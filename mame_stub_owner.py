"""Whose gdbstub a port serves, proved by the process that holds it and never by the port.

A connected stub leaves nothing listening on its port (`Session.dial`), so a second MAME told
the same port listens beside a live session, and a dial reaches whichever listens first: two
starts racing between a free-port probe and MAME's own bind both end up told one port, and each
drives the other's machine with neither reply saying so. So the pid this server spawned is
proved around the one dial:

- before it, the only listener on the port has to be that pid. A port nothing listens on is the
  boot under way (`NotListening`, an `OSError`, so the boot's wait goes on); any other pid
  listening is refused WITHOUT dialling, because the dial would take the one connection that
  other MAME serves;
- after it and before its first byte, the far end has to live in that same pid. MAME accepts
  only when its debugger first polls, so the connection can sit in the listen queue, owned by no
  process, for the rest of the boot: the proof waits for the accept, and a far end in another
  process is closed with nothing sent on it.

`bind_probe` answers whether a port is free at all, by binding it (`mame_launch` asks it for a
free port and of a port a caller names). The instrument that names the holder is `lsof` in its
declared field format (`-F`, one field per line, a letter
naming each), never its table. `-w` silences its warnings, so anything it prints on stderr is
an error: `lsof` answers 1 for "no match" and for a failure alike, and stderr is what tells
them apart. An `lsof` that is absent or broken is a host that cannot prove whose stub this is,
refused as such, never read as "nobody listens".
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

import gdb_session as gs

#: How long one `lsof` may take before it counts as broken: it answers in tens of milliseconds
#: on this kind of query, so five seconds is a hung instrument, not a slow one.
LSOF_TIMEOUT_S = 5.0

#: How often the accept is looked for after the dial: the boot it waits on takes seconds.
ACCEPT_POLL_S = 0.1


class StubNotOurs(gs.SessionError):
    """Another process serves the gdbstub's port: its listener before the dial (never dialled),
    or the far end of the connection after it (closed with nothing sent)."""

    def __init__(self, port: int, pids: list[int], ours: int) -> None:
        super().__init__(f"port {port} is served by pid {', '.join(map(str, pids))}, not by "
                         f"pid {ours}, the MAME this start launched: another emulator holds "
                         "it, and nothing was sent to it")
        self.port = port
        self.pids = pids


class StubUnproved(gs.SessionError):
    """Whose gdbstub the port serves could not be established: the instrument that proves it
    is absent or failed."""


class StubNotAccepted(gs.SessionError):
    """The connection was made and no process accepted it within the boot's bound: a stub that
    never answered, told apart from one that answered as somebody else's."""


class NotListening(OSError):
    """Nothing listens on the port yet: the boot has not reached the stub. An `OSError`, the
    family a refused connection already belongs to, so the boot's wait treats it as one."""


class MameGone(ConnectionAbortedError):
    """The MAME the proof waits on exited before it accepted: an `OSError`, so the boot reads
    it as the death it is, with its exit code, rather than waiting out its bound."""


def _fields(args: list[str]) -> list[str]:
    """`lsof`'s field lines for `args`, empty for an honest "no match"; `StubUnproved` for an
    `lsof` that is absent, hung, or said anything on stderr."""
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
    """THE ONE PROBE: bind `127.0.0.1:port` and let go at once, answering the port bound (the
    one the kernel chose, for 0) or None when the bind is refused. It asks by BIND and never by
    connecting: a connect CONSUMES the one connection a MAME's stub serves.

    SO_REUSEADDR IS NOT SET, and that is what makes the answer true. MAME's stub binds WITH it
    and closes its listener once it accepts, so a connected session leaves only its established
    socket on the port: a probe without the option is refused there, while one with it binds
    and calls free the port of a session still being served."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return None
        bound: int = s.getsockname()[1]
        return bound


def listeners(port: int) -> set[int]:
    """Every pid with a TCP socket LISTENING on `port`."""
    return {int(line[1:]) for line in _fields([f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"])
            if line.startswith("p")}


def accepted_by(port: int, local_port: int) -> set[int]:
    """Every pid holding the far end of the connection this process made from `local_port` to
    `port`: the socket whose own address is `port` and whose peer is `local_port`. This
    process's end, the reverse pair, is not counted."""
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
    """The proof `Session.dial` runs around its connection, for the MAME this server spawned:
    `alive` says whether that process still runs, `deadline` (`time.monotonic()`) is when the
    accept stops being waited for."""

    pid: int
    port: int
    deadline: float
    alive: Callable[[], bool]

    def before_dial(self) -> None:
        # THE CHEAP QUESTION FIRST: a port that binds holds no socket at all, which is every
        # poll of a boot that has not reached its stub yet, and costs no `lsof`.
        if bind_probe(self.port) is not None:     # nothing on it: `lsof` has nothing to say
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
