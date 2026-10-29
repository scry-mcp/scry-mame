"""What the declaration families share where an intent meets the machine."""

from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

from scry_core import declaration_rows
from scry_core import reply_contract as contract
from scry_core import value_format as vf

from scry_mame import declarations as dec
from scry_mame import files, inputs
from scry_mame import gdb_session as gs
from scry_mame import state as st
from scry_mame.state import STATE

BY_OPTIONS = ("auto", *dec.BY)
# Under a run the console started these stops send no packet, only the line.
_LISTED_STOP_LINE = re.compile(r"Stopped at (break|register)point [0-9A-Fa-f]+\b")


NO_DECL_CPU_WHY = "the declaration names no cpu: it acts on the visible one"


def decl_row(decl: dec.Declaration) -> dict[str, Any]:
    """A list row's identity with this server's cpu reason."""
    return declaration_rows.row(kind=decl.kind, ref=decl.ref, by=decl.by, cpu=decl.cpu,
                                cpu_why=NO_DECL_CPU_WHY, created_at=decl.created_at,
                                origin=decl.origin, own_origin=STATE.session_origin,
                                now=st.utc_now())


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

    try:
        return dec.Declaration(kind, by, ref, created_at=st.now(), origin=STATE.session_origin,
                               fingerprint=STATE.fingerprint(cpu), cpu=cpu, **watch)
    except dec.DeclarationError as e:
        raise st.Invalid("bad_argument", str(e)) from None


def held_names(kind: str, cpu: str | None) -> list[str]:
    """Bare names a call may repeat without being read as an address."""
    if STATE.store is None:
        return []
    return [d.ref for d in STATE.store.declarations()
            if d.kind == kind and d.cpu == cpu and d.by == "symbol"]


def held_triggers(cpu: str | None, block: str, by: str) -> list[str]:
    """Trigger names keeping a capture on `block` reachable after a rebuild."""
    if STATE.store is None:
        return []
    return [d.trigger for d in STATE.store.declarations()
            if d.kind == "watch" and d.cpu == cpu and d.trigger
            and not inputs.is_address(d.trigger) and STATE.store.matches(d, by, block)]


def classify_call(ref: str, cpu: str | None, kind: str | None = None,
                  held: Collection[str] = ()) -> str:

    return inputs.classify(ref, STATE.table(cpu).table, cpu or STATE.first_cpu,
                           [*(held_names(kind, cpu) if kind else ()), *held])


def decide_by(ref: str, by: str, cpu: str | None, kind: str) -> str:
    """`by` as given, or for `auto` decided once: pointer grammar, else the address rule."""
    if by not in ("auto", "pointer"):
        return by
    if (pr := vf.parse_pointer(ref)) is not None:
        inputs.zero_x(pr.base, "base")
        classify_call(pr.base, cpu)
        return "pointer"
    return by if by == "pointer" else classify_call(ref, cpu, kind)


def resolve_decl(decl: dec.Declaration) -> dec.Resolved:

    table = STATE.table(decl.cpu)
    return dec.resolve(decl, table.table, table.types)


def refuse_conflict(decl: dec.Declaration) -> None:
    """Ask the store first: a row armed for a refused declaration would be orphaned."""
    try:
        store().refuse_conflict(decl)
    except dec.DeclarationError as e:
        raise st.Invalid("ambiguous_ref", str(e)) from None


def inherited(decl: dec.Declaration) -> str:
    """The part of a stop's `cause` saying the declaration comes from a prior session.

    Declarations persist, so a run can be cut by one the caller never typed."""
    if decl.origin is None or STATE.session_origin is None:
        return ""
    if decl.origin == STATE.session_origin:
        return ""
    tools = ("`declaration_list(kind=\"regpoint\")` shows it and "
             "`declaration_clear(kind=\"regpoint\")` removes it"
             if decl.kind == "regpoint" else
             "`declaration_list(kind=\"watch\")`/`declaration_list(kind=\"breakpoint\")` shows it "
             "and `declaration_clear(kind=\"watch\")`/`declaration_clear(kind=\"breakpoint\")` "
             "removes it")
    return (" (a PERSISTENT declaration, re-armed from a prior session at `start`, not "
            f"declared by anything this session did: {tools})")


def running_on_arrival(ses: gs.Session) -> bool:
    """Whether the machine was running when the call arrived."""
    return bool(ses.running)


Refusal = tuple[contract.Code, str]


def debuglog_since(scratch: Path) -> list[str]:
    """The console's lines since the previous stop; moves the one shared mark.

    Read at every stop: a point typed through `debug` that cuts a console-started run
    (`gvblank`, `gtime`) leaves only its line, and missing it loses the hit."""
    since, STATE.debuglog_mark = files.lines_since(scratch / "debug.log", STATE.debuglog_mark)
    return since


def listed_stop_in(lines: list[str]) -> bool:
    """Whether `lines` hold a breakpoint's or registerpoint's stop (watchpoints: `watches`)."""
    return any(_LISTED_STOP_LINE.search(ln) for ln in lines)


def newest_listed_stop(lines: list[str]) -> str | None:
    """`break` or `register` for the newest stop in `lines`, or None; an action that resumes
    (`bpset a,1,{g}`) leaves its line in the window of the stop that really ended."""
    kinds = [m.group(1) for ln in lines if (m := _LISTED_STOP_LINE.search(ln)) is not None]
    return kinds[-1] if kinds else None
