"""CLEARING A DECLARATION: which rows of the debugger's lists a ref owns, the console command that
takes each one away (pasted where a caller must type it, as it is in naming a row this server did
not arm), the refusal when a ref matches nothing, what a clear or a refused arm left behind, and
the records forgotten once their rows are gone from the lists. Breakpoints, watches and
registerpoints clear through these, so a clear says the same thing whichever family it ends.

And the sentences that point at a clear: a row under another condition, a place a second
declaration would hold (`one_declaration`), a ref that matched nothing (`nothing_matched`, which
comments and io taps say too).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, NamedTuple

from scry_core import prose

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
    """The console command that removes ONE row by its index, whoever placed it and whatever
    cpu it is under. `0x` because the console EVALUATES the index against the visible cpu's
    symbols: a bare `D0` is the register D0 on a 68000, a bare `A` the register A on a Z80,
    and either clears whatever row that register's value numbers."""
    return f"{_CLEAR_WORD[kind]} {index:#x}"


def pasted_clear(kind: str, index: int) -> str:
    """`clear_command` as a reply pastes it, ready to type through `debug`: the same spelling
    the server sends, so it can be typed as it stands on any cpu."""
    return f'`debug("{clear_command(kind, index)}")`'


def another_condition(kind: Literal["breakpoint", "watch"], addr: int, row: dict[str, Any],
                      declared: str, width: int | None = None) -> st.Invalid:
    """The one refusal for a row the debugger already holds where a declaration would arm, under
    a condition that is not the declaration's: adopting it would arm a stop that judges something
    else, so it is named with the command that removes it. Both sides of the comparison are
    said, either of which may be no condition at all."""
    span = f" for {prose.counted(width, 'byte')}" if width else ""
    held = "under another condition" if row.get("condition") else "with no condition"
    theirs = (f"this declaration's is {declared!r}" if declared
              else "this declaration has none")
    lead = (f"the debugger already holds a row at {addr:#x}{span} {held} ({row['entry']}), and "
            f"{theirs}: {pasted_clear(kind, row['index'])} removes it, or ")
    # ONE LITERAL PER FAMILY, as `refuse_unmatched_clear` writes it: the refusal scan reads a
    # backticked tool name only where it stands in the literal.
    if kind == "breakpoint":
        return st.Invalid("ambiguous_ref", f"{lead}`breakpoint_clear` when a declaration of this "
                                           "server owns it (`breakpoint_list` says)")
    return st.Invalid("ambiguous_ref", f"{lead}`watch_clear` when a declaration of this server "
                                       "owns it (`watch_list` says)")


ClearTool = Literal["breakpoint_clear", "watch_clear", "regpoint_clear"]


def one_declaration(thing: str, other: str, clear_tool: ClearTool | None, cpu: str | None,
                    space: str = "") -> str:
    """The one sentence for a second declaration of what `other` already holds on `cpu` (in
    `space`, named only outside the program's): a place is held by one declaration, so a caller
    frees it, on that cpu alone, or uses the one there. With no `clear_tool` the sentence ends at
    the rule, for a report (`start`'s re-arm) that no call answers."""
    rule = f"one {thing} is one declaration"
    if clear_tool is None:
        return rule
    on = (f', cpu="{cpu}"' if cpu else "") + (f', space="{space}"' if space else "")
    return f"{rule}, so `{clear_tool}(ref={other!r}{on})` frees it, or use that ref"


def check_clear(ref: str, all_: bool, family: Literal["breakpoint", "watch", "regpoint"]
                ) -> None:
    """A clear names what it takes: one `ref`, or `all=True` and no `ref`. An empty `ref` never
    means everything, since a value left out by mistake would otherwise empty the store."""
    if all_ and ref.strip():
        both = f"`all` clears every declaration of this kind and takes no `ref`; got ref={ref!r}"
        # ONE LITERAL PER FAMILY, as `refuse_unmatched_clear` writes it.
        if family == "breakpoint":
            raise st.Invalid("bad_argument", f"{both}: `breakpoint_clear(all=True)` alone")
        if family == "watch":
            raise st.Invalid("bad_argument", f"{both}: `watch_clear(all=True)` alone")
        raise st.Invalid("bad_argument", f"{both}: `regpoint_clear(all=True)` alone")
    if not all_ and not ref.strip():
        empty = (f"ref={ref!r} names nothing, and an empty ref never means every declaration: "
                 "the `ref` its declaring reply carried, or all=True to clear every one")
        if family == "breakpoint":
            raise st.Invalid("bad_argument", f"{empty} (`breakpoint_clear(all=True)`)")
        if family == "watch":
            raise st.Invalid("bad_argument", f"{empty} (`watch_clear(all=True)`)")
        raise st.Invalid("bad_argument", f"{empty} (`regpoint_clear(all=True)`)")


def kept_fields(clear_tool: str, ref: str) -> dict[str, Any]:
    """What a `readback_refused` reply says about the declaration it leaves behind: it was
    stored before the arm, so it is kept and re-arms at the next `start`, and the reply
    names the call that removes it."""
    return {"stored": True, "armed": False, "state": "gone",
            "note": f"the declaration is kept and re-arms at the next `start`; "
                    f"{clear_tool}(ref={ref!r}) removes it"}


class Clearing(NamedTuple):
    """What a clear of one kind reaches, and what its refusal names when it reaches nothing."""
    going: list[dec.Declaration]    # the declarations `ref` names on the cpus cleared
    held: list[dec.Declaration]     # every declaration of the kind held on those cpus
    away: list[dec.Declaration]     # what `ref` names outside the cpu the clear named
    cpu: str | None                 # the cpu the clear named, None for every cpu


def clearing(ses: gs.Session, kind: str, ref: str, cpu: str) -> Clearing:
    """A clear's declarations of `kind`: those `ref` names (every one with no ref), on every cpu
    or with `cpu` on that one alone; every declaration of the kind held there, and what `ref`
    names elsewhere (on another cpu, or an expression watch, which is on none), which a refusal
    names. `ref` is read ONCE by the address rule (`inputs.classify`, against the tables of
    the cpus cleared and the names rows of the kind are stored under on any cpu) and reaches
    only rows of its own kind, compared under `dec.match_key` (`dec.REF_MATCH` says it in
    the client's words); an expression or a pointer ref is compared as its row was declared, and a
    registerpoint's ref is an expression. An expression watch's text is one of those names: a
    register such as `d0` is hex, and no address."""
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
    """The one sentence for a `ref` that matched nothing a call could act on: what was not done,
    and what is held where it looked (`there`), so the caller can pick the ref it meant."""
    return (f"{ref!r} matches no {what}{there}, so nothing was {done}. The {what}s held{there}: "
            f"{', '.join(held) or 'none at all'}.")


def refuse_unmatched_clear(ref: str, family: str, c: Clearing) -> dict[str, Any]:
    """A clear that reached nothing: what is held where it looked, and where `ref` names a
    declaration it did not look."""
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
    # ONE LITERAL PER FAMILY, each naming its own list backticked: the scan of
    # `test_every_refusal_of_the_three_families_names_the_call_that_resolves_it` reads a
    # refusal's literal, and an interpolated `{family}_list` would name no tool there.
    if family == "breakpoint":
        return menvelope.invalid("unknown_ref",
                                 f"{lead}`breakpoint_list` shows as `ref`. {matching}")
    if family == "watch":
        return menvelope.invalid("unknown_ref", f"{lead}`watch_list` shows as `ref`. {matching}")
    return menvelope.invalid("unknown_ref", f"{lead}`regpoint_list` shows as `ref`. {matching}")


#: A row a clear is taking down: whose declaration it is, its entry as the list printed it, and
#: its index.
Going = tuple[dec.Owner, str, int]


def disarm_rows(ses: gs.Session, kind: str, rows: list[Going],
                listed: Callable[[], list[dict[str, Any]]]
                ) -> tuple[list[Going], list[tuple[str, int]]]:
    """THE ONE REMOVAL EVERY FAMILY SHARES: each row's removal sent by its INDEX, whoever
    placed it and whichever cpu it is under, then the debugger's list read back ONCE, so
    `disarmed` is the machine's answer and never the tool's claim. Returns the rows the list no
    longer shows, and each row it still shows as `still_held_note` names it; what a row's
    record is, and when it goes, stays the family's."""
    if not rows:
        return [], []
    for _owner, _entry, index in rows:
        ses.monitor(clear_command(kind, index))
    after = listed()
    gone = [row for row in rows if mlists.row_at_index(after, row[2]) is None]
    return gone, [(entry, index) for _owner, entry, index in rows if (_owner, entry, index)
                  not in gone]


def still_held_note(kind: str, rows: list[tuple[str, int]]) -> str:
    """What a clear says of the rows the debugger still lists after their removal was
    sent: each entry as the list prints it, and the console command that removes it
    (`pasted_clear`), so it can be typed as it stands. The record stays with the row
    meanwhile, or the next stop there would read as foreign."""
    named = "address" if kind == "breakpoint" else "ref"
    commands = ", ".join(pasted_clear(kind, index) for _entry, index in rows)
    return (f"the debugger still lists {[entry for entry, _index in rows]} after the removal "
            f"was sent, so the record is kept and a stop there is still named by its {named}; "
            f"{commands} {'removes the row' if len(rows) == 1 else 'remove the rows'}")


def forget_rows_gone(ses: gs.Session, kind: str) -> list[dec.Owner]:
    """After a `bpclear` or a `wpclear` typed through `debug` (`kind` is `breakpoint` or
    `watch`; an `rpclear` is `mame_regpoints.forget_gone`): every record this server kept for
    a row the debugger's list no longer shows goes with the row, whether or not a declaration
    still names it (its list says `gone` either way), so nothing here believes a stop can land
    where nothing is armed and a row typed there later is named as the foreign row it is. The
    owners forgotten."""
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
    """One spelling for a debugger row's index in every sentence of every family: as
    the console's own lists print it (hex, upper case), so a row named here is the row the
    list shows. A COMMAND that takes the index is `clear_command`, which prefixes it."""
    return f"{index:X}"


def foreign_row_how(kind: str, index: int, detail: str) -> str:
    """How a stop by a row this server did not place is named, in every family: the
    family's word, the index as `row_index` spells it, what the caller gave as `detail`,
    and the sentence ENDS by naming the console command that removes the row
    (`pasted_clear`), so nothing has to be translated to act on it."""
    return f"{kind} {row_index(index)}{detail}: {pasted_clear(kind, index)} removes it"
