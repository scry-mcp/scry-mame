"""The live check's demo arguments."""

from __future__ import annotations

from pathlib import Path

from scry_core.demo import Demo


def demo_argv(demo: Demo, rompath: Path, cwd: Path) -> list[str]:
    argv = ["--rompath", str(rompath)]
    if "cwd" in demo.offers:
        argv += ["--cwd", str(cwd)]
    return argv
