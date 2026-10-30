"""Persistent debug session against MAME's gdbstub, over the GDB remote protocol (stdlib only).

Register numbers come from the target description XML, never guessed. `self_check` and
`determinism` are the honesty checks; `start` refuses a session that fails the first.
"""

from __future__ import annotations

import re
import socket
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol

from scry_core import prose
from scry_core import value_format as vf
from scry_core.reply_contract import Invalid

OTHER_DEVICE_FEATURE = "mame./"


class SessionError(RuntimeError):
    """Anything that means the session cannot be trusted. `reply` is the stub's answer, if any;
    `phase` names the handshake question that failed."""

    phase: str = "unknown"
    reply: str = ""


class Timeout(SessionError):
    """No answer within the bound; its own type so `poll_stop` can tell it."""


class ConnectionFailed(SessionError):
    """The connection is gone: reset, broken pipe, closed by the stub."""


class Refused(SessionError):
    """The stub answered no (an `E` reply or too few bytes): the channel kept its place."""


class NoRegisters(SessionError):
    """A well-formed target description that declares no register."""


class BadTargetXml(SessionError):
    """A target description that does not parse, or has non-numeric register numbers or sizes."""


class DialFailed(SessionError):
    """The TCP connection was made and its first byte could not be sent (`Session.dial`)."""


class ExpressionRefused(SessionError):
    """The console refused an expression: an answer about this machine, not a failed channel."""


class Mismatch(SessionError):
    """The stub's bytes differ from a known answer: a verdict, not a failed channel."""


class Unsupported(SessionError):
    """The stub answered the empty packet, the protocol's "unsupported": nothing was done."""


class CommandTooLong(SessionError):
    """A console command too long for the stub's packet size, refused before sending."""

    def __init__(self, command_chars: int, limit_chars: int) -> None:
        super().__init__(f"the console command is {command_chars} characters and the stub's "
                         f"packet size carries at most {limit_chars}: the stub would drop it "
                         "unanswered, so it was not sent")
        self.command_chars = command_chars
        self.limit_chars = limit_chars


class UnknownByteOrder(SessionError):
    """A cpu whose byte order cannot be known without guessing (`_BYTE_ORDER`): a refusal."""


class NotStopped(SessionError):
    """Raised by the server's gate, never by the client."""


REPLY_KEPT_CHARS = 200


@contextmanager
def _phase(name: str) -> Iterator[None]:
    try:
        yield
    except SessionError as e:
        e.phase, e.reply = name, e.reply[:REPLY_KEPT_CHARS]
        raise


def _within(deadline: float | None, arriving: str) -> None:
    """`Timeout` once `deadline` passed with `arriving`, a paged answer, still incomplete."""
    if deadline is not None and time.time() >= deadline:
        raise Timeout(f"{arriving} was still arriving at the handshake's deadline: the stub had "
                      "not sent its last page")


def _checksum(body: str) -> str:
    return f"{sum(body.encode()) & 0xFF:02x}"


def packet_size(supported: str) -> int | None:
    """The largest packet the stub takes (`PacketSize=<hex>`), or None; a longer one is dropped
    unanswered."""
    for feature in supported.split(";"):
        name, _, value = feature.partition("=")
        if name == "PacketSize" and value:
            try:
                return int(value, 16)
            except ValueError:
                raise SessionError(f"`qSupported` advertised PacketSize={value!r}, which is not "
                                   "hex") from None
    return None


# MAME's `MAX_LINE_LENGTH`: the console wraps every line at this column.
CONSOLE_WRAP_COLS = 250


def unwrap_console(text: str, starts: re.Pattern[str]) -> list[str]:
    """The logical lines of a console reply, rebuilt from MAME's wrapped pieces; `starts` matches
    a line of the caller's answer where the geometry cannot decide (`_continues`)."""
    lines: list[str] = []
    piece: str | None = None
    for line in text.split("\n"):
        if not line:
            piece = None
            continue
        if piece is not None and _continues(piece, line, starts):
            lines[-1] += ("" if len(piece) == CONSOLE_WRAP_COLS else " ") + line
        else:
            lines.append(line)
        piece = line
    return lines


def _continues(piece: str, line: str, starts: re.Pattern[str]) -> bool:
    if len(piece) == CONSOLE_WRAP_COLS:
        return True
    carried = CONSOLE_WRAP_COLS - 1 - len(piece)
    if carried == 0:
        return not starts.match(line)
    return len(line) >= carried and " " not in line[:carried]


_STOP_THREAD = re.compile(r"(?:^T[0-9a-fA-F]{2}|;)thread:([0-9a-fA-F]+);")


def _is_stop_reply(packet: str) -> bool:
    """Whether `packet` is a stop reply; refuses the stop shapes MAME's stub never sends."""
    if re.match(r"^S[0-9a-fA-F]{2}|^[WX]", packet):
        raise SessionError(f"the stub sent {packet[:32]!r}, a stop reply of a shape MAME's "
                           "stub never sends: the session cannot be trusted")
    return bool(re.match(r"^T[0-9a-fA-F]{2}", packet))


def _connection_failed(error: OSError) -> ConnectionFailed:
    """The `ConnectionFailed` a socket failure becomes (a read that ran out is `Timeout`)."""
    return ConnectionFailed(f"the connection failed: {error}")


def _label(cmd: str) -> str:
    if cmd.startswith("qRcmd,"):
        try:
            return bytes.fromhex(cmd[len("qRcmd,"):]).decode(errors="replace")
        except ValueError:
            pass
    return cmd


def _refuse_run_length(body: str) -> str:
    """`body`, or a refusal if it holds the run-length marker `*`: this stub never compresses."""
    at = body.find("*")
    if at >= 0:
        raise SessionError(f"the reply carries the run-length marker `*` at position {at} of "
                           f"a {len(body)}-character packet (ends {body[-32:]!r}): this stub "
                           "never compresses, so the reply cannot be trusted")
    return body


@dataclass
class Register:
    name: str
    number: int
    bits: int
    kind: str = "int"


# A register arrives in the target's byte order, which MAME's stub swaps by the endianness of the
# cpu's program space; the wrong decode gives a plausible wrong number. The description carries
# none, so `Session.know_endianness` takes MAME's reading and the rows below cross-check it (a
# disagreement refuses). `mips` has no row: MAME maps both endiannesses onto it.
_BYTE_ORDER: dict[str, Literal["little", "big"]] = {
    "i386": "little",
    "i8086": "little",
    "m68k": "big",
    "m6502": "little",
    "z80": "little",
    "m6809": "big",
    "arm": "little",
    "powerpc:common": "big",
    "score7": "little",
    "nios2": "little",
}


@dataclass(frozen=True)
class Layout:
    """One cpu's register file, as its thread's target description declares it."""

    regs: dict[str, Register]
    other_digits: int              # hex digits the `g` reply spends on other devices' state
    arch: str
    names: list[str]
    mame_order: str = ""

    @classmethod
    def parse(cls, xml: str) -> Layout:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            bad = BadTargetXml(f"target.xml is not a well-formed document: {e}")
            bad.reply = xml
            raise bad from None
        arch = root.findtext("architecture")
        regs: dict[str, Register] = {}
        other_digits = 0
        # Another device's state (feature `mame./<tag>`) is no register of this cpu: only counted.
        others = {id(r) for f in root.iter("feature")
                  if f.get("name", "").startswith(OTHER_DEVICE_FEATURE) for r in f.iter("reg")}
        n, last_own, first_other = 0, -1, sys.maxsize
        for reg in root.iter("reg"):
            try:
                num = int(reg.get("regnum", n))
                bits = int(reg.get("bitsize", "32"))
            except ValueError as e:
                bad = BadTargetXml(f"target.xml does not describe its registers: a register's "
                                   f"number or size is not a number ({e})")
                bad.reply = xml
                raise bad from None
            name = reg.get("name", f"r{num}")
            n = num + 1
            if id(reg) in others:
                other_digits += bits // 4
                first_other = min(first_other, num)
                continue
            last_own = max(last_own, num)
            regs[name.upper()] = Register(name, num, bits, reg.get("type", "int"))
        if not regs:
            empty = NoRegisters("target.xml declares no registers")
            empty.reply = xml
            raise empty
        # `registers` cuts `g` by position, so another device numbered first is refused.
        if first_other < last_own:
            raise SessionError(
                f"target.xml numbers another device's register ({first_other}) before this "
                f"cpu's last one ({last_own}), so a `g` reply cannot be cut by position")

        # m68k's XML says FP, SP, PS; everyone else says A6, A7, SR.
        for alias, real in (("A6", "FP"), ("A7", "SP"), ("SR", "PS"), ("USP", "SP")):
            if real in regs and alias not in regs:
                regs[alias] = regs[real]
        numbered = {r.number: n for n, r in regs.items() if r.name.upper() == n}
        return cls(regs, other_digits, arch.strip() if arch else "",
                   [numbered[k] for k in sorted(numbered)])

    @property
    def register_names(self) -> list[str]:
        return list(self.names)

    @property
    def register_bits(self) -> dict[str, int]:
        """Each listed register's declared width (no aliases)."""
        return {n: self.regs[n].bits for n in self.register_names}

    def register_name(self, name: str) -> str:
        """The stub's own name for `name`, or its `E`-prefixed 16-bit spelling (a V30's `AX` is
        `EAX`), else a refusal."""
        upper = name.upper()
        if upper in self.regs:
            return upper
        wide = f"E{upper}"
        if wide in self.regs and self.regs[wide].bits == 16:
            return wide
        raise SessionError(f"unknown register {name!r}; this CPU has {self.register_names}")

    def register_width(self, name: str) -> int:
        return self.regs[self.register_name(name)].bits

    @property
    def pointer_width(self) -> int:
        """Bytes of a pointer held in memory: the width of `sp`/`esp`/`rsp` (the pc is a 32-bit
        linear address on a V30)."""
        for name in ("SP", "ESP", "RSP"):
            if name in self.regs and self.regs[name].name.upper() == name:
                return self.regs[name].bits // 8
        return self.register_width(self.pc_name) // 8

    @property
    def pc_name(self) -> str:
        """The program counter's name, from target.xml: GDB fixes it per architecture (`pc`, `eip`,
        `rip`). `code_ptr` is only the fallback, as three families mark a second register with it.
        Refuses rather than guess."""
        for spelling in ("PC", "EIP", "RIP"):
            if spelling in self.regs:
                return spelling
        pointers = {
            n for n, r in self.regs.items()
            if r.kind == "code_ptr" and r.name.upper() == n
        }
        if len(pointers) == 1:
            return pointers.pop()
        raise SessionError(
            "cannot tell which register is the program counter: none is named PC/EIP/RIP "
            f"and the code_ptr registers are {sorted(pointers)}; this cpu has "
            f"{self.register_names}"
        )

    @property
    def byte_order(self) -> Literal["little", "big"]:
        """`little` or `big`: MAME's reading, checked against `_BYTE_ORDER`, else a refusal."""
        arch = self.arch or "(none declared)"
        if self.mame_order not in ("little", "big"):
            raise UnknownByteOrder(
                f"MAME's endianness of this cpu's program space (architecture {arch!r}) was not "
                f"read at start, and guessing the byte order returns a plausible wrong number "
                f"rather than an error"
            )
        order: Literal["little", "big"] = "little" if self.mame_order == "little" else "big"
        measured = _BYTE_ORDER.get(self.arch)
        if measured is not None and measured != order:
            raise UnknownByteOrder(
                f"MAME declares this cpu's program space {order}-endian, and architecture "
                f"{arch!r} was measured {measured}-endian here: one of the two is wrong for "
                f"this cpu, so neither decodes it"
            )
        return order


REQUEST_TIMEOUT_S = 10.0
#: How long a drain listens for a stop packet the stub should not send unasked.
STOP_REPLY_DRAIN_S = 0.1


class Owner(Protocol):
    """Proof that a connection reached the emulator this server spawned."""

    def before_dial(self) -> None: ...

    def after_dial(self, local_port: int) -> None: ...


@dataclass
class Session:
    """One live connection, one machine at a time."""

    host: str = "127.0.0.1"
    port: int = 23946
    timeout: float = REQUEST_TIMEOUT_S
    owner: Owner | None = field(default=None, repr=False)
    _sock: socket.socket | None = field(default=None, repr=False)
    _buf: bytes = field(default=b"", repr=False)
    _layouts: dict[int, Layout] = field(default_factory=dict, repr=False)
    writes: int = 0  # how many times this session has ALTERED the machine
    packet_size: int | None = None
    # GDB thread id -> cpu tag; empty on a stub serving the first cpu alone.
    threads: dict[int, str] = field(default_factory=dict)
    endianness: dict[int, str] = field(default_factory=dict)
    # The thread the stub serves `g`, `p`, `m` for; a stop naming another moves it.
    _served_thread: int = 1
    # The socket is the only witness of the running state.
    running: bool = False
    stop_count: int = 0
    last_stop_packet: str = ""
    # Why the session broke, or None; only a new session clears it.
    broken: str | None = None
    # An `owed` request that ran out: the next request reads and drops its answer.
    _owed: str | None = None

    def drain_stop_reply(self) -> None:
        with suppress(SessionError):
            self._receive(STOP_REPLY_DRAIN_S)

    def latch(self, reason: str) -> None:
        """Mark the session broken; the first reason stands."""
        self.broken = self.broken or reason

    def dial(self) -> None:
        """The TCP connection alone; MAME's stub serves one per session. With an `owner`, the
        listener and the far end are proved before any byte is sent. A first byte that cannot be
        sent is `DialFailed`."""
        if self.owner is not None:
            self.owner.before_dial()
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.owner is not None:
            try:
                self.owner.after_dial(self._sock.getsockname()[1])
            except BaseException:
                self.close()
                raise
        try:
            self._sock.sendall(b"+")
        except OSError as e:
            self.close()
            raise DialFailed(f"the connection was made and its first byte could not be sent: "
                             f"{e}") from e

    def handshake(self, timeout: float | None = None) -> None:
        """Ask the stub its packet size, first cpu's registers and threads. `timeout` bounds the
        first answer (it comes once the boot reaches the debugger). A failure sets `phase`."""
        began = time.time()
        with _phase("qSupported"):
            self.packet_size = packet_size(self.request("qSupported", timeout))
        budget = timeout if timeout is not None else self.timeout
        deadline = max(began + budget, time.time() + self.timeout)
        with _phase("target.xml"):
            self.layout(1, deadline=deadline)
        with _phase("threads"):
            self.threads = self._read_threads(deadline)

    @property
    def local_port(self) -> int | None:
        return self._sock.getsockname()[1] if self._sock else None

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    def _refuse_broken(self) -> None:
        if self.broken is not None:
            raise SessionError(f"this session broke and is asked nothing more: {self.broken}")

    def _send(self, cmd: str) -> None:
        self._collect_owed()
        self._transmit(f"${cmd}#{_checksum(cmd)}".encode())

    def _transmit(self, data: bytes) -> None:
        if not self._sock:
            raise SessionError("the session is not connected")
        try:
            self._sock.sendall(data)
        except OSError as e:
            raise _connection_failed(e) from e

    def _receive(self, timeout: float | None = None) -> str:
        """One complete reply, or a `Timeout`.

        No checksum is verified and no `-` sent: loopback TCP, and no bad frame has been seen."""
        assert self._sock
        timeout = timeout if timeout is not None else self.timeout
        deadline = time.time() + timeout
        while True:
            i = self._buf.find(b"#")
            if i >= 0 and len(self._buf) >= i + 3:
                raw = self._buf[: i + 3]
                self._buf = self._buf[i + 3 :]
                body = raw.decode(errors="replace").lstrip("+-").lstrip("$")[:-3]
                self._transmit(b"+")
                return _refuse_run_length(body)
            # Ask the socket at least once, even at timeout 0 (`poll_stop`).
            try:
                self._sock.settimeout(max(0.0, deadline - time.time()))
                chunk = self._sock.recv(65536)
            except (TimeoutError, BlockingIOError):
                if time.time() >= deadline:
                    raise Timeout(
                        f"no answer within {timeout} s: the machine may be "
                        "RUNNING (use `resume`) or the stub may have hung"
                    ) from None
                continue
            except OSError as e:
                raise _connection_failed(e) from e
            if not chunk:
                raise ConnectionFailed("the stub closed the connection")
            self._buf += chunk

    def request(self, cmd: str, timeout: float | None = None) -> str:
        """`cmd` sent and its answer read within `timeout`; running out latches the session."""
        return self._ask(cmd, timeout)

    def _ask(self, cmd: str, timeout: float | None, owed: bool = False) -> str:
        """`request`'s body; one sent `owed` that runs out is set aside, not latched."""
        self._refuse_broken()
        if owed and self._owed is not None:
            # Not sent while another is owed: collecting it could latch over the repaint.
            raise Timeout(f"`{_label(self._owed)}` is still owed its answer, so "
                          f"`{_label(cmd)}` was not sent")
        self._send(cmd)
        try:
            r = self._receive(timeout)
            # A stop reply can land mid-conversation: note it, read the real reply.
            while self.running and _is_stop_reply(r):
                self._note_stop(r)
                r = self._receive(timeout)
        except Timeout as e:
            if owed:
                self._owed = cmd
                raise
            # Latched here and never resynced: a `p11` would be read back as `p0`.
            waited = timeout if timeout is not None else self.timeout
            self.latch(f"`{_label(cmd)}` got no answer within {waited} s, and the answer it is "
                       "still owed would be read as the next request's, so no reply on this "
                       "connection can be paired with its request any more")
            raise Timeout(self.broken) from e
        if r.startswith("E") and len(r) == 3:
            refused = Refused(f"the stub refused `{cmd}`: {r}")
            refused.reply = r
            raise refused
        # The empty packet is 'unsupported', not 'done': reading it as success hid writes that
        # never happened.
        if r == "":
            raise Unsupported(
                f"the stub does not support `{cmd}`: it answered the empty packet, which "
                f"the remote protocol defines as 'unsupported', so nothing was done"
            )
        return r

    def _note_stop(self, packet: str) -> None:
        self.running = False
        self.stop_count += 1
        self.last_stop_packet = packet
        if (m := _STOP_THREAD.search(packet)) is not None:
            self._served_thread = int(m.group(1), 16)

    def _on_thread(self, thread: int, cmd: str) -> str:
        """`cmd`, a register or memory packet, answered for `thread`'s cpu: the one door for them.
        The stub keeps one `Hg` selection, changed only when needed."""
        if thread != 1 and thread not in self.threads:
            raise ValueError(f"thread {thread} is not one this stub serves "
                             f"({sorted(self.threads) or [1]})")
        if self._served_thread != thread:
            self.request(f"Hg{thread:x}")
            self._served_thread = thread
        return self.request(cmd)

    def register_block(self, thread: int) -> str:
        """Thread's whole `g` reply, compared whole and never cut by position."""
        return self._on_thread(thread, "g")

    def stopped_thread(self) -> int | None:
        """The thread the machine last stopped on, off `?`, or None."""
        m = _STOP_THREAD.search(self.request("?"))
        if m is None:
            return None
        self._served_thread = int(m.group(1), 16)
        return self._served_thread

    def make_visible(self, thread: int) -> None:
        """`Hc<thread>`: makes that cpu the visible one without releasing the machine."""
        self.request(f"Hc{thread:x}")

    def _read_threads(self, deadline: float | None = None) -> dict[int, str]:
        """Which GDB thread is which cpu, as the stub names them; empty for a stub naming none."""
        ids: list[int] = []
        page = self.request("qfThreadInfo")
        while page.startswith("m"):
            try:
                ids += [int(tid, 16) for tid in page[1:].split(",") if tid]
            except ValueError:
                raise SessionError(f"the stub listed its threads as {page!r}, which are not "
                                   "hex ids") from None
            _within(deadline, "the thread list")
            page = self.request("qsThreadInfo")
        threads: dict[int, str] = {}
        for tid in ids:
            try:
                named = self.request(f"qThreadExtraInfo,{tid:x}")
            except Unsupported:
                return {}
            try:
                threads[tid] = bytes.fromhex(named).decode("ascii")
            except (ValueError, UnicodeDecodeError):
                raise SessionError(f"the stub named thread {tid} with {named!r}, which is not hex "
                                   "text: its cpu is unknown rather than guessed") from None
        return threads

    def current_pc(self) -> int:
        """The pc as an address a breakpoint can take, asked of MAME's `curpc` rather than computed
        (`cs*16+ip` is wrong with descriptor tables)."""
        raw = self.monitor("print curpc").strip().split()
        if not raw:
            raise SessionError("MAME's console answered nothing for `print curpc`")
        try:
            return int(raw[0], 16)
        except ValueError as exc:
            raise SessionError(
                f"MAME's console did not answer `print curpc` with a number: {raw[0]!r}"
            ) from exc

    def layout(self, thread: int, deadline: float | None = None) -> Layout:
        """`thread`'s register file off its own target description, read once."""
        if thread not in self._layouts:
            parts: list[str] = []
            off = 0
            while True:
                _within(deadline, "target.xml")
                chunk = self._on_thread(thread, f"qXfer:features:read:target.xml:{off:x},400")
                parts.append(chunk[1:])
                if chunk[0] == "l":
                    break
                off += len(chunk) - 1
            self._layouts[thread] = replace(Layout.parse("".join(parts)),
                                            mame_order=self.endianness.get(thread, ""))
        return self._layouts[thread]

    def know_endianness(self, by_thread: dict[int, str]) -> None:
        self.endianness.update(by_thread)
        for thread, lay in self._layouts.items():
            self._layouts[thread] = replace(lay, mame_order=self.endianness.get(thread, ""))

    def reg(self, name: str, *, thread: int) -> int:
        lay = self.layout(thread)
        r = lay.regs[lay.register_name(name)]
        return int.from_bytes(bytes.fromhex(self._on_thread(thread, f"p{r.number:x}")),
                              lay.byte_order)

    def registers(self, *, thread: int) -> dict[str, int]:
        lay = self.layout(thread)
        return {n: int.from_bytes(bytes.fromhex(text), lay.byte_order)
                for n, text in self.register_texts(thread=thread).items()}

    def register_texts(self, *, thread: int) -> dict[str, str]:
        """Every register as the stub prints it, by name in number order: the `g` reply cut by the
        declared widths. A reply of any other length is refused."""
        lay = self.layout(thread)
        names = lay.register_names
        if not names:
            return {}
        digits = {n: lay.regs[n].bits // 4 for n in names}
        reply = self._on_thread(thread, "g")
        if len(reply) != sum(digits.values()) + lay.other_digits:
            raise SessionError(
                f"the stub answered `g` with {len(reply)} hex digits where the {len(names)} "
                f"registers of this cpu take {sum(digits.values())} and the other devices' "
                f"state {lay.other_digits}: {reply[:64]!r}"
            )
        out: dict[str, str] = {}
        pos = 0
        for n in names:
            out[n], pos = reply[pos:pos + digits[n]], pos + digits[n]
        return out

    def set_reg(self, name: str, value: int, *, thread: int) -> None:
        lay = self.layout(thread)
        r = lay.regs[lay.register_name(name)]
        # Convert before counting: a value too wide must not mark the machine `altered`. `write`
        # counts first because its packet goes out before anything can fail.
        try:
            payload = value.to_bytes(r.bits // 8, lay.byte_order).hex()
        except OverflowError:
            # Name the width: the bare overflow message reads as a broken tool.
            raise SessionError(
                f"{r.name.upper()} is {r.bits} bits on this cpu and {value:#x} does not fit it"
            ) from None
        self.writes += 1
        self._on_thread(thread, f"P{r.number:x}={payload}")

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        return bytes.fromhex(self._on_thread(thread, f"m{addr:x},{n:x}"))

    def max_payload(self) -> int | None:
        """The largest packet body the stub takes (its advertised size), or None."""
        return self.packet_size

    def write(self, addr: int, data: bytes, *, thread: int) -> None:
        """One write, in as many `M` packets as the stub's size needs."""
        if not data:
            return
        header = len(f"M{addr + len(data):x},{len(data):x}:")
        payload = self.max_payload()
        step = len(data) if payload is None else (payload - header) // 2
        if step < 1:
            raise SessionError(f"the stub's packet size {self.packet_size} cannot carry an `M` "
                               f"packet's header and one byte at {addr:#x}")
        self.writes += 1
        for at in range(0, len(data), step):
            chunk = data[at:at + step]
            self._on_thread(thread, f"M{addr + at:x},{len(chunk):x}:{chunk.hex()}")

    def go(self) -> None:
        """Let the machine run and return at once; the stop reply is read by the next call."""
        self._send("c")
        self.running = True

    def poll_stop(self, timeout: float = 0.0) -> bool:
        """Whether the machine is stopped; False means still running after `timeout`."""
        if not self.running or not self._running_after_owed():
            return True
        try:
            packet = self._receive(timeout)
        except Timeout:
            return False
        self._expect_stop(packet)
        return True

    def _expect_stop(self, packet: str) -> str:
        """`packet` noted as a stop, or a refusal of anything else."""
        if not _is_stop_reply(packet):
            raise SessionError(f"the stub sent {packet!r} while the machine ran, which is not "
                               "a stop reply: the session cannot be trusted")
        self._note_stop(packet)
        return packet

    def resume(self, timeout: float = 30.0) -> str:
        """Run until something stops us, waiting up to `timeout`; on a timeout `running` stays."""
        self.go()
        return self._expect_stop(self._receive(timeout))

    def halt(self) -> None:
        """Stop a machine a console command set running (`gtime`), where no stop reply comes; the
        caller proves the stop by the frame counter."""
        self._refuse_broken()
        self._collect_owed()
        self._transmit(b"\x03")

    def interrupt(self, timeout: float = 5.0) -> str:
        """Stop a running machine, leaving the session usable: after a `resume` timeout the stop
        reply would land in front of the next answer. A stopped machine is sent nothing."""
        if not self._sock:
            raise SessionError("the session is not connected")
        if not self.running or not self._running_after_owed():
            return self.last_stop_packet
        self._transmit(b"\x03")
        return self._expect_stop(self._receive(timeout))

    def step(self) -> str:
        self._refuse_broken()
        self._send("s")
        self.running = True
        return self._expect_stop(self._receive())

    def console_packet(self, command: str) -> str:
        """The `qRcmd` packet for `command`, or `CommandTooLong` past `max_payload`."""
        packet = "qRcmd," + command.encode().hex()
        payload = self.max_payload()
        if payload is not None and len(packet) > payload:
            raise CommandTooLong(len(command.encode()),
                                 max(0, (payload - len("qRcmd,")) // 2))
        return packet

    def _running_after_owed(self) -> bool:
        self._collect_owed()
        return self.running

    def _collect_owed(self) -> None:
        """Read and drop the answer an `owed` request ran out on; never coming, it latches."""
        if self._owed is None:
            return
        owed, self._owed = self._owed, None
        try:
            r = self._receive(self.timeout)
            while self.running and _is_stop_reply(r):
                self._note_stop(r)
                r = self._receive(self.timeout)
        except Timeout as e:
            self.latch(f"`{_label(owed)}` was still owed an answer that never came, so no reply "
                       "on this connection can be paired with its request any more")
            raise Timeout(self.broken) from e

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        """Run any MAME debugger command through `qRcmd` and return its text."""
        r = self.request(self.console_packet(command), timeout=timeout)
        try:
            return bytes.fromhex(r).decode(errors="replace")
        except ValueError:
            return r

    def monitor_owed(self, command: str, timeout: float = 10.0) -> None:
        """`monitor` for a command whose answer nobody reads: running out latches nothing."""
        self._ask(self.console_packet(command), timeout, owed=True)

    def emulated_seconds(self) -> float | None:
        """The elapsed emulated time off the console's `time`, or None."""
        text = self.monitor("time")
        m = re.search(r"[-+]?\d+\.\d+|\b\d+\b", text)
        return float(m.group(0)) if m else None

    def quit(self) -> None:
        """Ask MAME to exit cleanly (writes `cfg/` and `nvram/`): the debugger's `quit` only
        schedules it, so a bare `c` follows."""
        self.monitor("quit")
        self._send("c")

    def reset(self) -> int:
        """A soft reset, applied, and the pc it left the machine at (`softreset` fires on the next
        run, so one `step` lands on the boot pc)."""
        # Counted before sending: a failed `softreset` may still have been scheduled.
        self.writes += 1
        self.monitor("softreset")
        self.step()
        return self.current_pc()

    def self_check(self, rom: bytes, addr: int, n: int = 16, base: int = 0, *,
                   thread: int) -> None:
        """Known-answer test: what the machine reports must match the ROM file; `base` is where the
        file's first byte sits in cpu space."""
        lo = reference_window(len(rom), addr, n, base)
        live = self.read(addr, n, thread=thread)
        expected = rom[lo : lo + n]
        if live != expected:
            raise Mismatch(
                f"the session LIES: at 0x{addr:x} it returns {live.hex()} and the ROM on disk "
                f"holds {expected.hex()}. Nothing measured here is worth anything."
            )

    def determinism(self, addr: int, n: int = 16, times: int = 5, *, thread: int) -> bool:
        first = self.read(addr, n, thread=thread)
        return all(self.read(addr, n, thread=thread) == first for _ in range(times - 1))

    def cost_per_query(self, addr: int, n: int = 16, times: int = 200, *,
                       thread: int) -> float:
        t0 = time.time()
        for _ in range(times):
            self.read(addr, n, thread=thread)
        return (time.time() - t0) / times


def _span_add(spans: dict[str, tuple[int, int]], klass: str, addr: int) -> None:
    lo, hi = spans.get(klass, (addr, addr))
    spans[klass] = (min(lo, addr), max(hi, addr))


class AmbiguousRef(Invalid):
    """A name the table gives twice, looked up as if it named one address."""


class Names(dict[str, int]):
    """A table's forward map, name (upper-case) to the address of its first row.

    A name given twice is kept, with every row (`rows`, the file's order) and its addresses
    (`ambiguous`); looking it up is refused, naming them, so no site guesses between two."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, int]] = []
        self.row_classes: list[str] = []
        self.ambiguous: dict[str, list[int]] = {}

    def add(self, key: str, addr: int, klass: str = "") -> None:
        """Take one row; a repeat at the same address is the same symbol, not a second one."""
        self.rows.append((key, addr))
        self.row_classes.append(klass)
        if key not in self:
            super().__setitem__(key, addr)
        elif addr not in (held := self.ambiguous.get(key, [super().__getitem__(key)])):
            self.ambiguous[key] = [*held, addr]

    def _refuse(self, key: str) -> AmbiguousRef:
        return AmbiguousRef("ambiguous_ref", prose.ambiguous_name(
            key, [f"{a:#x}" for a in self.ambiguous[key]], "this table"))

    def __getitem__(self, key: str) -> int:
        if key in self.ambiguous:
            raise self._refuse(key)
        return super().__getitem__(key)

    def get(self, key: str, default: int | None = None) -> int | None:  # type: ignore[override]
        if key in self.ambiguous:
            raise self._refuse(key)
        return super().get(key, default)


def rows_in_class(table: dict[str, int], classes: dict[str, str],
                  klass: str) -> list[tuple[int, str]]:
    """`(address, name)` of every row of `klass`, in the file's order: a repeated name is placed
    by each row's own class."""
    if isinstance(table, Names):
        return [(a, n) for (n, a), c in zip(table.rows, table.row_classes, strict=True)
                if c == klass]
    return [(a, n) for n, a in table.items() if classes.get(n) == klass]


def rows_of(table: dict[str, int]) -> list[tuple[str, int]]:
    """Every `(name, address)` of a table in the file's order: a repeated name once per row."""
    return table.rows if isinstance(table, Names) else list(table.items())


@dataclass(frozen=True)
class SymbolTable:
    """What a symbol file loaded: the names, rows per class, and the shape (`"yaml"` or `"tsv"`)."""

    table: dict[str, int]
    by_class: dict[str, int]
    format: str
    # Symbol type where the file says (`type:`), in the watch format grammar.
    types: dict[str, str] = field(default_factory=dict)
    # Each class's [min, max] runtime address, for `find` within a class.
    class_span: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Numeric base each class was relocated by, to turn a map offset into a `read_memory` address.
    bases: dict[str, int] = field(default_factory=dict)
    # Class of each symbol, so an operand is placed among its own class.
    classes: dict[str, str] = field(default_factory=dict)
    # Segment base per class as the map says (`linear - offset`), for near pointers.
    segment_bases: dict[str, int] = field(default_factory=dict)
    # Each folded key as the file spelled it, so a reply names a symbol as its map does.
    spelled: dict[str, str] = field(default_factory=dict)

    def shown(self, key: str) -> str:
        """`key` as the file spelled it."""
        return self.spelled.get(key, key)


# The linker's map row: five TAB-separated fields, recognised by shape, never by its header.
_TSV_FIELDS = 5


def reference_window(rom_len: int, addr: int, n: int, base: int) -> int:
    """Offset into the image of `n` bytes at cpu address `addr`, or a refusal when the image has no
    opinion (below the base or past its end). Pure, so the server asks it before booting."""
    lo = addr - base
    if lo < 0 or lo + n > rom_len:
        raise SessionError(
            f"0x{addr:x} is OUTSIDE the reference image: the file holds {rom_len} bytes placed "
            f"at base {base:#x}, so its last byte is {base + rom_len - 1:#x} and the {n} bytes "
            "compared must fit inside. Pick an address inside it, or fix the base the image "
            "is placed at."
        )
    return lo


def symbols(path: str, bases: dict[str, int | None] | None = None) -> SymbolTable:
    """Read a project's symbol file: YAML `addr:`/`name:` pairs or the linker's five-field TAB map.

    `bases` maps a class to its runtime base: CODE runs at the row's linear address, but DATA is
    copied to RAM at boot, so its address is the base plus the row's offset. A class with no entry
    refuses; a base of `None` declares a resident class. A parameter that does nothing refuses, and
    so does zero symbols. `nombre:` is accepted as well as `name:`.
    """
    bases = {k.upper(): v for k, v in (bases or {}).items()}
    table = Names()
    types: dict[str, str] = {}
    by_class: dict[str, int] = {}
    class_span: dict[str, tuple[int, int]] = {}
    classes: dict[str, str] = {}
    segment_bases: dict[str, int | None] = {}   # None: the rows disagreed
    saw_yaml = saw_tsv = False
    last_name: str | None = None
    unbased: dict[str, str] = {}
    spelled: dict[str, str] = {}
    odd_tab_lines: list[tuple[int, int]] = []
    addr = None

    def enter(key: str, name: str) -> None:
        spelled.setdefault(key, name)

    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except UnicodeDecodeError as e:
        raise ValueError(f"{path} is not UTF-8 text: {e}") from None
    for lineno, line in enumerate(lines, 1):
        stripped = line.rstrip("\n")
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            continue
        fields = stripped.split("\t")
        if len(fields) == _TSV_FIELDS:
            name, linear_hex, _seg, offset_hex, klass = (f.strip() for f in fields)
            klass = klass.upper()
            if not name or not klass:
                raise ValueError(f"{path}:{lineno}: a map row with an empty name or class")
            try:
                linear, offset = int(linear_hex, 16), int(offset_hex, 16)
            except ValueError as e:
                raise ValueError(f"{path}:{lineno}: not a hex address: {e}") from None
            saw_tsv = True
            by_class[klass] = by_class.get(klass, 0) + 1
            seg = linear - offset
            if klass not in segment_bases:
                segment_bases[klass] = seg
            elif segment_bases[klass] != seg:
                segment_bases[klass] = None
            key = name.upper()
            enter(key, name)
            if klass in bases:
                base = bases[klass]
                at = linear if base is None else base + offset
            elif klass == "CODE":
                at = linear
            else:
                unbased.setdefault(klass, f"{path}:{lineno} ({name})")
                continue
            table.add(key, at, klass)
            _span_add(class_span, klass, at)
            classes.setdefault(key, klass)
            continue
        if len(fields) > 1:
            odd_tab_lines.append((lineno, len(fields)))
        # A tabbed non-row is still YAML; refused below only if the file is a map.
        m = re.search(r"^\s*-?\s*addr:\s*(0x[0-9a-fA-F]+|\d+)", line)
        if m:
            addr = int(m.group(1), 0)
            saw_yaml = True
            continue
        m = re.search(r"^\s*(?:name|nombre):\s*(\S+)", line)
        if m and addr is not None:
            last_name = m.group(1).upper()
            enter(last_name, m.group(1))
            table.add(last_name, addr)
            addr = None
            continue
        # A `type:` types the `name:` before it; a spec the grammar refuses refuses the file.
        m = re.search(r"^\s*type:\s*(\S+)", line)
        if m and last_name is not None and saw_yaml:
            try:
                vf.parse(m.group(1))
            except vf.FormatError as e:
                raise ValueError(f"{path}:{lineno}: {e}") from None
            types[last_name] = m.group(1)
    if saw_yaml and saw_tsv:
        raise ValueError(
            f"{path} holds both shapes, YAML pairs and map rows, and their addresses do not "
            "mean the same thing. One file, one shape."
        )
    if saw_tsv and odd_tab_lines:
        lineno, n = odd_tab_lines[0]
        raise ValueError(
            f"{path}:{lineno}: a map row with {n} TAB-separated fields, not {_TSV_FIELDS}"
        )
    if unbased:
        listed = "; ".join(f"{k}: first at {where}" for k, where in sorted(unbased.items()))
        raise ValueError(
            f"{path} carries symbols of a class with no runtime base: {listed}. CODE runs at the "
            "map's linear address; every other class needs an entry in `bases`, because loading "
            "it at the image address reads the ROM where the game means RAM."
        )
    if saw_tsv:
        unused = sorted(set(bases) - set(by_class))
        if unused:
            raise ValueError(
                f"`bases` names {unused}, and no row of {path} carries that class "
                f"(it has {sorted(by_class)}): the entry would be honoured by nothing."
            )
        return SymbolTable(table, by_class, "tsv", class_span=class_span,
                           bases={k: v for k, v in bases.items() if v is not None},
                           classes=classes,
                           segment_bases={k: v for k, v in segment_bases.items()
                                          if v is not None},
                           spelled=spelled)
    if bases and saw_yaml:
        raise ValueError(
            f"`bases` was given for {path}, which is a YAML symbol file: it already carries "
            "runtime addresses and has no classes, so nothing here would honour the parameter."
        )
    if not table:
        raise ValueError(
            f"{path} yields ZERO symbols: no `addr:`/`name:` pair and no {_TSV_FIELDS}-column "
            "map row was found. A table with nothing in it makes every lookup fall back to "
            "hex parsing, which is the failure this reader exists to prevent."
        )
    return SymbolTable(table, {}, "yaml", types=types, spelled=spelled)
