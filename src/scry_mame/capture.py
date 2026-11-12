"""A watch that captures: one row each time a trigger is written (holding a whole block) or read.

A count watch cannot answer a joint question: on a register block written by several routines,
two tallies cannot be joined afterwards. A capture keeps the block as it stood at the one write
that matters. The mechanism is every tap's (`tap`).

`machine.time` inside a tap is the accessing cpu's local time, so rows of two cpus order by it,
but below the driver's interleave that order is the scheduler's choice, not the board's.

A read trigger (`trigger_type="r"`) taps the reads and its row has no block: a Lua read tap that
reads memory inside its callback re-enters the bus, which MAME does not survive.

The block is read from its memory share or region when the address map backs it with one (a
write-only register block has no read side, so the space answers zeros for it); plain memory is
read through the space's direct read, which touches no handler. A block whose read side is a
handler is refused: reading it inside a write would run that handler once per trigger.

The tap runs before the write lands, so a trigger inside the block shows its previous value;
the write's own value is the row's `data`.

Rows past `ROWS_MAX` are counted in `overflow_rows`. Rows wait in the guest until a debugger
stop, where the periodic hook appends them to a file and rewrites the header by rename.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from scry_core import bus_writes, file_names, judges
from scry_core import value_format as vf
from scry_core.reply_contract import unavailable

from scry_mame import callbacks, files, inputs, lua_source, read, region, tally
from scry_mame import declarations as dec
from scry_mame import space as mspace
from scry_mame import state as st
from scry_mame import tap as mtap
from scry_mame.state import STATE

REGISTRY = "MCP_CAPTURE"
HEADER = "MCP_CAPTURE"
ROWS_MAX = 100_000
_HEAD = re.compile(
    rf"^{HEADER} (\S+) seq=(\d+) frame=(-?\d+) total=(\d+) rows=(\d+) overflow_rows=(\d+) "
    r"data_width=(\d+) endianness=(\w+) cpu=(\S+)$")
_ROW = re.compile(r"^r (\d+) (-?\d+) (-?\d+) (\d+)\.(\d{18}) ([0-9a-f]+) ([0-9a-f]+) "
                  r"([0-9a-f]+) ([0-9a-f]*)$")
ATTOSECONDS_PER_SECOND = 10**18
BEAM_LINE_LUA = lua_source.render("beam-line", no_frame=callbacks.NO_FRAME)


@dataclass(frozen=True)
class TapSource:
    """Where a block is read inside the tap: a `share` or `region` by full `tag`, or `space`."""
    kind: str
    tag: str
    offset: int

    def fields(self) -> dict[str, Any]:
        return ({"kind": self.kind, "addr": st.hex_addr(self.offset)} if self.kind == "space"
                else {"kind": self.kind, "tag": self.tag, "offset": st.hex_addr(self.offset)})


def id_for(cpu: str | None, addr: int, width: int, trigger: int,
           space: str = "program", trigger_type: str = "w") -> str:
    """The id a capture is kept under; a read trigger's carries an `r`."""
    read = "r" if trigger_type == "r" else ""
    return f"{tally.id_for(cpu, addr, width)}_t{trigger:x}{read}{mspace.suffix(space)}"


def paths(scratch: Path, capture_id: str) -> tuple[Path, Path]:
    """The header path and the rows path."""
    words = tally.id_words(capture_id)
    return (scratch / file_names.name("capture", words, extension="txt"),
            scratch / file_names.name("capture", words, extension="rows"))


def trigger_addr(trigger: str, table: dict[str, int]) -> int | None:
    """Where a declared trigger points against `table` (`inputs.stored_place`)."""
    return inputs.stored_place(trigger, table)


def source(addr: int, width: int, cpu: str | None,
           read_side: Callable[[int], str | None]) -> TapSource:
    """Where the block `width` bytes at `addr` of `cpu` is read inside the tap, or the refusal.

    A share or region when one entry of the program space holds the block whole: where entries
    overlap the bus answers with the one installed last, so a first match would read the memory
    under an overlay. Otherwise the space's direct read, when `read_side` (the console's `map`)
    answers memory at the block's first byte and at every entry start inside it; a direct read of
    a handler answers zeros that look like data."""
    last = addr + width - 1
    rows = STATE.machine_map.get("address_map", []) if STATE.machine_map else []
    reaching = [e for e in rows if e["cpu"] == cpu and e["space"] == "program"
                and region.unmirrored(e, addr) <= int(e["end"], 16)
                and region.unmirrored(e, last) >= int(e["start"], 16)]
    if len(reaching) == 1 and "address_mask" not in reaching[0]:
        entry = reaching[0]
        start = int(entry["start"], 16)
        if start <= region.unmirrored(entry, addr) and region.unmirrored(entry, last) <= int(
                entry["end"], 16):
            offset = region.unmirrored(entry, addr) - start
            if "share" in entry:
                return TapSource("share", entry["share"], offset)
            if "region" in entry:
                return TapSource("region", entry["region"], entry["region_offset"] + offset)
    probes = sorted({addr} | {s for e in reaching if addr < (s := int(e["start"], 16)) <= last})
    for at in probes:
        read = read_side(at)
        if read is None or not read.startswith("memory@"):
            raise st.Invalid("bad_argument",
                             f"the block {addr:#x}..{last:#x} has no memory a tap can read at "
                             f"{at:#x}: the console's `map` answers its read side with "
                             f"{read!r}, and no single share or region of the address map holds "
                             "the block; a handler read inside a write would run it once per "
                             "trigger. Capture a block memory backs")
    return TapSource("space", "", addr)


def block_captures(cpu: str = "",
                   space: str = "program") -> list[tuple[dec.Owner, dict[str, Any]]]:
    """The session's captures of a block on `cpu` (every cpu when empty) triggered in `space`
    (any when empty); a read trigger's capture holds no block."""
    return [(owner, rec) for owner, rec in STATE.tallies.items()
            if rec.get("trigger") is not None and rec.get("trigger_type", "w") == "w"
            and (not space or rec.get("space", "program") == space)
            and (not cpu or st.bare_tag(owner[1]) == st.bare_tag(cpu))]


def reading_region(tag: str, offset: int, length: int) -> list[dict[str, str | None]]:
    """Every capture whose block the region `tag` backs within the range: a region write changes
    it without a bus write the tap could see."""
    last = offset + length - 1
    return [{**mspace.shown(ref), "cpu": cpu} for (ref, cpu), rec in block_captures(space="")
            if (src := rec.get("source")) is not None and src.kind == "region"
            and src.tag == tag and src.offset <= last and offset < src.offset + rec["width"]]


def install_script(capture_id: str, trigger: int, src: TapSource, width: int, head: Path,
                   rows: Path, cpu: str | None = None, trigger_space: str = "program",
                   trigger_type: str = "w") -> str:
    """The Lua that installs capture `capture_id`: a tap on the bus word holding `trigger`.
    The tap sits in `trigger_space`; the block is read in the program space."""
    reads = trigger_type == "r"
    code = lua_source.Code
    reader = ("sp:read_direct_u8(off + i)" if src.kind == "space" else "blk:read_u8(off + i)")
    source = (lua_source.render("capture-space") if src.kind == "space" else
              lua_source.render("capture-lookup", blocks=code(f"{src.kind}s"), tag=src.tag,
                                kind=src.kind))
    prepared = ("" if reads else
                lua_source.render("capture-reader", width=width, off=code(f"{src.offset:#x}"),
                                  source=code(source)))
    block = "" if reads else lua_source.render("capture-block", reader=code(reader))
    dumper = lua_source.render("capture-dumper", header=HEADER)
    return mtap.tap_prelude(REGISTRY) + lua_source.render(
        "capture-install", id=capture_id, trig=code(f"{trigger:#x}"),
        head=str(head), rows=str(rows), bind_cpu=code(mtap.bound_cpu(cpu)),
        trigger_space=trigger_space, reader=code(prepared),
        beam=code(BEAM_LINE_LUA), remove_old=code(mtap.REMOVE_OLD_TAP),
        no_frame=callbacks.NO_FRAME,
        install=code("install_read_tap" if reads else "install_write_tap"),
        rows_max=ROWS_MAX, block=code(block),
        block_text=code('""' if reads else "string.format(fmt, table.unpack(b))"),
        dumper=code(mtap.register_dumper_once(dumper)), answer=mtap.ANSWER_PREFIX).rstrip("\n")


def parse_capture_header(text: str) -> dict[str, Any] | None:
    """A header, or None when the text is not a whole one."""
    whole = callbacks.read_whole(text, _HEAD, with_body=False)
    if whole is None:
        return None
    m, _, errors = whole
    return {"id": m.group(1), "seq": int(m.group(2)), "frame": int(m.group(3)),
            "total": int(m.group(4)), "rows": int(m.group(5)), "overflow_rows": int(m.group(6)),
            "data_width": int(m.group(7)), "endianness": m.group(8), "cpu": m.group(9),
            **errors}


class Row(NamedTuple):
    """One row; `frame`/`line` are `callbacks.NO_FRAME` with no screen, `block` empty on a read."""
    n: int
    frame: int
    line: int
    time_attoseconds: int
    pc: int
    data: int
    mask: int
    block: bytes


def rows(path: Path) -> Iterator[Row]:
    """Every row in order; a line of another shape ends the read (a row cut mid-write is no row)."""
    for line in files.file_lines(path):
        m = _ROW.match(line.rstrip("\n"))
        if m is None:
            return
        yield Row(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                  int(m.group(4)) * ATTOSECONDS_PER_SECOND + int(m.group(5)),
                  int(m.group(6), 16), int(m.group(7), 16), int(m.group(8), 16),
                  bytes.fromhex(m.group(9)))


def lane(data: int, mask: int, data_width: int, endianness: str, trigger: int,
         width: int) -> int | None:
    """The `width` bytes at `trigger` in one bus write; None if uncovered or across the bus word."""
    if mspace.crosses(trigger, width, data_width):
        return None
    shift = bus_writes.lane_shift(trigger % (data_width // 8), width, data_width, endianness)
    full = (1 << 8 * width) - 1
    return None if (mask >> shift) & full != full else (data >> shift) & full


def first_rows(path: Path, count: int) -> list[Row]:
    """The first `count` rows."""
    return list(itertools.islice(rows(path), count))


# Widest JSON a float prints as, by width in bytes: sign, 17 digits, point, exponent.
_FLOAT_CHARS = {4: 1 + 17 + 1 + 2 + 2, 8: 1 + 17 + 1 + 2 + 3}


def _scalar_chars(elem: str) -> int:
    code, size = vf.SCALARS[elem]
    if code in "fd":
        return _FLOAT_CHARS[size]
    bits = 8 * size
    lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if code.islower() else (0, (1 << bits) - 1)
    return max(len(str(lo)), len(str(hi)))


def _list_chars(n: int, each: int) -> int:
    """`n` values of at most `each` characters as a JSON list: brackets and `, ` between."""
    return 2 + n * each + 2 * (n - 1) if n else 2


def block_chars_max(fmt: vf.Format, width: int) -> int:
    """The widest a block of `width` bytes in `fmt` prints as JSON: a string is six characters
    a byte (`\\u00XX`)."""
    if fmt.kind == "struct":
        fields = [len(json.dumps(name)) + 2 + block_chars_max(sub, 0) for name, sub in fmt.fields]
        return 2 + sum(fields) + 2 * (len(fields) - 1)
    if fmt.kind == "string":
        assert fmt.count is not None
        return 2 + 6 * fmt.count
    assert fmt.elem is not None
    n = fmt.width_for(width) // vf.SCALARS[fmt.elem][1]
    each = _scalar_chars(fmt.elem)
    return _list_chars(n, each) if fmt.kind == "array" or n > 1 else each


#: A row's `frame` and `line` on a board with no screen to count them on.
NO_SCREEN_WHY = "this machine has no screen, so no frame or line is counted"


def row_fields(row: Row, fmt: str, width: int,
               data_width: int, endianness: str, cpu: str | None) -> dict[str, Any]:
    """One row as a reply shows it; `time_s` keeps a double's full precision since two accesses
    one cycle apart are nanoseconds apart."""
    out: dict[str, Any] = {
        "n": row.n,
        "frame": unavailable(NO_SCREEN_WHY) if row.frame == callbacks.NO_FRAME else row.frame,
        "line": unavailable(NO_SCREEN_WHY) if row.line == callbacks.NO_FRAME else row.line,
        "time_s": row.time_attoseconds / ATTOSECONDS_PER_SECOND, "pc": st.hex_addr(row.pc),
        "data": judges.hex_at_width(row.data, data_width),
        "mask": judges.hex_at_width(row.mask, data_width)}
    if fmt:
        out["raw_hex"] = row.block.hex()
    read.add_symbol(out, row.pc, cpu)
    if fmt:
        try:
            out["block"] = vf.parse(fmt).decode(row.block, endianness, width)
        except vf.FormatError as e:
            out["block"] = unavailable(str(e))
    return out


def send_install(scratch: Path, owner: dec.Owner, addr: int, width: int, trigger: int,
                 src: TapSource | None, trigger_space: str = "program",
                 trigger_type: str = "w") -> dict[str, Any]:
    """Put the capture's install for `owner` in the pipe (`mtap.send_tap`); a read has no `src`."""
    cpu = owner[1]
    capture_id = id_for(cpu, addr, width, trigger, trigger_space, trigger_type)
    head, rows = paths(scratch, capture_id)
    script = install_script(capture_id, trigger, src or TapSource("space", "", addr), width,
                            head, rows, cpu, trigger_space, trigger_type)
    return mtap.send_tap(scratch, owner, capture_id, script, REGISTRY, [head, rows], addr=addr,
                         width=width, path=head, rows_path=rows, trigger=trigger, source=src,
                         space=trigger_space, trigger_type=trigger_type)


def evaluate(scratch: Path, owner: dec.Owner, width: int, fmt: str, frame: int | None,
             shown: int, at_stop: bool) -> dict[str, Any]:
    """What a stop survey or `declaration_list(kind="watch")` says about the capture under
    `owner`; the first `shown` rows only in the list, since every stop reply carries a survey."""
    item, head = mtap.read_tap(scratch, owner, frame, at_stop, parse_capture_header, "captured")
    rec = STATE.tallies[owner]
    reads = rec.get("trigger_type", "w") == "r"
    item.update(trigger_addr=st.hex_addr(rec["trigger"]),
                trigger_type=rec.get("trigger_type", "w"), rows_path=str(rec["rows_path"]))
    if not reads:
        item["source"] = rec["source"].fields()
    if head is None:
        return item
    item.update(rows_kept=head["rows"], overflow_rows=head["overflow_rows"], rows_max=ROWS_MAX)
    if at_stop:
        return item
    listed = first_rows(rec["rows_path"], min(shown, head["rows"]))
    item["first_rows"] = [row_fields(r, "" if reads else fmt, width, head["data_width"],
                                     head["endianness"], head["cpu"]) for r in listed]
    return item
