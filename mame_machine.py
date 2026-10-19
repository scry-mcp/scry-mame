"""THE MACHINE'S INVENTORY: what the board IS, gathered once at `start` and served from a cache.

TWO EMULATOR SOURCES, because neither is complete. MAME's `-listxml` is the only one with a
cpu's clock, a screen's rotation and a ROM file's crc and sha1; the live machine's Lua channel
is the only one with the memory shares, the regions' sizes, the address map and a cpu's `type`
(the device's shortname, `m68000`), a device's `clock` reading back nil there. A THIRD source
is neither: `symbol_coverage` comes off the caller's own symbol table, and is named `symbols`
for it. So each SECTION of the reply names the source behind it, and `sources` has an entry
for every one of them.

A CPU IS A DEVICE MAME GIVES A `debug`, which is the one it gives a device that EXECUTES. The
live half identifies its own cpus that way rather than reading `-listxml`, because a build that
cannot answer `-listxml` must still produce a session; the cost is that a device merely exposing
an address space of its own falls outside the map, which `MAP_NOTE` says out loud.

THE BOOT HARNESS OWNS THE LIVE HALF, whole. The console route at the park reaches the same data
and costs a step; one route owns it because a gather split between two is where two accounts of
one fact diverge.

THE DUMP IS SORTED: `pairs` has no order in Lua, so an unsorted one differs run to run and
nothing downstream can be compared to anything.

The contract a caller reads is the tool's own description and `REFERENCE.md`; it is not
repeated here.
"""

from __future__ import annotations

import copy
import re
import subprocess
from pathlib import Path
from typing import Any
from xml.parsers import expat

from scry_core import narrowing, prose

import mame_cpus as cpus
import mame_envelope as menvelope
import mame_inputs as inputs
import mame_read as read
import mame_state as st
import mame_transport as transport
from mame_state import STATE

# WHERE THE BOOT HARNESS LEAVES THE INVENTORY: a file in the session's own scratch, which
# dies with the session. It is not a capture and never reaches the caller as a path.
DUMP_NAME = "machine.txt"
BEGIN = "MAME_MCP_MACHINE_BEGIN"
END = "MAME_MCP_MACHINE_END"
FAILED = "MAME_MCP_MACHINE_ERROR"

# THE GATHER, and every part of it runs inside a `pcall`. This chunk is the FIRST thing in the
# one `-autoboot_script` the server writes, and a raise here would abort the whole script:
# the throttle harness below it would never install and the caller's own harness would never
# run. An inventory is worth none of that, so a failure writes its message into the dump and
# the rest of the boot carries on. `%%` is a literal per cent for Lua's `string.format`;
# `%(...)s` is this module's.
MACHINE_LUA = """local function mame_mcp_inventory()
  local out = {}
  local function add(s) out[#out + 1] = s end
  local function sorted(t)
    local keys = {}
    for k in pairs(t) do keys[#keys + 1] = k end
    table.sort(keys)
    return keys
  end
  -- MAME gives an entry's missing share or region as nil or as ""; neither is a tag, so both
  -- dump as the one spelling of absent.
  local function dash_if_absent(v)
    if v == nil or v == "" then return "-" end
    return v
  end
  add("%(begin)s")
  local devices = manager.machine.devices
  local cpus = {}
  for _, tag in ipairs(sorted(devices)) do
    if devices[tag].debug ~= nil then cpus[#cpus + 1] = tag end
  end
  for _, tag in ipairs(cpus) do
    local dev = devices[tag]
    local names = sorted(dev.spaces)
    add(string.format("CPU %%s type=%%s name=%%s spaces=%%s", tag, dev.shortname, dev.name,
                      table.concat(names, ",")))
    -- The console's names for this cpu's registers: its symbol table takes each state entry.
    local regs = sorted(dev.state)
    add(string.format("REGS %%s %%s", tag, table.concat(regs, ",")))
    for _, sname in ipairs(names) do
      local space = dev.spaces[sname]
      local entries = space.map.entries
      add(string.format("SPACE %%s %%s data_width=%%d endianness=%%s entries=%%d "
                        .. "address_mask=%%x", tag, sname, space.data_width,
                        tostring(space.endianness), #entries, space.address_mask))
      for i = 1, #entries do
        local e = entries[i]
        add(string.format("ENTRY %%s %%s %%d start=%%x end=%%x mirror=%%x mask=%%x share=%%s "
                          .. "region=%%s region_offset=%%d",
                          tag, sname, i, e.address_start, e.address_end, e.address_mirror,
                          e.address_mask, dash_if_absent(e.share), dash_if_absent(e.region),
                          e.region_offset or 0))
      end
    end
  end
  local mem = manager.machine.memory
  for _, tag in ipairs(sorted(mem.regions)) do
    local r = mem.regions[tag]
    add(string.format("REGION %%s size=%%d bytewidth=%%d endianness=%%s", tag, r.size,
                      r.bytewidth, tostring(r.endianness)))
  end
  for _, tag in ipairs(sorted(mem.shares)) do
    local s = mem.shares[tag]
    add(string.format("SHARE %%s size=%%d bytewidth=%%d endianness=%%s", tag, s.size,
                      s.bytewidth, tostring(s.endianness)))
  end
  local screens = manager.machine.screens
  for _, tag in ipairs(sorted(screens)) do
    local sc = screens[tag]
    add(string.format("SCREEN %%s width=%%d height=%%d refresh=%%.6f", tag, sc.width,
                      sc.height, sc.refresh))
  end
  add("%(end)s")
  return out
end
local ok, err = pcall(function()
  local f = assert(io.open(%(dump)s, "w"))
  for _, line in ipairs(mame_mcp_inventory()) do f:write(line .. "\\n") end
  f:close()
end)
if not ok then
  local f = io.open(%(dump)s, "w")
  if f then f:write("%(failed)s " .. tostring(err) .. "\\n") f:close() end
end
"""

_CPU = re.compile(r"^CPU (\S+) type=(\S+) name=(.*) spaces=(\S*)$")
_REGS = re.compile(r"^REGS (\S+) (\S*)$")
_SPACE = re.compile(r"^SPACE (\S+) (\S+) data_width=(\d+) endianness=(\S+) entries=(\d+) "
                    r"address_mask=([0-9a-f]+)$")
_ENTRY = re.compile(r"^ENTRY (\S+) (\S+) (\d+) start=([0-9a-f]+) end=([0-9a-f]+) "
                    r"mirror=([0-9a-f]+) mask=([0-9a-f]+) share=(\S+) region=(\S+) "
                    r"region_offset=(\d+)$")
_BLOCK = re.compile(r"^(REGION|SHARE) (\S+) size=(\d+) bytewidth=(\d+) endianness=(\S+)$")
_SCREEN = re.compile(r"^SCREEN (\S+) width=(\d+) height=(\d+) refresh=([0-9.]+)$")

# The sections the live half owns, named here so an empty gather can present every one of them
# empty rather than presenting some and omitting others, which reads as "this board has none".
LIVE_SECTIONS = ("cpus", "spaces", "address_map", "regions", "shares", "screens")


def harness(dump: Path) -> str:
    """The gather, as the Lua text that goes into the one boot script this server writes."""
    return MACHINE_LUA % {"begin": BEGIN, "end": END, "failed": FAILED,
                          "dump": transport.lua_string(str(dump))}


def _none_if_absent(name: str) -> str | None:
    """The dump spells an absent share or region `-`, which is not a tag: a field neither
    source backs is absent from the reply, never the literal dash."""
    return None if name == "-" else name


def parse(text: str) -> dict[str, Any]:
    """The dump's lines as the live half of the inventory, or the refusal the caller reports.

    A dump with no `END` line is a gather that was cut off, and it is REFUSED rather than
    parsed: a truncated inventory is indistinguishable from a small machine, which is exactly
    the shape that reads as a verdict when it is a failure.
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
            # A BLOCK UNDER THE TAG THE `regions` AND `shares` TABLES CARRY (`full_tag`): the
            # gather writes an entry's share bare, and its region bare or full as the driver
            # declared it, and an entry compared with a table under the other spelling finds
            # nothing there.
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
        else:
            raise LookupError(f"the dump carries a line the gather does not write: {line!r}")
    # A MACHINE WITH NO EXECUTING DEVICE IS AN INSTRUMENT THAT EXAMINED NOTHING, not a board
    # with no cpu: every session here runs under `-debug`, so a device that executes has a
    # `debug`, and an empty list means the discriminator failed rather than that the board is
    # empty. Said as a refusal so the zero can never be read as a verdict.
    if not found["cpus"]:
        raise LookupError("the gather found no device that executes, so it recognised no cpu "
                          "on a machine that is running one: nothing here is an inventory")
    return {**found, cpus.CPU_REGISTERS: registers}


# THE OTHER SOURCE: MAME's own `-listxml`, run against THIS session's binary and no other,
# because each repository ships its own narrow build and the machine list is that binary's.
#
# ASKED EARLY, COLLECTED LATE. It is launched before the rest of the judging and read back when
# the boot is over, so it runs inside the seconds the boot spends waiting for the gdbstub:
# dead time, in which it costs nothing, and no constant had to be invented to bound it. The
# bound is the caller's own `wait`, a query still silent after a whole board has booted being
# broken rather than slow.
#
# One failure REFUSES the start, a system this build does not carry, because that is the
# caller's mistake. Every other leaves `start` working with the XML sections absent and the
# reason quoted: a debug session must not be blocked on an inventory.
ABSENT_SYSTEM_RC = 5
ABSENT_SYSTEM_TEXT = "No matching machines found"
# The sections `-listxml` is the only source for, and the ones both sources back, each with
# the word a disagreement about one of its rows is reported in.
XML_ONLY = ("rom_files",)
SHARED_SECTIONS = {"cpus": "cpu", "screens": "screen"}
# THE THIRD CHANNEL, and the one section it backs. Neither emulator source knows anything about
# it: the rows come from the symbol table the CALLER handed `start`, which is why the word here
# is `symbols`, the name that argument already has. It is named in `sources` like the other two
# because the section is a section by every other measure this module applies -- it is in
# `counts`, it is in the truncation test, the summary line counts it -- and a section whose
# provenance is the one thing missing is the case a reader cannot tell from an oversight.
SYMBOL_SECTION = "symbol_coverage"
SYMBOL_SOURCE = "symbols"

# WHAT A READER HAS TO BE TOLD ABOUT THE ANSWER ITSELF, whatever the board turns out to be.
# The first says where the map's boundary is; the second is the one caveat that makes a range
# in it something other than a fixed fact.
MAP_NOTE = ("the address map is the map of the machine's EXECUTING devices, which is what MAME "
            "gives a debugger: a device that only exposes an address space of its own is not in "
            "it, though its shares and regions are")
BANKING_NOTE = ("the map reported is the STATICALLY CONFIGURED one: a banked range answers for "
                "whichever bank is selected at the time, so a range here is what the machine was "
                "wired with and not a promise about what is behind it right now")


def full_tag(tag: str) -> str:
    """ONE spelling for one device. `-listxml` names a tag relative to the machine's root
    (`maincpu`), and the live channel names a device absolutely (`:maincpu`) but an address map
    entry's block as the driver declared it, so a reader given both would see two devices where
    the board has one, and nothing would line up. The absolute spelling wins because it is the
    one every other tool here already takes."""
    return tag if tag.startswith(":") else f":{tag}"


def parse_listxml(text: bytes, system: str) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """The cpus, the screens and the ROM files of ONE machine out of MAME's own `-listxml`.

    SCOPED TO THE MACHINE ASKED FOR, which is why this takes a system name.
    `<binary> <system> -listxml` does NOT answer one machine: it answers that machine plus a
    `<machine isdevice="yes">` for every device it is built out of, which on a real board is
    most of the document. A device machine may carry chips and
    ROMs of its own, so a walk of every `<chip>` in the document would attribute somebody
    else's hardware to this board, and silently. NEITHER BUILD ON THIS HOST HAS SUCH A
    DEVICE, so that half has no case to be seen red against and is right by construction; what
    IS checked is the other half, that a document not carrying the machine asked for is
    refused rather than answered empty.

    An attribute MAME did not write is ABSENT here, never filled: a ROM whose dump nobody has
    carries `dump_status="nodump"` (MAME's own `status`) and no crc and no sha1 at all, and a zero
    crc would be a fabrication about the one thing this section exists to carry.

    Answers the sections AND the sentence saying what it had to drop, which is empty when it
    dropped nothing.
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
        # A TAG IS OPTIONAL IN MAME'S OWN DTD, on a chip and a display exactly as on a rom's
        # region, so all three are guarded the same way. Filled from an absent attribute the
        # tag would come out as the bare `:`, which is not a device: it matches nothing on the
        # live side, so the real cpu silently loses its clock and a phantom row appears
        # beside it carrying one. An unnameable row is DROPPED, and the note says how many.
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
            # SIZE IS DECIMAL AND OFFSET IS HEX. MAME's DTD calls both CDATA and says no
            # more, so the reading is settled against the data: a board's graphics ROMs would
            # overlap each other under the other one, and a region's size agrees with the live
            # channel's only under this one.
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
        # A VALUE MAME WROTE IN A SHAPE THIS DOES NOT READ. Every number above is converted
        # from an attribute, and a `clock` or an `offset` spelled some other way would raise
        # from inside the handler, out through `Parse`, and take the whole `start` with it.
        # It is the same class of failure as unreadable XML and it answers the same way: the
        # XML half is absent, with the reason, and the session comes up.
        raise LookupError(f"a value in it is not the number this reads: {e}") from None
    if system not in seen:
        raise LookupError(f"its document carries no <machine name={system!r}>: it describes "
                          f"{prose.counted(len(seen), 'machine')}, none of them the one asked "
                          "about, so nothing in it is about this board")
    # A ROW MAME DID NOT NAME IS DROPPED, AND SAYING SO IS THE POINT: a section quietly one
    # row short cannot be told from a board with one fewer device.
    n = len(untagged)
    dropped = ("" if not untagged else
               f"{prose.counted(n, 'row')} of `-listxml` ({', '.join(sorted(set(untagged)))}) "
               f"{prose.agrees(n, 'carries', 'carry')} no `tag` and "
               f"{prose.agrees(n, 'was', 'were')} dropped: nothing could join "
               f"{prose.agrees(n, 'it', 'them')} to the live machine, and a device that cannot be "
               "named is not one this can report")
    return found, dropped


#: What `ask_listxml` hands back: the process, still running, or None with the sentence saying
#: why it could not even be started. One value, because the two cannot both be meaningful.
Asked = tuple["subprocess.Popen[bytes] | None", str]
#: What `listxml` answers: the sections it backs, and the sentence saying what it could not read.
Listed = tuple[dict[str, list[dict[str, Any]]], str]


def _no_xml() -> dict[str, list[dict[str, Any]]]:
    """The XML half when there is none: every section it backs, present and empty."""
    return {"cpus": [], "screens": [], "rom_files": []}


def _without_xml(binary: str, system: str, why: str) -> str:
    """The one sentence for `this source did not answer`, so the three ways it can fail cannot
    describe their consequence differently."""
    return (f"`{Path(binary).name} {system} -listxml` {why}, so the sections only it backs "
            f"({', '.join(XML_ONLY)}, and the clock and rotation) are empty here and "
            "describe nothing")


def ask_listxml(binary: str, system: str) -> Asked:
    """Put the question to THIS session's binary and RETURN AT ONCE, without waiting for it."""
    try:
        return subprocess.Popen([binary, system, "-listxml"], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE), ""
    except (OSError, ValueError) as e:
        return None, _without_xml(binary, system,
                                  f"could not be run ({e.__class__.__name__}: {e})")


def listxml(asked: Asked, binary: str, system: str, seconds: float) -> Listed:
    """Collect the answer to `ask_listxml`, whenever it comes, and read it.

    Raises `Invalid` for the one failure that is the caller's, a system this build does not
    carry. Every other failure comes back as empty sections and a sentence QUOTING the exit
    code and what the binary said, because a start that works today without this must keep
    working, and a section that is silently missing cannot be told from a machine that has none.

    `seconds` is the caller's own boot `wait`, not a constant of this module: by the time it
    has elapsed a whole arcade board was supposed to have booted, so a query that has not
    answered is broken rather than slow. A process that outlives it is killed rather than left
    behind, because this server may not leak one.
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
            f"had not answered {seconds:g} s after the boot began, which is longer than the "
            "whole machine took to come up, so it was killed")
    said = (err or out).decode("utf-8", "replace").strip()
    if proc.returncode == ABSENT_SYSTEM_RC and ABSENT_SYSTEM_TEXT in said:
        raise st.Invalid("bad_argument",
            f"this MAME does not carry {system!r}: `{Path(binary).name} {system} -listxml` "
            f"answered exit code {proc.returncode} and said `{said}`. Each repository ships "
            "its own narrow build, so the systems are this binary's", exit_code=proc.returncode)
    if proc.returncode != 0:
        # REDUCED BY MEANING, NEVER BY POSITION. A head slice of a diagnostic keeps whatever
        # the tool happened to print first, and what a reader needs is the line that says
        # `error` or `fatal`, which on a noisy channel is nowhere near the start.
        return _no_xml(), _without_xml(binary, system,
            f"failed with exit code {proc.returncode} and said `{_why_it_failed(said)}`")
    try:
        return parse_listxml(out, system)
    except LookupError as e:
        return _no_xml(), f"`{Path(binary).name} {system} -listxml` answered, but {e}"


_COMPLAINT = re.compile(r"error|fatal|warning|cannot|could not|unable|no such|not found",
                        re.IGNORECASE)


def _why_it_failed(said: str) -> str:
    """The lines of a failed run that say WHY, and the last line whatever it says.

    A tool's diagnostics print as they happen and its verdict prints at the end, so a slice
    that keeps the first N characters keeps neither reliably. What is kept here is chosen by
    what the lines MEAN, with the final line always, because the cause is often the last thing
    said. An output that complains about nothing comes back whole: there is nothing to reduce.
    """
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

    A field both sources back and spell differently is REPORTED in the note, with both values
    and where each came from. The field carries the LIVE one, because that half is read off the
    machine actually running while `-listxml` describes what the build says a machine of that
    name is; nothing here decides which is CORRECT.

    A row only one source has keeps only the fields that source backs.
    """
    rows: dict[str, dict[str, Any]] = {}
    clashes: list[str] = []
    # The XML goes in first and the live half overwrites it, which is what makes the
    # paragraph above true of the data and not only of the docstring.
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


# WHAT A CACHE CANNOT KNOW ABOUT ITSELF: the machine it describes may have died since. The
# session block says `alive: false` when it has, and this says why that is not a contradiction.
STALE_NOTE = ("this is what the machine WAS when `start` read it, and nothing re-reads it: if "
              "the emulator has since died the session block says `alive: false` while these "
              "sections still describe the board that was running")


def cache(scratch: Path, static: tuple[dict[str, list[dict[str, Any]]], str]) -> dict[str, Any]:
    """The inventory `start` caches, whole: the sections, the source that backs each one, and
    the note a reader needs about the answer's own boundaries.

    The `-listxml` half arrives already gathered, because the ONE failure of it that is the
    caller's -- a system this build does not carry -- has to refuse the start before an
    emulator is spawned, and that is judged with the rest of the arguments.
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
    """The live half of the inventory as `start` caches it, and the note that travels with it.

    A gather that did not happen is NOT an error `start` dies of: the session is the point and
    an inventory is not, so the sections come back empty and the note says what went wrong, in
    the gather's own words, so a missing section is never mistaken for a machine that has none.
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


# EVERY LIST SECTION IS BOUNDED, because a reply with no ceiling is a bug this project has
# recorded before, more than once. The convention is the readers' own listing ceiling rather than a
# number invented here, and what makes a cut honest is that `counts` keeps the FULL count
# beside it and `truncated` names the section: a short list that says nothing about being
# short is the shape that gets acted on as if it were the whole machine.
SECTIONS = (*LIVE_SECTIONS, *XML_ONLY)
# Which sections belong to ONE cpu, so `cpu=` can narrow them; the rest are the board's.
PER_CPU = ("cpus", "spaces", "address_map")


def _of_cpu(section: str, row: dict[str, Any], tag: str) -> bool:
    """Which key names the cpu a row belongs to: a cpu IS its tag, everything else names one."""
    return bool(row["tag" if section == "cpus" else "cpu"] == tag)


def select(cached: dict[str, Any], cpu: str) -> tuple[dict[str, Any], str]:
    """The cached inventory narrowed to one cpu, or whole. The tag is taken in either
    spelling, as `read_block` takes a block's, and the full one is what comes back."""
    if not inputs.cpu_given(cpu):
        return cached, ""
    wanted = cpus.match_tag(cpu, [row["tag"] for row in cached["cpus"]])
    narrowed = {name: ([row for row in rows if _of_cpu(name, row, wanted)]
                       if name in PER_CPU else rows)
                for name, rows in cached.items() if name in SECTIONS}
    return {**cached, **narrowed}, wanted


#: A coverage row's `cpu` when its table was given with no cpu named, and its `base` when the
#: bases do not place the class.
UNNAMED_TABLE_WHY = "the table was given with no cpu named, which is all that attributes a class"
NO_BASE_WHY = "the bases do not disambiguate this class (CODE, or one resident where the map says)"


def symbol_coverage(only: str = "") -> list[dict[str, Any]]:
    """Which parts of the machine this session's SYMBOLS speak for, one row per class of each
    cpu's table (`only`'s alone when it names one), and the `cpu` whose table it is: the one
    `start` was given it for, which is all that attributes a class to a cpu, since a linker map
    carries none.

    THE SPAN IS `find`'s OWN, constant and note together (`mame_read.CLASS_SPAN`), because two
    tools answering two different spans for one class is worse than either answer.

    `base` is unavailable, and deliberately not absent, when the bases do not disambiguate the
    class: a class resident where the map says, and CODE, have no base here, and its `why` is the
    informative answer while an absent field would read as an oversight.
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
                "cpu": cpu or st.unavailable(UNNAMED_TABLE_WHY),
                "span": {"from": st.hex_addr(lo), "length": hi - lo + 1, **read.CLASS_SPAN},
                "symbols": sum(1 for k in table.classes.values() if k == klass),
                "base": (st.hex_addr(base) if base is not None
                         else st.unavailable(NO_BASE_WHY)),
            })
    return rows


NO_CLASSES_NOTE = ("`symbol_coverage` is empty: this session's symbol table carries no classes "
                   "(a YAML table has none, and a session started without symbols has no table "
                   "at all), so there is no span to report and none is invented")


#: Every section `machine_map` answers, in reply order.
MAP_SECTIONS: tuple[str, ...] = (*SECTIONS, SYMBOL_SECTION)
#: What a map answers when asked for no section: the board's shape. Left out: `rom_files`, a
#: crc and a sha1 per chip, the question of a ROM audit and not of a debugging session.
DEFAULT_SECTIONS = frozenset(MAP_SECTIONS) - {"rom_files"}
#: How a map that left a section out asks for it.
MAP_HOW = "sections=[...] names the sections to answer"


def check_machine_map(sections: list[str] | None = None, **_: Any) -> list[str]:
    """`machine_map`'s machine-independent half, and the sections it answers."""
    return narrowing.sections(sections, MAP_SECTIONS, DEFAULT_SECTIONS)


def machine_map(cpu: str = "", sections: list[str] | None = None) -> dict[str, Any]:
    """The body of the `machine_map` tool: the cache `start` built, narrowed and bounded.

    The reply is a deep COPY: handing back the cache's own rows let a caller that touched one
    rewrite the cache through it, and the next call then answered something else, which a tool
    declaring `idempotentHint` may not allow.

    `truncated` is a boolean for the reason that lives beside `mame_read.LOG_LIMIT_MAX`; which
    section was cut needs no field, a section shorter than its own `counts` entry being the one.
    """
    asked = check_machine_map(sections)
    if not STATE.machine_map:
        st.no_machine()
    chosen, wanted = select(STATE.machine_map, cpu)
    # ONE RULE OVER EVERY LIST SECTION, `symbol_coverage` included. Bounding it apart meant
    # its own slice, its own count, its own term in the truncation test and its own place in
    # the reply: the same decision written twice, and the second copy is the one that gets
    # forgotten when the ceiling moves.
    rows = {name: symbol_coverage(wanted) if name == SYMBOL_SECTION else chosen[name]
            for name in asked}
    shown = {name: copy.deepcopy(items[:read.LOG_LIMIT_MAX]) for name, items in rows.items()}
    # A CPU IS NAMED `cpu` IN EVERY ROW OF THE REPLY, its own row too, as `cpu_info` names it:
    # the cache keeps `tag`, which the inventory's parsers and readers key by.
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
        "note": note,
        **narrowing.omission([n for n in MAP_SECTIONS if n not in asked], MAP_HOW),
    }
    reply = st.merged(reply, read.frame_fields())
    reply["cpu"] = wanted or st.unavailable(st.NO_CPU_NAMED_WHY)
    return menvelope.envelope(reply)
