"""Clearing a declaration: the rows a ref owns, the console command that removes each, and the
refusals and records around a clear, shared by breakpoints, watches and registerpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, NamedTuple

from scry_core import prose
from scry_core import vocabulary as vocab

import gdb_session as gs
import mame_arming as arming
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_inputs as inputs
import mame_lists as mlists
import mame_state as st
from mame_state import STATE

_CLEAR_WORD = {"breakpoint": "bpclear", "watch": "wpclear", "registerpoint": "rpclear"}


def clear_command(kind: str, index: int) -> str:
    """The console command that removes one row by index; `0x` because a bare `D0` or `A` would
    be evaluated as a cpu register."""
    return f"{_CLEAR_WORD[kind]} {index:#x}"


def pasted_clear(kind: str, index: int) -> str:
    """`clear_command` as a reply pastes it, ready to type through `debug`."""
    return f'`debug("{clear_command(kind, index)}")`'


def another_condition(kind: Literal["breakpoint", "watch"], addr: int, row: dict[str, Any],
                      declared: str, width: int | None = None) -> st.Invalid:
    """Refusal for a row already held where a declaration would arm, under another condition."""
    span = f" for {prose.counted(width, 'byte')}" if width else ""
    held = "under another condition" if row.get("condition") else "with no condition"
    theirs = (f"this declaration's is {declared!r}" if declared
              else "this declaration has none")
    lead = (f"the debugger already holds a row at {addr:#x}{span} {held} ({row['entry']}), and "
            f"{theirs}: {pasted_clear(kind, row['index'])} removes it, or ")
    # One literal per family: the refusal scan reads a tool name only inside a literal.
    if kind == "breakpoint":
        return st.Invalid("ambiguous_ref", f"{lead}`declaration_clear(kind=\"breakpoint\")` when a "
                                           "declaration of this server owns it "
                                           "(`declaration_list(kind=\"breakpoint\")` says)")
    return st.Invalid("ambiguous_ref", f"{lead}`declaration_clear(kind=\"watch\")` when a "
                                       "declaration of this server "
                                       "owns it (`declaration_list(kind=\"watch\")` says)")


ClearKind = Literal["breakpoint", "watch", "regpoint"]


def one_declaration(thing: str, other: str, clear_kind: ClearKind | None, cpu: str | None,
                    space: str = "") -> str:
    """Sentence for a second declaration of what `other` holds on `cpu`; with no `clear_kind` it
    ends at the rule, for a report no call answers."""
    rule = f"one {thing} is one declaration"
    if clear_kind is None:
        return rule
    on = (f', cpu="{cpu}"' if cpu else "") + (f', space="{space}"' if space else "")
    return (f"{rule}, so `declaration_clear(kind=\"{clear_kind}\", ref={other!r}{on})` frees "
            "it, or use that ref")


def check_clear(ref: str, all_: bool, family: Literal["breakpoint", "watch", "regpoint"]
                ) -> None:
    vocab.check_clear_scope(ref, all_, family)


def kept_fields(clear_kind: ClearKind, ref: str) -> dict[str, Any]:
    """What a `readback_refused` reply says of the declaration it leaves behind."""
    return {"stored": True, "armed": False, "state": "gone",
            "note": f"the declaration is kept and re-arms at the next `start`; "
                    f'declaration_clear(kind="{clear_kind}", ref={ref!r}) removes it'}


class Clearing(NamedTuple):
    """What a clear reaches, and what its refusal names when that is nothing."""
    going: list[dec.Declaration]    # the declarations `ref` names on the cpus cleared
    held: list[dec.Declaration]     # every declaration of the kind held on those cpus
    away: list[dec.Declaration]     # what `ref` names outside the cpu the clear named
    cpu: str | None                 # the cpu the clear named, None for every cpu


def clearing(ses: gs.Session, kind: str, ref: str, cpu: str) -> Clearing:
    """A clear's declarations of `kind`: those `ref` names (all with no ref), on `cpu` or every
    cpu, the kind's held ones there, and what `ref` names elsewhere (another cpu, or an
    expression watch, which is on none). `ref` is classified once (`inputs.classify`) and
    compared under `dec.match_key`; an expression watch's text is a name, so a register such
    as `d0` is not an address."""
    only = cpus.named(ses, cpu) if inputs.cpu_given(cpu) else None
    kept = [d for d in arming.store().declarations() if d.kind == kind]
    held = [d for d in kept if only is None or d.cpu == only]
    text = ref.strip()
    if not text:
        return Clearing(held, held, [], only)
    by = "expr"
    if kind != "regpoint":
        tables = [STATE.table(only)] if only is not None else [*STATE.tables.values()] or [
            STATE.table()]
        names = {name for t in tables for name in t.table}
        by = inputs.classify(text, names, only,
                             [d.ref for d in kept if d.by in ("symbol", "expr")])
    named = [d for d in kept
             if arming.store().matches(d, d.by if d.by in ("expr", "pointer") else by, text)]
    return Clearing([d for d in named if d in held], held,
                    [d for d in named if d not in held], only)


def nothing_matched(ref: str, what: str, there: str, held: list[str], done: str) -> str:
    """Sentence for a `ref` that matched nothing: what was not done and what is held there."""
    return (f"{ref!r} matches no {what}{there}, so nothing was {done}. The {what}s held{there}: "
            f"{', '.join(held) or 'none at all'}.")


def refuse_unmatched_clear(ref: str, family: str, c: Clearing) -> dict[str, Any]:
    """A clear that reached nothing: what is held, and where `ref` names a declaration."""
    there = f" on {c.cpu}" if c.cpu is not None else ""
    where = ", ".join(sorted({d.cpu or "no cpu" for d in c.away}))
    expr = " (an expression watch is on none)" if any(d.cpu is None for d in c.away) else ""
    away = (f" {ref.strip()!r} names {prose.counted(len(c.away), family + ' declaration')} "
            f"held on {where}{expr}: the same clear with no "
            "`cpu` reaches it." if c.away else "")
    declares = "breakpoint_at" if family == "breakpoint" else f"{family}_add"
    nothing = nothing_matched(ref.strip(), f"{family} declaration", there,
                              [repr(d.ref) for d in c.held], "cleared")
    lead = (f"{nothing}{away} A `ref` is compared with the one the `{declares}` reply carried, "
            "which ")
    matching = f"Matching: {dec.REF_MATCH[family]}."
    # One literal per family: `test_every_refusal_of_the_three_families_names_the_call_that_\
    # resolves_it` reads literals, and an interpolated `{family}_list` names no tool there.
    if family == "breakpoint":
        return menvelope.invalid("unknown_ref",
                                 f"{lead}`declaration_list(kind=\"breakpoint\")` shows as `ref`. "
                                 f"{matching}")
    if family == "watch":
        return menvelope.invalid("unknown_ref", f"{lead}`declaration_list(kind=\"watch\")` "
                                                f"shows as `ref`. {matching}")
    return menvelope.invalid("unknown_ref", f"{lead}`declaration_list(kind=\"regpoint\")` shows as "
                                            f"`ref`. {matching}")


#: A row a clear takes down: owner, entry as listed, index.
Going = tuple[dec.Owner, str, int]


def disarm_rows(ses: gs.Session, kind: str, rows: list[Going],
                listed: Callable[[], list[dict[str, Any]]]
                ) -> tuple[list[Going], list[tuple[str, int]]]:
    """The removal every family shares: send each row's removal by index, read the list back
    once, so `disarmed` is the machine's answer. Returns the rows gone and those still shown."""
    if not rows:
        return [], []
    for _owner, _entry, index in rows:
        ses.monitor(clear_command(kind, index))
    after = listed()
    gone = [row for row in rows if mlists.row_at_index(after, row[2]) is None]
    return gone, [(entry, index) for _owner, entry, index in rows if (_owner, entry, index)
                  not in gone]


def still_held_note(kind: str, rows: list[tuple[str, int]]) -> str:
    """What a clear says of rows still listed after removal: the record stays, or the next stop
    there would read as foreign."""
    named = "address" if kind == "breakpoint" else "ref"
    commands = ", ".join(pasted_clear(kind, index) for _entry, index in rows)
    return (f"the debugger still lists {[entry for entry, _index in rows]} after the removal "
            f"was sent, so the record is kept and a stop there is still named by its {named}; "
            f"{commands} {'removes the row' if len(rows) == 1 else 'remove the rows'}")


def forget_rows_gone(ses: gs.Session, kind: str) -> list[dec.Owner]:
    """After a `bpclear` or `wpclear` typed through `debug` (`rpclear` is
    `mame_regpoints.forget_gone`): drop every record of a row the list no longer shows, and
    return the owners forgotten."""
    gone: list[dec.Owner] = []
    if kind == "breakpoint":
        held = mlists.bp_held(ses)
        for index, rec in list(STATE.breakpoints.items()):
            if mlists.row_at_index(held, index) is None:
                STATE.breakpoints.pop(index)
                STATE.controls.pop(rec["owner"], None)
                gone.append(rec["owner"])
        return gone
    held = mlists.wp_held(ses)
    for owner, armed in list(STATE.armed_watches.items()):
        if mlists.row_at_index(held, armed["index"]) is None:
            STATE.armed_watches.pop(owner)
            gone.append(owner)
    return gone


def row_index(index: int) -> str:
    """A row's index as the console lists print it (upper-case hex)."""
    return f"{index:X}"


def foreign_row_cause(kind: str, index: int, detail: str) -> str:
    """How a stop by a row this server did not place is named; ends with the removing command."""
    return f"{kind} {row_index(index)}{detail}: {pasted_clear(kind, index)} removes it"
