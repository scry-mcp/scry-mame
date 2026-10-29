"""Section L of the live matrix: `audio_record`, the mixer's WAV bounded by the frame counter.

Run alone, it is the same machinery over this section only:

    MAME_BINARY=... MAME_TEST_ROMS=... uv run python tests/live/matrix_audio.py
"""

import hashlib
import shutil
import wave
from array import array
from pathlib import Path
from typing import Any

from bench_boards import board_missing, m68k_dual_missing
from live_harness import (
    WAIT_CEILING_S,
    Board,
    boards_cover,
    boot,
    call,
    cell,
    circus_boot,
    free_boards_missing,
    fresh,
    ok,
    refused,
    run_boards,
    run_sections,
    said,
    section,
)
from matrix_acceptance import V30, v30_boot
from scry_core import traffic

from scry_mame.transport import lua_string

# Written here, not imported from the server, so a server change turns the cells red. MAME mixes
# in updates of a fiftieth of a second (`STREAMS_UPDATE_FREQUENCY`); the span is exact on the
# frame notifier.
MIXER_UPDATES_PER_S = 50
SPAN_TOLERANCE_S = 1e-6
# v30's AY-3-8910: tone Hz = clock / (16 * 12-bit period). The game's sound driver rewrites the
# chip every frame, so a write tap substitutes the pinned value and the per-frame write sets it.
AY_CLOCK_HZ = 2_000_000
AY_PERIOD_A = 0x40
AY_PERIOD_B = 0x80
AY_TONE_TOLERANCE = 0.05
AY_PIN_LUA = """local io = manager.machine.devices[":maincpu"].spaces["io"]
local regs = {{0, %(period)d}, {1, 0}, {7, 0x3E}, {8, %(volume)d}}
local pin = {} for _, rv in ipairs(regs) do pin[rv[1]] = rv[2] end
local sel = -1
_G._mame_matrix_ay_tap = io:install_write_tap(0x0000, 0x0003, "matrix-ay-pin",
    function(offset, data, mask)
        if offset == 0 then sel = data & 0xff return nil end
        if offset == 2 and pin[sel] ~= nil then return (data & 0xff00) | pin[sel] end
        return nil
    end)
_G._mame_matrix_ay_poke = emu.add_machine_frame_notifier(function()
    for _, rv in ipairs(regs) do io:write_u8(0x0000, rv[1]) io:write_u8(0x0002, rv[2]) end
end)
"""
# The mixer's file is shared by every caller: these notifiers do, mid-recording, what another
# caller could (swap the file, or release the tool's script). The tool's script must not stop a
# file it did not begin nor write once released.
SWAP_LUA = """local snd = manager.machine.sound
local calls = 0
_G._mame_matrix_swap = emu.add_machine_frame_notifier(function()
    calls = calls + 1
    if calls == %(at)d then snd:stop_recording() snd:start_recording(%(path)s) end
end)
"""
RELEASE_LUA = """local calls = 0
_G._mame_matrix_release = emu.add_machine_frame_notifier(function()
    calls = calls + 1
    if calls == %(at)d then _G._mame_mcp_audio_release() end
end)
"""
RECORDING_LUA = "print(tostring(manager.machine.sound.recording))"
END_MARK = r"MAME_MCP_AUDIO#[0-9]+ end"
BEGIN_MARK = r"MAME_MCP_AUDIO#[0-9]+ begin .*ok=true"
PERIOD_LUA = ('local s = nil for _, x in pairs(manager.machine.screens) do s = x break end '
              'print(string.format("%.17g", s.frame_period))')

L_TITLE = "audio_record: the mixer's WAV, bounded by frames, checked against its own header"
L_CELLS = [f"L{n} {text}" for n, text in enumerate([
    "circus: 30 frames recorded, the counter and the span exact, the samples within one update",
    "circus: the file read by stdlib wave agrees with the reply and holds what its header claims, "
    "and the same reading of a copy 2 bytes short does not",
    "circus: captures lists the WAV present with its samples",
    "circus: frames=1 is refused bad_argument",
    "circus: the same dest again is refused and the file is left byte for byte",
    "circus: a running machine is refused not_stopped",
    "m68k-dual: a 30-frame recording has two channels",
    f"v30: the AY pinned at period {AY_PERIOD_A:#x} records its tone",
    f"v30: pinned at period {AY_PERIOD_B:#x} on a fresh boot, the tone halves",
    "circus: a file another caller swaps in under an open recording is still recording after "
    "that recording's last frame, and the cut recording is refused",
    "circus: a recording released mid-run began (its begin mark) and writes nothing more: no end "
    "mark, the mixer stopped",
    "circus: under an ini naming wavwrite the refused recording leaves the session's file "
    "recording past its last frame, logs no end mark, and the file is whole when closed; the "
    "refusal names the frames its run advanced",
    "v30 S3: audio_compare measure hears the pinned tone (an onset, not silent) and calls the AY "
    "pinned at volume 0 silent",
    "v30 S3: audio_compare diff finds two recordings of one pinned tone the same, and the halved "
    "tone different",
    "v30 S3 cost: the question is answered in numbers, with no picture and no sound sent",
])]


def bounded_exactly(r: dict[str, Any], frames: int, period: float | None) -> bool:
    """The recording spans `frames` frames, end inclusive, and its samples fit that span."""
    if not ok(r) or not r.get("ended") or period is None:
        return False
    rate, samples, emulated = r["sample_rate_hz"], r["samples"], r["emulated_s"]
    return bool(samples > 0 and r["frame_end"] - r["frame_begin"] + 1 == frames
            and abs(emulated - frames * period) < SPAN_TOLERANCE_S
            and abs(samples - emulated * rate) <= rate // MIXER_UPDATES_PER_S + 1)


def stdlib_wave_agrees(path: Path, r: dict[str, Any]) -> bool:
    """stdlib `wave` reads the reply's channels, rate and samples off a file holding its whole
    header-declared length."""
    try:
        with wave.open(str(path)) as w:
            n, channels = w.getnframes(), w.getnchannels()
            same = (channels, w.getframerate(), n) == (r.get("channels"), r.get("sample_rate_hz"),
                                                      r.get("samples"))
            return same and len(w.readframes(n)) == n * 2 * channels
    except (OSError, EOFError, wave.Error):
        return False


def tone_hz(path: Path) -> float | None:
    """Zero-crossing frequency of a MONO recording past the first mixer update (the attack)."""
    with wave.open(str(path)) as w:
        if w.getnchannels() != 1:
            return None
        rate = w.getframerate()
        samples = array("h")
        samples.frombytes(w.readframes(w.getnframes()))
    tail = samples[rate // MIXER_UPDATES_PER_S:]
    if len(tail) < 2:
        return None
    mean = sum(tail) / len(tail)
    above = [v > mean for v in tail]
    crossings = sum(1 for a, b in zip(above, above[1:], strict=False) if a != b)
    return float(crossings / 2 / (len(tail) / rate))


def _period() -> float | None:
    r = call("lua", script=PERIOD_LUA, read_only=True)
    try:
        return float(str(r.get("output")).strip())
    except ValueError:
        return None


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _l_circus(t: list[str]) -> None:
    circus_boot()
    call("run_for", frames=30, seconds=WAIT_CEILING_S)
    period = _period()
    dest = Path(fresh(".wav"))
    r = call("audio_record", frames=30, dest=str(dest), seconds=WAIT_CEILING_S)
    cell(t[0], bounded_exactly(r, 30, period), f"period {period} / {said(r)}")
    short = Path(fresh(".wav"))
    if dest.is_file():
        shutil.copyfile(dest, short)
        with short.open("r+b") as fh:
            fh.truncate(dest.stat().st_size - 2)
    cell(t[1], stdlib_wave_agrees(dest, r) and not stdlib_wave_agrees(short, r),
         f"file {stdlib_wave_agrees(dest, r)}, 2 bytes short {stdlib_wave_agrees(short, r)}")
    listed = [c for c in call("captures").get("captures") or [] if c.get("path") == str(dest)]
    cell(t[2], len(listed) == 1 and listed[0].get("present") is True
         and listed[0].get("samples") == r.get("samples"), str(listed)[:160])
    one = call("audio_record", frames=1, seconds=WAIT_CEILING_S)
    cell(t[3], refused(one, "bad_argument"), said(one))
    before = _sha(dest)
    again = call("audio_record", frames=2, dest=str(dest), seconds=WAIT_CEILING_S)
    cell(t[4], refused(again, "bad_argument") and "already exists" in str(again.get("message"))
         and before is not None and _sha(dest) == before, said(again))
    call("resume")
    running = call("audio_record", frames=10, seconds=WAIT_CEILING_S)
    call("stop")
    cell(t[5], refused(running, "not_stopped"), said(running))
    call("close")


def _mixer_recording() -> bool | None:
    out = str(call("lua", script=RECORDING_LUA, read_only=True).get("output")).strip()
    return {"true": True, "false": False}.get(out)


def _end_marks() -> list[str] | None:
    return _marks(END_MARK)


def _marks(pattern: str) -> list[str] | None:
    r = call("log", pattern=pattern, channel="emulator")
    return r.get("lines") if ok(r) else None


def _finished_samples(path: Path) -> int:
    """Samples of a closed WAV whose header matches its size on disk, else 0 (open files read 0)."""
    try:
        with wave.open(str(path)) as w:
            n, block = w.getnframes(), w.getnchannels() * w.getsampwidth()
    except (OSError, EOFError, wave.Error):
        return 0
    return int(n) if path.stat().st_size == 44 + n * block else 0


def _l_swap(t: list[str]) -> None:
    circus_boot()
    call("run_for", frames=30, seconds=WAIT_CEILING_S)
    theirs = Path(fresh(".wav"))
    call("lua", script=SWAP_LUA % {"at": 10, "path": lua_string(str(theirs))})
    r = call("audio_record", frames=30, dest=fresh(".wav"), seconds=WAIT_CEILING_S)
    on, ends = _mixer_recording(), _end_marks()
    call("lua", script="manager.machine.sound:stop_recording()")
    # the tool's own one end mark is the control that `_end_marks` can see one
    cell(t[9], on is True and refused(r, "readback_refused")
         and "does not hold the span" in str(r.get("message")) and ends is not None
         and len(ends) == 1 and _finished_samples(theirs) > 0,
         f"recording after {on}, end marks {ends}, theirs {_finished_samples(theirs)} samples / "
         f"{said(r)}")
    call("close")


def _l_release(t: list[str]) -> None:
    circus_boot()
    call("run_for", frames=30, seconds=WAIT_CEILING_S)
    call("lua", script=RELEASE_LUA % {"at": 10})
    r = call("audio_record", frames=30, seconds=WAIT_CEILING_S)
    on, ends, begins = _mixer_recording(), _end_marks(), _marks(BEGIN_MARK)
    # the begin mark is the positive beside the absences
    cell(t[10], on is False and ends == [] and begins is not None and len(begins) == 1,
         f"recording after {on}, begin marks {begins}, end marks {ends} / {said(r)}")
    call("close")


def _l_wavwrite(t: list[str]) -> None:
    session = Path(fresh(".wav"))
    circus_boot(ini_extra=f"wavwrite {session}\n")
    call("run_for", frames=30, seconds=WAIT_CEILING_S)
    r = call("audio_record", frames=10, seconds=WAIT_CEILING_S)
    call("run_for", frames=30, seconds=WAIT_CEILING_S)
    on, ends = _mixer_recording(), _end_marks()
    call("lua", script="manager.machine.sound:stop_recording()")
    moved = (isinstance(r.get("frame_before"), int) and isinstance(r.get("frame_after"), int)
             and r["frame_after"] - r["frame_before"] >= 10)    # at least the frames asked
    cell(t[11], refused(r, "readback_refused") and "mixer refused" in str(r.get("message"))
         and on is True and ends == [] and _finished_samples(session) > 0 and moved,
         f"recording after {on}, end marks {ends}, session {_finished_samples(session)} "
         f"samples, frames {r.get('frame_before')} to {r.get('frame_after')} / {said(r)}")
    call("close")


def _l_m68k_dual(t: list[str]) -> None:
    boot(symbols=None)
    call("run_for", frames=30, seconds=WAIT_CEILING_S)
    r = call("audio_record", frames=30, seconds=WAIT_CEILING_S)
    cell(t[6], ok(r) and r.get("channels") == 2 and (r.get("samples") or 0) > 0, said(r))
    call("close")


def _ay_recording(period: int, volume: int = 0x0F) -> tuple[Path, dict[str, Any]]:
    """A fresh v30 with the AY pinned, 30 frames recorded: the file and the reply."""
    v30_boot(V30)
    call("run_for", frames=60, seconds=WAIT_CEILING_S)
    call("lua", script=AY_PIN_LUA % {"period": period, "volume": volume})
    dest = Path(fresh(".wav"))
    r = call("audio_record", frames=30, dest=str(dest), seconds=WAIT_CEILING_S)
    call("close")
    return dest, r


def _ay_tone(period: int) -> tuple[float | None, dict[str, Any], Path]:
    """The tone of `_ay_recording`, the reply and the file."""
    dest, r = _ay_recording(period)
    return (tone_hz(dest) if ok(r) and dest.is_file() else None), r, dest


def _near(hz: float | None, want: float) -> bool:
    return hz is not None and abs(hz - want) <= AY_TONE_TOLERANCE * want


def _l_v30(t: list[str]) -> None:
    want_a = AY_CLOCK_HZ / (16 * AY_PERIOD_A)
    hz_a, r, wav_a = _ay_tone(AY_PERIOD_A)
    cell(t[7], _near(hz_a, want_a) and r.get("sample_min") != r.get("sample_max"),
         f"{hz_a} Hz against {want_a:g} / {said(r)}")
    want_b = AY_CLOCK_HZ / (16 * AY_PERIOD_B)
    hz_b, r, wav_b = _ay_tone(AY_PERIOD_B)
    # near its own prediction AND near half of the first pin
    cell(t[8], _near(hz_b, want_b) and hz_a is not None and _near(hz_b, hz_a / 2),
         f"{hz_b} Hz against {want_b:g} and half of {hz_a} / {said(r)}")
    # `PENDING` is handed to the transcript at every cell, so the four replies are kept here.
    heard = call("audio_compare", method="measure", path=str(wav_a))
    muted_path, muted_r = _ay_recording(AY_PERIOD_A, volume=0)
    muted = call("audio_compare", method="measure",
                 path=str(muted_path)) if ok(muted_r) else muted_r
    m = (heard.get("measures") or [{}])[0]
    q = (muted.get("measures") or [{}])[0]
    # the AY at volume 0 rests at a steady nonzero level: silent, no onset, but a peak
    cell(t[12], ok(heard) and m.get("silent") is False and isinstance(m.get("onset_s"), float)
         and ok(muted) and q.get("silent") is True
         and (q.get("onset_s") or {}).get("available") is False
         and q.get("clipped") is False and q.get("peak_dbfs") is not None,
         f"pinned {m.get('peak_dbfs')} dBFS onset {m.get('onset_s')}; volume 0 silent "
         f"{q.get('silent')}, onset {q.get('onset_s')}, clipped {q.get('clipped')}, peak "
         f"{q.get('peak_dbfs')} dBFS")
    again, again_r = _ay_recording(AY_PERIOD_A)
    same = call("audio_compare", method="diff", a=str(again),
                b=str(wav_a)) if ok(again_r) else again_r
    other = call("audio_compare", method="diff", a=str(wav_b), b=str(wav_a))
    cell(t[13], ok(same) and same.get("class") in ("exact", "inaudible")
         and ok(other) and other.get("class") == "different",
         f"same tone {same.get('class')} {same.get('snr_db')} dB; halved {other.get('class')} "
         f"{other.get('snr_db')} dB")
    replies = [r for r in (heard, muted, same, other) if ok(r)]
    units = sum(traffic.json_units(r) for r in replies)
    tokens = sum(traffic.image_tokens(r) for r in replies)
    cell(t[14], len(replies) == 4 and tokens == 0,
         f"new way: {len(replies)} calls, {units} text units, {tokens} image tokens; hand way: "
         "not answerable through the server")


L_BOARDS = (
    Board(_l_circus, (0, 1, 2, 3, 4, 5), free_boards_missing),
    Board(_l_m68k_dual, (6,), m68k_dual_missing),
    Board(_l_v30, (7, 8, 12, 13, 14), lambda: board_missing("v30")),
    Board(_l_swap, (9,), free_boards_missing),
    Board(_l_release, (10,), free_boards_missing),
    Board(_l_wavwrite, (11,), free_boards_missing),
)
boards_cover("L_BOARDS", L_CELLS, L_BOARDS)


def register_l() -> None:
    """Register section L with the matrix: after every section registered before it."""
    section("L", L_TITLE, L_CELLS)(lambda: run_boards(L_CELLS, L_BOARDS))


if __name__ == "__main__":
    register_l()
    run_sections("SECTION L")
