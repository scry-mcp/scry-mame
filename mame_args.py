from __future__ import annotations

from collections.abc import Callable
from typing import Any

import mame_launch as launch
import mame_sequence as sequence

#: Shares the batch's table: no operation judged at the surface is skipped in a batch.
BY_TOOL: dict[str, Callable[..., Any]] = {
    **sequence.BY_OP,
    "rom_check": launch.check_rom_check,
    "start": launch.check_start,
    "perform": sequence.check_perform,
    "drive": sequence.check_drive,
}

#: Named: an absent entry and a forgotten one look identical.
MACHINE_JUDGES = sequence.MACHINE_JUDGES | (sequence.NOT_STEPS - BY_TOOL.keys())

KNOWN = frozenset(BY_TOOL) | MACHINE_JUDGES


def check(tool: str, /, **given: Any) -> None:
    """Run the machine-independent checks; an unknown tool is a bug."""
    if tool not in KNOWN:
        raise AssertionError(f"no such tool for a pre-gate check: {tool!r}")
    judge = BY_TOOL.get(tool)
    if judge is not None:
        judge(**given)
