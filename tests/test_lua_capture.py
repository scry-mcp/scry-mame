"""The Lua channel: record, captures, saved states and drive."""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any

import pytest
from lua_support import (  # noqa: E402
    AVI_HEAD,
    R_ABS,
    STA_HEAD,
    TRIO,
    _captured,
    _channel,
    _logging_stateload,
    _marks_of,
    _whole,
)
from session_doubles import blank_session, documented, refused  # noqa: E402

from scry_mame import files as mfiles  # noqa: E402
from scry_mame import (
    launch,  # noqa: E402
    lua,  # noqa: E402
    running,  # noqa: E402
    transport,  # noqa: E402
)
from scry_mame import recording as mrec
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


def test_the_fixtures_reset_is_derived_from_state_and_not_from_a_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE MECHANISM THAT REPLACED TWO HAND-WRITTEN LISTS, held to what it claims."""
    fresh = mstate.State()
    for name, value in vars(fresh).items():
        if name == "start_seq":
            continue
        dirty = (value + 7 if isinstance(value, int) and not isinstance(value, bool)
                 else not value if isinstance(value, bool)
                 else {"leftover": 1} if isinstance(value, dict)
                 else ["leftover"] if isinstance(value, list)
                 else "leftover" if isinstance(value, str)
                 else object())
        monkeypatch.setattr(mstate.STATE, name, dirty)
    blank_session(monkeypatch)
    standing = {name: getattr(mstate.STATE, name) for name in vars(fresh)
                if name != "start_seq" and getattr(mstate.STATE, name) != getattr(fresh, name)}
    assert standing == {}, f"fields the reset left dirty: {sorted(standing)}"


def test_the_command_line_opens_the_console_and_names_the_state_directory(
    tmp_path: Path
) -> None:
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}abc"
    cmd = launch.build_command("/bin/mame", "m68k-dual", "/roms", 23946, ["-window"], str(scratch))
    assert "-console" in cmd
    assert cmd[cmd.index("-state_directory") + 1] == str(scratch / "sta")
    assert cmd[cmd.index("-statename") + 1] == "%g", "an ini cannot move the states' folder"
    state = tmp_path / "state"
    cmd = launch.build_command("/bin/mame", "m68k-dual", "/roms", 23946, ["-window"], str(scratch),
                               state_dir=str(state))
    assert cmd[cmd.index("-state_directory") + 1] == str(state / "sta")


@pytest.mark.parametrize("answered", ["none", "ok", "raised"])
def test_input_under_a_run_that_did_not_settle_is_the_runs_refusal_as_a_recordings_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answered: str
) -> None:
    """The recordings' shape"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    unsettled = {"status": "INVALID", "code": "not_settled",
                 "message": "the frame counter still moves", "frame_before": 100,
                 "frame_after": 103, "session": {}}
    real = lua.queued_then_ran

    def run(*a: Any) -> Any:
        _ran, answer, resent, moved = real(*a)
        answer = {"none": None, "ok": answer,
                  "raised": transport.Answer("", False, "boom")}[answered]
        return dict(unsettled), answer, resent, moved

    monkeypatch.setattr(lua, "queued_then_ran", run)
    out = s.input(port=":P1", field="Coin 1", value=1, frames=4)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert out["message"].startswith("the frame counter still moves. "), out
    assert "input's state is not read" in out["message"], out
    said = {"none": "may not have been evaluated yet", "ok": "frame notifier may still be armed",
            "raised": "raised (boom), so it armed nothing"}[answered]
    assert said in out["message"], out
    assert ":P1" in out["message"] and "Coin 1" in out["message"], out
    for key in ("released", "active", "port_held", "frame_set", "frame_release_planned", "name",
                "mask", "note", "pending"):
        assert key not in out, key
    assert out["frame_before"] == 100 and out["frame_after"] == 103, out
    assert out["lines_ahead"] == 0 and out.get("drain_steps", 0) == 0, out
    assert (answered == "none") or "thread_errors" in out, out


def test_record_checks_the_avi_header_and_runs_two_frames_past_the_recording(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    path = ses.scratch / "snap" / "record-1.avi"
    ses.answers[1] = _captured(5)
    ses.marks[1] = [m.replace("#5", "#1") for m in _marks_of("MAME_MCP_RECORD#5")]
    ses.files[1] = (path, AVI_HEAD)
    out = s.record(frames=30)
    assert out["status"] == "ok", out
    assert out["path"] == str(path) and out["bytes"] == len(AVI_HEAD)
    assert out["avi_frames"] == 30, "the captured header declares the frames asked for"
    assert out["frame_begin"] == 301 and out["frame_end"] == 330
    assert out["recording_after"] is True and out["ended"] is True
    assert out["frame_after"] - out["frame_before"] == 33, (
        "frames + 3: one for the begin, two for the file to close")
    assert out["summary"].startswith("record: 30 frames,")
    assert list(out)[-1] == "session"
    keys = list(out)
    assert keys.index("lines_ahead") < keys.index("path") < keys.index("cause"), (
        "the wrapper's own fields come before the stop survey, as the docstring lists them")
    assert out["session"]["altered"] is False


def test_record_writes_to_the_dest_it_is_given_and_names_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `dest` is where the script records, as a Lua string in the chunk, and the file checked and
    named in the reply"""
    ses = _channel(monkeypatch, tmp_path)
    dest = tmp_path / "mine.avi"
    ses.answers[1] = _captured(5)
    ses.marks[1] = [m.replace("#5", "#1") for m in _marks_of("MAME_MCP_RECORD#5")]
    ses.files[1] = (dest, AVI_HEAD)
    out = s.record(frames=30, dest=str(dest))
    assert out["status"] == "ok" and out["path"] == str(dest), out
    # a Lua literal inside the chunk, which quotes the whole script once more
    sent = transport.lua_string(transport.lua_string(mrec.begun_as(dest)))[1:-1]
    assert sent.encode() in ses.stdin.getvalue(), "the chunk records to the dest"
    assert not (ses.scratch / "snap" / "record-1.avi").exists()


def test_captures_lists_what_this_session_recorded_and_snapped_and_says_what_is_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without a listing, `record` and `snapshot` each hand back a path and nothing remembers
    them."""
    ses = _channel(monkeypatch, tmp_path)
    empty = s.captures()
    assert empty["status"] == "ok" and empty["captures"] == [], empty
    assert empty["summary"] == "captures: 0 files"
    path = ses.scratch / "snap" / "record-1.avi"
    ses.answers[1] = _captured(5)
    ses.marks[1] = [m.replace("#5", "#1") for m in _marks_of("MAME_MCP_RECORD#5")]
    ses.files[1] = (path, AVI_HEAD)
    assert s.record(frames=30)["status"] == "ok"
    dest = tmp_path / "shot.png"
    monkeypatch.setattr(mfiles, "_complete_png", lambda p: p.exists())
    (ses.scratch / "snap" / "snapshot-1.png").write_bytes(b"\x89PNG")
    assert s.snapshot(dest=str(dest))["status"] == "ok"
    out = s.captures()
    assert [c["kind"] for c in out["captures"]] == ["avi", "png"]
    avi, png = out["captures"]
    assert avi["path"] == str(path) and avi["bytes"] == len(AVI_HEAD) and avi["avi_frames"] == 30
    assert "frames" not in avi, "an AVI's count is `avi_frames`, as `record` answers it"
    assert avi["present"] is True and png["path"] == str(dest) and png["present"] is True
    assert "frames" not in png and png["bytes"] == 4
    assert out["summary"] == "captures: 2 files, 1 avi, 1 png"
    dest.unlink()
    gone = s.captures()["captures"][1]
    assert gone["present"] is False and gone["bytes"]["available"] is False
    assert list(out)[-1] == "session"


def test_the_captures_summary_counts_every_kind_and_its_parts_sum_to_the_total(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A graphics tool's `image` is a capture like any other, and the line counts every kind"""
    _channel(monkeypatch, tmp_path)
    for kind, name in (("image", "a.png"), ("mmm", "h.mmm"), ("zzz", "f.zzz"), ("png", "b.png"),
                       ("image", "c.png"), ("wav", "e.wav"), ("aaa", "g.aaa"),
                       ("trace", "d.trace")):
        (tmp_path / name).write_bytes(b"x")
        mstate.STATE.captures.append((kind, str(tmp_path / name)))
    out = s.captures()
    assert out["summary"] == ("captures: 8 files, 1 png, 2 image, 1 wav, 1 trace, 1 mmm, "
                              "1 zzz, 1 aaa"), out["summary"]


def test_record_refuses_a_missing_file_a_wrong_header_and_fewer_than_two_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mfiles, "FILE_WAIT_S", 0.05)
    for n, content in ((1, None), (2, b"RIFF" + bytes(60)),
                       (3, AVI_HEAD[:48] + bytes(4) + AVI_HEAD[52:])):
        ses.answers[n] = ses.sentinel(n)
        ses.marks[n] = [f"[luaengine] MAME_MCP_RECORD#{n} begin frame=1 recording=true",
                        f"[luaengine] MAME_MCP_RECORD#{n} end frame=2"]
        if content is not None:
            ses.files[n] = (ses.scratch / "snap" / f"record-{n}.avi", content)
        out = s.record(frames=2)
        assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert "ZERO frames" in out["message"]
    out = refused("cannot end a recording on the call that begins it", s.record(frames=1))
    assert out["code"] == "bad_argument"
    refused("frames=0 is below 2: the frame notifier cannot end", s.record(frames=0))
    refused(R_ABS, s.record(frames=2, dest="rel.avi"))


def test_record_raised_or_cut_short_is_said_in_the_consoles_words_or_as_still_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1, False, "mcp:5: this machine has no screen to record")
    out = refused("no screen to record", s.record(frames=2))
    assert out["code"] == "no_channel"
    ses.answers[2] = ses.sentinel(2)
    ses.marks[2] = ["[luaengine] MAME_MCP_RECORD#2 begin frame=10 recording=true"]
    out = s.record(frames=5)
    assert out["status"] == "ok" and out["ended"] is False and out["frame_end_planned"] == 14, out
    assert out["began"] is True, out
    assert out["summary"] == "record: still OPEN from frame 10, ends at 14"


def test_record_predicts_the_end_frame_its_script_ends_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The end the open and not-begun replies predict is the count the script ends at."""
    _channel(monkeypatch, tmp_path)
    seen: dict[str, Any] = {}

    real = inspect.signature(mrec.recording_run)

    def run(*args: Any) -> dict[str, Any]:
        seen.update(real.bind(*args).arguments)
        raise mstate.Invalid("bad_argument", "the run is this test's")

    monkeypatch.setattr(mrec, "recording_run", run)
    s.record(frames=5)
    ends = re.search(r"counted >= (\d+) - (\d+) then", seen["script"])
    assert ends is not None, seen["script"]
    assert int(ends.group(1)) - int(ends.group(2)) == seen["ends_after"] == 4, seen


@pytest.mark.parametrize(("vblank", "begins"), [("false", 60), ("true", 61)])
def test_a_recording_not_begun_begins_where_its_armed_mark_says(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, vblank: str, begins: int
) -> None:
    """MAME calls the frame notifiers as a vblank BEGINS and moves the frame counter as it ENDS, so
    a chunk the debugger evaluated at a stop inside a vblank is first called on the next frame, and
    one at a stop in the active display on."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = [f"[luaengine] MAME_MCP_RECORD#1 armed frame=60 vblank={vblank}"]
    out = s.record(frames=5)
    assert out["status"] == "ok" and out["began"] is False and out["ended"] is False, out
    assert (out["verdict"], out["frame_after"]) == ("ELAPSED", 108), out
    assert (out["frame_begin_planned"], out["frame_end_planned"]) == (begins, begins + 4), out
    assert out["avi_frames"]["available"] is False and out["bytes"]["available"] is False, out
    assert out["note"] == ("the recording has NOT begun: a stop came before the script's frame "
                           "notifier ran, and the notifier begins it on the next frame the "
                           "machine reaches, unless another `record` call releases it first")
    assert out["summary"] == f"record: NOT begun, begins at frame {begins}, ends at {begins + 4}"
    assert mstate.STATE.captures == [], "a recording not begun is no capture"


def test_a_recording_whose_marks_are_lost_is_refused_and_not_called_not_begun(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No `begin` mark reads as "not begun" only beside the chunk's own `armed` line, which a chunk
    that answered has logged as it was evaluated"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    out = refused("not even the `armed` line", s.record(frames=5))
    assert out["code"] == "readback_refused" and out.keys() >= TRIO, out
    unsettled = {"status": "INVALID", "code": "not_settled",
                 "message": "the frame counter still moves", "frame_before": 100,
                 "frame_after": 103, "session": {}}
    monkeypatch.setattr(lua, "queued_then_ran",
                        lambda *a: (dict(unsettled), transport.Answer("", True, "nil"), 0, 0))
    out = s.record(frames=5)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert "began" not in out and "frame_begin_planned" not in out and out["path"], out


def test_captures_says_a_recording_its_call_left_unfinished_is_not_listed() -> None:
    """A recording its call answered open or not begun is finished, or released, by a later run that
    reads no file, so `captures` never lists it"""
    here = Path(__file__).resolve().parent.parent
    texts = {"server": documented("captures"), "recording": mrec.captures.__doc__ or "",
             "REFERENCE": (here / "REFERENCE.md").read_text()}
    for name, text in texts.items():
        flat = " ".join(text.split()).lower()
        assert "wrote this session" not in flat and "graphics tools wrote" not in flat, name
        assert "handed back this session" in flat, name
    assert "a recording its call answered still open or not begun is not listed" in texts[
        "server"]


def test_state_save_checks_the_header_and_state_load_judges_it_before_the_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`statesave` through the console, the `.sta` found in the system's own folder and its header
    checked"""
    ses = _channel(monkeypatch, tmp_path)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(bytes(64))
    monkeypatch.setattr(mstate.STATE, "reference", (rom, 0x10, 0x20))
    # The captured header names m68k-dual: as m68k the save is refused on the name.
    out = s.state_write("save", name="live")
    assert out["status"] == "INVALID" and "state of `m68k-dual`" in out["message"], out
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    out = s.state_write("save", name="live")
    assert out["status"] == "ok", out
    assert Path(out["path"]) == ses.scratch / "sta" / "m68k-dual" / "live.sta"
    assert out["bytes"] == len(STA_HEAD) and out["frame"] == 100 and out["pc"] == "0x00000400"
    assert set(out["errorlog"]) == {"lines_total", "truncated", "lines", "mark"}, (
        "the survey's shape")
    assert "statesave live" in ses.commands
    assert out["session"]["altered"] is False
    refused("already exists", s.state_write("save", name="live"))
    boss = s.state_write("save", name="Boss_1")
    assert boss["name"] == "boss-1" and Path(boss["path"]).name == "boss-1.sta", boss
    refused("already exists", s.state_write("save", name="boss-1"))
    refused("no letter or digit", s.state_write("save", name="_ _"))
    # THE MACHINE MOVES before the load, so the comparison after it can prove one.
    ses.stale_after_load = True
    ses.saved_frames["live"] = ses.frame
    ses.frame += 3
    loaded = s.state_write("load", name="live")
    assert loaded["status"] == "ok", loaded
    assert loaded["rom_check"] == "OK" and loaded["cause"] == "stateload live"
    assert loaded["verified"] is True and loaded["saved"] == {"frame": 100, "pc": "0x00000400"}, (
        "one spelling per concept: the pc inside `saved` reads like the pc beside it")
    assert ses.checked == [(0x10, 0x20)], "the ROM check ran again, with start's arguments"
    assert loaded["session"]["altered"] is True
    # ONE WORD, ONE SHAPE.
    assert isinstance(loaded["output"], str) and "console" not in loaded, loaded
    assert isinstance(_whole()["console"], dict)
    assert "stateload live" in ses.commands
    assert "taps_across" not in loaded, "no tap, nothing named"
    # A LIVE TAP counted across the load: the reply names it, as `reset`'s does.
    monkeypatch.setitem(mstate.STATE.tallies, ("frame_lo", ":maincpu"), {})
    loaded = s.state_write("load", name="live")
    assert loaded["taps_across"] == [{"ref": "frame_lo", "cpu": ":maincpu"}], loaded
    assert mstate.STATE.tallies[("frame_lo", ":maincpu")]["across"][0]["event"] == (
        "stateload live")
    out = refused("no state named", s.state_write("load", name="nope"))
    assert out["code"] == "unknown_ref" and "`state_list` names the ones held" in out["message"]
    ses.saved_frames["boss-1"] = ses.frame
    assert s.state_write("load", name="boss-1")["name"] == "boss-1", "saved as Boss_1"
    assert s.state_write("load", name="BOSS 1")["name"] == "boss-1", "one state, any spelling"


def test_state_load_hands_the_stop_no_field_the_survey_also_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A field the tool passes beside the survey and the survey writes too is overwritten on every
    reply"""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    assert s.state_write("save", name="live")["status"] == "ok"
    _logging_stateload(monkeypatch, ses, "stateload says: something about the state")
    finish = running.finish_stop
    clashes: list[set[str]] = []

    def spy(ses_: Any, seen: dict[str, Any], how: str, **base: Any) -> dict[str, Any]:
        clashes.append(set(base) & set(seen))
        return finish(ses_, seen, how, **base)

    monkeypatch.setattr(running, "finish_stop", spy)
    assert s.state_write("load", name="live")["status"] == "ok"
    assert clashes == [set()], clashes


def test_state_list_names_every_state_in_the_folder_with_what_this_session_knows_of_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Writing and loading states with no way to list them leaves the caller remembering the
    names."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    empty = s.state_list()
    assert empty["status"] == "ok" and empty["states"] == [], empty
    assert Path(empty["state_dir"]) == ses.scratch / "sta" / "m68k-dual"
    assert empty["summary"] == f"state_list: 0 states in {empty['state_dir']}"
    assert s.state_write("save", name="live")["status"] == "ok"
    (ses.scratch / "sta" / "m68k-dual" / "earlier.sta").write_bytes(STA_HEAD)
    out = s.state_list()
    assert [x["name"] for x in out["states"]] == ["earlier", "live"]
    by = {x["name"]: x for x in out["states"]}
    assert by["live"]["frame"] == 100 and by["live"]["pc"] == "0x00000400"
    assert by["live"]["bytes"] == len(STA_HEAD) and Path(by["live"]["path"]).is_file()
    assert by["earlier"]["frame"]["available"] is False, by["earlier"]
    assert "did not write" in by["earlier"]["frame"]["why"] and "why" not in by["earlier"]
    assert out["summary"] == f"state_list: 2 states in {out['state_dir']}"
    assert list(out)[-1] == "session" and out["session"]["altered"] is False


def test_state_load_refuses_a_state_mame_would_refuse_in_silence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A corrupt header and a foreign system's state both load as `ok` through the console with
    nothing in any log."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    assert s.state_write("save", name="good")["status"] == "ok"
    folder = ses.scratch / "sta" / "m68k-dual"
    corrupt = bytearray(STA_HEAD)
    corrupt[0:8] = b"NOTASAVE"
    (folder / "corrupt.sta").write_bytes(corrupt)
    foreign = bytearray(STA_HEAD)
    foreign[0x0A:0x1C] = b"pacman".ljust(0x12, b"\0")
    (folder / "foreign.sta").write_bytes(foreign)
    other = bytearray(STA_HEAD)
    other[0x1C:0x20] = b"\x01\x02\x03\x04"
    (folder / "other.sta").write_bytes(other)
    assert refused("savestate magic", s.state_write("load",
                                                    name="corrupt"))["code"] == "readback_refused"
    assert refused("state of `pacman`", s.state_write("load", name="foreign"))["system"] == "pacman"
    out = refused("as this session saves it", s.state_write("load", name="other"))
    assert out["code"] == "readback_refused"
    assert not [c for c in ses.commands if c.startswith("stateload")], "judged before the console"
    # A well-formed state MAME silently did not load: the machine did not go back.
    ses.frame = 160
    out = refused("MAME did not load it", s.state_write("load", name="good"))
    assert out["code"] == "readback_refused" and out["saved"] == {"frame": 100, "pc": "0x00000400"}
    # ...and the stop it surveyed is remembered, carried by the refusal itself.
    assert out["frame"] == 160 and out["stop_seq"] == mstate.STATE.last_stop["seq"], out


def test_state_save_with_no_file_is_not_vouched_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mfiles, "FILE_WAIT_S", 0.05)
    ses.write_states = False
    out = refused("lost.sta appeared", s.state_write("save", name="lost"))
    assert out["code"] == "readback_refused"

def test_drive_marks_the_emulator_log_acts_verifies_and_looks_from_the_mark(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """LOOK, ACT, VERIFY for an arcade board"""
    ses = _channel(monkeypatch, tmp_path)
    (ses.scratch / "error.log").write_text("[luaengine] MAME_MCP_INPUT#0 release frame=1 "
                                           "port_held=00000000\n")   # STALE, before the mark
    ses.answers[1] = _captured(3)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.drive(act=[{"op": "input", "port": ":P1", "field": "Coin 1", "frames": 4}],
                  expect=r"release frame=\d+", pattern="MAME_MCP_INPUT", limit=10)
    assert out["status"] == "ok", out
    assert out["act"]["steps_completed"] == 1, out["act"]
    assert "failed" not in out["act"] and out["act"]["failed_at"]["available"] is False, out["act"]
    assert out["verify"]["seen"] is True and "release frame=" in out["verify"]["line"], out
    looked = out["looked"]["emulator"]
    assert looked["available"] is True and looked["since_mark"] > 0, looked
    assert (looked["lines_written"], looked["lines_total"], len(looked["lines"])) == (2, 2,
                                                                                      2), looked
    assert all("#1" in ln for ln in looked["lines"]), "the stale #0 line is before the mark"
    assert out["summary"] == "drive: effect seen, TARGET", out["summary"]
    # The cut: `lines=1` keeps the LAST matching line, the counts say what was cut.
    ses.answers[2] = _captured(3).replace(b"#3", b"#2")
    ses.marks[2] = [m.replace("#3", "#2") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.drive(act=[{"op": "input", "port": ":P1", "field": "Coin 1", "frames": 4}],
                  pattern="release", limit=1)
    looked = out["looked"]["emulator"]
    assert (looked["lines_written"], looked["lines_total"], len(looked["lines"])) == (2, 1,
                                                                                      1), looked
    assert "release" in looked["lines"][0]
    assert out["verify"]["checked"] is False and "no `expect`" in out["verify"]["why"]


def test_drive_reports_a_miss_a_failed_act_and_refuses_what_it_cannot_do(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(3)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.drive(act=[{"op": "input", "port": ":P1", "field": "Coin 1", "frames": 4}],
                  expect="never logged", seconds=1)
    assert out["status"] == "INVALID" and out["code"] == "wait_stopped", out
    assert out["verify"]["seen"] is False and "STOPPED" in out["verify"]["why"], out["verify"]
    assert out["act"]["steps_completed"] == 1 and "emulator" in out["looked"]
    assert out["summary"].startswith("drive: INVALID (wait_stopped)"), out["summary"]
    # A failed step ends the act before any verification, with the account and the look.
    out = s.drive(act=[{"op": "run_for", "frames": -1}], expect="x")
    assert out["status"] == "INVALID" and out["act"]["steps_completed"] == 0, out
    # Refused before anything moves.
    bad: dict[str, Any]
    moved = ses.commands.count("gvblank")
    for bad in ({"act": []}, {"act": [{"op": "no_such_op"}]},
                {"act": [{"op": "status"}], "pattern": "("},
                {"act": [{"op": "status"}], "seconds": 3},
                {"act": [{"op": "status"}], "expect": "x", "seconds": 0},
                {"act": [{"op": "status"}], "limit": 0}):
        got = s.drive(**bad)
        assert got["status"] == "INVALID" and got["code"] == "bad_argument", (bad, got)
    assert ses.commands.count("gvblank") == moved, "a refusal moves nothing"


def test_the_drive_summary_reads_the_field_the_reply_actually_carries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE HALF OF A RENAME THAT GOES QUIET."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    # The guest's own line, written where the emulator writes it AND WHEN it would.
    none = s.drive(act=[{"op": "step", "count": 1}])
    assert none["verify"]["checked"] is False, none
    assert "no expectation" in none["summary"], none["summary"]
    stepper = ses.step

    def step_and_log() -> str:
        out = stepper()
        with open(ses.scratch / "error.log", "a") as log:
            log.write("[:maincpu] DRIVE_MARK here\n")
        return out

    monkeypatch.setattr(ses, "step", step_and_log)
    seen = s.drive(act=[{"op": "step", "count": 1}], expect="DRIVE_MARK", seconds=0.5)
    monkeypatch.setattr(ses, "step", stepper)
    assert seen["status"] == "ok" and seen["verify"]["checked"] is True, seen
    assert "effect seen" in seen["summary"], seen["summary"]


def test_a_record_refused_after_its_run_says_the_frames_it_advanced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The AVI is checked after the whole run"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = ["[luaengine] MAME_MCP_RECORD#1 armed frame=100 vblank=false",
                    "[luaengine] MAME_MCP_RECORD#1 begin frame=100 recording=true",
                    "[luaengine] MAME_MCP_RECORD#1 end frame=104"]
    before = 100                      # the double's frame counter at its start
    out = refused("is not a finished AVI", s.record(frames=5))
    assert out["frame_before"] == before and out["frame_after"] > out["frame_before"], out
    assert out["frame_after"] == mstate.STATE.last_stop["frame"], out
