"""The idle bound (`idle`), with its clock given, and its wiring into the server: the
wrapper restarts the clock, `main` starts the watch, a start clears the note."""

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from scry_core import boundary
from server_support import _boot_args, _stub_boot  # noqa: E402

from scry_mame import idle  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import session as msession  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

LATE = idle.IDLE_CLOSE_S + 1


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> idle.Idle:
    fresh = idle.Idle()
    monkeypatch.setattr(idle, "IDLE", fresh)
    return fresh


def _never() -> None:
    raise AssertionError("closed a session it should have left alone")


def test_an_idle_session_is_closed_past_the_bound_and_the_reply_says_why(
    clock: idle.Idle,
) -> None:
    lock = boundary.ServerLock()
    closed: list[bool] = []
    assert not clock.reap(lock, lambda: True, _never, now=clock.last_call + LATE - 2)
    assert clock.reap(lock, lambda: True, lambda: closed.append(True),
                      now=clock.last_call + LATE)
    assert closed == [True] and "60 minutes with no tool call" in clock.note()
    assert "(the bound is 60 minutes)" in clock.note(), "a number says its unit"
    with pytest.raises(mstate.Invalid) as e:
        mstate.no_machine()
    assert clock.note() in str(e.value) and "call `start` first" in str(e.value)
    mstate.STATE.ses = None
    assert msession.status()["note"] == clock.note()


def test_no_note_before_the_bound_closed_anything(clock: idle.Idle) -> None:
    assert "note" not in msession.status()
    with pytest.raises(mstate.Invalid) as e:
        mstate.no_machine()
    assert str(e.value).startswith("no machine running; call `start` first")


def test_a_call_in_progress_or_a_session_already_gone_is_never_closed(clock: idle.Idle) -> None:
    lock = boundary.ServerLock()
    late = clock.last_call + LATE
    assert not clock.reap(lock, lambda: False, _never, now=late)
    held, release = threading.Event(), threading.Event()

    def call() -> None:
        with lock:
            held.set()
            release.wait(5)

    worker = threading.Thread(target=call)
    worker.start()
    held.wait(5)
    try:
        assert not clock.reap(lock, lambda: True, _never, now=late)
    finally:
        release.set()
        worker.join()


def test_a_call_that_ends_while_the_bound_takes_the_lock_keeps_the_session(
    clock: idle.Idle,
) -> None:
    """The look and the acquire are two moments: a call ending between them restarted the
    clock, and the bound reads it again under the lock."""

    class EndsACall:
        def acquire(self, blocking: bool = True) -> bool:
            clock.touch()
            return True

        def release(self) -> None:
            pass

    assert not clock.reap(EndsACall(), lambda: True, _never)  # type: ignore[arg-type]


def test_a_call_ending_restarts_the_clock_and_the_wrapper_is_what_ends_one(
    clock: idle.Idle,
) -> None:
    clock.last_call -= LATE
    s.status()
    assert not clock.reap(boundary.ServerLock(), lambda: True, _never)


def test_main_watches_with_the_tool_lock_the_machine_and_close(
    monkeypatch: pytest.MonkeyPatch, clock: idle.Idle,
) -> None:
    watched: list[tuple[Any, ...]] = []
    monkeypatch.setattr(clock, "watch", lambda *a: watched.append(a))
    monkeypatch.setattr(s.mcp, "run", lambda *a, **k: None)
    s.main()
    assert watched == [(mstate.LOCK, mstate.STATE.machine_alive, msession.close)], watched


def test_the_watch_survives_a_close_that_raises_and_says_so(
    monkeypatch: pytest.MonkeyPatch, clock: idle.Idle, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(idle, "IDLE_POLL_S", 0.01)
    calls: list[int] = []

    def close() -> None:
        calls.append(1)
        clock.last_call -= LATE
        raise RuntimeError("the drain broke")

    clock.last_call -= LATE
    clock.watch(boundary.ServerLock(), lambda: True, close)
    deadline = time.monotonic() + 5
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(calls) >= 2, "the watch died on the first raise"
    assert "the close raised RuntimeError: the drain broke" in capsys.readouterr().err


def test_a_new_start_clears_the_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clock: idle.Idle,
) -> None:
    """The note is about the last session; a session started since is the answer to it, and a
    later plain `close` must not be reported as the bound's."""
    image = bytes(16)
    clock._closed_why = "the last session was closed by this server after 61 minutes"
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    out = s.start(**_boot_args(tmp_path, image))
    assert out["status"] == "ok", out
    s.close()
    assert clock.note() == "" and "note" not in msession.status()
