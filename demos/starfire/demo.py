"""The starfire demo: Exidy's Star Fire (1979) on a stock MAME, driven by the calls the README's
prompt asks an MCP client to make, each answer checked. `--help` says how to run it.

The set is one of the ROMs mamedev.org distributes for free, non-commercial use, from its own
site only, so the demo says where to get it and never carries it. What it walks: the attract
mode running, a coin found in RAM by a value scan, the instruction that writes it caught by a
change watch, and a saved state that puts the credits back where they were.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `demos` imports as it checks
from demos import free_set  # noqa: E402
from demos.free_set import RUN_S, Reply, Run, Step, expect, main  # noqa: E402

SYSTEM = "starfire"
#: The first program ROM's CRC: the cpu sees it at 0x0, which is what `start` checks against.
REFERENCE_CRC = 0x9990AF64
#: The scratch RAM's first kilobyte. The driver mirrors it through its handler across
#: 0x8000-0x9FFF, so a scan over the whole range keeps every variable several times over.
RAM, RAM_BYTES = "0x8000", 0x400
#: The byte the scan converges on and the store that bumps it: taken from a run, asserted on
#: every run since.
CREDITS = "0x8299"
WRITER_PC = "0x00001e48"
COIN = {"port": ":SYSTEM", "field": "Coin 1", "frames": 4, "seconds": RUN_S}
#: Half a second after a coin, which is long enough for the game to count it.
SETTLE_MS = 500


def attract(reply: Reply, run: Run) -> str:
    return f"attract mode {free_set.ran(reply, run)}"


def unwatched(reply: Reply, run: Run) -> str:
    expect(reply["declarations_cleared"] == 1, f"{reply['declarations_cleared']} cleared")
    return "the watch cleared"


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


def fifth(reply: Reply, run: Run) -> str:
    expect(reply["ran"][-1]["reply"]["verdict"] == "ELAPSED", "the run after the coin was cut")
    return f"a fifth coin, run to frame {reply['ran'][-1]['reply']['frame_after']}"


STEPS = [
    Step("start", "start", free_set.boot(SYSTEM, REFERENCE_CRC, "0x0"), free_set.started,
         options=True,
         volatile=free_set.START_VOLATILE,
         shown=("rom_check", "pc")),
    Step("attract", "run_for", {"milliseconds": 3000, "seconds": RUN_S}, attract),
    Step("scan", "scan_start", {"ref": RAM, "length": RAM_BYTES}, free_set.scanned(RAM, RAM_BYTES),
         shown=("summary", "hits_total")),
    Step("coin 1", "perform", {"steps": coin_and_filter(1), "settle_seconds": RUN_S}, filtered(1)),
    Step("coin 2", "perform", {"steps": coin_and_filter(2), "settle_seconds": RUN_S}, filtered(2)),
    Step("coin 3", "perform", {"steps": coin_and_filter(3), "settle_seconds": RUN_S}, filtered(3),
         shown=("summary",)),
    Step("watch", "watch_add", {"ref": CREDITS, "mode": "change", "fmt": "u8"},
         lambda reply, run: f"a change watch armed at {reply['addr']}",
         shown=("summary", "entry", "write_maps_to")),
    Step("coin 4", "input", COIN, caught,
         shown=("summary", "cause", "watch_hit")),
    Step("writer", "disassemble", {"ref": "0x1e40", "length": 16}, listed,
         shown=("summary", "lines")),
    Step("history", "history", {"limit": 12}, trail),
    Step("registers", "registers", {}, regs),
    Step("release", "run_for", {"milliseconds": SETTLE_MS, "seconds": RUN_S}, released),
    Step("unwatch", "watch_clear", {"ref": CREDITS}, unwatched),
    Step("credits", "read_memory", {"ref": CREDITS, "length": 1}, credits_are(4)),
    Step("save", "state_save", {"name": "four_credits"}, free_set.saved,
         shown=("summary", "frame")),
    Step("coin 5", "perform", {"steps": [{"op": "input", **COIN},
                                         {"op": "run_for", "milliseconds": SETTLE_MS,
                                          "seconds": RUN_S}],
                               "settle_seconds": RUN_S}, fifth),
    Step("five", "read_memory", {"ref": CREDITS, "length": 1}, credits_are(5)),
    Step("load", "state_load", {"name": "four_credits"}, free_set.loaded,
         shown=("summary", "verified")),
    Step("back to four", "read_memory", {"ref": CREDITS, "length": 1}, credits_are(4),
         shown=("summary", "hex")),
    Step("screen", "screen_view", lambda run: {"mode": "render", "dest": run.dir / "screen.png",
                                               "scale": 2}, free_set.pictured("the screen")),
    Step("close", "close", {}, free_set.closed),
]

DEMO = free_set.demo(SYSTEM, __file__, STEPS)

if __name__ == "__main__":
    sys.exit(main(DEMO))
