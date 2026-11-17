from __future__ import annotations

import re
from pathlib import Path

from scry_core import example, install, reference

from scry_mame import server


def test_the_reference_pages_agree_with_the_registry() -> None:
    found = reference.drift(server.REFERENCE)
    assert not found, "\n".join([
        *found, "pages: uv run python -m scry_core.reference scry_mame.server:REFERENCE --write;",
        "examples come only from a live run's transcript (CONTRIBUTING.md, Changing a tool)"])


README = Path(__file__).resolve().parents[1] / "README.md"
#: The most words a visitor reads before the install block.
WORDS_ABOVE_INSTALL = 150


def test_the_readme_s_install_block_is_the_table_of_clients() -> None:
    found = install.drift(README, "scry_mame")
    assert not found, f"{found}; rewrite it: uv run python -m scry_core.install scry_mame --write"


def test_the_readme_reaches_its_install_block_within_its_words() -> None:
    text = README.read_text(encoding="utf-8")
    above = text[text.index("\n# "):text.index("\n## Install\n")]
    prose = re.sub(r"<[^>]+>|\]\([^)]*\)|^# .*$", " ", above, flags=re.MULTILINE)
    assert 0 < example.words(prose) <= WORDS_ABOVE_INSTALL, example.words(prose)
