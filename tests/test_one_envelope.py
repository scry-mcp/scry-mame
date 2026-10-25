"""Every reply is closed by one seam: `summary` first, `session` last, composed after the body."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_server import _running  # noqa: E402
from test_watches import _watching  # noqa: E402

import mame_envelope as menvelope  # noqa: E402
import mame_mcp  # noqa: E402
import mame_sequence as sequence  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


@pytest.fixture
def late_tool() -> Any:
    """A decorated tool whose body releases the machine and adds a field after its envelope."""
    def late_body() -> dict[str, Any]:
        reply = menvelope.envelope({"first": 1})
        assert mstate.STATE.ses is not None
        mstate.STATE.ses.running = True
        reply["late"] = 2
        return reply

    registered = mame_mcp.tool("A late body", summary=lambda args, reply: "late: done")(late_body)
    yield registered
    s.mcp._tool_manager._tools.pop("late_body", None)
    mame_mcp.BOUNDARY.summaries.pop("late_body", None)
    mame_mcp.BOUNDARY.bodies.pop("late_body", None)


def test_the_decorator_puts_session_last_and_composes_it_after_the_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, late_tool: Any,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.running = False
    out = late_tool()
    assert list(out)[0] == "summary" and list(out)[-1] == "session", list(out)
    assert out["late"] == 2 and out["first"] == 1, out
    assert out["session"]["running"] is True, (
        "the block was composed before the body released the machine", out["session"])


def test_a_schema_refusal_is_closed_by_the_same_composer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A schema refusal never reaches the decorator, so the composer is called directly."""
    seen: list[str] = []
    real = mame_mcp.BOUNDARY.finished

    def spy(name: str, *a: Any, **k: Any) -> dict[str, Any]:
        seen.append(name)
        return real(name, *a, **k)

    monkeypatch.setattr(mame_mcp.BOUNDARY, "finished", spy)
    _running(monkeypatch, tmp_path).running = True
    res = asyncio.run(s.mcp.call_tool("run_for", {"frames": [1, 2]}))
    out = json.loads("".join(c.text for c in res.content if getattr(c, "text", None)))
    assert seen == ["run_for"] and out["code"] == "bad_argument", (seen, out)
    assert list(out)[0] == "summary" and list(out)[-1] == "session", list(out)
    assert out["session"]["running"] is True, out["session"]


@pytest.mark.parametrize("call", [
    pytest.param(lambda: s.declaration_list("breakpoint"), id="declaration_list breakpoint"),
    pytest.param(lambda: s.declaration_list("regpoint"), id="declaration_list regpoint"),
    pytest.param(lambda: s.comment_list(), id="comment_list"),
    pytest.param(lambda: s.cpu_info(), id="cpu_info"),
])
def test_a_reader_on_a_running_machine_says_running_in_the_session_block_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, call: Any,
) -> None:
    _running(monkeypatch, tmp_path)
    s.resume(seconds=0)
    out = call()
    assert out["status"] == "ok", out
    assert "running" not in out and out["session"]["running"] is True, out


def test_watch_list_on_a_running_machine_says_running_in_the_session_block_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _watching(monkeypatch, tmp_path)
    s.resume()
    out = s.declaration_list("watch")
    assert out["status"] == "ok", out
    assert "running" not in out and out["session"]["running"] is True, out


def test_resume_and_stop_say_running_in_the_session_block_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    released = s.resume(seconds=0)
    assert "running" not in released and released["session"]["running"] is True, released
    ses.running = False
    already = s.stop()
    assert "running" not in already and already["session"]["running"] is False, already


def test_a_debug_release_says_running_in_the_session_block_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    monkeypatch.setattr(mstate.STATE, "console_writes", 0)
    out = s.debug(command="g")
    assert "running" not in out and out["session"]["running"] is True, out


def test_a_sequence_asks_the_session_block_whether_a_step_left_the_machine_running() -> None:
    assert sequence._leaves_running("debug", {"session": {"running": True}})
    assert not sequence._leaves_running("debug", {"session": {"running": False}})
    assert not sequence._leaves_running("debug", {"running": True, "session": {"running": False}})


def test_status_says_running_and_names_which_pc_it_carries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`status` keeps `running`; its `pc` is read now, the last stop's lives in `last_stop.pc`."""
    _running(monkeypatch, tmp_path)
    stopped = s.status()
    assert stopped["session"]["running"] is False and stopped["pc"] == "0x000f2034", stopped
    assert "broken" not in stopped, stopped
    s.resume(seconds=0)
    moving = s.status()
    assert moving["session"]["running"] is True and moving["pc"]["available"] is False, moving
    assert moving["last_stop"]["pc"] == "0x000f2034" and "0x000f2034" in moving["summary"], moving
