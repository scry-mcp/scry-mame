"""The reference tour: one session on Gridlee that calls each tool of the server once, in the order
of one investigation, every answer checked. `--help` says how to run it.

The reference pages take each tool's example from this run's normalised transcript, so a reader
with the free ROM set can try every one. What it follows: a coin to the two bytes that count it,
the START that spends it, the player's sprite from the sprite table to the ROM that holds its
picture, and the files a session leaves. Three tools are left out, each for what Gridlee lacks:
`cpu_focus` (a second cpu), `palette_log` (a port that sets a pen; the colours are PROMs) and
`gfx_blit_source` (source coordinates in the sprite entry, which names a whole tile).
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from scry_core import png
from scry_core.demo import DISPLAY, Demo, recorded

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))  # so `demos` imports as it checks
from demos import free_set  # noqa: E402
from demos.free_set import RUN_S, Reply, Run, Step, expect, main  # noqa: E402
from demos.gridlee import demo as gridlee  # noqa: E402

Check = Callable[[Reply, Run], str]

SYSTEM = gridlee.SYSTEM
#: The names the tour gives the addresses it proves, and what it states of the sprites.
SYMBOLS = HERE / "gridlee-symbols.yaml"
MANIFEST = HERE / "gridlee-gfx.yaml"
ROM_BASE = "0xa000"
#: `INC $042B`, the instruction `find` looks for, and the program ROMs it looks in.
INC_CREDITS, ROM_BYTES = "7c042b", 0x6000
#: The player's entry of the sprite table: tile, an unused byte, y and x.
PLAYER_ENTRY, ENTRY_BYTES = 12, 4
#: The line a sprite is drawn at is its entry's y plus this.
SPRITE_Y = 17
SPRITE_W, SPRITE_H = 8, 16
#: The sweep's candidate that reads four bits a pixel in row order.
PACKED = "s1c1"
#: The frames a film judges: past the coin dropped after its arming, and done within its run.
FILM_FRAMES = 90
#: The level card's title, still while the card is up, and the level it names.
CARD_TITLE, CARD_LEVEL = [24, 104, 208, 16], [88, 152, 72, 8]
CAPTURE_FRAMES = 30
#: Where each stop of the START hands the machine back: its first instruction, and the one after
#: `LDA #$99`.
TAKE_CREDIT, AFTER_LDA = gridlee.START_BIN_PC, "0x0000d67b"

#: Reply keys the host decides in this run beyond the demos' own, each with its reason.
VOLATILE = {
    **{key: free_set.VOLATILE[key] for key in ("stdout_tail", "reads", "mark", "errorlog")},
    "since_mark": free_set.VOLATILE["mark"],
    "waited_s": "wall-clock time a wait took",
    "created_at": "the wall-clock time a declaration was made",
    "origin": "the wall-clock time and the process id of the session that declared it",
    "age_s": "wall-clock time since a declaration was made",
    "rows_path": "a file inside the per-session temporary directory",
    "cost": "the host's time inside a frame notifier",
}
START_VOLATILE = {**free_set.START_VOLATILE,
                  **{key: free_set.VOLATILE[key]
                     for key in ("window", "flags", "binary", "binary_origin")}}
WINDOW_VOLATILE = {"display": "the host's display layout",
                   "bounds": "where the host's display put the window, and how big it fits",
                   "front": "whether another window of the host's desk covers it",
                   "summary": "names the host's display and whether the window is covered"}
STATES_VOLATILE = {"bytes": free_set.SAVE_VOLATILE["bytes"]}
CAPTURES_VOLATILE = {"bytes": "a PNG's size is the host zlib's, and the list gives every file's "
                              "size under this one key"}
#: What a reply says of a machine stopped by the clock: `resume` lets it run at the host's speed.
LET_RUN = {key: "where a machine left running is stopped depends on how long the host let it run"
           for key in ("summary", "pc", "frame", "regs", "instruction", "following",
                       "average_speed")}


def new(run: Run, name: str) -> Path:
    """`name` in the run's directory, removed first: a tool writes only a path not there yet."""
    path = run.dir / name
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    return path


def boot(run: Run) -> dict[str, Any]:
    return {**free_set.boot(SYSTEM, gridlee.REFERENCE_CRC, ROM_BASE)(run), "symbols": SYMBOLS}


def player(run: Run) -> tuple[int, int, int]:
    """The player's tile and where its entry draws it, as `read_block` read them."""
    tile, _, y, x = bytes.fromhex(run.replies["sprite entry"]["hex"])
    return tile, x, y + SPRITE_Y


def player_box(run: Run) -> list[int]:
    _, x, y = player(run)
    return [x, y, SPRITE_W, SPRITE_H]


def started(reply: Reply, run: Run) -> str:
    said = free_set.started(reply, run)
    expect(reply["symbols_total"] == 7, f"{reply['symbols_total']} symbols loaded")
    return f"{said}, {reply['symbols_total']} symbols"


def alive(reply: Reply, run: Run) -> str:
    expect(reply["system"] == SYSTEM and reply["pc"] == "0x0000f000",
           f"{reply['system']} at {reply['pc']}")
    return f"{reply['system']} alive, parked at {reply['pc']}"


def shown(reply: Reply, run: Run) -> str:
    window = reply["window"]
    expect(window["onscreen"] is True and window["fullscreen"] is False, f"window {window}")
    return "the window is on screen, not fullscreen"


def mapped(reply: Reply, run: Run) -> str:
    counts = reply["counts"]
    expect((counts["cpus"], counts["regions"], counts["shares"], counts["screens"])
           == (1, 3, 3, 1), f"counts {counts}")
    expect(":spriteram" in {s["tag"] for s in reply["shares"]}, f"shares {reply['shares']}")
    return (f"{counts['cpus']} cpu, {counts['address_map']} map entries, "
            f"{counts['regions']} regions, {counts['shares']} shares")


def one_cpu(reply: Reply, run: Run) -> str:
    cpus = reply["cpus"]
    expect(len(cpus) == 1 and cpus[0]["cpu"] == ":maincpu" and cpus[0]["visible"] is True,
           f"cpus {cpus}")
    return f"{cpus[0]['cpu']}, visible, pc {cpus[0]['pc']['value']}"


def rom_ok(reply: Reply, run: Run) -> str:
    expect(reply["rom_check"] == "OK", f"rom_check {reply['rom_check']}")
    return f"the ROM at {ROM_BASE} is the reference image"


def named(reply: Reply, run: Run) -> str:
    found = {s["name"]: s["addr"] for s in reply["symbols"]}
    want = {"credits": gridlee.at(gridlee.CREDITS_BIN),
            "credits_bcd": gridlee.at(gridlee.CREDITS_BCD)}
    expect(found == want, f"found {found}")
    return f"credits at {found['credits']}, credits_bcd at {found['credits_bcd']}"


def vector(reply: Reply, run: Run) -> str:
    expect(reply["hex"] == "fd80", f"the IRQ vector holds {reply['hex']}")
    return "the IRQ vector points at 0xfd80, which the symbols name irq"


def base_register(reply: Reply, run: Run) -> str:
    entry = reply["entries"][0] if reply["entries"] else {}
    expect(reply["entries_total"] == 1 and entry.get("id") == "ay8910:register:0x08..0x0A"
           and entry["rows"], f"entries {reply['entries']}")
    return (f"the base answers the AY-3-8910's {entry['name']} whole, in "
            f"{len(entry['rows'])} rows")


def one_writer(reply: Reply, run: Run) -> str:
    expect(reply["hits"] == [gridlee.COIN_BIN_PC], f"hits {reply['hits']}")
    return f"one INC $042B in the ROMs, at {reply['hits'][0]}"


def commented(reply: Reply, run: Run) -> str:
    expect(reply["comment"]["ref"] == "count_coin", f"comment {reply['comment']}")
    return f"a comment on count_coin: {reply['comment']['text']}"


def one_comment(reply: Reply, run: Run) -> str:
    expect(reply["comments_total"] == 1 and reply["comments"][0]["ref"] == "count_coin",
           f"comments {reply['comments']}")
    return f"one comment, on {reply['comments'][0]['ref']}"


def unthrottled(reply: Reply, run: Run) -> str:
    expect(reply["on"] is False and reply["pending"] is True, f"throttle {dict(reply)}")
    return f"the throttle goes off at the next run, tagged {reply['tag']}"


def tagged(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "TARGET" and run.replies["throttle"]["tag"] in reply["line"],
           f"verdict {reply['verdict']}, line {reply.get('line')}")
    return f"the log holds the tag: {reply['line']}"


def signed(reply: Reply, run: Run) -> str:
    expect(len(reply["signature"]) == 16 and (reply["width"], reply["height"]) == (256, 240),
           f"signature {reply['signature']}, {reply['width']}x{reply['height']}")
    return f"the attract screen signs as {reply['signature']}"


def counted_in_log(reply: Reply, run: Run) -> str:
    verify = reply["verify"]
    expect(verify["seen"] is True and verify["verdict"] == "TARGET", f"verify {verify}")
    return f"a coin, and the log said: {verify['line']}"


def coin_lines(reply: Reply, run: Run) -> str:
    expect(any(line.endswith("coin counter on") for line in reply["lines"]),
           f"lines {reply['lines']}")
    return f"{reply['lines_total']} lines name the coin counter"


def one_state(reply: Reply, run: Run) -> str:
    names = [s["name"] for s in reply["states"]]
    expect(names == [run.replies["save"]["name"]], f"states {names}")
    return f"one state, {names[0]}, saved at frame {reply['states'][0]['frame']}"


def entry_read(reply: Reply, run: Run) -> str:
    expect(reply["tag"] == ":spriteram" and len(reply["hex"]) == 2 * ENTRY_BYTES,
           f"{reply['tag']}: {reply['hex']}")
    tile, x, y = player(run)
    expect(tile != 0, f"the entry at offset {PLAYER_ENTRY} is empty: {reply['hex']}")
    return f"the entry {reply['hex']}: tile {tile}, drawn at ({x}, {y})"


def pen_read(reply: Reply, run: Run) -> str:
    expect(reply["screen_indexed"] is True and reply["color"].startswith("#"),
           f"indexed {reply['screen_indexed']}, colour {reply['color']}")
    return f"pixel ({reply['x']}, {reply['y']}) is pen {reply['pen']}, {reply['color']}"


def pens(reply: Reply, run: Run) -> str:
    pixel = run.replies["pixel"]
    expect(reply["colors"][pixel["pen"] - reply["first"]] == pixel["color"],
           f"pen {pixel['pen']} is {pixel['color']} on the screen, and the palette says "
           f"{reply['colors']}")
    return f"{reply['count']} pens from {reply['first']} of {reply['entries']}"


def swept(reply: Reply, run: Run) -> str:
    what = {c["id"]: c["what"] for c in reply["candidates"]}
    expect(PACKED in what and Path(reply["image"]["path"]).is_file(), f"candidates {what}")
    return f"{len(what)} candidates drawn, {PACKED} is {what[PACKED]}"


def located(reply: Reply, run: Run) -> str:
    tile, x, y = player(run)
    expect(reply["matches_total"] == 1, f"{reply['matches_total']} matches")
    match = reply["matches"][0]
    expect((match["layout"], match["tile"], match["window"]) == (PACKED, tile, [x, y]),
           f"matched {match}, and the entry says tile {tile} at ({x}, {y})")
    return f"tile {tile} of gfx1 is on the screen at ({x}, {y}), where the entry draws it"


def drafted(reply: Reply, run: Run) -> str:
    expect(list(reply["formats"].values()) == ["human"] and reply["chose"]["candidate"] == PACKED,
           f"formats {reply['formats']}, chose {reply.get('chose')}")
    expect(Path(reply["manifest"]["path"]).is_file(), f"no draft at {reply['manifest']['path']}")
    return f"a draft with the format chosen, {next(iter(reply['formats']))}"


def manifest_loaded(reply: Reply, run: Run) -> str:
    expect(reply["loaded"] is True and reply["draft"] is False and "player" in reply["commands"],
           f"loaded {reply['loaded']}, commands {reply['commands']}")
    return f"formats {sorted(reply['formats'])}, commands {sorted(reply['commands'])}"


def viewed(reply: Reply, run: Run) -> str:
    def stated(layout: Mapping[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in layout.items() if k != "name"}
    proved = run.replies["locate"]["candidates"][0]["layout"]
    expect(stated(reply["layout"]) == stated(proved),
           f"the manifest's layout is {reply['layout']}, and gfx_locate matched under {proved}")
    expect(reply["real_colors"] is True and Path(reply["image"]["path"]).is_file(),
           f"real_colors {reply['real_colors']}, image {reply['image']}")
    last = reply["first"] + reply["count"] - 1
    return f"tiles {reply['first']} to {last} in the palette's colours"


def captured(reply: Reply, run: Run) -> str:
    watch, ran = (r["reply"] for r in reply["ran"])
    expect(watch["mode"] == "capture" and ran["verdict"] == "ELAPSED",
           f"mode {watch['mode']}, verdict {ran['verdict']}")
    fired = ran["watches"][0]
    expect(fired["state"] == "captured" and fired["total"] > 0,
           f"the capture is {fired['state']} with {fired['total']} rows")
    return (f"a capture of the player's entry on each write of the next one, and frame "
            f"{ran['frame_after']} reached")


def boxed(reply: Reply, run: Run) -> str:
    tile, x, y = player(run)
    blit = reply["blits"][-1]
    box = blit["box"]
    expect([box["x"], box["y"], box["width"], box["height"]] == [x, y, SPRITE_W, SPRITE_H],
           f"the box is {box}, and gfx_locate found the tile at ({x}, {y})")
    expect(blit["fields"]["source_tile"] == tile, f"the blit names tile {blit['fields']}")
    expect(blit["symbol"].startswith("write_sprites"), f"written from {blit['symbol']}")
    return (f"frame {reply['frame_blit']}: the box of tile {tile}, written from "
            f"{blit['symbol']}, is where gfx_locate found it")


def cleared(kind: str, n: int) -> Check:
    def check(reply: Reply, run: Run) -> str:
        expect(reply["declarations_cleared"] == n, f"{reply['declarations_cleared']} cleared")
        return f"{n} {kind} cleared"
    return check


def film_armed(reply: Reply, run: Run) -> str:
    film = reply["film"]
    expect(reply["armed_now"] is True and film["trigger_addr"] == gridlee.at(gridlee.CREDITS_BIN),
           f"armed {reply['armed_now']}, film {film}")
    return (f"a film of the frames that write credits: {film['frames']} to judge, at most "
            f"{film['keep']} pictures to keep")


def at_target(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "TARGET" and reply["pc"] == gridlee.COIN_BIN_PC,
           f"verdict {reply['verdict']} at {reply['pc']}")
    expect(reply["control_hits"] > 0, "the control never ran")
    return f"reached count_coin, the control counted {reply['control_hits']}"


def stepped(reply: Reply, run: Run) -> str:
    expect(reply["instructions_completed"] == 1 and reply["pc"] == gridlee.COIN_BIN_STOP,
           f"{reply['instructions_completed']} completed, pc {reply['pc']}")
    return f"one instruction, INC $042B, and pc {reply['pc']}"


def watching(reply: Reply, run: Run) -> str:
    expect(reply["mode"] == "change" and reply["addr"] == gridlee.at(gridlee.CREDITS_BCD)
           and reply["armed"] is True, f"mode {reply['mode']} at {reply['addr']}")
    return f"a change watch on credits_bcd, {reply['addr']}"


def trail(reply: Reply, run: Run) -> str:
    lines = gridlee.folded(reply["lines"])
    want = ["B583: INC $042B", "B586: LDA #$01", "B588: ADDA $042C", "B58B: DAA",
            "B58C: STA $042C"]
    expect(lines[-len(want) - 1:-1] == want, f"the trail is {reply['lines']}")
    return "the trail: INC $042B, LDA #$01, ADDA $042C, DAA, STA $042C"


def regs(reply: Reply, run: Run) -> str:
    regs = reply["regs"]
    expect(int(regs["PC"], 16) == int(gridlee.COIN_BCD_STOP, 16) and int(regs["A"], 16) == 3,
           f"PC {regs['PC']}, A {regs['A']}")
    return f"PC {regs['PC']}, A {regs['A']}: the BCD credits just written"


def armed_at(addr: str) -> Check:
    def check(reply: Reply, run: Run) -> str:
        expect(reply["armed"] is True and reply["addr"] == addr,
               f"armed {reply['armed']} at {reply.get('addr')}")
        return f"a breakpoint on {reply['ref']}, {reply['addr']}"
    return check


def held(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "OTHER_STOP" and reply["pc"] == TAKE_CREDIT
           and reply["released"] is False,
           f"verdict {reply['verdict']} at {reply['pc']}, released {reply['released']}")
    return f"START stopped at the breakpoint, {reply['pc']}, still held"


def regpoint_armed(reply: Reply, run: Run) -> str:
    expect(reply["armed"] is True, f"armed {reply['armed']}")
    return f"a registerpoint on {reply['ref']}"


def loaded_99(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "OTHER_STOP" and reply["regpoint_hit"]["pc"] == AFTER_LDA,
           f"verdict {reply['verdict']}, hit {reply.get('regpoint_hit')}")
    return f"A became 0x99 at {reply['regpoint_hit']['pc']}, after LDA #$99"


def declared(reply: Reply, run: Run) -> str:
    refs = {kind: sorted(row["ref"] for row in reply[kind])
            for kind in ("breakpoints", "regpoints", "watches")}
    want = {"breakpoints": ["take_credit", "wait_frame"], "regpoints": ["a==99"],
            "watches": ["credits_bcd"]}
    expect(refs == want, f"declared {refs}")
    return "two breakpoints, a registerpoint and a watch are declared"


def card_mapped(reply: Reply, run: Run) -> str:
    expect(reply["screen"] == "level_card" and reply["match"][0]["crop"] == CARD_TITLE,
           f"screen {reply['screen']}, match {reply['match']}")
    return f"the level card mapped by its title, signed {reply['match'][0]['signature']}"


def card_found(reply: Reply, run: Run) -> str:
    expect(reply["matched"] is True and reply["screen"] == "level_card"
           and [c["name"] for c in reply["controls"]] == ["level"],
           f"matched {reply['matched']}: {reply.get('screen')}")
    return f"the screen is {reply['screen']}, with its control {reply['controls'][0]['name']}"


def filmed(reply: Reply, run: Run) -> str:
    expect(reply["state"] == "finished" and (reply["met"], reply["kept"]) == (1, 1),
           f"{reply['state']}: {reply['met']} met, {reply['kept']} kept")
    cell = reply["cells"][0]
    expect(cell["pc"] == gridlee.COIN_BIN_PC and Path(cell["path"]).is_file(), f"cell {cell}")
    return (f"of {reply['judged']} frames one wrote credits, {cell['frame']}, from "
            f"{cell['symbol']}")


def started_game(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED" and reply["released"] is True,
           f"verdict {reply['verdict']}, released {reply['released']}")
    return "START, held four frames and released"


def card_reached(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "TARGET" and reply["screen"]["name"] == "level_card"
           and reply["already"] is False, f"verdict {reply['verdict']}: {reply.get('screen')}")
    return f"the level card is whole at frame {reply['frame']}, {reply['frames']} frames on"


def series(run: Run) -> dict[str, Any]:
    first = run.replies["a is 99"]["frame"] + 4
    return {"first": first, "last": first + 24, "step": 8, "dest": new(run, "series"),
            "seconds": RUN_S}


def series_kept(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED" and reply["count"] == 4 and reply["lost"] == []
           and Path(reply["manifest"]).is_file(), f"count {reply['count']}, lost {reply['lost']}")
    return f"{reply['count']} frames, {reply['first']} to {reply['last']}, and their manifest"


def sound(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED" and reply["began"] is True and reply["ended"] is True
           and reply["samples"] > 0 and Path(reply["path"]).is_file(),
           f"verdict {reply['verdict']}, {reply['samples']} samples")
    return (f"{reply['samples']} samples at {reply['sample_rate_hz']} Hz, "
            f"from {reply['sample_min']} to {reply['sample_max']}")


def snapped(reply: Reply, run: Run) -> str:
    picture = png.decode(Path(reply["path"]).read_bytes())
    row = len(picture.pixels) // picture.height
    lines = {picture.pixels[at:at + row] for at in range(0, len(picture.pixels), row)}
    expect(len(lines) > 1, "every line of the picture is the same: nothing is drawn in it")
    return (f"a picture of {picture.width} x {picture.height}, saved through the "
            f"{reply['view']} view")


def trace_to(run: Run) -> dict[str, Any]:
    new(run, "trace-txt-set.jsonl")  # `trace` writes the set of addresses beside its file
    return {"frames": 2, "dest": new(run, "trace.txt"), "seconds": RUN_S}


def traced(reply: Reply, run: Run) -> str:
    trace = reply["trace"]
    names = {s["symbol"] for s in trace["symbols"]}
    expect(reply["verdict"] == "ELAPSED" and trace["instructions"] > 0 and "irq" in names,
           f"verdict {reply['verdict']}, symbols {names}")
    return (f"{trace['instructions']} instructions at {trace['addresses']} addresses, "
            f"in {sorted(names)}")


def listed(reply: Reply, run: Run) -> str:
    kinds = {c["kind"] for c in reply["captures"]}
    expect({"avi", "wav", "png", "trace"} <= kinds
           and all(c["present"] for c in reply["captures"]), f"kinds {kinds}")
    return f"{len(reply['captures'])} files, of kinds {sorted(kinds)}"


def dumped(reply: Reply, run: Run) -> str:
    image = (run.dir / f"{SYSTEM}.ref").read_bytes()
    expect(Path(reply["path"]).read_bytes() == image, "the dump is not the reference image")
    return f"{reply['bytes']} bytes from {ROM_BASE}, the reference image's"


def described(reply: Reply, run: Run) -> str:
    expect(reply["output"] == "Gridlee\n", f"output {reply['output']!r}")
    return "the machine describes itself as Gridlee"


def watchdog(reply: Reply, run: Run) -> str:
    expect("watchdog_timer_device::reset_w" in reply["output"] and reply["mutates"] is False,
           f"output {reply['output']!r}")
    return "0x9380 is written through watchdog_timer_device::reset_w"


def written(reply: Reply, run: Run) -> str:
    expect(reply["verified"] is True and reply["readback"] == "0909",
           f"verified {reply['verified']}, read back {reply['readback']}")
    return "both credit bytes written 9 and read back"


def forced(reply: Reply, run: Run) -> str:
    expect(reply["verified"] is True and reply["readback"] == "0x42",
           f"verified {reply['verified']}, read back {reply['readback']}")
    return f"{reply['register']} forced to {reply['readback']}"


def exported(reply: Reply, run: Run) -> str:
    expect(reply["checks"] == 3 and reply["cut"].get("available") is False
           and Path(reply["path"]).is_file(),
           f"{reply['steps']} steps, {reply['checks']} checks, cut {reply['cut']}")
    return (f"{reply['steps']} steps exported whole: the vector, the signature and the credits "
            "are their checks")


def reviewed(reply: Reply, run: Run) -> str:
    entries = sorted(c["entry"] for c in reply["candidates"])
    expect("maps/gridlee" in entries and not (run.dir / ".scry").exists(),
           f"candidates {entries}")
    return f"a review, nothing written: {', '.join(entries)}"


def rebooted(reply: Reply, run: Run) -> str:
    expect(reply["verified"] is True and reply["pc"] == reply["boot_pc"] == "0x0000f000",
           f"verified {reply['verified']}, pc {reply['pc']}")
    return f"a soft reset, back at {reply['pc']}"


def let_go(reply: Reply, run: Run) -> str:
    expect(reply["session"]["running"] is True, f"session {reply['session']}")
    return "the machine runs"


def interrupted(reply: Reply, run: Run) -> str:
    expect(reply["interrupted"] is True and reply["session"]["running"] is False,
           f"interrupted {reply['interrupted']}")
    return "stopped where it was"


def two_frames(run: Run) -> dict[str, Any]:
    kept = run.replies["series"]
    a, b = (run.dir / "series" / f"f{kept[end]:06d}.png" for end in ("first", "last"))
    return {"method": "image", "a": a, "b": b}


def frames_differ(reply: Reply, run: Run) -> str:
    expect(reply["differing_pixels"] > 0 and (reply["width"], reply["height"]) == (256, 240),
           f"{reply['differing_pixels']} pixels differ over {reply['width']}x{reply['height']}")
    return f"{reply['differing_pixels']} pixels differ between the two frames"


def measured(reply: Reply, run: Run) -> str:
    channel = reply["measures"][0]
    recording = run.replies["sound"]
    flat = recording["sample_min"] == recording["sample_max"] == 0
    expect(reply["channels"] == recording["channels"] and channel["silent"] is flat,
           f"silent {channel['silent']}, and the recording ran from {recording['sample_min']} "
           f"to {recording['sample_max']}")
    return f"one channel at {reply['sample_rate_hz']} Hz, silent {channel['silent']}"


STEPS = [
    Step("start", "start", boot, started, options=True, volatile=START_VOLATILE),
    Step("status", "status", {}, alive),
    Step("window", "window", {}, shown, volatile=WINDOW_VOLATILE),
    Step("machine", "machine_map", {}, mapped),
    Step("cpus", "cpu_info", {}, one_cpu),
    Step("rom", "rom_check", lambda run: {"reference_rom": run.dir / f"{SYSTEM}.ref",
                                          "reference_addr": ROM_BASE,
                                          "reference_base": ROM_BASE}, rom_ok,
         volatile={"summary": "quotes the wall-clock time a query took"}),
    Step("names", "symbols_find", {"name": "cred"}, named),
    Step("irq vector", "read_memory", {"ref": "0xfff8", "length": 2}, vector),
    Step("base", "knowledge_find", {"kind": "register", "key": "0x08", "scope": "ay8910"},
         base_register),
    Step("coin routine", "disassemble", {"ref": "count_coin", "length": 12}, gridlee.listed),
    Step("find", "find", {"data_hex": INC_CREDITS, "ref": ROM_BASE, "length": ROM_BYTES},
         one_writer),
    Step("comment", "comment_write", {"method": "add", "ref": "count_coin",
                                      "text": "a coin: INC credits, then the BCD copy"},
         commented),
    Step("comments", "comment_list", {}, one_comment),
    Step("throttle", "throttle", {"on": False}, unthrottled),
    Step("attract", "run_for", {"milliseconds": 5000, "seconds": RUN_S},
         lambda reply, run: f"attract mode {free_set.ran(reply, run)}"),
    Step("throttle applied", "log_wait",
         lambda run: {"pattern": run.replies["throttle"]["tag"], "channel": "emulator"}, tagged),
    Step("signature", "screen_signature", {}, signed),
    Step("scan", "scan", {"method": "start", "ref": gridlee.RAM, "length": gridlee.RAM_BYTES},
         free_set.scanned(gridlee.RAM, gridlee.RAM_BYTES)),
    Step("coin 1", "drive", {"act": gridlee.coin_and_run(), "expect": "coin counter on"},
         counted_in_log),
    Step("log", "log", {"pattern": "coin counter", "channel": "emulator"}, coin_lines),
    Step("film", "gfx_film", lambda run: {"trigger": "credits", "frames": FILM_FRAMES, "keep": 2,
                                          "film_dir": new(run, "film")}, film_armed),
    Step("coin 2", "perform", gridlee.coin_and_filter(2), gridlee.filtered(2)),
    Step("frames filmed", "gfx_film", {}, filmed),
    Step("credits", "read_memory", {"ref": "credits", "length": 2}, gridlee.credits_are(2, 0x02)),
    Step("export", "perform_export", lambda run: {"dest": new(run, "two-coins.json")}, exported),
    Step("save", "state_write", {"method": "save", "name": "two_credits"}, free_set.saved,
         volatile=free_set.SAVE_VOLATILE),
    Step("states", "state_list", {}, one_state, volatile=STATES_VOLATILE),
    Step("capture", "perform", {"steps": [
        {"op": "watch_add", "ref": "0xc", "mode": "capture", "length": ENTRY_BYTES,
         "trigger": "0x10"},
        {"op": "run_for", "frames": 2, "seconds": RUN_S}]}, captured),
    Step("sprite entry", "read_block", {"tag": "spriteram", "offset": PLAYER_ENTRY,
                                        "length": ENTRY_BYTES}, entry_read),
    Step("pixel", "screen_view",
         lambda run: {"mode": "pixel", "point": [player(run)[1] + 3, player(run)[2] + 8],
                      "dest": new(run, "pixel.png")}, pen_read),
    Step("palette", "palette",
         lambda run: {"first": run.replies["pixel"]["pen"] // 32 * 32, "count": 32,
                      "dest": new(run, "palette.png")}, pens),
    Step("sweep", "gfx_sweep", lambda run: {"tag": "gfx1", "planes": [4], "sizes": [[8, 16]],
                                            "count": 16, "dest": new(run, "sweep.png")}, swept),
    Step("locate", "gfx_locate", lambda run: {"layouts": [PACKED], "patch": player_box(run),
                                              "tag": "gfx1", "transparent": 0}, located),
    Step("draft", "gfx_draft",
         lambda run: {"dest": new(run, "gridlee-gfx-draft.yaml"),
                      "choose": {"candidate": PACKED, "chosen_by": "the tour"}}, drafted),
    Step("manifest", "gfx_load", {"path": MANIFEST}, manifest_loaded),
    Step("tiles", "gfx_view",
         lambda run: {"layout": "sprite", "tag": "gfx1", "palette": "palette",
                      "first": player(run)[0] // 8 * 8, "count": 8, "columns": 8,
                      "pen_base": run.replies["locate"]["matches"][0]["base"],
                      "dest": new(run, "tiles.png")}, viewed),
    Step("blits", "gfx_blits",
         lambda run: {"draw_command": "player", "frame": run.replies["sprite entry"]["frame"],
                      "area": player_box(run), "dest": new(run, "blits.png")}, boxed),
    Step("clear capture", "declaration_clear", {"kind": "watch", "all": True},
         cleared("watch", 1)),
    Step("coin 3", "input", gridlee.COIN, gridlee.dropped),
    Step("to the coin", "run_to", {"ref": "count_coin", "control": "wait_frame",
                                   "seconds": RUN_S}, at_target),
    Step("step", "step", {"count": 1}, stepped),
    Step("watch", "watch_add", {"ref": "credits_bcd", "mode": "change"}, watching),
    Step("bcd written", "run_for", {"frames": 1, "seconds": RUN_S},
         gridlee.wrote(gridlee.CREDITS_BCD, gridlee.COIN_BCD_PC, gridlee.COIN_BCD_STOP, 3,
                       "the BCD credits")),
    Step("trail", "history", {"limit": 8}, trail),
    Step("registers", "registers", {}, regs),
    Step("breakpoint", "breakpoint_at", {"ref": "take_credit"}, armed_at(TAKE_CREDIT)),
    Step("press start", "input", gridlee.START, held),
    Step("regpoint", "regpoint_add", {"condition": "a==99"}, regpoint_armed),
    Step("a is 99", "run_for", {"frames": 1, "seconds": RUN_S}, loaded_99),
    Step("declarations", "declaration_list", {}, declared),
    Step("clear breakpoints", "declaration_clear", {"kind": "breakpoint", "all": True},
         cleared("breakpoints", 2)),
    Step("clear regpoint", "declaration_clear", {"kind": "regpoint", "all": True},
         cleared("registerpoint", 1)),
    Step("clear watch", "declaration_clear", {"kind": "watch", "all": True}, cleared("watch", 1)),
    Step("series", "series_capture", series, series_kept),
    Step("to the card", "run_for", {"milliseconds": 2000, "seconds": RUN_S},
         lambda reply, run: f"the level card {free_set.ran(reply, run)}"),
    Step("map", "screen_map_write",
         {"method": "add", "screen": "level_card", "match": [CARD_TITLE],
          "controls": [{"name": "level", "rect": CARD_LEVEL}]}, card_mapped),
    Step("which screen", "screen_map_find", {}, card_found),
    Step("load", "state_write", {"method": "load", "name": "two_credits"}, free_set.loaded),
    Step("start again", "input", gridlee.START, started_game),
    # Judged frame by frame: the card is drawn over the frames after START, and the tour knows no
    # routine that runs once it is whole for a breakpoint to name.
    Step("card", "screen_wait", {"screen": "level_card", "seconds": RUN_S}, card_reached),
    Step("record", "record", lambda run: {"frames": CAPTURE_FRAMES, "dest": new(run, "card.avi"),
                                          "seconds": RUN_S}, recorded(CAPTURE_FRAMES)),
    Step("sound", "audio_record",
         lambda run: {"frames": CAPTURE_FRAMES, "dest": new(run, "card.wav"), "seconds": RUN_S},
         sound),
    Step("snapshot", "snapshot", lambda run: {"dest": new(run, "card.png")}, snapped,
         volatile={"summary": "it carries the picture's size, which the host's zlib decides"}),
    Step("trace", "trace", trace_to, traced),
    Step("captures", "captures", {}, listed, volatile=CAPTURES_VOLATILE),
    Step("dump", "memdump", lambda run: {"ref": ROM_BASE, "length": 4096,
                                         "dest": new(run, "rom.bin")}, dumped),
    Step("lua", "lua", {"script": "print(manager.machine.system.description)",
                        "read_only": True}, described),
    Step("console", "debug", {"command": "map 9380"}, watchdog),
    Step("write", "write", {"ref": "credits", "data_hex": "0909"}, written),
    Step("force", "set_register", {"name": "A", "value": "0x42"}, forced),
    Step("promote", "promote", lambda run: {"dry_run": True, "root": run.dir}, reviewed),
    Step("reset", "reset", {}, rebooted),
    Step("resume", "resume", {}, let_go),
    Step("stop", "stop", {}, interrupted, volatile=LET_RUN),
    Step("close", "close", {}, free_set.closed),
    Step("compare", "image_compare", two_frames, frames_differ),
    Step("measure", "audio_compare", lambda run: {"method": "measure",
                                                  "path": run.dir / "card.wav"}, measured),
]

DEMO = Demo(name="tour", root=ROOT, server=[sys.executable, "-m", "scry_mame.server"],
            steps=STEPS, offers=frozenset({"rompath", "display"}),
            precheck=free_set.precheck(SYSTEM), volatile=VOLATILE,
            host_args={**free_set.HOST_ARGS, "display": DISPLAY})


#: The committed copy of the run, which the reference reads its examples from.
TRANSCRIPT = HERE / "TRANSCRIPT.md"


def keep_transcript(code: int, argv: list[str]) -> int:
    """After a run where every step passed, copy its normalised transcript beside this file;
    a run sent elsewhere with `--transcript` is somebody's own and leaves the copy alone."""
    if code == 0 and not any(a.split("=", 1)[0] == "--transcript" for a in argv):
        shutil.copyfile(ROOT / "tmp" / "demos" / DEMO.name / "transcript-normalised.md",
                        TRANSCRIPT)
        print(f"kept: {TRANSCRIPT}")
    return code


if __name__ == "__main__":
    sys.exit(keep_transcript(main(DEMO), sys.argv[1:]))
