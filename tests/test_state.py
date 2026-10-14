"""`mame_state`'s and `mame_progress`'s arithmetic and bookkeeping, held on a clock this file
moves by hand.

The bounded waits all share `Ticker`, so its edges (the bound itself, the moment a report is
due) are asked here once, exactly at the edge, rather than inferred from the loops that each
cross it somewhere in the middle.
"""

import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_files as files  # noqa: E402
import mame_progress as mprogress  # noqa: E402
import mame_state as mstate  # noqa: E402


class _Clock:
    """`time.monotonic` as a number the case sets."""

    def __init__(self, at: float = 100.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr("mame_state.time.monotonic", c)
    return c


def test_a_bound_expires_at_its_deadline_and_leaves_nothing_after_it(clock: _Clock) -> None:
    t = mprogress.Ticker(5.0, mprogress.no_progress)
    clock.at += 4.0
    assert t.expired() is False and t.left() == 1.0
    clock.at += 1.0
    assert t.expired() is True and t.left() == 0.0, "the deadline itself is expired, 0 left"
    clock.at += 3.0
    assert t.expired() is True and t.left() == 0.0, "past it, never a negative wait"


def test_elapsed_is_rounded_to_a_millisecond_unless_asked(clock: _Clock) -> None:
    t = mprogress.Ticker(5.0, mprogress.no_progress)
    clock.at += 1.23456
    assert t.elapsed() == 1.235 and t.elapsed(1) == 1.2


def test_a_report_is_due_once_per_period_and_never_at_once(clock: _Clock) -> None:
    said: list[tuple[float, float | None, str]] = []
    t = mprogress.Ticker(10.0, lambda e, s, m: said.append((e, s, m)))
    t.expired()
    t.tick("{elapsed:.1f}s")
    assert said == [], "no report before a period has passed"
    clock.at += mprogress.PROGRESS_EVERY_S
    t.expired()
    t.tick("{elapsed:.1f}s")
    assert [m for _, _, m in said] == ["1.0s"], "due exactly one period in"
    clock.at += mprogress.PROGRESS_EVERY_S / 2
    t.expired()
    t.tick("{elapsed:.1f}s")
    assert len(said) == 1, "and not again inside the next period"
    clock.at += mprogress.PROGRESS_EVERY_S / 2
    t.expired()
    t.tick("{elapsed:.1f}s")
    assert [m for _, _, m in said] == ["1.0s", "2.0s"] and said[-1][0] == 2.0
    assert all(total is None for _, total, _ in said), said


def test_a_work_report_carries_its_pair_on_the_same_period(clock: _Clock) -> None:
    said: list[tuple[float, float | None, str]] = []
    t = mprogress.Ticker(10.0, lambda p, total, m: said.append((p, total, m)))
    t.expired()
    t.report(0, 4, "frame {frame}", frame=10)
    assert said == [], "no report before a period has passed"
    clock.at += mprogress.PROGRESS_EVERY_S
    t.expired()
    t.report(3, 4, "frame {frame}, {elapsed:.0f}s", frame=13)
    t.report(4, 4, "frame {frame}, {elapsed:.0f}s", frame=14)
    assert said == [(3, 4, "frame 13, 1s")], "once per period, whatever the work did meanwhile"
    clock.at += mprogress.PROGRESS_EVERY_S
    t.expired()
    t.report(-2, 4, "behind the start")
    clock.at += mprogress.PROGRESS_EVERY_S
    t.expired()
    t.report(9, 4, "past the end")
    assert [p for p, _, _ in said[1:]] == [0, 4], "clamped into [0, total]"


def test_a_finish_is_sent_at_once_at_its_total() -> None:
    said: list[tuple[float, float | None, str]] = []
    t = mprogress.Ticker(10.0, lambda p, total, m: said.append((p, total, m)))
    t.finish(4, "frame {frame}, done", frame=14)
    assert said == [(4, 4, "frame 14, done")], "never held back by the period"


def _rebased() -> tuple[mprogress.RebasedProgress, list[tuple[float, float | None, str]]]:
    sent: list[tuple[float, float | None, str]] = []
    return mprogress.RebasedProgress(lambda p, t, m: sent.append((p, t, m))), sent


def test_a_rebased_progress_passes_an_increasing_sequence_through_unchanged() -> None:
    report, sent = _rebased()
    report(1.0, None, "a")
    report(2.5, None, "b")
    report(3.0, 8.0, "c")
    assert sent == [(1.0, None, "a"), (2.5, None, "b"), (3.0, 8.0, "c")]


def test_a_restart_inside_one_call_continues_from_the_last_value_sent() -> None:
    """A retry after a wait, or a second Ticker in one call, begins again at its own zero: the
    client is told a value above everything it was told before, never a smaller one."""
    report, sent = _rebased()
    for elapsed in (1.0, 2.0, 3.0):
        report(elapsed, None, f"waiting {elapsed:g}s")
    report(1, 3, "retry 1 of 3")              # start's retry: a count, below the last raw
    report(1.0, None, "again 1s")             # the new Ticker's first: not above what was sent
    report(2.0, None, "again 2s")
    assert sent == [(1.0, None, "waiting 1s"), (2.0, None, "waiting 2s"),
                    (3.0, None, "waiting 3s"), (4.0, 6.0, "retry 1 of 3"),
                    (5.0, None, "again 2s")], sent
    values = [p for p, _, _ in sent]
    assert all(b > a for a, b in zip(values, values[1:], strict=False))


def test_a_second_restart_is_based_on_the_value_sent_not_on_the_raw_one() -> None:
    """After one rebase the value sent and the raw one differ, and only the value sent keeps the
    line rising: based on the raw one, the third segment would fall below what was sent."""
    report, sent = _rebased()
    for raw in (1.0, 2.0, 3.0):
        report(raw, None, "first")
    report(1.0, 3.0, "second")                # sent 4.0 of 6.0
    report(0.5, None, "third")
    assert sent[-2:] == [(4.0, 6.0, "second"), (4.5, None, "third")], sent


def test_a_value_not_above_the_last_one_sent_is_not_sent_nor_its_message() -> None:
    report, sent = _rebased()
    report(2.0, 4.0, "two")
    report(2.0, 4.0, "two again")
    assert sent == [(2.0, 4.0, "two")]


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
    assert fresh.as_of() is None
    fresh.last_stop = {"seq": 3, "pc": "0x000004a0", "cpu": ":subcpu", "frame": 9,
                       "how": "step 1", "when": clock.at, "wall_at": "c"}
    clock.at += 2.345
    assert fresh.as_of() == {"stop_seq": 3, "pc": "0x000004a0", "cpu": ":subcpu", "frame": 9,
                             "how": "step 1", "since_s": 2.3, "wall_at": "c"}


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
    start = (Path(__file__).parent / "fixtures" / "console" / "errorlog.start.txt").read_bytes()
    files.log_path(tmp_path, "emulator").write_bytes(start)
    lines, mark = files.errorlog_since(tmp_path, mstate.State().errorlog_mark)
    assert [line.lstrip("\ufeff") for line in lines] == ["Soft reset"] and mark == len(start)


# The fields a session holds only once it has one: everything else starts as the value an empty
# session reads, so its first reader never meets None where it iterates or compares.
_NONE_UNTIL_START = {"boot_pc", "cfg", "first_cpu", "guard", "manifest",
                     "proc",
                     "reference", "run_release", "scratch", "ses", "session_origin",
                     "scan", "stale_counter", "state_signature", "stdout_log", "store"}


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
    source = tmp_path / "radendur.cfg"
    source.write_text("<mameconfig/>")
    fresh = _killing(_Session(), _Mame(exits=True))
    fresh.cfg = {"installed": str(tmp_path / "gone.cfg"), "source": str(source)}
    report = fresh.kill()["cfg"]
    assert report["changed"]["available"] is False, report
    assert report["changed"]["why"].startswith("could not be read back"), report
