"""The starfire demo: Exidy's Star Fire (1979) on a stock MAME, driven by the calls the README's
prompt asks an MCP client to make, each answer checked. `--help` says how to run it.

The set is one of the ROMs mamedev.org distributes for free, non-commercial use, from its own
site only, so the demo says where to get it and never carries it. What it walks: the attract
mode running, a coin found in RAM by a value scan, the instruction that writes it caught by a
change watch, and a saved state that puts the credits back where they were.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

from scry_core.demo import Demo, Reply, Run, Step, StepFailed, main

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYSTEM = "starfire"
URL = f"https://www.mamedev.org/roms/{SYSTEM}/{SYSTEM}.zip"
#: The first program ROM, found in the zip by its CRC (MAME's own key, whatever the file's name):
#: the cpu sees it at 0x0, which is what `start` checks the running machine against.
REFERENCE_CRC = 0x9990AF64
#: The scratch RAM's first kilobyte. The driver mirrors it through its handler across
#: 0x8000-0x9FFF, so a scan over the whole range keeps every variable several times over.
RAM, RAM_BYTES = "0x8000", 0x400
#: The byte the scan converges on and the store that bumps it: taken from a run, asserted on
#: every run since.
CREDITS = "0x8299"
WRITER_PC = "0x00001e48"
COIN = {"port": ":SYSTEM", "field": "Coin 1", "frames": 4, "seconds": 300}
#: Half a second after a coin, which is long enough for the game to count it.
SETTLE_MS = 500
#: The `seconds` bound on one timed run, in wall-clock time: Star Fire's netlist sound keeps
#: MAME below real speed, so a run needs a generous wait.
RUN_S = 300


def expect(holds: bool, why: str) -> None:
    if not holds:
        raise StepFailed(why)


def precheck(run: Run) -> str:
    relative = [f"--{k} {v}" for k, v in run.options.items()
                if k in ("rompath", "binary") and not Path(v).is_absolute()]
    if relative:
        return f"the server takes absolute paths only: {', '.join(relative)}"
    rompath = run.options.get("rompath")
    if not rompath or not (Path(rompath) / f"{SYSTEM}.zip").is_file():
        return (f"no {SYSTEM}.zip in --rompath ({rompath or 'not given'}). Get it from {URL} "
                f"(free for non-commercial use, from mamedev.org only), put it in a directory, "
                f"check it with `mame -rompath <dir> -verifyroms {SYSTEM}` and pass that "
                f"directory as --rompath")
    return ""


def boot(run: Run) -> dict[str, Any]:
    """The reference image out of the zip, and an ini directory that turns the joystick
    provider off: a debug build can abort at boot with a controller connected, and the demo
    should not depend on what is plugged in."""
    with zipfile.ZipFile(Path(run.options["rompath"]) / f"{SYSTEM}.zip") as z:
        members = [i for i in z.infolist() if i.CRC == REFERENCE_CRC]
        expect(len(members) == 1, f"{SYSTEM}.zip holds no ROM with CRC {REFERENCE_CRC:08X}: "
                                  "not the set this demo checks the machine against")
        image = z.read(members[0])
    reference = run.dir / f"{SYSTEM}.ref"
    reference.write_bytes(image)
    ini = run.dir / "starfire-ini"
    ini.mkdir(exist_ok=True)
    (ini / "mame.ini").write_text("joystickprovider none\n", encoding="ascii")
    # The states go beside the transcript, emptied first: `state_save` never overwrites, and a
    # path under this run's own directory reads the same on every run.
    states = run.dir / "starfire-states"
    shutil.rmtree(states, ignore_errors=True)
    states.mkdir()
    return {"system": SYSTEM, "reference_rom": reference, "reference_addr": "0x0",
            "reference_base": "0x0", "inipath": ini, "state_dir": states,
            "seconds": 60}  # the wait for the debugger stub to answer at boot


def started(reply: Reply, run: Run) -> str:
    expect(reply["rom_check"] == "OK", f"rom_check {reply['rom_check']}")
    return f"{reply['system']} on MAME {reply['version']}, rom_check OK, pc {reply['pc']}"


def attract(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED", f"verdict {reply['verdict']}")
    expect(reply["frame_after"] > reply["frame_before"], "the frame counter did not move")
    return f"attract mode ran to frame {reply['frame_after']}, {reply['cycles']} cycles"


def scanned(reply: Reply, run: Run) -> str:
    expect(reply["hits_total"] == RAM_BYTES, f"{reply['hits_total']} candidates")
    return f"{reply['hits_total']} candidate bytes in {RAM}+{RAM_BYTES:#x}"


def unwatched(reply: Reply, run: Run) -> str:
    expect(reply["declarations_cleared"] == 1, f"{reply['declarations_cleared']} cleared")
    return "the watch cleared"


def closed(reply: Reply, run: Run) -> str:
    expect(reply["ended_by"] == "quit", f"ended by {reply['ended_by']}")
    return "closed: MAME quit on its own"


def coin_and_filter(credits: int) -> list[dict[str, Any]]:
    return [{"op": "input", **COIN}, {"op": "run_for", "milliseconds": SETTLE_MS, "seconds": RUN_S},
            {"op": "scan_filter", "operator": "=", "value": credits}]


def filtered(credits: int) -> Any:
    def check(reply: Reply, run: Run) -> str:
        scan = reply["ran"][-1]["reply"]
        left = scan["hits_total"]
        expect(left >= 1, f"no cell holds {credits} after coin {credits}")
        if credits == 3:
            addrs = [h["addr"] for h in scan["hits"]]
            expect(addrs == ["0x00008299"], f"after three coins the scan holds {addrs}")
            return f"coin {credits}: one cell left, {addrs[0]}, holding 3"
        return f"coin {credits}: {left} cells still hold {credits}"
    return check


def caught(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "OTHER_STOP", f"verdict {reply['verdict']}, not the watch's stop")
    hit = reply["watch_hit"]
    expect(hit["writer_pc"] == WRITER_PC, f"written by {hit['writer_pc']}")
    expect(hit["after"] == 4, f"the watch saw {hit['after']} written, not 4")
    return f"the fourth coin stopped the machine: {hit['lines'][0]}"


def listed(reply: Reply, run: Run) -> str:
    store = [ln for ln in reply["lines"] if ln.upper().startswith("1E48")]
    expect(bool(store), f"no line at 1E48 in {reply['lines']}")
    return f"the writer: {store[0]}"


def trail(reply: Reply, run: Run) -> str:
    expect(any(ln.upper().startswith("1E48") for ln in reply["lines"]),
           f"the writer is not in the trail: {reply['lines']}")
    return f"{len(reply['lines'])} instructions led there, ending {reply['lines'][-1]}"


def regs(reply: Reply, run: Run) -> str:
    expect(reply["regs"]["HL"] == "0x8299", f"HL {reply['regs']['HL']}")
    return f"HL {reply['regs']['HL']} points at the credits, A {reply['regs']['AF'][:4]}"


def released(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED", f"verdict {reply['verdict']}")
    planned = run.replies["coin 4"]["frame_release_planned"]
    expect(reply["frame_after"] > planned, f"stopped at {reply['frame_after']}, before the "
                                           f"release at {planned}")
    return f"ran on to frame {reply['frame_after']}, the coin released"


def credits_are(n: int) -> Any:
    def check(reply: Reply, run: Run) -> str:
        expect(int(reply["hex"], 16) == n, f"credits {reply['hex']}, not {n}")
        return f"credits {n}"
    return check


def saved(reply: Reply, run: Run) -> str:
    expect(Path(reply["path"]).is_file(), f"no state file at {reply['path']}")
    return f"state {reply['name']} saved at frame {reply['frame']}"


def fifth(reply: Reply, run: Run) -> str:
    expect(reply["ran"][-1]["reply"]["verdict"] == "ELAPSED", "the run after the coin was cut")
    return f"a fifth coin, run to frame {reply['ran'][-1]['reply']['frame_after']}"


def loaded(reply: Reply, run: Run) -> str:
    expect(reply["verified"] is True, f"verified {reply['verified']}")
    expect(reply["frame"] == run.replies["save"]["frame"], f"loaded at frame {reply['frame']}")
    return f"state {reply['name']} loaded and verified, frame {reply['frame']}"


def pictured(reply: Reply, run: Run) -> str:
    image = reply["image"]
    expect(Path(image["path"]) == run.dir / "screen.png" and Path(image["path"]).is_file(),
           f"the picture is at {image['path']}")
    return f"the screen, {reply['width']}x{reply['height']}, sha256 {image['sha256'][:12]}"


STEPS = [
    Step("start", "start", boot, started, options=True),
    Step("attract", "run_for", {"milliseconds": 3000, "seconds": RUN_S}, attract),
    Step("scan", "scan_start", {"ref": RAM, "length": RAM_BYTES}, scanned),
    Step("coin 1", "perform", {"steps": coin_and_filter(1), "settle_seconds": RUN_S}, filtered(1)),
    Step("coin 2", "perform", {"steps": coin_and_filter(2), "settle_seconds": RUN_S}, filtered(2)),
    Step("coin 3", "perform", {"steps": coin_and_filter(3), "settle_seconds": RUN_S}, filtered(3)),
    Step("watch", "watch_add", {"ref": CREDITS, "mode": "change", "fmt": "u8"},
         lambda reply, run: f"a change watch armed at {reply['addr']}"),
    Step("coin 4", "input", COIN, caught),
    Step("writer", "disassemble", {"ref": "0x1e40", "length": 16}, listed),
    Step("history", "history", {"limit": 12}, trail),
    Step("registers", "registers", {}, regs),
    Step("release", "run_for", {"milliseconds": SETTLE_MS, "seconds": RUN_S}, released),
    Step("unwatch", "watch_clear", {"ref": CREDITS}, unwatched),
    Step("credits", "read_memory", {"ref": CREDITS, "length": 1}, credits_are(4)),
    Step("save", "state_save", {"name": "four_credits"}, saved),
    Step("coin 5", "perform", {"steps": [{"op": "input", **COIN},
                                         {"op": "run_for", "milliseconds": SETTLE_MS,
                                          "seconds": RUN_S}],
                               "settle_seconds": RUN_S}, fifth),
    Step("five", "read_memory", {"ref": CREDITS, "length": 1}, credits_are(5)),
    Step("load", "state_load", {"name": "four_credits"}, loaded),
    Step("back to four", "read_memory", {"ref": CREDITS, "length": 1}, credits_are(4)),
    Step("screen", "screen_view", lambda run: {"mode": "render", "dest": run.dir / "screen.png",
                                               "scale": 2}, pictured),
    Step("close", "close", {}, closed),
]

DEMO = Demo(
    name=SYSTEM, root=ROOT, server=[sys.executable, str(ROOT / "server.py")],
    readme=HERE / "README.md", steps=STEPS, capture=lambda run: run.dir / "screen.png",
    offers=frozenset({"rompath", "shared"}), precheck=precheck,
    volatile={"stdout_tail": "the emulator's console as `close` found it, which echoes the "
                             "session's temporary paths",
              "reads": "how often a timed run polled the emulated clock, paced by wall time",
              "flags": "the window's placement, which the host's own helper decides"})

if __name__ == "__main__":
    sys.exit(main(DEMO))
