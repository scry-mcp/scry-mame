"""`screen_wait`'s own half: which predicate it runs on, what it refuses before a frame runs,
and the loop it steps the machine with. The emulator is doubled at `advance.run_for` and at
each predicate's reader, because what is judged here is the loop's own bookkeeping: the polls it
counts, the frames it steps, and the step it says it sampled at."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from scry_mame import advance, wait
from scry_mame import gdb_session as gs
from scry_mame import state as mstate

NO_SESSION = cast(gs.Session, None)
DEADLINE_OK = {"status": "ok", "verdict": "ELAPSED", "frame_after": 1, "stop_seq": 1}


def _raises(code: str, call: Any) -> str:
    """The refusal's code, and its message: what a caller is told."""
    with pytest.raises(Exception) as got:
        call()
    assert getattr(got.value, "code", None) == code, (code, got.value)
    return str(got.value)


def _steps(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """`advance.run_for` as an ELAPSED stop, counting the frames each poll asked for."""
    asked: list[int] = []

    def run_for(ses: Any, scratch: Path, milliseconds: int, seconds: float, progress: Any,
                disarm_watches: bool = False, frames: int = 0,
                route: dict[str, Any] | None = None) -> dict[str, Any]:
        asked.append(frames)
        return dict(DEADLINE_OK, frame_after=len(asked) * (frames or 1))

    monkeypatch.setattr(advance, "run_for", run_for)
    return asked


def _palette(monkeypatch: pytest.MonkeyPatch, reads: list[list[str]]) -> None:
    """`mpalette.palette` answering `reads` in turn, the last one held."""
    left = list(reads)

    def palette(ses: Any, scratch: Path, name: str, first: int, count: int, scale: int,
                dest: str, seconds: float, progress: Any = None) -> dict[str, Any]:
        held = left.pop(0) if len(left) > 1 else left[0]
        return {"status": "ok", "colors": held, "entries": len(held)}

    monkeypatch.setattr("scry_mame.wait.mpalette.palette", palette)


def test_a_wait_names_exactly_one_predicate() -> None:
    for kw in ({}, {"text": "X", "screen": "a"}, {"text": "X", "palette": "black"},
               {"screen": "a", "palette": "black"}):
        got = _raises("bad_argument", lambda kw=kw: wait.screen_wait(
            NO_SESSION, Path("."), kw.get("text", ""), kw.get("screen", ""), kw.get("palette", ""),
            0, 30))
        assert "exactly one of" in got


def test_a_palette_it_does_not_know_and_a_step_out_of_range_are_refused() -> None:
    def once(palette: str, every: int) -> None:
        _raises("bad_argument", lambda: wait.screen_wait(NO_SESSION, Path("."), "", "",
                                                        palette, every, 30))
    once("red", 0)
    once("black", 601)
    once("black", -1)


def test_text_is_refused_by_name_because_this_server_hands_pixels() -> None:
    got = _raises("no_channel", lambda: wait.screen_wait(NO_SESSION, Path("."),
                                                        "GAME OVER", "", "", 0, 30))
    assert "screen_map_write" in got


def test_a_screen_no_map_holds_is_refused_before_a_frame_runs(
        monkeypatch: pytest.MonkeyPatch) -> None:
    mstate.STATE.maps = __import__("scry_core.screen_map", fromlist=["Maps"]).Maps()
    _raises("unknown_ref", lambda: wait.screen_wait(NO_SESSION, Path("."), "", "menu", "", 0, 30))


def test_a_palette_already_black_answers_at_once_and_the_machine_is_not_stepped(
        monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _steps(monkeypatch)
    _palette(monkeypatch, [["#000000"] * 256])
    r = wait.screen_wait(NO_SESSION, Path("."), "", "", "black", 0, 30)
    assert (r["verdict"], r["predicate"], r["already"]) == ("TARGET", "palette", True), r
    assert r["polls"] == 0 and asked == [], "already true: the machine is not stepped"


def test_one_poll_after_the_opening_read_finds_it_and_counts_its_frames(
        monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _steps(monkeypatch)
    _palette(monkeypatch, [["#101010"] * 256, ["#000000"] * 256])
    r = wait.screen_wait(NO_SESSION, Path("."), "", "", "black", 0, 30)
    assert (r["verdict"], r["already"], r["polls"]) == ("TARGET", False, 1), r
    assert asked == [1], "one poll of one frame"


def test_the_step_is_what_the_poll_asks_the_machine_to_run(
        monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _steps(monkeypatch)
    _palette(monkeypatch, [["#101010"] * 256, ["#000000"] * 256])
    r = wait.screen_wait(NO_SESSION, Path("."), "", "", "black", 5, 30)
    assert (r["verdict"], r["polls"], r["sampled_every"]) == ("TARGET", 5, 5), r
    assert asked == [5], "one poll of five frames"


def test_a_palette_that_never_goes_black_times_out_saying_what_it_examined(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _steps(monkeypatch)
    _palette(monkeypatch, [["#101010"] * 256])
    r = wait.screen_wait(NO_SESSION, Path("."), "", "", "black", 0, 0.001)
    assert r["verdict"] == "TIMEOUT" and r["predicate"] == "palette", r
    assert "was not found in" in r["note"] and "within 0.001 s" in r["note"], r


def test_the_screen_predicate_is_the_map_naming_the_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    _steps(monkeypatch)
    mstate.STATE.maps = __import__("scry_core.screen_map", fromlist=["Maps"]).Maps()
    seen = [{"status": "ok", "matched": True, "screen": "menu", "layer": "session"}]
    monkeypatch.setattr("scry_mame.wait.maps.screen_map_find", lambda *a: seen[0])
    mstate.STATE.maps.session["menu"] = __import__(
        "scry_core.screen_map", fromlist=["Screen"]).Screen(
            name="menu", kind="pixel", size=(256, 240),
            match=(([0, 0, 4, 1], "0" * 16),), controls=())
    r = wait.screen_wait(NO_SESSION, Path("."), "", "menu", "", 0, 30)
    assert (r["verdict"], r["predicate"], r["already"]) == ("TARGET", "screen", True), r
    assert r["screen"] == {"name": "menu", "layer": "session"}, r
