"""MCP server owning one live MAME debug session, so questions cost milliseconds.

WHY AN MCP AND NOT A SCRIPT. The expensive part is never the question, it is the state:
each shell command is a fresh process, so a debug session dies between one question and the
next and every follow-up pays another boot, and reaching a late attract screen pays it many
times over, where a query on a session that stays put costs its round trip. An MCP is a
long-lived process that holds that state, which is exactly the missing piece.

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
rule for every tool surface, and two servers of one fleet are where it is easiest to break.

The server knows no game: the system, the ROM paths and the symbol file come from the caller,
and the binary from its argument, `MAME_BINARY` or the PATH, so the same server serves every
project.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import Context
from pydantic import Field
from scry_core import (  # noqa: E402
    log_marks,
    media_tools,
    methods,
    process_name,
    recording,
    reference,
    reply_schema,  # noqa: E402
    screen_map,
    signalled_end,
)
from scry_core import presence as scry_presence  # noqa: E402
from scry_core import (
    scan_vocabulary as words,
)
from scry_core import sequence_account as account  # noqa: E402
from scry_core import steps as core_steps  # noqa: E402
from scry_core import strict_arguments as strict  # noqa: E402
from scry_core import vocabulary as vocab
from scry_core.progress import bridge  # noqa: E402

from scry_mame import (
    advance,  # noqa: E402
    args,  # noqa: E402
    block,  # noqa: E402
    breakpoints,  # noqa: E402
    comments,  # noqa: E402
    cpus,  # noqa: E402
    files,  # noqa: E402
    folds,  # noqa: E402
    idle,  # noqa: E402
    inputs,  # noqa: E402
    iotaps,  # noqa: E402
    launch,  # noqa: E402
    machine,  # noqa: E402
    manifest,  # noqa: E402
    read,  # noqa: E402
    regpoints,  # noqa: E402
    running,  # noqa: E402
    savestates,  # noqa: E402
    sequence,  # noqa: E402
    summaries,  # noqa: E402
    watches,  # noqa: E402
)
from scry_mame import audio as maudio  # noqa: E402
from scry_mame import blits as mblits  # noqa: E402
from scry_mame import cpu_info as mcpu_info  # noqa: E402
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import draft as mdraft  # noqa: E402
from scry_mame import envelope as menvelope  # noqa: E402
from scry_mame import film as mfilm  # noqa: E402
from scry_mame import focus as mfocus  # noqa: E402
from scry_mame import gfx as mgfx  # noqa: E402
from scry_mame import layout as ml  # noqa: E402
from scry_mame import locate as mlocate  # noqa: E402
from scry_mame import lua as mlua  # noqa: E402
from scry_mame import map as mmap  # noqa: E402
from scry_mame import maps as mmaps  # noqa: E402
from scry_mame import palette as mpalette  # noqa: E402
from scry_mame import ramdac as mramdac  # noqa: E402
from scry_mame import recording as mrec
from scry_mame import replies as mame_replies  # noqa: E402
from scry_mame import scan as mscan  # noqa: E402
from scry_mame import screen as mscreen  # noqa: E402
from scry_mame import series as mseries  # noqa: E402
from scry_mame import session as msession  # noqa: E402
from scry_mame import space as mspace  # noqa: E402
from scry_mame import state as st  # noqa: E402
from scry_mame import sweep as msweep  # noqa: E402
from scry_mame import trace as mtrace  # noqa: E402
from scry_mame import write as mwrite  # noqa: E402
from scry_mame.mcp import RECORDER, ROSTER, tool  # noqa: E402
from scry_mame.mcp import mcp as mcp  # noqa: E402  (the probe and the clients read `server.mcp`)
from scry_mame.running import contact, stopped  # noqa: E402
from scry_mame.state import STATE  # noqa: E402


def _given(values: dict[str, Any]) -> dict[str, Any]:
    """A fold's arguments without the protocol's `ctx`."""
    return {k: v for k, v in values.items() if k != "ctx"}

# ----------------------------------------------------------------------------- session

@tool("Start a MAME session", summary=summaries.start, on_cancel="kill")
def start(
    system: str,
    rompath: str,
    reference_rom: str,
    symbols: str | dict[str, str] = "",
    reference_addr: str = "0x0",
    inipath: str = "",
    boot_seconds: Annotated[float, vocab.WAIT_BOUNDS] = 8.0,
    shared: bool = False,
    background: bool | None = None,
    boot_lua: str = "",
    env: dict[str, str] | None = None,
    bases: dict[str, str] | dict[str, dict[str, str]] | None = None,
    reference_base: str = "0x0",
    stub_port: Annotated[int, vocab.bounds(0, launch.PORT_MAX)] = 0,
    state_dir: str = "",
    throttle_from_frame: int = 0,
    types: str | dict[str, str] = "",
    cfg: str = "",
    binary: str = "",
    presence: Annotated[bool, Field(description=scry_presence.ARGUMENT)] = True,
    view: Annotated[str, Field(description=launch.VIEW_ARGUMENT)] = "",
    ctx: Context[Any, Any] | None = None,
) -> dict[str, Any]:
    """Start MAME with its gdbstub, parked STOPPED and checked against the reference image.

    Paths are absolute or `~`-led: `rompath`, `inipath`, `state_dir` directories, the rest
    files. The check: `reference_rom`, `reference_addr`, `reference_base` (`0x`, the image's first
    byte).
    `symbols`, `bases`, `types`: one value, or `{cpu: ...}` per cpu.
    `shared=True`: somebody watches (a window scaled to be seen, real speed).
    `background`: behind, the caller's focus kept; independent of `shared`, whose default it
    follows. `throttle_from_frame`: flat out until it.
    `boot_lua`: a harness file, not Lua text.

    Refused before MAME boots: a live session, an unknown cpu, a class with no base, `bases`
    beside a YAML file, a bad `types` line, a busy `stub_port`, a `reference_addr` outside the
    image (a `shared` start first asks MAME `-listxml`, whose time comes before that refusal).
    A mismatch: `readback_refused`, closed.

    Reply: `system`, `pid`, `stub_port`, `rom_check`, `pc`, `frame`, `start_retries`,
    `recommended_release` ({MAME_RELEASE}); another release boots with a `note` saying so.

    Reference: REFERENCE.md, The session.
    """
    args.check("start", binary=binary, rompath=rompath, reference_rom=reference_rom,
               symbols=symbols, inipath=inipath, boot_lua=boot_lua, state_dir=state_dir,
               cfg=cfg, types=types, view=view)
    return launch.start(binary, system, rompath, reference_rom, symbols, reference_addr,
                        inipath, boot_seconds, shared, boot_lua, env, bases, reference_base,
                        stub_port, state_dir, throttle_from_frame, types, cfg,
                        background=background, presence=presence, view=view,
                        progress=bridge(ctx))


@tool("Session status", summary=summaries.status, read_only=True)
def status() -> dict[str, Any]:
    """Whether a machine is alive, and which one. Safe on a running machine; a stop it finds the
    machine reached on its own is recorded and reported in `stopped_on_its_own`.

    Reply: with no machine, a `note`; alive, `system`, `pid`, `stub_port`, `scratch_dir`,
    `state_dir`, `presence`, `debugger`, `fingerprint` (`fingerprints` per cpu),
    `errorlog_path`, `pc`, `in_debugger` (`breakpoints`, `watches`, `regpoints`: each `ref`,
    `cpu`), `console_pending`, `throttles_pending`, `tallies_pending_removal`. Also
    `last_stop` (`stop_seq`, `pc`, `cpu`, `cause`) and `broken` when the session can no longer
    be trusted: `close`, then `start`.

    Reference: REFERENCE.md, The session.
    """
    return msession.status()


@tool("Close the MAME session", summary=summaries.close, body_session=True, on_cancel="kill")
def close(detail: bool = False, ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """End the session: MAME is asked to `quit` and killed only if it has not gone within the
    grace period. The scratch is deleted; a `state_dir` stays. Works on a running machine;
    with no session it answers `closed: false`.

    Reply: `closed`, `ended_by` (`quit`, `exited`, `killed`, `died`, `none`), `cfg_written`
    (MAME wrote its cfg as it quit),
    `cfg` (`installed_path`, `changed`), `average_speed` (while a `resume` run was open), `note`;
    `stdout_tail` and `errorlog_tail` when the end was not a clean `quit`, or with `detail=True`.
    `session` is the block as it is after the close (`alive` and `running` false); a console doubt
    or a throttle found not applied still rides there.

    Reference: REFERENCE.md, The session.
    """
    return msession.close(bridge(ctx), detail)


@tool("Show another cpu", summary=summaries.focus)
def focus(cpu: str) -> dict[str, Any]:
    """Make `cpu` (`subcpu` or `:subcpu`) the debugger's visible cpu, read back off the console's
    `cpulist`. {NEEDS_STOPPED}.

    With the stub's thread patch nothing runs. Without it the console's `focus` ignores every
    other cpu and may run until `cpu` executes.

    Refused: a cpu the machine lacks (`unknown_ref`); on the patched stub, a cpu the debugger
    ignores (`bad_argument`). A visible cpu read back other than `cpu`: `readback_refused`; a
    console run reaching no stop: `not_settled`.

    Reply: `cpu`, `was`, `via` (`stub` or `console`), `machine_ran`; `frame`, `unchanged`,
    `unread` (stub); `ignored` and, on a run, its survey (console).

    Reference: REFERENCE.md, The session.
    """
    args.check("focus", cpu=cpu)
    return mfocus.focus(*stopped("a focus"), cpu)


@tool("What the debugger sees of each cpu", summary=summaries.cpu_info, read_only=True)
def cpu_info(cpu: str = "") -> dict[str, Any]:
    """What the debugger sees of each cpu now: visibility, ignored or suspended, program counter,
    and the breakpoints, watches and registerpoints declared on it. Moves nothing; answers on a
    running machine.

    Arguments: `cpu`, a tag in either spelling (`subcpu` or `:subcpu`), narrows the rows.

    Refused: a tag no row names (`unknown_ref`); no machine (`no_session`); a broken session
    (`session_broken`).

    Reply: `cpus` (each `cpu`, `visible`, `ignored`, `suspended`, `pc`, `declarations`), `cpu`.

    Reference: REFERENCE.md, The session.
    """
    return mcpu_info.cpu_info(contact()[0], cpu)


@tool("Check the ROM against its image", summary=summaries.rom_check, read_only=True)
def rom_check(
    reference_rom: str, reference_addr: str = "0x0", reference_base: str = "0x0",
    cpu: str = ""
) -> dict[str, Any]:
    """Re-validate the session: 16 bytes at `reference_addr` of `cpu` (empty: the visible one)
    against `reference_rom` at `reference_base`. {NEEDS_STOPPED}.

    A mismatch is `readback_refused`.

    Reply: `rom_check` (`OK`), `deterministic`, `query_s`, `cpu`.

    Reference: REFERENCE.md, The session.
    """
    args.check("rom_check", reference_rom=reference_rom, reference_addr=reference_addr,
               reference_base=reference_base)
    return msession.rom_check(stopped("a known-answer read")[0], reference_rom, reference_addr,
                              reference_base, cpu)


# ----------------------------------------------------------------------------- advance

@tool("Run to a place or a mapped screen", summary=summaries.run_to, on_cancel="stop")
def run_to(ref: str = "", *, control: str = "", screen: str = "",
           seconds: Annotated[float, vocab.WAIT_BOUNDS] = 30.0,
           disarm_watches: bool = False, condition: str = "", cpu: str = "",
           ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Run to `ref` and stop, with a control counting meanwhile.

    `ref` is armed on `cpu` (the visible one when empty). `control` is required with a `ref` or an
    anchored screen: a place known to run, declared as a control on that cpu if it is new
    (`breakpoint_at(role="control")` does the same ahead of time), and the cpu's other declared
    controls count too. `condition`: stop only when it holds, bare numbers hex
    (`w@DemoLen==0x25`). Needs a stopped machine. Refused: an unresolved ref, an empty or
    unresolved control, an over-long `condition`.

    {MAP_RUN_TO}

    Reply: `verdict` (`TARGET`, `TIMEOUT`, `OTHER_STOP`), `control_hits`, `controls` (each `ref`,
    `cpu`, `hits_in_run`; a run to a ref or an anchor), `target_disarmed` (the target was left
    armed or the interrupt went unanswered), `frames` (a screen with no anchor), the
    stop survey (`stop_seq`, `pc`, `regs`, `instruction`, `following` when the listing runs on).
    INVALID has no `verdict`: `control_silent`, `cut_by_other_stop`, `not_settled`, `stale_map`.

    Reference: REFERENCE.md, Advancing the machine.
    """
    args.check("run_to", ref=ref, seconds=seconds, condition=condition, control=control,
               screen=screen)
    if screen:
        return mmaps.run_to_screen(*stopped("a run to a screen"), screen, control, seconds,
                                   bridge(ctx), condition=condition,
                                   disarm_watches=disarm_watches, cpu=cpu)
    return advance.run_to(*stopped("a run to a place"), ref, control, seconds, bridge(ctx),
                          condition=condition, disarm_watches=disarm_watches, cpu=cpu)


@tool("Run for emulated time", summary=summaries.run_for, on_cancel="stop")
def run_for(milliseconds: int = 0, frames: int = 0,
            seconds: Annotated[float, vocab.WAIT_BOUNDS] = 30.0,
            disarm_watches: bool = False, ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Run for `milliseconds` of emulated time or `frames` of the frame counter (exactly one) and
    wait until STOPPED. {NEEDS_STOPPED}.

    Reply: `verdict` (`ELAPSED`, `TIMEOUT`, `OTHER_STOP`; a control never cuts), `frame_before`,
    `frame_after`, `emulated_before_s`, `emulated_after_s`, `cycles` (each unavailable with
    why), `polls` (by frames) or `reads` (by milliseconds), and the stop survey of `run_to`.
    INVALID has no `verdict`: `no_progress`, `frames_went_backwards`, `not_settled`,
    `session_broken`; `no_channel` on a board with no counter.

    Reference: REFERENCE.md, Advancing the machine.
    """
    args.check("run_for", milliseconds=milliseconds, frames=frames, seconds=seconds)
    return advance.run_for(*stopped("a run by time"), milliseconds, seconds, bridge(ctx),
                           disarm_watches=disarm_watches, frames=frames)


@tool("Trace what a run executes", summary=summaries.trace, on_cancel="stop")
def trace(milliseconds: int = 0, frames: int = 0, dest: str = "",
          seconds: Annotated[float, vocab.WAIT_BOUNDS] = 60.0, cpu: str = "",
          noloop: bool = False, ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Run as `run_for` does with MAME's tracer on one cpu, then return the addresses it executed,
    joined to symbols. Window: `milliseconds` or `frames` (at most {TRACE_FRAMES_MAX} frames or
    {TRACE_MS_MAX} ms; `noloop`, {NOLOOP_FRAMES_MAX} and {NOLOOP_MS_MAX}). `dest`: an absolute
    new path. `noloop=True`: exact `count`s, not which addresses ran. Needs a stopped machine.

    Reply: `run_for`'s, plus `trace` (`path`, `set_path`, `instructions`, `addresses`,
    `unplaced`, `symbols` (first {TRACE_SYMBOLS_SHOWN})). Refused: `dest` existing,
    `no_channel`, `readback_refused`.

    Reference: REFERENCE.md, Advancing the machine.
    """
    args.check("trace", milliseconds=milliseconds, frames=frames, dest=dest, seconds=seconds,
               noloop=noloop)
    return mtrace.trace(*stopped("a trace"), milliseconds, frames, dest, seconds, cpu, noloop,
                        bridge(ctx))


@tool("Step instructions", summary=summaries.step, on_cancel="stop")
def step(count: Annotated[int, vocab.bounds(1, advance.step_max())] = 1,
         mode: Annotated[str, vocab.enum(advance.STEP_MODES)] = "into",
         cpu: str = "") -> dict[str, Any]:
    """Execute `count` (1..{STEP_MAX}) instructions of `cpu` (the visible one when empty): `into`
    is one instruction, `over` runs a call to its return as one step. A named cpu is made
    visible first; `others` gives every other cpu's program counter before and after. A stop on
    another cpu ends the steps (`note`). {NEEDS_STOPPED}.

    Reply: `mode`, `instructions_completed`, `others` (on a build with a thread per cpu), and
    the stop survey of `run_to`. A refused `over` may have run: the machine is marked RUNNING,
    and `stop` recovers it. INVALID: `not_settled`, `session_broken`.

    Reference: REFERENCE.md, Advancing the machine.
    """
    args.check("step", count=count, mode=mode)
    return advance.step(*stopped("a step"), count, mode, cpu)


@tool("Resume the machine", summary=summaries.resume, on_cancel="none", replay="wall")
def resume(seconds: Annotated[float, vocab.WAIT_FROM_ZERO_BOUNDS] = 0.0,
           ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Let the machine run. `seconds` 0 (the default) returns at once with no deadline; a bound up
    to {WAIT_MAX_S} waits for a stop and, if none comes, leaves it running. {NEEDS_STOPPED}.

    Reply: with a bound, `waited_s` and `verdict` (`OTHER_STOP` with the stop survey and
    `average_speed`; `TIMEOUT`, left running, with a `note`). INVALID: `session_broken`.

    Reference: REFERENCE.md, Advancing the machine.
    """
    args.check("resume", seconds=seconds)
    return running.resume(*contact(), seconds, bridge(ctx))


@tool("Stop a running machine", summary=summaries.stop, replay="wall")
def stop() -> dict[str, Any]:
    """Stop a running machine where it is and survey the stop.

    Reply: `interrupted` (`true` with the stop survey and `average_speed`; `false` when already
    stopped, with a `note`). INVALID: `not_settled` (the machine stays marked RUNNING; ask
    again), `session_broken`.

    Reference: REFERENCE.md, Advancing the machine.
    """
    return running.stop(*contact())


@tool("Declare a breakpoint", summary=summaries.breakpoint_at)
def breakpoint_at(ref: str,
                  by: Annotated[str, vocab.enum(breakpoints.BREAKPOINT_BY)] = "auto",
                  role: Annotated[str, vocab.enum(dec.ROLES)] = "stop",
                  condition: str = "", cpu: str = "") -> dict[str, Any]:
    """Declare an execution breakpoint at `ref`, a place in the code, as a `stop` or a `control`
    (never halts; hits counted in a `temp`, {TEMPS} at most, read by `run_to`). Stored,
    re-armed at `start`.

    `ref`: a symbol or linear `0x` address, never an expression. `condition` (a `stop` only):
    console grammar, bare numbers hex, no `,`, `;`, braces or assignment. `cpu`: else the
    visible one.

    Refused: a `seg:off`; a `condition` the console refuses or too long (`command_chars`); an
    unknown cpu (`unknown_ref`); an address another declaration holds; one ref under the other
    role; a control past the {TEMPS} temps.

    Reply: `ref`, `stored`, `already_stored`, `armed`, `state`, `temp` (a control), `addr`,
    `entry` (once `ref` resolves).

    Reference: REFERENCE.md, Declarations.
    """
    args.check("breakpoint_at", ref=ref, by=by, role=role, condition=condition)
    return breakpoints.breakpoint_at(contact()[0], ref, by, role, condition, cpu)


@tool("List the declarations", summary=summaries.declaration_list, read_only=True)
def declaration_list(kind: Annotated[str, vocab.enum(("", *folds.KINDS))] = "",
                     cpu: str = "") -> dict[str, Any]:
    """List the declarations of `kind` (empty: every kind) with their state, against the
    debugger's own list read back. `cpu` narrows the rows to it. Answers on a running machine.

    Reply: `breakpoints`, `regpoints`, `watches` (each kind asked; each row `ref`, `by`,
    `cpu`, `created_at`, `origin`, `inherited`, `age_s`, `state`, plus its kind's fields),
    `foreign` (debugger rows no declaration placed), `cpu`.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("declaration_list", kind=kind)
    return folds.list_declarations(kind, cpu)


@tool("Clear declarations", summary=summaries.declaration_clear)
def declaration_clear(kind: Annotated[str, vocab.enum(folds.KINDS)], ref: str = "",
                      cpu: str = "", all: bool = False,
                      space: Annotated[str, vocab.enum(mspace.SPACES)] = "program",
                      ) -> dict[str, Any]:
    """Clear the declarations of `kind` that `ref` names (as its declaring reply gave it), or
    every one with `all=True` and no `ref`, on `cpu` or every cpu. Disarms what this server
    armed; a foreign row is never deleted. `space="io"` clears a watch's io tap. Works on a
    running machine.

    Refused: an empty `ref` without `all`; a `ref` matching none (`unknown_ref`, naming the
    refs held); `space` for a kind other than `watch`.

    Reply: `declarations_cleared`, `disarmed`, `while_running`, `tallies_removed` (removing an io
    tap), `note`.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("declaration_clear", kind=kind, ref=ref, all=all, space=space)
    return folds.clear_declarations(kind, ref, cpu, all, space)




# --------------------------------------------------------------------------- registerpoints


@tool("Declare a registerpoint", summary=summaries.regpoint_add)
def regpoint_add(condition: str, cpu: str = "") -> dict[str, Any]:
    """Declare a registerpoint: the machine stops when `condition` comes true, wherever in the
    program ("who puts this value in this register"). Stored, re-armed at `start`.

    `condition`: console grammar, bare numbers hex (`d1==0x7fff`); compares, never assigns.
    `cpu`: only the visible one; another is refused naming `focus`.

    Refused: a condition the console refuses (`bad_argument`) or too long (`command_chars`,
    `limit_chars`); one equal to another registerpoint's (`ambiguous_ref`); a debugger with no
    registerpoints (`no_channel`).

    Reply: `ref` (the condition as typed), `stored`, `already_stored`, `armed`, `state`,
    `while_running`, `entry`, `cpu`, `note`.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("regpoint_add", condition=condition)
    return regpoints.regpoint_add(contact()[0], condition, cpu)




# --------------------------------------------------------------------------------- comments



@tool("List the comments", summary=summaries.comment_list, read_only=True)
def comment_list(cpu: str = "") -> dict[str, Any]:
    """Every comment of the store, or `cpu`'s. Answers on a running machine too.

    Reply: `comments` (each `ref`, `text`, `addr`, `state`; at most {ROWS_SHOWN}),
    `comments_total`, `truncated`, `declarations`, `cpu`.

    Reference: REFERENCE.md, Declarations.
    """
    return comments.comment_list(contact()[0], cpu)


@tool("Write the comments", summary=methods.fold_line("comment_write", folds.COMMENT),
      replay="drop")
def comment_write(method: Annotated[str, vocab.enum(tuple(folds.COMMENT))], ref: str = "",
                  text: str = "", cpu: str = "", dest: str = "", path: str = ""
                  ) -> dict[str, Any]:
    """Change the store's comments.

    `add`: `text` (one printable line, at most {COMMENT_TEXT_MAX} UTF-8 bytes) on `ref`,
    a symbol or a linear `0x` address, of `cpu` (default the visible one); a second there
    replaces it.
    Reply: `comment`, `replaced_comments`, `declarations`, `cpu`, `note`.

    `delete`: the comment at `ref`. Reply: `deleted`, `declarations`, `cpu`, `note`.

    {COMMENT_SAVE}

    {COMMENT_LOAD}

    `add`, `delete` and `load` need the machine stopped. Refused: an argument the method
    does not take, a misshapen `ref` or `text`, an unknown `ref` (`unknown_ref`), a `save`
    `dest` that is the declaration store's file (compared without regard to case, on any
    volume), an unwritable store (`host_failed`, `held_in_memory`).

    Reference: REFERENCE.md, Declarations.
    """
    args.check("comment_write", **_given(locals()))
    return methods.dispatch(folds.COMMENT, locals())





# ----------------------------------------------------------------------------- watches

@tool("Declare a watch", summary=summaries.watch_add)
def watch_add(ref: str, mode: Annotated[str, vocab.enum(dec.WATCH_MODES)],
              length: int = 0, fmt: str = "auto",
              by: Annotated[str, vocab.enum(watches.WATCH_BY)] = "auto",
              cpu: str = "", condition: str = "", trigger: str = "",
              space: Annotated[str, vocab.enum(mspace.SPACES)] = "program",
              trigger_type: Annotated[str, vocab.enum(dec.TRIGGER_TYPES)] = "w",
              ) -> dict[str, Any]:
    """Declare a watch at `ref`. Stored, re-armed at `start`.

    `mode`: `show` (read at each stop), `change` (a write stops the machine), `count` (tallies
    writes), `capture` (rows at `trigger`), `expr` (one debugger expression). `ref`: a symbol,
    `0x` address or pointer place (`base->field`; stopped machine only). `fmt`: a scalar (`u8`
    .. `f64`), an array (`u16[8]`), a string (`char[16]`) or a struct (`{x:i16,y:i16}`).
    `length`: total bytes, needed unless `fmt` is sized or the symbol typed; at most
    {WATCH_SHOW_MAX} for show or capture, {READ_MAX} otherwise. `condition`: change only.
    `trigger`, `trigger_type`: capture only; a capture of reads (`r`) takes no `length` or
    `fmt`. `space="io"`: a port tap, `count` or `capture` only, for this session only (never
    stored).

    Refused: a change watch on an unmapped write; a count range splitting a bus word; a ref
    declared another way; an unknown pointer base or `cpu`.

    Reply: `ref`, `mode`, `stored`, `already_stored`, `armed`, `state`, `reading` (on a stopped
    machine), and each mode's own fields.

    Reference: REFERENCE.md, Declarations.
    """
    args.check("watch_add", ref=ref, mode=mode, length=length, fmt=fmt, by=by,
               condition=condition, trigger=trigger, space=space, trigger_type=trigger_type)
    if space == mspace.IO:
        return iotaps.watch_add(contact()[0], ref, mode, length, fmt, by, cpu, trigger)
    return watches.watch_add(contact()[0], ref, mode, length, fmt, by, cpu, condition, trigger,
                             trigger_type)




# -------------------------------------------------------------------------------- read

@tool("Look a symbol up", summary=summaries.symbols_find, read_only=True)
def symbols_find(name: str = "", linear: str = "",
                 limit: Annotated[int, vocab.bounds(1, read.SYMBOLS_LIMIT_MAX)] = 10,
                 cpu: str = "") -> dict[str, Any]:
    """Look a symbol up in the table `start` loaded for `cpu`, else the visible cpu. One question
    per call: `name` (exact, else prefix matches by address, case-insensitive, up to `limit`
    1..{SYMBOLS_MAX}), or `linear`, a `0x` run-time address as `disassemble` shows it, not a
    linker map's column: the nearest symbol at or below, and the distance. Works while running.

    Refused: no table (`no_channel`); an address below every symbol (`unknown_ref`).

    Reply: by name, `query`, `symbols_total`, `symbols` (`name`, `addr`, `memory`), `truncated`;
    by address, `linear`, `name`, `addr`, `delta`, `memory`; and `cpu`, `note`.

    Reference: REFERENCE.md, Names for addresses.
    """
    args.check("symbols_find", name=name, linear=linear, limit=limit)
    ses, _scratch = contact()
    on = cpus.chosen(ses, cpu)                  # whose table, and whose map says what it IS
    named = on if inputs.cpu_given(cpu) else None
    # STOPPED, the console says what each address IS (`memory`); running, it cannot be asked.
    kind = None if ses.running else (lambda addr: mmap.memory_kind(ses, addr, named))
    return read.symbols_find(name, linear, limit, kind, on)


@tool("Map the machine", summary=summaries.machine_map, read_only=True, idempotent=True)
def machine_map(cpu: str = "",
                sections: list[Annotated[str, vocab.enum(machine.MAP_SECTIONS)]] | None = None,
                ) -> dict[str, Any]:
    """What the machine is: its cpus and spaces, address map, regions, shares, screens and ROM
    files. Cached at `start()`, free; answered on a running machine.

    Arguments: `cpu`, a tag in either spelling, narrows `cpus`, `spaces`, `address_map` and
    `symbol_coverage`. `sections` picks sections; left out, all but `rom_files`.

    Refused: an empty or unknown `sections` (`bad_argument`); an unknown tag (`unknown_ref`); no
    machine (`no_session`); a broken session (`session_broken`).

    Reply: `cpus`, `spaces`, `address_map`, `regions`, `shares`, `screens`, `rom_files`,
    `symbol_coverage`, `counts`, `truncated` (lists are cut to {LIST_MAX} rows), `sources`,
    `note`, `frame_symbol`. A field no source backs is absent.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("machine_map", sections=sections)
    st.refuse_broken(STATE.alive())
    return machine.machine_map(cpu, sections)


@tool("Read memory", summary=summaries.read_memory, read_only=True, replay=("hex",))
def read_memory(ref: str, length: Annotated[int, vocab.bounds(1, read.READ_MAX)] = 16,
                cpu: str = "") -> dict[str, Any]:
    """Read `length` bytes (1..{READ_MAX}) at `ref` (a symbol or `0x` address) of `cpu` (`subcpu`;
    the visible one when empty). A range past the cpu's program space is `bad_argument`.

    Reply: `addr`, `length`, `hex`, `cpu`. Above the ceiling use `memdump`. A write-only range
    (`latch`) answers zeros with no error: use `read_block`.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("read_memory", ref=ref, length=length)
    return read.read_memory(stopped("a memory read")[0], ref, length, cpu)


@tool("Read a memory share or region", summary=summaries.read_block, on_cancel="none",
      replay=("hex", "pc", "frame"))
def read_block(tag: str = "", ref: str = "", offset: inputs.NumberArg = 0,
               length: Annotated[int, vocab.bounds(1, read.READ_MAX)] = 16,
               seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
               cpu: str = "",
               ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Read `length` bytes (1..{READ_MAX}) of a block MAME keeps by tag: a share (what
    `symbols_find` calls `latch`) or a region (a ROM no cpu maps).

    `tag` (`blitram` or `:blitram`) with `offset`, or `ref` whose map entry names the block;
    `cpu` names `ref`'s space; `seconds` bounds the console's answer.

    Reply: `kind`, `tag`, `size`, `bytewidth`, `endianness`, `offset`, `length`, `hex`; with
    `ref` also `addr`, `addr_cpu`, `start`; then the stop survey. `unknown_ref`: no such tag
    (`tags` lists them) or `ref` in no entry naming a block. `bad_argument`: `offset` with
    `ref`, `cpu` with `tag`, past the block's end.

    Reference: REFERENCE.md, Reading and writing.
    """
    offset = inputs.as_read(offset)
    args.check("read_block", tag=tag, ref=ref, offset=offset, length=length, seconds=seconds,
               cpu=cpu)
    ses, scratch = stopped("a block read")
    return block.read_block(ses, scratch, tag, ref, offset, length, seconds, bridge(ctx), cpu)


@tool("Read the registers", summary=summaries.registers, read_only=True, replay=("regs",))
def registers(from_last_stop: bool = False, cpu: str = "") -> dict[str, Any]:
    """Every register of `cpu` (`subcpu`; the visible one when empty), by the gdbstub's name.
    `from_last_stop=True` returns the registers as of the last stop, answers on a running
    machine, and is refused before any stop and beside `cpu`.

    Reply: `regs` (name to hex string), `register_bits` (name to declared width), `cpu`,
    `superseded` (with `from_last_stop`). A cpu with no register map or an unknown byte order is
    `no_channel`.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("registers", from_last_stop=from_last_stop, cpu=cpu)
    if from_last_stop:
        return read.registers_at_last_stop(contact()[0], cpu)
    return read.registers(stopped("a register read")[0], cpu)


@tool("Disassemble", summary=summaries.disassemble, read_only=True)
def disassemble(ref: str, length: Annotated[int, vocab.bounds(1, read.READ_MAX)] = 16,
                cpu: str = "") -> dict[str, Any]:
    """Disassemble `length` bytes (1..{READ_MAX}) from `ref` of `cpu` (`subcpu`; the visible one
    when empty), as MAME's `dasm`; the last instruction is completed.

    Reply: `addr`, `length`, `cpu`, `lines`, `flow` (per line: `call`, `branch`, `return`,
    `sequential`, `unknown`), `flow_source`, `note`, and on a relocated board `resolved` (per
    direct memory operand: `line`, `operand`, `offset`, `linear`, `symbol`, `delta`). The
    printed operand is the map's offset: `read_memory` and `watch_add` take `linear`.
    Register-relative operands are not resolved.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("disassemble", ref=ref, length=length)
    return read.disassemble(*stopped("a disassembly"), ref, length, cpu)


@tool("Find bytes in memory", summary=summaries.find, read_only=True)
def find(data_hex: str, ref: str = "", length: int = 0,
         symbol_class: str = "", cpu: str = "") -> dict[str, Any]:
    """Every address in `length` bytes from `ref` holding `data_hex` (whole hex bytes,
    1..{FIND_BYTES_MAX}), in the program space of `cpu` (`subcpu`; the visible one when empty).

    `symbol_class` (`DATA`, `CODE`...) replaces `ref`+`length` with that class's symbol range,
    which misses a match past the last symbol's start. Both, neither, or an unknown class is
    refused. A range past the program space is `bad_argument`.

    Reply: `addr`, `length`, `span` (`from`, `length`, `source`), `hits` (at most {LIST_MAX},
    highest kept), `hits_total`, `truncated`, `cpu`, `symbol_class`. An unreadable console
    answer is `status: INVALID`.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("find", data_hex=data_hex, ref=ref, length=length, symbol_class=symbol_class)
    return read.find(stopped("a memory search")[0], data_hex, ref, length, symbol_class, cpu)


@tool("Value scan", summary=methods.fold_line("scan", folds.SCAN), replay="drop")
def scan(method: Annotated[str, vocab.enum(tuple(folds.SCAN))], ref: str = "",
         length: int | None = None,
         cell_bytes: Annotated[int, vocab.enum(mscan.CELL_BYTES)] | None = None, cpu: str = "",
         operator: Annotated[str, vocab.enum(mscan.OPERATORS)] | None = None,
         value: inputs.NumberArg | None = None,
         limit: Annotated[int, vocab.bounds(1, words.HITS_MAX)] | None = None
         ) -> dict[str, Any]:
    """Value scan: find a variable no map names, in one cpu's program space only, no io
    ports. One scan at a time; it outlives runs, writes, `reset` and state loads; `close`
    ends it.

    `start`: every cell of `cell_bytes` from `ref` on `cpu` is a candidate;
    `length` counts bytes, at most {SCAN_BYTES_MAX}. Reply: `addr`, `length`, `cell_bytes`,
    `hits_total`, `cpu`, `space`.

    `filter`: keep the cells whose value satisfies `operator` (`=` default) against
    `value` ({NUMBER_ARG}), or with no `value` against what each held at `start`; none left
    closes the scan. Reply: `operator`, `value`, `iterations`, `closed`, `hits` (the first
    `limit`, default {HITS_DEFAULT}), `hits_total`, `truncated`, `cpu`, `space`.

    `clear`: end the scan. Reply: `cleared`, `note`.

    Refused: an argument the method does not take; a second `start` or no scan open
    (`needs_call`); a range past the cpu's program space (`bad_argument`).

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("scan", **_given(locals()))
    return methods.dispatch(folds.SCAN, locals())





@tool("Instruction history", summary=summaries.history, read_only=True)
def history(limit: Annotated[int, vocab.bounds(1, read.HISTORY_MAX)] = 32,
            cpu: str = "") -> dict[str, Any]:
    """The last `limit` (1..{HISTORY_MAX}) instructions `cpu` retired before the stop, oldest
    first.

    Reply: `asked`, `lines` (`<addr>: <instruction>`), `cpu`, `note`. No disassembler:
    `no_channel`.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("history", limit=limit)
    return read.history(stopped("the instruction trail")[0], limit, cpu)


# ------------------------------------------------------------------------------- write

@tool("Write memory", summary=summaries.write)
def write(ref: str, data_hex: str, cpu: str = "", region: bool = False) -> dict[str, Any]:
    """Write bytes to memory at `ref` of `cpu` and read them back through it; needs the machine
    stopped.

    `data_hex` is 1..{READ_MAX} bytes. `region=True` patches ROM in the memory region backing
    the address (refused where none does, or past its end); without it a ROM write goes
    nowhere and says why. A range past the program space is `bad_argument`.

    Reply: `addr`, `bytes_written`, `readback`, `verified`, `cpu`; with `region` also
    `region`, `region_offset`, `captures_reading_it`; on ROM `target`, `note`. A failed
    re-read is `readback_refused` or `session_broken`.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("write", ref=ref, data_hex=data_hex)
    return mwrite.write(*stopped("a memory write"), ref, data_hex, cpu, region)


@tool("Force a register", summary=summaries.set_register)
def set_register(name: str, value: inputs.NumberArg, cpu: str = "") -> dict[str, Any]:
    """Force register `name` of `cpu` to `value` and read it back. Modifies the machine; needs it
    stopped.

    Refuses an unknown name (listing the cpu's) and a value wider than the register.

    Reply: `register`, `value`, `readback`, `verified`, `cpu`. A cpu the stub does not
    describe is `no_channel`.

    Reference: REFERENCE.md, Reading and writing.
    """
    value = inputs.as_read(value)
    args.check("set_register", name=name, value=value)
    return mwrite.set_register(stopped("a register write")[0], name, value, cpu)


@tool("Reset the machine", summary=summaries.reset)
def reset() -> dict[str, Any]:
    """Soft reset, applied, without relaunching. Modifies the machine; needs it stopped. A hard
    reset is `close` then `start`.

    Reply: `kind`, `pc`, `boot_pc`, `verified` (the two agree), `frame_at_reset`, `taps_across` (a
    tap was live), and the stop's survey (`cause`, `stop_seq`, `cpu`, `regs`, `frame`,
    `instruction`, `following`, `errorlog`, `watches`, `watch_hit`, `regpoint_hit`). The frame
    counter does not restart: subtract `frame_at_reset` before comparing with a cold boot.

    Reference: REFERENCE.md, Reading and writing.
    """
    return mwrite.reset(*stopped("a reset"))


# ------------------------------------------------------------------------------- files

@tool("Dump memory to a file", summary=summaries.memdump, replay="drop")
def memdump(ref: str, length: int, dest: str, cpu: str = "") -> dict[str, Any]:
    """Write `length` bytes from `ref` of `cpu` (`subcpu`) to the new file `dest` ({DEST_FILE}).

    Reply: `addr`, `length`, `path`, `bytes`, `cpu`. A file not `length` bytes, or whose first
    bytes differ from a protocol read, is `status: INVALID`; a refused control read is
    `readback_refused`, a broken channel `session_broken`. A range past the program space is
    `bad_argument`.

    Reference: REFERENCE.md, Reading and writing.
    """
    args.check("memdump", ref=ref, length=length, dest=dest)
    return files.memdump(stopped("a memory dump")[0], ref, length, dest, cpu)


@tool("Snapshot the screen to a PNG", summary=summaries.snapshot, replay="drop")
def snapshot(dest: str = "") -> dict[str, Any]:
    """Save a PNG of the screen now, through `view`, in the scratch or moved to `dest`, which must
    be a new absolute or `~`-led path in an existing directory. Works while running.

    Reply: `path`, `bytes`, `sha256`, `view`. An incomplete PNG is `INVALID`.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("snapshot", dest=dest)
    return menvelope.with_view(files.snapshot(*contact(), dest))


@tool("Signature of the screen", summary=summaries.screen_signature, on_cancel="none",
      replay=("signature", "pc", "frame"))
def screen_signature(crop: list[int] | None = None,
                     seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
                     ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """One hex string for the screen, or its `crop` `[x, y, width, height]`: "same screen?" is two
    strings compared; `series_capture` writes it too.

    Reply: `signature`, `width`, `height`. `bad_argument`: `crop` off the screen. `no_channel`,
    `ambiguous_ref`: no or several screens, or a vector one.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("screen_signature", crop=crop, seconds=seconds)
    return mscreen.screen_signature(*stopped("a screen signature"), crop, seconds,
                                    bridge(ctx))


# ------------------------------------------------------------------- the screen maps




@tool("Which mapped screen is this", summary=summaries.screen_map_find, on_cancel="none",
      replay=("matched", "screen", "pc", "frame"))
def screen_map_find(ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """{MAP_FIND}

    Reference: REFERENCE.md, Screen maps.
    """
    return mmaps.screen_map_find(*stopped("a screen map"), bridge(ctx))


@tool("Write the screen map", summary=methods.fold_line("screen_map_write", folds.MAP),
      on_cancel="none", replay={"add": "step", "load": "step", "save": "drop"})
def screen_map_write(method: Annotated[str, vocab.enum(tuple(folds.MAP))], screen: str = "",
              match: list[list[int]] | None = None, controls: list[dict[str, Any]] | None = None,
              cells: Annotated[str, vocab.enum(screen_map.CELLS_WORDS)] = "",
              anchor: str = "", path: str = "", scale: int | None = None,
              margin: list[int] | None = None, dest: str = "", overwrite: bool | None = None,
              ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """The screen map: an application's screens, each known by the signatures of its stable
    regions, and their controls, in a session layer and a file layer.

    `add`: the screen shown now as `screen` in the session layer, one capture signing each
    `match` crop ([x, y, width, height], 1..16), `controls` ([{"name", "rect"}]) naming its
    places to read; needs the machine stopped. Reply: `screen`, `kind`, `size`, `cells`,
    `match`, `controls`, `replaced`, `shadows_file`, `anchor` (when given).

    {MAP_CELLS}

    {MAP_ANCHOR}

    {MAP_LOAD}

    {MAP_SAVE}

    Refused: an argument the method does not take; a misshapen name, crop, control, view or
    file; an `add` without an `anchor` to a consolidated map, and a save of one holding a screen
    with none (`bad_argument`); nothing mapped to save (`needs_call`).

    Reference: REFERENCE.md, Screen maps.
    """
    args.check("screen_map_write", **_given(locals()))
    return methods.dispatch(folds.MAP, _given(locals()), {"progress": bridge(ctx)})



@tool("Capture a series of frames", summary=summaries.series_capture, on_cancel="stop")
def series_capture(at_frames: list[int] | None = None, first: int | None = None,
                   last: int | None = None, step: int = 1, crop: list[int] | None = None,
                   dest: str = "",
                   seconds: Annotated[float, vocab.WAIT_BOUNDS] = mseries.SECONDS_DEFAULT,
                   ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Screen frames kept inside MAME as PNGs and a manifest, for `image_compare`. Stops two frames
    past the last.

    Frames by `run_for`'s counter, all ahead: `at_frames` or `first`, `last`, `step`, at most
    {SERIES_MAX}. `crop` is `[x, y, width, height]`. `dest`: a new absolute or `~`-led
    directory, kept after `close`. Needs a stopped machine.

    Reply: `manifest`, `count`, `first`, `last`, `crop`, `distinct`, `lost`, `kept_after_close`,
    `run_for`'s fields. Refused: `bad_argument`, `cut_by_other_stop`.

    Reference: REFERENCE.md, Media files.
    """
    args.check("series_capture", at_frames=at_frames, first=first, last=last, step=step,
               crop=crop, dest=dest, seconds=seconds)
    return mseries.series_capture(*stopped("a series of frames"), at_frames, first, last, step,
                                  crop, dest, seconds, bridge(ctx))


# THE MEDIA FILE TOOLS are scry-core's, one body and one description for both servers, each
# registered through this server's own `tool`, its bare fields made a reply by `envelope` as this
# server's own bodies make theirs; bound here by name so `probe_check` and a direct call find
# them as they find every other tool.
_MEDIA = media_tools.register(tool, media_tools.IMAGE_TOOLS + media_tools.AUDIO_TOOLS,
                              menvelope.envelope)
image_compare = _MEDIA["image_compare"]
audio_compare = _MEDIA["audio_compare"]


# ---------------------------------------------------------------------------- graphics

@tool("The live pens of a palette device", summary=summaries.palette, on_cancel="none",
      replay="drop")
def palette(palette: str = "", first: inputs.NumberArg = 0, count: int = 0, scale: int = 0,
            dest: str = "",
            seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
            ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """The pens of a palette device as the machine holds them now, as a table and a swatch: the
    route to the colours of a write-only RAMDAC.

    `palette` is the device tag (empty: the only one).

    Reply: `palette`, `entries`, `first`, `count`, `truncated`, `colors`, `alpha` (not fully
    opaque), `indirect_entries`, `image`. `unknown_ref`, `ambiguous_ref`, `no_channel`: no such
    device, several, none. `bad_argument`: past the last pen.

    Reference: REFERENCE.md, Input and the screen.
    """
    first = inputs.as_read(first)
    args.check("palette", palette=palette, first=first, count=count, scale=scale, dest=dest,
               seconds=seconds)
    return mpalette.palette(*stopped("a palette read"), palette, first, count, scale, dest,
                            seconds, bridge(ctx))


@tool("The screen as palette indices", summary=summaries.screen_view, on_cancel="none",
      replay="drop")
def screen_view(mode: Annotated[str, vocab.enum(mscreen.MODES)] = "render",
                pens: inputs.NumberList | None = None, point: list[int] | None = None,
                crop: list[int] | None = None, scale: int = 0, dest: str = "", attach: bool = True,
                seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
                ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """The screen as the pens it holds: each pixel's palette index, recovered exactly.

    `mode`: `render`, `isolate` (`pens`, 1..{SCREEN_PENS_MAX}, in `isolate_color` over grey),
    `histogram` (pens used, no picture), `pixel` (`point` `[x, y]`). `crop` `[x, y, width,
    height]` narrows all but `pixel`.

    Reply: `mode`, `screen`, `width`, `height`, `frame_screen`, `palette`, `entries`,
    `screen_indexed`, `crop`, `image` (not for mode histogram); `isolate`: `pixels`, `bbox`,
    `pens`, `isolate_color`; mode histogram: `histogram`, `pens_used`, `unused`; `pixel`: `x`,
    `y`, `pen`, `color`, `set_by`, `point_in_crop`. `no_channel`: no pens to read, or no screen.
    `ambiguous_ref`: several screens. `readback_refused`: a pen did not read back. `bad_argument`:
    off the screen.

    Reference: REFERENCE.md, Input and the screen.
    """
    pen_list = inputs.list_as_read(pens)
    args.check("screen_view", mode=mode, pens=pen_list, point=point, crop=crop, scale=scale,
               dest=dest, attach=attach, seconds=seconds)
    return mscreen.screen_view(*stopped("a screen read"), mode, pen_list, point, crop, scale, dest,
                               seconds, bridge(ctx), attach)


@tool("Bytes as tiles, under a gfx_layout", summary=summaries.gfx_view, on_cancel="none",
      replay="drop")
def gfx_view(layout: dict[str, Any] | str, palette: str = "none", tag: str = "", ref: str = "",
             offset: inputs.NumberArg = 0, first: int = 0, count: int = 0,
             columns: Annotated[int, vocab.bounds(1, mgfx.COLUMNS_MAX)] = 16,
             pen_base: inputs.NumberArg = 0, scale: int = 0, dest: str = "", attach: bool = True,
             cpu: str = "",
             seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
             ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Bytes as tiles in a format you state, as MAME's `gfx_layout`.

    `layout`: a manifest format's name, or `width`, `height`, `planes` (1..{GFX_PLANES_MAX}),
    `planeoffset`, `xoffset`, `yoffset`, `charincrement` in bits; values may use
    `RGN_FRAC(n,d)`, `+ - *`, hex, `STEPn(a,b)`.

    Source: `tag` with `offset` ({NUMBER_ARG}), or `ref` (tile 0; `count` required). `count` 0:
    the block, at most {GFX_TILES_MAX}; `columns` 1..{GFX_COLUMNS_MAX}. `palette`: `none` or a
    tag.

    Reply: `layout`, `tiles_available`, `palette`, `real_colors`, `image`. `bad_argument`: not a
    layout, tiles past the block, too few pens, over {GFX_PIXELS_MAX} pixels or {GFX_BLOCK_MAX}
    bytes. `unknown_ref`: missing tag, palette or name.

    Reference: REFERENCE.md, Input and the screen.
    """
    offset = inputs.as_read(offset)
    pen_base = inputs.as_read(pen_base)
    args.check("gfx_view", layout=layout, palette=palette, tag=tag, ref=ref, offset=offset,
               first=first, count=count, columns=columns, pen_base=pen_base, scale=scale,
               dest=dest, attach=attach, seconds=seconds, cpu=cpu)
    return mgfx.gfx_view(*stopped("a graphics read"), layout, palette, tag, ref, offset, first,
                         count, columns, pen_base, scale, dest, cpu, seconds, bridge(ctx),
                         attach)


@tool("Find a screen patch in a block", summary=summaries.gfx_locate, on_cancel="none",
      replay="drop")
def gfx_locate(layouts: list[dict[str, Any] | str], patch: list[int], tag: str = "", ref: str = "",
               offset: inputs.NumberArg = 0, first: int = 0, count: int = 0,
               transparent: inputs.NumberArg | None = None,
               flips: list[Annotated[str, vocab.enum(mlocate.FLIPS)]] | None = None, cpu: str = "",
               seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
               ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Search a screen `patch` `[x, y, width, height]` for a block's tiles under `layouts`, a list
    of 1..{LOCATE_LAYOUTS_MAX} (plural even for one), each a `gfx_view` layout or a `gfx_sweep`
    id (`s1c3`).

    Tiles `first`.. (`count` 1..{LOCATE_TILES_MAX}, 0 all) are tried under `flips` (absent: all
    four). `transparent` leaves a pixel value out. Source as `gfx_view` (`offset`:
    {NUMBER_ARG}).

    Reply: `candidates`, `matched`, `matches_total`, `matches` (first {LOCATE_MATCHES_SHOWN}:
    `layout`, `window`, `tile`, `flip`, `base`, `shape`), `ambiguous`, `pen_map`, `nearest`
    (nothing matched), `evidence`. `bad_argument`: a patch off the screen or without a whole tile,
    past a bound; else `gfx_view`'s.

    Reference: REFERENCE.md, Input and the screen.
    """
    offset = inputs.as_read(offset)
    transparent = inputs.as_read(transparent)
    args.check("gfx_locate", layouts=layouts, patch=patch, tag=tag, ref=ref, offset=offset,
               first=first, count=count, transparent=transparent, flips=flips,
               seconds=seconds, cpu=cpu)
    return mlocate.gfx_locate(*stopped("a graphics search"), layouts, patch, tag, ref, offset,
                              first, count, transparent, flips, cpu, seconds, bridge(ctx))


@tool("A block under candidate layouts", summary=summaries.gfx_sweep, on_cancel="none",
      replay="drop")
def gfx_sweep(tag: str = "", ref: str = "", offset: inputs.NumberArg = 0,
              count: Annotated[int, vocab.bounds(1, msweep.COUNT_MAX)] = msweep.COUNT_DEFAULT,
              planes: list[Annotated[int, vocab.bounds(1, ml.PLANES_MAX)]] | None = None,
              sizes: list[list[Annotated[int, vocab.enum(msweep.SIDES)]]] | None = None,
              palette: str = "none", pen_base: inputs.NumberArg = 0, scale: int = 0, dest: str = "",
              cpu: str = "",
              seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
              ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """A block of unknown format drawn under a fixed family of candidate layouts as one sheet, each
    cell labelled (`S1C3`); nothing is ranked.

    The family: `planes` x `sizes` ([width, height], sides 8..{SWEEP_SIDE_MAX}) x pixel order x
    `packed`, `planar` or `split` (`tag` only); at most {SWEEP_MAX} candidates. `count`: tiles a
    cell shows (1..{SWEEP_COUNT_MAX}). Source: `tag` with `offset` ({NUMBER_ARG}), or `ref`.
    `palette` as `gfx_view`.

    Reply: `sweep`, `count`, `cell_scale`, `candidates` (`id`, `what`, `tiles_available`,
    `shown`), `next`, `image`. `bad_argument`: too many candidates, no whole tile, a sheet past
    the ceiling. `unknown_ref`: a tag or palette it lacks.

    Reference: REFERENCE.md, Input and the screen.
    """
    offset = inputs.as_read(offset)
    pen_base = inputs.as_read(pen_base)
    args.check("gfx_sweep", tag=tag, ref=ref, offset=offset, count=count, planes=planes,
               sizes=sizes, palette=palette, pen_base=pen_base, scale=scale, dest=dest,
               seconds=seconds, cpu=cpu)
    return msweep.gfx_sweep(*stopped("a graphics sweep"), tag, ref, offset, count, planes,
                            sizes, palette, pen_base, scale, dest, cpu, seconds, bridge(ctx))


@tool("Draft a gfx.yaml from the evidence", summary=summaries.gfx_draft, replay="drop")
def gfx_draft(dest: str = "", choose: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write a `gfx.yaml` draft from what this session proved, and a JSON report beside it with
    every figure. Refused with no evidence.

    `dest`: an absolute `.yaml` in an existing directory (empty: the scratch); an earlier draft
    there is replaced, anything else is refused. `choose` `{"candidate": "s1c3", "chosen_by":
    "<who>"}` records a person's pick first.

    Reply: `manifest` and `report` (each `path`, `sha256`), `formats` (name to status),
    `asset_names`, `command_fields`, `evidence`, `not_proved` (first {DRAFT_NOT_PROVED_SHOWN}),
    `chose` (with `choose`), `confirm`.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("gfx_draft", dest=dest, choose=choose)
    _, scratch = stopped("a draft")
    return mdraft.gfx_draft(scratch, dest, choose)


@tool("Load the project's graphics manifest", summary=summaries.gfx_load, replay="drop")
def gfx_load(path: str) -> dict[str, Any]:
    """Load a project's `gfx.yaml` (an ABSOLUTE `path`): `formats`, `assets`, draw `commands`,
    `palette_ports`. A load replaces the previous one; answers while running.

    Judged whole: an unknown or missing key, wrong type or dangling name is `bad_argument`
    naming its path; a manifest not listing the session's `system` is refused (`still_loaded`).

    Reply: `loaded`, `replaced_path`, `path`, `draft`, `formats`, `assets`, `commands`,
    `palette_ports`, `status_counts`, `note`.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("gfx_load", path=path)
    return manifest.gfx_load(path)


@tool("Blit boxes over the screen", summary=summaries.gfx_blits, on_cancel="none", replay="drop")
def gfx_blits(draw_command: str, frame: int | None = None, area: list[int] | None = None,
              detail: bool = False, first: int = 0, scale: int = 0, dest: str = "",
              seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
              ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Who painted this area: every blit of a `frame` from the manifest's `draw_command` capture,
    as a box over the screen, one colour per writer pc.

    A missing capture is refused, naming the `watch_add`. `frame` defaults to the newest with
    blits. A summary by default; `area` `[x, y, width, height]` lists the blits covering it in
    drawn order; `detail` lists all, {ROWS_SHOWN} a page from `first`.

    Reply: `frame_blit`, `rows_cut`, `blits_in_frame`, `legend`, `by_plane`, `covering`,
    `topmost` (with `area`), `listed`, `blits` (with `area` or `detail`), `next_first` (more
    blits remain), `not_proved`, `image`. `bad_argument`: no
    manifest, capture or rows; a frame without blits or past the rows kept. `unknown_ref`: no
    such command.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("gfx_blits", draw_command=draw_command, frame=frame, area=area, detail=detail,
               first=first,
               scale=scale, dest=dest, seconds=seconds)
    return mblits.gfx_blits(*stopped("a screen read"), draw_command, frame, area, detail, first,
                            scale, dest, seconds, bridge(ctx))


@tool("A blit's source, unscaled", summary=summaries.gfx_blit_source, on_cancel="none",
      replay="drop")
def gfx_blit_source(draw_command: str, frame: int | None = None, index: int | None = None,
                    pc: str = "", margin: Annotated[int, vocab.bounds(0, mblits.MARGIN_MAX)] = 0,
                    scale: int = 0, dest: str = "",
                    seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
                    ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """The rectangle one blit reads, decoded from the manifest command's `asset` under the live
    palette. Always unscaled: no zoom or scale register is applied, so it never shows the blit as
    it lands on screen.

    The blit: `frame` (as `gfx_blits`) and `index`, or `pc` (the writer; refused when it fired
    more than once). `margin` (0..{BLIT_MARGIN_MAX}) dims pixels round the rectangle: `image` is
    that view, `data` the exact indexed PNG.

    Reply: `frame_blit`, `index`, `blit_pc`, `asset`, `format`, `palette`, `rect` (`tile`, `x`,
    `y`, `width`, `height`), `margin`, `box`, `wrap`, `not_proved`, `reads_source`, `image`,
    `data` (with `margin` above 0). `bad_argument`: `gfx_blits`'s, no `asset`, a tile or rectangle
    past its bounds, a pc that fired none or several. `unknown_ref`: an unknown symbol.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("gfx_blit_source", draw_command=draw_command, frame=frame, index=index, pc=pc,
               margin=margin, scale=scale, dest=dest, seconds=seconds)
    return mblits.gfx_blit_source(*stopped("a graphics read"), draw_command, frame, index, pc,
                                  margin, scale, dest, seconds, bridge(ctx))


@tool("Log a palette's port writes", summary=summaries.palette_log, replay="drop")
def palette_log(palette_port: str, pen: inputs.NumberArg | None = None,
                limit: Annotated[int, vocab.bounds(0, mramdac.LIMIT_MAX)] = mramdac.LIMIT_DEFAULT,
                clear: bool = False,
                arm: bool = False) -> dict[str, Any]:
    """Who set this pen's colour, on a board whose colour RAM is write-only: every write to the
    ports of the loaded manifest's `palette_port`, placed on its pen by the device's law.

    `arm=True` arms the log; without it a call reads it; `clear=True` removes it. `pen` shows
    that pen alone, `limit` the newest rows. Answers while running. Rows are capped at
    {PALETTE_LOG_ROWS_MAX}, the rest counted.

    Reply: `palette_port`, `protocol`, `armed_now`, `installed` (unless `clear`), `state`
    (once armed), `writes_total`, `unsynced_writes`, `desyncs`, `rows_path` (once the log has
    dumped). Without `pen`: `setters` (each `pc`, `symbol`,
    `written_by`; the first {PALETTE_LOG_SETTERS_MAX}). With `pen`: `pen_state`, `rows`.
    `needs_call`: no manifest, entry or armed log; `bad_argument`: a pen it does not set.

    Reference: REFERENCE.md, Input and the screen.
    """
    pen = inputs.as_read(pen)
    args.check("palette_log", palette_port=palette_port, pen=pen, limit=limit, clear=clear,
               arm=arm)
    return mramdac.palette_log(contact()[1], palette_port, pen, limit, clear, arm)


@tool("Film the frames where a write happened", summary=summaries.gfx_film, on_cancel="none",
      replay="drop")
def gfx_film(trigger: str = "", length: Annotated[int, vocab.enum(mfilm.LENGTHS)] = 1,
             value: inputs.NumberArg | None = None,
             changed: bool = False, pc: str = "",
             cpu: str = "", frames: int = mfilm.FRAMES_DEFAULT, keep: int = mfilm.KEEP_DEFAULT,
             crop: list[int] | None = None, film_dir: str = "", first: int = 0, clear: bool = False,
             seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
             space: Annotated[str, vocab.enum(mspace.SPACES)] = "program",
             ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """The frames in which a write happened; one film per session.

    Arm (STOPPED): `trigger` (symbol or `0x` on `cpu`; `space` `io` for a port) is a write of
    `length` bytes, from `pc`, carrying `value` ({NUMBER_ARG}), or with `changed=True` a value
    unlike the one before. Judges `frames` (max {FILM_FRAMES_MAX}), keeps `keep` pictures (max
    {FILM_KEEP_MAX}) cropped to `crop`, into a new absolute `film_dir`.

    Read (no `trigger`; works while running): a contact sheet from `first`. `clear=True` clears.

    Reply (arm): `film`, `armed_now`. Reply (read): `film`, `state`, `judged`, `met`, `kept` (once
    the film has dumped), `cells` (each `frame`, `pc`, `path`), `image` (once frames are kept),
    `next_first` (more kept frames remain). `bad_argument`: film armed
    already, none to read.

    Reference: REFERENCE.md, Input and the screen.
    """
    value = inputs.as_read(value)
    args.check("gfx_film", trigger=trigger, length=length, value=value, changed=changed, pc=pc,
               cpu=cpu, frames=frames, keep=keep, crop=crop, film_dir=film_dir, first=first,
               clear=clear, seconds=seconds, space=space)
    ses, scratch = stopped("arming a film") if mfilm.arms(trigger, clear) else contact()
    return mfilm.gfx_film(ses, scratch, trigger, length, value, changed, pc, cpu, frames, keep,
                          crop, film_dir, first, clear, seconds, bridge(ctx), space)


@tool("Read the log", summary=summaries.log, read_only=True)
def log(pattern: str, channel: Annotated[str, vocab.enum(files.LOG_CHANNELS)],
        limit: Annotated[int, vocab.bounds(1, read.LOG_LIMIT_MAX)] = 40,
        labels: bool = False,
        since_mark: Annotated[int, log_marks.SINCE_MARK_BOUND] = 0) -> dict[str, Any]:
    """The newest lines of one `channel` of what MAME writes matching the regex `pattern` (`.` for
    all; never empty). Works while running.

    `channel`: `emulator`, `process` or `all` (lines tagged `[emulator] `, `[process] `);
    `guest` is refused. `labels=True` adds `labels`, lines counted by first word.
    `since_mark` reads only what follows that log byte position.

    Reply: `pattern`, `channel`, `lines` (the newest `limit`, 1..{LIST_MAX}, oldest first),
    `lines_total`, `truncated`, `counts` (on channel `all`), `labels`. A bad `limit`, regex or
    `since_mark` is refused.

    Reference: REFERENCE.md, The log.
    """
    args.check("log", pattern=pattern, channel=channel, limit=limit, since_mark=since_mark)
    ses, scratch = contact()
    reply = files.log(scratch, pattern, limit, channel, labels, since_mark)
    running.note_throttle_lift(ses, reply.get("lines", []), launch.THROTTLE_MARK)
    return reply


@tool("Wait for a log line", summary=summaries.log_wait, read_only=True, on_cancel="none")
def log_wait(pattern: str, channel: Annotated[str, vocab.enum(files.LOG_CHANNELS)],
             seconds: Annotated[float, vocab.WAIT_BOUNDS] = 30.0,
             since_mark: Annotated[int, log_marks.SINCE_MARK_BOUND] = 0,
             ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Wait up to `seconds` for a line of `channel` matching the regex `pattern` (never empty);
    at once if the log holds it. Answers while running. `channel`, `since_mark` as in `log`.

    Refused: `wait_stopped` when stopped and the log lacks the line; `session_broken`; a bad
    `seconds`, regex or `since_mark`.

    Reply: `verdict` `TARGET`, `line` (the first match), `already`, `waited_s`, `lines_before`,
    `lines_total`, `arrived_during`, `lines_examined`; on timeout `verdict` `TIMEOUT`, `note`.

    Reference: REFERENCE.md, The log.
    """
    args.check("log_wait", pattern=pattern, channel=channel, seconds=seconds,
               since_mark=since_mark)
    ses, scratch = contact()
    reply = files.log_wait(
        ses, scratch, lambda: STATE.proc is not None and STATE.proc.poll() is None,
        lambda: running.observe_stop(ses, scratch), pattern, seconds, channel, bridge(ctx),
        since_mark)
    line = reply.get("line")
    if isinstance(line, str) and line:
        running.note_throttle_lift(ses, [line], launch.THROTTLE_MARK)
    return reply


# ------------------------------------------------------------------------------- debug

def _step_ops() -> dict[str, Callable[..., dict[str, Any]]]:
    """Op name -> the wrapped tool it dispatches to, built at call time so it names the
    tools by their live registrations rather than a second hand-kept list: every tool but
    the lifecycle (`start`, `close`, `rom_check`), the two batch tools themselves, `perform`
    and `drive` (the reason is in `perform`'s docstring), and `perform_export`, which writes
    the session the list belongs to."""
    return core_steps.step_ops(mcp, globals(), sequence.NOT_STEPS)


#: `summaries`' own description, `perform`'s and `drive`'s, as scry-core words it.
SUMMARIES_ARGUMENT = account.summaries_argument(st.ROWS_SHOWN)


@tool("Drive an input and verify it", summary=summaries.drive, on_cancel="none")
def drive(act: list[dict[str, Any]], expect: str = "",
          seconds: Annotated[float, vocab.WAIT_BOUNDS] | None = None,
          pattern: str = ".", limit: Annotated[int, vocab.bounds(1, read.LOG_LIMIT_MAX)] = 40,
          settle_seconds: Annotated[float, vocab.WAIT_FROM_ZERO_BOUNDS] = 30.0,
          summaries: Annotated[bool, Field(description=SUMMARIES_ARGUMENT)] = False,
          ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Marks the emulator log, runs `act` (steps as in `perform`), then checks the log since
    the mark.

    `expect` (regex) waits up to `seconds` (default {EXPECT_WAIT_S}, at most {WAIT_MAX_S})
    for a matching line, only while the machine runs; `seconds` without `expect` is refused.
    `looked.emulator` is the last `limit` (1..{LIST_MAX}) lines matching `pattern`. A failed
    step is INVALID `step_failed`; a stopped machine lacking the line, `wait_stopped`; a bad
    `act` step or argument, `bad_argument` before anything ran. With no `expect`, `verify`
    is `checked: false`.

    Reply: `act`, `verify` (`checked`, `seen`, `verdict` `TARGET` or `TIMEOUT`, `line`,
    `waited_s`), `looked` (`emulator`).

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
    ses, scratch = contact()
    return sequence.drive(ses, scratch, _step_ops(), act, expect, seconds, pattern, limit,
                          settle_seconds, bridge(ctx), summaries=summaries)


@tool("Run a sequence of steps", summary=summaries.perform, on_cancel="stop")
def perform(steps: list[dict[str, Any]],
            settle_seconds: Annotated[float, vocab.WAIT_FROM_ZERO_BOUNDS] = 30.0,
            summaries: Annotated[bool, Field(description=SUMMARIES_ARGUMENT)] = False,
            until_frame: int = 0,
            ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Run this server's operations in order, stopping at the first failure.

    `steps`: `{"op": <tool>, ...}`, any tool but `start`, `close`, `rom_check`, `perform`,
    `drive`, `perform_export`. `until_frame=F` (with `summaries`, `run_for`) repeats the
    list until a stop reads frame F, within {UNTIL_STEPS_MAX} steps and {WAIT_MAX_S} s;
    `no_channel` if no frame counter. A step's `recorded`, `{field: value}` of its own reply,
    must hold, else INVALID `diverged`. A refused step: INVALID `errors`, nothing run.
    `settle_seconds` bounds each wait for a stop before a step that needs one (0: never wait).

    Reply: `ran`, `steps_completed`, `held`, `failed_at`, `failed` (`step_failed`),
    `verdict` (once the list waited; `TARGET` adds `stopped`, `TIMEOUT` `note`), `frame_reached`
    (with `until_frame`).

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
    ses, scratch = contact()
    sequence.check_until(steps, until_frame)     # after the contact: it judges where the machine is
    return sequence.run_steps(ses, scratch, steps, settle_seconds, _step_ops(), bridge(ctx),
                              summaries=summaries, until_frame=until_frame, shape_judged=True)


@tool("Export the session as a replay", summary=recording.export_summary)
def perform_export(dest: str, overwrite: bool = False) -> dict[str, Any]:
    """Write the session's calls since `start` to `dest` as a `perform` document.

    Kept: moving calls and checks (`read_memory`, `read_block`, `registers`,
    `screen_signature`, `screen_map_find`, `image_compare(method="golden")`), each held to its
    `recorded` reply. Other calls drop; the first no replay can place, or past {RECORD_MAX}, cuts
    the rest.

    `dest` (`.json`) is refused if present unless `overwrite`. Reply: `path`, `steps`,
    `checks`, `dropped`, `dropped_total`, `cut`, `replay`; `no_recording` if empty.

    Reference: REFERENCE.md, From an investigation to a bench.
    """
    return menvelope.envelope(recording.export(RECORDER, dest, overwrite))


@tool("Debugger console command", summary=summaries.debug)
def debug(command: str) -> dict[str, Any]:
    """Run any MAME debugger command, `command`. Prefer the typed readers: a wide `find` takes
    MAME down. Needs the machine stopped.

    A line that changes the machine (`fill`, `load`, `stateload`, a reset, a run or step, an
    assignment) is a write. `hardreset` is refused unsent. The `g` family, `step N`, `over`
    and `next` mark the session RUNNING until `stop`. A too long packet, or the console's own
    error answer, is `bad_argument`.

    Reply: `command`, `mutates`, `output`, `clipped`, `note`; past {OUTPUT_MAX} characters the
    text goes to a file (`output_chars`, `output_path`); `visible_cpu`, `ignored` (a line that
    sets cpus); on refusal `command_chars`, `limit_chars`, `refused`, `refused_total`, `not_run`.

    Reference: REFERENCE.md, The console.
    """
    args.check("debug", command=command)
    return mwrite.debug(*stopped("a console command"), command)


# ----------------------------------------------------------------------------- the Lua channel

@tool("Evaluate Lua on the machine", summary=summaries.lua, on_cancel="none")
def lua(script: str,
        seconds: Annotated[float, vocab.WAIT_BOUNDS] = mlua.EVAL_WAIT_S,
        read_only: bool = False, ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Evaluate a Lua `script` on MAME's Lua console; prefer the typed wrappers. {NEEDS_STOPPED}.

    `script`: one chunk of at most {SCRIPT_MAX} characters; only what it `print`s comes back.
    `read_only=True` declares it only reads, else the session is marked ALTERED. More than
    {PIPE_STEPS_MAX} lines ahead in the pipe is refused. A chunk that fails to load or raises
    is INVALID with the console's `error:`; `reader_died` means the script never ran.

    Reply: `output`, `clipped`, `output_path` (past {OUTPUT_MAX} characters), `evaluated_by`,
    `pc_before`, `lines_ahead`, `console_reruns`, `note`, the stop survey.

    Reference: REFERENCE.md, The console.
    """
    args.check("lua", script=script, seconds=seconds)
    return mlua.lua(*stopped("a Lua script"), script, seconds, read_only, bridge(ctx))


@tool("Hold an input field", summary=summaries.input, on_cancel="stop")
def input(port: str, field: str, value: inputs.NumberArg = 1, frames: int = 4,
          seconds: Annotated[float, vocab.WAIT_BOUNDS] = 30.0,
          ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Press input `field` of `port` by name, hold it `frames` frames, release it, stop one frame
    later. {NEEDS_STOPPED}.

    A non-zero `value` activates a digital field. `seconds` bounds the whole call. A press
    leaves `altered` as it was; an edge-detecting game needs a release between presses: call
    twice.

    Reply, once answered: `verdict`, `frame_before`, `frame_after`, `port_before`, `frame_set`,
    `released`, `frame_released`, `active` (read back at release), `name`, `mask`, `note`, the
    stop survey. Without an answer, `pending`.

    Reference: REFERENCE.md, Input and the screen.
    """
    value = inputs.as_read(value)
    args.check("input", port=port, field=field, frames=frames, seconds=seconds)
    return mlua.input_field(*stopped("an input"), port, field, value, frames, seconds,
                            bridge(ctx))


@tool("Record frames to an AVI", summary=summaries.record, on_cancel="stop")
def record(frames: int, dest: str = "",
           seconds: Annotated[float, vocab.WAIT_BOUNDS] = 60.0,
           ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Record exactly `frames` emulated frames of the screen to an AVI, then stop.
    {NEEDS_STOPPED}.

    `dest`: an absolute path not there yet; empty lands in the scratch. `frames` is 2 or more.
    The AVI is checked before its path is given; zero frames is INVALID. A run cut short
    leaves the recording open (`ended: false`).

    Reply, once answered: `verdict`, `path`, `began`, `ended`, `bytes`, `avi_frames`, `view`,
    `note`, the stop survey. Without an answer, `pending`.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("record", frames=frames, dest=dest, seconds=seconds)
    return menvelope.with_view(mrec.record(*stopped("a recording"), frames, dest, seconds,
                                           bridge(ctx)))


@tool("Record the sound to a WAV", summary=summaries.audio_record, on_cancel="stop")
def audio_record(frames: int, dest: str = "",
                 seconds: Annotated[float, vocab.WAIT_BOUNDS] = 60.0,
                 ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Record the mixer's output for exactly `frames` frames to a WAV, then stop.
    {NEEDS_STOPPED}.

    `dest`: an absolute path not there yet; empty lands in the scratch. `frames` is 2 or more.
    The WAV is checked before its path is given; a span with no mixer update, no speaker, or a
    mixer already recording is INVALID. Silence is reported, never refused.

    Reply, once answered: `verdict`, `path`, `began`, `ended`, `bytes`, `channels`,
    `sample_rate_hz`, `samples`, `emulated_s`, `sample_min`, `sample_max`, `note`, the stop
    survey. Without an answer, `pending`.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("audio_record", frames=frames, dest=dest, seconds=seconds)
    return maudio.audio_record(*stopped("an audio recording"), frames, dest, seconds,
                               bridge(ctx))


@tool("Switch the throttle", summary=summaries.throttle, on_cancel="none", replay="drop")
def throttle(on: bool, seconds: Annotated[float, vocab.WAIT_BOUNDS] = 5.0,
             ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
    """Switch real-speed throttling `on` or off; it applies when the console next reads a line.

    Stopped, the reply is `pending: true` with a `tag` for `log_wait` on the `emulator`
    channel. Running, it waits up to `seconds` for the tag; a bound that runs out is
    `wait_expired`.

    Reply: `on`, `pending`, `tag`; pending: `applies`, `confirmed_by`; applied: `frame`,
    `waited_s`.

    Reference: REFERENCE.md, Input and the screen.
    """
    args.check("throttle", on=on, seconds=seconds)
    return mlua.throttle(*contact(), on, seconds, bridge(ctx))



@tool("List this session's captures", summary=summaries.captures, read_only=True)
def captures() -> dict[str, Any]:
    """List the files `record`, `audio_record`, `trace`, `snapshot` and the graphics tools made
    this session, re-read now; works while running.

    Reply: `captures` (`kind`, `path`, `present`, `bytes`, `avi_frames`, `samples`, `channels`,
    `sample_rate_hz`).

    Reference: REFERENCE.md, Input and the screen.
    """
    contact()
    return mrec.captures()


@tool("List the saved states", summary=summaries.state_list, read_only=True)
def state_list() -> dict[str, Any]:
    """List the saved states of the session's state folder.

    Reply: `state_dir`, `states` (each `name`, `path`, `bytes`, `frame`, `pc`; unavailable with
    `why` when not read).

    Reference: REFERENCE.md, Saved states.
    """
    contact()
    return savestates.state_list()


@tool("Save or load a machine state", summary=methods.fold_line("state_write",
                                                             folds.STATE_METHODS))
def state_write(method: Annotated[str, vocab.enum(tuple(folds.STATE_METHODS))],
                name: str) -> dict[str, Any]:
    """Save or load a savestate `name` (`[A-Za-z0-9_-]`, never `-` first, 1..{STATE_NAME_MAX}
    characters) through the debugger console. Needs the machine stopped.

    `save`: write it, never overwriting. Reply: `name`, `path`, `bytes`, `frame`, `pc`,
    `errorlog`, `held`, `stop_seq` (held for a timer).

    `load`: restore it, altering the session; the header, the ROM and the stop are checked first.
    Reply: `name`, `path`, `rom_check`, `verified` (true, or INVALID `readback_refused` with
    `differs`), `saved`, `output`, `mark`, `held`, `taps_across` (a tap was live), and the stop
    survey (`cause`, `stop_seq`, `cpu`, `pc`, `regs`, `frame`, `instruction`, `following`,
    `errorlog`, `watches`, `watch_hit`, `regpoint_hit`).

    Refused: a name of another shape; `load` of a `.sta` that is no regular file
    (`unknown_ref`).

    Reference: REFERENCE.md, Saved states.
    """
    args.check("state_write", **_given(locals()))
    return methods.dispatch(folds.STATE_METHODS, locals())


strict.strict_arguments(mcp)
reply_schema.declare(mcp, mame_replies.MODELS)
sequence.GATE.check_folds(folds.METHODS)

#: What the reference pages are generated from
#: (`python -m scry_core.reference scry_mame.server:REFERENCE`) and held to
#: (`tests/test_reference_pages.py`).
REFERENCE = reference.Registry(server=mcp, models=mame_replies.MODELS, roster=ROSTER,
                               envelope=mame_replies.MameEnvelope,
                               root=Path(__file__).resolve().parents[2])


#: The end on a signal: the machine killed, which removes its scratch too, the process left.
END = signalled_end.SignalledEnd(st.LOCK, lambda: STATE.kill(), lambda: None, "mame server")


def main() -> None:
    process_name.set_title(launch.PROCESS_NAME)
    END.install()
    idle.IDLE.watch(st.LOCK, STATE.machine_alive, msession.close)
    try:
        mcp.run()
    finally:
        with st.LOCK:    # a signalled end may be killing it too
            STATE.kill()


if __name__ == "__main__":
    main()
