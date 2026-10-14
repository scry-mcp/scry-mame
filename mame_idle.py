"""The idle bound: a session no tool has touched for `IDLE_CLOSE_S` is closed by the server.

The clock restarts when a call ends, so a call's own bounded wait never counts, and a call in
progress is never interrupted: it holds the server's lock, which the bound only ever tries. The
close is the ordinary `close`, and the next reply that finds no machine says why (`note`).
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

#: A SESSION NO TOOL TOUCHED FOR AN HOUR IS ABANDONED. Longer than any pause a working session
#: makes between calls (a question waiting on its owner, a measurement read and thought over),
#: and short enough that a forgotten machine costs an hour of a core, not a night.
IDLE_CLOSE_S = 3600.0

#: How often the server looks for an idle session: the bound is an hour, a minute late is
#: nothing.
IDLE_POLL_S = 60.0


class Idle:
    """When the last tool call ended, and what the bound last closed. One per server, like the
    machine it watches."""

    def __init__(self) -> None:
        self.last_call = time.monotonic()
        self._closed_why = ""

    def touch(self) -> None:
        self.last_call = time.monotonic()

    def note(self) -> str:
        """Why there is no machine, when the bound closed the last one; empty otherwise."""
        return self._closed_why

    def clear_note(self) -> None:
        """A new session is the answer to that note."""
        self._closed_why = ""

    def _idle_s(self, now: float | None) -> float:
        return (time.monotonic() if now is None else now) - self.last_call

    def reap(self, lock: threading.RLock, alive: Callable[[], bool],
             close: Callable[[], object], now: float | None = None) -> bool:
        """Close the session if it has been idle past the bound and no call holds `lock`;
        answer whether it did."""
        if self._idle_s(now) < IDLE_CLOSE_S or not lock.acquire(blocking=False):
            return False
        try:
            # READ AGAIN UNDER THE LOCK: a call may have ended, or closed the session, between
            # the look above and the acquire.
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

    def watch(self, lock: threading.RLock, alive: Callable[[], bool],
              close: Callable[[], object]) -> None:
        """Apply the bound for the life of the server, on a thread of its own. A close that
        raises is said on stderr, the server's log, and the bound keeps watching: a thread that
        died on it would leave every later session with no bound and nobody told."""
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
