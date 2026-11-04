"""The SEQUENCE executor: `perform` and `drive` run a list of the server's own operations.

Every step is checked before the first one runs and every refusal is listed; the list stops at
the first step that answers INVALID, with the steps that ran as the account.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scry_core import frame_window, media_tools, roster, sequence
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core import sequence_account as account
from scry_core import steps as step_judge
from scry_core import value_format as vf
from scry_core import vocabulary as vocab
from scry_core.reply_contract import unavailable

from scry_mame import (
    advance,
    arming,
    block,
    breakpoints,
    cpus,
    files,
    folds,
    inputs,
    machine,
    manifest,
    read,
    regpoints,
    running,
    watches,
)
from scry_mame import audio as maudio
from scry_mame import blits as mblits
from scry_mame import cpu_focus as mfocus
from scry_mame import draft as mdraft
from scry_mame import envelope as menvelope
from scry_mame import film as mfilm
from scry_mame import gdb_session as gs
from scry_mame import gfx as mgfx
from scry_mame import locate as mlocate
from scry_mame import lua as mlua
from scry_mame import palette as mpalette
from scry_mame import ramdac as mramdac
from scry_mame import recording as mrec
from scry_mame import screen as mscreen
from scry_mame import series as mseries
from scry_mame import state as st
from scry_mame import sweep as msweep
from scry_mame import trace as mtrace
from scry_mame import write as mwrite
from scry_mame.state import STATE

Ops = dict[str, Callable[..., dict[str, Any]]]

SEQUENCES = frozenset({"perform", "drive"})
#: The tools that are no step of a sequence, named once; the other lists read off it.
NOT_STEPS = SEQUENCES | {"start", "close", "rom_check", "perform_export", "window"}

# Ops that may run on a RUNNING machine; any other waits for the next stop. The server's
# refusal names the same tools from here, because a second copy drifted.
RUNNING_OK_OPS = {"status", "cpu_info", "stop", "log", "log_wait", "snapshot",
                  "state_list", "captures", "breakpoint_at", "declaration_list",
                  "declaration_clear", "watch_add", "regpoint_add", "comment_list",
                  "comment_write", "symbols_find", "throttle",
                  "machine_map", "gfx_load", "palette_log", "gfx_film", "scan", "screen_map_write",
                  *media_tools.TOOLS}
#: The methods of a fold that answer on a running machine; its others need a stop.
RUNNING_METHODS: dict[str, tuple[str, ...]] = {
    "comment_write": ("save",), "scan": ("clear",), "screen_map_write": ("load", "save")}


#: A film's arming reads the screen, so it needs a stop.
GATE = roster.RunningGate(
    ops=frozenset(RUNNING_OK_OPS), methods=RUNNING_METHODS,
    needs_stop={"gfx_film": lambda a: mfilm.arms(str(a.get("trigger", "")),
                                                 bool(a.get("clear")))})


def answers_running(op: str, args: dict[str, Any]) -> bool:
    return GATE.answers(op, args)


STOP_POLL_S = 0.1


# Each entry is the operation's own `check_*`, the function the tool calls alone, so a batch
# refuses a step in the same words as the single call. `args.BY_TOOL` is built from this
# table: `preflight` skips an operation with no entry, and a skipped later step runs every step
# before it.
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
    "series_capture": mseries.check_series_capture,
    "lua": mlua.check_lua,
    "cpu_focus": mfocus.check_focus,
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
    **folds.CHECKS,
    "debug": mwrite.check_debug,
    "machine_map": machine.check_machine_map,
    **{name: spec.check for name, spec in media_tools.TOOLS.items()},
}

#: Operations with no machine-independent half, named so an absent entry above is a decision.
MACHINE_JUDGES = frozenset({
    "comment_list",
    "state_list", "captures", "stop", "status", "reset", "cpu_info",
    "screen_map_find",
})

def check_perform(settle_seconds: float = 30.0, summaries: bool = False, until_frame: int = 0,
                  **_: Any) -> None:
    """`perform`'s machine-independent half, less its steps (`refuse_steps`, which needs the
    server's operation table); `until_frame` comes with `summaries` because a window is hundreds
    of steps."""
    validate_settle(settle_seconds)
    account.check_summaries(summaries)
    frame_window.check_arguments(until_frame, summaries)


def check_until(steps: list[Any], until_frame: int) -> None:
    """A list run `until_frame` must advance the machine, and the frame must be ahead of it."""
    if not until_frame:
        return
    advance.refuse_frameless("until_frame")
    ses = STATE.ses
    frame_window.check_until(steps, until_frame, st.last_stop_frame(),
                             ses is not None and bool(ses.running))


def check_drive(act: Any = None, expect: str = "", seconds: float | None = None,
                pattern: str = ".", limit: int = 40, settle_seconds: float = 30.0,
                summaries: bool = False,
                **_: Any) -> tuple[re.Pattern[str], re.Pattern[str] | None]:
    """`drive`'s machine-independent half; returns the two regexes compiled (`expect`'s None
    when there is none). The act's operations are checked against the server's table in the tool."""
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
    """The bound a sequence waits for a stop to settle: zero means never wait."""
    vocab.check_wait(settle_seconds, name="settle_seconds", zero_means="never wait")


def preflight(steps: list[Any], ops: Ops) -> list[dict[str, Any]]:
    """Check every step's op, argument names and values before any runs, collecting every
    refusal (`step`, `op`, `code`, `message`): a bad third step must not follow a released first."""
    refused: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        op = sequence.step_op(step)
        if op is None or op not in ops:
            refused.append(sequence.not_a_step(i, step, "the step names no `op`"))
            continue
        refusal, args = step_judge.judge(ops[op], step)
        if refusal is not None:
            refused.append({"step": i, "op": op, **refusal})
            continue
        params = step_judge.signature_of(ops[op]).parameters
        check = BY_OP.get(op)
        try:
            args = inputs.numbers_read(ops[op], args)
            if check is not None:
                # Omitted arguments take the tool's defaults, not the check's.
                judged = step_judge.signature_of(check).parameters
                check(**{**{n: p.default for n, p in params.items()
                            if n in judged and p.default is not p.empty and n != "ctx"},
                         **args})
        except TypeError as e:
            # `judge` checks names only; a wrong-typed value raises here.
            refused.append({"step": i, "op": op, "code": "bad_argument",
                            "message": f"carries a value of the wrong type: {e}"})
            continue
        except st.Invalid as e:
            refused.append({"step": i, "op": op, "code": e.code, "message": str(e)})
    return refused


def _leaves_running(_op: str, reply: dict[str, Any]) -> bool:
    """Whether a step left the machine running, read from its own reply's `session` block.

    Not an enumeration of ops: a go-family command typed through `debug` releases the machine
    too. Safe to trust because only ops outside `RUNNING_OK_OPS` are asked, never a reader on a
    machine already moving."""
    session = reply.get("session")
    return isinstance(session, dict) and bool(session.get("running"))


def _something_can_stop_it() -> bool:
    """A stop breakpoint, a registerpoint or a change watch is armed; a control never halts."""
    return (any(rec["owner"] not in STATE.controls for rec in STATE.breakpoints.values())
            or bool(STATE.regpoints) or bool(STATE.armed_watches))


def _wait_for_stop(ses: Any, scratch: Path, seconds: float, progress: mprogress.Progress,
                   record: bool = True) -> sequence.Waited:
    """`stopped` | `running` | `gone`, asked until the bound (`running.came_to_rest`).

    A channel that fails is `gone` when MAME died; else it is answered as any tool's session
    error (`running.session_error_reply`) and the executor ends the list with it."""
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


#: The socket closes before the exit is seen, so a failed connection waits this long for it.
GONE_GRACE_S = 0.5


def _alive_after(error: gs.SessionError) -> bool:
    """Whether MAME still runs once a channel failed."""
    if not STATE.machine_alive() or not isinstance(error, gs.ConnectionFailed):
        return STATE.machine_alive()
    proc = STATE.proc
    assert proc is not None
    try:
        proc.wait(GONE_GRACE_S)
    except subprocess.TimeoutExpired:
        return True
    return False


#: `drive`'s look when the act was refused before anything ran.
NOTHING_LOOKED_WHY = "the act was refused before anything ran, so the log was not looked at"


def _account(ran: dict[str, Any]) -> dict[str, Any]:
    """The run's account as `drive` reports it: `run_steps`' reply minus the envelope."""
    return sequence.act_told(ran)


def refuse_act(act: list[Any], ops: Ops, pattern: str,
               ses: Any = None, shape: bool = True) -> dict[str, Any] | None:
    """`drive`'s refusal for an act refused before anything moved, or None when it is sound.
    With the session, the cpus and refs are judged too (`refuse_machine`); `shape` False when
    the caller already judged the act's shape."""
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
    """`drive`'s refusal before anything ran, in the one shape every `drive` reply has."""
    return menvelope.invalid(code, message,
                             act=act if act is not None else {"ran": [], "steps_completed": 0,
                                                              "failed": sequence.none_failed(),
                                                              "failed_at": sequence.none_failed()},
                             **named,
                             verify={"checked": False,
                                     "why": "the act was refused before anything ran"},
                             looked={"emulator": unavailable(NOTHING_LOOKED_WHY)})


def refuse_steps(steps: list[Any], ops: Ops) -> dict[str, Any] | None:
    """The whole list's refusal, or None when every step is sound.

    Needs no machine, so a cold server refuses as a warm one does. A reply rather than a raise
    because it carries every refused step, which makes one round of fixing enough.
    """
    if not steps:
        # `ok` over nothing examined is a green nobody earned.
        raise st.Invalid("bad_argument", "steps is a non-empty LIST of steps ({'op': <name>, "
                                         "...}): an empty one would run nothing")
    refused = preflight(steps, ops)
    if not refused:
        return None
    return _list_refused("bad_argument", refused, **sequence.vocabulary_named(refused, ops))


def refuse_machine(ses: Any, steps: list[Any]) -> dict[str, Any] | None:
    """The machine's halves of the preflight: the cpus, then the refs."""
    return refuse_cpus(ses, steps) or refuse_refs(ses, steps)


def refuse_cpus(ses: Any, steps: list[Any]) -> dict[str, Any] | None:
    """Every step's `cpu` judged against the machine's cpus before any step runs."""
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


#: Each operation's ref-like arguments the address rule (`inputs.classify`) reads before the
#: list runs. Not `gfx_blit_source`'s `pc` (only the rows say its cpu), nor a clear's or a
#: delete's `ref` (an earlier step may have declared it).
REF_ARGS: dict[str, tuple[str, ...]] = {
    "run_to": ("ref", "control"), "breakpoint_at": ("ref",), "watch_add": ("ref", "trigger"),
    "comment_write": ("ref",), "read_memory": ("ref",), "read_block": ("ref",),
    "disassemble": ("ref",), "find": ("ref",), "scan": ("ref",), "write": ("ref",),
    "memdump": ("ref",), "gfx_view": ("ref",), "gfx_locate": ("ref",), "gfx_sweep": ("ref",),
    "gfx_film": ("trigger", "pc"),
}
_REF_METHOD = {"comment_write": "add", "scan": "start"}
#: Operations after which the visible cpu may differ from the one the list began on; a step
#: naming no cpu past the first of them is judged when it runs.
MOVES_VISIBLE = frozenset({
    "cpu_focus", "step", "run_to", "run_for", "resume", "trace", "debug", "stop", "log_wait",
    "reset", "state_write", "lua", "input", "record", "audio_record", "screen_signature",
    "gfx_film", "series_capture"})
_DECLARES = {"breakpoint_at": "breakpoint", "watch_add": "watch", "comment_write": "comment"}


def _ref_args(step: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """The (argument, text, is a pointer's base) triples of `step` the address rule reads, as the
    tool will read them; never a port, an expression, or a `ref` that `by` already says."""
    op, io = step["op"], step.get("space", "program") != "program"
    out: list[tuple[str, str, bool]] = []
    if op in _REF_METHOD and step.get("method") != _REF_METHOD[op]:
        return out
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
    """The trigger names the capture on this step's block is held on (`arming.held_triggers`)."""
    block = step.get("ref")
    if not isinstance(block, str):
        return []
    by = step.get("by", "auto")
    if by == "auto":
        by = ("pointer" if vf.parse_pointer(block) is not None
              else "address" if inputs.is_address(block) else "symbol")
    return arming.held_triggers(on, block, by)


def refuse_refs(ses: Any, steps: list[Any]) -> dict[str, Any] | None:
    """The address rule's half of the preflight: every ref read against its table before any
    step runs, wherever that table is known now (the step names its cpu, or precedes the first
    step that can move the visible cpu). Bare hex naming no symbol refuses the LIST. Names
    count if held before the list or declared `by="symbol"` by an earlier step on the same cpu
    (on any, where that step's cpu is unknown); a capture's trigger also reads `_held_triggers`."""
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
    `failed`."""
    return menvelope.invalid(code, sequence.refused_text(refused),
                             ran=[], steps_completed=0, failed_at=refused[0]["step"],
                             failed=refused[0],
                             errors=refused, **named)


def _entry(op: str, reply: dict[str, Any]) -> dict[str, Any]:
    """One step in the account: its op, the cpu its reply names, and its reply."""
    return {"op": op, **({"cpu": reply["cpu"]} if isinstance(reply.get("cpu"), str) else {}),
            "reply": reply}


def _stop_extra(reply: dict[str, Any], cut: dict[str, Any]) -> None:
    """What a stop's compact row keeps beyond its keys: `watch_hit` less its lists, and
    `regpoint_hit`."""
    if isinstance(hit := reply.get("watch_hit"), dict):
        cut["watch_hit"] = {k: v for k, v in hit.items() if not isinstance(v, list)}
    if "regpoint_hit" in reply:
        cut["regpoint_hit"] = reply["regpoint_hit"]


#: This server's half of the account (`scry_core.sequence_account`): a stop's compact row is the
#: stop without its lists, counted by `cause` with the writer taken off (one watch, one key).
SHAPE = account.Shape(kept=("cause", "pc", "frame", "stop_seq"),
                      cause_key=lambda stop: watches.cause_key(str(stop.get("cause"))),
                      extra=_stop_extra)


def account_of(ran: list[dict[str, Any]], summaries: bool, keep_last: bool, scratch: Path,
               since: int, also: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`ran` as the reply carries it (`scry_core.sequence_account.account`); the kept step is
    the last of a completed list, or the one that left the machine running; a failed step stays
    whole under `failed`. The files go to the scratch, numbered per call."""
    return account.account(ran, summaries, keep_last, since,
                           int(STATE.last_stop.get("seq", 0)), SHAPE,
                           lambda: scratch / f"batch-{STATE.next_number('batches')}", also,
                           rows_shown=st.ROWS_SHOWN)


#: A reply's fields that are not the stop's.
_ENVELOPE = frozenset({"summary", "status", "session", "stopped_on_its_own", "applied_on_stop"})


class _Mame(sequence.SequenceMachine):
    """This server's half of a list (`scry_core.sequence`)."""

    stoppers = "A breakpoint, a registerpoint or a watch"
    undeclared = "no stop breakpoint, no registerpoint, no change watch: a control never halts"

    def __init__(self, ses: Any, scratch: Path, summaries: bool) -> None:
        self.ses, self.scratch, self.summaries = ses, scratch, summaries
        self.since = int(STATE.last_stop.get("seq", 0))
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
        """A step's own wait ran out (a `log_wait` TIMEOUT): later steps were built on it."""
        return op == "log_wait" and reply.get("verdict") == contract.TIMEOUT

    def rested(self, ran: list[dict[str, Any]]) -> dict[str, Any] | None:
        """The stop that came during the last step is the one the run was heading for.

        One the step surveyed itself is named as its reply carried it, never surveyed twice (a
        second survey renumbers it and reads the log past its cause); any other is surveyed now."""
        last = ran[-1]["reply"] if ran else {}
        if isinstance(last.get("stop_seq"), int):
            return {k: v for k, v in last.items() if k not in _ENVELOPE}
        found = last.get("stopped_on_its_own")
        if isinstance(found, dict) and isinstance(found.get("stop_seq"), int):
            return dict(found)
        return self.tail_stop()

    def noted(self, op: str, reply: dict[str, Any]) -> None:
        shown = reply.get("cpu") if op == "cpu_focus" else (
            reply.get("visible_cpu") if op == "debug" else None)
        # An unread visible cpu leaves the last one asked.
        self.asked = shown if isinstance(shown, str) else self.asked


def run_steps(ses: Any, scratch: Any, steps: list[Any], settle_seconds: float, ops: Ops,
              progress: mprogress.Progress = mprogress.no_progress, tail_wait: bool = True,
              summaries: bool = False, until_frame: int = 0,
              name: str = "perform", shape_judged: bool = False,
              machine_judged: bool = False) -> dict[str, Any]:
    """Execute steps in order (`scry_core.sequence.run`), stopping at the first failure with a
    full account (`ran`, `failed_at`, `failed`, `steps_completed`, the tail, `verdict`).

    On several cpus the reply adds `visible_cpu` and `visible_cpu_kept` (`_keep_visible`); with
    `until_frame` the list repeats (`frame_window.Window`). `shape_judged` and `machine_judged`
    say the caller already judged the list, so each judge runs once a call."""
    refusal = ((None if shape_judged else refuse_steps(steps, ops))
               or (None if machine_judged else refuse_machine(ses, steps)))
    if refusal is not None:
        return refusal
    several = len(cpus.cpu_list(ses)) > 1
    was = cpus.visible_cpu(ses) if several and not ses.running else None
    machine = _Mame(ses, scratch, summaries)
    window = (frame_window.Window(until_frame, st.last_stop_frame(), bool(ses.running),
                                  progress) if until_frame else None)
    ended = sequence.run(machine, steps, ops, settle_seconds, progress, name, tail_wait, window)
    fields = {**ended.fields, "held": ended.held}
    if several:
        # `visible_cpu` is the tag in every reply; how the list kept it is its own account.
        kept = _keep_visible(ses, was, machine.asked)
        fields["visible_cpu"], fields["visible_cpu_kept"] = kept["after"], kept
    # After the cpu is put back: the send is a poll, and a cancel there would skip the put-back.
    if window is not None:
        window.last_line()
    return (menvelope.invalid(ended.code, ended.message, **fields) if ended.code
            else menvelope.envelope(fields))


# A stop moves the visible cpu as MAME does; the list puts back the one it keeps (the one it
# found, or the last `cpu_focus` read back) with the stub's `Hc`, which runs nothing.
def _keep_visible(ses: Any, was: str | None, asked: str | None) -> dict[str, Any]:
    """`_kept_visible`'s account with each cpu it could not name said, never a null."""
    kept = _kept_visible(ses, was, asked)
    if kept["before"] is None:
        kept["before"] = unavailable("the list began with the machine running, or `cpulist` "
                                        "marked no cpu visible")
    if kept["after"] is None:
        kept["after"] = unavailable(str(kept.get("why") or "no cpu was read visible"))
    return kept


def _kept_visible(ses: Any, was: str | None, asked: str | None) -> dict[str, Any]:
    """The reply's `visible_cpu_kept`: `before`, `asked`, `after`, whether `restored`, `moved_to`
    for the cpu a stop left visible, and `why` when a put-back was due and not made."""
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
        # The list ran and its account is the reply: a failed put-back is said, not raised.
        return {**said, "after": now, "restored": False, "why": str(e)}
    after = cpus.visible_cpu(ses)
    if after != kept:
        return {**said, "moved_to": now, "after": after, "restored": False,
                "why": f"`Hc` was taken and `cpulist` read back {after}, not {kept}"}
    return {**said, "moved_to": now, "after": after, "restored": True}


DRIVE_EXPECT_WAIT_S = 5.0
DRIVE_POLL_S = 0.1


def _look(scratch: Path, mark: int, rx: re.Pattern[str], limit: int) -> dict[str, Any]:
    """The emulator log's lines since the mark (`account.looked`)."""
    return account.looked("emulator", files.errorlog_since(scratch, mark)[0], mark, rx, limit)


def _verify(ses: Any, scratch: Path, pat: re.Pattern[str], wait_s: float, mark: int,
            progress: mprogress.Progress) -> dict[str, Any]:
    """A line matching `pat` since the mark: waited for up to `wait_s` on a running machine
    (a stop ends the wait, as a stopped machine logs nothing), read once on a stopped one."""
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
            continue
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
    # The act's vocabulary is `preflight`'s; its shape was judged by the server before.
    refusal = refuse_act(act, ops, pattern, ses, shape=False)
    if refusal is not None:
        return refusal
    _lines, mark = files.errorlog_since(scratch, 0)
    # With an `expect` the verify is the wait; the tail's settle wait would run out before it.
    ran = run_steps(ses, scratch, act, settle_seconds, ops, progress, name="drive",
                    tail_wait=not expect, summaries=summaries, shape_judged=True,
                    machine_judged=True)
    told = _account(ran)
    if ran.get("status") != "ok":
        # The code is the step's: a broken session stays `session_broken`.
        act_code, said = sequence.act_stopped(ran)
        return menvelope.invalid(act_code, said, act=told,
                                 looked=_look(scratch, mark, pattern_rx, limit))
    checked: dict[str, Any] = dict(sequence.NO_EXPECT)
    if ran.get("verdict") == contract.TIMEOUT:
        # The act did not do what it was asked, so nothing it did is checked.
        checked = sequence.act_ran_out()
    elif expect_rx is not None:
        checked = _verify(ses, scratch, expect_rx, wait_s, mark, progress)
        # The verify consumed the stub's packet; left unsurveyed, the stop would ride on the
        # next call's reply.
        running.observe_stop(ses, scratch)
        if checked.pop("stopped", False):
            # `log_wait`'s refusal: a stopped machine logs nothing.
            return menvelope.invalid("wait_stopped",
                                     f"the act ran but the machine did not do what was expected: "
                                     f"{checked['why']}; `resume` lets it run, then `drive` "
                                     "again",
                                     act=told, verify=checked,
                                     looked=_look(scratch, mark, pattern_rx, limit))
    return menvelope.envelope({"act": told, "verify": checked,
                               "looked": _look(scratch, mark, pattern_rx, limit)})
