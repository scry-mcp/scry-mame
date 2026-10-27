"""Section H of the live matrix: contracts at the edges of boards other than m68k-dual.

A board that cannot run on this host has its cells BLOCKED with the reason, never passed.
Run alone, it is the same machinery over this section only:

    MAME_BINARY=... MAME_TEST_ROMS=... uv run python tests/live/matrix_acceptance.py
"""

import json
import re
from pathlib import Path
from typing import Any

from bench_boards import (
    BINARY,
    M68K_DUAL_SYSTEM,
    MANIFEST,
    ROMPATH,
    V30_REFERENCE_ROM,
    V30_SYMBOLS,
    board_dir,
    board_missing,
    m68k_dual_missing,
    value,
)
from gfx_layouts import CIRCUS_CHAR
from live_harness import (
    START_WAIT_S,
    WAIT_CEILING_S,
    Board,
    boards_cover,
    boot,
    call,
    cell,
    circus_boot,
    free_boards_missing,
    fresh,
    fresh_state,
    ok,
    pangofun_boot,
    pangofun_missing,
    refused,
    require_booted,
    run_boards,
    run_frames,
    run_sections,
    said,
    section,
    unavailable_why,
)

import mame_lexer as lexer  # isort: skip -- found through the path the harness sets
import mame_ramdac as mramdac  # isort: skip

V30_PENS = (1, 17, 100, 200, 255)
V30_ALT_PENS = (16, 17, 512, 1022)

H_TITLE = "contracts at the edges of boards other than m68k-dual, each on the board exposing it"
H_CELLS = [f"H{n} {text}" for n, text in enumerate([
    "circus: write(region=True) at 0x11f0 patches the ROM region :maincpu, reads the bytes back, "
    "and is restored",
    "circus: read_memory at 0x10000, past the program space, is refused naming its mask",
    "circus: read_memory of 4 bytes at 0xfffe, running past the space's end, is refused",
    "circus: write at 0x10000, past the program space, is refused and writes nothing",
    "circus: find past the space and memdump across its wrap are refused naming the mask, and the "
    "memdump leaves no file",
    "circus: a control past the debugger's temps is refused for want of one, and only the controls "
    "holding a temp are listed",
    "circus: a change watch over 0x9..0xc is refused while 0xb is a change watch, and only 0xb "
    "is listed",
    "circus: run_for(milliseconds=1) inside a frame is no_progress, with the stop's survey and "
    "the machine stopped",
    "circus: run_to reaching its target with a control that never counted is ok",
    "circus: a one-byte show watch on the 6502 reads the byte read_memory reads",
    "circus: gfx_locate from a ref with no count is refused",
    "circus: gfx_load of the project's manifest is refused naming the systems it describes",
    "m68k-dual: palette_log lists its setters up to the cut, their total beside them and every "
    "one in the file it names",
    "v30: read_block at 0x81a20 is refused: its map entry names no share and no region",
    f"v30: the sequence log's pens {', '.join(map(str, V30_PENS))} are the palette's, none "
    "unsynced",
    "v30: the digit Draw_BNumber draws is tile 1 of ten at (52, 104), and the draft proves "
    "tiles_24x24x8",
    "v30-alt: a count watch of two bytes at 0xecb1 is refused for splitting a bus word",
    "v30-alt: an io count on port 0x8 is not stored, and one on port 0x7e, which nothing handles, "
    "is armed saying so and tallies the cpu's own out there",
    f"v30-alt: the latch log's pens {', '.join(map(str, V30_ALT_PENS))} are the palette's, none "
    "unsynced",
    "v30-alt: the first run after a state_write load has no cycles, and says why",
    "v30-alt: an io count of two bytes at the odd port 0x9 is refused for splitting the io bus's "
    "16-bit word, naming the counts in the io space",
    "pangofun: the i486's own out of a dword at port 0xe2 reaches an io tap as two 32-bit bus "
    "word fragments; a count there is refused naming one per word, and declared back, the one at "
    "0xe2 tallies its half and the one at 0xe4, which nothing handles, the other half, where the "
    "aligned 0xe0 one tallies the dword whole",
], start=1)]

PALETTE_MANIFESTS = Path(__file__).resolve().parent / "fixtures"


#: Shorter than `LEG_FRAMES`: these boards run below real speed.
RUN_STEP_FRAMES = 100


def palette_manifest(name: str, label: str) -> str:
    """A copy of the tracked palette manifest `name` with `systems` set to board `label`'s set.

    The line must match exactly once: a miss would load the tracked file unchanged."""
    line = f"systems: [{value(label, 'system')}]"
    text, n = re.subn(r"(?m)^systems: \[[^\]\n]*\]$", lambda _m: line,
                      (PALETTE_MANIFESTS / name).read_text(encoding="utf-8"))
    if n != 1:
        raise RuntimeError(f"{name} has {n} `systems:` lines where one was expected")
    out = Path(fresh(".yaml"))
    out.write_text(text, encoding="utf-8")
    return str(out)

def _run_frames(frames: int) -> list[str]:
    """Run `frames` in legs; what the run said if it was not ELAPSED, else empty."""
    r = run_frames(frames, RUN_STEP_FRAMES)
    return [] if ok(r) and r.get("verdict") == "ELAPSED" else [said(r, 60)]


def _palette_log_matches(port: str, pens: tuple[int, ...]) -> tuple[bool, str]:
    """Whether each pen's logged colour equals the live palette's and no write is unplaced."""
    pairs = []
    for pen in pens:
        logged = call("palette_log", palette_port=port, pen=pen, limit=1).get("pen_state") or {}
        live = (call("palette", first=pen, count=1).get("colors") or [None])[0]
        pairs.append((pen, logged.get("color"), live))
    whole_log = call("palette_log", palette_port=port, limit=0)
    # pens all one colour agree however the log placed its writes
    agree = (ok(whole_log) and "unsynced_writes" not in whole_log
             and all(log is not None and log == live for _, log, live in pairs)
             and len({live for _, _, live in pairs}) > 1)
    return agree, f"unsynced {whole_log.get('unsynced_writes')}; {pairs}"


CONTROLS = [f"{0x1300 + i:#x}" for i in range(lexer.TEMPS)]
ONE_CONTROL_TOO_MANY = f"{0x1300 + lexer.TEMPS:#x}"


def _h_circus(t: list[str]) -> None:
    circus_boot()
    call("run_for", frames=60, seconds=WAIT_CEILING_S)
    was = str(call("read_memory", ref="0x11f0", length=1).get("hex", ""))
    new = f"{int(was or '0', 16) ^ 0xFF:02x}"
    patched = call("write", ref="0x11f0", data_hex=new, region=True)
    back = call("write", ref="0x11f0", data_hex=was, region=True)
    now = call("read_memory", ref="0x11f0", length=1).get("hex")
    cell(t[0], ok(patched) and patched.get("verified") is True and patched.get("readback") == new
         and patched.get("region") == ":maincpu" and ok(back) and back.get("verified") is True
         and now == was, f"{was} -> {new} -> {now}: {said(patched)}")

    r = call("read_memory", ref="0x10000", length=2)
    cell(t[1], refused(r, "bad_argument") and "0xffff" in str(r.get("message")), said(r))
    r = call("read_memory", ref="0xfffe", length=4)
    cell(t[2], refused(r, "bad_argument") and "0xffff" in str(r.get("message")), said(r))
    # byte 0 is where a write wrapped under the mask would land
    first = str(call("read_memory", ref="0x0", length=1).get("hex", ""))
    before = call("status").get("session", {}).get("altering_writes")
    r = call("write", ref="0x10000", data_hex=f"{int(first or '0', 16) ^ 0xFF:02x}")
    after = call("status").get("session", {}).get("altering_writes")
    now = call("read_memory", ref="0x0", length=1).get("hex")
    cell(t[3], refused(r, "bad_argument") and after == before and bool(first) and now == first,
         f"writes {before} -> {after}, byte 0 {first} -> {now}: {said(r)}")
    found = call("find", data_hex="a2", ref="0x0", length=0x10000 + 1)
    dest = fresh(".bin")
    dumped = call("memdump", ref="0xfff0", length=32, dest=dest)
    cell(t[4], refused(found, "bad_argument") and "0xffff" in str(found.get("message"))
         and refused(dumped, "bad_argument") and "0xffff" in str(dumped.get("message"))
         and not Path(dest).exists(), f"{said(found, 60)} / {said(dumped, 60)}")

    byte = call("read_memory", ref="0xa", length=1).get("hex", "")
    r = call("watch_add", ref="0xa", mode="show", length=1)
    reading = r.get("reading") or {}
    cell(t[9], ok(r) and bool(byte) and reading.get("available") is True
         and reading.get("raw_hex") == byte and reading.get("value") == int(byte, 16),
         f"read_memory {byte}; reading {reading}")
    call("declaration_clear", kind="watch", ref="0xa")

    call("watch_add", ref="0xb", mode="change", length=1)
    r = call("watch_add", ref="0x9", mode="change", length=4)
    listed = [w.get("ref") for w in call("declaration_list", kind="watch").get("watches", [])]
    cell(t[6], refused(r, "ambiguous_ref") and listed == ["0xb"], f"listed {listed}: {said(r)}")
    call("declaration_clear", kind="watch", all=True)

    for ref in CONTROLS:
        call("breakpoint_at", ref=ref, role="control")
    r = call("breakpoint_at", ref=ONE_CONTROL_TOO_MANY, role="control")
    rows = call("declaration_list", kind="breakpoint").get("breakpoints", [])
    cell(t[5], refused(r, "bad_argument") and "temp" in str(r.get("message"))
         and sorted(b.get("ref") for b in rows) == sorted(CONTROLS)
         and all(b.get("state") == "armed" for b in rows),
         f"{[(b.get('ref'), b.get('state')) for b in rows]}: {said(r)}")
    call("declaration_clear", kind="breakpoint", all=True)

    # 0x80 is a `brk` never reached, 0x12f7 the main loop
    r = call("run_to", ref="0x12f7", control="0x80", seconds=WAIT_CEILING_S)
    cell(t[8], ok(r) and r.get("verdict") == "TARGET" and r.get("control_hits") == 0, said(r))
    call("declaration_clear", kind="breakpoint", all=True)

    # from a frame's stop, a millisecond cannot reach the next vblank
    call("run_for", frames=1, seconds=WAIT_CEILING_S)
    r = call("run_for", milliseconds=1, seconds=WAIT_CEILING_S)
    cell(t[7], refused(r, "no_progress") and "stop_seq" in r and "pc" in r
         and r["session"].get("running") is False, said(r))

    r = call("gfx_locate", layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], ref="0x4000",
             flips=["none"])
    cell(t[10], refused(r, "bad_argument") and "`count`" in str(r.get("message")), said(r))
    r = call("gfx_load", path=MANIFEST)
    cell(t[11], refused(r, "bad_argument") and M68K_DUAL_SYSTEM in (r.get("systems") or [])
         and "circus" in str(r.get("message")), said(r))
    call("close")


M68K_DUAL_SETTERS = 256  # unrolled upload: one writer pc per pen


def _h_m68k_dual(t: list[str]) -> None:
    require_booted("m68k-dual", boot())
    loaded = call("gfx_load", path=MANIFEST)
    armed = call("palette_log", palette_port="ramdac", arm=True)
    call("run_for", frames=60, seconds=WAIT_CEILING_S)
    r = call("palette_log", palette_port="ramdac", limit=0)
    setters = r.get("setters") or []
    path = Path(str(r.get("setters_path")))
    every = json.loads(path.read_text()) if r.get("setters_path") and path.is_file() else None
    cell(t[12], ok(loaded) and ok(armed) and ok(r)
         and len(setters) == min(M68K_DUAL_SETTERS, mramdac.SETTERS_LISTED_MAX)
         and r.get("setters_total") == M68K_DUAL_SETTERS and isinstance(every, list)
         and len(every) == M68K_DUAL_SETTERS and every[:len(setters)] == setters,
         f"{len(setters)} listed, total {r.get('setters_total')}, file "
         f"{len(every) if isinstance(every, list) else None}")
    call("close")


# Per V30 board: label, then start's arguments; paths are relative to the board's bench directory,
# and the binary is the one MAME (absolute, so the join leaves it as it is).

V30 = ("v30", {"binary": BINARY, "system": value("v30", "system"),
                  "rompath": ROMPATH, "inipath": "run", "reference_rom": V30_REFERENCE_ROM,
                  "reference_addr": "0x30000", "reference_base": "0x0"})
V30_BOOT_SYMBOLS = (V30_SYMBOLS, {"DATA": "0x400", value("v30", "rom_segment"): "rom"})
V30_ALT = ("v30-alt", {"binary": BINARY, "system": value("v30-alt", "system"),
                      "rompath": ROMPATH, "inipath": "run",
                      "reference_rom": value("v30-alt", "reference_rom"),
                      "reference_addr": "0xFFFF0", "reference_base": "0x20000"})
PATHS = ("binary", "rompath", "inipath", "reference_rom")

# v30's score digit: 24x24 pixels, a byte a pixel as eight planes; ten digits from 0x81a20
DIGIT_ROW_BITS = 24 * 8
V30_DIGIT: dict[str, Any] = {
    "width": 24, "height": 24, "planes": 8, "planeoffset": "STEP8(0,1)",
    "xoffset": list(range(0, DIGIT_ROW_BITS, 8)),
    "yoffset": list(range(0, 24 * DIGIT_ROW_BITS, DIGIT_ROW_BITS)),
    "charincrement": 24 * DIGIT_ROW_BITS}


def v30_boot(board: tuple[str, dict[str, str]],
             symbols: tuple[str, dict[str, str]] | None = None) -> dict[str, Any]:
    label, args = board
    root = board_dir(label)
    kw: dict[str, Any] = {k: str(root / v) if k in PATHS else v for k, v in args.items()}
    if symbols is not None:
        kw.update(symbols=str(root / symbols[0]), bases=symbols[1])
    return require_booted(label, call("start", boot_seconds=START_WAIT_S, **kw))


def _h_v30(t: list[str]) -> None:
    v30_boot(V30)
    # a `sequence` log knows the index only from the start
    call("gfx_load", path=palette_manifest("v30-palette.yaml", "v30"))
    call("palette_log", palette_port="pal", arm=True)
    r = call("read_block", ref="0x81a20", length=16)
    cell(t[13], refused(r, "unknown_ref") and "no share and no region" in str(r.get("message")),
         said(r))
    short = _run_frames(600)
    agree, detail = _palette_log_matches("pal", V30_PENS)
    cell(t[14], agree and not short, f"{short} {detail}")
    call("close")

    v30_boot(V30, V30_BOOT_SYMBOLS)
    short = _run_frames(300)
    reached = call("run_to", ref="Draw_BNumber", control="Next_Frame", seconds=WAIT_CEILING_S)
    call("run_for", frames=2, seconds=WAIT_CEILING_S)
    r = call("gfx_locate", layouts=[V30_DIGIT], patch=[52, 104, 24, 24], ref="0x81a20",
             count=10, transparent=0, flips=["none"], seconds=WAIT_CEILING_S)
    m = (r.get("matches") or [{}])[0]
    draft = call("gfx_draft", dest=fresh(".yaml"))
    cell(t[15], not short and reached.get("verdict") == "TARGET"
         and ok(r) and r.get("matches_total") == 1 and m.get("tile") == 1
         and m.get("window") == [52, 104]
         and (draft.get("formats") or {}).get("tiles_24x24x8") == "proved",
         f"{short} {said(reached, 40)} / {said(r, 60)} / {said(draft, 60)}")
    call("declaration_clear", kind="breakpoint", ref="Next_Frame")
    call("close")


# The V30's own `out`, planted and stepped, so a tally is a write the cell caused.
V30_ALT_CODE_ADDR = 0x8000
V30_ALT_OUT_WORD = 0x1234


def _v30_out_word(port: int, value: int) -> None:
    """Run `mov dx, port; mov ax, value; out dx, ax; jmp $` from V30_ALT_CODE_ADDR."""
    code = bytes([0xBA, port & 0xFF, port >> 8, 0xB8, value & 0xFF, value >> 8, 0xEF, 0xEB, 0xFE])
    call("write", ref=hex(V30_ALT_CODE_ADDR), data_hex=code.hex())
    call("set_register", name="CS", value=0)
    call("set_register", name="EIP", value=V30_ALT_CODE_ADDR)
    # a count's install waits in the console pipe and a step reads none: drain it first
    call("lua", script='print("drained")')
    call("step", count=3)


def _h_v30_alt(t: list[str]) -> None:
    v30_boot(V30_ALT)
    r = call("watch_add", ref="0xecb1", mode="count", length=2)
    cell(t[16], refused(r, "bad_argument") and "split" in str(r.get("message")), said(r))
    tap = call("watch_add", ref="0x8", mode="count", space="io", length=2)
    if ok(tap) and tap.get("ref"):
        call("declaration_clear", kind="watch", ref=tap["ref"], space="io")
    odd = call("watch_add", ref="0x9", mode="count", space="io", length=2)
    cell(t[20], refused(odd, "bad_argument") and "split a 16-bit bus word" in str(
        odd.get("message")) and 'space="io"' in str(odd.get("message")), said(odd, 160))
    call("gfx_load", path=palette_manifest("v30-alt-palette.yaml", "v30-alt"))
    call("palette_log", palette_port="pal", arm=True)
    short = _run_frames(600)
    agree, detail = _palette_log_matches("pal", V30_ALT_PENS)
    cell(t[18], agree and not short, f"{short} {detail}")
    name = fresh_state()
    call("state_write", method="save", name=name)
    call("run_for", frames=3, seconds=WAIT_CEILING_S)
    call("state_write", method="load", name=name)
    r = call("run_for", frames=1, seconds=WAIT_CEILING_S)
    cell(t[19], ok(r) and "cycles" in r and bool(unavailable_why(r["cycles"])),
         said(r))
    # LAST: the planted code leaves the cpu in `jmp $`, and cells before need the game running
    none = call("watch_add", ref="0x7e", mode="count", space="io", length=2)
    _v30_out_word(0x7E, V30_ALT_OUT_WORD)
    none_values = _io_count_values("0x7e")
    cell(t[17], ok(tap) and tap.get("stored") is False and ok(none)
         and none.get("write_maps_to") == "unmapped"
         and "nothing in the machine handles an `out` at port 0x7e" in str(none.get("note"))
         and none_values == [V30_ALT_OUT_WORD],
         f"{said(tap, 50)} / {said(none, 50)} / {none_values}")
    call("close")


# Ports 0xe0..0xe7 are mapped to nothing that reacts (`nopw`). The dword goes out from code the
# cpu runs, since the accesses under test are its own bus cycles; the bios is still in real mode,
# which the 16-bit encoding assumes.
PANGOFUN_CODE_ADDR = 0x8000
PANGOFUN_DWORD = 0x12345678
# Globals: the dump is another chunk, and the tap lives for the session.
PANGOFUN_IO_TAP_LUA = """
local io_space = manager.machine.devices[":maincpu"].spaces["io"]
IO_TAP_LOG = {}
IO_TAP = io_space:install_write_tap(0xe0, 0xe7, "io_tap", function(offset, data, mask)
  IO_TAP_LOG[#IO_TAP_LOG + 1] = string.format("%x:%x:%x", offset, data, mask)
end)
"""
PANGOFUN_IO_TAP_DUMP = 'print(table.concat(IO_TAP_LOG, " ")); IO_TAP_LOG = {}'


def _bus_log_of_out_dword(port: int) -> str:
    """The io tap's `offset:data:mask` log (hex) of an `out dx, eax` of PANGOFUN_DWORD."""
    code = bytes([0xFA, 0xBA, port & 0xFF, port >> 8, 0x66, 0xB8,
                  *PANGOFUN_DWORD.to_bytes(4, "little"), 0x66, 0xEF, 0xEB, 0xFE])
    call("write", ref=hex(PANGOFUN_CODE_ADDR), data_hex=code.hex())
    call("set_register", name="CS", value=0)
    call("set_register", name="EIP", value=PANGOFUN_CODE_ADDR)
    call("lua", script=PANGOFUN_IO_TAP_DUMP)
    call("step", count=4)
    return str(call("lua", script=PANGOFUN_IO_TAP_DUMP).get("output", "")).strip()


def _io_count_values(ref: str) -> list[object]:
    """The values the io count at `ref` tallied, [] when none."""
    watch: dict[str, Any] = next((w for w in call("declaration_list",
                                                  kind="watch").get("watches") or []
                                  if (w.get("ref"), w.get("space")) == (ref, "io")), {})
    return [v.get("value") for v in watch.get("values") or []]


def _h_pangofun(t: list[str]) -> None:
    pangofun_boot()
    ran = call("run_for", frames=30, seconds=WAIT_CEILING_S)
    call("lua", script=PANGOFUN_IO_TAP_LUA)
    aligned_add = call("watch_add", ref="0xe0", mode="count", space="io", length=4)
    aligned_log = _bus_log_of_out_dword(0xe0)
    aligned_values = _io_count_values("0xe0")
    split_add = call("watch_add", ref="0xe2", mode="count", space="io", length=4)
    left_behind = _io_count_values("0xe2")
    half = call("watch_add", ref="0xe2", mode="count", space="io", length=2)
    other_half = call("watch_add", ref="0xe4", mode="count", space="io", length=2)
    split_log = _bus_log_of_out_dword(0xe2)
    half_values = _io_count_values("0xe2")
    other_values = _io_count_values("0xe4")
    remedy = ('declare one count per bus word it touches, each then written whole: '
              '`watch_add(ref="0xe2", mode="count", length=2, space="io")` and the same at 0xe4 '
              '(length=2)')
    cell(t[21], ok(ran) and ran.get("verdict") == "ELAPSED"
         and ok(aligned_add) and aligned_log == f"e0:{PANGOFUN_DWORD:x}:ffffffff"
         and aligned_values == [PANGOFUN_DWORD]
         and refused(split_add, "bad_argument")
         and "split a 32-bit bus word" in str(split_add.get("message"))
         and str(split_add.get("message")).endswith(remedy) and left_behind == []
         and ok(half) and split_log == "e0:56780000:ffff0000 e4:1234:ffff"
         and half_values == [0x5678]
         and ok(other_half) and other_half.get("write_maps_to") == "unmapped"
         and other_values == [0x1234],
         f"aligned {aligned_log!r} {aligned_values} / split {split_log!r} {half_values} "
         f"{other_values} / {said(split_add, 120)} / {said(other_half, 80)}")
    call("close")


H_BOARDS = (
    Board(_h_circus, tuple(range(12)), free_boards_missing),
    Board(_h_m68k_dual, (12,), m68k_dual_missing),
    Board(_h_v30, (13, 14, 15), lambda: board_missing("v30")),
    Board(_h_v30_alt, (16, 17, 18, 19, 20),
          lambda: board_missing("v30-alt")),
    Board(_h_pangofun, (21,), pangofun_missing),
)
boards_cover("H_BOARDS", H_CELLS, H_BOARDS)


def register_h() -> None:
    """Register section H with the matrix: after every section registered before it."""
    section("H", H_TITLE, H_CELLS)(lambda: run_boards(H_CELLS, H_BOARDS))


if __name__ == "__main__":
    register_h()
    run_sections("LIVE MATRIX, SECTION H")
