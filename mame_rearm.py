"""Re-resolve and re-arm every stored declaration in one pass, both families."""

from __future__ import annotations

from typing import Any

from scry_core import prose

import gdb_session as gs
import mame_arming as arming
import mame_breakpoints as breakpoints
import mame_capture as capture
import mame_clear as mclear
import mame_conditions as conditions
import mame_declarations as dec
import mame_lists as mlists
import mame_map as mmap
import mame_space as mspace
import mame_state as st
import mame_watches as watches
from mame_state import STATE


def _trigger_lost(decl: dec.Declaration) -> bool:
    """A capture held on a trigger name this build's table lacks."""
    return (decl.kind == "watch" and decl.watch_mode == "capture" and bool(decl.trigger)
            and capture.trigger_addr(decl.trigger, STATE.table(decl.cpu).table) is None)


def rearm_breakpoints_and_watches(ses: gs.Session) -> dict[str, Any]:
    """Re-arm every stored declaration at `start` and account for each one.

    Buckets: `rearmed`, `stale` (raw address from another build), `unresolved` (a name this
    build lacks), `unarmable` (with why) and `evaluated` (show watches, which need no arming).
    Each debugger list is read once before the pass and once after.
    """
    out: dict[str, Any] = {"rearmed": [], "stale": [], "unresolved": [], "unarmable": [],
                           "evaluated": []}
    if STATE.store is None:
        return out
    STATE.store.bind_first_cpu(STATE.first_cpu)
    # Read lazily: a store with no breakpoint never asks `bplist`.
    lists: dict[str, list[dict[str, Any]]] = {}
    # Indices held before the pass sent anything: a row the pass sent is not among them.
    before: dict[str, set[int]] = {}
    def held(which: str) -> list[dict[str, Any]]:
        if which not in lists:
            lists[which] = mlists.bp_held(ses) if which == "bp" else mlists.wp_held(ses)
            before.setdefault(which, {r["index"] for r in lists[which]})
        return lists[which]

    # Armed by cpu name, which no visible cpu changes, so a cpu left visible by a condition's
    # evaluation is only reported (once).
    put_backs: list[str | None] = []
    sent_bp: list[tuple[dec.Declaration, int, str]] = []
    done_bp: list[dec.Declaration] = []     # for alias checks
    sent_wp: list[tuple[dec.Declaration, int, int, str, str | None, str]] = []
    for decl in STATE.store.declarations():
        if decl.kind in ("regpoint", "comment"):
            continue        # accounted for by their own modules' `rearm`
        name = arming.decl_row(decl)
        res = arming.resolve_decl(decl)
        if decl.kind == "watch" and decl.watch_mode in ("show", "expr"):
            # same word as `declaration_list(kind="watch")` and the survey
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
            # a lost trigger outranks the rest, as in the list
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
                out["unresolved"].append(name)
            elif refused is not None:
                out["unarmable"].append({**name, "why": refused[1]})
            elif "unmapped" in (sent.get("write_maps_to"), sent.get("trigger_maps_to")):
                out["rearmed"].append({**name, "note": sent["note"]})
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
                lists.pop("bp", None)      # stale now: re-read on next use
                out["rearmed"].append({**name, **mlists.adopted_state("bp", row)})
                done_bp.append(decl)
            continue
        if decl.kind == "breakpoint":
            why = breakpoints.bp_aliased(decl.owner, res.addr, done_bp, " in this pass",
                                           None)
            cond = ""
            if why is None and decl.condition:
                try:
                    cond = conditions.console_condition(decl.condition, decl.cpu)
                    judged = conditions.judged_condition(
                        ses, breakpoints.bp_command(res.addr, cond, decl.cpu), cond, decl.cpu)
                    refusal = judged.refusal
                    put_backs.append(judged.left_visible)
                except (st.Invalid, gs.SessionError) as e:
                    # nothing was armed; the start goes on
                    out["unarmable"].append({**name, "why": str(e)})
                    continue
                if conditions.refused_on_rearm(refusal, cond, "breakpoint", decl.owner, name,
                                               out):
                    continue
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
            try:
                cond = conditions.console_condition(decl.condition, decl.cpu)
                judged = conditions.judged_condition(
                    ses, watches.wp_command(res.addr, decl.width, arm_on, cond), cond, arm_on)
                refusal = judged.refusal
                put_backs.append(judged.left_visible)
            except (st.Invalid, gs.SessionError) as e:
                out["unarmable"].append({**name, "why": str(e)})
                continue
            if conditions.refused_on_rearm(refusal, cond, "watch", decl.owner, name, out):
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
    # One read-back per list for everything sent: `rearmed` is the machine's answer.
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
