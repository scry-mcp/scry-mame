"""Section V of the live matrix: a control on the instruction a frame stop lands on, on
m68k-dual-alt, where that instruction is the first of the handler the vblank interrupt enters.

Two arms over one run by frames, in `run_frames`' legs, whose stops between them the server
counts as it counts any (`breakpoints.count_landing` says why the arms differ). The server's:
a control there counts as many hits as a control on the next instruction. MAME's own: a logging
breakpoint there, typed through `debug`, logs fewer lines than one on the next instruction. The
day MAME evaluates that instruction the second arm goes red, and the server's correction is the
thing to revisit. m68k-dual-alt runs on its copies on the bench, BLOCKED naming the file when they
are absent or off their pins.

`live_matrix.py` registers this section; run alone, it is the same machinery over it only:

    uv run python tests/live/matrix_landing.py
"""

from typing import Any

from bench_boards import M68K_DUAL_ALT_BOOT, board_missing
from live_harness import (
    Board,
    boards_cover,
    call,
    cell,
    ok,
    require_booted,
    run_boards,
    run_frames,
    said,
    section,
)

HANDLER = "0x564"               # the target of vectors 28 and 29, two autovectors
INSIDE = "0x568"                # the handler's second instruction
RUN_FRAMES = 600
AT_HANDLER, AT_INSIDE = "MCPH", "MCPI"      # each logging breakpoint's own word in error.log

V_TITLE = "a control on the instruction a stop lands on"
V = [
    "over a run by frames on m68k-dual-alt, a control on the handler a frame stop lands on counts "
    "as many hits as a control on the next instruction, while MAME's own logging breakpoint "
    "there logs fewer lines than one on the next instruction",
]


def _logged(word: str) -> Any:
    return call("log", pattern=f"^{word} ", channel="emulator", limit=1).get("lines_total")


def _v_m68k_dual_alt(_cells: list[str]) -> None:
    require_booted("m68k-dual-alt", call("start", **M68K_DUAL_ALT_BOOT, boot_seconds=25.0))
    controls = [call("breakpoint_at", ref=ref, role="control") for ref in (HANDLER, INSIDE)]
    raw = [call("debug", command=f'bp {ref[2:]},1,{{logerror "{word} %d\\n",frame ; g}}')
           for ref, word in ((HANDLER, AT_HANDLER), (INSIDE, AT_INSIDE))]
    run = run_frames(RUN_FRAMES)
    rows = {b.get("ref"): b for b in call("breakpoint_list").get("breakpoints") or []}
    first, inside = (rows.get(ref, {}).get("hits_since_armed") for ref in (HANDLER, INSIDE))
    logged_first, logged_inside = _logged(AT_HANDLER), _logged(AT_INSIDE)
    counts = (first, inside, logged_first, logged_inside)
    cell(V[0], all(ok(r) for r in (*controls, *raw)) and ok(run)
         and run.get("verdict") == "ELAPSED" and all(isinstance(c, int) for c in counts)
         and 0 < logged_first < logged_inside == first == inside,
         f"run {run.get('verdict')} {said(run, 60)}; controls at {HANDLER} {first}, at {INSIDE} "
         f"{inside}; logged at {HANDLER} {logged_first}, at {INSIDE} {logged_inside}")


V_BOARDS = (Board(_v_m68k_dual_alt, (0,), lambda: board_missing("m68k-dual-alt")),)
boards_cover("V_BOARDS", V, V_BOARDS)


def register_v() -> None:
    """Register section V with the matrix: after every section registered before it."""
    section("V", V_TITLE, V)(lambda: run_boards(V, V_BOARDS))


if __name__ == "__main__":
    from live_harness import run_sections
    register_v()
    run_sections("SECTION V")
