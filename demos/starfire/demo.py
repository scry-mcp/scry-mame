"""The starfire demo: Exidy's Star Fire (1979) on a stock MAME, driven by the calls the README's
prompt asks an MCP client to make, each answer checked. `--help` says how to run it.

The set is one of the ROMs mamedev.org distributes for free, non-commercial use, from its own
site only, so the demo says where to get it and never carries it. What it does: the attract
mode running, a coin found in RAM by a value scan, the instruction that writes it caught by a
change watch, a saved state that puts the credits back where they were, and START pressed: a
mission, which the fuel gauge it burns confirms.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `demos` imports as it checks
from demos import free_set  # noqa: E402
from demos.free_set import (  # noqa: E402
    RUN_S,
    Moment,
    Reply,
    Run,
    Step,
    expect,
    main,
    recording,
)

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
#: The instructions `history` is asked for: the routine that counts the coin, and the stop.
TRAIL = 8
START = {"port": ":SYSTEM", "field": "1 Player Start", "frames": 4, "seconds": RUN_S}
#: The fuel gauge, four decimal digits a byte each, lowest first, and what it reads while the
#: game waits with four coins in: taken from a run, asserted on every run since. Only a mission
#: burns it, so it is what says START was taken.
FUEL, FUEL_WAITING = "0x82ab", 1500
#: The frames each moment of the loop records: a second and a half, and a second.
COUNTED_FRAMES, BACK_FRAMES = 90, 60
#: The frames recorded once START is pressed, and the three seconds of them the loop shows (179
#: frames: 180 at the board's rate run past three): the mission as its first enemy closes in.
MISSION_FRAMES, MISSION_SKIP, MISSION_SHOWN = 420, 228, 179


def attract(reply: Reply, run: Run) -> str:
    return f"attract mode {free_set.ran(reply, run)}"


def unwatched(reply: Reply, run: Run) -> str:
    expect(reply["declarations_cleared"] == 1, f"{reply['declarations_cleared']} cleared")
    return "the watch cleared"


def coin_and_run() -> list[dict[str, Any]]:
    return [{"op": "input", **COIN}, {"op": "run_for", "milliseconds": SETTLE_MS, "seconds": RUN_S}]


def coin_and_filter(credits: int) -> list[dict[str, Any]]:
    return [*coin_and_run(), {"op": "scan", "method": "filter", "operator": "=", "value": credits}]


def filtered(credits: int) -> Any:
    def check(reply: Reply, run: Run) -> str:
        left = reply["ran"][-1]["reply"]["hits_total"]
        expect(left >= 1, f"no cell holds {credits} after coin {credits}")
        return f"{left} cells still hold {credits}"
    return check


def third(reply: Reply, run: Run) -> str:
    expect(reply["ran"][-1]["reply"]["verdict"] == "ELAPSED", "the run after the coin was cut")
    return "a third coin, and half a second for the game to count it"


def one_left(reply: Reply, run: Run) -> str:
    addrs = [h["addr"] for h in reply["hits"]]
    expect(addrs == ["0x00008299"], f"after three coins the scan holds {addrs}")
    return f"one cell left, {addrs[0]}, holding 3"


def dropped(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED" and reply["released"] is True,
           f"verdict {reply['verdict']}, released {reply['released']}")
    return "a fifth coin, held four frames and released"


def fuel(reply: Reply) -> int:
    return sum(digit * 10 ** place for place, digit in enumerate(bytes.fromhex(reply["hex"])))


def fuel_waits(reply: Reply, run: Run) -> str:
    expect(fuel(reply) == FUEL_WAITING, f"FUEL {fuel(reply)} before START, not {FUEL_WAITING}")
    return f"FUEL {FUEL_WAITING}, and the game waiting"


def fuel_burns(reply: Reply, run: Run) -> str:
    expect(fuel(reply) < FUEL_WAITING, f"FUEL still {fuel(reply)}: START began no mission")
    return f"FUEL {fuel(reply)}: the mission is burning it"


def pressed(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED" and reply["released"] is True,
           f"verdict {reply['verdict']}, released {reply['released']}")
    return "START, held four frames and released"


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


STEPS = [
    Step("start", "start", free_set.boot(SYSTEM, REFERENCE_CRC, "0x0"), free_set.started,
         options=True, volatile=free_set.START_VOLATILE),
    Step("attract", "run_for", {"milliseconds": 3000, "seconds": RUN_S}, attract),
    Step("scan", "scan", {"method": "start", "ref": RAM, "length": RAM_BYTES},
         free_set.scanned(RAM, RAM_BYTES)),
    Step("coin 1", "perform", {"steps": coin_and_filter(1), "settle_seconds": RUN_S}, filtered(1)),
    Step("coin 2", "perform", {"steps": coin_and_filter(2), "settle_seconds": RUN_S}, filtered(2)),
    Step("coin 3", "perform", {"steps": coin_and_run(), "settle_seconds": RUN_S}, third),
    Step("three", "scan", {"method": "filter", "operator": "=", "value": 3}, one_left,
         title="Find a variable nobody named",
         ask="Three coins are in. Keep only the bytes of the scan that hold 3 now.",
         shown=("summary", "hits_total", "hits"),
         reads=("One byte followed the coins from 1 to 3, so `0x8299` is the credits. "
                "\"1 left\" counts the bytes still in the scan.")),
    Step("watch", "watch_add", {"ref": CREDITS, "mode": "change", "fmt": "u8"},
         lambda reply, run: f"a change watch armed at {reply['addr']}"),
    Step("coin 4", "input", COIN, caught,
         title="Catch the instruction that writes it",
         ask="With a change watch on `0x8299`, drop a fourth coin and tell me what wrote it.",
         shown=("summary", "verdict", "cause"),
         reads=("`OTHER_STOP` means the watch stopped the machine while the coin was still "
                "held. `cause` names the byte and the instruction that wrote it, at `0x1e48`.")),
    Step("writer", "disassemble", {"ref": "0x1e40", "length": 16}, listed),
    Step("history", "history", {"limit": TRAIL}, trail,
         title="Read how the program got there",
         ask="Show me the last eight instructions the CPU ran before that stop.",
         shown=("lines",),
         reads=("`history` lists what the CPU ran up to the stop, oldest first. `inc (hl)` at "
                "`1E48` is the write the watch caught, and the line after it is where the game "
                "stopped.")),
    Step("registers", "registers", {}, regs),
    Step("release", "run_for", {"milliseconds": SETTLE_MS, "seconds": RUN_S}, released),
    Step("unwatch", "declaration_clear", {"kind": "watch", "ref": CREDITS}, unwatched),
    Step("credits", "read_memory", {"ref": CREDITS, "length": 1}, credits_are(4)),
    Step("save", "state_write", {"method": "save", "name": "four_credits"}, free_set.saved,
         volatile=free_set.SAVE_VOLATILE),
    Step("coin 5", "input", COIN, dropped),
    recording("fifth counted", COUNTED_FRAMES),
    Step("five", "read_memory", {"ref": CREDITS, "length": 1}, credits_are(5)),
    Step("load", "state_write", {"method": "load", "name": "four_credits"}, free_set.loaded,
         title="Go back to before the coin",
         ask="Load the state you saved at four credits.",
         shown=("summary", "verified"),
         reads=("`verified` is true: the server read the machine back after the load, and it is "
                "the saved one. The fifth coin is undone.")),
    recording("four again", BACK_FRAMES),
    Step("back to four", "read_memory", {"ref": CREDITS, "length": 1}, credits_are(4)),
    Step("fuel waiting", "read_memory", {"ref": FUEL, "length": 4}, fuel_waits),
    Step("press start", "input", START, pressed),
    recording("mission", MISSION_FRAMES),
    Step("fuel burning", "read_memory", {"ref": FUEL, "length": 4}, fuel_burns),
    Step("screen", "screen_view", lambda run: {"mode": "render", "dest": run.dir / "screen.png",
                                               "scale": 2}, free_set.pictured("the screen")),
    Step("close", "close", {}, free_set.closed),
]

MOMENTS = (
    Moment("coin 5", "fifth counted",
           "`input` drops a fifth coin: the screen redraws and FUEL reads 1800."),
    Moment("load", "four again",
           "`state_write` loads the state saved at four coins, and FUEL is back at 1500."),
    Moment("press start", "mission",
           "`input` presses START: the mission begins and its first enemy closes in.",
           skip=MISSION_SKIP, frames=MISSION_SHOWN),
)

DEMO = free_set.demo(SYSTEM, __file__, STEPS, MOMENTS,
                     "Star Fire counting a coin, going back to a saved state, then flying a "
                     "mission")

if __name__ == "__main__":
    sys.exit(main(DEMO))
