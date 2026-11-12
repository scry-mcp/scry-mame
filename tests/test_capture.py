"""A watch that CAPTURES (`capture`): the whole block recorded at each write to a trigger.

Known answers are CAPTURED on m68k-dual (`fixtures/capture/PROVENANCE.txt`), each beside a
control that counted the trigger's writes over the same pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from lua_text import has, squash
from scry_core import value_format as vf  # noqa: E402
from session_doubles import refs, refused, use_table  # noqa: E402
from test_callbacks import assert_every_callback_guarded  # noqa: E402
from test_machine import _cached  # noqa: E402
from test_tally import (  # noqa: E402
    _answer,
    _sent,
    _survey,
    _tallying,
)
from test_watches import _WatchSession  # noqa: E402

from scry_mame import (
    arming,  # noqa: E402
    capture,  # noqa: E402
    inputs,  # noqa: E402
    transport,  # noqa: E402
    watches,  # noqa: E402
)
from scry_mame import declarations as dec  # noqa: E402
from scry_mame import rearm as rearming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "capture"
COUNTER_ID = "2031fc_4_t2031fe"
BLIT_ID = "700010_10_t70001e"
INSTALLED = (FIXTURES / "installed.txt").read_text().strip()
OWNER = ("0x2031fc", ":maincpu")


def _capturing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _WatchSession:
    """The tally's double with m68k-dual's captured address map and the symbols placing its
    writers."""
    ses = _tallying(monkeypatch, tmp_path)
    _cached(monkeypatch, tmp_path)
    use_table(monkeypatch, table={"FRAME_LO": 0x2031FC, "IRQ_VBLANK": 0x400,
                                  "BLIT_DRIVER_A": 0x25DC, "BLIT_DRIVER_B": 0x2856})
    return ses


def _placed(tmp_path: Path, capture_id: str, name: str) -> None:
    """The captured header and rows where the periodic hook of `capture_id` writes them."""
    head, rows = capture.paths(tmp_path, capture_id)
    head.write_text((FIXTURES / f"{name}.txt").read_text())
    rows.write_text((FIXTURES / f"{name}.rows").read_text())




def test_the_tap_sits_on_the_triggers_word_keeps_its_lanes_and_reads_the_block_it_names() -> None:
    """A tap needs bus-aligned ends, so it covers the trigger's whole bus word and the callback
    keeps only a write whose mask names the trigger's lane; past the cap a write is only
    counted."""
    src = capture.TapSource("share", ":blitram", 0x10)
    script = capture.install_script(BLIT_ID, 0x70001E, src, 10, Path("/s/h.txt"),
                                    Path("/s/r.rows"), ":maincpu")
    assert has(script, "install_write_tap(lo, lo + nb - 1,")
    assert has(script, "local lane = trig - lo")
    assert has(script, "if ((mask >> shift) & 0xff) == 0 then return end")
    assert has(script, 'local blk = mem.shares[":blitram"]\nif blk'), "one lookup, the full tag"
    assert has(script, "blk:read_u8(off + i)")
    assert has(script, f"if t.rows >= {capture.ROWS_MAX} then t.overflow_rows")
    assert 'local cpu = manager.machine.devices[":maincpu"]\n' in script, (
        "the cpu is bound when the chunk is composed")
    assert script.index("old.tap:remove()") < script.index("install_write_tap")
    assert has(script,
               '"rows", "overflow_rows", "pending", "npending", "errors", "first_error",'), (
        "a rerun carries the rows and the errors it had, and never doubles nor zeroes them")
    assert has(script, 'io.open(it.rows_path, "a")'), "the rows file only grows"
    assert has(script, "replace(it.head"), "the header is whole or absent"
    assert has(script, '"%s installed tally_id=%s trigger=%x ", "MCP_TALLY", id,'), (
        "the count watch's reader answers it")
    assert len(script) < transport.SCRIPT_MAX
    plain = capture.install_script(COUNTER_ID, 0x2031FE, capture.TapSource("space", "", 0x2031FC),
                                   4, Path("/s/h.txt"), Path("/s/r.rows"))
    assert "sp:read_direct_u8(off + i)" in plain and "mem.shares" not in plain


def test_a_captured_header_and_its_rows_parse_whole_and_a_cut_one_reads_as_none(
    tmp_path: Path,
) -> None:
    head = capture.parse_capture_header((FIXTURES / "counter.txt").read_text())
    assert head is not None
    assert (head["id"], head["rows"], head["overflow_rows"], head["total"]) == (
        COUNTER_ID, 230, 0, 230)
    assert (head["frame"], head["data_width"], head["endianness"]) == (241, 16, "big")
    assert capture.parse_capture_header((FIXTURES / "counter.txt").read_text().replace("end\n",
                                                                                       "")) is None
    assert capture.parse_capture_header("MCP_CAPTURE x seq=1\nend\n") is None
    cut = tmp_path / "cut.rows"
    cut.write_text("r 1 12 256 0.2 40e 1 ffff 00000000\n"
                   "r 1 12 256 0.252239437500000000 40e 1 ffff 00000000\n"
                   "r 2 12 256 0.259850062500000000 40e 2 ff\n"
                   "r 3 13 256 0.279850062500000000 40e 3 ffff 00000002\n")
    assert [r.n for r in capture.first_rows(cut, 5)] == [], (
        "a time cut short of its eighteen digits is no row, and ends the read")
    cut.write_text(cut.read_text().split("\n", 1)[1])
    assert [r.n for r in capture.first_rows(cut, 5)] == [1], (
        "a line of another shape ends the read: what follows it is not known to be rows")
    assert capture.first_rows(tmp_path / "none.rows", 5) == []


def test_known_answer_every_row_holds_the_trigger_word_from_before_its_write() -> None:
    """A tap runs before the write lands, so each row's block holds the counter from before it: one
    less than the row's `data`. One row per write the control counted."""
    rows = capture.first_rows(FIXTURES / "counter.rows", capture.ROWS_MAX)
    head = capture.parse_capture_header((FIXTURES / "counter.txt").read_text())
    assert head is not None and len(rows) == head["rows"] == head["total"] == 230
    for r in rows:
        assert (r.pc, r.mask) == (0x40E, 0xFFFF), (r.n, r.pc, r.mask)
        high, low = int.from_bytes(r.block[:2], "big"), int.from_bytes(r.block[2:], "big")
        assert (high, low) == (0, r.data - 1), (r.n, r.data, r.block.hex())
    assert [r.data for r in rows] == list(range(1, 231)), "one row per write, in write order"


def test_known_answer_the_vblank_handlers_write_lands_on_the_line_the_driver_raises_it() -> None:
    """The frame counter's write is IRQ_VBLANK's, raised at scanline `NUM_SCANLINES` (256, past
    the 252 visible): every row from the second on is stamped line 256, and two rows sit one
    frame apart."""
    rows = capture.first_rows(FIXTURES / "counter.rows", capture.ROWS_MAX)
    assert rows[0].line == 137 and {r.line for r in rows[1:]} == {256}, rows[:3]
    times = [r.time_attoseconds for r in rows]
    assert times == sorted(times) and len(set(times)) == len(times)
    gaps = {b.time_attoseconds - a.time_attoseconds for a, b in zip(rows[1:], rows[2:],
                                                                    strict=False)}
    pixels_per_line, pixel_hz, field_lines = 512, 32_000_000 // 4, 312
    line_as = pixels_per_line * capture.ATTOSECONDS_PER_SECOND // pixel_hz
    assert all(abs(gap - field_lines * line_as) < line_as for gap in gaps), sorted(gaps)[:4]


def test_known_answer_two_routines_each_row_carries_its_own_writer_and_block() -> None:
    """The blitter's words written by two drivers: each row is one trigger write with its own pc
    and block."""
    rows = capture.first_rows(FIXTURES / "blit.rows", 100)
    assert len(rows) == 14
    pcs = [r.pc for r in rows]
    assert len(set(pcs)) == 14, "every trigger write here is a different instruction"
    assert all(0x25DC <= pc < 0x2856 for pc in pcs[:9]), "BLIT_DRIVER_A's"
    assert all(pc >= 0x2856 for pc in pcs[9:]), "BLIT_DRIVER_B's"
    assert [r.data for r in rows[:4]] == [0xFFFF, 0x0000, 0xFFFF, 0x0000]
    blocks = [r.block.hex() for r in rows]
    assert blocks[0] == "00" * 10 and blocks[1] == "c000" + "00" * 8
    assert blocks[4].endswith("00ff") and blocks[6] == "c0000008" + "00" * 4 + "00ff"
    assert blocks[11] == "c000" + "00" * 6 + "00ff", "B clears the word A set, and the row says so"




def test_a_capture_is_sent_pending_on_its_triggers_word_with_the_block_read_from_its_share(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _capturing(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031fe")
    assert out["status"] == "ok" and out["state"] == "pending", out
    assert (out["installed"], out["pending"], out["tally_id"], out["trigger"]) == (
        False, True, COUNTER_ID, "0x2031fe"), "an address trigger is kept in a ref's one spelling"
    assert out["trigger_addr"] == "0x002031fe"
    assert out["source"] == {"kind": "share", "tag": ":mainram", "offset": "0x000031fc"}
    assert out["session"]["altered"] is False, "a capture reads and never writes"
    assert "map 0x2031fe::maincpu" in ses.commands, "the trigger's write side is asked"
    assert b"install_write_tap" in _sent() and b"_G.MCP_CAPTURE" in _sent()
    (held,) = arming.store().declarations()
    assert (held.watch_mode, held.trigger, held.width) == ("capture", "0x2031fe", 4)


def test_a_capture_surveys_its_rows_as_the_periodic_wrote_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _capturing(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031fe")
    _answer(tmp_path, 1, output=INSTALLED)
    _placed(tmp_path, COUNTER_ID, "counter")
    item = _survey(ses, 240)
    assert (item["state"], item["installed"], item["cpu"]) == ("captured", True, ":maincpu"), item
    assert (item["rows_kept"], item["overflow_rows"], item["total"]) == (230, 0, 230)
    assert "rows" not in item, "the rows the file keeps are `rows_kept`, as palette_log's"
    assert item["since_last_stop"] == 230 and item["rows_max"] == capture.ROWS_MAX
    assert item["rows_path"] == str(capture.paths(tmp_path, COUNTER_ID)[1])
    # a stop counts the capture and lists none of its rows (`declaration_list` does)
    assert "first_rows" not in item, item
    assert _survey(ses, 240)["since_last_stop"] == 0, "the same dump is no new row"
    listed = s.declaration_list("watch")["watches"][0]
    assert listed["state"] == "captured" and listed["rows_kept"] == 230
    first = listed["first_rows"]
    assert isinstance(first, list) and len(first) == 24, (
        "the list shows the first rows, the file holds them all")
    assert first[1] == {"n": 2, "frame": 12, "line": 256, "time_s": 0.2598500625,
                        "pc": "0x0000040e", "data": "0x0002", "mask": "0xffff",
                        "raw_hex": "00000001", "symbol": "IRQ_VBLANK+0xe", "block": [0, 1]}
    assert len(Path(listed["rows_path"]).read_text().splitlines()) == 230, "the file holds all"


def _listed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fmt: str, fill: str,
            n: int = 300) -> dict[str, Any]:
    """`declaration_list(kind="watch")` over a capture of `fmt`, `n` rows past the reply."""
    _capturing(monkeypatch, tmp_path)
    width = vf.parse(fmt).width_for(0)
    out = s.watch_add(ref="0x2031fc", mode="capture", fmt=fmt, trigger="0x2031fe")
    assert out["status"] == "ok", out
    cid = capture.id_for(":maincpu", 0x2031FC, width, 0x2031FE)
    _answer(tmp_path, 1, output=INSTALLED.replace(COUNTER_ID, cid))
    head, rows = capture.paths(tmp_path, cid)
    head.write_text(f"MCP_CAPTURE {cid} seq=2 frame=240 total={n} rows={n} overflow_rows=0 "
                    "data_width=16 endianness=big cpu=:maincpu\nend\n")
    block = fill * (2 * width // len(fill))
    # the widest stamps a row prints
    rows.write_text("".join(f"r {i + 1} {12 + i} 1023 3600.123456789012345678 40e ffff ffff "
                            f"{block}\n" for i in range(n)))
    listed: dict[str, Any] = s.declaration_list("watch")
    return listed


def test_watch_list_shows_the_widest_capture_inside_the_reply_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The widest block a capture accepts, decoded to its widest JSON: the first `ROWS_SHOWN`
    rows fit the reply budget and `rows_path` holds the rest."""
    out = _listed(monkeypatch, tmp_path, "f32[32]", "ff7fffff")
    item = out["watches"][0]
    assert item["state"] == "captured" and item["rows_kept"] == 300, item.get("state")
    assert len(item["first_rows"]) == mstate.ROWS_SHOWN
    assert len(json.dumps(item["first_rows"][0]["block"])) == watches.capture_block_chars_max()
    assert len(json.dumps(out)) < mstate.REPLY_BUDGET_CHARS, len(json.dumps(out))
    monkeypatch.setattr(mstate, "ROWS_SHOWN", 300)
    assert len(json.dumps(s.declaration_list("watch"))) > mstate.REPLY_BUDGET_CHARS, "the control"


WIDEST_FILL = {"u8": "ff", "i8": "80", "u16": "ffff", "i16": "8000", "u32": "ffffffff",
               "i32": "80000000", "f32": "ff7fffff", "f64": "ffefffffffffffff", "char": "80"}


@pytest.mark.parametrize("elem", list(WIDEST_FILL))
def test_the_block_bound_is_the_json_the_widest_bytes_decode_to(elem: str) -> None:
    """The bound is exactly the JSON the widest bytes of each scalar decode to."""
    n = watches.SHOW_WATCH_MAX // vf.SCALARS.get(elem, ("", 1))[1]
    fmt = vf.parse(f"{elem}[{n}]")
    raw = bytes.fromhex(WIDEST_FILL[elem] * n)
    assert capture.block_chars_max(fmt, watches.SHOW_WATCH_MAX) == len(
        json.dumps(fmt.decode(raw, "big")))


def test_the_capture_bound_is_the_widest_array_a_capture_holds() -> None:
    widest = max(capture.block_chars_max(vf.parse(f"{e}[{watches.SHOW_WATCH_MAX // w}]"),
                                         watches.SHOW_WATCH_MAX)
                 for e, (_c, w) in vf.SCALARS.items())
    assert watches.capture_block_chars_max() == max(
        widest, capture.block_chars_max(vf.parse(f"char[{watches.SHOW_WATCH_MAX}]"), 0))


def _struct(chars: int, n: int = 32) -> str:
    """A struct of `n` one-byte fields whose widest decoded JSON is exactly `chars` characters."""
    names = [f"f{i:03d}" for i in range(n)]
    base = capture.block_chars_max(vf.parse("{" + ",".join(f"{a}:i8" for a in names) + "}"), 0)
    assert base <= chars, "even the shortest names are past the bound at this many fields"
    names[0] += "x" * (chars - base)
    return "{" + ",".join(f"{a}:i8" for a in names) + "}"


def test_a_struct_at_the_bound_lists_inside_the_budget_and_one_past_it_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A format is refused at `watch_add` when its widest decoded block is wider than the widest
    an array or string makes over the largest block; at the bound it lists inside the budget,
    one past it is refused."""
    fits = _struct(watches.capture_block_chars_max())
    out = _listed(monkeypatch, tmp_path, fits, "80")
    assert len(json.dumps(out["watches"][0]["first_rows"][0]["block"])) == (
        watches.capture_block_chars_max())
    assert len(json.dumps(out)) < mstate.REPLY_BUDGET_CHARS, len(json.dumps(out))
    s.declaration_clear("watch", all=True)
    sent = _sent().count(b"install_write_tap")
    over = s.watch_add(ref="0x2031fc", mode="capture",
                       fmt=_struct(watches.capture_block_chars_max() + 1), trigger="0x2031fe")
    refused(rf"widest row .*{watches.capture_block_chars_max() + 1} characters", over)
    assert over["code"] == "bad_argument", over
    assert _sent().count(b"install_write_tap") == sent, "nothing sent"
    assert not [d for d in arming.store().declarations() if d.watch_mode == "capture"]


def test_rows_past_the_cap_are_counted_and_said(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With the cap at three: three rows kept, the rest counted."""
    ses = _capturing(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031fe")
    _answer(tmp_path, 1, output=INSTALLED)
    _placed(tmp_path, COUNTER_ID, "counter-capped")
    item = _survey(ses, 240)
    assert (item["rows_kept"], item["overflow_rows"], item["total"]) == (3, 227, 230), item
    rows = s.declaration_list("watch")["watches"][0]["first_rows"]
    assert isinstance(rows, list) and [r["n"] for r in rows] == [1, 2, 3]


def test_a_capture_is_refused_without_a_trigger_by_pointer_or_wider_than_a_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    refused("needs `trigger`", s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]"))
    refused("only a capture takes one",
            s.watch_add(ref="0x2031fc", mode="count", length=4, trigger="0x2031fe"))
    refused("only a change watch", s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]",
                                               trigger="0x2031fe", condition="wpdata==1"))
    refused("above 128", s.watch_add(ref="0x2031fc", mode="capture", length=256,
                                     trigger="0x2031fe"))
    _capturing(monkeypatch, tmp_path)
    refused("by symbol or by address",
            s.watch_add(ref="[frame_lo]+4", mode="capture", length=2, trigger="0x2031fe"))


def test_a_trigger_this_build_lacks_is_refused_and_one_nothing_handles_is_armed_saying_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A name the build lacks sends nothing; an unmapped write side is armed, and the note says
    where it goes."""
    ses = _capturing(monkeypatch, tmp_path)
    out = refused(re.escape(inputs.not_a_ref("the trigger", "gone_sym", ":maincpu")),
                  s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="gone_sym"))
    assert out["code"] == "unknown_ref"
    assert _sent() == b"" and arming.store().declarations() == []
    ses.rom_write_unmapped.add(0x7B8)
    out = s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x7b8")
    assert out["status"] == "ok" and out["trigger_maps_to"] == "unmapped", out
    assert out["note"].startswith("the tap is installed"), "the install's note kept"
    assert "; the trigger: nothing in the machine handles a write at 0x7b8" in out["note"], out
    assert b"install_write_tap" in _sent()


def test_a_block_no_memory_backs_is_refused_before_anything_is_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A block no share or region holds, whose read side is a handler, is refused: reading it
    would run it."""
    ses = _capturing(monkeypatch, tmp_path)
    ses.latches.update({0x780000, 0x780003})
    out = refused("has no memory a tap can read",
                  s.watch_add(ref="0x780000", mode="capture", length=4, trigger="0x2031fe"))
    assert out["code"] == "bad_argument" and _sent() == b""


def test_one_block_on_one_trigger_is_one_capture_and_another_trigger_is_another(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _capturing(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031fe")
    use_table(monkeypatch, table={"FRAME_LO": 0x2031FC})
    refused(re.escape("already captured under '0x2031fc': one capture is one declaration, so "
                      "`declaration_clear(kind=\"watch\", ref='0x2031fc', cpu=\":maincpu\")` frees "
                      "it, or use that ref"),
            s.watch_add(ref="frame_lo", mode="capture", fmt="u16[2]", trigger="0x2031fe"))
    refused(re.escape("on the trigger '0x2031fe'"),
            s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031fc"))
    assert s.watch_add(ref="frame_lo", mode="capture", fmt="u16[2]",
                       trigger="0x2031fc")["status"] == "ok", "the same block on another trigger"


def test_a_cleared_capture_sends_its_removal_to_its_own_registry_and_drops_both_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _capturing(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031fe")
    _placed(tmp_path, COUNTER_ID, "counter")
    out = s.declaration_clear("watch", ref="0x2031fc")
    assert out["tallies_removed"][0]["tally_id"] == COUNTER_ID, out
    assert b"local T = _G.MCP_CAPTURE" in _sent().splitlines()[-1]
    assert not any(p.exists() for p in capture.paths(tmp_path, COUNTER_ID))


def test_a_pending_capture_reads_no_files_another_tap_left_on_its_range(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The count watch's rule: until its install answered, nothing at its paths is its own."""
    ses = _capturing(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031fe")
    _placed(tmp_path, COUNTER_ID, "counter")
    item = watches.evaluate_watches(ses, frame=61)[0]  # type: ignore[arg-type]
    assert (item["installed"], item["pending"]) == (False, True), item
    assert item["state"] == "no_dump_yet", item
    assert "total" not in item and "rows" not in item, item


def test_a_capture_installed_over_no_tap_removes_the_files_a_removed_one_left(
    tmp_path: Path,
) -> None:
    """Rows are appended: a re-declaration over a live tap keeps the file; over none, the files
    go."""
    head, rows = capture.paths(tmp_path, "c")
    src = capture.TapSource("space", "", 0x100)
    script = squash(capture.install_script("c", 0x10, src, 2, head, rows))
    removal = squash('if old == nil then os.remove(head) os.remove(head .. ".tmp") os.remove(rows) '
                     "end")
    assert script.count(removal) == 1, script
    assert script.index(squash("local old = T.items[id]")) < script.index(removal), (
        "old is read first")
    assert script.index(removal) < script.index(squash("T.items[id] = t"))


def test_a_stored_capture_comes_back_at_start_and_one_on_a_lost_trigger_is_unresolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _capturing(monkeypatch, tmp_path)
    store = arming.store()
    store.add(dec.Declaration("watch", "symbol", "frame_lo", width=4, fmt="u16[2]",
                              watch_mode="capture", trigger="0x2031fe", origin="s1",
                              cpu=":maincpu", fingerprint=mstate.STATE.fingerprint(":maincpu")))
    store.add(dec.Declaration("watch", "symbol", "frame_lo", width=2, fmt="u16",
                              watch_mode="capture", trigger="gone_sym", origin="s1",
                              cpu=":subcpu"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["rearmed"]) == ["frame_lo"] and refs(out["unresolved"]) == ["frame_lo"], out
    assert _sent().count(b"install_write_tap") == 1
    listed = [w for w in s.declaration_list("watch")["watches"] if w["cpu"] == ":subcpu"]
    assert listed[0]["state"] == "unresolved" and "gone_sym" in listed[0]["why"], listed


def test_a_capture_declaration_carries_its_trigger_and_only_a_capture_does() -> None:
    cap = dec.Declaration("watch", "address", "0x700010", width=10, fmt="u16[5]",
                          watch_mode="capture", trigger="0x70001e")
    assert dec.Declaration.from_dict(cap.to_dict()) == cap
    assert cap.to_dict()["trigger"] == "0x70001e"
    assert cap.adopted_by("s2", "t2").trigger == "0x70001e"
    with pytest.raises(dec.DeclarationError, match="only it, carries a trigger"):
        dec.Declaration("watch", "address", "0x700010", width=10, fmt="u16[5]",
                        watch_mode="capture")
    with pytest.raises(dec.DeclarationError, match="only it, carries a trigger"):
        dec.Declaration("watch", "address", "0x700010", width=10, fmt="u16[5]",
                        watch_mode="count", trigger="0x70001e")
    by_name = dec.Declaration("watch", "symbol", "blit_words", width=10, fmt="u16[5]",
                              watch_mode="capture", trigger="0x70001e", fingerprint="old")
    assert dec.is_stale(by_name, "new"), "a raw trigger over another build is stale"
    assert not dec.is_stale(by_name, "old")
    named = dec.Declaration("watch", "symbol", "blit_words", width=10, fmt="u16[5]",
                            watch_mode="capture", trigger="blit_start", fingerprint="old")
    assert not dec.is_stale(named, "new"), "a trigger by name re-resolves"


def test_the_capture_leaves_the_tally_state_to_the_tally(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A count and a capture over the same range are two taps, each surveyed in its own words."""
    ses = _capturing(monkeypatch, tmp_path)
    assert s.watch_add(ref="frame_lo", mode="capture", fmt="u16[2]",
                       trigger="0x2031fe")["status"] == "ok"
    assert s.watch_add(ref="0x2031fc", mode="count", length=4)["status"] == "ok"
    states = {w["ref"]: w["state"] for w in watches.evaluate_watches(ses, frame=1)}  # type: ignore[arg-type]
    assert states == {"frame_lo": "no_dump_yet", "0x2031fc": "no_dump_yet"}, states
    assert set(mstate.STATE.tallies) == {("frame_lo", ":maincpu"), OWNER}




def _map(*entries: tuple[int, int, str]) -> dict[str, object]:
    """An address map of `:maincpu`'s program space from `(start, end, share)` rows, in install
    order."""
    return {"address_map": [
        {"cpu": ":maincpu", "space": "program", "index": i, "start": f"{s:#010x}",
         "end": f"{e:#010x}", **({"share": sh} if sh else {})}
        for i, (s, e, sh) in enumerate(entries, start=1)]}


def test_an_overlaid_block_is_never_read_from_the_memory_under_the_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bus answers with the entry installed last, so a share overlaid by a handler is
    refused."""
    monkeypatch.setattr(mstate.STATE, "machine_map",
                        _map((0x100000, 0x10FFFF, ":mainram"), (0x10F000, 0x10F0FF, "")))
    asked: list[int] = []

    def read_side(at: int) -> str | None:
        asked.append(at)
        return "blit_w" if at >= 0x10F000 else "memory@100000"

    with pytest.raises(mstate.Invalid, match="no memory a tap can read at 0x10f000"):
        capture.source(0x10F000, 10, ":maincpu", read_side)
    assert asked == [0x10F000]
    assert capture.source(0x100010, 4, ":maincpu", read_side) == capture.TapSource(
        "share", ":mainram", 0x10), "a block only the share reaches is read there"


def test_a_block_with_a_handler_inside_is_refused_where_the_handler_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direct read of a handler answers zeros that look like data, so every entry reaching the
    block is asked."""
    monkeypatch.setattr(mstate.STATE, "machine_map", _map(
        (0x300000, 0x30000F, ""), (0x300010, 0x30001F, ""), (0x300020, 0x30002F, "")))
    sides = {0x300000: "memory@300000", 0x300010: "latch_w", 0x300020: "memory@300020",
             0x30002F: "memory@300020"}
    with pytest.raises(mstate.Invalid, match="at 0x300010"):
        capture.source(0x300000, 0x30, ":maincpu", sides.get)
    del sides[0x300010]
    sides[0x300010] = "memory@300010"
    assert capture.source(0x300000, 0x30, ":maincpu", sides.get).kind == "space"


def test_a_block_in_rom_is_read_from_its_region(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The map backs the main cpu's code with the region `:maincpu`: a capture there reads it at
    an offset."""
    _capturing(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x400", mode="capture", length=4, trigger="0x2031fe")
    assert out["source"] == {"kind": "region", "tag": ":maincpu", "offset": "0x00000400"}, out
    assert b'mem.regions[\\":maincpu\\"]' in _sent(), "the chunk goes out quoted"



def test_two_spellings_of_one_trigger_are_one_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _capturing(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031FE")
    again = s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031fe")
    assert again["status"] == "ok" and again["already_stored"] is True, again


def test_a_stale_capture_is_listed_stale_and_not_as_an_install_that_never_came(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _capturing(monkeypatch, tmp_path)
    arming.store().add(dec.Declaration("watch", "address", "0x2031fc", width=4, fmt="u16[2]",
                                       watch_mode="capture", trigger="0x2031fe", origin="s1",
                                       cpu=":maincpu", fingerprint="another build"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert refs(out["stale"]) == ["0x2031fc"], out
    (listed,) = s.declaration_list("watch")["watches"]
    assert listed["state"] == "stale" and "another build" in listed["why"], listed


def test_an_install_answer_is_its_own_taps_line_among_others_sent_with_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Another tap's `installed` line can land between the mark and this record's sentinel; the
    second line is the captured count watch's with its cpu replaced by `:subcpu`."""
    _capturing(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031fe")
    other = ("MCP_TALLY installed tally_id=2031fe_1_subcpu first=2031fe last=2031fe "
             "data_width=16 endianness=big cpu=:subcpu")
    _answer(tmp_path, 1, output=other + "\n" + INSTALLED)
    item = s.declaration_list("watch")["watches"][0]
    assert (item["installed"], item["cpu"]) == (True, ":maincpu"), item


def test_every_callback_a_capture_installs_runs_under_the_guard() -> None:
    for src in (capture.TapSource("share", ":blitram", 0x10), capture.TapSource("space", "", 0)):
        assert_every_callback_guarded(capture.install_script(
            BLIT_ID, 0x70001E, src, 10, Path("/s/h.txt"), Path("/s/r.rows"), ":maincpu"), 1, 0)


def test_a_row_is_counted_only_once_it_is_kept() -> None:
    """A body that raises half-way leaves no counted row that was never appended."""
    script = capture.install_script(COUNTER_ID, 0x2031FE, capture.TapSource("space", "", 0x2031FC),
                                    4, Path("/s/h.txt"), Path("/s/r.rows"))
    body = script.split("install_write_tap")[1].split("T.items[id] = t")[0]
    assert body.index("t.pending[n] = ") < body.index("t.npending, t.rows, t.dirty = n,"), body
    assert "t.rows = t.rows + 1" not in body and "t.npending = t.npending + 1" not in body


def test_a_capture_whose_tap_raised_says_so_and_is_never_an_empty_census(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A body that raised at every write kept no row: the errors ride beside the rows, at a stop
    and in the list."""
    ses = _capturing(monkeypatch, tmp_path)
    s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="0x2031fe")
    _answer(tmp_path, 1, output=INSTALLED)
    head, rows = capture.paths(tmp_path, COUNTER_ID)
    head.write_text((FIXTURES.parent / "callbacks" / "capture-raised.txt").read_text())
    rows.write_text("")
    item = _survey(ses, 904)
    assert item["callback_errors"] == {"count": 4, "first": "mcp:3: planted fault"}, item
    assert (item["state"], item["rows_kept"], item["total"]) == ("captured", 2, 2)
    listed = s.declaration_list("watch")["watches"][0]
    assert listed["callback_errors"]["count"] == 4
    clean = capture.parse_capture_header((FIXTURES / "counter.txt").read_text())
    assert clean is not None and clean["errors"] == 0, "a guarded tap that never raised"
    silent = capture.parse_capture_header("MCP_CAPTURE 2031fc_4_t2031fe seq=3 frame=12 total=0 "
                                          "rows=0 overflow_rows=0 data_width=16 endianness=big "
                                          "cpu=:maincpu\nend\n")
    assert silent is not None and silent["errors"] is None, "a header that does not say"
    assert capture.parse_capture_header("MCP_CAPTURE 2031fc_4_t2031fe seq=3 frame=12 total=0 "
                                        "rows=0 overflow_rows=0 data_width=16 endianness=big "
                                        "cpu=:maincpu errors=0\nend\n") is not None


def test_a_capture_that_cannot_open_its_rows_file_keeps_the_others_flushing() -> None:
    script = capture.install_script(COUNTER_ID, 0x2031FE, capture.TapSource("share", ":mainram", 0),
                                    4, Path("/s/h.txt"), Path("/s/r.rows"))
    # each item's dump is its own call from the shared dumper, so a `return` in it ends that item
    dump = script.split("local function dump(it, fr)")[1].split("dump_at_stops(T, dump)")[0]
    assert has(dump, "if r ~= nil then") and has(dump, "if f == nil then return end"), dump
    assert has(script, "dump_at_stops(T, dump)")


def test_a_trigger_by_name_is_placed_through_the_table_and_kept_as_typed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _capturing(monkeypatch, tmp_path)
    out = s.watch_add(ref="0x2031fc", mode="capture", fmt="u16[2]", trigger="frame_lo")
    assert out["trigger_addr"] == "0x002031fc" and out["trigger"] == "frame_lo", out
    assert arming.store().declarations()[0].trigger == "frame_lo", "a name re-resolves"


def test_the_block_captures_are_the_ones_with_a_write_trigger_in_order_on_a_bare_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One predicate for every reader: a count watch is no capture, and a manifest's bare
    `subcpu` is the owner's."""
    monkeypatch.setattr(mstate.STATE, "tallies", {
        ("b", ":subcpu"): {"trigger": 0x10},
        ("count", ":maincpu"): {"width": 4},
        ("a", ":maincpu"): {"trigger": 0x20},
        ("0x30", ":maincpu"): {"trigger": 0x30, "trigger_type": "r"},
    })
    assert [o for o, _ in capture.block_captures()] == [("b", ":subcpu"), ("a", ":maincpu")], (
        "a read capture holds no block, and every caller here reads one")
    assert [o for o, _ in capture.block_captures("subcpu")] == [("b", ":subcpu")]
    assert [o for o, _ in capture.block_captures(":maincpu")] == [("a", ":maincpu")]
    assert capture.block_captures("audiocpu") == []


@pytest.mark.parametrize("space", ["program", "io"])
def test_a_block_the_table_types_as_a_struct_past_the_bound_is_refused_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, space: str,
) -> None:
    """The bound is judged once the format is known, whether from the symbol table or a port
    trigger."""
    from session_doubles import io_board
    ses = _capturing(monkeypatch, tmp_path)
    wide = _struct(watches.capture_block_chars_max() + 1)
    use_table(monkeypatch, table={**mstate.STATE.table(":maincpu").table, "BLK": 0x2031FC},
              types={"BLK": wide})
    if space == "io":
        io_board(monkeypatch, ses)
    out = s.watch_add(ref="blk", mode="capture", trigger="0x6" if space == "io" else "0x2031fe",
                      space=space)
    refused("widest row", out)
    assert out["code"] == "bad_argument", out


def test_a_stored_capture_whose_format_is_past_the_bound_is_unarmable_at_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A capture stored before the bound re-arms at `start` judged there too: `unarmable`,
    nothing sent."""
    ses = _capturing(monkeypatch, tmp_path)
    wide = _struct(watches.capture_block_chars_max() + 1)
    assert arming.store() is not None
    arming.store().add(dec.Declaration("watch", "address", "0x2031fc", width=32, fmt=wide,
                                       watch_mode="capture", trigger="0x2031fe",
                                       fingerprint="fp-test", cpu=":maincpu"))
    sent = _sent().count(b"install_write_tap")
    account = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert [u["ref"] for u in account["unarmable"]] == ["0x2031fc"], account
    assert "widest row" in account["unarmable"][0]["why"], account
    assert _sent().count(b"install_write_tap") == sent, "nothing sent"


def test_watch_list_cuts_an_unarmable_captures_format_as_its_refusal_does_and_the_store_keeps_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A format past the bound lists cut by `watches.shown_fmt`; the store keeps it whole."""
    ses = _capturing(monkeypatch, tmp_path)
    wide = _struct(watches.capture_block_chars_max() + 1)
    assert len(wide) > 60, "the case is built: a format longer than the cut"
    assert arming.store() is not None
    arming.store().add(dec.Declaration("watch", "address", "0x2031fc", width=32, fmt=wide,
                                       watch_mode="capture", trigger="0x2031fe",
                                       fingerprint="fp-test", cpu=":maincpu"))
    rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    (row,) = [r for r in watches.list_watches(ses)["watches"]  # type: ignore[arg-type]
              if r["ref"] == "0x2031fc"]
    assert row["state"] == "not_installed", row
    assert row["fmt"] == wide[:60] + "...", row
    (held,) = [d for d in arming.store().declarations() if d.ref == "0x2031fc"]
    assert held.fmt == wide, "the store keeps the format whole"
    assert watches.shown_fmt("i8") == "i8", "a short format is shown as it is"
    (surveyed,) = [r for r in watches.evaluate_watches(ses)  # type: ignore[arg-type]
                   if r["ref"] == "0x2031fc"]
    assert surveyed["fmt"] == wide[:60] + "...", "the stop survey lists it the same way"
    refusal = refused("widest row", s.watch_add(ref="0x2031fc", mode="capture", length=32,
                                                fmt=wide, trigger="0x2031fe"))
    assert f"fmt={wide[:60] + '...'!r}" in refusal["message"], refusal


def test_a_long_format_inside_the_bound_and_a_long_one_on_a_count_row_are_listed_whole(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The cut is for a capture past the bound alone."""
    ses = _capturing(monkeypatch, tmp_path)
    long_fits = "{" + ",".join(f"field{i:02d}:u8" for i in range(8)) + "}"
    assert len(long_fits) > 60 and watches.capture_chars_past_bound(8, long_fits) is None
    assert arming.store() is not None
    arming.store().add(dec.Declaration("watch", "address", "0x2031fc", width=8, fmt=long_fits,
                                       watch_mode="capture", trigger="0x2031fe",
                                       fingerprint="fp-test", cpu=":maincpu"))
    arming.store().add(dec.Declaration("watch", "address", "0x203200", width=8, fmt=long_fits,
                                       watch_mode="show", fingerprint="fp-test", cpu=":maincpu"))
    rows = {r["ref"]: r for r in watches.list_watches(ses)["watches"]}  # type: ignore[arg-type]
    assert rows["0x2031fc"]["fmt"] == long_fits and rows["0x203200"]["fmt"] == long_fits, rows


def test_a_capture_read_from_its_own_space_names_the_address() -> None:
    """A block in no share or region is read at its own address: the source says `addr`, not an
    offset."""
    assert capture.TapSource("space", "", 0x2031FC).fields() == {"kind": "space",
                                                                 "addr": "0x002031fc"}
    assert capture.TapSource("share", ":blitram", 0x10).fields() == {
        "kind": "share", "tag": ":blitram", "offset": "0x00000010"}
