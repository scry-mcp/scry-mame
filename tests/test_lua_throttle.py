"""The Lua channel: throttle, pending until the console answers it."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lua_support import (  # noqa: E402
    CONSOLE,
    _captured,
    _channel,
    _closed_after_the_mark,
    _marks_of,
    _running,
    _settles,
)
from scry_core import progress as mprogress  # noqa: E402
from session_doubles import refused  # noqa: E402

import mame_envelope as menvelope  # noqa: E402
import mame_lua as lua  # noqa: E402
import mame_running as running  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_transport as transport  # noqa: E402
import server as s  # noqa: E402


def test_throttle_is_pending_on_a_stopped_machine_and_applied_on_a_running_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    out = s.throttle(on=False)
    assert out["pending"] is True and out["tag"] == "MAME_MCP_THROTTLE#1"
    assert out["summary"] == "throttle off: pending until the console next reads a line"
    assert out["applies"].startswith("when the console next reads a line: a step, "), out
    assert out["confirmed_by"].startswith("its tag in the error log, read by the next stop's "
                                          "survey, by `status` and by `close`"), out
    sent = transport.chunk_line(lua.THROTTLE_LUA % {"on": "false", "mark": "MAME_MCP_THROTTLE#6"},
                                6)
    assert sent.encode() + b"\n" in CONSOLE, "the chunk is the captured one"
    assert ses.stdin.getvalue() == sent.replace("#6", "#1").encode() + b"\n"
    # Running: the tick lands the mark and the tool reads it back.
    ses.running = True
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)
    ses.answers[1] = ses.sentinel(1)          # the stopped machine's line, read first
    ses.answers[2] = ses.sentinel(2)
    ses.marks[2] = [_marks_of("MAME_MCP_THROTTLE#6")[0].replace("#6", "#2")]

    def two_frames() -> None:                  # one line per frame: the first line, then ours
        ses._tick()
        ses._tick()
    threading.Timer(0.1, two_frames).start()
    out = s.throttle(on=False, seconds=2.0)
    assert out["pending"] is False and out["frame"] == 341
    assert out["session"]["altered"] is False
    # And a mark that says the OPPOSITE of what was asked is a refusal, not a green.
    ses.answers[3] = ses.sentinel(3)
    ses.marks[3] = ["[luaengine] MAME_MCP_THROTTLE#3 throttled=true frame=408"]
    threading.Timer(0.1, ses._tick).start()
    assert refused("reports throttled=true", s.throttle(on=False, seconds=2.0))["code"] == (
        "readback_refused")


def test_a_throttle_whose_running_machine_stops_before_a_frame_is_pending_not_expired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A breakpoint that stops the machine before its next frame leaves the line in the pipe, as a
    stopped machine does"""
    ses = _channel(monkeypatch, tmp_path)
    ses.running = True
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: True)
    out = s.throttle(on=True, seconds=5.0)
    assert out["status"] == "ok" and out["pending"] is True, out
    assert [r["tag"] for r in mstate.STATE.throttles_pending] == [out["tag"]]



def test_a_throttle_that_landed_leaves_no_row_because_it_is_not_news(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE COMMON CASE COSTS NOTHING AND SAYS NOTHING."""
    ses = _channel(monkeypatch, tmp_path)
    out = s.throttle(on=True)
    assert out["pending"] is True and out["tag"] == "MAME_MCP_THROTTLE#1", out
    assert mstate.STATE.throttles_pending, "the record is what a later call reads"
    # The console reads the line on the next call's step, and the script logs its mark.
    ses.marks[1] = ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=101"]
    ses.answers = {1: ses.sentinel(1), 2: b"7\n" + ses.sentinel(2)}
    later = s.lua("print(7)", seconds=1.0)
    assert "throttles_not_applied" not in later["session"], later["session"]
    assert mstate.STATE.throttles_pending == [], "the record goes with the answer"



def test_status_lists_a_throttle_while_it_waits_and_drops_it_once_its_mark_is_logged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WAITING AND LANDED ARE BOTH VISIBLE, on one channel."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    first = s.status()
    assert "throttles_pending" not in first, first
    s.throttle(on=True)
    assert s.status().get("throttles_pending", []) == [{"tag": "MAME_MCP_THROTTLE#1", "on": True}]
    # THE MARK IS LOGGED WITH NO STOP SINCE.
    with open(ses.scratch / "error.log", "a") as log:
        log.write("[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=101\n")
    out = s.status()
    assert out.get("throttles_pending", []) == [], out
    assert "throttles_not_applied" not in out["session"], out["session"]
    assert mstate.STATE.throttles_pending == [], "the record goes with the answer"

def test_a_throttle_whose_mark_never_comes_is_reported_and_keeps_being_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE DEFECT ITSELF."""
    ses = _channel(monkeypatch, tmp_path)
    s.throttle(on=True)
    ses.answers = {1: ses.sentinel(1), 2: b"7\n" + ses.sentinel(2)}   # no marks[1]: no mark
    out = s.lua("print(7)", seconds=1.0)
    rows = out["session"]["throttles_not_applied"]
    assert [r["tag"] for r in rows] == ["MAME_MCP_THROTTLE#1"], out["session"]
    assert rows[0]["asked"] is True and rows[0]["machine_reports"]["available"] is False, rows
    assert "NEVER applied" in rows[0]["why"], rows
    # AND AGAIN on the next reply, which is the whole point of latching.
    ses.answers[3] = b"8\n" + ses.sentinel(3)
    again = s.lua("print(8)", seconds=1.0)
    assert again["session"]["throttles_not_applied"] == rows, again["session"]


def test_a_throttle_still_in_the_pipe_is_pending_and_not_yet_a_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE CONTROL, and without it the row would fire on every stopped throttle ever asked."""
    ses = _channel(monkeypatch, tmp_path)
    s.throttle(on=True)
    assert "throttles_not_applied" not in menvelope.session_block()
    # A survey with the line still unread: the console has answered nothing at or past it.
    running.survey(ses, ses.scratch)  # type: ignore[arg-type]
    assert mstate.STATE.throttles_pending, "still waiting, and still honestly pending"
    assert "throttles_not_applied" not in menvelope.session_block()
    # AND THE BOUNDARY ITSELF, which is where an off-by-one lives.
    mstate.STATE.lua_answered = mstate.STATE.throttles_pending[0]["seq"] - 1
    running.survey(ses, ses.scratch)  # type: ignore[arg-type]
    assert mstate.STATE.throttles_pending, "the call before it is not past it"
    mstate.STATE.lua_answered = mstate.STATE.throttles_pending[0]["seq"]
    running.survey(ses, ses.scratch)  # type: ignore[arg-type]
    assert menvelope.session_block()["throttles_not_applied"], "at its own number it is due"


def test_an_older_pending_switch_is_not_answered_by_a_younger_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`MAME_MCP_THROTTLE#1` IS A SUBSTRING OF `MAME_MCP_THROTTLE#10`, and a caller who asks for
    several switches while stopped reaches two digits without doing anything unusual."""
    _channel(monkeypatch, tmp_path)
    mstate.STATE.throttles_pending = [{"tag": "MAME_MCP_THROTTLE#1", "on": True, "seq": 1},
                                      {"tag": "MAME_MCP_THROTTLE#10", "on": True, "seq": 10}]
    mstate.STATE.lua_answered = 10
    mstate.settle_throttles(["[luaengine] MAME_MCP_THROTTLE#10 throttled=true frame=50"])
    assert mstate.STATE.throttles_pending == [], "both records were judged"
    rows = mstate.STATE.throttles_not_applied
    assert [r["tag"] for r in rows] == ["MAME_MCP_THROTTLE#1"], (
        "#10 landed and says nothing; #1 never ran and has to say so")
    assert rows[0]["machine_reports"]["available"] is False, "nothing from #10's line"


def test_close_judges_a_throttle_whose_mark_disagrees_before_the_scratch_goes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE LAST REPLY JUDGES TOO."""
    out = _closed_after_the_mark(monkeypatch, tmp_path,
                                 "[luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=101")
    rows = out["session"].get("throttles_not_applied")
    assert rows and [r["tag"] for r in rows] == ["MAME_MCP_THROTTLE#1"], out["session"]
    assert rows[0]["asked"] is True and rows[0]["machine_reports"] is False, rows


def test_close_judges_a_throttle_whose_line_only_its_own_drain_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE ORDER IS THE CONTRACT"""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    assert s.throttle(on=True)["pending"] is True
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=101"]}
    ses.answers[1] = ses.sentinel(1)
    out = s.close()
    assert out["console_drained"] == 1, out
    rows = out["session"].get("throttles_not_applied")
    assert rows and rows[0]["machine_reports"] is False, out["session"]


def test_close_says_nothing_of_a_throttle_that_landed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE CONTROL: a switch whose mark agrees is not news at `close` either."""
    out = _closed_after_the_mark(monkeypatch, tmp_path,
                                 "[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=101")
    assert "throttles_not_applied" not in out["session"], out["session"]


def test_a_machine_that_reports_the_opposite_switch_is_a_row_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE DISAGREEMENT THE RUNNING PATH REFUSES ON, reached by a caller who could not wait for
    it."""
    ses = _channel(monkeypatch, tmp_path)
    s.throttle(on=False)
    ses.marks[1] = ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=101"]
    ses.answers = {1: ses.sentinel(1), 2: b"7\n" + ses.sentinel(2)}
    out = s.lua("print(7)", seconds=1.0)
    row = out["session"]["throttles_not_applied"][0]
    assert row["asked"] is False and row["machine_reports"] is True, row
    assert "not the one this session asked for" in row["why"], row


def test_a_throttle_asked_while_stopped_settles_the_reader_after_its_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The stopped path returns `pending` at once, and the next call moves the machine"""
    ses = _channel(monkeypatch, tmp_path)
    slept = _settles(monkeypatch, ses)
    out = s.throttle(on=False)
    assert out["pending"] is True, out
    assert slept == [(transport.READER_SETTLE_S, len(ses.stdin.getvalue()), 0)], slept


def test_a_throttle_line_a_drain_step_hands_to_a_dying_reader_stops_the_drain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every line sent is settled against the log, not only a wrapper's"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: _captured(3, as_seq=2)}
    ses.marks = {2: [m.replace("#3", "#2") for m in _marks_of("MAME_MCP_INPUT#3")]}
    assert s.throttle(on=True)["pending"] is True
    ses.reader_eats = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and (out["lines_ahead"], out.get("drain_steps", 0)) == (1, 1), out
    assert out["session"]["console"]["lost"] == 1, out


@pytest.mark.parametrize("on,word", [(True, "true"), (False, "false")])
def test_the_throttle_script_that_reaches_the_pipe_carries_the_switch_that_was_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, on: bool, word: str
) -> None:
    """The reply says `on`"""
    ses = _channel(monkeypatch, tmp_path)
    out = s.throttle(on=on)
    assert out["on"] is on and out["pending"] is True, out
    assert out["applies"].startswith("when the console next reads a line") and (
        "confirmed_by" in out), out
    sent = transport.chunk_line(lua.THROTTLE_LUA % {"on": word, "mark": "MAME_MCP_THROTTLE#1"}, 1)
    assert ses.stdin.getvalue() == sent.encode() + b"\n"
    assert f"video.throttled = {word}\n" in lua.THROTTLE_LUA % {"on": word, "mark": "x"}


def test_the_throttle_body_judges_its_own_bound_with_both_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The body is callable without the tool in front of it (`perform` reaches it), so the bound is
    judged there too, and with the bound it was given rather than the default."""
    ses = _channel(monkeypatch, tmp_path)
    seen: list[tuple[Any, ...]] = []
    check = lua.check_throttle

    def spy(*args: Any, **kwargs: Any) -> None:
        seen.append(args)
        check(*args, **kwargs)

    monkeypatch.setattr(lua, "check_throttle", spy)
    lua.throttle(ses, ses.scratch, False, 0.5)  # type: ignore[arg-type]
    assert seen == [(False, 0.5)], seen
    with pytest.raises(mstate.Invalid, match="seconds=0 is not a bound"):
        lua.throttle(ses, ses.scratch, True, 0)  # type: ignore[arg-type]
    assert ses.stdin.getvalue().count(b"\n") == 1, "a refused bound sends nothing"


def test_a_running_throttle_on_is_read_back_as_true_and_the_opposite_names_its_marks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _running(monkeypatch, ses)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=77"]
    threading.Timer(0.1, ses._tick).start()
    out = s.throttle(on=True, seconds=2.0)
    assert out["status"] == "ok" and out["pending"] is False and out["frame"] == 77, out
    assert out["tag"] == "MAME_MCP_THROTTLE#1" and 0 <= out["waited_s"] < 2.0, out
    ses.answers[2] = ses.sentinel(2)
    ses.marks[2] = ["[luaengine] MAME_MCP_THROTTLE#2 throttled=false frame=78"]
    threading.Timer(0.1, ses._tick).start()
    out = refused("reports throttled=false after asking for true", s.throttle(on=True, seconds=2.0))
    assert out["code"] == "readback_refused" and out["tagged_lines"] == ses.marks[2], out


def test_a_throttle_wait_names_its_tag_when_it_expires_and_when_mame_goes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _running(monkeypatch, ses)
    out = refused("still pending", s.throttle(on=True, seconds=0.2))
    assert out["code"] == "wait_expired" and out["tag"] == "MAME_MCP_THROTTLE#1", out
    ses.quit_asked = True                      # the process double now polls as exited, code 0
    out = refused("while this call waited for its own throttle tag in error.log",
                  s.throttle(on=True, seconds=0.2))
    assert out["code"] == "session_broken" and out["tag"] == "MAME_MCP_THROTTLE#2", out
    assert out["exit_code"] == 0, out


def test_a_throttle_wait_reports_its_progress_to_the_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _running(monkeypatch, ses)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    said: list[str] = []
    with pytest.raises(mstate.Invalid):
        lua.throttle(ses, ses.scratch, True, 0.1,  # type: ignore[arg-type]
                     lambda _done, _total, message: said.append(message))
    assert said and said[0].startswith("throttle: waiting for the tag, 0s"), said
