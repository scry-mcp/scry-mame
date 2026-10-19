"""`palette`: the live pens of a palette device, as a table and as a swatch.

WHY THE PALETTE DEVICE AND NOT MEMORY. On the boards this server drives, the colour RAM is not
where a reader could find it: a BT478 RAMDAC is write-only index and data ports, another board
keeps its colours in an array inside the driver. The one honest route is MAME's own palette
device, `manager.machine.palettes`, which holds the pens the screen is drawn with.

THE SWATCH. `ROW_PENS` pens a row, each a square of its colour, and the index of the row's first
pen written at its left in hexadecimal: a picture where a pen has to be counted across to be
named is a picture that gets the pen wrong.
"""

from __future__ import annotations

import re
import sys
from array import array
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

from scry_core import png
from scry_core import progress as mprogress

import gdb_session as gs
import mame_chunk as chunk
import mame_inputs as inputs
import mame_lua as mlua
import mame_prose as prose
import mame_running as running
import mame_state as st
import mame_transport as transport

COUNT_MAX = 256
ROW_PENS = 16
CELL = 8

PALETTE_LUA = """local pals = manager.machine.palettes
local names = {}
for tag in pairs(pals) do names[#names + 1] = tag end
table.sort(names)
local want = %(tag)s
local tag = nil
if want ~= "" then
  for _, cand in ipairs({want, ":" .. want}) do if pals[cand] then tag = cand break end end
  if tag == nil then
    print("MAME_MCP_PAL_NONE name=" .. want .. " palettes=" .. table.concat(names, ","))
    return
  end
elseif #names ~= 1 then
  print("MAME_MCP_PAL_NONE name=- palettes=" .. table.concat(names, ","))
  return
else
  tag = names[1]
end
local p = pals[tag]
local n = p.entries
local first, count = %(first)d, %(count)d
if first >= n or first + count > n then
  print(string.format("MAME_MCP_PAL_PAST tag=%%s entries=%%d", tag, n))
  return
end
if count == 0 then count = math.min(n - first, %(count_max)d) end
local pens, ind = {}, {}
for i = first, first + count - 1 do
  pens[#pens + 1] = string.format("%%08x", p:pen_color(i))
  if p.indirect_entries > 0 then ind[#ind + 1] = tostring(p:pen_indirect(i)) end
end
print(string.format("MAME_MCP_PAL tag=%%s entries=%%d indirect=%%d shadows=%%s highlights=%%s "
                    .. "first=%%d pens=%%s ind=%%s", tag, n, p.indirect_entries,
                    tostring(p.shadows_enabled), tostring(p.highlights_enabled), first,
                    table.concat(pens, ","), table.concat(ind, ",")))
"""
_PAL = re.compile(r"MAME_MCP_PAL tag=(\S+) entries=(\d+) indirect=(\d+) shadows=(\w+) "
                  r"highlights=(\w+) first=(\d+) pens=([0-9a-f,]*) ind=([0-9,]*)")
_NONE = re.compile(r"MAME_MCP_PAL_NONE name=(\S+) palettes=(\S*)")
_PAST = re.compile(r"MAME_MCP_PAL_PAST tag=(\S+) entries=(\d+)")

# A 3x5 font for the row labels, one string per glyph, rows top to bottom.
_GLYPHS = {
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111",
    "3": "111001111001111", "4": "101101111001001", "5": "111100111001111",
    "6": "111100111101111", "7": "111001001001001", "8": "111101111101111",
    "9": "111101111001111", "a": "111101111101101", "b": "110101110101110",
    "c": "111100100100111", "d": "110101101101110", "e": "111100111100111",
    "f": "111100111100100",
}
_GLYPH_W = 3
_INK, _PAPER = (255, 255, 255), (32, 32, 32)


def rgb_bytes(words: Sequence[int]) -> bytes:
    """THE ONE PEN-TO-RGB: ARGB words (a pen, a pixel of `pixels()`) as RGB triplets. The words
    are 32-bit in the host's order (`mame_screen`'s module docstring says why), so each channel
    is taken out of the words' bytes by position, one slice per channel over the whole run rather
    than three shifts per word."""
    raw = (words if isinstance(words, array) else array("I", words)).tobytes()
    r, g, b = (2, 1, 0) if sys.byteorder == "little" else (1, 2, 3)
    out = bytearray(len(raw) // 4 * 3)
    out[0::3], out[1::3], out[2::3] = raw[r::4], raw[g::4], raw[b::4]
    return bytes(out)


def pen_rgb(word: int) -> tuple[int, int, int]:
    """One ARGB word as its RGB (`rgb_bytes`)."""
    r, g, b = rgb_bytes([word])
    return r, g, b


def check_palette(palette: str = "", first: int = 0, count: int = 0, scale: int = 0,
                  dest: str = "", seconds: float = mlua.EVAL_WAIT_S, **_: Any) -> Path | None:
    """`palette`'s machine-independent half: the device's name, the range, the bound and the
    picture's own arguments."""
    inputs.seconds_bound(seconds)
    if palette:
        inputs.name_word("palette", palette, "a palette device's tag as MAME names it")
    inputs.pen("first", first)
    inputs.natural("count", count, f": 0 reads to the end (at most {COUNT_MAX} pens), or name "
                   f"1..{COUNT_MAX}; page a larger palette with `first`", hi=COUNT_MAX)
    return inputs.picture_args(scale, dest)


def unknown(name: str, have: list[str], common: dict[str, Any]) -> NoReturn:
    """A palette device the machine does not have, named with the ones it does: one sentence
    for every tool that takes a palette's tag."""
    raise st.Invalid("unknown_ref", f"no palette device named {name!r}; this machine has "
                     f"{have or 'none'}", palettes=have, **common)


def palette(ses: gs.Session, scratch: Path, name: str, first: int, count: int, scale: int,
            dest: str, seconds: float = mlua.EVAL_WAIT_S,
            progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `palette` tool: one Lua evaluation, altering nothing."""
    dest_path = check_palette(name, first, count, scale, dest, seconds)
    script = PALETTE_LUA % {"tag": transport.lua_string(name), "first": first, "count": count,
                            "count_max": COUNT_MAX}
    text, common = chunk.run(ses, scratch, script, seconds, progress, "palette")
    if (m := _NONE.search(text)) is not None:
        have = [t for t in m.group(2).split(",") if t]
        if m.group(1) != "-":
            unknown(m.group(1), have, common)
        chunk.one_of("palette device", have, "palettes", "name one with `palette`", common)
    if (m := _PAST.search(text)) is not None:
        raise st.Invalid("bad_argument", f"first={first} count={count} reaches past the last "
                         f"pen of {m.group(1)}, which has "
                         f"{prose.counted(int(m.group(2)), 'entry', 'entries')}",
                         palette=m.group(1), entries=int(m.group(2)), **common)
    m = _PAL.search(text)
    if m is None:
        chunk.no_line("palette", text, common)
    held, entries, indirect = m.group(1), int(m.group(2)), int(m.group(3))
    argb = [int(v, 16) for v in m.group(7).split(",") if v]
    colours = [f"#{v & 0xFFFFFF:06x}" for v in argb]
    fields: dict[str, Any] = {
        "palette": held, "entries": entries, "first": first, "count": len(argb),
        # "cut", as on every tool here: only the cap on a read to the end cuts anything
        "truncated": count == 0 and first + len(argb) < entries,
        "shadows": m.group(4) == "true", "highlights": m.group(5) == "true",
        "indirect_entries": indirect, "colors": colours,
    }
    if any(v >> 24 != 0xFF for v in argb):
        fields["alpha"] = [v >> 24 for v in argb]
    if indirect:
        fields["indirect"] = [int(v) for v in m.group(8).split(",") if v]
    fields["image"] = st.publish(swatch(first, argb, entries), scale, dest_path, scratch,
                                 "palette")
    return running.stop_reply(ses, scratch, f"palette: {common['evaluated_by']}",
                              **st.merged(fields, common))


def pen_runs(pens: list[int]) -> list[str]:
    """Sorted pens as `0xa-0xf` runs: a list of every pen of a large palette would bury the
    answer in the reply."""
    out: list[str] = []
    start = prev = None
    for p in [*pens, None]:
        if p is not None and prev is not None and p == prev + 1:
            prev = p
            continue
        if start is not None and prev is not None:
            out.append(f"{start:#x}" if start == prev else f"{start:#x}-{prev:#x}")
        start = prev = p
    return out


def label_width(entries: int) -> int:
    """The swatch's label column: a 3x5 glyph and a pixel of space for every hex digit the
    palette's last pen needs, and a pixel of margin."""
    return len(f"{max(entries - 1, 0):x}") * (_GLYPH_W + 1) + 1


def swatch(first: int, argb: list[int], entries: int) -> png.Raster:
    """`ROW_PENS` pens a row, each a `CELL`-pixel square, the row's first pen in hex at its
    left."""
    digits = len(f"{max(entries - 1, 0):x}")
    label_w = label_width(entries)
    rows = -(-len(argb) // ROW_PENS)
    width, height = label_w + ROW_PENS * CELL, rows * CELL
    px = bytearray(bytes(_PAPER) * (width * height))

    def put(x: int, y: int, rgb: tuple[int, int, int]) -> None:
        i = (y * width + x) * 3
        px[i:i + 3] = bytes(rgb)

    for row in range(rows):
        label = f"{first + row * ROW_PENS:0{digits}x}"
        for d, ch in enumerate(label):
            for gy in range(5):
                for gx in range(_GLYPH_W):
                    if _GLYPHS[ch][gy * _GLYPH_W + gx] == "1":
                        put(1 + d * (_GLYPH_W + 1) + gx, row * CELL + 1 + gy, _INK)
        for col in range(ROW_PENS):
            k = row * ROW_PENS + col
            if k >= len(argb):
                break
            cell_row = bytes(pen_rgb(argb[k])) * CELL
            for y in range(CELL):
                i = ((row * CELL + y) * width + label_w + col * CELL) * 3
                px[i:i + 3 * CELL] = cell_row
    return png.Raster(width, height, bytes(px))


# ------------------------------------------------------------------ pens for another tool
#
# `gfx_view` draws a tile sheet through `2^planes` pens of a device, read in the same chunk as the
# block it decodes: a function for that chunk to call, and the reading of what it printed.

PENS_LUA = """local function mcp_pens(name, first, n)
  local pals = manager.machine.palettes
  local t = {}
  for k in pairs(pals) do t[#t + 1] = k end
  table.sort(t)
  local p = nil
  if name == "" then
    if #t == 1 then p = pals[t[1]] end
  else
    p = pals[name] or pals[":" .. name]
  end
  if p == nil then
    local shown = name == "" and "-" or name
    print("MAME_MCP_GFX_PENS_NONE name=" .. shown .. " palettes=" .. table.concat(t, ","))
    return
  end
  if first + n > p.entries then
    print(string.format("MAME_MCP_GFX_PENS_SHORT tag=%s entries=%d", p.device.tag, p.entries))
    return
  end
  local out = {}
  for i = first, first + n - 1 do out[#out + 1] = string.format("%08x", p:pen_color(i)) end
  print(string.format("MAME_MCP_GFX_PENS tag=%s entries=%d pens=%s", p.device.tag, p.entries,
                      table.concat(out, ",")))
end
"""
_PENS = re.compile(r"MAME_MCP_GFX_PENS tag=(\S+) entries=(\d+) pens=([0-9a-f,]*)")
_PENS_NONE = re.compile(r"MAME_MCP_GFX_PENS_NONE name=(\S+) palettes=(\S*)")
_PENS_SHORT = re.compile(r"MAME_MCP_GFX_PENS_SHORT tag=(\S+) entries=(\d+)")


def pens_call(palette: str, first: int, n: int) -> str:
    return f"mcp_pens({transport.lua_string(palette)}, {first}, {n})"


def parse_pens(text: str, palette: str, pen_base: int, n: int,
               common: dict[str, Any]) -> tuple[str, list[tuple[int, int, int]]]:
    """The device's tag and the `n` pens from `pen_base`, or the refusal the chunk printed: an
    empty `palette` is the machine's only palette device, as the `palette` tool reads it."""
    if (m := _PENS_NONE.search(text)) is not None:
        have = [t for t in m.group(2).split(",") if t]
        if m.group(1) != "-":
            unknown(palette, have, common)
        chunk.one_of("palette device", have, "palettes", "name one with `palette`", common)
    if (m := _PENS_SHORT.search(text)) is not None:
        entries = int(m.group(2))
        raise st.Invalid("bad_argument", f"{prose.counted(n, 'pen')} from {pen_base:#x} "
                         f"{prose.agrees(n, 'runs', 'run')} past {m.group(1)}, which has "
                         f"{prose.counted(entries, 'entry', 'entries')}: a palette smaller than "
                         "the depth needs is refused, never padded", entries=entries,
                         **common)
    m = _PENS.search(text)
    if m is None:
        chunk.no_line("pens", text, common)
    argb = [int(v, 16) for v in m.group(3).split(",") if v]
    return m.group(1), [pen_rgb(c) for c in argb]
