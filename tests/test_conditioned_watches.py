"""A change watch conditioned on the value written (`wp <addr>,<len>,w,<condition>`).

The console's answers are captured (`fixtures/console/PROVENANCE.txt`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from session_doubles import captured, refs, refused, use_table  # noqa: E402
from test_watches import _watching, _WatchSession  # noqa: E402

from scry_mame import (
    advance,  # noqa: E402
    arming,  # noqa: E402
    watches,  # noqa: E402
)
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import lists as mlists  # noqa: E402
from scry_mame import map as mmap  # noqa: E402
from scry_mame import rearm as rearming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

COND = "(wpdata&3)!=0"
ARM = f"wp 0x2031fc::maincpu,0x4,w,{COND}"
OWNER = ("frame_lo", ":maincpu")
# The console prints the unconditioned shape, and only once the condition held.
STOP_LINE = next(ln for ln in captured("debuglog-conditioned-wp.txt").splitlines(keepends=True)
                 if ln.startswith("Stopped at watchpoint 1 "))


def _conditioned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _WatchSession:
    """The watch double with the captured answer to the condition's evaluation."""
    ses = _watching(monkeypatch, tmp_path)
    ses.rp_print_errors = {COND: captured("print-braces-wpdata-masked-outside.txt")}
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    return ses


def test_the_captured_row_and_arm_are_the_shapes_the_doubles_answer() -> None:
    """The doubles answer in the shapes MAME prints, and the parser reads the condition off."""
    live = captured("wplist-condition.txt")
    assert "write if (wpdata&3)==0" in live
    (row,) = mlists.parse_wplist(live)
    assert row["condition"] == "(wpdata&3)==0" and row["entry"].endswith(" if (wpdata&3)==0")
    assert captured("wpset-set-condition.txt") == captured("wpset-set.txt"), (
        "a conditioned `wp` answers the plain sentence, so only the list proves the condition")
    assert captured("print-braces-wpdata-outside.txt").strip() == "0"
    # MAME sets a condition it cannot evaluate and never fires it, hence the evaluator first.
    assert captured("wpset-malformed-condition.txt") == "Watchpoint 2 set\n\n"
    malformed = [r for r in mlists.parse_wplist(captured("wplist-malformed-armed.txt"))
                 if r["index"] == 2]
    assert malformed[0]["condition"] == "wpdata=="
    assert "unknown symbol" in captured("refused-wpset-unknown-symbol.txt")


def test_a_change_watch_arms_its_condition_once_the_console_evaluated_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _conditioned(monkeypatch, tmp_path)
    out = s.watch_add(ref="frame_lo", mode="change", length=4, condition=COND)
    assert out["status"] == "ok" and out["armed"] is True, out
    assert out["condition"] == COND and "condition_typed" not in out
    assert out["entry"] == f"1 @ 2031FC-2031FF write if {COND}", "the row read back carries it"
    assert ses.commands.index(f"print {{{COND}}}") < ses.commands.index(ARM), (
        "evaluated before it is armed")
    (held,) = arming.store().declarations()
    assert held.condition == COND and held.watch_mode == "change"
    assert mstate.STATE.armed_watches[OWNER]["condition"] == COND
    listed = s.declaration_list("watch")["watches"][0]
    assert listed["condition"] == COND and listed["state"] == "armed", listed


def test_a_symbol_in_the_condition_reaches_the_console_as_its_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _conditioned(monkeypatch, tmp_path)
    out = s.watch_add(ref="frame_lo", mode="change", length=4, condition="wpdata==copy_in_rom")
    assert out["condition"] == "wpdata==0x400", out
    assert out["condition_typed"] == "wpdata==copy_in_rom"
    assert "wp 0x2031fc::maincpu,0x4,w,wpdata==0x400" in ses.commands
    assert arming.store().declarations()[0].condition == "wpdata==copy_in_rom", (
        "stored as typed, re-substituted against the next build's table")


def test_a_condition_the_console_cannot_evaluate_arms_nothing_and_stores_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The evaluator's words are the refusal: MAME would set the `wp` and never fire it."""
    ses = _conditioned(monkeypatch, tmp_path)
    ses.rp_print_errors["wpdata=="] = captured("print-braces-malformed.txt")
    out = refused("did not evaluate `wpdata==`",
                  s.watch_add(ref="frame_lo", mode="change", length=4, condition="wpdata=="))
    assert out["code"] == "bad_argument"
    assert ses.watchpoints == [] and arming.store().declarations() == []


def test_a_condition_on_another_mode_or_of_a_writing_shape_is_refused_before_the_machine(
) -> None:
    """Only a change watch is conditioned, and a condition compares, never writes or acts."""
    for mode in ("show", "count", "expr"):
        out = refused("only a change watch", s.watch_add(ref="frame_lo", mode=mode, length=4,
                                                         condition=COND))
        assert out["code"] == "bad_argument", (mode, out)
    for bad in ("wpdata=1", "wpdata==1,{g}", "wpdata==1;g"):
        out = s.watch_add(ref="frame_lo", mode="change", length=4, condition=bad)
        assert out["code"] == "bad_argument", (bad, out)


def test_the_same_ref_under_another_condition_is_already_declared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _conditioned(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4, condition=COND)
    out = refused(re.escape("under the condition '(wpdata&3)!=0'"),
                  s.watch_add(ref="frame_lo", mode="change", length=4, condition="wpdata==1"))
    assert out["code"] == "ambiguous_ref" and len(ses.wplist_rows) == 1
    s.declaration_clear("watch", ref="frame_lo")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    refused("with no condition",
            s.watch_add(ref="frame_lo", mode="change", length=4, condition=COND))
    assert len(ses.wplist_rows) == 1


def test_a_row_listed_without_the_condition_sent_is_not_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The `wp` answer is the same whatever became of the condition, so the list is the proof."""
    ses = _conditioned(monkeypatch, tmp_path)
    real = ses.watchpoint

    def bare(addr: int, length: int, remove: bool = False, cpu: str | None = None,
             index: int | None = None, cond: str = "") -> None:
        real(addr, length, remove, cpu, index)

    monkeypatch.setattr(ses, "watchpoint", bare)
    out = refused("does not list a conditioned row",
                  s.watch_add(ref="frame_lo", mode="change", length=4, condition=COND))
    assert out["code"] == "readback_refused" and out["stored"] is False


def test_a_row_typed_under_another_condition_is_never_adopted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row held under another condition, or none, would judge something else than declared."""
    ses = _conditioned(monkeypatch, tmp_path)
    ses.wplist_rows.append("    1 @ 2031FC-2031FF write")
    ses.wp_next_index = 2
    out = refused(re.escape('`debug("wpclear 0x1")` removes it'),
                  s.watch_add(ref="frame_lo", mode="change", length=4, condition=COND))
    assert out["code"] == "ambiguous_ref" and ses.watchpoints == []
    assert out["message"] == (
        "the debugger already holds a row at 0x2031fc for 4 bytes with no condition (1 @ "
        "2031FC-2031FF write), and this declaration's is '(wpdata&3)!=0': "
        "`debug(\"wpclear 0x1\")` removes it, or `declaration_clear(kind=\"watch\")` when a "
        "declaration of this server "
        "owns it (`declaration_list(kind=\"watch\")` says)")
    ses.wplist_rows[0] = f"    1 @ 2031FC-2031FF write if {COND}"
    out = refused("under another condition",
                  s.watch_add(ref="frame_lo", mode="change", length=4))
    assert out["message"] == (
        f"the debugger already holds a row at 0x2031fc for 4 bytes under another condition (1 @ "
        f"2031FC-2031FF write if {COND}), and this declaration has none: "
        "`debug(\"wpclear 0x1\")` removes it, or `declaration_clear(kind=\"watch\")` when a "
        "declaration of this server "
        "owns it (`declaration_list(kind=\"watch\")` says)")


def test_a_stored_condition_is_re_armed_at_start_and_one_naming_a_lost_symbol_is_unresolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _conditioned(monkeypatch, tmp_path)
    store = arming.store()
    store.add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                              watch_mode="change", condition=COND, origin="s1",
                              cpu=":maincpu"))
    store.add(dec.Declaration("watch", "address", "0x203200", width=2, fmt="u16",
                              watch_mode="change", condition="wpdata==GONE", origin="s1",
                              cpu=":maincpu", fingerprint=mstate.STATE.fingerprint(":maincpu")))
    ses.rp_errors = {"wpdata==GONE": captured("print-braces-unknown-symbol.txt")}
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["frame_lo"] and refs(out["unresolved"]) == ["0x203200"], out
    assert ARM in ses.commands and not any(c.startswith("wp 0x203200") for c in ses.commands)
    listed = {w["ref"]: w for w in s.declaration_list("watch")["watches"]}
    assert listed["frame_lo"]["entry"].endswith(f" if {COND}")
    assert listed["0x203200"]["state"] == "unresolved", listed["0x203200"]
    assert "condition" in listed["0x203200"]["why"]
    s.declaration_clear("watch", ref="0x203200")
    assert ("watch", ("0x203200", ":maincpu")) not in mstate.STATE.conditions_unresolved


def test_a_stored_row_under_another_condition_is_unarmable_at_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _conditioned(monkeypatch, tmp_path)
    arming.store().add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                                       watch_mode="change", condition=COND, origin="s1",
                                       cpu=":maincpu"))
    ses.wplist_rows.append("    1 @ 2031FC-2031FF write")
    ses.wp_next_index = 2
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    (why,) = out["unarmable"]
    assert why["why"] == (
        "the debugger already holds a row at 0x2031fc for 4 bytes with no condition (1 @ "
        "2031FC-2031FF write), and this declaration's is '(wpdata&3)!=0': "
        "`debug(\"wpclear 0x1\")` removes it, or `declaration_clear(kind=\"watch\")` when a "
        "declaration of this server "
        "owns it (`declaration_list(kind=\"watch\")` says)")
    assert ses.watchpoints == []


def test_a_held_pass_re_arms_the_watch_under_its_condition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A pass with the watches disarmed re-arms each one under its condition."""
    ses = _conditioned(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4, condition=COND)
    out = advance._with_watches_disarmed(ses, True, lambda: {"verdict": "ELAPSED"})  # type: ignore[arg-type]
    assert out["disarmed_watches"] == [{"ref": "frame_lo", "cpu": ":maincpu"}], out
    assert ses.commands.count(ARM) == 2
    assert mstate.STATE.armed_watches[OWNER]["entry"] == f"2 @ 2031FC-2031FF write if {COND}"


def test_a_conditioned_watch_names_its_condition_when_it_stops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _conditioned(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4, condition=COND)
    (tmp_path / "debug.log").write_text("F2034\n")
    ses.next_packet = "T05watch:2031fc;"
    ses.stops_after_polls = 1
    (tmp_path / "debug.log").open("a").write(STOP_LINE + "25F6\n")
    ses.memory[0x2031FC] = bytes.fromhex("00000000")
    out = s.resume(seconds=1.0)
    assert out["watch_hit"]["condition"] == COND, out["watch_hit"]
    assert out["watch_hit"]["writes"] == [{"wrote": "0x00", "to": "0x002031fe", "pc": "0x000025f4"}]
    assert "condition" in out["omitted"], "the stop names its condition as left out"
    assert s.declaration_list("watch")["watches"][0]["condition"] == COND


def test_a_pointer_watch_that_moves_takes_its_condition_along(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _conditioned(monkeypatch, tmp_path)
    ses.pointer_width = 4
    use_table(monkeypatch, table={"_G_ENGINE": 0x2031FC})
    ses.memory[0x2031FC] = (0x210000).to_bytes(4, "big")
    ses.rp_print_errors["wpdata==7"] = captured("print-braces-wpdata-outside.txt")
    s.watch_add(ref="[_g_engine]+0x4", mode="change", length=2, condition="wpdata==7")
    ses.memory[0x2031FC] = (0x211000).to_bytes(4, "big")
    (w,) = s.step()["watches"]
    assert w["moved"] == {"from": "0x00210004", "to": "0x00211004"}, w
    assert ses.commands.count("wp 0x211004::maincpu,0x2,w,wpdata==7") == 1
    assert ses.wplist_rows[-1].endswith(" if wpdata==7")


@pytest.mark.parametrize("name", ["wpdata", "wpaddr", "wpsize"])
def test_a_project_symbol_spelled_like_a_watchpoint_variable_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str,
) -> None:
    """A table symbol spelled like a console variable would make the value written a constant."""
    _conditioned(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"FRAME_LO": 0x2031FC, name.upper(): 0x100})
    out = refused("both a symbol of the table and a name the console knows",
                  s.watch_add(ref="frame_lo", mode="change", length=4, condition=f"{name}==1"))
    assert out["code"] == "ambiguous_ref"


def test_the_write_side_under_lua_taps_is_the_memory_they_wrap() -> None:
    """MAME names a write tap in `map` before what it wraps; the memory is what it wraps."""
    for name in ("map-one-tap.txt", "map-two-taps.txt"):
        sides = mmap.map_sides(captured(name))
        assert sides == {"read": "memory@200000", "write": "memory@200000"}, (name, sides)
    assert watches.values_from("memory@200000", "memory@200000") == "memory"


def test_a_condition_on_a_pointer_watch_stored_null_is_judged_before_it_is_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A null-pointer watch is armed later with no call to refuse it, so it is judged first."""
    ses = _conditioned(monkeypatch, tmp_path)
    ses.pointer_width = 4
    use_table(monkeypatch, table={"_G_ENGINE": 0x2031FC})
    ses.memory[0x2031FC] = bytes(4)
    ses.rp_print_errors["wpdata=="] = captured("print-braces-malformed.txt")
    refused("did not evaluate `wpdata==`",
            s.watch_add(ref="[_g_engine]+0x4", mode="change", length=2, condition="wpdata=="))
    assert arming.store().declarations() == [] and ses.watchpoints == []
    assert "print {wpdata==}" in ses.commands


def test_a_held_pass_that_gets_the_row_back_without_its_condition_says_it_is_not_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The pass reads the list back, and a row without the condition is not the watch's."""
    ses = _conditioned(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4, condition=COND)
    owners = watches.disarm_for_pass(ses)  # type: ignore[arg-type]
    real = ses.watchpoint

    def bare(addr: int, length: int, remove: bool = False, cpu: str | None = None,
             index: int | None = None, cond: str = "") -> None:
        real(addr, length, remove, cpu, index)

    monkeypatch.setattr(ses, "watchpoint", bare)
    assert watches.rearm_after_pass(ses, owners) == []  # type: ignore[arg-type]
    assert mstate.STATE.armed_watches[OWNER]["enabled"] is False


def test_a_stored_condition_the_console_refuses_at_start_is_unarmable_and_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """At `start` a condition that no longer evaluates, or whose `wp` no longer fits, is
    `unarmable` with why, and the pass goes on."""
    ses = _conditioned(monkeypatch, tmp_path)
    store = arming.store()
    store.add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                              watch_mode="change", condition="wpdata==", origin="s1",
                              cpu=":maincpu"))
    ses.rp_print_errors["wpdata=="] = captured("print-braces-malformed.txt")
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    (why,) = out["unarmable"]
    assert "did not evaluate `wpdata==`" in why["why"] and ses.watchpoints == [], out
    ses.packet_size = 0x41
    store.discard(store.declarations())
    store.add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                              watch_mode="change", condition="wpdata==0x" + "0" * 80 + "1",
                              origin="s1", cpu=":maincpu"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert len(out["unarmable"]) == 1 and ses.watchpoints == [], out
