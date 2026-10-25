"""The server's guarantees: the helpers its test modules share."""

from __future__ import annotations

import io
import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scry_core.host_program import absolute as _abs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scry_core import host_program  # noqa: E402
from scry_core import progress as mprogress  # noqa: E402
from scry_core.host_program import temporary as _tmp  # noqa: E402
from session_doubles import (  # noqa: E402
    MAP_RAM,
    MAP_ROM,
    SessionFields,
    bplist_add,
    captured,
    debugger_lists,
    fake_mame,  # noqa: E402
    reading_session,
    rewrite_mame,
    use_table,  # noqa: E402
)

import gdb_session as g  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_files as files  # noqa: E402
import mame_launch as launch
import mame_machine as machine  # noqa: E402
import mame_running as running  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


def _wait_emulator(ses: Any, scratch: Path, alive: Any, on_stop: Any, pattern: str,
                   seconds: float, progress: Any = mprogress.no_progress) -> dict[str, Any]:
    """`files.log_wait` on the emulator channel, positional as these tests wrote it."""
    return files.log_wait(ses, scratch, alive, on_stop, pattern, seconds, "emulator", progress)


def _install(monkeypatch: pytest.MonkeyPatch, ses: Any, tmp_path: Path) -> None:
    """Install `ses` as the live session with a scratch under `tmp_path`."""
    monkeypatch.setattr(mstate.STATE, "alive", lambda: ses)
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path)
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    monkeypatch.setattr(mstate.STATE, "errorlog_mark", 0)
    monkeypatch.setattr(mstate.STATE, "found_stop_last", {})
    monkeypatch.setattr(mstate.STATE, "store", dec.DeclarationStore("test", path=None))
    monkeypatch.setattr(mstate.STATE, "session_origin", "s1")
    monkeypatch.setattr(mstate.STATE, "first_cpu", ":maincpu")      # the doubles' first cpu
    monkeypatch.setattr(mstate.STATE, "fingerprints", {":maincpu": "fp-test"})
    monkeypatch.setattr(mstate.STATE, "controls", {})


MAME_ASSIGNMENTS = ["=", "*=", "/=", "%=", "+=", "-=", "<<=", ">>=", "&=", "^=", "|=", "++", "--"]


def _never_spawns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Whatever `start` does past its checks, it may not reach the emulator in these cases."""
    import subprocess

    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "no-helper"))

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("start SPAWNED the emulator on an input it should have refused")

    monkeypatch.setattr(subprocess, "Popen", boom)




# The debugger's banner as `tests/fixtures/console/session.volume.stdout` captured it.
BANNER_LINE = launch.DEBUGGER_BANNER + "m68k-dual (m68k-dual)\n"


class _StubProcess:
    """What `start` gets back from `Popen`: alive until killed, with a pid, and nothing else."""

    PID = 4242
    last_argv: list[str] = []
    last_kwargs: dict[str, Any] = {}

    def __init__(self, *a: object, **k: object) -> None:
        self.killed = False
        self.pid = self.PID
        argv = a[0] if a else k.get("args")
        assert isinstance(argv, list)
        _StubProcess.last_argv = list(argv)
        _StubProcess.last_kwargs = dict(k)
        # The banner every MAME under `-debug` prints, as the console fixtures captured it.
        out = k.get("stdout")
        assert isinstance(out, io.BufferedIOBase), "`boot` hands MAME a file for its output"
        out.write(BANNER_LINE.encode())
        out.flush()

    def poll(self) -> int | None:
        return 1 if self.killed else None

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return 1


def _stub_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, image: bytes, at: int
) -> g.Session:
    """Everything `start` needs to run its happy path with no emulator."""
    import subprocess

    ses = reading_session(image, at)
    ses.dial = lambda: None  # type: ignore[method-assign]
    ses.handshake = lambda timeout=None: None  # type: ignore[method-assign]
    ses._layouts[1] = g.Layout({}, 0, "", [])
    ses.current_pc = lambda: at  # type: ignore[method-assign]
    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "no-helper"))
    real_popen = subprocess.Popen

    def popen(*a: Any, **k: Any) -> Any:
        argv = a[0] if a else k["args"]
        if Path(argv[0]).stem == "fake-mame" and "-debugger" in argv:
            return _StubProcess(*a, **k)
        return real_popen(*a, **k)

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(g, "Session", lambda port, owner=None: ses)
    return ses


def _boot_args(tmp_path: Path, image: bytes) -> dict[str, Any]:
    """The `start` arguments that pass every check against a `_stub_boot` session serving
    `image` at address 0 (the defaults for `reference_addr` and `reference_base`)."""
    binary = fake_mame(tmp_path)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(image)
    return dict(binary=str(binary), system="m68k", rompath=str(tmp_path), reference_rom=str(rom))




class _FakeSession(SessionFields):
    """A tiny addressed memory that accepts writes, and a `writable` switch to model ROM."""

    def __init__(self, holds: bytes, *, writable: bool = True) -> None:
        self.mem = bytearray(holds)
        self.base = 0
        self.writable = writable
        self.written: tuple[int, bytes] | None = None
        self.writes = 0
        self.threads: dict[int, str] = {}

    def write(self, addr: int, data: bytes, *, thread: int) -> None:
        self.written = (addr, data)
        self.writes += 1
        if self.writable:
            self.base = addr
            self.mem = bytearray(data)

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        if self.writable and addr != self.base:
            return bytes(n)
        return bytes(self.mem[:n])

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        """`map` as the console answers it."""
        if command == "cpulist":
            return captured("cpulist.main-visible.txt")
        assert command.startswith("map "), f"this double's console answers only `map`: {command}"
        return MAP_RAM if self.writable else MAP_ROM


class _DroppingWire:
    """A socket whose stub DROPS everything, as MAME's does a packet past its size."""

    def __init__(self, answers: tuple[str, ...] = ()) -> None:
        self.sent: list[bytes] = []
        self.answers = [f"${a}#{g._checksum(a)}".encode() for a in answers]

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def settimeout(self, seconds: float) -> None:
        pass

    def recv(self, n: int) -> bytes:
        if self.answers:
            return self.answers.pop(0)
        raise TimeoutError



def _recording_helper(tmp_path: Path) -> tuple[Path, Path]:
    """A `place-window` double that records its argv and prints a plausible flag list."""
    log = tmp_path / "argv.log"
    fake = host_program.write(tmp_path / "place-window", (
        f"import pathlib, sys\npathlib.Path({str(log)!r}).write_text("
        "''.join(a + '\\n' for a in sys.argv[1:]))\n"
        "sys.stdout.buffer.write(b'-window\\n-nomaximize\\n')\n"))
    return fake, log


class _RecordingSession(SessionFields):
    """A session that only records what `kill` asks of it."""

    def __init__(self, quit_raises: bool = False) -> None:
        self.events: list[str] = []
        self.quit_raises = quit_raises
        self.writes = 0
        self.running = False

    def quit(self) -> None:
        self.events.append("quit")
        if self.quit_raises:
            raise g.SessionError("the stub closed the connection")

    def close(self) -> None:
        self.events.append("close")


def _closing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exits: bool,
             code: int = 0) -> None:
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}tails"
    scratch.mkdir()
    (scratch / "stdout.log").write_text("bye\n")
    (scratch / "error.log").write_text("[luaengine] routine\n")
    monkeypatch.setattr(mstate.STATE, "scratch", scratch)
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=exits, code=code)  # type: ignore[assignment]


class _ExitingProcess:
    """A process that exits when asked through `quit`, or never, and records the order."""

    pid = 99

    def __init__(self, events: list[str], exits: bool, code: int = 0) -> None:
        self.events, self.exits, self.gone, self.code = events, exits, False, code

    def poll(self) -> int | None:
        return self.code if self.gone else None

    def wait(self, timeout: float | None = None) -> int:
        import subprocess

        # One `wait` per stretch: the real wait is sliced so the line can be painted, and
        # the ORDER is what these events prove, not how many slices a stretch took.
        if self.events[-1:] != ["wait"]:
            self.events.append("wait")
        if self.exits or "kill" in self.events:
            self.gone = True
            return self.code
        raise subprocess.TimeoutExpired("mame", timeout or 0)

    def kill(self) -> None:
        self.events.append("kill")


class _UnreapableProcess(_ExitingProcess):
    """SIGKILLed and still not reaped within the second wait: what a wedged host does."""

    def wait(self, timeout: float | None = None) -> int:
        import subprocess

        self.events.append("wait")
        raise subprocess.TimeoutExpired("mame", timeout or 0)




def _masked(mask: int, cpu: str = ":maincpu") -> dict[str, Any]:
    """An inventory holding one cpu's program space and its address mask, as `start` caches it."""
    return {"spaces": [{"cpu": cpu, "space": "program", "address_mask": f"{mask:#010x}"}]}


class _ConsoleSession(SessionFields):
    """A session whose console answers from canned replies, and whose memory is `image`."""

    def __init__(self, image: bytes = b"", replies: dict[str, Any] | None = None) -> None:
        self.image = image
        self.replies = replies or {}
        self.commands: list[str] = []
        self.writes = 0
        self.threads: dict[int, str] = {}

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        """The same image whichever thread reads it, a thread other than the first noted."""
        if thread != 1:
            self.commands.append(f"m@{thread}")
        return self.image[addr : addr + n]

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        self.commands.append(command)
        head = command.split()[0]
        reply = self.replies.get(head, "")
        return str(reply(command)) if callable(reply) else str(reply)


def _console(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ses: _ConsoleSession) -> Path:
    """Install `ses` as the live session and give the server a scratch under `tmp_path`."""
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}test"
    (scratch / "snap").mkdir(parents=True, exist_ok=True)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "scratch", scratch)
    monkeypatch.setattr(mstate.STATE, "snapshots", 0)
    monkeypatch.setattr(mstate.STATE, "debug_dumps", 0)
    return scratch


def _snapping(image_dir: Path) -> Any:
    """A fake console `snap` that writes a small PNG-looking file where MAME would."""

    def snap(command: str) -> str:
        name = command[len("snap "):]
        (image_dir / name).write_bytes(_PNG)
        return f"Saved screen #0 snapshot as '{name}'"

    return snap


# The smallest thing that passes for a finished PNG here: signature, padding, IEND trailer.
_PNG = files.PNG_SIGNATURE + bytes(64) + b"\x00\x00\x00\x00" + files.PNG_TRAILER



FIXTURES = Path(__file__).parent / "fixtures" / "console"


def _first_window(answer: str) -> Callable[[str], str]:
    """A console that holds `answer`'s hits in the window starting at zero and none after it."""
    none = (FIXTURES / "find.none.txt").read_text()
    return lambda cmd: answer if cmd.split()[1].startswith("0x0,") else none


def _listing_pair(scratch: Path, name: str) -> Callable[[str], str]:
    """A console `dasm` that writes the captured listing of one range, with its opcode bytes or
    without them as the command's `opcodes` flag asks, where the real console would."""
    def dasm(command: str) -> str:
        file, _addr, _length, *rest = command[len("dasm "):].split(",")
        bare = bool(rest) and rest[0] == "0"
        (scratch / file).write_bytes((FIXTURES / f"{name}{'.bare' if bare else ''}.txt")
                                     .read_bytes())
        return (FIXTURES / "dasm.reply.txt").read_text()
    return dasm




class _OwnRegisterFile:
    """A double that is its own register file for every thread."""

    values: dict[str, int]
    bits = 32

    def layout(self, thread: int) -> Any:
        return self

    @property
    def pc_name(self) -> str:
        return next(n for n in ("PC", "EIP", "RIP") if n in self.values)

    @property
    def register_names(self) -> list[str]:
        return list(self.values)

    @property
    def register_bits(self) -> dict[str, int]:
        return dict.fromkeys(self.values, self.bits)

    def register_texts(self, *, thread: int) -> dict[str, str]:
        """`values` as the stub prints them, big-endian digits at the declared width."""
        return {n: f"{v:0{self.bits // 4}x}" for n, v in self.values.items()}


class _RegisterSession(_OwnRegisterFile, SessionFields):
    """A session with a register file of a declared width, a frame counter and a console."""

    def __init__(self, bits: int, frame: int = 10, stop_after: int | None = 3,
                 values: dict[str, int] | None = None) -> None:
        self.bits = bits
        self.byte_order = "big"
        self.frame = frame
        self.stop_after = stop_after
        self.emu_clock = 0.0
        self.emulating = False
        self.running = False
        self.stop_count = 0
        self.last_stop_packet = ""
        self.polls_since_gtime = 0
        self.threads: dict[int, str] = {}
        self.values = values or {"EAX": 0x1234, "EIP": 0x8B56}
        self.temps: dict[int, int] = {}
        self.cycles_per_frame = 0x1000
        self.frozen = False
        self.pcs = [0xF2034, 0xF2100]
        self.commands: list[str] = []
        self.writes = 0
        self.interrupted = False
        self.received: list[float] = []
        self.frame_answers: list[str] | None = None
        self.bplist_rows: list[str] = []
        self.bp_next_index = 1
        self.bp_devices: dict[int, str] | None = None
        self.rplist_rows: list[tuple[int, str, bool]] = []
        self.rp_next_index = 1
        self.packet_size: int | None = None
        self.frameless = False
        self.cycles_offset = 0
        self.stale_after_load = False
        self.saved_frames: dict[str, int] = {}
        self.stale_cycles: int | None = None
        self.reset_pending = False

    # The real rules, not copies of them: they read nothing but `packet_size`.
    max_payload = g.Session.max_payload
    console_packet = g.Session.console_packet

    def emulated_seconds(self) -> float:
        if self.frameless and self.emulating:
            self.emu_clock = round(self.emu_clock + 0.001, 6)
            self.polls_since_gtime += 1
            if self.stop_after is not None and self.polls_since_gtime >= self.stop_after:
                self.emulating = False
        return self.emu_clock

    def totalcycles(self) -> int:
        if self.stale_cycles is not None:
            return self.stale_cycles
        return self.frame * self.cycles_per_frame + self.cycles_offset

    def executed(self) -> None:
        """The cpu ran."""
        self.stale_cycles = None
        if self.reset_pending:
            self.reset_pending = False
            self.cycles_offset = -self.frame * self.cycles_per_frame

    def close(self) -> None:
        """A no-op."""

    def registers(self, *, thread: int) -> dict[str, int]:
        return dict(self.values)

    def current_pc(self) -> int:
        # The machine is somewhere else once it has run: the pc before `gtime` is not the one after.
        ran = any(c.startswith("gtime") for c in self.commands)
        return self.pcs[-1] if ran else self.pcs[0]

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        self.commands.append(command)
        if (listed := debugger_lists(self, command)) is not None:
            return listed
        if self.frameless and command.startswith("print ") and (
                named := re.search(r"\bframe\d*\b", command)):
            return (FIXTURES / f"print-{named.group(0)}-no-screen.txt").read_text()
        if self.stale_after_load and command.startswith("statesave "):
            self.saved_frames[command[10:]] = self.frame
        if self.stale_after_load and command.split()[0] in ("stateload", "sl"):
            self.stale_cycles = self.totalcycles()
            self.frame = self.saved_frames[command.split()[1].split(";")[0]]
        if self.stale_after_load and command in ("rewind", "rw"):
            self.stale_cycles = self.totalcycles()
            self.frame -= 1
        if self.stale_after_load and command == "softreset":
            self.stale_cycles = self.totalcycles()
            self.reset_pending = True
        if command.startswith("gtime"):
            self.executed()
            self.emulating = True
            self.polls_since_gtime = 0
            return ""
        if command == "gvblank":
            self.executed()
            # One frame per `gvblank`, unless the double is frozen.
            if not self.frozen:
                self.frame += 1
            return ""
        if command in ("print frame", "print frame,totalcycles"):
            if self.frame_answers is not None:
                answer = self.frame_answers.pop(0)
                if command == "print frame,totalcycles" and answer.strip():
                    answer += f" {self.totalcycles():x}"
                return answer + "\n"
            if self.emulating:
                self.frame += 1
                self.polls_since_gtime += 1
                if self.stop_after is not None and self.polls_since_gtime >= self.stop_after:
                    self.emulating = False
            if command == "print frame,totalcycles":
                return f"{self.frame:x} {self.totalcycles():x}\n"
            return f"{self.frame:x}\n"
        if command == "print totalcycles":
            return f"{self.totalcycles():x}\n"
        if command == "print curpc":
            return f"{self.current_pc():x}\n"
        return ""

    def _receive(self, timeout: float | None = None) -> str:
        self.received.append(timeout if timeout is not None else -1.0)
        raise g.SessionError("no answer within the drain")

    def halt(self) -> None:
        self.interrupted = True
        self.emulating = False

    def interrupt(self, timeout: float = 5.0) -> str:
        self.interrupted = True
        self.running = False
        self.stop_count += 1
        return "T05"

    def breakpoint(self, addr: int, remove: bool = False) -> None:
        if remove:
            self.bplist_rows = [r for r in self.bplist_rows if not r.endswith(f"@ {addr:06X}")]
        else:
            bplist_add(self, addr)

    def set_reg(self, name: str, value: int, *, thread: int) -> None:
        # The client's own judgement, as it makes it: a value too wide for the register
        # is refused before a byte reaches the stub.
        if value >= 1 << self.bits:
            raise g.SessionError(f"{name.upper()} is {self.bits} bits on this cpu and "
                                 f"{value:#x} does not fit it")
        self.values[name.upper()] = value

    def reg(self, name: str, *, thread: int) -> int:
        return self.values[name.upper()]

    def register_width(self, name: str) -> int:
        return self.bits

    def register_name(self, name: str) -> str:
        if name.upper() not in self.values:
            raise g.SessionError(f"unknown register {name!r}; this CPU has {list(self.values)}")
        return name.upper()

    def go(self) -> None:
        self.executed()
        self.running = True

    def poll_stop(self, timeout: float = 0.0) -> bool:
        if self.running:
            self.running = False
            self.stop_count += 1
            self.last_stop_packet = "T05"
        return True




_FRESH: Path = Path(tempfile.gettempdir()) / "mame-boundary-never-created"

MACHINE_INDEPENDENT: dict[str, Any] = {
    "read_memory": lambda: s.read_memory(ref="0x0", length=0),
    "disassemble": lambda: s.disassemble(ref="0x0", length=0),
    "find": lambda: s.find(ref="0x0", length=4, data_hex="zz"),
    "history": lambda: s.history(limit=0),
    "log": lambda: s.log(channel="emulator", pattern="[", limit=0),
    "log-channel": lambda: s.log(channel="nosuch", pattern="."),
    "memdump-length": lambda: s.memdump(
        ref="0x0", length=0, dest=str(_FRESH.parent / "mame-boundary-probe-never-written.bin")),
    "memdump-relative": lambda: s.memdump(ref="0x0", length=4, dest="relative.bin"),
    "memdump-nul": lambda: s.memdump(ref="0x0", length=4, dest=_tmp("pro\x00be.bin")),
    "snapshot-relative": lambda: s.snapshot(dest="relative.png"),
    "snapshot-nul": lambda: s.snapshot(dest=_tmp("pro\x00be.png")),
    "record-frames": lambda: s.record(frames=0, dest=_tmp("probe.avi")),
    "record-relative": lambda: s.record(frames=4, dest="relative.avi"),
    "audio_record-frames": lambda: s.audio_record(frames=0, dest=_tmp("probe.wav")),
    "audio_record-relative": lambda: s.audio_record(frames=4, dest="relative.wav"),
    "run_for": lambda: s.run_for(milliseconds=0),
    "step": lambda: s.step(count=0),
    "resume": lambda: s.resume(seconds=-1),
    "log_wait": lambda: s.log_wait(channel="emulator", pattern="[", seconds=0),
    # Tools whose arguments are judged before the gate only through the batch path or a bound.
    "run_for-seconds": lambda: s.run_for(milliseconds=100, seconds=0),
    "perform-a-step's-value": lambda: s.perform(steps=[{"op": "status"},
                                                       {"op": "step", "count": 0}]),
    "perform-a-step's-dest": lambda: s.perform(steps=[{"op": "status"},
                                                      {"op": "memdump", "ref": "0x0", "length": 8,
                                                       "dest": "relative.bin"}]),
    "drive-a-step's-value": lambda: s.drive(act=[{"op": "step", "count": 0}], pattern="."),
    # Tools with a machine-independent argument that is easy to leave past the gate: a bound, a
    # vocabulary, a file that must exist, a name that becomes a file name.
    "breakpoint_at-by-address": lambda: s.breakpoint_at(ref="PLAYER_X", by="address"),
    "breakpoint_at-pointer": lambda: s.breakpoint_at(ref="[4a0]+0x4"),
    "watch_add-negative-width": lambda: s.watch_add(ref="0x0", mode="show", length=-4),
    "watch_add-length": lambda: s.watch_add(ref="0x0", mode="show", length=9999),
    "record-seconds": lambda: s.record(frames=2, seconds=0),
    "audio_record-seconds": lambda: s.audio_record(frames=2, seconds=0),
    "input-seconds": lambda: s.input(port=":P1", field="Coin 1", seconds=0),
    "throttle-seconds": lambda: s.throttle(on=True, seconds=0),
    "resume-ceiling": lambda: s.resume(seconds=1e9),
    "rom_check-addr": lambda: s.rom_check(reference_rom=_abs("nope"), reference_addr="zz"),
    "rom_check-file": lambda: s.rom_check(reference_rom=str(_FRESH / "rom.bin")),
    "state_write save-name": lambda: s.state_write("save", name="../x"),
    "state_write load-name": lambda: s.state_write("load", name="../x"),
    "perform-a-snapshot-step's-dest": lambda: s.perform(
        steps=[{"op": "status"}, {"op": "snapshot", "dest": "relative.png"}]),
    "perform-a-lua-step's-script": lambda: s.perform(
        steps=[{"op": "status"}, {"op": "lua", "script": "   "}]),
}


MACHINE_DEPENDENT: dict[str, Any] = {
    "read_memory": lambda: s.read_memory(ref="no_such_symbol", length=4),
    "disassemble": lambda: s.disassemble(ref="no_such_symbol", length=4),
    "memdump": lambda: s.memdump(ref="no_such_symbol", length=4, dest=_tmp("probe.bin")),
    "run_to": lambda: s.run_to(ref="no_such_symbol"),
    "symbols_find": lambda: s.symbols_find(name="no_such_symbol"),
}




class _RunningSession(_OwnRegisterFile, SessionFields):
    """A session with the PROTOCOL's running state."""

    def __init__(self, scratch: Path, pcs: list[int] | None = None) -> None:
        self.scratch = scratch
        self.running = False
        self.stop_count = 0
        self.threads: dict[int, str] = {}
        self.last_stop_packet = ""
        self.broken: str | None = None
        self.stops_after_polls: int | None = None
        self.polls = 0
        self.pcs = pcs or [0xF2034, 0x4A0, 0x25A4]
        self.pointer_width = 4                   # a 68000: a pointer is a long
        self.frame = 100
        self.values = {"D0": 0x1234, "PC": 0xF2034}
        self.commands: list[str] = []
        self.armed: list[tuple[int, bool]] = []
        self.bplist_rows: list[str] = []
        self.bp_next_index = 1
        self.bp_devices: dict[int, str] | None = None   # a row's cpu, by index
        self.rplist_rows: list[tuple[int, str, bool]] = []   # what `rplist` lists
        self.rp_next_index = 1
        self.rp_devices: dict[int, str] = {}
        self.rp_errors: dict[str, str] = {}
        self.rp_print_errors: dict[str, str] = {}
        self.temps: dict[int, int] = {}
        self.exprs: dict[str, int] = {}
        self.writes = 0
        self.interrupted = 0
        self.byte_order = "big"
        self.packet_size: int | None = None
        self.emu_clock = 0.0
        self.visible_cpu = ":maincpu"
        self.ignoring: list[str] = []            # the cpus `ignore` lists
        self.no_map: set[int] = set()
        self.live: str | None = None

    # The real rules, not copies of them: they read nothing but `packet_size`.
    max_payload = g.Session.max_payload
    console_packet = g.Session.console_packet

    def emulated_seconds(self) -> float:
        return self.emu_clock

    def know_endianness(self, by_thread: dict[int, str]) -> None:
        self.endianness = dict(by_thread)

    def registers(self, *, thread: int) -> dict[str, int]:
        self._on("g", thread)
        return dict(self.values)

    def _on(self, packet: str, thread: int) -> None:
        """A register or memory packet for a thread other than the first, noted as
        `<packet>@<thread>`: what a case reads to know which cpu a call went through."""
        if thread != 1:
            self.commands.append(f"{packet}@{thread}")

    def current_pc(self) -> int:
        return self.pcs[min(self.stop_count, len(self.pcs) - 1)]

    def go(self) -> None:
        self.running = True
        self.polls = 0

    def _stop(self) -> None:
        self.running = False
        self.stop_count += 1
        self.frame += 60
        self.last_stop_packet = "T05"

    def poll_stop(self, timeout: float = 0.0) -> bool:
        if not self.running:
            return True
        self.polls += 1
        if self.stops_after_polls is not None:
            self.stops_after_polls -= 1
            if self.stops_after_polls <= 0:
                self.stops_after_polls = None
                self._stop()
                return True
        return False

    def interrupt(self, timeout: float = 5.0) -> str:
        self.interrupted += 1
        self._stop()
        return "T05"

    def step(self) -> str:
        self.running = True
        self._stop()
        return "T05"

    def breakpoint(self, addr: int, remove: bool = False) -> None:
        """What a plain `bp` does to the debugger's list."""
        self.armed.append((addr, False))
        bplist_add(self, addr)

    def make_visible(self, thread: int) -> None:
        """`Hc`, as the patched stub answers it."""
        self.commands.append(f"Hc{thread:x}")
        tag = self.threads[thread]
        if tag in self.ignoring:
            raise g.Refused(f"the stub refused `Hc{thread:x}`: E01")
        self.visible_cpu = tag

    def stopped_thread(self) -> int | None:
        """`?`: the thread of the cpu the last stop was on, which an `Hc` does not move."""
        self.commands.append("?")
        tag = self.live or self.visible_cpu
        return next((tid for tid, name in self.threads.items() if name == tag), None)

    def register_block(self, thread: int) -> str:
        """One thread's whole `g` reply, which a run changes."""
        self.commands.append(f"g{thread:x}")
        if thread in self.no_map:
            raise g.Refused("the stub refused `g`: E01")
        return f"{thread:08x}{self.frame:08x}"

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        self._on("m", thread)
        return bytes(n)

    def write(self, addr: int, data: bytes, *, thread: int) -> None:
        self._on("M", thread)
        self.writes += 1

    def reg(self, name: str, *, thread: int) -> int:
        self._on("p", thread)
        return self.values[name.upper()]

    def register_width(self, name: str) -> int:
        return 32

    def register_name(self, name: str) -> str:
        return name.upper()

    def set_reg(self, name: str, value: int, *, thread: int) -> None:
        self._on("P", thread)
        self.writes += 1
        self.values[name.upper()] = value

    def connect(self) -> None:
        pass

    def dial(self) -> None:
        pass

    def handshake(self, timeout: float | None = None) -> None:
        pass

    def close(self) -> None:
        pass

    def quit(self) -> None:
        self.commands.append("quit")

    def halt(self) -> None:
        self._stop()

    def reset(self) -> int:
        self.commands.append("softreset")
        self.writes += 1
        self._stop()
        return self.current_pc()

    def request(self, cmd: str, timeout: float | None = None) -> str:
        self.commands.append(cmd)
        return "OK"

    def self_check(self, rom: bytes, addr: int, n: int = 16, base: int = 0, *,
                   thread: int) -> None:
        self._on("rom", thread)

    def determinism(self, addr: int, n: int = 16, times: int = 5, *, thread: int) -> bool:
        return True

    def cost_per_query(self, addr: int, n: int = 16, times: int = 200, *,
                       thread: int) -> float:
        return 0.0

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        self.commands.append(command)
        if (listed := debugger_lists(self, command)) is not None:
            return listed
        if command.startswith("print "):
            values: list[str] = []
            for name in command[6:].split(","):
                if name == "frame":
                    values.append(f"{self.frame:x}")
                elif name == "curpc":
                    values.append(f"{self.current_pc():x}")
                elif name in self.exprs:
                    values.append(f"{self.exprs[name]:x}")
                elif name == "totalcycles":
                    values.append(f"{self.frame * 0x1000:x}")
                else:
                    return f"Error: unable to evaluate {name}\n"   # a double's spelling
            return " ".join(values) + "\n"
        if command.startswith("dasm "):
            name, addr = command[5:].split(",")[:2]      # a cpu may follow the length
            (self.scratch / name).write_text(f"{addr[2:]}: move.l d0,d1\n{addr[2:]}+2: rts\n")
            return ""
        return ""

    def monitor_owed(self, command: str, timeout: float = 10.0) -> None:
        self.monitor(command, timeout)


class _AliveProcess:
    """A process that is up, and nothing else: what `log_wait`'s liveness check reads."""

    pid = 4242

    def poll(self) -> int | None:
        return None


def _running(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
             ses: _RunningSession | None = None) -> _RunningSession:
    """Install a running-capable double, parked at its first stop the way `start` parks."""
    ses = ses or _RunningSession(tmp_path)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    use_table(monkeypatch, table={})
    monkeypatch.setattr(mstate.STATE, "proc", _AliveProcess())
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    # What `start` creates beside the session: a session-lived store and the stamp.
    monkeypatch.setattr(mstate.STATE, "store", dec.DeclarationStore("test", path=None))
    monkeypatch.setattr(mstate.STATE, "session_origin", "s1")
    monkeypatch.setattr(mstate.STATE, "first_cpu", ":maincpu")      # the doubles' first cpu
    monkeypatch.setattr(mstate.STATE, "fingerprints", {":maincpu": "fp-test"})
    monkeypatch.setattr(mstate.STATE, "armed_watches", {})
    monkeypatch.setattr(mstate.STATE, "tallies", {})
    monkeypatch.setattr(mstate.STATE, "controls", {})
    monkeypatch.setattr(mstate.STATE, "debuglog_mark", 0)
    running.record_park(ses, tmp_path)  # type: ignore[arg-type]
    return ses


class _GoneProcess:
    def poll(self) -> int | None:
        return 0


class _CrashedProcess:
    """A MAME that died of a signal while the session still held it."""

    pid = 4242

    def poll(self) -> int | None:
        return -11


class _RecordingCtx:
    """The SDK's `Context` as far as progress goes: every report, in order."""

    def __init__(self) -> None:
        self.got: list[tuple[float, float | None, str | None]] = []

    async def report_progress(self, progress: float, total: float | None = None,
                              message: str | None = None) -> None:
        self.got.append((progress, total, message))


def _query_that_outlives_the_boot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                  ) -> tuple[dict[str, str], list[Any]]:
    """A binary whose `-listxml` sleeps past any boot."""
    args = _boot_args(tmp_path, bytes(range(64)))
    rewrite_mame(args["binary"], "if sys.argv[1:2] == ['-version']:\n"
                 "    print('0.0 (a slow query)')\n    sys.exit(0)\ntime.sleep(30)")
    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "no-helper"))
    held: list[Any] = []
    real_ask = machine.ask_listxml

    def remembered(binary: str, system: str) -> Any:
        held.append(real_ask(binary, system))
        return held[-1]

    monkeypatch.setattr(machine, "ask_listxml", remembered)
    return args, held


class _ClosedPresence:
    """A session's presence as `kill` meets it: closed once, and nothing else asked of it."""

    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class _AlreadyDead:
    """A process that exited on its own before `close` was called: `poll` knows the code."""

    pid = 77

    def poll(self) -> int | None:
        return -11


def _boot_judged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, session: type,
                 spawned: type, *, port: int, wait: float, presence: bool) -> Any:
    """`boot`'s judged arguments, with `session` as the stub and `spawned` as the process."""
    import subprocess
    from types import SimpleNamespace

    monkeypatch.setattr(g, "Session", session)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned())
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "proc", None)
    return SimpleNamespace(
        state_dir="", boot_lua="", env={}, throttle_from_frame=0, binary="mame",
        system="sys", rompath=str(tmp_path), port=port, flags=[], inipath="", wait=wait,
        ref=tmp_path / "ref.bin", ref_addr=0, ref_base=0, cfg=None, background=False,
        presence=presence, view="")


def _boot_against(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                  exit_code: int | None, wait: float, presence: bool = False) -> Any:
    """`boot` against a gdbstub that refuses every connection and a process whose `poll`
    answers `exit_code` (None: alive). Hands back the refusal it raised."""

    class Refusing:
        def __init__(self, port: int, owner: object = None) -> None:
            self.port = port

        def dial(self) -> None:
            raise OSError("connection refused")

    class Spawned:
        pid = 1

        def poll(self) -> int | None:
            return exit_code

    judged = _boot_judged(monkeypatch, tmp_path, Refusing, Spawned, port=1, wait=wait,
                          presence=presence)
    with pytest.raises(mstate.Invalid) as e:
        launch.boot(judged)
    assert mstate.STATE.ses is None
    return e.value


def _window(monkeypatch: pytest.MonkeyPatch, wall_s: float, emulated_s: float) -> Any:
    """An open run window `wall_s` and `emulated_s` long, on a double whose clock is read."""
    ses = _RegisterSession(bits=32)
    ses.emu_clock = 1.0 + emulated_s
    monkeypatch.setattr(mstate.STATE, "run_release", {"emulated": 1.0, "wall": 0.0})
    monkeypatch.setattr("mame_running.time.monotonic", lambda: wall_s)
    return ses



CFG_OK = """<?xml version="1.0"?>
<mameconfig version="10">
    <system name="m68k">
        <input>
            <port tag=":P1" type="P1_BUTTON1" mask="64" defvalue="64">
                <newseq type="standard">KEYCODE_DOWN</newseq>
            </port>
        </input>
    </system>
</mameconfig>
"""


def _refusal_text(fn: Any, *a: Any) -> str:
    """The words of the `Invalid` `fn(*a)` raises, or a failure saying it raised nothing."""
    try:
        fn(*a)
    except mstate.Invalid as e:
        return str(e)
    raise AssertionError(f"{fn.__name__}{a} refused nothing, so this case examined nothing")




def _by_frames(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kw: Any) -> _RegisterSession:
    ses = _RegisterSession(bits=32, frame=10, **kw)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    monkeypatch.setattr(advance, "VBLANK_SETTLE_S", 0.0)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    return ses


class _ScriptedClock(mprogress.Ticker):
    """A bound that runs out when the test says so, one answer per look."""

    answers: list[bool] = []

    def expired(self) -> bool:
        return self.answers.pop(0) if self.answers else True
