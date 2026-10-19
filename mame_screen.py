"""`screen_view`: the screen as the palette indices it really holds, and the capture every graphics
tool that looks at the screen shares.

WHY INDICES AND HOW. On a `bitmap_ind16` screen every pixel is a pen, which answers what a colour
picture cannot: which pen this wrong pixel is, where pen N is, which pens nobody uses, two pens
that share a colour. Stock `screen:pixels()` resolves the pens to colours through the palette
(`screen_device::pixels`), so the indices are recovered this way: inside ONE Lua chunk the pens
are saved, each pen `i` is
set to the colour `i`, the screen is read, the pens are put back and read back, and the screen is
read again. No guest instruction runs inside a chunk, so nothing the game does can see the
encoded pens, and the chunk's file holds every piece of evidence the checks below need. The
encoding and its read run under `pcall`, so the pens are put back whatever happened in between:
a chunk that raised there still leaves the palette as the game left it.

THE CHECKS, each of which makes the reply INVALID rather than a picture: every recovered index
below `entries`; every index mapped through the saved pens equal to the colour the screen showed;
the pens read back after the restore equal to the saved ones; the screen after the restore equal
to the screen before. A palette with shadows or highlights enabled draws indices past `entries`,
which the encoding cannot name, and is refused before anything is written.

WHY THE SESSION IS NOT ALTERED. The pens are written and put back inside one chunk, and the
restore is proven pen by pen. A pen that did not read back as it was saved is counted as a console
write and named in the refusal, because then the palette really is not as the game left it; a
screen that differs across the restore is refused without one, since the pens it is drawn with
did come back.

THE FILE'S WORDS ARE IN THE HOST'S ORDER: `pixels()` copies host-order words, and the pens are
packed with `=I4`, the host's order too, so `array("I")` reads every part of it the same way.
"""

from __future__ import annotations

import re
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core import judges, picture, png, prose
from scry_core import progress as mprogress
from scry_core.raster import signature as raster_signature

import gdb_session as gs
import mame_chunk as chunk
import mame_inputs as inputs
import mame_lua as mlua
import mame_palette as mpalette
import mame_ramdac as mramdac
import mame_ramdac_lua as rlua
import mame_running as running
import mame_state as st
import mame_transport as transport
from mame_state import STATE

MODES = ("render", "isolate", "histogram", "pixel")
INDEX_MODES = ("isolate", "histogram", "pixel")
PENS_MAX = 64
ENCODABLE_PENS = 1 << 24
# AN ISOLATED VIEW draws the pens asked for in ONE saturated hue and every other pen grey by its
# luminance, squeezed into a band with neither black nor white in it: a dimmed dark pen sank
# into a screen gone dark round it, and a hue over greys stands out whatever the pen's colour.
# Magenta is the hue a game's own palette is least likely to be spending.
ISOLATE_COLOUR = (255, 0, 255)
GREY_LOW, GREY_HIGH = 0x30, 0xB0
LUMA_WEIGHTS = (299, 587, 114)     # BT.601's luma, in thousandths: they sum to 1000
# THE PIXEL QUESTION'S PICTURE: a crop this many pixels a side round the point, kept inside the
# screen, the point ringed white then black just outside its own pixel, which a ring never covers.
# At the screen's edge the point is at the crop's too, so the picture carries a border as wide as
# the rings reach, outside the screen, and every pixel picture has the same frame.
PIXEL_CROP = 48
POINT_RINGS = ((255, 255, 255), (0, 0, 0))

# The capture, as a function the graphics chunks share: it prints its own refusal lines and
# answers nil, or the screen's tag, size and frame after writing the file at `path`.
CAPTURE_LUA = """local function mcp_capture(path, want_indices)
  local list = {}
  for tag in pairs(manager.machine.screens) do list[#list + 1] = tag end
  table.sort(list)
  if #list ~= 1 then
    print("MAME_MCP_SCREEN_COUNT screens=" .. table.concat(list, ","))
    return nil
  end
  local tag = list[1]
  local scr = manager.machine.screens[tag]
  local kind = scr.screen_type
  if kind == nil then
    kind = "raster"
    for _, d in pairs(manager.machine.devices) do
      if d.shortname == "vector_device" then kind = "vector" end
    end
  end
  if kind ~= "raster" then
    print(string.format("MAME_MCP_SCREEN_KIND tag=%%s type=%%s", tag, kind))
    return nil
  end
  local frame = scr.frame_number
  if type(frame) == "function" then frame = scr:frame_number() end
  local pal = scr.palette
  local head = string.format("tag=%%s w=%%d h=%%d frame=%%d", tag, scr.width, scr.height, frame)
  if want_indices and pal ~= nil and (pal.shadows_enabled or pal.highlights_enabled) then
    print(string.format("MAME_MCP_SCREEN_SHADOWS %%s palette=%%s", head, pal.device.tag))
    return nil
  end
  if want_indices and pal ~= nil and pal.entries > %(encodable)d then
    print(string.format("MAME_MCP_SCREEN_TOO_MANY %%s entries=%%d", head, pal.entries))
    return nil
  end
  local colour, w, h = scr:pixels()
  local f = assert(io.open(path, "wb"))
  f:write(colour)
  if pal == nil or not want_indices then
    f:close()
    print(string.format("MAME_MCP_SCREEN %%s palette=- entries=0", head))
    return tag
  end
  local n = pal.entries
  local saved, pens, back = {}, {}, {}
  for i = 0, n - 1 do saved[i] = pal:pen_color(i) end
  local ok, enc = pcall(function()
    for i = 0, n - 1 do pal:set_pen_color(i, 0xff000000 | i) end
    return scr:pixels()
  end)
  for i = 0, n - 1 do pal:set_pen_color(i, saved[i]) end
  if not ok then f:close() error(enc, 0) end
  for i = 0, n - 1 do
    pens[#pens + 1] = string.pack("=I4", saved[i])
    back[#back + 1] = string.pack("=I4", pal:pen_color(i))
  end
  local after = scr:pixels()
  f:write(enc) f:write(after) f:write(table.concat(pens)) f:write(table.concat(back))
  f:close()
  print(string.format("MAME_MCP_SCREEN %%s palette=%%s entries=%%d", head, pal.device.tag, n))
  return tag
end
"""

_SCREEN = re.compile(r"MAME_MCP_SCREEN tag=(\S+) w=(\d+) h=(\d+) frame=(\d+) palette=(\S+) "
                     r"entries=(\d+)")
_COUNT = re.compile(r"MAME_MCP_SCREEN_COUNT screens=(\S*)")
_KIND = re.compile(r"MAME_MCP_SCREEN_KIND tag=(\S+) type=(\S+)")
_SHADOWS = re.compile(r"MAME_MCP_SCREEN_SHADOWS tag=(\S+) .* palette=(\S+)")
_TOO_MANY = re.compile(r"MAME_MCP_SCREEN_TOO_MANY tag=(\S+) .* entries=(\d+)")


@dataclass
class Capture:
    """One screen as the chunk captured it: its colours always, its pens and indices when the
    screen is indexed (`palette` is None on a direct-colour screen)."""

    tag: str
    width: int
    height: int
    frame: int
    palette: str | None
    colours: array[int]        # one ARGB word per pixel, row-major
    indices: array[int] | None  # one pen per pixel, row-major
    pens: list[int]            # the saved pens, ARGB

    def rgb(self, pen: int) -> tuple[int, int, int]:
        return mpalette.pen_rgb(self.pens[pen])

    def window(self, x: int, y: int, w: int, h: int) -> list[int]:
        """The pens of the `w` x `h` rectangle at (`x`, `y`), row-major."""
        assert self.indices is not None
        return [v for row in range(y, y + h)
                for v in self.indices[row * self.width + x:row * self.width + x + w]]


def refuse_line(text: str, common: dict[str, Any]) -> None:
    """The capture's own refusals, each in the chunk's words, raised when the console printed
    one: not exactly one screen, a screen that is not a raster, a palette whose pens the encoding
    cannot name."""
    if (m := _COUNT.search(text)) is not None:
        chunk.one_of("screen", [t for t in m.group(1).split(",") if t], "screens",
                     "the graphics tools read a machine with one", common)
    if (m := _KIND.search(text)) is not None:
        raise st.Invalid("no_channel", f"screen {m.group(1)} is a {m.group(2)} screen: it has no "
                         "raster of pixels to read, and MAME would hand back a blank bitmap",
                         screen=m.group(1), screen_type=m.group(2), **common)
    if (m := _SHADOWS.search(text)) is not None:
        raise st.Invalid("no_channel", f"palette {m.group(2)} has shadows or highlights enabled, "
                         "so the screen holds indices past its entries that the pen encoding "
                         "cannot name", screen=m.group(1), palette=m.group(2), **common)
    if (m := _TOO_MANY.search(text)) is not None:
        entries = prose.counted(int(m.group(2)), "entry", "entries")
        raise st.Invalid("no_channel", f"the palette has {entries}, past the "
                         f"{ENCODABLE_PENS} a 24-bit colour can encode", screen=m.group(1),
                         **common)


def parse_capture(text: str, path: Path, common: dict[str, Any]) -> Capture:
    """The capture the console announced and the file it wrote, CHECKED (the module docstring's
    four checks). A check that fails is INVALID; a restore that did not hold counts a write."""
    m = _SCREEN.search(text)
    if m is None:
        chunk.no_line("screen", text, common)
    tag, w, h, frame, pal_tag, n = (m.group(1), int(m.group(2)), int(m.group(3)),
                                    int(m.group(4)), m.group(5), int(m.group(6)))
    data = path.read_bytes() if path.is_file() else b""
    size = w * h * 4
    want = size if pal_tag == "-" else 3 * size + 8 * n
    if len(data) != want:
        raise st.Invalid("unexpected_answer", f"the capture {path} holds "
                                              f"{prose.counted(len(data), 'byte')}, and "
                         f"a {w}x{h} screen with {prose.counted(n, 'pen')} is {want}", **common)
    colours = array("I", data[:size])
    if pal_tag == "-":
        return Capture(tag, w, h, frame, None, colours, None, [])
    encoded = array("I", data[size:2 * size])
    after = data[2 * size:3 * size]
    pens = list(array("I", data[3 * size:3 * size + 4 * n]))
    back = list(array("I", data[3 * size + 4 * n:]))
    if back != pens:
        STATE.console_writes += 1
        moved = [i for i in range(n) if back[i] != pens[i]]
        raise st.Invalid("readback_refused", f"{prose.counted(len(moved), 'pen')} did not read "
                         f"back as they were saved after the restore (first {moved[:8]}): the "
                         "palette is NOT as the game left it, and this session is counted as "
                         "altered",
                         pens_not_restored=moved[:64], **common)
    if after != data[:size]:
        raise st.Invalid("readback_refused", "the screen after the restore differs from the "
                         "screen before it, so the capture did not leave the picture as it found "
                         "it", **common)
    indices = array("I", (v & 0xFFFFFF for v in encoded))
    past = sum(1 for v in indices if v >= n)
    if past:
        raise st.Invalid("readback_refused", f"{prose.counted(past, 'pixel')} recovered an index "
                         f"past the {prose.counted(n, 'entry', 'entries')}: those pixels are not "
                         "drawn from this palette's pens",
                         **common)
    wrong = sum(1 for i, v in enumerate(indices) if (pens[v] | 0xFF000000)
                != (colours[i] | 0xFF000000))
    if wrong:
        raise st.Invalid("readback_refused", f"{prose.counted(wrong, 'pixel')} mapped through the "
                         f"saved pens {prose.agrees(wrong, 'does', 'do')} not give the colour the "
                         "screen showed (an adjusted "
                         "palette, contrast or gamma, draws other colours than its pens)", **common)
    return Capture(tag, w, h, frame, pal_tag, colours, indices, pens)


#: The pens the screen's palette holds NOW, as one string of host-order ARGB words: what a
#: frame's notifier saves so the frame is developed in its own colours, a frame later (the film
#: and the series both; `scr` is the chunk's screen).
FRAME_PENS_LUA = """local function pens()
  local pal = scr.palette
  if pal == nil then return "" end
  local p = {}
  for i = 0, pal.entries - 1 do p[i + 1] = string.pack("=I4", pal:pen_color(i)) end
  return table.concat(p)
end"""


def capture_lua() -> str:
    """The capture's function definition, for a chunk to call as `capture_call` says."""
    return CAPTURE_LUA % {"encodable": ENCODABLE_PENS}


def capture_call(path: Path, want_indices: bool) -> str:
    return f"mcp_capture({transport.lua_string(str(path))}, {'true' if want_indices else 'false'})"


def captured(text: str, path: Path, common: dict[str, Any]) -> Capture:
    """The capture a chunk made, refused in its own words or checked; its file is gone after."""
    try:
        refuse_line(text, common)
        return parse_capture(text, path, common)
    finally:
        path.unlink(missing_ok=True)


def capture(ses: gs.Session, scratch: Path, want_indices: bool, seconds: float,
            progress: mprogress.Progress, then: str = "") -> tuple[Capture, dict[str, Any]]:
    """One evaluation that captures the screen, and runs the Lua `then` after it in the same
    chunk, only when the capture answered, so what it reads is of the same instant and a refused
    capture leaves nothing done behind it: the checked capture and the console's account."""
    path = chunk.next_file(scratch, "screen")
    call = capture_call(path, want_indices)
    script = capture_lua() + (f"if {call} then\n{then}\nend" if then else call)
    try:
        text, common = chunk.run(ses, scratch, script, seconds, progress, "screen")
    except BaseException:
        path.unlink(missing_ok=True)       # a script that raised may have written half of it
        raise
    return captured(text, path, common), common


def check_read_on_time(frame: int, read_at: int, skipped: int) -> None:
    """A frame kept by a notifier was read at the next frame that drew, or it is not the bitmap
    MAME finished for it (`mame_film` says why the read is one frame late)."""
    if read_at != frame + 1 + skipped:
        raise st.Invalid("readback_refused", f"frame {frame}'s picture was read at frame "
                         f"{read_at}, not at the next one that drew (it waited out {skipped} "
                         "skipped), so it is not the bitmap MAME finished for it")


def check_same_size(cap: Capture, frame: int, width: int, height: int, what: str) -> None:
    """A frame kept by a notifier is the size the screen had when `what` was armed."""
    if (cap.width, cap.height) != (width, height):
        raise st.Invalid("readback_refused", f"the screen is {cap.width}x{cap.height} at frame "
                         f"{frame} and was {width}x{height} when the {what} was armed: its "
                         "frames no longer share one size, nor its crop")


def check_screen_signature(crop: list[int] | None = None, seconds: float = mlua.EVAL_WAIT_S,
                           **_: Any) -> None:
    """`screen_signature`'s machine-independent half: the crop's shape and the bound. Whether
    the crop lies on the screen is the machine's to say."""
    if crop is not None:
        judges.rect("crop", crop)
    inputs.seconds_bound(seconds)


def screen_signature(ses: gs.Session, scratch: Path, crop: list[int] | None, seconds: float,
                     progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `screen_signature` tool: the whole screen read in one chunk (the capture
    the views share, colours only, so no pen is touched) and `scry_core.raster`'s signature of
    it, or of `crop`."""
    check_screen_signature(crop, seconds)
    cap, common = capture(ses, scratch, False, seconds, progress)
    x0, y0, w, h = crop if crop is not None else (0, 0, cap.width, cap.height)
    inside(cap, x0, y0, w, h, "crop", common)
    signature = raster_signature("pixel", cap.width, cap.height, mpalette.rgb_bytes(cap.colours),
                                 [x0, y0, w, h])
    return running.stop_reply(ses, scratch, f"screen_signature: {common['evaluated_by']}",
                              signature=signature, kind="pixel", width=cap.width,
                              height=cap.height, crop=[x0, y0, w, h], screen=cap.tag,
                              frame_screen=cap.frame, **common)


# ------------------------------------------------------------------ the tool

def check_screen_view(mode: str = "render", pens: list[int] | None = None,
                      point: list[int] | None = None, crop: list[int] | None = None,
                      scale: int = 0, dest: str = "", seconds: float = mlua.EVAL_WAIT_S,
                      **_: Any) -> Path | None:
    """`screen_view`'s machine-independent half: the mode, the arguments that mode takes and no
    other (an argument a mode would ignore is refused, never dropped), and their shapes."""
    inputs.seconds_bound(seconds)
    inputs.one_of("mode", mode, tuple(MODES))
    if (pens is not None) != (mode == "isolate"):
        raise st.Invalid("bad_argument", "`pens` goes with mode `isolate`, and `isolate` needs "
                         "it: the pens to show")
    if pens is not None:
        if not isinstance(pens, list) or not 1 <= len(pens) <= PENS_MAX:
            raise st.Invalid("bad_argument", f"pens={pens!r}: 1..{PENS_MAX} pen numbers")
        for i, one in enumerate(pens):
            inputs.pen(f"pens[{i}]", one)
    if (point is not None) != (mode == "pixel"):
        raise st.Invalid("bad_argument", "`point` goes with mode `pixel`, and `pixel` needs it: "
                         "[x, y] on the visible screen")
    if point is not None and not inputs.is_naturals(point, 2):
        raise st.Invalid("bad_argument", f"point={point!r} is [x, y], each at or above zero")
    if crop is not None and (mode == "pixel" or not inputs.is_rectangle(crop)):
        raise st.Invalid("bad_argument", f"crop={crop!r} is [x, y, width, height] with a width "
                         "and a height above zero, and mode `pixel` takes `point` instead")
    if mode == "histogram" and (scale or dest):
        raise st.Invalid("bad_argument", "mode `histogram` answers no picture, so `scale` and "
                         "`dest` would do nothing")
    return inputs.picture_args(scale, dest)


def screen_view(ses: gs.Session, scratch: Path, mode: str, pens: list[int] | None,
                point: list[int] | None, crop: list[int] | None, scale: int, dest: str,
                seconds: float,
                progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `screen_view` tool."""
    dest_path = check_screen_view(mode, pens, point, crop, scale, dest, seconds)
    # THE PIXEL QUESTION'S THIRD ANSWER, who set the pen, is dumped by the same chunk, so the pen,
    # its colour and its last write are one state (`mame_ramdac_lua.dump_lua`)
    cap, common = capture(ses, scratch, True, seconds, progress,
                          rlua.dump_lua() if mode == "pixel" else "")
    if mode in INDEX_MODES and cap.indices is None:
        raise st.Invalid("no_channel", f"screen {cap.tag} is drawn in direct colour (it names "
                         "no palette, whatever palette devices the machine has), so it holds no "
                         f"pens: mode `{mode}` needs indices, `render` shows its colours",
                         screen=cap.tag, **common)
    fields: dict[str, Any] = {
        "screen": cap.tag, "width": cap.width, "height": cap.height, "frame_screen": cap.frame,
        "palette": st.or_unavailable(cap.palette, "the screen is direct colour: no palette device "
                                                  "draws it"),
        "entries": len(cap.pens),
        "screen_indexed": cap.indices is not None,
    }
    if mode == "pixel":
        assert point is not None
        x, y = point
        inside(cap, x, y, 1, 1, "point", common)
        assert cap.indices is not None
        pen = cap.indices[y * cap.width + x]
        r, g, b = cap.rgb(pen)
        fields.update(x=x, y=y, pen=pen, color=f"#{r:02x}{g:02x}{b:02x}",
                      **mramdac.set_by(scratch, cap.palette, pen, cap.pens[pen]))
        cx, cy = (min(max(v - PIXEL_CROP // 2, 0), max(side - PIXEL_CROP, 0))
                  for v, side in ((x, cap.width), (y, cap.height)))
        cw, ch = min(PIXEL_CROP, cap.width), min(PIXEL_CROP, cap.height)
        fields.update(crop=[cx, cy, cw, ch], point_in_crop=[x - cx, y - cy])
        rings: list[picture.Ring] = [(x - cx, y - cy, 1, 1, rgb, gap)
                                     for gap, rgb in enumerate(POINT_RINGS, 1)]
        fields["image"] = st.publish(colour_crop(cap, cx, cy, cw, ch), scale, dest_path,
                                     scratch, "pixel", rings=rings,
                                     border=len(POINT_RINGS))
        return running.stop_reply(ses, scratch, f"screen_view: {common['evaluated_by']}",
                                  mode=mode, **st.merged(fields, common))
    x0, y0, w, h = crop if crop is not None else (0, 0, cap.width, cap.height)
    inside(cap, x0, y0, w, h, "crop", common)
    fields["crop"] = [x0, y0, w, h]
    area = cap.window(x0, y0, w, h) if cap.indices is not None else None
    if mode == "histogram":
        assert area is not None
        counts: dict[int, int] = {}
        for v in area:
            counts[v] = counts.get(v, 0) + 1
        fields.update(histogram=[[p, counts[p]] for p in sorted(counts)],
                      pens_used=len(counts), unused=mpalette.pen_runs(
                          [p for p in range(len(cap.pens)) if p not in counts]))
        return running.stop_reply(ses, scratch, f"screen_view: {common['evaluated_by']}",
                                  mode=mode, **st.merged(fields, common))
    selected = set(pens or ())
    if mode == "isolate":
        assert area is not None
        hits = [(i % w + x0, i // w + y0) for i, v in enumerate(area) if v in selected]
        fields["pixels"] = len(hits)
        fields["bbox"] = ([min(x for x, _ in hits), min(y for _, y in hits),
                           max(x for x, _ in hits), max(y for _, y in hits)] if hits
                          else st.unavailable("no pixel holds the pens asked for"))
        fields["pens"] = sorted(selected)
        fields["isolate_color"] = "#{:02x}{:02x}{:02x}".format(*ISOLATE_COLOUR)
    shown = raster(cap, area, x0, y0, w, h, selected if mode == "isolate" else None)
    fields["image"] = st.publish(shown, scale, dest_path, scratch, "screen")
    return running.stop_reply(ses, scratch, f"screen_view: {common['evaluated_by']}",
                              mode=mode, **st.merged(fields, common))


def inside(cap: Capture, x: int, y: int, w: int, h: int, name: str,
           common: dict[str, Any]) -> None:
    """The rectangle named `name` (`crop`, `area`; `point` for one pixel) is on the screen, or
    the refusal that names the screen's size."""
    on_screen(cap.width, cap.height, x, y, w, h, name, common)


def on_screen(width: int, height: int, x: int, y: int, w: int, h: int, name: str,
              common: dict[str, Any]) -> None:
    """`inside` for a screen known by its size alone, as a series knows it when it arms."""
    if x + w > width or y + h > height:
        what = (f"point [{x}, {y}] is off" if name == "point"
                else f"{name} [{x}, {y}] + {w}x{h} leaves")
        raise st.Invalid("bad_argument", f"{what} the {width}x{height} screen",
                         width=width, height=height, **common)


def raster(cap: Capture, area: list[int] | None, x0: int, y0: int, w: int, h: int,
            isolate: set[int] | None) -> png.Raster:
    """The crop as a picture: indexed when the screen's pens fit a PLTE (each PNG index is the
    pen), RGB otherwise; `isolate` draws the set in `ISOLATE_COLOUR` and every other pen grey."""
    table = mpalette.rgb_bytes(cap.pens)        # every pen's RGB in one pass, read by slice

    def shown(pen: int) -> tuple[int, int, int]:
        r, g, b = table[3 * pen:3 * pen + 3]
        if isolate is None:
            return r, g, b
        if pen in isolate:
            return ISOLATE_COLOUR
        luma = sum(w * v for w, v in zip(LUMA_WEIGHTS, (r, g, b), strict=True))
        grey = GREY_LOW + luma * (GREY_HIGH - GREY_LOW) // (255 * sum(LUMA_WEIGHTS))
        return (grey, grey, grey)

    if area is not None and len(cap.pens) <= png.PLTE_MAX:
        return png.Raster(w, h, bytes(area), tuple(shown(p) for p in range(len(cap.pens))))
    if area is not None:
        lut = {p: bytes(shown(p)) for p in set(area)}
        return png.Raster(w, h, b"".join(lut[v] for v in area))
    return colour_crop(cap, x0, y0, w, h)


def colour_crop(cap: Capture, x0: int, y0: int, w: int, h: int) -> png.Raster:
    """The crop in the colours the screen showed, RGB: what a picture marked over is drawn on."""
    rows = array("I")
    for row in range(y0, y0 + h):
        rows.extend(cap.colours[row * cap.width + x0:row * cap.width + x0 + w])
    return png.Raster(w, h, mpalette.rgb_bytes(rows))
