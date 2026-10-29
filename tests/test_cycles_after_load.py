"""`cycles` right after a state load: a run whose baseline is the stale counter is withheld."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lua_support import _channel, _ChannelSession  # noqa: E402
from server_support import FIXTURES  # noqa: E402

from scry_mame import (
    advance,  # noqa: E402
    cycles,  # noqa: E402
    running,  # noqa: E402
)
from scry_mame import gdb_session as g  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

CAPTURE = (FIXTURES / "totalcycles-after-load.txt").read_text()


def _readings(text: str) -> list[tuple[int, int]]:
    """Each `print frame,totalcycles` answer of the capture, as (frame, cycles)."""
    out = []
    for answer in text.split("\n\n"):
        if answer.strip():
            frame, cycles = answer.split()
            out.append((int(frame, 16), int(cycles, 16)))
    return out


# The capture's own clock from its first two readings.
(_F0, _C0), (_F1, _C1) = _readings(CAPTURE)[:2]
PER_FRAME = (_C1 - _C0) // (_F1 - _F0)
AT_FRAME_0 = _C0 - _F0 * PER_FRAME


def _board(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _ChannelSession:
    """A stopped machine at frame 10 whose counter behaves as the capture's."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")   # the captured header's name
    monkeypatch.setattr(advance, "VBLANK_SETTLE_S", 0.0)
    ses.frame = 10
    ses.cycles_per_frame = PER_FRAME
    ses.cycles_offset = AT_FRAME_0
    ses.stale_after_load = True
    return ses


def test_the_double_answers_as_the_capture_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The double walked through the capture's sequence answers its readings (control)."""
    saved, ran, loaded, stepped = _readings(CAPTURE)
    ses = _board(monkeypatch, tmp_path)
    assert (_C1 - _C0) % (_F1 - _F0) == 0, "a whole number of cycles a frame"
    asked = "print frame,totalcycles"

    def reading() -> tuple[int, int]:
        frame, cycles = ses.monitor(asked).split()
        return int(frame, 16), int(cycles, 16)

    assert s.state_write("save", name="c1")["status"] == "ok"
    assert reading() == saved
    for _ in range(5):
        ses.monitor("gvblank")
    assert reading() == ran
    ses.monitor("stateload c1")
    assert reading() == loaded == (saved[0], ran[1]), "the loaded frame, the pre-load count"
    ses.step()
    assert reading() == saved
    assert stepped[0] == saved[0] and 0 < stepped[1] - saved[1] < PER_FRAME


def _run(frames: int) -> dict[str, Any]:
    out: dict[str, Any] = s.run_for(frames=frames, seconds=2.0)
    assert out["status"] == "ok", out
    return out


def test_a_run_right_after_a_load_reports_no_cycles_and_the_next_one_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Baseline is frame 15's count and the end frame 12's: a negative span, withheld."""
    _board(monkeypatch, tmp_path)
    s.state_write("save", name="c1")
    _run(5)
    assert s.state_write("load", name="c1")["status"] == "ok"
    out = _run(2)
    assert out["cycles"]["available"] is False, out
    assert out["cycles"]["why"] == cycles.cycles_why(cycles.STATE_LOAD), out
    again = _run(2)
    assert again["cycles"] == 2 * PER_FRAME, again
    assert isinstance(again["cycles"], int), again


def test_a_forward_load_is_withheld_too_never_a_silent_positive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A newer state leaves a count too small, so the run would read long yet plausible."""
    _board(monkeypatch, tmp_path)
    s.state_write("save", name="old")
    _run(5)
    s.state_write("save", name="new")
    assert s.state_write("load", name="old")["status"] == "ok"
    _run(2)                                  # at frame 12, the counter up to date again
    assert s.state_write("load", name="new")["status"] == "ok"   # frame 15, the counter frame 12's
    out = _run(2)
    assert out["cycles"]["available"] is False and out["cycles"]["why"], out


def test_a_load_whose_aligning_tick_re_reads_the_baseline_reports_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The first `gvblank` from inside a frame re-reads the baseline after the cpu ran."""
    ses = _board(monkeypatch, tmp_path)
    s.state_write("save", name="c1")
    _run(5)
    assert s.state_write("load", name="c1")["status"] == "ok"
    real = ses.monitor
    aligned: list[str] = []

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "gvblank" and not aligned:
            aligned.append(command)
            ses.frozen = True                # reaches the vblank of the frame it is inside
            try:
                return real(command, timeout)
            finally:
                ses.frozen = False
        return real(command, timeout)

    ses.monitor = monitor  # type: ignore[method-assign]
    out = _run(2)
    assert out["polls"] == 3 and out["cycles"] == 2 * PER_FRAME, out
    assert isinstance(out["cycles"], int), out


def test_a_run_by_milliseconds_right_after_a_load_reports_no_cycles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path)
    ses.stop_after = 3
    s.state_write("save", name="c1")
    _run(5)
    assert s.state_write("load", name="c1")["status"] == "ok"
    out = s.run_for(milliseconds=50, seconds=2.0)
    assert out["status"] == "ok" and out["cycles"]["available"] is False, out
    assert out["cycles"]["why"], out
    again = s.run_for(milliseconds=50, seconds=2.0)
    assert isinstance(again["cycles"], int) and again["cycles"] > 0, again


def test_a_load_the_rom_check_refused_still_withholds_the_next_runs_cycles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The refusal follows `stateload`, so the machine was replaced all the same."""
    ses = _board(monkeypatch, tmp_path)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(bytes(64))
    monkeypatch.setattr(mstate.STATE, "reference", (rom, 0x10, 0x20))
    s.state_write("save", name="c1")
    _run(5)

    def mismatch(*_: object, **__: object) -> None:
        raise g.Mismatch("the ROM differs")

    ses.self_check = mismatch  # type: ignore[method-assign]
    assert s.state_write("load", name="c1")["code"] == "readback_refused"
    out = _run(2)
    assert out["cycles"]["available"] is False and out["cycles"]["why"], out


def test_a_stop_recorded_without_running_does_not_make_the_counter_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stop recorded while nothing executes leaves the counter stale."""
    ses = _board(monkeypatch, tmp_path)
    s.state_write("save", name="c1")
    _run(5)
    assert s.state_write("load", name="c1")["status"] == "ok"
    running.record_stop(ses, ses.scratch, "a survey with no execution")  # type: ignore[arg-type]
    out = _run(2)
    assert out["cycles"]["available"] is False and out["cycles"]["why"], out


def test_a_long_run_after_an_older_load_is_withheld_though_its_number_would_look_plausible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Loading back five frames and running ten would read as a short positive number."""
    _board(monkeypatch, tmp_path)
    s.state_write("save", name="c1")
    _run(5)
    assert s.state_write("load", name="c1")["status"] == "ok"
    out = _run(10)
    assert out["cycles"]["available"] is False and out["cycles"]["why"], out


def test_a_step_between_the_load_and_the_run_makes_the_counter_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _board(monkeypatch, tmp_path)
    s.state_write("save", name="c1")
    _run(5)
    assert s.state_write("load", name="c1")["status"] == "ok"
    ses.step()
    out = _run(2)
    assert out["cycles"] == 2 * PER_FRAME and isinstance(out["cycles"], int), out


def test_a_load_that_broke_the_session_asks_the_console_nothing_more(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A channel that lost its place is asked nothing; the mark is taken as stale."""
    ses = _board(monkeypatch, tmp_path)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(bytes(64))
    monkeypatch.setattr(mstate.STATE, "reference", (rom, 0x10, 0x20))
    s.state_write("save", name="c1")

    def latching(*_: object, **__: object) -> None:
        ses.broken = "the stub stopped answering"
        raise g.SessionError("no answer to the ROM check")

    ses.self_check = latching  # type: ignore[method-assign]
    ses.commands.clear()
    s.state_write("load", name="c1")
    sent = ses.commands
    assert sent[sent.index("stateload c1"):] == ["stateload c1"], sent
    assert mstate.STATE.stale_counter == cycles.StaleCounter(None, None, cycles.STATE_LOAD)


@pytest.mark.parametrize("line", ["stateload c1", "sl c1", "rewind", "rw"])
def test_a_typed_load_or_rewind_withholds_the_next_runs_cycles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, line: str,
) -> None:
    """A typed load or rewind marks the counter stale as the tool's own load does."""
    _board(monkeypatch, tmp_path)
    s.state_write("save", name="c1")
    _run(5)
    assert s.debug(command=line)["status"] == "ok"
    out = _run(2)
    assert out["cycles"]["available"] is False, out
    word = line.split()[0]
    assert f"`{word}`" in out["cycles"]["why"] and "replaced" in out["cycles"]["why"], out
    again = _run(2)
    assert again["cycles"] == 2 * PER_FRAME and isinstance(again["cycles"], int), again


def test_a_typed_reset_withholds_the_run_that_applies_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A typed `softreset` is applied by the next run, which restarts the count."""
    _board(monkeypatch, tmp_path)
    _run(5)
    assert s.debug(command="softreset")["status"] == "ok"
    out = _run(2)
    assert out["cycles"]["available"] is False and "`softreset`" in out["cycles"]["why"], out
    assert "restarts" in out["cycles"]["why"], out
    again = _run(2)
    assert again["cycles"] == 2 * PER_FRAME, again


def test_a_typed_reset_a_step_applied_leaves_the_next_run_counted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Control: the step executes, refreshing the counter past the mark."""
    ses = _board(monkeypatch, tmp_path)
    _run(5)
    assert s.debug(command="softreset")["status"] == "ok"
    ses.step()
    out = _run(2)
    assert out["cycles"] == 2 * PER_FRAME and isinstance(out["cycles"], int), out


@pytest.mark.parametrize("line", ["print pc", "stateload c1;g"])
def test_a_line_that_replaces_nothing_or_runs_after_it_sets_no_mark(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, line: str,
) -> None:
    """A read marks nothing; a line that runs after its load leaves a current counter."""
    _board(monkeypatch, tmp_path)
    s.state_write("save", name="c1")
    _run(5)
    assert s.debug(command=line)["status"] == "ok"
    assert mstate.STATE.stale_counter is None


def test_a_typed_load_sent_and_not_answered_still_marks_the_counter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Sent is enough: `state_write(method="load")` marks in a `finally` too."""
    ses = _board(monkeypatch, tmp_path)
    s.state_write("save", name="c1")
    _run(5)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "sl c1":
            real(command, timeout)
            raise g.Timeout("no answer to the line")
        return str(real(command, timeout))

    ses.monitor = monitor  # type: ignore[method-assign]
    assert s.debug(command="sl c1")["status"] == "INVALID"
    assert mstate.STATE.stale_counter is not None
    assert mstate.STATE.stale_counter.command == "sl"


def test_the_last_command_of_a_line_that_left_the_counter_stale_names_the_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _board(monkeypatch, tmp_path)
    s.state_write("save", name="c1")
    _run(5)
    assert s.debug(command="stateload c1;softreset")["status"] == "ok"
    assert "`softreset`" in _run(2)["cycles"]["why"]


def test_a_rewind_mame_refused_leaves_the_next_runs_cycles_counted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A refused rewind replaced nothing; the control is the same line answered with nothing."""
    refused_answer = (FIXTURES / "rewind.refused.txt").read_text()
    for line, answer, withheld in (("rewind", refused_answer, False), ("rw", refused_answer, False),
                                   ("rewind", "", True)):
        (tmp_path / f"{line}{withheld}").mkdir()
        ses = _board(monkeypatch, tmp_path / f"{line}{withheld}")
        _run(5)
        real = ses.monitor

        def monitor(command: str, timeout: float = 10.0, answer: str = answer,
                    real: Any = real) -> str:
            return answer if command in ("rewind", "rw") else str(real(command, timeout))

        monkeypatch.setattr(ses, "monitor", monitor)
        assert s.debug(command=line)["status"] == "ok"
        assert (mstate.STATE.stale_counter is not None) is withheld, line
        out = _run(2)
        assert isinstance(out["cycles"], dict) is withheld, out


def test_a_line_of_a_refused_rewind_and_another_stale_command_stays_marked() -> None:
    from scry_mame import console
    refused_answer = (FIXTURES / "rewind.refused.txt").read_text()
    assert console.refused_rewind(["rewind"], refused_answer)
    assert not console.refused_rewind(["stateload c1", "rewind"], refused_answer)
    assert not console.refused_rewind(["rewind", "rewind"], refused_answer)
    assert not console.refused_rewind(["rewind"], "")
