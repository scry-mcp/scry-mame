"""MAME refreshes `totalcycles` only when the cpu executes
(`fixtures/console/totalcycles-after-load.txt`), so a run's `cycles` after a load span two machines.
"""

from __future__ import annotations

from typing import NamedTuple

import gdb_session as gs
import mame_console as console
import mame_cpus as cpus
import mame_read as read
from mame_state import STATE

#: Mark name of a load the tool sends.
STATE_LOAD = "state_write(method=load)"


class StaleCounter(NamedTuple):
    """`totalcycles` as read on `cpu` right after `command`."""

    cpu: str | None
    reading: int | None
    command: str


def cycles_why(command: str) -> str:
    """Why a run after `command` withholds `cycles`."""
    if console.is_reset(command):
        return (f"a `{command}` typed through `debug` is applied by the next run, which "
                "restarts `totalcycles` inside it, so that run's span crosses the reset; the "
                "run after it reports cycles")
    done = (f"`{command}`" if command == STATE_LOAD
            else f"`{command}` typed through `debug`")
    return (f"MAME's debugger refreshes `totalcycles` only when the cpu executes, so right after "
            f"{done} replaced the machine it still holds the count from before; the next run "
            "reports cycles")


def mark_stale_counter(ses: gs.Session, command: str) -> None:
    """Record `totalcycles` now, after `command`."""
    cpu, reading = _counter_now(ses)
    STATE.stale_counter = StaleCounter(cpu, reading, command)


def _counter_now(ses: gs.Session) -> tuple[str | None, int | None]:
    """The visible cpu and its `totalcycles`; None where unreadable."""
    if ses.broken:
        return None, None
    try:
        return cpus.visible_cpu(ses), read.print_values(ses, ["totalcycles"])[0]
    except gs.SessionError:
        return None, None


def stale_cycles_why(cpu: str | None, reading: int | None) -> str | None:
    """Why baseline `reading` on `cpu` is still stale, else None; consumes the mark."""
    mark, STATE.stale_counter = STATE.stale_counter, None
    if mark is None:
        return None
    stale = mark.reading is None or mark.cpu != cpu or mark.reading == reading
    return cycles_why(mark.command) if stale else None
