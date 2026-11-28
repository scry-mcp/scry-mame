"""Every machine of the bench and every device each one reports, asked of the knowledge base.

A set MAME answers `isdevice="yes"` for is a device, not a machine: it boots on the machine that
carries it and is counted apart. Each machine is started through this server's own tools, its map
read, and `knowledge_find` asked of every device it reports; the replies are recorded where
`tests/live/name_check.py` reads them. `start` needs a reference ROM, so `bench_map.lua` boot read
the map first.

    MAME_BINARY=... MAME_TEST_ROMS=... MAME_LIVE_BENCH=... \
        uv run python tests/live/bench_devices.py [--out DIR]

Exit 0 every machine ran, 1 a machine did not run, 3 INVALID (no bench, no reply).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scry_core import live_bench  # noqa: E402
from scry_core.verdict import Invalid  # noqa: E402

from scry_mame import naming  # noqa: E402
from scry_mame import server as s  # noqa: E402

from bench_sets import (  # noqa: E402  # isort: skip -- beside the harness
    Describe,
    Entry,
    Rom,
    carriers,
    extract,
    read_devices,
    read_map,
    reference_candidates,
    rom_files,
    under,
)

HERE = Path(__file__).resolve().parent
MAP_LUA = HERE / "bench_map.lua"
#: The bytes a placeholder image holds: all zero, which `start` refuses on a machine whose first
#: address is ROM and accepts on one whose is RAM. Either way the map is written at boot.
PLACEHOLDER = 64
#: How many (ROM file, address) pairs one machine is tried with; the first is the first cpu's.
ATTEMPTS = 6
#: The tool's own ceiling on a list: a scope with more vectors than this is asked in part.
LIST_LIMIT = 50
#: The 6809 family's `swi`, the one instruction of the bench whose line names a base entry: a
#: base of rows keys a vector by the slot's address on this cpu, and `swi` states that slot.
SWI_CPUS = frozenset({"m6809", "mc6809", "mc6809e"})
SWI_OPCODE = "3f"
#: The window a `find` searches, and the bytes a disassembly of one hit reads.
FIND_LENGTH, FIND_BYTES = 0x10000, 0x10


def describe(binary: str, system: str) -> Describe:
    """What MAME's own `-listxml` says of `system`: a machine or a device, its ROM files."""
    done = subprocess.run([binary, system, "-listxml"], capture_output=True, timeout=120,
                          check=False)
    if done.returncode != 0:
        raise LookupError(f"`{binary} {system} -listxml` exited {done.returncode}: "
                          + done.stderr.decode("utf-8", "replace").strip()[:200])
    machine = ET.fromstring(done.stdout).find("machine")
    if machine is None:
        raise LookupError(f"`{binary} {system} -listxml` answered no machine")
    roms = tuple(Rom(name=rom.get("name", ""), size=int(rom.get("size", "0")),
                     crc=rom.get("crc", ""), region=rom.get("region", ""),
                     offset=int(rom.get("offset", "0"), 16))
                 for rom in machine.findall("rom"))
    refs = tuple(ref.get("name", "") for ref in machine.findall("device_ref"))
    return Describe(system=system, isdevice=machine.get("isdevice") == "yes", roms=roms,
                    device_refs=refs)


@dataclass(frozen=True)
class Device:
    """One device a machine reports, and whether the base answered for it."""

    tag: str
    shortname: str
    name: str
    answered: bool

    def __str__(self) -> str:
        return f"{self.name or self.shortname} ({self.shortname}) at {self.tag}"


@dataclass
class MachineRun:
    system: str
    rc: int = 0
    devices: list[Device] = field(default_factory=list)
    why: str = ""

    @property
    def answered(self) -> int:
        return sum(1 for device in self.devices if device.answered)

    @property
    def gaps(self) -> list[Device]:
        return [device for device in self.devices if not device.answered]


class Bench:
    """One session at a time, its replies written where `name_check.py` reads them."""

    def __init__(self, binary: str, romdir: Path, out: Path, ini: Path, scratch: Path) -> None:
        self.binary = binary
        self.romdir = romdir
        self.out = out
        self.ini = ini
        self.scratch = scratch
        self.replies: list[dict[str, Any]] = []
        self.files = rom_files(romdir)

    def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        """One call of this server's own tool, recorded as the reply the run's checks read."""
        reply: dict[str, Any] = getattr(s, tool)(**arguments)
        self.replies.append(reply)
        return reply

    def boot_arguments(self, system: str) -> dict[str, Any]:
        return {"system": system, "rompath": str(self.romdir), "binary": self.binary,
                "boot_seconds": 60.0, "presence": False, "inipath": str(self.ini)}

    def learn(self, system: str) -> tuple[list[Entry], dict[str, Any]]:
        """Boot once on a placeholder image to read the map the machine declares."""
        dump = self.scratch / f"map-{system}.txt"
        harness = self.scratch / f"map-{system}.lua"
        harness.write_text(MAP_LUA.read_text(encoding="utf-8").replace(
            "__SCRY_dump__", json.dumps(str(dump))), encoding="utf-8")
        placeholder = self.scratch / "placeholder.bin"
        placeholder.write_bytes(bytes(PLACEHOLDER))
        reply = self.call("start", **self.boot_arguments(system), reference_rom=str(placeholder),
                          reference_addr="0x0", boot_lua=str(harness))
        if reply.get("session", {}).get("alive"):
            self.call("close")
        if not dump.is_file():
            raise LookupError("the map harness wrote no file: "
                              + str(reply.get("message") or reply.get("summary")))
        _spaces, entries = read_map(dump.read_text(encoding="utf-8"))
        return entries, reply

    def start(self, system: str, described: Describe) -> tuple[dict[str, Any], str]:
        """Boot on a reference taken from the machine's own map: the reply, and how it came."""
        entries, learned = self.learn(system)
        candidates = reference_candidates(entries, described.roms, self.files)
        if not candidates:
            raise LookupError(f"no ROM of {system} is mapped into a cpu's program space")
        last = ""
        for rom, addr, base in candidates[:ATTEMPTS]:
            image = self.scratch / f"{system}-{rom.crc}.bin"
            extract(rom, self.files, image)
            reply = self.call("start", **self.boot_arguments(system), reference_rom=str(image),
                              reference_addr=f"{addr:#x}", reference_base=f"{base:#x}")
            if reply.get("status") == "ok":
                return reply, f"{rom.name} at {addr:#x}"
            last = str(reply.get("message") or reply.get("summary"))
        raise LookupError(f"{system} would not start on {min(len(candidates), ATTEMPTS)} "
                          f"addresses, the map harness answering {learned.get('status')}: "
                          + last[:200])

    def devices(self, session: dict[str, Any], mapping: dict[str, Any]) -> MachineRun:
        """Every device the machine reports, asked of the base; a cpu by the scope of its type.

        No tool answers the device list, so it is read from the gather `start` made, where
        `status` says the session wrote it."""
        run = MachineRun(system=str(session.get("system", "")))
        cpus = {cpu.get("cpu", ""): cpu.get("type", "") for cpu in mapping.get("cpus", [])}
        dump = Path(str(session.get("scratch_dir", ""))) / "names.txt"
        for tag, shortname, name in read_devices(dump):
            asked = self.call("knowledge_find", kind="device", key=tag)
            answered = any(entry.get("chip") for entry in asked.get("entries", []))
            if not answered and tag in cpus:
                answered = self._scope_held(shortname)
            run.devices.append(Device(tag=tag, shortname=shortname, name=name,
                                      answered=answered))
            if any(entry.get("chip") for entry in asked.get("entries", [])):
                self.call("knowledge_find", kind="register", device=tag)
        return run

    def _scope_held(self, shortname: str) -> bool:
        scope = naming.MAMENAMER.scope_of_type(shortname)
        if scope is None:
            return False
        reply = self.call("knowledge_find", kind="vector", scope=scope, limit=1)
        return reply.get("status") == "ok" and reply.get("examined", 0) > 0

    def names(self, mapping: dict[str, Any], booted: dict[str, Any]) -> None:
        """The reads whose replies carry names: each cpu's first bytes and its pc, a 16-bit
        space's vector table, and a 6809 `swi`."""
        masks = {str(space.get("cpu", "")): int(str(space.get("address_mask", "0x0")), 16)
                 for space in mapping.get("spaces", []) if space.get("space") == "program"}
        for cpu in mapping.get("cpus", []):
            tag = str(cpu.get("cpu", ""))
            self.call("read_memory", ref="0x0", length=0x10, cpu=tag)
            self.call("disassemble", ref="0x0", length=0x10, cpu=tag)
            if masks.get(tag) == 0xFFFF:
                self.call("read_memory", ref=f"{0xFFF0:#x}", length=0x10, cpu=tag)
            if str(cpu.get("type", "")) in SWI_CPUS:
                found = self.call("find", ref="0x0", length=FIND_LENGTH, data_hex=SWI_OPCODE)
                # The last byte of the space has no room for a line, and MAME would refuse it.
                room = masks.get(tag, 0) - FIND_BYTES
                hits = [hit for hit in found.get("hits") or [] if int(str(hit), 16) <= room]
                if hits:
                    self.call("disassemble", ref=str(hits[0]), length=FIND_BYTES, cpu=tag)
        if isinstance(booted.get("pc"), str):
            self.call("disassemble", ref=booted["pc"], length=0x10)

    def write_replies(self) -> Path:
        """The run's replies, one JSON object a line."""
        path = self.out / "replies.jsonl"
        path.write_text("".join(json.dumps(reply, sort_keys=True) + "\n"
                                for reply in self.replies), encoding="utf-8")
        return path


def main(argv: Iterable[str]) -> int:
    arguments = list(argv)
    target = arguments[arguments.index("--out") + 1:] if "--out" in arguments else []
    out = ((Path(target[0]).expanduser() if target
            else Path(tempfile.mkdtemp(prefix="scry-bench-devices-"))).resolve())
    out.mkdir(parents=True, exist_ok=True)
    binary = os.environ.get("MAME_BINARY", "")
    romdir_raw = os.environ.get("MAME_TEST_ROMS", "")
    bench_raw = os.environ.get("MAME_LIVE_BENCH", "")
    for name, value in (("MAME_BINARY", binary), ("MAME_TEST_ROMS", romdir_raw),
                        ("MAME_LIVE_BENCH", bench_raw)):
        if not value:
            print(f"INVALID: {name} is not set")
            return 3
    romdir, bench_dir = Path(romdir_raw), Path(bench_raw)
    if not bench_dir.is_dir():
        print(f"INVALID: the bench at {bench_dir} is not a directory")
        return 3
    try:
        problems = live_bench.problems(bench_dir)
    except Invalid as bad:
        print(f"INVALID: {bench_dir} is not a bench: {bad}")
        return 3
    if problems:
        print(f"INVALID: the bench does not match its manifest: {problems[0]}")
        return 3
    archives = sorted(romdir.glob("*.zip"))
    if not archives:
        print(f"INVALID: no romset in {romdir}")
        return 3
    systems = [archive.stem for archive in archives]
    described: dict[str, Describe] = {}
    for system in systems:
        try:
            described[system] = describe(binary, system)
        except (LookupError, OSError, ET.ParseError) as failed:
            print(f"INVALID: {system} is not a set this MAME answers for: {failed}")
            return 3
    sets = [system for system in systems if described[system].isdevice]
    hosts = carriers(described, sets)
    scratch = out / "scratch"
    ini = scratch / "ini"
    ini.mkdir(parents=True, exist_ok=True)
    (ini / "mame.ini").write_text("joystickprovider none\n", encoding="ascii")
    bench = Bench(binary, romdir, out, ini, scratch)
    runs: dict[str, MachineRun] = {}
    machines = [system for system in systems if not described[system].isdevice]
    print(f"bench: {len(systems)} sets, {len(machines)} machines, {len(sets)} device sets")
    for system in machines:
        try:
            _reply, how = bench.start(system, described[system])
            mapping = bench.call("machine_map")
            run = bench.devices(bench.call("status"), mapping)
            bench.names(mapping, _reply)
        except (LookupError, OSError, ET.ParseError) as failed:
            s.close()
            runs[system] = MachineRun(system=system, rc=1, why=str(failed))
            print(f"{system}: rc=1 did not run: {failed}")
            continue
        bench.call("close")
        runs[system] = run
        print(f"{system}: rc=0 started (reference {how}), {len(run.devices)} devices, "
              f"{run.answered} answered, {len(run.gaps)} gaps")
        for gap in run.gaps:
            print(f"    gap: {gap}")
    for name in sets:
        ran = [runs[host] for host in hosts.get(name, []) if host in runs]
        if not ran:
            print(f"{name}: rc=1 no machine of the bench carries it")
            continue
        host = next((run for run in ran if run.rc == 0 and run.devices), None)
        if host is None:
            print(f"{name}: not examined: every machine that carries it failed to run")
            continue
        inside = [device for device in host.devices if under(device.tag, name)]
        print(f"{name}: boots on {host.system}, {len(inside)} devices, "
              f"{sum(1 for d in inside if d.answered)} answered, "
              f"{sum(1 for d in inside if not d.answered)} gaps")
        for device in inside:
            if not device.answered:
                print(f"    gap: {device}")
    replies = bench.write_replies()
    not_run = sorted(system for system, run in runs.items() if run.rc != 0)
    print(f"replies: {replies}")
    if not bench.replies:
        print("INVALID: the run recorded no reply")
        return 3
    print(f"{len(runs)} machines, {sum(len(run.devices) for run in runs.values())} devices "
          f"reported, {sum(run.answered for run in runs.values())} answered, "
          f"{sum(len(run.gaps) for run in runs.values())} gaps, "
          f"{len(not_run)} did not run{': ' + ', '.join(not_run) if not_run else ''}")
    return 1 if not_run else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
