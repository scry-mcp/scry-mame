"""The SEQUENCE executor: a list of the server's own operations, run in order, in one call.

`perform([...])` runs a LIST of the server's own operations, addressed by NAME: the caller
says the high-level steps, the server does the round trips. Ten goldens through loose calls
are twenty round trips and twenty replies to read, and a goldens run is one call.

The executor takes the operation table (`ops`) from the server, which owns the
registrations, so this module names no tool: it dispatches what it is handed, waits for the
machine to stop before a console step when a step let it run, and hands back the stop the
list was heading for. The rules: every step is
checked BEFORE the first one runs (its op, its argument names against the tool's own
signature, and the values the tool would refuse), every refusal is listed, and the list
stops at the first step that answers INVALID with the steps that ran as the account.
"""

from __future__ import annotations

import functools
import inspect
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scry_core import media_tools, prose, sequence
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core import sequence_account as account
from scry_core import steps as step_judge
from scry_core import value_format as vf
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_advance as advance
import mame_arming as arming
import mame_audio as maudio
import mame_blits as mblits
import mame_block as block
import mame_breakpoints as breakpoints
import mame_comments as comments
import mame_cpus as cpus
import mame_draft as mdraft
import mame_envelope as menvelope
import mame_files as files
import mame_film as mfilm
import mame_focus as mfocus
import mame_gfx as mgfx
import mame_inputs as inputs
import mame_locate as mlocate
import mame_lua as mlua
import mame_machine as machine
import mame_manifest as manifest
import mame_maps as mmaps
import mame_palette as mpalette
import mame_ramdac as mramdac
import mame_read as read
import mame_recording as mrec
import mame_regpoints as regpoints
import mame_running as running
import mame_savestates as savestates
import mame_scan as mscan
import mame_screen as mscreen
import mame_series as mseries
import mame_state as st
import mame_sweep as msweep
import mame_trace as mtrace
import mame_watches as watches
import mame_write as mwrite
from mame_state import STATE

Ops = dict[str, Callable[..., dict[str, Any]]]

#: The two tools whose steps ARE the calls: a list, and one act with its expectation.
SEQUENCES = frozenset({"perform", "drive"})
#: THE TOOLS THAT ARE NO STEP OF A SEQUENCE, named once: the session's own lifecycle (`start`,
#: `close`, `rom_check`, which answers about the files), the sequences themselves, and the export
#: of the session a list belongs to. What a list may not call, what the recording keeps out, what
#: the pre-gate has no half of and what answers while the machine runs are each read off it.
NOT_STEPS = SEQUENCES | {"start", "close", "rom_check", "perform_export"}

# Ops that may run on a RUNNING machine: they read a file or the log, arm through a stub
# that takes it while running (measured), or ask the session. Everything else needs a
# stopped machine, so a sequence WAITS for the next stop before dispatching one. THE ONE
# LIST: the server's refusal names the same tools from here, because a second copy drifted
# (a tool that answered while running was refused by the sequence for want of its name).
RUNNING_OK_OPS = {"status", "cpu_info", "stop", "log", "log_wait", "snapshot", "state_list",
                  "captures",
                  "breakpoint_at",
                  "breakpoint_list", "breakpoint_clear", "watch_add", "watch_list",
                  "watch_clear", "regpoint_add", "regpoint_list", "regpoint_clear",
                  "comment_list", "comment_save", "symbols_find", "throttle", "machine_map",
                  "gfx_load", "palette_log", "gfx_film", "scan_clear", "map_load", "map_save",
                  # the media file tools read files, never the machine
                  *media_tools.TOOLS}
# The one op among them with a gesture that needs a stop: a film's arming reads the screen.
_STOPPED_GESTURE: dict[str, Callable[[dict[str, Any]], bool]] = {
    "gfx_film": lambda a: mfilm.arms(str(a.get("trigger", "")), bool(a.get("clear")))}


#: The one gesture of a stopped reader that answers on a running machine: the registers as the
#: last stop surveyed them, which reads no cpu.
_RUNNING_GESTURE: dict[str, Callable[[dict[str, Any]], bool]] = {
    "registers": lambda a: a.get("from_last_stop") is True}


def answers_running(op: str, args: dict[str, Any]) -> bool:
    """Whether this step answers on a running machine (`RUNNING_OK_OPS`, less a gesture of
    theirs that needs a stop, plus a gesture of a reader that needs none), so the sequence
    sends it without waiting for one."""
    if (runs := _RUNNING_GESTURE.get(op)) is not None and runs(args):
        return True
    needs_stop = _STOPPED_GESTURE.get(op)
    return op in RUNNING_OK_OPS and not (needs_stop is not None and needs_stop(args))


# How often the wait for a stop asks the socket, and the largest bound a sequence takes.
STOP_POLL_S = 0.1
# THE OP A LIST RUN `until_frame` NEEDS: `run_for` walks through a watch's stop as a stop of its
# own and carries on at the next step, where `run_to` and `step` end at the first one.
UNTIL_OP = "run_for"
# THE BOUNDS ON A LIST RUN `until_frame`: a window takes its frames plus its stops, and a counter
# that never reaches the frame (every run cut before the frame ends) must end somewhere, in steps
# and in time, since the whole cycle holds the server's one lock.
UNTIL_STEPS_MAX = 5000
UNTIL_SECONDS_MAX = vocab.WAIT_MAX_S


# ------------------------------------------------------- what a STEP's values are held to
#
# ONE ENTRY PER OPERATION THAT HAS A MACHINE-INDEPENDENT HALF, AND EVERY ENTRY IS THE OPERATION'S
# OWN `check_*`: the very function the tool calls when it is called alone, so a batch can never
# refuse a step in different words, or in a different order, than the same call made on its own.
# THIS IS THE ONE TABLE: the surface's (`mame_args.BY_TOOL`) is built FROM it, plus the three
# tools that are not operations, so an operation cannot be judged at the surface and skipped here
# -- `preflight` skips an
# operation with no entry, and a skipped later step runs every step before it.
BY_OP: dict[str, Callable[..., Any]] = {
    "log": files.check_log,
    "log_wait": files.check_log_wait,
    "run_to": advance.check_run_to,
    "run_for": advance.check_run_for,
    "trace": mtrace.check_trace,
    "step": advance.check_step,
    "resume": running.check_resume,
    "throttle": mlua.check_throttle,
    "breakpoint_at": breakpoints.check_breakpoint_at,
    "watch_add": watches.check_watch_add,
    "regpoint_add": regpoints.check_regpoint_add,
    "comment_add": comments.check_comment_add,
    "comment_delete": comments.check_comment_delete,
    "comment_save": comments.check_comment_save,
    "comment_load": comments.check_comment_load,
    "read_memory": read.check_read_memory,
    "registers": read.check_registers,
    "read_block": block.check_read_block,
    "disassemble": read.check_disassemble,
    "find": read.check_find,
    "history": read.check_history,
    "symbols_find": read.check_symbols_find,
    "memdump": files.check_memdump,
    "snapshot": files.check_snapshot,
    "write": mwrite.check_write,
    "set_register": mwrite.check_set_register,
    "record": mrec.check_record,
    "audio_record": maudio.check_audio_record,
    "input": mlua.check_input,
    "screen_signature": mscreen.check_screen_signature,
    "map_load": mmaps.check_map_load,
    "map_save": mmaps.check_map_save,
    "map_add": mmaps.check_map_add,
    "series_capture": mseries.check_series_capture,
    "lua": mlua.check_lua,
    "state_save": savestates.check_state_name,
    "state_load": savestates.check_state_name,
    "focus": mfocus.check_focus,
    "palette": mpalette.check_palette,
    "screen_view": mscreen.check_screen_view,
    "gfx_view": mgfx.check_gfx_view,
    "gfx_locate": mlocate.check_gfx_locate,
    "gfx_sweep": msweep.check_gfx_sweep,
    "gfx_draft": mdraft.check_gfx_draft,
    "gfx_load": manifest.check_gfx_load,
    "gfx_blits": mblits.check_gfx_blits,
    "gfx_blit_source": mblits.check_gfx_blit_source,
    "palette_log": mramdac.check_palette_log,
    "gfx_film": mfilm.check_gfx_film,
    "scan_start": mscan.check_scan_start,
    "scan_filter": mscan.check_scan_filter,
    "breakpoint_clear": breakpoints.check_breakpoint_clear,
    "watch_clear": watches.check_watch_clear,
    "regpoint_clear": regpoints.check_regpoint_clear,
    "debug": mwrite.check_debug,
    "machine_map": machine.check_machine_map,
    # The media file tools' judges are scry-core's, beside their bodies.
    **{name: spec.check for name, spec in media_tools.TOOLS.items()},
}

#: OPERATIONS WITH NO MACHINE-INDEPENDENT HALF, named so an absent entry above is a decision and not
#: an omission. Every argument these take is one the machine decides: a row the debugger lists, a
#: capture it wrote, a state on its disk -- or they take none.
MACHINE_JUDGES = frozenset({
    "breakpoint_list", "watch_list", "regpoint_list", "comment_list",
    "state_list", "captures", "stop", "status", "reset", "cpu_info",
    "scan_clear", "map_find",
})

# -------------------------------------------------------------------------- the sequence


def check_perform(settle_seconds: float = 30.0, summaries: bool = False, until_frame: int = 0,
                  **_: Any) -> None:
    """`perform`'s machine-independent half: the bound on waiting for a stop, that `summaries`
    is a yes or a no, and that `until_frame` is a frame and comes with `summaries` (a window of
    frames is hundreds of steps, which unsummarised cross what the client takes in line). The
    STEPS are not an argument of this function on purpose -- their vocabulary and values are
    `refuse_steps`'s, which needs the server's operation table and is asked by the tool right
    after this; `check_until` judges them for `until_frame`."""
    validate_settle(settle_seconds)
    account.check_summaries(summaries)
    inputs.natural("until_frame", until_frame, " is a frame number, 0 for none")
    if until_frame and not summaries:
        raise st.Invalid("bad_argument",
                         "until_frame needs summaries=True: a window of frames is hundreds of "
                         "steps, and their full replies would not fit one reply")


def check_until(steps: list[Any], until_frame: int) -> None:
    """A list run `until_frame` must advance the machine through the window, or it repeats
    without arriving; and the frame must be ahead of the machine, or the first step ends it with
    a count of one that looks clean."""
    if not until_frame:
        return
    advance.refuse_frameless("until_frame")
    if not any(isinstance(s, dict) and s.get("op") == UNTIL_OP for s in steps):
        raise st.Invalid("bad_argument",
                         f"until_frame repeats the list until a stop reaches the frame, so the "
                         f"list needs a `{UNTIL_OP}` step (`frames: 1` walks a window one frame "
                         f"at a time)")
    here = st.last_stop_frame()
    ses = STATE.ses
    # ON A RUNNING MACHINE THE FRAME IS NOT KNOWN YET: `_Window.after` judges the first stop
    # instead.
    if here is not None and here >= until_frame and not (ses is not None and ses.running):
        raise st.Invalid("bad_argument",
                         f"until_frame={until_frame} is not ahead of the machine, which stands at "
                         f"frame {here}: the frame is absolute, the one the window ends at")


def check_drive(act: Any = None, expect: str = "", seconds: float | None = None,
                pattern: str = ".", limit: int = 40, settle_seconds: float = 30.0,
                summaries: bool = False,
                **_: Any) -> tuple[re.Pattern[str], re.Pattern[str] | None]:
    """`drive`'s machine-independent half: the act's SHAPE, the two regexes, the line cap, the
    bound, `summaries`, and the one contradiction (`seconds` with no `expect` bounds a wait
    nobody asked for). The two regexes are handed back compiled (`expect`'s None when there is
    none), so the look and the verify search with what was judged.
    Which OPERATIONS the act names is checked against the server's own table inside the tool."""
    if not isinstance(act, list) or not act:
        raise st.Invalid("bad_argument",
            "act is a non-empty LIST of steps ({'op': <name>, ...}), the same shape "
                         "`perform` takes")
    pattern_rx = inputs.regex("pattern", pattern)
    inputs.count("limit", limit, read.LOG_LIMIT_MAX)
    expect_rx = inputs.regex("expect", expect) if expect else None
    vocab.check_wait(DRIVE_EXPECT_WAIT_S if seconds is None else seconds)
    if not expect and seconds is not None:
        raise st.Invalid("bad_argument",
            "`seconds` bounds the wait for `expect`, and there is no `expect`: it would be "
                         "silently ignored")
    validate_settle(settle_seconds)
    account.check_summaries(summaries)
    return pattern_rx, expect_rx


def validate_settle(settle_seconds: float) -> None:
    """The bound a sequence waits for the machine to settle at a stop: zero means never wait."""
    vocab.check_wait(settle_seconds, name="settle_seconds", zero_means="never wait")


def _as_wrapped(params: dict[str, inspect.Parameter], args: dict[str, Any]) -> dict[str, Any]:
    """A step's arguments as this server's tool wrapper passes them: an integral float is the
    count it equals (`inputs.integral_counts`)."""
    return {n: inputs.integral_counts(v, params[n].annotation)
            if n in params and isinstance(params[n].annotation, str) else v
            for n, v in args.items()}


def preflight(steps: list[Any], ops: Ops) -> list[dict[str, Any]]:
    """EVERY STEP IS CHECKED BEFORE ANY STEP RUNS, its op, its argument NAMES and its
    argument VALUES, and every refusal is collected rather than the first one returned: a
    list whose third step is not a step must not have released the machine at its first.
    Returns the refusals, each `step`, `op`, `code`, `message`."""
    refused: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        op = sequence.step_op(step)
        if op is None or op not in ops:
            refused.append(sequence.not_a_step(i, step, "the step names no `op`"))
            continue
        refusal, args = step_judge.judge(ops[op], step, prepare=_as_wrapped)
        if refusal is not None:
            refused.append({"step": i, "op": op, **refusal})
            continue
        params = step_judge.signature_of(ops[op]).parameters
        check = BY_OP.get(op)
        try:
            # A number reaches the check as the integer the tool itself reads.
            args = inputs.numbers_read(ops[op], args)
            if check is not None:
                # EVERY DEFAULT IS THE TOOL'S: what the step leaves out is filled from the
                # tool's own signature, so the check judges what the tool will be called with
                # and its own defaults are never the ones a step runs on.
                judged = step_judge.signature_of(check).parameters
                check(**{**{n: p.default for n, p in params.items()
                            if n in judged and p.default is not p.empty and n != "ctx"},
                         **args})
        except TypeError as e:
            # A value of the wrong TYPE: `bind` above checks names only, and every check compares
            # numbers, so a string where an int belongs raises here rather than refusing.
            refused.append({"step": i, "op": op, "code": "bad_argument",
                            "message": f"carries a value of the wrong type: {e}"})
            continue
        except st.Invalid as e:
            refused.append({"step": i, "op": op, "code": e.code, "message": str(e)})
    return refused


def _leaves_running(_op: str, reply: dict[str, Any]) -> bool:
    """Whether a step left the machine running, read from its OWN reply and from nothing
    else: a step that released the machine says so in the field, whoever it was.

    NAMING THE OPS THAT CAN RELEASE IS AN ENUMERATION, and it went stale: it said only
    `resume` could, while a go-family command typed through `debug` sets the same field
    (`mame_console.releases`), so a `perform` that ended with one reported `steps_completed`
    over a running machine and dispatched the next step against it. The same
    wildcard-not-enumeration argument is written at `mame_write.py` for the classifier that
    decides which commands those are.

    THE FIELD IS THE `session` BLOCK'S, which `mame_mcp.tool` composes after the step's
    body, so it says what the machine is doing once the step is over. It is safe to trust
    here because the caller asks only for an op OUTSIDE `RUNNING_OK_OPS`: a running-ok reader
    on a machine already moving carries the same `running: true`, and this is never asked
    about one."""
    session = reply.get("session")
    return isinstance(session, dict) and bool(session.get("running"))


def _something_can_stop_it() -> bool:
    """A stop breakpoint, a registerpoint or a change watch armed: something the machine can
    halt on. A control never halts, so a session with only controls declared cannot be
    waited for."""
    return (any(rec["owner"] not in STATE.controls for rec in STATE.breakpoints.values())
            or bool(STATE.regpoints) or bool(STATE.armed_watches))


def _wait_for_stop(ses: Any, scratch: Path, seconds: float, progress: mprogress.Progress,
                   record: bool = True) -> sequence.Waited:
    """`stopped` | `running` | `gone`, asked until the bound by the proof the release allows
    (`running.came_to_rest`): the stub's packet for its own runs, the frame counter for a run
    the console started, which sends none. A channel that fails while it waits is `gone` when
    MAME died (a connection that failed gives the process `GONE_GRACE_S` to show its exit,
    since the socket closes before the exit is seen); else it is answered as any tool's session
    error is (`running.session_error_reply`: a refusal the stub answered latches nothing, the
    rest latch broken), and the executor ends the list with it, beside what ran
    (`scry_core.sequence`)."""
    try:
        clock = mprogress.Ticker(seconds, progress)
        while not clock.expired():
            if running.came_to_rest(ses, scratch, min(STOP_POLL_S, clock.left()), record):
                return "stopped"
            clock.tick("waiting for the machine to stop: {elapsed:.0f}s of {seconds:g}s",
                       seconds=seconds)
        return "stopped" if running.came_to_rest(ses, scratch, 0.0, record) else "running"
    except gs.NotStopped as e:
        raise st.Invalid("not_stopped", str(e)) from None
    except gs.SessionError as e:
        if not _alive_after(e):
            return "gone"
        said = running.session_error_reply(e, "the wait for a stop",
                                           tail="The list waited for a stop")
        code: contract.Code = said["code"]
        raise st.Invalid(code, said["message"]) from None


#: How long a connection that failed waits for MAME's exit to show before it is called broken.
GONE_GRACE_S = 0.5


def _alive_after(error: gs.SessionError) -> bool:
    """Whether MAME still runs once a channel failed: at once, or, for a connection that
    failed, after `GONE_GRACE_S` for its exit to be seen."""
    if not STATE.machine_alive() or not isinstance(error, gs.ConnectionFailed):
        return STATE.machine_alive()
    proc = STATE.proc
    assert proc is not None                     # alive above
    try:
        proc.wait(GONE_GRACE_S)
    except subprocess.TimeoutExpired:
        return True
    return False


#: `drive`'s look when the act was refused before anything ran.
NOTHING_LOOKED_WHY = "the act was refused before anything ran, so the log was not looked at"


def _reached(frame: int | None) -> int | dict[str, Any]:
    """`until_frame`'s `frame_reached`, or why there is none: no stop of the list read one."""
    return or_unavailable(frame, "no stop of the list read a frame")


def _account(ran: dict[str, Any]) -> dict[str, Any]:
    """The run's account as `drive` reports it, under its own key: everything `run_steps` said minus
    the envelope's own fields. One projection, used by `drive` and by the refusal that precedes it,
    because a tool answering two shapes for one kind of failure is a tool a caller cannot parse."""
    return sequence.act_told(ran)


def refuse_act(act: list[Any], ops: Ops, pattern: str,
               ses: Any = None, shape: bool = True) -> dict[str, Any] | None:
    """`drive`'s shape for an act refused before anything moved, or None when it is sound: `act`,
    `verify` and `looked` all present, in the shapes the tool documents, so a caller parses one
    reply whether the refusal came before the machine or after a step. `looked` is honest about
    having looked at nothing: `available` is false and every count is zero. With the session,
    the cpus and the refs the steps name are judged too (`refuse_machine`); `shape` False when
    the caller already judged the act's shape, so it is judged once."""
    try:
        refusal = ((refuse_steps(act, ops) if shape else None)
                   or (None if ses is None else refuse_machine(ses, act)))
    except st.Invalid as e:
        return drive_refused(e.code, str(e), pattern)
    if refusal is None:
        return None
    named = {key: refusal.pop(key) for key in ("operations", "cpu_tags") if key in refusal}
    return drive_refused(refusal.get("code", "bad_argument"), str(refusal.get("message")), pattern,
                         _account(refusal), **named)


def drive_refused(code: contract.Code, message: str, pattern: str,
                  act: dict[str, Any] | None = None,
                  **named: Any) -> dict[str, Any]:
    """`drive`'s refusal before anything ran, in the one shape every `drive` reply has: `act`,
    `verify` and `looked`, `looked` honest about having looked at nothing (`available` false,
    every count zero). An argument `drive` refuses on its own comes here too, so a caller
    parses one reply whichever check refused it."""
    return menvelope.invalid(code, message,
                             act=act if act is not None else {"ran": [], "steps_completed": 0,
                                                              "failed": sequence.none_failed(),
                                                              "failed_at": sequence.none_failed()},
                             **named,
                             verify={"checked": False,
                                     "why": "the act was refused before anything ran"},
                             looked={"emulator": unavailable(NOTHING_LOOKED_WHY)})


def refuse_steps(steps: list[Any], ops: Ops) -> dict[str, Any] | None:
    """The whole list's refusal, or None when every step's op, argument NAMES and VALUES are sound.

    IT NEEDS NO MACHINE, which is why it is its own function: the server asks it before fetching
    the live session, so a batch with a bad step is refused on a cold server as on a warm one, and
    never after some of its steps have run.

    It is a REPLY rather than a raised refusal because it carries the whole account -- every step
    that was refused, not just the first -- which is the thing that makes one round of fixing
    enough.
    """
    if not steps:
        # AN EMPTY LIST RAN NOTHING, and `ok` over nothing examined is a green nobody earned:
        # refused in the words `drive` refuses an empty act.
        raise st.Invalid("bad_argument", "steps is a non-empty LIST of steps ({'op': <name>, "
                                         "...}): an empty one would run nothing")
    refused = preflight(steps, ops)
    if not refused:
        return None
    return _list_refused("bad_argument", refused, **sequence.vocabulary_named(refused, ops))


def refuse_machine(ses: Any, steps: list[Any]) -> dict[str, Any] | None:
    """The machine's halves of the preflight, in order: the cpus the steps name, then their refs
    (`refuse_cpus`, `refuse_refs`). Asked once `refuse_steps` passed every step."""
    return refuse_cpus(ses, steps) or refuse_refs(ses, steps)


def refuse_cpus(ses: Any, steps: list[Any]) -> dict[str, Any] | None:
    """The machine's half of the preflight: every step's `cpu` judged against the machine's cpus
    before any step runs, so a cpu the machine lacks refuses the LIST, as a bad op does, and never
    after the steps before it moved the machine. Asked once `preflight` passed every step."""
    refused: list[dict[str, Any]] = []
    tags: list[str] = []
    for i, step in enumerate(steps):
        cpu = step.get("cpu")
        if not isinstance(cpu, str) or not inputs.cpu_given(cpu):
            continue
        try:
            cpus.named(ses, cpu)
        except st.Invalid as e:
            refused.append({"step": i, "op": step["op"], "code": e.code, "message": str(e)})
            tags = e.fields.get("cpu_tags", tags)
    if not refused:
        return None
    return _list_refused("unknown_ref", refused, cpu_tags=tags)


#: EACH OPERATION'S REF-LIKE ARGUMENTS, read by the address rule (`inputs.classify`) before the
#: list runs where the table they are read against is already known. Not `gfx_blit_source`'s
#: `pc`, read on the capture's cpu, which only the rows say; not a clear's or a delete's `ref`,
#: which an earlier step may have declared.
REF_ARGS: dict[str, tuple[str, ...]] = {
    "run_to": ("ref", "control"), "breakpoint_at": ("ref",), "watch_add": ("ref", "trigger"),
    "comment_add": ("ref",), "read_memory": ("ref",), "read_block": ("ref",),
    "disassemble": ("ref",), "find": ("ref",), "scan_start": ("ref",), "write": ("ref",),
    "memdump": ("ref",), "gfx_view": ("ref",), "gfx_locate": ("ref",), "gfx_sweep": ("ref",),
    "gfx_film": ("trigger", "pc"),
}
#: The operations after which the visible cpu is no longer the one the list began on: a focus, a
#: stop (which makes the stopping cpu visible), and any call that runs or may run the machine.
#: Past the first of them a step naming no cpu is read against a table nobody can know before
#: the list runs, so it is judged when it runs.
MOVES_VISIBLE = frozenset({
    "focus", "step", "run_to", "run_for", "resume", "trace", "debug", "stop", "log_wait",
    "reset", "state_load", "lua", "input", "record", "audio_record", "screen_signature",
    "gfx_film", "series_capture"})
#: The declaring operations, whose rows stored by name stay reachable by that name.
_DECLARES = {"breakpoint_at": "breakpoint", "watch_add": "watch", "comment_add": "comment"}


def _ref_args(step: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """The (argument, text, is a pointer's base) triples of `step` the address rule reads, as the
    tool will read them: a pointer's base rather than the pointer, whether `by` named the
    pointer or `auto` found it; never a port (the io space's own rule), an expression, or a
    `ref` that `by` already says (address, symbol, or a pointer the text is not)."""
    op, io = step["op"], step.get("space", "program") != "program"
    out = []
    for arg in REF_ARGS.get(op, ()):
        text = step.get(arg)
        if not isinstance(text, str) or not text.strip():
            continue
        by = step.get("by", "auto")
        if arg == "ref" and op in ("breakpoint_at", "watch_add") and by != "auto" and (
                by != "pointer" or vf.parse_pointer(text) is None):
            continue
        if op == "watch_add" and (arg == "ref" and (step.get("mode") == "expr"
                                                    or io and step.get("mode") == "count")
                                  or arg == "trigger" and io):
            continue
        if op == "gfx_film" and arg == "trigger" and io:
            continue
        pr = vf.parse_pointer(text)
        out.append((arg, text, False) if pr is None else (arg, pr.base, True))
    return out


def _held_triggers(step: dict[str, Any], on: str | None) -> list[str]:
    """The trigger names the capture on this step's block is held on (`arming.held_triggers`),
    its block read as the tool reads it: a pointer by its grammar, else `0x` an address and
    anything else a name."""
    block = step.get("ref")
    if not isinstance(block, str):
        return []
    by = step.get("by", "auto")
    if by == "auto":
        by = ("pointer" if vf.parse_pointer(block) is not None
              else "address" if inputs.is_address(block) else "symbol")
    return arming.held_triggers(on, block, by)


def refuse_refs(ses: Any, steps: list[Any]) -> dict[str, Any] | None:
    """The address rule's half of the preflight: every ref a step gives, read against the table
    it will be read against, before any step runs, wherever that table is known now: the step
    names its cpu, or it comes before the first step that can move the visible cpu. Bare hex
    naming no symbol refuses the LIST, as a bad cpu does. Asked once `refuse_cpus` passed. The
    names rows are stored under are the ones held before the list, and the ones an earlier step
    of the same list declares `by="symbol"` on the same cpu (on any, where that step's cpu is not
    known before the list runs), which that step will have stored when this one runs; a
    capture's trigger is read beside the names its block's capture is held on
    (`_held_triggers`)."""
    refused: list[dict[str, Any]] = []
    moved, visible = False, None
    declared: dict[tuple[str, str | None], list[str]] = {}
    for i, step in enumerate(steps):
        cpu = step.get("cpu")
        named = isinstance(cpu, str) and inputs.cpu_given(cpu)
        known = named or not moved
        triples = _ref_args(step) if known else []
        declares = _DECLARES.get(step["op"]) if step.get("by") == "symbol" else None
        on = None
        if triples or (known and declares):
            try:
                on = cpus.named(ses, cpu) if named else visible or cpus.visible_cpu(ses)
            except st.Invalid:
                on = None
            visible = visible if named else on
        for arg, text, base in triples:
            kind = _DECLARES.get(step["op"]) if arg == "ref" and not base else None
            held = ([*declared.get((kind, on), []), *declared.get((kind, None), [])] if kind
                    else _held_triggers(step, on) if arg == "trigger" and step["op"] == "watch_add"
                    else [])
            try:
                arming.classify_call(text, on, kind, held)
            except inputs.BareHex as e:
                refused.append({"step": i, "op": step["op"], "code": e.code,
                                "message": str(e)})
        if declares and isinstance(step.get("ref"), str):
            declared.setdefault((declares, on if known else None), []).append(step["ref"])
        moved = moved or step["op"] in MOVES_VISIBLE
    if not refused:
        return None
    return _list_refused("unknown_ref", refused)


def _list_refused(code: contract.Code, refused: list[dict[str, Any]],
                  **named: Any) -> dict[str, Any]:
    """A whole list refused before anything ran: every refused step in `errors`, the first in
    `failed`, and the fields that name the vocabulary it was judged against."""
    return menvelope.invalid(code, sequence.refused_text(refused),
                             ran=[], steps_completed=0, failed_at=refused[0]["step"],
                             failed=refused[0],
                             errors=refused, **named)


def _entry(op: str, reply: dict[str, Any]) -> dict[str, Any]:
    """One step in the account: its op, the cpu its reply names (the cpu it read, armed on or
    stopped on) when it names one, and its reply."""
    return {"op": op, **({"cpu": reply["cpu"]} if isinstance(reply.get("cpu"), str) else {}),
            "reply": reply}


def _stop_extra(reply: dict[str, Any], cut: dict[str, Any]) -> None:
    """What a stop's compact row keeps beyond its keys: its `watch_hit` without the lists (its
    `writes`), and its `regpoint_hit`."""
    if isinstance(hit := reply.get("watch_hit"), dict):
        cut["watch_hit"] = {k: v for k, v in hit.items() if not isinstance(v, list)}
    if "regpoint_hit" in reply:
        cut["regpoint_hit"] = reply["regpoint_hit"]


#: THIS SERVER'S HALF OF THE ACCOUNT (`scry_core.sequence_account`): a stop's compact row keeps
#: where and when it stopped, what stopped it and its number, spelled as the full reply spells
#: them, and is counted by `cause` with the writer taken off (one watch is one key, whoever
#: wrote). The rule is the stop without its lists (`regs`, `dasm`, `errorlog`, `watches`, a
#: hit's `writes`), which stay in the full reply.
SHAPE = account.Shape(kept=("cause", "pc", "frame", "stop_seq"),
                      cause_key=lambda stop: watches.cause_key(str(stop.get("cause"))),
                      extra=_stop_extra)


def account_of(ran: list[dict[str, Any]], summaries: bool, keep_last: bool, scratch: Path,
               since: int, also: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`ran` as the reply carries it, and with `summaries` what the machine counted
    (`scry_core.sequence_account.account`): the kept step is the one that matters, the last of
    a list that completed, whose stop is the one the list was heading for, and the step that
    left the machine running when a console step could not follow it, whose
    `session.running` and `waited_s` say so; a list that failed at a step keeps that step whole
    under `failed`. The files go to the scratch, numbered per call."""
    return account.account(ran, summaries, keep_last, since,
                           int(STATE.last_stop.get("seq", 0)), SHAPE,
                           lambda: scratch / f"batch-{STATE.next_number('batches')}", also,
                           rows_shown=st.ROWS_SHOWN)


#: A reply's own fields that are not the stop's: what `rested` leaves out of a step's reply.
_ENVELOPE = frozenset({"summary", "status", "session", "stopped_on_its_own", "applied_on_stop"})


class _Mame(sequence.SequenceMachine):
    """This server's half of a list (`scry_core.sequence`): its stops proved by the stub's packet
    or the frame counter, the visible cpu a `focus` or a `debug` line asked for, and the account
    in this server's shape."""

    stoppers = "A breakpoint, a registerpoint or a watch"
    undeclared = "no stop breakpoint, no registerpoint, no change watch: a control never halts"

    def __init__(self, ses: Any, scratch: Path, summaries: bool) -> None:
        self.ses, self.scratch, self.summaries = ses, scratch, summaries
        self.since = int(STATE.last_stop.get("seq", 0))  # the stops this list numbers follow it
        #: The visible cpu the last step that set one read back.
        self.asked: str | None = None

    def answers_running(self, op: str, args: dict[str, Any]) -> bool:
        return answers_running(op, args)

    def running(self) -> bool:
        return bool(self.ses.running)

    def leaves_running(self, op: str, reply: dict[str, Any]) -> bool:
        return _leaves_running(op, reply)

    def wait_for_stop(self, seconds: float, progress: mprogress.Progress,
                      tail: bool = False) -> sequence.Waited:
        return _wait_for_stop(self.ses, self.scratch, seconds, progress, record=not tail)

    def can_be_stopped(self) -> bool:
        return _something_can_stop_it()

    def tail_stop(self) -> dict[str, Any]:
        return running.stop_reply(self.ses, self.scratch, running.name_stop(self.ses))

    def account(self, ran: list[dict[str, Any]], keep_last: bool,
                also: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return account_of(ran, self.summaries, keep_last, self.scratch, self.since, also)

    def entry(self, op: str, reply: dict[str, Any]) -> dict[str, Any]:
        return _entry(op, reply)

    def missed(self, op: str, reply: dict[str, Any]) -> bool:
        """A step's own wait for what it was to see ran out (a `log_wait` TIMEOUT): the steps
        after it were built on it, so the list ends there."""
        return op == "log_wait" and reply.get("verdict") == contract.TIMEOUT

    def rested(self, ran: list[dict[str, Any]]) -> dict[str, Any] | None:
        """THE STOP CAME DURING THE LAST STEP (a `stop`, or a breakpoint that fired while a
        declaration went in): it is the stop the run was heading for. One the step surveyed
        itself (`stop`'s own reply, or the stop its contact found on its own) is named as that
        reply carried it, never surveyed twice: a second survey numbers it again and reads the
        log past its cause; any other is surveyed now."""
        last = ran[-1]["reply"] if ran else {}
        if isinstance(last.get("stop_seq"), int):
            return {k: v for k, v in last.items() if k not in _ENVELOPE}
        found = last.get("stopped_on_its_own")
        if isinstance(found, dict) and isinstance(found.get("stop_seq"), int):
            return dict(found)              # the step's contact found it and surveyed it
        return self.tail_stop()

    def noted(self, op: str, reply: dict[str, Any]) -> None:
        shown = reply.get("cpu") if op == "focus" else (
            reply.get("visible_cpu") if op == "debug" else None)
        # an unread visible cpu (unavailable, or none) leaves the last one asked
        self.asked = shown if isinstance(shown, str) else self.asked


class _Window(sequence.Cycle):
    """A list run `until_frame`, repeated until a stop reply carries a `frame` at or past it,
    because the steps a window of frames takes are its frames plus the stops inside it, and the
    stops are what is being measured: no caller can size that list before the run, and a list
    sized by guessing ends short of the window, reporting a smaller count that looks clean. The
    window is the frames BEFORE `until_frame`: the run ends right after the first step whose stop
    reads it, even mid-list. `UNTIL_STEPS_MAX` and `UNTIL_SECONDS_MAX` bound it, and a stop that
    carries no frame ends it, since nothing then says whether the window is over."""

    def __init__(self, ses: Any, until_frame: int, progress: mprogress.Progress) -> None:
        self.limit = UNTIL_STEPS_MAX
        self.until = until_frame
        # THE FRAME BEFORE THE WINDOW IS KNOWN ONLY ON A STOPPED MACHINE (`check_until`): on a
        # running one the first stop is where the window is seen to start.
        self.blind = bool(ses.running)
        self.start = None if self.blind else st.last_stop_frame()
        self.reached: int | None = None
        self.clock = mprogress.Ticker(UNTIL_SECONDS_MAX, progress)
        #: The window's last progress line, sent once the list has landed.
        self.last_line: Callable[[], None] = _no_line

    def expired(self) -> bool:
        return self.clock.expired()

    def after(self, reply: dict[str, Any], steps_completed: int,
              step: str) -> sequence.Stop | bool:
        if not account.stops_in(reply):
            return False
        frame = _frame_of(reply)
        if frame is None:
            return sequence.Stop("unexpected_answer",
                                 f"{step} stopped with no frame read, so "
                                 f"nothing says whether frame {self.until} was reached: the "
                                 "list ends here")
        if self.blind and self.reached is None and frame >= self.until:
            self.reached = frame
            return sequence.Stop("bad_argument",
                                 f"the machine was running when the list began and its first "
                                 f"stop already reads frame {frame}, at or past "
                                 f"until_frame={self.until}: nothing of the window was walked")
        self.reached = frame
        template = "perform until frame {until}: frame {frame}, {steps}"
        said = {"until": self.until, "frame": frame,
                "steps": prose.counted(steps_completed, "step")}
        if frame >= self.until:
            if self.start is not None:
                self.last_line = functools.partial(self.clock.finish, self.until - self.start,
                                                   template, **said)
            return True
        if self.start is None:
            self.clock.tick(template, **said)
        else:
            self.clock.report(frame - self.start, self.until - self.start, template, **said)
        return False

    def short(self, steps_completed: int) -> sequence.Stop | None:
        if self.reached is not None and self.reached >= self.until:
            return None
        return sequence.Stop(None, "", {
            "verdict": contract.TIMEOUT,
            "note": f"until_frame={self.until} was not reached in "
                    f"{prose.counted(steps_completed, 'step')} and {self.clock.elapsed():.0f} s "
                    f"(the bounds are {UNTIL_STEPS_MAX} steps and {UNTIL_SECONDS_MAX:g} s): "
                    f"the last frame read was {self.reached}"})

    def fields(self) -> dict[str, Any]:
        return {"until_frame": self.until, "frame_reached": _reached(self.reached)}


def run_steps(ses: Any, scratch: Any, steps: list[Any], settle_seconds: float, ops: Ops,
              progress: mprogress.Progress = mprogress.no_progress, tail_wait: bool = True,
              summaries: bool = False, until_frame: int = 0,
              name: str = "perform", shape_judged: bool = False,
              machine_judged: bool = False) -> dict[str, Any]:
    """Execute steps in order (`scry_core.sequence.run`, its rules), STOPPING at the first
    failure with a full account: `ran` (each step, the cpu its reply names, and its reply, or
    with `summaries` its summary line, `account_of` says which), `failed_at` and `failed`,
    `steps_completed`; the tail when the list ends with the machine running; `verdict` once it
    waited; and, on a machine with several cpus, `visible_cpu` (the tag after the list) and
    `visible_cpu_kept` (`_keep_visible`). With `until_frame` the list repeats until a stop reply's
    `frame` reaches it (`_Window`), and the reply says so in `until_frame` and `frame_reached`.
    Each step reports its own progress through the list's, as `<name> step i of n (<op>): ...`.
    `shape_judged` and `machine_judged` say the caller already judged the list (`refuse_steps`,
    `refuse_machine`): each judge runs once a call, and the machine's asks the console."""
    refusal = ((None if shape_judged else refuse_steps(steps, ops))
               or (None if machine_judged else refuse_machine(ses, steps)))
    if refusal is not None:
        return refusal
    several = len(cpus.cpu_list(ses)) > 1
    was = cpus.visible_cpu(ses) if several and not ses.running else None
    machine = _Mame(ses, scratch, summaries)
    window = _Window(ses, until_frame, progress) if until_frame else None
    ended = sequence.run(machine, steps, ops, settle_seconds, progress, name, tail_wait, window)
    fields = {**ended.fields, "held": ended.held}
    if several:
        # ONE SHAPE FOR `visible_cpu` in every reply, `debug`'s and this one's: the tag; how the
        # list kept it is an account of its own.
        kept = _keep_visible(ses, was, machine.asked)
        fields["visible_cpu"], fields["visible_cpu_kept"] = kept["after"], kept
    # THE LIST HAS LANDED BEFORE ITS LAST LINE: that send is a poll, and a cancel met there would
    # otherwise leave the visible cpu where a stop moved it.
    if window is not None:
        window.last_line()
    return (menvelope.invalid(ended.code, ended.message, **fields) if ended.code
            else menvelope.envelope(fields))


def _frame_of(reply: dict[str, Any]) -> int | None:
    """The newest frame a reply's stops carry, the one a run `until_frame` is judged by."""
    known = [f for s in account.stops_in(reply) if isinstance(f := s.get("frame"), int)]
    return max(known) if known else None


def _no_line() -> None:
    """The last line of a list that has none to send."""


# A LIST THAT ALTERNATES CPUS DOES NOT LEAVE THE VISIBLE CPU MOVED unless a step asked for it.
# A stop inside the list moves it as MAME does (the stopping cpu becomes the visible one), and
# the list puts back, with the stub's `Hc`, which runs nothing, the cpu it keeps: the one it
# found, or the one the last `focus` step read back (a `debug` line with `focus`, `ignore` or
# `observe` that read one back counts as one). So a stop after a `focus` is undone too.
def _keep_visible(ses: Any, was: str | None, asked: str | None) -> dict[str, Any]:
    """`_kept_visible`'s account with each cpu it could not name said, never a null: `before`
    when the list began running or with none visible, `after` by the account's own `why`."""
    kept = _kept_visible(ses, was, asked)
    if kept["before"] is None:
        kept["before"] = unavailable("the list began with the machine running, or `cpulist` "
                                        "marked no cpu visible")
    if kept["after"] is None:
        kept["after"] = unavailable(str(kept.get("why") or "no cpu was read visible"))
    return kept


def _kept_visible(ses: Any, was: str | None, asked: str | None) -> dict[str, Any]:
    """The reply's `visible_cpu_kept`: `before` the first step, `asked` by the last step that set
    one, `after` the list and whether it was `restored` (read back), with `moved_to` for the
    cpu a stop left visible, and `why` when a put-back was due and not made."""
    kept = asked or was
    said: dict[str, Any] = {"before": was, **({"asked": asked} if asked else {})}
    if ses.running or ses.broken:
        return {**said, "after": None, "restored": False,
                "why": "the list ended with the machine running, or the session broken, so "
                       "the visible cpu is the next stop's"}
    if kept is None:
        return {**said, "after": cpus.visible_cpu(ses), "restored": False,
                "why": "the list began with the machine running, or `cpulist` marked no cpu "
                       "visible, so there was none to keep"}
    now = cpus.visible_cpu(ses)
    if now == kept:
        return {**said, "after": now, "restored": False}
    if now is None:
        return {**said, "after": None, "restored": False,
                "why": "`cpulist` marked no cpu visible after the list, so it was not put back"}
    try:
        cpus.make_visible(ses, kept, f"the list puts back {kept}, the visible cpu it keeps")
    except (st.Invalid, gs.SessionError) as e:
        # THE LIST RAN, and its account is the reply: a put-back that failed is said here.
        return {**said, "after": now, "restored": False, "why": str(e)}
    after = cpus.visible_cpu(ses)
    if after != kept:
        return {**said, "moved_to": now, "after": after, "restored": False,
                "why": f"`Hc` was taken and `cpulist` read back {after}, not {kept}"}
    return {**said, "moved_to": now, "after": after, "restored": True}


# ------------------------------------------------------------------------------ drive
#
# LOOK, ACT, VERIFY in one call, over the channel an arcade board has: the EMULATOR log
# (`error.log`, what the driver and the scripts `logerror`).

DRIVE_EXPECT_WAIT_S = 5.0       # the default bound on the wait for `expect`
DRIVE_POLL_S = 0.1


def _look(scratch: Path, mark: int, rx: re.Pattern[str], limit: int) -> dict[str, Any]:
    """The LOOK after an act: the emulator log's lines since the mark (`account.looked`)."""
    return account.looked("emulator", files.errorlog_since(scratch, mark)[0], mark, rx, limit)


def _verify(ses: Any, scratch: Path, pat: re.Pattern[str], wait_s: float, mark: int,
            progress: mprogress.Progress) -> dict[str, Any]:
    """The VERIFY: a line matching `pat` since the mark. On a RUNNING machine it is
    waited for up to `wait_s`, and a stop reached meanwhile ends the wait, because a
    stopped machine logs nothing more; on a STOPPED machine it is read ONCE, no wait."""
    expect = pat.pattern
    clock = mprogress.Ticker(wait_s, progress)
    while True:
        since, _end = files.errorlog_since(scratch, mark)
        hits = [ln for ln in since if pat.search(ln)]
        if hits:
            return {"checked": True, "seen": True, "verdict": contract.TARGET, "expected": expect,
                    "line": hits[0],
                    "lines_before": since.index(hits[0]), "lines_total": len(hits),
                    "waited_s": st.spent_s(clock.seconds())}
        if not ses.running:
            return {"checked": True, "seen": False, "expected": expect, "stopped": True,
                    "waited_s": st.spent_s(clock.seconds()),
                    "why": f"no line matching {expect!r} since the mark, and the machine is "
                           f"STOPPED at the debugger, so nothing more will be logged until it "
                           f"runs: waiting would not change the answer. A stop it reached "
                           f"during this wait is surveyed here, and this reply carries it as "
                           f"`stopped_on_its_own`"}
        if running.came_to_rest(ses, scratch, 0.0):
            continue                     # the stop is noted; the next pass reads and returns
        if clock.expired():
            return {"checked": True, "seen": False, "verdict": contract.TIMEOUT, "expected": expect,
                    "waited_s": st.spent_s(clock.seconds()),
                    "why": f"no new line matching {expect!r} within {wait_s:g} s, the machine "
                           "still running"}
        clock.tick("drive: waiting for {expect!r}, {elapsed:.0f}s of {bound:g}s",
                   expect=expect, bound=wait_s)
        time.sleep(DRIVE_POLL_S)


def drive(ses: Any, scratch: Path, ops: Ops, act: list[dict[str, Any]], expect: str,
          seconds: float | None, pattern: str, limit: int, settle_seconds: float,
          progress: mprogress.Progress = mprogress.no_progress,
          summaries: bool = False) -> dict[str, Any]:
    """The body of the `drive` tool."""
    pattern_rx, expect_rx = check_drive(act, expect, seconds, pattern, limit, settle_seconds,
                                        summaries)
    wait_s = DRIVE_EXPECT_WAIT_S if seconds is None else seconds
    # THE ACT'S VOCABULARY IS `preflight`'s, asked by `refuse_act` before the machine is fetched. A
    # loop here did the same thing with a different code, which is what two implementations of one
    # rule look like from the outside; it is gone rather than disabled.
    # THE CPUS THE STEPS NAME, judged against the machine before anything moves, in the
    # refusal's own shape (`refuse_act`).
    refusal = refuse_act(act, ops, pattern, ses, shape=False)   # its shape: the server's, before
    if refusal is not None:
        return refusal
    # THE MARK, before anything moves: where the emulator log ends now.
    _lines, mark = files.errorlog_since(scratch, 0)
    # THE ACT'S TAIL DOES NOT WAIT WHEN THE VERIFY IS THE WAIT: `perform` waits `settle_seconds`
    # for a stop after a trailing `resume`, and with an `expect` that wait would run out before
    # the verify began.
    ran = run_steps(ses, scratch, act, settle_seconds, ops, progress, name="drive",
                    tail_wait=not expect, summaries=summaries, shape_judged=True,
                    machine_judged=True)
    told = _account(ran)
    if ran.get("status") != "ok":
        # THE CODE IS THE STEP'S: a wait that found the session broken stays `session_broken`.
        act_code, said = sequence.act_stopped(ran)
        return menvelope.invalid(act_code, said, act=told,
                                 looked=_look(scratch, mark, pattern_rx, limit))
    checked: dict[str, Any] = dict(sequence.NO_EXPECT)
    if ran.get("verdict") == contract.TIMEOUT:
        # AN ACT THAT RAN OUT ITS WAIT DID NOT DO WHAT IT WAS ASKED, so nothing it did is
        # checked: the verdict is the act's, and the verify says why there is none.
        checked = sequence.act_ran_out()
    elif expect_rx is not None:
        checked = _verify(ses, scratch, expect_rx, wait_s, mark, progress)
        # THE STOP THE WAIT MET IS THIS REPLY'S: the verify consumes the stub's packet to
        # learn the machine stopped, and left there the survey would ride on the next
        # call's reply, of whatever tool, as a stop reached while nobody looked.
        running.observe_stop(ses, scratch)
        if checked.pop("stopped", False):
            # `log_wait`'s refusal: a stopped machine logs nothing, so no line can come. A bound
            # that ran out on a running one is the verify's `TIMEOUT`, an answer.
            return menvelope.invalid("wait_stopped",
                                     f"the act ran but the machine did not do what was expected: "
                                     f"{checked['why']}; `resume` lets it run, then `drive` "
                                     "again",
                                     act=told, verify=checked,
                                     looked=_look(scratch, mark, pattern_rx, limit))
    return menvelope.envelope({"act": told, "verify": checked,
                               "looked": _look(scratch, mark, pattern_rx, limit)})
