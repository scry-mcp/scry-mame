"""What the session says about itself after a `SessionError` in the middle of a run.

The readers' gate trusts one flag and no query proves rest, so each case here breaks the
session at one point of a run and reads what the NEXT caller is told.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from scry_core import media_tools

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scry_core import progress as mprogress  # noqa: E402
from session_doubles import captured, documented, refused  # noqa: E402
from test_gdb_session import _wired  # noqa: E402
from test_reply_contract import _ARGS, _tools  # noqa: E402
from test_server import _install, _RegisterSession, _running  # noqa: E402

import gdb_session as g  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_files as files  # noqa: E402
import mame_lists as mlists  # noqa: E402
import mame_read as read  # noqa: E402
import mame_running as running  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_transport as transport  # noqa: E402
import mame_watches as watches  # noqa: E402
import server as s  # noqa: E402

NOT_A_STOP = ("the stub sent 'OK' while the machine ran, which is not a stop reply: the "
              "session cannot be trusted")


def _console_double(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """A stopped console double whose clocks cost nothing, with the console release restored
    after the case: these cases end with `console_run` set."""
    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    monkeypatch.setattr(advance, "VBLANK_SETTLE_S", 0.0)
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    return reg


def _owed(double: Any, packet: str) -> g.Timeout:
    """What the REAL client raises when `packet` gets no answer in time, and the latch it
    leaves, carried onto the double: taken from `Session.request` over a silent wire, never
    written here, so the double breaks the way the client does."""
    ses, _wire = _wired([])
    try:
        ses.request(packet, timeout=0.0)
    except g.Timeout as e:
        double.broken = ses.broken
        return e
    raise AssertionError(f"`{packet}` over a silent wire must run out")


def _console(command: str) -> str:
    """The packet the real client builds for a console command."""
    return g.Session().console_packet(command)


def _failing_at(reg: Any, failing: str, after: str = "",
                error: g.SessionError | None = None) -> None:
    """Make the double's console fail on `failing`, from the moment `after` has gone out (at
    once when `after` is empty): unanswered in time by default, else with `error`."""
    real = reg.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == failing and (not after or after in reg.commands):
            reg.commands.append(command)
            raise error or _owed(reg, _console(command))
        return str(real(command, timeout))

    reg.monitor = monitor


def _refused(command: str) -> g.SessionError:
    """What the REAL client raises when the stub answers `command` with `E01`."""
    ses, _wire = _wired(["E01"])
    try:
        ses.monitor(command)
    except g.SessionError as e:
        assert ses.broken is None, "a refusal is an answer: it latches nothing"
        return e
    raise AssertionError(f"`{command}` answered E01 must be refused")


REFUSED_GVBLANK, REFUSED_OVER, REFUSED_PRINT = (
    _refused("gvblank"), _refused("over"), _refused("print frame"))


def _latched_on(reg: Any, command: str, out: dict[str, Any]) -> None:
    """`out` is the latch's refusal for a `command` left unanswered, and the next contact is
    refused the same way: the reply it is owed would be read as the next request's."""
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert f"`{command}` got no answer" in out["message"], out["message"]
    assert "RUNNING" not in out["message"], "a broken session is never described as running"
    assert reg.broken is not None and f"`{command}`" in reg.broken, reg.broken
    assert out["session"]["running"] is False and "`start`" in out["message"], out
    after = s.registers()
    assert after["code"] == "session_broken" and "`close`" in after["message"], after


# ------------------------------------------------ a console release that fails lets go


def _stop_proved_at_next_contact(reg: Any) -> None:
    """THE DOUBLE IS IN FACT STOPPED (its console never took the command), which is the
    benign half of the asymmetry: the flag costs one proof on the frame counter at the next
    contact, which then serves and says what it found."""
    after = s.registers()
    assert after["stopped_on_its_own"]["packet"] == "none: a run the console started", after
    assert reg.running is False and mstate.STATE.console_run is False


def test_a_run_by_frames_whose_gvblank_is_refused_leaves_the_session_saying_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    _failing_at(reg, "gvblank", error=REFUSED_GVBLANK)
    out = s.run_for(frames=2, seconds=1.0)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert "`gvblank`" in out["message"] and "`stop`" in out["message"], out["message"]
    assert "E01" in out["message"], "what the release failed on"
    assert out["frame_before"] == 10, out
    assert reg.running is True and mstate.STATE.console_run is True
    _stop_proved_at_next_contact(reg)


def test_a_run_by_frames_whose_gvblank_is_not_answered_in_time_latches_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    _failing_at(reg, "gvblank")
    out = s.run_for(frames=2, seconds=1.0)
    _latched_on(reg, "gvblank", out)
    assert out["frame_before"] == 10, "the latch still says how far the counter got"


def test_a_run_by_frames_whose_landing_is_refused_leaves_the_session_saying_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    _failing_at(reg, "print frame", after="gvblank", error=REFUSED_PRINT)
    out = s.run_for(frames=2, seconds=1.0)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert "RUNNING" in out["message"] and "`stop`" in out["message"], out["message"]
    assert reg.running is True and mstate.STATE.console_run is True
    refused("RUNNING", s.read_memory(ref="0x1000", length=4))


def test_a_run_by_frames_whose_landing_is_not_answered_in_time_latches_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    _failing_at(reg, "print frame", after="gvblank")
    _latched_on(reg, "print frame", s.run_for(frames=2, seconds=1.0))


def test_a_step_over_whose_over_is_refused_leaves_the_session_saying_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    _failing_at(reg, "over", error=REFUSED_OVER)
    out = s.step(count=3, mode="over")
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert "`over`" in out["message"] and "`stop`" in out["message"], out["message"]
    assert "E01" in out["message"], "what the release failed on"
    assert out["mode"] == "over" and out["instructions_completed"] == 0, out
    assert reg.running is True and mstate.STATE.console_run is True
    _stop_proved_at_next_contact(reg)


def test_a_step_over_whose_over_is_not_answered_in_time_latches_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The answer the `over` is still owed would be read as the next request's, so `stop`,
    which would send one, is not the way out: `close` then `start` is."""
    reg = _console_double(monkeypatch, tmp_path)
    _failing_at(reg, "over")
    out = s.step(count=3, mode="over")
    _latched_on(reg, "over", out)
    assert out["mode"] == "over" and out["instructions_completed"] == 0, out


# ------------------------------------------------ something that is not a stop BREAKS it


def _broken_under_run_to(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    ses = _running(monkeypatch, tmp_path)

    def poll(timeout: float = 0.0) -> bool:
        raise g.SessionError(NOT_A_STOP)

    monkeypatch.setattr(ses, "poll_stop", poll)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["code"] == "session_broken", out
    assert re.search(r"the session broke \d+\.\d s into the run: ", out["message"]), out
    return ses


def test_a_run_to_that_read_something_other_than_a_stop_leaves_the_session_broken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _broken_under_run_to(monkeypatch, tmp_path)
    assert ses.broken == NOT_A_STOP
    out = refused("`close`.*`start`", s.registers())
    assert out["code"] == "session_broken" and NOT_A_STOP in out["message"], out
    assert "RUNNING" not in out["message"], "a broken session is never described as a running one"


def test_status_still_answers_on_a_broken_session_and_carries_the_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _broken_under_run_to(monkeypatch, tmp_path)
    touched: list[str] = []

    def current_pc() -> int:
        touched.append("pc")
        return 0

    monkeypatch.setattr(ses, "current_pc", current_pc)
    ses.running = False        # whatever the flag says: `broken` alone keeps the channel unasked
    out = s.status()
    assert (out["status"] == "ok" and out["session"]["alive"] is True
            and out["broken"] == NOT_A_STOP), out
    assert not touched, "a channel that cannot be trusted is not asked where the machine is"


def test_status_says_a_healthy_session_is_not_broken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    assert "broken" not in s.status()


@pytest.mark.parametrize("packet", ["W00", "X09", "S05", "00*\"00"])
def test_a_shape_the_stub_never_sends_met_by_run_to_leaves_the_session_broken(
    packet: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The packet layer's refusals arrive through the same wait, so they latch like any
    other thing that is not a stop: the real parser reads the wire here, under the double."""
    ses = _running(monkeypatch, tmp_path)
    wire, _ = _wired([packet])
    wire.running = True
    monkeypatch.setattr(ses, "poll_stop", wire.poll_stop)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["code"] == "session_broken", out
    assert ses.broken is not None and "never" in ses.broken, ses.broken
    assert s.registers()["code"] == "session_broken"


# The media file tools read files and never the machine, so a broken session leaves them as it
# leaves `status`: answering; and so does `perform_export`, which writes what the session did,
# a broken one's included.
#: A map's file methods read and write map files only, as the media file tools read theirs; its
#: `add` reads the screen, and is walked below.
MAP_FILE_TOOLS = {"map_write"}
_STILL_ANSWER = {"close", "status", "perform_export", *media_tools.TOOLS, *MAP_FILE_TOOLS}


@pytest.mark.parametrize("name", [t for t in _tools() if t not in _STILL_ANSWER])
def test_every_tool_but_close_and_status_answers_session_broken_on_a_broken_session(
    name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The latch is ONE gate, so this walks the server's own tool list: a tool added later
    that reaches the machine round the gate fails here by name."""
    ses = _running(monkeypatch, tmp_path)
    ses.broken = NOT_A_STOP
    out = getattr(s, name)(**_ARGS.get(name, {}))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", (name, out)
    assert NOT_A_STOP in out["message"] and "RUNNING" not in out["message"], (name, out)


def test_the_walk_over_the_tools_examined_the_ones_that_still_answer() -> None:
    assert set(_tools()) >= _STILL_ANSWER, "the exemptions name tools the server lacks"


@pytest.mark.parametrize("name", sorted(media_tools.TOOLS))
def test_a_media_file_tool_answers_on_a_broken_session(
    name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The exemption above, held: a file tool reads files only, so a latched session leaves its
    answer its own (here, the missing file's refusal), never `session_broken`."""
    ses = _running(monkeypatch, tmp_path)
    ses.broken = NOT_A_STOP
    out = getattr(s, name)(**_ARGS[name])
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", (name, out)
    assert "is not a file" in out["message"], (name, out)


@pytest.mark.parametrize(("method", "args", "code"), [
    ("load", {"path": "/nonexistent/x.scry-map.json"}, "bad_argument"),
    ("save", _ARGS["map_write"], "needs_call"),
    ("add", {"screen": "s", "match": [[0, 0, 1, 1]]}, "session_broken")])
def test_a_map_file_method_answers_on_a_broken_session_and_add_does_not(
    method: str, args: dict[str, Any], code: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.broken = NOT_A_STOP
    out = s.map_write(**{**args, "method": method})
    assert out["status"] == "INVALID" and out["code"] == code, (method, out)


# ------------------------------------------------ the interrupt at the bound not answered


def test_a_run_to_whose_interrupt_at_the_bound_is_not_answered_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "console_run", False)

    def interrupt(timeout: float = 5.0) -> str:
        raise g.Timeout("no answer within 5.0 s")

    monkeypatch.setattr(ses, "interrupt", interrupt)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert "interrupt at the bound" in out["message"] and "RUNNING" in out["message"], out
    assert "cause" not in out, "no stop was read, so the reply names none"
    assert out["target_disarmed"] is True and out["control_hits"] == 0, out
    assert ses.running is True and mstate.STATE.console_run is False
    assert getattr(ses, "broken", None) is None, "an unanswered interrupt is not a broken channel"
    refused("RUNNING", s.registers())


@pytest.mark.parametrize("condition", ["", "d0 == 1"], ids=["plain", "conditioned"])
def test_an_unanswered_interrupt_says_when_the_target_could_not_be_disarmed_either(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, condition: str,
) -> None:
    """A plain target and a conditioned one are armed and removed alike, through the console
    by index, and a removal left unanswered latches either."""
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor

    def interrupt(timeout: float = 5.0) -> str:
        raise g.Timeout("no answer within 5.0 s")

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bpclear"):
            raise _owed(ses, _console(command))
        return str(real(command, timeout))

    monkeypatch.setattr(ses, "interrupt", interrupt)
    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05, condition=condition)
    assert out["code"] == "session_broken" and "`bpclear 0x2` got no answer" in out["message"], out
    assert s.registers()["code"] == "session_broken", "`stop` would read the owed answer"


# ------------------------------------------------ a found stop whose speed cannot be read


def test_a_found_stop_is_published_even_when_its_speed_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    assert s.resume()["session"]["running"] is True
    ses.stops_after_polls = 1

    def asked() -> float:
        raise _owed(ses, _console("time"))

    monkeypatch.setattr(ses, "emulated_seconds", asked)
    out = s.status()
    found = out["stopped_on_its_own"]
    assert found["average_speed"]["available"] is False, found
    assert "`time` got no answer" in found["average_speed"]["why"], found
    assert found["pc"] == "0x000004a0", found
    assert mstate.STATE.run_release is None, "the window is closed, not left for the next stop"
    assert out["broken"] == ses.broken and out["session"]["running"] is False, (
        "the `time` it is owed would be the next request's answer, so the same reply says so")
    assert out["pc"]["available"] is False and out["last_stop"]["pc"] == "0x000004a0", out
    assert "BROKEN" in out["summary"] and "0x000004a0" in out["summary"], out["summary"]


def test_a_tool_whose_first_contact_latches_the_session_reads_nothing_after_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The found stop's `time` ran out inside the gate: the reader behind it would send the
    request that reads that owed answer as its own, so the same call refuses instead."""
    ses = _running(monkeypatch, tmp_path)
    assert s.resume()["session"]["running"] is True
    ses.stops_after_polls = 1
    asked: list[str] = []

    def time_ran_out() -> float:
        asked.append("time")
        raise _owed(ses, _console("time"))

    real = ses.registers

    def registers(*, thread: int) -> dict[str, int]:
        asked.append("g")
        return real(thread=thread)

    monkeypatch.setattr(ses, "emulated_seconds", time_ran_out)
    monkeypatch.setattr(ses, "registers", registers)
    out = s.registers()
    assert out["code"] == "session_broken" and "`time` got no answer" in out["message"], out
    assert "time" in asked and "g" not in asked[asked.index("time"):], (
        "nothing is asked of a session after it broke on the way in", asked)


def test_a_found_console_stop_is_published_even_when_its_speed_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    monkeypatch.setattr(mstate.STATE, "console_run", True)
    monkeypatch.setattr(mstate.STATE, "run_release", {"emulated": 0.0, "wall": 0.0})
    monkeypatch.setattr(running, "frame_at_rest", lambda ses_, reads=3, gap_s=0.1: True)

    def asked() -> float:
        raise _owed(ses, _console("time"))

    monkeypatch.setattr(ses, "emulated_seconds", asked)
    out = s.status()
    found = out["stopped_on_its_own"]
    assert found["average_speed"]["available"] is False, found
    assert "`time` got no answer" in found["average_speed"]["why"], found
    assert found["packet"] == "none: a run the console started", found
    assert out["broken"] == ses.broken, "the reply that found the stop says the session broke"


def test_status_reports_a_latch_its_own_observation_made_and_never_refuses_with_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`status` is where a latch is READ, so the frame read that proves a console run's stop
    running out is its `broken`, answered `ok`, never its refusal."""
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    monkeypatch.setattr(mstate.STATE, "console_run", True)

    def frame(ses_: Any) -> int:
        raise _owed(ses, _console("print frame"))

    monkeypatch.setattr(read, "frame", frame)
    out = s.status()
    assert out["status"] == "ok" and out["session"]["alive"] is True, out
    assert out["broken"] == ses.broken and out["session"]["running"] is False, out
    assert str(ses.broken).startswith("`print frame` got no answer"), ses.broken
    _running(monkeypatch, tmp_path)
    fresh = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(running, "observe_stop", _raising(g.SessionError("not a latch")))
    out = s.status()
    assert out["status"] == "ok" and "not a latch" in str(out["broken"]), out
    assert fresh.broken == out["broken"] and out["session"]["running"] is False, (
        "latched and reported")


def test_a_refusal_a_tool_raises_after_its_own_request_latched_answers_the_latch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A tool that turns a `SessionError` into a refusal of its own (an `expr` watch reads a
    failed evaluation as a bad expression) must not name the ARGUMENT when the request ran
    out: the session latched, and that is the answer."""
    ses = _running(monkeypatch, tmp_path)

    def values(ses_: Any, exprs: list[str]) -> list[int]:
        raise _owed(ses, _console("print beamy"))

    monkeypatch.setattr(read, "print_values", values)
    _answers_the_latch(ses, s.watch_add(ref="beamy", mode="expr"), "print beamy")


def test_a_halt_on_a_latched_session_sends_nothing() -> None:
    """The interrupt that stops a run the console started goes out raw, past `request`, so
    it asks the latch itself: a broken session is sent nothing, a byte included."""
    ses, wire = _wired([])
    ses.broken = "`print frame` got no answer"
    with pytest.raises(g.SessionError, match="asked nothing more"):
        ses.halt()
    assert wire.sent == [], wire.sent


def test_a_step_on_a_latched_session_sends_nothing() -> None:
    """A step sends its `s` past `request` as `halt` sends its 0x03, so it asks the latch
    itself: the contract is the client's, not each caller's gate."""
    ses, wire = _wired([])
    ses.broken = "`print frame` got no answer"
    with pytest.raises(g.SessionError, match="asked nothing more"):
        ses.step()
    assert wire.sent == [], wire.sent


# ------------------------------------------------ what a broken session is never asked


def test_the_session_block_of_a_broken_session_never_says_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _broken_under_run_to(monkeypatch, tmp_path)
    assert ses.running is True, "the double is as `go` left it, which is what makes this bite"
    for out in (s.registers(), s.status()):
        assert out["session"]["running"] is False, out["session"]
        assert out["session"]["broken"] == NOT_A_STOP, out["session"]
    assert s.status()["session"]["running"] is False


def test_a_healthy_session_block_carries_no_broken_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    assert "broken" not in s.status()["session"]


def test_a_refusal_on_a_broken_session_never_surveys_a_stop_it_left_unrecorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stop packet was read and the very next answer was not: the session holds a stop
    its record does not describe, which is what a refusal would otherwise survey as its own."""
    ses = _running(monkeypatch, tmp_path)
    ses.stops_after_polls = 1
    asked: list[str] = []

    def current_pc() -> int:
        asked.append("pc")
        if len(asked) == 1:
            raise g.SessionError(NOT_A_STOP)
        return 0x4A0

    monkeypatch.setattr(ses, "current_pc", current_pc)
    assert s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)["code"] == "session_broken"
    assert ses.running is False and ses.stop_count == 1
    before = dict(mstate.STATE.last_stop)
    assert s.registers()["code"] == "session_broken"
    assert asked == ["pc"] and mstate.STATE.last_stop == before


class _Process:
    """A process that exits only when killed, and says whether it was."""

    pid = 4242

    def __init__(self) -> None:
        self.killed = False

    def poll(self) -> int | None:
        return -9 if self.killed else None

    def wait(self, timeout: float | None = None) -> int:
        if not self.killed:
            raise subprocess.TimeoutExpired("mame", timeout or 0.0)
        return -9

    def kill(self) -> None:
        self.killed = True


def test_close_ends_a_broken_session_without_asking_its_channel_to_quit_or_drain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _broken_under_run_to(monkeypatch, tmp_path)
    proc = _Process()
    monkeypatch.setattr(mstate.STATE, "proc", proc)
    monkeypatch.setattr(mstate.STATE, "cfg", None)
    monkeypatch.setattr(mstate.STATE, "stdout_log", None)
    monkeypatch.setattr(mstate, "QUIT_GRACE_S", 0.0)
    asked: list[str] = []
    monkeypatch.setattr(ses, "quit", lambda: asked.append("quit"), raising=False)
    monkeypatch.setattr(ses, "close", lambda: None, raising=False)

    def drain(ses_: Any, scratch: Path) -> tuple[int, int]:
        asked.append("drain")
        return 0, 0

    monkeypatch.setattr(transport, "drain", drain)
    out = s.close()
    assert out["closed"] is True and out["ended_by"] == "killed" and proc.killed, out
    assert asked == [], "neither the drain nor `quit` has a channel it can believe"


def test_close_sends_a_latched_session_nothing_with_a_line_pending_in_the_pipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The real drain, over the real client on a wire that counts: a pending line is what
    would have it step the machine, and a latched session is sent nothing, a byte included."""
    _running(monkeypatch, tmp_path)
    ses, wire = _wired([])
    ses.broken = "`print frame` got no answer"
    monkeypatch.setattr(wire, "close", lambda: None, raising=False)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "proc", _Process())
    monkeypatch.setattr(mstate.STATE, "cfg", None)
    monkeypatch.setattr(mstate.STATE, "stdout_log", None)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 1)
    assert transport.pending_lines(tmp_path) == 1, "the line a drain would step the machine for"
    out = s.close()
    assert out["closed"] is True and out["ended_by"] == "killed", out
    assert wire.sent == [], wire.sent


# ------------------------------------------------ the later laps, and the other branches


def test_a_gvblank_that_fails_on_a_later_lap_says_how_far_the_counter_got(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    real = reg.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "gvblank" and reg.commands.count("gvblank") == 2:
            raise _owed(reg, _console(command))
        return str(real(command, timeout))

    reg.monitor = monitor
    out = s.run_for(frames=5, seconds=1.0)
    assert out["code"] == "session_broken", out
    assert (out["frame_before"], out["frame_after"]) == (10, 12), out


def test_an_over_that_fails_after_others_landed_says_how_many_did(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    monkeypatch.setattr(advance, "_settled_pc", lambda ses_: True)
    real = reg.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "over" and reg.commands.count("over") == 1:
            raise _owed(reg, _console(command))
        return str(real(command, timeout))

    reg.monitor = monitor
    out = s.step(count=3, mode="over")
    assert out["code"] == "session_broken" and out["instructions_completed"] == 1, out


@pytest.mark.parametrize("release", ["gvblank", "over"])
def test_a_release_too_long_to_send_lets_go_of_nothing(
    release: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Refused BEFORE a byte went out, so the machine is where it was and the flag says so."""
    reg = _console_double(monkeypatch, tmp_path)
    real = reg.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == release:
            raise g.CommandTooLong(14, 8)
        return str(real(command, timeout))

    reg.monitor = monitor
    out = (s.run_for(frames=1, seconds=1.0) if release == "gvblank"
           else s.step(count=1, mode="over"))
    assert out["code"] == "bad_argument", out
    assert reg.running is False and mstate.STATE.console_run is False


def test_a_pass_with_the_watches_disarmed_does_not_re_arm_them_over_a_broken_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)

    def poll(timeout: float = 0.0) -> bool:
        raise g.SessionError(NOT_A_STOP)

    def rearm(ses_: Any, disarmed: list[str]) -> list[str]:
        raise AssertionError("the watches were re-armed over a broken channel")

    monkeypatch.setattr(ses, "poll_stop", poll)
    monkeypatch.setattr(watches, "disarm_for_pass", lambda ses_: [("w1", ":maincpu")])
    monkeypatch.setattr(watches, "rearm_after_pass", rearm)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, disarm_watches=True)
    assert out["code"] == "session_broken", out
    w1 = [{"ref": "w1", "cpu": ":maincpu"}]
    assert out["disarmed_watches"] == w1 and out["not_rearmed"] == w1, out


def test_a_re_arm_that_fails_after_the_pass_latches_and_the_reply_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The run answered and the re-arm then lost the channel: the run's own reply stands, the
    watches it could not re-arm are named, and its `session` block is the one AFTER the latch,
    never the one the run built while the channel still held."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(watches, "disarm_for_pass", lambda ses_: [("w1", ":maincpu")])
    monkeypatch.setattr(watches, "rearm_after_pass",
                        _raising(g.Timeout("no answer to the re-arm")))
    out = s.run_for(frames=1, seconds=1.0, disarm_watches=True)
    w1 = [{"ref": "w1", "cpu": ":maincpu"}]
    assert out["disarmed_watches"] == w1 and out["not_rearmed"] == w1, out
    assert "no answer to the re-arm" in str(getattr(ses, "broken", "")), "the latch is set"
    assert "no answer to the re-arm" in str(out["session"]["broken"]), out["session"]
    assert list(out)[-1] == "session", "the session block stays last"


# ------------------------------------------------ the releases the tools make themselves

RECOVERY = "`stop` recovers it; if `stop` fails as well, `close` then `start` is the way out"
DEAD = "the connection failed: [Errno 54] Connection reset by peer"


def _dead() -> g.SessionError:
    """The error a dead connection raises, of the type the packet layer gives it."""
    return g.ConnectionFailed(DEAD)


def test_the_recovery_clause_is_one_constant() -> None:
    assert vars(running).get("STOP_RECOVERS") == RECOVERY


def _raising(error: g.SessionError) -> Any:
    """A session method that raises `error`, whatever it is called with."""
    def method(*_: Any, **__: Any) -> Any:
        raise error
    return method


def _latched(monkeypatch: pytest.MonkeyPatch, ses: Any, out: dict[str, Any], reason: str) -> None:
    """What every latching refusal owes: the reason on the session, the way out in its own
    words, never a machine called running, the next tool refused, and `close` answering."""
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert reason in out["message"] and "RUNNING" not in out["message"], out["message"]
    assert "`close`" in out["message"] and "`start`" in out["message"], out["message"]
    assert ses.broken == reason and out["session"]["running"] is False, out["session"]
    after = refused("`close`.*`start`", s.registers())
    assert after["code"] == "session_broken" and reason in after["message"], after
    proc = _Process()
    monkeypatch.setattr(mstate.STATE, "proc", proc)
    monkeypatch.setattr(mstate.STATE, "cfg", None)
    monkeypatch.setattr(mstate.STATE, "stdout_log", None)
    monkeypatch.setattr(mstate, "QUIT_GRACE_S", 0.0)
    # An open run window is what `close` would read the speed of, off a channel it must not ask.
    monkeypatch.setattr(mstate.STATE, "run_release", {"emulated": 0.0, "wall": 0.0})
    monkeypatch.setattr(ses, "emulated_seconds",
                        _raising(g.SessionError("the clock of a broken session was asked")))
    closed = s.close()
    assert closed["closed"] is True and proc.killed, closed
    assert "average_speed" not in closed, closed


@pytest.mark.parametrize("reason", [NOT_A_STOP, DEAD], ids=["not_a_stop", "dead"])
def test_a_resume_whose_wait_reads_something_other_than_a_stop_leaves_the_session_broken(
    reason: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "poll_stop", _raising(g.SessionError(reason)))
    out = s.resume(seconds=1.0)
    assert re.search(r"the session broke \d+\.\d s into the wait: ", out.get("message", "")), out
    assert "nothing about the run was measured" in out["message"].lower(), out["message"]
    assert "halted" not in out and "running" not in out, "it never says the machine is running"
    _latched(monkeypatch, ses, out, reason)


@pytest.mark.parametrize("seconds", [0.0, 1.0])
def test_a_resume_whose_release_could_not_be_sent_leaves_the_session_broken(
    seconds: float, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "go", _raising(g.SessionError(DEAD)))
    _latched(monkeypatch, ses, s.resume(seconds=seconds), DEAD)


def _stepping(ses: Any, monkeypatch: pytest.MonkeyPatch, error: g.SessionError,
              good: int) -> None:
    """`good` steps land, then the next one raises `error` with its `s` already out."""
    real = ses.step
    taken: list[int] = []

    def step() -> str:
        if len(taken) == good:
            ses.running = True
            raise error
        taken.append(1)
        return str(real())

    monkeypatch.setattr(ses, "step", step)


@pytest.mark.parametrize("good", [0, 1])
def test_a_step_into_whose_stop_does_not_arrive_in_time_leaves_the_session_saying_running(
    good: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    _stepping(ses, monkeypatch, g.Timeout("no answer within 10.0 s"), good=good)
    out = s.step(count=3)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert out["mode"] == "into" and out["instructions_completed"] == good, out
    assert f"step {good + 1} of 3" in out["message"] and RECOVERY in out["message"], out
    assert ses.running is True and mstate.STATE.console_run is False, "the stub WILL send a stop"
    assert getattr(ses, "broken", None) is None, "a wait that ran out is not a broken channel"
    refused("RUNNING", s.registers())
    recovered = s.stop()
    assert recovered["interrupted"] is True and recovered["session"]["running"] is False, recovered


@pytest.mark.parametrize("reason", [NOT_A_STOP, DEAD], ids=["not_a_stop", "dead"])
def test_a_step_into_that_reads_something_other_than_a_stop_leaves_the_session_broken(
    reason: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    _stepping(ses, monkeypatch, g.SessionError(reason), good=2)
    out = s.step(count=3)
    assert out.get("mode") == "into" and out.get("instructions_completed") == 2, out
    assert "step 3 of 3" in out["message"], out["message"]
    assert "the steps before it landed" in out["message"].lower(), out["message"]
    _latched(monkeypatch, ses, out, reason)


def _released(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, console: bool) -> Any:
    ses = _running(monkeypatch, tmp_path)
    assert s.resume()["session"]["running"] is True
    monkeypatch.setattr(mstate.STATE, "console_run", console)
    if console:
        # The first contact proves a console run's stop on the frame counter: it still moves.
        monkeypatch.setattr(running, "frame_at_rest", lambda ses_, reads=3, gap_s=0.1: False)
    return ses


def test_a_stop_whose_interrupt_is_not_answered_in_time_says_so_and_names_the_way_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _released(monkeypatch, tmp_path, console=False)
    monkeypatch.setattr(ses, "interrupt", _raising(g.Timeout("no answer within 5.0 s")))
    out = s.stop()
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert "no answer within 5.0 s" in out["message"] and RECOVERY in out["message"], out
    assert "RUNNING" in out["message"] and "cause" not in out, out
    assert ses.running is True and getattr(ses, "broken", None) is None


@pytest.mark.parametrize("console", [False, True])
@pytest.mark.parametrize("reason", [NOT_A_STOP, DEAD], ids=["not_a_stop", "dead"])
def test_a_stop_whose_own_release_breaks_leaves_the_session_broken_in_both_branches(
    reason: str, console: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _released(monkeypatch, tmp_path, console)
    monkeypatch.setattr(ses, "halt" if console else "interrupt",
                        _raising(g.SessionError(reason)))
    out = s.stop()
    assert "`stop`" in out.get("message", ""), out
    assert "no stop was read" in out["message"].lower(), out["message"]
    _latched(monkeypatch, ses, out, reason)


def test_a_console_run_that_does_not_come_to_rest_under_stop_names_the_way_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _released(monkeypatch, tmp_path, console=True)
    monkeypatch.setattr(ses, "halt", lambda: None)
    monkeypatch.setattr(ses, "_receive", _raising(g.Timeout("nothing came")), raising=False)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.0)
    out = s.stop()
    assert out["code"] == "not_settled" and "frame counter still moves" in out["message"], out
    assert RECOVERY in out["message"], out["message"]
    assert ses.running is True and getattr(ses, "broken", None) is None


# ------------------------------------------------ the interrupt at the bound answered LATE


def _bound_unanswered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, late: bool,
                      control_fires: bool = True, removal_fails: bool = False,
                      unanswered_by: g.SessionError | None = None) -> Any:
    """A `run_to` whose interrupt at the bound times out; with `late`, the stop packet lands
    while the target's removal is asked, as `request` notes one on the way to its answer,
    whether the removal goes through the stub or, for a conditional target, the console."""
    unanswered_by = unanswered_by or g.Timeout("no answer within 5.0 s")
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x25A4]
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    real_go, real_monitor = ses.go, ses.monitor

    def go() -> None:
        real_go()
        if control_fires:
            ses.temps[0] = ses.temps.get(0, 0) + 1   # the control counted once meanwhile

    def removing() -> None:
        if late:
            ses._stop()
        if removal_fails:
            raise _owed(ses, "bpclear 0x2")

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bpclear"):
            removing()
        return str(real_monitor(command, timeout))

    monkeypatch.setattr(ses, "go", go)
    monkeypatch.setattr(ses, "monitor", monitor)
    monkeypatch.setattr(ses, "interrupt", _raising(unanswered_by))
    return ses


def test_a_stop_that_arrives_late_under_an_unanswered_interrupt_is_the_ordinary_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _bound_unanswered(monkeypatch, tmp_path, late=True)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert out["cause"] == "interrupt at the bound, answered late", out
    assert out["control_hits"] == 1 and out["pc"] == "0x000025a4", out
    assert out["target_disarmed"] is True, out
    assert ses.running is False and out["session"]["running"] is False
    assert s.registers()["status"] == "ok", "the machine is stopped and the readers serve"


def test_a_late_stop_under_a_conditional_target_is_the_ordinary_timeout_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _bound_unanswered(monkeypatch, tmp_path, late=True)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05, condition="d0 == 1")
    assert out["verdict"] == "TIMEOUT" and out["condition"], out
    assert out["cause"] == "interrupt at the bound, answered late" and ses.running is False, out


def test_a_late_stop_over_a_silent_control_is_still_said_to_have_come_late(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _bound_unanswered(monkeypatch, tmp_path, late=True, control_fires=False)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "INVALID" and out["code"] == "control_silent", out
    assert out["cause"] == "interrupt at the bound, answered late", out
    assert out["target_disarmed"] is True, out


def test_a_late_stop_whose_removal_is_not_answered_in_time_latches_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stop landed and the removal's own answer did not: that answer is still owed, so
    the survey the TIMEOUT would carry is a request that would read it as its own."""
    ses = _bound_unanswered(monkeypatch, tmp_path, late=True, removal_fails=True)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["code"] == "session_broken" and "verdict" not in out, out
    assert ses.broken is not None and "`bpclear 0x2`" in ses.broken, ses.broken


@pytest.mark.parametrize("reason", [NOT_A_STOP, DEAD], ids=["not_a_stop", "dead"])
def test_an_interrupt_at_the_bound_that_breaks_leaves_the_session_broken_as_stops_own_does(
    reason: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _bound_unanswered(monkeypatch, tmp_path, late=False,
                            unanswered_by=g.SessionError(reason))
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out.get("control_hits") == 0, out
    assert "Nothing about 0x4a0 was measured" in out["message"], out["message"]
    _latched(monkeypatch, ses, out, reason)


def test_an_interrupt_still_unanswered_after_the_removal_names_the_way_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _bound_unanswered(monkeypatch, tmp_path, late=False)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["code"] == "not_settled" and out["target_disarmed"] is True, out
    assert RECOVERY in out["message"] and "RUNNING" in out["message"], out["message"]
    assert ses.running is True


# ------------------------------------------------ the recovery clause, wherever it is said


def test_a_console_release_that_fails_names_the_way_out_when_stop_fails_as_well(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    _failing_at(reg, "gvblank", error=REFUSED_GVBLANK)
    out = s.run_for(frames=2, seconds=1.0)
    assert f"Either way, {RECOVERY}" in out["message"], out["message"]


def test_a_step_over_still_moving_after_its_interrupt_names_the_way_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    monkeypatch.setattr(advance, "_settled_pc", lambda ses_: False)
    monkeypatch.setattr(reg, "_receive", _raising(g.Timeout("nothing came")), raising=False)
    out = s.step(count=1, mode="over")
    assert out["code"] == "not_settled" and reg.running is True, out
    assert RECOVERY in out["message"] and "step over 1 of 1: " in out["message"], out["message"]
    assert out["mode"] == "over" and out["instructions_completed"] == 0, out


# ------------------------------------------------ `close` may not fail on decoration


def test_close_still_answers_when_the_speed_of_the_run_it_ends_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    assert s.resume()["session"]["running"] is True
    assert mstate.STATE.run_release is not None, "the window `close` reads is open"
    proc = _Process()
    monkeypatch.setattr(mstate.STATE, "proc", proc)
    monkeypatch.setattr(mstate.STATE, "cfg", None)
    monkeypatch.setattr(mstate.STATE, "stdout_log", None)
    monkeypatch.setattr(mstate, "QUIT_GRACE_S", 0.0)
    monkeypatch.setattr(transport, "drain", lambda ses_, scratch: (0, 0))
    monkeypatch.setattr(ses, "emulated_seconds", _raising(g.SessionError(DEAD)))
    out = s.close()
    assert out["status"] == "ok" and out["closed"] is True, out
    assert "ended_by" in out and "exit_code" in out, out
    assert out["average_speed"] == {"available": False, "why": DEAD}, out
    assert list(out)[-1] == "session"


# ------------------------------------------------ what the server publishes about all this


def _prose(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


_PACKAGE = Path(__file__).resolve().parent.parent
WAY_OUT = "if `stop` fails as well, `close` then `start`"


@pytest.mark.parametrize("tool", ["resume", "stop"])
def test_a_stop_read_and_then_a_survey_that_breaks_leaves_the_session_broken(
    tool: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stop packet was read and the very next exchange was not: the same place `run_to`
    latches, reached through `resume` and through `stop`."""
    ses = _running(monkeypatch, tmp_path)
    if tool == "resume":
        ses.stops_after_polls = 1
    else:
        assert s.resume()["session"]["running"] is True
        monkeypatch.setattr(mstate.STATE, "console_run", False)
    monkeypatch.setattr(ses, "current_pc", _raising(_dead()))
    out = s.resume(seconds=1.0) if tool == "resume" else s.stop()
    assert "after the stop was read" in out.get("message", ""), out
    assert "the stop was not surveyed" in out["message"].lower(), out["message"]
    _latched(monkeypatch, ses, out, DEAD)


def test_a_step_over_whose_connection_failed_leaves_the_session_broken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    for failing in ("over", "print curpc,frame"):
        reg = _console_double(monkeypatch, tmp_path)
        reg.broken = None
        real = reg.monitor

        def monitor(command: str, timeout: float = 10.0, failing: str = failing,
                    real: Any = real) -> str:
            if command == failing:
                raise _dead()
            return str(real(command, timeout))

        monkeypatch.setattr(reg, "monitor", monitor)
        monkeypatch.setattr(reg, "_receive", _raising(g.Timeout("nothing came")), raising=False)
        out = s.step(count=2, mode="over")
        assert out.get("code") == "session_broken", (failing, out)
        assert out["mode"] == "over" and out["instructions_completed"] == 0, (failing, out)
        assert "the session broke at step over 1 of 2: " in out["message"], (failing, out)
        assert "whether it landed was not seen" in out["message"].lower(), (failing, out)
        assert reg.broken == DEAD and "RUNNING" not in out["message"], (failing, out)


def test_a_console_that_cannot_answer_a_counter_is_not_a_broken_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A refusal is an answer: the channel kept its place, so a step over that cannot read
    its counters bails out as `not_settled` and latches nothing."""
    reg = _console_double(monkeypatch, tmp_path)
    reg.broken = None
    real = reg.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "print curpc,frame":
            raise g.SessionError("the stub refused `qRcmd`: E01")
        return str(real(command, timeout))

    monkeypatch.setattr(reg, "monitor", monitor)
    monkeypatch.setattr(reg, "_receive", _raising(g.Timeout("nothing came")), raising=False)
    out = s.step(count=1, mode="over")
    assert out["code"] == "not_settled" and reg.broken is None, out


def test_a_run_for_that_bails_out_names_the_way_out_in_both_of_its_own_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    reg.emulating = True
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.0)
    monkeypatch.setattr(reg, "halt", lambda: None)
    monkeypatch.setattr(reg, "_receive", _raising(g.Timeout("nothing came")), raising=False)
    reg.stop_after = None
    by_time = s.run_for(milliseconds=100, seconds=0.05)
    assert by_time["code"] == "not_settled" and RECOVERY in by_time["message"], by_time
    assert f"still moved ([{by_time['frame_after']}])" in by_time["message"], by_time
    reg = _console_double(monkeypatch, tmp_path)
    monkeypatch.setattr(mprogress, "Ticker", _expired_ticker())
    by_frames = s.run_for(frames=2, seconds=1.0)
    assert by_frames["code"] == "not_settled" and RECOVERY in by_frames["message"], by_frames


def _expired_ticker() -> Any:
    class _Expired(mprogress.Ticker):
        def expired(self) -> bool:
            return True
    return _Expired


def test_the_descriptions_say_what_each_changed_reply_carries() -> None:
    assert "answered late" in documented("run_to")
    assert "`mode` and `instructions_completed`" in documented("step")
    assert "An `into` that reads anything else in a stop's place" in documented("step")
    assert ("a failed connection, or an `over` the console did not answer in time is "
            "`session_broken` and LATCHES") in documented("step")
    assert "`available: false`" in documented("close")


def test_the_instructions_and_the_reference_say_any_tool_latches() -> None:
    """A session error no tool answered latches wherever it surfaces (`mame_mcp.tool`
    wrapper), so the contract names no short list of tools that latch: such a list reads as
    "the others never do", which is false."""
    latching = "`session_broken` LATCHES until `close`"
    for where, text in (("instructions", " ".join((s.mcp.instructions or "").split())),
                        ("REFERENCE.md", _prose(_PACKAGE / "REFERENCE.md"))):
        assert latching in text, f"{where} does not say a broken session latches"
        assert "`run_to`, `resume`, `step` or `stop`" not in text, f"{where} names a short list"
        assert WAY_OUT in text, f"{where} names `stop` as the recovery and no way out past it"
    assert "`session_broken` from `run_to` LATCHES" not in (s.mcp.instructions or "")


# ------------------------------------------------ what a bail-out of the advance family carries


def test_a_landing_that_fails_after_one_reading_answers_the_counter_it_did_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    real = reg.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "print frame" and reg.commands.count("print frame") == 1:
            raise _owed(reg, _console(command))
        return str(real(command, timeout))

    reg.monitor = monitor
    out = s.run_for(frames=2, seconds=1.0)
    assert out["code"] == "session_broken", out
    assert (out["frame_before"], out["frame_after"]) == (10, 11), out


@pytest.mark.parametrize("halt_raises", [False, True])
def test_a_step_over_listens_no_longer_than_the_drain_and_a_halt_that_fails_is_not_the_news(
    halt_raises: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    monkeypatch.setattr(advance, "_settled_pc", lambda ses_: False)
    if halt_raises:
        monkeypatch.setattr(reg, "halt", _raising(g.SessionError("the stub refused")))
    out = s.step(count=1, mode="over")
    assert out["code"] == "not_settled" and reg.running is True, out
    assert reg.received == [g.STOP_REPLY_DRAIN_S] * 2, "after the `over`, after the halt"


def test_a_run_by_frames_looks_for_a_typed_breakpoint_in_the_consoles_own_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """By the name MAME writes it under: a scratch on a filesystem that folds case would
    open it under any spelling, and one that does not would find nothing, in silence."""
    _console_double(monkeypatch, tmp_path)
    looked: list[Path] = []
    real = files.lines_since

    def lines_since(path: Path, mark: int) -> tuple[list[str], int]:
        looked.append(path)
        return real(path, mark)

    monkeypatch.setattr(files, "lines_since", lines_since)
    assert s.run_for(frames=1, seconds=1.0)["verdict"] == "ELAPSED"
    spelled = [path.name for path in looked if path.name.lower() == "debug.log"]
    assert len(spelled) > 1 and set(spelled) == {"debug.log"}, looked


@pytest.mark.parametrize("by", [{"frames": 1}, {"milliseconds": 10}])
def test_a_run_for_holds_the_watches_for_the_pass_on_the_session_it_was_given(
    by: dict[str, int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    held: list[Any] = []

    def disarm(ses_: Any) -> list[tuple[str, str | None]]:
        held.append(ses_)
        return [("w1", ":maincpu")]

    monkeypatch.setattr(watches, "disarm_for_pass", disarm)
    monkeypatch.setattr(watches, "rearm_after_pass", lambda ses_, disarmed: list(disarmed))
    out = s.run_for(seconds=1.0, disarm_watches=True, **by)
    assert out["status"] == "ok", out
    assert out["disarmed_watches"] == [{"ref": "w1", "cpu": ":maincpu"}], out
    assert held == [reg] and "disarmed_watches" not in s.run_for(seconds=1.0, **by)


def test_the_bodies_judge_their_own_arguments_whoever_calls_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    with pytest.raises(mstate.Invalid, match="seconds=0 is not a bound"):
        advance.run_for(reg, tmp_path, 10, seconds=0)
    with pytest.raises(mstate.Invalid, match="a comma or a newline"):
        advance.run_to(reg, tmp_path, "4a0", "", 1.0, condition="d0==1,d1")
    with pytest.raises(mstate.Invalid, match="mode is one of"):
        advance.step(reg, tmp_path, 1, "out")
    assert reg.commands == [], "nothing reached the console"
    with pytest.raises(mstate.Invalid, match="run_to needs a ref"):
        advance.check_run_to()
    with pytest.raises(mstate.Invalid, match="run_to needs a ref"):
        advance.check_run_to(ref="   ")


# ------------------------------------------------ the call whose own request ran out answers it


def _answers_the_latch(ses: Any, out: dict[str, Any], packet: str) -> None:
    """The latch's refusal, on the call that made it: the reason is the request that ran out,
    nothing says RUNNING or sends the caller to `stop`, and the next call is refused too."""
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert f"`{packet}` got no answer" in out["message"], out["message"]
    assert "RUNNING" not in out["message"] and "`close`" in out["message"], out["message"]
    assert out["session"]["running"] is False, out["session"]
    assert ses.broken.startswith(f"`{packet}` got no answer"), "the first cause stays the reason"
    assert s.registers()["code"] == "session_broken"


def test_a_run_by_time_whose_counter_read_runs_out_answers_the_latch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The counter's read after `gtime` ran out: the interrupt and the settle loop behind it
    would ask a channel that can no longer be paired, so the call answers the latch."""
    reg = _console_double(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", reg)   # the live session the wrapper reads
    real = reg.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "print frame" and any(c.startswith("gtime") for c in reg.commands):
            reg.commands.append(command)
            raise _owed(reg, _console(command))
        return str(real(command, timeout))

    reg.monitor = monitor
    _answers_the_latch(reg, s.run_for(milliseconds=100, seconds=1.0), "print frame")


def test_a_step_over_whose_rest_read_runs_out_answers_the_latch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reg = _console_double(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", reg)   # the live session the wrapper reads
    _failing_at(reg, "print curpc,frame", after="over")
    out = s.step(count=2, mode="over")
    _answers_the_latch(reg, out, "print curpc,frame")
    assert out["mode"] == "over" and out["instructions_completed"] == 0, out


def test_a_stop_of_a_console_run_whose_counter_read_runs_out_answers_the_latch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The run was still moving when `stop` came in, and the counter read AFTER the interrupt
    ran out: `stop`'s own settle loop would otherwise read a latched channel as a machine that
    never comes to rest, and answer RUNNING with `stop` as the way out."""
    reg = _console_double(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", reg)   # the live session the wrapper reads
    reg.running, reg.emulating, reg.stop_after = True, True, None   # it never stops by itself
    monkeypatch.setattr(mstate.STATE, "console_run", True)
    real = reg.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "print frame" and reg.interrupted:
            reg.commands.append(command)
            raise _owed(reg, _console(command))
        return str(real(command, timeout))

    reg.monitor = monitor
    _answers_the_latch(reg, s.stop(), "print frame")


def _target_reached_then(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                         removal: Any) -> Any:
    """A `run_to` whose run reaches the target 0x4a0 with the control counted once, and whose
    removal of the target (`bpclear <index>`) first runs `removal(double, command)`, which
    raises what the case needs or answers in the removal's place."""
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x4A0]
    ses.stops_after_polls = 1
    real_go, real_monitor = ses.go, ses.monitor

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 1

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bpclear"):
            answered = removal(ses, command)
            if answered is not None:
                return str(answered)
        return str(real_monitor(command, timeout))

    monkeypatch.setattr(ses, "go", go)
    monkeypatch.setattr(ses, "monitor", monitor)
    return ses


def test_a_run_to_whose_target_removal_runs_out_answers_the_latch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The target was reached; its removal's own request ran out: the survey that would follow
    reads what that removal is still owed."""
    def owed(ses: Any, command: str) -> None:
        raise _owed(ses, _console(command))

    ses = _target_reached_then(monkeypatch, tmp_path, owed)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    _answers_the_latch(ses, out, "bpclear 0x2")
    assert "into the run" in out["message"] and out["control_hits"] == 0, (
        "the same cause answers the same way whichever path the removal was on", out)


def test_a_reached_target_whose_removal_the_list_does_not_confirm_is_still_the_measured_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A removal the console answers without making (the row still listed) is an answer, so
    the channel kept its place and the stop the run reached is still a measurement: the
    ordinary reply, saying the target may still be armed and how to remove it. The row the
    console still lists at the target, with the console's own `Stopped at breakpoint` line for
    it, is the run's own and not one typed through `debug`."""
    held: list[int] = []

    def refusal(ses: Any, command: str) -> str:
        held.append(int(command.split()[1], 16))
        (tmp_path / "debug.log").open("a").write(f"Stopped at breakpoint {held[0]:X}\n4A0\n")
        return captured("bpclear.invalid.txt")         # an answer, and the row stays

    ses = _target_reached_then(monkeypatch, tmp_path, refusal)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "ok" and out["verdict"] == "TARGET", out
    assert out["cause"] == "target 0x4a0", out["cause"]
    assert out["target_disarmed"] is False and "may still be armed" in out["note"], out
    assert f'`debug("bpclear {held[0]:#x}")`' in out["note"], out["note"]
    assert getattr(ses, "broken", None) is None, "a refusal latches nothing"


def test_a_removal_whose_list_cannot_be_read_back_is_not_called_confirmed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The removal is read back off `bplist`; an answer of no known shape there confirms
    nothing, so the reply says the target may still be armed, and nothing latches."""
    cleared: list[str] = []
    real_held = mlists.bp_held

    def held(ses: Any, cpu: str | None = None) -> Any:
        if cleared:
            raise mstate.Invalid("unexpected_answer", "bplist answered in no known shape")
        return real_held(ses, cpu)

    monkeypatch.setattr(mlists, "bp_held", held)
    ses = _target_reached_then(monkeypatch, tmp_path, lambda ses, command: cleared.append(command))
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert cleared and out["status"] == "ok" and out["verdict"] == "TARGET", out
    assert out["target_disarmed"] is False and "may still be armed" in out["note"], out
    assert getattr(ses, "broken", None) is None


def test_a_reached_target_whose_removal_loses_the_connection_breaks_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Only a refusal keeps the channel: a connection gone under the removal answers nothing
    any more, so the run is `session_broken`, latched, and nothing is surveyed over it."""
    gone = g._connection_failed(ConnectionResetError(54, "Connection reset by peer"))

    def lost(_ses: Any, command: str) -> None:
        raise gone

    ses = _target_reached_then(monkeypatch, tmp_path, lost)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["code"] == "session_broken" and "reset by peer" in out["message"], out
    assert ses.broken is not None and s.registers()["code"] == "session_broken"


def test_any_tool_whose_own_request_runs_out_answers_the_latch_and_nothing_else_is_translated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The latch is the state, whichever tool's request made it; a session error on a session
    that did NOT latch yet means the two ends may no longer agree where a packet starts, so
    it latches where it surfaces and answers `session_broken`, never an execution failure."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "registers", _raising(_owed(ses, "g")))
    _answers_the_latch(ses, s.registers(), "g")
    fresh = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(fresh, "registers", _raising(g.SessionError("not a latch")))
    out = s.registers()
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert fresh.broken == "not a latch", "latched where it surfaced"


@pytest.mark.parametrize(("error", "code"), [
    (g.Refused("the stub refused `m400,10`: E01"), "readback_refused"),
    (g.Unsupported("the stub does not support `m400,10`"), "no_channel"),
    (g.ConnectionFailed("the stub closed the connection"), "session_broken"),
    (g.UnknownByteOrder("no established byte order for this architecture"), "no_channel"),
    (g.Mismatch("the ROM on disk and the machine disagree"), "readback_refused"),
])
def test_a_session_error_no_tool_caught_is_answered_by_its_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: g.SessionError, code: str,
) -> None:
    """The stub's `no` keeps the channel paired, so it is a refusal and nothing latches; a
    connection that failed latches. None of them escapes as an execution failure."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "read", _raising(error))
    out = s.read_memory(ref="0x400", length=16)
    assert out["status"] == "INVALID" and out["code"] == code, out
    assert out["session"] and list(out)[-1] == "session", "the envelope, session last"
    assert (getattr(ses, "broken", None) is not None) == (code == "session_broken")


def test_a_session_error_with_no_session_left_to_latch_says_start_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A session already gone (a failed `start` kills its own) has nothing to latch: the
    reply is still `session_broken`, and it points at `start`, not at a `close` of nothing."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "read", _raising(g.ConnectionFailed("the stub closed it")))
    monkeypatch.setattr(mstate.STATE, "ses", None)
    out = s.read_memory(ref="0x400", length=16)
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert out["message"].endswith("`start` a new one") and "`close`" not in out["message"], out
    assert getattr(ses, "broken", None) is None, "nothing latched on a session not held"


def test_a_removal_the_list_does_not_confirm_after_an_unanswered_interrupt_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A removal the console answers without making is an answer, so the channel kept its
    place: the machine may still run, `stop` is the way back, and `target_disarmed` says the
    target may still be armed; nothing latches."""
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        return (captured("bpclear.invalid.txt") if command.startswith("bpclear")
                else str(real(command, timeout)))

    monkeypatch.setattr(ses, "interrupt", _raising(g.Timeout("no answer within 5.0 s")))
    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["code"] == "not_settled" and out["target_disarmed"] is False, out
    assert getattr(ses, "broken", None) is None and RECOVERY in out["message"], out


def test_a_session_that_already_latched_keeps_the_reason_that_latched_it() -> None:
    """What fails after the latch is its consequence (a refusal quoting it), so the reason a
    later refusal quotes stays the first cause, never a refusal nested in a refusal."""
    ses, _wire = _wired([])
    ses.broken = "`p11` got no answer within 0.2 s"
    out = running.session_broke(ses, g.SessionError("asked nothing more: `p11` ..."), "later",
                                "Nothing read")
    assert ses.broken == "`p11` got no answer within 0.2 s" and out["code"] == "session_broken"


# ------------------------------------------------ a write whose read-back fails


def _read_back_failing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                       fail: Any) -> tuple[Any, dict[str, Any]]:
    """A `write` whose read-back raises what `fail(double)` returns, after the bytes went out."""
    ses = _running(monkeypatch, tmp_path)

    def read_back(addr: int, n: int, *, thread: int) -> bytes:
        raise fail(ses)

    monkeypatch.setattr(ses, "read", read_back)
    return ses, s.write(ref="0x200000", data_hex="00")


def test_a_write_whose_read_back_is_refused_says_so_and_latches_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A refusal is an answer: the channel kept its place, so the reply names what was
    written and the next call is served."""
    def refusal(_ses: Any) -> g.SessionError:
        wire, _ = _wired(["E01"])
        try:
            wire.read(0x200000, 1, thread=1)
        except g.SessionError as e:
            return e
        raise AssertionError("`m` answered E01 must be refused")

    ses, out = _read_back_failing(monkeypatch, tmp_path, refusal)
    assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert out["addr"] == "0x00200000" and out["bytes_written"] == 1, out
    assert "E01" in out["message"] and "readback" not in out, out
    assert getattr(ses, "broken", None) is None, "a refusal latches nothing"
    assert s.registers()["status"] == "ok", "the next call is served"


def test_a_write_whose_read_back_runs_out_answers_the_latch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses, out = _read_back_failing(monkeypatch, tmp_path, lambda d: _owed(d, "m200000,1"))
    _answers_the_latch(ses, out, "m200000,1")
    assert out["addr"] == "0x00200000" and out["bytes_written"] == 1, out


def test_a_write_whose_connection_goes_under_the_read_back_latches_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A connection that is gone answers nothing any more, `stop` included: it latches as
    every other `session_broken` does."""
    gone = g._connection_failed(ConnectionResetError(54, "Connection reset by peer"))
    ses, out = _read_back_failing(monkeypatch, tmp_path, lambda _d: gone)
    assert out["code"] == "session_broken" and "reset by peer" in out["message"], out
    assert ses.broken is not None and s.registers()["code"] == "session_broken"


def test_a_write_whose_read_back_gets_an_answer_out_of_place_latches_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Only a refusal keeps the channel: an answer that is not the read's (here a stop shape
    the stub never sends) leaves nothing to pair a reply with, so it latches."""
    ses, out = _read_back_failing(monkeypatch, tmp_path,
                                  lambda _d: g.SessionError(NOT_A_STOP))
    assert out["code"] == "session_broken" and ses.broken is not None, out


def test_a_silent_control_whose_target_removal_is_not_confirmed_says_both_in_one_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A run cut at its bound with the control cold is `control_silent`; a target removal the
    console answers without making leaves the row armed. Both are notes of one reply, so they
    are said together: the reply carries one `note` holding both."""
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034]
    ses.stops_after_polls = 10**6
    real_monitor = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bpclear"):
            return captured("bpclear.invalid.txt")      # an answer, and the row stays
        return str(real_monitor(command, timeout))

    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "INVALID" and out["code"] == "control_silent", out
    assert out["target_disarmed"] is False, out
    assert "never fired" in out["message"] and "may still be armed" in out["note"], out
    assert out["note"].startswith(f"{advance.CONTROL_HINT}; the temporary breakpoint at 0x4a0 "
                                  "may still be armed"), ("both, the hint first, one `; `", out)


def test_a_stop_found_on_a_console_that_marks_no_cpu_says_so(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A console with no `cpulist` marks no visible cpu: the stop a contact found carries that
    as unavailable, as every other stop reply does, never a null."""
    seen: dict[str, Any] = {"pc": "0x00000400", "cpu": None, "frame": 3, "regs": {}}
    monkeypatch.setattr(running, "survey", lambda ses, scratch: dict(seen))
    monkeypatch.setattr(running, "attribute", lambda pc, cpu: "breakpoint")
    monkeypatch.setattr(running, "run_speed", lambda ses: {})
    monkeypatch.setattr(running, "_remember", lambda ses, seen, how: (
        {"seq": 2, "pc": seen["pc"], "cpu": seen["cpu"], "frame": seen["frame"], "cause": how,
         "packet": "S05"}, how))
    running._found(cast(g.Session, object()), tmp_path, None)
    found = mstate.STATE.found_stop_last
    assert found is not None and found["cpu"]["available"] is False, found
