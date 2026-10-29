"""A session no tool has touched for `IDLE_CLOSE_S` is closed by the server."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

from scry_core import boundary

#: Longer than any pause between a working session's calls.
IDLE_CLOSE_S = 3600.0

IDLE_POLL_S = 60.0


class Idle:
    """When the last tool call ended, and why the bound last closed a session."""

    def __init__(self) -> None:
        self.last_call = time.monotonic()
        self._closed_why = ""

    def touch(self) -> None:
        self.last_call = time.monotonic()

    def note(self) -> str:
        """Why there is no machine, when the bound closed the last one; empty otherwise."""
        return self._closed_why

    def clear_note(self) -> None:
        """A new session answers the note."""
        self._closed_why = ""

    def _idle_s(self, now: float | None) -> float:
        return (time.monotonic() if now is None else now) - self.last_call

    def reap(self, lock: boundary.ServerLock, alive: Callable[[], bool],
             close: Callable[[], object], now: float | None = None) -> bool:
        """Close the session if idle past the bound and `lock` is free; say whether it did."""
        if self._idle_s(now) < IDLE_CLOSE_S or not lock.acquire(blocking=False):
            return False
        try:
            # a call may have ended between the first look and the acquire
            idle = self._idle_s(now)
            if idle < IDLE_CLOSE_S or not alive():
                return False
            close()
            self._closed_why = (f"the last session was closed by this server after "
                                f"{idle / 60:.0f} minutes with no tool call (the bound is "
                                f"{IDLE_CLOSE_S / 60:.0f} minutes), so its emulator would not "
                                "run on abandoned")
            return True
        finally:
            lock.release()

    def watch(self, lock: boundary.ServerLock, alive: Callable[[], bool],
              close: Callable[[], object]) -> None:
        """Apply the bound on a daemon thread that survives a raising close."""
        def loop() -> None:
            while True:
                time.sleep(IDLE_POLL_S)
                try:
                    self.reap(lock, alive, close)
                except Exception as e:  # noqa: BLE001 -- said, and the watch goes on
                    print(f"mame idle bound: the close raised {type(e).__name__}: {e}",
                          file=sys.stderr, flush=True)
        threading.Thread(target=loop, name="idle-bound", daemon=True).start()


IDLE = Idle()
