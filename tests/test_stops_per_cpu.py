"""A stop on a board with several cpus: which cpu it happened on, and the runs that end in one."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from server_support import _install, _RegisterSession, _running  # noqa: E402
from session_doubles import bp_records, refused  # noqa: E402

import gdb_session as g  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_running as running  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


class _TwoCpuFrames(_RegisterSession):
    """Two cpus, where `gvblank` stops only through the first: with `:subcpu` visible it runs away.

    `threads` empty is a stub without the thread patch; `Hc` is refused on a cpu in `ignoring`."""

    def __init__(self, threads: dict[int, str], visible: str) -> None:
        super().__init__(bits=32, frame=10, stop_after=1)
        self.threads = threads
        self.visible_cpu = visible
        self.ignoring: list[str] = []

    def make_visible(self, thread: int) -> None:
        self.commands.append(f"Hc{thread:x}")
        if self.threads[thread] in self.ignoring:
            raise g.Refused(f"the stub refused `Hc{thread:x}`: E01")
        self.visible_cpu = self.threads[thread]

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        if command == "gvblank" and self.visible_cpu != ":maincpu":
            self.commands.append(command)
            self.emulating, self.stop_after = True, None
            return ""
        return super().monitor(command, timeout)


def _frames(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, threads: dict[int, str],
            visible: str) -> _TwoCpuFrames:
    ses = _TwoCpuFrames(threads, visible)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    return ses


_THREADS = {1: ":maincpu", 2: ":subcpu"}


def test_a_run_by_frames_with_the_sub_cpu_visible_is_sent_through_the_first_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frames(monkeypatch, tmp_path, _THREADS, ":subcpu")
    out = s.run_for(frames=2, seconds=2.0)
    assert out["status"] == "ok" and out["verdict"] == "ELAPSED", out
    assert (out["frame_before"], out["frame_after"]) == (10, 12), out
    assert ses.commands.index("Hc1") < ses.commands.index("gvblank"), ses.commands
    assert ":maincpu" in out["note"] and "vblank" in out["note"], out


def test_a_run_by_frames_on_the_first_cpu_moves_no_visible_cpu_and_says_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frames(monkeypatch, tmp_path, _THREADS, ":maincpu")
    out = s.run_for(frames=1, seconds=2.0)
    assert out["verdict"] == "ELAPSED" and "note" not in out, out
    assert not any(c.startswith("Hc") for c in ses.commands), ses.commands


def test_a_run_by_frames_is_refused_when_the_first_cpu_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frames(monkeypatch, tmp_path, _THREADS, ":subcpu")
    ses.ignoring = [":maincpu"]
    refused("observe :maincpu", s.run_for(frames=1, seconds=2.0))
    assert "gvblank" not in ses.commands, ses.commands


def test_a_run_by_frames_is_refused_on_a_stub_without_threads_when_another_cpu_is_visible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frames(monkeypatch, tmp_path, {}, ":subcpu")
    refused("milliseconds", s.run_for(frames=1, seconds=2.0))
    assert "gvblank" not in ses.commands, ses.commands


def test_a_run_by_frames_whose_counter_still_moves_after_the_last_landing_is_not_settled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The last landing is proved at rest: a counter that moves after it is `not_settled`."""
    ses = _frames(monkeypatch, tmp_path, _THREADS, ":maincpu")
    real = ses.monitor
    after_last: list[str] = []

    def runs_on(command: str, timeout: float = 10.0) -> str:
        out = real(command, timeout)
        if command == "print frame" and ses.commands.count("gvblank") == 2:
            after_last.append(out)
            if len(after_last) == 2:
                ses.emulating, ses.stop_after = True, None
        return out

    ses.monitor = runs_on  # type: ignore[method-assign]
    out = s.run_for(frames=2, seconds=2.0)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert ses.running, "a machine that may be running is marked RUNNING"


def test_a_stop_breakpoint_halts_only_the_cpu_it_is_armed_on() -> None:
    """The same address on two cpus is two places; an unread cpu falls back to the address."""
    saved = (mstate.STATE.breakpoints, mstate.STATE.controls)
    try:
        mstate.STATE.breakpoints = bp_records((1, "4a0", 0x4A0), (2, "25a4", 0x25A4))
        mstate.STATE.controls = {("25a4", ":maincpu"): {}}
        assert running.halts(0x4A0, ":maincpu")
        assert not running.halts(0x4A0, ":subcpu"), "another cpu's row at the same address"
        assert running.halts(0x4A0, None), "an unread cpu falls back to the address"
        assert not running.halts(0x25A4, ":maincpu"), "a control never halts"
        assert running.attribute(0x4A0, ":subcpu") == "stopped at no breakpoint this server armed"
    finally:
        mstate.STATE.breakpoints, mstate.STATE.controls = saved


def test_a_stop_on_the_sub_cpu_at_a_main_cpu_rows_address_is_not_named_after_that_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    assert s.breakpoint_at(ref="0x4a0")["cpu"] == ":maincpu"
    s.resume()
    ses.visible_cpu = ":subcpu"
    stop = s.stop()
    assert (stop["cpu"], stop["pc"], stop["cause"]) == (":subcpu", "0x000004a0", "interrupt"), stop
    s.resume()
    ses.visible_cpu, ses.pcs = ":maincpu", [0x4A0]
    stop = s.stop()
    assert stop["cause"] == "breakpoint at 0x4a0", stop
    s.resume()
    ses.visible_cpu, ses.stops_after_polls = ":subcpu", 1
    found = s.status()["stopped_on_its_own"]
    assert found["cause"] == "stopped at no breakpoint this server armed", found


def test_a_row_typed_on_the_sub_cpu_at_a_main_cpu_rows_address_names_its_own_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stop is the typed `:subcpu` row's (named by index), not the main cpu's."""
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0x4A0]
    assert s.breakpoint_at(ref="0x4a0")["cpu"] == ":maincpu"
    s.debug(command="bp 4a0:subcpu")
    s.resume()
    ses.visible_cpu = ":subcpu"
    # captured shape (`debuglog.subcpu-bp.resume.txt`): the emulated time, then the line
    (tmp_path / "debug.log").open("a").write("1.218048312\nStopped at breakpoint 2\n4A0\n")
    ses.stops_after_polls = 1
    found = s.status()["stopped_on_its_own"]
    assert found["cpu"] == ":subcpu", found
    assert found["cause"].startswith("breakpoint 2 at 0x000004a0, typed through `debug`"), found


def test_naming_the_machine_where_it_stands_asks_the_cpu_it_stopped_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`name_stop` names a stop by the pc and the cpu MAME made visible there."""
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0x4A0]
    s.breakpoint_at(ref="0x4a0")
    ses.visible_cpu = ":subcpu"
    assert running.name_stop(ses) == "stopped at no breakpoint this server armed"  # type: ignore[arg-type]
    ses.visible_cpu = ":maincpu"
    assert running.name_stop(ses) == "breakpoint at 0x4a0"  # type: ignore[arg-type]


@pytest.mark.parametrize("row_cpu", [":subcpu", ":maincpu"])
def test_a_frame_landing_is_cut_only_by_a_stop_row_of_the_cpu_it_landed_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, row_cpu: str,
) -> None:
    """A row of another cpu at the landing's pc did not stop it (ELAPSED); the landing cpu's did."""
    ses = _frames(monkeypatch, tmp_path, _THREADS, ":maincpu")
    monkeypatch.setattr(mstate.STATE, "breakpoints",
                        {1: {"owner": ("f2034", row_cpu), "addr": 0xF2034, "cpu": row_cpu}})
    out = s.run_for(frames=2, seconds=2.0)
    assert out["verdict"] == ("ELAPSED" if row_cpu == ":subcpu" else "OTHER_STOP"), out
    surveys = sum(c.startswith("dasm") for c in ses.commands)
    assert surveys == 1, "another cpu's row at a landing's pc costs no survey mid-run"


@pytest.mark.parametrize("row_cpu", [":subcpu", ":maincpu"])
def test_a_run_by_time_is_cut_only_by_a_stop_row_of_the_cpu_it_stopped_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, row_cpu: str,
) -> None:
    """A row of another cpu at the stop's pc did not cut a run by time; the stopping cpu's did."""
    ses = _frames(monkeypatch, tmp_path, _THREADS, ":maincpu")
    monkeypatch.setattr(mstate.STATE, "breakpoints",
                        {1: {"owner": ("f2100", row_cpu), "addr": ses.pcs[-1], "cpu": row_cpu}})
    out = s.run_for(milliseconds=20, seconds=2.0)
    assert out["verdict"] == ("ELAPSED" if row_cpu == ":subcpu" else "OTHER_STOP"), out



_LAYOUT = g.Layout.parse(
    '<target><architecture>m68k</architecture><feature name="org.gnu.gdb.m68k.core">'
    '<reg name="d0" bitsize="32" type="int"/><reg name="pc" bitsize="32" type="code_ptr"/>'
    '</feature></target>')


def _two_cpus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, threads: dict[int, str]) -> Any:
    """`_running`'s double on two cpus, where a step moves BOTH pcs by two bytes."""
    ses = _running(monkeypatch, tmp_path)
    ses.threads = threads
    pcs = {1: 0xB90, 2: 0x542}
    monkeypatch.setattr(ses, "layout", lambda thread: _LAYOUT)
    monkeypatch.setattr(ses, "reg", lambda name, *, thread: pcs[thread])
    real = ses.step

    def step() -> str:
        for tid in pcs:
            pcs[tid] += 2
        return str(real())

    monkeypatch.setattr(ses, "step", step)
    return ses


def test_a_step_on_a_named_cpu_shows_it_first_and_says_how_far_the_other_moved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`step(cpu=X)` is `Hc X` then `s`; `others` gives each other cpu's pc before and after."""
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)
    ses.commands.clear()
    out = s.step(count=1, cpu="subcpu")
    assert out["status"] == "ok" and out["cpu"] == ":subcpu", out
    assert list(out)[-1] == "session", "`others` rides inside the envelope, `session` last"
    assert "Hc2" in ses.commands, ses.commands
    assert out["others"] == {":maincpu": {"reg": "PC", "before": "0x00000b90",
                                          "after": "0x00000b92"}}, out
    ses.commands.clear()
    out = s.step(count=1)
    assert not any(c.startswith("Hc") for c in ses.commands), "the visible cpu steps as is"
    assert list(out["others"]) == [":maincpu"], out


def test_a_step_on_another_cpu_is_refused_on_a_build_without_the_thread_patch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_cpus(monkeypatch, tmp_path, {})
    before = ses.stop_count
    refused("thread patch", s.step(count=1, cpu="subcpu"))
    assert ses.stop_count == before, "nothing stepped"
    out = s.step(count=1, cpu="maincpu")
    assert out["status"] == "ok" and "others" not in out, "the visible cpu steps as before"


def test_a_run_to_a_named_cpu_arms_its_target_there_and_is_reached_only_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`run_to(cpu=X)` arms on X; a stop at the address is TARGET only when it is X's."""
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0x542]
    s.breakpoint_at(ref="0x25a4", role="control", cpu="subcpu")
    s.debug(command="bp 542")                         # a :maincpu row at the target's address
    real = ses._stop

    def stops_on_the_sub() -> None:
        real()
        ses.visible_cpu = ":subcpu"

    monkeypatch.setattr(ses, "_stop", stops_on_the_sub)
    ses.stops_after_polls = 1
    out = s.run_to(ref="0x542", control="0x25a4", cpu="subcpu", seconds=2.0)
    assert out["verdict"] == "TARGET" and out["cpu"] == ":subcpu", out
    assert any(c.startswith("bp 0x542::subcpu") for c in ses.commands), ses.commands
    monkeypatch.setattr(ses, "_stop", real)
    ses.visible_cpu, ses.stops_after_polls = ":maincpu", 1
    out = s.run_to(ref="0x542", control="0x25a4", cpu="subcpu", seconds=2.0)
    assert out["code"] == "cut_by_other_stop" and out["cpu"] == ":maincpu", out


def test_a_step_over_on_a_named_cpu_shows_it_first_and_says_what_the_others_did(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console's `over` goes through the visible cpu, so the named cpu is shown first."""
    ses = _frames(monkeypatch, tmp_path, _THREADS, ":maincpu")
    pcs = {1: 0xB90, 2: 0x542}
    monkeypatch.setattr(ses, "layout", lambda thread: _LAYOUT)
    monkeypatch.setattr(ses, "reg", lambda name, *, thread: pcs[thread])
    real = ses.monitor

    def over_runs_both(command: str, timeout: float = 10.0) -> str:
        if command == "over":
            for tid in pcs:
                pcs[tid] += 4
        if command == "print curpc,frame":            # the settle's reading, at rest
            return f"{pcs[2]:x} {ses.frame:x}\n"
        return real(command, timeout)

    ses.monitor = over_runs_both  # type: ignore[method-assign]
    out = s.step(count=1, mode="over", cpu="subcpu")
    assert out["status"] == "ok" and out["cpu"] == ":subcpu", out
    assert ses.commands.index("Hc2") < ses.commands.index("over"), ses.commands
    assert out["others"] == {":maincpu": {"reg": "PC", "before": "0x00000b90",
                                          "after": "0x00000b94"}}, out
    assert list(out)[-1] == "session", out


def test_a_cpu_whose_program_counter_cannot_be_read_is_named_unread_in_others(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)

    def layout(thread: int) -> g.Layout:
        if thread == 1:
            raise g.Refused("the stub refused `qXfer:features:read:target.xml:0,400`: E01")
        return _LAYOUT

    monkeypatch.setattr(ses, "layout", layout)
    out = s.step(count=1, cpu="subcpu")
    assert out["others"] == {":maincpu": {"available": False, "why": "the stub refused "
                                          "`qXfer:features:read:target.xml:0,400`: E01"}}, out


@pytest.mark.parametrize("cpu, why", [(None, ""), (":audiocpu", "the stub names no thread")])
def test_a_stops_registers_on_the_patched_stub_with_no_cpu_or_one_without_a_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cpu: str | None, why: str,
) -> None:
    """An unmarked cpu reads the first thread; a cpu with no thread is said, not read."""
    ses = _running(monkeypatch, tmp_path)
    ses.threads = _THREADS
    regs = running.stop_registers(ses, cpu)  # type: ignore[arg-type]
    if why:
        assert regs == {"available": False, "why": f"{why} for {cpu}"}, regs
    else:
        assert regs["D0"] == "0x00001234" and not any("@" in c for c in ses.commands), regs


def test_a_run_to_whose_stop_cpu_cannot_be_read_falls_back_to_the_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With no cpu marked at the stop, a landing at the target's address is taken as the target."""
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0x542]
    s.breakpoint_at(ref="0x25a4", role="control", cpu="subcpu")
    real = ses._stop

    def stops_unmarked() -> None:
        real()
        ses.visible_cpu = ":nocpu"                    # `cpulist` then marks no known cpu

    monkeypatch.setattr(ses, "_stop", stops_unmarked)
    monkeypatch.setattr("mame_cpus.visible_cpu",
                        lambda s_: None if ses.visible_cpu == ":nocpu" else ses.visible_cpu)
    ses.stops_after_polls = 1
    out = s.run_to(ref="0x542", control="0x25a4", cpu="subcpu", seconds=2.0)
    assert out["verdict"] == "TARGET", out


def test_a_run_by_frames_on_a_board_of_one_cpu_or_with_none_visible_shows_nothing_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With a single cpu, or none marked, there is nothing to route around: no `Hc`, no `note`."""
    ses = _frames(monkeypatch, tmp_path, _THREADS, ":subcpu")
    for tags, visible in (([":maincpu"], ":maincpu"), ([":maincpu", ":subcpu"], None)):
        monkeypatch.setattr(mstate.STATE, "cpus", tags)
        monkeypatch.setattr("mame_cpus.visible_cpu", lambda s_, v=visible: v)
        ses.visible_cpu = ":maincpu"                  # the double's `gvblank` lands
        ses.commands.clear()
        out = s.run_for(frames=1, seconds=2.0)
        assert out["verdict"] == "ELAPSED" and "note" not in out, out
        assert not any(c.startswith("Hc") for c in ses.commands), ses.commands


def test_a_lua_wrapper_whose_run_by_frames_is_refused_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A refused run is refused before the script is sent, or it would sit in the pipe."""
    from lua_support import _channel

    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "visible_cpu", ":subcpu", raising=False)
    refused("milliseconds", s.input(port=":P1", field="Coin 1", value=1, frames=4))
    assert ses.stdin.getvalue() == b"", "no script was sent"


def test_a_step_on_a_named_cpu_cut_by_another_cpus_stop_ends_there_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Steps left would turn into `:maincpu`'s, so they end at that stop, named."""
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)
    stepping = ses.step

    def lands_on_the_main() -> str:
        out = str(stepping())
        ses.visible_cpu = ":maincpu"
        return out

    monkeypatch.setattr(ses, "step", lands_on_the_main)
    out = s.step(count=3, cpu="subcpu")
    assert (out["status"] == "ok" and out["instructions_completed"] == 1
            and out["cpu"] == ":maincpu"), out
    assert "stopped on :maincpu, not :subcpu" in out["note"], out
    assert list(out["others"]) == [":subcpu"], out


@pytest.mark.parametrize("stop_cpu", [":subcpu", ":maincpu"])
def test_a_run_cut_on_another_cpu_reports_no_cycles_across_two_cpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stop_cpu: str,
) -> None:
    """`totalcycles` is per cpu: a run counted on `:maincpu` and cut on `:subcpu` has no span."""
    ses = _frames(monkeypatch, tmp_path, _THREADS, ":maincpu")
    monkeypatch.setattr(mstate.STATE, "breakpoints",
                        {1: {"owner": ("f2100", stop_cpu), "addr": ses.pcs[-1], "cpu": stop_cpu}})
    real = ses.monitor

    def stops_on(command: str, timeout: float = 10.0) -> str:
        out = real(command, timeout)
        if command.startswith("gtime"):
            ses.visible_cpu = stop_cpu
        return out

    ses.monitor = stops_on  # type: ignore[method-assign]
    out = s.run_for(milliseconds=20, seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cpu"] == stop_cpu, out
    assert isinstance(out["cycles"], dict) is (stop_cpu == ":subcpu"), out
    if stop_cpu == ":subcpu":
        assert "each cpu keeps its own `totalcycles`" in out["cycles"]["why"], out


def test_the_program_counter_in_others_is_the_one_named_pc_not_the_first_code_pointer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `code_ptr` link register before the pc (`ra`) is not the pc: `Layout.pc_name` is."""
    ses = _two_cpus(monkeypatch, tmp_path, _THREADS)
    linked = g.Layout.parse(
        '<target><architecture>mips</architecture><feature name="org.gnu.gdb.mips.cpu">'
        '<reg name="ra" bitsize="32" type="code_ptr"/><reg name="pc" bitsize="32" '
        'type="code_ptr"/></feature></target>')
    monkeypatch.setattr(ses, "layout", lambda thread: linked)
    out = s.step(count=1, cpu="subcpu")
    assert out["others"][":maincpu"]["reg"] == "PC", out


def test_a_run_by_frames_refused_with_the_watches_disarmed_disarms_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The route is judged before the pass disarms anything."""
    _frames(monkeypatch, tmp_path, {}, ":subcpu")
    disarmed: list[str] = []

    def disarm(ses: object) -> list[str]:
        disarmed.append("x")
        return []

    monkeypatch.setattr("mame_watches.disarm_for_pass", disarm)
    refused("milliseconds", s.run_for(frames=1, seconds=2.0, disarm_watches=True))
    assert disarmed == [], "nothing was disarmed for a run that was refused"


def test_a_step_over_cut_by_another_cpus_stop_ends_there_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _frames(monkeypatch, tmp_path, _THREADS, ":maincpu")
    monkeypatch.setattr(ses, "layout", lambda thread: _LAYOUT)
    monkeypatch.setattr(ses, "reg", lambda name, *, thread: 0x542)
    real = ses.monitor

    def over_lands_on_the_main(command: str, timeout: float = 10.0) -> str:
        if command == "over":
            ses.visible_cpu = ":maincpu"
        if command == "print curpc,frame":
            return f"542 {ses.frame:x}\n"
        return real(command, timeout)

    ses.monitor = over_lands_on_the_main  # type: ignore[method-assign]
    out = s.step(count=3, mode="over", cpu="subcpu")
    assert (out["instructions_completed"] == 1
            and "stopped on :maincpu, not :subcpu" in out["note"]), out


def test_a_step_on_a_board_of_one_cpu_asks_no_cpu_after_each_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "cpus", [":maincpu"])
    ses.commands.clear()
    out = s.step(count=3)
    assert out["instructions_completed"] == 3, out
    assert ses.commands.count("cpulist") == 2, (
        "one before the steps and one for the survey: none per step", ses.commands)
