"""Section U of the live matrix: what a `palette_log` row says about WHEN, on radendur, whose
RAMDAC the project's manifest declares and whose game uploads its palette a frame at a time.

THE LINE'S REFERENCE IS MAME'S OWN `vpos()`, the debugger's `beamy`, as section T takes it for a
capture row: read at a breakpoint on the instruction that writes the RAMDAC's data port and again
one `step` later, the two bracket the write, and the log's row of that write must carry a line
inside the bracket, and the line itself where the bracket is one line. Its control is the same
log armed with the line derived one line ahead, which must miss wherever the bracket is one line.
THE ORDER'S known answer is the log itself: one tap, one clock, so the time a row carries rises
with the row's number.

`live_matrix.py` registers this section; run alone, it is the same machinery over it only:

    uv run python tests/live/matrix_palette_stamps.py
"""

from __future__ import annotations

import collections
import re
from pathlib import Path
from typing import Any

from bench_boards import MANIFEST, radendur_missing
from live_harness import (
    Board,
    blocked,
    boards_cover,
    boot,
    call,
    cell,
    invalid,
    ok,
    run_boards,
    run_sections,
    said,
    section,
)
from matrix_stamps import brackets, lines_at_stops

import mame_capture as mcapture  # isort: skip -- found through the path the harness sets
import mame_ramdac as mramdac  # isort: skip

U_TITLE = "a palette_log row's line and time, on radendur's RAMDAC"
RAMDAC = "ramdac"
U_CELLS = [
    "radendur: the log's row of a palette data write carries a line inside the bracket the "
    "debugger's beamy reads before and after the writing instruction, at every stop",
    "radendur: the log's rows carry their times in the order the tap wrote them",
    "radendur: the same log with its line derived one line ahead misses beamy wherever the "
    "bracket is one line: the reference can fail",
]


def _rows() -> list[mramdac.Row]:
    """The log's rows, from the file its read names."""
    read = call("palette_log", palette_port=RAMDAC, limit=1)
    path = read.get("rows_path")
    return list(mramdac.rows(Path(str(path)))) if path else []


def _line_of(frame: Any, pc: int) -> int | None:
    """The line of the log's newest data row from `pc` in `frame`."""
    mine = [r for r in _rows() if r.kind == "d" and r.frame == frame and r.pc == pc]
    return mine[-1].line if mine else None


def _u_radendur(t: list[str]) -> None:
    boot()
    call("gfx_load", path=MANIFEST)
    # The upload runs once the game is past its boot, as section F finds it.
    for _ in range(9):
        call("run_for", frames=100, seconds=10.0)
    armed = call("palette_log", palette_port=RAMDAC, arm=True)
    call("run_for", frames=2, seconds=10.0)
    rows = _rows()
    # THE WRITER WHOSE WRITES SPREAD OVER THE MOST LINES, so the bracket is taken where the
    # beam moves (a writer confined to the vblank answers one line at every stop); its count of
    # writes breaks a tie. Spelled as a reply spells a pc, which the stop's `pc` is compared with.
    lines: dict[int, set[int | None]] = collections.defaultdict(set)
    for r in rows:
        if r.kind == "d":
            lines[r.pc].add(r.line)
    counts = collections.Counter(r.pc for r in rows if r.kind == "d")
    best = max(lines, key=lambda pc: (len(lines[pc]), counts[pc]), default=None)
    if best is None:
        # The game wrote no palette in the frames armed: a fact about its scene, which says
        # nothing of the log.
        for label in t:
            blocked(label, f"no data write logged in two frames ({said(armed, 80)})")
        call("palette_log", palette_port=RAMDAC, clear=True)
        call("close")
        return
    writer = f"0x{best:08x}"
    bp = call("breakpoint_at", ref=writer, by="address")
    seen = lines_at_stops(_line_of, writer) if ok(bp) else []
    cell(t[0], ok(armed) and ok(bp) and brackets(seen),
         f"writer {writer} over lines {sorted(x for x in lines[best] if x)[:8]}; "
         f"(beamy before, beamy after, row line) at each stop: {seen}")
    call("breakpoint_clear", all=True)
    call("run_for", frames=2, seconds=10.0)
    times = [r.time_attoseconds for r in sorted(_rows(), key=lambda r: r.n)
             if r.time_attoseconds is not None]
    # Two writes of one instruction can share a reading of the clock, so the order is `>=`; no
    # state load is made here, which is the one row whose time goes back.
    cell(t[1], len(times) > 1 and all(b >= a for a, b in zip(times, times[1:], strict=False)),
         f"{len(times)} stamped rows of {len(rows)}; first {times[:2]}")
    call("palette_log", palette_port=RAMDAC, clear=True)
    # THE CONTROL: the derivation one line ahead, armed in the log's place, at the same kind of
    # stop, must disagree with `beamy` every time the bracket is one line.
    exact = mcapture.BEAM_LINE_LUA
    ahead, moved = re.subn(r"return math\.floor\(", "return 1 + math.floor(", exact)
    if moved != 1:
        invalid("the control's derivation did not move: BEAM_LINE_LUA has no `return math.floor(`")
    mcapture.BEAM_LINE_LUA = ahead
    try:
        ahead_log = call("palette_log", palette_port=RAMDAC, arm=True)
    finally:
        mcapture.BEAM_LINE_LUA = exact
    call("run_for", frames=2, seconds=10.0)
    call("breakpoint_at", ref=writer, by="address")
    ahead_seen = lines_at_stops(_line_of, writer)
    one_line = [(b, r) for b, a, r in ahead_seen if b is not None and b == a and r is not None]
    cell(t[2], ok(ahead_log) and bool(one_line) and all(r != b for b, r in one_line),
         f"(beamy before, beamy after, ahead row line) at each stop: {ahead_seen}; "
         f"{said(ahead_log, 60)}")
    call("breakpoint_clear", all=True)
    call("palette_log", palette_port=RAMDAC, clear=True)
    call("close")


U_BOARDS = (Board(_u_radendur, (0, 1, 2), radendur_missing),)
boards_cover("section U", U_CELLS, U_BOARDS)


def register_u() -> None:
    """Register section U with the matrix: after every section registered before it."""
    section("U", U_TITLE, U_CELLS)(lambda: run_boards(U_CELLS, U_BOARDS))


if __name__ == "__main__":
    register_u()
    run_sections("SECTION U")
