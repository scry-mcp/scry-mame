"""A session started with its own `state_dir` and a symbol file keeps its declarations in
`<state_dir>/declarations.json` and never opens the project store, which every session of the
same system and symbol file shares: nothing it declares, adopts or clears reaches another
session's rows. And every listed declaration says how long ago it was declared (`age_s`).
"""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import refused  # noqa: E402
from test_declarations import _armable_boot  # noqa: E402
from test_server import _boot_args, _never_spawns  # noqa: E402

import mame_arming as arming  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

SEEDED_AT = "2026-01-01T00:00:00+00:00"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_state_dir_session_never_opens_the_project_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The project store holds a control another session declared; a session with its own
    `state_dir` declares the same control and then clears everything. The project file's bytes
    do not move, the start inherits nothing from it, and the session's rows are in
    `<state_dir>/declarations.json`, exactly its own."""
    image, sym, project, _armed = _armable_boot(monkeypatch, tmp_path)
    key = dec.store_key("m68k", str(sym))
    project.write_text(json.dumps({key: [
        {"kind": "breakpoint", "by": "symbol", "ref": "irq_vblank", "origin": "earlier",
         "created_at": SEEDED_AT}]}))
    before = _sha(project)
    own = tmp_path / "session-state"
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym), state_dir=str(own))
    try:
        assert out["status"] == "ok", out
        assert out["declarations"]["path"] == str(own / "declarations.json"), out["declarations"]
        assert out["declarations"]["persistent"] is True and out["declarations"]["held"] == 0
        assert out["declarations"]["rearm"]["rearmed"] == [], "nothing inherited from the project"
        bp = s.breakpoint_at(ref="irq_vblank")
        assert bp["status"] == "ok" and bp["already_stored"] is False, bp
        listed = s.breakpoint_list()["breakpoints"]
        assert [(r["ref"], r["inherited"]) for r in listed] == [("irq_vblank", False)]
        stored = json.loads((own / "declarations.json").read_text())
        assert [(r["ref"], r["origin"]) for r in stored[key]] == [
            ("irq_vblank", mstate.STATE.session_origin)], stored
        assert _sha(project) == before, "the project store was written"
        cleared = s.breakpoint_clear(all=True)
        assert cleared["status"] == "ok", cleared
        assert json.loads((own / "declarations.json").read_text())[key] == []
    finally:
        s.close()
    assert _sha(project) == before, "the project store was written"


def test_without_a_state_dir_the_project_store_is_the_one_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control of the case above: with no `state_dir`, the same start inherits the
    project's row and reports the project's file, and the list says it is inherited and how
    old it is, through the tool."""
    image, sym, project, _armed = _armable_boot(monkeypatch, tmp_path)
    project.write_text(json.dumps({dec.store_key("m68k", str(sym)): [
        {"kind": "breakpoint", "by": "symbol", "ref": "irq_vblank", "origin": "earlier",
         "created_at": SEEDED_AT}]}))
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym))
    try:
        assert out["declarations"]["path"] == str(project)
        assert [r["ref"] for r in out["declarations"]["rearm"]["rearmed"]] == ["irq_vblank"]
        monkeypatch.setattr(mstate, "utc_now", lambda: datetime(2026, 1, 2, tzinfo=UTC))
        (row,) = s.breakpoint_list()["breakpoints"]
        assert (row["inherited"], row["age_s"]) == (True, 86400), row
    finally:
        s.close()


def test_starts_rearm_rows_carry_the_identity_the_lists_give(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Every row of `start`'s re-arm account is the row `arming.decl_row` builds for its
    declaration: the row armed and the row a name this build lacks left unresolved, each with
    its own stamp, origin and age."""
    image, sym, project, _armed = _armable_boot(monkeypatch, tmp_path)
    project.write_text(json.dumps({dec.store_key("m68k", str(sym)): [
        {"kind": "breakpoint", "by": "symbol", "ref": "irq_vblank", "origin": "earlier",
         "created_at": SEEDED_AT},
        {"kind": "breakpoint", "by": "symbol", "ref": "nowhere_here", "origin": "older",
         "created_at": "2025-12-31T00:00:00+00:00"}]}))
    monkeypatch.setattr(mstate, "utc_now", lambda: datetime(2026, 1, 2, tzinfo=UTC))
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym))
    try:
        rearm = out["declarations"]["rearm"]
        (armed,), (lacking,) = rearm["rearmed"], rearm["unresolved"]
        assert armed == {"ref": "irq_vblank", "by": "symbol", "cpu": armed["cpu"],
                         "created_at": SEEDED_AT, "origin": "earlier", "inherited": True,
                         "age_s": 86400}, armed
        assert lacking == {"ref": "nowhere_here", "by": "symbol", "cpu": lacking["cpu"],
                           "created_at": "2025-12-31T00:00:00+00:00", "origin": "older",
                           "inherited": True, "age_s": 2 * 86400}, lacking
    finally:
        s.close()


def test_a_corrupt_project_store_does_not_reach_a_state_dir_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Never OPENED, not merely never written: a project file that would refuse any start
    without a `state_dir` is not read by one with it, and stays as it was."""
    image, sym, project, _armed = _armable_boot(monkeypatch, tmp_path)
    project.write_text("[]")
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym),
                  state_dir=str(tmp_path / "session-state"))
    try:
        assert out["status"] == "ok", out
    finally:
        s.close()
    assert project.read_text() == "[]"


def test_a_corrupt_own_store_refuses_the_start_before_the_spawn_and_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _never_spawns(monkeypatch, tmp_path)
    image, sym, _project, _armed = _armable_boot(monkeypatch, tmp_path)
    own = tmp_path / "session-state"
    own.mkdir()
    (own / "declarations.json").write_text("[]")
    e = refused("not a mapping", s.start(**_boot_args(tmp_path, image), symbols=str(sym),
                                         state_dir=str(own)))
    assert str(own / "declarations.json") in e["message"]
    assert (own / "declarations.json").read_text() == "[]"
    assert mstate.STATE.scratch is None


def test_a_state_dir_named_again_brings_back_what_an_earlier_pass_declared_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The store is the DIRECTORY's, not one boot's: a second pass over the same `state_dir`
    inherits what the first declared there, which is what a bare clear then reaches."""
    image, sym, _project, _armed = _armable_boot(monkeypatch, tmp_path)
    own = str(tmp_path / "session-state")
    s.start(**_boot_args(tmp_path, image), symbols=str(sym), state_dir=own)
    try:
        assert s.breakpoint_at(ref="irq_vblank")["status"] == "ok"
    finally:
        s.close()
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym), state_dir=own)
    try:
        assert out["declarations"]["held"] == 1, out["declarations"]
        (row,) = s.breakpoint_list()["breakpoints"]
        assert (row["ref"], row["inherited"]) == ("irq_vblank", True)
    finally:
        s.close()


def test_a_state_dir_that_is_a_file_is_refused_as_a_state_dir_with_a_symbol_file_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The store under it is read before `cfg/` and `nvram/` are made, so the refusal has to
    name the argument there too, not a declaration file inside a file."""
    _never_spawns(monkeypatch, tmp_path)
    image, sym, _project, _armed = _armable_boot(monkeypatch, tmp_path)
    a_file = tmp_path / "a-file"
    a_file.write_text("not a directory")
    e = refused("state_dir", s.start(**_boot_args(tmp_path, image), symbols=str(sym),
                                     state_dir=str(a_file)))
    assert "cfg" in e["message"], e
    assert mstate.STATE.scratch is None


def test_a_state_dir_that_is_the_project_store_directory_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Named directly or through a link, the project's own state directory would make the
    session's store the shared one under an own-store reply: refused, nothing spawned."""
    _never_spawns(monkeypatch, tmp_path)
    image, sym, project, _armed = _armable_boot(monkeypatch, tmp_path)
    link = tmp_path / "link"
    link.symlink_to(project.parent)
    for named in (project.parent, link):
        e = refused("project", s.start(**_boot_args(tmp_path, image), symbols=str(sym),
                                       state_dir=str(named)))
        assert e["code"] == "bad_argument", e
    assert not project.exists() and mstate.STATE.scratch is None


def test_a_state_dir_session_with_no_symbol_file_stays_session_lived(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """No symbol file means nothing could re-resolve by name, whatever the `state_dir`: no
    file is written there for the declarations."""
    image, _sym, _project, _armed = _armable_boot(monkeypatch, tmp_path)
    own = tmp_path / "session-state"
    out = s.start(**_boot_args(tmp_path, image), state_dir=str(own))
    try:
        assert out["declarations"]["persistent"] is False
        assert out["declarations"]["path"]["available"] is False, out["declarations"]
        assert s.breakpoint_at(ref="0x4a0")["status"] == "ok"
    finally:
        s.close()
    assert not (own / "declarations.json").exists()


def _row(created_at: str | None) -> dict[str, Any]:
    return arming.decl_row(dec.Declaration("breakpoint", "address", "0x4a0",
                                           created_at=created_at, origin="earlier"))


def test_a_listed_row_carries_its_age_in_whole_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """`age_s` is computed when the row is listed, from `created_at`, in whole seconds: a
    known stamp and a known clock give a known age, in any offset the stamp was written in."""
    monkeypatch.setattr(mstate, "utc_now", lambda: datetime(2026, 1, 1, 0, 1, 40, 900000,
                                                            tzinfo=UTC))
    assert _row(SEEDED_AT)["age_s"] == 100
    assert _row("2026-01-01T01:00:00+01:00")["age_s"] == 100, "the same instant, another offset"


def test_a_stamp_ahead_of_this_clock_is_a_negative_age(monkeypatch: pytest.MonkeyPatch) -> None:
    """Floored, never clamped: a row stamped by a clock ahead of this one reads below zero,
    which says so, where a zero would claim it was declared just now."""
    monkeypatch.setattr(mstate, "utc_now", lambda: datetime(2026, 1, 1, 0, 0, 0, 500000,
                                                            tzinfo=UTC))
    assert _row("2026-01-01T00:00:01+00:00")["age_s"] == -1
    assert _row("2026-01-02T00:00:00+00:00")["age_s"] == -86400


def test_a_row_with_no_readable_date_has_no_age_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row written before declarations were dated has no age, and says so in its place rather
    than with a zero that would read as "declared just now"; a stamp that is not a date with an
    offset is no date either."""
    monkeypatch.setattr(mstate, "utc_now", lambda: datetime(2026, 1, 1, tzinfo=UTC))
    assert _row(None)["age_s"]["available"] is False
    assert _row(None)["created_at"]["available"] is False
    assert _row("t")["age_s"]["available"] is False
    assert _row("2026-01-01T00:00:00")["age_s"]["available"] is False, "no offset: no instant"


def test_a_state_dir_whose_cfg_is_a_file_is_refused_naming_the_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A directory that cannot hold `cfg/` is found only when `cfg/` is made, after every
    other judgement: still the caller's, named as such, nothing spawned."""
    _never_spawns(monkeypatch, tmp_path)
    image, _sym, _project, _armed = _armable_boot(monkeypatch, tmp_path)
    own = tmp_path / "session-state"
    own.mkdir()
    (own / "cfg").write_text("not a directory")
    e = refused("cannot hold cfg/", s.start(**_boot_args(tmp_path, image), state_dir=str(own)))
    assert e["code"] == "host_failed" and mstate.STATE.scratch is None
