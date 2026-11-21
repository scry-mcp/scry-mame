"""The Lua channel: the helpers its test modules share."""

from __future__ import annotations

import io
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from server_support import _install, _RegisterSession  # noqa: E402
from session_doubles import blank_session  # noqa: E402

from scry_mame import envelope as menvelope  # noqa: E402
from scry_mame import files as mfiles  # noqa: E402
from scry_mame import (
    launch,  # noqa: E402
    transport,  # noqa: E402
)
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

R_ABS = "must be an absolute path"


class RecordingTold:
    """A presence that keeps what the session told it about recordings, in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def recording(self, kind: str, on: bool) -> None:
        self.calls.append((kind, on))

    def began(self, call: object) -> None:
        pass

    def ended(self, call: object, outcome: object) -> None:
        pass

    def paused(self, stopped: bool) -> None:
        pass

FIXTURES = Path(__file__).parent / "fixtures"
CONSOLE = (FIXTURES / "console.stdout").read_bytes()
#: The same session on MAME 0.288, whose console printed a raised chunk's sentinel twice.
CONSOLE_0288 = (FIXTURES / "console-0288.stdout").read_bytes()
MARKS = (FIXTURES / "console-error.log").read_text().splitlines()
AVI_HEAD = (FIXTURES / "record-30-frames-avi.head").read_bytes()
STA_HEAD = (FIXTURES / "statesave-sta.head").read_bytes()
PROMPT = b"\x1b[1;36m[MAME]\x1b[0m> "
BANNER = (b"mame 0.288\t\nCopyright (C) Nicola Salmoria and the MAME team\n\nLua 5.4\t\n"
          b"Copyright (C) Lua.org, PUC-Rio\n\n" + PROMPT
          + b"gdbstub: listening on address localhost port 23990\n")
# Captured on m68k-dual by writing a bare `error(...)` into the pipe.
CONSOLE_REFUSAL = (FIXTURES / "console-refused.stdout").read_bytes().split(b"\n", 1)[1].split(
    PROMPT, 1)[0]


def _captured(seq: int, as_seq: int = 1, console: bytes = CONSOLE) -> bytes:
    """What the console printed after the echo of chunk `seq`, up to the next prompt."""
    m = re.search(rb'"MAME_MCP_LUA_END#%d", false, e\) [^\n]*\n' % seq, console)
    assert m, seq
    rest = console[m.end():]
    return rest[:rest.index(PROMPT)].replace(b"#%d" % seq, b"#%d" % as_seq)


def _marks_of(tag: str) -> list[str]:
    return [m for m in MARKS if tag in m]


class _ChannelSession(_RegisterSession):
    """A register session with the channel's two ends."""

    def __init__(self, scratch: Path) -> None:
        super().__init__(bits=32, frame=100)
        self.scratch = scratch
        self.answers: dict[int, bytes] = {}
        self.sluggish = 0
        self.reader_late = 0
        self.reader_dies = 0
        self.reader_eats = 0
        self.console_refuses = 0
        self.last: tuple[bytes, bytes] | None = None
        self.marks: dict[int, list[str]] = {}
        self.files: dict[int, tuple[Path, bytes]] = {}
        self.pc = 0x400
        self.stdin = _TimedPipe()
        self.advanced: list[float] = []
        self.reader_dead = False
        self.reader_dead_said = False
        self.quit_asked = False
        self.consumed = 0
        self.queue: list[bytes] = []
        self.stepped = 0
        self.write_states = True
        self.checked: list[tuple[int, int]] = []
        (scratch / "stdout.log").write_bytes(BANNER)

    def current_pc(self) -> int:
        return self.pc

    def quit(self) -> None:
        """What `close` asks the console for."""
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
            if not self.reader_dead_said:
                self.reader_dead_said = True
                with open(self.scratch / "stdout.log", "ab") as fh:
                    fh.write(b"[LUA ERROR] in thread: attempt to index a nil value\n" + PROMPT)
            return
        # One line per tick, as the real console does (m68k-dual).
        if self.reader_dies > 0 and self.last is not None:
            self.reader_dies -= 1
            with open(self.scratch / "stdout.log", "ab") as fh:
                fh.write(b"[LUA ERROR] in thread: attempt to index a nil value\nstack "
                         b"traceback:\n\t[C]: in function 'require'\n" + self.last[1] + PROMPT)
            return
        fresh = self.stdin.getvalue()[self.consumed:]
        self.consumed = len(self.stdin.getvalue())
        self.queue.extend(line for line in fresh.split(b"\n") if line)
        if self.reader_eats > 0 and self.queue:
            self.reader_eats -= 1
            line = self.queue.pop(0)
            with open(self.scratch / "stdout.log", "ab") as fh:
                fh.write(line + b"\n[LUA ERROR] in thread: return value must be string\n"
                         + PROMPT)
            return
        if self.console_refuses > 0 and self.queue:
            self.console_refuses -= 1
            line = self.queue.pop(0)
            with open(self.scratch / "stdout.log", "ab") as fh:
                fh.write(line + b"\n" + CONSOLE_REFUSAL + PROMPT)
            return
        for line in self.queue[:1]:
            # THE WRAPPER'S SENTINEL IS THE LAST ON THE LINE.
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
        if self.reader_late > 0:
            self.reader_late -= 1
            return "T05"
        self._tick()
        return "T05"

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        if command == "gvblank":
            self.advanced.append(time.monotonic())
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
            # MAME answers the same whatever happened: the refusal is silent.
            return "State load attempted.  Please refer to window message popup for results.\n"
        return super().monitor(command, timeout)


class _TimedPipe(io.BytesIO):
    """The stdin end, with a clock."""

    def __init__(self) -> None:
        super().__init__()
        self.written: list[float] = []

    def write(self, data: Any) -> int:
        self.written.append(time.monotonic())
        return super().write(data)


class _PipeProcess:
    """The process end of the channel."""

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
    blank_session(monkeypatch)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "scratch", scratch)
    monkeypatch.setattr(mstate.STATE, "system", "m68k")
    monkeypatch.setattr(mstate.STATE, "named_state_dir", "")
    monkeypatch.setattr(mstate.STATE, "proc", _PipeProcess(ses.stdin, ses))
    return ses


TRIO = {"thread_errors", "console_reruns"}


def _logging_stateload(monkeypatch: pytest.MonkeyPatch, ses: Any, line: str) -> None:
    """The double's `stateload`, with MAME writing `line` to `error.log` while it loads."""
    plain = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("stateload "):
            with open(mfiles.log_path(ses.scratch, "emulator"), "a") as fh:
                fh.write(line + "\n")
        return str(plain(command, timeout))

    monkeypatch.setattr(ses, "monitor", monitor)


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


class _SlowExit:
    """A process that leaves `after` seconds from now."""

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


class _DiesMidWait:
    """MAME gone while a call waits for the console."""

    pid = 4243

    def __init__(self, stdin: Any, after: int) -> None:
        self.stdin, self.after, self.polls = stdin, after, 0

    def poll(self) -> int | None:
        self.polls += 1
        return None if self.polls <= self.after else -11


def _settles(monkeypatch: pytest.MonkeyPatch, ses: _ChannelSession) -> list[tuple[float, int, int]]:
    """Every sleep, with what the pipe held and the steps taken when it began."""
    monkeypatch.setattr(transport, "READER_SETTLE_S", 0.0137)
    slept: list[tuple[float, int, int]] = []
    monkeypatch.setattr(time, "sleep",
                        lambda s_: slept.append((s_, len(ses.stdin.getvalue()), ses.stepped)))
    return slept


VOLUME = (FIXTURES / "console" / "session-volume.stdout").read_bytes()


def _volume_line(seq: int) -> str:
    """The line the server sent for call `seq`, lifted from the capture."""
    m = re.search(re.escape(PROMPT) + rb'([^\n]*MAME_MCP_LUA_END#' + str(seq).encode()
                  + rb'"[^\n]*)\n', VOLUME)
    assert m, f"no echoed command line for call {seq} in the capture"
    return m.group(1).decode()



def _scratch_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes) -> Path:
    """The scratch of a blank session whose console log holds `raw` and nothing else."""
    blank_session(monkeypatch)
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path)
    mfiles.log_path(tmp_path, "process").write_bytes(raw)
    return tmp_path



def _running(monkeypatch: pytest.MonkeyPatch, ses: _ChannelSession) -> None:
    ses.running = True
    monkeypatch.setattr(ses, "poll_stop", lambda timeout=0.0: False)



class _Stepper:
    """A stopped session that counts its steps and refuses a walk without end"""

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


def _whole() -> dict[str, Any]:
    """The whole `session` block, as `status` carries it, read off the state as it is now."""
    return menvelope.session_block(True)
