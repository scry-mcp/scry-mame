"""What the server names; adding a cpu is this file and its dictionary."""

from __future__ import annotations

from pathlib import Path

import scry_core
from scry_core.knowledge import Base, Scope, Support, shared

#: A cpu's `types` are MAME's own short names for it (`cpus.cpu_type`).
SUPPORT = Support(
    scopes=(
        Scope("m68000", written=("vector",), types=("m68000",)),
        Scope("v30", written=("vector",), types=("v30",)),
        Scope("m6809", written=("vector",), types=("m6809", "mc6809", "mc6809e")),
        *shared.CPUS,
    ),
    chips=shared.CHIPS,
    live=("memory", "input", "device"),
)

_CORE = Path(scry_core.__file__).parent / "knowledge"


def load(fts5: bool | None = None) -> Base:
    return Base.load("scry_mame", _CORE / "chips", _CORE / "cpus", fts5=fts5, pins=shared.PINS)
