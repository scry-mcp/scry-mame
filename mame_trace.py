"""`trace`: the addresses one cpu executed over a run bounded like `run_for`, joined to the symbols.

MAME ALREADY TRACES. Its console's `trace <file>,<cpu>` writes one line per executed instruction
from the debugger's instruction hook, so this module adds no hook, no Lua binding and no stub
packet: it arms that tracer, runs `run_for`'s own body, closes the tracer and reads the file
back. Both ends live in ONE call, because a trace left armed keeps writing on the next run of a
client that forgot it.

THE FILE IS FLUSHED PER LINE (`m_file->flush()` after every write in `debugcpu.cpp`), so what
the file holds when `trace off` answers is the whole record, and the parse needs no
`traceflush`.

CONDENSED BY DEFAULT. The tracer keeps the last 64 logged pcs and skips a pc already twice among
them, writing `(loops for N instructions)` when the run leaves the loop. The SET of executed
addresses survives that exactly (a skipped pc was logged before it was skipped), the counts do
not, which is what `noloop` buys back at a larger file. The one hole in the set: the history
starts as zeros, so address 0 among the first logged instructions reads as a loop and is
skipped.

THE PARKED EDGES. The tracer logs a pc when the cpu reaches it, before executing it, so the pc a
stopped cpu is parked on is absent from a trace armed there although the window executes it
first, and the pc the run ends parked on is logged although the window never executed it. Both
are corrected when they can be read, and `note` says so. A cpu the run did not stop on has no
end edge: its last line is the last instruction it began, which a core that yields
mid-instruction (MAME's 68000) finishes only after the window. Its twin at the start: on such a
core, a cpu the last stop did not park may be inside an instruction when the window begins, which
it resumes with no hook, so it is finished in the window and never logged; `note` says that too.

THE FILE IS READ A LINE AT A TIME, never whole: a call at the cap writes about a gibibyte, and
held whole it would cost the server that much again and more in the lines split out of it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from scry_core import cancel, prose
from scry_core import progress as mprogress
from scry_core import sequence_account as account
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_advance as advance
import mame_cpus as cpus
import mame_envelope as menvelope
import mame_files as files
import mame_inputs as inputs
import mame_read as read
import mame_running as running
import mame_state as st
from mame_state import STATE

SET_SUFFIX = ".set.jsonl"
# Inline per-symbol rows; the rest is counted, and the set file holds every address.
SYMBOLS_SHOWN = 64
# THE ASKED WORK IS BOUNDED BY THE FILE IT MAKES, never by the wait (that is `seconds`): each cap
# is the work at which the heaviest window measured on any bench fills a gibibyte, taken from
# bytes because bytes are the same on any host and a cap from bytes per wall-second would not
# be. It is a measurement, not a guarantee: a window heavier than every one measured can write
# more than a gibibyte within it. By time, the bench heaviest
# per emulated millisecond (its bytes per frame times its screen's refresh), which need not be
# the one heaviest per frame.
FRAMES_MAX = 5026
MILLISECONDS_MAX = 98143
# `noloop` writes every instruction, so its file grows faster and its caps are its own.
NOLOOP_FRAMES_MAX = 1648
NOLOOP_MILLISECONDS_MAX = 32920

_INSTR = re.compile(rb"^([0-9A-F]+): ")
_LOOP = re.compile(rb"^   \(loops for (\d+) instructions\)$")
_IRQ = re.compile(rb"^   \(interrupted at ([0-9A-F]+), IRQ (-?\d+)\)$")
_PAGED = re.compile(rb"^[0-9A-F]+:[0-9A-F]+: ")
_ANSWER = re.compile(r"^(Tracing CPU|Error opening file)")


def caps(noloop: bool) -> tuple[int, int]:
    """The (frames, milliseconds) one call may trace in the mode asked."""
    return (NOLOOP_FRAMES_MAX, NOLOOP_MILLISECONDS_MAX) if noloop else (FRAMES_MAX,
                                                                         MILLISECONDS_MAX)


def check_trace(milliseconds: int = 0, frames: int = 0, dest: str = "", seconds: float = 60.0,
                noloop: bool = False, **_: Any) -> Path | None:
    """`trace`'s machine-independent half: `run_for`'s own judgement of the bound, the mode, the
    cap on the asked work, and the two files, handed back as the `Path` it built."""
    advance.check_run_bound(milliseconds, frames, seconds, "trace")
    vocab.check_bool("noloop", noloop)
    fmax, mmax = caps(noloop)
    why = (" is more than one call traces: its file could pass a gibibyte; split the window into "
           "consecutive calls")
    inputs.natural("frames", frames, f"{why} (at most {prose.counted(fmax, 'frame')})", hi=fmax)
    inputs.natural("milliseconds", milliseconds, f"{why} (at most {mmax} ms)", hi=mmax)
    if not dest:
        return None
    path = inputs.fresh_dest("dest", dest)
    inputs.fresh_dest("dest's set file", str(path) + SET_SUFFIX)
    return path


@dataclass
class Parsed:
    """What a trace file accounts for: instruction lines, the loop lines' counts, and the
    instruction lines per pc."""
    lines: int = 0
    loop_sum: int = 0
    counts: dict[int, int] = field(default_factory=dict)
    last_pc: int | None = None


def parse(lines: Iterable[bytes], width: int | None, mask: int | None, cpu: str) -> Parsed:
    """Every line by its shape, as the tracer prints it, and any other line refused by number:
    a column index would read a new shape as a plausible pc. `lines` as an open binary file
    yields them, ending in their newline or not; `width` and `mask` are the program space's
    (None: not judged); a pc field of another width, or paged, is a space this parser does not
    place."""
    p = Parsed()
    for n, raw in enumerate(lines, 1):
        line = raw[:-1] if raw.endswith(b"\n") else raw
        if not line:
            continue
        m = _INSTR.match(line)
        if m:
            digits = m.group(1)
            if width is not None and len(digits) != width:
                raise st.Invalid("no_channel", f"line {n} of the trace holds a pc of "
                                 f"{len(digits)} hex digits where {cpu}'s program space prints "
                                 f"{width}: {line[:120]!r}")
            pc = int(digits, 16)
            if mask is not None and pc & ~mask:
                raise st.Invalid("no_channel", f"line {n} of the trace holds pc {pc:#x}, past "
                                 f"{cpu}'s program mask {mask:#x}")
            p.lines += 1
            p.counts[pc] = p.counts.get(pc, 0) + 1
            p.last_pc = pc
            continue
        if m := _LOOP.match(line):
            p.loop_sum += int(m.group(1))
            continue
        if _IRQ.match(line):
            continue
        if _PAGED.match(line):
            raise st.Invalid("no_channel", f"line {n} of the trace holds a paged pc, which "
                             f"{cpu}'s addresses cannot be placed by: {line[:120]!r}")
        raise st.Invalid("unexpected_answer",
                         f"line {n} of the trace is not a shape the tracer prints: "
                         f"{line[:120].decode(errors='replace')!r}")
    return p


def join(counts: dict[int, int], place: read.Placer | None,
         noloop: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """The set rows ascending, the per-symbol rows ascending by base, and how many addresses no
    symbol places. A row's `symbol` is spelled as every reply spells a placed pc."""
    rows: list[dict[str, Any]] = []
    by_base: dict[int, dict[str, Any]] = {}
    unplaced = 0
    for addr in sorted(counts):
        row: dict[str, Any] = {"addr": st.hex_addr(addr)}
        placed = place(addr) if place is not None else None
        if placed is None:
            unplaced += 1
        else:
            base, name = placed
            row["symbol"] = name if addr == base else f"{name}+{addr - base:#x}"
            s = by_base.get(base)
            if s is None:
                s = by_base[base] = {"symbol": name, "addr": st.hex_addr(base), "addresses": 0,
                                     "first": addr, "last": addr, "instructions": 0}
            s["addresses"] += 1
            s["last"] = addr
            s["instructions"] += counts[addr]
        if noloop:
            row["count"] = counts[addr]
        rows.append(row)
    summary = []
    for base in sorted(by_base):
        s = by_base[base]
        s["first"], s["last"] = st.hex_addr(s["first"]), st.hex_addr(s["last"])
        if not noloop:
            del s["instructions"]
        summary.append(s)
    return rows, summary, unplaced


def _parked_start(ses: gs.Session, tag: str) -> tuple[int | None, str | None]:
    """The pc `tag` is parked on, when it is the cpu parked in its hook AND the visible one, so
    `current_pc` reads it: the window executes it first and the tracer, armed there, never logs
    it. Read before the route, which may change the visible cpu. Beside it, the note for a pc it
    could not read, or for a cpu the stop did not park, whose first instruction may go unlogged."""
    # A stop that recorded no cpu was the first cpu's, the one a stub without threads binds:
    # ASSUMED for the comparison, and never named in the note as if the stop had recorded it.
    recorded = STATE.last_stop.get("cpu")
    stopped_on = recorded or next(iter(cpus.cpu_list(ses)), None)
    if stopped_on != tag:
        parked = f" ({recorded} was)" if recorded else ""
        return None, (f"{tag} was not the cpu the last stop parked{parked}: on a core that yields "
                      "mid-instruction (MAME's 68000) the instruction it was inside when the "
                      "window began is finished in it with no hook, so its pc is in the set only "
                      "if the window reached it again")
    if cpus.visible_cpu(ses) != tag:
        return None, (f"{tag} is parked but not visible, so the pc it is parked on was not read "
                      "and is in the set only if the window reached it again")
    return ses.current_pc(), None


def _close(ses: gs.Session, scratch: Path, tag: str) -> bool | None:
    """Stop a machine a bail-out left running, so the tracer is never destroyed under a moving
    cpu, then `trace off`: True when it answered as it should, False when it did not, None when
    the session latched broken and nothing it answers can be believed."""
    if ses.broken:
        return None
    try:
        if ses.running:
            running.stop(ses, scratch)
        # READ AGAIN: the stop may have latched the session, which the first read cannot know;
        # the cast keeps the type checker from carrying that first read's answer past the call.
        if cast("str | None", ses.broken):
            return None
        if ses.running:
            return False
        return ses.monitor(f"trace off,{tag}").strip() == f"Stopped tracing on CPU '{tag}'"
    except gs.SessionError:
        return None if ses.broken else False


def _left(path: Path, closed: bool | None) -> dict[str, Any]:
    return {"path": str(path),
            "bytes": (path.stat().st_size if path.exists()
                      else unavailable("the tracer wrote no file")),
            "closed": or_unavailable(closed, "the session broke, so the tracer could not be "
                                                "asked to close")}


def _with_trace(reply: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    """`reply` with `trace` added: the survey's own `cpu` and `pc` stay at the top level, so the
    trace's live under their own key. Closing the tracer may have stopped a machine the run
    left running, which the `session` block `mame_mcp.tool` composes afterwards says."""
    reply["trace"] = block
    return reply


def trace(ses: gs.Session, scratch: Path, milliseconds: int, frames: int, dest: str,
          seconds: float, cpu: str, noloop: bool,
          progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `trace` tool. Every refusal about the arguments, the cpu and the route is
    made before the tracer is armed, so it leaves nothing armed and no file; once armed, the
    tracer is closed on every way out."""
    given = check_trace(milliseconds, frames, dest, seconds, noloop)
    tag = cpus.acting(ses, cpu)
    if (missing := read.no_disassembler(ses, tag)) is not None:
        return menvelope.invalid("no_channel",
                                 f"{tag} has no disassembler, and the tracer disassembles "
                                 f"every line it writes: {missing}")
    mask = cpus.program_mask(tag)
    if given is not None:
        path = given
    else:
        # THE NUMBER IS TAKEN ONLY ONCE THE PATH IS ACCEPTED: a refused one leaves the next
        # trace the name it would have had.
        path = scratch / "snap" / f"trace-{STATE.recordings + 1}.trace"
        files.refuse_console_path(path)
        STATE.next_number("recordings")
    parked, parked_note = _parked_start(ses, tag)
    route = advance.route_frames(ses, read.BY_TIME.format(tool="trace")) if frames else None
    set_path = Path(str(path) + SET_SUFFIX)
    # a long path wraps at the console's column: the answer is read as its logical line
    answer = ses.monitor(f"trace {path},{tag}" + (",noloop" if noloop else ""))
    armed = " ".join(gs.unwrap_console(answer, _ANSWER)).strip()
    if armed != f"Tracing CPU '{tag}' to file {path}":
        try:
            ses.monitor(f"trace off,{tag}")   # in case it armed under an answer not foreseen
        except gs.SessionError as e:
            return running.session_broke(ses, e, "closing a tracer armed under an answer "
                                         f"not foreseen ({armed!r})", "It may still be armed",
                                         path=str(path))
        if armed.startswith("Error opening file"):
            return menvelope.invalid("host_failed", f"MAME could not open the trace file: {armed}",
                                     path=str(path))
        return menvelope.invalid("unexpected_answer", f"the console answered the arming with "
                                 f"{armed!r}", path=str(path))
    try:
        reply = advance.run_for(ses, scratch, milliseconds, seconds, progress, frames=frames,
                                route=route)
    except st.Invalid as refused:
        closed = _close(ses, scratch, tag)
        if closed is False:
            return _unclosed(path, tag, f"refused `{refused.code}`")
        raise st.Invalid(refused.code, str(refused), **refused.fields,
                         trace=_left(path, closed)) from refused
    except gs.NotStopped:
        _close(ses, scratch, tag)
        raise
    except gs.SessionError as e:
        # answered as the server answers it, latching the session when the error does, before
        # the close, so a broken channel is not asked to close anything; the close is reached
        # even when building that answer raises
        try:
            broke = running.session_error_reply(
                e, "trace", tail="The file is named in the reply's `trace` block")
        except BaseException:
            with cancel.shielded():          # a cancelled call's cleanup is not cancelled again
                _close(ses, scratch, tag)
            raise
        closed = _close(ses, scratch, tag)
        if closed is False:
            return _unclosed(path, tag, f"raised `{broke['code']}` ({e})")
        return _with_trace(broke, _left(path, closed))
    except BaseException:
        with cancel.shielded():
            _close(ses, scratch, tag)
        raise
    closed = _close(ses, scratch, tag)
    if closed is None and reply.get("status") != "ok":
        return _with_trace(reply, _left(path, None))
    if closed is None:
        return menvelope.invalid("session_broken",
                                 "the session broke before the tracer could be closed: "
                                 f"{ses.broken}. `close` it (closing MAME closes the file), then "
                                 "`start` a new one",
                                 trace=_left(path, None))
    if closed is False:
        verdict = reply.get("verdict") or reply.get("code")
        after = reply.get("frame_after")
        at = f" at frame {after}" if isinstance(after, int) else ""
        return _unclosed(path, tag, f"ended {verdict}{at}")
    if reply.get("status") != "ok":
        return _with_trace(reply, _left(path, True))
    block = _account(path, set_path, tag, mask, noloop, parked, parked_note, reply, ses)
    # listed only once checked and handed back, as `captures` promises: a refused trace's path
    # is in its own reply
    STATE.captures.append(("trace", str(path)))
    return _with_trace(reply, block)


def _unclosed(path: Path, tag: str, run: str) -> dict[str, Any]:
    return menvelope.invalid("readback_refused",
                             f"the run {run}, and the tracer on {tag} could not be shown closed, "
                             f"so it may still be writing and nothing read from it is whole. "
                             f"`stop`, then `debug(\"trace off,{tag}\")`; if `stop` fails, `close` "
                             "then `start` (closing MAME closes the file)",
                             trace=_left(path, False))


def _nothing(ses: gs.Session, tag: str, path: Path, what: str) -> st.Invalid:
    """The refusal of a trace that recorded no executed address: an instrument that examined
    nothing, whose two causes cannot be told apart from the file."""
    ignored = tag in (cpus.ignored(ses) or [])
    return st.Invalid("readback_refused",
                      f"the trace on {tag} {what}: either the cpu executed nothing in the "
                      "window (held, halted, or ignored by the debugger"
                      + (f"; `cpu_info` lists {tag} as ignored" if ignored else "")
                      + ") or the tracer recorded nothing; the two cannot be told apart",
                      trace=_left(path, True))


def _account(path: Path, set_path: Path, tag: str, mask: int | None, noloop: bool,
             parked: int | None, parked_note: str | None, reply: dict[str, Any],
             ses: gs.Session) -> dict[str, Any]:
    """The file read back, the parked edges corrected, the set file written: the `trace` block."""
    size = path.stat().st_size
    notes = [parked_note] if parked_note else []
    if not size:
        raise _nothing(ses, tag, path, "is empty")
    width = len(f"{mask:X}") if mask is not None else None
    if mask is None:
        notes.append(f"{tag} has no program-space row in the inventory, so the pcs were read "
                     "with no width or range judgement")
    try:
        with path.open("rb") as trace_file:
            p = parse(trace_file, width, mask, tag)
    except st.Invalid as refused:
        raise st.Invalid(refused.code, str(refused), **refused.fields,
                         trace=_left(path, True)) from refused
    if not p.lines:
        # the interrupt hook writes for a cpu the instruction hook skips (an ignored one)
        raise _nothing(ses, tag, path, "holds no instruction line, only interrupt lines")
    counts = p.counts
    executed = p.lines + p.loop_sum
    survey_pc = reply.get("pc")
    ended = None
    stopped_on = reply.get("cpu")
    if isinstance(stopped_on, str) and stopped_on != tag:
        notes.append(f"the run stopped on {stopped_on}, not {tag}, so {tag}'s last line is "
                     "the last instruction it began, which a core that yields mid-instruction "
                     "finishes only after the window")
    elif stopped_on == tag and isinstance(survey_pc, str) and p.last_pc == int(survey_pc, 16):
        # the last line is an arrival the window never executed; condensed, an address that
        # also ran earlier stays, since only its last arrival is not an execution. The two edges
        # commute, so the note on the end pc is decided after both: a pc the run started and
        # ended parked on was executed once, first.
        ended = p.last_pc
        executed -= 1
        if noloop or counts[ended] == 1:
            counts[ended] -= 1
            if counts[ended] == 0:
                del counts[ended]
    if parked is not None:
        counts[parked] = counts.get(parked, 0) + 1
        executed += 1
        notes.append(f"the pc {tag} was parked on, {st.hex_addr(parked)}, is counted: the window "
                     "executed it first and the tracer, armed there, does not log it")
    if ended is not None and ended not in counts:
        notes.append(f"the pc the run ended parked on, {survey_pc}, is not in the set: the "
                     "tracer logged it on arrival and the window never executed it")
    if not STATE.table(tag).table:
        notes.append(f"{tag} has no symbol table, so no address is placed")
    rows, summary, unplaced = join(counts, read.placer(tag), noloop)
    account.write_jsonl(set_path, rows)
    block: dict[str, Any] = {
        "cpu": tag, "path": str(path), "bytes": size, "set_path": str(set_path),
        "instructions": executed, "addresses": len(rows), "unplaced": unplaced,
        "symbols": summary[:SYMBOLS_SHOWN], "symbols_total": len(summary),
        "truncated": len(summary) > SYMBOLS_SHOWN, "noloop": noloop,
    }
    return st.add_note(block, *notes)
