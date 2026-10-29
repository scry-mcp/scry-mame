"""`trace` (`trace`), judged against files MAME's own tracer wrote.

The doubles are captures: `fixtures/trace/` holds trace files a live session wrote
(`PROVENANCE.txt`), and the console's answers the fake gives are the ones that session read
back for arming and closing (`Tracing CPU '<tag>' to file <path>`, `Stopped tracing on CPU
'<tag>'`). The run itself is `run_for`'s, whose own tests judge it; here it is replaced by a
function that writes the captured file where the tracer would have and answers as `run_for`
answers, so what is under test is the arming, the close, the parse and the join.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
import sys
import tracemalloc
from pathlib import Path
from typing import Any

import pytest
from scry_core.reply_contract import unavailable  # noqa: E402
from session_doubles import SessionFields, use_table

from scry_mame import (
    advance,
    cpus,
    running,
    server,  # noqa: E402,F401 -- registers the tools and imports the boundary the shape guard wraps
)
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import mcp as mame_mcp
from scry_mame import state as mstate
from scry_mame import trace as mtrace

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "trace"
TAG = ":maincpu"
ARMED = "Tracing CPU '{tag}' to file {path}"
CLOSED = "Stopped tracing on CPU '{tag}'"
# program masks and the widths the tracer printed under them (M6)
WIDTHS = {"m68k-dual-maincpu-2f.trace.gz": (0xFFFFFF, 6),
          "m68k-dual-subcpu-2f.trace": (0xFFFFFF, 6), "v30-alt-2f.trace.gz": (0xFFFFF, 5),
          "circus-2f.trace": (0x7FFF, 4)}


def fixture(name: str) -> bytes:
    raw = (FIXTURES / name).read_bytes()
    return gzip.decompress(raw) if name.endswith(".gz") else raw


def lines(data: bytes) -> io.BytesIO:
    """`data` as the open file the parser reads a line at a time."""
    return io.BytesIO(data)


# ------------------------------------------------------------------------------- the parser

@pytest.mark.parametrize("name", sorted(WIDTHS))
def test_the_parser_reads_every_captured_file_as_a_known_count(name: str) -> None:
    data = fixture(name)
    mask, width = WIDTHS[name]
    p = mtrace.parse(lines(data), width, mask, TAG)
    # the known answer, by another instrument: a regex over the same bytes
    pcs = re.findall(rb"^([0-9A-F]+): ", data, re.M)
    assert p.lines == len(pcs) > 0
    assert set(p.counts) == {int(x, 16) for x in pcs}
    loops = sum(int(n) for n in re.findall(rb"^   \(loops for (\d+) instructions\)$", data, re.M))
    assert p.loop_sum == loops


def mutated(old: bytes, new: bytes) -> bytes:
    data = fixture("v30-alt-2f.trace.gz")
    assert data.count(old) >= 1
    return data.replace(old, new, 1)


def first_line() -> bytes:
    return fixture("v30-alt-2f.trace.gz").split(b"\n", 1)[0]


def test_a_line_of_no_shape_the_tracer_prints_is_refused_by_number() -> None:
    line = first_line()
    with pytest.raises(mstate.Invalid) as e:
        mtrace.parse(lines(mutated(line, b"MAME says hello")), 5, 0xFFFFF, TAG)
    assert e.value.code == "unexpected_answer" and "line 1 " in str(e.value)


def test_a_paged_pc_field_is_no_channel() -> None:
    line = first_line()
    field = line.split(b": ", 1)[0]
    with pytest.raises(mstate.Invalid) as e:
        mtrace.parse(lines(mutated(line, b"0012:3456: " + line.split(b": ", 1)[1])), 5,
                     0xFFFFF, TAG)
    assert e.value.code == "no_channel" and "paged" in str(e.value), field


def test_a_pc_field_one_digit_short_is_no_channel() -> None:
    line = first_line()
    short = line[1:]
    with pytest.raises(mstate.Invalid) as e:
        mtrace.parse(lines(mutated(line, short)), 5, 0xFFFFF, TAG)
    assert e.value.code == "no_channel" and "4 hex digits" in str(e.value)


def test_a_pc_field_one_digit_long_is_no_channel() -> None:
    line = first_line()
    with pytest.raises(mstate.Invalid) as e:
        mtrace.parse(lines(mutated(line, b"0" + line)), 5, 0xFFFFF, TAG)
    assert e.value.code == "no_channel" and "6 hex digits" in str(e.value)


def test_blank_lines_count_and_a_last_line_needs_no_newline() -> None:
    p = mtrace.parse(lines(b"000400: rte\n\n000402: nop"), 6, 0xFFFFFF, TAG)
    assert p.lines == 2 and p.last_pc == 0x402
    with pytest.raises(mstate.Invalid, match="line 3 "):
        mtrace.parse(lines(b"000400: rte\n\nnot a line\n"), 6, 0xFFFFFF, TAG)


def test_a_pc_past_the_mask_is_no_channel() -> None:
    with pytest.raises(mstate.Invalid) as e:
        mtrace.parse(lines(fixture("v30-alt-2f.trace.gz")), 5, 0xFFFF, TAG)
    assert e.value.code == "no_channel" and "mask" in str(e.value)


# ------------------------------------------------------------------------------- the join

def test_the_join_spells_a_place_as_every_reply_does_and_counts_the_unplaced() -> None:
    def place(addr: int) -> tuple[int, str] | None:
        return (0x400, "IRQ") if addr >= 0x400 else None
    rows, summary, unplaced = mtrace.join({0x300: 2, 0x400: 1, 0x40A: 5}, place, noloop=True)
    assert rows == [{"addr": "0x00000300", "count": 2},
                    {"addr": "0x00000400", "symbol": "IRQ", "count": 1},
                    {"addr": "0x0000040a", "symbol": "IRQ+0xa", "count": 5}]
    assert summary == [{"symbol": "IRQ", "addr": "0x00000400", "addresses": 2,
                        "first": "0x00000400", "last": "0x0000040a", "instructions": 6}]
    assert unplaced == 1
    rows, summary, _ = mtrace.join({0x400: 1}, place, noloop=False)
    assert rows == [{"addr": "0x00000400", "symbol": "IRQ"}] and "instructions" not in summary[0]


# ------------------------------------------------------------------------------- the caps

def test_the_caps_take_their_edge_and_refuse_one_past_it() -> None:
    for noloop in (False, True):
        fmax, mmax = mtrace.caps(noloop)
        mtrace.check_trace(frames=fmax, noloop=noloop)
        mtrace.check_trace(milliseconds=mmax, noloop=noloop)
        past: list[dict[str, Any]] = [{"frames": fmax + 1}, {"milliseconds": mmax + 1}]
        for kw in past:
            with pytest.raises(mstate.Invalid) as e:
                mtrace.check_trace(noloop=noloop, **kw)
            assert e.value.code == "bad_argument" and "could pass a gibibyte" in str(e.value)


def test_each_mode_is_judged_by_its_own_caps() -> None:
    """`noloop` writes every instruction, so its caps are the lower pair: the condensed cap is
    past them, and the noloop cap within the condensed ones."""
    assert mtrace.NOLOOP_FRAMES_MAX < mtrace.FRAMES_MAX
    assert mtrace.NOLOOP_MILLISECONDS_MAX < mtrace.MILLISECONDS_MAX
    mtrace.check_trace(frames=mtrace.NOLOOP_FRAMES_MAX + 1)
    mtrace.check_trace(milliseconds=mtrace.NOLOOP_MILLISECONDS_MAX + 1)
    past: list[dict[str, Any]] = [{"frames": mtrace.FRAMES_MAX},
                                  {"milliseconds": mtrace.MILLISECONDS_MAX}]
    for kw in past:
        with pytest.raises(mstate.Invalid):
            mtrace.check_trace(noloop=True, **kw)


def test_the_run_s_own_sentence_names_trace() -> None:
    with pytest.raises(mstate.Invalid) as e:
        mtrace.check_trace(frames=0)
    assert str(e.value).startswith("trace takes exactly one of")
    with pytest.raises(mstate.Invalid) as e:
        advance.check_run_for(frames=0)
    assert str(e.value).startswith("run_for takes exactly one of")


def test_noloop_is_a_boolean() -> None:
    with pytest.raises(mstate.Invalid) as e:
        mtrace.check_trace(frames=1, noloop=1)  # type: ignore[arg-type]
    assert e.value.code == "bad_argument"


def test_an_existing_dest_or_set_file_is_refused(tmp_path: Path) -> None:
    there = tmp_path / "t.trace"
    there.write_text("x")
    with pytest.raises(mstate.Invalid, match="already exists"):
        mtrace.check_trace(frames=1, dest=str(there))
    fresh = tmp_path / "u.trace"
    Path(str(fresh) + mtrace.SET_SUFFIX).write_text("x")
    with pytest.raises(mstate.Invalid, match="set file.*already exists"):
        mtrace.check_trace(frames=1, dest=str(fresh))


# ------------------------------------------------------------------------------- the flow

class Console(SessionFields):
    """The console the tool talks to: arming writes `data` where the tracer would."""

    def __init__(self, data: bytes, armed: str = ARMED, closed: str = CLOSED,
                 parked: int = 0x400) -> None:
        self.data, self.armed, self.closed, self.parked = data, armed, closed, parked
        self.sent: list[str] = []
        self.running = False
        self.broken: str | None = None
        self.writes = 0
        self.path: Path | None = None

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        self.sent.append(command)
        if command.startswith("history "):
            return "000400: rte\n"
        if command.startswith("trace off,"):
            return self.closed.format(tag=command.split(",", 1)[1])
        if command.startswith("trace "):
            path, tag = command[len("trace "):].split(",")[:2]
            self.path = Path(path)
            answer = self.armed.format(tag=tag, path=path)
            if answer.startswith("Tracing"):
                self.path.write_bytes(b"")
            return answer
        raise AssertionError(f"unexpected console command {command!r}")

    def current_pc(self) -> int:
        return self.parked

    def armed_count(self) -> int:
        return sum(1 for c in self.sent if c.startswith("trace ") and not c.startswith("trace off"))


def run_reply(pc: int, cpu: str = TAG, **more: Any) -> dict[str, Any]:
    return menvelope.envelope({"verdict": "ELAPSED", "frame_before": 10, "frame_after": 12,
                               "cpu": cpu, "pc": mstate.hex_addr(pc), **more})


@pytest.fixture
def board(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """`board(data, run=...)`: a console double installed, and `run_for` replaced by `run`,
    which by default writes `data` into the trace and answers ELAPSED parked at its last pc."""
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path / "scratch")
    (tmp_path / "scratch" / "snap").mkdir(parents=True)   # `start` makes it
    monkeypatch.setattr(cpus, "acting", lambda ses, cpu: TAG)
    monkeypatch.setattr(cpus, "program_mask", lambda cpu: 0xFFFFFF)
    monkeypatch.setattr(cpus, "visible_cpu", lambda ses: TAG)
    monkeypatch.setattr(cpus, "cpu_list", lambda ses: [TAG, ":subcpu"])
    monkeypatch.setattr(cpus, "ignored", lambda ses: [])
    monkeypatch.setattr(advance, "route_frames", lambda ses, instead="": {})

    def stop(ses: Console, scratch: Path) -> dict[str, Any]:
        ses.running = False
        ses.sent.append("<stop>")
        return {}
    monkeypatch.setattr(running, "stop", stop)

    def install(data: bytes, run: Any = None, mask: int | None = 0xFFFFFF,
                parked: int | None = None,
                **kw: Any) -> Console:
        """`parked`: the pc the traced cpu is parked on, as the last stop's cpu; None parks
        the machine's stop on the other cpu, so no start edge applies."""
        ses = Console(data, parked=parked or 0, **kw)
        monkeypatch.setattr(cpus, "program_mask", lambda cpu: mask)
        monkeypatch.setattr(mstate.STATE, "last_stop",
                            {"cpu": TAG if parked is not None else ":subcpu"})

        def default(*_: Any, **__: Any) -> dict[str, Any]:
            assert ses.path is not None
            ses.path.write_bytes(data)
            last = mtrace.parse(lines(data), None, None, TAG).last_pc
            return run_reply(last or 0)
        monkeypatch.setattr(advance, "run_for", run or default)
        return ses
    return install


def writing(data: bytes, pc: int) -> tuple[list[Console], Any]:
    """A run that writes `data` where the tracer would and ends parked at `pc`, for the console
    appended to the list it hands back."""
    held: list[Console] = []

    def run(*_: Any, **__: Any) -> dict[str, Any]:
        path = held[0].path
        assert path is not None
        path.write_bytes(data)
        return run_reply(pc)
    return held, run


def call(ses: Console, **kw: Any) -> dict[str, Any]:
    args = {"milliseconds": 0, "frames": 2, "dest": "", "seconds": 10.0, "cpu": "",
            "noloop": False, **kw}
    scratch = mstate.STATE.scratch
    assert scratch is not None
    # Closed as `mame_mcp.tool` closes it: `session` last, composed after the body.
    return mame_mcp.BOUNDARY.finished("trace", args, mtrace.trace(ses, scratch, **args))  # type: ignore[arg-type]


def test_a_trace_answers_the_set_and_writes_it_beside_the_file(board: Any) -> None:
    data = fixture("v30-alt-2f.trace.gz")
    ses = board(data, mask=0xFFFFF)
    out = call(ses)
    t = out["trace"]
    assert list(out)[-2:] == ["trace", "session"], "trace sits just before session"
    assert t["path"].endswith(os.path.join("", "snap", "trace-1.trace")), t["path"]
    assert t["bytes"] == len(data)
    rows = [json.loads(x) for x in Path(t["set_path"]).read_text().splitlines()]
    assert len(rows) == t["addresses"] > 0
    assert [r["addr"] for r in rows] == sorted(r["addr"] for r in rows)
    assert ("trace", t["path"]) in mstate.STATE.captures
    assert ses.sent[-1] == "trace off,:maincpu"


def test_a_cpu_with_no_table_places_nothing_and_says_so(board: Any) -> None:
    ses = board(fixture("circus-2f.trace"), mask=0x7FFF)
    t = call(ses)["trace"]
    assert t["unplaced"] == t["addresses"] and "no symbol table" in t["note"]


def test_the_summary_is_capped_and_counted(board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    data = fixture("v30-alt-2f.trace.gz")
    pcs = sorted(mtrace.parse(lines(data), None, None, TAG).counts)
    use_table(monkeypatch, TAG, table={f"S{i:03d}": pc for i, pc in enumerate(pcs[:100])})
    t = call(board(data, mask=0xFFFFF))["trace"]
    assert t["symbols_total"] == 100 and len(t["symbols"]) == mtrace.SYMBOLS_SHOWN
    assert t["truncated"] is True
    assert "symbols_truncated" not in t
    assert [s["symbol"] for s in t["symbols"][:2]] == ["S000", "S001"], "the lowest bases inline"


def test_a_summary_exactly_at_the_cap_is_not_truncated(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    data = fixture("v30-alt-2f.trace.gz")
    pcs = sorted(mtrace.parse(lines(data), None, None, TAG).counts)
    shown = mtrace.SYMBOLS_SHOWN
    use_table(monkeypatch, TAG, table={f"S{i:03d}": pc for i, pc in enumerate(pcs[:shown])})
    t = call(board(data, mask=0xFFFFF))["trace"]
    assert t["symbols_total"] == len(t["symbols"]) == shown and t["truncated"] is False


def test_the_parked_start_pc_is_counted(board: Any) -> None:
    data = fixture("m68k-dual-maincpu-parked-step3.trace")
    held, run = writing(data, 0x2600)
    ses = board(data, parked=0xF2034, run=run)
    held.append(ses)
    t = call(ses)["trace"]
    rows = [json.loads(x)["addr"] for x in Path(t["set_path"]).read_text().splitlines()]
    assert "0x000f2034" in rows and t["addresses"] == 4 and "parked on" in t["note"]
    assert "was not the cpu the last stop parked" not in t["note"], "parked and visible"


def test_the_parked_end_pc_leaves_the_set_when_it_ran_nowhere_else(board: Any) -> None:
    """The captured window ended on :maincpu at 0xba6, the file's last line and its only line
    at that pc: an arrival the window never executed."""
    data = fixture("m68k-dual-maincpu-parked-1f.trace")
    p = mtrace.parse(lines(data), None, None, TAG)
    assert p.last_pc == 0xBA6 and p.counts[0xBA6] == 1
    t = call(board(data))["trace"]
    rows = {json.loads(x)["addr"] for x in Path(t["set_path"]).read_text().splitlines()}
    assert "0x00000ba6" not in rows and "ended parked" in t["note"]
    assert t["addresses"] == len(p.counts) - 1
    assert t["instructions"] == p.lines + p.loop_sum - 1


def test_a_parked_end_pc_that_also_ran_earlier_is_kept_but_not_counted(board: Any) -> None:
    data = b"000400: rte\n000402: nop\n000400: rte\n"
    t = call(board(data))["trace"]
    rows = {json.loads(x)["addr"] for x in Path(t["set_path"]).read_text().splitlines()}
    assert rows == {"0x00000400", "0x00000402"}
    assert "ended parked" not in (t.get("note") or "") and t["instructions"] == 2


def test_under_noloop_the_parked_end_pc_loses_one_count(board: Any) -> None:
    data = b"000400: rte\n000402: nop\n000400: rte\n"
    t = call(board(data), noloop=True)["trace"]
    rows = [json.loads(x) for x in Path(t["set_path"]).read_text().splitlines()]
    assert rows == [{"addr": "0x00000400", "count": 1}, {"addr": "0x00000402", "count": 1}]
    assert t["instructions"] == 2


def test_a_parked_start_pc_already_in_the_set_is_still_counted(board: Any) -> None:
    data = b"000400: rte\n000402: nop\n"
    held, run = writing(data, 0x2600)
    ses = board(data, parked=0x400, run=run)
    held.append(ses)
    t = call(ses)["trace"]
    assert t["addresses"] == 2 and t["instructions"] == 3
    held, run = writing(data, 0x2600)
    ses = board(data, parked=0x400, run=run)
    held.append(ses)
    rows = Path(call(ses, noloop=True)["trace"]["set_path"]).read_text().splitlines()
    assert [json.loads(x)["count"] for x in rows] == [2, 1]


def test_a_pc_parked_at_both_edges_stays_in_the_condensed_set(board: Any) -> None:
    """The cpu parked on 0x400 executes it first, which the tracer armed there does not log, and
    ends parked on it again, logged once on arrival: the window executed it once, so the start
    edge puts back what the end edge takes (v30-alt's frame stop on its vblank handler)."""
    data = b"000402: nop\n000404: nop\n000400: rte\n"
    for noloop in (False, True):
        held, run = writing(data, 0x400)
        ses = board(data, parked=0x400, run=run)
        held.append(ses)
        t = call(ses, noloop=noloop)["trace"]
        rows = [json.loads(x) for x in Path(t["set_path"]).read_text().splitlines()]
        assert [r["addr"] for r in rows] == ["0x00000400", "0x00000402", "0x00000404"]
        assert t["instructions"] == 3 and "is not in the set" not in t["note"]
        if noloop:
            assert [r["count"] for r in rows] == [1, 1, 1]


def test_a_cpu_the_run_did_not_stop_on_keeps_its_last_line_and_says_why(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """m68k-dual's subcpu spinning on `bra $542` while the run stops on maincpu, whose survey pc
    is the same number: no edge is the subcpu's, and `note` says what its last line is."""
    data = b"000542: bra     $542\n000542: bra     $542\n"
    held, run = writing(data, 0x542)
    ses = board(data, run=run)
    held.append(ses)
    monkeypatch.setattr(cpus, "acting", lambda ses, cpu: ":subcpu")
    monkeypatch.setattr(mstate.STATE, "last_stop", {"cpu": TAG})
    t = call(ses, cpu="subcpu", noloop=True)["trace"]
    rows = [json.loads(x) for x in Path(t["set_path"]).read_text().splitlines()]
    assert rows == [{"addr": "0x00000542", "count": 2}] and t["instructions"] == 2
    assert "stopped on :maincpu, not :subcpu" in t["note"]


@pytest.mark.parametrize("survey", [{"pc": mstate.hex_addr(0x402)},
                                    {"cpu": unavailable("no cpu marked"),
                                     "pc": mstate.hex_addr(0x402)},
                                    {"cpu": TAG, "pc": unavailable("not read")}],
                         ids=["naming no cpu", "with its cpu unavailable", "with no pc"])
def test_a_survey_naming_no_cpu_corrects_no_end_edge(board: Any, survey: dict[str, Any]) -> None:
    """The end edge needs the cpu the run stopped on and its pc: a survey without either corrects
    nothing."""
    data = b"000400: rte\n000402: nop\n"
    held: list[Console] = []

    def run(*_: Any, **__: Any) -> dict[str, Any]:
        assert held[0].path is not None
        held[0].path.write_bytes(data)
        return menvelope.envelope({"verdict": "ELAPSED", "frame_before": 10, "frame_after": 12,
                                   **survey})
    ses = board(data, run=run)
    held.append(ses)
    t = call(ses)["trace"]
    assert t["addresses"] == 2 and t["instructions"] == 2 and "stopped on" not in str(t.get("note"))
    assert "ended parked" not in str(t.get("note")), "no end edge, so no end-edge note"


def test_noloop_reaches_the_console(board: Any) -> None:
    data = b"000400: rte\n000402: nop\n"
    for noloop, armed in ((True, ",noloop"), (False, ",:maincpu")):
        ses = board(data)
        call(ses, noloop=noloop)
        arming = [c for c in ses.sent if c.startswith("trace ") and "off" not in c]
        assert len(arming) == 1 and arming[0].endswith(armed)


def test_an_arming_answer_naming_another_file_is_refused(board: Any) -> None:
    ses = board(b"000400: rte\n", armed="Tracing CPU '{tag}' to file /elsewhere.trace")
    out = call(ses)
    assert out["code"] == "unexpected_answer" and ses.sent[-1] == "trace off,:maincpu"


def test_the_file_is_read_a_line_at_a_time_never_whole(board: Any) -> None:
    """tracemalloc counts what the call allocated, which the host does not move."""
    data = b"000400: nop\n000402: bra     $400\n" * 100_000
    held, run = writing(data, 0x2600)
    ses = board(data, run=run)
    held.append(ses)
    tracemalloc.start()
    try:
        t = call(ses)["trace"]
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert t["bytes"] == len(data) and t["addresses"] == 2
    assert peak < len(data) // 8, f"peak {peak} for a file of {len(data)}"


@pytest.mark.parametrize(("error", "code", "closed"), [
    (gs.SessionError("the stub stopped answering"), "session_broken", None),
    (gs.Refused("E01"), "readback_refused", True)])
def test_a_session_error_in_the_run_answers_carrying_the_trace(
        board: Any, monkeypatch: pytest.MonkeyPatch, error: Exception, code: str,
        closed: bool | None) -> None:
    """The server answers a session error as it answers every tool's; `trace` hands its file
    back beside it, and closes the tracer only on a channel the error did not break."""
    data = b"000400: rte\n"

    def run(*_: Any, **__: Any) -> dict[str, Any]:
        assert ses.path is not None
        ses.path.write_bytes(data)
        raise error
    ses = board(data, run=run)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    out = call(ses)
    shut = out["trace"]["closed"]
    assert out["code"] == code and (shut is closed if closed is not None
                                    else shut["available"] is False), out["trace"]
    assert out["trace"]["bytes"] == len(data) and list(out)[-2:] == ["trace", "session"]
    assert ("trace off,:maincpu" in ses.sent) is bool(closed)
    assert not mstate.STATE.captures
    if closed is None:
        assert "named in the reply's `trace` block" in out["message"]
        assert "under `trace`" in out["message"], out["message"]


def test_an_answered_session_error_whose_close_fails_says_the_way_out(board: Any) -> None:
    """The channel survived the error, the close did not confirm: the tracer may still be
    writing, so the reply is the unconfirmed close's, naming what the run raised."""
    def run(*_: Any, **__: Any) -> dict[str, Any]:
        raise gs.Refused("E01")
    ses = board(b"", run=run, closed="Not tracing")
    out = call(ses)
    assert out["code"] == "readback_refused" and out["trace"]["closed"] is False
    assert "E01" in out["message"] and "debug(\"trace off,:maincpu\")" in out["message"]


def test_a_machine_running_under_the_run_closes_the_tracer_and_latches_nothing(
        board: Any) -> None:
    def run(*_: Any, **__: Any) -> dict[str, Any]:
        raise gs.NotStopped("running")
    ses = board(b"", run=run)
    with pytest.raises(gs.NotStopped):
        call(ses)
    assert ses.sent[-1] == "trace off,:maincpu" and ses.broken is None


def test_a_refused_trace_is_not_listed_by_captures(board: Any) -> None:
    """`captures` lists what was checked and handed back: a refused trace's path is in its own
    reply, as a recording answered still open is."""
    with pytest.raises(mstate.Invalid):
        call(board(b""))

    def refused(*_: Any, **__: Any) -> dict[str, Any]:
        raise mstate.Invalid("no_progress", "the counter did not move")
    with pytest.raises(mstate.Invalid):
        call(board(b"", run=refused))
    assert call(board(b"", closed="Not tracing"))["code"] == "readback_refused"
    assert not mstate.STATE.captures


def test_a_close_whose_answer_latched_the_session_is_session_broken(board: Any) -> None:
    ses = board(b"000400: rte\n000402: nop\n")
    answer = Console.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("trace off"):
            ses.broken = "the wait ran out"
            raise gs.SessionError("no answer")
        return answer(ses, command, timeout)
    ses.monitor = monitor
    out = call(ses)
    assert out["code"] == "session_broken" and out["trace"]["closed"]["available"] is False


def test_an_ignored_cpu_s_refusal_names_it(board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cpus, "ignored", lambda ses: [TAG])
    with pytest.raises(mstate.Invalid) as e:
        call(board(fixture("m68k-dual-subcpu-ignored-2f.trace")))
    assert "lists :maincpu as ignored" in str(e.value)


def test_a_close_under_a_stop_that_broke_the_session_is_closed_null(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def left(*_: Any, **__: Any) -> dict[str, Any]:
        ses.running = True
        return menvelope.invalid("not_settled", "still moving")

    def broke(s_: Console, scratch: Path) -> dict[str, Any]:
        s_.broken = "the stub stopped answering"
        return {}
    monkeypatch.setattr(running, "stop", broke)
    ses = board(b"", run=left)
    out = call(ses)
    assert out["code"] == "not_settled" and out["trace"]["closed"]["available"] is False
    assert "trace off,:maincpu" not in ses.sent


class _Alive:
    def poll(self) -> int | None:
        return None


def test_an_invalid_reply_after_the_close_stopped_the_machine_says_stopped(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def left(*_: Any, **__: Any) -> dict[str, Any]:
        ses.running = True
        return menvelope.invalid("not_settled", "still moving")
    ses = board(b"", run=left)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "proc", _Alive())
    out = call(ses)
    assert out["trace"]["closed"] is True and ses.sent[-2:] == ["<stop>", "trace off,:maincpu"]
    assert out["session"]["running"] is False


def test_a_failed_arming_whose_close_breaks_the_session_says_so(board: Any) -> None:
    ses = board(b"", armed="Huh? {path}")

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("trace off"):
            raise gs.SessionError("no answer")
        return Console.monitor(ses, command, timeout)
    ses.monitor = monitor
    out = call(ses)
    assert out["code"] == "session_broken" and "may still be armed" in out["message"].lower()


@pytest.mark.skipif(sys.platform == "win32",
                    reason="its file name passes the 260 characters a Windows path holds")
def test_an_arming_answer_the_console_wrapped_is_read_whole(board: Any) -> None:
    """A path long enough to carry the answer past the console's column comes back cut hard
    there, as MAME's wrap cuts a line with no space to break at."""
    ses = board(b"000400: rte\n000402: nop\n000400: rte\n")
    cols = gs.CONSOLE_WRAP_COLS
    answer = Console.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        text = answer(ses, command, timeout)
        return "\n".join(text[i:i + cols] for i in range(0, len(text), cols))
    ses.monitor = monitor
    scratch = mstate.STATE.scratch
    assert scratch is not None
    dest = scratch / ("x" * (cols - len(str(scratch))) + ".trace")
    t = call(ses, dest=str(dest))["trace"]
    assert len(f"Tracing CPU ':maincpu' to file {dest}") > cols and t["addresses"] == 2


def test_an_empty_trace_is_refused_naming_both_causes(board: Any) -> None:
    with pytest.raises(mstate.Invalid) as e:
        call(board(b""))
    assert e.value.code == "readback_refused" and "is empty" in str(e.value)
    assert "executed nothing" in str(e.value) and "recorded nothing" in str(e.value)
    assert e.value.fields["trace"]["closed"] is True


def test_a_trace_of_only_interrupt_lines_is_refused_like_an_empty_one(board: Any) -> None:
    """An ignored cpu executes nothing the tracer logs, yet its interrupt hook still writes
    `(interrupted at ...)` lines: a file of those holds no executed address."""
    data = fixture("m68k-dual-subcpu-ignored-2f.trace")
    assert data and not re.search(rb"^[0-9A-F]+: ", data, re.M)
    with pytest.raises(mstate.Invalid) as e:
        call(board(data))
    assert e.value.code == "readback_refused" and "executed nothing" in str(e.value)
    assert not list((mstate.STATE.scratch or Path()).glob("snap/*.set.jsonl"))


def test_a_refused_route_arms_nothing(board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    ses = board(b"000400: rte\n")

    def frameless(_: Any, instead: str = "") -> dict[str, Any]:
        raise mstate.Invalid("no_channel", "no frame counter")
    monkeypatch.setattr(advance, "route_frames", frameless)
    with pytest.raises(mstate.Invalid, match="no frame counter"):
        call(ses)
    assert ses.armed_count() == 0
    assert not list((mstate.STATE.scratch or Path()).glob("snap/*.trace"))


def test_an_unknown_cpu_arms_nothing(board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    ses = board(b"000400: rte\n")

    def unknown(_: Any, cpu: str) -> str:
        raise mstate.Invalid("unknown_ref", f"no cpu {cpu}")
    monkeypatch.setattr(cpus, "acting", unknown)
    with pytest.raises(mstate.Invalid, match="no cpu nosuch"):
        call(ses, cpu="nosuch")
    assert ses.armed_count() == 0


@pytest.mark.parametrize(("answer", "code"), [
    ("Error opening file '{path}'", "host_failed"), ("Huh? {path}", "unexpected_answer")])
def test_a_refused_arming_runs_nothing_and_sends_off(board: Any, answer: str, code: str) -> None:
    ran: list[int] = []
    ses = board(b"000400: rte\n", armed=answer, run=lambda *a, **k: ran.append(1))
    out = call(ses)
    assert out["status"] == "INVALID" and out["code"] == code
    assert not ran and ses.sent[-1] == "trace off,:maincpu"


def test_a_close_that_fails_is_readback_refused_with_no_set_file(board: Any) -> None:
    ses = board(b"000400: rte\n", closed="Not tracing")
    out = call(ses)
    assert out["code"] == "readback_refused" and out["trace"]["closed"] is False
    assert "trace off,:maincpu" in out["message"] and "ELAPSED at frame 12" in out["message"]
    assert not list((mstate.STATE.scratch or Path()).glob("snap/*.set.jsonl"))


def test_an_invalid_run_carries_the_trace_and_no_set_file(board: Any) -> None:
    def refused(*_: Any, **__: Any) -> dict[str, Any]:
        raise mstate.Invalid("no_progress", "the counter did not move")
    ses = board(b"", run=refused)
    with pytest.raises(mstate.Invalid) as e:
        call(ses)
    assert e.value.code == "no_progress" and e.value.fields["trace"]["closed"] is True
    assert ses.sent[-1] == "trace off,:maincpu"
    assert not list((mstate.STATE.scratch or Path()).glob("snap/*.set.jsonl"))


def test_a_machine_left_running_is_stopped_before_the_close(board: Any) -> None:
    def left(*_: Any, **__: Any) -> dict[str, Any]:
        ses.running = True
        raise mstate.Invalid("not_settled", "still moving")
    ses = board(b"", run=left)
    with pytest.raises(mstate.Invalid) as e:
        call(ses)
    assert ses.sent[-2:] == ["<stop>", "trace off,:maincpu"]
    assert e.value.fields["trace"]["closed"] is True


def test_an_invalid_reply_keeps_its_code_and_gains_the_trace(board: Any) -> None:
    ses = board(b"", run=lambda *a, **k: menvelope.invalid("frames_went_backwards", "back"))
    out = call(ses)
    assert out["code"] == "frames_went_backwards" and out["trace"]["closed"] is True
    assert not mstate.STATE.captures
    assert list(out)[-2:] == ["trace", "session"]


def test_a_given_dest_is_where_the_tracer_writes(board: Any, tmp_path: Path) -> None:
    dest = tmp_path / "mine.trace"
    t = call(board(b"000400: rte\n000402: nop\n"), dest=str(dest))["trace"]
    assert t["path"] == str(dest) and t["set_path"] == str(dest) + mtrace.SET_SUFFIX


def test_a_parked_cpu_that_is_not_visible_is_not_read_and_says_so(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    ses = board(b"000400: rte\n000402: nop\n000400: rte\n", parked=0x300)
    monkeypatch.setattr(cpus, "visible_cpu", lambda ses: ":subcpu")
    t = call(ses)["trace"]
    assert "not visible" in t["note"] and t["addresses"] == 2


def test_a_cpu_with_no_disassembler_arms_nothing(board: Any) -> None:
    ses = board(b"")
    answer = Console.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("history "):
            return "No disassembler available for device ':audiocpu'\n"
        return answer(ses, command, timeout)
    ses.monitor = monitor
    out = call(ses)
    assert out["code"] == "no_channel" and ses.armed_count() == 0


def test_a_machine_the_stop_cannot_bring_back_is_not_closed(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def left(*_: Any, **__: Any) -> dict[str, Any]:
        ses.running = True
        raise mstate.Invalid("not_settled", "still moving")
    monkeypatch.setattr(running, "stop", lambda s_, scratch: {})
    ses = board(b"", run=left)
    out = call(ses)
    assert out["code"] == "readback_refused" and out["trace"]["closed"] is False
    assert "refused `not_settled`" in out["message"] and "trace off,:maincpu" not in ses.sent


def test_a_close_whose_answer_never_comes_is_not_closed(board: Any) -> None:
    ses = board(b"000400: rte\n000402: nop\n")
    answer = Console.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("trace off"):
            raise gs.SessionError("no answer")
        return answer(ses, command, timeout)
    ses.monitor = monitor
    out = call(ses)
    assert out["code"] == "readback_refused" and out["trace"]["closed"] is False


def test_a_foreign_exception_in_the_run_still_closes_the_tracer(board: Any) -> None:
    def boom(*_: Any, **__: Any) -> dict[str, Any]:
        raise RuntimeError("a bug elsewhere")
    ses = board(b"", run=boom)
    with pytest.raises(RuntimeError):
        call(ses)
    assert ses.sent[-1] == "trace off,:maincpu"


def test_a_session_that_broke_after_an_ok_run_is_session_broken(board: Any) -> None:
    data = b"000400: rte\n"

    def run(*_: Any, **__: Any) -> dict[str, Any]:
        assert ses.path is not None
        ses.path.write_bytes(data)
        ses.broken = "the channel died"
        return run_reply(0x400)
    ses = board(data, run=run)
    out = call(ses)
    assert out["code"] == "session_broken" and out["trace"]["closed"]["available"] is False


def test_a_cpu_with_no_program_space_row_is_read_unjudged_and_says_so(board: Any) -> None:
    t = call(board(b"0012: nop\n0014: rts\n0012: nop\n", mask=None))["trace"]
    assert "no width or range judgement" in t["note"] and t["addresses"] == 2


def test_a_file_of_the_wrong_shape_is_refused_carrying_the_trace(board: Any) -> None:
    data = b"000400: rte\nnot a trace line\n"
    held, run = writing(data, 0x400)
    ses = board(data, run=run)
    held.append(ses)
    with pytest.raises(mstate.Invalid) as e:
        call(ses)
    assert e.value.code == "unexpected_answer" and e.value.fields["trace"]["closed"] is True



# ----------------------------------------------------------- each guard of the edges, by its case

def test_an_unterminated_last_loop_line_is_read_whole() -> None:
    p = mtrace.parse(lines(b"000400: rte\n   (loops for 7 instructions)"), 6, 0xFFFFFF, TAG)
    assert (p.lines, p.loop_sum) == (1, 7)


def test_a_cpu_parked_on_pc_zero_has_its_start_counted(board: Any) -> None:
    """Zero is a pc like any other: the parked start is counted on it too."""
    data = b"000402: nop\n000404: nop\n"
    held, run = writing(data, 0x2600)
    ses = board(data, parked=0, run=run)
    held.append(ses)
    t = call(ses)["trace"]
    rows = [json.loads(x)["addr"] for x in Path(t["set_path"]).read_text().splitlines()]
    assert "0x00000000" in rows and t["instructions"] == 3 and "parked on" in t["note"]


def test_a_last_stop_naming_no_cpu_is_the_first_cpu_s(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stop recorded with no cpu was the first cpu's, the one a stub without threads binds."""
    data = b"000402: nop\n"
    held, run = writing(data, 0x2600)
    ses = board(data, parked=0x400, run=run)
    held.append(ses)
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    t = call(ses)["trace"]
    rows = [json.loads(x)["addr"] for x in Path(t["set_path"]).read_text().splitlines()]
    assert "0x00000400" in rows, rows


def test_two_traces_in_a_session_write_two_files(board: Any) -> None:
    data = b"000400: rte\n"
    first = call(board(data))["trace"]["path"]
    second = call(board(data))["trace"]["path"]
    assert first.endswith("trace-1.trace") and second.endswith("trace-2.trace"), (first, second)


def test_a_cpu_the_last_stop_did_not_park_says_its_first_instruction_may_be_unlogged(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The start edge's twin of the end edge's caveat: MAME's 68000 resumes an instruction it
    yielded inside with no hook, so for a cpu the stop did not park, the instruction it was
    inside when the window began is finished in it and never logged."""
    data = b"000542: bra     $542\n"
    held, run = writing(data, 0x542)
    ses = board(data, run=run)
    held.append(ses)
    monkeypatch.setattr(cpus, "acting", lambda ses, cpu: ":subcpu")
    monkeypatch.setattr(mstate.STATE, "last_stop", {"cpu": TAG})
    t = call(ses, cpu="subcpu")["trace"]
    assert "was not the cpu the last stop parked (:maincpu was)" in t["note"], t["note"]


def test_a_stop_that_recorded_no_cpu_is_named_by_no_cpu_in_the_start_edge_note(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first cpu is ASSUMED parked when the stop recorded none, and an assumption is not a
    record: the note says the traced cpu was not the one parked, and names no cpu as the one
    that was."""
    data = b"000542: bra     $542\n"
    held, run = writing(data, 0x542)
    ses = board(data, run=run)
    held.append(ses)
    monkeypatch.setattr(cpus, "acting", lambda ses, cpu: ":subcpu")
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    t = call(ses, cpu="subcpu")["trace"]
    start_edge = t["note"].split("; ")[0]
    assert "was not the cpu the last stop parked:" in start_edge, t["note"]
    assert "was)" not in start_edge and TAG not in start_edge, t["note"]


def test_a_stop_that_recorded_no_cpu_is_the_first_cpus_and_tracing_it_says_nothing_of_it(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: with no cpu recorded the first cpu is the parked one, so tracing it carries
    no start-edge note at all."""
    data = b"000542: bra     $542\n"
    held, run = writing(data, 0x542)
    ses = board(data, run=run)
    held.append(ses)
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    t = call(ses)["trace"]
    assert "was not the cpu the last stop parked" not in str(t.get("note")), t.get("note")


def test_the_tracer_is_closed_even_when_answering_the_session_error_raises(
        board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def run(*_: Any, **__: Any) -> dict[str, Any]:
        raise gs.Refused("E01")
    ses = board(b"", run=run)
    monkeypatch.setattr(mstate.STATE, "ses", ses)

    def broken_reply(*_: Any, **__: Any) -> dict[str, Any]:
        raise RuntimeError("the reply could not be built")
    monkeypatch.setattr(running, "session_error_reply", broken_reply)
    with pytest.raises(RuntimeError):
        call(ses)
    assert "trace off,:maincpu" in ses.sent, ses.sent
