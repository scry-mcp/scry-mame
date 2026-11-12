"""The beam line and emulated time a capture row carries, and the capture on a READ trigger.

The install is run by the host's `lua` against a stand-in machine whose screen and clock are set
per access. The screen is 1942's (6 MHz, 384 x 262, vblank from line 240); the line must be
MAME's `vpos()`, which rounds to the nearest pixel, so a line's last half pixel is the next line.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lua_text import has
from session_doubles import refused, run_host_lua  # noqa: E402
from test_capture import COUNTER_ID, INSTALLED, _capturing  # noqa: E402
from test_tally import _answer, _sent  # noqa: E402

from scry_mame import (
    arming,  # noqa: E402
    callbacks,  # noqa: E402
    capture,  # noqa: E402
)
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import rearm as rearming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

PIXEL_S = 1 / 6_000_000
SCAN_S = 384 * PIXEL_S
FRAME_S = 262 * SCAN_S

HOST = f"""
TAPS = {{}}
local function space()
  local sp = {{data_width = 8, endianness = "little"}}
  function sp:install_write_tap(lo, hi, name, cb)
    TAPS[#TAPS + 1] = {{kind = "w", cb = cb}} return {{remove = function() end}}
  end
  function sp:install_read_tap(lo, hi, name, cb)
    TAPS[#TAPS + 1] = {{kind = "r", cb = cb}} return {{remove = function() end}}
  end
  function sp:read_direct_u8(a) READS = (READS or 0) + 1 return a & 0xff end
  return sp
end
NOW = {{seconds = 0, attoseconds = 0}}
UNTIL = 0.0
SCREEN = {{frame_period = {FRAME_S!r}, scan_period = {SCAN_S!r}, pixel_period = {PIXEL_S!r}}}
function SCREEN:time_until_pos(v, h) return UNTIL end
function SCREEN:frame_number() return 120 end
SCREENS = HAS_SCREEN and {{[":screen"] = SCREEN}} or {{}}
local cpu = {{tag = ":maincpu", spaces = {{program = space(), io = space()}},
             state = {{CURPC = {{value = 0x10}}}}}}
manager = {{machine = setmetatable({{devices = {{[":maincpu"] = cpu}}, screens = SCREENS,
                                    memory = {{shares = {{}}, regions = {{}}}},
                                    debugger = {{execution_state = "stop"}}}},
                                   {{__index = function(t, k)
                                     if k == "time" then return NOW end end}})}}
function manager.machine:logerror(s) end
emu = {{register_periodic = function(f) PERIODIC = f end}}
"""


def _at(seconds: int, attoseconds: int, line_s: float) -> str:
    """One access at that emulated time, `line_s` seconds into the frame."""
    return (f"NOW = {{seconds = {seconds}, attoseconds = {attoseconds}}}\n"
            f"UNTIL = {FRAME_S!r} - {line_s!r}\n"
            "TAPS[#TAPS].cb(0x12, 0xab, 0xff)\n")


def _ran(tmp_path: Path, accesses: str, trigger_type: str = "w",
         screen: bool = True) -> list[capture.Row]:
    """The capture's install run on the host machine, `accesses` made, rows read back."""
    head, rows = tmp_path / "h.txt", tmp_path / "r.rows"
    script = capture.install_script("x_t12", 0x12, capture.TapSource("space", "", 0x10),
                                    1, head, rows, ":maincpu", trigger_type=trigger_type)
    chunk = (f"HAS_SCREEN = {str(screen).lower()}\n" + HOST + script + "\n" + accesses
             + "PERIODIC()\n")
    out = run_host_lua(chunk)
    assert any(ln.startswith("MCP_TALLY installed") for ln in out), out
    return capture.first_rows(rows, capture.ROWS_MAX)


def test_a_row_carries_the_beam_line_and_the_access_time_as_known_answers(
        tmp_path: Path) -> None:
    """Mid-line 240 is 240, its last half pixel is 241, a frame's first instants are 0; the time
    is the clock's own, to the attosecond."""
    rows = _ran(tmp_path,
                _at(2, 28936333331304397, 240 * SCAN_S + 50 * PIXEL_S)
                + _at(2, 28936666664637730, 241 * SCAN_S - PIXEL_S / 4)
                + _at(3, 0, PIXEL_S / 8))
    assert [r.line for r in rows] == [240, 241, 0], rows
    assert [r.time_attoseconds for r in rows] == [2_028936333331304397, 2_028936666664637730,
                                         3_000000000000000000], rows
    assert [r.frame for r in rows] == [120, 120, 120]


def test_an_access_on_the_rounding_tie_takes_the_line_vpos_gives(tmp_path: Path) -> None:
    """Half a pixel before a line starts, `vpos()` gives that line (the tie rounds up); the
    derivation works in doubles, where the tie lands either side by a rounding error."""
    rows = _ran(tmp_path, "".join(_at(2, i, k * SCAN_S - PIXEL_S / 2)
                                  for i, k in enumerate((1, 2, 3, 120, 241, 261)))
                + _at(2, 9, FRAME_S - PIXEL_S / 2)
                + _at(2, 10, 3 * SCAN_S - PIXEL_S / 2 - PIXEL_S / 64))
    assert [r.line for r in rows] == [1, 2, 3, 120, 241, 261, 0, 2], (
        "the tie rounds up, and an access a sliver before it does not", [r.line for r in rows])


def test_a_row_on_a_machine_with_no_screen_carries_no_line_and_still_its_time(
        tmp_path: Path) -> None:
    (row,) = _ran(tmp_path, _at(1, 5, 0.0), screen=False)
    assert (row.frame, row.line, row.time_attoseconds) == (callbacks.NO_FRAME, callbacks.NO_FRAME,
                                                  1_000000000000000005), row
    shown = capture.row_fields(row, "u8", 1, 8, "little", ":maincpu")
    no_screen = {"available": False, "why": capture.NO_SCREEN_WHY}
    assert (shown["frame"], shown["line"]) == (no_screen, no_screen), shown
    assert shown["time_s"] == 1.000000000000000005


def test_a_row_as_a_reply_shows_its_line_and_its_time_in_seconds(tmp_path: Path) -> None:
    (row,) = _ran(tmp_path, _at(2, 28936333331304397, 240 * SCAN_S + 50 * PIXEL_S))
    shown = capture.row_fields(row, "u8", 1, 8, "little", ":maincpu")
    assert (shown["frame"], shown["line"]) == (120, 240), shown
    assert shown["time_s"] == 2.028936333331304397, "unrounded: a cycle is nanoseconds"
    assert list(shown)[:7] == ["n", "frame", "line", "time_s", "pc", "data", "mask"], list(shown)


def test_a_row_without_its_line_and_time_is_no_row(tmp_path: Path) -> None:
    """A row with no line and no time is not read as one whose pc is a line."""
    old = tmp_path / "old.rows"
    old.write_text("r 1 12 40e 1 ffff 00000000\n")
    assert capture.first_rows(old, 5) == []


def test_a_read_capture_taps_the_reads_and_reads_no_memory_inside_them(tmp_path: Path) -> None:
    """A read tap that reads memory in its callback re-enters the bus, which MAME does not
    survive: the row is the access alone, with no block."""
    (row,) = _ran(tmp_path, _at(2, 7, 109 * SCAN_S + PIXEL_S), trigger_type="r")
    assert (row.line, row.time_attoseconds, row.data, row.mask, row.block) == (
        109, 2_000000000000000007, 0xAB, 0xFF, b""), row
    script = capture.install_script("x_t12", 0x12, capture.TapSource("space", "", 0x10), 1,
                                    tmp_path / "h", tmp_path / "r", ":maincpu", trigger_type="r")
    assert "install_read_tap" in script and "install_write_tap" not in script
    assert "read_direct_u8" not in script and "read_u8" not in script, (
        "nothing in a read capture's install reads memory")
    shown = capture.row_fields(row, "", 1, 8, "little", ":maincpu")
    assert "block" not in shown and "raw_hex" not in shown, shown


def test_a_read_capture_runs_under_the_guard_and_counts_what_raised(tmp_path: Path) -> None:
    script = capture.install_script("x_t12", 0x12, capture.TapSource("space", "", 0x10), 1,
                                    tmp_path / "h", tmp_path / "r", ":maincpu", trigger_type="r")
    assert has(script, "install_read_tap(lo, lo + nb - 1, \"mcp_capture_\" .. id,\n    guarded(t,")


def test_watch_add_declares_a_read_capture_on_its_trigger_and_sends_a_read_tap(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _capturing(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x2031fe", mode="capture", trigger="0x2031fe", trigger_type="r")
    assert out["status"] == "ok" and out["trigger_type"] == "r", out
    assert b"install_read_tap" in _sent() and b"install_write_tap" not in _sent()
    (held,) = arming.store().declarations()
    assert (held.watch_mode, held.trigger, held.trigger_type) == ("capture", "0x2031fe", "r")


def test_a_read_capture_s_trigger_is_its_ref_when_not_named(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A read has no block, so `trigger` may be left out and defaults to the ref."""
    _capturing(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x2031fe", mode="capture", trigger_type="r")
    assert out["status"] == "ok" and out["trigger"] == "0x2031fe", out
    (held,) = arming.store().declarations()
    assert (held.trigger, held.trigger_type) == ("0x2031fe", "r")
    refused("only a capture", s.watch_add(ref="0x2031fc", mode="show", length=2,
                                          trigger_type="r"))


@pytest.mark.parametrize(("call", "said"), [
    (dict(ref="0x2031fc", fmt="u16[2]", trigger="0x2031fe"), "no block"),
    (dict(ref="0x2031fe", length=2, trigger="0x2031fe"), "no block"),
    (dict(ref="0x2031fe", fmt="u16", trigger="0x2031fe"), "no block"),
])
def test_a_block_on_a_read_trigger_is_refused_with_the_reason(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, call: dict[str, object],
        said: str) -> None:
    _capturing(monkeypatch, tmp_path)
    out = refused(said, s.watch_add(mode="capture", trigger_type="r", **call))
    assert "re-enters" in out["message"], out
    assert arming.store().declarations() == []


def test_a_trigger_type_is_a_captures_alone(monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:
    _capturing(monkeypatch, tmp_path)
    refused("only a capture", s.watch_add(ref="0x2031fe", mode="show", length=2,
                                          trigger_type="r"))


def test_a_read_capture_declaration_round_trips_and_differs_from_the_write_one() -> None:
    read = dec.Declaration("watch", "address", "0x6000", width=1, fmt="u8",
                           watch_mode="capture", trigger="0x6000", trigger_type="r")
    write = dec.Declaration("watch", "address", "0x6000", width=1, fmt="u8",
                            watch_mode="capture", trigger="0x6000")
    assert dec.Declaration.from_dict(read.to_dict()) == read
    assert read != write and write.trigger_type == "w"
    assert "trigger_type" not in write.to_dict(), (
        "a write capture's store row carries no trigger type")
    with pytest.raises(dec.DeclarationError, match="trigger type here"):
        dec.Declaration("watch", "address", "0x6000", width=1, fmt="u8", watch_mode="show",
                        trigger_type="r")


def test_a_stored_read_capture_comes_back_at_start_as_a_read_tap(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _capturing(monkeypatch, tmp_path)
    arming.store().add(dec.Declaration(
        "watch", "address", "0x2031fe", width=1, fmt="u8", watch_mode="capture",
        trigger="0x2031fe", trigger_type="r", origin="s1", cpu=":maincpu",
        fingerprint=mstate.STATE.fingerprint(":maincpu")))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert [d["ref"] for d in out["rearmed"]] == ["0x2031fe"], out
    assert _sent().count(b"install_read_tap") == 1 and b"install_write_tap" not in _sent()


def test_a_read_capture_where_nothing_handles_a_read_is_armed_saying_so(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _capturing(monkeypatch, tmp_path)
    ses.latches.add(0x780000)
    out = s.watch_add(ref="0x780000", mode="capture", trigger_type="r")
    assert out["status"] == "ok" and out["trigger_maps_to"] == "unmapped", out
    assert "nothing in the machine handles a read at 0x780000" in out["note"], out["note"]


def test_a_read_capture_of_a_port_or_with_no_read_side_is_refused(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A port's reads are not captured, and an unnamed read side is refused like a write's."""
    _capturing(monkeypatch, tmp_path)
    refused("taps a program address", s.watch_add(ref="0x6", mode="capture", trigger_type="r",
                                                  space="io"))
    from scry_mame import map as mmap
    plain = mmap.write_side
    monkeypatch.setattr(mmap, "write_side", lambda *a, **k: (*plain(*a, **k)[:2], None))
    out = refused("named no `Read:` side",
                  s.watch_add(ref="0x2031fe", mode="capture", trigger_type="r"))
    assert b"install_read_tap" not in _sent(), out


def test_one_ref_holds_one_capture_and_the_refusal_says_which_access_it_holds(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A write capture under a read capture's ref is a second declaration of it; the refusal
    says the held one captures the writes."""
    _capturing(monkeypatch, tmp_path)
    assert s.watch_add(ref="0x2031fe", mode="capture", length=1, trigger="0x2031fe")[
        "status"] == "ok"
    out = refused("on the trigger '0x2031fe' \\(its writes\\)",
                  s.watch_add(ref="0x2031fe", mode="capture", trigger_type="r"))
    assert out["code"] == "ambiguous_ref", out


def test_a_read_capture_listed_before_its_tap_says_it_is_one(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A row with no tap of this session still says which access it captures."""
    _capturing(monkeypatch, tmp_path)
    arming.store().add(dec.Declaration("watch", "address", "0x2031fe", width=1, fmt="u8",
                                       watch_mode="capture", trigger="0x2031fe",
                                       trigger_type="r", cpu=":maincpu",
                                       fingerprint=mstate.STATE.fingerprint(":maincpu")))
    (listed,) = s.declaration_list("watch")["watches"]
    assert listed["state"] == "not_installed" and listed["trigger_type"] == "r", listed


def test_watch_list_shows_a_read_captures_rows_with_no_block(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _capturing(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fe", mode="capture", trigger="0x2031fe", trigger_type="r")
    cid = capture.id_for(":maincpu", 0x2031FE, 1, 0x2031FE, trigger_type="r")
    assert cid.endswith("_t2031fer"), "a capture of the reads is not the one of the writes"
    _answer(tmp_path, 1, output=INSTALLED.replace(COUNTER_ID, cid))
    head, rows = capture.paths(tmp_path, cid)
    head.write_text(f"MCP_CAPTURE {cid} seq=2 frame=240 total=1 rows=1 overflow_rows=0 "
                    "data_width=16 endianness=big cpu=:maincpu\nend\n")
    rows.write_text("r 1 12 109 2.000000000000000007 40e 1234 ffff \n")
    (listed,) = s.declaration_list("watch")["watches"]
    assert listed["trigger_type"] == "r", listed
    assert listed["first_rows"] == [{"n": 1, "frame": 12, "line": 109,
                                     "time_s": 2.000000000000000007, "pc": "0x0000040e",
                                     "data": "0x1234", "mask": "0xffff",
                                     "symbol": "IRQ_VBLANK+0xe"}], listed["first_rows"]
