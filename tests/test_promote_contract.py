"""scry-core's `PromoteContract` over this server's own `start`, `promote` and `close`, on a
booted stub."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from scry_core import conformance, screen_map
from scry_core import promote as core_promote
from server_support import _boot_args, _stub_boot

from scry_mame import server as s
from scry_mame.state import STATE


class _Subject:
    """Starts from a profile it writes where the project holds a store: a profile is how this
    server tells a program's project."""

    IMAGE = bytes(range(64))

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _stub_boot(monkeypatch, tmp_path, self.IMAGE, at=0)
        monkeypatch.setattr(STATE, "drafts", core_promote.Drafts())
        monkeypatch.setattr(STATE, "maps", screen_map.Maps())

    def start(self, project: Path, name: str) -> dict[str, Any]:
        arguments: dict[str, Any] = {**_boot_args(project, self.IMAGE), "system": name}
        if (project / ".scry").is_dir():
            profile = project / ".scry" / "start" / f"{name}.json"
            profile.parent.mkdir(exist_ok=True)
            profile.write_text(json.dumps({"format": "scry-start/1", "system": name}))
            arguments["profile"] = str(profile)
        return cast(dict[str, Any], s.start(**arguments))

    def promote(self, **arguments: Any) -> dict[str, Any]:
        return cast(dict[str, Any], s.promote(**arguments))

    def close(self) -> dict[str, Any]:
        return cast(dict[str, Any], s.close())


class TestMamePromotion(conformance.PromoteContract):
    @pytest.fixture
    def subject(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Subject:
        return _Subject(monkeypatch, tmp_path)
