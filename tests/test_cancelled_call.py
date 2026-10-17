"""A CALL THE CLIENT CANCELLED: the tool ends at once as it declared (`on_cancel`), the lock is
free for the next call, and that next reply, whatever tool it is, says once what the cancelled
call left, since the cancelled one answers nothing. The cancellation itself is the poll every
bounded wait makes (`scry_core.cancel.check`), raised here at the poll a case chooses.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from scry_core import cancel
from scry_core import progress as mprogress

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_server import _running  # noqa: E402

import mame_mcp  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


def _cancel_at(monkeypatch: pytest.MonkeyPatch, poll: int) -> None:
    """The call is cancelled at its `poll`-th poll, counting the one on entry; the calls after
    it are other requests, which nobody cancelled."""
    polls = [0]

    def check() -> None:
        if cancel.shielding():
            return
        polls[0] += 1
        if polls[0] == poll:
            raise asyncio.CancelledError
    monkeypatch.setattr(cancel, "check", check)


@pytest.fixture
def waiting_tool() -> Iterator[Any]:
    """Tools whose body waits on a `Ticker` for a minute, one per declared end."""
    made = []
    for end in cancel.ON_CANCEL:
        def body(ctx: Any = None) -> dict[str, Any]:
            clock = mprogress.Ticker(60.0, mprogress.no_progress)
            while not clock.expired():
                pass
            return {"status": "ok"}
        body.__name__ = body.__qualname__ = f"wait_{end}"
        made.append(mame_mcp.tool(f"wait {end}", summary=lambda a, r: "waited",
                                  on_cancel=end)(body))
    yield dict(zip(cancel.ON_CANCEL, made, strict=True))
    for end in cancel.ON_CANCEL:
        s.mcp._tool_manager._tools.pop(f"wait_{end}", None)
        mame_mcp._SUMMARIES.pop(f"wait_{end}", None)
        mame_mcp._BODIES.pop(f"wait_{end}", None)


def _lock_is_free() -> bool:
    """Whether another thread can take the lock now, and give it back."""
    took: list[bool] = []

    def take() -> None:
        took.append(mame_mcp.LOCK.acquire(timeout=1.0))
        if took[-1]:
            mame_mcp.LOCK.release()
    t = threading.Thread(target=take)
    t.start()
    t.join()
    return took == [True]


def test_a_cancelled_wait_that_ends_stopped_stops_the_machine_and_the_next_reply_says_so(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    _cancel_at(monkeypatch, 3)
    with pytest.raises(asyncio.CancelledError):
        waiting_tool["stop"]()
    assert ses.running is False, "the machine was left running"
    out = s.status()
    assert out["cancelled"] == {"tool": "wait_stop", "after_s": 0.0, "left": "stopped"}, out
    assert out["summary"].startswith("after a cancelled wait_stop (stopped): "), out["summary"]
    assert list(out)[-1] == "session" and list(out)[-2] == "cancelled", list(out)
    assert "cancelled" not in s.status(), "the record rode on a second reply"


def test_a_cancelled_wait_that_ends_as_it_was_leaves_a_running_machine_running(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    _cancel_at(monkeypatch, 2)
    with pytest.raises(asyncio.CancelledError):
        waiting_tool["none"]()
    assert ses.running is True
    assert s.status()["cancelled"]["left"] == "running"


def test_a_cancelled_wait_that_ends_killed_closes_the_emulator(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    _running(monkeypatch, tmp_path)
    killed: list[bool] = []

    def kill(grace: bool = True, **_: Any) -> dict[str, Any]:
        killed.append(grace)
        return {}
    monkeypatch.setattr(mstate.STATE, "kill", kill)
    monkeypatch.setattr(mstate.STATE, "machine_alive", lambda: not killed)
    _cancel_at(monkeypatch, 2)
    with pytest.raises(asyncio.CancelledError):
        waiting_tool["kill"]()
    assert killed == [True], "the kill went without the grace that writes cfg/ and nvram/"
    assert mstate.STATE.cancelled is not None and mstate.STATE.cancelled.left == "closed"


def test_the_lock_is_free_once_a_cancelled_call_has_ended(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    _running(monkeypatch, tmp_path).running = True
    _cancel_at(monkeypatch, 2)
    with pytest.raises(asyncio.CancelledError):
        waiting_tool["stop"]()
    assert _lock_is_free()


def test_a_real_wait_cancelled_mid_run_ends_as_its_tool_declared(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`log_wait` on a running machine, the wait of the server itself: it ends as it was."""
    _running(monkeypatch, tmp_path).running = True
    _cancel_at(monkeypatch, 2)
    with pytest.raises(asyncio.CancelledError):
        s.log_wait(pattern="NEVER_THERE", channel="emulator", seconds=30.0)
    record = mstate.STATE.cancelled
    assert record is not None and record.tool == "log_wait" and record.left == "running"
    mstate.STATE.cancelled = None


def test_a_tool_that_waits_and_declares_no_end_is_refused_at_registration() -> None:
    def waits(ctx: Any = None) -> dict[str, Any]:
        return {"status": "ok"}
    with pytest.raises(TypeError, match="on_cancel"):
        mame_mcp.tool("waits", summary=lambda a, r: "")(waits)


def test_a_console_run_cancelled_in_flight_is_stopped_and_proved_at_rest(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A run the console started (`gtime`) sends no stop packet and leaves `running` unset while
    it is in flight: cancelled there, it is still moving, so its end has to stop it."""
    from test_server import _AliveProcess, _install, _RegisterSession

    import mame_advance as advance
    ses = _RegisterSession(bits=32, frame=10, stop_after=50)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "proc", _AliveProcess())
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    halts: list[bool] = []
    real_halt = ses.halt

    def halt() -> None:
        halts.append(True)
        real_halt()
    monkeypatch.setattr(ses, "halt", halt)
    _cancel_at(monkeypatch, 3)                 # entry, the first reading, then inside the wait
    with pytest.raises(asyncio.CancelledError):
        s.run_for(milliseconds=250)
    record = mstate.STATE.cancelled
    assert record is not None and record.left == "stopped", record
    assert halts, "the run still in flight was never interrupted"
    assert ses.running is False and mstate.STATE.console_run is False
    mstate.STATE.cancelled = None


def test_a_cancelled_run_to_records_its_own_interrupt_and_no_later_reply_finds_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0", role="control")
    _cancel_at(monkeypatch, 3)
    with pytest.raises(asyncio.CancelledError):
        s.run_to(ref="0x25a4", control="0x4a0", seconds=30.0)
    out = s.status()
    assert "stopped_on_its_own" not in out, out
    assert out["cancelled"]["tool"] == "run_to", out
    del ses


def test_the_record_survives_the_close_that_kills_and_rides_on_its_reply(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    _running(monkeypatch, tmp_path).running = True
    _cancel_at(monkeypatch, 2)
    with pytest.raises(asyncio.CancelledError):
        waiting_tool["none"]()
    def kill(*a: Any, **k: Any) -> dict[str, Any]:
        mstate.STATE._reset()
        return {"ended_by": "quit", "exit_code": 0}
    monkeypatch.setattr(mstate.STATE, "kill", kill)
    out = s.close()
    assert out.get("cancelled", {}).get("tool") == "wait_none", list(out)


def test_only_the_outer_reply_of_a_sequence_carries_the_record(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    _running(monkeypatch, tmp_path).running = True
    _cancel_at(monkeypatch, 2)
    with pytest.raises(asyncio.CancelledError):
        waiting_tool["none"]()
    s.stop()  # noqa: F841 -- ends the run the double was left in; this reply carries the record
    _cancel_at(monkeypatch, 2)
    with pytest.raises(asyncio.CancelledError):
        waiting_tool["none"]()
    out = s.perform(steps=[{"op": "registers"}], settle_seconds=0.0)
    assert out.get("cancelled", {}).get("tool") == "wait_none", list(out)
    assert all("cancelled" not in (r.get("reply") or {}) for r in out.get("ran", [])), out["ran"]


def test_a_call_cancelled_while_it_waited_for_the_lock_touches_nothing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _running(monkeypatch, tmp_path)
    writes = ses.writes
    _cancel_at(monkeypatch, 1)
    with pytest.raises(asyncio.CancelledError):
        s.write(ref="0x100", data_hex="aa")
    assert ses.writes == writes
