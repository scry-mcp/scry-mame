"""The base this server ships meets the contract every server's dictionaries owe, against the
index captured from MAME's source and the shared chips' own index and locks."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest
import scry_core
from scry_core import conformance
from scry_core.knowledge import Base, Lock, SourceIndex, Support, read_index, read_lock

from scry_mame.knowledge import support

INDEX = Path(__file__).resolve().parent.parent / "src" / "scry_mame" / "knowledge_index"
CORE_INDEX = Path(scry_core.__file__).parent / "knowledge_index"
#: What the code of this server depends on: the cpus its boards are run on and its tests name.
CODE_SCOPES = ("m68000", "v30", "m6809", "z80")


class MameKnowledge:
    def support(self) -> Support:
        return support.SUPPORT

    def base(self, fts5: bool | None = None) -> Base:
        return support.load(fts5)

    def sources(self) -> SourceIndex:
        own, shared = read_index(INDEX / "sources.json"), read_index(CORE_INDEX / "shared.json")
        return SourceIndex({**shared.rows, **own.rows}, {**shared.lists, **own.lists},
                           {**shared.pins, **own.pins})

    def lock(self) -> Lock:
        return Lock({id_: held
                     for name in ("shared-lock.json", "cpus-lock.json")
                     for id_, held in read_lock(CORE_INDEX / name).checked.items()} | dict(
            read_lock(INDEX / "lock.json").checked))

    def code_scopes(self) -> Iterable[str]:
        return CODE_SCOPES


class TestMameKnowledge(conformance.KnowledgeContract):
    @pytest.fixture
    def subject(self) -> MameKnowledge:
        return MameKnowledge()
