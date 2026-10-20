"""The value scan: `scan_start`, `scan_filter`, `scan_clear`.

THE RANGE IS READ WITH THE CONSOLE'S `save` AND COMPARED IN PYTHON, not with MAME's own cheat
engine: `save` reads through handlers (a work RAM behind a bank or a handler, which the engine's
`cheatinit` refuses as "No writable bytes"), with the debugger's side effects disabled, into a
file whose bytes never cross the socket, and it neither steps nor writes the machine. The engine
is what the tests compare against, never the mechanism.

ONE READ RULE: every read saves from the first survivor to the last, which right after
`scan_start` is the whole range; a cell outside that span can no longer change the answer. The
survivors are `array` columns, the two values in the cell's own width and the offset in the
narrowest that spans the ceiling, so a scan holds a few bytes per cell rather than a Python int
and a list slot each.
"""

from __future__ import annotations

import operator as op
import sys
import uuid
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from scry_core import prose
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_cpus as cpus
import mame_envelope as menvelope
import mame_files as files
import mame_inputs as inputs
import mame_read as read
import mame_space as mspace
import mame_state as st
from mame_state import STATE

#: The cell sizes a scan takes, in bytes: the argument is the count the reply calls it.
CELL_BYTES = (1, 2, 4)
_TESTS: dict[str, Callable[[int, int], bool]] = {
    "=": op.eq, "!": op.ne, ">": op.gt, ">=": op.ge, "<": op.lt, "<=": op.le}
#: Compared unsigned; `!` is "not equal".
OPERATORS = tuple(_TESTS)
#: A V30's whole space, the widest range a bench's work RAM needs.
SCAN_BYTES_MAX = 0x100000


def _unsigned(size: int) -> str:
    """The unsigned `array` typecode of `size` bytes. C's sizes behind the codes are the
    platform's, so they are found by asking rather than assumed, and a platform with none fails
    here, at import."""
    return next(c for c in "BHILQ" if array(c).itemsize == size)


#: The typecode holding one cell of each size, and the narrowest holding any offset in cells.
TYPECODES = {n: _unsigned(n) for n in CELL_BYTES}
OFFSET_TYPECODE = _unsigned(next(n for n in (1, 2, 4, 8) if 1 << (8 * n) >= SCAN_BYTES_MAX))


@dataclass
class Scan:
    """The open scan: its range and cell, the cpu every filter reads, and per survivor (in
    address order) its offset in cells, the value it held when the scan opened, and the value
    the last read found."""
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


#: `scan_filter`'s `value` when none was given: each cell is held against its own opening value.
NO_VALUE_WHY = "no `value` was given, so each cell was compared with its value at `scan_start`"
NO_VALUE = unavailable(NO_VALUE_WHY)


def check_scan_start(ref: str = "", length: int = 0, cell_bytes: int = 1, **_: Any) -> None:
    """`scan_start`'s machine-independent half: the cell's size, and a length of whole cells."""
    inputs.check_ref(ref)
    inputs.one_of("cell_bytes", cell_bytes, CELL_BYTES)
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


def check_scan_filter(operator: str = "=", value: int | None = None, **_: Any) -> None:
    """`scan_filter`'s machine-independent half; the value against the width is the open
    scan's to judge."""
    inputs.one_of("operator", operator, OPERATORS)
    if value is not None:
        inputs.natural("value", value, " is not a whole number from 0: a scan compares unsigned")


def _cells_at(ses: gs.Session, scratch: Path, scan: Scan) -> array[int] | dict[str, Any]:
    """The cells from the first survivor to the last as the console's `save` reads them now,
    decoded in the scan's byte order and indexed from the first survivor (`offset - offsets[0]`),
    or the refusal it came to; the file is gone either way. The cpu goes on the `save` line
    always, so every filter reads the scan's own cpu whatever is visible."""
    folder = scratch / "scan"
    # A name of its own per save: a file a killed call left behind is never read as this one's.
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


def scan_start(ses: gs.Session, scratch: Path, ref: str, length: int, cell_bytes: int,
               cpu: str) -> dict[str, Any]:
    """The body of the `scan_start` tool."""
    check_scan_start(ref=ref, length=length, cell_bytes=cell_bytes)
    if (held := STATE.scan) is not None:
        raise st.Invalid("needs_call",
                         f"one scan at a time and one is open ({st.hex_addr(held.addr)} on "
                         f"{held.cpu}, {prose.counted(len(held.offsets), 'survivor')} after "
                         f"{prose.counted(held.iterations, 'filter')}): `scan_clear` it first, or "
                         "keep filtering it with `scan_filter`",
                         addr=st.hex_addr(held.addr), cpu=held.cpu, hits_total=len(held.offsets))
    on, thread, _ = files.save_target(ses, cpu)
    if on is None:
        raise st.Invalid("unexpected_answer",
                         "no cpu is named and the console marks none visible, so a scan would "
                         "read whichever cpu is visible at each filter: name the `cpu`")
    addr = STATE.resolve(ref, on)
    order = cpus.described(ses, on, thread).byte_order if cell_bytes > 1 else "little"
    code = TYPECODES[cell_bytes]
    # The two value columns start empty: `_cells_at` reads the span the offsets name, which here
    # is every cell, and the scan is held only once that read filled them.
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


def scan_filter(ses: gs.Session, scratch: Path, operator: str,
                value: int | None) -> dict[str, Any]:
    """The body of the `scan_filter` tool: each survivor against `value`, or with none against
    what it held when the scan opened. The read spans the first survivor to the last; only the
    survivors are compared."""
    check_scan_filter(operator=operator, value=value)
    scan = STATE.scan
    if scan is None:
        raise st.Invalid("needs_call",
                         "no scan is open, so there is nothing to filter: `scan_start` one")
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
    hex_cell = f"0x{{:0{2 * scan.cell_bytes}x}}".format
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
    listed = survivors <= read.LOG_LIMIT_MAX
    hits = ([{"addr": st.hex_addr(a), "value": hex_cell(v)} for a, v in scan.surviving()]
            if listed else [])
    return menvelope.envelope(reply | {"closed": False, "hits": hits, "hits_total": survivors,
                                       "truncated": not listed} | where)


def scan_clear() -> dict[str, Any]:
    """The body of the `scan_clear` tool."""
    if STATE.scan is None:
        return menvelope.envelope({"cleared": False, "note": "no scan was open"})
    STATE.scan = None
    return menvelope.envelope({"cleared": True})
