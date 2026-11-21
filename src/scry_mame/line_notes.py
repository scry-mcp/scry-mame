"""The note a disassembled line carries from the base, apart from a person's comments. Only what
the instruction states outright is named, and every operand is looked up as the address of the
vector it names; a register's value is never guessed."""

from __future__ import annotations

import re
from typing import Any

from scry_core import notes

from scry_mame import cpus, naming, read

#: 68000 absolute operands (`$202e84.l`, `$7e0000.w`) and TRAP's number (`trap    #$0`).
_ABSOLUTE_68K = re.compile(r"(?<![#\w])\$([0-9A-Fa-f]+)\.[wl]\b")
_TRAP_68K = re.compile(r"^trap\s+#\$([0-9A-Fa-f]+)$", re.IGNORECASE)
_VECTORS_68K = {"chk": 6, "trapv": 7}
#: 6809 `$042C`, but not `<$B2` (direct page), `#$01` (immediate) or `$FFF8,X` (an offset).
_EXTENDED_6809 = re.compile(r"(?<![#<\w])\$([0-9A-Fa-f]{4})\b(?!\s*,)")
#: A branch's `$XXXX` is where it lands.
_BRANCH_6809 = re.compile(r"^l?b(ra|rn|hi|ls|cc|hs|cs|lo|ne|eq|vc|vs|pl|mi|ge|lt|gt|le|sr)$")
_VECTOR_6809 = {"swi": 0xFFFA, "swi2": 0xFFF4, "swi3": 0xFFF2}
#: The V30's `brk 21h`, and the two that name their own vector.
_BRK_V30 = re.compile(r"^brk\s+([0-9A-Fa-f]+)h$", re.IGNORECASE)
_VECTORS_V30 = {"brkv": 4, "chkind": 5}
_WIDTH = 4


def _vector_address(number: int) -> notes.Operand:
    return notes.Operand("address", number * _WIDTH)


def operands(cpu_type: str | None, text: str) -> list[notes.Operand]:
    """What `text` (an instruction as MAME prints it for `cpu_type`) states outright."""
    words = text.strip().split()
    mnemonic = words[0].lower().split(".")[0] if words else ""
    if cpu_type == "m68000":
        if (trap := _TRAP_68K.match(text.strip())) is not None:
            return [_vector_address(32 + int(trap.group(1), 16))]
        if mnemonic in _VECTORS_68K:
            return [_vector_address(_VECTORS_68K[mnemonic])]
        return [notes.Operand("address", int(m.group(1), 16))
                for m in _ABSOLUTE_68K.finditer(text)]
    if cpu_type == "v30":
        if (brk := _BRK_V30.match(text.strip())) is not None:
            return [_vector_address(int(brk.group(1), 16))]
        return [_vector_address(_VECTORS_V30[mnemonic])] if mnemonic in _VECTORS_V30 else []
    if cpu_type in ("m6809", "mc6809", "mc6809e"):
        if mnemonic in _VECTOR_6809:
            return [notes.Operand("address", _VECTOR_6809[mnemonic])]
        if _BRANCH_6809.match(mnemonic):
            return []
        return [notes.Operand("address", int(m.group(1), 16))
                for m in _EXTENDED_6809.finditer(text)]
    return []


def note(text: str, cpu: str | None) -> str | None:
    """The base's note for the instruction `text` of `cpu`, or None when it names nothing."""
    kind = cpus.cpu_type(cpu)
    scope = naming.MAMENAMER.scope(cpu)
    if scope is None:
        return None
    found = notes.note(naming.base(), scope, operands(kind, text))
    return None if found is None else found.text


def of_listing(lines: list[str], on: str | None) -> list[dict[str, Any]]:
    """`{line, note}` for each listing line the base names an operand of."""
    out: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        at = read.LISTED_AT.match(line)
        text = read.stop_instruction(line, int(at.group(1), 16) if at else 0, on)["text"]
        if (named := note(text, on)) is not None:
            out.append({"line": i, "note": named})
    return out


def on_disassembly(reply: dict[str, Any]) -> dict[str, Any]:
    """`reply` of `disassemble`, with `line_notes` when the base names an operand."""
    on = reply.get("cpu")
    if "lines" in reply and (listed := of_listing(reply["lines"], on if isinstance(on, str)
                                                 else None)):
        reply["line_notes"] = listed
    return reply


def on_instruction(row: dict[str, Any], cpu: str | None) -> dict[str, Any]:
    """The stop's `instruction`, with its `note` when the base names what it states."""
    if (named := note(row["text"], cpu)) is not None:
        row["note"] = named
    return row
