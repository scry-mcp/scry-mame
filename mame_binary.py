"""MAME resolution: scry-core's binary ladder with this server's rungs, plus the boot canary."""

from __future__ import annotations

from scry_core import binaries

LADDER = binaries.Ladder(product="MAME", executable="mame", variable="MAME_BINARY")
EXECUTABLE_NAME, VARIABLE = LADDER.executable, LADDER.variable
ARGUMENT, PATH_RUNG = binaries.ARGUMENT, binaries.PATH_RUNG
Resolved = binaries.Resolved
resolve = LADDER.resolve
why_not, version, facts = binaries.why_not, binaries.version, binaries.facts
VERSION_TIMEOUT_S = binaries.VERSION_TIMEOUT_S


def canary_argv(binary: str, system: str, rompath: str, *extra: str) -> list[str]:
    """Boot `system` for one second, no video or sound, so the canary ends by itself."""
    return [binary, system, "-rompath", rompath, *extra, "-video", "none", "-sound", "none",
            "-seconds_to_run", "1", "-nothrottle", "-skip_gameinfo"]
