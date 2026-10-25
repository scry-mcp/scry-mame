"""What every demo on a free mamedev.org set shares.

The set is free for non-commercial use from mamedev.org only, so a demo says where to get it
and never carries it.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from scry_core import live_host
from scry_core.demo import Demo, Reply, Run, Step, StepFailed, main
from scry_core.reply_contract import Invalid

import mame_binary  # isort: skip -- the repository root, which each demo puts on the path

__all__ = ["RUN_S", "Demo", "Reply", "Run", "Step", "demo", "expect", "main"]

#: Wall-clock bound on one timed run: a board can emulate well below real speed under the debugger.
RUN_S = 300
#: Reply keys that differ between two honest runs, each with its reason.
VOLATILE = {
    "stdout_tail": "the emulator's console as `close` found it, which echoes the session's "
                   "temporary paths",
    "reads": "how often a timed run polled the emulated clock, paced by wall time",
    "flags": "the window's placement, which the host's own helper decides",
    "binary": "where the host installed MAME",
    "binary_origin": "how the host's MAME was found",
}

HOST_ARGS = {"rompath": "the directory the host keeps its ROM sets in"}

START_VOLATILE = {"summary": "names where the host installed MAME"}


def expect(holds: bool, why: str) -> None:
    if not holds:
        raise StepFailed(why)


def url(system: str) -> str:
    return f"https://www.mamedev.org/roms/{system}/{system}.zip"


def precheck(system: str) -> Callable[[Run], str]:
    """Why the demo cannot run, or "". An unresolvable binary is left to `start`."""
    def check(run: Run) -> str:
        relative = [f"--{k} {v}" for k, v in run.options.items()
                    if k in ("rompath", "binary") and not Path(v).is_absolute()]
        if relative:
            return f"the server takes absolute paths only: {', '.join(relative)}"
        rompath = run.options.get("rompath")
        if not rompath or not (Path(rompath) / f"{system}.zip").is_file():
            return (f"no {system}.zip in --rompath ({rompath or 'not given'}). Get it from "
                    f"{url(system)} (free for non-commercial use, from mamedev.org only), put "
                    f"it in a directory, check it with `mame -rompath <dir> -verifyroms "
                    f"{system}` and pass that directory as --rompath")
        try:
            binary = mame_binary.resolve(run.options.get("binary", "")).path
        except Invalid:
            return ""
        return live_host.canary(mame_binary.canary_argv(binary, system, rompath,
                                                        "-joystickprovider", "none"))
    return check


def boot(system: str, crc: int, addr: str) -> Callable[[Run], dict[str, Any]]:
    """`start`'s arguments: the reference image found in the zip by CRC, an ini that turns the
    joystick provider off (a debug build can abort at boot with a controller connected), and an
    emptied state directory, since `state_write(method="save")` never overwrites."""
    def args(run: Run) -> dict[str, Any]:
        with zipfile.ZipFile(Path(run.options["rompath"]) / f"{system}.zip") as z:
            members = [i for i in z.infolist() if crc == i.CRC]
            expect(len(members) == 1, f"{system}.zip holds {len(members)} ROMs with CRC "
                                      f"{crc:08X}, not one: not the set this demo checks the "
                                      "machine against")
            image = z.read(members[0])
        reference = run.dir / f"{system}.ref"
        reference.write_bytes(image)
        ini = run.dir / f"{system}-ini"
        ini.mkdir(exist_ok=True)
        (ini / "mame.ini").write_text("joystickprovider none\n", encoding="ascii")
        states = run.dir / f"{system}-states"
        shutil.rmtree(states, ignore_errors=True)
        states.mkdir()
        return {"system": system, "reference_rom": reference, "reference_addr": addr,
                "reference_base": addr, "inipath": ini, "state_dir": states,
                "boot_seconds": 60}  # the wait for the debugger stub to answer at boot
    return args


def started(reply: Reply, run: Run) -> str:
    expect(reply["rom_check"] == "OK", f"rom_check {reply['rom_check']}")
    return f"{reply['system']} on MAME {reply['version']}, rom_check OK, pc {reply['pc']}"


def ran(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED", f"verdict {reply['verdict']}")
    expect(reply["frame_after"] > reply["frame_before"], "the frame counter did not move")
    return f"ran to frame {reply['frame_after']}, {reply['cycles']} cycles"


def scanned(ref: str, length: int) -> Callable[[Reply, Run], str]:
    def check(reply: Reply, run: Run) -> str:
        expect(reply["hits_total"] == length, f"{reply['hits_total']} candidates")
        return f"{reply['hits_total']} candidate bytes in {ref}+{length:#x}"
    return check


def saved(reply: Reply, run: Run) -> str:
    expect(Path(reply["path"]).is_file(), f"no state file at {reply['path']}")
    return f"state {reply['name']} saved at frame {reply['frame']}"


def loaded(reply: Reply, run: Run) -> str:
    """The state `save` wrote, loaded back at its frame and verified."""
    expect(reply["verified"] is True, f"verified {reply['verified']}")
    expect(reply["frame"] == run.replies["save"]["frame"], f"loaded at frame {reply['frame']}")
    return f"state {reply['name']} loaded and verified, frame {reply['frame']}"


def pictured(what: str) -> Callable[[Reply, Run], str]:
    """The capture `screen_view` wrote at the run's `screen.png`."""
    def check(reply: Reply, run: Run) -> str:
        image = reply["image"]
        expect(Path(image["path"]) == run.dir / "screen.png" and Path(image["path"]).is_file(),
               f"the picture is at {image['path']}")
        return f"{what}, {reply['width']}x{reply['height']}, sha256 {image['sha256'][:12]}"
    return check


def closed(reply: Reply, run: Run) -> str:
    expect(reply["ended_by"] == "quit", f"ended by {reply['ended_by']}")
    return "closed: MAME quit on its own"


def demo(system: str, demo_file: str, steps: Sequence[Step]) -> Demo:
    """The demo of `system` whose `demo.py` is `demo_file`."""
    here = Path(demo_file).resolve().parent
    root = here.parents[1]
    return Demo(name=system, root=root, server=[sys.executable, str(root / "server.py")],
                readme=here / "README.md", front=root / "README.md", steps=steps,
                capture=lambda run: run.dir / "screen.png",
                offers=frozenset({"rompath", "shared"}), precheck=precheck(system),
                volatile=VOLATILE, host_args=HOST_ARGS)
