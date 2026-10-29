"""The Lua channel: what a session counts: reader deaths, reruns and lines eaten."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from lua_support import (  # noqa: E402
    AVI_HEAD,
    PROMPT,
    VOLUME,
    _captured,
    _channel,
    _marks_of,
    _scratch_logging,
    _volume_line,
    _whole,
)
from session_doubles import blank_session, refused  # noqa: E402

from scry_mame import (
    lua,  # noqa: E402
    transport,  # noqa: E402
)
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


@pytest.mark.parametrize("tool,captured,event", [
    ("record", "MAME_MCP_RECORD#5", "begin"),
    ("input", "MAME_MCP_INPUT#3", "set"),
])
def test_a_wrapper_whose_own_mark_appears_twice_refuses_as_a_console_rerun(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool: str, captured: str, event: str,
) -> None:
    """The sentinel check skips the call's own number, so the wrapper counts its own marks."""
    ses = _channel(monkeypatch, tmp_path)
    seq = captured.rsplit("#", 1)[1]
    ses.answers[1] = _captured(int(seq))
    marks = [m.replace(f"#{seq}", "#1") for m in _marks_of(captured)]
    twice = next(m for m in marks if f"#1 {event}" in m)
    ses.marks[1] = [*marks[:1], twice, *marks[1:]]
    ses.files[1] = (ses.scratch / "snap" / "record-1.avi", AVI_HEAD)
    tag = captured.rsplit("#", 1)[0] + "#1"
    out = (s.record(frames=30) if tool == "record"
           else s.input(port=":P1", field="Coin 1", value=1, frames=4))
    assert out["status"] == "INVALID" and out["code"] == "console_rerun", out
    assert out["console_reruns"] == 1 and f"{tag} {event}" in out["message"], out
    assert out["session"]["console"]["reruns"] == 1, out["session"]


def test_a_console_rerun_refusal_keeps_the_earlier_chunks_the_console_ran_again() -> None:
    """A refusal on the wrapper's marks also carries the reruns the sentinel check found."""
    answer = transport.Answer("", True, "", reruns=["MAME_MCP_LUA_END#1"])
    tag = "MAME_MCP_RECORD#2"
    seen = [f"[luaengine] {tag} begin frame=1", f"[luaengine] {tag} begin frame=1"]
    with pytest.raises(mstate.Invalid) as refused_:
        lua.refuse_a_rerun(seen, tag, answer, 0)
    reply = refused_.value.reply()
    assert reply["console_reruns"] == 2 and f"{tag} begin" in reply["message"], reply


def test_a_dead_reader_and_the_chunk_the_console_ran_again_are_said_in_the_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MAME's console thread is unsafe by its own admission (`luaengine.cpp`)."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    sig = b"%d\n"
    ses.answers = {1: sig % 11 + ses.sentinel(1), 2: sig % 22 + ses.sentinel(2),
                   3: b"7\n" + ses.sentinel(3)}
    out = s.lua("print(1)", seconds=1.0, read_only=True)
    assert out["thread_errors"] == 0 and out["console_reruns"] == 0 and "note" not in out, out
    ses.reader_dies = 1
    out = s.lua("print(1)", seconds=1.0, read_only=True)
    assert out["status"] == "ok" and out["output"] == "22\n", out
    assert out["thread_errors"] == 1 and out["console_reruns"] == 1, out
    assert out.get("reader_steps", 0) == 1 and "AGAIN" in out["note"], out
    # The raw form says the same, where it matters most: its script may have written.
    ses.reader_dies = 1
    out = s.lua("print(7)", seconds=1.0)
    assert out["status"] == "ok" and out["output"] == "7\n", out
    assert out["console_reruns"] == 1 and out["thread_errors"] == 1, out
    # And a wrapper's run, which evaluates by frames: the rerun is on its reply too.
    ses.answers[4] = ses.sentinel(4)
    ses.marks[4] = [m.replace("#3", "#4") for m in _marks_of("MAME_MCP_INPUT#3")]
    ses.reader_dies = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and out["console_reruns"] == 1, out
    assert out["thread_errors"] == 1 and out.get("resent", 0) == 0, out
    # A run cut short keeps BOTH notes: the tool's own and the console's.
    ses.answers[5] = ses.sentinel(5)
    ses.marks[5] = [_marks_of("MAME_MCP_INPUT#3 set")[0].replace("#3", "#5")]
    ses.reader_dies = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["released"] is False and "HELD" in out["note"], out
    assert out["console_reruns"] == 1 and "AGAIN" in out["note"]
    # The raw form with no output: the two notes do not collide.
    ses.answers[6] = ses.sentinel(6)
    ses.reader_dies = 1
    out = s.lua("return 1", seconds=1.0)
    assert out["status"] == "ok" and "no output" in out["note"], out
    assert out["console_reruns"] == 1 and "AGAIN" in out["note"]


def test_a_line_legitimately_ahead_is_not_a_rerun_and_a_rerun_after_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `throttle` line read by the next call's step prints its sentinel once, in that window."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: ses.sentinel(1), 2: b"m68k-dual\n" + ses.sentinel(2),
                   3: b"1\n" + ses.sentinel(3)}
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=100"]}
    s.throttle(on=True)
    out = s.lua("print(emu.romname())", seconds=0.5)
    assert out["lines_ahead"] == 1 and out["console_reruns"] == 0 and out["thread_errors"] == 0
    ses.reader_dies = 1
    out = s.lua("print(1)", seconds=1.0)
    assert out["console_reruns"] == 1 and out["thread_errors"] == 1, out
    # A script printing the sentinel's text for a number never sent is its own business.
    ses.answers[4] = b"MAME_MCP_LUA_END#99\tfake\n" + ses.sentinel(4)
    out = s.lua('print("MAME_MCP_LUA_END#99\\tfake")', seconds=1.0)
    assert out["console_reruns"] == 0, out


def test_a_pending_line_a_later_reader_dies_holding_is_counted_lost_and_costs_no_drain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A line no death could be pinned on stays ahead in the pipe until the log says otherwise."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    ses.reader_dead = True
    first = s.input(port=":P1", field="Coin 1", frames=4)
    assert first["code"] == "reader_died" and first["pending"] is True, first
    assert first.get("drain_steps", 0) == 0, first
    ses.reader_dead, ses.reader_eats = False, 1
    ses.answers = {2: _captured(3, as_seq=2)}
    ses.marks = {2: [m.replace("#3", "#2") for m in _marks_of("MAME_MCP_INPUT#3")]}
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and out["released"] is True, out
    assert (out["lines_ahead"], out.get("drain_steps", 0)) == (1, 1), out
    assert out["session"]["console"]["lost"] == 1 and mstate.STATE.lua_lost == 1, out
    transport.count_unread(ses.scratch)
    assert mstate.STATE.console_lines_lost == 1, "counted once, whoever reads the log again"


def test_a_lua_refused_for_somebody_elses_backlog_is_not_counted_as_a_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A call that never reached the console is not counted."""
    _channel(monkeypatch, tmp_path)
    for _ in range(transport.PIPE_STEPS_MAX + 1):          # a pipe nobody here filled
        transport.send("print(0)")
    refused_write = refused("still ahead", s.lua("print(1)"))
    assert refused_write["session"]["altered"] is False, refused_write["session"]
    assert _whole()["altering_writes"] == 0, refused_write["session"]
    refused_read = refused("still ahead", s.lua("print(1)", read_only=True))
    assert "read_only_claims" not in refused_read["session"], refused_read["session"]



def test_a_clean_session_reports_three_zeros_and_not_an_absent_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The control: a clean session reports no console object."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: b"7\n" + ses.sentinel(1)}
    out = s.lua("print(7)", seconds=1.0)
    assert out["status"] == "ok", out
    assert "console" not in out["session"], "three zeros are no alarm"
    assert _whole()["console"] == {"thread_errors": 0, "reruns": 0, "lost": 0}, out


def test_a_reader_death_is_held_against_the_session_and_still_there_two_replies_later(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The line was taken and never evaluated, so the session carries both counts."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    ses.reader_eats = 1
    out = s.lua("print(7)", seconds=1.0)
    assert out["status"] == "ok" and out.get("resent", 0) == 1, out
    assert out["session"]["console"] == {"thread_errors": 1, "reruns": 0, "lost": 1}, out
    ses.answers[3] = b"8\n" + ses.sentinel(3)
    later = s.lua("print(8)", seconds=1.0)
    assert later["thread_errors"] == 0, "the per-call field is about THIS line"
    assert later["session"]["console"] == {"thread_errors": 1, "reruns": 0, "lost": 1}, later


def test_a_chunk_the_console_ran_again_is_counted_for_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A rerun is counted apart from a harmless restart."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: b"7\n" + ses.sentinel(1), 2: b"8\n" + ses.sentinel(2)}
    out = s.lua("print(7)", seconds=1.0)
    assert _whole()["console"]["reruns"] == 0, out
    ses.reader_dies = 1
    out = s.lua("print(8)", seconds=1.0)
    assert out["console_reruns"] == 1, out
    assert out["session"]["console"] == {"thread_errors": 1, "reruns": 1, "lost": 0}, out
    # The near miss: a look-alike must not fire the counter.
    ses.answers[3] = b"MAME_MCP_LUA_END#99\tfake\n" + ses.sentinel(3)
    out = s.lua('print("MAME_MCP_LUA_END#99\\tfake")', seconds=1.0)
    assert out["console_reruns"] == 0, out
    assert out["session"]["console"]["reruns"] == 1, "a look-alike moved the session count"


def test_two_separate_incidents_add_up_rather_than_replacing_each_other(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two incidents tell an accumulator from an assignment, which one incident cannot."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    ses.reader_eats = 1
    first = s.lua("print(7)", seconds=1.0)
    assert first["session"]["console"] == {"thread_errors": 1, "reruns": 0, "lost": 1}, first
    ses.answers[4] = b"8\n" + ses.sentinel(4)
    ses.reader_eats = 1
    second = s.lua("print(8)", seconds=1.0)
    assert second["thread_errors"] == 1, "the per-call field is still about THIS line"
    assert second["session"]["console"] == {"thread_errors": 2, "reruns": 0, "lost": 2}, second


def test_a_second_look_at_one_window_does_not_count_its_deaths_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A double count reads as a channel in worse trouble than it is."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    ses.reader_eats = 1
    ses.sluggish = 2
    out = s.lua("print(7)", seconds=2.0)
    assert out["status"] == "ok", out
    assert out["session"]["console"]["thread_errors"] == 1, out
    assert out["session"]["console"]["lost"] == 1, out


def test_a_reader_death_that_precedes_the_echo_belongs_to_an_earlier_line() -> None:
    """The control: a death before the echo is an earlier line's."""
    line = transport.chunk_line('print("x")', 11)
    stale = b"[LUA ERROR] in thread: an earlier line killed it\n" + (line + "\n").encode()
    assert transport.eaten(stale, line) is False
    # The same bytes with the death behind the echo are this line's reader dying.
    assert transport.eaten((line + "\n").encode() + stale[:47], line) is True



def test_a_console_that_reports_its_own_error_is_a_line_that_was_never_evaluated() -> None:
    """The console's own error framing."""
    line = transport.chunk_line('print("x")', 4)
    # The prompt is part of what the console emits.
    raw = ((line + "\n").encode()
           + b'error: \t[string "..."]:2: something raised at the top level\n' + PROMPT)
    assert transport.eaten(raw, line) is True


def test_a_script_that_merely_prints_the_word_error_is_not_a_lost_line() -> None:
    """The control: a guest printing the word error is not a lost line."""
    line = transport.chunk_line('print("x")', 4)
    raw = ((line + "\n").encode()
           + b"error: the guest printed this itself\n"
           + f"{mstate.LUA_SENTINEL}#4\ttrue\tnil\n".encode())
    assert transport.eaten(raw, line) is False


def test_the_console_error_has_to_follow_the_echo_and_not_precede_it() -> None:
    """An earlier line's death is not this line's."""
    line = transport.chunk_line('print("x")', 4)
    raw = (b'error: \t[string "..."]:2: a previous line raised\n' + (line + "\n").encode())
    assert transport.eaten(raw, line) is False


def test_a_console_error_with_no_prompt_behind_it_is_a_script_that_hung_not_a_lost_line() -> None:
    """The prompt separates a console failure from a script that printed the framing and hung."""
    line = transport.chunk_line('print("x")', 9)
    hung = (line + "\n").encode() + b'error: \t[string "y"]:1: the guest printed this\n'
    assert transport.eaten(hung, line) is False
    # With the prompt behind them the same bytes are the console having finished.
    finished = hung + PROMPT
    assert transport.eaten(finished, line) is True


def test_passed_over_answers_no_for_every_captured_line_before_its_own_sentinel() -> None:
    """The lag shape on captured traffic."""
    seqs = sorted({int(n) for n in re.findall(
        re.escape(PROMPT) + rb'[^\n]*MAME_MCP_LUA_END#(\d+)"[^\n]*\n', VOLUME)})
    judged = 0
    for n in seqs:
        line = _volume_line(n)
        echo = VOLUME.find((line + "\n").encode())
        end = VOLUME.find(f"{mstate.LUA_SENTINEL}#{n}\t".encode(), echo)
        if echo < 0 or end < 0 or transport.THREAD_ERROR in VOLUME[echo:end]:
            continue
        assert transport.passed_over(VOLUME[:end], line) is False, n
        cut = VOLUME[:end] + VOLUME[VOLUME.index(b"\n", end) + 1:]
        assert transport.passed_over(cut, line) is True, n
        judged += 1
    assert judged >= 50, f"only {judged} captured lines judged"


def test_passed_over_takes_no_prompt_before_the_echo_and_no_error_framing_without_one() -> None:
    line = "the line"
    assert transport.passed_over(PROMPT + b"the line\n", line) is False
    assert transport.passed_over(b"the line\n" + PROMPT, line) is True
    assert transport.passed_over(PROMPT, line) is False, "no echo, not taken"
    # A script that prints the console's error framing and hangs is still running.
    assert transport.passed_over(b'the line\nerror: \t[string "x"]:1: y\n', line) is False
    assert transport.passed_over(b"the line\n" + transport.THREAD_ERROR + b" died\n", line) is True


def test_eaten_holds_its_ordering_against_a_console_log_with_real_volume_in_it() -> None:
    """The volume axis, against a captured session rather than an authored buffer."""
    assert VOLUME.count(transport.THREAD_ERROR) == 1, "the capture's single death is what places it"
    death = VOLUME.find(transport.THREAD_ERROR)
    seqs = sorted({int(n) for n in re.findall(
        re.escape(PROMPT) + rb'[^\n]*MAME_MCP_LUA_END#(\d+)"[^\n]*\n', VOLUME)})
    before = [n for n in seqs if VOLUME.find(_volume_line(n).encode()) < death]
    after = [n for n in seqs if VOLUME.find(_volume_line(n).encode()) > death]
    assert len(before) >= 5 and len(after) >= 50, (len(before), len(after))

    # (b) An echo with a death after it: taken and never evaluated.
    taken = _volume_line(before[-1])
    assert (taken + "\n").encode() in VOLUME
    assert transport.eaten(VOLUME, taken) is True

    # (c) A death before the echo is somebody else's.
    survived = _volume_line(after[0])
    assert (survived + "\n").encode() in VOLUME
    assert transport.eaten(VOLUME, survived) is False

    # (a) Still somebody else's with seventy calls in between.
    distant = _volume_line(after[-1])
    assert (distant + "\n").encode() in VOLUME
    assert transport.eaten(VOLUME, distant) is False

    two_line = b"[LUA ERROR] in thread: an earlier line killed it\n" + (survived + "\n").encode()
    assert transport.eaten(two_line, survived) == transport.eaten(VOLUME, survived)


def test_a_rerun_is_counted_per_printing_and_a_number_never_sent_is_not_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chunk not yet answered that prints twice in one window ran again once."""
    blank_session(monkeypatch)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 5)
    monkeypatch.setattr(mstate.STATE, "lua_answered", 2)
    def printed(*seqs: int) -> bytes:
        return b"".join(b"MAME_MCP_LUA_END#%d\ttrue\tnil\n" % n for n in seqs)
    assert transport.reruns_in(printed(3, 3), 5) == ["MAME_MCP_LUA_END#3"]
    assert transport.reruns_in(printed(3, 3, 3), 5) == ["MAME_MCP_LUA_END#3"] * 2
    assert transport.reruns_in(printed(2, 2), 5) == ["MAME_MCP_LUA_END#2"] * 2
    assert transport.reruns_in(printed(9, 9, 5, 2), 5) == ["MAME_MCP_LUA_END#2"]


def test_the_deaths_are_counted_up_to_the_size_read_and_no_further(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The count is by position."""
    death = transport.THREAD_ERROR + b" attempt to index a nil value\n"
    scratch = _scratch_logging(tmp_path, monkeypatch, death + death)
    monkeypatch.setattr(transport, "stdout_mark", lambda _scratch: len(death))
    transport.count_deaths(scratch)
    assert mstate.STATE.console_thread_errors == 1
    assert mstate.STATE.console_counted == len(death)


def test_a_wrapper_whose_line_died_twice_says_twice_and_counts_both_deaths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The wrapper's own refusal, told apart from a reader that never took the line."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    ses.reader_eats = 2
    out = refused("twice", s.input(port=":P1", field="Coin 1", frames=4))
    assert out["code"] == "reader_died" and out["pending"] is False, out
    assert out.get("resent", 0) == 1, out
    assert out["thread_errors"] == 2 and out["console_reruns"] == 0, out
    assert out["session"]["console"]["lost"] == 2, out



def test_a_wrappers_rerun_refusal_carries_its_marks_its_fields_and_what_was_resent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blank_session(monkeypatch)
    monkeypatch.setattr(mstate.STATE, "console_reruns_seen", 3)
    seen = ["[luaengine] MAME_MCP_RECORD#4 begin frame=1"] * 3
    answer = transport.Answer(text="", ok=True, error="", thread_errors=0, reruns=[])
    with pytest.raises(mstate.Invalid) as caught:
        lua.refuse_a_rerun(seen, "MAME_MCP_RECORD#4", answer, 1, path="/tmp/x.avi")
    fields = caught.value.fields
    assert mstate.STATE.console_reruns_seen == 3 + 2, "the repeats ADD to what was seen before"
    assert fields["tagged_lines"] == seen and fields["path"] == "/tmp/x.avi", fields
    assert fields.get("resent", 0) == 1 and "sent again (1 time)" in fields["note"], fields
    assert fields["console_reruns"] == 2, fields


def test_the_deaths_are_counted_from_where_the_last_count_stopped_to_the_size_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The read covers the bytes between the two positions."""
    death = transport.THREAD_ERROR + b" attempt to index a nil value\n"
    scratch = _scratch_logging(tmp_path, monkeypatch, death * 3)
    monkeypatch.setattr(mstate.STATE, "console_counted", len(death))
    monkeypatch.setattr(transport, "stdout_mark", lambda _scratch: 2 * len(death))
    transport.count_deaths(scratch)
    assert mstate.STATE.console_thread_errors == 1
    assert mstate.STATE.console_counted == 2 * len(death)
