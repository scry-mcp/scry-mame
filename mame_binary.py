"""Which MAME a session runs, where that choice came from, and what the build says it is.

ONE LADDER, CLIMBED ONCE PER LAUNCH (a relaunch after a crash climbs it again): the caller's
`binary`, else the `MAME_BINARY` variable, else the `mame` the PATH finds. The first rung that
holds anything is the one taken, and a wrong value there is refused rather than passed over: a
caller who named a build and silently got another would be measuring the wrong emulator. The
reply says which rung it was, so the choice is never made in silence.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from scry_core.reply_contract import Invalid

import mame_inputs as inputs

EXECUTABLE_NAME = "mame"
VARIABLE = "MAME_BINARY"
ARGUMENT = "argument"
PATH_RUNG = "PATH"
VERSION_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Resolved:
    path: str
    origin: str


def resolve(binary: str) -> Resolved:
    """The absolute executable the ladder lands on. A relative value is refused naming its
    argument or the variable; one naming no executable file is refused naming what all three
    rungs held, and why the one taken is no executable."""
    held = os.environ.get(VARIABLE, "")
    on_path = shutil.which(EXECUTABLE_NAME)
    # The variable is held to the argument's rule: a relative path would resolve against the
    # server's working directory, which is nobody's project.
    if binary:
        origin, found = ARGUMENT, shutil.which(str(inputs.absolute("binary", binary)))
    elif held:
        origin, found = VARIABLE, shutil.which(str(inputs.absolute(VARIABLE, held)))
    else:
        origin, found = PATH_RUNG, on_path
    if found is None:
        named = f"{binary} ({why_not(binary)})" if origin == ARGUMENT else binary or "nothing"
        variable = f"{held} ({why_not(held)})" if origin == VARIABLE else held or "nothing"
        raise Invalid("bad_argument",
            f"no MAME binary resolves from the {origin} rung: the argument `binary` held "
            f"{named}, {VARIABLE} held {variable}, and the PATH holds "
            f"{on_path or f'no `{EXECUTABLE_NAME}`'}. The first rung holding a value is the one "
            f"taken, and it has to name an executable file")
    # THE PATH `which` APPROVED, unchanged: `abspath` collapses `..` by spelling, so through a
    # symlinked directory it would name another file. A relative PATH entry is joined, not
    # normalised, for the same reason.
    return Resolved(found if os.path.isabs(found) else os.path.join(os.getcwd(), found), origin)


def why_not(path: str) -> str:
    """Why a named path is no executable file, in the words its owner looks for: a file that is
    there without its exec bit is not missing."""
    if not os.path.exists(path):        # a dangling link included: nothing there to run
        return "no such file"
    if os.path.isdir(path):
        return "a directory"
    return "not executable"


def version(binary: str) -> str | dict[str, Any]:
    """The first line `<binary> -version` prints, or why there is none.

    A version is whatever line comes back, from either stream and whatever the exit code: the
    line is the answer, and an exit code a build chose for an informational option is not. What
    makes it unavailable is a spawn that failed, a timeout, or nothing printed. Its stdin is
    closed, so a build that reads it cannot take the server's own protocol stream."""
    try:
        got = subprocess.run([binary, "-version"], capture_output=True, text=True,
                             errors="replace", check=False, timeout=VERSION_TIMEOUT_S,
                             stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"available": False,
                "why": f"`{binary} -version` did not return in {VERSION_TIMEOUT_S:g} s"}
    except OSError as exc:
        return {"available": False, "why": f"`{binary} -version` could not run: {exc}"}
    for line in (got.stdout + "\n" + got.stderr).splitlines():
        if line.strip():
            return line.strip()
    return {"available": False,
            "why": f"`{binary} -version` printed nothing (rc={got.returncode})"}


def facts(resolved: Resolved) -> dict[str, Any]:
    """The three fields `start` answers."""
    return {"binary": resolved.path, "binary_origin": resolved.origin,
            "version": version(resolved.path)}
