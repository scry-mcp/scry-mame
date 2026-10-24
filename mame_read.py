"""The READ family: bytes, a disassembly, a search, the trail, the registers.

Each answers from a STOPPED machine and reduces by MEANING before it crosses into the
conversation: a read is capped at `READ_MAX` bytes (above it, `memdump` writes a file), a
listing or a trail at `LOG_LIMIT_MAX` lines, and a console answer that is not the shape
asked for is `verdict: INVALID`, never a zero or a trail of the wrong thing.
"""

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

# CEILINGS ON WHAT CROSSES INTO THE CONVERSATION, the readers' half. A `read_memory` answers
# hex, two characters per byte, exactly as the stub sent it (it never compresses): a frame
# of VRAM through it is over a hundred thousand characters in a reply somebody has
# to scroll past. Above this many bytes the answer is `memdump`, which keeps the bytes in a file.
# `find`, `history` and `log` cap how many LINES they hand back, so a chatty driver cannot
# flood the reply. `debug`'s ceiling on TEXT sits with `debug`, in the server.
READ_MAX = 1024
LOG_LIMIT_MAX = 400
# THE WIDEST RANGE ONE CONSOLE `find` IS ASKED. Its answer is one `Found at` line per hit, so a
# one-byte pattern over a window answers up to one line per byte, and an answer that long takes
# MAME itself down (SIGSEGV, the stub gone) on a search the contract accepts. A window bounds
# the worst answer well under the length that kills it, whatever `length` the caller asked for.
FIND_WINDOW = 0x8000
# A PATTERN'S BYTES ARE PARAMETERS of the console's `find`, one each after the address and the
# length, and the console takes at most `MAX_COMMAND_PARAMS` (src/emu/debug/debugcon.h): past
# it the command is refused whole.
CONSOLE_PARAMS_MAX = 128
FIND_BYTES_MAX = CONSOLE_PARAMS_MAX - 2

# ONE SPELLING, THREE MECHANICS, AND THAT IS NOT AN OVERSIGHT. Every bounded list here says
# `truncated`, a boolean, because one word has to mean one shape. WHICH END each cuts from is a
# different question and the three answers differ on purpose: `find` keeps the LAST hits,
# because a search over a range is read from the end; `symbols_find` and `machine_map` keep the
# FIRST rows, because a prefix match and an inventory are read from the top. A helper taking a
# flag to say which end to cut from is two functions badly packed into one, and it would save
# two lines. So the mechanics stay three and the name stays one.


# The two shapes the console's `find` was captured answering: one line per hit, or one word.
_FOUND_AT = re.compile(r"^Found at ([0-9A-Fa-f]+)\s*$", re.M)
_NOT_FOUND = re.compile(r"^\s*Not found\s*$")


# What one line of the console's `history` looks like: an address, a colon, the instruction.
_HISTORY_LINE = re.compile(r"^[0-9A-Fa-f]+: ")

# A DIRECT memory operand as MAME's x86-family disassembler prints one: hex digits and an
# `h` inside brackets with nothing else (`word ptr [0C014h]`, captured on a V30 board). A
# register-relative form (`ds1:[bw-31BBh]`, `[ix]`) has more inside the brackets and is
# not matched: its address is the register's business at run time, not the map's.
_DIRECT_OPERAND = re.compile(r"\[([0-9A-Fa-f]+)h\]")


def print_values(ses: gs.Session, names: list[str]) -> list[int]:
    """Several debugger expressions evaluated in ONE console round trip: `print a,b,c` answers
    the values space-separated, in order, as hex (read in the debugger's own source). One
    call whatever the count is what lets a stop survey carry every declared expression
    beside the frame at no extra cost.

    Anything that is not exactly one number per expression is a `SessionError`, like
    `current_pc` does for `curpc`: a stop packet or an error line arriving here must take the
    caller down its refusal path, never out of the tool as a bare `ValueError` with the
    machine left running. The console REFUSING an expression is its own type,
    `ExpressionRefused`: an answer about this machine, so the channel kept its place.
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


# What a board with no frame counter is: the fact, and the reason `frame_symbol` carries in
# place of a name, which adds what that changes for a run.
FRAMELESS_WHY = ("this machine has no screen device (a vector display, for one), so MAME's "
                 "debugger defines no `frame` and no vblank stop")
# The way round it for a run, when the tool runs by time too.
BY_TIME = "`{tool}(milliseconds=)` works"
FRAMELESS_NOTE = f"{FRAMELESS_WHY}: `run_for(frames=)` is refused, {BY_TIME.format(tool='run_for')}"


def frame_symbol() -> str | None:
    """The console's name for the frame counter on THIS machine, as `start` asked it
    (`probe_frame_symbol`); None on a board with no screen device, which has none."""
    return STATE.frame_symbol


def probe_frame_symbol(ses: gs.Session) -> str | None:
    """Which name the frame counter answers to, asked of the console before anything surveys
    a frame. MAME registers `frame` only on a board with exactly one screen device, `frame0`,
    `frame1`... on one with several, and nothing on one with none (src/emu/debug/debugcpu.cpp),
    and the screens a start can list are no guide: a vector board lists its `vector` display
    and still has no screen device. So the console is asked, `frame0` first. None when both
    names are refused; an answer that is neither a number nor a refusal keeps `frame`, the
    name an unasked board is read by."""
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
    """What `start`, `status` and `machine_map` say of the counter: its name, or on a board
    with none `unavailable` saying what that changes."""
    symbol = frame_symbol()
    return {"frame_symbol": symbol if symbol is not None else unavailable(FRAMELESS_NOTE)}


def frame(ses: gs.Session) -> int:
    """MAME's own frame counter, read through the console: the clock emulated time is proved by."""
    return print_values(ses, [known_frame_symbol()])[0]


def frame_or_none(ses: gs.Session) -> int | None:
    """The frame counter, or None on a board with none; a failed read still raises."""
    return None if frame_symbol() is None else frame(ses)


def known_frame_symbol() -> str:
    """The frame counter's name, for a read that needs one: a board with none refuses it
    without a console round trip."""
    symbol = frame_symbol()
    if symbol is None:
        raise gs.ExpressionRefused(f"a frame was asked for, and {FRAMELESS_WHY}")
    return symbol


def rest_reading(ses: gs.Session) -> int | float:
    """What a proof of rest reads twice: the frame counter, or on a board with none the
    emulated clock (the console's `time`), which a stopped machine holds still as well."""
    if frame_symbol() is not None:
        return frame(ses)
    seconds = ses.emulated_seconds()
    if seconds is None:
        raise gs.SessionError(f"{FRAMELESS_WHY}, and the console's `time` answered no time, so "
                              "nothing here can prove the machine at rest")
    return seconds


def fmt_regs(ses: gs.Session, thread: int) -> dict[str, str]:
    """Every register of `thread`'s cpu, printed at ITS OWN declared width. The one formatter
    both readers use.

    Why the width is the cpu's and not a fixed eight digits is `Session.register_bits`'s to
    say. Why there is ONE formatter is this one's: two of them disagreeing about a register's
    width means one reply pads it and the next does not, and a reader comparing the two sees a
    value change that never happened. A width that is not a multiple of four rounds UP to the
    next whole hex digit, because a value cannot be shown in a fraction of one.
    """
    bits = ses.layout(thread).register_bits
    return {n: judges.hex_at_width(v, bits.get(n, 32))
            for n, v in ses.registers(thread=thread).items()}


def check_registers(from_last_stop: bool = False, cpu: str = "", **_: Any) -> None:
    """`registers`' machine-independent half: the last stop's registers are that stop's cpu's,
    so naming another beside them asks for two things at once."""
    if from_last_stop and inputs.cpu_given(cpu):
        raise st.Invalid("bad_argument", "`from_last_stop` hands back the last stop survey's "
                         "registers, which are that survey's cpu: `cpu` names a live read")


def space_bound(addr: int, length: int, cpu: str | None) -> None:
    """Refuse `length` (1 or more) bytes from `addr` when their last byte lies past the address
    mask `start` read for `cpu`'s program space, the cpu the bytes are read or written on; with
    no mask known the range is the console's. The one judge of the tools that name a range of a
    program space by address (`read_memory`, `write`, `find`, `memdump`): past the mask no
    address exists, and the stub answers the bytes at the space's start again, a plausible value
    for a place that is not there."""
    mask = cpus.program_mask(cpu)
    last = addr + length - 1
    if mask is not None and last > mask:
        raise st.Invalid("bad_argument",
            f"{length:#x} bytes from {addr:#x} end at {last:#x}, past the program space of "
            f"{cpu or 'the cpu'}, whose address mask is {mask:#x}: an address past it wraps to "
            f"the space's start, which is another place; keep the range within 0..{mask:#x}")


def check_read_memory(length: int = 16, ref: str = "", **_: Any) -> None:
    """`read_memory`'s machine-independent half: the reply has a size and this is it."""
    inputs.check_ref(ref)
    inputs.count("length", length, READ_MAX,
                   ": for more bytes use `memdump`, which writes them to a file instead of into "
                   "the reply")


def read_memory(ses: gs.Session, ref: str, length: int, cpu: str = "") -> dict[str, Any]:
    """The body of the `read_memory` tool."""
    check_read_memory(length, ref)
    on, thread = cpus.thread_for(ses, cpu)
    addr = STATE.resolve(ref, on)
    space_bound(addr, length, on)
    data = ses.read(addr, length, thread=thread)
    return menvelope.envelope({"addr": st.hex_addr(addr), "length": length, "hex": data.hex(),
                               "cpu": or_unavailable(on, st.NO_CPU_READ_WHY)})


def dasm_lines(ses: gs.Session, scratch: Path, addr: int, length: int,
               cpu: str | None = None, opcodes: bool = True) -> list[str]:
    """MAME's own `dasm` listing of `length` bytes at `addr` of `cpu` (the visible one when
    None), one line per decoded item, or a `SessionError` naming what the console said when no
    listing came out. The one reader both `disassemble` and the stop reply use, so a stop shows
    the same text the tool would. The `opcodes` flag is spelled out whenever a cpu follows it or
    it is off, and left to `dasm`'s default of 1 otherwise (`dasm <file>,<addr>,<len>[,<opcodes>
    [,<CPU>]]`, its `help`); without the bytes a line is `<addr>: <instruction>`."""
    listing = scratch / ("dasm.txt" if opcodes else "dasm.bare.txt")
    listing.unlink(missing_ok=True)
    flag = "1" if opcodes else "0"
    named = f",{flag},{cpu}" if cpu else ("" if opcodes else ",0")
    said = ses.monitor(f"dasm {listing.name},{addr:#x},{length:#x}{named}").strip()
    if not listing.exists():
        raise gs.SessionError(f"the console's `dasm` wrote no file; it said {said!r}")
    # Replacement on purpose, as the log reader's: a comment or a label the disassembler
    # prints raw out of ROM must not turn the whole listing into an exception.
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
    """The body of the `disassemble` tool."""
    check_disassemble(length, ref)
    on = cpus.chosen(ses, cpu)                  # the cpu whose program `dasm` decodes
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


# ONE LEADING HEX ADDRESS AND ITS COLON: where a `dasm` line says which instruction it is.
_LISTED_AT = re.compile(r"^([0-9A-Fa-f]+):")


def flows(ses: gs.Session, scratch: Path, addr: int, length: int, on: str | None,
          lines: list[str]) -> dict[str, Any]:
    """`flow` (one class per line of `lines`), `flow_source`, and a `note` when no line could
    be classified, said once for the listing rather than on every line.

    THE MNEMONIC IS READ OFF A SECOND LISTING WITHOUT OPCODE BYTES. In the first, the bytes and
    the instruction share one padded column and nothing marks where one ends: a 68000's `abcd`
    is four hex digits exactly like an opcode word. A type with no table costs no second call.
    The second listing NAMES `on` even when the first left the cpu to the console: the table is
    `on`'s, so the words it classifies have to be `on`'s too, not whichever cpu is visible."""
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
    """Every DIRECT memory operand in a listing, resolved under every class base: the
    operand as printed, its offset, and per class the linear address `read_memory` and
    `watch_add` take and the nearest symbol OF THAT CLASS at or below it, with the distance
    (`symbol` unavailable when the class has none below it: a routine of another class would be
    a plausible name for a datum).

    A segmented board prints such an operand as the offset inside its class (the map's
    `offset` column), which is NOT the runtime address: read or watched as printed, it names
    the wrong byte and answers a plausible zero with no error. Which class an operand belongs to
    is the instruction's segment register's business, so every class with a base is answered
    and the caller picks; on a board with
    one relocated class that is one answer. The table is sorted once per class and searched
    by bisection: a listing of the full length against a table of thousands is the common
    case, and a scan of the table per operand would pay it hundreds of times."""
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
    """The bytes a caller wrote as hex, or the refusal. THE ONLY HEX PARSER THIS SERVER HAS.

    It is `bytes.fromhex`, which IGNORES ASCII WHITESPACE by documented design, so `de ad` is two
    bytes: the standard library's answer, and a line pasted out of a dump is exactly what
    somebody has in hand. One parser, so no two tools can disagree about what hex IS.

    `verb` is the ONE thing the two callers differ on -- what the bytes were FOR -- so it is a
    parameter rather than a second copy of the function.
    """
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
    """`find`'s machine-independent half: the bytes, and which of the two ways of naming a range
    was used. WHICH CLASS a `symbol_class` names is the machine's to answer -- the table's
    `class_span` is built from the table that machine was started with -- so that stays in `find`
    itself."""
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


# WHAT A SYMBOL CLASS'S SPAN IS AND WHAT IT IS NOT, in ONE place. `find` searches a class
# over it and `machine_map` reports it as the symbols' coverage of the machine: two tools
# answering two different spans for one class is the disagreement this constant prevents, and
# the caveat is the whole reason the span has to be said at all.
CLASS_SPAN = {"source": "class symbols",
              "note": "the class's symbols' [min, max]: a match past the last symbol's own "
                      "start is not covered"}


def find(ses: gs.Session, data_hex: str, ref: str, length: int,
         symbol_class: str = "", cpu: str = "") -> dict[str, Any]:
    """The body of the `find` tool."""
    # THE PARSED BYTES, NOT THE TEXT AGAIN: the parser tolerates whitespace, so re-slicing the
    # string two characters at a time would hand the console `0xde,0x a,0xd` for `de ad`. Parsing
    # once and carrying the bytes is the only version of this that cannot disagree with itself.
    wanted = check_find(data_hex, ref, length, symbol_class)
    named = inputs.cpu_given(cpu)
    on = cpus.chosen(ses, cpu)                  # the cpu whose program the search walks
    class_of: str | None = None
    # THE SPAN EXAMINED RIDES ON THE REPLY, with where it came from. A class's span is its
    # symbols' [min, max] and NOT the segment (a linker map carries no sizes), so zero hits
    # over it mean "not among the class's symbols" and a caller reading `symbol_class` alone took
    # it for "not in the segment" (on a V30 board the span ends at the last DATA
    # symbol, well short of the segment's end). Saying the span is what makes a zero honest.
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
    # a class's span as well as a `ref`+`length`, in `cpu`'s space, the visible one's by default
    space_bound(addr, length, on)
    items = ",".join(f"0x{b:02x}" for b in wanted)
    found: list[str] = []
    # The windows tile the range, the last one short. A hit belongs to the window it STARTS in
    # (the console's own rule), so a pattern running past a window's end is counted once.
    for start in range(addr, addr + length, FIND_WINDOW):
        width = min(FIND_WINDOW, addr + length - start)
        text = ses.monitor(f"find {start:#x}{f':{on}' if named else ''},{width:#x},{items}")
        window = _FOUND_AT.findall(text)
        # EVERY LINE IS A HIT, or the answer is `Not found` alone: a hit beside a line of any
        # other shape is a console that also said something else, and a count read off half
        # of an answer is not one.
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


# MAME'S OWN DEPTH, `device_debug::HISTORY_SIZE` (src/emu/debug/debugcpu.h): the console clamps
# a longer request to it in silence, so a ceiling above it would promise a trail nobody keeps.
HISTORY_MAX = 256


def check_history(limit: int = 32, **_: Any) -> None:
    inputs.count("limit", limit, HISTORY_MAX,
                   ": MAME keeps no deeper trail than that for a cpu")


NO_DISASSEMBLER = "No disassembler available for device"


def no_disassembler(ses: gs.Session, tag: str) -> str | None:
    """The console's own sentence when `tag` has no disassembler, which neither its trail nor a
    trace can be listed without; None when it has one. Asked through a one-line `history`."""
    lines = [line for line in ses.monitor(f"history {tag},1").splitlines() if line.strip()]
    return lines[0] if len(lines) == 1 and lines[0].startswith(NO_DISASSEMBLER) else None


def history(ses: gs.Session, limit: int, cpu: str = "") -> dict[str, Any]:
    """The body of the `history` tool."""
    check_history(limit)
    on = cpus.chosen(ses, cpu)                  # the cpu whose trail the console keeps
    text = ses.monitor(f"history {on if inputs.cpu_given(cpu) else ''},{limit:#x}")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0].startswith(NO_DISASSEMBLER):
        return menvelope.invalid("no_channel", f"{on} keeps no trail MAME can list: {lines[0]}")
    if not all(_HISTORY_LINE.match(line) for line in lines):
        return menvelope.invalid("unexpected_answer",
                                 "the console answered something other than a trail: "
                                 f"{text.strip()!r}")
    # WHAT CAME BACK IS THE LINES, and what was asked rides beside them: at the boot one
    # instruction has retired, not the eight asked for. NONE is an answer too: MAME prints
    # nothing for a cpu that has retired no instruction yet.
    note = ({} if lines else
            {"note": f"{on} has retired no instruction yet, so MAME keeps no trail for it"})
    return menvelope.envelope({"asked": limit, "lines": lines,
                               "cpu": or_unavailable(on, st.NO_CPU_READ_WHY), **note})


# WHY, for the reader of this code (the client gets the docstring above the code):
#
# The names come from the target description the stub sends and are not a fixed list: one
# cpu's names promised here would refuse every call on a board with another set. The m68k
# aliases (`A6`, `A7`, `SR`, `USP` over `FP`, `SP`, `PS`) are accepted by name and not listed,
# because the list is the description's own register file in register-number order and an alias
# has no number of its own. Both halves of that have to be said, or the omission reads as a
# discrepancy.
def registers(ses: gs.Session, cpu: str = "") -> dict[str, Any]:
    """The body of the `registers` tool. `register_bits` states each register's declared width in
    bits, so a reader does not have to count a value's hex digits to know a V30's EAX is 16
    bits wide. It rides on `registers` alone; a stop reply carries the values and the width
    stays in their digits there."""
    on, thread = cpus.thread_for(ses, cpu)
    lay = cpus.described(ses, on, thread)
    return menvelope.envelope({"regs": fmt_regs(ses, thread),
                               "register_bits": dict(lay.register_bits),
                               "cpu": or_unavailable(on, st.NO_CPU_READ_WHY)})


def registers_at_last_stop(ses: gs.Session, cpu: str = "") -> dict[str, Any]:
    """The body of `registers(from_last_stop=True)`: the registers AS THEY WERE at the last stop,
    marked stale, which answers on a running machine because it reads nothing off it."""
    check_registers(from_last_stop=True, cpu=cpu)
    # A DELIBERATE GUARD NO LIVE SESSION REACHES: `start` records its park as stop 1
    # (`running.record_park`), so a session that answers holds one.
    if not STATE.last_stop:
        raise st.Invalid("no_stop", "no stop yet in this session, so there are no last-stop "
                                    "registers to hand back")
    stop = STATE.last_stop
    # THE WIDTHS ARE THE STOP'S CPU'S, off its own thread's description, and there are none
    # for registers the survey could not read.
    widths = ({} if "available" in stop["regs"]
              else dict(cpus.layout(ses, stop.get("cpu")).register_bits))
    return menvelope.envelope({"regs": dict(stop["regs"]),
                               "cpu": or_unavailable(stop.get("cpu"), st.NO_CPU_READ_WHY),
                               "superseded": True,
                               "last_stop": STATE.as_of(), "register_bits": widths})


SYMBOLS_LIMIT_MAX = 50


def check_symbols_find(name: str = "", linear: str = "", limit: int = 10,
                       **_: Any) -> None:
    """`symbols_find`'s machine-independent half. Its refusals are verdicts about the arguments
    alone: which question was asked, how many answers were wanted, and a `linear` that is not
    written as an address."""
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

# One sorted copy per table, keyed by the cpu asked and checked by IDENTITY: tables are frozen
# and `start` replaces them whole, so a table that is not the cached object is a new board.
_PLACERS: dict[str | None, tuple[gs.SymbolTable, Placer]] = {}


def placer(cpu: str | None = None) -> Placer:
    """`cpu`'s table as a function from an address to the symbol it is inside: the highest at
    or below it, as (base, name), ties to the greatest name; None when the table is empty or
    every symbol sits above it. The table is sorted once and each address bisected, because a
    trace places every address it executed and a scan of the table per address is the cost
    that would dominate the call."""
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
    """The symbol `addr` is inside in `cpu`'s table (`placer`'s rule). The one routine that
    places an address, so `symbols_find`, a tally's writer table and a trace cannot disagree."""
    return placer(cpu)(addr)


def symbol_label(addr: int, cpu: str | None = None) -> str | None:
    """`addr` placed as a reply shows it, `NAME` or `NAME+0x12`, or None when no symbol sits at
    or below it (`nearest_symbol`)."""
    placed = nearest_symbol(addr, cpu)
    if placed is None:
        return None
    base, name = placed
    return name if addr == base else f"{name}+{addr - base:#x}"


def add_symbol(row: dict[str, Any], pc: int, cpu: str | None) -> dict[str, Any]:
    """Append `symbol` LAST to `row`, IN PLACE, when `cpu`'s table places `pc` (`symbol_label`),
    and return `row`, so a caller may use it as a statement or as an expression: every reply
    that shows a writer's pc names it the same way, in the same place. `cpu` passes through
    unchanged, since the table lookup already reads None and an unknown cpu its own way."""
    label = symbol_label(pc, cpu)
    if label is not None:
        row["symbol"] = label
    return row


def symbols_find(name: str, linear: str, limit: int,
                 kind: Callable[[int], str] | None = None,
                 cpu: str | None = None) -> dict[str, Any]:
    """The body of the `symbols_find` tool: a reader over `cpu`'s TABLE, the one `start` loaded
    for it, which is why it takes no session; the server still asks for the machine first,
    because the table is that session's and not the last one's, and names the cpu. `kind`
    answers what an address IS to that cpu (`ram`, `rom`, `latch`), from the console, when the
    caller has one to ask: None while the machine runs, and every symbol then reads `unknown`
    with a note."""
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
        key = name.strip().upper()
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
