"""REGISTERPOINTS: MAME's `rpset`, a stop when an expression over the registers comes true,
wherever in the program that happens.

The debugger evaluates a registerpoint's condition after EVERY instruction, so one that holds
keeps holding: a machine resumed with it still true stops again one instruction on. And like a
breakpoint typed at the console, the stop it makes under a run the console started (`gvblank`,
`gtime`) sends no packet: the only trace is the console's own `Stopped at registerpoint <n>`.
"""

from __future__ import annotations

import re
from typing import Any

import gdb_session as gs
import mame_arming as arming
import mame_clear as mclear
import mame_conditions as conditions
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_inputs as inputs
import mame_lists as mlists
import mame_state as st
from mame_state import STATE

# The console's shapes, CAPTURED live and held to in the tests: one `rplist` row per
# registerpoint (`    1 if d1==7fff`, a leading `D` when disabled, the index in hex and the
# newest row first), a header per device, the sentence for none, and the stop line.
_RPLIST_ROW = re.compile(
    r"^(D?)\s*([0-9A-Fa-f]+) if (?P<cond>.+?)(?: do (?P<act>.+?))?\s*$")
_RPLIST_STARTS = re.compile(r"^(?:[ D] *[0-9A-Fa-f]+ if |Device |No registerpoints )")
_RPLIST_HEADER = re.compile(r"^Device '(?P<cpu>[^']*)' registerpoints:$")
_RPLIST_NONE = re.compile(r"^No registerpoints currently installed(?: for CPU \S+)?$")
_RP_STOP_LINE = re.compile(r"Stopped at registerpoint ([0-9A-Fa-f]+)\b")
_RPSET_TAKEN = re.compile(r"^Registerpoint ([0-9A-Fa-f]+) set$")
# What `print {<condition>}` answers for a condition the debugger evaluates: one number.
STILL_ARMED = ("still armed: a registerpoint fires at every instruction while its condition "
               "holds, so the next advance stops here again; `regpoint_clear` removes it")


def parse_rplist(text: str) -> list[dict[str, Any]]:
    """The debugger's registerpoints as `rplist` lists them, each under the device whose
    header it sits below, or the refusal `mlists.list_rows` makes."""
    return [{"index": int(m.group(2), 16), "cpu": under["cpu"] or "",
             "enabled": m.group(1) != "D",
             "entry": f"{'D ' if m.group(1) == 'D' else ''}{m.group(2)} if {m.group('cond')}"
                      + (f" do {m.group('act')}" if m.group("act") else ""),
             "condition": m.group("cond"), "action": m.group("act")}
            for m, under in mlists.list_rows(text, "rplist", _RPLIST_ROW, starts=_RPLIST_STARTS,
                                             header=_RPLIST_HEADER, none=_RPLIST_NONE)]


def rp_held(ses: gs.Session) -> list[dict[str, Any]]:
    """The debugger's own registerpoint list, read back."""
    return parse_rplist(ses.monitor("rplist"))


def _adoptable(visible: str | None, held: list[dict[str, Any]],
               condition: str) -> dict[str, Any] | None:
    """The row `rplist` already holds under exactly `condition` ON THE VISIBLE CPU (`visible`,
    read off `cpulist`), which is where an `rpset` lands, whoever placed it, or None. The same
    text under another cpu compares another register file, so it is never adopted; with the
    visible cpu unknown (a console that does not answer `cpulist`) nothing is, and a second
    row of one condition is the cheaper mistake."""
    return next((r for r in held if r["condition"] == condition and r["cpu"] == visible),
                None)


def _owner(row: dict[str, Any], but: dec.Owner) -> str | None:
    """The ref of the OTHER declaration that already holds `row`, or None: two conditions that
    differ as typed can read the same once their symbols are addresses, and one row is one
    declaration, or clearing either would disarm the other."""
    return next((owner[0] for owner, rec in STATE.regpoints.items()
                 if owner != but and rec["index"] == row["index"]), None)


def _shared_why(condition: str, owner: str, cpu: str | None, holds: str = "already arms",
                clear_tool: mclear.ClearTool | None = "regpoint_clear") -> str:
    return (f"`{condition}` is what the registerpoint {owner!r} {holds}: "
            f"{mclear.one_declaration('registerpoint row', owner, clear_tool, cpu)}")


def forget_gone(ses: gs.Session) -> list[dec.Owner]:
    """`mclear.forget_rows_gone` for an `rpclear`: the record of every registerpoint row the
    debugger's list no longer shows goes with it. The owners forgotten."""
    held = rp_held(ses)
    gone = [owner for owner in STATE.regpoints if held_row(held, owner) is None]
    for owner in gone:
        STATE.regpoints.pop(owner)
    return gone


def held_row(held: list[dict[str, Any]], owner: dec.Owner) -> dict[str, Any] | None:
    """The listed row this session recorded for `owner`, or None: the same index, still under
    the condition it was armed with."""
    rec = STATE.regpoints.get(owner)
    if rec is None:
        return None
    return next((r for r in held if r["index"] == rec["index"]
                 and r["condition"] == rec["condition"]), None)


def _record(owner: dec.Owner, row: dict[str, Any]) -> None:
    STATE.regpoints[owner] = {"index": row["index"], "cpu": row["cpu"],
                              "condition": row["condition"]}
    STATE.conditions_unresolved.discard(("regpoint", owner))


def rp_command(condition: str) -> str:
    """The console command that arms a registerpoint. The one builder, so the check that it
    fits the stub's packet (`Session.console_packet`) judges the text that is sent. The
    braces are the console's: bare, it reads the condition as an assignment."""
    return f"rpset {{{condition}}}"


def _send(ses: gs.Session, condition: str) -> int | str:
    """`rpset` sent: the INDEX the console gave the row, which is what identifies it in the
    list whatever else compares the same text, or why it was not taken."""
    answer = ses.monitor(rp_command(condition)).strip()
    if (taken := _RPSET_TAKEN.match(answer)) is not None:
        return int(taken.group(1), 16)
    return (f"this MAME's debugger offers no registerpoints (`rpset` answered "
            f"{' '.join(answer.split())!r}); `breakpoint_at(ref=..., condition=...)` at an "
            "address is what this build can arm")


def _listed(held: list[dict[str, Any]], index: int, condition: str) -> dict[str, Any] | None:
    """The row the list holds at `index`, if it is under `condition`, or None."""
    return next((r for r in held if r["index"] == index and r["condition"] == condition),
                None)


def _not_listed(condition: str) -> str:
    return (mlists.not_listed(f"`{rp_command(condition)}`", "rplist")
            + "; `regpoint_list` shows the declaration kept and "
            "`regpoint_clear(ref=...)` removes it")


def check_regpoint_add(condition: str, **_: Any) -> None:
    """`regpoint_add`'s machine-independent half: a condition that is not empty, carries no
    ACTION (a comma, a newline, a brace) and assigns nothing."""
    conditions.check_condition(condition)


def _refuse_another_cpu(ses: gs.Session, cpu: str) -> None:
    """Refuse a cpu `regpoint_add` names that is not the visible one. `rpset` takes no cpu
    (`rp[set] <condition>[,<action>]`, its `help`, and `execute_rpset` arms on the visible cpu),
    so another is refused naming `focus` rather than moving the visible cpu behind the caller's
    back."""
    if not inputs.cpu_given(cpu):
        return
    tag, visible = cpus.named(ses, cpu), cpus.visible_cpu(ses)
    if tag != visible:
        raise st.Invalid("needs_call",
                         f"a registerpoint lives on the visible cpu, "
                         f"{visible or 'one `cpulist` did not mark'}, and `rpset` names "
                         f"no other: `focus(cpu={tag!r})` first")


def regpoint_add(ses: gs.Session, condition: str, cpu: str = "") -> dict[str, Any]:
    """The body of the `regpoint_add` tool."""
    running = arming.running_on_arrival(ses)
    check_regpoint_add(condition)
    _refuse_another_cpu(ses, cpu)
    ref = condition.strip()
    # THE DECLARATION'S CPU is the visible one, the only one `rpset` arms on.
    on = cpus.visible_cpu(ses)
    cond = conditions.console_condition(ref, on)
    # A COMMAND THE STUB WOULD DROP is refused before the declaration is stored, so the
    # refusal leaves nothing behind: `CommandTooLong` is `bad_argument`.
    ses.console_packet(rp_command(cond))
    refusal = conditions.not_evaluated(ses, cond)
    if refusal is not None:
        raise st.Invalid("bad_argument", f"the debugger did not evaluate `{cond}`, and a "
                                         f"registerpoint it cannot evaluate never fires: "
                                         f"{refusal}. `symbols_find(name=...)` checks a name; "
                                         "`regpoint_add` again once it reads")
    held = rp_held(ses)
    decl = arming.declare("regpoint", "expr", ref, on)
    row = held_row(held, decl.owner) or _adoptable(on, held, cond)
    if row is not None and (owner := _owner(row, decl.owner)) is not None:
        raise st.Invalid("ambiguous_ref", _shared_why(cond, owner, on))
    is_new = arming.store().add(decl)
    if row is None:
        taken = _send(ses, cond)
        if isinstance(taken, str):
            if is_new:
                arming.store().discard([decl])
            raise st.Invalid("no_channel", taken)
        row = _listed(rp_held(ses), taken, cond)
    if row is None:
        return menvelope.invalid("readback_refused", _not_listed(cond), ref=ref,
                                 **mclear.kept_fields("regpoint_clear", ref))
    _record(decl.owner, row)
    return menvelope.envelope({**dec.owner_fields(decl.owner), "by": "expr", "condition": cond,
                               "stored": True, "already_stored": not is_new,
                               "while_running": running,
                               "armed": row["enabled"], "state": mlists.row_state(row),
                               "entry": row["entry"], "index": row["index"],
                               **st.add_note({}, cpus.ignored_note(ses, row["cpu"]))})


def _declared() -> list[dec.Declaration]:
    return [d for d in arming.store().declarations() if d.kind == "regpoint"]


def regpoint_list(ses: gs.Session, cpu: str = "") -> dict[str, Any]:
    """The body of the `regpoint_list` tool: every declaration, or with `cpu` those listed under
    it, as `breakpoint_list` narrows: only `regpoint_add` needs the visible cpu."""
    only = cpus.named(ses, cpu) if inputs.cpu_given(cpu) else None
    held = [r for r in rp_held(ses) if only is None or r["cpu"] == only]
    out: list[dict[str, Any]] = []
    mine: set[int] = set()
    for decl in _declared():
        item = arming.decl_row(decl)
        try:
            item["condition"] = conditions.console_condition(decl.ref, decl.cpu)
        except st.Invalid as e:
            item["state"], item["why"] = "unresolved", str(e)
            if only is None:
                out.append(item)
            continue
        row = held_row(held, decl.owner)
        if row is not None:
            item.update(state=mlists.row_state(row), entry=row["entry"], index=row["index"],
                        cpu=row["cpu"])
            mine.add(row["index"])
        elif ("regpoint", decl.owner) in STATE.conditions_unresolved:
            item["state"] = "unresolved"
        else:
            item["state"] = "gone"
        if only is None or item.get("cpu") == only:
            out.append(item)
    reply: dict[str, Any] = {"regpoints": out,
                             "foreign": [r["entry"] for r in held if r["index"] not in mine]}
    reply["cpu"] = st.or_unavailable(only, st.NO_CPU_NAMED_WHY)   # every list tool carries it
    if ses.running:
        reply["last_stop"] = STATE.as_of()
    return menvelope.envelope(reply)


def check_regpoint_clear(ref: str = "", all: bool = False, **_: Any) -> None:
    """`regpoint_clear`'s machine-independent half: one `ref` (a condition, as declared) or
    `all=True`."""
    mclear.check_clear(ref, all, "regpoint")


def regpoint_clear(ses: gs.Session, ref: str, cpu: str = "", all_: bool = False
                   ) -> dict[str, Any]:
    """The body of the `regpoint_clear` tool: `ref`'s declarations (every one with no ref), on
    every cpu or on `cpu` alone."""
    check_regpoint_clear(ref=ref, all=all_)
    ref = "" if all_ else ref
    running = arming.running_on_arrival(ses)
    reached = mclear.clearing(ses, "regpoint", ref, cpu)
    clearing = reached.going
    if ref.strip() and not clearing:
        return mclear.refuse_unmatched_clear(ref.strip(), "regpoint", reached)
    going: list[mclear.Going] = []
    held = rp_held(ses)
    for decl in clearing:
        row = held_row(held, decl.owner)
        if row is None:
            # The debugger does not hold it any more (`gone`), or never did: nothing to
            # disarm, and claiming it would make `disarmed` this tool's word.
            STATE.regpoints.pop(decl.owner, None)
            continue
        going.append((decl.owner, row["entry"], row["index"]))
    gone, still_held = mclear.disarm_rows(ses, "registerpoint", going, lambda: rp_held(ses))
    for cleared, _entry, _index in gone:
        STATE.regpoints.pop(cleared, None)
    STATE.conditions_unresolved -= {("regpoint", d.owner) for d in clearing}
    removed = arming.store().discard(clearing)
    reply: dict[str, Any] = {"declarations_cleared": removed,
                             "disarmed": [entry for _owner, entry, _index in gone],
                             "while_running": running}
    if still_held:
        reply["note"] = mclear.still_held_note("registerpoint", still_held)
    return menvelope.envelope(reply)


def rearm(ses: gs.Session, out: dict[str, Any]) -> None:
    """THE REGISTERPOINT HALF OF `start`'s RE-ARM, into the account
    `rearming.rearm_breakpoints_and_watches` opened: every stored registerpoint is re-resolved
    against this start's table and evaluated once, and is `rearmed` (armed and read back, or a
    row already listed under its condition adopted, with `mlists.adopted_state` when the list
    shows it disabled),
    `unresolved` (the console answers `unknown symbol`: kept), or `unarmable` with why (declared
    on a cpu that is not the visible one, since `rpset` arms on that one alone; any other
    refusal, a packet too long for THIS binary's stub, a console that raised while evaluating
    it, a row the list does not show). One declaration's refusal is its own: the pass goes on.
    The list is read once before the pass and once after it."""
    declared = _declared() if STATE.store is not None else []
    if not declared:
        return
    held, visible = rp_held(ses), cpus.visible_cpu(ses)
    sent: list[tuple[dec.Declaration, str, int]] = []
    for decl in declared:
        name = arming.decl_row(decl)
        if None not in (decl.cpu, visible) and decl.cpu != visible:
            out["unarmable"].append({**name, "why": (
                f"a registerpoint arms on the visible cpu alone (`rpset` names no other), and "
                f"{decl.cpu} is not visible now ({visible} is): `focus(cpu={decl.cpu!r})`, then "
                "`regpoint_add` again")})
            continue
        try:
            cond = conditions.console_condition(decl.ref, decl.cpu or visible)
            ses.console_packet(rp_command(cond))
            refusal = conditions.not_evaluated(ses, cond)
        except (st.Invalid, gs.SessionError) as e:
            out["unarmable"].append({**name, "why": str(e)})
            continue
        if refusal is not None and "unknown symbol" in refusal:
            STATE.conditions_unresolved.add(("regpoint", decl.owner))
            out["unresolved"].append(name)
        elif refusal is not None:
            out["unarmable"].append({**name, "why": "the debugger did not evaluate "
                                                    f"`{cond}`: {refusal}"})
        elif (first := next((d.ref for d, c, _i in sent if c == cond), None)) is not None:
            out["unarmable"].append({**name, "why": _shared_why(cond, first, visible,
                                                                "was just sent for", None)})
        elif (row := _adoptable(visible, held, cond)) is not None:
            if (owner := _owner(row, decl.owner)) is not None:
                out["unarmable"].append({**name, "why": _shared_why(cond, owner, visible,
                                                                    clear_tool=None)})
                continue
            _record(decl.owner, row)
            out["rearmed"].append({**name, **mlists.adopted_state("rp", row)})
        elif isinstance(taken := _send(ses, cond), str):
            out["unarmable"].append({**name, "why": taken})
        else:
            sent.append((decl, cond, taken))
    # READ THE LIST BACK ONCE for everything sent: `rearmed` is the machine's answer.
    after = rp_held(ses) if sent else []
    for placed, cond, index in sent:
        row = _listed(after, index, cond)
        if row is None:
            out["unarmable"].append({**arming.decl_row(placed), "why": _not_listed(cond)})
        else:
            _record(placed.owner, row)
            out["rearmed"].append(arming.decl_row(placed))


def stop_how(ses: gs.Session, since: list[str],
             pc: str) -> tuple[str, dict[str, Any] | None] | None:
    """How a stop is named when the console's newest `Stopped at registerpoint <n>` in
    `since` names a row somebody holds, and the hit when the row is this server's, or None.
    A registerpoint of this server is named by its ref, with the clause that says a declaration
    was inherited, and NOTHING about it changes: it stays armed and stored, and the hit says
    what that means for the next advance. A row typed through `debug` is named with the
    condition its row lists; one the debugger no longer lists is nobody's stop now. A list
    the console will not answer cannot say what the row compares: the stop is still named,
    since resuming through it would lose a stop somebody asked for."""
    stops = [m for ln in since if (m := _RP_STOP_LINE.search(ln)) is not None]
    if not stops:
        return None
    index = int(stops[-1].group(1), 16)
    own = next((owner for owner, rec in STATE.regpoints.items() if rec["index"] == index),
               None)
    if own is not None:
        decl = next((d for d in _declared() if d.owner == own), None)
        return (f"registerpoint {own[0]!r}" + (arming.inherited(decl) if decl is not None
                                              else ""),
                {**dec.owner_fields(own), "condition": STATE.regpoints[own]["condition"],
                 "index": index, "pc": pc, "note": STILL_ARMED})
    try:
        row = next((r for r in rp_held(ses) if r["index"] == index), None)
    except (gs.SessionError, st.Invalid) as e:
        return (f"registerpoint {mclear.row_index(index)}; the debugger's list could not be "
                f"read to say whose: {e}", None)
    if row is None:
        return None
    return (mclear.foreign_row_how("registerpoint", index,
                                   f" (if {row['condition']}), typed through `debug`"), None)
