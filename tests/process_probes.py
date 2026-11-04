"""Real processes for socket-holder and pid-lifetime cases."""

import subprocess
import sys
import time

from scry_core import host_program
from scry_core.live_host import COMM_MAX
from scry_core.process_tree import pid_alive as alive

# `accept` mode prints the first byte received, or `none`; `hold` mode never accepts.
LISTENER = """
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 0))
s.listen(1)
print(s.getsockname()[1], flush=True)
if sys.argv[1] == "accept":
    s.settimeout(float(sys.argv[2]))
    try:
        c, _ = s.accept()
    except OSError:
        print("none", flush=True)
    else:
        c.settimeout(float(sys.argv[2]))
        try:
            print(repr(c.recv(1)), flush=True)
        except OSError:
            print("silent", flush=True)
sys.stdin.read()
"""


def listener(mode: str = "accept", timeout_s: float = 2.0) -> tuple[subprocess.Popen[str], int]:
    """A `LISTENER` process and its port."""
    # the pid the socket names, not a launcher's: the cases compare the two
    proc = subprocess.Popen([host_program.INTERPRETER, "-c", LISTENER, mode, str(timeout_s)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    return proc, int(proc.stdout.readline())


def heard(proc: subprocess.Popen[str]) -> str:
    """What an `accept`-mode listener printed."""
    assert proc.stdout is not None
    line: str = proc.stdout.readline().strip()
    return line


def _ps(field: str, pid: int) -> str | None:
    """`ps`'s `field` for `pid`, or None for a pid it does not list (rc 1); any other rc is an
    error, which must not read as a process that is gone."""
    done = subprocess.run(["ps", "-o", f"{field}=", "-p", str(pid)], capture_output=True,
                          text=True, check=False)
    if done.returncode not in (0, 1):
        raise OSError(f"ps answered rc={done.returncode}: {done.stderr.strip()}")
    return done.stdout.strip() or None


def parent_of(pid: int) -> int | None:
    if sys.platform == "win32":
        return _win_parent(pid)
    else:
        out = _ps("ppid", pid)
        return int(out) if out else None


def children_named(parent: int, name: str) -> list[int]:
    """The pids of `parent`'s children the process table lists under `name`, or under the cut Linux
    gives a long one (POSIX; `ps` rc 0)."""
    table = subprocess.run(["ps", "-c", "-axo", "pid=,ppid=,comm="], capture_output=True,
                           text=True, errors="replace", check=True).stdout.splitlines()
    rows = [line.split(None, 2) for line in table]
    shown = (name, name[:COMM_MAX])
    return [int(r[0]) for r in rows if len(r) == 3 and r[1] == str(parent) and r[2] in shown]


TH32CS_SNAPPROCESS = 0x2


def _win_parent(pid: int) -> int | None:
    """The parent a toolhelp snapshot lists for `pid`, None when it lists no such process."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap in (None, wintypes.HANDLE(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(Entry)
            more = k32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(entry))
            while more:
                if entry.th32ProcessID == pid:
                    return int(entry.th32ParentProcessID)
                more = k32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(entry))
            return None
        finally:
            k32.CloseHandle(wintypes.HANDLE(snap))
    else:
        raise OSError("a Windows probe")


def gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False

__all__ = ["alive", "gone_within", "heard", "listener", "parent_of"]
