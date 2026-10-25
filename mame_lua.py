"""The Lua channel: MAME's own `-console` fed through stdin and read back off stdout, and the
typed wrappers built on it. The bytes of the channel are `mame_transport`'s.

The console evaluates a line from its periodic hook, so a line sent while the machine is
stopped sits in the pipe until the hook next runs (REFERENCE.md, *The console*). Texts a client
reads keep the shortest true form of that, since a client cannot follow a link.

The raw form (`lua`) marks the session altered always and buys its evaluation with a step.
The typed wrappers are queued, evaluated by the advance they make, and prove their effect
through `error.log` (`logerror` is flushed as written; a `print` from a frame notifier would sit
in the stdio buffer). A run cut short leaves a wrapper's notifier armed, and the reply says so.
"""
from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from scry_core import cancel, prose
from scry_core import log_wait as core_wait
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core import vocabulary as vocab
from scry_core.reply_contract import unavailable

import gdb_session as gs
import mame_advance as advance
import mame_envelope as menvelope
import mame_files as files
import mame_inputs as inputs
import mame_running as running
import mame_state as st
import mame_transport as transport
import mame_write as mwrite
from mame_state import STATE

EVAL_WAIT_S = 5.0
# Marks the wrappers write through `logerror`, each followed by the `#<seq>` of its call.
INPUT_MARK = "MAME_MCP_INPUT"
THROTTLE_MARK = "MAME_MCP_THROTTLE"

# Values go in as Lua literals through `lua_string`/ints so a quote in a port tag cannot break
# out. A new script of a family releases the previous notifier first: at most one is armed.
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


# The halves that need no machine: the server asks them before reaching for it.


def check_input(port: str, field: str, frames: int = 4, seconds: float = 30.0,
                **_: Any) -> None:
    """`input`'s machine-independent half. The bound is judged here because a run whose clock
    expired before it starts leaves the field pressed."""
    inputs.count("frames", frames, tail=": an input is held one frame or more")
    if not port or not field:
        raise st.Invalid("bad_argument", "port and field are both needed, as MAME names them "
                                         "(`:P1`, `Coin 1`)")
    vocab.check_wait(seconds)


def check_throttle(on: bool = True, seconds: float = 5.0, **_: Any) -> None:
    """`throttle`'s machine-independent half: the bound on waiting for its mark."""
    vocab.check_wait(seconds)


def check_lua(script: str, seconds: float = EVAL_WAIT_S, **_: Any) -> None:
    """The `lua` tool's machine-independent half."""
    transport.check_script(script)
    vocab.check_wait(seconds)


def lua(ses: gs.Session, scratch: Path, script: str, seconds: float,
        read_only: bool = False,
        progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `lua` tool: altered always unless the caller declares otherwise, one step
    to evaluate.

    `read_only` is the caller's word, unverified and counted in the session block. No classifier
    could judge a Lua string (`debug` classifies by prefix over a closed vocabulary; Lua has
    none), and a call is a write until proven otherwise."""
    check_lua(script, seconds)
    pc_before = ses.current_pc()
    # Refused before counted: a turned-away call never reached the console.
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
    """Refuse a wrapper's own chunk run twice, read off its marks: the sentinel check skips the
    call's own number, but a chunk that ran twice logs each mark twice."""
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
        tagged_lines=seen, **fields)


def one_event(seen: list[str], tag: str, event: str) -> dict[str, str] | None:
    """The fields of the `event` line the wrapper's chunk logged, or None."""
    lines = [ln for ln in seen if f"{tag} {event}" in ln]
    return st.mark_fields(lines[0]) if lines else None


def with_fields(ran: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """The run's reply with the wrapper's fields added before the stop survey (which begins at
    `cause`), or at the end when there is none. A wrapper's `note` joins the run's own."""
    keys = [k for k in ran if k != "session"]
    at = keys.index("cause") if "cause" in keys else len(keys)
    if "note" in fields and "note" in ran:
        fields = {**fields, "note": st.join_notes(ran["note"], fields["note"])}
    out = {k: ran[k] for k in keys[:at] if k not in fields}
    out.update(fields)
    out.update({k: ran[k] for k in keys[at:] if k not in fields})
    return out


def drain_ahead(ses: gs.Session, scratch: Path) -> tuple[int, int]:
    """Step the lines ahead in the pipe off before a wrapper sends its own: how many there
    were, and how many steps that took.

    The console reads one line per hook run, so a wrapper's frames would otherwise go on
    somebody else's line and its notifier come back unreleased."""
    ahead = transport.refuse_if_too_deep(scratch)
    # Verified, not counted out: a step whose line the reader had not taken buys nothing.
    drain_steps = 0
    while transport.pending_lines(scratch) and drain_steps < ahead + transport.PIPE_STEPS_MAX:
        ses.step()
        drain_steps += 1
    return ahead, drain_steps


@contextmanager
def drain_said(ahead: int, drain_steps: int) -> Iterator[None]:
    """Every refusal raised inside carries `lines_ahead` and `drain_steps`."""
    try:
        yield
    except st.Invalid as refusal:
        refusal.fields.setdefault("lines_ahead", ahead)
        refusal.fields.setdefault("drain_steps", drain_steps)
        raise


@contextmanager
def console_said(answer: transport.Answer, resent: int) -> Iterator[None]:
    """Every refusal raised inside, once a wrapper has read its answer, carries the console's
    account of it (`thread_errors`, `console_reruns`, `resent`)."""
    try:
        yield
    except st.Invalid as refusal:
        # The refusal's own fields win; its note joins after the console's.
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
    """Queue `script` on a pipe `drain_ahead` emptied, run `frames` frames, then consume the
    console's framing. Returns the run's stop reply, the answer (None when no sentinel came),
    how many times the line was resent after the reader died holding it, and the frames the run
    spent (a pending reply's survey is the extra step's, not the run's)."""
    # Routed before the send: a refused run would leave the script in the pipe.
    route = advance.route_frames(ses)
    # One bound for the whole call: every run and wait takes what is left of it.
    deadline = time.monotonic() + seconds

    def left(what: str, answer: transport.Answer | None = None) -> float:
        """What is left of the bound for a run, or the refusal of a spent one. With an `answer`
        the script is not pending: the answer came and the frames did not."""
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
        """What is left of the bound for an answer, never less than one last look."""
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
            # The reader died holding the line: resend once; a second death is refused.
            transport.record_lost(seq)
            # The mark moves with the send, or the first line's death would be blamed on
            # the resent one.
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
        # A run does not always evaluate the line; a single step does, on the way into the
        # debugger, and the frames are then bought again for the notifier. The run's frame
        # delta is kept before the step replaces the survey, so prose and numbers agree.
        moved = int(ran.get("frame_after", 0)) - int(ran.get("frame_before", 0))
        stepped = advance.step(ses, scratch, 1)
        answer = _answer_or_none(scratch, line, seq, progress, answer_wait())
        if answer is not None:
            ran = advance.run_for(ses, scratch, 0, left("the frames bought again", answer),
                                  progress, frames=frames)
        else:
            ran = stepped
    # No answer after run and step: said as a reader death, never plain "pending". Only a log
    # that proves the line eaten counts it lost; the console answers more lines after a death,
    # so otherwise it stays ahead in the pipe until `transport._settle_pending` settles it.
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


LAST_LOOK_S = 0.05


def _answer_or_none(scratch: Path, line: str, seq: int, progress: mprogress.Progress,
                    wait: float = EVAL_WAIT_S) -> transport.Answer | None:
    """The answer, or None when the bound expired with the line still in the pipe.

    A broken session is re-raised: catching it would turn a dead emulator into the pending path,
    which reports a machine that will execute again."""
    try:
        return transport.await_answer(scratch, line, seq, wait, progress)
    except st.Invalid as refusal:
        if refusal.code == "session_broken":
            raise
        return None


def not_evaluated(ran: dict[str, Any], what: str, ahead: int, resent: int,
                   moved: int, drain_steps: int) -> dict[str, Any]:
    """The reply for a script with no answer and no reader death in the log since its send.
    The note counts the frames the run spent rather than asserting a zero."""
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
    """A wrapper whose run did not settle: the run's refusal, its message extended with what
    the notifier may still do (`effect`, then `after`), and none of the wrapper's own fields,
    since the machine may still be running."""
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
    """Refuse a script that raised, under `code`: `bad_argument` when the script is the caller's
    own (`lua`), another when it is this server's."""
    if not answer.ok:
        raise st.Invalid(code, f"{what}: the script raised: {answer.error}",
                         **transport.console_did(answer, resent), **fields)


def input_refusal_code(error: str) -> contract.Code:
    """`INPUT_LUA` raises on its own only for a port or field the machine lacks."""
    return "unknown_ref" if ": no port " in error or " has no field " in error else (
        "unexpected_answer")


def input_field(ses: gs.Session, scratch: Path, port: str, field: str, value: int,
                frames: int, seconds: float,
                progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `input` tool: hold a field for `frames`, released by a frame notifier."""
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
                    tagged_lines=seen)
            mask, defvalue = int(set_line["mask"], 16), int(set_line["defvalue"], 16)
            own = dict(route="ioport", port=port, field=field,
                       value=f"0x{value & 0xFFFFFFFF:08x}", frames=frames,
                       name=set_line["name"], player=int(set_line["player"]),
                       mask=f"{mask:#010x}", defvalue=f"{defvalue:#010x}",
                       port_before=f"{int(set_line['port_before'], 16):#010x}",
                       frame_set=int(set_line["frame"]))
            if rel_line is None:
                # Cut short before the release: the field is still held, and said so.
                held_why = unavailable("the field is still HELD: the port is read at its "
                                          "release, which the run has not reached")
                return with_fields(ran, **own, released=False, active=held_why,
                             port_held=held_why,
                             frame_release_planned=int(set_line["frame"]) + frames,
                             note="the field is still HELD: the run stopped before the release "
                                  "frame, and the script releases it when the machine reaches it")
            held = int(rel_line["port_held"], 16)
            return with_fields(ran, **own, released=True, port_held=f"{held:#010x}",
                         frame_released=int(rel_line["frame"]),
                         # Read at the release: a set that never reached the port is inactive.
                         active=(held & mask) != (defvalue & mask))


def throttle(ses: gs.Session, scratch: Path, on: bool, seconds: float,
             progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `throttle` tool: queued, applied when the console next reads a line.
    Running, it waits for its tag in error.log; stopped, it reports the switch pending. It never
    reads stdout, so a reader death around its line is counted by the next call that does."""
    check_throttle(on, seconds)
    mark = files.log_mark(scratch)
    tag = f"{THROTTLE_MARK}#{STATE.lua_seq + 1}"
    script = THROTTLE_LUA % {"on": "true" if on else "false", "mark": tag}
    _line, seq = transport.send(script)

    def pending() -> dict[str, Any]:
        # The record closes the loop: the mark is written only when the console next reads.
        STATE.throttles_pending.append({"tag": tag, "on": on, "seq": seq})
        return menvelope.envelope({"on": on, "pending": True,
                                   "applies": "when the console next reads a line: "
                                   f"{transport.CONSOLE_READS}",
                                   "tag": tag,
                                   "confirmed_by": "its tag in the error log, read by the next "
                                   "stop's survey, by `status` and by `close`; "
                                   "`status` lists it in `throttles_pending` until "
                                   "then, and if the tag never comes, every reply "
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
                    f"for {str(on).lower()}", tagged_lines=seen)
            return menvelope.envelope({"on": on, "pending": False, "frame": int(got["frame"]),
                                       "waited_s": st.spent_s(clock.seconds()), "tag": tag})
        gone = transport.emulator_gone()
        if gone is not None:
            raise transport.died_waiting(gone, "its own throttle tag in error.log", tag=tag)
        if running.came_to_rest(ses, scratch, 0.0):
            # Stopped before the next frame: the line waits in the pipe, recorded as above.
            return pending()
        try:
            expired = clock.expired()
        except BaseException as e:
            if cancel.is_cancellation(e):
                STATE.throttles_pending.append({"tag": tag, "on": on, "seq": seq})
            raise
        if expired:
            # Still in the pipe: recorded so its tag is looked for later.
            STATE.throttles_pending.append({"tag": tag, "on": on, "seq": seq})
            raise st.Invalid("wait_expired",
                f"no {tag} in error.log within {seconds:g} s: the switch is "
                "still pending, and `status` lists it in `throttles_pending`", pending=True,
                tag=tag)
        clock.tick("throttle: waiting for the tag, {elapsed:.0f}s of {seconds:g}s",
                   seconds=seconds)
        time.sleep(core_wait.POLL_S)

