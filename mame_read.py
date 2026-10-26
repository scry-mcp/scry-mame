"""The READ family: bytes, a disassembly, a search, the trail, the registers."""

from __future__ import annotations

import bisect
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scry_core import judges, prose
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_console as console
import mame_cpus as cpus
import mame_envelope as menvelope
import mame_flow as flow
import mame_inputs as inputs
import mame_state as st
from mame_state import STATE

# `read_memory` answers two hex characters per byte; above READ_MAX the answer is `memdump`,
# which keeps the bytes in a file. `find`, `history` and `log` cap LINES so a chatty driver
# cannot flood the reply.
READ_MAX = 1024
LOG_LIMIT_MAX = 400
# A one-byte pattern answers one `Found at` line per hit, and an answer long enough takes MAME
# down (SIGSEGV); a window bounds it.
FIND_WINDOW = 0x8000
# Each pattern byte is a console parameter of `find`; past `MAX_COMMAND_PARAMS`
# (src/emu/debug/debugcon.h) the command is refused whole.
CONSOLE_PARAMS_MAX = 128
FIND_BYTES_MAX = CONSOLE_PARAMS_MAX - 2

# `truncated` names every bounded list; the end cut differs on purpose: `find` keeps the LAST
# hits (a range is read from the end), `symbols_find` and `machine_map` the FIRST rows.


_FOUND_AT = re.compile(r"^Found at ([0-9A-Fa-f]+)\s*$", re.M)
_NOT_FOUND = re.compile(r"^\s*Not found\s*$")


_HISTORY_LINE = re.compile(r"^[0-9A-Fa-f]+: ")

# A DIRECT memory operand (`word ptr [0C014h]`); a register-relative form is the register's
# business at run time, not the map's.
_DIRECT_OPERAND = re.compile(r"\[([0-9A-Fa-f]+)h\]")


def print_values(ses: gs.Session, names: list[str]) -> list[int]:
    """Several debugger expressions in ONE console round trip (`print a,b,c`), values as hex.

    Anything but one number per expression is a `SessionError`, so the caller takes its refusal
    path with the machine left stopped; a refused expression is `ExpressionRefused`.
    """
    command = "print " + ",".join(names)
    said = ses.monitor(command)
    if (found := console.refusals(command, said)) is not None:
        raise gs.ExpressionRefused(console.refusal_message(command, found))
    raw = said.strip().split()
    if not raw:
        raise gs.SessionError(f"MAME's console answered nothing for `{command}`")
    if len(raw) != len(names):
        raise gs.SessionError(
            f"MAME's console answered `{command}` with {prose.counted(len(raw), 'value')} for "
            f"{prose.counted(len(names), 'expression')}: {' '.join(raw)!r}")
    try:
        return [int(v, 16) for v in raw]
    except ValueError as exc:
        raise gs.SessionError(
            f"MAME's console did not answer `{command}` with numbers: {' '.join(raw)!r}"
        ) from exc


FRAMELESS_WHY = ("this machine has no screen device (a vector display, for one), so MAME's "
                 "debugger defines no `frame` and no vblank stop")
BY_TIME = "`{tool}(milliseconds=)` works"
FRAMELESS_NOTE = f"{FRAMELESS_WHY}: `run_for(frames=)` is refused, {BY_TIME.format(tool='run_for')}"


def frame_symbol() -> str | None:
    """The console's name for the frame counter, None on a board with no screen device."""
    return STATE.frame_symbol


def probe_frame_symbol(ses: gs.Session) -> str | None:
    """Which name the frame counter answers to: `frame0` first, then `frame`; None if both refused.

    MAME registers `frame` only with exactly one screen device (src/emu/debug/debugcpu.cpp), and
    a vector board lists a display yet has none. An answer neither number nor refusal keeps
    `frame`."""
    for symbol in ("frame0", "frame"):
        try:
            print_values(ses, [symbol])
        except gs.ExpressionRefused:
            continue
        except gs.ConnectionFailed:
            raise
        except gs.SessionError:
            if ses.broken:
                raise
            return "frame"
        return symbol
    return None


def frame_fields() -> dict[str, Any]:
    """What `start`, `status` and `machine_map` say of the counter."""
    symbol = frame_symbol()
    return {"frame_symbol": symbol if symbol is not None else unavailable(FRAMELESS_NOTE)}


def frame(ses: gs.Session) -> int:
    """MAME's frame counter, read through the console."""
    return print_values(ses, [known_frame_symbol()])[0]


def frame_or_none(ses: gs.Session) -> int | None:
    """The frame counter, or None on a board with none; a failed read still raises."""
    return None if frame_symbol() is None else frame(ses)


def known_frame_symbol() -> str:
    """The frame counter's name; a board with none refuses without a console round trip."""
    symbol = frame_symbol()
    if symbol is None:
        raise gs.ExpressionRefused(f"a frame was asked for, and {FRAMELESS_WHY}")
    return symbol


def rest_reading(ses: gs.Session) -> int | float:
    """The frame counter, or on a board with none the emulated clock; both hold still stopped."""
    if frame_symbol() is not None:
        return frame(ses)
    seconds = ses.emulated_seconds()
    if seconds is None:
        raise gs.SessionError(f"{FRAMELESS_WHY}, and the console's `time` answered no time, so "
                              "nothing here can prove the machine at rest")
    return seconds


def fmt_regs(ses: gs.Session, thread: int) -> dict[str, str]:
    """Every register of `thread`'s cpu at its own declared width, rounded up to a whole hex digit.

    One formatter for both readers, so a width never pads in one reply and not the next.
    """
    bits = ses.layout(thread).register_bits
    return {n: judges.hex_at_width(v, bits.get(n, 32))
            for n, v in ses.registers(thread=thread).items()}


def check_registers(from_last_stop: bool = False, cpu: str = "", **_: Any) -> None:
    """`registers`' machine-independent half."""
    if from_last_stop and inputs.cpu_given(cpu):
        raise st.Invalid("bad_argument", "`from_last_stop` hands back the last stop survey's "
                         "registers, which are that survey's cpu: `cpu` names a live read")


def space_bound(addr: int, length: int, cpu: str | None) -> None:
    """Refuse `length` bytes from `addr` whose last byte lies past `cpu`'s program-space mask.

    Past the mask the stub wraps to the space's start and answers a plausible value; with no mask
    known the range is the console's."""
    mask = cpus.program_mask(cpu)
    last = addr + length - 1
    if mask is not None and last > mask:
        raise st.Invalid("bad_argument",
            f"{length:#x} bytes from {addr:#x} end at {last:#x}, past the program space of "
            f"{cpu or 'the cpu'}, whose address mask is {mask:#x}: an address past it wraps to "
            f"the space's start, which is another place; keep the range within 0..{mask:#x}")


def check_read_memory(length: int = 16, ref: str = "", **_: Any) -> None:
    """`read_memory`'s machine-independent half."""
    inputs.check_ref(ref)
    inputs.count("length", length, READ_MAX,
                   ": for more bytes use `memdump`, which writes them to a file instead of into "
                   "the reply")


def read_memory(ses: gs.Session, ref: str, length: int, cpu: str = "") -> dict[str, Any]:
    check_read_memory(length, ref)
    on, thread = cpus.thread_for(ses, cpu)
    addr = STATE.resolve(ref, on)
    space_bound(addr, length, on)
    data = ses.read(addr, length, thread=thread)
    return menvelope.envelope({"addr": st.hex_addr(addr), "length": length, "hex": data.hex(),
                               "cpu": or_unavailable(on, st.NO_CPU_READ_WHY)})


def dasm_lines(ses: gs.Session, scratch: Path, addr: int, length: int,
               cpu: str | None = None, opcodes: bool = True) -> list[str]:
    """MAME's `dasm` listing of `length` bytes at `addr`, one line per item.

    A `SessionError` when no listing came out. `opcodes` is spelled out when a cpu follows it or
    it is off, else left to `dasm`'s default of 1."""
    listing = scratch / ("dasm.txt" if opcodes else "dasm.bare.txt")
    listing.unlink(missing_ok=True)
    flag = "1" if opcodes else "0"
    named = f",{flag},{cpu}" if cpu else ("" if opcodes else ",0")
    said = ses.monitor(f"dasm {listing.name},{addr:#x},{length:#x}{named}").strip()
    if not listing.exists():
        raise gs.SessionError(f"the console's `dasm` wrote no file; it said {said!r}")
    # Replacement on purpose: a raw ROM label must not turn the listing into an exception.
    text = listing.read_text(encoding="utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise gs.SessionError(f"the console's `dasm` wrote an empty listing; it said {said!r}")
    return lines


def check_disassemble(length: int = 16, ref: str = "", **_: Any) -> None:
    inputs.check_ref(ref)
    inputs.count("length", length, READ_MAX, " bytes")


def disassemble(ses: gs.Session, scratch: Path, ref: str, length: int,
                cpu: str = "") -> dict[str, Any]:
    check_disassemble(length, ref)
    on = cpus.chosen(ses, cpu)
    addr = STATE.resolve(ref, on)
    try:
        lines = dasm_lines(ses, scratch, addr, length, on if inputs.cpu_given(cpu) else None)
    except gs.SessionError as e:
        return menvelope.invalid("unexpected_answer", str(e))
    reply: dict[str, Any] = {"addr": st.hex_addr(addr), "length": length, "lines": lines,
                             "cpu": or_unavailable(on, st.NO_CPU_READ_WHY)}
    reply |= flows(ses, scratch, addr, length, on, lines)
    table = STATE.table(on)
    if table.bases:
        reply["resolved"] = resolve_operands(lines, table.bases, table.table, table.classes)
    return menvelope.envelope(reply)


_LISTED_AT = re.compile(r"^([0-9A-Fa-f]+):")


def flows(ses: gs.Session, scratch: Path, addr: int, length: int, on: str | None,
          lines: list[str]) -> dict[str, Any]:
    """`flow` per line, `flow_source`, and one `note` when no line could be classified.

    The mnemonic is read off a second listing without opcode bytes: in the first, bytes and
    instruction share one column (a 68000's `abcd` looks like an opcode word). That listing
    names `on`, since the table is `on`'s."""
    kind = cpus.cpu_type(on)
    source = flow.source(kind)
    if kind is None or source is None:
        why = (f"no mnemonic table for cpu type {kind!r} (tables: {', '.join(flow.TABLES)})"
               if kind else f"the cpu type of {on or 'the visible cpu'} is not in the "
                            "inventory `start` cached")
        return _unclassified(lines, f"{why}, so no line is classified")
    try:
        bare = dasm_lines(ses, scratch, addr, length, on, opcodes=False)
    except gs.SessionError as e:
        return _unclassified(lines, f"the listing without opcode bytes did not come out ({e}), "
                                    "so no line is classified")
    addresses = [m.group(1) if (m := _LISTED_AT.match(line)) else "" for line in lines]
    classes = flow.classify_listing(bare, addresses, kind)
    if classes is None:
        return _unclassified(lines, "the listing without opcode bytes did not decode the same "
                                    "instructions at the same addresses, so no line is classified")
    return {"flow": classes, "flow_source": source}


def _unclassified(lines: list[str], note: str) -> dict[str, Any]:
    return {"flow": [flow.UNKNOWN] * len(lines), "flow_source": "none", "note": note}


def resolve_operands(lines: list[str], bases: dict[str, int], symbols: dict[str, int],
                     classes: dict[str, str]) -> list[dict[str, Any]]:
    """Every DIRECT memory operand, resolved under every class base.

    Per class: the linear address `read_memory` and `watch_add` take, and the nearest symbol of
    that class at or below it (a routine of another class would be a plausible name for a datum).
    A segmented board prints the offset inside its class, not the runtime address, so read as
    printed it names the wrong byte; the segment register picks the class, so every class with a
    base is answered. Classes are bisected, not scanned."""
    by_class: dict[str, tuple[list[int], list[str]]] = {}
    for klass in bases:
        members = sorted((a, n) for n, a in symbols.items() if classes.get(n) == klass)
        by_class[klass] = ([a for a, _n in members], [n for _a, n in members])
    out: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        for m in _DIRECT_OPERAND.finditer(flow.without_comment(line)):
            offset = int(m.group(1), 16)
            for klass, base in bases.items():
                linear = base + offset
                addrs, names = by_class[klass]
                at = bisect.bisect_right(addrs, linear) - 1
                below = unavailable(f"no symbol of class {klass} lies at or below it")
                symbol, delta = (below, below) if at < 0 else (names[at], linear - addrs[at])
                out.append({"line": i, "operand": f"{m.group(1)}h", "offset": offset,
                            "class": klass, "linear": st.hex_addr(linear), "symbol": symbol,
                            "delta": delta})
    return out


def hex_bytes(name: str, value: str, *, verb: str) -> bytes:
    """The bytes a caller wrote as hex, or the refusal; the one hex parser of this server.

    `bytes.fromhex` ignores ASCII whitespace, so `de ad` is two bytes. `verb` is what the bytes
    were for."""
    try:
        data = bytes.fromhex(value)
    except ValueError:
        raise st.Invalid("bad_argument", f"{name}={value!r} is not a whole number of hex "
                                         "bytes (two digits per byte)") from None
    if not data:
        raise st.Invalid("bad_argument", f"{name} is empty: nothing to {verb}")
    return data


def check_find(data_hex: str = "", ref: str = "", length: int = 0, symbol_class: str = "",
               **_: Any) -> bytes:
    """`find`'s machine-independent half: the bytes, and which way of naming a range was used.

    Which class a `symbol_class` names is the machine's to answer, so that stays in `find`."""
    if inputs.given(ref):
        inputs.check_ref(ref)
    wanted = hex_bytes("data_hex", data_hex, verb="search for")
    inputs.count("the byte count of data_hex", len(wanted), FIND_BYTES_MAX,
                   ": the console takes each byte as a parameter of its own")
    if symbol_class:
        if inputs.given(ref) or length:
            raise st.Invalid("bad_argument",
                "give `symbol_class` OR `ref`+`length`, not both: a class supplies its own range, "
                "so a ref and a length beside it would name two searches")
        return wanted
    if not inputs.given(ref):
        raise st.Invalid("bad_argument",
            "no range to search: give `symbol_class` (a symbol class, searched over its "
            "symbols' span) or `ref`+`length` (an exact range). This server has no "
            "whole-address-space sweep, because the space's extent is not something the "
            "table says")
    inputs.count("length", length, tail=": a length counts bytes")
    return wanted


# One span per class for `find` and `machine_map`, so the two cannot disagree; the note is why
# the span must be said at all.
CLASS_SPAN = {"source": "class symbols",
              "note": "the class's symbols' [min, max]: a match past the last symbol's own "
                      "start is not covered"}


def find(ses: gs.Session, data_hex: str, ref: str, length: int,
         symbol_class: str = "", cpu: str = "") -> dict[str, Any]:
    # Parsed bytes, not the text: re-slicing `de ad` two characters at a time would hand the
    # console `0xde,0x a,0xd`.
    wanted = check_find(data_hex, ref, length, symbol_class)
    named = inputs.cpu_given(cpu)
    on = cpus.chosen(ses, cpu)
    class_of: str | None = None
    # THE SPAN EXAMINED RIDES ON THE REPLY, with where it came from. A class's span is its
    # The span rides on the reply: it is the symbols' [min, max], not the segment, so zero hits
    # mean not among the class's symbols.
    span_reply: dict[str, Any]
    if symbol_class:
        spans = STATE.table(on).class_span
        span = spans.get(symbol_class.upper())
        if span is None:
            have = sorted(spans) or "no classes (a YAML table carries none)"
            raise st.Invalid("unknown_ref",
                f"no symbol class {symbol_class!r} in this build; it has {have}")
        lo, hi = span
        addr, length, class_of = lo, hi - lo + 1, symbol_class.upper()
        span_reply = dict(CLASS_SPAN)
    else:
        addr = STATE.resolve(ref, on)
        span_reply = {"source": "ref+length"}
    space_bound(addr, length, on)
    items = ",".join(f"0x{b:02x}" for b in wanted)
    found: list[str] = []
        # A hit belongs to the window it STARTS in (the console's rule).
    for start in range(addr, addr + length, FIND_WINDOW):
        width = min(FIND_WINDOW, addr + length - start)
        text = ses.monitor(f"find {start:#x}{f':{on}' if named else ''},{width:#x},{items}")
        window = _FOUND_AT.findall(text)
        # Every line a hit, or `Not found` alone; half an answer is not a count.
        answered = [line for line in text.splitlines() if line.strip()]
        if not (_NOT_FOUND.match(text) if not window else len(window) == len(answered)):
            return menvelope.invalid("unexpected_answer",
                                     f"the console answered something other than hits or `Not "
                                     f"found`: {text.strip()!r}")
        found += window
    hits = [st.hex_addr(int(h, 16)) for h in found]
    reply: dict[str, Any] = {
        "addr": st.hex_addr(addr), "length": length,
        "span": {"from": st.hex_addr(addr), "length": length, **span_reply},
        "hits": hits[-LOG_LIMIT_MAX:], "hits_total": len(hits),
        "truncated": len(hits) > LOG_LIMIT_MAX,
    }
    if class_of is not None:
        reply["symbol_class"] = class_of
    reply["cpu"] = or_unavailable(on, st.NO_CPU_READ_WHY)
    return menvelope.envelope(reply)


# MAME's `device_debug::HISTORY_SIZE`; the console clamps a longer request in silence.
HISTORY_MAX = 256


def check_history(limit: int = 32, **_: Any) -> None:
    inputs.count("limit", limit, HISTORY_MAX,
                   ": MAME keeps no deeper trail than that for a cpu")


NO_DISASSEMBLER = "No disassembler available for device"


def no_disassembler(ses: gs.Session, tag: str) -> str | None:
    """The console's sentence when `tag` has no disassembler, else None (a one-line `history`)."""
    lines = [line for line in ses.monitor(f"history {tag},1").splitlines() if line.strip()]
    return lines[0] if len(lines) == 1 and lines[0].startswith(NO_DISASSEMBLER) else None


def history(ses: gs.Session, limit: int, cpu: str = "") -> dict[str, Any]:
    check_history(limit)
    on = cpus.chosen(ses, cpu)
    text = ses.monitor(f"history {on if inputs.cpu_given(cpu) else ''},{limit:#x}")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0].startswith(NO_DISASSEMBLER):
        return menvelope.invalid("no_channel", f"{on} keeps no trail MAME can list: {lines[0]}")
    if not all(_HISTORY_LINE.match(line) for line in lines):
        return menvelope.invalid("unexpected_answer",
                                 "the console answered something other than a trail: "
                                 f"{text.strip()!r}")
    # Fewer lines than asked is an answer, and so is none (no instruction retired yet).
    note = ({} if lines else
            {"note": f"{on} has retired no instruction yet, so MAME keeps no trail for it"})
    return menvelope.envelope({"asked": limit, "lines": lines,
                               "cpu": or_unavailable(on, st.NO_CPU_READ_WHY), **note})


# The names come from the stub's target description, not a fixed list. The m68k aliases (`A6`,
# `A7`, `SR`, `USP`) are accepted but not listed, having no register number of their own.
def registers(ses: gs.Session, cpu: str = "") -> dict[str, Any]:
    """`register_bits` gives each width; a stop reply leaves it in the digits."""
    on, thread = cpus.thread_for(ses, cpu)
    lay = cpus.described(ses, on, thread)
    return menvelope.envelope({"regs": fmt_regs(ses, thread),
                               "register_bits": dict(lay.register_bits),
                               "cpu": or_unavailable(on, st.NO_CPU_READ_WHY)})


def registers_at_last_stop(ses: gs.Session, cpu: str = "") -> dict[str, Any]:
    """The registers as they were at the last stop, marked stale; answers on a running machine."""
    check_registers(from_last_stop=True, cpu=cpu)
    # Unreachable in a live session: `start` records its park as stop 1.
    if not STATE.last_stop:
        raise st.Invalid("no_stop", "no stop yet in this session, so there are no last-stop "
                                    "registers to hand back")
    stop = STATE.last_stop
    # Widths are the stop's cpu's; none for registers the survey could not read.
    widths = ({} if "available" in stop["regs"]
              else dict(cpus.layout(ses, stop.get("cpu")).register_bits))
    return menvelope.envelope({"regs": dict(stop["regs"]),
                               "cpu": or_unavailable(stop.get("cpu"), st.NO_CPU_READ_WHY),
                               "superseded": True,
                               "last_stop": STATE.as_of(), "register_bits": widths})


SYMBOLS_LIMIT_MAX = 50


def check_symbols_find(name: str = "", linear: str = "", limit: int = 10,
                       **_: Any) -> None:
    """`symbols_find`'s machine-independent half."""
    if bool(name) == bool(linear):
        raise st.Invalid("bad_argument",
            "one question per call: `name` (a symbol to look up) or `linear` "
            "(an address to place inside the nearest symbol), not both, not neither")
    inputs.count("limit", limit, SYMBOLS_LIMIT_MAX,
                   ": each symbol answered costs the console one `map` when the machine is "
                   "stopped, so the list is bounded")
    if linear:
        inputs.hex_arg("linear", linear)


Placer = Callable[[int], tuple[int, str] | None]

# One sorted copy per cpu, checked by identity: `start` replaces tables whole.
_PLACERS: dict[str | None, tuple[gs.SymbolTable, Placer]] = {}


def placer(cpu: str | None = None) -> Placer:
    """`cpu`'s table as address -> (base, name) of the highest symbol at or below it.

    Ties go to the greatest name. Sorted once and bisected: a trace places every address."""
    table = STATE.table(cpu)
    cached = _PLACERS.get(cpu)
    if cached is not None and cached[0] is table:
        return cached[1]
    entries = sorted((a, n) for n, a in table.table.items())
    addrs = [a for a, _ in entries]

    def place(addr: int) -> tuple[int, str] | None:
        i = bisect.bisect_right(addrs, addr)
        return entries[i - 1] if i else None
    _PLACERS[cpu] = (table, place)
    return place


def nearest_symbol(addr: int, cpu: str | None = None) -> tuple[int, str] | None:
    """The symbol `addr` is inside (`placer`'s rule); the one placer all tools share."""
    return placer(cpu)(addr)


def symbol_label(addr: int, cpu: str | None = None) -> str | None:
    """`addr` as `NAME` or `NAME+0x12`, or None."""
    placed = nearest_symbol(addr, cpu)
    if placed is None:
        return None
    base, name = placed
    return name if addr == base else f"{name}+{addr - base:#x}"


def add_symbol(row: dict[str, Any], pc: int, cpu: str | None) -> dict[str, Any]:
    """Set `symbol` LAST on `row` in place when the table places `pc`, and return `row`."""
    label = symbol_label(pc, cpu)
    if label is not None:
        row["symbol"] = label
    return row


def symbols_find(name: str, linear: str, limit: int,
                 kind: Callable[[int], str] | None = None,
                 cpu: str | None = None) -> dict[str, Any]:
    """A reader over `cpu`'s table, so it takes no session.

    `kind` says what an address is (`ram`, `rom`, `latch`); None while the machine runs, and
    every symbol then reads `unknown` with a note."""
    def memory(addr: int) -> str:
        return "unknown" if kind is None else kind(addr)
    note = ({} if kind is not None else
            {"note": "the machine is running, so the console's `map` could not be asked "
                     "which symbols are RAM: stop it and ask again"})
    check_symbols_find(name, linear, limit)
    table = STATE.table(cpu).table
    if not table:
        whose = f"{cpu}'s" if cpu is not None else "a"
        return menvelope.invalid("no_channel",
                                 f"no symbol table: `start` was given no `symbols` file "
                                 f"for {whose} program, so there is nothing to look a "
                                 "name up in", cpu=cpu)
    if name:
        key = name.strip().upper()     # MAME's expressions fold a symbol's case, so its table does
        hits = ([key] if key in table else
                sorted((n for n in table if n.startswith(key)), key=lambda n: table[n]))
        return menvelope.envelope({
            "query": name, "cpu": or_unavailable(cpu, st.NO_CPU_READ_WHY),
            "symbols_total": len(hits),
            "symbols": [{"name": n, "addr": st.hex_addr(table[n]), "memory": memory(table[n])}
                        for n in hits[:limit]],
            "truncated": len(hits) > limit, **note,
        })
    addr = inputs.hex_arg("linear", linear)
    placed = nearest_symbol(addr, cpu)
    if placed is None:
        return menvelope.invalid("unknown_ref",
                                 f"{addr:#x} is below every symbol in the table (the lowest is "
                                 f"{min(table.values()):#x}), so nothing contains it",
                                 linear=st.hex_addr(addr), cpu=cpu)
    base, best = placed
    return menvelope.envelope({"linear": st.hex_addr(addr),
                               "cpu": or_unavailable(cpu, st.NO_CPU_READ_WHY), "name": best,
                               "addr": st.hex_addr(base), "delta": addr - base,
                               "memory": memory(base),
                               **note})
