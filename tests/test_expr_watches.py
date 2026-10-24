"""A watch of mode `expr`: any expression the MAME debugger evaluates, read at every stop.

The debugger exposes more than memory and registers: `beamx`, `beamy` (where the beam is),
`frame`, `cycles`, `totalcycles`, `lastinstructioncycles`, and any expression over them and
the registers. A stop survey that carried only the frame made a session type `debug("print
beamy")` after every stop to read the geometry it was measuring. An `expr` watch is a
declaration like the others, so it rides on every stop's `watches`, is listed, cleared and
re-evaluated at the next `start`; and every expression declared is read in ONE `print`
beside the frame (the console prints several expressions space-separated), so the cost of a
stop does not grow with the number of watches. `run_for` reads `totalcycles` the same way
and reports the cycles the run took, which is the exact clock behind an emulated duration.

The mode rests on the debugger's own expression evaluator, and the store rule it needs is
stated as this server's own.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import bp_records, refused  # noqa: E402
from test_server import _install, _RegisterSession, _running  # noqa: E402
from test_watches import _watching  # noqa: E402

import gdb_session as g  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_arming as arming  # noqa: E402
import mame_breakpoints as breakpoints  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_read as read  # noqa: E402
import mame_rearm as rearming  # noqa: E402
import mame_watches as watches  # noqa: E402
import server as s  # noqa: E402

# ------------------------------------------------------------------ the declaration


def test_an_expr_watch_carries_no_width_no_format_and_no_address() -> None:
    w = dec.Declaration("watch", "expr", "beamy", watch_mode="expr")
    assert w.to_dict() == {"kind": "watch", "by": "expr", "ref": "beamy", "width": None,
                           "fmt": None, "watch_mode": "expr"}
    assert dec.Declaration.from_dict(w.to_dict()) == w
    assert dec.resolve(w, {}).state == "expr"
    assert dec.is_stale(w, "another") is False, "an expression re-resolves against nothing"
    with pytest.raises(dec.DeclarationError, match="length"):
        dec.Declaration("watch", "expr", "beamy", width=2, fmt="u16", watch_mode="expr")
    with pytest.raises(dec.DeclarationError, match="expr"):
        dec.Declaration("watch", "symbol", "beamy", watch_mode="expr")
    with pytest.raises(dec.DeclarationError, match="expr"):
        dec.Declaration("watch", "expr", "beamy", width=2, fmt="u16", watch_mode="show")
    with pytest.raises(dec.DeclarationError, match="expr"):
        dec.Declaration("breakpoint", "expr", "beamy")


# ------------------------------------------------------------------ the console reader


def test_print_values_reads_several_expressions_in_one_call_and_refuses_a_short_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {"beamy": 0xF8, "totalcycles": 0x7A124B}
    values = read.print_values(ses, ["frame", "beamy", "totalcycles"])  # type: ignore[arg-type]
    assert values == [100, 0xF8, 0x7A124B]
    assert ses.commands[-1] == "print frame,beamy,totalcycles"
    assert read.frame(ses) == 100 and ses.commands[-1] == "print frame"  # type: ignore[arg-type]
    with pytest.raises(g.SessionError, match="values for 3 expressions"):
        read.print_values(ses, ["frame", "beamy", "nosuchthing"])  # type: ignore[arg-type]


# ------------------------------------------------------------------ declaring one


def test_watch_add_expr_validates_the_expression_on_the_console_and_answers_its_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {"beamy": 0xF8}
    out = s.watch_add(ref="beamy", mode="expr")
    assert out["status"] == "ok" and out["mode"] == "expr" and out["by"] == "expr"
    assert out["reading"] == {"available": True, "value": 0xF8, "hex": "0xf8"}
    assert out["armed"] is False and out["state"] == "evaluated"
    assert "width" not in out and "fmt" not in out
    assert "print beamy" in ses.commands, "validated on the console before it is stored"
    bad = refused("nosuchthing", s.watch_add(ref="nosuchthing", mode="expr"))
    assert bad["code"] == "bad_argument"
    assert not any(d.ref == "nosuchthing" for d in arming.store().declarations())
    refused("length", s.watch_add(ref="beamy", mode="expr", length=2))
    refused("needs a length", s.watch_add(ref="0x2031fc", mode="show"))
    refused("by", s.watch_add(ref="beamy", mode="expr", by="symbol"))


def test_watch_add_expr_while_running_stores_and_reads_no_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {"beamy": 0xF8}
    ses.go()
    out = s.watch_add(ref="beamy", mode="expr")
    assert out["status"] == "ok" and out["while_running"] is True and "value" not in out


# ------------------------------------------------------------------ at every stop


def test_a_stop_reads_the_frame_and_every_expression_in_one_print(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {"beamy": 0xF8, "totalcycles": 0x7A124B}
    s.watch_add(ref="beamy", mode="expr")
    s.watch_add(ref="totalcycles", mode="expr")
    ses.commands.clear()
    out = s.step()
    watched = {w["ref"]: w for w in out["watches"]}
    assert watched["beamy"] == {"ref": "beamy", "state": "evaluated",
                                "reading": {"available": True, "value": 0xF8, "hex": "0xf8"}}
    assert watched["totalcycles"]["reading"]["value"] == 0x7A124B
    prints = [c for c in ses.commands if c.startswith("print ")]
    assert prints == ["print frame,beamy,totalcycles"], prints
    assert out["frame"] == ses.frame


def test_an_expression_the_console_stops_answering_is_unreadable_and_the_frame_survives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {"beamy": 0xF8}
    s.watch_add(ref="beamy", mode="expr")
    del ses.exprs["beamy"]                     # a cpu switch, say: the name no longer resolves
    out = s.step()
    assert out["frame"] == ses.frame
    (w,) = out["watches"]
    assert w["state"] == "evaluated" and w["reading"]["available"] is False
    assert "beamy" in w["reading"]["why"]


# ------------------------------------------------------------------ list, clear, rearm


def test_expr_watches_are_listed_cleared_and_come_back_evaluated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)        # the double that answers `wplist`
    ses.exprs = {"beamy": 0xF8}
    s.watch_add(ref="beamy", mode="expr")
    (row,) = s.declaration_list("watch")["watches"]
    assert row["mode"] == "expr" and row["by"] == "expr" and row["state"] == "evaluated"
    assert "addr" not in row and row["length"]["available"] is False, row
    assert row["fmt"]["available"] is False and row["cpu"]["available"] is False, row
    (evaluated,) = rearming.rearm_breakpoints_and_watches(ses)["evaluated"]  # type: ignore[arg-type]
    assert evaluated["ref"] == "beamy" and evaluated["cpu"]["available"] is False, evaluated
    out = s.declaration_clear("watch", ref="beamy")
    assert out["declarations_cleared"] == 1 and out["disarmed"] == []
    assert s.declaration_list("watch")["watches"] == []


# ------------------------------------------------------------------ run_for's clock


def test_run_for_reports_the_cycles_the_run_took(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _RegisterSession(bits=32, frame=10, stop_after=4)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    out = s.run_for(milliseconds=100, seconds=5.0)
    assert out["verdict"] == "ELAPSED"
    assert out["cycles"] == (out["frame_after"] - out["frame_before"]) * reg.cycles_per_frame
    assert out["cycles"] > 0


# ------------------------------------------------------------------ the odd branches


def test_expression_refs_and_evaluation_answer_empty_with_no_store_or_no_expressions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import mame_state as mstate
    ses = _running(monkeypatch, tmp_path)
    assert watches.expression_refs() == [] and watches.evaluate_expressions(ses) == {}  # type: ignore[arg-type]
    assert watches.evaluate_watches(ses) == []  # type: ignore[arg-type]
    monkeypatch.setattr(mstate.STATE, "store", None)
    assert watches.expression_refs() == [] and watches.evaluate_watches(ses) == []  # type: ignore[arg-type]


def test_evaluate_watches_prints_the_expressions_itself_when_nobody_handed_them_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {"beamy": 0xF8}
    s.watch_add(ref="beamy", mode="expr")
    ses.commands.clear()
    (w,) = watches.evaluate_watches(ses)  # type: ignore[arg-type]
    assert w["reading"]["value"] == 0xF8 and ses.commands == ["print beamy"]
    del ses.exprs["beamy"]
    (w,) = watches.evaluate_watches(ses)  # type: ignore[arg-type]
    assert w["reading"]["available"] is False


def test_a_read_watch_declared_by_expr_is_refused_and_a_width_less_scalar_is_one_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    refused("by is one of", s.watch_add(ref="0x2031fc", mode="show", length=2, by="expr"))
    one = dec.Declaration("watch", "symbol", "x", fmt="u16", watch_mode="show")
    assert one.width == 2, "a scalar with no width is one value of it"
    with pytest.raises(dec.DeclarationError, match="whole number"):
        dec.Declaration("watch", "symbol", "x", fmt="u16", width=3, watch_mode="show")


def test_run_for_reports_no_cycles_when_the_console_stops_answering_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _RegisterSession(bits=32, frame=10, stop_after=4)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    real = reg.monitor

    def mute(command: str, timeout: float = 10.0) -> str:
        return "" if command == "print totalcycles" else real(command, timeout)

    reg.monitor = mute  # type: ignore[method-assign]
    out = s.run_for(milliseconds=100, seconds=5.0)
    assert out["verdict"] == "ELAPSED" and out["cycles"]["available"] is False


# ------------------------------------------------------------------ run_for by frames


def test_run_for_frames_advances_the_frame_counter_by_exactly_that_many(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A golden is a marker plus N FRAMES, and N milliseconds is not N frames: MAME's
    `gvblank` runs to the next vblank, one per frame counter tick (from the
    vblank line each `gvblank` moves `frame` by one and `totalcycles` by one frame's worth),
    so `frames=N` is N of them, each confirmed on the counter, until it has moved by N."""
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    out = s.run_for(frames=3, seconds=5.0)
    assert out["status"] == "ok" and out["verdict"] == "ELAPSED", out
    assert out["frame_before"] == 10 and out["frame_after"] == 13
    assert reg.commands.count("gvblank") == 3
    assert out["cycles"] == 3 * reg.cycles_per_frame
    # The summary names the unit that DECIDED the run: three repos read "run_for 0 ms" for a
    # run asked in frames and took it for a run that went nowhere.
    assert out["summary"] == "run_for 3 frames: ELAPSED, frame 10 to 13", out["summary"]
    refused("exactly one", s.run_for(milliseconds=100, frames=3))
    refused("exactly one", s.run_for())
    refused("frames", s.run_for(frames=-1))


def test_run_for_frames_is_invalid_when_the_counter_does_not_move(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    reg.frozen = True
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    out = s.run_for(frames=2, seconds=0.2)
    assert out["status"] == "INVALID" and out["code"] == "no_progress"


def test_run_for_refuses_a_negative_count_and_says_when_the_counter_runs_out_of_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    refused("negative", s.run_for(milliseconds=-5))
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    real = reg.monitor

    def slow(command: str, timeout: float = 10.0) -> str:
        if command == "gvblank":
            return ""
        if command == "print frame":
            reg.frame = 11 if reg.frame == 10 else 10   # two readings never agree: no landing
            return f"{reg.frame:x}\n"
        return real(command, timeout)

    reg.monitor = slow  # type: ignore[method-assign]
    out = s.run_for(frames=3, seconds=0.05)
    assert out["status"] == "INVALID" and out["code"] == "not_settled"


def test_run_for_frames_reports_no_cycles_when_the_console_stops_answering_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    real = reg.monitor

    def mute(command: str, timeout: float = 10.0) -> str:
        return "" if command == "print totalcycles" else real(command, timeout)

    reg.monitor = mute  # type: ignore[method-assign]
    out = s.run_for(frames=1, seconds=5.0)
    assert out["verdict"] == "ELAPSED" and out["cycles"]["available"] is False


def test_run_for_frames_stops_at_a_breakpoint_this_server_armed_between_two_vblanks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A breakpoint armed on a routine that runs every frame halts the machine BEFORE the
    vblank the `gvblank` was heading for: the counter has not moved, the pc sits on the
    row. The contract: the stop is OTHER_STOP, attributed, and NOTHING is sent after it, so
    the machine is left where the breakpoint put it. A run that resumed each hit with the
    next `gvblank` instead comes back ELAPSED at its last frame, with every halt it passed
    through lost."""
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    import mame_state as mstate
    row = 0x4A0
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "IRQ_VBLANK", row)))
    real = reg.monitor
    landed = False

    def halt_on_the_row(command: str, timeout: float = 10.0) -> str:
        nonlocal landed
        if command == "gvblank" and reg.commands.count("gvblank") == 1:
            # The second run to the vblank meets the row first: no frame elapsed, and the
            # pc is the row's.
            landed = True
            reg.commands.append(command)
            return ""
        return real(command, timeout)

    reg.monitor = halt_on_the_row  # type: ignore[method-assign]
    reg.current_pc = lambda: row if landed else 0x100  # type: ignore[method-assign]
    out = s.run_for(frames=5, seconds=2.0)
    assert out["status"] == "ok", out
    assert out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == "breakpoint at 0x4a0", out["cause"]   # attributed to the row
    assert out["frame_before"] == 10 and out["frame_after"] == 11, out
    assert reg.commands.count("gvblank") == 2, reg.commands
    assert out["summary"] == "run_for 5 frames: OTHER_STOP, frame 10 to 11", out["summary"]


def test_run_for_frames_stops_at_a_watchpoint_typed_through_debug(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A watchpoint this server did not arm (`debug("wpset ...")`) halts the machine before
    the vblank: the counter does not tick, no packet comes, and the only trace is the
    console's line in `debug.log`. The run is OTHER_STOP named by that line, and nothing
    is sent after it; before, the stop was absorbed and the run came back ELAPSED with
    every hit lost. The control is the ELAPSED run above, with no line in the log."""
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    real = reg.monitor

    def halt_on_the_foreign_watch(command: str, timeout: float = 10.0) -> str:
        if command == "gvblank" and reg.commands.count("gvblank") == 1:
            reg.commands.append(command)
            (tmp_path / "debug.log").write_text(
                "Stopped at watchpoint 1 writing 0003 to 700011 (PC=0009BC74)\n")
            return ""
        return real(command, timeout)

    reg.monitor = halt_on_the_foreign_watch  # type: ignore[method-assign]
    out = s.run_for(frames=5, seconds=2.0)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == ("watch 1 at 0x00700011 this server did not arm, wrote 0003 by pc "
                          "0x0009bc74: `debug(\"wpclear 0x1\")` removes it"), out["cause"]
    assert out["frame_before"] == 10 and out["frame_after"] == 11, out
    assert reg.commands.count("gvblank") == 2, reg.commands


# CAPTURED, never authored: what the console wrote to `debug.log` while `run_for` resumed through
# a breakpoint typed through `debug` on the vblank handler (PROVENANCE.txt says how).
_CAPTURED = Path(__file__).parent / "fixtures" / "console"
_FRAMES_LOG = (_CAPTURED / "debuglog.foreign-bp.frames.txt").read_text().splitlines(keepends=True)
_MS_LOG = (_CAPTURED / "debuglog.foreign-bp.ms.txt").read_text()
_FOREIGN_CAUSE = ("breakpoint 1 at 0x00000400, typed through `debug`: `debug(\"bpclear 0x1\")` "
                "removes it")


def _first_stop_through(last: str) -> str:
    """The captured log from its start through the first line that begins with `last`."""
    end = next(i for i, ln in enumerate(_FRAMES_LOG) if ln.startswith(last))
    return "".join(_FRAMES_LOG[:end + 1])


def _foreign_breakpoint_on_the_vblank(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                      chunk: str, rows: list[str]) -> _RegisterSession:
    """A double whose first `gvblank` lands, WITH the tick, on the row `bpset 0x400` made:
    the counter moves, the pc is the handler's, and the only trace is the console's line."""
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    reg.bplist_rows = rows
    real = reg.monitor
    landed = False

    def land_on_the_handler(command: str, timeout: float = 10.0) -> str:
        nonlocal landed
        if command == "gvblank" and not landed:
            landed = True
            with open(tmp_path / "debug.log", "a") as fh:
                fh.write(chunk)
        return real(command, timeout)

    reg.monitor = land_on_the_handler  # type: ignore[method-assign]
    reg.current_pc = lambda: 0x400 if landed else 0x100  # type: ignore[method-assign]
    return reg


@pytest.mark.parametrize("through", ["3D", "Stopped at VBLANK"],
                         ids=["the-breakpoint-and-its-echo", "and-the-vblank-of-the-same-frame"])
def test_run_for_frames_stops_at_a_breakpoint_typed_through_debug(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, through: str,
) -> None:
    """A breakpoint typed through `debug` on the vblank handler lands WITH the tick: the counter
    moved, the pc is on no row of this server's, no packet comes, and the only trace is the
    console's `Stopped at breakpoint <n>`. The run is OTHER_STOP named by that line, and
    nothing is sent after it."""
    reg = _foreign_breakpoint_on_the_vblank(monkeypatch, tmp_path, _first_stop_through(through),
                                            ["    1 @ 000400"])
    out = s.run_for(frames=5, seconds=2.0)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == _FOREIGN_CAUSE, out["cause"]
    assert out["frame_before"] == 10 and out["frame_after"] == 11, out
    assert reg.commands.count("gvblank") == 1, reg.commands


def test_run_for_milliseconds_stops_at_a_breakpoint_typed_through_debug(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The same breakpoint under `gtime`: the run the console started ends at it, and the
    survey of that end reads the line, so the verdict is OTHER_STOP named by it, not a run
    that elapsed."""
    reg = _RegisterSession(bits=32, frame=10, stop_after=2)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    reg.bplist_rows = ["    1 @ 000400"]
    reg.pcs = [0x100, 0x400]
    real = reg.monitor

    def gtime_to_the_handler(command: str, timeout: float = 10.0) -> str:
        if command.startswith("gtime"):
            (tmp_path / "debug.log").write_text(_MS_LOG)
        return real(command, timeout)

    reg.monitor = gtime_to_the_handler  # type: ignore[method-assign]
    out = s.run_for(milliseconds=200, seconds=2.0)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == _FOREIGN_CAUSE, out["cause"]


def test_a_breakpoint_stop_whose_list_the_console_will_not_answer_still_cuts_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With no list to say whose the row is, the stop is still a stop: named as such, with the
    reason, and the run ends there rather than resuming through a stop somebody asked for."""
    reg = _foreign_breakpoint_on_the_vblank(monkeypatch, tmp_path, _first_stop_through("3D"),
                                            ["    1 @ 000400"])
    landed = reg.monitor

    def mute_bplist(command: str, timeout: float = 10.0) -> str:
        return "garbage\n" if command == "bplist" else landed(command, timeout)

    reg.monitor = mute_bplist  # type: ignore[method-assign]
    out = s.run_for(frames=5, seconds=2.0)
    assert out["verdict"] == "OTHER_STOP", out
    assert out["cause"].startswith("breakpoint 1 at 0x00000400; the debugger's list could not be "
                                 "read to say whose"), out["cause"]


def test_a_stop_on_a_row_this_server_armed_keeps_its_name_beside_a_foreign_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """PRECEDENCE AT THE CALLER: the machine stands on a row this server armed while the window
    also holds a foreign row's line. The stop is the armed row's, whatever the line says."""
    import mame_state as mstate
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "irq_vblank", 0x400)))
    _foreign_breakpoint_on_the_vblank(
        monkeypatch, tmp_path, _first_stop_through("3D") + "Stopped at breakpoint 2\n",
        ["    1 @ 000400", "    2 @ 0025A4"])
    out = s.run_for(frames=5, seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cause"] == "breakpoint at 0x400", out["cause"]


def test_the_newest_breakpoint_line_in_the_window_names_the_stop(tmp_path: Path) -> None:
    """Two breakpoint stops in one window: the machine stands at the LAST one."""
    reg = _RegisterSession(bits=32)
    reg.bplist_rows = ["    1 @ 000400", "    2 @ 0025A4"]
    since = ["Stopped at breakpoint 1", "3D", "Stopped at breakpoint 2", "3D"]
    how = breakpoints.foreign_breakpoint(reg, since, 0x25A4)  # type: ignore[arg-type]
    assert how is not None and how.startswith("breakpoint 2 at 0x000025a4"), how


def test_a_resume_that_lands_on_a_breakpoint_typed_through_debug_names_it_the_same_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ONE READER, ONE ANSWER: every survey reads the line, so a `resume` that stops on the
    same row names it as `run_for` does, not as a stop at no breakpoint."""
    reg = _RegisterSession(bits=32, frame=10)
    _install(monkeypatch, reg, tmp_path)
    reg.bplist_rows = ["    1 @ 000400"]
    reg.current_pc = lambda: 0x400  # type: ignore[method-assign]
    real_go = reg.go

    def go_to_the_handler() -> None:
        (tmp_path / "debug.log").write_text(_MS_LOG)
        real_go()

    reg.go = go_to_the_handler  # type: ignore[method-assign]
    out = s.resume(seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cause"] == _FOREIGN_CAUSE, out


def test_a_breakpoint_line_of_a_row_this_server_armed_is_named_as_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """PRECEDENCE: the console writes the same line for a row this server armed, and that stop
    is named as the row it is, never as foreign. The control beside it: a line whose row is no
    longer in the debugger's list (a tool's own row, removed before the survey) names nothing,
    and the run goes on to its frames."""
    import mame_state as mstate
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "irq_vblank", 0x400)))
    _foreign_breakpoint_on_the_vblank(monkeypatch, tmp_path, _first_stop_through("3D"),
                                      ["    1 @ 000400"])
    out = s.run_for(frames=5, seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cause"] == "breakpoint at 0x400", out["cause"]
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    reg = _foreign_breakpoint_on_the_vblank(monkeypatch, tmp_path, _first_stop_through("3D"), [])
    out = s.run_for(frames=5, seconds=2.0)
    assert out["verdict"] == "ELAPSED" and out["frame_after"] == 15, out
    assert reg.commands.count("gvblank") == 5


def test_a_cut_frame_run_reports_no_cycles_when_the_console_stops_answering_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The cut's cycles are read like ELAPSED's: unreadable is None, never a guess."""
    import mame_state as mstate
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    row = 0x4A0
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "IRQ_VBLANK", row)))
    real = reg.monitor

    def mute_cycles(command: str, timeout: float = 10.0) -> str:
        return "" if command == "print totalcycles" else real(command, timeout)

    reg.monitor = mute_cycles  # type: ignore[method-assign]
    reg.current_pc = lambda: row  # type: ignore[method-assign]
    out = s.run_for(frames=5, seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cycles"]["available"] is False, out
    assert reg.commands.count("gvblank") == 1


def test_a_stop_packet_that_names_no_watch_and_no_row_does_not_cut_a_frame_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A packet the stub left (an earlier interrupt's, say) with the pc on no row of ours and
    no watch in the survey is not a stop this server armed: the run goes on to its frames."""
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    real = reg.monitor

    def leave_a_packet(command: str, timeout: float = 10.0) -> str:
        if command == "gvblank":
            reg.last_stop_packet = "T05thread:1;"
        return real(command, timeout)

    reg.monitor = leave_a_packet  # type: ignore[method-assign]
    out = s.run_for(frames=3, seconds=2.0)
    assert out["verdict"] == "ELAPSED" and out["frame_after"] == 13, out
    assert reg.commands.count("gvblank") == 3


def test_a_frame_run_landing_on_a_control_row_every_vblank_runs_to_its_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A control on the vblank handler is where every `gvblank` lands: it counts and never
    halts, so the run goes to its frames. A control treated as a halt ends a long frame run
    at the first vblank, on the control's row, with most of its frames still to go."""
    import mame_state as mstate
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    row = 0x400
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "irq_vblank", row)))
    monkeypatch.setattr(mstate.STATE, "controls",
                        {("irq_vblank", ":maincpu"): {"addr": row, "temp": 0, "index": "1",
                                                      "missed": 0}})
    reg.current_pc = lambda: row  # type: ignore[method-assign]
    out = s.run_for(frames=4, seconds=2.0)
    assert out["verdict"] == "ELAPSED" and out["frame_after"] == 14, out
    assert reg.commands.count("gvblank") == 4
    # Three of the four landings were released inside the run, unevaluated by MAME.
    assert mstate.STATE.controls[("irq_vblank", ":maincpu")]["missed"] == 3


# ------------------------------------------------ what span `cycles` reports for a frame run
#
# THE DOUBLE HERE DECOUPLES THE TWO COUNTERS, which the shared one cannot: its `totalcycles` is
# the frame counter times a constant, so a tick that burns cycles WITHOUT moving the frame --
# exactly the aligning `gvblank` this loop documents -- cannot be expressed through it.


def _misaligned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                align_ticks: int = 1) -> _RegisterSession:
    """A machine stopped in the MIDDLE of a frame: the first `align_ticks` `gvblank`s reach
    that frame's own vblank, burning a frame's worth of cycles each without moving the frame
    counter, and every one after that moves both."""
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    monkeypatch.setattr(advance, "VBLANK_SETTLE_S", 0.0)
    clock = [reg.frame * reg.cycles_per_frame]
    ticks = [0]
    real = reg.monitor

    def console(command: str, timeout: float = 10.0) -> str:
        if command == "gvblank":
            reg.commands.append(command)
            clock[0] += reg.cycles_per_frame
            ticks[0] += 1
            if ticks[0] > align_ticks:
                reg.frame += 1
            return ""
        if command == "print totalcycles":
            reg.commands.append(command)
            return f"{clock[0]:x}\n"
        if command == "print frame,totalcycles":
            reg.commands.append(command)
            return f"{reg.frame:x} {clock[0]:x}\n"
        if command == "print frame":
            reg.commands.append(command)
            return f"{reg.frame:x}\n"
        return real(command, timeout)

    reg.monitor = console  # type: ignore[method-assign]
    return reg


def test_the_aligning_vblank_is_outside_the_cycles_a_frame_run_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`cycles` is the clock behind the frames ASKED FOR. From a mid-frame stop the first
    `gvblank` reaches that frame's vblank without moving the counter, so its cycles sat
    inside a span whose frame count was still exactly N, so the first
    `run_for(frames=1)` of a session reports about twice the cycles of a later one.

    `polls` is NOT touched: it reports the `gvblank`s sent, honestly, and it is the only
    tell a caller has that the alignment fired at all."""
    reg = _misaligned(monkeypatch, tmp_path)
    out = s.run_for(frames=1, seconds=5.0)
    assert out["status"] == "ok" and out["verdict"] == "ELAPSED", out
    assert out["frame_before"] == 10 and out["frame_after"] == 11
    assert out["polls"] == 2, "two `gvblank`s went out and the reply says so"
    assert out["cycles"] == reg.cycles_per_frame, (
        "one frame was asked for, so one frame's worth of clock is the span")


def test_a_frame_run_from_an_aligned_stop_reports_the_same_per_frame_cycles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE KNOWN-ANSWER CASE the instrument is checked against: from a stop already ON a
    vblank no alignment is needed, and a run of N frames must report exactly what the
    misaligned one above reports per frame. An instrument whose answer depends on where the
    session happened to be stopped is not measuring the run."""
    aligned = _misaligned(monkeypatch, tmp_path, align_ticks=0)
    one = s.run_for(frames=1, seconds=5.0)
    assert one["polls"] == 1 and one["cycles"] == aligned.cycles_per_frame, one
    three = s.run_for(frames=3, seconds=5.0)
    assert three["polls"] == 3 and three["cycles"] == 3 * aligned.cycles_per_frame, three


def test_a_baseline_the_console_cannot_re_read_reports_no_cycles_rather_than_a_guess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The re-baseline is a console read like any other, and this file's rule for one that
    fails is the same everywhere: unreadable is None, never a number that spans the wrong
    thing."""
    reg = _misaligned(monkeypatch, tmp_path)
    real = reg.monitor

    def mute(command: str, timeout: float = 10.0) -> str:
        if command == "print totalcycles":
            raise g.SessionError("the console answered nothing")
        return real(command, timeout)

    reg.monitor = mute  # type: ignore[method-assign]
    out = s.run_for(frames=1, seconds=5.0)
    assert out["verdict"] == "ELAPSED" and out["cycles"]["available"] is False, out


def test_an_expr_watch_is_declared_by_its_mode_and_its_reply_says_what_was_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {"beamy": 0xF8}
    refused("by is one of", s.watch_add(ref="beamy", mode="expr", by="expr"))
    out = s.watch_add(ref="beamy", mode="expr")
    assert out["status"] == "ok" and (out["ref"], out["by"], out["mode"]) == ("beamy", "expr",
                                                                              "expr"), out
    assert (out["stored"], out["already_stored"], out["armed"]) == (True, False, False), out
    assert s.watch_add(ref="beamy", mode="expr")["already_stored"] is True
    assert s.watch_add(ref="beamy", mode="expr", by="symbol")["code"] == "bad_argument"


@pytest.mark.parametrize("ref", ["1;g", "(d0=5)", "beamy,d0", "d0++", "{g}"])
def test_an_expr_ref_that_would_run_a_command_or_write_is_refused_before_anything(ref: str) -> None:
    """The ref goes out as a parameter of `print frame,<ref>` at every stop: a `;` would run a
    second command there, a `,` a second parameter, and an assignment would write the machine at
    every stop with nothing counted."""
    out = s.watch_add(ref=ref, mode="expr")
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert out["session"]["altered"] is False
