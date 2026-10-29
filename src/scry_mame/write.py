"""The WRITE family: bytes, a register, a reset, and the console itself."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from scry_core import judges
from scry_core.reply_contract import or_unavailable, unavailable

from scry_mame import (
    capture,
    console,
    cpus,
    cycles,
    files,
    inputs,
    lexer,
    read,
    regpoints,
    running,
    savestates,
    watches,
)
from scry_mame import clear as mclear
from scry_mame import declarations as dec
from scry_mame import envelope as menvelope
from scry_mame import focus as mfocus
from scry_mame import gdb_session as gs
from scry_mame import map as mmap
from scry_mame import region as rom_region
from scry_mame import state as st
from scry_mame import tap as mtap
from scry_mame.state import STATE

# Above DEBUG_MAX characters a `debug` answer goes to a file in the scratch; the reply keeps
# a preview and the path.
DEBUG_MAX = 4000
DEBUG_PREVIEW = 160

# `readback` and `verified` are the point: a ROM write on a 68000 board answers
# `bytes_written: 4` while the memory keeps its old bytes.
def write(ses: gs.Session, scratch: Path, ref: str, data_hex: str, cpu: str = "",
          region: bool = False) -> dict[str, Any]:
    """The body of the `write` tool: through the cpu's program space, or with `region` into the
    memory region behind a ROM address (`region`), read back through the cpu either way."""
    # The hex is judged before the ref so the surface can ask without a machine.
    data = check_write(data_hex, ref)
    on, thread = cpus.thread_for(ses, cpu)
    addr = STATE.resolve(ref, on)
    read.space_bound(addr, len(data), on)
    placed: dict[str, Any] = {}
    if region:
        # A plain write that lands nowhere is explained, never re-sent into the region.
        placed = rom_region.write(ses, scratch, addr, data, on,
                                  mmap.memory_kind(ses, addr, on))
        # A capture reading this block would show the table change with nothing saying why.
        if readers := capture.reading_region(placed["region"], placed["region_offset"],
                                             len(data)):
            placed["captures_reading_it"] = readers
    else:
        ses.write(addr, data, thread=thread)
    try:
        readback = ses.read(addr, len(data), thread=thread)
    except gs.SessionError as e:
        return _after_write_failed(ses, e, "reading the write back",
                                   "The write was sent and what landed was not read",
                                   addr=st.hex_addr(addr), bytes_written=len(data), **placed)
    # A write is a survey of those bytes: a watch's `before` must not stay stale.
    landed = {"addr": st.hex_addr(addr), "bytes_written": len(data), "readback": readback.hex(),
              "verified": readback == data,
              "cpu": or_unavailable(on, NO_WRITE_CPU_WHY), **placed}
    if not landed["verified"] and not region:
        try:
            landed |= rom_target(ses, addr, on, len(data))
        except gs.SessionError as e:
            return _after_write_failed(ses, e, "asking the console's `map` why it did not read "
                                       "back", "The write was sent and read back unverified",
                                       **landed)
    try:
        watches.refresh_baselines(ses, addr, len(data), on)
    except gs.SessionError as e:
        return _after_write_failed(ses, e, "re-reading a watched range after the write",
                                   "The write landed and read back", **landed)
    return menvelope.envelope(landed)


#: A write's `cpu` when the console's `cpulist` named none.
NO_WRITE_CPU_WHY = "`cpulist` named no cpu the write went to"


def rom_target(ses: gs.Session, addr: int, cpu: str | None, n: int) -> dict[str, Any]:
    """Why a write that did not read back went nowhere, when the reason is ROM: `target`, a
    `note`, and the region and offset behind the address when the cached map can say
    (`region.unwritable`). Asked only on the failing path."""
    if mmap.memory_kind(ses, addr, cpu) != "rom":
        return {}
    here = rom_region.place(addr, cpu)
    reply: dict[str, Any] = {"target": "rom"}
    if here.region is not None:
        reply["region"] = here.region
    if here.offset is not None:
        reply["region_offset"] = here.offset
    fits = rom_region.unwritable(here, n) is None
    hint = "; `region=True` writes them there" if fits else ""
    reply["note"] = (f"the program space has no write side at {addr:#x}: it is ROM, so the "
                     f"bytes went nowhere; {here.where}{hint}")
    return reply


def _after_write_failed(ses: gs.Session, error: gs.SessionError, what: str, tail: str,
                        **fields: Any) -> dict[str, Any]:
    """A request after the write failed. A refusal keeps the channel, so the session serves
    (`readback_refused`); anything else leaves nothing to pair a reply with (`session_broken`)."""
    if not isinstance(error, gs.Refused):
        return running.session_broke(ses, error, what, tail, **fields)
    return menvelope.invalid("readback_refused",
                             f"the write went out, then {what} was refused: {error}. {tail}; the "
                             "session still serves", **fields)


def check_write(data_hex: str, ref: str = "", **_: Any) -> bytes:
    """`write`'s machine-independent half, handing back the bytes so the body parses once."""
    inputs.check_ref(ref)
    data = read.hex_bytes("data_hex", data_hex, verb="write")
    # The bytes cross the conversation as hex twice (call and readback); a larger image is a
    # file's job.
    inputs.count("the byte count of data_hex", len(data), read.READ_MAX,
                   ": a larger block is loaded from a file through `debug(\"load ...\")`")
    return data


def check_set_register(name: str, value: int, **_: Any) -> None:
    """`set_register`'s machine-independent half; the width check needs the machine."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise st.Invalid("bad_argument", f"a register value is an integer; got {value!r}")
    if value < 0:
        raise st.Invalid("bad_argument",
            f"value={value} is negative, and a register holds an unsigned value")


def set_register(ses: gs.Session, name: str, value: int, cpu: str = "") -> dict[str, Any]:
    """The body of the `set_register` tool, with the readback `write` makes."""
    check_set_register(name, value)
    on, thread = cpus.thread_for(ses, cpu)
    lay = cpus.described(ses, on, thread)
    # Name and width are judged about the argument: a refusal, not a broken session.
    try:
        register = lay.register_name(name)
        bits = lay.register_width(register)
    except gs.SessionError as e:
        raise st.Invalid("bad_argument", str(e)) from None
    if value >= 1 << bits:
        raise st.Invalid("bad_argument",
            f"{register} is {bits} bits on this cpu and {value:#x} does not fit it")
    ses.set_reg(name, value, thread=thread)
    back = ses.reg(name, thread=thread)
    return menvelope.envelope({"register": register, "value": judges.hex_at_width(value, bits),
                               "readback": judges.hex_at_width(back, bits),
                               "verified": back == value,
                               "cpu": or_unavailable(on, st.NO_CPU_READ_WHY)})


# The reset is scheduled: right after the call the PC is unchanged until the machine runs.
def reset(ses: gs.Session, scratch: Path) -> dict[str, Any]:
    """The body of the `reset` tool: a soft reset read back against the pc `start` parked at.
    There is no hard one: it kills the gdbstub connection, which is `close` and `start`."""
    pc = ses.reset()
    across = mtap.mark_across("softreset")
    boot = STATE.boot_pc
    # The step that applies the reset is a stop and is recorded, or the next call finds it as an
    # unexplained one. The frame counter does not restart on a soft reset: a caller subtracts
    # `frame_at_reset`.
    seen = running.survey(ses, scratch)
    return running.finish_stop(ses, seen, "softreset",
                               kind="softreset", pc=st.hex_addr(pc),
                               boot_pc=st.hex_addr(boot) if boot is not None else
                               unavailable("`start` read no pc at its park"),
                               verified=boot is not None and pc == boot,
                               frame_at_reset=st.frame_shown(seen["frame"]),
                               **({"taps_across": across} if across else {}))


def clip_text(output: str, scratch: Path, stem: str) -> dict[str, Any]:
    """Text of no known shape, bounded by characters: whole below the ceiling, else a file in
    the scratch (`<stem>-N.txt`) plus a preview, `output_chars` and `output_path`."""
    if len(output) <= DEBUG_MAX:
        return {"output": output, "clipped": False}
    path = scratch / f"{stem}-{STATE.next_number('debug_dumps')}.txt"
    path.write_text(output, encoding="utf-8", newline="")    # as printed, never CRLF
    preview = output.split("\n", 1)[0][:DEBUG_PREVIEW]
    return {"output": preview + "...", "output_chars": len(output), "output_path": str(path),
            "clipped": True}




# The console's three clears and the forget that follows each.
_CLEARS: dict[str, Callable[[gs.Session], list[dec.Owner]]] = {
    "bpclear": lambda ses: mclear.forget_rows_gone(ses, "breakpoint"),
    "wpclear": lambda ses: mclear.forget_rows_gone(ses, "watch"),
    "rpclear": lambda ses: regpoints.forget_gone(ses),
}


def _mark_counter(ses: gs.Session, commands: list[str]) -> None:
    """Mark `totalcycles` stale after the last of `commands` that leaves it so (`cycles`)."""
    if stale := [name for one in commands if (name := console.stale_counter_command(one))]:
        cycles.mark_stale_counter(ses, stale[-1])


def check_debug(command: str = "", **_: Any) -> None:
    """`debug`'s machine-independent half: a `hardreset` re-creates the machine and kills the
    stub's connection, so it is refused before anything is sent."""
    if any(console.command_name(one.strip()) == "hardreset"
           for one in console.console_commands(command)):
        raise st.Invalid("bad_argument",
                         f"{command!r} holds a `hardreset`, which re-creates the machine and "
                         "closes the stub's connection with it: `close` then `start` is the "
                         "same reset, and `reset` the soft one")


def debug(ses: gs.Session, scratch: Path, command: str) -> dict[str, Any]:
    """The body of the `debug` tool, judging every command of the line as `mutates` does."""
    check_debug(command)
    commands = [one.strip() for one in console.console_commands(command)]
    names = [console.command_name(one) for one in commands]
    releases = any(console.releases(one) for one in commands)
    # Read the live cpu before a line that can ignore it: MAME then runs until another cpu
    # executes.
    was = live = None
    if any(console.sets_cpus(one) for one in commands):
        was = cpus.visible_cpu(ses)
        live = cpus.live_cpu(ses) or was
    window = STATE.run_release
    if releases:
        ses.console_packet(command)
        running.mark_release(ses)
    mark = files.log_mark(scratch)
    try:
        output = ses.monitor(command)
    except gs.SessionError:
        # Sent and not answered: whether it wrote is unknown, so count it, cautiously.
        if console.mutates_any(commands):
            STATE.console_writes += 1
        _mark_counter(ses, commands)
        raise
    # What a parse error stopped never ran: it and what follows are left out of the writes, the
    # release and the cpu setters. A command refused while it ran stays counted.
    refusal = console.refusals(command, output)
    skipped = refusal.skipped() if refusal is not None else set()
    ran_cmds = [one for k, one in enumerate(commands) if k not in skipped]
    # The record of a row the list no longer shows goes now, once per family in the order
    # cleared; the list is read even for a refused clear.
    writes = console.mutates_any(ran_cmds)
    if writes:
        STATE.console_writes += 1  # before the forgets, whose reads can fail
    for name in dict.fromkeys(n for n in names if n in _CLEARS):
        _CLEARS[name](ses)
    reply: dict[str, Any] = {"command": command, "mutates": writes}
    notes = []
    if releases and not any(console.releases(one) for one in ran_cmds):
        # The release never ran: restore the window `mark_release` replaced.
        releases = False
        STATE.run_release = window
    if releases:
        ses.running = True
        STATE.console_run = True
        notes.append("the console released the machine: the readers refuse until it stops "
                     "(a breakpoint, `stop`), and the stop is proved on the frame counter")
    # A save or load MAME held is completed as `state_write` completes its own, before the
    # counter is read, and recorded as a stop. A refusal still marks the counter.
    if not releases:
        try:
            held = savestates.complete_held(ses, scratch, mark, command)
        except st.Invalid:
            if not console.refused_rewind(ran_cmds, output):
                _mark_counter(ses, ran_cmds)
            raise
        if held is not None:
            record = running.record_stop(ses, scratch, f"debug: {command}")
            notes.append(f"{held} (stop {record['seq']}, `status`'s `last_stop`)")
    # A load, rewind or reset the line ran leaves `totalcycles` stale, unless the line ran the
    # machine or the console refused the rewind.
    if not releases and not console.refused_rewind(ran_cmds, output):
        _mark_counter(ses, ran_cmds)
    _restart_assigned(ran_cmds)
    notes.extend(_controls_assigned(ran_cmds))
    if any(console.sets_cpus(one) for one in ran_cmds) and not releases:
        ignored = cpus.ignored(ses)
        # The line ignored the live cpu: MAME runs until another executes, so read the visible
        # cpu after.
        ran = live is not None and live in (ignored or [])
        visible = mfocus.settled_visible(ses, ignored or []) if ran else cpus.visible_cpu(ses)
        reply["visible_cpu"] = or_unavailable(
            visible, "no stop was read after the run the line started, so no cpu is visible yet"
            if ran else "`cpulist` marked no cpu visible")
        reply["ignored"] = or_unavailable(ignored, "`ignore` answered neither of its shapes")
        if ran and visible is None:
            ses.running = True
            STATE.console_run = True
            notes.append(f"the line ignored {live}, the cpu MAME was live on, which released "
                         "the machine until another cpu executes, and no stop was read: the "
                         "readers refuse until it stops (`stop`)")
        elif ran:
            record = running.record_stop(ses, scratch, f"debug: the console ignored {live} and "
                                         f"ran until {visible} executed")
            notes.append(f"the line ignored {live}, the cpu MAME was live on, so it ran until "
                         f"{visible} executed, and that stop is recorded (stop "
                         f"{record['seq']}, `status`'s `last_stop`); `focus` shows a cpu "
                         "without a run on a build whose stub serves a thread per cpu")
        elif visible in (ignored or []):
            notes.append(f"the visible cpu, {visible}, is ignored and was not live, so nothing "
                         "ran: a row on it has no effect until it is observed")
        elif ignored is None:
            notes.append("the console's `ignore` answered neither of its shapes, so whether "
                         "this line released the machine was not judged")
    st.add_note(reply, *notes)
    fields = {**reply, **clip_text(output, scratch, "debug")}
    if refusal is None:
        return menvelope.envelope(fields)
    # The console's own error refuses the argument in its words, keeping the whole answer.
    return menvelope.invalid("bad_argument", console.refusal_message(command, refusal), **fields,
                             **refusal.fields(commands))


def _assigned_now(commands: list[str]) -> set[int]:
    """The temps a line assigns as it runs, not in a row it arms for later."""
    return set().union(*(lexer.temps_assigned(one) for one in commands
                         if not console.evaluated_later(one)))


def _restart_assigned(commands: list[str]) -> None:
    """A control whose temp a line assigns now restarts from the written value."""
    now = _assigned_now(commands)
    for c in STATE.controls.values():
        if c["temp"] in now:
            c["missed"] = 0


def _controls_assigned(commands: list[str]) -> list[str]:
    """One note for the controls whose temp the line assigns now, one for those a row it arms
    assigns at each evaluation."""
    def named(found: set[int]) -> str:
        return ", ".join(f"{ref}{f' on {cpu}' if cpu else ''} (temp{c['temp']})"
                         for (ref, cpu), c in STATE.controls.items() if c["temp"] in found)

    now = _assigned_now(commands)
    armed = set().union(*(lexer.temps_assigned(one) for one in commands
                          if console.evaluated_later(one)))
    notes = []
    if named(now):
        notes.append(f"this line assigns the counter of {named(now)}: "
                     "`declaration_list(kind=\"breakpoint\")`'s "
                     "`hits_since_armed` now counts on from the value written (-1 makes the "
                     "control halt at its next hit), and a run's `control_hits`, taken across "
                     "the run, does not see it")
    if named(armed):
        notes.append(f"a row this line arms assigns the counter of {named(armed)} each time "
                     "it is evaluated, so `control_hits` and `hits_since_armed` count those writes")
    return notes
