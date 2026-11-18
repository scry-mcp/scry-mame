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

from scry_core.demo import Demo, Lead, Reply, Run, Step, main
from scry_core.game_demo import Binding, Press
from scry_core.games import lineup

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `demos` imports as it checks
from demos import free_set  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYSTEM = "lineup"
#: The game's own `.scry/` folder declares its screen map; `--cwd` is that checkout.
SCREEN_MAP = Path(".scry/maps/lineup-screen-map.json")


def at(run: Run) -> Path:
    """The game's screen map, in the checkout `--cwd` names."""
    return Path(str(run.options["cwd"])).expanduser() / SCREEN_MAP
#: The CODE segment's base, ROM content that never changes at runtime: what `start` checks.
REFERENCE_ADDR = "0x30000"
#: DGROUP sits at paragraph 0x40 at runtime, so a DATA symbol lives at 0x400 plus its offset;
#: Juke's tile sheet is read in place from ROM.
BASES = {"DATA": "0x400", "LUP_JUKEBOX": "rom"}
#: MAME's mix on Windows differs in its last bits, the same run after run.
SOUND = Path("win32", "music.wav") if sys.platform == "win32" else Path("music.wav")
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
    if relative := free_set.absolute_only(run):
        return relative
    rompath = run.options.get("rompath", "")
    missing = [n for n in ("lineup.zip", "lineup.map")
               if not rompath or not (Path(rompath) / n).is_file()]
    if missing:
        return (f"no {' or '.join(missing)} in --rompath ({rompath or 'not given'}): pass the "
                "directory holding LineUp's romset and the symbol map beside it")
    cwd = run.options.get("cwd")
    if not cwd:
        return (f"pass --cwd, the reader's checkout of the game: its {SCREEN_MAP.as_posix()} "
                "is the map the script loads")
    if not at(run).is_file():
        return (f"no {SCREEN_MAP.as_posix()} under --cwd {cwd}: the game's own `.scry/` "
                "folder declares it")
    return free_set.host_ready(run, SYSTEM, rompath)


def boot(run: Run) -> dict[str, Any]:
    """`start`'s arguments: the reference image the zip's two halves make (1.bin the even bytes,
    2.bin the odd), the romset's map copied beside it, and the run's own ini and state
    directories."""
    rompath = Path(run.options["rompath"])
    with zipfile.ZipFile(rompath / "lineup.zip") as z:
        even, odd = z.read("1.bin"), z.read("2.bin")
    image = bytearray(len(even) + len(odd))
    image[0::2], image[1::2] = even, odd
    reference = run.dir / "lineup.ref"
    reference.write_bytes(bytes(image))
    symbols = run.dir / "lineup.map"
    shutil.copyfile(rompath / "lineup.map", symbols)
    ini, states = free_set.fresh_dirs(run, SYSTEM)
    return {**free_set.window_args(run), "system": SYSTEM, "reference_rom": reference,
            "reference_addr": REFERENCE_ADDR,
            "reference_base": "0x0", "symbols": symbols, "bases": BASES, "inipath": ini,
            "state_dir": states, "boot_seconds": 60}


def started(reply: Reply, run: Run) -> str:
    free_set.booted(reply)
    return (f"{reply['system']} on MAME, rom_check OK, {reply['symbols_total']} symbols"
            f"{free_set.retried(reply)}")


BINDING = Binding(
    platform="mame",
    boot=[Step("start", "start", boot, started,
               options=frozenset({"binary", "rompath", "display"}),
               volatile=free_set.START_VOLATILE)],
    inputs=INPUTS, rate_hz=RATE_HZ, sound=HERE / SOUND,
    map=at)

DEMO = Demo(
    name="lineup", root=ROOT, server=[sys.executable, "-m", "scry_mame.server"],
    readme=HERE / "README.md", steps=lineup.steps(BINDING),
    capture=lambda run: run.dir / "screen.png",
    moments=lineup.filmed(BINDING),
    alt="LineUp played on the arcade board: three shots, each from another column or colour",
    lead=Lead(front=ROOT / "README.md", step="credits",
              ask="A coin is in. Read the game's `Credits` variable by its name.",
              caption="LineUp on its arcade board, played through this server: each shot is one "
                      "`input` call, by the names MAME gives the controls.",
              answer=("ref", "hex"), learns=True),
    offers=frozenset({"rompath", "cwd", "display"}), reads=frozenset({"cwd"}),
    precheck=precheck,
    volatile={**free_set.VOLATILE,
              "pcm_sha256": "the recording's digest, which Windows' mix changes",
              "b": "the platform's own reference recording"},
    host_args={**free_set.HOST_ARGS, "cwd": "the reader's checkout of the game",
               "b": "the platform's own reference recording", "display": free_set.DISPLAY})


if __name__ == "__main__":
    sys.exit(main(DEMO))
