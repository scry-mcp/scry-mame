"""The MCP boundary of the MAME server: server object, the one lock, and the call boundary."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from scry_core import (
    boundary,
    cancel,
    envelope,
    frame_window,
    media_tools,
    presence,
    recording,
    roster,
)
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
    """The refusal's reply, built under the lock because it writes (`State.end_call`)."""
    def build() -> dict[str, Any]:
        reply = menvelope.invalid("bad_argument", strict.schema_refusal(cause))
        STATE.end_call()
        return reply

    return BOUNDARY.refused(name, arguments, build)


# The reported name must be the installed one (`claude mcp add mame`), which namespaces the tools.
# What answers while the machine runs is named in every refusal and in the `instructions`, from
# this one list. A fold answers by some of its methods only.
_ANSWERS_WHILE_RUNNING = roster.answers_while_running(
    roster.by_method(sequence.GATE.ops - set(media_tools.TOOLS), sequence.GATE.methods),
    sequence.NOT_STEPS, {"start", "rom_check"})

#: The tools by family, in the order the instructions list them; the media file tools answer in
#: any state, so their family answers whole.
ROSTER = roster.Roster(families=(
    ("Session", ("start", "status", "close", "focus", "rom_check")),
    ("Machine", ("cpu_info", "machine_map", "symbols_find", "log", "log_wait")),
    ("Advance", ("run_to", "run_for", "step", "resume", "stop", "trace", "series_capture")),
    ("Declarations", ("breakpoint_at", "regpoint_add", "watch_add", "declaration_list",
                      "declaration_clear")),
    ("Read", ("read_memory", "read_block", "registers", "disassemble", "find", "history",
              "memdump", "screen_map_find", "screen_map_write")),
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
    """This server's pre-gate judge, in the shape `scry_core.probe.Check` takes."""
    args.check(tool, **inputs.numbers_read(BOUNDARY.bodies[tool], effective))


def _end_cancelled(name: str, on_cancel: cancel.OnCancel
                   ) -> tuple[cancel.Left, dict[str, Any] | None]:
    """The end a cancelled call declared (`stop`, `kill` or `none`), applied under the shield.

    Returns what it left and any stop the machine reached on its own, for `_keep_accounts`."""
    left: cancel.Left | None = None
    with cancel.shielded():
        try:
            # A stop the call made itself must not be found later as the machine's own.
            running.record_own_stop(name, "the stop it made when its call was cancelled")
            if on_cancel == "kill" and (STATE.ses is not None or STATE.proc is not None):
                # Grace lets a live session write `cfg/` and `nvram/`; a booting MAME has none.
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
    """Calls the body; translates `NotStopped`, `SessionError` and `Invalid` into replies, no more.

    Widening that to `Exception` would turn every genuine bug into "I examined nothing"."""
    latched_before = STATE.broken
    try:
        # `NumberArg`s are read as ints here, as `perform` reads a step's.
        called.arguments.update(inputs.numbers_read(fn, dict(called.arguments)))
        reply: dict[str, Any] = fn(*called.args, **called.kwargs)
        return reply
    except gs.NotStopped as e:
        return menvelope.invalid("not_stopped", str(e), last_stop=STATE.as_of(),
                                 answers_while_running=_ANSWERS_WHILE_RUNNING)
    except gs.SessionError as e:
        return running.session_error_reply(e, fn.__name__)
    except st.Invalid as e:
        # A refusal built from a request that latched this call names the wrong cause, so the
        # latch answers instead.
        latched = STATE.ses
        reason = latched.broken if latched is not None else None
        if latched is not None and reason and not latched_before:
            return running.session_broke(
                latched, gs.SessionError(reason), f"under `{fn.__name__}`",
                "Nothing this call read is handed back")
        running.record_own_stop(fn.__name__)
        return menvelope.envelope(e.reply())


def _after() -> None:
    """After every call, a sequence step included: drop its one-time account, restart idle."""
    STATE.end_call()
    idle.IDLE.touch()


def _keep_accounts(reply: dict[str, Any]) -> None:
    """Put back a stop-on-its-own account that a reply nobody read carried."""
    if reply.get("stopped_on_its_own"):
        STATE.found_stop_last = dict(reply["stopped_on_its_own"])


def _keep_cancelled(record: cancel.Cancelled) -> None:
    STATE.cancelled = record


def _machine() -> recording.Machine:
    """The machine around a recorded call: whether it runs, and the last stop's place."""
    ses = STATE.ses
    stop = STATE.last_stop
    moving = ses is not None and bool(ses.running)
    if moving or not stop:
        return recording.Machine(running=moving, seq=stop.get("seq"))
    return recording.Machine(running=False, seq=stop.get("seq"), frame=stop["frame"],
                             stop={"pc": stop["pc"], "frame": st.frame_shown(stop["frame"])})


#: Each kind of declaration a `start` re-arms, by the tool that lists it and its rows' field.
_LISTS = {kind: ("declaration_list", key) for kind, key in dec.COUNT_KEYS.items()}


RECORDER = recording.Recorder("mame", "server.py", frame_window.UNTIL_STEPS_MAX, _machine,
                              lambda: STATE.ses is not None and STATE.machine_alive(),
                              declarations=lambda: arming.store().declarations(),
                              kinds=_LISTS,
                              stop_fields=("pc", "frame"),
                              outside=sequence.NOT_STEPS - sequence.SEQUENCES - {"start"},
                              sequences=sequence.SEQUENCES, start_tool="start",
                              states=recording.States("state_write", "save", "load", "name"))

# Hooks are bound once at import: a test patches the name a hook calls through, not the hook.
BOUNDARY = boundary.Boundary(
    mcp, st.LOCK, invoke=_invoke, end=_end_cancelled, after=_after,
    refusal_line=summaries.refusal, session_block=menvelope.session_block,
    take_cancelled=STATE.take_cancelled, keep_cancelled=_keep_cancelled, doc=docs.filled,
    give_back=_keep_accounts, recorder=RECORDER,
    listener=presence.Slot(lambda: STATE.presence.held))


def tool(
    title: str, *, summary: summaries.Summary, read_only: bool = False, idempotent: bool = False,
    session_before: bool = False, on_cancel: cancel.OnCancel | None = None,
    replay: recording.Replay | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Registers an MCP tool on this server's boundary, serialised over the one machine."""

    return BOUNDARY.tool(title, summary=summary, read_only=read_only, idempotent=idempotent,
                         session_before=session_before, on_cancel=on_cancel, replay=replay)
