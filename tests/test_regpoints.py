"""Registerpoints: MAME's `rpset`, a stop when an expression over the registers comes true,
wherever that happens.

A registerpoint cuts a run like a breakpoint does and leaves the same kind of trace: no stop
packet under a run the console started, only the console's `Stopped at registerpoint <n>`. It
also fires at EVERY instruction while its condition holds, so a run by frames started with it
still true stops one instruction on with the frame counter where it was, which the counter
alone reads as a machine that emulated nothing.

Every console answer here is a capture (`fixtures/console/PROVENANCE.txt`), never authored;
the one exception says so where it stands, an answer that is no list at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scry_core import regpoint
from server_support import _install, _RegisterSession, _running, _RunningSession  # noqa: E402
from session_doubles import (  # noqa: E402
    IDENTITY_KEYS,
    bp_records,
    captured,
    refs,
    refused,
    rplist_answer,
    use_table,
)

from scry_mame import (
    advance,  # noqa: E402
    arming,  # noqa: E402
    regpoints,  # noqa: E402
    sequence,  # noqa: E402
)
from scry_mame import clear as mclear  # noqa: E402
from scry_mame import console as mconsole  # noqa: E402
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import gdb_session as gs  # noqa: E402
from scry_mame import lists as mlists  # noqa: E402
from scry_mame import rearm as rearming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

# ------------------------------------------------------------------ the list, as captured


def test_rplist_is_read_as_the_console_prints_it() -> None:
    assert regpoints.parse_rplist(captured("rplist-none.txt")) == []
    assert regpoints.parse_rplist(captured("rplist-one.txt")) == [
        {"index": 1, "cpu": ":maincpu", "enabled": True, "entry": "1 if d1==7fff",
         "condition": "d1==7fff", "action": None}]
    newest_first = regpoints.parse_rplist(captured("rplist-two-rows.txt"))
    assert [(r["index"], r["condition"]) for r in newest_first] == [(2, "d1=="), (1, "d1==7fff")]
    disabled = regpoints.parse_rplist(captured("rplist-disabled.txt"))
    assert disabled[0]["enabled"] is False and disabled[0]["entry"] == "D 1 if d1==7fff"
    spaced = regpoints.parse_rplist(captured("rplist-cond-with-spaces.txt"))
    assert spaced[0]["condition"] == "d1==7fff && d0!=0x12345678", spaced[0]
    sixteen = regpoints.parse_rplist(captured("rplist-sixteen.txt"))
    assert [r["index"] for r in sixteen] == list(range(16, 0, -1)), "`10` and `F` are hex"
    assert regpoints.parse_rplist(captured("rplist-action.txt")) == [
        {"index": 1, "cpu": ":maincpu", "enabled": True,
         "entry": "1 if temp2==0x1234 do temp3++ ; g",
         "condition": "temp2==0x1234", "action": "temp3++ ; g"}], "the action after `do`"


def test_the_double_lists_what_the_captures_list() -> None:
    """The fidelity of `rplist_answer`: it rebuilds the captured answers byte for byte."""
    assert rplist_answer([(1, "d1==7fff", True)]) == captured("rplist-one.txt")
    assert rplist_answer([(1, "d1==7fff", True), (2, "d1==", True)]) == captured(
        "rplist-two-rows.txt")
    assert rplist_answer([(1, "d1==7fff", False)]) == captured("rplist-disabled.txt")


@pytest.mark.parametrize("answer", [captured("rpset-unknown-command.txt"), "",
                                    "Device ':maincpu' registerpoints:\n    1 @ 000400\n"])
def test_an_answer_that_is_no_list_is_refused_and_quoted(answer: str) -> None:
    with pytest.raises(mstate.Invalid) as refusal:
        regpoints.parse_rplist(answer)
    assert refusal.value.code == "unexpected_answer"


# ------------------------------------------------- a stop one typed through `debug` makes

# The console's stop line, cut out of the capture it was logged in.
_STOP_LINE = next(
    ln for ln in captured("debuglog-foreign-rp-resume.txt").splitlines(keepends=True)
    if ln.startswith("Stopped at registerpoint 1"))
_FOREIGN_CAUSE = ("registerpoint 1 (if d1==7fff), typed through `debug`: `debug(\"rpclear 0x1\")` "
                "removes it")


def _typed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, frame: int = 10,
           stop_after: int | None = 3) -> _RegisterSession:
    """A machine with `rpset {d1==7fff}` typed through `debug`: the row is in the debugger's
    list and in nothing this server holds."""
    reg = _RegisterSession(bits=32, frame=frame, stop_after=stop_after)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", reg)     # the envelope reads `running` off it
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    reg.rplist_rows = [(1, "d1==7fff", True)]
    return reg


def _log_on(reg: _RegisterSession, tmp_path: Path, starts: str, chunk: str) -> None:
    """Every console command that starts with `starts` appends `chunk` to the debugger's log,
    as the run it starts does."""
    real = reg.monitor

    def console(command: str, timeout: float = 10.0) -> str:
        if command.startswith(starts):
            with open(tmp_path / "debug.log", "a") as fh:
                fh.write(chunk)
        return real(command, timeout)

    reg.monitor = console  # type: ignore[method-assign]


def test_a_resume_stopped_by_a_registerpoint_typed_through_debug_names_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _typed(monkeypatch, tmp_path)
    real_go = reg.go

    def go_to_the_value() -> None:
        (tmp_path / "debug.log").write_text(captured("debuglog-foreign-rp-resume.txt"))
        real_go()

    reg.go = go_to_the_value  # type: ignore[method-assign]
    out = s.resume(seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cause"] == _FOREIGN_CAUSE, out["cause"]
    assert "regpoint_hit" not in out, "a row this server did not place is no hit of its own"


def test_a_frame_run_cut_by_a_registerpoint_is_another_stop_and_never_no_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The captured run: the condition already holds, so the first `gvblank` stops one
    instruction on and the frame counter has not moved. That is a STOP somebody asked for, and
    the machine is stopped: the session must not be handed back marked running."""
    reg = _typed(monkeypatch, tmp_path, frame=10, stop_after=1)
    reg.frozen = True
    first_stop = captured("debuglog-foreign-rp-frames.txt").split("Data dumped", 1)[0]
    assert "Stopped at registerpoint 1" in first_stop
    _log_on(reg, tmp_path, "gvblank", first_stop)
    out = s.run_for(frames=2, seconds=2.0)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == _FOREIGN_CAUSE, out["cause"]
    assert out["frame_before"] == 10 and out["frame_after"] == 10, out
    assert reg.commands.count("gvblank") == 1, "nothing is sent after the stop"
    assert out["session"]["running"] is False, "a stopped machine handed back as running"


def test_a_registerpoint_that_lands_with_the_tick_still_ends_a_frame_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The counter MOVED and the pc is on no row of this server's, so nothing but the console's
    line says the landing is a stop: the log is looked at after every landing for it."""
    reg = _typed(monkeypatch, tmp_path, frame=10, stop_after=1)
    _log_on(reg, tmp_path, "gvblank", captured("debuglog-foreign-rp-resume.txt"))
    out = s.run_for(frames=5, seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cause"] == _FOREIGN_CAUSE, out
    assert out["frame_after"] == 11 and reg.commands.count("gvblank") == 1, out


def test_a_run_by_milliseconds_cut_by_a_registerpoint_is_another_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _typed(monkeypatch, tmp_path, frame=10)
    reg.frame_answers = ["a"] * 5        # the counter never moved: it stopped an instruction on
    _log_on(reg, tmp_path, "gtime", captured("debuglog-foreign-rp-ms.txt"))
    out = s.run_for(milliseconds=200, seconds=2.0)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == _FOREIGN_CAUSE, out["cause"]


def test_the_index_of_a_registerpoint_stop_is_read_in_hex(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The sixteenth registerpoint of a session stops as `registerpoint 10` and is listed as
    `10`: read in decimal it would be looked for under a number no row holds."""
    reg = _typed(monkeypatch, tmp_path)
    reg.rplist_rows = [(i, f"d1=={0x100000 + i - 1:x}", True) for i in range(1, 16)]
    reg.rplist_rows.append((16, "1", True))
    assert captured("rplist-sixteen.txt") == reg.monitor("rplist"), "the double is the capture"
    real_go = reg.go

    def go_to_the_sixteenth() -> None:
        (tmp_path / "debug.log").write_text(captured("debuglog-rp-sixteenth.txt"))
        real_go()

    reg.go = go_to_the_sixteenth  # type: ignore[method-assign]
    out = s.resume(seconds=2.0)
    assert out["cause"] == ("registerpoint 10 (if 1), typed through `debug`: "
                          "`debug(\"rpclear 0x10\")` removes it"), out["cause"]


def test_a_registerpoint_stop_whose_list_cannot_be_read_spells_its_index_as_the_console_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The list the console will not answer cannot say whose the row is, and the stop is
    still named: with the index spelled as `rplist` prints it, so the `rpclear` that removes
    the row can be typed from it."""
    reg = _typed(monkeypatch, tmp_path)
    real_go = reg.go

    def go_to_the_sixteenth() -> None:
        (tmp_path / "debug.log").write_text(captured("debuglog-rp-sixteenth.txt"))
        real_go()

    def unreadable(ses: object) -> list[dict[str, object]]:
        raise gs.SessionError("the console did not answer `rplist`")

    reg.go = go_to_the_sixteenth  # type: ignore[method-assign]
    monkeypatch.setattr(regpoints, "rp_held", unreadable)
    out = s.resume(seconds=2.0)
    assert out["cause"] == ("registerpoint 10; the debugger's list could not be read to say "
                          "whose: the console did not answer `rplist`"), out["cause"]


def test_a_registerpoint_line_whose_row_is_gone_names_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE CONTROL: a line whose row the debugger no longer lists is nobody's stop now, as a
    breakpoint's is, and the stop keeps the name it would have had."""
    reg = _typed(monkeypatch, tmp_path)
    reg.rplist_rows = []
    real_go = reg.go

    def go_to_the_value() -> None:
        (tmp_path / "debug.log").write_text(captured("debuglog-foreign-rp-resume.txt"))
        real_go()

    reg.go = go_to_the_value  # type: ignore[method-assign]
    out = s.resume(seconds=2.0)
    assert out["cause"] == "stopped at no breakpoint this server armed", out["cause"]


def test_a_stop_on_a_row_this_server_armed_keeps_its_name_beside_a_registerpoint_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _typed(monkeypatch, tmp_path, frame=10, stop_after=1)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "f2034", 0xF2034)))
    _log_on(reg, tmp_path, "gvblank", _STOP_LINE)
    out = s.run_for(frames=2, seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cause"] == "breakpoint at 0xf2034", out["cause"]


def test_a_registerpoint_stop_whose_list_the_console_will_not_answer_is_still_a_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _typed(monkeypatch, tmp_path, frame=10, stop_after=1)
    reg.frozen = True
    _log_on(reg, tmp_path, "gvblank", _STOP_LINE)
    landed = reg.monitor

    def mute_rplist(command: str, timeout: float = 10.0) -> str:
        # AUTHORED ON PURPOSE: the case is an answer that is no list, whatever it says.
        return "garbage\n" if command == "rplist" else landed(command, timeout)

    reg.monitor = mute_rplist  # type: ignore[method-assign]
    out = s.run_for(frames=2, seconds=2.0)
    assert out["verdict"] == "OTHER_STOP", out
    assert out["cause"].startswith("registerpoint 1; the debugger's list could not be read to "
                                 "say whose"), out["cause"]


# ------------------------------------------------------------------ the typed family
#
# `regpoint_add` / `declaration_list(kind="regpoint")` / `declaration_clear(kind="regpoint")`: a
# registerpoint declared, listed,
# persisted and re-armed the way a breakpoint is. What differs is what has no meaning without
# an address (`addr`, `role`, `aliased`, `stale`) and the one check MAME does not make for
# itself: it ARMS a condition its own evaluator refuses, so the condition is evaluated once
# before anything is stored.

_NOTE = regpoint.STILL_ARMED
_MAIN = {"spaces": [{"cpu": ":maincpu", "space": "program", "address_mask": "0x00ffffff"},
                    {"cpu": ":subcpu", "space": "program"}]}


def _two_cpus(monkeypatch: pytest.MonkeyPatch) -> None:
    """The board's inventory as `start` reads it: two 68000s, the main one visible."""
    monkeypatch.setattr(mstate.STATE, "machine_map", _MAIN)


def _sent(ses: _RunningSession) -> list[str]:
    """The registerpoint commands the console received, in order."""
    return [c for c in ses.commands if c.startswith(("rp", "print {"))]


def test_regpoint_add_evaluates_stores_arms_and_reads_the_list_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = s.regpoint_add(condition=" d1==7fff ")
    assert out["status"] == "ok", out
    assert {k: out.get(k, False) for k in ("ref", "by", "condition", "stored", "already_stored",
                                "while_running", "armed", "state", "entry", "index",
                                "cpu")} == {
        "ref": "d1==7fff", "by": "expr", "condition": "d1==7fff", "stored": True,
        "already_stored": False, "while_running": False, "armed": True, "state": "armed",
        "entry": "1 if d1==7fff", "index": 1, "cpu": ":maincpu"}
    assert out["summary"] == "regpoint_add d1==7fff: armed, index 1"
    assert _sent(ses) == ["print {d1==7fff}", "rplist", "rpset {d1==7fff}", "rplist"]
    assert out["session"]["altered"] is False and s.status()["session"]["altering_writes"] == 0, (
        "a registerpoint is the debugger's bookkeeping, as a breakpoint is")
    assert s.status()["in_debugger"]["regpoints"] == [{"ref": "d1==7fff", "cpu": ":maincpu"}]


def test_a_symbol_is_stored_by_name_and_sent_by_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC})
    out = s.regpoint_add(condition="d0==DemoLen")
    assert out["ref"] == "d0==DemoLen" and out["condition"] == "d0==0x2031fc", out
    assert _sent(ses) == ["print {d0==0x2031fc}", "rplist", "rpset {d0==0x2031fc}", "rplist"]
    listed = s.declaration_list("regpoint")["regpoints"]
    assert [(r["ref"], r["condition"]) for r in listed] == [("d0==DemoLen", "d0==0x2031fc")]


def test_a_symbol_spelled_like_a_register_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"D0": 0x1000})
    out = refused("both a symbol", s.regpoint_add(condition="d0==1"))
    assert out["code"] == "ambiguous_ref" and _sent(ses) == []


@pytest.mark.parametrize("condition, clause", [
    ("", "empty"), ("   ", "empty"),
    ("d1==7fff,{g}", "comma"), ("d1==1\nd0==2", "comma or a newline"),
    ("d1=5", "never assigns"), ("d1++", "never assigns"), ("{d1==5}", "never assigns"),
])
def test_an_action_an_assignment_or_nothing_is_refused_before_the_console_hears_of_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, condition: str, clause: str,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = refused(clause, s.regpoint_add(condition=condition))
    assert out["code"] == "bad_argument" and _sent(ses) == []
    assert s.declaration_list("regpoint")["regpoints"] == []


def test_the_same_refusal_needs_no_machine() -> None:
    assert refused("empty", s.regpoint_add(condition=""))["code"] == "bad_argument"


@pytest.mark.parametrize("condition, capture, words", [
    ("d1==", "print-braces-malformed.txt", "stack underflow"),
    ("eax==5", "print-braces-unknown-symbol.txt", "unknown symbol"),
])
def test_a_condition_the_debugger_cannot_evaluate_is_refused_in_its_own_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, condition: str, capture: str, words: str,
) -> None:
    """MAME ARMS `rpset {d1==}` (captured) and refuses `print {d1==}`: the evaluation is the
    check, and what it refuses is never sent and never stored."""
    ses = _running(monkeypatch, tmp_path)
    ses.rp_print_errors = {condition: captured(capture)}
    out = refused("the debugger did not evaluate", s.regpoint_add(condition=condition))
    assert out["code"] == "bad_argument" and words in out["message"], out["message"]
    assert _sent(ses) == [f"print {{{condition}}}"], "nothing was armed"
    assert s.declaration_list("regpoint")["regpoints"] == [], "and nothing was stored"


def test_a_condition_too_long_for_one_packet_is_refused_before_anything_is_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.packet_size = 64
    long = "d1==0x" + "0" * 80 + "1"
    out = s.regpoint_add(condition=long)
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "limit_chars" in out and _sent(ses) == []
    assert s.declaration_list("regpoint")["regpoints"] == []
    assert s.regpoint_add(condition="d1==1")["status"] == "ok", "the control: a short one fits"


def test_a_debugger_with_no_registerpoints_is_no_channel_and_holds_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor

    def older_console(command: str, timeout: float = 10.0) -> str:
        if command.startswith("rpset "):
            ses.commands.append(command)
            return captured("rpset-unknown-command.txt")
        return real(command, timeout)

    ses.monitor = older_console  # type: ignore[method-assign]
    out = refused("offers no registerpoints", s.regpoint_add(condition="d1==7fff"))
    assert out["code"] == "no_channel" and "unknown command" in out["message"], out
    assert s.declaration_list("regpoint")["regpoints"] == []


def test_a_row_the_list_does_not_show_after_rpset_is_readback_refused_and_the_declaration_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor

    def forgetful(command: str, timeout: float = 10.0) -> str:
        answer = real(command, timeout)
        if command.startswith("rpset "):
            ses.rplist_rows.clear()
        return answer

    ses.monitor = forgetful  # type: ignore[method-assign]
    out = refused("does not list it: nothing is armed", s.regpoint_add(condition="d1==7fff"))
    assert out["code"] == "readback_refused" and out["ref"] == "d1==7fff"
    assert (out["stored"], out["armed"], out["state"]) == (True, False, "gone"), out
    assert "re-arms at the next `start`" in out["note"] and (
        "declaration_clear(kind=\"regpoint\", ref='d1==7fff')" in out["note"]), (
        "the refusal says the declaration was KEPT, and what removes it")
    assert [(r["ref"], r["state"]) for r in s.declaration_list("regpoint")["regpoints"]] == [
        ("d1==7fff", "gone")]
    assert s.status()["in_debugger"]["regpoints"] == []


def test_a_row_already_listed_under_the_condition_is_adopted_and_nothing_is_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    _two_cpus(monkeypatch)
    ses.rplist_rows = [(3, "d1==7fff", True)]
    ses.rp_next_index = 4
    out = s.regpoint_add(condition="d1==7fff")
    assert out["armed"] is True and out["index"] == 3 and "already_stored" not in out, out
    assert not any(c.startswith("rpset") for c in ses.commands)
    again = s.regpoint_add(condition="d1==7fff")
    assert again["already_stored"] is True and again["index"] == 3
    assert len(ses.rplist_rows) == 1, "a re-declaration never stacks a second row"


def test_regpoint_add_on_a_running_machine_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.go()
    out = s.regpoint_add(condition="d1==7fff")
    assert out["status"] == "ok" and out["while_running"] is True and out["armed"] is True
    listed = s.declaration_list("regpoint")
    assert listed["session"]["running"] is True and "last_stop" in listed
    assert s.declaration_clear("regpoint", ref="d1==7fff")["while_running"] is True


def test_regpoint_list_places_every_declaration_and_names_the_rows_it_did_not_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.rplist_rows = [(1, "d0==1", True)]              # typed through `debug`
    ses.rp_next_index = 2
    s.regpoint_add(condition="d1==7fff")
    s.regpoint_add(condition="d1==2")
    ses.rplist_rows[2] = (3, "d1==2", False)            # `rpdisable 3` through `debug`
    out = s.declaration_list("regpoint")
    assert out["summary"] == "declaration_list regpoint: 2 regpoints (1 armed)"
    rows = {r["ref"]: r for r in out["regpoints"]}
    assert set(rows["d1==7fff"]) == {"ref", "by", "created_at", "origin", "inherited", "age_s",
                                     "condition", "state", "entry", "index", "cpu"}
    assert rows["d1==7fff"]["state"] == "armed" and rows["d1==7fff"]["inherited"] is False
    assert rows["d1==2"]["state"] == "disabled" and rows["d1==2"]["entry"] == "D 3 if d1==2"
    assert out["foreign"] == {"regpoints": ["1 if d0==1"]}
    assert "running" not in out
    ses.rplist_rows = [r for r in ses.rplist_rows if r[0] != 2]      # `rpclear 2` by hand
    gone = {r["ref"]: r for r in s.declaration_list("regpoint")["regpoints"]}["d1==7fff"]
    assert gone["state"] == "gone" and "entry" not in gone and "index" not in gone


def test_regpoint_clear_sends_the_index_as_listed_and_reports_what_the_list_lost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.rplist_rows = [(9, "d0==1", True)]              # a foreign row, never deleted
    ses.rp_next_index = 10
    s.regpoint_add(condition="d1==7fff")
    s.regpoint_add(condition="d1==2")
    out = s.declaration_clear("regpoint", ref="d1==7fff")
    assert "rpclear 0xa" in ses.commands, "the tenth row is `A`: the index goes out prefixed"
    assert out["declarations_cleared"] == 1 and out["disarmed"] == ["A if d1==7fff"]
    assert out["while_running"] is False
    assert out["summary"] == "declaration_clear regpoint d1==7fff: 1 cleared, 1 disarmed"
    missing = refused("matches no regpoint declaration", s.declaration_clear("regpoint",
                                                                             ref="d1==7fff"))
    assert missing["code"] == "unknown_ref" and "'d1==2'" in missing["message"]
    assert "`regpoint_add` reply" in missing["message"]
    everything = s.declaration_clear("regpoint", all=True)
    assert everything["declarations_cleared"] == 1 and everything["disarmed"] == ["B if d1==2"]
    assert ses.rplist_rows == [(9, "d0==1", True)], "a foreign row is never deleted"
    assert s.status()["in_debugger"]["regpoints"] == []
    assert s.declaration_clear("regpoint", all=True)["declarations_cleared"] == 0


def test_a_clear_whose_row_stays_listed_does_not_claim_it_disarmed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.regpoint_add(condition="d1==7fff")
    real = ses.monitor

    def deaf(command: str, timeout: float = 10.0) -> str:
        if command.startswith("rpclear "):
            ses.commands.append(command)
            return captured("rpclear-invalid.txt")
        return real(command, timeout)

    ses.monitor = deaf  # type: ignore[method-assign]
    out = s.declaration_clear("regpoint", ref="d1==7fff")
    assert out["disarmed"] == [] and out["declarations_cleared"] == 1, out
    # SAID, as a breakpoint's and a watch's clear say it: the row is still held, and the
    # command that removes it is named.
    assert 'debug("rpclear 0x1")' in out["note"] and "still lists" in out["note"], out


def test_a_regpoint_of_this_server_that_fires_is_named_and_stays_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.regpoint_add(condition="d1==7fff")
    (tmp_path / "debug.log").write_text(captured("debuglog-foreign-rp-resume.txt"))
    ses.stops_after_polls = 1
    out = s.resume(seconds=2.0)
    assert (out["verdict"] == "OTHER_STOP"
            and out["cause"] == "registerpoint 'd1==7fff'"), out["cause"]
    assert out["regpoint_hit"] == {"ref": "d1==7fff", "condition": "d1==7fff", "index": 1,
                                   "cpu": ":maincpu", "pc": out["pc"], "note": _NOTE}
    assert [r["state"] for r in s.declaration_list("regpoint")["regpoints"]] == ["armed"]
    assert s.status()["last_stop"]["cause"] == "registerpoint 'd1==7fff'"


def test_an_inherited_regpoint_that_fires_says_whose_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.regpoint_add(condition="d1==7fff")
    monkeypatch.setattr(mstate.STATE, "session_origin", "s2")
    (tmp_path / "debug.log").write_text(_STOP_LINE)
    ses.stops_after_polls = 1
    how = s.resume(seconds=2.0)["cause"]
    assert how.startswith("registerpoint 'd1==7fff' (a PERSISTENT declaration"), how
    assert ("`declaration_list(kind=\"regpoint\")` shows it and "
            "`declaration_clear(kind=\"regpoint\")` removes it") in how, how


def test_a_frame_run_cut_by_a_regpoint_of_this_server_carries_the_hit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _typed(monkeypatch, tmp_path, frame=10, stop_after=1)
    reg.rplist_rows = []
    use_table(monkeypatch, table={})
    assert s.regpoint_add(condition="d1==7fff")["index"] == 1
    reg.frozen = True
    _log_on(reg, tmp_path, "gvblank", _STOP_LINE)
    out = s.run_for(frames=2, seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cause"] == "registerpoint 'd1==7fff'", out
    assert out["regpoint_hit"]["index"] == 1 and out["regpoint_hit"]["note"] == _NOTE


# ------------------------------------------------------------------ across a `start`


def _stored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
            *conditions: str) -> _RunningSession:
    """A fresh machine over a store that already holds `conditions`, as a `start` finds it."""
    ses = _running(monkeypatch, tmp_path)
    for condition in conditions:
        arming.store().add(dec.Declaration("regpoint", "expr", condition, origin="s0"))
    return ses


def _rearm(ses: _RunningSession) -> dict[str, list[Any]]:
    """The two halves `start` runs, in its order, over one account."""
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    regpoints.rearm(ses, out)  # type: ignore[arg-type]
    return out


def test_a_stored_regpoint_is_re_armed_at_start_and_read_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _stored(monkeypatch, tmp_path, "d1==7fff", "d0==DemoLen")
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC})
    out = _rearm(ses)
    assert refs(out["rearmed"]) == ["d1==7fff", "d0==DemoLen"] and out["unarmable"] == [], out
    assert [c for c in _sent(ses) if c.startswith("rpset")] == [
        "rpset {d1==7fff}", "rpset {d0==0x2031fc}"], "re-resolved against THIS start's table"
    assert ses.commands.count("rplist") == 2, "the list is read once before and once after"
    rows = s.declaration_list("regpoint")["regpoints"]
    assert [(r["state"], r["inherited"]) for r in rows] == [("armed", True)] * 2


def test_a_re_armed_regpoint_row_names_whose_it_is_and_how_old(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The registerpoint half of `start`'s account gives each row the one `arming.decl_row`
    builds for ITS declaration, armed or refused alike: one row the session's own, one another's."""
    ses = _running(monkeypatch, tmp_path)
    mine = dec.Declaration("regpoint", "expr", "d1==7fff", origin=mstate.STATE.session_origin,
                           created_at="2026-01-01T00:00:00+00:00")
    theirs = dec.Declaration("regpoint", "expr", "d0==DemoLen", origin="s0",
                             created_at="2025-06-01T00:00:00+00:00")
    arming.store().add(mine)
    arming.store().add(theirs)
    ses.rp_errors = {"d0==DemoLen": captured("print-braces-unknown-symbol.txt")}
    out = _rearm(ses)
    held = {d.ref: d for d in arming.store().declarations()}  # as the re-arm bound their cpu
    for (row,), decl in ((out["rearmed"], mine), (out["unresolved"], theirs)):
        assert {k: row[k] for k in IDENTITY_KEYS} == arming.decl_row(held[decl.ref]), row
    assert (out["rearmed"][0]["inherited"], out["unresolved"][0]["inherited"]) == (False, True)


def test_a_row_already_listed_is_adopted_by_the_re_arm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _stored(monkeypatch, tmp_path, "d1==7fff")
    _two_cpus(monkeypatch)
    ses.rplist_rows = [(5, "d1==7fff", True)]
    out = _rearm(ses)
    assert refs(out["rearmed"]) == ["d1==7fff"]
    first = out["rearmed"][0]
    assert isinstance(first, dict) and "state" not in first, "an enabled row adds nothing"
    assert not any(c.startswith("rpset") for c in ses.commands)
    assert s.declaration_list("regpoint")["regpoints"][0]["index"] == 5


def test_a_row_listed_disabled_is_adopted_by_the_re_arm_saying_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The double answers `rplist` with the captured `rplist-disabled.txt` byte for byte (pinned
    above): the re-arm adopts the row as `regpoint_add` does, and says it is disabled and what
    enables it."""
    ses = _stored(monkeypatch, tmp_path, "d1==7fff")
    _two_cpus(monkeypatch)
    ses.rplist_rows = [(1, "d1==7fff", False)]
    out = _rearm(ses)
    assert refs(out["rearmed"]) == ["d1==7fff"] and out["unarmable"] == [], out
    first = out["rearmed"][0]
    assert isinstance(first, dict) and first["state"] == "disabled", out
    assert 'debug("rpenable 0x1")' in first["note"], out
    assert not any(c.startswith("rpset") for c in ses.commands)


def test_a_symbol_this_build_lacks_is_unresolved_and_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _stored(monkeypatch, tmp_path, "d0==DemoLen")
    ses.rp_errors = {"d0==DemoLen": captured("print-braces-unknown-symbol.txt")}
    out = _rearm(ses)
    assert refs(out["unresolved"]) == ["d0==DemoLen"] and refs(out["rearmed"]) == [], out
    assert not any(c.startswith("rpset") for c in ses.commands)
    assert [r["state"] for r in s.declaration_list("regpoint")["regpoints"]] == ["unresolved"]


def test_a_console_error_while_a_re_arm_evaluates_a_regpoint_is_that_declarations_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `print {...}` the console does not answer is `unarmable` for THAT declaration, with
    the error's words, and the pass goes on to the next one."""
    ses = _stored(monkeypatch, tmp_path, "d1==7fff", "d0==1")
    real = ses.monitor

    def silent(command: str, timeout: float = 10.0) -> str:
        if command == "print {d1==7fff}":
            raise gs.SessionError("the console answered nothing within 10.0 s")
        return real(command, timeout)

    ses.monitor = silent  # type: ignore[method-assign]
    out = _rearm(ses)
    assert [(u["ref"], u["cpu"], u["why"]) for u in out["unarmable"]] == [
        ("d1==7fff", ":maincpu", "the console answered nothing within 10.0 s")]
    assert refs(out["rearmed"]) == ["d0==1"], "the pass went on past it"
    assert [c for c in ses.commands if c.startswith("rpset")] == ["rpset {d0==1}"]


def test_the_two_families_unresolved_conditions_are_one_set_that_clears_by_family(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A breakpoint's unresolved condition and a regpoint's are kept in one place, and the
    clear of one family leaves the other's listed `unresolved`."""
    ses = _stored(monkeypatch, tmp_path, "d0==DemoLen")
    use_table(monkeypatch, table={"IRQ_VBLANK": 0x4A0})
    arming.store().add(dec.Declaration("breakpoint", "symbol", "irq_vblank", origin="s0",
                                       condition="w@DemoLen==0x25"))
    ses.rp_errors = {"d0==DemoLen": captured("print-braces-unknown-symbol.txt"),
                     "w@DemoLen==0x25": captured("print-braces-unknown-symbol.txt")}
    out = _rearm(ses)
    assert refs(out["unresolved"]) == ["irq_vblank", "d0==DemoLen"], out
    assert [r["state"] for r in s.declaration_list("regpoint")["regpoints"]] == ["unresolved"]
    assert [r["state"] for r in s.declaration_list("breakpoint")["breakpoints"]] == ["unresolved"]
    assert s.declaration_clear("regpoint", ref="d0==DemoLen")["declarations_cleared"] == 1
    listed = s.declaration_list("breakpoint")["breakpoints"]
    assert [r["state"] for r in listed] == ["unresolved"], (
        "the regpoint's clear did not drain the breakpoint's")
    assert s.declaration_clear("breakpoint", ref="irq_vblank")["declarations_cleared"] == 1
    assert s.declaration_list("breakpoint")["breakpoints"] == []


def test_what_cannot_be_armed_at_start_says_why_and_stays_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    long = "d1==0x" + "0" * 80 + "1"
    ses = _stored(monkeypatch, tmp_path, "d1==", long, "d1==3")
    ses.packet_size = 64
    ses.rp_print_errors = {"d1==": captured("print-braces-malformed.txt")}
    real = ses.monitor

    def forgetful(command: str, timeout: float = 10.0) -> str:
        answer = real(command, timeout)
        if command.startswith("rpset "):
            ses.rplist_rows.clear()
        return answer

    ses.monitor = forgetful  # type: ignore[method-assign]
    out = _rearm(ses)
    why = {str(u["ref"]): str(u["why"]) for u in out["unarmable"]}
    assert set(why) == {"d1==", long, "d1==3"} and refs(out["rearmed"]) == [], out
    assert "stack underflow" in why["d1=="]
    assert "packet size carries at most" in why[long]
    assert "does not list it" in why["d1==3"]
    assert len(s.declaration_list("regpoint")["regpoints"]) == 3, "nothing is dropped"


def test_a_store_with_no_regpoint_asks_the_console_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _stored(monkeypatch, tmp_path)
    assert _rearm(ses)["rearmed"] == [] and _sent(ses) == []


def test_two_conditions_that_read_the_same_are_one_row_and_the_second_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two symbols on one address: typed they differ, sent they are the same text. One row is
    one declaration, at the add and in one pass of the re-arm alike, or the second `rpset`
    arms a row no ref holds and no clear reaches."""
    ses = _running(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"LIVES": 0x2031FC, "LIVES_ALIAS": 0x2031FC})
    _two_cpus(monkeypatch)
    assert s.regpoint_add(condition="d0==Lives")["index"] == 1
    out = refused("already arms", s.regpoint_add(condition="d0==Lives_Alias"))
    assert out["code"] == "ambiguous_ref" and out["message"].endswith(
        "'d0==Lives' already arms: one registerpoint row is one declaration, so "
        "`declaration_clear(kind=\"regpoint\", ref='d0==Lives', cpu=\":maincpu\")` frees it, or "
        "use that ref"), out
    assert len(ses.rplist_rows) == 1 and len(s.declaration_list("regpoint")["regpoints"]) == 1
    fresh = _stored(monkeypatch, tmp_path, "d0==Lives", "d0==Lives_Alias")
    use_table(monkeypatch, table={"LIVES": 0x2031FC, "LIVES_ALIAS": 0x2031FC})
    account = _rearm(fresh)
    assert refs(account["rearmed"]) == ["d0==Lives"], account
    assert [u["ref"] for u in account["unarmable"]] == ["d0==Lives_Alias"]
    assert len(fresh.rplist_rows) == 1, "one row, not two"


def test_an_adopted_row_is_one_declarations_in_the_re_arm_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _stored(monkeypatch, tmp_path, "d0==Lives", "d0==Lives_Alias")
    use_table(monkeypatch, table={"LIVES": 0x2031FC, "LIVES_ALIAS": 0x2031FC})
    _two_cpus(monkeypatch)
    ses.rplist_rows, ses.rp_next_index = [(4, "d0==0x2031fc", True)], 5
    account = _rearm(ses)
    assert refs(account["rearmed"]) == ["d0==Lives"] and _sent(ses).count("rplist") == 1, account
    why = str(account["unarmable"][0]["why"])
    assert why.endswith("'d0==Lives' already arms: one registerpoint row is one declaration"), why


def test_two_stored_regpoints_of_one_condition_in_one_pass_say_sent_and_never_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The second of the pass meets a row that was SENT a moment ago and not yet read back:
    the account says that, and keeps `already arms` for a row the list showed."""
    ses = _stored(monkeypatch, tmp_path, "d0==Lives", "d0==Lives_Alias")
    use_table(monkeypatch, table={"LIVES": 0x2031FC, "LIVES_ALIAS": 0x2031FC})
    account = _rearm(ses)
    assert refs(account["rearmed"]) == ["d0==Lives"], account
    why = str(account["unarmable"][0]["why"])
    assert why.endswith("'d0==Lives' was just sent for: one registerpoint row is one "
                        "declaration"), why


def test_a_console_with_no_registerpoints_makes_a_stored_one_unarmable_and_the_start_goes_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _stored(monkeypatch, tmp_path, "d1==7fff")
    real = ses.monitor

    def older_console(command: str, timeout: float = 10.0) -> str:
        return (captured("rpset-unknown-command.txt") if command.startswith("rpset ")
                else real(command, timeout))

    ses.monitor = older_console  # type: ignore[method-assign]
    account = _rearm(ses)
    assert refs(account["rearmed"]) == [], account
    assert "offers no registerpoints" in str(account["unarmable"][0]["why"])
    assert len(s.declaration_list("regpoint")["regpoints"]) == 1, "kept"


# ------------------------------------------------------------------ a board with two cpus


def test_rplist_lists_each_cpu_under_its_own_header() -> None:
    rows = regpoints.parse_rplist(captured("rplist-two-devices.txt"))
    assert [(r["cpu"], r["index"], r["condition"]) for r in rows] == [
        (":maincpu", 1, "d1==7fff"), (":subcpu", 2, "d1==7fff")]
    assert rplist_answer([(1, "d1==7fff", True), (2, "d1==7fff", True)],
                         {2: ":subcpu"}) == captured("rplist-two-devices.txt")


@pytest.mark.parametrize("other", [":subcpu", ":audiocpu"],
                         ids=["listed-after-the-visible-cpu", "listed-before-it"])
def test_the_same_condition_under_another_cpu_is_not_this_ones_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, other: str,
) -> None:
    """The captured board: `d1==7fff` typed on the sub cpu compares ANOTHER D1. The add arms
    its own row on the visible cpu and knows it by the index the console answered."""
    ses = _running(monkeypatch, tmp_path)
    _two_cpus(monkeypatch)
    ses.rplist_rows, ses.rp_devices, ses.rp_next_index = [(1, "d1==7fff", True)], {1: other}, 2
    out = s.regpoint_add(condition="d1==7fff")
    assert out["cpu"] == ":maincpu" and out["index"] == 2, out
    assert "rpset {d1==7fff}" in _sent(ses)
    listed = s.declaration_list("regpoint")
    assert listed["regpoints"][0]["cpu"] == ":maincpu" and listed["foreign"] == {
        "regpoints": ["1 if d1==7fff"]}
    assert s.declaration_clear("regpoint", all=True)["disarmed"] == ["2 if d1==7fff"]
    assert ses.rplist_rows == [(1, "d1==7fff", True)], "the sub cpu's row is never deleted"


def test_the_row_adopted_is_the_one_under_the_cpu_visible_now(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The visible cpu is read off `cpulist` at the call, so after it moves to the sub cpu
    the sub cpu's row is the one an `rpset` would land beside, and the main cpu's is not."""
    ses = _running(monkeypatch, tmp_path)
    _two_cpus(monkeypatch)
    ses.visible_cpu = ":subcpu"
    ses.rplist_rows, ses.rp_devices, ses.rp_next_index = (
        [(1, "d1==7fff", True), (2, "d1==7fff", True)], {2: ":subcpu"}, 3)
    out = s.regpoint_add(condition="d1==7fff")
    assert (out["index"], out["cpu"]) == (2, ":subcpu"), out
    assert "rpset {d1==7fff}" not in _sent(ses)


def test_with_the_visible_cpu_unknown_nothing_is_adopted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A console that marks no cpu in `cpulist` leaves the visible cpu unknown, and a second
    row of one condition is the cheaper mistake."""
    ses = _running(monkeypatch, tmp_path)
    _two_cpus(monkeypatch)
    real = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: "" if c == "cpulist" else real(c))
    ses.rplist_rows, ses.rp_next_index = [(1, "d1==7fff", True)], 2
    assert s.regpoint_add(condition="d1==7fff")["index"] == 2


# ------------------------------------------------------------------ the rest of the states


def test_an_adopted_row_the_debugger_lists_disabled_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    _two_cpus(monkeypatch)
    ses.rplist_rows, ses.rp_next_index = [(1, "d1==7fff", False)], 2
    out = s.regpoint_add(condition="d1==7fff")
    assert out["armed"] is False and out["state"] == "disabled", out
    assert out["summary"] == "regpoint_add d1==7fff: stored, disabled"
    assert not any(c.startswith("rpset") for c in ses.commands)


def test_a_symbol_that_came_to_collide_with_a_register_is_listed_unresolved_with_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    s.regpoint_add(condition="d0==1")
    use_table(monkeypatch, table={"D0": 0x1000})
    row = s.declaration_list("regpoint")["regpoints"][0]
    assert row["state"] == "unresolved" and "both a symbol" in row["why"], row


def test_an_unresolved_regpoint_stops_being_one_once_cleared_or_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _stored(monkeypatch, tmp_path, "d0==DemoLen")
    ses.rp_errors = {"d0==DemoLen": captured("print-braces-unknown-symbol.txt")}
    _rearm(ses)
    ses.rp_errors = {}
    assert s.regpoint_add(condition="d0==DemoLen")["already_stored"] is True
    assert [r["state"] for r in s.declaration_list("regpoint")["regpoints"]] == ["armed"]
    ses.rplist_rows.clear()
    listed = s.declaration_list("regpoint")["regpoints"]
    assert [r["state"] for r in listed] == ["gone"], "not unresolved"
    again = _stored(monkeypatch, tmp_path, "d0==DemoLen")
    again.rp_errors = {"d0==DemoLen": captured("print-braces-unknown-symbol.txt")}
    _rearm(again)
    s.declaration_clear("regpoint", all=True)
    again.rp_errors = {}
    arming.store().add(dec.Declaration("regpoint", "expr", "d0==DemoLen", origin="s0"))
    assert [r["state"] for r in s.declaration_list("regpoint")["regpoints"]] == ["gone"]


def test_the_newest_line_in_the_window_names_the_stop_whichever_family_logged_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A breakpoint typed with an action that resumes leaves its line in the window of the
    registerpoint that really ended the run: the machine stands at the last line."""
    reg = _typed(monkeypatch, tmp_path)
    reg.bplist_rows = ["    1 @ 000400"]
    real_go = reg.go

    def go_through_the_breakpoint() -> None:
        (tmp_path / "debug.log").write_text(
            captured("debuglog-foreign-bp-ms.txt") + _STOP_LINE)
        real_go()

    reg.go = go_through_the_breakpoint  # type: ignore[method-assign]
    assert s.resume(seconds=2.0)["cause"] == _FOREIGN_CAUSE


def test_a_regpoint_is_never_run_tos_target_and_its_stop_is_named_there_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The double's control counts nothing, so the cut is `run_to`'s own refusal for a stop
    that came before any control fired; what matters here is that the stop is the regpoint's."""
    ses = _running(monkeypatch, tmp_path)
    s.regpoint_add(condition="d1==7fff")
    (tmp_path / "debug.log").write_text(_STOP_LINE)
    ses.stops_after_polls = 1
    out = s.run_to(ref="0xf9999", control="0x4a0", seconds=2.0)
    assert out["code"] == "cut_by_other_stop" and out["cause"] == "registerpoint 'd1==7fff'", out
    assert out["regpoint_hit"]["ref"] == "d1==7fff"


def test_the_double_answers_rpset_as_the_captures_do(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The rewrites the double makes of a captured answer are held to the OTHER captures: a
    `replace` that matched nothing would hand back index 1 for ever."""
    ses = _running(monkeypatch, tmp_path)
    assert ses.monitor("rpset {d1==7fff}") == captured("rpset-set.txt")
    assert ses.monitor("rpset {d1==}") == captured("rpset-malformed-armed.txt"), "MAME arms it"
    assert ses.monitor("rpclear 2") == captured("rpclear-cleared.txt")
    assert ses.monitor("rpclear 7") == captured("rpclear-invalid.txt")
    ses.rp_next_index = 16
    assert ses.monitor("rpset {1}") == captured("rpset-sixteenth.txt")


def test_an_rpclear_typed_through_debug_drops_the_record_of_the_row_it_removed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A registerpoint cleared by hand kept its record, so a sequence's tail over an otherwise
    empty store waited its bound for a stop nothing could make. The raw clear drops the record
    of the row it removed, and only that one."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    gone = s.regpoint_add(condition="d1==7fff")
    kept = s.regpoint_add(condition="d2==1")
    assert gone["status"] == kept["status"] == "ok", (gone, kept)
    s.debug(command=f"rpclear {gone['index']:x}")
    assert ("d1==7fff", ":maincpu") not in mstate.STATE.regpoints, mstate.STATE.regpoints
    assert ("d2==1", ":maincpu") in mstate.STATE.regpoints, \
        "a row the list still shows keeps its record"
    assert {r["ref"]: r["state"] for r in s.declaration_list("regpoint")["regpoints"]} == {
        "d1==7fff": "gone", "d2==1": "armed"}
    s.debug(command=f"rpclear {kept['index']:x}")
    assert not ses.running
    out = s.perform(steps=[{"op": "resume"}, {"op": "status"}], settle_seconds=0.05)
    assert out["still_running"] is True and "nothing declared" in out["note"], out["note"]


# ------------------------------------------------------------------ the batch and the console


def test_perform_judges_a_regpoint_step_before_the_first_step_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "regpoint_add", "condition": "d1==7fff"},
                           {"op": "regpoint_add", "condition": "d1=5"}])
    assert out["status"] == "INVALID" and _sent(ses) == [], out
    out = s.perform(steps=[{"op": "regpoint_add", "condition": "d1==7fff"},
                           {"op": "declaration_list", "kind": "regpoint"},
                           {"op": "declaration_clear", "kind": "regpoint", "ref": "d1==7fff"}])
    assert out["status"] == "ok" and [r["op"] for r in out["ran"]] == [
        "regpoint_add", "declaration_list", "declaration_clear"], out
    assert {"regpoint_add", "declaration_list", "declaration_clear"} <= sequence.RUNNING_OK_OPS


@pytest.mark.parametrize("command, writes", [
    ("rpset {d1==7fff}", False), ("rp {d1==7fff}", False), ("rplist", False),
    ("rpclear 1", False), ("rpdisable 1", False), ("rpenable 1", False),
    ("rpset {d1=5}", True), ("rpset {d1==1},{pokew 100,1}", True), ("rpset {d1==1},{g}", True),
])
def test_debug_counts_a_registerpoint_as_bookkeeping_unless_it_carries_an_action(
    command: str, writes: bool,
) -> None:
    assert mconsole.mutates(command) is writes, command


@pytest.mark.parametrize("declared,named", [
    ("d1==7fff", "d1==0x7fff"), ("d1==0x7fff", "d1==7fff"), ("d1==0ab", "d1==0XAB"),
    ("w@1234==5", "w@0x1234==0x5"), ("d1==$7fff", "d1==#32767"), ("d1==#32767", "d1==7fff"),
])
def test_a_registerpoint_is_cleared_by_its_condition_in_either_spelling_of_a_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, declared: str, named: str,
) -> None:
    """The console reads a bare number as hex, so `7fff` and `0x7fff` are one condition: a clear
    names it either way, and a second declaration in the other spelling is the same one."""
    ses = _running(monkeypatch, tmp_path)
    ses.rp_next_index = 1
    s.regpoint_add(condition=declared)
    again = s.regpoint_add(condition=named)
    assert again.get("already_stored") is True, again
    out = s.declaration_clear("regpoint", ref=named)
    assert out["declarations_cleared"] == 1, out


@pytest.mark.parametrize("a,b,same", [
    ("d1==ab", "d1==0xab", False),   # `ab` may be a symbol: a name is never folded into a number
    ("a1f==1", "a1f==0x1", True),    # `1` folds, the name holding hex digits does not
    ("d1==10", "d1==0x100", False),
    # express.cpp's prefixes: `$` hex, `#` decimal, a bare number hex.
    ("d1==$AB", "d1==0xab", True),
    ("d1==#16", "d1==0x10", True),
    ("d1==#16", "d1==16", False),
    ("d1==#1f", "d1==0x1f", False),      # no decimal: the console refuses it, nothing folds
    ("d1==$7fg", "d1==0x7f", False),     # one token the console refuses, nothing folds
    ("d1==$", "d1==0x0", False),         # a prefix with no digits is left as typed
    ("d1==0b101", "d1==0x5", True),      # `0b` is binary
    ("d1==0b12", "d1==0xb12", True),     # not binary: the console falls back to hex
    ("d1==0o17", "d1==0xf", True),       # `0o` is octal
    ("d1==0o19", "d1==0x19", False),     # no octal: the console refuses it, nothing folds
    ("d1==#", "d1==0x0", False),
    # `$` and `#` inside a token are part of a name: the number after them is not folded.
    ("a$1==1", "a$0x1==1", False),
    ("a#1==1", "a#0x1==1", False),
    # A u64 has at most 20 decimal digits: a longer `#` run is left as typed, never read.
    pytest.param("d1==#" + "1" * 4400, "d1==#" + "1" * 4400, True, id="decimal-past-a-u64"),
])
def test_only_numbers_fold_and_a_name_never_does(a: str, b: str, same: bool) -> None:
    from scry_mame import inputs
    assert (inputs.match_key(a, "expr") == inputs.match_key(b, "expr")) is same


#: Each clause's example, as the store compares it: (kind, one spelling, another, equal).
CLAUSE_EXAMPLES = [
    ("address", "0x00FF", "0xff", True),
    ("symbol", "SpriteBase", "spritebase", True),
    ("pointer", "[SpriteBase]+0x28", "[spritebase]+28", True),
    ("pointer", "[0x00FF]+4", "[0xff]+0x4", True),
    ("pointer", "[fade]+4", "[0xfade]+4", False),
    ("expr", "d1==7fff", "d1==0x7fff", True),
    ("expr", "d1==7fff", "d1==$7fff", True),
    ("expr", "d1==7fff", "d1==#32767", True),
    ("expr", "d1==7fff", "D1==7fff", False),
    ("expr", "a0==ab", "a0==0xab", False),
]


@pytest.mark.parametrize(("by", "one", "other", "same"), CLAUSE_EXAMPLES)
def test_each_clauses_example_holds_under_the_stores_comparison(
    by: str, one: str, other: str, same: bool,
) -> None:
    assert (dec.match_key(one, by) == dec.match_key(other, by)) is same


def test_each_family_is_told_only_of_the_kinds_it_holds() -> None:
    """A breakpoint is an address or a symbol, a registerpoint an expression; an expression's
    names keep their case, so no clause about case reaches the expression family."""
    assert "expression" not in dec.REF_MATCH["breakpoint"]
    assert "pointer" not in dec.REF_MATCH["breakpoint"]
    assert "case" not in dec.REF_MATCH["regpoint"] and "address" not in dec.REF_MATCH["regpoint"]
    assert "`d1==7fff`, `d1==0x7fff`, `d1==$7fff` and `d1==#32767` match" in dec.REF_MATCH[
        "regpoint"]


def test_a_clears_refusal_states_the_rule_it_was_matched_under(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The refusal names the list that shows the refs and its family's rule; the other
    spelling then clears."""
    _running(monkeypatch, tmp_path)
    s.regpoint_add(condition="d1==0x7ff1")
    missing = refused("matches no regpoint declaration", s.declaration_clear("regpoint",
                                                                             ref="d1==7ff2"))
    text = " ".join(missing["message"].split())
    assert f"Matching: {dec.REF_MATCH['regpoint']}." in text, text
    assert "`declaration_list(kind=\"regpoint\")`" in text, text
    assert s.declaration_clear("regpoint",
                               ref="d1==7ff1")["declarations_cleared"] == 1, "the rule it states"


@pytest.mark.parametrize("family", ["breakpoint", "watch", "regpoint"])
def test_a_clears_refusal_names_its_own_familys_list_and_no_other(family: str) -> None:
    """The list that shows a family's refs is the one its refusal names: a regpoint's refusal
    naming `declaration_list(kind="breakpoint")` sends the agent to a list that cannot hold what it
    typed."""
    out = mclear.refuse_unmatched_clear("d1==1", family, mclear.Clearing([], [], [], None))
    text = " ".join(out["message"].split())
    named = {f for f in ("breakpoint", "watch", "regpoint")
             if f'`declaration_list(kind="{f}")`' in text}
    assert named == {family}, text
    assert text.endswith(f"Matching: {dec.REF_MATCH[family]}."), text




@pytest.mark.parametrize(("parse", "command"), [
    (lambda text: regpoints.parse_rplist(text), "rplist"),
    (lambda text: mlists.parse_bplist(text), "bplist"),
    (lambda text: mlists.parse_wplist(text), "wplist"),
])
def test_each_list_refusal_names_its_own_command_and_quotes_what_it_read(
    parse: Any, command: str,
) -> None:
    """One reader serves the three lists: each refusal still names the command it read, the
    console call that shows it, and the text that was not a list."""
    with pytest.raises(mstate.Invalid) as e:
        parse("Huh? this is no list\n")
    message = str(e.value)
    assert f"`{command}`" in message and f'debug("{command}")' in message, message
    assert "'Huh? this is no list'" in message, message


def test_an_rplist_row_before_any_header_has_an_empty_cpu() -> None:
    rows = regpoints.parse_rplist("    1 if d1==7fff\n")
    assert rows[0]["cpu"] == "" and isinstance(rows[0]["cpu"], str), rows
