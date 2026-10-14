"""WHEN a palette write happened, as a capture row says it: each EVENT row of `palette_log` (an
index write, a data write, a desync) carries the beam line and the emulated time of that write,
derived by `capture.BEAM_LINE_LUA`, the one derivation both taps take. The stamp goes at the END of
a row, so the positional `gsub` that decides a row's writer at the next stop still matches; the
per-pen aggregates of the dump (`w`, `p`) are unchanged.

WHAT A ROW HOLDS IS JUDGED BY RUNNING THE SCRIPT: the install is executed by this host's `lua`
against a machine the chunk below stands in for, with 1942's screen (`set_raw(6 MHz, 384, 0, 256,
262, 16, 240)`), and the rows it dumps are read back the way the server reads them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import run_host_lua  # noqa: E402
from test_ramdac import LOG_ID, _ramdac  # noqa: E402

import mame_capture as capture  # noqa: E402
import mame_ramdac as mr  # noqa: E402
import mame_ramdac_lua as rlua  # noqa: E402

PIXEL_S = 1 / 6_000_000
SCAN_S = 384 * PIXEL_S
FRAME_S = 262 * SCAN_S

#: One 68000 whose program space records its taps, 1942's screen, and a clock the accesses set.
#: The debugger is at a stop with the park stamped at another time, so every write is UNDECIDED
#: (`?`) until the dump decides it: the positional `gsub` has to match a stamped row.
HOST = f"""
TAPS = {{}}
local sp = {{data_width = 16, endianness = "big"}}
function sp:install_write_tap(lo, hi, name, cb)
  TAPS[#TAPS + 1] = {{lo = lo, cb = cb}} return {{remove = function() end}}
end
NOW = {{seconds = 0, attoseconds = 0}}
UNTIL = 0.0
SCREEN = {{frame_period = {FRAME_S!r}, scan_period = {SCAN_S!r}, pixel_period = {PIXEL_S!r}}}
function SCREEN:time_until_pos(v, h) return UNTIL end
function SCREEN:frame_number() return 120 end
local cpu = {{tag = ":maincpu", spaces = {{program = sp}}, state = {{CURPC = {{value = 0xbf6}}}}}}
manager = {{machine = setmetatable({{devices = {{[":maincpu"] = cpu}},
                                    screens = {{[":screen"] = SCREEN}},
                                    debugger = {{execution_state = "stop"}}}},
                                   {{__index = function(t, k)
                                     if k == "time" then return NOW end end}})}}
function manager.machine:logerror(s) end
local function sub() return {{unsubscribe = function() end}} end
emu = {{register_periodic = function(f) PERIODIC = f end,
        add_machine_reset_notifier = function(f) RESET = f return sub() end,
        add_machine_post_load_notifier = function(f) return sub() end}}
"""


def _write(port: int, value: int, seconds: int, attoseconds: int, line_s: float) -> str:
    """One byte written to `port` (odd: the low lane of its big-endian word) at that time,
    `line_s` seconds into the frame."""
    return (f"NOW = {{seconds = {seconds}, attoseconds = {attoseconds}}}\n"
            f"UNTIL = {FRAME_S!r} - {line_s!r}\n"
            f"for _, tp in ipairs(TAPS) do if tp.lo == {port & ~1:#x} then "
            f"tp.cb({port & ~1:#x}, {value:#x}, 0x00ff) end end\n")


def _ran(tmp_path: Path, writes: str) -> list[mr.Row]:
    head, rows = tmp_path / "h.txt", tmp_path / "r.rows"
    script = rlua.install_script(LOG_ID, _ramdac(), head, rows, ":maincpu")
    out = run_host_lua(HOST + script + "\n" + writes + "PERIODIC()\n")
    assert any(ln.startswith("MCP_TALLY installed") for ln in out), out
    return list(mr.rows(rows))


def test_each_event_row_carries_the_line_and_time_of_its_own_write(tmp_path: Path) -> None:
    rows = _ran(tmp_path,
                _write(0x720001, 0x10, 2, 5, 40 * SCAN_S + 10 * PIXEL_S)
                + _write(0x720003, 0x3F, 2, 6, 40 * SCAN_S + 200 * PIXEL_S)
                + _write(0x720003, 0x20, 2, 7, 241 * SCAN_S - PIXEL_S / 4)
                + _write(0x720003, 0x01, 3, 0, PIXEL_S / 8))
    assert [r.kind for r in rows] == ["i", "d", "d", "d"], rows
    assert [r.line for r in rows] == [40, 40, 241, 0], "vpos() rounds to the nearest pixel"
    assert [r.time_attoseconds for r in rows] == [2 * capture.ATTOSECONDS_PER_SECOND + 5,
                                                  2 * capture.ATTOSECONDS_PER_SECOND + 6,
                                                  2 * capture.ATTOSECONDS_PER_SECOND + 7,
                                                  3 * capture.ATTOSECONDS_PER_SECOND]
    # THE WRITER WAS DECIDED AT THE DUMP: every row was written `?` at a stop, and a row the
    # positional `gsub` missed would still say `?`, which no reader parses.
    # The dump decides against the clock it reads: the last write shares it, so it is the
    # debugger's, and the three before it the guest's.
    assert [r.by for r in rows] == ["guest", "guest", "guest", "debugger"], rows


def test_a_desync_row_carries_the_line_and_time_of_the_reset(tmp_path: Path) -> None:
    rows = _ran(tmp_path, _write(0x720001, 0x10, 1, 9, 100 * SCAN_S)
                + f"NOW = {{seconds = 1, attoseconds = 99}}\nUNTIL = {FRAME_S!r} - "
                  f"{120 * SCAN_S!r}\nRESET()\n")
    assert [r.kind for r in rows] == ["i", "x"] and rows[1].reason == "reset", rows
    assert (rows[1].line, rows[1].time_attoseconds) == (120, capture.ATTOSECONDS_PER_SECOND + 99)


def test_a_row_written_before_the_stamp_still_reads() -> None:
    """A rows file of a log armed before the stamp existed (the captured fixtures are) reads as
    it did, with no line and no time."""
    (row,) = mr.rows_of(["i 1 900 bf6 g 10"])
    assert (row.kind, row.value, row.line, row.time_attoseconds) == ("i", 0x10, None, None)


def test_a_row_reply_says_when_and_spells_its_numbers_as_written() -> None:
    r = _ramdac()
    stamped = mr.Row("d", 3, 900, 0xBF6, "guest", pen=0x10, slot=0, value=0x3F, line=40,
                     time_attoseconds=2 * capture.ATTOSECONDS_PER_SECOND + 5)
    shown = mr.row_fields(stamped, "#ff0000", r, None)
    assert shown["line"] == 40, shown
    assert shown["time_s"] == (2 * capture.ATTOSECONDS_PER_SECOND + 5) / 10**18, shown
    assert shown["value"] == "0x3f" and shown["pen"] == 0x10, shown
    index = mr.row_fields(mr.Row("i", 1, 900, 0xBF6, "guest", value=0x10, line=39,
                                 time_attoseconds=1), None, r, None)
    assert index["index"] == "0x10" and index["line"] == 39, index


def test_the_line_is_derived_once_by_the_capture_s_own_function_after_the_screen() -> None:
    """One derivation for both taps: the palette log's script carries `BEAM_LINE_LUA` itself,
    once, where the `screen` it reads is already declared."""
    script = rlua.install_script(LOG_ID, _ramdac(), Path("/s/h.txt"), Path("/s/r.rows"), None)
    assert script.count(capture.BEAM_LINE_LUA) == 1, "the capture's derivation, verbatim"
    assert script.index("local screen = nil") < script.index(capture.BEAM_LINE_LUA)
    assert script.index(capture.BEAM_LINE_LUA) < script.index('" %d %d %018d", beam_line(),')


def test_a_row_cut_inside_its_stamp_ends_the_read() -> None:
    """The attoseconds are written at their full eighteen digits: a row a reader sees half
    appended, cut inside them, is no row, as a capture's time is read."""
    whole = "i 1 900 bf6 g 10 40 2 000000000000000005"
    assert [r.time_attoseconds for r in mr.rows_of([whole])] == [
        2 * capture.ATTOSECONDS_PER_SECOND + 5]
    assert list(mr.rows_of([whole[:-12]])) == [], "a cut stamp is not read as another time"


def test_a_stamped_row_on_a_machine_with_no_screen_has_no_line_and_still_its_time() -> None:
    (row,) = mr.rows_of(["i 1 -1 bf6 g 10 -1 1 000000000000000005"])
    shown = mr.row_fields(row, None, _ramdac(), None)
    no_screen = {"available": False, "why": capture.NO_SCREEN_WHY}
    assert shown["line"] == no_screen == shown["frame"], "as a capture row says it"
    assert shown["time_s"] == (capture.ATTOSECONDS_PER_SECOND + 5) / 10**18, shown
