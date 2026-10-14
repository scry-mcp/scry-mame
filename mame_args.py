"""WHICH ARGUMENTS THE SERVER JUDGES BEFORE IT ASKS FOR THE MACHINE. A table, and nothing else.

THE RULE. An argument is judged BEFORE the session gate when its validity does not depend on the
machine, and after it when it does. It names the PROPERTY and never the argument: a `length` of
zero, a regex that does not compile, a `dest` this server requires to be absolute are each exactly
as wrong on a running machine as on no machine at all, while a `ref` is a symbol in THAT machine's
table and there is nothing to resolve it against without one. Naming the property is what lets
another server draw the same boundary and still land differently on `dest`, when a relative one
is resolved against a launch directory of its own.

The rule is two-sided because each half alone is a defect: judging everything first tells a caller
off about a `length` on a machine that does not exist; judging nothing first answers `no_session`
to a relative `dest`, a refusal that then cannot be seen without booting a machine.

**THIS MODULE HOLDS NO RULE OF ITS OWN.** Each rule lives in the module that owns it, exposed as a
`check_*` function that module calls itself, and this file decides only WHO IS ASKED AND WHEN. A
second copy of a rule, however faithful the day it is written, drifts from the first and nothing
compares the two; a rule cannot drift from itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import mame_launch as launch
import mame_sequence as sequence

#: TOOL -> the machine-independent half of its own module's checks. THE TABLE IS THE BATCH'S
#: (`mame_sequence.BY_OP`) plus the tools that are not operations (`perform` and `drive`, which ARE
#: the batch, `rom_check`, and `start`, whose half is the shape of its paths): one table, so an
#: operation cannot be judged at the surface and skipped in a batch, which would let a later step's
#: bad value run every step before it. Every value is a function of the module that does the work,
#: and that module calls the same function itself, so there is one implementation per rule.
BY_TOOL: dict[str, Callable[..., Any]] = {
    **sequence.BY_OP,
    "rom_check": launch.check_rom_check,
    "start": launch.check_start,
    "perform": sequence.check_perform,
    "drive": sequence.check_drive,
}

#: DELIBERATELY WITHOUT AN ENTRY: the batch's own list, plus `close`, which takes nothing to judge.
#: Named rather than omitted: an absent entry and a forgotten one look identical, and a test holds
#: this set plus `BY_TOOL` to the server's own registry.
MACHINE_JUDGES = sequence.MACHINE_JUDGES | {"close"}

#: Every tool `check` will answer for, computed once: this is on the path of every call.
KNOWN = frozenset(BY_TOOL) | MACHINE_JUDGES


def check(tool: str, /, **given: Any) -> None:
    """ASK WHAT THE MACHINE IS NOT NEEDED FOR, before the server asks for the machine.

    A tool in `MACHINE_JUDGES` passes straight through. A name this module has never heard of does
    NOT: that is a programmer's error here, not a caller's, and an unknown key slipping through
    would make the pre-gate check a no-op nobody notices -- the substitution-that-matched-nothing
    failure in another costume. It is raised as the programmer's error it is, which the server's
    refusal wrapper deliberately does not translate.
    """
    if tool not in KNOWN:
        raise AssertionError(f"no such tool for a pre-gate check: {tool!r}")
    judge = BY_TOOL.get(tool)
    if judge is not None:
        judge(**given)
