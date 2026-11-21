"""Writes `src/scry_mame/knowledge_index/sources.json`, the index the vector dictionaries are held
to, from MAME's real source, or compares the committed file with it.

    python tools/knowledge_sources.py --mame DIR [--index PATH] [--specs DIR] [--check]

Exit 0: written, or equal under `--check`. Exit 1: `--check` and the committed index differs.
Exit 3: a source could not be read, a rule matched nothing (or more than once), or a spec is
malformed: an index that examined nothing is never written. Exit 2: a bad option.

`--mame DIR` is a tree holding the files of the MAME tag `PIN` at their own paths, fetched as
`https://raw.githubusercontent.com/mamedev/mame/<tag>/<path>`.

A row is the source's own line, tabs kept, so an entry's `cites` equals it character for
character. A rule that matches no line, or several where one was meant, is INVALID.

The chips' rows and lists are read from `tools/knowledge_specs/<chip>.json` (`--specs DIR`):

    {"rows":  [{"ref", "find", "key", "inside", "after", "until", "which", "marks"}, ...],
     "lists": [{"ref", "keys", "cases": {"file", "inside", "after", "until"}}, ...]}

A row is the one line of the file in `ref` (inside the function `inside`, after the line
matching `after`, before the one matching `until`) that matches the regular expression `find`;
`which` picks one of exactly `of` matches, counted from 0. A list is the keys a dictionary
must cover: each key is the key of a row of the same spec; `cases` makes the tool also demand
that every `case` label of that function (only those of the outermost `switch`) lies inside some
key, a label that is a name taking its number from the `enums` of `cases` (each `{"file",
"after"}` is the enum whose first enumerator matches `after`); and a list with `device_types` (a
file) holds exactly the short names of that file's `DEFINE_DEVICE_TYPE` lines.
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


SPECS = Path(__file__).resolve().parent / "knowledge_specs"
_CASE = re.compile(r"\bcase\s+([^:]+?)\s*:(?!:)")
_DEVICE_TYPE = re.compile(r'^DEFINE_DEVICE_TYPE(?:_NS)?\(\s*\w+\s*,\s*[\w:]+\s*,\s*"([^"]+)"')


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


def region(lines: list[str], inside: str, after: str, until: str) -> tuple[int, int]:
    """The first and one past the last line of the function `inside` (a definition starting in
    column 0 and closed by a `}` in column 0), narrowed to what follows the one line matching
    `after` and precedes the next matching `until`. No `inside` is the whole file."""
    start, end = 0, len(lines)
    if inside:
        starts = [i for i, text in enumerate(lines)
                  if text[:1] not in ("", " ", "\t", "/", "#") and not text.rstrip().endswith(";")
                  and re.search(rf"(?<![\w:]){re.escape(inside)}\s*[()]", text)]
        if len(starts) != 1:
            raise Invalid(f"{inside!r} is defined {len(starts)} times, not once")
        start = starts[0]
        closed = next((i + 1 for i in range(start + 1, len(lines)) if lines[i] == "}"), None)
        if closed is None:
            raise Invalid(f"{inside!r} has no closing `}}` in column 0")
        end = closed
    if after:
        found = [i for i in range(start, end) if re.search(after, lines[i])]
        if len(found) != 1:
            raise Invalid(f"{after!r} matches {len(found)} lines of {inside or 'the file'}, "
                          "not one")
        start = found[0]
    if until:
        found = [i for i in range(start + 1, end) if re.search(until, lines[i])]
        if not found:
            raise Invalid(f"nothing matches {until!r} after {after!r} in {inside or 'the file'}")
        end = found[0]
    return start, end


def _ref_file(ref: str) -> str:
    return ref.partition(":")[2].split(" ", 1)[0]


ROW_KEYS = {"ref", "find", "key", "inside", "after", "until", "which", "of", "marks"}
LIST_KEYS = {"ref", "keys", "cases", "device_types"}
CASES_KEYS = {"file", "inside", "after", "until", "enums"}


def _known(raw: dict[str, object], allowed: set[str], what: str) -> None:
    if unknown := sorted(set(raw) - allowed):
        raise Invalid(f"{what}: unknown key {', '.join(unknown)}")


def _spec_row(mame: Path, raw: dict[str, object]) -> tuple[str, dict[str, str]]:
    _known(raw, ROW_KEYS, f"row {raw.get('ref')}")
    ref = str(raw["ref"])
    lines = read(mame, _ref_file(ref))
    lo, hi = region(lines, str(raw.get("inside", "")), str(raw.get("after", "")),
                    str(raw.get("until", "")))
    found = [lines[i] for i in range(lo, hi) if re.search(str(raw["find"]), lines[i])]
    which, of = raw.get("which"), raw.get("of")
    if which is None and len(found) != 1:
        raise Invalid(f"{ref}: {raw['find']!r} matches {len(found)} lines, not one")
    if which is not None and not (
            type(which) is int and type(of) is int and 0 <= which < of == len(found)):
        raise Invalid(f"{ref}: {raw['find']!r} matches {len(found)} lines, and `which` {which!r} "
                      f"of `of` {of!r} needs exactly `of` matches")
    out = {"line": found[which if isinstance(which, int) else 0]}
    if raw.get("key"):
        out["key"] = str(raw["key"])
    if raw.get("marks"):
        out["marks"] = str(raw["marks"])
    return ref, out


def _number(text: str) -> int | None:
    try:
        return int(text.strip(), 0)
    except ValueError:
        return None


def _span(key: str) -> tuple[int, int] | None:
    lo, _, hi = key.partition("..")
    a, b = _number(lo), _number(hi or lo)
    return None if a is None or b is None else (a, b)


def _spec_list(mame: Path, raw: dict[str, object], rows: dict[str, dict[str, str]],
               held: set[str]) -> tuple[str, list[str]]:
    _known(raw, LIST_KEYS, f"list {raw.get('ref')}")
    ref = str(raw["ref"])
    if raw.get("device_types"):
        names = [m.group(1) for line in read(mame, str(raw["device_types"]))
                 if (m := _DEVICE_TYPE.match(line))]
        if not names:
            raise Invalid(f"{raw['device_types']} holds no DEFINE_DEVICE_TYPE line")
        return ref, names
    listed = [str(k) for k in raw.get("keys", [])]  # type: ignore[attr-defined]
    if not listed:
        raise Invalid(f"{ref}: a list with no keys examined nothing")
    for key in listed:
        if key not in held:
            raise Invalid(f"{ref}: key {key} is the key of no row of its spec")
        if key.startswith("0x") and ((span := _span(key)) is None or span[0] > span[1]):
            raise Invalid(f"{ref}: key {key} is no number or no upward range")
    if "cases" in raw:
        _cases_covered(mame, ref, raw["cases"], [_span(k) for k in listed])
    return ref, listed


def _enum(lines: list[str], after: str) -> dict[str, int]:
    """The enumerators of the enum whose first enumerator is the one line matching `after`: a name
    is its explicit number or the name of an earlier one, or one more than the one before."""
    firsts = [i for i, text in enumerate(lines) if re.search(after, text)]
    if len(firsts) != 1:
        raise Invalid(f"{after!r} matches {len(firsts)} lines, not the one of an enum")
    out: dict[str, int] = {}
    last = -1
    for text in lines[firsts[0]:]:
        code = re.sub(r"//.*|/\*.*?\*/", "", text).strip()
        if code.startswith("}"):
            break
        if not code:
            continue
        found = re.fullmatch(r"(\w+)(?:\s*=\s*(\w+))?,?", code)
        if not found:
            raise Invalid(f"an enumerator this tool cannot read: {text!r}")
        name, value = found.groups()
        last = (out[value] if value in out else int(value, 0)) if value else last + 1
        out[name] = last
    return out


def _depths(lines: list[str], lo: int, hi: int) -> list[int]:
    """The brace depth at the start of each line of `lines[lo:hi]`, comments and strings aside."""
    depth, out = 0, []
    for text in lines[lo:hi]:
        out.append(depth)
        code = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|//.*|/\*.*?\*/', "", text)
        depth += code.count("{") - code.count("}")
    return out


def _cases_covered(mame: Path, ref: str, cases: object,
                   spans: list[tuple[int, int] | None]) -> None:
    """Every `case` label of the function lies inside a key: by its number, or by the number the
    spec gives its name."""
    if not isinstance(cases, dict):
        raise Invalid(f"{ref}: `cases` is an object")
    _known(cases, CASES_KEYS, f"cases of {ref}")
    names: dict[str, int] = {}
    for enum in cases.get("enums", []):
        names |= _enum(read(mame, str(enum["file"])), str(enum["after"]))
    lines = read(mame, str(cases["file"]))
    lo, hi = region(lines, str(cases.get("inside", "")), str(cases.get("after", "")),
                    str(cases.get("until", "")))
    depths = _depths(lines, lo, hi)
    found = [(depths[i - lo], m) for i in range(lo, hi) for m in _CASE.findall(lines[i])]
    outer = min((d for d, _ in found), default=0)
    labels = [m for d, m in found if d == outer]
    if not labels:
        raise Invalid(f"{ref}: no `case` label in the function it must cover")
    for label in labels:
        n = names.get(label, _number(label))
        if n is None:
            raise Invalid(f"{ref}: `case {label}` is a name no enum of `enums` numbers")
        if not any(a <= n <= b for a, b in (s for s in spans if s is not None)):
            raise Invalid(f"{ref}: `case {label}` of {cases.get('inside', 'the file')} lies "
                          "inside no key of the list")


def chip_index(mame: Path, specs: Path) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """The rows and lists of every spec file under `specs`, and INVALID when there is none."""
    files = sorted(specs.glob("*.json")) if specs.is_dir() else []
    if not files:
        raise Invalid(f"{specs} holds no spec file: the chips' index would examine nothing")
    rows: dict[str, dict[str, str]] = {}
    lists: dict[str, list[str]] = {}
    for file in files:
        doc = json.loads(file.read_text(encoding="utf-8"))
        _known(doc, {"rows", "lists"}, file.name)
        mine: dict[str, dict[str, str]] = {}
        for raw in doc.get("rows", []):
            ref, found = _spec_row(mame, raw)
            if ref in rows or ref in mine:
                raise Invalid(f"{file.name}: {ref} is a row twice")
            mine[ref] = found
        held = {r["key"] for r in mine.values() if "key" in r}
        for raw in doc.get("lists", []):
            ref, keys = _spec_list(mame, raw, mine, held)
            if ref in lists:
                raise Invalid(f"{file.name}: {ref} is a list twice")
            lists[ref] = keys
        rows |= mine
    return rows, lists


def build(mame: Path, specs: Path | None = SPECS) -> dict[str, object]:
    rows = {rule.ref: row(mame, rule) for rule in RULES}
    nec = _constants(mame, f"{NEC}necpriv.ipp", r"^\tNEC_\w+_VECTOR\s+= (\d+),?$")
    m6809 = [f"0x{int(k, 16):02X}" for k in _constants(
        mame, f"{M6809}m6809.h", r"^\t\tVECTOR_\w+\s+= (0x[0-9A-Fa-f]+),?$")]
    lists = {LIST_M68000: _states(mame), LIST_V30: nec, LIST_M6809: m6809}
    if specs is not None:
        chip_rows, chip_lists = chip_index(mame, specs)
        if chip_rows.keys() & rows.keys() or chip_lists.keys() & lists.keys():
            raise Invalid("a chip spec names a row or a list of the vector rules")
        rows |= chip_rows
        lists |= chip_lists
    return {"format": INDEX_FORMAT, "pins": {"mame": PIN}, "rows": dict(sorted(rows.items())),
            "lists": lists}


def main(argv: Sequence[str] | None = None) -> int:
    ask = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ask.add_argument("--mame", type=Path, required=True)
    ask.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    ask.add_argument("--specs", type=Path, default=SPECS)
    ask.add_argument("--check", action="store_true")
    try:
        given = ask.parse_args(argv)
    except SystemExit as bad:
        return 2 if bad.code else 0
    try:
        text = dumps(build(given.mame, given.specs))
    except (Invalid, KeyError, ValueError, OSError, re.error) as bad:
        print(f"INVALID: {type(bad).__name__}: {bad}", file=sys.stderr)
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
