"""The base this server ships meets the contract every server's dictionaries owe, against the
index captured from MAME's source and the shared chips' own index and locks: its dictionaries of
rows, which it serves, and those of the old shape, which stay in the tree until they are retired."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest
import scry_core
from scry_core import conformance
from scry_core.knowledge import (
    Base,
    Confirmation,
    Lock,
    SecondCheck,
    SourceIndex,
    Support,
    read_index,
    read_lock,
    sealed,
    shared,
)
from scry_core.knowledge import base as rows_base
from scry_core.knowledge.lock import parse_lock

from scry_mame.knowledge import support

INDEX = Path(__file__).resolve().parent.parent / "src" / "scry_mame" / "knowledge_index"
CORE_INDEX = Path(scry_core.__file__).parent / "knowledge_index"
#: What the code of this server depends on: the cpus its boards are run on and its tests name.
CODE_SCOPES = ("m68000", "v30", "m6809", "z80")


class MameKnowledge:
    def support(self) -> Support:
        return support.SUPPORT

    def base(self, fts5: bool | None = None) -> Base:
        own = parse_lock((INDEX / "lock.json").read_text(encoding="utf-8"), "lock.json")
        sure = Confirmation.of((*shared.locks(), own), (shared.second_check(),))
        core = Path(scry_core.__file__).parent / "knowledge"
        return Base.load("scry_mame", core / "chips", core / "cpus", fts5=fts5, pins=shared.PINS,
                         confirmation=sure)

    def sources(self) -> SourceIndex:
        own, shared = read_index(INDEX / "sources.json"), read_index(CORE_INDEX / "shared.json")
        return SourceIndex({**shared.rows, **own.rows}, {**shared.lists, **own.lists},
                           {**shared.pins, **own.pins})

    def lock(self) -> Lock:
        return Lock({id_: held
                     for name in ("shared-lock.json", "cpus-lock.json")
                     for id_, held in read_lock(CORE_INDEX / name).checked.items()} | dict(
            read_lock(INDEX / "lock.json").checked))

    def second_check(self) -> SecondCheck:
        return shared.second_check()

    def code_scopes(self) -> Iterable[str]:
        return CODE_SCOPES

    def rows_base(self, fts5: bool | None = None) -> rows_base.Base:
        return support.load(fts5)

    def rows_sources(self) -> Sequence[str | Path]:
        return support.SOURCES

    def rows_lock(self) -> sealed.Lock:
        return support.rows_lock()


class TestMameKnowledge(conformance.KnowledgeContract):
    @pytest.fixture
    def subject(self) -> MameKnowledge:
        return MameKnowledge()
