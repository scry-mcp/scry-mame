"""`gfx_locate`: a patch of the index screen searched in a block, under candidate layouts.

WHY IT EXISTS. `gfx_view` shows bytes under a format somebody stated; nothing in it says the
format is right. This is the known-answer case that does: if a layout decodes, somewhere in the
block, a tile whose pixels are exactly the pens the screen holds, the format, the tile's place in
the block and the palette bank are proved together, against the screen and not against what a
driver believes. A decoder that has never matched the screen is an instrument nobody validated.

HOW A MATCH IS JUDGED. Every window of the layout's tile size inside the patch is tried against
every tile of the range under the flips asked for. A pixel on screen is `bank + value`, the bank
aligned to `2^planes` (`index & ~(2^planes - 1)`), and a match needs one bank for the window and
every value equal: exact, or not a match. A window of one pen matches every blank tile and proves
nothing, so it is skipped and counted, and so is a window whose pixels span two banks (it is not
one tile's pens). The window is flipped, never the tile: every flip is its own inverse, so a tile
flipped matches a window exactly when the window flipped matches the tile, and a window is
flipped once where a tile would be flipped once per window.

TRANSPARENCY PROVES LESS. With `transparent`, tile pixels of that value are not compared (a sprite
drawn over something else), and a match then needs two distinct values compared. On a real board
it leaves several candidates where one sprite is drawn, so each match says how many pixels it
`compared`, and a window more than one tile or flip matched is `ambiguous`. Nothing is ranked: a
heuristic that looks like proof is worse than an honest list, and which candidate is right is a
person's call, or another patch's.

WHAT A MATCH PROVES OF THE LAYOUT. Each match carries its window's `shape`: its distinct rows,
its distinct columns and the pixels of its rarest pen, by which, with the answer's other matches,
`mame_draft` judges whether the match could have happened by chance.

WHEN NO WINDOW IS ONE BANK'S. A board can draw a tile's ink and its paper from two banks (a 1-bit
char's ink in one colour register, its paper in another), or draw one value in two pens (a colour
attribute beside the pixel), and then no window is `bank + value`. So when the single-bank search
matched nothing, a PEN MAP is tried: per window and tile, a table from each pen of the window to
the value it stands for, which has to be a function (a pen standing for two values is no table)
and read two values, a tile of one value proving nothing. With `transparent` the left-out pixels
are free; a 1-bit tile then compares one value, which proves its shape only if the ink's pens are
nowhere among the left-out pixels. A pen map proves the format and the tile, never a bank:
its matches carry the table (`pen_map`) and no `base`.

NO MATCH IS NOT A NEAR MATCH. When nothing matched, `nearest` names the candidate with the
smallest share of disagreeing pixels found within a budget of comparisons (why a share and not
a count: REFERENCE.md, `gfx_locate`), lists them, is called what it is, and says whether the
budget let it look at every candidate (`complete`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core import progress as mprogress
from scry_core import prose
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_chunk as chunk
import mame_evidence as evidence
import mame_gfx as gfx
import mame_inputs as inputs
import mame_layout as ml
import mame_lua as mlua
import mame_manifest as manifest
import mame_running as running
import mame_screen as screen
import mame_state as st

LAYOUTS_MAX = 8
SEARCH_TILES_MAX = 1 << 16
WORK_MAX = 1 << 24             # pixel operations one call spends (`_work`)
NEAREST_WORK_MAX = 1 << 22     # pixel comparisons spent looking for the nearest non-match
MATCHES_MAX = 1 << 16          # matches one call holds: a repeated pattern matches without end
MATCHES_SHOWN = 32
DISAGREE_SHOWN = 16
FLIPS = ("none", "x", "y", "xy")


def _shown(match: dict[str, Any]) -> dict[str, Any]:
    """A match as the reply shows it: a `base` or a `byte` it has none of says why in its place,
    while the row the evidence keeps stays as found."""
    return {**match,
            "base": or_unavailable(match["base"], "matched through a pen map, which `pen_map` "
                                                     "carries instead of a palette bank"),
            "byte": or_unavailable(match["byte"], "the tile starts inside a byte")}


def check_gfx_locate(layouts: Any = None, patch: list[int] | None = None, tag: str = "",
                     ref: str = "", offset: int = 0, first: int = 0, count: int = 0,
                     transparent: int | None = None, flips: list[str] | None = None,
                     seconds: float = mlua.EVAL_WAIT_S, cpu: str = "",
                     **_: Any) -> list[ml.Layout]:
    """`gfx_locate`'s machine-independent half: the candidates whole, the patch, the source, the
    tiles and the flips; handed back parsed, so the body does not parse them twice. A candidate
    NAMED by the manifest is left out: the body resolves it past the gate (`candidates`)."""
    vocab.check_wait(seconds)
    if not isinstance(layouts, list) or not 1 <= len(layouts) <= LAYOUTS_MAX:
        raise st.Invalid("bad_argument", f"layouts is a list of 1..{LAYOUTS_MAX} candidate "
                         "layouts, each as `gfx_view` takes one, with an optional `name`, or the "
                         "name of a format of the loaded manifest")
    named = candidates(layouts, resolve=False)
    if patch is None or not inputs.is_rectangle(patch):
        raise st.Invalid("bad_argument", f"patch={patch!r} is [x, y, width, height] on the "
                         "visible screen, the width and height above zero")
    gfx.check_source(tag, ref, offset, count, named, cpu)
    gfx.check_first(first)
    gfx.check_count(count, SEARCH_TILES_MAX)
    check_transparent(transparent, named)
    if flips is not None and (not flips or len(set(flips)) != len(flips)
                              or not set(flips) <= set(FLIPS)):
        raise st.Invalid("bad_argument", f"flips={flips!r}: some of {list(FLIPS)}, each once "
                         "(the flips the hardware draws; all four when absent)")
    return named


def check_transparent(transparent: int | None, layouts: list[ml.Layout]) -> None:
    """`transparent` is a pixel value every candidate can hold: a value none can take would
    leave every pixel compared while the reply says transparency was used."""
    if transparent is None:
        return
    inputs.natural("transparent", transparent, " is a pixel value, an integer at or above zero")
    for lay in layouts:
        if transparent >= 1 << lay.planes.const:
            raise st.Invalid("bad_argument", f"transparent={transparent!r}: a pixel of "
                             f"{lay.name or 'a candidate'}'s "
                             f"{prose.counted(lay.planes.const, 'plane')} holds "
                             f"0..{(1 << lay.planes.const) - 1}")


def candidates(layouts: list[Any], resolve: bool) -> list[ml.Layout]:
    """The candidates parsed and named (an unnamed one is `layout<its index>`), names unique; a
    format NAMED by the manifest is resolved when `resolve`, else judged by its shape and left
    out."""
    parsed = [manifest.layout_arg(raw, f"layouts[{i}]", resolve) for i, raw in enumerate(layouts)]
    named = [lay if lay.name else _named(lay, f"layout{i}")
             for i, lay in enumerate(parsed) if lay is not None]
    names = [lay.name for lay in named] + [raw for raw, lay in zip(layouts, parsed, strict=True)
                                           if lay is None]
    if len(set(names)) != len(names):
        raise st.Invalid("bad_argument", "two candidate layouts share a name (an unnamed one is "
                         "called `layout<its index>`): give each its own")
    return named


def _named(lay: ml.Layout, name: str) -> ml.Layout:
    return ml.Layout(name, lay.width, lay.height, lay.planes, lay.planeoffset, lay.xoffset,
                     lay.yoffset, lay.charincrement)


@dataclass
class Budget:
    """The pixel comparisons `nearest` may still spend, across every candidate layout, and
    whether it ran out with a comparison left undone: what `complete` says, which the amount
    left cannot (a budget spent to exactly zero on the last comparison looked at everything)."""

    left: int
    cut: bool = False


@dataclass
class Window:
    """A tile-sized rectangle of the patch: where it is, and its pens row-major."""

    x: int
    y: int
    pens: list[int]


def _flipped(values: list[int], w: int, h: int, flip: str) -> list[int]:
    rows = [values[y * w:(y + 1) * w] for y in range(h)]
    if "y" in flip:
        rows.reverse()
    if "x" in flip:
        rows = [r[::-1] for r in rows]
    return [v for r in rows for v in r]


def gfx_locate(ses: gs.Session, scratch: Path, layouts: Any, patch: list[int], tag: str,
               ref: str, offset: int, first: int, count: int, transparent: int | None,
               flips: list[str] | None, cpu: str, seconds: float,
               progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `gfx_locate` tool: ONE evaluation captures the screen's pens and dumps the
    block, so the patch and the bytes are of one instant."""
    cands = check_gfx_locate(layouts, patch, tag, ref, offset, first, count, transparent,
                             flips, seconds, cpu)
    if any(isinstance(raw, str) for raw in layouts):
        cands = candidates(layouts, resolve=True)
        gfx.check_source(tag, ref, offset, count, cands, cpu)
        check_transparent(transparent, cands)
    tried = tuple(f for f in FLIPS if flips is None or f in flips)
    addr, length, on = None, 0, ""
    for lay in cands:
        addr, n, on = gfx.span(ses, lay, ref, first, count, cpu)
        length = max(length, n)
    shot, dump = chunk.next_file(scratch, "screen"), chunk.next_file(scratch, "block")
    script = (screen.capture_lua() + gfx.block_lua(ses, cpu)
              + f"if {screen.capture_call(shot, True)} then\n"
              + f"{gfx.block_call(dump, tag, addr, length)}\nend\n")
    try:
        text, common = chunk.run(ses, scratch, script, seconds, progress, "gfx_locate")
        cap = screen.captured(text, shot, common)
        if cap.indices is None:
            raise st.Invalid("no_channel", f"screen {cap.tag} is drawn in direct colour (it "
                             "names no palette), so it holds no pens to search for",
                             screen=cap.tag, **common)
        blk = gfx.parse_block(text, dump, common)
    finally:
        shot.unlink(missing_ok=True)
        dump.unlink(missing_ok=True)
    px, py, pw, ph = patch
    if px + pw > cap.width or py + ph > cap.height:
        raise st.Invalid("bad_argument", f"patch [{px}, {py}] + {pw}x{ph} leaves the "
                         f"{cap.width}x{cap.height} screen", width=cap.width, height=cap.height,
                         **common)
    start = offset if tag else 0
    plans = []
    spent = pen_spent = 0
    for lay in cands:
        res = gfx.resolved_for(lay, blk, common)
        avail = ml.available(res, blk.size * 8, start)
        n = count or min(max(avail - first, 0), SEARCH_TILES_MAX)
        if count and first + n > avail:
            raise st.Invalid("bad_argument", f"{lay.name}: tiles {first}..{first + n - 1} are "
                             f"not all inside {blk.kind} {blk.tag} ({blk.size:#x} bytes), which "
                             f"holds {avail}", size=blk.size, tiles_available=avail, **common)
        wins = max(pw - res.width + 1, 0) * max(ph - res.height + 1, 0)
        spent += _work(wins, n, len(tried), res.width * res.height, transparent is not None)
        pen_spent += _work(wins, n, len(tried), res.width * res.height, True)
        if spent > WORK_MAX:
            raise st.Invalid("bad_argument", f"{lay.name}: {prose.counted(wins, 'window')} of "
                             f"{res.width}x{res.height} pixels against {prose.counted(n, 'tile')} "
                             f"x {prose.counted(len(tried), 'flip')} brings the call past the "
                             f"{WORK_MAX} one call gathers and compares, every candidate counted: "
                             "narrow `patch`, "
                             "`first`, `count` or the candidates", **common)
        plans.append((res, n, avail, wins))
    if not any(wins and n for _, n, _, wins in plans):
        raise st.Invalid("bad_argument", f"the {pw}x{ph} patch holds no whole tile of any "
                         "candidate, or the range holds no tile: nothing would be compared",
                         **common)
    matches: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    budget = Budget(NEAREST_WORK_MAX)
    for res, n, avail, _wins in plans:
        found, row, near = _search(cap, blk, start, res, first, n, patch, transparent, tried,
                                   budget, MATCHES_MAX - len(matches), common, False)
        matches += found
        rows.append({**row, "tiles_available": avail})
        # the share of the tile's pixels, cross-multiplied (the module's `nearest`)
        if near is not None and (best is None
                                 or near["disagree"] * best["of"] < best["disagree"] * near["of"]):
            best = near
    pen_map: dict[str, Any] | None = None
    if not matches:
        pen_map = _by_pen_map(cap, blk, start, plans, first, patch, transparent, tried, rows,
                              matches, spent + pen_spent, common)
    by_window: dict[tuple[int, int], set[tuple[str, int, str]]] = {}
    for m in matches:
        by_window.setdefault((m["window"][0], m["window"][1]), set()).add(
            (m["layout"], m["tile"], m["flip"]))
    ambiguous = sum(1 for s in by_window.values() if len(s) > 1)
    for m in matches:
        m["ambiguous"] = len(by_window[(m["window"][0], m["window"][1])]) > 1
    fields: dict[str, Any] = {
        "patch": patch, "screen": cap.tag, "frame_screen": cap.frame, "palette": cap.palette,
        **gfx.source_fields(blk, start, addr, on),
        "transparent": or_unavailable(transparent, "no `transparent`: every pixel compared"),
        "flips": list(tried), "candidates": rows,
        "matched": bool(matches), "matches_total": len(matches),
        "matches": [_shown(m) for m in matches[:MATCHES_SHOWN]],
        "ambiguous": bool(ambiguous), "ambiguous_windows": ambiguous,
        "pen_map": or_unavailable(pen_map, "the single-bank search matched, so no pen map "
                                              "was tried"),
    }
    if not matches:
        if best is not None:
            best["complete"] = not budget.cut
        fields["nearest"] = best if best is not None else unavailable(
            "no window came close enough to name (the note says why)")
        if best is None:
            st.add_note(fields,
                "no nearest candidate: " + ("with `transparent` a disagreement has no fixed "
                "count of pixels to be out of" if transparent is not None else
                "every window was of one pen or of two banks")
                + ("; the pen map read none of them as a tile"
                   if pen_map is not None and pen_map["tried"] else ""))
    # what `gfx_draft` derives a draft from: this answer whole, every match included
    fields["evidence"] = {"locate": evidence.record_locate(fields, matches)}
    return running.stop_reply(ses, scratch, f"gfx_locate: {common['evaluated_by']}",
                              **st.merged(fields, common))


def _work(wins: int, n: int, flips: int, pixels: int, transparent: bool) -> int:
    """What one candidate costs, in pixel operations: every tile decoded, then, opaque, every
    window's pixels gathered (its tiles are then found in a table, and a window x tile x flip
    product bounds how many matches a block of repeated tiles can yield), or, transparent, every
    window compared with every tile pixel by pixel under each flip."""
    decoded = n * pixels
    if transparent:
        return decoded + wins * flips * n * pixels
    return decoded + max(wins * pixels, wins * flips * n)


def _search(cap: screen.Capture, blk: gfx.Block, start: int, res: ml.Resolved, first: int,
            n: int, patch: list[int], transparent: int | None, tried: tuple[str, ...],
            budget: Budget, room: int, common: dict[str, Any], by_pen_map: bool,
            ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    """One candidate over every window of the patch: its matches, at most `room` of them, its
    row of counts, and (with no match and no transparency) its nearest non-match within the
    budget; `by_pen_map`, through a pen map, every window of two pens or more tried."""
    px, py, pw, ph = patch
    w, h = res.width, res.height
    mask = (1 << res.planes) - 1
    windows, uniform, mixed = [], 0, 0
    for wy in range(py, py + ph - h + 1):
        for wx in range(px, px + pw - w + 1):
            pens = cap.window(wx, wy, w, h)
            if len(set(pens)) == 1:
                uniform += 1
            elif transparent is None and len({p & ~mask for p in pens}) > 1:
                mixed += 1
                if by_pen_map:
                    windows.append(Window(wx, wy, pens))
            else:
                windows.append(Window(wx, wy, pens))
    tiles: dict[int, list[int]] = {}

    def tile(t: int) -> list[int]:
        if t not in tiles:
            tiles[t] = ml.decode(res, blk.data, start, t)
        return tiles[t]

    found: list[dict[str, Any]] = []
    shapes: dict[tuple[int, int], list[int]] = {}

    def hit(win: Window, t: int, flip: str, base: int | None, compared: int,
            table: dict[int, int] | None = None) -> None:
        if len(found) >= room:
            raise st.Invalid("bad_argument", f"past {MATCHES_MAX} matches in one call: a "
                             "pattern repeated across the patch and the block matches without "
                             "telling anything apart; narrow `patch`, `first` and `count`",
                             **common)
        bit = start * 8 + t * res.charincrement
        shape = shapes.get((win.x, win.y))
        if shape is None:
            shape = shapes[(win.x, win.y)] = _shape(win.pens, w, h)
        found.append({"layout": res.name, "window": [win.x, win.y], "tile": t, "flip": flip,
                      "base": base, "bit": bit, "byte": bit // 8 if bit % 8 == 0 else None,
                      "compared": compared, "shape": shape,
                      **({} if table is None else {"pen_map": sorted(map(list, table.items()))})})

    if by_pen_map:
        for win in windows:
            for flip in tried:
                pens = _flipped(win.pens, w, h, flip)
                for t in range(first, first + n):
                    read = _pen_map_match(tile(t), pens, transparent, res.planes)
                    if read is not None:
                        hit(win, t, flip, None, read[1], read[0])
    elif transparent is None and windows:
        table: dict[tuple[int, ...], list[int]] = {}
        for t in range(first, first + n):
            table.setdefault(tuple(tile(t)), []).append(t)
        for win in windows:
            values = [p & mask for p in win.pens]
            for flip in tried:
                for t in table.get(tuple(_flipped(values, w, h, flip)), []):
                    hit(win, t, flip, win.pens[0] & ~mask, w * h)
    elif windows:
        for win in windows:
            for flip in tried:
                pens = _flipped(win.pens, w, h, flip)
                for t in range(first, first + n):
                    got = _transparent_match(tile(t), pens, mask, transparent)
                    if got is not None:
                        hit(win, t, flip, got[0], got[1])
    row = {"layout": res.as_reply(), "tiles_searched": [first, n], "windows": len(windows),
           "windows_uniform": uniform, "windows_mixed_bank": mixed, "matches": len(found)}
    near = None
    if not found and transparent is None and not by_pen_map:
        near = _nearest(windows, tile, first, n, w, h, mask, res.name, tried, budget)
    return found, row, near


def _by_pen_map(cap: screen.Capture, blk: gfx.Block, start: int,
                plans: list[tuple[ml.Resolved, int, int, int]], first: int, patch: list[int],
                transparent: int | None, tried: tuple[str, ...], rows: list[dict[str, Any]],
                matches: list[dict[str, Any]], spend: int, common: dict[str, Any],
                ) -> dict[str, Any]:
    """The pen map's pass over every candidate, once the single-bank one matched nothing: its
    matches join `matches`, each row says how many were its own. Not tried past the work bound,
    which counts it beside the first pass (the module's paragraph)."""
    if spend > WORK_MAX:
        return {"tried": False, "why": f"with the pen map the call passes the {WORK_MAX} pixel "
                "operations it spends: narrow `patch`, `first` and `count` to try it"}
    for (res, n, _avail, _wins), row in zip(plans, rows, strict=True):
        found, _, _ = _search(cap, blk, start, res, first, n, patch, transparent, tried,
                              Budget(0), MATCHES_MAX - len(matches), common, True)
        matches += found
        row["pen_map_matches"] = len(found)
    return {"tried": True, "matches": len(matches)}


def _pen_map_match(values: list[int], pens: list[int], transparent: int | None,
                   planes: int) -> tuple[dict[int, int], int] | None:
    """The table from each compared pen to the value it stands for, and the pixels compared,
    when the window reads as the tile through one; None otherwise (the module's paragraph)."""
    table: dict[int, int] = {}
    left_out: set[int] = set()
    for v, p in zip(values, pens, strict=True):
        if v == transparent:
            left_out.add(p)
        elif table.setdefault(p, v) != v:
            return None
    read = set(table.values())
    compared = sum(1 for v in values if v != transparent)
    if len(read) >= 2:
        return table, compared
    if transparent is not None and planes == 1 and read and left_out \
            and not left_out & table.keys():
        return table, compared
    return None


def _shape(pens: list[int], w: int, h: int) -> list[int]:
    """The window's distinct rows, its distinct columns and the pixels of its rarest pen: what
    says whether the match could have happened by chance (the module's paragraph)."""
    return [len({tuple(pens[y * w:(y + 1) * w]) for y in range(h)}),
            len({tuple(pens[x::w]) for x in range(w)}),
            min(pens.count(p) for p in set(pens))]


def _transparent_match(values: list[int], pens: list[int], mask: int,
                       transparent: int | None) -> tuple[int, int] | None:
    """The bank and the pixels compared when every opaque pixel is `bank + value`, with two
    distinct values among them; None otherwise."""
    bank: int | None = None
    seen: set[int] = set()
    for v, p in zip(values, pens, strict=True):
        if v == transparent:
            continue
        if p & mask != v or (bank is not None and p & ~mask != bank):
            return None
        bank = p & ~mask
        seen.add(v)
    if bank is None or len(seen) < 2:
        return None
    return bank, sum(1 for v in values if v != transparent)


def _nearest(windows: list[Window], tile: Callable[[int], list[int]], first: int, n: int,
             w: int, h: int, mask: int, name: str, tried: tuple[str, ...],
             budget: Budget) -> dict[str, Any] | None:
    """The candidate with the fewest disagreeing pixels, found within `budget` pixel
    comparisons (spent across every candidate layout); each comparison stops once it is no
    better than the best so far. A comparison is started only with budget left, and one that
    could not be is what makes the search incomplete."""
    best: tuple[int, Window, int, str, list[int]] | None = None
    for win in windows:
        for flip in tried:
            values = _flipped([p & mask for p in win.pens], w, h, flip)
            for t in range(first, first + n):
                if budget.left <= 0:
                    budget.cut = True
                    return _near_reply(best, w, h, tile, name)
                limit = best[0] if best is not None else w * h + 1
                bad = 0
                for a, b in zip(values, tile(t), strict=True):
                    budget.left -= 1
                    if a != b:
                        bad += 1
                        if bad >= limit:
                            break
                if bad < limit:
                    best = (bad, win, t, flip, values)
    return _near_reply(best, w, h, tile, name)


def _near_reply(best: tuple[int, Window, int, str, list[int]] | None, w: int, h: int,
                tile: Callable[[int], list[int]], name: str) -> dict[str, Any] | None:
    if best is None:
        return None
    bad, win, t, flip, values = best
    # Compared in the flipped window's frame; each disagreement is named where it sits on screen.
    at = _flipped(list(range(w * h)), w, h, flip)
    pixels = [[win.x + at[i] % w, win.y + at[i] // w, win.pens[at[i]], d]
              for i, (v, d) in enumerate(zip(values, tile(t), strict=True)) if v != d]
    return {"layout": name, "window": [win.x, win.y], "tile": t, "flip": flip,
            "disagree": bad, "of": w * h, "is_a_match": False,
            "pixels": pixels[:DISAGREE_SHOWN],
            "note": "`pixels` are [x, y, screen pen, decoded value]; the first "
                    f"{DISAGREE_SHOWN} disagreements"}
