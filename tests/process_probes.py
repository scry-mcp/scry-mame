"""Real processes for socket-holder and pid-lifetime cases."""

import subprocess
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


def alive(pid: int) -> bool:
    """Whether `pid` runs, zombies excluded."""
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
