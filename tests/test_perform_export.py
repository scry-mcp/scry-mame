"""`perform_export`: the session since its `start`, written as `perform`'s own document, on the
doubles a session runs on here. The rules of the export are scry-core's (`scry_core.recording`);
what is this server's is what each tool is declared to become, the machine it reads around a
call, and the tool's own reply."""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from scry_core import recording

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_server import _running  # noqa: E402

import mame_mcp  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Iterator[recording.Recorder]:
    """The server's recorder as a `start` that succeeded leaves it: a recording begun."""
    monkeypatch.setattr(mame_mcp.RECORDER, "recording", recording.Recording({"system": "board"}))
    yield mame_mcp.RECORDER


def test_with_nothing_recorded_the_export_is_no_recording(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mame_mcp.RECORDER, "recording", None)
    out = s.perform_export(path=str(tmp_path / "s.json"))
    assert out["status"] == "INVALID" and out["code"] == "no_recording", out
    assert not (tmp_path / "s.json").exists()


def test_a_session_on_the_double_is_exported_as_steps_checks_and_named_drops(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, recorder: recording.Recorder) -> None:
    _running(monkeypatch, tmp_path)
    s.write(ref="0x4a0", data_hex="ab")
    regs = s.registers()
    read = s.read_memory(ref="0x4a0", length=1)
    s.status()
    s.comment_add(ref="0x4a0", text="the loop")
    out = s.perform_export(path=str(tmp_path / "s.json"))
    assert out["status"] == "ok" and out["cut"] is None, out
    doc = json.loads((tmp_path / "s.json").read_text())
    assert doc["server"] == "mame" and doc["start"] == {"system": "board"}
    assert [st["op"] for st in doc["steps"]] == ["write", "registers", "read_memory"]
    assert doc["steps"][1]["recorded"] == {"regs": regs["regs"]}
    assert doc["steps"][2]["recorded"] == {"hex": read["hex"]}
    assert out["checks"] == 2 and [d["op"] for d in out["dropped"]] == ["status", "comment_add"]
    assert out["summary"].startswith("perform_export: 3 steps, 2 checks, 2 dropped to ")


def test_the_machine_around_a_call_is_the_last_stop_as_an_advance_spells_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _running(monkeypatch, tmp_path)
    got = mame_mcp._machine()
    stop = mstate.STATE.last_stop
    assert got == recording.Machine(running=False, frame=stop["frame"], seq=stop["seq"],
                                    stop={"pc": stop["pc"], "frame": stop["frame"]},
                                    reachable=bool(mstate.STATE.controls))
    ses.running = True
    assert mame_mcp._machine() == recording.Machine(running=True, frame=None, seq=stop["seq"])


def test_the_export_and_the_lifecycle_are_never_recorded_and_never_a_step() -> None:
    assert {"close", "rom_check", recording.EXPORT_TOOL} <= mame_mcp.RECORDER.outside
    assert "perform_export" not in s._step_ops()


#: What each tool's calls become in an export, stated here a second time so a declaration that
#: moves is seen: a check of fields, a run the wall clock ends, a drop, or (absent) a step.
DECLARED = {
    "read_memory": ("hex",), "read_block": ("hex", "pc", "frame"), "registers": ("regs",),
    "screen_signature": ("signature", "pc", "frame"),
    "golden_check": ("matched", "differing", "missing", "extra"),
    "resume": "wall", "stop": "wall",
    **dict.fromkeys(("throttle", "snapshot", "memdump", "comment_add", "comment_delete",
                     "comment_save", "comment_load", "palette", "screen_view", "gfx_view",
                     "gfx_locate", "gfx_sweep", "gfx_draft", "gfx_load", "gfx_blits",
                     "gfx_blit_source", "gfx_film", "palette_log", "scan_start", "scan_filter",
                     "scan_clear", "image_diff", "series_diff", "region_track", "audio_measure",
                     "audio_diff"), "drop"),
}


def test_each_tool_is_exported_as_it_is_declared_and_the_rest_as_steps_or_dropped_reads() -> None:
    declared = mame_mcp.RECORDER.declared
    for tool, kind in declared.items():
        want = DECLARED.get(tool, "drop" if kind.read_only else "step")
        assert kind.export_as == want, (tool, kind.export_as, want)
    assert set(DECLARED) <= set(declared), sorted(set(DECLARED) - set(declared))


def test_a_board_with_no_frame_counter_is_read_as_its_stop_says_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _running(monkeypatch, tmp_path)
    monkeypatch.setitem(mstate.STATE.last_stop, "frame", None)
    got = mame_mcp._machine()
    assert got.frame is None and got.stop["frame"] == mstate.frame_shown(None)



def test_a_run_a_stop_ended_goes_on_to_its_place_by_run_to() -> None:
    """Frames end at a frame's edge and a stop lands anywhere inside its frame, so the export
    follows a run's frames with `run_to` at the stop's `pc`: an argument `run_to` takes, a field
    its reply carries."""
    op, argument, field = mame_mcp.RECORDER.reach or ("", "", "")
    assert (op, argument, field) == ("run_to", "ref", "pc")
    assert argument in inspect.signature(s.run_to).parameters
    assert field in mame_mcp.RECORDER.stop_fields



def test_a_stop_with_no_control_declared_is_one_run_to_cannot_be_taken_from(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`run_to` refuses with no control declared, so the export does not write one there."""
    _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "controls", {})
    assert mame_mcp._machine().reachable is False
    monkeypatch.setattr(mstate.STATE, "controls", {("0x80", ":maincpu"): {}})
    assert mame_mcp._machine().reachable is True


def test_a_stop_at_a_declared_breakpoint_is_one_run_to_cannot_be_taken_from(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`run_to` refuses a target a breakpoint already sits at (a stop there could not be told
    from the target's), so a stop a breakpoint made is not `reachable` either."""
    _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "controls", {("0x80", ":maincpu"): {}})
    at = int(mstate.STATE.last_stop["pc"], 16)
    monkeypatch.setattr(mstate.STATE, "breakpoints",
                        {1: {"addr": at, "owner": (hex(at), None), "cpu": None}})
    assert mame_mcp._machine().reachable is False
    monkeypatch.setattr(mstate.STATE, "breakpoints",
                        {1: {"addr": at + 1, "owner": (hex(at + 1), None), "cpu": None}})
    assert mame_mcp._machine().reachable is True
