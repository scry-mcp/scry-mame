"""THE REGION BEHIND A ROM ADDRESS: which one backs it, and how bytes get into it.

A cpu's program space has no write side over ROM, so a `write` there lands nowhere. The bytes
live in a memory REGION that the space reads through, and the console can reach a region
directly: `saver` copies a span of one to a file and `loadr` a file into one, raw, without a
guest step and without the cpu's view in between. This module places an address in its
region (the same resolution `write`'s ROM explanation gives) and writes through that route,
reading the result back through the cpu, which is the view the caller asked about.
"""

from __future__ import annotations

import re
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core import prose

import gdb_session as gs
import mame_files as files
import mame_state as st
from mame_state import STATE

# WHAT SAYS THE SPAN MOVED. `Invalid offset`, `No matching memory region` and a clamp to the
# region's end all come back as ordinary text, and a clamped `saver` even says it succeeded
# (`tests/fixtures/console/saver.clamped-at-end.txt`): `saver`'s proof is its file, whole, and
# `loadr`'s is its success sentence naming the whole range (`loadr.loaded.txt`), matched
# positively, since a load one short of its file loads less and says so only there.
_LOADED = re.compile(r"^Data loaded successfully to memory : 0x([0-9A-F]+) to 0x([0-9A-F]+)$",
                     re.M)


@dataclass(frozen=True)
class Place:
    """Where an address of one cpu lives in a region: the `region` tag, and the `offset` into it
    and the offset `end` of the map entry's last byte when the cached address map can say, with
    `where`, the sentence that says so or says why not."""
    region: str | None
    offset: int | None
    end: int | None
    where: str


def unmirrored(entry: dict[str, Any], addr: int) -> int:
    """`addr` with the entry's mirror bits cleared: MAME ignores them when it matches an
    address to an entry, so a mirror copy is the same bytes."""
    return addr & ~int(entry.get("mirror", "0"), 16)


def _backing_entries(addr: int) -> list[dict[str, Any]]:
    """Every program-space entry of the cached address map that holds `addr`, a mirror copy
    included, and is backed by a region, whichever cpu it belongs to."""
    rows = STATE.machine_map.get("address_map", []) if STATE.machine_map else []
    return [row for row in rows if row["space"] == "program" and "region" in row
            and int(row["start"], 16) <= unmirrored(row, addr) <= int(row["end"], 16)]


def place(addr: int, cpu: str | None) -> Place:
    """The region backing `addr` on `cpu`, from the address map `start` cached. ONE CPU: a
    region is that cpu's, never one picked by list order off another cpu's map, and a cpu the
    console could not name leaves the region unnamed."""
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
    """The region's size, byte width and byte order as `start` gathered them, or None."""
    rows = STATE.machine_map.get("regions", []) if STATE.machine_map else []
    return next((row for row in rows if row["tag"] == tag), None)


HOST_ENDIAN = sys.byteorder    # what `region:read` copies in
_WORD_CODES = {2: "H", 4: "I", 8: "Q"}


def _swaps(width: int, endianness: str) -> bool:
    """Whether a region of this byte width and order is kept reversed from the cpu's view."""
    return width > 1 and endianness != HOST_ENDIAN


def logical(raw: bytes, width: int, endianness: str) -> bytes:
    """A region's host-order copy in the block's own order, or back (the swap is its own
    inverse): each `width`-byte word reversed when the block's endianness is not the host's
    (MAME's `xormask`, applied to the bytes). A block of
    megabytes is swapped in C by `array.byteswap`, never a word at a time in Python."""
    if not _swaps(width, endianness):
        return raw
    code = _WORD_CODES.get(width)
    if code is not None and array(code).itemsize == width and len(raw) % width == 0:
        words = array(code, raw)
        words.byteswap()
        return words.tobytes()
    return b"".join(raw[i:i + width][::-1] for i in range(0, len(raw), width))


def unwritable(here: Place, n: int) -> str | None:
    """Why `n` bytes cannot go into the region at `here`, or None when they can: the one
    judgement the region write refuses on and the ROM explanation offers `region=True` by."""
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
    """Put `data` into the region behind `addr` of `cpu` (`kind` is what the console's `map`
    answered for it) through `saver` then `loadr`, and answer the region and the offset.

    THE SPAN IS WIDENED TO WHOLE REGION WORDS when the region is kept in the other byte order:
    one region byte at an odd offset lands on the EVEN byte of its cpu word (measured), so a
    write that starts or ends inside a word is a read-modify-write of the words it touches, the
    rest of each word written back as `saver` found it. Everything is judged BEFORE `saver`,
    and `saver` goes before `loadr`, so a region the console will not answer for costs no
    write. A refusal is raised; the reply of a load is the caller's to finish with the
    read-back.
    """
    here = place(addr, cpu)
    # WHAT BACKS THE ADDRESS DECIDES, not what its write side is: a region entry's write side
    # can be unmapped, a handler or nothing, and MAME refuses one that writes to memory, so a
    # region placed here is read-only memory whatever `map` calls it.
    why = unwritable(here, len(data))
    if why is not None:
        also = "; a write without `region` reaches it" if kind == "ram" else ""
        raise st.Invalid("bad_argument",
                         f"the console's `map` answers {kind} at {addr:#x}, and {why}{also}")
    assert here.region is not None and here.offset is not None       # `unwritable` said so
    layout = _layout(here.region)
    assert layout is not None
    width, order = layout["bytewidth"], layout["endianness"]
    unit = width if _swaps(width, order) else 1
    last = here.offset + len(data) - 1
    lo, hi = here.offset - here.offset % unit, -(-(last + 1) // unit) * unit
    path = scratch / "region.bin"
    files.refuse_console_path(path)
    span = f"{lo:#x},{hi - lo:#x},{here.region}"
    path.unlink(missing_ok=True)     # an earlier write's file is not this `saver`'s answer
    said = ses.monitor(f"saver {path},{span}")
    files.whole_file(path, hi - lo, said, "saver", "; nothing was loaded", region=here.region,
                     region_offset=here.offset)
    # MAME KEEPS A REGION WIDER THAN A BYTE IN THE HOST'S ORDER (`romload.cpp` swaps one whose
    # endianness is not the native one once, at load), so the cpu's view is `logical` of
    # the file and back again, the swap being its own inverse. The region's layout is the
    # space's: MAME's validation refuses a map whose region differs in width or byte order.
    view = bytearray(logical(path.read_bytes(), width, order))
    view[here.offset - lo:here.offset - lo + len(data)] = data
    path.write_bytes(logical(bytes(view), width, order))
    # A `loadr` about to be sent counts as a write whatever comes back, on the cautious side:
    # an answer that is not its success sentence, or no answer, cannot say whether the file
    # reached the region.
    STATE.console_writes += 1
    said = ses.monitor(f"loadr {path},{span}")
    loaded = _LOADED.search(said)
    if loaded is None or (int(loaded.group(1), 16), int(loaded.group(2), 16)) != (lo, hi - 1):
        raise st.Invalid("unexpected_answer", f"`loadr` of {hi - lo:#x} bytes at "
                         f"{here.region} offset {lo:#x} answered {said.strip()!r}",
                         region=here.region, region_offset=here.offset)
    return {"region": here.region, "region_offset": here.offset}
