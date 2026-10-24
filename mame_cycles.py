"""THE `totalcycles` A RUN STARTS FROM, when a command left it stale: what was read right after
that command, and the reason a run whose baseline still reads it withholds its `cycles`.

A run's `cycles` right after a load would span two machines: MAME's debugger refreshes
`totalcycles` only when the cpu executes (`fixtures/console/totalcycles-after-load.txt`), so the
baseline is still the count from before the load and the span is off by the distance between
the two states, too short after loading an older one and too long after a newer one, plausible
either way. A rewind does the same, and a reset typed through `debug` is applied by the next run,
which restarts the count inside it (`mame_console.stale_counter_command` says which commands).
So the counter is read once the command is done, and a baseline that still reads it is
withheld. A stop recorded since is no proof that anything executed.
"""

from __future__ import annotations

from typing import NamedTuple

import gdb_session as gs
import mame_console as console
import mame_cpus as cpus
import mame_read as read
from mame_state import STATE

#: The command name `state_write(method="load")` the tool sends is marked under: it is not typed.
STATE_LOAD = "state_write(method=load)"


class StaleCounter(NamedTuple):
    """What `totalcycles` read right after `command` left it stale, on `cpu` (None where the
    console could not say either)."""

    cpu: str | None
    reading: int | None
    command: str


def cycles_why(command: str) -> str:
    """Why a run starting right after `command` withholds its `cycles`."""
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
    """Record what `totalcycles` reads now, after `command` left it stale, for the next run."""
    cpu, reading = _counter_now(ses)
    STATE.stale_counter = StaleCounter(cpu, reading, command)


def _counter_now(ses: gs.Session) -> tuple[str | None, int | None]:
    """The visible cpu and its `totalcycles`, each None when the console cannot say."""
    if ses.broken:
        return None, None
    try:
        return cpus.visible_cpu(ses), read.print_values(ses, ["totalcycles"])[0]
    except gs.SessionError:
        return None, None


def stale_cycles_why(cpu: str | None, reading: int | None) -> str | None:
    """Why a run's `totalcycles` baseline, `reading` on `cpu`, is still the count a command
    left stale (`mark_stale_counter`), else None: it reads what the counter read right after
    that command, on that cpu. Unknown is taken as stale (the counter unread then, or another
    cpu visible now, whose own nothing recorded). It consumes the mark, since the run that asks
    executes."""
    mark, STATE.stale_counter = STATE.stale_counter, None
    if mark is None:
        return None
    stale = mark.reading is None or mark.cpu != cpu or mark.reading == reading
    return cycles_why(mark.command) if stale else None
