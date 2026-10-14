"""WHAT THE DEBUGGER SEES OF EACH CPU at the call, one row per cpu (the contract is `cpu_info`'s
in `server.py`). Nothing here moves the machine: the listings are the console's own (`cpulist`,
and `ignore` and `suspend` with no argument, which only list) and each pc is a register read off
the stub, so no cpu is made visible.
"""

from __future__ import annotations

from typing import Any

import gdb_session as gs
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_inputs as inputs
import mame_iotaps as iotaps
import mame_state as st
from mame_state import STATE


def _counts(tags: list[str]) -> dict[str, dict[str, int]]:
    """This server's declarations on each of `tags`, zeros included, then on any other cpu a
    declaration names."""
    held = STATE.store.counts_by_cpu(iotaps.taps_by_cpu()) if STATE.store is not None else {}
    return {cpu: held.get(cpu) or dec.no_counts()
            for cpu in [*tags, *(c for c in held if c not in tags)]}


#: Why a row of a cpu `cpulist` does not list reads nothing.
UNLISTED_WHY = "`cpulist` does not list this cpu, so nothing of it is read"


def cpu_info(ses: gs.Session, cpu: str) -> dict[str, Any]:
    """The body of the `cpu_info` tool: a row per cpu, or the one row `cpu` names."""
    tags, visible = cpus.listed(ses)
    counts = _counts(tags)
    # The name is judged against the rows this call gives, so a cpu listed unfiltered can be
    # named, and one named is never an empty answer.
    wanted = cpus.match_tag(cpu, list(counts)) if inputs.cpu_given(cpu) else None
    shown = [tag for tag in counts if wanted in (None, tag)]
    ignored, suspended = cpus.ignored(ses), cpus.suspended(ses)
    read = [tag for tag in shown if tag in tags]
    pcs = {} if ses.running else cpus.pc_by_cpu(ses, read)
    # A wait that ran out in one of the reads latched the session: a half-read row is not a
    # reading, so the latch is the answer.
    st.refuse_broken(ses)

    def reading(tag: str, value: Any, known: object) -> Any:
        """`value`, or `unavailable` for a cpu `cpulist` does not list, or a listing the console
        did not answer."""
        if tag not in tags:
            return st.unavailable(UNLISTED_WHY)
        return value if known is not None else st.unavailable(
            "the console did not answer this listing")

    rows = [{"cpu": tag,
             "visible": reading(tag, tag == visible, visible),
             "ignored": reading(tag, tag in (ignored or []), ignored),
             "suspended": reading(tag, tag in (suspended or []), suspended),
             "pc": (cpus.pc_fields(pcs[tag]) if tag in pcs else st.unavailable(
                 UNLISTED_WHY if tag not in tags
                 else "the machine is RUNNING: no pc is read off a moving machine")),
             "declarations": counts[tag]} for tag in shown]
    reply: dict[str, Any] = {"cpus": rows, "cpu": st.or_unavailable(wanted, st.NO_CPU_NAMED_WHY)}
    return menvelope.envelope(reply)
