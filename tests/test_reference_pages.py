"""The reference pages agree with the registry: each tool's block on its family's page is what
`scry_core.reference` generates from the code, so an argument cannot change under a page that
still describes the old one. `uv run python -m scry_core.reference server:REFERENCE --write`
rewrites them; `--examples <transcript.jsonl>` first refreshes the examples from a live run."""

from __future__ import annotations

from scry_core import reference

import server


def test_the_reference_pages_agree_with_the_registry() -> None:
    found = reference.drift(server.REFERENCE)
    assert not found, "\n".join([*found, "regenerate: uv run python -m scry_core.reference "
                                  "server:REFERENCE --write"])
