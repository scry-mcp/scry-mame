"""Section W of the live matrix: a change watch that stops the machine in a run by frames on a
landing that also ticked the frame counter, so only the console's `Stopped at watchpoint` line
says the landing is a stop (`mame_advance._run_for_frames` says why the counter cannot). Gridlee's
START takes a credit in two writes inside such a frame once four coins went in, on the path
`_four_credits` replays from cold.

`live_matrix.py` registers this section; run alone, it is the same machinery over it only:

    uv run python tests/live/matrix_watch_tick.py
"""

from typing import Any

from live_harness import (
    Board,
    boards_cover,
    call,
    cell,
    free_boards_missing,
    free_boot,
    ok,
    run_boards,
    said,
    section,
)

CREDITS_BIN, CREDITS_BCD = "0x42b", "0x42c"
COIN: dict[str, Any] = {"port": ":IN1", "field": "Coin 1", "frames": 4, "seconds": 10.0}
START: dict[str, Any] = {"port": ":IN1", "field": "1 Player Start", "frames": 4, "seconds": 10.0}

W_TITLE = "a watch that stops the machine on a landing that ticked the counter"
W = [
    "gridlee: at four credits with both credit watches armed, the START's input stops on 0x42b, "
    "written by 0xd676, at 0xd679, on a landing that ticked the counter",
    "gridlee: the next run by one frame stops on 0x42c, written by 0xd67f, at 0xd682",
    "gridlee: at four credits with the 0x42c watch alone, the START stops at 0xd682 on a landing "
    "that ticked the counter, and a 16-instruction history from there reaches 0xd676",
]


def _stopped(r: dict[str, Any], addr: str, writer: int, pc: int) -> bool:
    hit = r.get("watch_hit")
    return (ok(r) and r.get("verdict") == "OTHER_STOP" and isinstance(hit, dict)
            and hit.get("addr") == f"0x{int(addr, 16):08x}"
            and hit.get("writer_pc") == f"0x{writer:08x}" and r.get("pc") == f"0x{pc:08x}")


def _ticked(r: dict[str, Any]) -> bool:
    """Whether the stop came on a landing that moved the counter: the path the console's line
    is the only tell of, which a START landing in the aligning tick would not exercise."""
    before, after = r.get("frame_before"), r.get("frame_after")
    return isinstance(before, int) and isinstance(after, int) and after == before + 1


def _four_credits() -> str:
    """A cold gridlee taken to four credits, both credit watches armed: three
    coins two seconds apart, the watches, a fourth coin and the coin routine's two stops, then
    half a second more, which leaves the START to land in the frame that ticks. Returns the two
    credit bytes read there, `0404` when the path went as it should."""
    free_boot("gridlee", ["gridfnla.bin"], "0xa000")
    call("run_for", milliseconds=5000, seconds=10.0)
    for _ in range(3):
        call("input", **COIN)
        call("run_for", milliseconds=2000, seconds=10.0)
    for ref in (CREDITS_BIN, CREDITS_BCD):
        call("watch_add", ref=ref, mode="change", fmt="u8")
    call("input", **COIN)
    for _ in range(3):
        call("run_for", milliseconds=500, seconds=10.0)
    return str(call("read_memory", ref=CREDITS_BIN, length=2).get("hex"))


def _w_gridlee(t: list[str]) -> None:
    credits = _four_credits()
    r = call("input", **START)
    cell(t[0], credits == "0404" and _stopped(r, CREDITS_BIN, 0xD676, 0xD679) and _ticked(r),
         f"credits {credits}; {said(r)}")
    r = call("run_for", frames=1, seconds=10.0)
    cell(t[1], _stopped(r, CREDITS_BCD, 0xD67F, 0xD682), said(r))
    call("close")
    # A SECOND COLD RUN rather than a saved state: a START taken after `state_write(method="load")`
    # lands inside
    # the aligning tick, where the counter does not move, so it would not exercise the line.
    credits = _four_credits()
    call("declaration_clear", kind="watch", ref=CREDITS_BIN)
    r = call("input", **START)
    trail = call("history", limit=16)
    lines = trail.get("lines") or []
    cell(t[2], credits == "0404" and _stopped(r, CREDITS_BCD, 0xD67F, 0xD682) and _ticked(r)
         and ok(trail) and any(str(ln).upper().startswith("D676:") for ln in lines),
         f"credits {credits}; {said(r)}; history {lines[:1]}..{lines[-1:]}")
    call("close")


W_BOARDS = (Board(_w_gridlee, (0, 1, 2), free_boards_missing),)
boards_cover("W_BOARDS", W, W_BOARDS)


def register_w() -> None:
    """Register section W with the matrix: after every section registered before it."""
    section("W", W_TITLE, W)(lambda: run_boards(W, W_BOARDS))


if __name__ == "__main__":
    from live_harness import run_sections
    register_w()
    run_sections("SECTION W")
