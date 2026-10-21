"""SAVESTATES: the console's own `statesave` and `stateload`, each judged by the file.

MAME writes and reads a state from the debugger console, so none of this is Lua: what is
here is the judgement around the two commands. A save is vouched for by the file it left,
not by what the console printed; a load is refused BEFORE the console when the header is
not this machine's, because MAME's own refusal says nothing on the console, and after it the
frame, the pc and every readable cpu's registers are compared with what the save recorded.
A `.sta` that holds no state (`state_files.not_a_state`) is judged before anything opens it.
"""

from __future__ import annotations

import os
import re
import struct
from pathlib import Path
from typing import Any, NamedTuple

from scry_core import state_files
from scry_core.reply_contract import unavailable

import gdb_session as gs
import mame_cpus as cpus
import mame_cycles as cycles
import mame_envelope as menvelope
import mame_files as files
import mame_read as read
import mame_running as running
import mame_state as st
import mame_tap as mtap
from mame_state import STATE

# A savestate as MAME writes it (`save.cpp`): the magic, the format version at byte 8, the
# system's name at 0x0a (NUL padded up to 0x1c), the signature of the machine's save
# registrations at 0x1c. MAME checks the same three on load and REFUSES IN SILENCE from
# the debugger console: measured, a corrupt header and a foreign system's state both
# left nothing in error.log or on stdout, so the check is made HERE, before the console.
STATE_MAGIC = b"MAMESAVE"
STATE_HEADER = 32
STATE_NAME_AT, STATE_NAME_END, STATE_SIGNATURE_AT = 0x0A, 0x1C, 0x1C
#: MAME's words in error.log when it holds a save or a load (`can_save`, which only
#: `handle_saveload` asks); `complete_held` says why and what is done about it.
HELD_BY_TIMERS = "Failed save state attempt due to anonymous timers"
#: The longest state name taken: a file name MAME writes under the state folder.
STATE_NAME_MAX = 64
STATE_NAME = re.compile(rf"[A-Za-z0-9_-]{{1,{STATE_NAME_MAX}}}")


def _state_dir() -> Path:
    """Where this session's states live: `sta/` under the caller's `state_dir` or the
    scratch, and inside it the system's own folder, which is where MAME puts them."""
    return Path(STATE.state_dir or str(STATE.scratch)) / "sta" / STATE.system


def _state_file(name: str) -> Path:
    return _state_dir() / f"{name}.sta"


#: Why a state's frame and pc cannot be judged: only a state this session wrote has a record.
NOT_WRITTEN_HERE = "this session did not write the state, so there is no frame and pc to compare"
#: Why a load is not judged where there is nothing to read: the emulated clock runs on across a
#: `stateload` instead of coming back with the state, so it proves nothing either.
NOTHING_TO_JUDGE = ("the save recorded no frame, since this machine counts none or the read "
                    "failed, and the stub reads no cpu's registers, so nothing read after the "
                    "load can prove it")
#: Why a load is not judged when the machine already read as the save before it.
ALREADY_AS_SAVED = ("the machine already read as the save before the load (the frame and pc "
                    "where there is a counter, and every register block judged), so the load "
                    "cannot be told from no load: a loop that comes back to the saved place "
                    "reads the same")


def state_list() -> dict[str, Any]:
    """The body of the `state_list` tool: every `.sta` in this session's folder, with its
    size, and the frame and pc when THIS session wrote it; a state an earlier session
    wrote carries each as `unavailable` saying so, as `state_load` says of it, and a `.sta`
    that holds no state (`state_files.not_a_state`) carries all three so: the name is taken,
    so it is shown.
    A reading of a directory: the machine is not touched, so it answers while the machine
    runs."""
    folder = _state_dir()
    states: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.sta")) if folder.is_dir() else []:
        why = state_files.not_a_state(path)
        if why is not None:
            gone = unavailable(why)
            states.append({"name": path.stem, "path": str(path), "bytes": gone, "frame": gone,
                           "pc": gone})
            continue
        try:
            size = os.stat(path).st_size
        except FileNotFoundError:
            continue     # removed since the folder was read: no state is there any more
        known = STATE.states.get(path.stem)
        # EACH READING SAYS WHY IT IS NOT THERE, in its own place: an earlier session's state
        # has neither, one saved on a board with no counter has no frame.
        states.append({
            "name": path.stem, "path": str(path), "bytes": size,
            "frame": (st.frame_shown(known["frame"]) if known
                      else unavailable(NOT_WRITTEN_HERE)),
            "pc": st.hex_addr(known["pc"]) if known else unavailable(NOT_WRITTEN_HERE),
        })
    return menvelope.envelope({"state_dir": str(folder), "states": states})


def check_state_name(name: str, **_: Any) -> None:
    """`state_save`/`state_load`'s machine-independent half: the name becomes a file name the
    console takes as one parameter."""
    if not STATE_NAME.fullmatch(name):
        raise st.Invalid("bad_argument",
            f"name={name!r}: letters, digits, `_` and `-` only, up to 64, because it becomes "
            "a file name the console takes as one parameter")


def _header(path: Path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(STATE_HEADER)


def _judge_header(path: Path, head: bytes) -> None:
    """The three things MAME checks on load, checked here because MAME's own refusal is
    silent from the console: the magic, the system's name, and (when this session saved
    a state) the signature of the machine's save registrations."""
    if head[:len(STATE_MAGIC)] != STATE_MAGIC:
        raise st.Invalid("readback_refused",
            f"{path} does not open with MAME's savestate magic", path=str(path))
    named = head[STATE_NAME_AT:STATE_NAME_END].split(b"\0", 1)[0].decode("ascii", "replace")
    if named != STATE.system:
        raise st.Invalid("readback_refused",
            f"{path} is a state of `{named}`, and this machine is `{STATE.system}`: it is "
            "not handed to MAME", path=str(path), system=named)
    signature = int(struct.unpack_from("<I", head, STATE_SIGNATURE_AT)[0])
    if STATE.state_signature is not None and signature != STATE.state_signature:
        raise st.Invalid("readback_refused",
            f"{path} carries save signature {signature:#010x} and the states this session "
            f"wrote carry {STATE.state_signature:#010x}: not a state of this machine as this "
            "session saves it",
            path=str(path))


def state_save(ses: gs.Session, scratch: Path, name: str) -> dict[str, Any]:
    """The body of the `state_save` tool: the console's `statesave`, then the file checked
    for MAME's own header. A save that runs in the command alters nothing; one MAME held is
    completed by one instruction (`complete_held`), and the reply's `held` and `stop_seq` say
    so. What the console prints is a promise, and the file is the measurement. The frame, the
    pc and every readable cpu's register block at the save are remembered, so a load of this
    state can be judged against them."""
    check_state_name(name)
    path = _state_file(name)
    if os.path.lexists(path):
        raise st.Invalid("bad_argument", f"a state named {name!r} already exists at "
                                         f"{path}; this tool never overwrites")
    mark = files.log_mark(scratch)
    said = ses.monitor(f"statesave {name}")
    held = complete_held(ses, scratch, mark, f"statesave {name}")
    files.wait_for(path.exists, files.FILE_WAIT_S, files.FILE_POLL_S)
    complaints, _ = files.errorlog_since(scratch, mark)
    if not path.exists():
        raise st.Invalid("readback_refused",
            f"no {path} appeared after `statesave`: the console said {said.strip()!r}",
            errorlog=running.errorlog_block(complaints, mark))
    head = _header(path)
    _judge_header(path, head)
    # READ AFTER THE SAVE, which is the machine the file holds: a save in the command altered
    # nothing, and a held one landed before the step's stop, with nothing executed since.
    frame = _frame(ses)
    pc = ses.current_pc()
    blocks = cpus.register_blocks(ses)
    STATE.state_signature = int(struct.unpack_from("<I", head, STATE_SIGNATURE_AT)[0])
    STATE.states[name] = {"frame": frame, "pc": pc, "blocks": blocks}
    fields = {"name": name, "path": str(path), "bytes": path.stat().st_size,
              "frame": st.frame_shown(frame),
              "pc": st.hex_addr(pc), "errorlog": running.errorlog_block(complaints, mark)}
    if held is None:
        return menvelope.envelope(fields)
    # THE STEP IS A STOP, recorded as one: left unrecorded, the next contact would find it and
    # report a stop the machine reached on its own.
    record = running.record_stop(ses, scratch, f"statesave {name}")
    return menvelope.envelope({**fields, "held": held, "stop_seq": record["seq"]})


def state_load(ses: gs.Session, scratch: Path, name: str) -> dict[str, Any]:
    """The body of the `state_load` tool: the console's `stateload`, which REPLACES the
    machine (altered from then on), then the stop surveyed and the ROM checked again
    against the reference `start` was given. MAME refuses a bad state IN SILENCE from the
    console (measured), so the header is judged BEFORE the console, and the load is judged
    against what `state_save` recorded (`_judged`): `verified`, or unavailable with why
    (`NOT_WRITTEN_HERE`, `ALREADY_AS_SAVED`, `NOTHING_TO_JUDGE`), or a refusal naming the frame
    and pc or carrying `differs`. `rom_check` is `OK`, or unavailable with no reference image."""
    check_state_name(name)
    path = _state_file(name)
    why = state_files.not_a_state(path)
    if why is not None:
        raise state_files.refused_load(name, path, why)
    if not path.exists():
        raise st.Invalid("unknown_ref", f"no state named {name!r} at {path}: `state_list` "
                                        "names the ones held")
    _judge_header(path, _header(path))
    # WHAT THE MACHINE READ BEFORE THE LOAD, the control of the comparison after it: between
    # the two readings only the load takes effect (a held one's step runs on the machine the
    # load then replaces), so equality after proves the load only where something differed
    # before (`ALREADY_AS_SAVED`).
    saved = STATE.states.get(name)
    before = None if saved is None else _reading(ses, saved)
    STATE.console_writes += 1     # before the send: a load that fails half-way still replaced
    try:
        return _stateload(ses, scratch, name, path, before)
    finally:
        # EVERY WAY OUT, a refusal included: the machine may be the state's from the send on.
        cycles.mark_stale_counter(ses, cycles.STATE_LOAD)


def _blocks(ses: gs.Session, saved: dict[str, Any]) -> dict[str, dict[str, str]]:
    """The register blocks, read now, of the cpus `saved` holds a block for."""
    now = cpus.register_blocks(ses)
    return {cpu: now[cpu] for cpu in saved["blocks"] if cpu in now}


def _reading(ses: gs.Session, saved: dict[str, Any]) -> dict[str, Any]:
    """The frame (None when unread), the pc and the blocks (`_blocks`), read now."""
    return {"frame": _frame(ses), "pc": ses.current_pc(), "blocks": _blocks(ses, saved)}


def _first_difference(saved: dict[str, dict[str, str]], now: dict[str, dict[str, str]]
                      ) -> tuple[str, str] | None:
    """The first cpu and register, in their own orders, whose digits `now` reads other than
    `saved` holds, of the cpus both hold."""
    for cpu, block in saved.items():
        for reg, text in block.items():
            if cpu in now and now[cpu].get(reg) != text:
                return cpu, reg
    return None


def _shown(ses: gs.Session, cpu: str, reg: str, text: str | None) -> str | dict[str, Any]:
    """A register's digits as every reply spells a register, `0x` at its width, in its cpu's
    byte order; the stub's own digits where that order is not established."""
    if text is None:
        return unavailable("the register was not read on this side")
    lay = ses.layout(cpus.thread_of(ses, cpu) or 1)
    try:
        value = int.from_bytes(bytes.fromhex(text), lay.byte_order)
    except gs.UnknownByteOrder:
        return text
    return read.hex_at_width(value, lay.register_bits.get(reg, len(text) * 4))


class Judgement(NamedTuple):
    """A load judged against its save: `verified`, and `why` when it is null; when it is false,
    the refusal's `message` and, for a register, its `differs`."""

    verified: bool | None
    why: str | None = None
    message: str = ""
    differs: dict[str, Any] | None = None
    unjudged: tuple[str, ...] = ()


def _judged(ses: gs.Session, name: str, saved: dict[str, Any], before: dict[str, Any],
            seen: dict[str, Any]) -> Judgement:
    """The load of `name` judged against `saved`, read `before` it and `seen` (the survey)
    after: the frame and pc where the save recorded a frame, then every block both readings
    hold; equal after proves the load only where something differed before."""
    counted = read.frame_symbol() is not None and saved["frame"] is not None
    if counted and (seen["frame"] != saved["frame"] or seen["pc"] != st.hex_addr(saved["pc"])):
        return Judgement(False, message=(
            f"after `stateload {name}` the machine is at frame {seen['frame']}, pc "
            f"{seen['pc']}, and the state was saved at frame {saved['frame']}, pc "
            f"{st.hex_addr(saved['pc'])}: MAME did not load it"))
    after = _blocks(ses, saved)
    judged = {cpu: saved["blocks"][cpu] for cpu in after}
    if (miss := _first_difference(judged, after)) is not None:
        cpu, reg = miss
        differs = {"cpu": cpu, "register": reg, "saved": _shown(ses, cpu, reg, judged[cpu][reg]),
                   "loaded": _shown(ses, cpu, reg, after[cpu].get(reg))}
        return Judgement(False, differs=differs, message=(
            f"after `stateload {name}` {cpu}'s {reg} reads {differs['loaded']}, and the state "
            f"was saved with {differs['saved']}: MAME did not load it"))
    # A CPU READ AT THE SAVE AND NOT NOW is left out of the comparison, and said.
    unjudged = tuple(cpu for cpu in saved["blocks"] if cpu not in after)
    if not counted and not judged:
        return Judgement(None, NOTHING_TO_JUDGE, unjudged=unjudged)
    # AN UNREAD FRAME IS NOT A FRAME THAT MOVED: only a reading can differ.
    frame_moved = counted and before["frame"] is not None and before["frame"] != saved["frame"]
    pc_moved = counted and before["pc"] != saved["pc"]
    moved = frame_moved or pc_moved or _first_difference(judged, before["blocks"]) is not None
    return (Judgement(True, unjudged=unjudged) if moved
            else Judgement(None, ALREADY_AS_SAVED, unjudged=unjudged))


def _stateload(ses: gs.Session, scratch: Path, name: str, path: Path,
               before: dict[str, Any] | None) -> dict[str, Any]:
    """`stateload` sent (and completed, when MAME held it), the ROM checked again, the stop
    surveyed and judged against the save."""
    channel_ends = files.channel_marks(scratch)
    mark = channel_ends["emulator"]
    said = ses.monitor(f"stateload {name}")
    held = complete_held(ses, scratch, mark, f"stateload {name}")
    across = mtap.mark_across(f"stateload {name}")
    rom_check: str | dict[str, Any]
    checks: dict[str, str] = {}
    if STATE.reference is None:
        rom_check = unavailable("this session holds no reference image to check against")
    else:
        ref, addr, base = STATE.reference
        try:
            ses.self_check(ref.read_bytes(), addr, base=base, thread=1)
        except gs.Mismatch as e:
            raise st.Invalid("readback_refused",
                f"after the load the ROM check failed: {e}", path=str(path)) from None
        rom_check = "OK"
    seen = running.survey(ses, scratch)
    saved = STATE.states.get(name)
    # The reply spells the saved pc as it spells every pc, hex; the record keeps the int.
    shown = unavailable(NOT_WRITTEN_HERE) if saved is None else {
        "frame": st.frame_shown(saved["frame"]), "pc": st.hex_addr(saved["pc"])}
    verified: bool | dict[str, Any] | None
    if saved is None or before is None:
        verified = unavailable(NOT_WRITTEN_HERE)
    else:
        judged = _judged(ses, name, saved, before, seen)
        verified = judged.verified
        if judged.why is not None:
            verified = unavailable(judged.why)
        if judged.unjudged:
            checks["note"] = (f"{', '.join(judged.unjudged)} read at the save could not be read "
                              "after the load, so it was not judged")
        if verified is False:
            # THE STOP IS RECORDED ALL THE SAME: the survey already moved the log's marks and
            # the watches' baselines, and a stop left unremembered would take what it read
            # away from the next one. The refusal carries where the machine is.
            stopped = running.finish_stop(ses, seen, f"stateload {name}")
            where = {k: v for k, v in stopped.items() if k not in ("status", "session")}
            return menvelope.invalid("readback_refused", judged.message, path=str(path),
                                     saved=shown, mark=channel_ends,
                                     **({"differs": judged.differs} if judged.differs else {}),
                                     **where)
    return running.finish_stop(ses, seen, f"stateload {name}", name=name, path=str(path),
                               rom_check=rom_check, verified=verified, saved=shown,
                               output=said.strip(), mark=channel_ends, **checks,
                               **({"held": held} if held is not None else {}),
                               **({"taps_across": across} if across else {}))


def complete_held(ses: gs.Session, scratch: Path, mark: int, command: str) -> str | None:
    """Complete `command` (a `statesave` or `stateload` just sent) when MAME held it, and say
    so; None when it ran inside the command.

    HOW ONE COMES TO BE HELD AT A STOP. Something queues an anonymous timer due now with the
    machine stopped, which nothing fires until it runs: a memory write through the stub that
    runs a driver handler that synchronizes (victory's sound command), or, on a stub that
    refreshes the display after every monitor command and memory write, a driver whose screen
    update raises an input line (circus asserts its IRQ on a sprite collision drawn). MAME
    then holds every save and load for the end of the next timeslice (`HELD_BY_TIMERS`), and
    left alone it lands inside the caller's next run. One instruction through the stub's `s`
    ends that timeslice, the timer fires, the operation completes, and the stop that follows
    is the machine the operation left; the `s` is no monitor command, so nothing refreshes
    between the two. NOTHING ENDS THAT STEP EARLY: while an operation is pending MAME calls no
    cpu's debugger hook (`compute_debug_flags`), so no breakpoint or watchpoint on any cpu
    stops the machine first, and no second hold logged after the step is proof it completed.
    A machine still held after it is refused, because the operation would land in the next
    run. MAME keeps ONE
    pending operation, each save or load replacing the one before, so a line that had several
    held completes only the last, and the reply says so."""
    count = _held_since(scratch, mark)
    if not count:
        return None
    held = f"MAME held `{command}` for a pending anonymous timer (error.log)"
    if count > 1:
        held += (f"; it held {count} saves or loads and keeps one pending at a time, so only "
                 "the last of them was completed")
    after = files.log_mark(scratch)
    try:
        ses.step()
    except gs.Timeout as e:
        # The `s` went out and the stub owes its stop packet, as for the `step` tool.
        raise st.Invalid("not_settled",
            f"{held}, and the step taken to complete it brought no stop in time ({e}), so "
            f"the machine may be RUNNING. {running.STOP_RECOVERS}") from None
    if _held_since(scratch, after):
        raise st.Invalid("not_settled",
            f"{held}, and one instruction later it was still held: it stays scheduled and "
            "lands inside the next run")
    return (f"{held}, so one instruction was stepped to complete it: the machine stopped "
            f"right after it, at pc {st.hex_addr(ses.current_pc())}")


def _held_since(scratch: Path, mark: int) -> int:
    """How many saves or loads error.log says, since `mark`, that MAME held."""
    return sum(HELD_BY_TIMERS in line for line in files.errorlog_since(scratch, mark)[0])


def _frame(ses: gs.Session) -> int | None:
    try:
        return int(read.frame(ses))
    except gs.SessionError:
        return None
