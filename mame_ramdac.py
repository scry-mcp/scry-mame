"""The palette write log: which pen each write to a palette's ports landed on, who made it, and
the colour it left, taken inside MAME at emulation speed (`palette_log`), and the answer to "who
set this pen" that `screen_view`'s pixel mode joins to the index screen. It covers every kind of
palette port the manifest states (`palette_ports`: a RAMDAC, a latch, a sequence).

WHY A LOG AND NOT A COUNT WATCH. A RAMDAC is an index port and a data port: the index is written
once, then the components one after another on the data port, and the index moves on by itself
after the last of them. So a pen's colour is the sum of several writes to a port that names no
pen, and which pen a data write landed on is only known by following the device's own state from
the last index write. A count watch on the ports counts values; the log runs the state machine.

THE STATE MACHINE IS MAME'S `ramdac_device` (`src/devices/video/ramdac.cpp`): an index write sets
the index and sends the component counter back to 0; a data write lands on pen `pen_base +
index`, component `order[counter]`, and the counter moves on, returning to 0 at three, when the
index (a byte) moves on by one if the device auto-increments (MAME's `ramdac_device` always does;
`auto_increment: false` states a device that keeps its index). Until the first index write after
the log is armed, the machine is reset or a state is loaded, the index is not known: such a write
is counted `unsynced` and lands on no pen, because a guessed index is a plausible wrong pen. The
Lua that runs it inside MAME, and how it tells the guest's writes from the debugger's, is
`mame_ramdac_lua`'s; this module arms it, reads what it wrote and answers from that.

TWO PACKED PROTOCOLS put a whole colour in one word (`protocol` `latch` and `sequence`, whose
laws REFERENCE.md states): their pens are dumped as the word and the bits of it seen written,
never as components, and `decode` reads the colour out of the word under the entry's law, so
the tap keeps what the port carried and the reading of it lives in one place.

WHAT IS KEPT. Per pen, the newest data write and the components as the log composed them: at most
`pen_count` pens, never cut, which is what answers "who set it" after any length of run. Beside it
the ordered log, the capture's way (`mame_capture`): the first `ROWS_MAX` rows kept and the rest
counted, appended to the scratch at a stop. The record, the install answer, the dump reading and
the removal are every tap's (`mame_tap`), in a registry of this module's own.
"""

from __future__ import annotations

import collections
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import mame_callbacks as callbacks
import mame_capture as capture
import mame_declarations as dec
import mame_envelope as menvelope
import mame_files as files
import mame_inputs as inputs
import mame_iotaps as iotaps
import mame_manifest as mm
import mame_palette as mpalette
import mame_ramdac_lua as rlua
import mame_read as read
import mame_space as mspace
import mame_state as st
import mame_tally as tally
import mame_tap as mtap
from mame_state import STATE

ROWS_MAX = capture.ROWS_MAX
LIMIT_MAX = 256
LIMIT_DEFAULT = 16
# THE SETTERS A REPLY LISTS: a guest that uploads its palette through an unrolled loop has one
# writer per pen, a list no argument bounded, so the reply carries the first ones and the count
# beside them, as `gfx_locate` cuts its matches, and a file holds the whole list.
SETTERS_LISTED_MAX = 32
BY = {"g": "guest", "d": "debugger"}
DEBUGGER_NOTE = ("a `debugger` write was made while the machine stood in the debugger (this "
                 "server's `write`, a console command, a Lua chunk): its `pc` is where the machine "
                 "stood, not a writer")
UNSYNCED_NOTE = ("`unsynced_writes` landed while the device's index was not known (before the "
                 "first write that sets it after the log was armed, a reset or a state load), "
                 "so they are on no pen")
PARTIAL_NOTE = ("`partial_writes` merged into a pen whose other bits the log had not seen "
                "written; such a pen reads `complete: false` until they are")
_HEAD = re.compile(
    rf"^{rlua.HEADER} (\S+) seq=(\d+) frame=(-?\d+) total=(\d+) index_writes=(\d+) unsynced=(\d+) "
    r"desyncs=(\d+) rows=(\d+) overflow_rows=(\d+) notifiers=(\d+) data_width=(\d+) "
    # `partial_writes` is optional, as `errors` is (read by name, `callbacks.match_head`):
    # the byte RAMDAC dumps captured as fixtures carry neither
    r"endianness=(\w+) cpu=(\S+)(?: partial_writes=(\d+))?$")
_PEN = re.compile(r"^p ([0-9a-f]+) (\d+) (\d+) (-?\d+) ([0-9a-f]+) ([gd]) (\S+) (\S+) (\S+)$")
_WORD = re.compile(r"^w ([0-9a-f]+) (\d+) (\d+) (-?\d+) ([0-9a-f]+) ([gd]) ([0-9a-f]+) "
                   r"([0-9a-f]+)$")
_ROW = re.compile(r"^(?:([idw]) (\d+) (-?\d+) ([0-9a-f]+) ([gd]) (.*)|x (\d+) (-?\d+) (\w+))$")


# ------------------------------------------------------------------ the tap

def cpu_of(r: mm.PalettePort) -> str | None:
    """The cpu a palette port is written by: the entry's, else the stub's first cpu."""
    return ":" + r.cpu.lstrip(":") if r.cpu else STATE.first_cpu


def owner_of(r: mm.PalettePort) -> dec.Owner:
    """The key the log's record is held under beside the count watches: never a watch's ref."""
    return (f"ramdac:{r.name}", cpu_of(r))


def id_for(r: mm.PalettePort) -> str:
    """The id the Lua registry holds the log under and its files are named by: the two ports on
    their cpu, so two names for one palette port meet one tap."""
    first = r.data_port if r.index_port is None else r.index_port
    return f"ramdac_{tally.id_for(cpu_of(r), first, 1, r.space)}_{r.data_port:x}"


def paths(scratch: Path, log_id: str) -> tuple[Path, Path, Path]:
    """The dump the tap's periodic rewrites, the rows file the tap appends to, and the setters file
    a read with no `pen` writes: the files `clear` removes."""
    return (scratch / f"ramdac-{log_id}.txt", scratch / f"ramdac-{log_id}.rows",
            scratch / f"ramdac-{log_id}.setters.json")


def law(r: mm.PalettePort) -> tuple[Any, ...]:
    """What the tap was composed from: an entry that differs here reads the log wrongly."""
    return (st.bare_tag(r.palette), cpu_of(r), r.index_port, r.data_port, r.order,
            r.component_bits, r.auto_increment, r.pen_base, r.space, r.protocol, r.pen_count,
            r.components_bit_reversed, r.index_flag_mask)


def fresh() -> bool:
    """Whether the machine stands where `start` parked it and has executed nothing since (no
    stop has been read after the park's, and it was not released): Line UP's driver zeroes its
    `sequence` offset as its video starts, before the first instruction, so a log armed here
    knows it."""
    ses, stop = STATE.ses, STATE.last_stop
    return (ses is not None and not ses.running and stop.get("how") == "start"
            and ses.stop_count == stop.get("stop_count"))


# ------------------------------------------------------------------ what the tap wrote

@dataclass(frozen=True)
class PenWrite:
    """A pen as the dump holds it: its writes, the newest one, and its components in r, g, b
    order, None where the log has not seen that component written. A packed protocol's pen
    holds its `word` instead, with the bits of it the log saw written (`known`), and its
    components are `decode`d from that under the entry's law."""

    pen: int
    writes: int
    n: int
    frame: int
    pc: int
    by: str
    components: tuple[int | None, int | None, int | None]
    word: int | None = None
    known: int = 0


def parse_dump(text: str) -> dict[str, Any] | None:
    """A dump as the dumper wrote it, or None when it is not a whole one."""
    whole = callbacks.read_whole(text, _HEAD, with_body=True)
    if whole is None:
        return None
    m, body, errors = whole
    pens: dict[int, PenWrite] = {}
    for ln in body:
        p = _PEN.match(ln)
        w = None if p else _WORD.match(ln)
        line = p or w
        if line is None:
            return None
        pen = int(line.group(1), 16)
        head = (pen, int(line.group(2)), int(line.group(3)), int(line.group(4)),
                int(line.group(5), 16), BY[line.group(6)])
        if w is not None:
            pens[pen] = PenWrite(*head, (None, None, None), int(w.group(7), 16),
                                 int(w.group(8), 16))
            continue
        comps = tuple(None if c == "-" else int(c, 16) for c in (line.group(7), line.group(8),
                                                                  line.group(9)))
        pens[pen] = PenWrite(*head, (comps[0], comps[1], comps[2]))
    names = ("id", "seq", "frame", "total", "index_writes", "unsynced", "desyncs", "rows",
             "overflow_rows", "notifiers", "data_width", "endianness", "cpu", "partial_writes")
    out: dict[str, Any] = {k: (v if k in ("id", "endianness", "cpu") else int(v or 0))
                           for k, v in zip(names, m.groups(), strict=True)}
    out.update(errors)
    out["pens"] = pens
    return out


@dataclass(frozen=True)
class Row:
    """One row of the ordered log: an index write (`kind` `i`, `value` the index), a data write
    (`d`: `pen` None when unsynced, `slot` its place in `order`), a packed protocol's data write
    (`w`: `value` the word, `mask` the bits of it written), or a desync (`x`, `reason`)."""

    kind: str
    n: int
    frame: int
    pc: int = 0
    by: str = ""
    pen: int | None = None
    slot: int | None = None
    value: int = 0
    reason: str = ""
    mask: int = 0
    # WHEN, as a capture row says it: the beam line and the emulated time of the write. None on a
    # row a log armed before the stamp wrote (the rows of a capture taken then).
    line: int | None = None
    time_attoseconds: int | None = None


#: The stamp every event row ends with: the beam line, then the emulated seconds and attoseconds,
#: the attoseconds at their full eighteen digits, so a row cut inside them is no row (as a
#: capture's time is read).
_STAMP = re.compile(r"^(.*) (-?\d+) (\d+) (\d{18})$")


def rows(path: Path) -> Iterator[Row]:
    """Every row of a rows file in order (`rows_of`)."""
    yield from rows_of(files.file_lines(path))


def rows_of(lines: Iterable[str]) -> Iterator[Row]:
    """Every row of `lines` in order, up to the first line of another shape (`mame_capture.rows`
    says why)."""
    for line in lines:
        row = _row(line.rstrip("\n"))
        if row is None:
            return
        yield row


def _row(line: str) -> Row | None:
    """A row, its stamp read off its end when it carries one: the fields before the stamp keep
    the shape and the count every kind has, so a line is either a stamped row or an old one."""
    stamped = _STAMP.match(line)
    if stamped is not None and (row := _fields(stamped.group(1))) is not None:
        beam = int(stamped.group(2))
        return replace(
            row, line=None if beam == callbacks.NO_FRAME else beam,
            time_attoseconds=(int(stamped.group(3)) * capture.ATTOSECONDS_PER_SECOND
                              + int(stamped.group(4))))
    return _fields(line)


def _fields(line: str) -> Row | None:
    m = _ROW.match(line)
    if m is None:
        return None
    if m.group(7) is not None:
        return Row("x", int(m.group(7)), int(m.group(8)), reason=m.group(9))
    kind, n, frame, pc, by = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4), 16), \
        BY[m.group(5)]
    rest = m.group(6).split(" ")
    try:
        if kind == "i" and len(rest) == 1:
            return Row("i", n, frame, pc, by, value=int(rest[0], 16))
        if kind == "d" and len(rest) == 3:
            if rest[0] == "-" and rest[1] == "-":
                return Row("d", n, frame, pc, by, value=int(rest[2], 16))
            return Row("d", n, frame, pc, by, int(rest[0], 16), int(rest[1]), int(rest[2], 16))
        if kind == "w" and len(rest) == 3:
            pen = None if rest[0] == "-" else int(rest[0], 16)
            return Row("w", n, frame, pc, by, pen, value=int(rest[1], 16),
                       mask=int(rest[2], 16))
    except ValueError:
        return None
    return None


def widen(value: int, bits: int) -> int:
    """A component of `bits` bits as the 8 a colour holds, by bit replication: MAME's `palNbit`
    (`pal6bit` is `v << 2 | v >> 4`), and the value itself at 8."""
    v = value & ((1 << bits) - 1)
    out, filled = 0, 0
    while filled < 8:
        out = (out << bits) | v
        filled += bits
    return (out >> (filled - 8)) & 0xFF


def colour(components: tuple[int | None, ...], bits: int) -> str | None:
    """`#rrggbb` from r, g, b components of `bits` bits, or None while one is unknown."""
    if any(c is None for c in components):
        return None
    r, g, b = (widen(c, bits) for c in components if c is not None)
    return f"#{r:02x}{g:02x}{b:02x}"


def _reversed(value: int, bits: int) -> int:
    return int(f"{value:0{bits}b}"[::-1], 2)


def decode(r: mm.PalettePort, word: int, known: int) -> tuple[int | None, int | None, int | None]:
    """A packed protocol's word as r, g, b components: `order`'s components from bit 0 up,
    `component_bits` each, each bit-reversed when the entry says so (Line UP's
    `bitswap<8>(x,7,6,5,0,1,2,3,4)` on a 5-bit component); all None until every colour bit of
    the word has been seen written (`known`)."""
    bits = r.component_bits
    if known & r.colour_mask() != r.colour_mask():
        return None, None, None
    out: list[int | None] = [None, None, None]
    for i, name in enumerate(r.order):
        v = (word >> (i * bits)) & ((1 << bits) - 1)
        out[mm.COMPONENTS.index(name)] = _reversed(v, bits) if r.components_bit_reversed else v
    return out[0], out[1], out[2]


def components_of(p: PenWrite, r: mm.PalettePort) -> tuple[int | None, int | None, int | None]:
    """A dumped pen's r, g, b components, a packed word decoded under `r`'s law."""
    return p.components if p.word is None else decode(r, p.word, p.known)


def replay(path: Path, r: mm.PalettePort) -> Iterator[tuple[Row, str | None]]:
    """Every kept row with the colour its pen held after it (None for an index write, a desync,
    an unsynced write, or a pen with a component or a bit not yet seen): the rows start where
    the log began, so composing them in order is what the tap composed."""
    comps: dict[int, list[int | None]] = {}
    words: dict[int, tuple[int, int]] = {}
    for row in rows(path):
        if row.kind == "w" and row.pen is not None:
            word, known = words.get(row.pen, (0, 0))
            word, known = (word & ~row.mask) | (row.value & row.mask), known | row.mask
            words[row.pen] = (word, known)
            yield row, colour(decode(r, word, known), r.component_bits)
            continue
        if row.kind != "d" or row.pen is None or row.slot is None:
            yield row, None
            continue
        c = comps.setdefault(row.pen, [None, None, None])
        c[mm.COMPONENTS.index(r.order[row.slot])] = row.value
        yield row, colour(tuple(c), r.component_bits)


def _frame(frame: int) -> int | dict[str, Any]:
    return st.unavailable(capture.NO_SCREEN_WHY) if frame == callbacks.NO_FRAME else frame


def _writer(n: int, frame: int, pc: int, by: str, cpu: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"n": n, "frame": _frame(frame), "pc": st.hex_addr(pc), "written_by": by}
    return read.add_symbol(out, pc, cpu) if by == "guest" else out


def pen_fields(p: PenWrite, r: mm.PalettePort, cpu: str | None) -> dict[str, Any]:
    """A pen of the dump as a reply shows it: its colour, whether all three components were seen,
    the raw components (and a packed protocol's word), how many writes it took, and the newest
    of them."""
    comps = components_of(p, r)
    col = colour(comps, r.component_bits)
    out = {"pen": p.pen, "color": st.or_unavailable(col, INCOMPLETE_WHY),
           "complete": col is not None,
           "components": {k: st.or_unavailable(c, UNSEEN_WHY)
                          for k, c in zip(mm.COMPONENTS, comps, strict=True)}}
    if p.word is not None:
        out["word"] = f"{p.word:#x}"
    return {**out, "writes_total": p.writes, "last": _writer(p.n, p.frame, p.pc, p.by, cpu)}


def setters(pens: list[PenWrite], cpu: str | None) -> list[dict[str, Any]]:
    """Who set the pens as they stand: each writer of a pen's newest write, with how many pens it
    set last, most first."""
    counts: dict[tuple[int, str], list[int]] = {}
    for p in pens:
        counts.setdefault((p.pc, p.by), []).append(p.pen)
    ranked = sorted(counts.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    out = []
    for (pc, by), who in ranked:
        item: dict[str, Any] = {"pc": st.hex_addr(pc), "written_by": by, "pens_set": len(who),
                                "which": mpalette.pen_runs(who)}
        out.append(read.add_symbol(item, pc, cpu) if by == "guest" else item)
    return out


def _setters_fields(every: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    """The first `SETTERS_LISTED_MAX` setters, their total, and the file holding them all, written
    whole or not at all. The dump has been read by now: a scratch that refuses the file costs the
    file, said where `setters_path` would be (`st.unavailable`), and never the read."""
    fields: dict[str, Any] = {"setters": every[:SETTERS_LISTED_MAX], "setters_total": len(every)}
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(every), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return {**fields, "setters_path": st.unavailable(str(e))}
    return {**fields, "setters_path": str(path)}


#: Why a row says no line and no time: a log armed before rows carried their stamp wrote it.
UNSTAMPED_WHY = "this row was written before the log's rows carried their line and time"


def _when(row: Row) -> dict[str, Any]:
    """A row's `line` and `time_s`, as a capture row says them (`mame_capture.row_fields`)."""
    if row.time_attoseconds is None:
        return {"line": st.unavailable(UNSTAMPED_WHY), "time_s": st.unavailable(UNSTAMPED_WHY)}
    return {"line": st.or_unavailable(row.line, capture.NO_SCREEN_WHY),
            "time_s": row.time_attoseconds / capture.ATTOSECONDS_PER_SECOND}


#: A pen's colour before all its components were seen, and a component not seen yet.
INCOMPLETE_WHY = "the pen's components have not all been seen written"
UNSEEN_WHY = "no write of this component has been seen"

#: Why a desync row lost the index, by the word its tap logged.
DESYNC_WHY = {
    "reset": "the machine was reset, so the index the device holds is no longer known",
    "load": "a state was loaded, so the index the device holds is no longer known",
    "index_partial": "an index write set only part of an index not yet known, so it stays "
                     "unknown",
}


def row_fields(row: Row, col: str | None, r: mm.PalettePort, cpu: str | None) -> dict[str, Any]:
    """One row as a reply shows it, with WHEN it was written; an index and a data byte are `0x`
    text at the width written (the pen index's digits, the byte's)."""
    if row.kind == "x":
        return {"n": row.n, "frame": _frame(row.frame), **_when(row), "desync": True,
                "why": DESYNC_WHY.get(row.reason, f"the log lost its index ({row.reason})")}
    out = {**_writer(row.n, row.frame, row.pc, row.by, cpu), **_when(row)}
    index_digits = len(f"{r.pen_count - 1:x}")
    value_digits = 2          # a data write is the byte the port took, whatever its bits keep
    if row.kind == "i":
        out["index"] = f"0x{row.value:0{index_digits}x}"
        return out
    if row.kind == "w":
        placed = {"unsynced": True} if row.pen is None else {"pen": row.pen}
        out.update(placed, word=f"{row.value:#x}", mask=f"{row.mask:#x}")
        if row.pen is not None:
            out["color"] = st.or_unavailable(col, INCOMPLETE_WHY)
        return out
    if row.pen is None or row.slot is None:
        out.update(unsynced=True, value=f"0x{row.value:0{value_digits}x}")
        return out
    out.update(pen=row.pen, component=r.order[row.slot], value=f"0x{row.value:0{value_digits}x}",
               color=st.or_unavailable(col, INCOMPLETE_WHY))
    return out


# ------------------------------------------------------------------ palette_log

def check_palette_log(palette_port: str = "", pen: int | None = None,
                      limit: int = LIMIT_DEFAULT, clear: bool = False, arm: bool = False,
                      **_: Any) -> None:
    """`palette_log`'s machine-independent half."""
    inputs.name_word("palette_port", palette_port,
                     "the name of an entry of the loaded manifest's `palette_ports`")
    if pen is not None:
        inputs.pen("pen", pen)
    # ZERO ROWS IS AN ANSWER HERE: the log's account (its counts, its pens, its setters) with no
    # row listed, which is what a caller asks for when the rows are in `rows_path`.
    inputs.count("limit", limit, LIMIT_MAX, " rows", lo=0)
    inputs.check_bool("clear", clear)
    inputs.check_bool("arm", arm)
    if arm and clear:
        raise st.Invalid("bad_argument", "`arm` installs the log and `clear` removes it: give one "
                         "(`palette_log(palette_port=..., arm=True)` to arm)")
    if arm and (pen is not None or limit != LIMIT_DEFAULT):
        raise st.Invalid("bad_argument", "`arm` installs the log and reads nothing, so `pen` and "
                         "`limit`, which choose what to read, would do nothing: "
                         "`palette_log(palette_port=...)` reads once it is armed")
    if clear and (pen is not None or limit != LIMIT_DEFAULT):
        raise st.Invalid("bad_argument", "`clear` removes the log, so `pen` and `limit`, which "
                         "choose what to read, would do nothing")


def _entry(r: mm.PalettePort) -> dict[str, Any]:
    return {"palette_port": r.name, "palette": r.palette, "cpu": cpu_of(r), "space": r.space,
            "protocol": r.protocol,
            "index_port": (st.unavailable(mm.NO_INDEX_PORT_WHY) if r.index_port is None
                           else st.hex_addr(r.index_port)),
            "data_port": st.hex_addr(r.data_port),
            "order": "".join(r.order), "component_bits": r.component_bits,
            "pen_range": [r.pen_base, r.pens().stop - 1]}


def held(r: mm.PalettePort) -> tuple[dec.Owner, dict[str, Any]] | None:
    """The record of the log armed under `r`'s NAME, whatever cpu it was armed on: a reloaded
    manifest that moved the port to another cpu must still reach the tap it armed."""
    return mtap.held(owner_of(r)[0])


def armed(r: mm.PalettePort) -> dict[str, Any] | None:
    """The record of the log armed on `r`, or None; refused when it was armed from an entry the
    loaded manifest no longer states the same way, since the rows would be read under another
    law than the tap composed them with."""
    found = held(r)
    rec = found[1] if found else None
    if rec is not None and law(rec["palette_port"]) != law(r):
        raise st.Invalid("needs_call", f"the log of palette port {r.name!r} was armed from an "
                         "entry the loaded manifest no longer states the same way: "
                         f"`palette_log(palette_port=\"{r.name}\", clear=True)`, then arm it "
                         "again")
    return rec


def palette_log(scratch: Path, palette_port: str, pen: int | None, limit: int,
                clear: bool, arm: bool = False) -> dict[str, Any]:
    """The body of the `palette_log` tool: arm the log (`arm`), read it, or clear it. A read
    never arms: a read of a log nobody armed says which call does."""
    check_palette_log(palette_port, pen, limit, clear, arm)
    r = mm.palette_port(palette_port)
    if pen is not None and pen not in r.pens():
        raise st.Invalid("bad_argument", f"pen {pen} is not one palette port {r.name!r} sets: "
                         f"it sets {r.pen_base}..{r.pens().stop - 1}")
    fields = _entry(r)
    if clear:
        found = held(r)
        removed = mtap.send_remove(scratch, found[0]) if found else None
        return menvelope.envelope({**fields, "cleared": removed is not None, **(removed or {
            "note": "no log was armed on this palette port"})})
    owner = owner_of(r)
    rec = armed(r)
    if rec is None and not arm:
        raise st.Invalid("needs_call", f"no log is armed on palette port {r.name!r}, so there is "
                         f"nothing to read: `palette_log(palette_port=\"{r.name}\", arm=True)` "
                         "arms it")
    if rec is None:
        if r.space == mspace.IO:
            iotaps.check_has_io(owner[1])
        log_id = id_for(r)
        head, rows_path, setters_path = paths(scratch, log_id)
        synced = r.protocol == "sequence" and fresh()
        sent = mtap.send_tap(scratch, owner, log_id,
                             rlua.install_script(log_id, r, head, rows_path, owner[1], synced),
                             rlua.REGISTRY, [head, rows_path, setters_path],
                             addr=r.data_port if r.index_port is None else r.index_port,
                             width=1, path=head, rows_path=rows_path,
                             setters_path=setters_path, palette_port=r)
        if synced:
            sent["synced_at_start"] = True
        return menvelope.envelope({**fields, "armed_now": True, **sent,
                                   "not_proved": _not_proved(r)})
    item, dump = mtap.read_tap(scratch, owner, st.stopped_frame(), False, parse_dump,
                               "logged")
    item.pop("addr", None)
    fields.update(armed_now=False, **item)
    if dump is None:
        return menvelope.envelope({**fields, "not_proved": _not_proved(r)})
    fields["writes_total"] = fields.pop("total")
    fields.update(index_writes=dump["index_writes"], unsynced_writes=dump["unsynced"],
                  desyncs=dump["desyncs"], sees_reset_and_load=dump["notifiers"] == rlua.NOTIFIERS,
                  rows_kept=dump["rows"], overflow_rows=dump["overflow_rows"],
                  rows_max=ROWS_MAX, rows_path=str(rec["rows_path"]))
    if r.packed():
        fields["partial_writes"] = dump["partial_writes"]
    cpu = dump["cpu"]
    written = sorted(dump["pens"].values(), key=lambda p: p.pen)
    shown = [p for p in written if p.pen == pen]
    fields["pens_written"] = mpalette.pen_runs([p.pen for p in written])
    if pen is None:
        fields.update(_setters_fields(setters(written, cpu), Path(rec["setters_path"])))
    else:
        fields["pen_state"] = (pen_fields(shown[0], r, cpu) if shown else st.unavailable(
            f"no write of pen {pen} has been logged since the log was armed"))
    # the newest `limit` rows, placed in the symbol table once kept rather than all of them
    kept: collections.deque[tuple[Row, str | None]] = collections.deque(maxlen=limit)
    kept.extend((row, col) for row, col in replay(rec["rows_path"], r)
                if pen is None or row.pen == pen)
    tail = [row_fields(row, col, r, cpu) for row, col in kept]
    fields["rows"] = tail
    fields["rows_cut"] = dump["overflow_rows"] > 0
    notes = []
    if any(p.by == "debugger" for p in (shown if pen is not None else written)) or any(
            t.get("written_by") == "debugger" for t in tail):
        notes.append(DEBUGGER_NOTE)
    if dump["unsynced"]:
        notes.append(UNSYNCED_NOTE)
    if dump["partial_writes"]:
        notes.append(PARTIAL_NOTE)
    if dump["notifiers"] != rlua.NOTIFIERS:
        notes.append(f"this MAME binds {dump['notifiers']} of the {rlua.NOTIFIERS} notifiers a "
                     "reset and a state load are seen through, so the log may miss one: after it, "
                     "the index the log follows may be the old one until the next index write")
    if notes:
        st.add_note(fields, *notes)
    fields["not_proved"] = _not_proved(r)
    return menvelope.envelope(fields)


def _not_proved(r: mm.PalettePort) -> list[str]:
    return [] if r.status == "proved" else [f"{mm.PALETTE_PORTS}.{r.name}"]


# ------------------------------------------------------------------ who set this pen

def set_by(scratch: Path, palette: str | None, pen: int, live: int) -> dict[str, Any]:
    """`screen_view` pixel mode's third answer: the newest logged write to `pen` of the screen's
    `palette`, joined to the pen's `live` colour (ARGB) read in the same chunk, whose
    `mame_ramdac_lua.dump_lua` wrote the dump this reads. `set_by` unavailable says what is
    missing."""
    man = STATE.manifest
    name = st.bare_tag(palette)
    if man is None:
        return {"set_by": st.unavailable(
            "no manifest is loaded: `gfx_load` a gfx.yaml whose `palette_ports` names this "
            "palette, "
            "then `palette_log(palette_port=..., arm=True)` arms the log that answers who set "
            "a pen")}
    r = next((x for x in man.palette_ports.values() if st.bare_tag(x.palette) == name
              and pen in x.pens()), None)
    if r is None:
        return {"set_by": st.unavailable(
            f"the loaded manifest names no `palette_ports` entry that sets pen {pen} of palette "
            f"{palette}, so no write to it can be logged")}
    try:
        rec = armed(r)
    except st.Invalid as e:
        return {"set_by": st.unavailable(str(e))}
    if rec is None:
        return {"set_by": st.unavailable(
            f"no palette write log is armed on palette port {r.name!r}: `palette_log(palette_port="
            f"\"{r.name}\", arm=True)` arms it, and it records from when the console next reads a "
            "line, so run the frames that set the pen again")}
    # past `armed`, the record's cpu is the entry's, so its owner is the entry's
    item, dump = mtap.read_tap(scratch, owner_of(r), None, False, parse_dump, "logged")
    if dump is None:
        return {"set_by": st.unavailable(item.get("why", (
            f"the log of palette port {r.name!r} has nothing on disk ({item.get('state')})")))}
    p = dump["pens"].get(pen)
    errors = item.get("callback_errors")
    if p is None:
        why = f"no write to pen {pen} since the log of palette port {r.name!r} was armed"
        if clause := callbacks.said(errors, "the log's"):
            why += f"; but {clause}, so a write that set it may not have been logged"
        return {"set_by": st.unavailable(why)}
    out = {"palette_port": r.name, **pen_fields(p, r, dump["cpu"])}
    if errors is not None:
        out["callback_errors"] = errors
    live_col = f"#{live & 0xFFFFFF:06x}"
    fields: dict[str, Any] = {"set_by": out}
    # who wrote and whether the colour moved since are two facts: the note keeps both
    notes = [DEBUGGER_NOTE] if p.by == "debugger" else []
    if out["complete"]:
        out["agrees"] = out["color"] == live_col
        if not out["agrees"]:
            notes.append(
                f"pen {pen} is {live_col} now and its last port write left {out['color']}: "
                "something other than a write to the entry's ports changed the pen since (a "
                "driver that copies pens itself, a Lua `set_pen_color`, a state load)")
            fields["same_color_write"] = _same_colour(rec["rows_path"], r, pen, live_col,
                                                      dump["cpu"])
            fields["rows_cut"] = dump["overflow_rows"] > 0
    else:
        out["agrees"] = st.unavailable(INCOMPLETE_WHY)
    if notes:
        st.add_note(fields, *notes)
    return fields


def _same_colour(path: Path, r: mm.PalettePort, pen: int, col: str,
                 cpu: str | None) -> dict[str, Any] | None:
    """The newest kept data write after which `pen` was `col`, or None."""
    hit: Row | None = None
    for row, after in replay(path, r):
        if row.pen == pen and after == col:
            hit = row
    return (st.unavailable("no kept data write left the pen this colour") if hit is None
            else row_fields(hit, col, r, cpu))
