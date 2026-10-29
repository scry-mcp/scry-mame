"""`perform_export`: the session since its `start`, written as `perform`'s own document, on the
doubles a session runs on here. The rules of the export are scry-core's (`scry_core.recording`);
what is this server's is what each tool is declared to become, the machine it reads around a
call, and the tool's own reply."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from scry_core import recording
from server_support import _running  # noqa: E402

from scry_mame import mcp as mame_mcp  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Iterator[recording.Recorder]:
    """The server's recorder as a `start` that succeeded leaves it: a recording begun."""
    monkeypatch.setattr(mame_mcp.RECORDER, "recording", recording.Recording({"system": "board"}))
    yield mame_mcp.RECORDER


def test_with_nothing_recorded_the_export_is_no_recording(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mame_mcp.RECORDER, "recording", None)
    out = s.perform_export(dest=str(tmp_path / "s.json"))
    assert out["status"] == "INVALID" and out["code"] == "no_recording", out
    assert not (tmp_path / "s.json").exists()


def test_a_session_on_the_double_is_exported_as_steps_checks_and_named_drops(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, recorder: recording.Recorder) -> None:
    _running(monkeypatch, tmp_path)
    s.write(ref="0x4a0", data_hex="ab")
    regs = s.registers()
    read = s.read_memory(ref="0x4a0", length=1)
    s.status()
    s.comment_write("add", ref="0x4a0", text="the loop")
    out = s.perform_export(dest=str(tmp_path / "s.json"))
    assert out["status"] == "ok" and out["cut"]["available"] is False, out
    doc = json.loads((tmp_path / "s.json").read_text())
    assert doc["server"] == "mame" and doc["start"] == {"system": "board"}
    assert [st["op"] for st in doc["steps"]] == ["write", "registers", "read_memory"]
    assert doc["steps"][1]["recorded"] == {"regs": regs["regs"]}
    assert doc["steps"][2]["recorded"] == {"hex": read["hex"]}
    assert out["checks"] == 2 and [d["op"] for d in out["dropped"]] == ["status", "comment_write"]
    assert out["summary"].startswith("perform_export: 3 steps, 2 checks, 2 dropped to ")


def test_the_machine_around_a_call_is_the_last_stop_as_an_advance_spells_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _running(monkeypatch, tmp_path)
    got = mame_mcp._machine()
    stop = mstate.STATE.last_stop
    assert got == recording.Machine(running=False, seq=stop["seq"], frame=stop["frame"],
                                    stop={"pc": stop["pc"], "frame": stop["frame"]})
    ses.running = True
    assert mame_mcp._machine() == recording.Machine(running=True, seq=stop["seq"])


def test_the_export_and_the_lifecycle_are_never_recorded_and_never_a_step() -> None:
    assert {"close", "rom_check", recording.EXPORT_TOOL} <= mame_mcp.RECORDER.outside
    assert "perform_export" not in s._step_ops()


#: What each tool's calls become in an export, stated here a second time so a declaration that
#: moves is seen: a check of fields, a run the wall clock ends, a drop, or (absent) a step.
DECLARED = {
    "read_memory": ("hex",), "read_block": ("hex", "pc", "frame"), "registers": ("regs",),
    "screen_signature": ("signature", "pc", "frame"),
    "image_compare": {"image": "drop", "series": "drop", "region": "drop",
                      "golden": ("matched", "differing_total", "missing_total", "extra_total",
                                 "differing", "missing", "extra")},
    "screen_map_write": {"add": "step", "load": "step", "save": "drop"},
    "resume": "wall", "stop": "wall",
    **dict.fromkeys(("throttle", "snapshot", "memdump", "comment_write", "palette",
                     "screen_view", "gfx_view", "gfx_locate", "gfx_sweep", "gfx_draft",
                     "gfx_load", "gfx_blits", "gfx_blit_source", "gfx_film", "palette_log",
                     "scan", "audio_compare"), "drop"),
    # A replay knows the map an identification was made against, and holds the find to it.
    "screen_map_find": ("matched", "screen", "pc", "frame"),
    # The readers dropped by default, named so a reader that turns into a step is seen.
    **dict.fromkeys(("declaration_list", "captures", "comment_list", "cpu_info", "disassemble",
                     "find", "history", "log", "log_wait", "machine_map", "rom_check",
                     "state_list", "status", "symbols_find"), "drop"),
}


def test_each_tool_is_exported_as_it_is_declared_and_the_rest_as_steps_or_dropped_reads() -> None:
    declared = mame_mcp.RECORDER.declared
    for tool, kind in declared.items():
        want = DECLARED.get(tool, "step")
        got = ({m: d.export_as for m, d in kind.items()} if isinstance(kind, dict)
               else kind.export_as)
        assert got == want, (tool, got, want)
    assert set(DECLARED) <= set(declared), sorted(set(DECLARED) - set(declared))


def test_a_board_with_no_frame_counter_is_read_as_its_stop_says_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _running(monkeypatch, tmp_path)
    monkeypatch.setitem(mstate.STATE.last_stop, "frame", None)
    got = mame_mcp._machine()
    assert got.stop["frame"] == mstate.frame_shown(None) and got.frame is None



def test_a_start_refused_over_the_live_session_keeps_its_recording(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, recorder: recording.Recorder) -> None:
    _running(monkeypatch, tmp_path)
    s.write(ref="0x4a0", data_hex="ab")
    image = tmp_path / "image.bin"
    image.write_bytes(bytes(16))
    refused = s.start(system="board", rompath=str(tmp_path), reference_rom=str(image))
    assert refused["status"] == "INVALID" and refused["code"] == "session_live", refused
    assert refused["session"]["alive"] is True
    rec = recorder.recording
    assert rec is not None and rec.start == {"system": "board"}
    assert [c.op for c in rec.calls] == ["write"]
