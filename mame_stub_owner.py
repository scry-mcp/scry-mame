"""Whose gdbstub a port serves, proved by the process that holds it and never by the port.

A connected stub leaves nothing listening, so racing starts can share a port. Before
the dial the only listener must be the spawned pid (a dial takes its one connection); after
it the far end must live in that pid. A missing or broken `lsof` is refused, never read
as "nobody listens".
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

import gdb_session as gs

LSOF_TIMEOUT_S = 5.0

ACCEPT_POLL_S = 0.1


class StubNotOurs(gs.SessionError):
    """Another process serves the gdbstub's port."""

    def __init__(self, port: int, pids: list[int], ours: int) -> None:
        super().__init__(f"port {port} is served by pid {', '.join(map(str, pids))}, not by "
                         f"pid {ours}, the MAME this start launched: another emulator holds "
                         "it, and nothing was sent to it")
        self.port = port
        self.pids = pids


class StubUnproved(gs.SessionError):
    """`lsof` is absent or failed."""


class StubNotAccepted(gs.SessionError):
    """No process accepted the connection in time."""


class NotListening(OSError):
    """Nothing listens yet; an `OSError` so the boot keeps waiting."""


class MameGone(ConnectionAbortedError):
    """The MAME exited before it accepted."""


def _fields(args: list[str]) -> list[str]:
    """`lsof`'s field lines, empty for "no match"; `StubUnproved` if absent, hung or noisy."""
    lsof = shutil.which("lsof")
    if lsof is None:
        raise StubUnproved("`lsof` is not on this host's PATH, and it is the instrument that "
                           "proves which process serves the gdbstub's port")
    try:
        done = subprocess.run([lsof, "-w", "-nP", *args], capture_output=True, text=True,
                              check=False, timeout=LSOF_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise StubUnproved(f"`lsof` could not be run: {e}") from e
    if done.returncode not in (0, 1) or done.stderr.strip():
        raise StubUnproved(f"`lsof` answered exit code {done.returncode} and printed "
                           f"{done.stderr.strip() or 'nothing'!r} on stderr")
    return done.stdout.splitlines()


def bind_probe(port: int) -> int | None:
    """Bind `127.0.0.1:port` and release it: the bound port, or None if refused.

    SO_REUSEADDR stays unset: MAME sets it, so a probe with it calls a served port free."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return None
        bound: int = s.getsockname()[1]
        return bound


def listeners(port: int) -> set[int]:
    """Every pid listening on `port`."""
    return {int(line[1:]) for line in _fields([f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"])
            if line.startswith("p")}


def accepted_by(port: int, local_port: int) -> set[int]:
    """Every pid holding the far end of the connection made from `local_port` to `port`."""
    holders: set[int] = set()
    pid = 0
    for line in _fields([f"-iTCP:{port}", "-sTCP:ESTABLISHED", "-Fpn"]):
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and "->" in line:
            near, far = line[1:].split("->", 1)
            if near.rsplit(":", 1)[-1] == str(port) and far.rsplit(":", 1)[-1] == str(local_port):
                holders.add(pid)
    return holders


@dataclass
class StubOwner:
    """The proof `Session.dial` runs around its connection."""

    pid: int
    port: int
    deadline: float
    alive: Callable[[], bool]

    def before_dial(self) -> None:
        # A port that binds holds no socket, so boot polls skip `lsof`.
        if bind_probe(self.port) is not None:
            raise NotListening(f"nothing listens on port {self.port} yet")
        holders = listeners(self.port)
        if holders - {self.pid}:
            raise StubNotOurs(self.port, sorted(holders - {self.pid}), self.pid)
        if self.pid not in holders:
            raise NotListening(f"nothing listens on port {self.port} yet")

    def after_dial(self, local_port: int) -> None:
        while True:
            holders = accepted_by(self.port, local_port)
            if holders == {self.pid}:
                return
            if holders:
                raise StubNotOurs(self.port, sorted(holders), self.pid)
            if not self.alive():
                raise MameGone(f"pid {self.pid} exited before it accepted the connection")
            if time.monotonic() >= self.deadline:
                raise StubNotAccepted(f"the connection to port {self.port} was made and no "
                                      "process accepted it within the boot's bound")
            time.sleep(ACCEPT_POLL_S)
