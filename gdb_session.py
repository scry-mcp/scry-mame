"""Persistent debug session against MAME's gdbstub, over the GDB remote protocol.

WHY THIS EXISTS. Without it, asking the emulated machine a question costs a whole MAME boot:
write a Lua script, launch, emulate up to the frame of interest, read error.log: seconds for
a boot and tens of seconds to reach a late attract screen, and every follow-up question
("fine, and what is in A2 now?") pays it again.
Against the gdbstub the same question costs about a millisecond, with the machine standing
where it was.

NO EXTERNAL GDB IS NEEDED. The remote protocol is plain text over TCP, and everything here
is stdlib. This matters: no host in the fleet has a gdb that speaks m68k.

WHAT MAME'S STUB ACTUALLY ANSWERS, measured rather than assumed, on the fleet's build:
    qSupported, ?, qXfer:features:read:target.xml, m/M, p/P, Z0/z0, Z1, c, s   -> yes
    qAttached, vCont?                                                          -> no
The register numbers come from the target description XML. They are NOT guessable: reading
"the PC" as register 16 returns E01 on this target, which is exactly the kind of silent
wrong answer this module exists to prevent.

HONESTY OF THE INSTRUMENT. A session that lies makes everything downstream lie, so
`self_check` reads a known address and compares it against the ROM file on disk, and
`determinism` repeats a read and reports whether it changed. Call them before trusting a
session: `start` calls the first one and refuses a session that fails it.
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

from scry_core import value_format as vf

# The feature name prefix under which MAME's stub appends the state of every device other than
# the debugged cpu (`mame./subcpu`), after that cpu's own registers.
OTHER_DEVICE_FEATURE = "mame./"


class SessionError(RuntimeError):
    """Anything that means the session cannot be trusted, rather than a normal 'no'.

    `reply` is the stub's own answer when one came (an `E` refusal, a target description), else
    empty; out of `Session.handshake` it is cut short, and `phase` says which of the
    handshake's questions failed."""

    phase: str = "unknown"
    reply: str = ""


class Timeout(SessionError):
    """No answer within the bound. Its own type because `poll_stop` tells it from every
    other failure, which a substring of the message could not do reliably."""


class ConnectionFailed(SessionError):
    """The connection itself is gone: reset, a broken pipe, closed by the stub. Its own type
    because a caller that tolerates a console's refusal (an answer: the channel kept its
    place) must still tell it from a channel that answers nothing any more."""


class Refused(SessionError):
    """The stub ANSWERED, and the answer was no: an `E` reply, or fewer bytes than were asked
    for. The channel kept its place, so the connection still pairs a reply with its request;
    every other `SessionError` says it may not."""


class NoRegisters(SessionError):
    """A well-formed target description that declares no register: the stub answered before
    its cpu was described."""


class BadTargetXml(SessionError):
    """A target description that does not parse (empty, cut or garbled), or whose registers'
    numbers or sizes are not numbers."""


class DialFailed(SessionError):
    """The TCP connection was made and its first byte could not be sent on it (`Session.dial`,
    which closes the socket)."""


class ExpressionRefused(SessionError):
    """The debugger's console REFUSED an expression (`Error in expression: frame / ^unknown
    symbol`): an answer about this machine, which lacks what was named, so the channel kept its
    place. Its own type so a caller asking for a symbol some boards lack (a frame counter on a
    board with no screen device) tells that answer from a channel that failed."""


class Mismatch(SessionError):
    """The stub ANSWERED, and the bytes are not the ones a known answer says they must be: the
    ROM on disk and the machine disagree. A verdict about the machine, not a channel that
    failed, so the connection still pairs a reply with its request."""


class Unsupported(SessionError):
    """The stub answered the empty packet, which the remote protocol defines as "unsupported":
    the stub has no such packet, and nothing was done. Its own type because a caller that asks
    for something only some builds serve (a thread's name) must tell that answer from a
    connection that failed or a wait that latched the session broken."""


class CommandTooLong(SessionError):
    """A console command whose `qRcmd` packet would be past the stub's size, refused BEFORE it
    is sent: the stub drops such a packet unanswered, so sending it only buys a timeout that
    blames the wait. Nothing of it went out, and the server answers it as a refusal of the
    argument. Both lengths are in characters of the command, counted as the bytes it is sent
    as."""

    def __init__(self, command_chars: int, limit_chars: int) -> None:
        super().__init__(f"the console command is {command_chars} characters and the stub's "
                         f"packet size carries at most {limit_chars}: the stub would drop it "
                         "unanswered, so it was not sent")
        self.command_chars = command_chars
        self.limit_chars = limit_chars


class UnknownByteOrder(SessionError):
    """A cpu whose byte order cannot be known without guessing (`_BYTE_ORDER` says when): its
    registers and its multi-byte values would decode as plausible wrong numbers, so they are not
    decoded.
    Its own type because it is a fact about the cpu, answered as a refusal, never a channel
    that failed."""


class NotStopped(SessionError):
    """The machine was released, no stop has been read since, and what was asked needs it
    stopped. Raised by the server's gate, never by the client: the stub itself answers most
    packets while the machine runs
    (measured: `m`, `qRcmd` and `Z0` all come back), so the client cannot know which asks
    are honest on a moving machine, and the policy sits where the tools are."""


# How much of the stub's answer a handshake failure keeps: a whole target description would
# drown what the failure says.
REPLY_KEPT_CHARS = 200


@contextmanager
def _phase(name: str) -> Iterator[None]:
    """Marks a `SessionError` raised inside with `name` as its `phase`, cuts its `reply` to
    `REPLY_KEPT_CHARS`, and raises it on."""
    try:
        yield
    except SessionError as e:
        e.phase, e.reply = name, e.reply[:REPLY_KEPT_CHARS]
        raise


def _within(deadline: float | None, arriving: str) -> None:
    """`Timeout` once `deadline` (`time.time()`) has passed with `arriving`, a paged answer,
    still incomplete: a stub that never sends the last page would hold the caller for ever."""
    if deadline is not None and time.time() >= deadline:
        raise Timeout(f"{arriving} was still arriving at the handshake's deadline: the stub had "
                      "not sent its last page")


def _checksum(body: str) -> str:
    return f"{sum(body.encode()) & 0xFF:02x}"


def packet_size(supported: str) -> int | None:
    """The largest packet the stub takes, as its `qSupported` answer advertises it
    (`PacketSize=<hex>`), or None when it says nothing: MAME's stub DROPS a longer packet
    without answering it, which from here is a timeout, so the size is read and not guessed."""
    for feature in supported.split(";"):
        name, _, value = feature.partition("=")
        if name == "PacketSize" and value:
            try:
                return int(value, 16)
            except ValueError:
                raise SessionError(f"`qSupported` advertised PacketSize={value!r}, which is not "
                                   "hex") from None
    return None


# THE CONSOLE'S LINE WIDTH, MAME's `MAX_LINE_LENGTH` in `src/emu/debug/textbuf.cpp`. Every
# `Rcmd` reply is the debugger console's text buffer, and that buffer wraps every line it is
# given at this column: at the last space before it when the line has one, DROPPING the space,
# and with a hard cut exactly at the column when it has none. So any console line past this
# width reaches `monitor` as several.
CONSOLE_WRAP_COLS = 250


def unwrap_console(text: str, starts: re.Pattern[str]) -> list[str]:
    """The LOGICAL lines of a console reply, rebuilt from the pieces MAME's wrap made of them.

    A blank line ends a logical line. A piece exactly `CONSOLE_WRAP_COLS` long was cut hard, so
    the next line continues it, joined with nothing. A shorter piece either ended its line or
    was cut at the space MAME dropped, and then the characters it carried past that space open
    the next line with no space among them: only a next line that can hold them continues it,
    joined with the space. A piece one short of the column carried nothing, so the geometry
    cannot tell; there `starts`, the caller's pattern for a line of ITS answer, decides."""
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
    """Whether MAME's wrap could have cut `line` off the end of `piece` (`unwrap_console`)."""
    if len(piece) == CONSOLE_WRAP_COLS:
        return True
    carried = CONSOLE_WRAP_COLS - 1 - len(piece)
    if carried == 0:
        return not starts.match(line)
    return len(line) >= carried and " " not in line[:carried]


# The stopped thread a `T` stop reply names (`thread:2;`), on a stub with a thread per cpu.
_STOP_THREAD = re.compile(r"(?:^T[0-9a-fA-F]{2}|;)thread:([0-9a-fA-F]+);")


def _is_stop_reply(packet: str) -> bool:
    """Whether `packet` is a stop reply, or the REFUSAL of a stop shape this stub never
    sends, asked wherever a stop can arrive. MAME's stub builds
    ONE shape, `T` and a two-digit signal followed by the watch and the registers, so that
    is what a stop is here. The protocol's other stop shapes (`S05`, and `W`/`X` for a
    process that went) are refused by name: the stub has no path that sends them, so one
    that arrives is neither a stop to count nor an answer to hand back."""
    if re.match(r"^S[0-9a-fA-F]{2}|^[WX]", packet):
        raise SessionError(f"the stub sent {packet[:32]!r}, a stop reply of a shape MAME's "
                           "stub never sends: the session cannot be trusted")
    return bool(re.match(r"^T[0-9a-fA-F]{2}", packet))


def _connection_failed(error: OSError) -> ConnectionFailed:
    """The `SessionError` a socket's own failure becomes (a reset connection, a broken pipe):
    every handler above the packet layer catches `SessionError`, so the translation is made
    once, here, where the socket is touched. A READ that ran out is a `TimeoutError`, an
    `OSError` too, and is never brought here: that is `Timeout`. A send that could not
    complete is brought here whatever it raised, because part of a packet may be out."""
    return ConnectionFailed(f"the connection failed: {error}")


def _label(cmd: str) -> str:
    """A packet as a reader knows it: a console command by its own words, not its hex."""
    if cmd.startswith("qRcmd,"):
        try:
            return bytes.fromhex(cmd[len("qRcmd,"):]).decode(errors="replace")
        except ValueError:
            pass
    return cmd


def _refuse_run_length(body: str) -> str:
    """`body` as it came, or the refusal of one carrying the protocol's run-length marker.
    MAME's stub never compresses what it sends and nothing it answers holds a literal `*`,
    so decoding one would be a guess about a reply that is already wrong, and a wrong byte
    count in a memory read looks like a finding."""
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


# THE TARGET'S BYTE ORDER, WHICH THE PROTOCOL WILL NOT TELL YOU, AND WHICH MAME WILL.
#
# A register arrives from the stub in the TARGET's byte order, and MAME's gdbstub does the
# swap itself: `if (!is_be) ... swapendian_int16/32/64`, `is_be` being the endianness of the
# cpu's PROGRAM address space. Decode it the wrong way round and nothing fails -- you get a
# plausible-looking number that is simply wrong. MEASURED on a V30 board: the stub sent `568b`,
# this client's fixed big-endian decode said 0x568b, and MAME's own console said the program
# counter was 8B56.
#
# GDB'S DESCRIPTION FORMAT CARRIES NO BYTE ORDER: architecture, osabi, compatible and feature,
# and nothing else. But the order the stub encodes in is a value MAME exposes to Lua, the
# program space's `endianness`, and `start`'s inventory reads it for every cpu. That reading is
# exact rather than inferred, because it is the very value the stub swaps by, so it decides
# (`Session.know_endianness`). A cpu whose reading is missing (the inventory not read, no
# program space) is refused rather than guessed.
#
# THE ROWS BELOW ARE CROSS-CHECKS, each a measurement: the PC's digits in the stub's reply
# against MAME's own reading of that cpu's PC at one stop (its console, or its Lua state where
# the console showed another cpu), on the board named beside it, at a PC of two different bytes
# (0x0000 reads the same either way). A cpu whose architecture has a row and whose program
# space MAME declares the other way is refused, naming both: one of the two is wrong for it.
# `mips` never gets one: MAME maps BOTH the big-endian r4600 AND the little-endian PSX cpu onto
# that one string, so only the cpu's own space can say which it is.
_BYTE_ORDER: dict[str, Literal["little", "big"]] = {
    "i386": "little",  # a V30 board, EFLAGS F002 at reset as it must; pangofun's i486, EIP
    "i8086": "little", # the V30 board, once the stub declares it as the 16-bit x86 it is
    "m68k": "big",     # verified live on a 68000 board against the console's own PC
    "m6502": "little",  # circus
    "z80": "little",    # robby
    "m6809": "big",     # gridlee
    "arm": "little",    # pockstat
    "powerpc:common": "big",  # pmac6100
    "score7": "little",  # hyprscan
    "nios2": "little",  # unkts
}


@dataclass(frozen=True)
class Layout:
    """ONE CPU'S REGISTER FILE, as the stub's target description for its thread declares it.

    The patched stub answers `qXfer:features:read:target.xml` for the thread `Hg` selected, so
    each cpu has its own description: its registers with their numbers and widths, its
    architecture, and how many digits the other devices' state takes
    after them in its `g` reply, which each thread appends in its own order. A stub without
    threads describes its first cpu alone. `Session.layout` reads one per thread, once."""

    regs: dict[str, Register]      # by upper-cased name, the m68k aliases included
    other_digits: int              # hex digits the `g` reply spends on other devices' state
    arch: str
    names: list[str]               # `register_names`, computed once by `parse`
    # MAME's word for this cpu's byte order (`_BYTE_ORDER` above): `little`, `big`, or empty.
    # Given by the session (`Session.know_endianness`), never by the description.
    mame_order: str = ""

    @classmethod
    def parse(cls, xml: str) -> Layout:
        """The register file a target description declares. Register numbers come from it:
        guessing them returns E01."""
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            bad = BadTargetXml(f"target.xml is not a well-formed document: {e}")
            bad.reply = xml
            raise bad from None
        arch = root.findtext("architecture")
        regs: dict[str, Register] = {}
        other_digits = 0
        # ANOTHER DEVICE'S STATE IS NOT THIS CPU'S REGISTER. The stub appends every other
        # device's visible state after the cpu's own registers, each device under a feature
        # named `mame./<tag>`; a second 68000 names its `D0` there, which folded upper-case
        # would overwrite this cpu's `d0`. Those rows only count towards the `g` reply,
        # which carries them too.
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
        # `registers` cuts the `g` reply from its start at this cpu's widths, which holds while
        # the other devices come after it, as the stub appends them; one numbered first would
        # shift every value onto the wrong name, so that description is refused here.
        if first_other < last_own:
            raise SessionError(
                f"target.xml numbers another device's register ({first_other}) before this "
                f"cpu's last one ({last_own}), so a `g` reply cannot be cut by position")

        # The m68k XML calls them FP, SP and PS; the disassembly and everyone else call them
        # A6, A7 and SR. Without these aliases, asking for "A7" is an error, and asking for it
        # through a dict returns zero in silence, which is exactly the failure this module
        # exists to prevent. They are m68k's and they are inert elsewhere: each is installed
        # only if the XML actually declared the register it aliases.
        for alias, real in (("A6", "FP"), ("A7", "SP"), ("SR", "PS"), ("USP", "SP")):
            if real in regs and alias not in regs:
                regs[alias] = regs[real]
        # The names without the aliases, in register-number order, computed once: every stop
        # survey asks for them, twice, and the description never changes.
        numbered = {r.number: n for n, r in regs.items() if r.name.upper() == n}
        return cls(regs, other_digits, arch.strip() if arch else "",
                   [numbered[k] for k in sorted(numbered)])

    @property
    def register_names(self) -> list[str]:
        """The ones from target.xml, without the aliases, in register-number order."""
        return list(self.names)

    @property
    def register_bits(self) -> dict[str, int]:
        """Each listed register's DECLARED width, so a reader can print it at its real size.

        Padding every value to eight hex digits whatever the cpu says makes a 16-bit V30
        register look 32-bit, and a refused `set_register` above 0xffff then reads as a
        broken tool rather than as the register's own limit. Same source and same
        filtering as `register_names`: the target description's
        own file, aliases excluded, since an alias has no width of its own to report.
        """
        return {n: self.regs[n].bits for n in self.register_names}

    def register_name(self, name: str) -> str:
        """The stub's own name for `name`: the name itself when the file has it, or the
        16-bit register its `E`-prefixed spelling names (a V30 is programmed as `AX` and
        served by the stub under the i386 map's `EAX`, 16 bits wide; its `EIP` is `GENPC`, the
        linear pc, 32 bits wide, so `IP` reaches no register through it), or the refusal
        that lists the file. A 32-bit register is never reached by the short
        spelling: on an i386 `AX` is half of `EAX`, and that half is not a register here."""
        upper = name.upper()
        if upper in self.regs:
            return upper
        wide = f"E{upper}"
        if wide in self.regs and self.regs[wide].bits == 16:
            return wide
        raise SessionError(f"unknown register {name!r}; this CPU has {self.register_names}")

    def register_width(self, name: str) -> int:
        """The declared width of `name`, an alias resolving to the register it names, or the
        refusal that lists the file. `register_bits` deliberately lists no alias, and a
        forced register is read back at its own width, which for an alias defaulted to 32."""
        return self.regs[self.register_name(name)].bits

    @property
    def pointer_width(self) -> int:
        """How many bytes a pointer held in memory takes on THIS cpu, for a watch reached
        through one: the width of the stack pointer, the one register that is as wide as a
        pointer by construction on every cpu (four on a 68000, two on a V30 whose near
        pointers are offsets in its data segment, and two on a 6502 whose accumulator is
        a byte). It is found by the name GDB's features give it, `sp`, `esp` or `rsp`.
        Two measures that look more principled are wrong here. The program counter: on
        the V30 the stub serves it as the linear address, 32 bits wide, and a near pointer
        is not. A `data_ptr` register: GDB sizes one by the architecture's pointer width
        whatever bitsize the description declares, so the stub cannot serve a 16-bit
        `data_ptr` without every register after it reading two bytes off, measured, and
        the V30 map declares none. A typed pointer (`ptr16`/`ptr32` in `types`) overrides
        it; a description with no stack pointer falls back to the program counter."""
        for name in ("SP", "ESP", "RSP"):
            if name in self.regs and self.regs[name].name.upper() == name:
                return self.regs[name].bits // 8
        return self.register_width(self.pc_name) // 8

    @property
    def pc_name(self) -> str:
        """The PROGRAM COUNTER's name on THIS cpu, resolved from target.xml.

        "PC" BY NAME IS A 68000 SPELLING. MAME's gdbstub names the same register `eip` on the
        x86 family, so a tool asking for "PC" refuses outright on a V30 board, with `unknown
        register 'PC'` from a machine that is working perfectly.

        THE NAME IS THE SPEC, NOT A HEURISTIC. GDB's Target Description format defines no
        architecture-independent way to say "this one is the program counter": its manual
        fixes the register NAMES per architecture, in Standard Target Features, and a
        description missing them is rejected outright. `org.gnu.gdb.m68k.core` must carry
        `pc`; `org.gnu.gdb.i386.core` must carry `eip`, and `rip` on amd64. Matching is
        case-insensitive there, which is why this compares upper-cased. MAME's gdbstub
        emits exactly those features, and across every cpu family in its own register table
        precisely one register carries one of those three names, with no exceptions.

        `code_ptr` IS THE FALLBACK AND NOT THE RULE, which is the trap worth naming: it
        looks like the principled choice, and GDB never promised it would be unique. In
        MAME's table three families mark a SECOND register `code_ptr` -- a link register,
        an exception-return address -- so keying on the type alone would take whichever
        came first. It is used only when it is unambiguous, which is what makes it a safe
        net for a cpu whose feature GDB does not standardise.

        WHICH GDBSTUB THIS IS, because the documentation for the other one says the
        opposite: MAME ships a gdbstub PLUGIN that supports only the i386 family, and a
        `-debugger gdbstub` MODULE that supports many. This server uses the module. A
        reader who finds the plugin's page first will conclude this cannot work at all.

        And when neither resolves, this REFUSES and names what it saw. A program counter
        guessed wrong is a stop address reported confidently against the wrong register.
        """
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
        """`little` or `big` for THIS target: MAME's, checked against a measured row where the
        architecture has one, or a refusal. See `_BYTE_ORDER` above."""
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


#: How long one request waits for its answer, unless a session is given another bound.
REQUEST_TIMEOUT_S = 10.0
#: How long a drain listens for a stop packet the stub is not expected to send: after a run the
#: console started (`gtime`, `over`), and after the interrupt that ends one. The stub sends a stop
#: reply only after a `c` or `s` of ours, so the drain is cheap insurance against a build that
#: differs, not the mechanism.
STOP_REPLY_DRAIN_S = 0.1


class Owner(Protocol):
    """The proof that a connection reached the emulator this server spawned
    (`mame_stub_owner.StubOwner`), run by `Session.dial` around its connection."""

    def before_dial(self) -> None: ...

    def after_dial(self, local_port: int) -> None: ...


@dataclass
class Session:
    """One live connection. One machine at a time, on purpose: there is no second use yet."""

    host: str = "127.0.0.1"
    port: int = 23946
    timeout: float = REQUEST_TIMEOUT_S
    # WHO MUST BE AT THE OTHER END, proved around the dial; None dials whatever answers.
    owner: Owner | None = field(default=None, repr=False)
    _sock: socket.socket | None = field(default=None, repr=False)
    _buf: bytes = field(default=b"", repr=False)
    _layouts: dict[int, Layout] = field(default_factory=dict, repr=False)  # by thread, once
    writes: int = 0  # how many times this session has ALTERED the machine
    packet_size: int | None = None  # what `qSupported` advertised: `packet_size`
    # WHICH GDB THREAD IS WHICH CPU, by id, as the stub names them (`_read_threads`). Empty on a
    # stub that serves the first cpu alone, which is every build without the thread patch.
    threads: dict[int, str] = field(default_factory=dict)
    # MAME's word for each thread's cpu's byte order (`_BYTE_ORDER` above), by thread.
    endianness: dict[int, str] = field(default_factory=dict)
    # THE THREAD THE STUB SERVES `g`, `p` and `m` FOR: 1 at connect, and a stop packet that
    # names another moves it there, as gdbserver does (`thread:` in the reply). Every register
    # and memory method takes the thread it is FOR, and `_on_thread` moves this to it.
    _served_thread: int = 1
    # THE RUNNING STATE, kept here because the socket is the only witness of it. `go` sets
    # it; the stop reply the stub sends on its own (a breakpoint, an interrupt) clears it,
    # whichever call happens to read that packet. `stop_count` counts every stop so a
    # record made at one can be told from the machine's current one.
    running: bool = False
    stop_count: int = 0
    last_stop_packet: str = ""
    # WHY THE SESSION CAN NO LONGER BE TRUSTED, in the words of the error that broke it, or
    # None. The server's gate refuses everything but `close` and `status` while it is set,
    # and only a new session clears it.
    broken: str | None = None
    # A request sent `owed` that ran out: its answer comes first on the wire, read and dropped
    # by the next request (`_collect_owed`).
    _owed: str | None = None

    def drain_stop_reply(self) -> None:
        """Read and drop a stop packet the stub may have sent unasked, so it is never read as
        the answer to the next request (`STOP_REPLY_DRAIN_S`)."""
        with suppress(SessionError):
            self._receive(STOP_REPLY_DRAIN_S)

    def latch(self, reason: str) -> None:
        """Mark the session broken for good: the first reason stands, since what fails after a
        session broke is its consequence, not its cause."""
        self.broken = self.broken or reason

    # ----------------------------------------------------------------- protocol

    def dial(self) -> None:
        """The TCP connection alone. MAME's stub serves ONE per session and closes its listening
        socket once it accepts it, so a dial that succeeded is the connection, whether or not the
        stub has read anything on it yet: a caller waiting on a boot keeps it, never dials again.
        A connection whose first byte cannot be sent is closed here and is `DialFailed`.

        With an `owner`, the port's listener is proved to be that emulator before the dial,
        and the connection's far end after it, BEFORE its first byte: a connection that is not
        proved is closed with nothing sent on it."""
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
        """What the stub is asked once connected: packet size, the first cpu's registers and its
        threads. `timeout` bounds the FIRST answer, which comes only once the boot reaches the
        debugger; the rest are ordinary requests. A failure leaves with `phase` and `reply` set
        (`SessionError`).

        The two paged answers after it, the description and the thread list, share one
        deadline: what is left of `timeout`, and never less than one request's own, since the
        first answer may have spent nearly all of it on the boot."""
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
        """This end's port of the connection, None while there is none."""
        return self._sock.getsockname()[1] if self._sock else None

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    def _refuse_broken(self) -> None:
        if self.broken is not None:
            raise SessionError(f"this session broke and is asked nothing more: {self.broken}")

    def _send(self, cmd: str) -> None:
        # WHAT AN `owed` REQUEST WAS STILL OWED is read before anything goes out, whichever
        # call sends: the stub answers in order, so it is the next thing on the wire.
        self._collect_owed()
        self._transmit(f"${cmd}#{_checksum(cmd)}".encode())

    def _transmit(self, data: bytes) -> None:
        """`data` onto the socket as it is: a framed packet, the `+`, or the bare 0x03."""
        if not self._sock:
            raise SessionError("the session is not connected")
        try:
            self._sock.sendall(data)
        except OSError as e:
            raise _connection_failed(e) from e

    def _receive(self, timeout: float | None = None) -> str:
        """One complete reply, or a timeout that is reported and never mistaken for 'no'.

        NO CHECKSUM IS VERIFIED AND NO `-` IS EVER SENT BACK, on purpose. The stub is reached
        over loopback TCP, which already checks every byte it carries, and MAME's stub has
        never been seen to send a frame with a bad checksum, so there is no captured shape
        to build a resend on: a mechanism for a failure nobody can provoke would be
        untested code on the one path every answer takes."""
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
            # The socket is asked at least ONCE, however small the timeout: a zero timeout is
            # `poll_stop`'s "is a stop packet already here?", answered by a non-blocking read,
            # and a deadline checked first would expire before reading anything at all.
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
        """`cmd` sent and its answer read within `timeout`; one that runs out latches the
        session, its answer still owed (`_ask`)."""
        return self._ask(cmd, timeout)

    def _ask(self, cmd: str, timeout: float | None, owed: bool = False) -> str:
        """`request`'s body. One sent `owed` (the presence's repaint, whose failure is its own)
        that runs out is set aside instead of latching, and the next request reads and drops
        that answer before it sends, latching only if it never comes."""
        # A BROKEN SESSION SENDS NOTHING MORE. Its callers catch `SessionError` in many places
        # and carry on, and the next request is the one that would read what the broken one
        # was still owed; refusing it here covers every caller, the ones not written yet too.
        self._refuse_broken()
        if owed and self._owed is not None:
            # AN OWED REQUEST WHILE ANOTHER IS STILL OWED is not sent: collecting the first here
            # could latch the session over the presence's own repaint, which never breaks it.
            # The next ordinary request collects it, as it would have.
            raise Timeout(f"`{_label(self._owed)}` is still owed its answer, so "
                          f"`{_label(cmd)}` was not sent")
        self._send(cmd)
        try:
            r = self._receive(timeout)
            # A STOP REPLY CAN LAND IN THE MIDDLE OF ANOTHER CONVERSATION. The stub sends one
            # on its own when a running machine stops (a breakpoint fired, or an interrupt),
            # and it dispatches other packets while running too, so the reply to a `Z0` or a
            # `qRcmd` sent to a running machine may be preceded by the stop it just reached.
            # That packet is the machine's, not the command's: it is noted and the real reply
            # read.
            while self.running and _is_stop_reply(r):
                self._note_stop(r)
                r = self._receive(timeout)
        except Timeout as e:
            if owed:
                self._owed = cmd
                raise
            # LATCHED HERE, where every request passes, and never resynced (a `p11` would be
            # read back as `p0`). A stop wait reads `_receive` directly and is not this.
            waited = timeout if timeout is not None else self.timeout
            self.latch(f"`{_label(cmd)}` got no answer within {waited} s, and the answer it is "
                       "still owed would be read as the next request's, so no reply on this "
                       "connection can be paired with its request any more")
            raise Timeout(self.broken) from e
        if r.startswith("E") and len(r) == 3:
            refused = Refused(f"the stub refused `{cmd}`: {r}")
            refused.reply = r
            raise refused
        # THE EMPTY PACKET IS "UNSUPPORTED", NOT "DONE". The remote protocol answers a
        # packet the stub does not implement with `$#00` (captured off MAME's stub on a
        # 68000 board: `vMustReplyEmpty`, `qFoo`, `QNonStop:1` all came back empty, a
        # refused `P` came back `E01`, and a `qRcmd` whose console command prints NOTHING
        # (`temp0 = 0`, `softreset`, `quit`) came back `0A`, one newline, never empty,
        # so the console path is untouched). Reading it as success let `write`, `set_register`
        # and `breakpoint` report an operation that never happened; a mute breakpoint is
        # exactly what the control on `run_to` exists to catch, and a control that never
        # armed silences that verdict too.
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
        """`cmd`, a register or memory packet, answered for `thread`'s cpu: THE ONE DOOR every
        such packet goes through. The stub keeps ONE selection (`Hg`) for `g`, `p`, `m` and
        their writes, and a stop moves it to the thread that stopped, so the selection is
        remembered here and moved only when the packet needs another thread: no packet runs on
        whatever thread was left selected. A stub without threads serves thread 1 alone, and
        asking it for another is a caller's error, refused before anything is sent."""
        if thread != 1 and thread not in self.threads:
            raise ValueError(f"thread {thread} is not one this stub serves "
                             f"({sorted(self.threads) or [1]})")
        if self._served_thread != thread:
            self.request(f"Hg{thread:x}")
            self._served_thread = thread
        return self.request(cmd)

    def register_block(self, thread: int) -> str:
        """Thread `thread`'s whole `g` reply as the stub sends it, in that cpu's own layout:
        compared whole, never cut by position, so it needs no layout to say whether that cpu
        moved. A cpu with no register map is refused (`E01`)."""
        return self._on_thread(thread, "g")

    def stopped_thread(self) -> int | None:
        """The thread whose cpu the machine last stopped on, off `?`: the patched stub answers
        the stop reply of that stop, which an `Hc` since does not change, so it names the cpu
        MAME is live on rather than the visible one. None when the reply names no thread. The
        stub selects that thread for `g` and `m`, as at a stop, and so does this session."""
        m = _STOP_THREAD.search(self.request("?"))
        if m is None:
            return None
        self._served_thread = int(m.group(1), 16)
        return self._served_thread

    def make_visible(self, thread: int) -> None:
        """`Hc<thread>`: the patched stub makes that thread's cpu the debugger's visible one
        and touches no ignore flag, so the machine is not released. A cpu the debugger
        ignores is refused (`E01`), since a step on it would never end."""
        self.request(f"Hc{thread:x}")

    def _read_threads(self, deadline: float | None = None) -> dict[int, str]:
        """Which GDB thread is which cpu, as the STUB names them: `qfThreadInfo` and its
        `qsThreadInfo` pages for the ids, `qThreadExtraInfo` for each one's tag (hex, as the
        protocol encodes it). A stub that names no thread serves the first cpu alone and
        answers an empty map, never a tag guessed for thread 1. Past `deadline`, a list still
        arriving is a `Timeout`."""
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

    # ---------------------------------------------------------------- registers

    def current_pc(self) -> int:
        """WHERE THE MACHINE IS, as an address you could set a breakpoint on.

        MAME IS ASKED RATHER THAN COMPUTED FROM, and that is the whole point. On a 68000
        this equals the `pc` register. On the NEC family (a V30) the stub serves MAME's
        `GENPC` under the i386 map's `EIP`, 32 bits wide: `(PS<<4) + ip`, the LINEAR pc, which
        at a stop equals `curpc`. That equality is the family's own
        and not a promise of the map: a cpu whose stub served an offset there would make a
        tool comparing the register against its linear target call INVALID a stop that
        happened exactly as asked.

        Nor is it segment arithmetic here: `cs*16+ip` is real-mode 8086 and would be wrong
        the moment a descriptor table is involved, and it would need a new branch per
        architecture. MAME already computes this for every cpu it emulates and calls it
        `curpc`, so it is asked. One console round trip, and no cpu knowledge of ours.
        """
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
        """`thread`'s cpu's register file, off its own target description: read the first time
        it is asked and kept, since a description does not change while the machine runs. Past
        `deadline` (`time.time()`), a description still arriving is a `Timeout`."""
        if thread not in self._layouts:
            parts: list[str] = []
            off = 0
            while True:
                _within(deadline, "target.xml")
                # The stub ends the description with an `l` chunk; an empty reply would be
                # "unsupported", which `request` refuses, so the loop has no other exit.
                chunk = self._on_thread(thread, f"qXfer:features:read:target.xml:{off:x},400")
                parts.append(chunk[1:])
                if chunk[0] == "l":
                    break
                off += len(chunk) - 1
            self._layouts[thread] = replace(Layout.parse("".join(parts)),
                                            mame_order=self.endianness.get(thread, ""))
        return self._layouts[thread]

    def know_endianness(self, by_thread: dict[int, str]) -> None:
        """MAME's word for each thread's cpu's byte order, given to every layout already read and
        to every one read after: the first description is read during the boot, before the
        inventory that says it."""
        self.endianness.update(by_thread)
        for thread, lay in self._layouts.items():
            self._layouts[thread] = replace(lay, mame_order=self.endianness.get(thread, ""))

    def reg(self, name: str, *, thread: int) -> int:
        lay = self.layout(thread)
        r = lay.regs[lay.register_name(name)]
        return int.from_bytes(bytes.fromhex(self._on_thread(thread, f"p{r.number:x}")),
                              lay.byte_order)

    def registers(self, *, thread: int) -> dict[str, int]:
        """The whole register file in ONE round trip, the protocol's `g`, each register decoded
        in its cpu's byte order (`register_texts` says how the reply is cut).

        Every stop survey reads the file, and `p` per register cost a round trip each: a
        68000's eighteen registers were eighteen trips a stop.
        """
        lay = self.layout(thread)
        return {n: int.from_bytes(bytes.fromhex(text), lay.byte_order)
                for n, text in self.register_texts(thread=thread).items()}

    def register_texts(self, *, thread: int) -> dict[str, str]:
        """Every register of `thread`'s cpu as the stub prints it, by name, in register-number
        order: the `g` reply cut by the widths the description declares, and nothing decoded,
        so it needs no byte order and two readings compare equal exactly when the stub sent
        the same digits.

        Read in the stub's source: `g` answers every register in number order, each printed at
        the width the description declares for it (two hex digits per eight bits: a 16-bit V30
        register takes four, an 80-bit x87 placeholder twenty), each already in the target's
        byte order like `p`, and after them the other devices' state the stub appends, which is
        counted and not read. The reply is cut by those widths, and one whose length is not
        their sum is refused: a file read short would be plausible numbers against the wrong
        names. The one map whose stub prints a width other than the declared one, the i486's
        x87 block, is refused by that same check rather than misread.
        """
        lay = self.layout(thread)
        names = lay.register_names
        if not names:
            return {}    # a map with no registers has nothing to ask the stub for
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
        # THE CONVERSION COMES BEFORE THE COUNTER, AND THAT ORDER IS THE WHOLE POINT. A value
        # too wide for the register raises here, before one byte reaches the stub, so counting
        # first marked the machine ALTERED for a call that provably never touched it -- and
        # `altered` is the single field a caller trusts to say whether a measurement describes a
        # normal run of the game. `write` below keeps the opposite order on purpose: there the
        # packet IS sent before anything can fail, so the machine may really have changed.
        try:
            payload = value.to_bytes(r.bits // 8, lay.byte_order).hex()
        except OverflowError:
            # NAMING THE WIDTH IS THE POINT: `registers` prints every value padded to eight hex
            # digits whatever the cpu declares, so a 16-bit V30 register looks 32-bit and the
            # bare `int too big to convert` read as a broken tool rather than a real limit.
            raise SessionError(
                f"{r.name.upper()} is {r.bits} bits on this cpu and {value:#x} does not fit it"
            ) from None
        self.writes += 1
        self._on_thread(thread, f"P{r.number:x}={payload}")

    # ------------------------------------------------------------------ memory

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        """`n` bytes at `addr` of `thread`'s cpu, its own program space."""
        return bytes.fromhex(self._on_thread(thread, f"m{addr:x},{n:x}"))

    def max_payload(self) -> int | None:
        """The largest packet body the stub takes, which is its advertised size itself, or None
        when it advertised nothing. GDB's `PacketSize` limits the data characters, frame and
        checksum excluded, and MAME's receive loop stores exactly that many before it drops a
        packet. The one frontier both `write` and `monitor` size themselves by."""
        return self.packet_size

    def write(self, addr: int, data: bytes, *, thread: int) -> None:
        """ONE write to the machine, in as many `M` packets as the stub's size needs: each
        byte is two hex digits, and a packet past the advertised size is dropped unanswered.
        The header is sized for the whole range, so every packet's is no longer."""
        if not data:
            return                      # nothing to send, and nothing altered to count
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

    # --------------------------------------------------------------- execution

    def go(self) -> None:
        """Let the machine RUN and come back at once: the `resume` with no deadline. The stop
        reply, when a breakpoint fires, arrives on its own and is read by whichever call
        next touches the socket (`poll_stop`, or `request` on the way to its own reply)."""
        self._send("c")
        self.running = True

    def poll_stop(self, timeout: float = 0.0) -> bool:
        """Whether the machine is STOPPED now, reading the stop reply if one arrived within
        `timeout`. On a stopped machine it answers True without touching the socket; on a
        running one it waits at most `timeout` for the stub's own stop packet and answers
        False when none came, which is the machine still running and not a failure."""
        if not self.running or not self._running_after_owed():
            return True
        try:
            packet = self._receive(timeout)
        except Timeout:
            return False
        self._expect_stop(packet)
        return True

    def _expect_stop(self, packet: str) -> str:
        """`packet` noted as the stop it is, or the refusal of anything else read where a stop
        was due: the stub sends nothing on its own but its stop packet (read in its source:
        every other `send_reply` answers a packet of ours), so nothing else is let through."""
        if not _is_stop_reply(packet):
            raise SessionError(f"the stub sent {packet!r} while the machine ran, which is not "
                               "a stop reply: the session cannot be trusted")
        self._note_stop(packet)
        return packet

    def resume(self, timeout: float = 30.0) -> str:
        """Run until something stops us, waiting up to `timeout` for the stop reply. On a
        timeout the machine is still RUNNING and `running` says so."""
        self.go()
        return self._expect_stop(self._receive(timeout))

    def halt(self) -> None:
        """Stop a machine that a CONSOLE command set running (`gtime`), where no stop reply
        will ever come: the stub sends one only after a `c` or an `s` of ours (its
        `m_send_stop_packet`), and a run started through `qRcmd` sets nothing. So the 0x03
        goes out and nothing is waited for; the caller proves the stop by reading the
        frame counter, as `run_for` does. It passes no `request`, so it asks the latch itself."""
        self._refuse_broken()
        self._collect_owed()
        self._transmit(b"\x03")

    def interrupt(self, timeout: float = 5.0) -> str:
        """Stop a RUNNING machine, so the session is left usable.

        Measured live: after `resume` times out, the machine keeps running, and the very next
        memory read comes back as something that is not hex, because the stop reply the stub
        then sends lands in front of the read's answer. The session looked alive and answered
        garbage, which is the worst state a debug session can be in (`request` now reads
        that packet as what it is, and this is what stops the machine).

        The remote protocol's interrupt is a bare 0x03 outside a packet, and the stop reply comes
        back on its own. If it does not arrive the session is genuinely wedged, and saying so is
        better than returning to a caller who will read rubbish. ON A STOPPED MACHINE NOTHING IS
        SENT: measured, the stub answers a 0x03 there with nothing at all, so a wait for its
        reply would time out for no reason.
        """
        if not self._sock:
            raise SessionError("the session is not connected")
        if not self.running or not self._running_after_owed():
            return self.last_stop_packet
        self._transmit(b"\x03")
        return self._expect_stop(self._receive(timeout))

    def step(self) -> str:
        """One instruction, waited for. Its `s` passes no `request`, so it asks the latch
        itself, as `halt` does."""
        self._refuse_broken()
        self._send("s")
        self.running = True
        return self._expect_stop(self._receive())

    def console_packet(self, command: str) -> str:
        """The `qRcmd` packet that carries `command`, or `CommandTooLong` when it would be past
        `max_payload`. A caller that has to do something before the command goes out (read a
        clock) asks this first, so a command that cannot be sent costs nothing at all."""
        packet = "qRcmd," + command.encode().hex()
        payload = self.max_payload()
        if payload is not None and len(packet) > payload:
            raise CommandTooLong(len(command.encode()),
                                 max(0, (payload - len("qRcmd,")) // 2))
        return packet

    def _running_after_owed(self) -> bool:
        """Whether the machine still runs once an owed answer was collected: a stop that
        arrived ahead of it was noted on the way."""
        self._collect_owed()
        return self.running

    def _collect_owed(self) -> None:
        """The answer an `owed` request ran out on, read and dropped before anything else is
        sent: the stub answers in order, so it comes first. Never coming, it latches."""
        if self._owed is None:
            return
        owed, self._owed = self._owed, None
        try:
            # A STOP CAN COME FIRST on a running machine, as in `_ask`: it is the machine's,
            # noted, and the answer read after it.
            r = self._receive(self.timeout)
            while self.running and _is_stop_reply(r):
                self._note_stop(r)
                r = self._receive(self.timeout)
        except Timeout as e:
            self.latch(f"`{_label(owed)}` was still owed an answer that never came, so no reply "
                       "on this connection can be paired with its request any more")
            raise Timeout(self.broken) from e

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        """Run any MAME debugger command through the session and return its text.

        The stub answers `qRcmd`, which is the standard escape hatch, and MAME wires it
        straight into its own debugger console. That is a much bigger door than it looks:
        everything the debugger window can do is reachable from here without a window, and
        without restarting anything.

        A command whose packet would be past the stub's size raises `CommandTooLong` and sends
        nothing (every caller's text passes here, so the check sits where the packet is made).
        """
        r = self.request(self.console_packet(command), timeout=timeout)
        try:
            return bytes.fromhex(r).decode(errors="replace")
        except ValueError:
            return r

    def monitor_owed(self, command: str, timeout: float = 10.0) -> None:
        """`monitor` for a command whose answer nobody reads (the presence's repaint): one that
        runs out is its caller's failure and latches nothing, its answer collected by the next
        request (`request`'s `owed`)."""
        self._ask(self.console_packet(command), timeout, owed=True)

    def emulated_seconds(self) -> float | None:
        """The machine's total elapsed EMULATED time in seconds, off the debugger console's
        own `time` command, or None when the console answered something else. It answers while
        the machine runs as well as stopped (measured), so a watched run's speed can be read at
        `close`. The console prints a plain decimal (`1.000003437`); anything else is not a
        time and is not guessed at."""
        text = self.monitor("time")
        m = re.search(r"[-+]?\d+\.\d+|\b\d+\b", text)
        return float(m.group(0)) if m else None

    def quit(self) -> None:
        """Ask MAME to EXIT cleanly, which is what writes its `cfg/` and `nvram/`.

        TWO STEPS, AND THE SECOND IS THE ONE THAT WAS MISSING. The debugger's `quit` only
        SCHEDULES the exit: MEASURED live, the console answered it at once and the process was
        still there two seconds later, because a machine stopped in the debugger never reaches
        the point where a scheduled exit is processed. Letting it run is what does: a bare `c`
        after the `quit` ended the process within tens of milliseconds, with the state files
        written. No stop reply is waited for, because none comes: the stub closes the
        connection as the process goes, and the caller reads the process, not the socket.
        """
        self.monitor("quit")
        self._send("c")

    def reset(self) -> int:
        """A SOFT reset, applied, and the pc it left the machine at.

        MEASURED on a board: the console's `softreset` is a timer that fires when the machine
        next runs, so the pc read right after the command is the old one, and one `step`
        lands on the boot pc; the frame counter does not restart. A HARD reset is not
        offered here: it re-creates the machine and the stub connection dies with it, so it
        is a `close` followed by a `start` and nothing a live session can do.

        It saves the process launch and nothing else: reaching a late screen costs the same
        emulated time again, and a rebuilt driver needs a new process by definition.
        """
        # COUNTED BEFORE IT IS SENT, on the cautious side: a `softreset` whose answer or whose
        # step fails may still have been scheduled, and a reset that went unrecorded would
        # leave `altered` false on a machine that no longer runs the game from where it was.
        self.writes += 1
        self.monitor("softreset")
        self.step()
        return self.current_pc()

    # --------------------------------------------------- instrument honesty

    def self_check(self, rom: bytes, addr: int, n: int = 16, base: int = 0, *,
                   thread: int) -> None:
        """Known-answer test: what the machine reports must match the ROM file on disk.

        `base` IS WHERE THE FILE'S FIRST BYTE SITS IN CPU SPACE, and it exists because the
        linker's output is not the address space. A 68000 board maps its program ROM at zero,
        so the file and the CPU agree and the base is zero. A V30 board maps its ROM at
        0x20000, and the linker emits the ROM alone: indexing that file with a CPU address
        lands on somebody else's bytes, or past the end on a slice that comes out short, and
        either way the compare fails and this method said LIES about a session that was
        answering perfectly. Every V30 repository worked round it by padding 128 KB of zeros
        onto its image, which is a copy of the memory map kept by hand in a build script.

        An address the file has no opinion about -- below the base, or past its end -- is a
        fact about the FILE and not about the session, so `reference_window` refuses it with
        a message that names the file's length and its base rather than blaming the machine.
        """
        lo = reference_window(len(rom), addr, n, base)
        live = self.read(addr, n, thread=thread)
        expected = rom[lo : lo + n]
        if live != expected:
            raise Mismatch(
                f"the session LIES: at 0x{addr:x} it returns {live.hex()} and the ROM on disk "
                f"holds {expected.hex()}. Nothing measured here is worth anything."
            )

    def determinism(self, addr: int, n: int = 16, times: int = 5, *, thread: int) -> bool:
        """A read repeated on a stopped machine must not change."""
        first = self.read(addr, n, thread=thread)
        return all(self.read(addr, n, thread=thread) == first for _ in range(times - 1))

    def cost_per_query(self, addr: int, n: int = 16, times: int = 200, *,
                       thread: int) -> float:
        t0 = time.time()
        for _ in range(times):
            self.read(addr, n, thread=thread)
        return (time.time() - t0) / times


def _span_add(spans: dict[str, tuple[int, int]], klass: str, addr: int) -> None:
    """Widen `klass`'s [min, max] to include `addr`."""
    lo, hi = spans.get(klass, (addr, addr))
    spans[klass] = (min(lo, addr), max(hi, addr))


@dataclass(frozen=True)
class SymbolTable:
    """What a symbol file loaded: the names, how many rows per class, and which shape it had.

    `by_class` is EMPTY for a YAML file, which carries runtime addresses and no classes; for a
    linker map it counts the rows per class, so a caller can see that the DATA symbols they
    expected were loaded at all. `format` is `"yaml"` or `"tsv"` for a file this module read;
    the server reports `"none"` when no file was given, and this module never returns that.
    """

    table: dict[str, int]
    by_class: dict[str, int]
    format: str
    # The TYPE of a symbol where the file says (`type:` beside `name:` in the YAML), in the
    # watch format grammar; a linker map carries none. What a watch reads with by default.
    types: dict[str, str] = field(default_factory=dict)
    # The [min, max] runtime address of each class's loaded symbols, so `find` can search
    # within a class (DATA, say) instead of the whole space. Empty for a YAML file, which
    # carries no classes. The span is the symbols' own addresses: a linker map has no sizes,
    # so it does not reach past the last symbol's START, which `find`'s docstring says.
    class_span: dict[str, tuple[int, int]] = field(default_factory=dict)
    # The NUMERIC base each class was relocated by (`{"DATA": 0x400}`), kept because a
    # disassembly prints a direct operand as the map's offset and a reader needs the base
    # to turn it into the address `read_memory` takes. A `rom` class has no base: its
    # runtime address is the map's own, and it is not listed here.
    bases: dict[str, int] = field(default_factory=dict)
    # The CLASS of each symbol (name -> class), from a linker map; empty for a YAML file.
    # What lets a resolved operand be placed among the symbols of ITS class and not the
    # nearest of any class, which on a board whose classes interleave would name a routine
    # for a datum.
    classes: dict[str, str] = field(default_factory=dict)
    # The SEGMENT BASE of each class as the map itself says it, `linear - offset` of its
    # rows, whatever `bases` relocated it by: a NEAR pointer holds an offset in its target
    # class's segment, and for a class `bases` does not list (CODE, a `rom` class) this is
    # the base that places it. A class whose rows disagree on it is left out, because no
    # single base would be honest.
    segment_bases: dict[str, int] = field(default_factory=dict)


# THE LINKER'S OWN MAP, one row per symbol, five TAB-separated fields:
# `name  linear_hex  seg_name  offset_hex  class`. A row is recognised by this SHAPE and never by
# the comment header above it, so a map with a different header, or none, loads all the same.
_TSV_FIELDS = 5


def reference_window(rom_len: int, addr: int, n: int, base: int) -> int:
    """Where `n` bytes at CPU address `addr` sit inside an image whose first byte is at `base`.

    Returns the offset into the image, or refuses when the image has no opinion about that
    address: below the base, or past its end. That refusal is a fact about the FILE and not
    about the session, so it is worded as one and never says LIES. It is a pure function so
    the server can ask it BEFORE booting an emulator, with nothing but the file's length.
    """
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
    """Read a project's symbol file. The server knows no game names.

    TWO SHAPES ARE READ, AND A FILE HOLDS ONE OF THEM. The first is the project's YAML, picked
    up as `addr:` / `name:` pairs without a YAML parser because this module has to run anywhere;
    the second is the linker's map as v30tool writes it, five TAB-separated fields per row (see
    `_TSV_FIELDS`). More than one repository wrote the same converter from the second shape to
    the first; reading the map directly is what retires every copy.

    A MAP ADDRESS IS NOT ALWAYS A RUNTIME ADDRESS, and that is what `bases` is for. CODE runs
    where the locator placed it, so the row's linear address is the right one. DATA is copied to
    RAM at boot and addressed off a segment register, so the runtime address is a base the
    RUNNING board decides (`DS = 0x40`, so `0x400`) plus the row's offset; the map's linear
    address for it is the ROM copy of its INITIAL value, which reads plausibly and is wrong:
    MEASURED, a `read` of a scene id off the map's address returned the initial zero while the
    RAM copy held the live scene. So `bases` maps a class name to that base, an explicit entry
    wins even for CODE, and a class with no entry and no default REFUSES, naming the class, the
    first row that carries it and this parameter. Loading it at the image address would be the
    measured defect, made silent. A base of `None` DECLARES a resident class: one the locator
    placed and that runs where the map says, like CODE (a tile sheet in ROM). A repository had
    to hand `linear - offset` back as that class's "base" to say so; the declaration is the
    honest spelling of the same fact.

    A PARAMETER THAT SILENTLY DOES NOTHING IS A DEFECT, so the mirror cases refuse too: a base
    for a class no row carries, and `bases` beside a YAML file, which already carries runtime
    addresses and has no classes to apply one to. And a file that yields ZERO symbols refuses
    whatever its shape, because zero symbols is the worst possible failure for this reader:
    every lookup falls back to hex parsing, so everything appears to work while reading the
    wrong addresses. A map whose tabs an editor turned into spaces is exactly that file.

    BOTH `name:` and `nombre:` are accepted, and that is not indecision. When this package was
    translated to English, a blind rename reached in here and left the parser expecting `name:`
    while every symbol file in the field still said `nombre:`. It loaded ZERO symbols in
    silence, which is the failure the refusal above now catches. The key is a DATA FORMAT
    belonging to the caller, not part of this API, so renaming it was never ours to do. A test
    pins both spellings.
    """
    bases = {k.upper(): v for k, v in (bases or {}).items()}
    table: dict[str, int] = {}
    types: dict[str, str] = {}
    by_class: dict[str, int] = {}
    class_span: dict[str, tuple[int, int]] = {}
    classes: dict[str, str] = {}
    segment_bases: dict[str, int | None] = {}   # None: the rows disagreed
    saw_yaml = saw_tsv = False
    last_name: str | None = None
    unbased: dict[str, str] = {}      # class -> the first row that carries it, for the refusal
    first_row: dict[str, int] = {}    # name -> line, so a duplicate can name both
    odd_tab_lines: list[tuple[int, int]] = []  # (line, field count) for tabbed non-rows
    addr = None
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
            if key in first_row:
                raise ValueError(
                    f"{path}:{lineno}: symbol {name!r} already appeared at line "
                    f"{first_row[key]}; two rows for one name would leave the last one "
                    "standing, in silence"
                )
            first_row[key] = lineno
            if klass in bases:
                base = bases[klass]
                table[key] = linear if base is None else base + offset
            elif klass == "CODE":
                table[key] = linear
            else:
                unbased.setdefault(klass, f"{path}:{lineno} ({name})")
                continue
            _span_add(class_span, klass, table[key])
            classes[key] = klass
            continue
        if len(fields) > 1:
            odd_tab_lines.append((lineno, len(fields)))
        # A tab is legal inside YAML text, so a tabbed line that is not a row is still read as
        # YAML; it is only refused below if the file turns out to be a map.
        m = re.search(r"^\s*-?\s*addr:\s*(0x[0-9a-fA-F]+|\d+)", line)
        if m:
            addr = int(m.group(1), 0)
            saw_yaml = True
            continue
        m = re.search(r"^\s*(?:name|nombre):\s*(\S+)", line)
        if m and addr is not None:
            last_name = m.group(1).upper()
            table[last_name] = addr
            addr = None
            continue
        # A TYPE RIDES WITH THE NAME BEFORE IT: `type: u16[8]` after `name:` types that
        # symbol; a spec the grammar refuses is a refusal of the FILE, named by line.
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
                                          if v is not None})
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
    return SymbolTable(table, {}, "yaml", types=types)
