"""A watch that CAPTURES: one row each time a trigger is written, holding a whole block, or each
time it is read, holding the read.

WHY IT EXISTS. A count watch answers per byte and per writer over a whole pass, and a joint
question dies in it: on a register block written by several routines ("the scale each blit
carries"), the raster routine's writes drown the sprite routine's, the values are shared across
writers, and two tallies cannot be joined afterwards. What the question needs is the block as it
stood at the one write that matters, the blit's strobe: every word, together, per event.

THE MECHANISM is every tap's (`mame_tap`), a fifth mode of the same tap: composed by the server,
sent through the console pipe and never stepped for, idempotent by id, answered by its sentinel
and resent once, removed by a send, re-armed at `start`. The tap sits on the bus word
that holds the TRIGGER and keeps the writes whose lanes cover the trigger's byte. For each one it
reads the block and appends a row: the frame, the beam line and the emulated time of the write,
the writer's pc (`CURPC`), the trigger write's own data and lane mask, and the block's bytes in the
cpu's order.

WHEN, TO THE CYCLE. The time is MAME's `machine.time`, which inside a tap is the accessing cpu's
own local time, so two accesses one cycle apart never share it and two cpus' rows order by it;
below the driver's interleave the order of two cpus' accesses is the scheduler's choice, not the
board's. The line is MAME's `vpos()`, which Lua does not bind, derived as `BEAM_LINE_LUA` says. A
machine with no screen stamps no frame and no line.

A READ TRIGGER (`trigger_type="r"`, `wpset`'s word) taps the reads instead, and its row is the
access alone, its value and its mask, with no block: a Lua read tap that reads memory inside its
callback re-enters the bus, which MAME does not survive.

WHERE THE BLOCK IS READ FROM, decided before the install. A block the address map backs with a
memory SHARE or REGION is read there, through the block's own reader: a write-only register
block (`.w(handler).share(...)`) has no read side, so the space answers zeros for it, while the
share holds every word the handler kept. Plain memory with no block of its own is read through
the space's DIRECT read, which touches no handler. A block whose read side is a handler is
refused: reading it inside a write would run that handler once per trigger.

WHAT A ROW SHOWS. The tap runs BEFORE the write lands, so the block holds every word already
written and, when the trigger lies inside the block, the trigger's value from BEFORE this write;
the write's own value is the row's `data`.

ROWS. The first `ROWS_MAX` are kept and the rest counted in `overflow_rows`, so a pass of any
length says what it dropped. They wait in the guest until a debugger stop, where the periodic
hook appends them to a file in the scratch and rewrites a header beside it, whole, through a
rename: the rows file only grows, so a reply names its path and shows the first rows.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from scry_core import judges
from scry_core import value_format as vf
from scry_core.reply_contract import unavailable

import mame_callbacks as callbacks
import mame_declarations as dec
import mame_files as files
import mame_inputs as inputs
import mame_read as read
import mame_region as region
import mame_space as mspace
import mame_state as st
import mame_tally as tally
import mame_tap as mtap
import mame_transport as transport
from mame_state import STATE

# The Lua registry every capture hangs from, beside the count watches' own.
REGISTRY = "MCP_CAPTURE"
HEADER = "MCP_CAPTURE"
# Rows a capture keeps before it only counts: a pass the length of an attract loop with margin.
ROWS_MAX = 100_000
_HEAD = re.compile(
    rf"^{HEADER} (\S+) seq=(\d+) frame=(-?\d+) total=(\d+) rows=(\d+) overflow_rows=(\d+) "
    r"data_width=(\d+) endianness=(\w+) cpu=(\S+)$")
_ROW = re.compile(r"^r (\d+) (-?\d+) (-?\d+) (\d+)\.(\d{18}) ([0-9a-f]+) ([0-9a-f]+) "
                  r"([0-9a-f]+) ([0-9a-f]*)$")
ATTOSECONDS_PER_SECOND = 10**18
# THE BEAM LINE OF THE PRESENT INSTANT, `vpos()` as Lua cannot call it, and the one place that
# says how it is derived. `vpos()` takes the time since line 0, adds half a pixel, divides by the
# line's period in integer attoseconds and wraps over the frame's lines, so the tie half a pixel
# before a line is already that line and the last half pixel of a frame is line 0. Lua binds the
# periods as doubles, where the tie lands either side by a rounding error: the quotient is nudged
# by a billionth of a line, far above that error and far below one cycle, so it rounds as
# `vpos()` does. The frame's sentinel on a machine with no screen.
BEAM_LINE_LUA = f"""local function beam_line()
  if screen == nil then return {callbacks.NO_FRAME} end
  local scan = screen.scan_period
  local since = screen.frame_period - screen:time_until_pos(0, 0)
  return math.floor((since + screen.pixel_period / 2) / scan + 1e-9)
    % math.floor(screen.frame_period / scan + 0.5)
end
"""


@dataclass(frozen=True)
class TapSource:
    """Where a capture's block is read inside the tap: a `share` or a `region` by `tag`, the full
    tag the address map carries (`mame_machine.full_tag`), at `offset` into it, or `space` at
    `offset`, the block's own address."""
    kind: str
    tag: str
    offset: int

    def fields(self) -> dict[str, Any]:
        return ({"kind": self.kind, "addr": st.hex_addr(self.offset)} if self.kind == "space"
                else {"kind": self.kind, "tag": self.tag, "offset": self.offset})


def id_for(cpu: str | None, addr: int, width: int, trigger: int,
           space: str = "program", trigger_type: str = "w") -> str:
    """The id a capture is kept under: the block and the trigger on its cpu, so two
    declarations of one capture meet the same tap, and the count watch's rules for the cpu and
    for a trigger outside the program space; a read trigger's carries an `r`, since a capture of
    the reads is not the capture of the writes."""
    read = "r" if trigger_type == "r" else ""
    return f"{tally.id_for(cpu, addr, width)}_t{trigger:x}{read}{mspace.suffix(space)}"


def paths(scratch: Path, capture_id: str) -> tuple[Path, Path]:
    """The header the periodic rewrites and the rows file it appends to."""
    return scratch / f"capture-{capture_id}.txt", scratch / f"capture-{capture_id}.rows"


def trigger_addr(trigger: str, table: dict[str, int]) -> int | None:
    """Where a declared trigger points against `table` (`inputs.stored_place`)."""
    return inputs.stored_place(trigger, table)


def source(addr: int, width: int, cpu: str | None,
           read_side: Callable[[int], str | None]) -> TapSource:
    """Where the block `width` bytes at `addr` of `cpu` is read inside the tap, or the refusal.

    A share or a region when ONE entry of the cpu's program space, in the address map `start`
    cached, reaches the block and holds it whole: where entries overlap, MAME's bus answers
    with the one installed last, so a first match would read the memory under an overlay. An
    entry that masks its addresses is not placed by offset here (`mame_region.place` says
    why). Otherwise the space's direct read, which takes the space's own decode, when the
    console's `map` (`read_side`, asked on the block's cpu) answers memory at the block's
    first byte and at the first byte of every entry that reaches into it; a direct read of a
    handler answers zeros that look like data, so a block with one inside is refused. The
    reader comes in as an argument (`mame_map.read_side` builds it) so this decision is a pure
    function its tests drive with a table of answers."""
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
    """The session's captures of a block, in the order first recorded, on `cpu` (every cpu when
    empty, compared by `st.bare_tag`), whose trigger is in `space` (any when empty): a manifest's
    fire word is a program address, so a port's capture never answers for one. A capture's
    record is the one tap record that carries a `trigger`: one predicate, beside the code that
    writes the record. A read trigger's capture holds no block, so it is none of these: every
    caller here reads blocks."""
    return [(owner, rec) for owner, rec in STATE.tallies.items()
            if rec.get("trigger") is not None and rec.get("trigger_type", "w") == "w"
            and (not space or rec.get("space", "program") == space)
            and (not cpu or st.bare_tag(owner[1]) == st.bare_tag(cpu))]


def reading_region(tag: str, offset: int, length: int) -> list[dict[str, str | None]]:
    """Every capture whose block the region `tag` backs within `offset`..`offset+length-1`:
    what a region write changes under a capture without a bus write it could see."""
    last = offset + length - 1
    return [{**mspace.shown(ref), "cpu": cpu} for (ref, cpu), rec in block_captures(space="")
            if (src := rec.get("source")) is not None and src.kind == "region"
            and src.tag == tag and src.offset <= last and offset < src.offset + rec["width"]]


def install_script(capture_id: str, trigger: int, src: TapSource, width: int, head: Path,
                   rows: Path, cpu: str | None = None, trigger_space: str = "program",
                   trigger_type: str = "w") -> str:
    """The Lua that installs capture `capture_id`: a tap on the bus word holding `trigger`,
    keeping the accesses that cover its byte, each appending a row stamped with its frame, beam
    line and time; a write's row carries the block read from `src`, a read's (`trigger_type`
    `r`) none. One chunk, on `cpu` (`mtap.bound_cpu`). The trigger's tap sits in `trigger_space`
    (`tsp`, a port's `out` in `io`) and the block is read in the program space (`sp`), where a
    block lives. The install prints every tap's `installed` line (`mtap.ANSWER_PREFIX`). The files
    a removed tap left on the range go as a count watch's dump does (`tally.install_script`);
    with a tap there, its rows file is what the install carries on appending to."""
    reads = trigger_type == "r"
    reader = ("sp:read_direct_u8(off + i)" if src.kind == "space" else "blk:read_u8(off + i)")
    capture_id_literal = transport.lua_string(capture_id)
    lookup = ("" if src.kind == "space" or reads else
              f"""local blk = mem.{src.kind}s[{transport.lua_string(src.tag)}]
if blk == nil then error("no {src.kind} named " .. {transport.lua_string(src.tag)}) end
""")
    block = ("" if reads else f"""  local b = {{}}
  for i = 0, width - 1 do b[i + 1] = {reader} end
""")
    block_text = '""' if reads else "string.format(fmt, table.unpack(b))"
    dumper = f"""  local function dump(it, fr)
    if not it.dirty and it.dumped_frame == fr then return end
    if it.npending > 0 then
      local r = {callbacks.OPENED}(it, io.open(it.rows_path, "a"))
      if r ~= nil then
        r:write(table.concat(it.pending, "\\n", 1, it.npending), "\\n")
        r:close()
        it.pending, it.npending = {{}}, 0
      end
    end
    it.seq = it.seq + 1
    local f = {callbacks.OPENED}(it, io.open(it.head .. ".tmp", "w"))
    if f == nil then return end
    f:write(string.format("{HEADER} %s seq=%d frame=%d total=%d rows=%d ", it.id, it.seq,
      fr, it.rows + it.overflow_rows, it.rows))
    f:write(string.format("overflow_rows=%d data_width=%d endianness=%s cpu=%s errors=%d\\n",
      it.overflow_rows, it.data_width, it.endianness, it.cpu, it.errors))
    if it.first_error ~= nil then f:write("e ", it.first_error, "\\n") end
    f:write("end\\n")
    f:close()
    os.rename(it.head .. ".tmp", it.head)
    it.dirty = false
    it.dumped_frame = fr
  end
  dump_at_stops(T, dump)
"""
    return mtap.tap_prelude(REGISTRY) + f"""\
local id, trig, width, off = {capture_id_literal}, {trigger:#x}, {width}, {src.offset:#x}
local head, rows = {transport.lua_string(str(head))}, {transport.lua_string(str(rows))}
{mtap.bound_cpu(cpu)}
local sp = cpu.spaces["program"]
local tsp = cpu.spaces[{transport.lua_string(trigger_space)}]
local curpc = cpu.state["CURPC"]
local mem = manager.machine.memory
{lookup}local screen = nil
for _, scr in pairs(manager.machine.screens) do screen = scr break end
{BEAM_LINE_LUA}{mtap.REMOVE_OLD_TAP}
local t = {{id = id, head = head, rows_path = rows, rows = 0, overflow_rows = 0, pending = {{}},
  npending = 0, errors = 0, seq = 0, dumped_frame = {callbacks.NO_FRAME}, dirty = true,
  data_width = tsp.data_width, endianness = tsp.endianness, cpu = cpu.tag}}
if old ~= nil then
  for _, k in ipairs({{"rows", "overflow_rows", "pending", "npending", "errors", "first_error",
                       "seq"}}) do t[k] = old[k] end
end
if old == nil then os.remove(head) os.remove(head .. ".tmp") os.remove(rows) end
local nb = tsp.data_width // 8
local lo = trig - (trig % nb)
local lane = trig - lo
local shift = tsp.endianness == "big" and (nb - 1 - lane) * 8 or lane * 8
local fmt = string.rep("%02x", width)
t.tap = tsp:install_{"read" if reads else "write"}_tap(lo, lo + nb - 1, "mcp_capture_" .. id,
    guarded(t, function(offset, data, mask)
  if ((mask >> shift) & 0xff) == 0 then return end
  if t.rows >= {ROWS_MAX} then t.overflow_rows = t.overflow_rows + 1 t.dirty = true return end
  local now = manager.machine.time
{block}  -- a row is counted once it is kept: a body that raised half-way leaves no hole in the file
  local n = t.npending + 1
  t.pending[n] = string.format("r %d %d %d %d.%018d %x %x %x ", t.rows + 1,
    screen and screen:frame_number() or {callbacks.NO_FRAME}, beam_line(), now.seconds,
    now.attoseconds, curpc.value, data, mask) .. {block_text}
  t.npending, t.rows, t.dirty = n, t.rows + 1, true
end))
T.items[id] = t
{mtap.register_dumper_once(dumper)}
print(string.format("{mtap.ANSWER_PREFIX} installed tally_id=%s trigger=%x ", id, trig)
  .. string.format("data_width=%d endianness=%s cpu=%s", tsp.data_width, tsp.endianness,
                   cpu.tag))"""


def parse_capture_header(text: str) -> dict[str, Any] | None:
    """A header as the periodic wrote it, or None when the text is not a whole one."""
    whole = callbacks.read_whole(text, _HEAD, with_body=False)
    if whole is None:
        return None
    m, _, errors = whole
    return {"id": m.group(1), "seq": int(m.group(2)), "frame": int(m.group(3)),
            "total": int(m.group(4)), "rows": int(m.group(5)), "overflow_rows": int(m.group(6)),
            "data_width": int(m.group(7)), "endianness": m.group(8), "cpu": m.group(9),
            **errors}


class Row(NamedTuple):
    """One row of a rows file. `frame` and `line` are `callbacks.NO_FRAME` on a machine with no
    screen; `block` is empty on a read trigger's row."""
    n: int
    frame: int
    line: int
    time_attoseconds: int
    pc: int
    data: int
    mask: int
    block: bytes


def rows(path: Path) -> Iterator[Row]:
    """Every row of a rows file in order; a line of another shape ends the read, since a row cut
    by a write in progress is no row."""
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
    """The `width` bytes at `trigger` in one bus write, placed as the tap places the trigger's
    byte; None when the write did not cover every one of them, or when they cross the bus word."""
    if mspace.crosses(trigger, width, data_width):
        return None
    shift = mspace.lane_shift(trigger % (data_width // 8), width, data_width, endianness)
    full = (1 << 8 * width) - 1
    return None if (mask >> shift) & full != full else (data >> shift) & full


def first_rows(path: Path, count: int) -> list[Row]:
    """The first `count` rows of a rows file (`rows`)."""
    return list(itertools.islice(rows(path), count))


# THE WIDEST JSON A FLOAT PRINTS AS, by its width in bytes: a sign, the 17 significant digits a
# double's repr can need, the point, and an exponent of up to 3 digits for a double (`e-308`) and 2
# for a single, whose range is a double's narrower one. `nan` and the infinities print shorter.
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
    """The widest a block of `width` bytes decoded in `fmt` prints as JSON (`json.dumps`, which a
    reply is measured by): every scalar at its widest, a string as six characters a byte (a
    byte past ASCII is escaped `\\u00XX`), a struct's field names counted with their quotes. What
    a capture's format is held to, since a struct's names are the caller's and unbounded."""
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
    """One row as a reply shows it: its frame, line and time (`time_s` at a double's full
    precision, since two accesses one cycle apart are nanoseconds apart), the trigger access's
    data and mask at the bus's width, the accessor placed in the symbol table, and a write's
    block decoded in the watch's format; a read's row has no block."""
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
    """Put the capture's install for `owner` in the pipe, on its cpu, and record it as every tap
    is (`mtap.send_tap`). A read trigger's has no `src`: it reads no block."""
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
    """What a stop survey or `declaration_list(kind="watch")` says about the capture under `owner`
    (`mtap.read_tap`,
    whose `total` is every trigger access), and once it has a header: `rows_kept`, `overflow_rows`,
    `rows_path`, and in `declaration_list(kind="watch")` the first `shown` rows. A STOP LISTS NONE:
    every reply
    carries a survey whatever the call was about, and a block of rows in each one is noise."""
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
