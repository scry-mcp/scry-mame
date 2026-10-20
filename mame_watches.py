"""THE WATCH FAMILY: `watch_add` arms a WRITE watchpoint (a change watch), sends a write tap
(a count or a capture watch, `mame_tally` and `mame_capture`) or holds a show watch
that arms nothing; `watch_list` reads `wplist` back, `watch_clear` removes and reads back,
`evaluate_watches` renders every watch's bytes at a stop, and `watch_stop` says WHO WROTE THIS
BYTE when a stop is a watchpoint's. What every family shares is `mame_arming`'s, `mame_lists`',
`mame_conditions`' and `mame_clear`'s; where an address's sides go is `mame_map`'s.

THE CONTROL OF A WATCH, decided the way `run_to`'s was: by naming what silences one. Three
things do, and each has its answer here. (1) The ROM copy of a datum whose live copy is in
RAM: measured, the debugger ACCEPTS a watchpoint on a ROM address, lists it, and it can never
fire, so before arming a change watch, the console's `map` is asked on the watch's cpu and a
write side that is `unmapped` is refused as INVALID naming the line; a count or capture tap
sees the cpu's writes there whatever handles them, so it arms and its `note` says so. (2) The
wrong cpu: the row names its cpu, and `map` is asked of the same one. (3) A watch set while
running: measured to be taken and to FIRE, like a breakpoint, so it is armed at once and the
reply says `while_running`. And the debugger's list is read back after every arm, so `armed:
true` is the machine's answer; a row it lists DISABLED (`wpdisable` typed through `debug`) is
`disabled` and never counts as armed.

ONE WATCHED BYTE, ONE DECLARATION. Two change watches sharing a byte would make "who wrote
this byte" ambiguous, and clearing either would disarm the other's byte in silence; so a change
watch sharing a byte with a range another declaration already arms is refused naming it, and a
ref declared again with another shape (width, format, mode) is refused until it is cleared.

WHO WROTE THIS BYTE, measured on a 68000 board: the write has LANDED when the machine stops,
the stop's pc is the instruction AFTER the writer, and the console's own line, which
`-debuglog` sends to `debug.log` in the scratch, names the watchpoint by its index, the value
written, the address written and the writer's pc: `Stopped at watchpoint 1 writing 0038 to
2031FE (PC=0000040E)`. The stub's stop packet for a console row names address 0, so that line
is the attribution. The reply carries every line of the firing watch's own index since the
previous stop (a long is written as two words), the value this server last saw at that address
(`before`) and the value now (`after`).
"""

from __future__ import annotations

import dataclasses
import functools
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, assert_never

from scry_core import prose
from scry_core import value_format as vf
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_arming as arming
import mame_capture as capture
import mame_clear as mclear
import mame_conditions as conditions
import mame_console as console
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_files as files
import mame_inputs as inputs
import mame_lists as mlists
import mame_map as mmap
import mame_read as read
import mame_space as mspace
import mame_state as st
import mame_tally as tally
import mame_tap as mtap
from mame_state import STATE

# A show watch reads at most this many bytes at a stop: a value is what a stop
# survey carries, a region is `memdump`'s job.
SHOW_WATCH_MAX = 128
_WATCH_PACKET = re.compile(r"^T05(?:watch|rwatch|awatch):([0-9a-fA-F]+);")
# One ceiling for every list this server hands back. Below it, the stub's watch stop packet
# and the console's stop line, both CAPTURED.
WRITES_MAX = read.LOG_LIMIT_MAX
# THE `(PC=...)` IS MAME'S ONLY WHEN THE WRITER IS THE WATCH'S OWN CPU (`watchpoint::hit` in
# src/emu/debug/points.cpp): a write by another cpu or a device prints the line bare and lets
# the debugger break when the watch's cpu next runs, so that line names no writer.
_STOP_LINE = re.compile(
    r"Stopped at watchpoint ([0-9A-Fa-f]+) writing ([0-9A-Fa-f]+) to ([0-9A-Fa-f]+)"
    r"(?: \(PC=([0-9A-Fa-f]+)\))?")
#: What a write the console logged with no pc is said to have been written by.
_NO_WRITER = "another cpu or device (MAME names a writer pc only for the watch's own cpu)"


def _writer(line: re.Match[str]) -> str | None:
    """The writer pc a stop line names, or None for a write another cpu or a device made."""
    return st.hex_addr(int(line.group(4), 16)) if line.group(4) else None


def watch_indices(but: dec.Owner | None = None) -> set[int]:
    """The indices of every watchpoint row this server armed, but `but`'s."""
    return {int(a["index"]) for r, a in STATE.armed_watches.items() if r != but}


def check_expr_ref(ref: str) -> None:
    """An `expr` watch's REF goes out as one parameter of `print frame,<ref>` at every stop, so
    it is held to the rules a condition is (`conditions.expression_fault`): the console splits a
    line at a `,` or a `;` outside brackets and EXECUTES an assignment, so `1;g` would release
    the machine at every stop and `(d0=5)` would write a register there, with nothing counted."""
    fault = conditions.expression_fault(ref)
    if fault is None:
        return
    rule, hit = fault
    if rule == "empty":
        raise st.Invalid("bad_argument", "an expr watch's ref is the expression to evaluate; "
                                         "got nothing: `watch_add(ref=\"beamy\", mode=\"expr\")`")
    if rule == "split":
        raise st.Invalid("bad_argument",
            f"ref={ref!r} holds a comma or a newline, which splits the `print` it is evaluated "
            "by into two parameters: an expr watch is ONE expression, so each value is its own "
            "`watch_add(mode=\"expr\")`")
    if rule == "writes":
        raise st.Invalid("bad_argument",
            f"ref={ref!r} holds {hit!r}, which the console EXECUTES at every stop: an expr "
            "watch reads (`beamy`, `w@0x400+2`) and never assigns; a command that writes goes "
            "through `debug`")
    assert_never(rule)


def check_expr_watch(length: int, fmt: str, by: str) -> None:
    """An `expr` watch's machine-independent rules: it takes neither a length nor a fmt, and its
    `by` is its mode's, so it is left at auto. The length is judged a count before it is asked to
    be zero, so `length=False` is refused rather than read as no length."""
    inputs.natural("length", length, " is not a number of bytes, and an expr watch takes none")
    if length or fmt != "auto":
        raise st.Invalid("bad_argument",
                         "an expr watch takes no length and no fmt: the debugger evaluates the "
                         "expression to one number, so `watch_add(ref=<expression>, "
                         "mode=\"expr\")` alone declares it")
    if by != "auto":
        raise st.Invalid("bad_argument", f"an expr watch is declared by its mode; got by={by!r}: "
                                         "`watch_add(mode=\"expr\")` with `by` left at auto")


def check_fmt_carries_no_class(fmt: str) -> None:
    """A CLASS IN THE CALLER'S `fmt` IS REFUSED, never ignored. `vf.parse("ptr16@CODE")` succeeds,
    which is why this has to be said explicitly: `fmt="ptr16@ANYTHING"` parsed fine and then did
    EXACTLY what `fmt="ptr16"` does, with no mention of the class and no refusal, even for a class
    that does not exist. A setting silently left at its default is indistinguishable from success.
    Checked against what the CALLER passed, before `types` is allowed to supply a spec of its own,
    which legitimately carries a class."""
    if "@" in fmt:
        raise st.Invalid("bad_argument",
            f"fmt={fmt!r} names a pointer class, and `fmt` does not take one: a pointer's "
            "class is declared in the `types` file `start` was given (or the map's YAML) and "
            "read from there, never from this argument. Passing it here changed nothing and "
            "is refused rather than ignored. Use `fmt=\"ptr16\"` and type the symbol")


def check_fmt_width(width: int, fmt: str) -> int | None:
    """A `fmt` the caller NAMED, against the `width` beside it, handing back the width the two
    resolve to. `auto` is not judged here and answers None: what it resolves to comes from the
    symbol table, which is the machine's."""
    if fmt == "auto":
        return None
    try:
        return vf.parse(fmt).width_for(width)
    except vf.FormatError as e:
        raise st.Invalid("bad_argument", str(e)) from None


@functools.cache
def capture_block_chars_max() -> int:
    """THE WIDEST A CAPTURE'S DECODED BLOCK MAY PRINT: the widest an array or a string makes over
    the largest block a capture holds, the listing `watch_list`'s budget test measures. A struct's
    field names are the caller's, so a struct is held to what the arrays already make. Computed on
    first use, since `mame_capture` is still importing this module when it is defined."""
    return max([capture.block_chars_max(vf.parse(f"{elem}[{SHOW_WATCH_MAX // size}]"), 0)
                for elem, (_code, size) in vf.SCALARS.items()]
               + [capture.block_chars_max(vf.parse(f"char[{SHOW_WATCH_MAX}]"), 0)])


# How much of a format a refusal or a row quotes: a format past the capture bound is long by
# construction, and quoted whole it would fill the line that refuses it, or every listing.
FMT_SHOWN = 60


def shown_fmt(fmt: str) -> str:
    """`fmt` as a refusal or a row quotes it: whole up to `FMT_SHOWN`, else cut with `...`."""
    return fmt[:FMT_SHOWN] + "..." if len(fmt) > FMT_SHOWN else fmt


def capture_chars_past_bound(width: int, fmt: str) -> int | None:
    """The characters of JSON a capture's widest row under `fmt` decodes to, when that is past
    the bound `watch_add` refuses it at; None when it fits or the format is still `auto`."""
    if not fmt or fmt == "auto":
        return None
    chars = capture.block_chars_max(vf.parse(fmt), width)
    return chars if chars > capture_block_chars_max() else None


def row_fmt(decl: dec.Declaration) -> str | None:
    """A watch row's `fmt`: a capture whose format is past the bound, which no tap was sent for,
    shows it as its refusal does (`shown_fmt`); every other row, and the store, keep it whole."""
    if (decl.watch_mode == "capture" and decl.fmt and decl.width is not None
            and capture_chars_past_bound(decl.width, decl.fmt) is not None):
        return shown_fmt(decl.fmt)
    return decl.fmt


# What `watch_add(by=...)` takes: every `by` but `expr`, which the mode says (`mode="expr"`), so a
# caller never names it twice.
WATCH_BY = tuple(b for b in arming.BY_OPTIONS if b != "expr")


def check_watch_width(width: int, mode: str, fmt: str = "") -> None:
    """The ceiling on a watch's width, which depends on nothing but the mode, and for a capture
    with its format known, the ceiling on its decoded row. Asked before the gate when the width is
    known from the arguments alone, and by the body once the table has filled in an `auto`
    format. A capture reads its block at every trigger into a row, so it is bounded like a show
    watch, and `watch_list` shows `ROWS_SHOWN` of those rows decoded."""
    limit = SHOW_WATCH_MAX if mode in ("show", "capture") else read.READ_MAX
    if width > limit:
        raise st.Invalid("bad_argument",
            f"length={width} is above {prose.counted(limit, 'byte')}: a region is `memdump`'s job")
    if mode == "capture" and (chars := capture_chars_past_bound(width, fmt)) is not None:
        raise st.Invalid("bad_argument",
            f"fmt={shown_fmt(fmt)!r}: its widest row decodes to "
            f"{chars} characters of JSON, past the {capture_block_chars_max()} the widest "
            "array a capture holds makes, which is what keeps `watch_list`'s rows inside a "
            "reply: shorter field names, or fewer fields (the block's bytes are `raw_hex` in "
            "every row anyway)")


# The longest address a `wp` spells, for judging a command before its address is known: the
# spaces this server drives are at most 32 bits wide.
_WIDEST_ADDR = 0xFFFFFFFF


def wp_command(addr: int, length: int, cpu: str | None = None, condition: str = "") -> str:
    """The console command that arms a WRITE watchpoint over `length` bytes on `cpu`, halting
    only on a write whose `condition` holds when there is one (`wpdata` is the value written)."""
    return (f"wp {addr:#x}{console.cpu_suffix(cpu)},{length:#x},w"
            + (f",{condition}" if condition else ""))


def check_watch_add(ref: str, mode: str, length: int = 0, fmt: str = "auto",
                    by: str = "auto", condition: str = "", trigger: str = "",
                    space: str = "program", trigger_type: str = "w", **_: Any) -> None:
    """`watch_add`'s machine-independent half: the vocabularies, the `expr` rules, a class in
    `fmt`, a condition's mode and shape, a trigger's and its type, and the space's. Resolving a
    POINTER's base needs the table, so that stays past the gate."""
    inputs.one_of("mode", mode, dec.WATCH_MODES)
    inputs.one_of("by", by, WATCH_BY)
    inputs.one_of("trigger_type", trigger_type, dec.TRIGGER_TYPES)
    if trigger_type == "r":
        # A READ'S TRIGGER IS ITS REF: with no block, what a row holds and what makes it are one
        # place, so naming it twice is allowed and naming it once is enough.
        check_read_capture(ref, mode, length, fmt, trigger, space)
        trigger = trigger or ref
    if bool(trigger.strip()) != (mode == "capture"):
        raise st.Invalid("bad_argument",
                         "a capture watch needs `trigger`, the write that makes a row "
                         "(`watch_add(ref=<block>, mode=\"capture\", trigger=...)`)"
                         if mode == "capture" else
                         f"trigger={trigger!r} on a {mode} watch: only a capture takes one")
    if trigger.strip():
        inputs.check_ref(trigger, "trigger")
    mspace.check_space(space, mode, ref, by, trigger)
    if condition.strip():
        if mode != "change":
            raise st.Invalid("bad_argument",
                             f"condition={condition!r} on a {mode} watch: only a change watch "
                             "stops, so only it is conditioned (`watch_add(mode=\"change\", "
                             "condition=...)`, `wpdata` being the value written)")
        conditions.check_condition(condition)
    if mode == "expr":
        check_expr_watch(length, fmt, by)
        check_expr_ref(ref)
        return
    if (pr := vf.parse_pointer(ref)) is not None:
        inputs.zero_x(pr.base, "base")
        inputs.check_pointer_offset(ref)
    elif by != "pointer":
        inputs.check_ref(ref)
    if (why := inputs.by_spelling(by, ref)) is not None:
        raise st.Invalid("bad_argument", why)
    check_fmt_carries_no_class(fmt)
    inputs.natural("length", length, " is not a number of bytes: `watch_add(length=...)` takes a "
                   "count of bytes")
    known_width = check_fmt_width(length, fmt)
    if known_width is None and length:
        known_width = length
    if known_width is not None:
        check_watch_width(known_width, mode, fmt)


def check_read_capture(ref: str, mode: str, length: int, fmt: str, trigger: str,
                       space: str) -> None:
    """A capture on a READ trigger holds the read and no block: its `ref` is the trigger itself,
    named again in `trigger` or left out, with no length and no format. Reading memory inside a
    Lua read tap re-enters the bus, which MAME does not survive, so the block a write capture
    reads is refused here rather than attempted. A port's `in` is not captured: the io space is
    the write capture's."""
    if mode != "capture":
        raise st.Invalid("bad_argument", f"trigger_type=\"r\" on a {mode} watch: only a "
                                         "capture takes a trigger type (`watch_add(ref=<trigger>, "
                                         "mode=\"capture\", trigger=<trigger>, "
                                         "trigger_type=\"r\")`)")
    if space != mspace.PROGRAM:
        raise st.Invalid("bad_argument", "a read capture taps a program address; a port's "
                                         "reads are not captured, and `space=\"io\"` takes a "
                                         "write trigger alone (`watch_add(..., "
                                         "trigger_type=\"r\")` with no `space`)")
    if (trigger.strip() and inputs.place_key(ref) != inputs.place_key(trigger)) or length or (
            fmt != "auto"):
        raise st.Invalid("bad_argument",
                         "a read capture holds no block: its row is the read itself, its "
                         "`data` and `mask`, since a Lua read tap that reads memory inside its "
                         "callback re-enters the bus, which MAME does not survive. Declare it "
                         "on its trigger alone, with no length and no fmt: "
                         "`watch_add(ref=<trigger>, mode=\"capture\", trigger_type=\"r\")`")


# ------------------------------------------------------------------------------- watches


def _one_byte_scalars(fmt: vf.Format) -> bool:
    """Whether every scalar `fmt` reads is one byte: `u8`, `i8`, an array of them, a string, a
    struct of such fields. A byte has no order, so such a format decodes the same either way."""
    if fmt.kind == "struct":
        return all(_one_byte_scalars(field) for _name, field in fmt.fields)
    return fmt.kind == "string" or (fmt.elem is not None and vf.SCALARS[fmt.elem][1] == 1)


def decode_order(ses: gs.Session, cpu: str | None, fmt: str) -> str:
    """The order `fmt` is decoded in on `cpu`: the cpu's own, which a cpu whose order is not
    established refuses (`SessionError`), except for a format of one-byte scalars, which needs
    none and reads on any cpu."""
    if _one_byte_scalars(vf.parse(fmt)):
        return "little"         # either order decodes these bytes alike; it names none of the cpu's
    return cpus.layout(ses, cpu).byte_order


def _value(raw: bytes, width: int, fmt: str, order: str) -> vf.Value:
    """`width` bytes read as `fmt` in the TARGET's byte order: one value, a list, a
    string or a struct, as the format says."""
    return vf.parse(fmt).decode(raw, order, width)


def disarm_for_pass(ses: gs.Session) -> list[dec.Owner]:
    """Disarm every armed change watch for ONE pass, keeping the declarations: the refs
    disarmed, in arming order. A watch on a byte written many times a frame stops every later
    `run_to` and `run_for` of a session, and clearing and re-declaring it around each
    unrelated question is the step that gets forgotten."""
    disarmed: list[dec.Owner] = []
    for owner, armed in STATE.armed_watches.items():
        ses.monitor(mclear.clear_command("watch", armed["index"]))
        disarmed.append(owner)
    return disarmed


def rearm_after_pass(ses: gs.Session, refs: list[dec.Owner]) -> list[dec.Owner]:
    """Re-arm the watches `disarm_for_pass` disarmed, each on its own cpu, and read their rows
    back from `wplist`: the debugger numbers a re-armed row afresh, and the index is what a
    stop's log line is matched by. The refs re-armed and listed; a ref the list no longer shows
    is left out and its entry marked disabled, never guessed at.

    THE PASS'S OWN SURVEY MAY HAVE ARMED ONE ALREADY: a pointer watch whose pointer moved is
    followed at the stop (`_follow`), which clears the old row and arms the new place there
    and then. Its row is listed under the record's index, so it is taken as re-armed rather
    than sent a second time; and a follow that lost both places dropped the record, so that
    ref has nothing to re-arm and is left out."""
    before = mlists.wp_held(ses)
    held = {r["index"] for r in before}
    pending = [ref for ref in refs
               if ref in STATE.armed_watches and STATE.armed_watches[ref]["index"] not in held]
    for ref in pending:
        armed = STATE.armed_watches[ref]
        # WITH ITS CONDITION: a conditioned watch re-armed bare would stop at every write.
        ses.monitor(wp_command(armed["addr"], armed["length"], armed["cpu"],
                               armed["condition"]))
    rows = mlists.wp_held(ses)
    rearmed: list[dec.Owner] = []
    for ref in refs:
        if ref not in STATE.armed_watches:
            continue
        armed = STATE.armed_watches[ref]
        if ref not in pending:
            rearmed.append(ref)
            continue
        row = mlists.armed_row(before, rows, int(armed["addr"]), int(armed["length"]), armed["cpu"])
        if row is None or (row.get("condition") or "") != armed["condition"]:
            armed["enabled"] = False
            continue
        armed.update(index=row["index"], entry=row["entry"], enabled=row["enabled"],
                     cpu=row["cpu"])
        rearmed.append(ref)
    return rearmed


def refresh_baselines(ses: gs.Session, addr: int, n: int, cpu: str | None) -> None:
    """Re-read every armed watch whose bytes a write of `n` at `addr` of `cpu` touched, so the
    next stop's `before` is what the machine held after the write and not what the previous
    survey saw. A watch on another cpu watches other memory, which the write did not touch."""
    for armed in STATE.armed_watches.values():
        if armed["cpu"] in (None, cpu) and mspace.ranges_meet(armed["addr"], armed["length"],
                                                              addr, n):
            armed["last"] = _read_exact(ses, armed["addr"], armed["length"], armed["cpu"])


def _read_exact(ses: gs.Session, addr: int, n: int, cpu: str | None = None) -> bytes:
    """`n` bytes at `addr` of `cpu` (the stub's first cpu when None), or the refusal a SHORT
    answer deserves: a value rendered from fewer bytes than the watch declared would be a
    number of the right shape and the wrong meaning, and `struct` would otherwise raise a bare
    error out of a stop survey. Another cpu is read through its thread of the patched stub; a
    stub without threads reads only its first, and the refusal says so rather than handing
    over the first cpu's bytes under another's name."""
    if cpu is None or cpu == cpus.stub_cpu(ses):
        raw = ses.read(addr, n, thread=1)
    elif (thread := cpus.thread_of(ses, cpu)) is not None:
        raw = ses.read(addr, n, thread=thread)
    else:
        raise gs.Refused(f"{cpu}'s memory is read through a thread of the gdbstub's thread "
                         f"patch, and this stub reads only {cpus.stub_cpu(ses)}")
    if len(raw) != n:
        raise gs.Refused(f"the stub answered {prose.counted(len(raw), 'byte')} for {n} at "
                         f"{addr:#x}")
    return raw


def chase(ses: gs.Session, res: dec.Resolved) -> tuple[int | None, dict[str, Any]]:
    """Follow a pointer ref against the machine NOW, on its declaration's cpu: the pointer read
    at the base, at the type's width or the cpu's, plus the offset. The address (None for a
    null pointer, which is a state and never a watch at zero) and the `pointer` block a reply
    carries so the reader sees through what the address was reached."""
    assert res.pointer is not None and res.base_addr is not None
    cpu = res.decl.cpu
    lay = cpus.layout(ses, cpu)
    width = res.pointer_width or lay.pointer_width
    raw = _read_exact(ses, res.base_addr, width, cpu)
    value = int.from_bytes(raw, lay.byte_order)
    info: dict[str, Any] = {"at": st.hex_addr(res.base_addr), "length": width,
                            "value": st.hex_addr(value), "offset": res.offset}
    if res.pointer.field is not None:
        info["field"] = res.pointer.field
    # A NEAR POINTER HOLDS AN OFFSET IN ITS TARGET'S SEGMENT, not a linear address: on a
    # board relocated by `bases`, the value read through a symbol of a relocated class is
    # placed under a class's base, the way `disassemble` places a direct operand.
    # Read raw, `[dmaptr]` answers the assembler's offset while the struct lives at that
    # offset plus the DATA base. WHICH class is the type's to say (`ptr16@CODE`: a routine's
    # address kept in DATA points into CODE), else the base symbol's, which is
    # right for a data pointer kept in data. An address base carries no class and no
    # type, so its pointer is taken as the linear value it is.
    relocation: int | None = None
    table = STATE.table(cpu)
    if res.pointer_class is not None:
        klass: str | None = res.pointer_class
        relocation = _class_base(res.pointer_class, table)
        info["relocated"] = {"class": klass, "base": st.hex_addr(relocation),
                             "class_from": "type"}
    else:
        klass = table.classes.get(res.pointer.base.strip().upper())
        relocation = table.bases.get(klass) if klass is not None else None
        if relocation is not None:
            info["relocated"] = {"class": klass, "base": st.hex_addr(relocation),
                                 "class_from": "base"}
    # The class is judged BEFORE the null check, so a type naming a class this table
    # lacks is refused when declared, not at the first stop that finds the pointer set.
    if value == 0:
        return None, info
    target = (relocation or 0) + value + res.offset
    if not (relocation or 0) <= target < (1 << (8 * width)) + (relocation or 0):
        # The pointer's own width bounds the space, FROM THE SEGMENT BASE it is placed
        # under: an offset
        # that reaches below the base leaves the segment, and a place below zero would
        # reach the stub as a packet it cannot read.
        raise gs.SessionError(f"the pointer plus the offset, {target:#x}, is outside what a "
                              f"{width}-byte pointer addresses"
                              + (f" under the {klass} base {relocation:#x}"
                                 if relocation is not None else ""))
    return target, info


def _class_base(klass: str, table: gs.SymbolTable) -> int:
    """The base a pointer typed into `klass` is placed under: the caller's `bases` entry
    when it relocated the class, else the map's own segment base (`linear - offset`), which
    is what CODE and a `rom` class run at. A class this table does not carry is refused
    naming the ones it does, because a base guessed for it would place the watch somewhere
    plausible and wrong."""
    based = table.bases.get(klass)
    if based is not None:
        return based
    seg = table.segment_bases.get(klass)
    if seg is not None:
        return seg
    carried = sorted(set(table.classes.values()))
    if klass in carried:
        # The map carries the class and its rows do not share one `linear - offset`: a
        # tile sheet laid out as many blocks, on a measured board. No single base is honest.
        #
        # AND THE REMEDY DEPENDS ON WHICH OF TWO THINGS IS TRUE, so `bases` is not suggested
        # for both. A class ALREADY in `bases` cannot be fixed by any
        # value there: `rom` gives each row its own address rather than one base to add an
        # offset to, and that is the whole reason the rows share none. Sending a caller back
        # to `bases` when `bases` already names the class costs them the search.
        declared = klass in (table.bases or {})
        remedy = (f"`bases` ALREADY names {klass}, and no value there can back a pointer into "
                  "it: a class whose rows share no segment base has no single base to add a "
                  "pointer's offset to. Point the pointer at a class that has one, or read "
                  "the target with an explicit address"
                  if declared else
                  f"name {klass} in `bases` if the running board reads it off one")
        raise gs.SessionError(
            f"the pointer's type names class {klass}, whose rows in this map do not share one "
            f"segment base, so no base places a pointer into it; {remedy}")
    hint = ""
    for c in carried:
        if klass.startswith(c) and klass != c:
            # `ptr16@CODEu16` reads as one class name: the grammar cannot tell where the
            # class ends and a bare target begins, so a typed target goes in braces.
            hint = (f"; `{klass}` reads as one class name, and a class-typed pointer's "
                    f"target goes in braces: `ptr16@{c}{{v:{klass[len(c):].lower()}}}`")
    raise gs.SessionError(
        f"the pointer's type names class {klass}, which this build's table does not carry "
        f"(its classes: {', '.join(carried) if carried else 'none, a table without classes'}); "
        f"a base guessed for it would place the watch somewhere plausible and wrong{hint}")


def null_note(info: dict[str, Any]) -> str:
    return (f"the pointer at {info['at']} is null, so there is nothing to watch yet; the "
            f"declaration is kept and re-resolved at every stop")


def values_from(write_maps_to: str, read_maps_to: str | None) -> str:
    """Where a change watch's values come from. `memory` when the address reads back
    through the handler it is written through; `bus` when it does not (the read side is
    unmapped, or another handler: a write-only latch, a register whose read is a port), in
    which case a memory read answers noise and the values are the writes the console logs."""
    return "memory" if read_maps_to == write_maps_to else "bus"


def _holder(records: dict[dec.Owner, dict[str, Any]], owner: dec.Owner,
            holds: Callable[[dict[str, Any]], bool]) -> str | None:
    """The ref of the OTHER declaration on the same cpu whose record `holds` says yes to, or
    None: another cpu's range is another program's memory, and a cpu nobody could read falls
    back to the address, as a row's adoption does."""
    return next((r[0] for r, rec in records.items()
                 if r != owner and cpus.same_cpu(r[1], owner[1]) and holds(rec)), None)


def range_holder(records: dict[dec.Owner, dict[str, Any]], size_key: str,
                 owner: dec.Owner, addr: int, width: int) -> str | None:
    """The declaration whose record holds this very range (`_holder`): one tap is one range.
    `size_key` is the word the record spells the byte count with: a tally's `width`."""
    return _holder(records, owner, lambda rec: (rec["addr"], rec[size_key]) == (addr, width))


def overlap_holder(owner: dec.Owner, addr: int, width: int) -> str | None:
    """The declaration whose armed change watch shares a byte with this range (`_holder`)."""
    return _holder(STATE.armed_watches, owner,
                   lambda rec: mspace.ranges_meet(rec["addr"], rec["length"], addr, width))


def watch_aliased(owner: dec.Owner, addr: int, width: int,
                  clear_tool: mclear.ClearTool | None = "watch_clear") -> arming.Refusal | None:
    """The refusal when another declaration already arms a range sharing a byte with this one:
    two watchpoints on one byte make "who wrote this byte" ambiguous, and clearing one
    declaration would disarm the other's byte in silence. `start`'s re-arm passes no
    `clear_tool`: its report names no call to make."""
    other = overlap_holder(owner, addr, width)
    if other is None:
        return None
    return ("ambiguous_ref", f"{addr:#x} for {prose.counted(width, 'byte')} shares a byte with a "
            f"range already armed under {other!r}: "
            f"{mclear.one_declaration('watched range', other, clear_tool, owner[1])}")


def record_watch(owner: dec.Owner, row: dict[str, Any], maps_to: str,
                 read_maps_to: str | None) -> None:
    """What this session armed for `ref`, with the debugger's own row. The console's log
    is read from THIS moment on: before any watch is armed nothing in it can be a watch's.
    `last` is the bytes last seen (a memory-sourced watch) and `last_wrote` the value last
    written (a bus-sourced one): each is what `before` means at the next hit."""
    if not STATE.armed_watches and STATE.scratch is not None:
        STATE.debuglog_mark = files.file_mark(STATE.scratch / "debug.log")
    STATE.armed_watches[owner] = {"index": row["index"], "addr": row["addr"],
                                "length": row["length"], "entry": row["entry"],
                                "cpu": row["cpu"], "condition": row.get("condition") or "",
                                "enabled": row["enabled"], "last": None, "last_wrote": None,
                                "maps_to": maps_to, "read_maps_to": read_maps_to,
                                "values_from": values_from(maps_to, read_maps_to)}


def change_row(held: list[dict[str, Any]], addr: int, width: int, cpu: str | None,
               condition: str, taken: set[int]
               ) -> tuple[dict[str, Any] | None, st.Invalid | None]:
    """The row of the debugger's list a change watch at `addr` on `cpu` adopts (None when it needs
    a new one), skipping the rows of `taken`, or the refusal when the row there stops under a
    condition that is not `condition`: `breakpoints.stop_row`'s rule, and like it it sends and
    raises nothing. Unlike it, it does not look for the owner's own row first: a watch keeps its
    row by index (`_arm_change_watch`), so the caller asks that before this."""
    row = mlists.adoptable_row(held, addr, cpu, taken, width)
    if row is not None and (row.get("condition") or "") != condition:
        return None, mclear.another_condition("watch", addr, row, condition, width)
    return row, None


def _arm_change_watch(ses: gs.Session, owner: dec.Owner, addr: int, width: int,
                      condition: str = "") -> arming.Refusal | None:
    """Arm ONE change watch on its owner's cpu: the map control over that cpu's space, the
    alias check, the `wp` (with `condition`, as the console reads it) unless the debugger
    already lists the row, the read back, the record. The refusal (its code and its prose) when
    it could not be, or None. An address nothing writes is the caller's argument to change; an
    alias is another declaration's; a listed row under a condition that is not this one is
    `change_row`'s refusal; a row the list lacks, or lists without the condition sent
    (`mlists.listed_as_sent`), is a readback refused. The re-arm at `start` judges each row by
    the same two (`change_row`, `listed_as_sent`) and differs in sending every `wp` before
    reading `wplist` back once."""
    cpu = owner[1]
    # ITS OWN ROW FIRST: a re-declaration must not stack a second row beside the one it
    # already has.
    own = STATE.armed_watches.get(owner)
    held = mlists.wp_held(ses) if own is not None else None
    row = mlists.row_at_index(held, own["index"]) if own is not None and held is not None else None
    if row is not None and ((row["addr"], row["length"]) != (addr, width)
                            or (row.get("condition") or "") != condition):
        row = None
    refused, maps_to, read_maps_to = mmap.change_watch_side(ses, addr, cpu)
    if refused is not None:
        return refused
    refused = watch_aliased(owner, addr, width)
    if refused is not None:
        return refused
    if held is None:
        held = mlists.wp_held(ses)
    if row is None:
        row, unadoptable = change_row(held, addr, width, cpu, condition, watch_indices(owner))
        if unadoptable is not None:
            return unadoptable.code, str(unadoptable)
    if row is None:
        command = wp_command(addr, width, cpu, condition)
        ses.monitor(command)
        row = mlists.armed_row(held, mlists.wp_held(ses), addr, width, cpu)
        if not mlists.listed_as_sent(row, condition):
            return "readback_refused", mlists.not_listed(f"`{command}`", "wplist",
                                                         bool(condition))
    assert row is not None
    record_watch(owner, row, maps_to, read_maps_to)
    return None


def _follow(ses: gs.Session, decl: dec.Declaration, target: int) -> dict[str, str] | None:
    """A change watch whose pointer now points elsewhere: the old row is removed, a row at
    the new place armed and read back, the record moved. `{from, to}` when it moved, None
    when it is where it was (or is a show watch, which arms nothing). A place nothing writes
    or one another declaration holds leaves the old row and the record as they are, and the
    reply's `moved` carries `why` instead."""
    armed = STATE.armed_watches.get(decl.owner)
    if decl.watch_mode != "change" or (armed is not None and armed["addr"] == target):
        return None
    assert decl.width is not None
    try:
        cond = conditions.console_condition(decl.condition, decl.cpu) if decl.condition else ""
    except st.Invalid as e:
        return {"from": st.hex_addr(armed["addr"]) if armed is not None else "null",
                "to": st.hex_addr(target), "why": str(e)}
    if armed is None:
        # Declared while the pointer was NULL, so nothing was armed: the stop that finds
        # the pointer set arms it, and says it came from null.
        refused = _arm_change_watch(ses, decl.owner, target, decl.width, cond)
        if refused is not None:
            return {"from": "null", "to": st.hex_addr(target), "why": refused[1]}
        return {"from": "null", "to": st.hex_addr(target)}
    old_addr, length, cpu = int(armed["addr"]), int(armed["length"]), armed["cpu"]
    ses.monitor(mclear.clear_command("watch", armed["index"]))
    STATE.armed_watches.pop(decl.owner)
    refused = _arm_change_watch(ses, decl.owner, target, decl.width, cond)
    if refused is not None:
        # The old row is gone: re-arm it, so the watch keeps watching SOMETHING it said.
        before = mlists.wp_held(ses)
        ses.monitor(wp_command(old_addr, length, cpu, cond))
        row = mlists.armed_row(before, mlists.wp_held(ses), old_addr, length, cpu)
        if row is not None:
            record_watch(decl.owner, row, str(armed["maps_to"]), armed["read_maps_to"])
        return {"from": st.hex_addr(old_addr), "to": st.hex_addr(target), "why": refused[1]}
    return {"from": st.hex_addr(old_addr), "to": st.hex_addr(target)}


def _watch_add_expr(ses: gs.Session, ref: str, width: int, fmt: str, by: str,
                    running: bool) -> dict[str, Any]:
    """An `expr` watch: the expression is evaluated ONCE on the console before it is stored,
    so a name the debugger cannot resolve is refused here, naming the console's answer,
    and never rides on every stop unavailable."""
    check_expr_watch(width, fmt, by)
    decl = arming.declare("watch", "expr", ref, watch_mode="expr")
    arming.refuse_conflict(decl)
    try:
        value = read.print_values(ses, [ref])[0]
    except gs.SessionError as e:
        raise st.Invalid("bad_argument",
                         f"the debugger did not evaluate {ref!r} to a number: {e}. An expr "
                         "watch takes what the console's `print` evaluates; `symbols_find` "
                         "checks a name of the table") from None
    is_new = arming.store().add(decl)
    reply: dict[str, Any] = {"ref": ref, "by": "expr", "mode": "expr", "while_running": running,
                             "stored": True, "already_stored": not is_new, "armed": False,
                             "state": "evaluated"}
    if not running:
        reply["reading"] = _expr_reading(value)
    return menvelope.envelope(reply)


def expression_refs() -> list[str]:
    """Every declared expression, in declaration order: what a stop survey prints beside
    the frame."""
    if STATE.store is None:
        return []
    return [d.ref for d in STATE.store.declarations()
            if d.kind == "watch" and d.watch_mode == "expr"]


def _read_through(ses: gs.Session, on: str | None, what: str, reader: str | None,
                  how: str) -> None:
    """The refusal of a `cpu` a watch cannot be read on: `what` is read `how`, on `reader`
    alone."""
    if on is not None and reader is not None and on != reader:
        raise st.Invalid("bad_argument", f"{what} is read {how}: {reader}, not {on}; "
                         "`focus(cpu=...)` makes the one you name the visible one")


def watch_add(ses: gs.Session, ref: str, mode: str, width: int, fmt: str,
              by: str, cpu: str = "", condition: str = "", trigger: str = "",
              trigger_type: str = "w") -> dict[str, Any]:
    """The body of the `watch_add` tool."""
    running = arming.running_on_arrival(ses)
    check_watch_add(ref, mode, width, fmt, by, condition, trigger, trigger_type=trigger_type)
    if trigger_type == "r":
        # THE READ ITSELF is what the row holds: its byte at the trigger, for the declaration's
        # width and format, which no caller gives, and the trigger its ref when not named
        # (`check_read_capture`).
        width, fmt, trigger = 1, "u8", trigger or ref
    # THE DECLARATION'S CPU is the one the call names, else the visible one, read now; an
    # expr watch has none, since the console evaluates it on whichever cpu is visible.
    on = cpus.chosen(ses, cpu)
    if mode == "expr":
        if inputs.cpu_given(cpu):
            _read_through(ses, on, "an expr watch", cpus.visible_cpu(ses),
                          "by the console, on the visible cpu")
        return _watch_add_expr(ses, ref, width, fmt, by, running)
    chosen = arming.decide_by(ref, by, on, "watch")
    if mode in dec.TAP_MODES:
        tally.check_count_watch(chosen, mode)
    if chosen == "pointer":
        # THE BASE IS JUDGED BEFORE THE TABLE-DEPENDENT REST: a ref with no pointer to start
        # from (a stack local, an untyped base under `->`) is refused for that rather than for a
        # width the table would have supplied. A fault in a NAMED `fmt` is told earlier still, by
        # `check_watch_add` before the gate, because it needs no machine to be wrong.
        probe = arming.resolve_decl(arming.declare("watch", "pointer", ref, on, width=1, fmt="u8",
                                       watch_mode="show"))
        if probe.state == "unresolved" and probe.why is not None:
            raise st.Invalid("unknown_ref", probe.why)
    # A class in `fmt` is refused by `check_fmt_carries_no_class`, applied by `check_watch_add`
    # before this point; its reason lives there.
    if fmt == "auto":
        # THE TYPE COMES FROM THE SYMBOL TABLE when the caller gave none: a `type:` beside
        # the symbol, or a `types` file; through a pointer, the named FIELD's own format.
        # Else the widest unsigned scalar the width divides.
        types = STATE.table(on).types
        typed = types.get(ref.strip().upper()) if chosen == "symbol" else None
        if chosen == "pointer":
            typed = vf.pointer_field_fmt(ref, types)
    else:
        typed = None
    width, fmt = size_watch(mode, width, fmt, typed, st.Invalid(
        "bad_argument", f"a {mode} watch needs a length in bytes, or a fmt that names its size "
        f"(u16[8], char[16], {{x:i16,y:i16}}), or a symbol the table types; {ref} has none of "
        "the three: `watch_add(length=...)` or `watch_add(fmt=...)`"))
    # Stored as typed and substituted at each arming, as a breakpoint's: a rebuild moves the
    # symbols.
    typed = condition.strip()
    cond = conditions.console_condition(typed, on) if typed else ""
    # A TRIGGER AT AN ADDRESS IS KEPT IN THE ONE SPELLING a ref is (`0x2031fe`), so two
    # spellings of one capture are one declaration; a name stays as typed, and the name the
    # capture on this block is held on stays reachable after a rebuild drops it.
    trig = trigger.strip()
    if trig and arming.classify_call(
            trig, on, held=arming.held_triggers(on, ref, chosen)) == "address":
        trig = dec.canonical_ref(trig, "address")
    ref = ref.strip()
    decl = arming.declare("watch", chosen, ref, on, width=width, fmt=fmt,
                          watch_mode=mode, condition=typed, trigger=trig,
                          trigger_type=trigger_type)
    stored = arming.store().held_ref(ref, chosen, ("watch",), on)
    if stored is not None and stored != ref:
        # AN ADDRESS DECLARED AGAIN IN ANOTHER SPELLING IS THE SAME DECLARATION, and
        # it is handled under its stored spelling, the string a clear takes.
        ref, decl = stored, dataclasses.replace(decl, ref=stored)
    arming.refuse_conflict(decl)
    res = arming.resolve_decl(decl)
    reply: dict[str, Any] = {"ref": ref, "by": chosen, "mode": mode, "length": width,
                             "fmt": fmt, "cpu": or_unavailable(on, st.NO_CPU_READ_WHY),
                             "while_running": running}
    if cond:
        conditions.condition_fields(reply, typed, cond)
    if decl.trigger:
        reply.update(trigger=decl.trigger, trigger_type=decl.trigger_type)
    if res.state == "unresolved" and res.why is not None:
        # A pointer ref with no base to start from is refused, not kept: nothing a later
        # build defines would give a stack local an address.
        raise st.Invalid("unknown_ref", res.why)
    if cond and res.state != "unresolved":
        # JUDGED BEFORE ANYTHING IS STORED, a pointer's too: one stored null is armed by the
        # stop that finds the pointer set, with no call left to refuse it in, and wherever it
        # then points its `wp` fits no worse than at the widest address judged here.
        at = res.addr if res.addr is not None else _WIDEST_ADDR
        judged = conditions.judged_condition(ses, wp_command(at, width, on, cond), cond, on)
        conditions.refuse_if_left_visible(judged, cond, on)
        if (refusal := judged.refusal) is not None:
            raise st.Invalid("bad_argument", f"the debugger did not evaluate `{cond}`, and "
                                             "a watch it cannot evaluate never stops (MAME "
                                             f"arms it all the same): {refusal}. "
                                             "`symbols_find(name=...)` checks a name; "
                                             "`watch_add` again once it reads")
    if res.state == "pointer":
        if running:
            raise gs.NotStopped("a watch through a pointer reads the pointer to place itself, "
                                "and the machine was released with no stop read since, so it "
                                "is taken as RUNNING: `stop` it, then `watch_add` again")
        try:
            target, info = chase(ses, res)
        except gs.SessionError as e:
            raise st.Invalid("bad_argument", str(e)) from None
        reply["pointer"] = info
        if target is None:
            is_new = arming.store().add(decl)
            return menvelope.envelope({**reply, "stored": True, "already_stored": not is_new,
                                       "armed": False, "state": "null_pointer",
                                       "note": null_note(info)})
        res = dec.Resolved(decl, "resolved", target)
    if res.state == "unresolved":
        is_new = arming.store().add(decl)
        return menvelope.envelope({**reply, "stored": True, "already_stored": not is_new,
                                   "armed": False, "state": "unresolved",
                                   "note": f"{ref} is not a symbol in this build; the declaration "
                                   "is kept and arms nothing until a build defines it"})
    if (trig and capture.trigger_addr(trig, STATE.table(on).table) is None
            and arming.store().index_of(decl) is not None):
        # THE CAPTURE HELD ON A NAME A REBUILD DROPPED, declared again, is that declaration:
        # adopted and listed as `watch_list` lists it, where a new one on that name is refused
        # at its tap, which has nowhere to sit.
        arming.store().add(decl)
        return menvelope.envelope({**reply, "stored": True, "already_stored": True, "armed": False,
                                   "state": "unresolved",
                                   "note": f"the trigger {trig!r} is not a symbol of this build; "
                                   "the declaration is kept and captures nothing until a build "
                                   "defines it"})
    addr = res.addr
    assert addr is not None
    reply["addr"] = st.hex_addr(addr)
    if mode in dec.TAP_MODES:
        return _watch_add_tap(ses, addr, width, decl, reply)
    if mode == "show":
        is_new = arming.store().add(decl)
        reply.update(stored=True, already_stored=not is_new, armed=False, state="evaluated")
        if not running:
            reply["reading"] = _reading(ses, decl, addr, cpu=on)[0]
        return menvelope.envelope(reply)
    refused = _arm_change_watch(ses, decl.owner, addr, width, cond)
    if refused is not None:
        code, why = refused
        if code == "ambiguous_ref":
            raise st.Invalid(code, why)
        if code == "readback_refused":
            # A WATCH IS STORED ONLY ONCE IT IS ARMED (the store write is below), so unlike a
            # breakpoint's refusal this one leaves nothing behind, and says so rather than
            # borrowing the breakpoints' "kept" words for a write that never happened.
            return menvelope.invalid(code, why, ref=ref, addr=reply["addr"], stored=False,
                                     armed=False, state="gone",
                                     note="nothing is stored for it: declare it again with "
                                     "`watch_add` once the debugger lists the row "
                                     "(`debug(\"wplist\")` shows what it holds)")
        return menvelope.invalid(code, why, ref=ref, addr=reply["addr"])
    is_new = arming.store().add(decl)
    armed = STATE.armed_watches[decl.owner]
    if not running and armed["values_from"] == "memory":
        reading, raw = _reading(ses, decl, addr, cpu=armed["cpu"])
        if raw is not None:
            armed["last"] = raw
        reply["reading"] = reading
    # `armed` IS THE ROW'S ANSWER, as the breakpoint twin's is: a row the debugger already
    # listed at the range is adopted without a second `wp`, and one listed DISABLED (a
    # `wpdisable` typed through `debug`) is not reported `armed: true`.
    reply.update(stored=True, already_stored=not is_new, armed=armed["enabled"],
                 state=mlists.row_state(armed), index=armed["index"], entry=armed["entry"],
                 cpu=armed["cpu"],
                 write_maps_to=armed["maps_to"],
                 read_maps_to=or_unavailable(armed["read_maps_to"], mmap.NO_READ_SIDE_WHY),
                 values_from=armed["values_from"])
    return menvelope.envelope(st.add_note(reply, cpus.ignored_note(ses, armed["cpu"])))


def _watch_add_tap(ses: gs.Session, addr: int, width: int, decl: dec.Declaration,
                   reply: dict[str, Any]) -> dict[str, Any]:
    """A COUNT or CAPTURE watch on its declaration's cpu (`send_tap` judges and sends it), the
    declaration stored once the send was taken, and the record kept for the surveys to read.
    Arming moves nothing, so `altered` stays."""
    ref, cpu = decl.owner
    scratch = STATE.scratch
    assert scratch is not None
    # SENT BEFORE STORED: a send the console's pipe refuses raises here, and a declaration
    # stored for an install that never went would read `not_installed` for the wrong reason.
    refused, sent = send_tap(ses, scratch, decl, addr, width)
    if refused is not None:
        code, why = refused
        return menvelope.invalid(code, why, ref=ref, addr=st.hex_addr(addr))
    is_new = arming.store().add(decl)
    reply.update(stored=True, already_stored=not is_new, armed=False, state="pending", cpu=cpu,
                 **sent)
    return menvelope.envelope(reply)


def bus_word_split(addr: int, width: int, cpu: str | None,
                   space: str = mspace.PROGRAM) -> tuple[str | None, str | None]:
    """A count range judged against the bus of `cpu`'s `space`: the refusal of one that splits a
    bus word (`mspace.splits_bus_word`, said by `tally.split_why`), else None; and beside it the
    note an install adds when the bus width is unknown and the range is wider than a byte. The
    program space's counts and the io space's take the same judgement."""
    bus_bits = cpus.bus_width(cpu, space)
    if bus_bits is not None and mspace.splits_bus_word(addr, width, bus_bits):
        return tally.split_why(addr, width, bus_bits, cpu, space), None
    unchecked = bus_bits is None and width > 1
    return None, tally.bus_unchecked_note(space) if unchecked else None


def size_watch(mode: str, width: int, fmt: str, typed: str | None,
               unsized: st.Invalid) -> tuple[int, str]:
    """A watch's width and format, in either space: with `fmt` left `auto`, the table's type
    (`typed`) when no length was given, else the widest unsigned scalar the length divides, else
    the caller's refusal `unsized`; then the format sized against the length and the mode's
    bound."""
    if fmt == "auto":
        if typed is not None and width == 0:
            fmt = typed
        elif width > 0:
            fmt = dec.fmt_for_width(width)
        else:
            raise unsized
    try:
        width = vf.parse(fmt).width_for(width)
    except vf.FormatError as e:
        raise st.Invalid("bad_argument", str(e)) from None
    check_watch_width(width, mode, fmt)
    return width, fmt


def send_count(scratch: Path, owner: dec.Owner, addr: int, width: int, space: str,
               unchecked: str | None, maps_to: str, read_maps_to: str | None) -> dict[str, Any]:
    """A count watch's install sent, once judged, in either space: its note carries the bus-word
    caveat when the space's width could not be read, and where an unmapped write goes."""
    sent = tally.send_install(scratch, owner, addr, width, space)
    st.add_note(sent, unchecked)
    sent["note"] = mmap.with_unmapped_note(sent["note"], maps_to, addr, space, read_maps_to)
    return sent


def send_capture(scratch: Path, owner: dec.Owner, addr: int, width: int, trigger: int,
                 src: capture.TapSource | None, space: str, maps_to: str,
                 trigger_read: str | None, trigger_type: str = "w") -> dict[str, Any]:
    """A capture's install sent, once judged, its trigger in `space`: its note says where an
    unmapped trigger's writes go."""
    sent = capture.send_install(scratch, owner, addr, width, trigger, src, space, trigger_type)
    if trigger_type == "r":
        return sent
    sent["note"] = mmap.with_unmapped_note(sent["note"], maps_to, trigger, space, trigger_read,
                                           trigger=True)
    return sent


def send_tap(ses: gs.Session, scratch: Path, decl: dec.Declaration, addr: int,
             width: int) -> tuple[arming.Refusal | None, dict[str, Any]]:
    """Judge a count or capture watch's tap and send its install, or the refusal as its code
    beside its text, nothing sent. A COUNT: a range that splits a bus word of its cpu's program
    space is refused before anything (`mspace.splits_bus_word`), then the range's write side is
    asked of the console's `map` and reported, an unmapped one with its note (`unmapped_note`),
    and one range carries one tally. A CAPTURE: its trigger resolves on its cpu, the TRIGGER's
    write side is the one asked (the tap sits there), the block has memory a tap can read
    (`mame_capture`), and one block on one trigger carries one capture."""
    owner = decl.owner
    if decl.watch_mode == "count":
        split, unchecked = bus_word_split(addr, width, owner[1])
        if split is not None:
            return ("bad_argument", split), {}
        refused, maps_to, read_maps_to = _tally_write_side(ses, owner, addr, width)
        if refused is not None:
            return refused, {}
        sent = send_count(scratch, owner, addr, width, mspace.PROGRAM, unchecked, maps_to,
                          read_maps_to)
        return None, {"write_maps_to": maps_to,
                      "read_maps_to": or_unavailable(read_maps_to,
                                                        mmap.NO_READ_SIDE_WHY), **sent}
    # A STORED CAPTURE IS JUDGED AS A DECLARED ONE: a row stored before the format bound, or by
    # another server, re-arms at `start` through here and not through `watch_add`.
    try:
        check_watch_width(width, "capture", decl.fmt or "")
    except st.Invalid as e:
        return ("bad_argument", str(e)), {}
    trigger = capture.trigger_addr(decl.trigger, STATE.table(owner[1]).table)
    if trigger is None:
        return ("unknown_ref", inputs.not_a_ref("the trigger", decl.trigger, owner[1])), {}
    refused, maps_to, trigger_read = mmap.write_side(ses, trigger, owner[1])
    reads = decl.trigger_type == "r"
    if refused is not None and not reads:
        return (refused[0], f"the trigger: {refused[1]}"), {}
    capture_id = capture.id_for(owner[1], addr, width, trigger, mspace.PROGRAM,
                                decl.trigger_type)
    other = next((r[0] for r, rec in STATE.tallies.items()
                  if r != owner and rec["tally_id"] == capture_id), None)
    if other is not None:
        return ("ambiguous_ref", f"{addr:#x} for {prose.counted(width, 'byte')} on the trigger "
                f"{trigger:#x} is already captured under {other!r}: "
                f"{mclear.one_declaration('capture', other, 'watch_clear', owner[1])}"), {}
    if reads:
        # A READ is tapped where the read side maps, and reads no block (`check_read_capture`).
        if trigger_read is None:
            return ("bad_argument", f"the trigger: the console's `map` named no `Read:` side "
                    f"at {trigger:#x}, so whether a read there can fire is unknown"), {}
        sent = send_capture(scratch, owner, addr, width, trigger, None, mspace.PROGRAM,
                            maps_to, trigger_read, decl.trigger_type)
        if trigger_read == "unmapped":
            sent["note"] = st.join_notes(
                sent["note"], f"the trigger: nothing in the machine handles a read at "
                f"{trigger:#x}, so the cpu reading it gets the bus's unmapped value") or ""
        return None, {"trigger_addr": st.hex_addr(trigger),
                      "trigger_maps_to": or_unavailable(trigger_read, mmap.NO_READ_SIDE_WHY),
                      **sent}
    try:
        src = capture.source(addr, width, owner[1], mmap.read_side(ses, owner[1]))
    except st.Invalid as e:
        return (e.code, str(e)), {}
    sent = send_capture(scratch, owner, addr, width, trigger, src, mspace.PROGRAM, maps_to,
                        trigger_read)
    return None, {"trigger_addr": st.hex_addr(trigger), "trigger_maps_to": maps_to,
                  "source": src.fields(), **sent}


def _tally_write_side(ses: gs.Session, owner: dec.Owner, addr: int, width: int
                      ) -> tuple[arming.Refusal | None, str, str | None]:
    """The write side of a range about to be tallied on the owner's cpu, and the
    one-tally-per-range rule, each refusal as its code beside its text: the `map` first, where a
    port's tap asks who holds it first (`mame_iotaps._held_elsewhere`)."""
    refused, maps_to, read_maps_to = mmap.write_side(ses, addr, owner[1])
    if refused is not None:
        return refused, maps_to, read_maps_to
    # a port's tally is in another space, so it holds no program range
    other = range_holder({r: rec for r, rec in STATE.tallies.items()
                           if rec["registry"] == tally.REGISTRY
                           and rec.get("space", mspace.PROGRAM) == mspace.PROGRAM},
                          "width", owner, addr, width)
    if other is not None:
        return (("ambiguous_ref", f"{addr:#x} for {prose.counted(width, 'byte')} already has a "
                 f"tally declared under {other!r}: "
                 f"{mclear.one_declaration('tally', other, 'watch_clear', owner[1])}"),
                maps_to, read_maps_to)
    return None, maps_to, read_maps_to


def _tally_item(ses: gs.Session, decl: dec.Declaration, addr: int, frame: int | None,
                shown: int, at_stop: bool) -> dict[str, Any]:
    """What a survey or a list says about a count or capture declaration: the tap's own
    account when this session sent one, else that none is recorded (the rearm at `start` could
    not send it, or it was cleared), which is a state and never an empty table. A capture's
    says which access it captures in every state."""
    item = _tally_state(decl, addr, frame, shown, at_stop)
    if decl.watch_mode == "capture":
        item.setdefault("trigger_type", decl.trigger_type)
    return item


def _tally_state(decl: dec.Declaration, addr: int, frame: int | None, shown: int,
                 at_stop: bool) -> dict[str, Any]:
    assert decl.width is not None and decl.fmt is not None
    if (decl.owner not in STATE.tallies and decl.trigger
            and capture.trigger_addr(decl.trigger, STATE.table(decl.cpu).table) is None):
        return {"state": "unresolved", "addr": st.hex_addr(addr),
                "why": f"the trigger {decl.trigger!r} is not a symbol of this build: the "
                       "declaration is kept and captures nothing until a build defines it"}
    if decl.owner not in STATE.tallies and arming.stale(decl):
        return {"state": "stale", "addr": st.hex_addr(addr), "why": arming.stale_why()}
    if decl.owner not in STATE.tallies or STATE.scratch is None:
        return {"state": "not_installed", "addr": st.hex_addr(addr),
                "why": "no tap is recorded for this declaration in this session: "
                       "`start`'s rearm did not send it, or it was cleared"}
    evaluate = capture.evaluate if decl.watch_mode == "capture" else tally.evaluate
    return evaluate(STATE.scratch, decl.owner, decl.width, decl.fmt, frame, shown, at_stop)


def _reading(ses: gs.Session, decl: dec.Declaration, addr: int, raw: bytes | None = None,
             cpu: str | None = None) -> tuple[dict[str, Any], bytes | None]:
    """A watch's bytes read NOW, as the `reading` every reader of a watch gives them: available
    with `value` and `raw_hex`, or `unavailable` with the stub's refusal and never a zero. It
    is its own field because it is its own axis: the row's `state` says where the watch is
    PLACED, and a change watch is `armed` and read at the same stop."""
    assert decl.width is not None and decl.fmt is not None
    # THE CPU'S OWN BYTE ORDER, and a cpu the stub does not describe, or whose order is not
    # established, leaves the value unreadable with the reason rather than failing the call.
    try:
        raw = raw or _read_exact(ses, addr, decl.width, cpu)
        value = _value(raw, decl.width, decl.fmt, decode_order(ses, cpu, decl.fmt))
    except gs.SessionError as e:
        return unavailable(str(e)), None
    return {"available": True, "value": value, "raw_hex": raw.hex()}, raw


def _expr_reading(value: int | gs.SessionError) -> dict[str, Any]:
    """An expression's `reading`: its value with `hex`, or the console's refusal."""
    if isinstance(value, gs.SessionError):
        return unavailable(str(value))
    return {"available": True, "value": value, "hex": f"{value:#x}"}


def resolved_state(decl: dec.Declaration, res: dec.Resolved, null: bool = False) -> str | None:
    """The state word a watch row takes from its declaration and its resolution alone, the one
    `watch_list`, the stop survey and `start`'s re-arm all ask: `evaluated` for an expression, or
    a show watch that resolves; `null_pointer` where a chase read a null pointer; `unresolved`
    where the ref names nothing this build has. None where the state is what arming says (a
    change watch's placement, a tap's account, a stale build). A pointer not yet chased is no
    state of its own: a show watch through one is evaluated at every stop, which chases it, and
    any other is chased by whoever arms it."""
    if res.state == "expr":
        return "evaluated"
    if res.state == "unresolved" or (res.addr is None and res.state != "pointer"):
        return "null_pointer" if null else "unresolved"
    return "evaluated" if decl.watch_mode == "show" else None


def _change_placement(decl: dec.Declaration, held: list[dict[str, Any]],
                      addr: int) -> dict[str, Any]:
    """Where a change watch is PLACED, read against the debugger's own list, in the one
    shape `watch_list` and the stop survey both give: its row's state with the `entry`,
    else `stale` over another build with the reason, else `gone`."""
    assert decl.width is not None
    armed = STATE.armed_watches.get(decl.owner)
    row = mlists.row_at_index(held, armed["index"]) if armed is not None else None
    if row is not None and (row["addr"], row["length"]) == (addr, decl.width):
        return {"state": mlists.row_state(row), "entry": row["entry"], "cpu": row["cpu"]}
    if ("watch", decl.owner) in STATE.conditions_unresolved:
        return {"state": "unresolved", "why": "the ref resolved and its condition names a "
                                              "symbol this build lacks, so nothing is armed"}
    if arming.stale(decl):
        return {"state": "stale", "why": arming.stale_why()}
    return {"state": "gone"}


def _wplist_or_error(ses: gs.Session) -> list[dict[str, Any]] | gs.SessionError:
    """The debugger's `wplist`, or why it could not be read."""
    try:
        return mlists.wp_held(ses)
    except gs.SessionError as e:
        return e


def _placement(rows: list[dict[str, Any]] | gs.SessionError, decl: dec.Declaration,
               addr: int) -> dict[str, Any]:
    """A change watch's placement against `rows`, the debugger's `wplist`. A list the console
    cannot give does not sink the reply: the placement is then this server's own record, and
    `why` says so."""
    if isinstance(rows, gs.SessionError):
        armed = STATE.armed_watches.get(decl.owner)
        return {"state": mlists.row_state(armed) if armed is not None else "gone",
                "why": f"the debugger's `wplist` could not be read back ({rows}), so this "
                "is what this server armed"}
    return _change_placement(decl, rows, addr)


def place_after_pass(ses: gs.Session, rows: list[dict[str, Any]],
                     refs: list[dec.Owner]) -> None:
    """Place again, in `rows` (a stop's `watches`, edited in place), every row the survey
    found `gone` among `refs`, the change watches a pass re-armed: the survey was read while
    they were off. One `wplist`, read after the re-arm, and only when a row needs it."""
    decls = {(d.ref, d.cpu): d for d in arming.store().declarations()
             if d.kind == "watch" and d.watch_mode == "change" and d.owner in refs}
    held: list[dict[str, Any]] | gs.SessionError | None = None
    for row in rows:
        cpu = row.get("cpu")              # unavailable on a row that names none: the key's None
        decl = decls.get((str(row.get("ref")), cpu if isinstance(cpu, str) else None))
        if decl is None or row.get("mode") != "change" or row.get("state") != "gone":
            continue
        if held is None:
            held = _wplist_or_error(ses)
        row.update(_placement(held, decl, int(STATE.armed_watches[decl.owner]["addr"])))


#: An expr watch's `length` and `fmt`: it reads an expression, never a span of bytes.
EXPR_NO_BYTES_WHY = "an expr watch reads an expression, not a span of bytes"


def _rows(ses: gs.Session, decls: list[dec.Declaration],
          held: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every watch declaration with its state against the table and the debugger's list."""
    out: list[dict[str, Any]] = []
    for decl in decls:
        if decl.kind != "watch":
            continue
        item = {**arming.decl_row(decl), "mode": decl.watch_mode,
                "length": or_unavailable(decl.width, EXPR_NO_BYTES_WHY),
                "fmt": or_unavailable(row_fmt(decl), EXPR_NO_BYTES_WHY)}
        if decl.condition:
            conditions.typed_condition(item, decl)
        res = arming.resolve_decl(decl)
        null = False
        if res.state == "pointer":
            # WHERE IT POINTS NOW, when the machine can be asked; else where it was armed.
            armed = STATE.armed_watches.get(decl.owner)
            try:
                if ses.running:
                    raise gs.NotStopped("a running machine answers no read")
                target, info = chase(ses, res)
                item["pointer"] = info
                null = target is None
                res = (dec.Resolved(decl, "resolved", target) if target is not None
                       else dec.Resolved(decl, "unresolved", why=null_note(info)))
            except gs.SessionError:
                res = (dec.Resolved(decl, "resolved", int(armed["addr"])) if armed is not None
                       else dec.Resolved(decl, "unresolved"))
        word = resolved_state(decl, res, null)
        if word is not None and (word != "evaluated" or res.addr is None):
            item["state"] = word
            out.append(item)
            continue
        # The chase above leaves no pointer, so `resolved_state` answered every row with no
        # address: what reaches here is a place.
        assert res.addr is not None
        if word == "evaluated":      # a show watch, read here
            item["addr"], item["state"] = st.hex_addr(res.addr), word
            if not ses.running:
                item["reading"] = _reading(ses, decl, res.addr, cpu=decl.cpu)[0]
        elif decl.watch_mode == "count":
            item.update(_tally_item(ses, decl, res.addr, None, tally.BUCKETS_MAX, at_stop=False))
        elif decl.watch_mode == "capture":
            # THE FIRST ROWS, AS THE SURVEY SHOWS THEM: every row is a whole block, and the
            # listing ceiling's worth of them crossed what the client takes in line. The rest is
            # in `rows_path`, which is the capture's whole record anyway.
            item.update(_tally_item(ses, decl, res.addr, None, st.ROWS_SHOWN, at_stop=False))
        else:
            item["addr"] = st.hex_addr(res.addr)
            item.update(_change_placement(decl, held, res.addr))
            armed = STATE.armed_watches.get(decl.owner)
            if "entry" in item and armed is not None:
                item["values_from"] = armed["values_from"]
        out.append(item)
    return out


def watch_list(ses: gs.Session, cpu: str = "") -> dict[str, Any]:
    """The body of the `watch_list` tool: every declaration, or with `cpu` the watches placed
    on it (a change watch's row under it in `wplist <cpu>`, a count watch's tap on it)."""
    only = cpus.named(ses, cpu) if inputs.cpu_given(cpu) else None
    held = mlists.wp_held(ses, only)
    rows = _rows(ses, arming.store().declarations(), held)
    if only is not None:
        rows = [r for r in rows if r.get("cpu") == only]
    mine = watch_indices()
    reply: dict[str, Any] = {
        "watches": rows,
        "foreign": [r["entry"] for r in held if r["index"] not in mine],
    }
    reply["cpu"] = or_unavailable(only, st.NO_CPU_NAMED_WHY)   # every list tool carries it
    # A REMOVAL IS READ HERE, because its declaration is already gone and the
    # per-declaration survey has nothing left to reach it through. It is READ and never
    # resent: `read_removal_answers` says why that asymmetry with the install is the point.
    if STATE.scratch is not None and (stuck := mtap.read_removal_answers(STATE.scratch)):
        reply["tallies_not_removed"] = stuck
    if ses.running:
        reply["last_stop"] = STATE.as_of()
    return menvelope.envelope(reply)


# A segmented address, which no ref here can be: an expression watch's text never has this shape.
_SEG_OFF = re.compile(r"(?:0[xX])?[0-9a-fA-F]+:(?:0[xX])?[0-9a-fA-F]+")
# One token a symbol or an address could be, as against an expression watch's text.
_ONE_TOKEN = re.compile(r"[\w.$#]+")


def check_watch_clear(ref: str = "", all: bool = False, space: str = mspace.PROGRAM,
                      **_: Any) -> None:
    """`watch_clear`'s machine-independent half: one `ref` or `all=True`, a port named by `space`
    and never by a suffix, and a `ref` judged by the shape `watch_add` judged it by: a pointer's
    base, else a segmented address refused, else one token that starts like an address and is
    not one refused. An expression watch's text is matched as declared."""
    mclear.check_clear(ref, all, "watch")
    inputs.one_of("space", space, mspace.SPACES)
    if all:
        if space != mspace.PROGRAM:
            raise st.Invalid("bad_argument", f'space="{space}" names where a `ref` is, and '
                             "`all` clears every watch in every space: `watch_clear(all=True)` "
                             "with no `space`")
        return
    text = ref.strip()
    tail = mspace.suffix(mspace.IO)
    if text.lower().endswith(tail):
        raise st.Invalid("bad_argument", f"ref={ref!r} carries its space in its text: a port is "
                         f'its `ref` with `space="io"` (`watch_clear(ref="{text[:-len(tail)]}", '
                         'space="io")`)')
    if (pr := vf.parse_pointer(text)) is not None:
        inputs.zero_x(pr.base, "base")
        inputs.check_pointer_offset(text)
    elif _SEG_OFF.fullmatch(text):
        inputs.check_ref(text)
    elif _ONE_TOKEN.fullmatch(text):
        inputs.zero_x(text)


def watch_clear(ses: gs.Session, ref: str, cpu: str = "", all_: bool = False) -> dict[str, Any]:
    """The body of the `watch_clear` tool: `ref`'s declarations (every one with no ref), on
    every cpu or on `cpu` alone."""
    check_watch_clear(ref=ref, all=all_)
    ref = "" if all_ else ref
    running = arming.running_on_arrival(ses)
    reached = mclear.clearing(ses, "watch", ref, cpu)
    going = reached.going
    if ref.strip() and not going:
        return mclear.refuse_unmatched_clear(ref, "watch", reached)
    rows: list[mclear.Going] = []
    tallies_removed: list[dict[str, Any]] = []
    for decl in going:
        if decl.watch_mode in dec.TAP_MODES:
            # THE REMOVAL IS SENT, like the install was: the tap goes when the console next
            # reads a line, and the record and the dump go now, so nothing later reads them.
            if STATE.scratch is not None and (gone := mtap.send_remove(STATE.scratch,
                                                                       decl.owner)):
                tallies_removed.append(gone)
            continue
        armed = STATE.armed_watches.get(decl.owner)
        if armed is not None:
            rows.append((decl.owner, str(armed["entry"]), int(armed["index"])))
    # The record goes only once the debugger's list no longer shows the row, as a breakpoint's
    # does: a refusal of the removal, or a row still listed after it, keeps the row armed and
    # the record with it, or the next hit there would read as foreign.
    cleared, still_held = mclear.disarm_rows(ses, "watch", rows, lambda: mlists.wp_held(ses))
    for owner, _entry, _index in cleared:
        STATE.armed_watches.pop(owner)
    disarmed = [entry for _owner, entry, _index in cleared]
    removed = arming.store().discard(going)
    STATE.conditions_unresolved -= {("watch", d.owner) for d in going}
    reply: dict[str, Any] = {"declarations_cleared": removed, "disarmed": disarmed,
                             "while_running": running}
    if still_held:
        reply["note"] = mclear.still_held_note("watch", still_held)
    if tallies_removed:
        reply["tallies_removed"] = tallies_removed
    return menvelope.envelope(reply)


def evaluate_expressions(ses: gs.Session) -> dict[str, int] | gs.SessionError:
    """Every declared expression's value in ONE `print`, or the console's refusal, which
    then leaves every expression's reading unavailable rather than lost."""
    refs = expression_refs()
    if not refs:
        return {}
    try:
        return dict(zip(refs, read.print_values(ses, refs), strict=True))
    except gs.SessionError as e:
        return e


def evaluate_watches(ses: gs.Session, fresh: dict[dec.Owner, bytes] | None = None,
                     expressions: dict[str, int] | gs.SessionError | None = None,
                     frame: int | None = None) -> list[dict[str, Any]]:
    """Every watch declaration EVALUATED at this stop: its bytes, rendered, or why it has
    none. A change watch is read too: MAME arms no trap byte (measured), so its bytes are
    the program's. What is read is also what `before` means at the next hit. `fresh` holds
    bytes a caller read a moment ago at this same stop (the hit's `after`), so one read
    serves both; `expressions` holds the expr watches' values when the caller already printed
    them beside the frame (the survey does), else they are printed here; `frame` is the
    stop's, what a count watch's dump is waited for and judged against."""
    if STATE.store is None:
        return []
    fresh = fresh or {}
    if expressions is None:
        expressions = evaluate_expressions(ses)
    wp_rows: list[list[dict[str, Any]] | gs.SessionError] = []

    def place(decl: dec.Declaration, addr: int) -> dict[str, Any]:
        """A change watch's placement (`_placement`), `wplist` asked once per survey and only
        if one needs placing."""
        if not wp_rows:
            wp_rows.append(_wplist_or_error(ses))
        return _placement(wp_rows[0], decl, addr)

    out: list[dict[str, Any]] = []
    for decl in STATE.store.declarations():
        if decl.kind != "watch":
            continue
        item: dict[str, Any]
        if decl.watch_mode == "expr":
            item = {"ref": decl.ref, "by": "expr", "mode": "expr", "state": "evaluated",
                    "reading": _expr_reading(expressions if isinstance(expressions,
                                                                   gs.SessionError)
                                             else expressions[decl.ref])}
            out.append(item)
            continue
        assert decl.width is not None and decl.fmt is not None
        item = {"ref": decl.ref, "by": decl.by,
                "cpu": or_unavailable(decl.cpu, arming.NO_DECL_CPU_WHY), "mode": decl.watch_mode,
                "length": decl.width, "fmt": row_fmt(decl)}
        if decl.condition:
            conditions.typed_condition(item, decl)
        res = arming.resolve_decl(decl)
        null = False
        if res.state == "pointer":
            # RE-RESOLVED AT EVERY STOP, because the pointer can move: the value read is at
            # where it points NOW, and a change watch armed at the old struct is moved to
            # the new one, the reply saying from where to where.
            try:
                target, info = chase(ses, res)
            except gs.SessionError as e:
                # WHERE IT POINTS could not be read, so it is placed where it was armed, as
                # `watch_list` places it; a show watch has no such place.
                armed = STATE.armed_watches.get(decl.owner)
                item.update(place(decl, int(armed["addr"]))
                            if armed is not None else {"state": "unresolved"},
                            reading=unavailable(str(e)))
                out.append(item)
                continue
            item["pointer"] = info
            if target is None:
                null, res = True, dec.Resolved(decl, "unresolved", why=null_note(info))
            else:
                moved = _follow(ses, decl, target)
                if moved is not None:
                    item["moved"] = moved
                # A move the debugger refused leaves the watch ARMED where it was: the value
                # read, the address reported and the `before` baseline are that place's.
                still = STATE.armed_watches.get(decl.owner)
                if moved is not None and "why" in moved and still is not None:
                    target = int(still["addr"])
                res = dec.Resolved(decl, "resolved", target)
        word = resolved_state(decl, res, null)
        if word is not None and word != "evaluated":
            item["state"] = word
            if null:
                item["why"] = res.why
            out.append(item)
            continue
        # The chase above leaves no pointer, so `resolved_state` answered every row with no
        # address: what reaches here is a place.
        assert res.addr is not None
        if decl.watch_mode in dec.TAP_MODES:
            item.update(_tally_item(ses, decl, res.addr, frame, st.ROWS_SHOWN,
                                    at_stop=True))
            out.append(item)
            continue
        armed = STATE.armed_watches.get(decl.owner)
        if armed is not None and armed["values_from"] == "bus":
            # A WRITE-ONLY REGISTER IS NEVER READ: the value is the last one written, off
            # the console's log, and the read side is named so the reader knows why.
            item.update(place(decl, res.addr), addr=st.hex_addr(res.addr),
                        reading={"state": "bus",
                                 "last_wrote": or_unavailable(
                                     armed["last_wrote"], "nothing has written it since it was "
                                                          "armed"),
                                 "read_maps_to": or_unavailable(armed["read_maps_to"],
                                                                   mmap.NO_READ_SIDE_WHY)})
            out.append(item)
            continue
        reading, raw = _reading(ses, decl, res.addr, fresh.get(decl.owner), decl.cpu)
        item.update({"state": word} if word is not None else place(decl, res.addr),
                    reading=reading, addr=st.hex_addr(res.addr))
        armed = STATE.armed_watches.get(decl.owner)
        if armed is not None and raw is not None:
            armed["last"] = raw
        out.append(item)
    return out


# THE WRITER'S PART OF A WATCH STOP'S `how`, in both spellings this module composes (its own
# watch's `... written by pc P`, and another row's `..., wrote V by pc P: ...`), so a count keys
# the watch and not each writer, a write with no pc to name (`_NO_WRITER`) included. Read
# here, beside the two f-strings it undoes.
_HOW_WRITER = re.compile(
    rf"(?:, wrote [0-9a-f]+)? by (?:pc 0x[0-9a-f]+|{re.escape(_NO_WRITER)})")


def how_key(how: str) -> str:
    """`how` with the writer taken off: the key a count of stops by watch uses."""
    return _HOW_WRITER.sub("", how, count=1)


def _foreign_how(line: re.Match[str]) -> str:
    """How a stop by a watchpoint this server did not arm is named when the console's line
    for it is there: its index, the address it wrote, the value and the writer's pc."""
    at, pc = st.hex_addr(int(line.group(3), 16)), _writer(line)
    by = f"by pc {pc}" if pc else f"by {_NO_WRITER}"
    return mclear.foreign_row_how("watch", int(line.group(1), 16),
                                  f" at {at} this server did not arm, "
                                  f"wrote {line.group(2).lower()} {by}")


#: Why a watch_hit's `before` is not a value: no earlier reading to compare with.
_NO_BEFORE_MEMORY = ("no value was read before this write: the watch's bytes are read at each "
                     "stop, and none was read since it was armed")
_NO_BEFORE_BUS = "the first write logged since the watch was armed: no earlier write to compare"


def stop_line_in(lines: list[str]) -> bool:
    """Whether the console logged a watchpoint's stop among `lines`: what a run the console
    started looks for after each landing, since such a run sends no packet and the stop can
    land with the counter's tick."""
    return any(_STOP_LINE.search(ln) for ln in lines)


def watch_packet_addr(ses: gs.Session) -> int | None:
    """The address a watchpoint's stop packet names, or None when the last stop was not a
    watchpoint's. What `run_to` reads to tell a watch stop from its own target."""
    m = _WATCH_PACKET.match(getattr(ses, "last_stop_packet", "") or "")
    return int(m.group(1), 16) if m else None


def watch_stop(ses: gs.Session, since: list[str]
               ) -> tuple[str, dict[str, Any] | None, dict[dec.Owner, bytes]] | None:
    """When the last stop was a watchpoint's: `how`, the attribution, and the bytes read
    for it (so the evaluation that follows reads nothing twice). The attribution is the
    console's own line for the stop, by its watchpoint's INDEX, in `since`
    (`debuglog_since`), with every line of that index and the bytes this server saw before
    and sees now. None when the stop was not a watch's. A FOREIGN watch is named by its line
    (the address WRITTEN, the value and the writer pc).

    The packet names no row (the module docstring says why): it says only that a watch
    stopped the machine, which matters when the console logged no line for it."""
    packet = watch_packet_addr(ses)
    stops = [mm for ln in since if (mm := _STOP_LINE.search(ln)) is not None]
    by_index = {a["index"]: r for r, a in STATE.armed_watches.items()}
    if not stops:
        if packet is None:
            return None
        return ("a watchpoint stopped the machine and the console logged no line for it, so "
                "which one is not known", None, {})
    newest = stops[-1]
    owner = by_index.get(int(newest.group(1), 16))
    if owner is None:
        return (_foreign_how(newest), None, {})
    ref = owner[0]
    armed = STATE.armed_watches[owner]
    decl = next((d for d in arming.store().declarations()
                 if d.kind == "watch" and d.owner == owner), None)
    if decl is None:
        # THE ROW OUTLIVED ITS DECLARATION: `watch_clear` sent the removal, the debugger kept
        # the row, and the record stayed so this stop could be named. Nothing renders it (a
        # declaration carried the width and the format), and the reply says what removes it.
        return (f"watch {ref}: {st.hex_addr(armed['addr'])} written, cleared while the "
                f"debugger still listed its row; {mclear.pasted_clear('watch', armed['index'])} "
                "removes it",
                None, {})
    assert decl.width is not None and decl.fmt is not None
    hit: dict[str, Any] = {"ref": ref, "addr": st.hex_addr(armed["addr"]), "cpu": armed["cpu"],
                           "index": armed["index"]}
    if decl.condition:
        # The console logs a conditioned row's stop only when the condition held, so every line
        # below is one it let through.
        conditions.typed_condition(hit, decl)
    # EVERY line of THIS watchpoint since the previous stop, not the last one and not
    # another watch's: a 68000 writes a long as two words and the console prints one line
    # per write, and two watches can fire inside one window.
    lines = [(ln.strip(), mm) for ln in since
             if (mm := _STOP_LINE.search(ln)) is not None
             and int(mm.group(1), 16) == armed["index"]]
    writes: list[dict[str, Any]] = [{"wrote": f"0x{mm.group(2).lower()}",
                                     "to": st.hex_addr(int(mm.group(3), 16)),
               "pc": or_unavailable(_writer(mm), _NO_WRITER)} for _ln, mm in lines]
    # THE SAME CEILING AS EVERY OTHER LIST, and the LAST writes are the ones kept: a latch
    # written many times a frame puts hundreds of writes in one reply, and the write that
    # stopped the machine is the last one.
    hit.update(writes_total=len(writes), truncated=len(writes) > WRITES_MAX)
    writes = writes[-WRITES_MAX:]
    # The row is named by one of these lines, the newest, so there is always at least one.
    hit.update(writer_pc=writes[-1]["pc"], writes=writes)
    by = f"pc {writes[-1]['pc']}" if isinstance(writes[-1]["pc"], str) else _NO_WRITER
    how = f"watch {ref}: {st.hex_addr(armed['addr'])} written by {by}"
    hit["values_from"] = armed["values_from"]
    fresh: dict[dec.Owner, bytes] = {}
    if armed["values_from"] == "bus":
        # THE VALUES ARE THE WRITES: what the console logged is what reached the handler,
        # and a memory read here would answer the read side, which is not this register.
        hit["before"] = (armed["last_wrote"] if armed["last_wrote"] is not None
                         else unavailable(_NO_BEFORE_BUS))
        hit["after"] = armed["last_wrote"] = int(writes[-1]["wrote"], 16)
    else:
        last = armed.get("last")
        hit["before"] = unavailable(_NO_BEFORE_MEMORY)
        decoded = False
        try:
            order = decode_order(ses, armed["cpu"], decl.fmt)
            if isinstance(last, bytes):
                hit["before"], decoded = _value(last, decl.width, decl.fmt, order), True
            now = _read_exact(ses, armed["addr"], armed["length"], armed["cpu"])
            hit["after"] = _value(now, decl.width, decl.fmt, order)
            fresh[owner] = now
        except gs.SessionError as e:
            hit["after"] = unavailable(str(e))
            if isinstance(last, bytes) and not decoded:
                hit["before"] = unavailable(str(e))     # read before, not decoded
    hit["lines"] = [ln for ln, _mm in lines]
    # A LEFTOVER FROM AN EARLIER SESSION SAYS SO, in the stop itself and not only in
    # `start`'s rearm block. The store keeps a declaration's original origin across a
    # re-arm, so an origin that is not this session's is a watch re-armed at start rather
    # than declared here -- the one that quietly deflects the first run of a new session.
    if decl.origin is not None and decl.origin != STATE.session_origin:
        hit["rearmed"] = True
        how += arming.inherited(decl)
    return how, hit, fresh
