"""What the server names; adding a cpu is this file and its dictionary."""

from __future__ import annotations

from importlib import resources

from scry_core.knowledge import Chip, Scope, Support, sealed, shared
from scry_core.knowledge.base import Base

#: The first tier of MAME's chips. A chip's key is MAME's short name of the family's base type;
#: `types` are the short names whose register layout was read and is the same.
CHIPS: tuple[Chip, ...] = (
    Chip("ay8910", written=("register",),
         types=("ay8910", "ay8912", "ay8913", "ym2149", "ym3439", "ymz284", "ymz294",
                "sunsoft_5b_sound")),
    Chip("okim6295", written=("register", "command"), types=("okim6295",)),
    Chip("ym2151", written=("register",), types=("ym2151", "ym2164")),
    Chip("ym2203", written=("register",), types=("ym2203",)),
    Chip("ym2608", written=("register",), types=("ym2608",)),
    Chip("ym2610", written=("register",), types=("ym2610", "ym2610b")),
    Chip("ym2612", written=("register",), types=("ym2612", "ym3438", "ymf276")),
    Chip("ym3526", written=("register",), types=("ym3526",)),
    Chip("msm5205", written=("register",), types=("msm5205",)),
    Chip("upd7759", written=("register", "command"), types=("upd7759",)),
    Chip("sega315_5313", written=("register", "command"), types=("sega315_5313",)),
    Chip("sega315_5124", written=("register",),
         types=("sega315_5124", "sega315_5246", "sega315_5377")),
    Chip("i8255", written=("register", "command"), types=("i8255",)),
    Chip("i8251", written=("register", "command"), types=("i8251",)),
    Chip("z80sio", written=("register", "command"), types=("z80sio", "z80dart")),
    Chip("z80scc", written=("register", "command"),
         types=("scc8030", "scc80c30", "scc80230", "scc8530", "scc85c30", "scc85230",
                "scc85233", "scc8523l")),
    Chip("upd1990a", written=("register", "command"), types=("upd1990a", "upd4990a")),
    Chip("pia6821", written=("register",), types=("pia6821",)),
    Chip("mc68681", written=("register", "command"), types=("mc68681", "scn2681")),
    Chip("acia6850", written=("register",), types=("acia6850",)),
)

#: A cpu's `types` are MAME's own short names for it (`cpus.cpu_type`).
SUPPORT = Support(
    scopes=(
        Scope("m68000", written=("vector",), types=("m68000",)),
        Scope("v30", written=("vector",), types=("v30",)),
        Scope("m6809", written=("vector",), types=("m6809", "mc6809", "mc6809e")),
        *shared.CPUS,
    ),
    chips=(*shared.CHIPS, *CHIPS),
    live=("memory", "input", "device"),
)

#: Where this server's dictionaries of rows are, and the shared ones every server loads.
SOURCES = ("scry_mame", "scry_core")


def merged(*locks: sealed.Lock) -> sealed.Lock:
    """One lock of several, part by part: a part two of them seal is refused by name, as nothing
    says which seal holds."""
    held: dict[str, dict[str, sealed.Part]] = {}
    for lock in locks:
        for id_, parts in lock.sealed.items():
            mine = held.setdefault(id_, {})
            for part, got in parts.items():
                if part in mine:
                    raise ValueError(f"{id_}: the part {part} is sealed in two locks")
                mine[part] = got
    return sealed.Lock(held, tuple(r for lock in locks for r in lock.reopened))


def own_lock() -> sealed.Lock:
    name = "rows-lock.json"
    return sealed.parse_lock((resources.files("scry_mame") / "knowledge_index" / name).read_text(
        encoding="utf-8"), name)


def rows_lock() -> sealed.Lock:
    """The seals of the shared dictionaries and of this server's own."""
    return merged(shared.rows_lock(), own_lock())


def load(fts5: bool | None = None) -> Base:
    """The base this server serves: the entries the locks seal."""
    return Base.load(*SOURCES, lock=rows_lock(), fts5=fts5)
