"""Section I of the live matrix: what `cpu_info` says of each cpu."""


from typing import Any

from bench_boards import (
    SUB_SYMBOLS,
    SYMBOLS,
)
from live_harness import (
    boot,
    call,
    cell,
    ensure_closed,
    ok,
    said,
    section,
    visible_of,
)
from matrix_tools_by_state import (  # noqa: E402
    MAIN,
    SUB,
)

#
# `cpu_info`'s rows on m68k-dual's two 68000s, each reading against an answer that does not come
# from `cpu_info`: the cpu's own `registers`, its `curpc` shown through `focus`, the console's
# listings, the `_list` tools' rows. "Moves nothing" is judged by readings that a step is proved
# to change, so the instrument can see a move.

I_CELLS = [
    "the sub cpu runs: its totalcycles grows across a frame",
    "cpu_info has a row for both cpus, each pc with its register and a value",
    "each cpu's pc equals its own registers' pc, numerically",
    "the sub cpu's pc equals its curpc shown through focus and back",
    "the visible cpu's pc equals status's pc",
    "after a step the visible cpu's pc is the step's, and it moved",
    "focus moves the visible row to the sub cpu, and back",
    "an ignored sub cpu is marked ignored and still read, and observe clears it",
    "a suspended sub cpu is marked suspended and still read, and resume clears it",
    "each cpu's counts equal the rows the _list tools give for it",
    "a bpclear typed at the console leaves the counts, and the rows read gone",
    "cpu_info moves nothing: frame, cycles, curpc, the listings, each cpu's registers",
    "the control: the same readings around a step differ in totalcycles and curpc",
]


# Read through `debug`, never the server's own readers: the answer each cell compares with
# `cpu_info` must not come from `cpu_info`'s code. -1 for an answer that is not a number, so a
# refused read fails its cell instead of ending the section.
def _printed(expr: str) -> int:
    words = str(call("debug", command=f"print {expr}").get("output") or "").split()
    try:
        return int(words[0], 16)
    except (IndexError, ValueError):
        return -1


def _sub_cycles() -> int:
    call("focus", cpu="subcpu")
    cycles = _printed("totalcycles")
    call("focus", cpu="maincpu")
    return cycles


def _rows(reply: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`cpu_info`'s rows by cpu."""
    return {row["cpu"]: row for row in reply.get("cpus") or []}


def _hex(value: Any) -> int:
    return int(value, 16) if isinstance(value, str) else -1


def _pc(rows: dict[str, dict[str, Any]], tag: str) -> dict[str, Any]:
    """A row's pc reading, empty when the row is absent or its pc unread."""
    return (rows.get(tag) or {}).get("pc") or {}


def _pc_of(rows: dict[str, dict[str, Any]], tag: str) -> int:
    """A row's pc value, or -1 when the row is absent or its pc unread."""
    return _hex(_pc(rows, tag).get("value"))


CYCLES, CURPC = "print frame,totalcycles", "print curpc"


def _readings() -> dict[str, Any]:
    """What a move would change, read through the console and each cpu's own thread."""
    out: dict[str, Any] = {c: call("debug", command=c).get("output") for c in (
        CYCLES, CURPC, "cpulist", "ignore", "suspend")}
    for tag in (MAIN, SUB):
        out[tag] = call("registers", cpu=tag).get("regs")
    return out


@section("I", "what cpu_info says of each cpu, on m68k-dual's two 68000s", I_CELLS)
def block_i_cpu_info() -> None:
    t = I_CELLS
    boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
    # The sub cpu leaves reset when the main one releases it, early in the boot.
    call("run_for", frames=60, seconds=10.0)
    before = _sub_cycles()
    call("run_for", frames=1, seconds=10.0)
    after = _sub_cycles()
    cell(t[0], after > before >= 0, f"{before:#x} -> {after:#x}")
    first_info = call("cpu_info")
    rows = _rows(first_info)
    cell(t[1], list(rows) == [MAIN, SUB]
         and all({"reg", "value"} <= set(r["pc"] or {}) for r in rows.values()),
         f"{[(c, r['pc']) for c, r in rows.items()]}")
    regs = {tag: call("registers", cpu=tag).get("regs", {}) for tag in (MAIN, SUB)}
    equal = {tag: _pc_of(rows, tag) >= 0
             and _pc_of(rows, tag) == _hex(regs[tag].get(_pc(rows, tag).get("reg", "")))
             for tag in (MAIN, SUB)}
    cell(t[2], all(equal.values()), f"{equal} {[r.get('PC') for r in regs.values()]}")
    call("focus", cpu="subcpu")
    curpc = _printed("curpc")
    call("focus", cpu="maincpu")
    cell(t[3], curpc >= 0 and _pc_of(rows, SUB) == curpc, f"{_pc_of(rows, SUB):#x} vs {curpc:#x}")
    st = call("status")
    cell(t[4], visible_of(first_info) == MAIN and _pc_of(rows, MAIN) == _hex(st.get("pc")),
         f"visible {visible_of(first_info)}, {_pc_of(rows, MAIN):#x} vs pc {st.get('pc')}")
    stepped = call("step", count=1)
    now = _rows(call("cpu_info"))
    cell(t[5], _pc_of(now, MAIN) == _hex(stepped.get("pc")) >= 0
         and _pc_of(now, MAIN) != _pc_of(rows, MAIN),
         f"{_pc_of(rows, MAIN):#x} -> {_pc_of(now, MAIN):#x}, step pc {stepped.get('pc')}")
    call("focus", cpu="subcpu")
    shown = visible_of(call("cpu_info"))
    call("focus", cpu="maincpu")
    back = visible_of(call("cpu_info"))
    cell(t[6], shown == SUB and back == MAIN, f"{shown}, then {back}")
    # The live cpu first: ignoring or suspending the cpu MAME is live on would run the machine.
    live = (call("status").get("last_stop") or {}).get("cpu")
    call("debug", command="ignore :subcpu")
    ignoring = _rows(call("cpu_info"))
    call("debug", command="observe :subcpu")
    cleared = _rows(call("cpu_info"))
    cell(t[7], live == MAIN and (ignoring.get(SUB) or {}).get("ignored") is True
         and (cleared.get(SUB) or {}).get("ignored") is False and _pc_of(ignoring, SUB) >= 0,
         f"live {live}, {ignoring.get(SUB)}, then {cleared.get(SUB)}")
    call("debug", command="suspend :subcpu")
    holding = _rows(call("cpu_info"))
    call("debug", command="resume :subcpu")
    released = _rows(call("cpu_info"))
    cell(t[8], (holding.get(SUB) or {}).get("suspended") is True
         and (released.get(SUB) or {}).get("suspended") is False and _pc_of(holding, SUB) >= 0,
         f"{holding.get(SUB)}, then {released.get(SUB)}")
    call("breakpoint_at", ref="exception_handler", cpu=MAIN)
    call("breakpoint_at", ref="0x8", cpu=SUB)
    call("watch_add", ref="0x200000", mode="change", length=2, cpu=SUB)
    call("regpoint_add", condition="pc==0xfffffffe")
    counts = {tag: row["declarations"] for tag, row in _rows(call("cpu_info")).items()}
    rows_listed = {tag: (len(call("declaration_list", kind="breakpoint", cpu=tag).get("breakpoints",
                                                                                      [])),
                         len(call("declaration_list", kind="watch", cpu=tag).get("watches", [])))
                   for tag in (MAIN, SUB)}
    regpoints = len(call("declaration_list", kind="regpoint").get("regpoints", []))
    cell(t[9], all((counts.get(tag, {}).get("breakpoints"), counts.get(tag, {}).get("watches"))
                   == rows_listed[tag] for tag in (MAIN, SUB))
         and counts.get(MAIN, {}).get("regpoints") == regpoints and rows_listed[SUB] == (1, 1),
         f"{counts} vs rows {rows_listed}, regpoints {regpoints}")
    call("debug", command="bpclear")
    kept = {tag: row["declarations"] for tag, row in _rows(call("cpu_info")).items()}
    states = [b.get("state") for b in call("declaration_list", kind="breakpoint").get("breakpoints",
                                                                                      [])]
    cell(t[10], kept == counts and states == ["gone", "gone"], f"{kept}, states {states}")
    call("declaration_clear", kind="breakpoint", all=True)
    call("declaration_clear", kind="watch", all=True)
    call("declaration_clear", kind="regpoint", all=True)
    first = _readings()
    between = call("cpu_info")
    second = _readings()
    cell(t[11], ok(between) and first == second,
         f"{said(between, 40)}; differ in {[k for k in first if first[k] != second[k]]}")
    call("step", count=1)
    third = _readings()
    cell(t[12], third[CYCLES] != second[CYCLES] and third[CURPC] != second[CURPC],
         f"{second[CURPC]!r} -> {third[CURPC]!r}")
    ensure_closed()
