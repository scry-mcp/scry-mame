"""A watch on a write-only register takes its values from the bus, never from memory."""

from __future__ import annotations

from pathlib import Path

import pytest
from session_doubles import MAP_LATCH, MAP_RAM, MAP_ROM  # noqa: E402
from test_watches import _watching  # noqa: E402

from scry_mame import map as mmap  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

LATCH_HIT_1 = "Stopped at watchpoint 1 writing FFFF to 740000 (PC=00000528)\n"
LATCH_HIT_2 = "Stopped at watchpoint 1 writing A0A0 to 740000 (PC=00203176)\n"


def test_map_answers_both_sides_and_the_write_only_latch_is_told_from_ram() -> None:
    assert mmap.map_sides(MAP_LATCH) == {"read": "unmapped",
                                         "write": "m68k_dual_state::latch_w"}
    assert mmap.map_sides(MAP_RAM) == {"read": "memory@200000", "write": "memory@200000"}
    assert mmap.map_sides(MAP_ROM) == {"read": "memory@0", "write": "unmapped"}
    assert mmap.map_sides("garbage") == {"read": None, "write": None}


def test_a_change_watch_on_a_latch_takes_its_values_from_the_bus_and_reads_no_memory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    ses.latches.add(0x740000)
    out = s.watch_add(ref="0x740000", mode="change", length=2)
    assert out["status"] == "ok" and out["armed"] is True
    assert out["write_maps_to"] == "m68k_dual_state::latch_w"
    assert out["read_maps_to"] == "unmapped" and out["values_from"] == "bus"
    assert "reading" not in out, "a write-only register has no value to read"
    ram = s.watch_add(ref="frame_lo", mode="change", length=4)
    assert ram["values_from"] == "memory" and ram["read_maps_to"] == "memory@200000"
    assert ram["reading"]["available"] is True
    rows = {w["ref"]: w for w in s.declaration_list("watch")["watches"]}
    assert rows["0x740000"]["values_from"] == "bus" and rows["frame_lo"]["values_from"] == "memory"
    assert s.status()["in_debugger"]["watches"] == [
        {"ref": "0x740000", "cpu": ":maincpu"}, {"ref": "frame_lo", "cpu": ":maincpu"}], (
        "status names each armed")
    assert s.declaration_clear("watch", ref="0x740000")["status"] == "ok"
    assert s.status()["in_debugger"]["watches"] == [{"ref": "frame_lo", "cpu": ":maincpu"}], (
        "a cleared watch leaves the list")


def test_a_latch_hit_takes_before_and_after_from_the_writes_the_console_logged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    ses.latches.add(0x740000)
    s.watch_add(ref="0x740000", mode="change", length=2)
    (tmp_path / "debug.log").write_text("F2034\n")
    s.resume()
    (tmp_path / "debug.log").open("a").write(LATCH_HIT_1 + "25F6\n")
    ses.next_packet = "T05watch:740000;"
    ses.stops_after_polls = 1
    st = s.status()
    hit = mstate.STATE.last_stop["watch_hit"]
    assert (st["stopped_on_its_own"]["cause"]
            == "watch 0x740000: 0x00740000 written by pc 0x00000528")
    assert hit["values_from"] == "bus" and hit["after"] == 0xFFFF
    assert hit["before"]["available"] is False and "first write" in hit["before"]["why"], hit
    assert hit["writes"] == [{"wrote": "0xffff", "to": "0x00740000", "pc": "0x00000528"}]
    ses.packets = ["T05watch:740000;"]
    (tmp_path / "debug.log").open("a").write(LATCH_HIT_2 + "25F6\n")
    out = s.step()                     # a step that lands on the watch's own stop
    hit = out["watch_hit"]
    assert hit["before"] == 0xFFFF and hit["after"] == 0xA0A0 and hit["values_from"] == "bus"
    (w,) = [w for w in out["watches"] if w["ref"] == "0x740000"]
    assert w["state"] == "armed" and w["reading"]["state"] == "bus"
    assert w["reading"]["last_wrote"] == 0xA0A0 and "raw_hex" not in w["reading"]
    assert w["reading"]["read_maps_to"] == "unmapped"


def test_a_latch_stop_with_no_console_line_claims_no_hit_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With no console line there is neither a value nor a row to name."""
    ses = _watching(monkeypatch, tmp_path)
    ses.latches.add(0x740000)
    s.watch_add(ref="0x740000", mode="change", length=2)
    (tmp_path / "debug.log").write_text("F2034\n")
    s.resume()
    ses.next_packet = "T05watch:0;"
    ses.stops_after_polls = 1
    s.status()
    assert mstate.STATE.last_stop.get("watch_hit") is None
    assert "logged no line for it" in mstate.STATE.last_stop["cause"]


def test_a_row_this_server_holds_no_record_for_is_foreign_and_its_declaration_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row is known by the index recorded at arming, never by its range."""
    ses = _watching(monkeypatch, tmp_path)
    s.watch_add(ref="frame_lo", mode="change", length=4)
    mstate.STATE.armed_watches.clear()                # the row stays listed, the record is gone
    listed = s.declaration_list("watch")
    (row,) = listed["watches"]
    assert row["state"] == "gone" and "values_from" not in row
    assert listed["foreign"] == {"watches": ["1 @ 2031FC-2031FF write"]} and ses.wplist_rows
