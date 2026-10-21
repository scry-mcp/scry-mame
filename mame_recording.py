"""The recordings: `record`'s AVI and the run every recording bounded by the frame notifier
makes (`audio_record`'s WAV is the other), and `captures`, which re-reads every file this
session handed back.

A recording is a wrapper on the Lua channel (`mame_lua`): its script is queued on a drained
pipe, evaluated by the run the wrapper makes, and proves itself through its marks in
`error.log`. What lives here is what only a recording does: the notifier that begins and ends
the file from one place in the frame, the `armed` line that predicts where a notifier the
debugger evaluated will first run, the replies of a recording not yet begun, still open, or
whose run did not settle, and the check of the finished file.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple

from scry_core import avi
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_advance as advance
import mame_envelope as menvelope
import mame_files as files
import mame_inputs as inputs
import mame_lua as mlua
import mame_read as read
import mame_state as st
import mame_transport as transport
from mame_state import STATE

# The mark `record`'s script writes through `logerror`, followed by `#<seq>` of the call that
# sent it, as every wrapper's mark is (`mame_lua`).
RECORD_MARK = "MAME_MCP_RECORD"

# WHERE A RECORDING SCRIPT'S NOTIFIER FIRST RUNS, logged by the chunk as it is evaluated, its last
# line (after the host script's own `local screen`), so a chunk that answered has logged it. It
# is read only when no `begin` followed, which is a chunk the debugger evaluated at a stop: one
# the running frame update evaluates has its notifier called right after it, in that same
# update (`video.cpp`). MAME calls the frame notifiers from the frame update at the START of a
# vblank and moves the frame counter at its END (`vblank_begin` and `vblank_end` in
# `src/emu/screen.cpp`): a chunk evaluated at a stop inside a vblank is first called on the
# next frame, one in the active display on the frame the counter already reads, and a screen
# with no vblank period is never inside one. Inside a vblank its end comes before the next
# one's start, which is the test. A driver that asks MAME to update AFTER the vblank
# (`VIDEO_UPDATE_AFTER_VBLANK`) has its notifiers called at the end instead, which Lua cannot
# see: on such a screen a chunk evaluated inside the vblank is predicted one frame late.
ARMED_LUA = """manager.machine:logerror(string.format("%(mark)s armed frame=%%d vblank=%%s\\n",
    screen:frame_number(), tostring(screen:time_until_vblank_end():as_double()
        < screen:time_until_vblank_start():as_double())))
"""

# The frame notifier registered by a chunk runs in the SAME frame update that evaluated it
# (the periodic hook comes just before the frame notifiers in `video.cpp`), so a recording
# begun at frame F and ended when the counter reads F + N - 1 holds exactly N frames;
# ended at F + N, the AVI declares N + 1.
# What the recording scripts raise on a machine with no screen, and what reads that back.
NO_SCREEN = "this machine has no screen"
RECORD_LUA = """if _G._mame_mcp_record_release then _G._mame_mcp_record_release() end
local v = manager.machine.video
local screen = nil
for _, s in pairs(manager.machine.screens) do screen = s break end
if screen == nil then error('""" + NO_SCREEN + """ to record') end
-- BEGIN AND END FROM THE SAME PLACE IN THE FRAME: the chunk itself is evaluated by the
-- console's periodic hook, at a point of the frame that is not the notifier's, so a
-- recording begun here and ended there came out one frame short on some runs and exact
-- on others. Begun on the first notifier call, it holds the frame of that call (the
-- notifier runs before the frame's video write) and one per later call, so the count
-- is exact whatever the console's own timing.
local counted = -1
local done = false
_G._mame_mcp_record_release = function()
    done = true
    if v.is_recording then v:end_recording() end
end
_G._mame_mcp_record = emu.add_machine_frame_notifier(function()
    if done then return end
    if counted < 0 then
        v:begin_recording(%(path)s, "avi")
        counted = 0
        manager.machine:logerror(string.format(
            "%(mark)s begin frame=%%d recording=%%s\\n", screen:frame_number(),
            tostring(v.is_recording)))
        return
    end
    counted = counted + 1
    if counted >= %(frames)d - 1 then
        done = true
        v:end_recording()
        manager.machine:logerror(string.format("%(mark)s end frame=%%d\\n", screen:frame_number()))
    end
end)
""" + ARMED_LUA

def check_record(frames: int, dest: str = "", seconds: float = 60.0, **_: Any) -> Path | None:
    """`record`'s machine-independent half: how many frames, the bound on waiting for them, and the
    file they go to -- handed back as the `Path` it built, so the body does not build it twice.
    The bound matters here more than anywhere: a recording waits inside the server's one lock, and
    an unbounded one held it for as long as the caller cared to type."""
    inputs.count("frames", frames, tail=": the frame notifier cannot end a recording on the "
                 "call that begins it, so one frame asked for would be two recorded", lo=2)
    inputs.seconds_bound(seconds)
    return inputs.optional_dest(dest)


class Recording(NamedTuple):
    """A bounded recording's run, read off its own marks: `ran`, the run's reply with the
    console's account in it; `begin`, the fields of the one `begin` mark; `end`, the `end`
    mark's, or None when the run stopped before the notifier ended the recording."""
    ran: dict[str, Any]
    begin: dict[str, str]
    end: dict[str, str] | None


#: Why a recording's file fields are not read: the file is not finished, or not begun.
OPEN_WHY = ("the recording is still OPEN: nothing is read from an unfinished file, and the script "
            "closes it when the machine reaches its last frame")
NOT_BEGUN_WHY = "the recording has NOT begun: the script's frame notifier has not run yet"


def not_read(keys: tuple[str, ...], why: str) -> dict[str, Any]:
    """Each of `keys` as `unavailable`, for the reason one recording state gives them all."""
    return {key: unavailable(why) for key in keys}


def _not_begun(ran: dict[str, Any], what: str, armed: dict[str, str], path: Path,
               frames: int, ends_after: int, file_keys: tuple[str, ...]) -> dict[str, Any]:
    """The reply of a recording whose script ran and whose frame notifier has not: a stop came
    between the two, as when the debugger evaluates the chunk at a breakpoint the run reached
    before the frame update. The notifier stays armed and begins the recording on the next
    frame the machine reaches, unless the next call of the same tool releases it first, so the
    reply says that instead of refusing. The frame is the one the chunk's `armed` line predicts
    (`ARMED_LUA`). Only a settled run gets here (`_unsettled` answers the others)."""
    begins = int(armed["frame"]) + (1 if armed["vblank"] == "true" else 0)
    return mlua.with_fields(ran, path=str(path), frames=frames, began=False, ended=False,
                       **not_read((*file_keys, "frame_begin", "recording_after"), NOT_BEGUN_WHY),
                       frame_begin_planned=begins,
                       frame_end_planned=begins + ends_after,
                       note="the recording has NOT begun: a stop came before the script's frame "
                            "notifier ran, and the notifier begins it on the next frame the "
                            f"machine reaches, unless another `{what}` call releases it first")


@contextmanager
def _frames_said(before: int | None) -> Iterator[None]:
    """A refusal raised once a recording's run began has moved the machine by that run: it says
    from which frame to which, under the run refusals' own `frame_before`/`frame_after`. A
    refusal that already carries them (the run's own) keeps its own."""
    try:
        yield
    except st.Invalid as refusal:
        if "frame_before" not in refusal.fields:
            refusal.fields.update(
                frame_before=or_unavailable(before, NO_FRAME_READ_WHY),
                frame_after=or_unavailable(st.last_stop_frame(), NO_FRAME_READ_WHY))
        raise


def _unsettled(ran: dict[str, Any], what: str, path: Path, ahead: int, drain_steps: int,
               answer: transport.Answer | None, resent: int) -> dict[str, Any]:
    """A recording whose run did not settle: the run's own refusal (`mame_lua.unsettled`), with
    the file's `path`."""
    return mlua.unsettled(ran, f"{what} recording", "begins or ends the recording at `path`",
                          "`stop`, then `captures` says whether a file was written", ahead,
                          drain_steps, answer, resent, path=str(path))


def recording_run(ses: gs.Session, scratch: Path, what: str, script: str, tag: str,
                  run_frames: int, seconds: float, progress: mprogress.Progress, path: Path,
                  frames: int, ends_after: int, file_keys: tuple[str, ...],
                  finish: Callable[[Recording], dict[str, Any]]) -> dict[str, Any]:
    """The run a recording bounded by the frame notifier makes, `record`'s AVI and
    `audio_record`'s WAV alike: its script begins and ends on the notifier and logs `begin` and
    `end` marks under `tag`, and everything between sending that script and reading those marks
    lives once, here, so the file format is the only thing a recording tool adds.

    `what` is the tool's name, the word the pending and refusal sentences use for it; `tag` is the
    mark the script logs, built from the same console sequence before anything is sent; `path` is
    the file, named in the refusals. `run_frames` is the run that carries the script past its last
    notifier call; `ends_after` is how many frames after the begin frame the last recorded frame is
    (a span's end is inclusive), and `file_keys` the caller's file keys, `unavailable` while there
    is no file. A script never evaluated is answered as pending, and one whose notifier has not run
    as not begun; an `end` mark with no `begin` is refused; otherwise `finish` checks the file and
    returns the reply through `with_fields`. No `begin` mark is "not begun" only beside the chunk's
    `armed` line, which a chunk that answered has logged, so a settled run with neither is refused
    as lost marks (the debugger can evaluate a chunk at the run's own last stop, so a run that
    reached every frame is no proof its notifier ran). A run that did not settle is its own refusal
    with the file's `path` (`_unsettled`), never the recording's fields. It runs inside the drain's
    account, and past the answer inside the console's, so every `Invalid` it raises carries
    `lines_ahead` and `drain_steps`, the
    console's trio once read, and the frames the call moved the machine by (`_frames_said`)."""
    mark = files.log_mark(scratch)
    advance.refuse_frameless(f"`{what}`, a count of frames,")   # before the drain, which steps
    before = st.last_stop_frame()
    if before is None:
        before = read.frame_or_none(ses)
    ahead, drain_steps = mlua.drain_ahead(ses, scratch)
    with mlua.drain_said(ahead, drain_steps), _frames_said(before):
        ran, answer, resent, moved = mlua.queued_then_ran(
            ses, scratch, script, run_frames, seconds, progress)
        if ran.get("status") != "ok":
            return _unsettled(ran, what, path, ahead, drain_steps, answer, resent)
        if answer is None:
            return mlua.not_evaluated(ran, what, ahead, resent, moved, drain_steps)
        with mlua.console_said(answer, resent):
            # THIS SERVER'S SCRIPT raises on its own only on a machine with no screen.
            code: contract.Code = ("no_channel" if NO_SCREEN in (answer.error or "")
                                   else "unexpected_answer")
            mlua.refuse_if_raised(answer, what, resent, code, path=str(path))
            ran = mlua.with_fields(ran, lines_ahead=ahead, drain_steps=drain_steps, reader_steps=0,
                                   **transport.console_did(answer, resent))
            seen = mlua.marks_since(scratch, mark, tag)
            mlua.refuse_a_rerun(seen, tag, answer, resent, path=str(path))
            begin, end = mlua.one_event(seen, tag, "begin"), mlua.one_event(seen, tag, "end")
            armed = mlua.one_event(seen, tag, "armed")
            if begin is None and end is not None:
                raise st.Invalid("readback_refused",
                    "the script logged an `end` mark and no `begin` mark: the log does not "
                    "hold the recording's beginning", tagged_lines=seen, path=str(path))
            if begin is None and armed is None:
                raise st.Invalid("readback_refused",
                    "the script answered and logged no mark, not even the `armed` line it "
                    "writes as it is evaluated: the log does not hold the script's marks",
                    tagged_lines=seen, path=str(path))
            if begin is None:
                assert armed is not None       # refused just above when neither was logged
                return _not_begun(ran, what, armed, path=path, frames=frames,
                                  ends_after=ends_after, file_keys=file_keys)
            return finish(Recording(ran, begin, end))


def record(ses: gs.Session, scratch: Path, frames: int, dest: str, seconds: float,
           progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `record` tool: an AVI of exactly `frames` frames, begun and ended by
    the script's own frame notifier, then the file checked before its path is given."""
    given = check_record(frames, dest, seconds)
    if given is not None:
        path = given
    else:
        path = scratch / "snap" / f"record-{STATE.next_number('recordings')}.avi"
    tag = f"{RECORD_MARK}#{STATE.lua_seq + 1}"
    script = RECORD_LUA % {"path": transport.lua_string(str(path)), "frames": frames, "mark": tag}
    ends_after = frames - 1                       # the script's `counted >= frames - 1`
    file_keys = ("avi_frames", "bytes")

    def finish(rec: Recording) -> dict[str, Any]:
        ran, begin, end = rec
        own = dict(path=str(path), frames=frames, began=True, frame_begin=int(begin["frame"]),
                   recording_after=begin["recording"] == "true")
        if end is None:
            return mlua.with_fields(ran, **own, ended=False, **not_read(file_keys, OPEN_WHY),
                         frame_end_planned=int(begin["frame"]) + ends_after,
                         note="the recording is still OPEN: the run stopped before its last "
                              "frame, and the script closes it when the machine reaches it")
        total = _avi_frames(path)
        if total is None:
            raise st.Invalid("readback_refused",
                f"{path} is not a finished AVI (missing, or not RIFF/AVI with an avih header)",
                path=str(path))
        if total == 0:
            raise st.Invalid("readback_refused", f"{path} holds ZERO frames", path=str(path),
                             bytes=path.stat().st_size)
        STATE.captures.append(("avi", str(path)))
        return mlua.with_fields(ran, **own, ended=True, bytes=path.stat().st_size, avi_frames=total,
                     frame_end=int(end["frame"]))

    return recording_run(ses, scratch, "record", script, tag, frames + 3, seconds, progress,
                         path, frames, ends_after, file_keys, finish)


#: A recording refusal's frame when no stop has read one.
NO_FRAME_READ_WHY = "no stop has read a frame"

#: A recording's header field when the file on disk no longer reads as finished.
NOT_FINISHED_WHY = "the file does not read as a finished recording"


def _avi_frames(path: Path) -> int | None:
    """The frame count an AVI declares in its main header (`scry_core.avi`), or None when the
    file is not an AVI with one. Waited for briefly: the writer closes the file after the
    notifier."""
    def declared() -> int | None:
        found = avi.header(path)
        return None if found is None else found.frames

    return files.wait_for(declared, files.FILE_WAIT_S, files.FILE_POLL_S)


def captures() -> dict[str, Any]:
    """The body of the `captures` tool: every file `record`, `audio_record`, `trace`, `snapshot`
    and the graphics tools checked and handed back this session, re-read now; a recording its
    call answered still open or not begun is finished, or released, by a later run that reads no
    file, so it is not listed and its path is in that call's reply. An AVI carries the frames
    its header declares, a WAV its samples, channels and rate (unavailable once it no longer reads
    as a finished WAV); a file that has gone since is listed as not present rather than dropped,
    because "what did this session produce" and "what is still on disk" are two questions and
    both are answered."""
    out: list[dict[str, Any]] = []
    for kind, path_s in STATE.captures:
        path = Path(path_s)
        entry: dict[str, Any] = {"kind": kind, "path": path_s, "present": path.is_file()}
        gone = unavailable("the file is gone")
        entry["bytes"] = path.stat().st_size if entry["present"] else gone
        # EVERY KEY OF A KIND ON EVERY ROW OF IT, unavailable with its why when nothing on disk
        # says it: a key that comes and goes is a shape a reader has to guess.
        if kind == "avi":
            frames = _avi_frames(path) if entry["present"] else None
            entry["avi_frames"] = (frames if frames is not None else gone if not entry["present"]
                                   else unavailable(NOT_FINISHED_WHY))
        if kind == "wav":
            wav = files.wav_header(path) if entry["present"] else None
            unread = gone if not entry["present"] else unavailable(NOT_FINISHED_WHY)
            entry["samples"] = wav.samples if wav else unread
            entry["channels"] = wav.channels if wav else unread
            entry["sample_rate_hz"] = wav.sample_rate if wav else unread
        out.append(entry)
    return menvelope.envelope({"captures": out})
