"""Holds the names a live run's replies carry to the knowledge base the server serves.

Each `names` item's id and each disassembled line's note is held to the base; the program's own
symbols and the machine's memory names are not the base's.

    uv run python tests/live/name_check.py [DIRECTORY...]

Exit 0 clean, 1 a finding, 3 INVALID: no directory, no reply, or no name examined.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scry_core import abbreviation
from scry_core.knowledge.base import Base, Served

from scry_mame import naming

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "tmp" / "demos"

#: A note piece as `scry_core.notes` writes it: a name cut at `NAME_WIDTH`, then its number.
NOTE = re.compile(r"^(?P<name>.+) \((?P<number>(?:[A-Z]{2}=)?0x[0-9A-F]+)\)$")
#: The `names` kinds that are the program's own or the address map's, never the base's.
NOT_THE_BASE = frozenset({"symbol", "memory"})


@dataclass(frozen=True)
class Finding:
    where: str
    said: str
    why: str

    def __str__(self) -> str:
        return f"{self.where}: {self.said}: {self.why}"


@dataclass
class Examined:
    replies: int = 0
    #: Held to the base; `symbols` counts the ones that are the program's or the machine's.
    names: int = 0
    symbols: int = 0
    findings: list[Finding] = field(default_factory=list)


def reply_files(root: Path) -> list[Path]:
    """The `transcript.md`s under `root`, else every `.md` and `.jsonl`."""
    whole = sorted(p for p in root.rglob("*") if p.name.casefold() == "transcript.md")
    if whole:
        return whole
    return sorted(p for p in root.rglob("*") if p.suffix in (".md", ".jsonl"))


def replies(root: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    for path in reply_files(root):
        text = path.read_text(encoding="utf-8")
        name = str(path.relative_to(root))
        if path.suffix == ".jsonl":
            for n, line in enumerate(text.splitlines(), 1):
                if line.strip():
                    yield f"{name}:{n}", json.loads(line)
            continue
        for n, block in enumerate(_fenced_json(text), 1):
            yield f"{name} block {n}", block


def _fenced_json(text: str) -> Iterator[dict[str, Any]]:
    opening = "```json\n"
    start = text.find(opening)
    while start >= 0:
        body = start + len(opening)
        end = text.find("\n```", body)
        if end < 0:
            return
        try:
            found = json.loads(text[body:end])
        except json.JSONDecodeError:
            found = None
        if isinstance(found, dict):
            yield found
        start = text.find(opening, end + 4)


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def names(value: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for obj in _walk(value):
        block = obj.get("names")
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    yield item


def notes(value: dict[str, Any]) -> Iterator[tuple[str, str]]:
    for obj in _walk(value):
        instruction = obj.get("instruction")
        if isinstance(instruction, dict) and isinstance(instruction.get("note"), str):
            yield "instruction.note", instruction["note"]
        listed = obj.get("line_notes")
        if isinstance(listed, list):
            for row in listed:
                if isinstance(row, dict) and isinstance(row.get("note"), str):
                    yield f"line_notes[{row.get('line', '?')}].note", row["note"]


def _entries(base: Base, name: str) -> list[Served]:
    found = base.by_alias(name)
    if found or not name.endswith(abbreviation.CUT):
        return found
    prefix = name.removesuffix(abbreviation.CUT).casefold()
    return [entry for entry in base.entries() if entry.name.casefold().startswith(prefix)]


def _answers(entry: Served, name: str) -> bool:
    if entry.name == name:
        return True
    return name.endswith(abbreviation.CUT) and entry.name.casefold().startswith(
        name.removesuffix(abbreviation.CUT).casefold())


def _check_item(base: Base, where: str, item: dict[str, Any]) -> Finding | None:
    kind, said = item.get("kind"), item.get("name")
    if kind in NOT_THE_BASE or not isinstance(said, str):
        return None
    ident = item.get("id")
    if not isinstance(ident, str) or not ident:
        return Finding(where, f"`{said}` ({kind})", "the reply names a base entry with no id")
    found = base.by_id(ident)
    if found is None:
        return Finding(where, f"`{said}` ({ident})", "the base holds no entry with that id")
    if found.name != said:
        return Finding(where, f"`{said}` ({ident})", f"the base calls it `{found.name}`")
    return None


def _check_note(base: Base, where: str, note: str) -> Finding | None:
    """One note against the entries its name answers.

    The number is not held: a note prints the instruction's address, a vector's entry is keyed
    by its number."""
    for piece in note.split("; "):
        match = NOTE.match(piece)
        if match is None:
            return Finding(where, repr(piece), "a note without a name and a number")
        said = match["name"]
        entries = _entries(base, said)
        if not entries:
            return Finding(where, repr(piece), "the base does not answer that name")
        if not any(_answers(entry, said) for entry in entries):
            held = "; ".join(sorted({entry.name for entry in entries}))
            return Finding(where, repr(piece), f"the base calls it `{held}`")
    return None


def check(base: Base, root: Path) -> Examined:
    out = Examined()
    for where, reply in replies(root):
        out.replies += sum(1 for obj in _walk(reply) if "status" in obj)
        for item in names(reply):
            if item.get("kind") in NOT_THE_BASE:
                out.symbols += 1
                continue
            out.names += 1
            if (found := _check_item(base, where, item)) is not None:
                out.findings.append(found)
        for path, text in notes(reply):
            out.names += 1
            if (found := _check_note(base, f"{where} {path}", text)) is not None:
                out.findings.append(found)
    return out


def main(argv: Iterable[str]) -> int:
    given = [Path(arg) for arg in argv]
    absent = [str(path) for path in given if not path.is_dir()]
    roots = given or [DEFAULT]
    if not given and not DEFAULT.is_dir():
        print(f"INVALID: no replies at {DEFAULT}: give the directory a run recorded them in")
        return 3
    if absent:
        print(f"INVALID: no directory {', '.join(absent)}")
        return 3
    base = naming.base()
    total = Examined()
    for root in roots:
        found = check(base, root)
        print(f"NAME CHECK {root}: {found.replies} replies, {found.names} names, "
              f"{found.symbols} names of the program's and the machine's own, "
              f"{len(found.findings)} findings")
        for finding in found.findings:
            print(f"  {finding}")
        total.replies += found.replies
        total.names += found.names
        total.symbols += found.symbols
        total.findings.extend(found.findings)
    if not total.replies or not total.names:
        print(f"INVALID: examined {total.replies} replies, {total.names} names and "
              f"{total.symbols} names of the program's and the machine's own, so it answered "
              "nothing the base holds")
        return 3
    if total.findings:
        print(f"FAIL: {len(total.findings)} findings in {total.replies} replies, "
              f"{total.names} names")
        return 1
    print(f"OK: {total.replies} replies, {total.names} names, all answered by the base")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
