"""A declaration keeps its cpu: the same ref on two cpus is two declarations, the
store's identity and every "one row, one declaration" rule compare (cpu, address), a raw address
is judged against its own cpu's build, and a store written before a declaration had a cpu reads
every row as the first cpu's.
"""

from pathlib import Path

import pytest
from server_support import _running  # noqa: E402
from session_doubles import add_symbol, refs, refused  # noqa: E402
from test_symbols_per_cpu import _m68k_dual_boot, _two_tables  # noqa: E402

from scry_mame import (
    arming,  # noqa: E402
    breakpoints,  # noqa: E402
    watches,  # noqa: E402
)
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import rearm as rearming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

MAIN, SUB = ":maincpu", ":subcpu"


def _bp(ref: str, cpu: str | None, fingerprint: str | None = None, origin: str | None = None,
        condition: str = "") -> dec.Declaration:
    return dec.Declaration("breakpoint", "address", ref, cpu=cpu, fingerprint=fingerprint,
                           origin=origin, condition=condition)


# ------------------------------------------------------------------------ the declaration


def test_the_cpu_is_part_of_a_declarations_identity_and_survives_the_store_file() -> None:
    assert _bp("0x4a0", MAIN) != _bp("0x4a0", SUB) and _bp("0x4a0", MAIN).owner == ("0x4a0", MAIN)
    back = dec.Declaration.from_dict(_bp("0x4a0", SUB).to_dict())
    assert back == _bp("0x4a0", SUB) and back.cpu == SUB
    assert "cpu" not in _bp("0x4a0", None).to_dict(), "a row with no cpu writes none"
    with pytest.raises(dec.DeclarationError, match="an expr watch carries no cpu"):
        dec.Declaration("watch", "expr", "beamy", watch_mode="expr", cpu=MAIN)


def test_the_same_ref_on_two_cpus_is_two_declarations_and_a_clear_can_take_one(
    tmp_path: Path,
) -> None:
    store = dec.DeclarationStore("t", tmp_path / "d.json")
    assert store.add(_bp("0x4a0", MAIN)) and store.add(_bp("0x4a0", SUB))
    assert not store.add(_bp("0X04A0", MAIN)), "one cpu's in another spelling: adopted"
    assert store.held_ref("0X04A0", "address", ("breakpoint",), MAIN) == "0x4a0"
    assert store.held_ref("0x4a0", "address", ("breakpoint",), ":audiocpu") is None
    assert store.held_ref("0x4a0", "symbol", ("breakpoint",), MAIN) is None
    store.refuse_conflict(dec.Declaration("breakpoint", "address", "0x4a0", role="control",
                                          cpu=":audiocpu"))   # another cpu: no conflict
    with pytest.raises(dec.DeclarationError, match="already declared"):
        store.refuse_conflict(_bp("0x4a0", MAIN, condition="d0==1"))
    assert store.discard([_bp("0x4a0", SUB)]) == 1
    assert [(d.ref, d.cpu) for d in dec.DeclarationStore("t", tmp_path / "d.json")
            .declarations()] == [("0x4a0", MAIN)], "persisted"


def test_a_store_written_before_a_declaration_had_a_cpu_reads_as_the_first_cpus() -> None:
    store = dec.DeclarationStore("t", None)
    store.add(_bp("0x4a0", None))
    store.add(dec.Declaration("watch", "expr", "beamy", watch_mode="expr"))
    store.add(_bp("0x542", SUB))
    store.bind_first_cpu(MAIN)
    assert [d.cpu for d in store.declarations()] == [MAIN, None, SUB]


# ------------------------------------------------------------------ arming on the machine


def test_two_refs_at_one_address_on_two_cpus_are_two_rows_and_on_one_cpu_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """One row is one declaration on ONE cpu: the address on the other cpu is another place."""
    ses = _running(monkeypatch, tmp_path)
    add_symbol(monkeypatch, "VBLANK", 0x4A0)
    assert s.breakpoint_at(ref="0x4a0")["status"] == "ok"
    sub = s.breakpoint_at(ref="vblank", cpu="subcpu")
    assert sub["status"] == "ok" and sub["cpu"] == SUB, sub
    assert len(ses.bplist_rows) == 2
    refused("already declared under '0x4a0'", s.breakpoint_at(ref="vblank"))


def test_two_refs_on_one_range_on_two_cpus_are_two_watchpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from test_watches import _watching

    ses = _watching(monkeypatch, tmp_path)
    assert s.watch_add(ref="frame_lo", mode="change", length=4)["status"] == "ok"
    other = s.watch_add(ref="0x2031fc", mode="change", length=4, cpu="subcpu")
    assert other["status"] == "ok" and len(ses.wplist_rows) == 2, other
    refused("already armed under 'frame_lo'", s.watch_add(ref="0x2031fc", mode="change",
                                                            length=4))


def test_a_clear_naming_a_cpu_takes_that_cpus_declaration_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x542")
    s.breakpoint_at(ref="0x542", cpu="subcpu")
    out = s.declaration_clear("breakpoint", ref="0x542", cpu="subcpu")
    assert out["declarations_cleared"] == 1 and len(out["disarmed"]) == 1, out
    assert [(b["ref"],
             b["cpu"]) for b in s.declaration_list("breakpoint")["breakpoints"]] == [("0x542",
                                                                                      MAIN)]
    assert len(ses.bplist_rows) == 1
    s.regpoint_add(condition="d1==7fff")
    refused("matches no regpoint declaration", s.declaration_clear("regpoint", ref="d1==7fff",
                                                                   cpu="subcpu"))
    assert s.declaration_clear("regpoint", ref="d1==7fff",
                               cpu="maincpu")["declarations_cleared"] == 1
    assert s.declaration_clear("breakpoint",
                               all=True)["declarations_cleared"] == 1, "no cpu: every cpu's"


def test_run_to_is_refused_only_by_a_control_on_its_own_cpu_and_declares_its_control_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0", role="control")
    refused("same address as a control", s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05))
    ses.stops_after_polls = 1
    ses.pcs = [0xF2034, 0x4A0]
    out = s.run_to(ref="0x4a0", control="0x25a4", cpu="subcpu", seconds=1.0)
    assert out.get("code") != "bad_argument", out
    assert ("0x25a4", SUB) in mstate.STATE.controls, "the control is the target's cpu's"
    assert any(c.startswith("bp 0x25a4::subcpu,(++temp") for c in ses.commands), ses.commands


def test_a_control_on_another_cpu_is_not_the_one_a_run_to_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A control on :maincpu says nothing about whether :subcpu ran: the control a run names is
    declared on the target's own cpu, and only that cpu's count."""
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4", role="control")
    ses.stops_after_polls = 1
    ses.pcs = [0xF2034, 0x542]
    out = s.run_to(ref="0x542", control="0x25a4", cpu="subcpu", seconds=1.0)
    assert {("0x25a4", MAIN), ("0x25a4", SUB)} <= set(mstate.STATE.controls)
    assert [c["cpu"] for c in out["controls"]] == [SUB], out["controls"]


def test_a_control_declared_on_another_cpu_is_named_as_such_when_run_to_cannot_resolve_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`irq_vblank` is a name of :maincpu's table, declared there as a control; a run to a
    :subcpu target naming it cannot resolve it in :subcpu's table, and the refusal says so,
    naming both cpus and the `breakpoint_at` that would put a control on the target's cpu,
    instead of calling the control "not armed (unresolved)" with no cpu at all."""
    import dataclasses

    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "tables", {
        MAIN: dataclasses.replace(mstate.NO_TABLE, table={"IRQ_VBLANK": 0x400}),
        SUB: mstate.NO_TABLE})
    assert s.breakpoint_at(ref="irq_vblank", role="control")["armed"] is True
    assert ("irq_vblank", MAIN) in mstate.STATE.controls
    # A second control under another name, on the target's own cpu: the hint names the cpus
    # THIS name is declared on, not every cpu a control sits on.
    assert s.breakpoint_at(ref="0x25a4", role="control", cpu="subcpu")["armed"] is True
    out = s.run_to(ref="0x542", cpu="subcpu", control="IRQ_VBLANK", seconds=0.05)
    assert out["status"] == "INVALID" and out["code"] == "unknown_ref", out
    assert "does not resolve in :subcpu's symbol table" in out["message"], out["message"]
    assert "declared on :maincpu" in out["message"], out["message"]
    assert 'breakpoint_at(ref, role="control", cpu=":subcpu")' in out["message"], out["message"]
    assert "unresolved" not in out["message"] and "nothing was declared" not in out["message"]
    assert out["cpu"] == SUB and out["control_on"] == [MAIN], "the ref's cpus, case-blind"
    assert not any(c.startswith("bp 0x542") for c in ses.commands) and not ses.running
    # A name declared nowhere still says which cpu's table it was looked up in.
    out = s.run_to(ref="0x542", cpu="subcpu", control="nowhere", seconds=0.05)
    assert out["code"] == "unknown_ref" and "a symbol of :subcpu's table" in out["message"], out
    assert "control_on" not in out and "declared on" not in out["message"]


def test_a_targets_silence_is_measured_by_the_controls_on_its_cpu_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The main cpu's control fires over the run and the sub cpu's does not: a run to a sub
    target counts the sub's alone, so its silence is `control_silent`, never a TIMEOUT."""
    from scry_mame import advance
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x25a4", role="control")                 # :maincpu, temp0
    s.breakpoint_at(ref="0x4a0", role="control", cpu="subcpu")    # :subcpu, temp1
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 30               # only the main cpu's fires

    monkeypatch.setattr(ses, "go", go)
    out = s.run_to(ref="0x542", control="0x4a0", cpu="subcpu", seconds=0.05)
    assert out["code"] == "control_silent" and out["control_hits"] == 0, out
    assert out["controls"] == [{"ref": "0x4a0", "cpu": SUB, "hits_in_run": 0}], out["controls"]
    assert [(d["ref"], d["cpu"]) for d in out["control_dasm"]] == [("0x4a0", SUB)]
    assert "(0x4a0)" in out["message"], out["message"]
    ses.stop_count, ses.interrupted = 0, 0
    out = s.run_to(ref="0x1000", control="0x25a4", seconds=0.05)     # :maincpu's target
    assert out["verdict"] == "TIMEOUT" and out["control_hits"] == 30, out
    assert out["controls"] == [{"ref": "0x25a4", "cpu": MAIN, "hits_in_run": 30}], out["controls"]


def test_a_control_or_a_target_of_unknown_cpu_falls_back_to_every_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scry_mame import advance
    held: dict[dec.Owner, dict[str, int]] = {("25a4", MAIN): {}, ("4a0", SUB): {},
                                             ("600", None): {}}
    monkeypatch.setattr(mstate.STATE, "controls", held)
    assert advance.counting(SUB) == [("4a0", SUB), ("600", None)]
    assert advance.counting(None) == list(held), "the target's cpu unknown: the address alone"


def test_status_names_each_registerpoint_by_its_ref_and_cpu_and_each_cpus_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "fingerprints", {MAIN: "fp-main", SUB: "fp-sub"})
    s.regpoint_add(condition="d1==7fff")
    out = s.status()
    assert out["in_debugger"]["regpoints"] == [{"ref": "d1==7fff", "cpu": MAIN}], out["in_debugger"]
    assert out["fingerprint"] == "fp-main" and out["fingerprints"] == {MAIN: "fp-main",
                                                                        SUB: "fp-sub"}


def test_a_raw_address_is_judged_against_its_own_cpus_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A rebuild of one cpu's program moves that cpu's addresses, not the other's."""
    _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "fingerprints", {MAIN: "fp-main", SUB: "fp-sub-new"})
    assert arming.declare("breakpoint", "address", "0x542", SUB).fingerprint == "fp-sub-new"
    store = arming.store()
    store.add(_bp("0x4a0", MAIN, fingerprint="fp-main", origin="earlier"))
    store.add(_bp("0x542", SUB, fingerprint="fp-sub-old", origin="earlier"))
    store.add(_bp("0x544", SUB, fingerprint="fp-sub-new", origin="earlier"))
    listed = {(b["ref"],
               b["cpu"]): b["state"] for b in s.declaration_list("breakpoint")["breakpoints"]}
    assert listed == {("0x4a0", MAIN): "gone", ("0x542", SUB): "stale", ("0x544", SUB): "gone"}, \
        listed


def test_start_gives_each_cpu_its_own_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    args = _m68k_dual_boot(monkeypatch, tmp_path)
    main, sub = _two_tables(tmp_path)
    out = s.start(**args, symbols={"maincpu": main, "subcpu": sub})
    try:
        prints = mstate.STATE.fingerprints
        assert set(prints) == {MAIN, SUB} and prints[MAIN] != prints[SUB], prints
        assert out["declarations"]["fingerprint"] == prints[MAIN]
    finally:
        s.close()


def test_the_rearm_reads_a_row_with_no_cpu_as_the_first_cpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    arming.store().add(_bp("0x4a0", None, origin="earlier", fingerprint="fp-test"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["0x4a0"], out
    assert [d.cpu for d in arming.store().declarations()] == [MAIN]
    assert [r["owner"] for r in mstate.STATE.breakpoints.values()] == [("0x4a0", MAIN)]


def test_a_stop_is_named_by_a_declaration_of_its_own_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A name declared on the sub cpu at an address says nothing of a stop at that address on
    the main cpu, whose row another declaration holds."""
    _running(monkeypatch, tmp_path)
    add_symbol(monkeypatch, "VBLANK", 0x4A0)
    s.breakpoint_at(ref="0x4a0")
    s.breakpoint_at(ref="vblank", cpu="subcpu")
    assert breakpoints.breakpoint_name(0x4A0, MAIN) == "breakpoint at 0x4a0"
    assert breakpoints.breakpoint_name(0x4A0, SUB) == "breakpoint vblank at 0x4a0"


def test_a_clear_with_no_cpu_takes_the_ref_on_every_cpu_in_any_spelling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x400")
    s.breakpoint_at(ref="0X0400", cpu="subcpu")
    out = s.declaration_clear("breakpoint", ref="0x00400")
    assert out["declarations_cleared"] == 2 and len(out["disarmed"]) == 2, out
    assert arming.store().declarations() == [] and ses.bplist_rows == []


def test_a_range_held_by_a_declaration_of_unknown_cpu_is_held_on_every_cpu() -> None:
    """A cpu nobody could read falls back to the address, as a row's adoption does."""
    held: dict[tuple[str, str | None], dict[str, object]] = {
        ("a", MAIN): {"addr": 0x2031FC, "width": 4}}
    assert watches.range_holder(held, "width", ("b", None), 0x2031FC, 4) == "a"
    assert watches.range_holder(held, "width", ("b", SUB), 0x2031FC, 4) is None


def test_bases_or_types_naming_one_cpu_twice_are_refused(tmp_path: Path) -> None:
    from test_symbols_per_cpu import M68K_DUAL, _two_tables

    from scry_mame import symbols as syms

    main, _sub = _two_tables(tmp_path)
    typed = tmp_path / "t.types"
    typed.write_text("irq_vblank: u16\n")
    with pytest.raises(mstate.Invalid, match="names one cpu twice"):
        syms.load({"maincpu": main}, None, {"maincpu": str(typed), ":maincpu": str(typed)},
                  M68K_DUAL)


def test_run_to_declares_its_control_on_the_cpu_it_already_chose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """One decision, taken once: the control is declared on the tag the target was armed on,
    not on the cpu read again."""
    _running(monkeypatch, tmp_path)
    asked: list[str] = []
    real = breakpoints.breakpoint_at

    def spy(ses: object, ref: str, by: str, role: str = "stop", condition: str = "",
            cpu: str = "") -> dict[str, object]:
        asked.append(cpu)
        return real(ses, ref, by, role, condition, cpu)  # type: ignore[arg-type]

    monkeypatch.setattr(breakpoints, "breakpoint_at", spy)
    s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert asked == [MAIN], asked
