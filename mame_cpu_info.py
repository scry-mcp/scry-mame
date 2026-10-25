"""The `cpu_info` body: listings and register reads only, so no cpu is made visible."""

from __future__ import annotations

from typing import Any

from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_inputs as inputs
import mame_iotaps as iotaps
import mame_state as st
from mame_state import STATE


def _counts(tags: list[str]) -> dict[str, dict[str, int]]:
    """Declaration counts per cpu: `tags` with zeros, then any other cpu a declaration names."""
    held = STATE.store.counts_by_cpu(iotaps.taps_by_cpu()) if STATE.store is not None else {}
    return {cpu: held.get(cpu) or dec.no_counts()
            for cpu in [*tags, *(c for c in held if c not in tags)]}


#: Why a row of a cpu `cpulist` does not list reads nothing.
UNLISTED_WHY = "`cpulist` does not list this cpu, so nothing of it is read"


def cpu_info(ses: gs.Session, cpu: str) -> dict[str, Any]:
    """The `cpu_info` body: a row per cpu, or the one `cpu` names."""
    tags, visible = cpus.listed(ses)
    counts = _counts(tags)
    # Judged against these rows so a named cpu is never an empty answer.
    wanted = cpus.match_tag(cpu, list(counts)) if inputs.cpu_given(cpu) else None
    shown = [tag for tag in counts if wanted in (None, tag)]
    ignored, suspended = cpus.ignored(ses), cpus.suspended(ses)
    read = [tag for tag in shown if tag in tags]
    pcs = {} if ses.running else cpus.pc_by_cpu(ses, read)
    # A half-read row is not a reading: a latched session is the answer.
    st.refuse_broken(ses)

    def reading(tag: str, value: Any, known: object) -> Any:
        if tag not in tags:
            return unavailable(UNLISTED_WHY)
        return value if known is not None else unavailable(
            "the console did not answer this listing")

    rows = [{"cpu": tag,
             "visible": reading(tag, tag == visible, visible),
             "ignored": reading(tag, tag in (ignored or []), ignored),
             "suspended": reading(tag, tag in (suspended or []), suspended),
             "pc": (cpus.pc_fields(pcs[tag]) if tag in pcs else unavailable(
                 UNLISTED_WHY if tag not in tags
                 else "the machine is RUNNING: no pc is read off a moving machine")),
             "declarations": counts[tag]} for tag in shown]
    reply: dict[str, Any] = {"cpus": rows, "cpu": or_unavailable(wanted, st.NO_CPU_NAMED_WHY)}
    return menvelope.envelope(reply)
