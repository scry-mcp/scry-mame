"""Section T of the live matrix: what a capture row says about WHEN, on 1942, a stock board of two
Z80s and one screen. The main cpu writes the sound latch in the handler its scanline PROM calls
near line 109, and the sound cpu reads that latch.

THE LINE'S REFERENCE IS MAME'S OWN `vpos()`, the debugger's `beamy`: read at a breakpoint on the
instruction that writes the latch and again one `step` later, the two bracket the write, and the
capture's row of that write must carry a line inside the bracket, and the line itself where the
bracket is one line. Its control is the same capture with the line derived one line ahead, which
must miss wherever the bracket is one line. THE ORDER'S
known answer is the latch: a capture of its reads on the sound cpu, one clock with the writes,
must find every read returning the value of the last write stamped before it.

`live_matrix.py` registers this section; run alone, it is the same machinery over it only:

    MAME_STOCK_BINARY=... MAME_TEST_ROMS=... uv run python tests/live/matrix_stamps.py
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from live_harness import (
    Board,
    blocked,
    boards_cover,
    call,
    cell,
    free_boards_missing,
    free_boot,
    invalid,
    ok,
    run_boards,
    run_sections,
    said,
    section,
    zips_missing,
)

import mame_capture as mcapture  # isort: skip -- found through the path the harness sets

T_TITLE = "a capture row's line and time, and a capture of reads on a second cpu"
LATCH_W, LATCH_R, AUDIO = "0xc800", "0x6000", ":audiocpu"
# How many writes of the latch a cell stops at: each is a line read twice, by `beamy` and by a row.
STOPS = 4
T_CELLS = [
    "1942: the capture's row of a sound-latch write carries a line inside the bracket the "
    "debugger's beamy reads before and after the writing instruction, at every stop",
    "1942: a capture of the latch's reads on the sound cpu, ordered against the writes by time, "
    "finds every read returning the value of the last write stamped before it",
    "1942: the same capture with its line derived one line ahead misses beamy wherever the "
    "bracket is one line: the reference can fail",
]


def _rows(ref: str) -> list[mcapture.Row]:
    """The rows of the capture held under `ref`, from the file `declaration_list(kind="watch")`
    names."""
    listed = call("declaration_list", kind="watch").get("watches", [])
    path = next((w.get("rows_path") for w in listed if w.get("ref") == ref), None)
    return list(mcapture.rows(Path(str(path)))) if path else []


def _write_capture(ref: str) -> dict[str, Any]:
    return call("watch_add", ref=ref, mode="capture", length=1, trigger=LATCH_W)


def beamy() -> int | None:
    said_ = call("debug", command="print beamy")
    return int(str(said_.get("output")).split()[0], 16) if ok(said_) else None


def lines_at_stops(line_of: Callable[[Any, int], int | None],
                   writer: str) -> list[tuple[int | None, int | None, int | None]]:
    """At each of `STOPS` stops on the instruction at `writer`: `beamy` before it runs and after
    one `step`, which bracket the write it makes, and `line_of(frame, writer)`, the line the row
    of that write carries (that writer's newest row in that frame), None where any is missing."""
    out: list[tuple[int | None, int | None, int | None]] = []
    for _ in range(STOPS):
        hit = call("run_for", frames=2, seconds=10.0)
        if hit.get("verdict") != "OTHER_STOP" or hit.get("pc") != writer:
            out.append((None, None, None))
            continue
        before = beamy()
        stepped = call("step")
        after = beamy() if ok(stepped) else None
        out.append((before, after, line_of(hit.get("frame"), int(writer, 16))))
    return out


def _capture_line(ref: str) -> Callable[[Any, int], int | None]:
    """The line of the capture under `ref`'s newest row from `pc` in `frame`."""
    def line_of(frame: Any, pc: int) -> int | None:
        mine = [r for r in _rows(ref) if r.frame == frame and r.pc == pc]
        return mine[-1].line if mine else None
    return line_of


def brackets(seen: list[tuple[int | None, int | None, int | None]]) -> bool:
    """Every row line inside its bracket, and equal to it where the bracket is one line."""
    return all(b is not None and a is not None and r is not None and r in (b, a)
               for b, a, r in seen) and any(b == a for b, a, _ in seen)


def _t_1942(t: list[str]) -> None:
    free_boot("1942", ["srb-03.m3"], "0x0")
    # IN PLAY, the latch carries sound commands that change; in attract it holds one value, and
    # an order judged over one value cannot fail.
    call("run_for", frames=120, seconds=10.0)
    for field in ("Coin 1", "1 Player Start"):
        call("input", port=":SYSTEM", field=field, frames=4, seconds=10.0)
        call("run_for", frames=30, seconds=10.0)
    writes = _write_capture("0xe000")
    reads = call("watch_add", ref=LATCH_R, mode="capture", trigger=LATCH_R, trigger_type="r",
                 cpu=AUDIO)
    # WHO WRITES THE LATCH is a change watch's answer; its own stop is not at the write's
    # instant, so the bracket is taken on a breakpoint at the writer instead.
    call("watch_add", ref=LATCH_W, mode="change", length=1)
    hit = call("run_for", frames=2, seconds=10.0)
    call("declaration_clear", kind="watch", ref=LATCH_W)
    writer = str((hit.get("watch_hit") or {}).get("writer_pc", ""))
    armed = call("breakpoint_at", ref=writer, by="address") if writer else {}
    seen = lines_at_stops(_capture_line("0xe000"), writer)
    cell(t[0], ok(writes) and ok(armed) and brackets(seen),
         f"writer {writer}; (beamy before, beamy after, row line) at {STOPS} stops: {seen}")
    call("declaration_clear", kind="breakpoint", all=True)
    ran = call("run_for", frames=120, seconds=10.0)
    w_rows, r_rows = _rows("0xe000"), _rows(LATCH_R)
    values = {r.data & 0xFF for r in w_rows}
    if not (ok(reads) and ok(ran) and r_rows and len(values) > 1):
        blocked(t[1], f"reads {len(r_rows)} ({said(reads, 80)}), write values {sorted(values)}: "
                      "an order over one value cannot fail")
    else:
        stamped = sorted((r.time_attoseconds, r.data & 0xFF) for r in w_rows)
        wrong, judged = [], 0
        for r in r_rows:
            before = [v for at, v in stamped if at <= r.time_attoseconds]
            if not before:
                continue
            judged += 1
            if before[-1] != r.data & 0xFF:
                wrong.append((r.n, r.time_attoseconds, r.data & 0xFF, before[-1]))
        cell(t[1], judged > 0 and not wrong,
             f"{judged} reads judged against {len(stamped)} writes of {len(values)} values; "
             f"wrong {wrong[:3]}")
    call("declaration_clear", kind="watch", ref="0xe000")
    # THE CONTROL: the derivation one line ahead, installed under another ref, at the same kind of
    # stop, must disagree with `beamy` every time.
    exact = mcapture.BEAM_LINE_LUA
    ahead, moved = re.subn(r"return math\.floor\(", "return 1 + math.floor(", exact)
    if moved != 1:
        invalid("the control's derivation did not move: BEAM_LINE_LUA has no `return math.floor(`")
    mcapture.BEAM_LINE_LUA = ahead
    try:
        ahead_cap = _write_capture("0xe001")
    finally:
        mcapture.BEAM_LINE_LUA = exact
    call("breakpoint_at", ref=writer, by="address")
    ahead_seen = lines_at_stops(_capture_line("0xe001"), writer)
    one_line = [(b, r) for b, a, r in ahead_seen if b is not None and b == a and r is not None]
    cell(t[2], ok(ahead_cap) and bool(one_line) and all(r != b for b, r in one_line),
         f"(beamy before, beamy after, ahead row line) at {STOPS} stops: {ahead_seen}")
    call("close")


def _missing() -> str:
    return free_boards_missing() or zips_missing("1942")


T_BOARDS = (Board(_t_1942, (0, 1, 2), _missing),)
boards_cover("section T", T_CELLS, T_BOARDS)


def register_t() -> None:
    """Register section T with the matrix: after every section registered before it."""
    section("T", T_TITLE, T_CELLS)(lambda: run_boards(T_CELLS, T_BOARDS))


if __name__ == "__main__":
    register_t()
    run_sections("SECTION T")
