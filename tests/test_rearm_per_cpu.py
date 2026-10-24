"""`start`'s re-arm puts each declaration on its own cpu: by console with the cpu
named, so the visible cpu never moves; a row already listed is adopted only under that cpu; and
every entry of the account names its ref and its cpu. A registerpoint re-arms only when its cpu is
the visible one, since `rpset` names no other.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import bplist_add, place_row, ref_cpu, visible_in  # noqa: E402
from test_server import _running  # noqa: E402
from test_watches import _watching  # noqa: E402

import mame_arming as arming  # noqa: E402
import mame_conditions as conditions  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_rearm as rearming  # noqa: E402
import mame_regpoints as regpoints  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_watches as watches  # noqa: E402
import server as s  # noqa: E402

MAIN, SUB = ":maincpu", ":subcpu"


def _stored(*decls: dec.Declaration) -> None:
    for decl in decls:
        arming.store().add(decl)


def test_each_declaration_is_re_armed_on_its_own_cpu_and_the_visible_cpu_stays(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    _stored(dec.Declaration("breakpoint", "address", "0x542", cpu=SUB, fingerprint="fp-test"),
            dec.Declaration("breakpoint", "address", "0x4a0", cpu=MAIN, fingerprint="fp-test"),
            dec.Declaration("breakpoint", "address", "0x25a4", role="control", cpu=SUB,
                            fingerprint="fp-test"),
            dec.Declaration("watch", "address", "0x2031fc", width=4, fmt="u32",
                            watch_mode="change", cpu=SUB, fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert sorted((e["ref"], e["cpu"]) for e in out["rearmed"]) == [
        ("0x2031fc", SUB), ("0x25a4", SUB), ("0x4a0", MAIN), ("0x542", SUB)], out
    for command in ("bp 0x542::subcpu", "bp 0x4a0::maincpu", "bp 0x25a4::subcpu,(++temp0)==0",
                    "wp 0x2031fc::subcpu,0x4,w"):
        assert command in ses.commands, (command, ses.commands)
    assert visible_in(s.cpu_info()) == MAIN
    assert not any(c.startswith(("Hc", "focus")) for c in ses.commands), "nothing moved it"
    listed = {(b["ref"],
               b["cpu"]): b["state"] for b in s.declaration_list("breakpoint")["breakpoints"]}
    assert listed == {("0x542", SUB): "armed", ("0x4a0", MAIN): "armed", ("0x25a4", SUB): "armed"}


def test_the_same_address_on_two_cpus_is_sent_twice_and_each_row_is_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two rows at one address in one pass are told apart by the cpu their header names."""
    ses = _running(monkeypatch, tmp_path)
    _stored(dec.Declaration("breakpoint", "address", "0x4a0", cpu=SUB, fingerprint="fp-test"),
            dec.Declaration("breakpoint", "address", "0x4a0", cpu=MAIN, fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert ref_cpu(out["rearmed"]) == [("0x4a0", SUB), ("0x4a0", MAIN)], out
    owners = {r["owner"]: r["cpu"] for r in mstate.STATE.breakpoints.values()}
    assert owners == {("0x4a0", SUB): SUB, ("0x4a0", MAIN): MAIN}, owners


def test_a_row_listed_under_the_other_cpu_is_not_adopted_by_the_re_arm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    index = bplist_add(ses, 0x542)
    place_row(ses, "bp_devices", index, MAIN)             # typed on the main cpu, not ours
    _stored(dec.Declaration("breakpoint", "address", "0x542", cpu=SUB, fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert ref_cpu(out["rearmed"]) == [("0x542", SUB)], out
    assert "bp 0x542::subcpu" in ses.commands, "its own row armed, the main cpu's left foreign"
    assert s.declaration_list("breakpoint")["foreign"] == {"breakpoints": [f"{index} @ 000542"]}


def test_a_registerpoint_re_arms_only_when_its_cpu_is_the_visible_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    _stored(dec.Declaration("regpoint", "expr", "d1==7fff", cpu=SUB),
            dec.Declaration("regpoint", "expr", "d2==1", cpu=MAIN))
    out: dict[str, list[object]] = {"rearmed": [], "unresolved": [], "unarmable": []}
    regpoints.rearm(ses, out)  # type: ignore[arg-type]
    assert ref_cpu(out["rearmed"]) == [("d2==1", MAIN)], out
    assert len(out["unarmable"]) == 1, out
    why = out["unarmable"][0]
    assert isinstance(why, dict) and why["cpu"] == SUB and "focus(cpu=':subcpu')" in why["why"]
    assert not any(c.startswith("rpset {d1") for c in ses.commands)


def test_a_pass_re_arms_one_range_on_two_cpus_as_two_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """After a pass the debugger numbers each re-sent row afresh: each record takes the row under
    its own cpu, never the other cpu's at the same range."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="change", length=4)
    s.watch_add(ref="0x2031fc", mode="change", length=4, cpu="subcpu")
    owners = watches.disarm_for_pass(ses)  # type: ignore[arg-type]
    assert watches.rearm_after_pass(ses, owners) == owners  # type: ignore[arg-type]
    main, sub = (mstate.STATE.armed_watches[("0x2031fc", c)] for c in (MAIN, SUB))
    assert main["index"] != sub["index"], (main, sub)
    assert (main["cpu"], sub["cpu"]) == (MAIN, SUB)
    assert "foreign" not in s.declaration_list("watch")


def test_a_control_re_armed_after_a_stop_row_at_its_address_on_the_other_cpu_takes_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stop row sent first in the pass sits at the same address under the other cpu; the
    control armed after it owns the row under its own cpu, and both are re-armed."""
    ses = _running(monkeypatch, tmp_path)
    _stored(dec.Declaration("breakpoint", "address", "0x542", cpu=MAIN, fingerprint="fp-test"),
            dec.Declaration("breakpoint", "address", "0x542", role="control", cpu=SUB,
                            fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert sorted((e["ref"], e["cpu"]) for e in out["rearmed"]) == [("0x542", MAIN), ("0x542", SUB)]
    assert out["unarmable"] == [], out
    owners = {r["owner"]: r["cpu"] for r in mstate.STATE.breakpoints.values()}
    assert owners == {("0x542", MAIN): MAIN, ("0x542", SUB): SUB}, owners
    control = mstate.STATE.controls[("0x542", SUB)]
    assert mstate.STATE.breakpoints[control["index"]]["cpu"] == SUB


def test_a_registerpoint_re_armed_with_the_visible_cpu_unread_uses_its_own_cpus_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    _stored(dec.Declaration("regpoint", "expr", "d1==7fff", cpu=SUB))
    seen: list[str | None] = []
    real = conditions.console_condition

    def spy(condition: str, cpu: str | None = None) -> str:
        seen.append(cpu)
        return real(condition, cpu)

    monkeypatch.setattr(conditions, "console_condition", spy)
    import mame_cpus as cpus

    monkeypatch.setattr(cpus, "visible_cpu", lambda ses_: None)
    regpoints.rearm(ses, {"rearmed": [], "unresolved": [], "unarmable": []})  # type: ignore[arg-type]
    assert seen == [SUB], seen


def test_start_judges_a_stored_condition_against_the_registers_its_own_cpu_lists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The re-arm reads each cpu's register names off the inventory, so that inventory is read
    before it. The capture's two 68000s share their names, so the sub cpu's are AUTHORED apart
    (one `IX` more, as a heterogeneous board has them) and the stub describes one layout for
    every thread: only the inventory can tell the two cpus apart."""
    import json

    from test_declarations import _armable_boot
    from test_machine import M68K_DUAL
    from test_server import _boot_args
    from test_symbols_per_cpu import LISTXML, _yaml

    import mame_launch as launch
    import mame_machine as machine

    sub_regs = "REGS :subcpu A0,A1,A2,A3,A4,A5,A6,CURFLAGS,CURPC,D0,D1,D2,D3,D4,D5,D6,D7,IR,PC,"
    assert M68K_DUAL.count(sub_regs) == 1, "the line the variant replaces"
    dump = M68K_DUAL.replace(sub_regs, sub_regs + "IX,")
    image, _sym, store, _armed = _armable_boot(monkeypatch, tmp_path)
    args = {**_boot_args(tmp_path, image), "system": "m68k-dual"}
    Path(args["binary"]).write_text(f"#!/bin/sh\ncat {LISTXML}\n")    # m68k-dual's -listxml
    real_boot = launch.boot

    def boot(*a: object, **k: object) -> object:
        booted = real_boot(*a, **k)  # type: ignore[arg-type]
        assert mstate.STATE.scratch is not None
        (mstate.STATE.scratch / machine.DUMP_NAME).write_text(dump)    # the harness's dump
        return booted

    monkeypatch.setattr(launch, "boot", boot)
    main = _yaml(tmp_path / "main.yaml", ("main_only", 0x500), ("ix", 0x2000), ("usp", 0x2100))
    sub = _yaml(tmp_path / "sub.yaml", ("sub_only", 0x600), ("sub_plain", 0x640),
                ("sub_data", 0x2031fc), ("ix", 0x2000))
    rows = [dec.Declaration("breakpoint", "symbol", ref, condition=cond, cpu=cpu,
                            origin="earlier")
            for ref, cond, cpu in (("sub_only", "IX==1", SUB), ("main_only", "IX==1", MAIN),
                                   ("sub_plain", "D0==1", SUB))]
    rows += [dec.Declaration("watch", "symbol", "sub_data", width=4, fmt="u32",
                             watch_mode="change", cpu=SUB, origin="earlier"),
             dec.Declaration("regpoint", "expr", "USP==1", cpu=MAIN, origin="earlier")]
    store.write_text(json.dumps({dec.store_key("m68k-dual", main): [r.to_dict() for r in rows]}))
    out = s.start(**args, symbols={"maincpu": main, "subcpu": sub})
    try:
        rearm = out["declarations"]["rearm"]
        refused = {(e["ref"], e["cpu"]): e["why"] for e in rearm["unarmable"]}
        assert set(refused) == {("sub_only", SUB), ("USP==1", MAIN)}, rearm
        assert "'IX' is both a symbol of the table" in refused[("sub_only", SUB)]
        assert "'USP' is both a symbol of the table" in refused[("USP==1", MAIN)]
        # The rest of each cpu's rows arm under their own cpu, the main cpu's `IX` as the symbol.
        assert sorted((e["ref"], e["cpu"]) for e in rearm["rearmed"]) == [
            ("main_only", MAIN), ("sub_data", SUB), ("sub_plain", SUB)], rearm
        listed = {(b["ref"], b["cpu"]): (b["state"], b["condition"])
                  for b in s.declaration_list("breakpoint")["breakpoints"]}
        assert listed[("main_only", MAIN)] == ("armed", "0x2000==1"), listed
        assert listed[("sub_plain", SUB)] == ("armed", "D0==1"), listed
        # Each served cpu's byte order is the inventory's word for its program space, given to
        # the session before anything decodes: both 68000s are big-endian in the dump.
        ses = mstate.STATE.ses
        assert ses is not None
        assert ses.endianness == {t: "big" for t in (ses.threads or {1: MAIN})}, ses.endianness
        assert ses.layout(1).mame_order == "big"
    finally:
        s.close()
