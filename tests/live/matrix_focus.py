"""Section X of the live matrix: whether any MAME this run launched came to the front, or any
display's Space moved, sampled from outside the run (`scry_core.focus_watch`) for its whole
length.

It is registered twice, FIRST and LAST. First, the control, in the same harness the verdict is
taken in: one quick start forced in front, which the watch must see in front, one behind, which it
must not, and the owner's Space moved and put back on purpose, which it must see move; a watch
that does not hold all three clears nothing. Then the watch keeps
sampling while every other section runs, and last its samples since the control are judged
against the names of the binaries this run launches. A control that did not hold, a run too
short, or a watch that could not sample leaves the verdict BLOCKED, never green and never a
server's FAIL. Judged by process name: another MAME of the same binary name in front counts.
The control's front start takes the owner's focus for a few seconds and its Space control moves
the owner's Space and back: a run that includes this section is announced.

    uv run python tests/live/matrix_focus.py      # the control alone; its verdict is BLOCKED
"""

from __future__ import annotations

import time
from pathlib import Path

import bench_boards
from live_harness import (
    FREE_BINARY,
    MULTICPU_BINARY,
    blocked,
    call,
    cell,
    circus_boot,
    ensure_closed,
    free_boards_missing,
    fresh,
    section,
)
from scry_core import focus_gate, focus_watch

X_TITLE = "the focus gate: the control, then the watch runs beside every section"
X_CONTROL = [
    "the control: a start forced in front is seen in front",
    "the control: a start behind is never in front",
    "the control: a Space moved on purpose is seen moved",
]
X_VERDICT_TITLE = "the focus gate: what the watch saw while the sections ran"
X_VERDICT = ["no MAME this run launched came to the front and no Space moved while the sections "
             "ran"]
#: The boards of the bench whose binaries a section may launch.
BENCH_BOARDS = ("m68k-dual", "m68k-dual-alt", "v30", "v30-alt")

_WATCH: list[focus_watch.FocusWatch] = []
_SINCE: list[int] = []


def _names() -> set[str]:
    """The process names of the binaries this run launches; the bench's are read off its
    manifest, and a board the bench does not hold launches nothing."""
    binaries = [FREE_BINARY, MULTICPU_BINARY]
    binaries += [bench_boards.board_path(board, "binary") for board in BENCH_BOARDS
                 if not bench_boards.board_missing(board)]
    return {Path(b).name for b in binaries if b}


def _hold(background: bool) -> tuple[int, int]:
    """One quick circus start, launched as asked, held for `HOLD_S`, closed: its window, ms."""
    began = focus_watch.now_ms()
    circus_boot(background=background)
    call("resume")
    time.sleep(focus_gate.HOLD_S)
    ensure_closed()
    return began, focus_watch.now_ms()


def _control() -> None:
    missing = free_boards_missing()
    tsv = Path(fresh("-focus.tsv"))
    watch = focus_watch.FocusWatch(tsv)
    watch.__enter__()
    _WATCH.append(watch)
    print(f"  focus watch: {tsv}", flush=True)
    if missing:
        for label in X_CONTROL:
            blocked(label, missing)
        return
    c = focus_gate.control(watch, _names(), _hold)
    for label, judged in zip(X_CONTROL, (c.front, c.behind, c.space), strict=True):
        _cell(label, judged)
    if c.since is not None:
        _SINCE.append(c.since)


def _cell(label: str, judged: focus_gate.Judged) -> None:
    """A `focus_gate` outcome as this matrix's cell."""
    if judged.status == "BLOCKED":
        blocked(label, judged.reason)
    else:
        cell(label, judged.status == "OK", judged.reason)


def _verdict() -> None:
    if not _WATCH:
        blocked(X_VERDICT[0], "the control section never started the watch")
        return
    names = _names()                    # before the watch is taken: a raise leaves it to its owner
    _cell(X_VERDICT[0], focus_gate.verdict(_WATCH.pop(), names, _SINCE[0] if _SINCE else None,
                                           focus_watch.now_ms()))


def register_x_control() -> None:
    """Register the control with the matrix: BEFORE every other section, so the watch spans them."""
    section("X", X_TITLE, X_CONTROL, alone=True)(_control)


def register_x_verdict() -> None:
    """Register the verdict with the matrix: AFTER every other section."""
    section("X", X_VERDICT_TITLE, X_VERDICT, alone=True)(_verdict)


if __name__ == "__main__":
    from live_harness import run_sections
    register_x_control()
    register_x_verdict()
    run_sections("SECTION X")
