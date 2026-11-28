"""Each tool's declaration of what it stands on in MAME, and the one sentence each reference
entry ends with, generated from it."""

from __future__ import annotations

from pathlib import Path

import pytest
from scry_core import reference
from scry_core.strict_arguments import registered

from scry_mame import server, standing
from scry_mame.mcp import ROSTER

ROOT = Path(__file__).resolve().parents[1]


def _tools() -> list[str]:
    return [t.name for t in registered(server.mcp)]


def test_every_registered_tool_declares_what_it_stands_on() -> None:
    assert standing.missing(_tools()) == []
    assert all(standing.STANDS_ON[n] for n in _tools()), "an empty declaration"


def test_a_tool_with_no_declaration_is_named_by_the_finding(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(standing.STANDS_ON, "registers")
    assert "`registers` declares nothing it stands on" in standing.missing(_tools())


def test_a_declaration_for_no_tool_is_named_by_the_finding(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(standing.STANDS_ON, "gone", (standing.DEBUGGER,))
    assert "`gone` declares what it stands on, and is no tool" in standing.missing(_tools())


def test_the_reference_drift_names_a_tool_whose_declaration_is_removed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(standing.STANDS_ON, "registers")
    found = reference.drift(server.REFERENCE)
    assert "`registers` declares nothing it stands on" in found, found


def test_every_family_page_ends_each_entry_with_its_one_line() -> None:
    for family, names in ROSTER.families:
        page = (ROOT / reference._page(family)).read_text(encoding="utf-8")
        for name in names:
            begin, end = reference.begin_marker(name), reference.end_marker(name)
            assert begin in page and end in page, f"{page}: no entry for {name}"
            block = page[page.index(begin) + len(begin):page.index(end)].strip("\n")
            assert block.splitlines()[-1] == reference.standing_sentence(
                standing.STANDS_ON[name], "MAME"), block[-300:]
