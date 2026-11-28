"""The bench's own reading, without an emulator: the map, the ROM's address, the device list and
the set a device belongs to. What needs one is the run itself."""

from __future__ import annotations

import zipfile
import zlib
from pathlib import Path

import pytest
from bench_sets import (
    Describe,
    Entry,
    Rom,
    Space,
    carriers,
    extract,
    read_devices,
    read_map,
    reference_candidates,
    rom_files,
    under,
)

from scry_mame import machine

ROMS = (Rom(name="a.bin", size=4096, crc="aaaaaaaa", region="maincpu", offset=0xA000),
        Rom(name="b.bin", size=4096, crc="bbbbbbbb", region="gfx1", offset=0),
        Rom(name="c.bin", size=4096, crc="cccccccc", region="maincpu", offset=0x2000))
FILES = {"aaaaaaaa": (Path("/z/a.zip"), "a.bin"), "bbbbbbbb": (Path("/z/a.zip"), "b.bin"),
         "cccccccc": (Path("/z/a.zip"), "c.bin")}


def test_the_map_reads_its_spaces_and_entries() -> None:
    text = ("SPACE :maincpu width=8 mask=ffff\n"
            "ENTRY :maincpu 14 a000 ffff :maincpu 40960\n")
    spaces, entries = read_map(text)
    assert spaces == [Space(":maincpu", 8, 0xFFFF)]
    assert entries == [Entry(":maincpu", 14, 0xA000, 0xFFFF, ":maincpu", 0xA000)]


def test_a_map_the_gather_failed_on_is_not_read_as_an_empty_one() -> None:
    with pytest.raises(LookupError, match="harness failed"):
        read_map("ERROR machine.machine is nil\n")
    with pytest.raises(LookupError, match="no entry"):
        read_map("SPACE :maincpu width=8 mask=ffff\n")


def test_a_rom_is_placed_where_the_map_says_its_region_is() -> None:
    """An entry places a ROM by its region offset, and its own offset moves the address."""
    entries = [Entry(":maincpu", 1, 0xA000, 0xFFFF, ":maincpu", 0xA000),
               Entry(":maincpu", 2, 0x2000, 0x2FFF, ":maincpu", 0x2000)]
    found = reference_candidates(entries, ROMS, FILES)
    assert found == [(ROMS[0], 0xA000, 0xA000), (ROMS[2], 0x2000, 0x2000)]


def test_a_rom_below_the_entry_is_placed_where_it_enters_it() -> None:
    """A region's bottom, overlaid by RAM, is not mapped: the reference starts inside the file."""
    rom = Rom(name="d.bin", size=0x8000, crc="dddddddd", region="maincpu", offset=0)
    files = {**FILES, "dddddddd": (Path("/z/a.zip"), "d.bin")}
    found = reference_candidates([Entry(":maincpu", 1, 0x3000, 0x7FFF, "maincpu", 0x3000)],
                                 (rom,), files)
    assert found == [(rom, 0x3000, 0)]


def test_the_main_cpu_is_tried_before_the_others() -> None:
    """The main cpu's address is offered first, because that is the cpu `start` checks."""
    other = Entry(":soundcpu", 1, 0x1000, 0x3FFF, "maincpu", 0x1000)
    main = Entry(":maincpu", 1, 0x1000, 0x3FFF, "maincpu", 0)
    assert reference_candidates([other, main], (ROMS[2],), FILES) == [
        (ROMS[2], 0x3000, 0x3000), (ROMS[2], 0x2000, 0x2000)]


def test_a_rom_no_entry_places_is_no_candidate() -> None:
    """A ROM in no mapped region, or below an entry's window, is no candidate."""
    entries = [Entry(":maincpu", 1, 0x2000, 0x2FFF, ":maincpu", 0x2000)]
    found = reference_candidates(entries, ROMS, FILES)
    assert [rom.name for rom, _, _ in found] == ["c.bin"]
    # Its first byte lands at 0 + (0xA000 - 0x4000), inside the entry, so it IS a candidate.
    assert reference_candidates([Entry(":maincpu", 1, 0, 0xFFFF, "maincpu", 0x4000)],
                                ROMS, FILES) == [(ROMS[0], 0x6000, 0x6000)]
    placed = reference_candidates([Entry(":maincpu", 1, 0x2000, 0x2007, "maincpu", 0x2000)],
                                  ROMS, FILES)
    assert placed == []


def test_a_device_set_is_found_under_the_host_that_names_it() -> None:
    described = {
        "pmac6100": Describe("pmac6100", False, (), ("cuda", "scsi")),
        "cuda": Describe("cuda", True, (), ()),
        "tekken": Describe("tekken", False, (), ("namcoc76",)),
        "namcoc76": Describe("namcoc76", True, (), ("m37710",)),
    }
    found = carriers(described, ("cuda", "namcoc76", "3c505"))
    assert found == {"cuda": ["pmac6100"], "namcoc76": ["tekken"]}


def test_a_rom_is_found_by_its_crc_and_copied_out(tmp_path: Path) -> None:
    """A ROM is found by its CRC, never by the file's name."""
    archive = tmp_path / "set.zip"
    body = b"\x01\x02\x03\x04"
    with zipfile.ZipFile(archive, "w") as held:
        held.writestr("r.bin", body)
    files = rom_files(tmp_path)
    crc = f"{zlib.crc32(body):08x}"
    rom = Rom(name="r.bin", size=4, crc=crc, region="maincpu", offset=0)
    assert files[rom.crc][1] == "r.bin"
    dest = tmp_path / "out.bin"
    extract(rom, files, dest)
    assert dest.read_bytes() == body


def test_a_device_list_is_read_only_whole(tmp_path: Path) -> None:
    """A cut or failed dump is refused, not read as a machine reporting no device."""
    dump = tmp_path / "names.txt"
    dump.write_text(f"{machine.NAMES_BEGIN}\nDEVICE\t:maincpu\tm6809\tMC6809\n"
                    f"{machine.NAMES_END}\n", encoding="utf-8")
    assert read_devices(dump) == [(":maincpu", "m6809", "MC6809")]
    dump.write_text(f"{machine.NAMES_BEGIN}\nDEVICE\t:maincpu\tm6809\tMC6809\n",
                    encoding="utf-8")
    with pytest.raises(LookupError, match="not whole"):
        read_devices(dump)
    dump.write_text(f"{machine.NAMES_FAILED} machine.machine is nil\n", encoding="utf-8")
    with pytest.raises(LookupError, match="not whole"):
        read_devices(dump)
    with pytest.raises(LookupError, match="no scratch"):
        read_devices(tmp_path / "absent.txt")


def test_a_device_tag_is_matched_under_the_set_it_belongs_to() -> None:
    assert under(":cuda", "cuda")
    assert under(":cuda:cudamcu", "cuda")
    assert under(":isa3:3c505:net", "3c505")
    assert not under(":cudamcu", "cuda")
    assert not under(":c76", "cuda")
    assert not under(":maincpu", "cuda")
