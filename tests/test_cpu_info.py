"""What `cpu_info` says of each cpu (visible, ignored, suspended, its pc register, the
declarations on it), and that it moves nothing: REFERENCE.md, The session. `status` carries no
per-cpu reading. The two-cpu double is `test_stops_per_cpu`'s, whose pcs are m68k-dual's.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server_support import _running  # noqa: E402
from session_doubles import io_board, refused  # noqa: E402
from test_iotaps import BLOCK_MAP  # noqa: E402
from test_stops_per_cpu import _LAYOUT, _THREADS, _two_cpus  # noqa: E402
from test_tally import _tallying  # noqa: E402

from scry_mame import cpu_info as mcpu_info  # noqa: E402
from scry_mame import (
    cpus,  # noqa: E402
    sequence,  # noqa: E402
)
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import gdb_session as g  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

MAIN, SUB = ":maincpu", ":subcpu"
NONE_DECLARED = {"breakpoints": 0, "watches": 0, "regpoints": 0}


def _rows(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`cpu_info`'s rows by cpu, each without the `cpu` key that indexes it."""
    assert out["status"] == "ok", out
    return {row["cpu"]: {k: v for k, v in row.items() if k != "cpu"} for row in out["cpus"]}


# ------------------------------------------------------------------------------------ rows

def test_one_row_per_cpu_says_what_the_debugger_sees_of_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _two_cpus(monkeypatch, tmp_path, _THREADS)
    out = s.cpu_info()
    assert _rows(out) == {
        MAIN: {"visible": True, "ignored": False, "suspended": False,
               "pc": {"reg": "PC", "value": "0x00000b90"}, "declarations": NONE_DECLARED},
        SUB: {"visible": False, "ignored": False, "suspended": False,
              "pc": {"reg": "PC", "value": "0x00000542"}, "declarations": NONE_DECLARED}}, out
    assert [r["cpu"] for r in out["cpus"]] == [MAIN, SUB], "in `cpulist`'s order"
    assert out["cpu"]["available"] is False and list(out)[-1] == "session", out
    assert out["summary"] == "cpu_info: 2 cpus, :maincpu visible", out["summary"]


@pytest.mark.parametrize("named", ["subcpu", ":subcpu"])
def test_a_named_cpu_narrows_the_rows_to_its_own_and_the_summary_to_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, named: str,
) -> None:
    """The summary speaks of the row asked for, never of the rows the filter left out."""
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)
    reads: list[int] = []
    real = ses.reg

    def reg(name: str, *, thread: int) -> int:
        reads.append(thread)
        return int(real(name, thread=thread))

    monkeypatch.setattr(ses, "reg", reg)
    out = s.cpu_info(cpu=named)
    assert out["cpu"] == SUB and list(_rows(out)) == [SUB], out
    assert out["summary"] == "cpu_info of :subcpu: not visible", out["summary"]
    assert reads == [2], "only the named cpu's pc is read"


def test_a_name_is_judged_against_the_rows_the_call_gives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A cpu the machine's inventory names and `cpulist` does not (a phantom row) is refused
    rather than answered with no row; one only a declaration names is reachable by name."""
    _two_cpus(monkeypatch, tmp_path, _THREADS)
    monkeypatch.setattr(mstate.STATE, "machine_map", {"cpus": [
        {"tag": MAIN}, {"tag": SUB}, {"tag": ":audiocpu"}]})
    out = refused("no cpu 'audiocpu'", s.cpu_info(cpu="audiocpu"))
    assert out["code"] == "unknown_ref" and out["cpu_tags"] == [MAIN, SUB], out
    store = mstate.STATE.store
    assert store is not None
    store.add(dec.Declaration("breakpoint", "address", "0x400", cpu=":audiocpu"))
    out = s.cpu_info(cpu="audiocpu")
    assert list(_rows(out)) == [":audiocpu"], out
    assert out["summary"] == "cpu_info of :audiocpu: visibility unread", out["summary"]


def test_status_carries_the_cpus_and_no_per_cpu_reading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """What each cpu is doing is `cpu_info`'s row; `status` names the cpus there are."""
    _two_cpus(monkeypatch, tmp_path, _THREADS)
    out = s.status()
    assert out["cpu_tags"] == [MAIN, SUB], out
    gone = {"visible_cpu", "ignored", "suspended", "pc_by_cpu", "declarations_by_cpu"}
    assert not gone & set(out), gone & set(out)


def test_status_reports_a_latch_while_reading_the_pc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)

    def current_pc() -> int:
        ses.broken = "`print curpc` got no answer within 10 s"
        raise g.Timeout(ses.broken)

    monkeypatch.setattr(ses, "current_pc", current_pc)
    out = s.status()
    assert out["broken"] == "`print curpc` got no answer within 10 s", out


# -------------------------------------------------------------------------------------- pc

def test_a_stub_without_threads_reads_the_cpu_it_serves_and_says_why_not_the_others(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stock stub serves its first cpu alone, on thread 1; another cpu's pc is unavailable in
    the words `thread_for` refuses it with."""
    ses = _running(monkeypatch, tmp_path)
    assert ses.threads == {}
    rows = _rows(s.cpu_info())
    assert rows[MAIN]["pc"] == {"reg": "PC", "value": "0x000f2034"}, rows
    unread = rows[SUB]["pc"]["why"]
    assert "thread patch" in unread and "serves only :maincpu" in unread, unread


def test_a_register_map_the_stub_refuses_is_unread_with_the_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)

    def layout(thread: int) -> g.Layout:
        if thread == 2:
            raise g.Refused("the stub refused `qXfer:features:read:target.xml:0,400`: E01")
        return _LAYOUT

    monkeypatch.setattr(ses, "layout", layout)
    rows = _rows(s.cpu_info())
    assert rows[SUB]["pc"] == {
        "available": False,
        "why": "the stub refused `qXfer:features:read:target.xml:0,400`: E01"}, rows
    assert rows[MAIN]["pc"] == {"reg": "PC", "value": "0x00000b90"}, rows


def test_a_register_read_the_stub_refuses_is_unread_with_the_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)
    real = ses.reg

    def reg(name: str, *, thread: int) -> int:
        if thread == 2:
            raise g.Refused("the stub refused `p11`: E01")
        return int(real(name, thread=thread))

    monkeypatch.setattr(ses, "reg", reg)
    out = s.cpu_info()
    assert _rows(out)[SUB]["pc"] == {"available": False, "why": "the stub refused `p11`: E01"}, out
    assert out["session"].get("broken") is None, "a refusal is an answer, not a latch"


def test_a_cpu_the_patched_stub_names_no_thread_for_is_unread_with_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _two_cpus(monkeypatch, tmp_path, {1: MAIN})
    rows = _rows(s.cpu_info())
    assert rows[MAIN]["pc"] == {"reg": "PC", "value": "0x00000b90"}, rows
    assert rows[SUB]["pc"] == {
        "available": False,
        "why": "the stub names no thread for :subcpu; its threads are {1: ':maincpu'}"}, rows


def test_a_running_machine_names_no_pc_and_still_says_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)
    ses.go()
    out = s.cpu_info()
    assert out["session"]["running"] is True, out
    rows = _rows(out)
    assert all(r["pc"]["available"] is False for r in rows.values()), rows
    assert rows[MAIN]["visible"] is True and rows[SUB]["suspended"] is False, rows
    assert rows[SUB]["declarations"] == NONE_DECLARED, rows


def test_a_latch_during_the_pc_reads_is_a_broken_session_not_a_half_read_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)

    def reg(name: str, *, thread: int) -> int:
        if thread == 2:
            ses.broken = "`p` got no answer within 10 s"
            raise g.Timeout(ses.broken)
        return 0xB90

    monkeypatch.setattr(ses, "reg", reg)
    out = s.cpu_info()
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert "cpus" not in out, out


def test_a_console_that_lists_no_cpu_leaves_no_row_but_a_declared_cpus_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With no `cpulist` there is no row to read; a cpu a declaration names keeps its row, its
    declarations counted and every reading null."""
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        return "Unknown command\n\n" if command == "cpulist" else str(real(command, timeout))

    ses.monitor = monitor
    monkeypatch.setattr(mstate.STATE, "cpus", [])
    assert s.cpu_info()["cpus"] == []
    store = mstate.STATE.store
    assert store is not None
    store.add(dec.Declaration("breakpoint", "address", "0x400", cpu=MAIN))
    out = s.cpu_info()
    assert out["summary"] == "cpu_info: 1 cpu, the visible cpu unread", out["summary"]
    (row,) = _rows(out).values()
    assert all(row[k]["available"] is False for k in ("visible", "ignored", "suspended", "pc"))
    assert row["declarations"] == {"breakpoints": 1, "watches": 0, "regpoints": 0}, row


def test_a_latch_during_a_listing_is_a_broken_session_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "ignore":
            ses.broken = "`ignore` got no answer within 10 s"
            raise g.Timeout(ses.broken)
        return str(real(command, timeout))

    ses.monitor = monitor
    out = s.cpu_info()
    assert out["code"] == "session_broken" and "cpus" not in out, out


def test_a_perform_step_reads_it_stopped_and_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A step of a list, on either side of a release: running, the rows stand and no pc is
    read."""
    _two_cpus(monkeypatch, tmp_path, _THREADS)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.perform(steps=[{"op": "cpu_info"}, {"op": "resume"}, {"op": "cpu_info"}],
                    settle_seconds=0.05)
    stopped, running = (step["reply"] for step in out["ran"] if step["op"] == "cpu_info")
    assert _rows(stopped)[SUB]["pc"] == {"reg": "PC", "value": "0x00000542"}, stopped
    assert running["session"]["running"] is True and all(
        row["pc"]["available"] is False for row in _rows(running).values()), running


def test_no_session_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mstate.STATE, "ses", None)
    assert s.cpu_info()["code"] == "no_session"


# ---------------------------------------------------------------------- ignored, suspended

def test_ignored_and_suspended_are_the_consoles_own_listings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)
    ses.monitor("suspend :subcpu")
    ses.ignoring = [SUB]
    rows = _rows(s.cpu_info())
    assert (rows[SUB]["suspended"], rows[SUB]["ignored"]) == (True, True), rows
    assert (rows[MAIN]["suspended"], rows[MAIN]["ignored"]) == (False, False), rows
    assert rows[SUB]["pc"] == {"reg": "PC", "value": "0x00000542"}, "still read"
    ses.monitor("resume subcpu")
    ses.ignoring = []
    assert _rows(s.cpu_info())[SUB]["suspended"] is False


def test_a_listing_the_console_answers_in_neither_shape_is_null(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        return "Unknown command\n\n" if command == "suspend" else str(real(command, timeout))

    ses.monitor = monitor
    rows = _rows(s.cpu_info())
    assert rows[SUB]["suspended"]["available"] is False and rows[SUB]["ignored"] is False, rows
    assert cpus.suspended(ses) is None


# ---------------------------------------------------------------------------- declarations

def _declaring(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """A two-cpu board with an io space on the main cpu, the patched stub's two threads."""
    ses = _tallying(monkeypatch, tmp_path)
    io_board(monkeypatch, ses)          # the `mapi` answers; its one-cpu map is replaced below
    monkeypatch.setattr(mstate.STATE, "machine_map", {
        **BLOCK_MAP, "cpus": [{"tag": MAIN, "spaces": ["io", "program"]},
                              {"tag": SUB, "spaces": ["program"]}]})
    ses.threads = dict(_THREADS)
    return ses


def test_the_counts_are_this_servers_declarations_on_each_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A breakpoint on each cpu, a change watch on the sub cpu, a registerpoint on the visible
    one, an io tap and an expr watch: each counted on its cpu, the expr watch nowhere, and each
    count equal to the rows the `_list` tools give for that cpu."""
    ses = _declaring(monkeypatch, tmp_path)
    ses.exprs["d1==7fff"] = 0
    for ref, cpu in (("0x400", "maincpu"), ("0x542", "subcpu")):
        assert s.breakpoint_at(ref=ref, cpu=cpu)["status"] == "ok"
    assert s.watch_add(ref="0x2031fc", mode="change", length=4, cpu="subcpu")["status"] == "ok"
    assert s.regpoint_add(condition="pc==0xfffffffe")["status"] == "ok"
    assert s.watch_add(ref="0x6", mode="count", length=2, space="io")["status"] == "ok"
    assert s.watch_add(ref="d1==7fff", mode="expr")["status"] == "ok"
    counts = {tag: row["declarations"] for tag, row in _rows(s.cpu_info()).items()}
    assert counts == {MAIN: {"breakpoints": 1, "watches": 1, "regpoints": 1},
                      SUB: {"breakpoints": 1, "watches": 1, "regpoints": 0}}, counts
    for tag in (MAIN, SUB):
        mine = [r for r in s.declaration_list("watch",
                                              cpu=tag)["watches"] if r.get("mode") != "expr"]
        assert counts[tag]["breakpoints"] == len(s.declaration_list("breakpoint",
                                                                    cpu=tag)["breakpoints"])
        assert counts[tag]["watches"] == len(mine), (tag, mine)
    assert counts[MAIN]["regpoints"] == len(s.declaration_list("regpoint")["regpoints"])


def test_the_counts_are_records_in_any_state_and_never_a_foreign_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row the console lost is still counted while `declaration_list(kind="breakpoint")` reads it
    `gone`, a
    control is counted as the list lists it, and a row typed at the console is the list's
    `foreign`, never this server's."""
    _two_cpus(monkeypatch, tmp_path, _THREADS)
    assert s.breakpoint_at(ref="0x400", cpu="maincpu")["status"] == "ok"
    assert s.breakpoint_at(ref="0x25a4", role="control")["status"] == "ok"
    s.debug(command="bpclear 1")
    s.debug(command="bp 700")
    assert _rows(s.cpu_info())[MAIN]["declarations"] == {
        "breakpoints": 2, "watches": 0, "regpoints": 0}
    listed = s.declaration_list("breakpoint", cpu="maincpu")
    assert sorted(b["state"] for b in listed["breakpoints"]) == ["armed", "gone"], listed
    assert len(listed["breakpoints"]) == 2 and listed["foreign"], listed


def test_an_io_tap_on_no_named_cpu_is_counted_nowhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A tap armed while `cpulist` marked no cpu has no cpu to count under, as an expr watch."""
    _two_cpus(monkeypatch, tmp_path, _THREADS)
    monkeypatch.setattr(mstate.STATE, "tallies", {("0x6@io", None): {"space": "io"},
                                                  ("0x7@io", MAIN): {"space": "io"}})
    counts = {tag: row["declarations"] for tag, row in _rows(s.cpu_info()).items()}
    assert counts == {MAIN: {"breakpoints": 0, "watches": 1, "regpoints": 0},
                      SUB: NONE_DECLARED}, counts


def test_a_declaration_on_a_cpu_cpulist_does_not_list_gets_its_own_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A store row can name a cpu this machine lacks (brought back from another board of the
    family): it gets a row of its own, never dropped nor folded into another, with nothing read
    for a cpu the debugger does not list."""
    _two_cpus(monkeypatch, tmp_path, _THREADS)
    store = mstate.STATE.store
    assert store is not None
    store.add(dec.Declaration("breakpoint", "address", "0x400", cpu=":audiocpu"))
    out = s.cpu_info()
    assert [r["cpu"] for r in out["cpus"]] == [MAIN, SUB, ":audiocpu"], out
    unlisted = _rows(out)[":audiocpu"]
    assert all(unlisted[k] == {"available": False, "why": mcpu_info.UNLISTED_WHY}
               for k in ("visible", "ignored", "suspended", "pc")), unlisted
    assert unlisted["declarations"] == {"breakpoints": 1, "watches": 0, "regpoints": 0}, out


# ---------------------------------------------------------------------------- moves nothing

def test_cpu_info_and_status_move_nothing(monkeypatch: pytest.MonkeyPatch,
                                          tmp_path: Path) -> None:
    """With every advance and `Hc` made to raise, `cpu_info` and `status` answer, the stop
    count, the running flag and the visible cpu hold, and `cpu_info`, first of the session,
    sends each listing once and one pc read per thread, nothing else."""
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)

    def moved(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a reader moved the machine")

    reads: list[int] = []
    real_reg = ses.reg

    def reg(name: str, *, thread: int) -> int:
        reads.append(thread)
        return int(real_reg(name, thread=thread))

    for name in ("step", "go", "interrupt", "halt", "reset", "make_visible"):
        monkeypatch.setattr(ses, name, moved)
    monkeypatch.setattr(ses, "reg", reg)
    before = (ses.stop_count, ses.running, ses.visible_cpu)
    monkeypatch.setattr(mstate.STATE, "cpus", [])    # the cpu list not read yet this session
    ses.commands.clear()
    assert s.cpu_info()["status"] == "ok"
    assert Counter(ses.commands) == Counter(["cpulist", "ignore", "suspend"]), ses.commands
    assert sorted(reads) == sorted(_THREADS), reads
    assert s.status()["status"] == "ok"
    assert (ses.stop_count, ses.running, ses.visible_cpu) == before
