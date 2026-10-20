"""This repository's MCP server, loaded without starting anything, as `scry_core.probe` reads it:

    uv run python -m scry_core.probe mame --servers mcp_probe/servers.py --tasks mcp_probe/tasks

The cap test and the probe read the SAME object the suite imports as `server`, so a text measured
under the cap is the text a model was probed with, and the shape guard wraps the one copy there is.
"""

from pathlib import Path
from types import ModuleType

import mame_mcp
import server

ROOT = Path(__file__).resolve().parent.parent
#: The servers whose real runs this repository keeps, re-judged by its suite.
CAPTURED = ("mame",)


def load() -> dict[str, ModuleType]:
    """The server's module by its registered name (`scry_core.probe_checks` says how)."""
    return {"mame": server}


CHECKS = {"mame": mame_mcp.probe_check}
