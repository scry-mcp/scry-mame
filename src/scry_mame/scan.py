"""The value scan: `scan(method="start")`, `scan(method="filter")`, `scan(method="clear")`.

The range is read with the console's `save` and compared in Python, not with MAME's cheat engine:
`save` reads through handlers (the engine's `cheatinit` refuses a banked work RAM as "No writable
bytes"), with the debugger's side effects disabled, and neither steps nor writes the machine.

Every read saves from the first survivor to the last. Survivors are `array` columns (values in the
cell's width, offsets in the narrowest typecode spanning the ceiling), a few bytes per cell.
"""

from __future__ import annotations

import itertools
import operator as op
import sys
import uuid
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from scry_core import judges, prose
from scry_core import scan_vocabulary as words
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable, unavailable

from scry_mame import cpus, files, inputs
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import space as mspace
from scry_mame import state as st
from scry_mame.state import STATE

CELL_BYTES = words.CELL_BYTES
_TESTS: dict[str, Callable[[int, int], bool]] = dict(zip(
    words.OPERATORS, (op.eq, op.ne, op.gt, op.ge, op.lt, op.le), strict=True))
OPERATORS = words.OPERATORS
#: A V30's whole space, the widest range a bench's work RAM needs.
SCAN_BYTES_MAX = 0x100000


def _unsigned(size: int) -> str:
    """The unsigned `array` typecode of `size` bytes; fails at import if none."""
    return next(c for c in "BHILQ" if array(c).itemsize == size)


TYPECODES = {n: _unsigned(n) for n in CELL_BYTES}
OFFSET_TYPECODE = _unsigned(next(n for n in (1, 2, 4, 8) if 1 << (8 * n) >= SCAN_BYTES_MAX))


@dataclass
class Scan:
    """The open scan; per survivor, in address order: offset in cells, opening and latest value."""
    addr: int
    length: int
    cell_bytes: int
    cpu: str
    thread: int
    order: Literal["little", "big"]
    offsets: array[int]
    opening: array[int]
    values: array[int]
    iterations: int = 0

    @property
    def typecode(self) -> str:
        return TYPECODES[self.cell_bytes]

    def surviving(self) -> list[tuple[int, int]]:
        """Every survivor as (address, the value the last read found)."""
        return [(self.addr + i * self.cell_bytes, v)
                for i, v in zip(self.offsets, self.values, strict=True)]


NO_VALUE_WHY = ("no `value` was given, so each cell was compared with its value at "
                "`scan(method=\"start\")`")
NO_VALUE = unavailable(NO_VALUE_WHY)


def check_start_scan(ref: str = "", length: int = 0, cell_bytes: int = 1, **_: Any) -> None:
    """`scan(method="start")`'s machine-independent half."""
    inputs.check_ref(ref)
    vocab.one_of("cell_bytes", cell_bytes, CELL_BYTES)
    cell = cell_bytes
    inputs.count("length", length, tail=f": a length counts bytes, one {cell}-byte cell at least",
                 lo=cell)
    if length > SCAN_BYTES_MAX:
        raise st.Invalid("bad_argument",
                         f"length={length:#x} is past {SCAN_BYTES_MAX:#x}, the most one scan takes")
    if length % cell:
        below = length - length % cell
        raise st.Invalid("bad_argument",
                         f"length={length:#x} is not a whole number of {cell}-byte cells: "
                         f"{below:#x} or {below + cell:#x}")


def check_filter_scan(operator: str = "=", value: int | None = None,
                      limit: int = words.HITS_DEFAULT, **_: Any) -> None:
    """`scan(method="filter")`'s machine-independent half; the value's width is judged later."""
    vocab.one_of("operator", operator, OPERATORS)
    if value is not None:
        inputs.natural("value", value, " is not a whole number from 0: a scan compares unsigned")
    inputs.natural("limit", limit, f" is outside 1..{words.HITS_MAX}", 1, words.HITS_MAX)


def _cells_at(ses: gs.Session, scratch: Path, scan: Scan) -> array[int] | dict[str, Any]:
    """The cells from the first survivor to the last, indexed `offset - offsets[0]`, or the refusal.

    The cpu always goes on the `save` line, so every filter reads the scan's own cpu.
    """
    folder = scratch / "scan"
    # A unique name: a file a killed call left behind is never read as this save's.
    path = folder / f"{uuid.uuid4().hex}.bin"
    files.refuse_console_path(path)
    folder.mkdir(exist_ok=True)
    cell_bytes, base = scan.cell_bytes, scan.offsets[0]
    data = files.save_checked(ses, scan.cpu, scan.thread, f":{scan.cpu}",
                              scan.addr + base * cell_bytes,
                              (scan.offsets[-1] + 1 - base) * cell_bytes, path, keep=False)
    if isinstance(data, dict):
        return data
    cells = array(scan.typecode)
    cells.frombytes(data)
    if cell_bytes > 1 and scan.order != sys.byteorder:
        cells.byteswap()
    return cells


def start_scan(ses: gs.Session, scratch: Path, ref: str, length: int, cell_bytes: int,
               cpu: str) -> dict[str, Any]:
    """The body of the `scan(method="start")` tool."""
    check_start_scan(ref=ref, length=length, cell_bytes=cell_bytes)
    if (held := STATE.scan) is not None:
        raise st.Invalid("needs_call",
                         f"one scan at a time and one is open ({st.hex_addr(held.addr)} on "
                         f"{held.cpu}, {prose.counted(len(held.offsets), 'survivor')} after "
                         f"{prose.counted(held.iterations, 'filter')}): "
                         "`scan(method=\"clear\")` it first, or "
                         "keep filtering it with `scan(method=\"filter\")`",
                         addr=st.hex_addr(held.addr), cpu=held.cpu, hits_total=len(held.offsets))
    on, thread, _ = files.save_target(ses, cpu)
    if on is None:
        raise st.Invalid("unexpected_answer",
                         "no cpu is named and the console marks none visible, so a scan would "
                         "read whichever cpu is visible at each filter: name the `cpu`")
    addr = STATE.resolve(ref, on)
    order = cpus.described(ses, on, thread).byte_order if cell_bytes > 1 else "little"
    code = TYPECODES[cell_bytes]
    # The value columns start empty: `_cells_at` reads the span the offsets name, and the scan is
    # held only once that read succeeded.
    scan = Scan(addr, length, cell_bytes, on, thread, order,
                array(OFFSET_TYPECODE, range(length // cell_bytes)), array(code), array(code))
    opening = _cells_at(ses, scratch, scan)
    if isinstance(opening, dict):
        return opening
    scan.opening, scan.values = opening, array(code, opening)
    STATE.scan = scan
    return menvelope.envelope({"addr": st.hex_addr(addr), "length": length,
                               "cell_bytes": scan.cell_bytes, "hits_total": len(opening),
                               "cpu": or_unavailable(on, st.NO_CPU_READ_WHY),
                               "space": mspace.PROGRAM})


def filter_scan(ses: gs.Session, scratch: Path, operator: str,
                value: int | None, limit: int = words.HITS_DEFAULT) -> dict[str, Any]:
    """The body of the `scan(method="filter")` tool: survivors against `value` or opening value."""
    check_filter_scan(operator=operator, value=value, limit=limit)
    scan = STATE.scan
    if scan is None:
        raise st.Invalid("needs_call",
                         "no scan is open, so there is nothing to filter: `scan(method=\"start\")` "
                         "one")
    top = (1 << (8 * scan.cell_bytes)) - 1
    if value is not None and value > top:
        raise st.Invalid("bad_argument",
                         f"value={value:#x} does not fit a {scan.cell_bytes}-byte cell "
                         f"(at most {top:#x})")
    now = _cells_at(ses, scratch, scan)
    if isinstance(now, dict):
        return now
    test = _TESTS[operator]
    base = scan.offsets[0]
    offsets, opening, values = array(OFFSET_TYPECODE), array(scan.typecode), array(scan.typecode)
    for i, opened in zip(scan.offsets, scan.opening, strict=True):
        v = now[i - base]
        if test(v, opened if value is None else value):
            offsets.append(i)
            opening.append(opened)
            values.append(v)
    survivors = len(offsets)
    def hex_cell(v: int) -> str:
        return judges.hex_at_width(v, 8 * scan.cell_bytes)
    reply: dict[str, Any] = {"operator": operator,
                             "value": NO_VALUE if value is None else hex_cell(value),
                             "iterations": scan.iterations + 1}
    where = {"cpu": scan.cpu, "space": mspace.PROGRAM}
    if not survivors:
        STATE.scan = None
        return menvelope.envelope(reply | {"closed": True, "hits": [], "hits_total": 0,
                                           "truncated": False} | where)
    scan.offsets, scan.opening, scan.values = offsets, opening, values
    scan.iterations += 1
    # Past `limit` the first hits, never an empty list; `hits_total` counts the rest.
    hits = [{"addr": st.hex_addr(a), "value": hex_cell(v)}
            for a, v in itertools.islice(scan.surviving(), limit)]
    return menvelope.envelope(reply | {"closed": False, "hits": hits, "hits_total": survivors,
                                       "truncated": survivors > limit} | where)


def clear_scan() -> dict[str, Any]:
    """The body of the `scan(method="clear")` tool."""
    if STATE.scan is None:
        return menvelope.envelope({"cleared": False, "note": "no scan was open"})
    STATE.scan = None
    return menvelope.envelope({"cleared": True})
