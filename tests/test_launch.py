import os
import subprocess
import threading
from pathlib import Path

import pytest
from scry_core import host_program
from scry_core.host_program import POSIX_NAMES

from scry_mame import (
    files,  # noqa: E402
    launch,  # noqa: E402
    machine,  # noqa: E402
    transport,  # noqa: E402
)
from scry_mame import state as mstate  # noqa: E402
from scry_mame import symbols as syms  # noqa: E402


def test_a_types_file_that_cannot_be_read_is_refused_naming_it(tmp_path: Path) -> None:
    """A directory or an unreadable file is refused naming the path, never an `OSError`."""
    with pytest.raises(mstate.Invalid) as refused:
        syms.read_types(str(tmp_path))
    assert refused.value.code == "bad_argument", refused.value.code
    assert str(refused.value) == f"types: no types file at {tmp_path}", refused.value
    locked = tmp_path / "locked.types"
    locked.write_text("x: u16\n")
    locked.chmod(0)
    if os.access(locked, os.R_OK):
        pytest.skip("this user reads a mode-0 file (root), so nothing is unreadable")
    with pytest.raises(mstate.Invalid) as refused:
        syms.read_types(str(locked))
    assert str(refused.value).startswith(f"types: {locked} cannot be read: "), refused.value


def test_a_reference_rom_nobody_may_read_is_refused_as_the_arguments_fault(tmp_path: Path) -> None:
    rom = tmp_path / "rom.bin"
    rom.write_bytes(b"\x00" * 16)
    rom.chmod(0o000)
    try:
        if os.access(rom, os.R_OK):
            pytest.skip("this user reads a file with no permission bits (root): no case here")
        with pytest.raises(mstate.Invalid) as refused:
            launch.reference_rom_file(str(rom))
        assert refused.value.code == "bad_argument"
        assert str(refused.value) == f"the reference ROM {rom} is not readable", refused.value
    finally:
        rom.chmod(0o600)
    assert launch.reference_rom_file(str(rom)) == rom, "the control: readable, it is accepted"


def test_the_cfg_refusal_is_found_past_bytes_that_are_not_text(tmp_path: Path) -> None:
    """A non-UTF-8 byte before the line does not hide it."""
    files.log_path(tmp_path, "process").write_bytes(
        b"boot \xff\xfe noise\n" + f"{launch.CFG_PARSE_ERROR} cfg/m68k-dual.cfg\n".encode())
    assert launch.cfg_parse_error(tmp_path) == f"{launch.CFG_PARSE_ERROR} cfg/m68k-dual.cfg"


def test_the_boot_script_carries_the_inventory_and_adds_the_throttle_after_it(
    tmp_path: Path,
) -> None:
    """The throttle is added behind the inventory, never in its place."""
    alone = Path(launch.boot_harness(tmp_path, "", 0)).read_text(encoding="utf-8")
    dump = transport.lua_string(str(tmp_path / machine.DUMP_NAME))
    assert dump in alone and launch.THROTTLE_MARK not in alone
    both = Path(launch.boot_harness(tmp_path, "", 900)).read_text(encoding="utf-8")
    assert both.startswith(alone) and launch.THROTTLE_MARK in both, "the throttle follows it"


@POSIX_NAMES
def test_the_boot_script_quotes_a_harness_path_holding_a_quote_or_a_backslash(
        tmp_path: Path) -> None:
    """The path enters `dofile("...")` with quote, backslash and newline escaped."""
    odd = tmp_path / 'a"b\\c\nd'
    odd.mkdir()
    harness = odd / "boot.lua"
    harness.write_text("-- a harness\n")
    text = Path(launch.boot_harness(tmp_path, str(harness), 0)).read_text(encoding="utf-8")
    literal = (str(harness.resolve()).replace("\\", "\\\\").replace('"', '\\"')
               .replace("\n", "\\n"))
    assert text.rstrip("\n").split("\n")[-1] == f'dofile("{literal}")', text[-300:]


def test_the_consoles_stdin_holds_what_the_posix_pipe_holds_before_a_writer_blocks() -> None:
    """Lines queue there while the machine is stopped, and a full pipe blocks the writer with no
    bound: Windows' own default holds a sixteenth of it."""
    proc = launch.console_popen([host_program.INTERPRETER, "-c", "import time; time.sleep(30)"],
                                stdout=subprocess.DEVNULL)
    try:
        pipe = proc.stdin
        assert pipe is not None
        writer = threading.Thread(target=lambda: (pipe.write(b"x" * launch.CONSOLE_PIPE_BYTES),
                                                  pipe.flush()), daemon=True)
        writer.start()
        writer.join(5.0)
        assert not writer.is_alive(), "the writer blocked short of the pipe's capacity"
    finally:
        proc.kill()
        proc.wait()
