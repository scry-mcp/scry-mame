"""Place a ROM address in its memory region and write through `saver`/`loadr`."""

from __future__ import annotations

import re
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core import prose

from scry_mame import files
from scry_mame import gdb_session as gs
from scry_mame import state as st
from scry_mame.state import STATE

# A clamped `saver` says it succeeded: its proof is its whole file, `loadr`'s the success
# sentence naming the whole range.
_LOADED = re.compile(r"^Data loaded successfully to memory : 0x([0-9A-F]+) to 0x([0-9A-F]+)$",
                     re.M)


@dataclass(frozen=True)
class Place:
    """Where an address lives in a region; `where` says so or says why not."""
    region: str | None
    offset: int | None
    end: int | None
    where: str


def unmirrored(entry: dict[str, Any], addr: int) -> int:
    """`addr` with the entry's mirror bits cleared (a mirror copy is the same bytes)."""
    return addr & ~int(entry.get("mirror", "0"), 16)


def _backing_entries(addr: int) -> list[dict[str, Any]]:
    """Region-backed program-space entries of the cached map that hold `addr`, any cpu."""
    rows = STATE.machine_map.get("address_map", []) if STATE.machine_map else []
    return [row for row in rows if row["space"] == "program" and "region" in row
            and int(row["start"], 16) <= unmirrored(row, addr) <= int(row["end"], 16)]


def place(addr: int, cpu: str | None) -> Place:
    """The region backing `addr` on `cpu`; another cpu's map entry never names it."""
    entries = [row for row in _backing_entries(addr) if row["cpu"] == cpu]
    if not (STATE.machine_map or {}).get("address_map"):
        return Place(None, None, None,
                     "the address map was not gathered at `start`, so no region is named")
    if cpu is None:
        return Place(None, None, None,
                     "`cpulist` named no cpu the write went to, so no region is named")
    if not entries:
        return Place(None, None, None, "no region in the cached address map backs it")
    if len(entries) > 1:
        return Place(None, None, None, "more than one entry of the cached address map backs "
                     "it, so no region is named")
    entry = entries[0]
    if "address_mask" in entry:
        return Place(entry["region"], None, None,
                     f"its bytes live in the region {entry['region']}; the map entry masks its "
                     "addresses, so the offset is not computed here")
    start = int(entry["start"], 16)
    offset = entry["region_offset"] + unmirrored(entry, addr) - start
    return Place(entry["region"], offset,
                 entry["region_offset"] + int(entry["end"], 16) - start,
                 f"its bytes live in the region {entry['region']} at offset {offset:#x}")


def _layout(tag: str) -> dict[str, Any] | None:
    """The region's size, byte width and byte order from `start`'s inventory, or None."""
    rows = STATE.machine_map.get("regions", []) if STATE.machine_map else []
    return next((row for row in rows if row["tag"] == tag), None)


HOST_ENDIAN = sys.byteorder
_WORD_CODES = {2: "H", 4: "I", 8: "Q"}


def _swaps(width: int, endianness: str) -> bool:
    """Whether a region of this width and order is kept reversed from the cpu's view."""
    return width > 1 and endianness != HOST_ENDIAN


def logical(raw: bytes, width: int, endianness: str) -> bytes:
    """Swap a region's host-order copy to the cpu's order, or back (its own inverse).

    `array.byteswap` does megabytes in C, never a word at a time in Python."""
    if not _swaps(width, endianness):
        return raw
    code = _WORD_CODES.get(width)
    if code is not None and array(code).itemsize == width and len(raw) % width == 0:
        words = array(code, raw)
        words.byteswap()
        return words.tobytes()
    return b"".join(raw[i:i + width][::-1] for i in range(0, len(raw), width))


def unwritable(here: Place, n: int) -> str | None:
    """Why `n` bytes cannot go into the region at `here`, or None when they can."""
    if here.region is None or here.offset is None or here.end is None:
        return f"{here.where}, so there is no region offset to write at"
    last = here.offset + n - 1
    if last > here.end:
        return (f"{prose.counted(n, 'byte')} from region offset {here.offset:#x} "
                f"{prose.agrees(n, 'runs', 'run')} past the map entry's end at {here.end:#x}")
    layout = _layout(here.region)
    if layout is None:
        return (f"the region {here.region} is not in the inventory `start` gathered, so its "
                "byte order is unknown")
    if last >= layout["size"]:
        return (f"{prose.counted(n, 'byte')} from region offset {here.offset:#x} "
                f"{prose.agrees(n, 'runs', 'run')} past the end of {here.region} "
                f"({layout['size']:#x} bytes)")
    return None


def write(ses: gs.Session, scratch: Path, addr: int, data: bytes, cpu: str | None,
          kind: str) -> dict[str, Any]:
    """Put `data` into the region behind `addr` through `saver` then `loadr`.

    `kind` is what the console's `map` answered. The span widens to whole region words when
    the region is kept in the other byte order (a read-modify-write). Everything is judged
    before `saver`, so a refusal costs no write; it is raised, and the read-back is the
    caller's.
    """
    here = place(addr, cpu)
    # a region entry's write side can be unmapped or a handler, yet the region is read-only
    # memory whatever `map` calls it
    why = unwritable(here, len(data))
    if why is not None:
        also = "; a write without `region` reaches it" if kind == "ram" else ""
        raise st.Invalid("bad_argument",
                         f"the console's `map` answers {kind} at {addr:#x}, and {why}{also}")
    assert here.region is not None and here.offset is not None
    layout = _layout(here.region)
    assert layout is not None
    width, order = layout["bytewidth"], layout["endianness"]
    unit = width if _swaps(width, order) else 1
    last = here.offset + len(data) - 1
    lo, hi = here.offset - here.offset % unit, -(-(last + 1) // unit) * unit
    path = scratch / "region.bin"
    files.refuse_console_path(path)
    span = f"{lo:#x},{hi - lo:#x},{here.region}"
    path.unlink(missing_ok=True)     # a stale file is not this `saver`'s answer
    said = ses.monitor(f"saver {path},{span}")
    files.whole_file(path, hi - lo, said, "saver", "; nothing was loaded", region=here.region,
                     region_offset=here.offset)
    # MAME keeps a region wider than a byte in host order (`romload.cpp`), so the cpu's view
    # is `logical` of the file; MAME's validation makes the space share the region's layout.
    view = bytearray(logical(path.read_bytes(), width, order))
    view[here.offset - lo:here.offset - lo + len(data)] = data
    path.write_bytes(logical(bytes(view), width, order))
    # counted before the send: a missing or unexpected answer cannot say whether it landed
    STATE.console_writes += 1
    said = ses.monitor(f"loadr {path},{span}")
    loaded = _LOADED.search(said)
    if loaded is None or (int(loaded.group(1), 16), int(loaded.group(2), 16)) != (lo, hi - 1):
        raise st.Invalid("unexpected_answer", f"`loadr` of {hi - lo:#x} bytes at "
                         f"{here.region} offset {lo:#x} answered {said.strip()!r}",
                         region=here.region, region_offset=here.offset)
    return {"region": here.region, "region_offset": here.offset}
