"""The server's guarantees: advancing the machine: run_to, run_for, resume, stop and their waits."""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scry_core import log_marks, placement
from scry_core import log_wait as core_wait
from scry_core import presence as presence_mod
from scry_core import progress as mprogress  # noqa: E402
from server_support import (  # noqa: E402
    _PNG,
    MACHINE_DEPENDENT,
    _boot_against,
    _boot_args,
    _by_frames,
    _console,
    _ConsoleSession,
    _DroppingWire,
    _GoneProcess,
    _install,
    _masked,
    _never_spawns,
    _RegisterSession,
    _running,
    _RunningSession,
    _ScriptedClock,
    _stub_boot,
    _StubProcess,
    _wait_emulator,
    _window,
)
from session_doubles import (  # noqa: E402
    bp_records,
    captured,
    refused,
    use_table,  # noqa: E402
)

import gdb_session as g  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_block as block  # noqa: E402
import mame_conditions as conditions  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_files as files  # noqa: E402
import mame_launch as launch
import mame_lists as mlists  # noqa: E402
import mame_read as read  # noqa: E402
import mame_running as running  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_stub_owner as owner  # noqa: E402
import mame_watches as watches  # noqa: E402
import server as s  # noqa: E402


def test_a_timeout_leaves_the_machine_stopped() -> None:
    """`run_to` must not hand back a session whose machine is still RUNNING."""
    import inspect

    assert hasattr(g.Session, "interrupt"), "the client has no way to stop a running machine"
    src = inspect.getsource(advance._run_to)
    assert "interrupt()" in src, "run_to does not stop the machine it left running"
    assert src.index("interrupt()") < src.index("mclear.clear_command("), (
        "the breakpoints are removed before the machine is stopped, which is the same gamble"
    )


def test_a_go_command_too_long_to_send_leaves_the_machine_stopped_and_no_run_window(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A go-family command reads the emulated clock to open its run window before it is sent."""
    ses = g.Session(timeout=0.2)
    wire = _DroppingWire(answers=(b"1.0".hex(),))
    ses._sock = wire  # type: ignore[assignment]
    ses.packet_size = 0x40
    _install(monkeypatch, ses, tmp_path)
    out = s.debug("gtime " + "1" * 40)
    assert out["code"] == "bad_argument", out
    assert ses.running is False and mstate.STATE.console_run is False
    assert mstate.STATE.run_release is None
    assert wire.sent == [], wire.sent


def test_the_instructions_warn_that_the_target_of_run_to_carries_no_stop_of_its_own() -> None:
    """Declaring a stop at X and then `run_to(ref=X)` is the natural order and is refused,
    rightly: one row per address. The refusal says so well; the instructions have to say it
    first, or a caller meets the rule only by tripping over it."""
    text = s.mcp.instructions or ""
    assert "run_to" in text and "no stop of its own" in text, "the sentence is missing"


def test_memdump_names_the_file_it_left_when_the_control_read_breaks_the_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The file is on disk when the control read is made."""
    image = bytes(range(64))

    def save(command: str) -> str:
        path, _addr, length = command[len("save "):].split(",")
        Path(path).write_bytes(image[:int(length, 16)])
        return "Data saved successfully"

    ses = _ConsoleSession(image, replies={"save": save})
    _console(monkeypatch, tmp_path, ses)

    def broken(addr: int, n: int, *, thread: int) -> bytes:
        raise g.SessionError("the stub closed the connection")

    monkeypatch.setattr(ses, "read", broken)
    dest = tmp_path / "left.bin"
    out = s.memdump("0x0", length=32, dest=str(dest))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert out["path"] == str(dest) and out["bytes"] == 32 and out["length"] == 32, out
    assert out["addr"] == "0x00000000", out
    assert "closed the connection" in out["message"] and "left there" in out["message"]
    assert dest.read_bytes() == image[:32], "the file is left for inspection"
    assert getattr(ses, "broken") and s.registers()["code"] == "session_broken", (  # noqa: B009
        "and the channel LATCHED")
    setattr(ses, "broken", None)          # noqa: B010  # a fresh session, for the short case
    out = s.memdump("0x0", length=8, dest=str(tmp_path / "short.bin"))
    assert out["code"] == "session_broken" and out["bytes"] == 8, "a control shorter than 16"


def test_snapshot_waits_for_a_file_that_arrives_late(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The wait loop's one reason to exist: the console answers before the file is whole."""
    import threading

    ses = _ConsoleSession()
    scratch = _console(monkeypatch, tmp_path, ses)

    def later(command: str) -> str:
        target = scratch / "snap" / command[len("snap "):]
        target.write_bytes(_PNG[:10])                       # a partial file first
        threading.Timer(0.15, lambda: target.write_bytes(_PNG)).start()
        return "Saved"

    ses.replies["snap"] = later
    out = s.snapshot()
    assert "verdict" not in out and out["bytes"] == len(_PNG)


def test_find_is_bounded_by_the_program_space_when_the_mask_is_known(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `length` past what the program space holds is refused naming the space and its mask."""
    ses = _ConsoleSession(replies={"find": "Not found\n",
                                   "cpulist": captured("cpulist.main-visible.txt")})
    _console(monkeypatch, tmp_path, ses)
    monkeypatch.setattr(mstate.STATE, "machine_map", _masked(0x3FFF))
    out = refused("past the program space",
                  s.find(ref="0x0", length=0x4001, data_hex="00"))
    assert out["code"] == "bad_argument" and "mask is 0x3fff" in out["message"], out
    assert ses.commands == ["cpulist"], "refused before the search: only the cpu was read"
    whole = s.find(ref="0x0", length=0x4000, data_hex="00")
    assert whole["hits_total"] == 0, "the whole space is a range"
    monkeypatch.setattr(mstate.STATE, "machine_map", {})
    unmasked = s.find(ref="0x0", length=0x00100000, data_hex="00")
    assert unmasked["hits_total"] == 0, "no mask: the console's"


def test_run_to_prints_registers_at_their_declared_width(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE REGRESSION THIS EXISTS FOR."""
    ses = _RegisterSession(bits=16)
    _install(monkeypatch, ses, tmp_path)
    use_table(monkeypatch, table={})
    narrow = s.registers()["regs"]
    assert narrow == {"EAX": "0x1234", "EIP": "0x8b56"}
    out = s.run_to(ref="0xf2034", control="0x4a0", seconds=1.0)
    assert out["verdict"] == "TARGET"
    assert out["regs"] == narrow, "the two tools disagree on the width of one register"
    wide = _RegisterSession(bits=32)
    _install(monkeypatch, wide, tmp_path)
    assert s.registers()["regs"] == {"EAX": "0x00001234", "EIP": "0x00008b56"}
    # A width that is not a multiple of four rounds UP to a whole hex digit: 13 bits is FOUR
    # digits, not three (12 bits would not tell the two roundings apart).
    odd = _RegisterSession(bits=13, values={"EAX": 0x12, "EIP": 0x345})
    _install(monkeypatch, odd, tmp_path)
    assert s.registers()["regs"] == {"EAX": "0x0012", "EIP": "0x0345"}


def test_run_for_waits_until_the_frame_counter_stops_moving(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console answers `print frame` while the machine still runs."""
    ses = _RegisterSession(bits=32, frame=10, stop_after=4)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    ses.last_stop_packet = "T05watch:2031fc;thread:1;"
    out = s.run_for(milliseconds=250)
    assert out["verdict"] == "ELAPSED"
    assert out["cause"] == "the console's `gtime` stop" and "watch_hit" not in out, out
    assert ses.last_stop_packet == "", "the stale packet survived the console-started run"
    assert out["frame_before"] == 10 and out["frame_after"] == 14
    # Before, gtime, then the poll: four moving readings and then the three that agree.
    # `cpulist` first: which cpu the run's `totalcycles` is counted on.
    assert ses.commands[:3] == ["cpulist", "print frame,totalcycles", "gtime 0xfa"]
    assert ses.commands[3:9] == ["print frame"] * 6
    # Then the stop survey: the visible cpu, the frame and the listing at the pc (the double's
    # `current_pc` answers without the console).
    assert ses.commands[9:] == ["cpulist", "print frame", "dasm dasm.txt,0xf2100,0x20",
                                "print totalcycles"]
    assert out["reads"] == 6 and "polls" not in out
    assert not ses.interrupted, "a machine that stopped by itself is not interrupted"
    assert ses.received == [g.STOP_REPLY_DRAIN_S], (
        "the drain is bounded by its named constant")
    assert out["pc"] == f"{0xF2100:#010x}", "the pc is read AFTER the run, not before"
    assert out["session"]["altered"] is False, "advancing the machine is not forcing its state"
    refused("milliseconds",
    s.run_for(milliseconds=0))


def test_run_for_is_invalid_when_the_counter_did_not_move_or_went_backwards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _RegisterSession(bits=32, frame=10)
    ses.frame_answers = ["a"] * 5
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    out = s.run_for(milliseconds=1)
    assert out["status"] == "INVALID" and "shorter than one frame" in out["message"]
    assert out["code"] == "no_progress"
    assert "pc" in out and "regs" in out and "dasm" in out, out
    back = _RegisterSession(bits=32, frame=10, stop_after=0)
    back.frame_answers = ["64", "3", "3", "3", "3"]
    _install(monkeypatch, back, tmp_path)
    out = s.run_for(milliseconds=100)
    assert out["status"] == "INVALID" and "this call saw only the counter" in out["message"]
    assert out["code"] == "frames_went_backwards"
    assert "pc" in out and "regs" in out, out


def test_run_for_interrupts_a_machine_still_moving_at_the_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The grace is a bound, not a promise."""
    import time as _time

    ses = _RegisterSession(bits=32, frame=10, stop_after=None)   # never stops by itself
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.01)
    t0 = _time.time()
    out = s.run_for(milliseconds=60000, seconds=0.2)
    assert _time.time() - t0 < 2.0, "the bound is the caller's timeout, not the console's"
    assert ses.interrupted, "the machine was left running"
    assert out["verdict"] == "TIMEOUT" and out["frame_after"] > out["frame_before"]
    # After the halt: the frame read that proves the stop, then the stop survey (the visible
    # cpu, its own frame read and the listing at the pc).
    assert ses.commands[-5:] == ["print frame", "cpulist", "print frame",
                                 "dasm dasm.txt,0xf2100,0x20", "print totalcycles"]


def test_run_for_treats_a_non_numeric_frame_as_a_refusal_and_stops_the_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stop packet or an error line where a number was expected must not escape as a bare
    ValueError, skipping the interrupt: it is the console refusing, and the machine is
    stopped before the tool answers."""
    ses = _RegisterSession(bits=32, frame=10, stop_after=None)
    ses.frame_answers = ["a", "T05thread:01;"]
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)

    def after_halt() -> None:
        ses.frame_answers = None
        ses.frame = 20             # and it had run meanwhile
        ses.interrupted = True
        ses.emulating = False

    ses.halt = after_halt  # type: ignore[method-assign]
    out = s.run_for(milliseconds=100)
    assert ses.interrupted and out["verdict"] == "TIMEOUT"


@pytest.mark.parametrize("name", sorted(MACHINE_DEPENDENT))
def test_an_argument_only_the_machine_can_judge_still_waits_for_it(name: str) -> None:
    """THE CONTROL FOR THE RULE ABOVE, and without it that rule is half a sentence."""
    mstate.STATE.kill()
    got = MACHINE_DEPENDENT[name]()
    got = refused("no machine running", got)
    assert got["code"] == "no_session", (
        f"{name} judged a machine-dependent argument with no machine to judge it against")


def test_resume_without_a_bound_lets_the_machine_run_and_the_readers_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE RUNNING-GUEST CONTRACT."""
    ses = _running(monkeypatch, tmp_path)
    out = s.resume()
    assert "verdict" not in out and out["session"]["running"] is True and ses.running
    assert out["session"]["running"] is True
    assert out["summary"] == "resume: running, no wait asked"
    calls: dict[str, Callable[[], dict[str, Any]]] = {
        "registers": lambda: s.registers(),
        "read_memory": lambda: s.read_memory(ref="0x0"),
        "disassemble": lambda: s.disassemble(ref="0x0"),
        "find": lambda: s.find(ref="0x0", length=4, data_hex="00"),
        "history": lambda: s.history(),
        "memdump": lambda: s.memdump(ref="0x0", length=4, dest=str(tmp_path / "x.bin")),
        "debug": lambda: s.debug(command="print pc"),
        "step": lambda: s.step(),
        "run_to": lambda: s.run_to(ref="0x4a0", control="0x25a4"),
        "run_for": lambda: s.run_for(milliseconds=10),
        "write": lambda: s.write(ref="0x0", data_hex="00"),
        "set_register": lambda: s.set_register(name="D0", value=1),
        "reset": lambda: s.reset(),
        "resume": lambda: s.resume(),
    }
    for name, call in calls.items():
        refused = call()
        assert refused["status"] == "INVALID", name
        assert "no stop has been read since" in refused["message"], refused
        assert refused["summary"].startswith(f"{name}: INVALID")
        assert refused["last_stop"]["stop_seq"] == 1 and refused["last_stop"]["cause"] == "start"
        assert refused["last_stop"]["pc"] == "0x000f2034"
        assert "status" in refused["answers_while_running"]
        # THE REMEDY ANSWERS: every tool the refusal sends the caller to is one that answers
        # while the machine runs, never a reader that refuses for the same reason.
        named = [n for n in re.findall(r"`([a-z_]+)`", refused["message"])
                 if callable(getattr(s, n, None))]
        assert named and all(n in refused["answers_while_running"] or n == name
                             for n in named), (name, named)
        assert list(refused)[-1] == "session", "the envelope holds on a refusal too"
    assert "a second `resume` has no state" in s.resume()["message"].lower()
    assert ses.running, "no refusal stopped the machine"
    assert ses.commands == ["cpulist", "print frame", "dasm dasm.txt,0xf2034,0x20"], (
        "nothing was read off the running machine: only the park's survey touched the console")
    # What answers meanwhile: the last stop's registers, marked superseded and dated.
    older = s.registers(from_last_stop=True)
    assert older["superseded"] is True and older["regs"] == {"D0": "0x00001234", "PC": "0x000f2034"}
    assert older["last_stop"]["stop_seq"] == 1 and "from the last stop" in older["summary"]
    listed = s.declaration_list("breakpoint")
    assert listed["session"]["running"] is True and listed["last_stop"]["stop_seq"] == 1
    st = s.status()
    assert (st["session"]["running"] is True and isinstance(st["pc"], dict)
            and st["last_stop"]["pc"] == "0x000f2034")
    assert st["last_stop"]["stop_seq"] == 1
    assert "RUNNING" in st["summary"]


def test_a_stop_the_machine_reached_on_its_own_is_recorded_by_the_first_contact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A breakpoint fires while nobody waits."""
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    s.resume()
    ses.stops_after_polls = 1                    # the breakpoint fires
    st = s.status()
    assert st["session"]["running"] is False and st["stopped_on_its_own"]["stop_seq"] == 2
    assert st["stopped_on_its_own"]["cause"] == "breakpoint at 0x4a0"
    assert st["last_stop"]["stop_seq"] == 2 and st["pc"] == "0x000004a0"
    assert "stopped_on_its_own" not in s.status(), "reported once, by the contact that found it"
    regs = s.registers()
    assert regs["status"] == "ok", "the readers answer again"


def test_a_call_that_steps_and_then_refuses_owns_its_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A refusal that comes after the call's own step owns that stop."""
    _running(monkeypatch, tmp_path)

    def steps_then_refuses(ses_: Any, *_: Any) -> dict[str, Any]:
        ses_.step()
        raise mstate.Invalid("unknown_ref", "the map entry names no share and no region")

    monkeypatch.setattr(block, "read_block", steps_then_refuses)
    refused_ = s.read_block(ref="0x4a0")
    assert refused_["code"] == "unknown_ref", refused_
    after = s.status()
    assert "stopped_on_its_own" not in after, after["stopped_on_its_own"]
    assert after["last_stop"]["stop_seq"] == 2, after["last_stop"]
    assert after["last_stop"]["cause"].startswith("read_block"), after["last_stop"]
    assert after["pc"] == after["last_stop"]["pc"], "the record describes where the machine is"


@pytest.mark.parametrize("state", ["running", "process gone", "no process", "no scratch"])
def test_a_stop_is_not_recorded_for_a_machine_that_cannot_be_surveyed(
    state: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The states a refusal can find the session in."""
    ses = _running(monkeypatch, tmp_path)
    ses.step()
    if state == "running":
        ses.running = True
    elif state == "no scratch":
        monkeypatch.setattr(mstate.STATE, "scratch", None)
    else:
        monkeypatch.setattr(mstate.STATE, "proc",
                            _GoneProcess() if state == "process gone" else None)

    def must_not_survey(*_: Any) -> dict[str, Any]:
        raise AssertionError(f"surveyed with {state}")

    monkeypatch.setattr(running, "survey", must_not_survey)
    running.record_own_stop("lua")
    assert mstate.STATE.last_stop["seq"] == 1


def test_a_stop_that_cannot_be_surveyed_leaves_the_refusal_as_it_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The record of the refusing call's own stop is a courtesy to the NEXT call, never a new
    way for this one to fail: a session that broke under it keeps its refusal, and the stop
    stays for the next contact to find."""
    _running(monkeypatch, tmp_path)

    def steps_then_refuses(ses_: Any, *_: Any) -> dict[str, Any]:
        ses_.step()
        raise mstate.Invalid("unknown_ref", "the map entry names no share and no region")

    def broken(*_: Any) -> dict[str, Any]:
        raise g.SessionError("the stub closed the connection")

    monkeypatch.setattr(block, "read_block", steps_then_refuses)
    monkeypatch.setattr(running, "survey", broken)
    refused_ = s.read_block(ref="0x4a0")
    assert refused_["status"] == "INVALID" and refused_["code"] == "unknown_ref", refused_
    assert mstate.STATE.last_stop["seq"] == 1, "nothing was recorded from a survey that broke"


def test_resume_with_a_bound_waits_for_the_stop_and_returns_the_survey(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(running, "RESUME_POLL_S", 0.0)
    ses.stops_after_polls = 3
    out = s.resume(seconds=2.0)
    assert "running" not in out, out
    assert out["verdict"] == "OTHER_STOP" and out["session"]["running"] is False
    assert out["waited_s"] < 1.0
    assert out["cause"] == "stopped at no breakpoint this server armed"
    assert out["pc"] == "0x000004a0" and out["frame"] == 160
    assert out["regs"] == {"D0": "0x00001234", "PC": "0x000f2034"}
    assert out["dasm"] == ["4a0: move.l d0,d1", "4a0+2: rts"]
    assert out["errorlog"] == {"lines_total": 0, "truncated": False, "lines": [], "mark": 0}
    assert out["summary"] == ("resume: OTHER_STOP at pc 0x000004a0 (stopped at no breakpoint "
                              "this server armed)")
    # And a bound that expires LEAVES IT RUNNING, unlike run_to.
    out = s.resume(seconds=0.05)
    assert "running" not in out, out
    assert out["verdict"] == "TIMEOUT" and out["session"]["running"] is True and ses.running
    assert "was LEFT RUNNING" in out["note"] and ses.interrupted == 0


def test_stop_interrupts_a_running_machine_and_surveys_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.resume()
    out = s.stop()
    assert out["interrupted"] is True and out["cause"] == "interrupt" and ses.interrupted == 1
    assert out["pc"] == "0x000004a0"
    assert out["summary"] == "stop: interrupted at pc 0x000004a0, frame 160"
    again = s.stop()
    assert again["interrupted"] is False and again["last_stop"]["stop_seq"] == 2
    assert ses.interrupted == 1, "nothing is sent to a stopped machine"


def test_the_stop_survey_shows_the_log_since_the_previous_stop_capped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The delta is what the driver logged BETWEEN two stops, not the whole log."""
    log = tmp_path / "error.log"
    log.write_text("boot\n")
    ses = _running(monkeypatch, tmp_path)              # stop 1 reads `boot`
    assert mstate.STATE.errorlog_mark == 5
    with open(log, "a") as fh:
        fh.write("".join(f"line {i}\n" for i in range(10)))
    ses.stops_after_polls = 1
    out = s.resume(seconds=1.0)
    assert out["errorlog"]["lines_total"] == 10 and len(out["errorlog"]["lines"]) == 8
    assert out["errorlog"]["truncated"] is True and out["errorlog"]["lines"][-1] == "line 9"
    assert out["errorlog"]["lines"][0] == "line 2"
    ses.stops_after_polls = 1
    assert s.resume(seconds=1.0)["errorlog"]["lines_total"] == 0


def test_breakpoints_arm_and_clear_while_running_and_say_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `Z0` sent to a running machine is taken and FIRES."""
    ses = _running(monkeypatch, tmp_path)
    s.resume()
    armed = s.breakpoint_at(ref="0x25a4")
    assert armed["while_running"] is True and ses.armed == [(0x25A4, False)]
    assert armed["summary"] == "breakpoint_at 0x25a4: armed at 0x000025a4 while running"
    cleared = s.declaration_clear("breakpoint", ref="0x25a4")
    assert cleared["while_running"] is True and "bpclear 0x1" in ses.commands
    assert ses.running


def test_log_wait_answers_the_log_first_then_waits_and_refuses_honestly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import threading

    log = tmp_path / "error.log"
    log.write_text("boot done\n")
    ses = _running(monkeypatch, tmp_path)
    # Already there: no wait, and the machine may be stopped for that.
    out = s.log_wait(channel="emulator", pattern="boot", seconds=1.0)
    assert out["already"] is True and out["line"] == "boot done" and out["waited_s"] == 0.0
    assert out["summary"] == "log_wait emulator /boot/: matched already there"
    # Not there and the machine STOPPED: refused at once, naming the stop.
    out = s.log_wait(channel="emulator", pattern="scene", seconds=1.0)
    assert out["status"] == "INVALID" and "STOPPED" in out["message"]
    assert out["last_stop"]["stop_seq"] == 1
    # Running: a line that arrives during the wait is found, with its counts.
    s.resume()

    def later() -> None:
        time.sleep(0.15)
        with open(log, "a") as fh:
            fh.write("noise\nscene 3 drawn\n")

    threading.Thread(target=later).start()
    out = s.log_wait(channel="emulator", pattern="scene", seconds=3.0)
    assert out["already"] is False and out["line"] == "scene 3 drawn" and out["waited_s"] > 0.1
    assert out["arrived_during"] == 2 and out["lines_before"] == 2 and out["lines_examined"] == 3
    # A bound that expires is a TIMEOUT and says what it examined.
    out = s.log_wait(channel="emulator", pattern="never", seconds=0.15)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert "bound that expired" in out["note"]
    assert out["arrived_during"] == 0 and "NOTHING" in out["note"]
    # A stop DURING the wait ends it, naming the stop, after one last read.
    ses.stops_after_polls = 2
    out = s.log_wait(channel="emulator", pattern="never", seconds=1.0)
    assert out["status"] == "INVALID" and "STOPPED during" in out["message"]
    assert out["last_stop"]["stop_seq"] == 2 and not ses.running
    assert out["stopped_on_its_own"]["stop_seq"] == 2, "the stop the wait found is recorded"
    # Bad arguments are refused; the machine is asked for FIRST (the no-machine test).
    refused("seconds",
    s.log_wait(channel="emulator", pattern=".", seconds=0))
    refused("does not compile",
    s.log_wait(channel="emulator", pattern="[", seconds=1))


def test_log_wait_reports_progress_while_it_waits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.go()
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    ticks: list[tuple[float, float | None, str]] = []
    out = _wait_emulator(ses, tmp_path, lambda: True, lambda: None,
                              "never", 0.1, lambda p, t, m: ticks.append((p, t, m)))
    assert out["verdict"] == "TIMEOUT"
    assert ticks and all(t is None and "log_wait emulator /never/" in m for _p, t, m in ticks)


def test_run_to_and_run_for_report_progress_while_they_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    ticks: list[str] = []
    ses.stops_after_polls = 3
    out = advance.run_to(ses, tmp_path, "0x4a0", "0x25a4", 1.0,  # type: ignore[arg-type]
                         lambda p, t, m: ticks.append(m))
    assert out["verdict"] == "TARGET" and ticks and "run_to 0x4a0" in ticks[0]
    reg = _RegisterSession(bits=32, frame=10, stop_after=4)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    ticks.clear()
    out = advance.run_for(reg, tmp_path, 100, 5.0,  # type: ignore[arg-type]
                          lambda p, t, m: ticks.append(m))
    assert out["verdict"] == "ELAPSED" and ticks and "run_for 100 ms" in ticks[0]


def test_log_wait_reads_the_log_one_last_time_before_every_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The loop checks the condition FIRST and reads LAST."""
    log = tmp_path / "error.log"
    log.write_text("boot\n")
    ses = _running(monkeypatch, tmp_path)
    ses.go()
    monkeypatch.setattr(core_wait, "POLL_S", 0.0)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)

    def writes(line: str) -> Callable[[], None]:
        def write() -> None:
            with open(log, "a") as fh:
                fh.write(line + "\n")
        return write

    # A stop DURING the wait: the reaction logged just before the breakpoint is found.
    ses.stops_after_polls = 2
    out = _wait_emulator(ses, tmp_path, lambda: True,
                              writes("reaction before the stop"), "reaction", 1.0)
    assert out["status"] == "ok" and out["line"] == "reaction before the stop"
    assert out["already"] is False and not ses.running
    # The emulator GONE: the exit trace is found; with nothing to find, the refusal says GONE.
    ses.go()
    gone = writes("driver exit")
    out = _wait_emulator(ses, tmp_path, lambda: (gone(), False)[1],
                              lambda: None, "exit", 1.0)
    assert out["status"] == "ok" and out["line"] == "driver exit"
    out = _wait_emulator(ses, tmp_path, lambda: False, lambda: None,
                              "never", 1.0)
    assert out["status"] == "INVALID" and "GONE" in out["message"]
    # The two cases at the CLOCK are scripted (a hundredth per reading), so the loop runs
    # exactly one iteration and what happens after it is deterministic.
    class _Clock:
        now = 0.0

        def monotonic(self) -> float:
            self.now += 0.01
            return self.now

        def sleep(self, seconds: float) -> None:
            pass

    clock = _Clock()
    monkeypatch.setattr(core_wait, "time", clock)
    monkeypatch.setattr(mstate, "time", clock)
    monkeypatch.setattr(mprogress, "time", clock)
    # A line landing between the final read and the deadline is found by the last look (the
    # progress callback fires after the read, so it plays the driver writing right then).
    out = _wait_emulator(ses, tmp_path, lambda: True, lambda: None,
                              "late", 0.015, lambda p, t, m: writes("late line")())
    assert out["status"] == "ok" and out["line"] == "late line" and out["already"] is False, out
    assert out["waited_s"] == 0.0, ("a wait is spelled to the tenth of a second, and this one "
                                    "took a hundredth", out)
    ses.stops_after_polls = 2
    out = _wait_emulator(ses, tmp_path, lambda: True, lambda: None,
                              "never", 0.015)
    assert out["status"] == "INVALID" and "STOPPED as the bound expired" in out["message"]


def test_a_frame_that_is_not_a_number_is_the_consoles_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _RunningSession(tmp_path)
    ses.monitor = lambda command, timeout=10.0: "T05thread:01;\n"  # type: ignore[method-assign]
    with pytest.raises(g.SessionError, match="print frame"):
        read.frame(ses)  # type: ignore[arg-type]
    ses.monitor = lambda command, timeout=10.0: ""  # type: ignore[method-assign]
    with pytest.raises(g.SessionError, match="nothing"):
        read.frame(ses)  # type: ignore[arg-type]


def test_resume_refuses_a_negative_bound_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    refused(r"^seconds=-1 is not a bound: .*0 \(no deadline\)",
    s.resume(seconds=-1))
    assert not ses.running, "a refused resume never released the machine"
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    monkeypatch.setattr(running, "RESUME_POLL_S", 0.0)
    ticks: list[str] = []
    out = running.resume(ses, tmp_path, 0.02, lambda p, t, m: ticks.append(m))  # type: ignore[arg-type]
    assert out["verdict"] == "TIMEOUT" and ticks and ticks[0].startswith("resume: running")


def test_a_throttle_frame_flies_unthrottled_and_hands_the_harness_the_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The throttle on arrival is a boot harness this server writes."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    mine = tmp_path / "mine.lua"
    mine.write_text("-- the caller's\n")
    out = s.start(**_boot_args(tmp_path, image), throttle_from_frame=2790, boot_lua=str(mine))
    try:
        argv = _StubProcess.last_argv
        assert argv.count("-nothrottle") == 1
        harness = Path(argv[argv.index("-autoboot_script") + 1])
        assert harness == Path(out["boot_lua_path"]) and harness.parent == mstate.STATE.scratch
        text = harness.read_text()
        assert launch.THROTTLE_MARK in text and "video.throttled = true" in text
        assert text.rstrip().endswith(f'dofile("{mine.resolve()}")')
        assert out.get("env", {}) == {launch.THROTTLE_FRAME_VAR: "2790"}
        assert _StubProcess.last_kwargs.get("env", {})[launch.THROTTLE_FRAME_VAR] == "2790"
        assert out.get("throttle_from_frame", 0) == 2790
        assert argv[argv.index("-autoboot_delay") + 1] == "0"
    finally:
        s.close()
    out = s.start(**_boot_args(tmp_path, image), throttle_from_frame=10)
    try:
        assert "dofile" not in Path(out["boot_lua_path"]).read_text()
    finally:
        s.close()
    out = s.start(**_boot_args(tmp_path, image), boot_lua=str(mine))
    try:
        composed = Path(out["boot_lua_path"])
        assert composed.parent == mstate.STATE.scratch
        text = composed.read_text()
        assert text.rstrip().endswith(f'dofile("{mine.resolve()}")')
        assert launch.THROTTLE_MARK not in text, "no throttle frame, no throttle harness"
        assert "-nothrottle" not in _StubProcess.last_argv
    finally:
        s.close()
    _never_spawns(monkeypatch, tmp_path)
    refused("throttle_from_frame",
    s.start(**_boot_args(tmp_path, image), throttle_from_frame=-1))




def test_run_to_counts_a_control_off_its_temp_and_ticks_meanwhile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control is MAME's own counting breakpoint."""
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x4A0]                      # park, target
    ses.stops_after_polls = 3
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    ticks: list[str] = []
    gos: list[int] = []
    real_go = ses.go

    def go() -> None:
        gos.append(ses.stop_count)
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 2

    ses.go = go  # type: ignore[method-assign]
    out = advance.run_to(ses, tmp_path, "0x4a0", "0x25a4", 2.0,  # type: ignore[arg-type]
                         lambda p, t, m: ticks.append(m))
    assert (out["verdict"] == "TARGET" and out["control_hits"] == 2
            and out["cause"] == "target 0x4a0")
    assert out["controls"] == [{"ref": "0x25a4", "cpu": ":maincpu", "hits_in_run": 2}]
    assert gos == [0], "released once: a control never stops the machine"
    assert len(ticks) >= 2 and "run_to 0x4a0" in ticks[-1]
    assert ses.armed == [(0x4A0, False), (0x4A0, True)], "the target alone, armed and removed"
    assert any(r.endswith("if (++temp0)==0") for r in ses.bplist_rows), "the control stays"


def test_run_to_stops_elsewhere_and_times_out_with_the_right_verdicts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x1000]                      # park, somewhere else
    ses.stops_after_polls = 1
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 1

    ses.go = go  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["control_hits"] == 1
    assert (out["cause"] == "stopped at no breakpoint this server armed"
            and out["pc"] == "0x00001000")
    # A timeout: the control counts, the target never, the machine is interrupted at the bound.
    ses.pcs = [0xF2034, 0x25A4]
    ses.stop_count = 0
    ses.stops_after_polls = None
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["verdict"] == "TIMEOUT" and out["control_hits"] == 1 and ses.interrupted == 1
    assert out["cause"] == "interrupt at the bound" and not ses.running


def test_run_to_reports_a_session_that_broke_under_the_run_as_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stub closing the connection must come back neither as a TIMEOUT nor as a bare
    traceback: it is INVALID, naming why."""
    ses = _running(monkeypatch, tmp_path)

    def poll(timeout: float = 0.0) -> bool:
        raise g.SessionError("the stub closed the connection")

    ses.poll_stop = poll  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and "closed the connection" in out["message"]
    assert "Nothing about 0x4a0 was measured" in out["message"] and ses.interrupted == 0


def test_run_for_refuses_to_survey_a_machine_that_did_not_settle_after_the_interrupt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The interrupt of a console-started run gets no reply."""
    ses = _RegisterSession(bits=32, frame=10, stop_after=None)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.05)
    ses.halt = lambda: setattr(ses, "interrupted", True)  # type: ignore[method-assign]
    out = s.run_for(milliseconds=1000, seconds=0.05)
    assert out["status"] == "INVALID" and "did not come to rest" in out["message"]
    assert out["code"] == "not_settled"
    assert ses.interrupted and "dasm" not in out, "a moving machine is not surveyed"


def test_a_stop_found_by_a_call_that_then_refused_is_not_carried_to_the_next_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.resume()
    ses.stops_after_polls = 1                        # a breakpoint fired meanwhile
    out = s.write(ref="no_such_symbol", data_hex="00")
    assert out["status"] == "INVALID", out
    assert out["stopped_on_its_own"]["stop_seq"] == 2, "the account rides on the refusal itself"
    assert mstate.STATE.last_stop["seq"] == 2, "the record stands"
    out = s.registers()
    assert "stopped_on_its_own" not in out, "the account was delivered with the call it belonged to"


def test_stop_landing_on_an_armed_breakpoint_is_attributed_to_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    s.resume()
    out = s.stop()
    assert out["interrupted"] is True and out["cause"] == "breakpoint at 0x4a0"
    again = s.stop()
    assert again["summary"] == "stop: was already stopped"


def test_the_survey_says_when_the_console_gave_no_listing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _RegisterSession(bits=32, frame=10, stop_after=3)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    out = s.run_for(milliseconds=100)
    assert out["dasm"]["available"] is False and "wrote no file" in out["dasm"]["why"]
    assert out["frame"] == 13 and out["errorlog"]["lines_total"] == 0
    run = _running(monkeypatch, tmp_path)
    stepped = s.step(count=2)
    assert stepped["cause"] == "step 2" and stepped["pc"] == "0x000025a4" and run.stop_count == 2
    assert stepped["dasm"] == ["25a4: move.l d0,d1", "25a4+2: rts"]


def test_the_tools_carry_the_clients_context_to_their_waits(tmp_path: Path) -> None:
    """End to end."""
    import anyio

    got: list[str] = []

    class _Ctx:
        async def report_progress(self, progress: float, total: float | None = None,
                                  message: str | None = None) -> None:
            got.append(str(message))

    async def main() -> None:
        with pytest.MonkeyPatch.context() as mp:
            ses = _running(mp, tmp_path)
            mp.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
            mp.setattr(running, "RESUME_POLL_S", 0.0)
            mp.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
            mp.setattr(core_wait, "POLL_S", 0.0)
            await anyio.to_thread.run_sync(lambda: s.resume(seconds=0.02, ctx=_Ctx()))
            assert got and got[-1].startswith("resume: running")
            got.clear()
            ses.go()
            await anyio.to_thread.run_sync(
                lambda: s.log_wait(channel="emulator", pattern="never", seconds=0.02, ctx=_Ctx()))
            assert got and got[-1].startswith("log_wait emulator /never/")

    anyio.run(main)


def test_the_advance_family_refuses_its_malformed_arguments_and_a_cold_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A control at the target's own address, a step of nothing."""
    ses = _running(monkeypatch, tmp_path)
    refused("same address",
    s.run_to(ref="0x4a0", control="0x4a0", seconds=1.0))
    refused(r"count=0 is outside 1\.\.300",
    s.step(count=0))
    refused(r"count=301 is outside 1\.\.300: a longer walk is `run_to` or `run_for`",
    s.step(count=advance.step_max() + 1))
    assert advance.step_max() == 300
    advance.check_step(count=advance.step_max())                      # AT the ceiling: taken
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "INVALID" and "never fired" in out["message"]
    assert out["code"] == "control_silent"
    listed = out["control_dasm"]
    assert [(c["ref"], c["cpu"]) for c in listed] == [("0x25a4", ":maincpu")], out
    assert isinstance(listed[0]["dasm"], list) and listed[0]["dasm"], out
    assert "listing" not in listed[0], "a listing is `dasm`, as the survey's"
    assert "ENTRY of something periodic" in out["note"]
    assert out["control_hits"] == 0 and ses.interrupted == 1, "the bound stopped the machine"
    # A LISTING THE CONSOLE CANNOT PRODUCE is said so, and the reply still comes back.
    real = read.dasm_lines

    def no_listing(ses: Any, scratch: Path, addr: int, length: int,
                   cpu: str | None = None) -> list[str]:
        if length == advance.CONTROL_DASM_BYTES:
            raise g.SessionError("the console's `dasm` wrote no file")
        lines: list[str] = real(ses, scratch, addr, length, cpu)
        return lines

    monkeypatch.setattr(read, "dasm_lines", no_listing)
    again = s.run_to(ref="0x4a2", seconds=0.05)
    assert again["code"] == "control_silent"
    assert again["control_dasm"][0]["dasm"]["available"] is False, "the survey's own shape"


def test_a_run_to_that_comes_back_invalid_still_records_the_stop_it_made(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The INVALID paths (a cold control at the bound, a stop elsewhere with a cold control)
    leave the machine STOPPED, and an unrecorded stop means the next contact finds a stop
    the record does not describe and reports the server's own interrupt as
    `stopped_on_its_own`, attributed to no breakpoint. An INVALID run carries the survey of
    where it left the machine, as every other stop does."""
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x3000]
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "INVALID" and out["cause"] == "interrupt at the bound"
    assert out["pc"] == "0x00003000" and "regs" in out and "dasm" in out
    seq = mstate.STATE.last_stop["seq"]
    nxt = s.status()
    assert "stopped_on_its_own" not in nxt and mstate.STATE.last_stop["seq"] == seq
    # A stop ELSEWHERE before the control ever fired: INVALID too, and surveyed where it is.
    ses.pcs = [0xF2034, 0x1000]
    ses.stop_count = 0
    ses.stops_after_polls = 1
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and out["control_hits"] == 0
    assert (out["cause"] == "stopped at no breakpoint this server armed"
            and out["pc"] == "0x00001000")
    assert "stopped_on_its_own" not in s.status()


def test_run_to_reads_bplist_back_after_arming_its_two_breakpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`breakpoint_at` and the re-arm read `bplist` after every arm."""
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bp 0x4a0"):
            return "Breakpoint 9 set\n\n"            # taken, listed by nobody
        return str(real(command, timeout))

    monkeypatch.setattr(ses, "monitor", monitor)
    released = []
    ses.go = lambda: released.append(True)  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and "bplist" in out["message"]
    assert "bp 0x4a0" in out["message"], out
    assert released == [], "the machine was never released: the list was read BEFORE `go`"
    assert not ses.running and (0x4A0, True) not in ses.armed, "no `z0` for an unlisted row"
    assert [r for r in ses.bplist_rows if "temp0" in r], "the declared control keeps its row"
    assert "bplist" in ses.commands


def test_run_to_over_a_declared_breakpoint_leaves_the_declaration_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `run_to` over a declared STOP breakpoint leaves that declaration armed."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "store", dec.DeclarationStore("t", None))
    monkeypatch.setattr(mstate.STATE, "session_origin", "s1")
    assert s.breakpoint_at(ref="0x4a0")["armed"] is True
    refused("already declared as a stop", s.run_to(ref="0x25a4", control="0x4a0", seconds=1.0))
    ses.pcs = [0xF2034, 0x25A4]
    ses.stops_after_polls = 1
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = 1

    ses.go = go  # type: ignore[method-assign]
    out = s.run_to(ref="0x25a4", control="0x600", seconds=1.0)
    assert out["verdict"] == "TARGET" and out["control_hits"] == 1
    assert [r for r in ses.bplist_rows if r.endswith("@ 0004A0")], "the declaration's row stays"
    listed = {b["ref"]: b for b in s.declaration_list("breakpoint")["breakpoints"]}
    assert listed["0x4a0"]["state"] == "armed" and listed["0x4a0"]["role"] == "stop"
    assert listed["0x600"]["role"] == "control" and listed["0x600"]["hits_since_armed"] == 1


def test_a_window_helper_that_hangs_is_bounded_and_one_that_prints_nothing_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`subprocess.run` on the helper had no bound."""
    slow = tmp_path / "slow"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    monkeypatch.setenv("WINDOW_APP", str(slow))
    with monkeypatch.context() as tight:
        tight.setattr(placement, "HELPER_TIMEOUT_S", 0.2)
        with pytest.raises(mstate.Invalid, match="did not answer within") as e:
            launch.window_flags(shared=True, display="main")
    assert "not at" not in str(e.value)
    mute = tmp_path / "mute"
    mute.write_text("#!/bin/sh\nexit 3\n")
    mute.chmod(0o755)
    monkeypatch.setenv("WINDOW_APP", str(mute))
    with pytest.raises(mstate.Invalid, match="exit code 3 and printed 'nothing'"):
        launch.window_flags(shared=True, display="main")


def test_run_to_refused_at_the_readback_removes_only_what_was_listed_and_says_if_it_could_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The refusal after the `bplist` readback must not send a removal for the unlisted
    target too: nothing is sent for a row the debugger never listed, and the declared control
    is not the run's to remove."""
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bp 0x4a0"):
            ses.commands.append(command)
            return "Breakpoint 9 set\n\n"            # taken, listed by nobody
        return str(real(command, timeout))

    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and "bp 0x4a0" in out["message"]
    assert out["code"] == "readback_refused" and out["control_hits"] == 0
    assert not any(c.startswith("bpclear") for c in ses.commands), (
        "no removal for a row the debugger never listed, and the control stays")


def test_the_boundary_tells_the_session_s_presence_of_each_call(
        monkeypatch: pytest.MonkeyPatch) -> None:
    heard: list[tuple[str, str]] = []

    class Heard:
        def began(self, tool: str) -> None:
            heard.append(("began", tool))

        def ended(self, tool: str) -> None:
            heard.append(("ended", tool))
    monkeypatch.setattr(mstate.STATE, "presence", presence_mod.Shown(held=Heard()))  # type: ignore[arg-type]
    assert s.status()["status"] == "ok"
    assert heard == [("began", "status"), ("ended", "status")]


def test_boot_names_a_process_that_died_without_waiting_out_the_bound(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A MAME THAT DIED IS KNOWN DEAD AT ONCE."""
    began = time.monotonic()
    refusal = _boot_against(monkeypatch, tmp_path, exit_code=7, wait=5.0)
    took = time.monotonic() - began
    assert took < 1.0, f"a dead process cost {took:.2f} s of a 5 s bound"
    assert refusal.code == "session_broken" and refusal.fields["exit_code"] == 7, refusal
    assert "exited with code 7" in str(refusal) and "did not answer" not in str(refusal)


def test_resume_then_close_reports_the_speed_the_host_held_over_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """MAME's own `Average speed` line is suppressed on a debugger-driven exit."""
    ses = _RegisterSession(bits=32)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    wall = [100.0]
    monkeypatch.setattr("mame_running.time.monotonic", lambda: wall[0])
    ses.emu_clock = 5.0
    r = s.resume()
    assert "verdict" not in r and "running" not in r and ses.running, r
    wall[0] = 102.0
    ses.emu_clock = 6.0
    ses.running = False
    closed = s.close()
    assert closed["average_speed"] == {"percent": 50.0, "emulated_s": 1.0,
                                       "wall_s": 2.0}, closed


def test_a_stop_found_by_a_later_contact_ends_the_run_and_carries_its_speed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The window a `resume` opened closes at the stop that ends the run, whoever finds it."""
    ses = _running(monkeypatch, tmp_path)
    wall = [100.0]
    monkeypatch.setattr("mame_running.time.monotonic", lambda: wall[0])
    ses.emu_clock = 5.0
    assert s.resume()["session"]["running"] is True
    ses.stops_after_polls = 1
    wall[0], ses.emu_clock = 102.0, 6.0
    found = s.status()["stopped_on_its_own"]
    assert found["average_speed"] == {"percent": 50.0, "emulated_s": 1.0,
                                      "wall_s": 2.0}, found
    assert mstate.STATE.run_release is None
    wall[0], ses.emu_clock = 702.0, 6.5
    assert "average_speed" not in s.step(count=1), "a step long after opened no window"


def test_a_close_with_no_run_open_reports_no_speed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A session closed without a `resume` in flight has no window to measure."""
    ses = _RegisterSession(bits=32)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    closed = s.close()
    assert "average_speed" not in closed, closed


def test_the_speed_and_its_two_times_are_rounded_to_what_each_can_carry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ses = _window(monkeypatch, wall_s=2.5004613579, emulated_s=1.23456789)
    assert running.average_speed(ses) == {"percent": 49.37, "emulated_s": 1.234568,
                                          "wall_s": 2.500461}


@pytest.mark.parametrize("wall_s", [0.01, 0.5])
def test_a_window_of_a_hundredth_of_a_second_or_more_is_a_speed(
    wall_s: float, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor keeps a division by almost nothing out, and it is a hundredth, inclusive."""
    ses = _window(monkeypatch, wall_s=wall_s, emulated_s=wall_s)
    speed = running.average_speed(ses)
    assert speed is not None and speed["wall_s"] == wall_s, speed


def test_a_release_whose_clock_cannot_be_read_opens_no_window_and_the_stop_still_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    wall = [100.0]
    monkeypatch.setattr("mame_running.time.monotonic", lambda: wall[0])
    monkeypatch.setattr(ses, "emulated_seconds", lambda: None)
    assert s.resume()["session"]["running"] is True
    monkeypatch.setattr(ses, "emulated_seconds", lambda: 6.0)
    wall[0] = 102.0
    out = s.stop()
    assert out["interrupted"] is True and "average_speed" not in out, out


def test_a_bounded_resume_asks_the_socket_in_polls_no_longer_than_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    asked: list[float | None] = []
    real = ses.poll_stop

    def poll_stop(timeout: float = 0.0) -> bool:
        asked.append(timeout)
        return real(timeout)

    monkeypatch.setattr(ses, "poll_stop", poll_stop)
    ses.stops_after_polls = 2
    assert s.resume(seconds=5.0)["verdict"] == "OTHER_STOP"
    polls = asked[-2:]
    assert all(t is not None and 0.0 <= t <= running.RESUME_POLL_S for t in polls), asked


def test_a_stop_of_a_run_the_console_started_is_proved_on_the_counter_and_says_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _RegisterSession(bits=32, stop_after=None)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "console_run", True)
    monkeypatch.setattr("mame_running.time.sleep", lambda gap_s: None)
    ses.running = ses.emulating = True
    out = s.stop()
    assert "running" not in out and out["status"] == "ok" and out["interrupted"] is True, out
    assert out["session"]["running"] is False and ses.running is False, out["session"]
    assert ses.interrupted and ses.received == [g.STOP_REPLY_DRAIN_S]
    again = s.stop()
    assert again["interrupted"] is False and again["session"]["running"] is False, again
    assert "note" in again and again["last_stop"]["cause"] == "interrupt", again


def test_the_throttle_lift_resets_the_speed_window_to_the_real_speed_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A P5 run flies flat out to a late frame and drops to REAL speed there, all inside one
    `resume`. Its speed window opened at the resume (the ramp), so `average_speed` over the
    whole run blends the fast ramp with the real-speed play. When the server sees the throttle
    harness's lift mark in error.log -- the natural way a caller learns the fly is done is
    `log_wait` on it -- the window is reset to that moment, so the real-speed part is
    what `close` reports. Reset once, and only while a run window is open."""
    ses = _RegisterSession(bits=32)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    (tmp_path / "error.log").write_text("boot\nMAME_MCP throttled from frame 900\n")
    mstate.STATE.run_release = {"emulated": 0.0, "wall": 100.0}   # the ramp's start
    ses.emu_clock = 15.0                                          # emulated at the lift
    monkeypatch.setattr("mame_running.time.monotonic", lambda: 200.0)
    out = s.log(channel="emulator", pattern="throttled from frame")
    assert out["status"] == "ok" and out["lines_total"] == 1, out
    assert mstate.STATE.run_release == {"emulated": 15.0, "wall": 200.0}, mstate.STATE.run_release
    assert mstate.STATE.throttle_seen is True
    # A second read does NOT reset again: the window now belongs to the real-speed run.
    ses.emu_clock = 40.0
    s.log(channel="emulator", pattern="throttled from frame")
    assert mstate.STATE.run_release == {"emulated": 15.0, "wall": 200.0}, "reset more than once"




def test_a_controls_hits_are_the_delta_and_the_count_after_only_when_it_fell() -> None:
    main = ":maincpu"
    before: dict[tuple[str, str | None], int] = {("same", main): 5, ("rose", main): 5,
                                                 ("fell", main): 5}
    after: dict[tuple[str, str | None], int] = {("same", main): 5, ("rose", main): 8,
                                                ("fell", main): 3}
    assert advance._hits(before, after, list(after)) == [
        {"ref": "same", "cpu": ":maincpu", "hits_in_run": 0},
        {"ref": "rose", "cpu": ":maincpu", "hits_in_run": 3},
        {"ref": "fell", "cpu": ":maincpu", "hits_in_run": 3}]
    assert advance._hits(before, after, [("rose", main)]) == [
        {"ref": "rose", "cpu": ":maincpu", "hits_in_run": 3}], "only the owners asked for"


def test_run_to_refuses_a_target_a_breakpoint_already_holds_in_the_words_of_that_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    out = refused(r"already has breakpoint 1 at 0x4a0: a stop there", s.run_to(
        ref="0x4a0", control="0x25a4", seconds=1.0))
    assert "(condition" not in out["message"], out["message"]
    s.declaration_clear("breakpoint", all=True)
    s.breakpoint_at(ref="0x4a0", condition="d0 == 1")
    out = refused(r"at 0x4a0 \(condition \S.*\): a stop there", s.run_to(
        ref="0x4a0", control="0x25a4", seconds=1.0))
    assert ses.running is False


def test_a_target_the_console_does_not_list_is_refused_in_the_words_of_how_it_was_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "breakpoint", lambda addr, remove=False: None)   # taken, not listed
    out = refused("the console took `bp 0x4a0::maincpu` and its `bplist` does not list it",
                  s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0))
    assert out["code"] == "readback_refused" and out["control_hits"] == 0, out


def test_run_to_polls_inside_its_bound_and_names_the_stop_it_did_not_ask_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x1000")
    ses.pcs = [0xF2034, 0x1000]
    ses.stops_after_polls = 1
    bounds: list[float] = []
    poll = ses.poll_stop

    def polled(timeout: float = 0.0) -> bool:
        bounds.append(timeout)
        return poll(timeout)

    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 1

    monkeypatch.setattr(ses, "poll_stop", polled)
    monkeypatch.setattr(ses, "go", go)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cause"] == "breakpoint at 0x1000", out
    assert "condition" not in out, "a run with no condition carries none"
    assert bounds and all(isinstance(b, float) and 0.0 <= b <= advance.RUN_POLL_S for b in bounds)


def test_a_run_to_that_found_nothing_to_trust_still_answers_with_every_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # The session broke under the run: the count is a zero that says nothing was measured.
    ses = _running(monkeypatch, tmp_path)

    def poll(timeout: float = 0.0) -> bool:
        raise g.SessionError("the stub closed the connection")

    disarmed: list[bool] = []
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bpclear"):
            disarmed.append(True)
            raise g.SessionError("the stub closed the connection")
        return str(real(command, timeout))

    monkeypatch.setattr(ses, "poll_stop", poll)
    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["code"] == "session_broken" and out["control_hits"] == 0, out
    assert disarmed == [True], "the removal is tried, and its failure is not the news"
    # The control never fired: the stop is surveyed, each control listed with its listing.
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x1000]
    ses.stops_after_polls = None
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    real_monitor = ses.monitor

    def no_listing(command: str, timeout: float = 10.0) -> str:
        if command.startswith("dasm ") and "0x25a4" in command:
            raise g.SessionError("the console refused the listing")
        return real_monitor(command, timeout)

    monkeypatch.setattr(ses, "monitor", no_listing)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["code"] == "control_silent", out
    assert out["controls"] == [{"ref": "0x25a4", "cpu": ":maincpu", "hits_in_run": 0}], out
    assert out["control_dasm"] == [{"ref": "0x25a4", "cpu": ":maincpu", "dasm": {
        "available": False, "why": "the console refused the listing"}}], out
    assert out["message"].startswith("the control (0x25a4) never fired"), out["message"]
    # A stop that was not the target's, before any control fired: cut, with the controls listed.
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x1000]
    ses.stops_after_polls = 1
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["code"] == "cut_by_other_stop"
    assert out["controls"] == [{"ref": "0x25a4", "cpu": ":maincpu", "hits_in_run": 0}]


def test_an_interrupt_the_stub_refuses_at_the_bound_does_not_escape_run_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.stops_after_polls = None
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)

    def wedged(timeout: float = 5.0) -> str:
        raise g.Timeout("no answer within 5 s")

    monkeypatch.setattr(ses, "interrupt", wedged)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out


def test_a_conditional_run_to_carries_the_condition_as_the_console_read_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x4A0]
    ses.stops_after_polls = 1
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 1

    monkeypatch.setattr(ses, "go", go)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, condition="  d0 == 1 ")
    assert out["verdict"] == "TARGET", out
    assert out["condition"] == conditions.console_condition("  d0 == 1 ") == "d0 == 1", out


def test_the_account_of_a_stop_found_later_has_every_field_and_the_name_of_where_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr("mame_running.time.monotonic", lambda: 100.0)   # no span, so no speed
    s.breakpoint_at(ref="0x4a0")
    ses.pcs = [0xF2034, 0x4A0]
    s.resume()
    ses.stops_after_polls = 1
    bounds: list[float] = []
    poll = ses.poll_stop

    def polled(timeout: float = 0.0) -> bool:
        bounds.append(timeout)
        return poll(timeout)

    monkeypatch.setattr(ses, "poll_stop", polled)
    found = s.status()["stopped_on_its_own"]
    assert found == {"stop_seq": 2, "pc": "0x000004a0", "cpu": ":maincpu", "frame": ses.frame,
                     "cause": "breakpoint at 0x4a0", "packet": "T05"}, found
    assert bounds == [0.0], "the first contact looks and never waits"


def test_a_console_run_found_at_rest_carries_the_speed_of_the_window_it_ends(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    wall = [100.0]
    monkeypatch.setattr("mame_running.time.monotonic", lambda: wall[0])
    monkeypatch.setattr(running, "frame_at_rest", lambda ses_, reads=3, gap_s=0.1: True)
    ses.emu_clock = 5.0
    assert s.resume()["session"]["running"] is True
    monkeypatch.setattr(mstate.STATE, "console_run", True)
    wall[0], ses.emu_clock = 102.0, 6.0
    found = s.status()["stopped_on_its_own"]
    assert found["packet"] == "none: a run the console started", found
    assert found["average_speed"] == {"percent": 50.0, "emulated_s": 1.0,
                                      "wall_s": 2.0}, found
    assert mstate.STATE.run_release is None


def test_a_reader_refused_on_a_running_machine_is_told_the_last_stop_or_that_there_is_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    with pytest.raises(g.NotStopped,
                       match=r"; last seen stopped at pc 0x000f2034 on :maincpu \(start, "):
        running.require_stopped(ses, "a read")  # type: ignore[arg-type]
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    with pytest.raises(g.NotStopped, match="; no stop recorded yet. Wait for"):
        running.require_stopped(ses, "a read")  # type: ignore[arg-type]


def test_the_survey_says_truncated_only_past_what_it_shows_and_dates_the_watches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    log = files.log_path(tmp_path, "emulator")
    shown = log_marks.STOP_LINES_SHOWN
    log.write_text("".join(f"line {n}\n" for n in range(shown)))
    monkeypatch.setattr(mstate.STATE, "errorlog_mark", 0)
    seen = running.survey(ses, tmp_path)  # type: ignore[arg-type]
    assert seen["errorlog"]["lines_total"] == shown and seen["errorlog"]["mark"] == 0
    assert seen["errorlog"]["truncated"] is False, "exactly what is shown is not truncated"
    assert "how" not in seen["errorlog"], "a whole block names no way to ask for more"
    # One past what is shown: cut, from the mark where the previous stop left the log, and the
    # block names the call that reads the rest from there.
    since = log.stat().st_size
    with log.open("a") as fh:
        fh.write("".join(f"more {n}\n" for n in range(shown + 1)))
    cut = running.survey(ses, tmp_path)["errorlog"]  # type: ignore[arg-type]
    assert cut["truncated"] and cut["lines_total"] == shown + 1 and cut["mark"] == since, cut
    assert cut["lines"][0] == "more 1" and f"since_mark={since}" in cut["how"], cut
    handed: list[tuple[Any, ...]] = []
    monkeypatch.setattr(watches, "evaluate_watches",
                        lambda *a: handed.append(a) or [])  # type: ignore[func-returns-value]
    running.survey(ses, tmp_path)  # type: ignore[arg-type]
    assert handed[0][1] == {} and handed[0][2] == {} and handed[0][3] == ses.frame, handed
    # An expression list the console refuses whole takes the expressions down, never the frame.
    monkeypatch.setattr(watches, "expression_refs", lambda: ["nope"])
    running.survey(ses, tmp_path)  # type: ignore[arg-type]
    assert isinstance(handed[1][2], g.SessionError) and handed[1][3] == ses.frame, handed[1]
    # And an answer shorter than the list asked for is never paired off silently.
    monkeypatch.setattr(read, "print_values", lambda ses_, names: [ses.frame])
    with pytest.raises(ValueError, match="zip"):
        running.survey(ses, tmp_path)  # type: ignore[arg-type]


def test_a_conditional_target_the_console_does_not_list_is_refused_as_the_console_took_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    real_monitor = ses.monitor

    def deaf(command: str, timeout: float = 10.0) -> str:
        return "" if command.startswith("bp 0x4a0:") else real_monitor(command, timeout)

    monkeypatch.setattr(ses, "monitor", deaf)
    out = refused(r"the console took `bp 0x4a0::maincpu,.+` and its `bplist` does not list it",
                  s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, condition="d0 == 1"))
    assert out["code"] == "readback_refused", out


def test_a_target_listed_without_its_condition_is_removed_before_the_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row armed bare where a conditioned one was sent stops at every pass."""
    ses = _running(monkeypatch, tmp_path)
    real_monitor = ses.monitor

    def bare(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bp 0x4a0:") and "," in command:
            command = command.split(",", 1)[0]
        return real_monitor(command, timeout)

    monkeypatch.setattr(ses, "monitor", bare)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, condition="d0 == 1")
    assert out["code"] == "readback_refused" and "without its condition" in out["message"], out
    assert not any(r["addr"] == 0x4A0 for r in mlists.bp_held(ses)  # type: ignore[arg-type]
                   ), "the bare row is gone"


def test_a_run_by_frames_that_elapsed_says_so_with_its_clock_its_polls_and_its_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    ses.last_stop_packet = "T05watch:200fd4;"
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    said: list[str] = []
    out = advance.run_for(ses, tmp_path, 0, 5.0,  # type: ignore[arg-type]
                          lambda _p, _t, m: said.append(m), frames=2)
    assert out["verdict"] == "ELAPSED" and "elapsed" not in out["cause"], out
    assert (out["frame_before"], out["frame_after"], out["polls"]) == (10, 12, 2), out
    assert out["cycles"] == 2 * ses.cycles_per_frame, out
    assert said[0] == "run_for 2 frames: frame 11 of 12, 0s of 5s", said
    assert ses.last_stop_packet == "", "the packet of the stop before the run is not this stop's"
    assert ses.commands.count("print frame") == 2 * 2 + 2 + 1, (
        "two agreeing reads confirm each landing, two a gap apart prove the last one at rest, "
        "and the survey reads the frame once")


def test_a_run_by_frames_reports_frames_done_of_the_frames_asked_and_ends_at_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The measure of a frame run is its frames, not its wall-clock bound."""
    ses = _by_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    got: list[tuple[float, float | None]] = []

    def record(p: float, t: float | None, _m: str) -> None:
        got.append((p, t))

    out = advance.run_for(ses, tmp_path, 0, 5.0,  # type: ignore[arg-type]
                          mprogress.RebasedProgress(record), frames=3)
    assert out["verdict"] == "ELAPSED", out
    assert got[-1] == (3.0, 3.0), got
    assert all(t == 3 for _p, t in got) and all(0 <= p <= 3 for p, _t in got), got
    values = [p for p, _t in got]
    assert all(b > a for a, b in zip(values, values[1:], strict=False)), got
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 3600.0)
    got.clear()
    out = advance.run_for(ses, tmp_path, 0, 5.0, record, frames=2)  # type: ignore[arg-type]
    assert out["verdict"] == "ELAPSED", out
    assert got == [(2.0, 2.0)], got


def test_the_waits_measured_in_time_report_no_total(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    totals: list[float | None] = []
    ses.stops_after_polls = 3
    advance.run_to(ses, tmp_path, "0x4a0", "0x25a4", 1.0,  # type: ignore[arg-type]
                   lambda _p, t, _m: totals.append(t))
    assert totals and all(t is None for t in totals), totals
    totals.clear()
    ses.stops_after_polls = 3
    running.resume(ses, tmp_path, 1.0, lambda _p, t, _m: totals.append(t))  # type: ignore[arg-type]
    assert totals and all(t is None for t in totals), totals


def test_a_run_by_frames_whose_alignment_clock_cannot_be_read_reports_no_cycles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    ses.frozen = True
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "print totalcycles" and ses.frozen:
            ses.frozen = False
            raise g.SessionError("the console refused `print totalcycles`")
        return real(command, timeout)

    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_for(frames=1)
    assert out["verdict"] == "ELAPSED" and out["polls"] == 2, out
    assert out["cycles"] == {"available": False, "why": "`totalcycles` could not be read before "
                                                         "the run, so there is no baseline"}, out


def test_a_run_by_frames_that_never_moves_gives_up_one_gvblank_past_the_alignment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    ses.frozen = True
    out = s.run_for(frames=1)
    assert out["code"] == "no_progress" and ses.commands.count("gvblank") == 3, out
    assert (out["frame_before"], out["frame_after"]) == (10, 10), out
    assert ses.running is True and mstate.STATE.console_run is True
    # THE COUNTER THAT NEVER MOVED CANNOT PROVE REST: the next reader's contact reads it
    # frozen, which is what it already was, so the machine stays RUNNING until `stop`.
    assert s.read_memory(ref="0x400")["code"] == "not_stopped"
    assert ses.running is True, "no contact took the frozen counter for a stop"


@pytest.mark.parametrize("looks,reads,after", [
    ([False, True], ["a"], 10),
    ([False, False, True], ["b"], 11),
    ([False, False, False, True], ["b", "c"], 12),
])
def test_a_run_by_frames_out_of_clock_reports_the_last_frame_it_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, looks: list[bool], reads: list[str],
    after: int,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    ses.frame_answers = ["a", *reads]
    monkeypatch.setattr(_ScriptedClock, "answers", list(looks))
    monkeypatch.setattr(mprogress, "Ticker", _ScriptedClock)
    out = s.run_for(frames=5)
    assert out["code"] == "not_settled", out
    assert (out["frame_before"], out["frame_after"]) == (10, after), out


def test_a_run_by_frames_cut_by_a_stop_this_server_armed_counts_the_clock_up_to_the_cut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "here", 0xF2034)))
    out = s.run_for(frames=3)
    assert out["verdict"] == "OTHER_STOP" and out["polls"] == 1, out
    assert (out["frame_before"], out["frame_after"]) == (10, 11), out
    assert out["cycles"] == ses.cycles_per_frame, out
    # With the clock unreadable at the cut the cycles are None, never a guess.
    ses = _by_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "here", 0xF2034)))
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "print totalcycles":
            raise g.SessionError("the console refused `print totalcycles`")
        return real(command, timeout)

    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_for(frames=3)
    assert out["verdict"] == "OTHER_STOP" and out["cycles"]["available"] is False, out
    # And a clock that could not be read at the ALIGNING tick stays unknown at the cut, even
    # when the console answers again by then.
    ses = _by_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "here", 0xF2034)))
    ses.frozen = True
    real_again = ses.monitor
    refused_once: list[bool] = []

    def once(command: str, timeout: float = 10.0) -> str:
        if command == "print totalcycles" and not refused_once:
            refused_once.append(True)
            raise g.SessionError("the console refused `print totalcycles`")
        return real_again(command, timeout)

    monkeypatch.setattr(ses, "monitor", once)
    out = s.run_for(frames=3)
    assert out["verdict"] == "OTHER_STOP" and out["cycles"]["available"] is False, out


def test_a_run_by_time_that_made_no_progress_still_says_how_it_ended_and_between_which_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    ses.frame_answers = ["a"] * 5
    out = s.run_for(milliseconds=1)
    assert out["code"] == "no_progress" and out["cause"] == "the console's `gtime` stop", out
    assert (out["frame_before"], out["frame_after"]) == (10, 10), out


def test_a_run_by_time_cut_at_a_breakpoint_this_server_armed_is_named_by_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "there", 0xF2100)))
    ses.frame_answers = ["a"] * 5               # cut before a frame elapsed
    out = s.run_for(milliseconds=1)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == running.attribute(0xF2100, ":maincpu") != (
        "stopped at no breakpoint this server armed")


@pytest.mark.parametrize("refusal", [g.SessionError("the socket went"), OSError("broken pipe")])
def test_a_run_by_time_at_its_bound_reports_the_frame_the_machine_came_to_rest_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, refusal: Exception,
) -> None:
    """The interrupt lands a few readings late, and a refused one is not the news."""
    ses = _by_frames(monkeypatch, tmp_path, stop_after=None)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)

    def halt() -> None:
        ses.interrupted = True
        ses.stop_after = ses.polls_since_gtime + 3
        halted_at.append(len(ses.commands))
        raise refusal

    halted_at: list[int] = []
    monkeypatch.setattr(ses, "halt", halt)
    said: list[str] = []
    out = advance.run_for(ses, tmp_path, 60000, 0.05,  # type: ignore[arg-type]
                          lambda _p, _t, m: said.append(m))
    assert out["verdict"] == "TIMEOUT" and out["cause"] == "interrupt at the bound", out
    assert out["frame_after"] == ses.frame and out["frame_before"] == 10, out
    assert re.fullmatch(r"run_for 60000 ms: frame \d+, 0s of 0.05s", said[0]), said[0]
    rested = [c for c in ses.commands if c == "print frame"]
    assert out["reads"] == len(rested) - 1, "every reading but the survey's own is counted"
    after_halt = ses.commands[halted_at[0]:]
    assert after_halt[:7] == ["print frame"] * 5 + ["cpulist", "print frame"], (
        "three moving readings, then the third that agrees ends the wait; the sixth, after "
        "the visible cpu, is the survey's")
    assert after_halt[7] != "print frame"


def test_a_run_by_time_that_never_rests_reports_the_last_frame_it_saw_moving(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path, stop_after=None)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.05)
    monkeypatch.setattr(ses, "halt", lambda: None)
    out = s.run_for(milliseconds=1000, seconds=0.05)
    assert out["code"] == "not_settled", out
    assert (out["frame_before"], out["frame_after"]) == (10, ses.frame), out


def test_start_hands_its_progress_to_the_kill_its_guard_makes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The kill a failed boot triggers is a wait the owner watches."""
    image = bytes(range(64))
    ses = _stub_boot(monkeypatch, tmp_path, image, at=0)
    monkeypatch.setattr(ses, "dial", lambda: (_ for _ in ()).throw(OSError("refused")))
    seen: list[Any] = []
    real = mstate.wait_exit

    def recording(proc: Any, seconds: float, progress: Any, what: str) -> int | None:
        seen.append(progress)
        return real(proc, seconds, progress, what)

    monkeypatch.setattr(mstate, "wait_exit", recording)
    refused("did not answer", s.start(**_boot_args(tmp_path, image), boot_seconds=0.2))
    assert seen and all(p is mprogress.no_progress for p in seen), seen


def test_settle_throttles_keeps_the_machines_word_verbatim_and_flags_the_other_setting() -> None:
    """A mark whose `throttled=` is neither word is kept VERBATIM in the row."""
    mstate.STATE.throttles_pending = [{"tag": "MAME_MCP_THROTTLE#1", "on": True, "seq": 1},
                                      {"tag": "MAME_MCP_THROTTLE#2", "on": True, "seq": 2}]
    mstate.settle_throttles(["[luaengine] MAME_MCP_THROTTLE#1 throttled=maybe frame=3",
                             "[luaengine] MAME_MCP_THROTTLE#2 throttled=false frame=4"])
    rows = mstate.STATE.throttles_not_applied
    assert [r["machine_reports"] for r in rows] == ["maybe", False], rows
    assert mstate.STATE.throttles_pending == []


def test_a_by_outside_breakpoint_ats_words_lists_only_the_words_it_takes() -> None:
    """A closed vocabulary's refusal names the words the tool takes."""
    out = refused("by is one of", s.breakpoint_at(ref="0x4a0", by="bogus"))
    assert "'address'" in out["message"] and "expr" not in out["message"], out["message"]
    assert "pointer" not in out["message"], out["message"]
    out = refused("by is one of", s.watch_add(ref="0x4a0", mode="change", by="bogus", length=2))
    assert "'pointer'" in out["message"] and "'expr'" not in out["message"], (
        "a watch takes a pointer, and an expr watch is its mode, never its `by`")


def test_a_control_carrying_a_segment_is_refused_before_any_session() -> None:
    """A `control` is a ref like `ref`, and the shape every ref is held to is judged offline."""
    out = refused("carries a segment", s.run_to(ref="0x4a0", control="12:34"))
    assert out["code"] == "bad_argument", out
    refused(r"control='0xzz'", s.run_to(ref="0x4a0", control="0xzz"))


def test_the_port_probe_answers_the_port_it_bound() -> None:
    """The real bind, not a double: the kernel's pick is a port, and a named free one is itself."""
    chosen = owner.bind_probe(0)
    assert chosen is not None and chosen > 0, chosen
    assert owner.bind_probe(chosen) == chosen
