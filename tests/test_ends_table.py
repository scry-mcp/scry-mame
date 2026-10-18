"""REFERENCE's table of how a cancelled call ends is the tools' own declarations, read back: every
tool that declares an `on_cancel` sits in the row of that end, and every tool a row names declares
it (`scry_core.ends_table`)."""

from __future__ import annotations

import sys
from pathlib import Path

from scry_core import ends_table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_mcp  # noqa: E402
import server  # noqa: E402,F401  (registers the tools)

ROOT = Path(__file__).resolve().parent.parent


def test_the_table_of_ends_is_the_declared_ends() -> None:
    declared = mame_mcp.BOUNDARY.declared_ends
    assert declared, "no tool is registered, so nothing was compared"
    assert ends_table.unlike((ROOT / "REFERENCE.md").read_text(), declared) == {}
