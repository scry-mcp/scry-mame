"""A capture's rows through the manifest's draw command: the boxes a frame's blits drew
(`gfx_blits`) and the rectangle one blit reads (`gfx_blit_source`).

THE m68k-dual CASE IS CAPTURED, on its own build through this server: a capture watch on
the blitter block (`watch_add(ref="0x700000", mode="capture", length=32, trigger="0x70001e")`)
declared at the stop at frame 900 and read at the stop at frame 903. `m68k-dual-blit-rows-rows.gz`
is the rows file the periodic hook wrote, in rows of six fields with no line and no time, which the
cases read completed by `with_stamps`, since no reader here takes either. `m68k-dual-screen-bin.gz`
is that stop's screen as the index capture writes it, rebuilt from the indexed PNG `screen_view`
wrote at the same stop (each PNG index is the pen, its PLTE the pens), and `screen-m68k-dual.txt`
the capture line that stop answered. The header is the one the survey of that stop reported (352
rows, none over the cap, a 16-bit big-endian bus). The known answer is the screen itself: at that
stop every FG blit of frame 902 into the low half, decoded from the ROM files, agreed with the
index screen pixel for pixel (the live matrix repeats it), so their boxes are where the screen
shows them.

The source cases run on a small AUTHORED block, because ROM bytes are not committed: a 16x16
8-bit tile sheet whose pixel at (x, y) of tile t is `t * 64 + y * 4 + x % 4` in a pattern that
tells every neighbour apart.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast

import png_read  # noqa: E402
import pytest
from lua_support import _channel, _ChannelSession  # noqa: E402
from scry_core import png as mpng  # noqa: E402
from scry_core.file_names import written_as  # noqa: E402
from session_doubles import add_symbol, refused, with_stamps  # noqa: E402
from test_gfx import _mark, _png  # noqa: E402

from scry_mame import blits as mblits  # noqa: E402
from scry_mame import (
    capture,  # noqa: E402
    inputs,  # noqa: E402
)
from scry_mame import layout as ml  # noqa: E402
from scry_mame import manifest as mm  # noqa: E402
from scry_mame import read as mame_read  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "gfx"
MANIFEST = FIX / "manifest-blitter.yaml"
OWNER = ("0x700000", ":maincpu")
HEADER = ("MCP_CAPTURE 700000_32_t70001e seq=3 frame=903 total=352 rows=352 overflow_rows=0 "
          "data_width=16 endianness=big cpu=:maincpu\nend\n")


def _m68k_dual_rows(salt: int = 0) -> str:
    """The captured rows, completed with a line and a time (`with_stamps`)."""
    return with_stamps(gzip.decompress((FIX / "m68k-dual-blit-rows-rows.gz").read_bytes()).decode(),
                       salt)


def _declared(ses: _ChannelSession, rows: str, header: str = HEADER) -> dict[str, Any]:
    """The record `watch_add` leaves for the blitter's capture once its install answered, and the
    header and rows the periodic hook wrote where that record says."""
    cid = capture.id_for(":maincpu", 0x700000, 32, 0x70001E)
    head, rows_path = capture.paths(ses.scratch, cid)
    head.write_text(header)
    rows_path.write_text(rows)
    rec = {"tally_id": cid, "installed": True, "lost": False, "cpu": ":maincpu", "resent": 0,
           "path": head, "rows_path": rows_path, "addr": 0x700000, "width": 32,
           "trigger": 0x70001E, "source": capture.TapSource("share", ":blitram", 0),
           "last_total": 0, "last_seq": 0}
    mstate.STATE.tallies[OWNER] = rec
    return rec


def _m68k_dual(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _ChannelSession:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    _declared(ses, _m68k_dual_rows())
    return ses


def _screen(ses: _ChannelSession) -> None:
    """The stop's screen as the colour-only capture writes it: the same console line with no
    palette, and the first of the capture's parts, its colours, which that chunk writes first."""
    seq = mstate.STATE.lua_seq + 1
    ses.answers[seq] = (b"MAME_MCP_SCREEN tag=:screen w=336 h=252 frame=903 palette=- entries=0\n"
                        + ses.sentinel(seq))
    raw = gzip.decompress((FIX / "m68k-dual-screen-bin.gz").read_bytes())
    (ses.scratch / f"screen-{seq}.bin").write_bytes(raw[:336 * 252 * 4])


def _by_n(blits: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {b["n"]: b for b in blits}


def _pages(ses: _ChannelSession, **kwargs: Any) -> list[dict[str, Any]]:
    """Every page `detail=True` lists, each call served the same screen, followed by
    `next_first` until the list says it is whole."""
    out, first = [], 0
    while True:
        _screen(ses)
        page = s.gfx_blits(draw_command="blit", detail=True, first=first, scale=1, **kwargs)
        assert page["status"] == "ok", page
        out.append(page)
        if "next_first" not in page:
            return out
        first = page["next_first"]


# ------------------------------------------------------------------ gfx_blits, m68k-dual

def test_the_blits_do_not_move_with_the_line_and_time_a_row_carries(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The boxes are read from a row's frame, writer, data and block: the same rows under two
    other lines and times answer the same blits."""
    ses = _m68k_dual(monkeypatch, tmp_path)
    first = [b for page in _pages(ses) for b in page["blits"]]
    _declared(ses, _m68k_dual_rows(salt=7).replace(" -1 ", " 3 "))
    again = [b for page in _pages(ses) for b in page["blits"]]
    assert first and again == first


def test_the_boxes_of_a_frame_sit_where_the_screen_shows_them(monkeypatch: pytest.MonkeyPatch,
                                                              tmp_path: Path) -> None:
    ses = _m68k_dual(monkeypatch, tmp_path)
    pages = _pages(ses)
    out = pages[0]
    assert (out["frame_blit"], out["frame_complete"], out["frame_screen"]) == (902, True, 903)
    assert out["blits_in_frame"] == 88 and out["frames_with_blits"] == {
        "first": 901, "last": 903, "count": 3}
    assert out["session"]["altered"] is False
    every = [b for page in pages for b in page["blits"]]
    assert [b["index"] for b in every] == list(range(88)), "the pages list every blit once"
    blits = _by_n(every)
    first = blits[112]
    assert first["index"] == 0 and first["pc"] == "0x00001fd2" and first["plane"] == "fg"
    assert first["box"] == {"x": 53, "y": 46, "width": 48, "height": 32, "dir_x": 1, "dir_y": 1}
    assert first["page"] == 1 and first["screen"] == [[53, 46, 48, 32]]
    assert first["on_screen"] is True and first["clipped"] is False
    assert first["fields"]["source_tile"] == 9 and first["flags"]["writes_index_0"] == 0
    # the high half (drawing_low_half 0) lands on the same screen rows through its origin
    high = blits[184]
    assert high["page"] == 0 and high["box"]["y"] == 265 and high["screen"][0][1] == 9
    # the page-wide blit of the high half runs past the screen and says so
    wide = blits[180]
    assert wide["box"]["width"] == 340 and wide["clipped"] is True
    assert wide["screen"] == [[0, 0, 336, 252]]
    assert out["note"].startswith("a plane drawn in pages: `by_plane` and each listed")
    assert "dest_x" not in out["not_proved"] and "pc_before" in out
    assert (out["rows_kept"], out["overflow_rows"]) == (352, 0)
    assert out["cause"] == f"gfx_blits: {out['evaluated_by']}"
    assert out["rows_path"].endswith(".rows") and "None" not in out["rows_path"]
    assert Path(out["image"]["path"]).name.startswith("blits-")
    assert [e["blits"] for e in out["legend"]] == [
        sum(1 for b in every if b["pc"] == e["pc"]) for e in out["legend"]]
    assert "dest_y" in out["not_proved"] and "planes.fg" in out["not_proved"]
    assert {e["pc"] for e in out["legend"]} == {"0x00001fd2", "0x000021ac"}
    pic = _png(out)
    assert not pic.indexed and (pic.width, pic.height) == (336, 252)
    colour = tuple(int(out["legend"][0]["color"][i:i + 2], 16) for i in (1, 3, 5))
    assert pic.at(53, 46) == colour and pic.at(100, 77) == colour, "the outline, at its corners"
    assert out["summary"].startswith("gfx_blits blit frame 902: 88 blits by 2 writers, "
                                     "listed 0..23; ")


def test_the_default_reply_is_a_summary_and_fits_the_clients_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The frame the owner read: 88 blits, every one with every field, crossed the client's cap
    and arrived cut. By default the reply is the count, the legend by writer, the count by plane
    and page, and the picture; the detail is a page. The control is the old reply, the whole list
    in the text the client is handed, which crosses the budget."""
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", scale=1)
    assert out["status"] == "ok", out
    assert "blits" not in out and "listed" not in out and out["blits_in_frame"] == 88
    assert sum(e["blits"] for e in out["legend"]) == 88
    every = [b for page in _pages(ses) for b in page["blits"]]
    planes: dict[tuple[str, int | None], list[int]] = {}
    for b in every:
        seen = planes.setdefault((b["plane"], b.get("page")), [0, 0])
        seen[0] += 1
        seen[1] += bool(b["on_screen"])
    assert out["by_plane"] == [{"plane": plane, "page": page, "blits": n, "on_screen": on}
                               for (plane, page), (n, on) in sorted(
                                   planes.items(), key=lambda kv: (kv[0][0], -1 if kv[0][1] is None
                                                                   else kv[0][1]))]
    assert out["summary"].startswith("gfx_blits blit frame 902: 88 blits by 2 writers; ")
    text = len(json.dumps(out, indent=2))
    assert text < mstate.REPLY_BUDGET_CHARS, text
    whole = len(json.dumps({**out, "blits": every}, indent=2))
    assert whole > mstate.REPLY_BUDGET_CHARS, f"the control: the whole list is {whole}"
    for page in _pages(ses):
        assert len(json.dumps(page, indent=2)) < mstate.REPLY_BUDGET_CHARS


def test_the_detail_is_paged_and_a_page_past_the_list_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", frame=902, detail=True)
    assert out["listed"] == {"first": 0, "count": mstate.ROWS_SHOWN, "of": 88}
    assert out["next_first"] == mstate.ROWS_SHOWN
    _screen(ses)
    last = s.gfx_blits(draw_command="blit", frame=902, detail=True, first=72)
    assert last["listed"] == {"first": 72, "count": 16, "of": 88} and "next_first" not in last
    assert [b["index"] for b in last["blits"]] == list(range(72, 88))
    _screen(ses)
    out = refused("first=88 is past the 88 blit", s.gfx_blits(draw_command="blit", detail=True,
                                                              first=88))
    assert out["listed_of"] == 88 and "evaluated_by" in out
    refused("`first` pages a listing", s.gfx_blits(draw_command="blit", first=24))


def test_an_area_nothing_covers_lists_nothing_and_no_page_past_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """One small blit in a corner (m68k-dual's frame covers its whole screen with page-wide
    blits): an area away from it lists nothing, so any page past the first is past the list."""
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    _declared(ses, _row(1, 902, 0x1000, _words(0, 0, 1, 1)))
    _screen(ses)
    empty = s.gfx_blits(draw_command="blit", area=[300, 200, 1, 1])
    assert empty["listed"] == {"first": 0, "count": 0, "of": 0}, empty.get("listed")
    assert empty["blits"] == [] and empty["topmost"]["available"] is False
    _screen(ses)
    refused("first=1 is past the 0 blit", s.gfx_blits(draw_command="blit", area=[300, 200, 1, 1],
                                                      first=1))


def test_topmost_is_judged_over_every_covering_blit_not_the_page(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The whole screen as the area: more blits cover it than a page lists, and `topmost` is the
    last of the highest plane among ALL of them, which the first page does not hold."""
    ses = _m68k_dual(monkeypatch, tmp_path)
    pages = _pages(ses, area=[0, 0, 336, 252])
    every = [b for page in pages for b in page["blits"]]
    assert len(pages) > 1 and pages[0]["listed"]["of"] == len(every)
    order = {"bg": 0, "fg": 1}
    best = max(every, key=lambda b: (order[b["plane"]], b["index"]))
    assert all(page["topmost"]["index"] == best["index"] for page in pages)
    assert best["index"] not in [b["index"] for b in pages[0]["blits"]], (
        "the known answer sits past the first page, or this case proves nothing")


def test_an_area_lists_the_blits_covering_it_in_the_order_drawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A point inside blit 112's box: it and the high half's page-wide blit cover it. The topmost
    is the later one, of the page the screen is NOT showing, which is exactly why covering is
    said not to be painting and why each names its page."""
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", area=[60, 50, 1, 1], scale=1)
    assert out["status"] == "ok", out
    assert out["listed"] == {"first": 0, "count": 2, "of": 2}, "an area lists what covers it"
    covering = [(b["n"], b["page"]) for b in out["blits"]]
    assert (112, 1) in covering and (180, 0) in covering and out["covering"] == len(covering)
    assert 114 not in [n for n, _ in covering], "blit 114's box (x 133..148) does not cover x 60"
    assert out["covering"] < out["blits_in_frame"]
    assert [b["n"] for b in out["blits"]] == [112, 180], "exactly these two, in the order drawn"
    assert out["topmost"]["n"] == covering[-1][0] and mblits.COVERING_NOTE in out["note"]
    assert out["area"] == [60, 50, 1, 1]
    assert _png(out).at(60, 50) == mblits.AREA_COLOUR
    assert re.match(r"gfx_blits blit frame 902: \d+ of 88 blits cover \[60, 50, 1, 1\], "
                    r"topmost #\d+ pc 0x", out["summary"])


def test_the_stops_own_frame_is_marked_incomplete(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", frame=903, scale=1)
    assert out["frame_blit"] == 903 and out["frame_complete"] is False and out["blits_in_frame"] > 0


def test_a_frame_with_no_blit_names_the_frames_that_have_some(monkeypatch: pytest.MonkeyPatch,
                                                               tmp_path: Path) -> None:
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    out = refused(r"no blit of 'blit' was fired in frame 800",
                  s.gfx_blits(draw_command="blit", frame=800))
    assert out["frames_with_blits"] == {"first": 901, "last": 903, "count": 3}
    assert out["rows_path"].endswith(".rows") and "None" not in out["rows_path"]
    _screen(ses)
    refused(r"^no blit of 'blit' was fired in frame 904", s.gfx_blits(draw_command="blit",
                                                                      frame=904))


def test_a_capture_whose_tap_raised_carries_its_errors_on_the_blits_and_their_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A capture short of the rows it was fired: the blits it kept, and a frame where it kept
    none, both carry the count that says there may have been more."""
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    raised = HEADER.replace("cpu=:maincpu\n", "cpu=:maincpu errors=9\ne mcp:44: planted fault\n")
    assert raised != HEADER
    _declared(ses, _m68k_dual_rows(),
              raised)
    errors = {"count": 9, "first": "mcp:44: planted fault"}
    clause = "the capture's callbacks raised 9 times (the first: mcp:44: planted fault)"
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", scale=1)
    assert out["status"] == "ok" and out["callback_errors"] == errors, out
    assert out["summary"].endswith("; its callbacks raised 9 times (the first: mcp:44: planted "
                                   "fault)"), out["summary"]
    _screen(ses)
    none = refused(r"no blit of 'blit' was fired in frame 800",
                   s.gfx_blits(draw_command="blit", frame=800))
    assert none["callback_errors"] == errors
    assert none["message"].endswith(f"; {clause}, so rows may be missing"), none["message"]
    # A HEADER THAT CARRIES NO COUNT says nothing either way: no key, no clause
    _declared(ses, _m68k_dual_rows())
    _screen(ses)
    plain = refused(r"no blit of 'blit' was fired in frame 800$",
                    s.gfx_blits(draw_command="blit", frame=800))
    assert "callback_errors" not in plain


def test_a_frame_past_the_rows_kept_is_said_to_be_past_them(monkeypatch: pytest.MonkeyPatch,
                                                            tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    rows = _m68k_dual_rows()
    kept = "".join(rows.splitlines(keepends=True)[:100])
    _declared(ses, kept, HEADER.replace("rows=352 overflow_rows=0", "rows=100 overflow_rows=252"))
    _screen(ses)
    refused(r"frame 903 is past the rows the capture kept: it counted 252 rows past its cap",
            s.gfx_blits(draw_command="blit", frame=903))


def test_no_capture_is_refused_with_the_call_that_declares_one(monkeypatch: pytest.MonkeyPatch,
                                                               tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    _screen(ses)
    out = refused(r"no capture of command 'blit'", s.gfx_blits(draw_command="blit"))
    assert out["declare"] == ('watch_add(ref="0x700000", mode="capture", length=32, '
                              'trigger="0x70001e")')


def test_a_capture_with_no_rows_yet_is_refused(monkeypatch: pytest.MonkeyPatch,
                                               tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    rec = _declared(ses, "")
    Path(rec["path"]).unlink()
    _screen(ses)
    out = refused(r"has written no rows yet", s.gfx_blits(draw_command="blit"))
    assert out["tally_id"] == rec["tally_id"]


def test_an_area_off_the_screen_is_refused_with_its_size(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    out = refused(r"area \[330, 0\] \+ 10x10 leaves the 336x252 screen",
                  s.gfx_blits(draw_command="blit", area=[330, 0, 10, 10]))
    assert (out["width"], out["height"]) == (336, 252)


@pytest.mark.parametrize("kwargs, said", [
    ({"draw_command": ""}, r"the name of a draw command"),
    ({"draw_command": "blit", "frame": -1}, r"frame=-1 is a frame of the counter"),
    ({"draw_command": "blit", "area": [0, 0, 0, 4]}, r"area=\[0, 0, 0, 4\] is \[x, y, width"),
    ({"draw_command": "blit", "scale": 9}, r"scale=9"),
    ({"draw_command": "blit", "detail": 1}, r"detail is true or false; got 1"),
    ({"draw_command": "blit", "detail": True, "first": -1}, r"first=-1 is a blit's place"),
    ({"draw_command": "blit", "detail": True, "first": True}, r"first=True is a blit's place"),
    ({"draw_command": "blit", "first": 3}, r"`first` pages a listing"),
])
def test_gfx_blits_arguments_are_judged_before_the_machine(kwargs: dict[str, Any],
                                                           said: str) -> None:
    refused(said, s.gfx_blits(**kwargs))


def test_a_command_the_manifest_lacks_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    _channel(monkeypatch, tmp_path)
    assert refused(r"no manifest is loaded",
                   s.gfx_blits(draw_command="blit"))["code"] == "needs_call"
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    refused(r"draw command 'sprite' is not in", s.gfx_blits(draw_command="sprite"))


# ------------------------------------------------------------------ the geometry

def _cmd() -> mm.Command:
    return mm.read(str(MANIFEST)).commands["blit"]


def _blit(cmd: mm.Command, words: list[int]) -> mblits.Blit:
    b = mblits.Blit(0, 1, 10, 0x1234, words)
    b.values = {n: f.value(words) for n, f in {**cmd.fields, **cmd.flags}.items()}
    return b


def _words(x0: int, y0: int, x1: int, y1: int, w7: int = 0x03, w8: int = 0xC020,
           w10: int = 0, w11: int = 0) -> list[int]:
    """A blitter block: endpoints with their bit 8s placed where the manifest says."""
    w = [0] * 16
    w[0], w[1], w[2], w[3] = x0 & 0xFF, x1 & 0xFF, y0 & 0xFF, y1 & 0xFF
    w[7] = w7 | (0x40 if x0 & 0x100 else 0) | (0x80 if y0 & 0x100 else 0)
    w[9] = (0x4 if x1 & 0x100 else 0) | (0x8 if y1 & 0x100 else 0)
    w[8], w[10], w[11] = w8, w10, w11
    return w


def test_a_walk_across_the_planes_edge_wraps_into_two_rectangles() -> None:
    cmd = _cmd()
    geo = mblits.geometry(cmd, _blit(cmd, _words(500, 10, 20, 12)), 336, 252)
    assert geo["box"]["width"] == 33
    assert geo["screen"] == [[0, 10, 21, 3]], geo
    assert geo["clipped"] is True, "the part past x 336 of the plane is not on the screen"


def test_a_walk_downwards_covers_from_its_end() -> None:
    cmd = _cmd()
    geo = mblits.geometry(cmd, _blit(cmd, _words(40, 30, 31, 25, w7=0x00)), 336, 252)
    assert geo["box"] == {"x": 40, "y": 30, "width": 10, "height": 6, "dir_x": -1, "dir_y": -1}
    assert geo["screen"] == [[31, 25, 10, 6]] and geo["clipped"] is False


def test_the_bg_plane_is_moved_by_its_scroll_and_wraps_onto_the_screen() -> None:
    cmd = _cmd()
    geo = mblits.geometry(cmd, _blit(cmd, _words(0, 0, 9, 9, w7=0x13, w10=500 & 0xFF,
                                                w11=0, w8=0xC020 | 0x40)), 336, 252)
    assert geo["plane"] == "bg" and "page" not in geo
    assert geo["screen"] == [[12, 0, 10, 10]], "x 0 of the plane is x 12 with a scroll of 500"


def test_a_walk_entirely_off_the_screen_is_not_on_it() -> None:
    cmd = _cmd()
    geo = mblits.geometry(cmd, _blit(cmd, _words(400, 10, 420, 20)), 336, 252)
    assert geo["screen"] == [] and geo["on_screen"] is False and geo["clipped"] is False


def test_a_plane_value_no_plane_declares_is_said(tmp_path: Path) -> None:
    """A `plane` role of two bits picks among four values and the manifest declares planes for
    two: a blit on a third is placed nowhere, and says why."""
    text = MANIFEST.read_text()
    edited, n = re.subn(r"plane: \{parts: \[\{word: 7, mask: 0x0010\}\]",
                        "plane: {parts: [{word: 7, mask: 0x0030}]", text, count=1)
    assert n == 1
    path = tmp_path / "gfx.yaml"
    path.write_text(edited)
    cmd = mm.read(str(path)).commands["blit"]
    geo = mblits.geometry(cmd, _blit(cmd, _words(0, 0, 3, 3, w7=0x23)), 336, 252)
    assert geo["on_screen"] is False and geo["why"] == "no plane is declared for plane value 2"
    assert geo["screen"] == [] and geo["clipped"] is False


def test_the_fire_word_is_read_from_its_lane_of_a_wider_bus() -> None:
    cmd = _cmd()
    assert mblits._lane(0x1234FFFF, 0x0000FFFF, 32, "big", cmd) == 0xFFFF
    assert mblits._lane(0xFFFF1234, 0xFFFF0000, 32, "little", cmd) == 0xFFFF
    assert mblits._lane(0x0000FFFF, 0x000000FF, 32, "big", cmd) is None, "half the word written"
    assert mblits._lane(0xFFFF, 0xFFFF, 16, "big", cmd) == 0xFFFF


def test_a_fire_word_across_the_bus_word_is_refused_by_name(monkeypatch: pytest.MonkeyPatch,
                                                           tmp_path: Path) -> None:
    """A fire word at an odd address of a 16-bit bus is carried by no single write: said so,
    on either byte order, never a raw error nor a capture that silently holds no blit."""
    ses = _m68k_dual(monkeypatch, tmp_path)
    text, n = re.subn(r"block: \{address: 0x700000,", "block: {address: 0x700001,",
                      MANIFEST.read_text(), count=1)
    assert n == 1
    path = tmp_path / "gfx.yaml"
    path.write_text(text)
    assert s.gfx_load(path=str(path))["status"] == "ok"
    mstate.STATE.tallies[OWNER].update(addr=0x700001, trigger=0x70001F)
    for order in ("big", "little"):
        head = Path(mstate.STATE.tallies[OWNER]["path"])
        head.write_text(HEADER.replace("endianness=big", f"endianness={order}"))
        with pytest.raises(mstate.Invalid, match="crosses the bus word") as err:
            mblits.read_rows(ses.scratch, mm.command("blit"), None, 903)
        assert err.value.fields["tally_id"] == mstate.STATE.tallies[OWNER]["tally_id"]


# ------------------------------------------------------------------ gfx_blit_source

TILE = 16
SHEET = bytes(((t * 64 + y * 4 + x % 4) & 0xFF) for t in range(4) for y in range(TILE)
              for x in range(TILE))


def _sheet_manifest(tmp_path: Path, wrap: bool = True) -> str:
    """The blitter manifest with its asset read as the 16x16 8-bit sheet."""
    text = MANIFEST.read_text()
    for old, new in (("      width: 512\n      height: 512\n      planes: 8",
                      "      width: 16\n      height: 16\n      planes: 8"),
                     ("xoffset: '{ STEP512(0,8) }'", "xoffset: '{ STEP16(0,8) }'"),
                     ("yoffset: '{ STEP512(0,4096) }'", "yoffset: '{ STEP16(0,128) }'"),
                     ("charincrement: 512*512*8", "charincrement: 16*16*8"),
                     ("    wrap: true\n", f"    wrap: {'true' if wrap else 'false'}\n")):
        text, n = re.subn(re.escape(old), new.replace("\\", "\\\\"), text, count=1)
        assert n == 1, old
    path = tmp_path / f"sheet-{wrap}.yaml"
    path.write_text(text)
    return str(path)


def _row(n: int, frame: int, pc: int, words: list[int]) -> str:
    return (f"r {n} {frame} 0 {frame}.{n:018d} {pc:x} ffff ffff "
            f"{''.join(f'{w:04x}' for w in words)}\n")


def _source_words(sx: int, sy: int, tile: int, x0: int, y0: int, x1: int, y1: int,
                  w8: int = 0xC020, w7: int = 0x07) -> list[int]:
    w = _words(x0, y0, x1, y1, w7=w7, w8=w8)
    w[0] |= (sx & 0xFF) << 8
    w[2] |= (sy & 0xFF) << 8
    w[6] = (tile << 10) | (0x100 if sx & 0x100 else 0) | (0x200 if sy & 0x100 else 0)
    return w


def _serve_pens(ses: _ChannelSession, pens_line: str) -> None:
    """The next call's block, the whole sheet, and `pens_line` where the pens would be."""
    seq = mstate.STATE.lua_seq + 1
    ses.answers[seq] = (f"MAME_MCP_GFX_BLOCK kind=region tag=:gfx1 size={len(SHEET)} bytewidth=1 "
                        f"endian=little\n{pens_line}\nMAME_MCP_LUA_END#{seq}\ttrue\tnil\n").encode()
    (ses.scratch / f"block-{seq}.bin").write_bytes(SHEET)


def _serve_sheet(ses: _ChannelSession) -> None:
    """The next call's block and pens: the whole sheet, each pen its own grey."""
    _serve_pens(ses, "MAME_MCP_GFX_PENS tag=:palette entries=256 pens="
                + ",".join(f"ff{i:02x}{i:02x}{i:02x}" for i in range(256)))


def _sourcing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rows: str,
              wrap: bool = True) -> _ChannelSession:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=_sheet_manifest(tmp_path, wrap))["status"] == "ok"
    _declared(ses, rows, HEADER.replace("frame=903", "frame=11"))
    mstate.STATE.last_stop = {**mstate.STATE.last_stop, "frame": 11}
    return ses


def _expected(tile: int, x0: int, y0: int, w: int, h: int) -> list[int]:
    return [SHEET[tile * 256 + ((y0 + j) % TILE) * TILE + (x0 + i) % TILE]
            for j in range(h) for i in range(w)]


def test_the_source_is_the_rectangle_the_blit_reads(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    """Source (2, 3) of tile 1, a 4x5 walk; `source_y`'s declared `add` of 1 is applied."""
    rows = _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_sheet(ses)
    out = s.gfx_blit_source(draw_command="blit", index=0, scale=1)
    assert out["status"] == "ok", out
    assert out["rect"] == {"tile": 1, "x": 2, "y": 4, "width": 4, "height": 5, "dir_x": 1,
                           "dir_y": 1}
    assert out["frame_blit"] == 10 and out["box"] == [0, 0, 4, 5] and out["margin"] == 0
    assert out["note"] == mblits.UNSCALED_NOTE and out["reads_source"] is True
    assert "source_y" in out["not_proved"] and "dest_x" not in out["not_proved"]
    assert out["not_proved"] == ["dest_dir_x", "dest_dir_y", "dest_x_end", "dest_y", "dest_y_end",
                                 "reads_source", "source_dir_x", "source_dir_y", "source_tile",
                                 "source_x", "source_y", "planes.fg", "planes.bg"], out
    assert "pc_before" in out and Path(out["image"]["path"]).name.startswith("source-")
    pic = _png(out)
    assert pic.indexed and list(pic.pixels) == _expected(1, 2, 4, 4, 5)
    assert pic.palette[7] == (7, 7, 7), "the pens read in the same chunk"
    assert out["summary"].startswith("gfx_blit_source blit frame 10 #0 pc 0x00001fd2: pages "
                                     "tile 1 (2, 4) 4x5")
    assert out["cause"] == f"gfx_blit_source: {out['evaluated_by']}"


def test_a_margin_shows_the_pixels_round_the_rectangle(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    rows = _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_sheet(ses)
    out = s.gfx_blit_source(draw_command="blit", index=0, margin=2, scale=2)
    assert out["status"] == "ok", out
    assert out["box"] == [2, 2, 4, 5] and mblits.MARGIN_NOTE in out["note"]
    assert Path(out["data"]["path"]).name.startswith("source-data")
    assert Path(out["image"]["path"]).name.startswith("source-")
    data = Path(out["data"]["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == out["data"]["sha256"]
    exact = png_read.read(data)
    assert exact.indexed and (exact.width, exact.height) == (8, 9), "the data is unscaled"
    assert list(exact.pixels) == _expected(1, 0, 2, 8, 9), "the data keeps every pixel's value"
    # THE VIEW keeps the margin apart: dimmed, the rectangle ringed just outside itself
    view = _png(out)
    assert not view.indexed and not out["image"]["indexed"] and (view.width, view.height) == (
        16, 18)
    pen = _expected(1, 0, 2, 8, 9)
    assert view.at(4, 4) == (pen[2 * 8 + 2],) * 3, "the rectangle in its own colour"
    assert view.at(0, 0) == (pen[0] >> mblits.MARGIN_DIM_SHIFT,) * 3, "the margin dimmed"
    assert view.at(3, 4) == view.at(12, 4) == view.at(4, 3) == view.at(4, 14) == (255, 255, 255)


def test_with_no_margin_the_picture_is_the_data(monkeypatch: pytest.MonkeyPatch,
                                                tmp_path: Path) -> None:
    rows = _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_sheet(ses)
    out = s.gfx_blit_source(draw_command="blit", index=0, scale=1)
    assert "data" not in out and out["image"]["indexed"] is True
    _serve_sheet(ses)
    dest = tmp_path / "chosen.png"
    chosen = s.gfx_blit_source(draw_command="blit", index=0, scale=1, dest=str(dest))
    assert chosen["image"]["path"] == str(dest), chosen
    assert "written as" not in chosen.get("note", ""), chosen
    _serve_sheet(ses)
    renamed = s.gfx_blit_source(draw_command="blit", index=0, scale=1,
                                dest=str(tmp_path / "Chosen_2.PNG"))
    assert renamed["image"]["path"] == str(tmp_path / "chosen-2.png"), renamed
    assert renamed["note"].endswith(str(written_as("dest", str(tmp_path / "Chosen_2.PNG"))))
    _serve_sheet(ses)
    dest = tmp_path / "chosen-margin.png"
    assert s.gfx_blit_source(draw_command="blit", index=0, margin=1, scale=1, dest=str(dest))[
        "image"]["path"] == str(dest)


def test_a_rectangle_past_the_tile_wraps_inside_it_when_the_asset_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rows = _row(1, 10, 0x1FD2, _source_words(14, 13, 0, 0, 0, 3, 5))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_sheet(ses)
    out = s.gfx_blit_source(draw_command="blit", index=0, scale=1)
    assert list(_png(out).pixels) == _expected(0, 14, 14, 4, 6)


def test_a_rectangle_past_the_tile_is_refused_when_the_asset_does_not_wrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rows = _row(1, 10, 0x1FD2, _source_words(14, 13, 0, 0, 0, 3, 5))
    ses = _sourcing(monkeypatch, tmp_path, rows, wrap=False)
    _serve_sheet(ses)
    out = refused(r"the rectangle 4x6 at \(14, 14\) leaves the 16x16 tile, and the asset does "
                  r"not wrap", s.gfx_blit_source(draw_command="blit", index=0))
    assert (out["tile_width"], out["tile_height"]) == (16, 16) and "evaluated_by" in out


def test_a_source_walking_backwards_is_shown_from_its_lowest_coordinate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rows = _row(1, 10, 0x1FD2, _source_words(9, 3, 2, 100, 50, 103, 51, w8=0x0020))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_sheet(ses)
    out = s.gfx_blit_source(draw_command="blit", index=0, scale=1)
    assert out["rect"] == {"tile": 2, "x": 6, "y": 3, "width": 4, "height": 2, "dir_x": -1,
                           "dir_y": -1}
    assert list(_png(out).pixels) == _expected(2, 6, 3, 4, 2)


def test_a_blit_that_reads_no_source_says_so(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    rows = _row(1, 10, 0x21AC, _source_words(0, 0, 0, 0, 0, 1, 1, w7=0x0B))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_sheet(ses)
    out = s.gfx_blit_source(draw_command="blit", pc="0x21ac", scale=1)
    assert out["reads_source"] is False
    assert "the manifest's `reads_source` says this blit reads no" in out["note"]
    assert "reads_source" in out["not_proved"], "the reply leans on the role it reports"


def test_a_pc_that_fired_several_blits_is_refused_with_their_indexes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    words = _source_words(0, 0, 0, 0, 0, 1, 1)
    rows = _row(1, 10, 0x1FD2, words) + _row(3, 10, 0x1FD2, words) + _row(5, 10, 0x21AC, words)
    _sourcing(monkeypatch, tmp_path, rows)
    out = refused(r"pc 0x1fd2 fired 2 blits in frame 10: name one by `index`",
                  s.gfx_blit_source(draw_command="blit", pc="0x1fd2"))
    assert out["indexes"] == [0, 1]
    refused(r"pc 0x9999 fired no blit in frame 10", s.gfx_blit_source(draw_command="blit",
                                                                      pc="0x9999"))
    # THE WRITER BY NAME, as `gfx_film`'s `pc` takes it: resolved on the capture's cpu.
    add_symbol(monkeypatch, "DRAWLEVEL", 0x1FD2)     # a table keeps its names upper case
    out = refused(r"pc 0x1fd2 fired 2 blits in frame 10",
                  s.gfx_blit_source(draw_command="blit", pc="DrawLevel"))
    assert out["indexes"] == [0, 1], "the name was resolved to the writer it names"
    # ON THE CAPTURE'S CPU: a name the first cpu's table holds elsewhere is not the writer.
    add_symbol(monkeypatch, "SUBWRITER", 0x9999, cpu=":subcpu")
    monkeypatch.setitem(mstate.STATE.tables, ":maincpu",
                        dataclasses.replace(mstate.NO_TABLE, table={"SUBWRITER": 0x1FD2}))
    monkeypatch.delitem(mstate.STATE.tables, None, raising=False)
    rec = mstate.STATE.tallies[OWNER]
    monkeypatch.delitem(mstate.STATE.tallies, OWNER)
    monkeypatch.setitem(mstate.STATE.tallies, (OWNER[0], ":subcpu"), {**rec, "cpu": ":subcpu"})
    refused(r"pc 0x9999 fired no blit", s.gfx_blit_source(draw_command="blit", pc="SUBWRITER"))
    # BARE HEX naming no symbol keeps the address rule's own refusal and its `0x` spelling.
    refused(r"an address is written 0x1fd2", s.gfx_blit_source(draw_command="blit", pc="1fd2"))
    out = refused(re.escape(inputs.not_a_ref("the pc", "NoSuchWriter", ":subcpu")),
                  s.gfx_blit_source(draw_command="blit", pc="NoSuchWriter"))
    assert out["code"] == "unknown_ref", out
    out = refused(r"frame 10 has 3 blits; index 3 is not one",
                  s.gfx_blit_source(draw_command="blit", index=3))
    assert out["blits_in_frame"] == 3


def test_a_tile_past_the_block_is_refused(monkeypatch: pytest.MonkeyPatch,
                                          tmp_path: Path) -> None:
    rows = _row(1, 10, 0x1FD2, _source_words(0, 0, 9, 0, 0, 1, 1))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_sheet(ses)
    out = refused(r"source tile 9 is not inside region :gfx1, which holds 4 whole tile",
                  s.gfx_blit_source(draw_command="blit", index=0))
    assert out["tiles_available"] == 4 and "evaluated_by" in out
    mstate.STATE.tallies.clear()
    _declared(ses, _row(1, 10, 0x1FD2, _source_words(0, 0, 4, 0, 0, 1, 1)),
              HEADER.replace("frame=903", "frame=11"))
    _serve_sheet(ses)
    refused(r"source tile 4 is not inside", s.gfx_blit_source(draw_command="blit", index=0))


def test_a_command_with_no_asset_has_no_source_to_show(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    text, n = re.subn(r"    asset: pages\n", "", MANIFEST.read_text(), count=1)
    assert n == 1
    path = tmp_path / "noasset.yaml"
    path.write_text(text)
    assert s.gfx_load(path=str(path))["status"] == "ok"
    _declared(ses, _row(1, 10, 0x1FD2, _source_words(0, 0, 0, 0, 0, 1, 1)))
    refused(r"names no `asset` to read a source from",
            s.gfx_blit_source(draw_command="blit", index=0, frame=10))


@pytest.mark.parametrize("kwargs, said", [
    ({"draw_command": "blit"}, r"one blit per call: `index`"),
    ({"draw_command": "blit", "index": 0, "pc": "1fd2"}, r"one blit per call"),
    ({"draw_command": "blit", "index": -1}, r"index=-1 is a blit's order"),
    ({"draw_command": "blit", "pc": "0xzz"}, r"pc"),
    ({"draw_command": "blit", "index": 0, "margin": 17}, r"margin=17 is 0\.\.16"),
])
def test_gfx_blit_source_arguments_are_judged_before_the_machine(kwargs: dict[str, Any],
                                                                 said: str) -> None:
    refused(said, s.gfx_blit_source(**kwargs))


def test_a_window_is_the_tiles_own_offsets_at_that_place() -> None:
    cmd_fmt = mm.read(str(MANIFEST)).formats["page_512x512x8"].layout
    res = ml.resolve(cmd_fmt, None)
    win = mblits.window(res, 510, 3, 4, 2, True)
    assert win.xoffset == (510 * 8, 511 * 8, 0, 8) and win.yoffset == (3 * 4096, 4 * 4096)
    assert (win.width, win.height, win.charincrement) == (4, 2, res.charincrement)


# ------------------------------------------------------------------ what the review found

def _variant(tmp_path: Path, *edits: tuple[str, str]) -> mm.Command:
    """The fixture's command with each `(old, new)` applied exactly once."""
    text = MANIFEST.read_text()
    for old, new in edits:
        text, n = re.subn(re.escape(old), new.replace("\\", "\\\\"), text, count=1)
        assert n == 1, old
    path = tmp_path / f"variant-{len(list(tmp_path.iterdir()))}.yaml"
    path.write_text(text)
    return mm.read(str(path)).commands["blit"]


_PLANES = MANIFEST.read_text()[MANIFEST.read_text().index("    planes:\n"):]
_ENDS = ("      dest_x_end:\n        parts:\n          - {word: 1, mask: 0x00ff}\n"
         "          - {word: 9, mask: 0x0004, at: 8}\n", "      width:\n        parts:\n"
         "          - {word: 1, mask: 0x00ff}\n          - {word: 9, mask: 0x0004, at: 8}\n")
_Y_ENDS = ("      dest_y_end:\n", "      height:\n")


def test_a_box_by_width_and_height_covers_that_many_and_at_most_the_plane(
    tmp_path: Path,
) -> None:
    cmd = _variant(tmp_path, _ENDS, _Y_ENDS)
    geo = mblits.geometry(cmd, _blit(cmd, _words(10, 20, 4, 3)), 336, 252)
    assert geo["box"]["width"] == 4 and geo["box"]["height"] == 3
    assert geo["screen"] == [[10, 20, 4, 3]] and geo["clipped"] is False
    wide = mblits.geometry(cmd, _blit(cmd, _words(0, 0, 400, 3)), 336, 252)
    assert wide["box"]["width"] == 400 - 256 + 256, "the field says 400 (0x190 with bit 8)"
    assert mblits._walk(0, None, 700, True, 512) == (0, 512), "a walk holds at most its plane"
    empty = mblits.geometry(cmd, _blit(cmd, _words(10, 20, 0, 3)), 336, 252)
    assert empty["on_screen"] is False and "covers no pixel" in empty["why"]


def test_a_command_with_no_planes_maps_its_walk_to_the_screen_as_it_is(tmp_path: Path) -> None:
    cmd = _variant(tmp_path, (_PLANES, ""),
                   ("      plane: {parts: [{word: 7, mask: 0x0010}], status: declared, source: "
                    "m68k-dual.cpp do_blit}\n", ""))
    assert cmd.planes == ()
    geo = mblits.geometry(cmd, _blit(cmd, _words(330, 250, 339, 251)), 336, 252)
    assert geo["plane"] is None and geo["screen"] == [[330, 250, 6, 2]] and geo["clipped"]
    behind = mblits.geometry(cmd, _blit(cmd, _words(20, 20, 10, 30)), 336, 252)
    assert behind["screen"] == [] and "end is behind it" in behind["why"]
    assert behind["on_screen"] is False and behind["clipped"] is False


def test_one_plane_with_no_plane_role_places_every_blit(tmp_path: Path) -> None:
    one = ("    planes:\n      - name: only\n        width: 512\n        height: 512\n"
           "        origin_x: 100\n        status: declared\n        source: a test\n")
    cmd = _variant(tmp_path, (_PLANES, one),
                   ("      plane: {parts: [{word: 7, mask: 0x0010}], status: declared, source: "
                    "m68k-dual.cpp do_blit}\n", ""))
    geo = mblits.geometry(cmd, _blit(cmd, _words(100, 0, 103, 1, w7=0x13)), 336, 252)
    assert geo["plane"] == "only" and geo["screen"] == [[0, 0, 4, 2]]


def test_several_planes_need_the_plane_role(tmp_path: Path) -> None:
    with pytest.raises(mstate.Invalid, match=r"several planes need the `plane` role"):
        _variant(tmp_path, ("      plane: {parts: [{word: 7, mask: 0x0010}], status: declared, "
                            "source: m68k-dual.cpp do_blit}\n", ""),
                 ("        when: 0\n", ""), ("        when: 1\n", ""))


def test_topmost_is_the_highest_plane_before_the_latest_blit() -> None:
    cmd = _cmd()
    shown = [{"index": 0, "n": 1, "pc": "0x1", "plane": "fg"},
             {"index": 1, "n": 3, "pc": "0x2", "plane": "bg"}]
    top = mblits._topmost(cmd, shown)
    assert top is not None and top["index"] == 0, "fg (order 1) over a later bg (order 0)"
    assert mblits._topmost(cmd, []) is None


def test_a_box_covers_what_overlaps_it_and_not_what_only_touches_it() -> None:
    box = [[10, 10, 5, 5]]
    assert mblits._covers(box, [14, 14, 1, 1]) and mblits._covers(box, [10, 10, 1, 1])
    assert not mblits._covers(box, [15, 10, 1, 1]) and not mblits._covers(box, [10, 15, 3, 3])
    assert not mblits._covers(box, [5, 10, 5, 5]), "a rectangle ending where the box starts"
    assert not mblits._covers(box, [10, 5, 5, 5]), "a rectangle ending where the box's top is"


def test_many_writers_and_many_blits_say_their_colours_repeat_and_the_list_is_cut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    words = _words(0, 0, 1, 1)
    rows = "".join(_row(i + 1, 902, 0x1000 + i, words) for i in range(len(mblits.PC_COLOURS) + 1))
    _declared(ses, rows)
    monkeypatch.setattr(mstate, "ROWS_SHOWN", 5)
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", detail=True, scale=1)
    assert out["status"] == "ok", out
    assert out["colors_repeat"] is True and len(out["legend"]) == len(mblits.PC_COLOURS) + 1
    assert all(e["blits"] == 1 for e in out["legend"])
    assert out["next_first"] == 5 and len(out["blits"]) == 5
    assert out["legend"][0]["color"] == out["legend"][-1]["color"], "the cycle comes round"


def test_a_capture_on_another_cpu_is_not_the_commands(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    cmd = _variant(tmp_path, ("{address: 0x700000, words: 16, word_bytes: 2, status",
                              "{address: 0x700000, words: 16, word_bytes: 2, cpu: maincpu, status"))
    assert cmd.cpu == "maincpu"
    _declared(ses, "")
    assert mblits.find_capture(cmd)[0] == OWNER, "maincpu is :maincpu"
    mstate.STATE.tallies[("700000", ":subcpu")] = mstate.STATE.tallies.pop(OWNER)
    with pytest.raises(mstate.Invalid, match=r'cpu="maincpu"'):
        mblits.find_capture(cmd)


def test_a_command_naming_no_cpu_is_refused_when_two_cpus_capture_its_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two captures of one block and trigger, one per cpu, and a command that names no cpu: the
    reply would be whichever was declared first, so it is refused naming both cpus."""
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    cmd = mm.command("blit")
    assert not cmd.cpu
    rec = _declared(ses, "")
    mstate.STATE.tallies[("0x700000", ":subcpu")] = dict(rec, cpu=":subcpu")
    with pytest.raises(mstate.Invalid) as err:
        mblits.find_capture(cmd)
    assert err.value.code == "bad_argument", err.value
    assert err.value.fields["captured_on"] == ["maincpu", "subcpu"], err.value.fields
    said = 'declaration_clear(kind="watch", ref="0x700000", cpu=":subcpu")'
    assert said in str(err.value), str(err.value)
    named = _variant(tmp_path, ("{address: 0x700000, words: 16, word_bytes: 2, status",
                                "{address: 0x700000, words: 16, word_bytes: 2, cpu: maincpu, "
                                "status"))
    assert mblits.find_capture(named)[0] == OWNER, "a command naming its cpu takes that capture"


@pytest.mark.parametrize(("change", "state", "said"), [
    ({"installed": False, "error": "no share named blitram"}, "install_failed",
     "refused it: no share named blitram"),
    ({"installed": None, "lost": True, "resent": 1}, "install_lost", "never evaluated"),
])
def test_a_capture_that_never_installed_says_so_rather_than_no_rows_yet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: dict[str, Any], state: str,
    said: str,
) -> None:
    """A tap the console refused, or never evaluated, recorded nothing and never will: waiting
    for a trigger, which "no rows yet" advises, would wait for ever."""
    ses = _m68k_dual(monkeypatch, tmp_path)
    mstate.STATE.tallies[OWNER].update(change)
    with pytest.raises(mstate.Invalid) as err:
        mblits.read_rows(ses.scratch, mm.command("blit"), None, 903)
    assert "no rows yet" not in str(err.value) and said in str(err.value), str(err.value)
    assert ('declaration_clear(kind="watch", ref="0x700000", cpu=":maincpu") and declare it '
            'again') in str(err.value)
    assert err.value.fields == {"tally_id": mstate.STATE.tallies[OWNER]["tally_id"],
                                "state": state}, err.value.fields


def test_the_frame_the_cap_cut_is_not_called_complete(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    """The tap drops every row past its cap, so the frame of the last kept row may have lost
    some: that frame is marked, the frames before it are whole."""
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    rows = _m68k_dual_rows()
    kept = "".join(rows.splitlines(keepends=True)[:300])
    last_frame = int(kept.splitlines()[-1].split()[2])
    _declared(ses, kept, HEADER.replace("rows=352 overflow_rows=0", "rows=300 overflow_rows=52"))
    _screen(ses)
    cut = s.gfx_blits(draw_command="blit", frame=last_frame, scale=1)
    assert cut["rows_cut"] is True and cut["frame_complete"] is False, cut.get("summary")
    _screen(ses)
    whole = s.gfx_blits(draw_command="blit", frame=901, scale=1)
    assert whole["rows_cut"] is False and whole["frame_complete"] is True


def test_a_fire_word_wider_than_the_bus_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    _declared(ses, _row(1, 10, 0x1FD2, _words(0, 0, 1, 1)),
              HEADER.replace("data_width=16", "data_width=8"))
    _screen(ses)
    out = refused(r"fires on a word of 2 bytes and its cpu's bus writes 1",
                  s.gfx_blits(draw_command="blit", frame=10))
    assert out["tally_id"] == mstate.STATE.tallies[OWNER]["tally_id"]


def test_a_negative_tile_and_an_empty_walk_are_refused(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    text = Path(_sheet_manifest(tmp_path)).read_text()
    for old, new in (("        parts:\n          - {word: 6, mask: 0xfc00}\n",
                      "        parts:\n          - {word: 6, mask: 0xfc00}\n        add: -1\n"),
                     (_PLANES, ""),
                     ("      plane: {parts: [{word: 7, mask: 0x0010}], status: declared, source: "
                      "m68k-dual.cpp do_blit}\n", "")):
        text, n = re.subn(re.escape(old), new, text, count=1)
        assert n == 1, old
    path = tmp_path / "edge.yaml"
    path.write_text(text)
    assert s.gfx_load(path=str(path))["status"] == "ok"
    _declared(ses, _row(1, 10, 0x1FD2, _source_words(0, 0, 0, 5, 5, 6, 6))
              + _row(3, 10, 0x1FD4, _source_words(0, 0, 1, 20, 5, 10, 6)))
    out = refused(r"names source tile -1, below the first",
                  s.gfx_blit_source(draw_command="blit", index=0, frame=10))
    assert out["source_tile"] == -1
    out = refused(r"blit 1 of frame 10 covers no pixel .*end is behind it",
                  s.gfx_blit_source(draw_command="blit", index=1, frame=10))
    assert (out["destination"]["x"], out["destination"]["width"]) == (20, 0), out


def test_with_no_frame_before_the_stops_there_is_nothing_to_default_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    _declared(ses, _row(1, 903, 0x1FD2, _words(0, 0, 1, 1)))
    _screen(ses)
    out = refused(r"no blit of 'blit' is in the rows from a frame before this stop's frame 903",
                  s.gfx_blits(draw_command="blit"))
    assert out["rows_path"].endswith(".rows"), out


def test_a_source_with_no_known_stop_frame_needs_its_frame(monkeypatch: pytest.MonkeyPatch,
                                                           tmp_path: Path) -> None:
    """A stop whose survey read no frame (the gate records the stop, so the body is asked alone):
    the newest frame before it cannot be picked."""
    ses = _sourcing(monkeypatch, tmp_path, _row(1, 10, 0x1FD2, _source_words(0, 0, 0, 0, 0, 1, 1)))
    mstate.STATE.last_stop = {**mstate.STATE.last_stop, "frame": None}
    with pytest.raises(mstate.Invalid, match=r"this stop's frame is not known"):
        mblits.gfx_blit_source(cast(Any, ses), ses.scratch, "blit", None, 0, "", 0, 0, "", 5.0)


def test_a_rectangle_past_the_pixels_one_call_decodes_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from scry_mame import gfx
    rows = _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    monkeypatch.setattr(gfx, "TILE_PIXELS_MAX", 19)
    _serve_sheet(ses)
    out = refused(r"a 4x5 rectangle is past the 19 pixels one call decodes",
                  s.gfx_blit_source(draw_command="blit", index=0))
    assert "evaluated_by" in out
    monkeypatch.setattr(gfx, "TILE_PIXELS_MAX", 20)
    _serve_sheet(ses)
    assert s.gfx_blit_source(draw_command="blit", index=0)["status"] == "ok", "a bound is reachable"


# ------------------------------------------------------------------ what a reply leans on

def test_a_listed_page_names_the_flags_it_shows_as_not_proved(monkeypatch: pytest.MonkeyPatch,
                                                              tmp_path: Path) -> None:
    """Every listed blit carries its flags, so a reply that lists blits leans on them; the
    summary lists none and names none of them."""
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    listed = s.gfx_blits(draw_command="blit", detail=True, scale=1)
    assert listed["blits"][0]["flags"]["writes_index_0"] == 0
    assert "writes_index_0" in listed["not_proved"], listed["not_proved"]
    _screen(ses)
    summary = s.gfx_blits(draw_command="blit", scale=1)
    assert "writes_index_0" not in summary["not_proved"]


def test_the_summary_builds_no_row_per_blit(monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:
    """The default reply lists no blit, so it names each writer once, for the legend, and no
    blit's row is built only to be thrown away."""
    ses = _m68k_dual(monkeypatch, tmp_path)
    calls: list[int] = []
    real = mame_read.add_symbol

    def counted(row: dict[str, Any], pc: int, cpu: str | None) -> dict[str, Any]:
        calls.append(pc)
        return real(row, pc, cpu)

    monkeypatch.setattr(mame_read, "add_symbol", counted)
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", scale=1)
    assert out["status"] == "ok" and "blits" not in out, out
    assert len(calls) == len(out["legend"]), f"{len(calls)} writer lookups for a summary"


def test_only_the_blits_a_page_shows_are_labelled(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    """A writer's symbol is looked up for the page listed and the legend, not for every blit of
    the frame the page is cut from."""
    ses = _m68k_dual(monkeypatch, tmp_path)
    labelled: list[int] = []
    real = mame_read.add_symbol

    def counted(row: dict[str, Any], pc: int, cpu: str | None) -> dict[str, Any]:
        labelled.append(1)
        return real(row, pc, cpu)

    monkeypatch.setattr(mame_read, "add_symbol", counted)
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", detail=True, scale=1)
    assert out["listed"]["of"] > len(out["blits"]), "the frame holds more than one page"
    assert len(labelled) == len(out["blits"]) + len(out["legend"])


def test_the_boxes_ask_the_screen_for_its_colours_and_touch_no_pen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The boxes are drawn over the screen's colours, so the capture asks for no pens: none is
    rewritten to read them, and a palette the game adjusted cannot refuse the answer."""
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", scale=1)
    assert out["status"] == "ok", out
    sent = ses.stdin.getvalue().decode()
    # the path between the quotes: escaped twice in the chunk, so a Windows one holds `\\\\`
    asked = re.findall(r'mcp_capture\(\\"(?:[^"\\]|\\\\)+\\", (true|false)\)', sent)
    assert asked == ["false"], f"the capture asked for the pens: {asked}"


@pytest.mark.parametrize("order", ["big", "little"])
def test_a_fire_word_across_the_bus_word_has_no_value_in_any_write(order: str) -> None:
    """What the draft reads for each row: a word at an odd address of a 16-bit bus is in no
    single write, whichever lanes the write covered, so no row states a value for it."""
    for data, mask in ((0x1234, 0xFFFF), (0x0012, 0x00FF), (0x1200, 0xFF00)):
        assert capture.lane(data, mask, 16, order, 0x70001F, 2) is None
    assert capture.lane(0x1234, 0xFFFF, 16, order, 0x70001E, 2) == 0x1234


def test_as_many_writers_as_colours_do_not_repeat_one(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    words = _words(0, 0, 1, 1)
    _declared(ses, "".join(_row(i + 1, 902, 0x1000 + i, words)
                           for i in range(len(mblits.PC_COLOURS))))
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", scale=1, dest=str(tmp_path / "Boxes_1.PNG"))
    assert out["colors_repeat"] is False and out["image"]["path"] == str(tmp_path / "boxes-1.png")
    assert out["note"].endswith(str(written_as("dest", str(tmp_path / "Boxes_1.PNG")))), out


def test_a_summary_names_the_flags_its_planes_lean_on(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", scale=1)
    assert {"drawing_low_half", "scroll_x", "scroll_y"} <= set(out["not_proved"]), out["not_proved"]


def test_a_frame_with_no_paged_plane_says_nothing_of_pages(monkeypatch: pytest.MonkeyPatch,
                                                            tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    _declared(ses, _row(1, 902, 0x1000, _words(0, 0, 1, 1, w7=0x13)))
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", scale=1)
    assert out["status"] == "ok" and "note" not in out, out


def test_a_span_of_no_frames_is_empty() -> None:
    assert mblits._span([]) == {}


def test_a_walk_with_no_end_and_no_wrap_covers_its_size() -> None:
    assert mblits._walk(0, None, 10, True, None) == (0, 10)


def test_words_are_read_in_the_byte_order_asked() -> None:
    cmd = _cmd()
    assert mblits._words(bytes([1, 2] + [0] * 30), cmd, "little")[0] == 0x0201
    assert mblits._words(bytes([1, 2] + [0] * 30), cmd, "big")[0] == 0x0102


def test_a_direction_the_command_does_not_declare_walks_up() -> None:
    cmd = _cmd()
    assert mblits._up(cmd, _blit(cmd, _words(0, 0, 1, 1)), "no_such_role") is True


def test_a_plane_no_one_declares_is_drawn_at_order_zero() -> None:
    shown = [{"index": 2, "n": 1, "pc": "0x1", "plane": "fg"},
             {"index": 10, "n": 2, "pc": "0x2", "plane": "ghost"}]
    top = mblits._topmost(_cmd(), shown)
    assert top is not None and top["index"] == 2, top


@pytest.mark.parametrize("kwargs, said", [({"frame": True}, "frame=True"),
                                          ({"frame": -1}, "frame=-1")])
def test_check_gfx_blits_refuses_a_frame_that_is_a_bool_or_below_zero(kwargs: dict[str, Any],
                                                                       said: str) -> None:
    with pytest.raises(mstate.Invalid, match=said):
        mblits.check_gfx_blits(draw_command="blit", **kwargs)


def test_check_gfx_blits_takes_frame_zero_and_answers_its_dest(tmp_path: Path) -> None:
    mblits.check_gfx_blits(draw_command="blit", frame=0)
    dest = tmp_path / "a.png"
    assert mblits.check_gfx_blits(draw_command="blit", dest=str(dest)) == dest


@pytest.mark.parametrize("kwargs, said", [({"index": True}, "index=True"),
                                          ({"index": 0, "margin": True}, "margin=True"),
                                          ({"index": 0, "frame": -1}, "frame=-1")])
def test_check_gfx_blit_source_refuses_a_bool_place_or_margin_and_a_frame_below_zero(
        kwargs: dict[str, Any], said: str) -> None:
    with pytest.raises(mstate.Invalid, match=said):
        mblits.check_gfx_blit_source(draw_command="blit", **kwargs)


def test_check_gfx_blit_source_takes_the_widest_margin_and_answers_its_dest(
        tmp_path: Path) -> None:
    mblits.check_gfx_blit_source(draw_command="blit", index=0, margin=mblits.MARGIN_MAX)
    dest = tmp_path / "b.png"
    assert mblits.check_gfx_blit_source(draw_command="blit", index=0, dest=str(dest)) == dest


def _symbols(monkeypatch: pytest.MonkeyPatch, known: dict[tuple[int, str], str]) -> list[Any]:
    """Every cpu a writer's symbol is looked up on, in order; `known` answers by (pc, cpu)."""
    seen: list[Any] = []

    def label(addr: int, cpu: Any = None) -> str | None:
        seen.append(cpu)
        return known.get((addr, cpu))

    monkeypatch.setattr(mame_read, "symbol_label", label)
    return seen


def test_a_symbol_is_looked_up_on_the_cpu_that_ran_the_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _symbols(monkeypatch, {(0x100, ":sub"): "NAME+0x4"})
    row = mame_read.add_symbol({"pc": "x", "k": 1}, 0x100, ":sub")
    assert list(row.items()) == [("pc", "x"), ("k", 1), ("symbol", "NAME+0x4")], (
        "appended last, after the row's own keys")
    assert "symbol" not in mame_read.add_symbol({}, 0x200, ":sub")
    assert seen == [":sub", ":sub"], "the cpu passes through unchanged"


def test_a_window_is_refused_past_either_side_and_taken_flush_with_them() -> None:
    res = ml.resolve(mm.read(str(MANIFEST)).formats["page_512x512x8"].layout, None)
    for x, y, w, h in ((510, 0, 4, 2), (0, 510, 2, 4), (-1, 0, 2, 2), (0, -1, 2, 2)):
        with pytest.raises(mstate.Invalid):
            mblits.window(res, x, y, w, h, False)
    for x, y, w, h in ((0, 0, 2, 2), (508, 0, 4, 2), (0, 508, 2, 4)):
        assert mblits.window(res, x, y, w, h, False).name == res.name


# ------------------------------------------------------------------ what the blit tools hand on

def test_an_arc_of_one_pixel_is_one_pixel_and_one_ending_at_the_edge_is_none() -> None:
    assert mblits._arc(5, 1, 0, None, 10) == [(5, 6)]
    assert mblits._arc(0, 1, 0, None, 10) == [(0, 1)], "one pixel at the screen's first column"
    assert mblits._arc(10, 5, 0, None, 10) == [], "a piece starting where the screen ends"


def test_the_row_below_the_rectangle_is_margin() -> None:
    exact = mpng.Raster(3, 3, bytes(9), ((200, 200, 200),))
    view = mblits._margin_view(exact, 1, 1, 1)
    red = [view.pixels[(y * 3 + 1) * 3] for y in range(3)]    # column 1, row by row
    assert red == [200 >> mblits.MARGIN_DIM_SHIFT, 200, 200 >> mblits.MARGIN_DIM_SHIFT], red


def _no_planes(tmp_path: Path) -> mm.Command:
    return _variant(tmp_path, (_PLANES, ""),
                    ("      plane: {parts: [{word: 7, mask: 0x0010}], status: declared, source: "
                     "m68k-dual.cpp do_blit}\n", ""))


def test_a_walk_down_a_screen_that_does_not_wrap_covers_from_its_end(tmp_path: Path) -> None:
    cmd = _no_planes(tmp_path)
    geo = mblits.geometry(cmd, _blit(cmd, _words(40, 30, 31, 25, w7=0x00)), 336, 252)
    assert (geo["box"]["width"], geo["box"]["height"]) == (10, 6)
    assert geo["screen"] == [[31, 25, 10, 6]] and geo["clipped"] is False


def test_a_walk_cut_by_the_screens_bottom_alone_is_clipped(tmp_path: Path) -> None:
    cmd = _no_planes(tmp_path)
    geo = mblits.geometry(cmd, _blit(cmd, _words(10, 250, 13, 253)), 336, 252)
    assert geo["screen"] == [[10, 250, 4, 2]] and geo["clipped"] is True


def test_a_walk_across_the_planes_bottom_wraps_to_its_top() -> None:
    cmd = _cmd()
    geo = mblits.geometry(cmd, _blit(cmd, _words(0, 500, 3, 10)), 336, 252)
    assert geo["box"]["height"] == 512 - 500 + 11
    assert geo["screen"] == [[0, 0, 4, 11]] and geo["clipped"] is True, geo


def test_a_source_with_no_tile_role_reads_tile_zero(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    text, n = re.subn(r"      source_tile:\n        parts:\n          - \{word: 6, mask: 0xfc00\}\n"
                      r"        status: declared\n        source: m68k-dual.cpp do_blit\n", "",
                      Path(_sheet_manifest(tmp_path)).read_text(), count=1)
    assert n == 1
    path = tmp_path / "notile.yaml"
    path.write_text(text)
    assert s.gfx_load(path=str(path))["status"] == "ok"
    _declared(ses, _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54)),
              HEADER.replace("frame=903", "frame=11"))
    mstate.STATE.last_stop = {**mstate.STATE.last_stop, "frame": 11}
    _serve_sheet(ses)
    out = s.gfx_blit_source(draw_command="blit", index=0, scale=1)
    assert out["rect"]["tile"] == 0 and list(_png(out).pixels) == _expected(0, 2, 4, 4, 5), out


def test_a_margin_reaches_back_from_the_rectangles_corner(monkeypatch: pytest.MonkeyPatch,
                                                          tmp_path: Path) -> None:
    rows = _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_sheet(ses)
    out = s.gfx_blit_source(draw_command="blit", index=0, margin=1, scale=1)
    exact = png_read.read(Path(out["data"]["path"]).read_bytes())
    assert list(exact.pixels) == _expected(1, 1, 3, 6, 7)


def test_a_backwards_source_of_an_odd_width_is_shown_from_its_lowest_coordinate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rows = _row(1, 10, 0x1FD2, _source_words(9, 3, 2, 100, 50, 102, 51, w8=0x0020))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_sheet(ses)
    out = s.gfx_blit_source(draw_command="blit", index=0, scale=1)
    assert out["rect"] == {"tile": 2, "x": 7, "y": 3, "width": 3, "height": 2, "dir_x": -1,
                           "dir_y": -1}
    assert list(_png(out).pixels) == _expected(2, 7, 3, 3, 2)


def test_the_block_is_read_whole_with_the_assets_pens_at_its_depth(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """One evaluation: the asset's whole block (no span), and 256 pens from its base for an
    8-bit format, under the call's progress and name; the layout resolves with its account."""
    from scry_mame import gfx
    rows = _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    seen: dict[str, tuple[Any, ...]] = {}
    for name in ("read_with_pens", "resolved_for"):
        real = getattr(gfx, name)

        def spy(*args: Any, _real: Any = real, _name: str = name) -> Any:
            seen[_name] = args
            return _real(*args)

        monkeypatch.setattr(gfx, name, spy)
    _serve_sheet(ses)
    out = mblits.gfx_blit_source(cast(Any, ses), ses.scratch, "blit", None, 0, "", 0, 1, "", 5.0,
                                 _mark)
    assert out["status"] == "ok", out
    asset = mm.loaded().assets["pages"]
    read = seen["read_with_pens"]
    assert read[2:9] == ("", asset.tag, None, 0, asset.palette, asset.pen_base, 256), read
    assert read[10] is _mark and read[11] == "gfx_blit_source"
    assert "evaluated_by" in seen["resolved_for"][2]


def test_a_command_with_no_source_role_says_which_is_missing(monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    text, n = re.subn(r"      source_x:\n        parts:\n          - \{word: 0, mask: 0xff00\}\n"
                      r"          - \{word: 6, mask: 0x0100, at: 8\}\n        status: declared\n"
                      r"        source: m68k-dual.cpp do_blit\n", "", MANIFEST.read_text(), count=1)
    assert n == 1
    path = tmp_path / "nosx.yaml"
    path.write_text(text)
    assert s.gfx_load(path=str(path))["status"] == "ok"
    _declared(ses, _row(1, 10, 0x1FD2, _source_words(0, 0, 0, 0, 0, 1, 1)))
    refused(r"names no \['source_x'\] role, so where it reads is not stated",
            s.gfx_blit_source(draw_command="blit", index=0, frame=10))


def test_a_block_short_of_a_whole_tile_holds_only_the_whole_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """1000 bytes hold three 2048-bit tiles and part of a fourth, which is no tile."""
    rows = _row(1, 10, 0x1FD2, _source_words(0, 0, 3, 0, 0, 1, 1))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    seq = mstate.STATE.lua_seq + 1
    _serve_sheet(ses)
    ses.answers[seq] = ses.answers[seq].replace(b"size=1024", b"size=1000")
    (ses.scratch / f"block-{seq}.bin").write_bytes(SHEET[:1000])
    out = refused(r"source tile 3 is not inside region :gfx1, which holds 3 whole tile",
                  s.gfx_blit_source(draw_command="blit", index=0))
    assert out["tiles_available"] == 3


def test_a_palette_too_short_for_the_depth_is_refused_with_what_was_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rows = _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_pens(ses, "MAME_MCP_GFX_PENS_SHORT tag=:palette entries=16")
    out = refused(r"^256 pens from 0x0 run past :palette, which has 16 entries",
                  s.gfx_blit_source(draw_command="blit", index=0))
    assert out["entries"] == 16 and "evaluated_by" in out


def test_a_palette_the_machine_lacks_is_named_with_the_ones_it_has(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rows = _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54))
    ses = _sourcing(monkeypatch, tmp_path, rows)
    _serve_pens(ses, "MAME_MCP_GFX_PENS_NONE name=palette palettes=:other")
    out = refused(r"no palette device named 'palette'; this machine has \[':other'\]",
                  s.gfx_blit_source(draw_command="blit", index=0))
    assert out["code"] == "unknown_ref" and "evaluated_by" in out


def test_every_writer_is_named_on_the_cpu_the_capture_ran_on(monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    seen = _symbols(monkeypatch, {})
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    assert s.gfx_blits(draw_command="blit", scale=1)["status"] == "ok"
    assert seen and set(seen) == {":maincpu"}, "the legend's writers"
    seen.clear()
    _screen(ses)
    assert s.gfx_blits(draw_command="blit", detail=True, scale=1, frame=902)["status"] == "ok"
    assert seen and set(seen) == {":maincpu"}, "the listed blits' writers"
    seen.clear()
    (tmp_path / "src").mkdir()
    ses = _sourcing(monkeypatch, tmp_path / "src",
                    _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54)))
    _serve_sheet(ses)
    assert s.gfx_blit_source(draw_command="blit", index=0, scale=1)["status"] == "ok"
    assert seen == [":maincpu"], "the source's writer"


def test_planes_drawn_in_one_frame_are_listed_by_name_paged_or_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    _declared(ses, _row(1, 902, 0x1FD2, _words(0, 0, 3, 3))
              + _row(3, 902, 0x21AC, _words(0, 0, 3, 3, w7=0x13, w8=0xC020 | 0x40)))
    _screen(ses)
    out = s.gfx_blits(draw_command="blit", scale=1)
    assert out["status"] == "ok", out
    assert [p["plane"] for p in out["by_plane"]] == ["bg", "fg"], out["by_plane"]


def test_the_screen_is_captured_under_the_calls_progress(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    from scry_mame import screen as mame_screen
    seen: list[tuple[Any, ...]] = []
    real = mame_screen.capture

    def spy(*args: Any) -> Any:
        seen.append(args)
        return real(*args)

    monkeypatch.setattr(mame_screen, "capture", spy)
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    mblits.gfx_blits(cast(Any, ses), ses.scratch, "blit", None, None, False, 0, 1, "", 5.0, _mark)
    (args,) = seen
    assert args[4] is _mark


def test_reading_the_rows_leaves_the_next_stops_baseline_alone(monkeypatch: pytest.MonkeyPatch,
                                                               tmp_path: Path) -> None:
    ses = _m68k_dual(monkeypatch, tmp_path)
    _screen(ses)
    s.gfx_blits(draw_command="blit", scale=1)
    rec = mstate.STATE.tallies[OWNER]
    assert (rec["last_seq"], rec["last_total"]) == (0, 0), "a read is a look, not a stop"


def test_a_frame_missing_among_the_kept_ones_is_not_called_past_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    _declared(ses, _row(1, 900, 0x1FD2, _words(0, 0, 1, 1))
              + _row(3, 902, 0x1FD2, _words(0, 0, 1, 1)),
              HEADER.replace("rows=352 overflow_rows=0", "rows=2 overflow_rows=5"))
    _screen(ses)
    refused(r"no blit of 'blit' was fired in frame 901", s.gfx_blits(draw_command="blit",
                                                                     frame=901))


def test_a_capture_whose_install_has_not_answered_is_read_from_this_sessions_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The install's answer sits in the scratch's console log: reading the rows records it."""
    from scry_mame import files as mame_files
    ses = _m68k_dual(monkeypatch, tmp_path)
    rec = mstate.STATE.tallies[OWNER]
    rec.update(installed=None, seq=9999, mark=0, line="the install line", error=None)
    mame_files.log_path(ses.scratch, "process").write_bytes(b"MAME_MCP_LUA_END#9999\ttrue\tnil\n")
    _screen(ses)
    assert s.gfx_blits(draw_command="blit", scale=1)["status"] == "ok"
    assert rec["installed"] is True


def test_a_source_whose_capture_install_has_not_answered_reads_this_sessions_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from scry_mame import files as mame_files
    ses = _sourcing(monkeypatch, tmp_path,
                    _row(1, 10, 0x1FD2, _source_words(2, 3, 1, 100, 50, 103, 54)))
    rec = mstate.STATE.tallies[OWNER]
    rec.update(installed=None, seq=9999, mark=0, line="the install line", error=None)
    mame_files.log_path(ses.scratch, "process").write_bytes(b"MAME_MCP_LUA_END#9999\ttrue\tnil\n")
    _serve_sheet(ses)
    assert s.gfx_blit_source(draw_command="blit", index=0, scale=1)["status"] == "ok"
    assert rec["installed"] is True
