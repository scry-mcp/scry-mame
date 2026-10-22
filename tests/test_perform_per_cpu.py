"""`perform` and `drive` over several cpus: every step's `cpu` is judged against the machine before
any step runs, each step's account names the cpu its reply names, and a list that alternates cpus
leaves the visible cpu where it found it unless a step asked for another.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_server import _running, _RunningSession  # noqa: E402

import gdb_session as g  # noqa: E402
import mame_sequence as sequence  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

MAIN, SUB = ":maincpu", ":subcpu"


def _patched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _RunningSession:
    ses = _running(monkeypatch, tmp_path)
    ses.threads = {1: MAIN, 2: SUB}
    return ses


def _stops_on_the_sub(monkeypatch: pytest.MonkeyPatch, ses: _RunningSession) -> None:
    """MAME makes the stopping cpu the visible one: every stop of the double lands on the sub."""
    real = ses._stop

    def stop() -> None:
        real()
        ses.visible_cpu = SUB

    monkeypatch.setattr(ses, "_stop", stop)


# ------------------------------------------------------------------------ B7.1: the steps


def test_a_cpu_the_machine_lacks_refuses_the_whole_list_before_any_step_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    out = s.perform(steps=[
        {"op": "breakpoint_at", "ref": "0x4a0"},
        {"op": "registers", "cpu": "audiocpu"},
        {"op": "read_memory", "ref": "0x0", "length": 2, "cpu": ":nosuchcpu"},
        {"op": "registers", "cpu": "subcpu"},
    ])
    assert out["status"] == "INVALID" and out["code"] == "unknown_ref", out
    assert [e["step"] for e in out["errors"]] == [1, 2], out["errors"]
    assert out["cpu_tags"] == [MAIN, SUB] and out["steps_completed"] == 0 and out["ran"] == []
    assert "Nothing was run" in out["message"] and "visible_cpu" not in out
    assert "visible_cpu_kept" not in out, out
    assert ses.armed == [] and not any(c.startswith("bp ") for c in ses.commands), ses.commands


def test_drive_refuses_a_cpu_the_machine_lacks_in_its_own_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    out = s.drive(act=[{"op": "breakpoint_at", "ref": "0x4a0"}, {"op": "focus", "cpu": "audiocpu"}])
    assert out["code"] == "unknown_ref" and out["cpu_tags"] == [MAIN, SUB], out
    assert out["act"]["failed_at"] == 1 and out["verify"]["checked"] is False
    assert out["looked"]["emulator"]["available"] is False
    assert ses.armed == [], "nothing ran"


def test_each_steps_account_names_the_cpu_its_reply_names_and_a_brief_keeps_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _patched(monkeypatch, tmp_path)
    steps = [{"op": "breakpoint_at", "ref": "0x542", "cpu": "subcpu"},
             {"op": "breakpoint_at", "ref": "0x4a0"},
             {"op": "state_list"}]
    out = s.perform(steps=steps)
    assert [r.get("cpu") for r in out["ran"]] == [SUB, MAIN, None], out["ran"]
    assert "cpu" not in out["ran"][2], "a reply that names no cpu adds none"
    s.breakpoint_clear(all=True)
    out = s.perform(steps=steps, summaries=True)
    assert [r.get("cpu") for r in out["ran"]] == [SUB, MAIN, None], out["ran"]
    assert set(out["ran"][0]["reply"]) == {"summary", "status"}


# ------------------------------------------------ B7.2: the visible cpu across the list


def test_a_stop_on_another_cpu_inside_the_list_is_put_back_and_said(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    _stops_on_the_sub(monkeypatch, ses)
    ses.stops_after_polls = 1
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x542", "cpu": "subcpu"},
                           {"op": "resume"}, {"op": "registers"}])
    assert out["status"] == "ok", out
    assert out["ran"][2]["cpu"] == SUB, "the stop made the sub visible, as MAME does"
    assert out["visible_cpu_kept"] == {"before": MAIN, "moved_to": SUB, "after": MAIN,
                                  "restored": True}, out["visible_cpu_kept"]
    assert ses.visible_cpu == MAIN and "Hc1" in ses.commands, ses.commands


def test_the_last_focus_step_is_the_cpu_the_list_keeps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "focus", "cpu": "subcpu"}, {"op": "registers"}])
    assert out["ran"][1]["cpu"] == SUB, out["ran"]
    assert out["visible_cpu_kept"] == {"before": MAIN, "asked": SUB, "after": SUB,
                                  "restored": False}, out["visible_cpu_kept"]
    # A stop on the main after the focus is undone, back to the cpu the focus asked for.
    real = ses._stop

    def stops_on_the_main() -> None:
        real()
        ses.visible_cpu = MAIN

    monkeypatch.setattr(ses, "_stop", stops_on_the_main)
    ses.visible_cpu, ses.stops_after_polls = MAIN, 1
    out = s.perform(steps=[{"op": "focus", "cpu": "subcpu"},
                           {"op": "breakpoint_at", "ref": "0x4a0", "cpu": "maincpu"},
                           {"op": "resume"}])
    assert out["visible_cpu_kept"] == {"before": MAIN, "asked": SUB, "moved_to": MAIN, "after": SUB,
                                  "restored": True}, out["visible_cpu_kept"]


def test_a_failed_list_still_puts_the_visible_cpu_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    _stops_on_the_sub(monkeypatch, ses)
    ses.stops_after_polls = 1
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x542", "cpu": "subcpu"},
                           {"op": "resume"}, {"op": "read_memory", "ref": "nosuchname",
                                              "length": 2}])
    assert out["code"] == "step_failed" and out["failed_at"] == 2, out
    assert out["visible_cpu_kept"]["restored"] is True and ses.visible_cpu == MAIN


def test_a_build_that_cannot_show_a_cpu_without_running_says_why_it_did_not_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)               # no thread patch: no `Hc`
    _stops_on_the_sub(monkeypatch, ses)
    ses.stops_after_polls = 1
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x542", "cpu": "subcpu"},
                           {"op": "resume"}])
    kept = out["visible_cpu_kept"]
    assert kept["restored"] is False and kept["after"] == SUB, kept
    assert "no thread patch" in kept["why"] and ses.visible_cpu == SUB


def test_a_list_left_running_keeps_no_visible_cpu_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _patched(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "resume"}], settle_seconds=0)
    assert out["still_running"] and out["visible_cpu_kept"]["restored"] is False, out
    assert "running" in out["visible_cpu_kept"]["why"]


def test_a_board_of_one_cpu_answers_as_it_did(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "cpus", [MAIN])
    before = len(ses.commands)
    out = s.perform(steps=[{"op": "state_list"}])
    assert out["status"] == "ok" and "visible_cpu" not in out, out
    assert "visible_cpu_kept" not in out, out
    assert "cpulist" not in ses.commands[before:], "nothing read for a cpu there is no other of"


def test_a_put_back_the_stub_does_not_answer_keeps_the_account_of_the_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    _stops_on_the_sub(monkeypatch, ses)
    ses.stops_after_polls = 1

    def times_out(thread: int) -> None:
        raise g.Timeout(f"no answer to Hc{thread:x}")

    monkeypatch.setattr(ses, "make_visible", times_out)
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x542", "cpu": "subcpu"},
                           {"op": "resume"}])
    assert out["steps_completed"] == 2 and len(out["ran"]) == 2, out
    kept = out["visible_cpu_kept"]
    assert kept["restored"] is False and "no answer to Hc1" in kept["why"], kept


def test_a_put_back_is_restored_only_when_the_cpu_reads_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    _stops_on_the_sub(monkeypatch, ses)
    ses.stops_after_polls = 1
    monkeypatch.setattr(ses, "make_visible", lambda thread: None)     # taken, moves nothing
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x542", "cpu": "subcpu"},
                           {"op": "resume"}])
    kept = out["visible_cpu_kept"]
    assert kept["restored"] is False and kept["after"] == SUB, kept
    assert "read back" in kept["why"], kept


def _ops(**replies: dict[str, object]) -> dict[str, object]:
    """Operations answering fixed replies, one per op, each taking any argument."""
    def answering(reply: dict[str, object]) -> object:
        return lambda **_: {"status": "ok", **reply}

    return {op: answering(reply) for op, reply in replies.items()}


def test_a_debug_line_that_shows_a_cpu_is_the_cpu_kept_and_one_that_read_none_is_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    ops = _ops(debug={"visible_cpu": SUB}, focus={"cpu": SUB})
    out = sequence.run_steps(ses, tmp_path, [{"op": "debug", "command": "focus subcpu"}], 1.0,
                             ops)  # type: ignore[arg-type]
    kept = out["visible_cpu_kept"]
    assert kept["asked"] == SUB and ses.visible_cpu == SUB, kept
    ses.visible_cpu = MAIN
    ops = _ops(debug={"visible_cpu": {"available": False, "why": "none read"}},
               focus={"cpu": SUB})
    out = sequence.run_steps(ses, tmp_path, [{"op": "focus", "cpu": "subcpu"},
                                             {"op": "debug", "command": "ignore"}], 1.0,
                             ops)  # type: ignore[arg-type]
    assert out["visible_cpu_kept"]["asked"] == SUB, "an unread visible cpu does not undo the focus"


def test_a_reply_whose_cpu_is_unknown_adds_none_to_the_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _patched(monkeypatch, tmp_path)
    out = sequence.run_steps(ses, tmp_path, [{"op": "registers"}], 1.0,
                             _ops(registers={"cpu": {"available": False,
                                                     "why": "none read"}}))  # type: ignore[arg-type]
    assert "cpu" not in out["ran"][0], out["ran"]


def test_a_list_begun_on_a_running_machine_has_no_cpu_to_keep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _patched(monkeypatch, tmp_path)
    s.resume()
    out = s.perform(steps=[{"op": "stop"}])
    kept = out["visible_cpu_kept"]
    assert kept["before"]["available"] is False and "began" in kept["why"] and "after" in kept, kept


def test_a_visible_cpu_unread_after_the_list_is_not_put_back_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import mame_cpus as cpus

    ses = _patched(monkeypatch, tmp_path)
    reads = iter([MAIN, None])
    monkeypatch.setattr(cpus, "visible_cpu", lambda s_: next(reads))
    out = s.perform(steps=[{"op": "state_list"}])
    kept = out["visible_cpu_kept"]
    assert kept["after"]["available"] is False and kept["restored"] is False, kept
    assert "marked no cpu" in kept["why"] and "Hc1" not in ses.commands, kept
