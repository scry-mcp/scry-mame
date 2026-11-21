"""Writes `src/scry_mame/knowledge_index/sources.json`, the index the vector dictionaries are held
to, from MAME's real source, or compares the committed file with it.

    python tools/knowledge_sources.py --mame DIR [--index PATH] [--check]

Exit 0: written, or equal under `--check`. Exit 1: `--check` and the committed index differs.
Exit 3: a source could not be read or a rule matched nothing, or more than once: an index that
examined nothing is never written. Exit 2: a bad option.

`--mame DIR` is a tree holding the files of the MAME tag `PIN` at their own paths, fetched as
`https://raw.githubusercontent.com/mamedev/mame/<tag>/<path>`.

A row is the source's own line, tabs kept, so an entry's `cites` equals it character for
character. A rule that matches no line, or several where one was meant, is INVALID.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scry_core.knowledge.lock import dumps
from scry_core.knowledge.sources import INDEX_FORMAT

PIN = "mame0289"
DEFAULT_INDEX = (Path(__file__).resolve().parent.parent
                 / "src/scry_mame/knowledge_index/sources.json")

M68K = "src/devices/cpu/m68000/"
NEC = "src/devices/cpu/nec/"
M6809 = "src/devices/cpu/m6809/"


class Invalid(Exception):
    """A source or a rule that cannot give what the index needs: exit 3."""


@dataclass(frozen=True)
class Rule:
    """The one line of `file` that matches `find`, cited as `ref`, and the key it carries."""

    ref: str
    find: str
    key: str = ""

    def file(self) -> str:
        return self.ref.partition(":")[2].split(" ", 1)[0]


def _state(name: str, key: str) -> Rule:
    return Rule(f"mame:{M68K}m68000gen.py states {name}",
                rf'^    \[0x[0-9a-f]+, "{name}", {key}, (True|False)\],?$', key)


RULES: tuple[Rule, ...] = (
    _state("reset", "0"), _state("bus_error", "2"), _state("address_error", "3"),
    _state("illegal", "4"), _state("priviledge", "8"), _state("trace", "9"),
    _state("linea", "10"), _state("linef", "11"),
    Rule(f"mame:{M68K}m68000gen.py macro_tvn chk", r"^    macro_tvn = \(6 if \(ir & 0xf040\)", "6"),
    Rule(f"mame:{M68K}m68000gen.py macro_tvn trapv", r"^\s+7 if \(ir & 0xf060\) == 0x4060 else$",
         "7"),
    Rule(f"mame:{M68K}m68000gen.py macro_tvn fallback", r"^\s+5\)$", "5"),
    Rule(f"mame:{M68K}m68000gen.py trap-tvn", r'return "0x80 \| \(\(m_ird & 0xf\) << 2\)"'),
    Rule(f"mame:{M68K}m68kcommon.h autovector", r"static constexpr u8 autovector\(int level\)"),
    Rule(f"mame:{NEC}necpriv.ipp NEC_DIVIDE_VECTOR", r"^\tNEC_DIVIDE_VECTOR\s+= 0,$", "0"),
    Rule(f"mame:{NEC}necpriv.ipp NEC_TRAP_VECTOR", r"^\tNEC_TRAP_VECTOR\s+= 1,$", "1"),
    Rule(f"mame:{NEC}necpriv.ipp NEC_NMI_VECTOR", r"^\tNEC_NMI_VECTOR\s+= 2,$", "2"),
    Rule(f"mame:{NEC}necpriv.ipp NEC_BRKV_VECTOR", r"^\tNEC_BRKV_VECTOR\s+= 4,$", "4"),
    Rule(f"mame:{NEC}necpriv.ipp NEC_CHKIND_VECTOR", r"^\tNEC_CHKIND_VECTOR\s+= 5$", "5"),
    *(Rule(f"mame:{M6809}m6809.h {name}", rf"^\t\t{name}\s+= {value},?$", value)
      for name, value in (("VECTOR_SWI3", "0xFFF2"), ("VECTOR_SWI2", "0xFFF4"),
                          ("VECTOR_FIRQ", "0xFFF6"), ("VECTOR_IRQ", "0xFFF8"),
                          ("VECTOR_SWI", "0xFFFA"), ("VECTOR_NMI", "0xFFFC"),
                          ("VECTOR_RESET_FFFE", "0xFFFE"))),
)

#: The lists a dictionary must cover, by the name its `complete_against` gives.
LIST_M68000 = f"mame:{M68K}m68000gen.py vectors"
LIST_V30 = f"mame:{NEC}necpriv.ipp NEC_*_VECTOR"
LIST_M6809 = f"mame:{M6809}m6809.h VECTOR_*"


def read(mame: Path, file: str) -> list[str]:
    path = mame / file
    if not path.is_file():
        raise Invalid(f"{path} is not a file: fetch it from "
                      f"https://raw.githubusercontent.com/mamedev/mame/{PIN}/{file}")
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")


def row(mame: Path, rule: Rule) -> dict[str, str]:
    found = [line for line in read(mame, rule.file()) if re.search(rule.find, line)]
    if len(found) != 1:
        raise Invalid(f"{rule.ref}: {rule.find!r} matches {len(found)} lines, not one")
    out = {"line": found[0]}
    if rule.key:
        out["key"] = rule.key
    return out


def _states(mame: Path) -> list[str]:
    """The vector numbers of the special states and of the trapping instructions, as keys. The
    states are read off the source's own table, and a rule for each must exist."""
    table = {m.group(1) for line in read(mame, f"{M68K}m68000gen.py")
             if (m := re.match(r'^    \[0x[0-9a-f]+, "\w+", (\d+), (?:True|False)\],?$', line))}
    keys = {rule.key for rule in RULES if rule.ref.startswith(f"mame:{M68K}m68000gen.py")
            and rule.key}
    ruled = {rule.key for rule in RULES if "states" in rule.ref}
    if table != ruled:
        raise Invalid(f"m68000gen.py's states table holds vectors {sorted(table, key=int)} and "
                      f"the rules name {sorted(ruled, key=int)}: write a rule for each")
    levels = {int(m.group(1)) for line in read(mame, f"{M68K}m68000.cpp")
              if (m := re.search(r"return autovector\((\d)\);", line))}
    if levels != set(range(1, 8)):
        raise Invalid(f"m68000.cpp answers autovector for levels {sorted(levels)}, not 1 to 7")
    mask = [line for line in read(mame, f"{M68K}m68000gen.py")
            if 'return "0x80 | ((m_ird & 0xf) << 2)"' in line]
    if len(mask) != 1:
        raise Invalid("the TRAP vector formula is not on one line of m68000gen.py")
    keys |= {str(0x18 + level) for level in levels} | {str(0x20 + n) for n in range(16)}
    return sorted(keys, key=int)


def _constants(mame: Path, file: str, pattern: str) -> list[str]:
    keys = [m.group(1) for line in read(mame, file) if (m := re.search(pattern, line))]
    if not keys:
        raise Invalid(f"{file} holds no line like {pattern!r}")
    return keys


def build(mame: Path) -> dict[str, object]:
    rows = {rule.ref: row(mame, rule) for rule in RULES}
    nec = _constants(mame, f"{NEC}necpriv.ipp", r"^\tNEC_\w+_VECTOR\s+= (\d+),?$")
    m6809 = [f"0x{int(k, 16):02X}" for k in _constants(
        mame, f"{M6809}m6809.h", r"^\t\tVECTOR_\w+\s+= (0x[0-9A-Fa-f]+),?$")]
    return {"format": INDEX_FORMAT, "pins": {"mame": PIN}, "rows": dict(sorted(rows.items())),
            "lists": {LIST_M68000: _states(mame), LIST_V30: nec, LIST_M6809: m6809}}


def main(argv: Sequence[str] | None = None) -> int:
    ask = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ask.add_argument("--mame", type=Path, required=True)
    ask.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    ask.add_argument("--check", action="store_true")
    try:
        given = ask.parse_args(argv)
    except SystemExit as bad:
        return 2 if bad.code else 0
    try:
        text = dumps(build(given.mame))
    except Invalid as bad:
        print(f"INVALID: {bad}", file=sys.stderr)
        return 3
    if given.check:
        same = given.index.is_file() and json.loads(given.index.read_text(encoding="utf-8")) == \
            json.loads(text)
        print("equal" if same else f"{given.index} differs from the source at {PIN}")
        return 0 if same else 1
    given.index.parent.mkdir(parents=True, exist_ok=True)
    given.index.write_text(text, encoding="utf-8")
    print(f"wrote {given.index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
