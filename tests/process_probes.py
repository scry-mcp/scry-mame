"""Real processes for socket-holder and pid-lifetime cases."""

import subprocess
import sys
import time

from scry_core import host_program

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


def alive(pid: int) -> bool:
    """Whether `pid` runs, zombies excluded."""
    if sys.platform == "win32":
        return _win_alive(pid)
    else:
        stat = _ps("stat", pid)
        return stat is not None and not stat.startswith("Z")


def parent_of(pid: int) -> int | None:
    if sys.platform == "win32":
        return _win_parent(pid)
    else:
        out = _ps("ppid", pid)
        return int(out) if out else None


SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x102
TH32CS_SNAPPROCESS = 0x2
ERROR_ACCESS_DENIED = 5


def _win_alive(pid: int) -> bool:
    """A process object still unsignalled; one the user may not open exists all the same."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        handle = k32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return bool(ctypes.get_last_error() == ERROR_ACCESS_DENIED)
        try:
            return bool(k32.WaitForSingleObject(wintypes.HANDLE(handle), 0) == WAIT_TIMEOUT)
        finally:
            k32.CloseHandle(wintypes.HANDLE(handle))
    else:
        raise OSError("a Windows probe")


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
