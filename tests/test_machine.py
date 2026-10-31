"""The machine inventory: the boot harness's dump read back into the `machine_map` sections."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scry_core import host_program
from session_doubles import run_host_lua, use_table  # noqa: E402

from scry_mame import (
    cpus,
    gdb_session,
    machine,
    read,
    server,  # noqa: E402,F401 -- registers the tools and imports the boundary the shape guard wraps
    summaries,
    transport,
)
from scry_mame import envelope as menvelope
from scry_mame import state as st
from scry_mame.state import STATE

FIXTURES = Path(__file__).parent / "fixtures" / "machine"
M68K_DUAL = (FIXTURES / "m68k-dual.txt").read_text(encoding="utf-8")
# The sub cpu's program space as captured, and an authored variant whose sub cpu reaches less:
# m68k-dual's two masks are equal, so the capture alone cannot tell one cpu's mask from the other's.
SUB_PROGRAM = "SPACE :subcpu program data_width=16 endianness=big entries=5 address_mask=ffffff\n"
SUB_NARROWED = M68K_DUAL.replace(SUB_PROGRAM, SUB_PROGRAM.replace("=ffffff", "=3fff"))


def test_the_captured_dump_of_a_two_cpu_board_reads_back_as_two_cpus() -> None:
    """Both 68000s come back with distinct tags; declared entry counts equal parsed."""
    found = machine.parse(M68K_DUAL)
    assert [cpu["tag"] for cpu in found["cpus"]] == [":maincpu", ":subcpu"]
    assert all(cpu["name"] == "Motorola MC68000" for cpu in found["cpus"])
    assert all(cpu["type"] == "m68000" for cpu in found["cpus"])
    assert all(cpu["spaces"] == ["cpu_space", "program"] for cpu in found["cpus"])
    for space in found["spaces"]:
        entries = [e for e in found["address_map"]
                   if (e["cpu"], e["space"]) == (space["cpu"], space["space"])]
        assert len(entries) == space["entries"], f"{space['cpu']} {space['space']}"
        assert [e["index"] for e in entries] == list(range(1, len(entries) + 1))


def test_the_capture_is_still_the_multi_cpu_case_it_was_taken_for() -> None:
    """The two-cpu case holds only while the capture has two cpus with distinct tags."""
    cpus = machine.parse(M68K_DUAL)["cpus"]
    tags = [cpu["tag"] for cpu in cpus]
    assert len(cpus) > 1 and len(set(tags)) == len(tags), tags


def test_an_entry_names_its_block_or_names_nothing_at_all() -> None:
    """A field neither source backs is absent: the dump's `-` never reaches the reply as a tag."""
    found = machine.parse(M68K_DUAL)["address_map"]
    entries = {(e["cpu"], e["space"], e["index"]): e for e in found}
    rom = entries[(":maincpu", "program", 1)]
    assert rom["region"] == ":maincpu" and rom["region_offset"] == 0 and "share" not in rom
    assert (rom["start"], rom["end"]) == ("0x00000000", "0x000fffff")
    ram = entries[(":maincpu", "program", 2)]
    assert ram["share"] == ":mainram" and "region" not in ram and "region_offset" not in ram
    assert ram["mirror"] == "0x00010000", "a mirror is carried when the entry has one"
    handler = entries[(":maincpu", "program", 4)]
    assert "share" not in handler and "region" not in handler
    assert not any("-" in str(value) for e in entries.values() for value in e.values())
    assert all("address_mask" not in e for e in entries.values()), "a zero mask says nothing"
    assert all("mask" not in e for e in entries.values()), "`mask` is MAME's word for the LANE mask"


def test_the_blocks_and_the_screen_come_back_with_their_sizes() -> None:
    found = machine.parse(M68K_DUAL)
    assert found["regions"] == [
        {"tag": ":gfx1", "size": 16777216, "bytewidth": 1, "endianness": "little"},
        {"tag": ":maincpu", "size": 1048576, "bytewidth": 2, "endianness": "big"},
        {"tag": ":plds", "size": 741, "bytewidth": 1, "endianness": "little"},
        {"tag": ":subcpu", "size": 1048576, "bytewidth": 2, "endianness": "big"},
    ]
    assert found["shares"] == [
        {"tag": ":blitram", "size": 32, "bytewidth": 2, "endianness": "big"},
        {"tag": ":mainram", "size": 65536, "bytewidth": 2, "endianness": "big"},
    ]
    screen = found["screens"][0]
    assert (screen["tag"], screen["width"], screen["height"]) == (":screen", 336, 252)
    assert 50.0 < screen["refresh_hz"] < 50.1, "the board's own rate, not an assumed 60 Hz"


def test_a_space_carries_the_width_and_the_byte_order_the_machine_declared() -> None:
    """A space row carries the bus width and byte order the machine declared."""
    found = machine.parse(M68K_DUAL)
    assert found["spaces"] == [
        {"cpu": ":maincpu", "space": "cpu_space", "data_width_bits": 16, "endianness": "big",
         "entries": 7, "address_mask": "0x00ffffff"},
        {"cpu": ":maincpu", "space": "program", "data_width_bits": 16, "endianness": "big",
         "entries": 13, "address_mask": "0x00ffffff"},
        {"cpu": ":subcpu", "space": "cpu_space", "data_width_bits": 16, "endianness": "big",
         "entries": 7, "address_mask": "0x00ffffff"},
        {"cpu": ":subcpu", "space": "program", "data_width_bits": 16, "endianness": "big",
         "entries": 5, "address_mask": "0x00ffffff"},
    ]


def test_an_entry_names_its_share_and_its_region_by_the_full_tag_whatever_the_dump_spells(
) -> None:
    """A bare share and region come out under their full tags."""
    line = ("ENTRY :maincpu program 1 start=0 end=fff mirror=0 mask=0 share=videoram "
            "region=maincpu region_offset=16")
    entry = machine.parse(f"{machine.BEGIN}\nCPU :maincpu type=m6502 name=X spaces=program\n"
                          f"SPACE :maincpu program data_width=8 endianness=little entries=1 "
                          f"address_mask=ffff\n{line}\n{machine.END}\n")["address_map"][0]
    assert (entry["share"], entry["region"]) == (":videoram", ":maincpu"), entry
    assert machine.full_tag(":maincpu") == ":maincpu", "a full tag is kept as it is"


def test_a_mirror_a_mask_and_a_region_offset_are_carried_when_they_are_not_zero() -> None:
    """Mirror, mask and region-offset, which the capture cannot prove, in the gather's format."""
    line = ("ENTRY :maincpu program 1 start=200000 end=20ffff mirror=10000 mask=ff00 "
            "share=- region=:gfx1 region_offset=524288")
    entry = machine.parse(f"{machine.BEGIN}\nCPU :maincpu type=m68000 name=X spaces=program\n"
                          f"SPACE :maincpu program data_width=16 endianness=big entries=1 "
                          f"address_mask=ffffff\n"
                          f"{line}\n{machine.END}\n")["address_map"][0]
    assert entry["mirror"] == "0x00010000"
    assert entry["address_mask"] == "0x0000ff00", "a mask that is not zero reaches the reply"
    assert "mask" not in entry, "under MAME's word for it, and under no second spelling"
    assert entry["region_offset"] == 524288, "and so does an offset into the region"
    assert entry["region"] == ":gfx1" and "share" not in entry


def test_a_cpu_with_no_address_space_lists_none_rather_than_an_empty_name() -> None:
    """`spaces=` empty means no spaces, not one space named ``."""
    cpus = machine.parse(f"{machine.BEGIN}\nCPU :mcu type=m68000 name=X spaces=\n{machine.END}\n"
                         )["cpus"]
    assert cpus == [{"tag": ":mcu", "type": "m68000", "name": "X", "spaces": []}], cpus


def test_why_a_listing_failed_keeps_the_complaints_and_the_last_line_once() -> None:
    """A failed `-listxml` reduces by meaning: complaining lines, then the last line once."""
    why = machine._why_it_failed
    assert why("loading\nerror: no rom\n  \nmore\nthe end\n") == "error: no rom / the end"
    assert why("warning: a\nfatal: b\n") == "warning: a / fatal: b", "the last one is not twice"
    assert why("first\nsecond\nlast\n") == "last", "no complaint: the last line alone"
    assert why(" \n\n") == " \n\n", "nothing to reduce"


def test_a_dump_that_was_cut_off_is_refused_rather_than_parsed() -> None:
    """A truncated inventory is refused at both ends, never read as a small machine."""
    with pytest.raises(LookupError, match="cut off"):
        machine.parse("\n".join(M68K_DUAL.splitlines()[:20]) + "\n")
    with pytest.raises(LookupError, match="does not open"):
        machine.parse("\n".join(M68K_DUAL.splitlines()[1:]) + "\n")
    with pytest.raises(LookupError, match="nothing here is the machine"):
        machine.parse("")


def test_the_harness_saying_it_failed_is_read_as_a_failure_and_not_as_an_empty_machine() -> None:
    with pytest.raises(LookupError, match="could not read the machine.*io.open"):
        machine.parse(f"{machine.FAILED} io.open: permission denied\n")


def test_a_line_the_gather_does_not_write_is_refused() -> None:
    """A line neither the parse nor the gather recognises is refused, not read past."""
    with pytest.raises(LookupError, match="a line the gather does not write"):
        machine.parse(f"{machine.BEGIN}\nCPU :maincpu type=m68000 name=X spaces=program\nWHAT 1\n"
                      f"{machine.END}\n")


# Authored: an mcu with a "" region (pangofun, pmac6100), one with a "" share, a cpu with real ones.
EMPTY_TAGS_BOARD = """manager = {machine = {
  devices = {
    [":kbd:ms_naturl:ms_natrl_cpu"] = {
      debug = {}, shortname = "i8051", name = "Intel 8051", state = {PC = {}},
      spaces = {program = {data_width = 8, endianness = "little", address_mask = 0xfff,
        map = {entries = {
          {address_start = 0, address_end = 0xfff, address_mirror = 0, address_mask = 0,
           share = nil, region = "", region_offset = 0},
          {address_start = 0x1000, address_end = 0x1fff, address_mirror = 0, address_mask = 0,
           share = "", region = nil, region_offset = 0}}}}}},
    [":maincpu"] = {
      debug = {}, shortname = "i486", name = "Intel I486", state = {EIP = {}},
      spaces = {program = {data_width = 32, endianness = "little", address_mask = 0xffffffff,
        map = {entries = {
          {address_start = 0, address_end = 0x9ffff, address_mirror = 0, address_mask = 0,
           share = "mainram", region = nil, region_offset = 0},
          {address_start = 0xfffe0000, address_end = 0xffffffff, address_mirror = 0,
           address_mask = 0, share = nil, region = ":bios", region_offset = 0x10000}}}}}}},
  memory = {regions = {}, shares = {}},
  screens = {}}}
"""


def test_an_empty_region_or_share_is_absent_and_the_other_cpus_tags_are_kept(
        tmp_path: Path) -> None:
    """An empty region or share is absent, not a parse failure that loses the whole inventory."""
    dump = tmp_path / "machine.txt"
    run_host_lua(EMPTY_TAGS_BOARD + machine.harness(dump))
    parsed = machine.parse(dump.read_text(encoding="utf-8"))
    assert [(s["cpu"], s["endianness"]) for s in parsed["spaces"]] == [
        (":kbd:ms_naturl:ms_natrl_cpu", "little"), (":maincpu", "little")]
    assert [{k: v for k, v in e.items() if k in ("start", "share", "region", "region_offset")}
            for e in parsed["address_map"]] == [
        {"start": st.hex_addr(0)}, {"start": st.hex_addr(0x1000)},
        {"start": st.hex_addr(0), "share": ":mainram"},
        {"start": st.hex_addr(0xfffe0000), "region": ":bios", "region_offset": 0x10000}]


def test_no_executing_device_is_invalid_and_never_a_board_with_no_cpu() -> None:
    """A machine with no debug device is an instrument that examined nothing, and says so."""
    with pytest.raises(LookupError, match="recognised no cpu"):
        machine.parse(f"{machine.BEGIN}\nREGION :maincpu size=16 bytewidth=2 endianness=big\n"
                      f"{machine.END}\n")


def test_the_cache_of_a_scratch_with_no_dump_is_empty_sections_and_a_note(tmp_path: Path) -> None:
    """A failed gather never fails a start: empty sections and a note saying why."""
    cached = machine.cache(tmp_path, NO_XML)
    assert all(cached[name] == [] for name in machine.LIVE_SECTIONS)
    assert "wrote no inventory" in cached["note"]
    assert machine.BANKING_NOTE in cached["note"]
    assert cached["sources"] == {
        "cpus": ["live", "-listxml"], "screens": ["live", "-listxml"],
        "spaces": ["live"], "address_map": ["live"], "regions": ["live"], "shares": ["live"],
        "rom_files": ["-listxml"],
        # `sources` is a fact about the section, so it names the symbol channel with no table.
        "symbol_coverage": ["symbols"],
    }
    # `SECTIONS` holds only the emulator channels; `sources` must reach past them.
    assert set(machine.SECTIONS) < set(cached["sources"])


def test_the_cache_of_a_scratch_holding_the_capture_is_the_capture(tmp_path: Path) -> None:
    (tmp_path / machine.DUMP_NAME).write_text(M68K_DUAL, encoding="utf-8")
    cached = machine.cache(tmp_path, NO_XML)
    assert [cpu["tag"] for cpu in cached["cpus"]] == [":maincpu", ":subcpu"]
    assert machine.MAP_NOTE in cached["note"]
    assert "could not be read" not in cached["note"]


def test_a_dump_that_cannot_be_parsed_leaves_the_sections_empty_and_says_why(
    tmp_path: Path,
) -> None:
    (tmp_path / machine.DUMP_NAME).write_text("garbage\n", encoding="utf-8")
    cached = machine.cache(tmp_path, NO_XML)
    assert cached["cpus"] == [] and "could not be read" in cached["note"]


def test_the_harness_text_carries_the_dump_path_and_its_own_sentinels(tmp_path: Path) -> None:
    """The dump path reaches the composed boot script; an unsubstituted path would write nowhere."""
    text = machine.harness(tmp_path / "machine.txt")
    assert transport.lua_string(str(tmp_path / "machine.txt")) in text
    assert machine.BEGIN in text and machine.END in text and machine.FAILED in text
    assert "%(" not in text, "every placeholder was filled"
    assert "pcall" in text, "the gather cannot be allowed to abort the rest of the boot script"


# What `listxml` hands `cache` when the XML half could not be gathered.
NO_XML: tuple[dict[str, list[dict[str, object]]], str] = (
    {"cpus": [], "screens": [], "rom_files": []}, "")
LISTXML_M68K_DUAL = (FIXTURES / "listxml-m68k-dual.xml").read_bytes()
LISTXML_V30 = (FIXTURES / "listxml-v30.xml").read_bytes()


def test_listxml_gives_both_cpus_their_clocks_which_the_live_channel_has_not() -> None:
    """The clock comes from `-listxml` only: the live channel answers nil for it."""
    found = machine.parse_listxml(LISTXML_M68K_DUAL, "m68k-dual")[0]
    assert [(c["tag"], c["name"], c["clock_hz"]) for c in found["cpus"]] == [
        (":maincpu", "Motorola MC68000", 16_000_000),
        (":subcpu", "Motorola MC68000", 16_000_000),
    ]


def test_a_single_cpu_board_reads_back_as_one_cpu_at_its_own_clock() -> None:
    """Counter-case: no hard-wired two cpus or one clock."""
    found = machine.parse_listxml(LISTXML_V30, "v30-board")[0]
    assert [(c["tag"], c["name"], c["clock_hz"]) for c in found["cpus"]] == [
        (":maincpu", "NEC V30", 8_000_000),
    ]
    assert found["screens"] == [{"tag": ":screen", "width": 320, "height": 204,
                                 "refresh_hz": 50.080128, "rotation": 0, "type": "raster"}]


def test_a_rom_nobody_has_dumped_carries_no_crc_and_no_sha1() -> None:
    """A zero crc would fabricate the one thing this section carries."""
    roms = machine.parse_listxml(LISTXML_M68K_DUAL, "m68k-dual")[0]["rom_files"]
    # `dump_status` is on every row (the DTD defaults it to `good`); the word marks an undumped ROM.
    dumped = [r for r in roms if r["dump_status"] == "good"]
    nodump = [r for r in roms if r["dump_status"] == "nodump"]
    assert nodump and dumped
    assert all("crc" not in r and "sha1" not in r for r in nodump)
    assert all(len(r["crc"]) == 8 and len(r["sha1"]) == 40 for r in dumped)


def test_a_roms_size_and_its_offset_are_numbers() -> None:
    """The DTD leaves both CDATA; graphics ROMs would overlap under the wrong reading."""
    roms = machine.parse_listxml(LISTXML_M68K_DUAL, "m68k-dual")[0]["rom_files"]
    gfx = sorted((r for r in roms if r.get("region") == ":gfx1"), key=lambda r: r["offset"])
    assert len(gfx) > 2
    for earlier, later in zip(gfx, gfx[1:], strict=False):
        assert later["offset"] >= earlier["offset"] + earlier["size"], (
            f"{earlier['name']} would overlap {later['name']}")
    plds = [r for r in roms if r.get("region") == ":plds"]
    live_size = {r["tag"]: r["size"] for r in machine.parse(M68K_DUAL)["regions"]}[":plds"]
    assert any(r["size"] == live_size for r in plds), "the two sources measure the same bytes"


def test_a_tag_is_spelled_the_live_channels_way_by_both_sources() -> None:
    """`-listxml` tags are relative and the live channel's absolute: one device, not two."""
    found = machine.parse_listxml(LISTXML_M68K_DUAL, "m68k-dual")[0]
    assert all(c["tag"].startswith(":") for c in found["cpus"])
    assert all(s["tag"].startswith(":") for s in found["screens"])
    assert all(r["region"].startswith(":") for r in found["rom_files"] if "region" in r)
    live_tags = {c["tag"] for c in machine.parse(M68K_DUAL)["cpus"]}
    assert {c["tag"] for c in found["cpus"]} == live_tags, "the two halves join on the tag"


def test_a_screen_that_is_mounted_turned_reports_the_rotation_it_was_given() -> None:
    """Both captures are horizontal; a turned screen's `rotate` must reach the reply."""
    turned = LISTXML_M68K_DUAL.replace(b'rotate="0"', b'rotate="270"', 1)
    assert turned != LISTXML_M68K_DUAL, "the substitution matched nothing, so nothing was tested"
    assert machine.parse_listxml(turned, "m68k-dual")[0]["screens"][0]["rotation"] == 270
    assert machine.parse_listxml(LISTXML_M68K_DUAL, "m68k-dual")[0]["screens"][0]["rotation"] == 0


def test_a_document_that_does_not_carry_the_machine_asked_about_is_refused() -> None:
    """`-listxml` also lists device machines; a whole-document walk would take their hardware."""
    with pytest.raises(LookupError, match="carries no <machine name='v30'>"):
        machine.parse_listxml(LISTXML_M68K_DUAL, "v30")[0]
    with pytest.raises(LookupError, match="carries no <machine name='m68k-dual'>"):
        machine.parse_listxml(LISTXML_V30, "m68k-dual")[0]


def test_hardware_belonging_to_a_device_machine_never_reaches_the_set() -> None:
    """A chip and rom added inside a device machine must be left out."""
    doctored = (FIXTURES / "listxml-device-with-hardware.xml").read_bytes()
    assert b'name="Imaginary DSP"' in doctored, "the fixture lost the thing it exists for"
    found, dropped = machine.parse_listxml(doctored, "m68k-dual")
    assert dropped == ""
    assert [c["name"] for c in found["cpus"]] == ["Motorola MC68000", "Motorola MC68000"]
    assert all(c["name"] != "Imaginary DSP" for c in found["cpus"])
    assert all(r["name"] != "never.dumped" for r in found["rom_files"])
    clean, _ = machine.parse_listxml(LISTXML_M68K_DUAL, "m68k-dual")
    assert len(found["cpus"]) == len(clean["cpus"])
    assert len(found["rom_files"]) == len(clean["rom_files"])


def test_a_chip_or_a_display_mame_did_not_name_is_dropped_and_the_note_says_so() -> None:
    """A tag is optional in the DTD: an absent one is a dropped row, said aloud."""
    untagged = LISTXML_M68K_DUAL.replace(
        b'<chip type="cpu" tag="maincpu" name="Motorola MC68000" clock="16000000"/>',
        b'<chip type="cpu" name="Motorola MC68000" clock="16000000"/>', 1)
    assert untagged != LISTXML_M68K_DUAL, "the substitution matched nothing"
    found, dropped = machine.parse_listxml(untagged, "m68k-dual")
    assert [c["tag"] for c in found["cpus"]] == [":subcpu"]
    assert all(c["tag"] != ":" for c in found["cpus"]), "the bare colon is not a device"
    assert "1 row of `-listxml` (cpu) carries no `tag` and was dropped" in dropped


def test_a_value_mame_spelled_some_other_way_does_not_take_the_start_down() -> None:
    """A raise in attribute conversion is an absent section with a reason, not a failed start."""
    odd = LISTXML_M68K_DUAL.replace(b'clock="16000000"', b'clock="XTAL_16MHz"', 1)
    assert odd != LISTXML_M68K_DUAL, "the substitution matched nothing"
    with pytest.raises(LookupError, match="not the number this reads"):
        machine.parse_listxml(odd, "m68k-dual")


def test_the_device_machines_beside_the_set_are_not_read_as_part_of_it() -> None:
    """Each document holds several machines and only the set's own counts are asserted."""
    for text, system, n_cpus, roms in ((LISTXML_M68K_DUAL, "m68k-dual", 2, 22),
                                       (LISTXML_V30, "v30-board", 1, 3)):
        assert text.count(b"<machine name=") > 1, "a one-machine document proves no scoping"
        found = machine.parse_listxml(text, system)[0]
        assert len(found["cpus"]) == n_cpus and len(found["rom_files"]) == roms
        assert len(found["screens"]) == 1


def _stub_mame(tmp_path: Path, name: str, body: str) -> str:
    """A stand-in for the MAME binary with its real exit code and stream, its `body` Python."""
    return str(host_program.write(tmp_path / name, f"import sys\n{body}\n"))


def _listxml(binary: str, system: str, seconds: float = 20.0
             ) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """Both halves of the query (put, then collect) over a real process."""
    return machine.listxml(machine.ask_listxml(binary, system), binary, system, seconds)


def test_a_system_this_build_does_not_carry_refuses_the_start_in_mames_own_words(
    tmp_path: Path,
) -> None:
    """The real binary exits 5 with the sentence on stderr: the caller's mistake, so a refusal."""
    binary = _stub_mame(tmp_path, "mame", "sys.stderr.write("
                        "f\"No matching machines found for '{sys.argv[1]}'\\n\")\nsys.exit(5)")
    with pytest.raises(st.Invalid) as refused:
        _listxml(binary, "nosuchsystem")
    assert refused.value.code == "bad_argument"
    assert "does not carry 'nosuchsystem'" in str(refused.value)
    assert "No matching machines found for 'nosuchsystem'" in str(refused.value)
    assert refused.value.fields["exit_code"] == machine.ABSENT_SYSTEM_RC


def test_any_other_listxml_failure_leaves_start_working_and_quotes_what_it_said(
    tmp_path: Path,
) -> None:
    """A failed inventory never blocks a debug session, and names its exit code and words."""
    binary = _stub_mame(tmp_path, "mame",
                        "sys.stderr.write('Fatal error: out of memory\\n')\nsys.exit(3)")
    found, note = _listxml(binary, "m68k-dual")
    assert found == {"cpus": [], "screens": [], "rom_files": []}
    assert "exit code 3" in note and "out of memory" in note and "rom_files" in note


def test_a_binary_that_cannot_be_run_is_a_note_and_not_a_crash(tmp_path: Path) -> None:
    found, note = _listxml(str(tmp_path / "not-here"), "m68k-dual")
    assert found["cpus"] == [] and "could not be run" in note


def test_listxml_that_answers_something_other_than_its_own_xml_is_a_note(
    tmp_path: Path,
) -> None:
    binary = _stub_mame(tmp_path, "mame", "print('not xml at all')")
    found, note = _listxml(binary, "m68k-dual")
    assert found["cpus"] == [] and "did not answer XML" in note


def test_a_successful_listxml_comes_back_parsed(tmp_path: Path) -> None:
    """Positive control: the same wrapper over the captured document answers the board."""
    xml = FIXTURES / "listxml-m68k-dual.xml"
    binary = _stub_mame(tmp_path, "mame",
                        f"sys.stdout.buffer.write(open({str(xml)!r}, 'rb').read())")
    found, note = _listxml(binary, "m68k-dual")
    assert note == "" and len(found["cpus"]) == 2 and len(found["rom_files"]) == 22


def test_the_two_halves_join_into_one_cpu_with_both_sources_fields(tmp_path: Path) -> None:
    """One row per cpu with the live spaces and the `-listxml` clock."""
    (tmp_path / machine.DUMP_NAME).write_text(M68K_DUAL, encoding="utf-8")
    cached = machine.cache(tmp_path,
                           machine.parse_listxml(LISTXML_M68K_DUAL, "m68k-dual"))
    by_tag = {c["tag"]: c for c in cached["cpus"]}
    assert set(by_tag) == {":maincpu", ":subcpu"}
    for cpu in by_tag.values():
        assert cpu["clock_hz"] == 16_000_000, "from -listxml"
        assert cpu["spaces"] == ["cpu_space", "program"], "from the live machine"
    screen = cached["screens"][0]
    assert screen["rotation"] == 0 and screen["width"] == 336, "both halves of the screen"
    assert len(cached["rom_files"]) == 22 and len(cached["address_map"]) == 32
    assert "disagree" not in cached["note"]


def test_the_two_sources_disagreeing_is_reported_and_never_resolved() -> None:
    """A disagreement between the sources is said, not decided."""
    rows, clashes = machine.merge(
        [{"tag": ":maincpu", "name": "Motorola MC68000", "spaces": ["program"]}],
        [{"tag": ":maincpu", "name": "Motorola MC68010", "clock_hz": 16_000_000}], "cpu")
    assert len(rows) == 1 and rows[0]["clock_hz"] == 16_000_000
    assert len(clashes) == 1 and ":maincpu" in clashes[0]
    # Attribution order: a swapped message would still hold both substrings.
    assert "'Motorola MC68000' from live" in clashes[0], clashes[0]
    assert "'Motorola MC68010' from the other" in clashes[0], clashes[0]
    assert rows[0]["name"] == "Motorola MC68000"


def test_a_device_only_one_source_has_keeps_only_that_sources_fields() -> None:
    rows, clashes = machine.merge([{"tag": ":maincpu", "spaces": ["program"]}],
                                  [{"tag": ":audiocpu", "clock_hz": 4_000_000}], "cpu")
    assert clashes == []
    by_tag = {r["tag"]: r for r in rows}
    assert "clock_hz" not in by_tag[":maincpu"] and "spaces" not in by_tag[":audiocpu"]


def _cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dump: str = "",
            xml: bytes = b"", system: str = "m68k-dual") -> None:
    """Put a machine on the STATE as `start` does; `machine_map` needs no session."""
    (tmp_path / machine.DUMP_NAME).write_text(dump or M68K_DUAL, encoding="utf-8")
    static = machine.parse_listxml(xml or LISTXML_M68K_DUAL, system)
    monkeypatch.setattr(STATE, "machine_map", machine.cache(tmp_path, static))


#: Every section, for the cases that judge the whole map.
EVERY = list(machine.MAP_SECTIONS)


def test_machine_map_with_no_machine_is_refused_and_never_answered_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(STATE, "machine_map", {})
    with pytest.raises(st.Invalid) as refused:
        machine.machine_map()
    assert refused.value.code == "no_session"


def test_the_reply_carries_every_section_its_sources_and_the_full_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _cached(monkeypatch, tmp_path)
    reply = machine.machine_map(sections=list(machine.MAP_SECTIONS))
    assert set(machine.SECTIONS) <= set(reply)
    assert "omitted" not in reply and "how" not in reply
    assert reply["counts"] == {"cpus": 2, "spaces": 4, "address_map": 32, "regions": 4,
                               "shares": 2, "screens": 1, "rom_files": 22,
                               "symbol_coverage": 0}
    assert all(reply["counts"][name] == len(reply[name]) for name in reply["counts"])
    assert reply["truncated"] is False
    # The denominator is the reply's own `counts`, not `SECTIONS`, which omits `symbol_coverage`.
    assert set(reply["sources"]) == set(reply["counts"])
    assert menvelope.session_block()["altered"] is False
    assert reply["cpu"]["available"] is False, "no cpu was asked for, so none is named"


def test_the_default_map_leaves_the_rom_files_out_and_says_how_to_ask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _cached(monkeypatch, tmp_path)
    reply = machine.machine_map()
    assert "rom_files" not in reply and "rom_files" not in reply["counts"]
    assert "rom_files" not in reply["sources"]
    assert reply["omitted"] == ["rom_files"] and "sections=" in reply["how"]
    line = summaries.machine_map({}, reply)
    assert line.endswith(", left out: rom_files (see `omitted`)"), line
    assert reply["counts"]["address_map"] == len(reply["address_map"]) == 32


def test_sections_answers_only_the_ones_named_in_the_reply_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _cached(monkeypatch, tmp_path)
    reply = machine.machine_map(sections=["rom_files", "cpus"])
    assert [k for k in reply if k in machine.MAP_SECTIONS] == ["cpus", "rom_files"]
    assert set(reply["counts"]) == set(reply["sources"]) == {"cpus", "rom_files"}
    assert reply["cpus"][0]["cpu"] == ":maincpu"
    assert "spaces" in reply["omitted"] and "symbol_coverage" in reply["omitted"]
    assert "classes" not in str(reply["note"])


@pytest.mark.parametrize("sections, said", [([], "a list naming at least one section"),
                                            (["cpus", "roms"], "'roms', none of them")])
def test_a_bad_section_list_is_refused_before_the_machine_is_asked(
    monkeypatch: pytest.MonkeyPatch, sections: list[str], said: str
) -> None:
    monkeypatch.setattr(STATE, "machine_map", {})
    with pytest.raises(st.Invalid) as refused:
        machine.machine_map(sections=sections)
    assert refused.value.code == "bad_argument" and said in str(refused.value)


def test_two_calls_answer_the_same_bytes_and_spawn_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The tool declares `idempotentHint`: a second call must not re-shell `-listxml`."""
    _cached(monkeypatch, tmp_path)
    spawns: list[object] = []
    real_popen = subprocess.Popen

    def counted(*a: object, **k: object) -> object:
        spawns.append(a or k)
        return real_popen(*a, **k)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "Popen", counted)
    first = json.dumps(machine.machine_map(), sort_keys=True)
    second = json.dumps(machine.machine_map(), sort_keys=True)
    assert first == second, "two calls, two different answers"
    assert spawns == [], f"machine_map spawned {len(spawns)} process(es)"


def test_a_cpu_narrows_only_what_belongs_to_one_and_answers_the_full_tag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Blocks, screens and ROM files are the board's: narrowing to a cpu must not hide them."""
    _cached(monkeypatch, tmp_path)
    whole = machine.machine_map(sections=EVERY)
    for spelling in (":subcpu", "subcpu"):
        one = machine.machine_map(cpu=spelling, sections=EVERY)
        assert one["cpu"] == ":subcpu", spelling
        assert [c["cpu"] for c in one["cpus"]] == [":subcpu"]
        assert "tag" not in one["cpus"][0]
        assert {e["cpu"] for e in one["address_map"]} == {":subcpu"}
        # `spaces` is in PER_CPU: dropping it left both cpus' spaces in a one-cpu reply.
        assert {sp["cpu"] for sp in one["spaces"]} == {":subcpu"}
        assert len(one["spaces"]) < len(whole["spaces"])
        assert one["counts"]["address_map"] == 12 < whole["counts"]["address_map"]
        assert one["rom_files"] == whole["rom_files"], "the ROMs are the board's"
        assert one["regions"] == whole["regions"] and one["screens"] == whole["screens"]


def test_a_cpu_this_machine_lacks_is_refused_naming_the_ones_it_has(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _cached(monkeypatch, tmp_path)
    with pytest.raises(st.Invalid) as refused:
        machine.machine_map(cpu="audiocpu")
    assert refused.value.code == "unknown_ref"
    assert refused.value.fields["cpu_tags"] == [":maincpu", ":subcpu"]


def test_a_section_past_the_ceiling_is_cut_and_says_so_with_the_full_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A cut keeps the full number in `counts` and names the section in `truncated`."""
    _cached(monkeypatch, tmp_path)
    over = read.LOG_LIMIT_MAX + 7
    one = STATE.machine_map["address_map"][0]
    STATE.machine_map["address_map"] = [dict(one, index=i) for i in range(over)]
    reply = machine.machine_map(sections=EVERY)
    assert len(reply["address_map"]) == read.LOG_LIMIT_MAX
    assert reply["counts"]["address_map"] == over, "the count is of the machine, not the reply"
    assert reply["truncated"] is True
    assert [name for name in machine.SECTIONS
            if len(reply[name]) < reply["counts"][name]] == ["address_map"]


def test_symbol_coverage_is_empty_and_says_why_when_the_table_has_no_classes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Absent symbol coverage is informative: the list is present and empty, the note says why."""
    _cached(monkeypatch, tmp_path)
    use_table(monkeypatch, class_span={})
    reply = machine.machine_map()
    assert reply["symbol_coverage"] == []
    assert machine.NO_CLASSES_NOTE in reply["note"]


def test_a_board_with_no_frame_counter_says_so_in_frame_symbol_and_keeps_its_own_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One `note` carries both the map's caveats and the board's missing counter."""
    _cached(monkeypatch, tmp_path)
    monkeypatch.setattr(read, "frame_symbol", lambda: None)
    reply = machine.machine_map()
    assert reply["frame_symbol"]["available"] is False
    assert machine.BANKING_NOTE in reply["note"] and read.FRAMELESS_NOTE not in reply["note"]
    assert reply["frame_symbol"]["why"] == read.FRAMELESS_NOTE, reply


def test_symbol_coverage_is_finds_own_span_and_nulls_a_base_it_cannot_disambiguate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two spans for one class, an absent `base`, or a wrong cpu row goes red."""
    _cached(monkeypatch, tmp_path)
    use_table(monkeypatch, class_span={"DATA": (0x400, 0x4FF), "CODE": (0x1000, 0x1FFF)})
    use_table(monkeypatch, bases={"DATA": 0x400})
    use_table(monkeypatch, classes={"A": "DATA", "B": "DATA", "C": "CODE"},
              table={"A": 0x400, "B": 0x410, "C": 0x1000})
    rows = {row["class"]: row for row in machine.machine_map()["symbol_coverage"]}
    assert set(rows) == {"CODE", "DATA"}
    assert rows["DATA"]["base"] == "0x00000400" and rows["DATA"]["symbols"] == 2
    assert rows["CODE"]["base"]["available"] is False, "the bases do not disambiguate CODE"
    assert rows["DATA"]["span"] == {"from": "0x00000400", "length": 0x100, **read.CLASS_SPAN}
    assert all(row["cpu"]["available"] is False for row in rows.values())


def test_symbol_coverage_counts_a_class_by_its_rows_not_by_the_names_first_class(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A name in two classes counts in each, and one repeated within a class once per row."""
    _cached(monkeypatch, tmp_path)
    names = gdb_session.Names()
    for key, addr, klass in (("N", 0x400, "DATA"), ("N", 0x1000, "CODE"),
                             ("M", 0x410, "DATA"), ("M", 0x420, "DATA")):
        names.add(key, addr, klass)
    use_table(monkeypatch, table=names, classes={"N": "DATA", "M": "DATA"},
              class_span={"DATA": (0x400, 0x4FF), "CODE": (0x1000, 0x1FFF)})
    rows = {row["class"]: row for row in machine.machine_map()["symbol_coverage"]}
    assert (rows["DATA"]["symbols"], rows["CODE"]["symbols"]) == (3, 1)


def test_a_populated_symbol_section_names_the_channel_that_backs_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With a table loaded `NO_CLASSES_NOTE` is suppressed, so `sources` carries the provenance."""
    _cached(monkeypatch, tmp_path)
    use_table(monkeypatch, class_span={"CODE": (0x1000, 0x1FFF)})
    use_table(monkeypatch, classes={"C": "CODE"})
    reply = machine.machine_map()
    assert reply[machine.SYMBOL_SECTION], "this case is about the section with rows in it"
    assert machine.NO_CLASSES_NOTE not in reply["note"]
    assert reply["sources"][machine.SYMBOL_SECTION] == [machine.SYMBOL_SOURCE]
    # `symbols` is `start`'s own argument name; a rename of either goes red here.
    import inspect

    from scry_mame import server as srv
    assert machine.SYMBOL_SOURCE in inspect.signature(srv.start).parameters


def test_the_summary_says_what_the_board_is_and_never_just_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Under `perform(summaries=True)` the summary is all a step keeps."""
    from scry_mame import mcp as mame_mcp
    _cached(monkeypatch, tmp_path)
    reply = machine.machine_map(sections=EVERY)
    line = mame_mcp.BOUNDARY.line("machine_map", {}, reply)
    assert "2 cpus" in line and "32 address map entries" in line and "22 ROM files" in line
    assert "1 screen," in line, "one of a section is said in the singular"
    narrowed = machine.machine_map(cpu="subcpu", sections=EVERY)
    assert "of :subcpu" in mame_mcp.BOUNDARY.line("machine_map", {"cpu": "subcpu"}, narrowed)
    STATE.machine_map["address_map"] *= 20
    cut = machine.machine_map(sections=EVERY)
    assert "sections cut" in mame_mcp.BOUNDARY.line("machine_map", {}, cut)
    line = mame_mcp.BOUNDARY.line("machine_map", {}, cut)
    assert "640 address map entries" in line, "the FULL count"


def test_every_space_carries_its_own_mask_and_a_cpu_is_judged_by_its_own() -> None:
    """The last address per space, so `memdump` and `find` judge by the reading cpu's mask."""
    assert [r["address_mask"] for r in machine.parse(M68K_DUAL)["spaces"]] == ["0x00ffffff"] * 4
    assert SUB_NARROWED != M68K_DUAL, "the capture no longer carries the sub cpu's program line"
    STATE.machine_map = machine.parse(SUB_NARROWED)
    try:
        assert (cpus.program_mask(":maincpu"), cpus.program_mask(":subcpu")) == (0xFFFFFF, 0x3FFF)
        assert cpus.program_mask(":audiocpu") is None and cpus.program_mask(None) is None
    finally:
        STATE.machine_map = {}


def test_the_reply_carries_each_rows_mask_and_no_key_of_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Each `spaces` row carries its own `address_mask`; no mask key beside the sections."""
    _cached(monkeypatch, tmp_path, dump=SUB_NARROWED)
    whole = machine.machine_map()
    masks = {(r["cpu"], r["space"]): r["address_mask"] for r in whole["spaces"]}
    assert masks[(":subcpu", "program")] == "0x00003fff" and len(masks) == 4, masks
    assert whole["sources"]["spaces"] == ["live"], whole["sources"]
    sub = machine.machine_map(cpu="subcpu")["spaces"]
    assert [r["address_mask"] for r in sub] == ["0x00ffffff", "0x00003fff"], sub
    assert not {"program_mask", "address_mask"} & set(whole), sorted(whole)


def test_the_matrix_derives_its_edge_refs_from_the_reply_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The live matrix takes the edge from a `machine_map` reply, held here."""
    import ast
    import importlib.util

    live = Path(__file__).parent / "live"
    spec = importlib.util.spec_from_file_location("map_edges", live / "map_edges.py")
    assert spec is not None and spec.loader is not None
    edges = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(edges)

    _cached(monkeypatch, tmp_path)
    reply = machine.machine_map(cpu="maincpu")
    last, hole, space_end = edges.program_edges(reply, reply["cpu"])
    spans = [(int(e["start"], 16), int(e["end"], 16)) for e in reply["address_map"]
             if e["space"] == "program"]
    assert not any(lo <= hole <= hi for lo, hi in spans), f"{hole:#x} is mapped"
    assert any(hi == hole - 1 for _, hi in spans), f"{hole:#x} does not follow an entry"
    assert space_end == 0xFFFFFF and last == max(hi for _, hi in spans) == 0x7E0003
    whole = {"spaces": [], "address_map": [
        {"cpu": ":x", "space": "program", "start": "0x00000000", "end": "0x0000ffff"},
        {"cpu": ":x", "space": "program", "start": "0x00010000", "end": "0x0001ffff"}]}
    assert edges.program_edges(whole, ":x") == (0x1FFFF, None, None), "no hole, no mask"
    with pytest.raises(LookupError, match="truncated"):
        edges.program_edges({**whole, "truncated": True}, ":x")
    assert edges.program_edges({**whole, "truncated": False}, ":x") == (0x1FFFF, None, None)
    with pytest.raises(LookupError, match="no program entry"):
        edges.program_edges({"spaces": [], "address_map": []}, ":x")

    tree = ast.parse((live / "matrix_edges.py").read_text(encoding="utf-8"))
    block = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "block_b_edges")
    named = ({n.id for n in ast.walk(block) if isinstance(n, ast.Name)}
             | {n.attr for n in ast.walk(block) if isinstance(n, ast.Attribute)})
    assert "program_edges" in named, "the block no longer derives its edges where this looks"
    assert not named & {"STATE", "PROGRAM_MASK"}, named & {"STATE", "PROGRAM_MASK"}




def test_a_cut_off_listxml_is_refused_and_a_device_after_the_set_keeps_its_hardware() -> None:
    """A cut-off document is refused, and the set's scoping closes with its element."""
    with pytest.raises(LookupError, match="XML"):
        machine.parse_listxml(LISTXML_M68K_DUAL[:4000], "m68k-dual")
    ghost = (b'<machine name="zzz" isdevice="yes"><description>x</description>'
             b'<chip type="cpu" tag="ghost" name="G" clock="1"/>'
             b'<rom name="ghost.bin" size="16" region="ghost" offset="0"/></machine>')
    after = LISTXML_M68K_DUAL.replace(b"</mame>", ghost + b"</mame>")
    assert after != LISTXML_M68K_DUAL, "the substitution matched nothing"
    clean = machine.parse_listxml(LISTXML_M68K_DUAL, "m68k-dual")[0]
    found = machine.parse_listxml(after, "m68k-dual")[0]
    assert found == clean, "the device machine after the set leaked into it"
    assert all(rom["name"] for rom in found["rom_files"]) and found["rom_files"]


def test_listxml_bounds_the_collection_reads_a_bad_byte_and_refuses_the_measured_shape() -> None:
    """Collection waits the boot's `wait`, replaces non-UTF-8, refuses on exit code and sentence."""
    seen: list[float | None] = []

    class Proc:
        def __init__(self, rc: int, err: bytes) -> None:
            self.returncode, self.err = rc, err

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            seen.append(timeout)
            return b"", self.err

    sections, note = machine.listxml((Proc(3, b"fatal \xff error"), ""), "bin", "sys", 2.5)  # type: ignore[arg-type]
    assert seen == [2.5] and sections == machine._no_xml() and "fatal" in note and "\ufffd" in note
    sections, note = machine.listxml((Proc(5, b"some other complaint"), ""), "bin", "sys", 2.5)  # type: ignore[arg-type]
    assert sections == machine._no_xml() and "exit code 5" in note
    absent = machine.ABSENT_SYSTEM_TEXT.encode()
    sections, note = machine.listxml((Proc(3, absent), ""), "bin", "sys", 2.5)  # type: ignore[arg-type]
    assert sections == machine._no_xml() and "exit code 3" in note
    with pytest.raises(st.Invalid):
        machine.listxml((Proc(5, absent), ""), "bin", "sys", 2.5)  # type: ignore[arg-type]


def test_a_dump_with_a_bad_byte_is_read_as_a_failure_and_never_raises(tmp_path: Path) -> None:
    (tmp_path / machine.DUMP_NAME).write_bytes(b"\xff not the gather\n")
    sections, note = machine.live(tmp_path)
    assert sections == {name: [] for name in machine.LIVE_SECTIONS} and "could not be read" in note


def test_machine_map_hands_back_copies_that_cannot_rewrite_the_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Callers touching nested rows must not touch the cache: rows and sources are deep copies."""
    _cached(monkeypatch, tmp_path)
    reply = machine.machine_map()
    reply["cpus"][0]["spaces"].append("rewritten")
    reply["sources"]["cpus"].append("rewritten")
    again = machine.machine_map()
    assert "rewritten" not in again["cpus"][0]["spaces"], "a cpu row is a copy"
    assert again["cpus"][0]["cpu"] == ":maincpu" and "rewritten" not in again["sources"]["cpus"]


def test_the_inventory_carries_the_set_s_views_and_the_one_snapshots_take() -> None:
    """The layout's views in MAME's order and the resolved `-snapview`."""
    lines = M68K_DUAL.splitlines()
    end = lines.index(machine.END)
    dump = "\n".join([*lines[:end], "VIEW Screen 0 Standard (4:3)", "VIEW Shifter-R Overlay",
                      "SNAPVIEW Shifter-R Overlay", *lines[end:]])
    got = machine.parse(dump)
    assert got[machine.VIEWS] == ["Screen 0 Standard (4:3)", "Shifter-R Overlay"]
    assert got[machine.SNAPVIEW] == "Shifter-R Overlay"
    plain = machine.parse(M68K_DUAL)
    assert plain[machine.VIEWS] == [] and plain[machine.SNAPVIEW] == ""


def test_start_says_which_view_its_captures_take() -> None:
    """`native` if none asked, else the view MAME took, else unavailable with a reason."""
    from scry_mame.launch import view_shown, views_shown

    taken = {machine.VIEWS: ["Shifter-R Overlay"], machine.SNAPVIEW: "Shifter-R Overlay"}
    assert view_shown("", taken) == "native"
    assert view_shown("shifter-r", taken) == "Shifter-R Overlay"
    assert view_shown("Shifter", {})["available"] is False      # type: ignore[index]
    assert views_shown(taken) == ["Shifter-R Overlay"]
    assert "no video" in views_shown({})["why"]                 # type: ignore[call-overload]


def test_a_view_line_with_no_name_costs_nothing_but_itself() -> None:
    """A view named with nothing is skipped and the inventory stands."""
    lines = M68K_DUAL.splitlines()
    end = lines.index(machine.END)
    got = machine.parse("\n".join([*lines[:end], "VIEW ", "VIEW Shifter", *lines[end:]]))
    assert got[machine.VIEWS] == ["Shifter"] and got["cpus"], got[machine.VIEWS]
