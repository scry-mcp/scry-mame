"""NUMBERS BETWEEN THE SERVER AND MAME'S CONSOLE, in both directions.

Out: the console's expression parser looks a bare token up in the visible cpu's symbol table
BEFORE it reads it as a number (`parse_symbol_or_number`, src/emu/debug/express.cpp), and a
cpu's registers are symbols there. So `bp d0` on a 68000 arms at the value of register D0, and
a `wp` length of ten spelled `a` is register A on a Z80. Every number the server sends travels
with `0x`.

In: `bplist` and `wplist` print each row as `%c%4X @ ...` (execute_bplist, execute_wplist in
src/emu/debug/debugcmd.cpp): ONE flag column, a space or `D`, then the index right-aligned in
four columns. The rows below are built with that format string, so an index whose own first
digit is `D` is read as the index it is.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_breakpoints as breakpoints  # noqa: E402
import mame_conditions as conditions  # noqa: E402
import mame_lists as mlists  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_watches as watches  # noqa: E402


@pytest.mark.parametrize("addr", [0xD0, 0xA7, 0xDE, 0x400])
def test_a_breakpoint_address_is_sent_as_a_number_never_as_a_name(addr: int) -> None:
    assert breakpoints.bp_command(addr, "", ":maincpu") == f"bp {addr:#x}::maincpu"


@pytest.mark.parametrize("length", [0xA, 0xDE, 4])
def test_a_watchpoint_address_and_length_are_sent_as_numbers(length: int) -> None:
    assert watches.wp_command(0xD0, length, ":maincpu") == f"wp 0xd0::maincpu,{length:#x},w"


def _row(enabled: bool, index: int, addr: int) -> str:
    """One `bplist` row as MAME prints it: `%c%4X @ %0*X`."""
    return f"{' ' if enabled else 'D'}{index:4X} @ {addr:06X}"


@pytest.mark.parametrize(("enabled", "index"), [
    (True, 0xD1), (False, 0xD1), (False, 0x1), (True, 0x1), (True, 0xDDD), (True, 0xD1234),
    (False, 0xD1234),
])
def test_a_bplist_row_is_read_by_its_flag_column_whatever_its_index_spells(
    enabled: bool, index: int,
) -> None:
    text = f"Device ':maincpu' breakpoints:\n{_row(enabled, index, 0x500)}\n"
    [row] = mlists.parse_bplist(text)
    assert (row["index"], row["enabled"], row["addr"]) == (index, enabled, 0x500), row


@pytest.mark.parametrize(("enabled", "index"), [(True, 0xDD), (False, 0xDD), (False, 0x2)])
def test_a_wplist_row_is_read_by_its_flag_column(enabled: bool, index: int) -> None:
    row_text = f"{' ' if enabled else 'D'}{index:4X} @ 000500-000501 write"
    text = f"Device ':maincpu' program space watchpoints:\n{row_text}\n"
    [row] = mlists.parse_wplist(text)
    assert (row["index"], row["enabled"], row["length"]) == (index, enabled, 2), row


@pytest.mark.parametrize("ref", ["4_00", "-10", "+400", "dead_beef", "0x", ""])
def test_a_ref_that_is_neither_a_symbol_nor_plain_hex_is_refused_never_read(ref: str) -> None:
    """`int(ref, 16)` alone takes a sign and underscores: `-10` would reach the stub as a
    negative address and `dead_beef`, a symbol this build lacks, would read 0xdeadbeef."""
    with pytest.raises(mstate.Invalid) as refused:
        mstate.STATE.resolve(ref)
    assert refused.value.code == "unknown_ref"


@pytest.mark.parametrize(("ref", "addr"), [("0x400", 0x400), ("0X4A0", 0x4A0), (" 0x4a0 ", 0x4A0)])
def test_a_0x_ref_resolves_to_its_address(ref: str, addr: int) -> None:
    assert mstate.STATE.resolve(ref) == addr


def test_a_write_is_held_to_the_read_ceiling_at_the_edge_and_one_past_it() -> None:
    import mame_read as read
    import mame_write as mwrite
    assert len(mwrite.check_write("00" * read.READ_MAX, ref="0x400")) == read.READ_MAX
    with pytest.raises(mstate.Invalid, match=r"byte count of data_hex=1025 is outside 1\.\.1024"):
        mwrite.check_write("00" * (read.READ_MAX + 1), ref="0x400")


def test_an_empty_list_of_steps_is_refused_before_anything() -> None:
    import server as s
    out = s.perform(steps=[])
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "non-empty" in out["message"]


@pytest.mark.parametrize("symbol", ["frame", "frame0", None])
def test_the_frame_counter_is_asked_by_the_name_the_console_gave_at_start_never_the_map(
    monkeypatch: pytest.MonkeyPatch, symbol: str | None,
) -> None:
    """MAME names the counter `frame` on a board with one screen device, `frame0`... on one with
    several and nothing on one with none (src/emu/debug/debugcpu.cpp), and the screens a start
    lists are no guide: topgunnr lists its `vector` display as one screen and has no counter.
    The name is the one the console answered to (`probe_frame_symbol`), whatever the map says."""
    import mame_read as read
    monkeypatch.setattr(mstate.STATE, "machine_map", {"screens": [{"tag": ":vector"}]})
    monkeypatch.setattr(mstate.STATE, "frame_symbol", symbol)
    assert read.frame_symbol() == symbol


@pytest.mark.parametrize("name", ["frame1", "BEAMY0", "max", "lastinstructioncycles", "cpunum",
                                  "s16", "temp9"])
def test_every_name_the_console_owns_is_known_as_its_own(name: str) -> None:
    assert conditions.is_console_name(name)


@pytest.mark.parametrize("name", ["frames", "maxlen", "demo_frame"])
def test_a_project_name_that_only_resembles_one_is_not_the_consoles(name: str) -> None:
    assert not conditions.is_console_name(name)


def test_an_ignore_list_the_console_wrapped_is_read_whole() -> None:
    """`ignore` answers ONE line (src/emu/debug/debugcmd.cpp), which the console's text buffer
    wraps at its column: at a space it drops, else hard. Read in pieces it lost every cpu past
    the first cut."""
    import gdb_session as gs
    import mame_cpus as cpus
    tags = [f":cpu{i:02d}_with_a_long_tag_name" for i in range(12)]
    rest, pieces = "Currently ignoring device " + ", ".join(f"'{t}'" for t in tags), []
    while len(rest) > gs.CONSOLE_WRAP_COLS:
        cut = rest.rfind(" ", 0, gs.CONSOLE_WRAP_COLS + 1)
        pieces.append(rest[:cut])
        rest = rest[cut + 1:]
    pieces.append(rest)
    assert len(pieces) > 1, "the control: the line really was wrapped"

    class _Console:
        def monitor(self, command: str) -> str:
            return "\n".join(pieces) + "\n"

    assert cpus.ignored(_Console()) == tags  # type: ignore[arg-type]
