"""Which MAME a session runs: scry-core's ladder (`scry_core.binaries`) with this server's
rungs, climbed once per launch (a relaunch after a crash climbs it again), and the canary that
proves the host can start it.
"""

from __future__ import annotations

from scry_core import binaries

#: The ladder is scry-core's (`scry_core.binaries`); this server names its rungs.
LADDER = binaries.Ladder(product="MAME", executable="mame", variable="MAME_BINARY")
EXECUTABLE_NAME, VARIABLE = LADDER.executable, LADDER.variable
ARGUMENT, PATH_RUNG = binaries.ARGUMENT, binaries.PATH_RUNG
Resolved = binaries.Resolved
resolve = LADDER.resolve
why_not, version, facts = binaries.why_not, binaries.version, binaries.facts
VERSION_TIMEOUT_S = binaries.VERSION_TIMEOUT_S


def canary_argv(binary: str, system: str, rompath: str, *extra: str) -> list[str]:
    """`system` on `binary` in a form that initialises SDL as a session's boot does and ENDS BY
    ITSELF: one second of the machine, no video, no sound (`scry_core.live_host.canary`)."""
    return [binary, system, "-rompath", rompath, *extra, "-video", "none", "-sound", "none",
            "-seconds_to_run", "1", "-nothrottle", "-skip_gameinfo"]
