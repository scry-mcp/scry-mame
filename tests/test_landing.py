"""A control on the instruction a frame stop lands on is counted by the run by frames, which
releases that instruction unevaluated (`breakpoints.count_landing` says why)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_server import _install, _RegisterSession  # noqa: E402

import mame_advance as advance  # noqa: E402
import mame_breakpoints as breakpoints  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

HANDLER = 0x564                 # where every frame stop of the double lands
NEXT = 0x568


class _Landing(_RegisterSession):
    """The frame double, every stop landing at `landing`."""

    landing = HANDLER

    def current_pc(self) -> int:
        return self.landing


def _frames(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Landing:
    reg = _Landing(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    monkeypatch.setattr(mstate.STATE, "controls", {})
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    return reg


def _control(addr: int, index: int, cpu: str = ":maincpu") -> dict[str, Any]:
    owner = (f"{addr:#x}", cpu)
    mstate.STATE.controls[owner] = rec = {"addr": addr, "temp": index, "index": index,
                                          "missed": 0}
    mstate.STATE.breakpoints[index] = {"owner": owner, "addr": addr, "cpu": cpu}
    return rec


def test_each_landing_a_run_by_frames_releases_is_counted_and_the_last_is_left(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Three `gvblank`s release the start and two landings; the start was the park, whose
    instruction a later release owns, and the third landing is released by the next call."""
    _frames(monkeypatch, tmp_path)
    on, off = _control(HANDLER, 1), _control(NEXT, 2)
    out = s.run_for(frames=3, seconds=5.0)
    assert out["verdict"] == "ELAPSED", out
    assert (on["missed"], off["missed"]) == (2, 0)


def test_a_run_by_frames_releases_the_landing_the_previous_one_ended_at(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _frames(monkeypatch, tmp_path)
    on = _control(HANDLER, 1)
    s.run_for(frames=3, seconds=5.0)
    s.run_for(frames=2, seconds=5.0)
    assert on["missed"] == 2 + 2, "the second run's first `gvblank` releases the first's end"


def test_a_pc_moved_since_the_last_frame_stop_is_not_that_landing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reg = _frames(monkeypatch, tmp_path)
    on = _control(HANDLER, 1)
    s.run_for(frames=1, seconds=5.0)
    reg.landing = NEXT                    # a read stepped it on
    s.run_for(frames=1, seconds=5.0)
    assert on["missed"] == 0


def test_a_control_on_another_cpu_at_the_landing_pc_is_not_counted(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _frames(monkeypatch, tmp_path)
    sub = _control(HANDLER, 1, cpu=":subcpu")
    s.run_for(frames=3, seconds=5.0)
    assert sub["missed"] == 0


def test_a_count_read_adds_the_landings_to_the_temp(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _frames(monkeypatch, tmp_path)
    _control(HANDLER, 1)["missed"] = 3
    monkeypatch.setattr(breakpoints.read, "print_values", lambda ses, names: [4])  # type: ignore[attr-defined]
    assert breakpoints.control_counts(mstate.STATE.ses) == {(f"{HANDLER:#x}", ":maincpu"): 7}  # type: ignore[arg-type]


def test_a_count_written_through_debug_restarts_from_the_value_written(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _frames(monkeypatch, tmp_path)
    on = _control(HANDLER, 1)
    on["missed"] = 3
    out = s.debug(command="temp1 = 0")
    assert out["status"] == "ok", out
    assert on["missed"] == 0
