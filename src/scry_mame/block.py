"""`read_block`: the bytes of a memory SHARE or REGION, by MAME's tag or by an address.

`read_memory` reads the cpu's program space, where a write-only block (`.w(handler).share("x")`)
is invisible: it answers zero for every byte and nothing says the values live elsewhere. A ROM
outside the cpu's space (`gfx1`) is not there at all. Both are blocks under
`manager.machine.memory`, read through the Lua console.

`shares` and `regions` are keyed by the FULL tag (`:blitram`; bare `blitram` is nil), while a map
entry names its share bare and a caller's `tag` comes in either spelling, so a lookup tries both.
A read past a block's `size` answers zero without raising, so the bound is judged here. The
`ref` form walks the program space of the cpu the call names, else the visible one.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scry_core import progress as mprogress
from scry_core import vocabulary as vocab

from scry_mame import chunk, cpus, inputs, read, running, transport
from scry_mame import gdb_session as gs
from scry_mame import lua as mlua
from scry_mame import state as st
from scry_mame.state import STATE

# Each printed shape has its own prefix, so a refusal is not misread as a missing hex field.
# `%%` is a literal per cent for Lua's `string.format`.
BLOCK_LUA = """local mem = manager.machine.memory
local function block(name)
  for _, cand in ipairs({name, ":" .. name}) do
    if mem.shares[cand] then return "share", cand, mem.shares[cand] end
    if mem.regions[cand] then return "region", cand, mem.regions[cand] end
  end
  return nil
end
local function tags()
  local t = {}
  for tag in pairs(mem.shares) do t[#t + 1] = tag .. "=share" end
  for tag in pairs(mem.regions) do t[#t + 1] = tag .. "=region" end
  table.sort(t)
  return table.concat(t, ",")
end
local kind, tag, blk, start
local offset = %(offset)d
local addr = %(addr)s
if addr then
  local space = %(space)s.spaces["program"]
  local hit = nil
  for _, e in ipairs(space.map.entries) do
    if e.address_start <= addr and addr <= e.address_end then hit = e break end
  end
  if hit == nil then
    print(string.format("MAME_MCP_BLOCK_NOENTRY addr=%%x", addr))
  elseif hit.share == nil and hit.region == nil then
    print(string.format("MAME_MCP_BLOCK_NOBLOCK start=%%x end=%%x", hit.address_start,
                        hit.address_end))
  else
    kind, tag, blk = block(hit.share or hit.region)
    if kind == nil then
      print("MAME_MCP_BLOCK_NONE name=" .. (hit.share or hit.region) .. " tags=" .. tags())
    else
      start = hit.address_start
      offset = addr - start + (hit.share and 0 or (hit.region_offset or 0))
    end
  end
else
  kind, tag, blk = block(%(tag)s)
  if kind == nil then print("MAME_MCP_BLOCK_NONE name=" .. %(tag)s .. " tags=" .. tags()) end
end
if kind then
  local length = %(length)d
  if offset + length > blk.size then
    print(string.format("MAME_MCP_BLOCK_OUTSIDE kind=%%s tag=%%s size=%%d offset=%%d length=%%d",
                        kind, tag, blk.size, offset, length))
  else
    local t = {}
    for i = offset, offset + length - 1 do t[#t + 1] = string.format("%%02x", blk:read_u8(i)) end
    print(string.format("MAME_MCP_BLOCK kind=%%s tag=%%s size=%%d bytewidth=%%d endian=%%s "
                        .. "start=%%s offset=%%d hex=%%s", kind, tag, blk.size, blk.bytewidth,
                        tostring(blk.endianness), start and string.format("%%x", start) or "-",
                        offset, table.concat(t)))
  end
end
"""

_BLOCK = re.compile(r"MAME_MCP_BLOCK kind=(\w+) tag=(\S+) size=(\d+) bytewidth=(\d+) "
                    r"endian=(\w+) start=(\S+) offset=(\d+) hex=([0-9a-f]*)")
_NONE = re.compile(r"MAME_MCP_BLOCK_NONE name=(\S+) tags=(\S*)")
_OUTSIDE = re.compile(r"MAME_MCP_BLOCK_OUTSIDE kind=(\w+) tag=(\S+) size=(\d+) offset=(\d+) "
                      r"length=(\d+)")
_NOENTRY = re.compile(r"MAME_MCP_BLOCK_NOENTRY addr=([0-9a-f]+)")
_NOBLOCK = re.compile(r"MAME_MCP_BLOCK_NOBLOCK start=([0-9a-f]+) end=([0-9a-f]+)")


def no_block(name: str, have: dict[str, Any]) -> str:
    """The refusal sentence for a share or region the machine does not have."""
    return (f"no share or region named {name!r} in this machine; it has "
            f"{sorted(have) or 'none'}: `machine_map` lists each one")


def check_read_block(tag: str = "", ref: str = "", offset: int = 0, length: int = 16,
                     seconds: float = mlua.EVAL_WAIT_S, cpu: str = "", **_: Any) -> None:
    """`read_block`'s machine-independent argument checks."""
    if bool(tag) == inputs.given(ref):
        raise st.Invalid("bad_argument",
            "one block per call: `tag` (a share or region as MAME names it, `blitram` or "
            "`:blitram`) or `ref` (an address whose map entry names the block), not both, "
            "not neither")
    check_tag(tag, cpu)
    if inputs.given(ref):
        inputs.check_ref(ref)
        if offset:
            inputs.idle("offset", "tag", "with `ref` the offset is the address's distance into "
                        "the block, and the reply says what it came to")
    check_offset(offset)
    inputs.count("length", length, read.READ_MAX,
                   ": a block read answers hex into the reply, so it is bounded like "
                   "`read_memory`; walk a larger block in windows")
    vocab.check_wait(seconds)


def check_tag(tag: str, cpu: str = "") -> None:
    """Refuse a tag with whitespace (it would corrupt the parsed line) or a `cpu` beside it."""
    if tag:
        inputs.name_word("tag", tag, "a share, region or device as MAME names it")
        if inputs.cpu_given(cpu):
            inputs.idle("cpu", "ref", "a block named by `tag` is the machine's own, in no "
                        "cpu's space")


def check_offset(offset: int) -> None:
    inputs.natural("offset", offset, " is not a byte offset into a block")


def space_of(ses: gs.Session, cpu: str) -> str:
    """The Lua naming the cpu whose program space a `ref` is in: `cpu` bound at composition,
    else the visible cpu when the script runs."""
    on = cpus.chosen(ses, cpu)
    return (f"manager.machine.devices[{transport.lua_string(on)}]" if inputs.cpu_given(cpu) and on
            else "manager.machine.debugger.visible_cpu")


def _tags(joined: str) -> dict[str, str]:
    """The script's comma-joined `tag=kind` list as a map."""
    return dict(item.split("=", 1) for item in joined.split(",") if "=" in item)


def read_block(ses: gs.Session, scratch: Path, tag: str, ref: str, offset: int, length: int,
               seconds: float, progress: mprogress.Progress = mprogress.no_progress,
               cpu: str = "") -> dict[str, Any]:
    """The body of the `read_block` tool: one Lua evaluation, altering nothing."""
    check_read_block(tag, ref, offset, length, seconds, cpu=cpu)
    on = cpus.chosen(ses, cpu)
    addr = STATE.resolve(ref, on) if ref.strip() else None
    script = BLOCK_LUA % {"tag": transport.lua_string(tag), "addr": "nil" if addr is None else addr,
                          "offset": offset, "length": length, "space": space_of(ses, cpu)}
    text, common = chunk.run(ses, scratch, script, seconds, progress, "block")
    if (m := _NONE.search(text)) is not None:
        have = _tags(m.group(2))
        raise st.Invalid("unknown_ref", no_block(m.group(1), have), tags=have, **common)
    if (m := _OUTSIDE.search(text)) is not None:
        raise st.Invalid("bad_argument",
            f"offset {int(m.group(4)):#x} + length {int(m.group(5))} is past the end of "
            f"{m.group(1)} {m.group(2)}, which is {int(m.group(3)):#x} bytes long (MAME would "
            "answer zeros past it, in silence)",
            tag=m.group(2), kind=m.group(1), size=int(m.group(3)), **common)
    if (m := _NOENTRY.search(text)) is not None:
        raise st.Invalid("unknown_ref",
            f"{int(m.group(1), 16):#x} is inside no entry of the program space's address "
            "map: nothing is mapped there", addr=st.hex_addr(int(m.group(1), 16)), **common)
    if (m := _NOBLOCK.search(text)) is not None:
        raise st.Invalid("unknown_ref",
            f"the map entry {int(m.group(1), 16):#x}..{int(m.group(2), 16):#x} names no share "
            "and no region: its handlers keep their values where no block reads them, so "
            "`read_memory` (the read side) or a `count` watch (the writes) is what there is",
            map_entry={"start": st.hex_addr(int(m.group(1), 16)),
                       "end": st.hex_addr(int(m.group(2), 16))},
            **common)
    m = _BLOCK.search(text)
    if m is None:
        chunk.no_line("block", text, common)
    kind, name, size, bytewidth, endian, start, at, data = m.groups()
    fields: dict[str, Any] = {
        "kind": kind, "tag": name, "size": int(size), "bytewidth": int(bytewidth),
        "endianness": endian, "offset": int(at), "length": len(data) // 2, "hex": data,
    }
    if addr is not None:
        fields["addr"] = st.hex_addr(addr)
        fields["addr_cpu"] = on
        fields["start"] = st.hex_addr(int(start, 16))
    return running.stop_reply(ses, scratch, f"read_block: {common['evaluated_by']}",
                              **st.merged(fields, common))
