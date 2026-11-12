"""`audio_record`: the WAV MAME's own mixer writes over exactly `frames` frames.

The mixer writes in updates of 1/50 emulated second (`STREAMS_UPDATE_FREQUENCY` in
`src/emu/sound.h`), so the sample count differs from span times rate by up to one update. MAME's
WAV writer checks none of its writes, so the file is read back and its header is the account.
The run itself is `recording.recording_run`, shared with `record`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scry_core import progress as mprogress
from scry_core import prose, wav
from scry_core import vocabulary as vocab

from scry_mame import gdb_session as gs
from scry_mame import inputs, lua_source
from scry_mame import lua as mlua
from scry_mame import recording as mrec
from scry_mame import state as st
from scry_mame.state import STATE

AUDIO_MARK = "MAME_MCP_AUDIO"
MIXER_UPDATE_HZ = 50
# Room for a double's rounding after 17 significant digits, not for a missed frame.
SPAN_TOLERANCE_S = 1e-6
FRAMES_MIN = 2
FRAMES_WHY = (f": MAME mixes in whole updates of 1/{MIXER_UPDATE_HZ} of an emulated second, and "
              f"{FRAMES_MIN} is the fewest frames that always hold one on a screen under "
              f"{FRAMES_MIN * MIXER_UPDATE_HZ} Hz")



def check_audio_record(frames: int, dest: str = "", seconds: float = 60.0,
                       **_: Any) -> Path | None:
    """`audio_record`'s machine-independent checks; returns the destination `Path`, if given."""
    inputs.count("frames", frames, tail=FRAMES_WHY, lo=FRAMES_MIN)
    vocab.check_wait(seconds)
    return inputs.optional_dest(dest)


_FILE_KEYS = ("bytes", "channels", "sample_rate_hz", "samples", "emulated_s", "sample_min",
              "sample_max")


def _refused(path: Path, message: str, **fields: Any) -> st.Invalid:
    return st.Invalid("readback_refused", message, path=str(path), **fields)


def audio_record(ses: gs.Session, scratch: Path, frames: int, dest: str, seconds: float,
                 progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The mixer's WAV over exactly `frames` frames, checked before its path is given."""
    given = check_audio_record(frames, dest, seconds)
    if given is not None:
        path = given
    else:
        path = scratch / "snap" / f"audio-{STATE.next_number('recordings')}.wav"
    tag = f"{AUDIO_MARK}#{STATE.lua_seq + 1}"
    script = (lua_source.render("audio", path=str(path), frames=frames, mark=tag,
                                no_screen=mrec.NO_SCREEN)
              + mrec.armed(tag))

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
        # Closed before the end mark is logged, so a file unreadable now never will be.
        head = wav.header(path)
        if head is None:
            why = (": this machine has no speaker, so MAME wrote a WAV with no channel"
                   if wav.without_channel(path) else "")
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
        if head.samples == 0:
            raise _refused(path, "the span held no mixer update: MAME mixes "
                           f"{MIXER_UPDATE_HZ} times per emulated second; ask for more frames",
                           bytes=path.stat().st_size)
        expected = emulated * head.sample_rate
        update = -(-head.sample_rate // MIXER_UPDATE_HZ)   # one update's samples, rounded up
        if abs(head.samples - expected) > update + 1:
            raise _refused(path, "the file does not hold the span it was bounded by: "
                           f"{prose.counted(head.samples, 'sample')} where {emulated:.9f} s at "
                           f"{head.sample_rate} Hz is {expected:.0f}")
        lo, hi = wav.levels(path)
        STATE.captures.append(("wav", str(path)))
        return mlua.with_fields(
            ran, **own, ended=True, bytes=path.stat().st_size, channels=head.channels,
            sample_rate_hz=head.sample_rate, samples=head.samples,
            emulated_s=st.measured_s(emulated), sample_min=lo, sample_max=hi,
            # the mixer stops AT the end frame; the span's end is inclusive, as `record`'s
            frame_end=int(end["frame"]) - 1)

    return mrec.recording_run(ses, scratch, "audio_record", script, tag, frames + 4, seconds,
                              progress, path, frames, frames - 1, _FILE_KEYS, finish)
