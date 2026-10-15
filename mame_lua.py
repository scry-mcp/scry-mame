"""The Lua CHANNEL, MAME's own `-console` fed through the process's stdin and read back off its
stdout, and the typed wrappers built on it; the bytes of the channel are `mame_transport`'s.

WHY A CHANNEL AT ALL. What the board asked for that is Lua and nothing else: an input by its
name (`field:set_value`), a recording bounded to a stretch (`video:begin_recording`, which
`mame_recording` builds on this channel), and the throttle switched at a PLACE rather than at a
frame decided at launch. The debugger
console, which is all the gdbstub speaks, knows none of them. `-console` is MAME's own Lua
console: it reads a line from stdin, loads it as a chunk, runs it and prints the prompt
again, and it works with no terminal attached (linenoise falls back to a plain line read and
ECHOES the line).

WHAT WAS MEASURED, and shapes everything here. The console evaluates a line from its
PERIODIC hook, so a line sent while the machine is STOPPED sits in the pipe until the hook
next runs: what runs it is stated once, in REFERENCE.md under *The console* ("The console
evaluates when its periodic hook runs"); this module points there, and the texts a client
reads (`throttle`'s description and `applies`, a tap's install `note`) keep its
shortest true form, since a client cannot follow a link. A wrapper's marks in `error.log`
carry the sequence number the transport gives each call, so a mark a cut-short run leaves
behind is never attributed to a later call.

The recordings, `record` and the run `audio_record` shares, and `captures` are
`mame_recording`'s, built on the queued run here.

THE HONESTY RULE. A Lua string can read a byte or rewrite the whole of RAM and nothing in
the text says which, so the raw form (`lua`) marks the session ALTERED always and buys its
evaluation with a step the reply declares (`pc_before`, `pc`). The typed wrappers are
scripts THIS SERVER composed, each knowing what it does: they are QUEUED and evaluated by
the advance the wrapper itself makes, and they prove their effect through `error.log`
(`logerror` is flushed as it is written; a `print` from a frame notifier would sit in the
stdio buffer until the next prompt). A run cut short by another stop leaves a wrapper's
notifier armed, so the reply SAYS what is left behind and when the notifier will act.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from scry_core import reply_contract as contract

import gdb_session as gs
import mame_advance as advance
import mame_envelope as menvelope
import mame_files as files
import mame_inputs as inputs
import mame_progress as mprogress
import mame_prose as prose
import mame_running as running
import mame_state as st
import mame_transport as transport
import mame_write as mwrite
from mame_state import STATE

# A Lua call's default bound for its answer: the machine ticks within a frame when it runs, and
# at once on the step the raw form makes.
EVAL_WAIT_S = 5.0
# The marks the wrappers' scripts write through `logerror`, each followed by `#<seq>` of the
# call that sent it (a chunk's own last line is `st.sentinel_line`).
INPUT_MARK = "MAME_MCP_INPUT"
THROTTLE_MARK = "MAME_MCP_THROTTLE"

# The wrappers' scripts. Each is one chunk; the values are substituted as Lua LITERALS
# through `lua_string`/ints so a port tag with a quote in it cannot break out of the string.
# A wrapper's notifier is kept under a global; a new script of the same family RELEASES the
# previous one's effect first, so at most one is ever armed.
INPUT_LUA = """if _G._mame_mcp_input_release then _G._mame_mcp_input_release() end
local p = manager.machine.ioport.ports[%(port)s]
if p == nil then error("no port " .. %(port)s) end
local f = p.fields[%(field)s]
if f == nil then error("port " .. %(port)s .. " has no field " .. %(field)s) end
local screen = nil
for _, s in pairs(manager.machine.screens) do screen = s break end
local start = screen and screen:frame_number() or -1
local before = p:read()
f:set_value(%(value)d)
local done = false
_G._mame_mcp_input_release = function() done = true f:clear_value() end
_G._mame_mcp_input = emu.add_machine_frame_notifier(function()
    if done then return end
    local frame = screen and screen:frame_number() or -1
    if frame - start >= %(frames)d then
        done = true
        local held = p:read()
        f:clear_value()
        manager.machine:logerror(string.format(
            "%(mark)s release frame=%%d port_held=%%08x\\n", frame, held))
    end
end)
manager.machine:logerror(string.format(
    "%(mark)s set name=%%q player=%%d mask=%%08x defvalue=%%08x port_before=%%08x frame=%%d\\n",
    f.name, f.player, f.mask, f.defvalue, before, start))
"""

THROTTLE_LUA = """manager.machine.video.throttled = %(on)s
local screen = nil
for _, s in pairs(manager.machine.screens) do screen = s break end
manager.machine:logerror(string.format("%(mark)s throttled=%%s frame=%%d\\n",
    tostring(manager.machine.video.throttled), screen and screen:frame_number() or -1))
"""


# THE SIGNATURE A REPO'S OWN LUA COMPUTES BY HAND: a grid of pixels
# spread over the screen, folded into one number; enough to say whether the image CHANGED,
# which is the only direct proof that a scene is painting. The formula is that script's, so
# a number this tool answers compares with one the repo's own script printed.
SIG_LUA = """local screen = nil
for _, s in pairs(manager.machine.screens) do screen = s break end
if screen == nil then error("no screen") end
local w, h = screen.width, screen.height
local n = %(grid)d
local cw, ch, ox, oy = %(cell_w)s, %(cell_h)s, %(offset_x)s, %(offset_y)s
if cw and (ox + (n - 1) * cw >= w or oy + (n - 1) * ch >= h) then
  print(string.format("MAME_MCP_SIG_OFFSCREEN w=%%d h=%%d", w, h))
  return
end
local sig = 0
for gy = 0, n - 1 do
  for gx = 0, n - 1 do
    local x, y
    if cw then
      x, y = ox + gx * cw, oy + gy * ch
    else
      x = math.floor(gx * w / n + w / (2 * n))
      y = math.floor(gy * h / n + h / (2 * n))
    end
    sig = (sig * 31 + screen:pixel(x, y)) %% 0x7fffffff
  end
end
print(string.format("MAME_MCP_SIG w=%%d h=%%d grid=%%d sig=%%d", w, h, n, sig))
"""
_SIG_LINE = re.compile(r"MAME_MCP_SIG w=(\d+) h=(\d+) grid=(\d+) sig=(\d+)")
# A LATTICE THAT LEAVES THE SCREEN folds MAME's off-screen zero (`screen_device::pixel`,
# src/emu/screen.cpp) into the number, which then stays the same whatever the screen shows: the
# script refuses it with the screen's size, which only the machine knows.
_SIG_OFFSCREEN = re.compile(r"MAME_MCP_SIG_OFFSCREEN w=(\d+) h=(\d+)")
GRID_MIN, GRID_MAX = 2, 64


# ---------------------------------------------------- the halves that need no machine
#
# Each is the machine-independent half of one tool in this module, exposed so the server can ask it
# BEFORE it reaches for the live machine and so the tool below asks the same function rather than a
# copy of it. What is NOT here is anything the emulator decides: whether the script RUNS, whether
# the port and field MAME names exist, whether a frame ever arrives.


def check_input(port: str, field: str, frames: int = 4, seconds: float = 30.0,
                **_: Any) -> None:
    """`input`'s machine-independent half: that both names were GIVEN, how many frames, and the
    bound. Whether MAME has a port by that name is the machine's answer and comes back from it. The
    bound is judged here and not by the run: a run whose clock has expired before it starts leaves
    the field pressed and reports a frame that never came."""
    inputs.count("frames", frames, tail=": an input is held one frame or more")
    if not port or not field:
        raise st.Invalid("bad_argument", "port and field are both needed, as MAME names them "
                                         "(`:P1`, `Coin 1`)")
    inputs.seconds_bound(seconds)


def check_throttle(on: bool = True, seconds: float = 5.0, **_: Any) -> None:
    """`throttle`'s machine-independent half: the bound on waiting for its mark. Unjudged, a zero
    reads as a measurement that expired rather than as the malformed argument it is."""
    inputs.seconds_bound(seconds)


#: `screen_signature`'s `cell` and `origin` with no lattice asked: the grid divides the screen.
NO_LATTICE_WHY = "no lattice was given, so the grid divides the screen evenly"


def check_screen_signature(grid: int = 8, seconds: float = EVAL_WAIT_S,
                           cell: list[int] | None = None,
                           origin: list[int] | None = None, **_: Any) -> None:
    """`screen_signature`'s machine-independent half: the grid, the bound, and the lattice's shape.
    Where the screen IS, and how big, is the machine's."""
    inputs.count("grid", grid, GRID_MAX, ": a side of the sample grid", lo=GRID_MIN)
    inputs.seconds_bound(seconds)
    if (cell is None) != (origin is None):
        raise st.Invalid("bad_argument", "`cell` and `origin` come together: a lattice is both")
    if cell is not None and origin is not None and not (
            inputs.is_naturals(cell, 2, 1) and inputs.is_naturals(origin, 2)):
        raise st.Invalid("bad_argument",
            "`cell` is [width, height] above zero and `origin` [x, y] at or above zero")


def check_lua(script: str, seconds: float = EVAL_WAIT_S, **_: Any) -> None:
    """The `lua` TOOL's machine-independent half: the script, and the bound on waiting for it."""
    transport.check_script(script)
    inputs.seconds_bound(seconds)


def screen_signature(ses: gs.Session, scratch: Path, grid: int, seconds: float,
                     cell: list[int] | None = None, origin: list[int] | None = None,
                     progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `screen_signature` tool: `grid` x `grid` pixels, one number. With
    `cell` (width, height) and `origin` (x, y) the sample is `origin + index * cell`, the
    fixed lattice a repo's own script uses, which is not always the centred one; without
    them each cell of the screen is sampled at its
    centre."""
    check_screen_signature(grid, seconds, cell, origin)
    lattice = ({"cell_w": cell[0], "cell_h": cell[1], "offset_x": origin[0], "offset_y": origin[1]}
               if cell is not None and origin is not None else
               {"cell_w": "nil", "cell_h": "nil", "offset_x": "nil", "offset_y": "nil"})
    pc_before = ses.current_pc()
    answer, ahead, evaluated_by, reader_steps, resent, seq = transport.evaluate(
        ses, scratch, SIG_LUA % {"grid": grid, **lattice}, seconds, progress, pc_before,
        alters=False)
    if not answer.ok:
        raise st.Invalid("unexpected_answer", f"the signature script raised: {answer.error}",
                         pc_before=st.hex_addr(pc_before), **transport.console_did(answer, resent))
    off = _SIG_OFFSCREEN.search(answer.text)
    if off is not None:
        assert cell is not None and origin is not None       # the script checks a lattice only
        raise st.Invalid("bad_argument",
            f"the lattice origin {origin} + {grid - 1} x cell {cell} leaves the "
            f"{off.group(1)}x{off.group(2)} screen, where MAME reads every pixel as 0 and the "
            "signature would not change whatever is drawn",
                         pc_before=st.hex_addr(pc_before), **transport.console_did(answer, resent))
    m = _SIG_LINE.search(answer.text)
    if m is None:
        raise st.Invalid("unexpected_answer",
            f"the console printed no signature line: {answer.text.strip()[-200:]!r}",
                         pc_before=st.hex_addr(pc_before), **transport.console_did(answer, resent))
    return running.stop_reply(ses, scratch, f"screen_signature: {evaluated_by}",
                              signature=int(m.group(4)), grid=int(m.group(3)),
                              width=int(m.group(1)), height=int(m.group(2)),
                              cell=st.or_unavailable(cell, NO_LATTICE_WHY),
                              origin=st.or_unavailable(origin, NO_LATTICE_WHY),
                              evaluated_by=evaluated_by, lines_ahead=ahead,
                              reader_steps=reader_steps, **transport.console_did(answer, resent),
                              call=st.sentinel_line(seq), pc_before=st.hex_addr(pc_before))


def lua(ses: gs.Session, scratch: Path, script: str, seconds: float,
        read_only: bool = False,
        progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `lua` tool: the raw form, altered always unless the caller declares
    otherwise, one step to evaluate.

    `read_only` IS THE CALLER'S WORD AND IS RECORDED AS SUCH. The default stays what it was,
    and it is the honest one: a Lua string can read a byte or rewrite the whole of RAM and
    nothing in the text says which, so a call is a write until proven otherwise. What that
    cost in practice is that one `print` stamped a session that only ever read with
    "MODIFIED" for the rest of its life, after which the flag said nothing about anything.
    There is no classifier that could judge this honestly: `debug` classifies by prefix over a
    CLOSED command vocabulary, and Lua has none, so a prefix rule here would be a guess
    wearing a measurement's clothes. So the claim is the caller's, it is not verified, and
    it is never silent: the session block counts the claims and says whose word they are."""
    check_lua(script, seconds)
    pc_before = ses.current_pc()
    # REFUSED BEFORE IT IS COUNTED: a call turned away for a pipe somebody else filled, or for a
    # script that is empty or too long, never reached the console, and counting it would put a
    # write (or a read_only claim) in the session block for something that did not happen.
    transport.refuse_if_too_deep(scratch)
    if read_only:
        STATE.lua_read_only_claims += 1
    else:
        STATE.lua_calls += 1
    answer, ahead, evaluated_by, reader_steps, resent, seq = transport.evaluate(
        ses, scratch, script, seconds, progress, pc_before, alters=not read_only)
    refuse_if_raised(answer, "lua", resent, pc_before=st.hex_addr(pc_before), output=answer.text)
    hint: dict[str, str] = {}
    if not answer.text and "print" not in script:
        # Two repos wrote `return x`, read an empty `output` beside `ok`, and could not tell
        # it from a silent failure: the console captures what prints and nothing else.
        hint["note"] = ("no output: the console captures what the script `print`s, and a "
                        "`return` value never reaches it; print what you want back")
    return running.stop_reply(ses, scratch, f"lua: {evaluated_by}", script_chars=len(script),
                              evaluated_by=evaluated_by, lines_ahead=ahead,
                              reader_steps=reader_steps, call=st.sentinel_line(seq),
                              pc_before=st.hex_addr(pc_before),
                              **st.merged(transport.console_did(answer, resent),
                                          mwrite.clip_text(answer.text, scratch, "lua"), hint))


def marks_since(scratch: Path, mark: int, tag: str) -> list[str]:
    lines, _ = files.errorlog_since(scratch, mark)
    return st.mark_lines(lines, tag)


def refuse_a_rerun(seen: list[str], tag: str, answer: transport.Answer, resent: int,
                   **fields: Any) -> None:
    """A wrapper's OWN chunk run twice, read off its own marks. The sentinel check cannot see
    it, because the call's own number is the one it skips, but a chunk that ran twice logs
    each of its marks twice, and a recording begun twice on one file or a field set twice
    is not an `ok`. Every repeat beyond the first is listed and held against the session."""
    counts: dict[str, int] = {}
    for ln in seen:
        m = re.search(re.escape(tag) + r"(?!\d) (\w+)", ln)
        if m:
            event = f"{tag} {m.group(1)}"
            counts[event] = counts.get(event, 0) + 1
    repeats = [event for event, n in counts.items() for _ in range(n - 1)]
    if not repeats:
        return
    STATE.console_reruns_seen += len(repeats)
    raise st.Invalid("console_rerun",
        f"the console ran this call's chunk more than once: {', '.join(repeats)} logged "
        "again, so whatever the script does was done twice and the reply would describe "
                     "neither run", **{**transport.console_did(answer, resent),
                                       "console_reruns": len(answer.reruns) + len(repeats)},
        marks=seen, **fields)


def one_event(seen: list[str], tag: str, event: str) -> dict[str, str] | None:
    """The fields of the ONE `event` line the wrapper's chunk logged, or None when it logged
    none. One, because `refuse_a_rerun` has already refused a chunk that logged two."""
    lines = [ln for ln in seen if f"{tag} {event}" in ln]
    return st.mark_fields(lines[0]) if lines else None


def with_fields(ran: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """The run's reply with the wrapper's own fields added where the docstrings list them:
    before the stop survey, which begins at `how`; a run with no survey (a refusal) takes them
    at the end. The `session` block is the server's `tool`'s, composed after this call read
    its answer, so it agrees with the console counters that answer moved. A `note` the wrapper
    adds joins the run's own, after it."""
    keys = [k for k in ran if k != "session"]
    at = keys.index("how") if "how" in keys else len(keys)
    if "note" in fields and "note" in ran:
        fields = {**fields, "note": st.join_notes(ran["note"], fields["note"])}
    out = {k: ran[k] for k in keys[:at] if k not in fields}
    out.update(fields)
    out.update({k: ran[k] for k in keys[at:] if k not in fields})
    return out


def drain_ahead(ses: gs.Session, scratch: Path) -> tuple[int, int]:
    """Step the lines ahead in the pipe off before a wrapper sends its own: how many there
    were, and how many steps that took (`drain_steps`).

    THE PIPE IS DRAINED FIRST, the raw form's rule. A `throttle` asked while stopped leaves
    its line there, and the console reads one line each time its hook runs: a wrapper that
    just ran its own frames spent them on somebody else's line and came back with its notifier never
    released (measured live on v30: `input` behind a backlog answered `released: false`,
    the field still held). So the lines ahead are stepped off first, and the frames the
    wrapper asks for are then its own."""
    ahead = transport.refuse_if_too_deep(scratch)
    # THE BACKLOG IS STEPPED OFF AND THE STEPPING IS VERIFIED, not counted out and trusted:
    # a step whose line the reader had not taken buys nothing, and sending this script on
    # top of a pipe that did not clear is the very thing this drain exists to prevent.
    drain_steps = 0
    while transport.pending_lines(scratch) and drain_steps < ahead + transport.PIPE_STEPS_MAX:
        ses.step()
        drain_steps += 1
    return ahead, drain_steps


@contextmanager
def drain_said(ahead: int, drain_steps: int) -> Iterator[None]:
    """Every refusal raised inside carries the pipe's depth and the drain's steps
    (`lines_ahead`, `drain_steps`): they were spent whatever the call ends in."""
    try:
        yield
    except st.Invalid as refusal:
        refusal.fields.setdefault("lines_ahead", ahead)
        refusal.fields.setdefault("drain_steps", drain_steps)
        raise


@contextmanager
def console_said(answer: transport.Answer, resent: int) -> Iterator[None]:
    """Every refusal raised inside, once a wrapper has read its chunk's answer, carries the
    console's account of that answer (`thread_errors`, `console_reruns`, `resent`), as the ok
    reply and the chunk readers' refusals do: a refusal of what the answer showed is still a
    reply that read it."""
    try:
        yield
    except st.Invalid as refusal:
        # THE REFUSAL'S OWN FIELDS WIN, its note joined after the console's.
        console = transport.console_did(answer, resent)
        note = st.join_notes(console.get("note"), refusal.fields.get("note"))
        refusal.fields = {**console, **refusal.fields}
        if note is not None:
            refusal.fields["note"] = note
        raise


def queued_then_ran(ses: gs.Session, scratch: Path, script: str, frames: int, seconds: float,
                    progress: mprogress.Progress) -> tuple[dict[str, Any],
                                                           transport.Answer | None, int,
                                                           int]:
    """Queue `script` on a pipe `drain_ahead` emptied, run `frames` frames (the run evaluates it
    on its first frame), then consume the console's framing for it. Returns the run's stop
    reply, the answer (None when no sentinel for the script came), how many times the line
    was sent again after the reader died holding it, and how many FRAMES the run spent (kept
    separately because a pending reply's survey is the extra step's, not the run's)."""
    # THE RUN IS ROUTED BEFORE THE SCRIPT IS SENT: a run by frames the build refuses would
    # otherwise leave the script in the pipe, for some later call's step to evaluate.
    route = advance.route_frames(ses)
    # ONE BOUND FOR THE WHOLE CALL, the caller's `seconds`: every run and every wait for the
    # answer below takes what is LEFT of it, so a resend or a second run never stretches the
    # call past what was asked. A retry the bound has no room for is refused, not taken.
    deadline = time.monotonic() + seconds

    def left(what: str, answer: transport.Answer | None = None) -> float:
        """What is left of the bound for a RUN, or the refusal of a spent one. A script with an
        `answer` is not pending: the refusal says the answer came and the frames did not, and,
        raised past an answer, carries the console's account of it as every such refusal does."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if answer is not None:
                raise st.Invalid("wait_expired",
                    f"the {seconds:g} s bound ran out before {what}: the script answered at the "
                    f"step, but its {prose.counted(frames, 'frame')} "
                    f"{prose.agrees(frames, 'was', 'were')} not run, so what it does over "
                    f"{prose.agrees(frames, 'it', 'them')} is not done; ask again with a longer "
                    "`seconds`", pending=False,
                                 **transport.console_did(answer, resent))
            raise st.Invalid("wait_expired",
                f"the {seconds:g} s bound ran out before {what}: the script was sent and its "
                "answer is not in; `log` on the `process` channel shows it when it lands",
                pending=True)
        return remaining

    def answer_wait() -> float:
        """What is left of the bound for an ANSWER, never less than one last look: a spent
        bound is the pending path's to report, which says what the run did."""
        return min(EVAL_WAIT_S, max(deadline - time.monotonic(), LAST_LOOK_S))

    mark = transport.stdout_mark(scratch)
    line, seq = transport.send(script)
    ran = advance.run_for(ses, scratch, 0, left("the run"), progress, frames=frames, route=route)
    answer = _answer_or_none(scratch, line, seq, progress, answer_wait())
    resent = 0
    moved = 0
    if answer is None:
        _, raw = transport.find_answer(scratch, line, seq)
        if transport.eaten(raw, line):
            # THE READER DIED HOLDING THE LINE: never evaluated, so it is sent once more
            # and the frames bought again; a second death is the refusal `evaluate` gives.
            transport.record_lost(seq)
            # THE MARK MOVES WITH THE SEND. The death that made us resend printed its own
            # `[LUA ERROR] in thread`, and it is behind us: read from before it and this
            # call would diagnose the resent line as dead on the strength of the FIRST
            # line's death, which it already handled.
            mark = transport.stdout_mark(scratch)
            line, seq = transport.send(script)
            resent = 1
            ran = advance.run_for(ses, scratch, 0, left("the resent line's run"), progress,
                                  frames=frames)
            answer = _answer_or_none(scratch, line, seq, progress, answer_wait())
            if answer is None:
                _, raw = transport.find_answer(scratch, line, seq)
                if transport.eaten(raw, line):
                    transport.record_lost(seq)
                    raise st.Invalid("reader_died", transport.DIED_TWICE, pending=False,
                                     resent=resent,
                                     thread_errors=raw.count(transport.THREAD_ERROR),
                                     console_reruns=len(transport.reruns_in(raw, seq)))
    if answer is None:
        # THE RUN DID NOT ALWAYS EVALUATE THE LINE (measured: the same five recordings came
        # back complete on one run and two of them pending on another, with the chunk still
        # in the pipe). A single step does, on the way into the debugger; then the frames
        # are bought again so the script's notifier can do its work.
        # THE RUN'S FRAME DELTA IS KEPT BEFORE THE STEP REPLACES THE SURVEY: the note owes
        # the caller the frames the RUN spent, and the pc/frame fields owe them the machine
        # as it stands NOW. Reporting the run's survey after stepping past it made the
        # reply's prose ("and one step") describe a machine its own numbers predated.
        moved = int(ran.get("frame_after", 0)) - int(ran.get("frame_before", 0))
        stepped = advance.step(ses, scratch, 1)
        answer = _answer_or_none(scratch, line, seq, progress, answer_wait())
        if answer is not None:
            ran = advance.run_for(ses, scratch, 0, left("the frames bought again", answer),
                                  progress, frames=frames)
        else:
            ran = stepped
    # NO ANSWER AFTER THE RUN AND THE STEP, AND A READER DEATH SINCE THE SEND. Said as a
    # death, never as a plain "pending": a caller told only to step again would not know the
    # reader went. The step can have handed the line to a reader that died holding it, and
    # then the log proves it eaten; otherwise it is NOT COUNTED LOST: the console answers
    # more lines after a death (the capture `tests/fixtures/console/session.volume.stdout`),
    # so it stays ahead in the pipe until the log settles it (`transport._settle_pending`).
    after = transport.since(scratch, mark)
    if answer is None and transport.eaten(after, line):
        transport.record_lost(seq)
        raise st.Invalid("reader_died",
            "the console's reader took the line at the step after the run and died holding "
            "it (its echo, a failure after it, and no sentinel): the script was NEVER "
            "evaluated and is counted lost. `close` and start again for a channel known to "
                         "be whole", pending=False, resent=resent,
                         thread_errors=after.count(transport.THREAD_ERROR))
    if answer is None and transport.THREAD_ERROR in after:
        raise st.Invalid("reader_died",
            "the console's reader died after the line was sent (a `[LUA ERROR] in "
            "thread` is in the log since then) and no sentinel for the line came after "
            "the run and one more step: the script has NOT been evaluated yet, and it may "
            "still run on a later reader, at whatever frame that reader takes it; it stays "
            "ahead in the pipe, where `status` counts it. `close` and start again for a "
            "channel known to be whole",
            pending=True, resent=resent, thread_errors=after.count(transport.THREAD_ERROR))
    return ran, answer, resent, moved


# The shortest wait for an answer once the call's bound is spent: one more look at the log.
LAST_LOOK_S = 0.05


def _answer_or_none(scratch: Path, line: str, seq: int, progress: mprogress.Progress,
                    wait: float = EVAL_WAIT_S) -> transport.Answer | None:
    """The answer, or None when the bound expired with the line still in the pipe.

    IT SWALLOWS ONE REFUSAL AND NOT THE OTHER. "No answer yet" is this function's whole
    business and its callers go on to run more frames for it. A BROKEN SESSION is not that:
    nothing later in this call can make a dead emulator answer, and catching it here would
    turn it into the pending path, which reports a machine that will execute again. A bare
    `except` made the liveness check above unreachable from `input` and `record`."""
    try:
        return transport.await_answer(scratch, line, seq, wait, progress)
    except st.Invalid as refusal:
        if refusal.code == "session_broken":
            raise
        return None


def not_evaluated(ran: dict[str, Any], what: str, ahead: int, resent: int,
                   moved: int, drain_steps: int) -> dict[str, Any]:
    """The reply for a script with no answer and no reader death in the log since its send.

    THE NOTE NAMES WHAT THIS RUN ACTUALLY DID. A flat "the machine did not emulate a frame"
    beside `frame_before`/`frame_after` differing by five in the same reply is a message
    contradicting its own numbers. The frames are the reply's own, so the note counts them
    instead of asserting a zero."""
    ran = with_fields(ran, lines_ahead=ahead, drain_steps=drain_steps, reader_steps=0,
                      resent=resent)
    twice = (f" It was sent {prose.counted(resent + 1, 'time')}: the console took the first and "
             "never evaluated it (its echo with a failure after it and no sentinel), and this is "
             "about the second." if resent else "")
    return with_fields(ran, pending=True,
                 note=f"the {what} script has no answer after {prose.counted(moved, 'frame')} and "
                      f"one step, with {prose.counted(ahead, 'line')} ahead of it when it was "
                      "sent: no sentinel for it is in the log and no reader death since it was "
                      "sent, so it counts as pending, and the console evaluates a line only when "
                      f"its hook runs.{twice}")


def unsettled(ran: dict[str, Any], subject: str, effect: str, after: str, ahead: int,
              drain_steps: int, answer: transport.Answer | None, resent: int,
              **fields: Any) -> dict[str, Any]:
    """A wrapper whose run did not settle: the run's own refusal, its message carried on with
    what the script did and what its notifier may still do (`effect`, then `after`, the way to
    learn the outcome), and never the wrapper's own fields beside it. The machine may still be
    running, so nothing read off it now is a state of what the script set up."""
    console = {} if answer is None else transport.console_did(answer, resent)
    left = ("its script may not have been evaluated yet" if answer is None else
            f"its script raised ({answer.error}), so it armed nothing" if not answer.ok else
            "its script was evaluated, and its frame notifier may still be armed")
    return with_fields(ran, message=f"{ran.get('message', 'the run did not settle')}. The "
                       f"{subject}'s state is not read: {left}, and {effect} on a frame the "
                       f"machine reaches; {after}", **fields, lines_ahead=ahead,
                       drain_steps=drain_steps, **(console or {"resent": resent}))


def refuse_if_raised(answer: transport.Answer, what: str, resent: int,
                     code: contract.Code = "bad_argument",
                     **fields: Any) -> None:
    """The refusal of a script that raised, under `code`: `bad_argument` when the script is the
    caller's own (`lua`), another when it is this server's, which raises on its own only when
    the caller named what does not exist, or when the machine answered what it was not built
    for."""
    if not answer.ok:
        raise st.Invalid(code, f"{what}: the script raised: {answer.error}",
                         **transport.console_did(answer, resent), **fields)


def input_refusal_code(error: str) -> contract.Code:
    """`INPUT_LUA` raises on its own for a port or a field the machine lacks, which is a name
    resolving to nothing; anything else it raises the server did not expect."""
    return "unknown_ref" if ": no port " in error or " has no field " in error else (
        "unexpected_answer")


def input_field(ses: gs.Session, scratch: Path, port: str, field: str, value: int,
                frames: int, seconds: float,
                progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `input` tool: hold a field for `frames`, released by the script's own
    frame notifier, and read the port back at the release."""
    check_input(port, field, frames, seconds)
    mark = files.log_mark(scratch)
    tag = f"{INPUT_MARK}#{STATE.lua_seq + 1}"
    script = INPUT_LUA % {"port": transport.lua_string(port), "field": transport.lua_string(field),
                          "value": value, "frames": frames, "mark": tag}
    advance.refuse_frameless("`input`, held for frames,")   # before the drain, which steps
    ahead, drain_steps = drain_ahead(ses, scratch)
    with drain_said(ahead, drain_steps):
        ran, answer, resent, moved = queued_then_ran(
            ses, scratch, script, frames + 1, seconds, progress)
        if ran.get("status") != "ok":
            return unsettled(ran, "input", f"holds or releases {port} {field}",
                             "`stop`, and the next `input` releases it first", ahead,
                             drain_steps, answer, resent)
        if answer is None:
            return not_evaluated(ran, "input", ahead, resent, moved, drain_steps)
        with console_said(answer, resent):
            refuse_if_raised(answer, f"input {port} {field}", resent,
                             input_refusal_code(answer.error or ""))
            ran = with_fields(ran, lines_ahead=ahead, drain_steps=drain_steps, reader_steps=0,
                              **transport.console_did(answer, resent))
            seen = marks_since(scratch, mark, tag)
            refuse_a_rerun(seen, tag, answer, resent)
            set_line, rel_line = one_event(seen, tag, "set"), one_event(seen, tag, "release")
            if set_line is None:
                raise st.Invalid("readback_refused",
                    "the script ran and logged no `set` mark: the field was not proved held",
                    marks=seen)
            mask, defvalue = int(set_line["mask"], 16), int(set_line["defvalue"], 16)
            own = dict(route="ioport", port=port, field=field,
                       value=f"0x{value & 0xFFFFFFFF:08x}", frames=frames,
                       name=set_line["name"], player=int(set_line["player"]),
                       mask=f"{mask:#010x}", defvalue=f"{defvalue:#010x}",
                       port_before=f"{int(set_line['port_before'], 16):#010x}",
                       frame_set=int(set_line["frame"]))
            if rel_line is None:
                # THE RUN WAS CUT SHORT (another stop, or its bound) before the notifier released
                # the field: it is STILL HELD, and the notifier releases it at the frame named
                # here, on whatever run reaches it. Said in the reply, never hidden in a refusal.
                held_why = st.unavailable("the field is still HELD: the port is read at its "
                                          "release, which the run has not reached")
                return with_fields(ran, **own, released=False, active=held_why,
                             port_held=held_why,
                             frame_release_planned=int(set_line["frame"]) + frames,
                             note="the field is still HELD: the run stopped before the release "
                                  "frame, and the script releases it when the machine reaches it")
            held = int(rel_line["port_held"], 16)
            return with_fields(ran, **own, released=True, port_held=f"{held:#010x}",
                         frame_released=int(rel_line["frame"]),
                         # ACTIVE is read off the port itself at the release, against the field's
                         # own default: a set that never reached the port reads inactive here.
                         active=(held & mask) != (defvalue & mask))


def throttle(ses: gs.Session, scratch: Path, on: bool, seconds: float,
             progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `throttle` tool: queued, applied when the console next reads a
    line. Running, the tool waits for its own mark; stopped, it says the switch is
    pending and names the mark to wait for. It proves itself by the mark in error.log and
    never reads stdout, so it carries no `thread_errors`/`console_reruns`: a reader death
    around its line is counted by the next call that does read the console."""
    check_throttle(on, seconds)
    mark = files.log_mark(scratch)
    tag = f"{THROTTLE_MARK}#{STATE.lua_seq + 1}"
    script = THROTTLE_LUA % {"on": "true" if on else "false", "mark": tag}
    _line, seq = transport.send(script)

    def pending() -> dict[str, Any]:
        # THE RECORD IS WHAT CLOSES THE LOOP: on a stopped machine the mark is written only
        # when the console next reads the line, which this call cannot wait for. What the
        # record MEANS is `REFERENCE.md`'s, once.
        STATE.throttles_pending.append({"mark": tag, "on": on, "seq": seq})
        return menvelope.envelope({"on": on, "pending": True,
                                   "applies": "when the console next reads a line: "
                                   f"{transport.CONSOLE_READS}",
                                   "mark": tag,
                                   "confirmed_by": "its mark in the error log, read by the next "
                                   "stop's survey, by `status` and by `close`; "
                                   "`status` lists it in `throttles_pending` until "
                                   "then, and if the mark never comes, every reply "
                                   "after that says so in "
                                   "`session.throttles_not_applied`"})

    if not ses.running:
        return pending()
    clock = mprogress.Ticker(seconds, progress)
    while True:
        seen = marks_since(scratch, mark, tag)
        if seen:
            got = st.mark_fields(seen[-1])
            if got.get("throttled") != ("true" if on else "false"):
                raise st.Invalid("readback_refused",
                    f"the machine reports throttled={got.get('throttled')} after asking "
                    f"for {str(on).lower()}", marks=seen)
            return menvelope.envelope({"on": on, "pending": False, "frame": int(got["frame"]),
                                       "waited_s": st.spent_s(clock.seconds()), "mark": tag})
        gone = transport.emulator_gone()
        if gone is not None:
            raise transport.died_waiting(gone, "its own throttle mark in error.log", mark=tag)
        if running.came_to_rest(ses, scratch, 0.0):
            # A STOP BEFORE THE NEXT FRAME: the line waits in the pipe exactly as it does on a
            # machine that was stopped already, and is recorded the same way.
            return pending()
        if clock.expired():
            # STILL IN THE PIPE, and applied whenever it is evaluated: recorded, so its mark is
            # looked for later and its absence is said, never lost with this refusal.
            STATE.throttles_pending.append({"mark": tag, "on": on, "seq": seq})
            raise st.Invalid("wait_expired",
                f"no {tag} mark in error.log within {seconds:g} s: the switch is "
                "still pending, and `status` lists it in `throttles_pending`", pending=True,
                mark=tag)
        clock.tick("throttle: waiting for the mark, {elapsed:.0f}s")
        time.sleep(files.LOG_POLL_S)

