"""`audio_record`: the sound of exactly `frames` frames, as the WAV MAME's own mixer writes.

THE MIXER ALREADY KNOWS HOW. MAME's sound manager writes the speakers' input mix, before any
effect, to a WAV whenever it is asked (`sound:start_recording`, the Lua side of `-wavwrite`), so
this tool adds no sound path of its own: it asks for the file on the frame notifier `record`
trusts, ends it a counted number of frames later, and then reads the file back, because MAME's
WAV writer checks none of its writes and the header is the one account of what reached the disk.

WHOLE MIXER UPDATES, NOT FRAMES. The mixer writes in updates of a fiftieth of an emulated second
(`STREAMS_UPDATE_FREQUENCY` in `src/emu/sound.h`), so a recording bounded by frames holds the
updates that fell inside the span: its sample count differs from the span times the rate by up
to one update, and a recording that holds the session's first update carries one sample more.
Nothing is written while the machine stands at the debugger, since no update runs there.

The run itself (the drain, the queued script, the console's account, the marks) is
`mame_recording.recording_run`, shared with `record`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scry_core import progress as mprogress

import gdb_session as gs
import mame_files as files
import mame_inputs as inputs
import mame_lua as mlua
import mame_prose as prose
import mame_recording as mrec
import mame_state as st
import mame_transport as transport
from mame_state import STATE

AUDIO_MARK = "MAME_MCP_AUDIO"
# `STREAMS_UPDATE_FREQUENCY` in MAME's `src/emu/sound.h`: the mixer's updates per emulated second.
MIXER_UPDATE_HZ = 50
# The span is begun and ended on the frame notifier, so it IS `frames` periods; the times travel
# as 17 significant digits, and this is room for a double's rounding, not for a missed frame.
SPAN_TOLERANCE_S = 1e-6
# The fewest frames a span may cover: on a screen under `FRAMES_MIN * MIXER_UPDATE_HZ` Hz, that
# many frames always hold one whole mixer update.
FRAMES_MIN = 2
FRAMES_WHY = (f": MAME mixes in whole updates of 1/{MIXER_UPDATE_HZ} of an emulated second, and "
              f"{FRAMES_MIN} is the fewest frames that always hold one on a screen under "
              f"{FRAMES_MIN * MIXER_UPDATE_HZ} Hz")

# BEGUN ON THE FIRST NOTIFIER CALL AND ENDED ON THE CALL WHERE `counted` REACHES `frames`, one call
# later than `record`'s script ends, so the span between the two marks is `frames` frame periods
# of emulated time, as their `time` fields measure it.
# THE MIXER HAS ONE FILE, AND OTHER CALLERS. The script stops only the recording it began, and
# only while the mixer is still writing it: a session whose ini names `wavwrite` is already
# recording, and a `lua` call may stop this file and begin its own, and stopping either would
# end somebody else's file. MAME writes the RIFF size only when it closes a file, so a size
# there means this one was closed under the script, and the mixer's file is no longer its own.
# Once released or ended, the notifier does nothing more. The chunk's last line logs where the
# notifier first runs, as `record`'s does (`mame_recording.ARMED_LUA`).
AUDIO_LUA = """if _G._mame_mcp_audio_release then _G._mame_mcp_audio_release() end
local snd = manager.machine.sound
local path = %(path)s
local screen = nil
for _, s in pairs(manager.machine.screens) do screen = s break end
if screen == nil then error('""" + mrec.NO_SCREEN + """ to count frames by') end
local counted = -1
local began = false
local done = false
local function stop_own()
    if not began then return end
    began = false
    local f = io.open(path, "rb")
    if f ~= nil then
        f:seek("set", 4)
        local size = f:read(4)
        f:close()
        if size ~= nil and #size == 4 and string.unpack("<I4", size) ~= 0 then return end
    end
    snd:stop_recording()
end
_G._mame_mcp_audio_release = function()
    done = true
    stop_own()
end
_G._mame_mcp_audio = emu.add_machine_frame_notifier(function()
    if done then return end
    if counted < 0 then
        began = snd:start_recording(path)
        counted = 0
        manager.machine:logerror(string.format(
            "%(mark)s begin frame=%%d ok=%%s recording=%%s time=%%.17g period=%%.17g\\n",
            screen:frame_number(), tostring(began), tostring(snd.recording),
            manager.machine.time:as_double(), screen.frame_period))
        if not began then done = true end
        return
    end
    counted = counted + 1
    if counted >= %(frames)d then
        done = true
        stop_own()
        manager.machine:logerror(string.format("%(mark)s end frame=%%d time=%%.17g\\n",
            screen:frame_number(), manager.machine.time:as_double()))
    end
end)
""" + mrec.ARMED_LUA


def check_audio_record(frames: int, dest: str = "", seconds: float = 60.0,
                       **_: Any) -> Path | None:
    """`audio_record`'s machine-independent half: how many frames, the bound on waiting for
    them, and the file they go to, handed back as the `Path` it built."""
    inputs.count("frames", frames, tail=FRAMES_WHY, lo=FRAMES_MIN)
    inputs.seconds_bound(seconds)
    return inputs.optional_dest(dest)


# The file's keys, `unavailable` while there is no finished file to read them from.
_FILE_KEYS = ("bytes", "channels", "sample_rate_hz", "samples", "emulated_s", "sample_min",
              "sample_max")


def _refused(path: Path, message: str, **fields: Any) -> st.Invalid:
    return st.Invalid("readback_refused", message, path=str(path), **fields)


def audio_record(ses: gs.Session, scratch: Path, frames: int, dest: str, seconds: float,
                 progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `audio_record` tool: the mixer's WAV over exactly `frames` frames,
    begun and ended by the script's own frame notifier, then the file checked before its
    path is given."""
    given = check_audio_record(frames, dest, seconds)
    if given is not None:
        path = given
    else:
        path = scratch / "snap" / f"audio-{STATE.next_number('recordings')}.wav"
    tag = f"{AUDIO_MARK}#{STATE.lua_seq + 1}"
    script = AUDIO_LUA % {"path": transport.lua_string(str(path)), "frames": frames, "mark": tag}

    def finish(rec: mrec.Recording) -> dict[str, Any]:
        ran, begin, end = rec
        if begin["ok"] != "true":
            raise _refused(path, "the mixer refused to begin: it is already recording (a "
                           "session whose ini holds `wavwrite`, or a file another `lua` call "
                           "began), or the file could not be opened")
        own = dict(path=str(path), frames=frames, began=True, frame_begin=int(begin["frame"]),
                   recording_after=begin["recording"] == "true")
        if end is None:
            return mlua.with_fields(
                ran, **own, ended=False, **mrec.not_read(_FILE_KEYS, mrec.OPEN_WHY),
                frame_end_planned=int(begin["frame"]) + frames - 1,
                note="the recording is still OPEN: the run stopped before its last frame, "
                     "and the script closes it when the machine reaches it")
        # The file is closed before the end mark is logged, by the script or by whoever stopped
        # it first, so a file that does not read as finished now never will.
        wav = files.wav_header(path)
        if wav is None:
            why = (": this machine has no speaker, so MAME wrote a WAV with no channel"
                   if files.wav_without_channel(path) else "")
            raise _refused(path, f"{path} is not a finished WAV (missing, or a header that "
                           f"disagrees with the file){why}")
        spanned = int(end["frame"]) - int(begin["frame"])
        if spanned != frames:
            raise _refused(path, "the notifier ended the recording "
                           f"{prose.counted(spanned, 'frame')} after it began, not {frames}")
        emulated = float(end["time"]) - float(begin["time"])
        period = float(begin["period"])
        if abs(emulated - frames * period) > SPAN_TOLERANCE_S:
            raise _refused(path, f"the span is not {frames} frame periods: {emulated:.9f} s "
                           f"emulated against {frames} x {period:.9f} s")
        if wav.samples == 0:
            raise _refused(path, "the span held no mixer update: MAME mixes "
                           f"{MIXER_UPDATE_HZ} times per emulated second; ask for more frames",
                           bytes=path.stat().st_size)
        expected = emulated * wav.sample_rate
        update = -(-wav.sample_rate // MIXER_UPDATE_HZ)   # one update's samples, rounded up
        if abs(wav.samples - expected) > update + 1:
            raise _refused(path, "the file does not hold the span it was bounded by: "
                           f"{prose.counted(wav.samples, 'sample')} where {emulated:.9f} s at "
                           f"{wav.sample_rate} Hz is {expected:.0f}")
        lo, hi = files.wav_levels(path)
        STATE.captures.append(("wav", str(path)))
        return mlua.with_fields(
            ran, **own, ended=True, bytes=path.stat().st_size, channels=wav.channels,
            sample_rate_hz=wav.sample_rate, samples=wav.samples,
            emulated_s=st.measured_s(emulated), sample_min=lo, sample_max=hi,
            # the mixer stops AT the end frame, so the last frame it recorded is the one before:
            # a span's end is inclusive, as `record`'s
            frame_end=int(end["frame"]) - 1)

    # The script ends the recording when its counter reaches `frames`, `frames` after it began,
    # so the last frame recorded is `frames - 1` after it.
    return mrec.recording_run(ses, scratch, "audio_record", script, tag, frames + 4, seconds,
                              progress, path, frames, frames - 1, _FILE_KEYS, finish)
