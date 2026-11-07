"""The Speed Fight demo on MAME: the arcade game's own `.scry/` boots it. `--help` says how to
run it. The game is the reader's checkout (`--cwd`); nothing of it is in this repository.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from scry_core.demo import Demo, Reply, Run, Step, expect, main
from scry_core.game_demo import arrived, word_is

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `demos` imports as it checks
from demos import free_set  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYSTEM = "speedf"
#: What the game's checkout holds once built: the recipe, the linker's image and the romset
#: staged with its map. The recipe names the last two as well; the precheck reads them here so
#: a checkout that is not built is refused with its own words before `start` is paid for.
PROFILE = Path(".scry/start/speedf.json")
IMAGE = Path("build/speedf.bin")
ROMSET = Path("run/mame_roms")
#: The attract's demo entry, and the video interrupt that runs every frame around it.
TARGET, CONTROL = "startdemo", "new_irq_video"
#: The reply keys a boot from the recipe fills with the reader's own paths.
VOLATILE_GAME = {**free_set.VOLATILE,
                 "name": "where the reader's checkout keeps its recipe",
                 "file": "where the reader's checkout keeps its recipe",
                 "key": "the draft's identity, which names the reader's checkout"}


def game(run: Run) -> Path:
    return Path(str(run.options["cwd"])).expanduser()


def romset(run: Run) -> Path:
    """The romset directory: the caller's, else the one the recipe names."""
    given = run.options.get("rompath")
    return Path(str(given)) if given else game(run) / ROMSET


def own_romset(run: Run) -> bool:
    """Whether the caller's romset is another directory than the recipe's: only then is it
    handed to `start`, so a call naming the recipe's own directory leaves the recipe to fill it."""
    return romset(run).resolve() != (game(run) / ROMSET).resolve()


def precheck(run: Run) -> str:
    """Why the demo cannot run, or ""; an unresolvable binary is left to `start`."""
    if relative := free_set.absolute_only(run):
        return relative
    cwd = run.options.get("cwd")
    if not cwd:
        return ("pass --cwd, the reader's checkout of the game: its .scry/ declares the recipe, "
                "and its build/ and run/ hold what the recipe names")
    missing = [p.as_posix() for p in (PROFILE, IMAGE) if not (game(run) / p).is_file()]
    if missing:
        return f"no {' or '.join(missing)} under --cwd {cwd}: build the game first"
    if not (romset(run) / f"{SYSTEM}.zip").is_file():
        return f"no {SYSTEM}.zip in {romset(run)}: stage the romset first"
    if not (game(run) / ROMSET / f"{SYSTEM}.map").is_file():
        return (f"no {(ROMSET / SYSTEM).as_posix()}.map under --cwd {cwd}: the recipe reads the "
                "symbols there whatever --rompath names")
    return free_set.host_ready(run, SYSTEM, str(romset(run)))


def boot(run: Run) -> dict[str, Any]:
    """The game's recipe, plus what is the run's own: its ini and state directories."""
    ini, states = free_set.fresh_dirs(run, SYSTEM)
    args: dict[str, Any] = {"profile": str(game(run) / PROFILE), "inipath": ini,
                            "state_dir": states, "shared": True}
    if own_romset(run):
        args["rompath"] = romset(run)  # the caller wins over the recipe
    return args


def started(reply: Reply, run: Run) -> str:
    free_set.booted(reply)
    supplied = reply["profile"]["supplied"]
    expect("system" in supplied and "reference_rom" in supplied and "symbols" in supplied,
           f"the recipe supplied {supplied}")
    return (f"{reply['system']} on MAME from the game's own recipe ({len(supplied)} keys), "
            f"rom_check OK, {reply['symbols_total']} symbols{free_set.retried(reply)}")


def scene(reply: Reply, run: Run) -> str:
    return f"_sceneId {bytes.fromhex(reply['hex'])[0]}: the attract dispatcher's current scene"


STEPS = [
    Step("start", "start", boot, started, options=frozenset({"binary"}),
         volatile=free_set.START_VOLATILE,
         highlight=("`start(profile=...)` boots from the recipe the game's own repository "
                    "declares: the set, the romset, the ini directory, the linker's image as "
                    "the known answer and the symbol map with its `DATA` base. The call gives "
                    "only what is the run's own, and the reply says which keys the recipe "
                    "filled.")),
    Step("to the demo", "run_to", {"ref": TARGET, "control": CONTROL, "seconds": free_set.RUN_S},
         arrived(TARGET),
         highlight=("`run_to` takes the game's own routine name from its map and runs the board "
                    "until the attract's demo starts; `control` is the video interrupt, counted "
                    "meanwhile, so a run that missed its target says whether the machine was "
                    "running at all.")),
    Step("scene", "read_memory", {"ref": "_sceneId", "length": 1}, scene),
    Step("no credits", "read_memory", {"ref": "creditos", "length": 2}, word_is("creditos", 0),
         highlight=("`creditos` is read by name through the map's `DATA` base: the map holds "
                    "the ROM address of the initialised copy, and the program reads its "
                    "variables at paragraph `0x40`, which the recipe's `bases` declares.")),
    Step("plays", "run_for", {"milliseconds": 3000, "seconds": free_set.RUN_S},
         lambda reply, run: f"the demo plays: {free_set.ran(reply, run)}"),
    Step("screen", "screen_view", lambda run: {"mode": "render", "dest": run.dir / "screen.png",
                                               "scale": 2}, free_set.pictured("the demo")),
    Step("close", "close", {}, free_set.closed),
]

DEMO = Demo(
    name=SYSTEM, root=ROOT, server=[sys.executable, "-m", "scry_mame.server"],
    readme=HERE / "README.md", steps=STEPS,
    capture=lambda run: run.dir / "screen.png",
    offers=frozenset({"cwd", "rompath"}), reads=frozenset({"cwd", "rompath"}),
    precheck=precheck,
    volatile=VOLATILE_GAME,
    host_args={"cwd": "the reader's checkout of the game",
               "rompath": "the directory the host keeps the game's romset in",
               "profile": "the reader's checkout of the game",
               "inipath": "the run's own directory",
               "state_dir": "the run's own directory"})


if __name__ == "__main__":
    sys.exit(main(DEMO))
