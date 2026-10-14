"""What a launch that failed before its session existed says, and whether `start` launches it
again.

`mame_launch.boot` raises a `LaunchFailed` for the failures `start` may launch again; `start`
launches again while `relaunch()` says so, under its cap, and keeps each one's `evidence()` in
`start_retries`, because the scratch holding MAME's words is deleted with the attempt. Which
failures are launched again, and why those, is `REFERENCE.md`, *The session*. `fold_attempt`
keeps the dial attempts of one boot.
"""

from __future__ import annotations

import re
import signal
from typing import Any

import gdb_session as gs
import mame_state as st

# The reason every refusal of a dial or a handshake gives for not dialling again.
ONE_CONNECTION = "MAME serves one connection per session, so a second is never dialled"


class LaunchFailed(st.Invalid):
    """`session_broken` for a launch that failed before a session existed. `relaunch()` says
    whether launching again can change the answer (never, unless a subclass says so),
    `evidence()` is its `start_retries` entry and `what` its relaunch's progress line."""

    def __init__(self, message: str, what: str, evidence: dict[str, Any],
                 **fields: Any) -> None:
        super().__init__("session_broken", message, **fields)
        self.what = what
        self._evidence = evidence

    def relaunch(self) -> bool:
        return False

    @property
    def kind(self) -> str:
        return str(self._evidence["kind"])

    def evidence(self) -> dict[str, Any]:
        return self._evidence


def handshake_failed(phase: str, after_s: float, error: BaseException) -> str:
    """What every refusal of a handshake says first: where it failed, after how long, and why."""
    return (f"the gdbstub accepted the connection and its handshake failed at {phase} after "
            f"{after_s:.1f} s: {error}")


# WHAT A FAILED `assert` PRINTS before its SIGABRT, as the macOS libc spells it. An assertion is
# deterministic: the same build aborts the same way on every launch, so a relaunch buys nothing
# but another identical death.
ASSERTION_MARK = "Assertion failed"
# SDL3's joystick ids are unsigned, so a debug MAME asserting one negative aborts at boot as soon
# as a controller is enumerated; the ini line is what a caller can do about it without a rebuild.
SDL3_JOYSTICK_MARK = "input_sdl3"
SDL3_JOYSTICK_NOTE = ("a debug MAME built with SDL3 aborts at boot when a game controller is "
                      "connected (an upstream regression in input_sdl3.cpp); `joystickprovider "
                      "none` in a mame.ini passed as `inipath` avoids it")


# A stub without the thread patch, at its first stop, describes the board's FIRST cpu or ends
# MAME with this fatal error, on every launch. Matched anywhere in a line: stdout shares the file
# and can leave a console prompt with no newline before it.
_NOT_SERVED = re.compile(
    r"Fatal error: gdbstub: cpuname (\S+) not found in gdb stub descriptions$", re.MULTILINE)


def death_refusal(exit_code: int, after_s: float, stdout_tail: str) -> st.Invalid:
    """What a MAME that ended before its gdbstub answered is refused as: `no_channel` when its
    stub said it has no description of the first cpu, which every launch would meet again;
    else `DiedBeforeStub`."""
    if m := _NOT_SERVED.search(stdout_tail):
        ended = (f"died by signal {-exit_code}" if exit_code < 0
                 else f"exited with code {exit_code}")
        return st.Invalid("no_channel",
                          f"this MAME's gdbstub has no description of the first cpu, "
                          f"{m.group(1)}, and said so: `{m.group(0)}`; MAME then {ended} after "
                          f"{after_s:.1f} s. Not launched again: what serves this board is a "
                          "build whose stub describes that cpu, or one carrying "
                          "`patches/0004-gdbstub-one-thread-per-cpu.patch`, whose stub leaves an "
                          "undescribed cpu's registers unserved instead of ending MAME",
                          exit_code=exit_code, after_s=st.spent_s(after_s),
                          stdout_tail=stdout_tail)
    return DiedBeforeStub(exit_code, after_s, stdout_tail)


class DiedBeforeStub(LaunchFailed):
    """A MAME that EXITED before its gdbstub answered. Launched again when a signal ended it,
    other than an assertion's abort; an exit code is MAME refusing what the caller gave it, and
    would answer the same again."""

    def __init__(self, exit_code: int, after_s: float, stdout_tail: str) -> None:
        self.exit_code = exit_code
        self.asserted = exit_code == -signal.SIGABRT and ASSERTION_MARK in stdout_tail
        note = ({"note": SDL3_JOYSTICK_NOTE}
                if self.asserted and SDL3_JOYSTICK_MARK in stdout_tail else {})
        own = {"exit_code": exit_code, "after_s": st.spent_s(after_s), "stdout_tail": stdout_tail}
        ended = (f"died by signal {-exit_code}" if exit_code < 0
                 else f"exited with code {exit_code}")
        super().__init__(f"MAME exited with code {exit_code} after {after_s:.1f} s, before its "
                         "gdbstub answered: its own words are in `stdout_tail`",
                         f"MAME {ended} before its gdbstub answered",
                         {"kind": "died", **own}, **own, **note)

    def relaunch(self) -> bool:
        return self.exit_code < 0 and not self.asserted


# The handshake failures of a LIVE process that mean its stub answered before it was ready,
# rather than a stub that hung (`Timeout`), a packet it lacks (`Unsupported`) or a channel gone.
NOT_READY_ERRORS = (gs.NoRegisters, gs.BadTargetXml, gs.Refused)


class StubNotReady(LaunchFailed):
    """A live MAME whose stub answered its handshake with one of `NOT_READY_ERRORS`: launched
    again like a death, under the same cap. `live` is what a refusal of the wait for the stub
    carries, `stdout_tail` among it."""

    def __init__(self, error: gs.SessionError, after_s: float, **live: Any) -> None:
        own = {"error": type(error).__name__, "phase": error.phase, "reply": error.reply,
               "after_s": st.spent_s(after_s)}
        super().__init__(f"{handshake_failed(error.phase, after_s, error)}; MAME was alive, so "
                         "its stub was not ready",
                         f"its gdbstub was not ready ({type(error).__name__} at {error.phase})",
                         {"kind": "stub_not_ready", **own, "stdout_tail": live["stdout_tail"]},
                         **own, **live)

    def relaunch(self) -> bool:
        return True


def fold_attempt(attempts: list[dict[str, Any]], at_s: float, error: BaseException) -> None:
    """One dial attempt into `attempts`, folded into the last entry when its error is the same:
    a boot's whole run stays a few entries, each with its first and last time (seconds from the
    launch) and its count, so a stub that never listened is told from one that listened and was
    refused later."""
    said = f"{type(error).__name__}: {error}"
    at = st.spent_s(at_s)
    if attempts and attempts[-1]["error"] == said:
        attempts[-1]["last_s"] = at
        attempts[-1]["count"] += 1
    else:
        attempts.append({"first_s": at, "last_s": at, "count": 1, "error": said})
