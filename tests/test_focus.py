"""`focus`: the visible cpu moved by the server, read back, and what the move did.

The patched stub's `Hc` moves nothing, and the reply proves it on the frame counter and each
cpu's whole register block. A stub without threads leaves only the console's `focus`, which
ignores every other cpu and runs until the focused one executes; the reply names what it
ignored and surveys where it stopped. The doubles answer `cpulist`, `ignore` and `focus` from
captures of radendur.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_doubles import ignored_in, refused, visible_in  # noqa: E402
from test_server import _running, _RunningSession  # noqa: E402

import gdb_session as gs  # noqa: E402
import mame_cpus as cpus  # noqa: E402
import mame_focus as mfocus  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

_THREADS = {1: ":maincpu", 2: ":subcpu"}


def _patched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _RunningSession:
    ses = _running(monkeypatch, tmp_path)
    ses.threads = dict(_THREADS)
    return ses


@pytest.mark.parametrize("spelling", ["subcpu", ":subcpu"])
def test_the_patched_stub_shows_the_cpu_and_proves_nothing_ran(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, spelling: str,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    ses.commands.clear()
    out = s.focus(cpu=spelling)
    assert out["status"] == "ok", out
    assert (out["cpu"], out["was"], out["via"], out["machine_ran"]) == (":subcpu", ":maincpu",
                                                                        "stub",
                                                                False)
    assert out["unchanged"] == [":maincpu", ":subcpu"] and out["frame"] == ses.frame
    assert "unread" not in out and "ignored" not in out
    assert "Hc2" in ses.commands and not any(c.startswith("focus") for c in ses.commands), (
        "the stub's switch, never the console's focus, which ignores cpus")
    assert out["summary"] == "focus: :subcpu visible, was :maincpu, nothing ran (stub)"
    assert visible_in(s.cpu_info()) == ":subcpu"


def test_a_block_that_moved_across_the_switch_is_a_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The proof has to be able to fail: a register block read differently after the switch
    makes `ran` true and leaves that cpu out of `unchanged`, with the frame held."""
    ses = _patched(monkeypatch, tmp_path)
    real = ses.register_block
    after = {"switched": False}

    def moved(thread: int) -> str:
        block = real(thread)
        return block + "ff" if after["switched"] and thread == 1 else block

    def switch(thread: int) -> None:
        after["switched"] = True
        _RunningSession.make_visible(ses, thread)

    monkeypatch.setattr(ses, "register_block", moved)
    monkeypatch.setattr(ses, "make_visible", switch)
    out = s.focus(cpu="subcpu")
    assert out["machine_ran"] is True and out["unchanged"] == [":subcpu"], out


def test_a_frame_that_moved_across_the_switch_is_a_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)

    def switch(thread: int) -> None:
        ses.frame += 1
        _RunningSession.make_visible(ses, thread)

    monkeypatch.setattr(ses, "make_visible", switch)
    out = s.focus(cpu="subcpu")
    assert out["machine_ran"] is True and out["frame"] == ses.frame, out


def test_a_cpu_whose_block_the_stub_refuses_is_unread_and_never_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    ses.no_map = {2}
    out = s.focus(cpu="subcpu")
    assert out["unread"] == [":subcpu"] and out["unchanged"] == [":maincpu"], out
    assert out["machine_ran"] is False, "an unread block is not evidence of a run"


def test_the_patched_stub_refuses_a_cpu_the_debugger_ignores_and_names_observe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    ses.ignoring = [":subcpu"]
    out = refused(r"ignores :subcpu.*`debug\(\"observe :subcpu\"\)`", s.focus(cpu="subcpu"))
    assert out["code"] == "needs_call"
    assert visible_in(s.cpu_info()) == ":maincpu"


def test_a_refusal_of_hc_for_another_reason_is_the_stubs_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)

    def no(thread: int) -> None:
        raise gs.Refused(f"the stub refused `Hc{thread:x}`: E01")

    monkeypatch.setattr(ses, "make_visible", no)
    out = refused(r"refused `Hc2`.*not made visible; `cpu_info` says which cpu is",
                  s.focus(cpu="subcpu"))
    assert out["code"] == "unexpected_answer"


def test_a_cpu_read_back_other_than_the_one_asked_is_readback_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "make_visible", lambda thread: None)
    out = refused(r"`cpulist` shows :maincpu visible, not :subcpu: `cpu_info` says which cpu is "
                  "visible now", s.focus(cpu="subcpu"))
    assert out["code"] == "readback_refused" and out["cpu"] == ":maincpu"


def test_without_threads_the_consoles_focus_runs_and_the_reply_surveys_the_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.commands.clear()
    out = s.focus(cpu="subcpu")
    assert out["status"] == "ok", out
    assert (out["cpu"], out["was"], out["via"], out["machine_ran"]) == (":subcpu", ":maincpu",
                                                                        "console",
                                                                True)
    assert out["ignored"] == [":maincpu"]
    assert out["how"] == (
        "focus :subcpu: the console ignored :maincpu and ran until :subcpu executed")
    assert {"pc", "frame", "regs", "dasm"} <= set(out), "the stop it reached, surveyed"
    assert "focus :subcpu" in ses.commands and not any(c.startswith("Hc") for c in ses.commands)
    assert mstate.STATE.last_stop["how"] == out["how"], "recorded as the last stop"


def test_without_threads_focusing_the_visible_cpu_runs_nothing_and_surveys_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    out = s.focus(cpu="maincpu")
    assert (out["cpu"], out["machine_ran"], out["ignored"]) == (":maincpu", False, [":subcpu"]), out
    assert "how" not in out


def test_a_console_focus_that_reaches_no_observed_cpu_is_not_settled_and_left_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mfocus, "settled_visible", lambda ses, ignored: None)
    out = refused(r"no stop on a cpu it observes was read", s.focus(cpu="subcpu"))
    assert out["code"] == "not_settled" and out["via"] == "console"
    assert ses.running and mstate.STATE.console_run


def test_the_visible_cpu_is_read_once_the_run_left_the_ignored_cpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The wait ends on the first reading of a cpu the debugger observes, and runs out as None
    when none comes (`mame_focus.settled_visible` says why it is needed)."""
    ses = _running(monkeypatch, tmp_path)
    readings = iter([":maincpu", ":maincpu", ":subcpu"])
    monkeypatch.setattr(cpus, "visible_cpu", lambda ses: next(readings))
    monkeypatch.setattr(mfocus, "SETTLE_POLL_S", 0.0)
    assert mfocus.settled_visible(ses, [":maincpu"]) == ":subcpu"   # type: ignore[arg-type]
    monkeypatch.setattr(cpus, "visible_cpu", lambda ses: ":maincpu")
    monkeypatch.setattr(mfocus, "SETTLE_S", 0.05)
    assert mfocus.settled_visible(ses, [":maincpu"]) is None        # type: ignore[arg-type]


def test_a_console_focus_answered_otherwise_is_unexpected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: (
        "Unable to find device ':subcpu'\n\n" if c.startswith("focus") else real(c)))
    assert refused(r"answered \"Unable to find", s.focus(cpu="subcpu"))["code"] == (
        "unexpected_answer")


def test_a_cpu_the_machine_lacks_is_unknown_ref_naming_its_cpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    out = refused(r"no cpu 'audiocpu' on this machine", s.focus(cpu="audiocpu"))
    assert out["code"] == "unknown_ref" and out["cpus"] == [":maincpu", ":subcpu"]
    assert not any(c.startswith("Hc") for c in ses.commands)


def test_the_inventory_start_gathered_names_the_cpus_before_the_console_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _patched(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "machine_map", {"cpus": [{"tag": ":maincpu"}]})
    out = refused(r"no cpu 'subcpu'", s.focus(cpu="subcpu"))
    assert out["cpus"] == [":maincpu"]


def test_an_empty_cpu_is_refused_before_the_machine_is_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "proc", None)
    assert refused(r"cpu is empty", s.focus(cpu=" "))["code"] == "bad_argument"


def test_focus_needs_a_stopped_machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _patched(monkeypatch, tmp_path)
    s.resume()
    assert s.focus(cpu="subcpu")["code"] == "not_stopped"
    assert not any(c.startswith("Hc") for c in ses.commands)


def test_the_ignored_set_is_read_off_the_consoles_ignore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    assert cpus.ignored(ses) == []                           # type: ignore[arg-type]
    ses.ignoring = [":maincpu"]
    assert cpus.ignored(ses) == [":maincpu"]                 # type: ignore[arg-type]
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: "Unknown command\n")
    assert cpus.ignored(ses) is None, "an answer of neither shape is unknown, never none"  # type: ignore[arg-type]


def test_the_live_cpu_is_unknown_when_the_question_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)

    def fails() -> int:
        raise gs.SessionError("no answer to ?")

    monkeypatch.setattr(ses, "stopped_thread", fails)
    assert cpus.live_cpu(ses) is None                        # type: ignore[arg-type]


# ------------------------------------------ a focus, an ignore or an observe typed through debug


def test_a_typed_focus_that_moves_the_visible_cpu_is_read_back_and_said(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console's `focus` ignored the cpu that was visible, so MAME ran until the focused
    one executed: the reply reads the visible cpu and the ignored set back, and says it ran."""
    _running(monkeypatch, tmp_path)
    out = s.debug(command="print 1;focus subcpu")
    assert (out["visible_cpu"], out["ignored"]) == (":subcpu", [":maincpu"]), out
    assert "ignored :maincpu, the cpu MAME was live on, so it ran until :subcpu executed" in (
        out["note"])
    seen = s.cpu_info()
    assert ignored_in(seen) == [":maincpu"] and visible_in(seen) == ":subcpu"


def test_a_typed_focus_on_the_visible_cpu_moves_nothing_and_says_nothing_of_a_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    out = s.debug(command="focus maincpu")
    assert (out["visible_cpu"], out["ignored"]) == (":maincpu", [":subcpu"]), out
    assert "note" not in out, out


def test_a_line_that_touches_no_cpu_setter_reads_no_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.commands.clear()
    out = s.debug(command="print 1")
    assert "visible_cpu" not in out and ses.commands == ["print 1"], ses.commands


def test_a_typed_focus_whose_ignored_set_is_unreadable_says_the_release_was_not_judged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`ignore` answering neither of its shapes leaves `ignored` null, and whether the line
    ignored the live cpu, and so ran, cannot be told: the note says it was not judged, rather
    than the reply reading as a line that ran nothing."""
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: "" if c == "ignore" else real(c))
    out = s.debug(command="focus subcpu")
    assert out["ignored"]["available"] is False, out
    assert "`ignore` answered neither of its shapes, so whether this line released the " \
           "machine was not judged" in out["note"], out


def test_cpu_info_names_the_ignored_cpus_and_null_when_the_console_cannot_say(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    assert ignored_in(s.cpu_info()) == []
    real = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: "" if c == "ignore" else real(c))
    assert ignored_in(s.cpu_info()) is None


@pytest.mark.parametrize("ignored", [[":maincpu"], []], ids=["ignored", "observed"])
def test_an_arming_reply_on_an_ignored_cpu_says_the_row_has_no_effect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ignored: list[str],
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.ignoring = ignored
    want = "the debugger ignores :maincpu, so this row has no effect until `debug(\"observe"
    for out in (s.breakpoint_at(ref="0x4a0"), s.breakpoint_at(ref="0x25a4", role="control"),
                s.regpoint_add(condition="d1==7fff")):
        assert out["status"] == "ok" and out["cpu"] == ":maincpu", out
        assert (want in out.get("note", "")) == bool(ignored), out


def test_a_change_watch_on_an_ignored_cpu_says_so_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from test_watches import _watching

    ses = _watching(monkeypatch, tmp_path)
    ses.ignoring = [":maincpu"]
    out = s.watch_add(ref="FRAME_LO", mode="change", length=4, fmt="u32")
    assert out["cpu"] == ":maincpu" and "ignores :maincpu" in out["note"], out


def test_a_typed_focus_that_ignores_a_cpu_mame_is_not_live_on_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Measured live: after a stop on the sub cpu and an `Hc` back to the main one, a typed
    `focus subcpu` ignores the main cpu, which is visible but not live, so nothing runs and the
    visible cpu stays an ignored one. The stub's `?` names the cpu MAME is live on."""
    ses = _patched(monkeypatch, tmp_path)
    ses.live = ":subcpu"
    out = s.debug(command="focus subcpu")
    assert (out["visible_cpu"], out["ignored"]) == (":maincpu", [":maincpu"]), out
    assert "is ignored and was not live, so nothing ran" in out["note"], out
    assert "?" in ses.commands


def test_a_typed_focus_reads_the_visible_cpu_once_the_run_it_released_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A typed `focus` waits for the same stop the tool's console path does."""
    _running(monkeypatch, tmp_path)
    readings = itertools.chain([":maincpu", ":maincpu"], itertools.repeat(":subcpu"))
    # before the line, during the run, then after it for good
    monkeypatch.setattr(cpus, "visible_cpu", lambda ses: next(readings))
    monkeypatch.setattr(mfocus, "SETTLE_POLL_S", 0.0)
    out = s.debug(command="focus subcpu")
    assert out["visible_cpu"] == ":subcpu" and "ran until :subcpu executed" in out["note"], out


def test_a_typed_ignore_of_the_live_cpu_waits_for_it_to_leave_though_the_visible_one_is_observed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """After an `Hc` the visible cpu is not the live one, so a line ignoring the live cpu runs
    the machine while `cpulist` already marks a cpu it observes: the stop is the live cpu
    leaving the ignored set, read off the stub's `?`."""
    ses = _patched(monkeypatch, tmp_path)
    ses.visible_cpu = ":subcpu"
    asked: list[str] = []
    lives = itertools.chain([":maincpu", ":maincpu", ":maincpu"], itertools.repeat(":subcpu"))
    # before the line, during the run twice, then after it for good

    def live_cpu(ses: object) -> str:
        asked.append(next(lives))
        return asked[-1]

    monkeypatch.setattr(cpus, "live_cpu", live_cpu)
    monkeypatch.setattr(mfocus, "SETTLE_POLL_S", 0.0)
    out = s.debug(command="focus subcpu")
    assert out["visible_cpu"] == ":subcpu" and "ran until :subcpu executed" in out["note"], out
    assert asked[-1] == ":subcpu", f"the wait ended while the live cpu was ignored: {asked}"


def test_the_consoles_focus_waits_for_a_stop_on_a_cpu_it_observes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The tool's console path reads the visible cpu only once the run left the cpus the line
    ignored: a `cpulist` still marking the ignored one is the run going on."""
    _running(monkeypatch, tmp_path)
    readings = iter([":maincpu", ":maincpu", ":maincpu", ":subcpu", ":subcpu"])
    monkeypatch.setattr(cpus, "visible_cpu", lambda ses: next(readings))
    monkeypatch.setattr(mfocus, "SETTLE_POLL_S", 0.0)
    out = s.focus(cpu="subcpu")
    assert out["status"] == "ok" and out["cpu"] == ":subcpu" and out["machine_ran"] is True, out


def test_a_typed_focus_whose_run_reaches_no_observed_cpu_leaves_the_session_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mfocus, "settled_visible", lambda ses, ignored: None)
    out = s.debug(command="focus subcpu")
    assert "running" not in out, out
    assert out["session"]["running"] is True and out["visible_cpu"]["available"] is False, out
    assert "no stop was read" in out["note"] and ses.running and mstate.STATE.console_run


def test_a_visible_cpu_unread_before_the_call_is_said_in_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`cpulist` marking no cpu visible before the call leaves `was` unread: it says so in its
    place rather than answering a null."""
    _patched(monkeypatch, tmp_path)
    monkeypatch.setattr(cpus, "visible_cpu", _first_none(cpus.visible_cpu))
    out = s.focus(cpu="subcpu")
    assert out["status"] == "ok" and out["was"] == {"available": False,
                                                    "why": mfocus.NO_WAS_WHY}, out


def _first_none(real: Any) -> Any:
    """`visible_cpu` answering None once, then as the double does."""
    calls = {"n": 0}

    def visible(ses: Any) -> Any:
        calls["n"] += 1
        return None if calls["n"] == 1 else real(ses)
    return visible
