"""`start(profile=)`: a repository's run recipe, found and read before the launch."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from scry_core.reply_contract import Invalid

from scry_mame import launch, replies, server

#: What a MAME profile may set: `start`'s own arguments but for the profile itself.
KEYS = tuple(name for name in inspect.signature(server.start).parameters
             if name not in ("ctx", "profile"))


def stored(root: Path, values: dict[str, Any], name: str = "bench") -> Path:
    path = root / ".scry" / "start" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": "scry-start/1", **values}), encoding="utf-8")
    return path


BENCH = {"system": "radendur", "rompath": "roms", "reference_rom": "roms/reference.bin"}


def call(**values: Any) -> dict[str, Any]:
    return {"system": "", "rompath": "", "reference_rom": "", "boot_seconds": 8.0, **values}


def test_start_takes_a_profile() -> None:
    assert "profile" in inspect.signature(server.start).parameters


def test_the_reply_model_carries_the_profile_block() -> None:
    assert "profile" in replies.StartReply.__annotations__


def test_a_profile_fills_what_the_caller_did_not_give(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    stored(tmp_path, BENCH)
    monkeypatch.chdir(tmp_path)
    arguments, block = launch.with_profile("bench", keys=KEYS, arguments=call(), given=())
    assert arguments["system"] == "radendur"
    assert arguments["rompath"] == str(tmp_path / "roms")
    assert arguments["boot_seconds"] == 8.0
    assert block["supplied"] == ["reference_rom", "rompath", "system"]


def test_a_callers_argument_wins_over_the_profile(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    stored(tmp_path, BENCH)
    monkeypatch.chdir(tmp_path)
    arguments, block = launch.with_profile("bench", keys=KEYS, arguments=call(system="lineup"),
                                           given={"system"})
    assert arguments["system"] == "lineup"
    assert block["supplied"] == ["reference_rom", "rompath"]


def test_the_block_names_the_profile_and_the_file_it_read(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    entry = stored(tmp_path, BENCH)
    monkeypatch.chdir(tmp_path)
    _arguments, block = launch.with_profile("bench", keys=KEYS, arguments=call(), given=())
    assert block == {"name": "bench", "file": str(entry),
                     "supplied": ["reference_rom", "rompath", "system"]}


def test_a_profile_found_nowhere_is_refused_naming_the_directories_searched(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(Invalid, match="searched"):
        launch.with_profile("nowhere", keys=KEYS, arguments=call(), given=())


def test_a_key_no_start_takes_is_refused_by_name(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    stored(tmp_path, {**BENCH, "steps": []})
    monkeypatch.chdir(tmp_path)
    with pytest.raises(Invalid, match="steps"):
        launch.with_profile("bench", keys=KEYS, arguments=call(), given=())


def test_start_with_no_system_and_no_profile_is_refused_naming_the_argument() -> None:
    with pytest.raises(Invalid, match="system"):
        launch.check_start(system="", rompath="/roms", reference_rom="/reference.bin")
