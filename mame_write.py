"""The WRITE family: bytes, a register, a reset, and the console itself.

Everything here CHANGES the machine, or can, and every reply after it says so through
`altered`: `write` and `set_register` read back what landed, because a count of what was
sent is not a measurement of what changed; `reset` schedules a reset the machine takes when
it next runs; and `debug` is the door to the whole console, judged by the console's grammar
(`mame_console`: which commands write or release, and which the console refused), erring on
the cautious side because under-marking costs a false measurement presented as a good one.
The contracts (the docstrings the client reads) stay with the registrations in `server.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import gdb_session as gs
import mame_capture as capture
import mame_clear as mclear
import mame_console as console
import mame_cpus as cpus
import mame_cycles as cycles
import mame_declarations as dec
import mame_envelope as menvelope
import mame_files as files
import mame_focus as mfocus
import mame_inputs as inputs
import mame_lexer as lexer
import mame_map as mmap
import mame_read as read
import mame_region as rom_region
import mame_regpoints as regpoints
import mame_running as running
import mame_savestates as savestates
import mame_state as st
import mame_tap as mtap
import mame_watches as watches
from mame_state import STATE

# CEILINGS ON WHAT CROSSES INTO THE CONVERSATION, the console's half: `debug` answers text
# of no known shape, so above this many characters the whole answer goes to a file in the
# scratch and the reply carries a bounded preview and the path. The readers' ceilings sit
# with the readers, in `mame_read`.
DEBUG_MAX = 4000
DEBUG_PREVIEW = 160

# `readback` AND `verified` ARE THE POINT. `bytes_written: 4` alone is a count of what was SENT and
# not of what landed: on a 68000 board, a write to a ROM address answers `bytes_written: 4` while
# the memory still holds its old bytes, and the caller has no way to know. A false green in
# exactly the shape the exit-code rule is about, produced by
# our own tool.
def write(ses: gs.Session, scratch: Path, ref: str, data_hex: str, cpu: str = "",
          region: bool = False) -> dict[str, Any]:
    """The body of the `write` tool: through the cpu's program space, or with `region` into the
    memory region behind a ROM address (`mame_region`), read back through the cpu either way."""
    # THE HEX BEFORE THE REF, which is the other way round from how this read. Resolving `ref`
    # needs the machine; judging the hex does not, so judging it first is what lets the surface ask
    # the same question before it has a machine at all -- and the caller is told about the argument
    # they got wrong rather than about a symbol they may have got right.
    data = check_write(data_hex, ref)
    on, thread = cpus.thread_for(ses, cpu)
    addr = STATE.resolve(ref, on)
    read.space_bound(addr, len(data), on)
    placed: dict[str, Any] = {}
    if region:
        # NEVER DIVERTED THE OTHER WAY: a plain write that lands nowhere is explained, not
        # re-sent into the region, so what the caller asked for is what was done.
        placed = rom_region.write(ses, scratch, addr, data, on,
                                  mmap.memory_kind(ses, addr, on))
        # A CAPTURE READS ITS BLOCK OFF THE BUS, as this write lands: its rows would show the
        # table change between two of them with nothing saying why.
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
    # A WRITE BY THIS SERVER IS A SURVEY OF THOSE BYTES: a watch's `before` is what the
    # previous survey saw, and a forced value the watch never saw made the next stop report
    # the value at arm time as what the writer read.
    landed = {"addr": st.hex_addr(addr), "bytes_written": len(data), "readback": readback.hex(),
              "verified": readback == data,
              "cpu": st.or_unavailable(on, NO_WRITE_CPU_WHY), **placed}
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
        # The write has landed by now, and the refusal still says what landed.
        return _after_write_failed(ses, e, "re-reading a watched range after the write",
                                   "The write landed and read back", **landed)
    return menvelope.envelope(landed)


#: A write's `cpu` when the console's `cpulist` named none.
NO_WRITE_CPU_WHY = "`cpulist` named no cpu the write went to"


def rom_target(ses: gs.Session, addr: int, cpu: str | None, n: int) -> dict[str, Any]:
    """Why a write to `cpu` that did not read back went nowhere, when the reason is ROM: `target`
    and a `note`, plus the memory REGION that backs the address and the offset into it when the
    address map `start` cached can say which, and a pointer to `region=True` when its `n` bytes
    fit there (`mame_region.unwritable`). Nothing for any other kind of memory, where
    `verified: false` has causes this cannot tell apart. Asked only on the failing path, so a
    write that reads back pays no extra round trip."""
    # ONE CPU: the console's `map` is asked of the cpu the write went to, named in it, and the
    # region is placed on that cpu's map (`mame_region.place`).
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
    """A request after the write that failed (the read-back, a watched range re-read, the
    `map` asked why). A REFUSAL is an answer, so the channel kept its place and the session
    still serves: `readback_refused`. Anything else (a request that ran out, a connection
    gone, an answer out of place) leaves nothing to pair a reply with: `session_broken`,
    latched as every other."""
    if not isinstance(error, gs.Refused):
        return running.session_broke(ses, error, what, tail, **fields)
    return menvelope.invalid("readback_refused",
                             f"the write went out, then {what} was refused: {error}. {tail}; the "
                             "session still serves", **fields)


def check_write(data_hex: str, ref: str = "", **_: Any) -> bytes:
    """`write`'s machine-independent half, handing back the bytes so the body parses once.
    Resolving `ref` is the machine's; the hex is not."""
    inputs.check_ref(ref)
    data = read.hex_bytes("data_hex", data_hex, verb="write")
    # THE SAME CEILING AS A READ, for the same reason: the bytes cross the conversation as hex
    # twice, once in the call and once in its `readback`. A larger image is a file's job.
    inputs.count("the byte count of data_hex", len(data), read.READ_MAX,
                   ": a larger block is loaded from a file through `debug(\"load ...\")`")
    return data


def check_set_register(name: str, value: int, **_: Any) -> None:
    """`set_register`'s machine-independent half, and only that half. A register holding an
    unsigned value is true of every cpu; whether THIS cpu has a register by that name, and how
    many bits wide it is, only the machine can say, so the width check stays past the gate."""
    # Two refusals that tell a type from a sign, which one `inputs.natural` sentence would merge.
    if isinstance(value, bool) or not isinstance(value, int):
        raise st.Invalid("bad_argument", f"a register value is an integer; got {value!r}")
    if value < 0:
        raise st.Invalid("bad_argument",
            f"value={value} is negative, and a register holds an unsigned value")


def set_register(ses: gs.Session, name: str, value: int, cpu: str = "") -> dict[str, Any]:
    """The body of the `set_register` tool: the same readback `write` makes, since a register
    that masks the write or answers something else came back looking forced."""
    check_set_register(name, value)
    on, thread = cpus.thread_for(ses, cpu)
    lay = cpus.described(ses, on, thread)
    # The client judges the name and the width before a byte reaches the stub, and its
    # judgement is about the ARGUMENT: it is answered as a refusal, not as a broken session.
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
    return menvelope.envelope({"register": register, "value": read.hex_at_width(value, bits),
                               "readback": read.hex_at_width(back, bits),
                               "verified": back == value,
                               "cpu": st.or_unavailable(on, st.NO_CPU_READ_WHY)})


# Right after the call the PC is still where it was, and stepping shows it jump to the boot
# area, because the reset is SCHEDULED and applies when the machine runs. What it saves is
# the process launch and nothing of the emulated time to the screen that matters, where it
# works against you. Save states avoid re-emulating where a driver declares
# MACHINE_SUPPORTS_SAVE, and whether it restores everything it should is a promise its own
# save_item coverage keeps or breaks, which `state_load` measures with the ROM check and the
# frame, pc and registers the save recorded.
def reset(ses: gs.Session, scratch: Path) -> dict[str, Any]:
    """The body of the `reset` tool: the soft reset applied and read back against the pc
    `start` parked at, and SURVEYED AS THE STOP IT IS. There is no hard one: it re-creates the
    machine and the gdbstub connection dies with it, which is `close` and `start`."""
    pc = ses.reset()
    across = mtap.mark_across("softreset")
    boot = STATE.boot_pc
    # THE STEP THAT APPLIES THE RESET IS A STOP, and it is recorded here like `step`'s:
    # a reset that leaves it unrecorded is found by the next call as a stop the machine
    # reached on its own, at no breakpoint this server armed. The
    # survey also reads the frame, and it is what a caller subtracts: THE FRAME COUNTER
    # DOES NOT RESTART on a soft reset (the same frame before and after), so a frame after
    # it is a cold boot's only by subtracting this one. Read
    # AFTER the step, so it is the counter the reset machine starts from. A console that
    # answers the frame with something else leaves it null in the survey, as at any stop,
    # never as an exception out of a write that already landed.
    seen = running.survey(ses, scratch)
    return running.finish_stop(ses, seen, "softreset",
                               kind="softreset", pc=st.hex_addr(pc),
                               boot_pc=st.hex_addr(boot) if boot is not None else None,
                               verified=boot is not None and pc == boot,
                               frame_at_reset=st.frame_shown(seen["frame"]),
                               **({"taps_across": across} if across else {}))


def clip_text(output: str, scratch: Path, stem: str) -> dict[str, Any]:
    """Text of no known shape, bounded: whole in the reply below the ceiling; above it the
    haystack goes to a file in the scratch (`<stem>-N.txt`) and the reply carries a bounded
    preview, `output_chars` and `output_path`. Bounded by CHARACTERS and not by line,
    because a single line can be the whole haystack. Shared by `debug` and the Lua channel,
    which answer the same kind of text."""
    if len(output) <= DEBUG_MAX:
        return {"output": output, "clipped": False}
    path = scratch / f"{stem}-{STATE.next_number('debug_dumps')}.txt"
    path.write_text(output, encoding="utf-8")
    preview = output.split("\n", 1)[0][:DEBUG_PREVIEW]
    return {"output": preview + "...", "output_chars": len(output), "output_path": str(path),
            "clipped": True}




# The console's three clears, and what forgets the records of the family each one clears,
# looked up at the call rather than bound at import.
_CLEARS: dict[str, Callable[[gs.Session], list[dec.Owner]]] = {
    "bpclear": lambda ses: mclear.forget_rows_gone(ses, "breakpoint"),
    "wpclear": lambda ses: mclear.forget_rows_gone(ses, "watch"),
    "rpclear": lambda ses: regpoints.forget_gone(ses),
}


def _mark_counter(ses: gs.Session, commands: list[str]) -> None:
    """Mark `totalcycles` stale after the last of `commands` that leaves it so (`mame_cycles`)."""
    if stale := [name for one in commands if (name := console.stale_counter_command(one))]:
        cycles.mark_stale_counter(ses, stale[-1])


def check_debug(command: str = "", **_: Any) -> None:
    """`debug`'s machine-independent half. A HARD RESET RE-CREATES THE MACHINE and the stub's
    connection dies with it: sent, the line would answer ok and the next call fail on a closed
    channel, so it is refused before anything is sent, as the `reset` tool offers no hard reset.
    A line too long for a packet waits for the session: the size is the stub's, negotiated."""
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
    # THE CPU MAME IS LIVE ON IS READ BEFORE a line that can ignore it: a `focus` or an
    # `ignore` that leaves it ignored makes MAME run until another cpu executes. It is the
    # visible cpu unless an `Hc` moved that one without a stop, which the stub's `?` sees.
    was = live = None
    if any(console.sets_cpus(one) for one in commands):
        was = cpus.visible_cpu(ses)
        live = cpus.live_cpu(ses) or was
    window = STATE.run_release
    if releases:
        ses.console_packet(command)   # a command too long to send reads no clock either
        running.mark_release(ses)     # the emulated clock read now, while it is still stopped
    mark = files.log_mark(scratch)
    try:
        output = ses.monitor(command)
    except gs.SessionError:
        # SENT AND NOT ANSWERED: whether it wrote is unknown, so a line that would write
        # counts as one, on the cautious side, before the failure goes on to its reply.
        if console.mutates_any(commands):
            STATE.console_writes += 1
        _mark_counter(ses, commands)
        raise
    # WHAT A PARSE ERROR STOPPED NEVER RAN: the refused command and everything after it are
    # left out of the writes, the release and the cpu setters below, so a `g` behind a
    # refused command leaves the machine stopped. A command refused WHILE IT RAN stays
    # counted, on the cautious side: it may have written before it failed (`mame_console`).
    refusal = console.refusals(command, output)
    skipped = refusal.skipped() if refusal is not None else set()
    ran_cmds = [one for k, one in enumerate(commands) if k not in skipped]
    # THE ONE DOOR A ROW HELD PAST ITS DECLARATION LEAVES BY: the record of a row the list no
    # longer shows goes now, or a stop would be believed possible where nothing is armed.
    # Once per family, in the order the line cleared them: each forget reads the list whole,
    # and it reads it for a refused clear too (`wpclear` of a row MAME already dropped is
    # refused by number, and the list is what says the record has to go).
    writes = console.mutates_any(ran_cmds)
    if writes:
        STATE.console_writes += 1     # before the forgets below, whose own reads can fail
    for name in dict.fromkeys(n for n in names if n in _CLEARS):
        _CLEARS[name](ses)
    reply: dict[str, Any] = {"command": command, "mutates": writes}
    notes = []
    if releases and not any(console.releases(one) for one in ran_cmds):
        # The release never ran: the window `mark_release` opened describes no run, and the
        # one it replaced is put back.
        releases = False
        STATE.run_release = window
    if releases:
        ses.running = True
        STATE.console_run = True
        notes.append("the console released the machine: the readers refuse until it stops "
                     "(a breakpoint, `stop`), and the stop is proved on the frame counter")
    # A SAVE OR A LOAD MAME HELD, however the line reached it (`do`, `source`, an alias), is
    # completed as `state_save` and `state_load` complete theirs, before the counter is read
    # below, and the step that completed it is recorded as a stop. MAME's words that it held
    # one come from nothing else (`HELD_BY_TIMERS`). A refusal still marks the counter: the
    # load may land in the next run.
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
    # A LOAD, A REWIND OR A RESET THE LINE RAN leaves `totalcycles` stale for the next run, as
    # `state_load` does, unless the line also ran the machine, which made it current, or the
    # console refused the rewind, which replaced nothing.
    if not releases and not console.refused_rewind(ran_cmds, output):
        _mark_counter(ses, ran_cmds)
    _restart_assigned(ran_cmds)
    notes.extend(_controls_assigned(ran_cmds))
    if any(console.sets_cpus(one) for one in ran_cmds) and not releases:
        ignored = cpus.ignored(ses)
        # THE LINE IGNORED THE LIVE CPU, so MAME runs until another executes, and answers the
        # console meanwhile: the visible cpu is read once that run stopped.
        ran = live is not None and live in (ignored or [])
        visible = mfocus.settled_visible(ses, ignored or []) if ran else cpus.visible_cpu(ses)
        reply["visible_cpu"] = st.or_unavailable(
            visible, "no stop was read after the run the line started, so no cpu is visible yet"
            if ran else "`cpulist` marked no cpu visible")
        reply["ignored"] = st.or_unavailable(ignored, "`ignore` answered neither of its shapes")
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
    # THE CONSOLE'S OWN ERROR IS A REFUSAL OF THE ARGUMENT, in the console's words, with the
    # whole answer kept as an `ok` reply keeps it; a sequence stops at this step.
    return menvelope.invalid("bad_argument", console.refusal_message(command, refusal), **fields,
                             **refusal.fields(commands))


def _assigned_now(commands: list[str]) -> set[int]:
    """The temps a line assigns as it runs, not in a row it arms for later."""
    return set().union(*(lexer.temps_assigned(one) for one in commands
                         if not console.evaluated_later(one)))


def _restart_assigned(commands: list[str]) -> None:
    """A control whose temp a line assigns now restarts from the value written: the landings
    this server added for it (`breakpoints.count_landing`) belonged to the count replaced."""
    now = _assigned_now(commands)
    for c in STATE.controls.values():
        if c["temp"] in now:
            c["missed"] = 0


def _controls_assigned(commands: list[str]) -> list[str]:
    """One note for the controls whose temp the line assigns now, one for those a row it arms
    assigns at every evaluation (REFERENCE.md, *The console*, says what each moves)."""
    def named(found: set[int]) -> str:
        return ", ".join(f"{ref}{f' on {cpu}' if cpu else ''} (temp{c['temp']})"
                         for (ref, cpu), c in STATE.controls.items() if c["temp"] in found)

    now = _assigned_now(commands)
    armed = set().union(*(lexer.temps_assigned(one) for one in commands
                          if console.evaluated_later(one)))
    notes = []
    if named(now):
        notes.append(f"this line assigns the counter of {named(now)}: `breakpoint_list`'s "
                     "`hits_since_armed` now counts on from the value written (-1 makes the "
                     "control halt at its next hit), and a run's `control_hits`, taken across "
                     "the run, does not see it")
    if named(armed):
        notes.append(f"a row this line arms assigns the counter of {named(armed)} each time "
                     "it is evaluated, so `control_hits` and `hits_since_armed` count those writes")
    return notes
