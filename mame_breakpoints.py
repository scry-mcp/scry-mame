"""THE BREAKPOINT FAMILY: `breakpoint_at` stores and arms a stop breakpoint or a counting
control (never a second row on one the debugger already lists), `breakpoint_list` reads the
debugger's own `bplist` back, `breakpoint_clear` removes what this server armed and reads the
list back, and `breakpoint_name` names a stop by the declaration it is at. What every family
shares is `mame_arming`'s (the store), `mame_lists`' (the debugger's lists read back, a row's
adoption), `mame_conditions`' (a condition as the console reads it) and `mame_clear`'s."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from scry_core import value_format as vf
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable

import gdb_session as gs
import mame_arming as arming
import mame_clear as mclear
import mame_conditions as conditions
import mame_console as console
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_inputs as inputs
import mame_lexer as lexer
import mame_lists as mlists
import mame_read as read
import mame_state as st
from mame_state import STATE

# The `by` a breakpoint can be declared under, which `breakpoint_at` publishes and judges: no
# `expr` or `pointer` for a place in the code.
BREAKPOINT_BY = ("auto", "symbol", "address")
_CONTROL_CONDITION = re.compile(r"^\(\+\+temp(\d)\)==0$")
# The console's line at EVERY breakpoint stop, this server's rows and anybody else's alike
# (`Stopped at breakpoint 1`, captured): only the row's index says whose it was.
_BP_STOP_LINE = re.compile(r"Stopped at breakpoint ([0-9A-Fa-f]+)\b")


def bp_record(owner: dec.Owner) -> tuple[int, dict[str, Any]] | None:
    """The row `owner` holds, as `(index, record)`, or None."""
    return next(((i, r) for i, r in STATE.breakpoints.items() if r["owner"] == owner), None)


def _owned_row(held: list[dict[str, Any]], owner: dec.Owner,
               addr: int) -> dict[str, Any] | None:
    """The listed row `owner` already holds at `addr`, or None."""
    own = bp_record(owner)
    row = mlists.row_at_index(held, own[0]) if own is not None else None
    return row if row is not None and row["addr"] == addr else None


def bp_owned_at(addr: int, cpu: str | None,
                but: frozenset[dec.Owner] = frozenset()) -> dec.Owner | None:
    """The owner whose row sits at `addr` on `cpu`, or None: what a stop at a pc is named by,
    the owners in `but` passed over. A cpu nobody could read (a console that listed none) on
    either side falls back to the address, as a row's adoption does."""
    return next((r["owner"] for r in STATE.breakpoints.values()
                 if r["addr"] == addr and r["owner"] not in but
                 and (cpu is None or r["cpu"] is None or r["cpu"] == cpu)), None)


def breakpoint_name(pc: int, cpu: str | None) -> str | None:
    """The declaration a stop at `pc` is at, for the stop's `cause`: by its name when one was
    declared by a name there, by the bare address when only by address, each with the
    clause that says a declaration was inherited. Every declaration at the address is
    looked at: an address declared first must not hide a name declared after, and among
    addresses the one that owns the armed row speaks for the stop (a store from before the
    one-row rule can hold a second, aliased one there)."""
    owner = bp_owned_at(pc, cpu)
    if STATE.store is None or owner is None:
        return None
    bare: str | None = None
    for decl in STATE.store.declarations():
        if (decl.kind != "breakpoint" or decl.cpu != owner[1]
                or arming.resolve_decl(decl).addr != pc):
            continue
        if decl.by == "symbol":
            return f"breakpoint {decl.ref} at {pc:#x}{arming.inherited(decl)}"
        if bare is None or decl.owner == owner:
            bare = f"breakpoint at {pc:#x}{arming.inherited(decl)}"
    return bare


def bp_aliased(owner: dec.Owner, addr: int, among: list[dec.Declaration],
               pass_note: str = "", clear_tool: mclear.ClearTool | None = "breakpoint_clear"
               ) -> str | None:
    """The refusal when ANOTHER breakpoint declaration on the same cpu already resolves to
    `addr`: one row is one declaration, or clearing either would remove the row and leave the
    other declared over a row the debugger no longer has. The watch family's `watch_aliased`, for
    breakpoints. `start`'s re-arm passes no `clear_tool`: its report names no call to make."""
    other = next((d.ref for d in among if d.kind == "breakpoint" and d.cpu == owner[1]
                  and d.owner != owner and arming.resolve_decl(d).addr == addr), None)
    if other is None:
        return None
    return (f"{addr:#x} is already declared under {other!r}{pass_note}: "
            f"{mclear.one_declaration('breakpoint row', other, clear_tool, owner[1])}")


def bp_command(addr: int, condition: str, cpu: str | None = None) -> str:
    """The console command that arms a breakpoint on `cpu`. The one builder, so the check that
    it fits the stub's packet (`Session.console_packet`) judges the text that is sent."""
    return f"bp {addr:#x}{console.cpu_suffix(cpu)}" + (f",{condition}" if condition else "")


def _row_to_adopt(held: list[dict[str, Any]], owner: dec.Owner, addr: int) -> dict[str, Any] | None:
    """The row of the debugger's list (`held`) a declaration at `addr` takes over rather than
    stacking a second breakpoint: the one `owner` holds, else one nobody holds there on its cpu."""
    return (_owned_row(held, owner, addr)
            or mlists.adoptable_row(held, addr, owner[1], set(STATE.breakpoints)))


def stop_row(held: list[dict[str, Any]], owner: dec.Owner, addr: int, condition: str
             ) -> tuple[dict[str, Any] | None, st.Invalid | None]:
    """The row a STOP at `addr` adopts (None when it needs a new one), or the refusal when the row
    there stops under a condition that is not `condition`. It sends nothing and raises nothing,
    so a declaration and `start`'s re-arm judge a row by one rule and each decides what a refusal
    does: the declaration raises it, the re-arm lists it and goes on with the rest."""
    row = _row_to_adopt(held, owner, addr)
    if row is not None and (row.get("condition") or "") != condition:
        return None, mclear.another_condition("breakpoint", addr, row, condition)
    return row, None


def _stop_row_or_refuse(held: list[dict[str, Any]], owner: dec.Owner, addr: int,
                        condition: str) -> dict[str, Any] | None:
    """`stop_row`, raising its refusal: what `breakpoint_at` does with one."""
    row, refused = stop_row(held, owner, addr, condition)
    if refused is not None:
        raise refused
    return row


def _arm_breakpoint(ses: gs.Session, owner: dec.Owner, addr: int, held: list[dict[str, Any]],
                    condition: str) -> dict[str, Any] | None:
    """`bp addr:cpu[,condition]` on the owner's cpu, unless the debugger's list (`held`, read by
    the caller) already holds a row `stop_row` adopts: a re-declaration must not stack a second
    breakpoint. The row, read back, or None when the list does not show one; who OWNS it is the
    caller's to record. Refused as `stop_row` refuses."""
    row = _stop_row_or_refuse(held, owner, addr, condition)
    if row is not None:
        return row
    ses.monitor(bp_command(addr, condition, owner[1]))
    return mlists.armed_row(held, mlists.bp_held(ses), addr, cpu=owner[1])


def own_row(row: dict[str, Any], owner: dec.Owner) -> None:
    """`owner` holds the row numbered `row["index"]` from here on, and no other; a condition
    this start could not resolve is no longer the reason it has none."""
    for index in [i for i, r in STATE.breakpoints.items() if r["owner"] == owner]:
        STATE.breakpoints.pop(index)
    STATE.breakpoints[row["index"]] = {"owner": owner, "addr": row["addr"], "cpu": row["cpu"]}
    STATE.conditions_unresolved.discard(("breakpoint", owner))


def _aliased_why(owner: str) -> str:
    return (f"another declaration, {owner!r}, owns the row at this address: one breakpoint row "
            "is one declaration, so this one arms nothing and clearing it disarms nothing")


# ------------------------------------------------------------------------------ controls


def _temp_for(owner: dec.Owner) -> int:
    """The temp `owner`'s own record holds, when the control is declared again over its own
    lost row; else the first of the debugger's temp variables no control holds, or the refusal
    when all ten are taken. One temp per control: its condition `(++tempN)==0` counts every hit
    and never comes true, so the machine is never halted and the count is `print tempN`."""
    if owner in STATE.controls:
        return int(STATE.controls[owner]["temp"])
    taken = {c["temp"] for c in STATE.controls.values()}
    free = next((i for i in range(lexer.TEMPS) if i not in taken), None)
    if free is None:
        raise st.Invalid("bad_argument",
                         f"the debugger has ten temp variables (temp0..temp{lexer.TEMPS - 1}) and "
                         "every one is held by a control (`breakpoint_list` names them): "
                         "`breakpoint_clear(ref=...)` frees one before declaring "
                         "another")
    return free


def _control_row(held: list[dict[str, Any]], owner: dec.Owner,
                 addr: int) -> tuple[dict[str, Any] | None, int]:
    """The row a CONTROL at `addr` adopts with the temp its condition names, or None and the
    free temp a new one takes; the refusal when the row there is not a counting control
    (adopting it would count nothing) or no temp is free. It sends nothing."""
    row = _row_to_adopt(held, owner, addr)
    if row is None:
        return None, _temp_for(owner)
    m = _CONTROL_CONDITION.match(row.get("condition") or "")
    if m is None:
        raise st.Invalid("ambiguous_ref",
                         f"the debugger already holds a row at {addr:#x} that is not a "
                         f"counting control ({row['entry']}): clear it through `debug` "
                         "or declare the control elsewhere")
    return row, int(m.group(1))


def arm_control(ses: gs.Session, owner: dec.Owner, addr: int,
                held: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Arm `owner` as a CONTROL at `addr` on its cpu: a console breakpoint whose condition
    counts and never halts, unless the list (`held`, read by the caller) already shows such a
    row there, which is adopted. The row read back, or None when the console listed nothing;
    refused as `_control_row` refuses. The counter is zeroed first: a temp freed by an earlier
    control still holds its count."""
    cpu = owner[1]
    row, temp = _control_row(held, owner, addr)
    # An adopted row keeps counting in its temp, and keeps what its landings cost it.
    missed = STATE.controls.get(owner, {}).get("missed", 0) if row is not None else 0
    if row is None:
        ses.monitor(f"temp{temp} = 0")
        ses.monitor(bp_command(addr, f"(++temp{temp})==0", cpu))
        row = mlists.armed_row(held, mlists.bp_held(ses), addr, cpu=cpu)
        if row is None:
            return None
    STATE.controls[owner] = {"addr": addr, "temp": temp, "index": row["index"], "missed": missed}
    own_row(row, owner)
    return row


def control_at(owner: dec.Owner) -> tuple[int, str | None]:
    """Where the control under `owner` is armed: its address and the cpu of its row. The one
    reading of a control's record outside this module."""
    record = STATE.controls[owner]
    return record["addr"], STATE.breakpoints.get(record["index"], {}).get("cpu")


def count_landing(pc: int, cpu: str | None) -> None:
    """One hit for every control at `pc` on `cpu`, the instruction a frame stop landed on, which
    the next release executes with its breakpoints never evaluated: MAME's instruction hook skips
    them while the debugger is stopped, and a `gvblank` stop takes effect at the hook of the
    instruction it lands on."""
    for owner, rec in STATE.controls.items():
        at, on = control_at(owner)
        if at == pc and cpus.same_cpu(on, cpu):
            rec["missed"] += 1


def control_counts(ses: gs.Session) -> dict[dec.Owner, int]:
    """Every control's count, by owner: its temp, read in ONE `print` (`read.print_values`), plus
    the hits frame stops' landings cost it (`count_landing`). Empty with no control armed. Raises
    what that raises: `ExpressionRefused` for a temp the console refuses, an answer about the
    machine; `SessionError` for one that is not a number per control."""
    if not STATE.controls:
        return {}
    refs = list(STATE.controls)
    values = read.print_values(ses, [f"temp{STATE.controls[r]['temp']}" for r in refs])
    return {r: v + STATE.controls[r]["missed"] for r, v in zip(refs, values, strict=True)}


def check_breakpoint_at(ref: str, by: str = "auto", role: str = "stop",
                        condition: str = "", **_: Any) -> None:
    """`breakpoint_at`'s machine-independent half: the two vocabularies and the condition's shape.

    The declaration's own rules (a `control` carries no condition, a `by="address"` names a `0x`
    address) are `Declaration`'s and are asked of it rather than restated here.
    """
    inputs.check_ref(ref) if vf.parse_pointer(ref) is None else None
    vocab.one_of("role", role, dec.ROLES)
    vocab.one_of("by", by, BREAKPOINT_BY)     # its own words: a refusal lists none it refuses
    if condition.strip():
        conditions.check_condition(condition)
    # `Declaration` validates itself in `__post_init__`, so CONSTRUCTING one is the whole of asking,
    # and it is asked with the CALLER's `by`: a declaration by address has a rule about the ref's
    # shape that a placeholder would not trigger. `auto` is decided from the symbol table, which is
    # the machine's -- except a POINTER, which its grammar decides, and a breakpoint on one is
    # refused whatever the table says, and a `0x` ref, which the address rule decides with no table.
    if by != "auto":
        decided = by
    elif vf.parse_pointer(ref) is not None:
        decided = "pointer"
    else:
        decided = "address" if inputs.is_address(ref) else "symbol"
    try:
        dec.Declaration(kind="breakpoint", by=decided, ref=ref,
                        role=role, condition=condition.strip())
    except dec.DeclarationError as e:
        raise st.Invalid("bad_argument", str(e)) from None


def breakpoint_at(ses: gs.Session, ref: str, by: str, role: str = "stop",
                  condition: str = "", cpu: str = "") -> dict[str, Any]:
    """The body of the `breakpoint_at` tool."""
    running = arming.running_on_arrival(ses)
    check_breakpoint_at(ref, by, role, condition)
    # THE DECLARATION'S CPU is the one the call names, else the visible one, read now: the
    # same ref on another cpu is another declaration.
    on = cpus.chosen(ses, cpu)
    # Stored as typed and substituted at each arming: a rebuild moves the symbols.
    typed = condition.strip()
    cond = conditions.console_condition(typed, on) if typed else ""
    ref = ref.strip()
    chosen = arming.decide_by(ref, by, on, "breakpoint")
    decl = arming.declare("breakpoint", chosen, ref, on, role=role, condition=typed)
    stored = arming.store().held_ref(ref, chosen, ("breakpoint",), on)
    if stored is not None and stored != ref:
        # AN ADDRESS DECLARED AGAIN IN ANOTHER SPELLING IS THE SAME DECLARATION, and
        # it is handled under its stored spelling, the string a clear takes.
        ref, decl = stored, dataclasses.replace(decl, ref=stored)
    # A ROW STORED WITH THE ADDRESS ALREADY IN PLACE, declared again by name, is the same
    # declaration. Its text is replaced where a new one would be added: past every refusal.
    earlier = dataclasses.replace(decl, condition=cond)
    migrates = typed != cond and arming.store().index_of(earlier) is not None
    if not migrates:
        arming.refuse_conflict(decl)
    res = arming.resolve_decl(decl)
    held: list[dict[str, Any]] = []
    if res.addr is not None:
        why = bp_aliased(decl.owner, res.addr, arming.store().declarations())
        if why is not None:
            raise st.Invalid("ambiguous_ref", why)
        if cond:
            # A COMMAND THE STUB WOULD DROP is refused before the declaration is stored,
            # so the refusal leaves nothing behind: `CommandTooLong` is `bad_argument`.
            judged = conditions.judged_condition(ses, bp_command(res.addr, cond, on), cond, on)
            conditions.refuse_if_left_visible(judged, cond, on)
            if (refusal := judged.refusal) is not None:
                raise st.Invalid("bad_argument", f"the debugger did not evaluate `{cond}`, and "
                                                 "a breakpoint it cannot evaluate never stops: "
                                                 f"{refusal}. `symbols_find(name=...)` checks "
                                                 "a name; `breakpoint_at` again once it reads")
        # THE ARMING'S OWN TWO REFUSALS (the row there, a free temp) are judged here too, before
        # anything is stored: a declaration refused after the store took it would be listed
        # `gone` and re-armed at the next `start` as if it had been accepted. The list read
        # here is the one the arming below compares its row against.
        held = mlists.bp_held(ses)
        if role == "control":
            _control_row(held, decl.owner, res.addr)
        else:
            _stop_row_or_refuse(held, decl.owner, res.addr, cond)
    if migrates:
        arming.store().replace(earlier, decl)
    is_new = arming.store().add(decl)
    reply: dict[str, Any] = {"ref": ref, "by": chosen, "role": role,
                             "cpu": or_unavailable(on, st.NO_CPU_READ_WHY),
                             "stored": True, "already_stored": not is_new,
                             "while_running": running}
    if cond:
        conditions.condition_fields(reply, typed, cond)
    if res.state == "unresolved":
        return menvelope.envelope({**reply, "armed": False, "state": "unresolved",
                                   "note": f"{ref} is not a symbol in this build; the declaration "
                                   "is kept and arms nothing until a build defines it"})
    addr = res.addr
    assert addr is not None
    if role == "control":
        row = arm_control(ses, decl.owner, addr, held)
        if row is None:
            return menvelope.invalid("readback_refused",
                                     f"the console took a `bp` at {addr:#x} and its `bplist` does "
                                     "not list it: nothing is armed; `breakpoint_list` shows the "
                                     "declaration kept and `breakpoint_clear(ref=...)` removes it",
                                     ref=ref, addr=st.hex_addr(addr),
                                     **mclear.kept_fields("breakpoint_clear", ref))
        return menvelope.envelope(st.add_note(
            {**reply, "addr": st.hex_addr(addr), "armed": row["enabled"],
             "state": mlists.row_state(row), "entry": row["entry"], "cpu": row["cpu"],
             "temp": f"temp{STATE.controls[decl.owner]['temp']}"},
            cpus.ignored_note(ses, row["cpu"])))
    row = _arm_breakpoint(ses, decl.owner, addr, held, cond)
    if not mlists.listed_as_sent(row, cond):
        unlisted = mlists.not_listed(f"`{bp_command(addr, cond, on)}`", "bplist", bool(cond))
        return menvelope.invalid("readback_refused",
                                 f"{unlisted}; `breakpoint_list` shows the declaration kept and "
                                 "`breakpoint_clear(ref=...)` removes it",
                                 ref=ref, addr=st.hex_addr(addr),
                                 **mclear.kept_fields("breakpoint_clear", ref))
    assert row is not None
    own_row(row, decl.owner)
    return menvelope.envelope(st.add_note(
        {**reply, "addr": st.hex_addr(addr), "armed": row["enabled"],
         "state": mlists.row_state(row), "entry": row["entry"], "cpu": row["cpu"]},
        cpus.ignored_note(ses, row["cpu"])))


def breakpoint_list(ses: gs.Session, cpu: str = "") -> dict[str, Any]:
    """The body of the `breakpoint_list` tool: every declaration, or with `cpu` the ones whose
    row the debugger lists under it, read off `bplist <cpu>`."""
    only = cpus.named(ses, cpu) if inputs.cpu_given(cpu) else None
    held = mlists.bp_held(ses, only)
    counts = control_counts(ses)
    out: list[dict[str, Any]] = []
    mine: set[int] = set()          # the indices of the rows this server's declarations own
    for decl in arming.store().declarations():
        if decl.kind != "breakpoint":
            continue
        item = arming.decl_row(decl)
        item["role"] = decl.role
        if decl.condition:
            conditions.typed_condition(item, decl)
        res = arming.resolve_decl(decl)
        if res.state == "unresolved" or res.addr is None:
            item["state"] = "unresolved"
        else:
            item["addr"] = st.hex_addr(res.addr)
            own = bp_record(decl.owner)
            row = mlists.row_at_index(held, own[0]) if own is not None else None
            owner = next((r["owner"][0] for i, r in STATE.breakpoints.items()
                          if r["addr"] == res.addr and r["owner"][1] == decl.cpu
                          and mlists.row_at_index(held, i) is not None), None)
            if row is not None:
                item["state"], item["entry"] = mlists.row_state(row), row["entry"]
                item["cpu"] = row["cpu"]
                if decl.owner in counts:
                    item["hits_since_armed"] = counts[decl.owner]
                mine.add(row["index"])
            elif owner is not None:
                # A store from before the one-row rule: the row is another declaration's,
                # and calling this one `armed` contradicted the re-arm's own account.
                item["state"], item["why"] = "aliased", _aliased_why(owner)
            elif ("breakpoint", decl.owner) in STATE.conditions_unresolved:
                item["state"] = "unresolved"       # the ref resolved; its condition did not
            elif arming.stale(decl):
                item["state"], item["why"] = "stale", arming.stale_why()
            else:
                item["state"] = "gone"
        if only is None or item.get("cpu") == only:
            out.append(item)
    reply: dict[str, Any] = {
        "breakpoints": out,
        "foreign": [r["entry"] for r in held if r["index"] not in mine],
    }
    reply["cpu"] = or_unavailable(only, st.NO_CPU_NAMED_WHY)   # every list tool carries it
    if ses.running:
        reply["last_stop"] = STATE.as_of()
    return menvelope.envelope(reply)


def check_breakpoint_clear(ref: str = "", all: bool = False, **_: Any) -> None:
    """`breakpoint_clear`'s machine-independent half: one `ref` or `all=True`, and a `ref` judged
    as every breakpoint's is."""
    mclear.check_clear(ref, all, "breakpoint")
    if ref.strip():
        inputs.check_ref(ref)


def breakpoint_clear(ses: gs.Session, ref: str, cpu: str = "", all_: bool = False
                     ) -> dict[str, Any]:
    """The body of the `breakpoint_clear` tool: `ref`'s declarations (every one with no ref),
    on every cpu or on `cpu` alone."""
    check_breakpoint_clear(ref=ref, all=all_)
    ref = "" if all_ else ref
    running = arming.running_on_arrival(ses)
    reached = mclear.clearing(ses, "breakpoint", ref, cpu)
    going_decls = reached.going
    if ref.strip() and not going_decls:
        return mclear.refuse_unmatched_clear(ref, "breakpoint", reached)
    going: list[mclear.Going] = []
    held = mlists.bp_held(ses)
    for decl in going_decls:
        # ONLY THE OWNER'S ROW IS REMOVED: a second declaration on the same address (an old
        # store) owns no row, and a removal sent for it would find none.
        own = bp_record(decl.owner)
        if own is None:
            continue
        index = own[0]
        row = mlists.row_at_index(held, index)
        if row is None:
            # The debugger does not hold it any more (`gone`): nothing to disarm, and
            # claiming it would make `disarmed` this tool's word instead of the list's.
            STATE.breakpoints.pop(index, None)
            STATE.controls.pop(decl.owner, None)
            continue
        going.append((decl.owner, row["entry"], index))
    gone, still_held = mclear.disarm_rows(ses, "breakpoint", going, lambda: mlists.bp_held(ses))
    for cleared, _entry, index in gone:
        STATE.breakpoints.pop(index, None)
        STATE.controls.pop(cleared, None)
    disarmed = [entry for _owner, entry, _index in gone]
    STATE.conditions_unresolved -= {("breakpoint", d.owner) for d in going_decls}
    removed = arming.store().discard(going_decls)
    reply: dict[str, Any] = {"declarations_cleared": removed, "disarmed": disarmed,
                             "while_running": running}
    if still_held:
        reply["note"] = mclear.still_held_note("breakpoint", still_held)
    return menvelope.envelope(reply)


def foreign_breakpoint(ses: gs.Session, since: list[str], pc: int) -> str | None:
    """How a stop is named when the console's newest `Stopped at breakpoint <n>` in `since`
    is a row this server did not arm (typed through `debug`), or None. The caller has
    already given a row this server armed at `pc` its precedence. A row the debugger no
    longer lists is none of anybody's now (a tool's own, removed before the survey), and
    one whose address this server armed is its own. A list the console will not answer
    cannot say whose the row is: the stop is still named, since resuming through it would
    lose a stop somebody asked for."""
    stops = [m for ln in since if (m := _BP_STOP_LINE.search(ln)) is not None]
    if not stops:
        return None
    index = int(stops[-1].group(1), 16)
    try:
        row = next((r for r in mlists.bp_held(ses) if r["index"] == index), None)
    except (gs.SessionError, st.Invalid) as e:
        return (f"breakpoint {mclear.row_index(index)} at {st.hex_addr(pc)}; the debugger's "
                f"list could not be read to say whose: {e}")
    if row is None or index in STATE.breakpoints:
        return None
    return mclear.foreign_row_cause("breakpoint", index,
                                    f" at {st.hex_addr(pc)}, typed through `debug`")
