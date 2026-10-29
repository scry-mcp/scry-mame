"""A capture's rows read through the manifest's draw command: every blit of a frame as a box over
the screen (`gfx_blits`), and the rectangle one blit reads, decoded unscaled (`gfx_blit_source`).

WHAT THE ROWS PROVE, AND WHAT THEY DO NOT. A row is the command's whole register block as it stood
at the write that fired it (`capture`), so its destination walk, its plane and its source
origin are facts. What painted a given pixel is not: that needs the source pixels, their
transparency and the scale the hardware applied, and the scale law belongs to the project. So a
box COVERS an area and the reply says covering is not painting. A plane drawn in pages (a board
that draws one half while it shows the other) reports each blit's page, and says that which page
the screen shows is not in the rows.

A WALK. The destination runs from `dest_x` to `dest_x_end` inclusive in its declared direction
(or `width` pixels from `dest_x`), wrapping at the plane's size, which makes it one arc of a
circle; the plane's origin, read from the same row, rotates that arc onto the screen, where it is
at most two intervals a side and so at most four rectangles, each cut to the visible area.

THE SOURCE, UNSCALED. The rectangle a blit reads is its origin in the asset's tile, the size of
its destination walk, in the tile's own orientation. It is decoded through a layout that is the
tile's own with its offsets windowed onto the rectangle, which is exact for every layout MAME's
language states, and wraps inside the tile when the asset says it does. The extent of a scaled
blit is the project's law and is not applied; the reply says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scry_core import picture, png, prose
from scry_core import progress as mprogress
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable, unavailable

from scry_mame import callbacks, capture, gfx, inputs, read, running
from scry_mame import gdb_session as gs
from scry_mame import layout as ml
from scry_mame import lua as mlua
from scry_mame import manifest as mm
from scry_mame import palette as mpalette
from scry_mame import screen as mscreen
from scry_mame import space as mspace
from scry_mame import state as st
from scry_mame import tap as mtap
from scry_mame.state import STATE

MARGIN_MAX = 16
# A MARGIN IS SHOWN APART from the rectangle: at a quarter of its colour, the rectangle ringed
# white just outside itself. Drawn like the rectangle, the neighbouring pixels read as part of
# the blit, which is an offset that does not exist. Dimming suits a margin where it did not suit
# `screen_view`'s isolate: here what is looked at keeps its own colours and only the context
# goes dark, and the ring marks the edge whatever the pixels are.
MARGIN_DIM_SHIFT = 2
RING_COLOUR = (255, 255, 255)
MARGIN_NOTE = ("the margin is dimmed and the rectangle ringed in white, so `image` is a view; "
               "`data` is the whole window unscaled, indexed, each pixel its value")
# One colour per writer pc, saturated and none of them white, which marks the `area`.
PC_COLOURS: tuple[tuple[int, int, int], ...] = (
    (255, 64, 64), (64, 224, 64), (64, 128, 255), (255, 200, 0), (255, 64, 255), (0, 224, 224),
    (255, 128, 0), (160, 96, 255), (128, 255, 128), (255, 128, 160), (0, 160, 255),
    (200, 200, 64))
AREA_COLOUR = (255, 255, 255)
COVERING_NOTE = ("a box COVERS the area; what painted a pixel also needs the source pixels, "
                 "their transparency and the scale, which the rows do not carry: `topmost` is "
                 "the last covering blit of the highest plane, the likeliest painter, not a "
                 "proven one")
UNSCALED_NOTE = ("shown unscaled: the rectangle is the destination walk's size from the source "
                 "origin; a scaled blit reads another extent, which is the project's scale law "
                 "and is not applied here")


# ------------------------------------------------------------------ the rows of a command

@dataclass
class Blit:
    """One fired row of a command, with its fields read."""

    index: int                 # its order among the frame's blits
    n: int                     # the capture's row number
    frame: int
    pc: int
    words: list[int]
    values: dict[str, int] = field(default_factory=dict)


@dataclass
class Rows:
    """The fired rows of one frame, and what the capture says about them."""

    frame: int
    frames: list[int]
    blits: list[Blit]
    cut: bool                  # rows past the cap were dropped inside this frame
    rows_path: str
    rows_kept: int
    overflow_rows: int
    cpu: str | None
    callback_errors: dict[str, Any] | None = None   # the capture's, as its watch reports them


#: A blit's `plane` and `page` where the command declares none.
NO_PLANE_WHY = "the command declares no plane"
NO_PAGE_WHY = "the plane is not drawn in pages"


def _pc_fields(pc: int, cpu: str | None) -> dict[str, Any]:
    return read.add_symbol({"pc": st.hex_addr(pc)}, pc, cpu)


def _clear_call(owner: tuple[str, str | None]) -> str:
    """The `declaration_clear(kind="watch")` call that removes the capture under `owner`, as a
    refusal quotes it: an
    owner with no cpu was declared on the first cpu, and a call naming none would clear the ref
    on every cpu."""
    cpu = owner[1] or STATE.first_cpu
    on = f', cpu="{cpu}"' if cpu else ""
    return f'declaration_clear(kind="watch", ref="{owner[0]}"{on})'


def find_capture(cmd: mm.Command) -> tuple[Any, dict[str, Any]]:
    """The capture this command describes: a capture watch on its block whose trigger is the
    command's fire word, on its cpu. None is a refusal that names the call that declares one.
    A command that names no cpu while its block is captured on two is refused too, naming both:
    the answer would otherwise be whichever was declared first."""
    found = [(owner, rec) for owner, rec in capture.block_captures(cmd.cpu)
             if rec.get("addr") == cmd.address and rec.get("width") == cmd.length
             and rec["trigger"] == cmd.trigger]
    # an owner with no cpu was declared on the first cpu, as the tap's id says (`tally.id_for`)
    on = {st.bare_tag(owner[1] or STATE.first_cpu): owner for owner, _ in found}
    if len(on) > 1:
        names = sorted(on)
        clears = "; ".join(_clear_call(o) for o in on.values())
        raise st.Invalid("bad_argument", f"command {cmd.name!r} names no cpu and its block is "
                         f"captured on {', '.join(names)}: name one in the command's `block:` "
                         f"(`cpu: {names[0]}`), or keep one capture ({clears})",
                         captured_on=names)
    if found:
        return found[0]
    call = (f'watch_add(ref="{cmd.address:#x}", mode="capture", length={cmd.length}, '
            f'trigger="{cmd.trigger:#x}"' + (f', cpu="{cmd.cpu}"' if cmd.cpu else "") + ")")
    raise st.Invalid("bad_argument", f"no capture of command {cmd.name!r}'s block is declared: "
                     f"{call} declares it, and the rows start at the next run", declare=call)


def _lane(data: int, mask: int, data_width: int, endianness: str, cmd: mm.Command
          ) -> int | None:
    """The fire word's value in a bus write, or None when the write did not cover all of it."""
    return capture.lane(data, mask, data_width, endianness, cmd.trigger, cmd.word_bytes)


def _words(block: bytes, cmd: mm.Command, endianness: str) -> list[int]:
    wb = cmd.word_bytes
    return [int.from_bytes(block[i * wb:(i + 1) * wb], "big" if endianness == "big" else "little")
            for i in range(cmd.words)]


def read_rows(scratch: Path, cmd: mm.Command, frame: int | None, stop_frame: int) -> Rows:
    """The fired rows of `frame` (None: the newest frame before `stop_frame` that has any)."""
    owner, rec = find_capture(cmd)
    tap, head = mtap.read_tap(scratch, owner, None, False, capture.parse_capture_header,
                              "captured")
    never = {"install_failed": f"the console refused it: {tap.get('why') or 'no error text'}",
             "install_lost": "the console never evaluated its install line"}.get(
                 str(tap.get("state")))
    if never is not None:
        raise st.Invalid("bad_argument", f"the capture of {cmd.name!r} was never installed "
                         f"({never}), so it records nothing: {_clear_call(owner)} and declare "
                         "it again", tally_id=rec["tally_id"], state=tap["state"])
    if head is None:
        raise st.Invalid("bad_argument", f"the capture of {cmd.name!r} has written no rows yet: "
                         "the machine has to run past a trigger and stop", tally_id=rec["tally_id"])
    if cmd.fire_value is not None and cmd.word_bytes > head["data_width"] // 8:
        raise st.Invalid("bad_argument", f"command {cmd.name!r} fires on a word of "
                         f"{prose.counted(cmd.word_bytes, 'byte')} and its cpu's bus writes "
                         f"{head['data_width'] // 8}: no single write carries the fire value",
                         tally_id=rec["tally_id"])
    if cmd.fire_value is not None and mspace.crosses(cmd.trigger, cmd.word_bytes,
                                                       head["data_width"]):
        raise st.Invalid("bad_argument", f"command {cmd.name!r}'s fire word at "
                         f"{cmd.trigger:#x} crosses the bus word of {head['data_width'] // 8} "
                         "bytes: no single write carries the fire value", tally_id=rec["tally_id"])
    by_frame: dict[int, list[Blit]] = {}
    last_row_frame = None
    for row in capture.rows(rec["rows_path"]):
        last_row_frame = row.frame
        if (cmd.fire_value is not None
                and _lane(row.data, row.mask, head["data_width"], head["endianness"], cmd)
                != cmd.fire_value):
            continue
        blits = by_frame.setdefault(row.frame, [])
        blits.append(Blit(len(blits), row.n, row.frame, row.pc,
                          _words(row.block, cmd, head["endianness"])))
    frames = sorted(by_frame)
    common = {"rows_path": str(rec["rows_path"]), "rows_kept": head["rows"],
              "overflow_rows": head["overflow_rows"],
              "frames_with_blits": _span(frames)}
    # A CAPTURE WHOSE TAP RAISED kept fewer rows than were fired, so "no blit in this frame"
    # rides with the count that says why there may have been some, in its fields and its words
    raised = ""
    if "callback_errors" in tap:
        common["callback_errors"] = tap["callback_errors"]
        clause = callbacks.said(tap["callback_errors"], "the capture's")
        raised = f"; {clause}, so rows may be missing" if clause else ""
    if frame is None:
        before = [f for f in frames if f < stop_frame]
        if not before:
            raise st.Invalid("bad_argument", f"no blit of {cmd.name!r} is in the rows from a frame "
                             f"before this stop's frame {stop_frame}: run the machine a frame "
                             f"past the one you want, or name `frame`{raised}", **common)
        frame = before[-1]
    if frame not in by_frame:
        cut = head["overflow_rows"] and (not frames or frame > frames[-1])
        raise st.Invalid("bad_argument", (
            f"frame {frame} is past the rows the capture kept: it counted "
            f"{prose.counted(head['overflow_rows'], 'row')} past its cap and "
            f"{prose.agrees(head['overflow_rows'], 'did not keep it', 'kept none of them')}; "
            "clear it and declare it again just before the frames you want" if cut else
            f"no blit of {cmd.name!r} was fired in frame {frame}") + raised, **common)
    blits = by_frame[frame]
    for b in blits:
        b.values = {name: f.value(b.words) for name, f in {**cmd.fields, **cmd.flags}.items()}
    # the tap keeps rows in order and drops every one past its cap, so only the frame of the
    # last kept row can have lost some
    cut = bool(head["overflow_rows"]) and frame == last_row_frame
    return Rows(frame, frames, blits, cut, str(rec["rows_path"]), head["rows"],
                head["overflow_rows"], owner[1], tap.get("callback_errors"))


def _span(frames: list[int]) -> dict[str, Any]:
    return {"first": frames[0], "last": frames[-1], "count": len(frames)} if frames else {}


# ------------------------------------------------------------------ geometry

def _walk(start: int, end: int | None, size: int | None, up: bool, wrap: int | None
          ) -> tuple[int, int]:
    """The lowest coordinate a walk covers and how many it covers: from `start` to `end`
    inclusive (or `size` of them) in its direction, wrapping at `wrap`, where a walk holds at
    most the plane; 0 when it never reaches its end (no wrap, the end behind it)."""
    if end is None:
        length = max(size or 0, 0)
        length = min(length, wrap) if wrap else length
    elif wrap:
        length = ((end - start) if up else (start - end)) % wrap + 1
    else:
        length = max((end - start if up else start - end) + 1, 0)
    return (start if up else start - length + 1), length


def _arc(lo: int, length: int, origin: int, wrap: int | None, visible: int
         ) -> list[tuple[int, int]]:
    """The interval `lo`..`lo+length-1` of a plane moved to the screen (`- origin`), wrapped at
    `wrap`, as intervals `(start, stop)` cut to `0..visible`."""
    if length <= 0:
        return []
    if wrap:
        length = min(length, wrap)
        a = (lo - origin) % wrap
        pieces = [(a, min(a + length, wrap))] + ([(0, a + length - wrap)]
                                                  if a + length > wrap else [])
    else:
        pieces = [(lo - origin, lo - origin + length)]
    return [(max(s, 0), min(e, visible)) for s, e in pieces if min(e, visible) > max(s, 0)]


def _plane(cmd: mm.Command, b: Blit) -> mm.Plane | None:
    if not cmd.planes:
        return None
    if "plane" not in cmd.fields:
        return cmd.planes[0]
    return next((p for p in cmd.planes if p.when == b.values["plane"]), None)


def _up(cmd: mm.Command, b: Blit, role: str) -> bool:
    f = cmd.fields.get(role)
    return True if f is None else f.holds(b.words)


def geometry(cmd: mm.Command, b: Blit, screen_w: int, screen_h: int) -> dict[str, Any]:
    """Where blit `b` lands: its destination walk, its plane and page, and its screen
    rectangles."""
    v = b.values
    plane = _plane(cmd, b)
    wrap_x = plane.width if plane else None
    wrap_y = plane.height if plane else None
    ends = "dest_x_end" in cmd.fields
    x_lo, w = _walk(v["dest_x"], v.get("dest_x_end") if ends else None, v.get("width"),
                    _up(cmd, b, "dest_dir_x"), wrap_x)
    y_lo, h = _walk(v["dest_y"], v.get("dest_y_end") if ends else None, v.get("height"),
                    _up(cmd, b, "dest_dir_y"), wrap_y)
    out: dict[str, Any] = {
        "box": {"x": v["dest_x"], "y": v["dest_y"], "width": w, "height": h,
                "dir_x": 1 if _up(cmd, b, "dest_dir_x") else -1,
                "dir_y": 1 if _up(cmd, b, "dest_dir_y") else -1},
        "plane": plane.name if plane else None}
    if cmd.planes and plane is None:
        out.update(screen=[], on_screen=False, clipped=False,
                   why=f"no plane is declared for plane value {v['plane']}")
        return out
    if not w or not h:
        out.update(screen=[], on_screen=False, clipped=False,
                   why="the walk covers no pixel: its size is 0, or its end is behind it in its "
                       "declared direction on a plane that does not wrap")
        return out
    ox = plane.origin_x.value(cmd, b.words) if plane else 0
    oy = plane.origin_y.value(cmd, b.words) if plane else 0
    if plane and plane.page:
        out["page"] = cmd.named(plane.page).value(b.words)
    xs = _arc(x_lo, w, ox, wrap_x, screen_w)
    ys = _arc(y_lo, h, oy, wrap_y, screen_h)
    rects = [[xa, ya, xb - xa, yb - ya] for xa, xb in xs for ya, yb in ys]
    # what the walk covers on its plane, a wrapped plane holding at most its own size
    full_x, full_y = min(w, wrap_x) if wrap_x else w, min(h, wrap_y) if wrap_y else h
    seen_x, seen_y = sum(b - a for a, b in xs), sum(b - a for a, b in ys)
    out.update(screen=rects, on_screen=bool(rects),
               clipped=bool(rects) and (seen_x < full_x or seen_y < full_y))
    return out


def _covers(rects: list[list[int]], area: list[int]) -> bool:
    ax, ay, aw, ah = area
    return any(x < ax + aw and ax < x + w and y < ay + ah and ay < y + h for x, y, w, h in rects)


def not_proved(cmd: mm.Command, used: set[str]) -> list[str]:
    """The fields, flags and planes a reply leaned on whose status is not `proved`."""
    out = [n for n in sorted(used) if n in cmd.fields or n in cmd.flags
           if cmd.named(n).status != "proved"]
    out += [f"planes.{p.name}" for p in cmd.planes if p.status != "proved"]
    return out


# ------------------------------------------------------------------ gfx_blits

def check_gfx_blits(draw_command: str = "", frame: int | None = None, area: list[int] | None = None,
                    detail: bool = False, first: int = 0, scale: int = 0, dest: str = "",
                    seconds: float = mlua.EVAL_WAIT_S, **_: Any) -> Path | None:
    """`gfx_blits`'s machine-independent half: the shapes of its arguments, and a `first` that
    pages nothing refused rather than dropped."""
    vocab.check_wait(seconds)
    _check_command(draw_command)
    _check_frame(frame)
    if area is not None and not inputs.is_rectangle(area):
        raise st.Invalid("bad_argument", f"area={area!r} is [x, y, width, height] on the visible "
                         "screen, the width and height above zero")
    vocab.check_bool("detail", detail)
    inputs.natural("first", first, " is a blit's place in the listing")
    if first and not detail and area is None:
        raise st.Invalid("bad_argument", f"first={first}: `first` pages a listing, and only "
                         "`detail=True` or an `area` lists blits")
    return inputs.picture_args(scale, dest)


def _check_command(draw_command: str) -> None:
    inputs.name_word("draw_command", draw_command,
                     "the name of a draw command of the loaded manifest")


def _check_frame(frame: int | None) -> None:
    if frame is not None:
        inputs.natural("frame", frame, " is a frame of the counter")


def gfx_blits(ses: gs.Session, scratch: Path, draw_command: str, frame: int | None,
              area: list[int] | None, detail: bool, first: int, scale: int, dest: str,
              seconds: float,
              progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `gfx_blits` tool. BY DEFAULT A SUMMARY: every blit of a frame with every
    field is a reply past what the client takes in, and the picture with its legend answers who
    drew where at a glance; the blits are listed for an `area` or on request, a page at a time."""
    dest_path = check_gfx_blits(draw_command, frame, area, detail, first, scale, dest, seconds)
    cmd = mm.command(draw_command)
    # the boxes are drawn over the colours: no pen is rewritten to read indices nobody uses
    cap, common = mscreen.capture(ses, scratch, False, seconds, progress)
    if area is not None:
        ax, ay, aw, ah = area
        mscreen.inside(cap, ax, ay, aw, ah, "area", common)
    got = read_rows(scratch, cmd, frame, cap.frame)
    listing = detail or area is not None
    colours: dict[int, tuple[int, int, int]] = {}
    listable: list[tuple[int, dict[str, Any]]] = []      # (pc, the blit's row, unlabelled)
    marks: list[picture.Mark] = []
    planes: dict[tuple[str, int | None], list[int]] = {}
    paged = False
    for b in got.blits:
        geo = geometry(cmd, b, cap.width, cap.height)
        colour = colours.setdefault(b.pc, PC_COLOURS[len(colours) % len(PC_COLOURS)])
        marks += [(x, y, w, h, colour) for x, y, w, h in geo["screen"]]
        counts = planes.setdefault((geo["plane"] or "", geo.get("page")), [0, 0])
        counts[0] += 1
        counts[1] += bool(geo["on_screen"])
        paged = paged or "page" in geo
        if not listing or (area is not None and not _covers(geo["screen"], area)):
            continue                   # the summary lists no blit, so builds no blit's row
        listable.append((b.pc, {
            "index": b.index, "n": b.n, "pc": st.hex_addr(b.pc), **geo,
            "fields": {k: v for k, v in b.values.items() if k in cmd.fields},
            "flags": {k: v for k, v in b.values.items() if k in cmd.flags}}))
    if first and first >= len(listable):
        raise st.Invalid("bad_argument", f"first={first} is past the "
                                         f"{prose.counted(len(listable), 'blit')} "
                         "listed", listed_of=len(listable), **common)
    if area is not None:
        marks.append((ax, ay, aw, ah, AREA_COLOUR))
    legend = [{**_pc_fields(pc, got.cpu),
               "color": "#{:02x}{:02x}{:02x}".format(*rgb),
               "blits": sum(1 for b in got.blits if b.pc == pc)} for pc, rgb in colours.items()]
    fields: dict[str, Any] = {
        "draw_command": cmd.name, "frame_blit": got.frame,
        "frame_complete": got.frame < cap.frame and not got.cut, "rows_cut": got.cut,
        "screen": cap.tag, "frame_screen": cap.frame, "width": cap.width, "height": cap.height,
        "rows_path": got.rows_path, "rows_kept": got.rows_kept,
        "overflow_rows": got.overflow_rows,
        **({} if got.callback_errors is None else {"callback_errors": got.callback_errors}),
        "frames_with_blits": _span(got.frames),
        "blits_in_frame": len(got.blits), "legend": legend,
        "colors_repeat": len(colours) > len(PC_COLOURS),
        "by_plane": [{"plane": plane or unavailable(NO_PLANE_WHY),
                      "page": or_unavailable(page, NO_PAGE_WHY), "blits": n, "on_screen": on}
                     for (plane, page), (n, on) in sorted(
                         planes.items(), key=lambda kv: (kv[0][0], -1 if kv[0][1] is None
                                                         else kv[0][1]))],
    }
    if area is not None:
        fields["area"] = area
        fields["covering"] = len(listable)
        top = _topmost(cmd, [row for _, row in listable])
        fields["topmost"] = or_unavailable(top, "no blit covers the area")
        st.add_note(fields, COVERING_NOTE)
    if listing:
        # a writer is placed in the symbol table for the rows shown, never for the whole frame
        page = [{**row, "plane": or_unavailable(row["plane"], NO_PLANE_WHY),
                 **_pc_fields(pc, got.cpu)}
                for pc, row in listable[first:first + st.ROWS_SHOWN]]
        fields["listed"] = {"first": first, "count": len(page), "of": len(listable)}
        if first + len(page) < len(listable):
            fields["next_first"] = first + len(page)
        fields["blits"] = page
    if paged:
        st.add_note(fields, "a plane drawn in pages: `by_plane` and each listed blit name the "
                            "`page`, and which page the screen shows is not in the rows")
    # a listed blit carries its flags, so a reply that lists blits leans on them
    fields["not_proved"] = not_proved(cmd, set(cmd.fields) | (set(cmd.flags) if listing else set())
                                      | {p.page for p in cmd.planes if p.page} | {
        o.field for p in cmd.planes for o in (p.origin_x, p.origin_y) if o.field})
    fields["image"] = st.publish(mscreen.colour_crop(cap, 0, 0, cap.width, cap.height),
                                 scale, dest_path, scratch, "blits", marks=marks)
    return running.stop_reply(ses, scratch, f"gfx_blits: {common['evaluated_by']}",
                              **st.merged(fields, common))


def _margin_view(exact: png.Raster, margin: int, w: int, h: int) -> png.Raster:
    """The window `exact` (indexed) as RGB, every pixel outside the `w` x `h` rectangle at
    (`margin`, `margin`) at a quarter of its colour."""
    assert exact.palette is not None
    full = [bytes(rgb) for rgb in exact.palette]
    dim = [bytes(v >> MARGIN_DIM_SHIFT for v in rgb) for rgb in exact.palette]
    out = bytearray()
    for y in range(exact.height):
        row = exact.pixels[y * exact.width:(y + 1) * exact.width]
        if not margin <= y < margin + h:
            out += b"".join(dim[v] for v in row)
            continue
        out += b"".join(dim[v] for v in row[:margin])
        out += b"".join(full[v] for v in row[margin:margin + w])
        out += b"".join(dim[v] for v in row[margin + w:])
    return png.Raster(exact.width, exact.height, bytes(out))


def _topmost(cmd: mm.Command, shown: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not shown:
        return None
    order = {p.name: p.order for p in cmd.planes}
    best = max(shown, key=lambda item: (order.get(item["plane"], 0), item["index"]))
    return {"index": best["index"], "n": best["n"], "pc": best["pc"],
            "plane": or_unavailable(best["plane"], NO_PLANE_WHY)}


# ------------------------------------------------------------------ gfx_blit_source

def check_gfx_blit_source(draw_command: str = "", frame: int | None = None,
                          index: int | None = None,
                          pc: str = "", margin: int = 0, scale: int = 0, dest: str = "",
                          seconds: float = mlua.EVAL_WAIT_S, **_: Any) -> Path | None:
    """`gfx_blit_source`'s machine-independent half."""
    vocab.check_wait(seconds)
    _check_command(draw_command)
    _check_frame(frame)
    if (index is None) == (not pc):
        raise st.Invalid("bad_argument", "one blit per call: `index` (its order in the frame, as "
                         "`gfx_blits` lists it) or `pc` (the writer that fired it), not both, not "
                         "neither")
    if index is not None:
        inputs.natural("index", index, " is a blit's order in its frame")
    if pc:
        inputs.check_ref(pc, "pc")      # a symbol or a `0x` address, as `gfx_film`'s `pc` is
    inputs.natural("margin", margin, f" is 0..{MARGIN_MAX} pixels round the rectangle",
                   hi=MARGIN_MAX)
    return inputs.picture_args(scale, dest)


def _pick(got: Rows, index: int | None, pc: str) -> Blit:
    if index is not None:
        if index >= len(got.blits):
            raise st.Invalid("bad_argument", f"frame {got.frame} has "
                                             f"{prose.counted(len(got.blits), 'blit')}; "
                             f"index {index} is not one", blits_in_frame=len(got.blits))
        return got.blits[index]
    want = STATE.resolve_named("pc", pc, got.cpu)   # on the capture's cpu, where it runs
    hits = [b for b in got.blits if b.pc == want]
    if len(hits) != 1:
        raise st.Invalid("bad_argument", (
            f"pc {want:#x} fired no blit in frame {got.frame}" if not hits else
            f"pc {want:#x} fired {prose.counted(len(hits), 'blit')} in frame {got.frame}: name one "
            "by `index`"),
            indexes=[b.index for b in hits])
    return hits[0]


def window(res: ml.Resolved, x0: int, y0: int, w: int, h: int, wrap: bool) -> ml.Resolved:
    """The tile layout `res` windowed onto the `w` x `h` rectangle at (`x0`, `y0`) of a tile:
    the same planes and increment, each pixel's offsets the tile's own at that place, taken
    modulo the tile's size when it `wrap`s, refused past its edge otherwise."""
    if not wrap and (x0 < 0 or y0 < 0 or x0 + w > res.width or y0 + h > res.height):
        raise st.Invalid("bad_argument", f"the rectangle {w}x{h} at ({x0}, {y0}) leaves the "
                         f"{res.width}x{res.height} tile, and the asset does not wrap",
                         tile_width=res.width, tile_height=res.height)
    xs = tuple(res.xoffset[(x0 + i) % res.width] for i in range(w))
    ys = tuple(res.yoffset[(y0 + j) % res.height] for j in range(h))
    return ml.Resolved(res.name, w, h, res.planes, res.planeoffset, xs, ys, res.charincrement)


def gfx_blit_source(ses: gs.Session, scratch: Path, draw_command: str, frame: int | None,
                    index: int | None, pc: str, margin: int, scale: int, dest: str,
                    seconds: float,
                    progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `gfx_blit_source` tool: ONE evaluation dumps the asset's block and reads
    its pens; the row comes from the capture."""
    dest_path = check_gfx_blit_source(draw_command, frame, index, pc, margin, scale, dest,
                                      seconds)
    cmd = mm.command(draw_command)
    missing = [r for r in ("source_x", "source_y") if r not in cmd.fields]
    if not cmd.asset or missing:
        raise st.Invalid("bad_argument", f"command {cmd.name!r} names " + (
            "no `asset` to read a source from" if not cmd.asset else
            f"no {missing} role, so where it reads is not stated"))
    asset = mm.loaded().assets[cmd.asset]
    lay = mm.loaded().formats[asset.format].layout
    stop_frame = st.last_stop_frame()
    if frame is None and stop_frame is None:
        raise st.Invalid("bad_argument", "this stop's frame is not known, so the newest frame "
                         "before it cannot be picked: name `frame`")
    got = read_rows(scratch, cmd, frame, stop_frame if isinstance(stop_frame, int) else 0)
    b = _pick(got, index, pc)
    geo = geometry(cmd, b, 1 << 30, 1 << 30)
    w, h = geo["box"]["width"], geo["box"]["height"]
    if not w or not h:
        raise st.Invalid("bad_argument", f"blit {b.index} of frame {got.frame} covers no pixel "
                         f"({geo.get('why', 'an empty walk')}), so it reads no rectangle",
                         destination=geo["box"])
    up_x, up_y = _up(cmd, b, "source_dir_x"), _up(cmd, b, "source_dir_y")
    sx, sy = b.values["source_x"], b.values["source_y"]
    tile = b.values.get("source_tile", 0)
    if tile < 0:
        raise st.Invalid("bad_argument", f"blit {b.index} of frame {got.frame} names source tile "
                         f"{tile}, below the first", source_tile=tile)
    x0 = (sx if up_x else sx - w + 1) - margin
    y0 = (sy if up_y else sy - h + 1) - margin
    depth = 1 << lay.planes.const
    text, common, blk = gfx.read_with_pens(ses, scratch, "", asset.tag, None, 0, asset.palette,
                                           asset.pen_base, depth, seconds, progress,
                                           "gfx_blit_source")
    res = gfx.resolved_for(lay, blk, common)
    avail = ml.available(res, blk.size * 8, asset.offset)
    if tile >= avail:
        raise st.Invalid("bad_argument", f"source tile {tile} is not inside {blk.kind} {blk.tag}, "
                         f"which holds {prose.counted(avail, 'whole tile')} of {lay.name} from "
                         f"offset {asset.offset:#x}", tiles_available=avail, **common)
    wide, high = w + 2 * margin, h + 2 * margin
    if wide * high > gfx.TILE_PIXELS_MAX:
        raise st.Invalid("bad_argument", f"a {wide}x{high} rectangle is past the "
                         f"{gfx.TILE_PIXELS_MAX} pixels one call decodes", **common)
    try:
        win = window(res, x0, y0, wide, high, asset.wrap)
    except st.Invalid as e:
        raise st.Invalid(e.code, str(e), **e.fields, **common) from None
    pixels = ml.decode(win, blk.data, asset.offset, tile)
    pal_tag, pens = mpalette.parse_pens(text, asset.palette, asset.pen_base, depth, common)
    fields: dict[str, Any] = {
        "draw_command": cmd.name, "frame_blit": got.frame, "index": b.index, "n": b.n,
        **{f"blit_{k}": v for k, v in _pc_fields(b.pc, got.cpu).items()},
        **({} if got.callback_errors is None else {"callback_errors": got.callback_errors}),
        "asset": asset.name, "tag": blk.tag, "format": lay.name,
        "palette": pal_tag, "pen_base": asset.pen_base,
        "rect": {"tile": tile, "x": sx if up_x else sx - w + 1, "y": sy if up_y else sy - h + 1,
                 "width": w, "height": h, "dir_x": 1 if up_x else -1, "dir_y": 1 if up_y else -1},
        "margin": margin, "box": [margin, margin, w, h], "wrap": asset.wrap,
        "destination": geo["box"], "note": UNSCALED_NOTE,
        "not_proved": not_proved(cmd, {"source_x", "source_y", "source_tile", "source_dir_x",
                                       "source_dir_y", "dest_x", "dest_y", "dest_x_end",
                                       "dest_y_end", "width", "height", "dest_dir_x",
                                       "dest_dir_y", "reads_source"} & set(cmd.fields)),
    }
    if "reads_source" in cmd.fields:
        reads = cmd.fields["reads_source"].holds(b.words)
        fields["reads_source"] = reads
        if not reads:
            st.add_note(fields, "the manifest's `reads_source` says this blit reads no source: "
                                "the rectangle is where its source registers point, not what it "
                                "drew")
    exact = png.Raster(wide, high, bytes(pixels), tuple(pens))
    if not margin:
        fields["image"] = st.publish(exact, scale, dest_path, scratch, "source")
    else:
        fields["data"] = st.data_file(exact, scratch, "source-data")
        st.add_note(fields, MARGIN_NOTE)
        fields["image"] = st.publish(_margin_view(exact, margin, w, h), scale, dest_path,
                                     scratch, "source",
                                     rings=[(margin, margin, w, h, RING_COLOUR, 1)])
    return running.stop_reply(ses, scratch, f"gfx_blit_source: {common['evaluated_by']}",
                              **st.merged(fields, common))
