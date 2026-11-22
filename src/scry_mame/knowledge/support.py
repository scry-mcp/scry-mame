"""What the server names; adding a cpu is this file and its dictionary."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import scry_core
from scry_core.knowledge import Base, Chip, Confirmation, Scope, Support, shared
from scry_core.knowledge.lock import parse_lock

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

_CORE = Path(scry_core.__file__).parent / "knowledge"


def confirmation() -> Confirmation:
    """The shared dictionaries' confirmation plus this server's lock. It has no second-check
    file of its own, so none of its own entries is confirmed."""
    own = (resources.files("scry_mame") / "knowledge_index" / "lock.json").read_text(
        encoding="utf-8")
    return Confirmation.of((*shared.locks(), parse_lock(own, "lock.json")),
                           (shared.second_check(),))


def load(fts5: bool | None = None) -> Base:
    return Base.load("scry_mame", _CORE / "chips", _CORE / "cpus", fts5=fts5, pins=shared.PINS,
                     confirmation=confirmation())
