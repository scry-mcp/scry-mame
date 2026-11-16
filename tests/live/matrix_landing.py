"""Section V of the live matrix: a control on the handler instruction a frame stop lands on.

Run alone: `uv run python tests/live/matrix_landing.py`
"""

from typing import Any

from bench_boards import board_missing
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

HANDLER = "0x564"               # vectors 28 and 29 share this target
INSIDE = "0x568"
RUN_FRAMES = 600
SEEK_FRAMES = 20                # single frames run until a stop lands on the handler
AT_HANDLER, AT_INSIDE = "MCPH", "MCPI"

V_TITLE = "a control on the instruction a stop lands on"
V = [
    "over a run by frames on m68k-dual-alt that ends on the handler a frame stop lands on, a "
    "control there counts the hits MAME's own logging breakpoint there logs, one more than a "
    "control on the next instruction, the landing the run ends on: the landing is evaluated by "
    "MAME (mamedev/mame#16435), not added by the server",
]


def _logged(word: str) -> Any:
    return call("log", pattern=f"^{word} ", channel="emulator", limit=1).get("lines_total")


def _lands(pc: Any) -> bool:
    return isinstance(pc, str) and int(pc, 16) == int(HANDLER, 16)


def _v_m68k_dual_alt(_cells: list[str]) -> None:
    require_booted("m68k-dual-alt", call("start", profile="m68k-dual-alt"))
    controls = [call("breakpoint_at", ref=ref, role="control") for ref in (HANDLER, INSIDE)]
    raw = [call("debug", command=f'bp {ref[2:]},1,{{logerror "{word} %d\\n",frame ; g}}')
           for ref, word in ((HANDLER, AT_HANDLER), (INSIDE, AT_INSIDE))]
    run = run_frames(RUN_FRAMES)
    # Where a frame stop lands moves with the board's timing, so the run goes on a frame at a
    # time until one lands on the handler: that landing is evaluated, its next instruction not
    # yet run, and a MAME that skipped it would count both the same.
    for _ in range(SEEK_FRAMES):
        if not ok(run) or _lands(run.get("pc")):
            break
        run = run_frames(1)
    rows = {b.get("ref"): b for b in call("declaration_list",
                                          kind="breakpoint").get("breakpoints") or []}
    first, inside = (rows.get(ref, {}).get("hits_since_armed") for ref in (HANDLER, INSIDE))
    logged_first, logged_inside = _logged(AT_HANDLER), _logged(AT_INSIDE)
    counts = (first, inside, logged_first, logged_inside)
    end = run.get("pc")
    cell(V[0], all(ok(r) for r in (*controls, *raw)) and ok(run)
         and run.get("verdict") == "ELAPSED" and all(isinstance(c, int) for c in counts)
         and _lands(end) and first == logged_first and inside == logged_inside and inside > 0
         and first == inside + 1,
         f"run {run.get('verdict')} {said(run, 60)}, ends at {end}; controls at {HANDLER} "
         f"{first}, at {INSIDE} {inside}; logged at {HANDLER} {logged_first}, at {INSIDE} "
         f"{logged_inside}")


V_BOARDS = (Board(_v_m68k_dual_alt, (0,), lambda: board_missing("m68k-dual-alt")),)
boards_cover("V_BOARDS", V, V_BOARDS)


def register_v() -> None:
    """Register section V with the matrix."""
    section("V", V_TITLE, V)(lambda: run_boards(V, V_BOARDS))


if __name__ == "__main__":
    from live_harness import run_sections
    register_v()
    run_sections("SECTION V")
