"""THE MCP BOUNDARY of the MAME server: the protocol's server object and its `instructions`, the
one lock over the one machine, and this server's part of the call boundary every Scry server shares
(`scry_core.boundary`): how a body is called and which errors are answers, how a cancelled call
ends, the `session` block and the summaries. `server.py` holds the tools.

THE SCHEMA'S REFUSAL AND THE PICTURE are `scry_core.envelope`'s, the same on every Scry server;
this server's part is `refusal`, the reply a refused call gets under its lock.
"""

from __future__ import annotations

import inspect
import threading
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from scry_core import boundary, cancel, envelope, media_tools, recording
from scry_core import strict_arguments as strict

import gdb_session as gs
import mame_args as args
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
        # `start` promises `start_retries` on every reply, and this one launched nothing.
        launched: dict[str, Any] = {"start_retries": []} if name == "start" else {}
        reply = menvelope.invalid("bad_argument", strict.schema_refusal(cause), **launched)
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
_ANSWERS_WHILE_RUNNING = [*sorted(sequence.RUNNING_OK_OPS - set(media_tools.TOOLS)),
                          "registers(from_last_stop=True)", "perform", "drive", "perform_export",
                          "close"]

mcp = envelope.Envelope(
    "mame",
    instructions=(
        "A live MAME debug session.\n\n"
        "TOOLS. `start`, `rom_check`, `focus`. "
        "Advance: `run_to`, `run_for`, `step`, `resume`, `trace`, `series_capture`. Read: "
        "`read_memory`, `read_block`, `registers`, `disassemble`, `find`, `history`, "
        "`palette`, `screen_view`, `gfx_view`, `gfx_locate`, "
        "`gfx_sweep`, `gfx_draft`, `gfx_blits`, `gfx_blit_source`, `screen_signature`, "
        "`scan_start`, `scan_filter`. Write: `write`, `set_register`, `reset`, `debug`, "
        "`comment_add`, `comment_delete`, `comment_load`. Lua: `input`, `record`, "
        "`audio_record`, "
        "`state_save`, `state_load`, `lua`. "
        "Files, any state: `image_diff`, `series_diff`, "
        "`region_track`, `golden_check`, `audio_measure`, `audio_diff`.\n\n"
        "A SESSION. `start` parks the machine STOPPED. "
        "`run_to`'s target has no stop of its own. "
        "`resume` lets it RUN. While it runs the readers refuse (`not_stopped`); these "
        "answer: " + ", ".join(f"`{name}`" for name in _ANSWERS_WHILE_RUNNING) + ". "
        "`rom_check`: 16 bytes at `reference_addr` vs `reference_rom` at `reference_base`. "
        "`memdump`, `snapshot` answer with a PATH. A cancel ends a call as its bound would; "
        "the next reply says `cancelled`.\n\n"
        "CPUS: no `cpu` acts on the VISIBLE one (stops move it), lists or clears all; named, moves "
        "only `step`'s.\n\n"
        "ADDRESSES are `0x`, a condition as typed; any other ref is a symbol, bare hex "
        "naming none refused. Breakpoints are PLACES, never expressions.\n\n"
        "EVERY REPLY carries `summary`, `status` (`ok`, or `INVALID` with `code` and "
        "`message`) and `session` (`altered` after a write). A "
        "wrong TYPE is the schema's `bad_argument`. `not_settled`: "
        "`stop`, and if `stop` fails as well, `close` then `start`. "
        "`session_broken` LATCHES until `close`.\n\n"
        "Reference: REFERENCE.md."
    ),
    refusal=refusal,
)

# ONE LOCK FOR ONE MACHINE. The server keeps ONE session in a global and the transport can hand
# over two calls at once. Without it, two overlapping `run_to` calls trample each other's
# breakpoints and steal each other's stops: the first collects the second's stop and returns a
# verdict about a PC that is not its own. A debugger that reports the wrong stop is worse than a
# slow one, so the tools serialize. Full stop.
LOCK = threading.RLock()


def _summary(name: str, args: dict[str, Any], reply: dict[str, Any]) -> str:
    """The one line the MCP client shows for a call (`mame_summaries`): the envelope's for a
    refusal, the tool's own otherwise."""
    if reply.get("status") == "INVALID":
        return summaries.refusal(name, reply)
    return _SUMMARIES[name](args, reply)


#: Each registered tool's summary, filled by `tool` as it registers them.
_SUMMARIES: dict[str, summaries.Summary] = {}
#: Each registered tool's own body, unwrapped, which the probe's judge reads arguments against.
_BODIES: dict[str, Callable[..., Any]] = {}


def probe_check(tool: str, given: dict[str, Any], effective: dict[str, Any]) -> None:
    """This server's pre-gate judge in the shape `scry_core.probe.Check` takes: each tool body
    calls `args.check` with its own values, defaults included, every number read first as the
    `tool()` wrapper reads it (`numbers_read`), so the probe judges a call the way the tool
    would. `given` is not used: the bodies judge what they run with."""
    args.check(tool, **inputs.numbers_read(_BODIES[tool], effective))


def _end_cancelled(name: str, on_cancel: cancel.OnCancel) -> tuple[cancel.Left, object]:
    """THE END A CANCELLED CALL DECLARED, applied at once: the end its own bound would have given
    it, under the shield so that end's own waits run to completion. `stop` for a tool that comes
    back STOPPED (the `stop` tool's own path: a machine already stopped is left so), `kill` for
    one whose failure path ends the emulator, `none` for one that leaves the machine as it was.
    Returned: what it left, and the account of a stop the machine reached on its own that this
    call found (or its end did), which its reply would have said, kept past the end of the call
    by `_after`."""
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
    return left, dict(STATE.found_stop_last)


def _invoke(fn: Callable[..., Any], signature: inspect.Signature, a: tuple[Any, ...],
            k: dict[str, Any]) -> dict[str, Any]:
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
        called = signature.bind_partial(*a, **k)
        for name, value in called.arguments.items():
            ann = signature.parameters[name].annotation
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


def _after(found: object) -> None:
    """After every call, a step of a sequence included, whichever way it ended: the one-time
    account it rode on goes with it (`State.end_call`). A cancelled call had no reply, so the
    account of a stop it found (`_end_cancelled`'s return) waits for the next; and THE IDLE
    CLOCK RESTARTS WHEN A CALL ENDS (`mame_idle`)."""
    STATE.end_call()
    if isinstance(found, dict) and found:
        STATE.found_stop_last = found
    idle.IDLE.touch()


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
RECORDER = recording.Recorder("mame", _machine, stop_fields=("pc", "frame"),
                              outside=frozenset({"close", "rom_check"}))

BOUNDARY = boundary.Boundary(
    mcp, LOCK, invoke=_invoke, end=_end_cancelled, after=_after, line=_summary,
    session_block=menvelope.session_block, take_cancelled=STATE.take_cancelled,
    keep_cancelled=_keep_cancelled, doc=docs.filled, recorder=RECORDER)


def tool(
    title: str, *, summary: summaries.Summary, read_only: bool = False, idempotent: bool = False,
    session_before: bool = False, on_cancel: cancel.OnCancel | None = None,
    replay: recording.ExportAs | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Registers an MCP tool, SERIALIZES it over the one machine (see `LOCK`), and puts the
    one-line `summary` first in its reply: `summary` is the tool's own line
    (`mame_summaries`), REQUIRED, so a tool registered without one fails at import.

    `title` is what the client shows for the tool, and `read_only` becomes the protocol's
    `readOnlyHint`: a reader declares it so a client may run readers in parallel, which is
    honest here because every tool takes the lock anyway. Anything that advances the machine,
    writes to it, or writes a FILE (`memdump`, `snapshot`) is not read-only.

    `idempotent` becomes `idempotentHint`, and it is a STRONGER claim than read-only: calling
    it again changes nothing AND answers the same. Almost nothing here can say that, because
    almost everything reads a machine that moves; what can is a tool serving a cache built
    once at `start`. Declared wrongly it would invite a client to repeat a call whose answer
    had moved underneath it, so it stays false unless the tool's own data cannot change.

    `session_before` keeps the `session` block the body built (`close`'s, the state BEFORE the
    kill, so that `altered` is the truth about the session it ended). `on_cancel` is how the
    tool ends when the client cancels its call (`_end_cancelled`); the rest of the contract,
    the `ctx` rule included, is `scry_core.boundary.Boundary.tool`'s, and which errors become
    replies is `_invoke`'s. `replay` is what its calls become in an exported session
    (`scry_core.replay`; REFERENCE.md, From an investigation to a bench).
    """

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        wrapped = BOUNDARY.tool(title, read_only=read_only, idempotent=idempotent,
                                session_before=session_before, on_cancel=on_cancel,
                                replay=replay)(fn)
        _SUMMARIES[fn.__name__] = summary
        _BODIES[fn.__name__] = fn
        return wrapped

    return register
