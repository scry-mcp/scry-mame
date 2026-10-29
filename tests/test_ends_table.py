from __future__ import annotations

from pathlib import Path

from scry_core import ends_table

from scry_mame import mcp as mame_mcp  # noqa: E402
from scry_mame import server  # noqa: E402,F401  (registers the tools)

ROOT = Path(__file__).resolve().parent.parent


def test_the_table_of_ends_is_the_declared_ends() -> None:
    declared = mame_mcp.BOUNDARY.declared_ends
    assert declared, "no tool is registered, so nothing was compared"
    assert ends_table.unlike((ROOT / "REFERENCE.md").read_text(), declared) == {}
