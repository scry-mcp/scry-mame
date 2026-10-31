"""A board with no screen device: no frame counter, and a run told by the emulated clock.

MAME's debugger registers `frame` (and `beamx`, `beamy`, the vblank stop) only on a machine
with exactly one screen device, `frame0`, `frame1`... on one with several, and nothing at all on
one with none (src/emu/debug/debugcpu.cpp): a vector board such as topgunnr has a `vector`
display and no screen chip. There `print frame` is refused, so `start` asks which name the
counter answers to, and every proof of rest that read the counter reads the console's `time`
instead. The console's answers here are the captured ones (`fixtures/console/print-frame*`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lua_support import _channel  # noqa: E402
from server_support import (  # noqa: E402
    FIXTURES,
    _AliveProcess,
    _boot_args,
    _install,
    _RegisterSession,
    _running,
    _stub_boot,
)
from session_doubles import refused  # noqa: E402

from scry_mame import (
    advance,  # noqa: E402
    read,  # noqa: E402
    running,  # noqa: E402
    savestates,  # noqa: E402
    summaries,  # noqa: E402
)
from scry_mame import gdb_session as g  # noqa: E402
from scry_mame import lua as mlua  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

NO_FRAME = (FIXTURES / "print-frame-no-screen.txt").read_text()
NO_FRAME0 = (FIXTURES / "print-frame0-no-screen.txt").read_text()
ONE_SCREEN = (FIXTURES / "print-frame-one-screen.txt").read_text()


def _answering(ses: g.Session, answers: dict[str, str]) -> list[str]:
    """`start`'s session answering the frame probe with captured text, and every other console
    command as the unconnected session it is; the commands asked, in order."""
    asked: list[str] = []

    def monitor(command: str, timeout: float = 10.0) -> str:
        asked.append(command)
        if command in answers:
            return answers[command]
        raise g.SessionError("the session is not connected")

    ses.monitor = monitor  # type: ignore[method-assign]
    return asked


@pytest.mark.parametrize(("answers", "symbol", "probed"), [
    ({"print frame0": NO_FRAME0, "print frame": NO_FRAME}, None, ["print frame0", "print frame"]),
    ({"print frame0": NO_FRAME0, "print frame": ONE_SCREEN}, "frame",
     ["print frame0", "print frame"]),
    ({"print frame0": ONE_SCREEN}, "frame0", ["print frame0"]),
    # Neither a number nor a refusal the console is known to print: the default `frame` stands.
    ({"print frame0": "something else entirely\n"}, "frame", ["print frame0"]),
], ids=["no-screen", "one-screen", "several-screens", "unrecognised"])
def test_start_asks_which_name_the_frame_counter_answers_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answers: dict[str, str],
    symbol: str | None, probed: list[str],
) -> None:
    image = bytes(range(64))
    ses = _stub_boot(monkeypatch, tmp_path, image, at=0)
    asked = _answering(ses, answers)
    out = s.start(**_boot_args(tmp_path, image))
    try:
        assert out["status"] == "ok", out
        assert [c for c in asked if c.startswith("print frame")][:len(probed)] == probed
        for reply in (out, s.status(), s.machine_map()):
            named = reply["frame_symbol"]
            if symbol is None:
                # No name: the reason in its place, saying what that changes for a run.
                assert named["available"] is False, reply
                assert "no screen device" in named["why"], reply
                assert "`run_for(milliseconds=)` works" in named["why"], reply
            else:
                assert named == symbol, reply
            assert "note" not in reply or "screen device" not in reply["note"], reply
        if symbol is None:
            # The park's survey asked no counter it now knows is not there.
            assert asked.count("print frame") == 1 and out["frame"]["available"] is False
    finally:
        s.close()
    assert mstate.STATE.frame_symbol == "frame", "a closed session's answer outlived it"


def _frameless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
               stop_after: int | None = 3) -> _RegisterSession:
    ses = _RegisterSession(bits=32, frame=10, stop_after=stop_after)
    ses.frameless = True
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "proc", _AliveProcess())
    monkeypatch.setattr(mstate.STATE, "frame_symbol", None, raising=False)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    return ses


def test_run_for_frames_is_refused_before_the_machine_is_released(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frameless(monkeypatch, tmp_path)
    out = refused(r"no screen device.*`run_for\(milliseconds=\)` works", s.run_for(frames=30))
    assert out["code"] == "no_channel"
    assert getattr(ses, "broken", None) is None, "a refusal of the question latches nothing"
    assert "gvblank" not in ses.commands and not ses.emulating
    after = s.status()
    assert after["status"] == "ok" and after["session"]["alive"] is True and "broken" not in after


def test_run_for_milliseconds_proves_rest_by_the_emulated_clock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frameless(monkeypatch, tmp_path, stop_after=3)
    out = s.run_for(milliseconds=50)
    assert out["status"] == "ok" and out["verdict"] == "ELAPSED", out
    assert all(out[k]["available"] is False for k in ("frame_before", "frame_after", "frame")), out
    assert out["frame"]["why"] == mstate.NO_COUNTER_WHY, out["frame"]
    assert out["emulated_before_s"] == 0.0 and out["emulated_after_s"] == 0.003, out
    # The record keeps None; every reply that dates an answer by it says why there is none.
    assert s.status()["last_stop"]["frame"] == {"available": False,
                                                "why": mstate.NO_COUNTER_WHY}
    assert "gtime 0x32" in ses.commands
    assert not [c for c in ses.commands if c.startswith("print") and "frame" in c], ses.commands
    assert "frame None" not in out["summary"] and "0.003" in out["summary"], out["summary"]


def test_run_for_milliseconds_on_a_clock_that_did_not_move_is_no_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frameless(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "emulated_seconds", lambda: 1.5)
    out = refused("the emulated clock did not move", s.run_for(milliseconds=50))
    assert out["code"] == "no_progress" and out["emulated_after_s"] == 1.5, out
    assert out["frame_before"]["available"] is False, out


def test_run_for_milliseconds_reports_the_emulated_clock_on_a_board_with_a_counter_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control: a one-screen board keeps its counter's proof and gains the two times."""
    ses = _RegisterSession(bits=32, frame=10, stop_after=4)
    ses.emu_clock = 2.2500004321          # below a microsecond: the reply spells it to one
    plain = ses.monitor

    def gtime_moves_the_clock(command: str, timeout: float = 10.0) -> str:
        if command.startswith("gtime"):
            ses.emu_clock += int(command.split()[1], 16) / 1000
        return plain(command, timeout)

    monkeypatch.setattr(ses, "monitor", gtime_moves_the_clock)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    out = s.run_for(milliseconds=250)
    assert out["status"] == "ok" and out["frame_before"] == 10 and out["frame_after"] == 14
    assert out["emulated_before_s"] == 2.25 and out["emulated_after_s"] == 2.5, out


def test_a_console_run_is_stopped_on_the_emulated_clock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frameless(monkeypatch, tmp_path, stop_after=None)
    # Still moving when `stop` is called: only its interrupt halts it.
    ses.running = ses.emulating = True
    monkeypatch.setattr(mstate.STATE, "console_run", True)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.5)
    out = s.stop()
    assert out["status"] == "ok" and out["interrupted"] is True, out
    assert out["frame"]["available"] is False and "frame None" not in out["summary"], out


def test_a_step_over_settles_on_the_emulated_clock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frameless(monkeypatch, tmp_path)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.5)
    out = s.step(mode="over")
    assert out["status"] == "ok" and out["instructions_completed"] == 1, out
    assert not ses.interrupted, "a step that came to rest by itself is not interrupted"


def test_perform_until_frame_is_refused_before_any_step_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frameless(monkeypatch, tmp_path)
    out = refused("no screen device", s.perform(steps=[{"op": "run_for", "frames": 1}],
                                                summaries=True, until_frame=5))
    assert out["code"] == "no_channel"
    assert "milliseconds" not in out["message"], "no remedy offered that `perform` lacks"
    assert "gvblank" not in ses.commands and not any(c.startswith("gtime")
                                                      for c in ses.commands)


def test_a_state_load_on_a_board_with_no_counter_is_not_verified_by_a_block_that_never_moved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two missing frames compared equal would pass any load, and so would a register block
    that already read as the save before the load (`savestates.ALREADY_AS_SAVED`)."""
    ses = _channel(monkeypatch, tmp_path)
    ses.frameless = True
    monkeypatch.setattr(mstate.STATE, "frame_symbol", None, raising=False)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    saved = s.state_write("save", name="live")
    assert saved["status"] == "ok" and saved["frame"]["available"] is False, saved
    assert saved["frame"]["why"] == mstate.NO_COUNTER_WHY, saved
    assert "frame None" not in saved["summary"], saved["summary"]
    loaded = s.state_write("load", name="live")
    assert loaded["status"] == "ok", loaded
    assert loaded["verified"]["available"] is False, loaded
    assert loaded["verified"]["why"] == savestates.ALREADY_AS_SAVED, loaded
    assert "frame None" not in loaded["summary"], loaded["summary"]


def test_the_survey_reads_the_expressions_alone_and_asks_no_counter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "frame_symbol", None, raising=False)
    ses.exprs = {"beamy": 0xF8}
    s.watch_add(ref="beamy", mode="expr")
    ses.commands.clear()
    out = s.step()
    assert [c for c in ses.commands if c.startswith("print ")] == ["print beamy"]
    (w,) = out["watches"]
    assert w["reading"] == {"available": True, "value": 0xF8, "hex": "0xf8"}, w
    assert out["frame"]["available"] is False


def test_focus_on_the_patched_stub_proves_nothing_ran_by_the_blocks_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    monkeypatch.setattr(mstate.STATE, "frame_symbol", None, raising=False)
    ses.commands.clear()
    out = s.cpu_focus(cpu="subcpu")
    assert (out["status"] == "ok" and out["machine_ran"] is False
            and out["frame"]["available"] is False), out
    assert not [c for c in ses.commands if c.startswith("print")], ses.commands


def test_a_console_refusal_of_an_expression_is_an_answer_and_latches_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The defence under all of the above: an expression the console refuses is no channel on
    this machine, never a broken session."""
    ses = _RegisterSession(bits=32)
    ses.frameless = True
    with pytest.raises(g.ExpressionRefused, match="frame"):
        read.print_values(ses, ["frame", "totalcycles"])  # type: ignore[arg-type]
    ses2 = _frameless(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "frame_symbol", "frame", raising=False)
    out = s.run_for(frames=3)          # a board the start misjudged: refused, not latched
    assert out["status"] == "INVALID" and out["code"] == "no_channel", out
    assert getattr(ses2, "broken", None) is None
    assert "broken" not in s.status()


def test_the_emulated_clock_is_read_off_the_consoles_own_answer() -> None:
    """The clock every proof above reads, parsed from what `time` answered on topgunnr."""
    ses = g.Session()
    ses.monitor = lambda command, timeout=10.0: (  # type: ignore[method-assign]
        (FIXTURES / "time.txt").read_text() if command == "time" else "")
    assert ses.emulated_seconds() == 0.00000425


def test_a_clock_that_stops_answering_after_the_release_leaves_the_machine_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A refusal after `gtime` went out is still no proof of rest: the machine is let go of,
    `not_settled`, never answered `no_channel` as if nothing had been released."""
    ses = _frameless(monkeypatch, tmp_path)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.3)
    asked = {"n": 0}

    def clock() -> float:
        asked["n"] += 1
        if asked["n"] == 1:
            return 0.0
        raise g.ExpressionRefused("the console refused `time`")

    monkeypatch.setattr(ses, "emulated_seconds", clock)
    out = refused("could no longer be read", s.run_for(milliseconds=50))
    assert out["code"] == "not_settled" and out["emulated_before_s"] == 0.0, out
    assert out["frame_after"]["available"] is False, out
    assert "refused `time`" in out["emulated_after_s"]["why"], out
    assert s.status()["session"]["running"] is True


def test_a_moving_clock_is_no_rest_for_a_stop_or_a_step_over(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The negative half of the two proofs above: the clock read while the machine emulates
    moves, so neither reads it as at rest."""
    ses = _frameless(monkeypatch, tmp_path, stop_after=None)
    ses.emulating = True
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.2)
    assert not running.frame_at_rest(ses, gap_s=0.0)  # type: ignore[arg-type]
    assert not advance._settled_pc(ses)  # type: ignore[arg-type]
    ses.emulating = False
    assert running.frame_at_rest(ses, gap_s=0.0)  # type: ignore[arg-type]
    assert advance._settled_pc(ses)  # type: ignore[arg-type]


def test_input_and_record_are_refused_before_the_pipe_is_drained(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Draining the console's pipe steps the machine, so a run by frames the board cannot take
    is refused first."""
    _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "frame_symbol", None, raising=False)
    drained: list[str] = []

    def drain(ses: object, scratch: Path) -> tuple[int, int]:
        drained.append("drain")
        return 0, 0

    monkeypatch.setattr(mlua, "drain_ahead", drain)
    for out in (refused("no screen device", s.input(port=":IN0", field="Coin 1", value=1,
                                                    frames=2)),
                refused("no screen device", s.record(frames=2)),
                refused("no screen device", s.audio_record(frames=2))):
        assert "milliseconds" not in out["message"], ("no way round offered a tool lacks", out)
    assert drained == [], "the pipe was drained, stepping the machine, before the refusal"
    out = refused("no screen device", s.trace(frames=3))
    assert out["message"].endswith("`trace(milliseconds=)` works"), "its own way round"


def test_no_summary_names_a_frame_the_board_does_not_have() -> None:
    reply = {"kind": "soft", "frame_at_reset": {"available": False, "why": "no counter"},
             "pc": "0x00000400", "verified": True}
    assert "frame" not in summaries.reset({}, reply), summaries.reset({}, reply)


def test_state_list_says_why_a_state_written_here_has_no_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.frameless = True
    monkeypatch.setattr(mstate.STATE, "frame_symbol", None, raising=False)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    assert s.state_write("save", name="live")["status"] == "ok"
    (row,) = s.state_list()["states"]
    assert row["frame"]["available"] is False and row["pc"] is not None, row
    assert "no frame counter" in row["frame"]["why"], row


def test_a_board_with_neither_counter_nor_clock_is_refused_before_the_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frameless(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "emulated_seconds", lambda: None)
    out = refused("`time` answered no time", s.run_for(milliseconds=50))
    assert out["code"] == "no_channel"
    assert not any(c.startswith("gtime") for c in ses.commands), ses.commands
    assert not running.frame_at_rest(ses, gap_s=0.0), (  # type: ignore[arg-type]
        "no clock is no proof of rest")


class _Probed:
    """A console that answers the frame probe with one failure."""

    def __init__(self, error: g.SessionError, latch: bool = False) -> None:
        self.error, self.latch = error, latch
        self.broken: str | None = None

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        if self.latch:
            self.broken = "latched"
        raise self.error


@pytest.mark.parametrize(("error", "latch"), [
    (g.ConnectionFailed("reset by peer"), False),
    (g.Timeout("no answer"), True),
], ids=["connection-gone", "latched"])
def test_the_probe_does_not_guess_past_a_channel_that_failed(
    error: g.SessionError, latch: bool,
) -> None:
    """Only an answer keeps the default name; a channel that failed is the start's failure."""
    with pytest.raises(type(error)):
        read.probe_frame_symbol(_Probed(error, latch))  # type: ignore[arg-type]


def test_a_moving_counter_is_judged_at_the_first_reading_that_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings: list[int] = []

    def moving(_ses: object) -> int:
        readings.append(len(readings))
        return len(readings)

    monkeypatch.setattr(read, "rest_reading", moving)
    assert not running.frame_at_rest(object(), reads=3, gap_s=0.0)  # type: ignore[arg-type]
    assert len(readings) == 2, readings
