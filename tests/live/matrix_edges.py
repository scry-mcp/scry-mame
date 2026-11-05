"""Section B of the live matrix: every argument at its edge."""


import sys
from dataclasses import dataclass
from typing import Any

from bench_boards import (
    REFERENCE_ROM,
)
from live_harness import (
    BOOT,
    SCRATCH,
    TRANSCRIPT,
    WAIT_CEILING_S,
    Blocked,
    blocked,
    boot,
    call,
    cell,
    ensure_closed,
    fresh,
    last_wall,
    ok,
    refused,
    said,
    section,
    whole,
)
from map_edges import program_edges

from scry_mame import breakpoints, conditions

from scry_mame import cpus  # isort: skip
from scry_mame import declarations as dec  # isort: skip
from scry_mame import read  # isort: skip
from scry_mame.state import STATE  # isort: skip
from matrix_tools_by_state import (  # noqa: E402
    STOPPED_SAYS,
    Judge,
    load_judged,
    restore,
)

#
# (S1 b, and interaction section 13.) Each argument at its documented MAXIMUM, one past it, far
# past it, at its minimum where one is documented, and absent where it is optional. The limits
# are each tool's own docstring's (`1..1024`, `outside (0, 600]`, "at most 128 bytes").

FAR = 10**9
WAIT_MAX = 600.0  # the documented ceiling of every wait (`vocab.WAIT_MAX_S`)
ONE_PAST_WAIT = WAIT_MAX + 0.001
PRE_GATE = "refused by the argument check, before any wait"


def is_ok(pred: Judge = lambda r: True) -> Judge:
    return lambda r: ok(r) and pred(r)


def is_refused(*codes: str) -> Judge:
    return lambda r: refused(r, *codes)


def refused_saying(words: str) -> Judge:
    """A `bad_argument` whose message holds `words`: the refusal of one judge, told from another
    layer's refusal of the same call."""
    return lambda r: refused(r, "bad_argument") and words in str(r.get("message"))


def prints(value: str) -> Judge:
    """A `debug` reply whose output is `value`, the console's hex with no leading zeros."""
    return lambda r: str(r.get("output", "")).strip().upper().lstrip("0") == value


def silent(r: dict[str, Any]) -> bool:
    """A cell whose contract does not settle the answer: whatever it is, it arrives in the
    envelope and not as an exception. The reply is in the transcript for the auditors."""
    return whole(r)


@dataclass
class Case:
    label: str
    tool: str
    kw: dict[str, Any]
    judge: Judge
    exempt: str = ""       # why this call cannot wait, when its own wait is above the ceiling
    then: str = ""         # the call that restores the machine after it
    before: tuple[str, dict[str, Any]] | None = None   # the call that sets up its state


def waits(tool: str, arg: str, base: dict[str, Any], *, at_max: str = "",
          absent: str | None = None, zero_ok: bool = False, then: str = "") -> list[Case]:
    """The five edges of one WAIT argument. `at_max` and `absent` say why the call returns at
    once in this state; with none, the cell is BLOCKED by B1. `absent` is None for a default
    already inside the ceiling. `then` is the restoring call run after those two cells."""
    zero = is_ok() if zero_ok else is_refused("bad_argument")
    cases = [
        Case(f"{tool}.{arg} at max {WAIT_MAX:g}", tool, {**base, arg: WAIT_MAX}, is_ok(),
             exempt=at_max, then=then),
        Case(f"{tool}.{arg} one past max", tool, {**base, arg: ONE_PAST_WAIT},
             is_refused("bad_argument"), exempt=PRE_GATE),
        Case(f"{tool}.{arg} far past max", tool, {**base, arg: float(FAR)},
             is_refused("bad_argument"), exempt=PRE_GATE),
        Case(f"{tool}.{arg} at zero", tool, {**base, arg: 0.0}, zero),
    ]
    if absent is not None:
        cases.append(Case(f"{tool}.{arg} absent", tool, dict(base), is_ok(), exempt=absent,
                          then=then))
    return cases


def counts(tool: str, arg: str, base: dict[str, Any], ceiling: int, reply_has: Judge,
           floor: int = 1) -> list[Case]:
    """The edges of one COUNT argument documented as `floor..ceiling`."""
    return [
        Case(f"{tool}.{arg} at max {ceiling}", tool, {**base, arg: ceiling}, is_ok(reply_has)),
        Case(f"{tool}.{arg} one past max", tool, {**base, arg: ceiling + 1},
             is_refused("bad_argument")),
        Case(f"{tool}.{arg} far past max", tool, {**base, arg: FAR}, is_refused("bad_argument")),
        Case(f"{tool}.{arg} at min {floor}", tool, {**base, arg: floor}, is_ok()),
        Case(f"{tool}.{arg} below min", tool, {**base, arg: floor - 1},
             is_refused("bad_argument")),
    ]


def hex_len(n: int) -> Judge:
    return lambda r: len(str(r.get("hex", ""))) == 2 * n


def _lua_of(n: int) -> str:
    """A script of exactly `n` characters that prints `1`: the rest is one comment line."""
    head = "print(1)\n--"
    return head + "x" * (n - len(head))


NAME_MAX = 64  # a state name: letters, digits, `_` and `-`, never `-` first, up to 64
MAX_NAME = "s" * NAME_MAX
# A WAIT IS EXEMPT FROM B1 ONLY WHERE THE CALL RETURNS AT ONCE, so a published maximum is proved
# without being waited out; `run_case` FAILS the cell if it took longer than the ceiling, so each
# reason below is checked, never trusted.
RUNS_EVERY_FRAME = "the run is asked of a target that runs every frame"
STOPPED_ANSWERS_AT_ONCE = "a stopped machine answers in one step"
ENDS_IN_FRAMES = "the call asks for one or two frames"
STOP_AT_ONCE = "a breakpoint on a routine that runs every frame stops the release within a frame"
AT_A_STOP = "at a stop the log is read once, never waited on (drive's docstring)"
NO_RUN_STEP = "no step of the list lets the machine run, so nothing waits for a stop"
STOPPED_THROTTLE = "a stopped machine's throttle is pending and never waits (its docstring)"
# A line the act makes the EMULATOR log, so an `expect` has something to see: the throttle's own
# mark, which it writes there on the first frame run after it (its docstring).
SEEN_ACT: dict[str, Any] = {
    "act": [{"op": "throttle", "on": False}, {"op": "run_for", "frames": 1, "seconds": 10.0}],
    "expect": "MAME_MCP_THROTTLE#", "settle_seconds": 2.0}

STOPPED_CASES: list[Case] = [
    *counts("read_memory", "length", {"ref": "0x400"}, 1024, hex_len(1024)),
    Case("read_memory.length absent", "read_memory", {"ref": "0x400"}, is_ok(hex_len(16))),
    Case("read_memory.ref empty (contract silent)", "read_memory", {"ref": ""}, silent),
    *counts("disassemble", "length", {"ref": "0x400"}, 1024, lambda r: bool(r.get("lines"))),
    Case("disassemble.length absent", "disassemble", {"ref": "0x400"}, is_ok()),
    *counts("read_block", "length", {"tag": "maincpu"}, 1024, hex_len(1024)),
    Case("read_block.length absent", "read_block", {"tag": "maincpu"}, is_ok(hex_len(16))),
    *waits("read_block", "seconds", {"tag": "maincpu", "length": 8}, at_max=STOPPED_ANSWERS_AT_ONCE,
           absent=None),
    Case("read_block.seconds absent", "read_block", {"tag": "maincpu", "length": 8}, is_ok()),
    Case("read_block.offset negative", "read_block", {"tag": "maincpu", "offset": -1},
         is_refused("bad_argument")),
    Case("read_block.tag and ref both empty", "read_block", {}, is_refused("bad_argument")),
    Case("read_block.tag and ref both given", "read_block", {"tag": "maincpu", "ref": "0x400"},
         is_refused("bad_argument")),
    Case("read_block.tag with whitespace", "read_block", {"tag": "main cpu"},
         is_refused("bad_argument")),
    Case("read_block.offset beside ref", "read_block", {"ref": "0x400", "offset": 4},
         is_refused("bad_argument")),
    Case("read_block.offset written 0x", "read_block", {"tag": "maincpu", "offset": "0x10",
         "length": 8}, is_ok(lambda r: r.get("offset") == 0x10)),
    Case("read_block.offset as decimal text", "read_block", {"tag": "maincpu", "offset": "16"},
         refused_saying("decimal text is refused")),
    *counts("history", "limit", {}, read.HISTORY_MAX,
            lambda r: 1 <= len(r.get("lines", [])) <= read.HISTORY_MAX),
    Case("history.limit absent", "history", {}, is_ok()),
    *counts("symbols_find", "limit", {"name": "vec"}, 50,
            lambda r: 1 <= len(r.get("symbols", [])) <= 50),
    Case("symbols_find.limit absent", "symbols_find", {"name": "vec"},
         is_ok(lambda r: len(r.get("symbols", [])) <= 10)),
    Case("symbols_find.name and linear both empty", "symbols_find", {},
         is_refused("bad_argument")),
    Case("symbols_find.name and linear both given", "symbols_find",
         {"name": "vec", "linear": "0x400"}, is_refused("bad_argument")),
    Case("symbols_find.linear not hex", "symbols_find", {"linear": "zz"},
         is_refused("bad_argument")),
    Case("symbols_find.linear bare hex", "symbols_find", {"linear": "400"},
         is_refused("bad_argument")),
    *counts("log", "limit", {"pattern": ".", "channel": "emulator"}, 400,
            lambda r: len(r.get("lines", [])) <= 400),
    Case("log.limit absent", "log", {"pattern": ".", "channel": "emulator"}, is_ok()),
    Case("log.channel guest is refused by name", "log", {"pattern": ".", "channel": "guest"},
         is_refused("bad_argument", "no_channel")),
    Case("log.channel empty", "log", {"pattern": ".", "channel": ""},
         is_refused("bad_argument", "no_channel")),
    Case("log.pattern unusable regex", "log", {"pattern": "(", "channel": "emulator"},
         is_refused("bad_argument")),
    Case("log.labels true adds labels", "log",
         {"pattern": ".", "channel": "emulator", "labels": True},
         is_ok(lambda r: isinstance(r.get("labels"), dict))),
    # The emulator log already holds a line at every stop after the boot, so these answer at
    # once: `log_wait`'s docstring promises it for a line the log already holds.
    *waits("log_wait", "seconds", {"pattern": ".", "channel": "emulator"},
           at_max="the log already holds the line: answered at once",
           absent="the log already holds the line: answered at once"),
    # A stopped machine logs nothing, so a line the log does not hold could never arrive:
    # INVALID at once, never an empty answer.
    Case("log_wait on a stopped machine, a line the log does not hold", "log_wait",
         {"pattern": "MAME_MCP never logged this", "channel": "emulator", "seconds": 5.0},
         is_refused("wait_stopped")),
    *counts("drive", "limit", {"act": [{"op": "run_for", "frames": 1, "seconds": 10.0}],
                               "settle_seconds": 2.0}, read.LOG_LIMIT_MAX,
            lambda r: len(r.get("looked", {}).get("emulator", {}).get("lines", []))
            <= read.LOG_LIMIT_MAX),
    Case("drive.limit absent", "drive", {"act": [{"op": "run_for", "frames": 1,
                                                  "seconds": 10.0}], "settle_seconds": 2.0},
         is_ok()),
    *waits("drive", "seconds", SEEN_ACT, at_max=AT_A_STOP, absent=None),
    Case("drive.seconds absent", "drive", SEEN_ACT, is_ok()),
    *waits("drive", "settle_seconds", {"act": [{"op": "registers"}]}, at_max=NO_RUN_STEP,
           absent=NO_RUN_STEP, zero_ok=True),
    *waits("perform", "settle_seconds", {"steps": [{"op": "registers"}]}, at_max=NO_RUN_STEP,
           absent=NO_RUN_STEP, zero_ok=True),
    Case("perform.steps empty (contract silent)", "perform", {"steps": [], "settle_seconds": 2.0},
         silent),
    Case("drive.act empty (contract silent)", "drive", {"act": [], "settle_seconds": 2.0}, silent),
    Case("watch_add.length show at max 128", "watch_add",
         {"ref": "0x200000", "mode": "show", "length": 128},
         is_ok(lambda r: r.get("length") == 128), then="declaration_clear watch"),
    Case("watch_add.length show one past max", "watch_add",
         {"ref": "0x200000", "mode": "show", "length": 129}, is_refused("bad_argument")),
    Case("watch_add.length show far past max", "watch_add",
         {"ref": "0x200000", "mode": "show", "length": FAR}, is_refused("bad_argument")),
    Case("watch_add.length change at max 1024", "watch_add",
         {"ref": "0x200000", "mode": "change", "length": 1024},
         is_ok(lambda r: r.get("armed") is True and r.get("length") == 1024),
         then="declaration_clear watch"),
    Case("watch_add.length change one past max", "watch_add",
         {"ref": "0x200000", "mode": "change", "length": 1025}, is_refused("bad_argument")),
    Case("watch_add.length change far past max", "watch_add",
         {"ref": "0x200000", "mode": "change", "length": FAR}, is_refused("bad_argument")),
    Case("watch_add.length negative", "watch_add", {"ref": "0x200000", "mode": "show",
                                                    "length": -1},
         is_refused("bad_argument")),
    Case("watch_add.length absent on an untyped address (contract silent)", "watch_add",
         {"ref": "0x200000", "mode": "show"}, silent, then="declaration_clear watch"),
    Case("watch_add.fmt names a pointer class", "watch_add",
         {"ref": "0x200000", "mode": "show", "fmt": "ptr16@CODE"}, is_refused("bad_argument")),
    Case("watch_add.fmt a sized array needs no length", "watch_add",
         {"ref": "0x200000", "mode": "show", "fmt": "u16[4]"},
         is_ok(lambda r: r.get("length") == 8), then="declaration_clear watch"),
    Case("watch_add.mode outside the vocabulary", "watch_add", {"ref": "0x200000", "mode": "poke"},
         is_refused("bad_argument")),
    Case("watch_add.by outside the vocabulary", "watch_add",
         {"ref": "200000", "mode": "show", "length": 2, "by": "guess"}, is_refused("bad_argument")),
    Case("watch_add.expr with a length", "watch_add", {"ref": "beamy", "mode": "expr", "length": 2},
         is_refused("bad_argument")),
    Case("watch_add.length capture at max 128", "watch_add",
         {"ref": "0x200000", "mode": "capture", "length": 128, "trigger": "0x200000"},
         is_ok(lambda r: r.get("length") == 128 and r.get("state") == "pending"),
         then="declaration_clear watch"),
    Case("watch_add.length capture one past max", "watch_add",
         {"ref": "0x200000", "mode": "capture", "length": 129, "trigger": "0x200000"},
         is_refused("bad_argument")),
    Case("watch_add.trigger absent on a capture", "watch_add",
         {"ref": "0x200000", "mode": "capture", "length": 2}, is_refused("bad_argument")),
    Case("watch_add.trigger on a count watch", "watch_add",
         {"ref": "0x200000", "mode": "count", "length": 2, "trigger": "0x200000"},
         is_refused("bad_argument")),
    Case("watch_add.condition on a show watch", "watch_add",
         {"ref": "0x200000", "mode": "show", "length": 2, "condition": "wpdata==1"},
         is_refused("bad_argument")),
    Case("watch_add.condition the console cannot evaluate", "watch_add",
         {"ref": "0x200000", "mode": "change", "length": 2, "condition": "wpdata=="},
         is_refused("bad_argument")),
    Case("screen_signature.crop absent", "screen_signature", {},
         is_ok(lambda r: r.get("crop") == [0, 0, r.get("width"), r.get("height")])),
    *waits("screen_signature", "seconds", {}, at_max=STOPPED_ANSWERS_AT_ONCE, absent=None),
    Case("screen_signature.seconds absent", "screen_signature", {"crop": [0, 0, 8, 8]},
         is_ok(lambda r: r.get("crop") == [0, 0, 8, 8])),
    Case("screen_signature.crop off the screen", "screen_signature",
         {"crop": [0, 0, 1, 100000]}, is_refused("bad_argument")),
    Case("screen_signature.crop of no width", "screen_signature", {"crop": [0, 0, 0, 8]},
         is_refused("bad_argument")),
    Case("lua.script at max 16000 chars", "lua", {"script": _lua_of(16000), "read_only": True},
         is_ok(lambda r: r.get("output") == "1\n")),
    Case("lua.script one past max", "lua", {"script": _lua_of(16001)},
         is_refused("bad_argument")),
    Case("lua.script far past max", "lua", {"script": _lua_of(10**6)},
         is_refused("bad_argument")),
    Case("lua.script empty", "lua", {"script": ""}, is_refused("bad_argument")),
    Case("lua.script whitespace only", "lua", {"script": "  \n "}, is_refused("bad_argument")),
    *waits("lua", "seconds", {"script": "print(1)", "read_only": True},
           at_max=STOPPED_ANSWERS_AT_ONCE, absent=None),
    Case("lua.seconds absent", "lua", {"script": "print(1)", "read_only": True}, is_ok()),
    Case("input.frames absent", "input", {"port": ":P1", "field": "Coin 1", "seconds": 10.0},
         is_ok(lambda r: r.get("frames") == 4 and r.get("released") is True)),
    Case("input.frames zero", "input",
         {"port": ":P1", "field": "Coin 1", "frames": 0, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("input.port empty", "input", {"port": "", "field": "Coin 1", "seconds": 10.0},
         is_refused("bad_argument")),
    Case("input.field empty", "input", {"port": ":P1", "field": "", "seconds": 10.0},
         is_refused("bad_argument")),
    Case("input.value written 0x", "input",
         {"port": ":P1", "field": "Coin 1", "value": "0x1", "frames": 1, "seconds": 10.0},
         is_ok(lambda r: r.get("value") == "0x00000001" and r.get("released") is True)),
    Case("input.value as decimal text", "input",
         {"port": ":P1", "field": "Coin 1", "value": "1", "frames": 1, "seconds": 10.0},
         refused_saying("decimal text is refused")),
    *waits("input", "seconds", {"port": ":P1", "field": "Coin 1", "frames": 1},
           at_max=ENDS_IN_FRAMES, absent=ENDS_IN_FRAMES),
    # The frame notifier cannot end a recording on the call that begins it, so the minimum
    # is two and one is refused rather than recorded as two.
    Case("record.frames at min 2", "record", {"frames": 2, "seconds": 10.0},
         is_ok(lambda r: r.get("avi_frames") == 2)),
    Case("record.frames below min 2", "record", {"frames": 1, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("record.frames zero", "record", {"frames": 0, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("record.dest relative", "record", {"frames": 2, "dest": "rel.avi", "seconds": 10.0},
         is_refused("bad_argument")),
    *waits("record", "seconds", {"frames": 2}, at_max=ENDS_IN_FRAMES, absent=ENDS_IN_FRAMES),
    # The mixer writes whole updates of a fiftieth of an emulated second, so two frames is the
    # shortest span that holds one on a screen under 100 Hz; a bool is not a count.
    Case("audio_record.frames at min 2", "audio_record", {"frames": 2, "seconds": 10.0},
         is_ok(STOPPED_SAYS["audio_record"])),
    Case("audio_record.frames below min 2", "audio_record", {"frames": 1, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("audio_record.frames zero", "audio_record", {"frames": 0, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("audio_record.frames a bool", "audio_record", {"frames": True, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("audio_record.dest relative", "audio_record",
         {"frames": 2, "dest": "rel.wav", "seconds": 10.0}, is_refused("bad_argument")),
    *waits("audio_record", "seconds", {"frames": 2}, at_max=ENDS_IN_FRAMES,
           absent=ENDS_IN_FRAMES),
    *waits("throttle", "seconds", {"on": False}, at_max=STOPPED_THROTTLE, absent=None),
    Case("throttle.seconds absent", "throttle", {"on": False}, is_ok()),
    *waits("run_to", "seconds", {"ref": "irq_vblank", "control": "0x4a0"}, at_max=RUNS_EVERY_FRAME,
           absent=RUNS_EVERY_FRAME, then="declaration_clear breakpoint"),
    Case("run_to.condition absent", "run_to",
         {"ref": "irq_vblank", "control": "0x4a0", "seconds": 10.0},
         is_ok(lambda r: r.get("verdict") == "TARGET"), then="declaration_clear breakpoint"),
    Case("run_to.condition with a comma", "run_to",
         {"ref": "irq_vblank", "control": "0x4a0", "condition": "d0==1,d1==2", "seconds": 10.0},
         is_refused("bad_argument")),
    Case("run_to.condition that assigns", "run_to",
         {"ref": "irq_vblank", "control": "0x4a0", "condition": "d0=1", "seconds": 10.0},
         is_refused("bad_argument")),
    Case("run_to.ref empty", "run_to", {"ref": "", "control": "0x4a0", "seconds": 10.0},
         is_refused("bad_argument")),
    Case("run_to.control empty: refused", "run_to",
         {"ref": "irq_vblank", "control": "", "seconds": 10.0}, is_refused("bad_argument")),
    *waits("run_for", "seconds", {"frames": 1}, at_max=ENDS_IN_FRAMES, absent=ENDS_IN_FRAMES),
    Case("run_for.milliseconds and frames both absent", "run_for", {"seconds": 10.0},
         is_refused("bad_argument")),
    Case("run_for.milliseconds and frames both given", "run_for",
         {"milliseconds": 10, "frames": 1, "seconds": 10.0}, is_refused("bad_argument")),
    Case("run_for.frames negative", "run_for", {"frames": -1, "seconds": 10.0},
         is_refused("bad_argument")),
    *waits("trace", "seconds", {"frames": 1}, at_max=ENDS_IN_FRAMES, absent=ENDS_IN_FRAMES),
    Case("trace.milliseconds and frames both absent", "trace", {"seconds": 10.0},
         is_refused("bad_argument")),
    Case("trace.milliseconds and frames both given", "trace",
         {"milliseconds": 10, "frames": 1, "seconds": 10.0}, is_refused("bad_argument")),
    Case("trace.frames negative", "trace", {"frames": -1, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("trace.frames True", "trace", {"frames": True, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("resume.seconds absent", "resume", {},
         is_ok(lambda r: "verdict" not in r and "halted" not in r),
         then="stop"),
    Case(f"resume.seconds at max {WAIT_MAX:g}", "resume", {"seconds": WAIT_MAX},
         is_ok(lambda r: r.get("verdict") == "OTHER_STOP"), exempt=STOP_AT_ONCE,
         before=("breakpoint_at", {"ref": "irq_vblank"}), then="declaration_clear breakpoint"),
    Case("resume.seconds one past max", "resume", {"seconds": ONE_PAST_WAIT},
         is_refused("bad_argument"), exempt=PRE_GATE),
    Case("resume.seconds far past max", "resume", {"seconds": float(FAR)},
         is_refused("bad_argument"), exempt=PRE_GATE),
    Case("resume.seconds negative", "resume", {"seconds": -1.0}, is_refused("bad_argument")),
    Case("step.count absent", "step", {}, is_ok(lambda r: r.get("instructions_completed") == 1)),
    Case("step.count zero", "step", {"count": 0}, is_refused("bad_argument")),
    Case("step.mode outside the vocabulary", "step", {"mode": "sideways"},
         is_refused("bad_argument")),
    Case(f"state_write save.name at max {NAME_MAX}", "state_write", {"method": "save",
                                                                     "name": MAX_NAME},
         is_ok()),
    Case("state_write save.name one past max", "state_write", {"method": "save",
                                                               "name": MAX_NAME + "s"},
         is_refused("bad_argument")),
    Case("state_write save.name far past max", "state_write", {"method": "save",
                                                               "name": "s" * 10_000},
         is_refused("bad_argument")),
    Case("state_write save.name empty", "state_write", {"method": "save", "name": ""},
         is_refused("bad_argument")),
    Case("state_write save.name with a space", "state_write", {"method": "save", "name": "a b"},
         is_refused("bad_argument")),
    Case(f"state_write load.name at max {NAME_MAX}", "state_write", {"method": "load",
                                                                     "name": MAX_NAME},
         is_ok(load_judged)),
    Case("state_write load.name one past max", "state_write", {"method": "load",
                                                               "name": MAX_NAME + "s"},
         is_refused("bad_argument")),
    Case("state_write load.name far past max", "state_write", {"method": "load",
                                                               "name": "s" * 10_000},
         is_refused("bad_argument")),
    Case("state_write load.name empty", "state_write", {"method": "load", "name": ""},
         is_refused("bad_argument")),
    Case("set_register.value at max of a 32-bit D0", "set_register",
         {"name": "D0", "value": 0xFFFFFFFF}, is_ok(lambda r: r.get("verified") is True)),
    Case("set_register.value one past max", "set_register",
         {"name": "D0", "value": 0x1_0000_0000}, is_refused("bad_argument")),
    Case("set_register.value far past max", "set_register", {"name": "D0", "value": 2**64},
         is_refused("bad_argument")),
    Case("set_register.value negative", "set_register", {"name": "D0", "value": -1},
         is_refused("bad_argument")),
    Case("set_register.value at max written 0x", "set_register",
         {"name": "D0", "value": "0xFFFFFFFF"},
         is_ok(lambda r: r.get("verified") is True and r.get("value") == "0xffffffff")),
    Case("set_register.value one past max written 0x", "set_register",
         {"name": "D0", "value": "0x100000000"}, refused_saying("does not fit")),
    Case("set_register.value as decimal text", "set_register", {"name": "D0", "value": "4660"},
         refused_saying("decimal text is refused")),
    Case("set_register.value 0x with no digits", "set_register", {"name": "D0", "value": "0x"},
         refused_saying("starts like hex")),
    Case("declaration_clear regpoint.ref names a condition's number in the other spelling",
         "perform",
         {"steps": [{"op": "regpoint_add", "condition": "d0==0x7ff1"},
                    {"op": "declaration_clear", "kind": "regpoint", "ref": "d0==7ff1"}],
          "settle_seconds": 2.0},
         is_ok(lambda r: r.get("steps_completed") == 2 and (r.get("ran") or [{}, {}])[1].get(
             "reply", {}).get("declarations_cleared") == 1)),
    # The console reads `$` as hex and `#` as decimal: 0x7ff2 is 32754.
    Case("declaration_clear regpoint.ref names a `$` condition's number in its `#` spelling",
         "perform",
         {"steps": [{"op": "regpoint_add", "condition": "d0==$7ff2"},
                    {"op": "declaration_clear", "kind": "regpoint", "ref": "d0==#32754"}],
          "settle_seconds": 2.0},
         is_ok(lambda r: r.get("steps_completed") == 2 and (r.get("ran") or [{}, {}])[1].get(
             "reply", {}).get("declarations_cleared") == 1)),
    # The fold above is the server's; these two are the console's own reading of the prefixes.
    *[Case(f"debug.command the console reads `{n}` as 0x{v}", "debug", {"command": f"print {n}"},
           is_ok(prints(v)))
      for n, v in (("#32754", "7FF2"), ("$7ff2", "7FF2"), ("0b101", "5"), ("0o17", "F"))],
    # A ref no cell declares, so the refusal holds in any order of the list.
    Case("declaration_clear regpoint.ref never declared states the rule it is matched under",
         "declaration_clear", {"kind": "regpoint", "ref": "d0==7ff3"},
         lambda r: refused(r, "unknown_ref") and all(words in " ".join(str(
             r.get("message")).split()) for words in (
                 "`declaration_list(kind=\"regpoint\")`",
                                                      f"Matching: {dec.REF_MATCH['regpoint']}."))),
    Case("perform.steps a set_register step written 0x", "perform",
         {"steps": [{"op": "set_register", "name": "D0", "value": "0x0"}], "settle_seconds": 2.0},
         is_ok(lambda r: r.get("steps_completed") == 1)),
    Case("set_register.name this cpu lacks", "set_register", {"name": "XX", "value": 0},
         is_refused()),
    Case("rom_check.reference_addr at the image's last 16 bytes", "rom_check",
         {"reference_rom": REFERENCE_ROM, "reference_addr": "0xffff0"}, is_ok()),
    Case("rom_check.reference_addr one past the image", "rom_check",
         {"reference_rom": REFERENCE_ROM, "reference_addr": "0xffff1"}, is_refused()),
    Case("rom_check.reference_addr far past the image", "rom_check",
         {"reference_rom": REFERENCE_ROM, "reference_addr": "0x10000000"}, is_refused()),
    Case("rom_check.reference_addr not hex", "rom_check",
         {"reference_rom": REFERENCE_ROM, "reference_addr": "zz"}, is_refused("bad_argument")),
    Case("memdump.length zero", "memdump", {"ref": "0x0", "length": 0, "dest": "/tmp/x"},
         is_refused("bad_argument")),
    Case("memdump.dest relative", "memdump", {"ref": "0x0", "length": 4, "dest": "rel.bin"},
         is_refused("bad_argument")),
    Case("memdump.dest already there", "memdump",
         {"ref": "0x0", "length": 4, "dest": str(TRANSCRIPT)}, is_refused("bad_argument")),
    Case("memdump.dest with a comma", "memdump",
         {"ref": "0x0", "length": 4, "dest": str(SCRATCH / "a,b.bin")}, is_refused("bad_argument")),
    Case("memdump.dest with a semicolon", "memdump",
         {"ref": "0x0", "length": 4, "dest": str(SCRATCH / "a;b.bin")}, is_refused("bad_argument")),
    Case("memdump.dest in a missing directory", "memdump",
         {"ref": "0x0", "length": 4, "dest": str(SCRATCH / "no" / "x.bin")},
         is_refused("bad_argument")),
    Case("snapshot.dest absent", "snapshot", {}, is_ok()),
    Case("snapshot.dest relative", "snapshot", {"dest": "rel.png"}, is_refused("bad_argument")),
    Case("write.data_hex empty", "write", {"ref": "0x200000", "data_hex": ""},
         is_refused("bad_argument")),
    Case("write.data_hex odd digits", "write", {"ref": "0x200000", "data_hex": "0"},
         is_refused("bad_argument")),
    # The ceiling is `read_memory`'s, since a write is read back through it; past one stub
    # packet the write is split, which the edge at the ceiling already crosses.
    Case(f"write.data_hex at max {read.READ_MAX} bytes", "write",
         {"ref": "0x200000", "data_hex": "11" * read.READ_MAX},
         is_ok(lambda r: r.get("verified") is True)),
    Case("write.data_hex one past max", "write",
         {"ref": "0x200000", "data_hex": "22" * (read.READ_MAX + 1)}, is_refused("bad_argument")),
    Case("find.data_hex empty", "find", {"ref": "0x0", "length": 16, "data_hex": ""},
         is_refused("bad_argument")),
    Case("find.symbol_class and ref both given", "find",
         {"ref": "0x0", "length": 16, "data_hex": "00", "symbol_class": "CODE"},
         is_refused("bad_argument")),
    Case("find.symbol_class and ref both absent", "find", {"data_hex": "00"},
         is_refused("bad_argument")),
    Case("find.symbol_class the table does not carry", "find",
         {"data_hex": "00", "symbol_class": "NOPE"},
         is_refused()),
    # Over the ROM, whose bytes no cell writes: its zeros make a console answer longer than one
    # window can carry, which is what `find`'s windows exist for.
    Case("find.hits past 400 keep the highest", "find",
         {"ref": "0x0", "length": 0x20000, "data_hex": "00"},
         is_ok(lambda r: r.get("hits_total", 0) > 400 and len(r.get("hits", [])) == 400
               and r.get("truncated") is True
               and r["hits"] == sorted(r["hits"], key=lambda h: int(h, 16)))),
    Case("breakpoint_at.role outside the vocabulary", "breakpoint_at",
         {"ref": "0x400", "role": "watch"}, is_refused("bad_argument")),
    Case("breakpoint_at.by outside the vocabulary", "breakpoint_at",
         {"ref": "400", "by": "guess"}, is_refused("bad_argument")),
    Case("breakpoint_at.condition on a control", "breakpoint_at",
         {"ref": "0x400", "role": "control", "condition": "d0==1"}, is_refused("bad_argument")),
    Case("breakpoint_at.ref segmented", "breakpoint_at", {"ref": "F000:9627"},
         is_refused("bad_argument")),
    Case("declaration_clear breakpoint.ref no declaration holds", "declaration_clear",
         {"kind": "breakpoint",
                                                                            "ref": "nosuch"},
         is_refused()),
    Case("declaration_clear breakpoint.ref absent", "declaration_clear", {"kind": "breakpoint"},
         is_refused("bad_argument")),
    Case("declaration_clear breakpoint.all", "declaration_clear", {"kind": "breakpoint",
                                                                   "all": True}, is_ok()),
    Case("declaration_clear watch.ref no declaration holds", "declaration_clear", {"kind": "watch",
                                                                       "ref": "nosuch"},
         is_refused()),
    Case("declaration_clear watch.ref absent", "declaration_clear", {"kind": "watch"},
         is_refused("bad_argument")),
    Case("declaration_clear watch.all", "declaration_clear", {"kind": "watch", "all": True},
         is_ok()),
    Case("declaration_clear regpoint.ref absent", "declaration_clear", {"kind": "regpoint"},
         is_refused("bad_argument")),
    Case("declaration_clear regpoint.all", "declaration_clear", {"kind": "regpoint", "all": True},
         is_ok()),
    Case("machine_map.cpu absent", "machine_map", {}, is_ok(lambda r: len(r["cpus"]) == 2)),
    Case("machine_map.cpu bare tag", "machine_map", {"cpu": "maincpu"},
         is_ok(lambda r: [c["cpu"] for c in r["cpus"]] == [":maincpu"])),
    Case("machine_map.cpu full tag", "machine_map", {"cpu": ":subcpu"},
         is_ok(lambda r: [c["cpu"] for c in r["cpus"]] == [":subcpu"])),
    Case("machine_map.cpu the machine lacks", "machine_map", {"cpu": "nosuch"},
         is_refused("unknown_ref")),
    Case("debug.command empty (contract silent)", "debug", {"command": ""}, silent),
    Case("registers.from_last_stop true", "registers", {"from_last_stop": True},
         is_ok(lambda r: r.get("superseded") is True)),
]


def _tenth_control() -> tuple[Case, Case]:
    """The debugger's ten `temp` variables are the ceiling on controls: the tenth is taken,
    the eleventh is refused. The addresses are code in the vblank handler, never halted on."""
    return (Case("breakpoint_at.control the tenth", "breakpoint_at",
                 {"ref": f"{0x400 + 2 * 9:#x}", "role": "control"},
                 is_ok(lambda r: r.get("armed") is True)),
            Case("breakpoint_at.control the eleventh", "breakpoint_at",
                 {"ref": f"{0x400 + 2 * 10:#x}", "role": "control"}, is_refused()))


#: A watched window's first flags. Windows ignores `-resolution` under `-nomaximize`, so a
#: fitted window drops that flag there and states its size instead (`window_words.mame`).
WATCHED_FLAGS = (["-window", "-resolution"] if sys.platform == "win32"
                 else ["-window", "-nomaximize", "-resolution"])

NO_SESSION_CASES: list[Case] = [
    Case("start.stub_port at max 65535", "start", {**BOOT, "stub_port": 65535},
         is_ok(lambda r: r.get("stub_port") == 65535), then="close"),
    Case("start.stub_port one past max", "start", {**BOOT, "stub_port": 65536},
         is_refused("bad_argument")),
    Case("start.stub_port far past max", "start", {**BOOT, "stub_port": FAR},
         is_refused("bad_argument")),
    Case("start.shared opens a window scaled from the machine's screen", "start",
         {**BOOT, "shared": True, "background": True},
         is_ok(lambda r: r.get("flags", [])[:len(WATCHED_FLAGS)] == WATCHED_FLAGS),
         then="close"),
    Case("start.display names the display the window opens on and the start proves it", "start",
         {**BOOT, "shared": True, "display": 0, "background": True},
         is_ok(lambda r: (r.get("window") or {}).get("display") == 0
               and (r.get("window") or {}).get("onscreen") is True
               and r.get("flags", [])[-2:] == ["-screen0", "screen0"]),
         then="close"),
    Case("start.display without shared", "start", {**BOOT, "display": 0},
         refused_saying("shared=true")),
    Case("start.display past the host's displays", "start",
         {**BOOT, "shared": True, "display": FAR}, refused_saying("does not exist")),
    Case("window answers the window the start proved", "window", {},
         is_ok(lambda r: (r.get("window") or {}).get("display") == 0
               and (r.get("window") or {}).get("onscreen") is True),
         before=("start", {**BOOT, "shared": True, "display": 0, "background": True}),
         then="close"),
    Case("start.throttle_from_frame negative", "start", {**BOOT, "throttle_from_frame": -1},
         is_refused("bad_argument")),
    Case("start.rompath relative", "start", {**BOOT, "rompath": "run/mame_roms"},
         is_refused("bad_argument")),
    Case("start.system the binary lacks", "start", {**BOOT, "system": "nosuchsystem"},
         is_refused()),
    Case("start.reference_addr at the image's last 16 bytes", "start",
         {**BOOT, "reference_addr": "0xffff0"}, is_ok(), then="close"),
    Case("start.reference_addr one past the image", "start",
         {**BOOT, "reference_addr": "0xffff1"}, is_refused()),
    Case("start.reference_addr far past the image", "start",
         {**BOOT, "reference_addr": "0x10000000"}, is_refused()),
]


def run_case(c: Case) -> dict[str, Any]:
    if c.before is not None and not ok(set_up := call(c.before[0], **c.before[1])):
        cell(c.label, False, f"its setup {c.before[0]} failed: {said(set_up)}")
        if c.then:
            restore(c.then)
        return set_up
    try:
        r = call(c.tool, b1_exempt=c.exempt, **c.kw)
    except Blocked as e:
        blocked(c.label, str(e))
        return {}
    good = c.judge(r)
    detail = said(r)
    if good and c.exempt and last_wall() > WAIT_CEILING_S:
        good, detail = False, f"took {last_wall():.1f} s where {c.exempt!r}"
    cell(c.label, good, detail if good else f"{r.get('code', '')} {detail}")
    if c.then:
        restore(c.then)
    return r


def killed_it(r: dict[str, Any]) -> bool:
    """Did this call leave no usable machine behind? A cell after it would fail for the
    machine's death and say nothing about its own tool."""
    return "exception" in r or r.get("session", {}).get("alive") is False


def run_cases_stopped(cases: list[Case]) -> None:
    """Each case on a stopped machine, booting a fresh one after a call that killed or hung it:
    the death is the cell that caused it, not every cell after."""
    for c in cases:
        if killed_it(run_case(c)):
            ensure_closed()
            boot()


# A CONSOLE COMMAND'S EDGE IS THE STUB'S OWN PACKET SIZE, which only the live session knows, so
# these three are judged at run time off the rule `Session.max_payload` states and never off a
# literal: the maximum, one past it, and the overflow.
DEBUG_EDGES = ["debug.command at the stub's packet limit answers ok",
               "debug.command one past the stub's packet limit is bad_argument at once",
               "debug.command four times the stub's packet limit is bad_argument at once"]


def _debug_edges() -> None:
    payload = STATE.ses.max_payload() if STATE.ses is not None else None
    if payload is None:
        for label in DEBUG_EDGES:
            blocked(label, "the stub advertised no packet size, so there is no limit to probe")
        return
    limit = (payload - len("qRcmd,")) // 2

    def command(n: int) -> str:
        # `print 1` padded with spaces, which the console's expression reader skips.
        return "print 1".ljust(n)

    r = call("debug", command=command(limit))
    cell(DEBUG_EDGES[0], ok(r) and r.get("output", "").strip() == "1",
         f"{limit} chars: {said(r)}")
    for label, n in ((DEBUG_EDGES[1], limit + 1), (DEBUG_EDGES[2], 4 * limit)):
        r = call("debug", command=command(n))
        cell(label, refused(r, "bad_argument") and r.get("command_chars") == n
             and r.get("limit_chars") == limit and last_wall() < 1.0,
             f"{n} chars in {last_wall()} s: {said(r)}")


# A CONDITION'S EDGE IS THE SAME PACKET, reached through the `bp` command the arming builds:
# a refusal there must leave nothing behind, neither a stored declaration nor a declared
# control nor a disarmed watch.
BP_CONDITION_EDGES = [
    "breakpoint_at.condition at the stub's packet limit is armed",
    "breakpoint_at.condition one past the stub's packet limit is bad_argument and stores nothing",
    "breakpoint_at.condition four times the stub's packet limit is bad_argument and stores "
    "nothing",
    "run_to.condition one past the stub's packet limit leaves the watch armed and declares no "
    "control",
    "declaration_list breakpoint reads the at-limit row whole",
    "declaration_list watch reads a foreign conditioned watchpoint row",
]


def _condition(addr: int, chars: int, evaluated: bool = True) -> str:
    """`d0==0x<zeros>1`, sized so the LONGEST command it goes out in is `chars` long: the `bp`
    at `addr` in its CONSOLE form, on the visible cpu it names, and for a declaration the
    `print {...}` that evaluates it first. Leading zeros change a hex literal's length and not
    its value."""
    cond = conditions.console_condition("d0==0x1")
    on = cpus.visible_cpu(STATE.ses) if STATE.ses is not None else None   # where it is armed
    sent = [breakpoints.bp_command(addr, cond, on)] + ([f"print {{{cond}}}"] if evaluated else [])
    zeros = chars - max(len(c) for c in sent)
    if zeros < 0:
        raise ValueError(f"no condition of this shape makes a {chars}-character command")
    return "d0==0x" + "0" * zeros + "1"


def _bp_condition_edges() -> None:
    payload = STATE.ses.max_payload() if STATE.ses is not None else None
    if payload is None:
        for label in BP_CONDITION_EDGES:
            blocked(label, "the stub advertised no packet size, so there is no limit to probe")
        return
    limit = (payload - len("qRcmd,")) // 2
    call("declaration_clear", kind="breakpoint", all=True)
    at_limit = _condition(0x400, limit)
    r = call("breakpoint_at", ref="0x400", condition=at_limit)
    cell(BP_CONDITION_EDGES[0], ok(r) and r.get("armed") is True, f"{limit} chars: {said(r)}")
    listed = by_ref(call("declaration_list", kind="breakpoint").get("breakpoints")).get("0x400", {})
    cell(BP_CONDITION_EDGES[4], listed.get("state") == "armed"
         and listed.get("condition") == at_limit
         and str(listed.get("entry", "")).endswith(f" if {conditions.console_condition(at_limit)}"),
         f"state {listed.get('state')}, entry of {len(str(listed.get('entry', '')))} chars")
    call("declaration_clear", kind="breakpoint", all=True)
    for label, n in ((BP_CONDITION_EDGES[1], limit + 1), (BP_CONDITION_EDGES[2], 4 * limit)):
        before = call("declaration_list", kind="breakpoint").get("breakpoints")
        r = call("breakpoint_at", ref="0x400", condition=_condition(0x400, n))
        after = call("declaration_list", kind="breakpoint").get("breakpoints")
        cell(label, refused(r, "bad_argument") and r.get("command_chars") == n
             and r.get("limit_chars") == limit and isinstance(before, list) and after == before,
             f"{n} chars: {said(r)}; declarations {len(before or [])} -> {len(after or [])}")
    call("watch_add", ref="0x2031fc", mode="change", length=4)
    controls = dict(STATE.controls)
    target = STATE.resolve("irq_vblank")
    r = call("run_to", ref="irq_vblank", control="0x4a0", disarm_watches=True, seconds=5.0,
             condition=_condition(target, limit + 1, evaluated=False))
    w = by_ref(call("declaration_list", kind="watch").get("watches")).get("0x2031fc", {})
    cell(BP_CONDITION_EDGES[3], refused(r, "bad_argument")
         and r.get("command_chars") == limit + 1 and w.get("state") == "armed"
         and STATE.controls == controls,
         f"{said(r)}; watch {w.get('state')}; controls {sorted(controls)} -> "
         f"{sorted(STATE.controls)}")
    call("declaration_clear", kind="watch", all=True)
    call("declaration_clear", kind="breakpoint", all=True)
    # A watchpoint row carries its condition the way a breakpoint row does, and one long
    # enough to wrap is still read as ONE foreign row.
    cond = "d0==0x" + "0" * 400 + "1"
    call("debug", command=f"wpset 0x2031fc,0x4,w,{cond}")
    r = call("declaration_list", kind="watch")
    foreign = r.get("foreign", {}).get("watches", [])
    cell(BP_CONDITION_EDGES[5], ok(r) and len(foreign) == 1
         and str(foreign[0]).endswith(f"write if {cond}"),
         f"{len(foreign)} foreign: {[str(f)[:40] for f in foreign]}")
    call("debug", command="wpclear")


@section("B", "every argument at its documented edge, on a stopped machine",
         [c.label for c in STOPPED_CASES] + [c.label for c in _tenth_control()] + DEBUG_EDGES
         + BP_CONDITION_EDGES)
def block_b_stopped() -> None:
    boot()
    # In list order: `state_write load.name at max` loads what `state_write save.name at max` wrote.
    run_cases_stopped(STOPPED_CASES)
    _debug_edges()
    _bp_condition_edges()
    for i in range(9):
        call("breakpoint_at", ref=f"{0x400 + 2 * i:#x}", role="control")
    for c in _tenth_control():
        run_case(c)
    call("declaration_clear", kind="breakpoint", all=True)


@section("B", "start's arguments at their edges, with no session",
         [c.label for c in NO_SESSION_CASES])
def block_b_start() -> None:
    ensure_closed()
    for c in NO_SESSION_CASES:
        run_case(c)


# Section 13: the readers at the address map's edges, which the machine declares at `start`.
EDGES = ("address 0", "the last mapped byte", "straddling the last mapped byte",
         "an unmapped hole", "straddling the space's end")
READERS_AT_EDGES = ("read_memory", "read_block", "disassemble", "find", "memdump")


def _edge_label(tool: str, edge: str) -> str:
    return f"{tool} at {edge}"


@section("B", "readers at the address map's edges (section 13)",
         [_edge_label(t, e) for t in READERS_AT_EDGES for e in EDGES]
         + ["history at one instruction"])
def block_b_edges() -> None:
    boot()
    reply = call("machine_map", cpu="maincpu")
    # BOTH EDGES ARE THE MACHINE'S, never a cpu's width written here, and both come from the
    # reply alone: an edge only this process could compute is one no MCP client could ask for.
    missing = {"an unmapped hole": "the program space's map leaves no hole",
               "straddling the space's end": "`machine_map` carries no program address mask"}
    at = {"address 0": (0, 8)}
    try:
        last, hole, space_end = program_edges(reply, reply["cpu"])
        at.update({"the last mapped byte": (last, 1),
                   "straddling the last mapped byte": (last - 3, 8)})
    except LookupError as exc:
        hole, space_end = None, None
        missing = dict.fromkeys(EDGES, str(exc))
    if hole is not None:
        at["an unmapped hole"] = (hole, 8)
    if space_end is not None:
        at["straddling the space's end"] = (space_end - 3, 8)
    for edge in EDGES:
        if edge not in at:
            for tool in READERS_AT_EDGES:
                blocked(_edge_label(tool, edge), missing[edge])
            continue
        addr, n = at[edge]
        ref = f"{addr:#x}"
        r = call("read_memory", ref=ref, length=n)
        # A read of a mapped byte answers it, and one past the space's end is refused; into a
        # hole the docstring names zeros only for a write-only block, so the rest is the
        # transcript's to judge.
        good = {"address 0": ok(r) and hex_len(n)(r),
                "the last mapped byte": ok(r) and hex_len(n)(r),
                "straddling the space's end": refused(r, "bad_argument")}.get(edge, whole(r))
        cell(_edge_label("read_memory", edge), good, said(r))
        r = call("read_block", ref=ref, length=n)
        # By address the block is the one the map entry names; a hole names none, and a read
        # past a block's end is refused because MAME answers zeros there in silence.
        good = {"address 0": ok(r) and r.get("offset") == 0,
                "an unmapped hole": refused(r, "unknown_ref")}.get(
            edge, refused(r, "unknown_ref", "bad_argument") or ok(r))
        cell(_edge_label("read_block", edge), good, said(r))
        r = call("disassemble", ref=ref, length=n)
        # A `read_block` refused above had already stepped the cpu for its evaluation: that
        # stop is its own, and this call must not find it as the machine's.
        cell(_edge_label("disassemble", edge), ok(r) and bool(r.get("lines"))
             and "stopped_on_its_own" not in r, said(r))
        # Past the space's end no address exists: `find` and `memdump` refuse the range, and the
        # console's `save` would hang on it besides.
        past = edge == "straddling the space's end"
        r = call("find", ref=ref, length=n, data_hex="00")
        cell(_edge_label("find", edge), refused(r, "bad_argument") if past
             else ok(r) and isinstance(r.get("hits_total"), int), said(r))
        r = call("memdump", ref=ref, length=n, dest=fresh(".bin"))
        good = refused(r, "bad_argument") if past else ok(r) and r.get("bytes") == n
        cell(_edge_label("memdump", edge), good, said(r))
        if killed_it(r):
            ensure_closed()
            boot()
    r = call("history", limit=1)
    cell("history at one instruction", ok(r) and len(r.get("lines", [])) == 1, said(r))


#
# (S1 c.) Each section is one item of the plan's interaction list: a sequence where one tool's
# effect is what the next one reads. The contract of each cell is the docstring of the tool that
# answers it.


def by_ref(items: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {str(w.get("ref")): w for w in items or []}
