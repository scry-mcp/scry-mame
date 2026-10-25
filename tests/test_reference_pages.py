from __future__ import annotations

from scry_core import reference

import server


def test_the_reference_pages_agree_with_the_registry() -> None:
    found = reference.drift(server.REFERENCE)
    assert not found, "\n".join([
        *found, "pages: uv run python -m scry_core.reference server:REFERENCE --write;",
        "examples come only from a live run's transcript (CONTRIBUTING.md, The battery)"])
