"""The Lua channel: MAME's `-console` fed through stdin, read back off stdout.

The doubles here are CAPTURED from real sessions, byte for byte, in `tests/fixtures/`:
`console.stdout` is what the console printed for a raw `lua` call, a raw call whose script
raised, an `input`, an `input` on a field that does not exist, a `record` and a `throttle`
(the echo of each chunk, what it printed, the sentinel with the outcome, the prompt), and
`console.error.log` the marks those wrappers' scripts wrote through `logerror`. What the
probe established, and these tests pin: a line sent while the machine is STOPPED is not
evaluated until the console's periodic hook runs (the gdbstub spins in its own packet loop,
and the hook runs once per stop, on the way in, and on a stub that refreshes the display after
a console command, once more per command), so the raw tool buys the evaluation with ONE
single-step; while it RUNS a line is evaluated within a frame.
"""

import inspect
import io
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import blank_session, refused  # noqa: E402
from test_server import _install, _RegisterSession  # noqa: E402

import gdb_session as g  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_envelope as menvelope  # noqa: E402
import mame_files as mfiles  # noqa: E402
import mame_launch as launch  # noqa: E402
import mame_lua as lua  # noqa: E402
import mame_progress as mprogress  # noqa: E402
import mame_recording as mrec
import mame_running as running  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_summaries as summaries  # noqa: E402
import mame_transport as transport  # noqa: E402
import mame_write as mwrite  # noqa: E402
import server as s  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
CONSOLE = (FIXTURES / "console.stdout").read_bytes()
MARKS = (FIXTURES / "console.error.log").read_text().splitlines()
AVI_HEAD = (FIXTURES / "record-30-frames.avi.head").read_bytes()
STA_HEAD = (FIXTURES / "statesave.sta.head").read_bytes()
# The prompt as captured, with its colour codes, and the banner a session starts with.
PROMPT = b"\x1b[1;36m[MAME]\x1b[0m> "
BANNER = (b"mame 0.288\t\nCopyright (C) Nicola Salmoria and the MAME team\n\nLua 5.4\t\n"
          b"Copyright (C) Lua.org, PUC-Rio\n\n" + PROMPT
          + b"gdbstub: listening on address localhost port 23990\n")
# THE CONSOLE REFUSING A LINE AT ITS TOP LEVEL, captured on radendur by writing a bare
# `error(...)` into the pipe: the echo, then `error:`, a TAB and the chunk's name, then the
# prompt. What the double prints is the bytes between that echo and that prompt, verbatim.
CONSOLE_REFUSAL = (FIXTURES / "console.refused.stdout").read_bytes().split(b"\n", 1)[1].split(
    PROMPT, 1)[0]


def _captured(seq: int, as_seq: int = 1) -> bytes:
    """What the console printed AFTER the echo of chunk `seq` in the capture, up to the
    next prompt (the duplicated sentinel MAME prints after a raised script is kept: the
    reader has to survive it), renumbered as call `as_seq` of the test's session."""
    m = re.search(rb'"MAME_MCP_LUA_END#%d", false, e\) [^\n]*\n' % seq, CONSOLE)
    assert m, seq
    rest = CONSOLE[m.end():]
    return rest[:rest.index(PROMPT)].replace(b"#%d" % seq, b"#%d" % as_seq)


def _marks_of(tag: str) -> list[str]:
    return [m for m in MARKS if tag in m]


class _ChannelSession(_RegisterSession):
    """A register session (a frame counter, a console that answers `print`, a `gvblank`
    that moves one frame) with the CHANNEL's two ends: the pipe the server writes lines
    into, and the console's periodic hook, run on every `step` and on every `gvblank`,
    which appends the echo of each pending line, then `answers[seq]` (the captured bytes:
    output and sentinel), then the prompt, to stdout.log, and `marks[seq]` to error.log.
    A line with no answer prepared stays pending, as the real console leaves one the
    machine has not ticked for."""

    def __init__(self, scratch: Path) -> None:
        super().__init__(bits=32, frame=100)
        self.scratch = scratch
        self.answers: dict[int, bytes] = {}
        self.sluggish = 0
        self.reader_late = 0
        self.reader_dies = 0
        self.reader_eats = 0
        self.console_refuses = 0
        self.last: tuple[bytes, bytes] | None = None      # the line and answer last run
        self.marks: dict[int, list[str]] = {}
        self.files: dict[int, tuple[Path, bytes]] = {}   # what a chunk's script writes
        self.pc = 0x400
        self.stdin = _TimedPipe()
        self.advanced: list[float] = []
        # THE READER DIED FOR GOOD: unlike `reader_dies`, no later tick starts one that
        # reads. Nothing is ever taken from the pipe again, the shape a wrapper must survive.
        # AUTHORED, and kept because it is what drives a wrapper into the death it cannot pin
        # on its line; "never again" is this double's, not MAME's (`_queued_then_ran` says
        # why), and no case asserts it.
        self.reader_dead = False
        self.reader_dead_said = False
        self.quit_asked = False
        self.consumed = 0
        self.queue: list[bytes] = []
        self.stepped = 0
        self.write_states = True
        self.checked: list[tuple[int, int]] = []          # the ROM checks asked of it
        (scratch / "stdout.log").write_bytes(BANNER)

    def current_pc(self) -> int:
        return self.pc

    def quit(self) -> None:
        """What `close` asks the console for; the process double exits on the next poll."""
        self.quit_asked = True

    def close(self) -> None:
        return None

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        return bytes(n)

    def self_check(self, rom: bytes, addr: int, n: int = 16, base: int = 0, *,
                   thread: int) -> None:
        self.checked.append((addr, base))

    @staticmethod
    def sentinel(seq: int, ok: bool = True, error: str = "nil") -> bytes:
        return f"MAME_MCP_LUA_END#{seq}\t{str(ok).lower()}\t{error}\n".encode()

    def _tick(self) -> None:
        if self.reader_dead:
            # It prints MAME's own words ONCE and never reads again: no echo of any line,
            # so nothing downstream can see the death through the echo.
            if not self.reader_dead_said:
                self.reader_dead_said = True
                with open(self.scratch / "stdout.log", "ab") as fh:
                    fh.write(b"[LUA ERROR] in thread: attempt to index a nil value\n" + PROMPT)
            return
        # ONE LINE PER TICK, the measured property of the real console (radendur, MAME
        # 0.288): a throttle line sent while stopped and a `lua` line after it were answered
        # by two successive steps, one each. A double answering every pending line per tick
        # could not have shown the defect this models. A line with no answer prepared stays
        # at the head of the queue, as one the machine has not ticked for.
        # THE READER DIED STARTING UP (measured on radendur): the console prints MAME's own
        # words, RUNS THE PREVIOUS CHUNK AGAIN from the result the dead thread never
        # cleared (its answer, with no echo: nothing read it), and takes nothing from
        # the pipe; the next tick starts a reader that does.
        if self.reader_dies > 0 and self.last is not None:
            self.reader_dies -= 1
            with open(self.scratch / "stdout.log", "ab") as fh:
                fh.write(b"[LUA ERROR] in thread: attempt to index a nil value\nstack "
                         b"traceback:\n\t[C]: in function 'require'\n" + self.last[1] + PROMPT)
            return
        fresh = self.stdin.getvalue()[self.consumed:]
        self.consumed = len(self.stdin.getvalue())
        self.queue.extend(line for line in fresh.split(b"\n") if line)
        # THE READER DIED HOLDING THE LINE (measured on radendur): it echoed the line, its return
        # was lost ("return value must be string"), and the chunk never ran.
        if self.reader_eats > 0 and self.queue:
            self.reader_eats -= 1
            line = self.queue.pop(0)
            with open(self.scratch / "stdout.log", "ab") as fh:
                fh.write(line + b"\n[LUA ERROR] in thread: return value must be string\n"
                         + PROMPT)
            return
        # THE CONSOLE REFUSED THE LINE AT ITS TOP LEVEL, the second shape `eaten` knows: the
        # reader is alive, the console prints its own `error:` and hands the prompt back, and
        # neither a `[LUA ERROR] in thread:` nor a duplicate sentinel is left behind.
        if self.console_refuses > 0 and self.queue:
            self.console_refuses -= 1
            line = self.queue.pop(0)
            with open(self.scratch / "stdout.log", "ab") as fh:
                fh.write(line + b"\n" + CONSOLE_REFUSAL + PROMPT)
            return
        for line in self.queue[:1]:
            # THE WRAPPER'S SENTINEL IS THE LAST ON THE LINE: a script may print the
            # sentinel's text itself, and that one comes first, inside the quoted chunk.
            seqs = re.findall(rb"MAME_MCP_LUA_END#(\d+)", line)
            assert seqs, line
            seq = int(seqs[-1])
            answer = self.answers.get(seq)
            if answer is None:
                continue
            self.queue.pop(0)
            self.last = (line, answer)
            with open(self.scratch / "stdout.log", "ab") as fh:
                fh.write(line + b"\n" + answer + PROMPT)
            with open(self.scratch / "error.log", "a") as log:
                for mark in self.marks.get(seq, []):
                    log.write(mark + "\n")
            if seq in self.files:
                path, content = self.files[seq]
                path.write_bytes(content)

    def step(self) -> str:
        self.stepped += 1
        self.executed()
        self.advanced.append(time.monotonic())
        self.pc += 4
        # THE READER IS A THREAD (measured on radendur): `reader_late` stops pass with the hook
        # finding it still busy taking the line, so nothing is evaluated at that stop.
        if self.reader_late > 0:
            self.reader_late -= 1
            return "T05"
        self._tick()
        return "T05"

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        if command == "gvblank":
            self.advanced.append(time.monotonic())
            # `sluggish` frames pass without the console reading its pipe (measured: a run
            # that evaluated nothing, the line still pending); a step always reads it.
            if self.sluggish > 0:
                self.sluggish -= 1
            else:
                self._tick()
        if command.startswith(("statesave ", "stateload ")):
            super().monitor(command, timeout)       # the register half keeps the frame
        if command.startswith("statesave ") and self.write_states:
            folder = self.scratch / "sta" / mstate.STATE.system
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{command[10:]}.sta").write_bytes(STA_HEAD)
            return "State save attempted.  Please refer to window message popup for results.\n"
        if command.startswith("stateload "):
            # MAME's own answer, whatever happened: the refusal is SILENT (measured).
            return "State load attempted.  Please refer to window message popup for results.\n"
        return super().monitor(command, timeout)


class _TimedPipe(io.BytesIO):
    """The stdin end, with the CLOCK: every line written is stamped, so a test can measure
    the gap between a line reaching the pipe and the machine being advanced for it. That
    gap is the whole of `READER_SETTLE_S`, and nothing else observes it."""

    def __init__(self) -> None:
        super().__init__()
        self.written: list[float] = []

    def write(self, data: Any) -> int:
        self.written.append(time.monotonic())
        return super().write(data)


class _PipeProcess:
    """The process end of the channel: alive, with the stdin the session double writes.
    It exits 0 once the console has been asked to quit, which is what `close` measures."""

    pid = 4243

    def __init__(self, stdin: Any, session: Any = None) -> None:
        self.stdin = stdin
        self.session = session

    def poll(self) -> int | None:
        return 0 if self.session is not None and self.session.quit_asked else None

    def wait(self, timeout: float = 0.0) -> int:
        code = self.poll()
        if code is None:
            raise subprocess.TimeoutExpired("mame", timeout)
        return code

    def kill(self) -> None:
        return None


def _channel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _ChannelSession:
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}lua"
    scratch.mkdir()
    (scratch / "snap").mkdir()
    ses = _ChannelSession(scratch)
    # BLANK FIRST, then this fixture's own specifics on top: a reset that ran afterwards
    # would silently un-set what the fixture had just arranged.
    blank_session(monkeypatch)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "scratch", scratch)
    monkeypatch.setattr(mstate.STATE, "system", "m68k")
    monkeypatch.setattr(mstate.STATE, "state_dir", "")
    monkeypatch.setattr(mstate.STATE, "proc", _PipeProcess(ses.stdin, ses))
    return ses


# ------------------------------------------------------------------------- the raw form

def test_the_fixtures_reset_is_derived_from_state_and_not_from_a_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE MECHANISM THAT REPLACED TWO HAND-WRITTEN LISTS, held to what it claims.

    A list of field names goes quietly short, and the field it misses leaks from one case into
    the next in SILENCE, which is the worst way for a suite to be wrong: every case still
    passes and one of them is measuring the previous one's leftovers. It had already happened.
    `blank_session` derives the set from a fresh `State`, so a field added tomorrow is covered
    without anybody remembering; this case is what says that out loud, by dirtying EVERY field
    there is and finding none of them left standing.
    """
    fresh = mstate.State()
    for name, value in vars(fresh).items():
        if name == "start_seq":
            continue
        # A VALUE OF THE RIGHT SHAPE BUT THE WRONG CONTENT, so a field this leaves at its
        # default cannot pass for one that was cleared.
        dirty = (value + 7 if isinstance(value, int) and not isinstance(value, bool)
                 else not value if isinstance(value, bool)
                 else {"leftover": 1} if isinstance(value, dict)
                 else ["leftover"] if isinstance(value, list)
                 else "leftover" if isinstance(value, str)
                 else object())
        monkeypatch.setattr(mstate.STATE, name, dirty)
    blank_session(monkeypatch)
    standing = {name: getattr(mstate.STATE, name) for name in vars(fresh)
                if name != "start_seq" and getattr(mstate.STATE, name) != getattr(fresh, name)}
    assert standing == {}, f"fields the reset left dirty: {sorted(standing)}"


def test_a_script_becomes_one_chunk_under_pcall_with_its_sentinel() -> None:
    """The console reads stdin a LINE at a time and loads each as its own chunk, so a
    two-line script would run as two chunks and a `local` on the first would be gone by
    the second. The whole script travels as one Lua string literal on one line, quoted so
    quotes, backslashes and newlines survive, run under `pcall`, and closed by the sentinel
    of THIS call, so the outcome and the error come back in the console's own words."""
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
    """The measured shape: stopped, the line sits in the pipe until the console's hook runs;
    one step buys the evaluation; the answer is what sits between the echo and the
    sentinel; and the raw form marks the session ALTERED always, its pc moved by the step."""
    script = 'print(string.format("PROBE %02x %02x", 0x20, 0x34))'
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(1)
    out = s.lua(script)
    assert out["status"] == "ok", out
    assert out["output"] == "PROBE 20 34\n"
    assert out["evaluated_by"] == "one step"
    assert out["pc_before"] == "0x00000400" and out["pc"] == "0x00000404"
    assert ses.stepped == 1
    assert out["session"]["altered"] is True and out["session"]["altering_writes"] == 1
    assert out["how"] == "lua: one step"
    assert out["summary"].startswith("lua: 12 chars back, pc 0x00000404")
    assert "note" not in out, "a script that printed needs no hint"
    # The mark moved past the sentinel: the same script again is read from ITS echo and
    # ITS sentinel, not the first one's.
    ses.answers[2] = b"PROBE 20 35\n" + ses.sentinel(2)
    again = s.lua(script)
    assert again["output"] == "PROBE 20 35\n" and again["session"]["altering_writes"] == 2


def test_an_empty_output_from_a_script_that_never_printed_says_where_the_channel_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The console captures what `print`s, and a `return` prints nothing: two repos wrote
    `return emu.romname()`, read `output: ""` beside `status: ok`, and could not tell it from
    a silent failure. The reply says so, once, only when the output is empty and the script
    holds no `print`."""
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
    """The captured answer to a raised script: the sentinel carries `false` and the error,
    MAME prints a `[LUA ERROR] in thread` and the sentinel a SECOND time, and the channel
    goes on. The refusal quotes the error, the session is altered (the step happened), and
    the next call reads its own answer, not the duplicate."""
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
    """No sentinel within the bound: the line is still in the pipe, and the reply says so
    rather than reading the banner as an answer."""
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


def test_the_command_line_opens_the_console_and_names_the_state_directory(
    tmp_path: Path
) -> None:
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}abc"
    cmd = launch.build_command("/bin/mame", "radendur", "/roms", 23946, ["-window"], str(scratch))
    assert "-console" in cmd
    assert cmd[cmd.index("-state_directory") + 1] == str(scratch / "sta")
    assert cmd[cmd.index("-statename") + 1] == "%g", "an ini cannot move the states' folder"
    state = tmp_path / "state"
    cmd = launch.build_command("/bin/mame", "radendur", "/roms", 23946, ["-window"], str(scratch),
                               state_dir=str(state))
    assert cmd[cmd.index("-state_directory") + 1] == str(state / "sta")


def test_start_hands_mame_a_stdin_pipe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The channel's write end: MAME spawned with stdin connected to nothing leaves the
    console reading end-of-file at once."""
    from test_server import _boot_args, _stub_boot, _StubProcess

    image = bytes(range(256)) * 64
    _stub_boot(monkeypatch, tmp_path, image, 0)
    s.start(**_boot_args(tmp_path, image))
    try:
        assert _StubProcess.last_kwargs["stdin"] == subprocess.PIPE
    finally:
        s.close()


# ----------------------------------------------------------------- the typed wrappers

def test_inputs_value_comes_back_as_the_32_bit_value_the_port_took(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MAME's port value is unsigned and 32 bits wide, so a negative value reaches the port as
    its two's complement, and the reply says what the port took in the `0x` spelling a call
    takes back: a `-0x...` would be refused as an argument."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(3)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.input(port=":P1", field="Coin 1", value=-1, frames=4)
    assert out["status"] == "ok" and out["value"] == "0xffffffff", out


def test_input_queues_the_script_and_reads_the_port_back_off_the_marks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The wrapper does not step: it queues the script and RUNS `frames + 1` frames, the
    run's first frame evaluates it, and the two marks the script logs are the measurement:
    the field's own mask and default, the port before, and the port as read at the release.
    `active` is computed off those, never assumed from the set; the chunk sent is the one
    the capture holds, byte for byte."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(3)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.input(port=":P1", field="Coin 1", value=1, frames=4)
    assert out["status"] == "ok", out
    assert ses.stepped == 0, "a wrapper never single-steps"
    assert ses.stdin.getvalue().replace(b"#1", b"#3") in CONSOLE, "the chunk is the captured one"
    assert out["name"] == "Coin 1" and out["player"] == 0 and out["value"] == "0x00000001"
    assert out["mask"] == "0x00000400" and out["defvalue"] == "0x00000400"
    assert out["port_before"] == "0x0000dfff" and out["port_held"] == "0x0000dbff"
    assert out["active"] is True and out["released"] is True
    assert out["frame_set"] == 301 and out["frame_released"] == 305
    assert out["verdict"] == "ELAPSED" and out["frame_after"] - out["frame_before"] == 5
    assert out["session"]["altered"] is False, "a typed wrapper is not the raw form"
    assert list(out)[-1] == "session", "the envelope's shape survives the wrapper's fields"
    assert out["summary"] == "input :P1 'Coin 1': held 4 frames, active True, released at frame 305"


@pytest.mark.parametrize(
    ("held", "defvalue", "mask", "active"),
    [
        # The captured case: the coin's bit went low against a high default.
        (0xDBFF, 0x0400, 0x0400, True),
        # A bit outside the mask changed and the field's own did not: NOT active. A
        # comparison without the mask would say True here.
        (0xDBFF, 0x0401, 0x0001, False),
        # The field's bit equals its default while other bits differ from the port
        # before: comparing against `port_before` instead of `defvalue` would say True.
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


def test_input_refuses_in_the_consoles_words_when_the_field_does_not_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(4)
    out = refused("has no field No Such Field",
                  s.input(port=":P1", field="No Such Field", frames=2))
    assert out["code"] == "unknown_ref", "a field the machine lacks is a name resolving to nothing"


def test_input_cut_short_says_the_field_is_still_held_and_a_later_call_ignores_its_mark(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run another stop cuts before the release frame leaves the field HELD and the
    notifier armed: the reply says so, with the frame the release lands on, and is never a
    refusal that reads as nothing happened. When that release mark lands later, the next
    call's own tag keeps it from being read as its own."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = [_marks_of("MAME_MCP_INPUT#3 set")[0].replace("#3", "#1")]
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and out["released"] is False
    assert out["active"]["available"] is False and out["port_held"]["available"] is False
    assert out["frame_release_planned"] == 305 and "still HELD" in out["note"]
    assert out["summary"] == "input :P1 'Coin 1': still HELD from frame 301, releases at 305"
    # The stale release lands in the log with the FIRST call's tag, before the second call
    # runs: the second call must not take it as its own release.
    with open(ses.scratch / "error.log", "a") as log:
        log.write(_marks_of("MAME_MCP_INPUT#3 release")[0].replace("#3", "#1") + "\n")
    ses.answers[2] = ses.sentinel(2)
    ses.marks[2] = [_marks_of("MAME_MCP_INPUT#3 set")[0].replace("#3", "#2")]
    again = s.input(port=":P1", field="Coin 1", frames=4)
    assert again["released"] is False, "the first call's release is not the second's"


@pytest.mark.parametrize("answered", ["none", "ok", "raised"])
def test_input_under_a_run_that_did_not_settle_is_the_runs_refusal_as_a_recordings_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answered: str
) -> None:
    """The recordings' shape: the run's own `not_settled` refusal, its message carried on with
    what the script did and what may still happen to the field, and never the field's half (the
    set, the release, `active`) under it, whether the script had not answered, had answered with
    its `set` mark logged, or had raised."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    unsettled = {"status": "INVALID", "code": "not_settled",
                 "message": "the frame counter still moves", "frame_before": 100,
                 "frame_after": 103, "session": {}}
    real = lua.queued_then_ran

    def run(*a: Any) -> Any:
        _ran, answer, resent, moved = real(*a)
        answer = {"none": None, "ok": answer,
                  "raised": transport.Answer("", False, "boom")}[answered]
        return dict(unsettled), answer, resent, moved

    monkeypatch.setattr(lua, "queued_then_ran", run)
    out = s.input(port=":P1", field="Coin 1", value=1, frames=4)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert out["message"].startswith("the frame counter still moves. "), out
    assert "input's state is not read" in out["message"], out
    said = {"none": "may not have been evaluated yet", "ok": "frame notifier may still be armed",
            "raised": "raised (boom), so it armed nothing"}[answered]
    assert said in out["message"], out
    assert ":P1" in out["message"] and "Coin 1" in out["message"], out
    for key in ("released", "active", "port_held", "frame_set", "frame_release_planned", "name",
                "mask", "note", "pending"):
        assert key not in out, key
    assert out["frame_before"] == 100 and out["frame_after"] == 103, out
    assert out["lines_ahead"] == 0 and out["drain_steps"] == 0, out
    assert ("resent" in out) and ((answered == "none") or "thread_errors" in out), out


def test_input_with_no_set_mark_is_not_vouched_for_and_a_run_that_never_ticks_is_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    out = refused("not proved held", s.input(port=":P1", field="Coin 1", frames=4))
    assert out["code"] == "readback_refused"
    # No answer at all (the run never emulated a frame): the script is still pending.
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["pending"] is True and "pending" in out["summary"]


def test_input_refuses_its_arguments_before_the_pipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    refused("one frame or more", s.input(port=":P1", field="Coin 1", frames=0))
    refused("both needed", s.input(port="", field="Coin 1"))
    assert ses.stdin.getvalue() == b""


def test_record_checks_the_avi_header_and_runs_two_frames_past_the_recording(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    path = ses.scratch / "snap" / "record-1.avi"
    ses.answers[1] = _captured(5)
    ses.marks[1] = [m.replace("#5", "#1") for m in _marks_of("MAME_MCP_RECORD#5")]
    ses.files[1] = (path, AVI_HEAD)
    out = s.record(frames=30)
    assert out["status"] == "ok", out
    assert out["path"] == str(path) and out["bytes"] == len(AVI_HEAD)
    assert out["avi_frames"] == 30, "the captured header declares the frames asked for"
    assert out["frame_begin"] == 301 and out["frame_end"] == 330
    assert out["recording_after"] is True and out["ended"] is True
    assert out["frame_after"] - out["frame_before"] == 33, (
        "frames + 3: one for the begin, two for the file to close")
    assert out["summary"].startswith("record: 30 frames,")
    assert list(out)[-1] == "session"
    keys = list(out)
    assert keys.index("lines_ahead") < keys.index("path") < keys.index("how"), (
        "the wrapper's own fields come before the stop survey, as the docstring lists them")
    assert out["session"]["altered"] is False


def test_record_writes_to_the_dest_it_is_given_and_names_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `dest` is where the script records, as a Lua string in the chunk, and the file checked
    and named in the reply; the session's own numbering is not used for it."""
    ses = _channel(monkeypatch, tmp_path)
    dest = tmp_path / "mine.avi"
    ses.answers[1] = _captured(5)
    ses.marks[1] = [m.replace("#5", "#1") for m in _marks_of("MAME_MCP_RECORD#5")]
    ses.files[1] = (dest, AVI_HEAD)
    out = s.record(frames=30, dest=str(dest))
    assert out["status"] == "ok" and out["path"] == str(dest), out
    assert str(dest).encode() in ses.stdin.getvalue(), "the chunk records to the dest"
    assert not (ses.scratch / "snap" / "record-1.avi").exists()


@pytest.mark.parametrize("tool,captured,event", [
    ("record", "MAME_MCP_RECORD#5", "begin"),
    ("input", "MAME_MCP_INPUT#3", "set"),
])
def test_a_wrapper_whose_own_mark_appears_twice_refuses_as_a_console_rerun(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool: str, captured: str, event: str,
) -> None:
    """A chunk the console ran twice logs its own mark twice, and the sentinel check cannot
    see it: the call's own number is the one it skips. The wrapper counts its OWN marks, and
    two of the line a single run logs once is a recording begun twice on one file, or a field
    set twice: INVALID, the repeated mark listed, the session's rerun count moved."""
    ses = _channel(monkeypatch, tmp_path)
    seq = captured.rsplit("#", 1)[1]
    ses.answers[1] = _captured(int(seq))
    marks = [m.replace(f"#{seq}", "#1") for m in _marks_of(captured)]
    twice = next(m for m in marks if f"#1 {event}" in m)
    ses.marks[1] = [*marks[:1], twice, *marks[1:]]
    ses.files[1] = (ses.scratch / "snap" / "record-1.avi", AVI_HEAD)
    tag = captured.rsplit("#", 1)[0] + "#1"
    out = (s.record(frames=30) if tool == "record"
           else s.input(port=":P1", field="Coin 1", value=1, frames=4))
    assert out["status"] == "INVALID" and out["code"] == "console_rerun", out
    assert out["console_reruns"] == 1 and f"{tag} {event}" in out["message"], out
    assert out["session"]["console"]["reruns"] == 1, out["session"]


def test_a_console_rerun_refusal_keeps_the_earlier_chunks_the_console_ran_again() -> None:
    """The sentinel check and the wrapper's own marks each find reruns, and a refusal on the
    second carries the first too: one list, the earlier chunks and this call's own."""
    answer = transport.Answer("", True, "", reruns=["MAME_MCP_LUA_END#1"])
    tag = "MAME_MCP_RECORD#2"
    seen = [f"[luaengine] {tag} begin frame=1", f"[luaengine] {tag} begin frame=1"]
    with pytest.raises(mstate.Invalid) as refused_:
        lua.refuse_a_rerun(seen, tag, answer, 0)
    reply = refused_.value.reply()
    assert reply["console_reruns"] == 2 and f"{tag} begin" in reply["message"], reply


def test_captures_lists_what_this_session_recorded_and_snapped_and_says_what_is_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without a listing, `record` and `snapshot` each hand back a path and nothing
    remembers them. Every file the two checked and handed back this session, in the scratch or
    at a `dest`,
    with its size and (an AVI) the frames its header declares; a file that has
    since gone is listed as gone rather than dropped, and the list answers while the machine
    runs."""
    ses = _channel(monkeypatch, tmp_path)
    empty = s.captures()
    assert empty["status"] == "ok" and empty["captures"] == [], empty
    assert empty["summary"] == "captures: 0 files"
    path = ses.scratch / "snap" / "record-1.avi"
    ses.answers[1] = _captured(5)
    ses.marks[1] = [m.replace("#5", "#1") for m in _marks_of("MAME_MCP_RECORD#5")]
    ses.files[1] = (path, AVI_HEAD)
    assert s.record(frames=30)["status"] == "ok"
    dest = tmp_path / "shot.png"
    monkeypatch.setattr(mfiles, "_complete_png", lambda p: p.exists())
    (ses.scratch / "snap" / "snapshot-1.png").write_bytes(b"\x89PNG")
    assert s.snapshot(dest=str(dest))["status"] == "ok"
    out = s.captures()
    assert [c["kind"] for c in out["captures"]] == ["avi", "png"]
    avi, png = out["captures"]
    assert avi["path"] == str(path) and avi["bytes"] == len(AVI_HEAD) and avi["avi_frames"] == 30
    assert "frames" not in avi, "an AVI's count is `avi_frames`, as `record` answers it"
    assert avi["present"] is True and png["path"] == str(dest) and png["present"] is True
    assert "frames" not in png and png["bytes"] == 4
    assert out["summary"] == "captures: 2 files, 1 avi, 1 png"
    dest.unlink()
    gone = s.captures()["captures"][1]
    assert gone["present"] is False and gone["bytes"]["available"] is False
    assert list(out)[-1] == "session"


def test_the_captures_summary_counts_every_kind_and_its_parts_sum_to_the_total(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A graphics tool's `image` is a capture like any other, and the line counts every kind:
    the known kinds first in their own order, then a kind not yet listed in the order first
    seen, so the parts always sum to the total."""
    _channel(monkeypatch, tmp_path)
    for kind, name in (("image", "a.png"), ("mmm", "h.mmm"), ("zzz", "f.zzz"), ("png", "b.png"),
                       ("image", "c.png"), ("wav", "e.wav"), ("aaa", "g.aaa"),
                       ("trace", "d.trace")):
        (tmp_path / name).write_bytes(b"x")
        mstate.STATE.captures.append((kind, str(tmp_path / name)))
    out = s.captures()
    assert out["summary"] == ("captures: 8 files, 1 png, 2 image, 1 wav, 1 trace, 1 mmm, "
                              "1 zzz, 1 aaa"), out["summary"]


def test_record_refuses_a_missing_file_a_wrong_header_and_fewer_than_two_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mfiles, "FILE_WAIT_S", 0.05)
    for n, content in ((1, None), (2, b"RIFF" + bytes(60)),
                       (3, AVI_HEAD[:48] + bytes(4) + AVI_HEAD[52:])):
        ses.answers[n] = ses.sentinel(n)
        ses.marks[n] = [f"[luaengine] MAME_MCP_RECORD#{n} begin frame=1 recording=true",
                        f"[luaengine] MAME_MCP_RECORD#{n} end frame=2"]
        if content is not None:
            ses.files[n] = (ses.scratch / "snap" / f"record-{n}.avi", content)
        out = s.record(frames=2)
        assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert "ZERO frames" in out["message"]
    # The notifier begins the recording on its first call and returns, so it can end one no
    # earlier than the next frame: one frame asked for would be two recorded.
    out = refused("cannot end a recording on the call that begins it", s.record(frames=1))
    assert out["code"] == "bad_argument"
    refused("frames=0 is below 2: the frame notifier cannot end", s.record(frames=0))
    refused("ABSOLUTE", s.record(frames=2, dest="rel.avi"))


def test_record_raised_or_cut_short_is_said_in_the_consoles_words_or_as_still_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1, False, "mcp:5: this machine has no screen to record")
    out = refused("no screen to record", s.record(frames=2))
    assert out["code"] == "no_channel"
    ses.answers[2] = ses.sentinel(2)
    ses.marks[2] = ["[luaengine] MAME_MCP_RECORD#2 begin frame=10 recording=true"]
    out = s.record(frames=5)
    # Begun at frame 10, the script ends the AVI when its counter reads `frames - 1`, so on
    # the notifier call of frame 14: the frame the raw `end` mark names.
    assert out["status"] == "ok" and out["ended"] is False and out["frame_end_planned"] == 14, out
    assert out["began"] is True, out
    assert out["summary"] == "record: still OPEN from frame 10, ends at 14"


def test_record_predicts_the_end_frame_its_script_ends_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The end the open and not-begun replies predict is the count the script ends at."""
    _channel(monkeypatch, tmp_path)
    seen: dict[str, Any] = {}

    real = inspect.signature(mrec.recording_run)

    def run(*args: Any) -> dict[str, Any]:
        seen.update(real.bind(*args).arguments)
        raise mstate.Invalid("bad_argument", "the run is this test's")

    monkeypatch.setattr(mrec, "recording_run", run)
    s.record(frames=5)
    ends = re.search(r"counted >= (\d+) - (\d+) then", seen["script"])
    assert ends is not None, seen["script"]
    assert int(ends.group(1)) - int(ends.group(2)) == seen["ends_after"] == 4, seen


TRIO = {"thread_errors", "console_reruns", "resent"}


@pytest.mark.parametrize(("vblank", "begins"), [("false", 60), ("true", 61)])
def test_a_recording_not_begun_begins_where_its_armed_mark_says(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, vblank: str, begins: int
) -> None:
    """MAME calls the frame notifiers as a vblank BEGINS and moves the frame counter as it ENDS,
    so a chunk the debugger evaluated at a stop inside a vblank is first called on the next
    frame, and one at a stop in the active display on the frame the counter read; the frame the
    run stopped at (108 here) is not the prediction. The run reached every frame it asked for:
    the debugger can evaluate the chunk at that run's own last stop, after its last notifier
    call, so a run that elapsed is no proof the recording began."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = [f"[luaengine] MAME_MCP_RECORD#1 armed frame=60 vblank={vblank}"]
    out = s.record(frames=5)
    assert out["status"] == "ok" and out["began"] is False and out["ended"] is False, out
    assert (out["verdict"], out["frame_after"]) == ("ELAPSED", 108), out
    assert (out["frame_begin_planned"], out["frame_end_planned"]) == (begins, begins + 4), out
    assert out["avi_frames"]["available"] is False and out["bytes"]["available"] is False, out
    assert out["note"] == ("the recording has NOT begun: a stop came before the script's frame "
                           "notifier ran, and the notifier begins it on the next frame the "
                           "machine reaches, unless another `record` call releases it first")
    assert out["summary"] == f"record: NOT begun, begins at frame {begins}, ends at {begins + 4}"
    assert mstate.STATE.captures == [], "a recording not begun is no capture"


def test_a_recording_whose_marks_are_lost_is_refused_and_not_called_not_begun(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No `begin` mark reads as "not begun" only beside the chunk's own `armed` line, which a
    chunk that answered has logged as it was evaluated: with neither, the log lost the marks.
    A run that did not settle is not judged on its marks: it may have left the machine running,
    and its reply is the run's refusal with the file's path, none of the recording's fields."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    out = refused("not even the `armed` line", s.record(frames=5))
    assert out["code"] == "readback_refused" and out.keys() >= TRIO, out
    unsettled = {"status": "INVALID", "code": "not_settled",
                 "message": "the frame counter still moves", "frame_before": 100,
                 "frame_after": 103, "session": {}}
    monkeypatch.setattr(lua, "queued_then_ran",
                        lambda *a: (dict(unsettled), transport.Answer("", True, "nil"), 0, 0))
    out = s.record(frames=5)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert "began" not in out and "frame_begin_planned" not in out and out["path"], out


def test_a_refusal_of_what_a_wrappers_answer_showed_carries_the_consoles_trio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The trio rides on every reply that read a chunk's answer back, as the chunk readers'
    refusals carry it, so a wrapper's refusal of what its answer showed carries it too: `input`
    with no `set` mark, `record` with an `end` mark and no `begin`, and a file that does not
    check."""
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


def test_captures_says_a_recording_its_call_left_unfinished_is_not_listed() -> None:
    """A recording its call answered open or not begun is finished, or released, by a later run
    that reads no file, so `captures` never lists it: every text that describes the list says
    which files it holds, the ones a call checked and handed back, and none claims every file
    the tools wrote."""
    here = Path(__file__).resolve().parent.parent
    texts = {"server": s.captures.__doc__ or "", "mame_recording": mrec.captures.__doc__ or "",
             "README": (here / "README.md").read_text(),
             "REFERENCE": (here / "REFERENCE.md").read_text()}
    for name, text in texts.items():
        flat = " ".join(text.split()).lower()
        assert "wrote this session" not in flat and "graphics tools wrote" not in flat, name
        assert "handed back this session" in flat, name
    assert "a recording its call answered still open or not begun is not listed" in " ".join(
        texts["server"].split()), texts["server"]


def test_state_save_checks_the_header_and_state_load_judges_it_before_the_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`statesave` through the console, the `.sta` found in the system's own folder and its
    header checked; `stateload` marks the session altered, re-runs `start`'s ROM check on
    the machine the state replaced, and compares the frame and pc with the save's."""
    ses = _channel(monkeypatch, tmp_path)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(bytes(64))
    monkeypatch.setattr(mstate.STATE, "reference", (rom, 0x10, 0x20))
    # The captured header names radendur: as m68k the save is refused on the name.
    out = s.state_save(name="live")
    assert out["status"] == "INVALID" and "state of `radendur`" in out["message"], out
    monkeypatch.setattr(mstate.STATE, "system", "radendur")
    out = s.state_save(name="live")
    assert out["status"] == "ok", out
    assert Path(out["path"]) == ses.scratch / "sta" / "radendur" / "live.sta"
    assert out["bytes"] == len(STA_HEAD) and out["frame"] == 100 and out["pc"] == "0x00000400"
    assert set(out["errorlog"]) == {"lines_total", "truncated", "lines"}, "the survey's shape"
    assert "statesave live" in ses.commands
    assert out["session"]["altered"] is False
    refused("already exists", s.state_save(name="live"))
    refused("letters, digits", s.state_save(name="a b"))
    # THE MACHINE MOVES before the load, so the comparison after it can prove one: the double
    # gives the saved frame back at `stateload`.
    ses.stale_after_load = True
    ses.saved_frames["live"] = ses.frame
    ses.frame += 3
    loaded = s.state_load(name="live")
    assert loaded["status"] == "ok", loaded
    assert loaded["rom_check"] == "OK" and loaded["how"] == "stateload live"
    assert loaded["verified"] is True and loaded["saved"] == {"frame": 100, "pc": "0x00000400"}, (
        "one spelling per concept: the pc inside `saved` reads like the pc beside it")
    assert ses.checked == [(0x10, 0x20)], "the ROM check ran again, with start's arguments"
    assert loaded["session"]["altered"] is True
    # ONE WORD, ONE SHAPE: `console` is the session's block of counters on every reply, so
    # the text the debugger console printed for `stateload` is `output`, as `debug` names it.
    assert isinstance(loaded["output"], str) and "console" not in loaded, loaded
    assert isinstance(loaded["session"]["console"], dict)
    assert "stateload live" in ses.commands
    assert "taps_across" not in loaded, "no tap, nothing named"
    # A LIVE TAP counted across the load: the reply names it, as `reset`'s does.
    monkeypatch.setitem(mstate.STATE.tallies, ("frame_lo", ":maincpu"), {})
    loaded = s.state_load(name="live")
    assert loaded["taps_across"] == [{"ref": "frame_lo", "cpu": ":maincpu"}], loaded
    assert mstate.STATE.tallies[("frame_lo", ":maincpu")]["across"][0]["event"] == (
        "stateload live")
    out = refused("no state named", s.state_load(name="nope"))
    assert out["code"] == "unknown_ref" and "`state_list` names the ones held" in out["message"]


def _logging_stateload(monkeypatch: pytest.MonkeyPatch, ses: Any, line: str) -> None:
    """The double's `stateload`, with MAME writing `line` to `error.log` while it loads."""
    plain = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("stateload "):
            with open(mfiles.log_path(ses.scratch, "emulator"), "a") as fh:
                fh.write(line + "\n")
        return str(plain(command, timeout))

    monkeypatch.setattr(ses, "monitor", monitor)


def test_what_mame_logs_during_stateload_is_in_the_stop_surveys_errorlog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The survey reads `error.log` from the last stop, which is before the load began, so
    what the load logged is in the survey's `errorlog` and needs no field of its own."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "radendur")
    assert s.state_save(name="live")["status"] == "ok"
    _logging_stateload(monkeypatch, ses, "stateload says: something about the state")
    loaded = s.state_load(name="live")
    assert loaded["status"] == "ok", loaded
    assert loaded["errorlog"]["lines_total"] >= 1
    assert "stateload says: something about the state" in loaded["errorlog"]["lines"]


def test_state_load_hands_the_stop_no_field_the_survey_also_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A field the tool passes beside the survey and the survey writes too is overwritten on
    every reply: one of the two meanings never reaches the caller."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "radendur")
    assert s.state_save(name="live")["status"] == "ok"
    _logging_stateload(monkeypatch, ses, "stateload says: something about the state")
    finish = running.finish_stop
    clashes: list[set[str]] = []

    def spy(ses_: Any, seen: dict[str, Any], how: str, **base: Any) -> dict[str, Any]:
        clashes.append(set(base) & set(seen))
        return finish(ses_, seen, how, **base)

    monkeypatch.setattr(running, "finish_stop", spy)
    assert s.state_load(name="live")["status"] == "ok"
    assert clashes == [set()], clashes


def test_state_list_names_every_state_in_the_folder_with_what_this_session_knows_of_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Writing and loading states with no way to list them leaves the caller remembering the
    names. Every `.sta` in the session's folder, with its size, and the frame and pc when
    THIS session wrote it (a state from an earlier session
    is listed with `not checked` there, as `state_load` reports it)."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "radendur")
    empty = s.state_list()
    assert empty["status"] == "ok" and empty["states"] == [], empty
    assert Path(empty["state_dir"]) == ses.scratch / "sta" / "radendur"
    assert empty["summary"] == f"state_list: 0 states in {empty['state_dir']}"
    assert s.state_save(name="live")["status"] == "ok"
    (ses.scratch / "sta" / "radendur" / "earlier.sta").write_bytes(STA_HEAD)
    out = s.state_list()
    assert [x["name"] for x in out["states"]] == ["earlier", "live"]
    by = {x["name"]: x for x in out["states"]}
    assert by["live"]["frame"] == 100 and by["live"]["pc"] == "0x00000400"
    assert by["live"]["bytes"] == len(STA_HEAD) and Path(by["live"]["path"]).is_file()
    assert by["earlier"]["frame"]["available"] is False, by["earlier"]
    assert "did not write" in by["earlier"]["frame"]["why"] and "why" not in by["earlier"]
    assert out["summary"] == f"state_list: 2 states in {out['state_dir']}"
    assert list(out)[-1] == "session" and out["session"]["altered"] is False


def test_state_load_refuses_a_state_mame_would_refuse_in_silence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Measured: a corrupt header and a foreign system's state both load as `ok` through
    the console with nothing in any log. So the header is judged BEFORE the console, and
    a load MAME did not take is caught by the frame and pc not being the save's."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "radendur")
    assert s.state_save(name="good")["status"] == "ok"
    folder = ses.scratch / "sta" / "radendur"
    corrupt = bytearray(STA_HEAD)
    corrupt[0:8] = b"NOTASAVE"
    (folder / "corrupt.sta").write_bytes(corrupt)
    foreign = bytearray(STA_HEAD)
    foreign[0x0A:0x1C] = b"pacman".ljust(0x12, b"\0")
    (folder / "foreign.sta").write_bytes(foreign)
    other = bytearray(STA_HEAD)
    other[0x1C:0x20] = b"\x01\x02\x03\x04"
    (folder / "other.sta").write_bytes(other)
    assert refused("savestate magic", s.state_load(name="corrupt"))["code"] == "readback_refused"
    assert refused("state of `pacman`", s.state_load(name="foreign"))["system"] == "pacman"
    out = refused("as this session saves it", s.state_load(name="other"))
    assert out["code"] == "readback_refused"
    assert not [c for c in ses.commands if c.startswith("stateload")], "judged before the console"
    # A well-formed state MAME silently did not load: the machine did not go back.
    ses.frame = 160
    out = refused("MAME did not load it", s.state_load(name="good"))
    assert out["code"] == "readback_refused" and out["saved"] == {"frame": 100, "pc": "0x00000400"}
    # ...and the stop it surveyed is remembered, carried by the refusal itself.
    assert out["frame"] == 160 and out["stop_seq"] == mstate.STATE.last_stop["seq"], out


def test_state_save_with_no_file_is_not_vouched_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mfiles, "FILE_WAIT_S", 0.05)
    ses.write_states = False
    out = refused("lost.sta appeared", s.state_save(name="lost"))
    assert out["code"] == "readback_refused"


def test_throttle_is_pending_on_a_stopped_machine_and_applied_on_a_running_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    out = s.throttle(on=False)
    assert out["pending"] is True and out["mark"] == "MAME_MCP_THROTTLE#1"
    assert out["summary"] == "throttle off: pending until the console next reads a line"
    assert out["applies"].startswith("when the console next reads a line: a step, "), out
    assert out["confirmed_by"].startswith("its mark in the error log, read by the next stop's "
                                          "survey, by `status` and by `close`"), out
    sent = transport.chunk_line(lua.THROTTLE_LUA % {"on": "false", "mark": "MAME_MCP_THROTTLE#6"},
                                6)
    assert sent.encode() + b"\n" in CONSOLE, "the chunk is the captured one"
    assert ses.stdin.getvalue() == sent.replace("#6", "#1").encode() + b"\n"
    # Running: the tick lands the mark and the tool reads it back.
    ses.running = True
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)
    ses.answers[1] = ses.sentinel(1)          # the stopped machine's line, read first
    ses.answers[2] = ses.sentinel(2)
    ses.marks[2] = [_marks_of("MAME_MCP_THROTTLE#6")[0].replace("#6", "#2")]

    def two_frames() -> None:                  # one line per frame: the first line, then ours
        ses._tick()
        ses._tick()
    threading.Timer(0.1, two_frames).start()
    out = s.throttle(on=False, seconds=2.0)
    assert out["pending"] is False and out["frame"] == 341
    assert out["session"]["altered"] is False
    # And a mark that says the OPPOSITE of what was asked is a refusal, not a green.
    ses.answers[3] = ses.sentinel(3)
    ses.marks[3] = ["[luaengine] MAME_MCP_THROTTLE#3 throttled=true frame=408"]
    threading.Timer(0.1, ses._tick).start()
    assert refused("reports throttled=true", s.throttle(on=False, seconds=2.0))["code"] == (
        "readback_refused")


def test_a_throttle_whose_running_machine_stops_before_a_frame_is_pending_not_expired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A breakpoint that stops the machine before its next frame leaves the line in the pipe,
    as a stopped machine does: the reply is `pending` and the switch is recorded, never a wait
    sat out and then forgotten."""
    ses = _channel(monkeypatch, tmp_path)
    ses.running = True
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: True)
    out = s.throttle(on=True, seconds=5.0)
    assert out["status"] == "ok" and out["pending"] is True, out
    assert [r["mark"] for r in mstate.STATE.throttles_pending] == [out["mark"]]


# ------------------------------- a throttle asked while stopped, and what became of it
#
# THE STOPPED PATH CANNOT WAIT FOR ITS OWN MARK: nothing reads its line while it would wait.
# It answered `pending` and forgot, so a switch that never landed stayed pending for ever and
# every timing taken afterwards described a speed nobody had asked for. It now leaves a
# record, and the next survey reads it -- the shape the tally's removal already has.


def test_a_throttle_that_landed_leaves_no_row_because_it_is_not_news(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE COMMON CASE COSTS NOTHING AND SAYS NOTHING. A switch that worked is not a finding,
    and a row for it would be one more thing every caller learns to skip."""
    ses = _channel(monkeypatch, tmp_path)
    out = s.throttle(on=True)
    assert out["pending"] is True and out["mark"] == "MAME_MCP_THROTTLE#1", out
    assert mstate.STATE.throttles_pending, "the record is what a later call reads"
    # The console reads the line on the next call's step, and the script logs its mark.
    ses.marks[1] = ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=101"]
    ses.answers = {1: ses.sentinel(1), 2: b"7\n" + ses.sentinel(2)}
    later = s.lua("print(7)", seconds=1.0)
    assert "throttles_not_applied" not in later["session"], later["session"]
    assert mstate.STATE.throttles_pending == [], "the record goes with the answer"



def test_status_lists_a_throttle_while_it_waits_and_drops_it_once_its_mark_is_logged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WAITING AND LANDED ARE BOTH VISIBLE, on one channel. The list is always there, so an
    empty one says somebody looked; a switch waiting is a row in it, and a switch that landed
    is its row leaving. Without it the only way to learn either was a second channel: a Lua
    read of `manager.machine.video.throttled` and the mark in the emulator's log."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    first = s.status()
    assert first.get("throttles_pending") == [], first
    s.throttle(on=True)
    assert s.status()["throttles_pending"] == [{"mark": "MAME_MCP_THROTTLE#1", "on": True}]
    # THE MARK IS LOGGED WITH NO STOP SINCE: `status` reads what is already in the log rather
    # than answering as of the last stop, which would call a landed switch still waiting.
    with open(ses.scratch / "error.log", "a") as log:
        log.write("[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=101\n")
    out = s.status()
    assert out["throttles_pending"] == [], out
    assert "throttles_not_applied" not in out["session"], out["session"]
    assert mstate.STATE.throttles_pending == [], "the record goes with the answer"

def test_a_throttle_whose_mark_never_comes_is_reported_and_keeps_being_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE DEFECT ITSELF. The console worked its way past the line and logged no mark, so the
    switch was never applied. It LATCHES: the declaration it would otherwise hang from is
    already answered, so a caller who does not happen to ask again would never hear of it,
    and every measurement they take meanwhile is at the wrong speed."""
    ses = _channel(monkeypatch, tmp_path)
    s.throttle(on=True)
    ses.answers = {1: ses.sentinel(1), 2: b"7\n" + ses.sentinel(2)}   # no marks[1]: no mark
    out = s.lua("print(7)", seconds=1.0)
    rows = out["session"]["throttles_not_applied"]
    assert [r["mark"] for r in rows] == ["MAME_MCP_THROTTLE#1"], out["session"]
    assert rows[0]["asked"] is True and rows[0]["machine_reports"]["available"] is False, rows
    assert "NEVER applied" in rows[0]["why"], rows
    # AND AGAIN on the next reply, which is the whole point of latching.
    ses.answers[3] = b"8\n" + ses.sentinel(3)
    again = s.lua("print(8)", seconds=1.0)
    assert again["session"]["throttles_not_applied"] == rows, again["session"]


def test_a_throttle_still_in_the_pipe_is_pending_and_not_yet_a_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE CONTROL, and without it the row would fire on every stopped throttle ever asked.
    Until the console has worked past the line the `pending` the caller was given is TRUE: the
    console may simply not have read the line. A row here would be a false alarm about a switch
    that is about to land."""
    ses = _channel(monkeypatch, tmp_path)
    s.throttle(on=True)
    assert "throttles_not_applied" not in menvelope.envelope({})["session"]
    # A survey with the line still unread: the console has answered nothing at or past it.
    running.survey(ses, ses.scratch)  # type: ignore[arg-type]
    assert mstate.STATE.throttles_pending, "still waiting, and still honestly pending"
    assert "throttles_not_applied" not in menvelope.envelope({})["session"]
    # AND THE BOUNDARY ITSELF, which is where an off-by-one lives: the console answering the
    # line BEFORE this one leaves it pending; answering THIS one is what makes the mark due.
    mstate.STATE.lua_answered = mstate.STATE.throttles_pending[0]["seq"] - 1
    running.survey(ses, ses.scratch)  # type: ignore[arg-type]
    assert mstate.STATE.throttles_pending, "the call before it is not past it"
    mstate.STATE.lua_answered = mstate.STATE.throttles_pending[0]["seq"]
    running.survey(ses, ses.scratch)  # type: ignore[arg-type]
    assert menvelope.envelope({})["session"]["throttles_not_applied"], "at its own number it is due"


def test_an_older_pending_switch_is_not_answered_by_a_younger_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`MAME_MCP_THROTTLE#1` IS A SUBSTRING OF `MAME_MCP_THROTTLE#10`, and a caller who asks
    for several switches while stopped reaches two digits without doing anything unusual. Read
    with a bare substring test, switch #1 would be answered off switch #10's line, and it
    fails in the worst direction available: #1's own line is missing precisely BECAUSE it
    never ran, so a younger line that AGREES makes it vanish with no row at all."""
    _channel(monkeypatch, tmp_path)
    mstate.STATE.throttles_pending = [{"mark": "MAME_MCP_THROTTLE#1", "on": True, "seq": 1},
                                      {"mark": "MAME_MCP_THROTTLE#10", "on": True, "seq": 10}]
    mstate.STATE.lua_answered = 10
    mstate.settle_throttles(["[luaengine] MAME_MCP_THROTTLE#10 throttled=true frame=50"])
    assert mstate.STATE.throttles_pending == [], "both records were judged"
    rows = mstate.STATE.throttles_not_applied
    assert [r["mark"] for r in rows] == ["MAME_MCP_THROTTLE#1"], (
        "#10 landed and says nothing; #1 never ran and has to say so")
    assert rows[0]["machine_reports"]["available"] is False, "nothing from #10's line"


def test_a_wrappers_marks_close_the_digits_of_their_number(tmp_path: Path) -> None:
    """THE SAME AXIS ON THE LUA WRAPPERS' SIDE. `input`, `record` and `throttle` read their
    own marks back off `error.log`, and `#1` is a substring of `#10`: the digits have to be
    closed where the lines are SELECTED, so no caller's safety rests on the suffix it happens
    to filter with or on its mark being the newest in the window."""
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
    something is already wrong. A row visible only from the tool whose survey earned it would
    be a row most callers never see."""
    ses = _channel(monkeypatch, tmp_path)
    s.throttle(on=True)
    ses.answers = {1: ses.sentinel(1), 2: b"7\n" + ses.sentinel(2)}
    s.lua("print(7)", seconds=1.0)
    assert mstate.STATE.throttles_not_applied, "the row is earned"
    told = s.status()
    assert told["session"]["throttles_not_applied"][0]["mark"] == "MAME_MCP_THROTTLE#1", told
    refusal = refused("", s.read_memory(ref="zzz_no_such_symbol", length=2))
    assert refusal["session"]["throttles_not_applied"] == told["session"][
        "throttles_not_applied"], "a refusal carries it too"


def _closed_after_the_mark(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                           mark: str) -> dict[str, Any]:
    """A throttle asked while stopped, its mark logged with no survey since, then `close`."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    assert s.throttle(on=True)["pending"] is True
    ses.answers[1] = ses.sentinel(1)
    with open(ses.scratch / "error.log", "a") as log:
        log.write(mark + "\n")
    out: dict[str, Any] = s.close()
    return out


def test_close_judges_a_throttle_whose_mark_disagrees_before_the_scratch_goes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE LAST REPLY JUDGES TOO. The mark lives in the scratch's error log, which `close`
    deletes, so `close` judges every throttle still pending against it first and its reply
    names one that did not land."""
    out = _closed_after_the_mark(monkeypatch, tmp_path,
                                 "[luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=101")
    rows = out["session"].get("throttles_not_applied")
    assert rows and [r["mark"] for r in rows] == ["MAME_MCP_THROTTLE#1"], out["session"]
    assert rows[0]["asked"] is True and rows[0]["machine_reports"] is False, rows


def test_close_judges_a_throttle_whose_line_only_its_own_drain_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE ORDER IS THE CONTRACT: a line still in the pipe at `close` runs in its drain, so the
    settlement comes after the drain, or it judges a log the mark has not reached yet."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    assert s.throttle(on=True)["pending"] is True
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=101"]}
    ses.answers[1] = ses.sentinel(1)
    out = s.close()
    assert out["console_drained"] == 1, out
    rows = out["session"].get("throttles_not_applied")
    assert rows and rows[0]["machine_reports"] is False, out["session"]


def test_close_says_nothing_of_a_throttle_that_landed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE CONTROL: a switch whose mark agrees is not news at `close` either."""
    out = _closed_after_the_mark(monkeypatch, tmp_path,
                                 "[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=101")
    assert "throttles_not_applied" not in out["session"], out["session"]


def test_a_machine_that_reports_the_opposite_switch_is_a_row_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE DISAGREEMENT THE RUNNING PATH REFUSES ON, reached by a caller who could not wait
    for it. It cannot be a refusal here, because the call that finds it asked about something
    else entirely; it is the same fact carried to the caller a different way."""
    ses = _channel(monkeypatch, tmp_path)
    s.throttle(on=False)
    ses.marks[1] = ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=101"]
    ses.answers = {1: ses.sentinel(1), 2: b"7\n" + ses.sentinel(2)}
    out = s.lua("print(7)", seconds=1.0)
    row = out["session"]["throttles_not_applied"][0]
    assert row["asked"] is False and row["machine_reports"] is True, row
    assert "not the one this session asked for" in row["why"], row


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
    # A record whose script answered and logged no mark at all, not even the `armed` line it
    # writes as it is evaluated (the first line is read on the first frame, this one on the
    # second): the log lost the marks, and "not begun" would be false.
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
    monkeypatch.setattr(mstate.STATE, "system", "radendur")
    folder = ses.scratch / "sta" / "radendur"
    folder.mkdir(parents=True)
    (folder / "theirs.sta").write_bytes(STA_HEAD)
    out = s.state_load(name="theirs")
    assert out["status"] == "ok" and out["verified"]["available"] is False
    assert "did not write" in out["verified"]["why"]
    assert out["summary"].startswith(
        "state_load theirs: rom_check unavailable, verified unavailable")
    # A load after which the ROM check fails: refused, never a traceback.
    rom = tmp_path / "rom.bin"
    rom.write_bytes(bytes(64))
    monkeypatch.setattr(mstate.STATE, "reference", (rom, 0, 0))

    def lying(rom_: bytes, addr: int, n: int = 16, base: int = 0, *,
               thread: int) -> None:
        raise g.Mismatch("the reference bytes differ")

    monkeypatch.setattr(ses, "self_check", lying)
    assert refused("ROM check failed", s.state_load(name="theirs"))["code"] == "readback_refused"
    # A frame the console cannot answer at the save: recorded as None, not a crash.
    monkeypatch.setattr(mstate.STATE, "reference", None)
    def no_frame(command: str, timeout: float = 10.0) -> str:
        (folder / "noframe.sta").write_bytes(STA_HEAD)
        return "x"

    monkeypatch.setattr(ses, "monitor", no_frame)
    assert s.state_save(name="noframe")["frame"] == {"available": False,
                                                     "why": mstate.FRAME_UNREAD_WHY}
    # A CHANNEL that fails during the re-check is not a mismatch: it latches, as it would
    # under any other tool, instead of reading as a refusal the next call could ignore.
    monkeypatch.setattr(mstate.STATE, "reference", (rom, 0, 0))

    def silent(rom_: bytes, addr: int, n: int = 16, base: int = 0, *, thread: int) -> None:
        raise g.Timeout("no answer to the read")

    monkeypatch.setattr(ses, "self_check", silent)
    monkeypatch.setattr(mstate.STATE, "ses", ses)      # the latch lands on the live session
    out = refused("no answer to the read", s.state_load(name="theirs"))
    assert out["code"] == "session_broken" and getattr(ses, "broken", None), out


# ----------------------------------------------------------- the waits the owner watches

class _SlowExit:
    """A process that leaves `after` seconds from now, whatever it is sent: what `close`
    waits on, sliced so the line can be painted."""

    pid = 77

    def __init__(self, after: float) -> None:
        self.gone_at = time.monotonic() + after

    def poll(self) -> int | None:
        return 0 if time.monotonic() >= self.gone_at else None

    def wait(self, timeout: float | None = None) -> int:
        time.sleep(min(timeout or 0.0, 0.1))
        code = self.poll()
        if code is None:
            raise subprocess.TimeoutExpired("mame", timeout or 0)
        return code

    def kill(self) -> None:
        self.gone_at = 0.0


def test_close_reports_its_progress_while_mame_takes_its_time(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """`close` blocking in `proc.wait(timeout)` and painting nothing makes a quit that takes
    seconds look like a hung server. The control: a process already gone reports nothing."""

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

    from test_server import _boot_args, _stub_boot

    image = bytes(range(256)) * 64
    ses = _stub_boot(monkeypatch, tmp_path, image, 0)
    ready_at = time.monotonic() + 2.2

    def slow_connect() -> None:
        if time.monotonic() < ready_at:
            raise OSError("connection refused")

    ses.dial = slow_connect  # type: ignore[method-assign]
    ticks: list[str] = []
    monkeypatch.setattr(s, "_progress", lambda ctx: (lambda p, t, m: ticks.append(m)))
    out = s.start(**_boot_args(tmp_path, image), seconds=5.0)
    try:
        assert out["status"] == "ok", out
        assert ticks and "waiting for the gdbstub on port" in ticks[0], ticks
    finally:
        s.close()


def test_start_and_close_carry_the_clients_context_to_their_waits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Through the TOOLS, with a real context: the two waits the owner watches longest
    reach `report_progress` from the worker thread the SDK runs them in. A `ctx` dropped
    at either tool's signature would leave the two body tests above green."""
    import time

    import anyio
    from test_server import _boot_args, _stub_boot

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
            lambda: s.start(**_boot_args(tmp_path, image), seconds=6.0, ctx=_Ctx()))
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
    """`start` kills the session and deletes the scratch when the gdbstub never listens, so
    the refusal is the only place MAME's last lines survive: a plugin it could not find, a
    fatal error. Measured need: a repository's session saw four `session_broken` refusals
    with no way to tell why."""
    from test_server import _boot_args, _stub_boot, _StubProcess

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
    out = s.start(**_boot_args(tmp_path, image), seconds=0.5)
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert "Console plugin not found" in out["stdout_tail"]
    assert out["session"]["alive"] is False, "the failed start owns nothing"


def test_the_stdout_tail_of_a_session_with_no_scratch_is_empty() -> None:
    assert launch._stdout_tail(None) == ""


def test_a_line_the_run_did_not_evaluate_is_bought_with_one_step_and_the_frames_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Measured on radendur: five recordings in a row, all exact on one run, and on another
    the last two came back PENDING with the chunk still in the pipe after the whole run.
    One step evaluates it on the way into the debugger; the frames are then bought again so
    the notifier finishes, and the reply is the finished recording, not a pending note."""
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
    """A `throttle` asked on a stopped machine leaves its line in the pipe, and the console
    reads ONE line each time its hook runs: where nothing reads it first, `lua`'s single step
    buys the THROTTLE's evaluation and its own answer never comes, measured as `wait_expired`
    with the session altered. So `lua` counts the lines ahead of its own and steps once for
    each."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: ses.sentinel(1), 2: b"radendur\n" + ses.sentinel(2)}
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=100"]}
    queued = s.throttle(on=True)
    assert queued["status"] == "ok" and queued["pending"] is True, queued
    out = s.lua("print(emu.romname())", seconds=0.5)
    assert out["status"] == "ok", out
    assert out["output"] == "radendur\n" and out["evaluated_by"] == "2 steps", out
    assert out["lines_ahead"] == 1 and ses.stepped == 2, out
    keys = list(out)
    assert keys.index("lines_ahead") < keys.index("output") < keys.index("how"), keys
    # With the pipe drained, the next call costs the one step it always did.
    ses.answers[3] = b"1\n" + ses.sentinel(3)
    again = s.lua("print(1)", seconds=0.5)
    assert again["evaluated_by"] == "one step" and again["lines_ahead"] == 0
    assert ses.stepped == 3


def test_a_stop_the_reader_had_not_taken_the_line_for_is_followed_by_one_more_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The console's reader is a THREAD (`plugins/console/init.lua`, `emu.thread`), and the
    periodic hook, run once at a stop, returns without evaluating while that thread is still
    taking the line. Measured on radendur: a signature sent right after another expired with
    the line in the pipe, and ONE more step landed its answer at once. So a step whose answer
    does not come within the reader's window is followed by another, said in the reply, up
    to a cap that keeps a reader that never hands the line over a refusal."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s_: slept.append(s_))
    ses.reader_late = 1
    ses.answers = {1: b"MAME_MCP_SIG w=320 h=224 grid=8 sig=2140790385\n" + ses.sentinel(1)}
    out = s.screen_signature(seconds=1.0)
    assert out["status"] == "ok" and out["signature"] == 2140790385, out
    assert out["evaluated_by"] == "2 steps" and out["reader_steps"] == 1, out
    assert out["lines_ahead"] == 0 and ses.stepped == 2 and out["session"]["altered"] is False
    # THE SETTLE: the first sleep of the call is the reader's settle, after the write and
    # before the first step (the double's step count says the steps came after).
    assert slept and slept[0] == transport.READER_SETTLE_S, slept[:3]
    # A reader that never hands the line over inside the bound: the steps are capped and
    # the refusal counts them, so a stalled reader is not stepped through forever. The cap
    # is set to one so the case does not race the bound on a loaded host.
    monkeypatch.setattr(transport, "READER_STEPS_MAX", 1)
    ses.reader_late = 20
    out = refused("reader", s.screen_signature(seconds=0.4))
    assert out["reader_steps"] == 1 and out["pending"] is True, out
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


def test_a_dead_reader_and_the_chunk_the_console_ran_again_are_said_in_the_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MAME's console thread is unsafe by its own admission (`luaengine.cpp`): measured on
    radendur, the reader died at start and the hook ran the PREVIOUS chunk again, its
    sentinel printed twice, before a new reader took the line. A chunk that wrote has then
    written twice, so every reply counts the deaths and names the chunks run again, and
    a reply with nothing to say carries the zeros rather than nothing."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    sig = b"MAME_MCP_SIG w=320 h=224 grid=8 sig=%d\n"
    ses.answers = {1: sig % 11 + ses.sentinel(1), 2: sig % 22 + ses.sentinel(2),
                   3: b"7\n" + ses.sentinel(3)}
    out = s.screen_signature(seconds=1.0)
    assert out["thread_errors"] == 0 and out["console_reruns"] == 0 and "note" not in out, out
    ses.reader_dies = 1
    out = s.screen_signature(seconds=1.0)
    assert out["status"] == "ok" and out["signature"] == 22, out
    assert out["thread_errors"] == 1 and out["console_reruns"] == 1, out
    assert out["reader_steps"] == 1 and "AGAIN" in out["note"], out
    # The raw form says the same, where it matters most: its script may have written.
    ses.reader_dies = 1
    out = s.lua("print(7)", seconds=1.0)
    assert out["status"] == "ok" and out["output"] == "7\n", out
    assert out["console_reruns"] == 1 and out["thread_errors"] == 1, out
    # And a wrapper's run, which evaluates by frames: the rerun is on its reply too.
    ses.answers[4] = ses.sentinel(4)
    ses.marks[4] = [m.replace("#3", "#4") for m in _marks_of("MAME_MCP_INPUT#3")]
    ses.reader_dies = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and out["console_reruns"] == 1, out
    assert out["thread_errors"] == 1 and out["resent"] == 0, out
    # A run cut short keeps BOTH notes: the tool's own and the console's.
    ses.answers[5] = ses.sentinel(5)
    ses.marks[5] = [_marks_of("MAME_MCP_INPUT#3 set")[0].replace("#3", "#5")]
    ses.reader_dies = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["released"] is False and "HELD" in out["note"], out
    assert out["console_reruns"] == 1 and "AGAIN" in out["note"]
    # The raw form with no output: the two notes do not collide.
    ses.answers[6] = ses.sentinel(6)
    ses.reader_dies = 1
    out = s.lua("return 1", seconds=1.0)
    assert out["status"] == "ok" and "no output" in out["note"], out
    assert out["console_reruns"] == 1 and "AGAIN" in out["note"]


def test_a_line_legitimately_ahead_is_not_a_rerun_and_a_rerun_after_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `throttle`'s line, read by the step the next call spends for it, prints its sentinel
    once, for the first time, inside that call's window: not a rerun. The same sentinel
    printed again later, after its answer was consumed, is one."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: ses.sentinel(1), 2: b"radendur\n" + ses.sentinel(2),
                   3: b"1\n" + ses.sentinel(3)}
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=100"]}
    s.throttle(on=True)
    out = s.lua("print(emu.romname())", seconds=0.5)
    assert out["lines_ahead"] == 1 and out["console_reruns"] == 0 and out["thread_errors"] == 0
    ses.reader_dies = 1
    out = s.lua("print(1)", seconds=1.0)
    assert out["console_reruns"] == 1 and out["thread_errors"] == 1, out
    # A script printing the sentinel's text for a number never sent is its own business.
    ses.answers[4] = b"MAME_MCP_LUA_END#99\tfake\n" + ses.sentinel(4)
    out = s.lua('print("MAME_MCP_LUA_END#99\\tfake")', seconds=1.0)
    assert out["console_reruns"] == 0, out


def test_a_line_the_reader_died_holding_is_sent_again_once_and_the_reply_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Measured on radendur: the first line of a session was echoed, the reader died with
    "return value must be string", and no sentinel for it ever came: the script was never
    evaluated. Sending it again runs it once, which is what the caller asked for; twice is a
    refusal that says the script never ran, not one that calls it pending."""
    ses = _channel(monkeypatch, tmp_path)
    sig = b"MAME_MCP_SIG w=320 h=224 grid=8 sig=%d\n"
    ses.answers = {2: sig % 22 + ses.sentinel(2)}
    ses.reader_eats = 1
    out = s.screen_signature(seconds=1.0)
    assert out["status"] == "ok" and out["signature"] == 22, out
    assert out["resent"] == 1 and out["call"] == "MAME_MCP_LUA_END#2", out
    assert out["thread_errors"] == 1 and out["console_reruns"] == 0, out
    assert out["evaluated_by"] == "2 steps" and out["reader_steps"] == 0 and ses.stepped == 2
    # The next call costs one step: the eaten line is not counted as still ahead.
    ses.answers[3] = sig % 33 + ses.sentinel(3)
    out = s.screen_signature(seconds=1.0)
    assert out["evaluated_by"] == "one step" and out["lines_ahead"] == 0, out
    ses.reader_eats = 2
    out = refused("NEVER evaluated", s.screen_signature(seconds=1.0))
    assert out["code"] == "reader_died" and out["pending"] is False and out["resent"] == 1, out
    assert out["thread_errors"] == 2 and out["console_reruns"] == 0, out
    # And the two lines it died holding are not phantom debt for the call after.
    ses.answers[6] = sig % 66 + ses.sentinel(6)
    out = s.screen_signature(seconds=1.0)
    assert out["lines_ahead"] == 0 and out["evaluated_by"] == "one step", out
    # The raw form says `resent` the same way.
    ses.answers[8] = b"9\n" + ses.sentinel(8)
    ses.reader_eats = 1
    out = s.lua("print(9)", seconds=1.0)
    assert out["status"] == "ok" and out["resent"] == 1 and out["output"] == "9\n", out
    # A wrapper's line eaten on its run is sent again and the run bought again: the
    # resent chunk is the same text, so its marks carry the FIRST number (the tag is in
    # the script) while the double keys them by the resent sentinel's number.
    ses.marks[10] = [m.replace("#3", "#9") for m in _marks_of("MAME_MCP_INPUT#3")]
    ses.answers[10] = ses.sentinel(10)
    ses.reader_eats = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and out["resent"] == 1 and out["released"] is True, out
    ses.reader_eats = 2
    out = refused("NEVER evaluated", s.input(port=":P1", field="Coin 1", frames=4))
    assert out["code"] == "reader_died" and out["resent"] == 1 and out["drain_steps"] == 0, out


def test_a_resend_the_bound_has_no_room_for_is_refused_not_taken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One bound for the whole call: the first run spent it, the reader then died holding the
    line, and a second run would stretch the call past what was asked, so it is refused as
    `wait_expired`, pending, instead of taken."""
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
    """The run spent the whole bound, the step evaluated the line and its answer came in on
    the last look, and the frames bought again have no room left. The refusal says the
    script WAS evaluated and not pending, never that its answer is not in."""
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


class _DiesMidWait:
    """MAME gone while a call waits for the console. `poll` answers None until the line has
    been sent and its step spent, then the code the crash left, which is what separates a
    process that DIED from a console that is merely slow."""

    pid = 4243

    def __init__(self, stdin: Any, after: int) -> None:
        self.stdin, self.after, self.polls = stdin, after, 0

    def poll(self) -> int | None:
        self.polls += 1
        return None if self.polls <= self.after else -11


def test_a_call_whose_emulator_died_while_it_waited_says_so_instead_of_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`wait_expired` says the line is still pending in the pipe, to be evaluated when the
    console's hook next runs. About a process that is GONE that is not a bound expiring,
    it is a sentence describing a machine that no longer exists, and the caller waits the
    whole bound to be told to wait some more. MAME's own Lua thread crashes (`luaengine.cpp`,
    `thread_context::start`, its own FIXME) and that is not ours to fix; describing a dead
    process as a busy one is."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    monkeypatch.setattr(mstate.STATE, "proc", _DiesMidWait(ses.stdin, after=1))
    ses.reader_late = 20
    out = refused("exited with code -11", s.screen_signature(seconds=5.0))
    assert out["code"] == "session_broken" and out["exit_code"] == -11, out
    assert "pending" not in out["message"], out
    assert "was stepped 1 time for it" in out["message"], out
    assert out["lines_ahead"] == 0 and out["call"] == "MAME_MCP_LUA_END#1", out
    # THE CONTROL: a process that is still there over the same wait refuses as it always
    # did, so the code above is the death speaking and not every expired bound.
    monkeypatch.setattr(mstate.STATE, "proc", _PipeProcess(ses.stdin, ses))
    out = refused("no sentinel for the line", s.lua("print(1)", seconds=0.3))
    assert out["code"] == "wait_expired", out


def test_every_console_wait_says_the_emulator_died_rather_than_calling_it_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE SAME LIE, TOLD BY THREE LOOPS. Each bound here expires into words about a machine
    that will execute again -- "still pending in the pipe", "the switch is still pending" --
    and about a process that is GONE those describe a busy machine, so the caller sits out
    the whole bound to be told to wait longer. `evaluate` has its own case; these are the two
    that `input`, `record` and `throttle` reach.

    THE SWALLOW IS THE POINT OF THE SECOND HALF. `_answer_or_none` exists to turn "no answer
    yet" into None so its callers can run more frames, and it caught EVERY refusal, so a
    liveness check inside `await_answer` was unreachable from `input` and `record`: the check
    would have been there, the tests for it green at the unit, and the tool would still have
    said pending. It now lets a broken session through and keeps swallowing the other.
    """
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)

    # THE CONTROL FIRST, and it is what keeps the assertions below about the death rather
    # than about any refusal at all: a live emulator that simply has not answered yet still
    # reaches the pending path, with the run's own words and no refusal.
    ses.answers = {}
    out = s.input(port=":P1", field="Coin 1", frames=4, seconds=1.0)
    assert out["status"] == "ok" and out.get("released") is not True, out
    assert "note" in out, out

    # `input` and `record` go through `_answer_or_none`, which is where the swallow was.
    monkeypatch.setattr(mstate.STATE, "proc", _DiesMidWait(ses.stdin, after=0))
    out = refused("exited with code -11", s.input(port=":P1", field="Coin 1", frames=4,
                                                  seconds=1.0))
    assert out["code"] == "session_broken" and out["exit_code"] == -11, out
    assert "pending" not in out["message"], out

    # `throttle` on a RUNNING machine waits for its own mark, and said the switch was still
    # pending about an emulator that had gone.
    ses.running = True
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)
    monkeypatch.setattr(mstate.STATE, "proc", _DiesMidWait(ses.stdin, after=0))
    out = refused("exited with code -11", s.throttle(on=False, seconds=1.0))
    assert out["code"] == "session_broken" and out["exit_code"] == -11, out
    assert "still pending" not in out["message"], out


def test_a_line_the_console_refused_and_that_was_sent_again_is_named_in_the_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE SECOND SHAPE OF A LOST LINE, through a real call: the console reports the line's
    own top-level failure and carries on, which leaves no dead reader and no duplicate
    sentinel behind. The line is resent and runs, so `thread_errors` and `console_reruns` are
    both empty while `resent` and `session.console.lost` say 1, and the prose has to say the
    same thing the counters do: a reply with a counter at 1 and no note is two answers."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    ses.console_refuses = 1
    out = s.lua("print(7)")
    assert out["status"] == "ok" and out["output"].strip() == "7", out
    assert out["resent"] == 1 and out["session"]["console"]["lost"] == 1, out
    assert out["thread_errors"] == 0 and out["console_reruns"] == 0, out
    note = out.get("note", "")
    assert "never evaluated" in note and "sent again (1 time)" in note, out
    assert "died" not in note and "AGAIN" not in note, out
    # THE CONTROL: the same call with nothing lost carries no note at all, so the note above
    # is the loss speaking and not a sentence every reply now carries.
    ses.answers[3] = b"8\n" + ses.sentinel(3)
    clean = s.lua("print(8)")
    assert clean["resent"] == 0 and "note" not in clean, clean

def test_screen_signature_hashes_a_grid_of_pixels_through_one_step_and_alters_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The 64-pixel signature a repo's own `nav-phase.lua` computes, as a typed tool, so a
    golden's "is the race painting" needs no raw `lua` (altered always).
    The script prints the grid it sampled and the hash; the reply carries both, and the
    session is NOT altered: a pixel is read, nothing is written."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: b"MAME_MCP_SIG w=320 h=224 grid=8 sig=2140790385\n" + ses.sentinel(1)}
    out = s.screen_signature()
    assert out["status"] == "ok", out
    assert out["signature"] == 2140790385 and out["grid"] == 8
    assert out["width"] == 320 and out["height"] == 224 and out["evaluated_by"] == "one step"
    assert out["session"]["altered"] is False and ses.stepped == 1
    assert out["call"] == "MAME_MCP_LUA_END#1" and out["cell"]["available"] is False
    assert out["origin"]["available"] is False
    assert out["summary"] == "screen_signature 8x8: 2140790385", out["summary"]
    sent = ses.stdin.getvalue().decode()
    assert "screen:pixel(" in sent and "% 0x7fffffff" in sent, "the repo's own formula"
    refused("grid", s.screen_signature(grid=1))
    refused("grid", s.screen_signature(grid=65))
    # THE REPO'S OWN LATTICE: a fixed cell from a fixed offset, which need not be the
    # centred one, declared and sent as such; half a lattice is refused.
    ses.answers[2] = b"MAME_MCP_SIG w=320 h=224 grid=8 sig=896136150\n" + ses.sentinel(2)
    out = s.screen_signature(cell=[40, 28], origin=[8, 8])
    assert out["status"] == "ok" and out["cell"] == [40, 28] and out["origin"] == [8, 8], out
    assert "40, 28, 8, 8" in ses.stdin.getvalue().decode()
    refused("together", s.screen_signature(cell=[40, 28]))
    refused("above zero", s.screen_signature(cell=[0, 28], origin=[8, 8]))
    # A LATTICE THAT LEAVES THE SCREEN would fold MAME's off-screen zeros into a number that
    # never changes: the script says so with the screen's size, and it is refused.
    ses.answers[3] = b"MAME_MCP_SIG_OFFSCREEN w=320 h=224\n" + ses.sentinel(3)
    out = refused("leaves the 320x224 screen", s.screen_signature(cell=[100, 28], origin=[0, 0]))
    assert out["code"] == "bad_argument" and "thread_errors" in out, out
    # An expiry says the machine moved, that NOTHING was altered, and under which sentinel
    # the answer will land (a repo read "is altered" beside `altered: false`).
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.2)
    out = refused("alters nothing", s.screen_signature(seconds=0.2))
    assert out["call"] == "MAME_MCP_LUA_END#4" and out["session"]["altered"] is False


# ------------------------------------------------------------------------------ drive

def test_drive_marks_the_emulator_log_acts_verifies_and_looks_from_the_mark(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """LOOK, ACT, VERIFY for an arcade board: the emulator log (`error.log`,
    what the driver and the scripts `logerror`) is marked BEFORE the act, the act runs as
    `perform` runs it, the overall `expect` is read from that mark (once, when the act left
    the machine stopped: a stopped machine logs nothing more), and the LOOK is what landed
    since the mark, filtered and cut. A stale line before the mark is neither."""
    ses = _channel(monkeypatch, tmp_path)
    (ses.scratch / "error.log").write_text("[luaengine] MAME_MCP_INPUT#0 release frame=1 "
                                           "port_held=00000000\n")   # STALE, before the mark
    ses.answers[1] = _captured(3)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.drive(act=[{"op": "input", "port": ":P1", "field": "Coin 1", "frames": 4}],
                  expect=r"release frame=\d+", pattern="MAME_MCP_INPUT", limit=10)
    assert out["status"] == "ok", out
    assert out["act"]["steps_completed"] == 1, out["act"]
    assert out["act"]["failed"]["available"] is False, out["act"]
    assert out["verify"]["seen"] is True and "release frame=" in out["verify"]["line"], out
    looked = out["looked"]["emulator"]
    assert looked["available"] is True and looked["since_mark"] > 0, looked
    assert (looked["lines_written"], looked["lines_total"], len(looked["lines"])) == (2, 2,
                                                                                      2), looked
    assert all("#1" in ln for ln in looked["lines"]), "the stale #0 line is before the mark"
    assert out["summary"] == "drive: effect seen, TARGET", out["summary"]
    # The cut: `lines=1` keeps the LAST matching line, the counts say what was cut.
    ses.answers[2] = _captured(3).replace(b"#3", b"#2")
    ses.marks[2] = [m.replace("#3", "#2") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.drive(act=[{"op": "input", "port": ":P1", "field": "Coin 1", "frames": 4}],
                  pattern="release", limit=1)
    looked = out["looked"]["emulator"]
    assert (looked["lines_written"], looked["lines_total"], len(looked["lines"])) == (2, 1,
                                                                                      1), looked
    assert "release" in looked["lines"][0]
    assert out["verify"]["checked"] is False and "no `expect`" in out["verify"]["why"]


def test_drive_reports_a_miss_a_failed_act_and_refuses_what_it_cannot_do(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = _captured(3)
    ses.marks[1] = [m.replace("#3", "#1") for m in _marks_of("MAME_MCP_INPUT#3")]
    out = s.drive(act=[{"op": "input", "port": ":P1", "field": "Coin 1", "frames": 4}],
                  expect="never logged", seconds=1)
    assert out["status"] == "INVALID" and out["code"] == "wait_stopped", out
    assert out["verify"]["seen"] is False and "STOPPED" in out["verify"]["why"], out["verify"]
    assert out["act"]["steps_completed"] == 1 and "emulator" in out["looked"]
    assert out["summary"].startswith("drive: INVALID (wait_stopped)"), out["summary"]
    # A failed step ends the act before any verification, with the account and the look.
    out = s.drive(act=[{"op": "run_for", "frames": -1}], expect="x")
    assert out["status"] == "INVALID" and out["act"]["steps_completed"] == 0, out
    # Refused before anything moves: an empty act, an unknown op, a bad pattern, seconds
    # without expect, a bound out of range.
    bad: dict[str, Any]
    moved = ses.commands.count("gvblank")
    for bad in ({"act": []}, {"act": [{"op": "no_such_op"}]},
                {"act": [{"op": "status"}], "pattern": "("},
                {"act": [{"op": "status"}], "seconds": 3},
                {"act": [{"op": "status"}], "expect": "x", "seconds": 0},
                {"act": [{"op": "status"}], "limit": 0}):
        got = s.drive(**bad)
        assert got["status"] == "INVALID" and got["code"] == "bad_argument", (bad, got)
    assert ses.commands.count("gvblank") == moved, "a refusal moves nothing"


def test_lua_refuses_a_pipe_too_far_ahead_and_says_how_a_frame_drains_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Nine lines nobody answered would cost nine steps and a pc nine instructions on; a
    frame reads them all, so the call refuses naming it, and sends nothing."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "lua_seq", transport.PIPE_STEPS_MAX + 1)
    out = refused("ahead", s.lua("print(1)", seconds=0.2))
    assert out["code"] == "bad_argument" and "run_for" in out["message"]
    assert ses.stdin.getvalue() == b"" and ses.stepped == 0


def test_a_script_printing_the_sentinels_text_cannot_poison_the_count_of_lines_ahead(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The raw `lua` prints what it likes, the sentinel's text included, and a number this
    server never sent must not read as "everything is answered": the next call would then
    buy no step. Only numbers up to what was sent count, and `ahead` is never negative."""
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


def test_screen_signature_refuses_its_bound_a_raising_script_and_a_missing_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    refused("not a bound", s.screen_signature(seconds=0))
    ses.answers[1] = ses.sentinel(1, ok=False, error="no screen")
    out = refused("raised", s.screen_signature())
    assert out["code"] == "unexpected_answer"
    ses.answers[2] = b"something else\n" + ses.sentinel(2)
    out = refused("no signature line", s.screen_signature())
    assert out["code"] == "unexpected_answer"


# ------------------------------------------------------ the wrappers and the pipe's floor

def test_a_queued_wrapper_lets_the_reader_take_the_line_before_it_advances(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE WINDOW THAT KILLS THE READER, measured on a wrapper that runs frames rather than
    steps: the machine is advanced no sooner than `READER_SETTLE_S` after the line reached the
    pipe, because a frame run inside that window loses the reader like a step does."""
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


def _settles(monkeypatch: pytest.MonkeyPatch, ses: _ChannelSession) -> list[tuple[float, int, int]]:
    """Every sleep, with what the pipe held and how many steps the machine had taken when
    it began: a settle is a sleep of `READER_SETTLE_S` that starts with the line already in
    the pipe and the machine not yet moved for it. The settle is given a value no other wait
    has (`POLL_S` shares its default), so a sleep of the wrong constant cannot pass for it."""
    monkeypatch.setattr(transport, "READER_SETTLE_S", 0.0137)
    slept: list[tuple[float, int, int]] = []
    monkeypatch.setattr(time, "sleep",
                        lambda s_: slept.append((s_, len(ses.stdin.getvalue()), ses.stepped)))
    return slept


def test_send_returns_only_after_the_reader_settle_that_follows_its_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The window that kills the reader is opened by the WRITE, so the function that writes
    owns the wait: every caller inherits it, and none can forget it."""
    ses = _channel(monkeypatch, tmp_path)
    slept = _settles(monkeypatch, ses)
    line, _seq = transport.send("print(1)")
    assert slept == [(transport.READER_SETTLE_S, len(line) + 1, 0)], slept


def test_a_throttle_asked_while_stopped_settles_the_reader_after_its_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The stopped path returns `pending` at once, and the next call moves the machine: with
    no settle between the two, that call's step lands inside the window this line opened."""
    ses = _channel(monkeypatch, tmp_path)
    slept = _settles(monkeypatch, ses)
    out = s.throttle(on=False)
    assert out["pending"] is True, out
    assert slept == [(transport.READER_SETTLE_S, len(ses.stdin.getvalue()), 0)], slept


def test_a_lua_call_settles_the_reader_once_before_its_first_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ONE OWNER: a caller that still waits on its own after `send` doubles the settle, and
    a wait nobody owns is the one that goes missing on the next path added."""
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
    """A `throttle` asked while stopped leaves its line in the pipe. `lua` counts those and
    steps once for each before its own; the wrappers did not, so their FRAMES were spent
    draining somebody else's line and the input lost its own release frame (measured live on
    LineUp: `released: false`, the field left held). And the reply carried no `lines_ahead`,
    so no caller could see the pipe filling before tripping over it."""
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
    assert "reader_steps" in out, out
    assert 1 not in mstate.STATE.lua_pending and out["session"]["console"]["lost"] == 0, (
        "settled by its sentinel: it ran, and nothing is lost")
    # The input's own frames were its own: the field was released, not left held.
    assert out["released"] is True, out


def test_a_wrapper_whose_reader_died_before_the_echo_says_so_and_counts_nothing_lost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE DEATH NOTHING COULD PIN ON THE LINE: no echo, so not `eaten`. The refusal says
    the death and that the line has not run YET: it stays pending, and nothing is counted
    lost that the log does not prove eaten."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    ses.reader_dead = True
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "INVALID", out
    assert out["code"] == "reader_died", out
    assert "may still run on a later reader" in out["message"], out
    assert "lost" not in out["message"], out
    assert out["pending"] is True and out["resent"] == 0 and out["lines_ahead"] == 0, out
    assert out["thread_errors"] == 1, out
    assert out["session"]["console"]["lost"] == 0 and mstate.STATE.lua_lost == 0, out
    assert transport.pending_lines(tmp_path) == 1, "the line is still ahead in the pipe"


def test_a_pending_line_a_later_reader_dies_holding_is_counted_lost_and_costs_no_drain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The line a death could not be pinned on stays ahead in the pipe until the log says
    otherwise. The next wrapper's first drain step hands it to a reader that dies holding it:
    counted lost once, and the drain stops there instead of stepping on for a line that will
    never answer (`ahead + PIPE_STEPS_MAX` steps before)."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    ses.reader_dead = True
    first = s.input(port=":P1", field="Coin 1", frames=4)
    assert first["code"] == "reader_died" and first["pending"] is True, first
    assert first["drain_steps"] == 0, first
    ses.reader_dead, ses.reader_eats = False, 1
    ses.answers = {2: _captured(3, as_seq=2)}
    ses.marks = {2: [m.replace("#3", "#2") for m in _marks_of("MAME_MCP_INPUT#3")]}
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and out["released"] is True, out
    assert (out["lines_ahead"], out["drain_steps"]) == (1, 1), out
    assert out["session"]["console"]["lost"] == 1 and mstate.STATE.lua_lost == 1, out
    transport.count_unread(ses.scratch)
    assert mstate.STATE.console_lines_lost == 1, "counted once, whoever reads the log again"


def test_a_wrapper_line_the_step_after_its_run_hands_to_a_dying_reader_is_lost_not_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The run evaluated nothing, and the one step after it gave the line to a reader that
    died holding it: the log proves it eaten, so the refusal says NEVER evaluated and counts
    it lost, rather than calling it pending and leaving it ahead for the next drain."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    ses.sluggish = 1000
    ses.reader_eats = 1
    out = refused("NEVER evaluated", s.input(port=":P1", field="Coin 1", frames=4))
    assert out["code"] == "reader_died" and out["pending"] is False, out
    assert out["session"]["console"]["lost"] == 1 and transport.pending_lines(ses.scratch) == 0, out


def test_a_throttle_line_a_drain_step_hands_to_a_dying_reader_stops_the_drain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every line sent is settled against the log, not only a wrapper's: a `throttle` left in
    the pipe and eaten by the drain's first step is lost, and the drain goes no further."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: _captured(3, as_seq=2)}
    ses.marks = {2: [m.replace("#3", "#2") for m in _marks_of("MAME_MCP_INPUT#3")]}
    assert s.throttle(on=True)["pending"] is True
    ses.reader_eats = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok" and (out["lines_ahead"], out["drain_steps"]) == (1, 1), out
    assert out["session"]["console"]["lost"] == 1, out


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
    assert (out["lines_ahead"], out["drain_steps"]) == (1, 1), out


def test_settling_the_pending_lines_survives_a_loss_that_settles_another_on_the_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`record_lost` reads the log again, and a log that grew meanwhile settles the rest from
    inside the first settlement: the outer pass must not find those gone from under it."""
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
    """A `throttle` left in the pipe costs the next wrapper a step before its own line, and
    the reply says so beside `lines_ahead`."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: ses.sentinel(1), 2: _captured(3, as_seq=2)}
    ses.marks = {1: ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=100"],
                 2: [m.replace("#3", "#2") for m in _marks_of("MAME_MCP_INPUT#3")]}
    assert s.throttle(on=True)["pending"] is True
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["status"] == "ok", out
    assert (out["lines_ahead"], out["drain_steps"]) == (1, 1), out
    keys = list(out)
    assert keys.index("lines_ahead") < keys.index("drain_steps") < keys.index("reader_steps")


def test_status_counts_the_lines_the_console_has_not_evaluated_and_close_drains_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A backlog left in the pipe is what MAME's Lua GC tears down at `quit` (SIGSEGV in
    `lua_engine::close`). So the count is READABLE before it bites, and `close`
    drains what it can and says what it could not."""
    ses = _channel(monkeypatch, tmp_path)
    # `status` answers off the session and the process, not off the `alive` gate the other
    # tests install, so both are wired here.
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
    """THE FALSE POSITIVE the death detector invites. `find_answer` hands back everything
    since the session's console mark, and that mark only moves when an answer is CONSUMED,
    so a `[LUA ERROR] in thread` the session already survived sits in the tail for ever. A
    detector reading the whole tail would call every later slow call a dead reader and tell
    the caller to throw a working session away. It looks only at what arrived after its own
    line was sent."""
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
    """A chunk sent again is a second write for a script that writes, which this channel
    promises never to leave silent. The resend was counted and then dropped on the one path
    that most needs it: the pending one."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    # The first send is TAKEN by the reader and never run (its echo, then the thread's
    # death); the resend is merely slow, because no answer is prepared for it, so the line
    # sits at the head of the pipe exactly as one the machine has not ticked for.
    ses.reader_eats = 1
    out = s.input(port=":P1", field="Coin 1", frames=4)
    assert out["pending"] is True, out
    assert out["resent"] == 1, out
    assert "sent 2 times" in out["note"] and "about the second" in out["note"], out


def test_close_does_not_step_a_running_machine_to_drain_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`throttle` is the one wrapper callable while the guest RUNS, and its own timeout
    leaves the line queued with the machine still running. `close` works on a running
    machine too, so the drain it now does would have stepped a machine that was mid-run:
    every other stepper in this package is behind a stopped gate. A running machine reads
    its own pipe frame by frame anyway, so there is nothing to buy: the count is reported
    and no step is spent."""
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
    """The raw form marks the session ALTERED on every call, a read included, because a
    Lua string can read a byte or rewrite RAM and the text does not say which. That is the
    honest default and it stays the default; the cost is that one `print` stamps a session
    that only ever read with "MODIFIED", and from then on the flag says nothing.

    So `read_only=True` is the CALLER'S DECLARATION, and it is recorded AS a declaration. It
    is not verified and it never could be, so it may not be silent: the session block counts
    the claims and names them as the caller's word, and a session carrying one can never be
    mistaken for one nothing was ever declared about."""
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


def test_the_drive_summary_reads_the_field_the_reply_actually_carries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE HALF OF A RENAME THAT GOES QUIET. `verify.verified` became `verify.checked`, and
    a one-line summary the client PAINTS still reading the old key would `.get()` a key
    nobody writes, get None, and announce "no expectation" for a drive that ran a check.

    SAID PLAINLY: on THIS server that middle branch is currently unreachable, because a
    check that ran and saw nothing returns INVALID and an INVALID summary is the refusal's.
    The key is still corrected, because dead code that lies is what a later change makes
    live. What is asserted here is the pair that IS reachable, so the branch is exercised in
    both directions rather than asserted about a path this server cannot take today."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    # The guest's own line, written where the emulator writes it AND WHEN it would: `drive`
    # marks the log, acts, then reads what landed SINCE the mark, so a line written before
    # the call is behind the mark and invisible by construction. The act's own step writes
    # it, which is what a real guest's act does.
    # No `expect`, and no `seconds` either: bounding a wait that will not happen is refused.
    none = s.drive(act=[{"op": "step", "count": 1}])
    assert none["verify"]["checked"] is False, none
    assert "no expectation" in none["summary"], none["summary"]
    stepper = ses.step

    def step_and_log() -> str:
        out = stepper()
        with open(ses.scratch / "error.log", "a") as log:
            log.write("[:maincpu] DRIVE_MARK here\n")
        return out

    monkeypatch.setattr(ses, "step", step_and_log)
    seen = s.drive(act=[{"op": "step", "count": 1}], expect="DRIVE_MARK", seconds=0.5)
    monkeypatch.setattr(ses, "step", stepper)
    assert seen["status"] == "ok" and seen["verify"]["checked"] is True, seen
    assert "effect seen" in seen["summary"], seen["summary"]


def test_a_lua_refused_for_somebody_elses_backlog_is_not_counted_as_a_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A CALL THAT NEVER REACHED THE CONSOLE IS NOT A CALL. `lua` stamps the session before
    it evaluates, and the pipe-depth refusal lived inside the evaluation: a call turned away
    for a backlog somebody ELSE left had already been counted, so the very reply that said
    INVALID also reported a write (or, with `read_only`, a claim) that never happened."""
    _channel(monkeypatch, tmp_path)
    for _ in range(transport.PIPE_STEPS_MAX + 1):          # a pipe nobody here filled
        transport.send("print(0)")
    refused_write = refused("still ahead", s.lua("print(1)"))
    assert refused_write["session"]["altered"] is False, refused_write["session"]
    assert refused_write["session"]["altering_writes"] == 0, refused_write["session"]
    refused_read = refused("still ahead", s.lua("print(1)", read_only=True))
    assert "read_only_claims" not in refused_read["session"], refused_read["session"]


def test_a_batch_refuses_a_class_in_fmt_before_a_single_step_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`perform` promises the WHOLE list is judged before the first step runs, and the tool's
    `@`-in-fmt refusal was not mirrored here: `vf.parse("ptr16@CODE")` succeeds, so the step
    passed validation and failed only when it was dispatched, with the batch's earlier steps
    already executed for real."""
    ses = _channel(monkeypatch, tmp_path)
    before = ses.stepped
    out = refused("does not take one", s.perform(steps=[
        {"op": "step", "count": 1},
        {"op": "watch_add", "ref": "0x4a0", "mode": "show", "fmt": "ptr16@CODE"}]))
    assert out["code"] == "bad_argument", out
    assert ses.stepped == before, "an earlier step of the batch ran before the refusal"


# --------------------------------------- what the console channel did to the WHOLE session
#
# THE PER-CALL FIELDS ARE GONE FROM THE NEXT ANSWER. `thread_errors` and `console_reruns`
# describe the window around ONE line, so a caller reading the third reply after a reader died
# has no way to know it happened, and `altered` alone cannot say that a chunk which wrote has
# written twice. The session block carries the running total instead, on every reply, the same
# argument `altered` itself rests on.


def test_a_clean_session_reports_three_zeros_and_not_an_absent_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE CONTROL, and it is the one that makes the counts worth reading. An object that
    appears only when something went wrong is one a caller never learns to look for, and its
    absence is then indistinguishable from a caller who forgot to check."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: b"7\n" + ses.sentinel(1)}
    out = s.lua("print(7)", seconds=1.0)
    assert out["status"] == "ok", out
    assert out["session"]["console"] == {"thread_errors": 0, "reruns": 0, "lost": 0}, out


def test_a_reader_death_is_held_against_the_session_and_still_there_two_replies_later(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The line was taken and never evaluated, so the session carries BOTH: a reader death and
    a lost line. The second reply is the point of the whole block -- it carries no per-call
    field about the death, and the session count is the only thing that still says it."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    ses.reader_eats = 1
    out = s.lua("print(7)", seconds=1.0)
    assert out["status"] == "ok" and out["resent"] == 1, out
    assert out["session"]["console"] == {"thread_errors": 1, "reruns": 0, "lost": 1}, out
    ses.answers[3] = b"8\n" + ses.sentinel(3)
    later = s.lua("print(8)", seconds=1.0)
    assert later["thread_errors"] == 0, "the per-call field is about THIS line"
    assert later["session"]["console"] == {"thread_errors": 1, "reruns": 0, "lost": 1}, later


def test_a_chunk_the_console_ran_again_is_counted_for_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A RERUN IS THE ONE THAT MATTERS MOST and the one a single number could not tell from a
    harmless restart: the chunk it ran again may have WRITTEN, and then it wrote twice."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {1: b"7\n" + ses.sentinel(1), 2: b"8\n" + ses.sentinel(2)}
    out = s.lua("print(7)", seconds=1.0)
    assert out["session"]["console"]["reruns"] == 0, out
    ses.reader_dies = 1
    out = s.lua("print(8)", seconds=1.0)
    assert out["console_reruns"] == 1, out
    assert out["session"]["console"] == {"thread_errors": 1, "reruns": 1, "lost": 0}, out
    # AND THE NEAR MISS, which is what stops the counter firing on anything that merely looks
    # like one: a script that PRINTS a sentinel this server never sent is a script's own text.
    ses.answers[3] = b"MAME_MCP_LUA_END#99\tfake\n" + ses.sentinel(3)
    out = s.lua('print("MAME_MCP_LUA_END#99\\tfake")', seconds=1.0)
    assert out["console_reruns"] == 0, out
    assert out["session"]["console"]["reruns"] == 1, "a look-alike moved the session count"


def test_a_refusal_does_not_contradict_its_own_session_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ONE REPLY MAY NOT CARRY TWO ANSWERS TO ONE QUESTION. The `reader_died` refusal names
    the deaths it saw in its own field, and the session block spells that word too, so the two
    must agree in one reply: the refusal reads bytes it never consumes, and a count that
    followed whichever path consumed them would let them differ. Counting by POSITION is
    what makes the two agree, and a refusal is the reply where the counts matter most: it is
    the one a caller gets when the channel is in trouble."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    ses.reader_eats = 2
    out = refused("NEVER evaluated", s.lua("print(7)", seconds=1.0))
    assert out["code"] == "reader_died" and out["thread_errors"] == 2, out
    assert out["session"]["console"]["thread_errors"] == out["thread_errors"], out
    assert out["session"]["console"]["lost"] == 2, out


def test_two_separate_incidents_add_up_rather_than_replacing_each_other(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CUMULATIVE IS THE WHOLE CLAIM, and with only one incident ever exercised an accumulator
    and an assignment produce the same number: every other case here would stay green with
    `+=` written as `=`. Two deaths in two separate calls is the smallest arrangement that
    can tell them apart."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    ses.reader_eats = 1
    first = s.lua("print(7)", seconds=1.0)
    assert first["session"]["console"] == {"thread_errors": 1, "reruns": 0, "lost": 1}, first
    ses.answers[4] = b"8\n" + ses.sentinel(4)
    ses.reader_eats = 1
    second = s.lua("print(8)", seconds=1.0)
    assert second["thread_errors"] == 1, "the per-call field is still about THIS line"
    assert second["session"]["console"] == {"thread_errors": 2, "reruns": 0, "lost": 2}, second


def test_a_second_look_at_one_window_does_not_count_its_deaths_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A COUNT THAT DOUBLE-COUNTS IS WORSE THAN NO COUNT, because it reads as a channel in
    worse trouble than it is. The console's mark moves past the bytes an answer consumed, so
    the window is counted once however many times the poll loop looked at it: here the wait
    spans several looks before the answer lands."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers = {2: b"7\n" + ses.sentinel(2)}
    ses.reader_eats = 1
    ses.sluggish = 2
    out = s.lua("print(7)", seconds=2.0)
    assert out["status"] == "ok", out
    assert out["session"]["console"]["thread_errors"] == 1, out
    assert out["session"]["console"]["lost"] == 1, out


# ---------------------------------------- the FIRST shape of a lost line, measured on the board


def test_a_reader_that_died_after_the_echo_is_a_line_that_was_never_evaluated() -> None:
    """THE FIRST SHAPE: the console's reader dies holding the line, printing `[LUA ERROR] in
    thread:`, and no sentinel for the call ever comes. Only one reader exists at a time, so a
    death standing AFTER the echo is that reader's."""
    line = transport.chunk_line('print("x")', 11)
    raw = (line + "\n").encode() + b"[LUA ERROR] in thread: return value must be string\n"
    assert transport.eaten(raw, line) is True


def test_a_reader_death_that_precedes_the_echo_belongs_to_an_earlier_line() -> None:
    """THE CONTROL, and it is the one that makes the shape above worth anything: the console's
    tail holds everything the session has ever printed, so a death sitting BEFORE this line's
    echo is somebody else's. Read without that ordering, this line would be resent on the
    strength of a death it survived, which is a SECOND execution of a script that may write."""
    line = transport.chunk_line('print("x")', 11)
    stale = b"[LUA ERROR] in thread: an earlier line killed it\n" + (line + "\n").encode()
    assert transport.eaten(stale, line) is False
    # AND THE SAME BYTES WITH THE DEATH BEHIND THE ECHO are this line's reader dying.
    assert transport.eaten((line + "\n").encode() + stale[:47], line) is True


# ------------------------------------- the SECOND shape of a lost line, measured on the board
#
# A LINE CAN BE TAKEN AND NEVER ANSWERED IN TWO WAYS, and `install_lost` was written for one
# of them: the console's reader dies, printing `[LUA ERROR] in thread:`. Measured on radendur
# (MAME 0.288), a line that raises at its TOP LEVEL does something else entirely -- the
# console catches it, prints its own `error:` line, hands back the prompt and carries on
# reading. The reader is alive; the line was taken, never evaluated, and no sentinel will
# ever come.
#
# For the caller that is the SAME fact: the script did not run, and sending it again runs it
# once. It was not the same fact to the detector, which read no death and therefore waited for
# an answer that could not arrive -- a tally left `installed: false, pending: true` for ever,
# which is the state `install_lost` exists to replace.


def test_a_console_that_reports_its_own_error_is_a_line_that_was_never_evaluated() -> None:
    """THE SECOND SHAPE, in the console's own framing. `error:` then a TAB then `[string "`
    is what MAME prints for a line that raised at its top level; matching on the bare word
    would let a script that merely PRINTS "error:" be read as a line that never ran."""
    line = transport.chunk_line('print("x")', 4)
    # THE PROMPT IS PART OF THE DOUBLE because it is part of what the console emits: it prints
    # its error and hands the prompt straight back, which is what says it is done with the
    # line. A double that leaves it out is not the shape the real console produces.
    raw = ((line + "\n").encode()
           + b'error: \t[string "..."]:2: something raised at the top level\n' + PROMPT)
    assert transport.eaten(raw, line) is True


def test_a_script_that_merely_prints_the_word_error_is_not_a_lost_line() -> None:
    """THE CONTROL FOR THE CASE ABOVE, and it is the one that makes the match worth anything:
    a resend runs the script a SECOND time, so a false positive here is a double write on a
    line that answered perfectly well."""
    line = transport.chunk_line('print("x")', 4)
    raw = ((line + "\n").encode()
           + b"error: the guest printed this itself\n"
           + f"{mstate.LUA_SENTINEL}#4\ttrue\tnil\n".encode())
    assert transport.eaten(raw, line) is False


def test_the_console_error_has_to_follow_the_echo_and_not_precede_it() -> None:
    """AN EARLIER LINE'S DEATH IS NOT THIS LINE'S. The console's tail holds everything the
    session has ever printed, so a report that sits BEFORE this line's echo belongs to
    somebody else's line and reading it here would resend a line that is merely slow."""
    line = transport.chunk_line('print("x")', 4)
    raw = (b'error: \t[string "..."]:2: a previous line raised\n' + (line + "\n").encode())
    assert transport.eaten(raw, line) is False


def test_a_console_error_with_no_prompt_behind_it_is_a_script_that_hung_not_a_lost_line() -> None:
    """THE PROMPT IS WHAT SAYS THE CONSOLE FINISHED WITH THE LINE, and it is what separates the
    console reporting a failure from a script that PRINTED that framing itself and then hung.
    Without it the script would be resent, which is a SECOND execution of a script that is
    still running -- the one harm a wrong verdict here can do."""
    line = transport.chunk_line('print("x")', 9)
    hung = (line + "\n").encode() + b'error: \t[string "y"]:1: the guest printed this\n'
    assert transport.eaten(hung, line) is False
    # AND THE SAME BYTES WITH THE PROMPT BEHIND THEM are the console having finished.
    finished = hung + PROMPT
    assert transport.eaten(finished, line) is True


# ------------------------------------------------- and the axis every double above is blind to
#
# EVERY CASE ABOVE IS A DOUBLE OF ONE OR TWO LINES, and they cover the SHAPE axis well: each
# failure shape, each control, each near miss. What none of them can hold is VOLUME. `eaten`
# works by finding THIS line's echo in a buffer that holds the whole session and searching the
# tail after it, so its correctness rests on there being a second candidate somewhere else to
# get wrong -- another line's echo, another line's death -- and a two-line double has nowhere
# to put one. A fake producer emitting one line where the real one emits kilobytes cannot fail
# on volume.

VOLUME = (FIXTURES / "console" / "session.volume.stdout").read_bytes()


def _volume_line(seq: int) -> str:
    """The line the server SENT for call `seq`, lifted out of the capture rather than authored:
    the console echoes the line whole behind its prompt, so the bytes between that prompt and
    the newline are exactly what `eaten` is asked about, byte for byte."""
    m = re.search(re.escape(PROMPT) + rb'([^\n]*MAME_MCP_LUA_END#' + str(seq).encode()
                  + rb'"[^\n]*)\n', VOLUME)
    assert m, f"no echoed command line for call {seq} in the capture"
    return m.group(1).decode()


def test_passed_over_answers_no_for_every_captured_line_before_its_own_sentinel() -> None:
    """THE LAG SHAPE ON REAL TRAFFIC. Cut the captured session just before a line's sentinel and
    the console has echoed the line and not finished it: no prompt behind the echo yet, so the
    line is waiting, never passed over. Cut that sentinel's line out instead and the next
    reader's prompt stands behind the echo, which is exactly a line handed back unrun."""
    seqs = sorted({int(n) for n in re.findall(
        re.escape(PROMPT) + rb'[^\n]*MAME_MCP_LUA_END#(\d+)"[^\n]*\n', VOLUME)})
    judged = 0
    for n in seqs:
        line = _volume_line(n)
        echo = VOLUME.find((line + "\n").encode())
        end = VOLUME.find(f"{mstate.LUA_SENTINEL}#{n}\t".encode(), echo)
        if echo < 0 or end < 0 or transport.THREAD_ERROR in VOLUME[echo:end]:
            continue
        assert transport.passed_over(VOLUME[:end], line) is False, n
        cut = VOLUME[:end] + VOLUME[VOLUME.index(b"\n", end) + 1:]
        assert transport.passed_over(cut, line) is True, n
        judged += 1
    assert judged >= 50, f"only {judged} captured lines judged"


def test_passed_over_takes_no_prompt_before_the_echo_and_no_error_framing_without_one() -> None:
    line = "the line"
    assert transport.passed_over(PROMPT + b"the line\n", line) is False
    assert transport.passed_over(b"the line\n" + PROMPT, line) is True
    assert transport.passed_over(PROMPT, line) is False, "no echo, not taken"
    # A script that prints the console's error framing and hangs is still running.
    assert transport.passed_over(b'the line\nerror: \t[string "x"]:1: y\n', line) is False
    assert transport.passed_over(b"the line\n" + transport.THREAD_ERROR + b" died\n", line) is True


def test_eaten_holds_its_ordering_against_a_console_log_with_real_volume_in_it() -> None:
    """THE VOLUME AXIS, against a captured session rather than an authored buffer.

    The capture holds a session's worth of echoed command lines and exactly ONE reader death,
    sitting among them rather than at either end, so this line's echo, another line's death
    and this line's own answer are all present at different offsets -- the arrangement that
    discriminates. What each figure actually is belongs in the capture's `PROVENANCE.txt`,
    where it is a record of one run and nobody has to keep it true.

    `eaten` is asked only after the caller has failed to find an answer, so a line that WAS
    answered is not a question it is ever put; what is pinned here is its ordering rule, which
    is the one that decides whether somebody's script is executed a second time.
    """
    assert VOLUME.count(transport.THREAD_ERROR) == 1, "the capture's single death is what places it"
    death = VOLUME.find(transport.THREAD_ERROR)
    # THE NUMBERING COMES OFF THE CAPTURE, never a literal range: a recapture that appended
    # more calls would leave a hardcoded bound quietly examining the first few and calling
    # that the volume axis, which is the one thing this case exists to hold.
    # Off the ECHOES, not off every sentinel in the file: the boot harness's own call prints
    # a sentinel the console never echoed, and it is not a line `eaten` can be asked about.
    seqs = sorted({int(n) for n in re.findall(
        re.escape(PROMPT) + rb'[^\n]*MAME_MCP_LUA_END#(\d+)"[^\n]*\n', VOLUME)})
    before = [n for n in seqs if VOLUME.find(_volume_line(n).encode()) < death]
    after = [n for n in seqs if VOLUME.find(_volume_line(n).encode()) > death]
    assert len(before) >= 5 and len(after) >= 50, (len(before), len(after))

    # (b) THIS LINE'S ECHO WITH A DEATH AFTER IT is a line the console took and never
    # evaluated: the last call whose echo precedes the death.
    taken = _volume_line(before[-1])
    assert (taken + "\n").encode() in VOLUME
    assert transport.eaten(VOLUME, taken) is True

    # (c) A DEATH SITTING BEFORE THIS LINE'S ECHO IS SOMEBODY ELSE'S, which is the claim
    # `eaten`'s docstring makes and the one a small double cannot put to it: the first call
    # whose echo follows the death.
    survived = _volume_line(after[0])
    assert (survived + "\n").encode() in VOLUME
    assert transport.eaten(VOLUME, survived) is False

    # (a) AND WITH SEVENTY CALLS IN BETWEEN it is still somebody else's: the death is not
    # merely adjacent-and-before, it is buried far behind a wall of other traffic.
    distant = _volume_line(after[-1])
    assert (distant + "\n").encode() in VOLUME
    assert transport.eaten(VOLUME, distant) is False

    # WHAT THE CAPTURE ADDS OVER THE DOUBLES, stated exactly rather than assumed. The same
    # question put to a hand-built two-line double answers the SAME, because the ordering
    # rule alone settles it and the test above already holds that with two lines. So the
    # ordering is not what the volume buys, and this case does not pretend otherwise: what
    # it buys is the assertion below, which needs a session's worth of calls to make at all.
    two_line = b"[LUA ERROR] in thread: an earlier line killed it\n" + (survived + "\n").encode()
    assert transport.eaten(two_line, survived) == transport.eaten(VOLUME, survived)


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
    # AND THE SCRIPTS REPEAT, which is what makes the line above worth asserting rather than
    # a property of a session that happened to send a different script every time: strip
    # each line's call number and one and the same text comes back many times over.
    bare = Counter(re.sub(rb"MAME_MCP_LUA_END#\d+", b"#", e) for e in echoes)
    assert max(bare.values()) >= 10, f"no script was sent twice: {bare.most_common(3)}"


def test_the_volume_fixture_keeps_the_size_that_is_its_whole_point() -> None:
    """THE SIZE IS PART OF THE CONTRACT, so it is asserted rather than assumed. A later tidy
    that sliced this file down to a few lines would leave every case above still passing
    while the axis they exist for had quietly gone; this is what goes RED instead."""
    assert len(VOLUME) > 100_000, f"the capture is {len(VOLUME)} bytes: the volume is gone"
    assert VOLUME.count(PROMPT) > 50, "a session's worth of calls is what gives it volume"


# ------------------------------------------------- the channel's decisions, held at their edges


def _scratch_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes) -> Path:
    """The scratch of a blank session whose console log holds `raw` and nothing else."""
    blank_session(monkeypatch)
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path)
    mfiles.log_path(tmp_path, "process").write_bytes(raw)
    return tmp_path


def test_an_answer_is_cut_at_its_own_line_whatever_follows_it_in_the_same_look(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One look can hold more than this call's answer (a frame evaluates several lines). The
    mark stops right after this sentinel's line, so what follows is still there for whoever it
    belongs to; the outcome is split at its FIRST tab, because an error's own words may carry
    one; and bytes that are not UTF-8 are replaced rather than raised on."""
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


def test_a_rerun_is_counted_per_printing_and_a_number_never_sent_is_not_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chunk not yet answered that prints twice in one window ran again ONCE; one already
    answered ran again every time it prints; a number this server never sent is a script's
    own text however often it prints, and it does not end the reading either."""
    blank_session(monkeypatch)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 5)
    monkeypatch.setattr(mstate.STATE, "lua_answered", 2)
    def printed(*seqs: int) -> bytes:
        return b"".join(b"MAME_MCP_LUA_END#%d\ttrue\tnil\n" % n for n in seqs)
    assert transport.reruns_in(printed(3, 3), 5) == ["MAME_MCP_LUA_END#3"]
    assert transport.reruns_in(printed(3, 3, 3), 5) == ["MAME_MCP_LUA_END#3"] * 2
    assert transport.reruns_in(printed(2, 2), 5) == ["MAME_MCP_LUA_END#2"] * 2
    assert transport.reruns_in(printed(9, 9, 5, 2), 5) == ["MAME_MCP_LUA_END#2"]


def test_the_deaths_are_counted_up_to_the_size_read_and_no_further(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The count is by POSITION: what lies past the size it took belongs to the next count. A
    log that grew between the two reads would otherwise have that death counted twice."""
    death = transport.THREAD_ERROR + b" attempt to index a nil value\n"
    scratch = _scratch_logging(tmp_path, monkeypatch, death + death)
    monkeypatch.setattr(transport, "stdout_mark", lambda _scratch: len(death))
    transport.count_deaths(scratch)
    assert mstate.STATE.console_thread_errors == 1
    assert mstate.STATE.console_counted == len(death)


def test_a_resent_line_the_reader_is_late_for_is_stepped_for_like_any_other(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reader's window restarts at the resend's own step, and every step spent for the
    reader is counted: the reply's arithmetic is the machine's, one step per instruction."""
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
    assert out["resent"] == 1 and out["reader_steps"] == 2, out
    assert out["evaluated_by"] == "4 steps" and ses.stepped == 4, out
    assert out["pc_before"] == f"{pc:#010x}", out


def test_a_refusal_counts_its_steps_and_names_where_the_machine_stood(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """What a refused evaluation cost is in the refusal, in the reply's own fields: the steps
    spent for the reader ADD to the ones bought, and so does the one a resend took."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_WAIT_S", 0.05)
    monkeypatch.setattr(transport, "READER_STEPS_MAX", 1)
    ses.reader_late = 20
    pc = ses.pc
    out = refused("reader", s.lua("print(1)", seconds=0.4))
    assert out["code"] == "wait_expired" and out["reader_steps"] == 1, out
    assert out["evaluated_by"] == "2 steps" and out["pc_before"] == f"{pc:#010x}", out
    assert out["lines_ahead"] == 0 and out["call"] == "MAME_MCP_LUA_END#1", out
    # A line taken and lost twice, on a channel of its own: the resend's step is in the count.
    (tmp_path / "lost").mkdir()
    ses = _channel(monkeypatch, tmp_path / "lost")
    ses.reader_eats = 2
    out = refused("twice", s.lua("print(1)", seconds=1.0))
    assert out["code"] == "reader_died" and out["resent"] == 1, out
    assert out["evaluated_by"] == "2 steps", out


def test_a_wrapper_whose_line_died_twice_says_twice_and_counts_both_deaths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The wrapper's own refusal, told apart from the one a reader that never took the line
    earns: both say the script never ran, and only this one is about two taken lines."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(lua, "EVAL_WAIT_S", 0.05)
    ses.reader_eats = 2
    out = refused("twice", s.input(port=":P1", field="Coin 1", frames=4))
    assert out["code"] == "reader_died" and out["pending"] is False and out["resent"] == 1, out
    assert out["thread_errors"] == 2 and out["console_reruns"] == 0, out
    assert out["session"]["console"]["lost"] == 2, out


def test_a_backlog_that_does_not_clear_is_stepped_a_bounded_number_of_times(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A wrapper steps the lines ahead off before it sends its own, and a line the console
    never evaluates cannot make that a walk without end."""
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
    """The answer ends at the FIRST sentinel of the call. A second printing of it, after a
    reader death, is a rerun of a chunk by then answered: it stays past the mark, and the
    next answer names it instead of it being read as part of this one."""
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


# ------------------------------------ the throttle's own words, and the edges of the pipe's depth


def _running(monkeypatch: pytest.MonkeyPatch, ses: _ChannelSession) -> None:
    ses.running = True
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)


@pytest.mark.parametrize("on,word", [(True, "true"), (False, "false")])
def test_the_throttle_script_that_reaches_the_pipe_carries_the_switch_that_was_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, on: bool, word: str
) -> None:
    """The reply says `on`; what moves the machine is the line in the pipe, so that line is
    what is read here, for both switches."""
    ses = _channel(monkeypatch, tmp_path)
    out = s.throttle(on=on)
    assert out["on"] is on and out["pending"] is True, out
    assert out["applies"].startswith("when the console next reads a line") and (
        "confirmed_by" in out), out
    sent = transport.chunk_line(lua.THROTTLE_LUA % {"on": word, "mark": "MAME_MCP_THROTTLE#1"}, 1)
    assert ses.stdin.getvalue() == sent.encode() + b"\n"
    assert f"video.throttled = {word}\n" in lua.THROTTLE_LUA % {"on": word, "mark": "x"}


def test_the_throttle_body_judges_its_own_bound_with_both_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The body is callable without the tool in front of it (`perform` reaches it), so the
    bound is judged there too, and with the bound it was given rather than the default."""
    ses = _channel(monkeypatch, tmp_path)
    seen: list[tuple[Any, ...]] = []
    check = lua.check_throttle

    def spy(*args: Any, **kwargs: Any) -> None:
        seen.append(args)
        check(*args, **kwargs)

    monkeypatch.setattr(lua, "check_throttle", spy)
    lua.throttle(ses, ses.scratch, False, 0.5)  # type: ignore[arg-type]
    assert seen == [(False, 0.5)], seen
    with pytest.raises(mstate.Invalid, match="seconds=0 is not a bound"):
        lua.throttle(ses, ses.scratch, True, 0)  # type: ignore[arg-type]
    assert ses.stdin.getvalue().count(b"\n") == 1, "a refused bound sends nothing"


def test_a_running_throttle_on_is_read_back_as_true_and_the_opposite_names_its_marks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _running(monkeypatch, ses)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = ["[luaengine] MAME_MCP_THROTTLE#1 throttled=true frame=77"]
    threading.Timer(0.1, ses._tick).start()
    out = s.throttle(on=True, seconds=2.0)
    assert out["status"] == "ok" and out["pending"] is False and out["frame"] == 77, out
    assert out["mark"] == "MAME_MCP_THROTTLE#1" and 0 <= out["waited_s"] < 2.0, out
    ses.answers[2] = ses.sentinel(2)
    ses.marks[2] = ["[luaengine] MAME_MCP_THROTTLE#2 throttled=false frame=78"]
    threading.Timer(0.1, ses._tick).start()
    out = refused("reports throttled=false after asking for true", s.throttle(on=True, seconds=2.0))
    assert out["code"] == "readback_refused" and out["marks"] == ses.marks[2], out


def test_a_throttle_wait_names_its_mark_when_it_expires_and_when_mame_goes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _running(monkeypatch, ses)
    out = refused("still pending", s.throttle(on=True, seconds=0.2))
    assert out["code"] == "wait_expired" and out["mark"] == "MAME_MCP_THROTTLE#1", out
    ses.quit_asked = True                      # the process double now polls as exited, code 0
    out = refused("while this call waited for its own throttle mark in error.log",
                  s.throttle(on=True, seconds=0.2))
    assert out["code"] == "session_broken" and out["mark"] == "MAME_MCP_THROTTLE#2", out
    assert out["exit_code"] == 0, out


def test_a_throttle_wait_reports_its_progress_to_the_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _running(monkeypatch, ses)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    said: list[str] = []
    with pytest.raises(mstate.Invalid):
        lua.throttle(ses, ses.scratch, True, 0.1,  # type: ignore[arg-type]
                     lambda _done, _total, message: said.append(message))
    assert said and said[0].startswith("throttle: waiting for the mark, 0s"), said


def test_the_pipe_is_refused_one_line_past_the_steps_a_call_spends_and_not_at_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exactly `PIPE_STEPS_MAX` lines ahead is a depth the call steps off; one more is the
    refusal, which carries the depth as a field and in its words."""
    blank_session(monkeypatch)
    monkeypatch.setattr(mstate.STATE, "lua_seq", transport.PIPE_STEPS_MAX)
    assert transport.refuse_if_too_deep(tmp_path) == transport.PIPE_STEPS_MAX
    monkeypatch.setattr(mstate.STATE, "lua_seq", transport.PIPE_STEPS_MAX + 1)
    with pytest.raises(mstate.Invalid) as caught:
        transport.refuse_if_too_deep(tmp_path)
    e = caught.value
    assert e.code == "bad_argument" and e.fields == {"lines_ahead": transport.PIPE_STEPS_MAX + 1}
    assert str(e).startswith(f"{transport.PIPE_STEPS_MAX + 1} lines are still ahead"), str(e)


# ------------------------------------------------------- the drain `close` spends before `quit`


class _Stepper:
    """A stopped session that counts its steps and refuses a walk without end: the cap is the
    test's own, far past any count the drain may legitimately reach."""

    running = False
    WALK_MAX = 80

    def __init__(self, on_step: Any = None) -> None:
        self.stepped = 0
        self.on_step = on_step

    def step(self) -> str:
        self.stepped += 1
        assert self.stepped <= self.WALK_MAX, "the drain is walking without end"
        if self.on_step is not None:
            self.on_step(self.stepped)
        return "T05"


def _backlog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, depth: int) -> Path:
    scratch = _scratch_logging(tmp_path, monkeypatch, b"")
    monkeypatch.setattr(mstate.STATE, "lua_seq", depth)
    monkeypatch.setattr(transport, "POLL_S", 0.0)
    return scratch


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
    """`close` passes no bound, so the default IS the bound of every real drain; and a clock
    that has run out ends the walk with budget to spare."""
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


# ------------------------------------------------ what a refusal of the channel carries with it


def test_a_wrappers_rerun_refusal_carries_its_marks_its_fields_and_what_was_resent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blank_session(monkeypatch)
    monkeypatch.setattr(mstate.STATE, "console_reruns_seen", 3)
    seen = ["[luaengine] MAME_MCP_RECORD#4 begin frame=1"] * 3
    answer = transport.Answer(text="", ok=True, error="", thread_errors=0, reruns=[])
    with pytest.raises(mstate.Invalid) as caught:
        lua.refuse_a_rerun(seen, "MAME_MCP_RECORD#4", answer, 1, path="/tmp/x.avi")
    fields = caught.value.fields
    assert mstate.STATE.console_reruns_seen == 3 + 2, "the repeats ADD to what was seen before"
    assert fields["marks"] == seen and fields["path"] == "/tmp/x.avi", fields
    assert fields["resent"] == 1 and "sent again (1 time)" in fields["note"], fields
    assert fields["console_reruns"] == 2, fields


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


def test_the_deaths_are_counted_from_where_the_last_count_stopped_to_the_size_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The read is of the bytes BETWEEN the two positions: with a count already behind it, a
    read as long as the size itself would run into what the next count owns."""
    death = transport.THREAD_ERROR + b" attempt to index a nil value\n"
    scratch = _scratch_logging(tmp_path, monkeypatch, death * 3)
    monkeypatch.setattr(mstate.STATE, "console_counted", len(death))
    monkeypatch.setattr(transport, "stdout_mark", lambda _scratch: 2 * len(death))
    transport.count_deaths(scratch)
    assert mstate.STATE.console_thread_errors == 1
    assert mstate.STATE.console_counted == 2 * len(death)


def test_a_wrappers_session_block_is_built_after_its_answer_was_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The run's reply was built inside `run_for`, BEFORE the wrapper read its answer; what
    the answer showed (a reader death, the previous chunk run again) moved the session
    counters after that block was taken, so the reply named the rerun in its own
    `console_reruns` while its `session.console` still said zero. The block a wrapper
    returns is the one built after everything the call read."""
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


def test_a_record_refused_after_its_run_says_the_frames_it_advanced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The AVI is checked after the whole run: a refusal there has moved the machine, and it
    says from which frame to which, in the run refusals' own keys."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = ses.sentinel(1)
    ses.marks[1] = ["[luaengine] MAME_MCP_RECORD#1 armed frame=100 vblank=false",
                    "[luaengine] MAME_MCP_RECORD#1 begin frame=100 recording=true",
                    "[luaengine] MAME_MCP_RECORD#1 end frame=104"]
    before = 100                      # the double's frame counter at its start
    out = refused("is not a finished AVI", s.record(frames=5))
    assert out["frame_before"] == before and out["frame_after"] > out["frame_before"], out
    assert out["frame_after"] == mstate.STATE.last_stop["frame"], out



@pytest.mark.parametrize(("error", "code"), [
    ("mcp:3: no port :P9", "unknown_ref"),
    ("mcp:5: port :P1 has no field Coin 9", "unknown_ref"),
    ("mcp:3: boom", "unexpected_answer"),
])
def test_inputs_own_script_raising_is_coded_by_what_it_raised(error: str, code: str) -> None:
    """The console prefixes the chunk's place (`mcp:N:`): the port and the field the script
    refuses on its own are the caller's names resolving to nothing."""
    assert lua.input_refusal_code(error) == code
