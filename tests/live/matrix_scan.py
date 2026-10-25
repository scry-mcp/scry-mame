"""Section J of the live matrix: the value scan, against MAME's own cheat engine."""


import re
from pathlib import Path
from typing import Any

from bench_boards import (
    SUB_SYMBOLS,
    SYMBOLS,
    m68k_dual_missing,
)
from live_harness import (
    Board,
    boards_cover,
    boot,
    call,
    cell,
    circus_boot,
    free_boards_missing,
    fresh,
    ok,
    refused,
    run_boards,
    run_frames,
    said,
    section,
)
from matrix_tools_by_state import (  # noqa: E402
    MAIN,
    SUB,
)

# The known answer is the console's `cheatinit`/`cheatnextf` at the same stops, never an address
# written here: the game decides which cells move. m68k-dual's engine omits the write taps, whose
# growth is discounted from the count.

J_CELLS = [
    "m68k-dual: a :maincpu scan narrows the credits and matches the console's cheat engine at "
    "every filter",
    "m68k-dual: a :subcpu scan names its cpu and an `=` after a `>` round closes it",
    "m68k-dual: a second scan start, a filter with none open, a scan on a running machine are "
    "refused",
    "m68k-dual: the scan calls move neither pc, stop_seq nor the emulated time, and alter nothing",
    "circus: the clown's latch narrows the RAM to the console's own survivors at every filter",
]
_FOUND = re.compile(r"(\d+) cheats found")
_INIT = re.compile(r"(\d+) cheat locations initialized for .* '([^']+)' program space")
_LIST_ROW = re.compile(r"Possibility \d+: ([0-9A-F]+) \(([0-9A-F]+)\)")
# Read when the board runs, so a missing file fails that board and not the matrix at import.
_TAPS_FILE = Path(__file__).parents[1] / "fixtures" / "scan" / "m68k-dual-ub-not-admitted.txt"


def _tap_addrs() -> tuple[int, ...]:
    return tuple(int(a, 16) for a in _TAPS_FILE.read_text().split())


def _engine_init(spec: str, tag: str) -> bool:
    """`cheatinit` on `tag`; true only when its line names that tag's program space."""
    m = _INIT.search(str(call("debug", command=f"cheatinit {spec},{tag}").get("output") or ""))
    return m is not None and m.group(2) == tag and int(m.group(1)) > 0


def _engine_rows() -> set[tuple[int, int]]:
    """The engine's survivors as (address, current value), off its own `cheatlist`."""
    path = Path(fresh(".xml"))
    call("debug", command=f"cheatlist {path}")
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {(int(a, 16), int(v, 16)) for a, v in _LIST_ROW.findall(text)}


def _hits(r: dict[str, Any]) -> set[tuple[int, int]]:
    return {(int(h["addr"], 16), int(h["value"], 16)) for h in r.get("hits") or []}


def _same(r: dict[str, Any], count: int, leave_out: tuple[int, ...] = ()) -> bool | None:
    """The tool's survivors against the engine's; None past the list ceiling, so a cell needs a
    True besides."""
    if r.get("truncated"):
        return None
    return {(a, v) for a, v in _hits(r) if a not in leave_out} == _engine_rows() and (
        len([1 for a, _ in _hits(r) if a not in leave_out]) == count)


def _engine(cond: str) -> int:
    """The engine's survivor count after the filter, or -1."""
    found = _FOUND.findall(str(call("debug", command=f"cheatnextf {cond}").get("output") or ""))
    return int(found[-1]) if found else -1


def _where() -> tuple[Any, ...]:
    """`pc`, `stop_seq` and the emulated time; None in any of them means not read."""
    st = call("status")
    return (st.get("pc"), (st.get("last_stop") or {}).get("stop_seq"),
            str(call("debug", command="time").get("output") or "").strip() or None)


def _taps(addrs: tuple[int, ...]) -> list[int]:
    return [int(call("read_memory", ref=f"{a:#x}", length=1).get("hex") or "-1", 16)
            for a in addrs]


def _j_m68k_dual(t: list[str]) -> None:
    boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
    run_frames(600)
    before = _where()
    opened = call("scan", method="start", ref="0x200000", length=0x10000, cpu="maincpu")
    shut = call("scan", method="filter", operator="!")
    after = _where()
    unaltered = not any((x.get("session") or {}).get("altered") for x in (opened, shut))
    cell(t[3], ok(opened) and shut.get("closed") is True and None not in before
         and before == after and unaltered, f"{before} -> {after}; {said(shut)}")
    call("scan", method="start", ref="0x200000", length=0x10000, cpu="maincpu")
    inited = _engine_init("ub,0x200000,0x10000", MAIN)
    taps = _tap_addrs()
    held, rounds = [True] * len(taps), []
    for k in (1, 2):                        # k coins: credits hold k
        call("input", port=":P1", field="Coin 1", seconds=10.0)
        call("run_for", frames=30, seconds=10.0)
        r = call("scan", method="filter", operator="=", value=k)
        held = [h and n == k for h, n in zip(held, _taps(taps), strict=True)]
        engine = _engine(f"equal,0x{k:x}")
        rounds.append((r.get("hits_total"), engine, sum(held), r.get("cpu"), r.get("space"),
                       _same(r, engine, taps)))
    cell(t[0], inited and len(rounds) == 2
         and all(h is not None and h - tap == e and c == MAIN and sp == "program"
                 and same is not False for h, e, tap, c, sp, same in rounds)
         and any(same for *_, same in rounds)
         and 0 < int(rounds[1][0] or 0) < int(rounds[0][0] or 0),
         f"(tool, engine, taps held, cpu, space, sets) {rounds}")
    call("scan", method="clear")
    sub = call("scan", method="start", ref="0x200000", length=0x10000, cpu="subcpu")
    inited = _engine_init("ub,0x200000,0x10000", SUB)
    call("run_for", frames=7, seconds=10.0)
    grew, engine = call("scan", method="filter", operator=">"), _engine("increase")
    same = _same(grew, engine)
    if grew.get("closed"):
        end, engine_end = grew, engine
    else:
        end, engine_end = call("scan", method="filter", operator="="), _engine("equal")
    cell(t[1], inited and sub.get("cpu") == SUB and grew.get("cpu") == SUB and same is True
         and grew.get("hits_total") == engine and end.get("closed") is True and engine_end == 0,
         f"`>` {grew.get('hits_total')} vs engine {engine}; end {said(end)} engine {engine_end}")
    call("scan", method="start", ref="0x200000", length=0x100, cpu="maincpu")
    second = call("scan", method="start", ref="0x200000", length=0x100, cpu="maincpu")
    call("scan", method="clear")
    none = call("scan", method="filter", operator="=")
    call("resume")
    running = call("scan", method="start", ref="0x200000", length=0x100, cpu="maincpu")
    call("stop")
    cell(t[2], refused(second, "needs_call") and refused(none, "needs_call")
         and refused(running, "not_stopped"), f"{said(second, 40)}; {said(none, 40)}; "
         f"{said(running, 40)}")
    call("close")


def _wrote() -> str | None:
    r = call("resume", seconds=5.0)
    if r.get("verdict") != "OTHER_STOP":
        call("stop")
        return None
    writes = (r.get("watch_hit") or {}).get("writes") or []
    return str(writes[-1].get("wrote")) if writes else None


def _j_circus(t: list[str]) -> None:
    circus_boot()
    call("watch_add", ref="0x2000", mode="change", length=1)
    # The latch climbs without repeating, then swings; open at the first value written twice in a
    # row after it left its first one, so the scan sees the latch return to its opening.
    first = previous = _wrote()
    opening = None
    for _ in range(400):
        now = _wrote()
        if now is not None and now == previous and now != first:
            opening = now
            break
        previous = now
    call("scan", method="start", ref="0x0", length=0x200)
    inited = _engine_init("ub,0x0,0x200", MAIN)
    kinds, rounds, wrote = {"!": 0, "=": 0}, [], opening
    for _ in range(60):
        wrote = _wrote() or wrote
        op = "!" if wrote != opening else "="
        r = call("scan", method="filter", operator=op)
        engine = _engine("notequal" if op == "!" else "equal")
        rounds.append((op, r.get("hits_total"), engine, _same(r, engine)))
        kinds[op] += 1
        if r.get("closed") or min(kinds.values()) >= 2:
            break
    agree = (all(h == e and same is not False for _, h, e, same in rounds)
             and any(same for *_, same in rounds))
    enough = min(kinds.values()) >= 2
    cell(t[4], inited and opening is not None and agree and enough,
         ("too few movements: " if agree and not enough else "") + f"{kinds} {rounds[-4:]}")
    call("close")


J_BOARDS = (Board(_j_m68k_dual, (0, 1, 2, 3), m68k_dual_missing),
            Board(_j_circus, (4,), free_boards_missing))
boards_cover("J_BOARDS", J_CELLS, J_BOARDS)


@section("J", "the value scan: known answers and refusals", J_CELLS)
def block_j_scan() -> None:
    run_boards(J_CELLS, J_BOARDS)
