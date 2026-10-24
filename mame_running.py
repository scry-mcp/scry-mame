"""The RUNNING guest: what a stop is, and what the server does at the first contact after one.

A machine let go with `resume` answers the stub's packets while it runs (`m`,
`qRcmd` and `Z0` all come back), but a value read off a moving machine is a sample of no
state, so the readers refuse and name the LAST STOP instead (`require_stopped`). This
module is about the moments around that: a stop the machine reached on its own is
RECORDED by the first contact that finds it (`observe_stop`, which reads the stub's own
stop packet off the socket); and a stop a tool produced comes back as ONE survey
(`stop_reply`): the program counter, the registers, the frame, the disassembly at the
program counter and what the driver logged since the previous stop, so the round trips
are saved where they are worth saving.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scry_core import log_marks, narrowing
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_arming as arming
import mame_breakpoints as breakpoints
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_files as files
import mame_iotaps as iotaps
import mame_read as read
import mame_regpoints as regpoints
import mame_state as st
import mame_tap as mtap
import mame_watches as watches
from mame_state import STATE

# What a stop shows at the program counter: a handful of instructions on either cpu.
DASM_BYTES = 32

# How often a bounded `resume` asks the socket for the stop.
RESUME_POLL_S = 0.1
# How long `stop` gives a run the console started to come to rest after the interrupt.
CONSOLE_HALT_SETTLE_S = 2.0
# What every reply that leaves the machine marked RUNNING says about getting it back: `stop`
# has refusals of its own, so the way out past it is named beside it.
STOP_RECOVERS = "`stop` recovers it; if `stop` fails as well, `close` then `start` is the way out"


def errorlog_block(lines: list[str], mark: int) -> dict[str, Any]:
    """The lines `error.log` gained from byte `mark`, as every reply carrying them spells them
    (`log_marks.stop_block`, the emulator channel's)."""
    return log_marks.stop_block(lines, mark, "emulator", read.LOG_LIMIT_MAX)


def session_broke(ses: gs.Session, error: gs.SessionError, when: str, tail: str,
                  **fields: Any) -> dict[str, Any]:
    """LATCH the session broken and answer the refusal that says so. Something read in a
    stop's place, or a connection that failed, means the two ends no longer agree where a
    packet starts, and the stub honours an interrupt only between packets: from here not even
    `stop` can be believed, so the reply never calls the machine running. A session that had
    already latched keeps the reason that latched it: what failed after is its consequence."""
    ses.latch(str(error))
    return menvelope.invalid("session_broken",
                             f"the session broke {when}: {error}. {tail}. `close` it, then `start` "
                             "a new one", **fields)


def session_error_reply(error: gs.SessionError, tool: str,
                        tail: str = "Nothing this call read is handed back") -> dict[str, Any]:
    """A session error `tool` raised (anything but `NotStopped`), as the reply that says so: the
    server's wrapper answers every tool's this way, and a tool that hands something back past
    the error (`trace`'s file) calls it itself and adds that to the reply.

    A COMMAND THE STUB WOULD DROP (`CommandTooLong`) was refused before a byte of it was sent:
    the argument was wrong, and nothing of it reached the machine. THE STUB ANSWERED, and the
    answer was no (`Refused`, `Unsupported`, `UnknownByteOrder`, `Mismatch`,
    `ExpressionRefused`): the channel kept its place, so this is a refusal of what was asked and
    nothing latches; a build or a machine that lacks the capability is `no_channel`, an `E`
    reply or a known answer that did not match `readback_refused`. EVERY OTHER SESSION ERROR
    MEANS THE TWO ENDS MAY NO LONGER AGREE where a packet starts (a request that ran out, a
    connection that failed, a packet read in a reply's place), so it LATCHES, and the call
    answers what every later call will; a session already gone (a failed `start` kills its own)
    has nothing to latch."""
    if isinstance(error, gs.CommandTooLong):
        return menvelope.invalid("bad_argument", str(error), command_chars=error.command_chars,
                                 limit_chars=error.limit_chars)
    if isinstance(error, (gs.Refused, gs.Unsupported, gs.UnknownByteOrder, gs.Mismatch,
                          gs.ExpressionRefused)):
        record_own_stop(tool)
        lacks = isinstance(error, (gs.Unsupported, gs.UnknownByteOrder, gs.ExpressionRefused))
        return menvelope.invalid("no_channel" if lacks else "readback_refused", str(error))
    latched = STATE.ses
    if latched is None:
        return menvelope.invalid("session_broken", f"the session broke under `{tool}`: {error}. "
                                 "`start` a new one")
    return session_broke(latched, error, f"under `{tool}`", tail)


def settle_logged(scratch: Path) -> None:
    """Settle every throttle and count-watch removal against what the error log and the removal
    answers already hold. Both settlements only look, so looking twice is free; the error log
    is read without moving its mark, which belongs to the next survey."""
    st.settle_throttles(files.errorlog_since(scratch, STATE.errorlog_mark)[0])
    mtap.read_removal_answers(scratch)


def still_pending(scratch: Path) -> dict[str, list[dict[str, Any]]]:
    """What this session asked for and the machine has not yet confirmed: every throttle
    asked while stopped, by the `tag` its reply named, and every count watch's removal, by
    the `call` `declaration_clear(kind="watch")` named. Always both lists, so an empty one says
    somebody looked.

    SUCCESS IS A ROW LEAVING, never a row of its own: a failure latches in a row that repeats
    (`throttles_not_applied`, `tallies_not_removed`), and what was still missing was the
    waiting, which is the one state a caller could only establish through a second channel.

    SETTLED AGAINST WHAT IS ALREADY LOGGED (`settle_logged`), not as of the last stop, so a
    switch whose mark has arrived is not called waiting.
    """
    settle_logged(scratch)
    return {
        "throttles_pending": [{"tag": r["tag"], "on": r["on"]}
                              for r in STATE.throttles_pending],
        "tallies_pending_removal": [{"tally_id": r["tally_id"],
                                     "call": st.sentinel_line(r["seq"])}
                                    for r in STATE.tally_removals if not r["state"]],
    }

def stop_registers(ses: gs.Session, cpu: str | None) -> dict[str, Any]:
    """The registers of `cpu`, the one the machine stopped on, read on its own thread; or
    `available: false` with the reason, never another cpu's file, when this build cannot read
    them: a stub without the thread patch serves its first cpu alone, and a cpu the stub does not
    describe has none. A `cpu` of None (`cpulist` marked none) is read as the stub's first."""
    if not ses.threads:
        served = cpus.stub_cpu(ses)
        if cpu not in (None, served):
            return unavailable(f"{cpu}'s registers are read through its own thread of the "
                                  f"gdbstub's thread patch, and this build's stub serves only "
                                  f"{served}")
        thread = 1
    else:
        found = cpus.thread_of(ses, cpu) if cpu is not None else 1
        if found is None:
            return unavailable(f"the stub names no thread for {cpu}")
        thread = found
    try:
        cpus.described(ses, cpu, thread)
    except st.Invalid as e:
        return unavailable(str(e))
    return read.fmt_regs(ses, thread)


def survey(ses: gs.Session, scratch: Path) -> dict[str, Any]:
    """ONE survey of a stopped machine: where it is, its registers, the frame, the listing at
    the program counter and the log since the last stop. The listing and the frame are the
    console's, and a console that answers something else is reported as unavailable, never
    as a listing of the wrong thing; the log's mark moves to where the log ends now."""
    pc = ses.current_pc()
    # ONE CPU, THE ONE THAT STOPPED: MAME makes it the visible cpu at every stop
    # (`debugger_cpu::wait_for_debugger`), so `cpulist` names it on either build, and the pc,
    # the listing and the registers are all its own. The patched stub's `?` names the same
    # thread; a survey always follows a stop, so no `Hc` can have moved the visible cpu since.
    cpu = cpus.visible_cpu(ses)
    regs = stop_registers(ses, cpu)
    # THE FRAME AND EVERY DECLARED EXPRESSION IN ONE `print`: the console answers a list, so
    # a stop's cost does not grow with the expr watches. A refusal of the whole list is
    # retried for the frame alone, so an expression that stopped resolving (a cpu switch)
    # takes the expressions' readings down as unavailable and never the frame. A board with no frame
    # counter prints the expressions alone, and its frame is null.
    frame: int | None = None
    expressions: dict[str, int] | gs.SessionError = {}
    exprs = watches.expression_refs()
    symbol = read.frame_symbol()
    names = [symbol, *exprs] if symbol is not None else exprs
    if names:
        try:
            values = read.print_values(ses, names)
            if symbol is not None:
                frame, values = values[0], values[1:]
            expressions = dict(zip(exprs, values, strict=True))
        except gs.SessionError as e:
            expressions = e
            if symbol is not None:
                try:
                    frame = read.frame(ses)
                except gs.SessionError:
                    frame = None
    dasm: list[str] | dict[str, Any]
    try:
        dasm = read.dasm_lines(ses, scratch, pc, DASM_BYTES)
    except gs.SessionError as e:
        dasm = unavailable(str(e))
    from_mark = STATE.errorlog_mark
    since, STATE.errorlog_mark = files.errorlog_since(scratch, from_mark)
    # JUDGED OFF THE LINES ALREADY IN HAND. A throttle left pending proves itself by its
    # tag in this same log, so the one place that reads the log at every stop is the
    # one place that can answer for it, and it costs no second read. A tally's removal is
    # read here too, so the alarm every reply carries latches at the next stop.
    st.settle_throttles(since)
    mtap.read_removal_answers(scratch)
    seen: dict[str, Any] = {
        "pc": st.hex_addr(pc),
        "cpu": cpu,
        "frame": frame,
        "regs": regs,
        "dasm": dasm,
        "errorlog": errorlog_block(since, from_mark),
    }
    # A WATCHPOINT'S STOP names its writer: the packet says which address, the console's
    # log says who and what, and `before` is what the previous survey saw. Read BEFORE the
    # watches are evaluated below, which is what moves `before` on to this stop's bytes.
    # A BREAKPOINT typed through `debug` is named off the same lines, and a REGISTERPOINT
    # after it, each only when no row this server armed is at the pc: that row keeps its
    # own name.
    since = arming.debuglog_since(scratch)
    watched = watches.watch_stop(ses, since)
    fresh: dict[dec.Owner, bytes] = {}
    if watched is not None:
        seen["watch_cause"], fresh = watched[0], watched[2]
    elif not halts(pc, cpu):
        # The typed breakpoint's naming is tried first unless the console's NEWEST listed
        # stop is a registerpoint's: the machine stands at the last line, not the first kind.
        foreign = (None if arming.newest_listed_stop(since) == "register"
                   else breakpoints.foreign_breakpoint(ses, since, pc))
        if foreign is not None:
            seen["breakpoint_cause"] = foreign
        elif (named := regpoints.stop_cause(ses, since, seen["pc"])) is not None:
            seen["regpoint_cause"] = named[0]
            if named[1] is not None:
                seen["regpoint_hit"] = named[1]
    evaluated = [*watches.evaluate_watches(ses, fresh, expressions, frame),
                 *iotaps.rows(frame, at_stop=True)]
    if evaluated:
        # WHAT THE SHORT ROWS LEFT OUT is said beside them, as every short reply says it.
        seen["watches"], left = watches.at_stop(evaluated)
        seen.update(narrowing.omission(left, watches.STOP_HOW))
    if watched is not None and watched[1] is not None:
        seen["watch_hit"] = watched[1]
    return seen


def stop_logged_in(lines: list[str]) -> bool:
    """Whether the console logged, among `lines`, a stop of any family `survey` names off the
    log: a breakpoint's, a registerpoint's or a watchpoint's. What a run the console started
    looks for after each landing, since such a run sends no packet and the stop can land with
    the counter's tick; kept here, beside the survey, so the two name the same families."""
    return arming.listed_stop_in(lines) or watches.stop_line_in(lines)


#: The survey's keys that name a stop nobody's tool asked for, each popped into `cause`.
_NAMED_STOPS = ("watch_cause", "breakpoint_cause", "regpoint_cause")


def cut_by_a_stop(seen: dict[str, Any], pc: int) -> bool:
    """Whether the stop `seen` surveyed is one somebody ARMED (a watch, a row typed through
    `debug`, a registerpoint, a stop breakpoint of this server's at `pc` on the survey's cpu)
    rather than the end of the run a tool was counting: asked before `_remember` pops the
    names."""
    return any(key in seen for key in _NAMED_STOPS) or halts(pc, seen["cpu"])


def halts(pc: int, cpu: str | None) -> bool:
    """Whether a row this server armed that HALTS the machine sits at `pc` on `cpu`: a stop
    breakpoint, never a control. A control is a row too (the debugger counts through it), and its
    address is where a `gvblank` lands when it sits on the vblank handler, so a stop found
    ON a control is a stop that happened there, not one the control caused: a `stop` on a
    running machine would otherwise name the control as its cause, and a run by frames end
    after two frames at a control on the vblank handler. Two cpus run two programs, so a row is
    (cpu, pc), never the address alone (`breakpoints.bp_owned_at`)."""
    return breakpoints.bp_owned_at(pc, cpu, but=frozenset(STATE.controls)) is not None


def attribute(pc: int, cpu: str | None) -> str:
    """How a stop at `pc` on `cpu` is named when no tool asked for it: a breakpoint this server
    armed there, or a stop this server cannot attribute (one typed through `debug`, or an
    interrupt). A watchpoint's stop is named by the survey itself (`watch_cause`), which reads the
    packet."""
    if halts(pc, cpu):
        return breakpoints.breakpoint_name(pc, cpu) or f"breakpoint at {pc:#x}"
    return "stopped at no breakpoint this server armed"

def name_stop(ses: gs.Session) -> str:
    """`attribute` for the machine as it stands: its pc and the cpu it stopped on, which MAME
    makes the visible one at every stop."""
    return attribute(ses.current_pc(), cpus.visible_cpu(ses))


def mark_release(ses: gs.Session) -> None:
    """Stamp the run window at the moment the machine is released and left running: the
    emulated time now (read while it is still stopped, a clean console read) and the wall
    clock. The stop that ends the run, or `close` on a watched run, reads the pair back to
    report the speed the host held. Failing to read the clock is not fatal to the run: the
    window is simply not measured."""
    emulated = ses.emulated_seconds()
    STATE.run_release = None if emulated is None else {"emulated": emulated,
                                                       "wall": time.monotonic()}


def note_throttle_lift(ses: gs.Session, lines: list[str], mark: str) -> None:
    """When the throttle harness's lift mark first appears in error.log, the REAL-SPEED part
    of a run begins there, so the open speed window is reset to now: a `resume` that flew flat
    out to a late frame and dropped to real speed then reports the real-speed speed at `close`,
    not the blend of the fast ramp and the real-speed play. Reset once per session, and only
    while a run window is open. Observed near the lift because the natural way to learn the fly
    is done is `log_wait` on this mark; a mark seen long after the fact (a late `log`)
    would reset to a window of almost no wall time, which `average_speed` reports as none."""
    if STATE.throttle_seen or STATE.run_release is None:
        return
    if any(mark in line for line in lines):
        mark_release(ses)          # re-stamp: the real-speed window starts here
        STATE.throttle_seen = True


def average_speed(ses: gs.Session) -> dict[str, float] | None:
    """The speed the host held over the open run window, emulated seconds over wall seconds
    as a percent, and the two deltas; None when no window is open, the console will not read
    the emulated clock, or too little wall time passed to divide by. Clears the window: a
    speed is reported once, by the stop or the `close` that ends the run it belongs to."""
    release = STATE.run_release
    if release is None:
        return None
    STATE.run_release = None
    now_emulated = ses.emulated_seconds()
    wall = time.monotonic() - release["wall"]
    if now_emulated is None or wall < 0.01:
        return None
    emulated = now_emulated - release["emulated"]
    return {"percent": round(emulated / wall * 100, 2),
            "emulated_s": st.measured_s(emulated), "wall_s": st.measured_s(wall)}


def _remember(ses: gs.Session, seen: dict[str, Any], cause: str) -> tuple[dict[str, Any], str]:
    """The record of a surveyed stop, with `cause` replaced by the watch's account when the
    stop was a watchpoint's, or by the row's when a breakpoint typed through `debug` or a
    registerpoint made it: the packet and the console's log, not the caller, know that."""
    for key in _NAMED_STOPS:
        cause = seen.pop(key, cause)
    hit = seen.get("watch_hit")
    record = STATE.remember_stop(ses, int(seen["pc"], 16), seen["regs"], seen["frame"], cause,
                                 watch_hit=hit if isinstance(hit, dict) else None,
                                 cpu=seen["cpu"])
    return record, cause


def run_speed(ses: gs.Session) -> dict[str, Any]:
    """`average_speed` as the reply field of whatever ENDS a run, a stop or `close`, or nothing
    when no window was open. Every record of such a stop asks, the one a later contact finds
    included: a window left open there is closed by the next stop of any tool, over a span it
    never ran."""
    try:
        speed = average_speed(ses)
    except gs.SessionError as e:
        # THE END OF THE RUN IS REAL AND THE SPEED IS DECORATION: a clock that could not be
        # read is said on its account, which is published all the same.
        return {"average_speed": unavailable(str(e))}
    return {"average_speed": speed} if speed is not None else {}


def stop_reply(ses: gs.Session, scratch: Path, cause: str, **base: Any) -> dict[str, Any]:
    """What a stop ALWAYS returns, on top of the tool's own fields in `base`, and the record
    of it as the last stop."""
    return finish_stop(ses, survey(ses, scratch), cause, **base)


def finish_stop(ses: gs.Session, seen: dict[str, Any], cause: str, **base: Any) -> dict[str, Any]:
    """The reply and the record of a stop ALREADY surveyed, for a tool that has to read the
    survey before it can name its verdict (`run_for`: a watch that cut the run is a stop of
    its own, not a run that made no progress). A survey is one read of the machine and the
    log, so it is taken once and handed here. A stop that ENDS A RUN carries the speed the
    host held over it (`average_speed`), read from the window `resume` opened."""
    record, cause = _remember(ses, seen, cause)
    return menvelope.envelope({**base, "cause": cause, "stop_seq": record["seq"], **seen,
                               "cpu": or_unavailable(seen["cpu"], st.NO_CPU_READ_WHY),
                               "frame": st.frame_shown(seen["frame"]), **run_speed(ses)})


def observe_stop(ses: gs.Session, scratch: Path) -> None:
    """A STOP THE MACHINE REACHED ON ITS OWN IS RECORDED BY THE FIRST CONTACT THAT FINDS IT.
    The socket is asked, without waiting, whether the stub sent its stop packet; when the
    machine is stopped at a stop the record does not describe (the session's `stop_count`
    moved past the last record's), it is surveyed once, remembered, and the account rides on
    this contact's reply as `stopped_on_its_own`."""
    if ses.running and STATE.console_run:
        if console_run_ended(ses, scratch):
            _found(ses, scratch, "none: a run the console started")
        return
    if ses.running:
        ses.poll_stop(0.0)
    count = getattr(ses, "stop_count", None)
    if (count is None or ses.running or not STATE.last_stop
            or count == STATE.last_stop.get("stop_count")):
        return
    _found(ses, scratch, None)


def came_to_rest(ses: gs.Session, scratch: Path, wait: float, record: bool = True) -> bool:
    """Whether a released machine has stopped, asked by the proof its release allows: the
    stub's stop packet, waited for up to `wait`, for a run the stub started; for one the
    console started, which sends no packet, `console_run_ended`. `record` says who surveys
    that stop: here, as the first contact after it would (`observe_stop`), or the caller, which
    is about to survey it itself (`stop_reply`) and must not record it twice."""
    if ses.running and STATE.console_run:
        if console_run_ended(ses, scratch):
            if record:
                _found(ses, scratch, "none: a run the console started")
            return True
        time.sleep(wait)
        return False
    return bool(ses.poll_stop(wait))


def console_run_ended(ses: gs.Session, scratch: Path) -> bool:
    """Whether a run the console started has come to rest, the session told so when it has. No
    packet will come for it: the frame counter that a stop freezes is the proof, read as
    `run_for` reads it, unless the counter is what never moved (`console_run_unprovable`);
    then a stop the console logged proves it, read from where the last look ended and without
    moving the survey's mark."""
    if STATE.console_run_unprovable:
        lines, STATE.unprovable_peek = files.lines_since(
            scratch / "debug.log", max(STATE.unprovable_peek, STATE.debuglog_mark))
        if not stop_logged_in(lines):
            return False
    elif not frame_at_rest(ses):
        return False
    ses.running = False
    STATE.console_run = STATE.console_run_unprovable = False
    return True


def _found(ses: gs.Session, scratch: Path, packet: str | None) -> None:
    """Survey and remember a stop `observe_stop` found, named by where it is, and keep its
    account for the reply of the contact that found it: `packet` is what to say of the stop
    packet, or None for the one the record holds."""
    seen = survey(ses, scratch)
    record, _cause = _remember(ses, seen, attribute(int(seen["pc"], 16), seen["cpu"]))
    STATE.found_stop_last = {"stop_seq": record["seq"], "pc": record["pc"],
                             "cpu": or_unavailable(record["cpu"], st.NO_CPU_READ_WHY),
                             "frame": st.frame_shown(record["frame"]),
                             "cause": record["cause"],
                             "packet": record["packet"] if packet is None else packet,
                             **run_speed(ses)}


def record_own_stop(tool: str, cause: str = "the step it took before it refused") -> None:
    """A STOP THE REFUSING CALL MADE IS ITS OWN. `read_block`, `lua` and `screen_signature`
    buy their evaluation with a real single step, and some of their refusals come after it
    (an answer that names no block, a script that raised, one that never came), as do
    `state_write(method="load")`'s after the console loaded the state. Left unrecorded, that stop is
    found by
    the next contact and reported as the machine's own, at no breakpoint this server armed:
    a stop this server made, misattributed. So the refusal records it, under the tool's name,
    before its envelope is built. It never raises: a session that broke under the call is the
    refusal's own story, and the next contact's to find."""
    ses, scratch = STATE.ses, STATE.scratch
    if (ses is None or scratch is None or STATE.proc is None or STATE.proc.poll() is not None
            or ses.running or ses.broken
            or not STATE.last_stop
            or getattr(ses, "stop_count", None) in (None, STATE.last_stop.get("stop_count"))):
        return
    try:
        _remember(ses, survey(ses, scratch), f"{tool}: {cause}")
    except gs.SessionError:
        return


def record_stop(ses: gs.Session, scratch: Path, cause: str) -> dict[str, Any]:
    """Survey and record a stop a console command reached with no packet (a `focus` or an
    `ignore` that released the machine), so the next contact describes where it is; the
    record, with `cause` as the survey named it."""
    return _remember(ses, survey(ses, scratch), cause)[0]


def record_park(ses: gs.Session, scratch: Path) -> dict[str, Any]:
    """The park at the debugger right after `start` is stop 1: the survey the readers name
    until something moves the machine."""
    seen = survey(ses, scratch)
    _remember(ses, seen, "start")
    return seen


def require_stopped(ses: gs.Session, what: str) -> None:
    """Refuse `what` on a RUNNING machine, naming the last stop. A value read off a moving
    machine is a sample of no state, and the stop packet the stub sends on its own can land
    in front of the read's answer: the next read after a timed-out run comes back
    as something that is not hex."""
    if ses.running:
        stop = STATE.as_of()
        stopped = "pc" in stop
        on = f" on {stop['cpu']}" if stopped and isinstance(stop.get("cpu"), str) else ""
        where = (f"last seen stopped at pc {stop['pc']}{on} ({stop['cause']}, {stop['since_s']} s "
                 f"ago)" if stopped else "no stop recorded yet")
        raise gs.NotStopped(
            f"the machine was released and no stop has been read since, so it is taken as "
            f"RUNNING and {what} has no state to answer from; {where}. "
            "Wait for its own stop (`status` says `stopped_on_its_own` when one came; `log_wait` "
            "waits on what it logs), or `stop` it."
        )


def check_resume(seconds: float = 0.0, **_: Any) -> None:
    """`resume`'s machine-independent half. Zero is not an error here: it means no deadline, and
    the machine is left running. A positive number is a WAIT, and a wait has the ceiling every
    other wait in this server has: without it a single call could hold the server's one lock for
    as long as the caller cared to type."""
    vocab.check_wait(seconds, zero_means="no deadline")


def resume(ses: gs.Session, scratch: Path, seconds: float,
           progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `resume` tool."""
    check_resume(seconds)
    require_stopped(ses, "a second `resume`")
    mark_release(ses)      # the emulated clock read now, while it is still stopped
    clock = mprogress.Ticker(seconds, progress)
    try:
        ses.go()
        if seconds == 0:
            return menvelope.envelope({})     # a wait nobody asked for: no verdict, no time
        while not clock.expired():
            if ses.poll_stop(min(RESUME_POLL_S, clock.left())):
                break
            clock.tick("resume: running {elapsed:.0f}s of {seconds:g}s, no stop yet",
                       seconds=seconds)
    except gs.SessionError as e:
        return session_broke(ses, e, f"{clock.elapsed(1)} s into the wait",
                             "Nothing about the run was measured")
    if not ses.running:
        return _survey_read_stop(ses, scratch, attribute, verdict=contract.OTHER_STOP,
                                 waited_s=st.spent_s(clock.seconds()))
    return menvelope.envelope({
        "verdict": contract.TIMEOUT, "waited_s": st.spent_s(clock.seconds()),
        "note": f"no stop arrived within {seconds:g} s, so the machine was LEFT RUNNING; the "
                "readers refuse until a stop is read (`stop`, a breakpoint, `log_wait` "
                "meanwhile)",
    })


def frame_at_rest(ses: gs.Session, reads: int = 3, gap_s: float = 0.1) -> bool:
    """Whether the frame counter reads the same `reads` times `gap_s` apart: a stopped
    machine's does, a running one's moves. The assumption is a frame shorter than the gap,
    which holds at real speed for any board above ten frames a second; a driver slower than
    that, or a host throttled below it, reads at rest while running. A board with no counter
    reads the emulated clock instead (`read.rest_reading`), which moves whenever it runs.
    The proof `run_for` uses for a run the console started, shared here for `stop` and for
    the first contact after such a run."""
    seen: list[int | float] = []
    for i in range(reads):
        if i:
            time.sleep(gap_s)
        try:
            seen.append(read.rest_reading(ses))
        except gs.SessionError:
            if ses.broken:
                raise      # a LATCHED channel is not a moving machine: the tool answers it
            return False
    return len(set(seen)) == 1


def _survey_read_stop(ses: gs.Session, scratch: Path, name: Callable[[int, str | None], str],
                      **base: Any) -> dict[str, Any]:
    """The survey of a stop whose packet was just read, named by `name` from where it is: its
    pc and its cpu, both the survey's. An exchange that fails right behind a stop is where
    `run_to` latches too: the record would describe a machine this channel can no longer be
    asked about."""
    try:
        seen = survey(ses, scratch)
        return finish_stop(ses, seen, name(int(seen["pc"], 16), seen["cpu"]), **base)
    except gs.SessionError as e:
        return session_broke(ses, e, "after the stop was read", "The stop was not surveyed")


def _interrupt_or_row(pc: int, cpu: str | None) -> str:
    """A `stop`'s cause, by where it is and not by who asked: the packet the interrupt reads
    can be a BREAKPOINT's that fired in the same instant (a `stop` right after
    arming one at the vblank handler comes back at the handler's address)."""
    return attribute(pc, cpu) if halts(pc, cpu) else "interrupt"


def _stop_failed(ses: gs.Session, error: gs.SessionError) -> dict[str, Any]:
    """The refusal of a `stop` whose own release failed. A wait that ran out is not a broken
    channel: the machine stays marked RUNNING and the caller decides when to give up, with
    the way out in front of them. Anything else latches."""
    if isinstance(error, gs.Timeout):
        return menvelope.invalid("not_settled",
                                 f"the interrupt was not answered ({error}), so the machine may be "
                                 f"RUNNING and no stop was read. {STOP_RECOVERS}")
    return session_broke(ses, error, "under `stop`", "No stop was read")


def stop(ses: gs.Session, scratch: Path) -> dict[str, Any]:
    """The body of the `stop` tool."""
    if not ses.running:
        return menvelope.envelope({"interrupted": False,
                                   "note": "the machine was already stopped",
                                   "last_stop": STATE.as_of()})
    if STATE.console_run:
        # A run the console started answers no stop packet to the interrupt: the 0x03 goes
        # out and the stop is proved on the frame counter, as `run_for` proves its own.
        try:
            ses.halt()
        except gs.SessionError as e:
            return _stop_failed(ses, e)
        ses.drain_stop_reply()
        clock = mprogress.Ticker(CONSOLE_HALT_SETTLE_S, mprogress.no_progress)
        while not frame_at_rest(ses):
            if clock.expired():
                return menvelope.invalid("not_settled",
                                         f"the machine did not come to rest within "
                                         f"{CONSOLE_HALT_SETTLE_S} s of the interrupt: the frame "
                                         "counter still moves, so it may be RUNNING. "
                                         f"{STOP_RECOVERS}")
        ses.running = False
        STATE.console_run = STATE.console_run_unprovable = False
        return _survey_read_stop(ses, scratch, _interrupt_or_row, interrupted=True)
    try:
        ses.interrupt()
    except gs.SessionError as e:
        return _stop_failed(ses, e)
    return _survey_read_stop(ses, scratch, _interrupt_or_row, interrupted=True)


def contact() -> tuple[gs.Session, Path]:
    """The live machine and its scratch, whatever it is doing: the gate of the tools that
    answer on a RUNNING machine. A stop the machine reached on its own is recorded here, by
    whichever tool makes the first contact after it (`observe_stop`)."""
    ses, scratch = STATE.live()
    st.refuse_broken(ses)
    observe_stop(ses, scratch)
    st.refuse_broken(ses)      # a request inside the observation may have latched it
    return ses, scratch


def stopped(what: str) -> tuple[gs.Session, Path]:
    """The live machine, STOPPED, or the refusal that names the last stop: the gate of every
    reader and every advance.

    WHAT CROSSES THIS GATE AND WHAT DOES NOT. An argument whose validity depends on the machine is
    judged on the far side of it, because with no machine there is nothing to judge it against: a
    `ref` is a symbol in THAT machine's table. An argument whose validity does not -- a `length`, a
    regex, a `dest` this server requires to be absolute -- is judged by `mame_args` BEFORE the tool
    gets here, because it is exactly as wrong with a machine as without one and "no machine
    running" withholds the only thing the caller needed to hear.

    The rule is two-sided on purpose: judging everything before the gate tells a caller off about a
    `length` on a machine that does not exist, and judging nothing before it hides a refusal that
    needs no machine behind one.
    """
    ses, scratch = contact()
    require_stopped(ses, what)
    return ses, scratch
