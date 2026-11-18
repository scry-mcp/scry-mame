"""The Speed Fight demo on MAME: the arcade game's own `.scry/` boots it. `--help` says how to
run it. The game is the reader's checkout (`--cwd`); nothing of it is in this repository.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from scry_core.demo import Demo, Moment, Reply, Run, Step, expect, main, recording
from scry_core.game_demo import arrived, word_is

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `demos` imports as it checks
from demos import free_set  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYSTEM = "speedf"
#: What the game's checkout holds once built: the start profile, the linker's image and the
#: romset staged with its map. The profile names the last two as well; the precheck reads them
#: here so a checkout that is not built is refused with its own words before `start` is paid for.
PROFILE = Path(".scry/start/speedf.json")
IMAGE = Path("build/speedf.bin")
ROMSET = Path("run/mame_roms")
#: The attract's demo entry, and the video interrupt that runs every frame around it.
TARGET, CONTROL = "startdemo", "new_irq_video"
#: The frames the loop shows of the attract demo: three seconds of this screen.
PLAYS_FRAMES = 180
#: The reply keys a boot from the start profile fills with the reader's own paths.
VOLATILE_GAME = {**free_set.VOLATILE,
                 "name": "where the reader's checkout keeps its start profile",
                 "file": "where the reader's checkout keeps its start profile",
                 "key": "the draft's identity, which names the reader's checkout"}


def game(run: Run) -> Path:
    return Path(str(run.options["cwd"])).expanduser()


def romset(run: Run) -> Path:
    """The romset directory: the caller's, else the one the start profile names."""
    given = run.options.get("rompath")
    return Path(str(given)) if given else game(run) / ROMSET


def own_romset(run: Run) -> bool:
    """Whether the caller's romset is another directory than the profile's: only then is it
    handed to `start`, so a call naming the profile's own directory leaves the profile to fill
    it."""
    return romset(run).resolve() != (game(run) / ROMSET).resolve()


def precheck(run: Run) -> str:
    """Why the demo cannot run, or ""; an unresolvable binary is left to `start`."""
    if relative := free_set.absolute_only(run):
        return relative
    cwd = run.options.get("cwd")
    if not cwd:
        return ("pass --cwd, the reader's checkout of the game: its .scry/ holds the start "
                "profile, and its build/ and run/ hold what the profile names")
    missing = [p.as_posix() for p in (PROFILE, IMAGE) if not (game(run) / p).is_file()]
    if missing:
        return f"no {' or '.join(missing)} under --cwd {cwd}: build the game first"
    if not (romset(run) / f"{SYSTEM}.zip").is_file():
        return f"no {SYSTEM}.zip in {romset(run)}: stage the romset first"
    if not (game(run) / ROMSET / f"{SYSTEM}.map").is_file():
        return (f"no {(ROMSET / SYSTEM).as_posix()}.map under --cwd {cwd}: the start profile "
                "reads the symbols there whatever --rompath names")
    return free_set.host_ready(run, SYSTEM, str(romset(run)))


def boot(run: Run) -> dict[str, Any]:
    """The game's start profile, plus what is the run's own: its ini and state directories."""
    ini, states = free_set.fresh_dirs(run, SYSTEM)
    args: dict[str, Any] = {**free_set.window_args(run), "profile": str(game(run) / PROFILE),
                            "inipath": ini, "state_dir": states}
    if own_romset(run):
        args["rompath"] = romset(run)  # the caller wins over the profile
    return args


def started(reply: Reply, run: Run) -> str:
    free_set.booted(reply)
    supplied = reply["profile"]["supplied"]
    expect("system" in supplied and "reference_rom" in supplied and "symbols" in supplied,
           f"the start profile supplied {supplied}")
    return (f"{reply['system']} on MAME from the game's own start profile ({len(supplied)} keys), "
            f"rom_check OK, {reply['symbols_total']} symbols{free_set.retried(reply)}")


def scene(reply: Reply, run: Run) -> str:
    return f"_sceneId {bytes.fromhex(reply['hex'])[0]}: the attract dispatcher's current scene"


STEPS = [
    Step("start", "start", boot, started,
         options=frozenset({"binary", "display"}),
         volatile=free_set.START_VOLATILE,
         title="Start from the game's own start profile",
         ask="Start Speed Fight from the start profile its repository keeps in `.scry/start/`.",
         shown=("rom_check", "symbols_total", "kept"),
         reads=("A start profile is a saved set of `start` arguments; the call adds only this "
                "run's own. `rom_check` says the ROM in memory is the build's, `symbols_total` "
                "counts its map's names, and `kept` that a candidate was saved.")),
    Step("to the demo", "run_to", {"ref": TARGET, "control": CONTROL, "seconds": free_set.RUN_S},
         arrived(TARGET),
         title="Run to a routine by its name",
         ask=("Run the game until its attract demo starts, at `startdemo`, counting the video "
              "interrupt on the way."),
         shown=("summary", "verdict", "control_hits"),
         reads=("`TARGET` means the run stopped at `startdemo`. `control_hits` counts the video "
                "interrupt meanwhile, so a run that never arrived would still say the game was "
                "running.")),
    Step("scene", "read_memory", {"ref": "_sceneId", "length": 1}, scene),
    Step("no credits", "read_memory", {"ref": "creditos", "length": 2}, word_is("creditos", 0),
         title="Read a variable by its name",
         ask="Read the game's `creditos` variable.",
         shown=("summary", "addr", "hex"),
         reads=("`creditos` is a name from the game's symbol map. The start profile says where "
                "the game's data sits in RAM, so the name resolves to the address the program "
                "reads.")),
    recording("plays", PLAYS_FRAMES, lambda reply, run: "the attract demo plays for three seconds"),
    Step("screen", "screen_view", lambda run: {"mode": "render", "dest": run.dir / "screen.png",
                                               "scale": 2}, free_set.pictured("the demo")),
    Step("close", "close", {}, free_set.closed),
]

DEMO = Demo(
    name=SYSTEM, root=ROOT, server=[sys.executable, "-m", "scry_mame.server"],
    readme=HERE / "README.md", steps=STEPS,
    capture=lambda run: run.dir / "screen.png",
    moments=(Moment("no credits", "plays",
                    "`run_to` stopped where the attract demo starts, and `record` films it.",
                    skip=24, frames=156),),
    alt="Speed Fight's attract demo playing on the arcade board",
    offers=frozenset({"cwd", "rompath", "display"}),
    reads=frozenset({"cwd", "rompath"}), precheck=precheck,
    volatile=VOLATILE_GAME,
    host_args={"cwd": "the reader's checkout of the game",
               "rompath": "the directory the host keeps the game's romset in",
               "profile": "the reader's checkout of the game",
               "display": free_set.DISPLAY,
               "inipath": "the run's own directory",
               "state_dir": "the run's own directory"})


if __name__ == "__main__":
    sys.exit(main(DEMO))
