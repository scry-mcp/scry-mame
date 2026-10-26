"""The console's `statesave` and `stateload`, each judged by the file rather than the console.

MAME refuses a bad state in silence from the debugger console, so the header is judged before
the console, and a load is compared afterwards with what the save recorded.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Any, NamedTuple

from scry_core import judges, state_files
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

# Header as MAME writes it (`save.cpp`): magic, format version at 8, system name at 0x0a
# (NUL padded to 0x1c), save-registration signature at 0x1c. MAME refuses a bad one silently.
STATE_MAGIC = b"MAMESAVE"
STATE_HEADER = 32
STATE_NAME_AT, STATE_NAME_END, STATE_SIGNATURE_AT = 0x0A, 0x1C, 0x1C
#: MAME's error.log words when it holds a save or a load (`can_save`).
HELD_BY_TIMERS = "Failed save state attempt due to anonymous timers"


def _state_dir() -> Path:
    """Where this session's states live: `sta/<system>` under `state_dir` or the scratch."""
    return Path(STATE.state_dir or str(STATE.scratch)) / "sta" / STATE.system


def _state_file(name: str) -> Path:
    return _state_dir() / f"{name}.sta"


NOT_WRITTEN_HERE = "this session did not write the state, so there is no frame and pc to compare"
NOTHING_TO_JUDGE = ("the save recorded no frame, since this machine counts none or the read "
                    "failed, and the stub reads no cpu's registers, so nothing read after the "
                    "load can prove it")
ALREADY_AS_SAVED = ("the machine already read as the save before the load (the frame and pc "
                    "where there is a counter, and every register block judged), so the load "
                    "cannot be told from no load: a loop that comes back to the saved place "
                    "reads the same")


def state_list() -> dict[str, Any]:
    """The body of the `state_list` tool: every `.sta` with its size, and the frame and pc when
    this session wrote it; otherwise each is `unavailable` saying why. A reading of a
    directory, so it answers while the machine runs."""
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
        states.append({
            "name": path.stem, "path": str(path), "bytes": size,
            "frame": (st.frame_shown(known["frame"]) if known
                      else unavailable(NOT_WRITTEN_HERE)),
            "pc": st.hex_addr(known["pc"]) if known else unavailable(NOT_WRITTEN_HERE),
        })
    return menvelope.envelope({"state_dir": str(folder), "states": states})


def check_state_name(name: str, **_: Any) -> None:
    state_files.check_state_name(name, "a file name the console takes as one parameter")


def _header(path: Path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(STATE_HEADER)


def _judge_header(path: Path, head: bytes) -> None:
    """Check the magic, the system's name and, once this session has saved, the signature."""
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


def save_state(ses: gs.Session, scratch: Path, name: str) -> dict[str, Any]:
    """The body of the `state_write(method="save")` tool: `statesave`, then the file checked for
    MAME's header. A held save is completed by one instruction (`complete_held`) and the reply
    says so. The frame, pc and register blocks are kept to judge a later load."""
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
    # After the save, which is the machine the file holds: nothing ran since it landed.
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
    # Unrecorded, the next contact would report this step as a stop the machine reached itself.
    record = running.record_stop(ses, scratch, f"statesave {name}")
    return menvelope.envelope({**fields, "held": held, "stop_seq": record["seq"]})


def load_state(ses: gs.Session, scratch: Path, name: str) -> dict[str, Any]:
    """The body of the `state_write(method="load")` tool: `stateload`, which replaces the
    machine, then the stop surveyed, the ROM rechecked and the load judged (`_judged`) against
    the save: `verified`, unavailable with why, or a refusal."""
    check_state_name(name)
    path = _state_file(name)
    why = state_files.not_a_state(path)
    if why is not None:
        raise state_files.refused_load(name, path, why)
    if not path.exists():
        raise st.Invalid("unknown_ref", f"no state named {name!r} at {path}: `state_list` "
                                        "names the ones held")
    _judge_header(path, _header(path))
    # The control of the comparison: equality after proves the load only if it differed before.
    saved = STATE.states.get(name)
    before = None if saved is None else _reading(ses, saved)
    STATE.console_writes += 1     # before the send: a load failing half-way still replaced
    try:
        return _stateload(ses, scratch, name, path, before)
    finally:
        # A refusal included: the machine may be the state's from the send on.
        cycles.mark_stale_counter(ses, cycles.STATE_LOAD)


def _blocks(ses: gs.Session, saved: dict[str, Any]) -> dict[str, dict[str, str]]:
    """The register blocks read now, of the cpus `saved` holds."""
    now = cpus.register_blocks(ses)
    return {cpu: now[cpu] for cpu in saved["blocks"] if cpu in now}


def _reading(ses: gs.Session, saved: dict[str, Any]) -> dict[str, Any]:
    """The frame (None when unread), the pc and the blocks, read now."""
    return {"frame": _frame(ses), "pc": ses.current_pc(), "blocks": _blocks(ses, saved)}


def _first_difference(saved: dict[str, dict[str, str]], now: dict[str, dict[str, str]]
                      ) -> tuple[str, str] | None:
    """The first cpu and register of the cpus both hold whose digits differ."""
    for cpu, block in saved.items():
        for reg, text in block.items():
            if cpu in now and now[cpu].get(reg) != text:
                return cpu, reg
    return None


def _shown(ses: gs.Session, cpu: str, reg: str, text: str | None) -> str | dict[str, Any]:
    """A register as replies spell it (`0x` at its width); the stub's digits if order unknown."""
    if text is None:
        return unavailable("the register was not read on this side")
    lay = ses.layout(cpus.thread_of(ses, cpu) or 1)
    try:
        value = int.from_bytes(bytes.fromhex(text), lay.byte_order)
    except gs.UnknownByteOrder:
        return text
    return judges.hex_at_width(value, lay.register_bits.get(reg, len(text) * 4))


class Judgement(NamedTuple):
    """A load judged against its save: `why` when `verified` is null, else the refusal."""

    verified: bool | None
    why: str | None = None
    message: str = ""
    differs: dict[str, Any] | None = None
    unjudged: tuple[str, ...] = ()


def _judged(ses: gs.Session, name: str, saved: dict[str, Any], before: dict[str, Any],
            seen: dict[str, Any]) -> Judgement:
    """The load of `name` judged against `saved`: frame and pc where a frame was recorded, then
    every register block both readings hold."""
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
    unjudged = tuple(cpu for cpu in saved["blocks"] if cpu not in after)
    if not counted and not judged:
        return Judgement(None, NOTHING_TO_JUDGE, unjudged=unjudged)
    # An unread frame has not moved.
    frame_moved = counted and before["frame"] is not None and before["frame"] != saved["frame"]
    pc_moved = counted and before["pc"] != saved["pc"]
    moved = frame_moved or pc_moved or _first_difference(judged, before["blocks"]) is not None
    return (Judgement(True, unjudged=unjudged) if moved
            else Judgement(None, ALREADY_AS_SAVED, unjudged=unjudged))


def _stateload(ses: gs.Session, scratch: Path, name: str, path: Path,
               before: dict[str, Any] | None) -> dict[str, Any]:
    """`stateload` sent, the ROM rechecked, the stop surveyed and judged against the save."""
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
            # Recorded all the same: the survey already moved the log marks and watch baselines.
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

    A pending anonymous timer due now with the machine stopped (a memory write that runs a
    synchronizing driver handler, or a display refresh that raises an input line) makes MAME
    hold every save and load (`HELD_BY_TIMERS`) into the caller's next run. One instruction
    through the stub's `s` ends the timeslice and completes it. Nothing ends that step early:
    while an operation is pending no cpu's debugger hook is called (`compute_debug_flags`).
    MAME keeps one pending operation, so several held completes only the last."""
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
    """How many saves or loads error.log says MAME held since `mark`."""
    return sum(HELD_BY_TIMERS in line for line in files.errorlog_since(scratch, mark)[0])


def _frame(ses: gs.Session) -> int | None:
    try:
        return int(read.frame(ses))
    except gs.SessionError:
        return None
