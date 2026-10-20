"""The screen maps on this server, on the captured screens of `test_gfx`: a screen mapped from
the one in front, found again off ONE capture, saved and loaded, and every refusal before the
machine is asked anything."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scry_core import screen_map  # noqa: E402
from session_doubles import refused  # noqa: E402
from test_gfx import _serve  # noqa: E402
from test_lua import _channel  # noqa: E402

import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

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
    added = _ok(s.map_add(screen="board", match=[STRIP], controls=[PLACE]))
    assert (added["kind"], added["size"], added["controls"]) == ("pixel", [256, 240], 1)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    assert added["match"][0]["signature"] == _ok(s.screen_signature(crop=STRIP))["signature"]
    before = mstate.STATE.lua_seq
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    found = _ok(s.map_find())
    assert (found["matched"], found["screen"], found["layer"]) == (True, "board", "session")
    assert found["controls"] == [{"name": "score", "rect": [8, 0, 64, 8], "centre": [40, 4]}]
    assert mstate.STATE.lua_seq == before + 1, "one Lua chunk for the whole identification"
    assert found["summary"] == "map_find: board (session), 1 control"
    assert found["session"]["altered"] is False
    assert mstate.STATE.maps.found is not None
    assert mstate.STATE.maps.found.stop == found["stop_seq"], "dated at the stop it reports"


def test_another_board_matches_nothing_and_says_what_it_tried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.map_add(screen="board", match=[STRIP]))
    _serve(ses, "screen-circus", screen="circus-screen")
    found = _ok(s.map_find())
    assert found["matched"] is False and "screen" not in found
    assert (found["size"], found["screens_tried"], found["screens_mapped"]) == ([248, 256], 0, 1)


def test_saved_screens_become_the_file_layer_and_load_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    _ok(s.map_add(screen="board", match=[STRIP], controls=[PLACE]))
    path = tmp_path / "gridlee.scry-map.json"
    saved = _ok(s.map_save(dest=str(path)))
    assert saved["promoted"] == ["board"] and json.loads(path.read_text())["application"] == (
        "gridlee")
    refused("there", s.map_save(dest=str(path)))
    mstate.STATE.maps = screen_map.Maps()
    loaded = _ok(s.map_load(path=str(path)))
    assert (loaded["application"], loaded["screens"], loaded["controls"]) == ("gridlee", 1, 1)


@pytest.mark.parametrize(("call", "code"), [
    (lambda p: s.map_save(dest=str(p / "x.scry-map.json")), "needs_call"),
    (lambda p: s.map_load(path=str(p / "no.scry-map.json")), "bad_argument"),
    (lambda p: s.map_load(path="relative.scry-map.json"), "bad_argument"),
    (lambda p: s.map_save(dest=str(p / "x.json")), "bad_argument"),
    (lambda p: s.map_save(dest=str(p / "x.scry-map.json"), overwrite="yes"), "bad_argument"),
    (lambda p: s.map_add(screen="", match=[STRIP]), "bad_argument"),
    (lambda p: s.map_add(screen="s", match=[]), "bad_argument"),
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
    got = s.map_add(screen="board", match=[STRIP], controls=[{"name": "score"}])
    assert got["code"] == "bad_argument" and "has no `rect`" in got["message"], got
    assert "mcp_capture(" not in ses.stdin.getvalue().decode(), "no capture for a refusal"


def test_find_with_nothing_mapped_asks_for_a_map(monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    got = s.map_find()
    assert got["code"] == "needs_call" and "map_load" in got["message"], got
    assert "mcp_capture(" not in ses.stdin.getvalue().decode(), "no capture for nothing mapped"


def test_a_start_empties_the_session_layer_and_keeps_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from test_server import _boot_args, _stub_boot

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
    """A capture here steps the machine, so `map_add` and `map_find` move it and an export keeps
    them whatever they were declared; what the declaration decides is that `map_load` is a step
    too (or the replayed find would know no map), `map_find` a check of what it matched and
    where, and `map_save` dropped (a replay would find its file there)."""
    import mame_mcp
    kinds = {n: mame_mcp.RECORDER.kind(n).export_as
             for n in ("map_load", "map_add", "map_find", "map_save")}
    assert kinds == {"map_load": "step", "map_add": "step",
                     "map_find": ("matched", "screen", "pc", "frame"), "map_save": "drop"}
