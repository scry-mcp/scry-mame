"""The guardian (`mame_guardian`), against REAL processes: whether a child outlives its parent
is a property of processes. Its "MAME" is `sleep`, and its "server" an interpreter these cases
SIGKILL, the ending that runs no `finally`."""

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from process_probes import alive, gone_within  # noqa: E402

import mame_guardian as guardian  # noqa: E402
import mame_state as mstate  # noqa: E402

HERE = Path(__file__).resolve().parent.parent

# The server stand-in: spawns the "MAME" and its guardian as `boot` does (unless told not to,
# for the control), prints both pids, and waits to be killed.
SERVER = f"""
import subprocess, sys, time
sys.path.insert(0, {str(HERE)!r})
import mame_guardian as guardian
mame = subprocess.Popen(["sleep", "60"])
guard = guardian.spawn(mame) if sys.argv[1] == "guarded" else None
print(mame.pid, guard.pid if guard else 0, flush=True)
time.sleep(60)
"""

WITHIN_S = 5 * guardian.GUARDIAN_POLL_S


def _server(mode: str = "guarded") -> tuple[subprocess.Popen[str], int, int]:
    proc = subprocess.Popen([sys.executable, "-c", SERVER, mode], stdout=subprocess.PIPE,
                            text=True)
    assert proc.stdout is not None
    mame, guard = (int(n) for n in proc.stdout.readline().split())
    return proc, mame, guard


def _reap(*pids: int) -> None:
    for pid in pids:
        if pid and alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_a_sigkilled_server_takes_its_mame_with_it() -> None:
    proc, mame, guard = _server()
    try:
        proc.send_signal(signal.SIGKILL)
        proc.wait()
        assert gone_within(mame, WITHIN_S), "the MAME outlived its server"
        assert gone_within(guard, WITHIN_S), "the guardian lingered"
    finally:
        _reap(mame, guard)


def test_without_a_guardian_the_mame_outlives_its_server() -> None:
    """THE CONTROL: the same ending with no guardian leaves the child running under init, so
    the case above is the guardian's doing and not the child dying with its parent."""
    proc, mame, _ = _server("bare")
    try:
        proc.send_signal(signal.SIGKILL)
        proc.wait()
        assert not gone_within(mame, WITHIN_S), "the child died on its own"
    finally:
        _reap(mame)


def test_a_live_server_keeps_its_mame() -> None:
    """The guardian kills only on the parent's death, never on a timer."""
    proc, mame, guard = _server()
    try:
        assert not gone_within(mame, 3 * guardian.GUARDIAN_POLL_S)
        assert alive(guard)
    finally:
        proc.kill()
        proc.wait()
        gone_within(mame, WITHIN_S)
        _reap(mame, guard)


def test_the_guardian_leaves_when_its_mame_does() -> None:
    mame = subprocess.Popen(["sleep", "60"])
    guard = guardian.spawn(mame)
    assert guard is not None
    mame.kill()
    mame.wait()
    assert guard.wait(timeout=WITHIN_S) == 0


def test_no_guardian_for_a_process_this_server_did_not_spawn() -> None:
    """The guardian kills BY PID, and a stand-in's pid may be anybody's (init's, in the
    doubles)."""

    class Double:
        pid = 1

    assert guardian.spawn(Double()) is None


def test_kill_stops_the_guardian_only_once_the_mame_is_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stopped first, a server dying in between would leave the MAME unwatched: the guardian is
    stopped after the MAME is reaped, and it is stopped (not left to notice on its own)."""
    state = mstate.State()
    state.proc = subprocess.Popen(["sleep", "60"])
    mame = state.proc
    state.guard = guardian.spawn(mame)
    guard = state.guard
    seen: list[tuple[bool, object]] = []
    real_stop = guardian.stop

    def stop(g: subprocess.Popen[bytes] | None) -> None:
        seen.append((mame.poll() is not None, g))
        real_stop(g)

    monkeypatch.setattr(guardian, "stop", stop)
    state.kill(grace=False)
    assert seen == [(True, guard)], seen
    assert guard is not None and guard.poll() is not None and state.guard is None
