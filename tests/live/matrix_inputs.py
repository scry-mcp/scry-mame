"""Section O of the live matrix: the inputs every tool shares, read by one rule each.

An address is written `0x`, any other ref is a symbol, and bare hex naming no symbol is refused
with the `0x` spelling: on circus (no symbol file at all) and on m68k-dual, whose table holds
`adc`, a name that is also valid hex. Each cell carries its own control: the other spelling of
the same place, read through the same tool, or the row the call must leave alone.

`live_matrix.py` registers this section before H; run alone, it is the same machinery over this
section only:

    MAME_STOCK_BINARY=... MAME_TEST_ROMS=... uv run python tests/live/matrix_inputs.py

v30-alt (its copy on the bench) carries the io port cell, the one board here with an io space.
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any

from bench_boards import SYMBOLS, board_missing, m68k_dual_missing
from live_harness import (
    BOOT,
    Board,
    boards_cover,
    boot,
    call,
    cell,
    circus_boot,
    free_boards_missing,
    fresh,
    ok,
    refused,
    run_boards,
    run_sections,
    said,
    section,
)
from matrix_acceptance import V30_ALT, v30_boot

import mame_declarations as dec  # isort: skip -- found through the path the harness sets
import mame_symbols as syms  # isort: skip -- found through the path the harness sets

O_TITLE = "inputs: an address only with 0x, one reading per ref, the store's old rows kept"
O_CELLS = [f"O{n} {text}" for n, text in enumerate([
    "circus, no symbols: 0x1000 reads, bare 1000 is refused naming 0x1000",
    "m68k-dual: adc reads the symbol and 0xadc the address, each as its memdump holds it",
    "a comment by the name adc and one at 0xadc: a delete by the name leaves the raw one",
    "after a rebuild, a delete by the name in another case leaves the stale raw comment",
    "a list whose third step is bare hex is refused before anything ran, nothing written",
    "irq_vblank then IRQ_VBLANK is one breakpoint, and a third case clears it",
    "a store row by address in bare hex, of this build, loads and re-arms in the 0x spelling",
    "0X4A0 is an address, and a ref padded with spaces reads as the trimmed one",
    "by=\"address\" with bare hex and by=\"symbol\" with 0x are refused, the list unchanged",
    "0x alone and 0x before non-hex are refused as starting like an address",
    "v30-alt: a port written 0x8 is tapped, the bare port 8 is refused naming 0x8",
    "start with a bare reference_addr is refused before any MAME runs",
], start=1)]
MAIN = ":maincpu"


def _addr(r: dict[str, Any]) -> str:
    return str(r.get("addr", ""))


def _o_circus(t: list[str]) -> None:
    circus_boot()
    good, bare = call("read_memory", ref="0x1000", length=4), call("read_memory", ref="1000")
    cell(t[0], ok(good) and _addr(good) == "0x00001000" and refused(bare, "unknown_ref")
         and "an address is written 0x1000" in str(bare.get("message")),
         f"{said(good, 60)} / {said(bare, 90)}")
    call("close")


def _dumped(ref: str) -> str:
    dest = fresh(".bin")
    r = call("memdump", ref=ref, length=4, dest=dest)
    return Path(dest).read_bytes().hex() if ok(r) and Path(dest).is_file() else f"<{said(r)}>"


def _o_m68k_dual(t: list[str]) -> None:
    seeded = _legacy_row()
    r = boot()
    if not ok(r):
        raise RuntimeError(f"m68k-dual did not boot: {said(r)}")
    listed = call("breakpoint_list").get("breakpoints") or []
    rows = [(b.get("ref"), b.get("by"), b.get("state")) for b in listed]
    bplist = str(call("debug", command="bplist").get("output", ""))
    built = (r.get("declarations") or {}).get("fingerprint")
    cell(t[6], built == seeded and rows == [("0x4a0", "address", "armed")]
         and re.search(r"\b0*4A0\b", bplist.upper()) is not None,
         f"{said(r, 50)} / {rows} / {bplist.strip()[:60]}")
    call("breakpoint_clear", all=True)
    found = call("symbols_find", name="adc", cpu="maincpu")
    adc = str((found.get("symbols") or [{}])[0].get("addr", ""))
    by_name, by_hex = call("read_memory", ref="adc", length=4), call("read_memory", ref="0xadc",
                                                                       length=4)
    cell(t[1], bool(adc) and int(adc, 16) != 0xADC and ok(by_name) and ok(by_hex)
         and int(_addr(by_name), 16) == int(adc, 16) and _addr(by_hex) == "0x00000adc"
         and by_name.get("hex") == _dumped("adc") and by_hex.get("hex") == _dumped("0xadc"),
         f"adc at {adc}: {said(by_name, 60)} / {said(by_hex, 60)}")
    call("comment_add", ref="0xadc", text="matrix raw", cpu="maincpu")
    call("comment_add", ref="adc", text="matrix name", cpu="maincpu")
    gone = call("comment_delete", ref="adc", cpu="maincpu")
    left = [c.get("ref") for c in call("comment_list").get("comments") or []]
    cell(t[2], ok(gone) and (gone.get("deleted") or {}).get("ref") == "adc"
         and left == ["0xadc"], f"{said(gone)} / left {left}")
    call("comment_delete", ref="0xadc", cpu="maincpu")
    before = call("status").get("session", {}).get("altering_writes")
    ram = call("read_memory", ref="0x200000", length=2)
    r = call("perform", steps=[{"op": "read_memory", "ref": "0x200000", "length": 2},
                               {"op": "write", "ref": "0x200000",
                                "data_hex": str(ram.get("hex", "0000"))},
                               {"op": "read_memory", "ref": "4a0", "length": 2}],
             settle_seconds=5.0)
    after = call("status").get("session", {}).get("altering_writes")
    said_r = str(r.get("message"))
    cell(t[4], ok(ram) and refused(r, "unknown_ref") and "before anything ran" in said_r
         and "0x4a0" in said_r and before == after,
         f"writes {before} -> {after}: {said(r)}")
    first, again = call("breakpoint_at", ref="irq_vblank"), call("breakpoint_at", ref="IRQ_VBLANK")
    held = call("breakpoint_list").get("breakpoints") or []
    cleared = call("breakpoint_clear", ref="Irq_Vblank")
    cell(t[5], ok(first) and again.get("already_stored") is True and len(held) == 1
         and cleared.get("declarations_cleared") == 1
         and call("breakpoint_list").get("breakpoints") == [],
         f"{said(again)} / held {len(held)} / {said(cleared)}")
    upper, padded = call("read_memory", ref="0X4A0", length=2), call("read_memory",
                                                                    ref=" 0x400 ", length=2)
    cell(t[7], ok(upper) and _addr(upper) == "0x000004a0" and ok(padded)
         and _addr(padded) == "0x00000400", f"{said(upper, 60)} / {said(padded, 60)}")
    before = call("breakpoint_list").get("breakpoints")
    bare = call("breakpoint_at", ref="4a0", by="address")
    contra = call("breakpoint_at", ref="0x4a0", by="symbol")
    after = call("breakpoint_list").get("breakpoints")
    cell(t[8], refused(bare, "bad_argument") and "an address is written 0x4a0" in str(
        bare.get("message")) and refused(contra, "bad_argument") and "by symbol names a symbol"
         in str(contra.get("message")) and before == after == [],
         f"{said(bare, 60)} / {said(contra, 60)}")
    edge = [call("read_memory", ref=r, length=2) for r in ("0x", "0xzz")]
    cell(t[9], all(refused(e, "bad_argument") and "starts like an address" in str(
        e.get("message")) for e in edge), " / ".join(said(e, 60) for e in edge))
    call("close")
    _rebuilt(t)
    bare_start = boot(reference_addr="0")
    alive = call("status").get("alive")
    cell(t[11], refused(bare_start, "bad_argument") and "an address is written 0x0" in str(
        bare_start.get("message")) and alive is False, f"{said(bare_start, 80)} / alive {alive}")
    if alive:
        call("close")


def _o_v30_alt(t: list[str]) -> None:
    v30_boot(V30_ALT)
    tap = call("watch_add", ref="0x8", mode="count", space="io", length=2)
    bare = call("watch_add", ref="8", mode="count", space="io", length=2)
    cell(t[10], ok(tap) and refused(bare, "bad_argument")
         and "an address is written 0x8" in str(bare.get("message")),
         f"{said(tap, 50)} / {said(bare, 60)}")
    if ok(tap) and tap.get("ref"):
        call("watch_clear", ref=tap["ref"], space="io")
    call("close")


def _legacy_row() -> str:
    """The store as an older version wrote it: a breakpoint by address in bare hex, on the key
    `start` reads for m68k-dual's symbol file, in this section's own state directory, declared
    against the build this section boots (its fingerprint, which a raw address re-arms over).
    Answers that fingerprint, for the cell to compare with the one `start` computes."""
    path = dec.default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    build = syms.fingerprint(str(BOOT["system"]), Path(str(BOOT["reference_rom"])), Path(SYMBOLS))
    row = {"kind": "breakpoint", "by": "address", "ref": "4A0", "cpu": MAIN, "fingerprint": build}
    path.write_text(json.dumps({dec.store_key(str(BOOT["system"]), SYMBOLS): [row]}))
    return build


def _rebuilt(t: list[str]) -> None:
    """A raw comment at `page_bit_compose_a`'s address and an unshowable one by `irq_vblank`,
    then a rebuild (a copy of the symbol file, rewritten in place) that moves `irq_vblank` onto
    the raw one's place: the raw comment is another build's (`stale`), the named one the
    caller's, and a delete by the name in another case reaches the named one."""
    copy = Path(fresh(".yaml"))
    shutil.copyfile(SYMBOLS, copy)
    r = boot(symbols=str(copy))
    if not ok(r):
        raise RuntimeError(f"m68k-dual did not boot on the copy: {said(r)}")
    raw = str((call("symbols_find", name="page_bit_compose_a").get("symbols") or [{}])[0]
              .get("addr", ""))
    call("comment_add", ref=f"{int(raw, 16):#x}", text="matrix old raw", cpu="maincpu")
    call("comment_add", ref="irq_vblank", text='matrix "q"', cpu="maincpu")
    call("close")
    text = copy.read_text()
    moved = text.replace("addr: 0x00000400\n    name: irq_vblank",
                         f"addr: {int(raw, 16):#010x}\n    name: irq_vblank_moved_from_400\n"
                         f"  - addr: {int(raw, 16):#010x}\n    name: irq_vblank", 1)
    copy.write_text(moved)
    r = boot(symbols=str(copy))
    gone = call("comment_delete", ref="IRQ_VBLANK", cpu="maincpu")
    rows = [(c.get("ref"), c.get("state")) for c in call("comment_list").get("comments") or []]
    cell(t[3], moved != text and ok(r) and (gone.get("deleted") or {}).get("ref") == "irq_vblank"
         and rows == [(f"{int(raw, 16):#x}", "stale")], f"{said(gone)} / rows {rows}")
    call("comment_delete", ref=f"{int(raw, 16):#x}", cpu="maincpu")
    call("close")


O_BOARDS = (Board(_o_circus, (0,), free_boards_missing),
            Board(_o_m68k_dual, (1, 2, 3, 4, 5, 6, 7, 8, 9, 11), m68k_dual_missing),
            Board(_o_v30_alt, (10,), lambda: board_missing("v30-alt")))
boards_cover("O_BOARDS", O_CELLS, O_BOARDS)


def register_o() -> None:
    """Register section O with the matrix: after every section registered before it."""
    section("O", O_TITLE, O_CELLS)(lambda: run_boards(O_CELLS, O_BOARDS))


if __name__ == "__main__":
    register_o()
    run_sections("SECTION O")
