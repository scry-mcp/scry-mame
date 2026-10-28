"""MAME resolution: scry-core's binary ladder with this server's rungs, plus the boot canary."""

from __future__ import annotations

import re
from typing import Any

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

#: The MAME release this server is tested on; another boots with a note naming both.
RELEASE = "0.289"
RELEASE_NOTE_MARK = f"the release this server is tested on is {RELEASE}"
_RELEASE = re.compile(r"(\d+\.\d+)(?![\d.])")


def release_note(said: str | dict[str, Any]) -> str | None:
    """Why the build may not be the tested release, or None when it is.

    Only a refusal stops a start: a later MAME usually works, and a capability it lacks is
    refused where the launch meets it, with MAME's own words."""
    if isinstance(said, dict):
        what = f"this build's release could not be read ({said.get('why', 'no reason given')})"
    elif (found := _RELEASE.match(said)) is None:
        what = f"this build names no MAME release (`-version` said {said!r})"
    elif found.group(1) == RELEASE:
        return None
    else:
        what = f"MAME {found.group(1)} is not the release this server is tested on"
    return (f"{what}; {RELEASE_NOTE_MARK}: a tool may refuse or answer differently on "
            "another, and each refusal names what was missing")
