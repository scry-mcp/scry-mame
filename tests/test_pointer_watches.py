"""A watch reached through a pointer (`[base]+0x28`, `base->field`), re-resolved at every stop."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scry_core import value_format as vf  # noqa: E402
from session_doubles import refs, refused, use_table  # noqa: E402
from test_watches import _watching, _WatchSession  # noqa: E402

import gdb_session as g  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

ENGINE = 0x2031FC          # the global pointer `_G_ENGINE`
HEAP = 0x210000            # where it points now
HEAP2 = 0x211000           # where it points after a realloc


def _pointing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _WatchSession:
    ses = _watching(monkeypatch, tmp_path)
    ses.pointer_width = 4          # a 68000: a pointer is a long
    use_table(monkeypatch, table={"_G_ENGINE": ENGINE, "FRAME_LO": 0x203200})
    use_table(monkeypatch, types={"_G_ENGINE": "ptr32{rate:u32,sync_delta:i16,flags:u8}"})
    ses.memory[ENGINE] = HEAP.to_bytes(4, "big")
    ses.memory[HEAP + 4] = (-7).to_bytes(2, "big", signed=True)
    ses.memory[HEAP2 + 4] = (9).to_bytes(2, "big", signed=True)
    return ses


def test_the_pointer_grammar_is_one_shape_on_both_servers() -> None:
    """`[base]`, `[base]+/-0x..` and `base->field` parse; anything else is no pointer ref."""
    assert vf.parse_pointer("[_g_engine]+0x28") == vf.PointerRef("_g_engine", 0x28, None)
    assert vf.parse_pointer("[ _g_engine ] - 0x4") == vf.PointerRef("_g_engine", -4, None)
    assert vf.parse_pointer("[2031fc]") == vf.PointerRef("2031fc", 0, None)
    assert vf.parse_pointer("_g_engine->sync_delta") == vf.PointerRef("_g_engine", 0,
                                                                        "sync_delta")
    assert vf.parse_pointer("_g_engine") is None and vf.parse_pointer("0x2031fc") is None
    with pytest.raises(dec.DeclarationError, match="pointer ref"):
        dec.Declaration("watch", "pointer", "[]+0x28", width=2, fmt="u16", watch_mode="show")
    # a pointer names data, and a breakpoint at a moving address is a stop nobody can attribute
    with pytest.raises(dec.DeclarationError, match="breakpoint"):
        dec.Declaration("breakpoint", "pointer", "[_g_engine]+0x28")


def test_the_grammar_gained_a_pointer_format_with_its_width() -> None:
    """`ptr16`/`ptr32`, bare or with a target, carry the pointer's own width."""
    p = vf.parse("ptr32{rate:u32,sync_delta:i16}")
    assert p.kind == "pointer" and p.size == 4 and p.target is not None
    assert p.target.kind == "struct" and vf.field_offset(p.target, "sync_delta") == (4, "i16")
    assert vf.parse("ptr16").size == 2 and vf.parse("ptr16").target is None
    assert p.decode(bytes.fromhex("00210000"), "big") == 0x210000
    with pytest.raises(vf.FormatError, match="no field"):
        vf.field_offset(p.target, "missing")
    with pytest.raises(vf.FormatError):
        vf.parse("ptr64")
    assert vf.FORMAT_VERSION == 4, "the class-typed pointer is a change of grammar"


def test_a_pointer_watch_is_resolved_when_armed_and_the_reply_says_through_what(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _pointing(monkeypatch, tmp_path)
    out = s.watch_add(ref="[_g_engine]+0x4", mode="show", length=2, fmt="i16")
    assert out["status"] == "ok", out
    assert out["by"] == "pointer" and out["addr"] == f"{HEAP + 4:#010x}"
    assert out["pointer"] == {"at": f"{ENGINE:#010x}", "length": 4, "value": f"{HEAP:#010x}",
                              "offset": 4}
    assert out["reading"]["value"] == -7
    # `->` takes offset and format from the base's type
    out = s.watch_add(ref="_g_engine->sync_delta", mode="show")
    assert out["status"] == "ok", out
    assert out["fmt"] == "i16" and out["length"] == 2 and out["addr"] == f"{HEAP + 4:#010x}"
    assert out["pointer"]["field"] == "sync_delta"
    listed = {w["ref"]: w for w in s.declaration_list("watch")["watches"]}
    assert listed["_g_engine->sync_delta"]["addr"] == f"{HEAP + 4:#010x}"
    assert listed["_g_engine->sync_delta"]["by"] == "pointer"


def test_a_pointer_watch_is_re_resolved_at_every_stop_and_a_change_watch_follows_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stop re-reads the pointer, and a change watch armed at the old struct follows it."""
    ses = _pointing(monkeypatch, tmp_path)
    s.watch_add(ref="_g_engine->sync_delta", mode="change")
    assert ses.watchpoints[-1][:2] == (HEAP + 4, 2)
    ses.memory[ENGINE] = HEAP2.to_bytes(4, "big")       # the pointer moved
    out = s.step()
    (w,) = out["watches"]
    assert w["addr"] == f"{HEAP2 + 4:#010x}" and w["reading"]["value"] == 9, w
    assert w["moved"] == {"from": f"{HEAP + 4:#010x}", "to": f"{HEAP2 + 4:#010x}"}
    assert ses.watchpoints[-2:] == [(HEAP + 4, 2, True), (HEAP2 + 4, 2, False)]
    assert mstate.STATE.armed_watches[("_g_engine->sync_delta", ":maincpu")]["addr"] == HEAP2 + 4
    again = s.step()
    (w,) = again["watches"]
    assert "moved" not in w and w["addr"] == f"{HEAP2 + 4:#010x}"
    cleared = s.declaration_clear("watch", ref="_g_engine->sync_delta")
    assert cleared["disarmed"] and ses.watchpoints[-1] == (HEAP2 + 4, 2, True)


def test_a_base_that_is_not_a_global_is_refused_naming_the_stack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stack local has no stable address, so it is refused rather than kept unresolved."""
    _pointing(monkeypatch, tmp_path)
    out = refused("stack local", s.watch_add(ref="[ur_count]+0x0", mode="show", length=2))
    assert out["message"].startswith("the pointer base 'ur_count' is neither a symbol of "), out
    assert out["message"].endswith("says whether the table has one"), out
    refused("stack local", s.watch_add(ref="ur_count->x", mode="show"))
    refused("ptr32", s.watch_add(ref="FRAME_LO->x", mode="show"))
    refused("no field", s.watch_add(ref="_g_engine->missing", mode="show"))


def test_a_null_or_unmapped_pointer_is_a_state_at_the_stop_never_a_watch_at_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _pointing(monkeypatch, tmp_path)
    ses.memory[ENGINE] = bytes(4)
    out = s.watch_add(ref="_g_engine->sync_delta", mode="show")
    assert out["status"] == "ok" and out["state"] == "null_pointer", out
    ses.memory[ENGINE] = HEAP.to_bytes(4, "big")
    (w,) = s.step()["watches"]
    assert w["state"] == "evaluated" and w["reading"]["value"] == -7
    # a change watch over null arms nothing until a stop finds the pointer set
    s.declaration_clear("watch", all=True)
    ses.memory[ENGINE] = bytes(4)
    out = s.watch_add(ref="_g_engine->sync_delta", mode="change")
    assert out["state"] == "null_pointer" and not ses.wplist_rows
    ses.memory[ENGINE] = HEAP.to_bytes(4, "big")
    (w,) = s.step()["watches"]
    assert w["moved"] == {"from": "null", "to": f"{HEAP + 4:#010x}"}, w
    assert w["reading"]["value"] == -7, w
    assert ses.watchpoints[-1] == (HEAP + 4, 2, False)


def test_a_pointer_watch_needs_the_machine_stopped_to_place_itself(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The pointer is a read, which a running machine cannot answer."""
    ses = _pointing(monkeypatch, tmp_path)
    ses.go()
    out = s.watch_add(ref="_g_engine->sync_delta", mode="show")
    assert out["status"] == "INVALID" and out["code"] == "not_stopped", out
    # listing on a running machine reports where the watch was armed, without chasing
    ses.interrupt()
    s.watch_add(ref="_g_engine->sync_delta", mode="change")
    ses.go()
    listed = {w["ref"]: w for w in s.declaration_list("watch")["watches"]}
    assert listed["_g_engine->sync_delta"]["addr"] == f"{HEAP + 4:#010x}"
    ses.interrupt()
    s.declaration_clear("watch", all=True)
    s.watch_add(ref="_g_engine->sync_delta", mode="show")
    ses.go()
    listed = {w["ref"]: w for w in s.declaration_list("watch")["watches"]}
    assert listed["_g_engine->sync_delta"]["state"] == "unresolved"


def test_a_move_the_debugger_refuses_keeps_the_old_row_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A move to a place nothing writes (the ROM copy) keeps the old row and says why."""
    ses = _pointing(monkeypatch, tmp_path)
    s.watch_add(ref="_g_engine->sync_delta", mode="change")
    ses.rom_write_unmapped.add(HEAP2 + 4)
    ses.memory[ENGINE] = HEAP2.to_bytes(4, "big")
    (w,) = s.step()["watches"]
    assert w["moved"]["why"] and w["moved"]["from"] == f"{HEAP + 4:#010x}", w
    assert w["moved"]["to"] == f"{HEAP2 + 4:#010x}", "the refused place is named beside why"
    assert mstate.STATE.armed_watches[("_g_engine->sync_delta", ":maincpu")]["addr"] == HEAP + 4
    assert ses.wplist_rows and f"{HEAP + 4:06X}" in ses.wplist_rows[-1]
    # value, address and baseline are the armed place's, not the refused one's
    assert w["addr"] == f"{HEAP + 4:#010x}" and w["reading"]["value"] == -7, w
    armed = mstate.STATE.armed_watches[("_g_engine->sync_delta", ":maincpu")]
    assert armed["last"] == ses.memory[HEAP + 4]
    s.declaration_clear("watch", all=True)
    ses.memory[ENGINE] = bytes(4)
    s.watch_add(ref="_g_engine->sync_delta", mode="change")
    ses.memory[ENGINE] = HEAP2.to_bytes(4, "big")
    (w,) = s.step()["watches"]
    assert w["moved"]["from"] == "null" and w["moved"]["why"], w
    assert w["moved"]["to"] == f"{HEAP2 + 4:#010x}", w
    # an unanswerable chase is reported at the stop, never a traceback
    def no_answer(addr: int, n: int, *, thread: int) -> bytes:
        raise g.SessionError("the stub answered nothing for the pointer")
    monkeypatch.setattr(ses, "read", no_answer)
    (w,) = s.step()["watches"]
    assert w["state"] == "unresolved" and w["reading"]["available"] is False, w
    assert "answered nothing" in w["reading"]["why"], w
    monkeypatch.undo()
    ses = _pointing(monkeypatch, tmp_path)
    refused("outside", s.watch_add(ref="[_g_engine]-0x00300000", mode="show", length=2))


def test_a_pointer_watch_comes_back_at_the_next_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The re-arm chases the pointer against the table this start loaded."""
    import mame_rearm as rearming
    ses = _pointing(monkeypatch, tmp_path)
    s.watch_add(ref="_g_engine->sync_delta", mode="change")
    ses.wplist_rows.clear()                           # the rows a fresh emulator lacks
    mstate.STATE.armed_watches.clear()
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["_g_engine->sync_delta"], out
    ses.memory[ENGINE] = bytes(4)
    ses.wplist_rows.clear()
    mstate.STATE.armed_watches.clear()
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert out["unarmable"] and "null" in out["unarmable"][0]["why"], out
    def no_answer(addr: int, n: int, *, thread: int) -> bytes:
        raise g.SessionError("the stub answered nothing for the pointer")
    monkeypatch.setattr(ses, "read", no_answer)
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert out["unarmable"] and "answered nothing" in out["unarmable"][0]["why"], out


def test_a_pointer_read_off_a_relocated_class_is_relocated_by_that_class_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A near pointer holds an offset in its class's segment, so the value read through the
    base symbol is relocated by that class's base (the symbol's own address already is)."""
    ses = _pointing(monkeypatch, tmp_path)
    ses.pointer_width = 2                                     # a V30: a near pointer
    use_table(monkeypatch, bases={"DATA": 0x400})
    use_table(monkeypatch, classes={"_G_ENGINE": "DATA"})
    use_table(monkeypatch, types={})
    ses.memory[ENGINE] = (0xC031).to_bytes(2, "big")          # the raw offset, as the map says
    ses.memory[0x400 + 0xC031 + 4] = (-7).to_bytes(2, "big", signed=True)
    out = s.watch_add(ref="[_g_engine]+0x4", mode="show", length=2, fmt="i16")
    assert out["status"] == "ok", out
    assert out["addr"] == f"{0x400 + 0xC031 + 4:#010x}" and out["reading"]["value"] == -7, out
    assert out["pointer"]["relocated"] == {"class": "DATA", "base": f"{0x400:#010x}",
                                           "class_from": "base"}
    # an address base carries no class: its pointer is linear
    ses.memory[0x00203300] = (0x2100).to_bytes(2, "big")
    ses.memory[0x2100] = b"\x00\x2a"
    out = s.watch_add(ref="[0x203300]", mode="show", length=2)
    assert out["addr"] == f"{0x2100:#010x}" and "relocated" not in out["pointer"], out


def test_a_bare_deref_of_a_typed_pointer_reads_as_the_struct_it_points_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`[base]` with no `fmt` on a `ptr32{...}` base reads the whole struct."""
    ses = _pointing(monkeypatch, tmp_path)
    ses.memory[HEAP] = bytes.fromhex("0000ac44") + (-7).to_bytes(2, "big", signed=True) + b"\x81"
    out = s.watch_add(ref="[_g_engine]", mode="show")
    assert out["status"] == "ok", out
    assert out["fmt"] == "{rate:u32,sync_delta:i16,flags:u8}" and out["length"] == 7
    assert out["reading"]["value"] == {"rate": 0xAC44, "sync_delta": -7, "flags": 0x81}
    import struct
    ses.memory[HEAP + 8] = struct.pack(">d", 5.17)
    out = s.watch_add(ref="[_g_engine]+0x8", mode="show", fmt="f64")
    assert out["status"] == "ok" and out["length"] == 8, out
    assert abs(out["reading"]["value"] - 5.17) < 1e-9, out


def test_a_pointer_typed_with_a_class_is_relocated_by_that_class_not_the_base_symbols(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`ptr16@CODE` places a near pointer under the target class's segment base, not the base
    symbol's class; an unknown class is refused naming the ones the table has."""
    ses = _pointing(monkeypatch, tmp_path)
    ses.pointer_width = 2
    use_table(monkeypatch, table={"ROUTINE_ANIM": 0x8436, "PUSH_START_ANIM": 0x318EB,
                                  "PLAYER1": 0x8400})
    use_table(monkeypatch, bases={"DATA": 0x400})
    use_table(monkeypatch, segment_bases={"CODE": 0x30000, "DATA": 0x8000, "V30_JUKEBOX": 0x60000})
    use_table(monkeypatch, classes={"ROUTINE_ANIM": "DATA", "PUSH_START_ANIM": "CODE",
                                    "PLAYER1": "DATA"})
    use_table(monkeypatch, types={"ROUTINE_ANIM": "ptr16@CODE",
                                  "PLAYER1": "ptr16@DATA{status:u16}"})
    ses.memory[0x8436] = (0x1923).to_bytes(2, "big")
    ses.memory[0x30000 + 0x1923] = b"\x4e\x71"
    out = s.watch_add(ref="[Routine_Anim]", mode="show", length=2)
    assert out["status"] == "ok", out
    assert out["addr"] == f"{0x30000 + 0x1923:#010x}", out
    assert out["pointer"]["relocated"] == {"class": "CODE", "base": f"{0x30000:#010x}",
                                           "class_from": "type"}, out["pointer"]
    # a class `bases` lists takes the caller's base
    ses.memory[0x8400] = (0x0020).to_bytes(2, "big")
    ses.memory[0x400 + 0x20] = b"\x00\x05"
    out = s.watch_add(ref="[Player1]", mode="show")
    assert out["status"] == "ok" and out["addr"] == f"{0x420:#010x}", out
    assert out["reading"]["value"] == {"status": 5}
    assert out["pointer"]["relocated"]["class_from"] == "type"
    use_table(monkeypatch, types={"ROUTINE_ANIM": "ptr16"})
    s.declaration_clear("watch", all=True)
    out = s.watch_add(ref="[Routine_Anim]", mode="show", length=2)
    assert out["addr"] == f"{0x400 + 0x1923:#010x}", out
    assert out["pointer"]["relocated"]["class_from"] == "base", out["pointer"]
    use_table(monkeypatch, types={"ROUTINE_ANIM": "ptr16@TEXT"})
    s.declaration_clear("watch", all=True)
    out = s.watch_add(ref="[Routine_Anim]", mode="show", length=2)
    assert out["status"] == "INVALID" and "TEXT" in out["message"], out
    assert "CODE" in out["message"] and "DATA" in out["message"], out["message"]
    # the class is judged before the null return, or a bad type is accepted at boot
    ses.memory[0x8436] = b"\x00\x00"
    out = s.watch_add(ref="[Routine_Anim]", mode="show", length=2)
    assert out["status"] == "INVALID" and "TEXT" in out["message"], out
    # a carried class whose rows share no segment base is named as such, not as absent
    use_table(monkeypatch, classes={"ROUTINE_ANIM": "DATA", "ICON_6": "V30_JUKEBOX"})
    use_table(monkeypatch, types={"ROUTINE_ANIM": "ptr16@V30_JUKEBOX"})
    use_table(monkeypatch, segment_bases={"CODE": 0x30000, "DATA": 0x8000})
    out = s.watch_add(ref="[Routine_Anim]", mode="show", length=2)
    assert out["status"] == "INVALID" and "do not share one segment base" in out["message"], out
    # `ptr16@CODEu16` is ambiguous: the class is named as read, with the spelling to use
    use_table(monkeypatch, classes={"ROUTINE_ANIM": "DATA", "PUSH_START_ANIM": "CODE"})
    use_table(monkeypatch, types={"ROUTINE_ANIM": "ptr16@CODEu16"})
    out = s.watch_add(ref="[Routine_Anim]", mode="show", length=2)
    assert out["status"] == "INVALID" and "CODEU16" in out["message"], out
    assert "ptr16@CODE{v:u16}" in out["message"], out["message"]
    # an offset reaching below the class base is refused
    use_table(monkeypatch, types={"ROUTINE_ANIM": "ptr16@CODE"})
    ses.memory[0x8436] = (0x0001).to_bytes(2, "big")
    out = s.watch_add(ref="[Routine_Anim]-0x100", mode="show", length=2)
    assert out["status"] == "INVALID" and "0x2ff01" in out["message"], out
    assert "under the CODE base 0x30000" in out["message"], out["message"]


def test_a_null_pointer_row_carries_its_pointer_block_and_the_list_and_survey_go_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A null-pointer watch is a state with its pointer block, and later watches still list."""
    ses = _pointing(monkeypatch, tmp_path)
    ses.memory[ENGINE] = bytes(4)
    out = s.watch_add(ref="_g_engine->sync_delta", mode="change")
    assert (out["stored"], out["already_stored"], out["armed"]) == (True, False, False), out
    assert out["state"] == "null_pointer" and "null" in out["note"], out
    assert s.watch_add(ref="_g_engine->sync_delta", mode="change")["already_stored"] is True
    s.watch_add(ref="frame_lo", mode="show", length=2)
    block = {"at": f"{ENGINE:#010x}", "length": 4, "value": f"{0:#010x}", "offset": 4,
             "field": "sync_delta"}
    listed = {w["ref"]: w for w in s.declaration_list("watch")["watches"]}
    assert listed["_g_engine->sync_delta"]["state"] == "null_pointer"
    assert listed["_g_engine->sync_delta"]["pointer"] == block
    assert listed["frame_lo"]["state"] == "evaluated", "listed past the null pointer"
    survey = {w["ref"]: w for w in s.step()["watches"]}
    assert survey["_g_engine->sync_delta"]["state"] == "null_pointer"
    assert survey["_g_engine->sync_delta"]["pointer"] == block
    assert "null" in survey["_g_engine->sync_delta"]["why"]
    assert survey["frame_lo"]["state"] == "evaluated", "evaluated past the null pointer"


def test_a_change_watch_armed_from_null_is_recorded_under_its_ref_and_clears_by_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _pointing(monkeypatch, tmp_path)
    ses.memory[ENGINE] = bytes(4)
    s.watch_add(ref="_g_engine->sync_delta", mode="change")
    ses.memory[ENGINE] = HEAP.to_bytes(4, "big")
    (w,) = s.step()["watches"]
    assert w["moved"] == {"from": "null", "to": f"{HEAP + 4:#010x}"}, w
    out = s.declaration_clear("watch", ref="_g_engine->sync_delta")
    assert out["disarmed"] == [f"1 @ {HEAP + 4:06X}-{HEAP + 5:06X} write"], out
    assert ses.watchpoints[-1] == (HEAP + 4, 2, True) and ses.wplist_rows == []


def test_a_pointer_is_read_in_the_cpus_byte_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _pointing(monkeypatch, tmp_path)
    ses.byte_order = "little"
    ses.memory[ENGINE] = HEAP.to_bytes(4, "little")
    ses.memory[HEAP + 4] = (-7).to_bytes(2, "little", signed=True)
    out = s.watch_add(ref="[_g_engine]+0x4", mode="show", length=2, fmt="i16")
    assert out["status"] == "ok" and out["addr"] == f"{HEAP + 4:#010x}", out
    assert out["pointer"]["value"] == f"{HEAP:#010x}" and out["reading"]["value"] == -7


def test_a_pointer_plus_a_negative_offset_reaches_zero_and_no_further(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A target at zero is a place; one below it is refused naming the pointer width."""
    ses = _pointing(monkeypatch, tmp_path)
    ses.memory[ENGINE] = (8).to_bytes(4, "big")
    out = s.watch_add(ref="[_g_engine]-0x8", mode="show", length=2)
    assert out["status"] == "ok" and out["addr"] == f"{0:#010x}", out
    out = refused("outside what a 4-byte pointer addresses",
                  s.watch_add(ref="[_g_engine]-0x10", mode="show", length=2))
    assert out["code"] == "bad_argument" and "under the" not in out["message"], out


def test_a_near_pointer_typed_with_a_class_is_read_at_its_width_and_placed_by_the_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`ptr16@DATA{...}` reads two bytes whatever the cpu's width and places by the type's class."""
    ses = _pointing(monkeypatch, tmp_path)
    use_table(monkeypatch, types={"_G_ENGINE": "ptr16@DATA{rate:u32,sync_delta:i16,flags:u8}"})
    use_table(monkeypatch, bases={"DATA": 0x400})
    use_table(monkeypatch, classes={"_G_ENGINE": "DATA"})
    ses.memory[ENGINE] = (0x2100).to_bytes(2, "big") + b"\xff\xff"
    ses.memory[0x400 + 0x2100 + 4] = (-7).to_bytes(2, "big", signed=True)
    out = s.watch_add(ref="_g_engine->sync_delta", mode="show")
    assert out["status"] == "ok", out
    assert out["pointer"]["length"] == 2 and out["pointer"]["value"] == f"{0x2100:#010x}", out
    assert out["addr"] == f"{0x400 + 0x2100 + 4:#010x}" and out["reading"]["value"] == -7
    assert out["pointer"]["relocated"] == {"class": "DATA", "base": f"{0x400:#010x}",
                                           "class_from": "type"}, out["pointer"]
    use_table(monkeypatch, types={"FRAME_LO": "ptr32"})
    refused("pointer to a struct", s.watch_add(ref="frame_lo->x", mode="show"))


def test_a_pointer_the_stub_cannot_read_leaves_an_armed_watch_placed_where_it_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _pointing(monkeypatch, tmp_path)
    s.watch_add(ref="_g_engine->sync_delta", mode="change")
    real = ses.read

    def only_the_pointer_fails(addr: int, n: int, *, thread: int) -> bytes:
        if addr == ENGINE:
            raise g.SessionError("the stub answered nothing for the pointer")
        return real(addr, n, thread=thread)

    monkeypatch.setattr(ses, "read", only_the_pointer_fails)
    (w,) = s.step()["watches"]
    assert w["state"] == "armed" and w["reading"]["available"] is False, w
    assert "answered nothing" in w["reading"]["why"], w
