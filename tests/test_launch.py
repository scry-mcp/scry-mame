"""`mame_launch`'s refusals of a caller's files, and its reading of what MAME printed, asked of
the functions themselves: the start path reaches them only behind a boot double."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_files as files  # noqa: E402
import mame_launch as launch  # noqa: E402
import mame_machine as machine  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_symbols as syms  # noqa: E402


def test_a_types_file_that_cannot_be_read_is_refused_naming_it(tmp_path: Path) -> None:
    """A directory where the file should be is no file at all, and a file nobody may read is an
    `OSError` of its own: both refusals are the argument's and name the path, never a traceback
    out of `read_text`."""
    with pytest.raises(mstate.Invalid) as refused:
        syms.read_types(str(tmp_path))
    assert refused.value.code == "bad_argument", refused.value.code
    assert str(refused.value) == f"no such types file: {tmp_path}", refused.value
    locked = tmp_path / "locked.types"
    locked.write_text("x: u16\n")
    locked.chmod(0)
    if os.access(locked, os.R_OK):
        pytest.skip("this user reads a mode-0 file (root), so nothing is unreadable")
    with pytest.raises(mstate.Invalid) as refused:
        syms.read_types(str(locked))
    assert str(refused.value).startswith(f"cannot read the types file {locked}: "), refused.value


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
    """MAME's stdout carries whatever a driver prints, and one byte that is not UTF-8 ahead of
    the line may not hide the line."""
    files.log_path(tmp_path, "process").write_bytes(
        b"boot \xff\xfe noise\n" + f"{launch.CFG_PARSE_ERROR} cfg/m68k-dual.cfg\n".encode())
    assert launch.cfg_parse_error(tmp_path) == f"{launch.CFG_PARSE_ERROR} cfg/m68k-dual.cfg"


def test_the_boot_script_carries_the_inventory_and_adds_the_throttle_after_it(
    tmp_path: Path,
) -> None:
    """ONE script: the inventory, dumping to the scratch, always first; the throttle when a
    frame was asked for is ADDED behind it, never in its place."""
    alone = Path(launch.boot_harness(tmp_path, "", 0)).read_text(encoding="utf-8")
    assert str(tmp_path / machine.DUMP_NAME) in alone and launch.THROTTLE_MARK not in alone
    both = Path(launch.boot_harness(tmp_path, "", 900)).read_text(encoding="utf-8")
    assert both.startswith(alone) and launch.THROTTLE_MARK in both, "the throttle follows it"


def test_the_boot_script_quotes_a_harness_path_holding_a_quote_or_a_backslash(
        tmp_path: Path) -> None:
    """The caller's harness is reached through `dofile("<path>")` inside the one boot script, so
    a `"` would end the Lua string, a `\\` would start an escape and a newline would end the
    line: the path goes in as a Lua literal with the three escaped, one statement per line."""
    odd = tmp_path / 'a"b\\c\nd'
    odd.mkdir()
    harness = odd / "boot.lua"
    harness.write_text("-- a harness\n")
    text = Path(launch.boot_harness(tmp_path, str(harness), 0)).read_text(encoding="utf-8")
    literal = (str(harness.resolve()).replace("\\", "\\\\").replace('"', '\\"')
               .replace("\n", "\\n"))
    assert text.rstrip("\n").split("\n")[-1] == f'dofile("{literal}")', text[-300:]
