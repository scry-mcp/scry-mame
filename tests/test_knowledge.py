"""The base this server ships meets the rows contract."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest
from scry_core import conformance
from scry_core.knowledge import Support, quote, sealed
from scry_core.knowledge import base as rows_base

from scry_mame.knowledge import support

#: The cpus the server's code depends on.
CODE_SCOPES = ("m68000", "v30", "m6809", "z80")


class MameKnowledge:
    def support(self) -> Support:
        return support.SUPPORT

    def code_scopes(self) -> Iterable[str]:
        return CODE_SCOPES

    def rows_base(self, fts5: bool | None = None) -> rows_base.Base:
        return support.load(fts5)

    def rows_sources(self) -> Sequence[str | Path]:
        return support.SOURCES

    def rows_lock(self) -> sealed.Lock:
        return support.rows_lock()

    def rows_index(self) -> quote.Quotes:
        return support.rows_index()


class TestMameKnowledge(conformance.KnowledgeContract):
    @pytest.fixture
    def subject(self) -> MameKnowledge:
        return MameKnowledge()
