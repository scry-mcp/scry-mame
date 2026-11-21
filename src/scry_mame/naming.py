"""What a number is called on MAME: the namer `scry_core.naming` asks, and what the running
machine says about itself for `knowledge_find`.

The namer reads only what the server already holds: the symbol tables, the inventory `start`
cached (cpu types, the address map with its handlers, devices and input fields) and the loaded
base. It never asks the emulator; the test that proves it hands it a session that fails on any
call."""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping, Sequence
from typing import Any

from scry_core import naming
from scry_core.knowledge import Base, Entry, KeyFault
from scry_core.knowledge import keys as keyspelling
from scry_core.naming import Field, Named

from scry_mame import cpus, inputs, machine, read
from scry_mame.knowledge import support
from scry_mame.state import STATE

#: The argument that says where a tool looks, in the tools that take an address or a symbol.
ADDRESS_ARGUMENT = "ref"
ADDRESS_TOOLS = frozenset({"read_memory", "memdump", "write", "disassemble", "find", "scan",
                           "breakpoint_at", "watch_add", "read_block"})

_ADDRESS = Field("addr", "memory")
_PC = "symbol"
#: Numbers the replies of a tool show, by the path of their field.
NUMBER_FIELDS: dict[str, tuple[Field, ...]] = {
    "read_memory": (_ADDRESS,), "memdump": (_ADDRESS,), "write": (_ADDRESS,),
    "disassemble": (_ADDRESS,), "breakpoint_at": (_ADDRESS,), "watch_add": (_ADDRESS,),
    "read_block": (_ADDRESS,), "scan": (_ADDRESS, Field("hits[].addr", "memory")),
    "find": (Field("hits[]", "memory"),),
    "status": (Field("pc", _PC),), "start": (Field("pc", _PC), Field("boot_pc", _PC)),
    "reset": (Field("pc", _PC),), "cpu_info": (Field("cpus[].pc.value", _PC),),
}
#: A stop may surface in the reply of any tool that runs the machine.
STOP_FIELDS = (Field("watch_hit.writer_pc", _PC), Field("watch_hit.writes[].pc", _PC),
               Field("regpoint_hit.pc", _PC))

#: More registers than any chip holds, and the span of one register bank (OPL3's second bank
#: starts at 0x100).
ALL_REGISTERS = 1000
BANK = 0x100

_BYTE = re.compile(r"[0-9A-Fa-f]{2}")
_HANDLER_CLASS = re.compile(r"([A-Za-z0-9_]+)::([A-Za-z0-9_]+)$")


def _address(value: object) -> int | None:
    """`value` as an address when it is one: an integer, or `0x` and hex digits."""
    found = None
    if isinstance(value, int) and not isinstance(value, bool):
        found = value
    elif isinstance(value, str) and inputs.ADDRESS.fullmatch(value.strip()):
        found = int(value, 16)
    return found if found is not None and keyspelling.fits(found) else None


def _hex(value: int) -> str:
    return f"0x{value:04X}"


class MameNamer:
    """Per argument and per reply field, what an address, a pc or a typed symbol is called."""

    def __init__(self, base: Base) -> None:
        self._base = base
        self._by_class: dict[str, Entry] = {
            c: e for e in base.entries() if e.kind == "device" and e.scope == "chip"
            for c in e.classes}

    def _cpu(self, tag: object) -> str | None:
        """The cpu a call or a reply is about: the one it names, else the machine's only one.
        With several and none named, no name is given: a wrong name is worse than none."""
        tags = [row["tag"] for row in (STATE.machine_map or {}).get("cpus", [])]
        if isinstance(tag, str) and tag:
            return next((t for t in tags if tag.strip() in (t, t.lstrip(":"))), None)
        return tags[0] if len(tags) == 1 else None

    def scope(self, cpu: str | None) -> str | None:
        """The base's scope of `cpu`'s type, or None when the server does not name it."""
        return self.scope_of_type(cpus.cpu_type(cpu))

    @staticmethod
    def scope_of_type(kind: str | None) -> str | None:
        """The base's scope of a MAME cpu type."""
        return next((s.name for s in support.SUPPORT.scopes if kind in s.types), None)

    def _symbol(self, addr: int, cpu: str, number: str) -> Named | None:
        if not STATE.table(cpu).table:
            return None
        placed = read.nearest_symbol(addr, cpu)
        if placed is None:
            return None
        start, name = placed
        return Named("symbol", name, number, addr - start)

    def _entry(self, cpu: str, addr: int) -> dict[str, Any] | None:
        """The address-map entry of `cpu`'s program space that holds `addr`: the last one, as
        MAME's later entries override earlier ones."""
        found = None
        for row in (STATE.machine_map or {}).get("address_map", []):
            if row["cpu"] == cpu and row["space"] == "program" and \
                    int(row["start"], 16) <= addr <= int(row["end"], 16):
                found = row
        return found

    def chip(self, handler: str) -> tuple[Entry, str] | None:
        """The shared chip a handler (`delegate/mc6845_device::address_w`) belongs to, and the
        method's own name."""
        found = _HANDLER_CLASS.search(handler)
        entry = self._by_class.get(found.group(1)) if found else None
        return None if entry is None or found is None else (entry, found.group(2))

    def chip_of_type(self, shortname: str) -> Entry | None:
        """The shared chip whose MAME device type is `shortname`."""
        chip = next((c for c in support.SUPPORT.chips if shortname in c.types), None)
        return None if chip is None else self._base.device_entry("chip", chip.name)

    def address(self, addr: int, cpu: str | None, number: str) -> Named | None:
        """The cpu's vector, which is sized and sourced, else the nearest symbol (a table holds no
        sizes), else the chip behind the map's handler, else the memory the map names."""
        if cpu is None:
            return None
        scope = self.scope(cpu)
        if scope is not None and (at := self._base.at(addr, scope)) is not None:
            vector, delta = at
            return Named("vector", vector.name, number, delta, vector.id)
        if (named := self._symbol(addr, cpu, number)) is not None:
            return named
        row = self._entry(cpu, addr)
        if row is None:
            return None
        for way in ("read", "write"):
            if (chip := self.chip(row.get(way, ""))) is not None:
                entry, _ = chip
                return Named("device", entry.name, number, 0, entry.id, entry.key)
        tag = row.get("share") or row.get("region")
        return Named("memory", tag.lstrip(":"), number) if tag else None

    @staticmethod
    def _handlers(reached: object) -> tuple[str, ...]:
        """The handler names a dictionary's `reached` word holds, one or a list."""
        if isinstance(reached, str):
            return (reached,)
        return tuple(reached) if isinstance(reached, list | tuple) else ()

    def _bank(self, chip: str, method: str) -> int | None:
        """Which 0x100-register bank the index handler `method` of `chip` selects: its place in
        the `reached.index` list of whichever of the chip's dictionaries holds one."""
        held = self._base.search(kind="register", scopes=(chip,), limit=ALL_REGISTERS).entries
        lists = sorted({self._handlers(e.reached.get("index")) for e in held if e.reached})
        return next((one.index(method) for one in lists if method in one), None)

    def register(self, addr: int, cpu: str | None, data: int, access: str = "write"
                 ) -> Named | None:
        """The register a one-byte `access` selects, when `addr` is a shared chip's index handler.
        The key is looked up across every register dictionary of the chip, as an entry of that
        `access` (else one with no access), reached through that handler."""
        row = self._entry(cpu, addr) if cpu is not None else None
        chip = self.chip(row.get("write", "")) if row is not None else None
        if chip is None:
            return None
        entry, method = chip
        bank = self._bank(entry.key, method)
        if bank is None:
            return None
        try:
            key = keyspelling.canonical("register", f"0x{bank * BANK + data:X}")
        except KeyFault:
            return None
        covering = [e for e in self._base.search(kind="register", key=key, scopes=(entry.key,),
                                                 limit=ALL_REGISTERS).entries
                    if e.reached and method in self._handlers(e.reached.get("index"))]
        found = next((e for want in (access, "") for e in covering if e.access == want), None)
        return None if found is None else Named("register", found.name, f"0x{data:02X}", 0,
                                                found.id, entry.key)

    def arguments(self, tool: str, given: Mapping[str, Any]) -> Mapping[str, Named]:
        out: dict[str, Named] = {}
        if tool not in ADDRESS_TOOLS or not STATE.machine_map:
            return out
        cpu = self._cpu(given.get("cpu"))
        ref = given.get(ADDRESS_ARGUMENT)
        if not isinstance(ref, str) or cpu is None:
            return out
        typed = _address(ref)
        if typed is None:
            try:
                addr = STATE.resolve(ref, cpu)
            except Exception:  # a ref that resolves to nothing is the call's own refusal
                return out
            out[ADDRESS_ARGUMENT] = Named("symbol", ref.strip(), _hex(addr))
            return out
        if (named := self.address(typed, cpu, ref.strip())) is not None:
            out[ADDRESS_ARGUMENT] = named
        data = given.get("data_hex")
        byte = data.replace(" ", "") if isinstance(data, str) else ""
        if tool == "write" and _BYTE.fullmatch(byte) and (
                register := self.register(typed, cpu, int(byte, 16), "write")) is not None:
            out["data_hex"] = register
        return out

    def reply(self, tool: str, reply: Mapping[str, Any]) -> Sequence[tuple[str, Named]]:
        out: list[tuple[str, Named]] = []
        if not STATE.machine_map:
            return out
        cpu = self._cpu(reply.get("cpu"))
        typed_symbol = isinstance(reply.get("ref"), str) and _address(reply["ref"]) is None
        for seen in naming.walk(reply, (*NUMBER_FIELDS.get(tool, ()), *STOP_FIELDS)):
            addr = _address(seen.value)
            if addr is None or (seen.field.path == "addr" and typed_symbol):
                continue
            number = seen.value if isinstance(seen.value, str) else _hex(addr)
            named = (self._symbol(addr, cpu, number) if seen.field.kind == _PC and cpu
                     else self.address(addr, cpu, number))
            if named is not None:
                out.append((seen.path, named))
        return out


@functools.cache
def base() -> Base:
    """The base this server loads once, at its first use."""
    return support.load()


class Live:
    """What the running machine says about itself, read from the inventory `start` cached."""

    kinds: tuple[str, ...] = ("memory", "input", "device")

    def scopes(self) -> tuple[str, ...]:
        found = [MAMENAMER.scope(row["tag"]) for row in (STATE.machine_map or {}).get("cpus", [])]
        return tuple(dict.fromkeys(s for s in found if s))

    def rows(self, kind: str, key: str, device: str) -> Sequence[Mapping[str, Any]] | None:
        if not STATE.machine_map:
            return None
        if kind == "input":
            return self._inputs(key)
        if kind == "memory":
            return self._memory(key)
        return self._devices(key or device)

    @staticmethod
    def _inputs(key: str) -> list[dict[str, Any]]:
        port, _, field = key.partition("/")
        return [{"kind": "input", "key": f"{row['port']}/{row['field']}", "name": row["field"],
                 "scope": row["port"]}
                for row in STATE.machine_map.get(machine.INPUTS, [])
                if (not port or row["port"] == port) and (not field or row["field"] == field)]

    @staticmethod
    def _devices(tag: str) -> list[dict[str, Any]]:
        out = []
        for row in STATE.machine_map.get(machine.DEVICES, []):
            if tag and row["tag"] != tag:
                continue
            chip = MAMENAMER.chip_of_type(row["shortname"])
            out.append({"kind": "device", "key": row["tag"], "name": row["name"],
                        "type": row["shortname"], **({"chip": chip.id} if chip else {})})
        return out

    @staticmethod
    def _memory(key: str) -> list[dict[str, Any]]:
        try:
            asked = keyspelling.query("memory", key)[1] if key else None
        except KeyFault:
            return []
        out = []
        for row in STATE.machine_map.get("address_map", []):
            lo, hi = int(row["start"], 16), int(row["end"], 16)
            if asked is not None and asked.lo is not None and not (
                    asked.lo <= hi and lo <= (asked.hi if asked.hi is not None else asked.lo)):
                continue
            handlers = (row.get(way, "").partition("/")[2] for way in ("read", "write"))
            name = row.get("share") or row.get("region") or next((h for h in handlers if h), "")
            if name:
                out.append({"kind": "memory", "key": f"{row['start']}..{row['end']}",
                            "name": str(name).lstrip(":"), "scope": row["cpu"]})
        return out


MAMENAMER = MameNamer(base())
#: The namer as the boundary holds it: a failure gives no names and is counted for `status`.
GUARD = naming.Guarded(MAMENAMER)
