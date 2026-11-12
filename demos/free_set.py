"""What the MAME demos share: the boot, the checks every step runs and the shape of a demo.

A demo on a free mamedev.org set says where to get it and never carries it: the set is free
for non-commercial use from mamedev.org only. A game's own demo takes the rest.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from scry_core import live_host
from scry_core.demo import DISPLAY, Demo, Loop, Reply, Run, Step, expect, main, window_args
from scry_core.reply_contract import Invalid

from scry_mame import binary as mame_binary  # isort: skip -- the repository root, which each demo puts on the path

__all__ = ["DISPLAY", "RUN_S", "Demo", "Reply", "Run", "Step", "absolute_only", "demo", "expect",
           "fresh_dirs", "host_ready", "main", "window_args"]

#: Wall-clock bound on one timed run: a board can emulate well below real speed under the debugger.
RUN_S = 300
#: Reply keys that differ between two honest runs, each with its reason.
VOLATILE = {
    "stdout_tail": "the emulator's console as `close` found it, which echoes the session's "
                   "temporary paths",
    "reads": "how often a timed run polled the emulated clock, paced by wall time",
    "flags": "the window's flags, which name this host's display",
    "binary": "where the host installed MAME",
    "binary_origin": "how the host's MAME was found",
    "window": "where the host's display put the window, and how big it fits",
    "mark": "a byte position in the emulator's log, whose line endings are the host's",
    "how": "a hint that, on a log's replies, quotes a position whose line endings are the host's",
    "errorlog": "it carries a log position, whose line endings are the host's",
}

#: What a saved state's reply says that the host decides: MAME compresses the state, and the
#: size it comes to differs between hosts.
SAVE_VOLATILE = {"bytes": "the compressed state's size, which the host's compressor decides",
                 "summary": "it carries the compressed state's size"}

HOST_ARGS = {"rompath": "the directory the host keeps its ROM sets in"}
START_VOLATILE = {"summary": "names where the host installed MAME"}


def url(system: str) -> str:
    return f"https://www.mamedev.org/roms/{system}/{system}.zip"


def absolute_only(run: Run) -> str:
    """Why the host's paths cannot reach the server, or "": it takes absolute ones, and a
    checkout (`cwd`) absolute or `~`-led."""
    relative = [f"--{k} {v}" for k, v in run.options.items()
                if k in ("rompath", "binary", "cwd") and not Path(str(v)).is_absolute()
                and not (k == "cwd" and str(v).startswith("~"))]
    return f"the server takes absolute paths only: {', '.join(relative)}" if relative else ""


def host_ready(run: Run, system: str, rompath: str) -> str:
    """The host's MAME starting `system` off `rompath`, as the canary says; "" when the binary
    cannot be resolved, which is left to `start`."""
    try:
        binary = mame_binary.resolve(run.options.get("binary", "")).path
    except Invalid:
        return ""
    return live_host.canary(mame_binary.canary_argv(binary, system, rompath,
                                                    "-joystickprovider", "none"))


def fresh_dirs(run: Run, system: str) -> tuple[Path, Path]:
    """An ini that turns the joystick provider off (a debug build can abort at boot with a
    controller connected) and an emptied state directory, since `state_write(method="save")`
    never overwrites."""
    ini = run.dir / f"{system}-ini"
    ini.mkdir(exist_ok=True)
    (ini / "mame.ini").write_text("joystickprovider none\n", encoding="ascii")
    states = run.dir / f"{system}-states"
    shutil.rmtree(states, ignore_errors=True)
    states.mkdir()
    return ini, states


def precheck(system: str) -> Callable[[Run], str]:
    """Why the demo cannot run, or "". An unresolvable binary is left to `start`."""
    def check(run: Run) -> str:
        if relative := absolute_only(run):
            return relative
        rompath = run.options.get("rompath")
        if not rompath or not (Path(rompath) / f"{system}.zip").is_file():
            return (f"no {system}.zip in --rompath ({rompath or 'not given'}). Get it from "
                    f"{url(system)} (free for non-commercial use, from mamedev.org only), put "
                    f"it in a directory, check it with `mame -rompath <dir> -verifyroms "
                    f"{system}` and pass that directory as --rompath")
        return host_ready(run, system, rompath)
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
        ini, states = fresh_dirs(run, system)
        return {**window_args(run), "system": system, "reference_rom": reference,
                "reference_addr": addr,
                "reference_base": addr, "inipath": ini, "state_dir": states,
                "boot_seconds": 60}  # the wait for the debugger stub to answer at boot
    return args


def booted(reply: Reply) -> None:
    """A start a README may be written from: the ROM matched and the build's release was read."""
    expect(reply["rom_check"] == "OK", f"rom_check {reply['rom_check']}")
    expect(isinstance(reply["version"], str),
           f"the build's release was not read: {reply['version']}")


def retried(reply: Reply) -> str:
    """What a start that needed retries adds to its line, so the README never hides it."""
    n = len(reply.get("start_retries", []))
    return f", after {n} start {'retry' if n == 1 else 'retries'}" if n else ""


def started(reply: Reply, run: Run) -> str:
    booted(reply)
    return (f"{reply['system']} on MAME {reply['version']}, rom_check OK, pc {reply['pc']}"
            f"{retried(reply)}")


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
        return f"{what}, {reply['width']}x{reply['height']}"
    return check


def closed(reply: Reply, run: Run) -> str:
    expect(reply["ended_by"] == "quit", f"ended by {reply['ended_by']}")
    return "closed: MAME quit on its own"


def demo(system: str, demo_file: str, steps: Sequence[Step]) -> Demo:
    """The demo of `system` whose `demo.py` is `demo_file`, its loop recorded after `screen`."""
    here = Path(demo_file).resolve().parent
    root = here.parents[1]
    return Demo(name=system, root=root, server=[sys.executable, "-m", "scry_mame.server"],
                readme=here / "README.md", front=root / "README.md", steps=steps,
                capture=lambda run: run.dir / "screen.png", loop=Loop("screen"),
                offers=frozenset({"rompath", "display"}),
                precheck=precheck(system),
                volatile=VOLATILE, host_args={**HOST_ARGS, "display": DISPLAY})
