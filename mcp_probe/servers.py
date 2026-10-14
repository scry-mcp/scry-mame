"""This repository's MCP server, loaded without starting anything, as `scry_core.probe` reads it:

    uv run python -m scry_core.probe mame --servers mcp_probe/servers.py --tasks mcp_probe/tasks

The cap test and the probe read the SAME object the suite imports as `server`, so a text measured
under the cap is the text a model was probed with, and the shape guard wraps the one copy there is.
"""

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
#: The servers whose real runs this repository keeps, re-judged by its suite.
CAPTURED = ("mame",)


def _mame() -> ModuleType:
    # By name, from the repository's root, which the probe puts on `sys.path`: the module the
    # package publishes as `server` (its entry point is `server:main`).
    return importlib.import_module("server")


def load() -> dict[str, ModuleType]:
    """The server's MODULE by its registered name: `.mcp` is the server, and each tool is the
    module attribute of the same name.

    A test calls this at COLLECTION, never inside a test body: the root conftest's shape guard
    wraps every server module in `sys.modules` once collection ends, and fails on one imported
    after it."""
    return {"mame": _mame()}


def _mame_check(tool: str, given: dict[str, Any], effective: dict[str, Any]) -> None:
    """mame's tools call `check` with their own values, defaults included, and every judge
    takes the names it does not rule on as extras: so this passes them all, each number read
    first as the tool reads it (`numbers_read`)."""
    import mame_args
    import mame_inputs

    mame_args.check(tool, **mame_inputs.numbers_read(getattr(_mame(), tool), effective))


CHECKS = {"mame": _mame_check}
