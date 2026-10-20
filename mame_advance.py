"""The ADVANCE family: run to a place with a control, run for emulated time, step.

Everything here moves the machine and hands it back STOPPED, and says how it stopped:
`run_to` with the control's hit count (a silence is a measurement only when the control
fired), `run_for` with the frame counter read before and after (the stub answers the
console while the machine still runs, so the counter is polled until it stops moving),
`step` with the program counter. Every stop comes back as the one survey `mame_running`
makes (registers, frame, the listing at the program counter, the log since the last
stop). Advancing does not count as altering. A bounded wait reports its progress. The
breakpoints, which are DECLARATIONS, live in `mame_arming`.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Hashable, Iterator
from pathlib import Path
from typing import Any, TypeVar

from scry_core import cancel, prose
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core.reply_contract import unavailable

import gdb_session as gs
import mame_breakpoints as breakpoints
import mame_clear as mclear
import mame_conditions as conditions
import mame_cpus as cpus
import mame_cycles as cycles
import mame_declarations as dec
import mame_envelope as menvelope
import mame_files as files
import mame_inputs as inputs
import mame_lists as mlists
import mame_read as read
import mame_running as running
import mame_state as st
import mame_watches as watches
from mame_state import STATE

# How `run_for` knows the machine has STOPPED, since the stub tells it nothing: MAME's frame
# counter, read through the console, stops moving. Three equal readings a tenth of a second apart
# is a machine that has not drawn a frame in that time, which a running one does unless it
# emulates below a few frames per second; the poll is bounded by the caller's `seconds`.
FRAME_POLL_S = 0.1
FRAME_STABLE_READS = 3
# How often `run_to` asks the socket for the stop: the deadline is honoured to this, and it is
# NOT the progress cadence (`PROGRESS_EVERY_S`), which is a different decision.
RUN_POLL_S = 0.1
# Between the two readings that confirm a `gvblank` landed: a console round trip is
# milliseconds and the run to the next vblank is less, so the pause is a few of those and
# never the `gtime` poll's, which is paid once per frame here and would make a run by
# frames cost the poll and not the emulation.
VBLANK_SETTLE_S = 0.002
CONTROL_DASM_BYTES = 16     # a few instructions at the control: is it code, and which
CONTROL_HINT = ("a control is the ENTRY of something periodic (the vblank or timer interrupt "
                "handler, the frame loop's first instruction), not a point inside a handler "
                "that only some path reaches; `control_dasm` shows whether the address decodes "
                "as code, and `history` at a stop shows what actually runs")


Reading = TypeVar("Reading", bound=Hashable)


def wait_for_rest(readings: list[Reading], read_counter: Callable[[], Reading], bound_s: float,
                  *, sleep_first: bool = False,
                  progress: mprogress.Progress = mprogress.no_progress,
                  report: Callable[[mprogress.Ticker], None] | None = None) -> bool:
    """Read the counter (`read_counter`, any reading that stops changing at rest) into
    `readings`, `FRAME_POLL_S` apart, until the last `FRAME_STABLE_READS` agree (True) or
    `bound_s` passes (False). A read that raises
    propagates, and what was read before it stays in `readings`, since a caller counts them.
    `sleep_first` waits before each read rather than after it, for the reads that follow an
    interrupt; `report` ticks the caller's progress line between two reads."""
    clock = mprogress.Ticker(bound_s, progress)
    while True:
        if sleep_first:
            time.sleep(FRAME_POLL_S)
        readings.append(read_counter())
        tail = readings[-FRAME_STABLE_READS:]
        if len(tail) == FRAME_STABLE_READS and len(set(tail)) == 1:
            return True
        if clock.expired():
            return False
        if report is not None:
            report(clock)
        if not sleep_first:
            time.sleep(FRAME_POLL_S)

def check_run_to(ref: str = "", seconds: float = 30.0, condition: str = "",
                 control: str = "", **_: Any) -> None:
    """`run_to`'s machine-independent half: that a run needs somewhere to run TO, the bound, the
    shape of a condition, and the shape of a `control` as of any ref, judged before a control is
    armed and persisted. That the control is not the target's address needs the table to
    resolve both, and stays below."""
    if not ref or not ref.strip():
        raise st.Invalid("bad_argument", "run_to needs a ref: a symbol or a `0x` address")
    inputs.check_ref(ref)
    if control.strip():
        inputs.check_ref(control, "control")
    inputs.seconds_bound(seconds)
    if condition.strip():
        conditions.check_condition(condition)


def check_run_for(milliseconds: int = 0, frames: int = 0, seconds: float = 30.0,
                  **_: Any) -> None:
    """`run_for`'s machine-independent half: two different mistakes, said apart."""
    check_run_bound(milliseconds, frames, seconds, "run_for")


def check_run_bound(milliseconds: int, frames: int, seconds: float, what: str) -> None:
    """The bound of a run as `run_for` takes it, judged for `what`, the tool named in the one
    sentence: `trace` bounds its run the same way and is told off in its own name."""
    inputs.natural("milliseconds", milliseconds, " is not a count of milliseconds: an integer, "
                   "never negative")
    inputs.natural("frames", frames, " is not a count of frames: an integer, never negative")
    if (milliseconds > 0) == (frames > 0):
        raise st.Invalid("bad_argument",
                         f"{what} takes exactly one of `milliseconds` and `frames`, above zero")
    # THE BOUND ON THE WAIT, the same one every wait in this server has.
    inputs.seconds_bound(seconds)


STEP_MODES = ("into", "over")


def step_max() -> int:
    """THE LONGEST WALK ONE `step` TAKES, derived: an `over` may wait `CONSOLE_HALT_SETTLE_S`
    for its landing, so this many of them fit inside the ceiling every other wait here takes,
    and the one lock is never held longer than a bounded call holds it. A longer walk is
    `run_to` or `run_for`. A function, read at the call: `mame_running` reaches this module
    through its own imports, so at import time its constant does not exist yet."""
    return int(inputs.WAIT_MAX_S // running.CONSOLE_HALT_SETTLE_S)


def check_step(count: int = 1, mode: str = "into", **_: Any) -> None:
    """`step`'s machine-independent half: how many, and which of two words."""
    inputs.count("count", count, step_max(), ": a longer walk is `run_to` or `run_for`")
    inputs.one_of("mode", mode, STEP_MODES)


# WHY, for the reader of this code (the client gets the docstring above the code):
#
# The control is not bureaucracy: four different mistakes leave a MAME breakpoint silent (a wrong
# address space, a symbol that resolved to the ROM copy, a routine behind a coin nobody inserted,
# a machine parked on the red warning), and all four look exactly like "that routine is never
# called". Only a control that DID fire turns that silence into a measurement. A breakpoint set
# while the machine runs is not among them: the stub takes a `Z0` sent to a running machine, and
# it fires (`breakpoint_at` rests on it).
#
# THE CONTROL IS DECLARED, NOT ARMED PER RUN, AND MAME COUNTS IT. A control is a breakpoint
# declaration with `role="control"`: a console row whose condition `(++tempN)==0` counts every
# hit and never halts, so the machine is never stopped for it and the count is one `print`.
# `run_to` arms the target alone and reads, before and after the run, the counts of the
# controls on the target's cpu. MAME counts, not the stub: a control hot enough to be a good one
# fires often, and a round trip per firing would starve the progress tick. A run that names a
# `control` declares it (or adopts it) first.
def run_to(ses: gs.Session, scratch: Path, ref: str, control: str, seconds: float,
           progress: mprogress.Progress = mprogress.no_progress, disarm_watches: bool = False,
           condition: str = "", cpu: str = "") -> dict[str, Any]:
    """The body of the `run_to` tool, with the armed watches held for the pass on request: the
    target armed on `cpu`, or on the visible cpu when none is named."""
    check_run_to(ref, seconds, condition)
    # The cpu is judged BEFORE the control is declared, so a cpu the machine lacks changes
    # nothing, and the target is a name of that cpu's table.
    on = cpus.chosen(ses, cpu)
    a_target = STATE.resolve(ref, on)
    if condition.strip():
        # The target's command is judged against the stub's packet BEFORE the control is
        # declared and the watches disarmed, so its refusal changes nothing.
        ses.console_packet(breakpoints.bp_command(
            a_target, conditions.console_condition(condition, on), on))
    if control.strip():
        # The target and the control are both resolved BEFORE the control is declared, so a
        # refused call leaves nothing in the store to re-arm at a later `start`.
        try:
            a_control = STATE.resolve(control, on)
        except inputs.BareHex:
            raise
        except st.Invalid:
            return _control_unresolved(control, on)
        if a_control == a_target:
            raise st.Invalid("bad_argument",
                             "the control cannot be the same address as the target")
        # ON THE TARGET'S CPU: a control proves the run reached something hot in the program
        # the target is in.
        declared = breakpoints.breakpoint_at(ses, control, "auto", role="control", cpu=on or "")
        if declared.get("status") != "ok":
            return declared
        if not declared.get("armed"):
            return menvelope.invalid("bad_argument",
                                     f"the control {control} is declared but not armed "
                                     f"({declared.get('state')}): a control counts only once it "
                                     "resolves to an address in this build", control=control)
    if not counting(on):
        # ONLY THE TARGET'S CPU'S CONTROLS COUNT (REFERENCE.md, Advancing the machine).
        where = f" on {on}, the target's cpu" if on else ""
        elsewhere = sorted({c or "an unknown cpu" for _ref, c in STATE.controls})
        listed = f" (the controls declared are on {', '.join(elsewhere)})" if elsewhere else ""
        named = f", cpu=\"{on}\"" if on else ""
        raise st.Invalid("bad_argument",
                         f"no control is declared{where}{listed}: `run_to` measures nothing "
                         "without one. Declare a routine known to be hot with `breakpoint_at("
                         f"ref, role=\"control\"{named})`, or name it here as `control`")
    return _with_watches_disarmed(ses, disarm_watches,
                    lambda: _run_to(ses, scratch, ref, seconds, on, progress, condition))


def _control_unresolved(control: str, on: str | None) -> dict[str, Any]:
    """The refusal for a `control` name that resolves in no table of the target's cpu: it
    names that cpu, and when the name is a control already declared on ANOTHER cpu it says
    so, naming that cpu and the declaration that would put one on the target's. Without the
    two cpus named, a caller goes looking for a broken declaration that is not broken."""
    where = f"{on}'s" if on else "the target cpu's"
    named = f", cpu=\"{on}\"" if on else ""
    elsewhere = sorted(c or "an unknown cpu" for r, c in STATE.controls
                       if r.strip().upper() == control.strip().upper() and c != on)
    if elsewhere:
        return menvelope.invalid("unknown_ref",
                                 f"the control {control} does not resolve in {where} symbol table: "
                                 f"it is a control declared on {', '.join(elsewhere)}, and a "
                                 f"control counts only on the target's cpu. Declare one there with "
                                 f"`breakpoint_at(ref, role=\"control\"{named})`, or name a ref of "
                                 f"{where} table as `control`",
                                 control=control, cpu=on, control_on=elsewhere)
    return menvelope.invalid("unknown_ref",
                             inputs.not_a_ref("the control", control, on, then=(
                                 ", so nothing was declared (a control counts only once it "
                                 "resolves to an address in this build)")),
                             control=control, cpu=on)


def _with_watches_disarmed(ses: gs.Session, disarm: bool,
                           run: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run `run` with every armed change watch disarmed when `disarm` says so, re-arming
    them afterwards whatever the run answered, and say in the reply which were disarmed and
    which came back listed. Without `disarm` the reply is the run's own."""
    if not disarm:
        return run()
    disarmed = watches.disarm_for_pass(ses)
    rearmed: list[dec.Owner] = []
    try:
        reply = run()
    finally:
        # Over a session the run BROKE nothing is re-armed: the list would be read back off a
        # channel that lost its place, and the reply says which watches stayed disarmed. A
        # re-arm that fails LATCHES instead of raising, so it never hides the run's own reply
        # (or its exception) behind a second one.
        if not ses.broken:
            try:
                rearmed = watches.rearm_after_pass(ses, disarmed)
            except gs.SessionError as e:
                ses.latch(f"re-arming the watches after the pass failed: {e}")
    # A latch the re-arm made is newer than the block the run built: `mame_mcp.tool`
    # composes the block after the body, so the reply says the channel broke.
    if rearmed and isinstance(reply.get("watches"), list):
        watches.place_after_pass(ses, reply["watches"], rearmed)
    reply["disarmed_watches"] = [dec.owner_fields(owner) for owner in disarmed]
    if rearmed != disarmed:
        reply["not_rearmed"] = [dec.owner_fields(owner) for owner in disarmed
                                if owner not in rearmed]
    return reply


def counting(on: str | None) -> list[dec.Owner]:
    """The controls that validate a target on `on`: those on its cpu, or, when either cpu is
    unknown, the control by its address alone, as a row's adoption falls back."""
    return [owner for owner in STATE.controls if cpus.same_cpu(on, owner[1])]


def _hits(before: dict[dec.Owner, int], after: dict[dec.Owner, int],
          owners: list[dec.Owner]) -> list[dict[str, Any]]:
    """Each of `owners`' hits over ONE run, named by its ref and cpu: the count after minus the
    count before. A count that went DOWN is a temp somebody reset under the run (`debug`), and
    the honest reading is then the count after, which is at least the hits since the reset."""
    return [{**dec.owner_fields(r),
             "hits_in_run": after[r] - before[r] if after[r] >= before[r] else after[r]}
            for r in after if r in owners]


def _target_not_listed(ses: gs.Session, armed_as: str,
                       row: dict[str, Any] | None) -> dict[str, Any]:
    """The refusal of a target the console took and did not list as sent, BEFORE the machine
    moved. A row listed without its condition is armed all the same and nobody would own it,
    so it goes first, or every later run would stop there as at a foreign row."""
    if row is not None:
        ses.monitor(mclear.clear_command("breakpoint", row["index"]))
    return menvelope.invalid("readback_refused",
                             f"the console took `{armed_as}` and its `bplist` "
                             + ("lists it without its condition, so that row was removed"
                                if row is not None else "does not list it: nothing is armed there")
                             + ", and the run was not started", control_hits=0)


def _run_to(ses: gs.Session, scratch: Path, ref: str, seconds: float, on: str | None,
            progress: mprogress.Progress = mprogress.no_progress,
            condition: str = "") -> dict[str, Any]:
    """The run itself: the target armed on `on` through the console (with its `condition` when
    there is one) and read back, the wait, the survey, the controls' counts around it, the target
    removed by its index; the reply carries the condition as the console read it."""
    cond = conditions.console_condition(condition, on) if condition.strip() else ""
    a_target = STATE.resolve(ref, on)
    owners = counting(on)
    # A CONTROL ON ANOTHER CPU IS ANOTHER PLACE: only one on the target's cpu sits where the
    # target would stop.
    if any(breakpoints.control_at(owner)[0] == a_target for owner in owners):
        raise st.Invalid("bad_argument",
                         f"the target {ref} is at the same address as a control on its cpu: a "
                         "control never halts, so nothing would stop there")
    held = mlists.bp_held(ses)
    # A ROW OF ANOTHER CPU AT THE SAME ADDRESS IS ANOTHER PLACE: a stop there is told from the
    # target's by its cpu, and the removal goes by index.
    taken = next((r for r in mlists.rows_at(held, a_target)
                  if cpus.same_cpu(on, r["cpu"])), None)
    if taken is not None:
        # A STOP AT AN ADDRESS TWO ENTRIES SHARE CANNOT BE ATTRIBUTED: the packet names the
        # address, not the entry, so a declared breakpoint there would be read as the target
        # (measured: a declaration's condition held, the run's did not, and the reply said
        # TARGET); and the list holds both, so the removal would take the wrong one.
        what = f" (condition {taken['condition']})" if taken.get("condition") else ""
        raise st.Invalid("bad_argument",
                         f"the target {ref} already has breakpoint "
                         f"{mclear.row_index(taken['index'])} at "
                         f"{a_target:#x}{what}: a stop there could not be told from the "
                         "target's. Clear it (`breakpoint_clear`) and run again")
    before = breakpoints.control_counts(ses)
    # THE TARGET IS ARMED ON ITS CPU, named, like every row (`mame_breakpoints.bp_command`), and
    # removed by its index.
    armed_as = breakpoints.bp_command(a_target, cond, on)
    ses.monitor(armed_as)
    # READ THE LIST BACK before the machine moves, as `breakpoint_at` does: a target the
    # console then does not list came back TIMEOUT beside a control that fired, which the
    # contract reads as "the routine never ran".
    row = mlists.armed_row(held, mlists.bp_held(ses), a_target, cpu=on)
    if row is None or (cond and not row.get("condition")):
        return _target_not_listed(ses, armed_as, row)
    clock = mprogress.Ticker(seconds, progress)
    verdict = contract.TIMEOUT
    broken: gs.SessionError | None = None
    try:
        ses.go()
        while not clock.expired():
            clock.tick("run_to {ref}: running {elapsed:.0f}s of {seconds:g}s",
                       ref=ref, seconds=seconds)
            if not ses.poll_stop(min(RUN_POLL_S, clock.left())):
                continue
            pc = ses.current_pc()
            # A WATCHPOINT'S STOP IS NOT THE TARGET even at the target's own address: the
            # packet says what stopped the machine, and the survey names the watch. Nor is
            # another cpu's stop there: two cpus run two programs.
            stopped_on = cpus.visible_cpu(ses)
            if (pc == a_target and watches.watch_packet_addr(ses) is None
                    and cpus.same_cpu(on, stopped_on)):
                verdict = contract.TARGET
            else:
                verdict = contract.OTHER_STOP
            break
    except gs.SessionError as e:
        # The stub closed the connection, or sent something that was not a stop: the session
        # cannot be trusted, and the reply says so instead of dressing it as a TIMEOUT or
        # escaping as a traceback.
        broken = e
    finally:
        # A TIMEOUT leaves the machine RUNNING, and a running target will not serve memory reads:
        # Measured live, the next `read` came back as something that was not hex at all. The
        # session looked alive and answered garbage. So it is stopped before returning, and the
        # breakpoint is only removed once it is, because removing it on a running target is
        # the same gamble. On a broken session the removal is attempted and its failure is
        # not the news.
        unanswered: gs.Timeout | None = None
        if verdict == contract.TIMEOUT and broken is None:
            try:
                ses.interrupt()
            except gs.Timeout as e:
                unanswered = e
            except gs.SessionError as e:
                broken = e         # the two cases `stop` tells apart for its own interrupt
        def disarm() -> bool:
            """The row removed by its index, and READ BACK: the console answers a removal it
            could not make in words (`Invalid breakpoint number`), never as a refusal."""
            ses.monitor(mclear.clear_command("breakpoint", row["index"]))
            return mlists.row_at_index(mlists.bp_held(ses), row["index"]) is None

        # A removal the list does not confirm is an answer: the channel kept its place, so the
        # stop the run reached is still a measurement, and the reply says the target may still
        # be armed. Anything else (a request that ran out, a connection gone) breaks it.
        try:
            target_disarmed = disarm()
        except st.Invalid:
            target_disarmed = False
        except gs.SessionError as e:
            target_disarmed = False
            if broken is None and not isinstance(e, gs.Refused):
                broken = e

    if broken is not None:
        return running.session_broke(ses, broken, f"{clock.elapsed(1)} s into the run",
                                     f"Nothing about {ref} was measured", control_hits=0)
    # THE STOP PACKET CAN LAND LATE: the target's removal is a `request`, which notes a stop
    # that arrives in front of its answer, so the flag is read again after it. A machine that
    # did stop is the ordinary TIMEOUT, surveyed, and `how` says the answer came late.
    if unanswered is not None and ses.running:
        # THE RUN WAS STARTED BY `c`, so the stub WILL send its stop packet when the machine
        # stops and `stop` is the recovery that waits for it: `running` stays as `go` left
        # it and `console_run` is not set, which would make `stop` ignore that packet.
        return menvelope.invalid("not_settled",
                                 f"the interrupt at the bound was not answered ({unanswered}), so "
                                 f"the machine may be RUNNING and nothing about {ref} was "
                                 "measured; `target_disarmed` says whether the temporary "
                                 f"breakpoint's removal was confirmed. {running.STOP_RECOVERS}",
                                 control_hits=0, target_disarmed=target_disarmed)
    controls = _hits(before, breakpoints.control_counts(ses), owners)
    control_hits = sum(c["hits_in_run"] for c in controls)
    at_bound = "interrupt at the bound" + (", answered late" if unanswered is not None else "")
    # A removal that was not confirmed, refused or run under an unanswered interrupt, is said
    # on the stop's reply as it is on `not_settled`'s.
    late: dict[str, Any] = ({} if unanswered is None and target_disarmed
                            else {"target_disarmed": target_disarmed})
    if not target_disarmed:
        late["note"] = (f"the temporary breakpoint at {ref} may still be armed (row "
                        f"{mclear.row_index(row['index'])}), so a later run may stop there; "
                        f"{mclear.pasted_clear('breakpoint', row['index'])} removes it")
    how = ({contract.TARGET: f"target {ref}", contract.TIMEOUT: at_bound}.get(verdict)
           or running.name_stop(ses))
    if verdict == contract.OTHER_STOP and control_hits == 0:
        # THE RUN WAS CUT BEFORE THE CONTROL HAD ITS CHANCE: another stop (a watch, a
        # registerpoint, a foreign breakpoint) ended the run first, so the control's silence
        # over that shortened window says nothing about the control, and calling it cold would
        # send the caller to doubt a good address. The stop itself is surveyed and named as
        # what it was.
        return running.stop_reply(ses, scratch, how, status="INVALID", code="cut_by_other_stop",
                                  control_hits=0, controls=controls, **late, message=(
            f"another stop cut the run before any control could fire, so neither {ref} nor "
            "the controls were measured over the window asked for; `how` says what stopped "
            "it. Clear what stopped it, or, for a watch, disarm the watches for the pass "
            "(`disarm_watches=True`), and run "
            "again"))
    if verdict != contract.TARGET and control_hits == 0:
        # INVALID, and still a STOP: the machine is where the bound or the other stop left
        # it, and the survey rides on this reply like any other's. Left unrecorded, the next
        # contact found a stop the record did not describe and reported this server's own
        # interrupt as `stopped_on_its_own`, attributed to no breakpoint.
        # A SILENT CONTROL HAS TWO CAUSES THAT READ THE SAME: the address is not code, or it
        # is code that runs less often than assumed (a branch inside a handler rather than
        # the handler's entry). The listing at each control separates the first from the
        # second without another pass; the hint says what a control is chosen from.
        control_dasm: list[dict[str, Any]] = []
        for owner in owners:
            # ON THE CONTROL'S OWN CPU: the stop may have left another one visible.
            at, on = breakpoints.control_at(owner)
            try:
                control_dasm.append({**dec.owner_fields(owner), "dasm": read.dasm_lines(
                    ses, scratch, at, CONTROL_DASM_BYTES, on)})
            except gs.SessionError as e:
                control_dasm.append({**dec.owner_fields(owner),
                                     "dasm": unavailable(str(e))})
        names = ", ".join(ref for ref, _cpu in owners)
        # ONE NOTE: the target's removal, when unconfirmed, is said beside the control's hint.
        silent = {**late, "note": st.join_notes(CONTROL_HINT, late.get("note"))}
        return running.stop_reply(ses, scratch, how, status="INVALID", code="control_silent",
                                  control_hits=0, controls=controls, control_dasm=control_dasm,
                                  **silent, message=(
            f"the control ({names}) never fired, so {ref} not firing means nothing. "
            "Check that the control really is hot on this screen."))
    own: dict[str, Any] = {"condition": cond} if cond else {}
    seen = running.survey(ses, scratch)
    if verdict == contract.TARGET:
        # THE ROW AT THE TARGET IS THE RUN'S OWN, even while a refused removal leaves it
        # listed: the survey would otherwise name it a row typed through `debug`.
        seen.pop("breakpoint_how", None)
    return running.finish_stop(ses, seen, how, verdict=verdict, control_hits=control_hits,
                               controls=controls, **own, **late)


# WHY, for the reader of this code (the client gets the docstring above the code):
#
# `gtime` ANSWERS AT ONCE, and the console then answers `print frame` WHILE THE MACHINE IS STILL
# RUNNING, with a mid-run count, so draining a stop reply and reading the counter once would hand
# back a running machine under the verdict ELAPSED. The counter (on a board with none, the
# emulated clock) is polled until `FRAME_STABLE_READS` readings agree, `FRAME_POLL_S` apart,
# bounded by `seconds` (`wait_for_rest`).

def run_for(ses: gs.Session, scratch: Path, milliseconds: int, seconds: float,
            progress: mprogress.Progress = mprogress.no_progress, disarm_watches: bool = False,
            frames: int = 0, route: dict[str, Any] | None = None) -> dict[str, Any]:
    """The body of the `run_for` tool, with the armed watches held for the pass on request:
    by emulated milliseconds, or by FRAMES of the frame counter, exactly one of the two. A run by
    frames is routed (`route_frames`) before anything is disarmed, or takes the `route` a caller
    that had to judge it before sending anything already took."""
    check_run_for(milliseconds, frames, seconds)
    if frames:
        through = (route_frames(ses, read.BY_TIME.format(tool="run_for")) if route is None
                   else route)
        return _with_watches_disarmed(
            ses, disarm_watches,
            lambda: _run_for_frames(ses, scratch, frames, seconds, progress, through))
    return _with_watches_disarmed(
        ses, disarm_watches,
        lambda: _run_for(ses, scratch, milliseconds, seconds, progress))


# THE SESSION SAYS SO WHEN A BAIL-OUT LETS GO OF THE MACHINE, and `require_stopped` reading
# `ses.running` is the ONLY thing that keeps a reader off a moving machine (measured there: the
# next read after a timed-out run came back as something that was not hex).
#
# WHICH WAY TO FAIL IS DECIDED BY THE ASYMMETRY, and this is the reason, written where it bites:
# saying "it may be RUNNING" about a machine that is in fact stopped costs the caller one loud
# refusal naming `stop`, which works on a running machine and is recoverable in a single call.
# Saying nothing about a machine that IS running returns a wrong value with nothing saying so.
# The second is unrecoverable by the reader, so every bail-out that cannot PROVE a stop takes
# the first.
#
# AND NONE OF THESE CAN PROVE ONE. Every proof of rest by frames is two agreeing readings of
# the frame counter, and the console answers `print frame` while the machine runs: a machine
# running without ever reaching a vblank (the screen off, an interrupt-less loop) reads the
# same counter twice exactly as a stopped one does. So `no_progress`'s "nothing was emulated" is
# a claim about the COUNTER, never about the machine being at rest, and it lets go like the
# other two.
#
# `console_run` rides along because the release was a CONSOLE command (`gvblank`, `gtime`), and
# the stub sends no stop packet for a run it did not start: the stop is proved on the counter.
@contextlib.contextmanager
def _console_run(ses: gs.Session) -> Iterator[None]:
    """A run the CONSOLE started is in flight inside this block, and it sends no stop packet: a
    cancelled call that unwinds out of it leaves the machine marked RUNNING, as the bound's own
    bail-out does, so the end the call declared stops it and proves the rest (`running.stop`)."""
    try:
        yield
    except BaseException as e:
        if cancel.is_cancellation(e):
            _left_running(ses)
        raise


def _left_running(ses: gs.Session, unprovable: bool = False) -> None:
    """Mark the session RUNNING because a bail-out handed the machine back moving;
    `unprovable` when the frame counter is the thing that did not move, so it cannot prove
    rest later either and only `stop`'s interrupt brings the machine back."""
    ses.running = True
    STATE.console_run = True
    STATE.console_run_unprovable = unprovable


def _release_unconfirmed(ses: gs.Session, command: str, error: gs.SessionError,
                         **fields: Any) -> dict[str, Any]:
    """The refusal of a CONSOLE release (`gvblank`, `over`) whose answer, or whose landing,
    the session failed to read: the command may have been taken, so the machine is let go of
    (`_left_running`) and the reply says what went out, that nothing proves rest, and what
    recovers it. A request that ran out LATCHED the session (`Session.request`): its answer
    is still owed, so nothing `stop` read could be believed, and the refusal is the latch's."""
    if ses.broken is not None:
        return running.session_broke(ses, error, f"under `{command}`",
                                     f"Whether `{command}` was taken is not known", **fields)
    _left_running(ses)
    return menvelope.invalid("not_settled",
                             f"`{command}` was sent and the session failed before its landing was "
                             f"confirmed ({error}): nothing proves the machine came to rest, so it "
                             f"may be RUNNING under a run the console started. Either way, "
                             f"{running.STOP_RECOVERS}", **fields)


# WHY, for the reader of this code (the client gets the docstring above the code):
#
# A GOLDEN IS A MARKER PLUS N FRAMES, and N milliseconds is not N frames: the frame period is
# not a whole number of milliseconds and a stop lands where the frame COUNTER says, which is
# how a repository's oracle counts. MAME's own `gvblank` runs to the next vblank. MEASURED on a
# board: from the vblank line each `gvblank` moved `frame` by exactly one and `totalcycles` by
# one frame's worth, and the console answers `print` while the run is still landing, so each
# step is confirmed on the counter (two agreeing reads) before the next `gvblank` goes out. The
# run is counted on the FRAME COUNTER, not on the number of `gvblank`s sent: from a stop in
# the middle of a frame the first one reaches that frame's vblank without moving the counter.
#
# AND A `gvblank` STOPS ONLY THROUGH THE FIRST CPU, which consumes MAME's one vblank flag
# (`debugger_cpu::start_hook`): sent through another it runs the machine away, so the run goes
# through the first (REFERENCE.md, Advancing the machine) and its end is proved at rest.
def route_frames(ses: gs.Session, instead: str = "") -> dict[str, Any]:
    """The first cpu made visible for a run by frames, and the reply's `note` saying so; nothing
    when it already is, or when `cpulist` names no second cpu. Refused before anything runs on a
    board with no frame counter, which has no vblank stop either (`refuse_frameless`); on a
    stub without threads, which cannot show it without running; and when the debugger ignores
    it, which no `gvblank` then stops. `instead` is the calling tool's way round a board with no
    frame counter, when it has one."""
    refuse_frameless("a run by frames", instead)
    tags = cpus.cpu_list(ses)
    visible = cpus.visible_cpu(ses)
    if len(tags) < 2 or visible in (None, tags[0]):
        return {}
    first = tags[0]
    cpus.make_visible(ses, first, f"a run by frames needs {first} visible, since a `gvblank` "
                                  "stops only on the first cpu to run after the vblank (by "
                                  "`milliseconds` a run stops on any)")
    return {"note": f"sent through {first}, made visible first (`Hc`, which runs nothing): a "
                    f"`gvblank` stops only on {first}, the first cpu to run after the vblank, "
                    f"and {visible} was visible"}


def refuse_frameless(what: str, instead: str = "") -> None:
    """`no_channel` for `what`, which counts the frame counter, on a board with none: the one
    refusal every run by frames takes before anything is sent. `instead` is the tool's own way
    round it, when it has one."""
    if read.frame_symbol() is None:
        raise st.Invalid("no_channel", f"{what} counts the frame counter, and {read.FRAMELESS_WHY}"
                                       + (f": {instead}" if instead else ""))


# How a run by frames names the stop it ends at: the next run by frames reads it back, since the
# instruction that stop landed on is the one its first `gvblank` releases.
FRAMES_END = "the `gvblank` stop of the last frame asked"


def _landing_left(counted_on: str | None) -> int | None:
    """The pc of a frame stop a previous run by frames ended at, when the machine still stands
    there on `counted_on`: its instruction's breakpoints were skipped, so the first `gvblank`
    of this run executes it unchecked. None for any other stop, or a pc a read since moved."""
    stop = STATE.last_stop or {}
    if stop.get("how") != FRAMES_END or not cpus.same_cpu(stop.get("cpu"), counted_on):
        return None
    return int(stop["pc"], 16)


def _run_for_frames(ses: gs.Session, scratch: Path, frames: int, seconds: float,
                    progress: mprogress.Progress, through: dict[str, Any]) -> dict[str, Any]:
    """The run by frames: `gvblank` until the frame counter has moved by `frames`, routed
    already (`through` is `route_frames`'s answer)."""
    counted_on = cpus.visible_cpu(ses)
    first = read.print_values(ses, [read.known_frame_symbol(), "totalcycles"])
    before: int = first[0]
    cycles_before: int | None = first[1]
    stale_why = cycles.stale_cycles_why(counted_on, cycles_before)
    ses.last_stop_packet = ""
    clock = mprogress.Ticker(seconds, progress)
    target = before + frames
    sent = 0
    last = before
    # A CURSOR OF ITS OWN into the console's log, only to LOOK after each landing: the one
    # mark belongs to the survey, which reads every line since the previous stop and
    # attributes the stop from them, so looking here loses nothing to it.
    log, peeked = scratch / "debug.log", STATE.debuglog_mark
    # THE LANDING EACH `gvblank` RELEASES: a frame stop takes effect at the hook of the
    # instruction it lands on, which skips breakpoints while the debugger is stopped, so the next
    # `gvblank` executes that instruction with a control on it never evaluated. Counted for the
    # control here (`breakpoints.count_landing`), at the release, on the cpu the stops land on.
    landing = _landing_left(counted_on)
    if landing is not None and landing != ses.current_pc():
        landing = None
    with _console_run(ses):
        while last < target:
            if clock.expired():
                _left_running(ses)
                return menvelope.invalid("not_settled",
                                         f"the frame counter reached {last} of the {target} asked "
                                         "for "
                                         f"in {seconds:g} s: the machine may be RUNNING under a "
                                         "`gvblank` this server cannot see end. "
                                         f"{running.STOP_RECOVERS}",
                                         frame_before=before, frame_after=last, **through)
            landed_from = last
            readings: list[int] = []
            try:
                ses.monitor("gvblank")
                sent += 1
                if landing is not None:
                    breakpoints.count_landing(landing, counted_on)
                    landing = None
                # CONFIRMED ON THE COUNTER: the console answers while the run to the vblank is
                # still landing, so the reading is taken until two in a row agree.
                while not clock.expired():
                    readings.append(read.frame(ses))
                    if len(readings) >= 2 and readings[-1] == readings[-2]:
                        break
                    time.sleep(VBLANK_SETTLE_S)
            except gs.CommandTooLong:
                raise                  # refused before a byte went out: nothing was let go of
            except gs.SessionError as e:
                return _release_unconfirmed(ses, "gvblank", e, frame_before=before,
                                            frame_after=readings[-1] if readings else last,
                                            **through)
            last = readings[-1] if readings else last
            # THE ALIGNING TICK IS NOT PART OF THE RUN, and `cycles` is the clock behind the
            # frames ASKED FOR. From a mid-frame stop the first `gvblank` reaches that frame's own
            # vblank WITHOUT moving the counter (the comment above this function), so its cycles
            # fell inside a span whose `frame_after - frame_before` was still exactly N: a
            # session's first `run_for(frames=1)` would report about twice a later one's cycles,
            # and an instrument silently inflated like that cannot be caught by reading its output.
            #
            # THE RULE IS BOUNDED BY ITS OWN CONDITION rather than by a flag: while the counter
            # still reads `before` nothing that was asked for has landed, so everything burned so
            # far is alignment and the baseline moves to here. The moment it moves this can never
            # fire again, which is why no general "was that tick an alignment?" question has to be
            # answered. `polls` is untouched: it counts the `gvblank`s sent, honestly, and it is
            # the only tell a caller has that the alignment fired.
            if last == before:
                stale_why = None              # the aligning tick executed: `totalcycles` is current
                try:
                    cycles_before = read.print_values(ses, ["totalcycles"])[0]
                except gs.SessionError:
                    # unreadable is None, never a span over the wrong thing
                    cycles_before = None
            # A STOP THIS SERVER ARMED CAN LAND BETWEEN TWO VBLANKS: a breakpoint on a routine
            # that runs every frame, or a change watch, halts the machine BEFORE the vblank this
            # `gvblank` was heading for, the counter has not ticked, and the next `gvblank` would
            # simply resume it: with a `stop` breakpoint on the per-frame irq, `run_for(frames=5)`
            # would come back ELAPSED with the row crossed five times. A run the
            # console starts sends NO stop packet, so the first tell is the COUNTER: a `gvblank`
            # that moved it by nothing stopped early. It is not the only one, because the counter
            # ticks as a run leaves a vblank stop: a watch that fires later in that frame, or a
            # breakpoint typed through `debug`, halts the machine with the counter MOVED, and
            # leaves nothing but the console's `Stopped at ...` line. So the log is looked at
            # after EVERY landing, and a watchpoint's, breakpoint's or registerpoint's line there
            # is a stop. A row the machine lands on WITH the tick is surveyed too: a stop
            # breakpoint sitting on the vblank handler fired there. A control never counts,
            # wherever the machine lands.
            pc = ses.current_pc()
            landing = pc
            lines, peeked = files.lines_since(log, peeked)
            # A ROW AT THIS PC IS ASKED ITS CPU only when one sits there: the stop's cpu costs a
            # console read, and most landings have no row at their pc.
            if (last == landed_from or running.stop_logged_in(lines)
                    or (breakpoints.bp_owned_at(pc, None) is not None
                        and running.halts(pc, cpus.visible_cpu(ses)))):
                seen = running.survey(ses, scratch)
                peeked = STATE.debuglog_mark
                if running.cut_by_a_stop(seen, pc):
                    return running.finish_stop(ses, seen, running.attribute(pc, seen["cpu"]),
                                               verdict=contract.OTHER_STOP, frame_before=before,
                                               frame_after=last,
                                               **_cycles(ses, cycles_before, stale_why,
                                                         counted_on, seen["cpu"]), polls=sent,
                                               **through)
            if last == before and sent > frames + 1:
                _left_running(ses, unprovable=True)
                return menvelope.invalid("no_progress",
                                         f"the frame counter did not move over {sent} `gvblank`s: "
                                         "nothing was emulated, and the counter cannot tell that "
                                         "from "
                                         "a machine still RUNNING under the last `gvblank`",
                                         frame_before=before, frame_after=last, **through)
            clock.report(min(last - before, frames), frames,
                         "run_for {asked}: frame {frame} of {target}, {elapsed:.0f}s of {bound:g}s",
                         asked=prose.counted(frames, "frame"), frame=last, target=target,
                         bound=seconds)
        if not running.frame_at_rest(ses, reads=2):
            _left_running(ses)
            return menvelope.invalid("not_settled",
                                     f"the frame counter reached {last} of the {target} asked for "
                                     "and "
                                     "still moves: no `gvblank` held the machine, so it is "
                                     "RUNNING. "
                                     ""
                                     f"{running.STOP_RECOVERS}", frame_before=before,
                                     frame_after=last,
                                     **through)
    seen = running.survey(ses, scratch)
    landed = running.finish_stop(ses, seen, FRAMES_END, verdict=contract.ELAPSED,
                                 frame_before=before, frame_after=last,
                                 **_cycles(ses, cycles_before, stale_why, counted_on,
                                           seen["cpu"]), polls=sent, **through)
    # THE LANDING IS RECORDED BEFORE THE LAST LINE: that send is a poll, and a cancel met there
    # would otherwise leave the machine at rest where no record says it is.
    clock.finish(frames, "run_for {asked}: frame {frame} of {target}, done",
                 asked=prose.counted(frames, "frame"), frame=last, target=target)
    return landed


def _cycles(ses: gs.Session, cycles_before: int | None, stale_why: str | None,
            counted_on: str | None, stopped_on: str | None) -> dict[str, Any]:
    """The reply's `cycles`: a count, or unavailable because the baseline was one a load, a
    rewind or a reset left stale (`stale_why`, `mame_cycles.stale_cycles_why`), or because
    `_span` could not measure one."""
    if stale_why is not None:
        return {"cycles": unavailable(stale_why)}
    return {"cycles": _span(ses, cycles_before, counted_on, stopped_on)}


def _span(ses: gs.Session, cycles_before: int | None, counted_on: str | None,
          stopped_on: str | None) -> int | dict[str, Any]:
    """`totalcycles` now minus `cycles_before`, or unavailable saying why there is no span: the
    counter is each cpu's own and `print` reads the visible one, which a stop on another cpu
    moves, so a span across two cpus is no clock at all; an unreadable counter is said, never
    guessed."""
    if cycles_before is None:
        return unavailable("`totalcycles` could not be read before the run, so there is no "
                              "baseline")
    if None not in (counted_on, stopped_on) and counted_on != stopped_on:
        return unavailable(f"counted on {counted_on} and stopped on {stopped_on}: each cpu "
                              "keeps its own `totalcycles`, so a span across the two is no clock")
    try:
        return read.print_values(ses, ["totalcycles"])[0] - cycles_before
    except gs.SessionError as e:
        return unavailable(f"`totalcycles` could not be read after the run: {e}")


def _run_for(ses: gs.Session, scratch: Path, milliseconds: int, seconds: float,
             progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The run itself: `gtime`, the frame counter polled to rest, the survey. The duration
    was judged by the caller, `run_for`, which chose this run over the one by frames. On a
    board with no frame counter the emulated clock is what is polled, and what proves the run
    moved; every board reports it before and after."""
    counted_on = cpus.visible_cpu(ses)
    symbol = read.frame_symbol()
    emulated_before = ses.emulated_seconds()
    clocked = symbol is None
    what = "the emulated clock" if clocked else "the frame counter"
    # WHAT PROVES THE RUN MOVED AND CAME TO REST, the counter or the clock: `before` is its
    # reading before the release, compared with the readings after.
    before: int | float
    frame_before: int | None = None
    cycles_before: int | None
    if symbol is not None:
        frame_before, cycles_before = read.print_values(ses, [symbol, "totalcycles"])
        before = frame_before
    elif emulated_before is None:
        raise gs.ExpressionRefused(f"{read.FRAMELESS_WHY}, and the console's `time` answered no "
                                   "time, so nothing could prove a run's end: nothing released")
    else:
        before, cycles_before = emulated_before, read.print_values(ses, ["totalcycles"])[0]
    stale_why = cycles.stale_cycles_why(counted_on, cycles_before)

    # A READING THAT IS NOT THERE SAYS WHY, in the place of its value: a board with no counter
    # has no frame, and a console that answers no `time` has no emulated clock.
    def counted(frame: int | None) -> int | dict[str, Any]:
        return frame if frame is not None else unavailable(
            f"{read.FRAMELESS_WHY}: `emulated_before_s` and `emulated_after_s` are this run's "
            "clock")

    def timed(clock: float | None) -> float | dict[str, Any]:
        return (st.measured_s(clock) if clock is not None
                else unavailable("the console's `time` answered no time"))

    times: dict[str, Any] = {"emulated_before_s": timed(emulated_before)}
    ses.monitor(f"gtime {milliseconds:#x}")
    # A RUN THE CONSOLE STARTS ENDS WITH NO STOP PACKET, so the packet of the stop before it
    # (a watchpoint's, say) would still be the last one the stub sent, and the survey of
    # this run's end would read it as this stop's cause. Cleared here: the survey then
    # attributes the stop to the run, and only a packet the run itself produces names a watch.
    ses.last_stop_packet = ""
    ses.drain_stop_reply()
    readings: list[int | float] = []
    verdict = contract.ELAPSED
    with _console_run(ses):
        try:
            if not wait_for_rest(
                    readings, lambda: read.rest_reading(ses), seconds, progress=progress,
                    report=lambda clock: clock.tick(
                        "run_for {ms} ms: {what} {frame}, {elapsed:.0f}s of {seconds:g}s",
                        ms=milliseconds, what="clock" if clocked else "frame", frame=readings[-1],
                        seconds=seconds)):
                raise gs.SessionError(f"{what} was still moving at {seconds} s")
            after = readings[-1]
        except gs.SessionError:
            # A run the CONSOLE started sends no stop packet, so the interrupt is the one that
            # does not wait for one (`halt`), and the proof of the stop is the same one the
            # ELAPSED path uses: the counter (or the clock) no longer moving. One reading after the
            # 0x03
            # proved nothing about a machine that had not processed it yet.
            with contextlib.suppress(gs.SessionError, OSError):
                ses.halt()
            settled: list[int | float] = []
            try:
                steady = wait_for_rest(settled, lambda: read.rest_reading(ses),
                                        running.CONSOLE_HALT_SETTLE_S, sleep_first=True)
            except gs.ExpressionRefused as e:
                # AN ANSWER, AND STILL NO PROOF OF REST: the machine was released, so the
                # refusal lets go of it rather than answering `no_channel` as if nothing ran.
                _left_running(ses)
                return menvelope.invalid("not_settled",
                                         f"`gtime` was sent and {what} could no longer be read "
                                         f"({e}): nothing proves the machine came to rest, so it "
                                         f"may be RUNNING. {running.STOP_RECOVERS}",
                                         frame_before=counted(frame_before),
                                         frame_after=unavailable(f"not read after the run: {e}"),
                                         emulated_after_s=unavailable(
                                             f"not read after the run: {e}"), **times)
            if not steady:
                _left_running(ses)
                return menvelope.invalid(
                    "not_settled",
                    f"the machine did not come to rest within "
                    f"{running.CONSOLE_HALT_SETTLE_S} s of the "
                    f"interrupt at the bound: {what} still moved "
                    f"({settled[-FRAME_STABLE_READS:]}). It may be RUNNING, and this "
                    f"server cannot see a run the console started. {running.STOP_RECOVERS}",
                    frame_before=counted(frame_before),
                    frame_after=counted(None) if clocked else settled[-1],
                    emulated_after_s=(timed(settled[-1]) if clocked else unavailable(
                        "not read: the machine did not come to rest")), **times)
            after = settled[-1]
            readings.extend(settled)
            verdict = contract.TIMEOUT
    times["emulated_after_s"] = timed(after if clocked else ses.emulated_seconds())
    frame_after = counted(None if clocked else int(after))
    # `how` NAMES WHAT STOPPED IT, never the verdict again: the console's own end of the run,
    # in words with no number in them, so a count of stops by `how` adds the runs up.
    how = "the console's `gtime` stop" if verdict == contract.ELAPSED else "interrupt at the bound"
    # THE SURVEY IS READ BEFORE THE VERDICT IS NAMED: a watch or a breakpoint this server
    # armed can cut the run before its time, before a frame has even elapsed, and that is a
    # stop of its own with the writer in it, an `OTHER_STOP`. Judged by the frame counter
    # alone it would read as "nothing emulated", an INVALID with the whole `watch_hit`
    # beside it, which a reader filtering on `status` throws away.
    seen = running.survey(ses, scratch)
    pc = int(seen["pc"], 16)
    cut = running.cut_by_a_stop(seen, pc)
    if after < before or (after == before and not cut):
        # INVALID, AND STILL A STOP: the machine is where the run left it, and the survey
        # rides on this reply as it does on `run_to`'s INVALID.
        code = "frames_went_backwards" if after < before else "no_progress"
        return running.finish_stop(ses, seen, how, status="INVALID", code=code,
                                   frame_before=counted(frame_before), frame_after=frame_after,
                                   **times,
                                   message=(
            f"the emulated clock did not move across `gtime {milliseconds:#x}` (it read "
            f"{after} s before and after): nothing was emulated; this is not a run"
            if clocked and after == before else
            f"{what} went from {before} to {after} across `gtime {milliseconds:#x}`: " + (
                "it went BACKWARDS, which a run does not do: something put the machine back "
                f"under it, and this call saw only the {'clock' if clocked else 'counter'}"
                if after < before else
                "shorter than one frame, or nothing emulated; this is not a run")))
    if cut:
        verdict, how = contract.OTHER_STOP, running.attribute(pc, seen["cpu"])
    # THE CYCLES THE RUN TOOK, the exact clock behind an emulated duration, so a duration in
    # milliseconds is checked against the cpu's clock rather than believed.
    return running.finish_stop(ses, seen, how, verdict=verdict, frame_before=counted(frame_before),
                               frame_after=frame_after, **times,
                               **_cycles(ses, cycles_before, stale_why, counted_on,
                                         seen["cpu"]), reads=len(readings))


# MAME CANNOT ADVANCE ONE CPU ALONE (REFERENCE.md, Advancing the machine): a step goes through
# the visible cpu, so a named one is shown first, and `others` says what the rest did.
def step(ses: gs.Session, scratch: Path, count: int, mode: str = "into",
         cpu: str = "") -> dict[str, Any]:
    """The body of the `step` tool, on `cpu` (shown first) or the visible cpu, with
    `others`: every other cpu's program counter before and after, on a build that serves a
    thread per cpu."""
    check_step(count, mode)
    stepped = cpus.visible_cpu(ses)
    if inputs.cpu_given(cpu) and (tag := cpus.named(ses, cpu)) != stepped:
        cpus.make_visible(ses, tag, f"a step on {tag} goes through the visible cpu")
        stepped = tag
    before = cpus.pc_readings(ses)

    def others() -> dict[str, Any]:
        """The stop reply's `others`, read once the step stopped: every cpu but the one it
        stopped on, which MAME makes the visible one. Nothing with a single thread."""
        if len(before) < 2:
            return {}
        after, stopped = cpus.pc_readings(ses), cpus.visible_cpu(ses) or stepped
        return {"others": {tag: _moved(before[tag], after[tag])
                           for tag in before if tag != stopped}}

    return _step(ses, scratch, count, mode, stepped, others)


def _moved(before: cpus.PcReading, after: cpus.PcReading) -> dict[str, Any]:
    """One cpu's program counter register before and after a step, or unavailable saying why it
    was not read."""
    if isinstance(before, str) or isinstance(after, str):
        return unavailable(before if isinstance(before, str) else str(after))
    return {"reg": before[0], "before": st.hex_addr(before[1]), "after": st.hex_addr(after[1])}


def _elsewhere(ses: gs.Session, scratch: Path, stepped: str | None, completed: int, count: int,
               mode: str, others: Callable[[], dict[str, Any]]) -> dict[str, Any] | None:
    """The reply of a step whose stop landed on a cpu other than `stepped`, or None: another
    cpu's breakpoint or watch fired while `stepped` executed, so the stop is named as that one's
    and the steps left are not taken on the wrong cpu. Asked only with several cpus."""
    if stepped is None or len(cpus.cpu_list(ses)) < 2:
        return None
    now = cpus.visible_cpu(ses)
    if now in (None, stepped):
        return None
    return running.stop_reply(ses, scratch, running.name_stop(ses), mode=mode,
                              instructions_completed=completed, **others(),
                              note=f"step {completed} of {count} stopped on {now}, not "
                                   f"{stepped}: a stop there cut it, and no step was taken "
                                   "after it")


def _step(ses: gs.Session, scratch: Path, count: int, mode: str, stepped: str | None,
          others: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """The steps themselves: `into` through the stub's `s`, `over` through the console's `over`
    (the stub offers no step-over), each `over` confirmed on the program counter before the next
    goes out, because the console answers while the machine is still running to the return.
    Every stop's reply carries `others()`, inside its envelope, and a stop on a cpu other than
    `stepped` ends the steps (`_elsewhere`)."""
    completed = 0
    if mode == "into":
        for _ in range(count):
            try:
                ses.step()
            except gs.Timeout as e:
                # The `s` went out, so the stub owes its stop packet as it does for
                # `_run_to`'s `c`: the state is left the way that site leaves it.
                return menvelope.invalid("not_settled",
                                         f"step {completed + 1} of {count}: no stop arrived in "
                                         f"time ({e}), so the machine may be RUNNING. "
                                         f"{running.STOP_RECOVERS}", mode=mode,
                                         instructions_completed=completed)
            except gs.SessionError as e:
                return running.session_broke(ses, e, f"at step {completed + 1} of {count}",
                                             "The steps before it landed and this one was "
                                             "not seen to", mode=mode,
                                             instructions_completed=completed)
            completed += 1
            if (cut := _elsewhere(ses, scratch, stepped, completed, count, mode,
                                  others)) is not None:
                return cut
        return running.stop_reply(ses, scratch, f"step {count}", mode=mode,
                                  instructions_completed=completed,
                                  **others())
    try:
        with _console_run(ses):
            for _ in range(count):
                try:
                    ses.monitor("over")
                except (gs.CommandTooLong, gs.ConnectionFailed):
                    raise
                except gs.SessionError as e:
                    return _release_unconfirmed(ses, "over", e, mode=mode,
                                                instructions_completed=completed)
                ses.last_stop_packet = ""
                ses.drain_stop_reply()
                if not _settled_pc(ses):
                    # AN `over` ACROSS A CALL THAT NEVER RETURNS leaves the machine running with no
                    # stop packet to come: it is halted here, and the reply says how far it got.
                    with contextlib.suppress(gs.SessionError, OSError):
                        ses.halt()
                    ses.drain_stop_reply()
                    if not _settled_pc(ses):
                        # STILL MOVING after the interrupt: the machine may be RUNNING, and the
                        # session says so, as a console `g` does, so the readers refuse instead
                        # of sampling a moving machine.
                        _left_running(ses)
                        return menvelope.invalid("not_settled",
                                                 f"step over {completed + 1} of {count}: the "
                                                 "machine "
                                                 f"did not come to rest within "
                                                 f"{running.CONSOLE_HALT_SETTLE_S} s after `over` "
                                                 "and an interrupt; it may still be RUNNING. "
                                                 f"{running.STOP_RECOVERS}",
                                                 mode=mode, instructions_completed=completed)
                    return running.stop_reply(
                        ses, scratch, "interrupt after a step over still moving at its bound",
                        status="INVALID", code="not_settled", mode=mode,
                        instructions_completed=completed,
                        **others(),
                        message=(f"step over {completed + 1} of {count} was still moving "
                                 f"{running.CONSOLE_HALT_SETTLE_S} s after `over` and was "
                                 "interrupted; whether the call it stepped over would have "
                                 "returned later was not seen"))
                completed += 1
                if (cut := _elsewhere(ses, scratch, stepped, completed, count, mode,
                                      others)) is not None:
                    return cut
    except gs.SessionError as e:
        # A console that REFUSES kept its place and bails out above as `not_settled`; a
        # connection that is gone, or a request that ran out and latched, answers nothing,
        # `stop` included.
        if not (isinstance(e, gs.ConnectionFailed) or ses.broken):
            raise
        return running.session_broke(ses, e, f"at step over {completed + 1} of {count}",
                                     "Whether it landed was not seen", mode=mode,
                                     instructions_completed=completed)
    return running.stop_reply(ses, scratch, f"step {count} over", mode=mode,
                              instructions_completed=completed,
                              **others())


def _settled_pc(ses: gs.Session) -> bool:
    """Whether the machine is at rest after an `over`: the program counter AND the frame
    counter read the same `FRAME_STABLE_READS` times in a row within
    `running.CONSOLE_HALT_SETTLE_S`. The console answers both while the machine runs (the frame
    counter under `gtime` included), so a step over is confirmed on the counters it moves, never
    assumed from the console's prompt; and the pc alone is not enough, because a callee spinning
    on a flag reads the same pc three times while the frames keep coming. A board with no frame
    counter reads the emulated clock beside the pc."""
    symbol = read.frame_symbol()

    def reading() -> tuple[int, int | float]:
        if symbol is not None:
            pc, frame = read.print_values(ses, ["curpc", symbol])
            return pc, frame
        return read.print_values(ses, ["curpc"])[0], read.rest_reading(ses)

    try:
        return wait_for_rest([], reading, running.CONSOLE_HALT_SETTLE_S)
    except gs.ConnectionFailed:
        raise          # no counter will ever answer again: the caller's to latch
    except gs.SessionError:
        if ses.broken:
            raise      # a LATCHED channel is not a moving machine: the tool answers it
        return False   # a counter the console cannot answer is not a rest
