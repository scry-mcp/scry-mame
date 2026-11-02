"""Section Z's leaking drawer is derived from the production drawer on any host's paths."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from scry_mame import server  # noqa: F401 -- registers the tools the shape guard wraps

LEAK = Path(__file__).parent / "live" / "presence_leak.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("presence_leak", LEAK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("folder", ["scratch", "back\\slash", 'quo"te'])
def test_the_leaking_drawer_moves_one_container_and_one_state_path_on_any_path(
        tmp_path: Path, folder: str) -> None:
    root = tmp_path / folder
    root.mkdir()
    text, containers, paths = _module().leaking_drawer(root, tmp_path / "leak.state")
    assert (containers, paths) == (1, 1)
    assert "screens[':screen'].container" in text and "ui_container" not in text
