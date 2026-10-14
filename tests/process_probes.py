"""Real processes for the cases about which process holds a socket or outlives another: a
listener that is not MAME, and the questions asked of a pid. Shared by the unit tests and the
live matrix, which both need a process no double can stand for."""

import subprocess
import sys
import time

# A listener in its own process. It prints its port; in `accept` mode it accepts within its
# timeout and prints the first byte the connection brings (`b''` for a connection closed unread),
# or `none` when no connection came; in `hold` mode it never accepts.
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
    """A `LISTENER` process and its port; the caller kills it."""
    proc = subprocess.Popen([sys.executable, "-c", LISTENER, mode, str(timeout_s)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    return proc, int(proc.stdout.readline())


def heard(proc: subprocess.Popen[str]) -> str:
    """What an `accept`-mode listener printed after its port: `none` (nothing connected), the
    first byte's repr, or `silent`. Blocks until it prints, which its timeout bounds."""
    assert proc.stdout is not None
    line: str = proc.stdout.readline().strip()
    return line


def alive(pid: int) -> bool:
    """Whether `pid` runs: present, and not a zombie waiting to be reaped."""
    stat = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
                          text=True, check=False).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


def parent_of(pid: int) -> int | None:
    out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True,
                         check=False).stdout.strip()
    return int(out) if out else None


def gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False
