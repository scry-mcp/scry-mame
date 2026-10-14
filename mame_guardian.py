"""The guardian: a MAME this server spawned dies with it, however the server ends.

MAME has no reason of its own to exit (end-of-file on its Lua console only stops the console,
and a dropped stub connection leaves the machine running), and a server that is SIGKILLed or
crashes runs no `finally`, so its MAME would run on under init. The guardian is a small process
beside every MAME, in a session of its own so a signal to the server's process group does not
take it down with the server. It polls its parent: the moment it is reparented, the server is
gone, and it SIGKILLs the MAME, since MAME ignores SIGTERM (`State.kill`). The server stops it at
every `close`, so it outlives no session it watches.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys

#: The guardian's whole program: watch the parent, kill the MAME if the parent goes, leave when
#: the MAME does. `os.getppid` changing is the test, never `kill(server, 0)`, because a dead
#: server's pid can be reused and a reparented process cannot be un-reparented.
GUARDIAN = """
import os, signal, sys, time
server, mame = int(sys.argv[1]), int(sys.argv[2])
while True:
    try:
        os.kill(mame, 0)
    except ProcessLookupError:
        break
    if os.getppid() != server:
        os.kill(mame, signal.SIGKILL)
        break
    time.sleep(float(sys.argv[3]))
"""

#: How often the guardian looks: a second, against an emulator that would otherwise run until
#: reboot.
GUARDIAN_POLL_S = 1.0

#: How long `stop` waits for the SIGKILLed guardian to be reaped.
STOP_GRACE_S = 5.0

#: `Popen` as this module found it. The guardian kills BY PID, so it watches only a process
#: that is this server's own child: anything else (a stand-in whose pid may be anybody's)
#: gets none.
_POPEN = subprocess.Popen


def spawn(mame: object) -> subprocess.Popen[bytes] | None:
    """The guardian for `mame`, a child of this server in a session of its own; None for a
    process this server did not spawn itself."""
    if not isinstance(mame, _POPEN):
        return None
    return _POPEN(
        [sys.executable, "-c", GUARDIAN, str(os.getpid()), str(mame.pid), str(GUARDIAN_POLL_S)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)


def stop(guard: subprocess.Popen[bytes] | None) -> None:
    """End a guardian, once the MAME it watches is ended or given up on: stopped before, a
    server dying in between would leave that MAME with nothing watching it."""
    if guard is None:
        return
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        guard.kill()
        guard.wait(timeout=STOP_GRACE_S)
