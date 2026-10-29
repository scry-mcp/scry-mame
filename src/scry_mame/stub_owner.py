"""Whose gdbstub a port serves, proved by the process that holds it and never by the port.

A connected stub leaves nothing listening, so racing starts can share a port. Before
the dial the only listener must be the spawned pid (a dial takes its one connection); after
it the far end must live in that pid. The instrument is `lsof` on POSIX and the OS's own TCP
table on Windows (`GetExtendedTcpTable`); a missing or broken one is refused, never read as
"nobody listens". Windows lists a connection still in the listener's queue as the listener's, so
there the far end is proved to be that pid's, but not yet that it accepted.
"""

from __future__ import annotations

import shutil
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from scry_mame import gdb_session as gs

LSOF_TIMEOUT_S = 5.0

ACCEPT_POLL_S = 0.1

#: Windows' TCP table: the class whose rows name their owning pid, the two states read, and the
#: row layouts Microsoft documents (`MIB_TCPROW_OWNER_PID`, `MIB_TCP6ROW_OWNER_PID`).
TCP_TABLE_OWNER_PID_ALL = 5
TCP_LISTEN, TCP_ESTABLISHED = 2, 5
_ROWS: dict[int, struct.Struct] = {socket.AF_INET: struct.Struct("<6I"),
                                  socket.AF_INET6: struct.Struct("<16sII16sIIII")}
#: The table can grow between the call that sizes it and the one that fills it.
TABLE_TRIES = 4


class StubNotOurs(gs.SessionError):
    """Another process serves the gdbstub's port."""

    def __init__(self, port: int, pids: list[int], ours: int) -> None:
        super().__init__(f"port {port} is served by pid {', '.join(map(str, pids))}, not by "
                         f"pid {ours}, the MAME this start launched: another emulator holds "
                         "it, and nothing was sent to it")
        self.port = port
        self.pids = pids


class StubUnproved(gs.SessionError):
    """The instrument that proves the owner (`lsof`, or Windows' TCP table) is absent or failed."""


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


@dataclass(frozen=True)
class TcpRow:
    """One row of Windows' TCP table: its state, its two ports in host order, its pid."""

    state: int
    local: int
    remote: int
    pid: int


def tcp_rows(table: bytes, family: int) -> list[TcpRow]:
    """The rows of one `GetExtendedTcpTable` answer; `StubUnproved` if it holds fewer."""
    row = _ROWS[family]
    count = struct.unpack_from("<I", table)[0] if len(table) >= 4 else -1
    if count < 0 or 4 + count * row.size > len(table):
        raise StubUnproved(f"the TCP table claims {count} rows in {len(table)} bytes")
    rows = []
    for i in range(count):
        f = row.unpack_from(table, 4 + i * row.size)
        state, local, remote, pid = ((f[0], f[2], f[4], f[5]) if family == socket.AF_INET
                                     else (f[6], f[2], f[5], f[7]))
        rows.append(TcpRow(state, socket.ntohs(local & 0xFFFF), socket.ntohs(remote & 0xFFFF),
                           pid))
    return rows


def _tcp_table(family: int) -> bytes:
    """Windows' TCP table for `family`, as `GetExtendedTcpTable` answers it."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        get = ctypes.WinDLL("iphlpapi.dll").GetExtendedTcpTable
        get.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                        wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
        get.restype = wintypes.DWORD
        size = wintypes.DWORD(0)
        rc = get(None, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0)
        for _ in range(TABLE_TRIES):
            buf = ctypes.create_string_buffer(max(size.value, 4))
            rc = get(buf, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0)
            if rc == 0:
                return buf.raw
        raise StubUnproved(f"`GetExtendedTcpTable` answered {rc}, so no process can be "
                           "proved to serve the gdbstub's port")
    else:
        raise StubUnproved("the TCP table is read on Windows only")


def _windows_rows() -> list[TcpRow]:
    """Both families' rows; an IPv6 table that will not read (IPv6 removed) is skipped, never
    the IPv4 one the gdbstub listens in."""
    rows: list[TcpRow] = []
    for family in _ROWS:
        try:
            table = _tcp_table(family)
        except StubUnproved:
            if family != socket.AF_INET6:
                raise
            continue
        rows += tcp_rows(table, family)
    return rows


def bind_probe(port: int) -> int | None:
    """Bind `127.0.0.1:port` and release it: the bound port, or None if refused.

    SO_REUSEADDR stays unset: MAME sets it, so a probe with it calls a served port free. Windows
    binds a port only a connection holds, so there the TCP table is asked too."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return None
        bound: int = s.getsockname()[1]
    if sys.platform == "win32" and any(r.local == bound for r in _windows_rows()):
        return None
    return bound


def listeners(port: int) -> set[int]:
    """Every pid listening on `port`."""
    if sys.platform == "win32":
        return {r.pid for r in _windows_rows() if r.state == TCP_LISTEN and r.local == port}
    else:
        return {int(line[1:]) for line in _fields([f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"])
                if line.startswith("p")}


def accepted_by(port: int, local_port: int) -> set[int]:
    """Every pid holding the far end of the connection made from `local_port` to `port`."""
    if sys.platform == "win32":
        return {r.pid for r in _windows_rows() if r.state == TCP_ESTABLISHED
                and r.local == port and r.remote == local_port}
    else:
        holders: set[int] = set()
        pid = 0
        for line in _fields([f"-iTCP:{port}", "-sTCP:ESTABLISHED", "-Fpn"]):
            if line.startswith("p"):
                pid = int(line[1:])
            elif line.startswith("n") and "->" in line:
                near, far = line[1:].split("->", 1)
                if (near.rsplit(":", 1)[-1] == str(port)
                        and far.rsplit(":", 1)[-1] == str(local_port)):
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
        # A port that binds holds no socket, so boot polls skip `lsof`; Windows asks its TCP table.
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
