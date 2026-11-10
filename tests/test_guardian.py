import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from scry_core import guardian, host_program

from scry_mame import launch  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


def _watched_mame() -> mstate.State:
    """A session's state holding a process that sleeps and its guardian."""
    state = mstate.State()
    state.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    state.guard = guardian.spawn(state.proc, launch.PROCESS_NAME)
    return state


def test_kill_stops_the_guardian_only_once_the_mame_is_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stopped before the MAME is reaped, a dying server would leave it unwatched."""
    state = _watched_mame()
    mame, guard = state.proc, state.guard
    assert isinstance(mame, subprocess.Popen)
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
    state = _watched_mame()
    mame, guard = state.proc, state.guard
    assert isinstance(mame, subprocess.Popen)
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


def test_kill_ends_what_the_mame_started_before_it_removes_the_scratch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A process the MAME started holds the log open on Windows until the guardian ends it."""
    state = _watched_mame()
    scratch = state.scratch = tmp_path / "mame-mcp-scratch"
    scratch.mkdir()
    there: list[bool] = []
    real_stop = guardian.stop

    def stop(g: guardian.Guard | None) -> None:
        there.append(scratch.exists())
        real_stop(g)

    monkeypatch.setattr(guardian, "stop", stop)
    state.kill(grace=False)
    assert there == [True], "the scratch went while the guardian still held the MAME's own"
    assert not scratch.exists()


def test_kill_removes_the_scratch_of_a_mame_started_through_a_launcher(tmp_path: Path) -> None:
    """Windows runs the double behind a launcher, and with no guardian only `kill` can end it.
    Elsewhere the double is the process itself."""
    state = mstate.State()
    scratch = state.scratch = tmp_path / "mame-mcp-scratch"
    scratch.mkdir()
    booted = tmp_path / "booted"
    binary = host_program.write(
        tmp_path / "slow-mame",
        f"import time\nfrom pathlib import Path\nPath({str(booted)!r}).touch()\ntime.sleep(60)\n")
    with (scratch / "stdout.log").open("wb") as log:
        state.proc = subprocess.Popen([str(binary)], stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 20
    while not booted.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert booted.exists(), "the double never ran"
    state.kill(grace=False)
    assert not scratch.exists(), sorted(p.name for p in scratch.iterdir())


def test_on_windows_kill_ends_what_a_real_process_started_and_follows_no_other_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tree is followed by pid, so only a process this server made is followed."""
    ran: list[list[str]] = []

    class Double:
        pid, killed = 4242, False

        def kill(self) -> None:
            self.killed = True

    real = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    double = Double()
    try:
        with monkeypatch.context() as host:
            host.setattr(sys, "platform", "win32")
            host.setattr(subprocess, "run", lambda argv, **_k: ran.append(argv))
            mstate.end(real)
            mstate.end(double)  # type: ignore[arg-type]
        assert ran == [["taskkill", "/F", "/T", "/PID", str(real.pid)]], ran
        assert real.wait(timeout=10) is not None, "the process itself is killed as well"
        assert double.killed
    finally:
        real.kill()
        real.wait()


def test_a_scratch_a_dying_process_still_holds_is_removed_once_it_lets_go(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch = tmp_path / "mame-mcp-scratch"
    scratch.mkdir()
    real, calls = shutil.rmtree, []

    def held_twice(path: Path, ignore_errors: bool = False) -> None:
        calls.append(path)
        if len(calls) > 2:
            real(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(shutil, "rmtree", held_twice)
    monkeypatch.setattr(mstate, "SCRATCH_POLL_S", 0.01)
    mstate._remove(scratch)
    assert calls == [scratch] * 3 and not scratch.exists()


def test_a_scratch_that_never_goes_is_given_up_at_the_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch = tmp_path / "mame-mcp-scratch"
    scratch.mkdir()
    calls: list[Path] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))
    monkeypatch.setattr(mstate, "SCRATCH_POLL_S", 0.01)
    monkeypatch.setattr(mstate, "SCRATCH_GONE_S", 0.2)
    began = time.monotonic()
    mstate._remove(scratch)
    took = time.monotonic() - began
    assert 0.2 <= took < 2.0 and 2 < len(calls) < 60, (took, len(calls))
