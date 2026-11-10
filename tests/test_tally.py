"""A watch that COUNTS (`tally`): write tap, install, periodic dump, survey.

The dump is CAPTURED (`tests/fixtures/tally-2031fc-4.txt`, m68k-dual's vblank handler). The
dumps with two writers and an overflow are hand-written in the captured shape, because the
capture has one writer and no overflow, and a field that is zero in every fixture is one two
regex groups could swap unnoticed."""

from __future__ import annotations

import io
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scry_core import file_names  # noqa: E402
from scry_core import value_format as vf  # noqa: E402
from session_doubles import blank_session, refs, refused, use_table  # noqa: E402
from test_callbacks import assert_every_callback_guarded  # noqa: E402
from test_watches import _watching, _WatchSession  # noqa: E402

from scry_mame import (
    advance,  # noqa: E402
    arming,  # noqa: E402
    cpus,  # noqa: E402
    running,  # noqa: E402
    tally,  # noqa: E402
    transport,  # noqa: E402
    watches,  # noqa: E402
)
from scry_mame import callbacks as mcallbacks
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import envelope as menvelope  # noqa: E402
from scry_mame import rearm as rearming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import space as mspace  # noqa: E402
from scry_mame import state as mstate  # noqa: E402
from scry_mame import tap as mtap  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
DUMP = (FIXTURES / "tally-2031fc-4.txt").read_text()
PROMPT = b"\x1b[1;36m[MAME]\x1b[0m> "
INSTALLED = ("MCP_TALLY installed tally_id=2031fc_4 first=2031fc last=2031ff data_width=16 "
             "endianness=big cpu=:maincpu")
TWO_WRITERS = ("MCP_TALLY 2031fe_2 seq=9 frame=40 total=500 values=2 pcs=2 overflow_values=7 "
               "overflow_pcs=3 data_width=16 endianness=big cpu=:maincpu\n"
               "v 2031fe 1 ffff 300\nv 2031fe 2 ffff 190\np 40e 490\np 1234 10\nend\n")


def _tallying(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _WatchSession:
    """The watch double plus the Lua channel's sending end; nothing answers by itself."""
    # Blank first: a reset run afterwards would un-set what the fixture arranged.
    blank_session(monkeypatch)
    ses = _watching(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "proc",
                        SimpleNamespace(stdin=io.BytesIO(), poll=lambda: None, pid=0))
    use_table(monkeypatch, table={"FRAME_LO": 0x2031FC, "COPY_IN_ROM": 0x400, "IRQ_VBLANK": 0x400})
    (tmp_path / "stdout.log").write_bytes(PROMPT)
    return ses


def _sent() -> bytes:
    pipe = mstate.STATE.proc.stdin  # type: ignore[union-attr]
    assert isinstance(pipe, io.BytesIO)
    return pipe.getvalue()


def _console_prints(tmp_path: Path, text: bytes) -> None:
    with open(tmp_path / "stdout.log", "ab") as fh:
        fh.write(text)


def _answer(tmp_path: Path, seq: int, ok: bool = True, error: str = "nil",
            output: str = INSTALLED) -> None:
    """What the console prints once it ran the install, in the captured shape."""
    line = _sent().splitlines()[seq - 1]
    _console_prints(tmp_path, line + b"\n" + output.encode() + b"\n"
                    + f"MAME_MCP_LUA_END#{seq}\t{str(ok).lower()}\t{error}\n".encode() + PROMPT)


def _survey(ses: _WatchSession, frame: int) -> dict[str, object]:
    return watches.evaluate_watches(ses, frame=frame)[0]  # type: ignore[arg-type]





@pytest.mark.parametrize(("one", "other"), [
    ("10_2_audio.cpu", "10_2_audio_cpu"), ("6_2@io", "6_2_io"), ("6_2__io", "6_2_io"),
    ("6_2@io", "6_2.io"), ("A_1", "a_1"), ("_a", "a"),
    ("10_2_" + "a" * 80, "10_2_" + "a" * 81)])
def test_two_ids_never_share_a_file_and_a_plain_one_keeps_its_own_words(
        one: str, other: str) -> None:
    files = {tally.dump_path(Path("/s"), an_id).name for an_id in (one, other, one)}
    assert len(files) == 2, files
    assert all(file_names.NAME.fullmatch(name) for name in files), files
    assert tally.dump_path(Path("/s"), "2031fc_4").name == "tally-2031fc-4.txt"
    assert tally.id_words("ramdac_0_3c8") == "ramdac-0-3c8"


def test_the_install_is_idempotent_by_id_carries_the_counts_and_registers_one_dumper() -> None:
    """A rerun of the install chunk must neither double nor zero a census, nor add a dumper."""
    script = tally.install_script("2031fc_4", 0x2031FC, 4, Path("/s/tally-2031fc-4.txt"))
    assert script.index("old.tap:remove()") < script.index("install_write_tap")
    assert 'for _, k in ipairs({"total", "reads", "values", "nvalues", "pcs", "npcs",' in script
    assert '"overflow_pcs", "errors", "first_error", "seq"}}) do t[k] = old[k] end'.replace(
        "}}", "}") in script, "a rerun carries the errors too, never zeroing them"
    assert script.index("do t[k] = old[k] end") < script.index("T.items[id] = t")
    assert "if not T.periodic then" in script and script.count("emu.register_periodic") == 1
    assert '"2031fc_4", 0x2031fc, 0x2031ff' in script
    assert 'execution_state ~= "stop" then return' in script, "dumps only at a stop"
    assert 'replace(it.path .. ".tmp", it.path)' in script, "whole or absent, never half-written"
    assert len(script) < transport.SCRIPT_MAX, "one console line"


def test_the_tap_is_bus_aligned_filters_by_landing_and_pays_no_string_per_write() -> None:
    """MAME refuses a one-byte tap on a 16-bit bus: the tap is bus-aligned, filters by landing."""
    script = tally.install_script("20351c_1", 0x20351C, 1, Path("/s/t.txt"))
    assert "local lo, hi = first - (first % nb), last + (nb - 1 - (last % nb))" in script
    assert "local aligned = lo == first and hi == last" in script
    assert 'install_write_tap(lo, hi,' in script
    assert "if not aligned and not lands(offset, mask) then return end" in script
    assert 'local curpc = cpu.state["CURPC"]' in script, "hoisted: the writer, not the prefetch"
    assert script.index('local curpc = cpu.state["CURPC"]') < script.index("install_write_tap")
    assert "local pc = curpc.value" in script
    assert "local k = ((data & mask) << 32) | mask" in script
    callback = script.split("install_write_tap")[1].split("T.items[id] = t")[0]
    assert "string.format" not in callback


def test_the_removal_takes_the_tap_and_the_registry_entry_and_refuses_nothing() -> None:
    script = mtap.remove_script("2031fc_4", tally.REGISTRY)
    assert "it.tap:remove()" in script and "T.items[id] = nil" in script
    assert 'print("MCP_TALLY absent tally_id=" .. id)' in script




def test_a_captured_dump_parses_whole_and_a_cut_one_is_no_table() -> None:
    dump = tally.parse_dump(DUMP)
    assert dump is not None
    assert dump["id"] == "2031fc_4" and dump["frame"] == 61 and dump["seq"] == 62
    assert dump["total"] == 102 and len(dump["values"]) == 52 and dump["pcs"] == [(0x40E, 102)]
    assert dump["data_width"] == 16 and dump["endianness"] == "big" and dump["cpu"] == ":maincpu"
    assert (0x2031FC, 0, 0xFFFF, 51) in dump["values"], "the high word, zero, 51 times"
    assert (0x2031FE, 0x32, 0xFFFF, 1) in dump["values"]
    # No `end` line is no table: a prefix would report a count that stopped where the file did.
    assert tally.parse_dump(DUMP.rsplit("end", 1)[0]) is None
    assert tally.parse_dump("MCP_TALLY x seq=1 frame=1 total=0 nope=1\nend") is None
    assert tally.parse_dump(DUMP.replace("p 40e 102", "q 40e 102")) is None
    assert tally.parse_dump("") is None


def test_the_two_overflow_counts_are_read_from_their_own_fields() -> None:
    """Every capture has both at zero, and two regex groups swapped would read the same."""
    dump = tally.parse_dump(TWO_WRITERS)
    assert dump is not None
    assert dump["overflow_values"] == 7 and dump["overflow_pcs"] == 3
    assert dump["pcs"] == [(0x40E, 490), (0x1234, 10)] and dump["total"] == 500


def test_the_value_table_decodes_a_whole_write_in_the_watch_format_and_marks_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A whole write decodes to `value`; a part of the range or an undecodable one is `partial`."""
    dump = tally.parse_dump(DUMP)
    assert dump is not None
    rows = tally._value_rows(dump, 0x2031FE, 2, "u16", 3)
    assert rows[0] == {"at": "0x002031fc", "raw_hex": "", "count": 51, "partial": True}
    assert rows[1] == {"at": "0x002031fe", "raw_hex": "0001", "count": 1, "value": 1}
    whole = tally._value_rows(dump, 0x2031FC, 4, "u32", 60)
    assert len(whole) == 52 and all(r.get("partial") is True for r in whole)
    assert whole[0] == {"at": "0x002031fc", "raw_hex": "0000", "count": 51, "partial": True}
    assert sorted(r["raw_hex"] for r in whole[1:])[:3] == ["0001", "0002", "0003"]

    class Refusing:
        def decode(self, raw: bytes, order: str, width: int) -> object:
            raise vf.FormatError("no")

    monkeypatch.setattr(vf, "parse", lambda fmt: Refusing())
    undecodable = tally._value_rows(dump, 0x2031FE, 2, "u16", 2)
    assert undecodable[1] == {"at": "0x002031fe", "raw_hex": "0001", "count": 1, "partial": True}


def test_a_value_is_decoded_in_the_byte_order_the_dump_names() -> None:
    """A whole write is decoded in the byte order the dump names, not the first thread's cpu."""
    dump = tally.parse_dump(DUMP)
    assert dump is not None and dump["endianness"] == "big"
    assert tally._value_rows(dump, 0x2031FE, 2, "u16", 3)[1]["value"] == 1
    swapped = {**dump, "endianness": "little"}
    row = tally._value_rows(swapped, 0x2031FE, 2, "u16", 60)
    whole = [r for r in row if "value" in r]
    assert whole and all(r["value"] == int.from_bytes(bytes.fromhex(r["raw_hex"]), "little")
                         for r in whole), whole


def test_the_writer_table_places_each_pc_inside_the_nearest_symbol_and_is_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dump = tally.parse_dump(TWO_WRITERS)
    assert dump is not None
    use_table(monkeypatch, table={"IRQ_VBLANK": 0x400, "MAIN": 0x1000})
    assert tally._writer_rows(dump, 5) == [
        {"pc": "0x0000040e", "count": 490, "symbol": "IRQ_VBLANK+0xe"},
        {"pc": "0x00001234", "count": 10, "symbol": "MAIN+0x234"}]
    assert tally._writer_rows(dump, 1) == [{"pc": "0x0000040e", "count": 490,
                                           "symbol": "IRQ_VBLANK+0xe"}]
    use_table(monkeypatch, table={"MAIN": 0x1000})
    assert tally._writer_rows(dump, 5)[0] == {"pc": "0x0000040e", "count": 490}, "below all"




def test_a_count_watch_is_a_mode_of_the_store_and_stale_like_a_change_watch() -> None:
    d = dec.Declaration("watch", "address", "0x2031fc", width=4, fmt="u32", watch_mode="count",
                        fingerprint="fp-a")
    assert dec.Declaration.from_dict(d.to_dict()) == d
    assert dec.is_stale(d, "fp-b") is True, "a raw address tapped blind lands anywhere"
    assert dec.is_stale(d, "fp-a") is False
    store = dec.DeclarationStore("k", path=None)
    store.add(d)
    with pytest.raises(dec.DeclarationError, match="not be both count AND change"):
        store.add(dec.Declaration("watch", "address", "0x2031fc", width=4, fmt="u32",
                                  watch_mode="change"))




def test_watch_add_count_sends_the_install_and_stores_pending_moving_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    out = s.watch_add(ref="frame_lo", mode="count", length=4)
    assert out["status"] == "ok" and out["state"] == "pending", out
    assert (out["installed"], out["pending"]) == (False, True)
    assert out["armed"] is False and out["stored"] is True
    assert out["tally_id"] == "2031fc_4" and out["call"] == "MAME_MCP_LUA_END#1"
    assert out["write_maps_to"] == "memory@200000" and out["lines_ahead"] == 0
    assert out["session"]["altered"] is False
    assert b"install_write_tap" in _sent() and b'\\"2031fc_4\\"' in _sent()
    assert ses.watchpoints == [], "no `Z2`: a tally is a tap, not a watchpoint"
    rec = mstate.STATE.tallies[("frame_lo", ":maincpu")]
    assert rec["addr"] == 0x2031FC and rec["width"] == 4 and rec["installed"] is None
    assert rec["path"] == tmp_path / "tally-2031fc-4.txt"
    assert out["summary"] == "watch_add frame_lo: count watch pending at 0x002031fc, 4 bytes"
    # A re-declaration adopts and re-sends the install (idempotent in Lua by id).
    again = s.watch_add(ref="frame_lo", mode="count", length=4)
    assert again["already_stored"] is True and again["call"] == "MAME_MCP_LUA_END#2"


def test_a_send_the_console_pipe_refuses_stores_no_declaration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The install is sent before the declaration is stored, so a refused send stores nothing."""
    _tallying(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "lua_seq", transport.PIPE_STEPS_MAX + 1)
    out = refused("ahead", s.watch_add(ref="frame_lo", mode="count", length=4))
    assert out["code"] == "bad_argument"
    assert arming.store().declarations() == [] and mstate.STATE.tallies == {}
    assert _sent() == b""


def test_watch_add_count_arms_the_rom_copy_and_refuses_a_second_tally_and_a_pointer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An unmapped write side arms, noted; a second tally on a range or a pointer is refused."""
    _tallying(monkeypatch, tmp_path)
    out = s.watch_add(ref="copy_in_rom", mode="count", length=2)
    assert out["status"] == "ok" and out["write_maps_to"] == "unmapped", out
    assert "nothing in the machine handles a write at 0x400" in out["note"], out
    assert "reads as memory, the ROM copy" in out["note"]
    assert ("copy_in_rom", ":maincpu") in mstate.STATE.tallies
    sent = s.watch_add(ref="frame_lo", mode="count", length=4)
    assert sent["write_maps_to"] == "memory@200000" == sent["read_maps_to"], sent
    out = refused(re.escape("already has a tally declared under 'frame_lo': one tally is one "
                            "declaration, so `declaration_clear(kind=\"watch\", ref='frame_lo', "
                            "cpu=\":maincpu\")` frees "
                            "it, or use that ref"),
                  s.watch_add(ref="0x2031fc", mode="count", length=4))
    assert out["code"] == "ambiguous_ref"
    assert list(mstate.STATE.tallies) == [("copy_in_rom", ":maincpu"), ("frame_lo", ":maincpu")]
    out = refused("not by pointer", s.watch_add(ref="[frame_lo]+0x4", mode="count", length=2))
    assert out["code"] == "bad_argument"
    out = refused("not be both count AND change",
                  s.watch_add(ref="frame_lo", mode="change", length=4))


def _on_bus(monkeypatch: pytest.MonkeyPatch, data_width: int) -> None:
    """`start`'s inventory with the double's cpu's program space `data_width` bits wide."""
    monkeypatch.setattr(mstate.STATE, "machine_map", {**mstate.STATE.machine_map, "spaces": [
        {"cpu": ":maincpu", "space": "program", "data_width_bits": data_width, "endianness": "big",
         "entries": 13, "address_mask": "0x00ffffff"}]})


@pytest.mark.parametrize(("addr", "length"), [(0x2031FD, 2), (0x2031FD, 4), (0x2031FC, 3)],
                         ids=["odd-2", "odd-4", "even-3"])
def test_a_count_watch_that_splits_a_bus_word_is_refused_with_nothing_sent_or_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, addr: int, length: int,
) -> None:
    """A range covering a bus word only in part is refused before the console is asked anything."""
    ses = _tallying(monkeypatch, tmp_path)
    _on_bus(monkeypatch, 16)
    out = refused("split a 16-bit bus word",
                  s.watch_add(ref=f"{addr:#x}", mode="count", length=length))
    assert out["code"] == "bad_argument", out
    assert f'`watch_add(ref="{addr:#x}", mode="count", length={2 - addr % 2})`' in out["message"]
    assert _sent() == b"" and mstate.STATE.tallies == {}
    assert arming.store().declarations() == []
    assert not [c for c in ses.commands if c.startswith("map ")], "judged before the map"


@pytest.mark.parametrize(("addr", "width", "data_width", "first", "others"), [
    (0x2031FD, 2, 16, (0x2031FD, 1), "0x2031fe (length=1)"),
    (0x2031FD, 4, 16, (0x2031FD, 1), "0x2031fe (length=2), 0x203200 (length=1)"),
    (0x2031FC, 3, 16, (0x2031FC, 2), "0x2031fe (length=1)"),
    (0x101, 10, 16, (0x101, 1), "0x102 (length=2), every bus word after it, and 0x10a (length=1)"),
    (0x103, 2, 32, (0x103, 1), "0x104 (length=1)"),
    (0x102, 4, 32, (0x102, 2), "0x104 (length=2)"),
    (0x101, 8, 32, (0x101, 3), "0x104 (length=4), 0x108 (length=1)")])
def test_the_refusal_names_one_count_per_bus_word_the_range_touches(
    monkeypatch: pytest.MonkeyPatch, addr: int, width: int, data_width: int,
    first: tuple[int, int], others: str,
) -> None:
    monkeypatch.setattr(mstate.STATE, "first_cpu", ":maincpu")
    why = tally.split_why(addr, width, data_width, ":maincpu")
    assert why.startswith(f"{width} bytes at {addr:#x} split a {data_width}-bit bus word"), why
    assert why.endswith(f'`watch_add(ref="{first[0]:#x}", mode="count", length={first[1]})` '
                        f"and the same at {others}"), why


def test_the_refusal_names_the_cpu_when_it_is_not_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The suggested counts go where the refused one would have, naming a non-first cpu."""
    monkeypatch.setattr(mstate.STATE, "first_cpu", ":maincpu")
    assert 'length=1, cpu=":subcpu")`' in tally.split_why(0x101, 2, 16, ":subcpu")
    assert "cpu=" not in tally.split_why(0x101, 2, 16, ":maincpu")
    assert "cpu=" not in tally.split_why(0x101, 2, 16, None)


@pytest.mark.parametrize(("addr", "length", "data_width"), [
    (0x2031FD, 1, 16), (0x2031FE, 2, 16), (0x2031FC, 4, 16), (0x2031FD, 2, 8),
    (0x2031FE, 2, 32), (0x2031FD, 2, 32)])
def test_a_count_watch_inside_a_bus_word_or_of_whole_ones_is_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, addr: int, length: int, data_width: int,
) -> None:
    """A range inside one bus word, or of whole words, is installed; an 8-bit bus refuses none."""
    _tallying(monkeypatch, tmp_path)
    _on_bus(monkeypatch, data_width)
    out = s.watch_add(ref=f"{addr:#x}", mode="count", length=length)
    assert out["status"] == "ok" and out["state"] == "pending", out
    assert "bus word" not in out["note"], out["note"]
    assert _sent().count(b"install_write_tap") == 1


def test_a_count_watch_on_a_cpu_with_no_program_space_row_is_installed_and_says_unchecked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With no bus width to judge by the range is taken and the reply says the check did not run."""
    _tallying(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "machine_map", {})
    out = s.watch_add(ref="0x2031fd", mode="count", length=2)
    assert out["status"] == "ok" and out["state"] == "pending", out
    assert out["note"].endswith("; " + tally.bus_unchecked_note("program")), out["note"]
    one = s.watch_add(ref="0x203201", mode="count", length=1)
    assert one["status"] == "ok" and "bus word" not in one["note"], one["note"]


def test_rearm_refuses_a_stored_count_watch_that_splits_a_bus_word(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The re-arm at `start` bypasses `watch_add`, so it judges the split itself: `unarmable`."""
    ses = _tallying(monkeypatch, tmp_path)
    _on_bus(monkeypatch, 16)
    store = arming.store()
    store.add(dec.Declaration("watch", "address", "0x2031fd", width=2, fmt="u16",
                              watch_mode="count", fingerprint="fp-test"))
    store.add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                              watch_mode="count", fingerprint="fp-test"))
    account = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(account["rearmed"]) == ["frame_lo"], account
    assert [u["ref"] for u in account["unarmable"]] == ["0x2031fd"], account
    assert "split a 16-bit bus word" in account["unarmable"][0]["why"]
    assert list(mstate.STATE.tallies) == [("frame_lo", ":maincpu")]
    assert _sent().count(b"install_write_tap") == 1


@pytest.mark.parametrize(("addr", "width", "data_width", "splits"), [
    (0x101, 2, 16, True), (0x101, 4, 16, True), (0x100, 3, 16, True), (0x101, 3, 16, True),
    (0x100, 2, 16, False), (0x100, 6, 16, False), (0x101, 1, 16, False), (0x101, 0, 16, False),
    (0x101, 2, 8, False), (0x103, 2, 32, True), (0x101, 3, 32, False), (0x102, 4, 32, True),
    (0x100, 8, 32, False)])
def test_whether_a_range_splits_a_bus_word_is_bus_arithmetic(
    addr: int, width: int, data_width: int, splits: bool,
) -> None:
    assert mspace.splits_bus_word(addr, width, data_width) is splits


def test_the_bus_width_is_the_program_space_row_of_the_cpu_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mstate.STATE, "machine_map", {})
    _on_bus(monkeypatch, 16)
    assert cpus.bus_width(":maincpu") == 16
    assert cpus.bus_width(":subcpu") is None
    assert cpus.bus_width(None) is None


def test_a_pass_that_holds_the_change_watches_leaves_the_tally_counting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A tally is not a watchpoint, so holding the change watches sends no removal."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    s.watch_add(ref="0x203200", mode="change", length=2)
    out = advance._with_watches_disarmed(ses, True, lambda: {"verdict": "ELAPSED"})  # type: ignore[arg-type]
    assert out["disarmed_watches"] == [{"ref": "0x203200", "cpu": ":maincpu"}]
    assert ("frame_lo", ":maincpu") in mstate.STATE.tallies
    assert _sent().count(b"install_write_tap") == 1
    assert b"removed tally_id" not in _sent()


def test_a_count_watch_declared_again_keeps_what_the_survey_already_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Nothing wrote between two declarations, so the next stop reports no writes since the last."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    assert _survey(ses, 61)["since_last_stop"] == 102
    again = s.watch_add(ref="frame_lo", mode="count", length=4)
    assert again["already_stored"] is True and again["call"] == "MAME_MCP_LUA_END#2"
    _answer(tmp_path, 2)
    item = _survey(ses, 61)
    assert item["installed"] is True and item["pending"] is False and item["total"] == 102, item
    assert item["since_last_stop"] == 0 and "reset" not in item, item
    # Another range under the same ref is another tap: nothing carries.
    tally.send_install(tmp_path, ("frame_lo", ":maincpu"), 0x2031FC, 2)
    rec = mstate.STATE.tallies[("frame_lo", ":maincpu")]
    assert (rec["tally_id"], rec["last_total"], rec["last_seq"]) == ("2031fc_2", 0, 0), rec


def test_the_survey_reads_the_dump_as_of_this_stop_and_says_when_it_is_behind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    item = _survey(ses, 100)
    assert item["state"] == "no_dump_yet", item
    assert (item["installed"], item["pending"]) == (False, True), item
    assert "install has no answer" in str(item["why"])
    _answer(tmp_path, 1)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    item = _survey(ses, 61)
    assert item["state"] == "tallied" and item["installed"] is True and item["cpu"] == ":maincpu"
    assert item["frame_as_of"] == 61 and item["superseded"] is False and item["total"] == 102
    assert "stale" not in item, "a reading older than the stop is `superseded`, never `stale`"
    assert item["since_last_stop"] == 102 and item["values_total"] == 52
    assert len(item["values"]) == mstate.ROWS_SHOWN  # type: ignore[arg-type]
    assert item["overflow_values"] == 0 and item["writers_total"] == 1
    assert item["writers"] == [{"pc": "0x0000040e", "count": 102, "symbol": "COPY_IN_ROM+0xe"}]
    assert item["values"][0] == {"at": "0x002031fc", "raw_hex": "0000", "count": 51,  # type: ignore[index]
                                 "partial": True}
    again = _survey(ses, 61)
    assert again["since_last_stop"] == 0 and again["total"] == 102
    # A stop the dumper has not reached within the bound is never read as current.
    monkeypatch.setattr(mtap, "DUMP_WAIT_S", 0.05)
    behind = _survey(ses, 70)
    assert behind["superseded"] is True and behind["frame_as_of"] == 61 and "stale" not in behind
    assert "frame 61" in str(behind["why"]) and "frame 70" in str(behind["why"])


def test_a_dump_that_lands_during_the_wait_is_read_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The survey polls until the dump reaches the stop's frame instead of calling it stale."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    path = tmp_path / "tally-2031fc-4.txt"
    path.write_text(DUMP)
    polls: list[float] = []

    def dumper_writes(seconds: float) -> None:
        polls.append(seconds)
        path.write_text(DUMP.replace("seq=62 frame=61 total=102", "seq=63 frame=70 total=120"))

    monkeypatch.setattr(time, "sleep", dumper_writes)
    item = _survey(ses, 70)
    assert polls == [mtap.DUMP_POLL_S], "one poll, then the dump was there"
    assert item["superseded"] is False and item["frame_as_of"] == 70 and item["total"] == 120
    assert item["since_last_stop"] == 120


def test_a_list_between_two_stops_looks_and_consumes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`declaration_list(kind="watch")` shows the tables and leaves the stop baseline alone."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    listed = s.declaration_list("watch")["watches"][0]
    assert listed["state"] == "tallied" and len(listed["values"]) == 52
    assert "since_last_stop" not in listed
    item = _survey(ses, 61)
    assert item["since_last_stop"] == 102, "the look consumed nothing"


def test_a_tally_whose_total_fell_is_a_reset_never_a_negative_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    path = tmp_path / "tally-2031fc-4.txt"
    path.write_text(DUMP)
    assert _survey(ses, 61)["since_last_stop"] == 102
    path.write_text(DUMP.replace("seq=62 frame=61 total=102", "seq=63 frame=62 total=5"))
    item = _survey(ses, 62)
    assert item["since_last_stop"] == 5 and item["reset"] is True and item["total"] == 5


def test_a_machine_with_no_screen_dumps_no_frame_and_the_survey_does_not_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    (tmp_path / "tally-2031fc-4.txt").write_text(
        DUMP.replace("seq=62 frame=61 total=102", "seq=62 frame=-1 total=102"))
    began = time.monotonic()
    item = _survey(ses, 500)
    assert time.monotonic() - began < mtap.DUMP_WAIT_S / 2, "nothing to wait for"
    assert item["state"] == "tallied" and item["frame_as_of"] == {
        "available": False, "why": "the dump was written with no frame counter to read"}, item
    assert item["superseded"] is False and "why" not in item and item["total"] == 102


def test_the_install_answer_is_matched_by_its_own_call_number_past_a_rerun(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A rerun of an earlier chunk prints its sentinel again; it must not answer a later install."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    s.watch_add(ref="0x203200", mode="count", length=2)
    # The rerun of chunk 1 lands after chunk 2 was sent: not chunk 2's sentinel.
    _console_prints(tmp_path, INSTALLED.encode() + b"\nMAME_MCP_LUA_END#1\ttrue\tnil\n" + PROMPT)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    items = {i["ref"]: i for i in watches.evaluate_watches(ses, frame=61)}  # type: ignore[arg-type]
    assert items["frame_lo"]["installed"] is True
    assert (items["0x203200"]["installed"], items["0x203200"]["pending"]) == (False, True)
    assert items["0x203200"]["state"] == "no_dump_yet"
    _answer(tmp_path, 2, output=INSTALLED.replace("2031fc_4", "203200_2"))
    items = {i["ref"]: i for i in watches.evaluate_watches(ses, frame=61)}  # type: ignore[arg-type]
    assert items["0x203200"]["installed"] is True and items["0x203200"]["cpu"] == ":maincpu"


def test_an_install_the_console_refused_is_reported_in_its_own_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A failed sentinel is `install_failed` with the console's error, never `pending` or zero."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1, ok=False, output="",
            error="install_write_tap: In range 20351c-20351c mirror 0, end address has "
                  "low bits unset, did you mean 20351d ?")
    item = _survey(ses, 61)
    assert item["state"] == "install_failed"
    assert item["installed"] is False and item["pending"] is False
    assert "low bits unset" in str(item["why"]) and "total" not in item and "error" not in item


def test_an_install_the_reader_died_holding_is_sent_again_once_then_said_lost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A line the reader died holding is resent once; a second death is `install_lost`."""
    ses = _tallying(monkeypatch, tmp_path)
    out = s.watch_add(ref="frame_lo", mode="count", length=4)
    assert (out["installed"], out["pending"]) == (False, True)
    assert out["call"] == "MAME_MCP_LUA_END#1"
    first = _sent().splitlines()[0]
    _console_prints(tmp_path, first + b"\n" + transport.THREAD_ERROR + b" attempt to index\n")
    item = _survey(ses, 61)
    assert (item["installed"], item["pending"]) == (False, True), item
    assert item.get("install_resent", 0) == 1, item
    assert "resent" not in item, "a tap's resend is `install_resent`"
    assert item["call"] == "MAME_MCP_LUA_END#2", "the resend is a new call"
    assert _sent().count(b"install_write_tap(") == 2, "the same install went out again"
    _answer(tmp_path, 2)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    item = _survey(ses, 61)
    assert item["installed"] is True and item.get("install_resent",
                                                  0) == 1 and item["state"] == "tallied"
    # The second death: a resend that dies too is lost.
    s.declaration_clear("watch", ref="frame_lo")
    s.watch_add(ref="0x203200", mode="count", length=2)
    line = _sent().splitlines()[-1]
    _console_prints(tmp_path, line + b"\n" + transport.THREAD_ERROR + b" again\n")
    item = _survey(ses, 62)
    assert (item["installed"], item["pending"]) == (False, True) and item.get("install_resent",
                                                                              0) == 1
    line = _sent().splitlines()[-1]
    _console_prints(tmp_path, line + b"\n" + transport.THREAD_ERROR + b" and again\n")
    item = _survey(ses, 63)
    assert item["state"] == "install_lost" and item["installed"] is False, item
    assert item["pending"] is False, "lost is no longer waiting for an answer"
    assert "recorded NOTHING" in str(item["why"]) and "total" not in item
    assert _survey(ses, 64)["state"] == "install_lost", "lost stays lost, nothing is resent"


def test_a_session_that_only_declares_tallies_still_counts_the_reader_deaths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A lost install pulls the reader death into the session count, so it never reads healthy."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    assert mstate.STATE.console_thread_errors == 0, "nothing has died yet"
    first = _sent().splitlines()[0]
    _console_prints(tmp_path, first + b"\n" + transport.THREAD_ERROR + b" attempt to index\n")
    _survey(ses, 61)
    assert mstate.STATE.console_lines_lost == 1, "the loss itself is recorded"
    assert mstate.STATE.console_thread_errors == 1, (
        "the death went uncounted: the session would read as healthy over a dead reader")
    assert menvelope.session_block()["console"] == {
        "thread_errors": 1, "reruns": 0, "lost": 1}


def test_a_tally_of_zero_is_a_measurement_beside_its_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    (tmp_path / "tally-2031fc-4.txt").write_text(
        "MCP_TALLY 2031fc_4 seq=1 frame=5 total=0 values=0 pcs=0 overflow_values=0 "
        "overflow_pcs=0 data_width=16 endianness=big cpu=:maincpu\nend\n")
    item = _survey(ses, 5)
    assert item["state"] == "tallied" and item["total"] == 0 and item["values"] == []
    assert item["writers"] == [] and item["frame_as_of"] == 5 and item["superseded"] is False


# Tap body raised at every write since a planted fault (`fixtures/callbacks`).
RAISED = (FIXTURES / "callbacks" / "tally-raised.txt").read_text()
RAISED_FIRST = "mcp:3: planted fault"


def test_every_callback_the_count_watch_installs_runs_under_the_guard() -> None:
    assert_every_callback_guarded(
        tally.install_script("2031fc_4", 0x2031FC, 4, Path("/s/tally-2031fc-4.txt")), 1, 0)
    assert_every_callback_guarded(
        tally.install_script("20351c_1", 0x20351C, 1, Path("/s/t.txt")), 1, 0)


def test_a_count_whose_tap_raised_says_so_and_is_never_an_empty_census(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A tap that raised at every write reports its errors beside the census, in survey and list."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="0x70001e", mode="count", length=2)
    _answer(tmp_path, 1, output=INSTALLED.replace("2031fc_4 first=2031fc last=2031ff",
                                                  "70001e_2 first=70001e last=70001f"))
    (tmp_path / "tally-70001e-2.txt").write_text(RAISED)
    item = _survey(ses, 904)
    assert item["callback_errors"] == {"count": 678, "first": RAISED_FIRST}, item
    assert (item["state"], item["total"], item["values"]) == ("tallied", 978, [])
    listed = s.declaration_list("watch")
    assert listed["watches"][0]["callback_errors"]["count"] == 678
    assert listed["summary"].endswith(", 1 with callback errors)"), listed["summary"]
    # A clean tap says a count of zero and no message.
    clean = RAISED.replace("errors=678", "errors=0").replace(f"e {RAISED_FIRST}\n", "")
    assert clean.count("errors=0") == 1 and "\ne " not in clean
    (tmp_path / "tally-70001e-2.txt").write_text(clean)
    item = _survey(ses, 904)
    none_raised = {"available": False, "why": mcallbacks.NONE_RAISED_WHY}
    assert item["callback_errors"] == {"count": 0, "first": none_raised}, item
    assert "callback errors" not in s.declaration_list("watch")["summary"]


def test_the_errors_and_the_first_message_are_read_from_their_own_lines() -> None:
    """A dump from before the guard carries no error count, which reads as unknown, never zero."""
    dump = tally.parse_dump(RAISED)
    assert dump is not None and (dump["errors"], dump["first_error"]) == (678, RAISED_FIRST)
    assert dump["values"] == [] and len(dump["pcs"]) == 4
    old = tally.parse_dump(DUMP)
    assert old is not None and (old["errors"], old["first_error"]) == (None, None)
    assert tally.parse_dump(RAISED.replace("\nend\n", "\n")) is None
    assert tally.parse_dump(RAISED.replace(f"e {RAISED_FIRST}", f"x {RAISED_FIRST}")) is None


def test_the_stop_survey_carries_the_overflows_and_the_writer_count_of_the_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fe", mode="count", length=2)
    _answer(tmp_path, 1, output=INSTALLED.replace("2031fc_4", "2031fe_2"))
    (tmp_path / "tally-2031fe-2.txt").write_text(TWO_WRITERS)
    item = _survey(ses, 40)
    assert item["overflow_values"] == 7 and item["overflow_pcs"] == 3
    assert item["writers_total"] == 2 and item["values_total"] == 2 and item["total"] == 500
    assert item["values"][0] == {"at": "0x002031fe", "raw_hex": "0001",  # type: ignore[index]
                                 "count": 300, "value": 1}


def test_watch_clear_sends_the_removal_and_drops_the_record_and_the_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    (tmp_path / "tally-2031fc-4.txt.tmp").write_text("half")
    out = s.declaration_clear("watch", ref="frame_lo")
    assert out["status"] == "ok" and out["declarations_cleared"] == 1
    assert out["tallies_removed"] == [{"tally_id": "2031fc_4", "removal": "pending",
                                       "lines_ahead": 1, "call": "MAME_MCP_LUA_END#2"}]
    assert mstate.STATE.tallies == {} and ses.watchpoints == []
    assert not (tmp_path / "tally-2031fc-4.txt").exists()
    assert not (tmp_path / "tally-2031fc-4.txt.tmp").exists()
    assert b'MCP_TALLY removed tally_id=' in _sent()
    assert watches.evaluate_watches(ses, frame=61) == []  # type: ignore[arg-type]
    s.watch_add(ref="0x203200", mode="show", length=2)
    assert "tallies_removed" not in s.declaration_clear("watch", all=True)


def test_the_install_and_the_removal_each_settle_the_reader_after_their_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Both return `pending` at once, like a stopped `throttle` (`test_lua_throttle.py`)."""
    _tallying(monkeypatch, tmp_path)
    monkeypatch.setattr(transport, "READER_SETTLE_S", 0.0137)       # not `POLL_S`'s value
    slept: list[tuple[float, int]] = []
    monkeypatch.setattr(time, "sleep", lambda s_: slept.append((s_, len(_sent()))))
    tally.send_install(tmp_path, ("frame_lo", ":maincpu"), 0x2031FC, 4)
    assert slept == [(transport.READER_SETTLE_S, len(_sent()))], slept
    slept.clear()
    assert mtap.send_remove(tmp_path, ("frame_lo", ":maincpu")) is not None
    assert slept == [(transport.READER_SETTLE_S, len(_sent()))], slept


def test_rearm_sends_every_stored_tally_again_and_accounts_for_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`start` re-sends stored tallies; unknown names are `unresolved`, refused ones `unarmable`."""
    ses = _tallying(monkeypatch, tmp_path)
    store = arming.store()
    for ref in ("frame_lo", "copy_in_rom", "ghost"):
        store.add(dec.Declaration("watch", "symbol", ref, width=4, fmt="u32", watch_mode="count",
                                  fingerprint="fp-test"))
    account = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(account["rearmed"]) == ["frame_lo", "copy_in_rom"]
    rom = next(r for r in account["rearmed"] if r["ref"] == "copy_in_rom")
    assert "nothing in the machine handles a write at 0x400" in rom["note"], (
        "a tap re-armed on an unmapped side says so, as its `watch_add` did")
    assert "note" not in next(r for r in account["rearmed"] if r["ref"] == "frame_lo")
    assert refs(account["unresolved"]) == ["ghost"] and account["unarmable"] == []
    assert list(mstate.STATE.tallies) == [("frame_lo", ":maincpu"), ("copy_in_rom", ":maincpu")]
    assert _sent().count(b"install_write_tap") == 2
    # A pipe too deep refuses by name; the pass still accounts for the rest.
    mstate.STATE.tallies.clear()
    monkeypatch.setattr(mstate.STATE, "lua_seq", transport.PIPE_STEPS_MAX + 1)
    account = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(account["rearmed"]) == [] and refs(account["unresolved"]) == ["ghost"]
    whys = {u["ref"]: u["why"] for u in account["unarmable"]}
    assert "ahead" in whys["frame_lo"] and "ahead" in whys["copy_in_rom"]
    assert mstate.STATE.tallies == {}


def test_a_count_declaration_with_no_record_this_session_says_so_at_a_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stored declaration with no tally sent is a state at the stop, never an empty table."""
    ses = _tallying(monkeypatch, tmp_path)
    arming.store().add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u32",
                                       watch_mode="count"))
    item = _survey(ses, 1)
    assert item["state"] == "not_installed" and "rearm" in str(item["why"])
    listed = s.declaration_list("watch")["watches"][0]
    assert listed["state"] == "not_installed"


def test_the_check_of_a_count_watch_needs_no_machine() -> None:
    with pytest.raises(mstate.Invalid, match="not by pointer"):
        tally.check_count_watch("pointer")
    with pytest.raises(mstate.Invalid, match="not by expr"):
        tally.check_count_watch("expr")
    tally.check_count_watch("symbol")
    tally.check_count_watch("address")
def _cleared_with_the_console_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> tuple[_WatchSession, bytes]:
    """A tally installed and cleared, the console silent on the removal; returns its line."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    assert _survey(ses, 61)["installed"] is True
    out = s.declaration_clear("watch", ref="frame_lo")
    assert out["tallies_removed"][0]["removal"] == "pending"
    return ses, _sent().splitlines()[-1]


def _removals(ses: _WatchSession) -> list[dict[str, object]]:
    """What the session block says is stuck once `declaration_list` has read the removals."""
    watches.list_watches(ses)  # type: ignore[arg-type]
    return mstate.tallies_not_removed()


def test_a_removal_the_console_ran_leaves_no_row_and_no_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The sentinel is the sweep's only exit for a removal that worked."""
    ses, _line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    assert mstate.STATE.tally_removals, "the removal is pending and has to be recorded"
    _answer(tmp_path, 2, output="MCP_TALLY removed tally_id=2031fc_4")
    assert _removals(ses) == [], "a tap that went is not news"
    assert mstate.STATE.tally_removals == [], "and the record goes with it"



def test_status_lists_a_removal_while_it_waits_and_drops_it_once_the_console_ran_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A waiting removal is a `status` row that leaves once run; a latched failure leaves too."""
    ses, _line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    assert s.status()["tallies_pending_removal"] == [
        {"tally_id": "2031fc_4", "call": "MAME_MCP_LUA_END#2"}]
    _answer(tmp_path, 2, output="MCP_TALLY removed tally_id=2031fc_4")
    assert s.status()["tallies_pending_removal"] == []
    assert _removals(ses) == [] and mstate.STATE.tally_removals == []

def test_a_removal_the_console_refused_is_not_read_as_one_that_worked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `false` sentinel means the tap is still there, so the record must not be dropped."""
    ses, _line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    _answer(tmp_path, 2, ok=False, output="",
            error="mcp:5: attempt to index a nil value (field 'tap')")
    rows = _removals(ses)
    assert [r["state"] for r in rows] == ["refused"], rows
    assert "attempt to index" in str(rows[0]["why"]) and "error" not in rows[0], rows[0]
    assert "was not carried out" in str(rows[0]["why"]), "no more than the branch knows"


def test_a_removal_the_reader_died_holding_is_reported_and_never_resent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The install resends; a removal must not: `tally_id` is the RANGE, so a blind resend
    could remove whatever tap holds it now. The row latches and keeps saying so."""
    ses, line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    sent_before = _sent().count(b"it.tap:remove()")
    _console_prints(tmp_path, line + b"\n" + transport.THREAD_ERROR + b" attempt to index\n")
    rows = _removals(ses)
    assert [r["state"] for r in rows] == ["lost"], rows
    assert "never evaluated" in str(rows[0]["why"])
    assert _sent().count(b"it.tap:remove()") == sent_before, "a removal is NEVER resent"
    # It keeps saying so: this has no declaration left to hang from, so the row latches.
    assert [r["state"] for r in _removals(ses)] == ["lost"], "lost stays lost"
    assert _sent().count(b"it.tap:remove()") == sent_before, "and still nothing is resent"


def test_a_removal_handed_back_unrun_with_no_death_is_lost_and_never_resent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Echo then prompt, no sentinel (`transport.passed_over`): a lost removal, never resent."""
    ses, line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    sent_before = _sent().count(b"it.tap:remove()")
    _console_prints(tmp_path, line + b"\n" + PROMPT)
    rows = _removals(ses)
    assert [r["state"] for r in rows] == ["lost"], rows
    assert s.status()["tallies_pending_removal"] == [], "lost, so no longer waiting"
    assert _sent().count(b"it.tap:remove()") == sent_before, "a removal is NEVER resent"
    assert 2 not in mstate.STATE.lua_pending, "the console's accounting settled the line"


def test_a_removal_echoed_with_nothing_behind_it_still_waits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control: an echo alone is a reader still holding the line."""
    ses, line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    _console_prints(tmp_path, line + b"\n")
    assert _removals(ses) == []
    assert s.status()["tallies_pending_removal"] == [
        {"tally_id": "2031fc_4", "call": "MAME_MCP_LUA_END#2"}]


def test_a_pending_install_reads_no_dump_another_tap_left_on_its_range(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`tally_id` is the range, so until this install answers nothing on disk is this tap's."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    item = _survey(ses, 61)
    assert (item["installed"], item["pending"]) == (False, True), item
    assert item["state"] == "no_dump_yet" and "total" not in item, item


def test_an_answered_install_reads_its_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control: the same file, once the install answered, is the tap's."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    item = _survey(ses, 61)
    assert item["installed"] is True and item["state"] == "tallied" and "total" in item, item


def test_an_install_over_no_tap_removes_the_dump_a_removed_one_left(tmp_path: Path) -> None:
    """With no tap of the range in the registry the install deletes any dump left at its path."""
    path = tmp_path / "tally-10-2.txt"
    script = tally.install_script("10_2", 0x10, 2, path)
    removal = 'if old == nil then os.remove(path) os.remove(path .. ".tmp") end'
    assert script.count(removal) == 1, script
    assert script.index("local old = T.items[id]") < script.index(removal), "old is read first"
    assert script.index(removal) < script.index("T.items[id] = t"), "before the tap is held"


def test_a_resend_would_carry_away_a_tally_that_is_alive_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Why the sweep only looks: a resend aimed at the old removal would remove the NEW tap."""
    ses, line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    _console_prints(tmp_path, line + b"\n" + transport.THREAD_ERROR + b" died\n")
    # Allowed once the clear removed the declaration; installs over the tap that never went.
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 3)
    sent_before = _sent().count(b"it.tap:remove()")
    assert _removals(ses)[0]["state"] == "lost", "the old removal is still reported"
    assert _sent().count(b"it.tap:remove()") == sent_before, (
        "nothing may be sent at the live tally's range")


_LATER = DUMP.replace("seq=62 frame=61 total=102", "seq=63 frame=70 total=120")


def _declared_again_over(tmp_path: Path, ses: _WatchSession) -> dict[str, object]:
    """The range declared again after the clear, its install answered, then the first survey."""
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 3)
    assert "old[k]" in _sent().splitlines()[-1].decode(), "the install carries the old counts"
    (tmp_path / "tally-2031fc-4.txt").write_text(_LATER)
    return _survey(ses, 70)


@pytest.mark.parametrize("end", ["lost", "refused"])
def test_a_tally_declared_again_over_a_tap_that_never_went_reports_only_the_new_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, end: str,
) -> None:
    """The install carries the old tap's counts, so the latched row's last report carries over."""
    ses, line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    if end == "lost":
        _console_prints(tmp_path, line + b"\n" + transport.THREAD_ERROR + b" died\n")
    else:
        _answer(tmp_path, 2, ok=False, output="", error="mcp:5: attempt to index a nil value")
    assert [r["state"] for r in _removals(ses)] == [end]
    item = _declared_again_over(tmp_path, ses)
    assert item["total"] == 120, item
    assert item["since_last_stop"] == 18 and "reset" not in item, item


def test_a_lost_removal_nobody_looked_at_is_looked_at_by_the_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A clear then a declare back to back never listed anything, so the install looks first."""
    ses, line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    _console_prints(tmp_path, line + b"\n" + transport.THREAD_ERROR + b" died\n")
    item = _declared_again_over(tmp_path, ses)
    assert item["since_last_stop"] == 18, item


def test_the_newest_latched_row_of_the_range_speaks_and_another_ranges_row_never_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The newest latched row of THIS range is the report to carry; another range's says nothing."""
    ses, line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    _console_prints(tmp_path, line + b"\n" + transport.THREAD_ERROR + b" died\n")
    assert _declared_again_over(tmp_path, ses)["since_last_stop"] == 18
    s.declaration_clear("watch", ref="frame_lo")
    _console_prints(tmp_path,
                    _sent().splitlines()[-1] + b"\n" + transport.THREAD_ERROR + b" died\n")
    assert [r["state"] for r in _removals(ses)] == ["lost", "lost"]
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 5)
    (tmp_path / "tally-2031fc-4.txt").write_text(
        _LATER.replace("seq=63 frame=70 total=120", "seq=64 frame=80 total=125"))
    assert _survey(ses, 80)["since_last_stop"] == 5, "from the second row's 120, not the first's"
    lost = mstate.STATE.tally_removals[-1]
    s.declaration_clear("watch", ref="frame_lo")
    _answer(tmp_path, 6, output="MCP_TALLY removed tally_id=2031fc_4")
    mstate.STATE.tally_removals.append(dict(lost, tally_id="203200_2", last_total=7))
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 7)
    (tmp_path / "tally-2031fc-4.txt").write_text(
        _LATER.replace("seq=63 frame=70 total=120", "seq=65 frame=90 total=30"))
    assert _survey(ses, 90)["since_last_stop"] == 30, "the newest row of THIS range ran"


def test_a_tally_declared_again_after_a_removal_that_ran_counts_from_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control: the removal ran, so the new tap starts at zero."""
    ses, _line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    _answer(tmp_path, 2, output="MCP_TALLY removed tally_id=2031fc_4")
    assert _removals(ses) == []
    item = _declared_again_over(tmp_path, ses)
    assert item["since_last_stop"] == 120, item


def test_a_removal_still_in_the_pipe_hands_nothing_to_the_tally_declared_after_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Only a LATCHED row says the tap stayed; a pending one may yet run."""
    ses, _line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    item = _declared_again_over(tmp_path, ses)
    assert item["since_last_stop"] == 120, item


# An install ages only on evidence the console is done with its line; the double sits at frame 100.


def _taken(tmp_path: Path, seq: int, after: bytes = b"") -> None:
    """The console took call `seq`'s line (its echo) and printed `after` behind it."""
    _console_prints(tmp_path, _sent().splitlines()[seq - 1] + b"\n" + after)


def test_an_install_whose_reader_lags_is_neither_resent_nor_lost_whatever_the_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Echoed with no prompt behind it, the console has not moved on; a resend doubles the tap."""
    monkeypatch.setattr(mtap, "DUMP_WAIT_S", 0.0)          # no dump is ever written here
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _taken(tmp_path, 1)
    for frame in range(101, 111):
        item = _survey(ses, frame)
        assert (item["installed"], item["pending"]) == (False, True), (frame, item)
        assert item.get("install_resent", 0) == 0, (frame, item)
    assert _sent().count(b"install_write_tap(") == 1, "nothing was resent"
    assert mstate.STATE.console_lines_lost == 0, "a line still waiting for the hook is not lost"
    _console_prints(tmp_path, INSTALLED.encode() + b"\nMAME_MCP_LUA_END#1\ttrue\tnil\n" + PROMPT)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    item = _survey(ses, 111)
    assert item["installed"] is True and item.get("install_resent", 0) == 0, item


def test_an_install_the_console_has_not_taken_waits_whatever_the_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """No echo: the line is still in the pipe and is never counted lost."""
    monkeypatch.setattr(mtap, "DUMP_WAIT_S", 0.0)
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    for frame in (100, 101, 150):
        item = _survey(ses, frame)
        assert (item["installed"], item["pending"]) == (False, True), (frame, item)
        assert item.get("install_resent", 0) == 0, (frame, item)
        assert item["call"] == "MAME_MCP_LUA_END#1"
    assert _sent().count(b"install_write_tap(") == 1
    assert mstate.STATE.console_lines_lost == 0


def test_an_install_the_console_passed_over_is_resent_with_no_frame_run_then_said_lost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Echo then prompt with no sentinel is the evidence; it needs no frame."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _taken(tmp_path, 1, PROMPT)
    item = _survey(ses, 100)
    assert (item["installed"], item["pending"]) == (False, True), item
    assert item.get("install_resent", 0) == 1, item
    assert item["call"] == "MAME_MCP_LUA_END#2", "the resend is a new call"
    assert _sent().count(b"install_write_tap(") == 2
    assert mstate.STATE.console_lines_lost == 1, "a line taken and never evaluated is lost"
    assert list(mstate.STATE.lua_pending) == [2] and mstate.STATE.lua_lost == 1, \
        "the original is settled lost and the resend is the one still ahead"
    _taken(tmp_path, 2, PROMPT)
    item = _survey(ses, 100)
    assert item["state"] == "install_lost" and item["installed"] is False, item
    assert mstate.STATE.console_lines_lost == 2 and mstate.STATE.lua_lost == 2
    assert mstate.STATE.lua_pending == {}
    assert "total" not in item
    assert _survey(ses, 101)["state"] == "install_lost"
    assert _sent().count(b"install_write_tap(") == 2, "lost is never resent"


def test_the_prompt_before_an_echo_is_the_reader_that_took_the_line_not_one_past_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control: the prompt before an echo is the reader taking the line."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _console_prints(tmp_path, PROMPT)
    _taken(tmp_path, 1)
    item = _survey(ses, 100)
    assert (item["installed"], item["pending"]) == (False, True), item
    assert item.get("install_resent", 0) == 0, item


def test_installs_sent_back_to_back_wait_their_turn_whatever_the_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The hook reads one line per run, so no number of frames says the fourth install never ran."""
    monkeypatch.setattr(mtap, "DUMP_WAIT_S", 0.0)          # no dump is ever written here
    ses = _tallying(monkeypatch, tmp_path)
    adds = [s.watch_add(ref=ref, mode="count", length=4)
            for ref in ("0x2031fc", "0x203200", "0x203204", "0x203208")]
    assert [a["lines_ahead"] for a in adds] == [0, 1, 2, 3], "each counts the ones sent before"
    ids = [rec["tally_id"] for rec in mstate.STATE.tallies.values()]
    for seq in (1, 2, 3):
        _answer(tmp_path, seq, output=INSTALLED.replace("2031fc_4", ids[seq - 1]))
    _taken(tmp_path, 4)
    for frame in range(101, 111):
        items = watches.evaluate_watches(ses, frame=frame)         # type: ignore[arg-type]
        assert [i.get("install_resent", 0) for i in items] == [0, 0, 0, 0], (frame, items)
    assert (items[3]["installed"], items[3]["pending"]) == (False, True)
    assert items[3]["call"] == "MAME_MCP_LUA_END#4"
    assert _sent().count(b"install_write_tap(") == 4
    assert mstate.STATE.console_lines_lost == 0


def test_a_list_resends_an_install_the_console_passed_over(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`declaration_list(kind="watch")` has no stop of its own and reads the same evidence."""
    _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _taken(tmp_path, 1, PROMPT)
    listed = s.declaration_list("watch")["watches"][0]
    assert (listed["installed"], listed["pending"]) == (False, True), listed
    assert listed.get("install_resent", 0) == 1, listed
    assert listed["call"] == "MAME_MCP_LUA_END#2"


def test_an_install_passed_over_is_out_of_the_pipe_before_any_survey_reads_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console's own accounting settles a passed-over line before any survey looks."""
    _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _taken(tmp_path, 1, PROMPT)
    assert transport.pending_lines(tmp_path) == 0
    assert mstate.STATE.console_lines_lost == 1


def test_a_callers_own_script_followed_by_a_prompt_is_not_settled_by_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control: only the server's own chunks are settled by the bare prompt."""
    _tallying(monkeypatch, tmp_path)
    line, _seq = transport.send("print('x')")
    _console_prints(tmp_path, line.encode() + b"\n" + PROMPT)
    assert transport.pending_lines(tmp_path) == 1
    assert mstate.STATE.console_lines_lost == 0


def test_the_late_original_after_a_resend_is_passed_over_and_the_resend_is_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _taken(tmp_path, 1, transport.THREAD_ERROR + b" died\n")
    assert _survey(ses, 100).get("install_resent", 0) == 1
    _console_prints(tmp_path, b"MAME_MCP_LUA_END#1\ttrue\tnil\n")   # call #1's sentinel, late
    item = _survey(ses, 100)
    assert (item["installed"], item["pending"]) == (False, True), item
    assert item["call"] == "MAME_MCP_LUA_END#2", item
    _answer(tmp_path, 2)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    item = _survey(ses, 100)
    assert item["installed"] is True and item.get("install_resent", 0) == 1, item




def _logged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: bytes) -> Path:
    """The scratch of a blank session whose console log holds `raw` only."""
    blank_session(monkeypatch)
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path)
    monkeypatch.setattr(mstate.STATE, "proc", SimpleNamespace(stdin=io.BytesIO()))
    (tmp_path / "stdout.log").write_bytes(raw)
    return tmp_path


def _record(seq: int, **fields: object) -> dict[str, object]:
    """A tally's record as `send_install` leaves it, its script composed for cpu `bound`."""
    bound = fields.get("bound")
    script = tally.install_script("2031fc_4", 0x2031FC, 4, Path("/scratch/t.txt"),
                                  bound if isinstance(bound, str) else None)
    return {"tally_id": "2031fc_4", "addr": 0x2031FC, "width": 4, "path": Path("/scratch/t.txt"),
            "script": script, "registry": tally.REGISTRY, "files": [Path("/scratch/t.txt")],
            "line": "the install line", "seq": seq, "mark": 0, "installed": None,
            "cpu": None, "error": None, "resent": 0, "lost": False, **fields}


def test_the_stopped_frame_is_the_recorded_stops_and_none_while_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """What film and ramdac judge a dump's freshness against."""
    ses = _tallying(monkeypatch, tmp_path)
    monkeypatch.setitem(mstate.STATE.last_stop, "frame", 42)
    assert mstate.stopped_frame() == 42
    monkeypatch.setitem(mstate.STATE.last_stop, "frame", None)
    assert mstate.stopped_frame() is None, "a stop with no frame dates nothing"
    monkeypatch.setitem(mstate.STATE.last_stop, "frame", 42)
    ses.running = True
    assert mstate.stopped_frame() is None, "a running machine has no frame of its own"


def test_the_last_stops_frame_is_read_once_and_only_a_whole_number_is_one(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Only an integer is the last stop's frame; the stopped frame is None with no session."""
    for last, frame in (({"frame": 42}, 42), ({}, None), ({"frame": "42"}, None),
                        ({"frame": None}, None)):
        monkeypatch.setattr(mstate.STATE, "last_stop", last)
        assert mstate.last_stop_frame() == frame, last
    monkeypatch.setattr(mstate.STATE, "last_stop", {"frame": 42})
    monkeypatch.setattr(mstate.STATE, "ses", None)
    assert mstate.stopped_frame() is None, "no session stands at any frame"


def test_an_install_already_answered_or_already_lost_is_not_read_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch = _logged(monkeypatch, tmp_path, b"MAME_MCP_LUA_END#5\tfalse\tmcp:1: late words\n")
    done = _record(5, installed=True, cpu=":maincpu")
    mtap._read_install_answer(scratch, done)
    assert done["installed"] is True and done["error"] is None, done
    lost = _record(5, lost=True, resent=1)
    mtap._read_install_answer(scratch, lost)
    assert lost["installed"] is None and lost["error"] is None, lost


def test_an_install_answer_is_read_whatever_bytes_the_console_printed_around_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `true` with no `installed` line is a cpu nobody named; non-UTF-8 bytes are replaced."""
    scratch = _logged(monkeypatch, tmp_path, b"noise \xff\nMAME_MCP_LUA_END#5\ttrue\tnil\n"
                                             b"MAME_MCP_LUA_END#6\tfalse\tmcp:1: bad \xfe\n")
    rec = _record(5)
    mtap._read_install_answer(scratch, rec)
    assert rec["installed"] is True and rec["cpu"] is None, rec
    rec = _record(6)
    mtap._read_install_answer(scratch, rec)
    assert rec["installed"] is False and rec["error"] == "mcp:1: bad �", rec


def test_the_install_sent_again_is_the_same_install_writing_to_the_same_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch = _logged(monkeypatch, tmp_path, b"the install line\n" + PROMPT)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 5)
    rec = _record(5)
    mtap._read_install_answer(scratch, rec)              # taken, and passed over
    assert rec.get("resent", 0) == 1 and rec["seq"] == 6 and rec["lost"] is False, rec
    expected = transport.chunk_line(tally.install_script("2031fc_4", 0x2031FC, 4,
                                                         Path("/scratch/t.txt")), 6)
    assert mstate.STATE.proc.stdin.getvalue() == expected.encode() + b"\n"  # type: ignore[union-attr]
    assert rec["line"] == expected and rec["mark"] == len(b"the install line\n" + PROMPT), \
        "the record now reads the RESEND's answer"


class _EchoingPipe(io.BytesIO):
    """A stdin whose console echoes each line and prints a prompt before `send` returns."""

    def __init__(self, log: Path) -> None:
        super().__init__()
        self.log = log

    def write(self, data: bytes) -> int:  # type: ignore[override]
        with open(self.log, "ab") as fh:
            fh.write(data + PROMPT)
        return super().write(data)


def test_the_resend_is_read_from_before_its_own_line_reached_the_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The mark is taken before the resend, or an echo printed during `send`'s wait is unseen."""
    scratch = _logged(monkeypatch, tmp_path, b"the install line\n" + PROMPT)
    monkeypatch.setattr(mstate.STATE, "proc", SimpleNamespace(stdin=_EchoingPipe(
        tmp_path / "stdout.log")))
    monkeypatch.setattr(mstate.STATE, "lua_seq", 5)
    rec = _record(5)
    mtap._read_install_answer(scratch, rec)
    assert rec.get("resent", 0) == 1 and rec["lost"] is False, rec
    mtap._read_install_answer(scratch, rec)
    assert rec["lost"] is True, "the resend's own echo and prompt were read"


def test_a_removal_answer_is_found_past_another_calls_sentinel_and_read_in_any_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch = _logged(monkeypatch, tmp_path, b"MAME_MCP_LUA_END#3\ttrue\tnil\n"
                                             b"MAME_MCP_LUA_END#4\ttrue\tnil\n"
                                             b"MAME_MCP_LUA_END#7\tfalse\tmcp:1: bad \xfe\n")
    rem: dict[str, object] = {"tally_id": "t", "line": "x", "seq": 4, "mark": 0, "state": "",
                              "error": ""}
    mtap._read_removal_answer(scratch, rem)
    assert rem["state"] == "removed", rem
    rem = {"tally_id": "t", "line": "x", "seq": 7, "mark": 0, "state": "", "error": ""}
    mtap._read_removal_answer(scratch, rem)
    assert rem["state"] == "refused" and rem["error"] == "mcp:1: bad �", rem


def test_an_install_sent_again_keeps_the_cpu_it_was_bound_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A resend keeps the declared cpu, not whichever a later `focus` made visible."""
    scratch = _logged(monkeypatch, tmp_path, b"the install line\n" + PROMPT)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 5)
    rec = _record(5, bound=":subcpu")
    mtap._read_install_answer(scratch, rec)
    assert rec.get("resent", 0) == 1
    sent = mstate.STATE.proc.stdin.getvalue().decode()  # type: ignore[union-attr]
    assert 'devices[\\":subcpu\\"]' in sent, sent[-300:]


def test_a_tap_that_counted_across_a_reset_says_so_and_the_reset_names_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A reset or `stateload` keeps the Lua counters; the reply names taps, surveys add `across`."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    assert "across" not in _survey(ses, 61), "nothing crossed yet"
    out = s.reset()
    assert out["status"] == "ok", out
    assert out["taps_across"] == [{"ref": "frame_lo", "cpu": ":maincpu"}], out
    item = _survey(ses, 61)
    across = item["across"]
    assert isinstance(across, list) and [a["event"] for a in across] == ["softreset"], item
    assert "frame_from" in across[0] and "from_frame" not in across[0], across


def test_a_range_declared_again_over_its_live_tap_reads_that_taps_dump_while_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With no removal between, the file is the live tap's own, so it is read, not `no_dump_yet`."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    assert _survey(ses, 61)["state"] == "tallied"
    again = s.watch_add(ref="frame_lo", mode="count", length=4)
    assert again["status"] == "ok", again
    if mstate.STATE.tallies[("frame_lo", ":maincpu")]["installed"] is not None:
        pytest.fail("the declaration again sent no new install: nothing here is pending")
    item = _survey(ses, 61)
    assert (item["installed"], item["pending"]) == (False, True), item
    assert item["state"] == "tallied", item
    assert item["total"] == 102, item


def test_a_range_declared_again_after_its_removal_still_reads_no_dump_while_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control: a removal in between makes the file a removed tap's."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    s.declaration_clear("watch", ref="frame_lo")
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    item = _survey(ses, 61)
    assert (item["installed"], item["pending"]) == (False, True), item
    assert item["state"] == "no_dump_yet", item


def _dump_failed_line(tally_id: str) -> str:
    """The captured `error.log` line of a raised dumper (`fixtures/callbacks`), under `tally_id`."""
    from scry_mame import callbacks
    line = (FIXTURES / "callbacks" / "dump-failed-errorlog.txt").read_text()
    assert f"{callbacks.DUMP_FAILED} 70001e_2 " in line, "the capture is the guard's own line"
    return line.replace(" 70001e_2 ", f" {tally_id} ")


def test_a_dump_older_than_the_stop_names_the_dumper_s_error_when_it_raised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A raised dumper leaves the last finished dump, and `why` names the error, not a timing."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    monkeypatch.setattr(mtap, "DUMP_WAIT_S", 0.0)
    old = _survey(ses, 70)
    assert old["superseded"] is True and "had not written" in str(old["why"]), old
    with (tmp_path / "error.log").open("a") as log:
        log.write(_dump_failed_line("2031fc_4"))
    item = _survey(ses, 70)
    assert item["superseded"] is True, item
    assert "the dumper raised writing a newer one (mcp:3: planted fault)" in str(item["why"])


def test_a_dumper_error_followed_by_a_newer_dump_is_not_why_a_later_one_is_old(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """After a newer dump a later old reading is a timing, not that old error."""
    ses = _tallying(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    _answer(tmp_path, 1)
    path = tmp_path / "tally-2031fc-4.txt"
    path.write_text(DUMP)
    monkeypatch.setattr(mtap, "DUMP_WAIT_S", 0.0)
    with (tmp_path / "error.log").open("a") as log:
        log.write(_dump_failed_line("2031fc_4"))
    assert "planted fault" in str(_survey(ses, 70)["why"])
    path.write_text(DUMP.replace("seq=62 frame=61", "seq=63 frame=65"))
    item = _survey(ses, 70)
    assert item["superseded"] is True and "had not written" in str(item["why"]), item


def test_a_range_declared_again_before_its_first_install_answered_reads_no_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A never-installed predecessor owns no file; a live tap beside a pending one is read."""
    ses = _tallying(monkeypatch, tmp_path)
    (tmp_path / "tally-2031fc-4.txt").write_text(DUMP)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    assert _survey(ses, 61)["state"] == "no_dump_yet"
    _answer(tmp_path, 2)
    assert _survey(ses, 61)["state"] == "tallied"
    s.watch_add(ref="frame_lo", mode="count", length=4)
    s.watch_add(ref="frame_lo", mode="count", length=4)
    item = _survey(ses, 61)
    assert (item["installed"], item["pending"]) == (False, True), item
    assert item["state"] == "tallied", item


def test_the_install_note_and_throttle_say_when_the_console_reads_in_one_spelling(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The install note, `throttle`'s `applies` and description share `transport.CONSOLE_READS`."""
    import asyncio

    from scry_mame import transport
    _tallying(monkeypatch, tmp_path)
    out = s.watch_add(ref="frame_lo", mode="count", length=4)
    assert f"({transport.CONSOLE_READS})" in out["note"], out["note"]
    described = {t.name: t.description or "" for t in asyncio.run(s.mcp.list_tools())}
    assert "applies when the console next reads a line" in described["throttle"]
    assert "REFERENCE" not in out["note"], "a reply's note names nothing the client cannot read"


def test_a_replacement_before_any_stop_says_why_it_has_no_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reset before any stop read a frame leaves `frame_from` unread, said in its place."""
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    monkeypatch.setattr(mstate.STATE, "tallies", {("0x20", ":maincpu"): {}})
    mtap.mark_across("softreset")
    (across,) = mstate.STATE.tallies[("0x20", ":maincpu")]["across"]
    assert across["frame_from"]["available"] is False, across


def test_a_removal_the_console_refused_is_latched_by_the_next_stop_and_rides_every_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stop after the answer latches the refusal into every reply's session block."""
    ses, _line = _cleared_with_the_console_silent(monkeypatch, tmp_path)
    _answer(tmp_path, 2, ok=False, output="",
            error="mcp:5: attempt to index a nil value (field 'tap')")
    running.survey(ses, tmp_path)  # type: ignore[arg-type]
    assert [r["state"] for r in mstate.tallies_not_removed()] == ["refused"]
    block = menvelope.session_block()
    assert [r["state"] for r in block["tallies_not_removed"]] == ["refused"], block


def test_a_count_of_reads_taps_the_reads_and_only_the_reads() -> None:
    script = tally.install_script("2031fc_4", 0x2031FC, 4, Path("/s/t.txt"), access="r")
    assert "install_read_tap(lo, hi," in script and "install_write_tap" not in script
    assert "t.reads = t.reads + 1" in script
    assert "if not aligned and not lands(offset, mask) then return end" in script


def test_a_count_of_both_keeps_two_taps_under_the_one_a_removal_takes() -> None:
    script = tally.install_script("2031fc_4", 0x2031FC, 4, Path("/s/t.txt"), access="rw")
    assert "install_read_tap(lo, hi," in script and "install_write_tap(lo, hi," in script
    assert "t.tap = {remove = function() wtap:remove() rtap:remove() end}" in script


def test_a_count_of_writes_is_the_tap_it_always_was() -> None:
    script = tally.install_script("2031fc_4", 0x2031FC, 4, Path("/s/t.txt"))
    assert "t.tap = sp:install_write_tap(lo, hi," in script and "install_read_tap" not in script


def test_a_rerun_of_the_install_carries_the_reads_too() -> None:
    script = tally.install_script("2031fc_4", 0x2031FC, 4, Path("/s/t.txt"), access="rw")
    assert '"reads"' in script.split("do t[k] = old[k] end")[0]
    assert "reads = 0" in script


def test_the_dump_says_its_reads_and_one_without_them_reads_none() -> None:
    read = TWO_WRITERS.replace("total=500 ", "total=500 reads=77 ")
    said = tally.parse_dump(read)
    assert said is not None and said["reads"] == 77
    parsed = tally.parse_dump(TWO_WRITERS)
    assert parsed is not None and parsed["reads"] == 0 and parsed["data_width"] == 16
    assert parsed["cpu"] == ":maincpu"
    assert parsed["overflow_values"] == 7 and parsed["overflow_pcs"] == 3


def test_the_dumper_writes_the_header_the_parser_reads() -> None:
    script = tally.install_script("2031fc_4", 0x2031FC, 4, Path("/s/t.txt"))
    assert "total=%d reads=%d values=%d" in script and "it.total, it.reads, it.nvalues" in script


@pytest.mark.parametrize("access", ["r", "rw"])
def test_a_count_takes_the_reads_as_its_trigger_type(access: str) -> None:
    watches.check_watch_add("0x2031fc", "count", 4, trigger_type=access)
    made = dec.Declaration(kind="watch", ref="0x2031fc", width=4, fmt="u32", watch_mode="count",
                           by="address", trigger_type=access)
    assert dec.Declaration.from_dict(made.to_dict()).trigger_type == access


@pytest.mark.parametrize(("mode", "extra"), [("show", {}), ("change", {})])
def test_only_a_count_or_a_capture_takes_a_trigger_type(mode: str, extra: dict[str, Any]) -> None:
    with pytest.raises(dec.DeclarationError, match="trigger type"):
        dec.Declaration(kind="watch", ref="0x10", width=2, watch_mode=mode, by="address",
                        trigger_type="rw", **extra)


def test_a_capture_cannot_be_triggered_by_both() -> None:
    with pytest.raises(dec.DeclarationError, match="trigger type"):
        dec.Declaration(kind="watch", ref="0x10", width=2, watch_mode="capture", by="address",
                        trigger="0x20", trigger_type="rw")


@pytest.mark.parametrize("access", ["w", "r", "rw"])
def test_the_taps_lua_carries_no_python_template_left_unfilled(access: str) -> None:
    script = tally.install_script("2031fc_4", 0x2031FC, 4, Path("/s/t.txt"), access=access)
    assert "{BUCKETS_MAX}" not in script and "{{" not in script and "}}" not in script
    if "w" in access:
        assert f"t.nvalues < {tally.BUCKETS_MAX} then" in script
