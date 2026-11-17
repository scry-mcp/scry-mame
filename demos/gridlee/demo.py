"""The gridlee demo: Videa's Gridlee (1983) on a stock MAME, driven by the calls the README's
prompt asks an MCP client to make, each answer checked. `--help` says how to run it.

What it proves, by address: the coin routine's two writes of the credits, the START's two
(each watch stopping the machine at its writer, the START still held), and the instructions the
history shows behind the second. The README tells the story.
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

SYSTEM = "gridlee"
#: The first program ROM's CRC: the cpu sees it at 0xA000, which is what `start` checks against.
REFERENCE_CRC = 0x1C43539E
#: The first 2 KB of the cpu's space (the `:spriteram` share), where the scan finds the credits.
RAM, RAM_BYTES = "0x0", 0x800
#: The credits in binary and in BCD, and the instructions that write them: taken from a run,
#: asserted on every run since.
CREDITS_BIN, CREDITS_BCD = "0x42b", "0x42c"
COIN_BIN_PC, COIN_BCD_PC = "0x0000b583", "0x0000b58c"
START_BIN_PC, START_BCD_PC = "0x0000d676", "0x0000d67f"
#: Where each watch's stop hands the machine back: the instruction after its writer.
COIN_BIN_STOP, COIN_BCD_STOP = "0x0000b586", "0x0000b58f"
START_BIN_STOP, START_BCD_STOP = "0x0000d679", "0x0000d682"
#: The history's window: the START's five-instruction routine, the stop's own instruction last,
#: and the call into the routine before it, with one to spare.
TRAIL = 8
COIN = {"port": ":IN1", "field": "Coin 1", "frames": 4, "seconds": RUN_S}
START = {"port": ":IN1", "field": "1 Player Start", "frames": 4, "seconds": RUN_S}
#: Half a second after an input, long enough for the game to act on it.
SETTLE = {"milliseconds": 500, "seconds": RUN_S}
#: After each coin of the scan: the game had not yet counted the third coin half a second after it
#: dropped, and had two seconds after.
COIN_MS = 2000
#: The frames recorded after the last coin, for the loop to show it counted, and the eight seconds
#: the game plays after START.
COIN_FRAMES, PLAY_FRAMES = 120, 480


def at(addr: str) -> str:
    return f"0x{int(addr, 16):08x}"


def folded(lines: list[str]) -> list[str]:
    return [" ".join(ln.upper().split()) for ln in lines]


def coin_and_run() -> list[dict[str, Any]]:
    return [{"op": "input", **COIN}, {"op": "run_for", "milliseconds": COIN_MS, "seconds": RUN_S}]


def coin_and_filter(coins: int) -> dict[str, Any]:
    return {"steps": [*coin_and_run(),
                      {"op": "scan", "method": "filter", "operator": "=", "value": coins}],
            "settle_seconds": RUN_S}


def filtered(coins: int) -> Any:
    def check(reply: Reply, run: Run) -> str:
        left = reply["ran"][-1]["reply"]["hits_total"]
        expect(left >= 1, f"no byte holds {coins} after coin {coins}")
        return f"{left} bytes still hold {coins}"
    return check


def third(reply: Reply, run: Run) -> str:
    expect(reply["ran"][-1]["reply"]["verdict"] == "ELAPSED", "the run after the coin was cut")
    return "a third coin, and two seconds for the game to count it"


def three_left(reply: Reply, run: Run) -> str:
    addrs = {h["addr"] for h in reply["hits"]}
    expect(reply["hits_total"] == 3 and {at(CREDITS_BIN), at(CREDITS_BCD)} <= addrs,
           f"the scan kept {addrs}")
    return f"three bytes hold 3, among them {CREDITS_BIN} and {CREDITS_BCD}"


def watching(reply: Reply, run: Run) -> str:
    armed = [(r["reply"]["addr"], r["reply"]["mode"]) for r in reply["ran"]]
    want = [(at(CREDITS_BIN), "change"), (at(CREDITS_BCD), "change")]
    expect(armed == want and all(r["reply"].get("armed") for r in reply["ran"]), f"armed {armed}")
    return f"change watches armed on {CREDITS_BIN} and {CREDITS_BCD}"


def dropped(reply: Reply, run: Run) -> str:
    expect(reply["verdict"] == "ELAPSED" and reply["released"] is True,
           f"verdict {reply['verdict']}, released {reply['released']}")
    return "a coin, held four frames and released"


def wrote(addr: str, pc: str, stop: str, value: int, what: str) -> Any:
    def check(reply: Reply, run: Run) -> str:
        expect(reply["verdict"] == "OTHER_STOP", f"verdict {reply['verdict']}")
        hit = reply["watch_hit"]
        expect((hit["addr"], hit["writer_pc"], hit["after"]) == (at(addr), pc, value),
               f"{hit['addr']} written {hit['after']} by {hit['writer_pc']}")
        expect(reply["pc"] == stop, f"the machine was handed back at {reply['pc']}, not {stop}")
        return f"{what}: {hit['lines'][0]}"
    return check


def listed(reply: Reply, run: Run) -> str:
    lines = folded(reply["lines"])
    want = ["B583: 7C 04 2B INC $042B", "B586: 86 01 LDA #$01", "B588: BB 04 2C ADDA $042C",
            "B58B: 19 DAA", "B58C: B7 04 2C STA $042C"]
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


def listing_addr(pc: str) -> str:
    """`pc` as MAME's listings print an address: `0x0000d676` is `D676`."""
    return f"{int(pc, 16):04X}"


def taken(reply: Reply, run: Run) -> str:
    lines = folded(reply["lines"])
    routine = [(START_BIN_PC, "DEC $042B"), (START_BIN_STOP, "LDA #$99"),
               ("0xd67b", "ADDA $042C"), ("0xd67e", "DAA"), (START_BCD_PC, "STA $042C")]
    want = [f"{listing_addr(pc)}: {text}" for pc, text in routine]
    order = [lines.index(w) if w in lines else -1 for w in want]
    expect(-1 not in order and order == sorted(order), f"the trail is not {want}: "
                                                       f"{reply['lines']}")
    expect(bool(lines) and lines[-1].startswith(f"{listing_addr(START_BCD_STOP)}:"),
           f"the trail does not end at the stop, {START_BCD_STOP}: {reply['lines']}")
    return "the trail: DEC $042B, then LDA #$99, ADDA $042C, DAA, STA $042C"


def regs(reply: Reply, run: Run) -> str:
    expect(int(reply["regs"].get("PC") or "-1", 16) == int(START_BCD_STOP, 16),
           f"PC {reply['regs'].get('PC')}, not the stop's {START_BCD_STOP}")
    return f"the stop landed at PC {reply['regs']['PC']}, A {reply['regs']['A']}"


def cleared(reply: Reply, run: Run) -> str:
    expect(reply["declarations_cleared"] == 2
           and sorted(reply["disarmed"]) == ["1 @ 042B-042B write", "2 @ 042C-042C write"],
           f"{reply['declarations_cleared']} cleared, {reply['disarmed']} disarmed")
    return "both watches cleared"


STEPS = [
    Step("start", "start", free_set.boot(SYSTEM, REFERENCE_CRC, "0xa000"), free_set.started,
         options=True, volatile=free_set.START_VOLATILE),
    Step("attract", "run_for", {"milliseconds": 5000, "seconds": RUN_S},
         lambda reply, run: f"attract mode {free_set.ran(reply, run)}"),
    Step("scan", "scan", {"method": "start", "ref": RAM, "length": RAM_BYTES},
         free_set.scanned(RAM, RAM_BYTES)),
    Step("coin 1", "perform", coin_and_filter(1), filtered(1)),
    Step("coin 2", "perform", coin_and_filter(2), filtered(2)),
    Step("coin 3", "perform", {"steps": coin_and_run(), "settle_seconds": RUN_S}, third),
    Step("holds 3", "scan", {"method": "filter", "operator": "=", "value": 3}, three_left,
         title="Narrow a scan with each coin",
         ask="Three coins are in. Keep only the bytes of the scan that hold 3 now.",
         shown=("summary", "hits_total", "hits"),
         reads=("Three bytes hold 3, and a scan cannot say which is the credits. A \"survivor\" "
                "is a byte still in the scan; the watches of the next step tell them apart.")),
    Step("watch", "perform", {"steps": [
        {"op": "watch_add", "ref": CREDITS_BIN, "mode": "change", "fmt": "u8"},
        {"op": "watch_add", "ref": CREDITS_BCD, "mode": "change", "fmt": "u8"}]}, watching),
    Step("coin 4", "input", COIN, dropped),
    Step("binary", "run_for", SETTLE,
         wrote(CREDITS_BIN, COIN_BIN_PC, COIN_BIN_STOP, 4, "the binary credits"),
         title="Let a watch name the writer",
         ask=("Change watches are on `0x42b` and `0x42c` and a fourth coin is in. Run half a "
              "second and tell me what stopped it."),
         shown=("summary", "verdict", "cause"),
         reads=("`OTHER_STOP` means a watch stopped the run before its half second ended. "
                "`cause` names the byte and the instruction that wrote it.")),
    Step("bcd", "run_for", SETTLE,
         wrote(CREDITS_BCD, COIN_BCD_PC, COIN_BCD_STOP, 4, "the BCD credits")),
    Step("writer", "disassemble", {"ref": "0xb583", "length": 12}, listed,
         title="Read the routine it stopped in",
         ask="Disassemble 12 bytes from `0xb583`, where the first watch stopped.",
         shown=("summary", "lines"),
         reads=("The coin routine increments `$042B`, then adds one to `$042C` in BCD (`ADDA`, "
                "`DAA`, `STA`). The game keeps its credits twice, in binary and in BCD.")),
    Step("settle", "run_for", SETTLE, settled),
    Step("both", "read_memory", {"ref": CREDITS_BIN, "length": 2}, credits_are(4, 0x04)),
    Step("save", "state_write", {"method": "save", "name": "four_credits"}, free_set.saved,
         volatile=free_set.SAVE_VOLATILE),
    Step("press start", "input", START,
         wrote(CREDITS_BIN, START_BIN_PC, START_BIN_STOP, 3, "START stopped on the binary")),
    Step("start bcd", "run_for", {"frames": 1, "seconds": RUN_S},
         wrote(CREDITS_BCD, START_BCD_PC, START_BCD_STOP, 3, "then on the BCD credits")),
    Step("trail", "history", {"limit": TRAIL}, taken,
         title="See what ran before a stop",
         ask="START was pressed and a watch stopped it. Show me the last eight instructions.",
         shown=("lines",),
         reads=("`history` lists what the CPU ran up to the stop, oldest first. START takes a "
                "credit from both counters: `DEC $042B`, then the BCD one by adding 99.")),
    Step("registers", "registers", {}, regs),
    Step("unwatch", "declaration_clear", {"kind": "watch", "all": True}, cleared),
    recording("play", PLAY_FRAMES, lambda reply, run: "the game plays on for eight seconds"),
    Step("after start", "read_memory", {"ref": CREDITS_BIN, "length": 2}, credits_are(3, 0x03)),
    Step("screen", "screen_view", lambda run: {"mode": "render", "dest": run.dir / "screen.png",
                                               "scale": 2}, free_set.pictured("the game in play")),
    Step("load", "state_write", {"method": "load", "name": "four_credits"}, free_set.loaded),
    Step("back", "read_memory", {"ref": CREDITS_BIN, "length": 2}, credits_are(4, 0x04)),
    Step("coin 5", "input", COIN, dropped),
    recording("fifth credit", COIN_FRAMES),
    Step("five", "read_memory", {"ref": CREDITS_BIN, "length": 2}, credits_are(5, 0x05)),
    Step("close", "close", {}, free_set.closed),
]

MOMENTS = (
    Moment("unwatch", "play", "`input` pressed START and a credit is spent: the level card, then "
                              "the game.", skip=300, frames=170),
    Moment("coin 5", "fifth credit", "`state_write` loads the saved state and `input` drops a "
                                     "coin: CREDITS goes from 4 to 5.", frames=90),
)

DEMO = free_set.demo(SYSTEM, __file__, STEPS, MOMENTS,
                     "Gridlee starting a game, then counting a coin after a saved state is loaded")


if __name__ == "__main__":
    sys.exit(main(DEMO))
