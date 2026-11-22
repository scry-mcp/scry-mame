"""The names MAME's replies and captions carry: what the namer gives for an address, a typed
symbol and a stop's pc, that it never asks the emulator, what `knowledge_find` reads from the
machine, and the note a disassembled line carries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scry_core import naming as core_naming
from scry_core import notes
from scry_core.knowledge import sealed
from scry_core.knowledge.base import Base, Served

from scry_mame import cpus, line_notes, machine, naming, presence
from scry_mame import gdb_session as gs
from scry_mame import server as s
from scry_mame.knowledge import support
from scry_mame.state import STATE

ROOT = Path(__file__).resolve().parent.parent
#: Dictionaries of rows of a few vectors of each cpu, each with the slot it sits at.
VECTORS = Path(__file__).resolve().parent / "fixtures" / "knowledge_rows"
CHIP_HANDLER = "delegate/mc6845_device::address_w"
SINGLE = """MAME_MCP_MACHINE_BEGIN
CPU :maincpu type=m68000 name=Motorola MC68000 spaces=program
REGS :maincpu PC
SPACE :maincpu program data_width=16 endianness=big entries=3 address_mask=ffffff
ENTRY :maincpu program 1 start=0 end=fffff mirror=0 mask=0 share=- region=:maincpu region_offset=0
ENTRY :maincpu program 2 start=200000 end=20ffff mirror=0 mask=0 share=mainram region=-\
 region_offset=0
ENTRY :maincpu program 3 start=900000 end=900001 mirror=0 mask=0 share=- region=- region_offset=0
MAME_MCP_MACHINE_END
"""
NAMES = ("MAME_MCP_NAMES_BEGIN\n"
         "DEVICE\t:maincpu\tm68000\tMotorola MC68000\n"
         "DEVICE\t:crtc\tmc6845\tMotorola MC6845\n"
         "INPUT\t:IN1\tCoin 1\t1\n"
         "INPUT\t:IN1\t1 Player Start\t2\n"
         f"HANDLER\t:maincpu\tprogram\t3\t{CHIP_HANDLER}\t{CHIP_HANDLER}\n"
         "MAME_MCP_NAMES_END\n")
TWO = SINGLE.replace("MAME_MCP_MACHINE_END", "CPU :subcpu type=m68000 name=x spaces=program\n"
                     "MAME_MCP_MACHINE_END")


class Untouchable:
    """A session that fails on any use: a namer that asks the emulator goes red."""

    asked: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.asked.append(name)
        raise AssertionError(f"the namer asked the session for {name}")


def board(monkeypatch: pytest.MonkeyPatch, text: str = SINGLE, symbols: dict[str, int] | None
          = None, guarded: bool = True) -> None:
    """A machine inventory as `start` would have cached it, read from a session that would
    fail on any call."""
    found = machine.parse(text)
    parsed = machine.parse_names(NAMES)
    machine.with_handlers(found["address_map"], parsed["handlers"])
    STATE.machine_map = {**found, machine.DEVICES: parsed["devices"],
                         machine.INPUTS: parsed["inputs"]}
    if guarded:
        monkeypatch.setattr(STATE, "ses", Untouchable())
    monkeypatch.setattr(STATE, "first_cpu", ":maincpu")
    if symbols is not None:
        monkeypatch.setitem(STATE.tables, ":maincpu", gs.SymbolTable(symbols, {}, "yaml"))


class Placed(Base):
    """This server's dictionaries of rows and the vector fixtures, the entries `lock` seals (every
    one with none), each vector at the slot its fixture gives. The core places no entry of rows at
    an address yet (`Index.at` answers nothing over them), so these cases place the fixtures to
    judge what the server does with a vector it finds: the namer's order and the notes'
    plumbing."""

    def __init__(self, lock: sealed.Lock | None = None) -> None:
        super().__init__((*support.SOURCES, VECTORS), lock)
        self._slots = [(d["scope"], e["address"], e["length"], e["key"])
                       for f in sorted(VECTORS.glob("*.json"))
                       for d in [json.loads(f.read_text(encoding="utf-8"))] for e in d["entries"]]

    def at(self, address: int, scope: str = "") -> tuple[Served, int] | None:
        for of, lo, length, key in self._slots:
            if scope in ("", of) and lo <= address < lo + length:
                found = self.get("vector", key, of)
                return None if found is None else (found, address - lo)
        return None


def place_vectors(monkeypatch: pytest.MonkeyPatch, lock: sealed.Lock | None = None) -> None:
    whole = Placed(lock)
    monkeypatch.setattr(naming, "base", lambda: whole)
    monkeypatch.setattr(naming.MAMENAMER, "_base", whole)


@pytest.fixture
def every_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The namer over every entry, served or not, with the vectors placed: how a name is found,
    judged apart from the filter, which has its own cases."""
    place_vectors(monkeypatch)


@pytest.mark.usefixtures("every_entry")
def test_a_vector_address_is_named_by_the_cpus_dictionary(monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch)
    named = naming.MAMENAMER.address(8, ":maincpu", "0x8")
    assert named == core_naming.Named("vector", "bus error", "0x8", 0, "m68000:vector:2")


def test_a_symbol_beats_the_vector_and_a_typed_symbol_keeps_its_address(
        monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch, symbols={"SCORE": 0x20042B})
    typed = naming.MAMENAMER.arguments("read_memory", {"ref": "score", "length": 2})
    assert typed["ref"] == core_naming.Named("symbol", "score", "0x20042B")
    found = naming.MAMENAMER.arguments("read_memory", {"ref": "0x20042c"})
    assert found["ref"].kind == "symbol" and found["ref"].delta == 1


@pytest.mark.usefixtures("every_entry")
def test_a_vector_slot_beats_the_nearest_symbol_that_has_no_size(
        monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch, symbols={"START": 0x0})
    named = naming.MAMENAMER.address(8, ":maincpu", "0x8")
    far = naming.MAMENAMER.address(0x1000, ":maincpu", "0x1000")
    assert named is not None and far is not None
    assert (named.kind, named.name) == ("vector", "bus error")
    assert (far.kind, far.name, far.delta) == ("symbol", "START", 0x1000)


def test_the_memory_the_map_names_is_the_last_resort(monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch)
    ram = naming.MAMENAMER.address(0x200010, ":maincpu", "0x00200010")
    assert ram is not None and (ram.kind, ram.name) == ("memory", "mainram")
    rom = naming.MAMENAMER.address(0x1000, ":maincpu", "0x1000")
    assert rom is not None and rom.name == "maincpu"
    assert naming.MAMENAMER.address(0x400000, ":maincpu", "0x400000") is None


def test_a_board_with_two_cpus_and_no_cpu_named_gets_no_name(
        monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch, TWO)
    assert naming.MAMENAMER.arguments("read_memory", {"ref": "0x8"}) == {}
    assert naming.MAMENAMER.arguments("read_memory", {"ref": "0x8", "cpu": "maincpu"})


def test_a_vector_is_unnamed_until_it_is_served_and_the_machine_still_names_the_address(
        monkeypatch: pytest.MonkeyPatch) -> None:
    place_vectors(monkeypatch, support.rows_lock())
    board(monkeypatch)
    assert naming.base().by_id("m68000:vector:2") is None
    held = naming.MAMENAMER.address(8, ":maincpu", "0x8")
    assert held is not None and (held.kind, held.name) == ("memory", "maincpu")
    board(monkeypatch, symbols={"START": 0x0})
    held = naming.MAMENAMER.address(8, ":maincpu", "0x8")
    assert held is not None and (held.kind, held.name, held.delta) == ("symbol", "START", 8)
    place_vectors(monkeypatch)
    board(monkeypatch)
    assert naming.MAMENAMER.address(8, ":maincpu", "0x8") == core_naming.Named(
        "vector", "bus error", "0x8", 0, "m68000:vector:2")


def test_a_trap_line_carries_no_note_while_its_vector_is_held_back(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from scry_mame import read
    place_vectors(monkeypatch, support.rows_lock())
    board(monkeypatch)
    line = "000560: 4E40           trap    #$0"
    assert line_notes.of_listing([line], ":maincpu") == []
    assert "note" not in line_notes.on_instruction(
        read.stop_instruction(line, 0x560, ":maincpu"), ":maincpu")


def test_the_boundary_names_no_held_back_entry_in_a_reply_or_its_summary(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from scry_mame import mcp
    place_vectors(monkeypatch, support.rows_lock())
    board(monkeypatch, guarded=False)
    given = {"ref": "0x8"}
    closed = mcp.BOUNDARY.finished("read_memory", given, dict(READ),
                                   named=naming.GUARD.arguments("read_memory", given))
    assert "bus error" not in closed["summary"]
    assert not [i for i in closed.get("names", []) if "id" in i]
    place_vectors(monkeypatch)
    closed = mcp.BOUNDARY.finished("read_memory", given, dict(READ),
                                   named=naming.GUARD.arguments("read_memory", given))
    assert "(bus error)" in closed["summary"]
    assert [i["id"] for i in closed["names"] if "id" in i] == ["m68000:vector:2"] * 2


def test_a_device_names_its_chip_only_when_that_chip_is_served(
        monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch)
    STATE.machine_map[machine.DEVICES].append(
        {"tag": ":psg", "name": "AY-3-8910", "shortname": "ay8910"})
    assert naming.base().by_id("ay8910:device:ay8910") is None
    rows = {r["key"]: r for r in naming.Live().rows("device", "", "") or []}
    assert "chip" not in rows[":psg"]
    place_vectors(monkeypatch)
    rows = {r["key"]: r for r in naming.Live().rows("device", "", "") or []}
    assert rows[":psg"]["chip"] == "ay8910:device:ay8910"


def test_a_stops_pc_is_named_and_a_typed_symbols_address_is_not_repeated(
        monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch, symbols={"COUNT_COIN": 0x20B583})
    stop = {"cpu": ":maincpu", "watch_hit": {"writer_pc": "0x0020b58c"}}
    assert naming.MAMENAMER.reply("run_for", stop) == [
        ("watch_hit.writer_pc", core_naming.Named("symbol", "COUNT_COIN", "0x0020b58c", 9))]
    typed = {"ref": "count_coin", "addr": "0x0020b583", "cpu": ":maincpu"}
    assert naming.MAMENAMER.reply("read_memory", typed) == []
    untyped = {"ref": "0x20b583", "addr": "0x0020b583", "cpu": ":maincpu"}
    assert [p for p, _ in naming.MAMENAMER.reply("read_memory", untyped)] == ["addr"]
    assert naming.MAMENAMER.reply("read_memory", {"addr": 0x20B583, "cpu": ":maincpu"}) == [
        ("addr", core_naming.Named("symbol", "COUNT_COIN", "0x20B583"))]


@pytest.mark.usefixtures("every_entry")
def test_the_namer_never_asks_the_emulator_over_every_example_of_the_reference(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The proof is a counter: zero calls reach the session over every call and reply."""
    board(monkeypatch, symbols={"SCORE": 0x20042B})
    examples = json.loads((ROOT / "docs/reference/examples.json").read_text(encoding="utf-8"))
    Untouchable.asked.clear()
    guard = core_naming.Guarded(naming.MAMENAMER)
    seen = 0
    for tool, example in examples.items():
        for step in (example, *([example["then"]] if "then" in example else [])):
            tool = step.get("tool", tool)
            guard.close(tool, step["reply"], guard.arguments(tool, step["call"]), "")
            seen += 1
    assert seen >= 60 and Untouchable.asked == [] and guard.failed() is None


@pytest.mark.parametrize("given", [
    {"ref": "0x1" + "0" * 16}, {"ref": "0x900000", "data_hex": "zz"},
    {"ref": "0x900000", "data_hex": "0x"}, {"ref": "0x900000", "data_hex": "0 c"},
    {"ref": 7}, {"ref": "0x900000", "data_hex": 12}])
def test_an_argument_the_call_will_refuse_is_no_failure_of_the_namer(
        monkeypatch: pytest.MonkeyPatch, given: dict[str, Any]) -> None:
    board(monkeypatch)
    guard = core_naming.Guarded(naming.MAMENAMER)
    guard.arguments("write", given)
    assert guard.failed() is None, guard.failed()


def test_the_proof_goes_red_for_a_namer_that_asks_the_emulator(
        monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch)

    class Asking(naming.MameNamer):
        def arguments(self, tool: str, given: Any) -> Any:
            assert STATE.ses is not None
            return {"ref": STATE.ses.monitor("print 0")}

    guarded = core_naming.Guarded(Asking(naming.base()))
    Untouchable.asked.clear()
    assert guarded.arguments("read_memory", {"ref": "0x8"}) == {}
    assert Untouchable.asked == ["monitor"] and guarded.failed() is not None


def test_a_memory_row_is_named_by_a_handler_that_has_a_name_and_never_by_its_kind(
        monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch)
    STATE.machine_map["address_map"].append(
        {"cpu": ":maincpu", "space": "program", "index": 9, "start": "0x910000",
         "end": "0x910001", "read": "none", "write": "delegate/x_device::y_w"})
    STATE.machine_map["address_map"].append(
        {"cpu": ":maincpu", "space": "program", "index": 10, "start": "0x920000",
         "end": "0x920001", "read": "ram", "write": "none"})
    names = {r["key"]: r["name"] for r in naming.Live().rows("memory", "", "") or []}
    assert names["0x910000..0x910001"] == "x_device::y_w"
    assert "0x920000..0x920001" not in names


def test_knowledge_find_reads_the_inputs_the_devices_and_the_map_from_the_machine(
        monkeypatch: pytest.MonkeyPatch) -> None:
    live = naming.Live()
    assert live.rows("input", "", "") is None, "no session, no rows"
    board(monkeypatch)
    ports = live.rows("input", ":IN1", "")
    assert [r["name"] for r in ports or []] == ["Coin 1", "1 Player Start"]
    assert live.rows("input", ":IN1/Coin 1", "") == [
        {"kind": "input", "key": ":IN1/Coin 1", "name": "Coin 1", "scope": ":IN1"}]
    crtc = live.rows("device", ":crtc", "")
    assert crtc == [{"kind": "device", "key": ":crtc", "name": "Motorola MC6845",
                     "type": "mc6845"}]
    assert live.scopes() == ("m68000",)
    held = live.rows("memory", "0x200010", "") or []
    assert [r["name"] for r in held] == ["mainram"]
    assert live.rows("memory", "not a key", "") == []


def test_a_device_is_asked_by_its_tag_in_either_spelling_and_answers_the_same(
        monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch, guarded=False)
    by_key = s.knowledge_find(kind="device", key=":crtc")
    by_device = s.knowledge_find(device=":crtc")
    assert by_key["entries"] == by_device["entries"] != []
    assert by_key["entries"][0]["key"] == ":crtc"


@pytest.mark.parametrize(("cpu", "text", "expected"), [
    ("m68000", "trap    #$0", "TRAP #0 (0x80)"),
    ("m68000", "trap    #$f", "TRAP #15 (0xBC)"),
    ("m68000", "chk.w   D1, D0", "CHK (0x18)"),
    ("m68000", "trapv", "TRAPV (0x1C)"),
    ("m68000", "move.l  $8.l, D0", "bus error (0x08)"),
    ("m6809", "swi", "SWI (0xFFFA)"),
    ("m6809", "swi3", "SWI3 (0xFFF2)"),
    ("m6809", "ldx     $FFF8", "IRQ (0xFFF8)"),
    ("m6809", "stu     $FFFF", "reset+0x1 (0xFFFF)"),
    ("v30", "brkv", "overflow (0x10)"),
    ("v30", "chkind  bw, [ix]", "bound check (0x14)"),
])
@pytest.mark.usefixtures("every_entry")
def test_what_an_instruction_states_outright_is_named(cpu: str, text: str,
                                                      expected: str) -> None:
    scope = naming.MAMENAMER.scope_of_type(cpu)
    assert scope is not None
    found = notes.note(naming.base(), scope, line_notes.operands(cpu, text), names_on=True)
    assert found is not None and found.text == expected and not found.live


@pytest.mark.parametrize(("cpu", "text"), [
    ("m6809", "lda     #$FFF8"), ("m6809", "inc     <$B2"), ("m6809", "ldx     $0400"),
    ("m6809", "bvc     $FFFC"), ("m6809", "lbsr    $FFFC"), ("m6809", "lda     $FFF8,X"),
    ("m6809", "leax    $FFFE ,Y"),
    ("m68000", "move.w  $400.l, D0"), ("m68000", "move.w  D0, D1"), ("v30", "brk     21h"),
    ("v30", "call    350BAh"), ("z80", "rst 8"), ("m68010", "trap    #$0"),
])
@pytest.mark.usefixtures("every_entry")
def test_what_a_register_or_nothing_holds_is_left_as_it_is(cpu: str, text: str) -> None:
    scope = naming.MAMENAMER.scope_of_type(cpu)
    ops = line_notes.operands(cpu, text)
    assert scope is None or notes.note(naming.base(), scope, ops, names_on=True) is None


@pytest.mark.usefixtures("every_entry")
def test_a_listing_line_carries_its_note_apart_from_a_persons_comment(
        monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch)
    lines = ["000560: 4E40           trap    #$0 // a person's words",
             "000562: 3039 0020 0000 move.w  $200000.l, D0"]
    from scry_mame import read
    assert line_notes.of_listing(lines, ":maincpu") == [{"line": 0, "note": "TRAP #0 (0x80)"}]
    row = line_notes.on_instruction(read.stop_instruction(lines[0], 0x560, ":maincpu"),
                                    ":maincpu")
    assert row["note"] == "TRAP #0 (0x80)" and row["comment"] == "a person's words"
    assert cpus.cpu_type(":maincpu") == "m68000"


@pytest.mark.usefixtures("every_entry")
def test_with_the_names_off_a_disassembled_line_carries_no_note(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from scry_mame import read
    board(monkeypatch)
    lines = ["000560: 4E40           trap    #$0 // a person's words"]
    monkeypatch.setattr(STATE, "names", False)
    assert line_notes.of_listing(lines, ":maincpu") == []
    row = line_notes.on_instruction(read.stop_instruction(lines[0], 0x560, ":maincpu"),
                                    ":maincpu")
    assert "note" not in row and row["comment"] == "a person's words"


@pytest.mark.usefixtures("every_entry")
def test_disassemble_answers_line_notes_only_for_the_lines_the_base_names(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from scry_mame import read
    board(monkeypatch)
    lines = ["000560: 4E40           trap    #$0", "000562: 4E71           nop"]
    monkeypatch.setattr(read, "dasm_lines", lambda *_, **__: lines)
    monkeypatch.setattr(read, "flows", lambda *_, **__: {"flow": ["call", "sequential"],
                                                         "flow_source": "x"})
    monkeypatch.setattr(cpus, "chosen", lambda _ses, cpu: cpu or ":maincpu")
    reply = line_notes.on_disassembly(
        read.disassemble(Untouchable(), tmp_path, "0x560", 8))  # type: ignore[arg-type]
    assert reply["line_notes"] == [{"line": 0, "note": "TRAP #0 (0x80)"}]
    monkeypatch.setattr(read, "dasm_lines", lambda *_, **__: lines[1:])
    assert "line_notes" not in line_notes.on_disassembly(
        read.disassemble(Untouchable(), tmp_path, "0x562", 4))  # type: ignore[arg-type]
    refused = {"status": "INVALID", "code": "unexpected_answer"}
    assert line_notes.on_disassembly(dict(refused)) == refused


def test_a_stopped_machine_says_what_its_layers_lose() -> None:
    from scry_core import overlay
    reply = presence.overlay_reply(overlay.Overlay())
    assert set(reply["notes"]) == {"calls", "record"} and "pointer" in reply["lacking"]
    assert "notes" not in presence.overlay_reply(overlay.Overlay(calls=False, record=False))


def test_the_names_switch_is_a_start_argument_a_profile_key_and_on_by_default() -> None:
    import asyncio
    start = next(t for t in asyncio.run(s.mcp.list_tools()) if t.name == "start")
    published = start.input_schema["properties"]["names"]
    assert published["default"] is True and published["description"] == core_naming.ARGUMENT
    assert "names" in s._PROFILE_KEYS and s._START_DEFAULTS["names"] is True
    assert STATE.names is True


READ = {"status": "ok", "ref": "0x8", "addr": "0x00000008", "length": 4, "hex": "00000000",
        "cpu": ":maincpu"}


@pytest.mark.usefixtures("every_entry")
def test_the_boundary_names_a_reply_and_its_summary_while_the_switch_is_on(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from scry_mame import mcp
    board(monkeypatch, guarded=False)
    given = {"ref": "0x8"}
    closed = mcp.BOUNDARY.finished("read_memory", given, dict(READ),
                                   named=naming.GUARD.arguments("read_memory", given))
    assert "(bus error)" in closed["summary"]
    assert [i["field"] for i in closed["names"]] == ["given.ref", "addr"]
    assert closed["names"][1]["id"] == "m68000:vector:2"


@pytest.mark.usefixtures("every_entry")
def test_the_switch_leaves_a_reply_bare_and_the_captions_alone(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from scry_mame import mcp
    board(monkeypatch, guarded=False)
    monkeypatch.setattr(STATE, "names", False)
    given = {"ref": "0x8"}
    named = naming.GUARD.arguments("read_memory", given)
    closed = mcp.BOUNDARY.finished("read_memory", given, dict(READ), named=named)
    assert "names" not in closed and "bus error" not in closed["summary"]
    assert named["ref"].name == "bus error", "the window's caption still has its name"


def test_a_refused_start_leaves_the_switch_of_the_live_session_as_it_was(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from scry_mame import launch, mcp
    monkeypatch.setattr(launch, "start", lambda **_: {"status": "INVALID", "code": "session_live"})
    monkeypatch.setattr(STATE, "names", True)
    image = tmp_path / "rom.bin"
    image.write_bytes(bytes(16))
    mcp.BOUNDARY.bodies["start"](system="board", rompath=str(tmp_path),
                                 reference_rom=str(image), names=False)
    assert STATE.names is True


def test_start_sets_the_switch_a_later_close_is_judged_by(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    from scry_mame import launch
    from scry_mame import promote as mpromote
    ok = {"status": "ok", "pid": 1, "frame": 0, "pc": "0x00000000", "rom_check": "OK",
          "recommended_release": "0.289"}
    monkeypatch.setattr(launch, "start", lambda **_: dict(ok))
    monkeypatch.setattr(mpromote, "after_start", lambda reply, *_, **__: reply)
    image = tmp_path / "rom.bin"
    image.write_bytes(bytes(16))
    from scry_mame import mcp
    body = mcp.BOUNDARY.bodies["start"]
    body(system="board", rompath=str(tmp_path), reference_rom=str(image), names=False)
    assert STATE.names is False
    body(system="board", rompath=str(tmp_path), reference_rom=str(image))
    assert STATE.names is True


def test_status_says_a_namer_failed_and_the_failing_call_does_not(
        monkeypatch: pytest.MonkeyPatch) -> None:
    board(monkeypatch, guarded=False)
    guard = core_naming.Guarded(naming.MAMENAMER)
    monkeypatch.setattr(naming, "GUARD", guard)
    assert "names_failed" not in s.status()

    def broken(*_: Any) -> Any:
        raise RuntimeError("the table changed")
    monkeypatch.setattr(naming.MAMENAMER, "address", broken)
    assert guard.arguments("read_memory", {"ref": "0x8"}) == {}
    assert s.status()["names_failed"] == {"count": 1, "last": "RuntimeError: the table changed"}


def test_the_names_dump_is_read_whole_or_refused(tmp_path: Path) -> None:
    assert machine.names(tmp_path)[0] == {"devices": [], "inputs": [], "handlers": {}}
    assert "wrote no names" in machine.names(tmp_path)[1]
    dump = tmp_path / machine.NAMES_DUMP_NAME
    dump.write_text(NAMES, encoding="utf-8")
    found, why = machine.names(tmp_path)
    assert why == "" and len(found["devices"]) == 2 and len(found["inputs"]) == 2
    assert found["handlers"] == {(":maincpu", "program", 3): (CHIP_HANDLER, CHIP_HANDLER)}
    for broken, said in ((NAMES.replace("MAME_MCP_NAMES_END\n", ""), "not whole"),
                         (f"{machine.NAMES_FAILED} no ioport", "no ioport"),
                         (NAMES.replace("INPUT\t", "INPUTS\t", 1), "does not write")):
        dump.write_text(broken, encoding="utf-8")
        assert said in machine.names(tmp_path)[1], broken


def test_a_row_with_no_handler_gains_none_and_one_with_a_handler_gains_it() -> None:
    rows = [{"cpu": ":maincpu", "space": "program", "index": 1},
            {"cpu": ":maincpu", "space": "program", "index": 3}]
    machine.with_handlers(rows, {(":maincpu", "program", 3): ("ram", "none")})
    assert rows == [{"cpu": ":maincpu", "space": "program", "index": 1},
                    {"cpu": ":maincpu", "space": "program", "index": 3, "read": "ram",
                     "write": "none"}]


@pytest.mark.usefixtures("every_entry")
def test_a_stops_instruction_and_the_disassemble_tool_carry_the_note(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from server_support import _running

    from scry_mame import read, running
    ses = _running(monkeypatch, tmp_path)
    board(monkeypatch, guarded=False)
    monkeypatch.setattr(cpus, "visible_cpu", lambda _ses: ":maincpu")
    trap = "000560: 4E40           trap    #$0"
    monkeypatch.setattr(read, "dasm_lines", lambda *_, **__: [trap, "000562: 4E71  nop"])
    seen = running.survey(ses, tmp_path)  # type: ignore[arg-type]
    assert seen["instruction"]["note"] == "TRAP #0 (0x80)"
    monkeypatch.setattr(s, "stopped", lambda _what: (ses, tmp_path))
    monkeypatch.setattr(cpus, "chosen", lambda _ses, cpu: cpu or ":maincpu")
    monkeypatch.setattr(read, "flows", lambda *_, **__: {"flow": ["call"], "flow_source": "x"})
    monkeypatch.setattr(read, "dasm_lines", lambda *_, **__: [trap])
    said = s.disassemble(ref="0x560", length=4)
    assert said["line_notes"] == [{"line": 0, "note": "TRAP #0 (0x80)"}]
