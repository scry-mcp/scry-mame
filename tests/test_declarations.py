"""The persistent declarations store, keyed by system and symbol file, and the breakpoints
declared by NAME through it.

Every case was written RED before the code. What they guard: a declaration outliving the
session that made it and re-resolving against the next build; two guests never inheriting
each other's; a corrupt file refused by name and never discarded; and a breakpoint that
is an INTENT the debugger's own list is read back against.
"""

import dataclasses
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import (
    add_symbol,
    bplist_add,  # noqa: E402
    bplist_answer,  # noqa: E402
    captured,  # noqa: E402
    control_console,  # noqa: E402
    fake_mame,  # noqa: E402
    refs,
    refused,  # noqa: E402
    regpoint_console,  # noqa: E402
    use_table,
    wplist_answer,  # noqa: E402
)
from test_server import _boot_args, _never_spawns, _stub_boot  # noqa: E402
from test_watches import _watching  # noqa: E402

import gdb_session as g  # noqa: E402
import mame_arming as arming  # noqa: E402
import mame_breakpoints as breakpoints  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_lists as mlists  # noqa: E402
import mame_rearm as rearming  # noqa: E402
import mame_running as running  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_symbols as syms  # noqa: E402
import server as s  # noqa: E402

BPLIST_NONE = "No breakpoints currently installed\n\n"


def _watch(tmp_path: Path) -> dec.Declaration:
    return dec.Declaration("watch", "symbol", "frame", width=4, fmt="u32", watch_mode="show",
                           created_at="t", origin="s1")


# ------------------------------------------------------------------ the file behind it


def test_a_declaration_survives_a_new_store_over_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "declarations.json"
    store = dec.DeclarationStore("m68k-dual /repo/symbols.yaml", path)
    assert store.persistent is True
    store.add(_watch(tmp_path))
    store.add(dec.Declaration("breakpoint", "address", "0x4a0", origin="s1"))
    again = dec.DeclarationStore("m68k-dual /repo/symbols.yaml", path)
    assert again.declarations() == store.declarations()
    assert again.declarations()[0].origin == "s1", "the stamp travels too"
    assert again.discard([d for d in again.declarations() if d.ref == "0x4a0"]) == 1
    assert len(dec.DeclarationStore("m68k-dual /repo/symbols.yaml", path).declarations()) == 1


def test_a_replaced_declaration_is_on_disk_in_one_write_and_keeps_what_the_new_one_lacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    path = tmp_path / "declarations.json"
    store = dec.DeclarationStore("m68k game.yaml", path)
    old = dec.Declaration("breakpoint", "address", "0x4a0", condition="w@0x2031fc==1",
                          created_at="t1", origin="s1", fingerprint="fp")
    store.add(old)
    writes: list[str] = []
    real = os.replace

    def counted(src: str, dst: str) -> None:
        writes.append(str(dst))
        real(src, dst)

    monkeypatch.setattr(os, "replace", counted)
    new = dec.Declaration("breakpoint", "address", "0x4a0", condition="w@frame_lo==1", origin="s2")
    store.replace(old, new)
    assert writes == [str(path)], "one write"
    (held,) = dec.DeclarationStore("m68k game.yaml", path).declarations()
    assert (held.condition, held.origin, held.created_at, held.fingerprint) == (
        "w@frame_lo==1", "s2", "t1", "fp")
    with pytest.raises(dec.DeclarationError, match="nothing to replace"):
        store.replace(old, new)


def test_two_keys_do_not_see_each_others_declarations_and_neither_clobbers(
    tmp_path: Path,
) -> None:
    """Two boards over one map are two keys (the system tells them apart); two maps of one
    board are two keys (the path does). A store persists ONLY its own key: writing the whole
    in-memory picture would erase every key this store never loaded."""
    path = tmp_path / "declarations.json"
    a = dec.DeclarationStore("wheelfir /repo/map", path)
    b = dec.DeclarationStore("pwball /repo/map", path)
    a.add(dec.Declaration("breakpoint", "symbol", "draw", origin="s1"))
    b.add(dec.Declaration("breakpoint", "symbol", "sound", origin="s1"))
    a.add(dec.Declaration("breakpoint", "symbol", "input", origin="s1"))
    assert [d.ref for d in dec.DeclarationStore("wheelfir /repo/map", path).declarations()] == [
        "draw", "input"]
    assert [d.ref for d in dec.DeclarationStore("pwball /repo/map", path).declarations()] == [
        "sound"]
    assert dec.DeclarationStore("wheelfir /other/map", path).declarations() == []


def test_a_bench_copy_of_a_symbol_file_is_a_store_of_its_own(tmp_path: Path) -> None:
    """The live tier boots on a COPY of a project's symbol file, byte for byte the same, and the
    key is the resolved path, so the copy's store neither sees the rows a session on the
    project's own file declared nor clears them."""
    path = tmp_path / "declarations.json"
    project, copy = tmp_path / "checkout" / "symbols.yaml", tmp_path / "bench" / "symbols.yaml"
    for p in (project, copy):
        p.parent.mkdir()
        p.write_text("symbols: []\n")
    owner = dec.DeclarationStore(dec.store_key("m68k-dual", str(project)), path)
    owner.add(dec.Declaration("breakpoint", "address", "0x4a0", origin="owner"))
    bench = dec.DeclarationStore(dec.store_key("m68k-dual", str(copy)), path)
    assert bench.declarations() == []
    bench.add(dec.Declaration("breakpoint", "address", "0x400", origin="tier"))
    assert bench.discard(bench.declarations()) == 1
    assert [d.ref for d in dec.DeclarationStore(dec.store_key("m68k-dual", str(project)),
                                                path).declarations()] == ["0x4a0"]


@pytest.mark.parametrize("text, why", [
    ("[1, 2]", "not a mapping"),
    ('{"k": "oops"}', "not a list"),
    ('{"k": [1]}', "not an object"),
    ('{"k": [{"kind": "watch", "by": "symbol", "ref": "x", "width": "w"}]}', "non-integer"),
    ('{"k": [{"kind": "watch", "by": "symbol", "width": 4, "fmt": "u32", "watch_mode": "show"}]}',
     "lacks `ref`"),
    ('{"k": [{"by": "symbol", "ref": "x"}]}', "lacks `kind`"),
    ("{not json", "could not be read"),
])
def test_a_corrupt_file_is_refused_by_name_and_never_discarded(
    tmp_path: Path, text: str, why: str,
) -> None:
    path = tmp_path / "declarations.json"
    path.write_text(text)
    with pytest.raises(dec.DeclarationError, match=why):
        dec.DeclarationStore("k", path)
    assert path.read_text() == text, "fix or remove it, never lose what it holds"


def test_a_write_is_atomic_and_a_failed_one_leaves_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "state" / "declarations.json"
    store = dec.DeclarationStore("k", path)
    store.add(_watch(tmp_path))
    assert json.loads(path.read_text())["k"][0]["ref"] == "frame"
    assert [p.name for p in path.parent.iterdir()] == ["declarations.json"]

    def boom(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        store.add(dec.Declaration("breakpoint", "symbol", "x"))
    assert [p.name for p in path.parent.iterdir()] == ["declarations.json"]
    assert json.loads(path.read_text())["k"][0]["ref"] == "frame", "the file is whole"


def test_the_default_path_is_a_state_directory_and_the_key_is_system_and_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert dec.default_path() == tmp_path / "xdg" / "mame-debug" / "declarations.json"
    monkeypatch.delenv("XDG_STATE_HOME")
    assert dec.default_path() == Path.home() / ".local/state/mame-debug/declarations.json"
    sym = tmp_path / "a" / ".." / "symbols.yaml"
    assert dec.store_key("m68k-dual", str(sym)) == f"m68k-dual {tmp_path / 'symbols.yaml'}"
    with pytest.raises(dec.DeclarationError, match="system"):
        dec.store_key("", "x")


# --------------------------------------------------------------- what start does with it


def test_start_opens_the_store_keyed_by_system_and_symbol_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With a symbol file the declarations PERSIST, keyed by the system and the RESOLVED path
    of the file, so two spellings of one file are one key; the reply says so and names the
    file and how many declarations it found. Without a file there is no key to re-resolve
    anything by, and the store lives as long as the session: the honest answer, said."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    image = bytes(range(64))
    ses = _stub_boot(monkeypatch, tmp_path, image, at=0)
    # The re-arm at start asks the debugger's list and arms; this session has no wire.
    rows = ["No breakpoints currently installed\n\n"]

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "bplist":
            return rows[0]
        if command.startswith("bp "):
            addr = int(command.split()[1].split(":", 1)[0], 16)
            rows[0] = f"Device ':maincpu' breakpoints:\n    1 @ {addr:06X}\n\n"
            return captured("bpset.set.txt")
        return "No watchpoints currently installed\n\n"

    monkeypatch.setattr(ses, "monitor", monitor)
    sym = tmp_path / "game.yaml"
    sym.write_text("- addr: 0x400\n  name: irq_vblank\n")
    path = tmp_path / "xdg" / "mame-debug" / "declarations.json"
    key = f"m68k {sym.resolve()}"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({key: [{"kind": "breakpoint", "by": "symbol", "ref": "irq_vblank",
                                       "origin": "earlier"}]}))
    (tmp_path / "sub").mkdir()
    out = s.start(**_boot_args(tmp_path, image), symbols=str(tmp_path / "sub" / ".." / "game.yaml"))
    try:
        assert out["declarations"] == {"persistent": True, "path": str(path), "key": key,
                                       "held": 1, "fingerprint": mstate.STATE.fingerprint(),
                                       "rearm": {"rearmed": [{
                                           "ref": "irq_vblank", "by": "symbol",
                                           "cpu": {"available": False,
                                                   "why": arming.NO_DECL_CPU_WHY},
                                           "created_at": {"available": False,
                                                          "why": arming.UNDATED_WHY},
                                           "origin": "earlier", "inherited": True,
                                           "age_s": {"available": False,
                                                     "why": arming.UNDATED_WHY}}], "stale": [],
                                                 "unresolved": [], "unarmable": [],
                                                 "evaluated": []},
                                       "comments": {"rearmed": [], "stale": [],
                                                    "unresolved": [], "unarmable": []}}
        assert mstate.STATE.store is not None and mstate.STATE.store.persistent
        assert mstate.STATE.session_origin
    finally:
        s.close()
    after = mstate.STATE           # a fresh name, or mypy keeps the narrowing from above
    assert after.store is None and after.session_origin is None
    out = s.start(**_boot_args(tmp_path, image))
    try:
        assert out["declarations"]["persistent"] is False and out["declarations"]["held"] == 0
        assert "no `symbols` file" in out["declarations"]["path"]["why"]
        assert "why" not in out["declarations"], "the reason sits where the path would"
    finally:
        s.close()


def test_a_corrupt_store_refuses_start_before_the_emulator_is_spawned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    sym = tmp_path / "game.yaml"
    sym.write_text("- addr: 0x400\n  name: irq_vblank\n")
    path = tmp_path / "xdg" / "mame-debug" / "declarations.json"
    path.parent.mkdir(parents=True)
    path.write_text("[]")
    refused("not a mapping",
    s.start(binary=str(binary), system="none", rompath=str(tmp_path),
            reference_rom=str(rom), reference_addr="0x10", symbols=str(sym)))
    assert mstate.STATE.scratch is None


# --------------------------------------------------- breakpoints as declarations by name


def test_breakpoint_at_stores_a_declaration_by_name_and_lists_it_against_bplist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    out = s.breakpoint_at(ref="frame_lo")
    assert out["armed"] is True and out["addr"] == "0x002031fc" and out["by"] == "symbol"
    assert out["stored"] is True and out["already_stored"] is False and out["state"] == "armed"
    assert out["entry"] == "1 @ 2031FC", "the debugger's row, read back"
    assert out["summary"] == "breakpoint_at frame_lo: armed at 0x002031fc"
    again = s.breakpoint_at(ref="frame_lo")
    assert again["already_stored"] is True and ses.armed.count((0x2031FC, False)) == 1, (
        "a re-declaration adopts, and does not stack a second Z0")
    by_addr = s.breakpoint_at(ref="0x4a0")
    assert by_addr["by"] == "address" and by_addr["addr"] == "0x000004a0"
    unresolved = s.breakpoint_at(ref="scene_id")
    assert unresolved["armed"] is False and unresolved["state"] == "unresolved"
    assert unresolved["stored"] is True
    listed = s.breakpoint_list()
    assert [(b["ref"], b["by"], b["state"]) for b in listed["breakpoints"]] == [
        ("frame_lo", "symbol", "armed"), ("0x4a0", "address", "armed"),
        ("scene_id", "symbol", "unresolved")]
    assert listed["breakpoints"][0]["entry"] == "1 @ 2031FC" and listed["foreign"] == []
    assert listed["summary"] == "breakpoint_list: 3 declared, 2 armed"
    st = s.status()
    assert st["in_debugger"]["breakpoints"] == [{"ref": "0x4a0", "cpu": ":maincpu"},
                                                {"ref": "frame_lo", "cpu": ":maincpu"}], (
        "what is armed, in address order")
    assert st["in_debugger"]["watches"] == [] and st["in_debugger"]["regpoints"] == []
    assert not {"breakpoints_armed", "regpoints", "armed"} & set(st), "one key for the families"
    ses.bplist_rows.append("    9 @ 0025A4")
    assert s.breakpoint_list()["foreign"] == ["9 @ 0025A4"]


def test_breakpoint_clear_by_ref_disarms_and_drops_the_declaration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.breakpoint_at(ref="frame_lo")
    s.breakpoint_at(ref="0x4a0")
    out = s.breakpoint_clear(ref="frame_lo")
    assert out["disarmed"] == ["1 @ 2031FC"] and out["declarations_cleared"] == 1
    assert out["summary"] == "breakpoint_clear frame_lo: 1 cleared, 1 disarmed"
    assert "bpclear 0x1" in ses.commands and ses.bplist_rows == ["    2 @ 0004A0"]
    refused = s.breakpoint_clear(ref="nothing")
    assert refused["status"] == "INVALID" and "'0x4a0'" in refused["message"]
    assert s.breakpoint_clear(all=True)["disarmed"] == ["2 @ 0004A0"]
    assert s.breakpoint_list()["breakpoints"] == [] and mstate.STATE.breakpoints == {}
    assert s.breakpoint_clear(all=True)["disarmed"] == [], "an empty store's nothing is ok"
    # `disarmed` is the list's answer: a row the console kept is not claimed gone.
    s.breakpoint_at(ref="0x4a0")
    real = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda command, timeout=10.0: (
        captured("bpclear.cleared.txt").replace(" 1 ", " 3 ") if command.startswith("bpclear ")
        else real(command, timeout)))
    kept = s.breakpoint_clear(all=True)
    assert kept["declarations_cleared"] == 1 and kept["disarmed"] == []


def test_a_stop_at_a_declared_breakpoint_is_attributed_by_its_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    s.breakpoint_at(ref="frame_lo")
    ses.pcs = [0xF2034, 0x2031FC]
    s.resume()
    ses.stops_after_polls = 1
    assert s.status()["stopped_on_its_own"]["how"] == "breakpoint frame_lo at 0x2031fc"


def test_breakpoint_list_names_the_odd_states_and_skips_the_watches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A watch declaration is not a breakpoint and is skipped by the list and the clear; a
    breakpoint whose row the debugger lost is `gone`; a raw address declared over another
    build is `stale`; a stop at an address-declared breakpoint is named bare, as before."""
    ses = _watching(monkeypatch, tmp_path)
    store = arming.store()
    s.watch_add(ref="frame_lo", mode="show", length=4)
    s.breakpoint_at(ref="0x4a0")
    ses.bplist_rows.clear()                                    # the debugger lost the row
    store.add(dec.Declaration("breakpoint", "address", "0x25a4", origin="another"))
    listed = s.breakpoint_list()
    assert [(b["ref"], b["state"]) for b in listed["breakpoints"]] == [
        ("0x4a0", "gone"), ("0x25a4", "stale")]
    assert "another build" in listed["breakpoints"][1]["why"]
    cleared = s.breakpoint_clear(all=True)
    assert cleared["disarmed"] == [] and cleared["declarations_cleared"] == 2
    assert cleared["summary"] == "breakpoint_clear all: 2 cleared, 0 disarmed"
    assert [d.kind for d in store.declarations()] == ["watch"], "the watch stays"
    s.breakpoint_at(ref="0x4a0")
    assert breakpoints.breakpoint_name(0x4A0, ":maincpu") == "breakpoint at 0x4a0", (
        "declared by address this session: the bare address, nothing inherited")
    assert breakpoints.breakpoint_name(0x25A4, ":maincpu") is None, "not armed by this session"
    # A symbol declared AFTER an address at the same place is REFUSED naming the holder
    # (one row, one declaration, as for a watch); a store from before that rule still names
    # a stop by the name it holds there, whatever was declared first.
    add_symbol(monkeypatch, "VBLANK_CTL", 0x4A0)
    refused(re.escape("already declared under '0x4a0': one breakpoint row is one declaration, so "
                      "`breakpoint_clear(ref='0x4a0', cpu=\":maincpu\")` frees it, or use that "
                      "ref"), s.breakpoint_at(ref="vblank_ctl"))
    store.add(dec.Declaration("breakpoint", "symbol", "vblank_ctl", origin="s1", cpu=":maincpu"))
    assert breakpoints.breakpoint_name(0x4A0, ":maincpu") == "breakpoint vblank_ctl at 0x4a0"
    refused("by is one of .*got 'index'",
    s.breakpoint_at(ref="0x4a0", by="index"))
    with pytest.raises(mstate.Invalid, match="bplist"):
        mlists.parse_bplist("Unknown command\n")
    monkeypatch.setattr(mstate.STATE, "store", None)
    assert breakpoints.breakpoint_name(0x4A0, ":maincpu") is None
    with pytest.raises(mstate.Invalid, match="no machine"):
        arming.store()


# ------------------------------------------------ re-resolution and re-arming at start


def _armable_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> tuple[bytes, Path, Path, list[tuple[str, int, int, bool]]]:
    """A stub boot whose debugger keeps `bplist` and `wplist` rows for what is armed, with
    0x400's write side unmapped: the image, the symbol file, the store's path (its folder
    made, the file not written) and the log of every arm, for a `start` that re-arms."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    image = bytes(range(64))
    ses = _stub_boot(monkeypatch, tmp_path, image, at=0)
    ses._layouts[1] = g.Layout({}, 0, "m68k", [])      # a 68000, no register to decode
    armed: list[tuple[str, int, int, bool]] = []
    # ONE console for both lists, as MAME's is: `bp`/`wp` arm a row, `bpclear`/`wpclear` drop
    # one by index (`control_console`), each logged as `(family, addr, length, removed)`.
    lists = SimpleNamespace(bplist_rows=[], bp_next_index=1, temps={}, wplist_rows=[],
                            wp_next_index=1, armed=[], watchpoints=[])

    def plain(addr: int) -> None:
        lists.armed.append((addr, False))
        bplist_add(lists, addr)

    lists.breakpoint = plain
    rp = SimpleNamespace(rplist_rows=[], rp_next_index=1)

    def monitor(command: str, timeout: float = 10.0) -> str:
        if (listed := regpoint_console(rp, command)) is not None:
            return listed
        bps, wps = len(lists.armed), len(lists.watchpoints)
        if (taken := control_console(lists, command)) is not None:
            armed.extend(("bp", a, 0, gone) for a, gone in lists.armed[bps:])
            armed.extend(("wp", a, n, gone) for a, n, gone in lists.watchpoints[wps:])
            return taken
        if command == "bplist":
            return bplist_answer(lists.bplist_rows, getattr(lists, "bp_devices", None))
        if command == "wplist":
            return wplist_answer(lists.wplist_rows, getattr(lists, "wp_devices", None))
        if command.startswith("map "):
            unmapped = int(command[4:].split(":", 1)[0], 16) == 0x400
            return (f"  Write: x -> {'unmapped' if unmapped else 'memory@200000'}\n")
        return ""

    monkeypatch.setattr(ses, "monitor", monitor)
    sym = tmp_path / "game.yaml"
    sym.write_text("- addr: 0x400\n  name: irq_vblank\n- addr: 0x2031fc\n  name: frame_lo\n")
    path = tmp_path / "xdg" / "mame-debug" / "declarations.json"
    path.parent.mkdir(parents=True)
    return image, sym, path, armed


def test_the_armable_boot_numbers_its_rows_as_mame_does_and_drops_one_on_a_removal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The fidelity of `_armable_boot`: one hex counter for every `bp`, never reused, and a
    `bpclear` of an index takes that row away instead of adding another."""
    image, sym, _path, armed = _armable_boot(monkeypatch, tmp_path)
    s.start(**_boot_args(tmp_path, image), symbols=str(sym))
    try:
        ses = mstate.STATE.ses
        assert ses is not None
        for addr in range(0x500, 0x500 + 2 * 9, 2):
            ses.monitor(f"bp {addr:x}::maincpu")
        ses.monitor("bp 4a0,d0==1")
        ses.monitor("bpclear 0x1")
        ses.monitor("bp 600")
        rows = ses.monitor("bplist").splitlines()
        assert rows[0] == "Device ':maincpu' breakpoints:"
        assert rows[1:3] == ["    A @ 0004A0 if d0==1", "    2 @ 000502"], (
            "by address, and the first row gone with its `bpclear`")
        assert rows[-2] == "    B @ 000600", rows
        assert armed[-2:] == [("bp", 0x500, 0, True), ("bp", 0x600, 0, False)]
    finally:
        s.close()


def test_start_re_resolves_and_re_arms_the_store_and_reports_what_it_could_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Every declaration the store held is re-resolved against the table this start loaded
    and re-armed when it can be: a symbol breakpoint and a symbol change watch are armed and
    read back; a raw address stored with no build recorded is stale, listed and not armed; a
    name this build lacks is unresolved, kept; a change watch whose write side is unmapped NOW
    is unarmable with its why; a show watch needs no arming. Nothing is dropped and every one is
    named in the reply."""
    image, sym, path, armed = _armable_boot(monkeypatch, tmp_path)
    held = [
        {"kind": "breakpoint", "by": "symbol", "ref": "irq_vblank", "origin": "earlier"},
        {"kind": "breakpoint", "by": "address", "ref": "25a4", "origin": "earlier"},
        {"kind": "breakpoint", "by": "symbol", "ref": "scene_id", "origin": "earlier"},
        {"kind": "watch", "by": "symbol", "ref": "frame_lo", "width": 4, "fmt": "u32",
         "watch_mode": "change", "origin": "earlier"},
        {"kind": "watch", "by": "address", "ref": "203200", "width": 2, "fmt": "u16",
         "watch_mode": "change", "origin": "earlier"},
        {"kind": "watch", "by": "symbol", "ref": "irq_vblank", "width": 2, "fmt": "u16",
         "watch_mode": "change", "origin": "earlier"},
        {"kind": "watch", "by": "symbol", "ref": "irq_vblank", "width": 4, "fmt": "u32",
         "watch_mode": "show", "origin": "earlier"},
    ]
    path.write_text(json.dumps({f"m68k {sym.resolve()}": held}))
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym))
    try:
        rearm = out["declarations"]["rearm"]
        assert refs(rearm["rearmed"]) == ["irq_vblank", "frame_lo"]
        assert refs(rearm["stale"]) == ["0x25a4", "0x203200"]
        assert refs(rearm["unresolved"]) == ["scene_id"]
        assert [u["ref"] for u in rearm["unarmable"]] == ["irq_vblank"]
        assert "unmapped" in rearm["unarmable"][0]["why"]
        assert refs(rearm["evaluated"]) == ["irq_vblank"], "a show watch needs no arming"
        assert armed == [("bp", 0x400, 0, False), ("wp", 0x2031FC, 4, False)]
        assert mstate.STATE.breakpoints == {1: {"owner": ("irq_vblank", None), "addr": 0x400,
                                                "cpu": ":maincpu"}}
        assert mstate.STATE.armed_watches[("frame_lo", None)]["index"] == 1
        assert out["declarations"]["held"] == 7, "nothing was dropped"
        assert out["summary"].endswith(
            "pc 0x00000000, 2 declarations re-armed: irq_vblank, frame_lo"), out["summary"]
        listed = s.breakpoint_list()
        assert [(b["ref"], b["state"]) for b in listed["breakpoints"]] == [
            ("irq_vblank", "armed"), ("0x25a4", "stale"), ("scene_id", "unresolved")]
        # The show watch is placed `evaluated` and READ by the listing on a stopped machine,
        # and this stub holds no memory there: the stub's refusal, never a zero.
        rows = s.watch_list()["watches"]
        assert [w["state"] for w in rows] == ["armed", "stale", "gone", "evaluated"]
        assert rows[3]["reading"]["available"] is False
        # THE ONE HAS NOT BEEN DROPPED: it re-resolves next start, or the caller clears it.
        assert len(json.loads(path.read_text())[f"m68k {sym.resolve()}"]) == 7
    finally:
        s.close()


def _start_over_an_earlier_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rows: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """`start` over a store holding `rows`, declared by an EARLIER session over this very
    build: the fingerprint, and what `start` answered."""
    image, sym, path, _armed = _armable_boot(monkeypatch, tmp_path)
    args = _boot_args(tmp_path, image)
    same = syms.fingerprint("m68k", Path(args["reference_rom"]), sym.resolve())
    path.write_text(json.dumps({f"m68k {sym.resolve()}": [
        {**row, "origin": "earlier", "fingerprint": same} for row in rows]}))
    return same, s.start(**args, symbols=str(sym))


def _stored_conditions(out: dict[str, Any]) -> dict[str, str]:
    """The condition of every breakpoint row in the store FILE `start` reported, by ref."""
    raw = json.loads(Path(out["declarations"]["path"]).read_text())
    (rows,) = raw.values()
    return {r["ref"]: r.get("condition", "") for r in rows if r["kind"] == "breakpoint"}


def test_the_store_file_holds_a_condition_as_typed_and_adopts_a_row_written_before_that(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A condition is an INTENT like the ref beside it: the file keeps the name the caller
    typed, so the next build's address goes to the console. A row an earlier server stored
    with the address already in place still loads and re-arms (substituting it changes
    nothing), and declaring it again BY NAME is the same declaration: adopted, and its text
    replaced by what was typed. Any other condition under that ref is still refused."""
    _same, out = _start_over_an_earlier_store(monkeypatch, tmp_path, [
        {"kind": "breakpoint", "by": "symbol", "ref": "irq_vblank",
         "condition": "w@0x2031fc==0x25"},
    ])
    try:
        assert refs(out["declarations"]["rearm"]["rearmed"]) == ["irq_vblank"], out["declarations"]
        fresh = s.breakpoint_at(ref="0x4a0", condition=" w@frame_lo==1 ")
        assert fresh["status"] == "ok" and fresh["condition"] == "w@0x2031fc==1", fresh
        assert fresh["condition_typed"] == "w@frame_lo==1"
        again = s.breakpoint_at(ref="irq_vblank", condition="w@frame_lo==0x25")
        assert again["status"] == "ok" and again["already_stored"] is True, again
        assert again["condition"] == "w@0x2031fc==0x25"
        assert again["condition_typed"] == "w@frame_lo==0x25"
        assert _stored_conditions(out) == {"irq_vblank": "w@frame_lo==0x25",
                                           "0x4a0": "w@frame_lo==1"}
        refused("breakpoint_clear", s.breakpoint_at(ref="irq_vblank", condition="w@frame_lo==0x26"))
        assert _stored_conditions(out)["irq_vblank"] == "w@frame_lo==0x25", "and nothing moved"
    finally:
        s.close()


def test_a_refused_re_declaration_leaves_the_store_file_as_it_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row written with the address in place, declared again by name while the console
    cannot evaluate the condition: the call is refused, and the file holds what it held."""
    _same, out = _start_over_an_earlier_store(monkeypatch, tmp_path, [
        {"kind": "breakpoint", "by": "symbol", "ref": "irq_vblank",
         "condition": "w@0x2031fc==0x25"},
    ])
    try:
        ses = mstate.STATE.ses
        assert ses is not None
        taken = ses.monitor
        monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: (
            captured("print.braces.malformed.txt") if c.startswith("print {")
            else taken(c, timeout)))
        refused("did not evaluate", s.breakpoint_at(ref="irq_vblank",
                                                    condition="w@frame_lo==0x25"))
        assert _stored_conditions(out) == {"irq_vblank": "w@0x2031fc==0x25"}
    finally:
        s.close()


def test_a_raw_address_over_the_same_build_is_rearmed_and_every_row_says_it_was_inherited(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE PATH A LIVE SESSION HIT, which no case ran: a raw address stored by an earlier
    session WITH the fingerprint of this very build. It is `rearmed`, never `stale` (stale
    is a DIFFERENT build, not a raw address), and from then on nothing in a list row told it
    from one declared this session. Every row now says `inherited`, true for what the store
    brought back and false for a declaration made here."""
    same, out = _start_over_an_earlier_store(monkeypatch, tmp_path, [
        {"kind": "breakpoint", "by": "address", "ref": "4a0"},
        {"kind": "watch", "by": "address", "ref": "203200", "width": 2, "fmt": "u16",
         "watch_mode": "change"},
    ])
    try:
        assert out["declarations"]["fingerprint"] == same, "the case is the same build"
        rearm = out["declarations"]["rearm"]
        assert refs(rearm["rearmed"]) == ["0x4a0", "0x203200"] and refs(rearm["stale"]) == [], rearm
        assert s.breakpoint_at(ref="frame_lo")["status"] == "ok"
        assert [(b["ref"], b["inherited"]) for b in s.breakpoint_list()["breakpoints"]] == [
            ("0x4a0", True), ("frame_lo", False)]
        assert [(w["ref"], w["inherited"]) for w in s.watch_list()["watches"]] == [
            ("0x203200", True)]
    finally:
        s.close()


def test_a_stop_at_an_inherited_raw_address_breakpoint_names_it_inherited(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A raw address the store brought back over the same build cuts a run like a named one
    does, and the caller never typed it this session: the stop's `how` keeps the bare-address
    name and says it was inherited, as a named breakpoint's does."""
    _same, out = _start_over_an_earlier_store(
        monkeypatch, tmp_path, [{"kind": "breakpoint", "by": "address", "ref": "4a0"}])
    try:
        assert refs(out["declarations"]["rearm"]["rearmed"]) == ["0x4a0"], out["declarations"]
        how = running.attribute(0x4A0, ":maincpu")
        assert how.startswith("breakpoint at 0x4a0 (a PERSISTENT declaration"), how
    finally:
        s.close()


def test_a_stop_is_named_by_the_declaration_that_speaks_for_the_armed_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two declarations at one pc, one of them inherited: the inherited clause is the one of
    the declaration that names the stop, never the other's. A name declared this session
    beats an inherited address; between two addresses (a store from before the one-row
    rule), the owner of the armed row beats one listed before it."""
    _watching(monkeypatch, tmp_path)
    store = arming.store()
    main = ":maincpu"
    store._items.append(dec.Declaration("breakpoint", "address", "0x4a0", origin="earlier",
                                        fingerprint="fp-old", cpu=main))
    store._items.append(dec.Declaration("breakpoint", "address", "0x4a0", origin="s1",
                                        fingerprint="fp-test", cpu=main))
    monkeypatch.setitem(mstate.STATE.breakpoints, 1,
                        {"owner": ("0x4a0", main), "addr": 0x4A0, "cpu": main})
    assert breakpoints.breakpoint_name(0x4A0, ":maincpu") == "breakpoint at 0x4a0", (
        "the owner is this session's")
    store._items.append(dec.Declaration("breakpoint", "address", "0x04a0", origin="earlier",
                                        fingerprint="fp-old", cpu=main))
    assert breakpoints.breakpoint_name(0x4A0, ":maincpu") == "breakpoint at 0x4a0", (
        "nor one listed after it")
    add_symbol(monkeypatch, "VBLANK_CTL", 0x4A0)
    store._items.append(dec.Declaration("breakpoint", "symbol", "vblank_ctl", origin="s1",
                                        cpu=main))
    assert breakpoints.breakpoint_name(0x4A0, ":maincpu") == "breakpoint vblank_ctl at 0x4a0"


def test_rearm_reads_each_list_once_and_reports_a_row_the_debugger_did_not_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    store = arming.store()
    # THREE ADDRESSES, one per name: `len(name)` here once gave all three the same one,
    # which the alias rule now refuses, so the case had been passing on a coincidence.
    for i, name in enumerate(("irq_a", "irq_b", "irq_c")):
        add_symbol(monkeypatch, name.upper(), 0x1000 + i * 0x10)
        store.add(dec.Declaration("breakpoint", "symbol", name, origin="s1"))
    store.add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                              watch_mode="change", origin="s1"))
    store.add(dec.Declaration("watch", "address", "0x203200", width=2, fmt="u16",
                              watch_mode="change", origin="s1", fingerprint="fp-test"))
    monkeypatch.setattr(ses, "watchpoint", lambda addr, length, remove=False, cpu=None,
                        index=None: None)
    ses.commands.clear()
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["irq_a", "irq_b", "irq_c"]
    assert [u["ref"] for u in out["unarmable"]] == ["frame_lo", "0x203200"]
    assert all("wplist` does not list" in u["why"] for u in out["unarmable"])
    assert ses.commands.count("bplist") == 2 and ses.commands.count("wplist") == 2, (
        "one read before the pass and one read back after it, per list")


def test_a_breakpoint_the_debugger_did_not_list_is_invalid_at_arming_and_unarmable_at_rearm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "breakpoint", lambda addr, remove=False: None)
    out = s.breakpoint_at(ref="frame_lo")
    assert out["status"] == "INVALID" and "bplist" in out["message"]
    arming.store().add(dec.Declaration("breakpoint", "symbol", "copy_in_rom", origin="s1"))
    back = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert [u["ref"] for u in back["unarmable"]] == ["frame_lo", "copy_in_rom"]
    assert all("`bplist` does not list" in u["why"] for u in back["unarmable"])
    # Two names, the first at another address: the loop looks past it.
    monkeypatch.setattr(ses, "breakpoint", lambda addr, remove=False:
                        ses.bplist_rows.append(f"    9 @ {addr:06X}"))
    s.breakpoint_at(ref="copy_in_rom")
    assert breakpoints.breakpoint_name(0x400, ":maincpu") == "breakpoint copy_in_rom at 0x400"


def test_a_breakpoint_the_debugger_did_not_list_owns_no_row_that_appears_there_later(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `bp` the list never showed armed nothing, so a row somebody types at that address
    afterwards is THEIRS: listed `foreign`, and the declaration is `gone`, never `armed`."""
    ses = _watching(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "breakpoint", lambda addr, remove=False: None)
    refused("bplist", s.breakpoint_at(ref="frame_lo"))
    ses.bplist_rows.append("    9 @ 2031FC")
    listed = s.breakpoint_list()
    assert [(b["ref"], b["state"]) for b in listed["breakpoints"]] == [("frame_lo", "gone")]
    assert listed["foreign"] == ["9 @ 2031FC"]
    assert breakpoints.breakpoint_name(0x2031FC, ":maincpu") is None


def test_one_breakpoint_row_is_one_declaration_at_declaration_and_at_rearm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A name and the address it holds are two declarations over ONE `Z0`: clearing either
    sent the `z0` and left the other declared over a row the debugger no longer had, in
    silence. The watch family refuses a range another declaration already arms; the
    breakpoints refuse the same way now, and the re-arm of a store that predates the rule
    files the second `unarmable` naming the first instead of stacking a second row. Two
    SPELLINGS of one address (`0x4a0`, `0X04A0`) are one declaration, adopted, never two
    (measured by a fresh client against a store an earlier session had written)."""
    ses = _watching(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    again = s.breakpoint_at(ref="0X04A0")
    assert again["already_stored"] is True and again["ref"] == "0x4a0", again
    assert [d.ref for d in arming.store().declarations()] == ["0x4a0"]
    assert len(ses.bplist_rows) == 1
    cleared = s.breakpoint_clear(ref="0x04a0")
    assert cleared["disarmed"] and ses.bplist_rows == []
    # A store from before the rule: its bare spelling of the address is read as `0x` and `add`
    # adopts the same declaration again; a name over the same address, the pair an older version
    # wrote to disk, is what the re-arm meets.
    use_table(monkeypatch, table={"IRQ": 0x4A0})
    store = arming.store()
    legacy: dict[str, object] = {"kind": "breakpoint", "by": "address", "ref": "4a0",
                                 "origin": "s1", "fingerprint": "fp-test"}
    store.add(dec.Declaration.from_dict(legacy))
    assert store.add(dec.Declaration("breakpoint", "address", "0x4a0", origin="s1",
                                     fingerprint="fp-test")) is False
    store._items.append(dec.Declaration("breakpoint", "symbol", "irq", origin="s1",
                                        fingerprint="fp-test"))
    mstate.STATE.breakpoints.clear()
    back = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(back["rearmed"]) == ["0x4a0"] and len(ses.bplist_rows) == 1
    assert [u["ref"] for u in back["unarmable"]] == ["irq"]
    assert back["unarmable"][0]["why"].endswith(
        "already declared under '0x4a0' in this pass: one breakpoint row is one declaration")
    # THE LIST AND THE CLEAR AGREE WITH THE RE-ARM. The address is armed and has a row, and
    # calling the second declaration `armed` on that alone is the trap: the clear then sends
    # a second `z0` for the shared row, which the stub refuses, and the first declaration is
    # left sitting over a row the debugger no longer has.
    listed = {b["ref"]: b for b in s.breakpoint_list()["breakpoints"]}
    assert listed["0x4a0"]["state"] == "armed" and listed["irq"]["state"] == "aliased"
    assert "'0x4a0'" in listed["irq"]["why"]
    # A clear reaches the declarations of its own kind: the address takes the ONE armed row,
    # and the name, which owned none, goes with nothing to disarm.
    cleared = s.breakpoint_clear(ref="0x4a0")
    assert cleared["declarations_cleared"] == 1 and cleared["disarmed"] == ["2 @ 0004A0"]
    cleared = s.breakpoint_clear(ref="IRQ")
    assert cleared["declarations_cleared"] == 1 and cleared["disarmed"] == []
    assert ses.bplist_rows == [] and s.breakpoint_list()["breakpoints"] == []


def test_an_address_ref_has_one_spelling_and_a_clear_takes_any_of_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A fresh stdio client declared `4a0`, and the clear of `4a0` was refused because an
    earlier session had stored the same address as `0x4a0`: two spellings of one address,
    compared as text. An address ref is stored in ONE spelling, the reply carries it, and
    a clear matches an address however it is spelt; a symbol stays the exact name."""
    ses = _watching(monkeypatch, tmp_path)
    out = s.breakpoint_at(ref="0x4A0")
    assert out["status"] == "ok" and out["ref"] == "0x4A0", out
    assert s.breakpoint_at(ref="0x4a0")["already_stored"] is True, "one address, adopted"
    assert s.breakpoint_at(ref="0x0004a0")["already_stored"] is True
    cleared = s.breakpoint_clear(ref="0x4a0")
    assert cleared["declarations_cleared"] == 1 and cleared["disarmed"] == ["1 @ 0004A0"], cleared
    assert ses.bplist_rows == []
    s.watch_add(ref="0x2031FC", mode="show", length=2)
    assert s.watch_clear(ref="0x2031fc")["declarations_cleared"] == 1
    assert s.watch_clear(ref="0x2031fc")["status"] == "INVALID"


def test_a_clear_reads_the_callers_ref_the_way_the_declaration_was_made(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Guessing the caller's ref's kind from the symbol table breaks an address declared as
    one the moment a later build names a symbol `4A0`, so a ref is read once, by its spelling:
    `0x4a0` reaches the address row and `4a0`, a name this build defines, the symbol row, and
    neither reaches the other."""
    _watching(monkeypatch, tmp_path)
    assert s.breakpoint_at(ref="0x4a0", by="address")["status"] == "ok"
    add_symbol(monkeypatch, "4A0", 0x2031FC)
    named = s.breakpoint_at(ref="4a0")
    assert (named["by"], named["addr"]) == ("symbol", "0x002031fc"), named
    out = s.breakpoint_clear(ref="0x4a0")
    assert out["status"] == "ok" and out["declarations_cleared"] == 1, out
    left = [(b["by"], b["ref"]) for b in s.breakpoint_list()["breakpoints"]]
    assert left == [("symbol", "4a0")], left
    assert s.breakpoint_clear(ref="4A0")["declarations_cleared"] == 1


def test_an_address_inside_a_pointer_ref_matches_in_any_spelling_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The auditor's input one layer down: `[0x203300]+0x4` and `[0X203300]+4` name one place
    through one pointer, and compared as text they stacked two watches on one byte. The
    base inside a pointer ref folds like an address; a field name and a symbol stay."""
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x203300] = (0x2100).to_bytes(4, "big")
    ses.memory[0x2104] = b"\x00\x2a"
    first = s.watch_add(ref="[0x203300]+0x4", mode="show", length=2)
    assert first["status"] == "ok", first
    again = s.watch_add(ref="[0X203300]+4", mode="show", length=2)
    assert again["already_stored"] is True and again["ref"] == "[0x203300]+0x4", again
    assert s.watch_clear(ref="[ 0x203300 ] + 0x4")["declarations_cleared"] == 1
    assert dec.canonical_ref("[FRAME_LO]-0x4", "pointer") == "[FRAME_LO]-0x4"
    assert dec.canonical_ref("frame_lo->x", "pointer") == "frame_lo->x"
    # A base with no `0x` is a NAME, however hex it looks (`BEEF`): the
    # symbol and the literal address are two places, as the address rule reads any ref.
    add_symbol(monkeypatch, "BEEF", 0x203300)
    assert dec.canonical_ref("[beef]", "pointer") == "[beef]"
    assert dec.canonical_ref("[0xBEEF]", "pointer") == "[0xbeef]"
    ses.memory[0xBEEF] = (0x2100).to_bytes(4, "big")
    assert s.watch_add(ref="[beef]", mode="show", length=2)["status"] == "ok"
    literal = s.watch_add(ref="[0xBEEF]", mode="show", length=2)
    assert literal["status"] == "ok" and literal["already_stored"] is False, literal


# ------------------------------------------------------------------ a regpoint


def test_a_regpoint_is_an_expression_held_by_its_text_and_nothing_else() -> None:
    """The `ref` IS the condition, as typed: no address, so no role, no watch field, no
    `condition` field of its own, and never stale whatever the build."""
    rp = dec.Declaration("regpoint", "expr", "d1==7fff", origin="s1", fingerprint="fp")
    assert dec.Declaration.from_dict(rp.to_dict()) == rp
    assert "watch_mode" not in {k for k, v in rp.to_dict().items() if v is not None}
    assert dec.resolve(rp, {}).state == "expr"
    assert dec.is_stale(rp, "another build") is False
    for bad in (dict(by="symbol"), dict(by="address", ref="0x400"), dict(width=2),
                dict(watch_mode="expr"), dict(role="control"), dict(condition="d0==1")):
        fields = {"by": "expr", "ref": "d1==7fff", **bad}
        with pytest.raises(dec.DeclarationError):
            dec.Declaration("regpoint", **fields)  # type: ignore[arg-type]
    with pytest.raises(dec.DeclarationError, match="only a watch or a registerpoint is"):
        dec.Declaration("breakpoint", "expr", "d1==7fff")


def test_a_regpoint_and_an_expr_watch_over_the_same_text_are_two_declarations() -> None:
    store = dec.DeclarationStore("test", path=None)
    assert store.add(dec.Declaration("watch", "expr", "d1==7fff", watch_mode="expr")) is True
    assert store.add(dec.Declaration("regpoint", "expr", "d1==7fff")) is True
    assert store.add(dec.Declaration("regpoint", "expr", " d1==7fff ")) is False, "one, adopted"
    assert store.discard([dec.Declaration("regpoint", "expr", "d1==7fff")]) == 1
    assert [d.kind for d in store.declarations()] == ["watch"]


def test_start_re_arms_a_stored_regpoint_and_says_so_in_its_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    try:
        _same, out = _start_over_an_earlier_store(
            monkeypatch, tmp_path, [{"kind": "regpoint", "by": "expr", "ref": "d1==7fff"}])
        assert refs(out["declarations"]["rearm"]["rearmed"]) == ["d1==7fff"], out["declarations"]
        rows = s.regpoint_list()["regpoints"]
        assert [(r["state"], r["inherited"]) for r in rows] == [("armed", True)]
    finally:
        s.close()


# ------------------------------------------------------------------ comments as declarations


def _comment(ref: str = "irq_vblank", by: str = "symbol", text: str = "a note",
             cpu: str | None = ":maincpu", **kw: Any) -> dec.Declaration:
    return dec.Declaration("comment", by, ref, cpu=cpu, text=text, **kw)


@pytest.mark.parametrize(("make", "words"), [
    (lambda: dec.Declaration("comment", "symbol", "x", cpu=":maincpu"), "carries a text"),
    (lambda: dec.Declaration("breakpoint", "symbol", "x", text="t"), "carries a text"),
    (lambda: dec.Declaration("comment", "expr", "x", text="t"), "symbol or at an address"),
    (lambda: dec.Declaration("comment", "pointer", "[x]", text="t"), "symbol or at an address"),
    (lambda: dec.Declaration("comment", "symbol", "x", text="t", role="control"), "no role"),
    (lambda: dec.Declaration("comment", "symbol", "x", text="t", condition="d0==1"), "no role"),
    (lambda: dec.Declaration("comment", "symbol", "x", text="t", width=2), "no watch fields"),
    (lambda: dec.Declaration("comment", "symbol", "x", text="a\tb"), "comment's text holds"),
    (lambda: dec.Declaration("comment", "symbol", "a b", text="t"), "ref 'a b' holds"),
])
def test_a_comment_is_a_text_at_a_symbol_or_an_address_and_nothing_else(make: Any,
                                                                       words: str) -> None:
    with pytest.raises(dec.DeclarationError, match=words):
        make()


def test_a_comment_round_trips_through_the_store_file_with_its_text() -> None:
    c = _comment(created_at="2026-10-02T00:30:00+00:00", origin="s1", fingerprint="fp")
    assert c.to_dict()["text"] == "a note"
    back = dec.Declaration.from_dict(c.to_dict())
    assert (back, back.text, back.created_at) == (c, "a note", c.created_at)
    assert c.adopted_by("s2", "later").text == "a note"
    with pytest.raises(dec.DeclarationError, match="carries a text"):
        dec.Declaration.from_dict({k: v for k, v in c.to_dict().items() if k != "text"})


def test_a_comment_is_its_place_whatever_its_text() -> None:
    assert dec.same_place(_comment(text="one"), _comment(text="two"))
    assert dec.same_place(_comment("0x400", "address"), _comment("0x0400", "address"))
    assert not dec.same_place(_comment(), _comment(cpu=":subcpu"))


def test_a_comment_is_counted_as_no_breakpoint_watch_or_registerpoint() -> None:
    store = dec.DeclarationStore("k", None)
    store.add(dec.Declaration("breakpoint", "symbol", "irq_vblank", cpu=":maincpu"))
    store.add(_comment())
    assert store.counts_by_cpu({}) == {":maincpu": {"breakpoints": 1, "watches": 0,
                                                    "regpoints": 0}}
    assert set(dec.COUNT_KEYS) == set(dec.COUNTED_KINDS) and "comment" in dec.KINDS


@pytest.mark.parametrize("watch_first", [True, False])
def test_a_comment_and_a_watch_on_one_ref_are_both_held(watch_first: bool) -> None:
    store = dec.DeclarationStore("k", None)
    watch = dec.Declaration("watch", "symbol", "irq_vblank", width=2, fmt="u16",
                            watch_mode="show", cpu=":maincpu")
    for d in ((watch, _comment()) if watch_first else (_comment(), watch)):
        assert store.add(d) is True
    assert [d.kind for d in store.declarations()] == (["watch", "comment"] if watch_first
                                                     else ["comment", "watch"])


def test_apply_writes_once_and_a_failed_write_keeps_the_change_in_memory(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "decl.json"
    store = dec.DeclarationStore("k", path)
    a, b = _comment("a"), _comment("b")
    store.add(a)
    writes: list[int] = []
    real = store._persist

    def counted() -> None:
        writes.append(1)
        real()

    monkeypatch.setattr(store, "_persist", counted)
    b2 = dataclasses.replace(a, text="replaced")
    store.apply(adds=[b], replaces=[(a, b2)])
    assert writes == [1] and [(d.ref, d.text) for d in store.declarations()] == [
        ("a", "replaced"), ("b", "a note")]
    assert [d["text"] for d in json.loads(path.read_text())["k"]] == ["replaced", "a note"]

    def broken() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_persist", broken)
    with pytest.raises(OSError):
        store.apply(removes=[b])
    assert [d.ref for d in store.declarations()] == ["a"], "held in memory though unwritten"


def test_the_rearm_leaves_comments_to_their_own_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """`start`'s re-arm walks the store once; a comment arms no breakpoint or watch, so the
    breakpoint and watch pass skips it by name and sends the console nothing for it."""
    store = dec.DeclarationStore("k", None)
    store.add(_comment())
    store.add(_comment("0x400", "address", cpu=":maincpu"))
    monkeypatch.setattr(mstate.STATE, "store", store)
    monkeypatch.setattr(mstate.STATE, "first_cpu", ":maincpu")
    monkeypatch.setitem(mstate.STATE.tables, ":maincpu",
                        g.SymbolTable({"IRQ_VBLANK": 0x400}, {}, "test"))
    sent: list[str] = []

    def monitor(command: str, timeout: float = 10.0) -> str:
        sent.append(command)
        return ""

    ses = SimpleNamespace(monitor=monitor)
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert out == {"rearmed": [], "stale": [], "unresolved": [], "unarmable": [],
                   "evaluated": []} and sent == []
