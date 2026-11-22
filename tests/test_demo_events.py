"""The input a MAME demo's steps fired, as its run's timeline carries it: read from the
committed runs of the demos, which stand in for an emulator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from demo_transcripts import timeline_of  # noqa: E402

from demos import free_set
from demos.gridlee import demo as gridlee
from demos.lineup import demo as lineup
from demos.speedf import demo as speedf
from demos.starfire import demo as starfire

ROOT = Path(__file__).resolve().parents[1]
DEMOS = {"gridlee": gridlee.DEMO, "lineup": lineup.DEMO, "speedf": speedf.DEMO,
         "starfire": starfire.DEMO}


def _timeline(name: str) -> dict[str, Any]:
    return timeline_of(DEMOS[name], ROOT / "demos" / name / "TRANSCRIPT.md")


def _events(name: str, step: str) -> list[dict[str, Any]]:
    return [e for call in _timeline(name)["calls"] if call["step"] == step
            for e in call["events"]]


def test_a_coin_is_a_key_down_at_the_frame_the_field_was_set_and_up_when_released() -> None:
    assert _events("gridlee", "coin 4") == [
        {"kind": "key", "name": "Coin 1", "down": True, "frame": 667},
        {"kind": "key", "name": "Coin 1", "down": False, "frame": 671}]


def test_each_input_a_perform_ran_is_an_event_of_that_step() -> None:
    names = [(e["name"], e["down"]) for e in _events("gridlee", "coin 1")]
    assert names == [("Coin 1", True), ("Coin 1", False)]


def test_a_field_still_held_when_the_call_ends_is_let_go_at_the_frame_it_was_set() -> None:
    assert _events("starfire", "coin 4") == [
        {"kind": "key", "name": "Coin 1", "down": True, "frame": 284},
        {"kind": "key", "name": "Coin 1", "down": False, "frame": 284}]


def test_a_demo_that_presses_nothing_fires_nothing() -> None:
    assert [e for call in _timeline("speedf")["calls"] for e in call["events"]] == []


@pytest.mark.parametrize("name", sorted(DEMOS))
def test_every_committed_run_makes_a_timeline_the_decorator_can_read(name: str) -> None:
    calls = _timeline(name)["calls"]
    assert calls, f"{name}'s committed run holds no call"
    down = [e for call in calls for e in call["events"] if e["down"]]
    assert {e["kind"] for call in calls for e in call["events"]} <= {"key"}
    assert bool(down) == (name != "speedf")


def test_a_step_that_names_its_own_events_keeps_them() -> None:
    mine = free_set.Step("mine", "input", {}, lambda reply, run: "", events=lambda a, r: ())
    assert free_set.fired([mine])[0].events is mine.events


def test_only_the_tools_that_press_are_given_the_extractor() -> None:
    steps = [free_set.Step(tool, tool, {}, lambda reply, run: "")
             for tool in ("input", "perform", "run_for")]
    assert [s.events is not None for s in free_set.fired(steps)] == [True, True, False]


def test_a_refused_input_fires_nothing() -> None:
    refused = {"status": "refused", "summary": "x"}
    assert free_set.pressed({}, free_set.Reply(refused)) == []
