"""`audio_record` and its WAV reader, tested on real files MAME wrote (`tests/fixtures/audio/`).

Every failure is a controlled edit of one of them, never a header written from belief.
"""

import gzip
import json
import os
import re
import struct
import time
import wave
from array import array
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from lua_support import AVI_HEAD, _captured, _channel, _marks_of  # noqa: E402
from lua_text import has, squash
from scry_core import roster, wav
from session_doubles import refused, run_host_lua  # noqa: E402

from scry_mame import (
    advance,  # noqa: E402
    lua,  # noqa: E402
    lua_source,  # noqa: E402
    summaries,  # noqa: E402
    transport,  # noqa: E402
)
from scry_mame import audio as maudio  # noqa: E402
from scry_mame import recording as mrec
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

#: How the one refusal of a relative path begins (scry-core's judge).
R_ABS = "must be an absolute path"

AUDIO = Path(__file__).parent / "fixtures" / "audio"
MARKS = json.loads((AUDIO / "marks.json").read_text())


def _wav(name: str) -> bytes:
    return gzip.decompress((AUDIO / f"{name}-wav.gz").read_bytes())


def _marks(name: str, seq: int) -> list[str]:
    """The fixture's own `begin` and `end` lines, renumbered as call `seq` of the test's session."""
    return [ln.split("#", 1)[0] + f"#{seq} " + ln.split(" ", 2)[2] for ln in MARKS[name]]


def _with_sizes(data: bytes) -> bytes:
    """`data` with its RIFF and data sizes made to agree with its length."""
    out = bytearray(data)
    struct.pack_into("<I", out, 4, len(out) - 8)
    struct.pack_into("<I", out, 40, len(out) - wav.HEADER_BYTES)
    return bytes(out)


def _put(ses: object, seq: int, path: Path, content: bytes | None, marks: list[str]) -> None:
    ses.answers[seq] = ses.sentinel(seq)  # type: ignore[attr-defined]
    ses.marks[seq] = marks  # type: ignore[attr-defined]
    if content is not None:
        ses.files[seq] = (path, content)  # type: ignore[attr-defined]


# ------------------------------------------------------------------------------- the reader

@pytest.mark.parametrize("name", ["v30-ay-tone", "v30-plain", "v30-closed-empty",
                                  "m68k-dual-stereo"])
def test_the_reader_agrees_with_stdlib_wave_on_every_real_file(tmp_path: Path, name: str) -> None:
    """`wave` from the standard library is the known answer for the header."""
    path = tmp_path / f"{name}.wav"
    path.write_bytes(_wav(name))
    got = wav.header(path)
    with wave.open(str(path)) as w:
        want = (w.getnchannels(), w.getframerate(), w.getnframes())
    assert got is not None and (got.channels, got.sample_rate, got.samples) == want
    assert got.data_bytes == path.stat().st_size - wav.HEADER_BYTES
    with wave.open(str(path)) as w:
        every = array("h", w.readframes(w.getnframes()))
    assert wav.levels(path) == ((min(every), max(every)) if every else (0, 0))


def test_the_levels_of_a_tone_differ_and_those_of_a_held_level_do_not(tmp_path: Path) -> None:
    tone = tmp_path / "tone.wav"
    tone.write_bytes(_wav("v30-ay-tone"))
    lo, hi = wav.levels(tone)
    assert lo < hi, (lo, hi)
    # every sample of the same file set to one level: a DAC at rest
    held = bytearray(tone.read_bytes())
    held[wav.HEADER_BYTES:] = struct.pack("<h", -1234) * (
        (len(held) - wav.HEADER_BYTES) // 2)
    flat = tmp_path / "flat.wav"
    flat.write_bytes(bytes(held))
    assert wav.levels(flat) == (-1234, -1234)


def test_the_levels_are_read_across_chunk_boundaries(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    """The extremes found are the whole file's, whatever chunk holds them."""
    path = tmp_path / "tone.wav"
    path.write_bytes(_wav("v30-ay-tone"))
    whole = wav.levels(path)
    monkeypatch.setattr(wav, "CHUNK_BYTES", 6)
    assert wav.levels(path) == whole


def test_the_levels_of_a_file_longer_than_one_chunk_are_its_own(tmp_path: Path) -> None:
    """A file longer than one chunk reads the levels stdlib `wave` reads."""
    tone = _wav("v30-ay-tone")[wav.HEADER_BYTES:]
    data = tone * (wav.CHUNK_BYTES // len(tone) + 2)
    path = tmp_path / "long.wav"
    path.write_bytes(_with_sizes(_wav("v30-ay-tone")[:wav.HEADER_BYTES] + data))
    assert path.stat().st_size > wav.CHUNK_BYTES + wav.HEADER_BYTES
    with wave.open(str(path)) as w:
        every = array("h", w.readframes(w.getnframes()))
    assert wav.levels(path) == (min(every), max(every))


@pytest.mark.parametrize("at", ["first", "last", "second chunk"])
def test_a_lone_outlier_is_found_wherever_it_lies(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path, at: str) -> None:
    """One sample out of silence is seen at the first, last and second-chunk positions."""
    monkeypatch.setattr(wav, "CHUNK_BYTES", 64)
    n = 100
    index = {"first": 0, "last": n - 1, "second chunk": 32}[at]
    data = bytearray(2 * n)
    struct.pack_into("<h", data, 2 * index, -777)
    path = tmp_path / "x.wav"
    path.write_bytes(_with_sizes(_wav("v30-ay-tone")[:wav.HEADER_BYTES] + data))
    assert wav.levels(path) == (-777, 0)


def _edit(data: bytes, at: int, fmt: str, value: int) -> bytes:
    out = bytearray(data)
    struct.pack_into(fmt, out, at, value)
    return bytes(out)


AY = _wav("v30-ay-tone")
STEREO = _wav("m68k-dual-stereo")


def _no_speaker(data: bytes) -> bytes:
    """The header MAME writes for no speaker: channels, byte rate and block align all zero."""
    return _edit(_edit(_edit(data, 22, "<H", 0), 28, "<I", 0), 32, "<H", 0)


REFUSED_HEADERS = {
    "RIFF magic": b"RIFX" + AY[4:],
    "WAVE magic": AY[:8] + b"WAVX" + AY[12:],
    "fmt tag": AY[:12] + b"fmtX" + AY[16:],
    "fmt size 18": _edit(AY, 16, "<I", 18),
    "not PCM": _edit(AY, 20, "<H", 3),
    "no channel": _no_speaker(AY),
    "rate zero": _edit(AY, 24, "<I", 0),
    # the byte rate made to agree with a zero rate, so nothing but the rate check refuses it
    "rate and byte rate zero": _edit(_edit(AY, 24, "<I", 0), 28, "<I", 0),
    "byte rate": _edit(AY, 28, "<I", 1),
    "block align": _edit(_edit(AY, 32, "<H", 4), 28, "<I", 48000 * 4),
    "8 bits": _edit(AY, 34, "<H", 8),
    "data tag": AY[:36] + b"LIST" + AY[40:],
    "RIFF size": _edit(AY, 4, "<I", len(AY)),
    "RIFF size short": _edit(AY, 4, "<I", len(AY) - 10),
    "data size": _edit(AY, 40, "<I", len(AY) - 46),
    "data size long": _edit(AY, 40, "<I", len(AY) - wav.HEADER_BYTES + 2),
    "half a sample": _with_sizes(AY + b"\x00"),
    "half a stereo frame": _with_sizes(STEREO + b"\x00\x00"),
    "short header": AY[:43],
}


@pytest.mark.parametrize("why", sorted(REFUSED_HEADERS))
def test_the_reader_refuses_a_header_that_disagrees_with_itself_or_the_file(
    tmp_path: Path, why: str
) -> None:
    path = tmp_path / "x.wav"
    path.write_bytes(REFUSED_HEADERS[why])
    assert wav.header(path) is None, why


def test_the_reader_refuses_an_unfinished_file_and_a_missing_one(tmp_path: Path) -> None:
    """MAME writes both sizes at close: a file still open reads 0 there whatever it holds."""
    path = tmp_path / "open.wav"
    path.write_bytes(_wav("v30-unfinished"))
    head = path.read_bytes()[:wav.HEADER_BYTES]
    assert path.stat().st_size > wav.HEADER_BYTES
    assert struct.unpack_from("<I", head, 4) == struct.unpack_from("<I", head, 40) == (0,), (
        "the fixture is what it says: both sizes still 0")
    assert wav.header(path) is None
    assert wav.header(tmp_path / "never.wav") is None


def test_a_header_naming_no_channel_is_told_apart_from_a_file_that_is_no_wav(
    tmp_path: Path
) -> None:
    path = tmp_path / "x.wav"
    path.write_bytes(_no_speaker(_wav("v30-closed-empty")))
    assert wav.header(path) is None and wav.without_channel(path)
    path.write_bytes(bytes(wav.HEADER_BYTES))
    assert not wav.without_channel(path), "zeros are not a WAV, with a channel or none"
    path.write_bytes(b"RIFX" + _no_speaker(_wav("v30-closed-empty"))[4:])
    assert not wav.without_channel(path), "no RIFF magic, no WAV"
    no_wave = _no_speaker(_wav("v30-closed-empty"))
    path.write_bytes(no_wave[:8] + b"WAVX" + no_wave[12:])
    assert not wav.without_channel(path), "no WAVE magic, no WAV"
    path.write_bytes(_wav("v30-closed-empty"))
    assert not wav.without_channel(path)
    assert not wav.without_channel(tmp_path / "never.wav")


# ------------------------------------------------------------------------------- the tool

def test_audio_record_checks_the_wav_and_answers_its_fields_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    path = ses.scratch / "snap" / "audio-1.wav"
    _put(ses, 1, path, AY, _marks("v30-ay-tone", 1))
    out = s.audio_record(frames=30)
    assert out["status"] == "ok", out
    assert out["path"] == str(path) and out["bytes"] == len(AY) and out["ended"] is True
    assert (out["frame_begin"], out["frame_end"], out["frames"]) == (61, 90, 30)
    assert (out["channels"], out["sample_rate_hz"], out["samples"]) == (1, 48000, 28800)
    assert out["emulated_s"] == pytest.approx(0.59904, abs=1e-9)
    assert "emulated_seconds" not in out, "seconds are `_s` in every reply"
    assert out["sample_min"] < out["sample_max"]
    assert out["recording_after"] is True
    assert out["frame_after"] - out["frame_before"] == 34, (
        "frames + 4: the notifier ends the recording one call later than record's does")
    keys = list(out)
    order = ["lines_ahead", "path", "frames", "frame_begin", "recording_after", "ended", "bytes",
             "channels", "sample_rate_hz", "samples", "emulated_s", "sample_min",
             "sample_max", "frame_end", "cause"]
    assert [k for k in keys if k in order] == order, keys
    assert keys[-1] == "session" and out["session"]["altered"] is False
    assert out["summary"] == f"audio_record: 28800 samples at 48000 Hz x 1 at {path}"
    assert mstate.STATE.captures[-1] == ("wav", str(path))


def test_audio_record_writes_where_it_is_told_and_counts_its_default_with_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`dest` is taken as given; the default name shares `record`'s session counter."""
    ses = _channel(monkeypatch, tmp_path)
    dest = tmp_path / "out.wav"
    _put(ses, 1, dest, _wav("m68k-dual-stereo"), _marks("m68k-dual-stereo", 1))
    out = s.audio_record(frames=7, dest=str(dest))
    assert out["status"] == "ok" and out["path"] == str(dest) and out["channels"] == 2, out
    assert mstate.STATE.recordings == 0, "a given dest takes no number from the counter"
    mstate.STATE.recordings = 4
    _put(ses, 2, ses.scratch / "snap" / "audio-5.wav", AY, _marks("v30-ay-tone", 2))
    assert s.audio_record(frames=30)["path"].endswith("audio-5.wav")


@pytest.mark.parametrize("level", [0, -1234])
def test_a_silent_recording_is_answered_and_said_never_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, level: int
) -> None:
    """A DAC at rest holds a level, zero or not: either is silence, reported as such."""
    ses = _channel(monkeypatch, tmp_path)
    held = bytearray(AY)
    held[wav.HEADER_BYTES:] = struct.pack("<h", level) * (
        (len(AY) - wav.HEADER_BYTES) // 2)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", bytes(held), _marks("v30-ay-tone", 1))
    out = s.audio_record(frames=30)
    assert out["status"] == "ok" and out["sample_min"] == out["sample_max"] == level, out
    assert out["summary"].endswith(", silent at " + out["path"]), out["summary"]


def _refused_with(ses: object, content: bytes | None, marks: list[str], frames: int,
                  needle: str) -> dict[str, Any]:
    path = ses.scratch / "snap" / "audio-1.wav"  # type: ignore[attr-defined]
    _put(ses, 1, path, content, marks)
    out: dict[str, Any] = s.audio_record(frames=frames)
    assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert needle in str(out["message"]), out["message"]
    assert out["path"] == str(path)
    assert "lines_ahead" in out, "the drain's account rides the refusal"
    assert ("wav", str(path)) not in mstate.STATE.captures
    return out


def _shifted(name: str, seq: int, end_frame: int | None = None,
             end_time: float | None = None) -> list[str]:
    begin, end = _marks(name, seq)
    head, _, rest = end.partition(" end ")
    fields = dict(kv.split("=") for kv in rest.split())
    if end_frame is not None:
        fields["frame"] = str(end_frame)
    if end_time is not None:
        fields["time"] = repr(end_time)
    return [begin, f"{head} end " + " ".join(f"{k}={v}" for k, v in fields.items())]


@pytest.mark.parametrize("case", [
    "mixer refused", "unfinished", "no speaker", "one frame short", "span",
    "no update", "samples", "one frame long",
])
def test_audio_record_refuses_what_it_measured_and_says_which(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    marks = _marks("v30-ay-tone", 1)
    if case == "mixer refused":
        begin = marks[0].replace("ok=true recording=true", "ok=false recording=true")
        _refused_with(ses, None, [begin], 30, "the mixer refused to begin")
    elif case == "unfinished":
        out = _refused_with(ses, _wav("v30-unfinished"), marks, 30, "not a finished WAV")
        assert "no speaker" not in str(out["message"]), "its header names a channel"
    elif case == "no speaker":
        empty = _no_speaker(_wav("v30-closed-empty"))
        out = _refused_with(ses, empty, marks, 30, "not a finished WAV")
        assert "no speaker" in str(out["message"])
    elif case == "one frame short":
        _refused_with(ses, AY, _shifted("v30-ay-tone", 1, end_frame=90), 30,
                      "ended the recording 29 frames after it began, not 30")
    elif case == "span":
        _refused_with(ses, AY, _shifted("v30-ay-tone", 1, end_time=1.84), 30,
                      "not 30 frame periods")
    elif case == "no update":
        out = _refused_with(ses, _wav("v30-closed-empty"), marks, 30, "held no mixer update")
        assert out["bytes"] == len(_wav("v30-closed-empty")), "the file's own size"
    elif case == "one frame long":
        _refused_with(ses, AY, _shifted("v30-ay-tone", 1, end_frame=92), 30,
                      "ended the recording 31 frames after it began, not 30")
    elif case == "samples":
        _refused_with(ses, _wav("m68k-dual-stereo"), marks, 30,
                      "does not hold the span it was bounded by")


def test_a_recording_cut_short_is_still_open_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", None, _marks("v30-ay-tone", 1)[:1])
    out = s.audio_record(frames=30)
    assert out["status"] == "ok" and out["ended"] is False and out["frame_end_planned"] == 90, out
    assert out["began"] is True, out
    for key in ("bytes", "channels", "sample_rate_hz", "samples", "emulated_s",
                "sample_min", "sample_max"):
        assert out[key]["available"] is False, key
    assert "still OPEN" in out["note"]
    assert out["summary"] == "audio_record: still OPEN from frame 61, ends at 90"
    assert mstate.STATE.captures == [], "an open recording is no capture yet"


def test_a_recording_a_stop_came_before_is_not_begun_and_says_when_it_begins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only the `armed` line is logged: the notifier has not run, so it is not begun."""
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", None,
         ["[luaengine] MAME_MCP_AUDIO#1 armed frame=60 vblank=false"])
    out = s.audio_record(frames=30)
    assert out["status"] == "ok" and out["began"] is False and out["ended"] is False, out
    assert (out["frame_begin_planned"], out["frame_end_planned"]) == (60, 89), out
    for key in ("bytes", "channels", "sample_rate_hz", "samples", "emulated_s",
                "sample_min", "sample_max"):
        assert out[key]["available"] is False, key
    assert "unless another `audio_record` call releases it first" in out["note"], out["note"]
    assert out["summary"] == "audio_record: NOT begun, begins at frame 60, ends at 89"
    assert mstate.STATE.captures == [], "a recording not begun is no capture"


def test_the_armed_line_reads_the_vblank_off_the_two_screen_timers() -> None:
    """Where the notifier first runs, which each recording script logs last."""
    armed = mrec.armed("MAME_MCP_RECORD#1")
    assert has(armed, "time_until_vblank_end():as_double() < screen:time_until_vblank_start()")
    assert mrec.armed("x") != armed, "the line carries its call's own mark"


def test_an_end_mark_with_no_begin_mark_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No reply can say what the file is, and "not begun" would be false."""
    ses = _channel(monkeypatch, tmp_path)
    _refused_with(ses, AY, _marks("v30-ay-tone", 1)[1:], 30, "no `begin` mark")


def test_a_chunk_the_console_ran_twice_is_a_rerun(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    begin, end = _marks("v30-ay-tone", 1)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", AY, [begin, begin, end])
    out = s.audio_record(frames=30)
    assert out["code"] == "console_rerun", out
    assert out["console_reruns"] == 1 and "MAME_MCP_AUDIO#1 begin" in out["message"], out


@pytest.mark.parametrize("frames", [1, 0, True, 2.5, "30"])
def test_frames_is_a_count_of_two_or_more_and_never_another_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, frames: object
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    out = refused("^frames", s.audio_record(frames=frames))
    # A count below the floor says why the floor is there; what is no count at all says so.
    said = "whole updates" if frames in (0, 1) and frames is not True else "is a count; got"
    assert out["code"] == "bad_argument" and said in out["message"], out
    assert ses.stdin.getvalue() == b"", "refused before the pipe"


def test_dest_is_absolute_and_new(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    refused(R_ABS, s.audio_record(frames=2, dest="rel.wav"))
    there = tmp_path / "there.wav"
    there.write_bytes(b"x")
    refused("already exists", s.audio_record(frames=2, dest=str(there)))
    assert there.read_bytes() == b"x"
    refused("seconds", s.audio_record(frames=2, seconds=0))
    assert ses.stdin.getvalue() == b""


def test_a_running_machine_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.running = True
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)
    out = s.audio_record(frames=2)
    assert out["code"] == "not_stopped", out
    assert ses.stdin.getvalue() == b""


def test_captures_lists_a_wav_with_its_header_and_nulls_once_it_no_longer_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    path = ses.scratch / "snap" / "audio-1.wav"
    _put(ses, 1, path, AY, _marks("v30-ay-tone", 1))
    assert s.audio_record(frames=30)["status"] == "ok"
    wav = s.captures()["captures"][-1]
    assert (wav["kind"], wav["present"], wav["bytes"]) == ("wav", True, len(AY)), wav
    assert (wav["samples"], wav["channels"], wav["sample_rate_hz"]) == (28800, 1, 48000), wav
    with path.open("r+b") as fh:
        fh.truncate(len(AY) - 2)
    wav = s.captures()["captures"][-1]
    assert wav["present"] is True and wav["bytes"] == len(AY) - 2
    unread = {"available": False, "why": mrec.NOT_FINISHED_WHY}
    assert (wav["samples"], wav["channels"], wav["sample_rate_hz"]) == (unread,) * 3, wav


def test_the_script_stops_the_mixer_in_one_place_and_prints_its_times_whole() -> None:
    """Release and end both go through `stop_own`, only for a file this script began."""
    script = lua_source.render("audio", path="/x.wav", frames=5, mark="MAME_MCP_AUDIO#9",
                               no_screen=mrec.NO_SCREEN)
    release = script.split("_G._mame_mcp_audio_release = function()", 1)[1].split("end\n", 1)[0]
    first = "if _G._mame_mcp_audio_release then _G._mame_mcp_audio_release() end\n"
    assert squash(script).startswith(squash(first)), "the previous recording is released first"
    assert has(release, "done = true") and has(release, "stop_own()"), release
    assert script.count("snd:stop_recording()") == 1
    own = script.split("local function stop_own()", 1)[1].split("\nend\n", 1)[0]
    assert has(own, "if not began then return end") and has(own, 'string.unpack("<I4", size) ~= 0')
    assert has(script, "time=%.17g period=%.17g") and has(script, "end frame=%d time=%.17g")


def _spanning(seq: int, emulated: float, frames: int = 30, t0: float | None = None) -> list[str]:
    """Marks whose span is `emulated` seconds over `frames` periods, from `t0` or the fixture's."""
    begin, _ = _marks("v30-ay-tone", seq)
    if t0 is None:
        t0 = float(begin.rsplit("time=", 1)[1].split()[0])
    head = begin.split(" begin ", 1)[0]
    return [f"{head} begin frame=61 ok=true recording=true time={t0!r} "
            f"period={emulated / frames!r}",
            f"{head} end frame={61 + frames} time={t0 + emulated!r}"]


@pytest.mark.parametrize("off,ok", [(960.5, True), (961.5, False), (-960.5, True),
                                    (-961.5, False)])
def test_the_samples_are_held_to_one_update_and_one_sample_either_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, off: float, ok: bool
) -> None:
    """One update (960 at 48 kHz) and one sample is the bound, in both directions."""
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", AY, _spanning(1, (28800 - off) / 48000))
    out = s.audio_record(frames=30)
    assert (out["status"] == "ok") is ok, out
    if not ok:
        assert "does not hold the span" in out["message"], out


@pytest.mark.parametrize("drift,ok", [(5e-7, True), (2e-6, False), (-5e-7, True),
                                      (-2e-6, False)])
def test_the_span_is_held_to_its_periods_within_a_microsecond(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, drift: float, ok: bool
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    begin, end = _marks("v30-ay-tone", 1)
    t1 = float(end.rsplit("time=", 1)[1])
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", AY,
         [begin, end.rsplit("time=", 1)[0] + f"time={t1 + drift!r}"])
    out = s.audio_record(frames=30)
    assert (out["status"] == "ok") is ok, out


def test_the_script_raising_and_a_script_never_evaluated_are_said(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1, False, "mcp:5: this machine has no screen to count frames by")
    out = refused("no screen to count frames by", s.audio_record(frames=2))
    assert out["code"] == "no_channel" and out["message"].startswith("audio_record:"), (
        "a machine with no screen has no channel to count frames by", out)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    out = s.audio_record(frames=2)
    assert out["status"] == "ok" and out["pending"] is True, out
    assert out["summary"] == "audio_record: " + summaries.PENDING_SCRIPT
    assert "the audio_record script has no answer" in out["note"], out["note"]


def _samples(data: bytes, n: int, rate: int = 48000) -> bytes:
    """`data` cut to its first `n` samples (mono) at `rate`, its header made to agree."""
    out = bytearray(data[:wav.HEADER_BYTES + 2 * n])
    struct.pack_into("<I", out, 24, rate)
    struct.pack_into("<I", out, 28, rate * 2)
    return _with_sizes(bytes(out))


@pytest.mark.parametrize("rate,samples,ok", [
    # 0.5 s at 48 kHz is 24000; one update is 960, so 961 off is the edge and is held
    (48000, 24961, True), (48000, 24962, False),
    # at 11025 Hz an update is 220.5 samples, rounded UP to 221, so 221.5 off is held and
    # 222.5 is not: the bound follows the file's own rate, not a rate every fixture shares
    (11025, 5734, True), (11025, 5735, False),
])
def test_the_sample_bound_is_one_update_rounded_up_at_the_files_own_rate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rate: int, samples: int, ok: bool
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", _samples(AY, samples, rate),
         _spanning(1, 0.5, t0=0.0))
    out = s.audio_record(frames=30)
    assert (out["status"] == "ok") is ok, out
    if ok:
        assert (out["sample_rate_hz"], out["samples"]) == (rate, samples), out


def test_the_span_is_answered_to_the_nanosecond(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", AY, _spanning(1, 0.5990412345, t0=0.0))
    out = s.audio_record(frames=30)
    assert out["status"] == "ok" and out["emulated_s"] == 0.599041, out


def test_recording_after_is_what_the_begin_mark_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    begin, end = _marks("v30-ay-tone", 1)
    begin = begin.replace("ok=true recording=true", "ok=true recording=false")
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", AY, [begin, end])
    out = s.audio_record(frames=30)
    assert out["status"] == "ok" and out["recording_after"] is False, out


def test_the_run_gets_the_script_for_this_call_and_the_callers_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The run gets this call's script, absolute path, count, four frames more, and `seconds`."""
    _channel(monkeypatch, tmp_path)
    seen: dict[str, Any] = {}

    def run(ses: object, scratch: Path, *, what: str, script: str, tag: str, run_frames: int,
            seconds: float, progress: object, path: Path, frames: int, ends_after: int,
            file_keys: tuple[str, ...], finish: object,
            on_bound: object = None) -> dict[str, Any]:
        seen.update(script=script, tag=tag, run_frames=run_frames, seconds=seconds, path=path,
                    frames=frames, ends_after=ends_after)
        raise mstate.Invalid("bad_argument", "the run is this test's")

    monkeypatch.setattr(mrec, "recording_run", run)
    dest = tmp_path / "out.wav"
    s.audio_record(frames=30, dest=str(dest), seconds=7.5)
    assert seen["tag"] == "MAME_MCP_AUDIO#1" and seen["path"] == dest, seen
    assert seen["script"].count(transport.lua_string(seen["tag"])) == 3, "begin, end and armed"
    assert seen["script"].endswith(mrec.armed(seen["tag"])), "the armed line is the chunk's last"
    assert f"local path = {transport.lua_string(str(dest))}" in seen["script"]
    # the script ends AT `frames`, so the last frame recorded, the span's end, is one before
    assert f"counted >= {seen['ends_after'] + 1} then" in seen["script"], seen
    assert (seen["frames"], seen["ends_after"]) == (30, 29), seen
    assert (seen["run_frames"], seen["seconds"]) == (34, 7.5), seen



def test_a_recording_s_script_ends_with_its_armed_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _channel(monkeypatch, tmp_path)
    seen: dict[str, Any] = {}

    def run(ses: object, scratch: Path, *, script: str, tag: str,
            **_: object) -> dict[str, Any]:
        seen.update(script=script, tag=tag)
        raise mstate.Invalid("bad_argument", "the run is this test's")

    monkeypatch.setattr(mrec, "recording_run", run)
    s.record(frames=30)
    assert seen["script"].endswith(mrec.armed(seen["tag"])), "the armed line is the chunk's last"
    assert transport.lua_string(mrec.NO_SCREEN) in seen["script"]

def test_captures_gives_sample_keys_to_a_wav_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _channel(monkeypatch, tmp_path)
    png = tmp_path / "shot.png"
    png.write_bytes(b"x")
    mstate.STATE.captures.append(("png", str(png)))
    entry = s.captures()["captures"][-1]
    assert entry["present"] is True and "samples" not in entry and "channels" not in entry, entry


# ------------------------------------------------------------------ the shapes of a recording

def _armed(seq: int, frame: int = 60, vblank: str = "false") -> str:
    return f"[luaengine] MAME_MCP_AUDIO#{seq} armed frame={frame} vblank={vblank}"


def test_the_armed_line_the_lua_writes_is_the_line_the_parser_reads() -> None:
    """Lua writes the `armed` line and Python reads it: the format must round-trip."""
    tag = "MAME_MCP_AUDIO#7"
    chunk = mrec.armed(tag)
    m = re.search(r'string\.format\(\s*"(.*?)\\n"', chunk)
    assert m is not None, chunk
    line = "[luaengine] " + (m.group(1).replace("%s", tag, 1).replace("%d", "61", 1)
                             .replace("%s", "true", 1))
    assert lua.one_event(mstate.mark_lines([line], tag), tag, "armed") == {
        "frame": "61", "vblank": "true"}


def test_a_finished_recording_with_its_armed_line_is_finished(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The live shape: `armed` logged first, then `begin` and `end`."""
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", _wav("v30-ay-tone"),
         [_armed(1), *_marks("v30-ay-tone", 1)])
    out = s.audio_record(frames=30)
    assert out["status"] == "ok" and out["began"] is True and out["ended"] is True, out
    assert out["samples"] > 0, out


def test_a_refusal_after_the_run_says_the_frames_the_run_advanced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A refusal after the run says from which frame to which, in the run refusals' keys."""
    ses = _channel(monkeypatch, tmp_path)
    began = [ln.replace(" ok=true", " ok=false") for ln in _marks("v30-ay-tone", 1)]
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", None, [_armed(1), *began])
    before = 100                      # the double's frame counter at its start
    out = refused("the mixer refused to begin", s.audio_record(frames=30))
    assert out["frame_before"] == before and out["frame_after"] > out["frame_before"], out
    assert out["frame_after"] == mstate.STATE.last_stop["frame"], out


def test_a_recording_cut_short_by_an_unsettled_run_is_the_runs_refusal_with_its_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The run's `not_settled` refusal with the file's `path`, never the recording's fields."""
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", None, [_armed(1)])
    unsettled = {"status": "INVALID", "code": "not_settled",
                 "message": "the frame counter still moves", "frame_before": 100,
                 "frame_after": 103, "session": {}}
    real = lua.queued_then_ran

    def run(*a: Any) -> Any:
        ran, answer, resent, moved = real(*a)
        return dict(unsettled), answer, resent, moved

    monkeypatch.setattr(lua, "queued_then_ran", run)
    out = s.audio_record(frames=30)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert out["path"].endswith("audio-1.wav"), out
    assert "notifier" in out["message"] and "the frame counter still moves" in out["message"]
    for key in ("began", "ended", "frame_begin_planned", "frame_end_planned", "note", "samples"):
        assert key not in out, key


BOUND_REFUSAL = {"status": "INVALID", "code": "not_settled",
                 "message": "the frame counter reached 103 of the 30 asked for",
                 "frame_before": 100, "frame_after": 103, "session": {}}


def _bound_at(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, content: bytes = AVI_HEAD,
              twice: bool = False, left_running: bool = False
              ) -> tuple[Any, Path, dict[str, Any]]:
    """The channel of a `record` whose run meets its bound with the notifier armed: the script
    ran, its file is `content`, and `queued_then_ran` answers `not_settled` on the first call
    only, so the release runs on a line of its own. `left_running` makes that first call let go
    of the machine as the frame counter's bound does (`advance.left_running`)."""
    ses = _channel(monkeypatch, tmp_path)
    path = ses.scratch / "snap" / "record-1.avi"
    ses.answers[1] = _captured(5)
    marks = [m.replace("#5", "#1") for m in _marks_of("MAME_MCP_RECORD#5")]
    ses.marks[1] = [*marks, *marks] if twice else marks
    ses.files[1] = (path, content)
    ses.answers[2] = ses.sentinel(2)          # the release line's own answer
    seen: dict[str, Any] = {"calls": 0}
    real = lua.queued_then_ran

    def run(*a: Any, **k: Any) -> Any:
        seen["calls"] += 1
        ran, answer, resent, moved = real(*a, **k)
        if seen["calls"] == 1:
            if left_running:
                advance.left_running(ses)  # type: ignore[arg-type]
            return dict(BOUND_REFUSAL), answer, resent, moved
        return ran, answer, resent, moved

    monkeypatch.setattr(lua, "queued_then_ran", run)
    return ses, path, seen


def test_a_bound_that_fires_releases_the_recording_and_answers_its_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The bound's `not_settled` is not the reply when the release finalises the file: the
    recording is ended on the console its script came through and its AVI is read back."""
    _ses, path, seen = _bound_at(monkeypatch, tmp_path)
    out = s.record(frames=30)
    assert out["status"] == "ok", out
    assert out["verdict"] == "TIMEOUT" and out["ended"] is True, out
    assert out["path"] == str(path) and out["bytes"] == len(AVI_HEAD), out
    assert out["avi_frames"] == 30 and out["frame_begin"] == 321, out
    assert seen["calls"] == 2, "the release ran on a line of its own, after the bound"
    assert "cut at its `seconds` bound" in out["note"], out
    assert set(roster.RECORD_REPLY_FIELDS) <= set(out), out


def _open_avi(head: bytes) -> bytes:
    """The fixture's header as a writer still holds it: the frame count at 0, no index."""
    out = bytearray(head)
    struct.pack_into("<I", out, out.find(b"avih") + 8 + 4 * 4, 0)
    return bytes(out)


def test_a_bound_whose_file_is_still_open_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The release's answer can land before the writer closes; the reply never calls that ok."""
    _bound_at(monkeypatch, tmp_path, content=_open_avi(AVI_HEAD))
    out = s.record(frames=30)
    assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert "holds ZERO frames" in out["message"], out


def test_a_bound_whose_chunk_ran_twice_is_the_reruns_refusal_never_a_file_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two runs log every mark twice, and the file is one run's: neither may be described."""
    _bound_at(monkeypatch, tmp_path, twice=True)
    out = s.record(frames=30)
    assert out["status"] == "INVALID" and out["code"] == "console_rerun", out


def test_a_bound_recovered_reply_carries_the_consoles_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A settled run says what the console did (`thread_errors`, `console_reruns`, and `resent`
    only when it is not zero); the recovery is a run of the same console and says the same."""
    ses, _path, _seen = _bound_at(monkeypatch, tmp_path)
    ses.answers[1] = (b"m68k-dual\n[LUA ERROR] in thread: attempt to index a nil value\n"
                      + ses.sentinel(1))
    out = s.record(frames=30)
    assert out["status"] == "ok", out
    assert out["thread_errors"] == 1 and out["console_reruns"] == 0, out
    assert "resent" not in out, "a counter at zero is left out, as the settled path leaves it"


def test_a_stop_straight_after_a_bound_recovery_finds_the_machine_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The bound lets go of a machine it cannot see stop, and the release's own run ends at a
    stop: a `stop` after it has nothing to interrupt."""
    _bound_at(monkeypatch, tmp_path, left_running=True)
    out = s.record(frames=30)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    after = s.stop()
    assert after["interrupted"] is False and after["note"] == "the machine was already stopped", \
        after


def test_the_spent_bound_after_an_answer_carries_the_consoles_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A refusal raised past an answer carries the console's trio."""
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", None, [_armed(1)])
    now = {"t": 0.0, "stepped": False}

    def answer_or_none(*a: Any, **k: Any) -> Any:
        return transport.Answer("", True, "nil") if now["stepped"] else None

    step = advance.step

    def step_spending_the_bound(*a: Any, **k: Any) -> Any:
        out = step(*a, **k)
        now["t"], now["stepped"] = 1e9, True
        return out

    monkeypatch.setattr(lua, "_answer_or_none", answer_or_none)
    monkeypatch.setattr(advance, "step", step_spending_the_bound)
    # the bound's clock only, the lua module's own view of `time`: the global stays real
    clock = SimpleNamespace(**{k: getattr(time, k) for k in dir(time) if not k.startswith("_")})
    clock.monotonic = lambda: now["t"]
    monkeypatch.setattr("scry_mame.lua.time", clock)
    out = refused("the script answered at the step", s.audio_record(frames=30, seconds=5.0))
    assert out["code"] == "wait_expired" and out.keys() >= {"thread_errors", "console_reruns"}, out


def test_a_refusal_past_a_resent_answer_counts_the_resend_and_a_not_begun_names_its_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The refusal carries the call's own `resent`; not begun names its file."""
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", None, [])
    real = lua.queued_then_ran

    def resent_once(*a: Any) -> Any:
        ran, answer, _resent, moved = real(*a)
        return ran, answer, 1, moved

    monkeypatch.setattr(lua, "queued_then_ran", resent_once)
    out = refused("not even the `armed` line", s.audio_record(frames=30))
    assert out.get("resent", 0) == 1, out
    (tmp_path / "again").mkdir()
    ses = _channel(monkeypatch, tmp_path / "again")
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", None, [_armed(1)])
    out = s.audio_record(frames=30)
    assert out["began"] is False and out["path"] == str(ses.scratch / "snap" / "audio-1.wav"), out


# ------------------------------------------- the script itself, run on a Lua with MAME's mixer
# The recording script is Lua, and the parts that decide whose file the mixer stops are Lua too:
# a substring of the script cannot say what it does. Here it RUNS, on this host's `lua`, against
# a mixer that behaves as MAME's measurably does: a file begun holds the header of the copy taken
# from a recording still open (both sizes zero), and a file closed has both sizes written, which
# for a file that got no update is the captured header of exactly that.

def _lua_bytes(data: bytes) -> str:
    return '"' + "".join(f"\\{b:03d}" for b in data) + '"'


MIXER_LUA = """local OPEN_HEADER = %(header)s
local current = nil
local function close_current()
    local f = io.open(current, "r+b")
    local data = f:read("a")
    f:seek("set", 4) f:write(string.pack("<I4", #data - 8))
    f:seek("set", 40) f:write(string.pack("<I4", #data - 44))
    f:close()
end
local snd = {recording = false}
function snd:start_recording(path)
    if current ~= nil then return false end
    local f = io.open(path, "wb")
    if f == nil then return false end
    f:write(OPEN_HEADER) f:close()
    current = path self.recording = true
    return true
end
function snd:stop_recording()
    if current == nil then return end
    close_current()
    print("stop " .. current)
    current = nil self.recording = false
end
local frame = 100
local vblank = {as_double = function() return 0.25 end}
local active = {as_double = function() return 0.5 end}
local screen = {frame_period = 1 / 60}
function screen:frame_number() return frame end
function screen:time_until_vblank_end() return active end
function screen:time_until_vblank_start() return vblank end
local machine = {sound = snd, screens = {main = screen},
                 time = {as_double = function() return frame / 60 end}}
function machine:logerror(s) io.write("log " .. s) end
manager = {machine = machine}
local notifier = nil
emu = {add_machine_frame_notifier = function(fn) notifier = fn return {} end}
function tick(n) for _ = 1, n or 1 do frame = frame + 1 notifier() end end
function update(n) local f = io.open(current, "ab") f:write(string.rep("\\0", n)) f:close() end
function other_begins(path) return snd:start_recording(path) end
function other_swaps(path) snd:stop_recording() snd:start_recording(path) end
function release() _G._mame_mcp_audio_release() end
"""


def _run_audio_lua(tmp_path: Path, frames: int, before: str, after: str) -> list[str]:
    """Mixer, `before`, the recording script for `frames` frames, then `after`; one event a line."""
    header = _wav("v30-unfinished")[:wav.HEADER_BYTES]
    chunk = (MIXER_LUA % {"header": _lua_bytes(header)} + before + "\n"
             + lua_source.render("audio", path=str(tmp_path / "ours.wav"), frames=frames,
                                 mark="MAME_MCP_AUDIO#1", no_screen=mrec.NO_SCREEN)
             + after + "\n")
    return [ln.replace(str(tmp_path) + os.sep, "") for ln in run_host_lua(chunk, tmp_path)]


def test_the_lua_mixer_double_closes_a_file_as_mames_did(tmp_path: Path) -> None:
    """The double closes a file begun and stopped with no update as MAME did, byte for byte."""
    out = _run_audio_lua(tmp_path, 2, 'other_begins("x.wav") machine = manager.machine '
                         'machine.sound:stop_recording()', "")
    assert out[0] == "stop x.wav", out
    assert (tmp_path / "x.wav").read_bytes() == _wav("v30-closed-empty")


def test_the_script_begins_on_its_first_notifier_call_and_ends_frames_calls_later(
    tmp_path: Path,
) -> None:
    """Begun at the first call, ended where the counter reaches `frames`, own file stopped once."""
    out = _run_audio_lua(tmp_path, 3, "", "tick(1) update(4) tick(5)")
    begin = next(ln for ln in out if " begin " in ln)
    end = next(ln for ln in out if " end " in ln)
    assert "frame=101 ok=true" in begin and "frame=104 " in end, out
    assert out.count("stop ours.wav") == 1, out


def test_the_script_never_stops_a_file_another_caller_began_on_the_mixer(
    tmp_path: Path,
) -> None:
    """The script finding a RIFF size written leaves the other caller's recording alone."""
    out = _run_audio_lua(tmp_path, 3, "", 'tick(1) other_swaps("other.wav") tick(5)')
    assert "stop ours.wav" in out and "stop other.wav" not in out, out


def test_a_script_whose_begin_was_refused_stops_nothing_at_its_release(tmp_path: Path) -> None:
    """A refused begin leaves nothing for the next release to stop."""
    out = _run_audio_lua(tmp_path, 3, 'other_begins("ini.wav")', "tick(2) release()")
    assert any("ok=false" in ln for ln in out) and "stop ini.wav" not in out, out


def test_a_finished_script_stops_nothing_more_at_its_release(tmp_path: Path) -> None:
    """After the script stopped its file, a later recording on the path is somebody else's."""
    out = _run_audio_lua(tmp_path, 2, "", 'tick(4) other_begins("ours.wav") release()')
    assert out.count("stop ours.wav") == 1, out


@pytest.mark.parametrize(("answer", "said"), [
    (None, "may not have been evaluated yet"),
    (transport.Answer("", False, "mcp:2: boom"), "raised (mcp:2: boom), so it armed nothing"),
    (transport.Answer("", True, "nil"), "frame notifier may still be armed"),
])
def test_an_unsettled_recording_says_what_its_script_did(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: Any, said: str,
) -> None:
    """The message says what the console answered: nothing yet, a raise, or an evaluation."""
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", None, [_armed(1)])
    unsettled = {"status": "INVALID", "code": "not_settled", "message": "still moves",
                 "frame_before": 100, "frame_after": 103, "session": {}}
    monkeypatch.setattr(lua, "queued_then_ran",
                        lambda *a: (dict(unsettled), answer, 0, 0))
    out = s.audio_record(frames=30)
    assert out["code"] == "not_settled" and said in out["message"], out["message"]
    assert (out["frame_before"], out["frame_after"]) == (100, 103), "the run's own frames"


def test_a_refusal_carrying_its_own_frames_keeps_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A refusal naming its own `frame_before`/`frame_after` keeps them."""
    ses = _channel(monkeypatch, tmp_path)
    _put(ses, 1, ses.scratch / "snap" / "audio-1.wav", None, [_armed(1)])

    def refused_run(*a: Any) -> Any:
        raise mstate.Invalid("wait_expired", "the run's own", frame_before=7, frame_after=9)
    monkeypatch.setattr(lua, "queued_then_ran", refused_run)
    out = s.audio_record(frames=30)
    assert (out["frame_before"], out["frame_after"]) == (7, 9), out


def test_the_frames_refusal_states_the_mixer_rate_from_its_constant() -> None:
    """The refusal states `MIXER_UPDATE_HZ` and `FRAMES_MIN`, never a hand-written copy."""
    import types
    source = Path(maudio.__file__).read_text()
    assert source.count("MIXER_UPDATE_HZ = 50\n") == 1 and source.count("FRAMES_MIN = 2\n") == 1
    other = types.ModuleType("mame_audio_other_rate")
    exec(compile(source.replace("MIXER_UPDATE_HZ = 50\n", "MIXER_UPDATE_HZ = 60\n")
                 .replace("FRAMES_MIN = 2\n", "FRAMES_MIN = 3\n"), maudio.__file__, "exec"),
         other.__dict__)
    said = other.FRAMES_WHY
    assert "1/60 of an emulated second" in said, said
    assert "3 is the fewest" in said and "under 180 Hz" in said, said
    out = refused("frames=1 is below 2: ", s.audio_record(frames=1))
    assert maudio.FRAMES_WHY in out["message"], out


def test_a_refusal_after_the_run_began_says_why_it_has_no_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no stop having read a frame, both frame fields say so."""
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    with pytest.raises(mstate.Invalid) as e, mrec._frames_said(None):
        raise mstate.Invalid("unexpected_answer", "the run is this test's")
    assert e.value.fields["frame_before"]["available"] is False, e.value.fields
    assert e.value.fields["frame_after"]["available"] is False, e.value.fields


def test_a_recording_is_begun_under_its_name_without_the_extension_mame_appends() -> None:
    """MAME appends `.avi` itself, so the name handed over leaves it off."""
    assert mrec.begun_as(Path("/x/snap/record-2.avi")) == str(Path("/x/snap/record-2"))
    assert mrec.begun_as(Path("/x/out/take.AVI")) == str(Path("/x/out/take"))
