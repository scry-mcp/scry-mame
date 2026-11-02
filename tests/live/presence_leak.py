"""Section Z's leaking presence drawer."""

from __future__ import annotations

import re
from pathlib import Path

from scry_mame import presence as mpresence
from scry_mame import transport


def leaking_drawer(root: Path, leak_state: Path) -> tuple[str, int, int]:
    """The drawer, and the containers and paths it moved (counted as a Lua literal)."""
    held = transport.lua_string(str(root / mpresence.STATE_FILE))
    leaking, containers = re.subn(r"manager\.machine\.render\.ui_container",
                                  "manager.machine.screens[':screen'].container",
                                  mpresence.drawer(root))
    paths = leaking.count(held)
    return leaking.replace(held, transport.lua_string(str(leak_state))), containers, paths
