"""The edges of the declarations tier: which row is whose, which declaration a loop
reaches, where a list ends, each asked through what a caller sees or what goes to the
console. No list a double prints here assumes one cpu: every one carries its `Device` header.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from scry_core import reply_contract as contract  # noqa: E402
from server_support import _running, _RunningSession  # noqa: E402
from session_doubles import IDENTITY_KEYS, captured, ref_cpu, refs, refused, use_table  # noqa: E402
from test_controls import _cond, _controlled, _limit, _refusing  # noqa: E402
from test_tally import _tallying  # noqa: E402
from test_watches import STOP_LINE, _watching  # noqa: E402

from scry_mame import (
    arming,  # noqa: E402
    breakpoints,  # noqa: E402
    regpoints,  # noqa: E402
    watches,  # noqa: E402
)
from scry_mame import clear as mclear  # noqa: E402
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import gdb_session as gs  # noqa: E402
from scry_mame import lists as mlists  # noqa: E402
from scry_mame import rearm as rearming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

BP_HEADER = "Device ':maincpu' breakpoints:\n"
WP_HEADER = "Device ':maincpu' program space watchpoints:\n"


# ------------------------------------------------------------------ what a list is


@pytest.mark.parametrize("parse, text", [(mlists.parse_bplist, "\n"), (mlists.parse_wplist, "")])
def test_an_answer_with_no_row_and_no_sentence_for_none_is_not_a_list(
    parse: object, text: str,
) -> None:
    with pytest.raises(contract.Invalid, match="something other than a list") as refusal:
        parse(text)  # type: ignore[operator]
    assert refusal.value.code == "unexpected_answer"


def test_a_line_that_is_no_row_is_refused_by_its_code() -> None:
    with pytest.raises(contract.Invalid) as refusal:
        mlists.parse_bplist(BP_HEADER + "Unknown command\n")
    assert refusal.value.code == "unexpected_answer"


def test_a_list_index_is_hex_and_a_disabled_row_says_so_in_its_entry() -> None:
    rows = mlists.parse_bplist(BP_HEADER + "   1F @ 000400\nD  20 @ 0004A0 if d0==1\n\n")
    assert [(r["index"], r["enabled"], r["entry"]) for r in rows] == [
        (0x1F, True, "1F @ 000400"), (0x20, False, "D 20 @ 0004A0 if d0==1")]
    (row,) = mlists.parse_wplist(WP_HEADER + "   1F @ 2031FC-2031FF write\n\n")
    assert row["index"] == 0x1F


def test_a_pointer_ref_keeps_the_sign_of_its_offset() -> None:
    assert dec.canonical_ref("[0X4A0]+4", "pointer") == "[0x4a0]+0x4"
    assert dec.canonical_ref("[0X4A0]-4", "pointer") == "[0x4a0]-0x4"


# ------------------------------------------------------------------ a condition


def test_a_symbol_spelled_like_a_console_variable_is_refused_in_a_condition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"FRAME": 0x2031FC})
    out = refused("both a symbol of the table and a name the console knows",
                  s.breakpoint_at(ref="0x4a0", condition="Frame==1"))
    assert out["code"] == "ambiguous_ref"


@pytest.mark.parametrize("at_rearm", [False, True])
def test_the_bp_command_of_a_long_address_is_judged_before_anything_is_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, at_rearm: bool,
) -> None:
    """At an address of six digits the `bp` is the LONGER of the two commands, so it is the
    one the packet check has to reach: the evaluation alone would fit and be sent."""
    ses = _controlled(monkeypatch, tmp_path)
    _refusing(ses)
    ses.packet_size = 0x41
    cond = _cond(ses, 0x200000, 1)
    assert len(breakpoints.bp_command(0x200000, cond, ":maincpu")) == _limit(ses) + 1 > len(
        f"print {{{cond}}}")
    if at_rearm:
        arming.store().add(dec.Declaration("breakpoint", "address", "0x200000", condition=cond,
                                           fingerprint="fp-test"))
        out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
        assert ref_cpu(out["unarmable"]) == [("0x200000", ":maincpu")]
        assert f"{_limit(ses) + 1} characters" in out["unarmable"][0]["why"]
    else:
        out = s.breakpoint_at(ref="0x200000", condition=cond)
        assert out["code"] == "bad_argument" and out["command_chars"] == _limit(ses) + 1
        assert arming.store().declarations() == []
    assert not any(c.startswith("print {") for c in ses.commands), "nothing was sent"


def test_a_stored_condition_this_table_makes_ambiguous_is_unarmable_and_listed_as_typed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"TICKS": 0x2031FC})
    s.breakpoint_at(ref="0x4a0", condition="w@Ticks==1")
    s.breakpoint_at(ref="0x4b0")
    ses.bplist_rows.clear()
    ses.commands.clear()
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    use_table(monkeypatch, table={"TICKS": 0x2031FC, "FRAME": 0x100})
    arming.store().replace(arming.store().declarations()[0], dec.Declaration(
        "breakpoint", "address", "0x4a0", condition="w@Frame==1", origin="s1"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert [u["ref"] for u in out["unarmable"]] == ["0x4a0"], out
    assert refs(out["rearmed"]) == ["0x4b0"], out
    assert "both a symbol of the table" in out["unarmable"][0]["why"]
    row = s.declaration_list("breakpoint")["breakpoints"][0]
    assert row["condition"] == "w@Frame==1" and "condition_typed" not in row
    assert not any(c.startswith(("bp 0x4a0", "print {")) for c in ses.commands)


def test_a_conditioned_breakpoint_is_evaluated_and_armed_on_a_running_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    ses.running = True
    out = s.breakpoint_at(ref="0x4a0", condition="d0==1")
    assert out["armed"] is True and out["while_running"] is True, out
    assert [c for c in ses.commands if c.startswith(("print {", "bp "))] == [
        "print {d0==1}", "bp 0x4a0::maincpu,d0==1"]


# ------------------------------------------------------------------ breakpoint_at's replies


def test_an_unresolved_declaration_says_why_in_a_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    out = s.breakpoint_at(ref="scene_id", by="symbol")
    assert out["state"] == "unresolved" and "not a symbol in this build" in out["note"]


@pytest.mark.parametrize("condition, took, missing", [
    ("", "the console took `bp 0x4a0::maincpu`", "does not list it: nothing is armed"),
    ("d0==1", "the console took `bp 0x4a0::maincpu,d0==1`",
     "does not list a conditioned row: nothing"),
])
def test_a_refused_readback_names_the_ref_the_address_and_what_was_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, condition: str, took: str, missing: str,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "breakpoint", lambda addr, remove=False: None)
    taken = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: (
        "Breakpoint 1 set\n\n" if c.startswith("bp ") else taken(c, timeout)))
    out = s.breakpoint_at(ref="0x4a0", condition=condition)
    assert (out["code"], out["ref"], out["addr"]) == ("readback_refused", "0x4a0", "0x000004a0")
    assert took in out["message"] and missing in out["message"], out["message"]
    assert (out["stored"], out["armed"], out["state"]) == (True, False, "gone"), out
    assert "re-arms at the next `start`" in out["note"] and (
        "declaration_clear(kind=\"breakpoint\", ref='0x4a0')" in out["note"]), (
        "the refusal says the declaration was KEPT, and what removes it")
    assert [(r["ref"], r["state"]) for r in s.declaration_list("breakpoint")["breakpoints"]] == [
        ("0x4a0", "gone")]


def test_a_control_the_list_never_showed_names_its_ref_and_its_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    taken = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: (
        "Breakpoint 1 set\n\n" if c.startswith("bp ") else taken(c, timeout)))
    out = s.breakpoint_at(ref="0x25a4", role="control")
    assert (out["code"], out["ref"], out["addr"]) == ("readback_refused", "0x25a4", "0x000025a4")
    assert (out["stored"], out["armed"], out["state"]) == (True, False, "gone"), out
    assert "declaration_clear(kind=\"breakpoint\", ref='0x25a4')" in out["note"], out["note"]


# ------------------------------------------------------------------ a clear reaches past a skip


def _cleared_but_listed(monkeypatch: pytest.MonkeyPatch, ses: Any) -> Any:
    """A console that answers every `bpclear` as done and keeps the row listed; the real
    `monitor`, for the case to put back."""
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bpclear "):
            ses.commands.append(command)
            return captured("bpclear-cleared.txt").replace(
                " 1 ", f" {int(command[8:], 16):X} ")
        return str(real(command, timeout))

    monkeypatch.setattr(ses, "monitor", monitor)
    return real


def test_breakpoint_clear_keeps_its_record_while_the_list_still_shows_the_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console TOOK the `bpclear` and `bplist` still lists the row: `disarmed` stays the list's
    answer and `note` names the row and its `bpclear`, as `declaration_clear(kind="watch")`'s does.
    A stop the
    row then produces is named by its address; once that `bpclear` is typed through `debug`
    and the list drops the row, the record goes with it and a row typed there later is
    named as the foreign row it is."""
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0x4A0])
    s.breakpoint_at(ref="0x4a0")
    real = _cleared_but_listed(monkeypatch, ses)
    out = s.declaration_clear("breakpoint", ref="0x4a0")
    assert out["declarations_cleared"] == 1 and out["disarmed"] == [], out
    assert "1 @ 0004A0" in out["note"] and "still" in out["note"], out
    assert "`debug(\"bpclear 0x1\")` removes the row" in out["note"], out["note"]
    assert 1 in mstate.STATE.breakpoints, "the record is kept while the row is listed"
    assert arming.store().declarations() == []
    (tmp_path / "debug.log").write_text("F2034\n")
    s.resume()
    ses.stops_after_polls = 1
    how = str(s.status()["stopped_on_its_own"]["cause"])
    assert how == "breakpoint at 0x4a0", how
    # THE COMMAND THE NOTE NAMES, typed: the list drops the row and the record goes with
    # it, so a row typed there later is a foreign row and named as one.
    monkeypatch.setattr(ses, "monitor", real)
    s.debug(command="bpclear 1")
    assert ses.bplist_rows == [] and mstate.STATE.breakpoints == {}, "forgotten"
    ses.bplist_rows.append("   1F @ 0004A0")
    s.resume()
    (tmp_path / "debug.log").open("a").write("Stopped at breakpoint 1F\n4A0\n")
    ses.stops_after_polls = 1
    how = str(s.status()["stopped_on_its_own"]["cause"])
    assert how == ("breakpoint 1F at 0x000004a0, typed through `debug`: `debug(\"bpclear 0x1f\")` "
                   "removes it"), how


def test_breakpoint_clear_names_every_row_still_listed_with_its_own_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    s.breakpoint_at(ref="0x4b0")
    _cleared_but_listed(monkeypatch, ses)
    out = s.declaration_clear("breakpoint", all=True)
    assert out["declarations_cleared"] == 2 and out["disarmed"] == [], out
    assert "1 @ 0004A0" in out["note"] and "2 @ 0004B0" in out["note"], out["note"]
    assert out["note"].endswith(
        '`debug("bpclear 0x1")`, `debug("bpclear 0x2")` remove the rows'), out


def test_a_breakpoint_clear_reaches_the_declaration_after_one_it_skips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="scene_id", by="symbol")            # unresolved: nothing to disarm
    s.breakpoint_at(ref="0x4a0")
    s.breakpoint_at(ref="0x4b0")
    ses.bplist_rows[:] = [r for r in ses.bplist_rows if "0004A0" not in r]   # 4a0 is `gone`
    assert s.declaration_clear("breakpoint", ref="0x4b0")["disarmed"] == ["2 @ 0004B0"]
    s.breakpoint_at(ref="0x4b0")
    out = s.declaration_clear("breakpoint", all=True)
    assert out["disarmed"] == ["3 @ 0004B0"] and out["declarations_cleared"] == 3
    # The row that was gone left no owner behind: one typed there now is nobody's declaration.
    ses.bplist_rows.append("    9 @ 0004A0")
    assert breakpoints.breakpoint_name(0x4A0, ":maincpu") is None


def test_clearing_a_declaration_that_owns_no_row_leaves_the_owners_row_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A store from before the one-row rule: two declarations at one address, one owner."""
    ses = _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"VBLANK": 0x4A0})
    s.breakpoint_at(ref="vblank")
    arming.store().add(dec.Declaration("breakpoint", "address", "0x4a0", origin="s1",
                                       fingerprint="fp-test"))
    out = s.declaration_clear("breakpoint", ref="0x4a0")
    assert out["disarmed"] == [] and out["declarations_cleared"] == 1
    assert ses.bplist_rows == ["    1 @ 0004A0"] and ses.armed == [(0x4A0, False)]


def test_a_watch_clear_reaches_the_declaration_after_one_it_skips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="0x203300", mode="count", length=2)        # a tally: its own removal
    s.watch_add(ref="0x203400", mode="show", length=2)         # nothing armed
    s.watch_add(ref="0x203500", mode="change", length=2)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    assert s.declaration_clear("watch", ref="frame_lo")["disarmed"] == ["2 @ 2031FC-2031FF write"]
    out = s.declaration_clear("watch", all=True)
    assert out["disarmed"] == ["1 @ 203500-203501 write"] and ses.wplist_rows == []


def test_a_regpoint_clear_and_list_reach_past_a_row_the_debugger_dropped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    for condition in ("d0==1", "d1==2", "d2==3"):
        s.regpoint_add(condition=condition)
    ses.rplist_rows[:] = [r for r in ses.rplist_rows if r[1] != "d0==1"]
    states = [(r["ref"], r["state"]) for r in s.declaration_list("regpoint")["regpoints"]]
    assert states == [("d0==1", "gone"), ("d1==2", "armed"), ("d2==3", "armed")]
    assert s.declaration_clear("regpoint", ref="d2==3")["disarmed"] == ["3 if d2==3"]
    assert s.declaration_clear("regpoint", all=True)["disarmed"] == ["2 if d1==2"]


def test_a_regpoint_clear_takes_regpoints_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.exprs["d1==7fff"] = 0
    s.breakpoint_at(ref="0x4a0")
    assert s.watch_add(ref="d1==7fff", mode="expr")["status"] == "ok"
    s.regpoint_add(condition="d1==7fff")
    assert s.declaration_clear("regpoint", ref="d1==7fff")["declarations_cleared"] == 1
    s.regpoint_add(condition="d1==7fff")
    assert s.declaration_clear("regpoint", all=True)["declarations_cleared"] == 1
    assert [(d.kind, d.ref) for d in arming.store().declarations()] == [
        ("breakpoint", "0x4a0"), ("watch", "d1==7fff")]


def test_clearing_one_unresolved_regpoint_leaves_the_other_unresolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    for condition in ("d0==Gone_A", "d0==Gone_B"):
        arming.store().add(dec.Declaration("regpoint", "expr", condition, origin="s0"))
        ses.rp_errors[condition] = captured("print-braces-unknown-symbol.txt")
    out: dict[str, list[object]] = {"rearmed": [], "unresolved": [], "unarmable": []}
    regpoints.rearm(ses, out)  # type: ignore[arg-type]
    assert refs(out["unresolved"]) == ["d0==Gone_A", "d0==Gone_B"]
    s.declaration_clear("regpoint", ref="d0==Gone_A")
    assert [(r["ref"], r["state"]) for r in s.declaration_list("regpoint")["regpoints"]] == [
        ("d0==Gone_B", "unresolved")]


def test_a_regpoint_the_console_will_not_take_removes_only_itself(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    s.regpoint_add(condition="d0==1")
    taken = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: (
        captured("rpset-unknown-command.txt") if c.startswith("rpset ") else taken(c, timeout)))
    ses.exprs["d1==2"] = 0
    assert s.watch_add(ref="d1==2", mode="expr")["status"] == "ok"
    assert s.regpoint_add(condition="d1==2")["code"] == "no_channel"
    assert [(d.kind, d.ref) for d in arming.store().declarations()] == [
        ("breakpoint", "0x4a0"), ("regpoint", "d0==1"), ("watch", "d1==2")]


def test_the_regpoint_list_and_the_re_arm_reach_past_one_they_set_aside(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A condition this table makes ambiguous, two that are one row, and a plain one LAST."""
    ses = _running(monkeypatch, tmp_path)
    for condition in ("d0==Frame", "d0==Lives", "d0==Lives_Alias", "d1==7fff"):
        arming.store().add(dec.Declaration("regpoint", "expr", condition, origin="s0"))
    use_table(monkeypatch, table={"FRAME": 0x100, "LIVES": 0x2031FC,
                                  "LIVES_ALIAS": 0x2031FC})
    ses.rplist_rows, ses.rp_next_index = [(4, "d0==0x2031fc", True)], 5
    monkeypatch.setattr(mstate.STATE, "machine_map", {"spaces": [
        {"cpu": ":maincpu", "space": "program", "address_mask": 0xFFFFFF}]})
    out: dict[str, list[object]] = {"rearmed": [], "unresolved": [], "unarmable": []}
    regpoints.rearm(ses, out)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["d0==Lives", "d1==7fff"], out
    assert [u["ref"] for u in out["unarmable"]] == [  # type: ignore[index]
        "d0==Frame", "d0==Lives_Alias"]
    states = [(r["ref"], r["state"]) for r in s.declaration_list("regpoint")["regpoints"]]
    assert states[0] == ("d0==Frame", "unresolved") and states[3] == ("d1==7fff", "armed")


def test_a_regpoint_index_is_hex_from_the_answer_to_the_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.rp_next_index = 0x1F
    out = s.regpoint_add(condition="d1==7fff")
    assert out["armed"] is True and out["index"] == 0x1F, out


def test_a_regpoint_list_on_a_running_machine_is_dated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.regpoint_add(condition="d1==7fff")
    ses.running = True
    out = s.declaration_list("regpoint")
    assert out["session"]["running"] is True and out["last_stop"] == mstate.STATE.as_of()
    assert "pc" in out["last_stop"], "dated by a stop the list read at"


# ------------------------------------------------------------------ the re-arm at start


def _next_start(monkeypatch: pytest.MonkeyPatch, ses: _RunningSession) -> None:
    ses.commands.clear()
    ses.armed.clear()
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    monkeypatch.setattr(mstate.STATE, "controls", {})
    monkeypatch.setattr(mstate.STATE, "regpoints", {})


def test_a_re_arm_goes_on_past_every_declaration_it_cannot_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """One of each thing the pass sets aside, and a plain breakpoint LAST: it is reached."""
    ses = _watching(monkeypatch, tmp_path)
    store = arming.store()
    store.add(dec.Declaration("regpoint", "expr", "d1==7fff", origin="s0"))
    store.add(dec.Declaration("watch", "address", "0x203400", width=2, fmt="u16",
                              watch_mode="show", origin="s0", fingerprint="fp-test"))
    store.add(dec.Declaration("watch", "pointer", "[0x203600]+0x4", width=2, fmt="u16",
                              watch_mode="change", origin="s0",
                              fingerprint="fp-test"))       # a null pointer
    store.add(dec.Declaration("breakpoint", "symbol", "scene_id", origin="s0"))   # unresolved
    store.add(dec.Declaration("breakpoint", "address", "0x400", role="control",
                              origin="s0", fingerprint="fp-test"))
    store.add(dec.Declaration("breakpoint", "symbol", "copy_in_rom", role="control",
                              origin="s0", fingerprint="fp-test"))
    store.add(dec.Declaration("breakpoint", "address", "0x4b0", condition="d0==1",
                              origin="s0", fingerprint="fp-test"))
    store.add(dec.Declaration("breakpoint", "address", "0x4c0", origin="s0", fingerprint="fp-test"))
    ses.bplist_rows.append("    7 @ 0004B0 if d0==2")      # another condition: set aside
    ses.bp_next_index = 8
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["evaluated"]) == ["0x203400"] and refs(out["unresolved"]) == ["scene_id"]
    assert [u["ref"] for u in out["unarmable"]] == ["[0x203600]+0x4", "copy_in_rom", "0x4b0"], out
    assert all(set(u) == IDENTITY_KEYS | {"why"} and u["why"] for u in out["unarmable"])
    assert refs(out["rearmed"]) == ["0x400", "0x4c0"], "the last one was reached"
    # EACH REF OWNS THE ROW IT PLACED, by that row's index: the control's, armed through the
    # console in the pass, and the plain one's, sent by the stub and read back after it.
    rows = {r["index"]: r for r in mlists.bp_held(ses)}  # type: ignore[arg-type]
    owned = {rec["owner"][0]: (i, rec["addr"]) for i, rec in mstate.STATE.breakpoints.items()}
    assert owned == {"0x400": (owned["0x400"][0], 0x400),
                     "0x4c0": (owned["0x4c0"][0], 0x4C0)}, owned
    assert {rows[i]["addr"] for i, _a in owned.values()} == {0x400, 0x4C0}
    assert mstate.STATE.controls[("0x400", ":maincpu")]["index"] == owned["0x400"][0]


def test_a_listed_row_adopted_at_start_is_owned_and_the_pass_goes_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    s.breakpoint_at(ref="0x4b0")
    _next_start(monkeypatch, ses)
    ses.bplist_rows[:] = ["    1 @ 0004A0"]                # the debugger kept one of the two
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["0x4a0", "0x4b0"] and ses.armed == [(0x4B0, False)], out
    assert [(b["ref"], b["state"]) for b in s.declaration_list("breakpoint")["breakpoints"]] == [
        ("0x4a0", "armed"), ("0x4b0", "armed")]
    assert breakpoints.breakpoint_name(0x4A0, ":maincpu") == "breakpoint at 0x4a0"


def test_a_control_a_plain_row_blocks_is_unarmable_and_the_pass_goes_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    for ref, role in (("0x4a0", "control"), ("0x4b0", "stop")):
        arming.store().add(dec.Declaration("breakpoint", "address", ref, role=role,
                                           origin="s0", fingerprint="fp-test"))
    ses.bplist_rows.append("    1 @ 0004A0")               # typed through `debug`: no counter
    ses.bp_next_index = 2
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert [u["ref"] for u in out["unarmable"]] == ["0x4a0"], out
    assert refs(out["rearmed"]) == ["0x4b0"], out
    assert "not a counting control" in out["unarmable"][0]["why"]


def test_a_second_stored_tally_on_a_range_is_unarmable_at_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    for by, ref in (("symbol", "frame_lo"), ("address", "0x2031fc")):
        arming.store().add(dec.Declaration("watch", by, ref, width=4, fmt="u32",
                                           watch_mode="count", fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["frame_lo"], out
    assert "already has a tally declared under 'frame_lo'" in out["unarmable"][0]["why"]


def test_a_watch_re_armed_at_start_knows_where_its_bytes_are_read_from(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Both ways a watch comes back: a row the debugger kept, and a `Z2` sent again."""
    ses = _watching(monkeypatch, tmp_path)
    arming.store().add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                                       watch_mode="change", origin="s0", fingerprint="fp-test"))
    arming.store().add(dec.Declaration("watch", "address", "0x203500", width=2, fmt="u16",
                                       watch_mode="change", origin="s0", fingerprint="fp-test"))
    ses.wplist_rows.append("    1 @ 2031FC-2031FF write")
    ses.wp_next_index = 2
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["frame_lo", "0x203500"], out
    assert [(w["ref"], w["values_from"]) for w in s.declaration_list("watch")["watches"]] == [
        ("frame_lo", "memory"), ("0x203500", "memory")]


def test_a_stored_watch_sharing_a_byte_with_an_adopted_one_is_unarmable_and_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row the debugger already lists is adopted first; a stored change watch over any byte of
    it is not armed, says so, and stays in the store."""
    ses = _watching(monkeypatch, tmp_path)
    for by, ref, width, fmt in (("symbol", "frame_lo", 4, "u32"),
                                ("address", "0x2031fe", 2, "u16")):
        arming.store().add(dec.Declaration("watch", by, ref, width=width, fmt=fmt,
                                           watch_mode="change", origin="s0",
                                           fingerprint="fp-test"))
    ses.wplist_rows.append("    1 @ 2031FC-2031FF write")
    ses.wp_next_index = 2
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["frame_lo"] and ses.watchpoints == [], out
    assert "shares a byte with a range already armed under 'frame_lo'" in (
        out["unarmable"][0]["why"]), out
    assert [d.ref for d in arming.store().declarations()] == ["frame_lo", "0x2031fe"]

def test_a_stored_watch_whose_range_an_adopted_one_holds_is_unarmable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    for by, ref in (("symbol", "frame_lo"), ("address", "0x2031fc")):
        arming.store().add(dec.Declaration("watch", by, ref, width=4, fmt="u32",
                                           watch_mode="change", origin="s0",
                                           fingerprint="fp-test"))
    ses.wplist_rows.append("    1 @ 2031FC-2031FF write")
    ses.wp_next_index = 2
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["frame_lo"] and ses.watchpoints == [], out
    assert "already armed under 'frame_lo'" in out["unarmable"][0]["why"]


# ------------------------------------------------------------------ whose stop it is


def _stop_on_a_watch(ses: object, tmp_path: Path, packet: str, lines: str) -> dict[str, object]:
    (tmp_path / "debug.log").write_text("F2034\nData dumped successfully\n")
    s.resume()
    (tmp_path / "debug.log").open("a").write(lines)
    ses.next_packet = packet  # type: ignore[attr-defined]
    ses.stops_after_polls = 1  # type: ignore[attr-defined]
    return dict(s.status())


def test_a_watch_stop_with_no_packet_is_attributed_by_the_consoles_hex_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    ses.wp_next_index = 0x1F
    s.watch_add(ref="frame_lo", mode="change", length=4)
    line = STOP_LINE.replace("watchpoint 1 ", "watchpoint 1F ")
    st = _stop_on_a_watch(ses, tmp_path, "T05", line + "25F6\n")
    assert str(st["stopped_on_its_own"]["cause"]).startswith("watch frame_lo: ")  # type: ignore[index]


def test_a_foreign_watchs_line_is_told_from_an_armed_one_by_its_hex_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The log holds a line of this server's watch 0x10 and then one of a foreign 0x11: the stop
    is the newest line's, the foreign one's, told apart by its index read as hex."""
    ses = _watching(monkeypatch, tmp_path)
    ses.wp_next_index = 0x10
    s.watch_add(ref="frame_lo", mode="change", length=4)
    lines = (STOP_LINE.replace("watchpoint 1 ", "watchpoint 10 ")
             + STOP_LINE.replace("watchpoint 1 ", "watchpoint 11 "))
    st = _stop_on_a_watch(ses, tmp_path, "T05watch:0;11:0000040e;", lines)
    how = str(st["stopped_on_its_own"]["cause"])  # type: ignore[index]
    assert how.startswith("watch 11 at ") and "did not arm" in how, how
    assert how.endswith('`debug("wpclear 0x11")` removes it'), how


def test_a_watch_stop_reads_the_watchpoints_index_as_hex(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    ses.wp_next_index = 0x1F
    s.watch_add(ref="frame_lo", mode="change", length=4)
    line = STOP_LINE.replace("watchpoint 1 ", "watchpoint 1F ")
    st = _stop_on_a_watch(ses, tmp_path, "T05watch:2031fc;11:0000040e;", line + "25F6\n")
    hit = mstate.STATE.last_stop["watch_hit"]
    assert st["stopped_on_its_own"]["cause"].startswith("watch frame_lo: ")  # type: ignore[index]
    assert hit["index"] == 0x1F and hit["lines"] == [line.strip()] and hit["writes_total"] == 1


def test_a_stop_one_past_a_watchs_range_is_not_that_watchs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    st = _stop_on_a_watch(ses, tmp_path, "T05watch:203200;11:0000040e;", "25F6\n")
    assert "frame_lo" not in st["stopped_on_its_own"]["cause"]  # type: ignore[index]


def test_a_watch_stop_with_no_console_line_says_which_is_not_known(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Without the console's line for the stop no row can be named: the stop says so and claims
    no hit, even with one watch armed, since a row typed through `debug` stops the machine the
    same way."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    st = _stop_on_a_watch(ses, tmp_path, "T05watch:0;11:0000040e;", "25F6\n")
    how = str(st["stopped_on_its_own"]["cause"])  # type: ignore[index]
    assert "logged no line for it" in how and "frame_lo" not in how, how
    assert mstate.STATE.last_stop.get("watch_hit") is None


@pytest.mark.parametrize("over, truncated", [(0, False), (1, True)])
def test_a_watch_stop_holds_exactly_its_ceiling_of_writes_untruncated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, over: int, truncated: bool,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    count = watches.WRITES_MAX + over
    _stop_on_a_watch(ses, tmp_path, "T05watch:2031fc;11:0000040e;", STOP_LINE * count)
    hit = mstate.STATE.last_stop["watch_hit"]
    assert (hit["writes_total"], hit["truncated"]) == (count, truncated)
    assert len(hit["writes"]) == watches.WRITES_MAX


def test_an_inherited_watchs_stop_keeps_its_name_in_front_of_the_clause(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    arming.store().add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                                       watch_mode="change", origin="s0",
                                       fingerprint="fp-test"))
    rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    st = _stop_on_a_watch(ses, tmp_path, "T05watch:2031fc;11:0000040e;", STOP_LINE)
    how = str(st["stopped_on_its_own"]["cause"])  # type: ignore[index]
    assert how.startswith("watch frame_lo: 0x002031fc written by") and "PERSISTENT" in how


def test_a_foreign_breakpoints_stop_reads_its_index_as_hex(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0x400])
    ses.bplist_rows.append("   1F @ 000400")
    (tmp_path / "debug.log").write_text("F2034\n")
    s.resume()
    (tmp_path / "debug.log").open("a").write("Stopped at breakpoint 1F\n400\n")
    ses.stops_after_polls = 1
    how = str(s.status()["stopped_on_its_own"]["cause"])
    assert how == ("breakpoint 1F at 0x00000400, typed through `debug`: `debug(\"bpclear 0x1f\")` "
                   "removes it"), how


def test_a_foreign_breakpoints_stop_whose_list_cannot_be_read_spells_its_index_the_same(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0x400])
    (tmp_path / "debug.log").write_text("F2034\n")
    s.resume()
    (tmp_path / "debug.log").open("a").write("Stopped at breakpoint 1F\n400\n")
    ses.stops_after_polls = 1

    def unreadable(ses: object) -> list[dict[str, object]]:
        raise gs.SessionError("the console did not answer `bplist`")

    monkeypatch.setattr(mlists, "bp_held", unreadable)
    how = str(s.status()["stopped_on_its_own"]["cause"])
    assert how == ("breakpoint 1F at 0x00000400; the debugger's list could not be read to say "
                   "whose: the console did not answer `bplist`"), how


# ------------------------------------------------------------------ the store


def test_an_adopted_declaration_keeps_everything_but_who_and_when() -> None:
    watch = dec.Declaration("watch", "symbol", "frame", width=4, fmt="u32", watch_mode="change")
    control = dec.Declaration("breakpoint", "address", "0x4a0", role="control")
    for decl in (watch, control):
        adopted = decl.adopted_by("s2", "t2", "fp2")
        assert adopted == decl, "the same declaration"
        assert (adopted.width, adopted.fmt, adopted.watch_mode, adopted.role) == (
            decl.width, decl.fmt, decl.watch_mode, decl.role)
        assert (adopted.origin, adopted.created_at, adopted.fingerprint) == ("s2", "t2", "fp2")


def test_a_declaration_made_again_with_no_stamp_keeps_the_one_it_had(tmp_path: Path) -> None:
    store = dec.DeclarationStore("m68k game.yaml", tmp_path / "d.json")
    store.add(dec.Declaration("breakpoint", "address", "0x4a0", origin="s1", created_at="t1",
                              fingerprint="fp1"))
    assert store.add(dec.Declaration("breakpoint", "address", "0x4a0", origin="s2")) is False
    (held,) = store.declarations()
    assert (held.origin, held.created_at, held.fingerprint) == ("s2", "t1", "fp1")
    new = dec.Declaration("breakpoint", "address", "0x4a0", condition="d0==1", origin="s3",
                          created_at="t3", fingerprint="fp3")
    store.replace(held, new)
    (held,) = store.declarations()
    assert (held.origin, held.created_at, held.fingerprint) == ("s3", "t3", "fp3")
    store.replace(held, dec.Declaration("breakpoint", "address", "0x4a0", condition="d0==2"))
    (held,) = store.declarations()
    assert (held.condition, held.origin, held.created_at, held.fingerprint) == (
        "d0==2", "s3", "t3", "fp3")


def test_an_expr_watch_refuses_a_width_alone_and_a_format_alone() -> None:
    for width, fmt in ((2, None), (None, "u16")):
        with pytest.raises(dec.DeclarationError, match="expr"):
            dec.Declaration("watch", "expr", "d0+1", watch_mode="expr", width=width, fmt=fmt)


def test_the_watch_refusals_look_past_a_watch_of_another_ref() -> None:
    store = dec.DeclarationStore("test", path=None)
    store.add(dec.Declaration("watch", "address", "0x203200", width=2, fmt="u16",
                              watch_mode="change"))
    store.add(dec.Declaration("watch", "address", "0x2031fc", width=4, fmt="u32",
                              watch_mode="change"))
    with pytest.raises(dec.DeclarationError, match="not be both change AND show"):
        store.refuse_conflict(dec.Declaration("watch", "address", "0x2031FC", width=4,
                                              fmt="u32", watch_mode="show"))


def test_the_store_makes_its_folder_and_writes_beside_the_file_it_replaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    path = tmp_path / "state" / "mame-debug" / "declarations.json"
    moved: list[tuple[Path, Path]] = []
    real = os.replace

    def recorded(src: str, dst: str) -> None:
        moved.append((Path(src).parent, Path(dst)))
        real(src, dst)

    monkeypatch.setattr(os, "replace", recorded)
    dec.DeclarationStore("m68k game.yaml", path).add(
        dec.Declaration("breakpoint", "address", "0x4a0"))
    assert moved == [(path.parent, path)], "a rename is atomic only inside one folder"
    assert list(json.loads(path.read_text())) == ["m68k game.yaml"]
    assert [p.name for p in path.parent.iterdir()] == ["declarations.json"]


def test_a_pasted_clear_spells_the_index_with_0x_because_the_console_evaluates_it() -> None:
    """The console evaluates a clear's argument as an expression, so a bare `D0` (a 68000
    register) or `A` (a Z80 register) names the register's value and not the row: every
    pasted `bpclear`/`wpclear`/`rpclear` carries `0x`, while the row quoted from the list
    keeps the list's own spelling."""
    assert mclear.pasted_clear("breakpoint", 0xD0) == '`debug("bpclear 0xd0")`'
    assert mclear.pasted_clear("registerpoint", 0xA) == '`debug("rpclear 0xa")`'
    assert mclear.clear_command("watch", 0xA) == "wpclear 0xa", "what the server sends"
    how = mclear.foreign_row_cause("breakpoint", 0xD0, " at 0x000400")
    assert how == 'breakpoint D0 at 0x000400: `debug("bpclear 0xd0")` removes it', how
    how = mclear.foreign_row_cause("registerpoint", 0xA, " (if d1==7fff)")
    assert how.endswith('`debug("rpclear 0xa")` removes it'), how
    note = mclear.still_held_note("watch", [("A @ 2031FC-2031FF write", 0xA)])
    assert "['A @ 2031FC-2031FF write']" in note, note
    assert '`debug("wpclear 0xa")` removes the row' in note, note
    assert "wpclear A" not in note and "bpclear D0" not in how
    assert mclear.foreign_row_cause("watch", 0xD0, " at 0x2031fc").endswith(
        '`debug("wpclear 0xd0")` removes it')
    assert '`debug("bpclear 0xa")`' in mclear.still_held_note("breakpoint", [("A @ 0004A0", 0xA)])
