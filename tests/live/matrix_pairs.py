"""Section C of the live matrix: the tools that share state, in pairs."""


import hashlib
import json
import math
import os
import re
import struct
import subprocess
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bench_boards import (
    MANIFEST,
    SUB_SYMBOLS,
    SYMBOLS,
)
from gfx_layouts import BYTES_8X8
from live_harness import (
    PENDING,
    SCRATCH,
    blocked,
    boot,
    call,
    cell,
    fresh,
    ok,
    rearm_pairs,
    refused,
    said,
    section,
    session_is,
    whole,
)

from evidence import (  # isort: skip -- it imports the server's files, so after the harness
    console_disagreement,
    console_in_log,
    console_ran_the_throttle_first,
    sentinel_order,
)

import mame_transport as transport

import mame_callbacks as callbacks  # isort: skip
import mame_capture as mcapture  # isort: skip
import mame_watches as mwatches  # isort: skip
import server as s  # isort: skip
from scry_core import png, series  # isort: skip
from scry_core import value_format as vf  # isort: skip
from mame_state import STATE  # isort: skip
from matrix_edges import (  # noqa: E402
    SEEN_ACT,
    by_ref,
)
from matrix_tools_by_state import (  # noqa: E402
    BLIT_TRIGGER,
    BLITTER,
    FILM,
    MAIN,
    PROBES,
    SUB,
)

# A FAULT PLANTED FROM THE HARNESS, never from the server: one Lua chunk that reaches the tap's
# item in the server's registry and makes the tap's own body raise at its next write, the way a
# body with a bug would; uncaught, it reads as a tap that saw nothing (`mame_callbacks` says why).
# `plant` is Lua over the item `t`; `said` is a Lua expression printed at the same instant, a
# baseline the cell reads back.
FAULT = "planted fault"


def plant_fault(registry: str, item_id: str, plant: str, said: str = '""') -> dict[str, Any]:
    return call("lua", read_only=True, script=(
        f'local t = _G.{registry} and _G.{registry}.items["{item_id}"]\n'
        f'if t == nil then error("no item {item_id} in {registry}") end\n'
        f"{plant}\nprint(\"planted \" .. tostring({said}))"))


def planted_at(r: dict[str, Any]) -> int:
    """The baseline a `plant_fault` printed, or -1 when it did not answer."""
    m = re.search(r"planted (\d+)", str(r.get("output") or ""))
    return int(m.group(1)) if m else -1


def raised(w: dict[str, Any]) -> tuple[int, str]:
    """A reply's `callback_errors`, as (count, first), (-1, "") when it carries none."""
    errors = w.get("callback_errors") or {}
    return int(errors.get("count", -1)), str(errors.get("first") or "")


# A DUMPER FAULTED FROM THE HARNESS: the item's `endianness`, which only its dumper reads, and
# only once its `.tmp` is open (the head's last line), is made to raise when formatted, so the
# dump fails half-way through a write, as a dumper with a bug would. `mame_callbacks`'s guard
# then closes the file, logs `MCP_DUMP_FAILED <id>` once per run of failures, and the dump on
# disk stays the last one finished, which a later stop reads as superseded.
DUMPER_FAULT = ('t.endianness = setmetatable({}, {__tostring = function() error("' + FAULT
                + '") end})')


def open_files(pid: object) -> list[str] | None:
    """The paths `lsof` lists open in `pid`, resolved as `lsof` resolves them (`/var` is
    `/private/var` on this host), or None when it could not say."""
    r = subprocess.run(["lsof", "-a", "-p", str(pid), "-F", "n"], capture_output=True,
                       text=True, check=False)
    names = [ln[1:] for ln in r.stdout.splitlines() if ln.startswith("n")]
    return names if r.returncode == 0 and names else None


def dumper_fault_cell(label: str, registry: str, item_id: str, ref: str, dump: Path) -> None:
    """`label` judged over the item `item_id` of `registry`, whose dump is `dump`, on the stop
    survey, the one reading that judges a dump against the frame: before the plant the dump is
    current (the control), after it the guard's line is in `error.log` once over two stops, the
    `.tmp` the dumper opened exists and is closed (`lsof`, itself seen to list `error.log`
    open), and the dump read at the stop is superseded, its `why` naming the planted error."""
    status = call("status")
    errorlog, pid = Path(str(status.get("errorlog_path"))), status.get("pid")
    before = by_ref(call("run_for", frames=2, seconds=10.0).get("watches")).get(ref, {})
    at = planted_at(plant_fault(registry, item_id, DUMPER_FAULT, "t.seq"))
    call("run_for", frames=4, seconds=10.0)
    w = by_ref(call("run_for", frames=4, seconds=10.0).get("watches")).get(ref, {})
    said_line = f"{callbacks.DUMP_FAILED} {item_id} "
    logged = [ln for ln in errorlog.read_text(errors="replace").splitlines() if said_line in ln]
    tmp = Path(os.path.realpath(f"{dump}.tmp"))
    errorlog = Path(os.path.realpath(errorlog))
    names = open_files(pid)
    why = str(w.get("why"))
    still_open = None if names is None else str(tmp) in names
    detail = (f"before superseded {before.get('superseded')}; planted at seq {at}; logged "
              f"{logged}; .tmp there {tmp.exists()}, open {still_open}; "
              f"after superseded {w.get('superseded')}, why {why[-120:]!r}")
    if at < 0:
        blocked(label, f"the dumper fault was not planted, so nothing was faulted: {detail}")
        return
    if names is None or not any(n == str(errorlog) for n in names):
        blocked(label, f"lsof could not be read, or did not list error.log open: {detail}")
        return
    cell(label, "superseded" not in before and len(logged) == 1
         and FAULT in logged[0] and tmp.exists() and str(tmp) not in names
         and w.get("superseded") is True and "the dumper raised writing a newer one" in why
         and FAULT in why, detail)


def writes(r: dict[str, Any]) -> int:
    """How many calls wrote to the machine, off a reply whose block is whole (`start`,
    `status`): every other reply names the count in `omitted`."""
    return int(r.get("session", {}).get("altering_writes", -1))


SEQ = re.compile(r"#(\d+)")


def seq_of(r: dict[str, Any]) -> int | None:
    """The console sequence number a reply names, in its `call`, or a throttle's `tag` (the
    `call` first: `read_block`'s `tag` is the region it read)."""
    m = SEQ.search(str(r.get("call") or r.get("tag") or ""))
    return int(m.group(1)) if m else None


C1 = [
    "a symbol breakpoint comes back rearmed",
    "a raw-address control over the same build comes back rearmed",
    "a change watch by symbol comes back rearmed",
    "a count watch comes back rearmed, its install sent again",
    "a show watch and an expr watch come back evaluated",
    "nothing is stale, unresolved or unarmable over the same build",
    "held counts every declaration the store kept",
    "every breakpoint row the store brought back says inherited",
    "every watch row the store brought back says inherited",
    "the inherited raw-address control is listed armed",
    "the inherited count watch tallies on the next run",
    "a declaration made this session says inherited false",
    "a condition is stored as typed and replied as the console reads it",
    "a raw address over another build comes back stale, not armed",
    "a symbol over another build comes back rearmed",
    "the stale row is listed stale",
    "declaring the stale address again adopts it",
]


@section("C", "1. declarations across start", C1)
def c1_declarations() -> None:
    # A COPY of the table, so the second build below is this file edited, under the same key.
    table = SCRATCH / "c1-symbols.yaml"
    table.write_text(Path(SYMBOLS).read_text())
    boot(symbols=str(table))
    # The STOP is on a routine a healthy boot never runs: re-armed on the vblank it would cut
    # every run of this section at its first frame, which is the re-arm working, not a finding.
    call("breakpoint_at", ref="exception_handler")
    call("breakpoint_at", ref="0x4a0", role="control")
    call("watch_add", ref="main_ram", mode="change", length=4)
    call("watch_add", ref="0x203200", mode="show", length=2)
    call("watch_add", ref="0x2031fc", mode="count", length=4)
    call("watch_add", ref="beamy", mode="expr")
    call("close")
    r = boot(symbols=str(table))
    decl = r.get("declarations", {})
    rearm = decl.get("rearm", {})
    # EACH ENTRY NAMES ITS REF AND ITS CPU: every declaration here was made on the main cpu, the
    # one visible after a start, and an expr watch has none (the console evaluates it there).
    rearmed, evaluated = rearm_pairs(rearm, "rearmed"), rearm_pairs(rearm, "evaluated")
    cell(C1[0], ("exception_handler", ":maincpu") in rearmed, str(rearm))
    cell(C1[1], ("0x4a0", ":maincpu") in rearmed, str(rearmed))
    cell(C1[2], ("main_ram", ":maincpu") in rearmed, str(rearmed))
    cell(C1[3], ("0x2031fc", ":maincpu") in rearmed, str(rearmed))
    cell(C1[4], {("0x203200", ":maincpu"), ("beamy", None)} <= set(evaluated), str(evaluated))
    cell(C1[5], not any(rearm.get(k) for k in ("stale", "unresolved", "unarmable")), str(rearm))
    cell(C1[6], decl.get("held") == 6, f"held={decl.get('held')}")
    bps = call("declaration_list", kind="breakpoint").get("breakpoints", [])
    cell(C1[7], len(bps) == 2 and all(b.get("inherited") is True for b in bps),
         str([(b.get("ref"), b.get("inherited")) for b in bps]))
    ws = call("declaration_list", kind="watch").get("watches", [])
    cell(C1[8], len(ws) == 4 and all(w.get("inherited") is True for w in ws),
         str([(w.get("ref"), w.get("inherited")) for w in ws]))
    row4a0 = by_ref(bps).get("0x4a0", {})
    cell(C1[9], row4a0.get("state") == "armed" and row4a0.get("role") == "control", str(row4a0))
    # m68k-dual's vblank handler starts writing this counter only once the boot has settled, a
    # few frames in: sixty frames are past that, so a zero here would be the tally's, not the
    # game's.
    r = call("run_for", frames=60, seconds=10.0, disarm_watches=True)
    tally = by_ref(r.get("watches")).get("0x2031fc", {})
    cell(C1[10], tally.get("state") == "tallied" and tally.get("total", 0) > 0,
         f"{r.get('verdict')} {tally}"[:160])
    call("breakpoint_at", ref="vec_trapv")
    bps = by_ref(call("declaration_list", kind="breakpoint").get("breakpoints"))
    cell(C1[11], bps.get("vec_trapv", {}).get("inherited") is False,
         str(bps.get("vec_trapv")))
    call("declaration_clear", kind="breakpoint", ref="vec_trapv")
    typed = "d0==irq_vblank"
    r = call("breakpoint_at", ref="vec_trapv", condition=typed)
    (rows,) = json.loads(Path(str(decl.get("path"))).read_text()).values()
    kept = by_ref(rows).get("vec_trapv", {}).get("condition")
    cell(C1[12], kept == typed and r.get("condition_typed") == typed
         and r.get("condition") == f"d0=={STATE.resolve('irq_vblank'):#x}",
         f"stored {kept!r}, replied {r.get('condition')!r} / {r.get('condition_typed')!r}")
    call("declaration_clear", kind="breakpoint", ref="vec_trapv")
    call("close")
    # ANOTHER BUILD: the same file under the same key, one symbol more, so another fingerprint.
    table.write_text(table.read_text() + "  - addr: 0x00000500\n    name: c1_extra\n")
    r = boot(symbols=str(table))
    rearm = r.get("declarations", {}).get("rearm", {})
    cell(C1[13], ("0x4a0", ":maincpu") in rearm_pairs(rearm, "stale")
         and ("0x4a0", ":maincpu") not in rearm_pairs(rearm, "rearmed"),
         str(rearm))
    cell(C1[14], {("exception_handler", ":maincpu"), ("main_ram", ":maincpu")}
         <= set(rearm_pairs(rearm, "rearmed")),
         str(rearm))
    row4a0 = by_ref(call("declaration_list", kind="breakpoint").get("breakpoints")).get("0x4a0", {})
    cell(C1[15], row4a0.get("state") == "stale", str(row4a0))
    r = call("breakpoint_at", ref="0x4a0", role="control")
    row4a0 = by_ref(call("declaration_list", kind="breakpoint").get("breakpoints")).get("0x4a0", {})
    cell(C1[16], ok(r) and r.get("armed") is True and row4a0.get("state") == "armed",
         f"{said(r)} / {row4a0.get('state')}")


C2_WATCHES = ("0x203200", "0x2031fc", "0x20351c", "beamy", "[main_ram]")
C2 = [
    "state_write load's survey carries every declared watch",
    "a show watch after state_write load reads the restored bytes",
    "the change watch is listed armed after state_write load",
    "the change watch still fires after state_write load",
    "the count watch after state_write load is in a documented state (contract silent)",
    "the expr watch evaluates after state_write load",
    "the pointer watch re-resolves after state_write load",
    "declaration_list watch after state_write load lists all five in a documented state",
]
WATCH_STATES = {"evaluated", "armed", "disabled", "gone", "stale", "unresolved", "tallied",
                "no_dump_yet", "install_failed", "not_installed", "null_pointer", "pending",
                "install_lost"}


@section("C", "2. watches across state_write load", C2)
def c2_watches_across_load() -> None:
    boot()
    call("watch_add", ref="0x203200", mode="show", length=2)
    call("watch_add", ref="0x2031fc", mode="change", length=4)
    call("watch_add", ref="0x20351c", mode="count", length=1)
    call("watch_add", ref="beamy", mode="expr")
    call("watch_add", ref="[main_ram]", mode="show", length=4)
    call("run_for", frames=2, seconds=10.0, disarm_watches=True)
    before = by_ref(call("declaration_list", kind="watch").get("watches")).get("0x203200",
                                                                               {}).get("reading",
                                                                                       {}).get(
        "value")
    call("state_write", method="save", name="c2")
    call("run_for", frames=10, seconds=10.0, disarm_watches=True)
    r = call("state_write", method="load", name="c2")
    seen = by_ref(r.get("watches"))
    cell(C2[0], set(C2_WATCHES) <= set(seen), f"{said(r)}; {sorted(seen)}")
    after = seen.get("0x203200", {}).get("reading", {}).get("value")
    cell(C2[1], after == before, f"saved {before}, after load {after}")
    listed = by_ref(call("declaration_list", kind="watch").get("watches"))
    cell(C2[2], listed.get("0x2031fc", {}).get("state") == "armed", str(listed.get("0x2031fc")))
    hit = call("resume", seconds=5.0)
    cell(C2[3], hit.get("verdict") == "OTHER_STOP"
         and str(hit.get("cause", "")).startswith("watch 0x2031fc"), said(hit))
    if hit.get("verdict") != "OTHER_STOP":
        call("stop")
    cell(C2[4], listed.get("0x20351c", {}).get("state") in WATCH_STATES,
         str(listed.get("0x20351c"))[:140])
    cell(C2[5], isinstance(seen.get("beamy", {}).get("reading", {}).get("value"), int),
         str(seen.get("beamy")))
    ptr = seen.get("[main_ram]", {})
    cell(C2[6], ptr.get("state") in ("evaluated", "null_pointer") and "pointer" in ptr
         or ptr.get("state") == "null_pointer", str(ptr)[:140])
    cell(C2[7], set(listed) == set(C2_WATCHES)
         and all(w.get("state") in WATCH_STATES for w in listed.values()),
         str({k: w.get("state") for k, w in listed.items()}))


C3_TRIO = ("thread_errors", "console_reruns", "resent")
C3_CARRY = ("lua", "input", "record", "audio_record", "screen_signature", "read_block")
C3_BARE = ("throttle", "state_write save", "state_write load")
C3 = [
    "the console sequence numbers of the calls strictly increase",
    "a console command evaluated the stopped throttle's line before lua's own",
    "a console command on a stopped machine evaluates the Lua line ahead",
    "the stopped throttle's mark landed: throttles_pending is empty",
    "no throttle is recorded as not applied",
    "session.console agrees with the kept log",
    *[f"the per-call trio rides on {t}" for t in C3_CARRY],
    *[f"the per-call trio is absent from {t}" for t in C3_BARE],
]


def _pending_after(deadline_s: float) -> int:
    """The lines still ahead in the Lua console's pipe, read off the process log (a file read,
    which sends the stub nothing) until none is or `deadline_s` passes: the console's reader is a
    thread, so one read can land while it is still taking a line."""
    scratch = STATE.scratch
    assert scratch is not None
    end = time.monotonic() + deadline_s
    while (left := transport.pending_lines(scratch)) and time.monotonic() < end:
        time.sleep(0.2)
    return left


@section("C", "3. the Lua console's shared sequence", C3)
def c3_console_sequence() -> None:
    boot()
    replies = {
        "throttle": call("throttle", on=False),
        "lua": call("lua", script="print(2)", read_only=True),
        "input": call("input", port=":P1", field="Coin 1", frames=1, seconds=10.0),
        "record": call("record", frames=2, seconds=10.0),
        "audio_record": call("audio_record", frames=2, seconds=10.0),
        "screen_signature": call("screen_signature"),
        "read_block": call("read_block", tag="maincpu", length=4),
        "state_write save": call("state_write", method="save", name="c3"),
    }
    replies["state_write load"] = call("state_write", method="load", name="c3")
    numbered = [(t, n) for t, r in replies.items() if (n := seq_of(r)) is not None]
    nums = [n for _, n in numbered]
    cell(C3[0], len(nums) >= 4 and all(a < b for a, b in zip(nums, nums[1:], strict=False)),
         str(numbered))
    st_ = call("status")
    log = Path(str(st_.get("stdout_path", "")))
    cell(C3[1], console_ran_the_throttle_first(replies["lua"], replies["throttle"],
                                               log.read_bytes() if log.is_file() else b""),
         f"lines_ahead={replies['lua'].get('lines_ahead')}, ends in order: "
         f"{sentinel_order(log.read_bytes()) if log.is_file() else 'no log'}")
    cell(C3[3], "throttles_pending" not in st_, str(st_.get("throttles_pending")))
    cell(C3[4], "throttles_not_applied" not in st_.get("session", {}),
         str(st_.get("session", {}).get("throttles_not_applied")))
    # THE MECHANISM ITSELF, with nothing but one debugger command between the line and the read,
    # after the status above has judged the first throttle's mark.
    call("throttle", on=False)
    ahead = _pending_after(0.0)
    call("debug", command="print 0")
    after = _pending_after(3.0)
    cell(C3[2], ahead == 1 and after == 0,
         f"ahead after the throttle: {ahead}; after `print 0`: {after}")
    # THE SERVER PROMISES TO COUNT what the console did, not that its reader never dies: a
    # reader's death is MAME's, and on some hosts it is common. So the counts are held against
    # the process log, read by the cell's own rule, and only a disagreement fails. They are
    # `close`'s: before it, the counts hold only what the lua-family calls read back, and a
    # death after the last of them is on the log and in nobody's count yet.
    stdout = log.read_bytes() if log.is_file() else b""
    console = call("close").get("session", {}).get("console", {})
    if not console or console_in_log(stdout)["sentinels"] == 0:
        blocked(C3[5], f"nothing to compare: console={console}, sentinels in {log}: none")
    else:
        off = console_disagreement(stdout, console)
        cell(C3[5], not off, f"{console}; the log, where it differs: {off}")
    for t in C3_CARRY:
        r = replies[t]
        # `resent` is left out at zero (omit-empty); the two counts always ride.
        cell(f"the per-call trio rides on {t}", all(k in r for k in C3_TRIO[:2])
             and r.get("resent", 1) != 0,
             str({k: r.get(k) for k in C3_TRIO}))
    for t in C3_BARE:
        r = replies[t]
        cell(f"the per-call trio is absent from {t}", ok(r) and not any(k in r for k in C3_TRIO),
             said(r))


#: (door, the calls that open it, whether it must mark the session). From each tool's own
#: docstring: `write`, `set_register`, `reset` and `state_write(method="load")` MODIFY; `debug`
#: counts a mutating
#: command and a bare assignment and not its bookkeeping; raw `lua` alters unless declared
#: read-only; reads, saves and advances do not.
C4_DOORS: list[tuple[str, list[tuple[str, dict[str, Any]]], bool | None]] = [
    ("write", [("write", {"ref": "0x200000", "data_hex": "00"})], True),
    ("set_register", [("set_register", {"name": "D1", "value": 1})], True),
    ("debug with a fill", [("debug", {"command": "fill 0x200000,2,0x12,0x34"})], True),
    ("debug with a bare assignment", [("debug", {"command": "d0=1234"})], True),
    ("debug with a comparison", [("debug", {"command": "print {d0==1234}"})], False),
    ("debug reading", [("debug", {"command": "dasm /dev/null,0x400,1"})], False),
    ("debug bookkeeping", [("debug", {"command": "bpset 0x25a4"}),
                           ("debug", {"command": "bpclear"})], False),
    ("debug bplist", [("debug", {"command": "bplist"})], False),
    ("debug save", [("debug", {"command": "save {dest},0,10"})], False),
    ("perform carrying a write", [("perform", {"steps": [
        {"op": "write", "ref": "0x200000", "data_hex": "00"}], "settle_seconds": 2.0})], True),
    ("perform carrying a read", [("perform", {"steps": [
        {"op": "read_memory", "ref": "0x400"}], "settle_seconds": 2.0})], False),
    ("drive carrying a write", [("drive", {"act": [
        {"op": "write", "ref": "0x200000", "data_hex": "00"}], "settle_seconds": 2.0})], True),
    ("lua by default", [("lua", {"script": "print(1)"})], True),
    ("lua declared read_only", [("lua", {"script": "print(1)", "read_only": True})], False),
    ("read_block", [("read_block", {"tag": "maincpu", "length": 4})], False),
    ("screen_signature", [("screen_signature", {})], False),
    ("state_write save", [("state_write", {"method": "save", "name": "c4"})], False),
    ("run_for", [("run_for", {"frames": 1, "seconds": 10.0})], False),
    ("step", [("step", {})], False),
    ("reset", [("reset", {})], True),
    ("state_write load", [("state_write", {"method": "load", "name": "c4"})], True),
    ("input (contract silent)", [("input", {"port": ":P1", "field": "Coin 1", "frames": 1,
                                            "seconds": 10.0})], None),
]


def _c4(door: str, alters: bool | None) -> str:
    verb = {True: "marks", False: "does not mark", None: "is counted as it is"}[alters]
    return f"{door} {verb} the session"


C4 = ["a fresh session is not altered"] + [_c4(d, a) for d, _, a in C4_DOORS] + [
    "a read_only lua call is recorded as the caller's word"]


@section("C", "4. altered through every door", C4)
def c4_altered() -> None:
    r = boot()
    cell(C4[0], r.get("session", {}).get("altered") is False and writes(r) == 0,
         str(r.get("session")))
    for door, calls, alters in C4_DOORS:
        w0 = writes(call("status"))
        r = {}
        for tool, kw in calls:
            kw = {k: (v.format(dest=fresh(".bin")) if isinstance(v, str) and "{dest}" in v
                      else v) for k, v in kw.items()}
            r = call(tool, **kw)
        w1 = writes(call("status"))
        moved = w1 > w0
        good = whole(r) and (alters is None or moved is alters)
        if alters:
            good = good and r["session"].get("altered") is True
        cell(_c4(door, alters), good, f"writes {w0} -> {w1}: {said(r, 80)}")
    ses = call("status").get("session", {})
    cell(C4[-1], ses.get("read_only_claims", 0) >= 1 and "caller" in str(ses.get("note")),
         f"claims={ses.get('read_only_claims')}")


C5 = [
    "run_to with the control named in the call reaches its target",
    "run_to with a control declared by breakpoint_at reaches its target",
    "run_to with a condition stops when it holds",
    "and the word reads the value the condition named",
    "run_to with a HOT control and a target that never runs is a TIMEOUT that counted",
    "and a TIMEOUT leaves the machine stopped",
    "run_to with a COLD control is control_silent with the listing and a hint",
    "run_to at a ref holding a stop declaration is refused",
    "run_for by frames with a debug breakpoint on the vblank ends OTHER_STOP",
    "run_for by milliseconds with the same breakpoint ends OTHER_STOP",
    "run_for by frames stops at the first hit of a breakpoint typed through debug, naming it",
    "and with that row cleared the same run reaches its bound",
    "step over runs one instruction through the console",
    "step into three instructions completes three",
    "without disarm_watches a change watch cuts run_to",
    "with disarm_watches run_to reaches its target and names the watch",
    "and the watch is armed again after the run",
]


@section("C", "5. advancing with stops declared", C5)
def c5_advancing() -> None:
    boot()
    r = call("run_to", ref="irq_vblank", control="0x4a0", seconds=10.0)
    cell(C5[0], r.get("verdict") == "TARGET" and "0x4a0" in str(r.get("controls")), said(r))
    call("declaration_clear", kind="breakpoint", all=True)
    call("breakpoint_at", ref="irq_vblank", role="control")
    r = call("run_to", ref="0x4a0", seconds=10.0)
    cell(C5[1], r.get("verdict") == "TARGET", said(r))
    # The vblank handler adds one to the long at 0x2031fc every frame once the boot settles
    # (read off the machine, frame by frame), so a value three frames ahead is a condition that
    # holds within the bound.
    n = int(call("read_memory", ref="0x2031fc", length=4).get("hex", "0"), 16)
    cond = f"d@0x2031fc=={n + 3:#x}"
    r = call("run_to", ref="0x4a0", seconds=10.0, condition=cond)
    cell(C5[2], r.get("verdict") == "TARGET" and r.get("condition") == cond, said(r))
    after = int(call("read_memory", ref="0x2031fc", length=4).get("hex", "0"), 16)
    cell(C5[3], after == n + 3, f"{n} -> {after}")
    r = call("run_to", ref="exception_handler", seconds=3.0)
    cell(C5[4], r.get("verdict") == "TIMEOUT" and r.get("control_hits", 0) > 0,
         f"{said(r)} hits={r.get('control_hits')}")
    st_ = call("status")
    cell(C5[5], st_.get("session", {}).get("running") is False, said(st_))
    call("declaration_clear", kind="breakpoint", all=True)
    r = call("run_to", ref="exception_handler", control="vec_chk", seconds=3.0)
    cell(C5[6], refused(r, "control_silent") and "verdict" not in r
         and bool(r.get("control_dasm")) and all("dasm" in row for row in r["control_dasm"])
         and "note" in r, said(r))
    call("declaration_clear", kind="breakpoint", all=True)
    call("breakpoint_at", ref="irq_vblank")
    r = call("run_to", ref="irq_vblank", control="0x4a0", seconds=5.0)
    cell(C5[7], refused(r), said(r))
    call("declaration_clear", kind="breakpoint", all=True)
    call("debug", command="bpset 0x400")
    r = call("run_for", frames=5, seconds=10.0)
    cell(C5[8], r.get("verdict") == "OTHER_STOP", said(r))
    r = call("run_for", milliseconds=200, seconds=10.0)
    cell(C5[9], r.get("verdict") == "OTHER_STOP", said(r))
    call("debug", command="bpclear")
    # THE VBLANK HANDLER IS HOT EVERY FRAME, so a row there is hit well inside the bound: the
    # run ends at that hit, not absorbed into the frames. `polls` is the frames run, plus the
    # landing on the hit when it came before the tick, plus the aligning `gvblank` a
    # mid-frame stop spends first.
    call("debug", command="bpset 4a0")
    r = call("run_for", frames=60, seconds=10.0)
    ran = int(r.get("frame_after", 0)) - int(r.get("frame_before", 0))
    polls = int(r.get("polls", -1))
    cell(C5[10], r.get("verdict") == "OTHER_STOP" and int(str(r.get("pc", "0")), 16) == 0x4A0
         and "typed through `debug`" in str(r.get("cause")) and polls - ran in (0, 1, 2),
         f"{r.get('verdict')} pc={r.get('pc')} polls={polls} ran={ran} how={r.get('cause')}")
    call("debug", command="bpclear")
    r = call("run_for", frames=60, seconds=10.0)
    ran = int(r.get("frame_after", 0)) - int(r.get("frame_before", 0))
    cell(C5[11], r.get("verdict") == "ELAPSED" and ran == 60, f"ran={ran}: {said(r)}")
    pc0 = call("registers").get("regs", {}).get("PC")
    r = call("step", count=1, mode="over")
    cell(C5[12],
         r.get("mode") == "over" and r.get("instructions_completed") == 1 and r.get("pc") != pc0,
         f"{pc0} -> {r.get('pc')}: {said(r)}")
    r = call("step", count=3, mode="into")
    cell(C5[13], r.get("instructions_completed") == 3 and "regs" in r, said(r))
    call("breakpoint_at", ref="irq_vblank", role="control")
    call("watch_add", ref="0x2031fc", mode="change", length=4)
    # From the handler's second instruction, BEFORE its write to the watched long at 0x40e:
    # from anywhere past it the target comes first and the watch has nothing to cut.
    call("run_to", ref="0x404", seconds=5.0, disarm_watches=True)
    r = call("run_to", ref="0x4a0", seconds=5.0)
    cell(C5[14], r.get("verdict") == "OTHER_STOP" or refused(r, "cut_by_other_stop"), said(r))
    r = call("run_to", ref="0x4a0", seconds=5.0, disarm_watches=True)
    cell(C5[15], r.get("verdict") == "TARGET" and "0x2031fc" in str(r.get("disarmed_watches")),
         f"{said(r)} disarmed={r.get('disarmed_watches')}")
    w = by_ref(call("declaration_list", kind="watch").get("watches")).get("0x2031fc", {})
    cell(C5[16], w.get("state") == "armed", str(w)[:120])


#: The readers the server's `instructions` name as refusing on a running machine.
RUNNING_READERS = ("registers", "read_memory", "disassemble", "find", "history", "memdump",
                   "debug", "step", "run_to", "run_for", "write", "set_register", "reset",
                   "rom_check", "lua", "read_block", "input", "record", "audio_record",
                   "state_write save", "state_write load", "trace")
C6 = [
    "every reader the instructions name refuses not_stopped while it runs",
    "log answers while it runs",
    "log_wait answers while it runs",
    "throttle applies at once while it runs, with the frame",
    "registers(from_last_stop=True) answers superseded with as_of while it runs",
    "a breakpoint armed while it runs stops it, found by the first contact",
    "the readers answer again at that stop",
    "stop interrupts a run and surveys it",
    "and the readers answer after it",
]


@section("C", "6. the running machine", C6)
def c6_running() -> None:
    boot()
    call("resume")
    bad = [t for t in RUNNING_READERS if not refused(call(t, **PROBES[t]()), "not_stopped")]
    cell(C6[0], not bad, f"answered: {bad}")
    cell(C6[1], ok(call("log", pattern=".", channel="emulator", limit=3)), said(PENDING[-1]
                                                                                ["reply"]))
    r = call("log_wait", pattern=".", channel="emulator", seconds=5.0)
    cell(C6[2], ok(r) and "line" in r, said(r))
    r = call("throttle", on=False, seconds=5.0)
    cell(C6[3], ok(r) and r.get("pending") is False and isinstance(r.get("frame"), int), said(r))
    r = call("registers", from_last_stop=True)
    cell(C6[4], ok(r) and r.get("superseded") is True and "last_stop" in r, said(r))
    call("breakpoint_at", ref="irq_vblank")
    time.sleep(0.3)
    r = call("status")
    cell(C6[5], r.get("session", {}).get("running") is False and "stopped_on_its_own" in r, said(r))
    r = call("registers")
    cell(C6[6], ok(r), said(r))
    call("declaration_clear", kind="breakpoint", all=True)
    call("resume")
    r = call("stop")
    cell(C6[7], r.get("interrupted") is True and "regs" in r, said(r))
    r = call("disassemble", ref="0x400", length=4)
    cell(C6[8], ok(r), said(r))


C7_MODES = ("show", "count", "expr", "pointer")
C7_ADVANCES = ("run_for", "run_to", "step")
C7_RAISED = ("a count watch whose tap raises counts each error beside its total, never an empty "
             "census")
C7_DUMPER = ("a count watch whose dumper raises after its open logs MCP_DUMP_FAILED once, "
             "closes its .tmp, and the superseded dump's why names the error")
C7 = [f"a {m} watch under {a}" for m in C7_MODES for a in C7_ADVANCES] + [
    C7_RAISED,
    C7_DUMPER,
    "a change watch cuts run_for, naming its writer",
    "a change watch cuts run_to",
    "a change watch rides a step's survey, evaluated",
]
C7_REF = {"show": "0x203200", "count": "0x20351c", "expr": "beamy", "pointer": "[main_ram]"}


def _c7_judge(mode: str, w: dict[str, Any], stop: dict[str, Any]) -> bool:
    reading = w.get("reading", {})
    if mode == "show":
        return (w.get("state") == "evaluated" and reading.get("available") is True
                and "value" in reading and "raw_hex" in reading)
    if mode == "count":
        # A STOP'S ROW OF A TAP is its count as of this stop: `superseded` rides only when the
        # dump on disk is older than the stop (its frame is `declaration_list(kind="watch")`'s).
        return (w.get("state") == "tallied" and isinstance(w.get("total"), int)
                and "superseded" not in w)
    if mode == "expr":
        return isinstance(reading.get("value"), int) and "hex" in reading
    return w.get("state") in ("evaluated", "null_pointer")


@section("C", "7. watch modes x advances", C7)
def c7_watch_modes() -> None:
    boot()
    call("watch_add", ref="0x203200", mode="show", length=2)
    call("watch_add", ref="0x20351c", mode="count", length=1)
    call("watch_add", ref="beamy", mode="expr")
    call("watch_add", ref="[main_ram]", mode="show", length=4)
    advances: dict[str, Callable[[], dict[str, Any]]] = {
        "run_for": lambda: call("run_for", frames=2, seconds=10.0),
        "run_to": lambda: call("run_to", ref="irq_vblank", control="0x4a0", seconds=10.0),
        "step": lambda: call("step"),
    }
    for adv in C7_ADVANCES:
        stop = advances[adv]()
        seen = by_ref(stop.get("watches"))
        for mode in C7_MODES:
            w = seen.get(C7_REF[mode], {})
            cell(f"a {mode} watch under {adv}", _c7_judge(mode, w, stop),
                 f"{said(stop, 50)}: {str(w)[:110]}")
    call("declaration_clear", kind="watch", all=True)
    call("declaration_clear", kind="breakpoint", all=True)
    call("breakpoint_at", ref="irq_vblank", role="control")
    call("watch_add", ref="0x2031fc", mode="change", length=4)
    r = call("run_for", frames=2, seconds=10.0)
    cell(C7[-3], r.get("verdict") == "OTHER_STOP"
         and r.get("watch_hit", {}).get("writer_pc") is not None, said(r))
    r = call("run_to", ref="0x4a0", seconds=5.0)
    cell(C7[-2], r.get("verdict") == "OTHER_STOP" or refused(r, "cut_by_other_stop"), said(r))
    r = call("step")
    w = by_ref(r.get("watches")).get("0x2031fc", {})
    # The survey carries EVERY declared watch evaluated: a change watch rides it placed
    # `armed` and read, with its bytes now, whether or not this step wrote them.
    reading = w.get("reading", {})
    cell(C7[-1], w.get("state") == "armed" and "value" in reading and "raw_hex" in reading
         or "watch_hit" in r, f"{said(r, 50)}: {w}"[:150])
    call("declaration_clear", kind="watch", all=True)
    call("declaration_clear", kind="breakpoint", all=True)
    # the blitter's strobe, written many times a frame: every write after the plant raises
    tap = call("watch_add", ref=BLIT_TRIGGER, mode="count", length=2)
    call("run_for", frames=2, seconds=10.0)
    at = planted_at(plant_fault("MCP_TALLY", str(tap.get("tally_id")), (
        f'setmetatable(t.values, {{__index = function() error("{FAULT}") end}})\n'
        "for k in pairs(t.values) do t.values[k] = nil end"), "t.total"))
    call("run_for", frames=10, seconds=10.0)
    w = by_ref(call("declaration_list", kind="watch").get("watches")).get(BLIT_TRIGGER, {})
    count, first = raised(w)
    total = int(w.get("total", -1))
    cell(C7_RAISED, at >= 0 and total > at and count == total - at and FAULT in first,
         f"total {at} -> {total}, errors {count}, first {first[:70]!r}")
    call("declaration_clear", kind="watch", all=True)
    tap = call("watch_add", ref=BLIT_TRIGGER, mode="count", length=2)
    call("run_for", frames=2, seconds=10.0)
    scratch = Path(str(call("status").get("scratch_dir")))
    dumper_fault_cell(C7_DUMPER, "MCP_TALLY", str(tap.get("tally_id")), BLIT_TRIGGER,
                      scratch / f"tally-{tap.get('tally_id')}.txt")
    call("declaration_clear", kind="watch", all=True)


C8 = [
    "captures lists the AVI record wrote, with its frames",
    "captures lists both PNGs snapshot wrote, present",
    "captures does not list what memdump wrote",
    "screen_signature writes no capture",
    "snapshot's sha256 is the file's own",
    "a PNG removed since is listed present false",
    "captures lists the WAV audio_record wrote, with its samples",
]


@section("C", "8. captures", C8)
def c8_captures() -> None:
    boot()
    avi, png = fresh(".avi"), fresh(".png")
    call("record", frames=3, dest=avi, seconds=10.0)
    wav = fresh(".wav")
    sound = call("audio_record", frames=3, dest=wav, seconds=10.0)
    shot = call("snapshot", dest=png)
    call("snapshot")
    dump = fresh(".bin")
    call("memdump", ref="0x0", length=16, dest=dump)
    caps = call("captures").get("captures", [])
    avis = [c for c in caps if c.get("kind") == "avi"]
    cell(C8[0], len(avis) == 1 and avis[0].get("avi_frames") == 3 and avis[0].get("present") is True
         and avis[0].get("path") == avi, str(avis)[:150])
    pngs = [c for c in caps if c.get("kind") == "png"]
    cell(C8[1], len(pngs) == 2 and all(c.get("present") and c.get("bytes", 0) > 0 for c in pngs),
         str(pngs)[:150])
    cell(C8[2], all(c.get("path") != dump for c in caps), str([c.get("path") for c in caps]))
    call("screen_signature")
    cell(C8[3], len(call("captures").get("captures", [])) == len(caps), said(PENDING[-1]["reply"]))
    digest = hashlib.sha256(Path(png).read_bytes()).hexdigest()
    cell(C8[4], shot.get("sha256") == digest, f"{shot.get('sha256')} vs {digest}")
    Path(png).unlink()
    gone = [c for c in call("captures").get("captures", []) if c.get("path") == png]
    cell(C8[5], len(gone) == 1 and gone[0].get("present") is False, str(gone))
    wavs = [c for c in caps if c.get("kind") == "wav"]
    cell(C8[6], len(wavs) == 1 and wavs[0].get("path") == wav and wavs[0].get("present") is True
         and (wavs[0].get("samples") or 0) > 0 and wavs[0].get("samples") == sound.get("samples"),
         str(wavs)[:150])


C9 = [
    "reset answers softreset, verified, with the stop survey",
    "the stop breakpoint and the control are still listed armed",
    "the change watch is still listed armed",
    "the show watch still reads at the reset's stop",
    "the control still counts after the reset",
    "the tally still reports after the reset (contract silent on the total)",
    "the session is altered after the reset",
]


@section("C", "9. reset with declarations armed", C9)
def c9_reset() -> None:
    boot()
    call("breakpoint_at", ref="vec_trapv")
    call("breakpoint_at", ref="irq_vblank", role="control")
    call("watch_add", ref="0x2031fc", mode="change", length=4)
    call("watch_add", ref="0x20351c", mode="count", length=1)
    call("watch_add", ref="0x203200", mode="show", length=2)
    before = call("run_for", frames=10, seconds=10.0, disarm_watches=True)
    t0 = by_ref(before.get("watches")).get("0x20351c", {}).get("total")
    r = call("reset")
    cell(C9[0], ok(r) and r.get("kind") == "softreset" and r.get("verified") is True
         and "regs" in r, said(r))
    bps = by_ref(call("declaration_list", kind="breakpoint").get("breakpoints"))
    cell(C9[1], [bps.get(k, {}).get("state") for k in ("vec_trapv", "irq_vblank")]
         == ["armed", "armed"], str({k: b.get("state") for k, b in bps.items()}))
    w = by_ref(call("declaration_list", kind="watch").get("watches")).get("0x2031fc", {})
    cell(C9[2], w.get("state") == "armed", str(w)[:120])
    rw = by_ref(r.get("watches")).get("0x203200", {})
    cell(C9[3], rw.get("state") == "evaluated" and rw.get("reading", {}).get("available") is True,
         str(rw))
    r = call("run_to", ref="exception_handler", seconds=3.0, disarm_watches=True)
    cell(C9[4], r.get("verdict") == "TIMEOUT" and r.get("control_hits", 0) > 0, said(r))
    r = call("run_for", frames=5, seconds=10.0, disarm_watches=True)
    t = by_ref(r.get("watches")).get("0x20351c", {})
    cell(C9[5], t.get("state") == "tallied" and isinstance(t.get("total"), int),
         f"total {t0} before the reset, {t.get('total')} after")
    cell(C9[6], r.get("session", {}).get("altered") is True, str(r.get("session")))


def _media_files() -> dict[str, str]:
    """Files whose answers are known, for the media file tools in a batch, which cannot read a
    path an earlier step returns: a series of two different 2x2 frames with its goldens, and a
    one-second WAV of a tone."""
    folder = Path(fresh("-series"))
    folder.mkdir()
    for frame, level in ((0, 0), (1, 255)):
        (folder / series.frame_name(frame)).write_bytes(
            png.encode(png.Raster(2, 2, bytes([level]) * 12)))
    manifest = series.write_manifest(folder, "mame", "frame_number", None, [0, 1])["manifest"]
    sums = folder / "goldens.sha256"
    sums.write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                            for p in sorted(folder.glob("f*.png"))))
    tone = fresh(".wav")
    with wave.open(tone, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", round(8000 * math.sin(i / 4)))
                               for i in range(8000)))
    return {"png": str(folder / series.frame_name(0)), "manifest": str(manifest),
            "sums": str(sums), "wav": tone}


def _every_op_once(state: str, frame_now: int) -> list[dict[str, Any]]:
    """A batch holding every operation `perform` accepts, in an order the machine can take: the
    series first, its frames just ahead of `frame_now` (where the machine stands before the
    batch, which nothing has advanced yet), the console ops stopped, then `resume`, the
    running-ok ops, and `stop`."""
    tsv = fresh(".tsv")
    media = _media_files()
    maps = Path(fresh("-maps"))
    maps.mkdir()
    screen_map = str(maps / "batch.scry-map.json")
    return [
        {"op": "series_capture", "first": frame_now + 1, "last": frame_now + 2,
         "seconds": 10.0},
        {"op": "status"}, {"op": "machine_map"}, {"op": "cpu_info"},
        {"op": "symbols_find", "name": "irq_vblank"},
        {"op": "read_memory", "ref": "0x400", "length": 4},
        {"op": "read_block", "tag": "maincpu", "length": 4}, {"op": "registers"},
        {"op": "disassemble", "ref": "0x400", "length": 4},
        {"op": "find", "ref": "0x0", "length": 64, "data_hex": "00"},
        {"op": "history", "limit": 2}, {"op": "focus", "cpu": "maincpu"},
        {"op": "log", "pattern": ".", "channel": "emulator", "limit": 2},
        {"op": "snapshot"}, {"op": "captures"}, {"op": "state_list"},
        {"op": "breakpoint_at", "ref": "exception_handler"}, {"op": "declaration_list",
                                                              "kind": "breakpoint"},
        {"op": "declaration_clear", "kind": "breakpoint", "all": True}, {"op": "watch_add",
                                                                         "ref": "0x203200",
                                                  "mode": "show",
                                     "length": 2},
        {"op": "declaration_list", "kind": "watch"}, {"op": "declaration_clear", "kind": "watch",
                                                      "all": True},
        {"op": "regpoint_add", "condition": "pc==0xfffffffe"}, {"op": "declaration_list",
                                                                "kind": "regpoint"},
        {"op": "declaration_clear", "kind": "regpoint", "all": True},
        {"op": "comment_write", "method": "add", "ref": "irq_vblank", "text": "batch"},
            {"op": "comment_list"},
        {"op": "comment_write", "method": "save", "dest": tsv}, {"op": "comment_write",
                                                                 "method": "load", "path": tsv},
        {"op": "comment_write", "method": "delete", "ref": "irq_vblank"},
        {"op": "debug", "command": "print pc"},
        {"op": "lua", "script": "print(1)", "read_only": True}, {"op": "screen_signature"},
        {"op": "map_write", "method": "add", "screen": "batch", "match": [[0, 0, 8, 8]]},
            {"op": "map_find"},
        {"op": "map_write", "method": "save", "dest": screen_map}, {"op": "map_write",
                                                                    "method": "load",
                                                                    "path": screen_map},
        {"op": "palette", "count": 4}, {"op": "screen_view", "mode": "histogram"},
        {"op": "image_compare", "method": "image", "a": media["png"], "b": media["png"]},
        {"op": "image_compare", "method": "series", "a": media["manifest"], "b": media["manifest"]},
        {"op": "image_compare", "method": "region", "manifest": media["manifest"]},
        {"op": "image_compare", "method": "golden", "manifest": media["manifest"],
         "checksums": media["sums"]},
        {"op": "audio_compare", "method": "measure", "path": media["wav"]},
        {"op": "audio_compare", "method": "diff", "a": media["wav"], "b": media["wav"]},
        {"op": "gfx_view", "layout": BYTES_8X8, "palette": "none", "tag": "maincpu", "count": 4},
        {"op": "gfx_locate", "layouts": [BYTES_8X8], "patch": [0, 0, 8, 8], "tag": "maincpu",
         "count": 4},
        {"op": "gfx_sweep", "tag": "maincpu", "planes": [1], "count": 4},
        {"op": "gfx_draft", "dest": fresh(".yaml")},
        {"op": "gfx_load", "path": MANIFEST},
        {"op": "watch_add", "ref": BLITTER, "mode": "capture", "length": 32,
         "trigger": BLIT_TRIGGER},
        {"op": "run_for", "frames": 8, "seconds": 10.0},
        {"op": "gfx_blits", "draw_command": "blit"}, {"op": "gfx_blit_source",
                                                      "draw_command": "blit",
                                                  "index": 0},
        {"op": "palette_log", "palette_port": "ramdac", "arm": True},
        {"op": "palette_log", "palette_port": "ramdac", "clear": True},
        {"op": "gfx_film", **FILM}, {"op": "run_for", "frames": 6, "seconds": 10.0},
        {"op": "gfx_film"}, {"op": "gfx_film", "clear": True},
        {"op": "declaration_clear", "kind": "watch", "all": True},
        {"op": "write", "ref": "0x200000", "data_hex": "00"},
        {"op": "set_register", "name": "D1", "value": 0},
        {"op": "run_to", "ref": "irq_vblank", "control": "0x4a0", "seconds": 10.0},
        {"op": "declaration_clear", "kind": "breakpoint", "all": True}, {"op": "run_for",
                                                                         "frames": 1,
                                                                         "seconds": 10.0},
        {"op": "trace", "frames": 1, "seconds": 10.0},
        {"op": "step"}, {"op": "input", "port": ":P1", "field": "Coin 1", "frames": 1,
                         "seconds": 10.0},
        {"op": "record", "frames": 2, "seconds": 10.0},
        {"op": "audio_record", "frames": 2, "seconds": 10.0},
        {"op": "memdump", "ref": "0x0", "length": 16, "dest": fresh(".bin")},
        {"op": "scan", "method": "start", "ref": "0x200000", "length": 0x100}, {"op": "scan",
                                                                                "method": "filter",
                                                                  "operator": "!"},
        {"op": "scan", "method": "clear"},
        {"op": "state_write", "method": "save", "name": state}, {"op": "state_write",
                                                                 "method": "load", "name": state},
        {"op": "reset"}, {"op": "throttle", "on": False},
        {"op": "resume"}, {"op": "log_wait", "pattern": ".", "channel": "emulator",
                           "seconds": 5.0},
        {"op": "stop"},
    ]


C10 = [
    "the batch covers every operation perform accepts",
    "perform runs a list holding every operation, in one call",
    "one refused step stops the list there, the steps before it ran",
    "a list with two bad steps is refused whole, nothing run, both listed",
    "drive with no expect says the verify was not checked",
    "drive with an expect the act meets says seen",
    "drive with an expect a stopped machine never met is wait_stopped with the act's account",
    "drive with a refused step is step_failed with the act and the look",
]


@section("C", "10. batches", C10)
def c10_batches() -> None:
    boot()
    steps = _every_op_once("c10", int(call("screen_signature").get("frame_screen") or 0))
    ops = {st_["op"] for st_ in steps}
    accepted = set(s._step_ops())
    cell(C10[0], ops == accepted,
         f"missing {sorted(accepted - ops)}, extra {sorted(ops - accepted)}")
    r = call("perform", steps=steps, settle_seconds=5.0, summaries=True)
    cell(C10[1],
         ok(r) and r.get("steps_completed") == len(steps)
         and (r.get("failed_at") or {}).get("available") is False,
         f"{said(r)} completed {r.get('steps_completed')} of {len(steps)} "
         f"({r.get('failed', {}).get('reply', {}).get('message', '')})"[:200])
    r = call("perform", steps=[{"op": "read_memory", "ref": "0x400", "length": 2},
                               {"op": "read_memory", "ref": "nosuchsymbol", "length": 2},
                               {"op": "read_memory", "ref": "0x400",
                                "length": 2}], settle_seconds=2.0)
    cell(C10[2], refused(r, "step_failed") and r.get("failed_at") == 1
         and r.get("steps_completed") == 1 and len(r.get("ran", [])) == 1, said(r))
    r = call("perform", steps=[{"op": "warp_core"}, {"op": "read_memory", "ref": "0x400",
                                                     "length": 0}], settle_seconds=2.0)
    cell(C10[3], refused(r) and r.get("steps_completed") == 0 and r.get("ran") == []
         and len(r.get("errors", [])) == 2, f"{said(r)} errors={r.get('errors')}"[:200])
    r = call("drive", act=[{"op": "run_for", "frames": 1, "seconds": 10.0}], settle_seconds=2.0)
    cell(C10[4], ok(r) and r.get("verify", {}).get("checked") is False, said(r))
    r = call("drive", **SEEN_ACT)
    cell(C10[5], ok(r) and r.get("verify", {}).get("seen") is True, said(r))
    r = call("drive", act=[{"op": "run_for", "frames": 1, "seconds": 10.0}],
             expect="no line ever says this", seconds=1.0, settle_seconds=2.0)
    cell(C10[6], refused(r, "wait_stopped") and r.get("act", {}).get("steps_completed") == 1,
         said(r))
    r = call("drive", act=[{"op": "read_memory", "ref": "nosuchsymbol"}], settle_seconds=2.0)
    cell(C10[7], refused(r, "step_failed") and "act" in r and "looked" in r, said(r))


C12_BARE = [
    "with no symbol file symbols_find is no_channel",
    "with no symbol file symbol_coverage is an empty list",
    "with no symbol file read_memory by name is refused, by 0x answered",
    "with no symbol file disassemble by name is refused",
    "with no symbol file run_to by name is refused",
    "with no symbol file breakpoint_at by name is kept unresolved, not refused",
    "with no symbol file watch_add by name is kept unresolved",
    "with no symbol file find by region is refused",
    "with no symbol file memdump by name is refused",
    "with no symbol file read_block by name is refused",
]
C12_TABLE = [
    "read_memory by symbol reads what the hex address holds",
    "disassemble by symbol starts at the table's address",
    "find by symbol finds the bytes at the table's address",
    "memdump by symbol writes what the hex address holds",
    "read_block by symbol names the block and the offset",
    "write by symbol lands at the table's address",
    "symbols_find by linear places an address inside the nearest symbol",
    "breakpoint_at by symbol arms the table's address",
    "watch_add by symbol watches the table's address",
    "run_to by symbol stops at the table's address",
    "a YAML table carries no classes: symbol_coverage is an empty list",
]


@section("C", "12. symbols, with a table and with none", C12_BARE + C12_TABLE)
def c12_symbols() -> None:
    boot(symbols=None)
    b = C12_BARE
    cell(b[0], refused(call("symbols_find", name="irq_vblank"), "no_channel"),
         said(PENDING[-1]["reply"]))
    cell(b[1], call("machine_map").get("symbol_coverage") == [], said(PENDING[-1]["reply"]))
    by_name, by_hex = call("read_memory", ref="irq_vblank"), call("read_memory", ref="0x400")
    cell(b[2], refused(by_name) and ok(by_hex), f"{said(by_name, 60)} / {said(by_hex, 40)}")
    cell(b[3], refused(call("disassemble", ref="irq_vblank")), said(PENDING[-1]["reply"]))
    cell(b[4], refused(call("run_to", ref="irq_vblank", control="0x4a0", seconds=5.0)),
         said(PENDING[-1]["reply"]))
    r = call("breakpoint_at", ref="irq_vblank")
    cell(b[5], ok(r) and r.get("state") == "unresolved", said(r))
    r = call("watch_add", ref="main_ram", mode="change", length=4)
    cell(b[6], ok(r) and r.get("state") == "unresolved", said(r))
    cell(b[7], refused(call("find", data_hex="00", symbol_class="CODE")),
         said(PENDING[-1]["reply"]))
    cell(b[8], refused(call("memdump", ref="irq_vblank", length=4, dest=fresh(".bin"))),
         said(PENDING[-1]["reply"]))
    cell(b[9], refused(call("read_block", ref="irq_vblank")), said(PENDING[-1]["reply"]))
    call("close")
    boot()
    t = C12_TABLE
    sym, hx = call("read_memory", ref="irq_vblank", length=8), call("read_memory", ref="0x400",
                                                                     length=8)
    cell(t[0], ok(sym) and sym.get("hex") == hx.get("hex") and sym.get("addr") == "0x00000400",
         said(sym))
    r = call("disassemble", ref="irq_vblank", length=4)
    cell(t[1], ok(r) and r.get("addr") == "0x00000400", said(r))
    r = call("find", ref="irq_vblank", length=8, data_hex=str(hx.get("hex", ""))[:4])
    cell(t[2], ok(r) and "0x00000400" in [h.lower() for h in r.get("hits", [])]
         or ok(r) and any(int(h, 16) == 0x400 for h in r.get("hits", [])), said(r))
    dest = fresh(".bin")
    r = call("memdump", ref="irq_vblank", length=8, dest=dest)
    cell(t[3], ok(r) and Path(dest).read_bytes().hex() == hx.get("hex"), said(r))
    r = call("read_block", ref="irq_vblank", length=4)
    cell(t[4], ok(r) and r.get("tag") == ":maincpu" and r.get("offset") == 0x400, said(r))
    r = call("write", ref="main_ram", data_hex="00")
    cell(t[5], ok(r) and r.get("addr") == "0x00200000", said(r))
    r = call("symbols_find", linear="0x40e")
    cell(t[6], ok(r) and r.get("name") == "IRQ_VBLANK" and r.get("delta") == 0xE, said(r))
    r = call("breakpoint_at", ref="irq_vblank")
    cell(t[7], ok(r) and r.get("addr") == "0x00000400", said(r))
    call("declaration_clear", kind="breakpoint", all=True)
    r = call("watch_add", ref="main_ram", mode="show", length=4)
    cell(t[8], ok(r) and r.get("addr") == "0x00200000", said(r))
    call("declaration_clear", kind="watch", all=True)
    r = call("run_to", ref="irq_vblank", control="0x4a0", seconds=10.0)
    cell(t[9], r.get("verdict") == "TARGET" and r.get("pc") == "0x00000400", said(r))
    cell(t[10], call("machine_map").get("symbol_coverage") == [], said(PENDING[-1]["reply"]))


C13 = [
    "regpoint_add arms d1==7fff on a fresh start, read back off rplist",
    "declaration_list regpoint shows it armed, with its index and cpu",
    "a resume is cut by it: regpoint_hit, and D1 holds the value",
    "still armed, a run by frames is OTHER_STOP with the hit, never no_progress",
    "and the session is not handed back running",
    "declaration_clear regpoint disarms it, read back",
    "the same run by frames then ELAPSES",
    "a malformed condition (d1==) is bad_argument in the console's words, and stores nothing",
    "a register this cpu lacks (eax==5) is bad_argument: unknown symbol",
    "an action after a comma is bad_argument before the console hears of it",
    "a registerpoint added WHILE RUNNING is armed, fires and is found by the next contact",
    "a second start re-arms the stored registerpoint and says so in rearm",
    "a registerpoint typed through debug is named by index and condition",
    "the same condition typed on the OTHER 68000 is not adopted: the add arms the main cpu's",
    "and the other cpu's row is listed foreign and survives the clear",
]


@section("C", "13. regpoints: declared, fired, cleared, re-armed", C13)
def c13_regpoints() -> None:
    t = C13
    boot()
    cond = "d1==7fff"
    r = call("regpoint_add", condition=cond)
    cell(t[0], ok(r) and r.get("armed") is True and r.get("index") == 1
         and r.get("entry") == f"1 if {cond}" and r.get("cpu") == ":maincpu"
         and r.get("session", {}).get("altered") is False, said(r))
    rows = call("declaration_list", kind="regpoint").get("regpoints", [])
    cell(t[1], [(x.get("ref"), x.get("state"), x.get("cpu")) for x in rows]
         == [(cond, "armed", ":maincpu")] and "index" in rows[0], str(rows)[:150])
    r = call("resume", seconds=5.0)
    hit = r.get("regpoint_hit", {})
    cell(t[2], r.get("verdict") == "OTHER_STOP" and r.get("cause") == f"registerpoint '{cond}'"
         and hit.get("ref") == cond and hit.get("pc") == r.get("pc")
         and r.get("regs", {}).get("D1") == "0x00007fff", said(r))
    r = call("run_for", frames=2, seconds=10.0)
    cell(t[3], r.get("verdict") == "OTHER_STOP" and r.get("regpoint_hit", {}).get("ref") == cond,
         said(r))
    cell(t[4], session_is(r, alive=True, running=False), str(r.get("session")))
    r = call("declaration_clear", kind="regpoint", ref=cond)
    cell(t[5], r.get("declarations_cleared") == 1 and len(r.get("disarmed", [])) == 1
         and call("declaration_list", kind="regpoint").get("regpoints") == [], said(r))
    r = call("run_for", frames=2, seconds=10.0)
    cell(t[6], r.get("verdict") == "ELAPSED", said(r))
    r = call("regpoint_add", condition="d1==")
    cell(t[7], refused(r, "bad_argument") and "stack underflow" in str(r.get("message"))
         and call("declaration_list", kind="regpoint").get("regpoints") == []
         and call("debug", command="rplist").get("output", "").startswith("No registerpoints"),
         said(r))
    r = call("regpoint_add", condition="eax==5")
    cell(t[8], refused(r, "bad_argument") and "unknown symbol" in str(r.get("message")), said(r))
    r = call("regpoint_add", condition="d1==7fff,{g}")
    cell(t[9], refused(r, "bad_argument") and "ACTION" in str(r.get("message")), said(r))
    # WHILE RUNNING: `pc!=0` holds at once, so the machine stops by itself an instruction on.
    call("resume")
    r = call("regpoint_add", condition="pc!=0")
    time.sleep(0.5)
    found = call("status")
    cell(t[10], r.get("armed") is True and r.get("while_running") is True
         and found.get("session", {}).get("running") is False
         and str(found.get("last_stop", {}).get("cause")) == "registerpoint 'pc!=0'",
         f"{said(r)} / {found.get('last_stop')}")
    call("declaration_clear", kind="regpoint", all=True)
    call("regpoint_add", condition=cond)
    call("close")
    r = boot()
    rearm = r.get("declarations", {}).get("rearm", {})
    rows = call("declaration_list", kind="regpoint").get("regpoints", [])
    cell(t[11], rearm_pairs(rearm, "rearmed") == [(cond, ":maincpu")]
         and rearm.get("unarmable") == []
         and [(x.get("state"), x.get("inherited")) for x in rows] == [("armed", True)],
         f"{rearm} / {str(rows)[:100]}")
    call("declaration_clear", kind="regpoint", all=True)
    call("debug", command="rpset {d1==7fff}")
    r = call("resume", seconds=5.0)
    cell(t[12], str(r.get("cause")).startswith("registerpoint ")
         and "(if d1==7fff), typed through `debug`: `debug(\"rpclear " in str(r.get("cause"))
         and "regpoint_hit" not in r, said(r))
    call("debug", command="rpclear")
    # THE BOARD HAS TWO 68000s, and `d1==7fff` on the sub cpu compares another D1.
    call("debug", command="focus subcpu")
    typed = call("debug", command="rpset {d1==7fff}").get("output", "")
    call("debug", command="focus maincpu")
    r = call("regpoint_add", condition=cond)
    rows = call("debug", command="rplist").get("output", "")
    cell(t[13], typed.startswith("Registerpoint ") and r.get("armed") is True
         and r.get("cpu") == ":maincpu" and rows.count(f"if {cond}") == 2
         and "Device ':subcpu' registerpoints:" in rows, f"{said(r)} / {rows!r}")
    listed = call("declaration_list", kind="regpoint")
    call("declaration_clear", kind="regpoint", all=True)
    after = call("debug", command="rplist").get("output", "")
    cell(t[14], len(listed.get("foreign", {}).get("regpoints", [])) == 1
         and "Device ':subcpu'" in after
         and "Device ':maincpu'" not in after, f"{listed.get('foreign')} / {after!r}")
    call("debug", command="rpclear")


#: Per cpu: a ROM word of that cpu's program, and a pattern that is not what it holds.
REGION_AT = {MAIN: (0x7B8, "8020"), SUB: (0x544, "4e71")}
REGION_END = 0xFFFFE            # the last word of each program ROM region, both 1 MB


def _c14(tag: str, what: str) -> str:
    return f"{what} on {tag}"


C14_EACH = [
    "a region write reads back the pattern through the cpu, naming the region and offset",
    "read_memory through the cpu sees the pattern, and the other cpu's ROM did not move",
    "one byte at the odd address lands on that byte, its word's other byte kept",
    "the region's last word is written and read back",
    "two bytes from the region's last byte are refused before anything is sent",
    "a plain write there goes nowhere and points at region=True",
    "a region write to RAM is refused naming what map answers, and writes nothing",
    "restored: the original word written back through the region reads as before",
]
C14 = [_c14(tag, what) for tag in (MAIN, SUB) for what in C14_EACH]


@section("C", "14. the ROM region write, per cpu", C14)
def c14_region_write() -> None:
    boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
    call("run_for", frames=60, seconds=10.0)       # the sub cpu is out of reset
    for tag in (MAIN, SUB):
        t = [_c14(tag, what) for what in C14_EACH]
        other = SUB if tag == MAIN else MAIN
        addr, pattern = REGION_AT[tag]
        ref = f"{addr:#x}"

        def word(at: int, on: str = tag) -> str:
            return str(call("read_memory", ref=f"{at:#x}", length=2, cpu=on).get("hex"))

        before, beside, end_before = word(addr), word(addr, other), word(REGION_END)
        r = call("write", ref=ref, data_hex=pattern, cpu=tag, region=True)
        cell(t[0], ok(r) and r.get("verified") is True and r.get("readback") == pattern
             and (r.get("region"), r.get("region_offset"), r.get("cpu")) == (tag, addr, tag)
             and r["session"]["altered"] is True, said(r))
        cell(t[1], word(addr) == pattern and word(addr, other) == beside,
             f"{tag} {word(addr)}, {other} {word(addr, other)} (was {beside})")
        r = call("write", ref=f"{addr + 1:#x}", data_hex="5a", cpu=tag, region=True)
        cell(t[2], ok(r) and r.get("verified") is True and word(addr) == pattern[:2] + "5a",
             f"{said(r)} / {word(addr)}")
        r = call("write", ref=f"{REGION_END:#x}", data_hex="a55a", cpu=tag, region=True)
        cell(t[3], ok(r) and r.get("verified") is True and word(REGION_END) == "a55a", said(r))
        call("write", ref=f"{REGION_END:#x}", data_hex=end_before, cpu=tag, region=True)
        r = call("write", ref=f"{REGION_END + 1:#x}", data_hex="a55a", cpu=tag, region=True)
        cell(t[4], refused(r, "bad_argument") and "past the map entry's end" in str(
             r.get("message")) and word(REGION_END) == end_before, said(r))
        r = call("write", ref=ref, data_hex=before, cpu=tag)
        cell(t[5], ok(r) and r.get("verified") is False and r.get("target") == "rom"
             and "`region=True` writes them there" in str(r.get("note"))
             and word(addr) == pattern[:2] + "5a", said(r))
        writes_before = call("status")["session"]["altering_writes"]
        r = call("write", ref="0x200000", data_hex="00", cpu=tag, region=True)
        cell(t[6], refused(r, "bad_argument") and "answers ram at 0x200000" in str(
             r.get("message")) and writes(call("status")) == writes_before, said(r))
        r = call("write", ref=ref, data_hex=before, cpu=tag, region=True)
        cell(t[7], ok(r) and r.get("verified") is True and word(addr) == before
             and word(REGION_END) == end_before, f"{said(r)} / {word(addr)} (was {before})")


#: The frame counter's long, written once a frame by IRQ_VBLANK, and its low word.
COUNTER, COUNTER_LOW = "0x2031fc", "0x2031fe"


def _c15(tag: str, what: str) -> str:
    return f"{what} on {tag}"


C15_MAIN = [
    "a change watch conditioned on the value written is armed with the condition in its row",
    "it stops only on writes its condition holds for, and each hit names the condition",
    "a pass with disarm_watches re-arms it under its condition",
    "a capture of the counter on its low word keeps one row per write, rows + overflow_rows "
    "equal to a count watch on the trigger",
    "each row holds the trigger's word from before its write, one less than its data",
    "a cleared capture sends its removal and drops its rows file",
    "a capture whose tap raises counts one error per trigger write and keeps no row, never an "
    "empty census",
    "a capture whose dumper raises after its open logs MCP_DUMP_FAILED once, closes its .tmp, "
    "and the superseded dump's why names the error",
    "a capture whose struct format would decode past the widest array's row is refused at "
    "watch_add, nothing installed, and one at that bound is taken",
]
C15_SUB = [
    "a conditioned change watch on the sub cpu's RAM is armed on that cpu",
    "a capture on the sub cpu's plain RAM is read through the space and installs on that cpu, "
    "its rows agreeing with a count watch there",
]
C15 = [_c15(MAIN, w) for w in C15_MAIN] + [_c15(SUB, w) for w in C15_SUB]


@section("C", "15. the conditioned change watch and the capture, per cpu", C15)
def c15_condition_and_capture() -> None:
    boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
    call("run_for", frames=60, seconds=10.0)       # the counter runs, the sub cpu is out of reset
    t = [_c15(MAIN, w) for w in C15_MAIN]
    cond = "(wpdata&3)==0"
    r = call("watch_add", ref=COUNTER_LOW, mode="change", length=2, condition=cond, cpu=MAIN)
    cell(t[0], ok(r) and r.get("armed") is True and str(r.get("entry")).endswith(f" if {cond}")
         and r.get("condition") == cond, said(r))
    wrote: list[int] = []
    named = True
    for _ in range(3):
        r = call("run_for", frames=12, seconds=10.0)
        hit = r.get("watch_hit") or {}
        named = named and (not hit or hit.get("condition") == cond)
        wrote += [int(w["wrote"], 16) for w in hit.get("writes", [])]
    cell(t[1], bool(wrote) and named and all(v & 3 == 0 for v in wrote),
         f"{[f'{v:x}' for v in wrote]}")
    call("run_for", frames=2, seconds=10.0, disarm_watches=True)
    w = by_ref(call("declaration_list", kind="watch").get("watches")).get(COUNTER_LOW, {})
    cell(t[2], w.get("state") == "armed" and str(w.get("entry")).endswith(f" if {cond}"),
         str(w)[:160])
    call("declaration_clear", kind="watch", all=True)
    cap = call("watch_add", ref=COUNTER, mode="capture", fmt="u16[2]", trigger=COUNTER_LOW,
               cpu=MAIN)
    call("watch_add", ref=COUNTER_LOW, mode="count", length=1, cpu=MAIN)
    call("run_for", frames=30, seconds=10.0)
    seen = by_ref(call("declaration_list", kind="watch").get("watches"))
    c, k = seen.get(COUNTER, {}), seen.get(COUNTER_LOW, {})
    cell(t[3], ok(cap) and c.get("state") == "captured" and int(c.get("rows_kept", 0)) > 0
         and c.get("rows_kept", 0) + c.get("overflow_rows", 0) == k.get("total"),
         f"{c.get('rows_kept')} + {c.get('overflow_rows')} vs {k.get('total')}")
    rows = c.get("first_rows") or []
    cell(t[4], bool(rows) and all(r["block"][1] == int(r["data"], 16) - 1 for r in rows),
         str(rows[:2])[:160])
    gone = call("declaration_clear", kind="watch", ref=COUNTER)
    cell(t[5], ok(gone) and bool(gone.get("tallies_removed"))
         and not Path(str(c.get("rows_path"))).exists(), said(gone))
    call("declaration_clear", kind="watch", all=True)
    # the control is a count watch on the trigger, read in the planting chunk itself
    cap = call("watch_add", ref=COUNTER, mode="capture", fmt="u16[2]", trigger=COUNTER_LOW,
               cpu=MAIN)
    ctl = call("watch_add", ref=COUNTER_LOW, mode="count", length=1, cpu=MAIN)
    call("run_for", frames=4, seconds=10.0)
    watched = by_ref(call("declaration_list", kind="watch").get("watches"))
    kept = int(watched.get(COUNTER, {}).get("rows_kept", -1))
    at = planted_at(plant_fault("MCP_CAPTURE", str(cap.get("tally_id")), (
        f't.pending = setmetatable({{}}, {{__newindex = function() error("{FAULT}") end}})'),
        f'_G.MCP_TALLY.items["{ctl.get("tally_id")}"].total'))
    call("run_for", frames=30, seconds=10.0)
    seen = by_ref(call("declaration_list", kind="watch").get("watches"))
    c, k = seen.get(COUNTER, {}), seen.get(COUNTER_LOW, {})
    count, first = raised(c)
    grew = int(k.get("total", -1)) - at
    cell(t[6], at >= 0 and grew > 0 and count == grew and FAULT in first
         and kept > 0 and c.get("rows_kept") == kept,
         f"trigger writes since the plant {grew}, errors {count}, rows kept {kept} -> "
         f"{c.get('rows_kept')}, first {first[:60]!r}")
    call("declaration_clear", kind="watch", all=True)
    cap = call("watch_add", ref=COUNTER, mode="capture", fmt="u16[2]", trigger=COUNTER_LOW,
               cpu=MAIN)
    call("run_for", frames=2, seconds=10.0)
    scratch = Path(str(call("status").get("scratch_dir")))
    dumper_fault_cell(t[7], "MCP_CAPTURE", str(cap.get("tally_id")), COUNTER,
                      scratch / f"capture-{cap.get('tally_id')}.txt")
    call("declaration_clear", kind="watch", all=True)
    # the bound is the server's own, computed from the formats it already holds
    bound = mwatches.capture_block_chars_max()
    fields = [f"f{i:02d}" for i in range(16)]
    base = mcapture.block_chars_max(vf.parse("{" + ",".join(f"{f}:i8" for f in fields) + "}"), 0)
    fields[0] += "x" * (bound - base)
    at_bound = "{" + ",".join(f"{f}:i8" for f in fields) + "}"
    past = at_bound.replace(fields[0], fields[0] + "x", 1)
    over = call("watch_add", ref=COUNTER, mode="capture", fmt=past, trigger=COUNTER_LOW)
    listed = [w for w in call("declaration_list",
                              kind="watch").get("watches") or [] if w.get("ref") == COUNTER]
    taken = call("watch_add", ref=COUNTER, mode="capture", fmt=at_bound, trigger=COUNTER_LOW)
    cell(t[8], refused(over, "bad_argument") and "widest row" in str(over.get("message"))
         and listed == [] and ok(taken),
         f"{said(over, 80)} / listed {len(listed)} / {said(taken, 50)}")
    call("declaration_clear", kind="watch", all=True)
    t = [_c15(SUB, w) for w in C15_SUB]
    r = call("watch_add", ref="0x200000", mode="change", length=2, condition="wpdata!=0", cpu=SUB)
    cell(t[0], ok(r) and r.get("armed") is True and r.get("cpu") == SUB
         and str(r.get("entry")).endswith(" if wpdata!=0"), said(r))
    call("declaration_clear", kind="watch", all=True)
    cap = call("watch_add", ref="0x200000", mode="capture", fmt="u16[2]", trigger="0x200002",
               cpu=SUB)
    call("watch_add", ref="0x200002", mode="count", length=1, cpu=SUB)
    call("run_for", frames=10, seconds=10.0)
    seen = by_ref(call("declaration_list", kind="watch").get("watches"))
    c, k = seen.get("0x200000", {}), seen.get("0x200002", {})
    cell(t[1], ok(cap) and (cap.get("source") or {}).get("kind") == "space"
         and c.get("installed") is True and c.get("cpu") == SUB
         and c.get("rows_kept", -1) + c.get("overflow_rows", -1) == k.get("total"),
         f"{said(cap, 60)} / {c.get('rows_kept')} vs {k.get('total')}")
    call("declaration_clear", kind="watch", all=True)
