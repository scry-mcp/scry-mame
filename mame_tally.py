"""A watch that COUNTS: every write to a range over a pass, by value and by writer, never
stopping for one.

WHY IT EXISTS. A change watch answers "who wrote this byte" by stopping at the first write,
and a census asks the other question: which values does this register take over a whole
attract pass, and from which pcs. `disarm_watches` disarms the change watches for a pass, so a
held pass counts nothing and reads exactly like an address nobody writes. Every census on
the blitter boards went through a Lua write tap written by hand in each session; this is
that tap, composed by the server, keyed by a declaration, read back at every stop.

THE MECHANISM, on a 68000 board. `space:install_write_tap` calls its function once
per BUS write with the access offset, the data and the lane mask: a `move.l` arrives as two
word events, a `move.b` as a word carrying the byte on both lanes with the mask naming the
one that lands. `cpu.state["CURPC"]` inside the callback is the writing instruction's own
pc (`PC` is the prefetch, two bytes on). `emu.register_periodic` runs per frame while the
machine runs and several times at every debugger stop, where the debugger's
`execution_state` reads `stop`: that is where each tally is written to a file in the
scratch, whole, through a rename, and the stop survey reads it. The tap and the registry
live in the MAME process's `_G`, so a new `start` begins clean and `rearm` sends the
installs again.

IDEMPOTENT BY ID, because the console's reader dies now and then and the console then runs
an earlier chunk AGAIN (`console_reruns`): the probe's tap was installed twice and every
write counted twice. An install removes the tap already held under its id and CARRIES ITS
COUNTS into the new one, so a rerun neither doubles nor zeroes a census. A `watch_clear`
removes the tap, so a clear followed by a new declaration starts from zero. How a tap is sent,
proved, removed and read is every tap's (`mame_tap`).

THE TAP IS THE HOT PATH: a blitter register takes hundreds of thousands of writes per
line. What the callback does per write is what the census costs, so the writer's state
entry is looked up once at install, the value key is an integer and never a formatted
string, and a range that is bus-aligned skips the lane test altogether.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scry_core import prose
from scry_core import value_format as vf

import mame_callbacks as callbacks
import mame_declarations as dec
import mame_read as read
import mame_space as mspace
import mame_state as st
import mame_tap as mtap
import mame_transport as transport
from mame_state import STATE

# The Lua registry every tally hangs from, in the MAME process's `_G`.
REGISTRY = "MCP_TALLY"
# Distinct values and distinct writer pcs a tally keeps buckets for. Past the cap a write
# still counts in `total` and in `overflow_values` / `overflow_pcs`, so a table that was
# cut says so instead of looking complete. A 16-bit register has at most 65536 values and
# a handful of writers; a tally that overflows is one on a byte of a buffer.
BUCKETS_MAX = 256
# The prefix of a count watch's dump.
HEADER = "MCP_TALLY"
_HEAD = re.compile(
    rf"^{HEADER} (\S+) seq=(\d+) frame=(-?\d+) total=(\d+) values=(\d+) pcs=(\d+) "
    r"overflow_values=(\d+) overflow_pcs=(\d+) data_width=(\d+) endianness=(\w+) cpu=(\S+)$")
_VALUE = re.compile(r"^v ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+) (\d+)$")
_PC = re.compile(r"^p ([0-9a-f]+) (\d+)$")


def id_for(cpu: str | None, addr: int, width: int, space: str = "program") -> str:
    """The id a range is tallied under: in the Lua registry, in the dump's name and in every
    reply, as `tally_id`. The range itself on its cpu, so two declarations of one range (two
    spellings of one address) meet the same tap and the second install adopts the first, and
    the same range on another cpu, another program's memory, is another tap. The first cpu's
    id is the range alone and another cpu's carries its tag without the colons, since the id
    names a file. A range in another space than the program's carries it (`@io`): port 6 and
    RAM address 6 are two places."""
    tag = "" if cpu in (None, STATE.first_cpu) else "_" + str(cpu).strip(":").replace(":", ".")
    return f"{addr:x}_{width}{tag}{mspace.suffix(space)}"


def dump_path(scratch: Path, tally_id: str) -> Path:
    return scratch / f"tally-{tally_id}.txt"


def install_script(tally_id: str, addr: int, width: int, path: Path,
                   cpu: str | None = None, space: str = "program") -> str:
    """The Lua that installs the tally `tally_id` over `width` bytes at `addr`, dumping to
    `path`. One chunk, so `local`s hold across its lines, on `cpu` (`mtap.bound_cpu`). THE TAP
    IS INSTALLED OVER THE BUS WORDS the range touches and the callback keeps only the writes that
    LAND inside it: MAME refuses a tap whose ends are not bus-aligned (a one-byte tap
    on the 16-bit 68000 bus answers "end address has low bits unset"), and a word write next to
    the range would otherwise count for it. The value key packs the masked data and the
    mask into one integer under the offset, so a write costs no string. WITH NO TAP OF THE
    RANGE IN THE REGISTRY, a dump at `path` is a removed tap's (the dumper rewrites it at every
    stop until the removal runs), so the install deletes it and the first dump read after it
    is this tap's; with one there, the install carries its counts and the file says the same."""
    last = addr + width - 1
    dumper = f"""  local function dump(it, fr)
    if not it.dirty and it.dumped_frame == fr then return end
    it.seq = it.seq + 1
    local f = {callbacks.OPENED}(it, io.open(it.path .. ".tmp", "w"))
    if f == nil then return end
    f:write(string.format("{HEADER} %s seq=%d frame=%d total=%d values=%d pcs=%d ",
      it.id, it.seq, fr, it.total, it.nvalues, it.npcs))
    f:write(string.format("overflow_values=%d overflow_pcs=%d data_width=%d ",
      it.overflow_values, it.overflow_pcs, it.data_width))
    f:write(string.format("endianness=%s cpu=%s errors=%d\\n", it.endianness, it.cpu,
      it.errors))
    for offset, at in pairs(it.values) do
      for k, c in pairs(at) do
        f:write(string.format("v %x %x %x %d\\n", offset, (k >> 32) & 0xffffffff,
                              k & 0xffffffff, c))
      end
    end
    for pc, c in pairs(it.pcs) do f:write(string.format("p %x %d\\n", pc, c)) end
    if it.first_error ~= nil then f:write("e ", it.first_error, "\\n") end
    f:write("end\\n")
    f:close()
    os.rename(it.path .. ".tmp", it.path)
    it.dirty = false
    it.dumped_frame = fr
  end
  dump_at_stops(T, dump)
"""
    return mtap.tap_prelude(REGISTRY) + f"""\
local id, first, last = {transport.lua_string(tally_id)}, {addr:#x}, {last:#x}
local path = {transport.lua_string(str(path))}
{mtap.bound_cpu(cpu)}
local sp = cpu.spaces[{transport.lua_string(space)}]
local curpc = cpu.state["CURPC"]
{mtap.REMOVE_OLD_TAP}
local t = {{id = id, path = path, total = 0, values = {{}}, nvalues = 0, pcs = {{}}, npcs = 0,
  overflow_values = 0, overflow_pcs = 0, errors = 0, dirty = true, seq = 0,
  dumped_frame = {callbacks.NO_FRAME},
  data_width = sp.data_width, endianness = sp.endianness, cpu = cpu.tag}}
if old ~= nil then
  for _, k in ipairs({{"total", "values", "nvalues", "pcs", "npcs", "overflow_values",
                       "overflow_pcs", "errors", "first_error", "seq"}}) do t[k] = old[k] end
end
if old == nil then os.remove(path) os.remove(path .. ".tmp") end
local nb = sp.data_width // 8
local big = sp.endianness == "big"
local lo, hi = first - (first % nb), last + (nb - 1 - (last % nb))
local aligned = lo == first and hi == last
local function lands(offset, mask)
  for i = 0, nb - 1 do
    local shift = big and (nb - 1 - i) * 8 or i * 8
    if ((mask >> shift) & 0xff) ~= 0 and offset + i >= first and offset + i <= last then
      return true
    end
  end
  return false
end
t.tap = sp:install_write_tap(lo, hi, "mcp_tally_" .. id, guarded(t, function(offset, data, mask)
  if not aligned and not lands(offset, mask) then return end
  t.total = t.total + 1
  local at = t.values[offset]
  if at == nil then at = {{}} t.values[offset] = at end
  local k = ((data & mask) << 32) | mask
  local c = at[k]
  if c ~= nil then at[k] = c + 1
  elseif t.nvalues < {BUCKETS_MAX} then at[k] = 1 t.nvalues = t.nvalues + 1
  else t.overflow_values = t.overflow_values + 1 end
  local pc = curpc.value
  local p = t.pcs[pc]
  if p ~= nil then t.pcs[pc] = p + 1
  elseif t.npcs < {BUCKETS_MAX} then t.pcs[pc] = 1 t.npcs = t.npcs + 1
  else t.overflow_pcs = t.overflow_pcs + 1 end
  t.dirty = true
end))
T.items[id] = t
{mtap.register_dumper_once(dumper)}
print(string.format("{mtap.ANSWER_PREFIX} installed tally_id=%s first=%x last=%x ", id, first, last)
  .. string.format("data_width=%d endianness=%s cpu=%s", sp.data_width, sp.endianness, cpu.tag))"""


def send_install(scratch: Path, owner: dec.Owner, addr: int, width: int,
                 space: str = "program") -> dict[str, Any]:
    """Put the count watch's install for `owner` in the pipe, on its cpu and in `space`, and
    record it (`mtap.send_tap`)."""
    cpu = owner[1]
    tally_id = id_for(cpu, addr, width, space)
    path = dump_path(scratch, tally_id)
    return mtap.send_tap(scratch, owner, tally_id,
                         install_script(tally_id, addr, width, path, cpu, space),
                         REGISTRY, [path], addr=addr, width=width, path=path, space=space)


def parse_dump(text: str) -> dict[str, Any] | None:
    """A dump as the periodic wrote it, or None when the text is not a whole dump (a header
    this reader does not know, or no `end` line): a half-read table is not a table."""
    whole = callbacks.read_whole(text, _HEAD, with_body=True)
    if whole is None:
        return None
    head, body, errors = whole
    values: list[tuple[int, int, int, int]] = []
    pcs: list[tuple[int, int]] = []
    for ln in body:
        if (v := _VALUE.match(ln)) is not None:
            values.append((int(v.group(1), 16), int(v.group(2), 16), int(v.group(3), 16),
                           int(v.group(4))))
        elif (p := _PC.match(ln)) is not None:
            pcs.append((int(p.group(1), 16), int(p.group(2))))
        else:
            return None
    return {"id": head.group(1), "seq": int(head.group(2)), "frame": int(head.group(3)),
            "total": int(head.group(4)), "values": values, "pcs": pcs,
            "overflow_values": int(head.group(7)), "overflow_pcs": int(head.group(8)),
            "data_width": int(head.group(9)), "endianness": head.group(10),
            "cpu": head.group(11), **errors}


def lanes(offset: int, data: int, mask: int, data_width: int,
          endianness: str) -> list[tuple[int, int]]:
    """The bytes a bus write LANDED, as (address, byte) in address order: the mask names
    the lanes, and on a big-endian bus the high lane is the lowest address."""
    out: list[tuple[int, int]] = []
    for i in range(data_width // 8):
        shift = mspace.lane_shift(i, 1, data_width, endianness)
        if (mask >> shift) & 0xFF:
            out.append((offset + i, (data >> shift) & 0xFF))
    return out


def _value_rows(dump: dict[str, Any], addr: int, width: int, fmt: str,
                shown: int) -> list[dict[str, Any]]:
    """The value table, most written first: each bus write decoded to the bytes it landed
    and, when one write covers the declared range whole, the `value` in the watch's own
    format, in the byte order of the space the tap sat on, which the dump itself names. A
    write that lands part of the range is `partial` with the bytes it wrote."""
    rows: list[dict[str, Any]] = []
    ranked = sorted(dump["values"], key=lambda r: (-r[3], r[0], r[1]))
    for offset, data, mask, count in ranked[:shown]:
        landed = lanes(offset, data, mask, dump["data_width"], dump["endianness"])
        inside = [(a, b) for a, b in landed if addr <= a < addr + width]
        row: dict[str, Any] = {"at": st.hex_addr(inside[0][0] if inside else offset),
                               "raw_hex": bytes(b for _a, b in inside).hex(), "count": count}
        if [a for a, _b in inside] == list(range(addr, addr + width)):
            try:
                row["value"] = vf.parse(fmt).decode(bytes(b for _a, b in inside),
                                                    dump["endianness"], width)
            except vf.FormatError:
                row["partial"] = True
        else:
            row["partial"] = True
        rows.append(row)
    return rows


def _writer_rows(dump: dict[str, Any], shown: int) -> list[dict[str, Any]]:
    """The writer table, most frequent first, each pc placed inside the nearest symbol
    below it when the table has one."""
    rows: list[dict[str, Any]] = []
    for pc, count in sorted(dump["pcs"], key=lambda r: (-r[1], r[0]))[:shown]:
        rows.append(read.add_symbol({"pc": st.hex_addr(pc), "count": count}, pc,
                                    dump.get("cpu")))
    return rows


def evaluate(scratch: Path, owner: dec.Owner, width: int, fmt: str,
             frame: int | None, shown: int, at_stop: bool) -> dict[str, Any]:
    """What a stop survey or `watch_list` says about the tally under `owner` (`mtap.read_tap`), and
    once it has a dump, its value and writer tables."""
    item, dump = mtap.read_tap(scratch, owner, frame, at_stop, parse_dump, "tallied")
    if dump is None:
        return item
    rec = STATE.tallies[owner]
    item.update(values=_value_rows(dump, rec["addr"], width, fmt, shown),
                values_total=len(dump["values"]), overflow_values=dump["overflow_values"],
                writers=_writer_rows(dump, shown), writers_total=len(dump["pcs"]),
                overflow_pcs=dump["overflow_pcs"])
    return item


def check_count_watch(chosen: str, mode: str = "count") -> None:
    """A count or capture watch is by symbol or by address: a tap follows no pointer (it sits
    on one range for its life, and a range that moves under it would count, or read, the wrong
    bytes in silence), and an expression is no range at all."""
    if chosen not in ("symbol", "address"):
        raise st.Invalid("bad_argument",
                         f"a {mode} watch is declared by symbol or by address, not by {chosen}: "
                         "the tap sits on one range for its life, so "
                         f"`watch_add(ref=<symbol or address>, mode=\"{mode}\")`")


def bus_unchecked_note(space: str) -> str:
    """What `watch_add`'s count reply adds when its cpu's bus width in `space` is unknown."""
    return (f"`start` gathered no {space} space for this cpu, so whether the range splits a bus "
            "word was not checked")


def split_why(addr: int, width: int, data_width: int, cpu: str | None,
              space: str = mspace.PROGRAM) -> str:
    """The refusal of a count range that `mspace.splits_bus_word`, naming the counts that work:
    one per bus word the range touches, each written whole by one write, on the range's cpu and
    in its space."""
    nb = data_width // 8
    pieces: list[tuple[int, int]] = []
    at, end = addr, addr + width
    while at < end:
        stop = min(end, at - at % nb + nb)
        pieces.append((at, stop - at))
        at = stop
    on = (f', cpu="{cpu}"' if cpu is not None and cpu != STATE.first_cpu else "") + (
        "" if space == mspace.PROGRAM else f', space="{space}"')
    (first, first_n), rest = pieces[0], [f"{a:#x} (length={n})" for a, n in pieces[1:]]
    others = (", ".join(rest) if len(rest) <= 3
              else f"{rest[0]}, every bus word after it, and {rest[-1]}")
    return (f"{prose.counted(width, 'byte')} at {addr:#x} split a {data_width}-bit bus word: a "
            "write lands in one bus word, so the rows of a word the range covers only in part are "
            "fragments, `partial` with no `value`; declare one count per bus word it touches, "
            "each then written whole: "
            f'`watch_add(ref="{first:#x}", mode="count", length={first_n}{on})` '
            f"and the same at {others}")
