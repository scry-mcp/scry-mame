from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple

from scry_core import avi, wav
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable, unavailable

from scry_mame import advance, files, inputs, read, transport
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import lua as mlua
from scry_mame import state as st
from scry_mame.state import STATE

RECORD_MARK = "MAME_MCP_RECORD"

# Predicts where a notifier the debugger evaluated first runs. A chunk evaluated at a stop
# inside a vblank is first called on the next frame (frame notifiers run at vblank start, the
# counter moves at vblank end: `screen.cpp`); the running frame update's own chunk is called in
# that same update. Wrong by one frame under `VIDEO_UPDATE_AFTER_VBLANK`, which Lua cannot see.
ARMED_LUA = """manager.machine:logerror(string.format("%(mark)s armed frame=%%d vblank=%%s\\n",
    screen:frame_number(), tostring(screen:time_until_vblank_end():as_double()
        < screen:time_until_vblank_start():as_double())))
"""

# The chunk's notifier runs in the same frame update that evaluated it, so a recording begun at
# frame F and ended when the counter reads F + N - 1 holds exactly N frames.
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
    """`record`'s machine-independent checks; returns the `Path` built from `dest`, if any."""
    inputs.count("frames", frames, tail=": the frame notifier cannot end a recording on the "
                 "call that begins it, so one frame asked for would be two recorded", lo=2)
    vocab.check_wait(seconds)
    path = inputs.optional_dest(dest)
    if path is not None and path.suffix != ".avi":
        raise st.Invalid("bad_argument", f"dest={dest!r}: an `.avi` file, or empty for the "
                         "scratch's; MAME adds `.avi` to any other name, and the file would "
                         "not be the one named")
    return path


class Recording(NamedTuple):
    """A bounded recording's run read off its marks; `end` is None when the run stopped first."""
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
    """The reply of a recording whose script ran and whose notifier has not: the notifier stays
    armed and begins on the frame the `armed` line predicts, unless the next call releases it."""
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
    """Stamp a refusal with `frame_before`/`frame_after` unless it already carries them."""
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
    """The run's own refusal (`lua.unsettled`) with the file's `path`."""
    return mlua.unsettled(ran, f"{what} recording", "begins or ends the recording at `path`",
                          "`stop`, then `captures` says whether a file was written", ahead,
                          drain_steps, answer, resent, path=str(path))


def recording_run(ses: gs.Session, scratch: Path, what: str, script: str, tag: str,
                  run_frames: int, seconds: float, progress: mprogress.Progress, path: Path,
                  frames: int, ends_after: int, file_keys: tuple[str, ...],
                  finish: Callable[[Recording], dict[str, Any]]) -> dict[str, Any]:
    """The run a recording bounded by the frame notifier makes, `record`'s AVI and
    `audio_record`'s WAV alike.

    `what` is the tool's name; `tag` the mark its script logs; `run_frames` carries the script
    past its last notifier call; `ends_after` is the last recorded frame's offset from the begin
    frame; `file_keys` are `unavailable` while there is no file. A settled run with neither a
    `begin` nor the chunk's `armed` mark is refused as lost marks: the debugger can evaluate a
    chunk at the run's last stop, so reaching every frame proves nothing about the notifier.
    Every `Invalid` raised carries `lines_ahead`, `drain_steps` and the frames moved."""
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
                assert armed is not None
                return _not_begun(ran, what, armed, path=path, frames=frames,
                                  ends_after=ends_after, file_keys=file_keys)
            return finish(Recording(ran, begin, end))


def begun_as(path: Path) -> str:
    """The name for `video:begin_recording`, without `.avi`: under `-snapview native` MAME
    appends the extension even to a name that has one."""
    return str(path.with_suffix("")) if path.suffix.lower() == ".avi" else str(path)


def record(ses: gs.Session, scratch: Path, frames: int, dest: str, seconds: float,
           progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `record` tool."""
    given = check_record(frames, dest, seconds)
    if given is not None:
        path = given
    else:
        path = scratch / "snap" / f"record-{STATE.next_number('recordings')}.avi"
    tag = f"{RECORD_MARK}#{STATE.lua_seq + 1}"
    script = RECORD_LUA % {"path": transport.lua_string(begun_as(path)), "frames": frames,
                           "mark": tag}
    ends_after = frames - 1
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
    """The frame count an AVI declares, or None. Waited for: the writer closes late."""
    def declared() -> int | None:
        found = avi.header(path)
        return None if found is None else found.frames

    return files.wait_for(declared, files.FILE_WAIT_S, files.FILE_POLL_S)


def captures() -> dict[str, Any]:
    """The body of the `captures` tool: every file the tools checked and handed back this
    session, re-read now. A recording its call answered still open or not begun is not listed.
    A file that has gone is listed as not present, not dropped."""
    out: list[dict[str, Any]] = []
    for kind, path_s in STATE.captures:
        path = Path(path_s)
        entry: dict[str, Any] = {"kind": kind, "path": path_s, "present": path.is_file()}
        gone = unavailable("the file is gone")
        entry["bytes"] = path.stat().st_size if entry["present"] else gone
        if kind == "avi":
            frames = _avi_frames(path) if entry["present"] else None
            entry["avi_frames"] = (frames if frames is not None else gone if not entry["present"]
                                   else unavailable(NOT_FINISHED_WHY))
        if kind == "wav":
            head = wav.header(path) if entry["present"] else None
            unread = gone if not entry["present"] else unavailable(NOT_FINISHED_WHY)
            entry["samples"] = head.samples if head else unread
            entry["channels"] = head.channels if head else unread
            entry["sample_rate_hz"] = head.sample_rate if head else unread
        out.append(entry)
    return menvelope.envelope({"captures": out})
