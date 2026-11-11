"""The gate of a screen wait on a declared stop, run by the host's `lua` over a fake machine,
and the refusals made before it is installed."""
from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scry_core import reply_schema, stop_wait
from session_doubles import run_host_lua

from scry_mame import advance, arming, at_stop, chunk, cpus, read, running
from scry_mame import declarations as dec
from scry_mame import gdb_session as gs
from scry_mame import state as st

# A machine of the gate's own shape: stops are `periodic` calls with the debugger at `stop`,
# a frame's end is `frame_done`. `stop_at(pc)` parks the machine at a new instant; `run()` lets it
# go, which the gate sees at the next periodic; `frame(px)` ends a frame showing `px`.
FAKE = """
local PERIODIC, FRAME = {}, {}
emu = {register_periodic = function(f) PERIODIC[#PERIODIC + 1] = f end,
       register_frame_done = function(f) FRAME[#FRAME + 1] = f end}
local now, PX = 0, "first"
local mem = {}
local regs = {CURPC = {value = 0}, D0 = {value = 0}}
local cpu = {tag = ":maincpu", state = regs, spaces = {program = {
  read_u8 = function(self, a) return mem[a] or 0 end,
  read_u16 = function(self, a) return mem[a] or 0 end}}}
local scr = {scan_period = 1, frame_period = 262, pixel_period = 0.001,
             time_until_pos = function(self, y, x) return 262 - (now %% 262) end,
             pixels = function(self) return PX end}
manager = {machine = {devices = {[":maincpu"] = cpu}, screens = {[":screen"] = scr},
  debugger = {execution_state = "stop", consolelog = {}},
  time = {as_double = function(self) return now end}}}
local dbg = manager.machine.debugger
function hooks() for _, f in ipairs(PERIODIC) do f() end end
function stop_at(pc) now = now + 1 regs.CURPC.value = pc dbg.execution_state = "stop" hooks() end
function run() dbg.execution_state = "run" hooks() end
function frame(px) PX = px now = now + 1 for _, f in ipairs(FRAME) do f() end
  if dbg.execution_state == "stop" then stop_at(0x9999) end end
function poke(a, v) mem[a] = v end
function logged(line) table.insert(dbg.consolelog, line) end
function setreg(n, v) regs[n].value = v end
function state() local f = io.open(%(state)s) local s = f:read("l") f:close() print(s) end
function go(n) local f = io.open(%(ctl)s, "w") f:write("go " .. (n or 1) .. "\\n") f:close() end
function release(n) go(n) run() end
function tell_off() local f = io.open(%(ctl)s, "w") f:write("off\\n") f:close() end
"""

PC = 0x1234


def gate_run(tmp_path: Path, kind: str, script: str, condition: str = "") -> list[str]:
    spec = stop_wait.check(f"0x{PC:x}" if kind == "breakpoint" else "",
                           "level" if kind == "watch" else "", 0, condition)
    assert spec is not None
    decl = dec.Declaration(kind, "address" if kind == "breakpoint" else "symbol", spec.ref,
                           watch_mode="change" if kind == "watch" else None,
                           width=1 if kind == "watch" else None,
                           fmt="u8" if kind == "watch" else None, cpu=":maincpu")
    addr = PC if kind == "breakpoint" else 0x40
    state, control = at_stop.files_of(tmp_path, 1)
    quoted = {"state": repr(str(state)), "ctl": repr(str(control))}
    # The console's reader steps the machine once after the install, before the server's `go`.
    chunk = (FAKE % quoted + at_stop.gate(state, control, spec, decl, addr, ":maincpu",
                                          lambda ref: 0x50) + " stop_at(0x4444) go() " + script)
    return run_host_lua(chunk, tmp_path)


def fields(line: str) -> dict[str, str]:
    return dict(part.split("=") for part in line.split())


def test_a_firing_judges_the_frame_and_stops_on_a_picture_never_rejected(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint", "stop_at(0x1234) state() frame('menu') state()")
    first, second = map(fields, out)
    assert first["outcome"] == "installed" or first["firings"] == "1"
    assert second["outcome"] == "candidate" and second["firings"] == "1"
    assert second["examined"] == "1"


def test_a_rejected_picture_does_not_stop_the_machine_again(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint", """
        stop_at(0x1234) frame('title') state()
        release(2) stop_at(0x1234) frame('title') frame('title') state()""")
    assert fields(out[0])["outcome"] == "candidate"
    after = fields(out[1])
    assert after["seq"] == fields(out[0])["seq"] and after["outcome"] == "candidate"


def test_the_window_spans_two_frames_and_closes(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint", """
        stop_at(0x1234) frame('first') state() release(2)
        frame('late') state() release(3)
        frame('later') state()""")
    assert fields(out[0])["outcome"] == "candidate" and fields(out[0])["examined"] == "1"
    # the picture rejected at the first notifier does not close the window: the second is judged
    assert fields(out[1])["outcome"] == "candidate" and fields(out[1])["examined"] == "2"
    assert fields(out[2])["seq"] == fields(out[1])["seq"]


def test_the_stop_parked_at_before_the_go_is_not_judged_after_it(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint", "hooks() state()")
    assert fields(out[0])["outcome"] == "installed"


def test_the_servers_reader_steps_at_a_held_stop_are_not_reported(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint", """
        stop_at(0x1234) frame('menu') state() stop_at(0x5555) frame('redraw') stop_at(0x5556)
        state() release(2) stop_at(0x1234) frame('menu') frame('menu') state()""")
    assert fields(out[0])["seq"] == fields(out[1])["seq"]
    # what was held and rejected is the picture judged, never one drawn while it was held
    assert fields(out[2])["seq"] == fields(out[1])["seq"]


def test_a_firing_whose_condition_fails_opens_no_window(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint",
                   "setreg('D0', 2) stop_at(0x1234) frame('menu') state()", condition="d0==3")
    got = fields(out[0])
    assert got["outcome"] == "installed" and got["seq"] == "1"
    again = tmp_path / "again"
    again.mkdir()
    out = gate_run(again, "breakpoint",
                   "setreg('D0', 3) stop_at(0x1234) frame('menu') state()", condition="d0==3")
    assert fields(out[0])["outcome"] == "candidate"


def test_a_register_the_cpu_lacks_installs_nothing_and_says_so(tmp_path: Path) -> None:
    # the gate's `return` ends the chunk, the script after it included
    out = gate_run(tmp_path, "breakpoint", "print('ran on')", condition="zz==1")
    assert out == []
    state = at_stop.read_state(at_stop.files_of(tmp_path, 1)[0])
    assert state is not None and state["outcome"] == "noregister"


def test_the_loop_refuses_a_register_the_gate_did_not_find(loop: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(ses, scratch, script, seconds, progress, what):  # type: ignore[no-untyped-def]
        at_stop.files_of(scratch, 1)[0].write_text(
            "seq=1 outcome=noregister firings=0 examined=0 line=-1 pc=0\n")
        return "", {}
    monkeypatch.setattr(chunk, "run", missing)
    spec = stop_wait.check("0x1234", "", 0, "zz==1")
    assert spec is not None
    with pytest.raises(st.Invalid) as e:
        at_stop.screen_wait_at(Ses(at_stop.files_of(loop, 1)[0], []), loop, spec, "",  # type: ignore[arg-type]
                               lambda: None, "screen", "x", 1.0, lambda *a: None, lambda r: 0)
    assert e.value.code == "bad_argument" and "ZZ" in str(e.value)


def test_a_stop_the_gate_did_not_make_is_left_for_the_server(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint", "stop_at(0x2000) state()")
    got = fields(out[0])
    assert got["outcome"] == "other" and got["firings"] == "0" and got["pc"] == "2000"


def test_a_watch_fires_when_its_bytes_change_and_not_otherwise(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "watch", """
        frame('a') stop_at(0x700) state() release(2)
        poke(0x40, 5) stop_at(0x700) frame('b') state()""")
    assert fields(out[0])["outcome"] == "other"
    second = fields(out[1])
    assert second["outcome"] == "candidate" and second["firings"] == "1"


def test_a_stop_before_the_servers_go_is_not_reported(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint", "state()")
    assert fields(out[0])["outcome"] == "installed"


def test_a_watch_written_with_the_value_it_held_fires_by_the_consoles_line(
        tmp_path: Path) -> None:
    out = gate_run(tmp_path, "watch", """
        logged("Stopped at watchpoint 1 writing 00 to 00000040 (PC=00000700)")
        stop_at(0x700) frame('b') state()""")
    got = fields(out[0])
    assert got["outcome"] == "candidate" and got["firings"] == "1"


def test_a_gate_told_off_writes_its_last_counts(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint", "stop_at(0x1234) tell_off() hooks() state()")
    got = fields(out[0])
    assert got["outcome"] == "off" and got["firings"] == "1"


def test_the_servers_own_stop_at_its_release_is_not_a_new_stop(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint",
                   "stop_at(0x1234) frame('title') state() stop_at(0x5555) go(2) hooks() state()")
    assert fields(out[1])["seq"] == fields(out[0])["seq"]


def test_what_the_server_did_while_held_is_not_a_watch_firing(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "watch", """
        poke(0x40, 5) stop_at(0x700) frame('b') state()
        logged("Stopped at watchpoint 1 writing 09 to 00000040") poke(0x40, 9) stop_at(0x5555)
        release(2) stop_at(0x2000) state()""")
    got = fields(out[1])
    assert got["outcome"] == "other" and got["firings"] == "1"


def test_a_gate_told_off_does_nothing(tmp_path: Path) -> None:
    out = gate_run(tmp_path, "breakpoint",
                   "tell_off() stop_at(0x1234) frame('menu') stop_at(0x2000) state()")
    got = fields(out[0])
    assert got["outcome"] == "off" and got["firings"] == "0"


def test_the_condition_becomes_lua_over_registers_and_memory() -> None:
    terms = stop_wait.parse_condition("d0!=3 && w@level==0x10")
    assert at_stop.condition_lua(terms, lambda ref: 0x50) == (
        'cpu.state["D0"].value ~= 0x3 and sp:read_u16(0x50) == 0x10')
    assert at_stop.condition_lua((), lambda ref: 0) == "true"


@pytest.mark.parametrize("text", ["seq=1", "seq=x outcome=a firings=0 examined=0 line=0 pc=0"])
def test_a_state_line_out_of_shape_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "x.state"
    path.write_text(text)
    with pytest.raises(st.Invalid) as e:
        at_stop.read_state(path)
    assert e.value.code == "unexpected_answer"
    path.unlink()
    assert at_stop.read_state(path) is None


# ------------------------------------------------------------------- the clocks across a wait


class Clocked:
    """A session whose console answers the frame counter and `totalcycles` from `values`."""

    def __init__(self) -> None:
        self.values = {"frame": 10, "totalcycles": 1000}
        self.emulated = 0.5

    def emulated_seconds(self) -> float:
        return self.emulated


@pytest.mark.parametrize("symbol", ["frame", None])
def test_the_clocks_are_read_before_and_after_a_wait(monkeypatch: pytest.MonkeyPatch,
                                                     symbol: str | None) -> None:
    ses = Clocked()
    monkeypatch.setattr(read, "frame_symbol", lambda: symbol)
    monkeypatch.setattr(read, "print_values", lambda s, names: [s.values[n] for n in names])
    monkeypatch.setattr(cpus, "visible_cpu", lambda s: ":maincpu")
    after = advance.clock_before(ses)  # type: ignore[arg-type]
    ses.values, ses.emulated = {"frame": 12, "totalcycles": 1300}, 0.6
    got = after()
    assert got["cycles"] == 300 and got["emulated_after_s"] != got["emulated_before_s"], got
    if symbol is None:
        assert got["frame_before"]["available"] is False, got
        assert got["frame_after"]["available"] is False, got
    else:
        assert (got["frame_before"], got["frame_after"]) == (10, 12), got


def test_a_clock_the_console_cannot_read_is_said_and_the_reply_keeps_its_model(
        monkeypatch: pytest.MonkeyPatch) -> None:
    ses = Clocked()
    ses.emulated = None  # type: ignore[assignment]

    def values(s: Clocked, names: list[str]) -> list[int]:
        raise gs.ExpressionRefused("no such symbol")
    monkeypatch.setattr(read, "frame_symbol", lambda: "frame")
    monkeypatch.setattr(read, "print_values", values)
    monkeypatch.setattr(cpus, "visible_cpu", lambda s: ":maincpu")
    got = advance.clock_before(ses)()  # type: ignore[arg-type]
    for key in ("cycles", "frame_before", "frame_after", "emulated_before_s",
                "emulated_after_s"):
        assert got[key]["available"] is False, (key, got)
    reply_schema.check("screen_wait", {"summary": "s", "status": "ok", "verdict": "TIMEOUT",
                                       **got, "session": SESSION})


# ------------------------------------------------------------------- the server's loop


class Ses:
    """A session whose console `g` makes the gate write the next of `outcomes`."""

    def __init__(self, state: Path, outcomes: list[str]) -> None:
        self.state, self.outcomes = state, outcomes
        self.sent: list[str] = []
        self.running = False
        self.seq = 1

    def monitor(self, command: str) -> str:
        self.sent.append(command)
        if self.outcomes:
            self.seq += 1
            outcome = self.outcomes.pop(0)
            self.state.write_text(outcome if outcome.startswith("garbled") else
                                  f"seq={self.seq} outcome={outcome} firings={self.seq - 1} "
                                  "examined=1 line=40 pc=1234\n")
        return ""


@pytest.fixture
def loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    store = dec.DeclarationStore("t", None)
    store.add(dec.Declaration("breakpoint", "address", "0x1234", cpu=":maincpu"))
    store.add(dec.Declaration("breakpoint", "address", "0x2000", cpu=":maincpu",
                              role="control"))
    store.add(dec.Declaration("watch", "symbol", "level", cpu=":maincpu", watch_mode="show",
                              width=1, fmt="u8"))
    store.add(dec.Declaration("watch", "pointer", "[0x10]+0x2", cpu=":maincpu",
                              watch_mode="change", width=1, fmt="u8"))
    store.add(dec.Declaration("breakpoint", "symbol", "gone", cpu=":maincpu"))
    monkeypatch.setattr(arming, "store", lambda: store)
    monkeypatch.setattr(arming, "resolve_decl", lambda d: dec.Resolved(
        d, "unresolved", None) if d.ref == "gone" else dec.Resolved(d, "address", int(d.ref, 16)))
    monkeypatch.setattr(cpus, "chosen", lambda ses, cpu: ":maincpu")
    monkeypatch.setattr(at_stop, "_WAITS", itertools.count(1))

    def installed(ses, scratch, script, seconds, progress, what):  # type: ignore[no-untyped-def]
        at_stop.files_of(scratch, 1)[0].write_text(
            "seq=1 outcome=installed firings=0 examined=0 line=-1 pc=0\n")
        return "", {}
    monkeypatch.setattr(chunk, "run", installed)
    monkeypatch.setattr(running, "survey",
                        lambda ses, scratch: {"pc": st.hex_addr(0x1234), "cpu": ":maincpu"})

    def attribute(pc: int, cpu: str | None) -> str:
        assert isinstance(pc, int), pc        # the survey's pc is hex text
        return "the frame's end"
    monkeypatch.setattr(running, "attribute", attribute)
    monkeypatch.setattr(running, "finish_stop", lambda ses, seen, cause, **base: {
        "status": "ok", "cause": cause, "stop_seq": 9, **base})
    monkeypatch.setattr(running, "stop", lambda ses, scratch: {"status": "ok", "stop_seq": 8})
    monkeypatch.setattr(at_stop, "POLL_S", 0.001)
    monkeypatch.setattr(at_stop, "FINAL_WAIT_S", 0.01)
    monkeypatch.setattr(advance, "clock_before", lambda ses: lambda: dict(CLOCK))
    return tmp_path


#: What `run_for` measures across a run, which a wait's reply carries as its model requires.
CLOCK = {"cycles": 300, "frame_before": 10, "frame_after": 12, "emulated_before_s": 0.1,
         "emulated_after_s": 0.2}
SESSION = {"alive": True, "running": False, "altered": False}


def wait(scratch: Path, outcomes: list[str], judged: list[dict[str, Any] | None],
         seconds: float = 5.0, ref: str = "0x1234", kind: str = "breakpoint"
         ) -> tuple[dict[str, Any], Ses]:
    spec = stop_wait.check(ref if kind == "breakpoint" else "", ref if kind == "watch" else "",
                           0, "")
    assert spec is not None
    ses = Ses(at_stop.files_of(scratch, 1)[0], outcomes)
    out = at_stop.screen_wait_at(ses, scratch, spec, "", lambda: judged.pop(0), "screen",  # type: ignore[arg-type]
                                 "screen 'menu'", seconds, lambda *a: None, lambda r: 0)
    return out, ses


def control(scratch: Path) -> str:
    return at_stop.files_of(scratch, 1)[1].read_text()


def test_the_clocks_are_read_before_the_gate_is_installed(loop: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    installed = chunk.run

    def install(*a: object) -> object:
        order.append("install")
        return installed(*a)  # type: ignore[arg-type]
    monkeypatch.setattr(chunk, "run", install)
    def clock_before(ses: object) -> Callable[[], dict[str, Any]]:
        order.append("clock")
        return lambda: dict(CLOCK)
    monkeypatch.setattr(advance, "clock_before", clock_before)
    wait(loop, ["candidate"], [{"screen": {"name": "menu", "layer": "file"}}])
    assert order == ["clock", "install"], order


def test_the_loop_releases_until_a_candidate_matches(loop: Path) -> None:
    out, ses = wait(loop, ["candidate", "candidate"],
                    [None, {"screen": {"name": "menu", "layer": "file"}}])
    assert out["verdict"] == "TARGET" and out["screen"]["name"] == "menu", out
    assert out["firings"] == 2 and out["fired_line"] == 40 and ses.sent == ["g", "g"]
    assert out["cause"] == "the frame's end" and control(loop) == "off\n"
    assert {k: out[k] for k in CLOCK} == CLOCK, out
    reply_schema.check("screen_wait", {"summary": "s", **out, "session": SESSION})


def test_a_stop_the_gate_did_not_make_ends_the_wait_recording_it(loop: Path) -> None:
    with pytest.raises(st.Invalid) as e:
        wait(loop, ["other"], [])
    assert e.value.code == "wait_stopped" and "0x00001234" in str(e.value)
    assert e.value.fields["stop_seq"] == 9 and e.value.fields["cause"] == "the frame's end"


def test_a_bound_with_firings_is_a_timeout_on_the_stops_reply(loop: Path) -> None:
    out, _ = wait(loop, ["candidate"], [None], seconds=0.05)
    assert out["verdict"] == "TIMEOUT" and "not found" in str(out["note"]), out
    assert out["stop_seq"] == 8 and {k: out[k] for k in CLOCK} == CLOCK, out
    reply_schema.check("screen_wait", {"summary": "s", **out, "session": SESSION})


def test_a_bound_with_no_firing_is_never_fired_on_the_stops_fields(loop: Path) -> None:
    with pytest.raises(st.Invalid) as e:
        wait(loop, [], [], seconds=0.05)
    assert e.value.code == "never_fired" and e.value.fields["stop_seq"] == 8


def test_a_failure_while_the_machine_is_let_go_leaves_the_session_running(
        loop: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    left: list[bool] = []
    monkeypatch.setattr(advance, "left_running", lambda ses, unprovable=False: left.append(True))
    with pytest.raises(st.Invalid) as e:
        wait(loop, ["garbled"], [])
    assert e.value.code == "unexpected_answer" and left == [True]
    assert control(loop) == "off\n"


def test_a_gate_that_wrote_nothing_is_refused_and_told_off(
        loop: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chunk, "run", lambda *a: ("", {}))
    with pytest.raises(st.Invalid) as e:
        wait(loop, [], [])
    assert e.value.code == "unexpected_answer" and control(loop) == "off\n"


def test_a_bound_whose_stop_fails_hands_that_failure_back(
        loop: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    failed = {"status": "INVALID", "code": "not_settled", "message": "still running"}
    monkeypatch.setattr(running, "stop", lambda ses, scratch: failed)
    out, _ = wait(loop, [], [], seconds=0.05)
    assert out == failed


@pytest.mark.parametrize(("ref", "kind", "code"), [
    ("0x9999", "breakpoint", "unknown_ref"),
    ("0x2000", "breakpoint", "bad_argument"),
    ("level", "watch", "bad_argument"),
    ("[0x10]+0x2", "watch", "bad_argument"),
    ("gone", "breakpoint", "bad_argument"),
])
def test_a_row_that_cannot_be_waited_on_is_refused_first(loop: Path, ref: str, kind: str,
                                                          code: str) -> None:
    with pytest.raises(st.Invalid) as e:
        wait(loop, [], [], ref=ref, kind=kind)
    assert e.value.code == code
    assert not at_stop.files_of(loop, 1)[0].exists()
