"""The breakpoint family: `breakpoint_at`, the breakpoint declaration list and clear, and the
stop names."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from scry_core import declaration_rows
from scry_core import value_format as vf
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable

from scry_mame import arming, conditions, console, cpus, inputs, lexer, read
from scry_mame import clear as mclear
from scry_mame import declarations as dec
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import lists as mlists
from scry_mame import state as st
from scry_mame.state import STATE

BREAKPOINT_BY = ("auto", "symbol", "address")
_CONTROL_CONDITION = re.compile(r"^\(\+\+temp(\d)\)==0$")
# Printed at every breakpoint stop, anybody's: only the row's index says whose it was.
_BP_STOP_LINE = re.compile(r"Stopped at breakpoint ([0-9A-Fa-f]+)\b")


def bp_record(owner: dec.Owner) -> tuple[int, dict[str, Any]] | None:
    """The row `owner` holds, as `(index, record)`, or None."""
    return next(((i, r) for i, r in STATE.breakpoints.items() if r["owner"] == owner), None)


def _owned_row(held: list[dict[str, Any]], owner: dec.Owner,
               addr: int) -> dict[str, Any] | None:
    """The listed row `owner` holds at `addr`, or None."""
    own = bp_record(owner)
    row = mlists.row_at_index(held, own[0]) if own is not None else None
    return row if row is not None and row["addr"] == addr else None


def bp_owned_at(addr: int, cpu: str | None,
                but: frozenset[dec.Owner] = frozenset()) -> dec.Owner | None:
    """The owner whose row sits at `addr` on `cpu`, or None, passing over `but`. An unread cpu
    on either side falls back to the address, as a row's adoption does."""
    return next((r["owner"] for r in STATE.breakpoints.values()
                 if r["addr"] == addr and r["owner"] not in but
                 and (cpu is None or r["cpu"] is None or r["cpu"] == cpu)), None)


def breakpoint_name(pc: int, cpu: str | None) -> str | None:
    """The declaration a stop at `pc` is at, for the stop's `cause`: named when declared by name,
    else by address. An address declared first must not hide a name declared after; among
    addresses the armed row's owner speaks (an old store can hold an aliased second)."""
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
               pass_note: str = "", clear_kind: mclear.ClearKind | None = "breakpoint"
               ) -> str | None:
    """The refusal when ANOTHER breakpoint declaration on the cpu resolves to `addr`: clearing
    either would leave the other over a row the debugger no longer has. `start`'s re-arm passes
    no `clear_kind`: its report names no call to make."""
    other = next((d.ref for d in among if d.kind == "breakpoint" and d.cpu == owner[1]
                  and d.owner != owner and arming.resolve_decl(d).addr == addr), None)
    if other is None:
        return None
    return (f"{addr:#x} is already declared under {other!r}{pass_note}: "
            f"{mclear.one_declaration('breakpoint row', other, clear_kind, owner[1])}")


def bp_command(addr: int, condition: str, cpu: str | None = None) -> str:
    """The console command that arming sends, built once so the packet-fit check judges it."""
    return f"bp {addr:#x}{console.cpu_suffix(cpu)}" + (f",{condition}" if condition else "")


def _row_to_adopt(held: list[dict[str, Any]], owner: dec.Owner, addr: int) -> dict[str, Any] | None:
    """The row of `held` a declaration at `addr` takes over: `owner`'s, else one nobody holds."""
    return (_owned_row(held, owner, addr)
            or mlists.adoptable_row(held, addr, owner[1], set(STATE.breakpoints)))


def stop_row(held: list[dict[str, Any]], owner: dec.Owner, addr: int, condition: str
             ) -> tuple[dict[str, Any] | None, st.Invalid | None]:
    """The row a STOP at `addr` adopts (None when it needs a new one), or the refusal when that
    row stops under another condition. Sends and raises nothing: the declaration raises the
    refusal, `start`'s re-arm lists it."""
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
    """`bp` on the owner's cpu unless `held` has a row `stop_row` adopts, so a re-declaration
    stacks nothing. The row read back, or None; recording its owner is the caller's."""
    row = _stop_row_or_refuse(held, owner, addr, condition)
    if row is not None:
        return row
    ses.monitor(bp_command(addr, condition, owner[1]))
    return mlists.armed_row(held, mlists.bp_held(ses), addr, cpu=owner[1])


def own_row(row: dict[str, Any], owner: dec.Owner) -> None:
    """`owner` holds the row `row["index"]` and no other."""
    for index in [i for i, r in STATE.breakpoints.items() if r["owner"] == owner]:
        STATE.breakpoints.pop(index)
    STATE.breakpoints[row["index"]] = {"owner": owner, "addr": row["addr"], "cpu": row["cpu"]}
    STATE.conditions_unresolved.discard(("breakpoint", owner))


def _aliased_why(owner: str) -> str:
    return (f"another declaration, {owner!r}, owns the row at this address: one breakpoint row "
            "is one declaration, so this one arms nothing and clearing it disarms nothing")


def _temp_for(owner: dec.Owner) -> int:
    """The temp `owner` holds, else the first free one, or the refusal when all ten are taken.
    A control's `(++tempN)==0` counts every hit and never comes true: the count is `print tempN`."""
    if owner in STATE.controls:
        return int(STATE.controls[owner]["temp"])
    taken = {c["temp"] for c in STATE.controls.values()}
    free = next((i for i in range(lexer.TEMPS) if i not in taken), None)
    if free is None:
        raise st.Invalid("bad_argument",
                         f"the debugger has ten temp variables (temp0..temp{lexer.TEMPS - 1}) and "
                         "every one is held by a control (`declaration_list(kind=\"breakpoint\")` "
                         "names them): "
                         "`declaration_clear(kind=\"breakpoint\", ref=...)` frees one before "
                         "declaring "
                         "another")
    return free


def _control_row(held: list[dict[str, Any]], owner: dec.Owner,
                 addr: int) -> tuple[dict[str, Any] | None, int]:
    """The row a CONTROL at `addr` adopts with its temp, or None and the free temp; refused when
    the row there is no counting control or no temp is free. Sends nothing."""
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
    """Arm `owner` as a CONTROL at `addr`, adopting such a row in `held`. The row read back, or
    None. The counter is zeroed first: a freed temp still holds its count."""
    cpu = owner[1]
    row, temp = _control_row(held, owner, addr)
    if row is None:
        ses.monitor(f"temp{temp} = 0")
        ses.monitor(bp_command(addr, f"(++temp{temp})==0", cpu))
        row = mlists.armed_row(held, mlists.bp_held(ses), addr, cpu=cpu)
        if row is None:
            return None
    STATE.controls[owner] = {"addr": addr, "temp": temp, "index": row["index"]}
    own_row(row, owner)
    return row


def control_at(owner: dec.Owner) -> tuple[int, str | None]:
    """Where the control under `owner` is armed: its address and the cpu of its row."""
    record = STATE.controls[owner]
    return record["addr"], STATE.breakpoints.get(record["index"], {}).get("cpu")


def control_counts(ses: gs.Session) -> dict[dec.Owner, int]:
    """Every control's count by owner: its temp.
    Raises `ExpressionRefused` for a temp the console refuses, `SessionError` for a reply that
    is not a number per control."""
    if not STATE.controls:
        return {}
    refs = list(STATE.controls)
    values = read.print_values(ses, [f"temp{STATE.controls[r]['temp']}" for r in refs])
    return dict(zip(refs, values, strict=True))


def check_breakpoint_at(ref: str, by: str = "auto", role: str = "stop",
                        condition: str = "", **_: Any) -> None:
    """`breakpoint_at`'s machine-independent half: the vocabularies and the condition's shape."""
    inputs.check_ref(ref) if vf.parse_pointer(ref) is None else None
    vocab.one_of("role", role, dec.ROLES)
    vocab.one_of("by", by, BREAKPOINT_BY)
    if condition.strip():
        conditions.check_condition(condition)
    # Constructing a Declaration validates it, with the caller's `by`. `auto` needs the symbol
    # table (the machine's) except for a pointer or a `0x` ref, which their grammar decides.
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
    """The body of `breakpoint_at`."""
    running = arming.running_on_arrival(ses)
    check_breakpoint_at(ref, by, role, condition)
    on = cpus.chosen(ses, cpu)
    # Stored as typed, substituted at each arming: a rebuild moves the symbols.
    typed = condition.strip()
    cond = conditions.console_condition(typed, on) if typed else ""
    ref = ref.strip()
    chosen = arming.decide_by(ref, by, on, "breakpoint")
    decl = arming.declare("breakpoint", chosen, ref, on, role=role, condition=typed)
    stored = arming.store().held_ref(ref, chosen, ("breakpoint",), on)
    if stored is not None and stored != ref:
        # Another spelling of a declared address is the same declaration, under its stored one.
        ref, decl = stored, dataclasses.replace(decl, ref=stored)
    # A row stored with the address in place, declared again by name, is replaced, not added.
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
            # Refused before the store, so a command the stub would drop leaves nothing behind.
            judged = conditions.judged_condition(ses, bp_command(res.addr, cond, on), cond, on)
            conditions.refuse_if_left_visible(judged, cond, on)
            if (refusal := judged.refusal) is not None:
                raise st.Invalid("bad_argument", f"the debugger did not evaluate `{cond}`, and "
                                                 "a breakpoint it cannot evaluate never stops: "
                                                 f"{refusal}. `symbols_find(name=...)` checks "
                                                 "a name; `breakpoint_at` again once it reads")
        # The arming's own refusals are judged before the store: one refused after it would be
        # listed `gone` and re-armed at the next `start`. `held` is what the arming compares.
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
                                     "not list it: nothing is armed; "
                                     "`declaration_list(kind=\"breakpoint\")` shows the "
                                     "declaration kept and `declaration_clear(kind=\"breakpoint\", "
                                     "ref=...)` removes it",
                                     ref=ref, addr=st.hex_addr(addr),
                                     **mclear.kept_fields("breakpoint", ref))
        return menvelope.envelope(st.add_note(
            {**reply, "addr": st.hex_addr(addr), "armed": row["enabled"],
             "state": mlists.row_state(row), "entry": row["entry"], "cpu": row["cpu"],
             "temp": f"temp{STATE.controls[decl.owner]['temp']}"},
            cpus.ignored_note(ses, row["cpu"])))
    row = _arm_breakpoint(ses, decl.owner, addr, held, cond)
    if not mlists.listed_as_sent(row, cond):
        unlisted = mlists.not_listed(f"`{bp_command(addr, cond, on)}`", "bplist", bool(cond))
        return menvelope.invalid("readback_refused",
                                 f"{unlisted}; `declaration_list(kind=\"breakpoint\")` shows the "
                                 "declaration kept and "
                                 "`declaration_clear(kind=\"breakpoint\", ref=...)` removes it",
                                 ref=ref, addr=st.hex_addr(addr),
                                 **mclear.kept_fields("breakpoint", ref))
    assert row is not None
    own_row(row, decl.owner)
    return menvelope.envelope(st.add_note(
        {**reply, "addr": st.hex_addr(addr), "armed": row["enabled"],
         "state": mlists.row_state(row), "entry": row["entry"], "cpu": row["cpu"]},
        cpus.ignored_note(ses, row["cpu"])))


def list_breakpoints(ses: gs.Session, cpu: str = "") -> dict[str, Any]:
    """The body of `declaration_list(kind="breakpoint")`, optionally for one `cpu`."""
    only = cpus.named(ses, cpu) if inputs.cpu_given(cpu) else None
    held = mlists.bp_held(ses, only)
    counts = control_counts(ses)
    out: list[dict[str, Any]] = []
    mine: set[int] = set()
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
                # An old store: the row is another declaration's.
                item["state"], item["why"] = "aliased", _aliased_why(owner)
            elif ("breakpoint", decl.owner) in STATE.conditions_unresolved:
                item["state"] = "unresolved"       # the condition did not
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
    reply["cpu"] = or_unavailable(only, st.NO_CPU_NAMED_WHY)
    if ses.running:
        reply["last_stop"] = STATE.as_of()
    return menvelope.envelope(reply)


def check_clear_breakpoints(ref: str = "", all: bool = False, **_: Any) -> None:
    """`declaration_clear(kind="breakpoint")`'s machine-independent half."""
    declaration_rows.check_clear_scope(ref, all, "breakpoint")
    if ref.strip():
        inputs.check_ref(ref)


def clear_breakpoints(ses: gs.Session, ref: str, cpu: str = "", all_: bool = False
                     ) -> dict[str, Any]:
    """The body of `declaration_clear(kind="breakpoint")`."""
    check_clear_breakpoints(ref=ref, all=all_)
    ref = "" if all_ else ref
    running = arming.running_on_arrival(ses)
    reached = mclear.clearing(ses, "breakpoint", ref, cpu)
    going_decls = reached.going
    if ref.strip() and not going_decls:
        return mclear.refuse_unmatched_clear(ref, "breakpoint", reached)
    going: list[mclear.Going] = []
    held = mlists.bp_held(ses)
    for decl in going_decls:
        # Only the owner's row is removed: an old store's second declaration owns none.
        own = bp_record(decl.owner)
        if own is None:
            continue
        index = own[0]
        row = mlists.row_at_index(held, index)
        if row is None:
            # `gone`: nothing to disarm, and `disarmed` stays the list's word.
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
    """How a stop is named when the newest `Stopped at breakpoint <n>` in `since` is a row typed
    through `debug`, else None. The caller gave this server's own rows precedence. An unreadable
    list still names the stop: resuming through it would lose one somebody asked for."""
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
