"""THE MCP BOUNDARY of the MAME server: the protocol's server object and its `instructions`, the
one lock over the one machine, and this server's part of the call boundary every Scry server shares
(`scry_core.boundary`): how a body is called and which errors are answers, how a cancelled call
ends, the `session` block and the summaries. `server.py` holds the tools.

THE SCHEMA'S REFUSAL AND THE PICTURE are `scry_core.envelope`'s, the same on every Scry server;
this server's part is `refusal`, the reply a refused call gets under its lock.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from scry_core import boundary, cancel, envelope, media_tools, presence, recording, roster
from scry_core import strict_arguments as strict

import gdb_session as gs
import mame_args as args
import mame_arming as arming
import mame_declarations as dec
import mame_docs as docs
import mame_envelope as menvelope
import mame_idle as idle
import mame_inputs as inputs
import mame_running as running
import mame_sequence as sequence
import mame_state as st
import mame_summaries as summaries
from mame_state import STATE


def refusal(name: str, arguments: dict[str, Any], cause: ValidationError) -> dict[str, Any]:
    """The refusal's reply, built over the ONE machine like every other reply.

    It is built under the lock (`BOUNDARY.refused`) because it WRITES, ending the call
    (`State.end_call`) and with it the one-time account of a stop the machine reached on its
    own: unlocked, a refused call could take that account away from the call building the
    reply meant to carry it. No tool in this package dispatches through `call_tool`, so
    nothing on this path already holds the lock.
    """
    def build() -> dict[str, Any]:
        reply = menvelope.invalid("bad_argument", strict.schema_refusal(cause))
        STATE.end_call()
        return reply

    return BOUNDARY.refused(name, arguments, build)


# The name it REPORTS must be the name it is INSTALLED as (`claude mcp add mame`), which is also
# what namespaces its tools as `mcp__mame__*`: a name that is not the registration is the name of
# nothing, harmless while private and confusing the day somebody else installs it. THE
# `instructions` ARE THE SERVER'S OWN, the channel an MCP client documents for this and the one a
# session receives without asking: what the protocol delivers cannot come out short or carry a
# truncated name, as a copy pasted by hand can.
# What answers while the machine RUNS, named in every refusal so the caller can decide
# without provoking a stop, and in the `instructions` below from the same list: the batch's
# own running-ok operations, the last stop's registers, the two batch tools (which wait for a
# stop before a step that needs one) and `close`. The list is the server's because it names
# tools.
# The media file tools answer in any state too, and the instructions say so once, beside them.
# A fold answers by some of its methods only, and is named with them.
_ANSWERS_WHILE_RUNNING = roster.answers_while_running(
    roster.by_method(sequence.RUNNING_OK_OPS - set(media_tools.TOOLS), sequence.RUNNING_METHODS),
    sequence.NOT_STEPS, {"start", "rom_check"})

#: THE TOOLS BY FAMILY, in the order the instructions list them (`scry_core.roster`): the
#: roster and the "answers while it runs" sentence are both rendered from it, so a family that
#: answers whole is named once instead of tool by tool. The media file tools answer in any
#: state, so their family answers whole.
ROSTER = roster.Roster(families=(
    ("Session", ("start", "status", "close", "focus", "rom_check")),
    ("Machine", ("cpu_info", "machine_map", "symbols_find", "log", "log_wait")),
    ("Advance", ("run_to", "run_for", "step", "resume", "stop", "trace", "series_capture")),
    ("Declarations", ("breakpoint_at", "regpoint_add", "watch_add", "declaration_list",
                      "declaration_clear")),
    ("Read", ("read_memory", "read_block", "registers", "disassemble", "find", "history",
              "memdump", "map_find", "map_write")),
    ("Screen", ("palette", "screen_view", "screen_signature", "gfx_view", "gfx_locate",
                  "gfx_sweep", "gfx_draft", "gfx_blits", "gfx_blit_source")),
    ("Film", ("gfx_load", "gfx_film", "palette_log")),
    ("Scan", ("scan",)),
    ("Write", ("write", "set_register", "reset", "debug")),
    ("Comments", ("comment_list", "comment_write")),
    ("Lua", ("input", "record", "audio_record", "lua", "throttle")),
    ("States", ("state_list", "state_write")),
    ("Files", (*media_tools.TOOLS, "snapshot", "captures")),
    ("Lists", ("perform", "drive", "perform_export")),
), answering=(*_ANSWERS_WHILE_RUNNING, *media_tools.TOOLS))

mcp = envelope.Envelope(
    "mame",
    instructions=(
        "A live MAME debug session.\n\n"
        "TOOLS. " + ROSTER.text() + "\n\n"
        "A SESSION. `start` parks it STOPPED. "
        "`run_to`'s target has no stop of its own. "
        "`resume` RUNs it; readers then refuse (`not_stopped`); "
        + ROSTER.running_sentence() + " "
        "`rom_check`: 16 bytes at `reference_addr` vs `reference_rom` at `reference_base`. "
        "`memdump`, `snapshot` answer with a PATH. A cancelled call ends as at its bound; "
        "the next reply says `cancelled`.\n\n"
        "CPUS: no `cpu` acts on the VISIBLE one, lists or clears all.\n\n"
        "ADDRESSES are `0x`, a condition as typed; any other ref is a symbol, bare hex "
        "naming none refused. Breakpoints are PLACES, never expressions.\n\n"
        "EVERY REPLY carries `summary`, `status` (`ok`, or `INVALID` with `code` and "
        "`message`) and `session` (`altered` after a write); a diagnostic left out is empty, "
        "and `omitted` names what was not sent. A wrong TYPE is the schema's `bad_argument`. "
        "`not_settled`: `stop`; if `stop` fails as well, `close` then `start`. "
        "`session_broken` LATCHES until `close`."
    ),
    refusal=refusal,
)



def probe_check(tool: str, given: dict[str, Any], effective: dict[str, Any]) -> None:
    """This server's pre-gate judge in the shape `scry_core.probe.Check` takes: each tool body
    calls `args.check` with its own values, defaults included, every number read first as the
    `tool()` wrapper reads it (`numbers_read`), so the probe judges a call the way the tool
    would. `given` is not used: the bodies judge what they run with."""
    args.check(tool, **inputs.numbers_read(BOUNDARY.bodies[tool], effective))


def _end_cancelled(name: str, on_cancel: cancel.OnCancel
                   ) -> tuple[cancel.Left, dict[str, Any] | None]:
    """THE END A CANCELLED CALL DECLARED, applied at once: the end its own bound would have given
    it, under the shield so that end's own waits run to completion. `stop` for a tool that comes
    back STOPPED (the `stop` tool's own path: a machine already stopped is left so), `kill` for
    one whose failure path ends the emulator, `none` for one that leaves the machine as it was.
    Returned: what it left, and the account of a stop the machine reached on its own that this
    call found (or its end did), in the reply's own words, which its reply would have said and
    the next one says instead (`_keep_accounts`)."""
    left: cancel.Left | None = None
    with cancel.shielded():
        try:
            # A stop the call made on its way (an interrupt in a `finally`, a step a Lua read
            # bought) is its own, recorded as a refused call's is, never found later as one the
            # machine reached by itself.
            running.record_own_stop(name, "the stop it made when its call was cancelled")
            if on_cancel == "kill" and (STATE.ses is not None or STATE.proc is not None):
                # With its grace when a session can be asked to quit (`cfg/` and `nvram/` are
                # written); a MAME still booting has nobody to ask, so waiting for it holds time.
                STATE.kill(grace=STATE.ses is not None)
            elif (on_cancel == "stop" and STATE.ses is not None and STATE.ses.running
                    and running.stop(*running.contact()).get("status") != "ok"):
                left = "unknown"
        except (gs.SessionError, st.Invalid):
            left = "unknown"
    if left is None:
        ses = STATE.ses
        left = ("closed" if ses is None or not STATE.machine_alive()
                else "running" if ses.running else "stopped")
    found = dict(STATE.found_stop_last)
    return left, {"stopped_on_its_own": found} if found else None


def _invoke(fn: Callable[..., Any], called: inspect.BoundArguments) -> dict[str, Any]:
    """The body called the way this server reads its arguments, and THREE kinds of exception
    translated into replies and no more: `NotStopped`, into the INVALID reply that names the
    last stop and the tools that answer while the machine runs; every other `SessionError`,
    through `running.session_error_reply`, which says which of them are an answer and which
    LATCH the session; and `Invalid`, the tools' own refusals, answered as `session_broken`
    when the call itself latched the session. Widening that to `Exception` would turn every
    genuine bug into "I examined nothing"."""
    latched_before = STATE.broken
    try:
        # A COUNT IS AN INT TO EVERY BODY: an integral float a direct call or a `perform` step
        # carried is made the int it equals (`integral_counts`). AND A NUMBER IS AN INT TOO:
        # every argument the tool declares `NumberArg`, and each item of a `NumberList`, is read
        # here, as `perform` reads a step's, before the body judges it (`inputs.as_read` tells
        # mypy so).
        for name, value in called.arguments.items():
            ann = called.signature.parameters[name].annotation
            if isinstance(ann, str):
                called.arguments[name] = inputs.integral_counts(value, ann)
        called.arguments.update(inputs.numbers_read(fn, dict(called.arguments)))
        reply: dict[str, Any] = fn(*called.args, **called.kwargs)
        return reply
    except gs.NotStopped as e:
        # THE GUEST RUNS AND THIS READER CANNOT ANSWER: say where the machine was last seen and
        # which tools do answer now, so the caller can decide without provoking a stop (the
        # running-guest contract).
        return menvelope.invalid("not_stopped", str(e), last_stop=STATE.as_of(),
                                 answers_while_running=_ANSWERS_WHILE_RUNNING)
    except gs.SessionError as e:
        # Every session error but `NotStopped`, answered here, where every tool passes, so no
        # path a tool left unguarded escapes as an execution failure.
        return running.session_error_reply(e, fn.__name__)
    except st.Invalid as e:
        # Past the two above, ONLY `Invalid` is translated: a bug (an AttributeError, a broken
        # regex, a session error) escapes as an execution failure, never as "I examined
        # nothing" wearing a verdict. A stop the call made before it refused is recorded as its
        # own first (`record_own_stop`). A refusal a tool built out of a request that LATCHED on
        # this call names the wrong cause (an argument, an answer), so the latch answers instead.
        latched = STATE.ses
        reason = latched.broken if latched is not None else None
        if latched is not None and reason and not latched_before:
            return running.session_broke(
                latched, gs.SessionError(reason), f"under `{fn.__name__}`",
                "Nothing this call read is handed back")
        running.record_own_stop(fn.__name__)
        return menvelope.envelope(e.reply())


def _after() -> None:
    """After every call, a step of a sequence included, whichever way it ended: the one-time
    account it rode on goes with it (`State.end_call`); and THE IDLE CLOCK RESTARTS WHEN A CALL
    ENDS (`mame_idle`)."""
    STATE.end_call()
    idle.IDLE.touch()


def _keep_accounts(reply: dict[str, Any]) -> None:
    """THE ACCOUNT A REPLY NOBODY READS CARRIED GOES BACK for the next one: a stop the machine
    reached on its own, found by a call cancelled as it returned, by a step of a cancelled
    sequence, or by a cancelled call's end."""
    if reply.get("stopped_on_its_own"):
        STATE.found_stop_last = dict(reply["stopped_on_its_own"])


def _keep_cancelled(record: cancel.Cancelled) -> None:
    STATE.cancelled = record


def _machine() -> recording.Machine:
    """The machine around a recorded call: whether it runs, and the last stop's number and place
    as an advance's reply spells them (`pc`, `frame`), which is how the export tells a call that
    moved the machine."""
    ses = STATE.ses
    stop = STATE.last_stop
    moving = ses is not None and bool(ses.running)
    if moving or not stop:
        return recording.Machine(running=moving, seq=stop.get("seq"))
    return recording.Machine(running=False, seq=stop.get("seq"),
                             stop={"pc": stop["pc"], "frame": st.frame_shown(stop["frame"])})


#: The session's recording: what `perform_export` writes (REFERENCE.md, From an investigation to
#: a bench). `rom_check` answers about the files, never the machine, and is no step of a list.
# `live` is what `start` refuses over (`mame_launch`): a start refused there touched nothing.
#: Each kind of declaration a `start` re-arms, by the tool that lists it and the field its rows
#: are under.
_LISTS = {kind: ("declaration_list", key) for kind, key in dec.COUNT_KEYS.items()}


RECORDER = recording.Recorder("mame", "server.py", sequence.UNTIL_STEPS_MAX, _machine,
                              lambda: STATE.ses is not None and STATE.machine_alive(),
                              declarations=lambda: arming.store().declarations(),
                              kinds=_LISTS,
                              stop_fields=("pc", "frame"),
                              outside=sequence.NOT_STEPS - sequence.SEQUENCES - {"start"},
                              sequences=sequence.SEQUENCES, start_tool="start",
                              states=recording.States("state_write", "save", "load", "name"))

# THE HOOKS ARE BOUND HERE, ONCE, AT IMPORT: a test that replaces one patches the name the hook
# calls through (`STATE`, `running`), never the hook itself, which the boundary already holds.
BOUNDARY = boundary.Boundary(
    mcp, st.LOCK, invoke=_invoke, end=_end_cancelled, after=_after,
    refusal_line=summaries.refusal, session_block=menvelope.session_block,
    take_cancelled=STATE.take_cancelled, keep_cancelled=_keep_cancelled, doc=docs.filled,
    give_back=_keep_accounts, recorder=RECORDER,
    # PRESENCE hears every outermost call, so the window lights while one drives the machine.
    listener=presence.Slot(lambda: STATE.presence.held))


def tool(
    title: str, *, summary: summaries.Summary, read_only: bool = False, idempotent: bool = False,
    session_before: bool = False, on_cancel: cancel.OnCancel | None = None,
    replay: recording.Replay | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Registers an MCP tool on this server's boundary (`scry_core.boundary.Boundary.tool`, the
    contract), serialised over the one machine (`mame_state.LOCK`, kept beside the session it
    guards), `summary` its line in `mame_summaries`; `on_cancel` ends at `_end_cancelled`, and which
    errors become replies is `_invoke`'s. What can be idempotent here is a tool serving a cache
    built once at `start`.
    """

    return BOUNDARY.tool(title, summary=summary, read_only=read_only, idempotent=idempotent,
                         session_before=session_before, on_cancel=on_cancel, replay=replay)
