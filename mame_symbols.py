"""The symbol tables a start loads, one per cpu (why: REFERENCE.md, The session).

One path is keyed `None` until the machine names the first cpu (`Loaded.keyed`); a mapping
names its cpus and is judged against the machine's list before anything is spawned.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from scry_core import judges
from scry_core import value_format as vf

import gdb_session as gs
import mame_cpus as cpus
import mame_declarations as dec
import mame_files as files
import mame_inputs as inputs
import mame_state as st

#: `symbols` as `start` takes it: one path, or one path per cpu.
Given = str | dict[str, str]
#: `bases` beside one path (class to base), or beside a mapping (cpu to class to base).
Bases = dict[str, str] | dict[str, dict[str, str]]
#: `types` beside one path, or one file per cpu beside a mapping.
Types = str | dict[str, str]


def expanded(files: Given) -> Given:
    """`files` with each `~` expanded (`judges.expanded`)."""
    if isinstance(files, dict):
        return {cpu: judges.expanded(path) for cpu, path in files.items()}
    return judges.expanded(files)


def is_mapping(symbols: Given) -> bool:
    """Whether `symbols` names its cpus; an empty mapping is no table, as `""` is."""
    return isinstance(symbols, dict) and bool(symbols)


@dataclass(frozen=True)
class Loaded:
    """Every table a start loaded, by cpu, and its file."""

    tables: dict[str | None, gs.SymbolTable]
    paths: dict[str | None, Path]

    def keyed(self, first: str | None) -> dict[str | None, gs.SymbolTable]:
        """The tables with the one path's table under the first cpu's tag.
        With no tag it stays under `None`, which `State.table` serves for every cpu."""
        return {first if cpu is None else cpu: t for cpu, t in self.tables.items()}

    def path_of(self, cpu: str | None, first: str | None) -> Path | None:
        """The file `cpu`'s table came from, if any."""
        if cpu == first and None in self.paths:
            return self.paths[None]
        return self.paths.get(cpu)


def named_files(symbols: Given, types: Types) -> list[tuple[str, str, str]]:
    """Every file named, as (argument, path, what it is). A `types` entry of `""` is a cpu
    with no types file; a `symbols` entry has no such meaning."""
    out: list[tuple[str, str, str]] = []
    for argument, given, thing in (("symbols", symbols, "symbol file"),
                                   ("types", types, "types file")):
        named = ({f"{argument}[{cpu!r}]": path for cpu, path in given.items()
                  if path or argument == "symbols"}
                 if isinstance(given, dict) else {argument: given} if given else {})
        out += [(name, path, thing) for name, path in named.items()]
    return out


def check_files(symbols: Given, types: Types) -> None:
    """Every named file is an input file (`inputs.input_file`)."""
    for name, path, thing in named_files(symbols, types):
        inputs.input_file(name, path, thing)


def _parse_bases(bases: dict[str, str]) -> dict[str, int | None]:
    """One table's `bases`: `rom` is the one non-hex value (resident at its linear address)."""
    return {k.upper(): (None if v.strip().lower() == "rom" else inputs.hex_arg(f"bases[{k!r}]", v))
            for k, v in bases.items()}


def _one(name: str, path: str, bases: dict[str, str], types: str) -> gs.SymbolTable:
    """One cpu's table: the file read under its `bases`, `types` merged over its `type:` lines.
    A reader complaint is refused as argument `name`; an unreadable file is `unreadable`."""
    parsed = _parse_bases(bases)
    try:
        table = gs.symbols(path, parsed)
    except OSError as e:
        raise files.unreadable("symbol file", path, e) from None
    except ValueError as e:
        raise st.Invalid("bad_argument", f"{name}: {e}") from None
    if types:
        table = replace(table, types={**table.types, **read_types(types)})
    unknown = sorted(n for n in table.types if n not in table.table)
    if unknown:
        raise st.Invalid("bad_argument",
                         f"types are named for symbols the table lacks: {unknown[:5]}")
    return table


def read_types(path: str) -> dict[str, str]:
    """A `types` file read for `start`; a refusal names the file and line."""
    text = files.read_text("types", path, "types file")
    try:
        return vf.read_types(text, path)
    except vf.FormatError as e:
        raise st.Invalid("bad_argument", str(e)) from None
    except ValueError as e:
        # A value the grammar matched and Python could not hold (array count past the int limit).
        raise st.Invalid("bad_argument", f"{path}: {e}") from None


def _per_cpu(what: str, value: dict[str, str] | dict[str, dict[str, str]] | str,
             mapped: dict[str, str], tags: list[str]) -> dict[str, object]:
    """`bases` or `types` beside a mapping: one entry per cpu, keyed by resolved tag. The
    one-path shape is refused: it does not say which cpu's program it describes."""
    entry_type = dict if what == "bases" else str
    if not isinstance(value, dict) or not all(isinstance(v, entry_type) for v in value.values()):
        raise st.Invalid("bad_argument",
                         f"`{what}` beside a `symbols` mapping is one entry per cpu "
                         f"({'{cpu: {class: base}}' if what == 'bases' else '{cpu: path}'}): a "
                         f"{what} describes one cpu's program")
    out: dict[str, object] = {}
    for name, entry in value.items():
        tag = cpus.match_tag(name, tags)
        if tag in out:
            raise st.Invalid("bad_argument", f"`{what}` names one cpu twice: {sorted(value)}")
        if tag not in mapped:
            raise st.Invalid("bad_argument",
                             f"`{what}` names {tag}, which the `symbols` mapping gives no table: "
                             f"its cpus are {sorted(mapped)}")
        out[tag] = entry
    return out


def load(symbols: Given, bases: Bases | None, types: Types, tags: list[str]) -> Loaded:
    """Every table `symbols` names, judged before the machine exists."""
    if not is_mapping(symbols):
        path = symbols if isinstance(symbols, str) else ""
        if bases and any(isinstance(v, dict) for v in bases.values()):
            raise st.Invalid("bad_argument",
                             "`bases` is one entry per cpu only beside a `symbols` mapping; "
                             "beside one path it maps each class to its base")
        if isinstance(types, dict):
            raise st.Invalid("bad_argument",
                             "`types` is one file per cpu only beside a `symbols` mapping; "
                             "beside one path it is one file")
        flat: dict[str, str] = {k: v for k, v in (bases or {}).items() if isinstance(v, str)}
        if flat and not path:
            raise st.Invalid("bad_argument",
                             "`bases` was given with no `symbols` file to apply it to")
        if types and not path:
            raise st.Invalid("bad_argument", "`types` was given with no `symbols` file: a type "
                                             "names a symbol, and there is none to name")
        if not path:
            return Loaded({}, {})
        return Loaded({None: _one("symbols", path, flat, types)}, {None: Path(path)})
    assert isinstance(symbols, dict)
    mapped = {cpus.match_tag(name, tags): path for name, path in symbols.items()}
    given = {cpus.match_tag(name, tags): name for name in symbols}
    if len(mapped) != len(symbols):
        raise st.Invalid("bad_argument", f"`symbols` names one cpu twice: {sorted(symbols)}")
    per_bases = _per_cpu("bases", bases, mapped, tags) if bases else {}
    per_types = _per_cpu("types", types, mapped, tags) if types else {}
    tables: dict[str | None, gs.SymbolTable] = {}
    for tag, path in mapped.items():
        entry = per_bases.get(tag, {})
        typed = per_types.get(tag, "")
        assert isinstance(entry, dict) and isinstance(typed, str)
        tables[tag] = _one(f"symbols[{given[tag]!r}]", path, entry, typed)
    return Loaded(tables, {tag: Path(p) for tag, p in mapped.items()})


def store_key(system: str, loaded: Loaded, tags: list[str]) -> str | None:
    """The store's key, or None when no table was given.

    Keyed by the system and the FIRST cpu's file, so adding a table for another cpu keeps the
    store; without the first cpu's table, by the first cpu it gives, named."""
    if None in loaded.paths:
        return dec.store_key(system, str(loaded.paths[None]))
    for tag in tags:
        if tag in loaded.paths:
            key = dec.store_key(system, str(loaded.paths[tag]))
            return key if tag == tags[0] else f"{key} {tag}"
    return None


def fingerprint(system: str, reference_rom: Path, symbols: Path | None,
                cpu: str | None = None) -> str:
    """The build a declaration is judged against: a hash of system, reference ROM and symbol
    file, plus the tag of any cpu but the first."""
    digest = hashlib.sha256(system.encode())
    digest.update(reference_rom.read_bytes())
    if symbols is not None:
        digest.update(b"\0" + symbols.read_bytes())
    if cpu is not None:
        digest.update(b"\0cpu " + cpu.encode())
    return digest.hexdigest()[:16]
