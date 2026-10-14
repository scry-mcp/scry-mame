"""WHERE AN ADDRESS GOES, from the console's own `map` (and `mapi` for a port): the handler each
side of an address reaches, read before anything is armed there. A change watch, a count or
capture tap, a film's trigger, a `write`'s description of what it touched and a capture's choice
of where to read a block all ask this one reader, so one answer about an address is the answer
every tool gives about it.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import gdb_session as gs
import mame_arming as arming
import mame_console as console
import mame_space as mspace
import mame_state as st

# THE HANDLER IS THE REST OF THE LINE after the arrow and whatever MAME names in parentheses
# before it: an armed watchpoint (`-> (wp@91d0) twins_state::access_w`) and every Lua write tap
# (`-> (mcp_tally_2031fe_1) (mcp_capture_...) memory@200000`, captured). A match wanting one
# last token read the first line as having no write side, and one that kept a tap's name read
# memory as a handler.
_MAP_WRITE = re.compile(r"^\s*Write:.*->\s*(?:\([^()]*\)\s*)*(.+?)\s*$", re.M)
_MAP_READ = re.compile(r"^\s*Read:.*->\s*(?:\([^()]*\)\s*)*(.+?)\s*$", re.M)


def map_question(addr: int, space: str = mspace.PROGRAM) -> str:
    """The console command that asks where `addr` goes: `map`, or `mapi` for a port in the io
    space. The one spelling every reader asks it with, and the one a refusal quotes."""
    return f"{'mapi' if space == mspace.IO else 'map'} {addr:#x}"


def ask_map(ses: gs.Session, addr: int, cpu: str | None, space: str = mspace.PROGRAM) -> str:
    """The console's answer to `map_question` on `cpu` (the visible one when None)."""
    return ses.monitor(f"{map_question(addr, space)}{console.cpu_suffix(cpu)}")

#: A handler side the console's `map` printed no line for.
NO_READ_SIDE_WHY = "the console's `map` printed no line for this side"


def map_sides(maps: str) -> dict[str, str | None]:
    """Both handlers the console's `map` names for an address: `read` and `write`, each the
    rest of its line after the arrow (None when the line is not there). One call answers
    both, and the write side is the change watch's control while the read side decides where a
    watch's values come from."""
    def side(rx: re.Pattern[str]) -> str | None:
        m = rx.search(maps)
        return None if m is None else m.group(1)
    return {"read": side(_MAP_READ), "write": side(_MAP_WRITE)}


def write_side(ses: gs.Session, addr: int, cpu: str | None = None,
               space: str = "program") -> tuple[arming.Refusal | None, str, str | None]:
    """WHERE the write side of `addr` maps, from the console's `map` (`mapi` for a port in the
    io space), asked before anything is armed: the refusal as its code beside its text (or None)
    when the console names no `Write:` side, the write target (`unmapped` is one), and the read
    target from the same answer. What a caller makes of `unmapped` is its own:
    `with_unmapped_note` for a tap, `change_watch_side` for a change watch."""
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
    """The ONE sentence a tap on an unmapped write side says: a write tap sees every write the
    cpu makes whether or not anything handles it (measured, program and io), so the guest's
    write goes nowhere and the tap still sees it; on an address that reads as memory, the ROM
    copy of a datum, where the datum lives instead."""
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
    """`note` with `unmapped_note` appended when the tap's write side (a capture's or a film's
    TRIGGER, `trigger`) is unmapped, else `note` unchanged: what the install said is kept."""
    if maps_to != "unmapped":
        return note
    label = "the trigger: " if trigger else ""
    return st.join_notes(note, f"{label}{unmapped_note(addr, space, read_maps_to)}") or note


def change_watch_side(ses: gs.Session, addr: int, cpu: str | None = None
                      ) -> tuple[arming.Refusal | None, str, str | None]:
    """`write_side` for a CHANGE watch, which refuses an unmapped write side: it is the
    debugger's watchpoint, and measured, the stub accepts and lists one there that never fires."""
    refused, write, read_ = write_side(ses, addr, cpu)
    if refused is None and write == "unmapped":
        return (("bad_argument", f"the write side of {addr:#x} is unmapped: a change "
                 "watch there can never fire. Measured: the stub accepts and lists it all the "
                 "same. This is the ROM copy of a datum whose live copy is elsewhere, or an "
                 "address nothing writes; watch the RAM address instead, or count the cpu's "
                 "writes there with `mode=\"count\"`"), "", read_)
    return refused, write, read_


def read_side(ses: gs.Session, cpu: str | None) -> Callable[[int], str | None]:
    """Where the program map reads an address on `cpu`: what `capture.source` asks of each
    address a block touches."""
    return lambda at: map_sides(ask_map(ses, at, cpu))["read"]


def memory_kind(ses: gs.Session, addr: int, cpu: str | None = None) -> str:
    """What `addr` IS to `cpu` (the visible one when None), from the console's `map`, for a
    symbol table that carries no such thing: `ram` (written and read through the same memory),
    `rom` (nothing writes it: the ROM copy of a datum, or code), `latch` (written through a
    handler and read NOWHERE: a change watch's values come off the bus there), `handlers`
    (written and read through handlers, a paired `_r`/`_w` region: readable, watchable,
    not plain memory), `unmapped` (neither side), `unknown` (the console named no side).
    Asked BEFORE a change watch is tried, which was the only way to learn it."""
    sides = map_sides(ask_map(ses, addr, cpu))
    write, read_ = sides["write"], sides["read"]
    if write is None or read_ is None:
        return "unknown"
    if write == "unmapped":
        return "unmapped" if read_ == "unmapped" else "rom"
    if read_ == "unmapped":
        return "latch"
    return "ram" if read_ == write and read_.startswith("memory@") else "handlers"
