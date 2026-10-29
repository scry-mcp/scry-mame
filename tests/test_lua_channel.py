"""The Lua channel: scripts, the pipe, the reader and the backlog."""

from __future__ import annotations

import io
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from lua_support import (  # noqa: E402
    AVI_HEAD,
    CONSOLE,
    PROMPT,
    STA_HEAD,
    TRIO,
    VOLUME,
    _backlog,
    _captured,
    _channel,
    _DiesMidWait,
    _logging_stateload,
    _marks_of,
    _PipeProcess,
    _scratch_logging,
    _settles,
    _SlowExit,
    _Stepper,
    _TimedPipe,
    _whole,
)
from scry_core import progress as mprogress  # noqa: E402
from session_doubles import blank_session, refused  # noqa: E402

from scry_mame import (
    advance,  # noqa: E402
    launch,  # noqa: E402
    lua,  # noqa: E402
    summaries,  # noqa: E402
    transport,  # noqa: E402
)
from scry_mame import files as mfiles  # noqa: E402
from scry_mame import gdb_session as g  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402
from scry_mame import write as mwrite  # noqa: E402


def test_a_script_becomes_one_chunk_under_pcall_with_its_sentinel() -> None:
    """The console reads stdin a LINE at a time and loads each as its own chunk, so a two-line
    script would run as two chunks and a `local` on the first would be gone by the second."""
    line = transport.chunk_line('local x = "a\\b"\nprint(x)', 7)
    assert "\n" not in line
    assert line.startswith('local f, e = load("')
    assert '\\"a\\\\b\\"\\nprint(x)' in line
    assert 'print("MAME_MCP_LUA_END#7", false, e)' in line
    assert 'pcall(f) print("MAME_MCP_LUA_END#7", ok, err)' in line
    # And the chunk the capture holds is the one this code builds, byte for byte.
    assert (transport.chunk_line('print(string.format("PROBE %02x %02x", 0x20, 0x34))', 1).encode()
            + b"\n" in CONSOLE)


def test_a_script_is_evaluated_by_one_step_and_read_between_echo_and_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The shape"""
    script = 'print(string.format("PROBE %02x %02x", 0x20, 0x34))'
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(1)
    out = s.lua(script)
    assert out["status"] == "ok", out
    assert out["output"] == "PROBE 20 34\n"
    assert out["evaluated_by"] == "one step"
    assert out["pc_before"] == "0x00000400" and out["pc"] == "0x00000404"
    assert ses.stepped == 1
    assert out["session"]["altered"] is True and _whole()["altering_writes"] == 1
    assert out["cause"] == "lua: one step"
    assert out["summary"].startswith("lua: 12 chars back, pc 0x00000404")
    assert "note" not in out, "a script that printed needs no hint"
    # The mark moved past the sentinel.
    ses.answers[2] = b"PROBE 20 35\n" + ses.sentinel(2)
    again = s.lua(script)
    assert again["output"] == "PROBE 20 35\n" and _whole()["altering_writes"] == 2


def test_an_empty_output_from_a_script_that_never_printed_says_where_the_channel_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The console captures what `print`s, and a `return` prints nothing"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    out = s.lua("return emu.romname()")
    assert out["status"] == "ok" and out["output"] == "", out
    assert "print" in out["note"] and "return" in out["note"], out.get("note")
    assert list(out)[-1] == "session"
    ses.answers[2] = ses.sentinel(2)
    silent = s.lua("print()")
    assert silent["output"] == "" and "note" not in silent, "a script that prints is not hinted"


def test_a_script_that_raises_is_a_refusal_in_the_consoles_words_and_the_reader_survives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The captured answer to a raised script"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(2)
    assert ses.answers[1].count(b"MAME_MCP_LUA_END#1") == 2, "the duplicate is in the capture"
    out = refused("attempt to call a nil value", s.lua("this_function_does_not_exist()"))
    assert out["code"] == "bad_argument"
    assert out["session"]["altered"] is True
    ses.answers[2] = b"after\n" + ses.sentinel(2)
    assert s.lua("print('after')")["output"] == "after\n"


def test_a_script_printing_the_prompt_bytes_does_not_cut_its_own_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = b"before\n" + PROMPT + b"after\n" + ses.sentinel(1)
    out = s.lua("print('x')")
    assert out["output"] == "before\n" + PROMPT.decode() + "after\n"


def test_a_line_the_console_never_answers_is_wait_expired_and_says_it_is_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No sentinel within the bound"""
    _channel(monkeypatch, tmp_path)
    out = refused("no sentinel for the line", s.lua("print(1)", seconds=0.3))
    assert out["code"] == "wait_expired" and out["pending"] is True
    seq = int(out["call"].rsplit("#", 1)[1])
    assert f"as the line {mstate.LUA_SENTINEL}#{seq} followed by a tab" in out["message"], (
        "the late answer is findable in `log` by the line this message names", out["message"])


def test_a_long_answer_goes_to_a_file_like_debugs_and_the_summary_counts_it_whole(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    long = "\n".join(str(i) for i in range(1, 2001)).encode() + b"\n"
    assert len(long) > mwrite.DEBUG_MAX
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = long + ses.sentinel(1)
    out = s.lua("for i=1,2000 do print(i) end")
    assert out["clipped"] is True and out["output_chars"] == len(long)
    assert Path(out["output_path"]).name == "lua-1.txt"
    assert Path(out["output_path"]).read_bytes() == long
    assert out["summary"].startswith(f"lua: {len(long)} chars back, to a file")


def test_a_script_above_the_ceiling_is_refused_before_the_machine_is_touched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    refused("ceiling", s.lua("x" * (transport.SCRIPT_MAX + 1)))
    refused("empty", s.lua("   "))
    assert ses.stepped == 0 and ses.stdin.getvalue() == b""


def test_a_session_without_the_pipe_is_no_channel_and_a_closed_pipe_is_session_broken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "proc", _PipeProcess(None))
    assert refused("stdin", s.lua("print(1)"))["code"] == "no_channel"

    class _Closed:
        def write(self, data: bytes) -> None:
            raise BrokenPipeError("pipe closed")

    monkeypatch.setattr(mstate.STATE, "proc", _PipeProcess(_Closed()))
    assert refused("reaches the console any more", s.lua("print(1)"))["code"] == "session_broken"


def test_start_hands_mame_a_stdin_pipe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The channel's write end"""
    from server_support import _boot_args, _stub_boot, _StubProcess

    image = bytes(range(256)) * 64
    _stub_boot(monkeypatch, tmp_path, image, 0)
    s.start(**_boot_args(tmp_path, image))
    try:
        stdin = _StubProcess.last_kwargs["stdin"]
        # Windows': the read end of `CONSOLE_PIPE_BYTES`, created by the server itself
        assert (isinstance(stdin, int) if sys.platform == "win32" else stdin == subprocess.PIPE)
    finally:
        s.close()


@pytest.mark.parametrize(
    ("held", "defvalue", "mask", "active"),
    [
        # The captured case: the coin's bit went low against a high default.
        (0xDBFF, 0x0400, 0x0400, True),
        # A bit outside the mask changed and the field's own did not.
        (0xDBFF, 0x0401, 0x0001, False),
        # The field's bit equals its default while other bits differ from the port before.
        (0x0400, 0x0400, 0x0400, False),
    ],
)
def test_active_is_the_fields_own_bits_against_its_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, held: int, defvalue: int, mask: int,
    active: bool
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = [
        f"[luaengine] MAME_MCP_INPUT#1 set name=\"Coin 1\" player=0 mask={mask:08x} "
        f"defvalue={defvalue:08x} port_before=0000dfff frame=301",
        f"[luaengine] MAME_MCP_INPUT#1 release frame=305 port_held={held:08x}",
    ]
    assert s.input(port=":P1", field="Coin 1", frames=4)["active"] is active


def test_a_refusal_of_what_a_wrappers_answer_showed_carries_the_consoles_trio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The trio rides on every reply that read a chunk's answer back, as the chunk readers' refusals
    carry it, so a wrapper's refusal of what its answer showed carries it too"""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mfiles, "FILE_WAIT_S", 0.05)
    ses.answers[1] = ses.sentinel(1)
    out = refused("not proved held", s.input(port=":P1", field="Coin 1", frames=4))
    assert out.keys() >= TRIO, out
    ses.answers[2] = ses.sentinel(2)
    ses.marks[2] = ["[luaengine] MAME_MCP_RECORD#2 end frame=5"]
    out = refused("no `begin` mark", s.record(frames=2))
    assert out.keys() >= TRIO, out
    ses.answers[3] = ses.sentinel(3)
    ses.marks[3] = ["[luaengine] MAME_MCP_RECORD#3 begin frame=1 recording=true",
                    "[luaengine] MAME_MCP_RECORD#3 end frame=2"]
    out = refused("not a finished AVI", s.record(frames=2))
    assert out.keys() >= TRIO, out


def test_what_mame_logs_during_stateload_is_in_the_stop_surveys_errorlog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The survey reads `error.log` from the last stop, which is before the load began, so what the
    load logged is in the survey's `errorlog` and needs no field of its own."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    assert s.state_write("save", name="live")["status"] == "ok"
    _logging_stateload(monkeypatch, ses, "stateload says: something about the state")
    loaded = s.state_write("load", name="live")
    assert loaded["status"] == "ok", loaded
    assert loaded["errorlog"]["lines_total"] >= 1
    assert "stateload says: something about the state" in loaded["errorlog"]["lines"]


def test_a_wrappers_marks_close_the_digits_of_their_number(tmp_path: Path) -> None:
    """THE SAME AXIS ON THE LUA WRAPPERS' SIDE."""
    log = mfiles.log_path(tmp_path, "emulator")
    log.write_text("[luaengine] MAME_MCP_THROTTLE#10 throttled=true frame=50\n"
                   "[luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=51\n")
    assert lua.marks_since(tmp_path, 0, "MAME_MCP_THROTTLE#1") == [
        "[luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=51"], "#10's line is not #1's"
    assert lua.marks_since(tmp_path, 0, "MAME_MCP_THROTTLE#10") == [
        "[luaengine] MAME_MCP_THROTTLE#10 throttled=true frame=50"]


def test_the_row_stands_on_a_reply_from_a_tool_that_did_not_make_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """EVERY REPLY MEANS EVERY REPLY, including a refusal, which is the one a caller gets when
    something is already wrong."""
    ses = _channel(monkeypatch, tmp_path)
    s.throttle(on=True)
    ses.answers = {1: ses.sentinel(1), 2: b"7\n" + ses.sentinel(2)}
    s.lua("print(7)", seconds=1.0)
    assert mstate.STATE.throttles_not_applied, "the row is earned"
    told = s.status()
    assert told["session"]["throttles_not_applied"][0]["tag"] == "MAME_MCP_THROTTLE#1", told
    refusal = refused("", s.read_memory(ref="zzz_no_such_symbol", length=2))
    assert refusal["session"]["throttles_not_applied"] == told["session"][
        "throttles_not_applied"], "a refusal carries it too"


def test_the_error_paths_nobody_reaches_by_accident(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each branch here is a refusal or a wording a happy path never exercises."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    refused("not a bound", s.lua("print(1)", seconds=0))
    # A record whose run never emulated a frame: pending, said in the summary too.
    ses.sluggish = 2                           # the console reads nothing for two frames
    out = s.record(frames=2)
    assert out["pending"] is True and out["summary"] == "record: " + summaries.PENDING_SCRIPT
    # A record whose script answered and logged no mark at all, not even the `armed` line it writes
    # as it is evaluated (the first line is read on the first frame, this one on the second).
    ses.answers[1] = ses.sentinel(1)
    ses.answers[2] = ses.sentinel(2)
    out = refused("not even the `armed` line", s.record(frames=2))
    assert out["code"] == "readback_refused", out
    assert mstate.STATE.captures == [], "a refused recording is no capture"
    # A throttle on a running machine whose mark never lands within the bound.
    ses.running = True
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)
    out = refused("still pending", s.throttle(on=True, seconds=0.2))
    assert out["code"] == "wait_expired" and out["pending"] is True
    ses.running = False
    # A state written by another session: the frame comparison is `not checked`, said so.
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    folder = ses.scratch / "sta" / "m68k-dual"
    folder.mkdir(parents=True)
    (folder / "theirs.sta").write_bytes(STA_HEAD)
    out = s.state_write("load", name="theirs")
    assert out["status"] == "ok" and out["verified"]["available"] is False
    assert "did not write" in out["verified"]["why"]
    assert out["summary"].startswith(
        "state_write load: theirs, rom_check unavailable, verified unavailable")
    # A load after which the ROM check fails: refused, never a traceback.
    rom = tmp_path / "rom.bin"
    rom.write_bytes(bytes(64))
    monkeypatch.setattr(mstate.STATE, "reference", (rom, 0, 0))

    def lying(rom_: bytes, addr: int, n: int = 16, base: int = 0, *,
               thread: int) -> None:
        raise g.Mismatch("the reference bytes differ")

    monkeypatch.setattr(ses, "self_check", lying)
    assert refused("ROM check failed", s.state_write("load",
                                                     name="theirs"))["code"] == "readback_refused"
    # A frame the console cannot answer at the save: recorded as None, not a crash.
    monkeypatch.setattr(mstate.STATE, "reference", None)
    def no_frame(command: str, timeout: float = 10.0) -> str:
        (folder / "noframe.sta").write_bytes(STA_HEAD)
        return "x"

    monkeypatch.setattr(ses, "monitor", no_frame)
    assert s.state_write("save", name="noframe")["frame"] == {"available": False,
                                                     "why": mstate.FRAME_UNREAD_WHY}
    # A CHANNEL that fails during the re-check is not a mismatch.
    monkeypatch.setattr(mstate.STATE, "reference", (rom, 0, 0))

    def silent(rom_: bytes, addr: int, n: int = 16, base: int = 0, *, thread: int) -> None:
        raise g.Timeout("no answer to the read")

    monkeypatch.setattr(ses, "self_check", silent)
    monkeypatch.setattr(mstate.STATE, "ses", ses)      # the latch lands on the live session
    out = refused("no answer to the read", s.state_write("load", name="theirs"))
    assert out["code"] == "session_broken" and getattr(ses, "broken", None), out


def test_close_reports_its_progress_while_mame_takes_its_time(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """`close` blocking in `proc.wait(timeout)` and painting nothing makes a quit that takes seconds
    look like a hung server."""

    ticks: list[str] = []
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "proc", _SlowExit(2.2))
    monkeypatch.setattr(mstate.STATE, "scratch", None)
    numbers: list[tuple[float, float | None]] = []

    def record(p: float, t: float | None, m: str) -> None:
        ticks.append(m)
        numbers.append((p, t))

    ended = mstate.STATE.kill(record)
    assert ended["ended_by"] == "quit" and ended["exit_code"] == 0
    assert ticks and all(m.startswith("close: waiting for MAME to quit") for m in ticks), ticks
    assert all(t is None and 0 < p < mstate.QUIT_GRACE_S for p, t in numbers), numbers
    control: list[str] = []
    monkeypatch.setattr(mstate.STATE, "proc", _SlowExit(0.0))
    mstate.STATE.kill(lambda p, t, m: control.append(m))
    assert control == [], "a process already gone has nothing to report"


def test_start_reports_its_progress_while_the_gdbstub_is_slow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The boot of a whole board is the longest wait a session makes, and it painted nothing."""
    import time

    from server_support import _boot_args, _stub_boot

    image = bytes(range(256)) * 64
    ses = _stub_boot(monkeypatch, tmp_path, image, 0)
    ready_at = time.monotonic() + 2.2

    def slow_connect() -> None:
        if time.monotonic() < ready_at:
            raise OSError("connection refused")

    ses.dial = slow_connect  # type: ignore[method-assign]
    ticks: list[str] = []
    monkeypatch.setattr(s, "bridge", lambda ctx: (lambda p, t, m: ticks.append(m)))
    out = s.start(**_boot_args(tmp_path, image), boot_seconds=5.0)
    try:
        assert out["status"] == "ok", out
        assert ticks and "waiting for the gdbstub on port" in ticks[0], ticks
    finally:
        s.close()


def test_start_and_close_carry_the_clients_context_to_their_waits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Through the TOOLS, with a real context"""
    import time

    import anyio
    from server_support import _boot_args, _stub_boot

    got: list[tuple[float, float | None, str | None]] = []

    class _Ctx:
        async def report_progress(self, progress: float, total: float | None = None,
                                  message: str | None = None) -> None:
            got.append((progress, total, message))

    image = bytes(range(256)) * 64
    ses = _stub_boot(monkeypatch, tmp_path, image, 0)
    ready_at = time.monotonic() + 2.2

    def slow_connect() -> None:
        if time.monotonic() < ready_at:
            raise OSError("connection refused")

    ses.dial = slow_connect  # type: ignore[method-assign]

    async def main() -> None:
        out = await anyio.to_thread.run_sync(
            lambda: s.start(**_boot_args(tmp_path, image), boot_seconds=6.0, ctx=_Ctx()))
        assert out["status"] == "ok", out
        assert any("waiting for the gdbstub" in str(m) for _p, _t, m in got), got
        monkeypatch.setattr(mstate.STATE, "proc", _SlowExit(2.2))
        got.clear()
        await anyio.to_thread.run_sync(lambda: s.close(ctx=_Ctx()))
        assert any("waiting for MAME to quit" in str(m) for _p, _t, m in got), got

    anyio.run(main)


def test_a_start_whose_stub_never_answers_carries_mames_own_last_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`start` kills the session and deletes the scratch when the gdbstub never listens, so the
    refusal is the only place MAME's last lines survive"""
    from server_support import _boot_args, _stub_boot, _StubProcess

    image = bytes(range(256)) * 64
    ses = _stub_boot(monkeypatch, tmp_path, image, 0)

    def refuses() -> None:
        raise OSError("connection refused")

    ses.dial = refuses  # type: ignore[method-assign]
    real_init = _StubProcess.__init__

    def writing_init(self: Any, *a: Any, **k: Any) -> None:
        real_init(self, *a, **k)
        k["stdout"].write(b"Fatal error: Console plugin not found.\n")
        k["stdout"].flush()

    monkeypatch.setattr(_StubProcess, "__init__", writing_init)
    out = s.start(**_boot_args(tmp_path, image), boot_seconds=0.5)
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert "Console plugin not found" in out["stdout_tail"]
    assert out["session"]["alive"] is False, "the failed start owns nothing"


def test_the_stdout_tail_of_a_session_with_no_scratch_is_empty() -> None:
    assert launch.stdout_tail(None) == ""


def test_a_line_the_run_did_not_evaluate_is_bought_with_one_step_and_the_frames_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """On m68k-dual five recordings in a row can all be exact on one run, and on another the last
    two come back PENDING with the chunk still in the pipe after the whole run."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    ses.sluggish = 40                      # the whole first run passes without a read
    path = ses.scratch / "snap" / "record-1.avi"
    ses.answers[1] = _captured(5)
    ses.marks[1] = [m.replace("#5", "#1") for m in _marks_of("MAME_MCP_RECORD#5")]
    ses.files[1] = (path, AVI_HEAD)
    out = s.record(frames=30)
    assert out["status"] == "ok" and out["ended"] is True and out["avi_frames"] == 30, out
    assert "pending" not in out
    assert ses.stepped == 1, "one step bought the evaluation"
    assert out["frame_after"] - out["frame_before"] == 33, "the reply is the second run's"


def test_the_double_answers_one_line_per_tick_like_the_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The fidelity the case below rests on, asserted on the double itself."""
    ses = _channel(monkeypatch, tmp_path)
    ses.stdin.write(b"a MAME_MCP_LUA_END#1\nb MAME_MCP_LUA_END#2\n")
    ses.answers = {1: ses.sentinel(1), 2: ses.sentinel(2)}
    ses.step()
    assert len(ses.queue) == 1 and b"#2" in ses.queue[0]
    ses.step()
    assert ses.queue == []


def test_lua_steps_once_per_line_still_in_the_pipe_before_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `throttle` asked on a stopped machine leaves its line in the pipe, and the console reads
    ONE line each time its hook runs"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: ses.sentinel(1), 2: b"m68k-dual\n" + ses.sentinel(2)}
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=100"]}
    queued = s.throttle(on=True)
    assert queued["status"] == "ok" and queued["pending"] is True, queued
    out = s.lua("print(emu.romname())", seconds=0.5)
    assert out["status"] == "ok", out
    assert out["output"] == "m68k-dual\n" and out["evaluated_by"] == "2 steps", out
    assert out["lines_ahead"] == 1 and ses.stepped == 2, out
    keys = list(out)
    assert keys.index("lines_ahead") < keys.index("output") < keys.index("cause"), keys
    # With the pipe drained, the next call costs the one step it always did.
    ses.answers[3] = b"1\n" + ses.sentinel(3)
    again = s.lua("print(1)", seconds=0.5)
    assert again["evaluated_by"] == "one step" and again["lines_ahead"] == 0
    assert ses.stepped == 3


def test_a_stop_the_reader_had_not_taken_the_line_for_is_followed_by_one_more_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The console's reader is a THREAD (`plugins/console/init.lua`, `emu.thread`), and the periodic
    hook, run once at a stop, returns without evaluating while that thread is still taking the
    line."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s_: slept.append(s_))
    ses.reader_late = 1
    ses.answers = {1: b"2140790385\n" + ses.sentinel(1)}
    out = s.lua("print(1)", seconds=1.0, read_only=True)
    assert out["status"] == "ok" and out["output"] == "2140790385\n", out
    assert out["evaluated_by"] == "2 steps" and out.get("reader_steps", 0) == 1, out
    assert out["lines_ahead"] == 0 and ses.stepped == 2 and out["session"]["altered"] is False
    # THE SETTLE.
    assert slept and slept[0] == transport.READER_SETTLE_S, slept[:3]
    # A reader that never hands the line over inside the bound.
    monkeypatch.setattr(transport, "READER_STEPS_MAX", 1)
    ses.reader_late = 20
    out = refused("reader", s.lua("print(1)", seconds=0.4, read_only=True))
    assert out.get("reader_steps", 0) == 1 and out["pending"] is True, out
    assert ses.stepped == 2 + 1 + 1, ses.stepped
    # The double's fidelity: a late reader is a step that consumed nothing.
    ses.reader_late, ses.queue, ses.stdin = 1, [], _TimedPipe()
    ses.consumed = 0
    ses.stdin.write(b"x MAME_MCP_LUA_END#9\n")
    ses.answers[9] = ses.sentinel(9)
    ses.step()
    assert ses.queue == [] and ses.consumed == 0, "the late step took nothing from the pipe"
    ses.step()
    assert ses.consumed > 0 and ses.queue == [], "the next one did"


def test_a_line_the_reader_died_holding_is_sent_again_once_and_the_reply_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """On m68k-dual the first line of a session is echoed, the reader dies with "return value must
    be string", and no sentinel for it ever comes"""
    ses = _channel(monkeypatch, tmp_path)
    sig = b"%d\n"
    ses.answers = {2: sig % 22 + ses.sentinel(2)}
    ses.reader_eats = 1
    out = s.lua("print(1)", seconds=1.0, read_only=True)
    assert out["status"] == "ok" and out["output"] == "22\n", out
    assert out.get("resent", 0) == 1 and out["call"] == "MAME_MCP_LUA_END#2", out
    assert out["thread_errors"] == 1 and out["console_reruns"] == 0, out
    assert out["evaluated_by"] == "2 steps" and out.get("reader_steps", 0) == 0 and ses.stepped == 2
    # The next call costs one step: the eaten line is not counted as still ahead.
    ses.answers[3] = sig % 33 + ses.sentinel(3)
    out = s.lua("print(1)", seconds=1.0, read_only=True)
    assert out["evaluated_by"] == "one step" and out["lines_ahead"] == 0, out
    ses.reader_eats = 2
    out = refused("NEVER evaluated", s.lua("print(1)", seconds=1.0, read_only=True))
    assert out["code"] == "reader_died" and out["pending"] is False, out
    assert out.get("resent", 0) == 1, out
    assert out["thread_errors"] == 2 and out["console_reruns"] == 0, out
    # And the two lines it died holding are not phantom debt for the call after.
    ses.answers[6] = sig % 66 + ses.sentinel(6)
    out = s.lua("print(1)", seconds=1.0, read_only=True)
    assert out["lines_ahead"] == 0 and out["evaluated_by"] == "one step", out
    # The raw form says `resent` the same way.
    ses.answers[8] = b"9\n" + ses.sentinel(8)
    ses.reader_eats = 1
    out = s.lua("print(9)", seconds=1.0)
    assert out["status"] == "ok" and out.get("resent", 0) == 1 and out["output"] == "9\n", out
    # A wrapper's line eaten on its run is sent again and the run bought again.
    ses.marks[10] = [m.replace("#3", "#9") for m in _marks_of("MAME_MCP_INPUT#3")]
    ses.answers[10] = ses.sentinel(10)
    ses.reader_eats = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and out.get("resent", 0) == 1 and out["released"] is True, out
    ses.reader_eats = 2
    out = refused("NEVER evaluated", s.input(port=":P1", field="Coin 1", frames=4))
    assert out["code"] == "reader_died" and out.get("resent", 0) == 1, out
    assert out.get("drain_steps", 0) == 0, out


def test_a_resend_the_bound_has_no_room_for_is_refused_not_taken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One bound for the whole call"""
    ses = _channel(monkeypatch, tmp_path)
    ses.reader_eats = 1
    real = advance.run_for

    def slow(*a: Any, **k: Any) -> dict[str, Any]:
        time.sleep(0.35)                      # the first run eats the whole 0.3 s bound
        return real(*a, **k)

    calls: list[int] = []

    def counted(*a: Any, **k: Any) -> dict[str, Any]:
        calls.append(1)
        return slow(*a, **k)

    monkeypatch.setattr(advance, "run_for", counted)
    out = refused("bound ran out before the resent line's run",
                  s.input(port=":P1", field="Coin 1", frames=4, seconds=0.3))
    assert out["code"] == "wait_expired" and out["pending"] is True, out
    assert calls == [1], "the second run was not taken"


def test_an_answer_the_step_brought_with_the_bound_spent_is_not_reported_as_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The run spent the whole bound, the step evaluated the line and its answer came in on the last
    look, and the frames bought again have no room left."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    ses.sluggish = 40                      # the whole first run passes without a read
    ses.answers[1] = _captured(5)
    ses.marks[1] = [m.replace("#5", "#1") for m in _marks_of("MAME_MCP_RECORD#5")]
    real = advance.run_for
    calls: list[int] = []

    def slow(*a: Any, **k: Any) -> dict[str, Any]:
        calls.append(1)
        time.sleep(0.35)                      # the first run eats the whole 0.3 s bound
        return real(*a, **k)

    monkeypatch.setattr(advance, "run_for", slow)
    out = refused("script answered", s.record(frames=30, seconds=0.3))
    assert out["code"] == "wait_expired" and out["pending"] is False, out
    assert ses.stepped == 1 and calls == [1], "the step ran, the frames were not bought again"


def test_a_call_whose_emulator_died_while_it_waited_says_so_instead_of_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`wait_expired` says the line is still pending in the pipe, to be evaluated when the console's
    hook next runs."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    monkeypatch.setattr(mstate.STATE, "proc", _DiesMidWait(ses.stdin, after=1))
    ses.reader_late = 20
    out = refused("died by signal 11", s.lua("print(1)", seconds=5.0, read_only=True))
    assert out["code"] == "session_broken" and out["exit_code"] == -11, out
    assert "pending" not in out["message"], out
    assert "was stepped 1 time for it" in out["message"], out
    assert out["lines_ahead"] == 0 and out["call"] == "MAME_MCP_LUA_END#1", out
    # THE CONTROL.
    monkeypatch.setattr(mstate.STATE, "proc", _PipeProcess(ses.stdin, ses))
    out = refused("no sentinel for the line", s.lua("print(1)", seconds=0.3))
    assert out["code"] == "wait_expired", out


def test_every_console_wait_says_the_emulator_died_rather_than_calling_it_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE SAME LIE, TOLD BY THREE LOOPS."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)

    ses.answers = {}
    out = s.input(port=":P1", field="Coin 1", frames=4, seconds=1.0)
    assert out["status"] == "ok" and out.get("released") is not True, out
    assert "note" in out, out

    # `input` and `record` go through `_answer_or_none`, which is where the swallow was.
    monkeypatch.setattr(mstate.STATE, "proc", _DiesMidWait(ses.stdin, after=0))
    out = refused("died by signal 11", s.input(port=":P1", field="Coin 1", frames=4,
                                                  seconds=1.0))
    assert out["code"] == "session_broken" and out["exit_code"] == -11, out
    assert "pending" not in out["message"], out

    ses.running = True
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)
    monkeypatch.setattr(mstate.STATE, "proc", _DiesMidWait(ses.stdin, after=0))
    out = refused("died by signal 11", s.throttle(on=False, seconds=1.0))
    assert out["code"] == "session_broken" and out["exit_code"] == -11, out
    assert "still pending" not in out["message"], out


def test_a_line_the_console_refused_and_that_was_sent_again_is_named_in_the_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE SECOND SHAPE OF A LOST LINE, through a real call"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    ses.console_refuses = 1
    out = s.lua("print(7)")
    assert out["status"] == "ok" and out["output"].strip() == "7", out
    assert out.get("resent", 0) == 1 and out["session"]["console"]["lost"] == 1, out
    assert out["thread_errors"] == 0 and out["console_reruns"] == 0, out
    note = out.get("note", "")
    assert "never evaluated" in note and "sent again (1 time)" in note, out
    assert "died" not in note and "AGAIN" not in note, out
    # THE CONTROL.
    ses.answers[3] = b"8\n" + ses.sentinel(3)
    clean = s.lua("print(8)")
    assert clean.get("resent", 0) == 0 and "note" not in clean, clean


def test_lua_refuses_a_pipe_too_far_ahead_and_says_how_a_frame_drains_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Nine lines nobody answered would cost nine steps and a pc nine instructions on"""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "lua_seq", transport.PIPE_STEPS_MAX + 1)
    out = refused("ahead", s.lua("print(1)", seconds=0.2))
    assert out["code"] == "bad_argument" and "run_for" in out["message"]
    assert ses.stdin.getvalue() == b"" and ses.stepped == 0


def test_a_script_printing_the_sentinels_text_cannot_poison_the_count_of_lines_ahead(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The raw `lua` prints what it likes, the sentinel's text included, and a number this server
    never sent must not read as "everything is answered" """
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = b"MAME_MCP_LUA_END#999\tfaked\n" + ses.sentinel(1)
    out = s.lua('print("MAME_MCP_LUA_END#999", "faked")')
    assert out["status"] == "ok" and out["evaluated_by"] == "one step", out
    assert transport.answered_seq(ses.scratch) == 1
    ses.answers[2] = b"2\n" + ses.sentinel(2)
    again = s.lua("print(2)")
    assert again["evaluated_by"] == "one step" and again["lines_ahead"] == 0
    assert ses.stepped == 2


def test_a_lua_that_expires_says_how_many_steps_it_took_and_where_the_answer_lands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 1)      # one line ahead, never answered
    out = refused("stepped 2 time", s.lua("print(1)", seconds=0.2))
    assert out["code"] == "wait_expired" and out["lines_ahead"] == 1
    assert "session is altered" in out["message"] and out["call"] == "MAME_MCP_LUA_END#2"
    assert out["evaluated_by"] == "2 steps" and ses.stepped == 2 and "log" in out["message"]


def test_a_missing_stdout_log_is_a_pending_line_with_nothing_seen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    (ses.scratch / "stdout.log").unlink()
    out = refused("no sentinel for the line", s.lua("print(1)", seconds=0.2))
    assert out["code"] == "wait_expired" and out["seen_bytes"] == 0


def test_a_queued_wrapper_lets_the_reader_take_the_line_before_it_advances(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE WINDOW THAT KILLS THE READER, on a wrapper that runs frames rather than steps"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(3)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok", out
    assert ses.stdin.written and ses.advanced, (ses.stdin.written, ses.advanced)
    gap = ses.advanced[0] - ses.stdin.written[0]
    assert gap >= transport.READER_SETTLE_S, (
        f"the machine was advanced {gap:.4f}s after the line reached the pipe, inside the "
        f"{transport.READER_SETTLE_S}s the reader needs to take it")


def test_send_returns_only_after_the_reader_settle_that_follows_its_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The window that kills the reader is opened by the WRITE, so the function that writes owns the
    wait"""
    ses = _channel(monkeypatch, tmp_path)
    slept = _settles(monkeypatch, ses)
    line, _seq = transport.send("print(1)")
    assert slept == [(transport.READER_SETTLE_S, len(line) + 1, 0)], slept


def test_a_lua_call_settles_the_reader_once_before_its_first_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ONE OWNER"""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = b"1\n" + ses.sentinel(1)
    slept = _settles(monkeypatch, ses)
    out = s.lua("print(1)", seconds=0.5)
    assert out["status"] == "ok" and ses.stepped == 1, out
    before_step = [z for z in slept if z[2] == 0]
    assert before_step == [(transport.READER_SETTLE_S, len(ses.stdin.getvalue()), 0)], slept


def test_a_queued_wrapper_drains_the_pipe_first_and_says_how_deep_it_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `throttle` asked while stopped leaves its line in the pipe."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: ses.sentinel(1), 2: _captured(3, as_seq=2)}
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=100"],
                 2: [m.replace("#3", "#2") for m in _marks_of("MAME_MCP_INPUT#3")]}
    queued = s.throttle(on=True)
    assert queued["pending"] is True, queued
    assert 1 in mstate.STATE.lua_pending, "a line sent is pending until the log settles it"
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok", out
    assert out["lines_ahead"] == 1, out
    assert 1 not in mstate.STATE.lua_pending and _whole()["console"]["lost"] == 0, (
        "settled by its sentinel: it ran, and nothing is lost")
    # The input's own frames were its own: the field was released, not left held.
    assert out["released"] is True, out


def test_a_wrapper_whose_reader_died_before_the_echo_says_so_and_counts_nothing_lost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE DEATH NOTHING COULD PIN ON THE LINE"""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    ses.reader_dead = True
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "INVALID", out
    assert out["code"] == "reader_died", out
    assert "may still run on a later reader" in out["message"], out
    assert "lost" not in out["message"], out
    assert out["pending"] is True and out.get("resent", 0) == 0 and out["lines_ahead"] == 0, out
    assert out["thread_errors"] == 1, out
    assert _whole()["console"]["lost"] == 0 and mstate.STATE.lua_lost == 0, out
    assert transport.pending_lines(tmp_path) == 1, "the line is still ahead in the pipe"


def test_a_wrapper_line_the_step_after_its_run_hands_to_a_dying_reader_is_lost_not_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The run evaluated nothing, and the one step after it gave the line to a reader that died
    holding it"""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    ses.sluggish = 1000
    ses.reader_eats = 1
    out = refused("NEVER evaluated", s.input(port=":P1", field="Coin 1", frames=4))
    assert out["code"] == "reader_died" and out["pending"] is False, out
    assert out["session"]["console"]["lost"] == 1 and transport.pending_lines(ses.scratch) == 0, out


@pytest.mark.parametrize("tool", ["input", "record"])
def test_a_wrapper_refusal_after_its_drain_still_says_the_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool: str
) -> None:
    """The drain's steps are spent whatever the call ends in: a script that raised, behind a
    line left in the pipe, is refused with `drain_steps` beside the console's words."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: ses.sentinel(1), 2: ses.sentinel(2, False, "mcp:3: boom")}
    assert s.throttle(on=True)["pending"] is True
    out = refused("boom", s.input(port=":P1", field="Coin 1", frames=4) if tool == "input"
                  else s.record(frames=2))
    assert out["code"] == "unexpected_answer", ("this server's own script raised", out)
    assert (out["lines_ahead"], out.get("drain_steps", 0)) == (1, 1), out


def test_settling_the_pending_lines_survives_a_loss_that_settles_another_on_the_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`record_lost` reads the log again, and a log that grew meanwhile settles the rest from inside
    the first settlement"""
    ses = _channel(monkeypatch, tmp_path)
    lines = [transport.chunk_line("print(1)", n) for n in (1, 2)]
    with open(ses.scratch / "stdout.log", "ab") as fh:
        for line in lines:
            fh.write(line.encode() + b"\n[LUA ERROR] in thread: return value must be string\n")
    monkeypatch.setattr(mstate.STATE, "lua_seq", 2)
    monkeypatch.setattr(mstate.STATE, "lua_pending", {1: (lines[0], 0), 2: (lines[1], 0)})
    real = transport.record_lost
    nested: list[int] = []

    def settles_the_rest(seq: int) -> None:
        real(seq)
        if not nested:
            nested.append(seq)
            transport._settle_pending(ses.scratch)

    monkeypatch.setattr(transport, "record_lost", settles_the_rest)
    transport._settle_pending(ses.scratch)
    assert mstate.STATE.lua_pending == {} and mstate.STATE.console_lines_lost == 2


def test_a_wrapper_says_the_steps_its_drain_spent_on_a_line_ahead(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `throttle` left in the pipe costs the next wrapper a step before its own line, and the
    reply says so beside `lines_ahead`."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: ses.sentinel(1), 2: _captured(3, as_seq=2)}
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=100"],
                 2: [m.replace("#3", "#2") for m in _marks_of("MAME_MCP_INPUT#3")]}
    assert s.throttle(on=True)["pending"] is True
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok", out
    assert (out["lines_ahead"], out.get("drain_steps", 0)) == (1, 1), out
    keys = list(out)
    assert keys.index("lines_ahead") < keys.index("drain_steps")


def test_status_counts_the_lines_the_console_has_not_evaluated_and_close_drains_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A backlog left in the pipe is what MAME's Lua GC tears down at `quit` (SIGSEGV in
    `lua_engine::close`)."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=100"]}
    assert s.status()["console_pending"] == 0, "nothing sent, nothing pending"
    queued = s.throttle(on=True)
    assert queued["pending"] is True, queued
    assert s.status()["console_pending"] == 1, s.status()
    ses.answers[1] = ses.sentinel(1)
    out = s.close()
    assert out["console_pending_before"] == 1, out
    assert out["console_drained"] == 1, out


def test_a_stale_thread_error_from_an_earlier_call_is_not_this_calls_reader_dying(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE FALSE POSITIVE the death detector invites."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    # A death this session already survived, left in the log before anything is sent.
    with open(ses.scratch / "stdout.log", "ab") as fh:
        fh.write(b"[LUA ERROR] in thread: attempt to index a nil value\n" + PROMPT)
    ses.sluggish = 40                      # merely slow: the reader is alive
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok", out
    assert out["pending"] is True, out


def test_the_pending_reply_says_the_line_was_sent_twice_when_it_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A chunk sent again is a second write for a script that writes, which this channel promises
    never to leave silent."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    # The first send is TAKEN by the reader and never run (its echo, then the thread's death).
    ses.reader_eats = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["pending"] is True, out
    assert out.get("resent", 0) == 1, out
    assert "sent 2 times" in out["note"] and "about the second" in out["note"], out


def test_close_does_not_step_a_running_machine_to_drain_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`throttle` is the one wrapper callable while the guest RUNS, and its own timeout leaves the
    line queued with the machine still running."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=100"]}
    s.throttle(on=True)
    assert s.status()["console_pending"] == 1
    ses.running = True
    before = ses.stepped
    out = s.close()
    assert ses.stepped == before, "close stepped a machine that was running"
    assert out["console_pending_before"] == 1, out
    assert out["console_drained"] == 0, out
    assert "RUNNING" in out["note"], out


def test_a_lua_the_caller_declares_read_only_does_not_alter_but_says_whose_word_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The raw form marks the session ALTERED on every call, a read included, because a Lua string
    can read a byte or rewrite RAM and the text does not say which."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: b"5\n" + ses.sentinel(1), 2: b"6\n" + ses.sentinel(2)}
    read = s.lua("print(5)", read_only=True)
    assert read["status"] == "ok" and read["output"] == "5\n", read
    assert read["session"]["altered"] is False, read["session"]
    assert read["session"]["read_only_claims"] == 1, read["session"]
    assert "caller" in read["session"]["note"], read["session"]
    # The default is untouched: one ordinary call and the session is altered as always.
    wrote = s.lua("print(6)")
    assert wrote["session"]["altered"] is True, wrote["session"]
    # BOTH THINGS THE SESSION HAS TO SAY stand in its one note: the claims, then the modification.
    claims, modified = wrote["session"]["note"].split("; this session has been MODIFIED")
    assert "caller" in claims and modified.startswith(":"), wrote["session"]
    assert wrote["session"]["read_only_claims"] == 1, wrote["session"]


def test_a_batch_refuses_a_class_in_fmt_before_a_single_step_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`perform` promises the WHOLE list is judged before the first step runs, and the tool's
    `@`-in-fmt refusal was not mirrored here"""
    ses = _channel(monkeypatch, tmp_path)
    before = ses.stepped
    out = refused("does not take one", s.perform(steps=[
        {"op": "step", "count": 1},
        {"op": "watch_add", "ref": "0x4a0", "mode": "show", "fmt": "ptr16@CODE"}]))
    assert out["code"] == "bad_argument", out
    assert ses.stepped == before, "an earlier step of the batch ran before the refusal"


def test_a_refusal_does_not_contradict_its_own_session_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ONE REPLY MAY NOT CARRY TWO ANSWERS TO ONE QUESTION."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    ses.reader_eats = 2
    out = refused("NEVER evaluated", s.lua("print(7)", seconds=1.0))
    assert out["code"] == "reader_died" and out["thread_errors"] == 2, out
    assert out["session"]["console"]["thread_errors"] == out["thread_errors"], out
    assert out["session"]["console"]["lost"] == 2, out



def test_a_reader_that_died_after_the_echo_is_a_line_that_was_never_evaluated() -> None:
    """THE FIRST SHAPE"""
    line = transport.chunk_line('print("x")', 11)
    raw = (line + "\n").encode() + b"[LUA ERROR] in thread: return value must be string\n"
    assert transport.eaten(raw, line) is True


def test_no_two_calls_of_a_session_share_a_line_so_the_echo_search_has_one_candidate() -> None:
    """THE PROPERTY `eaten` RESTS ON, and the one only volume can put a question to.

    `eaten` finds this line by `raw.find((line + "\\n").encode())`, which answers the FIRST
    occurrence. That is sound only while no two calls of a session can send the same bytes:
    if two ever did, this line's verdict would be read off the older one's tail, and a script
    would be executed a second time on the strength of a death it survived. What keeps them
    apart is `chunk_line` embedding the call's own number twice in every line -- and nothing
    else in this file asserts it, because with one echo in the buffer there is nothing to
    collide with.

    A session's worth of real calls, the same script text sent over and over, and every
    line still distinct: that is the claim, and it takes a capture to make it.
    """
    echoes = re.findall(re.escape(PROMPT) + rb'([^\n]*MAME_MCP_LUA_END#\d+"[^\n]*)\n', VOLUME)
    assert len(echoes) > 50, f"{len(echoes)} echoed lines is not a session's worth"
    assert len(set(echoes)) == len(echoes), "two calls sent the same bytes"
    # AND THE SCRIPTS REPEAT, which is what makes the line above worth asserting rather than a
    # property of a session that happened to send a different script every time.
    bare = Counter(re.sub(rb"MAME_MCP_LUA_END#\d+", b"#", e) for e in echoes)
    assert max(bare.values()) >= 10, f"no script was sent twice: {bare.most_common(3)}"


def test_the_volume_fixture_keeps_the_size_that_is_its_whole_point() -> None:
    """THE SIZE IS PART OF THE CONTRACT, so it is asserted rather than assumed."""
    assert len(VOLUME) > 100_000, f"the capture is {len(VOLUME)} bytes: the volume is gone"
    assert VOLUME.count(PROMPT) > 50, "a session's worth of calls is what gives it volume"


def test_an_answer_is_cut_at_its_own_line_whatever_follows_it_in_the_same_look(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One look can hold more than this call's answer (a frame evaluates several lines)."""
    line = transport.chunk_line("print(1)", 1)
    own = (line.encode() + b"\nout \xff put\nMAME_MCP_LUA_END#1\tfalse\tmcp:1: a\ttab \xfe\n")
    later = PROMPT + b"somebody else's line\nMAME_MCP_LUA_END#2\ttrue\tnil\n" + PROMPT
    scratch = _scratch_logging(tmp_path, monkeypatch, own + later)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 2)
    answer, _ = transport.find_answer(scratch, line, 1)
    assert answer is not None and answer.ok is False
    assert answer.error == "mcp:1: a\ttab �" and answer.text == "out � put\n"
    assert mstate.STATE.console_mark == len(own), "the mark sits on the byte after the line"
    assert transport.since(scratch, mstate.STATE.console_mark) == later
    ok_line = transport.chunk_line("print(2)", 3)
    _scratch_logging(tmp_path, monkeypatch, ok_line.encode() + b"\nMAME_MCP_LUA_END#3\ttrue\tnil\n")
    monkeypatch.setattr(mstate.STATE, "lua_seq", 3)
    answer, _ = transport.find_answer(tmp_path, ok_line, 3)
    assert answer is not None and answer.ok is True and answer.error == ""


def test_a_console_that_ends_its_lines_in_crlf_is_read_as_one_that_ends_them_in_lf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MAME on Windows writes its stdout in text mode, the echo and the sentinel included."""
    line = transport.chunk_line("print(1)", 1)
    log = line.encode() + b"\r\nout\r\nMAME_MCP_LUA_END#1\ttrue\t42\r\n" + PROMPT
    scratch = _scratch_logging(tmp_path, monkeypatch, log)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 1)
    answer, _ = transport.find_answer(scratch, line, 1)
    assert answer is not None and (answer.ok, answer.text, answer.error) == (True, "out\n", "")
    assert transport.passed_over(log, line) is True and transport.eaten(log, line) is False
    died = line.encode() + b"\r\n" + transport.THREAD_ERROR + b" boom\r\n"
    assert transport.eaten(died, line) is True

def test_a_resent_line_the_reader_is_late_for_is_stepped_for_like_any_other(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reader's window restarts at the resend's own step, and every step spent for the reader is
    counted"""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    ses.reader_eats = 1
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    step = ses.step

    def late_after_the_first() -> str:
        if ses.stepped == 1:
            ses.reader_late = 2
        return step()

    monkeypatch.setattr(ses, "step", late_after_the_first)
    pc = ses.pc
    out = s.lua("print(7)", seconds=2.0)
    assert out["status"] == "ok" and out["output"] == "7\n", out
    assert out.get("resent", 0) == 1 and out.get("reader_steps", 0) == 2, out
    assert out["evaluated_by"] == "4 steps" and ses.stepped == 4, out
    assert out["pc_before"] == f"{pc:#010x}", out


def test_a_refusal_counts_its_steps_and_names_where_the_machine_stood(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """What a refused evaluation cost is in the refusal, in the reply's own fields"""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    monkeypatch.setattr(transport, "READER_STEPS_MAX", 1)
    ses.reader_late = 20
    pc = ses.pc
    out = refused("reader", s.lua("print(1)", seconds=0.4))
    assert out["code"] == "wait_expired" and out.get("reader_steps", 0) == 1, out
    assert out["evaluated_by"] == "2 steps" and out["pc_before"] == f"{pc:#010x}", out
    assert out["lines_ahead"] == 0 and out["call"] == "MAME_MCP_LUA_END#1", out
    # A line taken and lost twice, on a channel of its own: the resend's step is in the count.
    (tmp_path / "lost").mkdir()
    ses = _channel(monkeypatch, tmp_path / "lost")
    ses.reader_eats = 2
    out = refused("twice", s.lua("print(1)", seconds=1.0))
    assert out["code"] == "reader_died" and out.get("resent", 0) == 1, out
    assert out["evaluated_by"] == "2 steps", out


def test_a_backlog_that_does_not_clear_is_stepped_a_bounded_number_of_times(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A wrapper steps the lines ahead off before it sends its own, and a line the console never
    evaluates cannot make that a walk without end."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    transport.send("print('never answered')")
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["pending"] is True and out["lines_ahead"] == 1, out
    # The depth plus the cap for the backlog, then the one step the pending path spends.
    assert ses.stepped == 1 + transport.PIPE_STEPS_MAX + 1, ses.stepped
    assert "after 5 frames and one step" in out["note"], out["note"]


def test_a_calls_own_chunk_run_again_is_left_in_the_log_for_the_next_call_to_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The answer ends at the FIRST sentinel of the call."""
    line = transport.chunk_line("print(1)", 1)
    own = line.encode() + b"\n1\nMAME_MCP_LUA_END#1\ttrue\tnil\n"
    again = (transport.THREAD_ERROR
             + b" attempt to index a nil value\n1\nMAME_MCP_LUA_END#1\ttrue\tnil\n")
    nxt = transport.chunk_line("print(2)", 2)
    rest = PROMPT + nxt.encode() + b"\n2\nMAME_MCP_LUA_END#2\ttrue\tnil\n" + PROMPT
    scratch = _scratch_logging(tmp_path, monkeypatch, own + again + rest)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 2)
    first, _ = transport.find_answer(scratch, line, 1)
    assert first is not None and first.text == "1\n" and first.reruns == []
    second, _ = transport.find_answer(scratch, nxt, 2)
    assert second is not None and second.text == "2\n"
    assert second.reruns == ["MAME_MCP_LUA_END#1"] and second.thread_errors == 1


def test_the_pipe_is_refused_one_line_past_the_steps_a_call_spends_and_not_at_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exactly `PIPE_STEPS_MAX` lines ahead is a depth the call steps off"""
    blank_session(monkeypatch)
    monkeypatch.setattr(mstate.STATE, "lua_seq", transport.PIPE_STEPS_MAX)
    assert transport.refuse_if_too_deep(tmp_path) == transport.PIPE_STEPS_MAX
    monkeypatch.setattr(mstate.STATE, "lua_seq", transport.PIPE_STEPS_MAX + 1)
    with pytest.raises(mstate.Invalid) as caught:
        transport.refuse_if_too_deep(tmp_path)
    e = caught.value
    assert e.code == "bad_argument" and e.fields == {"lines_ahead": transport.PIPE_STEPS_MAX + 1}
    assert str(e).startswith(f"{transport.PIPE_STEPS_MAX + 1} lines are still ahead"), str(e)


def test_a_backlog_that_never_clears_is_drained_for_its_depth_plus_the_cap_and_no_more(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch = _backlog(monkeypatch, tmp_path, 2)
    ses = _Stepper()
    assert transport.drain(ses, scratch) == (2, 0)  # type: ignore[arg-type]
    assert ses.stepped == 2 + transport.PIPE_STEPS_MAX


def test_a_backlog_that_clears_is_drained_by_one_step_per_line_and_says_how_many_went(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch = _backlog(monkeypatch, tmp_path, 3)

    def answers(stepped: int) -> None:         # one line per step, the console's own rate
        if stepped <= 2:
            with open(mfiles.log_path(scratch, "process"), "ab") as fh:
                fh.write(b"MAME_MCP_LUA_END#%d\ttrue\tnil\n" % stepped)

    ses = _Stepper(answers)
    monkeypatch.setattr(transport, "PIPE_STEPS_MAX", 0)       # the depth alone is the budget here
    assert transport.drain(ses, scratch) == (3, 2)  # type: ignore[arg-type]
    assert ses.stepped == 3
    # And one that empties stops being stepped at once, whatever budget is left.
    monkeypatch.setattr(transport, "PIPE_STEPS_MAX", 8)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 4)
    ses = _Stepper(lambda _n: mfiles.log_path(scratch, "process").write_bytes(
        b"MAME_MCP_LUA_END#4\ttrue\tnil\n"))
    assert transport.drain(ses, scratch) == (2, 2)  # type: ignore[arg-type]
    assert ses.stepped == 1


def test_a_drain_whose_step_the_stub_refuses_stops_there_and_still_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch = _backlog(monkeypatch, tmp_path, 1)

    def refuses(_stepped: int) -> None:
        raise g.SessionError("the stub went")

    assert transport.drain(_Stepper(refuses), scratch) == (1, 0)  # type: ignore[arg-type]


def test_the_drain_close_asks_for_is_bounded_by_the_clock_it_was_written_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`close` passes no bound, so the default IS the bound of every real drain"""
    scratch = _backlog(monkeypatch, tmp_path, 1)
    bounds: list[float] = []

    class _Spent(mprogress.Ticker):
        def __init__(self, seconds: float, progress: Any) -> None:
            super().__init__(seconds, progress)
            bounds.append(seconds)

        def expired(self) -> bool:
            return True

    monkeypatch.setattr(mprogress, "Ticker", _Spent)
    ses = _Stepper()
    assert transport.drain(ses, scratch) == (1, 0)  # type: ignore[arg-type]
    assert bounds == [2.0] and ses.stepped == 0


def test_an_answer_awaited_names_what_it_waited_for_and_the_bytes_it_saw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch = _scratch_logging(tmp_path, monkeypatch, b"12345")
    line = transport.chunk_line("print(1)", 1)
    with pytest.raises(mstate.Invalid) as caught:
        transport.await_answer(scratch, line, 1, 0.05)
    assert caught.value.code == "wait_expired" and caught.value.fields["seen_bytes"] == 5
    monkeypatch.setattr(mstate.STATE, "proc", _PipeProcess(io.BytesIO(),
                                                         SimpleNamespace(quit_asked=True)))
    with pytest.raises(mstate.Invalid, match="waited for the console's answer") as caught:
        transport.await_answer(scratch, line, 1, 0.05)
    assert caught.value.code == "session_broken" and caught.value.fields["seen_bytes"] == 5


def test_a_session_with_no_process_has_no_emulator_that_could_have_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blank_session(monkeypatch)
    monkeypatch.setattr(mstate.STATE, "proc", None)
    assert transport.emulator_gone() is None


def test_a_wrappers_session_block_is_built_after_its_answer_was_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The run's reply was built inside `run_for`, BEFORE the wrapper read its answer"""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    ses.answers = {1: b"7\n" + ses.sentinel(1), 2: ses.sentinel(2)}
    assert s.lua("print(7)", seconds=1.0)["status"] == "ok"
    assert mstate.STATE.console_reruns_seen == 0
    ses.marks[2] = [m.replace("#3", "#2") for m in _marks_of("MAME_MCP_INPUT#3")]
    ses.reader_dies = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and out["console_reruns"] == 1, out
    assert out["thread_errors"] == 1, out
    assert out["session"]["console"] == {"thread_errors": 1, "reruns": 1, "lost": 0}, (
        "the block is composed after the answer the call read")
    assert list(out)[-1] == "session"


@pytest.mark.parametrize(("tool", "args", "head"), [
    ("input", {"port": ":IN0", "field": "Coin 1"}, "input :IN0 'Coin 1'"),
    ("record", {}, "record"),
    ("audio_record", {}, "audio_record"),
])
def test_the_pending_summary_never_says_no_frame_ran(tool: str, args: dict[str, Any],
                                                     head: str) -> None:
    """The pending reply's note counts the frames the run spent before the script was given up
    on, so the summary beside it says the script is unevaluated, never that no frame ran: one
    sentence for the three tools."""
    reply = {"pending": True, "note": "the script has no answer after 6 frames and one step"}
    line = getattr(summaries, tool)(args, reply)
    assert line == f"{head}: {summaries.PENDING_SCRIPT}", line
    said = summaries.PENDING_SCRIPT
    assert "not evaluated" in said and "no frame" not in said


def test_a_read_only_chunk_that_expires_says_it_altered_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An expiry says the machine was stepped and that NOTHING was altered, and under which sentinel
    the answer will land"""
    _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    out = refused("alters nothing", s.lua("print(1)", seconds=0.2, read_only=True))
    assert out["code"] == "wait_expired" and out["session"]["altered"] is False, out
    assert out["call"] == "MAME_MCP_LUA_END#1", out
