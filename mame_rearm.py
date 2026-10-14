"""THE RE-ARM AT `start`: every declaration the store holds re-resolved and re-armed in
ONE pass, whatever its family, each debugger list read once before it and once after,
and every declaration accounted for. It walks the store in its own order, which is
why it is one pass over both families rather than one per family."""

from __future__ import annotations

from typing import Any

import gdb_session as gs
import mame_arming as arming
import mame_breakpoints as breakpoints
import mame_capture as capture
import mame_clear as mclear
import mame_conditions as conditions
import mame_declarations as dec
import mame_lists as mlists
import mame_map as mmap
import mame_prose as prose
import mame_space as mspace
import mame_state as st
import mame_watches as watches
from mame_state import STATE

# --------------------------------------------------------------------------- the re-arm


def _trigger_lost(decl: dec.Declaration) -> bool:
    """A capture held on a trigger name this build's table lacks."""
    return (decl.kind == "watch" and decl.watch_mode == "capture" and bool(decl.trigger)
            and capture.trigger_addr(decl.trigger, STATE.table(decl.cpu).table) is None)


def rearm_breakpoints_and_watches(ses: gs.Session) -> dict[str, Any]:
    """RE-RESOLVE AND RE-ARM every declaration the store holds, at `start`, against the table
    this start loaded, and account for every one of them, all inherited since nothing of this
    session's is declared yet: `rearmed` (a breakpoint or a change watch armed and read back,
    a count or capture watch's tap sent, with its `note` when its write side is unmapped, by
    name whatever the build and by raw address over
    this same build fingerprint), `stale` (a raw address declared over another build, kept
    and not armed: `dec.is_stale`), `unresolved` (a name this build lacks, kept, in the ref,
    in a condition or in a capture's trigger), `unarmable` (with why: a change watch's write side
    unmapped now, an address or a range sharing a byte with one another declaration already holds, a
    row the debugger did not list or lists under another condition, a condition too long for
    one packet of THIS binary's stub, a capture's block with no memory a tap can read; a
    breakpoint's, stop or control, or a change watch's row it lists disabled is adopted into
    `rearmed` with its state, `mlists.adopted_state`, as `mame_regpoints.rearm` adopts a
    registerpoint's),
    `evaluated` (a show watch, which needs no arming and rides on every stop). Nothing is
    dropped and nothing is silent: the whole point of keeping the intent is that it comes back.
    Each debugger list is read ONCE before the pass and once after it, whatever the store
    holds. Every row is the one `arming.decl_row` builds for its declaration."""
    out: dict[str, Any] = {"rearmed": [], "stale": [], "unresolved": [], "unarmable": [],
                           "evaluated": []}
    if STATE.store is None:
        return out
    # A STORE WRITTEN BEFORE A DECLARATION HAD A CPU held the first cpu's alone.
    STATE.store.bind_first_cpu(STATE.first_cpu)
    # Each list is read the first time a declaration needs it, and once: a store with no
    # breakpoint never asks `bplist`, and a stub answering nothing else stays untouched.
    lists: dict[str, list[dict[str, Any]]] = {}
    # THE INDICES EACH LIST HELD BEFORE THE PASS SENT ANYTHING, from its first reading, which
    # every send follows: a row the pass sent is one whose index is not among them.
    before: dict[str, set[int]] = {}
    def held(which: str) -> list[dict[str, Any]]:
        if which not in lists:
            lists[which] = mlists.bp_held(ses) if which == "bp" else mlists.wp_held(ses)
            before.setdefault(which, {r["index"] for r in lists[which]})
        return lists[which]

    # A VISIBLE CPU NOT PUT BACK after a condition's evaluation: the row keeps its judgement and
    # is armed by its cpu's name, which no visible cpu changes; the pass names the cpu once.
    put_backs: list[str | None] = []
    sent_bp: list[tuple[dec.Declaration, int, str]] = []
    done_bp: list[dec.Declaration] = []     # the breakpoints this pass has placed, for aliases
    sent_wp: list[tuple[dec.Declaration, int, int, str, str | None, str]] = []
    for decl in STATE.store.declarations():
        if decl.kind in ("regpoint", "comment"):
            continue        # `mame_regpoints.rearm` and `mame_comments.rearm` account for these
        name = arming.decl_row(decl)
        res = arming.resolve_decl(decl)
        if decl.kind == "watch" and decl.watch_mode in ("show", "expr"):
            # ONE WORD PER ROW in every view (`watches.resolved_state`): a show watch whose ref
            # this build cannot place is `unresolved` here as in `watch_list` and the survey.
            word = watches.resolved_state(decl, res)
            out["unresolved" if word == "unresolved" else "evaluated"].append(name)
            continue
        if res.state == "pointer":
            try:
                target, info = watches.chase(ses, res)
            except gs.SessionError as e:
                out["unarmable"].append({**name, "why": str(e)})
                continue
            if target is None:
                out["unarmable"].append({**name, "why": watches.null_note(info)})
                continue
            res = dec.Resolved(decl, "resolved", target)
        if (decl.kind == "watch" and watches.resolved_state(decl, res) == "unresolved"
                or res.addr is None or _trigger_lost(decl)):
            # a capture's trigger this build lacks is what it lacks first, as the list says
            out["unresolved"].append(name)
            continue
        if arming.stale(decl):
            out["stale"].append(name)
            continue
        if decl.kind == "watch" and decl.watch_mode in dec.TAP_MODES:
            assert decl.width is not None
            if STATE.scratch is None:
                out["unarmable"].append({**name, "why": "no scratch"})
                continue
            try:
                refused, sent = watches.send_tap(ses, STATE.scratch, decl, res.addr, decl.width)
            except st.Invalid as e:
                out["unarmable"].append({**name, "why": str(e)})
                continue
            if refused is not None and refused[0] == "unknown_ref":
                out["unresolved"].append(name)       # a trigger this build lacks
            elif refused is not None:
                out["unarmable"].append({**name, "why": refused[1]})
            elif "unmapped" in (sent.get("write_maps_to"), sent.get("trigger_maps_to")):
                out["rearmed"].append({**name, "note": sent["note"]})    # where the writes go
            else:
                out["rearmed"].append(name)
            continue
        if decl.kind == "breakpoint" and decl.role == "control":
            why = breakpoints.bp_aliased(decl.owner, res.addr, done_bp, " in this pass",
                                           None)
            if why is not None:
                out["unarmable"].append({**name, "why": why})
                continue
            try:
                row = breakpoints.arm_control(ses, decl.owner, res.addr, held("bp"))
            except st.Invalid as e:
                out["unarmable"].append({**name, "why": str(e)})
                continue
            if row is None:
                out["unarmable"].append({**name, "why": mlists.not_listed(
                    f"a `bp` at {res.addr:#x}", "bplist")})
            else:
                lists.pop("bp", None)      # the list changed: the next reader re-reads it
                out["rearmed"].append({**name, **mlists.adopted_state("bp", row)})
                done_bp.append(decl)
            continue
        if decl.kind == "breakpoint":
            why = breakpoints.bp_aliased(decl.owner, res.addr, done_bp, " in this pass",
                                           None)
            cond = ""
            if why is None and decl.condition:
                # A name this build lacks reaches the console as a word it does not know.
                try:
                    cond = conditions.console_condition(decl.condition, decl.cpu)
                    judged = conditions.judged_condition(
                        ses, breakpoints.bp_command(res.addr, cond, decl.cpu), cond, decl.cpu)
                    refusal = judged.refusal
                    put_backs.append(judged.left_visible)
                except (st.Invalid, gs.SessionError) as e:
                    # A packet smaller than the one that stored it, a name this table makes
                    # ambiguous, or a console that raised under the evaluation. Nothing was
                    # armed for it, and the start goes on to the next declaration.
                    out["unarmable"].append({**name, "why": str(e)})
                    continue
                if refusal is not None and "unknown symbol" in refusal:
                    STATE.conditions_unresolved.add(("breakpoint", decl.owner))
                    out["unresolved"].append(name)
                    continue
                if refusal is not None:
                    why = f"the debugger did not evaluate `{cond}`: {refusal}"
            row = None
            if why is None:
                row, unadoptable = breakpoints.stop_row(held("bp"), decl.owner, res.addr, cond)
                if unadoptable is not None:
                    why = str(unadoptable)
            if why is not None:
                out["unarmable"].append({**name, "why": why})
            elif row is not None:
                breakpoints.own_row(row, decl.owner)
                out["rearmed"].append({**name, **mlists.adopted_state("bp", row)})
                done_bp.append(decl)
            else:
                ses.monitor(breakpoints.bp_command(res.addr, cond, decl.cpu))
                if cond:
                    lists.pop("bp", None)
                sent_bp.append((decl, res.addr, cond))
                done_bp.append(decl)
            continue
        assert decl.width is not None
        arm_on = decl.cpu
        cond = ""
        if decl.condition:
            # The breakpoints' pass, for a watch: a name this build lacks is `unresolved`.
            try:
                cond = conditions.console_condition(decl.condition, decl.cpu)
                judged = conditions.judged_condition(
                    ses, watches.wp_command(res.addr, decl.width, arm_on, cond), cond, arm_on)
                refusal = judged.refusal
                put_backs.append(judged.left_visible)
            except (st.Invalid, gs.SessionError) as e:
                out["unarmable"].append({**name, "why": str(e)})
                continue
            if refusal is not None and "unknown symbol" in refusal:
                STATE.conditions_unresolved.add(("watch", decl.owner))
                out["unresolved"].append(name)
                continue
            if refusal is not None:
                out["unarmable"].append({**name, "why": f"the debugger did not evaluate "
                                                        f"`{cond}`: {refusal}"})
                continue
        refused, maps_to, read_maps_to = mmap.change_watch_side(ses, res.addr, arm_on)
        refused = refused or watches.watch_aliased(decl.owner, res.addr, decl.width, None)
        why = refused[1] if refused is not None else next(
            (f"{res.addr:#x} for {prose.counted(decl.width, 'byte')} shares a byte with a range "
             f"already sent under {d.ref!r} in this pass: "
             f"{mclear.one_declaration('watched range', d.ref, None, decl.cpu)}"
             for d, a, w, _t, _r, _c in sent_wp
             if d.cpu == decl.cpu and mspace.ranges_meet(a, w, res.addr, decl.width)),
            None)
        if why is not None:
            out["unarmable"].append({**name, "why": why})
            continue
        row, unadoptable = watches.change_row(held("wp"), res.addr, decl.width, arm_on, cond,
                                              watches.watch_indices())
        if unadoptable is not None:
            out["unarmable"].append({**name, "why": str(unadoptable)})
        elif row is not None:
            watches.record_watch(decl.owner, row, maps_to, read_maps_to)
            out["rearmed"].append({**name, **mlists.adopted_state("wp", row)})
        else:
            ses.monitor(watches.wp_command(res.addr, decl.width, arm_on, cond))
            sent_wp.append((decl, res.addr, decl.width, maps_to, read_maps_to, cond))
    # READ EACH LIST BACK ONCE for everything sent: `rearmed` is the machine's answer. Which row a
    # declaration adopts, what refuses it and whether a row read back is the one sent are the
    # declarations' own rules (`stop_row`, `change_row`, `mlists.listed_as_sent`); what is the
    # pass's alone is the batching, one `bplist` and one `wplist` for the whole store where a
    # declaration reads its list after its own command.
    if sent_bp:
        bp_rows = mlists.bp_held(ses)
        for placed, addr, cond in sent_bp:
            row = mlists.fresh_row(bp_rows, before["bp"] | set(STATE.breakpoints), addr,
                                   cpu=placed.cpu)
            if not mlists.listed_as_sent(row, cond):
                out["unarmable"].append({**arming.decl_row(placed), "why": mlists.not_listed(
                    f"a `bp` at {addr:#x}", "bplist", bool(cond))})
            else:
                assert row is not None
                breakpoints.own_row(row, placed.owner)
                out["rearmed"].append(arming.decl_row(placed))
    if sent_wp:
        wp_held = mlists.wp_held(ses)
        for placed, addr, width, maps_to, read_maps_to, cond in sent_wp:
            row = mlists.fresh_row(wp_held, before["wp"] | watches.watch_indices(), addr, width,
                                   placed.cpu)
            if not mlists.listed_as_sent(row, cond):
                out["unarmable"].append({**arming.decl_row(placed), "why": mlists.not_listed(
                    f"a `wp` at {addr:#x} for {prose.counted(width, 'byte')}", "wplist",
                    bool(cond))})
            else:
                assert row is not None
                watches.record_watch(placed.owner, row, maps_to, read_maps_to)
                out["rearmed"].append(arming.decl_row(placed))
    return st.add_note(out, *put_backs)
