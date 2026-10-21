"""Doubles shared by this suite's modules, so the same fake is not written twice in two shapes.

A PLAIN MODULE AND NOT THE `conftest.py` beside it: these are helpers a test imports and calls
by name, and the `conftest.py` holds only the one fixture every test gets without asking.
"""

import asyncio
import dataclasses
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gdb_session as g  # noqa: E402
import mame_state as mstate  # noqa: E402

# `map`'s answers, CAPTURED from a live m68k-dual session, never authored: a RAM address, a ROM
# one, and a write-only latch.
MAP_RAM = ("   Read: 200000 logical program == 200000 physical program -> memory@200000\n"
           "  Write: 200000 logical program == 200000 physical program -> memory@200000\n"
           "  Fetch: 200000 logical program == 200000 physical program -> memory@200000\n")
MAP_ROM = ("   Read: 000400 logical program == 000400 physical program -> memory@0\n"
           "  Write: 000400 logical program == 000400 physical program -> unmapped\n"
           "  Fetch: 000400 logical program == 000400 physical program -> memory@0\n")
# A write-only latch: the write side is a handler, the read side is nowhere (captured).
MAP_LATCH = ("   Read: 740000 logical program == 740000 physical program -> unmapped\n"
             "  Write: 740000 logical program == 740000 physical program -> "
             "m68k_dual_state::latch_w\n"
             "  Fetch: 740000 logical program == 740000 physical program -> unmapped\n")


def published(tool: str) -> str:
    """A tool's description as the client receives it, its wrapped lines joined. The server is
    imported here, not at the top: `conftest.py` imports this module for every test."""
    import server as s
    found = [t for t in asyncio.run(s.mcp.list_tools()) if t.name == tool]
    assert len(found) == 1, f"the server registers no tool named {tool}"
    return " ".join((found[0].description or "").split())


def bp_records(*rows: tuple[int, str, int]) -> dict[int, dict[str, Any]]:
    """`STATE.breakpoints` as the server keeps it, one `(index, ref, addr)` per row, each held
    by a declaration on the main cpu the doubles list, and listed under it."""
    return {index: {"owner": (ref, ":maincpu"), "addr": addr, "cpu": ":maincpu"}
            for index, ref, addr in rows}


def blank_session(monkeypatch: Any) -> None:
    """Every field of the module-global `STATE` back to what a brand-new session has.

    NO HAND-WRITTEN LIST, and that is the whole point. Two fixtures named the fields to reset
    one by one, and nothing held either list to what `State` actually carries: a field added
    later leaks from one case into the next in SILENCE, which is the worst way for a suite to
    be wrong, because every case still passes and one of them is measuring the previous one's
    leftovers. It has already happened once. A fresh `State` knows its own fields, so this
    cannot go short.

    `start_seq` is left alone for the same reason `kill`'s own completeness case leaves it:
    it counts sessions rather than describing one, so resetting it would be a lie about how
    many there have been. Everything a fixture wants set to something OTHER than blank is set
    after this, by the fixture, which is where that belongs.
    """
    blank = mstate.State()
    for name, value in vars(blank).items():
        if name == "start_seq":
            continue
        monkeypatch.setattr(mstate.STATE, name, value)


class SessionFields:
    """What every session double holds of `gdb_session.Session`'s own state, so the code reads
    `running` and `broken` as it reads them on a real session, and latches through the real
    method."""

    running = False
    broken: str | None = None
    latch = g.Session.latch
    drain_stop_reply = g.Session.drain_stop_reply


def refs(entries: Any) -> list[str]:
    """The refs of a list of rows that each name a declaration (`start`'s `rearm`)."""
    return [e["ref"] for e in entries]


#: The keys of a row naming a declaration, as the lists and `start`'s `rearm` give it, written
#: out rather than read off `arming.decl_row`, so a key it loses is a red here.
IDENTITY_KEYS = frozenset({"ref", "by", "cpu", "created_at", "origin", "inherited", "age_s"})


def ref_cpu(entries: Any) -> list[tuple[str, str | None]]:
    """Each row's `ref` and `cpu`, the pair that names a declaration in `start`'s `rearm`."""
    return [(e["ref"], e["cpu"]) for e in entries]


def identities(out: dict[str, Any]) -> list[dict[str, Any]]:
    """Every row of a re-arm account, each bucket's (a `note` is not a bucket), refused unless
    it carries every identity key: one call checks the whole account a test drove."""
    rows = [r for v in out.values() if isinstance(v, list) for r in v]
    for r in rows:
        assert set(r) >= IDENTITY_KEYS, r
    return rows


def checked_rearms(monkeypatch: Any) -> None:
    """The three halves of `start`'s re-arm, each wrapped so every account any test drives is
    put through `identities`: one invariant over every path a case reaches, where an assertion
    per case would leave the paths nobody thought to assert on."""
    import mame_comments
    import mame_rearm
    import mame_regpoints

    rearm = mame_rearm.rearm_breakpoints_and_watches
    regpoints, comments = mame_regpoints.rearm, mame_comments.rearm

    def rearm_checked(ses: Any) -> dict[str, Any]:
        out = rearm(ses)
        identities(out)
        return out

    def regpoints_checked(ses: Any, out: dict[str, Any]) -> None:
        regpoints(ses, out)
        identities(out)

    def comments_checked(ses: Any, scratch: Path) -> dict[str, Any]:
        out = comments(ses, scratch)
        identities(out)
        return out

    monkeypatch.setattr(mame_rearm, "rearm_breakpoints_and_watches", rearm_checked)
    monkeypatch.setattr(mame_regpoints, "rearm", regpoints_checked)
    monkeypatch.setattr(mame_comments, "rearm", comments_checked)


def use_table(monkeypatch: Any, cpu: str | None = None, **fields: Any) -> None:
    """`cpu`'s symbol table replaced by the one it held with `fields` over it, each a whole
    field of `gdb_session.SymbolTable` as `start` would have loaded it. `None`, the default, is
    the table that serves every cpu: a one-path start's whose cpu the console did not name."""
    held = mstate.STATE.tables.get(cpu, mstate.NO_TABLE)
    monkeypatch.setitem(mstate.STATE.tables, cpu, dataclasses.replace(held, **fields))


def add_symbol(monkeypatch: Any, name: str, addr: int, cpu: str | None = None) -> None:
    """One more name in `cpu`'s table (`use_table`'s `None` by default)."""
    held = mstate.STATE.tables.get(cpu, mstate.NO_TABLE).table
    use_table(monkeypatch, cpu, table={**held, name: addr})


def reading_session(image: bytes, at: int) -> g.Session:
    """A REAL `Session` whose `read` serves `image` as if it sat at CPU address `at`.

    Everything above `read` (`self_check`, `determinism`, the OUTSIDE refusal) is the code
    under test, not a copy of it. The double honours `addr`: a fake that returned the same
    slice whatever the address would let a check that ignores the base stay green.
    """
    ses = g.Session()
    def read(addr: int, n: int, *, thread: int) -> bytes:
        return image[addr - at : addr - at + n]

    ses.read = read  # type: ignore[method-assign]
    return ses


def fake_mame(tmp_path: Path, *, name: str = "fake-mame", version: str = "") -> Path:
    """A MAME that exits at once, with the console plugin beside it the way a source build
    ships it: `judge` refuses a binary without one before anything is spawned.

    RUNNABLE ON PURPOSE. `start` asks the binary `-listxml` before it boots anything, and that
    call is NOT the emulator, so it is not the one the process double intercepts: it really
    runs this script. Left unreadable-as-a-program it would answer differently depending on
    the host's exec bit, and a double whose behaviour is a property of the filesystem is a
    double that cannot be reasoned about. Exiting 0 with nothing on stdout is a MAME that
    answered no XML, which is the shape `start` has to survive. `version`, the shell a
    `-version` call runs (none: it prints nothing), and `name` serve the ladder's cases.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    binary = tmp_path / name
    answer = f'case "$1" in -version) {version} ;; esac\n' if version else ""
    binary.write_text(f"#!/bin/sh\n{answer}exit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    console = tmp_path / "plugins" / "console"
    console.mkdir(parents=True, exist_ok=True)
    (console / "init.lua").write_text("-- the console plugin's place, not its code\n")
    return binary


def refused(pattern: str, reply: dict[str, Any]) -> dict[str, Any]:
    """A refusal read off the REPLY, with the prose matched: every tool answers `status:
    INVALID` with `code` and `message` rather than raising, so a test that wrapped a call
    in `pytest.raises` reads the envelope instead. The pattern goes first so a multi-line call
    keeps its own shape as the second argument."""
    assert reply["status"] == "INVALID", reply
    assert re.search(pattern, reply["message"]), (pattern, reply["message"])
    return reply


def row_index(row: str) -> int:
    """The index a list row carries: the `%4X` field after the `%c` a disabled row fills with
    `D`, which WIDENS past four digits rather than wrapping, so it is parsed up to the ` @`
    and never sliced."""
    return int(row[1:].split(" @", 1)[0], 16)


def _by_device(title: str, rows: list[str], devices: dict[int, str] | None,
               by_address: bool = False) -> str:
    """A breakpoint or watchpoint list in its captured shape: one `Device '<tag>'` section per
    cpu that holds a row, the sections by tag, which is the captured order for `:maincpu` and
    `:subcpu` and is not known for any other pair. `devices` names the cpu of a row by its
    index; the rest are the main one's. `by_address` orders a section as `bplist` does."""
    where = devices or {}
    if by_address:
        rows = sorted(rows, key=lambda r: int(r.split(" @ ", 1)[1][:6], 16))
    tags = sorted({where.get(row_index(r), ":maincpu") for r in rows})
    return "".join(f"Device '{tag}' {title}:\n"
                   + "".join(r + "\n" for r in rows
                             if where.get(row_index(r), ":maincpu") == tag)
                   for tag in tags) + "\n"


def bplist_answer(rows: list[str], devices: dict[int, str] | None = None) -> str:
    """The console's `bplist` for the rows a double holds, in its captured shape: a section's
    rows by ADDRESS whatever order they were set in (`bplist.by-address.txt`)."""
    if not rows:
        return "No breakpoints currently installed\n\n"
    return _by_device("breakpoints", rows, devices, by_address=True)


def wplist_answer(rows: list[str], devices: dict[int, str] | None = None) -> str:
    """The console's `wplist` for the rows a double holds, in its captured shape."""
    if not rows:
        return "No watchpoints currently installed\n\n"
    return _by_device("program space watchpoints", rows, devices)


def bplist_add(double: Any, addr: int, cond: str = "") -> int:
    """Add a row to `double.bplist_rows` under MAME's breakpoint index and answer it. The index
    is one counter shared by the stub's `Z0` and the console's `bp`, that only increments,
    printed `%c%4X` in `bplist` (`execute_bplist`), so the tenth is `   A` and a clear never
    frees a number for the next breakpoint. The double carries `bp_next_index`."""
    index: int = double.bp_next_index
    double.bp_next_index += 1
    double.bplist_rows.append(f" {index:4X} @ {addr:06X}" + (f" if {cond}" if cond else ""))
    return index


def wplist_add(double: Any, addr: int, length: int, cond: str = "") -> int:
    """Add a row to `double.wplist_rows` under MAME's watchpoint index and answer it: a counter
    of its own (`get_watchpoint_index`), separate from the breakpoints', that only increments,
    printed `%c%4X` in `wplist` (`execute_wplist`), a condition after ` if ` as the console lists
    one (`wplist.condition.txt`). The double carries `wp_next_index`."""
    index: int = double.wp_next_index
    double.wp_next_index += 1
    double.wplist_rows.append(f" {index:4X} @ {addr:06X}-{addr + length - 1:06X} write"
                              + (f" if {cond}" if cond else ""))
    return index


# How the server arms every row (`mame_breakpoints.bp_command`, `wp_command`): the cpu after the
# address, absolute (`bp 0x400::maincpu,<cond>`, `wp 0x2031fc::subcpu,0x4,w`), or none at all.
BP_ARM = re.compile(r"bp (?:0x)?([0-9a-fA-F]+)(?::(:?[^,]+))?(?:,(.*))?")
WP_ARM = re.compile(r"wp (?:0x)?([0-9a-fA-F]+)(?::(:?[^,]+))?,(?:0x)?([0-9a-fA-F]+),w(?:,(.*))?")


def place_row(double: Any, devices: str, index: int, cpu: str | None) -> None:
    """Record the cpu a row was armed on, by its index, where the list double reads it: a row
    named on no cpu, or on the main one, is the main one's (the doubles' visible cpu)."""
    tag = ":" + cpu.lstrip(":") if cpu else ":maincpu"
    if tag != ":maincpu":
        setattr(double, devices, {**(getattr(double, devices, None) or {}), index: tag})


def control_console(double: Any, command: str) -> str | None:
    """The console half every armed row needs, shared by every double that lists them:
    `bp <addr>[:<cpu>][,<cond>]` adds a row spelled as the console lists a conditioned one
    (`    2 @ 000404 if (++temp1)==0`, captured live), a plain one through the double's own
    `breakpoint(addr)` when it has one (a case stands in for the debugger there), `bpclear N`
    drops that row (or answers
    the captured `Invalid breakpoint number N` when no row holds N), `wp <addr>[:<cpu>],<len>,w`
    adds one for a double that lists watchpoints (whose own `monitor` answers `wpclear`), each
    row's cpu kept where the list double reads it, and `print tempA,tempB` answers the counters
    the test moves by hand through `double.temps`, space-separated as the console does. None
    for any other command, so the double's own `monitor` goes on. The double carries `bplist_rows`,
    `bp_next_index` and `temps`; the index is `bplist_add`'s, echoed `%X` as `bpset` and
    `bpclear` print it."""
    if (armed := BP_ARM.fullmatch(command)) is not None:
        addr, index = int(armed.group(1), 16), double.bp_next_index
        if armed.group(3) or not callable(getattr(double, "breakpoint", None)):
            bplist_add(double, addr, armed.group(3) or "")
        else:
            double.breakpoint(addr)       # a plain row, through the double's own stand-in
        if double.bp_next_index > index:
            place_row(double, "bp_devices", index, armed.group(2))
        return captured("bpset.set.txt").replace("Breakpoint 1 ", f"Breakpoint {index:X} ")
    if command.startswith("bpclear "):
        index = int(command[8:], 16)
        gone = next((r for r in double.bplist_rows if row_index(r) == index), None)
        if gone is None:
            return captured("bpclear.invalid.txt").replace(" 7\n", f" {index:X}\n")
        double.bplist_rows = [r for r in double.bplist_rows if row_index(r) != index]
        if hasattr(double, "armed") and " if " not in gone:
            double.armed.append((int(gone.split(" @ ", 1)[1][:6], 16), True))
        return f"Breakpoint {index:X} cleared\n\n"
    if (armed := WP_ARM.fullmatch(command)) is not None and hasattr(double, "wplist_rows"):
        addr, length = int(armed.group(1), 16), int(armed.group(3), 16)
        index = wplist_add(double, addr, length, armed.group(4) or "")
        place_row(double, "wp_devices", index, armed.group(2))
        if hasattr(double, "watchpoints"):
            double.watchpoints.append((addr, length, False))
        return captured("wpset.set.txt").replace("Watchpoint 1 ", f"Watchpoint {index:X} ")
    if command.startswith("print temp"):
        names = command[6:].split(",")
        return " ".join(f"{double.temps.get(int(n[4:]), 0):X}" for n in names) + "\n\n"
    return None


_CAPTURED = Path(__file__).parent / "fixtures" / "console"


def visible_in(cpu_info: dict[str, Any]) -> str | None:
    """The cpu a `cpu_info` reply marks visible, or None when no row marks one (an unread
    `visible` included)."""
    return next((row["cpu"] for row in cpu_info["cpus"] if row["visible"] is True), None)


def ignored_in(cpu_info: dict[str, Any]) -> list[str] | None:
    """The cpus a `cpu_info` reply marks ignored, or None when it could not say: no rows, or
    a row whose listing the console did not answer."""
    if not cpu_info["cpus"] or any(not isinstance(row["ignored"], bool)
                                   for row in cpu_info["cpus"]):
        return None
    return [row["cpu"] for row in cpu_info["cpus"] if row["ignored"] is True]


def captured(name: str) -> str:
    """One captured console answer, by its file name under `fixtures/console/`."""
    return (_CAPTURED / name).read_text()


def rplist_answer(rows: list[tuple[int, str, bool]],
                  devices: dict[int, str] | None = None) -> str:
    """The console's `rplist` for the rows a double holds, in its captured shape: a section
    per cpu that has any, each newest first, the index `%4X` after the `%c` a disabled row
    fills with `D`. `devices` names the cpu of a row by its index; the rest are the main one's."""
    if not rows:
        return captured("rplist.none.txt")
    where = devices or {}
    tags = sorted({where.get(index, ":maincpu") for index, _c, _e in rows})
    return "".join(
        f"Device '{tag}' registerpoints:\n"
        + "".join(f"{' ' if enabled else 'D'}{index:4X} if {cond}\n"
                  for index, cond, enabled in reversed(rows)
                  if where.get(index, ":maincpu") == tag)
        for tag in tags) + "\n"


def regpoint_console(double: Any, command: str) -> str | None:
    """The console half the registerpoints need, every answer in its captured shape: `rpset
    {<cond>}` arms a row under a counter that only increments (and ARMS a condition the
    evaluator refuses, as MAME does), `print {<cond>}` evaluates it, `rpclear N` drops a row or
    names the number no row holds, `rplist` lists. A condition in `double.rp_errors` gets that
    text from BOTH commands (an unknown symbol); one in `double.rp_print_errors` from `print`
    alone (a malformed one). None for any other command. The double carries `rplist_rows` and
    `rp_next_index`."""
    if command == "rplist":
        return rplist_answer(double.rplist_rows, getattr(double, "rp_devices", None))
    braced = re.fullmatch(r"(rpset|print) \{(.*)\}", command)
    if braced is not None:
        verb, cond = braced.groups()
        errors: dict[str, str] = getattr(double, "rp_errors", {})
        if cond in errors:
            return errors[cond]
        if verb == "print":
            print_errors: dict[str, str] = getattr(double, "rp_print_errors", {})
            return print_errors.get(cond, captured("print.braces.false.txt"))
        index: int = double.rp_next_index
        double.rp_next_index += 1
        double.rplist_rows.append((index, cond, True))
        return captured("rpset.set.txt").replace("Registerpoint 1 ", f"Registerpoint {index:X} ")
    if command.startswith("rpclear "):
        index = int(command[8:], 16)
        kept = [r for r in double.rplist_rows if r[0] != index]
        if len(kept) == len(double.rplist_rows):
            return captured("rpclear.invalid.txt").replace(" 7\n", f" {index:X}\n")
        double.rplist_rows = kept
        return captured("rpclear.cleared.txt").replace(" 2 ", f" {index:X} ")
    return None


def debugger_lists(double: Any, command: str) -> str | None:
    """Everything a double's console answers about the debugger's own lists (a control's half,
    the registerpoints, `bplist`), or None so the double's own `monitor` goes on."""
    for half in (control_console, regpoint_console, suspend_console):
        if (answer := half(double, command)) is not None:
            return answer
    if command == "bplist":
        return bplist_answer(double.bplist_rows, getattr(double, "bp_devices", None))
    if command.startswith("bplist :"):
        return one_cpus_list(double.bplist_rows, getattr(double, "bp_devices", None),
                             command.split()[1], bplist_answer, "bplist.sub-none.txt")
    if command == "cpulist":
        # Two cpus, `:maincpu` visible unless the double says `:subcpu` is (both captured).
        sub = getattr(double, "visible_cpu", ":maincpu") == ":subcpu"
        return captured("cpulist.sub-visible.txt" if sub else "cpulist.main-visible.txt")
    return focus_console(double, command)


def one_cpus_list(rows: list[str], devices: dict[int, str] | None, cpu: str,
                  answer: Any, none: str) -> str:
    """`bplist <cpu>` or `wplist <cpu>`: that cpu's section alone, or the captured sentence for
    none naming it (`bplist.sub-none.txt`, `wplist.sub-none.txt`)."""
    where = devices or {}
    mine = [r for r in rows if where.get(row_index(r), ":maincpu") == cpu]
    if not mine:
        return captured(none).replace(":subcpu", cpu)
    return str(answer(mine, where))


_TWO_CPUS = (":maincpu", ":subcpu")


def focus_console(double: Any, command: str) -> str | None:
    """The console's `focus <tag>` and `ignore` over the two captured cpus: `focus` ignores the
    other cpu and, when the one it ignores was visible, leaves the focused one visible, which is
    where MAME stops once it has run until that cpu executes (the frame counter held across it,
    captured). `ignore` with no argument lists what is ignored. A `focus` is found in any
    command of a `;` line, as the console splits it, and takes a tag in either spelling. The
    double carries `ignoring` and `live`."""
    focused = next((c.strip() for c in command.split(";") if c.strip().startswith("focus ")), "")
    if focused:
        tag = ":" + focused[len("focus "):].strip().lstrip(":")
        double.ignoring = [t for t in _TWO_CPUS if t != tag]
        # MAME runs only when the cpu it is LIVE on is ignored; after an `Hc` that is not the
        # visible one (`live`, None meaning the visible one), and then nothing moves.
        live = getattr(double, "live", None) or getattr(double, "visible_cpu", ":maincpu")
        if live in double.ignoring:
            double.visible_cpu = double.live = tag
        return captured("focus.subcpu.txt").replace("':subcpu'", f"'{tag}'")
    if command == "ignore":
        ignoring: list[str] = getattr(double, "ignoring", [])
        if not ignoring:
            return captured("ignore.none.txt")
        return captured("ignore.main-ignored.txt").replace("':maincpu'", f"'{ignoring[0]}'")
    return None


def suspend_console(double: Any, command: str) -> str | None:
    """The console's `suspend` and `resume`, each answer a capture with the tag replaced: with a
    tag in either spelling each sets or clears that cpu's flag, and `suspend` with none lists
    the suspended cpu (only one: MAME refuses to suspend the last cpu that runs, and the
    doubles have two). The double carries `suspending`."""
    verb, _, tag = command.partition(" ")
    if verb not in ("suspend", "resume") or (verb == "resume" and not tag.strip()):
        return None
    suspending: list[str] = getattr(double, "suspending", [])
    if not tag.strip():
        if not suspending:
            return captured("suspend.none.txt")
        return captured("suspend.sub-suspended.txt").replace("':subcpu'", f"'{suspending[0]}'")
    tag = ":" + tag.strip().lstrip(":")
    if verb == "suspend":
        double.suspending = [*suspending, tag] if tag not in suspending else suspending
        return captured("suspend.sub.txt").replace("':subcpu'", f"'{tag}'")
    double.suspending = [t for t in suspending if t != tag]
    return captured("resume.sub.txt").replace("':subcpu'", f"'{tag}'")


def io_board(monkeypatch: Any, ses: Any, spaces: tuple[str, ...] = ("io", "program")) -> None:
    """`ses`'s cpu given an io space, and its console answering `mapi` as a V30 board's did: the
    palette ports 6..7, one map entry, written through its handler, every other port unmapped
    (`mapi.v30-*.txt`; the captured answer is port 6's, and 7 shares its entry)."""
    monkeypatch.setattr(mstate.STATE, "machine_map",
                        {**mstate.STATE.machine_map,
                         "cpus": [{"tag": ":maincpu", "spaces": list(spaces)}]})
    plain = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("mapi "):
            ses.commands.append(command)
            port = int(command[5:].split(":", 1)[0], 16)
            return captured("mapi.v30-6.txt" if port in (6, 7)
                            else "mapi.v30-20-unmapped.txt")
        return str(plain(command, timeout))

    monkeypatch.setattr(ses, "monitor", monitor)


def with_stamps(rows: str, salt: int = 0) -> str:
    """Capture rows of six fields, a row without its line and time, completed with both: the
    line as the no-screen sentinel and a time that differs per row and per `salt`. The fixtures
    that need this hold a live run their builds no longer repeat, and the readers they feed
    take neither field; two salts giving one answer is what shows it."""
    out = []
    for i, line in enumerate(rows.splitlines(keepends=True)):
        head, n, frame, rest = line.split(" ", 3)
        out.append(f"{head} {n} {frame} -1 {salt}.{i:018d} {rest}")
    return "".join(out)


def run_host_lua(chunk: str, cwd: Path | None = None) -> list[str]:
    """`chunk` run by this host's `lua`, as a server script runs in MAME's, against the doubles
    the chunk itself defines: what it printed, a line an event. No interpreter is a failure, never
    a skip, since nothing would have been examined."""
    import shutil
    import subprocess

    import pytest
    lua_bin = shutil.which("lua")
    if lua_bin is None:
        pytest.fail("no `lua` on PATH: these cases run a server script itself, and without an "
                    "interpreter nothing here was examined")
    done = subprocess.run([lua_bin, "-"], input=chunk, capture_output=True, text=True,
                          timeout=10, check=False, cwd=cwd)
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()
