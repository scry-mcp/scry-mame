"""MAME resolution: scry-core's binary ladder with this server's rungs, the boot canary, and the
release this server recommends."""

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


#: The MAME release this server is tested on, and so recommends; another boots with a note.
RELEASE = "0.289"
_RELEASE = re.compile(r"(\d+\.\d+)(?![\d.])")
_SAID_SHOWN = 80


def release_note(said: str | dict[str, Any]) -> str | None:
    """Why the build may not be the recommended release, or None when it is.

    A note and never a refusal: nothing here knows which tools another release breaks."""
    if isinstance(said, dict):
        what = f"this build's release could not be read ({said.get('why', 'no reason given')})"
    elif (found := _RELEASE.match(said)) is None:
        what = f"`-version` named no release ({said[:_SAID_SHOWN]!r})"
    elif found.group(1) == RELEASE:
        return None
    else:
        what = f"this is MAME {found.group(1)}"
    return (f"{what}, and this server is tested on MAME {RELEASE}, the release it recommends: "
            "on another a tool may refuse, or answer differently")
