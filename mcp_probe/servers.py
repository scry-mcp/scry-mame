"""This repository's MCP server, loaded without starting anything, as `scry_core.probe` reads it:

    uv run python -m scry_core.probe mame --servers mcp_probe/servers.py --tasks mcp_probe/tasks

The cap test and the probe read the SAME object the suite imports as `server`, so a text measured
under the cap is the text a model was probed with, and the shape guard wraps the one copy there is.
"""

from pathlib import Path
from types import ModuleType

import server

ROOT = Path(__file__).resolve().parent.parent
#: The servers whose real runs this repository keeps, re-judged by its suite.
CAPTURED = ("mame",)


def load() -> dict[str, ModuleType]:
    """The server's MODULE by its registered name: `.mcp` is the server, and each tool is the
    module attribute of the same name.

    The server is imported with this file, so the repository's root must already be importable
    (the hook runs from it; a test puts it on `sys.path` first), and a test configures the probe
    at COLLECTION, never
    inside a test body: the shape guard wraps its declared anchors once collection ends, and
    fails on one imported after it."""
    return {"mame": server}


CHECKS = {"mame": server.probe_check}
