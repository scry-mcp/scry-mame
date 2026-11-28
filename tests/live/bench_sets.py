"""What the bench reads around a session: its sets, the map a boot declares, a ROM's address,
and the device list `start` gathered."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from scry_mame import machine

#: The bytes `start` checks against a ROM file.
CHECKED = 16

SPACE = re.compile(r"^SPACE (?P<tag>\S+) width=(?P<width>\d+) mask=(?P<mask>[0-9a-f]+)$")
ENTRY = re.compile(r"^ENTRY (?P<tag>\S+) (?P<index>\d+) (?P<start>[0-9a-f]+) "
                   r"(?P<end>[0-9a-f]+) (?P<region>\S+) (?P<offset>\d+)$")
#: The gather's line for each device the machine instantiates.
DEVICE_LINE = re.compile(r"^DEVICE\t(?P<tag>[^\t]+)\t(?P<shortname>[^\t]*)\t(?P<name>.*)$")


@dataclass(frozen=True)
class Rom:
    name: str
    size: int
    crc: str
    region: str
    offset: int


@dataclass(frozen=True)
class Describe:
    system: str
    isdevice: bool
    roms: tuple[Rom, ...]
    device_refs: tuple[str, ...]


@dataclass(frozen=True)
class Space:
    tag: str
    width: int
    mask: int


@dataclass(frozen=True)
class Entry:
    tag: str
    index: int
    start: int
    end: int
    region: str
    region_offset: int


def _number(text: str) -> int:
    return int(text, 16)


def read_map(text: str) -> tuple[list[Space], list[Entry]]:
    """The map `bench_map.lua` wrote: its spaces and its entries, in the order it wrote them."""
    spaces: list[Space] = []
    entries: list[Entry] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("ERROR "):
            raise LookupError("the map harness failed: " + line[len("ERROR "):])
        if (found := SPACE.match(line)) is not None:
            spaces.append(Space(found["tag"], int(found["width"]), _number(found["mask"])))
        elif (found := ENTRY.match(line)) is not None:
            entries.append(Entry(found["tag"], int(found["index"]), _number(found["start"]),
                                 _number(found["end"]), found["region"], int(found["offset"])))
    if not entries:
        raise LookupError("the map harness wrote no entry: " + repr(text[:400]))
    return spaces, entries


def carriers(described: dict[str, Describe], sets: Iterable[str]) -> dict[str, list[str]]:
    """The bench machines each device set boots on: those whose XML names it."""
    out: dict[str, list[str]] = {}
    for name in sets:
        hosts = sorted(system for system, said in described.items()
                       if not said.isdevice and name in said.device_refs)
        if hosts:
            out[name] = hosts
    return out


def rom_files(romdir: Path) -> dict[str, tuple[Path, str]]:
    """Every ROM member of every set, by CRC, so a parent set's own ROM is found too."""
    found: dict[str, tuple[Path, str]] = {}
    for archive in sorted(romdir.glob("*.zip")):
        with zipfile.ZipFile(archive) as held:
            for member in held.infolist():
                found.setdefault(f"{member.CRC:08x}", (archive, member.filename))
    return found


def reference_candidates(entries: list[Entry], roms: tuple[Rom, ...],
                         files: dict[str, tuple[Path, str]]) -> list[tuple[Rom, int, int]]:
    """Where a ROM's bytes sit: the file, the address read, and the base `start` takes.

    An entry places a ROM loaded at region offset `o` at `start + (o - region_offset)`, its base;
    the address read is where the two overlap. The main cpu's entries come first.
    """
    out: list[tuple[Rom, int, int]] = []
    first = sorted(entries, key=lambda e: (not e.tag.lstrip(":").endswith("maincpu"), e.tag,
                                           e.index))
    for entry in first:
        if entry.region == "-":
            continue
        mapped = entry.end - entry.start + 1
        for rom in roms:
            if rom.region != entry.region.lstrip(":") or rom.crc not in files:
                continue
            lo = max(rom.offset, entry.region_offset)
            hi = min(rom.offset + rom.size, entry.region_offset + mapped)
            if hi - lo < CHECKED:
                continue
            base = entry.start + (rom.offset - entry.region_offset)
            if base < 0:
                continue
            found = (rom, entry.start + (lo - entry.region_offset), base)
            if found not in out:
                out.append(found)
    return out


def extract(rom: Rom, files: dict[str, tuple[Path, str]], dest: Path) -> None:
    archive, member = files[rom.crc]
    with zipfile.ZipFile(archive) as held:
        dest.write_bytes(held.read(member))


def read_devices(dump: Path) -> list[tuple[str, str, str]]:
    """The devices the boot gather wrote, refused unless its own begin and end are there."""
    if not dump.is_file():
        raise LookupError(f"the machine's device list is not at {dump}: `status` named no scratch "
                          "directory the session wrote, so nothing here says what it reports")
    lines = [line for line in dump.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines or lines[0] != machine.NAMES_BEGIN or lines[-1] != machine.NAMES_END:
        raise LookupError(f"the device list at {dump} is not whole: it does not open and close "
                          f"with the gather's own lines ({lines[0] if lines else 'empty'})")
    out: list[tuple[str, str, str]] = []
    for line in lines[1:-1]:
        found = DEVICE_LINE.match(line)
        if found is not None:
            out.append((found["tag"], found["shortname"], found["name"]))
    return out


def under(tag: str, name: str) -> bool:
    """Whether `tag` is `name` or sits under it: `:cuda`, `:cuda:cudamcu`."""
    return tag.strip(":").split(":")[0] == name or f":{name}:" in f"{tag}:"
