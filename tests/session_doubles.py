"""Doubles shared by this suite's modules."""

import asyncio
import dataclasses
import re
from pathlib import Path
from typing import Any

from scry_core import host_program

from scry_mame import gdb_session as g  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

# `map` answers captured from a live m68k-dual session: RAM, ROM, write-only latch.
MAP_RAM = ("   Read: 200000 logical program == 200000 physical program -> memory@200000\n"
           "  Write: 200000 logical program == 200000 physical program -> memory@200000\n"
           "  Fetch: 200000 logical program == 200000 physical program -> memory@200000\n")
MAP_ROM = ("   Read: 000400 logical program == 000400 physical program -> memory@0\n"
           "  Write: 000400 logical program == 000400 physical program -> unmapped\n"
           "  Fetch: 000400 logical program == 000400 physical program -> memory@0\n")
MAP_LATCH = ("   Read: 740000 logical program == 740000 physical program -> unmapped\n"
             "  Write: 740000 logical program == 740000 physical program -> "
             "m68k_dual_state::latch_w\n"
             "  Fetch: 740000 logical program == 740000 physical program -> unmapped\n")


def published(tool: str) -> str:
    # Imported here: `conftest.py` imports this module for every test.
    from scry_mame import server as s
    found = [t for t in asyncio.run(s.mcp.list_tools()) if t.name == tool]
    assert len(found) == 1, f"the server registers no tool named {tool}"
    return " ".join((found[0].description or "").split())


def documented(tool: str) -> str:
    """What a reader finds for `tool` past its description: its family page and REFERENCE.md."""
    from scry_mame import mcp as mame_mcp
    root = Path(__file__).resolve().parent.parent
    family = next(f for f, tools in mame_mcp.ROSTER.families if tool in tools)
    pages = (root / "docs" / "reference" / f"{family.lower()}.md", root / "REFERENCE.md")
    return " ".join(" ".join(p.read_text(encoding="utf-8").split()) for p in pages)


def bp_records(*rows: tuple[int, str, int]) -> dict[int, dict[str, Any]]:
    return {index: {"owner": (ref, ":maincpu"), "addr": addr, "cpu": ":maincpu"}
            for index, ref, addr in rows}


def blank_session(monkeypatch: Any) -> None:
    """Every field of `STATE` back to a brand-new session's, except `start_seq`."""
    blank = mstate.State()
    for name, value in vars(blank).items():
        if name == "start_seq":
            continue
        monkeypatch.setattr(mstate.STATE, name, value)


class SessionFields:
    """The `gdb_session.Session` state every session double holds, latching via the real method."""

    running = False
    broken: str | None = None
    latch = g.Session.latch
    drain_stop_reply = g.Session.drain_stop_reply


def refs(entries: Any) -> list[str]:
    return [e["ref"] for e in entries]


#: Written out rather than read off `arming.decl_row`, so a key it loses is a red here.
IDENTITY_KEYS = frozenset({"ref", "by", "cpu", "created_at", "origin", "inherited", "age_s"})


def ref_cpu(entries: Any) -> list[tuple[str, str | None]]:
    return [(e["ref"], e["cpu"]) for e in entries]


def identities(out: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [r for v in out.values() if isinstance(v, list) for r in v]
    for r in rows:
        assert set(r) >= IDENTITY_KEYS, r
    return rows


def checked_rearms(monkeypatch: Any) -> None:
    """Wrap `start`'s re-arm halves so every account a test drives goes through `identities`."""
    from scry_mame import comments as mame_comments
    from scry_mame import rearm as mame_rearm
    from scry_mame import regpoints as mame_regpoints

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
    """`cpu`'s symbol table with `fields` of `gdb_session.SymbolTable` replaced; `None` is the
    table serving every cpu (a one-path start)."""
    held = mstate.STATE.tables.get(cpu, mstate.NO_TABLE)
    monkeypatch.setitem(mstate.STATE.tables, cpu, dataclasses.replace(held, **fields))


def add_symbol(monkeypatch: Any, name: str, addr: int, cpu: str | None = None) -> None:
    held = mstate.STATE.tables.get(cpu, mstate.NO_TABLE).table
    use_table(monkeypatch, cpu, table={**held, name: addr})


def reading_session(image: bytes, at: int) -> g.Session:
    """A REAL `Session` whose `read` serves `image` as if it sat at CPU address `at`."""
    ses = g.Session()
    def read(addr: int, n: int, *, thread: int) -> bytes:
        return image[addr - at : addr - at + n]

    ses.read = read  # type: ignore[method-assign]
    return ses


def fake_mame(tmp_path: Path, *, name: str = "fake-mame", version: str = "") -> Path:
    """A MAME that exits at once, with the console plugin beside it. `start` really runs it.
    `version` is the Python statement it runs when asked `-version`."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    answer = f"if sys.argv[1:2] == ['-version']:\n    {version}\n" if version else ""
    binary = host_program.write(tmp_path / name, f"import os, sys, time\n{answer}sys.exit(0)\n")
    console = tmp_path / "plugins" / "console"
    console.mkdir(parents=True, exist_ok=True)
    (console / "init.lua").write_text("-- the console plugin's place, not its code\n")
    return binary


def rewrite_mame(binary: str, body: str) -> None:
    """The fake MAME at `binary` made to run the Python `body`, its plugins kept beside it."""
    host_program.write(Path(binary).with_suffix(""), f"import os, sys, time\n{body}\n")


def prints_file(path: Path) -> str:
    """Python that copies `path`'s bytes to stdout as they are."""
    return f"sys.stdout.buffer.write(open({str(path)!r}, 'rb').read())"


def refused(pattern: str, reply: dict[str, Any]) -> dict[str, Any]:
    """A refusal read off the REPLY, which tools return rather than raise."""
    assert reply["status"] == "INVALID", reply
    assert re.search(pattern, reply["message"]), (pattern, reply["message"])
    return reply


def row_index(row: str) -> int:
    # Parsed, not sliced: an index widens past four digits.
    return int(row[1:].split(" @", 1)[0], 16)


def _by_device(title: str, rows: list[str], devices: dict[int, str] | None,
               by_address: bool = False) -> str:
    """A breakpoint or watchpoint list, one `Device` section per cpu (default main)."""
    where = devices or {}
    if by_address:
        rows = sorted(rows, key=lambda r: int(r.split(" @ ", 1)[1][:6], 16))
    tags = sorted({where.get(row_index(r), ":maincpu") for r in rows})
    return "".join(f"Device '{tag}' {title}:\n"
                   + "".join(r + "\n" for r in rows
                             if where.get(row_index(r), ":maincpu") == tag)
                   for tag in tags) + "\n"


def bplist_answer(rows: list[str], devices: dict[int, str] | None = None) -> str:
    if not rows:
        return "No breakpoints currently installed\n\n"
    return _by_device("breakpoints", rows, devices, by_address=True)


def wplist_answer(rows: list[str], devices: dict[int, str] | None = None) -> str:
    if not rows:
        return "No watchpoints currently installed\n\n"
    return _by_device("program space watchpoints", rows, devices)


def bplist_add(double: Any, addr: int, cond: str = "") -> int:
    """Add a row to `double.bplist_rows`; the counter only increments, so a clear frees nothing."""
    index: int = double.bp_next_index
    double.bp_next_index += 1
    double.bplist_rows.append(f" {index:4X} @ {addr:06X}" + (f" if {cond}" if cond else ""))
    return index


def wplist_add(double: Any, addr: int, length: int, cond: str = "") -> int:
    """Add a row to `double.wplist_rows`; its counter is separate from the breakpoints'."""
    index: int = double.wp_next_index
    double.wp_next_index += 1
    double.wplist_rows.append(f" {index:4X} @ {addr:06X}-{addr + length - 1:06X} write"
                              + (f" if {cond}" if cond else ""))
    return index


# How the server arms every row: the cpu after the address, absolute, or none.
BP_ARM = re.compile(r"bp (?:0x)?([0-9a-fA-F]+)(?::(:?[^,]+))?(?:,(.*))?")
WP_ARM = re.compile(r"wp (?:0x)?([0-9a-fA-F]+)(?::(:?[^,]+))?,(?:0x)?([0-9a-fA-F]+),w(?:,(.*))?")


def place_row(double: Any, devices: str, index: int, cpu: str | None) -> None:
    tag = ":" + cpu.lstrip(":") if cpu else ":maincpu"
    if tag != ":maincpu":
        setattr(double, devices, {**(getattr(double, devices, None) or {}), index: tag})


def control_console(double: Any, command: str) -> str | None:
    """`bp`, `bpclear`, `wp` and `print tempA,tempB` for a double that lists rows, else None."""
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
    return next((row["cpu"] for row in cpu_info["cpus"] if row["visible"] is True), None)


def ignored_in(cpu_info: dict[str, Any]) -> list[str] | None:
    if not cpu_info["cpus"] or any(not isinstance(row["ignored"], bool)
                                   for row in cpu_info["cpus"]):
        return None
    return [row["cpu"] for row in cpu_info["cpus"] if row["ignored"] is True]


def captured(name: str) -> str:
    return (_CAPTURED / name).read_text()


def rplist_answer(rows: list[tuple[int, str, bool]],
                  devices: dict[int, str] | None = None) -> str:
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
    """`rpset`, `print`, `rpclear` and `rplist`. `rpset` ARMS a condition the evaluator refuses,
    as MAME does; `rp_errors` fails both commands, `rp_print_errors` `print` alone."""
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
    for half in (control_console, regpoint_console, suspend_console):
        if (answer := half(double, command)) is not None:
            return answer
    if command == "bplist":
        return bplist_answer(double.bplist_rows, getattr(double, "bp_devices", None))
    if command.startswith("bplist :"):
        return one_cpus_list(double.bplist_rows, getattr(double, "bp_devices", None),
                             command.split()[1], bplist_answer, "bplist.sub-none.txt")
    if command == "cpulist":
        sub = getattr(double, "visible_cpu", ":maincpu") == ":subcpu"
        return captured("cpulist.sub-visible.txt" if sub else "cpulist.main-visible.txt")
    return focus_console(double, command)


def one_cpus_list(rows: list[str], devices: dict[int, str] | None, cpu: str,
                  answer: Any, none: str) -> str:
    where = devices or {}
    mine = [r for r in rows if where.get(row_index(r), ":maincpu") == cpu]
    if not mine:
        return captured(none).replace(":subcpu", cpu)
    return str(answer(mine, where))


_TWO_CPUS = (":maincpu", ":subcpu")


def focus_console(double: Any, command: str) -> str | None:
    focused = next((c.strip() for c in command.split(";") if c.strip().startswith("focus ")), "")
    if focused:
        tag = ":" + focused[len("focus "):].strip().lstrip(":")
        double.ignoring = [t for t in _TWO_CPUS if t != tag]
        # After an `Hc` the live cpu may not be the visible one (`live`, None meaning visible).
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
    """`ses`'s cpu given an io space, its console answering `mapi` as a V30 board did."""
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
    """Capture rows of six fields completed with a no-screen line and a per-row, per-`salt` time."""
    out = []
    for i, line in enumerate(rows.splitlines(keepends=True)):
        head, n, frame, rest = line.split(" ", 3)
        out.append(f"{head} {n} {frame} -1 {salt}.{i:018d} {rest}")
    return "".join(out)


def run_host_lua(chunk: str, cwd: Path | None = None) -> list[str]:
    """`chunk` run by this host's `lua`: what it printed, a line an event."""
    import shutil
    import subprocess

    import pytest
    lua_bin = shutil.which("lua")
    if lua_bin is None:
        pytest.skip("this host has no `lua` on PATH: these cases run the server's script "
                    "itself, so there is nothing to run here")
    done = subprocess.run([lua_bin, "-"], input=chunk, capture_output=True, text=True,
                          timeout=10, check=False, cwd=cwd)
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()
