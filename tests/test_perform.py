"""`perform`: a list of the server's own operations, run in order, in ONE call: checked whole
before the first runs, stopped at the first INVALID, with the account of what ran."""

from __future__ import annotations

import dataclasses
import re
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from scry_core import (
    frame_window,  # noqa: E402
    sequence_account,  # noqa: E402
)
from scry_core import progress as mprogress  # noqa: E402
from scry_core import steps as step_judge  # noqa: E402
from scry_core import vocabulary as vocab
from scry_core.reply_contract import unavailable  # noqa: E402
from server_support import _running  # noqa: E402
from session_doubles import refused  # noqa: E402
from test_watches import STOP_LINE, _watching  # noqa: E402

from scry_mame import (
    advance,  # noqa: E402
    read,  # noqa: E402
    running,  # noqa: E402
    sequence,  # noqa: E402
)
from scry_mame import envelope as menvelope  # noqa: E402
from scry_mame import gdb_session as gs  # noqa: E402
from scry_mame import lua as mlua  # noqa: E402
from scry_mame import mcp as mame_mcp  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


def test_the_tool_is_registered_and_the_vocabulary_is_every_tool_but_the_lifecycle() -> None:
    names = {t.name for t in s.mcp._tool_manager.list_tools()}
    assert "perform" in names
    ops = set(s._step_ops())
    assert ops == names - {"start", "close", "rom_check", "perform", "drive",
                           "perform_export", "window", "promote"}, ops ^ names


def test_perform_runs_steps_in_order_and_stops_at_the_first_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = s.perform(steps=[
        {"op": "breakpoint_at", "ref": "0x4a0"},
        {"op": "breakpoint_at", "ref": "0x4a0", "role": "control"},
        {"op": "breakpoint_at", "ref": "0x25a4"},
    ])
    assert out["status"] == "INVALID" and out["code"] == "step_failed"
    assert out["failed_at"] == 1 and out["steps_completed"] == 1
    assert [r["op"] for r in out["ran"]] == ["breakpoint_at"]
    assert out["failed"]["op"] == "breakpoint_at" and "already declared" in out["message"]
    assert ses.armed == [(0x4A0, False)], "the third step never armed"


def test_perform_checks_every_step_before_any_step_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "resume"}, {"op": "warp_core"},
                           {"op": "status", "bogus": 1}, {"op": "status", "ctx": 1},
                           {"op": "log", "pattern": "(", "channel": "emulator"},
                           {"op": "run_for", "milliseconds": 0},
                           {"op": "watch_add", "ref": "0x4a0", "mode": "poll", "length": 2},
                           {"op": "breakpoint_at", "ref": "0x4a0", "role": "counter"},
                           {"op": "step", "count": 0},
                           "registers"])
    assert out["status"] == "INVALID" and out["steps_completed"] == 0 and out["ran"] == []
    assert out["failed_at"] == 1
    assert not ses.running, "the resume never went out: the list was refused whole"
    refused = {(e["step"], e["code"]) for e in out["errors"]}
    assert refused == {(1, "bad_argument"), (2, "bad_argument"), (3, "bad_argument"),
                       (4, "bad_argument"), (5, "bad_argument"), (6, "bad_argument"),
                       (7, "bad_argument"), (8, "bad_argument"), (9, "bad_argument")}
    messages = {e["step"]: e["message"] for e in out["errors"]}
    assert "not a step" in messages[1] and "operations" in messages[1], "points at the vocabulary"
    assert "resume" in out["operations"] and "registers" in out["operations"], (
        "the vocabulary is named once, as a field, not inside every copy of the message")
    assert "bad arguments" in messages[2] and "`ctx`" in messages[3]
    assert "does not compile" in messages[4]
    assert "exactly one of `milliseconds` and `frames`" in messages[5]
    assert "mode" in messages[6] and "role" in messages[7] and "count=0" in messages[8]
    assert "not a" in messages[9]


def test_summaries_cut_every_step_but_the_last_to_its_summary_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With `summaries`, each earlier step keeps its `summary` and `status`; the last keeps its
    whole reply."""
    _running(monkeypatch, tmp_path)
    steps = [{"op": "breakpoint_at", "ref": "0x4a0"}, {"op": "declaration_list",
                                                       "kind": "breakpoint"},
             {"op": "registers"}]
    full = s.perform(steps=steps)
    assert full["status"] == "ok" and full["steps_completed"] == 3
    assert all("summary" in r["reply"] and len(r["reply"]) > 2 for r in full["ran"]), (
        "the control: without the flag every step carries its whole reply")
    s.declaration_clear("breakpoint", all=True)
    out = s.perform(steps=steps, summaries=True)
    assert out["status"] == "ok" and out["steps_completed"] == 3, out
    assert out["failed_at"]["available"] is False, out
    assert [set(r["reply"]) for r in out["ran"][:2]] == [{"summary", "status"}] * 2, out["ran"]
    assert out["ran"][0]["reply"]["summary"].startswith("breakpoint_at 0x4a0: armed")
    assert out["ran"][0]["reply"]["status"] == "ok"
    assert [r["op"] for r in out["ran"]] == ["breakpoint_at", "declaration_list", "registers"]
    assert "regs" in out["ran"][2]["reply"], "the last step keeps its whole reply"
    refused("true or false", s.perform(steps=steps, summaries="yes"))


def test_each_row_carries_the_frames_it_ran_for_and_a_summary_keeps_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A timeline places each step it shows by the frames that step ran for: every row carries
    them, and the compact `summaries` row keeps them."""
    _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "frame_symbol", "frame", raising=False)
    full = s.perform(steps=[{"op": "status"}])
    assert [(r["frame_before"], r["frame_after"]) for r in full["ran"]] == [(100, 100)]
    out = s.perform(steps=[{"op": "status"}], summaries=True)
    assert [(r["frame_before"], r["frame_after"]) for r in out["ran"]] == [(100, 100)]


def test_perform_says_on_its_line_how_many_steps_ran_and_where_the_list_ended(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The line carries the count of steps completed and the tail: the stop it was heading for, or
    still running."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x4a0"}, {"op": "registers"}])
    assert out["summary"] == "perform: 2 steps completed", out["summary"]
    ses.pcs = [0xF2034, 0x4A0]
    ses.stops_after_polls = 2
    out = s.perform(steps=[{"op": "resume"}], settle_seconds=2.0)
    assert out["stopped"]["pc"] == "0x000004a0"
    assert out["summary"].startswith(
        "perform: 1 step completed, TARGET, stopped at pc 0x000004a0 (breakpoint"), out["summary"]
    ses.running = False
    out = s.perform(steps=[{"op": "resume"}], settle_seconds=0)
    assert out["still_running"] is True
    assert out["summary"] == "perform: 1 step completed, still running", out["summary"]
    ses.running = False
    out = s.perform(steps=[{"op": "registers"}, {"op": "warp_core"}])
    assert out["summary"].startswith("perform: INVALID (bad_argument), 1 step refused"), out


def test_a_registerpoint_alone_is_something_the_machine_can_stop_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A registerpoint alone is something that can stop the machine, so the tail waits and says so
    when the bound runs out."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.perform(steps=[{"op": "resume"}, {"op": "status"}], settle_seconds=0.05)
    assert out["still_running"] is True and "no registerpoint" in out["note"], out["note"]
    ses.running = False
    monkeypatch.setattr(mstate.STATE, "regpoints",
                        {"d1==7fff": {"index": 1, "cpu": ":maincpu", "condition": "d1==7fff"}})
    out = s.perform(steps=[{"op": "resume"}, {"op": "status"}], settle_seconds=0.05)
    assert out["verdict"] == "TIMEOUT" and "still_running" not in out, out
    assert "did not stop" in out["note"] and "nothing declared" not in out["note"]


def test_a_failure_in_the_middle_keeps_its_own_reply_whole_and_briefs_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A failed list keeps the failing step's reply whole under `failed` and briefs the steps
    before it."""
    _running(monkeypatch, tmp_path)
    out = s.perform(steps=[
        {"op": "breakpoint_at", "ref": "0x4a0"},
        {"op": "declaration_list", "kind": "breakpoint"},
        {"op": "breakpoint_at", "ref": "0x4a0", "role": "control"},
        {"op": "registers"},
    ], summaries=True)
    assert out["status"] == "INVALID" and out["code"] == "step_failed" and out["failed_at"] == 2
    assert out["steps_completed"] == 2
    assert [set(r["reply"]) for r in out["ran"]] == [{"summary", "status"}] * 2, out["ran"]
    assert out["failed"]["op"] == "breakpoint_at"
    assert "already declared" in out["failed"]["reply"]["message"], out["failed"]
    assert out["failed"]["reply"]["code"] == "ambiguous_ref", out["failed"]


def test_perform_refuses_a_wait_that_is_not_a_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    for bad in (-1, 601):
        out = s.perform(steps=[{"op": "status"}], settle_seconds=bad)
        assert out["status"] == "INVALID" and "bound" in out["message"]


def test_perform_waits_for_the_stop_before_a_console_step_after_a_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x4A0]
    ses.stops_after_polls = 3
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.perform(steps=[{"op": "resume"}, {"op": "status"}, {"op": "registers"}],
                    settle_seconds=2.0)
    assert out["status"] == "ok" and out["steps_completed"] == 3, out
    assert out["ran"][0]["reply"]["session"]["running"] is True
    assert out["ran"][2]["reply"]["regs"]["PC"] == f"{ses.pcs[0]:#010x}", out["ran"][2]["reply"]
    assert not ses.running and "stopped" not in out


def test_perform_names_a_machine_still_running_before_a_console_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.perform(steps=[{"op": "resume"}, {"op": "registers"}], settle_seconds=0.05)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert out["failed_at"]["available"] is False and out["steps_completed"] == 1 and ses.running
    assert "failed" not in out, "no step refused: the boundary is what could not be sent"
    assert "'registers' cannot be sent" in out["note"], out["note"]
    ses.running = False
    out = s.perform(steps=[{"op": "resume"}, {"op": "registers"}], settle_seconds=0)
    assert out["status"] == "INVALID" and out["code"] == "not_stopped", out
    assert out["failed_at"] == 1 and out["steps_completed"] == 1 and "verdict" not in out, out
    ses.running = False
    out = s.perform(steps=[{"op": "status"}, {"op": "resume"}, {"op": "registers"}],
                    settle_seconds=0.05,
                    summaries=True)
    assert out["verdict"] == "TIMEOUT" and out["steps_completed"] == 2, out
    assert set(out["ran"][0]["reply"]) == {"summary", "status"}
    assert out["ran"][1]["reply"]["session"]["running"] is True, out["ran"][1]


def test_drive_takes_summaries_by_the_same_rule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`drive`'s act takes `summaries` by the same rule."""
    _running(monkeypatch, tmp_path)
    out = s.drive(act=[{"op": "breakpoint_at", "ref": "0x4a0"}, {"op": "declaration_list",
                                                                 "kind": "breakpoint"},
                       {"op": "registers"}], summaries=True)
    assert out["status"] == "ok", out
    ran = out["act"]["ran"]
    assert [set(r["reply"]) for r in ran[:2]] == [{"summary", "status"}] * 2, ran
    assert "regs" in ran[2]["reply"]
    refused("true or false", s.drive(act=[{"op": "status"}], summaries=1))


def test_perform_tail_waits_for_the_stop_it_was_heading_for_and_surveys_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x4A0]
    ses.stops_after_polls = 2
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    s.breakpoint_at(ref="0x4a0")
    out = s.perform(steps=[{"op": "resume"}], settle_seconds=2.0)
    assert out["status"] == "ok" and out["steps_completed"] == 1
    assert out["stopped"]["pc"] == "0x000004a0" and out["stopped"]["cause"].startswith("breakpoint")
    assert not ses.running


def test_perform_tail_says_still_running_with_wait_zero_or_nothing_declared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.perform(steps=[{"op": "resume"}], settle_seconds=0)
    assert out["status"] == "ok" and out["still_running"] is True, out
    assert "settle_seconds=0" in out["note"], out
    assert ses.running
    ses.running = False
    out = s.perform(steps=[{"op": "resume"}, {"op": "status"}], settle_seconds=5.0)
    assert out["still_running"] is True and "nothing declared" in out["note"]
    ses.running = False
    out = s.perform(steps=[{"op": "resume"}], settle_seconds=0.05)
    assert out["verdict"] == "TIMEOUT" and "did not stop" in out["note"], out


def test_perform_a_running_ok_step_leaves_the_machine_as_it_found_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    (tmp_path / "error.log").write_text("boot\n")
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.perform(steps=[{"op": "resume"}, {"op": "log", "pattern": "boot",
                                                  "channel": "emulator"},
                           {"op": "status"}], settle_seconds=0)
    assert out["status"] == "ok" and out["steps_completed"] == 3 and out["still_running"] is True
    assert out["ran"][1]["reply"]["lines"] == ["boot"] and ses.running


def test_perform_goldens_shape_runs_to_markers_and_snapshots_in_one_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The batch a goldens run is: a control declared once, then `run_to` a marker and
    `snapshot`, twice, in one call, every step's reply in `ran`."""
    ses = _watching(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x4A0, 0x25A4]
    ses.stop_queue = [1, 1]
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 5

    ses.go = go  # type: ignore[method-assign]
    from scry_mame import files
    monkeypatch.setattr(files, "snapshot", lambda ses_, scratch, dest: menvelope.envelope(
        {"path": dest or "snap.png", "bytes": 7, "sha256": "0" * 64}))
    out = s.perform(steps=[
        {"op": "breakpoint_at", "ref": "0x600", "role": "control"},
        {"op": "run_to", "ref": "0x4a0", "control": "0x600", "seconds": 2.0},
        {"op": "snapshot", "dest": str(tmp_path / "scene1.png")},
        {"op": "run_to", "ref": "0x25a4", "control": "0x600", "seconds": 2.0},
        {"op": "snapshot", "dest": str(tmp_path / "scene2.png")},
    ], settle_seconds=2.0)
    assert out["status"] == "ok" and out["steps_completed"] == 5, out
    assert [r["op"] for r in out["ran"]] == ["breakpoint_at", "run_to", "snapshot", "run_to",
                                             "snapshot"]
    first = out["ran"][1]["reply"]
    assert first["verdict"] == "TARGET" and first["control_hits"] == 5
    assert out["ran"][3]["reply"]["verdict"] == "TARGET"
    assert out["ran"][4]["reply"]["path"].endswith("scene2.png")
    assert "stopped" not in out and not ses.running


#: A directory that EXISTS with names that do not: what `fresh_dest` asks for. Nothing here
#: writes a byte, because these rows exercise the CHECK and never the step.
_NEVER_WRITTEN = str(Path(tempfile.gettempdir()) / "mame-perform-check")


@pytest.mark.parametrize("op,bad,good", [
    ("log", {"pattern": "(", "channel": "emulator"}, {"pattern": ".", "channel": "all"}),
    ("log", {"pattern": ".", "channel": "guest"}, {"pattern": ".", "channel": "process"}),
    ("log", {"pattern": ".", "channel": "emulator", "limit": 0},
     {"pattern": ".", "channel": "emulator", "limit": 5}),
    ("log_wait", {"pattern": ".", "channel": "emulator", "seconds": 0},
     {"pattern": ".", "channel": "emulator", "seconds": 3}),
    ("log_wait", {"pattern": "[", "channel": "emulator"}, {"pattern": "x", "channel": "all"}),
    ("run_to", {"ref": "", "control": "0x25a4"}, {"ref": "0x4a0", "control": "0x25a4"}),
    ("run_to", {"ref": "0x4a0", "control": ""}, {"ref": "0x4a0", "control": "0x25a4"}),
    ("run_to", {"ref": "0x4a0", "control": "0x25a4", "seconds": 0},
     {"ref": "0x4a0", "control": "0x25a4", "seconds": 1}),
    ("run_for", {"milliseconds": 10, "frames": 2}, {"frames": 2}),
    ("run_for", {"frames": 2, "seconds": 0}, {"milliseconds": 10}),
    ("step", {"count": 0}, {"count": 3}),
    ("resume", {"seconds": -1}, {"seconds": 0}),
    ("breakpoint_at", {"ref": "0x4a0", "by": "guess"}, {"ref": "0x4a0", "by": "address"}),
    ("breakpoint_at", {"ref": "0x4a0", "role": "x"}, {"ref": "0x4a0", "role": "control"}),
    ("watch_add", {"ref": "4a0", "mode": "show", "by": "expr"}, {"ref": "4a0", "mode": "show"}),
    ("watch_add", {"ref": "4a0", "mode": "show", "by": "guess"},
     {"ref": "0x4a0", "mode": "show", "by": "address"}),
    ("watch_add", {"ref": "0x4a0", "mode": "show", "fmt": "u64"},
     {"ref": "0x4a0", "mode": "show", "fmt": "u16[2]"}),
    ("watch_add", {"ref": "beamy", "mode": "expr", "fmt": "u64"}, {"ref": "beamy", "mode": "expr"}),
    ("read_memory", {"ref": "0x4a0", "length": 0}, {"ref": "0x4a0", "length": 8}),
    ("disassemble", {"ref": "0x4a0", "length": 99999}, {"ref": "0x4a0"}),
    ("memdump", {"ref": "0x4a0", "length": 0, "dest": f"{_NEVER_WRITTEN}-a.bin"},
     {"ref": "0x4a0", "length": 8, "dest": f"{_NEVER_WRITTEN}-b.bin"}),
    ("memdump", {"ref": "0x4a0", "length": 8, "dest": "relative.bin"},
     {"ref": "0x4a0", "length": 8, "dest": f"{_NEVER_WRITTEN}-c.bin"}),
    ("write", {"ref": "0x4a0", "data_hex": "abc"}, {"ref": "0x4a0", "data_hex": "abcd"}),
    ("set_register", {"name": "d0", "value": "1"}, {"name": "d0", "value": 1}),
])
def test_every_value_check_refuses_its_bad_value_and_passes_its_good_one(
    op: str, bad: dict[str, object], good: dict[str, object],
) -> None:
    """One bad value and one good one per registry entry: the bad raises the tool's own refusal,
    the good passes."""
    with pytest.raises(mstate.Invalid):
        sequence.BY_OP[op](**bad)
    sequence.BY_OP[op](**good)


def test_perform_dispatches_throttle_on_a_running_machine_without_waiting_for_a_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`throttle` answers while the machine runs, from the one list the server's refusal also
    reads."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mlua, "throttle",
                        lambda ses_, scratch, on, seconds, progress: menvelope.envelope(
                            {"on": on, "pending": False, "frame": 1, "waited_s": 0.0,
                             "tag": "MAME_MCP_THROTTLE#1"}))
    out = s.perform(steps=[{"op": "resume"}, {"op": "throttle", "on": False}], settle_seconds=0.05)
    assert out["status"] == "ok" and out["steps_completed"] == 2, out
    assert out["ran"][1]["reply"]["pending"] is False and ses.running
    assert "throttle" in mame_mcp._ANSWERS_WHILE_RUNNING and "throttle" in sequence.RUNNING_OK_OPS
    monkeypatch.setattr(sequence, "GATE", dataclasses.replace(
        sequence.GATE, ops=sequence.GATE.ops - {"throttle"}))
    ses.running = False
    out = s.perform(steps=[{"op": "resume"}, {"op": "throttle", "on": False}], settle_seconds=0.05)
    assert out["verdict"] == "TIMEOUT" and out["steps_completed"] == 1, out


def test_a_step_with_a_value_of_the_wrong_type_is_refused_naming_the_argument() -> None:
    """A string where an int belongs is refused before the session, naming the argument."""
    out = s.perform(steps=[{"op": "step", "count": 1},
                           {"op": "read_memory", "ref": "0x0", "length": "8"}])
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "step 2 ('read_memory') length is an integer; got '8'" in out["message"], out["message"]
    assert "not supported" not in out["message"]
    flag = s.perform(steps=[{"op": "step", "count": True}])
    assert "step 1 ('step') count is an integer; got True" in flag["message"], flag["message"]
    whole = s.perform(steps=[{"op": "step", "count": 1.0}])
    assert "step 1 ('step') count is an integer; got 1.0" in whole["message"], whole
    half = s.perform(steps=[{"op": "step", "count": 1.5}])
    assert "step 1 ('step') count is an integer; got 1.5" in half["message"], half["message"]


def test_a_wrong_type_after_an_argument_the_step_left_out_is_still_refused() -> None:
    """The check skips a parameter the step does not pass or whose annotation is not a plain
    scalar, and walks on."""
    out = s.perform(steps=[{"op": "run_for", "frames": "2"}])
    assert "step 1 ('run_for') frames is an integer; got '2'" in out["message"], out
    out = s.perform(steps=[{"op": "run_to", "ref": "x", "control": "y", "seconds": "5"}])
    assert "step 1 ('run_to') seconds is a number; got '5'" in out["message"], out


def test_a_sequences_wait_takes_its_ceiling_and_refuses_a_boolean_and_one_past_it() -> None:
    """The bound is 0..`WAIT_MAX_S` INCLUSIVE, and `True` is a mistake, not one second."""
    sequence.validate_settle(vocab.WAIT_MAX_S)
    sequence.validate_settle(0)
    for bad in (True, vocab.WAIT_MAX_S + 0.001, -0.001, "5"):
        with pytest.raises(mstate.Invalid, match=r"^settle_seconds=.* is not a bound"):
            sequence.validate_settle(bad)  # type: ignore[arg-type]


def test_drive_refused_before_the_machine_answers_the_documented_shape_whole() -> None:
    """The cold refusal of `drive` is one shape: the step named, the vocabulary once, `verify` and
    `looked` empty."""
    out = s.drive(act=[{"op": "status"}, {"op": "warp_core"}], pattern="COIN")
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "step 2 ('warp_core') is not a step" in out["message"], out["message"]
    assert "status" in out["operations"] and "warp_core" not in out["operations"], out
    assert out["act"]["steps_completed"] == 0 and out["act"]["failed_at"] == 1, out["act"]
    assert out["act"]["failed"]["op"] == "warp_core" == out["act"]["errors"][0]["op"], out["act"]
    assert out["verify"] == {"checked": False, "why": "the act was refused before anything ran"}
    assert out["looked"] == {"emulator": {"available": False,
                                          "why": sequence.NOTHING_LOOKED_WHY}}, out["looked"]
    named = s.drive(act=[{"op": "run_for", "frames": "2"}])
    assert "operations" not in named, "the vocabulary rides only on an op the server lacks"


def test_every_step_check_takes_what_its_tool_takes_with_the_same_defaults() -> None:
    """A check is called with a step's arguments, so a default the tool and the check spell
    differently is not judged."""
    import inspect
    ops = s._step_ops()
    for op, check in sequence.BY_OP.items():
        tool = {n: p for n, p in inspect.signature(ops[op]).parameters.items() if n != "ctx"}
        for name, param in inspect.signature(check).parameters.items():
            if param.kind is param.VAR_KEYWORD:
                continue
            assert name in tool, f"{op}: the check takes `{name}`, which the tool does not"
            if param.default is param.empty:
                assert tool[name].default is param.empty, (
                    f"{op}: the tool defaults `{name}` and the check requires it")
            elif tool[name].default is not param.empty:
                assert tool[name].default == param.default, (
                    f"{op}: `{name}` defaults to {tool[name].default!r} in the tool and "
                    f"{param.default!r} in the check")




def test_a_debug_that_releases_the_machine_ends_the_sequence_still_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`debug` is not a running-ok op, so its release reaches the tail the way `resume`'s does."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    monkeypatch.setattr(mstate.STATE, "console_writes", 0)
    out = s.perform(steps=[{"op": "debug", "command": "g"}], settle_seconds=0)
    assert out["status"] == "ok" and out["steps_completed"] == 1, out
    assert out["ran"][0]["reply"]["session"]["running"] is True
    assert out["still_running"] is True and "settle_seconds=0" in out["note"], out
    assert ses.running, "the machine the console released is still running"


def test_a_step_after_a_debug_release_waits_for_the_stop_instead_of_dispatching(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console step after a release needs a stopped machine; a run the console started sends no
    stop packet, so the proof is the frame counter at rest."""
    class _Frames:
        def __init__(self, stops_after: int | None) -> None:
            self.left = stops_after

        def at_rest(self) -> bool:
            if self.left is None:
                return False
            self.left -= 1
            return self.left < 0

    running_frames = _Frames(None)
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    monkeypatch.setattr(running, "frame_at_rest",
                        lambda ses_, reads=3, gap_s=0.1: running_frames.at_rest())
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    monkeypatch.setattr(mstate.STATE, "console_writes", 0)
    out = s.perform(steps=[{"op": "debug", "command": "g"}, {"op": "registers"}],
                    settle_seconds=0.05)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert out["failed_at"]["available"] is False and out["steps_completed"] == 1, out
    assert "'registers' cannot be sent" in out["note"], out["note"]
    ses.running, mstate.STATE.console_run = False, False
    running_frames = _Frames(2)
    out = s.perform(steps=[{"op": "debug", "command": "g"}, {"op": "registers"}],
                    settle_seconds=2.0)
    assert out["status"] == "ok" and out["steps_completed"] == 2, out
    assert "regs" in out["ran"][1]["reply"], out


def test_leaves_running_reads_the_reply_and_not_the_ops_name() -> None:
    """The unit behind both cases: the field, whoever wrote it."""
    assert sequence._leaves_running("debug", {"session": {"running": True}})
    assert sequence._leaves_running("resume", {"session": {"running": True}})
    assert not sequence._leaves_running("debug", {"session": {"running": False}})
    assert not sequence._leaves_running("debug", {"command": "print pc"})
    assert not sequence._leaves_running("run_for", {"verdict": "ELAPSED"})




def test_perform_ending_in_a_stop_that_halted_the_machine_has_no_running_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.perform(steps=[{"op": "resume"}, {"op": "stop"}], settle_seconds=5.0)
    assert out["status"] == "ok" and out["steps_completed"] == 2, out
    assert not ses.running and ses.interrupted == 1
    assert "still_running" not in out and "note" not in out, out
    stopped, stop_reply = out["stopped"], out["ran"][-1]["reply"]
    assert stopped["stop_seq"] == stop_reply["stop_seq"] and stopped["pc"] == stop_reply["pc"], (
        out)


def test_perform_ending_in_a_status_that_found_a_stop_has_no_running_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    ses.stops_after_polls = 1
    out = s.perform(steps=[{"op": "resume"}, {"op": "status"}], settle_seconds=5.0)
    assert out["status"] == "ok" and out["steps_completed"] == 2, out
    assert not ses.running
    assert "still_running" not in out and "note" not in out, out
    found = out["ran"][-1]["reply"]["stopped_on_its_own"]
    assert out["stopped"]["stop_seq"] == found["stop_seq"], (out["stopped"], found)


def test_perform_ending_in_a_status_over_a_running_machine_keeps_the_running_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control: still running with nothing able to stop it, the tail says so."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.perform(steps=[{"op": "resume"}, {"op": "status"}], settle_seconds=5.0)
    assert ses.running
    assert out["still_running"] is True and "nothing declared" in out["note"], out


def test_drive_whose_act_ends_in_a_stop_reports_no_running_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    log = tmp_path / "error.log"
    log.write_text("boot\n")
    go = ses.go

    def go_and_log() -> None:
        go()
        log.write_text("boot\nattract\n")

    monkeypatch.setattr(ses, "go", go_and_log)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.drive(act=[{"op": "resume"}, {"op": "stop"}], expect="attract")
    assert out["status"] == "ok", out
    assert not ses.running
    assert "still_running" not in out["act"] and "note" not in out["act"], out["act"]


def test_perform_ending_in_a_log_wait_the_machine_halted_during_has_no_running_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The third running-ok op that can find a stop: its line is logged as the machine halts."""
    ses = _running(monkeypatch, tmp_path)
    log = tmp_path / "error.log"
    log.write_text("boot\n")
    halt = ses._stop

    def halt_and_log() -> None:
        halt()
        log.write_text("boot\nhalted\n")

    monkeypatch.setattr(ses, "_stop", halt_and_log)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    ses.stops_after_polls = 1
    out = s.perform(steps=[{"op": "resume"}, {"op": "log_wait", "pattern": "halted",
                                                  "channel": "emulator", "seconds": 1.0}],
                    settle_seconds=5.0)
    assert out["status"] == "ok" and out["steps_completed"] == 2, out
    assert not ses.running
    assert "still_running" not in out and "note" not in out, out




def test_a_stop_breakpoint_or_a_change_watch_alone_makes_the_tail_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Each family on its own: a stop breakpoint, and a change watch, make the tail wait."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    s.breakpoint_at(ref="0x4a0")
    out = s.perform(steps=[{"op": "resume"}, {"op": "status"}], settle_seconds=0.05)
    assert out["verdict"] == "TIMEOUT" and "did not stop" in out["note"], out
    ses.running = False
    s.declaration_clear("breakpoint", all=True)
    monkeypatch.setattr(mstate.STATE, "armed_watches",
                        {("x", ":maincpu"): {"addr": 0x4A0, "length": 2}})
    out = s.perform(steps=[{"op": "resume"}, {"op": "status"}], settle_seconds=0.05)
    assert out["verdict"] == "TIMEOUT" and "did not stop" in out["note"], out


def test_the_progress_line_is_painted_while_a_sequence_or_a_verify_waits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Every bounded wait reports through the progress it was handed, with the bound in the line.
"""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)
    s.breakpoint_at(ref="0x4a0")
    ses.running = True
    lines: list[str] = []
    rec = lambda p, t, m: lines.append(m)  # noqa: E731
    assert sequence._wait_for_stop(ses, tmp_path, 0.05, rec) == "running"
    assert lines and "waiting for the machine to stop" in lines[-1] and "0.05s" in lines[-1]
    (tmp_path / "error.log").write_text("boot\n")
    lines.clear()
    checked = sequence._verify(ses, tmp_path, re.compile("never"), 0.05, 0, rec)
    assert checked["seen"] is False and "still running" in checked["why"]
    assert lines and "drive: waiting for 'never'" in lines[-1] and "0.05s" in lines[-1]
    ops = s._step_ops()
    ses.running = False
    lines.clear()
    out = sequence.run_steps(ses, tmp_path, [{"op": "resume"}, {"op": "registers"}], 0.05, ops,
                             progress=rec)
    assert out["verdict"] == "TIMEOUT" and lines, out
    ses.running = False
    lines.clear()
    out = sequence.run_steps(ses, tmp_path, [{"op": "resume"}], 0.05, ops, progress=rec)
    assert out["verdict"] == "TIMEOUT" and "did not stop" in out["note"] and lines, out
    ses.running = False
    lines.clear()
    out = sequence.drive(ses, tmp_path, ops, [{"op": "resume"}, {"op": "registers"}], "never",
                         0.05, ".", 40, 0.05, progress=rec)
    assert out["act"]["verdict"] == "TIMEOUT" and out["verify"]["available"] is False, out
    assert lines, out
    ses.running = False
    lines.clear()
    out = sequence.drive(ses, tmp_path, ops, [{"op": "resume"}], "never", 0.05, ".", 40, 0.05,
                         progress=rec)
    assert out["verify"]["verdict"] == "TIMEOUT" and lines, out


def test_the_verify_says_it_checked_whether_the_line_came_and_honours_its_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`checked` is whether a check ran, on both misses."""
    import time

    ses = _running(monkeypatch, tmp_path)
    (tmp_path / "error.log").write_text("boot\n")
    out = s.drive(act=[{"op": "registers"}], expect="never")
    assert out["code"] == "wait_stopped" and out["verify"]["checked"] is True, out["verify"]
    monkeypatch.setattr(sequence, "DRIVE_POLL_S", 0.0)
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)
    ses.running = True
    began = time.monotonic()
    out = s.drive(act=[{"op": "status"}], expect="never", seconds=0.2)
    assert out["status"] == "ok" and out["verify"]["verdict"] == "TIMEOUT", out
    assert out["verify"]["checked"] is True and "still running" in out["verify"]["why"], out
    assert out["verify"]["waited_s"] < 1.0 and time.monotonic() - began < 2.0


def test_the_polls_of_a_sequence_ask_the_socket_without_blocking_and_only_after_a_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stub's stop packet is polled with a bound of at most the poll interval, and only when a
    step released the machine."""
    ses = _running(monkeypatch, tmp_path)
    real = ses.poll_stop
    polls: list[float | None] = []

    def recording(timeout: float | None = 0.0) -> bool:
        polls.append(timeout)
        return real(0.0)

    monkeypatch.setattr(ses, "poll_stop", recording)
    out = s.perform(steps=[{"op": "registers"}, {"op": "read_memory", "ref": "0x0"}])
    assert out["status"] == "ok" and polls == [], polls
    ses.stops_after_polls = 1
    out = s.perform(steps=[{"op": "resume"}, {"op": "registers"}, {"op": "registers"}],
                    settle_seconds=1.0)
    assert out["status"] == "ok" and out["steps_completed"] == 3, out
    waited = [t for t in polls if t is not None and t > 0]
    assert len(waited) == 1 and waited[0] <= sequence.STOP_POLL_S, polls
    assert None not in polls, polls
    ses.running = True
    ses.stops_after_polls = 1
    polls.clear()
    assert sequence._wait_for_stop(ses, tmp_path, 0.0, mprogress.no_progress) == "stopped"
    assert polls == [0.0], polls
    (tmp_path / "error.log").write_text("boot\n")
    ses.running = True
    monkeypatch.setattr(sequence, "DRIVE_POLL_S", 0.0)
    polls.clear()
    sequence._verify(ses, tmp_path, re.compile("never"), 0.05, 0, mprogress.no_progress)
    assert polls and all(t == 0.0 for t in polls), polls


def test_check_drive_holds_its_two_ceilings_and_refuses_a_boolean_where_a_number_is_due() -> None:
    act = [{"op": "status"}]
    sequence.check_drive(act, "x", vocab.WAIT_MAX_S, ".", read.LOG_LIMIT_MAX)
    with pytest.raises(mstate.Invalid, match=r"limit=401 is outside 1\.\.400"):
        sequence.check_drive(act, "", None, ".", read.LOG_LIMIT_MAX + 1)
    with pytest.raises(mstate.Invalid, match=r"limit is a count; got True"):
        sequence.check_drive(act, "", None, ".", True)
    with pytest.raises(mstate.Invalid, match="seconds=601.0 is not a bound"):
        sequence.check_drive(act, "x", vocab.WAIT_MAX_S + 1, ".", 40)
    with pytest.raises(mstate.Invalid, match="seconds=True is not a bound"):
        sequence.check_drive(act, "x", True, ".", 40)


def test_a_failing_step_inside_an_act_answers_step_failed_with_the_account_and_the_look(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The refusal `drive` builds when a step fails carries the same three fields as its success.
"""
    log = tmp_path / "error.log"
    log.write_text("boot\nline\n")
    _running(monkeypatch, tmp_path)
    out = s.drive(act=[{"op": "breakpoint_at", "ref": "0x4a0"},
                       {"op": "breakpoint_at", "ref": "0x4a0", "role": "control"}], pattern="line",
                  limit=5)
    assert out["status"] == "INVALID" and out["code"] == "step_failed", out
    assert "the act stopped at step 2" in out["message"] and "already declared" in out["message"]
    assert out["act"]["steps_completed"] == 1 and out["act"]["failed"]["op"] == "breakpoint_at"
    looked = out["looked"]["emulator"]
    assert looked["available"] is True and looked["since_mark"] == log.stat().st_size
    assert looked["pattern"] == "line" and looked["lines"] == [] and looked["lines_total"] == 0


def test_an_act_that_ends_running_without_an_expect_waits_for_its_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x4A0]
    ses.stops_after_polls = 2
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    s.breakpoint_at(ref="0x4a0")
    out = s.drive(act=[{"op": "resume"}], settle_seconds=2.0)
    assert out["status"] == "ok", out
    assert out["act"]["stopped"]["pc"] == "0x000004a0" and not ses.running


def test_a_stop_the_verify_wait_meets_rides_on_drives_own_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stop the verify consumed is carried by the reply that missed its line as
    `stopped_on_its_own`."""
    ses = _running(monkeypatch, tmp_path)
    (tmp_path / "error.log").write_text("boot\n")
    monkeypatch.setattr(sequence, "DRIVE_POLL_S", 0.0)
    s.step(count=1)
    ses.pcs = [0x4A0, 0x4A0]
    ses.running = True
    ses.stops_after_polls = 3
    out = s.drive(act=[{"op": "status"}], expect="never", seconds=1.0)
    assert out["code"] == "wait_stopped" and out["verify"]["seen"] is False, out
    assert out["message"].endswith("; `resume` lets it run, then `drive` again"), out
    assert "stopped_on_its_own" not in out["act"]["ran"][0]["reply"], "the act saw no stop"
    assert out["stopped_on_its_own"]["pc"] == "0x000004a0", out.get("stopped_on_its_own")
    assert "surveyed here" in out["verify"]["why"]


def test_preflight_lists_every_refusal_and_survives_a_step_that_is_not_a_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Every kind of bad step in one list, each after the one before it, none crashing the walk."""
    _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "status", "ctx": 1}, {"op": "registers", "x": 1},
                           {"op": "step", "count": "x"}, 5,
                           {"op": "log", "pattern": "(", "channel": "emulator"}])
    assert out["status"] == "INVALID" and out["steps_completed"] == 0
    assert [e["step"] for e in out["errors"]] == [0, 1, 2, 3, 4], out["errors"]



WATCH_KEY = "watch frame_lo: 0x002031fc written"


def _cut_by_the_watch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                      outside: set[int] | None = None) -> list[str]:
    """A watched double whose every `gtime` is cut by the change watch, each write by a different
    pc; a run in `outside` first records a stop no step surveys."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    (tmp_path / "debug.log").write_text("F2034\n")
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    runs: list[str] = []
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("gtime"):
            runs.append(command)
            if outside and len(runs) in outside:
                mstate.STATE.remember_stop(ses, 0x25F6, {}, 100,  # type: ignore[arg-type]
                                           "a stop outside the list")
            value = 0x38 + len(runs)
            with (tmp_path / "debug.log").open("a") as log:
                log.write(f"Stopped at watchpoint 1 writing {value:04X} to 2031FE "
                          f"(PC={0x400 + 2 * len(runs):08X})\n25F6\n")
            ses.memory[0x2031FC] = value.to_bytes(4, "big")
        return real(command, timeout)

    monkeypatch.setattr(ses, "monitor", monitor)
    return runs


def _runs(n: int) -> list[dict[str, object]]:
    return [{"op": "run_for", "milliseconds": 1} for _ in range(n)]


def test_every_stop_reply_carries_the_stop_seq_status_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stop's number is in the reply, as `status`'s `last_stop.stop_seq`, with or without
    `summaries`."""
    _cut_by_the_watch(monkeypatch, tmp_path)
    out = s.run_for(milliseconds=1)
    assert out["verdict"] == "OTHER_STOP" and out["stop_seq"] == mstate.STATE.last_stop["seq"]
    assert s.status()["last_stop"]["stop_seq"] == out["stop_seq"]
    full = s.perform(steps=_runs(2))
    seqs = [r["reply"]["stop_seq"] for r in full["ran"]]
    assert seqs == [out["stop_seq"] + 1, out["stop_seq"] + 2], seqs
    assert "stops" not in full and "ran_path" not in full, "without summaries nothing changes"


def test_a_summarised_stop_keeps_its_hit_without_its_lists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The compact row is the stop without its lists; a step that is not a stop keeps its summary
    line and status."""
    _cut_by_the_watch(monkeypatch, tmp_path)
    out = s.perform(steps=[*_runs(2), {"op": "registers"}, {"op": "run_for", "milliseconds": 1}],
                    summaries=True)
    assert out["status"] == "ok" and out["steps_completed"] == 4, out
    row = out["ran"][0]
    assert row["step"] == 0 and row["op"] == "run_for", row
    assert set(row["reply"]) == {"summary", "status", "cause", "pc", "frame", "stop_seq",
                                 "watch_hit"}, row["reply"]
    assert row["reply"]["cause"].startswith(WATCH_KEY + " by pc "), row["reply"]["cause"]
    hit = row["reply"]["watch_hit"]
    assert "writes" not in hit and "lines" not in hit, hit
    assert {"ref", "addr", "cpu", "writer_pc", "writes_total", "truncated", "values_from", "before",
            "after"} <= set(hit), hit
    assert hit["writes_total"] == 1 and hit["after"] == 0x39
    assert set(out["ran"][2]["reply"]) == {"summary", "status"}, out["ran"][2]
    assert out["ran"][3]["step"] == 3 and "regs" in out["ran"][3]["reply"], "the last kept whole"


def test_the_program_counts_the_stops_and_names_what_it_did_not_survey(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`stops` is the machine's count: first and last numbers, the surveyed, a count per `cause`,
    and `unaccounted`."""
    _cut_by_the_watch(monkeypatch, tmp_path)
    out = s.perform(steps=[*_runs(3), {"op": "registers"}, *_runs(2)], summaries=True)
    stops = out["stops"]
    assert stops["surveyed"] == 5 and stops["by_cause"] == {WATCH_KEY: 5}, stops
    assert stops["stop_seq_last"] - stops["stop_seq_first"] == 4 and stops["unaccounted"] == 0
    assert stops["stop_seq_last"] == mstate.STATE.last_stop["seq"]
    runs = _cut_by_the_watch(monkeypatch, tmp_path, outside={2})
    out = s.perform(steps=_runs(3), summaries=True)
    assert len(runs) == 3 and out["status"] == "ok", out
    assert out["stops"]["surveyed"] == 3 and out["stops"]["unaccounted"] == 1, out["stops"]


def test_a_long_summarised_list_shows_its_first_rows_and_its_files_hold_every_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`ran` holds the first `ROWS_SHOWN` compact rows and the kept step; the files hold the rest;
    the reply stays inside its budget."""
    import json
    _cut_by_the_watch(monkeypatch, tmp_path)
    n = 214
    out = s.perform(steps=_runs(n), summaries=True)
    assert out["status"] == "ok" and out["steps_completed"] == n, out.get("message")
    assert out["steps_total"] == n and out["truncated"] is True
    assert len(out["ran"]) == mstate.ROWS_SHOWN + 1 and out["ran"][-1]["step"] == n - 1
    assert [r["step"] for r in out["ran"][:-1]] == list(range(mstate.ROWS_SHOWN))
    rows = [json.loads(ln) for ln in Path(out["ran_path"]).read_text().splitlines()]
    assert [r["step"] for r in rows] == list(range(n)) and rows[0] == out["ran"][0]
    replies = [json.loads(ln) for ln in Path(out["replies_path"]).read_text().splitlines()]
    assert len(replies) == n and all("regs" in r["reply"] for r in replies)
    assert replies[-1]["reply"]["stop_seq"] == out["stops"]["stop_seq_last"]
    assert out["stops"]["surveyed"] == n and out["stops"]["unaccounted"] == 0
    assert len(json.dumps(out)) < mstate.REPLY_BUDGET_CHARS
    monkeypatch.setattr(mstate, "ROWS_SHOWN", n)
    uncut = s.perform(steps=_runs(n), summaries=True)
    assert uncut["truncated"] is False and len(uncut["ran"]) == n
    assert len(json.dumps(uncut)) > mstate.REPLY_BUDGET_CHARS, "the control: the cap is the bound"
    assert uncut["ran_path"] != out["ran_path"], "two calls, two files"


def test_drive_counts_and_files_its_act_by_the_same_rule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _cut_by_the_watch(monkeypatch, tmp_path)
    out = s.drive(act=_runs(3), summaries=True)
    act = out["act"]
    assert act["stops"]["surveyed"] == 3 and act["stops"]["by_cause"] == {WATCH_KEY: 3}, act
    assert act["steps_total"] == 3 and act["truncated"] is False
    assert Path(act["ran_path"]).is_file() and Path(act["replies_path"]).is_file()
    assert "watch_hit" in act["ran"][0]["reply"]



FOREIGN_LINE = "Stopped at watchpoint 7 writing {value} to 2031FE (PC={pc:08X})\n"


def test_a_stop_found_on_its_own_between_steps_is_counted_and_the_tail_stop_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `resume` then a console step: the stop the contact found and the tail's stop are both
    counted."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    (tmp_path / "debug.log").write_text("F2034\n" + STOP_LINE + "25F6\n")
    ses.memory[0x2031FC] = bytes.fromhex("00000038")
    ses.next_packet = "T05watch:2031fc;0e:00000000;11:0000040e;"
    ses.stops_after_polls = 1
    out = s.perform(steps=[{"op": "resume"}, {"op": "registers"}], settle_seconds=2.0,
                    summaries=True)
    assert out["status"] == "ok", out
    assert out["stops"]["surveyed"] == 1 and out["stops"]["unaccounted"] == 0, out["stops"]
    assert out["stops"]["by_cause"] == {WATCH_KEY: 1}, out["stops"]
    ses.stops_after_polls = 1
    out = s.perform(steps=[{"op": "registers"}, {"op": "resume"}], settle_seconds=2.0,
                    summaries=True)
    assert "stopped" in out, out
    assert out["stops"]["surveyed"] == 1, out["stops"]
    assert out["stops"]["stop_seq_last"] == out["stopped"]["stop_seq"]


def test_a_stop_numbered_after_the_last_surveyed_one_is_unaccounted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The range is read off the session's own counter before and after, not the span of the
    replies."""
    _cut_by_the_watch(monkeypatch, tmp_path)
    real = s.registers

    def registers_that_step(**kwargs: Any) -> dict[str, Any]:
        ses = mstate.STATE.ses
        assert ses is not None
        mstate.STATE.remember_stop(ses, 0x25F6, {}, 100, "a reader's own step")
        reply: dict[str, Any] = real(**kwargs)
        return reply

    monkeypatch.setattr(s, "registers", registers_that_step)
    out = s.perform(steps=[*_runs(2), {"op": "registers"}], summaries=True)
    assert out["stops"]["surveyed"] == 2 and out["stops"]["unaccounted"] == 1, out["stops"]
    assert out["stops"]["stop_seq_last"] == mstate.STATE.last_stop["seq"]


def test_one_watch_is_one_key_whoever_wrote_and_whatever_value() -> None:
    """`by_cause` keys a watch's stops by the watch, with the writer's pc taken off."""
    from scry_mame import watches
    lines = [watches._STOP_LINE.search(FOREIGN_LINE.format(value=v, pc=pc))
             for v, pc in (("0038", 0x40E), ("0039", 0x25F4))]
    hows = [watches._foreign_cause(m) for m in lines if m is not None]
    assert len(hows) == 2 and hows[0] != hows[1]
    assert watches.cause_key(hows[0]) == watches.cause_key(hows[1]), hows
    assert "0x00040e" not in watches.cause_key(hows[0]) and "wpclear" in watches.cause_key(hows[0])
    own = "watch frame_lo: 0x002031fc written by pc 0x0000040e"
    assert watches.cause_key(own) == WATCH_KEY
    nobody = f"by {watches._NO_WRITER}"
    assert watches.cause_key(own.replace("by pc 0x0000040e", nobody)) == WATCH_KEY
    foreign = hows[0].replace("by pc 0x0000040e", nobody)
    assert foreign != hows[0] and watches.cause_key(foreign) == watches.cause_key(hows[0]), foreign
    assert watches.cause_key("elapsed") == "elapsed", "a stop that names no writer is left whole"


def test_a_batch_whose_files_cannot_be_written_keeps_its_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A scratch that refuses the files costs the files, said with the reason, never the account.
"""
    _cut_by_the_watch(monkeypatch, tmp_path)

    def refuses(path: Path, rows: object) -> str:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(sequence_account, "write_jsonl", refuses)
    out = s.perform(steps=_runs(2), summaries=True)
    assert out["status"] == "ok" and out["stops"]["surveyed"] == 2, out
    assert out["ran_path"] == out["replies_path"], "the pair or neither"
    assert out["ran_path"]["available"] is False, out["ran_path"]
    assert "No space left" in out["ran_path"]["why"], out["ran_path"]


@pytest.mark.parametrize("extra", [0, 1])
def test_truncated_turns_on_one_row_past_the_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extra: int,
) -> None:
    _cut_by_the_watch(monkeypatch, tmp_path)
    n = mstate.ROWS_SHOWN + 1 + extra
    out = s.perform(steps=_runs(n), summaries=True)
    assert out["truncated"] is bool(extra), (n, out["truncated"])
    assert len(out["ran"]) == mstate.ROWS_SHOWN + 1


def test_a_batch_refused_at_its_first_step_still_counts_and_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Nothing ran: `ran` is empty, the files hold no row, and `drive` gives the same account under
    `act`."""
    _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    bad = {"op": "breakpoint_at", "ref": "0x4a0", "role": "control"}
    for out, account in ((o := s.perform(steps=[bad], summaries=True)), o), (
            (d := s.drive(act=[bad], summaries=True)), d["act"]):
        assert out["status"] == "INVALID" and account["ran"] == [], out
        assert account["steps_total"] == 0 and account["stops"]["surveyed"] == 0
        assert Path(account["ran_path"]).read_text() == ""
        assert Path(account["replies_path"]).read_text() == ""


def test_a_compact_row_keeps_a_registerpoints_hit_and_counts_its_stop_by_its_name() -> None:
    reply = {"summary": "resume: halted", "status": "ok", "cause": "registerpoint 'd1==7fff'",
             "pc": "0x000f2234", "frame": 9, "stop_seq": 7, "regs": {"D1": "0x7fff"},
             "regpoint_hit": {"ref": "d1==7fff", "index": 1, "cpu": ":maincpu"}}
    row = sequence_account.brief({"op": "resume", "reply": reply}, 3, sequence.SHAPE)
    assert row["reply"]["regpoint_hit"] == reply["regpoint_hit"] and "regs" not in row["reply"]
    stops = sequence_account.stops([reply], 7, 7, sequence.SHAPE)
    assert stops["by_cause"] == {"registerpoint 'd1==7fff'": 1} and stops["unaccounted"] == 0


def test_the_stop_count_covers_the_stops_the_rows_carry_when_the_record_is_gone(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A session buried mid-list still has the count cover every stop the replies carry."""
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    ran = [{"op": "run_for", "reply": {"summary": "s", "status": "ok", "cause": "elapsed",
                                       "pc": "0x00000400", "frame": n, "stop_seq": n}}
           for n in (6, 7, 8)]
    got = sequence.account_of(ran, True, False, tmp_path, since=5)["stops"]
    assert got == {"stop_seq_first": 6, "stop_seq_last": 8, "surveyed": 3,
                   "by_cause": {"elapsed": 3}, "unaccounted": 0}, got


@pytest.mark.parametrize("where", ["also", "stopped_on_its_own"])
def test_the_stop_count_reaches_the_newest_stop_wherever_a_reply_carries_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, where: str) -> None:
    """With the record gone, the range still ends at the newest stop."""
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    newest = {"summary": "s", "status": "ok", "cause": "elapsed", "pc": "0x00000400",
              "frame": 9, "stop_seq": 9}
    ran = [{"op": "run_for", "reply": {**newest, "frame": 6, "stop_seq": 6}}]
    also = [newest] if where == "also" else None
    if where == "stopped_on_its_own":
        ran.append({"op": "log", "reply": {"summary": "s", "status": "ok",
                                           "stopped_on_its_own": newest}})
    got = sequence.account_of(ran, True, False, tmp_path, since=5, also=also)["stops"]
    assert (got["stop_seq_first"], got["stop_seq_last"]) == (6, 9), got
    assert got["surveyed"] == 2 and got["unaccounted"] == 2, got




def _frames_and_the_watch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """A watched double on the frames path, where landings alternate, so a window of N frames takes
    2N steps."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    (tmp_path / "debug.log").write_text("F2034\n")
    monkeypatch.setattr(advance, "VBLANK_SETTLE_S", 0.0)
    runs: list[str] = []
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "gvblank":
            runs.append(command)
            if len(runs) % 2:
                value = 0x38 + len(runs)
                with (tmp_path / "debug.log").open("a") as log:
                    log.write(f"Stopped at watchpoint 1 writing {value:04X} to 2031FE "
                              f"(PC={0x400 + 2 * len(runs):08X})\n25F6\n")
                ses.memory[0x2031FC] = value.to_bytes(4, "big")
            else:
                ses.frame += 1
            return ""
        return real(command, timeout)

    monkeypatch.setattr(ses, "monitor", monitor)
    return ses


FRAME_STEP = {"op": "run_for", "frames": 1}
#: How a run by frames that elapsed says it stopped (`run_for`'s `cause`).
ELAPSED_BY_FRAMES = "the `gvblank` stop of the last frame asked"


def test_until_frame_repeats_the_list_until_a_stop_reaches_the_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The caller names the frame, never the length: the list repeats until a stop reply reaches
    it."""
    ses = _frames_and_the_watch(monkeypatch, tmp_path)
    start = ses.frame
    out = s.perform(steps=[FRAME_STEP], summaries=True, until_frame=start + 5)
    assert out["status"] == "ok", out.get("message")
    assert out["until_frame"] == start + 5 and out["frame_reached"] == start + 5, out
    assert out["steps_total"] == 10 and out["steps_completed"] == 10
    assert out["stops"]["by_cause"] == {WATCH_KEY: 5, ELAPSED_BY_FRAMES: 5}, out["stops"]
    assert out["stops"]["unaccounted"] == 0 and out["stops"]["surveyed"] == 10
    assert out["ran"][-1]["reply"]["frame"] == start + 5
    assert out["summary"].endswith(f"frame {start + 5} of {start + 5}"), out["summary"]
    assert "until_frame" not in s.perform(steps=_runs(1), summaries=True), "absent when unused"


def test_until_frame_cycles_a_longer_list_and_ends_right_after_the_step_that_arrives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`step` counts the steps run, and the pass that reaches the frame ends right after its
    `run_for`."""
    ses = _frames_and_the_watch(monkeypatch, tmp_path)
    start = ses.frame
    out = s.perform(steps=[FRAME_STEP, {"op": "registers"}], summaries=True,
                    until_frame=start + 2)
    assert out["status"] == "ok", out.get("message")
    assert out["steps_total"] == 7 and out["frame_reached"] == start + 2, out
    ops = [r["op"] for r in out["ran"]]
    assert ops == ["run_for", "registers"] * 3 + ["run_for"], ops
    assert [r["step"] for r in out["ran"]] == list(range(7))


def test_until_frame_already_reached_is_refused_before_anything_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A frame the machine already stands at or past is refused, naming where it is."""
    ses = _frames_and_the_watch(monkeypatch, tmp_path)
    for past in (ses.frame, ses.frame - 3):
        out = s.perform(steps=[FRAME_STEP], summaries=True, until_frame=past)
        assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
        assert str(ses.frame) in out["message"] and out.get("steps_completed", 0) == 0
    assert ses.frame == mstate.STATE.last_stop["frame"], "nothing ran"


def test_until_frame_refuses_a_window_whose_first_stop_is_already_past_on_a_running_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """On a running machine, a first stop already at or past the frame is refused, naming both
    frames."""
    ses = _frames_and_the_watch(monkeypatch, tmp_path)
    far = ses.frame + 100

    def stop(**_: Any) -> dict[str, Any]:
        ses.running = False
        return menvelope.envelope({"cause": "interrupted", "stop_seq": 50, "frame": far,
                                   "pc": "0x00000400"})

    monkeypatch.setattr(s, "stop", stop)
    ses.running = True
    out = s.perform(steps=[{"op": "stop"}, FRAME_STEP], summaries=True,
                    until_frame=ses.frame + 5)
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert str(far) in out["message"] and str(ses.frame + 5) in out["message"], out["message"]


def test_the_batch_files_are_written_as_a_pair_or_not_at_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A second file that cannot be written takes the first with it, and the reply names neither.
"""
    _frames_and_the_watch(monkeypatch, tmp_path)
    real = sequence_account.write_jsonl

    def second_fails(path: Path, rows: Any) -> str:
        if path.name.endswith("-replies.jsonl"):
            raise OSError("disk full")
        return str(real(path, rows))

    monkeypatch.setattr(sequence_account, "write_jsonl", second_fails)
    out = s.perform(steps=_runs(2), summaries=True)
    assert out["ran_path"] == {"available": False, "why": "disk full"} == out["replies_path"], out
    scratch = mstate.STATE.scratch
    assert scratch is not None and not list(scratch.glob("batch-*.jsonl")), "an unnamed file"


def test_until_frame_refuses_a_stop_that_carries_no_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stop whose frame could not be read ends the list INVALID."""
    ses = _frames_and_the_watch(monkeypatch, tmp_path)

    def no_frame(**_: Any) -> dict[str, Any]:
        return menvelope.envelope({"cause": "elapsed", "stop_seq": 99,
                                   "frame": unavailable("no counter"),
                                   "pc": "0x00000000"})

    monkeypatch.setattr(s, "run_for", no_frame)
    out = s.perform(steps=[FRAME_STEP], summaries=True, until_frame=ses.frame + 3)
    assert out["status"] == "INVALID" and out["code"] == "unexpected_answer", out
    assert out["steps_total"] == 1 and out["frame_reached"]["available"] is False


def test_until_frame_is_bounded_in_time_and_reports_its_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The whole cycle holds the server's one lock, so it ends at the ceiling with `verdict:
    TIMEOUT` and the account."""
    ses = _frames_and_the_watch(monkeypatch, tmp_path)
    said: list[str] = []
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    target = ses.frame + 2
    out = sequence.run_steps(ses, tmp_path, [FRAME_STEP], 1.0, s._step_ops(),
                             lambda _p, _t, m: said.append(m), summaries=True,
                             until_frame=target)
    assert out["status"] == "ok", out.get("message")
    assert any(m.startswith(f"perform until frame {target}: frame ") for m in said), said
    monkeypatch.setattr(frame_window, "UNTIL_SECONDS_MAX", 0.0)
    out = s.perform(steps=[FRAME_STEP], summaries=True, until_frame=ses.frame + 5)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert "until_frame" in out and "frame_reached" in out
    start = ses.frame
    monkeypatch.setattr(frame_window, "UNTIL_SECONDS_MAX", 0.3)
    run_for = s.run_for

    def slow(**kw: Any) -> dict[str, Any]:
        time.sleep(0.05)
        out: dict[str, Any] = run_for(**kw)
        return out

    monkeypatch.setattr(s, "run_for", slow)
    out = s.perform(steps=[FRAME_STEP], summaries=True, until_frame=start + 500)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert out["steps_completed"] >= 2 and start < out["frame_reached"] < start + 500, out


def test_until_frame_begun_stopped_reports_frames_done_of_the_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Begun stopped the bar is frames of the window; begun running it is elapsed time with no
    total."""
    ses = _frames_and_the_watch(monkeypatch, tmp_path)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    start = ses.frame
    monkeypatch.setitem(mstate.STATE.last_stop, "frame", start)
    got: list[tuple[float, float | None]] = []
    out = sequence.run_steps(ses, tmp_path, [FRAME_STEP], 1.0, s._step_ops(),
                             lambda p, t, _m: got.append((p, t)), summaries=True,
                             until_frame=start + 4)
    assert out["status"] == "ok", out.get("message")
    assert got and all(t == 4 and 0 <= p <= 4 for p, t in got), got
    assert [p for p, _t in got] == sorted(p for p, _t in got), got
    assert got[-1] == (4.0, 4.0), got
    ses.running = True
    got.clear()
    sequence.run_steps(ses, tmp_path, [FRAME_STEP], 1.0, s._step_ops(),
                       lambda p, t, _m: got.append((p, t)), summaries=True,
                       until_frame=ses.frame + 4)
    assert got and all(t is None for _p, t in got), got


def test_a_failed_step_inside_the_cycle_keeps_the_window_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frames_and_the_watch(monkeypatch, tmp_path)
    clash = {"op": "watch_add", "ref": "frame_lo", "mode": "count", "length": 4}
    out = s.perform(steps=[FRAME_STEP, clash], summaries=True, until_frame=ses.frame + 5)
    assert out["code"] == "step_failed" and out["failed_at"] == 1, out
    assert out["until_frame"] == ses.frame + 5 and out["frame_reached"] is not None


def test_until_frame_is_bounded_and_says_where_it_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A counter that never reaches the frame ends at the step bound with `TIMEOUT`, never a loop.
"""
    _cut_by_the_watch(monkeypatch, tmp_path)
    ses: Any = mstate.STATE.ses
    monkeypatch.setattr(frame_window, "UNTIL_STEPS_MAX", 3)
    out = s.perform(steps=_runs(1), summaries=True, until_frame=ses.frame + 1)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert out["steps_total"] == 3 and out["stops"]["surveyed"] == 3
    assert out["frame_reached"] == ses.frame and str(ses.frame + 1) in out["note"]


def test_until_frame_is_refused_where_it_cannot_mean_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    refused("summaries", s.perform(steps=_runs(1), until_frame=10))
    refused("until_frame", s.perform(steps=_runs(1), summaries=True, until_frame=-1))
    refused("until_frame", s.perform(steps=_runs(1), summaries=True, until_frame=True))
    refused("run_for", s.perform(steps=[{"op": "registers"}], summaries=True, until_frame=10))
    refused("run_for", s.perform(steps=[{"op": "step"}], summaries=True, until_frame=10))
    out = s.perform(steps=[{"op": "registers", "bogus": 1}], summaries=True, until_frame=10)
    assert out["code"] == "bad_argument" and "errors" in out, "the whole list is judged first"


def test_a_list_is_refused_whole_for_an_optional_scalar_or_a_clash_a_step_would_meet_late(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`control` and `registers` shapes are judged before any step runs."""
    refused = sequence.preflight([
        {"op": "write", "ref": "0x400", "data_hex": "00"},
        {"op": "run_to", "ref": "0x4a0", "control": 5},
        {"op": "registers", "from_last_stop": True, "cpu": "subcpu"},
    ], s._step_ops())
    assert [(r["step"], r["code"]) for r in refused] == [(1, "bad_argument"), (2, "bad_argument")]
    assert "control is a string; got 5" in refused[0]["message"]
    assert "`cpu` names a live read" in refused[1]["message"]
    assert sequence.preflight([{"op": "run_to", "ref": "0x4a0", "control": "0x25a4"}],
                              s._step_ops()) == []


@pytest.mark.parametrize("call", [
    {"act": [], "expect": "x"},
    {"act": [{"op": "status"}], "limit": 0},
    {"act": [{"op": "status"}], "seconds": 5.0},
    {"act": [{"op": "status"}], "expect": "["},
])
def test_every_refusal_drive_makes_before_anything_ran_has_drives_shape(
    call: dict[str, Any],
) -> None:
    out = s.drive(**call)
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert out["act"]["steps_completed"] == 0 and out["verify"]["checked"] is False, out
    assert out["looked"]["emulator"]["available"] is False, out


def test_a_list_begun_on_a_running_machine_waits_for_its_stop_before_a_console_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """After a `resume`, the first console step waits up to `wait` for the stop."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    assert s.resume()["session"]["running"] is True
    ses.stops_after_polls = 1
    out = s.perform(steps=[{"op": "registers"}], settle_seconds=2.0)
    assert out["status"] == "ok" and out["steps_completed"] == 1, out


def _optional_count(count: int | None = None, mode: str | int | None = None) -> None:
    """A signature for `_wrong_type` alone: one optional scalar and one three-part union."""


@pytest.mark.parametrize(("args", "refusal"), [
    ({"count": None}, None),
    ({"count": 3}, None),
    ({"count": "3"}, "count is "),
    ({"count": True}, "count is "),
    ({"mode": 1.5}, None),
])
def test_an_optional_scalar_takes_null_and_judges_anything_else_as_the_scalar(
    args: dict[str, Any], refusal: str | None,
) -> None:
    said = step_judge.wrong_type(_optional_count, args)
    assert (said is None) if refusal is None else (said or "").startswith(refusal), said


def test_a_film_arming_step_waits_for_a_stop_and_its_read_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`gfx_film` answers while running when it reads and needs a stop when it arms."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(sequence, "STOP_POLL_S", 0.0)
    out = s.perform(steps=[{"op": "resume"}, {"op": "gfx_film", "trigger": "0x2000"}],
                    settle_seconds=0.05)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert out["steps_completed"] == 1 and "failed" not in out, "the arming was never sent"
    assert ses.running


def test_a_list_sends_the_last_stops_registers_to_a_running_machine_at_once() -> None:
    """`registers(from_last_stop=True)` reads no cpu, so a list sends it without waiting for a
    stop."""
    from scry_mame.sequence import answers_running
    assert answers_running("registers", {"from_last_stop": True})
    assert not answers_running("registers", {})
    assert not answers_running("registers", {"from_last_stop": False})
    assert answers_running("log", {}) and not answers_running("read_memory", {"ref": "0x0"})


def test_a_list_is_judged_once_a_call_its_shape_and_its_machine_halves_alike(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The shape is checked before the machine is fetched, the machine's half once it is, never
    again inside the run."""
    _running(monkeypatch, tmp_path)
    shapes: list[int] = []
    machines: list[int] = []
    shape, machine = sequence.refuse_steps, sequence.refuse_machine
    monkeypatch.setattr(sequence, "refuse_steps",
                        lambda *a: shapes.append(1) or shape(*a))   # type: ignore[func-returns-value]
    monkeypatch.setattr(sequence, "refuse_machine",
                        lambda *a: machines.append(1) or machine(*a))  # type: ignore[func-returns-value]
    assert s.perform(steps=[{"op": "status"}])["status"] == "ok"
    assert (len(shapes), len(machines)) == (1, 1)
    shapes.clear()
    machines.clear()
    assert s.drive(act=[{"op": "status"}])["status"] == "ok"
    assert (len(shapes), len(machines)) == (1, 1)


class _Exiting:
    """A MAME whose exit shows only once it is waited for: the socket closed first."""

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return -9


class _Running:
    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        raise subprocess.TimeoutExpired("mame", timeout or 0)


@pytest.mark.parametrize("proc", ["dead", "exiting", "alive"])
def test_a_channel_that_fails_while_the_list_waits_is_gone_or_a_refusal_the_list_ends_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, proc: str
) -> None:
    """The stub's channel failing during the wait: `gone` for a dead MAME, latched broken and
    refused for a lost place."""
    ses = _running(monkeypatch, tmp_path)

    def fails(*_a: Any, **_k: Any) -> bool:
        raise gs.ConnectionFailed("the stub hung up")

    monkeypatch.setattr(running, "came_to_rest", fails)
    monkeypatch.setattr(mstate.STATE, "proc", {"dead": SimpleNamespace(poll=lambda: -9),
                                               "exiting": _Exiting(), "alive": _Running()}[proc])
    if proc != "alive":
        assert sequence._wait_for_stop(ses, tmp_path, 0.5, mprogress.no_progress) == "gone"
        return
    with pytest.raises(mstate.Invalid, match="stub hung up") as e:
        sequence._wait_for_stop(ses, tmp_path, 0.5, mprogress.no_progress)
    assert e.value.code == "session_broken" and ses.broken, (e.value, ses.broken)


def test_a_refusal_the_stub_answered_while_the_list_waits_latches_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stub answered no: the wait ends the list with the usual refusal and the session is not
    broken."""
    ses = _running(monkeypatch, tmp_path)

    def refused(*_a: Any, **_k: Any) -> bool:
        raise gs.Refused("E01")

    monkeypatch.setattr(running, "came_to_rest", refused)
    monkeypatch.setattr(mstate.STATE, "proc", _Running())
    with pytest.raises(mstate.Invalid) as e:
        sequence._wait_for_stop(ses, tmp_path, 0.5, mprogress.no_progress)
    assert e.value.code == "readback_refused" and not ses.broken, (e.value, ses.broken)


@pytest.mark.parametrize(("op", "args"), [
    ("log_wait", {"pattern": "GO", "channel": "emulator"}),
    ("screen_wait", {"palette": "black"}),
])
def test_a_step_whose_own_wait_missed_ends_the_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, op: str, args: dict[str, Any],
) -> None:
    """A wait for something to see that timed out ends the list with the verdict."""
    _running(monkeypatch, tmp_path)
    monkeypatch.setattr(s, op, lambda **_k: menvelope.envelope(
        {"verdict": "TIMEOUT", "waited_s": 0.1}))
    out = s.perform(steps=[{"op": op, **args, "seconds": 0.1}, {"op": "status"}],
                    settle_seconds=0.5)
    assert out["status"] == "ok" and out["steps_completed"] == 1, out
    assert out["verdict"] == "TIMEOUT" and f"step 1 ('{op}')" in out["note"], out


def test_an_unprovable_console_run_is_proved_stopped_by_the_stop_the_console_logged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A breakpoint's stop line in the console's log proves the stop when the frame counter never
    moved."""
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    monkeypatch.setattr(mstate.STATE, "console_run", True)
    monkeypatch.setattr(mstate.STATE, "console_run_unprovable", True)
    monkeypatch.setattr(mstate.STATE, "debuglog_mark", 0)
    (tmp_path / "debug.log").write_text("D682\nStopped at breakpoint 3\n")
    began = time.monotonic()
    assert sequence._wait_for_stop(ses, tmp_path, 3.0, mprogress.no_progress,
                                   record=False) == "stopped"
    assert time.monotonic() - began < 1.0 and not ses.running


def test_an_unprovable_console_run_reads_each_logged_line_once_and_status_agrees(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The log is read from where the last look ended, so the wait and the first contact agree on
    whether it stopped."""
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    monkeypatch.setattr(mstate.STATE, "console_run", True)
    monkeypatch.setattr(mstate.STATE, "console_run_unprovable", True)
    monkeypatch.setattr(mstate.STATE, "debuglog_mark", 0)
    monkeypatch.setattr(mstate.STATE, "unprovable_peek", 0)
    log = tmp_path / "debug.log"
    log.write_bytes(b"D682\n")
    assert running.console_run_ended(cast(Any, ses), tmp_path) is False
    assert mstate.STATE.unprovable_peek == len("D682\n")
    with log.open("ab") as fh:
        fh.write(b"Stopped at breakpoint 3\n")
    found: list[str] = []
    monkeypatch.setattr(running, "_found", lambda _s, _d, packet: found.append(packet))
    running.observe_stop(cast(Any, ses), tmp_path)
    assert not ses.running and found == ["none: a run the console started"], found


def test_a_step_count_given_as_a_float_is_refused_as_the_tool_itself_refuses_it() -> None:
    """`length: 4.0` is refused by the schema of a direct call, so a step refuses it too, before
    anything runs; the DOSBox-X server's `perform` says the same."""
    out = s.perform(steps=[{"op": "read_memory", "ref": "0x0", "length": 4.0}])
    assert out["code"] == "bad_argument" and "length" in out["message"], out
