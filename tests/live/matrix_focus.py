"""Section X of the live matrix: whether any MAME this run launched came to the front, sampled
from outside the run (`scry_core.focus_watch`) for its whole length.

It is registered twice, FIRST and LAST. First, the control, in the same harness the verdict is
taken in: one quick start forced in front, which the watch must see in front, and one behind,
which it must not; a watch that cannot see the first clears nothing. Then the watch keeps
sampling while every other section runs, and last its samples since the control are judged
against the names of the binaries this run launches. A control that did not hold, a run too
short, or a watch that could not sample leaves the verdict BLOCKED, never green and never a
server's FAIL. Judged by process name: another MAME of the same binary name in front counts.
The control's front start takes the owner's focus for a few seconds: a run that includes this
section is announced.

    uv run python tests/live/matrix_focus.py      # the control alone; its verdict is BLOCKED
"""

from __future__ import annotations

import contextlib
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
from scry_core import focus_watch

X_TITLE = "the focus gate: the control, then the watch runs beside every section"
X_CONTROL = [
    "the control: a start forced in front is seen in front",
    "the control: a start behind is never in front",
]
X_VERDICT_TITLE = "the focus gate: what the watch saw while the sections ran"
X_VERDICT = ["no MAME this run launched came to the front while the sections ran"]
HOLD_S = 4.0
#: Shorter than this, a judged window says too little about a run to be its verdict.
MIN_WINDOW_MS = 60_000
#: The boards of the bench whose binaries a section may launch.
BENCH_BOARDS = ("m68k-dual", "m68k-dual-alt", "v30", "v30-alt")

_WATCH: list[focus_watch.FocusWatch] = []
_SINCE: list[int] = []


def _names() -> set[str]:
    """The process names of the binaries this run launches; the bench's are read off its
    manifest, and a board the bench does not hold launches nothing."""
    binaries = [FREE_BINARY, MULTICPU_BINARY]
    for board in BENCH_BOARDS:
        with contextlib.suppress(Exception):
            binaries.append(bench_boards.board_path(board, "binary"))
    return {Path(b).name for b in binaries if b}


def _hold(background: bool) -> tuple[int, int]:
    """One quick circus start, launched as asked, held for `HOLD_S`, closed: its window, ms."""
    began = int(time.time() * 1000)
    circus_boot(background=background)
    call("resume")
    time.sleep(HOLD_S)
    ensure_closed()
    return began, int(time.time() * 1000)


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
    names = _names()
    front, behind = _hold(background=False), _hold(background=True)
    seen = focus_watch.judge(watch.samples, names, start_ms=front[0], end_ms=front[1])
    cell(X_CONTROL[0], seen.status == "TOOK_FOCUS", seen.reason)
    clean = focus_watch.judge(watch.samples, names, start_ms=behind[0], end_ms=behind[1])
    cell(X_CONTROL[1], clean.status == "CLEAN", clean.reason)
    # A WATCH THAT DID NOT HOLD ITS CONTROL CLEARS NOTHING: the verdict is judged only after both.
    if seen.status == "TOOK_FOCUS" and clean.status == "CLEAN":
        _SINCE.append(behind[1])


def _verdict() -> None:
    if not _WATCH:
        blocked(X_VERDICT[0], "the control section never started the watch")
        return
    watch = _WATCH.pop()
    watch.__exit__(None, None, None)
    if not _SINCE:
        blocked(X_VERDICT[0], f"the control did not hold, so the watch clears nothing; record "
                              f"{watch.path}")
        return
    end = int(time.time() * 1000)
    if end - _SINCE[0] < MIN_WINDOW_MS:
        blocked(X_VERDICT[0], f"the sections ran for {end - _SINCE[0]} ms, too little to judge; "
                              f"record {watch.path}")
        return
    v = focus_watch.judge(watch.samples, _names(), start_ms=_SINCE[0], end_ms=end)
    if v.status == "INVALID":
        # THE INSTRUMENT, not the server: a sample it could not take, or a stretch unsampled.
        blocked(X_VERDICT[0], f"the watch cannot judge the run: {v.reason}; record {watch.path}")
        return
    cell(X_VERDICT[0], v.status == "CLEAN", f"{v.status}: {v.reason}; record {watch.path}")


def register_x_control() -> None:
    """Register the control with the matrix: BEFORE every other section, so the watch spans them."""
    section("X", X_TITLE, X_CONTROL)(_control)


def register_x_verdict() -> None:
    """Register the verdict with the matrix: AFTER every other section."""
    section("X", X_VERDICT_TITLE, X_VERDICT)(_verdict)


if __name__ == "__main__":
    from live_harness import run_sections
    register_x_control()
    register_x_verdict()
    run_sections("SECTION X")
