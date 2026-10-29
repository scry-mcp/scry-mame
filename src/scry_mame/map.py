"""Where an address goes, from the console's `map` (`mapi` for a port): one reader for all tools."""

from __future__ import annotations

import re
from collections.abc import Callable

from scry_mame import arming, console
from scry_mame import gdb_session as gs
from scry_mame import space as mspace
from scry_mame import state as st

# Handler = rest of the line after the arrow, minus parenthesised names: an armed watchpoint
# (`-> (wp@91d0) twins_state::access_w`) or a Lua tap (`-> (mcp_tally_...) memory@200000`).
_MAP_WRITE = re.compile(r"^\s*Write:.*->\s*(?:\([^()]*\)\s*)*(.+?)\s*$", re.M)
_MAP_READ = re.compile(r"^\s*Read:.*->\s*(?:\([^()]*\)\s*)*(.+?)\s*$", re.M)


def map_question(addr: int, space: str = mspace.PROGRAM) -> str:
    """The console command asking where `addr` goes: `mapi` for the io space, else `map`."""
    return f"{'mapi' if space == mspace.IO else 'map'} {addr:#x}"


def ask_map(ses: gs.Session, addr: int, cpu: str | None, space: str = mspace.PROGRAM) -> str:
    """The console's answer to `map_question` on `cpu` (the visible one when None)."""
    return ses.monitor(f"{map_question(addr, space)}{console.cpu_suffix(cpu)}")

NO_READ_SIDE_WHY = "the console's `map` printed no line for this side"


def map_sides(maps: str) -> dict[str, str | None]:
    """The `read` and `write` handlers `map` names, each None when its line is absent."""
    def side(rx: re.Pattern[str]) -> str | None:
        m = rx.search(maps)
        return None if m is None else m.group(1)
    return {"read": side(_MAP_READ), "write": side(_MAP_WRITE)}


def write_side(ses: gs.Session, addr: int, cpu: str | None = None,
               space: str = "program") -> tuple[arming.Refusal | None, str, str | None]:
    """The write and read targets of `addr`, and a refusal when `map` names no `Write:` side.

    `unmapped` is a valid write target; what to do about it is the caller's."""
    command = map_question(addr, space)
    maps = ask_map(ses, addr, cpu, space)
    sides = map_sides(maps)
    write = sides["write"]
    if write is None:
        return (("bad_argument", f"the console's `{command}` named no `Write:` side, so "
                 f"whether a write there can fire is unknown: {maps.strip()!r}"),
                "", sides["read"])
    return None, write, sides["read"]


def unmapped_note(addr: int, space: str, read_maps_to: str | None) -> str:
    """The sentence a tap on an unmapped write side carries."""
    if space == mspace.IO:
        return (f"nothing in the machine handles an `out` at port {addr:#x}, so the guest's "
                "write goes nowhere, and the tap still sees every one the cpu makes")
    note = (f"nothing in the machine handles a write at {addr:#x}, so the guest's write goes "
            "nowhere, and the tap still sees every one the cpu makes")
    if read_maps_to is not None and read_maps_to.startswith("memory@"):
        note += ("; it reads as memory, the ROM copy of a datum whose live one is elsewhere: "
                 "watch the RAM address to see the datum change")
    return note


def with_unmapped_note(note: str, maps_to: str, addr: int, space: str,
                       read_maps_to: str | None, trigger: bool = False) -> str:
    """`note` plus `unmapped_note` when the tap's write side (or its `trigger`) is unmapped."""
    if maps_to != "unmapped":
        return note
    label = "the trigger: " if trigger else ""
    return st.join_notes(note, f"{label}{unmapped_note(addr, space, read_maps_to)}") or note


def change_watch_side(ses: gs.Session, addr: int, cpu: str | None = None
                      ) -> tuple[arming.Refusal | None, str, str | None]:
    """`write_side` refusing an unmapped write side, where a change watch never fires."""
    refused, write, read_ = write_side(ses, addr, cpu)
    if refused is None and write == "unmapped":
        return (("bad_argument", f"the write side of {addr:#x} is unmapped: a change "
                 "watch there can never fire. Measured: the stub accepts and lists it all the "
                 "same. This is the ROM copy of a datum whose live copy is elsewhere, or an "
                 "address nothing writes; watch the RAM address instead, or count the cpu's "
                 "writes there with `mode=\"count\"`"), "", read_)
    return refused, write, read_


def read_side(ses: gs.Session, cpu: str | None) -> Callable[[int], str | None]:
    """Where the program map reads each address on `cpu`."""
    return lambda at: map_sides(ask_map(ses, at, cpu))["read"]


def memory_kind(ses: gs.Session, addr: int, cpu: str | None = None) -> str:
    """What `addr` is to `cpu`: ram, rom, latch (written via handler, read nowhere), handlers,
    unmapped, or unknown (the console named no side)."""
    sides = map_sides(ask_map(ses, addr, cpu))
    write, read_ = sides["write"], sides["read"]
    if write is None or read_ is None:
        return "unknown"
    if write == "unmapped":
        return "unmapped" if read_ == "unmapped" else "rom"
    if read_ == "unmapped":
        return "latch"
    return "ram" if read_ == write and read_.startswith("memory@") else "handlers"
