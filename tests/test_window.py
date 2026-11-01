"""The window a watched start opens: asked for with `display` and `fullscreen`, proved in the host's
window list, answered by `window`; and the name of the tool that moves the debugger's cpu."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import pytest
from scry_core import conformance
from scry_core import window as core_window
from scry_core.reply_contract import Invalid
from server_support import _boot_args, _stub_boot, _StubProcess
from window_double import asked as session_window

from scry_mame import launch
from scry_mame import server as s
from scry_mame import state as mstate
from scry_mame.state import STATE


class _Subject:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.monkeypatch, self.tmp_path = monkeypatch, tmp_path
        self.asked = session_window
        self.shows_fullscreen = sys.platform not in launch.NO_FULLSCREEN_ON

    def start(self, **arguments: Any) -> dict[str, Any]:
        return _start(self.monkeypatch, self.tmp_path, **arguments)

    def window(self, front: bool = False) -> dict[str, Any]:
        return cast(dict[str, Any], s.window(front=front))

    def close(self) -> dict[str, Any]:
        return cast(dict[str, Any], s.close())

    def status(self) -> dict[str, Any]:
        return cast(dict[str, Any], s.status())

    def has_session(self) -> bool:
        return STATE.proc is not None


class TestMameWindow(conformance.SessionContract):
    @pytest.fixture
    def subject(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Subject:
        return _Subject(monkeypatch, tmp_path)


def _start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kw: Any) -> dict[str, Any]:
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    return cast(dict[str, Any], s.start(**_boot_args(tmp_path, image), **kw))


@pytest.mark.parametrize(("asked", "tail"), [
    ({}, ["-screen0", "screen0"]),
    ({"display": 1}, ["-screen0", "screen1"]),
    ({"fullscreen": False}, ["-screen0", "screen0"]),
])
def test_a_watched_start_asks_mame_for_the_display(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, asked: dict[str, Any],
        tail: list[str]) -> None:
    got = _start(monkeypatch, tmp_path, shared=True, **asked)
    try:
        assert got["status"] == "ok", got
        assert _StubProcess.last_argv[-len(tail):] == tail and got["flags"][-len(tail):] == tail
    finally:
        s.close()


def test_fullscreen_is_refused_by_name_where_mame_has_none_and_passes_through_elsewhere(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """On macOS and Windows `-nowindow` opens a window the display's work area holds, never the
    display."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    monkeypatch.setattr(launch, "NO_FULLSCREEN_ON", (sys.platform,))
    got = s.start(**args, shared=True, display=1, fullscreen=True)
    assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
    assert "fullscreen" in got["message"] and "-nowindow" in got["message"], got
    assert STATE.proc is None
    monkeypatch.setattr(launch, "NO_FULLSCREEN_ON", ())
    got = s.start(**args, shared=True, display=1, fullscreen=True)
    try:
        assert got["status"] == "ok", got
        assert got["flags"] == ["-nowindow", "-screen0", "screen1"], got["flags"]
        assert got["window"]["fullscreen"] is True, got
    finally:
        s.close()


@pytest.mark.parametrize(("platform", "refused"), [("darwin", True), ("win32", True),
                                                    ("linux", False)])
def test_fullscreen_is_refused_on_the_platforms_where_nowindow_was_measured_not_to_fill_it(
        monkeypatch: pytest.MonkeyPatch, platform: str, refused: bool) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    asked = core_window.WindowRequest(0, True, (0, 0))
    if refused:
        with pytest.raises(Invalid) as e:
            launch.refuse_fullscreen_that_cannot_show(asked)
        assert e.value.code == "bad_argument" and "-nowindow" in str(e.value)
    else:
        launch.refuse_fullscreen_that_cannot_show(asked)


def test_a_start_nobody_watches_asks_for_no_display_and_says_nothing_of_a_window(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    got = _start(monkeypatch, tmp_path)
    try:
        assert got["status"] == "ok" and "window" not in got, got
        assert "-screen0" not in got["flags"], got["flags"]
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


def test_the_background_judge_keeps_only_the_env_refusal_and_the_rest_is_core_s() -> None:
    with pytest.raises(mstate.Invalid, match="`env` sets"):
        launch.judge_background(None, True, {core_window.BACKGROUND_VAR: "1"})
    assert launch.judge_background(None, True, None) is False
    assert launch.judge_background(None, False, None) is True
    assert not hasattr(launch, "launch_environment") and not hasattr(launch, "BACKGROUND_VAR")


def test_the_tool_that_moves_the_debugger_s_cpu_is_named_for_the_cpu() -> None:
    names = {t.name for t in s.mcp._tool_manager.list_tools()}
    assert "cpu_focus" in names and "focus" not in names, sorted(names)
