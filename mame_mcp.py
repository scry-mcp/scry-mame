"""THE MCP BOUNDARY of the MAME server: the protocol's server object and its `instructions`, the
one lock over the one machine, the reply every tool closes with, the decorator that registers a
tool, and the progress line of a bounded wait. `server.py` holds the tools; what a tool is
wrapped in, which is the same for every one of them, is here.

THE SCHEMA'S REFUSAL AND THE PICTURE are `scry_core.envelope`'s, the same on every Scry server;
this server's part is `refusal`, the reply a refused call gets under its lock.
"""

from __future__ import annotations

import functools
import inspect
import threading
from collections.abc import Callable
from typing import Any

import anyio.from_thread
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from pydantic import ValidationError
from scry_core import envelope, media_tools
from scry_core import strict_arguments as strict

import gdb_session as gs
import mame_args as args
import mame_docs as docs
import mame_envelope as menvelope
import mame_idle as idle
import mame_inputs as inputs
import mame_progress as mprogress
import mame_running as running
import mame_sequence as sequence
import mame_state as st
import mame_summaries as summaries
from mame_state import STATE


def refusal(name: str, arguments: dict[str, Any], cause: ValidationError) -> dict[str, Any]:
    """The refusal's reply, built over the ONE machine like every other reply.

    THE SEAM SITS OUTSIDE `tool()`'s WRAPPER and so outside the `LOCK` that wrapper
    holds, which would be a torn read of the state group `envelope()` gathers. It is
    worse than that: this path WRITES, ending the call (`State.end_call`), the one-time
    account of a stop the machine reached on its own. Unlocked, a call the schema refused
    could take that account away from the call that was building the reply meant to carry
    it, and the stop would be reported to nobody.

    NOTHING ON THIS PATH CAN ALREADY HOLD THE LOCK, established by reading rather than
    relied on: the schema refuses BEFORE the tool body runs, so this call never reached
    the wrapper that takes it, and no tool in this package dispatches through
    `call_tool`. `LOCK` being an `RLock` is not what makes this safe.
    """
    with LOCK:
        # `start` promises `start_retries` on every reply, and this one launched nothing.
        launched: dict[str, Any] = {"start_retries": []} if name == "start" else {}
        reply = menvelope.invalid("bad_argument", strict.schema_refusal(cause), **launched)
        STATE.end_call()
        body = _finished(name, arguments, reply)
    return body


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
                          "registers(from_last_stop=True)", "perform", "drive", "close"]

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
        "`run_to`, `run_for`, `step` stop it again with a survey; `run_to`'s target has no "
        "stop of its own. "
        "`resume` lets it RUN. While it runs the readers refuse (`not_stopped`); these "
        "answer: " + ", ".join(f"`{name}`" for name in _ANSWERS_WHILE_RUNNING) + ". "
        "`rom_check`: 16 bytes at `reference_addr` vs `reference_rom` at `reference_base`. "
        "`memdump`, `snapshot` answer with a PATH.\n\n"
        "CPUS: no `cpu` acts on the VISIBLE one (stops move it), lists or clears all; named, moves "
        "only `step`'s.\n\n"
        "ADDRESSES are written `0x`, a condition as typed; any other ref is a symbol, bare hex "
        "naming none refused. Breakpoints are at PLACES, never expressions.\n\n"
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


def _finished(name: str, args: dict[str, Any], reply: dict[str, Any],
              session_before: bool = False) -> dict[str, Any]:
    """The reply a caller reads, closed in ONE place for every path (the decorator's and the
    schema's refusal): `summary` first, the tool's own fields, `session` last.

    THE `session` BLOCK IS COMPOSED HERE, AFTER THE BODY, from the state the server holds: a
    body that released the machine or latched the session once its envelope was built would
    otherwise hand back a block describing the machine before it did. A tool registered with
    `session_before` keeps the block its body built: `close`'s, the state BEFORE the close."""
    body = {k: v for k, v in reply.items() if k != "session"}
    kept = reply.get("session") if session_before else None
    session = kept if kept is not None else menvelope.session_block()
    return {"summary": _summary(name, args, reply), **body, "session": session}


def probe_check(tool: str, given: dict[str, Any], effective: dict[str, Any]) -> None:
    """This server's pre-gate judge in the shape `scry_core.probe.Check` takes: each tool body
    calls `args.check` with its own values, defaults included, every number read first as the
    `tool()` wrapper reads it (`numbers_read`), so the probe judges a call the way the tool
    would. `given` is not used: the bodies judge what they run with."""
    args.check(tool, **inputs.numbers_read(_BODIES[tool], effective))


def tool(
    title: str, *, summary: summaries.Summary, read_only: bool = False, idempotent: bool = False,
    session_before: bool = False,
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

    `session_before` keeps the `session` block the body built instead of composing it after
    (`_finished`): only `close`, whose block is the state BEFORE the kill, so that `altered` is
    the truth about the session it ended.

    THREE kinds of exception are translated and no more: `NotStopped`, into the INVALID reply
    that names the last stop and the tools that answer while the machine runs; every other
    `SessionError`, through `running.session_error_reply`, which says which of them are an
    answer and which LATCH the session; and `Invalid`, the tools' own refusals, answered as
    `session_broken` when the call itself latched the session. Widening that to `Exception`
    would turn every genuine bug into "I examined nothing". A tool that takes a
    `ctx` (the protocol's `Context`, for the progress line of a bounded wait) gets it from the
    SDK and it is kept out of the summary's arguments.
    """

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(fn)
        _SUMMARIES[fn.__name__] = summary
        _BODIES[fn.__name__] = fn

        @functools.wraps(fn)
        def wrapped(*a: Any, **k: Any) -> Any:
            with LOCK:
                latched_before = STATE.broken
                reply: dict[str, Any] | None = None
                try:
                    # A COUNT IS AN INT TO EVERY BODY: an integral float a direct call or a
                    # `perform` step carried is made the int it equals (`integral_counts`).
                    # AND A NUMBER IS AN INT TOO: every argument the tool declares `NumberArg`,
                    # and each item of a `NumberList`, is read here, as `perform` reads a
                    # step's, before the body judges it (`inputs.as_read` tells mypy so).
                    called = signature.bind_partial(*a, **k)
                    for name, value in called.arguments.items():
                        ann = signature.parameters[name].annotation
                        if isinstance(ann, str):
                            called.arguments[name] = inputs.integral_counts(value, ann)
                    called.arguments.update(inputs.numbers_read(fn, dict(called.arguments)))
                    reply = fn(*called.args, **called.kwargs)
                except gs.NotStopped as e:
                    # THE GUEST RUNS AND THIS READER CANNOT ANSWER: say where the machine was
                    # last seen and which tools do answer now, so the caller can decide
                    # without provoking a stop (the running-guest contract).
                    reply = menvelope.invalid("not_stopped", str(e), last_stop=STATE.as_of(),
                                              answers_while_running=_ANSWERS_WHILE_RUNNING)
                except gs.SessionError as e:
                    # Every session error but `NotStopped`, answered here, where every tool
                    # passes, so no path a tool left unguarded escapes as an execution failure.
                    reply = running.session_error_reply(e, fn.__name__)
                except st.Invalid as e:
                    # Past the two above, ONLY `Invalid` is translated: a bug (an
                    # AttributeError, a broken regex, a session error) escapes as an execution
                    # failure, never as "I examined nothing" wearing a verdict. A stop the call
                    # made before it refused is recorded as its own first (`record_own_stop`).
                    # A refusal a tool built out of a request that LATCHED on this call names
                    # the wrong cause (an argument, an answer), so the latch answers instead.
                    latched = STATE.ses
                    reason = latched.broken if latched is not None else None
                    if latched is not None and reason and not latched_before:
                        reply = running.session_broke(
                            latched, gs.SessionError(reason), f"under `{fn.__name__}`",
                            "Nothing this call read is handed back")
                    else:
                        running.record_own_stop(fn.__name__)
                        reply = menvelope.envelope(e.reply())
                finally:
                    # The wrapper is the one place that knows the OUTER call is over, a call
                    # that escaped without a reply included. A `finally`, because an exception
                    # re-raised from one `except` clause never reaches a sibling clause.
                    STATE.end_call()
                    # THE IDLE CLOCK RESTARTS WHEN A CALL ENDS (`mame_idle`).
                    idle.IDLE.touch()
                assert reply is not None      # every path above either built one or raised
                bound = signature.bind_partial(*a, **k)
                bound.apply_defaults()               # a summary reads what the call RAN with
                args = dict(bound.arguments)
                args.pop("ctx", None)
                # Under the lock: the `session` block is read off the one machine's state.
                return _finished(fn.__name__, args, reply, session_before)

        # THE DOCSTRING IS A LITERAL WITH PLACEHOLDERS, filled here: a string composed with
        # `+` is an expression, not a docstring, so `__doc__` comes out None and the client
        # shows the tool with no description at all.
        wrapped.__doc__ = docs.filled(fn.__name__, fn.__doc__ or "")
        return mcp.tool(title=title,
                        annotations=ToolAnnotations(read_only_hint=read_only,
                                                    idempotent_hint=idempotent))(wrapped)

    return register


def progress_of(ctx: Context[Any, Any] | None) -> mprogress.Progress:
    """The progress line of one call, bridged from the worker thread the SDK runs a synchronous
    tool in to the request's `Context` on the event loop, and rebased so it never goes back
    (`mprogress.RebasedProgress`). With no context (a direct call, a test) nothing is painted and
    nothing is reported."""
    if ctx is None:
        return mprogress.no_progress

    def report(progress: float, total: float | None, message: str) -> None:
        anyio.from_thread.run(ctx.report_progress, progress, total, message)

    return mprogress.RebasedProgress(report)
