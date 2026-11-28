from __future__ import annotations

import re
from pathlib import Path

import pytest
from scry_core import example, install, reference, roster

from scry_mame import server
from scry_mame.mcp import ROSTER


def test_the_reference_pages_agree_with_the_registry() -> None:
    found = reference.drift(server.REFERENCE)
    assert not found, "\n".join([
        *found, "pages: uv run python -m scry_core.reference scry_mame.server:REFERENCE --write;",
        "sentences: docs/reference/asks.json; examples: the tour (CONTRIBUTING.md)"])


ROOT = Path(__file__).resolve().parents[1]


def test_the_knowledge_base_has_the_section_the_site_links_and_the_tool_names() -> None:
    headings = re.findall(r"^## (.+)$", (ROOT / "REFERENCE.md").read_text(encoding="utf-8"), re.M)
    assert "Knowledge base" in headings, headings
    page = (ROOT / "docs" / "reference" / "knowledge.md").read_text(encoding="utf-8")
    assert "Reference: REFERENCE.md, Knowledge base." in page


def test_the_rosters_shared_families_follow_the_shared_order() -> None:
    """One canonical order, declared by `SHARED_FAMILIES`: a reader meets the same families
    first, in the same sequence, on both servers."""
    shared = list(dict.fromkeys(roster.SHARED_FAMILIES.values()))
    held = [family for family, _ in ROSTER.families if family in set(shared)]
    assert held == [family for family in shared if family in set(held)], held


README = Path(__file__).resolve().parents[1] / "README.md"
#: The most words a visitor reads before the install block.
WORDS_ABOVE_INSTALL = 150


def test_the_readme_s_install_block_is_the_table_of_clients() -> None:
    found = install.drift(README, "scry_mame")
    assert not found, f"{found}; rewrite it: uv run python -m scry_core.install scry_mame --write"


def words_above_install(text: str) -> int:
    """The words a visitor reads before the install block, outside the block a demo's run
    writes."""
    above = text[:text.index("\n## Install\n")]
    begins, ends = above.count("<!-- demo-lead:begin "), above.count("<!-- demo-lead:end ")
    assert begins == ends == 1, f"{begins} lead blocks begin and {ends} ends above the install"
    hand = re.sub(r"<!-- demo-lead:begin (\w+) -->.*?<!-- demo-lead:end \1 -->", " ", above,
                  flags=re.DOTALL)
    # A tag ends on its own line: a bare `<` in a sentence hides nothing after it.
    return example.words(re.sub(r"<[^>\n]+>|\]\([^)]*\)", " ", hand))


def test_the_readme_reaches_its_install_block_within_its_words() -> None:
    words = words_above_install(README.read_text(encoding="utf-8"))
    assert 0 < words <= WORDS_ABOVE_INSTALL, words


def test_words_typed_where_the_count_could_miss_them_are_counted() -> None:
    text = README.read_text(encoding="utf-8")
    counted, typed = words_above_install(text), "word " * 200
    in_the_title = text.replace("</h1>", typed + "</h1>", 1)
    assert words_above_install(in_the_title) == counted + 200
    after_a_bare_angle = text.replace(
        "\n## Install\n", f"\nIt starts in <1 s.\n{typed}\n<p></p>\n\n## Install\n", 1)
    assert words_above_install(after_a_bare_angle) == counted + 205
    begin = "<!-- demo-lead:begin "
    under_a_second_marker = text.replace(begin, f"{begin}typed -->\n{typed}\n{begin}", 1)
    with pytest.raises(AssertionError, match="2 lead blocks begin and 1 ends"):
        words_above_install(under_a_second_marker)
