"""The screen maps on this server, on the captured screens of `test_gfx`: a screen mapped from
the one in front, found again off ONE capture, saved and loaded, and every refusal before the
machine is asked anything."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from lua_support import _channel  # noqa: E402
from scry_core import screen_map  # noqa: E402
from scry_core.file_names import written_as  # noqa: E402
from session_doubles import refused  # noqa: E402
from test_gfx import _serve  # noqa: E402

from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

#: A strip of gridlee's captured framebuffer, and a place on it.
STRIP = [0, 0, 256, 8]
PLACE = {"name": "score", "rect": [8, 0, 64, 8]}


@pytest.fixture(autouse=True)
def fresh_maps() -> None:
    mstate.STATE.maps = screen_map.Maps()


def _ok(reply: dict[str, Any]) -> dict[str, Any]:
    assert reply["status"] == "ok", reply
    return reply


def test_a_screen_mapped_from_the_one_in_front_is_found_again_off_one_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    added = _ok(s.screen_map_write("add", screen="board", match=[STRIP], controls=[PLACE]))
    assert (added["kind"], added["size"], added["controls"]) == ("pixel", [256, 240], 1)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    assert added["match"][0]["signature"] == _ok(s.screen_signature(crop=STRIP))["signature"]
    before = mstate.STATE.lua_seq
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    found = _ok(s.screen_map_find())
    assert (found["matched"], found["screen"], found["layer"]) == (True, "board", "session")
    assert found["controls"] == [{"name": "score", "rect": [8, 0, 64, 8], "centre": [40, 4]}]
    assert mstate.STATE.lua_seq == before + 1, "one Lua chunk for the whole identification"
    assert found["summary"] == "screen_map_find: board (session), 1 control"
    assert found["session"]["altered"] is False
    assert mstate.STATE.maps.found is not None
    assert mstate.STATE.maps.found.stop == found["stop_seq"], "dated at the stop it reports"


def test_a_run_to_a_verified_screen_reports_the_stop_its_capture_left(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The capture that judges the screen steps the machine, so the reply and the
    identification are dated at the stop after it, never at the anchor's."""
    from scry_mame import advance, running
    from scry_mame import maps as mmaps
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.screen_map_write("add", screen="board", match=[STRIP], controls=[PLACE]))
    added = mstate.STATE.maps.session["board"]
    mstate.STATE.maps.session["board"] = screen_map.Screen(
        added.name, added.kind, added.size, added.match, added.controls, added.cells, "Board")
    arrival = {"status": "ok", "verdict": "TARGET", "stop_seq": -1, "pc": "0x0000dead",
               "cause": "run_to's target Board"}
    monkeypatch.setattr(advance, "run_to", lambda *a, **k: dict(arrival))
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    got = mmaps.run_to_screen(*running.stopped("a run to a screen"), "board", "Tick", 30.0)
    assert got["status"] == "ok" and got["screen"]["judged"] is True, got
    assert got["stop_seq"] != -1 and got["pc"] != "0x0000dead", "the stop after the capture"
    assert "evaluated_by" in got
    assert mstate.STATE.maps.found is not None
    assert mstate.STATE.maps.found.stop == got["stop_seq"]


def test_a_screen_signed_by_index_asks_the_capture_for_its_pens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    added = _ok(s.screen_map_write("add", screen="board", match=[STRIP], cells="index"))
    assert added["cells"] == "index"
    asked = ses.stdin.getvalue()
    assert b", true)" in asked and b", false)" not in asked, "the pens were not asked for"
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    found = _ok(s.screen_map_find())
    assert (found["matched"], found["screen"]) == (True, "board")
    assert b", false)" not in ses.stdin.getvalue(), "an index map read without its pens"


def test_another_board_matches_nothing_and_says_what_it_tried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.screen_map_write("add", screen="board", match=[STRIP]))
    _serve(ses, "screen-circus", screen="circus-screen")
    found = _ok(s.screen_map_find())
    assert found["matched"] is False and "screen" not in found
    assert (found["size"], found["screens_tried"], found["screens_mapped"]) == ([248, 256], 0, 1)


def test_saved_screens_become_the_file_layer_and_load_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.screen_map_write("add", screen="board", match=[STRIP], controls=[PLACE]))
    path = tmp_path / "gridlee-screen-map.json"
    saved = _ok(s.screen_map_write("save", dest=str(path)))
    assert saved["promoted"] == ["board"] and json.loads(path.read_text())["application"] == (
        "gridlee")
    assert "note" not in saved, saved
    refused("there", s.screen_map_write("save", dest=str(path)))
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    renamed = _ok(s.screen_map_write("save", dest=str(elsewhere / "Gridlee-Screen-Map.JSON")))
    assert renamed["path"] == str(elsewhere / "gridlee-screen-map.json"), renamed
    assert renamed["note"] == written_as("dest", str(elsewhere / "Gridlee-Screen-Map.JSON"))
    mstate.STATE.maps = screen_map.Maps()
    loaded = _ok(s.screen_map_write("load", path=str(path)))
    assert (loaded["application"], loaded["screens"], loaded["controls"]) == ("gridlee", 1, 1)


def _consolidated_board(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """The gridlee board mapped, saved as a consolidated map that enters it by `DrawBoard`, and
    loaded back; the session it was read on."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.screen_map_write("add", screen="board", match=[STRIP]))
    path = tmp_path / "gridlee-screen-map.json"
    _ok(s.screen_map_write("save", dest=str(path)))
    doc = json.loads(path.read_text())
    doc["mode"], doc["screens"][0]["anchor"] = "consolidated", "DrawBoard"
    path.write_text(json.dumps(doc))
    mstate.STATE.maps = screen_map.Maps()
    _ok(s.screen_map_write("load", path=str(path)))
    return ses


def test_a_screen_added_to_a_consolidated_map_names_its_anchor_and_saves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _consolidated_board(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    said = refused("anchor", s.screen_map_write("add", screen="score", match=[STRIP]))
    assert said["code"] == "bad_argument" and "consolidated" in said["message"], said
    added = _ok(s.screen_map_write("add", screen="score", match=[STRIP], anchor="DrawScore"))
    assert added["anchor"] == "DrawScore"
    (tmp_path / "out").mkdir()
    saved = _ok(s.screen_map_write("save", dest=str(tmp_path / "out" / "gridlee-screen-map.json")))
    assert saved["promoted"] == ["score"] and saved["mode"] == "consolidated"


@pytest.mark.parametrize(("call", "code"), [
    (lambda p: s.screen_map_write("save", dest=str(p / "x-screen-map.json")), "needs_call"),
    (lambda p: s.screen_map_write("load", path=str(p / "no-screen-map.json")), "bad_argument"),
    (lambda p: s.screen_map_write("load", path="relative-screen-map.json"), "bad_argument"),
    (lambda p: s.screen_map_write("save", dest=str(p / "x.json")), "bad_argument"),
    (lambda p: s.screen_map_write("save", dest=str(p / "x-screen-map.json"), overwrite="yes"),
     "bad_argument"),
    (lambda p: s.screen_map_write("add", screen="", match=[STRIP]), "bad_argument"),
    (lambda p: s.screen_map_write("add", screen="s", match=[]), "bad_argument"),
], ids=["save with nothing mapped", "a file that is not there", "a relative path",
        "a name without the map suffix", "an overwrite that is no yes or no",
        "an empty screen name", "no region"])
def test_what_the_map_tools_refuse_before_the_machine(tmp_path: Path, call: Any,
                                                      code: str) -> None:
    got = call(tmp_path)
    assert got["status"] == "INVALID" and got["code"] == code, got


def test_a_misshapen_control_is_refused_before_the_capture(monkeypatch: pytest.MonkeyPatch,
                                                           tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    got = s.screen_map_write("add", screen="board", match=[STRIP], controls=[{"name": "score"}])
    assert got["code"] == "bad_argument" and "has no `rect`" in got["message"], got
    assert "mcp_capture(" not in ses.stdin.getvalue().decode(), "no capture for a refusal"


def test_find_with_nothing_mapped_asks_for_a_map(monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    got = s.screen_map_find()
    assert got["code"] == "needs_call", got
    assert "`screen_map_write` a map (`load`)" in got["message"], got
    assert "mcp_capture(" not in ses.stdin.getvalue().decode(), "no capture for nothing mapped"


def test_a_start_empties_the_session_layer_and_keeps_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from server_support import _boot_args, _stub_boot

    maps = mstate.STATE.maps
    maps.file["kept"] = screen_map.Screen("kept", "pixel", (8, 8), (((0, 0, 8, 8), "0" * 16),), ())
    maps.session["old"] = screen_map.Screen("old", "pixel", (8, 8), (((0, 0, 8, 8), "0" * 16),),
                                            ())
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    out = s.start(**_boot_args(tmp_path, image))
    try:
        assert out["status"] == "ok", out
        assert list(maps.session) == [] and list(maps.file) == ["kept"] and maps.found is None
    finally:
        s.close()


def test_an_export_keeps_the_map_and_holds_an_identification_to_what_it_matched() -> None:
    """A capture here steps the machine, so `screen_map_write(method="add")` and `screen_map_find`
    move it and an export keeps them whatever they were declared; what the declaration decides
    is that `screen_map_write(method="load")` is a step too (or the replayed find would know no
    map), `screen_map_find` a check of what it matched and where, and
    `screen_map_write(method="save")` dropped (a replay would find its file there)."""
    from scry_mame import mcp as mame_mcp
    kinds = {m: mame_mcp.RECORDER.kind("screen_map_write", {"method": m}).export_as
             for m in ("load", "add", "save")}
    assert kinds == {"load": "step", "add": "step", "save": "drop"}
    found = mame_mcp.RECORDER.kind("screen_map_find", {}).export_as
    assert found == ("matched", "screen", "pc", "frame")


def _one_frame(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """`run_for(frames=1)` as one frame stop, counted."""
    from scry_mame import advance
    ran: list[dict[str, Any]] = []

    def frame(ses: Any, scratch: Any, milliseconds: int, seconds: float, progress: Any = None,
              disarm_watches: bool = False, frames: int = 0, route: Any = None) -> dict[str, Any]:
        ran.append({"frames": frames})
        return {"status": "ok", "verdict": "ELAPSED", "stop_seq": 100 + len(ran),
                "pc": "0x0000beef", "frame_before": len(ran), "frame_after": len(ran) + 1,
                "polls": 1, "cause": "the frame a run_for ran to"}
    monkeypatch.setattr(advance, "run_for", frame)
    return ran


def test_a_run_to_a_screen_with_no_anchor_runs_frames_until_the_map_names_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from scry_mame import maps as mmaps
    from scry_mame import running
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.screen_map_write("add", screen="board", match=[STRIP], controls=[PLACE]))
    ran = _one_frame(monkeypatch)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    got = mmaps.run_to_screen(*running.stopped("a run to a screen"), "board", "", 30.0)
    assert got["status"] == "ok" and got["verdict"] == "TARGET", got
    assert got["frames"] == len(ran) == 1 and got["screen"]["judged"] is True, got
    assert "polls" not in got and "frame_before" not in got, got


def test_a_frame_run_ending_on_another_stop_after_a_read_is_not_surveyed_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The read that judged an earlier frame is not the last act: a frame that ended on a stop
    of someone else's leaves the machine where it stopped, so nothing refreshes the reply."""
    from scry_mame import advance, running
    from scry_mame import maps as mmaps
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.screen_map_write("add", screen="board", match=[STRIP], controls=[PLACE]))
    replies = [{"status": "ok", "verdict": "ELAPSED", "stop_seq": 101, "pc": "0x0000beef"},
               {"status": "ok", "verdict": "OTHER_STOP", "stop_seq": 102, "pc": "0x0000beef",
                "cause": "somebody's breakpoint"}]
    monkeypatch.setattr(advance, "run_for", lambda *a, **k: dict(replies.pop(0)))
    real_find = screen_map.Maps.find

    def unmatched(self: Any, read: Any, stop: Any) -> dict[str, Any]:
        real_find(self, read, stop)
        return {"matched": False}
    monkeypatch.setattr(screen_map.Maps, "find", unmatched)
    surveyed: list[Any] = []

    def stop_reply(*a: Any, **k: Any) -> dict[str, Any]:
        surveyed.append(k)
        return {}
    monkeypatch.setattr(running, "stop_reply", stop_reply)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    got = mmaps.run_to_screen(*running.stopped("a run to a screen"), "board", "", 30.0)
    assert surveyed == [], "no survey after a frame that was not read"
    assert got["verdict"] == "OTHER_STOP" and not replies, got


def test_a_control_with_a_screen_that_has_no_anchor_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.screen_map_write("add", screen="board", match=[STRIP]))
    got = s.run_to(screen="board", control="Tick")
    assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
    assert "no anchor" in got["message"], got["message"]


def test_the_tool_summary_of_a_run_to_an_anchorless_screen_counts_frames_not_controls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.screen_map_write("add", screen="board", match=[STRIP], controls=[PLACE]))
    _one_frame(monkeypatch)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    got = _ok(s.run_to(screen="board"))
    assert got["verdict"] == "TARGET" and got["frames"] == 1, got
    assert got["summary"] == "run_to screen board (judged): TARGET after 1 frame", got["summary"]


def test_a_run_to_an_anchored_screen_hands_the_run_its_condition_watches_and_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from scry_mame import advance
    _consolidated_board(monkeypatch, tmp_path)
    given: list[tuple[Any, ...]] = []

    def run(ses_: Any, scratch: Any, ref: str, control: str, seconds: float, progress: Any = None,
            **kw: Any) -> dict[str, Any]:
        given.append((ref, control, kw))
        return {"status": "ok", "verdict": "TARGET", "stop_seq": 9, "control_hits": 1}
    monkeypatch.setattr(advance, "run_to", run)
    got = _ok(s.run_to(screen="board", control="Tick", condition="w@X==1", disarm_watches=True,
                       cpu=":sub"))
    assert given == [("DrawBoard", "Tick", {"condition": "w@X==1", "disarm_watches": True,
                                            "cpu": ":sub"})], given
    assert got["screen"] == {"screen": "board", "layer": "file", "mode": "consolidated",
                             "judged": False}, got


@pytest.mark.parametrize("kw, word", [
    ({"condition": "w@X==1"}, "condition"),
    ({"disarm_watches": True}, "disarm_watches"),
    ({"cpu": ":sub"}, "cpu"),
])
def test_arguments_a_frame_by_frame_run_cannot_apply_are_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kw: dict[str, Any], word: str,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.screen_map_write("add", screen="board", match=[STRIP]))
    got = s.run_to(screen="board", **kw)
    assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
    assert word in got["message"] and "no anchor" in got["message"], got["message"]
