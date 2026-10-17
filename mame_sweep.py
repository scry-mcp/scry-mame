"""`gfx_sweep`: one block under a fixed family of candidate layouts, as ONE labelled sheet.

WHY. A board nobody has described has no format to state, and a format must not be guessed.
So the block is drawn under every arrangement MAME's own layouts are made of, side by side,
each cell labelled with what it is and with the id the next call takes: a person picks the one
that looks like graphics (`gfx_draft(choose=...)`, recorded as `human`), and `gfx_locate` fed the
ids proves one against the screen. Nothing ranks the cells: a heuristic that looks like proof is
worse than an honest choice.

THE FAMILY is fixed, never tuned to a board: the depths in `planes`, the tile sizes
in `sizes`, the pixel ORDER (`rows`; for a tile of several 8x8 cells, the cells `across` then
down, or `down` then across, the 8-pixel column strips) and, past one plane, the plane
ARRANGEMENT (`packed`: a pixel's bits together, plane 0 the top bit as MAME counts it; `planar`:
the planes' bytes of each 8-pixel group one after another; `split`: each plane a fraction of the
block apart, `RGN_FRAC`, so a block only). Candidates with the same offsets are one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scry_core import picture, png
from scry_core import progress as mprogress

import gdb_session as gs
import mame_evidence as evidence
import mame_gfx as gfx
import mame_inputs as inputs
import mame_layout as ml
import mame_lua as mlua
import mame_palette as mpalette
import mame_prose as prose
import mame_running as running
import mame_sheet as sheet
import mame_state as st
from mame_state import STATE

SWEEP_MAX = 16             # candidates on one sheet, which a person reads cell by cell
COUNT_MAX = 64             # tiles a cell shows
COUNT_DEFAULT = 32
COLUMNS = 8                # tiles a row inside a cell
SIDES = (8, 16, 24, 32)    # a tile's side: whole 8x8 cells, up to what MAME's sprites use
PLANES_DEFAULT = (1, 2, 4)
SIZES_DEFAULT = ((8, 8),)
ENLARGE_MAX = 4            # the cells' own integer enlargement, so a tile reads at a glance
_NOMINAL_BITS = 8 << 20    # a block length to compare `RGN_FRAC` candidates at: they are linear
ORDERS = ("rows", "cells across", "cells down")
ARRANGEMENTS = ("packed", "planar", "split")


def _layout(planes: int, w: int, h: int, arrangement: str, order: str) -> dict[str, Any]:
    """The candidate as a `gfx_view` layout object."""
    split = arrangement == "split"
    per_px = 1 if split or planes == 1 else planes          # bits a pixel spans in one row
    cellrow = 8 * per_px
    cell = 8 * cellrow

    def within(x: int) -> int:                               # a pixel inside its 8-pixel group
        return x if arrangement in ("planar", "split") or planes == 1 else x * planes

    if arrangement == "planar":
        planeoffset: list[Any] = [p * 8 for p in range(planes)]
    elif split:
        planeoffset = [f"RGN_FRAC({p},{planes})" for p in range(planes)]
    else:
        planeoffset = list(range(planes))
    cols, rows = w // 8, h // 8
    if order == "rows":
        xoffset = [(x // 8) * cellrow + within(x % 8) for x in range(w)]
        yoffset = [y * cols * cellrow for y in range(h)]
    elif order == "cells across":
        xoffset = [(x // 8) * cell + within(x % 8) for x in range(w)]
        yoffset = [(y // 8) * cols * cell + (y % 8) * cellrow for y in range(h)]
    else:
        xoffset = [(x // 8) * rows * cell + within(x % 8) for x in range(w)]
        yoffset = [(y // 8) * cell + (y % 8) * cellrow for y in range(h)]
    return {"width": w, "height": h, "planes": planes, "planeoffset": planeoffset,
            "xoffset": xoffset, "yoffset": yoffset, "charincrement": cols * rows * cell}


def _what(planes: int, w: int, h: int, arrangement: str, order: str) -> str:
    return f"{planes}bpp {w}x{h} " + (order if planes == 1 else f"{arrangement}, {order}")


def family(planes: list[int], sizes: list[list[int]], split_ok: bool
           ) -> list[tuple[str, dict[str, Any]]]:
    """Every candidate, `(what, raw layout)`, in a fixed order, those with equal offsets once."""
    out: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[Any, ...]] = set()
    for p in planes:
        for w, h in sizes:
            arrangements = ("packed",) if p == 1 else tuple(
                a for a in ARRANGEMENTS if split_ok or a != "split")
            orders = ORDERS if w > 8 or h > 8 else ("rows",)
            for arr in arrangements:
                for order in orders:
                    raw = _layout(p, w, h, arr, order)
                    key = evidence.layout_key(
                        ml.resolve(ml.parse_layout(raw), _NOMINAL_BITS).as_reply())
                    if key not in seen:
                        seen.add(key)
                        out.append((_what(p, w, h, arr, order), raw))
    return out


def check_gfx_sweep(tag: str = "", ref: str = "", offset: int = 0, count: int = COUNT_DEFAULT,
                    planes: list[int] | None = None, sizes: list[list[int]] | None = None,
                    palette: str = "none", pen_base: int = 0, scale: int = 0, dest: str = "",
                    seconds: float = mlua.EVAL_WAIT_S, cpu: str = "", **_: Any
                    ) -> tuple[list[tuple[str, dict[str, Any]]], Path | None]:
    """`gfx_sweep`'s machine-independent half: the family whole, bounded, and the picture's
    arguments."""
    inputs.seconds_bound(seconds)
    ps = list(PLANES_DEFAULT) if planes is None else planes
    if (not isinstance(ps, list) or not ps or len(set(ps)) != len(ps)
            or not all(inputs.is_natural(p, 1, ml.PLANES_MAX) for p in ps)):
        raise st.Invalid("bad_argument", f"planes={planes!r}: depths of 1..{ml.PLANES_MAX}, "
                         f"each once (default {list(PLANES_DEFAULT)})")
    ss = [list(s) for s in SIZES_DEFAULT] if sizes is None else sizes
    if (not isinstance(ss, list) or not ss
            or any(not isinstance(s, list) or len(s) != 2 or any(
                isinstance(v, bool) or v not in SIDES for v in s) for s in ss)
            or len({tuple(s) for s in ss}) != len(ss)):
        raise st.Invalid("bad_argument", f"sizes={sizes!r}: tile sizes [width, height], each side "
                         f"one of {list(SIDES)}, each size once (default [[8, 8]])")
    inputs.count("count", count, COUNT_MAX, ": the tiles each cell shows")
    gfx.check_source(tag, ref, offset, count, [], cpu)
    if palette:
        inputs.name_word("palette", palette, "a palette device's tag, empty for the machine's "
                         "only one, or `none` (the default, a grey ramp that says it is not the "
                         "machine's colours)")
    gfx.check_pen_base(palette, pen_base)
    cands = family(ps, ss, split_ok=bool(tag))
    if len(cands) > SWEEP_MAX:
        raise st.Invalid("bad_argument", f"{prose.counted(len(cands), 'candidate')} "
                         f"{prose.agrees(len(cands), 'is', 'are')} past the "
                         f"{SWEEP_MAX} one sheet holds: narrow `planes` or `sizes`",
                         candidates=len(cands))
    return cands, inputs.picture_args(scale, dest)


def _cell(res: ml.Resolved, data: bytes, start: int, n: int,
          colours: list[tuple[int, int, int]]) -> tuple[int, int, bytes]:
    """`n` tiles, `COLUMNS` a row, as RGB."""
    cols = min(COLUMNS, n)
    width, height = cols * res.width, -(-n // cols) * res.height
    px = bytearray(width * height * 3)
    ink = [bytes(c) for c in colours]
    for k in range(n):
        tx, ty = (k % cols) * res.width, (k // cols) * res.height
        pix = ml.decode(res, data, start, k)
        for y in range(res.height):
            at = ((ty + y) * width + tx) * 3
            px[at:at + 3 * res.width] = b"".join(ink[v]
                                                 for v in pix[y * res.width:(y + 1) * res.width])
    return width, height, bytes(px)


def _padded(width: int, height: int, rgb: bytes, size: tuple[int, int], factor: int) -> bytes:
    """`rgb` enlarged by `factor` into the top left of a `size` picture on the sheet's ground."""
    big = png.enlarged(png.Raster(width, height, rgb), factor)
    out = bytearray(bytes(sheet.GROUND) * (size[0] * size[1]))
    for y in range(big.height):
        at = y * size[0] * 3
        out[at:at + big.width * 3] = big.pixels[y * big.width * 3:(y + 1) * big.width * 3]
    return bytes(out)


def _page(cells: list[tuple[tuple[str, ...], tuple[int, int, bytes]]]
          ) -> tuple[png.Raster, int]:
    """Every cell on one page, its tiles enlarged by the largest factor that keeps them all
    inside the inline ceiling, and that factor."""
    widest = max(w for _, (w, _, _) in cells)
    tallest = max(h for _, (_, h, _) in cells)
    labels = [lab for lab, _ in cells]
    for factor in range(ENLARGE_MAX, 0, -1):
        size = (widest * factor, tallest * factor)
        lay = sheet.layout(size, labels)
        cols, rows = sheet.page_shape(lay, len(cells))
        if cols * rows >= len(cells) and picture.within_ceiling(*lay.size(cols, rows)):
            return sheet.compose(lay, [(lab, _padded(w, h, rgb, size, factor))
                                       for lab, (w, h, rgb) in cells]), factor
    raise st.Invalid("bad_argument", f"{prose.counted(len(cells), 'cell')} of up to "
                     f"{widest}x{tallest} pixels {prose.agrees(len(cells), 'does', 'do')} not fit "
                     "one sheet inside the inline ceiling: narrow `count` or `sizes`")


def gfx_sweep(ses: gs.Session, scratch: Path, tag: str, ref: str, offset: int, count: int,
              planes: list[int] | None, sizes: list[list[int]] | None, palette: str,
              pen_base: int, scale: int, dest: str, cpu: str, seconds: float,
              progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `gfx_sweep` tool: ONE evaluation reads the block and the pens."""
    cands, dest_path = check_gfx_sweep(tag, ref, offset, count, planes, sizes, palette,
                                       pen_base, scale, dest, seconds, cpu)
    layouts = [ml.parse_layout(raw) for _, raw in cands]
    addr, length, on = None, 0, ""
    for lay in layouts:
        addr, n, on = gfx.span(ses, lay, ref, 0, count, cpu)
        length = max(length, n)
    depth = 1 << max(lay.planes.const for lay in layouts)
    text, common, blk = gfx.read_with_pens(ses, scratch, cpu, tag, addr, length, palette,
                                           pen_base, depth, seconds, progress, "gfx_sweep")
    real = palette != "none"
    pal_tag, pens = (mpalette.parse_pens(text, palette, pen_base, depth, common) if real
                     else ("none", []))
    start = offset if tag else 0
    n_sweep = len(evidence.sweeps()) + 1
    listed: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    cells: list[tuple[tuple[str, ...], tuple[int, int, bytes]]] = []
    for k, ((what, raw), lay) in enumerate(zip(cands, layouts, strict=True), start=1):
        cid = evidence.sweep_id(n_sweep, k)
        res = gfx.resolved_for(ml.Layout(cid, lay.width, lay.height, lay.planes, lay.planeoffset,
                                         lay.xoffset, lay.yoffset, lay.charincrement),
                               blk, common)
        avail = ml.available(res, blk.size * 8, start)
        shown = min(count, avail)
        listed.append({"id": cid, "what": what, "tiles_available": avail, "shown": shown})
        if not shown:
            continue
        colours = (list(pens[:1 << res.planes]) if real else gfx.grey_ramp(res.planes))
        kept.append({"id": cid, "raw": raw, "what": what, "resolved": res.as_reply()})
        planes_s, rest = what.split(" ", 1)
        size_s, arrangement = rest.split(" ", 1)
        cells.append(((cid.upper(), f"{planes_s} {size_s}".upper(),
                       arrangement.replace(",", "").upper()),
                      _cell(res, blk.data, start, shown, colours)))
    if not cells:
        raise st.Invalid("bad_argument", f"no candidate holds a whole tile in {blk.kind} "
                         f"{blk.tag} ({blk.size:#x} bytes) from offset {start:#x}",
                         size=blk.size, candidates=listed, **common)
    page, factor = _page(cells)
    image = picture.publish(page, scale, dest_path, scratch, "sweep", STATE.record_image)
    source = gfx.source_fields(blk, start, addr, on)
    n = evidence.record_sweep(evidence.source_of(source), pal_tag, pen_base, kept, image)
    fields: dict[str, Any] = {
        **source, "sweep": n, "count": count, "palette": pal_tag, "pen_base": pen_base,
        "real_colors": real, "cell_scale": factor, "candidates": listed,
        "next": "gfx_locate(layouts=[<ids>]) proves one against the screen; "
                'gfx_draft(choose={"candidate": <id>, "chosen_by": <who>}) records a '
                "person's pick",
    }
    if not real:
        fields["note"] = ("palette `none`: a grey ramp over the pixel values, NOT the machine's "
                          "colours")
    fields["image"] = image
    return running.stop_reply(ses, scratch, f"gfx_sweep: {common['evaluated_by']}",
                              **st.merged(fields, common))

