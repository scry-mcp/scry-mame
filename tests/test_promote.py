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
from scry_core.reply_contract import Invalid

from scry_mame import promote as mpromote
from scry_mame import replies, sequence, server
from scry_mame import state as mstate

STATE = mstate.STATE

START: dict[str, Any] = {
    "system": "lineup", "rompath": "/x/roms", "reference_rom": "/x/ref.bin",
    "state_dir": "/tmp/run", "binary": "", "reference_addr": 0, "inipath": "",
    "boot_seconds": 8.0, "shared": False, "presence": False,
    "symbols": {"maincpu": "/x/symbols.yaml"}, "env": None, "view": "",
    "throttle_from_frame": 0, "background": None, "display": None, "size": None,
    "boot_lua": "", "cfg": "", "types": "", "bases": None, "reference_base": 0,
    "stub_port": 0,
}



def kept_recipe(params: dict[str, Any]) -> bool:
    """Whether `start`'s reply for `params` says the recipe was kept."""
    return "kept" in mpromote.after_start({}, params, block=None, defaults=server._START_DEFAULTS)

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


def started(profile: Path | None = None) -> None:
    """What the server's `start` leaves noted once its launch returned: the profile it read."""
    with STATE.drafts.starting(profile=str(profile) if profile else ""):
        pass


def profile_in(root: Path, name: str = "lineup") -> Path:
    """A profile in `root`'s own store, and its path."""
    path = root / ".scry" / "start" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": "scry-start/1", "system": name}))
    return path


def test_a_start_keeps_its_recipe_without_the_run_s_own_arguments() -> None:
    kept_recipe(START)
    kept = STATE.drafts.held("start", "lineup")[0].document
    assert kept == {"format": "scry-start/1", "system": "lineup", "rompath": "/x/roms",
                    "reference_rom": "/x/ref.bin", "symbols": {"maincpu": "/x/symbols.yaml"},
                    "presence": False}


def test_a_start_from_a_profile_is_named_by_the_profile_it_read() -> None:
    STATE.drafts.loaded_entry("start", "v30")
    kept_recipe({**START, "system": "lineup"})
    assert STATE.drafts.entries() == ["start/v30"]


def test_a_start_with_no_machine_proposes_nothing() -> None:
    assert not kept_recipe({**START, "system": ""})
    assert STATE.drafts.entries() == []


def test_a_map_add_is_named_by_the_entry_this_session_read() -> None:
    STATE.maps.session_application = "lineup"
    STATE.maps.session["play"] = screen()
    reply = mpromote.after_map("add", {"screen": "play"})
    assert reply["kept"].startswith("kept 1 (promote to review)")
    assert STATE.drafts.entries() == ["maps/lineup"]
    assert STATE.drafts.held("maps", "lineup")[0].document["screens"][0]["name"] == "play"


def test_a_map_add_after_a_start_is_named_by_the_machine() -> None:
    STATE.system = "lineup"
    STATE.maps.session["play"] = screen()
    kept = mpromote.after_map("add", {"screen": "play"})["kept"]
    assert kept.startswith("kept 1 (promote to review)")
    assert STATE.drafts.entries() == ["maps/lineup"]


def test_a_map_load_keeps_nothing_and_names_the_entry_it_read(tmp_path: Path) -> None:
    read = str(tmp_path / ".scry" / "maps" / "lineup-screen-map.json")
    loaded = {"application": "lineup", "path": read}
    assert mpromote.after_map("load", loaded) == loaded
    assert STATE.drafts.entries() == []
    assert (STATE.drafts.loaded_name("maps"), STATE.drafts.sources["maps"]) == ("lineup", read)


def test_a_map_loaded_from_another_store_and_added_to_belongs_to_that_store(
        tmp_path: Path) -> None:
    started(profile_in(tmp_path / "game", "v30"))
    other = tmp_path / "other" / ".scry" / "maps" / "lineup-screen-map.json"
    other.parent.mkdir(parents=True)
    mpromote.after_map("load", {"application": "lineup", "path": str(other)})
    STATE.maps.session_application = "lineup"
    STATE.maps.session["play"] = screen()
    mpromote.after_map("add", {"screen": "play"})
    assert STATE.drafts.held("maps", "lineup")[0].project == str(tmp_path / "other")


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


def exported(path: Path) -> dict[str, Any]:
    return core_promote.after_export(STATE.drafts, {"path": str(path)}, mpromote.PROMOTE_PATHS)


def test_an_export_keeps_its_document_named_by_the_file_it_wrote(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text(json.dumps(perform_document()))
    assert exported(path)["kept"].startswith("kept 1 (promote to review)")
    assert STATE.drafts.entries() == ["perform/session"]


def test_an_export_after_a_replay_updates_the_entry_it_replayed(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text(json.dumps(perform_document()))
    STATE.drafts.loaded_entry("perform", "dos")
    exported(path)
    assert STATE.drafts.entries() == ["perform/dos"]


def test_a_replay_the_reader_refuses_marks_no_entry(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({**perform_document(), "version": 2}))
    assert server.perform(path=str(path))["code"] == "bad_argument"
    assert STATE.drafts.loaded_name("perform") == ""


def test_close_reports_what_was_left_unkept() -> None:
    kept_recipe(START)
    assert server.close()["draft"] == ["start/lineup"]


def test_close_leaves_out_what_the_store_already_holds(tmp_path: Path) -> None:
    started(profile_in(tmp_path))
    kept_recipe(start_at(tmp_path))
    entry = STATE.drafts.entries()[0]
    server.promote(entries=[entry])
    kept_recipe(start_at(tmp_path))
    assert STATE.drafts.entries() == [entry]
    assert "draft" not in server.close()


def test_a_promotion_empties_the_draft_and_close_then_says_nothing(tmp_path: Path) -> None:
    kept_recipe(start_at(tmp_path))
    server.promote(entries=["start/lineup"], root=str(tmp_path))
    assert STATE.drafts.entries() == []
    assert "draft" not in server.close()


def test_promote_reviews_and_writes_in_a_store_of_its_own(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    kept_recipe(start_at(tmp_path))
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
    kept_recipe(START)
    reply = server.promote(dry_run=True)
    assert reply["code"] == "bad_argument" and "root" in reply["message"]


def test_a_root_creates_the_store_only_on_the_approved_call(tmp_path: Path) -> None:
    repo = tmp_path / "game"
    repo.mkdir()
    kept_recipe(start_at(repo))
    assert server.promote(dry_run=True, root=str(repo))["candidates"][0]["change"] == "new"
    assert not (repo / ".scry").exists()
    server.promote(entries=["start/lineup"], root=str(repo))
    assert (repo / ".scry" / "start" / "lineup.json").is_file()


def test_a_start_that_only_loads_its_profile_learned_nothing() -> None:
    STATE.drafts.loaded_entry("start", "v30")
    with given.remembered({"profile", "state_dir"}):
        assert not kept_recipe({**START, "system": "lineup"})
    assert STATE.drafts.entries() == []
    with given.remembered({"profile", "boot_seconds"}):
        assert kept_recipe({**START, "system": "lineup"})


def test_a_kept_start_leaves_the_run_s_own_keys_to_the_store() -> None:
    kept_recipe(START)
    assert set(STATE.drafts.held("start", "lineup")[0].own) == set(mpromote.RUN_OWN)


def test_a_recipe_read_from_a_profile_belongs_to_the_profile_s_store(tmp_path: Path) -> None:
    started(profile_in(tmp_path / "game"))
    kept_recipe(start_at(tmp_path / "bench"))
    assert STATE.drafts.held("start", "lineup")[0].project == str(tmp_path / "game")
    assert server.promote(dry_run=True)["store"] == str(tmp_path / "game" / ".scry")


def test_a_recipe_s_roms_never_say_whose_it_is(tmp_path: Path) -> None:
    (tmp_path / "game" / ".scry").mkdir(parents=True)
    started()
    kept_recipe(start_at(tmp_path / "game"))
    assert STATE.drafts.held("start", "lineup")[0].project == ""
    refused = server.promote(entries=["start/lineup"])
    assert refused["code"] == "bad_argument" and "root=<the repository>" in refused["message"]
    assert not (tmp_path / "game" / ".scry" / "start").exists()


def test_a_map_learned_after_a_profile_start_belongs_to_that_store(tmp_path: Path) -> None:
    started(profile_in(tmp_path / "game", "v30"))
    STATE.system = "lineup"
    STATE.maps.session["play"] = screen()
    assert mpromote.after_map("add", {"screen": "play"})["kept"] == "kept 1 (promote to review)"
    assert STATE.drafts.held("maps", "lineup")[0].project == str(tmp_path / "game")


def test_a_refused_start_leaves_the_live_session_s_project(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(STATE, "proc", None)
    started(profile_in(tmp_path / "game"))
    monkeypatch.setattr(STATE, "proc", object())
    with pytest.raises(Invalid), mpromote.launching(str(profile_in(tmp_path / "other"))):
        raise Invalid("session_live", "a session is already live")
    assert STATE.drafts.started_in == str(tmp_path / "game")


def test_a_start_refused_with_its_own_session_live_keeps_its_project(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(STATE, "proc", None)
    with pytest.raises(Invalid), mpromote.launching(str(profile_in(tmp_path / "other"))):
        monkeypatch.setattr(STATE, "proc", object())
        raise Invalid("window_not_visible", "the window never appeared")
    assert STATE.drafts.started_in == str(tmp_path / "other")


def test_two_projects_each_keep_their_own_recipe_and_store(tmp_path: Path) -> None:
    game, bare = tmp_path / "game", tmp_path / "bare"
    started(profile_in(game, "alpha"))
    with given.remembered({"profile", "boot_seconds"}):
        kept_recipe({**start_at(game), "system": "alpha", "boot_seconds": 9.0})
    started()
    kept_recipe({**start_at(bare), "system": "beta"})
    kept = core_promote.kept_line(STATE.drafts)
    assert "start/beta: nothing this session read names its repository" in kept, kept
    review = server.promote(dry_run=True)
    assert review["store"] == str(game / ".scry")
    assert [c["entry"] for c in review["candidates"]] == ["start/alpha"]
    assert [u["entry"] for u in review["unwritable"]] == ["start/beta"]
    refused = server.promote(entries=["start/alpha", "start/beta"])
    assert refused["code"] == "bad_argument" and "start/beta" in refused["message"]
    server.promote(entries=["start/alpha"])
    assert not (game / ".scry" / "start" / "beta.json").exists()
    assert not (bare / ".scry").exists()


def working_directory_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    """The working directory cannot be resolved, as when it was deleted: Windows refuses to
    delete a process's own working directory, so the state is reached without deleting it."""
    def gone() -> str:
        raise FileNotFoundError("the working directory")
    monkeypatch.setattr(os, "getcwd", gone)


def test_a_working_directory_that_is_gone_does_not_cost_the_reply(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started(profile_in(tmp_path))
    working_directory_gone(monkeypatch)
    kept_recipe(START)
    assert core_promote.kept_line(STATE.drafts) == "kept 1 (promote to review)"


def test_a_promote_with_a_root_does_not_need_the_working_directory(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    working_directory_gone(monkeypatch)
    kept_recipe(start_at(tmp_path))
    assert server.promote(dry_run=True, root=str(tmp_path))["store"] == str(tmp_path / ".scry")


SETUP = [".scry/", ".scry/about.json", ".scry/README.md"]


def test_an_approved_promotion_into_a_bare_repository_sets_up_the_store(tmp_path: Path) -> None:
    repo = tmp_path / "game"
    repo.mkdir()
    kept_recipe(start_at(repo))
    review = server.promote(dry_run=True, root=str(repo))
    assert review["would_create"] == SETUP and "created" not in review
    assert not (repo / ".scry").exists()
    written = server.promote(entries=["start/lineup"], root=str(repo))
    assert written["created"] == SETUP and "would_create" not in written
    assert json.loads((repo / ".scry" / "about.json").read_text())["server"] == "mame"
    assert (repo / ".scry" / "README.md").is_file()


def test_a_second_promotion_creates_nothing_more(tmp_path: Path) -> None:
    kept_recipe(start_at(tmp_path))
    server.promote(entries=["start/lineup"], root=str(tmp_path))
    kept_recipe({**start_at(tmp_path), "boot_seconds": 9.0})
    assert "created" not in server.promote(entries=["start/lineup"], root=str(tmp_path))


def test_a_kept_line_says_how_to_set_up_a_store_only_when_it_names_none(tmp_path: Path) -> None:
    started(profile_in(tmp_path))
    kept_recipe(start_at(tmp_path))
    assert core_promote.kept_line(STATE.drafts) == "kept 1 (promote to review)"
    started()
    kept_recipe({**start_at(tmp_path), "system": "speedf"})
    assert "start/speedf: nothing this session read names its repository" in \
        core_promote.kept_line(STATE.drafts)


def test_a_store_in_the_server_s_own_directory_does_not_silence_the_hint(
        tmp_path: Path) -> None:
    kept_recipe(start_at(tmp_path / "game"))
    assert "root=<the repository>" in core_promote.kept_line(STATE.drafts)


def test_an_export_names_the_missing_store_too(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "run.json"
    path.write_text(json.dumps(perform_document()))
    assert "root=<the repository>" in exported(path)["kept"]
