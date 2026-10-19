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
        mame_mcp.BOUNDARY.summaries.pop(f"wait_{end}", None)
        mame_mcp.BOUNDARY.bodies.pop(f"wait_{end}", None)
        mame_mcp.BOUNDARY.declared_ends.pop(f"wait_{end}", None)


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


@pytest.mark.parametrize("end", ["stop", "kill"])
def test_a_call_cancelled_in_the_queue_applies_no_end_and_keeps_no_record(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any],
        end: str) -> None:
    """Cancelled before its body ran, the call did nothing, so it has nothing to end: a queued
    `start` that killed the session it never touched would be the worst of it."""
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    killed: list[bool] = []
    def kill(*a: Any, **k: Any) -> dict[str, Any]:
        killed.append(True)
        return {}
    monkeypatch.setattr(mstate.STATE, "kill", kill)
    _cancel_at(monkeypatch, 1)
    with pytest.raises(asyncio.CancelledError):
        waiting_tool[end]()
    assert ses.running is True and killed == []
    assert mstate.STATE.cancelled is None


def test_a_second_cancel_keeps_the_name_of_the_first_no_reply_reported(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    _running(monkeypatch, tmp_path).running = True
    for _ in range(2):
        _cancel_at(monkeypatch, 2)
        with pytest.raises(asyncio.CancelledError):
            waiting_tool["none"]()
    assert s.status()["cancelled"]["earlier"] == ["wait_none"]


def test_the_stop_end_hands_the_next_reply_a_stop_the_machine_had_reached_on_its_own(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    """The end's stop reply goes to nobody, so what it found rides on the next one. The stop is
    found where it is in the server, by the contact the end makes (`running.contact`), never
    planted by a double of `running.stop`."""
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    ses.stops_after_polls = 1                  # the stop packet waits for the first poll
    _cancel_at(monkeypatch, 2)
    with pytest.raises(asyncio.CancelledError):
        waiting_tool["stop"]()
    found = s.status().get("stopped_on_its_own", {})
    assert ses.interrupted == 0, "the end interrupted a machine that had already stopped"
    assert found.get("stop_seq") == mstate.STATE.last_stop["seq"], found


def test_a_schema_refusal_whose_call_was_cancelled_spends_no_account(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Its reply goes to nobody, so the record another cancelled call left must wait for the
    next one."""
    from pydantic import BaseModel, ValidationError

    class _M(BaseModel):
        n: int
    try:
        _M(n="x")  # type: ignore[arg-type]
    except ValidationError as e:
        cause = e
    mstate.STATE.cancelled = cancel.Cancelled("run_for", 1.0, "stopped")
    _cancel_at(monkeypatch, 1)
    with pytest.raises(asyncio.CancelledError):
        mame_mcp.refusal("read_memory", {"ref": 5}, cause)
    assert mstate.STATE.cancelled is not None and mstate.STATE.cancelled.tool == "run_for"
    mstate.STATE.cancelled = None


def test_a_start_cancelled_before_its_session_is_up_is_killed_without_a_grace(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    """Nobody can ask a MAME with no session to quit, so waiting for it to is time held."""
    from test_server import _AliveProcess
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "proc", _AliveProcess())
    graces: list[bool] = []

    def kill(progress: Any = None, grace: bool = True) -> dict[str, Any]:
        graces.append(grace)
        return {}
    monkeypatch.setattr(mstate.STATE, "kill", kill)
    _cancel_at(monkeypatch, 2)
    with pytest.raises(asyncio.CancelledError):
        waiting_tool["kill"]()
    assert graces == [False], graces
    mstate.STATE.cancelled = None


def test_a_step_of_a_sequence_cancelled_is_the_sequences_cancel_alone(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    _running(monkeypatch, tmp_path)
    _cancel_at(monkeypatch, 3)                 # perform's entry, the step's entry, its wait
    with pytest.raises(asyncio.CancelledError):
        s.perform(steps=[{"op": "wait_none"}], settle_seconds=0.0)
    out = s.status()
    assert out["cancelled"]["tool"] == "perform" and "earlier" not in out["cancelled"], out


def test_the_stop_a_cancel_made_is_not_called_a_refusal(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0", role="control")
    _cancel_at(monkeypatch, 3)
    with pytest.raises(asyncio.CancelledError):
        s.run_to(ref="0x25a4", control="0x4a0", seconds=30.0)
    how = s.status()["last_stop"]["how"]
    assert "refused" not in how and "cancel" in how, how


def test_a_machine_that_died_under_the_cancelled_call_is_left_closed(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiting_tool: dict[str, Any]) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.running = True

    class _Dead:
        pid = 4242

        def poll(self) -> int:
            return 1
    _cancel_at(monkeypatch, 2)

    monkeypatch.setattr(mstate.STATE, "proc", _Dead())
    with pytest.raises(asyncio.CancelledError):
        waiting_tool["stop"]()
    assert mstate.STATE.cancelled is not None and mstate.STATE.cancelled.left == "closed"
    mstate.STATE.cancelled = None


def test_a_step_over_cancelled_while_it_waits_for_rest_is_stopped_as_its_own(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`over` is a console run: cancelled in the wait for the pc to settle (`_settled_pc`, a
    bounded wait that polls), it ends as its bound does, stopped."""
    from test_server import _AliveProcess, _install, _RegisterSession

    import mame_advance as advance
    ses = _RegisterSession(bits=32, frame=10, stop_after=50)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "proc", _AliveProcess())
    monkeypatch.setattr(mstate.STATE, "ses", ses)

    def cancelled_while_settling(_ses: Any) -> bool:
        raise asyncio.CancelledError
    monkeypatch.setattr(advance, "_settled_pc", cancelled_while_settling)
    with pytest.raises(asyncio.CancelledError):
        s.step(mode="over")
    record = mstate.STATE.cancelled
    assert record is not None and record.left == "stopped", record
    mstate.STATE.cancelled = None


def test_a_run_for_cancelled_at_its_last_line_has_already_recorded_its_landing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The last progress line is a poll: met there, a cancel must find the landing recorded,
    or the machine rests where no record says it is."""
    from test_server import _AliveProcess, _install, _RegisterSession

    import mame_advance as advance
    ses = _RegisterSession(bits=32, frame=10, stop_after=4)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "proc", _AliveProcess())
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    seq_before = (mstate.STATE.last_stop or {}).get("seq", 0)

    def cancelled_at_the_last_line(self: Any, *a: Any, **k: Any) -> None:
        raise asyncio.CancelledError
    monkeypatch.setattr(mprogress.Ticker, "finish", cancelled_at_the_last_line)
    with pytest.raises(asyncio.CancelledError):
        s.run_for(frames=3)
    assert (mstate.STATE.last_stop or {}).get("seq", 0) > seq_before, mstate.STATE.last_stop
    mstate.STATE.cancelled = None


def test_until_frame_lands_the_list_before_its_last_line_a_cancel_can_meet(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The last line of a window (`Ticker.finish`) is a poll: the list's landing (the visible cpu
    put back) comes before it, as `run_for`'s does, so a cancel met there leaves nothing undone."""
    from test_perform import FRAME_STEP, _frames_and_the_watch

    import mame_cpus as mcpus
    import mame_sequence as sequence
    ses = _frames_and_the_watch(monkeypatch, tmp_path)
    start = ses.frame
    monkeypatch.setitem(mstate.STATE.last_stop, "frame", start)
    landed: list[str] = []
    monkeypatch.setattr(mcpus, "cpu_list", lambda ses: [":maincpu", ":sub"])

    def keep_visible(ses: Any, was: Any, asked: Any) -> dict[str, Any]:
        landed.append("kept")
        return {"after": ":maincpu"}
    monkeypatch.setattr(sequence, "_keep_visible", keep_visible)

    real_finish = mprogress.Ticker.finish

    def cancelled_at_the_windows_last_line(self: Any, total: float, template: str, /,
                                           **k: Any) -> None:
        if template.startswith("perform until frame"):
            raise asyncio.CancelledError
        real_finish(self, total, template, **k)
    monkeypatch.setattr(mprogress.Ticker, "finish", cancelled_at_the_windows_last_line)
    with pytest.raises(asyncio.CancelledError):
        sequence.run_steps(ses, tmp_path, [FRAME_STEP], 1.0, s._step_ops(), summaries=True,
                           until_frame=start + 2)
    assert landed == ["kept"]


def test_a_call_cancelled_as_its_body_returned_is_recorded_and_its_account_waits(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A `status` that found a stop of its own and whose cancel came as it returned: its reply
    goes to nobody, so the next one says both that it was cancelled and what it found; no end is
    applied, since the body reached its own."""
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    ses.stops_after_polls = 1
    _cancel_at(monkeypatch, 2)               # the poll after the body, not the entry's
    with pytest.raises(asyncio.CancelledError):
        s.status()
    out = s.status()
    assert out["cancelled"]["tool"] == "status" and out["cancelled"]["left"] == "stopped", out
    assert out.get("stopped_on_its_own", {}).get("stop_seq") == mstate.STATE.last_stop["seq"]
    assert ses.interrupted == 0
