"""`gfx_view`: bytes as a picture, under a format stated in MAME's own `gfx_layout` terms
(`mame_layout`), and the reader of the bytes a layout is stated over, which `gfx_locate` shares.

THE BYTES ARE THE BLOCK'S IN LOGICAL ORDER. `region:read` is a copy of the host-order memory, so
a region whose endianness is not the host's comes back with each word's bytes swapped; MAME's
decoder undoes that with an `xormask` on the bit address, and this module undoes it on the bytes,
which is the same thing. A share is read a byte at a time through `read_u8`, which answers in
logical order already (stock Lua binds no bulk read for a share), and a range of a cpu's program
space through `read_range`, byte by byte in the order that cpu addresses them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core import png, prose
from scry_core import progress as mprogress
from scry_core import vocabulary as vocab

import gdb_session as gs
import mame_block as block
import mame_chunk as chunk
import mame_cpus as cpus
import mame_inputs as inputs
import mame_layout as ml
import mame_lua as mlua
import mame_manifest as manifest
import mame_palette as mpalette
import mame_region as region
import mame_running as running
import mame_state as st
import mame_transport as transport
from mame_state import STATE

VIEW_TILES_MAX = 1024
COLUMNS_MAX = 64
TILE_PIXELS_MAX = 1 << 20      # the pixels one call decodes
BLOCK_BYTES_MAX = 64 << 20     # a block read whole into a file
# A SHARE IS READ A BYTE AT A TIME (stock Lua binds no bulk read for one), so its bound is the size
# that loop dumps well inside the console's default wait on the slowest host in use, not the
# region's: past it the chunk would time out rather than be refused by its size.
SHARE_BYTES_MAX = 4 << 20


# ------------------------------------------------------------------ the bytes

@dataclass
class Block:
    """The bytes a layout is read over, in logical order, and where they came from."""

    kind: str                  # `region`, `share` or `space`
    tag: str
    size: int                  # the whole block's bytes (the span's, for `space`)
    bytewidth: int
    endianness: str
    data: bytes                # from byte 0 of the block (of the span, for `space`)


BLOCK_LUA = """local function mcp_block(path, name, addr, length)
  local mem = manager.machine.memory
  local kind, tag, blk
  if addr then
    local space = %(space)s.spaces["program"]
    local data = space:read_range(addr, addr + length - 1, 8)
    local f = assert(io.open(path, "wb")) f:write(data) f:close()
    print(string.format("MAME_MCP_GFX_BLOCK kind=space tag=%%s size=%%d bytewidth=%%d endian=%%s",
                        space.name, #data, space.data_width // 8, tostring(space.endianness)))
    return true
  end
  for _, cand in ipairs({name, ":" .. name}) do
    if mem.regions[cand] then kind, tag, blk = "region", cand, mem.regions[cand] break end
    if mem.shares[cand] then kind, tag, blk = "share", cand, mem.shares[cand] break end
  end
  if kind == nil then
    local t = {}
    for k in pairs(mem.shares) do t[#t + 1] = k .. "=share" end
    for k in pairs(mem.regions) do t[#t + 1] = k .. "=region" end
    table.sort(t)
    print("MAME_MCP_GFX_BLOCK_NONE name=" .. name .. " tags=" .. table.concat(t, ","))
    return nil
  end
  if blk.size > (kind == "share" and %(share_max)d or %(bytes_max)d) then
    print(string.format("MAME_MCP_GFX_BLOCK_BIG kind=%%s tag=%%s size=%%d", kind, tag, blk.size))
    return nil
  end
  local data
  if kind == "region" then
    data = blk:read(0, blk.size)
  else
    local parts, bytes = {}, {}
    for i = 0, blk.size - 1 do
      bytes[#bytes + 1] = blk:read_u8(i)
      if #bytes == 4096 then parts[#parts + 1] = string.char(table.unpack(bytes)) bytes = {} end
    end
    if #bytes > 0 then parts[#parts + 1] = string.char(table.unpack(bytes)) end
    data = table.concat(parts)
  end
  local f = assert(io.open(path, "wb")) f:write(data) f:close()
  print(string.format("MAME_MCP_GFX_BLOCK kind=%%s tag=%%s size=%%d bytewidth=%%d endian=%%s",
                      kind, tag, blk.size, blk.bytewidth, tostring(blk.endianness)))
  return true
end
"""
_BLOCK = re.compile(r"MAME_MCP_GFX_BLOCK kind=(\w+) tag=(\S+) size=(\d+) bytewidth=(\d+) "
                    r"endian=(\w+)")
_BLOCK_NONE = re.compile(r"MAME_MCP_GFX_BLOCK_NONE name=(\S+) tags=(\S*)")
_BLOCK_BIG = re.compile(r"MAME_MCP_GFX_BLOCK_BIG kind=(\w+) tag=(\S+) size=(\d+)")


def block_call(path: Path, tag: str, addr: int | None, length: int) -> str:
    """The Lua call that dumps the block (or the `space` range) into `path`."""
    return (f"mcp_block({transport.lua_string(str(path))}, {transport.lua_string(tag)}, "
            f"{'nil' if addr is None else addr}, {length})")


def block_lua(ses: gs.Session, cpu: str) -> str:
    """`BLOCK_LUA` bound to the program space of `cpu`, the visible one when empty (as
    `read_block` binds it)."""
    return BLOCK_LUA % {"space": block.space_of(ses, cpu), "bytes_max": BLOCK_BYTES_MAX,
                        "share_max": SHARE_BYTES_MAX}


def parse_block(text: str, path: Path, common: dict[str, Any]) -> Block:
    """The block the console announced and the file it wrote, in logical order; the file is
    gone after."""
    try:
        if (m := _BLOCK_NONE.search(text)) is not None:
            have = dict(item.split("=", 1) for item in m.group(2).split(",") if "=" in item)
            raise st.Invalid("unknown_ref", block.no_block(m.group(1), have), tags=have,
                             **common)
        if (m := _BLOCK_BIG.search(text)) is not None:
            share = m.group(1) == "share"
            raise st.Invalid("bad_argument", f"{m.group(1)} {m.group(2)} is "
                             f"{int(m.group(3)):#x} bytes, past the "
                             + (f"{SHARE_BYTES_MAX:#x} a share is read in, a byte at a time"
                                if share else f"{BLOCK_BYTES_MAX:#x} read whole into a file"),
                             size=int(m.group(3)), **common)
        m = _BLOCK.search(text)
        if m is None:
            chunk.no_line("dump", text, common)
        kind, tag, size, width, endian = (m.group(1), m.group(2), int(m.group(3)),
                                          int(m.group(4)), m.group(5))
        raw = path.read_bytes() if path.is_file() else b""
        if len(raw) != size:
            raise st.Invalid("unexpected_answer", f"the dump of {tag} holds "
                                                  f"{prose.counted(len(raw), 'byte')} and "
                             f"the console said {size}", **common)
    finally:
        path.unlink(missing_ok=True)
    data = region.logical(raw, width, endian) if kind == "region" else raw
    return Block(kind, tag, size, width, endian, data)


def read_with_pens(ses: gs.Session, scratch: Path, cpu: str, tag: str, addr: int | None,
                   length: int, palette: str, pen_base: int, depth: int, seconds: float,
                   progress: mprogress.Progress, what: str) -> tuple[str, dict[str, Any], Block]:
    """ONE evaluation that dumps a block (`block_call`'s arguments) and, unless `palette` is
    `none`, reads `depth` pens of it from `pen_base`: the console's text, its account, and the
    block. The pens are parsed from the text by `mame_palette.parse_pens`."""
    real = palette != "none"
    path = chunk.next_file(scratch, "block")
    script = (block_lua(ses, cpu) + (mpalette.PENS_LUA if real else "")
              + f"if {block_call(path, tag, addr, length)} then\n"
              + (mpalette.pens_call(palette, pen_base, depth) if real else "") + "\nend\n")
    try:
        text, common = chunk.run(ses, scratch, script, seconds, progress, what)
    except BaseException:
        path.unlink(missing_ok=True)       # whatever went wrong, nothing else removes the dump
        raise
    return text, common, parse_block(text, path, common)


# ------------------------------------------------------------------ the checks both tools share

def check_source(tag: str, ref: str, offset: int, count: int,
                 layouts: list[ml.Layout], cpu: str = "") -> None:
    """One source per call: a block by `tag` with `offset` into it, or `ref` in a cpu's space,
    which is a fraction of nothing (no `RGN_FRAC`) and has no end of its own (`count` named)."""
    if bool(tag) == inputs.given(ref):
        raise st.Invalid("bad_argument", "one source per call: `tag` (a region or share, `gfx1` "
                         "or `:gfx1`) or `ref` (an address in a cpu's program space), not both, "
                         "not neither")
    block.check_tag(tag, cpu)
    if inputs.given(ref):
        inputs.check_ref(ref)
        if offset:
            inputs.idle("offset", "tag", "with `ref` the address is where the first tile starts")
        if any(lay.needs_block for lay in layouts):
            raise st.Invalid("bad_argument", "a layout uses RGN_FRAC, a fraction of a block's "
                             "length, and a range of a cpu's space is no block: name the region "
                             "or share with `tag`")
        if not count:
            raise st.Invalid("bad_argument", "with `ref` name `count`: a range of a cpu's space "
                             "has no end of its own to stop at")
    block.check_offset(offset)


def check_first(first: int) -> None:
    inputs.natural("first", first, " is not a tile number")


def check_count(count: int, most: int) -> None:
    """A tile count: 0 for every tile the block holds (at most `most`), or 1..`most`."""
    inputs.natural("count", count, f": 0 takes every tile the block holds (at most {most}), or "
                   f"name 1..{most}", hi=most)


def span(ses: gs.Session, lay: ml.Layout, ref: str, first: int, count: int,
         cpu: str) -> tuple[int | None, int, str]:
    """For a `ref`, the address of tile 0, how many bytes reach the end of the last tile asked
    for, and the cpu whose space that is; for a `tag`, none: the block is read whole, because
    `RGN_FRAC` is a fraction of all of it."""
    if not ref.strip():
        return None, 0, ""
    try:
        res = ml.resolve(lay, None)
    except ml.LayoutError as e:
        raise st.Invalid("bad_argument", str(e)) from None
    _, hi = res.tile_bits()
    length = ((first + count - 1) * res.charincrement + hi) // 8 + 1
    if length > BLOCK_BYTES_MAX:
        raise st.Invalid("bad_argument", f"tiles {first}..{first + count - 1} reach {length:#x} "
                         f"bytes from `ref`, past the {BLOCK_BYTES_MAX:#x} read into a file")
    on = cpus.chosen(ses, cpu)
    return STATE.resolve(ref, on), length, on or ""


def resolved_for(lay: ml.Layout, blk: Block, common: dict[str, Any]) -> ml.Resolved:
    """`lay` for the block that came back, as a refusal when it does not resolve."""
    try:
        return ml.resolve(lay, None if blk.kind == "space" else blk.size * 8)
    except ml.LayoutError as e:
        raise st.Invalid("bad_argument", str(e), **common) from None


def source_fields(blk: Block, start: int, addr: int | None, on: str) -> dict[str, Any]:
    """Where the bytes came from, as both tools' replies say it."""
    out: dict[str, Any] = {"kind": blk.kind, "tag": blk.tag, "size": blk.size,
                           "bytewidth": blk.bytewidth, "endianness": blk.endianness,
                           "offset": start}
    if addr is not None:
        out.update(addr=st.hex_addr(addr), addr_cpu=on)
    return out


# ------------------------------------------------------------------ the tool

def check_gfx_view(layout: Any = None, palette: str = "none", tag: str = "", ref: str = "",
                   offset: int = 0, first: int = 0, count: int = 0, columns: int = 16,
                   pen_base: int = 0, scale: int = 0, dest: str = "",
                   seconds: float = mlua.EVAL_WAIT_S, cpu: str = "", attach: bool = True,
                   **_: Any) -> tuple[ml.Layout | None, Path | None]:
    """`gfx_view`'s machine-independent half: the layout whole, the source, the tiles, the
    palette's name and base, and the picture's own arguments; handed back parsed and built. A
    layout NAMED by the manifest comes back None: the body resolves it past the gate."""
    vocab.check_wait(seconds)
    lay = manifest.layout_arg(layout, resolve=False)
    check_source(tag, ref, offset, count, [lay] if lay else [], cpu)
    check_first(first)
    check_count(count, VIEW_TILES_MAX)
    inputs.count("columns", columns, COLUMNS_MAX)
    if palette:
        inputs.name_word("palette", palette, "no palette is invented: a palette device's tag "
                         "(`palette`), empty for the machine's only one, or `none` for a grey "
                         "ramp that says it is not the machine's colours")
    check_pen_base(palette, pen_base)
    return lay, inputs.picture_args(scale, dest, attach)


def check_pen_base(palette: str, pen_base: int) -> None:
    """The first pen a palette is read from: a pen, and only with a device to read it from."""
    inputs.pen("pen_base", pen_base)
    if palette == "none" and pen_base:
        raise st.Invalid("bad_argument", "pen_base picks pens of a device; with palette `none` "
                         "there are none")


def grey_ramp(planes: int) -> list[tuple[int, int, int]]:
    """`palette="none"`: `2^planes` evenly spaced greys, black to white."""
    top = (1 << planes) - 1
    return [(g, g, g) for g in (round(i * 255 / top) for i in range(top + 1))]


def gfx_view(ses: gs.Session, scratch: Path, layout: Any, palette: str, tag: str, ref: str,
             offset: int, first: int, count: int, columns: int, pen_base: int, scale: int,
             dest: str, cpu: str, seconds: float,
             progress: mprogress.Progress = mprogress.no_progress,
             attach: bool = True) -> dict[str, Any]:
    """The body of the `gfx_view` tool: ONE evaluation reads the source and the pens."""
    lay, dest_path = check_gfx_view(layout, palette, tag, ref, offset, first, count, columns,
                                    pen_base, scale, dest, seconds, cpu, attach)
    if lay is None:
        lay = manifest.named_layout(layout)
        check_source(tag, ref, offset, count, [lay], cpu)
    addr, length, on = span(ses, lay, ref, first, count, cpu)
    depth = 1 << lay.planes.const
    real = palette != "none"
    text, common, blk = read_with_pens(ses, scratch, cpu, tag, addr, length, palette, pen_base,
                                       depth, seconds, progress, "gfx_view")
    res = resolved_for(lay, blk, common)
    # the pens first: a palette the machine lacks is named before the tiles are judged
    pal_tag, colours = (mpalette.parse_pens(text, palette, pen_base, depth, common) if real
                        else ("none", grey_ramp(res.planes)))
    start = offset if tag else 0
    avail = ml.available(res, blk.size * 8, start)
    n = count or min(max(avail - first, 0), VIEW_TILES_MAX)
    if n < 1 or first + n > avail:
        raise st.Invalid("bad_argument", f"tiles {first}..{first + max(n, 1) - 1} are not all "
                         f"inside {blk.kind} {blk.tag} ({blk.size:#x} bytes), which holds "
                         f"{prose.counted(avail, 'whole tile')} of this layout from offset "
                         f"{start:#x}",
                         size=blk.size, tiles_available=avail, **common)
    if n * res.width * res.height > TILE_PIXELS_MAX:
        raise st.Invalid("bad_argument", f"{prose.counted(n, 'tile')} of {res.width}x{res.height} "
                         f"{prose.agrees(n, 'is', 'are')} "
                         f"{prose.counted(n * res.width * res.height, 'pixel')}, past the "
                         f"{TILE_PIXELS_MAX} one call decodes: narrow `count`", **common)
    cols = min(columns, n)
    width, height = cols * res.width, -(-n // cols) * res.height
    canvas = bytearray(width * height)
    for k in range(n):
        tx, ty = (k % cols) * res.width, (k // cols) * res.height
        pix = ml.decode(res, blk.data, start, first + k)
        for y in range(res.height):
            at = (ty + y) * width + tx
            canvas[at:at + res.width] = bytes(pix[y * res.width:(y + 1) * res.width])
    fields: dict[str, Any] = {
        "layout": res.as_reply(), **source_fields(blk, start, addr, on),
        "first": first, "count": n, "tiles_available": avail, "columns": cols,
        "palette": pal_tag, "pen_base": pen_base, "real_colors": real,
    }
    if not real:
        fields["note"] = ("palette `none`: a grey ramp over the pixel values, NOT the machine's "
                          "colours; the PNG's index is the pixel value either way")
    fields["image"] = st.publish(png.Raster(width, height, bytes(canvas), tuple(colours)),
                                 scale, dest_path, scratch, "gfx", attach=attach)
    return running.stop_reply(ses, scratch, f"gfx_view: {common['evaluated_by']}",
                              **st.merged(fields, common))
