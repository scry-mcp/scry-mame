"""The server adds no hit of its own to a control at a frame stop's landing."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server_support import _install, _RegisterSession  # noqa: E402

from scry_mame import (
    advance,  # noqa: E402
)
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

HANDLER = 0x564                 # where every frame stop of the double lands


class _Landing(_RegisterSession):
    def current_pc(self) -> int:
        return HANDLER


def _control(addr: int, index: int, cpu: str = ":maincpu") -> dict[str, Any]:
    owner = (f"{addr:#x}", cpu)
    mstate.STATE.controls[owner] = rec = {"addr": addr, "temp": index, "index": index}
    mstate.STATE.breakpoints[index] = {"owner": owner, "addr": addr, "cpu": cpu}
    return rec


def test_a_run_by_frames_adds_no_hit_of_its_own_to_a_control_at_the_landing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install(monkeypatch, _Landing(bits=32, frame=10, stop_after=1), tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    monkeypatch.setattr(mstate.STATE, "controls", {})
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    on = _control(HANDLER, 1)
    out = s.run_for(frames=3, seconds=5.0)
    assert out["verdict"] == "ELAPSED", out
    assert on == {"addr": HANDLER, "temp": 1, "index": 1}, on
