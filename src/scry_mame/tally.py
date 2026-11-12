"""A watch that COUNTS: every write to a range over a pass, by value and by writer, never
stopping for one; asked to (`access`), the reads too, as a bare total apart from the writes.

A change watch stops at the first write; a census needs every value a register takes over a
pass and from which pcs. `disarm_watches` disarms change watches, so a held pass counts nothing.

Idempotent by id: the console reruns an earlier chunk after its reader dies
(`console_reruns`), so an install removes the tap held under its id and carries its counts
into the new one; `declaration_clear(kind="watch")` removes the tap, so the next declaration
starts from zero. Sending, proving, removing and reading a tap is `tap`.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from scry_core import bus_writes, file_names, prose
from scry_core.reply_contract import Invalid

from scry_mame import callbacks, lua_source, read
from scry_mame import declarations as dec
from scry_mame import space as mspace
from scry_mame import state as st
from scry_mame import tap as mtap
from scry_mame.state import STATE

REGISTRY = "MCP_TALLY"
# Past the cap a write still counts in `total` and `overflow_*`, so a cut table says so.
BUCKETS_MAX = 256
HEADER = "MCP_TALLY"
_HEAD = re.compile(
    rf"^{HEADER} (\S+) seq=(\d+) frame=(-?\d+) total=(\d+) (?:reads=(\d+) )?values=(\d+) "
    r"pcs=(\d+) "
    r"overflow_values=(\d+) overflow_pcs=(\d+) data_width=(\d+) endianness=(\w+) cpu=(\S+)$")
_VALUE = re.compile(r"^v ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+) (\d+)$")
_PC = re.compile(r"^p ([0-9a-f]+) (\d+)$")


def id_for(cpu: str | None, addr: int, width: int, space: str = "program") -> str:
    """The `tally_id` of a range on its cpu and space, whose words name the dump's file; the
    first cpu's id is the range alone, and a space other than the program's is suffixed
    (`@io`)."""
    tag = "" if cpu in (None, STATE.first_cpu) else "_" + str(cpu).strip(":").replace(":", ".")
    return f"{addr:x}_{width}{tag}{mspace.suffix(space)}"


def id_words(an_id: str) -> str:
    """An id as the words of its file. One the words do not spell back, or too long for a
    name, carries a digest of the id, which keeps two ids out of one file."""
    digest = hashlib.sha256(an_id.encode()).hexdigest()
    try:
        words = file_names.word(an_id, "id")
    except Invalid:
        return digest[:16]
    return words if words.replace("-", "_") == an_id else f"{words}-{digest[:8]}"


def dump_path(scratch: Path, tally_id: str) -> Path:
    return scratch / file_names.name("tally", id_words(tally_id), extension="txt")


def install_script(tally_id: str, addr: int, width: int, path: Path,
                   cpu: str | None = None, space: str = "program", access: str = "w") -> str:
    """The one-chunk Lua that installs the tally over `width` bytes at `addr` on `cpu`."""
    last = addr + width - 1
    code = lua_source.Code
    return mtap.tap_prelude(REGISTRY) + lua_source.render(
        "tally-install", id=tally_id, first=code(f"{addr:#x}"), last=code(f"{last:#x}"),
        path=str(path), bind_cpu=code(mtap.bound_cpu(cpu)), space=space,
        remove_old=code(mtap.REMOVE_OLD_TAP), no_frame=callbacks.NO_FRAME,
        taps=code(_taps(access)),
        dumper=code(mtap.register_dumper_once(lua_source.render("tally-dumper", header=HEADER))),
        answer=mtap.ANSWER_PREFIX).rstrip("\n")


def _taps(access: str) -> str:
    """The Lua that installs the tap or taps `access` names, each filtered by landing."""
    writes = lua_source.render("tally-write-tap", buckets_max=BUCKETS_MAX)
    reads = lua_source.render("tally-read-tap")
    if access == "r":
        return reads + "t.tap = rtap\n"
    if access == "rw":
        return writes + reads + "t.tap = {remove = function() wtap:remove() rtap:remove() end}\n"
    return writes + "t.tap = wtap\n"


def send_install(scratch: Path, owner: dec.Owner, addr: int, width: int,
                 space: str = "program", access: str = "w") -> dict[str, Any]:
    """Send the count watch's install for `owner` (`mtap.send_tap`)."""
    cpu = owner[1]
    tally_id = id_for(cpu, addr, width, space)
    path = dump_path(scratch, tally_id)
    return mtap.send_tap(scratch, owner, tally_id,
                         install_script(tally_id, addr, width, path, cpu, space, access),
                         REGISTRY, [path], addr=addr, width=width, path=path, space=space,
                         access=access)


def parse_dump(text: str) -> dict[str, Any] | None:
    """A dump as the periodic wrote it, or None when not whole (unknown header, no `end`)."""
    whole = callbacks.read_whole(text, _HEAD, with_body=True)
    if whole is None:
        return None
    head, body, errors = whole
    values: list[tuple[int, int, int, int]] = []
    pcs: list[tuple[int, int]] = []
    for ln in body:
        if (v := _VALUE.match(ln)) is not None:
            values.append((int(v.group(1), 16), int(v.group(2), 16), int(v.group(3), 16),
                           int(v.group(4))))
        elif (p := _PC.match(ln)) is not None:
            pcs.append((int(p.group(1), 16), int(p.group(2))))
        else:
            return None
    return {"id": head.group(1), "seq": int(head.group(2)), "frame": int(head.group(3)),
            "total": int(head.group(4)), "reads": int(head.group(5) or 0), "values": values,
            "pcs": pcs, "overflow_values": int(head.group(8)), "overflow_pcs": int(head.group(9)),
            "data_width": int(head.group(10)), "endianness": head.group(11),
            "cpu": head.group(12), **errors}


def _value_rows(dump: dict[str, Any], addr: int, width: int, fmt: str,
                shown: int) -> list[dict[str, Any]]:
    """The value table in the byte order the dump names (`bus_writes.value_rows`)."""
    return bus_writes.value_rows(dump["values"], addr, width, fmt, dump["data_width"],
                                 dump["endianness"], shown, st.hex_addr)


def _writer_rows(dump: dict[str, Any], shown: int) -> list[dict[str, Any]]:
    """The writer table, most frequent first, each pc placed in the nearest symbol below."""
    rows: list[dict[str, Any]] = []
    for pc, count in sorted(dump["pcs"], key=lambda r: (-r[1], r[0]))[:shown]:
        rows.append(read.add_symbol({"pc": st.hex_addr(pc), "count": count}, pc,
                                    dump.get("cpu")))
    return rows


def evaluate(scratch: Path, owner: dec.Owner, width: int, fmt: str,
             frame: int | None, shown: int, at_stop: bool) -> dict[str, Any]:
    """What a stop survey or `declaration_list(kind="watch")` says about the tally under
    `owner`, with its value and writer tables once it has a dump."""
    item, dump = mtap.read_tap(scratch, owner, frame, at_stop, parse_dump, "tallied")
    if dump is None:
        return item
    rec = STATE.tallies[owner]
    item.update(values=_value_rows(dump, rec["addr"], width, fmt, shown),
                values_total=len(dump["values"]), overflow_values=dump["overflow_values"],
                writers=_writer_rows(dump, shown), writers_total=len(dump["pcs"]),
                overflow_pcs=dump["overflow_pcs"])
    if "r" in rec.get("access", "w"):
        item["reads"] = dump["reads"]
    return item


def check_count_watch(chosen: str, mode: str = "count") -> None:
    """A count or capture watch is by symbol or address: a tap follows no pointer, so a
    moving range would be counted wrong in silence."""
    if chosen not in ("symbol", "address"):
        raise st.Invalid("bad_argument",
                         f"a {mode} watch is declared by symbol or by address, not by {chosen}: "
                         "the tap sits on one range for its life, so "
                         f"`watch_add(ref=<symbol or address>, mode=\"{mode}\")`")


def bus_unchecked_note(space: str) -> str:
    """What `watch_add`'s count reply adds when the bus width in `space` is unknown."""
    return (f"`start` gathered no {space} space for this cpu, so whether the range splits a bus "
            "word was not checked")


def split_why(addr: int, width: int, data_width: int, cpu: str | None,
              space: str = mspace.PROGRAM) -> str:
    """The refusal of a range that `mspace.splits_bus_word`, naming one count per bus word."""
    nb = data_width // 8
    pieces: list[tuple[int, int]] = []
    at, end = addr, addr + width
    while at < end:
        stop = min(end, at - at % nb + nb)
        pieces.append((at, stop - at))
        at = stop
    on = (f', cpu="{cpu}"' if cpu is not None and cpu != STATE.first_cpu else "") + (
        "" if space == mspace.PROGRAM else f', space="{space}"')
    (first, first_n), rest = pieces[0], [f"{a:#x} (length={n})" for a, n in pieces[1:]]
    others = (", ".join(rest) if len(rest) <= 3
              else f"{rest[0]}, every bus word after it, and {rest[-1]}")
    return (f"{prose.counted(width, 'byte')} at {addr:#x} split a {data_width}-bit bus word: a "
            "write lands in one bus word, so the rows of a word the range covers only in part are "
            "fragments, `partial` with no `value`; declare one count per bus word it touches, "
            "each then written whole: "
            f'`watch_add(ref="{first:#x}", mode="count", length={first_n}{on})` '
            f"and the same at {others}")
