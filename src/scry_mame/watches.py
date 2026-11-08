"""The watch family: `watch_add` arms a write watchpoint (change), sends a write tap (count or
capture) or holds a show watch that arms nothing; `watch_stop` says who wrote the byte when a
stop is a watchpoint's. What every family shares is `arming`'s, `lists`',
`conditions`' and `clear`'s; where an address's sides go is `map`'s.

What silences a watch, and its answer: (1) a ROM address is accepted and listed but never
fires, so a change watch asks the console's `map` on its cpu and refuses an `unmapped` write
side (a tap sees the cpu's writes whatever handles them, so it arms with a `note`); (2) the
wrong cpu, so the row names its cpu and `map` is asked of it; (3) a watch set while running
fires like a breakpoint, so it arms at once and says `while_running`. `armed: true` is read
back from the debugger's list; a row listed DISABLED is `disabled`, never armed.

One watched byte, one declaration: two change watches on a byte make "who wrote this byte"
ambiguous and a clear would disarm the other's, so overlapping a range another declaration
arms is refused, as is a ref redeclared with another shape until it is cleared.

Who wrote this byte, on a 68000: the write has landed when the machine stops, so the stop's
pc is the instruction after the writer. The stub's stop packet for a console row names
address 0; attribution is the console's own line in `debug.log`, `Stopped at watchpoint 1
writing 0038 to 2031FE (PC=0000040E)`. The reply carries every line of the firing index since
the previous stop, the value last seen (`before`) and the value now (`after`)."""

from __future__ import annotations

import dataclasses
import functools
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, assert_never

from scry_core import declaration_rows, prose
from scry_core import value_format as vf
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable, unavailable

from scry_mame import arming, capture, conditions, console, cpus, files, inputs, read, tally
from scry_mame import clear as mclear
from scry_mame import declarations as dec
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import lists as mlists
from scry_mame import map as mmap
from scry_mame import space as mspace
from scry_mame import state as st
from scry_mame import tap as mtap
from scry_mame.state import STATE

# a value is what a stop survey carries; a region is `memdump`'s job
SHOW_WATCH_MAX = 128
_WATCH_PACKET = re.compile(r"^T05(?:watch|rwatch|awatch):([0-9a-fA-F]+);")
WRITES_MAX = read.LOG_LIMIT_MAX
# the `(PC=...)` is MAME's only when the writer is the watch's own cpu
# (`watchpoint::hit`, src/emu/debug/points.cpp); another cpu or a device prints it bare
_STOP_LINE = re.compile(
    r"Stopped at watchpoint ([0-9A-Fa-f]+) writing ([0-9A-Fa-f]+) to ([0-9A-Fa-f]+)"
    r"(?: \(PC=([0-9A-Fa-f]+)\))?")
_NO_WRITER = "another cpu or device (MAME names a writer pc only for the watch's own cpu)"


def _writer(line: re.Match[str]) -> str | None:
    """The writer pc a stop line names, or None for a write another cpu or a device made."""
    return st.hex_addr(int(line.group(4), 16)) if line.group(4) else None


def watch_indices(but: dec.Owner | None = None) -> set[int]:
    """The indices of every watchpoint row this server armed, but `but`'s."""
    return {int(a["index"]) for r, a in STATE.armed_watches.items() if r != but}


def check_expr_ref(ref: str) -> None:
    """An `expr` ref is held to a condition's rules: the console executes an assignment in a
    `print`."""
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
    """An `expr` watch's machine-independent rules: no length, no fmt, `by` left at auto."""
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
    """A class in the caller's `fmt` is refused, never ignored: `vf.parse("ptr16@CODE")` succeeds
    and would behave as `ptr16`. Judged on what the caller passed, before `types` supplies a
    spec."""
    if "@" in fmt:
        raise st.Invalid("bad_argument",
            f"fmt={fmt!r} names a pointer class, and `fmt` does not take one: a pointer's "
            "class is declared in the `types` file `start` was given (or the map's YAML) and "
            "read from there, never from this argument. Passing it here changed nothing and "
            "is refused rather than ignored. Use `fmt=\"ptr16\"` and type the symbol")


def check_fmt_width(width: int, fmt: str) -> int | None:
    """The width a named `fmt` resolves to beside `width`; None for `auto`."""
    if fmt == "auto":
        return None
    try:
        return vf.parse(fmt).width_for(width)
    except vf.FormatError as e:
        raise st.Invalid("bad_argument", str(e)) from None


@functools.cache
def capture_block_chars_max() -> int:
    """The widest decoded block a capture may print, computed lazily: `capture` is still
    importing this module when it is defined."""
    return max([capture.block_chars_max(vf.parse(f"{elem}[{SHOW_WATCH_MAX // size}]"), 0)
                for elem, (_code, size) in vf.SCALARS.items()]
               + [capture.block_chars_max(vf.parse(f"char[{SHOW_WATCH_MAX}]"), 0)])


# a format past the capture bound is long by construction; quoted whole it fills the line
FMT_SHOWN = 60


def shown_fmt(fmt: str) -> str:
    """`fmt` as a refusal or a row quotes it: whole up to `FMT_SHOWN`, else cut with `...`."""
    return fmt[:FMT_SHOWN] + "..." if len(fmt) > FMT_SHOWN else fmt


def capture_chars_past_bound(width: int, fmt: str) -> int | None:
    """The JSON characters of a capture's widest row under `fmt`, if past the refusal bound."""
    if not fmt or fmt == "auto":
        return None
    chars = capture.block_chars_max(vf.parse(fmt), width)
    return chars if chars > capture_block_chars_max() else None


def row_fmt(decl: dec.Declaration) -> str | None:
    """A watch row's `fmt`: cut by `shown_fmt` where its capture was refused, whole elsewhere."""
    if (decl.watch_mode == "capture" and decl.fmt and decl.width is not None
            and capture_chars_past_bound(decl.width, decl.fmt) is not None):
        return shown_fmt(decl.fmt)
    return decl.fmt


WATCH_BY = tuple(b for b in arming.BY_OPTIONS if b != "expr")


def check_watch_width(width: int, mode: str, fmt: str = "") -> None:
    """The ceiling on a watch's width, and for a capture its decoded row, judged once `fmt` is
    known."""
    limit = SHOW_WATCH_MAX if mode in ("show", "capture") else read.READ_MAX
    if width > limit:
        raise st.Invalid("bad_argument",
            f"length={width} is above {prose.counted(limit, 'byte')}: a region is `memdump`'s job")
    if mode == "capture" and (chars := capture_chars_past_bound(width, fmt)) is not None:
        raise st.Invalid("bad_argument",
            f"fmt={shown_fmt(fmt)!r}: its widest row decodes to "
            f"{chars} characters of JSON, past the {capture_block_chars_max()} the widest "
            "array a capture holds makes, which is what keeps `declaration_list(kind=\"watch\")`'s "
            "rows inside a "
            "reply: shorter field names, or fewer fields (the block's bytes are `raw_hex` in "
            "every row anyway)")


# the spaces this server drives are at most 32 bits wide
_WIDEST_ADDR = 0xFFFFFFFF


def wp_command(addr: int, length: int, cpu: str | None = None, condition: str = "") -> str:
    """The console command that arms a write watchpoint, halting only when `condition` holds."""
    return (f"wp {addr:#x}{console.cpu_suffix(cpu)},{length:#x},w"
            + (f",{condition}" if condition else ""))


def check_watch_add(ref: str, mode: str, length: int = 0, fmt: str = "auto",
                    by: str = "auto", condition: str = "", trigger: str = "",
                    space: str = "program", trigger_type: str = "w", **_: Any) -> None:
    """`watch_add`'s machine-independent half; resolving a pointer's base needs the table."""
    vocab.one_of("mode", mode, dec.WATCH_MODES)
    vocab.one_of("by", by, WATCH_BY)
    vocab.one_of("trigger_type", trigger_type, dec.COUNT_ACCESSES)
    if mode == "count":
        if trigger_type != "w" and space != mspace.PROGRAM:
            raise st.Invalid("bad_argument", "a count of reads taps a program address; "
                             "`space=\"io\"` counts a port's writes alone: `watch_add(ref=<port>, "
                             "mode=\"count\", space=\"io\")`")
    elif trigger_type == "rw":
        raise st.Invalid("bad_argument", f"trigger_type=\"rw\" on a {mode} watch: only a count "
                         "tallies both (`watch_add(mode=\"count\", trigger_type=\"rw\")`)")
    elif trigger_type == "r":
        # a read's trigger is its ref: with no block, naming it once is enough
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
    """A read capture holds the read and no block: Lua reading memory inside a read tap re-enters
    the bus, which MAME does not survive. A port's `in` is not captured."""
    if mode != "capture":
        raise st.Invalid("bad_argument", f"trigger_type=\"r\" on a {mode} watch: only a "
                                         "capture or a count takes a trigger type "
                                         "(`watch_add(ref=<trigger>, "
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




def _one_byte_scalars(fmt: vf.Format) -> bool:
    """Whether every scalar `fmt` reads is one byte, which has no order."""
    if fmt.kind == "struct":
        return all(_one_byte_scalars(field) for _name, field in fmt.fields)
    return fmt.kind == "string" or (fmt.elem is not None and vf.SCALARS[fmt.elem][1] == 1)


def decode_order(ses: gs.Session, cpu: str | None, fmt: str) -> str:
    """The order `fmt` decodes in on `cpu`; one-byte formats need none and read on any cpu."""
    if _one_byte_scalars(vf.parse(fmt)):
        return "little"
    return cpus.layout(ses, cpu).byte_order


def _value(raw: bytes, width: int, fmt: str, order: str) -> vf.Value:
    """`width` bytes read as `fmt` in the target's byte order."""
    return vf.parse(fmt).decode(raw, order, width)


def disarm_for_pass(ses: gs.Session) -> list[dec.Owner]:
    """Disarm every armed change watch for one pass, keeping the declarations: a watch on a byte
    written many times a frame would stop every later `run_to`."""
    disarmed: list[dec.Owner] = []
    for owner, armed in STATE.armed_watches.items():
        ses.monitor(mclear.clear_command("watch", armed["index"]))
        disarmed.append(owner)
    return disarmed


def rearm_after_pass(ses: gs.Session, refs: list[dec.Owner]) -> list[dec.Owner]:
    """Re-arm what `disarm_for_pass` disarmed on each cpu and read the rows back: the debugger
    numbers a re-armed row afresh. A ref the list no longer shows is marked disabled. A pointer
    watch already followed to a new place during the pass is taken as re-armed."""
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
    """Re-read the armed watches a write touched, so the next `before` is the post-write bytes."""
    for armed in STATE.armed_watches.values():
        if armed["cpu"] in (None, cpu) and mspace.ranges_meet(armed["addr"], armed["length"],
                                                              addr, n):
            armed["last"] = _read_exact(ses, armed["addr"], armed["length"], armed["cpu"])


def _read_exact(ses: gs.Session, addr: int, n: int, cpu: str | None = None) -> bytes:
    """`n` bytes at `addr` of `cpu`, or a refusal for a short answer: fewer bytes would decode to a
    number of the right shape and the wrong meaning. Another cpu is read through its thread."""
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
    """Follow a pointer ref against the machine now: the address (None for null, a state and not a
    watch at zero) and the `pointer` block showing how it was reached."""
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
    # a near pointer holds an offset in its target's segment, so it is placed under a class's
    # base, as `disassemble` places a direct operand. The class is the type's (`ptr16@CODE`),
    # else the base symbol's; an address base carries none and is taken as linear.
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
    if value == 0:
        return None, info
    target = (relocation or 0) + value + res.offset
    if not (relocation or 0) <= target < (1 << (8 * width)) + (relocation or 0):
        # the pointer's width bounds the space from the segment base; a place below zero would
        # reach the stub as a packet it cannot read
        raise gs.SessionError(f"the pointer plus the offset, {target:#x}, is outside what a "
                              f"{width}-byte pointer addresses"
                              + (f" under the {klass} base {relocation:#x}"
                                 if relocation is not None else ""))
    return target, info


def _class_base(klass: str, table: gs.SymbolTable) -> int:
    """The base a pointer typed into `klass` is placed under: `bases`, else the map's segment base.
    A class the table lacks is refused naming the ones it has."""
    based = table.bases.get(klass)
    if based is not None:
        return based
    seg = table.segment_bases.get(klass)
    if seg is not None:
        return seg
    carried = sorted(set(table.classes.values()))
    if klass in carried:
        # the class's rows share no `linear - offset` (a tile sheet as many blocks): no single base
        # is honest. A class already in `bases` cannot be fixed by any value there, so `bases` is
        # suggested only when it does not name the class.
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
            # the grammar cannot tell where the class ends: a typed target goes in braces
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
    """Where a change watch's values come from: `memory`, or `bus` when the read side differs from
    the write side, so the values are the writes the console logs."""
    return "memory" if read_maps_to == write_maps_to else "bus"


def _holder(records: dict[dec.Owner, dict[str, Any]], owner: dec.Owner,
            holds: Callable[[dict[str, Any]], bool]) -> str | None:
    """The ref of the other declaration on the same cpu whose record satisfies `holds`."""
    return next((r[0] for r, rec in records.items()
                 if r != owner and cpus.same_cpu(r[1], owner[1]) and holds(rec)), None)


def range_holder(records: dict[dec.Owner, dict[str, Any]], size_key: str,
                 owner: dec.Owner, addr: int, width: int) -> str | None:
    """The declaration whose record holds this very range: one tap is one range."""
    return _holder(records, owner, lambda rec: (rec["addr"], rec[size_key]) == (addr, width))


def overlap_holder(owner: dec.Owner, addr: int, width: int) -> str | None:
    """The declaration whose armed change watch shares a byte with this range (`_holder`)."""
    return _holder(STATE.armed_watches, owner,
                   lambda rec: mspace.ranges_meet(rec["addr"], rec["length"], addr, width))


def watch_aliased(owner: dec.Owner, addr: int, width: int,
                  clear_kind: mclear.ClearKind | None = "watch") -> arming.Refusal | None:
    """The refusal when another declaration arms a range sharing a byte; `start`'s re-arm passes no
    `clear_kind`."""
    other = overlap_holder(owner, addr, width)
    if other is None:
        return None
    return ("ambiguous_ref", f"{addr:#x} for {prose.counted(width, 'byte')} shares a byte with a "
            f"range already armed under {other!r}: "
            f"{mclear.one_declaration('watched range', other, clear_kind, owner[1])}")


def record_watch(owner: dec.Owner, row: dict[str, Any], maps_to: str,
                 read_maps_to: str | None) -> None:
    """What this session armed for `ref`. The console log is read from the first arm on; `last` is
    the bytes last seen and `last_wrote` the value last written, each being `before` at the next
    hit."""
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
    """The row of the debugger's list a change watch adopts, or the refusal when that row stops
    under another condition; sends and raises nothing. The owner's own row is asked first by the
    caller."""
    row = mlists.adoptable_row(held, addr, cpu, taken, width)
    if row is not None and (row.get("condition") or "") != condition:
        return None, mclear.another_condition("watch", addr, row, condition, width)
    return row, None


def _arm_change_watch(ses: gs.Session, owner: dec.Owner, addr: int, width: int,
                      condition: str = "") -> arming.Refusal | None:
    """Arm one change watch: map control, alias check, the `wp` unless the row is already listed,
    the read back, the record. Returns the refusal (code, prose) or None; `start`'s re-arm judges
    rows the same way but reads `wplist` once."""
    cpu = owner[1]
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
    """A change watch whose pointer moved: old row removed, new one armed and read back. `{from,
    to}` when it moved, with `why` when the move was refused and the old row kept."""
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
    """An `expr` watch, evaluated once before storing, so an unresolvable name is refused."""
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
    """Every declared expression, in declaration order."""
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
                         "`cpu_focus(cpu=...)` makes the one you name the visible one")


def watch_add(ses: gs.Session, ref: str, mode: str, width: int, fmt: str,
              by: str, cpu: str = "", condition: str = "", trigger: str = "",
              trigger_type: str = "w") -> dict[str, Any]:
    """The body of the `watch_add` tool."""
    running = arming.running_on_arrival(ses)
    check_watch_add(ref, mode, width, fmt, by, condition, trigger, trigger_type=trigger_type)
    if trigger_type == "r" and mode == "capture":
        # the read itself is the row: its byte at the trigger, the trigger defaulting to the ref
        width, fmt, trigger = 1, "u8", trigger or ref
    # an expr watch has no cpu: the console evaluates it on the visible one
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
        # the base is judged before the table-dependent rest, so a ref with no pointer to start
        # from (a stack local) is refused for that and not for a width
        probe = arming.resolve_decl(arming.declare("watch", "pointer", ref, on, width=1, fmt="u8",
                                       watch_mode="show"))
        if probe.state == "unresolved" and probe.why is not None:
            raise st.Invalid("unknown_ref", probe.why)
    if fmt == "auto":
        # the type comes from the table when none was given: a `type:`, a `types` file, or the
        # pointer field's format; else the widest unsigned scalar the width divides
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
    # stored as typed and substituted at each arming: a rebuild moves the symbols
    typed = condition.strip()
    cond = conditions.console_condition(typed, on) if typed else ""
    # an address trigger is kept in a ref's one spelling, so two spellings are one declaration
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
        # an address redeclared in another spelling is the same declaration, handled as stored
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
        # nothing a later build defines would give a stack local an address
        raise st.Invalid("unknown_ref", res.why)
    if cond and res.state != "unresolved":
        # judged before anything is stored: a stored null is armed by a later stop, with no call
        # left to refuse it in
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
        # a capture held on a name a rebuild dropped, declared again, is that declaration
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
            # a watch is stored only once armed, so this refusal leaves nothing behind
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
    # `armed` is the row's answer: a row listed DISABLED is not reported armed
    reply.update(stored=True, already_stored=not is_new, armed=armed["enabled"],
                 state=mlists.row_state(armed), index=armed["index"], entry=armed["entry"],
                 cpu=armed["cpu"],
                 write_maps_to=armed["maps_to"],
                 read_maps_to=or_unavailable(armed["read_maps_to"], mmap.NO_READ_SIDE_WHY),
                 values_from=armed["values_from"])
    return menvelope.envelope(st.add_note(reply, cpus.ignored_note(ses, armed["cpu"])))


def _watch_add_tap(ses: gs.Session, addr: int, width: int, decl: dec.Declaration,
                   reply: dict[str, Any]) -> dict[str, Any]:
    """A count or capture watch: `send_tap` judges and sends it, the declaration is stored once the
    send was taken. Arming moves nothing, so `altered` stays."""
    ref, cpu = decl.owner
    scratch = STATE.scratch
    assert scratch is not None
    # sent before stored: a declaration stored for an install that never went would read
    # `not_installed` for the wrong reason
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
    """A count range judged against the bus of `cpu`'s `space`: the refusal of one splitting a bus
    word, else None, with the note an install adds when the bus width is unknown."""
    bus_bits = cpus.bus_width(cpu, space)
    if bus_bits is not None and mspace.splits_bus_word(addr, width, bus_bits):
        return tally.split_why(addr, width, bus_bits, cpu, space), None
    unchecked = bus_bits is None and width > 1
    return None, tally.bus_unchecked_note(space) if unchecked else None


def size_watch(mode: str, width: int, fmt: str, typed: str | None,
               unsized: st.Invalid) -> tuple[int, str]:
    """A watch's width and format: `fmt` auto takes the table's type, else the widest scalar the
    length divides, else `unsized` is raised; then sized against the mode's bound."""
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
               unchecked: str | None, maps_to: str, read_maps_to: str | None,
               access: str = "w") -> dict[str, Any]:
    """A count watch's install sent, with the bus-word caveat and where an unmapped write goes."""
    sent = tally.send_install(scratch, owner, addr, width, space, access)
    st.add_note(sent, unchecked)
    sent["note"] = mmap.with_unmapped_note(sent["note"], maps_to, addr, space, read_maps_to)
    return sent


def send_capture(scratch: Path, owner: dec.Owner, addr: int, width: int, trigger: int,
                 src: capture.TapSource | None, space: str, maps_to: str,
                 trigger_read: str | None, trigger_type: str = "w") -> dict[str, Any]:
    """A capture's install sent; its note says where an unmapped trigger's writes go."""
    sent = capture.send_install(scratch, owner, addr, width, trigger, src, space, trigger_type)
    if trigger_type == "r":
        return sent
    sent["note"] = mmap.with_unmapped_note(sent["note"], maps_to, trigger, space, trigger_read,
                                           trigger=True)
    return sent


def send_tap(ses: gs.Session, scratch: Path, decl: dec.Declaration, addr: int,
             width: int) -> tuple[arming.Refusal | None, dict[str, Any]]:
    """Judge a count or capture tap and send its install, or the refusal (code, text), nothing sent.
    A count's range must not split a bus word and carries one tally; a capture's trigger resolves
    on its cpu, the trigger's write side is the one asked, and one block on one trigger carries one
    capture."""
    owner = decl.owner
    if decl.watch_mode == "count":
        split, unchecked = bus_word_split(addr, width, owner[1])
        if split is not None:
            return ("bad_argument", split), {}
        refused, maps_to, read_maps_to = _tally_write_side(ses, owner, addr, width,
                                                           "w" in decl.trigger_type)
        if refused is not None:
            return refused, {}
        sent = send_count(scratch, owner, addr, width, mspace.PROGRAM, unchecked, maps_to,
                          read_maps_to, decl.trigger_type)
        return None, {"write_maps_to": maps_to,
                      "read_maps_to": or_unavailable(read_maps_to,
                                                        mmap.NO_READ_SIDE_WHY), **sent}
    # a stored capture is judged as a declared one: `start` re-arms through here
    try:
        check_watch_width(width, "capture", decl.fmt or "")
    except st.Invalid as e:
        return ("bad_argument", str(e)), {}
    trigger = capture.trigger_addr(decl.trigger, STATE.table(owner[1]).table)
    if trigger is None:
        key = decl.trigger.strip().upper()
        twice = getattr(STATE.table(owner[1]).table, "ambiguous", {}).get(key)
        if twice is not None:
            return ("ambiguous_ref", prose.ambiguous_name(
                key, [f"{a:#x}" for a in twice], "this table")), {}
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
                f"{mclear.one_declaration('capture', other, 'watch', owner[1])}"), {}
    if reads:
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


def _tally_write_side(ses: gs.Session, owner: dec.Owner, addr: int, width: int,
                      writes: bool = True) -> tuple[arming.Refusal | None, str, str | None]:
    """The write side of a range about to be tallied, when writes are, and the one-tally-per-range
    rule."""
    refused, maps_to, read_maps_to = mmap.write_side(ses, addr, owner[1])
    if refused is not None and writes:
        return refused, maps_to, read_maps_to
    # a port's tally is in another space, so it holds no program range
    other = range_holder({r: rec for r, rec in STATE.tallies.items()
                           if rec["registry"] == tally.REGISTRY
                           and rec.get("space", mspace.PROGRAM) == mspace.PROGRAM},
                          "width", owner, addr, width)
    if other is not None:
        return (("ambiguous_ref", f"{addr:#x} for {prose.counted(width, 'byte')} already has a "
                 f"tally declared under {other!r}: "
                 f"{mclear.one_declaration('tally', other, 'watch', owner[1])}"),
                maps_to, read_maps_to)
    return None, maps_to, read_maps_to


def _tally_item(ses: gs.Session, decl: dec.Declaration, addr: int, frame: int | None,
                shown: int, at_stop: bool) -> dict[str, Any]:
    """What a survey or list says of a count or capture: the tap's account, else that none is
    recorded (a state, never an empty table)."""
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
    """A watch's bytes read now: available with `value` and `raw_hex`, or `unavailable` with the
    stub's refusal, never a zero. Its own field since `state` says where the watch is placed."""
    assert decl.width is not None and decl.fmt is not None
    # an unestablished byte order leaves the value unreadable with the reason
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
    """The state word a watch row takes from its declaration and resolution alone: `evaluated`,
    `null_pointer` or `unresolved`; None where arming decides (a change watch's placement, a tap's
    account, a stale build)."""
    if res.state == "expr":
        return "evaluated"
    if res.state == "unresolved" or (res.addr is None and res.state != "pointer"):
        return "null_pointer" if null else "unresolved"
    return "evaluated" if decl.watch_mode == "show" else None


def _change_placement(decl: dec.Declaration, held: list[dict[str, Any]],
                      addr: int) -> dict[str, Any]:
    """Where a change watch is placed against the debugger's list: its row's state, else `stale`,
    else `gone`."""
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
    """A change watch's placement against `wplist`; an unreadable list falls back to the record."""
    if isinstance(rows, gs.SessionError):
        armed = STATE.armed_watches.get(decl.owner)
        return {"state": mlists.row_state(armed) if armed is not None else "gone",
                "why": f"the debugger's `wplist` could not be read back ({rows}), so this "
                "is what this server armed"}
    return _change_placement(decl, rows, addr)


#: what a watch is at a stop: which, what it reads, where it stands and every alarm that
#: holds; the rest is `declaration_list(kind="watch")`'s
STOP_KEYS = ("ref", "cpu", "space", "state", "pointer", "reading", "total", "since_last_stop",
             "reset", "why", "moved", "callback_errors")
#: alarms a tap's row carries whether or not they hold; a stop keeps each only while it does
_STOP_ALARM_WHEN: dict[str, Callable[[Any], bool]] = {
    "superseded": bool, "install_resent": bool, "across": bool, "pending": bool,
    "installed": lambda v: v is not True}
STOP_HOW = ("`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the "
            "debugger's row for it, "
            "and a count's or a capture's tables")


def at_stop(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """`rows` as a stop shows them (`STOP_KEYS`), and the names of the keys left out of any."""
    short, left = [], set()
    for row in rows:
        # a pointer's row keeps where it read: the armed place may differ after a refused move
        kept = {k: v for k, v in row.items()
                if k in STOP_KEYS or (k in _STOP_ALARM_WHEN and _STOP_ALARM_WHEN[k](v))
                or (k == "addr" and "pointer" in row)}
        left |= row.keys() - kept.keys()
        short.append(kept)
    return short, sorted(left)


def place_after_pass(ses: gs.Session, rows: list[dict[str, Any]],
                     refs: list[dec.Owner]) -> None:
    """Place again the rows a pass left `gone`, with one `wplist` read after the re-arm."""
    decls = {(d.ref, d.cpu): d for d in arming.store().declarations()
             if d.kind == "watch" and d.watch_mode == "change" and d.owner in refs}
    held: list[dict[str, Any]] | gs.SessionError | None = None
    for row in rows:
        cpu = row.get("cpu")
        decl = decls.get((str(row.get("ref")), cpu if isinstance(cpu, str) else None))
        if decl is None or row.get("state") != "gone":
            continue
        if held is None:
            held = _wplist_or_error(ses)
        placed = _placement(held, decl, int(STATE.armed_watches[decl.owner]["addr"]))
        row.update({k: v for k, v in placed.items() if k in STOP_KEYS})


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
            # where it points now when the machine can be asked, else where it was armed
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
        assert res.addr is not None
        if word == "evaluated":
            item["addr"], item["state"] = st.hex_addr(res.addr), word
            if not ses.running:
                item["reading"] = _reading(ses, decl, res.addr, cpu=decl.cpu)[0]
        elif decl.watch_mode == "count":
            item.update(_tally_item(ses, decl, res.addr, None, tally.BUCKETS_MAX, at_stop=False))
        elif decl.watch_mode == "capture":
            # the first rows only: every row is a whole block; `rows_path` holds the whole record
            item.update(_tally_item(ses, decl, res.addr, None, st.ROWS_SHOWN, at_stop=False))
        else:
            item["addr"] = st.hex_addr(res.addr)
            item.update(_change_placement(decl, held, res.addr))
            armed = STATE.armed_watches.get(decl.owner)
            if "entry" in item and armed is not None:
                item["values_from"] = armed["values_from"]
        out.append(item)
    return out


def list_watches(ses: gs.Session, cpu: str = "") -> dict[str, Any]:
    """The body of the `declaration_list(kind="watch")` tool: every declaration, or with `cpu` those
    placed on it."""
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
    reply["cpu"] = or_unavailable(only, st.NO_CPU_NAMED_WHY)
    # a removal is read, never resent, because its declaration is already gone; what it finds
    # stuck rides on every reply's session block (`tallies_not_removed`)
    if STATE.scratch is not None:
        mtap.read_removal_answers(STATE.scratch)
    if ses.running:
        reply["last_stop"] = STATE.as_of()
    return menvelope.envelope(reply)


_SEG_OFF = re.compile(r"(?:0[xX])?[0-9a-fA-F]+:(?:0[xX])?[0-9a-fA-F]+")
_ONE_TOKEN = re.compile(r"[\w.$#]+")


def check_clear_watches(ref: str = "", all: bool = False, space: str = mspace.PROGRAM,
                      **_: Any) -> None:
    """`declaration_clear(kind="watch")`'s machine-independent half: one `ref` or `all=True`, a port
    named by `space` and never by a suffix, a `ref` judged by the shape `watch_add` judged."""
    declaration_rows.check_clear_scope(ref, all, "watch")
    vocab.one_of("space", space, mspace.SPACES)
    if all:
        if space != mspace.PROGRAM:
            raise st.Invalid("bad_argument", f'space="{space}" names where a `ref` is, and '
                             "`all` clears every watch in every space: "
                             "`declaration_clear(kind=\"watch\", all=True)` "
                             "with no `space`")
        return
    text = ref.strip()
    tail = mspace.suffix(mspace.IO)
    if text.lower().endswith(tail):
        raise st.Invalid("bad_argument", f"ref={ref!r} carries its space in its text: a port is "
                         'its `ref` with `space="io"` (`declaration_clear(kind="watch", '
                         f'ref="{text[:-len(tail)]}", '
                         'space="io")`)')
    if (pr := vf.parse_pointer(text)) is not None:
        inputs.zero_x(pr.base, "base")
        inputs.check_pointer_offset(text)
    elif _SEG_OFF.fullmatch(text):
        inputs.check_ref(text)
    elif _ONE_TOKEN.fullmatch(text):
        inputs.zero_x(text)


def clear_watches(ses: gs.Session, ref: str, cpu: str = "", all_: bool = False) -> dict[str, Any]:
    """The body of the `declaration_clear(kind="watch")` tool, on every cpu or on `cpu` alone."""
    check_clear_watches(ref=ref, all=all_)
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
            # the removal is sent like the install; the record and the dump go now
            if STATE.scratch is not None and (gone := mtap.send_remove(STATE.scratch,
                                                                       decl.owner)):
                tallies_removed.append(gone)
            continue
        armed = STATE.armed_watches.get(decl.owner)
        if armed is not None:
            rows.append((decl.owner, str(armed["entry"]), int(armed["index"])))
    # the record goes only once the list no longer shows the row, or the next hit would read
    # as foreign
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
    """Every declared expression's value in one `print`, or the console's refusal."""
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
    """Every watch declaration evaluated at this stop: its bytes rendered, or why it has none; what
    is read is also `before` at the next hit. `fresh` holds bytes read at this same stop,
    `expressions` the expr values if already printed, `frame` the stop's, for a count's dump."""
    if STATE.store is None:
        return []
    fresh = fresh or {}
    if expressions is None:
        expressions = evaluate_expressions(ses)
    wp_rows: list[list[dict[str, Any]] | gs.SessionError] = []

    def place(decl: dec.Declaration, addr: int) -> dict[str, Any]:
        """A change watch's placement, `wplist` asked once per survey."""
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
            # re-resolved at every stop, since the pointer moves: a change watch is moved with it
            try:
                target, info = chase(ses, res)
            except gs.SessionError as e:
                # unreadable: placed where it was armed
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
                # a refused move leaves the watch armed where it was, so that place is read
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
        assert res.addr is not None
        if decl.watch_mode in dec.TAP_MODES:
            item.update(_tally_item(ses, decl, res.addr, frame, st.ROWS_SHOWN,
                                    at_stop=True))
            out.append(item)
            continue
        armed = STATE.armed_watches.get(decl.owner)
        if armed is not None and armed["values_from"] == "bus":
            # a write-only register is never read: its value is the last one written
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


# the writer part of a stop's `cause` in both spellings composed here, so a count keys the
# watch and not each writer
_CAUSE_WRITER = re.compile(
    rf"(?:, wrote [0-9a-f]+)? by (?:pc 0x[0-9a-f]+|{re.escape(_NO_WRITER)})")


def cause_key(cause: str) -> str:
    """`cause` with the writer taken off: the key for counting stops by watch."""
    return _CAUSE_WRITER.sub("", cause, count=1)


def _foreign_cause(line: re.Match[str]) -> str:
    """How a stop by a watchpoint this server did not arm is named from the console's line."""
    at, pc = st.hex_addr(int(line.group(3), 16)), _writer(line)
    by = f"by pc {pc}" if pc else f"by {_NO_WRITER}"
    return mclear.foreign_row_cause("watch", int(line.group(1), 16),
                                    f" at {at} this server did not arm, "
                                    f"wrote {line.group(2).lower()} {by}")


#: Why a watch_hit's `before` is not a value: no earlier reading to compare with.
_NO_BEFORE_MEMORY = ("no value was read before this write: the watch's bytes are read at each "
                     "stop, and none was read since it was armed")
_NO_BEFORE_BUS = "the first write logged since the watch was armed: no earlier write to compare"


def stop_line_in(lines: list[str]) -> bool:
    """Whether the console logged a watchpoint stop among `lines`."""
    return any(_STOP_LINE.search(ln) for ln in lines)


def watch_packet_addr(ses: gs.Session) -> int | None:
    """The address a watchpoint's stop packet names, or None when the last stop was not one."""
    m = _WATCH_PACKET.match(getattr(ses, "last_stop_packet", "") or "")
    return int(m.group(1), 16) if m else None


def watch_stop(ses: gs.Session, since: list[str]
               ) -> tuple[str, dict[str, Any] | None, dict[dec.Owner, bytes]] | None:
    """When the last stop was a watchpoint's: `cause`, the attribution and the bytes read for it.
    The attribution is the console's line by the watchpoint's index in `since`, with every line
    of that index and the bytes seen before and now. A foreign watch is named by its line. The
    packet names no row; it matters only when the console logged no line."""
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
        return (_foreign_cause(newest), None, {})
    ref = owner[0]
    armed = STATE.armed_watches[owner]
    decl = next((d for d in arming.store().declarations()
                 if d.kind == "watch" and d.owner == owner), None)
    if decl is None:
        # the row outlived its declaration: the removal was sent, the debugger kept the row, and the
        # record stayed so this stop can be named
        return (f"watch {ref}: {st.hex_addr(armed['addr'])} written, cleared while the "
                f"debugger still listed its row; {mclear.pasted_clear('watch', armed['index'])} "
                "removes it",
                None, {})
    assert decl.width is not None and decl.fmt is not None
    hit: dict[str, Any] = {"ref": ref, "addr": st.hex_addr(armed["addr"]), "cpu": armed["cpu"],
                           "index": armed["index"]}
    if decl.condition:
        # the console logs a conditioned row's stop only when the condition held
        conditions.typed_condition(hit, decl)
    # every line of this watchpoint since the previous stop: a 68000 writes a long as two words
    lines = [(ln.strip(), mm) for ln in since
             if (mm := _STOP_LINE.search(ln)) is not None
             and int(mm.group(1), 16) == armed["index"]]
    writes: list[dict[str, Any]] = [{"wrote": f"0x{mm.group(2).lower()}",
                                     "to": st.hex_addr(int(mm.group(3), 16)),
               "pc": or_unavailable(_writer(mm), _NO_WRITER)} for _ln, mm in lines]
    # the last writes are kept: the one that stopped the machine is the last
    hit.update(writes_total=len(writes), truncated=len(writes) > WRITES_MAX)
    writes = writes[-WRITES_MAX:]
    hit.update(writer_pc=writes[-1]["pc"], writes=writes)
    by = f"pc {writes[-1]['pc']}" if isinstance(writes[-1]["pc"], str) else _NO_WRITER
    cause = f"watch {ref}: {st.hex_addr(armed['addr'])} written by {by}"
    hit["values_from"] = armed["values_from"]
    fresh: dict[dec.Owner, bytes] = {}
    if armed["values_from"] == "bus":
        # the values are the writes: a memory read would answer the read side
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
                hit["before"] = unavailable(str(e))
    hit["lines"] = [ln for ln, _mm in lines]
    # a watch re-armed at `start` from an earlier session says so in the stop itself
    if decl.origin is not None and decl.origin != STATE.session_origin:
        hit["rearmed"] = True
        cause += arming.inherited(decl)
    return cause, hit, fresh
