"""THE PROGRESS LINE OF A BOUNDED WAIT, and the one rule every call's notifications keep: never
going backwards. A module waits and reports through the callback the server hands in; it knows
nothing of the protocol's `Context`, and a test hands in a list.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

# A BOUNDED WAIT REPORTS PROGRESS WITH A MESSAGE. The arguments are the protocol's own
# (`progress`, `total`, `message`); `total` is None for a wait measured in time, because a bar
# filling towards the bound reads as progress towards failure.
Progress = Callable[[float, float | None, str], None]


# How often a bounded wait reports: a second, which is what a person watching the line reads.
PROGRESS_EVERY_S = 1.0


def no_progress(progress: float, total: float | None, message: str) -> None:
    """The callback of a call with no client to paint for (a test, a direct call)."""


class Ticker:
    """The progress line of ONE bounded wait: the clock it started on, its bound, and the
    report every `PROGRESS_EVERY_S` while the loop asks, of the time elapsed (`tick`) or of the
    work done when the work has a size (`report`, then `finish` where it ends). The arithmetic
    lives here once, while the WHERE stays each loop's (`run_to` ticks before its poll, on
    purpose): a copy per loop drifts in where the tick sits and nothing compares them. The line
    is formatted only when a report is due."""

    def __init__(self, seconds: float, progress: Progress) -> None:
        self.began = time.monotonic()
        self.now = self.began
        self.deadline = self.began + seconds
        self._progress = progress
        self._next = self.began + PROGRESS_EVERY_S

    def elapsed(self, digits: int = 3) -> float:
        return round(self.seconds(), digits)

    def seconds(self) -> float:
        """The span since the wait began, unrounded: a reply's field rounds it once
        (`st.spent_s`), where rounding an already rounded `elapsed` would round twice."""
        return time.monotonic() - self.began

    def expired(self) -> bool:
        """ONE clock read per iteration, at the loop's head: `left` and `tick` reuse it, so a
        tick is judged at most one poll late."""
        self.now = time.monotonic()
        return self.now >= self.deadline

    def left(self) -> float:
        return max(0.0, self.deadline - self.now)

    def tick(self, template: str, **fields: Any) -> None:
        """Report the time elapsed, with no total, when a report is due: `template` is
        formatted with `elapsed` and `fields` only then. A template and its fields, not a
        closure: a closure over a loop variable needs a default-argument dance to bind it, and
        the tools that measure this package saw its body as never run."""
        self._send_if_due(None, None, template, fields)

    def report(self, done: float, total: float, template: str, /, **fields: Any) -> None:
        """Report work done of `total`, clamped into [0, total], when a report is due, on the
        period `tick` keeps. Positional-only, so no field a template names can collide."""
        self._send_if_due(min(max(done, 0), total), total, template, fields)

    def finish(self, total: float, template: str, /, **fields: Any) -> None:
        """The work is over: report `total` of `total` at once, so the bar ends where the work
        did, whatever the period held back before it."""
        self._send(total, total, template, fields)

    def _send_if_due(self, done: float | None, total: float | None, template: str,
                     fields: dict[str, Any]) -> None:
        if self.now >= self._next:
            self._next = self.now + PROGRESS_EVERY_S
            self._send(done, total, template, fields)

    def _send(self, done: float | None, total: float | None, template: str,
              fields: dict[str, Any]) -> None:
        elapsed = self.now - self.began
        self._progress(elapsed if done is None else done, total,
                       template.format(elapsed=elapsed, **fields))


class RebasedProgress:
    """The progress of ONE call, never going backwards, which the protocol requires of every
    notification in a request. A call may hold several waits that each count from zero (a retry
    of `start`, the waits a `perform` makes between its steps, the Lua tools' chained waits): a
    raw value below the previous raw one begins a new segment, based at the last value sent, so
    the client sees one rising line. A value not above the last one sent is dropped with its
    message rather than sent out of order."""

    def __init__(self, report: Progress) -> None:
        self._report = report
        self._last_raw: float | None = None
        self._base = 0.0
        self._sent: float | None = None

    def __call__(self, progress: float, total: float | None, message: str) -> None:
        if self._last_raw is not None and progress < self._last_raw:
            self._base = self._sent or 0.0
        self._last_raw = progress
        value = self._base + progress
        if self._sent is not None and value <= self._sent:
            return
        self._sent = value
        self._report(value, None if total is None else self._base + total, message)
