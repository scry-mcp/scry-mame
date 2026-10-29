"""The server, loaded without starting anything."""

from pathlib import Path
from types import ModuleType

from scry_mame import mcp as mame_mcp
from scry_mame import server

ROOT = Path(__file__).resolve().parent.parent
CAPTURED = ("mame",)


def load() -> dict[str, ModuleType]:
    return {"mame": server}


CHECKS = {"mame": mame_mcp.probe_check}
