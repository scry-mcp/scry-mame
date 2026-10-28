"""The server's guarantees: what start judges before the emulator exists."""

from __future__ import annotations

import ast
import io
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from scry_core import host_program

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server_support import (  # noqa: E402
    CFG_OK,
    FIXTURES,
    _boot_args,
    _console,
    _ConsoleSession,
    _ExitingProcess,
    _install,
    _masked,
    _never_spawns,
    _RecordingSession,
    _refusal_text,
    _running,
    _RunningSession,
    _stub_boot,
    _StubProcess,
)
from session_doubles import (  # noqa: E402
    captured,
    fake_mame,  # noqa: E402
    reading_session,
    refused,
    rewrite_mame,
    use_table,  # noqa: E402
)

import gdb_session as g  # noqa: E402
import mame_docs as mdocs  # noqa: E402
import mame_envelope as menvelope  # noqa: E402
import mame_files as files  # noqa: E402
import mame_inputs as inputs
import mame_launch as launch
import mame_read as read  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


def test_altered_counts_both_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Protocol writes and console writes go into the SAME counter."""
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "console_writes", 0)
    assert menvelope.session_block()["altered"] is False
    monkeypatch.setattr(mstate.STATE, "console_writes", 1)
    block = menvelope.session_block()
    assert block["altered"] is True
    assert menvelope.session_block(True)["altering_writes"] == 1
    assert block["omitted"] == ["altering_writes", "console"]
    assert "MODIFIED" in block["note"]
    assert list(menvelope.envelope({})) == ["status"], "the boundary adds the block, once"


def test_startup_leaves_no_state_in_the_servers_directory() -> None:
    """MAME writes `cfg/` and `nvram/` into its cwd, and that cwd was the SHARED tool's own."""
    here = Path(s.__file__).resolve().parent
    for leftover in ("cfg", "nvram"):
        assert not (here / leftover).exists(), (
            f"{leftover}/ inside the server: one project's state in a shared tool"
        )


def test_every_tool_this_server_promises_is_actually_registered() -> None:
    """`mcp.tool()` returns the function unchanged."""
    registered = sorted(t.name for t in s.mcp._tool_manager.list_tools())
    assert registered == sorted([
        "breakpoint_at", "declaration_clear", "declaration_list", "close", "debug", "disassemble",
        "focus", "cpu_info", "input", "log", "log_wait", "lua", "find", "history", "machine_map",
        "memdump",
        "perform", "perform_export", "palette", "screen_view", "gfx_view", "gfx_locate",
        "gfx_load", "gfx_blits",
        "gfx_blit_source", "palette_log", "gfx_film", "gfx_sweep", "gfx_draft",
        "screen_signature", "drive", "series_capture",
        "image_compare", "audio_compare", "screen_map_find", "screen_map_write",
        "read_memory", "read_block", "record", "audio_record", "registers", "regpoint_add",
        "reset", "resume", "run_for", "trace", "comment_list", "comment_write",
        "run_to",
        "captures", "rom_check", "set_register", "snapshot", "start", "state_list", "state_write",
        "status",
        "step", "stop", "symbols_find", "throttle", "watch_add",
        "write", "scan",
    ]), f"the registered surface changed: {registered}"




def test_a_missing_rom_directory_is_refused_before_the_emulator_is_spawned(
        tmp_path: Path) -> None:
    """A missing ROM directory is the worst shaped failure if it reaches MAME."""
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    refused("no such ROM directory",
    s.start(binary=str(binary), system="none", rompath=str(tmp_path / "run" / "mame_roms"),
            reference_rom=str(rom), boot_seconds=0.2))
    assert mstate.STATE.proc is None, "a refused start spawned something"


def test_a_missing_symbol_file_is_refused_before_the_emulator_is_spawned(tmp_path: Path) -> None:
    """IT WAS THE ONE PATH NOT CHECKED UP FRONT, and the cost was not cosmetic."""
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    refused("no symbol file at",
    s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(rom), symbols=str(tmp_path / "absent.sym"),
    ))


def test_a_missing_reference_rom_is_refused_too(tmp_path: Path) -> None:
    """The control for the case above: the neighbouring check still refuses as it should."""
    binary = fake_mame(tmp_path)
    refused("no reference ROM at",
    s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(tmp_path / "absent.bin"),
    ))


@pytest.mark.parametrize(("argument", "refusal"), [
    ("binary", r"MAME binary resolves from the argument rung: .*\(a directory\)"),
    ("reference_rom", "no reference ROM at"),
    ("symbols", "no symbol file at"),
    ("boot_lua", "no boot harness at"),
    ("cfg", "no cfg at"),
])
def test_a_directory_where_a_file_is_due_is_refused_naming_the_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argument: str, refusal: str
) -> None:
    """Each of the five path arguments refuses a DIRECTORY, at the argument and before
    anything is spawned. The reason `is_file()` is the check and not `exists()` lives with the
    check, in `mame_launch.judge`, and for `binary` in the ladder (`mame_binary`), which says
    why the path it was given is no executable; what this pins is that every one asks it."""
    _never_spawns(monkeypatch, tmp_path)
    folder = tmp_path / "a-directory-not-a-file"
    folder.mkdir()
    args: dict[str, Any] = {**_boot_args(tmp_path, bytes(16)), argument: str(folder)}
    refused(refusal, s.start(**args))
    assert mstate.STATE.proc is None, "a refused start spawned something"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows keeps no mode bit")
def test_a_binary_that_is_a_file_and_cannot_be_run_is_refused_as_such(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The other half of the binary's check, and the reason it is two sentences and not one."""
    _never_spawns(monkeypatch, tmp_path)
    args = _boot_args(tmp_path, bytes(16))
    unrunnable = tmp_path / "not-a-program"
    unrunnable.write_text("#!/bin/sh\nexit 0\n")
    unrunnable.chmod(0o644)
    refused(r"\(not executable\)", s.start(**{**args, "binary": str(unrunnable)}))


def test_a_map_class_with_no_base_refuses_start_before_the_emulator_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reading the symbol file AFTER the boot and the ROM check makes a refusal here cost a
    whole boot (the guard does kill the process) to say what the file already said.
    Every input is judged before anything exists."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    sym = tmp_path / "game.map"
    sym.write_text("_start\tED000\t_TEXT\t0\tCODE\nstack\t2B000\t_STACK\t0\tSTACK\n")
    out = refused("STACK", s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(rom), symbols=str(sym), bases={"DATA": "0x400"},
    ))
    assert out["code"] == "bad_argument" and out["message"].startswith("symbols: "), out


def test_bases_beside_a_yaml_file_refuse_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    sym = tmp_path / "s.yaml"
    sym.write_text("- addr: 16\n  name: first\n")
    out = refused("YAML|yaml", s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(rom), symbols=str(sym), bases={"DATA": "0x400"},
    ))
    assert out["code"] == "bad_argument" and "bases" in out["message"], out


def test_a_bases_value_of_rom_means_the_class_stays_at_its_linear_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The word `rom` where a hex base would go."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    sym = tmp_path / "game.map"
    sym.write_text("_start\tED000\t_TEXT\t0\tCODE\njuke\t60000\tJUKE\t0\tV30_JUKEBOX\n")
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym), bases={"V30_JUKEBOX": "rom"})
    try:
        assert out["symbols_total"] == 2
        assert out["symbols_by_class"] == {"CODE": 1, "V30_JUKEBOX": 1}
        assert mstate.STATE.resolve("juke") == 0x60000
    finally:
        s.close()


def test_a_bases_value_that_is_not_hex_refuses_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`bases` values are hex strings like `reference_addr`; one that is not is the caller's."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    sym = tmp_path / "game.map"
    sym.write_text("_start\tED000\t_TEXT\t0\tCODE\n")
    refused("DATA", s.start(
            binary=str(binary), system="none", rompath=str(tmp_path),
            reference_rom=str(rom), symbols=str(sym), bases={"DATA": "0x4zz"},
        ))


def test_bases_with_no_symbol_file_refuse_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `bases` with nothing to apply it to is a parameter honoured by nothing."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    out = refused("no `symbols`", s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(rom), bases={"DATA": "0x400"},
    ))
    assert out["code"] == "bad_argument"
    assert mstate.STATE.proc is None, "a refused start spawned something"


def test_a_reference_address_outside_the_image_refuses_start_before_the_emulator_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The window is a function of the file's LENGTH and three numbers."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "raw.bin"
    rom.write_bytes(bytes(64))
    common = dict(binary=str(binary), system="none", rompath=str(tmp_path), reference_rom=str(rom))
    refused("OUTSIDE", s.start(reference_addr="0x20010", **common))
    refused("reference_addr", s.start(reference_addr="0x4zz", **common))
    refused("reference_base", s.start(reference_addr="0x10", reference_base="-20000", **common))


def test_start_on_a_machine_that_does_not_hold_the_rom_is_refused_in_the_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The known-answer check failing is a VERDICT about the machine, answered in the reply
    shape every `start` has (`start_retries` included), never an execution failure; and the
    session it refused is gone."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, bytes(64), at=0)       # the machine serves zeros
    out = s.start(**_boot_args(tmp_path, image))
    assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert "LIES" in out["message"] and out.get("start_retries", []) == [], out
    assert list(out)[-1] == "session" and s.status()["session"]["alive"] is False


def test_start_without_a_symbol_file_reports_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The third value of `symbols_format`, which the reader never produces and the server does."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    out = s.start(**_boot_args(tmp_path, image))
    try:
        assert out["symbols_total"] == 0
        assert out["symbols_format"] == "none"
        assert out["symbols_by_class"] == {}
    finally:
        s.close()


def test_rom_check_takes_the_reference_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The tool passes the base through to the comparison, so a raw linker image works."""
    ses = reading_session(bytes(range(64)), 0x20000)
    _install(monkeypatch, ses, tmp_path)
    rom = tmp_path / "raw.bin"
    rom.write_bytes(bytes(range(64)))
    monkeypatch.setattr(ses, "cost_per_query", lambda *_a, **_k: 0.0012345678, raising=False)
    out = s.rom_check(reference_rom=str(rom), reference_addr="0x20010", reference_base="0x20000")
    assert out["rom_check"] == "OK"
    assert out["query_s"] == 0.001235, "the cost of one query, in seconds, to the microsecond"


def test_rom_check_without_the_base_indexes_the_file_as_cpu_space(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The control."""
    ses = reading_session(bytes(range(64)), 0x20000)
    _install(monkeypatch, ses, tmp_path)
    rom = tmp_path / "raw.bin"
    rom.write_bytes(bytes(range(64)))
    got = s.rom_check(reference_rom=str(rom), reference_addr="0x20010")
    assert got["code"] == "bad_argument" and "OUTSIDE" in got["message"], got


def test_a_state_dir_survives_close_and_the_scratch_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two session shapes in one parameter."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    state = tmp_path / "state"
    out = s.start(**_boot_args(tmp_path, image), state_dir=str(state))
    scratch = Path(out["scratch_dir"])
    try:
        assert out["state_dir"] == str(state)
        assert (state / "cfg").is_dir() and (state / "nvram").is_dir()
        assert scratch.is_dir() and scratch.name.startswith(launch.SCRATCH_PREFIX)
        assert (scratch / "snap").is_dir()
        assert not (scratch / "cfg").exists(), "state went to the state_dir, not the scratch"
        assert s.status()["state_dir"] == str(state)
        # What reached MAME, not only what the server created: the argv names the same places.
        argv = _StubProcess.last_argv
        assert argv[argv.index("-cfg_directory") + 1] == str(state / "cfg")
        assert argv[argv.index("-nvram_directory") + 1] == str(state / "nvram")
        assert argv[argv.index("-snapshot_directory") + 1] == str(scratch / "snap")
        assert launch.SCRATCH_PREFIX in argv[argv.index("-snapshot_directory") + 1]
    finally:
        s.close()
    assert not scratch.exists(), "the scratch is this session's and dies with it"
    assert (state / "cfg").is_dir(), "the state_dir outlives the session"
    dead = s.status()
    assert dead["session"]["alive"] is False
    assert list(dead)[0] == "summary" and dead["summary"] == "status: no session"
    # The second pass finds the first one's state, and a pre-existing state_dir is not an error.
    (state / "cfg" / "m68k.cfg").write_text("<mameconfig/>")
    again = s.start(**_boot_args(tmp_path, image), state_dir=str(state))
    try:
        assert again["state_dir"] == str(state)
        assert (state / "cfg" / "m68k.cfg").exists(), "the second session found the first's cfg"
    finally:
        s.close()


def test_a_relative_or_unusable_state_dir_is_refused_and_leaves_no_scratch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Relative, MAME would resolve it against ITS cwd."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    common = dict(binary=str(binary), system="none", rompath=str(tmp_path), reference_rom=str(rom))
    refused("must be an absolute path",
    s.start(state_dir="state", **common))
    a_file = tmp_path / "a-file"
    a_file.write_text("not a directory")
    e = refused("state_dir",
    s.start(state_dir=str(a_file), **common))
    assert "cfg" in e["message"] and e["code"] == "bad_argument", "the caller's, not the host's"
    assert "name a directory" in e["message"]
    assert mstate.STATE.scratch is None and mstate.STATE.state_dir == ""


def test_memdump_judges_the_range_by_the_mask_of_the_cpu_it_saves_from(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`save` reads the VISIBLE cpu's program space, read off `cpulist` at the call."""
    def save(command: str) -> str:
        path, _start, length = command[len("save "):].split(",")
        Path(path).write_bytes(bytes(int(length, 16)))
        return "Data saved successfully\n"

    ses = _ConsoleSession(bytes(0x5000), replies={"save": save,
                                                  "cpulist": captured("cpulist.sub-visible.txt")})
    _console(monkeypatch, tmp_path, ses)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    two = {"spaces": _masked(0xFFFFFF)["spaces"] + _masked(0x3FFF, ":subcpu")["spaces"]}
    monkeypatch.setattr(mstate.STATE, "machine_map", two)
    refused("wraps", s.memdump("0x3ffc", length=8, dest=str(tmp_path / "sub.bin")))
    ses.replies["cpulist"] = captured("cpulist.main-visible.txt")
    out = s.memdump("0x3ffc", length=8, dest=str(tmp_path / "main.bin"))
    assert out["status"] == "ok" and out["cpu"] == ":maincpu", out


def test_disassemble_resolves_direct_memory_operands_under_the_bases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A DIRECT memory operand on a segmented board prints as the raw offset inside its class."""
    ses = _ConsoleSession()
    scratch = _console(monkeypatch, tmp_path, ses)
    use_table(monkeypatch, table={"IN_IRQ": 0xC414, "TOTALTIME": 0xEC49,
                                  "DEMOSTATE": 0xCA30, "SOME_CODE": 0xC415})
    use_table(monkeypatch, classes={"IN_IRQ": "DATA", "TOTALTIME": "DATA", "DEMOSTATE": "DATA",
                                    "SOME_CODE": "CODE"})
    use_table(monkeypatch, bases={"DATA": 0x400})
    fixture = {"f5bc0": "dasm.v30.new_irq_video.txt", "f5e2f": "dasm.v30.startdemo.txt"}

    def dasm(command: str) -> str:
        name, addr, _length = command[len("dasm "):].split(",")
        (scratch / name).write_bytes((FIXTURES / fixture[addr[2:]]).read_bytes())
        return ""

    ses.replies["dasm"] = dasm
    out = s.disassemble("0xf5bc0", length=48)
    assert out["status"] == "ok", out
    assert out["resolved"] == [
        {"line": 4, "operand": "0C014h", "offset": 0xC014, "class": "DATA",
         "linear": "0x0000c414", "symbol": "IN_IRQ", "delta": 0},
        {"line": 16, "operand": "0C014h", "offset": 0xC014, "class": "DATA",
         "linear": "0x0000c414", "symbol": "IN_IRQ", "delta": 0},
        {"line": 21, "operand": "0E849h", "offset": 0xE849, "class": "DATA",
         "linear": "0x0000ec49", "symbol": "TOTALTIME", "delta": 0},
        {"line": 22, "operand": "0C016h", "offset": 0xC016, "class": "DATA",
         "linear": "0x0000c416", "symbol": "IN_IRQ", "delta": 2},
    ], out["resolved"]
    out = s.disassemble("0xf5e2f", length=48)
    assert out["resolved"] == [
        {"line": 21, "operand": "0CA34h", "offset": 0xCA34, "class": "DATA",
         "linear": "0x0000ce34", "symbol": "DEMOSTATE", "delta": 0x404},
    ], "only the one direct operand resolves; the register-relative ones are left alone"
    # TWO RELOCATED CLASSES answer one entry each per operand, and a class with no symbol
    # below the address answers `symbol` unavailable rather than another class's name.
    use_table(monkeypatch, bases={"DATA": 0x400, "OTHER": 0x20000})
    none_below = {"available": False, "why": "no symbol of class OTHER lies at or below it"}
    out = s.disassemble("0xf5e2f", length=48)
    assert [(r["class"], r["linear"], r["symbol"], r["delta"]) for r in out["resolved"]] == [
        ("DATA", "0x0000ce34", "DEMOSTATE", 0x404), ("OTHER", "0x0002ca34", none_below, none_below)]
    # AN EMPTY TABLE still resolves the address: the symbol is what is missing, not the base.
    use_table(monkeypatch, table={})
    use_table(monkeypatch, classes={})
    use_table(monkeypatch, bases={"DATA": 0x400})
    out = s.disassemble("0xf5e2f", length=48)
    below = {"available": False, "why": "no symbol of class DATA lies at or below it"}
    assert out["resolved"] == [{"line": 21, "operand": "0CA34h", "offset": 0xCA34,
                                "class": "DATA", "linear": "0x0000ce34", "symbol": below,
                                "delta": below}]
    # THE CONTROL: a board with no bases (a 68000 with a YAML table) carries no `resolved`
    # at all, rather than an empty list that reads as "nothing to resolve here".
    use_table(monkeypatch, bases={})
    out = s.disassemble("0xf5bc0", length=48)
    assert "resolved" not in out, out


def test_a_warm_batch_is_also_refused_whole_for_a_later_steps_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE SAME THING WITH A MACHINE UP, which is the half that was observed from the outside."""
    _running(monkeypatch, tmp_path)
    # `snapshot` is the step the repository actually tried, and the one the batch table had left
    # out: `memdump` alone was covered, so a green here on `memdump` said nothing about `snapshot`.
    for later in ({"op": "memdump", "ref": "0x0", "length": 8, "dest": "relative.bin"},
                  {"op": "snapshot", "dest": "relative.png"}):
        out = s.perform(steps=[{"op": "status"}, later])
        assert out["code"] == "bad_argument", (later, out)
        assert (out["ran"] == []
                and out["steps_completed"] == 0), "a step ran before the list was refused"


def test_a_log_shorter_than_its_mark_is_read_from_the_start(tmp_path: Path) -> None:
    """A mark past the end describes a file that no longer exists (MAME rewrote it)."""
    log = tmp_path / "error.log"
    log.write_text("a\nb\nc\n", newline="")
    assert files.errorlog_since(tmp_path, 0) == (["a", "b", "c"], 6)
    assert files.errorlog_since(tmp_path, 4) == (["c"], 6)
    log.write_text("x\n", newline="")
    assert files.errorlog_since(tmp_path, 6) == (["x"], 2)
    # A CRLF log, and a line still being written: the half line is NOT a line yet, the mark
    # stays before it, and it is seen whole, once, when its newline arrives.
    log.write_text("p\r\nq", newline="")
    assert files.errorlog_since(tmp_path, 0) == (["p"], 3)
    with open(log, "a", newline="") as fh:
        fh.write("uiet\n")
    assert files.errorlog_since(tmp_path, 3) == (["quiet"], 9)
    assert files.errorlog_since(tmp_path / "none", 0) == ([], 0)


def test_a_system_this_build_does_not_carry_refuses_the_start_in_mame_s_own_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each repository ships its own narrow MAME, so which systems exist is the BINARY's answer."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    # The shape of the real refusal: exit code 5, the sentence on stderr.
    rewrite_mame(args["binary"], (
        "sys.stderr.write(f\"No matching machines found for '{sys.argv[1]}'\\n\")\nsys.exit(5)"))
    out = refused("does not carry", s.start(**{**args, "system": "notthisone"}))
    assert "No matching machines found for 'notthisone'" in out["message"]
    assert out["exit_code"] == 5
    assert mstate.STATE.ses is None and mstate.STATE.scratch is None, (
        "a start that did not start owns nothing")


def test_a_listxml_that_fails_for_any_other_reason_leaves_the_start_working(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A debug session must not be blocked on an inventory."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    rewrite_mame(args["binary"], "sys.stderr.write('Fatal error: no memory\\n')\nsys.exit(3)")
    out = s.start(**args)
    try:
        assert out["rom_check"] == "OK", "the session still came up"
        cached = mstate.STATE.machine_map
        assert cached["rom_files"] == [] and cached["sources"]["rom_files"] == ["-listxml"]
        assert "exit code 3" in cached["note"]
        assert "no memory" in cached["note"]
    finally:
        s.close()


def test_the_doubles_surface_is_derived_from_the_package_and_held_to_the_real_session(
        tmp_path: Path) -> None:
    """Every attribute the package reads on a session is derived by AST from the package's
    own source, per file against that file's own imports
    (so prose cannot contribute and `subprocess.run` cannot either), and held in two
    directions. Every callable name must exist on the real `Session`, or the server calls a
    method the client lacks; and the running double must carry every one, or a tool moved
    onto a method the double never had crashes on the real path with a traceback the
    wrapper does not translate, while the suite stays green. A floor of names the server
    plainly uses guards the derivation itself against going blind."""
    package = Path(str(s.__file__)).parent
    used: set[str] = set()
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {a.asname or a.name.split(".")[0]
                   for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {a.asname or a.name
                    for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                 and not (isinstance(n.value, ast.Name) and n.value.id in modules)}
    called = {n for n in used if not n.startswith("_") and callable(getattr(g.Session, n, None))}
    for sentinel in ("read", "registers", "monitor", "make_visible", "register_block", "poll_stop",
                     "go", "interrupt", "step", "current_pc", "quit", "set_reg", "write"):
        assert sentinel in called, (
            f"the derivation no longer sees `{sentinel}`, which the package plainly calls on "
            "a session: it has gone blind and this check is empty")
    double = _RunningSession(tmp_path)
    for name in sorted(called):
        assert hasattr(g.Session, name), f"the package calls `Session.{name}`, which does not exist"
        assert callable(getattr(double, name, None)), (
            f"the running double has fallen behind: the package calls `{name}` on the session "
            "and `_RunningSession` does not have it")
    # And the non-callable attributes the package reads, which a double answers as fields.
    fields = {n for n in used if not n.startswith("_") and hasattr(g.Session, n)
              and not callable(getattr(g.Session, n))}
    missing = sorted(n for n in fields if not hasattr(double, n)
                     and n not in ("host", "port", "timeout", "owner", "pc_name"))
    assert missing == [], f"session fields the package reads and the double lacks: {missing}"


def test_a_binary_with_no_console_plugin_in_any_place_is_refused_before_the_boot(
    tmp_path: Path,
) -> None:
    """MAME's `-console` is fatal without the console plugin."""
    # EXECUTABLE, because this case is about the PLUGINS and nothing else: the check that asks
    # whether the binary can be RUN fires first and answers a different question.
    binary = host_program.write(tmp_path / "bare-mame", "")
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    out = refused("no console plugin for", s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(rom), boot_seconds=0.2))
    assert out["code"] == "bad_argument"
    for place in (tmp_path / "plugins", tmp_path.parent / "share" / "mame" / "plugins"):
        assert str(place.resolve() / "console" / "init.lua") in out["message"], (
            "every place it looked is named", place)
    assert "pass as `binary`, or set MAME_BINARY to, the executable" in out["message"]
    assert mstate.STATE.proc is None, "a refused start spawned something"


def test_a_plugin_less_build_the_path_found_is_the_host_s_to_fix_and_says_which_rung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same build reached by the PATH rung."""
    host_program.write(tmp_path / "bin" / "mame", "")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.delenv("MAME_BINARY", raising=False)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    out = refused("no console plugin for", s.start(
        system="none", rompath=str(tmp_path), reference_rom=str(rom), boot_seconds=0.2))
    assert out["code"] == "host_failed", out
    assert "the PATH rung" in out["message"] and "MAME_BINARY" in out["message"], out["message"]
    assert mstate.STATE.proc is None, "a refused start spawned something"


@pytest.mark.skipif(sys.platform == "win32", reason="a keg is a POSIX prefix reached by symlink")
def test_a_packaged_mame_finds_its_console_plugin_under_its_prefixs_share(
    tmp_path: Path,
) -> None:
    """A Homebrew keg."""
    version = "1.0"
    keg = tmp_path / "Cellar" / "mame" / version
    (keg / "bin").mkdir(parents=True)
    real = keg / "bin" / "mame"
    real.write_text("#!/bin/sh\nexit 0\n")
    real.chmod(0o755)
    console = keg / "share" / "mame" / "plugins" / "console"
    console.mkdir(parents=True)
    (console / "init.lua").write_text("-- the console plugin's place, not its code\n")
    (tmp_path / "bin").mkdir()
    link = tmp_path / "bin" / "mame"
    link.symlink_to(Path("..") / "Cellar" / "mame" / version / "bin" / "mame")
    (keg / "bin" / "plugins" / "console").mkdir(parents=True)        # no init.lua in it
    assert launch.plugins_dir(str(link)) == console.parent.resolve()
    cmd = launch.build_command(str(link), "circus", "/roms", 23946, [], str(tmp_path))
    assert cmd[cmd.index("-pluginspath") + 1] == str(console.parent.resolve())
    # BESIDE THE EXECUTABLE STILL WINS, a source build's place asked first.
    beside = keg / "bin" / "plugins" / "console"
    (beside / "init.lua").write_text("--\n")
    assert launch.plugins_dir(str(link)) == beside.parent.resolve()


def test_the_command_line_names_the_plugins_beside_the_binary(tmp_path: Path) -> None:
    binary = fake_mame(tmp_path)
    cmd = launch.build_command(str(binary), "m68k-dual", "/roms", 23946, [], str(tmp_path))
    at = cmd.index("-pluginspath")
    assert cmd[at + 1] == str((tmp_path / "plugins").resolve())
    assert "-console" in cmd


def test_registers_from_the_last_stop_before_any_stop_is_no_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stale read before the session has recorded a stop has nothing to hand back."""
    _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    out = s.registers(from_last_stop=True)
    assert out["status"] == "INVALID" and out["code"] == "no_stop", out
    assert "no stop yet" in out["message"]


def test_start_installs_the_repos_cfg_where_mame_reads_it_and_close_says_if_it_changed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The cabinet's key map is a versioned `.cfg` in the repo, the ONE source of those keys."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    source = tmp_path / "repo" / "run" / "cfg" / "v30.cfg"
    source.parent.mkdir(parents=True)
    source.write_text(CFG_OK)
    out = s.start(**_boot_args(tmp_path, image), cfg=str(source))
    assert out["status"] == "ok", out
    scratch = Path(out["scratch_dir"])
    installed = scratch / "cfg" / "m68k.cfg"
    assert out["cfg"] == {"source_path": str(source), "installed_path": str(installed),
                          "replaced": False}
    assert installed.read_text() == CFG_OK
    argv = _StubProcess.last_argv
    assert argv[argv.index("-cfg_directory") + 1] == str(installed.parent)
    assert s.status()["cfg"] == out["cfg"]
    installed.write_text(CFG_OK.replace("KEYCODE_DOWN", "KEYCODE_UP"))   # MAME canonising
    closed = s.close()
    assert closed["cfg"] == {"installed_path": str(installed), "changed": True}, closed
    assert source.read_text() == CFG_OK, "the repo's file is never touched"
    # Into a persistent state_dir the copy lands there, and an unchanged copy says so.
    state = tmp_path / "state"
    out = s.start(**_boot_args(tmp_path, image), cfg=str(source), state_dir=str(state))
    assert out["cfg"]["installed_path"] == str(state / "cfg" / "m68k.cfg")
    assert out["cfg"]["replaced"] is False
    closed = s.close()
    assert closed["cfg"] == {"installed_path": str(state / "cfg" / "m68k.cfg"), "changed": False}
    # A second pass over the same state_dir finds the earlier copy and SAYS it replaced it.
    out = s.start(**_boot_args(tmp_path, image), cfg=str(source), state_dir=str(state))
    assert out["cfg"]["replaced"] is True
    s.close()
    # No cfg: nothing installed, and the replies say so with `null`.
    out = s.start(**_boot_args(tmp_path, image))
    assert out["cfg"]["available"] is False and s.close()["cfg"]["available"] is False


def test_a_cfg_mame_would_not_bind_is_refused_before_the_boot_naming_the_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two XML subtleties MAME meets in SILENCE (the MAME reference carries both)."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    cfg = tmp_path / "bad.cfg"
    cfg.write_text(CFG_OK.replace(' mask="64" defvalue="64"', ""))
    out = refused("`mask`", s.start(**args, cfg=str(cfg)))
    assert "line 5" in out["message"], out["message"]
    # THE LINE IS THE PARSER'S: a comment quoting a port and two ports on one line do not
    # shift it (the audit found a count over the text that both would move).
    cfg.write_text(CFG_OK.replace("<input>", "<!-- <port> used to be here -->\n        <input>")
                   .replace('<port tag=":P1" type="P1_BUTTON1" mask="64" defvalue="64">',
                            '<port tag=":P1" type="P1_START" mask="1" defvalue="1"><newseq '
                            'type="standard">KEYCODE_1</newseq></port><port tag=":P1" '
                            'type="P1_BUTTON1" defvalue="64">'))
    out = refused("`mask`", s.start(**args, cfg=str(cfg)))
    assert "line 6" in out["message"], out["message"]
    # A refused cfg beside a fresh state_dir leaves NO directory behind.
    state = tmp_path / "never"
    refused("`mask`", s.start(**args, cfg=str(cfg), state_dir=str(state)))
    assert not state.exists(), "a refused start created the caller's state_dir"
    cfg.write_text(CFG_OK.replace("<input>", "<!-- a -- b -->\n        <input>"))
    refused("comment", s.start(**args, cfg=str(cfg)))
    cfg.write_text(CFG_OK.replace('name="m68k"', 'name="v30"'))
    refused("v30", s.start(**args, cfg=str(cfg)))
    refused("must be an absolute path", s.start(**args, cfg="run/cfg/v30.cfg"))
    refused("no cfg at", s.start(**args, cfg=str(tmp_path / "missing.cfg")))
    assert s.status()["session"]["alive"] is False, "nothing was spawned"


def test_a_cfg_mame_did_not_read_ends_the_session_it_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The control AFTER the boot."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    cfg = tmp_path / "good.cfg"
    cfg.write_text(CFG_OK)
    line = "Error parsing XML configuration file m68k.cfg\n"

    class _Complaining(_StubProcess):
        """A MAME that refuses its cfg."""

        def __init__(self, *a: object, **k: object) -> None:
            super().__init__(*a, **k)
            out = k["stdout"]
            assert isinstance(out, io.BufferedIOBase), "start opens stdout.log in binary"
            out.write(b"boot\n" + line.encode())
            out.flush()

    import subprocess
    real_popen = subprocess.Popen
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _Complaining(*a, **k)
                        if (Path((a[0] if a else k["args"])[0]).stem == "fake-mame"
                            and "-debugger" in (a[0] if a else k["args"]))
                        else real_popen(*a, **k))
    out = refused("did not read", s.start(**_boot_args(tmp_path, image), cfg=str(cfg)))
    assert "Error parsing XML configuration file m68k.cfg" in out["message"], out["message"]
    assert "`process` channel" in out["message"] and out["stdout_path"].endswith("stdout.log")
    assert s.status()["session"]["alive"] is False, (
        "a session MAME booted on the defaults was left alive")
    # The reader itself: it reads the captured stdout, and a line in `error.log` is not it.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assert launch.cfg_parse_error(scratch) is None
    (scratch / "error.log").write_text("boot\n" + line, newline="")
    assert launch.cfg_parse_error(scratch) is None, "error.log is not where MAME writes it"
    (scratch / "stdout.log").write_text("boot\n" + line + "more\n", newline="")
    assert launch.cfg_parse_error(scratch) == line.strip()


def test_a_tilde_path_is_expanded_and_a_relative_one_says_why(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A `~` path is ABSOLUTE to the person who typed it and no shell stands between them and
    this argument, so the judge expands it; a relative one is refused saying why."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert inputs.absolute("binary", "~/mame") == tmp_path / "mame"
    with pytest.raises(mstate.Invalid, match="must be an absolute path or start with `~`"):
        inputs.absolute("binary", "upstream/v30")
    assert inputs.absolute("binary", str(tmp_path / "mame")) == tmp_path / "mame"


def test_every_path_refusal_names_the_remedy_and_not_only_the_rule() -> None:
    """A refusal that only says "must be an absolute path" names the rule and withholds the
    reason: every path argument says why a relative one is refused, in one sentence."""
    relative = _refusal_text(inputs.fresh_dest, "dest", "snap/x.png")
    assert "would be judged in one directory and used in another" in relative, relative
    assert "start with `~`" in relative, relative


def test_close_lists_its_fields_in_the_order_its_docstring_promises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The last words of each channel come right after `closed`, then how it ended."""
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}order"
    scratch.mkdir()
    (scratch / "stdout.log").write_text("bye\n", newline="")
    (scratch / "error.log").write_text("", newline="")
    monkeypatch.setattr(mstate.STATE, "scratch", scratch)
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    keys = list(s.close(detail=True))
    promised = ["closed", "stdout_tail", "errorlog_tail", "ended_by", "exit_code"]
    assert [k for k in keys if k in promised] == promised, keys


def test_a_docstring_placeholder_is_filled_from_its_constant_or_fails_the_import() -> None:
    """A number a description states is the constant that enforces it."""
    assert mdocs.filled("x", "at most {READ_MAX} bytes") == f"at most {read.READ_MAX} bytes"
    with pytest.raises(TypeError, match=r"x's docstring names \['\{NOPE\}'\]"):
        mdocs.filled("x", "at most {NOPE} bytes")
    assert mdocs.filled("x", "a {lowercase} brace is prose") == "a {lowercase} brace is prose"




def test_boot_hands_the_inipath_and_the_scratch_as_cwd_to_the_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`build_command` is tested alone."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    ini = tmp_path / "ini"
    ini.mkdir()
    out = s.start(**_boot_args(tmp_path, image), inipath=str(ini))
    try:
        argv = _StubProcess.last_argv
        assert argv[argv.index("-inipath") + 1] == str(ini)
        assert str(_StubProcess.last_kwargs["cwd"]) == out["scratch_dir"]
    finally:
        s.close()


def test_close_proves_the_clean_exit_by_the_cfg_mame_writes_on_its_way_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`how."""

    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}proof"
    (scratch / "cfg").mkdir(parents=True)
    cfg = scratch / "cfg" / "m68k-dual.cfg"
    cfg.write_text("<mameconfig/>")
    os.utime(cfg, ns=(1_000_000_000, 1_000_000_000))       # long before any exit

    class _Writing(_ExitingProcess):
        """A MAME that writes its cfg as it quits, the way the real one does."""

        def wait(self, timeout: float | None = None) -> int:
            cfg.write_text("<mameconfig>rewritten</mameconfig>")
            return super().wait(timeout)

    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _Writing(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.scratch, mstate.STATE.system = scratch, "m68k-dual"
    closed = s.close()
    assert closed["ended_by"] == "quit" and closed["state_written"] is True, closed
    assert closed["summary"].startswith("close: quit, exit code 0")
    (scratch / "cfg").mkdir(parents=True)
    cfg.write_text("<mameconfig/>")
    os.utime(cfg, ns=(1_000_000_000, 1_000_000_000))
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.scratch, mstate.STATE.system = scratch, "m68k-dual"
    closed = s.close()
    assert closed["ended_by"] == "exited" and closed["state_written"] is False, closed
    assert closed["summary"] == "close: exited without writing its state, exit code 0"
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    closed = s.close()
    assert closed["ended_by"] == "quit" and closed["state_written"]["available"] is False, closed


def test_a_cfg_that_cannot_be_read_back_says_which_file_and_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`changed."""

    source = tmp_path / "repo.cfg"
    source.write_text("<mameconfig/>")
    installed = tmp_path / "installed.cfg"
    installed.write_text("<mameconfig/>")
    installed.chmod(0)
    if os.access(installed, os.R_OK):
        pytest.skip("this account reads a file with no permission bits (root?)")
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.cfg = {"source": source, "installed": installed, "replaced": False}
    try:
        closed = s.close()
    finally:
        installed.chmod(0o644)
    assert closed["cfg"]["changed"]["available"] is False, closed["cfg"]
    assert "installed.cfg" in closed["cfg"]["changed"]["why"], closed["cfg"]
    assert "could not be read back" in closed["cfg"]["changed"]["why"]


def test_judge_cfg_refuses_a_wrong_root_an_unreadable_file_and_a_cut_off_document_in_the_envelope(
    tmp_path: Path,
) -> None:
    """Three refusals of `judge_cfg` no case reached."""

    wrong_root = tmp_path / "root.cfg"
    wrong_root.write_text('<?xml version="1.0"?>\n<foo><system name="m68k"/></foo>\n')
    with pytest.raises(mstate.Invalid) as e:
        launch.judge_cfg(str(wrong_root), "m68k")
    assert e.value.code == "bad_argument" and "not <mameconfig>" in str(e.value)
    cut = tmp_path / "cut.cfg"
    cut.write_text('<?xml version="1.0"?>\n<mameconfig version="10"><system name="m68k">\n')
    with pytest.raises(mstate.Invalid) as e:
        launch.judge_cfg(str(cut), "m68k")
    assert e.value.code == "bad_argument" and "not XML" in str(e.value)
    unreadable = tmp_path / "locked.cfg"
    unreadable.write_text(CFG_OK)
    unreadable.chmod(0)
    try:
        if os.access(unreadable, os.R_OK):
            pytest.skip("this account reads a file with no permission bits (root?)")
        with pytest.raises(mstate.Invalid) as e:
            launch.judge_cfg(str(unreadable), "m68k")
        assert e.value.code == "bad_argument" and "cannot read the cfg" in str(e.value)
    finally:
        unreadable.chmod(0o644)
