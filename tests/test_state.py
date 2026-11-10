"""`state`'s arithmetic and bookkeeping, held on a clock this file moves by hand.
"""

import os
from pathlib import Path
from typing import Any

import pytest

from scry_mame import files  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


class _Clock:
    """`time.monotonic` as a number the case sets."""

    def __init__(self, at: float = 100.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr("scry_mame.state.time.monotonic", c)
    return c


def test_two_starts_of_one_process_in_one_second_never_share_an_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mstate, "now", lambda: "2026-01-01T00:00:00+00:00")
    fresh = mstate.State()
    first, second = fresh.origin(), fresh.origin()
    assert first != second, "the promise is that they differ; how they are numbered is not"
    fresh.kill()
    assert fresh.origin() not in (first, second), "nor across a close, which keeps the counter"


def test_the_last_stop_is_dated_in_tenths_of_a_second_since_it(clock: _Clock) -> None:
    fresh = mstate.State()
    assert fresh.as_of() == {"available": False, "why": "this session has not stopped yet"}
    fresh.last_stop = {"seq": 3, "pc": "0x000004a0", "cpu": ":subcpu", "frame": 9,
                       "cause": "step 1", "when": clock.at, "wall_at": "c"}
    clock.at += 2.345
    assert fresh.as_of() == {"stop_seq": 3, "pc": "0x000004a0", "cpu": ":subcpu", "frame": 9,
                             "cause": "step 1", "since_s": 2.3, "wall_at": "c"}


class _Proc:
    def __init__(self, exited: int | None) -> None:
        self.exited = exited

    def poll(self) -> int | None:
        return self.exited


@pytest.mark.parametrize("ses, proc", [(None, _Proc(None)), (object(), None)],
                         ids=["no session", "no process"])
def test_a_machine_is_alive_only_with_a_session_and_a_process_still_running(
    ses: Any, proc: Any,
) -> None:
    fresh = mstate.State()
    fresh.ses, fresh.proc = ses, proc
    with pytest.raises(mstate.Invalid, match="no machine running"):
        fresh.alive()
    fresh.ses, fresh.proc = object(), _Proc(None)  # type: ignore[assignment]
    assert fresh.alive() is fresh.ses


def test_a_machine_that_died_under_its_session_points_at_close_not_at_start() -> None:
    """`start` deletes the scratch that holds what a dead MAME printed on its way out; `close`
    reads those last words and the exit code first, so it is the step the refusal names."""
    fresh = mstate.State()
    fresh.ses, fresh.proc = object(), _Proc(139)  # type: ignore[assignment]
    with pytest.raises(mstate.Invalid) as refused:
        fresh.alive()
    assert refused.value.code == "session_broken" and refused.value.fields["exit_code"] == 139
    assert "`close` collects" in str(refused.value)


class _Session:
    def __init__(self, quit_error: BaseException | None = None, broken: str | None = None) -> None:
        self.quit_error, self.broken = quit_error, broken
        self.asked: list[str] = []

    def quit(self) -> None:
        self.asked.append("quit")
        if self.quit_error is not None:
            raise self.quit_error

    def close(self) -> None:
        self.asked.append("close")


class _Mame:
    """A process that exits when waited on after a `kill`, or at once when `exits`."""

    pid = 99

    def __init__(self, exits: bool) -> None:
        self.exits, self.gone = exits, False
        self.events: list[str] = []

    def poll(self) -> int | None:
        return 0 if self.gone else None

    def wait(self, timeout: float | None = None) -> int:
        import subprocess

        if self.events[-1:] != ["wait"]:
            self.events.append("wait")
        if self.exits or "kill" in self.events:
            self.gone = True
            return 0
        raise subprocess.TimeoutExpired("mame", timeout or 0)

    def kill(self) -> None:
        self.events.append("kill")


def _killing(ses: _Session, proc: _Mame, scratch: Path | None = None) -> mstate.State:
    fresh = mstate.State()
    fresh.ses, fresh.proc, fresh.scratch = ses, proc, scratch  # type: ignore[assignment]
    return fresh


def test_a_quit_the_socket_refuses_still_ends_the_session() -> None:
    """The connection can be gone under the quit (a reset, a closed pipe): the ending still
    happens, and the session's fields still go."""
    ses = _Session(quit_error=ConnectionResetError("reset"))
    fresh = _killing(ses, _Mame(exits=True))
    ended = fresh.kill()
    assert ended["ended_by"] == "quit" and ended["exit_code"] == 0, ended
    assert ses.asked == ["quit", "close"] and fresh.ses is None and fresh.proc is None


def test_a_broken_session_is_neither_asked_to_quit_nor_waited_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its channel cannot be believed, so no quit goes out and no grace period is spent on an
    exit nobody asked for: straight to the kill, then the reap."""
    monkeypatch.setattr(mstate, "QUIT_GRACE_S", 0.05)
    ses, proc = _Session(broken="the stub sent 'OK' while the machine ran"), _Mame(exits=False)
    ended = _killing(ses, proc).kill()
    assert ses.asked == ["close"] and proc.events == ["kill", "wait"], (ses.asked, proc.events)
    assert ended["ended_by"] == "killed" and ended["exit_code"] == 0, ended


def test_a_scratch_that_cannot_be_wholly_removed_does_not_fail_the_close(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    locked = scratch / "locked"
    locked.mkdir(parents=True)
    (locked / "left.log").write_text("x")
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("this user writes where no write bit is set (root): no case here")
        fresh = _killing(_Session(), _Mame(exits=True), scratch)
        fresh.kill()
        assert fresh.scratch is None and (locked / "left.log").exists(), "the control: it stayed"
    finally:
        locked.chmod(0o700)


def test_a_fresh_session_reads_the_emulator_log_from_its_first_byte(tmp_path: Path) -> None:
    """The first survey after `start` reads `error.log` from the mark a fresh session holds:
    anything but the file's start loses the head of MAME's first line (captured: a byte-order
    mark, then `Soft reset`)."""
    start = (Path(__file__).parent / "fixtures" / "console" / "errorlog-start.txt").read_bytes()
    files.log_path(tmp_path, "emulator").write_bytes(start)
    lines, mark = files.errorlog_since(tmp_path, mstate.State().errorlog_mark)
    assert [line.lstrip("\ufeff") for line in lines] == ["Soft reset"] and mark == len(start)


# The fields a session holds only once it has one: everything else starts as the value an empty
# session reads, so its first reader never meets None where it iterates or compares.
_NONE_UNTIL_START = {"boot_pc", "cfg", "first_cpu", "guard", "manifest",
                     "proc",
                     "reference", "run_release", "scratch", "ses", "session_origin", "cancelled",
                     "scan", "stale_counter", "state_signature", "stdout_log", "store", "window"}


def test_a_fresh_state_holds_none_only_where_a_session_has_yet_to_put_something() -> None:
    fresh = mstate.State()
    none = {k for k, v in vars(fresh).items() if v is None}
    assert none == _NONE_UNTIL_START, (
        "a new field that starts None must be guarded by every reader, and is added above on "
        f"purpose: {sorted(none ^ _NONE_UNTIL_START)}")


class _SlowReap(_Mame):
    """Reaped only after the clock has moved past a progress period since the kill."""

    def __init__(self, clock: _Clock) -> None:
        super().__init__(exits=False)
        self.clock = clock

    def wait(self, timeout: float | None = None) -> int:
        import subprocess

        if "kill" in self.events and self.clock.at >= 102.0:
            self.gone = True
            return 0
        self.clock.at += 0.6
        raise subprocess.TimeoutExpired("mame", timeout or 0)


def test_the_reap_after_a_kill_says_what_it_waits_for(
    clock: _Clock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    said: list[str] = []
    fresh = _killing(_Session(broken="broken"), _SlowReap(clock))
    ended = fresh.kill(lambda e, s, m: said.append(m))
    assert ended["ended_by"] == "killed" and ended["exit_code"] == 0, ended
    assert said and all(m.startswith("close: waiting for the SIGKILLed MAME to be reaped, ")
                        for m in said), said


def test_a_cfg_that_cannot_be_read_back_says_so_rather_than_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "m68k-dual.cfg"
    source.write_text("<mameconfig/>")
    fresh = _killing(_Session(), _Mame(exits=True))
    fresh.cfg = {"installed": str(tmp_path / "gone.cfg"), "source": str(source)}
    report = fresh.kill()["cfg"]
    assert report["changed"]["available"] is False, report
    assert report["changed"]["why"].startswith("could not be read back"), report
