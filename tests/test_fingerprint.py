"""Stale is decided by a FINGERPRINT of what runs, not by which session declared.

A raw address re-resolves against nothing, so re-arming it blind on a board whose ROM or
symbol file has changed lands it on whatever the new build put there. Calling a raw address
stale whenever ANOTHER session declared it would throw away every
declaration of a board that has not changed at all. The rule is the owner's: the
fingerprint of the ROM image and the symbol file (and the system's name) stamps every
declaration, a session over the same fingerprint re-arms everything it finds, and one over
a different fingerprint leaves the raw addresses stale (a name re-resolves as always).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from server_support import _boot_args, _stub_boot  # noqa: E402
from session_doubles import refs  # noqa: E402
from test_watches import _watching  # noqa: E402

from scry_mame import arming  # noqa: E402
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import rearm as rearming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402
from scry_mame import symbols as syms  # noqa: E402


def test_a_declaration_carries_the_fingerprint_it_was_made_against() -> None:
    d = dec.Declaration("breakpoint", "address", "0x4a0", origin="s1", fingerprint="fp1")
    assert d.to_dict()["fingerprint"] == "fp1"
    assert dec.Declaration.from_dict(d.to_dict()) == d
    assert dec.Declaration.from_dict(d.to_dict()).fingerprint == "fp1"
    assert d.adopted_by("s2", "t2", "fp2").fingerprint == "fp2"
    assert d.adopted_by("s2", "t2", None).fingerprint == "fp1", "a half not carried is kept"
    assert "fingerprint" not in dec.Declaration("breakpoint", "address", "0x4a0").to_dict()


def test_stale_is_a_raw_address_against_another_fingerprint_and_nothing_else() -> None:
    addr = dec.Declaration("breakpoint", "address", "0x4a0", origin="s1", fingerprint="fp1")
    assert dec.is_stale(addr, "fp2") is True
    assert dec.is_stale(addr, "fp1") is False, "another session, same board: re-armed"
    legacy = dec.Declaration("breakpoint", "address", "0x4a0", origin="s1")
    assert dec.is_stale(legacy, "fp1") is True, "no fingerprint recorded: nobody can vouch"
    assert dec.is_stale(addr, None) is False, "a session with no build recorded judges nothing"
    name = dec.Declaration("breakpoint", "symbol", "irq_vblank", origin="s1", fingerprint="fp1")
    assert dec.is_stale(name, "fp2") is False
    watch = dec.Declaration("watch", "address", "0x203200", width=2, fmt="u16",
                            watch_mode="change", fingerprint="fp1")
    assert dec.is_stale(watch, "fp2") is True and dec.is_stale(watch, "fp1") is False
    expr = dec.Declaration("watch", "expr", "beamy", watch_mode="expr", fingerprint="fp1")
    assert dec.is_stale(expr, "fp2") is False
    read = dec.Declaration("watch", "address", "0x203200", width=2, fmt="u16", watch_mode="show",
                           fingerprint="fp1")
    assert dec.is_stale(read, "fp2") is False, "a show watch arms nothing, whatever the build"


def test_the_fingerprint_is_the_system_the_rom_and_the_symbol_file(tmp_path: Path) -> None:
    rom = tmp_path / "rom.bin"
    rom.write_bytes(b"\x00" * 64)
    sym = tmp_path / "s.yaml"
    sym.write_text("- addr: 0\n  name: a\n")
    one = syms.fingerprint("m68k", rom, sym)
    assert one == syms.fingerprint("m68k", rom, sym), "deterministic"
    assert one != syms.fingerprint("v30", rom, sym), "the system is part of it"
    rom.write_bytes(b"\x00" * 63 + b"\x01")
    assert one != syms.fingerprint("m68k", rom, sym), "a byte of ROM changes it"
    two = syms.fingerprint("m68k", rom, sym)
    sym.write_text("- addr: 2\n  name: a\n")
    assert two != syms.fingerprint("m68k", rom, sym), "a moved symbol changes it"
    assert syms.fingerprint("m68k", rom, None) != syms.fingerprint("m68k", rom, sym)


def test_start_stamps_the_session_and_its_declarations_with_the_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    image = bytes(range(256))
    _stub_boot(monkeypatch, tmp_path, image, 0)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    sym = tmp_path / "s.yaml"
    sym.write_text("- addr: 0x400\n  name: irq_vblank\n")
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym))
    try:
        fp = out["declarations"]["fingerprint"]
        assert fp == mstate.STATE.fingerprint() and len(fp) == 16
        assert arming.declare("breakpoint", "address", "0x4a0").fingerprint == fp
    finally:
        s.close()
    assert mstate.STATE.fingerprint() is None, "cleared with the session"


def test_a_raw_address_re_arms_over_the_same_fingerprint_and_is_stale_over_another(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "fingerprints", {":maincpu": "fp1"})
    store = arming.store()
    store.add(dec.Declaration("breakpoint", "address", "0x4a0", origin="earlier",
                              fingerprint="fp1"))
    store.add(dec.Declaration("watch", "address", "0x203200", width=2, fmt="u16",
                              watch_mode="change", origin="earlier", fingerprint="fp1"))
    store.add(dec.Declaration("breakpoint", "address", "0x25a4", origin="earlier",
                              fingerprint="fp0"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["0x4a0", "0x203200"] and refs(out["stale"]) == ["0x25a4"]
    listed = {b["ref"]: b["state"] for b in s.declaration_list("breakpoint")["breakpoints"]}
    assert listed == {"0x4a0": "armed", "0x25a4": "stale"}
    why = next(b["why"] for b in s.declaration_list("breakpoint")["breakpoints"]
               if b["ref"] == "0x25a4")
    assert "another build" in why
    # Declaring the stale one again adopts it under this fingerprint.
    assert s.breakpoint_at(ref="0x25a4")["status"] == "ok"
    kept = next(d for d in arming.store().declarations() if d.ref == "0x25a4")
    assert kept.fingerprint == "fp1"
