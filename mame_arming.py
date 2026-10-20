"""The declarations' ARMING PRIMITIVES: what every family shares where an intent meets the
machine.

A declaration is an INTENT (`mame_declarations`). The families that put one into the debugger
and read it back are `mame_breakpoints`, `mame_watches` and `mame_regpoints`, and `start`'s re-arm
of the whole store is `mame_rearm`; what they share lives here, once: the store and a
declaration's shape (`declare`, `inherited`, `decl_row`), how a call's ref is classed and
resolved, and the stop lines the console logs for a row of its own lists. The debugger's lists
are `mame_lists`', a condition `mame_conditions`', a clear `mame_clear`'s.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

from scry_core import reply_contract as contract
from scry_core import value_format as vf
from scry_core.reply_contract import or_unavailable

import gdb_session as gs
import mame_declarations as dec
import mame_files as files
import mame_inputs as inputs
import mame_state as st
from mame_state import STATE

# The `by` VOCABULARY: what a declaration is made by, or `auto` to have it decided.
BY_OPTIONS = ("auto", *dec.BY)
# The stop lines of the rows this module lists (a breakpoint's and a registerpoint's), which send
# NO packet under a run the console started; a watchpoint's line is `mame_watches`', beside the
# parser that names its writer.
_LISTED_STOP_LINE = re.compile(r"Stopped at (break|register)point [0-9A-Fa-f]+\b")


#: A list row's fields its declaration does not hold.
NO_DECL_CPU_WHY = "the declaration names no cpu: it acts on the visible one"
UNDATED_WHY = "the row carries no date with an offset (declared before rows were dated)"
NO_ORIGIN_WHY = "the row names no session it was declared in"


def decl_row(decl: dec.Declaration) -> dict[str, Any]:
    """A list row's identity. `inherited` is the half a caller cannot work out from `origin`,
    because no reply names this session's own: a declaration the store brought back at
    `start`, raw addresses over the same build included, reads otherwise exactly like one
    declared here. `age_s` is the half that tells an old row from a recent one in a store
    other sessions share, computed now (`st.age_s`)."""
    return {"ref": decl.ref, "by": decl.by, "cpu": or_unavailable(decl.cpu, NO_DECL_CPU_WHY),
            "created_at": or_unavailable(decl.created_at, UNDATED_WHY),
            "origin": or_unavailable(decl.origin, NO_ORIGIN_WHY),
            "inherited": decl.origin != STATE.session_origin,
            "age_s": or_unavailable(st.age_s(decl.created_at), UNDATED_WHY)}


def stale_why() -> str:
    return ("a raw address declared against another build (a different ROM or symbol file, "
            "or none recorded): kept and never re-armed here. Declare it again to adopt it, "
            "or clear it")


def stale(decl: dec.Declaration) -> bool:
    """`dec.is_stale` against `decl`'s own cpu's build."""
    return dec.is_stale(decl, STATE.fingerprint(decl.cpu))


def store() -> dec.DeclarationStore:
    """The session's declarations, which `start` creates with the session."""
    if STATE.store is None:
        st.no_machine()
    return STATE.store


def declare(kind: str, by: str, ref: str, cpu: str | None = None,
            **watch: Any) -> dec.Declaration:
    """A declaration on `cpu` stamped with this session's origin, the clock and that cpu's
    build, or the refusal that names what was wrong with it."""
    try:
        return dec.Declaration(kind, by, ref, created_at=st.now(), origin=STATE.session_origin,
                               fingerprint=STATE.fingerprint(cpu), cpu=cpu, **watch)
    except dec.DeclarationError as e:
        raise st.Invalid("bad_argument", str(e)) from None


def held_names(kind: str, cpu: str | None) -> list[str]:
    """The names `cpu`'s declarations of `kind` are stored under BY NAME: the bare spellings a
    call may name back without being read as an address (a raw row's bare ref never is)."""
    if STATE.store is None:
        return []
    return [d.ref for d in STATE.store.declarations()
            if d.kind == kind and d.cpu == cpu and d.by == "symbol"]


def held_triggers(cpu: str | None, block: str, by: str) -> list[str]:
    """The names `cpu`'s capture on `block` (a ref of kind `by`) is triggered on: declared
    again, that capture stays reachable by its trigger's name after a rebuild drops it, as a
    declaration stored by name does (`held_names`); a capture on another block is a new one."""
    if STATE.store is None:
        return []
    return [d.trigger for d in STATE.store.declarations()
            if d.kind == "watch" and d.cpu == cpu and d.trigger
            and not inputs.is_address(d.trigger) and STATE.store.matches(d, by, block)]


def classify_call(ref: str, cpu: str | None, kind: str | None = None,
                  held: Collection[str] = ()) -> str:
    """The address rule (`inputs.classify`) for a ref a CALL typed on `cpu`: against that cpu's
    table, and, for a call that declares or clears declarations of `kind`, the names they are
    stored under, beside `held`."""
    return inputs.classify(ref, STATE.table(cpu).table, cpu or STATE.first_cpu,
                           [*(held_names(kind, cpu) if kind else ()), *held])


def decide_by(ref: str, by: str, cpu: str | None, kind: str) -> str:
    """`by` as given, or for `auto` decided ONCE: a pointer by its grammar, else the address
    rule itself (`classify_call`). A pointer's base is read by the address rule like any ref,
    whether `by` named the pointer or `auto` found it."""
    if by not in ("auto", "pointer"):
        return by
    if (pr := vf.parse_pointer(ref)) is not None:
        inputs.zero_x(pr.base, "base")
        classify_call(pr.base, cpu)
        return "pointer"
    return by if by == "pointer" else classify_call(ref, cpu, kind)


def resolve_decl(decl: dec.Declaration) -> dec.Resolved:
    """Where `decl` points against its own cpu's table, and its types."""
    table = STATE.table(decl.cpu)
    return dec.resolve(decl, table.table, table.types)


def refuse_conflict(decl: dec.Declaration) -> None:
    """The store's refusal, asked BEFORE the machine is touched: a row armed for a
    declaration the store then refused would be listed by nothing and cleared by nothing."""
    try:
        store().refuse_conflict(decl)
    except dec.DeclarationError as e:
        raise st.Invalid("ambiguous_ref", str(e)) from None


# ----------------------------------------------------------------- a declaration at a stop


def inherited(decl: dec.Declaration) -> str:
    """The half of a stop's `how` that says the declaration is not this session's.

    DECLARATIONS PERSIST ACROSS SESSIONS, which is the point of the store: a watch declared
    yesterday re-arms itself at the next `start`. So a run can be cut by something the caller
    never declared and cannot see in anything they typed, and `OTHER_STOP` then reads as a
    condition somebody wrote badly rather than as an inheritance. Saying whose it is turns a
    puzzle into a `watch_clear`.

    IT SAYS THE FACT ONCE. `watch_stop` already appended a terse "(re-armed from a prior
    session)" of its own, so calling this beside it stated the same thing twice in one
    string; this replaces that text rather than joining it."""
    if decl.origin is None or STATE.session_origin is None:
        return ""
    if decl.origin == STATE.session_origin:
        return ""
    tools = ("`regpoint_list` shows it and `regpoint_clear` removes it"
             if decl.kind == "regpoint" else
             "`watch_list`/`breakpoint_list` shows it and `watch_clear`/`breakpoint_clear` "
             "removes it")
    return (" (a PERSISTENT declaration, re-armed from a prior session at `start`, not "
            f"declared by anything this session did: {tools})")


def running_on_arrival(ses: gs.Session) -> bool:
    """Whether the machine was running when a declaring call ARRIVED, read once at its entry,
    which is what its `while_running` says: a stop the call's own round trips let through (a
    condition it armed, firing an instruction later) is the next contact's, as `last_stop`
    reports it."""
    return bool(ses.running)


Refusal = tuple[contract.Code, str]


# ------------------------------------------------------------------ the console's stop lines


def debuglog_since(scratch: Path) -> list[str]:
    """The console's lines since the previous stop, and the ONE mark moved to where the log
    ends now. Read at EVERY stop, whether or not this server armed anything: a watchpoint or
    a breakpoint typed through `debug` that cuts a run the console started (`gvblank`,
    `gtime`) leaves NO stop packet and only its line, and a survey that did not read the log
    took that stop for a landing, so `run_for(frames=N)` resumed it with the next `gvblank`
    and every hit was lost. Both readings of a stop (`watch_stop`, `foreign_breakpoint`) take
    their lines from here, so no line is read by one and lost to the other."""
    since, STATE.debuglog_mark = files.lines_since(scratch / "debug.log", STATE.debuglog_mark)
    return since


def listed_stop_in(lines: list[str]) -> bool:
    """Whether the console logged a breakpoint's or a registerpoint's stop among `lines`; the
    watchpoint's half is `mame_watches.stop_line_in`, and `mame_running.stop_logged_in` asks
    both."""
    return any(_LISTED_STOP_LINE.search(ln) for ln in lines)


def newest_listed_stop(lines: list[str]) -> str | None:
    """Which family logged the NEWEST stop among `lines`, `break` or `register`, or None. A
    row whose action resumes the machine (`bpset a,1,{g}`) leaves its line in the window of
    the stop that really ended the run, and the machine stands at the last one."""
    kinds = [m.group(1) for ln in lines if (m := _LISTED_STOP_LINE.search(ln)) is not None]
    return kinds[-1] if kinds else None
