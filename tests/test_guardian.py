"""The guardian beside this server's MAME (`scry_core.guardian`, whose own suite holds what it
does to processes): `kill` stops it only once the MAME it watches is ended."""

import subprocess
import sys
from pathlib import Path

import pytest
from scry_core import guardian

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_launch as launch  # noqa: E402
import mame_state as mstate  # noqa: E402


def test_kill_stops_the_guardian_only_once_the_mame_is_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stopped first, a server dying in between would leave the MAME unwatched: the guardian is
    stopped after the MAME is reaped, and it is stopped (not left to notice on its own)."""
    state = mstate.State()
    state.proc = subprocess.Popen(["sleep", "60"])
    mame = state.proc
    state.guard = guardian.spawn(mame, launch.GUARDIAN_NAME)
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

