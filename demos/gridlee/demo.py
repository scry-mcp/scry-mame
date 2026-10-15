"""The gridlee demo: Videa's Gridlee (1983) on a stock MAME, driven by the calls the README's
prompt asks an MCP client to make, each answer checked. `--help` says how to run it.

What it walks: three coins leave a value scan with three bytes holding 3, and change watches on
two of them tell them apart: the coin routine increments one (`INC $042B`) and then adds one in
BCD to the other (`ADDA $042C`, `DAA`, `STA $042C`). A START is stopped by the watch on the BCD
byte, and the routine that wrote it decrements the binary byte just before. A saved state takes
the START back, and the picture is the game in play.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `demos` imports as it checks
from demos import free_set  # noqa: E402
from demos.free_set import RUN_S, Reply, Run, Step, expect, main  # noqa: E402

SYSTEM = "gridlee"
#: The first program ROM's CRC: the cpu sees it at 0xA000, which is what `start` checks against.
REFERENCE_CRC = 0x1C43539E
#: The first 2 KB of the cpu's space (the `:spriteram` share), where the scan finds the credits.
RAM, RAM_BYTES = "0x0", 0x800
#: The credits in binary and in BCD, and the instructions that write them: taken from a run,
#: asserted on every run since.
CREDITS_BIN, CREDITS_BCD = "0x42b", "0x42c"
COIN_BIN_PC, COIN_BCD_PC, START_BCD_PC = "0x0000b583", "0x0000b58c", "0x0000d67f"
#: Where the START's routine takes a credit: the binary decrement, then one taken in BCD.
START_ROUTINE = "0xd676"
COIN = {"port": ":IN1", "field": "Coin 1", "frames": 4, "seconds": RUN_S}
START = {"port": ":IN1", "field": "1 Player Start", "frames": 4, "seconds": RUN_S}
#: Half a second after an input, long enough for the game to act on it.
SETTLE = {"milliseconds": 500, "seconds": RUN_S}
#: After each coin of the scan: the game had not yet counted the third coin half a second after it
#: dropped, and had two seconds after.
COIN_MS = 2000


def at(addr: str) -> str:
    return f"0x{int(addr, 16):08x}"


def folded(lines: list[str]) -> list[str]:
    return [" ".join(ln.upper().split()) for ln in lines]


def coin_and_filter(coins: int) -> dict[str, Any]:
    return {"steps": [{"op": "input", **COIN},
                      {"op": "run_for", "milliseconds": COIN_MS, "seconds": RUN_S},
                      {"op": "scan_filter", "operator": "=", "value": coins}],
            "settle_seconds": RUN_S}


def filtered(coins: int) -> Any:
    def check(reply: Reply, run: Run) -> str:
        scan = reply["ran"][-1]["reply"]
        left = scan["hits_total"]
        expect(left >= 1, f"no byte holds {coins} after coin {coins}")
        if coins < 3:
            return f"coin {coins}: {left} bytes still hold {coins}"
        addrs = {h["addr"] for h in scan["hits"]}
        expect(left == 3 and {at(CREDITS_BIN), at(CREDITS_BCD)} <= addrs, f"the scan kept {addrs}")
        return f"coin 3: three bytes hold 3, among them {CREDITS_BIN} and {CREDITS_BCD}"
    return check


def watching(reply: Reply, run: Run) -> str:
    armed = [(r["reply"]["addr"], r["reply"]["mode"]) for r in reply["ran"]]
    want = [(at(CREDITS_BIN), "change"), (at(CREDITS_BCD), "change")]
    expect(armed == want and all(r["reply"].get("armed") for r in reply["ran"]), f"armed {armed}")
    return f"change watches armed on {CREDITS_BIN} and {CREDITS_BCD}"


def dropped(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED" and reply["released"] is True,
           f"verdict {reply['verdict']}, released {reply['released']}")
    return "the fourth coin, held four frames and released"


def wrote(addr: str, pc: str, value: int, what: str) -> Any:
    def check(reply: Reply, run: Run) -> str:
        expect(reply["verdict"] == "OTHER_STOP", f"verdict {reply['verdict']}")
        hit = reply["watch_hit"]
        expect((hit["addr"], hit["writer_pc"], hit["after"]) == (at(addr), pc, value),
               f"{hit['addr']} written {hit['after']} by {hit['writer_pc']}")
        return f"{what}: {hit['lines'][0]}"
    return check


def listed(reply: Reply, run: Run) -> str:
    lines = folded(reply["lines"])
    want = ["B583: 7C 04 2B INC $042B", "B58B: 19 DAA", "B58C: B7 04 2C STA $042C"]
    expect(all(w in lines for w in want), f"the coin routine is not {want}: {reply['lines']}")
    return "the coin routine: INC $042B, then ADDA $042C, DAA, STA $042C"


def settled(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED", f"verdict {reply['verdict']}: another write stopped it")
    return f"ran on to frame {reply['frame_after']} with no other write"


def credits_are(binary: int, bcd: int) -> Any:
    def check(reply: Reply, run: Run) -> str:
        raw = bytes.fromhex(reply["hex"])
        expect((raw[0], raw[1]) == (binary, bcd), f"binary {raw[0]}, BCD {raw[1]:02x}")
        return f"credits {binary} in binary, {bcd:02x} in BCD"
    return check


def unwatched(reply: Reply, run: Run) -> str:
    expect(reply["declarations_cleared"] == 1, f"{reply['declarations_cleared']} cleared")
    return f"the watch on {CREDITS_BIN} cleared; the one on {CREDITS_BCD} stays"


def taken(reply: Reply, run: Run) -> str:
    lines = folded(reply["lines"])
    want = ["DEC $042B", "LDA #$99", "ADDA $042C", "DAA", "STA $042C"]
    got = [ln.split(" ", 1)[-1] for ln in lines]
    order = [next((i for i, g in enumerate(got) if g.endswith(w)), -1) for w in want]
    expect(-1 not in order and order == sorted(order), f"the START's routine is not {want}: "
                                                       f"{reply['lines']}")
    return "the START's routine: DEC $042B, then LDA #$99, ADDA $042C, DAA, STA $042C"


def regs(reply: Reply, run: Run) -> str:
    expect(bool(reply["regs"].get("PC")), f"no PC in {reply['regs']}")
    return f"the stop landed at PC {reply['regs']['PC']}, A {reply['regs']['A']}"


def cleared(reply: Reply, run: Run) -> str:
    expect(reply["declarations_cleared"] == 1, f"{reply['declarations_cleared']} cleared")
    return "the last watch cleared"


STEPS = [
    Step("start", "start", free_set.boot(SYSTEM, REFERENCE_CRC, "0xa000"), free_set.started,
         options=True),
    Step("attract", "run_for", {"milliseconds": 5000, "seconds": RUN_S},
         lambda reply, run: f"attract mode {free_set.ran(reply, run)}"),
    Step("scan", "scan_start", {"ref": RAM, "length": RAM_BYTES},
         free_set.scanned(RAM, RAM_BYTES)),
    Step("coin 1", "perform", coin_and_filter(1), filtered(1)),
    Step("coin 2", "perform", coin_and_filter(2), filtered(2)),
    Step("coin 3", "perform", coin_and_filter(3), filtered(3)),
    Step("watch", "perform", {"steps": [
        {"op": "watch_add", "ref": CREDITS_BIN, "mode": "change", "fmt": "u8"},
        {"op": "watch_add", "ref": CREDITS_BCD, "mode": "change", "fmt": "u8"}]}, watching),
    Step("coin 4", "input", COIN, dropped),
    Step("binary", "run_for", SETTLE, wrote(CREDITS_BIN, COIN_BIN_PC, 4, "the binary credits")),
    Step("bcd", "run_for", SETTLE, wrote(CREDITS_BCD, COIN_BCD_PC, 4, "the BCD credits")),
    Step("writer", "disassemble", {"ref": "0xb583", "length": 12}, listed),
    Step("settle", "run_for", SETTLE, settled),
    Step("both", "read_memory", {"ref": CREDITS_BIN, "length": 2}, credits_are(4, 0x04)),
    Step("save", "state_save", {"name": "four_credits"}, free_set.saved),
    Step("one watch", "watch_clear", {"ref": CREDITS_BIN}, unwatched),
    Step("press start", "input", START,
         wrote(CREDITS_BCD, START_BCD_PC, 3, "START stopped on the BCD credits")),
    Step("start code", "disassemble", {"ref": START_ROUTINE, "length": 12}, taken),
    Step("registers", "registers", {}, regs),
    Step("unwatch", "watch_clear", {"ref": CREDITS_BCD}, cleared),
    Step("play", "run_for", {"milliseconds": 8000, "seconds": RUN_S},
         lambda reply, run: f"the game plays on: {free_set.ran(reply, run)}"),
    Step("after start", "read_memory", {"ref": CREDITS_BIN, "length": 2}, credits_are(3, 0x03)),
    Step("screen", "screen_view", lambda run: {"mode": "render", "dest": run.dir / "screen.png",
                                               "scale": 2}, free_set.pictured("the game in play")),
    Step("load", "state_load", {"name": "four_credits"}, free_set.loaded),
    Step("back", "read_memory", {"ref": CREDITS_BIN, "length": 2}, credits_are(4, 0x04)),
    Step("close", "close", {}, free_set.closed),
]

DEMO = free_set.demo(SYSTEM, __file__, STEPS)

if __name__ == "__main__":
    sys.exit(main(DEMO))
