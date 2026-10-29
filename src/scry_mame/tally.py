"""A watch that COUNTS: every write to a range over a pass, by value and by writer, never
stopping for one.

A change watch stops at the first write; a census needs every value a register takes over a
pass and from which pcs. `disarm_watches` disarms change watches, so a held pass counts nothing.

`space:install_write_tap` calls its function once per BUS write with offset, data and lane
mask: a `move.l` arrives as two word events, a `move.b` as a word with the mask naming the
lane that lands. `cpu.state["CURPC"]` in the callback is the writing instruction's own pc
(`PC` is the prefetch, two bytes on). `emu.register_periodic` also runs at debugger stops,
where each tally is written whole to a file in the scratch through a rename. The tap and the
registry live in the MAME process's `_G`: a new `start` begins clean, `rearm` reinstalls.

Idempotent by id: the console reruns an earlier chunk after its reader dies
(`console_reruns`), so an install removes the tap held under its id and carries its counts
into the new one; `declaration_clear(kind="watch")` removes the tap, so the next declaration
starts from zero. Sending, proving, removing and reading a tap is `tap`.

The callback is the hot path (hundreds of thousands of writes per line): the writer's state
entry is looked up once at install, the value key is an integer, and a bus-aligned range
skips the lane test.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scry_core import bus_writes, prose

from scry_mame import callbacks, read, transport
from scry_mame import declarations as dec
from scry_mame import space as mspace
from scry_mame import state as st
from scry_mame import tap as mtap
from scry_mame.state import STATE

REGISTRY = "MCP_TALLY"
# Past the cap a write still counts in `total` and `overflow_*`, so a cut table says so.
BUCKETS_MAX = 256
HEADER = "MCP_TALLY"
_HEAD = re.compile(
    rf"^{HEADER} (\S+) seq=(\d+) frame=(-?\d+) total=(\d+) values=(\d+) pcs=(\d+) "
    r"overflow_values=(\d+) overflow_pcs=(\d+) data_width=(\d+) endianness=(\w+) cpu=(\S+)$")
_VALUE = re.compile(r"^v ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+) (\d+)$")
_PC = re.compile(r"^p ([0-9a-f]+) (\d+)$")


def id_for(cpu: str | None, addr: int, width: int, space: str = "program") -> str:
    """The `tally_id` of a range on its cpu and space, also the dump's file name (hence no
    colons in a cpu tag); the first cpu's id is the range alone, and a space other than
    the program's is suffixed (`@io`)."""
    tag = "" if cpu in (None, STATE.first_cpu) else "_" + str(cpu).strip(":").replace(":", ".")
    return f"{addr:x}_{width}{tag}{mspace.suffix(space)}"


def dump_path(scratch: Path, tally_id: str) -> Path:
    return scratch / f"tally-{tally_id}.txt"


def install_script(tally_id: str, addr: int, width: int, path: Path,
                   cpu: str | None = None, space: str = "program") -> str:
    """The one-chunk Lua that installs the tally over `width` bytes at `addr` on `cpu`.

    The tap covers the bus words the range touches (MAME refuses a tap not bus-aligned: "end
    address has low bits unset") and the callback keeps only writes that land inside. The
    value key packs masked data and mask into one integer. With no tap of the range in the
    registry, a dump at `path` is a removed tap's, so the install deletes it."""
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
    replace(it.path .. ".tmp", it.path)
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
    """Send the count watch's install for `owner` (`mtap.send_tap`)."""
    cpu = owner[1]
    tally_id = id_for(cpu, addr, width, space)
    path = dump_path(scratch, tally_id)
    return mtap.send_tap(scratch, owner, tally_id,
                         install_script(tally_id, addr, width, path, cpu, space),
                         REGISTRY, [path], addr=addr, width=width, path=path, space=space)


def parse_dump(text: str) -> dict[str, Any] | None:
    """A dump as the periodic wrote it, or None when not whole (unknown header, no `end`)."""
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


def _value_rows(dump: dict[str, Any], addr: int, width: int, fmt: str,
                shown: int) -> list[dict[str, Any]]:
    """The value table in the byte order the dump names (`bus_writes.value_rows`)."""
    return bus_writes.value_rows(dump["values"], addr, width, fmt, dump["data_width"],
                                 dump["endianness"], shown, st.hex_addr)


def _writer_rows(dump: dict[str, Any], shown: int) -> list[dict[str, Any]]:
    """The writer table, most frequent first, each pc placed in the nearest symbol below."""
    rows: list[dict[str, Any]] = []
    for pc, count in sorted(dump["pcs"], key=lambda r: (-r[1], r[0]))[:shown]:
        rows.append(read.add_symbol({"pc": st.hex_addr(pc), "count": count}, pc,
                                    dump.get("cpu")))
    return rows


def evaluate(scratch: Path, owner: dec.Owner, width: int, fmt: str,
             frame: int | None, shown: int, at_stop: bool) -> dict[str, Any]:
    """What a stop survey or `declaration_list(kind="watch")` says about the tally under
    `owner`, with its value and writer tables once it has a dump."""
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
    """A count or capture watch is by symbol or address: a tap follows no pointer, so a
    moving range would be counted wrong in silence."""
    if chosen not in ("symbol", "address"):
        raise st.Invalid("bad_argument",
                         f"a {mode} watch is declared by symbol or by address, not by {chosen}: "
                         "the tap sits on one range for its life, so "
                         f"`watch_add(ref=<symbol or address>, mode=\"{mode}\")`")


def bus_unchecked_note(space: str) -> str:
    """What `watch_add`'s count reply adds when the bus width in `space` is unknown."""
    return (f"`start` gathered no {space} space for this cpu, so whether the range splits a bus "
            "word was not checked")


def split_why(addr: int, width: int, data_width: int, cpu: str | None,
              space: str = mspace.PROGRAM) -> str:
    """The refusal of a range that `mspace.splits_bus_word`, naming one count per bus word."""
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
