"""`promote`: what a session learned, kept as a candidate and written on approval."""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any

import pytest
from scry_core import given, media_replies, screen_map, tool_replies
from scry_core import promote as core_promote

from scry_mame import promote as mpromote
from scry_mame import replies, sequence, server
from scry_mame import state as mstate

STATE = mstate.STATE

START: dict[str, Any] = {
    "system": "lineup", "rompath": "/x/roms", "reference_rom": "/x/ref.bin",
    "state_dir": "/tmp/run", "binary": "", "reference_addr": "0x0", "inipath": "",
    "boot_seconds": 8.0, "shared": False, "presence": False,
    "symbols": {"maincpu": "/x/symbols.yaml"}, "env": None, "view": "",
    "throttle_from_frame": 0, "background": None, "display": None, "size": None,
    "boot_lua": "", "cfg": "", "types": "", "bases": None, "reference_base": "0x0",
    "stub_port": 0,
}


def screen(name: str = "play") -> screen_map.Screen:
    return screen_map.Screen(name, "pixel", (320, 200), (((0, 0, 8, 8), "0" * 16),), (),
                             "rgb", "")


def start_at(root: Path) -> dict[str, Any]:
    return {**START, "rompath": str(root / "roms"), "reference_rom": str(root / "ref.bin"),
            "symbols": {"maincpu": str(root / "symbols.yaml")}}


def perform_document() -> dict[str, Any]:
    return {"version": 3, "server": "mame", "entry": "lineup",
            "start": {"system": "lineup", "rompath": "/x/roms"},
            "steps": [{"op": "read_memory", "ref": "0x10", "length": 2,
                       "recorded": {"data": "abcd"}}],
            "needs": {"states": [], "declarations": {}}}


@pytest.fixture(autouse=True)
def fresh_drafts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ambient = tmp_path / "ambient"
    (ambient / ".scry").mkdir(parents=True)
    monkeypatch.chdir(ambient)
    STATE.drafts = core_promote.Drafts()
    STATE.maps = screen_map.Maps()


def test_the_tool_takes_the_review_and_the_approval() -> None:
    names = set(inspect.signature(server.promote).parameters)
    assert {"dry_run", "entries", "names", "root"} <= names


def test_the_reply_models_carry_what_a_promotion_says() -> None:
    assert "kept" in replies.StartReply.__annotations__
    assert "kept" in media_replies.PerformExportFields.__annotations__
    assert "kept" in tool_replies.MapWriteFields.__annotations__
    assert "draft" in replies.CloseReply.__annotations__
    assert "candidates" in replies.PromoteReply.__annotations__


def test_promote_is_no_step_of_a_sequence() -> None:
    assert "promote" in sequence.NOT_STEPS and "promote" not in server._step_ops()


def test_a_start_keeps_its_recipe_without_the_run_s_own_arguments() -> None:
    mpromote.keep_start(START, defaults=server._START_DEFAULTS)
    kept = STATE.drafts.kept["start", "lineup"].document
    assert kept == {"format": "scry-start/1", "system": "lineup", "rompath": "/x/roms",
                    "reference_rom": "/x/ref.bin", "symbols": {"maincpu": "/x/symbols.yaml"},
                    "presence": False}


def test_a_start_from_a_profile_is_named_by_the_profile_it_read() -> None:
    STATE.drafts.loaded_entry("start", "v30")
    mpromote.keep_start({**START, "system": "lineup"}, defaults=server._START_DEFAULTS)
    assert STATE.drafts.entries() == ["start/v30"]


def test_a_start_with_no_machine_proposes_nothing() -> None:
    assert mpromote.keep_start({**START, "system": ""},
                               defaults=server._START_DEFAULTS) is False
    assert STATE.drafts.entries() == []


def test_a_map_add_is_named_by_the_entry_this_session_read() -> None:
    STATE.maps.session_application = "lineup"
    STATE.maps.session["play"] = screen()
    reply = mpromote.after_map("add", {"screen": "play"})
    assert reply["kept"] == "kept 1 (promote to review)"
    assert STATE.drafts.entries() == ["maps/lineup"]
    assert STATE.drafts.kept["maps", "lineup"].document["screens"][0]["name"] == "play"


def test_a_map_add_after_a_start_is_named_by_the_machine() -> None:
    STATE.system = "lineup"
    STATE.maps.session["play"] = screen()
    assert mpromote.after_map("add", {"screen": "play"})["kept"] == "kept 1 (promote to review)"
    assert STATE.drafts.entries() == ["maps/lineup"]


def test_a_map_load_only_marks_the_entry_in_the_map_layer() -> None:
    assert mpromote.after_map("load", {"application": "lineup"}) == {"application": "lineup"}
    assert STATE.drafts.entries() == [] and STATE.drafts.loaded == {}


def test_a_map_save_keeps_nothing() -> None:
    STATE.maps.session_application = "lineup"
    STATE.maps.session["play"] = screen()
    reply = mpromote.after_map("save", {"application": "lineup", "screens": 1})
    assert reply == {"application": "lineup", "screens": 1}
    assert STATE.drafts.entries() == []


def test_a_map_add_with_no_screen_proposes_nothing() -> None:
    STATE.system = "lineup"
    assert mpromote.after_map("add", {"screen": "play"}) == {"screen": "play"}
    assert STATE.drafts.entries() == []


def test_an_export_keeps_its_document_named_by_the_file_it_wrote(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text(json.dumps(perform_document()))
    reply = mpromote.after_export(STATE.drafts, {"path": str(path)}, mpromote.PROMOTE_PATHS)
    assert reply["kept"] == "kept 1 (promote to review)"
    assert STATE.drafts.entries() == ["perform/session"]


def test_an_export_after_a_replay_updates_the_entry_it_replayed(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text(json.dumps(perform_document()))
    STATE.drafts.loaded_entry("perform", "dos")
    mpromote.after_export(STATE.drafts, {"path": str(path)}, mpromote.PROMOTE_PATHS)
    assert STATE.drafts.entries() == ["perform/dos"]


def test_a_replay_the_reader_refuses_marks_no_entry(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({**perform_document(), "version": 2}))
    assert server.perform(path=str(path))["code"] == "bad_argument"
    assert STATE.drafts.loaded_name("perform") == ""


def test_close_reports_what_was_left_unkept() -> None:
    mpromote.keep_start(START, defaults=server._START_DEFAULTS)
    assert server.close()["draft"] == ["start/lineup"]


def test_close_leaves_out_what_the_store_already_holds(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    mpromote.keep_start(start_at(tmp_path), defaults=server._START_DEFAULTS)
    entry = STATE.drafts.entries()[0]
    server.promote(entries=[entry], root=str(tmp_path))
    mpromote.keep_start(start_at(tmp_path), defaults=server._START_DEFAULTS)
    assert STATE.drafts.entries() == [entry]
    assert "draft" not in server.close()


def test_a_promotion_empties_the_draft_and_close_then_says_nothing(tmp_path: Path) -> None:
    mpromote.keep_start(start_at(tmp_path), defaults=server._START_DEFAULTS)
    server.promote(entries=["start/lineup"], root=str(tmp_path))
    assert STATE.drafts.entries() == []
    assert "draft" not in server.close()


def test_promote_reviews_and_writes_in_a_store_of_its_own(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    mpromote.keep_start(start_at(tmp_path), defaults=server._START_DEFAULTS)
    review = server.promote(dry_run=True, root=str(tmp_path))
    assert [c["entry"] for c in review["candidates"]] == ["start/lineup"]
    assert review["candidates"][0]["change"] == "new"
    written = server.promote(entries=["start/lineup"], root=str(tmp_path))
    assert written["written"][0]["file"] == ".scry/start/lineup.json"
    document = json.loads((tmp_path / ".scry" / "start" / "lineup.json").read_text())
    assert document["rompath"] == "${root}/roms"


def test_a_promotion_with_no_store_names_root(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    mpromote.keep_start(START, defaults=server._START_DEFAULTS)
    reply = server.promote(dry_run=True)
    assert reply["code"] == "bad_argument" and "root" in reply["message"]


def test_a_root_creates_the_store_only_on_the_approved_call(tmp_path: Path) -> None:
    repo = tmp_path / "game"
    repo.mkdir()
    mpromote.keep_start(start_at(repo), defaults=server._START_DEFAULTS)
    assert server.promote(dry_run=True, root=str(repo))["candidates"][0]["change"] == "new"
    assert not (repo / ".scry").exists()
    server.promote(entries=["start/lineup"], root=str(repo))
    assert (repo / ".scry" / "start" / "lineup.json").is_file()


def test_the_store_is_looked_for_from_the_recipe_s_own_paths(tmp_path: Path) -> None:
    mpromote.keep_start({**START, "rompath": f"{tmp_path}/roms;{tmp_path}/more"},
                        defaults=server._START_DEFAULTS)
    assert f"{tmp_path}/roms" in mpromote.starting()
    assert f"{tmp_path}/more" in mpromote.starting()


def test_a_start_that_only_loads_its_profile_learned_nothing() -> None:
    STATE.drafts.loaded_entry("start", "v30")
    with given.remembered({"profile", "state_dir"}):
        assert mpromote.keep_start({**START, "system": "lineup"},
                                   defaults=server._START_DEFAULTS) is False
    assert STATE.drafts.entries() == []
    with given.remembered({"profile", "boot_seconds"}):
        assert mpromote.keep_start({**START, "system": "lineup"},
                                   defaults=server._START_DEFAULTS) is True


def test_a_kept_start_leaves_the_run_s_own_keys_to_the_store() -> None:
    mpromote.keep_start(START, defaults=server._START_DEFAULTS)
    assert set(STATE.drafts.kept["start", "lineup"].own) == set(mpromote.RUN_OWN)


def test_the_recipe_s_paths_are_searched_before_this_process_s_directory(tmp_path: Path) -> None:
    mpromote.keep_start({**START, "rompath": f"{tmp_path}/roms"},
                        defaults=server._START_DEFAULTS)
    starts = mpromote.starting()
    assert starts[0] == f"{tmp_path}/roms" and starts[-1] == os.getcwd()


def test_a_map_learned_from_a_loaded_recipe_is_looked_for_in_that_recipe_s_store(
        tmp_path: Path) -> None:
    source = f"{tmp_path}/game/.scry/start/v30.json"
    STATE.drafts.loaded_entry("start", "v30", source=source)
    STATE.drafts.keep("maps", "v30", {"format": "scry-screen-map/1", "screens": [screen()]})
    assert mpromote.starting()[0] == source


def test_a_perform_document_s_start_block_says_where_the_store_is() -> None:
    STATE.drafts.keep("perform", "x", {"start": {"rompath": "/game/roms", "binary": "/b/mame"},
                                       "steps": [{"op": "a", "recorded": {"v": 1}}]})
    starts = mpromote.starting()
    assert starts[0] == "/game/roms" and str(Path("/b")) not in starts


def test_an_export_looks_for_the_store_where_the_document_it_kept_points(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    (repo / ".scry").mkdir(parents=True)
    bare = tmp_path / "elsewhere"
    bare.mkdir()
    monkeypatch.chdir(bare)
    document = perform_document()
    document["start"]["rompath"] = f"{repo}/roms"
    path = tmp_path / "run.json"
    path.write_text(json.dumps(document))
    kept = mpromote.after_export(STATE.drafts, {"path": str(path)}, mpromote.PROMOTE_PATHS)
    assert kept["kept"] == "kept 1 (promote to review)"


def test_a_working_directory_that_is_gone_does_not_cost_the_reply(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    gone.rmdir()
    mpromote.keep_start(START, defaults=server._START_DEFAULTS)
    assert mpromote.kept_line(STATE.drafts) == "kept 1 (promote to review)"


SETUP = [".scry/", ".scry/about.json", ".scry/README.md"]


def test_an_approved_promotion_into_a_bare_repository_sets_up_the_store(tmp_path: Path) -> None:
    repo = tmp_path / "game"
    repo.mkdir()
    mpromote.keep_start(start_at(repo), defaults=server._START_DEFAULTS)
    review = server.promote(dry_run=True, root=str(repo))
    assert review["would_create"] == SETUP and "created" not in review
    assert not (repo / ".scry").exists()
    written = server.promote(entries=["start/lineup"], root=str(repo))
    assert written["created"] == SETUP and "would_create" not in written
    assert json.loads((repo / ".scry" / "about.json").read_text())["server"] == "mame"
    assert (repo / ".scry" / "README.md").is_file()


def test_a_second_promotion_creates_nothing_more(tmp_path: Path) -> None:
    mpromote.keep_start(start_at(tmp_path), defaults=server._START_DEFAULTS)
    server.promote(entries=["start/lineup"], root=str(tmp_path))
    mpromote.keep_start({**start_at(tmp_path), "boot_seconds": 9.0},
                        defaults=server._START_DEFAULTS)
    assert "created" not in server.promote(entries=["start/lineup"], root=str(tmp_path))


def test_a_kept_line_says_how_to_set_up_a_store_only_when_none_is_above(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    mpromote.keep_start(START, defaults=server._START_DEFAULTS)
    assert "no .scry/ above" in mpromote.kept_line(STATE.drafts)
    (tmp_path / ".scry").mkdir()
    assert mpromote.kept_line(STATE.drafts) == "kept 1 (promote to review)"


def test_an_export_names_the_missing_store_too(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "run.json"
    path.write_text(json.dumps(perform_document()))
    kept = mpromote.after_export(STATE.drafts, {"path": str(path)}, mpromote.PROMOTE_PATHS)
    assert "no .scry/ above" in kept["kept"]
