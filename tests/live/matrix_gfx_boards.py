"""Section D of the live matrix: the graphics tools on the free boards."""


import json
import re
import sys
from pathlib import Path
from typing import Any

from gfx_layouts import BYTES_8X8, CIRCUS_CHAR, GRID_FB, GRID_SPRITE, WITCH_TILE
from live_harness import (
    Board,
    blocked,
    boards_cover,
    call,
    cell,
    circus_boot,
    free_boards_missing,
    free_boot,
    live_tmp,
    ok,
    refused,
    run_boards,
    run_frames,
    said,
    section,
)
from matrix_pairs import (  # noqa: E402
    writes,
)

#
# The graphics tools' calibration: each known answer is the MACHINE'S OWN, read in the same
# session (circus's videoram names the char, gridlee's spriteram the sprite), and each negative is
# a board whose screen has no pens to give (starfire, direct colour; witchgme, a palette device
# its screen does not use; topgunnr, vector). The boards are the free sets of mamedev.org, which
# m68k-dual's binary does not carry, so the section runs a stock MAME named by MAME_STOCK_BINARY
# (its `plugins` directory beside it) over the zips in MAME_TEST_ROMS; without both, every cell is
# BLOCKED with that reason.

D_CELLS = [
    "circus: an indexed screen of two pens renders as an indexed PNG and alters nothing",
    "circus: the char videoram names at (88, 96) is located there, alone, as that tile",
    "circus: the patch one pixel over matches nothing, and the nearest says it is no match",
    "gridlee: the palette pages 2048 pens and says more are left",
    "gridlee: a 4-bit framebuffer patch is the tile at the line and column the driver lays out",
    "gridlee: the sprite spriteram places is found through transparency, image and bank",
    "witchgme: RGN_FRAC resolves its planes a third of gfx2 apart",
    "witchgme: an index mode on a screen drawn in direct colour is no_channel",
    "starfire: render answers colours, the index modes and the palette are no_channel",
    "topgunnr: no frame symbol at start; run_for by frames is no_channel and the session "
    "answers after it, by milliseconds it runs the emulated time asked; screen_view and "
    "gfx_locate are no_channel",
    "circus: a film says its frames are unchecked, measuring the snapshot's difference, and "
    "keeps them",
    "starfire: a film of a direct-colour screen keeps its frames in colour, each checked",
    "circus: a sweep of gfx2 labels its candidates, and the column-strip one is an id "
    "gfx_locate proves on the clown",
    "circus: the draft's command, from a capture of the RAM copied to port 2000, places the "
    "clown reversed at one frame's lag: x = 240 - byte 10, y = 239 - byte 11",
    "circus: the control, a capture of videoram on the same trigger, writes no command",
    "circus: the draft loads as a draft, and gfx_blits boxes the clown where gfx_locate finds it",
    "circus: the report regenerates byte for byte, and a manifest is never overwritten",
    "circus: a cleared film leaves its files where they were, its film.txt among them",
    "circus: under frameskip a drawn frame is kept, read at the next frame that drew, and a "
    "met frame the machine skipped is lost as skipped",
    "circus: a film of the clown's vertical position with changed=True meets exactly the frames "
    "an independent counter saw the value move in, fewer than it judged, and names its baseline",
    "circus: the control, a byte written every frame with one value (the paddle's copy at 1f), "
    "keeps nothing with changed=True and says so",
    "hardhat: the text videoram names in row 3, ink and paper in two banks, is found through a "
    "pen map, each letter at its place and no bank claimed",
    "hardhat: the same patch a pixel lower matches nothing, even through a pen map",
    "circus, on the bare screen: a film checks each frame against MAME's rendering of it, keeps "
    "those that match, and refuses a picture that is not, saying the frame it was read at",
    "circus, on the bare screen at frameskip 6: each drawn frame taken is refused for its "
    "picture, each skipped one is lost, and none is kept",
]

# THE INDEPENDENT COUNTER of the changed film's known answer: its own write tap and its own frame
# notifier, recording every span as the frame counter its end reads and whether a write to the
# trigger landed a value unlike the write before; the cell counts them over the frames the film
# says it judged, since the film's install runs a step after this one and its window is its own.
CHANGE_COUNTER_LUA = """local sp = manager.machine.devices[":maincpu"].spaces["program"]
local scr = manager.machine.screens[":screen"]
local C = {prev = nil, moved = false, spans = {}}
_G.MCP_CHANGES = C
C.tap = sp:install_write_tap(%#x, %#x, "mcp_live_changes", function(_, data)
  if C.prev ~= nil and data ~= C.prev then C.moved = true end
  C.prev = data
end)
C.sub = emu.add_machine_frame_notifier(function()
  if #C.spans < 400 then
    C.spans[#C.spans + 1] = string.format("%%d:%%d", scr:frame_number(), C.moved and 1 or 0)
  end
  C.moved = false
end)
print("counter armed")"""
CHANGE_COUNTER_READ = """local C = _G.MCP_CHANGES
C.tap:remove() C.sub:unsubscribe()
print("MCP_CHANGES " .. table.concat(C.spans, ","))"""


def counted_changes(said_by: str, first: int, last: int) -> tuple[int, int] | None:
    """The spans the counter saw end within frames `first`..`last`, and those a value moved in."""
    m = re.search(r"MCP_CHANGES (\S*)", said_by)
    if m is None:
        return None
    spans = [tuple(int(x) for x in item.split(":")) for item in m.group(1).split(",") if item]
    inside = [moved for frame, moved in spans if first <= frame <= last]
    return len(inside), sum(inside)


def _d_circus(t: list[str]) -> None:
    # THE SET'S OWN COLOUR OVERLAY IS THE VIEW HERE, so the film's frames are the unchecked
    # case its cells measure: the snapshot is not the bare screen there.
    circus_boot(view="Color Overlay")
    run_frames(600)
    before = call("status")["session"]["altering_writes"]
    r = call("screen_view", scale=1)
    cell(t[0], ok(r) and r.get("screen_indexed") is True and r.get("entries") == 2
         and r.get("image",
                   {}).get("indexed") is True and writes(call("status")) == before,
         said(r))
    code = call("read_block", tag="videoram", offset=12 * 32 + 11, length=1).get("hex", "")
    r = call("gfx_locate", layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], tag="gfx1",
             flips=["none"])
    m = (r.get("matches") or [{}])[0]
    cell(t[1], ok(r) and r.get("matches_total") == 1 and m.get("ambiguous") is False
         and f"{m.get('tile', -1):02x}" == code, f"videoram {code}; {said(r)}")
    r = call("gfx_locate", layouts=[CIRCUS_CHAR], patch=[89, 96, 8, 8], tag="gfx1",
             flips=["none"])
    near = r.get("nearest") or {}
    cell(t[2], ok(r) and r.get("matched") is False and near.get("is_a_match") is False
         and near.get("disagree", 0) > 0, said(r))
    armed = call("gfx_film", trigger="0x2000", keep=2, frames=4)
    run_frames(6)
    film = call("gfx_film")
    armed_film = armed.get("film") or {}
    mismatch = armed_film.get("mismatch") or {}
    cell(t[10], armed_film.get("checked") is False
         and isinstance(mismatch.get("differing_pixels"), int) and mismatch["differing_pixels"] > 0
         and "overlay_or_artwork" in (mismatch.get("candidates") or [])
         and film.get("kept") == 2 and film.get("film", {}).get("checked") is False, said(film))
    cleared = call("gfx_film", clear=True)
    folder = Path(str(armed_film.get("film_dir")))
    cell(t[17], cleared.get("cleared") is True and (folder / "film.txt").is_file()
         and (folder / "film.json").is_file(),
         f"{folder}: {sorted(p.name for p in folder.iterdir())}")
    # THE CLOWN'S VERTICAL POSITION (port 2000, MAME's `clown_x_w`) IS WRITTEN EVERY FRAME,
    # moved or not: `changed` keeps the frames it moved in, and an independent counter armed at
    # the same stop says which those are
    # the counter's install is sent after the film's, so the console runs the film's first and
    # both see the same first write, which is the film's baseline
    armed = call("gfx_film", trigger="0x2000", changed=True, keep=2, frames=120)
    call("lua", script=CHANGE_COUNTER_LUA % (0x2000, 0x2000))
    run_frames(125)
    film = call("gfx_film")
    said_by = str(call("lua", script=CHANGE_COUNTER_READ).get("output", ""))
    judged = film.get("judged_frames")
    window = judged if isinstance(judged, list) else [0, -1]
    counted = counted_changes(said_by, window[0], window[1])
    cell(t[19], ok(armed) and ok(film) and counted is not None
         and film.get("judged") == counted[0] == 120 and film.get("met") == counted[1]
         and 0 < film.get("met", 0) < 120
         and isinstance(film.get("frame_baseline"), int)
         and film["frame_baseline"] < window[0] and film.get("kept") == 2,
         f"counter over {window}: {counted}; {said(film)}")
    call("gfx_film", clear=True)
    call("gfx_film", trigger="0x1f", changed=True, keep=2, frames=60)
    run_frames(65)
    film = call("gfx_film")
    cell(t[20], ok(film) and film.get("judged") == 60 and film.get("met") == 0
         and "nothing_kept" in film and film.get("baseline_value") == "0x73", said(film))
    call("gfx_film", clear=True)
    # EVERY OTHER FRAME SKIPPED (`s_skiptable` level 6): half the met frames draw nothing and are
    # lost, and each drawn one is read at the next frame that drew, which its file counts
    call("lua", script="manager.machine.video.frameskip = 6")
    call("gfx_film", trigger="0x3000", keep=4, frames=8)
    run_frames(14)
    film = call("gfx_film")
    cell(t[18], ok(film) and film.get("kept") == 4 and film.get("refused") == 0
         and film.get("lost") == {"skipped": 4}, said(film))
    call("close")


def _no_case(label: str, armed: dict[str, Any], film: dict[str, Any],
             lost: dict[str, int]) -> bool:
    """On Windows the picture read at the next notifier is the frame's rendering, so a checked
    film keeps every drawn frame and the refusal has no case; the lost frames still have to be
    the ones these cells expect."""
    if (sys.platform == "win32" and ok(film) and (armed.get("film") or {}).get("checked") is True
            and film.get("refused") == 0 and film.get("kept", 0) > 0
            and film.get("lost") == lost):
        blocked(label, f"no frame's picture differed from its rendering on this build, so "
                f"none could be refused: {said(film, 80)}")
        return True
    return False


def _d_circus_bare(t: list[str]) -> None:
    # THE BARE SCREEN, where the film's check runs: on circus the picture read at the next
    # notifier is no frame's rendering on some frames, and on every one skipping at level 6, so
    # the check refuses those pictures
    circus_boot()
    run_frames(600)
    armed = call("gfx_film", trigger="0x2000", keep=8, frames=12)
    run_frames(16)
    film = call("gfx_film")
    whys = [str(r.get("why", "")) for r in film.get("refused_frames") or []]
    if not _no_case(t[23], armed, film, {}):
        cell(t[23], ok(film) and (armed.get("film") or {}).get("checked") is True
             and film.get("kept", 0) > 0 and film.get("refused", 0) > 0
             and film.get("kept", 0) + film.get("refused", 0) == 8 and film.get("lost") == {}
             and all(", read at frame " in w and "MAME's rendering" in w for w in whys),
             said(film))
    call("gfx_film", clear=True)
    call("lua", script="manager.machine.video.frameskip = 6")
    armed = call("gfx_film", trigger="0x3000", keep=4, frames=8)
    run_frames(14)
    film = call("gfx_film")
    whys = [str(r.get("why", "")) for r in film.get("refused_frames") or []]
    if not _no_case(t[24], armed, film, {"skipped": 4}):
        cell(t[24], ok(film) and (armed.get("film") or {}).get("checked") is True
             and film.get("kept") == 0 and film.get("refused") == 4
             and film.get("lost") == {"skipped": 4}
             and all(", read at frame " in w and "MAME's rendering" in w for w in whys),
             said(film))
    call("close")


def _d_gridlee(t: list[str]) -> None:
    free_boot("gridlee", ["gridfnla.bin"], "0xa000")
    run_frames(900)
    r = call("palette")
    cell(t[3], ok(r) and r.get("entries") == 2048 and r.get("count") == 256
         and r.get("truncated") is True, said(r))
    r = call("gfx_locate", layouts=[GRID_FB], patch=[96, 96, 8, 8], tag="videoram",
             offset=16 * 128, flips=["none"])
    m = (r.get("matches") or [{}])[0]
    cell(t[4], ok(r) and r.get("matches_total") == 1
         and m.get("tile") == (96 - 16) * 32 + 96 // 8, said(r))
    sprite = bytes.fromhex(str(call("read_block", tag="spriteram", length=4).get("hex", "")))
    image, y, x = sprite[0], sprite[2] + 17, sprite[3]     # visible row 0 is bitmap line 16
    r = call("gfx_locate", layouts=[GRID_SPRITE], patch=[x, y, 8, 16], tag="gfx1",
             transparent=0)
    tiles = {(mm.get("tile"), tuple(mm.get("window") or ())) for mm in r.get("matches") or []}
    cell(t[5], ok(r) and (image, (x, y)) in tiles
         and all(isinstance(mm.get("base"), int) and mm["base"] % 16 == 0
                 for mm in r.get("matches") or []),
         f"spriteram image {image:#x} at ({x}, {y}); {said(r)}")
    call("close")


def _d_witchgme(t: list[str]) -> None:
    free_boot("witchgme", ["hn58c256p.box12t1"], "0x4000")
    call("run_for", frames=300, seconds=10.0)
    r = call("gfx_view", layout=WITCH_TILE, palette="palette", tag="gfx2", count=64)
    cell(t[6], ok(r) and r.get("layout", {}).get("planeoffset") == [0, 0x1000 * 8, 0x2000 * 8],
         said(r))
    r = call("screen_view", mode="pixel", point=[10, 10])
    cell(t[7], refused(r, "no_channel") and "direct colour" in str(r.get("message")), said(r))
    call("close")


def _d_starfire(t: list[str]) -> None:
    free_boot("starfire", ["sfire.1a"], "0x0")
    call("run_for", frames=300, seconds=10.0)
    render = call("screen_view", scale=1)
    index_modes = [call("screen_view", mode="histogram"),
                   call("screen_view", mode="pixel", point=[1, 1]),
                   call("screen_view", mode="isolate", pens=[1])]
    pal = call("palette")
    cell(t[8], ok(render) and render.get("screen_indexed") is False
         and all(refused(r, "no_channel") for r in index_modes) and refused(pal, "no_channel"),
         f"{said(render, 50)} / {[said(r, 30) for r in index_modes]} / {said(pal, 50)}")
    # the byte its main loop writes every frame, found with a count watch over its scratch RAM
    armed = call("gfx_film", trigger="0x8014", keep=2, frames=4)
    run_frames(6)
    film = call("gfx_film")
    files = [Path(str(c["path"])) for c in film.get("cells", [])]
    colour = all(p.is_file() and p.read_bytes()[25] == 2 for p in files)
    cell(t[11], (armed.get("film") or {}).get("checked") is True and film.get("kept") == 2
         and film.get("refused") == 0 and colour and len(files) == 2, said(film))
    call("close")


def _d_topgunnr(t: list[str]) -> None:
    """A vector board has no screen device, so MAME's debugger defines no frame counter: the
    run by frames is refused before anything is released, the one by milliseconds runs on the
    emulated clock, and the screen readers have no screen to read."""
    started = free_boot("topgunnr", ["tgl-2.9r", "tgl-2.10r"], "0x804000")
    if isinstance(started.get("frame_symbol"), str):
        # Some MAME builds define a frame counter on this board; the stock Windows release does.
        blocked(t[9], f"this build's topgunnr has a frame counter ({said(started, 60)}): the "
                "board without one is not here to be tested")
        call("close")
        return
    by_frames = call("run_for", frames=30, seconds=10.0)
    after = call("status")
    timed = call("run_for", milliseconds=200, seconds=10.0)
    # Rounded to the microsecond: two readings at the microsecond subtract with a float's error.
    span = round((timed.get("emulated_after_s") or 0.0)
                 - (timed.get("emulated_before_s") or 0.0), 6)
    view = call("screen_view")
    find = call("gfx_locate", layouts=[BYTES_8X8], patch=[0, 0, 8, 8], tag="maincpu", count=8)
    cell(t[9], (started.get("frame_symbol") or {}).get("available") is False
         and refused(by_frames, "no_channel") and ok(after) and after.get("broken") is None
         and ok(timed) and 0.2 <= span <= 0.25
         and refused(view, "no_channel") and refused(find, "no_channel"),
         f"{said(started, 40)} / {said(by_frames, 50)} / {said(timed, 60)} / span {span:.4f} "
         f"/ {said(view, 40)} / {said(find, 40)}")
    call("close")


def _d_discovery(t: list[str]) -> None:
    """The discovery on circus, the known answer read in its driver after the blind run: the
    clown is `clownlayout`, drawn at `256 - clown_y - 16`, `256 - clown_x - 16 - 1`, and the game
    copies RAM 0x0a and 0x0b to the ports that latch them."""
    circus_boot()
    run_frames(600)
    sweep = call("gfx_sweep", tag="gfx2", planes=[1], sizes=[[16, 16]], count=16)
    strips = next((c["id"] for c in sweep.get("candidates", [])
                   if c["what"] == "1bpp 16x16 cells down"), "")
    call("watch_add", ref="0x0", mode="capture", length=64, trigger="0x2000", by="address")
    call("watch_add", ref="0x4080", mode="capture", length=64, trigger="0x2000", by="address")
    last: dict[str, Any] = {}
    for _ in range(40):
        call("run_for", frames=7, seconds=10.0)
        last = call("gfx_locate", layouts=[strips], patch=[0, 0, 248, 256], tag="gfx2",
                    seconds=10.0)
    for _ in range(30):                     # end on a frame where the clown is in the clear
        if last.get("matches_total") == 1:
            break
        call("run_for", frames=1, seconds=10.0)
        last = call("gfx_locate", layouts=[strips], patch=[0, 0, 248, 256], tag="gfx2",
                    seconds=10.0)
    cell(t[12], ok(sweep) and bool(strips) and last.get("matched") is True, said(last))
    dest = live_tmp("mame-live-draft-") / "circus-gfx.yaml"
    draft = call("gfx_draft", dest=str(dest))
    report = (json.loads(Path(draft["report"]["path"]).read_text()) if ok(draft) else {})
    done = [c for c in report.get("correlations", []) if c.get("command")]
    fields = done[0]["fields"] if done else {}
    cell(t[13], draft.get("command_fields") == {
        "write_2000": ["dest_x", "dest_y", "height", "width"]}
         and len(done) == 1 and done[0]["capture"]["addr"] == "0x00000000" and done[0]["lag"] == 1
         and [fields.get(r, {}).get(k) for r in ("dest_x", "dest_y")
              for k in ("word", "sign", "add")] == [10, -1, 240, 11, -1, 239], said(draft))
    control = [c for c in report.get("correlations", []) if c["capture"]["addr"] == "0x00004080"]
    # THE REPORT IS A FILE, not a reply: a correlation that proved no command carries `command`
    # null and says why, which is the draft's promise for data that is no sprite table.
    cell(t[14], len(control) == 1 and control[0]["command"] is None
         and bool(control[0].get("why")), str(control)[:110])
    loaded = call("gfx_load", path=str(dest))
    blits = call("gfx_blits", draw_command="write_2000", detail=True)
    box = ((blits.get("blits") or [{}])[0]).get("box", {})
    window = ((last.get("matches") or [{}])[0]).get("window")
    cell(t[15], loaded.get("draft") is True and blits.get("blits_in_frame") == 1
         and [box.get("x"), box.get("y")] == window, f"box {box}, located {window}")
    again = call("gfx_draft", dest=str(dest))
    confirmed = dest.with_name("confirmed.yaml")
    confirmed.write_text("schema: 1\nsystems: [circus]\n")
    over = call("gfx_draft", dest=str(confirmed))
    cell(t[16], again.get("report", {}).get("sha256") == draft.get("report", {}).get("sha256")
         and refused(over, "bad_argument")
         and confirmed.read_text() == "schema: 1\nsystems: [circus]\n", said(over))
    call("close")


def _d_hardhat(t: list[str]) -> None:
    """The hall of fame at frame 2400: its text is pen 5 over pen 0, two banks for a 1-bit char,
    drawn from `characterram` a bit a pixel (`exidy.cpp`, `draw_background`)."""
    free_boot("hardhat", ["hhl-2.11a"], "0xa000")
    ran = run_frames(2400)
    codes = bytes.fromhex(str(call("read_block", tag="videoram", offset=3 * 32 + 6,
                                   length=7).get("hex", "")))
    if ran.get("frame_after") != 2400:
        codes = b""                        # not the hall of fame: nothing below is its answer
    r = call("gfx_locate", layouts=[BYTES_8X8], patch=[48, 24, 64, 8], tag="characterram",
             count=256, flips=["none"])
    found = sorted((m.get("window", [0])[0], m.get("tile")) for m in r.get("matches") or [])
    cell(t[21], ok(r) and ran.get("frame_after") == 2400 and len(codes) == 7
         and found == [(48 + 8 * i, code) for i, code in enumerate(codes)]
         and all((m.get("base") or {}).get("available") is False and m.get("pen_map")
                 for m in r.get("matches") or [])
         and (r.get("pen_map") or {}).get("tried") is True,
         f"videoram {codes.hex()}; {said(r)}")
    r = call("gfx_locate", layouts=[BYTES_8X8], patch=[48, 25, 64, 8], tag="characterram",
             count=256, flips=["none"])
    cell(t[22], ok(r) and ran.get("frame_after") == 2400 and r.get("matched") is False
         and (r.get("pen_map") or {}).get("tried") is True, said(r))
    call("close")


# EACH BOARD AND THE CELLS IT JUDGES, by their index in D_CELLS (`run_boards` says why the table
# is checked both ways).
D_BOARDS = tuple(Board(run, owned, free_boards_missing) for run, owned in (
    (_d_circus, (0, 1, 2, 10, 17, 18, 19, 20)), (_d_gridlee, (3, 4, 5)), (_d_witchgme, (6, 7)),
    (_d_starfire, (8, 11)), (_d_topgunnr, (9,)), (_d_discovery, (12, 13, 14, 15, 16)),
    (_d_hardhat, (21, 22)), (_d_circus_bare, (23, 24))))
boards_cover("D_BOARDS", D_CELLS, D_BOARDS)


@section("D", "the graphics tools on free boards: known answers and negatives", D_CELLS)
def block_d() -> None:
    run_boards(D_CELLS, D_BOARDS)
