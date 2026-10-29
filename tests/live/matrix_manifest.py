"""Sections E and F of the live matrix: the project's manifest on m68k-dual."""


import json
from pathlib import Path
from typing import Any

from bench_boards import (
    BENCH,
    MANIFEST,
    bench_missing,
    value,
)
from live_harness import (
    blocked,
    boot,
    call,
    cell,
    fresh_state,
    ok,
    refused,
    said,
    section,
    unavailable_why,
)

from scry_mame import ramdac as mramdac  # isort: skip
from scry_core import pens as scry_pens  # noqa: E402

from scry_mame import watches as mwatches  # isort: skip
from scry_mame.state import REPLY_BUDGET_CHARS  # isort: skip
from matrix_pairs import (  # noqa: E402
    FAULT,
    plant_fault,
    planted_at,
    raised,
)
from matrix_tools_by_state import (  # noqa: E402
    BLIT_TRIGGER,
    BLITTER,
)

E_CELLS = [
    "gfx_load reads the project's manifest whole, every field with its status",
    "gfx_blits reads a finished frame of the blitter's capture as boxes over the screen",
    "the known answer: the sprite plane composed from each blit's source, in the order drawn, "
    "is the screen's pens wherever it is opaque, on the page the screen shows",
    "the control: the same composition from the row before each source origin disagrees",
    "an area inside one blit's box lists it among the blits covering it, in the order drawn",
    "gfx_blit_source is byte-identical to what the project's renderer samples for that rectangle",
    "the control: the renderer's rectangle a row over is not",
    "gfx_blits by default is a summary, no blit listed, its text under the reply budget",
    "no stop's survey lists the capture's rows; declaration_list watch does",
    "isolate draws the pen asked for in the contrast colour and every other pen grey, indexed",
    "pixel answers a crop round the point, the point's own pixel its colour and ringed white",
    "a margin is a view: dimmed round the rectangle, which is ringed; `data` holds the exact "
    "window, and its rectangle is the source without a margin",
    "and none of the graphics reads altered the session",
]


def _every_blit(frame: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every blit of `frame`, paged through `detail=True` by `next_first`, and the first page."""
    first_page = page = call("gfx_blits", draw_command="blit", frame=frame, detail=True, scale=1)
    blits = list(page.get("blits", []))
    while ok(page) and "next_first" in page:
        page = call("gfx_blits", draw_command="blit", frame=frame, detail=True, scale=1,
                    first=page["next_first"])
        blits += page.get("blits", [])
    return blits, first_page


def _png(path: str) -> Any:
    """A PNG the server wrote, read by the suite's own reader (`tests/png_read.py`)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import png_read
    return png_read.read(Path(path).read_bytes())


def _compose(blits: list[dict[str, Any]], sources: dict[int, Any], page: int,
             shift: int) -> dict[tuple[int, int], int]:
    """The sprite plane's pixels on screen from each blit's source (read with a margin of one),
    later blits over earlier ones, source pixel 0 transparent: `shift` rows back from the row
    the blitter reads (0 is the known answer, 1 the control)."""
    out: dict[tuple[int, int], int] = {}
    for b in blits:
        if b["index"] not in sources or b.get("page") != page:
            continue
        pic, rect = sources[b["index"]]
        box = b["box"]
        for j in range(rect["height"]):
            row = j if rect["dir_y"] == 1 else rect["height"] - 1 - j
            y = (box["y"] + box["dir_y"] * j) % 512 - 256 * page
            for i in range(rect["width"]):
                col = i if rect["dir_x"] == 1 else rect["width"] - 1 - i
                v = pic.at(1 + col, 1 + row - shift)
                if v:
                    out[((box["x"] + box["dir_x"] * i) % 512, y)] = v
    return out


def _renderer_tile(tile: int, x: int, y: int, w: int, h: int) -> bytes | None:
    """What the project's renderer samples for a tile whose descriptor sends the blitter to page
    `tile` at (`x`, `y`), `w` x `h`: its own `tile()` over a descriptor written into a copy of its
    ROM. The bench holds one capture per argument set, taken by `fill`, because the renderer
    needs its project's own environment (numpy); the m68k-dual boot already checked every pin.
    None when no capture is pinned for these arguments: the rectangle is not the one pinned."""
    name = f"{value('m68k-dual', 'dir')}/renderer/tile{tile}_x{x}_y{y}_{w}x{h}.bin"
    return None if bench_missing(name) else (BENCH.root / name).read_bytes()


@section("E", "the project's manifest on m68k-dual: boxes, sources, the renderer", E_CELLS)
def block_e() -> None:
    t = E_CELLS
    boot()
    for _ in range(9):
        call("run_for", frames=100, seconds=10.0)
    before = call("status")["session"]["altering_writes"]
    man = call("gfx_load", path=MANIFEST)
    counts = man.get("status_counts", {})
    cell(t[0], ok(man) and "blit" in man.get("commands", {})
         and sum(counts.values()) > 0 and counts.get("proved", 0) > 0, said(man))
    call("watch_add", ref=BLITTER, mode="capture", length=32, trigger=BLIT_TRIGGER)
    call("run_for", frames=3, seconds=10.0)
    summary = call("gfx_blits", draw_command="blit", scale=1)
    blits, boxes = _every_blit(int(summary.get("frame_blit", -1)))
    cell(t[1], ok(boxes) and boxes.get("frame_complete") is True and bool(blits)
         and len(blits) == summary.get("blits_in_frame")
         and [b["index"] for b in blits] == list(range(len(blits)))
         and all(b["pc"] for b in blits), said(boxes))
    text = len(json.dumps(summary, indent=2))
    cell(t[7], ok(summary) and "blits" not in summary and text < REPLY_BUDGET_CHARS,
         f"{summary.get('blits_in_frame')} blits, {text} characters of text")
    listed = [w for w in call("declaration_list", kind="watch").get("watches", [])
              if w.get("mode") == "capture"]
    captured = {w.get("ref") for w in listed}
    survey = [w for w in summary.get("watches", []) if w.get("ref") in captured]
    cell(t[8], bool(survey) and all("first_rows" not in w for w in survey)
         and summary.get("how") == mwatches.STOP_HOW
         and bool(listed) and all(w.get("first_rows") for w in listed),
         f"{len(survey)} in the survey, {len(listed)} listed")
    screen = call("screen_view", scale=1)
    pens = _png(str(screen.get("image", {}).get("path")))
    frame = boxes.get("frame_blit")
    drawn = [b for b in blits if b.get("plane") == "sprites" and b["fields"].get("reads_source")
             and not b["flags"].get("writes_index_0")]   # m68k-dual's driver skips those blits
    sources: dict[int, Any] = {}
    for b in drawn:
        src = call("gfx_blit_source", draw_command="blit", frame=frame, index=b["index"], margin=1,
                   scale=1)
        if ok(src):
            sources[b["index"]] = (_png(str(src["data"]["path"])), src["rect"])
    best: tuple[int, int, int] | None = None
    for page in (0, 1):
        plane = _compose(drawn, sources, page, 0)
        seen = [(x, y) for x, y in plane if 0 <= x < pens.width and 0 <= y < pens.height]
        agree = sum(1 for x, y in seen if pens.at(x, y) == plane[x, y])
        if seen and (best is None or agree - len(seen) > best[1] - best[2]):
            best = (page, agree, len(seen))
    shown = best[0] if best else -1
    cell(t[2], best is not None and best[1] == best[2] and len(sources) == len(drawn),
         f"page {shown}: {best[1] if best else 0} of {best[2] if best else 0} pixels agree, "
         f"{len(sources)} of {len(drawn)} sources read")
    off = _compose(drawn, sources, shown, 1)
    seen_off = [(x, y) for x, y in off if 0 <= x < pens.width and 0 <= y < pens.height]
    wrong = sum(1 for x, y in seen_off if pens.at(x, y) != off[x, y])
    cell(t[3], bool(seen_off) and wrong > 0, f"{wrong} of {len(seen_off)} disagree")
    first = next((b for b in drawn if b.get("page") == shown and b["on_screen"]), None)
    if first is None:
        cell(t[4], False, "no sprite blit of the shown page is on screen")
    else:
        x, y, w, h = first["screen"][0]
        area = call("gfx_blits", draw_command="blit", frame=frame, area=[x + w // 2, y + h // 2, 1,
                                                                         1],
                    scale=1)
        order = [b["index"] for b in area.get("blits", [])]
        cell(t[4], ok(area) and first["index"] in order and order == sorted(order), said(area))
    if first is None or first["index"] not in sources:
        cell(t[5], False, "no blit to compare")
        cell(t[6], False, "no blit to compare")
    else:
        src = call("gfx_blit_source", draw_command="blit", frame=frame, index=first["index"],
                   scale=1)
        rect = src.get("rect", {})
        pic = _png(str(src.get("image", {}).get("path")))
        # the register origin is the rectangle's first row less the manifest's declared add of 1
        mine = _renderer_tile(rect["tile"], rect["x"], rect["y"] - 1, rect["width"],
                              rect["height"])
        over = _renderer_tile(rect["tile"], rect["x"], rect["y"], rect["width"], rect["height"])
        where = (f"{rect.get('width')}x{rect.get('height')} at ({rect.get('x')}, "
                 f"{rect.get('y')}) of page {rect.get('tile')}")
        if mine is None or over is None:
            # A RECTANGLE NOBODY PINNED is the scene or the server's rect having moved: a FAIL
            # naming it, never a BLOCKED that would read as nothing wrong.
            cell(t[5], False, f"{where}: no renderer capture pinned on the bench for it")
            cell(t[6], False, f"{where}: no renderer capture pinned on the bench for it")
        else:
            cell(t[5], ok(src) and bytes(pic.pixels) == mine and len(mine) > 0,
                 f"{where}: {len(mine)} bytes")
            cell(t[6], len(over) == len(mine) and over != mine, f"{len(over)} bytes")
    _e_views(t, pens, first, frame)
    call("declaration_clear", kind="watch", all=True)
    after = call("status")
    cell(t[-1],
         after["session"]["altering_writes"] == before and after["session"]["altered"] is False,
         f"writes {before} -> {after['session']['altering_writes']}")


def _e_views(t: list[str], pens: Any, first: dict[str, Any] | None, frame: Any) -> None:
    """The three views, read back from the files they wrote."""
    pen = pens.at(46, 160)
    iso = call("screen_view", mode="isolate", pens=[pen], scale=1)
    pic = _png(str(iso.get("image", {}).get("path")))
    greys = [c for i, c in enumerate(pic.palette) if i != pen]
    cell(t[9], ok(iso) and pic.indexed and bytes(pic.pixels) == bytes(pens.pixels)
         and pic.palette[pen] == scry_pens.ISOLATE_COLOUR and all(r == g == b for r, g, b in greys),
         f"pen {pen}: {said(iso, 80)}")
    px = call("screen_view", mode="pixel", point=[46, 160], scale=4)
    view = _png(str(px.get("image", {}).get("path")))
    ax, ay = px.get("point_in_crop", [0, 0])
    colour = tuple(int(str(px.get("color", "#000000"))[i:i + 2], 16) for i in (1, 3, 5))
    b = px.get("image", {}).get("border", 0)
    cell(t[10], ok(px) and px.get("pen") == pen and b == len(scry_pens.POINT_RINGS)
         and view.at(b + ax * 4 + 1, b + ay * 4 + 1) == colour
         and view.at(b + ax * 4 - 1, b + ay * 4) == (255, 255, 255),
         f"{px.get('crop')} {said(px, 80)}")
    if first is None:
        cell(t[11], False, "no sprite blit of the shown page is on screen")
        return
    bare = call("gfx_blit_source", draw_command="blit", frame=frame, index=first["index"], scale=1)
    wide = call("gfx_blit_source", draw_command="blit", frame=frame, index=first["index"], margin=2,
                scale=1)
    exact = _png(str(bare.get("image", {}).get("path")))
    data = _png(str(wide.get("data", {}).get("path")))
    shown = _png(str(wide.get("image", {}).get("path")))
    w, h = exact.width, exact.height
    inner = bytes(data.pixels[(2 + j) * data.width + 2 + i] for j in range(h) for i in range(w))
    cell(t[11], ok(wide) and data.indexed and not shown.indexed and inner == bytes(exact.pixels)
         and shown.at(1, 2) == (255, 255, 255) and wide.get("box") == [2, 2, w, h],
         f"{w}x{h} with a margin of 2: {said(wide, 60)}")


#: The name of m68k-dual's palette port in m68k-dual's manifest, which is a RAMDAC.
RAMDAC = "ramdac"
F_CELLS = [
    "with no log armed, the pixel names the `palette_log` call that arms one",
    "a palette port the manifest does not declare is refused, naming the ones it does",
    "palette_log arms the RAMDAC the project's manifest declares",
    "a frame later the log placed the game's writes on pens",
    "before any write of the server's, every logged write is the game's, the last one before "
    "a frame's stop included",
    "the known answer: a pen the log saw completed by its third component, red and blue apart, "
    "holds in the palette device the colour the log composed",
    "the control: the same components read in the order b, g, r are not",
    "the server's own write of a pen is that pen's last setter at the pixel, the debugger's, "
    "agreeing with the live colour",
    "a state load unsyncs the log: no write lands on a pen until an index write",
    "and the log itself altered nothing: before the state load, the only writes counted are the "
    "server's four",
    "a log whose data tap raises counts one error per synced data write, never an empty census",
]


#: The most frames block F runs, one at a time, to find a pen `_completed_pen_red_blue_apart`
#: takes.
PEN_SEARCH_FRAMES_MAX = 30


def _completed_pen_red_blue_apart(r: dict[str, Any]) -> int | None:
    """Of a log read's rows, the newest pen whose own newest write is its third component (`b`)
    and leaves red and blue apart, or None: such a pen is whole in the device at any later stop
    until the game writes it again, and only red and blue apart lets the reversed order below tell
    two readings apart. Chosen from what the log recorded, so the cell asks no scene of a build."""
    seen: set[int] = set()
    for x in sorted((x for x in r.get("rows", []) if "pen" in x), key=lambda x: -x["n"]):
        if x["pen"] in seen:
            continue
        seen.add(x["pen"])
        color = str(x.get("color") or "")
        if x.get("component") == "b" and len(color) == 7 and color[1:3] != color[5:7]:
            return int(x["pen"])
    return None


@section("F", "the palette write log on m68k-dual: which pen, and who set it", F_CELLS)
def block_f() -> None:
    t = F_CELLS
    boot()
    call("gfx_load", path=MANIFEST)
    for frames in (100,) * 8 + (98,):
        call("run_for", frames=frames, seconds=10.0)
    before = call("status")["session"]["altering_writes"]
    call("run_for", milliseconds=6, seconds=10.0)
    px = call("screen_view", mode="pixel", point=[100, 100])
    cell(t[0], ok(px)
         and f'palette_log(palette_port="{RAMDAC}", arm=True)'
         in str(unavailable_why(px.get("set_by"))),
         said(px))
    nope = call("palette_log", palette_port="dac")
    cell(t[1], refused(nope, "unknown_ref") and nope.get("palette_ports") == [RAMDAC], said(nope))
    armed = call("palette_log", palette_port=RAMDAC, arm=True)
    cell(t[2], ok(armed) and armed.get("armed_now") is True, said(armed))
    call("run_for", frames=2, seconds=10.0)
    logged = call("palette_log", palette_port=RAMDAC, limit=4)
    cell(t[3], ok(logged) and logged.get("writes_total", 0) > 0 and bool(logged.get("pens_written"))
         and logged.get("index_writes", 0) > 0, said(logged))
    rows = list(mramdac.rows(Path(str(logged.get("rows_path")))))
    cell(t[4], bool(rows) and all(x.by == "guest" for x in rows if x.kind != "x"),
         f"{len(rows)} rows, {sum(1 for x in rows if x.by == 'debugger')} the debugger's")
    def find_pen() -> int | None:
        return _completed_pen_red_blue_apart(
            call("palette_log", palette_port=RAMDAC, limit=mramdac.LIMIT_MAX))
    pen, ran = find_pen(), 0
    while pen is None and ran < PEN_SEARCH_FRAMES_MAX:
        call("run_for", frames=1, seconds=10.0)
        pen, ran = find_pen(), ran + 1
    mine = ({} if pen is None else
            call("palette_log", palette_port=RAMDAC, pen=pen, limit=1).get("pen_state") or {})
    if pen is None:
        # The game offered no such pen: a fact about its scene, which says nothing of the log.
        why = f"no pen completed with red and blue apart in {PEN_SEARCH_FRAMES_MAX} frames"
        blocked(t[5], why)
        blocked(t[6], why)
    else:
        live = call("palette", first=pen, count=1).get("colors", [None])[0]
        cell(t[5], mine.get("color") == live and live is not None,
             f"pen {pen}: log {mine.get('color')}, palette {live}")
        c = mine.get("components", {})
        bgr = f"#{c.get('b', 0):02x}{c.get('g', 0):02x}{c.get('r', 0):02x}"
        cell(t[6], bgr != live,
             f"pen {pen}: b, g, r reads {bgr} against {live}")
    call("run_for", milliseconds=6, seconds=10.0)
    px = call("screen_view", mode="pixel", point=[100, 100])
    pen = px.get("pen")
    wrote = False
    if isinstance(pen, int) and pen < 256:
        wrote = ok(call("write", ref="0x720001", data_hex=f"{pen:02x}"))
        for v in ("12", "34", "56"):
            wrote = ok(call("write", ref="0x720003", data_hex=v)) and wrote
    after = call("screen_view", mode="pixel", point=[100, 100])
    by = after.get("set_by") or {}
    cell(t[7], wrote and after.get("color") == "#123456" and by.get("color") == "#123456"
         and by.get("last", {}).get("written_by") == "debugger" and by.get("agrees") is True,
         said(after))
    written = call("status")["session"]["altering_writes"]
    name = fresh_state()
    call("state_write", method="save", name=name)
    call("run_for", milliseconds=3, seconds=10.0)
    call("state_write", method="load", name=name)
    call("run_for", frames=1, seconds=10.0)
    loaded = call("palette_log", palette_port=RAMDAC, limit=1)
    rows = list(mramdac.rows(Path(str(loaded.get("rows_path")))))
    at = next((i for i, x in enumerate(rows) if x.kind == "x" and x.reason == "load"), None)
    tail = rows[at + 1:] if at is not None else []
    first_index = next((i for i, x in enumerate(tail) if x.kind == "i"), len(tail))
    placed_early = [x.n for x in tail[:first_index] if x.kind == "d" and x.pen is not None]
    cell(t[8], at is not None and loaded.get("desyncs", 0) >= 1 and not placed_early
         and any(x.kind == "d" and x.pen is not None for x in tail[first_index:]),
         f"desync at row {rows[at].n if at is not None else None}, {len(tail)} rows after, "
         f"placed before an index write: {placed_early[:4]}")
    call("palette_log", palette_port=RAMDAC, clear=True)
    cell(t[9], written - before == 4, f"writes {before} -> {written}")
    armed = call("palette_log", palette_port=RAMDAC, arm=True)
    call("run_for", frames=2, seconds=10.0)
    at = planted_at(plant_fault("MCP_RAMDAC", str(armed.get("tally_id")), (
        f'setmetatable(t.pens, {{__index = function() error("{FAULT}") end}})\n'
        "for k in pairs(t.pens) do t.pens[k] = nil end"), "t.total - t.unsynced"))
    call("run_for", frames=2, seconds=10.0)
    log = call("palette_log", palette_port=RAMDAC, limit=1)
    count, first = raised(log)
    grew = int(log.get("writes_total", -1)) - int(log.get("unsynced_writes", 0)) - at
    cell(t[10], at >= 0 and grew > 0 and count == grew and FAULT in first
         and "callbacks raised" in str(log.get("summary")),
         f"synced data writes since the plant {grew}, errors {count}, first {first[:60]!r}")
    call("palette_log", palette_port=RAMDAC, clear=True)
