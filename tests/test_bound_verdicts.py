"""A WAIT ANSWERS A VERDICT, in run_for's words: `TARGET` when what it waited for came,
`TIMEOUT` when its bound ran out, `OTHER_STOP` when a stop it did not ask for ended it, all
`status: ok`. A refusal is kept for an action that could not finish (`wait_stopped`: a stopped
machine logs nothing). A wait nobody asked for (`resume` with 0, `settle_seconds=0`) carries no
verdict, and no boolean restates one (`halted`, a tail's `still_running` once it waited).
A survey's `cause` is prose that never repeats the verdict, and `close` says how it ended in
`ended_by`.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server_support import _running  # noqa: E402
from test_perform import FRAME_STEP, _frames_and_the_watch  # noqa: E402

import mame_running as running  # noqa: E402
import mame_sequence as sequence  # noqa: E402
import server as s  # noqa: E402


def test_log_wait_answers_target_when_the_line_comes_and_timeout_when_the_bound_runs_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    (tmp_path / "error.log").write_text("boot\n")
    s.resume()

    def later() -> None:
        time.sleep(0.15)
        with open(tmp_path / "error.log", "a") as fh:
            fh.write("scene 3 drawn\n")

    t = threading.Thread(target=later)
    t.start()
    found = s.log_wait(pattern="scene", channel="emulator", seconds=2.0)
    t.join()
    assert found["status"] == "ok" and found["verdict"] == "TARGET", found
    out = s.log_wait(pattern="zzz", channel="emulator", seconds=0.3)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert "code" not in out and "line" not in out and ses.running, out
    assert out["pattern"] == "zzz" and out["arrived_during"] == 0 and out["waited_s"] >= 0.3
    assert "TIMEOUT" in out["summary"], out["summary"]


def test_resume_carries_a_verdict_only_when_it_waited(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(running, "RESUME_POLL_S", 0.0)
    free = s.resume()
    assert "verdict" not in free and "halted" not in free and free["session"]["running"], free
    ses.running = False
    expired = s.resume(seconds=0.05)
    assert expired["verdict"] == "TIMEOUT" and "halted" not in expired, expired
    assert expired["session"]["running"] is True and "TIMEOUT" in expired["summary"], expired
    ses.running = False
    ses.stops_after_polls = 2
    stopped = s.resume(seconds=2.0)
    assert stopped["verdict"] == "OTHER_STOP" and "halted" not in stopped, stopped
    assert stopped["session"]["running"] is False and "regs" in stopped, stopped
    assert "OTHER_STOP" in stopped["summary"], stopped["summary"]


def test_perform_answers_timeout_when_a_settle_wait_runs_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Before a console step and at the tail: the list ends there, `ok`, the steps done
    counted, and no `still_running` restating the verdict."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    s.breakpoint_at(ref="0x4a0")              # something declared, so the waits wait
    out = s.perform(steps=[{"op": "resume"}, {"op": "registers"}], settle_seconds=0.05)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert out["steps_completed"] == 1 and "still_running" not in out and ses.running, out
    ses.running = False
    out = s.perform(steps=[{"op": "resume"}], settle_seconds=0.05)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert "still_running" not in out and "TIMEOUT" in out["summary"], out


def test_perform_answers_target_when_its_wait_met_the_stop_and_nothing_when_none_was_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    s.breakpoint_at(ref="0x4a0")
    ses.stops_after_polls = 2
    out = s.perform(steps=[{"op": "resume"}], settle_seconds=2.0)
    assert out["status"] == "ok" and out["verdict"] == "TARGET" and "stopped" in out, out
    ses.running = False
    out = s.perform(steps=[{"op": "resume"}], settle_seconds=0)
    assert "verdict" not in out and out["still_running"] is True, out
    ses.running = False
    out = s.perform(steps=[{"op": "status"}])
    assert "verdict" not in out, "a list that waited for nothing has nothing to judge"
    # A STOP ALREADY THERE is still no wait asked for with `settle_seconds` 0.
    ses.running = False
    ses.stops_after_polls = 1
    out = s.perform(steps=[{"op": "resume"}, {"op": "registers"}], settle_seconds=0)
    assert out["status"] == "ok" and out["steps_completed"] == 2, out
    assert "verdict" not in out, out


def test_perform_until_frame_answers_target_or_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frames_and_the_watch(monkeypatch, tmp_path)
    out = s.perform(steps=[FRAME_STEP], summaries=True, until_frame=ses.frame + 2)
    assert out["status"] == "ok" and out["verdict"] == "TARGET", out
    monkeypatch.setattr(sequence, "UNTIL_SECONDS_MAX", 0.0)
    out = s.perform(steps=[FRAME_STEP], summaries=True, until_frame=ses.frame + 5)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert "code" not in out and "frame_reached" in out, out
    assert "None" not in out["summary"], out["summary"]


def test_drive_puts_its_check_in_a_verdict_and_an_act_that_ran_out_verifies_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    (tmp_path / "error.log").write_text("boot\n")
    monkeypatch.setattr(sequence, "DRIVE_POLL_S", 0.0)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)
    ses.running = True
    out = s.drive(act=[{"op": "status"}], expect="never", seconds=0.2)
    assert out["status"] == "ok" and out["verify"]["verdict"] == "TIMEOUT", out
    assert "code" not in out, out
    def later() -> None:
        time.sleep(0.05)
        with open(tmp_path / "error.log", "a") as fh:
            fh.write("scene 3 drawn\n")

    writer = threading.Thread(target=later)
    writer.start()
    out = s.drive(act=[{"op": "status"}], expect="scene", seconds=2.0)
    writer.join()
    assert out["status"] == "ok" and out["verify"]["verdict"] == "TARGET", out
    s.breakpoint_at(ref="0x4a0")
    out = s.drive(act=[{"op": "registers"}], settle_seconds=0.05)
    assert out["status"] == "ok" and out["act"]["verdict"] == "TIMEOUT", out
    assert out["verify"]["available"] is False and out["verify"]["why"], out["verify"]
    assert out["verify"]["checked"] is False, "every verify says whether a check ran"
    # A stopped machine logs nothing: still the refusal it was.
    ses.running = False
    out = s.drive(act=[{"op": "registers"}], expect="never")
    assert out["status"] == "INVALID" and out["code"] == "wait_stopped", out


def test_a_list_that_waited_mid_way_and_ends_running_carries_no_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`TARGET` says every wait the list made ended at a stop; a list that waited mid-way and
    then ended with the machine running, nothing declared to stop it, is `still_running` and
    carries no verdict."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    ses.stops_after_polls = 2                    # the first resume's stop lands a moment later
    out = s.perform(steps=[{"op": "resume"}, {"op": "registers"}, {"op": "resume"},
                           {"op": "status"}], settle_seconds=2.0)
    assert out["status"] == "ok" and out.get("still_running") is True, out
    assert "verdict" not in out, out
