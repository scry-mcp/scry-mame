"""The repository's own `.scry/` store: every recipe reads, and none carries this host's paths."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest
from scry_core import project_store

from scry_mame import launch, server

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / ".scry" / "start"

#: What a MAME profile may set: `start`'s own arguments but for the profile itself.
KEYS = tuple(name for name in inspect.signature(server.start).parameters
             if name not in ("ctx", "profile"))

#: The directories a recipe names through `${env:...}`, as a live run exports them.
ENVIRON = {"MAME_LIVE_BENCH": str(ROOT / "bench"),
           "MAME_BINARY": str(ROOT / "bin" / "mame"),
           "MAME_TEST_ROMS": str(ROOT / "roms")}

RECIPES = ("free", "m68k-dual", "m68k-dual-alt", "v30", "v30-alt")

#: An absolute path, POSIX or Windows: a tracked recipe never carries one.
HOST_PATH = re.compile(r"^(/|[A-Za-z]:[\\/])")


def test_the_store_declares_exactly_these_recipes() -> None:
    assert sorted(path.stem for path in STORE.glob("*.json")) == list(RECIPES)


@pytest.mark.parametrize("name", RECIPES)
def test_the_ini_inside_the_repository_it_names_exists(name: str) -> None:
    values = project_store.read(STORE / f"{name}.json", KEYS, launch.START_PATHS,
                                state="/scratch", environ=ENVIRON)
    held = str(values.get("inipath") or "")
    if held.startswith(str(ROOT / "tests")):
        assert Path(held).exists(), f"{name}.inipath names {held}, which is not there"


@pytest.mark.parametrize("name", RECIPES)
def test_a_recipe_is_located_by_its_own_name_from_the_repository(name: str) -> None:
    assert project_store.locate([ROOT], name) == STORE / f"{name}.json"


@pytest.mark.parametrize("name", RECIPES)
def test_a_recipe_reads_with_the_servers_own_keys(name: str) -> None:
    values = project_store.read(STORE / f"{name}.json", KEYS, launch.START_PATHS,
                                state="/scratch", environ=ENVIRON)
    assert values, f"{name} declared nothing"


@pytest.mark.parametrize("name", RECIPES)
def test_a_recipe_carries_no_host_path(name: str) -> None:
    for key, value in json.loads((STORE / f"{name}.json").read_text(encoding="utf-8")).items():
        if isinstance(value, str):
            assert not HOST_PATH.match(value), f"{name}.{key} is {value!r}"


@pytest.mark.parametrize("name", RECIPES)
def test_a_recipe_resolves_every_path_it_names(name: str) -> None:
    values = project_store.read(STORE / f"{name}.json", KEYS, launch.START_PATHS,
                                state="/scratch", environ=ENVIRON)
    for key in ("rompath", "reference_rom", "symbols", "binary"):
        held = str(values.get(key) or "")
        if held:
            assert Path(held).is_absolute(), f"{name}.{key} did not resolve: {held!r}"
