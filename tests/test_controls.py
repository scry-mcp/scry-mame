"""The CONTROL is a declared breakpoint that MAME counts and never stops on.

It makes a zero mean something: a target that never fires reads like a breakpoint that cannot
fire unless something known to be hot proves the mechanism. The shape is MAME's own, a
breakpoint whose condition counts and never comes true, `bp <addr>,(++temp0)==0`, read with
`print temp0`. The doubles answer console shapes captured from a real board.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from server_support import _RegisterSession, _running, _RunningSession  # noqa: E402
from session_doubles import (
    bp_records,
    bplist_add,
    bplist_answer,
    captured,
    control_console,
    debugger_lists,
    refs,
    refused,
    row_index,
    use_table,  # noqa: E402
    wplist_answer,
)
from test_watches import WPLIST_ONE  # noqa: E402

from scry_mame import (
    arming,  # noqa: E402
    breakpoints,  # noqa: E402
    conditions,  # noqa: E402
    inputs,  # noqa: E402
    running,  # noqa: E402
)
from scry_mame import console as mconsole  # noqa: E402
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import gdb_session as gs  # noqa: E402
from scry_mame import lists as mlists  # noqa: E402
from scry_mame import read as mame_read  # noqa: E402
from scry_mame import rearm as rearming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

# CAPTURED from a real console (`fixtures/console/PROVENANCE.txt`): the action row of
# `bplist.action.txt`, armed with the action in braces as the documentation writes it, and
# the conditioned rows of `bplist.by-address.txt`. Nothing here is authored.
BPLIST_ACTION = captured("bplist.action.txt")
BPLIST_CONDITIONED = captured("bplist.by-address.txt")


def _controlled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                pcs: list[int] | None = None) -> _RunningSession:
    return _running(monkeypatch, tmp_path, _RunningSession(tmp_path, pcs))


def _bps_sent(ses: _RunningSession) -> int:
    """How many `bp`s the console took, stop or control."""
    return sum(c.startswith("bp ") for c in ses.commands)


def _console_bps(ses: _RunningSession) -> list[str]:
    """The conditioned `bp`s the console took: a control's and a conditioned stop's."""
    return [c for c in ses.commands if c.startswith("bp ") and "," in c]


# ------------------------------------------------------------------ the declaration


def test_a_breakpoint_declaration_carries_a_role_and_a_watch_refuses_one() -> None:
    plain = dec.Declaration("breakpoint", "symbol", "irq_vblank")
    assert plain.role == "stop", "a breakpoint with no role named is one that stops"
    control = dec.Declaration("breakpoint", "address", "0x4a0", role="control")
    assert control.role == "control"
    assert dec.Declaration.from_dict(control.to_dict()) == control
    assert "role" not in plain.to_dict(), "the default role is not written to the store"
    assert dec.Declaration.from_dict(plain.to_dict()).role == "stop"
    with pytest.raises(dec.DeclarationError, match="role"):
        dec.Declaration("breakpoint", "address", "0x4a0", role="counter")
    with pytest.raises(dec.DeclarationError, match="role"):
        dec.Declaration("watch", "address", "0x4a0", width=2, fmt="u16", watch_mode="show",
                        role="control")


def test_a_stop_and_a_control_under_one_ref_are_not_the_same_declaration() -> None:
    store = dec.DeclarationStore("test", path=None)
    assert store.add(dec.Declaration("breakpoint", "address", "0x4a0"))
    with pytest.raises(dec.DeclarationError, match="stop"):
        store.add(dec.Declaration("breakpoint", "address", "0x4a0", role="control"))


# ------------------------------------------------------------------ the console's list


def test_bplist_rows_with_a_condition_or_an_action_parse_and_keep_them() -> None:
    """The captured action row keeps the text after `do`; a condition of `1` prints no `if`."""
    assert mlists.parse_bplist(BPLIST_ACTION) == [
        {"index": 1, "addr": 0x25A4, "cpu": ":maincpu", "enabled": True,
         "entry": "1 @ 0025A4 do temp0++ ; g", "condition": None, "action": "temp0++ ; g"}]
    rows = mlists.parse_bplist(BPLIST_CONDITIONED)
    assert [(r["index"], r["addr"]) for r in rows] == [(2, 0x400), (1, 0x4A0)]
    assert rows[1]["condition"] == "(++temp0)==0" and rows[1]["action"] is None
    assert rows[1]["entry"] == "1 @ 0004A0 if (++temp0)==0"
    assert mlists.parse_bplist("Device ':maincpu' breakpoints:\n    1 @ 000400\n\n")[0] == {
        "index": 1, "addr": 0x400, "cpu": ":maincpu", "enabled": True, "entry": "1 @ 000400",
        "condition": None, "action": None}


CONSOLE = Path(__file__).parent / "fixtures" / "console"


def _hard_cut_cond(name: str) -> str:
    """The condition of a captured at-limit row: its pieces after `if`, joined with nothing."""
    pieces = [p for p in (CONSOLE / name).read_text().split("\n") if p]
    tail = []
    for p in pieces[2:]:
        tail.append(p)
        if len(p) < len(pieces[2]):
            break
    cond = "".join(tail)
    assert cond.startswith("d0==0x") and cond.endswith("1") and " " not in cond
    return cond


def test_bplist_reads_a_wrapped_row_whole() -> None:
    cond = _hard_cut_cond("bplist.at-limit.txt")
    rows = mlists.parse_bplist((CONSOLE / "bplist.at-limit.txt").read_text())
    assert [(r["index"], r["addr"], r["condition"]) for r in rows] == [(4, 0x400, cond)]
    two = mlists.parse_bplist((CONSOLE / "bplist.two-rows.txt").read_text())
    assert [(r["index"], r["addr"], r["condition"]) for r in two] == [
        (7, 0x400, cond), (8, 0x404, "d0==1")], "the short row beside it is not dropped"
    late = mlists.parse_bplist((CONSOLE / "bplist.space-late.txt").read_text())
    assert late[0]["condition"] == "d0==0x" + "0" * 220 + "1 || d1==0x1", "the space comes back"
    short = mlists.parse_bplist((CONSOLE / "bplist.row249.txt").read_text())
    assert short[0]["condition"] == "d0==0x" + "0" * 224 + "1"


def test_bplist_with_a_line_it_does_not_recognise_is_refused_naming_it() -> None:
    with pytest.raises(mstate.Invalid, match="Unexpected thing"):
        mlists.parse_bplist("Unexpected thing\n" + BPLIST_ACTION)
    with pytest.raises(mstate.Invalid, match="5 things happened"):
        mlists.parse_bplist("Device ':maincpu' breakpoints:\n    1 @ 000400 if d0==1\n"
                            "5 things happened\n\n")


# ------------------------------------------------------------------ declaring a control


def test_a_control_is_armed_through_the_console_as_a_counting_condition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    out = s.breakpoint_at(ref="0x25a4", role="control")
    assert out["status"] == "ok" and out["role"] == "control" and out["armed"] is True
    assert out["temp"] == "temp0" and out["entry"] == "1 @ 0025A4 if (++temp0)==0"
    assert _console_bps(ses) == ["bp 0x25a4::maincpu,(++temp0)==0"]
    assert ses.armed == [], "a control is never a stub breakpoint: no Z0 went out"
    second = s.breakpoint_at(ref="0x4a0", role="control")
    assert second["temp"] == "temp1", "each control owns one of the debugger's temp variables"
    again = s.breakpoint_at(ref="0x25a4", role="control")
    assert again["already_stored"] is True and again["temp"] == "temp0"
    assert len(_console_bps(ses)) == 2, "a re-declaration adopts, it does not stack a row"
    listed = s.declaration_list("breakpoint")
    by_ref = {b["ref"]: b for b in listed["breakpoints"]}
    assert by_ref["0x25a4"]["role"] == "control" and by_ref["0x25a4"]["state"] == "armed"
    assert by_ref["0x25a4"]["hits_since_armed"] == 0
    assert "hits_total" not in by_ref["0x25a4"]
    assert "foreign" not in listed


def test_a_control_declared_where_a_stop_is_declared_is_refused_naming_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    assert s.breakpoint_at(ref="0x4a0")["status"] == "ok"
    refused("already declared", s.breakpoint_at(ref="0x4a0", role="control"))
    refused("role", s.breakpoint_at(ref="0x25a4", role="counter"))


def test_the_debugger_has_ten_temps_and_the_eleventh_control_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    for i in range(10):
        assert s.breakpoint_at(ref=f"{0x1000 + i * 2:#x}", role="control")["temp"] == f"temp{i}"
    refused("ten", s.breakpoint_at(ref="0x2000", role="control"))


def _ten_controls(ses: _RunningSession) -> None:
    for i in range(10):
        assert s.breakpoint_at(ref=f"{0x1000 + i * 2:#x}", role="control")["status"] == "ok"


def test_a_control_redeclared_over_its_own_lost_row_takes_its_temp_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Redeclaring a lost control takes the temp its record holds, so the pool stays full."""
    ses = _controlled(monkeypatch, tmp_path)
    _ten_controls(ses)
    ses.bplist_rows = [r for r in ses.bplist_rows if not r.endswith("@ 001006 if (++temp3)==0")]
    states = [b["state"] for b in s.declaration_list("breakpoint")["breakpoints"]]
    assert states.count("gone") == 1, states
    sent = len(ses.commands)
    again = s.breakpoint_at(ref="0x1006", role="control")
    assert again["status"] == "ok" and again["temp"] == "temp3", again
    assert "temp3 = 0" in ses.commands[sent:], "the count it held is zeroed before it counts"
    refused("ten", s.breakpoint_at(ref="0x2000", role="control"))   # still ten, none to spare


# THE ARMING'S OWN REFUSALS, each with the console as it stands then: the eleventh control finds
# no free temp, a plain row where a control is declared is not one, and a stop meets a row under
# another condition.
_REFUSED_ARMINGS: dict[str, tuple[Callable[[_RunningSession], None], str, dict[str, str], str]] = {
    "no free temp": (_ten_controls, "0x2000", {"role": "control"}, "ten temp variables"),
    "a plain row": (lambda ses: ses.bplist_rows.append("    1 @ 0025A4"), "0x25a4",
                    {"role": "control"}, "not a counting control"),
    "another condition": (lambda ses: ses.bplist_rows.append("    3 @ 0004A0 if d0==1"), "0x4a0",
                          {"condition": "d1==2"}, "another condition"),
}


@pytest.mark.parametrize("case", sorted(_REFUSED_ARMINGS))
def test_a_breakpoint_the_arming_refuses_is_never_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str,
) -> None:
    """A refusal leaves no state: neither listed `gone` nor carried into the next `start`."""
    console_as, ref, kw, said = _REFUSED_ARMINGS[case]
    ses = _controlled(monkeypatch, tmp_path)
    console_as(ses)
    before = [d.ref for d in arming.store().declarations()]
    refused(said, s.breakpoint_at(ref=ref, **kw))
    assert [d.ref for d in arming.store().declarations()] == before, "the refusal stored it"
    listed = s.declaration_list("breakpoint")["breakpoints"]
    assert ref not in [b["ref"] for b in listed] and all(b["state"] != "gone" for b in listed)


def test_the_double_numbers_its_bplist_rows_as_mame_prints_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The tenth index lists as `A` right-aligned in four; clearing it drops that row."""
    ses = _controlled(monkeypatch, tmp_path)
    for i in range(10):
        s.breakpoint_at(ref=f"{0x1000 + i * 2:#x}", role="control")
    assert ses.bplist_rows[9].startswith("    A @ 001012 "), ses.bplist_rows[9]
    s.declaration_clear("breakpoint", ref="0x1012")
    assert "bpclear 0xa" in ses.commands
    assert len(ses.bplist_rows) == 9 and not any(" A @ " in r for r in ses.bplist_rows)


def test_the_double_never_reuses_a_breakpoint_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """MAME's breakpoint index only increments, even when the list is empty again."""
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4", role="control")
    s.declaration_clear("breakpoint", ref="0x25a4")
    s.breakpoint_at(ref="0x4a0", role="control")
    assert ses.bplist_rows == ["    2 @ 0004A0 if (++temp0)==0"], ses.bplist_rows


def test_every_breakpoint_takes_the_doubles_one_counter(tmp_path: Path) -> None:
    """Every `bp` on any cpu takes the one index, or a `bpclear` of either would take both."""
    for ses in (_RunningSession(tmp_path), _RegisterSession(bits=32, frame=10)):
        control_console(ses, "bp 1000::maincpu")
        control_console(ses, "bp 2000")
        control_console(ses, "bpclear 0x1")
        control_console(ses, "bp 25a4::maincpu")
        assert control_console(ses, "bp 4a0,(++temp0)==0") == "Breakpoint 4 set\n\n"
        assert ses.bplist_rows == ["    2 @ 002000", "    3 @ 0025A4",
                                   "    4 @ 0004A0 if (++temp0)==0"], ses.bplist_rows
        control_console(ses, "bpclear 4")
        assert ses.bplist_rows == ["    2 @ 002000", "    3 @ 0025A4"], ses.bplist_rows


def test_the_list_doubles_rebuild_the_two_device_captures_byte_for_byte() -> None:
    """The list doubles rebuild the two-device captures: one counter, a header per cpu."""
    assert bplist_answer(["    1 @ 000400", "    2 @ 0004A0 if d0==1", "    3 @ 000400"],
                         {3: ":subcpu"}) == captured("bplist.two-devices.txt")
    assert wplist_answer(["    1 @ 203200-203201 write", "    2 @ 008000-008001 write"],
                         {2: ":subcpu"}) == captured("wplist.two-devices.txt")
    assert bplist_answer(["    1 @ 0004A0 if (++temp0)==0", "    2 @ 000400 if temp1++"]
                         ) == captured("bplist.by-address.txt"), "the newer row sits lower"
    ses = SimpleNamespace(bplist_rows=[], bp_next_index=1, bp_devices={3: ":subcpu"}, temps={})
    bplist_add(ses, 0x400)
    control_console(ses, "bp 4a0,d0==1")
    bplist_add(ses, 0x400)
    assert debugger_lists(ses, "bplist") == captured("bplist.two-devices.txt")


def test_a_listed_row_keeps_the_cpu_its_devices_header_names() -> None:
    """Only the `Device` header says whose row it is, so every row carries that cpu (and space)."""
    assert [(r["index"], r["addr"], r["cpu"]) for r in
            mlists.parse_bplist(captured("bplist.two-devices.txt"))] == [
        (1, 0x400, ":maincpu"), (2, 0x4A0, ":maincpu"), (3, 0x400, ":subcpu")]
    assert [(r["index"], r["addr"], r["cpu"], r["space"]) for r in
            mlists.parse_wplist(captured("wplist.two-devices.txt"))] == [
        (1, 0x203200, ":maincpu", "program"), (2, 0x8000, ":subcpu", "program")]
    # One cpu, one header, as every single-cpu capture prints it.
    assert {r["cpu"] for r in mlists.parse_bplist(captured("bplist.by-address.txt"))} == {
        ":maincpu"}
    assert {(r["cpu"], r["space"]) for r in
            mlists.parse_wplist(captured("wplist.action.txt"))} == {(":maincpu", "program")}


def test_the_doubles_bpclear_reads_an_index_wider_than_four_digits() -> None:
    """MAME's `%4X` index widens at the fifth digit; the double's `bpclear` must read it."""
    ses = SimpleNamespace(bplist_rows=[], bp_next_index=0xFFFF, bp_devices=None, temps={})
    bplist_add(ses, 0x400)
    assert control_console(ses, "bp 4a0,d0==1") == "Breakpoint 10000 set\n\n"
    assert ses.bplist_rows[1] == " 10000 @ 0004A0 if d0==1"
    assert [row_index(r) for r in ses.bplist_rows] == [0xFFFF, 0x10000]
    control_console(ses, "bpclear 10000")
    assert ses.bplist_rows == [" FFFF @ 000400"], ses.bplist_rows
    control_console(ses, "bpclear FFFF")
    assert ses.bplist_rows == []


def test_the_doubles_bpclear_answers_a_number_no_row_holds_as_the_console_does() -> None:
    """An unheld index answers `Invalid breakpoint number N`, not `cleared`."""
    ses = SimpleNamespace(bplist_rows=[], bp_next_index=1, bp_devices=None, temps={})
    bplist_add(ses, 0x400)
    assert control_console(ses, "bpclear 7") == captured("bpclear.invalid.txt")
    assert control_console(ses, "bpclear a") == "Invalid breakpoint number A\n\n", (
        "the index spelled `%X`, as `bpset` and `bpclear` print it")
    assert [row_index(r) for r in ses.bplist_rows] == [1], "and nothing was dropped"
    assert control_console(ses, "bpclear 1") == "Breakpoint 1 cleared\n\n"


def test_clearing_a_control_goes_through_the_console_and_frees_its_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4", role="control")
    out = s.declaration_clear("breakpoint", ref="0x25a4")
    assert out["disarmed"] == ["1 @ 0025A4 if (++temp0)==0"] and out["declarations_cleared"] == 1
    assert "bpclear 0x1" in ses.commands and ses.armed == []
    assert s.breakpoint_at(ref="0x4a0", role="control")["temp"] == "temp0", "the temp is free again"


def test_clearing_a_disabled_control_takes_its_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`bpclear N` clears a disabled row too; its leading `D` is not part of the index."""
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4", role="control")
    ses.bplist_rows[0] = "D" + ses.bplist_rows[0][1:]
    s.declaration_clear("breakpoint", ref="0x25a4")
    assert "bpclear 0x1" in ses.commands and ses.bplist_rows == [], ses.bplist_rows


# ------------------------------------------------------------------ run_to over a control


def test_run_to_arms_only_the_target_and_reads_the_control_off_its_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0x4A0])
    s.breakpoint_at(ref="0x25a4", role="control")
    ses.temps[0] = 7                      # what the counter already holds from earlier runs
    ses.stops_after_polls = 1
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] += 30                # the control fires while the machine runs

    ses.go = go  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0)
    assert out["status"] == "ok" and out["verdict"] == "TARGET"
    assert out["control_hits"] == 30
    assert out["controls"] == [{"ref": "0x25a4", "cpu": ":maincpu", "hits_in_run": 30}]
    assert ses.armed == [(0x4A0, False), (0x4A0, True)], "the target alone, armed and removed"
    assert out["cause"] == "target 0x4a0"


def test_run_to_with_a_control_argument_declares_it_and_then_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0x4A0])
    ses.stops_after_polls = 1
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 3

    ses.go = go  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0)
    assert out["verdict"] == "TARGET" and out["control_hits"] == 3
    held = [d for d in arming.store().declarations() if d.kind == "breakpoint"]
    assert [(d.ref, d.role) for d in held] == [("0x25a4", "control")], "declared, and kept"
    assert _console_bps(ses) == ["bp 0x25a4::maincpu,(++temp0)==0"]
    ses.stop_count, ses.stops_after_polls = 0, 1
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0)
    assert out["control_hits"] == 3 and len(_console_bps(ses)) == 1, "the second run adopts it"


def _finds_a_stop_on_the_way_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first contact of the next call finds a stop the machine reached on its own."""
    real = running.observe_stop
    seen: list[int] = []

    def observe(ses_: Any, scratch: Path) -> None:
        real(ses_, scratch)
        if not seen:
            seen.append(1)
            mstate.STATE.found_stop_last = {"stop_seq": 9, "pc": "0x00000500", "cause": "found"}

    monkeypatch.setattr(running, "observe_stop", observe)


def test_a_stop_found_on_the_way_in_rides_on_run_to_when_it_declares_its_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The found stop's account survives `run_to(control=...)` dropping `breakpoint_at`'s reply."""
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0x4A0])
    ses.stops_after_polls = 1
    _finds_a_stop_on_the_way_in(monkeypatch)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0)
    assert out["verdict"] == "TARGET" and out["stopped_on_its_own"]["stop_seq"] == 9, out
    listed = s.declaration_list("breakpoint")
    assert "stopped_on_its_own" not in listed, "reported once, by that call"


def test_a_stop_found_by_a_call_that_escapes_is_not_reported_by_the_next_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An exception in one handler never reaches a sibling, so the account drops in a `finally`."""
    _controlled(monkeypatch, tmp_path)
    _finds_a_stop_on_the_way_in(monkeypatch)

    def refuses(*_a: Any, **_k: Any) -> None:
        raise mstate.Invalid("bad_argument", "refused")

    def bug(_name: str) -> None:
        raise ValueError("bug")

    monkeypatch.setattr(mame_read, "read_memory", refuses)
    monkeypatch.setattr(running, "record_own_stop", bug)
    with pytest.raises(ValueError, match="bug"):
        s.read_memory(ref="0x400")
    out = s.status()
    assert out["session"]["alive"] is True and "stopped_on_its_own" not in out, out


@pytest.mark.parametrize("control", ["", "   "])
def test_run_to_with_an_empty_control_is_refused_before_the_machine_moves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, control: str,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4", role="control")        # declared, and still not enough
    refused("no control is named", s.run_to(ref="0x4a0", control=control, seconds=2.0))
    assert ses.armed == [] and not ses.running


def test_run_to_that_times_out_with_a_silent_control_is_invalid_and_a_hot_one_measures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from scry_mame import advance
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0x1000])
    s.breakpoint_at(ref="0x25a4", role="control")
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "INVALID" and out["code"] == "control_silent"
    assert out["control_hits"] == 0 and "control_dasm" in out and ses.interrupted == 1
    ses.stop_count, ses.interrupted = 0, 0
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = 50                 # the control counts while the machine runs

    ses.go = go  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT" and out["control_hits"] == 50


def test_a_control_and_a_target_at_one_address_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0", role="control")
    refused("same address", s.run_to(ref="0x4a0", control="0x4a0", seconds=1.0))


# ------------------------------------------------------------------ across sessions


def test_a_control_declaration_re_arms_through_the_console_at_the_next_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    arming.store().add(dec.Declaration("breakpoint", "address", "0x25a4", role="control",
                                       origin="s1", fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["0x25a4"]
    assert _console_bps(ses) == ["bp 0x25a4::maincpu,(++temp0)==0"]
    assert ses.armed == []
    assert mstate.STATE.controls[("0x25a4", ":maincpu")]["temp"] == 0


def test_the_tool_surface_knows_the_role(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`run_to`'s `control` is required with a ref, and `breakpoint_at` takes a `role`."""
    import inspect
    refused_without = s.run_to(ref="0x4a0")
    assert refused_without["status"] == "INVALID" and "no control is named" in refused_without[
        "message"], refused_without
    assert inspect.signature(s.breakpoint_at).parameters["role"].default == "stop"
    _controlled(monkeypatch, tmp_path)
    assert "role" in (s.breakpoint_at(ref="0x4a0"))
    assert s.breakpoint_at(ref="0x4a2")["role"] == "stop"



# ------------------------------------------------------------------ the refusal branches


def test_run_to_returns_a_control_refusal_and_refuses_an_unresolved_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4")                                 # a STOP under that ref
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and "already declared as a stop" in out["message"]
    out = s.run_to(ref="0x4a0", control="no_such_symbol", seconds=1.0)
    assert out["status"] == "INVALID" and out["message"] == inputs.not_a_ref(
        "the control", "no_such_symbol", ":maincpu", then=(
            ", so nothing was declared (a control counts only once it resolves to an address "
            "in this build)")), out
    assert (0x4A0, False) not in ses.armed and not ses.running, "the target was never armed"
    # A control the console takes but does not list: the readback refusal is the run's reply.
    real = ses.monitor

    def swallow(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bp "):
            return "Breakpoint 9 set\n\n"
        return real(command, timeout)

    ses.monitor = swallow  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x600", seconds=1.0)
    assert out["status"] == "INVALID" and out["code"] == "readback_refused"


def _declared() -> list[tuple[str, str]]:
    return [(d.ref, d.role) for d in arming.store().declarations() if d.kind == "breakpoint"]


def test_run_to_with_an_unresolvable_target_declares_no_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    out = s.run_to(ref="NOSUCHSYMBOL", control="0x4a0", seconds=2.0)
    assert out["status"] == "INVALID" and out["code"] == "unknown_ref"
    assert _declared() == [] and _console_bps(ses) == [], "a refused run stores nothing"


def test_run_to_with_an_unresolvable_control_declares_nothing_and_a_resolvable_one_still_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0x4A0])
    out = s.run_to(ref="0x4a0", control="NOSUCHCONTROL", seconds=2.0)
    assert out["status"] == "INVALID" and out["code"] == "unknown_ref", (
        "a control naming nothing is answered as a target naming nothing is", out)
    assert out["control"] == "NOSUCHCONTROL" and out["message"].startswith(
        "the control 'NOSUCHCONTROL' is neither a symbol of :maincpu's table"), out
    assert _declared() == [] and _console_bps(ses) == [], "a refused run stores nothing"
    ses.stops_after_polls = 1
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0)
    assert out["verdict"] == "TARGET" and _declared() == [("0x25a4", "control")]
    assert "target_disarmed" not in out, "only a run whose interrupt went unanswered says it"


def test_run_to_refuses_a_resolved_control_whose_row_is_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4", role="control")
    ses.bplist_rows[0] = "D" + ses.bplist_rows[0][1:]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and out["code"] == "bad_argument"
    assert "declared but not armed (disabled)" in out["message"] and not ses.running
    assert out["control"] == "0x25a4", out


@pytest.mark.parametrize("role", ["control", "stop"])
@pytest.mark.parametrize("enabled", [False, True])
def test_a_breakpoint_whose_row_is_listed_disabled_is_re_armed_saying_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, enabled: bool, role: str,
) -> None:
    """The re-arm adopts a stop or control row and says a disabled one is, with the enabler."""
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4", role=role)
    if not enabled:
        ses.bplist_rows[0] = "D" + ses.bplist_rows[0][1:]
    sent = _bps_sent(ses)
    mstate.STATE.controls.clear()
    mstate.STATE.breakpoints.clear()
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["0x25a4"] and out["unarmable"] == [], out
    assert _bps_sent(ses) == sent, "the row was adopted, not sent again"
    if enabled:
        assert "state" not in out["rearmed"][0] and "note" not in out["rearmed"][0], out
        return
    assert out["rearmed"][0]["state"] == "disabled", out
    assert 'debug("bpenable 0x1")' in out["rearmed"][0]["note"], out


def test_a_plain_row_at_the_address_is_not_adopted_as_a_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    ses.bplist_rows.append("    1 @ 0025A4")                    # typed through `debug`
    refused("not a counting control", s.breakpoint_at(ref="0x25a4", role="control"))


def test_a_control_the_console_does_not_list_is_readback_refused_here_and_at_rearm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    real = ses.monitor

    def swallow(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bp "):
            ses.commands.append(command)
            return "Breakpoint 1 set\n\n"                       # taken, never listed
        return real(command, timeout)

    ses.monitor = swallow  # type: ignore[method-assign]
    out = s.breakpoint_at(ref="0x25a4", role="control")
    assert out["status"] == "INVALID" and out["code"] == "readback_refused"
    arming.store().add(dec.Declaration("breakpoint", "address", "0x4a0", role="control",
                                       origin="s1", fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert {u["ref"] for u in out["unarmable"]} == {"0x25a4",
                                                    "0x4a0"}, "both were stored, none listed"
    assert all("does not list" in u["why"] for u in out["unarmable"])


def test_two_controls_on_one_address_in_the_store_leave_the_second_unarmable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"HOT": 0x25A4})
    store = arming.store()
    store.add(dec.Declaration("breakpoint", "symbol", "hot", role="control", origin="s1"))
    store.add(dec.Declaration("breakpoint", "address", "0x25a4", role="control", origin="s1",
                              fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["hot"] and [u["ref"] for u in out["unarmable"]] == ["0x25a4"]
    # And a control whose row the console refuses to adopt is unarmable too, by its why.
    ses2 = _controlled(monkeypatch, tmp_path)
    ses2.bplist_rows.append("    1 @ 0025A4")
    arming.store().add(dec.Declaration("breakpoint", "address", "0x25a4", role="control",
                                       origin="s1", fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses2)  # type: ignore[arg-type]
    assert "not a counting control" in out["unarmable"][0]["why"]


def test_control_counts_refuses_a_short_or_non_numeric_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from scry_mame import gdb_session as g
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4", role="control")
    s.breakpoint_at(ref="0x4a0", role="control")
    real = ses.monitor
    answers = {"print temp0,temp1": "7\n"}

    def monitor(command: str, timeout: float = 10.0) -> str:
        return answers.get(command) or real(command, timeout)

    ses.monitor = monitor  # type: ignore[method-assign]
    with pytest.raises(g.SessionError, match="1 value for 2 expressions"):
        breakpoints.control_counts(ses)  # type: ignore[arg-type]
    # A temp the console REFUSES is an answer about the machine, not a broken channel.
    answers["print temp0,temp1"] = ("Error in expression: temp0\n"
                                    "                     ^unknown symbol\n")
    with pytest.raises(g.ExpressionRefused):
        breakpoints.control_counts(ses)  # type: ignore[arg-type]
    answers["print temp0,temp1"] = "x y\n"
    with pytest.raises(g.SessionError, match="numbers"):
        breakpoints.control_counts(ses)  # type: ignore[arg-type]


def test_clearing_one_control_leaves_the_other_and_its_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4", role="control")
    s.breakpoint_at(ref="0x4a0", role="control")
    assert s.declaration_clear("breakpoint", ref="0x25a4")["declarations_cleared"] == 1
    assert set(mstate.STATE.controls) == {("0x4a0", ":maincpu")}
    assert mstate.STATE.controls[("0x4a0", ":maincpu")]["temp"] == 1


# ------------------------------------------------------------------ a condition on a stop
# A stop conditioned by VALUE: `bp addr,w@DemoLen==0x25` in the console's own grammar, which
# turns a stretch of hundreds of round trips into one run. The stub's
# packet carries no condition, so a conditioned row is armed and removed through the console
# like a control, and the declaration keeps the condition.


def test_a_declaration_keeps_its_condition_and_a_control_or_a_non_change_watch_refuses_one(
) -> None:
    cond = dec.Declaration("breakpoint", "address", "0x4a0", condition="w@0x2031fc==0x25")
    assert dec.Declaration.from_dict(cond.to_dict()) == cond
    assert "condition" not in dec.Declaration("breakpoint", "address", "0x4a0").to_dict()
    assert cond != dec.Declaration("breakpoint", "address", "0x4a0"), (
        "another condition, another declaration")
    assert cond.adopted_by("s2", "t2").condition == cond.condition
    with pytest.raises(dec.DeclarationError, match="control"):
        dec.Declaration("breakpoint", "address", "0x4a0", role="control", condition="d0==1")
    watched = dec.Declaration("watch", "address", "0x4a0", watch_mode="change", fmt="u16",
                              condition="(wpdata&3)!=0")
    assert dec.Declaration.from_dict(watched.to_dict()) == watched, "a change watch keeps it"
    assert watched != dataclasses.replace(watched, condition=""), (
        "another condition, another declaration")
    for mode in ("show", "count"):
        with pytest.raises(dec.DeclarationError, match="only a change watch carries a condition"):
            dec.Declaration("watch", "address", "0x4a0", watch_mode=mode, fmt="u16",
                            condition="d0==1")


def test_a_condition_names_the_projects_symbols_and_the_console_gets_addresses(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC, "W": 0x10})
    assert conditions.console_condition("w@DemoLen==0x25") == "w@0x2031fc==0x25", (
        "the word after `@` is the symbol; `w` before it is a size and `0x25` a number")
    assert conditions.console_condition(" b@0x20100c == 3 ") == "b@0x20100c == 3"
    assert conditions.console_condition("W == 1") == "0x10 == 1", "a whole word is substituted"
    use_table(monkeypatch, table={"BEEF": 0x400})
    assert conditions.console_condition("d1==$beef") == "d1==$beef", (
        "after `$` the letters are a hex number's digits, never a name (express.cpp, `case '$'`)")
    with pytest.raises(mstate.Invalid, match="empty"):
        conditions.console_condition("   ")
    with pytest.raises(mstate.Invalid, match="comma"):
        conditions.console_condition("d0==1,{d0=2}")
    # A condition READS: an assignment, a step or a brace is executed at every evaluation,
    # on a path whose reply says the session is not altered.
    for writes in ("d0=1", "w@DemoLen=0x99", "d0++", "d0--", "d0==1;g", "{d0=1}"):
        with pytest.raises(mstate.Invalid, match="EXECUTES"):
            conditions.console_condition(writes)
    for reads in ("d0==1", "d0!=1", "d0<=1", "d0>=1", "d0<1"):
        assert conditions.console_condition(reads) == reads
    # A symbol spelled like a register or a console variable is ambiguous, never substituted.
    use_table(monkeypatch, table={"PC": 0x1000, "DEMOLEN": 0x2031FC})

    class _Regs:
        register_names = ["D0", "PC", "SP"]
        threads: dict[int, str] = {}

        def layout(self, thread: int) -> _Regs:
            return self

    monkeypatch.setattr(mstate.STATE, "ses", _Regs())
    with pytest.raises(mstate.Invalid, match="both a symbol"):
        conditions.console_condition("pc==0x400")
    assert conditions.console_condition("DemoLen==1") == "0x2031fc==1"
    # A name followed by `@` with no size letter is not a symbol and is left whole.
    assert conditions.console_condition("DemoLen@==1") == "DemoLen@==1"


def test_a_conditioned_stop_is_armed_listed_and_cleared_through_the_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC})
    out = s.breakpoint_at(ref="0x4a0", condition="w@DemoLen==0x25")
    assert out["status"] == "ok" and out["armed"] is True, out
    assert out["condition"] == "w@0x2031fc==0x25" and out["role"] == "stop"
    assert _console_bps(ses) == ["bp 0x4a0::maincpu,w@0x2031fc==0x25"]
    assert ses.armed == [], "no Z0: the stub's packet carries no condition"
    listed = s.declaration_list("breakpoint")["breakpoints"]
    assert listed[0]["condition"] == "w@0x2031fc==0x25" and listed[0]["state"] == "armed"
    # The same address under ANOTHER condition is refused, never stacked or swapped.
    refused("declaration_clear", s.breakpoint_at(ref="0x4a0", condition="d0==1"))
    refused("no condition", s.breakpoint_at(ref="0x25a4", role="control", condition="d0==1"))
    gone = s.declaration_clear("breakpoint", ref="0x4a0")
    assert gone["declarations_cleared"] == 1
    assert any(c.startswith("bpclear ") for c in ses.commands), "removed through the console"
    assert ses.armed == [], "and never through the stub"


def test_run_to_with_a_condition_arms_the_target_through_the_console_and_reports_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0x4A0])
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC})
    ses.stops_after_polls = 1
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 3

    ses.go = go  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0, condition="w@DemoLen==0x25")
    assert out["status"] == "ok" and out["verdict"] == "TARGET", out
    assert out["condition"] == "w@0x2031fc==0x25" and out["control_hits"] == 3
    assert "bp 0x4a0::maincpu,w@0x2031fc==0x25" in _console_bps(ses)
    assert ses.armed == [], "the target went through the console, not the stub"
    assert any(c.startswith("bpclear ") for c in ses.commands), "and left through it"
    assert mlists.rows_at(mlists.bp_held(ses), 0x4A0) == [], "gone"  # type: ignore[arg-type]
    assert not ses.running
    # And the session is NOT altered: a conditioned stop is bookkeeping, not a write.
    assert out["session"]["altered"] is False


def test_a_conditioned_stop_is_re_armed_with_its_condition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0", condition="w@0x2031fc==0x25")
    # A new start: the debugger holds nothing, the store still does.
    ses.bplist_rows.clear()
    ses.commands.clear()
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["0x4a0"], out
    assert _console_bps(ses) == ["bp 0x4a0::maincpu,w@0x2031fc==0x25"]
    assert ses.armed == []


def test_a_second_declaration_of_a_ref_is_refused_naming_what_the_held_one_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The refusal describes the declaration the store holds (role, condition) and nothing else."""
    _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0", condition="d0==1")
    out = refused("declared as a stop breakpoint under the condition 'd0==1'; "
                  r'`declaration_clear\(kind="breakpoint"',
                  s.breakpoint_at(ref="0x4a0", condition="d0==2"))
    assert "declaring it another way" in out["message"]
    s.breakpoint_at(ref="0x4b0")
    refused("declared as a stop breakpoint with no condition; "
            r'`declaration_clear\(kind="breakpoint"',
            s.breakpoint_at(ref="0x4b0", condition="d0==2"))
    s.breakpoint_at(ref="0x25a4", role="control")
    refused("declared as a control breakpoint with no condition; "
            r'`declaration_clear\(kind="breakpoint"',
            s.breakpoint_at(ref="0x25a4"))


def test_perform_refuses_a_condition_on_a_control_before_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x25a4", "role": "control",
                            "condition": "d0==1"}])
    assert out["status"] == "INVALID" and "no condition" in str(out.get("errors"))
    assert _console_bps(ses) == []


def test_a_foreign_row_under_another_condition_refuses_the_declaration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row at the address under another condition is refused, never adopted."""
    ses = _controlled(monkeypatch, tmp_path)
    ses.bplist_rows.append("    3 @ 0004A0 if d0==1")
    out = refused("another condition", s.breakpoint_at(ref="0x4a0", condition="d1==2"))
    assert out["code"] == "ambiguous_ref"
    assert out["message"] == (
        "the debugger already holds a row at 0x4a0 under another condition (3 @ 0004A0 if "
        "d0==1), and this declaration's is 'd1==2': `debug(\"bpclear 0x3\")` removes it, or "
        "`declaration_clear(kind=\"breakpoint\")` when a declaration of this server owns it "
        "(`declaration_list(kind=\"breakpoint\")` says)")
    assert _console_bps(ses) == [] and ses.armed == []


def test_a_stored_stop_rearmed_listed_without_its_condition_is_unarmable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The `bp` answers alike whatever it did with the condition, so the read back is the proof."""
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0", condition="d0==1")
    ses.bplist_rows[:] = []
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    real_monitor = ses.monitor

    def bare(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bp 0x4a0:") and "," in command:
            command = command.split(",", 1)[0]          # the console dropped the condition
        return real_monitor(command, timeout)

    monkeypatch.setattr(ses, "monitor", bare)
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == [], out
    (why,) = out["unarmable"]
    assert why["ref"] == "0x4a0" and why["why"] == (
        "the console took a `bp` at 0x4a0 and its `bplist` does not list a conditioned row: "
        "nothing is armed"), why


def test_perform_refuses_a_run_to_condition_with_a_comma_before_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "run_to", "ref": "0x4a0", "control": "0x25a4",
                            "condition": "d0==1,{d0=2}"}])
    assert out["status"] == "INVALID" and "comma" in str(out.get("errors"))
    assert not ses.running and _console_bps(ses) == []


def test_rearm_refuses_to_adopt_a_row_under_another_condition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A conditioned declaration meeting an unconditioned row is `unarmable`, never `rearmed`."""
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0", condition="w@0x2031fc==0x25")
    ses.bplist_rows[:] = ["    9 @ 0004A0"]
    ses.commands.clear()
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == [] and out["unarmable"][0]["ref"] == "0x4a0"
    assert out["unarmable"][0]["why"] == (
        "the debugger already holds a row at 0x4a0 with no condition (9 @ 0004A0), and "
        "this declaration's is 'w@0x2031fc==0x25': `debug(\"bpclear 0x9\")` removes it, or "
        "`declaration_clear(kind=\"breakpoint\")` when a declaration of this server owns it "
        "(`declaration_list(kind=\"breakpoint\")` says)")
    assert _console_bps(ses) == [], "nothing sent: the row is somebody else's"


# ------------------------------------------ a condition keeps its names across a rebuild

def _new_start(monkeypatch: pytest.MonkeyPatch, ses: _RunningSession,
               symbols: dict[str, int]) -> None:
    """The next `start`: the store as it was, an empty debugger, another build's table."""
    ses.bplist_rows.clear()
    ses.commands.clear()
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    use_table(monkeypatch, table=symbols)


def test_a_condition_is_listed_as_the_console_reads_it_and_as_it_was_typed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC})
    out = s.breakpoint_at(ref="0x4a0", condition=" w@DemoLen==0x25 ")
    assert out["condition"] == "w@0x2031fc==0x25" and out["condition_typed"] == "w@DemoLen==0x25"
    row = s.declaration_list("breakpoint")["breakpoints"][0]
    assert (row["condition"], row["condition_typed"]) == ("w@0x2031fc==0x25", "w@DemoLen==0x25")
    # What was typed IS what the console reads: nothing to tell apart, so no second field.
    plain = s.breakpoint_at(ref="0x4b0", condition="d0==1")
    assert plain["condition"] == "d0==1" and "condition_typed" not in plain
    assert "condition_typed" not in s.declaration_list("breakpoint")["breakpoints"][1]
    assert _console_bps(ses) == ["bp 0x4a0::maincpu,w@0x2031fc==0x25", "bp 0x4b0::maincpu,d0==1"]


def test_a_re_arm_sends_the_condition_with_the_address_of_this_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC})
    s.breakpoint_at(ref="0x4a0", condition="w@DemoLen==0x25")
    _new_start(monkeypatch, ses, {"DEMOLEN": 0x203300})
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["0x4a0"], out
    assert _console_bps(ses) == ["bp 0x4a0::maincpu,w@0x203300==0x25"], (
        "the symbol MOVED, and so did this")
    row = s.declaration_list("breakpoint")["breakpoints"][0]
    assert (row["state"], row["condition"], row["condition_typed"]) == (
        "armed", "w@0x203300==0x25", "w@DemoLen==0x25")


def test_a_re_arm_adopts_a_listed_row_by_the_condition_of_this_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC})
    s.breakpoint_at(ref="0x4a0", condition="w@DemoLen==0x25")
    _new_start(monkeypatch, ses, {"DEMOLEN": 0x203300})
    ses.bplist_rows[:] = ["    7 @ 0004A0 if w@0x203300==0x25"]
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["0x4a0"] and _console_bps(ses) == [], out
    # THE CONTROL: the row the OLD build's address left behind judges another place.
    _new_start(monkeypatch, ses, {"DEMOLEN": 0x203300})
    ses.bplist_rows[:] = ["    7 @ 0004A0 if w@0x2031fc==0x25"]
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == [] and "another condition" in out["unarmable"][0]["why"], out
    assert "w@0x203300==0x25" in out["unarmable"][0]["why"], "it names what THIS build compares"
    assert _console_bps(ses) == []


def test_a_condition_the_console_cannot_evaluate_is_refused_before_anything_is_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    ses.rp_print_errors["d1=="] = captured("print.braces.malformed.txt")
    out = refused("did not evaluate `d1==`", s.breakpoint_at(ref="0x4a0", condition="d1=="))
    assert out["code"] == "bad_argument"
    assert " ".join(captured("print.braces.malformed.txt").split()) in out["message"]
    assert _console_bps(ses) == [] and s.declaration_list("breakpoint")["breakpoints"] == []
    assert "print {d1==}" in ses.commands, "it was the console that judged it"


def test_a_re_arm_accounts_for_a_condition_this_build_cannot_evaluate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A symbol the rebuild dropped makes the declaration `unresolved` and kept; other refusals are
    `unarmable`; an unresolved ref sends nothing."""
    ses = _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC, "OTHER": 0x203400,
                                  "WHERE": 0x4C0})
    s.breakpoint_at(ref="0x4a0", condition="w@DemoLen==0x25")
    s.breakpoint_at(ref="0x4b0", condition="w@Other==1")
    s.breakpoint_at(ref="where", condition="w@Other==2")
    _new_start(monkeypatch, ses, {"OTHER": 0x203400})
    ses.rp_errors["w@DemoLen==0x25"] = captured("print.braces.unknown-symbol.txt")
    ses.rp_print_errors["w@0x203400==1"] = captured("print.braces.malformed.txt")
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["unresolved"]) == ["0x4a0", "where"] and refs(out["rearmed"]) == [], out
    assert [u["ref"] for u in out["unarmable"]] == ["0x4b0"]
    assert "did not evaluate `w@0x203400==1`" in out["unarmable"][0]["why"]
    assert _console_bps(ses) == [], "nothing was armed blind"
    assert "print {w@0x203400==2}" not in ses.commands, "an unresolved ref sends nothing"
    assert len(s.declaration_list("breakpoint")["breakpoints"]) == 3, "and every one is kept"


def test_a_breakpoint_whose_condition_is_unresolved_is_listed_so_until_cleared_or_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The list says `unresolved` (not `gone`) when the ref resolved and the condition did not."""
    ses = _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC, "OTHER": 0x00203400})
    s.breakpoint_at(ref="0x4a0", condition="w@DemoLen==0x25")
    s.breakpoint_at(ref="0x4b0", condition="w@Other==1")
    _new_start(monkeypatch, ses, {"OTHER": 0x00203400})
    ses.rp_errors["w@DemoLen==0x25"] = captured("print.braces.unknown-symbol.txt")
    ses.rp_print_errors["w@0x203400==1"] = captured("print.braces.malformed.txt")
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["unresolved"]) == ["0x4a0"]
    assert [u["ref"] for u in out["unarmable"]] == ["0x4b0"]
    listed = s.declaration_list("breakpoint")["breakpoints"]
    assert [(r["ref"], r["state"], r.get("addr")) for r in listed] == [
        ("0x4a0", "unresolved", "0x000004a0"), ("0x4b0", "gone", "0x000004b0")]
    assert listed[0]["condition"] == "w@DemoLen==0x25", "as typed: this table refuses it"
    assert s.declaration_clear("breakpoint", ref="0x4a0")["declarations_cleared"] == 1
    arming.store().add(dec.Declaration("breakpoint", "address", "0x4a0", origin="s0",
                                       condition="w@DemoLen==0x25", fingerprint="fp-test"))
    assert [r["state"] for r in s.declaration_list("breakpoint")["breakpoints"]] == ["gone",
                                                                                     "gone"], (
        "cleared: back in the store unarmed, it is gone, not unresolved")
    arming.store().discard([d for d in arming.store().declarations() if d.ref == "0x4a0"])
    _new_start(monkeypatch, ses, {"OTHER": 0x00203400})
    s.breakpoint_at(ref="0x4a0", condition="d0==1")            # the store holds 0x4b0, 0x4a0
    ses.rp_errors["d0==1"] = captured("print.braces.unknown-symbol.txt")
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["unresolved"]) == ["0x4a0"]
    del ses.rp_errors["d0==1"]
    again = s.breakpoint_at(ref="0x4a0", condition="d0==1")     # the same declaration, adopted
    assert (again["state"], again["already_stored"]) == ("armed", True), again
    ses.bplist_rows.clear()                                   # the debugger drops the row
    assert [(r["ref"], r["state"]) for r in s.declaration_list("breakpoint")["breakpoints"]] == [
        ("0x4b0", "gone"), ("0x4a0", "gone")], "armed: no longer unresolved, so a lost row is gone"


def test_a_console_error_while_a_re_arm_evaluates_a_condition_is_that_declarations_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `print {...}` the console does not answer is `unarmable` for that declaration alone."""
    ses = _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"DEMOLEN": 0x2031FC})
    s.breakpoint_at(ref="0x4a0", condition="w@DemoLen==0x25")
    s.breakpoint_at(ref="0x4b0", condition="d0==1")
    _new_start(monkeypatch, ses, {"DEMOLEN": 0x2031FC})
    real = ses.monitor

    def silent(command: str, timeout: float = 10.0) -> str:
        if command == "print {w@0x2031fc==0x25}":
            raise gs.SessionError("the console answered nothing within 10.0 s")
        return real(command, timeout)

    ses.monitor = silent  # type: ignore[method-assign]
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert [(u["ref"], u["why"]) for u in out["unarmable"]] == [
        ("0x4a0", "the console answered nothing within 10.0 s")]
    assert refs(out["rearmed"]) == ["0x4b0"], "the pass went on past it"
    assert _console_bps(ses) == ["bp 0x4b0::maincpu,d0==1"], "nothing was armed blind for 4a0"


# ------------------------------------------------ a condition too long for one stub packet
# The stub drops a `qRcmd` past its packet size, so the session refuses such a command before
# sending it. Every path that sends a conditioned `bp` has state to change first (a stored
# declaration, a declared control, watches disarmed for the pass), so it must be judged before
# any of it, and at `start` a stored one that does not fit this binary must not kill the start.

def _refusing(ses: _RunningSession) -> None:
    """The double's console refuses a command past its packet size, as the real one does."""
    taken = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        ses.console_packet(command)  # type: ignore[misc]
        return taken(command, timeout)

    ses.monitor = monitor  # type: ignore[method-assign]


def _limit(ses: _RunningSession) -> int:
    payload = ses.max_payload()  # type: ignore[misc]
    assert payload is not None
    return (payload - len("qRcmd,")) // 2


def _cond(ses: _RunningSession, addr: int, over: int, evaluated: bool = True) -> str:
    """A condition whose longest command is `over` characters past the limit."""
    sent = ([breakpoints.bp_command(addr, "d0==0x1", ":maincpu")]
            + (["print {d0==0x1}"] if evaluated else []))
    zeros = _limit(ses) + over - max(len(c) for c in sent)
    assert zeros >= 0
    return "d0==0x" + "0" * zeros + "1"


def _too_long(out: dict[str, Any], over: int = 1) -> None:
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert out["command_chars"] == out["limit_chars"] + over, out


@pytest.mark.parametrize("over", [0, 1, 40])
def test_breakpoint_at_a_condition_past_the_packet_stores_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, over: int,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    _refusing(ses)
    ses.packet_size = 0x41
    stored = arming.store().declarations()
    out = s.breakpoint_at(ref="0x4a0", condition=_cond(ses, 0x4A0, over))
    if over == 0:
        assert out["status"] == "ok" and out["armed"] is True, out
        assert len(_console_bps(ses)) == 1
        assert max(len(c) for c in ses.commands) == _limit(ses), "one command sat AT the limit"
        return
    _too_long(out, over)       # it names the LONGEST command, whichever one is refused first
    assert arming.store().declarations() == stored, "the declaration was not stored"
    assert mstate.STATE.breakpoints == {} and _console_bps(ses) == []


@pytest.mark.parametrize("over", [0, 1])
def test_run_to_a_condition_past_the_packet_declares_no_control_and_disarms_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, over: int,
) -> None:
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0x4A0])
    taken = ses.monitor
    ses.monitor = lambda command, timeout=10.0: (  # type: ignore[method-assign]
        WPLIST_ONE if command == "wplist" else taken(command, timeout))
    _refusing(ses)
    # The control's own `bp 0x25a4::maincpu,(++temp0)==0` has to fit, so the target's
    # condition is the one command that reaches the limit.
    ses.packet_size = 0x45
    watch = {"index": 1, "addr": 0x2031FC, "length": 4, "entry": "1 @ 2031FC-2031FF write",
             "enabled": True, "cpu": ":maincpu", "condition": ""}
    monkeypatch.setattr(mstate.STATE, "armed_watches", {("0x2031fc", ":maincpu"): dict(watch)})
    ses.stops_after_polls = 1
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0, disarm_watches=True,
                   condition=_cond(ses, 0x4A0, over, evaluated=False))
    if over == 0:
        assert out["status"] == "ok" and out["verdict"] == "TARGET", out
        assert out["disarmed_watches"] == [{"ref": "0x2031fc", "cpu": ":maincpu"}], \
            "the pass disarmed the watch"
        assert list(out)[-1] == "session", "the pass's fields land before the session block"
        assert "wpclear 0x1" in ses.commands, "and the removal reached the console"
        return
    _too_long(out)
    assert arming.store().declarations() == [], "no control was declared"
    assert mstate.STATE.controls == {} and _console_bps(ses) == []
    assert not any(c.startswith("wpclear") for c in ses.commands), "no watch was disarmed"
    assert mstate.STATE.armed_watches == {("0x2031fc", ":maincpu"): watch}
    assert not ses.running


@pytest.mark.parametrize("over", [0, 1, 40])
def test_rearm_puts_a_condition_past_the_packet_in_unarmable_and_goes_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, over: int,
) -> None:
    """A condition too long for this binary's packet is reported and kept; the rest re-arm."""
    ses = _controlled(monkeypatch, tmp_path)
    _refusing(ses)
    ses.packet_size = 0x41
    cond = _cond(ses, 0x4A0, over)
    ses.packet_size = None                  # declared where the stub advertised no limit
    assert s.breakpoint_at(ref="0x4a0", condition=cond)["status"] == "ok"
    assert s.breakpoint_at(ref="0x25a4")["status"] == "ok"
    ses.bplist_rows.clear()                 # a new start: the debugger holds nothing
    ses.commands.clear()
    ses.armed.clear()
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    ses.packet_size = 0x41
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    if over == 0:
        assert sorted(refs(out["rearmed"])) == ["0x25a4", "0x4a0"] and out["unarmable"] == [], out
        return
    assert refs(out["rearmed"]) == ["0x25a4"], "the pass went on past the refused one"
    assert [u["ref"] for u in out["unarmable"]] == ["0x4a0"], out
    assert f"{_limit(ses) + over} characters" in out["unarmable"][0]["why"]
    assert _console_bps(ses) == [], "nothing of it was sent"
    assert [d.ref for d in arming.store().declarations()] == ["0x4a0", "0x25a4"], "and it is kept"


# ------------------------------------------------------- step over, and a run the console started
# The stub offers no step-over; the console's `over` runs a call to its return and
# answers while the machine still runs, so each `over` is confirmed on the program counter.
# A `g` typed through `debug` releases the machine and the stub sends no stop packet for
# it, so the session marks itself RUNNING and proves the stop on the frame counter.


def _no_packet(timeout: float | None = None) -> str:
    """The socket of a machine the console released: nothing arrives."""
    raise gs.SessionError("no packet")


def test_step_over_goes_through_the_console_and_is_confirmed_on_the_pc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path, pcs=[0xF2034, 0xF2100])
    real_monitor = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "over":
            ses.commands.append(command)
            ses.pcs = ses.pcs[1:] + ses.pcs[:1] if len(ses.pcs) > 1 else ses.pcs
            return ""
        return real_monitor(command, timeout)

    ses.monitor = monitor  # type: ignore[method-assign]
    monkeypatch.setattr(ses, "current_pc", lambda: ses.pcs[0])
    monkeypatch.setattr(ses, "_receive", _no_packet, raising=False)
    ses.last_stop_packet = "T05watch:2031fc;"
    out = s.step(count=2, mode="over")
    assert (out["status"] == "ok" and out["mode"] == "over"
            and out["instructions_completed"] == 2), out
    assert ses.last_stop_packet == "", "the packet of the stop before is not this stop's cause"
    assert ses.commands.count("over") == 2 and out["cause"] == "step 2 over"
    assert out["summary"] == "step 2 over: pc 0x000f2034"
    refused("mode is one of", s.step(mode="out"))
    into = s.step(count=1)
    assert (into["mode"] == "into" and into["cause"] == "step 1"
            and into["instructions_completed"] == 1)


def test_step_over_that_never_returns_is_halted_and_says_how_far_it_got(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:

    ses = _controlled(monkeypatch, tmp_path)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.3)
    moving = iter(range(1, 10_000))
    monkeypatch.setattr(ses, "current_pc", lambda: next(moving))
    real_monitor = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "over":
            ses.commands.append(command)
            return ""
        return real_monitor(command, timeout)

    ses.monitor = monitor  # type: ignore[method-assign]
    monkeypatch.setattr(ses, "_receive", _no_packet, raising=False)
    out = s.step(count=3, mode="over")
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert out["instructions_completed"] == 0 and ses.commands.count("over") == 1


def test_a_g_typed_through_debug_marks_the_machine_running_and_the_stop_is_proved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Readers refuse after a console `g`; `stop` returns via `halt` and the counter's rest."""
    from scry_mame import running

    ses = _controlled(monkeypatch, tmp_path)
    at_rest = [False, False, True]     # the first two looks find the counter moving
    monkeypatch.setattr(running, "frame_at_rest",
                        lambda ses_, reads=3, gap_s=0.1: at_rest.pop(0) if at_rest else True)
    monkeypatch.setattr(ses, "_receive", _no_packet, raising=False)
    halted: list[bool] = []
    monkeypatch.setattr(ses, "halt", lambda: halted.append(True), raising=False)
    out = s.debug(command="g")
    assert out["status"] == "ok" and out["session"]["running"] is True and out["mutates"] is True
    assert out["session"]["running"] is True and getattr(mstate.STATE, "console_run")  # noqa: B009
    # A reader refuses, naming the last stop, while the counter moves.
    refused("RUNNING", s.registers())
    # `stop`: the 0x03 goes out and the stop is proved on the counter.
    out = s.stop()
    assert out["status"] == "ok" and out["interrupted"] is True and halted == [True], out
    assert out["session"]["running"] is False and not mstate.STATE.console_run
    # And a stop the console's own breakpoint produced is found by the first contact.
    s.debug(command="gvblank")
    assert getattr(mstate.STATE, "console_run")  # noqa: B009 -- mypy narrowed it above
    st_ = s.status()
    assert st_["session"]["running"] is False and "stopped_on_its_own" in st_, st_
    assert st_["stopped_on_its_own"]["packet"].startswith("none")


def test_frame_at_rest_reads_the_counter_three_times() -> None:
    from server_support import _RegisterSession

    from scry_mame import running

    ses = _RegisterSession(bits=32, frame=10)
    ses.frame_answers = ["10", "11", "12"]
    assert not running.frame_at_rest(ses, gap_s=0.0)  # type: ignore[arg-type]
    ses.frame_answers = ["20", "20", "20"]
    assert running.frame_at_rest(ses, gap_s=0.0)  # type: ignore[arg-type]


def test_step_over_that_settles_only_after_the_interrupt_is_an_invalid_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The pc moves until the interrupt, then rests: a stop survey, INVALID `not_settled`."""

    ses = _controlled(monkeypatch, tmp_path)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.3)
    pcs = iter(range(1, 10_000))
    resting = [False]
    monkeypatch.setattr(ses, "current_pc", lambda: 0x4A0 if resting[0] else next(pcs))
    monkeypatch.setattr(ses, "halt", lambda: resting.__setitem__(0, True), raising=False)
    real_monitor = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "over":
            ses.commands.append(command)
            return ""
        return real_monitor(command, timeout)

    ses.monitor = monitor  # type: ignore[method-assign]
    monkeypatch.setattr(ses, "_receive", _no_packet, raising=False)
    out = s.step(count=2, mode="over")
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert out["instructions_completed"] == 0 and out["pc"] == "0x000004a0" and "regs" in out
    assert "would have returned later was not seen" in out["message"]
    assert "step over 1 of 2 was still moving" in out["message"] and out["mode"] == "over", out
    assert out["cause"] == "interrupt after a step over still moving at its bound"


def test_a_console_run_that_never_rests_is_not_settled_and_the_counter_read_can_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from server_support import _RegisterSession

    from scry_mame import running

    ses = _controlled(monkeypatch, tmp_path)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.3)
    monkeypatch.setattr(running, "frame_at_rest", lambda ses_, reads=3, gap_s=0.1: False)
    monkeypatch.setattr(ses, "_receive", _no_packet, raising=False)
    monkeypatch.setattr(ses, "halt", lambda: None, raising=False)
    s.debug(command="g")
    out = refused("did not come to rest", s.stop())
    assert out["code"] == "not_settled"
    # A counter the console cannot answer reads as NOT at rest, never as a stop.
    reg = _RegisterSession(bits=32, frame=10)

    def refuses(command: str, timeout: float = 10.0) -> str:
        raise gs.SessionError("the console answered nothing")

    monkeypatch.setattr(reg, "monitor", refuses)
    assert not running.frame_at_rest(reg, gap_s=0.0)  # type: ignore[arg-type]


def test_perform_refuses_a_step_mode_it_does_not_know_before_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _controlled(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "step", "mode": "out"}])
    assert out["status"] == "INVALID" and "mode is one of" in str(out.get("errors"))
    assert ses.commands == [] or all(not c.startswith("over") for c in ses.commands)


def test_step_over_is_not_fooled_by_a_callee_spinning_on_one_pc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A callee spinning on a flag reads one pc; the frame counter tells it from a stop."""

    ses = _controlled(monkeypatch, tmp_path)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.3)
    frames = iter(range(1, 10_000))
    real_monitor = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "over":
            ses.commands.append(command)
            return ""
        if command == "print curpc,frame":
            return f"4a0 {next(frames):x}\n"        # the pc stands, the frames keep coming
        if command == "print frame":
            return f"{next(frames):x}\n"
        return real_monitor(command, timeout)

    ses.monitor = monitor  # type: ignore[method-assign]
    monkeypatch.setattr(ses, "halt", lambda: None, raising=False)
    monkeypatch.setattr(ses, "_receive", _no_packet, raising=False)
    out = s.step(count=1, mode="over")
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert out["session"]["running"] is True and getattr(mstate.STATE, "console_run")  # noqa: B009
    refused("RUNNING", s.registers())


@pytest.mark.parametrize("command", ["g", "go", "gt 10", "gvblank 3", "gint 2", "gex", "gni", "GO"])
def test_every_spelling_of_the_go_family_releases(command: str) -> None:

    assert mconsole.releases(command), command
    assert mconsole.mutates(command), command


@pytest.mark.parametrize("command", ["print pc", "bplist", "dasm x,0,10", "history"])
def test_a_reader_never_releases(command: str) -> None:

    assert not mconsole.releases(command), command


class _LineSession:
    """Just what `write.debug` touches of a session, answering every line alike."""

    running = False
    threads: dict[int, str] = {}         # a stub without threads: no `?` is asked

    def console_packet(self, command: str) -> str:
        return "qRcmd," + command.encode().hex()

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        if command in ("cpulist", "ignore"):
            return captured("cpulist.main-visible.txt" if command == "cpulist"
                            else "ignore.none.txt")
        return "1\n"

    def emulated_seconds(self) -> float:
        return 1.0


@pytest.mark.parametrize(
    ("line", "released", "forgot", "rereads"),
    [("print 1;g", True, [], False),
     ("print 1;bpclear", False, ["bpclear"], False),
     ("print 1;wpclear;rpclear", False, ["wpclear", "rpclear"], False),
     ("bpclear 1;bpclear 2", False, ["bpclear"], False),
     ("bpclear;print 1", False, ["bpclear"], False),
     ("rpclear;wpclear", False, ["rpclear", "wpclear"], False),
     ("print 1;g;bpclear", True, ["bpclear"], False),
     # The word as the console resolves it: a prefix, a case, a comma straight after it.
     ("bpcl 1", False, ["bpclear"], False),
     ("WPCLEAR 1", False, ["wpclear"], False),
     ("rpclear,1", False, ["rpclear"], False),
     ("print 1;focus maincpu", False, [], True),
     ("focus maincpu;focus subcpu", False, [], True),
     ("print 1;IGNORE subcpu", False, [], True),
     ("print 1;obs subcpu", False, [], True),
     ("print 1;foc 1", False, [], True),
     ("print 1;fo 1", False, [], False),       # `fo` is an alias of `find`, not a prefix of focus
     ("print 1;f 0,4,1", False, [], False),
     ('print "a;g;bpclear"', False, [], False)],
)
def test_debug_reads_every_command_of_a_line_for_a_release_a_clear_and_a_focus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, line: str, released: bool,
    forgot: list[str], rereads: bool,
) -> None:
    """Each family's records are forgotten once per line in order; `focus`, `ignore`, `observe`
    (any prefix) re-read the cpu state; a `;` inside quotes splits nothing."""
    from scry_mame import write as mwrite

    calls: list[str] = []

    def forgets(word: str) -> Callable[[gs.Session], list[str]]:
        def forget(ses: gs.Session) -> list[str]:
            calls.append(word)
            return []
        return forget

    for word in list(mwrite._CLEARS):
        monkeypatch.setitem(mwrite._CLEARS, word, forgets(word))
    ses = _LineSession()
    out = mwrite.debug(ses, tmp_path, line)  # type: ignore[arg-type]
    assert ses.running is released and "running" not in out, out
    assert calls == forgot, calls
    assert ("visible_cpu" in out, "ignored" in out) == (rereads, rereads), out
    if rereads:
        assert (out["visible_cpu"], out["ignored"]) == (":maincpu", []), out


@pytest.mark.parametrize(
    ("line", "mutates", "now", "armed"),
    [("temp3=5", False, ["IRQ_VBLANK"], []), ("TEMP3 += 1", False, ["IRQ_VBLANK"], []),
     ("++temp3", False, ["IRQ_VBLANK"], []),
     ("temp3=0;temp9=0", False, ["IRQ_VBLANK", "SUB_IRQ"], []),
     ("temp3=w@100=1", True, ["IRQ_VBLANK"], []), ("w@temp3++=1", True, ["IRQ_VBLANK"], []),
     ("bp 0x500,(++temp9)==0", False, [], ["SUB_IRQ"]),
     ("bp 0x500,1,{temp3=0};temp9=1", True, ["SUB_IRQ"], ["IRQ_VBLANK"]),
     ("temp4=5", False, [], []), ("print temp3", False, [], []),
     ("print temp3==5", False, [], []), ("w@temp3=1", True, [], []),
     ('printf "temp3=%d",temp3', False, [], []), ("temp30=1", True, [], [])],
)
def test_a_debug_line_that_assigns_a_controls_temp_names_the_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, line: str, mutates: bool,
    now: list[str], armed: list[str],
) -> None:
    """Writing a temp is no guest write, but a control counts in one: the note names the counts."""
    from scry_mame import write as mwrite

    monkeypatch.setattr(mstate.STATE, "controls", {
        ("IRQ_VBLANK", ":maincpu"): {"addr": 0x400, "temp": 3, "index": "1"},
        ("SUB_IRQ", ":subcpu"): {"addr": 0x500, "temp": 9, "index": "2"}})
    out = mwrite.debug(_LineSession(), tmp_path, line)  # type: ignore[arg-type]
    assert out["mutates"] is mutates, out
    notes = str(out.get("note", "")).split("; ")
    said_now = next((n for n in notes if n.startswith("this line assigns")), "")
    said_armed = next((n for n in notes if n.startswith("a row this line arms")), "")
    temps = {"IRQ_VBLANK": "on :maincpu (temp3)", "SUB_IRQ": "on :subcpu (temp9)"}
    for ref, temp in temps.items():
        assert (f"{ref} {temp}" in said_now) is (ref in now), (ref, notes)
        assert (f"{ref} {temp}" in said_armed) is (ref in armed), (ref, notes)
    assert ("`hits_since_armed`" in said_now and "does not see it" in said_now) is bool(now), notes
    assert ("each time it is evaluated" in said_armed) is bool(armed), notes


def test_a_debug_line_that_releases_and_assigns_a_counter_says_both(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from scry_mame import write as mwrite

    monkeypatch.setattr(mstate.STATE, "controls", {
        ("IRQ_VBLANK", ":maincpu"): {"addr": 0x400, "temp": 3, "index": "1"}})
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    out = mwrite.debug(_LineSession(), tmp_path, "temp3=0;g")  # type: ignore[arg-type]
    first, second = str(out["note"]).split("; ")
    assert first.startswith("the console released the machine"), out["note"]
    assert second.startswith("this line assigns the counter of IRQ_VBLANK on :maincpu (temp3)"), \
        out["note"]


def test_a_settle_proof_whose_console_answers_nothing_is_not_a_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A console that cannot answer proves nothing, so each proof of rest says not-at-rest."""
    from server_support import _RegisterSession

    from scry_mame import advance, running

    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.2)
    reg = _RegisterSession(bits=32, frame=10)

    def refuses(command: str, timeout: float = 10.0) -> str:
        raise gs.SessionError("the console answered nothing")

    monkeypatch.setattr(reg, "monitor", refuses)
    assert not advance._settled_pc(reg)  # type: ignore[arg-type]
    assert not running.frame_at_rest(reg, gap_s=0.0)  # type: ignore[arg-type]


def test_run_to_refuses_a_target_that_already_carries_a_breakpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A declared stop at the target halts the run and the reply says TARGET; the removal leaves
    the run's row; an address two entries share is refused before the run starts."""
    ses = _controlled(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0", condition="w@0x2031fc==0x0")
    armed_before = list(_console_bps(ses))
    out = refused("already has breakpoint", s.run_to(
        ref="0x4a0", control="0x25a4", seconds=1.0, condition="w@0x2031fc==0xffff"))
    assert out["code"] == "bad_argument" and "w@0x2031fc==0x0" in out["message"]
    at_target = [c for c in _console_bps(ses) if c.startswith("bp 0x4a0")]
    assert at_target == armed_before, "nothing armed at the target, nothing removed"
    assert not any(c.startswith("bpclear ") for c in ses.commands)
    assert not ses.running
    # Cleared, the same run is taken.
    s.declaration_clear("breakpoint", ref="0x4a0")
    ses.stops_after_polls = 1
    assert s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0,
                    condition="w@0x2031fc==0xffff")["status"] == "ok"


def test_a_stop_found_on_a_control_row_is_an_interrupt_and_never_the_controls_doing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An interrupt on a control's address is the `cause` if its row exists, else `interrupt`."""
    from scry_mame import running

    ses = _controlled(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "IRQ_VBLANK", 0x400)))
    monkeypatch.setattr(mstate.STATE, "controls",
                        {("IRQ_VBLANK", ":maincpu"): {"addr": 0x400, "temp": 0, "index": "1"}})
    assert running.halts(0x400, ":maincpu") is False
    assert running.attribute(0x400, ":maincpu") == "stopped at no breakpoint this server armed"
    at_rest = [False, True]            # the counter moves under `g`, rests after the halt
    monkeypatch.setattr(running, "frame_at_rest",
                        lambda ses_, reads=3, gap_s=0.1: at_rest.pop(0) if at_rest else True)
    monkeypatch.setattr(ses, "_receive", _no_packet, raising=False)
    monkeypatch.setattr(ses, "halt", lambda: None, raising=False)
    monkeypatch.setattr(ses, "current_pc", lambda: 0x400, raising=False)
    s.debug(command="g")
    out = s.stop()
    assert out["status"] == "ok" and out["interrupted"] is True, out
    assert out["cause"] == "interrupt", out["cause"]
    # The same address as a STOP row is the row's doing.
    monkeypatch.setattr(mstate.STATE, "controls", {})
    assert running.halts(0x400, ":maincpu") is True
    assert running.attribute(0x400, ":maincpu") == "breakpoint at 0x400"


# ------------------------------------------- the three `run_for` bail-outs that let go
#
# EACH OF THESE LEAVES THE MACHINE UNDER A CONSOLE-STARTED RUN, and the only thing standing
# between a caller and a value sampled off a moving machine is `ses.running`. The sibling in
# `step`'s `over` mode already sets it; these three did not, so a retried read was SERVED.


def _never_lands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """A double whose `gvblank` releases the machine and whose frame counter never settles."""
    from server_support import _install, _RegisterSession

    from scry_mame import advance

    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    monkeypatch.setattr(advance, "VBLANK_SETTLE_S", 0.0)
    # A CONSOLE RELEASE IS GLOBAL STATE and these cases end with it set: declared through
    # `monkeypatch` so it is restored rather than left for whatever runs next.
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    real = reg.monitor

    def slow(command: str, timeout: float = 10.0) -> str:
        if command == "gvblank":
            return ""
        if command == "print frame":
            reg.frame = 11 if reg.frame == 10 else 10   # two readings never agree: no landing
            return f"{reg.frame:x}\n"
        return real(command, timeout)

    reg.monitor = slow  # type: ignore[method-assign]
    return reg


def test_a_run_by_frames_that_runs_out_of_clock_leaves_the_session_saying_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`not_settled` from `_run_for_frames`: the machine may be RUNNING, so the readers refuse."""
    reg = _never_lands(monkeypatch, tmp_path)
    out = s.run_for(frames=3, seconds=0.05)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert reg.running is True and getattr(mstate.STATE, "console_run")  # noqa: B009
    refused("RUNNING", s.registers())
    refused("RUNNING", s.read_memory(ref="0x1000", length=4))


def test_a_run_by_frames_that_emulated_nothing_leaves_the_session_saying_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`no_progress`: the counter never moved. This double is in fact stopped, but two agreeing
    readings prove nothing; `stop` interrupts it, which does, and the readers serve."""
    from server_support import _install, _RegisterSession

    from scry_mame import advance

    reg = _RegisterSession(bits=32, frame=10, stop_after=1)
    reg.frozen = True                      # a `gvblank` that moves no frame
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    out = s.run_for(frames=2, seconds=0.2)
    assert out["status"] == "INVALID" and out["code"] == "no_progress", out
    assert "RUNNING" in out["message"], out["message"]
    assert reg.running is True and getattr(mstate.STATE, "console_run")  # noqa: B009
    assert s.registers()["code"] == "not_stopped", "the frozen counter proved nothing"
    assert reg.running is True
    assert s.stop()["interrupted"] is True
    assert getattr(reg, "running") is False  # noqa: B009   # mypy narrowed it to True above
    assert s.registers()["status"] == "ok"


def test_a_run_by_milliseconds_that_never_came_to_rest_leaves_the_session_saying_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`not_settled` from `_run_for`: the bound interrupt did not land, so the readers refuse."""
    from server_support import _install, _RegisterSession

    from scry_mame import advance

    reg = _RegisterSession(bits=32, frame=10, stop_after=None)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.05)
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    reg.halt = lambda: setattr(reg, "interrupted", True)  # type: ignore[method-assign]
    out = s.run_for(milliseconds=1000, seconds=0.05)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out
    assert reg.running is True and getattr(mstate.STATE, "console_run")  # noqa: B009
    refused("RUNNING", s.registers())


def test_the_inherited_clause_names_the_familys_tools_and_is_silent_without_an_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """No clause for a row with no origin or this session's own; list and clear otherwise."""
    _controlled(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "session_origin", "s-now")
    assert arming.inherited(dec.Declaration("breakpoint", "address", "0x4a0")) == ""
    assert arming.inherited(dec.Declaration("breakpoint", "address", "0x4a0", origin="s-now")) == ""
    watch = arming.inherited(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                                             watch_mode="change", origin="s-old"))
    assert "PERSISTENT" in watch and "regpoint" not in watch
    assert "`declaration_clear(kind=\"watch\")`" in watch
    reg = arming.inherited(dec.Declaration("regpoint", "expr", "d1==7fff", origin="s-old"))
    assert "`declaration_clear(kind=\"regpoint\")`" in reg and 'kind=\"watch\"' not in reg
