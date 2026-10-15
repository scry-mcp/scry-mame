"""MCP server owning one live MAME debug session, so questions cost milliseconds.

WHY AN MCP AND NOT A SCRIPT. The expensive part was never the question, it was the state:
each shell command is a fresh process, so a debug session died between one question and the
next and every follow-up paid another boot: measured on a 68000 arcade driver, seconds for a
boot and tens of seconds to reach a late attract screen, against about a millisecond per
query on a session that stays put. An MCP is a long-lived process that holds that state,
which is exactly the missing piece.

WHAT IT DELIBERATELY DOES NOT DO. Counting how many times a routine runs across a whole
attract cycle is a WHOLE-RUN question, and paying a run for it is correct; forcing it through
a stop-and-continue loop over the wire would be slower, not faster. That job stays with the
project's batch tracer. This server answers the other kind: what is here, now, and what
happens next.

HONESTY, wired into the contract rather than into a prompt:

- `start` refuses to hand back a session that cannot reproduce the ROM file on disk, and kills
  it: a guarantee that leaves alive what it just declared invalid is not a guarantee.
- `run_to` counts a CONTROL breakpoint declared at a hot place beside the target, refuses to run
  with none, and reports its hit count with the answer. "It never ran" is evidence only when the
  control fired; when it did not, the tool answers INVALID instead of a zero. Several different
  mistakes silence a MAME breakpoint, and every one of them looks exactly like "that routine is
  never called".
- Every reply carries a `session` block with `altered` in it, because writing to a live machine
  is allowed here and a measurement taken on a forced state is not a measurement of the game.
  `console` rides beside it for the same reason: what the Lua channel did to this session is
  a property of every answer it gave, not of the one reply that happened to be looking.
- A machine let go with `resume` is taken as RUNNING until a stop is read, and the readers
  refuse to answer from it, naming the last stop: a value read off a moving machine is a
  sample of no state. What a running machine offers is what it writes (`log`, `log_wait`),
  its screen (`snapshot`), its breakpoints, and `stop`.

THE SHAPE OF A REPLY, AND THE NAMES OF THE TOOLS AND THEIR ARGUMENTS, ARE THE FLEET'S CONVENTION,
one spelling per concept wherever two servers name one: `debug` for the console,
`run_to` for a run to a place, `read_memory` for bytes, `ref` for how a place is named, `seconds`
for how long a wait may take, `count` for how many steps, the `breakpoint_*` verbs, and
`memdump(ref, length, dest)` with its subject first. One spelling per concept is the fleet's
rule for every tool surface, and the two emulator servers were the one place it was broken.

The server knows no game: the system, the ROM paths and the symbol file come from the caller,
and the binary from its argument, `MAME_BINARY` or the PATH, so the same server serves every
project.
"""

from __future__ import annotations

import functools
import inspect
import json
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import anyio.from_thread
import anyio.to_thread
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import ValidationError

# The gdbstub client and the modules live next door, and this file starts in two ways: as a
# script (`python server.py`, which puts its directory on sys.path) and as the package's
# installed entry point (which does NOT). Without this line the second way dies at the import,
# and the server is launchable only with `--directory` pointing here.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scry_core import strict_arguments as strict  # noqa: E402

import gdb_session as gs  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_args as args  # noqa: E402
import mame_audio as maudio  # noqa: E402
import mame_blits as mblits  # noqa: E402
import mame_block as block  # noqa: E402
import mame_breakpoints as breakpoints  # noqa: E402
import mame_comments as comments  # noqa: E402
import mame_cpu_info as mcpu_info  # noqa: E402
import mame_cpus as cpus  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_docs as docs  # noqa: E402
import mame_draft as mdraft  # noqa: E402
import mame_envelope as menvelope  # noqa: E402
import mame_files as files  # noqa: E402
import mame_film as mfilm  # noqa: E402
import mame_focus as mfocus  # noqa: E402
import mame_gfx as mgfx  # noqa: E402
import mame_idle as idle  # noqa: E402
import mame_inputs as inputs  # noqa: E402
import mame_iotaps as iotaps  # noqa: E402
import mame_launch as launch  # noqa: E402
import mame_layout as ml  # noqa: E402
import mame_locate as mlocate  # noqa: E402
import mame_lua as mlua  # noqa: E402
import mame_machine as machine  # noqa: E402
import mame_manifest as manifest  # noqa: E402
import mame_map as mmap  # noqa: E402
import mame_palette as mpalette  # noqa: E402
import mame_picture as picture  # noqa: E402
import mame_progress as mprogress  # noqa: E402
import mame_ramdac as mramdac  # noqa: E402
import mame_read as read  # noqa: E402
import mame_recording as mrec
import mame_regpoints as regpoints  # noqa: E402
import mame_running as running  # noqa: E402
import mame_savestates as savestates  # noqa: E402
import mame_scan as mscan  # noqa: E402
import mame_screen as mscreen  # noqa: E402
import mame_sequence as sequence  # noqa: E402
import mame_space as mspace  # noqa: E402
import mame_state as st  # noqa: E402
import mame_summaries as summaries  # noqa: E402
import mame_sweep as msweep  # noqa: E402
import mame_trace as mtrace  # noqa: E402
import mame_watches as watches  # noqa: E402
import mame_write as mwrite  # noqa: E402
from mame_state import STATE  # noqa: E402


class Envelope(MCPServer):
    """THE MCP BOUNDARY, where two things happen once for every tool.

    THE SCHEMA'S REFUSAL. The SDK validates every call against the tool's schema before the
    tool runs, and its refusal is its own error text, outside the reply shape every tool here
    promises. Nothing is validated twice: the refusal is caught here, once, and given the
    envelope (`summary`, `status`, `code`, `message`, `session`) so a caller reads one shape.
    Any other error keeps the SDK's path: a defect in a tool body is never dressed as a
    refusal.

    THE PICTURE. A graphics tool's body names its PNG in `image`; the picture itself is
    attached here, beside the JSON (`mame_picture.attached`), so a tool body and a test deal in
    a plain dict and the attachment is built in one place."""

    async def call_tool(self, name: str, arguments: dict[str, Any],
                        context: Context[Any, Any] | None = None) -> Any:
        try:
            return picture.attached(await super().call_tool(name, arguments, context))
        except ToolError as e:
            cause = strict.refused_by_schema(e)
            if cause is None:
                raise
            # OFF THE EVENT LOOP, AND THAT IS NOT A PREFERENCE. See `_refused` for the lock;
            # what forces the worker thread is that a plain `with _LOCK:` here DEADLOCKS. Every
            # tool body is synchronous, so the SDK runs it on a worker thread and that thread
            # is what holds the lock; a bounded wait reports progress from there through
            # `_progress`, which needs the event loop (`anyio.from_thread.run`). A loop parked
            # in `_LOCK.acquire()` never runs that callback, so the worker never finishes and
            # never lets go, and the loop never gets the lock. Both sides wait for ever.
            return await anyio.to_thread.run_sync(self._refused, name, arguments, cause)

    @staticmethod
    def _refused(name: str, arguments: dict[str, Any], cause: ValidationError) -> Any:
        """The refusal's reply, built over the ONE machine like every other reply.

        THE SEAM SITS OUTSIDE `tool()`'s WRAPPER and so outside the `_LOCK` that wrapper
        holds, which would be a torn read of the state group `envelope()` gathers. It is
        worse than that: this path WRITES, ending the call (`State.end_call`), the one-time
        account of a stop the machine reached on its own. Unlocked, a call the schema refused
        could take that account away from the call that was building the reply meant to carry
        it, and the stop would be reported to nobody.

        NOTHING ON THIS PATH CAN ALREADY HOLD THE LOCK, established by reading rather than
        relied on: the schema refuses BEFORE the tool body runs, so this call never reached
        the wrapper that takes it, and no tool in this package dispatches through
        `call_tool`. `_LOCK` being an `RLock` is not what makes this safe.
        """
        with _LOCK:
            # `start` promises `start_retries` on every reply, and this one launched nothing.
            launched: dict[str, Any] = {"start_retries": []} if name == "start" else {}
            reply = menvelope.invalid("bad_argument", strict.schema_refusal(cause), **launched)
            STATE.end_call()
            body = _finished(name, arguments, reply)
        text = TextContent(type="text", text=json.dumps(body, indent=2))
        return CallToolResult(content=[text], structured_content=body)


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
_ANSWERS_WHILE_RUNNING = [*sorted(sequence.RUNNING_OK_OPS),
                          "registers(from_last_stop=True)", "perform", "drive", "close"]

mcp = Envelope(
    "mame",
    instructions=(
        "A live MAME debug session.\n\n"
        "TOOLS. Session: `start`, `rom_check`, `focus`. "
        "Advance: `run_to`, `run_for`, `step`, `resume`, `trace`. Read: "
        "`read_memory`, `read_block`, `registers`, `disassemble`, `find`, `history`, "
        "`palette`, `screen_view`, `gfx_view`, `gfx_locate`, "
        "`gfx_sweep`, `gfx_draft`, `gfx_blits`, `gfx_blit_source`. "
        "Write: `write`, `set_register`, `reset`. Scan: `scan_start`, `scan_filter`. "
        "Comments: `comment_add`, `comment_delete`, `comment_load`. Lua: `input`, `record`, "
        "`audio_record`, "
        "`state_save`, `state_load`, `screen_signature`, `lua`. "
        "Console: `debug`.\n\n"
        "A SESSION. `start` parks the machine STOPPED. "
        "`run_to`, `run_for` and `step` stop it again, with a survey; "
        "`run_to`'s target has no stop of its own. "
        "`resume` lets it RUN. While it runs the readers refuse (`not_stopped`); these "
        "answer: " + ", ".join(f"`{name}`" for name in _ANSWERS_WHILE_RUNNING) + ". A stop "
        "reached on its own is `stopped_on_its_own`. `rom_check` reads 16 bytes at "
        "`reference_addr` against `reference_rom` at `reference_base`. A wait that ran out "
        "is `verdict: TIMEOUT`, `ok`. "
        "`memdump` and `snapshot` answer with a PATH.\n\n"
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
)

# ONE LOCK FOR ONE MACHINE. The server keeps ONE session in a global and the transport can hand
# over two calls at once. Without it, two overlapping `run_to` calls trample each other's
# breakpoints and steal each other's stops: the first collects the second's stop and returns a
# verdict about a PC that is not its own. A debugger that reports the wrong stop is worse than a
# slow one, so the tools serialize. Full stop.
_LOCK = threading.RLock()


def _summary(name: str, args: dict[str, Any], reply: dict[str, Any]) -> str:
    """The one line the MCP client shows for a call (`mame_summaries`): the envelope's for a
    refusal, the tool's own otherwise."""
    if reply.get("status") == "INVALID":
        return summaries.refusal(name, reply)
    return _SUMMARIES[name](args, reply)


#: Each registered tool's summary, filled by `tool` as it registers them.
_SUMMARIES: dict[str, summaries.Summary] = {}


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
    args.check(tool, **inputs.numbers_read(globals()[tool], effective))


def tool(
    title: str, *, summary: summaries.Summary, read_only: bool = False, idempotent: bool = False,
    session_before: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Registers an MCP tool, SERIALIZES it over the one machine (see `_LOCK`), and puts the
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

        @functools.wraps(fn)
        def wrapped(*a: Any, **k: Any) -> Any:
            with _LOCK:
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


def _progress(ctx: Context[Any, Any] | None) -> mprogress.Progress:
    """The progress line of one call, bridged from the worker thread the SDK runs a synchronous
    tool in to the request's `Context` on the event loop, and rebased so it never goes back
    (`mprogress.RebasedProgress`). With no context (a direct call, a test) nothing is painted and
    nothing is reported."""
    if ctx is None:
        return mprogress.no_progress

    def report(progress: float, total: float | None, message: str) -> None:
        anyio.from_thread.run(ctx.report_progress, progress, total, message)

    return mprogress.RebasedProgress(report)


def _contact() -> tuple[gs.Session, Path]:
    """The live machine and its scratch, whatever it is doing: the gate of the tools that
    answer on a RUNNING machine. A stop the machine reached on its own is recorded here, by
    whichever tool makes the first contact after it (`running.observe_stop`)."""
    ses, scratch = STATE.live()
    st.refuse_broken(ses)
    running.observe_stop(ses, scratch)
    st.refuse_broken(ses)      # a request inside the observation may have latched it
    return ses, scratch


def _stopped(what: str) -> tuple[gs.Session, Path]:
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
    ses, scratch = _contact()
    running.require_stopped(ses, what)
    return ses, scratch


# ----------------------------------------------------------------------------- session

@tool("Start a MAME session", summary=summaries.start)
def start(
    system: str,
    rompath: str,
    reference_rom: str,
    symbols: str | dict[str, str] = "",
    reference_addr: str = "0x0",
    inipath: str = "",
    seconds: float = 8.0,
    shared: bool = False,
    background: bool | None = None,
    boot_lua: str = "",
    env: dict[str, str] | None = None,
    bases: dict[str, str] | dict[str, dict[str, str]] | None = None,
    reference_base: str = "0x0",
    display: Annotated[str, inputs.vocabulary(launch.DISPLAY_OPTIONS)] = "",
    stub_port: int = 0,
    state_dir: str = "",
    throttle_from_frame: int = 0,
    types: str | dict[str, str] = "",
    cfg: str = "",
    binary: str = "",
    ctx: Context[Any, Any] | None = None,
) -> dict[str, Any]:
    """Start MAME with its gdbstub, parked STOPPED and checked against the reference image.

    Arguments (every path absolute; `rompath`, `inipath`, `state_dir` directories, the rest files):
    - `system`, `rompath`; `binary` (omitted: `MAME_BINARY`, else the PATH's `mame`).
    - `reference_rom`, `reference_addr` (`0x`), `reference_base` (`0x`, the image's first byte).
    - `symbols`: a YAML or the linker's five-column map, the first cpu's. `bases`
      maps each non-CODE class of a map to a `0x` base or to `rom`. `types`: a file of `name:
      format` lines. Several cpus: `symbols` `{cpu: path}`, `bases` `{cpu: {class: base}}`,
      `types` `{cpu: file}`.
    - `shared=True`: somebody WATCHES (big window, real speed); `display` (`main` | `secondary`)
      says where and needs `shared=True`. `throttle_from_frame`: flat out until it.
    - `background`: `true` behind, your focus kept; `false` in front; omitted, by `shared`.
    - `boot_lua`, an EXISTING harness file, never Lua text (no tool here writes one;
      never `manager.machine:exit()`), `env` for it, `inipath`,
      `seconds` (the stub's wait, (0, {WAIT_MAX_S}]), `stub_port` (`0`: a free one).
    - `state_dir` (empty: disposable; else kept), `cfg`.

    Refused before anything is spawned: a live session, a relative path, a missing file, a cpu
    the machine lacks, a class with no base, `bases` beside a YAML file, a bad `types` line,
    a `stub_port` in use,
    a `reference_addr` OUTSIDE the image; a `system` the binary lacks. Another pid's stub:
    `host_failed`. 16 bytes that do not match: `readback_refused`, closed.

    Reply: `system`, `binary`, `binary_origin`, `version`, `pid`, `stub_port`, `scratch_dir`,
    `state_dir`, `cfg`, `debugger`, `errorlog_path`, `stdout_path`, `rom_check`,
    `symbols_total`, `symbols_typed`, `symbols_format`, `symbols_by_class` (first cpu),
    `symbols_by_cpu`, `registers`, `pc`, `frame`, `frame_symbol`, `machine` (counts), what
    reached the driver (`env`, `display`, `background`, `flags`, `throttle_from_frame`,
    `boot_lua_path`), `declarations` and `start_retries`.

    Reference: REFERENCE.md, The session.
    """
    try:
        args.check("start", binary=binary, rompath=rompath, reference_rom=reference_rom,
                   symbols=symbols, inipath=inipath, boot_lua=boot_lua, state_dir=state_dir,
                   cfg=cfg, types=types, display=display)
    except st.Invalid as refused:
        refused.fields["start_retries"] = []    # every `start` reply carries it, refusals too
        raise
    return launch.start(binary, system, rompath, reference_rom, symbols, reference_addr,
                        inipath, seconds, shared, boot_lua, env, bases, reference_base, display,
                        stub_port, state_dir, throttle_from_frame, types, cfg,
                        background=background, progress=_progress(ctx))


@tool("Session status", summary=summaries.status, read_only=True)
def status() -> dict[str, Any]:
    """Whether a machine is alive, and which one. Safe on a running machine; a stop it finds
    the machine reached on its own is recorded and reported in `stopped_on_its_own`.

    Reply: `alive`; with no machine, a `note` when the server closed the last session after an hour
    with no call; with `exit_code` and a `note` when MAME died under the session (`close` collects
    its last words before anything is deleted); when alive also `system`, `pid`, `stub_port`,
    `scratch_dir`, `state_dir`, `cfg`, `debugger` (`attached`, and a `note`: a capture taken at a
    stop here can land a frame away from an autoboot golden), `fingerprint` (the build the
    declarations are judged against, the first cpu's) and `fingerprints` (each cpu's),
    `errorlog_path`, `stdout_path`, `running`, `pc` (the machine's, read now; absent while it runs
    or once the session broke: `last_stop.pc`), `last_stop` (`stop_seq`, `pc`, `cpu`, `frame`,
    `how`, `since_s`, `wall_at`; the park after `start` is stop 1), `in_debugger` (`breakpoints`,
    `watches` (the change watches) and `regpoints`: each `ref` this server armed in the debugger,
    and its `cpu`), `threads` (the stub's thread per cpu; empty without the thread patch), `cpus`
    (what each is doing is `cpu_info`'s), `frame_symbol` (the frame counter's name as `start` asked
    it, unavailable on a board with none), and, always present, `console_pending` (Lua lines sent
    and not yet evaluated, which `close` drains before its `quit`), `throttles_pending` (`mark`,
    `on`) and `tallies_pending_removal` (`tally_id`, `call`), where a switch that landed is its row
    leaving. `broken` (absent on a healthy session) says why it can no longer be trusted: the
    machine is then asked nothing, `running` reads false, and the way out is `close`, then `start`.

    Reference: REFERENCE.md, The session.
    """
    return launch.status()


@tool("Close the MAME session", summary=summaries.close, session_before=True)
def close(ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """End the session: MAME is asked to `quit` through its console and killed only if it has not
    gone within the grace period. The scratch (snapshots included) is deleted; a `state_dir` stays.
    Works on a RUNNING machine too. Takes no argument and refuses nothing: with no session it
    answers `closed: false`.

    Reply: `closed`, `stdout_tail` and `errorlog_tail` (the last words of each channel, read before
    the scratch goes), `ended_by` (`quit`: a clean exit that wrote its cfg; `exited`: it exited and
    wrote none; `killed`: SIGKILL after the grace period; `died`: it had already exited; `none`: no
    session), `state_written`, `exit_code` (unavailable with its `why` when SIGKILLed and still not
    reaped: an emulator may still be on the machine), `cfg` (`installed_path`, `changed`: did MAME
    rewrite the copy, `available: false` with its `why` when a file could not be read back;
    unavailable when no cfg was given; the repo's file is never touched), `console_pending_before`,
    `console_drained` and a `note` (the Lua pipe, emptied before the `quit`), and `average_speed`
    when it ends a run (`percent` with the two deltas, or `available: false` with its `why`; absent
    on a broken session). The `session` block describes the state BEFORE closing, plus any throttle
    found not applied, which `session_describes` says in the reply: `alive: true` beside `closed:
    true` is that, not a contradiction.

    Reference: REFERENCE.md, The session.
    """
    return launch.close(_progress(ctx))


@tool("Show another cpu", summary=summaries.focus)
def focus(cpu: str) -> dict[str, Any]:
    """Make `cpu` (`subcpu` or `:subcpu`) the debugger's VISIBLE cpu, and read it back off the
    console's `cpulist`. {NEEDS_STOPPED}.

    THE MODEL, every tool's: no `cpu` is the visible cpu, which a stop moves to the cpu that
    stopped and a release back to it (`cpu_info`'s `visible`); `cpu` names another, and the
    visible one stays (`step` alone shows the cpu it steps). A reply that touches a cpu names
    it (`cpu`). A declaration keeps its cpu, its `ref` resolving in that cpu's symbols. `rpset`
    names no cpu: a registerpoint is the visible cpu's. Another cpu's registers and memory need
    the thread patch.

    On a build whose gdbstub serves a thread per cpu (`status`'s `threads`) it is the stub's `Hc`,
    which ignores no cpu and releases nothing, and the reply PROVES nothing ran: `machine_ran:
    false`, the `frame`, and `unchanged`, the cpus whose whole register block read the same before
    and after (`unread`: one whose block the stub refuses). Without that patch it is the console's
    own `focus`, which IGNORES every other cpu (a breakpoint or watch on one has no effect until
    `debug("observe <cpu>")`) and, when it ignores the visible cpu, RUNS until `cpu` executes:
    `ignored` lists them, and a run adds the survey of where it stopped.

    Refused: a cpu the machine lacks (`unknown_ref` with `cpus`); on the patched stub, a cpu the
    debugger ignores (`bad_argument`). A visible cpu read back other than `cpu` is
    `readback_refused`; a console run that reached no stop on an observed cpu is `not_settled`.

    Reply: `cpu` (read back), `was`, `via` (`stub` or `console`), `machine_ran`, and `frame`,
    `unchanged`, `unread` (stub) or `ignored` and on a run {STOP_FIELDS} (console).

    Reference: REFERENCE.md, The session.
    """
    args.check("focus", cpu=cpu)
    return mfocus.focus(*_stopped("a focus"), cpu)


@tool("What the debugger sees of each cpu", summary=summaries.cpu_info, read_only=True)
def cpu_info(cpu: str = "") -> dict[str, Any]:
    """WHAT THE DEBUGGER SEES OF EACH CPU at the call, one row per cpu: whether it is visible,
    ignored or suspended, its program counter, and how many breakpoints, watches and
    registerpoints are declared on it, moving nothing: the listings are the console's own and
    each pc register is read off the stub, so no cpu is made visible and nothing runs. Answers
    on a RUNNING machine too. What a cpu IS (its type, clock, spaces) is `machine_map`'s.

    Arguments: `cpu`, a tag in either spelling (`subcpu` or `:subcpu`), narrows the rows to that
    cpu's, and only its pc is read; empty is every cpu.

    Refused: a tag no row names (`unknown_ref` naming the ones that do); no machine
    (`no_session`); a session that broke, a read that latched it included (`session_broken`).

    Reply: `cpus`, one row per cpu `cpulist` lists, in its order, then one per other cpu a
    declaration names: `cpu`, `visible` (the cpu a call naming none acts on; a stop moves it),
    `ignored` (its breakpoints and watches have no effect), `suspended` (held by the debugger's
    own `suspend`), `pc` (its program counter register, `reg` and `value`, or unavailable with
    why, as while it runs), `declarations` (this server's `breakpoints`, `watches`, an io tap
    among them, and `regpoints` on it, counted in any state; an expr watch names no cpu).
    `visible`, `ignored` and `suspended` are unavailable when the console did not answer, and
    all four for a cpu `cpulist` does not list; `declarations` is always counted. `cpu` (unavailable
    unless named).

    Reference: REFERENCE.md, The session.
    """
    return mcpu_info.cpu_info(_contact()[0], cpu)


@tool("Check the ROM against its image", summary=summaries.rom_check, read_only=True)
def rom_check(
    reference_rom: str, reference_addr: str = "0x0", reference_base: str = "0x0",
    cpu: str = ""
) -> dict[str, Any]:
    """Re-validate the session: the 16 bytes at `reference_addr` of `cpu` (`subcpu`; the visible
    one when empty) against the reference image `reference_rom` (placed at `reference_base`), a
    repeated read for determinism, and the cost of a query. {CPU_READS}.

    Reply: `rom_check` (`OK`), `deterministic`, `query_s`, `cpu` (the one read). The three
    arguments come again on every call (`state_load` checks against the image `start` held; this
    is the check a caller points where it likes), with `cpu` naming the image's cpu once a stop
    has made another one visible; a mismatch is `readback_refused`, naming the cpu read and both
    sides. It is about the live machine, never about the build. {NEEDS_STOPPED}.

    Reference: REFERENCE.md, The session.
    """
    args.check("rom_check", reference_rom=reference_rom, reference_addr=reference_addr,
               reference_base=reference_base)
    return launch.rom_check(_stopped("a known-answer read")[0], reference_rom, reference_addr,
                            reference_base, cpu)


# ----------------------------------------------------------------------------- advance

# THE STOP SURVEY every tool that hands the machine back stopped carries is `mame_docs.STOP_FIELDS`,
# quoted into the docstrings through their `{STOP_FIELDS}` placeholder.


@tool("Run to a place, with a control", summary=summaries.run_to)
def run_to(ref: str, control: str = "", seconds: float = 30.0,
           disarm_watches: bool = False, condition: str = "", cpu: str = "",
           ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Run to `ref` and stop, with the session's CONTROLS counting meanwhile.

    Arguments: `ref`, the target, armed on `cpu` (the visible one when empty) and reached only by
    that cpu. `control`: a ref declared as a control on the target's cpu
    (`breakpoint_at(role="control")`: counts, never halts); with none there the run is refused, and
    one named here is DECLARED and stored. `condition`: stop at `ref` only when it holds, in the
    console's grammar, bare numbers hex (`w@DemoLen==0x25`; no `,`, `;`, braces or assignment).
    `seconds`: the wall-clock bound, (0, {WAIT_MAX_S}]. `disarm_watches=True`: change watches off
    for this pass, re-armed after it (`disarmed_watches`, `not_rearmed`).

    Refused before anything is declared: a target or a control this build does not resolve, a
    `condition` too long for a packet (`command_chars`, `limit_chars`). {NEEDS_STOPPED}.

    Reply: `verdict` (`TARGET`; `TIMEOUT` within `seconds`, the machine STOPPED; `OTHER_STOP`, a
    registerpoint included), `control_hits`, `controls` (each control's `ref`, `cpu`, `hits_in_run`
    over THIS run), and {STOP_FIELDS}. A removal the stub refuses keeps the stop's reply, with
    `target_disarmed: false` and a `note`; a stop packet landing during it is a TIMEOUT, `how`
    "answered late". A TARGET is `ok` with no control hit: reaching it proves the cpu ran. An
    INVALID run carries no `verdict`: `control_silent` (a TIMEOUT with no control hit: the survey,
    `control_dasm`, a `note`), `cut_by_other_stop`, `readback_refused` (a row listed bare is
    removed first), `not_settled` (may be RUNNING: `stop`, and if `stop` fails as well, `close`
    then `start`) or `session_broken`, which LATCHES until `close`.

    Reference: REFERENCE.md, Advancing the machine.
    """
    args.check("run_to", ref=ref, seconds=seconds, condition=condition, control=control)
    return advance.run_to(*_stopped("a run to a place"), ref, control, seconds, _progress(ctx),
                          condition=condition, disarm_watches=disarm_watches, cpu=cpu)


@tool("Run for emulated time", summary=summaries.run_for)
def run_for(milliseconds: int = 0, frames: int = 0, seconds: float = 30.0,
            disarm_watches: bool = False, ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Run the machine for `milliseconds` of EMULATED time, or for `frames` of the frame COUNTER
    (exactly one of the two), and wait until it has STOPPED.

    Arguments: `milliseconds` (the console's `gtime`) or `frames` (one `gvblank` per tick, each
    confirmed on the counter; sent through the first cpu, the one MAME's vblank stop lands on,
    with a `note` when it had to be made visible; the first screen's counter on a board of
    several; `no_channel` on a board with none). `seconds`: the wall-clock bound,
    (0, {WAIT_MAX_S}]. `disarm_watches` as in `run_to`. {NEEDS_STOPPED}.

    Reply: `verdict` (`ELAPSED`: it stopped by itself; `TIMEOUT`: still moving at `seconds`, so
    interrupted; `OTHER_STOP`: a watch, stop breakpoint, registerpoint or row typed through `debug`
    cut it, named by the survey; a CONTROL never cuts), `frame_before`, `frame_after`,
    `emulated_before_s`, `emulated_after_s`, `cycles` (the visible cpu's `totalcycles` over what was
    asked), each unavailable with why (no counter; `cycles` also across two cpus, after a load,
    rewind or typed reset), `polls` (by frames, the `gvblank`s sent, N+1 after a mid-frame stop) or
    `reads` (by milliseconds, its readings), and {STOP_FIELDS}. An INVALID run carries no
    `verdict`: `no_progress` (by `milliseconds`, a counter or clock that did not move, as under one
    frame: the survey, the machine STOPPED; by `frames`: no survey, the machine RUNNING until
    `stop`), `frames_went_backwards`, `not_settled` (a counter or clock still moving at the bound;
    may be RUNNING: `stop`, and if `stop` fails as well, `close` then `start`) or `session_broken`,
    which LATCHES. Reports its progress while it waits; advancing alters nothing.

    Reference: REFERENCE.md, Advancing the machine.
    """
    args.check("run_for", milliseconds=milliseconds, frames=frames, seconds=seconds)
    return advance.run_for(*_stopped("a run by time"), milliseconds, seconds, _progress(ctx),
                           disarm_watches=disarm_watches, frames=frames)


@tool("Trace what a run executes", summary=summaries.trace)
def trace(milliseconds: int = 0, frames: int = 0, dest: str = "", seconds: float = 60.0,
          cpu: str = "", noloop: bool = False,
          ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Run as `run_for` does with MAME's own tracer on one cpu, then hand back every address
    that cpu executed, joined to its symbols. It takes no `ref`: the window is frames or
    milliseconds, and no trace runs until a place is reached (`run_to` goes there, untraced).

    Arguments: `milliseconds` or `frames` as in `run_for` (at most {TRACE_FRAMES_MAX} frames or
    {TRACE_MS_MAX} ms; with `noloop`, {NOLOOP_FRAMES_MAX} and {NOLOOP_MS_MAX}). `dest`: an absolute
    path not there yet; empty lands in the scratch. `seconds`: the wall-clock bound,
    (0, {WAIT_MAX_S}]. `cpu`: the visible one when empty. `noloop=True`: only for exact
    `count`s and `instructions` (every instruction written), never for which addresses ran.
    {NEEDS_STOPPED}.

    Reply: `run_for`'s, plus `trace`: `cpu`, `path` (the tracer's file), `bytes`, `set_path` (one
    row per executed address, ascending: `addr`, `symbol` when placed, `count` under `noloop`),
    `instructions`, `addresses`, `unplaced`, `symbols` (per routine: `symbol`, `addr`, `addresses`,
    `first`, `last`, `instructions` under `noloop`; first {TRACE_SYMBOLS_SHOWN}), `symbols_total`,
    `truncated`, `noloop`, `note`. Refused before anything is armed: an existing `dest` or
    `<dest>.set.jsonl`, a cpu with no disassembler (`no_channel`). A trace with no instruction line
    is `readback_refused`; a tracer that could not be closed is `readback_refused` with
    `trace.closed: false` (unavailable when the session broke); an INVALID run carries `trace`
    (`path`, `bytes`, `closed`) and no set file.

    Reference: REFERENCE.md, Advancing the machine.
    """
    args.check("trace", milliseconds=milliseconds, frames=frames, dest=dest, seconds=seconds,
               noloop=noloop)
    return mtrace.trace(*_stopped("a trace"), milliseconds, frames, dest, seconds, cpu, noloop,
                        _progress(ctx))


@tool("Step instructions", summary=summaries.step)
def step(count: int = 1, mode: Annotated[str, inputs.vocabulary(advance.STEP_MODES)] = "into",
         cpu: str = "") -> dict[str, Any]:
    """Execute `count` (1..{STEP_MAX}) instructions of `cpu` (`subcpu`; the visible one when empty)
    and stop, the ceiling keeping the longest walk of `over`s inside the bound every wait takes (a
    longer one is `run_to` or `run_for`):
    `into` (the gdbstub's single step, one instruction) or `over` (the console's `over`: a call is
    run to its return as one step). A named cpu is made visible first (the stub's `Hc`, needing
    the thread patch); MAME runs every other cpu meanwhile, and `others` gives each one's program
    counter register before and after. A stop on another cpu ends the steps there (`note`).
    An `over` still moving at its bound is interrupted and answers INVALID (`not_settled`)
    with the count; whether the call would have returned later is not seen. An `over` the
    console REFUSED is `not_settled` too: it may have been taken, so the session is marked
    RUNNING and `stop` recovers it; if `stop` fails as well, `close` then `start` is the way
    out. An `into` whose stop does not arrive in time is `not_settled` as well, with `mode`
    and `instructions_completed`: the stub still owes the stop packet of
    that step, and `stop` waits for it. An `into` that reads anything else in a stop's place,
    or whose connection failed, is `session_broken` with both, and it
    LATCHES as `run_to`'s does; so does an `over` whose connection failed, or that the console
    did not answer IN TIME: that answer is still owed and would be read as the next
    request's, so `close` then `start` is the way out.
    {NEEDS_STOPPED}.

    Reply: `mode`, `instructions_completed` (those that landed), `others` on a build with a thread
    per cpu, then {STOP_FIELDS}.

    Reference: REFERENCE.md, Advancing the machine.
    """
    args.check("step", count=count, mode=mode)
    return advance.step(*_stopped("a step"), count, mode, cpu)


@tool("Resume the machine", summary=summaries.resume)
def resume(seconds: float = 0.0, ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Let the machine RUN. With `seconds` at zero (the default) it comes back at once and the
    machine runs with NO deadline, until a breakpoint fires, `stop`, or `close`; with a bound it
    waits up to `seconds` for a stop and, if none comes, LEAVES IT RUNNING (unlike `run_to`, which
    interrupts at its bound). {NEEDS_STOPPED}: a second `resume` is refused.

    Reply: `waited_s`; with a bound, `verdict`: `OTHER_STOP` (back at the debugger, with
    {STOP_FIELDS} and `average_speed`) or `TIMEOUT` (LEFT RUNNING, a `note`); with 0, none.
    `seconds` is 0 or a bound up to {WAIT_MAX_S}. While it runs the readers of the machine refuse,
    naming `last_stop` and, in `answers_while_running`, every tool that answers. A wait that reads
    something in a stop's place, or a release that could not be sent, is `status: INVALID`
    (`session_broken`) and never a running session, and so is a stop that was read and could not be
    surveyed: it LATCHES as `run_to`'s does, and the way out is `close`, then `start`. Reports its
    progress while it waits.

    Reference: REFERENCE.md, Advancing the machine.
    """
    args.check("resume", seconds=seconds)
    return running.resume(*_contact(), seconds, _progress(ctx))


@tool("Stop a running machine", summary=summaries.stop)
def stop() -> dict[str, Any]:
    """Stop a RUNNING machine where it is (the stub's interrupt) and survey the stop.

    Reply: `interrupted` (`true` with {STOP_FIELDS} and `average_speed`; `false` when it was already
    stopped, with `last_stop` and a `note`). An interrupt not answered in time, or a run the
    console started whose frame counter still moves, is `status: INVALID` (`not_settled`): the
    machine stays marked RUNNING, asking again is allowed and nothing counts the attempts, and
    if `stop` fails as well, `close` then `start` is the way out. An interrupt answered by
    something that is not a stop, a connection that failed, or a stop that was read and could
    not be surveyed, is `session_broken`, and it LATCHES as `run_to`'s does. A run by frames
    bailed out as `no_progress` is brought back here: the interrupt is its proof of rest.

    Reference: REFERENCE.md, Advancing the machine.
    """
    return running.stop(*_contact())


@tool("Declare a breakpoint", summary=summaries.breakpoint_at)
def breakpoint_at(ref: str,
                  by: Annotated[str, inputs.vocabulary(breakpoints.BREAKPOINT_BY)] = "auto",
                  role: Annotated[str, inputs.vocabulary(dec.ROLES)] = "stop",
                  condition: str = "", cpu: str = "") -> dict[str, Any]:
    """Declare an execution breakpoint at `ref`, a PLACE in the code, and arm it on a cpu, as a
    `stop` or a `control` (never halts: MAME counts its hits in one of its {TEMPS} `temp`
    variables, read by `run_to`). STORED and re-armed at the next `start`; armed until
    `breakpoint_clear` or `close`.

    Arguments: `ref`, a symbol or a LINEAR `0x` address (`0x4a0`; a `seg:off` is refused). `by`:
    `auto`, `symbol` or `address` only: an expression is never a place here (`expr` and `pointer`
    are refused; a halt when one holds is `regpoint_add`'s). `role`: `stop` or `control`.
    `condition` (a `stop` only): halt only when it holds, in the console's
    grammar, bare numbers hex (`w@DemoLen==0x25`; no `,`, `;`, braces or assignment), kept as
    typed and evaluated once before arming, on the row's cpu (a build without the thread patch
    refuses one on another cpu). `cpu` (`subcpu`): its cpu, else the visible one, which never
    moves; one ref on two cpus is two declarations.

    Refused: a `condition` the console's evaluator refuses or one too long for a packet
    (`command_chars`, `limit_chars`); a cpu the machine lacks (`unknown_ref` with `cpus`); a second
    declaration at an address another holds on its cpu; one ref under the other role; a control
    past the {TEMPS} temps; a row already there it cannot adopt. A refusal stores nothing. A
    name absent from THIS build (not bare hex) is stored `unresolved`. Works on a RUNNING machine
    too (`while_running`).

    Reply: `ref` (the string that clears it), `by`, `role`, `stored`, `already_stored`, `condition`
    (as the console reads it) and `condition_typed` when that differs, `armed`, `state` (`armed`,
    `disabled`, `unresolved` with a `note`), `while_running`, a control's `temp`, and once it
    resolves `addr`, `entry` (the debugger's row), its `cpu`, and a `note` when that cpu is
    ignored. A row `bplist` does not list after the arm is `readback_refused` with the
    declaration KEPT (`armed: false`, `state: gone`).

    Reference: REFERENCE.md, Declarations.
    """
    args.check("breakpoint_at", ref=ref, by=by, role=role, condition=condition)
    return breakpoints.breakpoint_at(_contact()[0], ref, by, role, condition, cpu)


@tool("List the breakpoint declarations", summary=summaries.breakpoint_list, read_only=True)
def breakpoint_list(cpu: str = "") -> dict[str, Any]:
    """Every breakpoint declaration and its state, against the debugger's own `bplist` read back.
    Reply: `breakpoints`, each with `ref`, `by`, `role`, `created_at`, `origin`, `inherited` (true
    for a declaration the store brought back at `start`, false for one made this session), `age_s`
    (whole seconds since `created_at`, unavailable with no date), `condition` and `condition_typed`
    as `breakpoint_at` replies them, `addr`, `hits_since_armed` for an armed control (its count
    since it was armed), `state` (`armed` or `disabled` with its `entry` and `cpu`, `gone` for one
    that owns no row, `stale` for a raw address declared over another build, `aliased` with `why`
    for a declaration from before the one-row rule whose address another declaration owns,
    `unresolved` for a symbol this build lacks, in the ref or in the CONDITION: the latter keeps its
    `addr`, since the ref resolved, as the registerpoint family lists its own), and `foreign`:
    breakpoints the debugger holds that no declaration placed (one typed through `debug`, or a
    `run_to`'s while it runs). Answers on a running machine too, with `last_stop`. `cpu` (`subcpu`;
    left out, every cpu) narrows both to that cpu's rows (`bplist <cpu>`); the reply's `cpu` names
    it, unavailable when none was.

    Reference: REFERENCE.md, Declarations.
    """
    return breakpoints.breakpoint_list(_contact()[0], cpu)


@tool("Clear breakpoint declarations", summary=summaries.breakpoint_clear)
def breakpoint_clear(ref: str = "", cpu: str = "", all: bool = False) -> dict[str, Any]:
    """Clear breakpoint declarations: those named by the `ref` their `breakpoint_at` reply
    carried, or every one with `all=True` and no `ref`, on every cpu or, with `cpu`, on that one
    alone,
    disarming what this server armed for each and reading the debugger's list back. A foreign
    breakpoint is never deleted. Works on a running machine too. `all=True` takes every
    breakpoint declaration of the store `start` named (`declarations.path`): without a
    `state_dir`, other sessions' rows too, listed `inherited` with their `age_s`. An empty `ref`
    is refused.

    Reply: `declarations_cleared`, `disarmed` (the debugger's rows that went), `while_running`.
    A row the debugger still lists after its removal was sent keeps its record, as a
    watch's does, so `disarmed` does not name it and `note` says which row is still held
    and names the `bpclear` that removes it; a stop there is then named by its address.
    Matching: {BREAKPOINT_MATCH}. A `ref` that matches no breakpoint declaration is
    `status: INVALID`, naming the refs held; `all=True` on an empty store is `ok` with 0.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("breakpoint_clear", ref=ref, all=all)
    return breakpoints.breakpoint_clear(_contact()[0], ref, cpu, all)


# --------------------------------------------------------------------------- registerpoints


@tool("Declare a registerpoint", summary=summaries.regpoint_add)
def regpoint_add(condition: str, cpu: str = "") -> dict[str, Any]:
    """Declare a REGISTERPOINT and arm it: the machine stops when `condition` comes true,
    WHEREVER in the program that happens (MAME's own `rpset`, evaluated after every
    instruction). It is for "who puts this value in this register", which needs no address.
    STORED like a breakpoint, with the condition as typed, and re-armed at the next `start`.

    Arguments: `condition`, in the console's grammar that `breakpoint_at` and `run_to` take (bare
    numbers hex: `d1==0x7fff`, `a0==GameState && d0!=0`), a symbol replaced by its address; it
    compares, never assigns, and carries no action. `cpu`: MAME's `rpset` takes none and arms on the
    visible cpu, so another is refused naming `focus`.

    Refused, storing and arming nothing: a condition the console's evaluator refuses, a register
    this cpu lacks included (`bad_argument` in the console's words); one too long for a packet
    (`command_chars`, `limit_chars`); one reading the same as another registerpoint's once its
    symbols are addresses (`ambiguous_ref` naming it); a debugger with no registerpoints
    (`no_channel`). The same condition again is adopted, never a second row. Works on a RUNNING
    machine too: the console takes it and it fires (`while_running`). It marks nothing altered.

    Reply: `ref` (the condition as typed, the string that clears it), `by` (`expr`), `condition`
    (as the console read it), `stored`, `already_stored`, `while_running`, `armed`, `state`
    (`armed`, or `disabled`), `entry` (the debugger's row), `index` and `cpu` (the visible cpu it
    is armed on), with a `note` when the debugger ignores that cpu. A row `rplist` does not list
    after the `rpset` is `readback_refused` with the declaration KEPT (`armed: false`, `state:
    gone`, a `note`). When it fires, the stop's `how` is ``registerpoint '<ref>'`` with
    `regpoint_hit`, and it fires again one instruction on while the condition holds.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("regpoint_add", condition=condition)
    return regpoints.regpoint_add(_contact()[0], condition, cpu)


@tool("List the registerpoint declarations", summary=summaries.regpoint_list, read_only=True)
def regpoint_list(cpu: str = "") -> dict[str, Any]:
    """Every registerpoint declaration and its state, against the debugger's own `rplist` read
    back. Reply: `regpoints`, each with `ref`, `by`, `created_at`, `origin`, `inherited`
    (true for a declaration the store brought back at `start`, false for one made this
    session), `age_s` (whole seconds since `created_at`, unavailable with no date), `condition` (as
    the console reads it now), `state` (`armed` or `disabled` with its `entry`, `index` and
    `cpu`; `gone` for one the debugger no longer lists; `unresolved` for one whose symbol this
    start's build lacks, or with `why` when a symbol now collides with a name the console
    knows), and `foreign`: registerpoints the debugger holds that no declaration placed (one
    typed through `debug`). It has no `addr`, `role`, `stale` or `aliased`: those belong to an
    address, and a registerpoint has none. Answers on a running machine too, with
    `last_stop`. `cpu` (left out, every cpu) narrows both to its rows and is named in `cpu`, as
    `breakpoint_list`'s does.

    Reference: REFERENCE.md, Declarations.
    """
    return regpoints.regpoint_list(_contact()[0], cpu)


@tool("Clear registerpoint declarations", summary=summaries.regpoint_clear)
def regpoint_clear(ref: str = "", cpu: str = "", all: bool = False) -> dict[str, Any]:
    """Clear registerpoint declarations: those named by the `ref` their `regpoint_add` reply
    carried, or every one with `all=True` and no `ref`, on every cpu or on `cpu` alone,
    disarming what this server armed or adopted for it and reading the debugger's list back. A
    foreign registerpoint is never deleted. Works on a running machine too. `all=True` takes every
    registerpoint declaration of the store `start` named, as `breakpoint_clear`'s; an empty
    `ref` is refused.

    Reply: `declarations_cleared`, `disarmed` (the debugger's rows that went), `while_running`.
    A row the debugger still lists after its removal was sent keeps its record, as a
    breakpoint's does, so `disarmed` does not name it and `note` names the `rpclear` that
    removes it. Matching: {REGPOINT_MATCH}. A `ref` that matches no registerpoint declaration
    is `status: INVALID`, naming the refs held; `all=True` on an empty store is `ok` with 0.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("regpoint_clear", ref=ref, all=all)
    return regpoints.regpoint_clear(_contact()[0], ref, cpu, all)


# --------------------------------------------------------------------------------- comments


@tool("Add a comment", summary=summaries.comment_add)
def comment_add(ref: str, text: str, cpu: str = "") -> dict[str, Any]:
    """Put `text` on `ref` of a cpu as a COMMENT: a declaration in the store, and the line MAME's
    own disassembly shows (`disassemble` ends it ` // <text>`). By symbol it follows the symbol
    through a rebuild; by address it is listed `stale` once the build changes. One comment per
    place on a cpu: a second at the same place, in any spelling, replaces the text and keeps the
    first `ref`. Kept per system and symbol file and fed back at the next `start`; with no symbol
    file `declarations.persistent` is false and it dies at `close`.

    Arguments: `ref`, a symbol or a LINEAR `0x` address (`0x4a0`; a `seg:off`, a pointer,
    whitespace or a leading `#` is refused). `text`: one printable line, no tab, no edge spaces,
    at most {COMMENT_TEXT_MAX} UTF-8 bytes; else `bad_argument`, nothing stored. `cpu`: its cpu,
    else the visible one; a comment on another cpu is fed with that cpu made visible and the
    visible one put back (a `note` says so if it cannot be).

    Refused: an address past the cpu's program space; `0x` before anything but hex (a file reads
    `0x` as an address). A name absent from THIS build (not bare hex) is stored `unresolved`. A
    text the console cannot carry (a `"`, a trailing `\\`) is stored and not shown (`unarmable`,
    a `note`). {NEEDS_STOPPED}.

    Reply: `comment` (the row as `comment_list` gives it), `replaced_comments` (the row this
    place held, or empty), `declarations` (`persistent`, `path`: the store), `cpu`, `note`. A store
    that cannot be written: `host_failed` with `held_in_memory: true`.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("comment_add", ref=ref, text=text)
    return comments.comment_add(*_stopped("comment_add"), ref, text, cpu)


@tool("List the comments", summary=summaries.comment_list, read_only=True)
def comment_list(cpu: str = "") -> dict[str, Any]:
    """Every comment of the store, or `cpu`'s, as held and as MAME's pane last took it. Answers on
    a running machine too (with `last_stop`): it asks the machine nothing.

    Reply: `comments`, each with `ref`, `by`, `cpu`, `created_at`, `origin`, `inherited`, `age_s`,
    `text`, `addr` once it resolves, and `state`: `armed` (shown in the pane), `unarmable` (not
    shown, `why`), `unresolved` (a symbol this build lacks) or `stale` (a raw address declared over
    another build); at most {ROWS_SHOWN} rows, with `comments_total` and `truncated` (the whole set
    is `comment_save`'s). Also `declarations` (`persistent`, `path`), and `cpu` (unavailable for
    every cpu).

    Reference: REFERENCE.md, Declarations.
    """
    return comments.comment_list(_contact()[0], cpu)


@tool("Delete a comment", summary=summaries.comment_delete)
def comment_delete(ref: str, cpu: str = "") -> dict[str, Any]:
    """Delete the comment at the place `ref` names on a cpu (the visible one when `cpu` is empty),
    however that comment was spelled, from the store and from MAME's pane. One at a time: `ref`
    is required and an empty one is refused, so unlike the `*_clear` tools there is no
    delete-all (and no `comment_clear`): one place per call.

    Refused: a `ref` that matches no comment there (`unknown_ref`, naming the comments held). The
    store's removal is the fact; a pane line still showing the text (MAME keys a comment by the
    bytes too) is a `note`. {NEEDS_STOPPED}.

    Reply: `deleted` (the row), `declarations` (`persistent`, `path`), `cpu`, `note`. A store that
    cannot be written: `host_failed` with `held_in_memory: true`.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("comment_delete", ref=ref)
    return comments.comment_delete(*_stopped("comment_delete"), ref, cpu)


@tool("Save the comments to a file", summary=summaries.comment_save)
def comment_save(dest: str) -> dict[str, Any]:
    """Write every comment of the store, every cpu, to `dest`, the comment file (REFERENCE.md): a
    header line, then one line per comment, `ref`, `cpu`, `created_at` and `text` separated by
    tabs, sorted, so a project versions it beside its symbol file. Answers on a running machine
    too.

    Arguments: `dest`, {DEST_FILE}. A file there is REPLACED only when it is a comment file this
    server reads whole (the header, then every row by the format); anything else, a directory, a
    link, a FIFO or a device, and the declaration store's own file are refused naming why and left
    as they are.
    A new file is readable by others; a replaced one keeps its mode.

    Reply: `path`, `comments_total` (rows written), `dropped_comments` (each `ref` and `cpu` the
    replaced file held and the store does not, at most {ROWS_SHOWN}), `dropped_total`,
    `truncated`, `note`. A file that cannot be written: `host_failed`.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("comment_save", dest=dest)
    _contact()
    return comments.comment_save(dest)


@tool("Load comments from a file", summary=summaries.comment_load)
def comment_load(path: str) -> dict[str, Any]:
    """Read the comment file at `path` (absolute) into the store and MAME's pane, all or
    nothing: a bad header, a row short of a column, a text or ref that breaks the format, a cpu
    this machine lacks, an address past its space, or one place named twice refuses the whole
    file naming the line. `0x` and hex is an address, anything else a symbol. Where the store
    already comments a place the file comments, the FILE wins; rows only the store holds stay.
    {NEEDS_STOPPED}.

    Reply: `path` (the file read), `parsed` (rows read), `added`, `replaced_comments` (each store
    row the file replaced, whole, at most {ROWS_SHOWN}), `replaced_total`, `truncated`,
    `unchanged` (places already holding the file's text, a stale one brought to this
    build), `comments_total` (the store's after), `declarations` (`persistent`, `path`), `note`. A
    store that cannot be written: `host_failed` with `held_in_memory: true`.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("comment_load", path=path)
    return comments.comment_load(*_stopped("comment_load"), path)


# ----------------------------------------------------------------------------- watches

@tool("Declare a watch", summary=summaries.watch_add)
def watch_add(ref: str, mode: Annotated[str, inputs.vocabulary(dec.WATCH_MODES)],
              length: int = 0, fmt: str = "auto",
              by: Annotated[str, inputs.vocabulary(watches.WATCH_BY)] = "auto",
              cpu: str = "", condition: str = "", trigger: str = "",
              space: Annotated[str, inputs.vocabulary(mspace.SPACES)] = "program",
              trigger_type: Annotated[str, inputs.vocabulary(dec.TRIGGER_TYPES)] = "w",
              ) -> dict[str, Any]:
    """Declare a WATCH at `ref`, in its cpu's byte order. STORED, re-armed at the next `start`.

    Arguments:
    - `mode`: `show` (read at each stop, arms nothing), `change` (a WRITE watchpoint: a write
      stops the machine, and `watch_hit` says WHO WROTE THIS BYTE), `count` (tallies
      every write by value and writer pc, never stopping), `capture` (one
      row per access to `trigger`, never stops) or `expr`
      (`ref` is ONE reading debugger expression, `beamy`: no `,`, `;`, assignment, length or
      fmt).
    - `ref`: a symbol, a `0x` address, or a place through a POINTER (`[base]+0x28`,
      `base->field`), re-resolved each stop; a capture's `ref` is what each row HOLDS.
    - `fmt`: a scalar (`u8` .. `f64`), an array (`u16[8]`), a string
      (`char[16]`) or a struct (`{x:i16,y:i16}`). `auto`: a typed symbol's type, else the WIDEST
      unsigned scalar `length` divides.
    - `length`: TOTAL bytes, REQUIRED unless `fmt` is sized or the symbol is typed; at most
      {WATCH_SHOW_MAX} for a show or capture watch, {READ_MAX} otherwise.
    - `by`: `auto` unless forced.
    - `cpu`: its cpu, else the visible one.
    - `condition` (change only): stop only on a write it holds for (`breakpoint_at`'s grammar
      on the row's cpu; `wpdata` is the value written).
    - `trigger`, `trigger_type` (capture only): the symbol or `0x` address whose WRITES (`w`)
      or READS (`r`: of `ref` itself; no length, fmt or block) make rows.
    - `space`: `io` when `ref` (count) or `trigger` (capture) is a `0x` PORT; session-only.

    Refused: a change watch on an unmapped write; a count range splitting a bus word;
    a ref declared again another way; a range another declaration arms; what the console
    cannot evaluate; an unknown pointer base or `cpu`.
    Works on a RUNNING machine, not through a POINTER (`not_stopped`).

    Reply: `ref`, `by`, `mode`, `stored`, `already_stored`, `armed`, `state`, `while_running`; at a
    place `length`, `fmt`, `addr` once resolved, `pointer` through one, `reading` when stopped; and
    each mode's own fields (REFERENCE.md, Declarations; rows: `watch_list`).

    Reference: REFERENCE.md, Declarations.
    """
    args.check("watch_add", ref=ref, mode=mode, length=length, fmt=fmt, by=by,
               condition=condition, trigger=trigger, space=space, trigger_type=trigger_type)
    if space == mspace.IO:
        return iotaps.watch_add(_contact()[0], ref, mode, length, fmt, by, cpu, trigger)
    return watches.watch_add(_contact()[0], ref, mode, length, fmt, by, cpu, condition, trigger,
                             trigger_type)


@tool("List the watch declarations", summary=summaries.watch_list, read_only=True)
def watch_list(cpu: str = "") -> dict[str, Any]:
    """Every watch declaration and its state, and each io tap (`space: "io"`, `stored: false`).
    Reply: `watches`, each with `ref`, `by`, `created_at`, `origin`, `inherited` (true for one the
    store brought back at `start`), `age_s` (whole seconds since `created_at`, unavailable with no
    date), `mode`, `length`, `fmt`, `addr`, `state`, where it is PLACED (a show or expr watch:
    `evaluated`, or `unresolved`, `null_pointer`; stopped, a show watch adds `reading`, `available`
    with `value` and `raw_hex`, or unavailable with `why`; a change watch: `armed` or `disabled`
    with its `entry`, `cpu` and `values_from`, `gone`, `stale` for a raw address declared over
    another build, `unresolved` (the ref, or a name in its `condition`); a count watch: `tallied`
    with its whole value and writer tables (`total`, `since_last_stop`, `frame_as_of`, `superseded`,
    `across`), `no_dump_yet`, `install_failed` (its `why`), `install_lost` (`install_resent`) or
    `not_installed`; a capture: `captured` with `rows_kept`, `overflow_rows`, `first_rows` (each
    with `frame`, `line` and `time_s`) and `rows_path` (every row), or those same states; both:
    `callback_errors`, `count` and `first`, the times the tap's body raised, which a census beside a
    non-zero count is short of), and `foreign`: watchpoints the debugger holds that this server
    never armed. The debugger's own `wplist` is read back, on a running machine too, where the reply
    adds `last_stop`. `cpu` (`subcpu`; left out, every cpu) narrows both to that cpu's watches
    (`wplist <cpu>`), named in `cpu` (unavailable when none was). `tallies_not_removed` appears when
    a count watch's removal was NOT carried out by the console (`state` `refused`, the console's
    words in its `why`, or `lost`): the tap is still in the guest and this server no longer holds
    its record. It is NEVER resent (the id is the range, so a resend could take a tap declared
    since), and each row repeats on every call until the session ends; its `why` says what declaring
    the range again does.

    Reference: REFERENCE.md, Declarations.
    """
    ses = _contact()[0]
    reply = watches.watch_list(ses, cpu)
    reply["watches"] += iotaps.rows(None, at_stop=False,
                                    cpu=cpus.named(ses, cpu) if inputs.cpu_given(cpu) else None)
    return reply


@tool("Clear watch declarations", summary=summaries.watch_clear)
def watch_clear(ref: str = "", cpu: str = "", all: bool = False,
                space: Annotated[str, inputs.vocabulary(mspace.SPACES)] = "program",
                ) -> dict[str, Any]:
    """Clear watch declarations: those named by the `ref` their `watch_add` reply carried, with
    its `space` (`io` for an io tap's), or every one with `all=True` and no `ref` or `space`, on
    every cpu or on `cpu` alone. Disarms from the debugger what THIS server armed (a show watch
    armed nothing) and reads the list back; a foreign watchpoint is never deleted. Works on a
    running machine too. `all=True` takes every watch declaration of the store `start` named, as
    `breakpoint_clear`'s, and every io tap; an empty `ref` is refused.

    Reply: `declarations_cleared`, `disarmed` (the debugger's rows that went), `while_running`,
    and `tallies_removed` when a count or capture watch went (its removal is SENT to the console
    and applied when the console next reads a line; the record and its files go at once). A row the
    debugger still lists after its removal was sent keeps its record, as a breakpoint's does,
    so `disarmed` does not name it and `note` says which row is still held.
    Matching: {WATCH_MATCH}. A `ref` that matches no watch declaration is `status: INVALID`,
    naming the refs held; `all=True` on an empty store is `ok` with 0.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("watch_clear", ref=ref, all=all, space=space)
    ses = _contact()[0]
    only = cpus.named(ses, cpu) if inputs.cpu_given(cpu) else None
    if space == mspace.IO:
        return iotaps.watch_clear(ses, ref, only)
    reply = watches.watch_clear(ses, ref, cpu, all)
    if all and (gone := iotaps.clear("", only)):
        reply["tallies_removed"] = [*reply.get("tallies_removed", []), *gone]
    return reply


# -------------------------------------------------------------------------------- read

@tool("Look a symbol up", summary=summaries.symbols_find, read_only=True)
def symbols_find(name: str = "", linear: str = "", limit: int = 10,
                 cpu: str = "") -> dict[str, Any]:
    """Look a symbol up in a cpu's table, the one `start` loaded for it: `cpu`'s (`subcpu`),
    else the visible cpu's, named in the reply as `cpu`. One question per call: `name` (exact
    match, else prefix matches ordered by address, up to `limit` (1..{SYMBOLS_MAX}: each symbol
    answered costs the console one `map`), `truncated` saying whether it bit; matched WITHOUT regard
    to case, so `vec_irq1` finds `VEC_IRQ1`), or `linear` (a `0x` address as the debugger shows it:
    what am I inside? The nearest symbol AT OR BELOW and the distance above it, since the table
    carries no sizes).

    `linear` IS THE ADDRESS AT RUN TIME, after `bases`: the one `read_memory`, `disassemble`
    and a stop's `pc` show. It is NOT the `linear` column a linker map prints, which is the
    address BEFORE the bases `start` applied; that column passed here answers a plausible
    symbol with an absurd delta.

    Reply: by name, `query`, `symbols_total` (how many matched) and `symbols` (`name`, `addr`,
    `memory`);
    by address, `linear`, `name`, `addr`, `delta`, `memory`. `memory` is what the address IS
    to the machine, from the console's `map`: `ram` (written and read through memory, a
    change watch fires there), `rom` (nothing writes it: the ROM copy of a datum, or code),
    `latch` (written through a handler, read nowhere: `read_memory` answers zeros there,
    and when the map entry keeps a share, `read_block(ref=...)` reads it), `handlers` (read
    and written through
    handlers, a paired region: readable, not plain memory), `unmapped`; `unknown` on a RUNNING
    machine, where the console cannot be asked (the `note` says so), or where `map` names no
    side. `status: INVALID` with no symbol table (`no_channel`), or for an address below every
    symbol (`unknown_ref`). Answers on a running machine: the table is not a value read off it.

    Reference: REFERENCE.md, Names for addresses.
    """
    args.check("symbols_find", name=name, linear=linear, limit=limit)
    ses, _scratch = _contact()
    on = cpus.chosen(ses, cpu)                  # whose table, and whose map says what it IS
    named = on if inputs.cpu_given(cpu) else None
    # STOPPED, the console says what each address IS (`memory`); running, it cannot be asked.
    kind = None if ses.running else (lambda addr: mmap.memory_kind(ses, addr, named))
    return read.symbols_find(name, linear, limit, kind, on)


@tool("Map the machine", summary=summaries.machine_map, read_only=True, idempotent=True)
def machine_map(cpu: str = "") -> dict[str, Any]:
    """WHAT THE MACHINE IS, rather than what is on it: its cpus and their spaces, every address map
    entry and the share or region it names, the blocks by tag and size, its screens, and its ROM
    files with their crc. Cached at `start()`, so it is free, reads nothing off the machine, alters
    nothing, and answers the same every time. Answers on a RUNNING machine too.

    Arguments: `cpu`, a tag in either spelling (`maincpu` or `:maincpu`), narrows `cpus`, `spaces`,
    `address_map` and `symbol_coverage` to one; the blocks, screens and ROM files stay whole.

    Refused: a tag this machine lacks (`unknown_ref` naming the ones it has); no machine
    (`no_session`); a session that broke (`session_broken`).

    Reply: `cpus` (`cpu`, `type` (MAME's shortname, `m68000`), `name`, `clock_hz`, `spaces`),
    `spaces` (`cpu`, `space`, `data_width_bits`, `endianness`, `entries`, and the space's last
    address `address_mask` where a source backs it),
    `address_map` (`cpu`, `space`, `index`, `start`, `end`, `share` or `region`+`region_offset`
    by the full tag `regions` and `shares` carry, and the ENTRY's own `mirror` and
    `address_mask` when not zero), `regions` and `shares` (`tag`,
    `size`, `bytewidth`, `endianness`), `screens` (`tag`, `width`, `height`, `refresh_hz`,
    `rotation`, `type`), `rom_files` (`name`, `size`, `crc`, `sha1`, `dump_status`, `region`,
    `offset`), `symbol_coverage` (one row per class of each cpu's table: `cpu`, `span`,
    `symbols`, `base`; an empty list when no table has classes), `counts` (each section's full
    count), `truncated` (a boolean: each list section is cut to {LIST_MAX} rows), `sources` (which
    source backs each section; a field none backs is ABSENT), `note` (a disagreement
    between sources, the live value kept; banked ranges; and that this is the machine as `start`
    read it), and `frame_symbol` (the frame counter's name; unavailable, saying what that
    changes, on a board with none).

    Reference: REFERENCE.md, Reading and writing.
    """
    st.refuse_broken(STATE.alive())
    return machine.machine_map(cpu)


@tool("Read memory", summary=summaries.read_memory, read_only=True)
def read_memory(ref: str, length: int = 16, cpu: str = "") -> dict[str, Any]:
    """Read `length` bytes of memory at `ref` (a symbol name or a `0x` address), `length` in
    1..{READ_MAX}, of `cpu` (`subcpu`; the visible one when empty). {CPU_READS}. {SPACE_BOUND}.

    Reply: `addr`, `length`, `hex`, `cpu` (the one read). Above the ceiling the answer
    is `memdump`, which writes to a file: a read comes back as hex text, two characters per byte,
    and a frame of VRAM through it is a haystack in the conversation rather than data. A range whose
    read side is unmapped (a write-only block, `latch` to `symbols_find`) answers ZEROS here with no
    error: the values live in the share behind its handler, and `read_block(ref=...)` reads them.
    {NEEDS_STOPPED}.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("read_memory", ref=ref, length=length)
    return read.read_memory(_stopped("a memory read")[0], ref, length, cpu)


@tool("Read a memory share or region", summary=summaries.read_block)
def read_block(tag: str = "", ref: str = "", offset: inputs.NumberArg = 0, length: int = 16,
               seconds: float = mlua.EVAL_WAIT_S, cpu: str = "",
               ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Read `length` bytes (1..{READ_MAX}) of a memory BLOCK MAME keeps by tag: a SHARE (a block a
    map entry writes through a handler and reads nowhere, so `read_memory` there answers zeros with
    no error and `symbols_find` calls it `latch`) or a REGION (a ROM no cpu's space maps,
    `gfx1` say). It alters nothing.

    Arguments, one block per call: `tag` (as MAME names it, `blitram` or `:blitram`) with `offset`
    ({NUMBER_ARG}) into it, or `ref` (a symbol or `0x` address in the program space) whose
    map entry names the block, the offset then being the address's distance into it; `length`,
    the count asked (left out, a default); `cpu` (`subcpu`) names the cpu whose space `ref` is
    in, the visible one when empty. `seconds`: the wait for the console's answer,
    (0, {WAIT_MAX_S}].

    It goes through MAME's Lua console and costs what `lua` costs, so the read is of the state
    AFTER the instruction at the stop's pc: to read the block as a write there found it, stop one
    instruction earlier. {NEEDS_STOPPED}.

    Reply: `kind` (`share` | `region`), `tag` (the full one), `size`, `bytewidth`, `endianness`,
    `offset`, `length`, `hex`; with `ref` also `addr`, `addr_cpu` and `start` (the entry's first
    address); the console's account as `lua` reports it; then {STOP_FIELDS}.
    INVALID `unknown_ref` when the tag matches none (with `tags`, every block the machine HAS),
    when `ref` is inside no map entry (with `addr`), or when its entry names no block (with
    `map_entry`); `bad_argument` for `offset` beside `ref`, `cpu` beside `tag`, a tag with
    whitespace, and past the block's end, where MAME answers zeros in silence.

    Reference: REFERENCE.md, Reading and writing.
    """
    offset = inputs.as_read(offset)
    args.check("read_block", tag=tag, ref=ref, offset=offset, length=length, seconds=seconds,
               cpu=cpu)
    ses, scratch = _stopped("a block read")
    return block.read_block(ses, scratch, tag, ref, offset, length, seconds, _progress(ctx), cpu)


@tool("Read the registers", summary=summaries.registers, read_only=True)
def registers(from_last_stop: bool = False, cpu: str = "") -> dict[str, Any]:
    """Every register of `cpu` (`subcpu`; the visible one when empty), by the name MAME's gdbstub
    gives it, each printed at its own declared width. {CPU_READS}. {NEEDS_STOPPED}.
    `from_last_stop=True` hands back the registers AS THEY WERE at the last stop, marked
    `superseded: true` with `last_stop` and the `cpu` it stopped on, never as the current value, and
    answers on a running machine; refused before any stop, and beside `cpu`: those are the stop
    survey's.

    Reply: `regs` (name to hex string), `register_bits` (name to the declared width in bits, so a
    16-bit V30 register named `EAX` says 16 rather than leaving it to a digit count) and `cpu` (the
    one read). The names come from the target description: a 68000 board answers
    D0..D7/A0..A5/FP/SP/PS/PC, an x86 or V30 board EAX..GS with EIP. The m68k aliases `A6`, `A7`,
    `SR`, `USP` are accepted by `set_register` but not listed here. A cpu the stub does not describe
    (no register map), or whose byte order is not established, is `no_channel`.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("registers", from_last_stop=from_last_stop, cpu=cpu)
    if from_last_stop:
        return read.registers_at_last_stop(_contact()[0], cpu)
    return read.registers(_stopped("a register read")[0], cpu)


@tool("Disassemble", summary=summaries.disassemble, read_only=True)
def disassemble(ref: str, length: int = 16, cpu: str = "") -> dict[str, Any]:
    """Disassemble `length` BYTES (1..{READ_MAX}) from `ref` of `cpu` (`subcpu`; the visible one
    when empty), as MAME's own `dasm` prints them.

    Reply: `addr`, `length`, `cpu` (the one decoded), `lines` (MAME's text verbatim, one line per
    decoded item; a word MAME could not decode is marked by MAME, `dc.w ...; ILLEGAL`; the listing
    completes the instruction that straddles the end, so it may run a little past `length`), and on
    a board whose table was relocated by `bases`, `resolved`: every DIRECT memory operand (`word ptr
    [0C014h]`) with `line` (its index in `lines`), `operand`, `offset`, and per relocated `class`
    the `linear` address under that base with the nearest `symbol` at or below it and `delta`. THE
    OPERAND AS PRINTED IS THE MAP'S OFFSET, NOT AN ADDRESS: `read_memory` and `watch_add` take
    `linear`. Register-relative operands (`ds1:[bw-31BBh]`, `[ix]`) are not resolved: their address
    is the register's at run time. `flow`, one class per line of `lines` (`call`, `branch`,
    `return`, `sequential`, or `unknown` for a word the table does not list), and `flow_source`,
    where the class came from: `mnemonic_table:<type>` (read off the mnemonic by a table for the
    cpu's MAME type, since MAME's console drops its own step flags), or `none` with a `note`
    saying why no line was classified (no table for the type, or the listing without opcode bytes
    did not come out). A line MAME holds a comment for ends ` // <text>` (`comment_add`).
    `status: INVALID` with `message` when the console wrote no listing, or an empty one.
    {NEEDS_STOPPED}.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("disassemble", ref=ref, length=length)
    return read.disassemble(*_stopped("a disassembly"), ref, length, cpu)


@tool("Find bytes in memory", summary=summaries.find, read_only=True)
def find(data_hex: str, ref: str = "", length: int = 0,
         symbol_class: str = "", cpu: str = "") -> dict[str, Any]:
    """Every address in `length` bytes from `ref` holding the bytes `data_hex` (whole hex bytes,
    two digits each, 1..{FIND_BYTES_MAX} of them: the console takes each byte as a parameter of
    its own), in the program space of `cpu` (`subcpu`; the visible one when empty).

    `symbol_class` searches within a SYMBOL CLASS instead of a hand-counted `ref`+`length`: a class
    name the symbol file carries (`DATA`, `CODE`, ...), whose loaded symbols give the range, so a
    one-byte pattern in DATA skips the CODE where its opcode also lives. The span is that class's
    symbols' [min, max] address; a match PAST the last symbol's own start is not covered, because
    a linker map carries no sizes, so pass `ref`+`length` for an exact range. `symbol_class` with
    `ref` or `length` is refused, and a class the table does not carry is refused naming it.

    Reply: `addr`, `length`, `span` (WHAT WAS EXAMINED, so a zero says over which bytes: `from`,
    `length`, `source` (`class symbols`, with a `note` on the uncovered tail; or `ref+length`)),
    `hits` (hex addresses in address order, at most {LIST_MAX}: when truncated, the HIGHEST
    addresses are kept; a hit is where the pattern STARTS, so one running past the window's end is
    counted), `hits_total` (every hit), `truncated`, `cpu` (the one searched), and `symbol_class`
    when one was given. A console answer other than `Found at <addr>` lines or `Not found` is
    `status: INVALID` with `message`, never a count read off half of it. With neither `symbol_class`
    nor `ref`+`length` the call is refused naming both: there is
    no whole-address-space sweep. {SPACE_BOUND}. {NEEDS_STOPPED}.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("find", data_hex=data_hex, ref=ref, length=length, symbol_class=symbol_class)
    return read.find(_stopped("a memory search")[0], data_hex, ref, length, symbol_class, cpu)


@tool("Start a value scan", summary=summaries.scan_start)
def scan_start(ref: str, length: int,
               cell_bytes: Annotated[int, inputs.vocabulary(mscan.CELL_BYTES)] = 1,
               cpu: str = "") -> dict[str, Any]:
    """Open a VALUE SCAN, the search for a variable no map names, in one cpu's PROGRAM space
    only: there is no `space` argument, and io ports are never scanned. Every cell of
    `cell_bytes` (1, 2 or 4, in the cpu's byte order) from `ref`, for `length` bytes, on `cpu`
    (`subcpu`; the visible one when empty) is a candidate, then `scan_filter` keeps the ones
    that moved as the variable did. `length` counts BYTES whatever the cell (a multiple of
    `cell_bytes`, at most {SCAN_BYTES_MAX}); an odd start is allowed.

    Reply: `addr`, `length`, `cell_bytes`, `hits_total` (the addresses the scan holds),
    `cpu` (bound: every filter reads this cpu whatever is visible later), `space` (`program`).
    The range is read with the console's `save`, through handlers, stepping and writing nothing.
    One scan at a time: a second is `needs_call` naming the open one (its `addr`, `cpu` and
    `hits_total`; `scan_clear` it); it outlives runs, writes,
    `reset` and `state_load`, and dies with `close`. {SPACE_BOUND}. {NEEDS_STOPPED}.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("scan_start", ref=ref, length=length, cell_bytes=cell_bytes)
    ses, scratch = _stopped("a value scan")
    return mscan.scan_start(ses, scratch, ref, length, cell_bytes, cpu)


@tool("Filter the value scan", summary=summaries.scan_filter)
def scan_filter(operator: Annotated[str, inputs.vocabulary(mscan.OPERATORS)] = "=",
                value: inputs.NumberArg | None = None) -> dict[str, Any]:
    """Keep the cells of the open scan whose value satisfies `operator` (`=`, `!` not equal,
    `>`, `>=`, `<`, `<=`, unsigned) against `value` ({NUMBER_ARG}), or, with no
    `value`, against what each
    cell held when `scan_start` opened the scan (`!` keeps a cell that differs from it, `>` one
    larger).

    Reply: `operator`, `value` (`0x` at the cell's width; unavailable without one), `iterations`
    (filters since `scan_start`, this one included), `closed`, `hits` (each `addr` and its `value`
    now, address order), `hits_total` (the survivors), `truncated`, `cpu`, `space`: `hits` whole
    when at most {LIST_MAX} survive, else empty with `truncated` true. None left CLOSES the scan
    (`hits` empty, `hits_total` 0). No scan open, or a value wider than the cell, is `bad_argument`;
    a refused filter leaves the scan as it was. {NEEDS_STOPPED}.

    Reference: REFERENCE.md, Reading and writing.
    """
    value = inputs.as_read(value)
    args.check("scan_filter", operator=operator, value=value)
    ses, scratch = _stopped("a value scan")
    return mscan.scan_filter(ses, scratch, operator, value)


@tool("Clear the value scan", summary=summaries.scan_clear)
def scan_clear() -> dict[str, Any]:
    """End the value scan `scan_start` opened. Reply: `cleared`, with a `note` when none was
    open. It is the server's own state, so it answers on a RUNNING machine.

    Reference: REFERENCE.md, Reading and writing.
    """
    _contact()
    return mscan.scan_clear()


@tool("Instruction history", summary=summaries.history, read_only=True)
def history(limit: int = 32, cpu: str = "") -> dict[str, Any]:
    """The last `limit` (1..{HISTORY_MAX}, MAME's own depth) instructions `cpu` (`subcpu`; the
    visible one when empty) executed before the stop, as MAME's `history` lists them, oldest first.

    Reply: `asked` (the argument), `lines` (MAME's text verbatim, `<addr>: <instruction>`: fewer
    than asked when fewer have retired, one at the boot, none with a `note` for a cpu that has
    retired none), `cpu` (the one whose trail it is). A cpu MAME cannot disassemble is
    `no_channel`; a reply whose lines are not of that shape is `status: INVALID` with `message`,
    never a trail. {NEEDS_STOPPED}.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("history", limit=limit)
    return read.history(_stopped("the instruction trail")[0], limit, cpu)


# ------------------------------------------------------------------------------- write

@tool("Write memory", summary=summaries.write)
def write(ref: str, data_hex: str, cpu: str = "", region: bool = False) -> dict[str, Any]:
    """Write bytes to memory at `ref` of `cpu` (`subcpu`; the visible one when empty) and READ THEM
    BACK through the same cpu. {CPU_READS}. {SPACE_BOUND}. MODIFIES the machine: every later
    reply says so.
    `data_hex` holds 1..{READ_MAX} bytes, `read_memory`'s ceiling: a larger image is loaded from a
    file (`debug("load ...")`).

    `region=True` patches ROM live: the bytes go into the memory REGION that backs the address on
    that cpu's map (the console's `saver` and `loadr`, in the region's own byte order, a partial
    word widened to whole words), then are read back through the cpu. Refused where no region
    backs the address or its offset cannot be placed, and past the entry's or the region's end.
    Never taken on its own: without it a ROM write goes nowhere and says why.

    Reply: `addr`, `bytes_written` (sent), `readback`, `verified` (readback equals what was sent),
    `cpu`, and with `region` the `region`, `region_offset` and any `captures_reading_it`.
    `verified: false` is not always a failure: a hardware register that answers something else is
    doing its job; for RAM the write went nowhere; on ROM the reply adds `target: "rom"`, a `note`,
    and the `region` backing it when the address map can say which. A watched range that cannot be
    re-read afterwards carries the fields above so the landed write is not lost; a read BACK that
    fails carries `addr` and `bytes_written` only. Either is `readback_refused` when the stub
    refused, else `session_broken`. {NEEDS_STOPPED}.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("write", ref=ref, data_hex=data_hex)
    return mwrite.write(*_stopped("a memory write"), ref, data_hex, cpu, region)


@tool("Force a register", summary=summaries.set_register)
def set_register(name: str, value: inputs.NumberArg, cpu: str = "") -> dict[str, Any]:
    """Force the register `name` of `cpu` (`subcpu`; the visible one when empty) to `value`
    ({NUMBER_ARG}) and READ IT BACK. {CPU_READS}. MODIFIES the machine.
    Refuses a name this cpu does not have, naming the ones it has (a 16-bit register also answers
    to its short name: `AX` for the `EAX` a V30 is served under; the reply
    carries the stub's name), and a value wider than the
    register, naming its width.

    Reply: `register`, `value` (what was sent), `readback` (the register read again; both hex at its
    width), `verified` (readback equals what was sent; false is not always a failure: a register
    that masks or answers something else is doing its job), `cpu` (the one forced). A cpu the stub
    does not describe, or whose byte order is not established, is `no_channel`. {NEEDS_STOPPED}.

    Reference: REFERENCE.md, Reading and writing.
    """
    value = inputs.as_read(value)
    args.check("set_register", name=name, value=value)
    return mwrite.set_register(_stopped("a register write")[0], name, value, cpu)


@tool("Reset the machine", summary=summaries.reset)
def reset() -> dict[str, Any]:
    """SOFT reset of the machine, applied, without relaunching the process. MODIFIES the machine.

    Reply: `kind` (`softreset`), `pc` read back after the reset, `boot_pc` (where `start` parked),
    `verified` (the two agree), `frame_at_reset`, `taps_across` (every count or capture watch
    whose totals now span the reset, which each survey then says in `across`), and
    {STOP_FIELDS}: the step that applies
    the reset is a stop of its own, surveyed and recorded like `step`'s, so the next call
    finds nothing to attribute to the machine alone. The console's reset is a timer that
    fires when the machine next runs, so this steps once to apply it. THE FRAME COUNTER
    DOES NOT RESTART, so a frame number after a
    reset is NOT a cold boot's: subtract `frame_at_reset`, the counter read once the reset
    was applied, before comparing a later stop's `frame` with one taken from a cold boot.
    There is no hard reset: it re-creates the machine and the gdbstub connection dies with it,
    which is `close` followed by `start`, and it would save only the process launch, none of
    the emulated time to the screen that matters. {NEEDS_STOPPED}.

    Reference: REFERENCE.md, Reading and writing.
    """
    return mwrite.reset(*_stopped("a reset"))


# ------------------------------------------------------------------------------- files

@tool("Dump memory to a file", summary=summaries.memdump)
def memdump(ref: str, length: int, dest: str, cpu: str = "") -> dict[str, Any]:
    """Write `length` bytes of memory from `ref` of `cpu` (`subcpu`; the visible one when empty) to
    the file `dest`, and CHECK the file.

    Reply: `addr`, `length`, `path`, `bytes`, `cpu` (the one dumped). The dump is written by MAME's
    own console `save`, so the bytes never cross the socket; the file must then be exactly `length`
    bytes and its first bytes must equal a protocol read of the same range (the known-answer
    control), else the reply is `status: INVALID` with `message`; a control read that breaks the
    channel is `session_broken` naming the `path` the file was left at. `dest` must be {DEST_FILE},
    and not there yet. {SPACE_BOUND}. A range that wraps would hang the console's
    `save`, and one past the space never reaches it. The control reads the same cpu, through its own
    thread of the gdbstub's thread patch; a build without it reads only its first cpu, and another
    is refused. Each refusal happens before `save`, so a refused call never leaves a file behind. A
    control read the stub refuses is `readback_refused`; one that breaks the channel is
    `session_broken`, which LATCHES. {NEEDS_STOPPED}.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("memdump", ref=ref, length=length, dest=dest)
    return files.memdump(_stopped("a memory dump")[0], ref, length, dest, cpu)


@tool("Snapshot the screen to a PNG", summary=summaries.snapshot)
def snapshot(dest: str = "") -> dict[str, Any]:
    """Save a PNG of the screen as it is NOW, numbered in the scratch, or moved to `dest`.

    Reply: `path`, `bytes`, `sha256` (of the file, the hash a golden's `checksums.sha256` compares).
    The file must be a complete PNG (signature and IEND trailer) within a short wait, else
    `status: INVALID` with `message`. `dest` must be {DEST_FILE}, and not there yet, judged before
    the console is touched. A SEMANTIC frame is `run_to` the point where the drawer finishes, then
    this; a scratch snapshot dies with `close`, so give a `dest` to keep one. Works on a
    RUNNING machine, which is what a watched run wants.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("snapshot", dest=dest)
    return files.snapshot(*_contact(), dest)


@tool("Signature of the screen", summary=summaries.screen_signature)
def screen_signature(grid: int = 8, seconds: float = mlua.EVAL_WAIT_S,
                     cell: list[int] | None = None, origin: list[int] | None = None,
                     ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """One number for what is on screen: `grid` x `grid` pixels, folded into one hash, so two
    signatures compare and a changed image is a changed number. It answers "is the menu still up"
    without a PNG crossing the conversation; for the exact image, `snapshot`, whose `sha256` is
    the hash a golden compares.

    Arguments: `grid` ({GRID_MIN}..{GRID_MAX}); by default the pixels are the centre of each cell of
    the screen, and with `cell` ([width, height], above zero) and `origin` ([x, y], at or above
    zero) the fixed lattice `origin + index * cell`, which compares with a number a repo's own
    script printed; a lattice that leaves the screen is refused with its size, since MAME reads
    every pixel off it as zero. `seconds`: the wait for the answer, (0, {WAIT_MAX_S}].

    Through the Lua console, so it costs what a `lua` call costs and the screen it reads is the one
    AFTER the instruction at the stop's pc. It does NOT alter the session. {NEEDS_STOPPED}.

    Reply: `signature`, `grid`, `cell`, `origin`, `width`, `height`, the console's account as
    `lua` reports it (`evaluated_by`, `lines_ahead`, `reader_steps`, `resent`, `thread_errors`,
    `console_reruns`, its `note`), `call` (this call's sentinel, `MAME_MCP_LUA_END#N`),
    `pc_before`, then {STOP_FIELDS}. A `wait_expired` says the machine was stepped and nothing was
    altered: the number, when it comes, lands in `log` (channel `process`) as that sentinel
    followed by a tab.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("screen_signature", grid=grid, seconds=seconds, cell=cell, origin=origin)
    return mlua.screen_signature(*_stopped("a screen signature"), grid, seconds, cell, origin,
                                 _progress(ctx))


# ---------------------------------------------------------------------------- graphics

@tool("The live pens of a palette device", summary=summaries.palette)
def palette(palette: str = "", first: inputs.NumberArg = 0, count: int = 0, scale: int = 0,
            dest: str = "",
            seconds: float = mlua.EVAL_WAIT_S,
            ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """The pens of a palette device as MAME holds them NOW, as a table and a swatch ({ROW_PENS}
    a row, the row's first pen in hex at its left): the route to the colours on a board whose colour
    RAM is a write-only RAMDAC. {PICTURE}.

    `palette` (the device's tag, as `gfx_view` takes it; empty: the machine's only palette
    device), `first` and `count` (0: to the end, at most {PALETTE_COUNT_MAX}; `truncated` says
    whether that cap cut it), `scale` and `dest`
    ({PICTURE_ARGS}), `seconds` (the console's wait, (0, {WAIT_MAX_S}]).

    One step, the pens AFTER the instruction at the stop's pc, nothing altered. {NEEDS_STOPPED}.

    Reply: `palette`, `entries`, `first`, `count`, `truncated`, `colors` (`#rrggbb`), `alpha` (when
    a pen is not opaque), `indirect_entries`, `indirect`, `shadows`, `highlights`, `image`, the
    console's account, then the stop's survey. `unknown_ref` (a device it lacks), `ambiguous_ref`
    (several, none named), `no_channel` (none), `bad_argument` (past the last pen, naming
    `entries`).

    Reference: REFERENCE.md, Input and the screen.
    """
    first = inputs.as_read(first)
    args.check("palette", palette=palette, first=first, count=count, scale=scale, dest=dest,
               seconds=seconds)
    return mpalette.palette(*_stopped("a palette read"), palette, first, count, scale, dest,
                            seconds, _progress(ctx))


@tool("The screen as palette indices", summary=summaries.screen_view)
def screen_view(mode: Annotated[str, inputs.vocabulary(mscreen.MODES)] = "render",
                pens: inputs.NumberList | None = None,
                point: list[int] | None = None, crop: list[int] | None = None, scale: int = 0,
                dest: str = "", seconds: float = mlua.EVAL_WAIT_S,
                ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """The screen as the PENS it holds: every pixel's palette index recovered exactly by one Lua
    chunk that encodes each pen as its own index, reads the screen, and puts every pen back,
    proving it did. {PICTURE}; up to 256 pens the PNG is indexed and its index IS the pen.

    `mode`: `render` (the picture; a direct-colour screen shows its colours), `isolate` (to SEE
    where the `pens` you name are, 1..{SCREEN_PENS_MAX}, all in `isolate_color` over the rest in
    grey; `pixels`, `bbox`),
    `histogram` (to COUNT: which pens are used, pixels each as `[pen, pixels]`, and which are
    not, `unused`, as `0xa-0xf` runs; no picture), `pixel`
    (`point` `[x, y]`: `pen`, `color`, and `set_by`, the pen's newest `palette_log` write, same
    step, with `agrees`, or unavailable with why; the picture is a crop round the point,
    `point_in_crop` ringed, in a `border`). `crop` `[x, y, width, height]` narrows all but
    `pixel`. `scale`, `dest` (`pixel` too): {PICTURE_ARGS}.
    `seconds`: (0, {WAIT_MAX_S}].

    One step, the screen AFTER the instruction at the stop's pc, nothing altered. {NEEDS_STOPPED}.

    Reply: `mode`, `screen`, `width`, `height`, `frame_screen`, `palette`, `entries`,
    `screen_indexed` (false: direct colour), `crop`, the
    mode's fields, `image`, the console's account, the survey. `no_channel`: an index mode on a
    direct-colour screen, a vector or LCD screen (`screen_type`), shadows or highlights on, more
    pens than 24 bits name; `no_channel` or `ambiguous_ref`: no screen or several;
    `readback_refused`: a pen not back (a write) or a failed check;
    `bad_argument`: `point` or `crop` off the screen.

    Reference: REFERENCE.md, Input and the screen.
    """
    pen_list = inputs.list_as_read(pens)
    args.check("screen_view", mode=mode, pens=pen_list, point=point, crop=crop, scale=scale,
               dest=dest, seconds=seconds)
    return mscreen.screen_view(*_stopped("a screen read"), mode, pen_list, point, crop, scale, dest,
                               seconds, _progress(ctx))


@tool("Bytes as tiles, under a gfx_layout", summary=summaries.gfx_view)
def gfx_view(layout: dict[str, Any] | str, palette: str = "none", tag: str = "", ref: str = "",
             offset: inputs.NumberArg = 0, first: int = 0, count: int = 0, columns: int = 16,
             pen_base: inputs.NumberArg = 0, scale: int = 0, dest: str = "", cpu: str = "",
             seconds: float = mlua.EVAL_WAIT_S,
             ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Bytes as tiles under a format YOU state in MAME's `gfx_layout` terms, not what a driver
    believes. {PICTURE}; the PNG is indexed, its index the pixel value.

    `layout`: a format's NAME in the loaded manifest, or `width`, `height`, `planes`
    (1..{GFX_PLANES_MAX}), `planeoffset`, `xoffset`, `yoffset`, `charincrement` in BITS, and an
    optional `name`; a value is an integer or a string with `RGN_FRAC(n,d)`, `+`, `-`, `*`, hex;
    a list is a JSON list or a braced string where `STEPn(a,b)` expands. A driver's layout
    transcribes as it is (`total` is `first` and `count`). Plane 0 is the top bit.

    Source: `tag` (a region or share, read whole in its own byte order; `RGN_FRAC` is of all of
    it) with `offset` (bytes), or `ref` (tile 0 in `cpu`'s program space; `count` required);
    `offset` and `pen_base`: {NUMBER_ARG}.
    `first`, `count` (0: what the block holds, at most {GFX_TILES_MAX}), `columns`
    (1..{GFX_COLUMNS_MAX}). `palette`: `none` (grey, not real), a device tag or empty for the only
    one, its pens `pen_base` .. `pen_base + 2^planes - 1` read live. `scale`,
    `dest`: {PICTURE_ARGS}. `seconds`: (0, {WAIT_MAX_S}].

    One step; the state AFTER the stop's instruction; unaltered. {NEEDS_STOPPED}.

    Reply: `layout`, the source, `first`, `count`, `tiles_available`, `columns`, `palette`,
    `pen_base`, `real_colors`, `note`, `image`, the console's account, the survey. `bad_argument`: a
    layout that is not one, tiles past the block, too few pens (`entries`), past {GFX_PIXELS_MAX}
    pixels or a {GFX_BLOCK_MAX}-byte block; `unknown_ref`: a tag, palette or name it lacks.

    Reference: REFERENCE.md, Input and the screen.
    """
    offset = inputs.as_read(offset)
    pen_base = inputs.as_read(pen_base)
    args.check("gfx_view", layout=layout, palette=palette, tag=tag, ref=ref, offset=offset,
               first=first, count=count, columns=columns, pen_base=pen_base, scale=scale,
               dest=dest, seconds=seconds, cpu=cpu)
    return mgfx.gfx_view(*_stopped("a graphics read"), layout, palette, tag, ref, offset, first,
                         count, columns, pen_base, scale, dest, cpu, seconds, _progress(ctx))


@tool("Find a screen patch in a block", summary=summaries.gfx_locate)
def gfx_locate(layouts: list[dict[str, Any] | str], patch: list[int], tag: str = "", ref: str = "",
               offset: inputs.NumberArg = 0, first: int = 0, count: int = 0,
               transparent: inputs.NumberArg | None = None,
               flips: list[Annotated[str, inputs.vocabulary(mlocate.FLIPS)]] | None = None,
               cpu: str = "", seconds: float = mlua.EVAL_WAIT_S,
               ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Search a screen `patch` `[x, y, width, height]` for a block's tiles under `layouts`, a
    LIST of 1..{LOCATE_LAYOUTS_MAX} candidates (plural even for one), each `gfx_view`'s `layout`
    or a `gfx_sweep` candidate's id (`s1c3`): a match proves the format and the tile's place,
    against the screen.

    Every tile-sized window is tried against tiles `first`.. (`count`, 1..{LOCATE_TILES_MAX}; 0:
    all, capped) under `flips` (of `none`, `x`, `y`, `xy`: `["none"]` for a board that never flips a
    tile; all four when absent). A pixel is `base + value`, `base` aligned to `2^planes`, one per
    window: exact or nothing, proving the bank; one-pen windows are counted, not tried. When nothing
    matches so, a PEN MAP is tried (one value per pen, two-bank windows too): its matches carry
    `pen_map` and no `base`. `transparent` (a pixel value) leaves those tile pixels out, proving
    less; nothing is ranked. At most {LOCATE_WORK_MAX} pixel operations
    and {LOCATE_MATCHES_MAX} matches a call. Source: `tag` with `offset` ({NUMBER_ARG}), or `ref` on
    `cpu`, as `gfx_view`'s. `seconds`: (0, {WAIT_MAX_S}].

    One step, altering nothing; kept as `gfx_draft`'s evidence.
    {NEEDS_STOPPED}.

    Reply: `patch`, `screen`, `frame_screen`, `palette`, the source, `transparent`, `flips`,
    `candidates` (counts per layout), `matched`, `matches_total`, `matches` (first
    {LOCATE_MATCHES_SHOWN}: `layout`, `window`, `tile`, `flip`, `base`, `bit`, `byte`, `compared`,
    `ambiguous`, `shape`, `pen_map`), `ambiguous`, `ambiguous_windows`, `pen_map` (unavailable, or
    `tried` with `matches` or `why`); unmatched, `nearest` (`disagree` of `of`, `pixels` `[x, y,
    pen, value]`, `is_a_match: false`, `complete`) or a `note` on why none; `evidence`; the
    console's account, survey. Refusals: `gfx_view`'s and `screen_view`'s capture's, `no_channel`
    for a screen with no pens, `bad_argument`: a patch off the screen or holding no whole tile, or
    past a bound.

    Reference: REFERENCE.md, Input and the screen.
    """
    offset = inputs.as_read(offset)
    transparent = inputs.as_read(transparent)
    args.check("gfx_locate", layouts=layouts, patch=patch, tag=tag, ref=ref, offset=offset,
               first=first, count=count, transparent=transparent, flips=flips,
               seconds=seconds, cpu=cpu)
    return mlocate.gfx_locate(*_stopped("a graphics search"), layouts, patch, tag, ref, offset,
                              first, count, transparent, flips, cpu, seconds, _progress(ctx))


@tool("A block under candidate layouts", summary=summaries.gfx_sweep)
def gfx_sweep(tag: str = "", ref: str = "", offset: inputs.NumberArg = 0,
              count: int = msweep.COUNT_DEFAULT,
              planes: list[Annotated[int, inputs.bounds(1, ml.PLANES_MAX)]] | None = None,
              sizes: list[list[Annotated[int, inputs.vocabulary(msweep.SIDES)]]] | None = None,
              palette: str = "none", pen_base: inputs.NumberArg = 0, scale: int = 0, dest: str = "",
              cpu: str = "", seconds: float = mlua.EVAL_WAIT_S,
              ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """A block no format is known for, drawn under a FIXED family of candidate layouts as ONE
    sheet, each cell labelled with its id (`S1C3`) and what it is; nothing is ranked. {PICTURE}.

    The family: `planes` (depths, default [1, 2, 4]) x `sizes` ([width, height], each side a
    whole number of 8-pixel cells up to {SWEEP_SIDE_MAX}; default [[8, 8]]) x pixel order
    (`rows`; for tiles of several 8x8 cells, `cells across` or `cells down`) x, past one
    plane, `packed`, `planar` or `split` (planes a block fraction apart, `tag` only). At most
    {SWEEP_MAX} candidates, else narrow. `count`: tiles a cell shows (1..{SWEEP_COUNT_MAX},
    default {SWEEP_COUNT}). Source: `tag`, a region or share (`offset` bytes into it,
    {NUMBER_ARG}), or `ref`,
    an address in `cpu`'s program space. Bits a pixel or a tile size the request names go in
    `planes` or `sizes`; leave out what it does not name.
    `palette`: `none` (default, grey), a device tag, or empty for the only one, from
    `pen_base` ({NUMBER_ARG}). `scale`, `dest`: {PICTURE_ARGS}. `seconds`: (0, {WAIT_MAX_S}].

    NEXT: a candidate's id is a layout for `gfx_locate` (against the screen) and `gfx_view`;
    `gfx_draft(choose=...)` records a person's pick.

    One step; unaltered. {NEEDS_STOPPED}.

    Reply: the source, `sweep` (its number), `count`, `palette`, `real_colors`,
    `cell_scale`, `candidates` (`id`, `what`,
    `tiles_available`, `shown`), `next`, `note`, `image`, the
    console's account, the survey. `bad_argument`: past the candidates a sheet holds, a
    block with no whole tile, a sheet past the ceiling; `unknown_ref`: a tag or palette it lacks.

    Reference: REFERENCE.md, Input and the screen.
    """
    offset = inputs.as_read(offset)
    pen_base = inputs.as_read(pen_base)
    args.check("gfx_sweep", tag=tag, ref=ref, offset=offset, count=count, planes=planes,
               sizes=sizes, palette=palette, pen_base=pen_base, scale=scale, dest=dest,
               seconds=seconds, cpu=cpu)
    return msweep.gfx_sweep(*_stopped("a graphics sweep"), tag, ref, offset, count, planes,
                            sizes, palette, pen_base, scale, dest, cpu, seconds, _progress(ctx))


@tool("Draft a gfx.yaml from the evidence", summary=summaries.gfx_draft)
def gfx_draft(dest: str = "", choose: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write a `gfx.yaml` DRAFT from what THIS session proved, and a JSON report beside it
    holding every figure. A format is `proved` on a source by a `gfx_locate` match whose window
    varies along both axes, its rarest pen covering the tile's longer side (or, at 3+ planes,
    its layout's one match in a search of every tile), where no other source matched on that
    frame; two layouts of ONE tile size that both matched there are rivals, and one is proved
    only where an answer that tried both saw it match a window the other missed (else both are
    ambiguous, none written), while layouts of different sizes are each proved on their own;
    `human` when chosen from a sweep's sheet; an asset per source and bank; a command per
    capture watch whose words agree with the located object's x and y on every paired event (one
    window per answer, one row per frame, at one lag for the group, a coordinate stored reversed
    as `sign: -1`). Refused with no evidence.

    `dest`: an absolute `.yaml` in a directory that exists, free of the characters every `dest`
    refuses (the scratch's when empty); an earlier draft there is replaced, anything else there
    (its first line not the DRAFT marker, a link) refused; the report is
    `dest` with `.report.json`, regenerated byte for byte from the same evidence. `choose`:
    `{"candidate": "s1c3", "chosen_by": "<who>"}` records a person's pick first, once however often
    it is made, and not when the draft fails. The draft is loaded
    back before the reply; `gfx_load` takes it and says `draft: true`. {NEEDS_STOPPED}.

    Reply: `manifest` and `report` (`path`, `sha256`), `formats` (name to status),
    `asset_names`, `command_fields` (each command's proved fields), `evidence` (counts),
    `not_proved` (why, first {DRAFT_NOT_PROVED_SHOWN}), `chose`, `confirm`.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("gfx_draft", dest=dest, choose=choose)
    _, scratch = _stopped("a draft")
    return mdraft.gfx_draft(scratch, dest, choose)


@tool("Load the project's graphics manifest", summary=summaries.gfx_load)
def gfx_load(path: str) -> dict[str, Any]:
    """Load a project's `gfx.yaml` (an ABSOLUTE `path`): named `formats` in `gfx_view`'s layout
    terms, `assets` (a region or share read under a format through a palette), draw `commands`
    (the block a capture reads, the write that fires it, the bits each coordinate lives in), and
    `palette_ports` (the ports `palette_log` follows; `ramdacs`, the old name, is read as it).
    Every entry carries `status` (`proved`, `declared`, `human`) and `source`. Held for the
    session; a load replaces the previous one. Answers on a RUNNING machine: it reads nothing
    from it.

    Judged WHOLE before anything is kept: the first unknown key, missing key, wrong type or
    dangling name is `bad_argument` naming its path (a misspelt `maks` is
    `commands.blit.fields.dest_x.parts[1].maks`),
    YAML outside the subset read here names its line, and a manifest that does not list this
    session's `system` is refused. A refusal keeps the manifest loaded before (`still_loaded`).

    Reply: `loaded`, `replaced_path` (the manifest it replaced, unavailable on a first load),
    `path`, `sha256`, `draft` (its first line is `gfx_draft`'s DRAFT marker, deleted to confirm it),
    `systems`, `formats` (name to status), `assets` (`format`, `tag`, `palette`), `commands`
    (`block`, `length`, `trigger_addr`, `fires_with`, `asset`, `roles`, `flags`, `planes`),
    `palette_ports` (`palette`, `protocol`, the ports, `pen_range`), `status_counts`; `note` on the
    old name.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("gfx_load", path=path)
    return manifest.gfx_load(path)


@tool("Blit boxes over the screen", summary=summaries.gfx_blits)
def gfx_blits(draw_command: str, frame: int | None = None, area: list[int] | None = None,
              detail: bool = False, first: int = 0, scale: int = 0, dest: str = "",
              seconds: float = mlua.EVAL_WAIT_S,
              ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """WHO PAINTED THIS AREA: every blit of a `frame`, from the capture the loaded manifest's
    `draw_command` describes, as a box over the screen, one colour per writer pc. {PICTURE}; RGB, a
    picture ABOUT the data (`screen_view` is the data).

    Rows: the capture watch on the command's block triggered by its fire word (none: refused, naming
    the `watch_add`); a blit is a row writing the fire value. `frame`: default the
    newest with blits BEFORE this stop's (the stop's own is still drawn).
    By default a SUMMARY: counts, `legend` by writer, `by_plane`, the picture. `area`
    `[x, y, width, height]` LISTS the blits covering it, in the order drawn, and `topmost`, the
    last of the highest plane; `detail=True` lists every blit. A
    listing is a page of {ROWS_SHOWN} from `first`, `next_first` while more remain.
    `scale`, `dest`: {PICTURE_ARGS}. `seconds`: (0, {WAIT_MAX_S}].

    A box: the destination walk wrapped at its plane's size, moved by the plane's origin from the
    same row, cut to the screen; a paged plane names each blit's `page`. {NEEDS_STOPPED}.

    Reply: `draw_command`, `frame_blit`, `frame_complete`, `rows_cut`, `screen`, `frame_screen`,
    `rows_path`, `rows_kept`, `overflow_rows`, `frames_with_blits`, `callback_errors`,
    `blits_in_frame`, `colors_repeat`, `legend`, `by_plane`, `area`, `covering`, `topmost`,
    `listed` (`first`, `count`, `of`), `next_first`, `blits`, `not_proved`, `note`, `image`, the
    console's account, the survey. `bad_argument`: no manifest, capture or rows; a frame
    with no blit or past the rows kept; a bad `first`;
    `unknown_ref`: a command it lacks.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("gfx_blits", draw_command=draw_command, frame=frame, area=area, detail=detail,
               first=first,
               scale=scale, dest=dest, seconds=seconds)
    return mblits.gfx_blits(*_stopped("a screen read"), draw_command, frame, area, detail, first,
                            scale, dest, seconds, _progress(ctx))


@tool("A blit's source, unscaled", summary=summaries.gfx_blit_source)
def gfx_blit_source(draw_command: str, frame: int | None = None, index: int | None = None,
                    pc: str = "", margin: int = 0, scale: int = 0, dest: str = "",
                    seconds: float = mlua.EVAL_WAIT_S,
                    ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """The rectangle ONE blit reads, decoded from the manifest command's `asset` under the live
    palette. {PICTURE}; with no `margin` it is indexed, its index the pixel value.

    The blit: `frame` (as `gfx_blits`'s) and `index` (its place, as `gfx_blits` lists it) or
    `pc` (the writer, a symbol or `0x`; refused, with the indexes, when it fired more than
    once).
    The rectangle: the source origin (with each field's declared `add`) in tile `source_tile` of
    the asset's format, the destination walk's size, in the tile's own orientation; it wraps
    inside the tile when the asset says `wrap`, else past the edge is refused. Always
    UNSCALED: no blit's zoom or scale registers are applied (the `note` says so).
    `margin` (0..{BLIT_MARGIN_MAX}): pixels shown round it, dimmed, the rectangle ringed:
    `image` is a view (RGB), `data` the exact indexed PNG; `box` places the rectangle.
    `scale`, `dest`: {PICTURE_ARGS}. `seconds`: (0, {WAIT_MAX_S}].

    One step dumps the asset's block and reads its pens; nothing altered. {NEEDS_STOPPED}.

    Reply: `draw_command`, `frame_blit`, `index`, `n`, `blit_pc`, `blit_symbol`, `asset`, `tag`,
    `format`, `palette`, `pen_base`, `rect` (`tile`, `x`, `y`, `width`, `height`, `dir_x`, `dir_y`),
    `margin`, `box`, `wrap`, `destination`, `not_proved`, `reads_source`, `image`, `data`,
    `callback_errors`, a `note`, the console's account, the survey.
    `bad_argument`: `gfx_blits`'s, no `asset` or source roles, a tile past the block, a
    rectangle past the tile or past {GFX_PIXELS_MAX} pixels, a pc that fired none or several;
    `unknown_ref`: a pc naming no symbol.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("gfx_blit_source", draw_command=draw_command, frame=frame, index=index, pc=pc,
               margin=margin, scale=scale, dest=dest, seconds=seconds)
    return mblits.gfx_blit_source(*_stopped("a graphics read"), draw_command, frame, index, pc,
                                  margin, scale, dest, seconds, _progress(ctx))


@tool("Log a palette's port writes", summary=summaries.palette_log)
def palette_log(palette_port: str, pen: inputs.NumberArg | None = None,
                limit: int = mramdac.LIMIT_DEFAULT, clear: bool = False,
                arm: bool = False) -> dict[str, Any]:
    """WHO SET THIS PEN'S COLOUR, on a board whose colour RAM is write-only: every write to the
    ports of the loaded manifest's `palette_port`, placed on its pen by the device's own law
    (`protocol`: `ramdac`, `latch` or `sequence`).

    `arm=True` ARMS the log (`armed_now`), installed when the console next reads a line; a call
    without it READS it; `clear=True` removes it.
    `pen`: that pen alone, whole. `limit` (0..{PALETTE_LOG_LIMIT_MAX}): the newest kept rows shown.
    Answers while RUNNING, from the files the last stop wrote (`superseded` when older).

    A data write lands on no pen (`unsynced_writes`) until the index is known after the arming,
    a reset or a state load. `written_by`: `guest` or `debugger`. The newest write of each pen is
    always kept; the ordered rows, the first {PALETTE_LOG_ROWS_MAX}, the rest counted.

    Reply: `palette_port`, `palette`, `cpu`, `space`, `protocol`, `index_port`, `data_port`,
    `order`, `component_bits`, `pen_range`, `armed_now`, `synced_at_start`, `installed`, `pending`,
    `tally_id`, the console's account, `state`, `frame_as_of`, `superseded`, `across`,
    `writes_total`, `index_writes`, `unsynced_writes`, `partial_writes` (packed), `desyncs`,
    `callback_errors` (`count`, `first`), `sees_reset_and_load`, `rows_kept`, `overflow_rows`,
    `rows_max`, `rows_path`, `pens_written` (`0x10-0x1f` runs); without `pen`, `setters` (each
    writer of a pen's newest write: `pc`, `symbol`, `written_by`, `pens_set` and `which`; the first
    {PALETTE_LOG_SETTERS_MAX}), `setters_total`, `setters_path` (all); with `pen`, `pen_state`
    (`color`, `complete`, `components`, `word` (packed), `writes_total`, `last` with `n`, `frame`,
    `pc`, `symbol`, `written_by`); `rows` (each with its write's `line` and `time_s`: an `index`, a
    data write with `pen`, `component` and `value` or `word` and `mask`, and the `color` it left, or
    a `desync` with its `why`), `rows_cut`, `note`, `not_proved`; `cleared` on a clear.
    `needs_call`: no manifest, no entry, or no log armed; `bad_argument`: a pen it does not set, io
    on a cpu with none; `unknown_ref`: a port.

    Reference: REFERENCE.md, Input and the screen.
    """
    pen = inputs.as_read(pen)
    args.check("palette_log", palette_port=palette_port, pen=pen, limit=limit, clear=clear,
               arm=arm)
    return mramdac.palette_log(_contact()[1], palette_port, pen, limit, clear, arm)


@tool("Film the frames where a write happened", summary=summaries.gfx_film)
def gfx_film(trigger: str = "", length: Annotated[int, inputs.vocabulary(mfilm.LENGTHS)] = 1,
             value: inputs.NumberArg | None = None,
             changed: bool = False, pc: str = "",
             cpu: str = "", frames: int = mfilm.FRAMES_DEFAULT, keep: int = mfilm.KEEP_DEFAULT,
             crop: list[int] | None = None, film_dir: str = "", first: int = 0, clear: bool = False,
             seconds: float = mlua.EVAL_WAIT_S,
             space: Annotated[str, inputs.vocabulary(mspace.SPACES)] = "program",
             ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """THE FRAMES IN WHICH A WRITE HAPPENED, kept inside MAME at emulation speed: a tap marks the
    frame, a notifier judges it and keeps its indexed screen.
    One film per session, gone at `close`; its files stay.

    ARM (STOPPED; reads the screen once, one step): `trigger` (symbol or `0x` on `cpu`), a write
    landing all its `length` bytes (1, 2 or 4) from the instruction at `pc` if given, carrying
    `value` if given ({NUMBER_ARG}), or with `changed=True` a value unlike the one before it (the
    first write is the baseline). `frames` (1..{FILM_FRAMES_MAX}, default {FILM_FRAMES}): frames
    judged, then it finishes. `keep` (1..{FILM_KEEP_MAX}, default {FILM_KEEP}): pictures kept.
    `crop` `[x, y, width, height]`. `film_dir`: a new absolute directory, else the scratch.
    `seconds`: the screen read's wait, (0, {WAIT_MAX_S}]. `space`: `io` for a PORT `trigger` (`0x`
    alone, no `@io`). READ (no `trigger`; answers RUNNING): counts, and a contact sheet of kept
    frames from `first`, as many as fit, each labelled with its frame, hits and first hit (`listed`,
    `next_first`). CLEAR: `clear=True`.

    A picture is read at the next frame that draws, checked against MAME's rendering (`checked`,
    else `why` and `mismatch`).

    Reply (arm): `film`, `armed_now`, `installed`, `pending`, `tally_id`, `trigger_maps_to`, the
    console's account, the survey. Reply (clear): `cleared`, `files_kept`.
    Reply (read): `film`, `installed`, `pending`, `state` (`judging`, `finished`; before its
    first dump, the tap's own, with `why`), `frame_as_of`, `superseded`, `judged`, `judged_frames`,
    `met`, `kept`, `refused` (`refused_frames`), `dropped_total` (`dropped_frames`), `lost` (by
    `reset`, `load`, `skipped`), `callback_errors` (`count`, `first`), `pending_picture`, `cost`,
    `listing_path`, `cells` (`k`, `frame`, `hit_counters`, `hits_in_frame`, `pc`, `symbol`, `value`,
    `path`), `image`, `animation`, `nothing_kept`; with `changed`, `frame_baseline`,
    `baseline_value`. `bad_argument`: a film already armed, none to read, `crop` off the screen, a
    trigger across a bus word.

    Reference: REFERENCE.md, Input and the screen.
    """
    value = inputs.as_read(value)
    args.check("gfx_film", trigger=trigger, length=length, value=value, changed=changed, pc=pc,
               cpu=cpu, frames=frames, keep=keep, crop=crop, film_dir=film_dir, first=first,
               clear=clear, seconds=seconds, space=space)
    ses, scratch = _stopped("arming a film") if mfilm.arms(trigger, clear) else _contact()
    return mfilm.gfx_film(ses, scratch, trigger, length, value, changed, pc, cpu, frames, keep,
                          crop, film_dir, first, clear, seconds, _progress(ctx), space)


@tool("Read the log", summary=summaries.log, read_only=True)
def log(pattern: str, channel: Annotated[str, inputs.vocabulary(files.LOG_CHANNELS)],
        limit: int = 40, labels: bool = False) -> dict[str, Any]:
    """The newest lines of one `channel` of what MAME writes, matching the regex `pattern` (`.`
    for every line; never empty).

    `channel` is `emulator` (`error.log`: what the core and the drivers say through
    `logerror`), `process` (`stdout.log`: the process's own stdout and stderr, where
    `osd_printf_error` and `-verbose` go, a driver's own counters among them) or `all` (both,
    each line tagged `[emulator] ` or `[process] `, with `counts` per source); `guest` names a
    channel an arcade board does not have, and is refused by name.
    `labels=True` adds `labels`, how many returned lines carry each first word (`RE_DAC`,
    `RE_IRQ`): one glance at who is talking.

    PASS A PATTERN THAT NARROWS, always, and treat `.` as a last resort. A driver's own
    `logerror` traffic can run to hundreds of lines per emulated second, so a default-pattern read
    is mostly somebody else's noise
    with the line you want buried in it. The same goes for `drive`'s `pattern`.

    Reply: `pattern`, `channel`, `lines` (the newest `limit` matches, 1..{LIST_MAX}, oldest
    first), `lines_total` (every match in the file), `truncated`. `status: INVALID` with `message`
    when no file of the channel exists yet; a bad `limit`, an unusable regex or an unknown channel
    is refused. Works on a running machine.

    Reference: REFERENCE.md, The log.
    """
    args.check("log", pattern=pattern, channel=channel, limit=limit)
    ses, scratch = _contact()
    reply = files.log(scratch, pattern, limit, channel, labels)
    running.note_throttle_lift(ses, reply.get("lines", []), launch.THROTTLE_MARK)
    return reply


@tool("Wait for a log line", summary=summaries.log_wait, read_only=True)
def log_wait(pattern: str, channel: Annotated[str, inputs.vocabulary(files.LOG_CHANNELS)],
             seconds: float = 30.0,
             ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """WHEN a line of `channel` matching the regex `pattern` (`.` for any; never empty) was
    logged: at once if the log
    already holds it, else wait up to `seconds` for it. The one wait that answers while the
    machine RUNS, and the proof that a run reached what it was meant to reach.

    `channel` as in `log` (`emulator`, `process`, `all`; over `all` the first match in either
    file wins and the line carries its tag).

    Reply: `verdict` `TARGET`, `channel`, `line` (the FIRST match; `log` is the tool for the
    newest), `already` (it was in the log before this call), `waited_s` (0.0 when already),
    `lines_before`, `lines_total`, `arrived_during`, `lines_examined`; when the bound ran out,
    `verdict` `TIMEOUT` with `arrived_during`, `lines_examined`, `waited_s` and a `note` (the
    machine still runs). `status: INVALID`: `wait_stopped` when the machine is STOPPED and the
    log does not already hold the line (a stopped machine logs nothing, so the wait could not
    end; the refusal names `last_stop`, and a stop that lands DURING the wait is reported the
    same way after one last read of the log), `session_broken` (LATCHED) when the emulator
    went away. A
    bad `seconds` (outside (0, {WAIT_MAX_S}]), an unusable regex or an unknown channel is refused.
    Reports its progress while it waits.

    Reference: REFERENCE.md, The log.
    """
    args.check("log_wait", pattern=pattern, channel=channel, seconds=seconds)
    ses, scratch = _contact()
    reply = files.log_wait(
        ses, scratch, lambda: STATE.proc is not None and STATE.proc.poll() is None,
        lambda: running.observe_stop(ses, scratch), pattern, seconds, channel, _progress(ctx))
    line = reply.get("line")
    if isinstance(line, str) and line:
        running.note_throttle_lift(ses, [line], launch.THROTTLE_MARK)
    return reply


# ------------------------------------------------------------------------------- debug

def _step_ops() -> dict[str, Callable[..., dict[str, Any]]]:
    """Op name -> the wrapped tool it dispatches to, built at call time so it names the
    tools by their live registrations rather than a second hand-kept list: every tool but
    the lifecycle (`start`, `close`, `rom_check`) and the two batch tools themselves,
    `perform` and `drive` (the reason is in `perform`'s docstring)."""
    lifecycle = {"start", "close", "rom_check", "perform", "drive"}
    return {t.name: globals()[t.name] for t in mcp._tool_manager.list_tools()
            if t.name not in lifecycle}


@tool("Drive an input and verify it", summary=summaries.drive)
def drive(act: list[dict[str, Any]], expect: str = "", seconds: float | None = None,
          pattern: str = ".", limit: int = 40, settle_seconds: float = 30.0,
          summaries: bool = False, ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """LOOK, ACT, VERIFY in one call: the way a browser is driven, for an arcade board. The
    channel is the EMULATOR log (`error.log`: what the driver and this server's scripts
    `logerror`). The waits inside report their progress.

    The log is MARKED first; `act` (a list of steps in `perform`'s vocabulary, typically
    `input`, `run_for`, `run_to`) runs with `perform`'s rules; with `expect` (a regex; empty
    for none) the call then looks for a matching line since the mark, waiting up to `seconds`
    (default {EXPECT_WAIT_S}, at most {WAIT_MAX_S}) only while the machine RUNS (at a stop the log
    is read once); and `looked.emulator` is what landed since the mark, matching `pattern` (a
    regex, as `log` takes it; NARROW it, since a chatty driver logs hundreds of lines per emulated
    second) and cut to the LAST `limit` (1..{LIST_MAX}, default 40). `settle_seconds` is
    `perform`'s, and
    with an `expect` the act's TAIL does not wait for a stop (the verify is the wait), so a
    trailing `resume` is answered within `seconds`. `summaries` is `perform`'s too, its count and
    its files included. `seconds` with no `expect` is refused.

    Reply: `act` (`ran`, `steps_completed`, `failed`, `failed_at`, `perform`'s tail, and with
    `summaries` its `steps_total`, `truncated`, `ran_path`, `replies_path` and `stops`), `verify`
    (`checked`: whether a check ran at all; `seen`, and `verdict` `TARGET` or `TIMEOUT`; `line`,
    `lines_before`, `lines_total`, `waited_s`; `checked: false` with `why` when no `expect` was
    given; `available: false` when `act.verdict` is `TIMEOUT`), and `looked.emulator`
    (`lines_written`, `lines_total`, `truncated`, `lines`, `since_mark`, `pattern`). INVALID with
    the same `act`, `verify` and `looked` when a step failed (`step_failed`), when a stopped machine
    lacks the line (`wait_stopped`), and before anything ran, whichever argument or step was
    refused (`bad_argument`; `unknown_ref`, with `cpus` for a cpu). No screen in the look: a
    still is `snapshot`, a number for it `screen_signature`.

    Reference: REFERENCE.md, Sequences in one call.
    """
    # IN `drive`'s OWN SHAPE, under `act`: a refusal that arrives before the machine exists must not
    # be a different shape from one that arrives after, whichever check it came from.
    try:
        args.check("drive", act=act, expect=expect, seconds=seconds, pattern=pattern,
                   limit=limit, settle_seconds=settle_seconds, summaries=summaries)
    except st.Invalid as e:
        return sequence.drive_refused(e.code, str(e), pattern, **e.fields)
    refusal = sequence.refuse_act(act, _step_ops(), pattern)
    if refusal is not None:
        return refusal
    ses, scratch = _contact()
    return sequence.drive(ses, scratch, _step_ops(), act, expect, seconds, pattern, limit,
                          settle_seconds, _progress(ctx), summaries=summaries)


@tool("Run a sequence of steps", summary=summaries.perform)
def perform(steps: list[dict[str, Any]], settle_seconds: float = 30.0, summaries: bool = False,
            until_frame: int = 0, ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Run a LIST of the server's own operations in order, in ONE round trip, stopping at the
    first failure with the whole account. A goldens run is one call: a control, then `run_to`
    each marker and `snapshot` it.

    Arguments: `steps`, a non-empty list, each `{"op": <tool name>, ...its arguments}`, any tool but
    `start`, `close`, `rom_check`, `perform` and `drive`. While the machine runs (after a `resume`
    or a run typed through `debug`, or from the start) only running-ok ops go on at once, and before
    the next console op the sequence WAITS up to `settle_seconds` (0..{WAIT_MAX_S}) for the machine
    to stop, proved by the stub's packet or, for a run the console started, by the frame counter.
    `summaries=True` keeps every stop of a long list and counts them: each step but the one that
    matters (last, left running, failing) becomes a compact row; `ran` shows the first {ROWS_SHOWN}
    (`truncated`, of `steps_total`), `ran_path` and `replies_path` all, and `stops` counts the
    stops. `until_frame=F` (with summaries and a `run_for` step) repeats the list until a stop reads
    frame F, within {UNTIL_STEPS_MAX} steps and {WAIT_MAX_S} s: never a list you size; `no_channel`
    with no frame counter.

    Refused before the first step runs: the WHOLE list is checked (ops, argument names, types,
    the values the tools refuse alone, each step's `cpu`, a bare hex ref whose table is known),
    INVALID with `errors` listing EVERY refused step, nothing run. Anything else, at its step.

    Reply: `ran` (each step's `op`, the `cpu` its reply names, and `reply`), `steps_completed`,
    `failed_at` (unavailable on success); on a step's refusal INVALID (`step_failed`) with `failed`
    (`op`, `reply`); once it waited, `verdict`: `TARGET` (a list ending running adds
    `stopped`, the survey) or `TIMEOUT` (the steps after the wait unsent, a `note`); with no
    wait, `not_stopped` before a console step, or `still_running`; `until_frame` and
    `frame_reached`. With several cpus, `visible_cpu` and `visible_cpu_kept`: the list
    puts back the cpu it found, or its last `focus`'s.

    Reference: REFERENCE.md, Sequences in one call.
    """
    args.check("perform", settle_seconds=settle_seconds, summaries=summaries,
               until_frame=until_frame)
    # THE WHOLE LIST, BEFORE THE MACHINE. Nothing in a step's op, argument names or values needs an
    # emulator to be wrong, so the list is checked before the machine is asked for, and a cold
    # server refuses it exactly as a warm one does.
    refusal = sequence.refuse_steps(steps, _step_ops())
    if refusal is not None:
        return refusal
    ses, scratch = _contact()
    sequence.check_until(steps, until_frame)     # after the contact: it judges where the machine is
    return sequence.run_steps(ses, scratch, steps, settle_seconds, _step_ops(), _progress(ctx),
                              summaries=summaries, until_frame=until_frame)


@tool("Debugger console command", summary=summaries.debug)
def debug(command: str) -> dict[str, Any]:
    """Run ANY MAME debugger command, `command` (its only argument), and return its text.
    The read-only recipes have typed tools: prefer them, above all for a command whose answer can
    run past the console's text buffer (`find` or `dump` over a wide range), which takes MAME down.

    Reply: `command`, `mutates`, `output`, `clipped`, and a `note` when there is
    something to say; above {OUTPUT_MAX} characters the text goes to a file (`output_chars`,
    `output_path`, a bounded preview). Every `;` command of a line is judged, each word resolved as
    the console resolves it (the command or the one it prefixes). One that changes the machine
    (`fill`, `load`, `stateload`/`sl`, a reset, `rewind`, `mount`, `do`, any run or console step, an
    assignment such as `d0=1234`) counts as a write and `altered` says so, on the cautious side; a
    comparison, quoted text or a debugger temp alone (`temp9=0`) does not; `source` and an ACTION
    count, by the parameter each command takes it in, braced or bare (a `bp`, `wp`, `rp`, `ep` or
    `trace` line); a bare `suspend`, `resume`, `ignore` or `observe` only lists; a `hardreset` is
    refused unsent (`close` then `start`). A run the console owns (the `g` family, `step N`, `over`,
    `next`) marks the session RUNNING: no stop packet comes for it, so the readers refuse until the
    frame counter proves the stop, and `stop` brings it back. A `focus`, `ignore` or `observe`
    naming a cpu adds `visible_cpu` and `ignored`, read back. A command too long for one packet is
    `bad_argument` (`command_chars`, `limit_chars`), never sent. The console's own error answer
    (`Error in expression`, `unknown command`, `Unable to find device` and its other printed
    refusals) is INVALID (`bad_argument`) quoting its line, with `output` whole, `refused` (by
    `index`, with its `error`) and `not_run` (what a parse error left unexecuted); a `perform` stops
    there.
    {NEEDS_STOPPED}.

    Reference: REFERENCE.md, The console.
    """
    args.check("debug", command=command)
    return mwrite.debug(*_stopped("a console command"), command)


# ----------------------------------------------------------------------------- the Lua channel

@tool("Evaluate Lua on the machine", summary=summaries.lua)
def lua(script: str, seconds: float = mlua.EVAL_WAIT_S, read_only: bool = False,
        ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Evaluate a Lua `script` on MAME's own Lua console (the whole scripting API). THE RAW
    FORM: prefer the typed wrappers (`input`, `record`, `audio_record`, `throttle`, `state_save`,
    `state_load`).

    Arguments: `script`, ONE chunk of at most {SCRIPT_MAX} characters (a `local` on line 1 is seen
    on line 2); only what it `print`s comes back, never a `return` value. `seconds`: the wait for
    its answer, (0, {WAIT_MAX_S}]. `read_only=True` is YOUR word that it only reads: without it the
    call marks the session ALTERED, and nothing verifies the claim (`read_only_claims`).

    It costs steps: the machine is stepped once per line still ahead in the console's pipe plus
    its own, and the script reads the state after the last step (with nothing ahead, AFTER the
    instruction at the stop's pc). More than
    {PIPE_STEPS_MAX} lines ahead is refused, naming `run_for` a frame to drain them. A chunk that
    fails to load or raises is INVALID with the console's own `error:` words; `wait_expired` says
    how many steps were taken, and a late answer lands in `log` (`process`); `reader_died` means
    the script never ran. {NEEDS_STOPPED}.

    Guard the callbacks it installs with `pcall`: a write tap's error goes NOWHERE and the tap
    keeps firing; a notifier's or periodic's is a `[LUA ERROR]` line per call in `log`
    (`process`).

    Reply: `script_chars`, `evaluated_by`, `lines_ahead`, `reader_steps`, `resent`,
    `thread_errors` and `console_reruns` (the reader's deaths, and EARLIER chunks run twice: one
    that wrote, wrote twice), `call` (a lost answer's sentinel in `log`), `pc_before`, `output`
    and `clipped` (`output_chars`, `output_path` for a large one), a `note` (what the console
    did, or nothing printed), then {STOP_FIELDS}.

    Reference: REFERENCE.md, The console.
    """
    args.check("lua", script=script, seconds=seconds)
    return mlua.lua(*_stopped("a Lua script"), script, seconds, read_only, _progress(ctx))


@tool("Hold an input field", summary=summaries.input)
def input(port: str, field: str, value: inputs.NumberArg = 1, frames: int = 4,
          seconds: float = 30.0,
          ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Press an input by NAME, as MAME names it, hold it for `frames` frames of the frame
    counter and release it, then hand the machine back stopped one frame later. Reports its
    progress while it waits.

    Arguments: `port` (the tag, `:P1`), `field` (the field's name: `Coin 1`, `1 Player Start`,
    `P1 Right`), `value` ({NUMBER_ARG}; a digital field is active for any non-zero
    value; an analog one takes a
    value in its own range), `frames` (one or more), `seconds` (the wall-clock bound of the WHOLE
    call, (0, {WAIT_MAX_S}]: every run and every wait for the console inside it takes what is
    left, and a run it has no room left for is `wait_expired`). A press is play, not a write: it
    leaves `altered` as it was. A game that detects an
    EDGE needs a release between two presses: call twice. {NEEDS_STOPPED}; every wrapper but
    `throttle` shares that.

    Reply: the frame run's `verdict`, `frame_before`, `frame_after`, `cycles` and `polls`;
    `lines_ahead`, `drain_steps` and `reader_steps` (the pipe, stepped off BEFORE this script
    is sent, and the steps that cost), the
    console's account (`thread_errors`, `console_reruns`, `resent`, its `note`: see `lua`);
    `route` (`ioport`: set inside the machine), `port`, `field`, `value`, `frames`, `name`,
    `player`, `mask`, `defvalue`, `port_before`, `frame_set`, `released`, `port_held`,
    `frame_released`, `active` (the port READ BACK at the release: false when the press never
    reached it); then {STOP_FIELDS}. A run another stop cuts
    short leaves the field HELD and says so (`released: false`, `frame_release_planned`, a `note`).
    A script the console ran twice is INVALID (`console_rerun`): the field was set twice.

    Reference: REFERENCE.md, Input and the screen.
    """
    value = inputs.as_read(value)
    args.check("input", port=port, field=field, frames=frames, seconds=seconds)
    return mlua.input_field(*_stopped("an input"), port, field, value, frames, seconds,
                            _progress(ctx))


@tool("Record frames to an AVI", summary=summaries.record)
def record(frames: int, dest: str = "", seconds: float = 60.0,
           ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Record exactly `frames` frames of the screen to an AVI, bounded by the frame counter
    (begun and ended by the machine's own frame notifier, so the count is emulated frames and
    not wall time), then hand the machine back stopped. The file is CHECKED before its path
    is given: a finished AVI whose header declares its frames, and zero frames is INVALID.
    `dest` is an absolute path not there yet; empty lands in the scratch, which `close`
    deletes. `seconds` is the wall-clock bound of the whole call, (0, {WAIT_MAX_S}], as `input`'s
    is. Reports its progress while it waits. `frames` is 2 or more: the frame notifier cannot end a
    recording on the call that begins it, so one frame is refused rather than recorded as two.
    {NEEDS_STOPPED}.

    A run cut short leaves the recording OPEN (`ended: false`, `frame_end_planned`), or not begun
    when cut before its first frame (`began: false`, `frame_begin_planned`), with a `note`. Lines
    already in the console's pipe are stepped off before this script is sent, so the frames asked
    for are the recording's own; `lines_ahead` says how deep the pipe was.

    Reply: the frame run's `verdict`, `frame_before`, `frame_after`, `cycles` and `polls`;
    `lines_ahead`, `drain_steps` and `reader_steps`, the console's own account (`thread_errors`,
    `console_reruns`, `resent`, and a `note` when there is something to say: see
    `lua`); `path`, `frames`, `began`, `frame_begin`, `recording_after`, `ended`, `bytes`,
    `avi_frames`, `frame_end`; then {STOP_FIELDS}. A script the console ran twice logs its
    own mark twice, and is `status: INVALID` (`console_rerun`) naming the repeated marks: a
    recording begun twice on one file.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("record", frames=frames, dest=dest, seconds=seconds)
    return mrec.record(*_stopped("a recording"), frames, dest, seconds, _progress(ctx))


@tool("Record the sound to a WAV", summary=summaries.audio_record)
def audio_record(frames: int, dest: str = "", seconds: float = 60.0,
                 ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Record the sound of exactly `frames` frames to a WAV: the mixer's own output, the
    speakers' input mix before any effect, begun and ended by the machine's frame notifier as
    `record`'s AVI is, then hand the machine back stopped. The mixer writes in whole updates, so
    the sound begins and ends up to one update off the frame edges. The file is CHECKED before
    its path is given: a header that agrees with the file, the counter moved by exactly
    `frames`, the emulated span `frames` frame periods, and the samples that span holds at the
    header's rate, within one update. A span with no mixer update, a machine with no speaker,
    or a mixer already recording (an ini naming `wavwrite`) is INVALID; silence is reported
    (`sample_min` equals `sample_max`), never refused. `dest` is an absolute path not there
    yet; empty lands in the scratch, which `close` deletes. `seconds` bounds the whole call,
    (0, {WAIT_MAX_S}]. `frames` is 2 or more. {NEEDS_STOPPED}.

    A run cut short leaves the recording OPEN (`ended: false`, `frame_end_planned`), or not begun
    when cut before its first frame (`began: false`, `frame_begin_planned`), with a `note`. Lines
    already in the console's pipe are stepped off first; `lines_ahead` says how deep it was.

    Reply: the frame run's `verdict`, `frame_before`, `frame_after`, `cycles` and `polls`;
    `lines_ahead`, `drain_steps`, `reader_steps` and the console's own account (see `lua`);
    `path`, `frames`, `began`, `frame_begin`, `recording_after`, `ended`, `bytes`, `channels`,
    `sample_rate_hz`, `samples` (per channel), `emulated_s`, `sample_min`, `sample_max`,
    `frame_end`; then {STOP_FIELDS}. A script the console ran twice is INVALID
    (`console_rerun`).

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("audio_record", frames=frames, dest=dest, seconds=seconds)
    return maudio.audio_record(*_stopped("an audio recording"), frames, dest, seconds,
                               _progress(ctx))


@tool("Switch the throttle", summary=summaries.throttle)
def throttle(on: bool, seconds: float = 5.0,
             ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Switch real-speed throttling `on` or off at a PLACE: stopped at a breakpoint, ask for it
    and `resume`, and the machine runs at real speed from its first frame. The switch is evaluated
    when the Lua console next reads a line ({CONSOLE_READS}), so on a STOPPED machine the reply
    says `pending: true` and names the `mark` `log_wait` can wait for on the `emulator` channel. THE
    MARK'S NUMBER IS THE SESSION'S CONSOLE SEQUENCE, shared with every call that sends the console a
    line, so it counts nothing about throttles; and `log_wait` takes a regex, so close the digits
    (`MAME_MCP_THROTTLE#1(?![0-9])`) or `#1` also matches `#10`. On a RUNNING machine the tool waits
    up to `seconds` ((0, {WAIT_MAX_S}]) for the mark and reports the frame it applied at; one that
    stops before its next frame leaves the switch pending as a stopped one does, and one whose
    bound runs out is `wait_expired`, recorded all the same. `start`'s `throttle_from_frame` is the
    same switch decided at launch.

    A PENDING SWITCH IS COME BACK TO: the next stop's survey, `status` and `close` read the log
    for its mark. One that arrives leaves `status`'s `throttles_pending`; one the console worked
    past without writing puts a row in `session.throttles_not_applied` that REPEATS on every reply
    afterwards, since a caller who never asks again would otherwise measure at a speed nobody
    chose, and so does a machine reporting the OTHER setting (the running path's refusal
    `readback_refused`).

    Reply: `on`, `pending`, `mark`; pending: `applies`, `confirmed_by`; applied: `frame`,
    `waited_s`.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("throttle", on=on, seconds=seconds)
    return mlua.throttle(*_contact(), on, seconds, _progress(ctx))


@tool("Save the machine state", summary=summaries.state_save)
def state_save(name: str) -> dict[str, Any]:
    """Write a savestate `name` (`[A-Za-z0-9_-]`, 1..{STATE_NAME_MAX} characters) through the
    debugger console (`statesave`), under the
    session's state directory (`state_dir/sta`, or the scratch's), and CHECK the file: it
    must appear and open with MAME's own magic. Never overwrites. A save that runs in the
    command alters nothing; one MAME holds is completed by one instruction (REFERENCE.md,
    Saved states).
    Whether the driver restores everything it should is the driver's promise
    (`MACHINE_SUPPORTS_SAVE`); `state_load` measures it with the ROM check, the frame and the
    registers this records.
    {NEEDS_STOPPED}.

    Reply: `name`, `path`, `bytes`, `frame`, `pc`, `errorlog` (what MAME logged meanwhile, as a
    stop's survey carries it), and for a held save `held` (what was stepped, and where the
    machine stopped) and `stop_seq`.

    Reference: REFERENCE.md, Saved states.
    """
    args.check("state_save", name=name)
    return savestates.state_save(*_stopped("a state save"), name)


@tool("List this session's captures", summary=summaries.captures, read_only=True)
def captures() -> dict[str, Any]:
    """Every file `record` (an AVI), `audio_record` (a WAV), `trace` (a `.trace`; its set file is
    not listed), `snapshot` (a PNG) and a graphics tool (an `image`) checked and handed back THIS
    session, in the scratch or at the `dest` they were given, re-read now; a recording its call
    answered still open or not begun is not listed, its path being in that reply. `kind` is the
    extension (`avi`, `wav`, `png`, `trace`) or `image`. `bytes`, and for an AVI the `avi_frames`
    its header declares, for a WAV its `samples`, `channels` and `sample_rate_hz` (each unavailable
    once the file no longer reads as finished, or is gone); a file gone since is listed with
    `present: false` rather than dropped. Answers while the machine runs.

    Reply: `captures` (`kind`, `path`, `present`, `bytes`, `avi_frames`, `samples`, `channels`,
    `sample_rate_hz`).

    Reference: REFERENCE.md, Input and the screen.
    """
    _contact()
    return mrec.captures()


@tool("List the saved states", summary=summaries.state_list, read_only=True)
def state_list() -> dict[str, Any]:
    """Every state under this session's state folder (`sta/<system>` under the `state_dir`
    given to `start`, or the scratch's), with its size and, for a state THIS session wrote,
    the frame and pc `state_save` recorded; a state from an earlier session carries both
    unavailable, as `state_load` reports it, and a `.sta` that is no regular file (a link to
    nothing, a directory, a FIFO) `bytes` too, its `why` saying what is there. A reading of
    a directory: answers while the machine runs.

    Reply: `state_dir`, `states` (`name`, `path`, `bytes`, `frame`, `pc`, each unavailable with
    its `why` when not read).

    Reference: REFERENCE.md, Saved states.
    """
    _contact()
    return savestates.state_list()


@tool("Load a machine state", summary=summaries.state_load)
def state_load(name: str) -> dict[str, Any]:
    """Restore the savestate `name` through the debugger console (`stateload`). It REPLACES
    the machine, so the session is ALTERED from then on. MAME refuses a bad state IN
    SILENCE from the console, so the file's header is judged BEFORE the console (magic, system name,
    and the save signature of the states this session wrote), the ROM is checked again
    against the reference `start` was given, and the stop is surveyed and compared with
    what `state_save` recorded, the frame and pc and every register of every cpu the stub reads:
    `verified` is true, or the reply is INVALID (`readback_refused`) naming the frame and pc or
    carrying `differs` (`cpu`, `register`, `saved`, `loaded`), the stop it surveyed recorded all
    the same. `verified` is `available: false` with its `why` for a state this session did not
    write, a
    machine that already read as the save BEFORE the load (equality after it would prove
    nothing), or a board with no frame counter and no readable register; with no reference image
    held `rom_check` is unavailable with why. A `.sta` that is no regular file (a link to
    nothing, a directory, a FIFO) is `unknown_ref`, never opened. {NEEDS_STOPPED}.

    Reply: `name`, `path`, `rom_check`, `verified`, `saved`, `output` (what the debugger console
    printed for `stateload`, named as `debug` names it), `held` when MAME held the load and one
    instruction completed it (REFERENCE.md, Saved states), `taps_across` as `reset`'s, then
    {STOP_FIELDS}; that `errorlog`
    runs from the last stop, so it includes what MAME logged during the load.

    Reference: REFERENCE.md, Saved states.
    """
    args.check("state_load", name=name)
    return savestates.state_load(*_stopped("a state load"), name)


strict.strict_arguments(mcp)


def main() -> None:
    idle.IDLE.watch(_LOCK, STATE.machine_alive, launch.close)
    try:
        mcp.run()
    finally:
        STATE.kill()


if __name__ == "__main__":
    main()
