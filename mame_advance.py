"""The ADVANCE family: run to a place with a control, run for emulated time, step."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Hashable, Iterator
from pathlib import Path
from typing import Any, TypeVar

from scry_core import cancel, prose
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core import vocabulary as vocab
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

# `run_for` knows the machine STOPPED when MAME's frame counter, read through the console, repeats
# three times 0.1 s apart; the poll is bounded by the caller's `seconds`.
FRAME_POLL_S = 0.1
FRAME_STABLE_READS = 3
RUN_POLL_S = 0.1
# Between the two readings that confirm a `gvblank` landed: far shorter than the `gtime` poll,
# which paid per frame would make a run by frames cost the poll.
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
    """Read `read_counter` into `readings`, `FRAME_POLL_S` apart, until the last
    `FRAME_STABLE_READS` agree (True) or `bound_s` passes (False). A raising read propagates and
    earlier readings stay. `sleep_first` waits before each read; `report` ticks progress."""
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
    """`run_to`'s machine-independent half: the ref, the bound, the shapes of a condition and a
    `control`, judged before a control is armed. Address equality needs the table, below."""
    if not ref or not ref.strip():
        raise st.Invalid("bad_argument", "run_to needs a ref: a symbol or a `0x` address")
    inputs.check_ref(ref)
    if control.strip():
        inputs.check_ref(control, "control")
    vocab.check_wait(seconds)
    if condition.strip():
        conditions.check_condition(condition)


def check_run_for(milliseconds: int = 0, frames: int = 0, seconds: float = 30.0,
                  **_: Any) -> None:
    """`run_for`'s machine-independent half: two different mistakes, said apart."""
    check_run_bound(milliseconds, frames, seconds, "run_for")


def check_run_bound(milliseconds: int, frames: int, seconds: float, what: str) -> None:
    """The bound of a run as `run_for` takes it, judged for the tool `what` (`trace` shares it)."""
    inputs.natural("milliseconds", milliseconds, " is not a count of milliseconds: an integer, "
                   "never negative")
    inputs.natural("frames", frames, " is not a count of frames: an integer, never negative")
    if (milliseconds > 0) == (frames > 0):
        raise st.Invalid("bad_argument",
                         f"{what} takes exactly one of `milliseconds` and `frames`, above zero")
    vocab.check_wait(seconds)


STEP_MODES = ("into", "over")


def step_max() -> int:
    """The longest walk one `step` takes: as many `over` settles as fit in the ceiling of every
    other wait. A function: `mame_running` imports this module, so its constant does not exist
    yet at import time."""
    return int(vocab.WAIT_MAX_S // running.CONSOLE_HALT_SETTLE_S)


def check_step(count: int = 1, mode: str = "into", **_: Any) -> None:
    """`step`'s machine-independent half: how many, and which of two words."""
    inputs.count("count", count, step_max(), ": a longer walk is `run_to` or `run_for`")
    vocab.one_of("mode", mode, STEP_MODES)


# The control is not bureaucracy: four mistakes leave a MAME breakpoint silent (wrong address
# space, a symbol resolved to the ROM copy, a routine behind an uninserted coin, a machine on the
# red warning) and all read as "never called"; only a control that DID fire makes the silence a
# measurement. A breakpoint set while the machine runs is not among them (`breakpoint_at`).
#
# The control is a declaration with `role="control"`: a console row whose condition
# `(++tempN)==0` counts every hit and never halts. MAME counts, not the stub: a hot control would
# starve the progress tick with a round trip per firing. `run_to` reads the counts on the
# target's cpu before and after; a run that names a `control` declares it first.
def run_to(ses: gs.Session, scratch: Path, ref: str, control: str, seconds: float,
           progress: mprogress.Progress = mprogress.no_progress, disarm_watches: bool = False,
           condition: str = "", cpu: str = "") -> dict[str, Any]:
    """The body of the `run_to` tool, with the armed watches held for the pass on request: the
    target armed on `cpu`, or on the visible cpu when none is named."""
    check_run_to(ref, seconds, condition)
    on = cpus.chosen(ses, cpu)
    a_target = STATE.resolve(ref, on)
    if condition.strip():
        ses.console_packet(breakpoints.bp_command(
            a_target, conditions.console_condition(condition, on), on))
    if control.strip():
        try:
            a_control = STATE.resolve(control, on)
        except inputs.BareHex:
            raise
        except st.Invalid:
            return _control_unresolved(control, on)
        if a_control == a_target:
            raise st.Invalid("bad_argument",
                             "the control cannot be the same address as the target")
        declared = breakpoints.breakpoint_at(ses, control, "auto", role="control", cpu=on or "")
        if declared.get("status") != "ok":
            return declared
        if not declared.get("armed"):
            return menvelope.invalid("bad_argument",
                                     f"the control {control} is declared but not armed "
                                     f"({declared.get('state')}): a control counts only once it "
                                     "resolves to an address in this build", control=control)
    if not counting(on):
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
    """The refusal for a `control` that resolves in no table of the target's cpu; one declared
    on ANOTHER cpu is named, so the caller does not hunt for a broken declaration."""
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
    """Run `run` with every armed change watch disarmed when `disarm`, re-arming afterwards
    whatever it answered, and say which were disarmed and which came back."""
    if not disarm:
        return run()
    disarmed = watches.disarm_for_pass(ses)
    rearmed: list[dec.Owner] = []
    try:
        reply = run()
    finally:
        # A failing re-arm LATCHES rather than raising, so it never hides the run's own reply;
        # over a session the run broke nothing is re-armed.
        if not ses.broken:
            try:
                rearmed = watches.rearm_after_pass(ses, disarmed)
            except gs.SessionError as e:
                ses.latch(f"re-arming the watches after the pass failed: {e}")
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
    """Each owner's hits over one run: after minus before, or after when a count went down (a
    temp reset under the run by `debug`)."""
    return [{**dec.owner_fields(r),
             "hits_in_run": after[r] - before[r] if after[r] >= before[r] else after[r]}
            for r in after if r in owners]


def _target_not_listed(ses: gs.Session, armed_as: str,
                       row: dict[str, Any] | None) -> dict[str, Any]:
    """Refuse a target the console took and did not list as sent, before the machine moved; a
    row listed without its condition is removed first, or every later run would stop at it."""
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
    """The run: the target armed on `on` (with `condition`) and read back, the wait, the survey,
    the controls' counts around it, the target removed by index."""
    cond = conditions.console_condition(condition, on) if condition.strip() else ""
    a_target = STATE.resolve(ref, on)
    owners = counting(on)
    if any(breakpoints.control_at(owner)[0] == a_target for owner in owners):
        raise st.Invalid("bad_argument",
                         f"the target {ref} is at the same address as a control on its cpu: a "
                         "control never halts, so nothing would stop there")
    held = mlists.bp_held(ses)
    taken = next((r for r in mlists.rows_at(held, a_target)
                  if cpus.same_cpu(on, r["cpu"])), None)
    if taken is not None:
        # The packet names the address, not the entry, so a stop at a shared address cannot be
        # attributed and the removal could take the wrong entry.
        what = f" (condition {taken['condition']})" if taken.get("condition") else ""
        raise st.Invalid("bad_argument",
                         f"the target {ref} already has breakpoint "
                         f"{mclear.row_index(taken['index'])} at "
                         f"{a_target:#x}{what}: a stop there could not be told from the "
                         "target's. Clear it (`declaration_clear(kind=\"breakpoint\")`) and run "
                         "again")
    before = breakpoints.control_counts(ses)
    armed_as = breakpoints.bp_command(a_target, cond, on)
    ses.monitor(armed_as)
    # Read back before the machine moves: an unlisted target came back TIMEOUT beside a firing
    # control, read as "the routine never ran".
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
            # A watchpoint's stop, or another cpu's, is not the target even at its address.
            stopped_on = cpus.visible_cpu(ses)
            if (pc == a_target and watches.watch_packet_addr(ses) is None
                    and cpus.same_cpu(on, stopped_on)):
                verdict = contract.TARGET
            else:
                verdict = contract.OTHER_STOP
            break
    except gs.SessionError as e:
        broken = e
    finally:
        # A TIMEOUT leaves the machine RUNNING and a running target serves non-hex reads, so stop
        # it first and remove the breakpoint only once stopped. On a broken session the removal
        # is attempted and its failure is not the news.
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
    if unanswered is not None and ses.running:
        # `c` started the run, so the stub will send its stop and `stop` recovers it: `running`
        # stays as `go` left it.
        return menvelope.invalid("not_settled",
                                 f"the interrupt at the bound was not answered ({unanswered}), so "
                                 f"the machine may be RUNNING and nothing about {ref} was "
                                 "measured; `target_disarmed` says whether the temporary "
                                 f"breakpoint's removal was confirmed. {running.STOP_RECOVERS}",
                                 control_hits=0, target_disarmed=target_disarmed)
    controls = _hits(before, breakpoints.control_counts(ses), owners)
    control_hits = sum(c["hits_in_run"] for c in controls)
    at_bound = "interrupt at the bound" + (", answered late" if unanswered is not None else "")
    late: dict[str, Any] = ({} if unanswered is None and target_disarmed
                            else {"target_disarmed": target_disarmed})
    if not target_disarmed:
        late["note"] = (f"the temporary breakpoint at {ref} may still be armed (row "
                        f"{mclear.row_index(row['index'])}), so a later run may stop there; "
                        f"{mclear.pasted_clear('breakpoint', row['index'])} removes it")
    cause = ({contract.TARGET: f"target {ref}", contract.TIMEOUT: at_bound}.get(verdict)
             or running.name_stop(ses))
    if verdict == contract.OTHER_STOP and control_hits == 0:
        # Another stop cut the run before the control could fire, so its silence says nothing.
        return running.stop_reply(ses, scratch, cause, status="INVALID", code="cut_by_other_stop",
                                  control_hits=0, controls=controls, **late, message=(
            f"another stop cut the run before any control could fire, so neither {ref} nor "
            "the controls were measured over the window asked for; `cause` says what stopped "
            "it. Clear what stopped it, or, for a watch, disarm the watches for the pass "
            "(`disarm_watches=True`), and run "
            "again"))
    if verdict != contract.TARGET and control_hits == 0:
        # INVALID, and still a STOP: the survey rides on this reply, or the next contact would
        # report this server's own interrupt as `stopped_on_its_own`. A silent control is not
        # code, or code that runs less often than assumed; the listing at each separates them.
        control_dasm: list[dict[str, Any]] = []
        for owner in owners:
            at, on = breakpoints.control_at(owner)
            try:
                control_dasm.append({**dec.owner_fields(owner), "dasm": read.dasm_lines(
                    ses, scratch, at, CONTROL_DASM_BYTES, on)})
            except gs.SessionError as e:
                control_dasm.append({**dec.owner_fields(owner),
                                     "dasm": unavailable(str(e))})
        names = ", ".join(ref for ref, _cpu in owners)
        silent = {**late, "note": st.join_notes(CONTROL_HINT, late.get("note"))}
        return running.stop_reply(ses, scratch, cause, status="INVALID", code="control_silent",
                                  control_hits=0, controls=controls, control_dasm=control_dasm,
                                  **silent, message=(
            f"the control ({names}) never fired, so {ref} not firing means nothing. "
            "Check that the control really is hot on this screen."))
    own: dict[str, Any] = {"condition": cond} if cond else {}
    seen = running.survey(ses, scratch)
    if verdict == contract.TARGET:
        seen.pop("breakpoint_cause", None)
    return running.finish_stop(ses, seen, cause, verdict=verdict, control_hits=control_hits,
                               controls=controls, **own, **late)


# `gtime` answers at once and `print frame` then answers mid-run, so the counter is polled until
# `FRAME_STABLE_READS` readings agree (`wait_for_rest`).

def run_for(ses: gs.Session, scratch: Path, milliseconds: int, seconds: float,
            progress: mprogress.Progress = mprogress.no_progress, disarm_watches: bool = False,
            frames: int = 0, route: dict[str, Any] | None = None) -> dict[str, Any]:
    """The body of the `run_for` tool: by emulated milliseconds or by FRAMES, exactly one. Frames
    are routed (`route_frames`) before anything is disarmed, or take the caller's `route`."""
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


# `require_stopped` reading `ses.running` is the only thing keeping a reader off a moving machine.
# Failing toward "it may be RUNNING" costs one loud refusal naming `stop`; silence about a running
# machine returns a wrong value unannounced. So every bail-out that cannot PROVE a stop takes the
# first, and none of these can: two agreeing frame readings are the same on a machine that never
# reaches a vblank, so `no_progress` is a claim about the counter, not about rest.
#
# `console_run` rides along because the release was a console command and the stub sends no stop
# packet for it.
@contextlib.contextmanager
def _console_run(ses: gs.Session) -> Iterator[None]:
    """A console-started run is in flight inside this block; a cancel unwinding out of it marks
    the machine RUNNING so the declared end stops it and proves the rest (`running.stop`)."""
    try:
        yield
    except BaseException as e:
        if cancel.is_cancellation(e):
            _left_running(ses)
        raise


def _left_running(ses: gs.Session, unprovable: bool = False) -> None:
    """Mark the session RUNNING after a bail-out handed back a moving machine; `unprovable` when
    the frame counter itself did not move, so only `stop`'s interrupt recovers it."""
    ses.running = True
    STATE.console_run = True
    STATE.console_run_unprovable = unprovable
    STATE.unprovable_peek = STATE.debuglog_mark


def _release_unconfirmed(ses: gs.Session, command: str, error: gs.SessionError,
                         **fields: Any) -> dict[str, Any]:
    """Refuse a console release (`gvblank`, `over`) whose answer or landing was not read: the
    command may have been taken, so the machine is let go of. A request that ran out LATCHED
    the session, and the refusal is the latch's."""
    if ses.broken is not None:
        return running.session_broke(ses, error, f"under `{command}`",
                                     f"Whether `{command}` was taken is not known", **fields)
    _left_running(ses)
    return menvelope.invalid("not_settled",
                             f"`{command}` was sent and the session failed before its landing was "
                             f"confirmed ({error}): nothing proves the machine came to rest, so it "
                             f"may be RUNNING under a run the console started. Either way, "
                             f"{running.STOP_RECOVERS}", **fields)


# A golden is a marker plus N frames, and N milliseconds is not N frames (the period is not whole
# milliseconds; the oracle counts the frame COUNTER). Each `gvblank` runs to the next vblank,
# moving `frame` and `totalcycles` by one frame, and its landing is confirmed on the counter (two
# agreeing reads) before the next goes out. The run counts the counter, not the `gvblank`s sent:
# from a mid-frame stop the first reaches that vblank without moving it.
#
# A `gvblank` stops only through the FIRST cpu, which consumes MAME's one vblank flag
# (`debugger_cpu::start_hook`): through another it runs away (REFERENCE.md, Advancing the machine).
def route_frames(ses: gs.Session, instead: str = "") -> dict[str, Any]:
    """Make the first cpu visible for a run by frames and return the reply's `note` saying so; {}
    when it already is or there is no second cpu. Refused (`refuse_frameless`) on a board with no
    frame counter, on a stub without threads, and when the debugger ignores the switch. `instead`
    is the calling tool's way round a frameless board."""
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
    """`no_channel` for `what` on a board with no frame counter; `instead` is the way round it."""
    if read.frame_symbol() is None:
        raise st.Invalid("no_channel", f"{what} counts the frame counter, and {read.FRAMELESS_WHY}"
                                       + (f": {instead}" if instead else ""))


FRAMES_END = "the `gvblank` stop of the last frame asked"


def _landing_left(counted_on: str | None) -> int | None:
    """The pc of a frame stop a previous run by frames ended at, if the machine still stands there
    on `counted_on`: its breakpoints were skipped, so the first `gvblank` executes it unchecked."""
    stop = STATE.last_stop or {}
    if stop.get("cause") != FRAMES_END or not cpus.same_cpu(stop.get("cpu"), counted_on):
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
    log, peeked = scratch / "debug.log", STATE.debuglog_mark
    # A frame stop takes effect at the hook of its instruction, skipping breakpoints, so the next
    # `gvblank` executes it with a control on it never evaluated: counted at the release.
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
            # The aligning tick is not part of the run: from a mid-frame stop the first `gvblank`
            # reaches that frame's vblank without moving the counter, which would inflate a
            # session's first `run_for(frames=1)` cycles to about twice a later one's. While the
            # counter still reads `before`, everything burned is alignment and the baseline moves.
            # `polls` counts the `gvblank`s sent and is the caller's only tell that it fired.
            if last == before:
                stale_why = None              # the aligning tick executed: `totalcycles` is current
                try:
                    cycles_before = read.print_values(ses, ["totalcycles"])[0]
                except gs.SessionError:
                    # unreadable is None, never a span over the wrong thing
                    cycles_before = None
            # A stop this server armed (a per-frame breakpoint, a change watch) can land between
            # two vblanks, and the next `gvblank` would just resume it. The console run sends no
            # stop packet, so the tells are the counter not moving and, since it ticks as a run
            # leaves a vblank stop, the console log read after EVERY landing. A stop row hit with
            # the tick is surveyed too; a control never counts.
            pc = ses.current_pc()
            landing = pc
            lines, peeked = files.lines_since(log, peeked)
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
    # Recorded before the last line: that send is a poll, and a cancel there would leave the
    # machine at rest unrecorded.
    clock.finish(frames, "run_for {asked}: frame {frame} of {target}, done",
                 asked=prose.counted(frames, "frame"), frame=last, target=target)
    return landed


def _cycles(ses: gs.Session, cycles_before: int | None, stale_why: str | None,
            counted_on: str | None, stopped_on: str | None) -> dict[str, Any]:
    """The reply's `cycles`: a count, or unavailable when the baseline is stale (`stale_why`) or
    `_span` could not measure one."""
    if stale_why is not None:
        return {"cycles": unavailable(stale_why)}
    return {"cycles": _span(ses, cycles_before, counted_on, stopped_on)}


def _span(ses: gs.Session, cycles_before: int | None, counted_on: str | None,
          stopped_on: str | None) -> int | dict[str, Any]:
    """`totalcycles` now minus `cycles_before`, or unavailable saying why: the counter is each
    cpu's own and `print` reads the visible one, so a span across two cpus is no clock."""
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
    """The run: `gtime`, the frame counter (the emulated clock on a frameless board) polled to
    rest, the survey. The caller chose this run over the one by frames."""
    counted_on = cpus.visible_cpu(ses)
    symbol = read.frame_symbol()
    emulated_before = ses.emulated_seconds()
    clocked = symbol is None
    what = "the emulated clock" if clocked else "the frame counter"
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

    def counted(frame: int | None) -> int | dict[str, Any]:
        return frame if frame is not None else unavailable(
            f"{read.FRAMELESS_WHY}: `emulated_before_s` and `emulated_after_s` are this run's "
            "clock")

    def timed(clock: float | None) -> float | dict[str, Any]:
        return (st.measured_s(clock) if clock is not None
                else unavailable("the console's `time` answered no time"))

    times: dict[str, Any] = {"emulated_before_s": timed(emulated_before)}
    ses.monitor(f"gtime {milliseconds:#x}")
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
            # A console run sends no stop packet, so interrupt with `halt` and prove rest on the
            # counter, as the ELAPSED path does.
            with contextlib.suppress(gs.SessionError, OSError):
                ses.halt()
            settled: list[int | float] = []
            try:
                steady = wait_for_rest(settled, lambda: read.rest_reading(ses),
                                        running.CONSOLE_HALT_SETTLE_S, sleep_first=True)
            except gs.ExpressionRefused as e:
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
    cause = ("the console's `gtime` stop" if verdict == contract.ELAPSED
             else "interrupt at the bound")
    # Read before the verdict: a watch or breakpoint this server armed can cut the run, a stop of
    # its own that frame counting alone would call "nothing emulated".
    seen = running.survey(ses, scratch)
    pc = int(seen["pc"], 16)
    cut = running.cut_by_a_stop(seen, pc)
    if after < before or (after == before and not cut):
        code = "frames_went_backwards" if after < before else "no_progress"
        return running.finish_stop(ses, seen, cause, status="INVALID", code=code,
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
        verdict, cause = contract.OTHER_STOP, running.attribute(pc, seen["cpu"])
    return running.finish_stop(ses, seen, cause, verdict=verdict,
                               frame_before=counted(frame_before),
                               frame_after=frame_after, **times,
                               **_cycles(ses, cycles_before, stale_why, counted_on,
                                         seen["cpu"]), reads=len(readings))


# MAME cannot advance one cpu alone (REFERENCE.md, Advancing the machine): a step goes through
# the visible cpu, so a named one is shown first.
def step(ses: gs.Session, scratch: Path, count: int, mode: str = "into",
         cpu: str = "") -> dict[str, Any]:
    """The body of the `step` tool on `cpu` (shown first) or the visible cpu, with `others`:
    every other cpu's pc before and after, on a build serving a thread per cpu."""
    check_step(count, mode)
    stepped = cpus.visible_cpu(ses)
    if inputs.cpu_given(cpu) and (tag := cpus.named(ses, cpu)) != stepped:
        cpus.make_visible(ses, tag, f"a step on {tag} goes through the visible cpu")
        stepped = tag
    before = cpus.pc_readings(ses)

    def others() -> dict[str, Any]:
        """The stop reply's `others`: every cpu but the one stopped on; nothing with one thread."""
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
    """The reply of a step that stopped on a cpu other than `stepped` (another's breakpoint or
    watch fired), named as that stop; the steps left are not taken on the wrong cpu."""
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
    """`into` through the stub's `s`, `over` through the console's `over` (the stub has no
    step-over), each confirmed on the program counter before the next, since the console answers
    while the machine still runs to the return. A stop on another cpu ends it (`_elsewhere`)."""
    completed = 0
    if mode == "into":
        for _ in range(count):
            try:
                ses.step()
            except gs.Timeout as e:
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
                    with contextlib.suppress(gs.SessionError, OSError):
                        ses.halt()
                    ses.drain_stop_reply()
                    if not _settled_pc(ses):
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
        # A refusing console kept its place (bailed out above); a gone connection or a latched
        # request answers nothing, `stop` included.
        if not (isinstance(e, gs.ConnectionFailed) or ses.broken):
            raise
        return running.session_broke(ses, e, f"at step over {completed + 1} of {count}",
                                     "Whether it landed was not seen", mode=mode,
                                     instructions_completed=completed)
    return running.stop_reply(ses, scratch, f"step {count} over", mode=mode,
                              instructions_completed=completed,
                              **others())


def _settled_pc(ses: gs.Session) -> bool:
    """Whether the machine is at rest after an `over`: pc and frame counter (the emulated clock
    on a frameless board) read the same `FRAME_STABLE_READS` times within the settle bound. The pc
    alone is not enough: a callee spinning on a flag repeats it while frames keep coming."""
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
