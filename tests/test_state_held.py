"""A save or a load MAME held (`mame_savestates.complete_held`) is completed by one step.

The double holds them as MAME does, logging MAME's words (`fixtures/console/
statesave.held.errorlog.txt`, captured on circus), and completes the held one after the step's
instruction, which moves the pc, the register block and the cycle counter.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_doubles import captured  # noqa: E402
from test_state_verified import _BlockSession, _board, _moved  # noqa: E402

import gdb_session as gs  # noqa: E402
import mame_files as mfiles  # noqa: E402
import mame_savestates as savestates  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

HELD_LOG = captured("statesave.held.errorlog.txt")
#: What the console prints for each command, held or not (`debugcmd.cpp`).
ATTEMPTED = {"statesave": "State save attempted.  Please refer to window message popup for "
                          "results.\n",
             "stateload": "State load attempted.  Please refer to window message popup for "
                          "results.\n"}
#: The cycles the double's stepped instruction takes.
STEP_CYCLES = 7


class _HeldSession(_BlockSession):
    """`held` saves or loads MAME holds instead of running them in the command; the step after
    one completes it, unless `stays`, when MAME logs that it is still held, or `times_out`, when
    no stop comes."""

    held: int
    stays: bool
    times_out: bool
    pending: str | None

    def log_held(self) -> None:
        with open(mfiles.log_path(self.scratch, "emulator"), "a") as fh:
            fh.write(HELD_LOG)

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        # The console runs every command of a `;` line inside the one request.
        if ";" in command:
            return "".join(self.monitor(one.strip(), timeout) for one in command.split(";"))
        word = {"ss": "statesave", "sl": "stateload"}.get(command.split()[0], command.split()[0])
        if word in ATTEMPTED and self.held > 0:
            self.held -= 1
            self.pending = f"{word} {command.split()[1]}"     # MAME's one pending slot
            self.log_held()
            return ATTEMPTED[word]
        return super().monitor(command, timeout)

    def step(self) -> str:
        if self.times_out:
            raise gs.Timeout("no stop packet within 10.0 s")
        stop = super().step()
        self.cycles_offset += STEP_CYCLES
        self.blocks[1]["PC"] = f"{self.pc:08x}"
        # THE INSTRUCTION RAN FIRST: the timeslice ends after it, and only then the operation.
        if self.pending is not None:
            if self.stays:
                self.log_held()
            else:
                command, self.pending = self.pending, None
                super().monitor(command)
        return stop


def _held(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, held: int = 0) -> _HeldSession:
    ses = cast(_HeldSession, _board(monkeypatch, tmp_path, threads={}, kind=_HeldSession))
    ses.held, ses.stays, ses.times_out, ses.pending = held, False, False, None
    return ses


def _saved_and_moved(ses: _HeldSession) -> int:
    """A state `a` saved in the command, then the machine moved: the pc it was saved at."""
    assert s.state_save(name="a")["status"] == "ok"
    saved_pc = ses.pc
    _moved(ses)
    ses.pc += 8
    return saved_pc


def test_the_fixture_carries_mames_words_for_a_held_save() -> None:
    """The known answer the double logs is the line `complete_held` looks for."""
    assert savestates.HELD_BY_TIMERS in HELD_LOG.splitlines()[0]


def test_a_save_mame_runs_in_the_command_takes_no_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _held(monkeypatch, tmp_path)
    out = s.state_save(name="a")
    assert out["status"] == "ok" and "held" not in out and "stop_seq" not in out, out
    assert ses.stepped == 0


def test_a_held_save_is_completed_by_one_step_and_records_the_machine_it_holds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _held(monkeypatch, tmp_path, held=1)
    at_send = ses.pc
    # a line logged since the last stop and before the save, which is not the save's
    with open(mfiles.log_path(ses.scratch, "emulator"), "a") as fh:
        fh.write("[:maincpu] logged before the save\n")
    out = s.state_save(name="a")
    assert out["status"] == "ok", out
    # the reply of a save that ran in the command, with what the hold adds and no survey
    assert set(out) == {"name", "path", "bytes", "frame", "pc", "errorlog", "held", "stop_seq",
                        "summary", "status", "session"}, sorted(out)
    assert ses.stepped == 1 and ses.pending is None
    # the record is the machine the file holds: the one after the step's instruction
    assert out["pc"] == mstate.hex_addr(ses.pc) != mstate.hex_addr(at_send), out
    assert mstate.STATE.states["a"]["pc"] == ses.pc
    assert mstate.STATE.states["a"]["blocks"][":maincpu"]["PC"] == f"{ses.pc:08x}"
    assert "stepped" in out["held"] and mstate.hex_addr(ses.pc) in out["held"], out
    # the reply's errorlog is the save's own: MAME's words, from the command on
    assert out["errorlog"]["lines_total"] == len(HELD_LOG.splitlines()), out["errorlog"]
    # the step is a stop, recorded as one
    assert mstate.STATE.last_stop["how"] == "statesave a", mstate.STATE.last_stop
    assert out["stop_seq"] == mstate.STATE.last_stop["seq"], out


def test_a_held_save_loads_back_verified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The record of a held save is the machine its file holds, so its load is proved by it."""
    ses = _held(monkeypatch, tmp_path, held=1)
    assert s.state_save(name="a")["status"] == "ok"
    _moved(ses)
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"] is True, out


def test_a_held_load_is_completed_by_one_step_and_verified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _held(monkeypatch, tmp_path)
    saved_pc = _saved_and_moved(ses)
    ses.held = 1
    out = s.state_load(name="a")
    assert out["status"] == "ok" and out["verified"] is True, out
    assert ses.stepped == 1 and ses.pc == saved_pc and "held" in out, out
    assert out["output"] == ATTEMPTED["stateload"].strip(), out


def test_a_load_still_held_after_the_step_is_refused_and_steps_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _held(monkeypatch, tmp_path)
    _saved_and_moved(ses)
    ses.held, ses.stays = 1, True
    out = s.state_load(name="a")
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert "next run" in out["message"], out
    assert ses.stepped == 1


def test_a_step_with_no_stop_is_not_settled_and_leaves_the_session_usable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """As the `step` tool answers it: `stop` recovers, nothing latches."""
    ses = _held(monkeypatch, tmp_path, held=1)
    ses.times_out = True
    out = s.state_save(name="a")
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert "`stop` recovers it" in out["message"], out
    assert not ses.broken


def test_a_held_load_typed_through_debug_is_completed_and_its_stop_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _held(monkeypatch, tmp_path)
    saved_pc = _saved_and_moved(ses)
    ses.held = 1
    out = s.debug(command="sl a")
    assert out["status"] == "ok", out
    assert ses.stepped == 1 and ses.pc == saved_pc
    assert "stepped" in str(out.get("note")), out
    assert mstate.STATE.last_stop["how"] == "debug: sl a", mstate.STATE.last_stop
    # the counter is marked after the load landed, so the next run withholds its cycles
    mark = mstate.STATE.stale_counter
    assert mark is not None and mark.reading == ses.totalcycles(), mark


def test_a_held_save_typed_through_debug_is_completed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _held(monkeypatch, tmp_path, held=1)
    out = s.debug(command="statesave b")
    assert out["status"] == "ok" and "stepped" in str(out.get("note")), out
    assert ses.stepped == 1
    assert (Path(s.state_list()["state_dir"]) / "b.sta").exists()


def test_a_typed_load_still_held_is_refused_and_still_marks_the_counter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The load may land inside the next run, whose cycles would span two machines."""
    ses = _held(monkeypatch, tmp_path)
    _saved_and_moved(ses)
    ses.held, ses.stays = 1, True
    out = s.debug(command="stateload a")
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert mstate.STATE.stale_counter is not None


def test_a_line_holding_two_saves_says_only_the_last_was_completed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """MAME keeps one pending operation: the second save replaced the first, which is lost."""
    ses = _held(monkeypatch, tmp_path, held=2)
    out = s.debug(command="statesave b; statesave c")
    assert out["status"] == "ok", out
    assert "held 2 saves or loads" in str(out.get("note")), out
    folder = Path(s.state_list()["state_dir"])
    assert ses.stepped == 1 and (folder / "c.sta").exists() and not (folder / "b.sta").exists()
