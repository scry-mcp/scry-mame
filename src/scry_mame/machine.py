"""The machine's inventory, gathered once at `start` and served from a cache.

Two emulator sources, because neither is complete: `-listxml` alone has a cpu's clock, a
screen's rotation and a ROM's crc and sha1; the live Lua channel alone has the shares, the
regions' sizes, the address map and a cpu's `type` (its `clock` reads back nil there).
`symbol_coverage` is a third source, the caller's own symbol table. Each section names its
source in `sources`.

A cpu is a device MAME gives a `debug`, i.e. one that executes. The live half identifies cpus
that way because a build that cannot answer `-listxml` must still produce a session; `MAP_NOTE`
states the cost. The boot harness owns the live half whole, so two routes cannot diverge. The
dump is sorted because Lua's `pairs` has no order.
"""

from __future__ import annotations

import copy
import re
import subprocess
from pathlib import Path
from typing import Any
from xml.parsers import expat

from scry_core import narrowing, prose
from scry_core.reply_contract import unavailable

from scry_mame import cpus, inputs, lua_source, read
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import state as st
from scry_mame.state import STATE

# The inventory file in the session's scratch: not a capture, never handed to the caller.
DUMP_NAME = "machine.txt"
BEGIN = "MAME_MCP_MACHINE_BEGIN"
END = "MAME_MCP_MACHINE_END"
FAILED = "MAME_MCP_MACHINE_ERROR"


_CPU = re.compile(r"^CPU (\S+) type=(\S+) name=(.*) spaces=(\S*)$")
_REGS = re.compile(r"^REGS (\S+) (\S*)$")
_SPACE = re.compile(r"^SPACE (\S+) (\S+) data_width=(\d+) endianness=(\S+) entries=(\d+) "
                    r"address_mask=([0-9a-f]+)$")
_ENTRY = re.compile(r"^ENTRY (\S+) (\S+) (\d+) start=([0-9a-f]+) end=([0-9a-f]+) "
                    r"mirror=([0-9a-f]+) mask=([0-9a-f]+) share=(\S+) region=(\S+) "
                    r"region_offset=(\d+)$")
_BLOCK = re.compile(r"^(REGION|SHARE) (\S+) size=(\d+) bytewidth=(\d+) endianness=(\S+)$")
_SCREEN = re.compile(r"^SCREEN (\S+) width=(\d+) height=(\d+) refresh=([0-9.]+)$")
_VIEW = re.compile(r"^(VIEW|SNAPVIEW)(?: (.*))?$")
VIEWS, SNAPVIEW = "views", "snapview"

# An empty gather presents every live section empty, never omits some (that reads as "none").
LIVE_SECTIONS = ("cpus", "spaces", "address_map", "regions", "shares", "screens")


def harness(dump: Path) -> str:
    """The gather, as Lua text for the boot script."""
    return lua_source.render("inventory", begin=BEGIN, end=END, failed=FAILED, dump=str(dump))


def _none_if_absent(name: str) -> str | None:
    """The dump's `-` is not a tag: an absent field stays absent, never a literal dash."""
    return None if name == "-" else name


def parse(text: str) -> dict[str, Any]:
    """The dump's lines as the live half of the inventory; raises `LookupError` on a bad dump.

    A dump with no `END` line is refused: a truncated inventory reads as a small machine.
    """
    if text.startswith(FAILED):
        raise LookupError(f"the boot harness could not read the machine: "
                          f"{text[len(FAILED):].strip()}")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != BEGIN:
        raise LookupError("the dump does not open with the gather's own first line, so "
                          "nothing here is the machine's inventory")
    if lines[-1] != END:
        raise LookupError("the dump does not close with the gather's own last line, so it "
                          "was cut off and what it holds is a fragment")
    found: dict[str, list[dict[str, Any]]] = {name: [] for name in LIVE_SECTIONS}
    registers: dict[str, list[str]] = {}
    views: list[str] = []
    snapview = ""
    for line in lines[1:-1]:
        if (m := _CPU.match(line)) is not None:
            spaces = m.group(4).split(",") if m.group(4) else []
            found["cpus"].append({"tag": m.group(1), "type": m.group(2), "name": m.group(3),
                                  "spaces": spaces})
        elif (m := _REGS.match(line)) is not None:
            registers[m.group(1)] = m.group(2).split(",") if m.group(2) else []
        elif (m := _SPACE.match(line)) is not None:
            found["spaces"].append({"cpu": m.group(1), "space": m.group(2),
                                    "data_width_bits": int(m.group(3)),
                                    "endianness": m.group(4),
                                    "entries": int(m.group(5)),
                                    "address_mask": st.hex_addr(int(m.group(6), 16))})
        elif (m := _ENTRY.match(line)) is not None:
            entry: dict[str, Any] = {
                "cpu": m.group(1), "space": m.group(2), "index": int(m.group(3)),
                "start": st.hex_addr(int(m.group(4), 16)), "end": st.hex_addr(int(m.group(5), 16)),
            }
            if (mirror := int(m.group(6), 16)):
                entry["mirror"] = st.hex_addr(mirror)
            if (address_mask := int(m.group(7), 16)):
                entry["address_mask"] = st.hex_addr(address_mask)
            # The gather writes share and region as the driver declared them; the tables
            # carry `full_tag`, and the other spelling matches nothing.
            if (share := _none_if_absent(m.group(8))) is not None:
                entry["share"] = full_tag(share)
            if (region := _none_if_absent(m.group(9))) is not None:
                entry["region"] = full_tag(region)
                entry["region_offset"] = int(m.group(10))
            found["address_map"].append(entry)
        elif (m := _BLOCK.match(line)) is not None:
            found["regions" if m.group(1) == "REGION" else "shares"].append(
                {"tag": m.group(2), "size": int(m.group(3)), "bytewidth": int(m.group(4)),
                 "endianness": m.group(5)})
        elif (m := _SCREEN.match(line)) is not None:
            found["screens"].append({"tag": m.group(1), "width": int(m.group(2)),
                                     "height": int(m.group(3)),
                                     "refresh_hz": float(m.group(4))})
        elif (m := _VIEW.match(line.strip())) is not None:
            # A nameless view is skipped, not a reason to refuse the inventory.
            if not (name := (m.group(2) or "").strip()):
                continue
            if m.group(1) == "VIEW":
                views.append(name)
            else:
                snapview = name
        else:
            raise LookupError(f"the dump carries a line the gather does not write: {line!r}")
    # Every session runs under `-debug`, so zero cpus means the discriminator failed, and
    # the zero must not read as a verdict.
    if not found["cpus"]:
        raise LookupError("the gather found no device that executes, so it recognised no cpu "
                          "on a machine that is running one: nothing here is an inventory")
    return {**found, cpus.CPU_REGISTERS: registers, VIEWS: views, SNAPVIEW: snapview}


# MAME's own `-listxml`, run against THIS session's binary: each repository ships a narrow
# build, so the machine list is that binary's. It is launched early and collected after the
# boot, inside the wait for the gdbstub, so the bound is the caller's own `wait`. Only a
# system this build lacks refuses the start; any other failure leaves the XML sections absent
# with the reason quoted.
ABSENT_SYSTEM_RC = 5
ABSENT_SYSTEM_TEXT = "No matching machines found"
# Sections only `-listxml` backs, and the shared ones with the word a clash is reported in.
XML_ONLY = ("rom_files",)
SHARED_SECTIONS = {"cpus": "cpu", "screens": "screen"}
# Rows come from the caller's symbol table, hence `symbols`.
SYMBOL_SECTION = "symbol_coverage"
SYMBOL_SOURCE = "symbols"

# Caveats owed on every answer: where the map's boundary is, and that a range is not fixed.
MAP_NOTE = ("the address map is the map of the machine's EXECUTING devices, which is what MAME "
            "gives a debugger: a device that only exposes an address space of its own is not in "
            "it, though its shares and regions are")
BANKING_NOTE = ("the map reported is the STATICALLY CONFIGURED one: a banked range answers for "
                "whichever bank is selected at the time, so a range here is what the machine was "
                "wired with and not a promise about what is behind it right now")


def full_tag(tag: str) -> str:
    """One spelling per device: `-listxml` says `maincpu`, the live channel `:maincpu`, and the
    absolute one wins because every other tool takes it."""
    return tag if tag.startswith(":") else f":{tag}"


def parse_listxml(text: bytes, system: str) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """The cpus, screens and ROM files of ONE machine out of `-listxml`, and the sentence
    saying what was dropped (empty if nothing).

    `<binary> <system> -listxml` answers that machine plus a `<machine isdevice="yes">` per
    device it is built from, which may carry chips and ROMs of their own, so only the asked
    machine's rows are taken and a document without it is refused. An attribute MAME did not
    write stays absent (a `nodump` ROM has no crc), never filled with a fabricated zero.
    """
    found = _no_xml()
    parser = expat.ParserCreate()
    inside = [False]
    seen: list[str] = []
    untagged: list[str] = []

    def opened(name: str, attrs: dict[str, str]) -> None:
        if name == "machine":
            seen.append(attrs.get("name", ""))
            inside[0] = attrs.get("name") == system
            return
        if not inside[0]:
            return
        # A tag is optional in MAME's DTD. Filled from nothing it would be the bare `:`, which
        # matches nothing live and leaves a phantom row, so an untagged row is dropped and counted.
        if name == "chip" and attrs.get("type") == "cpu":
            if (tag := attrs.get("tag")) is None:
                untagged.append("cpu")
                return
            cpu: dict[str, Any] = {"tag": full_tag(tag), "name": attrs.get("name", "")}
            if (clock := attrs.get("clock")) is not None:
                cpu["clock_hz"] = int(clock)
            found["cpus"].append(cpu)
        elif name == "display":
            if (tag := attrs.get("tag")) is None:
                untagged.append("screen")
                return
            screen: dict[str, Any] = {"tag": full_tag(tag)}
            for key, attr in (("width", "width"), ("height", "height")):
                if (value := attrs.get(attr)) is not None:
                    screen[key] = int(value)
            if (refresh := attrs.get("refresh")) is not None:
                screen["refresh_hz"] = float(refresh)
            if (rotate := attrs.get("rotate")) is not None:
                screen["rotation"] = int(rotate)
            if (kind := attrs.get("type")) is not None:
                screen["type"] = kind
            found["screens"].append(screen)
        elif name == "rom":
            # Size is decimal and offset hex: the DTD says only CDATA, and the data agrees
            # with the live region sizes only under this reading.
            rom: dict[str, Any] = {"name": attrs.get("name", ""), "size": int(attrs["size"])}
            for key in ("crc", "sha1", "status"):
                if (value := attrs.get(key)) is not None:
                    # MAME's `status` is the dump's; a reply's `status` is the envelope's
                    rom["dump_status" if key == "status" else key] = value
            if (region := attrs.get("region")) is not None:
                rom["region"] = full_tag(region)
            if (offset := attrs.get("offset")) is not None:
                rom["offset"] = int(offset, 16)
            found["rom_files"].append(rom)

    def closed(name: str) -> None:
        if name == "machine":
            inside[0] = False

    parser.StartElementHandler = opened
    parser.EndElementHandler = closed
    try:
        parser.Parse(text, True)
    except expat.ExpatError as e:
        raise LookupError(f"`-listxml` did not answer XML this could read: {e}") from None
    except ValueError as e:
        # A misspelled number raises out of the handler through `Parse`; it answers like
        # unreadable XML so `start` survives.
        raise LookupError(f"a value in it is not the number this reads: {e}") from None
    if system not in seen:
        raise LookupError(f"its document carries no <machine name={system!r}>: it describes "
                          f"{prose.counted(len(seen), 'machine')}, none of them the one asked "
                          "about, so nothing in it is about this board")
    # A silently short section cannot be told from a board with one fewer device.
    n = len(untagged)
    dropped = ("" if not untagged else
               f"{prose.counted(n, 'row')} of `-listxml` ({', '.join(sorted(set(untagged)))}) "
               f"{prose.agrees(n, 'carries', 'carry')} no `tag` and "
               f"{prose.agrees(n, 'was', 'were')} dropped: nothing could join "
               f"{prose.agrees(n, 'it', 'them')} to the live machine, and a device that cannot be "
               "named is not one this can report")
    return found, dropped


#: The running process, or None with the sentence saying why it could not start.
Asked = tuple["subprocess.Popen[bytes] | None", str]
Listed = tuple[dict[str, list[dict[str, Any]]], str]


def _no_xml() -> dict[str, list[dict[str, Any]]]:
    """Every XML-backed section, present and empty."""
    return {"cpus": [], "screens": [], "rom_files": []}


def _without_xml(binary: str, system: str, why: str) -> str:
    """The one consequence sentence shared by every way `-listxml` can fail."""
    return (f"`{Path(binary).name} {system} -listxml` {why}, so the sections only it backs "
            f"({', '.join(XML_ONLY)}, and the clock and rotation) are empty here and "
            "describe nothing")


def ask_listxml(binary: str, system: str) -> Asked:
    """Start `-listxml` on this session's binary and return at once."""
    try:
        return subprocess.Popen([binary, system, "-listxml"], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE), ""
    except (OSError, ValueError) as e:
        return None, _without_xml(binary, system,
                                  f"could not be run ({e.__class__.__name__}: {e})")


def listxml(asked: Asked, binary: str, system: str, seconds: float) -> Listed:
    """Collect and read the answer to `ask_listxml`.

    Raises `Invalid` for a system this build does not carry. Any other failure returns empty
    sections and a sentence quoting the exit code and what the binary said.

    `seconds` is the caller's boot `wait`: a query silent after that is broken, not slow, and
    is killed so no process leaks.
    """
    proc, refused = asked
    if proc is None:
        return _no_xml(), refused
    try:
        out, err = proc.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return _no_xml(), _without_xml(binary, system,
            f"had not answered within {seconds:g} s, the whole boot's wait, so it was "
            "killed")
    said = (err or out).decode("utf-8", "replace").strip()
    if proc.returncode == ABSENT_SYSTEM_RC and ABSENT_SYSTEM_TEXT in said:
        raise st.Invalid("bad_argument",
            f"this MAME does not carry {system!r}: `{Path(binary).name} {system} -listxml` "
            f"answered exit code {proc.returncode} and said `{said}`. Each repository ships "
            "its own narrow build, so the systems are this binary's", exit_code=proc.returncode)
    if proc.returncode != 0:
        # Reduced by meaning: a head slice keeps what printed first, not the `error` line.
        return _no_xml(), _without_xml(binary, system,
            f"failed with exit code {proc.returncode} and said `{_why_it_failed(said)}`")
    try:
        return parse_listxml(out, system)
    except LookupError as e:
        return _no_xml(), f"`{Path(binary).name} {system} -listxml` answered, but {e}"


_COMPLAINT = re.compile(r"error|fatal|warning|cannot|could not|unable|no such|not found",
                        re.IGNORECASE)


def _why_it_failed(said: str) -> str:
    """The lines of a failed run that say why, plus the last line; no complaint means whole."""
    lines = [line.strip() for line in said.splitlines() if line.strip()]
    if not lines:
        return said
    kept = [line for line in lines if _COMPLAINT.search(line)]
    if lines[-1] not in kept:
        kept.append(lines[-1])
    return " / ".join(kept) if kept else said


def merge(live_rows: list[dict[str, Any]], xml_rows: list[dict[str, Any]],
          what: str) -> tuple[list[dict[str, Any]], list[str]]:
    """One section out of the two sources, joined on the device tag.

    A field the sources spell differently is reported in the note with both values; the field
    carries the live one (the running board), without judging which is correct. A row only one
    source has keeps only that source's fields.
    """
    rows: dict[str, dict[str, Any]] = {}
    clashes: list[str] = []
    # XML first, so the live half overwrites it.
    for source, source_rows in (("-listxml", xml_rows), ("live", live_rows)):
        for row in source_rows:
            held = rows.setdefault(row["tag"], {})
            for key, value in row.items():
                if key in held and held[key] != value:
                    clashes.append(
                        f"the two sources disagree about {what} {row['tag']}'s {key}: "
                        f"{value!r} from {source} and {held[key]!r} from the other; the "
                        "field carries the live machine's, because that is the board running")
                held[key] = value
    return list(rows.values()), clashes


STALE_NOTE = ("this is what the machine WAS when `start` read it, and nothing re-reads it: if "
              "the emulator has since died the session block says `alive: false` while these "
              "sections still describe the board that was running")


def cache(scratch: Path, static: tuple[dict[str, list[dict[str, Any]]], str]) -> dict[str, Any]:
    """The inventory `start` caches: sections, the source of each, and the boundary notes.

    The `-listxml` half arrives gathered so its caller-side failure refuses the start early.
    """
    sections, live_failure = live(scratch)
    listed, xml_failure = static
    notes = [MAP_NOTE, BANKING_NOTE, STALE_NOTE]
    sources: dict[str, list[str]] = {name: ["live"] for name in LIVE_SECTIONS}
    sources |= {name: ["-listxml"] for name in XML_ONLY}
    sources[SYMBOL_SECTION] = [SYMBOL_SOURCE]
    for name, one in SHARED_SECTIONS.items():
        sections[name], clashes = merge(sections[name], listed[name], one)
        sources[name] = ["live", "-listxml"]
        notes += clashes
    for name in XML_ONLY:
        sections[name] = listed[name]
    notes += [note for note in (live_failure, xml_failure) if note]
    return {**sections, "sources": sources, "note": st.join_notes(*notes)}



def live(scratch: Path) -> tuple[dict[str, Any], str]:
    """The live half of the inventory and its note.

    A failed gather does not kill `start`: the sections come back empty and the note says why,
    so a missing section is not mistaken for a machine that has none.
    """
    dump = scratch / DUMP_NAME
    try:
        text = dump.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ({name: [] for name in LIVE_SECTIONS},
                f"the boot harness wrote no inventory ({e.__class__.__name__}: {e}), so every "
                "section the live machine backs is empty here and describes nothing")
    try:
        return parse(text), ""
    except LookupError as e:
        return ({name: [] for name in LIVE_SECTIONS},
                f"the boot harness's inventory could not be read: {e}")


# Every list section is bounded by the readers' own ceiling; `counts` keeps the full count so
# a cut is visible.
SECTIONS = (*LIVE_SECTIONS, *XML_ONLY)
# Sections `cpu=` narrows; the rest are the board's.
PER_CPU = ("cpus", "spaces", "address_map")


def _of_cpu(section: str, row: dict[str, Any], tag: str) -> bool:
    """A cpu row is its own tag; every other row names its cpu."""
    return bool(row["tag" if section == "cpus" else "cpu"] == tag)


def select(cached: dict[str, Any], cpu: str) -> tuple[dict[str, Any], str]:
    """The cached inventory narrowed to one cpu (either tag spelling), or whole."""
    if not inputs.cpu_given(cpu):
        return cached, ""
    wanted = cpus.match_tag(cpu, [row["tag"] for row in cached["cpus"]])
    narrowed = {name: ([row for row in rows if _of_cpu(name, row, wanted)]
                       if name in PER_CPU else rows)
                for name, rows in cached.items() if name in SECTIONS}
    return {**cached, **narrowed}, wanted


UNNAMED_TABLE_WHY = "the table was given with no cpu named, which is all that attributes a class"
NO_BASE_WHY = "the bases do not disambiguate this class (CODE, or one resident where the map says)"


def symbol_coverage(only: str = "") -> list[dict[str, Any]]:
    """One row per symbol class of each cpu's table (`only`'s alone when given).

    The span is `find`'s own (`read.CLASS_SPAN`). `base` is unavailable, not absent, when
    the bases do not disambiguate the class, so its `why` shows.
    """
    rows = []
    for cpu, table in STATE.tables.items():
        if only and cpu != only:
            continue
        for klass in sorted(table.class_span):
            lo, hi = table.class_span[klass]
            base = table.bases.get(klass)
            rows.append({
                "class": klass,
                "cpu": cpu or unavailable(UNNAMED_TABLE_WHY),
                "span": {"from": st.hex_addr(lo), "length": hi - lo + 1, **read.CLASS_SPAN},
                "symbols": len(gs.rows_in_class(table.table, table.classes, klass)),
                "base": (st.hex_addr(base) if base is not None
                         else unavailable(NO_BASE_WHY)),
            })
    return rows


NO_CLASSES_NOTE = ("`symbol_coverage` is empty: this session's symbol table carries no classes "
                   "(a YAML table has none, and a session started without symbols has no table "
                   "at all), so there is no span to report and none is invented")


MAP_SECTIONS: tuple[str, ...] = (*SECTIONS, SYMBOL_SECTION)
#: The board's shape; `rom_files` is a ROM audit's question, not a debugging session's.
DEFAULT_SECTIONS = frozenset(MAP_SECTIONS) - {"rom_files"}
MAP_HOW = "sections=[...] names the sections to answer"


def check_machine_map(sections: list[str] | None = None, **_: Any) -> list[str]:
    """The sections `machine_map` answers; no machine needed."""
    return narrowing.sections(sections, MAP_SECTIONS, DEFAULT_SECTIONS)


def machine_map(cpu: str = "", sections: list[str] | None = None) -> dict[str, Any]:
    """The body of the `machine_map` tool: the cached inventory, narrowed and bounded.

    The reply is a deep copy so a caller cannot rewrite the cache. `truncated` is a boolean
    for the reason beside `read.LOG_LIMIT_MAX`.
    """
    asked = check_machine_map(sections)
    if not STATE.machine_map:
        st.no_machine()
    chosen, wanted = select(STATE.machine_map, cpu)
    # One bounding rule for every list section, `symbol_coverage` included.
    rows = {name: symbol_coverage(wanted) if name == SYMBOL_SECTION else chosen[name]
            for name in asked}
    shown = {name: copy.deepcopy(items[:read.LOG_LIMIT_MAX]) for name, items in rows.items()}
    # Replies name a cpu `cpu`, as `cpu_info` does; the cache keeps `tag`.
    # The cache keeps the offsets as numbers to compute with; a reply writes them as addresses.
    for name, key in (("address_map", "region_offset"), ("rom_files", "offset")):
        if name in shown:
            shown[name] = [{**row, key: st.hex_addr(row[key])} if key in row else row
                           for row in shown[name]]
    if "cpus" in shown:
        shown["cpus"] = [{"cpu": row["tag"], **{k: v for k, v in row.items() if k != "tag"}}
                         for row in shown["cpus"]]
    note = st.join_notes(chosen["note"], None if shown.get(SYMBOL_SECTION, True)
                         else NO_CLASSES_NOTE)
    reply: dict[str, Any] = {
        **shown,
        "counts": {name: len(items) for name, items in rows.items()},
        "truncated": any(len(shown[name]) < len(rows[name]) for name in rows),
        "sources": {n: copy.deepcopy(v) for n, v in chosen["sources"].items() if n in asked},
        **({"note": note} if note is not None else {}),
        **narrowing.omission([n for n in MAP_SECTIONS if n not in asked], MAP_HOW),
    }
    reply = st.merged(reply, read.frame_fields())
    reply["cpu"] = wanted or unavailable(st.NO_CPU_NAMED_WHY)
    return menvelope.envelope(reply)
