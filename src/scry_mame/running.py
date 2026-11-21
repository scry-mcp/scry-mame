"""The running guest: stops, and the survey taken at the first contact after one."""

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

from scry_mame import (
    arming,
    breakpoints,
    cpus,
    files,
    iotaps,
    line_notes,
    read,
    regpoints,
    watches,
)
from scry_mame import declarations as dec
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import state as st
from scry_mame import tap as mtap
from scry_mame.state import STATE

DASM_BYTES = 32

RESUME_POLL_S = 0.1
CONSOLE_HALT_SETTLE_S = 2.0
STOP_RECOVERS = "`stop` recovers it; if `stop` fails as well, `close` then `start` is the way out"


def errorlog_block(lines: list[str], mark: int) -> dict[str, Any]:
    """The lines `error.log` gained from byte `mark`."""
    return log_marks.stop_block(lines, mark, "emulator", read.LOG_LIMIT_MAX)


def session_broke(ses: gs.Session, error: gs.SessionError, when: str, tail: str,
                  **fields: Any) -> dict[str, Any]:
    """Latch the session broken and answer the refusal. The stub honours an interrupt only
    between packets, so after this not even `stop` can be believed. A session already latched
    keeps its first reason."""
    ses.latch(str(error))
    return menvelope.invalid("session_broken",
                             f"the session broke {when}: {error}. {tail}. `close` it, then `start` "
                             "a new one", **fields)


def session_error_reply(error: gs.SessionError, tool: str,
                        tail: str = "Nothing this call read is handed back") -> dict[str, Any]:
    """A session error `tool` raised (anything but `NotStopped`), as its reply.

    A command too long, or a stub answer of no, leaves the channel in place and latches nothing;
    every other error may leave the two ends disagreeing where a packet starts, so it latches."""
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
    """Settle throttle and count-watch removals against what is already logged, without moving
    the error log's mark."""
    st.settle_throttles(files.errorlog_since(scratch, STATE.errorlog_mark)[0])
    mtap.read_removal_answers(scratch)


def still_pending(scratch: Path) -> dict[str, list[dict[str, Any]]]:
    """Throttles (by `tag`) and count-watch removals (by `call`) the machine has not confirmed.

    Always both lists; success is a row leaving."""
    settle_logged(scratch)
    return {
        "throttles_pending": [{"tag": r["tag"], "on": r["on"]}
                              for r in STATE.throttles_pending],
        "tallies_pending_removal": [{"tally_id": r["tally_id"],
                                     "call": st.sentinel_line(r["seq"])}
                                    for r in STATE.tally_removals if not r["state"]],
    }

def stop_registers(ses: gs.Session, cpu: str | None) -> dict[str, Any]:
    """The registers of `cpu` read on its own thread, or `available: false` with the reason;
    a cpu of None is read as the stub's first."""
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
    """One survey of a stopped machine: pc, registers, frame, listing, log since the last stop."""
    pc = ses.current_pc()
    # The cpu that stopped: MAME makes it the visible one at every stop
    # (`debugger_cpu::wait_for_debugger`).
    cpu = cpus.visible_cpu(ses)
    regs = stop_registers(ses, cpu)
    # Frame and expressions in one `print`; a refused list is retried for the frame alone.
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
    instruction: dict[str, Any]
    following: list[str] = []
    try:
        listing = read.dasm_lines(ses, scratch, pc, DASM_BYTES)
        instruction = line_notes.on_instruction(read.stop_instruction(listing[0], pc, cpu), cpu)
        following = listing[1:]
    except gs.SessionError as e:
        instruction = unavailable(str(e))
    from_mark = STATE.errorlog_mark
    since, STATE.errorlog_mark = files.errorlog_since(scratch, from_mark)
    # Judged off the lines in hand: a pending throttle proves itself by its tag in this log.
    st.settle_throttles(since)
    mtap.read_removal_answers(scratch)
    seen: dict[str, Any] = {
        "pc": st.hex_addr(pc),
        "cpu": cpu,
        "frame": frame,
        "regs": regs,
        "instruction": instruction,
        **({"following": following} if following else {}),
        "errorlog": errorlog_block(since, from_mark),
    }
    # Named before the watches are evaluated, which moves `before` on. A typed breakpoint or
    # registerpoint is named only when no row this server armed is at the pc.
    since = arming.debuglog_since(scratch)
    watched = watches.watch_stop(ses, since)
    fresh: dict[dec.Owner, bytes] = {}
    if watched is not None:
        seen["watch_cause"], fresh = watched[0], watched[2]
    elif not halts(pc, cpu):
        # A registerpoint as the newest listed stop outranks a typed breakpoint's naming.
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
        seen["watches"], left = watches.at_stop(evaluated)
        seen.update(narrowing.omission(left, watches.STOP_HOW))
    if watched is not None and watched[1] is not None:
        seen["watch_hit"] = watched[1]
    return seen


def stop_logged_in(lines: list[str]) -> bool:
    """Whether `lines` hold a stop of any family `survey` names off the log."""
    return arming.listed_stop_in(lines) or watches.stop_line_in(lines)


#: Survey keys naming a stop nobody's tool asked for.
_NAMED_STOPS = ("watch_cause", "breakpoint_cause", "regpoint_cause")


def cut_by_a_stop(seen: dict[str, Any], pc: int) -> bool:
    """Whether the surveyed stop was armed by somebody rather than being the end of the run a
    tool was counting; asked before `_remember` pops the names."""
    return any(key in seen for key in _NAMED_STOPS) or halts(pc, seen["cpu"])


def halts(pc: int, cpu: str | None) -> bool:
    """Whether a stop breakpoint of this server's sits at `pc` on `cpu`. A control is excluded:
    a stop found on one happened there, it was not caused by it. Rows are (cpu, pc)."""
    return breakpoints.bp_owned_at(pc, cpu, but=frozenset(STATE.controls)) is not None


def attribute(pc: int, cpu: str | None) -> str:
    """How an unrequested stop at `pc` on `cpu` is named."""
    if halts(pc, cpu):
        return breakpoints.breakpoint_name(pc, cpu) or f"breakpoint at {pc:#x}"
    return "stopped at no breakpoint this server armed"

def name_stop(ses: gs.Session) -> str:
    """`attribute` for the machine as it stands."""
    return attribute(ses.current_pc(), cpus.visible_cpu(ses))


def mark_release(ses: gs.Session) -> None:
    """Stamp the run window (emulated time, wall clock) at release, for the speed reported at the
    stop or `close`."""
    emulated = ses.emulated_seconds()
    STATE.run_release = None if emulated is None else {"emulated": emulated,
                                                       "wall": time.monotonic()}


def note_throttle_lift(ses: gs.Session, lines: list[str], mark: str) -> None:
    """Reset the open speed window at the throttle harness's lift mark, so `close` reports
    real-speed play and not its blend with the fast ramp. Once per session."""
    if STATE.throttle_seen or STATE.run_release is None:
        return
    if any(mark in line for line in lines):
        mark_release(ses)
        STATE.throttle_seen = True


def average_speed(ses: gs.Session) -> dict[str, float] | None:
    """Emulated over wall seconds as a percent, with the two deltas; None when no window is
    open, the clock is unreadable or too little wall time passed. Clears the window."""
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
    """The record of a surveyed stop, `cause` replaced by the one the packet or log names."""
    for key in _NAMED_STOPS:
        cause = seen.pop(key, cause)
    hit = seen.get("watch_hit")
    record = STATE.remember_stop(ses, int(seen["pc"], 16), seen["regs"], seen["frame"], cause,
                                 watch_hit=hit if isinstance(hit, dict) else None,
                                 cpu=seen["cpu"])
    return record, cause


def run_speed(ses: gs.Session) -> dict[str, Any]:
    """`average_speed` as the reply field of whatever ends a run. Every record of such a stop
    asks, or a window left open would be closed by a later stop over a span it never ran."""
    try:
        speed = average_speed(ses)
    except gs.SessionError as e:
        # The end of the run is real and the speed decoration.
        return {"average_speed": unavailable(str(e))}
    return {"average_speed": speed} if speed is not None else {}


def stop_reply(ses: gs.Session, scratch: Path, cause: str, **base: Any) -> dict[str, Any]:
    """What a stop always returns on top of `base`, and its record as the last stop."""
    return finish_stop(ses, survey(ses, scratch), cause, **base)


def finish_stop(ses: gs.Session, seen: dict[str, Any], cause: str, **base: Any) -> dict[str, Any]:
    """Reply and record for a stop already surveyed (`run_for` reads the survey first)."""
    record, cause = _remember(ses, seen, cause)
    return menvelope.envelope({**base, "cause": cause, "stop_seq": record["seq"], **seen,
                               "cpu": or_unavailable(seen["cpu"], st.NO_CPU_READ_WHY),
                               "frame": st.frame_shown(seen["frame"]), **run_speed(ses)})


def observe_stop(ses: gs.Session, scratch: Path) -> None:
    """Record a stop the machine reached on its own, at the first contact that finds it; the
    account rides on that reply as `stopped_on_its_own`."""
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
    """Whether a released machine has stopped. `record` says whether to survey it here or leave
    that to the caller."""
    if ses.running and STATE.console_run:
        if console_run_ended(ses, scratch):
            if record:
                _found(ses, scratch, "none: a run the console started")
            return True
        time.sleep(wait)
        return False
    return bool(ses.poll_stop(wait))


def console_run_ended(ses: gs.Session, scratch: Path) -> bool:
    """Whether a console-started run has come to rest, proved by the frame counter or, when it
    never moved, by a stop the console logged."""
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
    """Survey and remember a stop `observe_stop` found; `packet` is what to say of its packet,
    None for the recorded one."""
    seen = survey(ses, scratch)
    record, _cause = _remember(ses, seen, attribute(int(seen["pc"], 16), seen["cpu"]))
    STATE.found_stop_last = {"stop_seq": record["seq"], "pc": record["pc"],
                             "cpu": or_unavailable(record["cpu"], st.NO_CPU_READ_WHY),
                             "frame": st.frame_shown(record["frame"]),
                             "cause": record["cause"],
                             "packet": record["packet"] if packet is None else packet,
                             **run_speed(ses)}


def record_own_stop(tool: str, cause: str = "the step it took before it refused") -> None:
    """Record the stop a refusing call made with its own single step, else the next contact
    reports it as the machine's own. Never raises."""
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
    """Survey and record a stop a console command reached with no packet."""
    return _remember(ses, survey(ses, scratch), cause)[0]


def record_park(ses: gs.Session, scratch: Path) -> dict[str, Any]:
    """The park after `start` is stop 1."""
    seen = survey(ses, scratch)
    _remember(ses, seen, "start")
    return seen


def require_stopped(ses: gs.Session, what: str) -> None:
    """Refuse `what` on a running machine, naming the last stop: a read off a moving machine
    is a sample of no state."""
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
    """`resume`'s machine-independent half: zero means no deadline, a positive wait has the
    server-wide ceiling."""
    vocab.check_wait(seconds, zero_means="no deadline")


def resume(ses: gs.Session, scratch: Path, seconds: float,
           progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `resume` tool."""
    check_resume(seconds)
    require_stopped(ses, "a second `resume`")
    mark_release(ses)
    clock = mprogress.Ticker(seconds, progress)
    try:
        ses.go()
        if seconds == 0:
            return menvelope.envelope({})
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
    """Whether the frame counter reads the same `reads` times `gap_s` apart. Assumes a frame
    shorter than the gap; a board with no counter reads the emulated clock."""
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
        if seen[-1] != seen[0]:
            return False
    return True


def _survey_read_stop(ses: gs.Session, scratch: Path, name: Callable[[int, str | None], str],
                      **base: Any) -> dict[str, Any]:
    """Survey a stop whose packet was just read, named by `name`. A failed exchange right
    behind a stop latches."""
    try:
        seen = survey(ses, scratch)
        return finish_stop(ses, seen, name(int(seen["pc"], 16), seen["cpu"]), **base)
    except gs.SessionError as e:
        return session_broke(ses, e, "after the stop was read", "The stop was not surveyed")


def _interrupt_or_row(pc: int, cpu: str | None) -> str:
    """A `stop`'s cause by where it is: a breakpoint may have fired in the same instant."""
    return attribute(pc, cpu) if halts(pc, cpu) else "interrupt"


def _stop_failed(ses: gs.Session, error: gs.SessionError) -> dict[str, Any]:
    """The refusal of a `stop` whose release failed; a timeout leaves the machine marked
    running, anything else latches."""
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
        # A console run answers no stop packet: the frame counter proves the stop.
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
    """The live machine, whatever it is doing; records a stop it reached on its own."""
    ses, scratch = STATE.live()
    st.refuse_broken(ses)
    observe_stop(ses, scratch)
    st.refuse_broken(ses)      # a request inside the observation may have latched it
    return ses, scratch


def stopped(what: str) -> tuple[gs.Session, Path]:
    """The live machine, stopped, or the refusal naming the last stop.

    Arguments whose validity depends on the machine are judged past this gate; the rest are
    judged by `args` before it."""
    ses, scratch = contact()
    require_stopped(ses, what)
    return ses, scratch
