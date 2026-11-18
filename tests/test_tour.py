"""The reference tour's own tail, without an emulator: when a run's transcript replaces the
committed copy the reference pages read their examples from."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

TOUR = Path(__file__).resolve().parents[1] / "docs" / "reference" / "tour" / "tour.py"


@pytest.fixture(scope="module")
def tour() -> ModuleType:
    spec = importlib.util.spec_from_file_location("reference_tour", TOUR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("code, argv, copies", [
    (0, ["--display", "1"], 1),
    (0, [], 1),
    (1, [], 0),
    (0, ["--transcript", "/elsewhere/t.md"], 0),
    (0, ["--display", "1", "--transcript=/elsewhere/t.md"], 0),
])
def test_only_a_run_that_passed_at_its_own_place_replaces_the_committed_transcript(
        tour: ModuleType, monkeypatch: pytest.MonkeyPatch, code: int, argv: list[str],
        copies: int) -> None:
    copied: list[tuple[Any, Any]] = []
    monkeypatch.setattr(tour.shutil, "copyfile", lambda src, dst: copied.append((src, dst)))
    assert tour.keep_transcript(code, argv) == code
    assert len(copied) == copies
    assert all(dst == tour.TRANSCRIPT for _, dst in copied)
