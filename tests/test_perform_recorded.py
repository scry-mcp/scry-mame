"""A step's `recorded`: what a session's reply said, which the replay's `perform` holds the step's
own reply to. A mismatch stops the list there as INVALID `diverged`, naming the field, what was
recorded and what came back (`failed_at`, as any step failure); a match is an ordinary step."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from scry_core import demo, replay

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
    assert out["held"] == 2, "each step held to its recorded answer is counted"


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
    assert out["held"] == 1, "the step before the divergence held, the diverged one did not"


def test_the_replay_runner_reads_this_servers_own_diverged_reply(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The contract between this server's `perform` and the runner (`scry_core.replay`): the
    reply a diverged step gives is the one the runner names the step, the field and both values
    from, never an exit 3 for a reply it cannot read."""
    _running(monkeypatch, tmp_path)
    got = s.read_memory(ref="0x4a0", length=2)["hex"]
    steps = [_read({"hex": got}), _read({"hex": "ffff"}), _read({"hex": got})]
    out = s.perform(steps=steps)
    said = replay._failed(steps)(out, demo.Run(dir=tmp_path))
    assert said == f"diverged at step 2 of 3 (read_memory): hex recorded 'ffff', got {got!r}"


def test_recorded_is_the_steps_own_and_never_reaches_the_tool(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "registers", "recorded": {}}])
    assert out["status"] == "ok", out.get("message")
    assert out["held"] == 0, "an empty `recorded` holds the step to nothing"


def test_a_recorded_that_is_not_a_mapping_is_refused_before_any_step_runs(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "run_for", "frames": 1},
                           {"op": "read_memory", "ref": "0x4a0", "recorded": ["hex"]}])
    assert out["code"] == "bad_argument" and out.get("steps_completed", 0) == 0, out
    assert "recorded" in out["message"]


def test_the_lists_a_replay_reads_are_this_servers_own_tools() -> None:
    """The document names the tools a replay reads the store back through (`needs.declarations`):
    each is one this server registers, or every replay of its sessions would end at exit 3."""
    import mame_mcp

    served = {t.name for t in s.mcp._tool_manager.list_tools()}
    assert set(mame_mcp.RECORDER.lists) <= served
    assert set(mame_mcp.RECORDER.lists.values()) == {"breakpoints", "watches", "regpoints"}


def test_the_declarations_the_recorder_reads_are_the_refs_the_list_tools_answer(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """THE REPLAY'S PRECONDITION: the runner holds the replayed store, read through each list tool
    the recorder names, to what `_declared` read at the recorded start, so the two readings are one
    for every kind a `start` re-arms."""
    from test_watches import _watching

    import mame_mcp

    _watching(monkeypatch, tmp_path)
    assert s.breakpoint_at(ref="0x4a0")["status"] == "ok"
    assert s.watch_add(ref="frame_lo", mode="change", length=4)["status"] == "ok"
    assert s.regpoint_add(condition="pc == 0x10")["status"] == "ok"
    declared = mame_mcp.RECORDER._stored()
    for tool, key in mame_mcp.RECORDER.lists.items():
        listed = getattr(s, tool)()
        assert listed["status"] == "ok", (tool, listed.get("message"))
        assert sorted(r["ref"] for r in listed[key]) == sorted(declared[tool]), tool
    assert sum(len(refs) for refs in declared.values()) == 3
