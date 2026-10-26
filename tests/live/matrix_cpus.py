"""Section R of the live matrix: the cpus the stub describes.

An x86 PC is a segment and an offset, so pangofun is read as `EIP` against `print eip`.

`live_matrix.py` registers this section; run alone, it is the same machinery over it only:

    MAME_STOCK_BINARY=... MAME_TEST_ROMS=... uv run python tests/live/matrix_cpus.py
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from live_harness import (
    FREE_BINARY,
    FREE_ROMS,
    PC_STEPS_MAX,
    START_WAIT_S,
    Board,
    blocked,
    boards_cover,
    call,
    cell,
    console_pc,
    free_boards_missing,
    free_boot,
    free_image,
    fresh,
    no_joystick_ini,
    ok,
    pangofun_boot,
    pangofun_missing,
    pc_of,
    refused,
    registers_at_a_telling_pc,
    run_boards,
    run_sections,
    said,
    section,
    tells_byte_order,
    zips_missing,
)


class PcBoard(NamedTuple):
    """`focus` empty: the cpu visible at the park."""
    system: str
    members: list[str]
    addr: str
    arch: str
    focus: str = ""


R_TITLE = "the stub's cpus: byte order and an unserved first cpu"
R_PC_BOARDS = (PcBoard("circus", ["9004a.1a"], "0x1000", "m6502"),
               PcBoard("robby", ["rotox1.bin"], "0x0", "z80"),
               PcBoard("gridlee", ["gridfnla.bin"], "0xa000", "m6809"),
               PcBoard("pockstat", ["kernel.bin"], "0x4000000", "arm"),
               PcBoard("tekken", ["te2verc.2l", "te2verc.2j"], "0x1fc00000", "mips"),
               PcBoard("dn3500", ["3500_boot_12191_7.bin"], "0x0", "m68k"),
               PcBoard("dn3000", ["3000_boot_8475_7.bin"], "0x0", "m68k"),
               PcBoard("hyprscan", ["hyperscan.bin"], "0x10000000", "score7"),
               PcBoard("unkts", ["am29lv400bt.u23"], "0x800000", "nios2"),
               # Parks on its Cuda mcu; the focus runs the machine until the PowerPC executes.
               PcBoard("pmac6100", ["9feb69b3.rom"], "0xffc00000", "powerpc:common",
                       ":maincpu"))
R_CELLS = [
    *[f"{b.system}: registers reads the {b.arch}'s PC as the console's print curpc at the same "
      "stop" for b in R_PC_BOARDS],
    "alienar: start refuses the mc6809e the stock stub has no description of, no_channel, "
    "quoting MAME's line, launched once",
    "pangofun: registers reads the i486's EIP as the console's print eip at the same stop",
]
def _pc_against_console(board: PcBoard, label: str) -> None:
    free_boot(board.system, board.members, board.addr)
    if board.focus:
        shown = call("focus", cpu=board.focus)
        if not ok(shown) or shown.get("cpu") != board.focus:
            cell(label, False, said(shown, 200))
            call("close")
            return
    regs = registers_at_a_telling_pc()
    pc = pc_of(regs)
    if not ok(regs):
        cell(label, False, said(regs, 200))
    elif not tells_byte_order(pc):
        blocked(label, f"no stop whose PC tells the byte order in {PC_STEPS_MAX} steps: {pc}")
    else:
        console = console_pc()
        cell(label, int(str(pc), 16) == console, f"registers pc {pc}, print curpc {console}")
    call("close")


def _r_pc(k: int) -> Callable[[list[str]], None]:
    """The runner of `R_PC_BOARDS[k]`, named after its system for `run_boards`."""
    def run(cells: list[str]) -> None:
        _pc_against_console(R_PC_BOARDS[k], cells[k])
    run.__name__ = f"_r_{R_PC_BOARDS[k].system}"
    return run


NOT_FREE = ("pockstat", "tekken", "dn3500", "dn3000", "hyprscan", "unkts", "pmac6100")


def _set_missing(system: str) -> Callable[[], str]:
    """Why `system` cannot run on this host, or empty."""
    return lambda: free_boards_missing() or (zips_missing(system) if system in NOT_FREE else "")


def _r_alienar(cells: list[str]) -> None:
    folder = Path(fresh("-image"))
    folder.mkdir()
    r = call("start", binary=FREE_BINARY, system="alienar", rompath=FREE_ROMS,
             reference_rom=free_image("alienar", ["aarom01"], folder), reference_addr="0x0",
             inipath=no_joystick_ini(), boot_seconds=START_WAIT_S)
    message = str(r.get("message"))
    if sys.platform == "win32" and refused(r, "session_broken") and "3221225477" in message:
        # MAME on Windows exits with an access violation (3221225477 is 0xC0000005) where macOS
        # prints the gdbstub's refusal, so the line this cell quotes is never written there.
        blocked(cells[ALIENAR], f"MAME exits 0xC0000005 on Windows with no refusal written: "
                f"{said(r, 120)}")
        return
    cell(cells[ALIENAR], refused(r, "no_channel") and "start_retries" not in r
         and "`Fatal error: gdbstub: cpuname mc6809e not found in gdb stub descriptions`"
         in message, said(r, 300))


def _r_pangofun(cells: list[str]) -> None:
    """The reset stop is always there, so an EIP that does not tell the byte order is a FAIL."""
    pangofun_boot()
    regs = call("registers", cpu=":maincpu")
    eip = (regs.get("regs") or {}).get("EIP")
    if not ok(regs):
        cell(cells[PANGO], False, said(regs, 200))
    else:
        console = console_pc(":maincpu", "eip")
        cell(cells[PANGO], tells_byte_order(eip) and int(str(eip), 16) == console,
             f"registers EIP {eip}, print eip {console}")
    call("close")


ALIENAR, PANGO = len(R_PC_BOARDS), len(R_PC_BOARDS) + 1
R_BOARDS = (*(Board(_r_pc(k), (k,), _set_missing(b.system)) for k, b in enumerate(R_PC_BOARDS)),
            Board(_r_alienar, (ALIENAR,), free_boards_missing),
            Board(_r_pangofun, (PANGO,), pangofun_missing))
boards_cover("section R", R_CELLS, R_BOARDS)


def register_r() -> None:
    """Register section R after every section registered before it."""
    section("R", R_TITLE, R_CELLS)(lambda: run_boards(R_CELLS, R_BOARDS))


if __name__ == "__main__":
    register_r()
    run_sections("SECTION R")
