"""The LineUp demo on MAME: `scry_core.games.lineup` bound to the arcade board. `--help` says how
to run it. The romset and its symbol map are the reader's; nothing of the game is in this
repository.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

from scry_core import live_host
from scry_core.demo import Demo, Reply, Run, Step, main
from scry_core.game_demo import Binding, Press
from scry_core.games import lineup
from scry_core.reply_contract import Invalid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `demos` imports as it checks
from demos import free_set  # noqa: E402

from scry_mame import binary as mame_binary  # noqa: E402  isort: skip -- the repository root, put on the path above

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYSTEM = "lineup"
#: The CODE segment's base, ROM content that never changes at runtime: what `start` checks.
REFERENCE_ADDR = "0x30000"
#: DGROUP sits at paragraph 0x40 at runtime, so a DATA symbol lives at 0x400 plus its offset;
#: Juke's tile sheet is read in place from ROM.
BASES = {"DATA": "0x400", "LUP_JUKEBOX": "rom"}
#: The board's pixel clock over its 512 x 312 raster.
RATE_HZ = 8_000_000 / (512 * 312)
#: The game's actions on the board's first player, by the arcade source's `J_*` bits: its
#: `J_FIRE1` is bit 7, which MAME names `P1 Button 2` (the PC port swapped the two fire bits).
INPUTS = {action: Press("input", {"port": ":P1", "field": field, "frames": 4})
          for action, field in (("COIN", "Coin 1"), ("START", "1 Player Start"),
                                ("RIGHT", "P1 Right"), ("FIRE1", "P1 Button 2"),
                                ("UP", "P1 Up"))}


def precheck(run: Run) -> str:
    """Why the demo cannot run, or ""; an unresolvable binary is left to `start`."""
    relative = [f"--{k} {v}" for k, v in run.options.items()
                if k in ("rompath", "binary") and not Path(v).is_absolute()]
    if relative:
        return f"the server takes absolute paths only: {', '.join(relative)}"
    rompath = run.options.get("rompath", "")
    missing = [n for n in ("lineup.zip", "lineup.map")
               if not rompath or not (Path(rompath) / n).is_file()]
    if missing:
        return (f"no {' or '.join(missing)} in --rompath ({rompath or 'not given'}): pass the "
                "directory holding LineUp's romset and the symbol map beside it")
    try:
        binary = mame_binary.resolve(run.options.get("binary", "")).path
    except Invalid:
        return ""
    return live_host.canary(mame_binary.canary_argv(binary, SYSTEM, rompath,
                                                    "-joystickprovider", "none"))


def boot(run: Run) -> dict[str, Any]:
    """`start`'s arguments: the reference image the zip's two halves make (1.bin the even bytes,
    2.bin the odd), the romset's map copied beside it, an ini that turns the joystick provider
    off, and an emptied state directory."""
    rompath = Path(run.options["rompath"])
    with zipfile.ZipFile(rompath / "lineup.zip") as z:
        even, odd = z.read("1.bin"), z.read("2.bin")
    image = bytearray(len(even) + len(odd))
    image[0::2], image[1::2] = even, odd
    reference = run.dir / "lineup.ref"
    reference.write_bytes(bytes(image))
    symbols = run.dir / "lineup.map"
    shutil.copyfile(rompath / "lineup.map", symbols)
    ini = run.dir / "lineup-ini"
    ini.mkdir(exist_ok=True)
    (ini / "mame.ini").write_text("joystickprovider none\n", encoding="ascii")
    states = run.dir / "lineup-states"
    shutil.rmtree(states, ignore_errors=True)
    states.mkdir()
    return {"system": SYSTEM, "reference_rom": reference, "reference_addr": REFERENCE_ADDR,
            "reference_base": "0x0", "symbols": symbols, "bases": BASES, "inipath": ini,
            "state_dir": states, "shared": True, "boot_seconds": 60}


def started(reply: Reply, run: Run) -> str:
    free_set.booted(reply)
    return f"{reply['system']} on MAME, rom_check OK, {reply['symbols_total']} symbols"


BINDING = Binding(
    platform="mame",
    boot=[Step("start", "start", boot, started, options=frozenset({"binary", "rompath"}),
               volatile=free_set.START_VOLATILE)],
    inputs=INPUTS, rate_hz=RATE_HZ, sound=HERE / "music.wav")

DEMO = Demo(
    name="lineup", root=ROOT, server=[sys.executable, "-m", "scry_mame.server"],
    readme=HERE / "README.md", steps=lineup.steps(BINDING),
    capture=lambda run: run.dir / "screen.png",
    offers=frozenset({"rompath"}), precheck=precheck,
    volatile=free_set.VOLATILE, host_args=free_set.HOST_ARGS)


if __name__ == "__main__":
    sys.exit(main(DEMO))
