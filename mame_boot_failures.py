"""Launch failures before a session exists, and whether `start` launches again (REFERENCE.md)."""

from __future__ import annotations

import re
import signal
from typing import Any

from scry_core import reply_contract as contract

import gdb_session as gs
import mame_state as st

# The reason every refusal of a dial or a handshake gives for not dialling again.
ONE_CONNECTION = "MAME serves one connection per session, so a second is never dialled"


class LaunchFailed(st.Invalid):
    """A launch that failed before a session existed; `evidence()` is its `start_retries` entry
    (the scratch holding MAME's words is deleted with the attempt), `what` its progress line."""

    def __init__(self, message: str, what: str, evidence: dict[str, Any],
                 code: contract.Code = "session_broken", **fields: Any) -> None:
        super().__init__(code, message, **fields)
        self.what = what
        self._evidence = evidence

    def relaunch(self, port_picked: bool) -> bool:
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


# What the macOS libc prints before the SIGABRT of a failed assert; deterministic, so no relaunch.
ASSERTION_MARK = "Assertion failed"
# SDL3 joystick ids are unsigned, so a debug MAME asserts on a negative one once a controller is
# enumerated.
SDL3_JOYSTICK_MARK = "input_sdl3"
SDL3_JOYSTICK_NOTE = ("a debug MAME built with SDL3 aborts at boot when a game controller is "
                      "connected (an upstream regression in input_sdl3.cpp); `joystickprovider "
                      "none` in a mame.ini passed as `inipath` avoids it")


# Matched anywhere in a line: stdout shares the file and can leave a prompt with no newline.
_NOT_SERVED = re.compile(
    r"Fatal error: gdbstub: cpuname (\S+) not found in gdb stub descriptions$", re.MULTILINE)


def death_refusal(exit_code: int, after_s: float, stdout_tail: str) -> st.Invalid:
    """`no_channel` when the stub has no description of the first cpu (every launch meets it
    again), else `DiedBeforeStub`."""
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


_PORT_TAKEN = re.compile(r"Fatal error: gdbstub: failed to start listening on address \S+ port \d+")


class DiedBeforeStub(LaunchFailed):
    """A MAME that exited before its gdbstub answered. An exit code is MAME refusing the
    caller's input, so only a signal (not an assertion's abort) or `port_taken` relaunches."""

    def __init__(self, exit_code: int, after_s: float, stdout_tail: str) -> None:
        self.exit_code = exit_code
        self.stdout_tail = stdout_tail
        self.asserted = exit_code == -signal.SIGABRT and ASSERTION_MARK in stdout_tail
        note: dict[str, Any] = ({"note": SDL3_JOYSTICK_NOTE}
                if self.asserted and SDL3_JOYSTICK_MARK in stdout_tail else {})
        own: dict[str, Any] = {"exit_code": exit_code, "after_s": st.spent_s(after_s),
                               "stdout_tail": stdout_tail}
        ended = (f"died by signal {-exit_code}" if exit_code < 0
                 else f"exited with code {exit_code}")
        what = (f"MAME {ended}: another process held its gdbstub port"
                if self.port_taken() else f"MAME {ended} before its gdbstub answered")
        super().__init__(f"MAME exited with code {exit_code} after {after_s:.1f} s, before its "
                         "gdbstub answered: its own words are in `stdout_tail`", what,
                         {"kind": "died", **own}, **own, **note)

    def relaunch(self, port_picked: bool) -> bool:
        return (self.exit_code < 0 and not self.asserted) or (port_picked and self.port_taken())

    def port_taken(self) -> bool:
        """MAME's own line that another process held its gdbstub port."""
        return self.exit_code > 0 and _PORT_TAKEN.search(self.stdout_tail) is not None


# Handshake failures of a live process whose stub answered before it was ready.
NOT_READY_ERRORS = (gs.NoRegisters, gs.BadTargetXml, gs.Refused)


class StubNotReady(LaunchFailed):
    """A live MAME whose stub failed its handshake with one of `NOT_READY_ERRORS`."""

    def __init__(self, error: gs.SessionError, after_s: float, **live: Any) -> None:
        own: dict[str, Any] = {"error": type(error).__name__, "phase": error.phase,
                               "reply": error.reply, "after_s": st.spent_s(after_s)}
        super().__init__(f"{handshake_failed(error.phase, after_s, error)}; MAME was alive, so "
                         "its stub was not ready",
                         f"its gdbstub was not ready ({type(error).__name__} at {error.phase})",
                         {"kind": "stub_not_ready", **own, "stdout_tail": live["stdout_tail"]},
                         **own, **live)

    def relaunch(self, port_picked: bool) -> bool:
        return True


class PortServed(LaunchFailed):
    """Another process serves the gdbstub's port (`mame_stub_owner.StubNotOurs`); relaunches
    only when the port was this server's pick."""

    def __init__(self, error: gs.SessionError, port_picked: bool, **live: Any) -> None:
        then = ("launched again on another port" if port_picked
                else "your `stub_port` is another process's, so pick another or omit it")
        super().__init__(f"{error}. The launched MAME is killed; {then}",
                         "another process serves its gdbstub port",
                         {"kind": "port_served", "error": str(error)}, code="host_failed",
                         **live)
        self._picked = port_picked

    def relaunch(self, port_picked: bool) -> bool:
        return port_picked


def fold_attempt(attempts: list[dict[str, Any]], at_s: float, error: BaseException) -> None:
    """One dial attempt into `attempts`, folded into the last entry when its error is the same."""
    said = f"{type(error).__name__}: {error}"
    at = st.spent_s(at_s)
    if attempts and attempts[-1]["error"] == said:
        attempts[-1]["last_s"] = at
        attempts[-1]["count"] += 1
    else:
        attempts.append({"first_s": at, "last_s": at, "count": 1, "error": said})
