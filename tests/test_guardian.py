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
    """Stopped before the MAME is reaped, a dying server would leave it unwatched."""
    state = mstate.State()
    state.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    mame = state.proc
    state.guard = guardian.spawn(mame, launch.PROCESS_NAME)
    guard = state.guard
    seen: list[tuple[bool, object]] = []
    real_stop = guardian.stop

    def stop(g: guardian.Guard | None) -> None:
        seen.append((mame.poll() is not None, g))
        real_stop(g)

    monkeypatch.setattr(guardian, "stop", stop)
    state.kill(grace=False)
    assert seen == [(True, guard)], seen
    assert guard is not None and guard.poll() is not None and state.guard is None



def test_a_mame_still_unreaped_after_its_kill_keeps_its_guardian(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreaped MAME may still exist, so `kill` leaves its guardian running."""
    state = mstate.State()
    state.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    mame = state.proc
    state.guard = guardian.spawn(mame, launch.PROCESS_NAME)
    guard = state.guard
    monkeypatch.setattr(mstate, "wait_exit", lambda *_a, **_k: None)   # never reaped
    monkeypatch.setattr(mame, "kill", lambda: None)
    monkeypatch.setattr(mame, "poll", lambda: None)
    try:
        ended = state.kill(grace=False)
        assert "not reaped" in str(ended["exit_code"])
        assert guard is not None and guard.poll() is None, "the guardian was stopped"
    finally:
        subprocess.Popen.kill(mame)
        subprocess.Popen.wait(mame)
        guardian.stop(guard)
    assert launch.GUARDIAN_NAME == "scry-mame-guardian"
