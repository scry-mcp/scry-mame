"""The window a watched start opens: asked for with `display` and `fullscreen`, proved in the host's
window list, answered by `window`; and the name of the tool that moves the debugger's cpu."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import pytest
from scry_core import window as core_window
from server_support import _boot_args, _stub_boot, _StubProcess
from window_double import Absent, Covered, ObeyingHost

from scry_mame import launch
from scry_mame import server as s
from scry_mame import state as mstate
from scry_mame.state import STATE


def _start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kw: Any) -> dict[str, Any]:
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    return cast(dict[str, Any], s.start(**_boot_args(tmp_path, image), **kw))


@pytest.mark.parametrize(("asked", "tail"), [
    ({}, ["-screen0", "screen0"]),
    ({"display": 1}, ["-screen0", "screen1"]),
    ({"fullscreen": False}, ["-screen0", "screen0"]),
])
def test_a_watched_start_asks_mame_for_the_display_and_proves_the_window(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, asked: dict[str, Any],
        tail: list[str]) -> None:
    got = _start(monkeypatch, tmp_path, shared=True, **asked)
    try:
        assert got["status"] == "ok", got
        assert _StubProcess.last_argv[-len(tail):] == tail and got["flags"][-len(tail):] == tail
        window = got["window"]
        assert window["display"] == asked.get("display", 0) and window["onscreen"] is True, window
        assert window["fullscreen"] is bool(asked.get("fullscreen")), window
    finally:
        s.close()


def test_fullscreen_is_refused_by_name_where_mame_has_none_and_passes_through_elsewhere(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """On macOS `-nowindow` opens the largest window below the menu bar, never the display."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    monkeypatch.setattr(launch, "NO_FULLSCREEN_ON", sys.platform)
    got = s.start(**args, shared=True, display=1, fullscreen=True)
    assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
    assert "fullscreen" in got["message"] and "macOS" in got["message"], got
    assert STATE.proc is None
    monkeypatch.setattr(launch, "NO_FULLSCREEN_ON", "a-platform-this-is-not")
    got = s.start(**args, shared=True, display=1, fullscreen=True)
    try:
        assert got["status"] == "ok", got
        assert got["flags"] == ["-nowindow", "-screen0", "screen1"], got["flags"]
        assert got["window"]["fullscreen"] is True, got
    finally:
        s.close()


def test_a_start_nobody_watches_asks_for_no_display_and_says_nothing_of_a_window(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    got = _start(monkeypatch, tmp_path)
    try:
        assert got["status"] == "ok" and "window" not in got, got
        assert "-screen0" not in got["flags"], got["flags"]
    finally:
        s.close()


@pytest.mark.parametrize("asked", [{"display": 0}, {"fullscreen": True},
                                   {"display": 1, "fullscreen": False}])
def test_the_window_arguments_without_shared_are_refused_not_ignored(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, asked: dict[str, Any]) -> None:
    got = _start(monkeypatch, tmp_path, **asked)
    assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
    assert "shared=true" in got["message"], got


def test_a_display_past_the_host_s_count_is_refused_naming_the_count(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    got = _start(monkeypatch, tmp_path, shared=True, display=5)
    assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
    assert "2 displays (0 to 1)" in got["message"], got
    assert STATE.proc is None


def test_a_window_mame_never_opened_refuses_the_start_and_leaves_the_session_to_close(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(core_window, "host", lambda _platform="": Absent())
    monkeypatch.setattr(launch, "WINDOW_WAIT_S", 0.0)
    got = _start(monkeypatch, tmp_path, shared=True)
    try:
        assert got["status"] == "INVALID" and got["code"] == "window_not_visible", got
        assert STATE.proc is not None, "the caller closes it, as the message says"
    finally:
        s.close()


def test_window_answers_where_the_window_is_and_with_front_brings_it_forward(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _start(monkeypatch, tmp_path, shared=True, display=1)
    try:
        got = s.window()
        assert got["status"] == "ok" and got["window"]["display"] == 1, got
        forward = s.window(front=True)
        assert forward["status"] == "ok" and forward["window"]["front"] is True, forward
    finally:
        s.close()


def test_window_front_activates_a_covered_window_and_without_front_only_reports_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    host = Covered()
    monkeypatch.setattr(core_window, "host", lambda _platform="": host)
    _start(monkeypatch, tmp_path, shared=True, display=1)
    try:
        host.activations = 0
        seen = s.window()
        assert seen["window"]["onscreen"] is False and host.activations == 0, seen
        forward = s.window(front=True)
        assert forward["window"]["onscreen"] is True and host.activations == 1, forward
    finally:
        s.close()


def test_a_session_whose_mame_has_died_is_session_broken_not_a_missing_window(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _start(monkeypatch, tmp_path, shared=True)
    try:
        assert STATE.proc is not None
        STATE.proc.kill()
        got = s.window()
        assert got["status"] == "INVALID" and got["code"] == "session_broken", got
    finally:
        s.close()


def test_a_fullscreen_that_does_not_fill_the_display_is_refused_not_reported(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Bordered(ObeyingHost):
        def windows(self) -> list[core_window.Seen]:
            return [core_window.Seen(w.pid, w.number, (w.bounds[0], w.bounds[1] + 30,
                                                       w.bounds[2], w.bounds[3] - 30), True)
                    for w in super().windows()]
    monkeypatch.setattr(core_window, "host", lambda _platform="": Bordered())
    monkeypatch.setattr(launch, "NO_FULLSCREEN_ON", "a-platform-this-is-not")
    got = _start(monkeypatch, tmp_path, shared=True, fullscreen=True)
    assert got["status"] == "INVALID" and got["code"] == "window_not_visible", got
    assert got["seen"]["fullscreen"] is False and "fullscreen" in got["message"], got
    s.close()


def test_window_refuses_without_a_session_and_for_a_headless_one(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    none = s.window()
    assert none["status"] == "INVALID" and none["code"] == "no_session", none
    _start(monkeypatch, tmp_path)
    try:
        headless = s.window()
        assert headless["status"] == "INVALID" and headless["code"] == "no_channel", headless
        assert "shared=true" in headless["message"], headless
    finally:
        s.close()


def test_the_background_judge_keeps_only_the_env_refusal_and_the_rest_is_core_s() -> None:
    with pytest.raises(mstate.Invalid, match="`env` sets"):
        launch.judge_background(None, True, {core_window.BACKGROUND_VAR: "1"})
    assert launch.judge_background(None, True, None) is False
    assert launch.judge_background(None, False, None) is True
    assert not hasattr(launch, "launch_environment") and not hasattr(launch, "BACKGROUND_VAR")


def test_the_tool_that_moves_the_debugger_s_cpu_is_named_for_the_cpu() -> None:
    names = {t.name for t in s.mcp._tool_manager.list_tools()}
    assert "cpu_focus" in names and "focus" not in names, sorted(names)
