"""The address rule, its table half: an address is written `0x`, any other ref is a symbol, and
bare hex that names no symbol is refused with the `0x` spelling it most likely meant. A call's
ref is read ONCE, so it only ever reaches declarations of its own kind (an address never a
symbol's row, nor the reverse), a symbol in any case and an address in any spelling. Rows the
store already holds keep the reading they were written under.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import refused, use_table  # noqa: E402
from test_capture import _capturing  # noqa: E402
from test_comments import MAIN, _pane, _states  # noqa: E402
from test_controls import _controlled  # noqa: E402
from test_film import _session as _film_session  # noqa: E402
from test_iotaps import _io_board  # noqa: E402
from test_server import _running  # noqa: E402

import mame_comments as comments  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_inputs as inputs  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


def _rows(kind: str) -> list[tuple[str, str]]:
    assert mstate.STATE.store is not None
    return [(d.by, d.ref) for d in mstate.STATE.store.declarations() if d.kind == kind]


def _suggests(reply: dict[str, Any], spelling: str) -> None:
    assert reply["status"] == "INVALID" and reply["code"] == "unknown_ref", reply
    assert f"an address is written {spelling}" in reply["message"], reply


# ------------------------------------------------------------------ the readers


@pytest.mark.parametrize(("ref", "addr"), [("0x400", 0x400), ("0X4A0", 0x4A0), (" 0x4a0 ", 0x4A0),
                                           ("fade", 0x900), ("FADE", 0x900)])
def test_a_ref_is_an_address_with_0x_and_a_symbol_otherwise(
    monkeypatch: pytest.MonkeyPatch, ref: str, addr: int,
) -> None:
    use_table(monkeypatch, table={"FADE": 0x900})
    assert mstate.STATE.resolve(ref) == addr


def test_a_0x_ref_is_an_address_even_where_the_table_has_the_same_hex_as_a_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_table(monkeypatch, table={"ADC": 0x780000})
    assert mstate.STATE.resolve("0xadc") == 0xADC
    assert mstate.STATE.resolve("adc") == 0x780000


@pytest.mark.parametrize("ref", ["400", "4a0", "beef", " 25A4 "])
def test_bare_hex_naming_no_symbol_is_refused_with_the_0x_spelling(
    monkeypatch: pytest.MonkeyPatch, ref: str,
) -> None:
    use_table(monkeypatch, table={"FADE": 0x900})
    with pytest.raises(mstate.Invalid) as refusal:
        mstate.STATE.resolve(ref)
    assert refusal.value.code == "unknown_ref"
    assert f"an address is written 0x{ref.strip()}" in str(refusal.value), refusal.value


@pytest.mark.parametrize("ref", ["  ", "\t"])
def test_a_ref_that_is_only_whitespace_is_refused_as_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ref: str,
) -> None:
    _controlled(monkeypatch, tmp_path)
    for reply in (s.read_memory(ref=ref, length=2), s.breakpoint_at(ref=ref),
                  s.watch_add(ref=ref, mode="change", length=2)):
        refused("is empty", reply)
        assert reply["code"] == "bad_argument", reply
    assert _rows("breakpoint") == [] and _rows("watch") == [], "nothing stored"


# ------------------------------------------------------------------ declarations


def test_a_name_and_the_address_its_hex_spells_are_two_breakpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"ADC": 0x780000})
    assert s.breakpoint_at(ref="0xadc")["status"] == "ok"
    out = s.breakpoint_at(ref="adc")
    assert out["status"] == "ok", out
    assert (out["by"], out["ref"]) == ("symbol", "adc"), out
    assert _rows("breakpoint") == [("address", "0xadc"), ("symbol", "adc")]


def test_a_clear_by_name_never_reaches_the_address_its_hex_spells(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"ADC": 0x780000})
    s.breakpoint_at(ref="0xadc")
    s.breakpoint_at(ref="adc")
    assert s.declaration_clear("breakpoint", ref="adc")["status"] == "ok"
    assert _rows("breakpoint") == [("address", "0xadc")]
    assert s.declaration_clear("breakpoint", ref="0xADC")["status"] == "ok"
    assert _rows("breakpoint") == []


def test_one_symbol_in_two_cases_is_one_declaration_and_either_case_clears_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"IRQ": 0x4A0})
    assert s.breakpoint_at(ref="irq")["status"] == "ok"
    again = s.breakpoint_at(ref="IRQ")
    assert again["status"] == "ok" and again["already_stored"] is True, again
    assert _rows("breakpoint") == [("symbol", "irq")]
    assert s.declaration_clear("breakpoint", ref="IRQ")["status"] == "ok"
    assert _rows("breakpoint") == []


def test_a_declaration_by_bare_hex_naming_no_symbol_is_refused_and_nothing_is_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    _suggests(s.breakpoint_at(ref="4a0"), "0x4a0")
    _suggests(s.watch_add(ref="2031fc", mode="change", length=2), "0x2031fc")
    _suggests(s.declaration_clear("breakpoint", ref="4a0"), "0x4a0")
    assert _rows("breakpoint") == [] and _rows("watch") == []


def test_a_held_row_named_in_bare_hex_stays_reachable_by_its_stored_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row by the NAME `fade` (a file loaded it, or a build that lost the symbol): the call
    names it back and is not refused as bare hex."""
    _controlled(monkeypatch, tmp_path)
    store = mstate.STATE.store
    assert store is not None
    store.add(dec.Declaration("breakpoint", "symbol", "fade", cpu=":maincpu"))
    assert s.declaration_clear("breakpoint", ref="FADE")["status"] == "ok"
    assert _rows("breakpoint") == []


def test_a_store_row_by_address_in_bare_hex_loads_in_the_0x_spelling(tmp_path: Path) -> None:
    """A legacy row: its `by` says address, so nothing is guessed, and `start` never refuses
    the store over it."""
    path = tmp_path / "declarations.json"
    path.write_text(json.dumps({"key": [{"kind": "breakpoint", "by": "address", "ref": "4A0"},
                                        {"kind": "watch", "by": "address", "ref": "2031fc",
                                         "width": 2, "fmt": "u16", "watch_mode": "change"}]}))
    held = dec.DeclarationStore("key", path).declarations()
    assert [(d.by, d.ref) for d in held] == [("address", "0x4a0"), ("address", "0x2031fc")]


def test_a_stored_capture_trigger_is_raw_only_when_written_as_an_address() -> None:
    capture = dec.Declaration("watch", "symbol", "palbuf", width=4, fmt="u32",
                              watch_mode="capture", trigger="FADE", fingerprint="old")
    assert dec.is_stale(capture, "new") is False, "a name re-resolves, spelled like hex or not"
    raw = dec.Declaration("watch", "symbol", "palbuf", width=4, fmt="u32",
                          watch_mode="capture", trigger="0x900", fingerprint="old")
    assert dec.is_stale(raw, "new") is True


def test_an_io_capture_by_address_reads_its_block_as_an_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _io_board(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"FRAME_LO": 0x2031FC})
    out = s.watch_add(ref="frame_lo", by="address", mode="capture", length=4, trigger="0x6",
                      space="io")
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "by address needs a `0x` address" in out["message"], out


# ------------------------------------------------------------------ comments


def test_a_comment_delete_by_name_never_reaches_the_raw_comment_its_hex_spells(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _pane(monkeypatch, tmp_path)
    assert s.comment_write("add", ref="0xfade", text="raw",
                           cpu="maincpu")["comment"]["by"] == "address"
    assert s.comment_write("add", ref="fade", text="sym",
                           cpu="maincpu")["comment"]["by"] == "symbol"
    out = s.comment_write("delete", ref="fade", cpu="maincpu")
    assert out["deleted"]["ref"] == "fade", out
    assert _states() == {"0xfade": ("armed", "raw")}
    assert s.comment_write("add", ref="fade", text="sym2", cpu="maincpu")["replaced_comments"] == []


def _stale_raw_and_unshowable_symbol(monkeypatch: pytest.MonkeyPatch,
                                     tmp_path: Path) -> dict[str, Any]:
    """A raw comment of another build and a symbol comment the pane cannot show, at one place;
    the comments' re-arm that found them."""
    pane = _pane(monkeypatch, tmp_path)
    s.comment_write("add", ref="0x900", text="old raw", cpu="maincpu")
    s.comment_write("add", ref="irq_vblank", text='a "q"', cpu="maincpu")
    use_table(monkeypatch, MAIN, table={"IRQ_VBLANK": 0x900, "FADE": 0x904})
    monkeypatch.setitem(mstate.STATE.fingerprints, MAIN, "fp-main-rebuilt")
    pane.held.clear()
    mstate.STATE.comment_feed.clear()
    counts: dict[str, Any] = comments.rearm(pane, tmp_path)  # type: ignore[arg-type]
    assert (len(counts["stale"]), len(counts["unarmable"])) == (1, 1), counts
    return counts


def test_a_delete_by_name_in_another_case_reaches_the_symbol_row_and_not_the_stale_raw_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _stale_raw_and_unshowable_symbol(monkeypatch, tmp_path)
    out = s.comment_write("delete", ref="IRQ_VBLANK", cpu="maincpu")
    assert out["deleted"]["ref"] == "irq_vblank", out
    assert _states() == {"0x900": ("stale", "old raw")}


def test_an_add_by_name_in_another_case_replaces_the_symbol_row_and_leaves_the_stale_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _stale_raw_and_unshowable_symbol(monkeypatch, tmp_path)
    out = s.comment_write("add", ref="IRQ_VBLANK", text="new", cpu="maincpu")
    assert [r["ref"] for r in out["replaced_comments"]] == ["irq_vblank"], out
    assert _states()["0x900"] == ("stale", "old raw")


def test_a_name_never_deletes_a_stale_raw_comment_it_only_shares_a_place_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _stale_raw_and_unshowable_symbol(monkeypatch, tmp_path)
    s.comment_write("delete", ref="irq_vblank", cpu="maincpu")
    out = s.comment_write("delete", ref="IRQ_VBLANK", cpu="maincpu")
    assert out["status"] == "INVALID" and out["code"] == "unknown_ref", out
    assert _states() == {"0x900": ("stale", "old raw")}
    adopted = s.comment_write("add", ref="0x900", text="adopted", cpu="maincpu")
    assert [r["ref"] for r in adopted["replaced_comments"]] == ["0x900"], adopted


def test_a_comment_by_bare_hex_naming_no_symbol_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _pane(monkeypatch, tmp_path)
    _suggests(s.comment_write("add", ref="cafe", text="x", cpu="maincpu"), "0xcafe")
    _suggests(s.comment_write("delete", ref="cafe", cpu="maincpu"), "0xcafe")


# ------------------------------------------------------------------ the refusal passes whole


def test_run_to_lets_the_bare_hex_refusal_of_its_control_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    _suggests(s.run_to(ref="0x4a0", control="25a4", seconds=2.0), "0x25a4")
    _suggests(s.run_to(ref="4a0", seconds=2.0), "0x4a0")
    assert _rows("breakpoint") == [], "no control declared"


def test_gfx_film_lets_the_bare_hex_refusal_of_its_trigger_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _film_session(monkeypatch, tmp_path)
    _suggests(s.gfx_film(trigger="70001e"), "0x70001e")


def test_a_list_with_bare_hex_at_its_third_step_is_refused_before_anything_ran(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x4a0"},
                           {"op": "breakpoint_at", "ref": "0x25a4", "role": "control"},
                           {"op": "breakpoint_at", "ref": "2600"}])
    assert out["status"] == "INVALID" and out["code"] == "unknown_ref", out
    assert "before anything ran" in out["message"] and "0x2600" in out["message"], out
    assert len(out["errors"]) == 1 and out["failed_at"] == 2, out
    assert ses.armed == [] and _rows("breakpoint") == [], "nothing ran"


# ------------------------------------------------------------------ the review's reds


def test_a_row_declared_by_address_in_bare_hex_is_never_read_back_as_a_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Only a row stored BY NAME keeps its bare spelling reachable: a raw row's bare ref is
    refused with the `0x` spelling that reaches it, and never read as a second, symbol row; a
    call declaring by address in bare hex is refused before any row is written."""
    _controlled(monkeypatch, tmp_path)
    refused("an address is written 0x4a0", s.breakpoint_at(ref="4a0", by="address"))
    assert s.breakpoint_at(ref="0x4a0", by="address")["status"] == "ok"
    _suggests(s.breakpoint_at(ref="4a0"), "0x4a0")
    _suggests(s.declaration_clear("breakpoint", ref="4a0"), "0x4a0")
    assert _rows("breakpoint") == [("address", "0x4a0")]
    assert s.declaration_clear("breakpoint", ref="0x4a0")["declarations_cleared"] == 1


def test_a_pointer_base_in_bare_hex_naming_no_symbol_is_refused_in_a_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    _suggests(s.watch_add(ref="[203300]+4", mode="show", length=2), "0x203300")
    assert _rows("watch") == []
    assert s.watch_add(ref="[0x203300]+4", mode="show", length=2)["status"] == "ok"


def test_a_store_holding_one_declaration_in_two_spellings_loads_one(tmp_path: Path) -> None:
    path = tmp_path / "declarations.json"
    rows = [{"kind": "breakpoint", "by": "address", "ref": ref} for ref in ("4a0", "0x4A0")]
    path.write_text(json.dumps({"key": rows + [{"kind": "breakpoint", "by": "symbol",
                                                "ref": "irq"}]}))
    held = dec.DeclarationStore("key", path).declarations()
    assert [(d.by, d.ref) for d in held] == [("address", "0x4a0"), ("symbol", "irq")]


def test_a_regpoint_clear_reads_its_ref_as_an_expression_and_never_as_an_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    out = s.declaration_clear("regpoint", ref="d0")
    assert out["code"] == "unknown_ref" and "an address is written" not in out["message"], out


def test_a_clear_naming_no_cpu_says_it_read_every_cpus_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    out = s.declaration_clear("breakpoint", ref="4a0")
    _suggests(out, "0x4a0")
    assert "the machine's table" in out["message"], out


def test_the_preflight_judges_a_trigger_whatever_by_says_and_a_capture_block_in_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    for step in ({"op": "watch_add", "ref": "0x2031fc", "by": "address", "mode": "capture",
                  "length": 4, "trigger": "2031fe"},
                 {"op": "watch_add", "ref": "2031fc", "mode": "capture", "length": 4,
                  "trigger": "0x6", "space": "io"}):
        out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x4a0"}, step], settle_seconds=5.0)
        assert out["code"] == "unknown_ref" and "before anything ran" in out["message"], out
    assert ses.armed == [] and _rows("breakpoint") == []


def test_the_preflight_leaves_a_step_after_one_that_can_stop_the_machine_to_its_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stop moves the visible cpu, and the table the step would be read against with it."""
    _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x4a0"}, {"op": "stop"},
                           {"op": "breakpoint_at", "ref": "2600"}], settle_seconds=5.0)
    assert out["code"] == "step_failed" and out["failed_at"] == 2, out
    assert _rows("breakpoint") == [("address", "0x4a0")], "the steps before it ran"


def test_drive_refuses_bare_hex_before_anything_ran_and_names_one_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = s.drive(act=[{"op": "breakpoint_at", "ref": "0x4a0"},
                       {"op": "breakpoint_at", "ref": "2600"}], expect="x", seconds=1.0)
    assert out["code"] == "unknown_ref" and "0x2600" in out["message"], out
    assert len(out["act"]["errors"]) == 1 and out["act"]["failed_at"] == 1, out["act"]
    assert ses.armed == [] and _rows("breakpoint") == []


def test_a_declaring_call_names_back_a_row_stored_by_a_hex_shaped_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The name `fade` a build no longer defines, held by name: declaring it again adopts the
    row, where a bare `fade` held by nothing is refused."""
    _controlled(monkeypatch, tmp_path)
    _suggests(s.breakpoint_at(ref="fade"), "0xfade")
    assert s.breakpoint_at(ref="fade", by="symbol")["state"] == "unresolved"
    again = s.breakpoint_at(ref="FADE")
    assert again["status"] == "ok" and again["already_stored"] is True, again
    assert _rows("breakpoint") == [("symbol", "fade")]


def test_a_clear_naming_no_cpu_reads_a_name_of_any_cpus_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`beef` is a name of the sub cpu alone: a clear naming no cpu reads it as that name, and
    the main cpu's raw row at 0xbeef stays."""
    import gdb_session as g
    _controlled(monkeypatch, tmp_path)
    monkeypatch.setitem(mstate.STATE.tables, ":subcpu",
                        g.SymbolTable({"BEEF": 0x640}, {}, "yaml"))
    store = mstate.STATE.store
    assert store is not None
    store.add(dec.Declaration("breakpoint", "address", "0xbeef", cpu=":maincpu"))
    store.add(dec.Declaration("breakpoint", "symbol", "beef", cpu=":subcpu"))
    out = s.declaration_clear("breakpoint", ref="beef")
    assert out["declarations_cleared"] == 1, out
    assert _rows("breakpoint") == [("address", "0xbeef")]


def test_a_capture_trigger_is_read_by_the_address_rule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _capturing(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"FADE": 0x2031FE})
    _suggests(s.watch_add(ref="0x2031fc", mode="capture", length=2, trigger="2031fe"),
              "0x2031fe")
    named = s.watch_add(ref="0x2031fc", mode="capture", length=2, trigger="fade")
    assert named["status"] == "ok" and named["trigger"] == "fade", named
    assert _rows("watch") == [("address", "0x2031fc")]


def test_an_io_capture_block_naming_nothing_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _io_board(monkeypatch, tmp_path)
    out = s.watch_add(ref="no_such_block", mode="capture", length=4, trigger="0x6", space="io")
    assert out["code"] == "unknown_ref" and out["message"] == inputs.not_a_ref(
        "the block", "no_such_block", ":maincpu"), out


def test_the_preflight_leaves_a_port_to_the_io_space_rule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A trigger in the io space is a port, read by the io space's own rule when the step runs."""
    from mame_sequence import _ref_args
    assert _ref_args({"op": "gfx_film", "trigger": "0x1e", "space": "io", "pc": "0x400"}) == [
        ("pc", "0x400", False)]
    assert _ref_args({"op": "watch_add", "ref": "0x1c", "mode": "count", "space": "io"}) == []
    assert _ref_args({"op": "watch_add", "ref": "[2031fc]+4"}) == [("ref", "2031fc", True)]


# ------------------------------------------------------------------ the rule's offline half


@pytest.mark.parametrize("ref", ["0x", "0xzz", "0X", " 0xg1 "])
def test_text_that_starts_like_an_address_and_is_not_one_is_refused_before_the_machine(
    ref: str,
) -> None:
    for reply in (s.read_memory(ref=ref, length=2), s.breakpoint_at(ref=ref),
                  s.comment_write("add", ref=ref, text="x")):
        refused("starts like an address and is not one", reply)
        assert reply["code"] == "bad_argument", reply


def test_by_address_takes_a_0x_ref_and_by_symbol_never_does() -> None:
    """`by` says the kind, and the spelling has to agree, judged with no machine: a bare ref by
    address is refused with its `0x` spelling, a `0x` ref by symbol as a contradiction."""
    out = refused("an address is written 0x4a0", s.breakpoint_at(ref="4a0", by="address"))
    assert out["code"] == "bad_argument", out
    refused("by symbol names a symbol", s.breakpoint_at(ref="0x4a0", by="symbol"))
    refused("an address is written 0x2031fc",
            s.watch_add(ref="2031fc", by="address", mode="change", length=2))


@pytest.mark.parametrize("port", ["6", "1c", "fe"])
def test_a_port_is_written_0x(port: str) -> None:
    refused(f"an address is written 0x{port}",
            s.watch_add(ref=port, mode="count", length=1, space="io"))
    out = refused(f"an address is written 0x{port}", s.gfx_film(trigger=port, space="io"))
    assert out["message"].startswith(f"trigger='{port}'"), "the argument it came in is named"


def test_symbols_find_refuses_a_bare_linear_before_the_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    out = refused(r"linear is '1000'; an address is written 0x1000", s.symbols_find(linear="1000"))
    assert out["code"] == "bad_argument", out


@pytest.mark.parametrize(("call", "name"), [
    (lambda: s.rom_check(reference_rom="/no/such.bin", reference_addr="1000"), "reference_addr"),
    (lambda: s.rom_check(reference_rom="/no/such.bin", reference_addr="0x0",
                         reference_base="20000"), "reference_base"),
])
def test_an_address_argument_is_written_0x(call: Any, name: str) -> None:
    out = refused(rf"{name} is '[0-9a-f]+'; an address is written 0x", call())
    assert out["code"] == "bad_argument", out


def test_a_bases_value_is_written_0x(tmp_path: Path) -> None:
    import mame_symbols as symbols
    with pytest.raises(mstate.Invalid, match=r"bases\['DATA'\] is '400'; an address is written "
                                             r"0x400"):
        symbols._parse_bases({"DATA": "400"})
    assert symbols._parse_bases({"DATA": "0x400", "TILES": "rom"}) == {"DATA": 0x400,
                                                                      "TILES": None}


# ------------------------------------------------------------------ the P6 review's reds


def test_a_stored_row_by_symbol_written_as_an_address_loads_as_the_address(tmp_path: Path) -> None:
    """A row an older version stored `by="symbol"` with a `0x` ref is read as what its spelling
    says, an address, and never refuses the whole store at `start`."""
    path = tmp_path / "declarations.json"
    row = {"kind": "breakpoint", "by": "symbol", "ref": "0x4a0", "cpu": MAIN}
    path.write_text(json.dumps({"k": [row]}))
    held = dec.DeclarationStore("k", path).declarations()
    assert [(d.by, d.ref) for d in held] == [("address", "0x4a0")]


def test_a_pointer_named_by_pointer_judges_its_base_as_auto_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`by="pointer"` names the grammar, not the base's kind: a bare base naming no symbol is
    refused with its `0x` spelling, as it is under `auto`."""
    _running(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"FRAME_LO": 0x2031FC})
    for by in ("pointer", "auto"):
        _suggests(s.watch_add(ref="[2031fc]+4", by=by, mode="show", length=2), "0x2031fc")
    assert _rows("watch") == []


def test_a_0x_segment_is_refused_for_its_segment() -> None:
    refused("carries a segment", s.read_memory(ref="0x1000:0x10", length=2))


# ------------------------------------------------- names held another way, and the preflight


@pytest.mark.parametrize("name", ["d0", "a7", "bc"])
def test_an_expression_watch_named_like_hex_is_cleared_by_its_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str,
) -> None:
    """A register is an expression, not a ref of the address kind: `d0`, `a7`, `bc` are hex
    and name no symbol, and the watch they declare is still cleared by the text it was
    declared with."""
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {name: 1}
    assert s.watch_add(ref=name, mode="expr")["status"] == "ok"
    out = s.declaration_clear("watch", ref=name)
    assert out.get("declarations_cleared") == 1, out
    assert _rows("watch") == []


def test_a_bare_hex_name_held_by_no_expression_is_still_refused_by_a_clear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {"d0": 1}
    assert s.watch_add(ref="d0", mode="expr")["status"] == "ok"
    _suggests(s.declaration_clear("watch", ref="d1"), "0xd1")
    assert _rows("watch") == [("expr", "d0")]


@pytest.mark.parametrize("by", ["pointer", "auto"])
def test_perform_judges_a_pointer_base_before_anything_ran_whatever_by_says(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, by: str,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x4a0"},
                           {"op": "watch_add", "ref": "[2600]+0x4", "by": by, "mode": "show",
                            "length": 2}])
    assert out.get("code") == "unknown_ref" and "before anything ran" in out["message"], out
    assert "0x2600" in out["message"], out
    assert ses.armed == [] and _rows("breakpoint") == [], "nothing ran"


def test_a_pointer_through_a_symbol_in_two_cases_is_one_watch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"IRQ_PTR": 0x2600})
    assert s.watch_add(ref="[irq_ptr]+0x8", mode="show", length=2)["status"] == "ok"
    again = s.watch_add(ref="[IRQ_PTR]+0x8", mode="show", length=2)
    assert again.get("already_stored") is True, again
    assert _rows("watch") == [("pointer", "[irq_ptr]+0x8")]
    assert s.declaration_clear("watch", ref="[Irq_Ptr]+0x8").get("declarations_cleared") == 1
    assert _rows("watch") == []


def test_a_capture_trigger_named_in_two_cases_is_one_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _capturing(monkeypatch, tmp_path)
    first = s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="frame_lo")
    assert first["status"] == "ok", first
    again = s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="FRAME_LO")
    assert again["status"] == "ok" and again.get("already_stored") is True, again
    assert _rows("watch") == [("address", "0x2031fc")]


def test_a_stored_place_with_no_0x_is_a_name_however_it_is_spelled() -> None:
    """A capture's trigger and a pointer's base read from the store: `0x` an address, anything
    else a name of the table in any case, and a name a rebuild dropped points nowhere, never at
    the address its letters would spell."""
    for place in ("fade", "FADE", " fade "):
        assert inputs.stored_place(place, {"FADE": 0x900}) == 0x900
    assert inputs.stored_place("fade", {}) is None
    assert inputs.stored_place("2031fc", {}) is None
    assert inputs.stored_place("0xfade", {"FADE": 0x900}) == 0xFADE


def test_a_stored_pointer_through_a_name_the_build_lost_points_nowhere() -> None:
    decl = dec.Declaration("watch", "pointer", "[fade]+0x4", width=2, fmt="u16",
                           watch_mode="show", cpu=MAIN)
    assert dec.resolve(decl, {}, {}).state == "unresolved"
    assert dec.resolve(decl, {"FADE": 0x2600}, {}).base_addr == 0x2600
    assert dec.canonical_ref("[fade]+0x4", "pointer") == "[fade]+0x4"
    assert dec.canonical_ref(" [0xFADE]+4 ", "pointer") == "[0xfade]+0x4"


@pytest.mark.parametrize(("lower", "upper"), [("irq_ptr->x", "IRQ_PTR->x"),
                                              ("adc->x", "ADC->x"),
                                              ("[fade]+0x4", "[FADE]+0x4")])
def test_a_pointer_through_a_lost_name_compares_in_any_case_and_never_as_an_address(
    lower: str, upper: str,
) -> None:
    assert dec.match_key(lower, "pointer") == dec.match_key(upper, "pointer")
    named = dec.Declaration("watch", "pointer", lower, width=2, fmt="u16", watch_mode="show",
                            cpu=MAIN)
    address = dec.Declaration("watch", "pointer", "[0xfade]+0x4", width=2, fmt="u16",
                              watch_mode="show", cpu=MAIN)
    assert not dec.same_place(named, address)
    assert dec.match_key("[fade]+0x4", "pointer") != dec.match_key("[0xfade]+0x4", "pointer")


@pytest.mark.parametrize("name", ["fade", "blit_go"])
def test_a_capture_held_on_a_name_the_build_lost_is_declared_again_as_the_one_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str,
) -> None:
    """Declared again after a rebuild dropped its trigger's name, a capture is the declaration
    the store holds: kept, capturing nothing until a build defines the name, never the address
    its letters spell. Only the capture held on that block is reached by the name."""
    _capturing(monkeypatch, tmp_path)
    use_table(monkeypatch, table={name.upper(): 0x2031FE})
    assert s.watch_add(ref="0x2031fc", mode="capture", length=2, trigger=name)["status"] == "ok"
    use_table(monkeypatch, table={})
    again = s.watch_add(ref="0x2031fc", mode="capture", length=2, trigger=name.upper())
    assert again["status"] == "ok" and again.get("already_stored") is True, again
    assert again["state"] == "unresolved" and again["armed"] is False, again
    assert f"the trigger {name.upper()!r} is not a symbol of this build" in again["note"], again
    assert _rows("watch") == [("address", "0x2031fc")]
    other = s.watch_add(ref="0x2031f0", mode="capture", length=2, trigger=name)
    if name == "fade":
        _suggests(other, "0xfade")
    else:
        assert other.get("code") == "unknown_ref", other
        assert other["message"] == inputs.not_a_ref("the trigger", name, ":maincpu"), other
    _suggests(s.watch_add(ref="0x2031fc", mode="capture", length=2, trigger="beef"), "0xbeef")
    assert _rows("watch") == [("address", "0x2031fc")]


def test_a_capture_trigger_held_on_another_cpu_is_no_name_on_this_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _capturing(monkeypatch, tmp_path)
    assert mstate.STATE.store is not None
    mstate.STATE.store.add(dec.Declaration("watch", "address", "0x2031fc", width=2, fmt="u16",
                                           watch_mode="capture", trigger="fade", cpu=":subcpu"))
    use_table(monkeypatch, table={})
    _suggests(s.watch_add(ref="0x2031fc", mode="capture", length=2, trigger="fade",
                          cpu="maincpu"), "0xfade")


def test_perform_declares_again_a_capture_held_on_a_name_the_build_lost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """What the preflight lets through as a held trigger, the step answers as held: the list
    runs whole, never half."""
    ses = _capturing(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"FADE": 0x2031FE})
    assert s.watch_add(ref="0x2031fc", mode="capture", length=2, trigger="fade")["status"] == "ok"
    use_table(monkeypatch, table={})
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x4a0"},
                           {"op": "watch_add", "ref": "0x2031fc", "mode": "capture",
                            "length": 2, "trigger": "fade"}])
    assert out["status"] == "ok" and out["steps_completed"] == 2, out
    assert _rows("watch") == [("address", "0x2031fc")]
    other = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x4b0"},
                             {"op": "watch_add", "ref": "0x2031f0", "mode": "capture",
                              "length": 2, "trigger": "fade"}])
    assert other.get("code") == "unknown_ref" and other["steps_completed"] == 0, other
    assert "before anything ran" in other["message"], other
    assert _rows("breakpoint") == [("address", "0x4a0")] and len(ses.armed) == 1, ses.armed


@pytest.mark.parametrize("by", ["pointer", "auto"])
def test_a_pointer_base_that_starts_like_an_address_is_refused_as_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, by: str,
) -> None:
    _controlled(monkeypatch, tmp_path)
    out = s.watch_add(ref="[0xzz]+0x4", by=by, mode="show", length=2)
    assert out.get("code") == "bad_argument", out
    assert out["message"].startswith("base='0xzz' starts like an address"), out["message"]
    assert _rows("watch") == []


def test_perform_refuses_a_pointer_base_that_starts_like_an_address_before_anything_ran(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x4a0"},
                           {"op": "watch_add", "ref": "[0xzz]+0x4", "mode": "show", "length": 2}])
    assert out.get("code") == "bad_argument" and "before anything ran" in out["message"], out
    assert ses.armed == [] and _rows("breakpoint") == []


def test_perform_reads_a_pointer_base_as_the_tool_does_never_by_a_held_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A watch held by the name `fade` lets a call name that watch back, not use `fade` as the
    base of a pointer: the tool refuses the base, so the list is refused before it starts."""
    ses = _running(monkeypatch, tmp_path)
    store = mstate.STATE.store
    assert store is not None
    store.add(dec.Declaration("watch", "symbol", "fade", width=2, fmt="u16", watch_mode="show",
                              cpu=MAIN))
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x4a0"},
                           {"op": "watch_add", "ref": "[fade]+0x4", "mode": "show",
                            "length": 2}])
    assert out.get("code") == "unknown_ref" and "before anything ran" in out["message"], out
    assert ses.armed == [] and _rows("breakpoint") == []


def test_perform_reads_an_earlier_steps_name_only_on_the_cpu_it_was_declared_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import gdb_session as g
    ses = _running(monkeypatch, tmp_path)
    ses.threads = {1: MAIN, 2: ":subcpu"}
    monkeypatch.setitem(mstate.STATE.tables, ":subcpu", g.SymbolTable({}, {}, "yaml"))
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "fade", "by": "symbol",
                            "cpu": "subcpu"},
                           {"op": "breakpoint_at", "ref": "fade"}])
    assert out.get("code") == "unknown_ref" and "before anything ran" in out["message"], out
    assert _rows("breakpoint") == []


def test_a_clear_naming_a_cpu_says_where_the_declaration_it_names_is_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An expression watch is on no cpu, so a clear naming one does not reach it; the refusal
    says it is held, where, and the clear that does reach it, never "none at all"."""
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {"d0": 1}
    assert s.watch_add(ref="d0", mode="expr")["status"] == "ok"
    out = s.declaration_clear("watch", ref="d0", cpu="maincpu")
    assert out.get("code") == "unknown_ref", out
    assert "an address is written" not in out["message"], out
    assert out["message"].startswith(
        "'d0' matches no watch declaration on :maincpu, so nothing was cleared. The watch "
        "declarations held on :maincpu: none at all."), out
    assert "'d0' names 1 watch declaration held on no cpu" in out["message"], out
    assert _rows("watch") == [("expr", "d0")]
    assert s.declaration_clear("watch", ref="d0").get("declarations_cleared") == 1
    assert _rows("watch") == []


def test_a_clear_naming_a_cpu_says_another_cpu_holds_a_hex_shaped_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    assert s.breakpoint_at(ref="beef", by="symbol", cpu="subcpu")["status"] == "ok"
    out = s.declaration_clear("breakpoint", ref="beef", cpu="maincpu")
    assert out.get("code") == "unknown_ref", out
    assert "an address is written" not in out["message"], out
    assert ("'beef' names 1 breakpoint declaration held on :subcpu: the same clear with no "
            "`cpu` reaches it.") in out["message"], out
    assert _rows("breakpoint") == [("symbol", "beef")]


def test_an_expression_watch_names_no_declaration_of_another_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.exprs = {"d0": 1}
    assert s.watch_add(ref="d0", mode="expr")["status"] == "ok"
    _suggests(s.declaration_clear("breakpoint", ref="d0"), "0xd0")


def test_perform_reads_a_name_a_step_on_an_unknown_cpu_declares_by_name_on_any_later_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """After a `focus` the visible cpu is unknown before the list runs, so a name a step there
    declares `by="symbol"` stands for that name on whichever cpu a later step names."""
    ses = _running(monkeypatch, tmp_path)
    ses.threads = {1: MAIN, 2: ":subcpu"}
    out = s.perform(steps=[{"op": "focus", "cpu": "maincpu"},
                           {"op": "breakpoint_at", "ref": "fade", "by": "symbol"},
                           {"op": "breakpoint_at", "ref": "fade", "cpu": "maincpu"}])
    assert "before anything ran" not in str(out.get("message")), out
    assert out["status"] == "ok" and out["steps_completed"] == 3, out
    assert _rows("breakpoint") == [("symbol", "fade")]


def test_perform_reads_a_name_an_earlier_step_declares_by_name_as_that_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "fade", "by": "symbol"},
                           {"op": "breakpoint_at", "ref": "FADE"}])
    assert out["status"] == "ok", out
    assert _rows("breakpoint") == [("symbol", "fade")]
    other = s.perform(steps=[{"op": "watch_add", "ref": "beef", "by": "symbol", "mode": "show",
                              "length": 2},
                             {"op": "breakpoint_at", "ref": "beef"}])
    assert other.get("code") == "unknown_ref" and "before anything ran" in other["message"], (
        "a name declared as a watch does not exempt a breakpoint")


def test_a_refusal_of_text_that_starts_like_an_address_names_its_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _capturing(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x2031fc", mode="capture", length=2, trigger="0x")
    assert out.get("code") == "bad_argument", out
    assert out["message"].startswith("trigger='0x' starts like an address"), out["message"]
    film = s.gfx_film(trigger="0x70001e", length=2, pc="0xq")
    assert film.get("code") == "bad_argument", film
    assert film["message"].startswith("pc='0xq' starts like an address"), film["message"]


def test_a_stored_row_by_symbol_in_hex_letters_stays_a_symbol(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text(json.dumps({"key": [{"kind": "breakpoint", "by": "symbol", "ref": "adc"}]}))
    held = dec.DeclarationStore("key", path).declarations()
    assert [(d.by, d.ref) for d in held] == [("symbol", "adc")]


def test_an_io_capture_block_by_a_hex_shaped_name_is_cleared_by_that_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _io_board(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"ADC": 0x2031FC})
    out = s.watch_add(ref="adc", mode="capture", length=4, trigger="0x6", space="io")
    assert out["status"] == "ok" and out["ref"] == "ADC" and out["space"] == "io", out
    cleared = s.declaration_clear("watch", ref="adc", space="io")
    assert [t["tally_id"] for t in cleared.get("tallies_removed", [])] == [out["tally_id"]], cleared


def test_a_clear_by_whitespace_alone_is_refused_and_clears_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    for ref in ("0x4a0", "0x4b0"):
        assert s.breakpoint_at(ref=ref)["status"] == "ok"
    out = s.declaration_clear("breakpoint", ref="   ")
    assert out["code"] == "bad_argument" and "all=True" in out["message"], out
    assert len(_rows("breakpoint")) == 2


def test_perform_leaves_a_step_after_a_focus_to_the_table_of_the_cpu_it_focused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`fade` is a name of the sub cpu alone: after a `focus` on it, the step is read against
    the sub's table when it runs, never refused against the main's before the list starts."""
    import gdb_session as g
    ses = _running(monkeypatch, tmp_path)
    ses.threads = {1: MAIN, 2: ":subcpu"}
    monkeypatch.setitem(mstate.STATE.tables, ":subcpu", g.SymbolTable({"FADE": 0x900}, {}, "yaml"))
    out = s.perform(steps=[{"op": "focus", "cpu": "subcpu"},
                           {"op": "breakpoint_at", "ref": "fade"}])
    assert "before anything ran" not in str(out.get("message")), out
    assert out["steps_completed"] >= 1, out


def test_a_capture_on_a_symbol_block_held_on_a_name_the_build_lost_is_declared_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The held trigger names are looked up by the block as the tool reads it, so a block named
    by its symbol finds them too: declared again by the call and by a list, the capture is the
    one held, and the list runs whole."""
    _capturing(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"MAIN_RAM": 0x2031FC, "FADE": 0x2031FE})
    first = s.watch_add(ref="main_ram", mode="capture", length=2, trigger="fade")
    assert first["status"] == "ok", first
    use_table(monkeypatch, table={"MAIN_RAM": 0x2031FC})
    again = s.watch_add(ref="main_ram", mode="capture", length=2, trigger="fade")
    assert again["status"] == "ok" and again.get("already_stored") is True, again
    out = s.perform(steps=[{"op": "breakpoint_at", "ref": "0x4a0"},
                           {"op": "watch_add", "ref": "main_ram", "mode": "capture",
                            "length": 2, "trigger": "fade"}])
    assert out["status"] == "ok" and out["steps_completed"] == 2, out
    assert _rows("watch") == [("symbol", "main_ram")]


def _state_in_three_views(ses: Any, ref: str) -> tuple[Any, Any, Any]:
    """`ref`'s state as `declaration_list(kind="watch")` lists it, as a stop's survey carries it,
    and the word
    `start`'s re-arm files it under."""
    import mame_rearm as rearming
    import mame_watches as watches
    listed = next(w for w in s.declaration_list("watch")["watches"] if w["ref"] == ref)
    surveyed = next(w for w in watches.evaluate_watches(ses) if w["ref"] == ref)
    account = rearming.rearm_breakpoints_and_watches(ses)
    filed = [word for word, rows in account.items() if isinstance(rows, list)
             and any(r.get("ref") == ref for r in rows)]
    return listed["state"], surveyed["state"], filed


def test_a_pointer_whose_base_the_build_lacks_is_unresolved_in_every_view(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A pointer through a name this build lacks points nowhere: `unresolved` wherever the row is
    shown, never `null_pointer` (no pointer was read) and never `evaluated` (nothing was)."""
    ses = _capturing(monkeypatch, tmp_path)
    assert mstate.STATE.store is not None
    mstate.STATE.store.add(dec.Declaration("watch", "pointer", "[2600]+0x4", width=2, fmt="u16",
                                           watch_mode="show", cpu=":maincpu",
                                           fingerprint="fp-test"))
    assert _state_in_three_views(ses, "[2600]+0x4") == ("unresolved", "unresolved",
                                                        ["unresolved"])


def test_a_capture_whose_trigger_the_build_lacks_is_unresolved_in_every_view(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A capture by a raw address declared over another build, held on a trigger name this build
    lacks: what it lacks first is the trigger, so `unresolved` in every view, as the list says."""
    ses = _capturing(monkeypatch, tmp_path)
    assert mstate.STATE.store is not None
    mstate.STATE.store.add(dec.Declaration("watch", "address", "0x2031fc", width=2, fmt="u16",
                                           watch_mode="capture", trigger="lost_name",
                                           cpu=":maincpu", fingerprint="another build"))
    listed, surveyed, filed = _state_in_three_views(ses, "0x2031fc")
    assert (listed, surveyed, filed) == ("unresolved", "unresolved", ["unresolved"]), (
        listed, surveyed, filed)


def test_the_three_views_take_a_rows_resolution_word_from_one_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The list, the stop survey and `start`'s re-arm ask ONE function for the word a row's
    declaration and resolution give (`watches.resolved_state`), so a word changed there is
    changed in every view: a show watch that resolves, made `unresolved` by that function alone,
    is `unresolved` in all three, and each of them asked it."""
    import mame_watches as watches
    ses = _capturing(monkeypatch, tmp_path)
    assert mstate.STATE.store is not None
    mstate.STATE.store.add(dec.Declaration("watch", "address", "0x2031fc", width=2, fmt="u16",
                                           watch_mode="show", cpu=":maincpu",
                                           fingerprint="fp-test"))
    mstate.STATE.store.add(dec.Declaration("watch", "address", "0x203200", width=2, fmt="u16",
                                           watch_mode="count", cpu=":maincpu",
                                           fingerprint="fp-test"))
    real = watches.resolved_state
    asked: list[str] = []

    def owner(decl: dec.Declaration, res: dec.Resolved, null: bool = False) -> str | None:
        if decl.ref in ("0x2031fc", "0x203200"):
            asked.append(decl.ref)
            return "unresolved"
        return real(decl, res, null)

    monkeypatch.setattr(watches, "resolved_state", owner)
    for ref in ("0x2031fc", "0x203200"):
        assert _state_in_three_views(ses, ref) == ("unresolved", "unresolved",
                                                   ["unresolved"]), ref
    assert asked.count("0x2031fc") == 3 * 2 and asked.count("0x203200") == 3 * 2, asked


def test_a_clear_that_reaches_nothing_quotes_its_ref_one_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _controlled(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"BEEF": 0x2600})
    out = s.declaration_clear("watch", ref=" beef ")
    assert refused("matches no watch", out)["message"].startswith("'beef' matches no"), out
    assert "' beef '" not in out["message"], out["message"]
