"""The server, loaded without starting anything."""

from pathlib import Path
from types import ModuleType

import mame_mcp
import server

ROOT = Path(__file__).resolve().parent.parent
CAPTURED = ("mame",)


def load() -> dict[str, ModuleType]:
    return {"mame": server}


CHECKS = {"mame": mame_mcp.probe_check}
