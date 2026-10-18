"""A step's `recorded`: what a session's reply said, which the replay's `perform` holds the step's
own reply to. A mismatch stops the list there as INVALID `diverged`, naming the field, what was
recorded and what came back (`failed_at`, as any step failure); a match is an ordinary step."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_server import _running  # noqa: E402

import server as s  # noqa: E402


def _read(recorded: dict[str, Any]) -> dict[str, Any]:
    return {"op": "read_memory", "ref": "0x4a0", "length": 2, "recorded": recorded}


def test_a_step_that_holds_to_what_was_recorded_runs_as_any_step(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _running(monkeypatch, tmp_path)
    first = s.read_memory(ref="0x4a0", length=2)
    out = s.perform(steps=[_read({"hex": first["hex"]}), _read({"hex": first["hex"]})])
    assert out["status"] == "ok", out.get("message")
    assert out["steps_completed"] == 2


def test_a_step_that_does_not_hold_stops_the_list_as_diverged(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _running(monkeypatch, tmp_path)
    got = s.read_memory(ref="0x4a0", length=2)["hex"]
    out = s.perform(steps=[_read({"hex": got}), _read({"hex": "ffff"}), _read({"hex": got})])
    assert out["status"] == "INVALID" and out["code"] == "diverged", out
    assert out["failed_at"] == 1 and out["steps_completed"] == 1
    assert (out["field"], out["recorded"], out["got"]) == ("hex", "ffff", got)
    assert out["failed"]["op"] == "read_memory" and out["failed"]["reply"]["hex"] == got
    assert "step 1 ('read_memory') diverged" in out["message"] and "diverged" in out["summary"]


def test_recorded_is_the_steps_own_and_never_reaches_the_tool(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "registers", "recorded": {}}])
    assert out["status"] == "ok", out.get("message")


def test_a_recorded_that_is_not_a_mapping_is_refused_before_any_step_runs(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "run_for", "frames": 1},
                           {"op": "read_memory", "ref": "0x4a0", "recorded": ["hex"]}])
    assert out["code"] == "bad_argument" and out.get("steps_completed", 0) == 0, out
    assert "recorded" in out["message"]
