"""The sweep: a block under the fixed family of candidate layouts, one labelled sheet, its ids
taken by `gfx_locate`, and a person's choice from it recorded and promoted.

The doubles are E1's, captured from a live `circus` (`gfx-circus.txt` with the dump of its
`gfx1`, `locate-circus-g.txt` with its screen at frame 600): the chars are 8x8 at one bit, and
the G of "GAME" sits at (88, 96) as tile 0x47, which is what the sweep's one-plane candidate has
to be proved against.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import png_read  # noqa: E402
from scry_core import picture as mpicture  # noqa: E402
from session_doubles import refused  # noqa: E402
from test_film import _read_label  # noqa: E402
from test_gfx import _mark, _png, _serve  # noqa: E402
from test_lua import _channel, _ChannelSession  # noqa: E402

import mame_evidence as evidence  # noqa: E402
import mame_font as font  # noqa: E402
import mame_layout as ml  # noqa: E402
import mame_sheet as msheet  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_sweep as msweep  # noqa: E402
import mame_yaml  # noqa: E402
import server as s  # noqa: E402


def _swept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kw: Any
           ) -> tuple[_ChannelSession, dict[str, Any]]:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    _serve(ses, "gfx-circus", block="circus-gfx1")
    out = s.gfx_sweep(tag="gfx1", **kw)
    assert out["status"] == "ok", out
    return ses, out


def _labels(c: dict[str, Any]) -> tuple[str, str, str]:
    """What a cell must say, from the listing: its id, its depth and size, its arrangement."""
    depth, size, arrangement = c["what"].split(" ", 2)
    return (c["id"].upper(), f"{depth} {size}".upper(), arrangement.replace(",", "").upper())


def test_the_family_holds_each_arrangement_once() -> None:
    names = [what for what, _ in msweep.family([1, 2, 4], [[8, 8]], split_ok=True)]
    assert names == ["1bpp 8x8 rows",
                     "2bpp 8x8 packed, rows", "2bpp 8x8 planar, rows", "2bpp 8x8 split, rows",
                     "4bpp 8x8 packed, rows", "4bpp 8x8 planar, rows", "4bpp 8x8 split, rows"]
    assert all("split" not in w for w, _ in msweep.family([2], [[8, 8]], split_ok=False))
    # a tile one cell wide: its cells across, its cells down and its rows are one layout
    assert [w for w, _ in msweep.family([1], [[8, 16]], split_ok=True)] == ["1bpp 8x16 rows"]


def test_cells_down_is_the_column_strip_layout_circus_draws_its_clown_with() -> None:
    """The arrangement the live sweep of circus's `gfx2` showed as clowns, written the way a
    driver would (8-pixel columns, the right one 16 bytes on)."""
    ((_, raw),) = [c for c in msweep.family([1], [[16, 16]], split_ok=True)
                   if c[0].endswith("cells down")]
    strips = ml.parse_layout({"width": 16, "height": 16, "planes": 1, "planeoffset": [0],
                              "xoffset": "{STEP8(0,1), STEP8(128,1)}",
                              "yoffset": "{STEP16(0,8)}", "charincrement": 256})
    assert ml.resolve(ml.parse_layout(raw), None) == ml.resolve(strips, None)


def test_a_sweep_draws_every_candidate_on_one_labelled_sheet(monkeypatch: pytest.MonkeyPatch,
                                                              tmp_path: Path) -> None:
    ses, out = _swept(monkeypatch, tmp_path)
    ids = [c["id"] for c in out["candidates"]]
    assert ids == [f"s1c{k}" for k in range(1, 8)] and out["sweep"] == 1
    assert all(c["shown"] == msweep.COUNT_DEFAULT for c in out["candidates"]), out["candidates"]
    assert out["palette"] == "none" and "NOT the machine's" in out["note"]
    assert out["image"]["inline"] is True and out["session"]["altered"] is False
    assert out["summary"].startswith("gfx_sweep region :gfx1: sweep 1, 7 candidates "
                                     "s1c1..s1c7, 7 drawn;")
    (rec,) = evidence.sweeps()
    assert rec["sheet"]["sha256"] == out["image"]["sha256"] and len(rec["candidates"]) == 7
    # READ BACK OFF THE PIXELS, never off the strings the writer drew
    sheet = _png(out)
    grid = msweep.COLUMNS * 8 * out["cell_scale"]
    rows = -(-msweep.COUNT_DEFAULT // msweep.COLUMNS) * 8 * out["cell_scale"]
    labels: list[tuple[str, ...]] = [_labels(c) for c in out["candidates"]]
    lay = msheet.layout((grid, rows), labels)
    cols, _ = msheet.page_shape(lay, len(labels))
    chars = (lay.cell[0] - 2 * msheet.LABEL_PAD) // font.advance(msheet.LABEL_SCALE)
    for i, want in enumerate(labels):
        x, y = lay.label_origin(i % cols, i // cols)
        got = tuple(_read_label(sheet, x, y + n * font.line_height(msheet.LABEL_SCALE), chars,
                                out["image"]["scale"]) for n in range(3))
        assert got == want, (i, got, want)


def test_a_sweep_id_is_a_layout_for_locate_and_the_draft_proves_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses, _ = _swept(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=["s1c1", "s1c2", "s1c5"], patch=[88, 96, 8, 8], tag="gfx1",
                       flips=["none"])
    assert out["status"] == "ok", out
    assert [(m["layout"], m["tile"]) for m in out["matches"]] == [("s1c1", 0x47)]
    assert out["evidence"] == {"locate": 1}
    draft = s.gfx_draft()
    assert draft["formats"] == {"tiles_8x8x1": "proved"} and draft["asset_names"] == ["gfx1"]


def test_gfx_view_takes_a_sweep_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses, _ = _swept(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus", block="circus-gfx1")
    out = s.gfx_view(layout="s1c1", palette="none", tag="gfx1", count=8)
    assert out["status"] == "ok" and out["layout"]["name"] == "s1c1", out


def test_an_id_no_sweep_holds_is_refused_naming_the_ones_it_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _swept(monkeypatch, tmp_path)
    out = refused("names no candidate of this session's sweeps",
                  s.gfx_view(layout="s1c9", palette="none", tag="gfx1"))
    assert "s1c1" in out["message"] and out["code"] == "unknown_ref", out


def test_a_choice_is_human_until_a_match_confirms_it(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    ses, out = _swept(monkeypatch, tmp_path)
    chose = s.gfx_draft(choose={"candidate": "s1c1", "chosen_by": "the owner"})
    assert chose["formats"] == {"tiles_8x8x1": "human"}
    assert chose["chose"]["chosen_by"] == "the owner"
    assert chose["asset_names"] == [], "chosen under no palette, so no asset"
    text = Path(chose["manifest"]["path"]).read_text()
    assert f"chosen by the owner from gfx_sweep s1's sheet sha256 {out['image']['sha256'][:16]}" \
        in text
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    s.gfx_locate(layouts=["s1c1"], patch=[88, 96, 8, 8], tag="gfx1", flips=["none"])
    promoted = s.gfx_draft()
    assert promoted["formats"] == {"tiles_8x8x1": "proved"}
    fmt = mame_yaml.loads(Path(promoted["manifest"]["path"]).read_text())["formats"]["tiles_8x8x1"]
    assert fmt["source"].startswith("gfx_locate matched it on the screen on gfx1, told apart "
                                    "from every rival, confirming the choice of the owner "
                                    "(s1c1); evidence in"), fmt["source"]


def test_a_choice_a_match_contradicts_is_said(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    ses, _ = _swept(monkeypatch, tmp_path)
    s.gfx_draft(choose={"candidate": "s1c2", "chosen_by": "a guess"})
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    s.gfx_locate(layouts=["s1c1"], patch=[88, 96, 8, 8], tag="gfx1", flips=["none"])
    out = s.gfx_draft()
    assert out["formats"] == {"tiles_8x8x1": "proved"}
    assert any("s1c2 was contradicted" in why for why in out["not_proved"]), out["not_proved"]
    report = json.loads(Path(out["report"]["path"]).read_text())
    (entry,) = report["formats"]["tiles_8x8x1"]
    assert entry["contradicted_choice"] is True and entry["choice"]["candidate"] == "s1c2"


def test_a_choice_of_an_id_no_sweep_holds_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    _swept(monkeypatch, tmp_path)
    refused(r"^choose\.candidate='s2c1' names no candidate",
            s.gfx_draft(choose={"candidate": "s2c1", "chosen_by": "me"}))
    assert evidence.choices() == []


@pytest.mark.parametrize("kw,why", [
    ({"planes": [1, 2, 3, 4, 5, 6], "sizes": [[8, 8], [16, 16]]}, "past the 16 one sheet holds"),
    ({"planes": [0]}, "depths of 1..8"), ({"planes": [1, 1]}, "each once"),
    ({"sizes": [[12, 8]]}, "each side one of"), ({"sizes": [[8]]}, "tile sizes"),
    ({"count": 0}, "count=0"), ({"count": 65}, "count=65"),
    ({"pen_base": 16}, "with palette `none` there are none"),
    ({"palette": "a b"}, "palette='a b': a palette device's tag"),
    ({"tag": "", "ref": ""}, "one source per call"),
])
def test_a_sweep_is_judged_before_the_machine(kw: dict[str, Any], why: str) -> None:
    refused(why, s.gfx_sweep(**{"tag": "gfx1", **kw}))


def test_a_sheet_the_ceiling_cannot_hold_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    monkeypatch.setattr(msweep, "ENLARGE_MAX", 1)
    monkeypatch.setattr(mpicture, "within_ceiling", lambda w, h: False)
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus", block="circus-gfx1")
    refused("do not fit one sheet", s.gfx_sweep(tag="gfx1"))


def test_the_sheet_is_an_rgb_png(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, out = _swept(monkeypatch, tmp_path, planes=[1])
    pic = png_read.read(Path(out["image"]["path"]).read_bytes())
    assert out["image"]["indexed"] is False and pic.width == out["image"]["width"]


def test_a_choice_is_recorded_once_and_not_by_a_draft_that_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A retry after a failed draft, or the same pick made twice, is still ONE person's pick."""
    import mame_manifest as mm

    _swept(monkeypatch, tmp_path)
    real = mm.parse

    def refusing(*_: Any, **__: Any) -> Any:
        raise mm.ManifestError("a draft the loader refuses")

    monkeypatch.setattr(mm, "parse", refusing)
    pick = {"candidate": "s1c1", "chosen_by": "the owner"}
    assert s.gfx_draft(choose=pick)["code"] == "unexpected_answer"
    assert evidence.choices() == [], "a draft that failed recorded no choice"
    monkeypatch.setattr(mm, "parse", real)
    assert s.gfx_draft(choose=pick)["status"] == "ok"
    assert s.gfx_draft(choose=pick)["status"] == "ok"
    assert len(evidence.choices()) == 1, evidence.choices()


@pytest.mark.parametrize(("planes", "size", "what", "driver"), [
    (4, [8, 16], "4bpp 8x16 packed, rows", "GRID_SPRITE"),
    (3, [8, 8], "3bpp 8x8 split, rows", "WITCH_TILE"),
])
def test_a_deeper_candidate_is_a_drivers_own_layout(planes: int, size: list[int], what: str,
                                                    driver: str) -> None:
    """The family's arithmetic for more than one plane, against two layouts transcribed from
    drivers: gridlee's sprites, two pixels a byte high nibble first, are the packed rows
    candidate; witchgme's tiles, planes a third of the region apart, the split one."""
    import gfx_layouts
    (raw,) = [r for w, r in msweep.family([planes], [size], split_ok=True) if w == what]
    bits = 3 * 8 * 8 * 64 * 8
    ours = ml.resolve(ml.parse_layout(raw), bits).as_reply()
    theirs = ml.resolve(ml.parse_layout(getattr(gfx_layouts, driver), allow_name=True),
                        bits).as_reply()
    assert {**ours, "name": None} == {**theirs, "name": None}


# ------------------------------------------------------------------ the family's arithmetic

def test_two_planes_are_packed_planar_or_split_as_a_driver_writes_them() -> None:
    packed = msweep._layout(2, 8, 8, "packed", "rows")
    assert (packed["planeoffset"], packed["xoffset"], packed["yoffset"]) == (
        [0, 1], [0, 2, 4, 6, 8, 10, 12, 14], [0, 16, 32, 48, 64, 80, 96, 112])
    planar = msweep._layout(2, 8, 8, "planar", "rows")
    assert (planar["planeoffset"], planar["xoffset"], planar["yoffset"]) == (
        [0, 8], list(range(8)), [0, 16, 32, 48, 64, 80, 96, 112])
    split = msweep._layout(2, 8, 8, "split", "rows")
    assert (split["planeoffset"], split["xoffset"], split["yoffset"]) == (
        ["RGN_FRAC(0,2)", "RGN_FRAC(1,2)"], list(range(8)), list(range(0, 64, 8)))
    assert msweep._layout(1, 16, 8, "packed", "rows")["xoffset"][8] == 8
    assert msweep._layout(1, 16, 16, "packed", "cells across")["xoffset"][8] == 64
    assert msweep._layout(1, 16, 16, "packed", "cells down")["xoffset"][8] == 128


def test_a_tile_wider_than_a_cell_is_tried_in_every_order() -> None:
    # one row of cells: across and down are one layout, kept once
    assert [w for w, _ in msweep.family([1], [[16, 8]], split_ok=True)] == [
        "1bpp 16x8 rows", "1bpp 16x8 cells across"]
    assert len(msweep.family([1], [[16, 16]], split_ok=True)) == 3
    assert len(msweep.family([1], [[9, 8]], split_ok=True)) > 1, "a width past 8 is wide"


def test_a_cell_is_placed_top_left_on_the_sheets_ground() -> None:
    rgb = bytes(range(12))                                  # 2x2, row 1 is bytes 6..11
    out = msweep._padded(2, 2, rgb, (6, 4), 1)
    assert len(out) == 6 * 4 * 3
    assert out[:6] == rgb[:6] and out[18:24] == rgb[6:12]
    assert out[6:9] == bytes(msheet.GROUND) and out[3 * 18:3 * 18 + 3] == bytes(msheet.GROUND)


def _cells(n: int) -> list[tuple[tuple[str, ...], tuple[int, int, bytes]]]:
    return [((f"S1C{k}", "1BPP 8X8", "ROWS"), (8, 8, bytes(8 * 8 * 3))) for k in range(n)]


def test_the_sheet_takes_the_largest_enlargement_that_fits_down_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells = _cells(2)
    labels = [lab for lab, _ in cells]
    lay = msheet.layout((8, 8), labels)
    most = lay.size(*msheet.page_shape(lay, len(cells)))     # the page unenlarged, a real fit
    monkeypatch.setattr(mpicture, "within_ceiling", lambda w, h: w <= most[0] and h <= most[1])
    _raster, factor = msweep._page(cells)
    assert factor == 1


def test_a_page_needs_room_for_every_cell_and_the_ceiling_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(msheet, "page_shape", lambda lay, n: (2, 2))
    monkeypatch.setattr(mpicture, "within_ceiling", lambda w, h: True)
    assert msweep._page(_cells(3))[1] == msweep.ENLARGE_MAX, "two by two holds three"
    monkeypatch.setattr(mpicture, "within_ceiling", lambda w, h: False)
    with pytest.raises(mstate.Invalid, match="do not fit one sheet"):
        msweep._page(_cells(3))


# ------------------------------------------------------------------ the arguments, at their edges

@pytest.mark.parametrize(("kw", "said"), [
    ({"planes": 5}, "depths of 1..8"), ({"planes": [True]}, "depths of 1..8"),
    ({"planes": [9]}, "depths of 1..8"), ({"sizes": 5}, "tile sizes"),
    ({"count": True}, "count is a count; got True"), ({"count": 0}, "count=0 is outside"),
    ({"count": msweep.COUNT_MAX + 1}, f"count={msweep.COUNT_MAX + 1}"),
])
def test_a_sweeps_arguments_are_refused_by_their_shape(kw: dict[str, Any], said: str) -> None:
    with pytest.raises(mstate.Invalid, match=said):
        msweep.check_gfx_sweep(tag="gfx1", **kw)


def test_a_sweeps_arguments_are_taken_at_their_edges(tmp_path: Path) -> None:
    for kw in ({"planes": [8]}, {"count": 1}, {"count": msweep.COUNT_MAX}):
        msweep.check_gfx_sweep(tag="gfx1", **kw)
    cands, dest = msweep.check_gfx_sweep(ref="0x1000", count=7, planes=[1],
                                         dest=str(tmp_path / "s.png"))
    assert dest == tmp_path / "s.png" and cands


def test_the_sheets_bound_is_its_candidate_count(monkeypatch: pytest.MonkeyPatch) -> None:
    some = msweep.family([1], [[8, 8]], split_ok=True)
    monkeypatch.setattr(msweep, "family", lambda *a, **k: some * msweep.SWEEP_MAX)
    msweep.check_gfx_sweep(tag="gfx1")
    monkeypatch.setattr(msweep, "family", lambda *a, **k: some * (msweep.SWEEP_MAX + 1))
    with pytest.raises(mstate.Invalid) as err:
        msweep.check_gfx_sweep(tag="gfx1")
    assert err.value.fields["candidates"] == msweep.SWEEP_MAX + 1


# ------------------------------------------------------------------ the sweep's reply

def test_a_sweep_under_the_machines_palette_says_so(monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    _ses, out = _swept(monkeypatch, tmp_path, planes=[1], palette="palette")
    assert out["real_colors"] is True and out["palette"] == ":palette" and "note" not in out
    assert out["next"].startswith("gfx_locate(layouts=[<ids>]) proves one against the screen")
    assert 'gfx_draft(choose={"candidate": <id>, "chosen_by": <who>}) records' in out["next"]
    assert "pc_before" in out and Path(out["image"]["path"]).name.startswith("sweep-")


def test_a_sweep_from_an_offset_reads_from_there_past_candidates_with_no_room(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Eight bytes before the block's end: an 8bpp tile has no room, a 1bpp one exactly one,
    and the 1bpp candidate after the empty ones is still drawn."""
    _ses, out = _swept(monkeypatch, tmp_path, planes=[8, 1], offset=2040)
    assert out["offset"] == 2040
    by_what = {c["what"]: c for c in out["candidates"]}
    assert by_what["1bpp 8x8 rows"]["tiles_available"] == 1
    assert all(c["tiles_available"] == 0 for w, c in by_what.items() if w.startswith("8bpp"))


def test_a_sweep_with_no_candidate_that_fits_is_refused_with_what_it_tried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    _serve(ses, "gfx-circus", block="circus-gfx1")
    out = refused("no candidate holds a whole tile", s.gfx_sweep(tag="gfx1", planes=[2],
                                                                 offset=2040))
    assert out["code"] == "bad_argument" and out["size"] == 2048
    assert [c["tiles_available"] for c in out["candidates"]] == [0] * len(out["candidates"])
    assert "evaluated_by" in out


# ------------------------------------------------------------------ a sweep id, once resolved

def test_a_sweep_id_that_needs_a_block_is_refused_through_a_ref(monkeypatch: pytest.MonkeyPatch,
                                                                tmp_path: Path) -> None:
    """A split candidate's planes are a fraction of the block apart, and a range of a cpu's
    space is no block: the id is judged against the source once it names its layout."""
    _, out = _swept(monkeypatch, tmp_path)
    split = next(c["id"] for c in out["candidates"] if "split" in c["what"])
    got = refused("uses RGN_FRAC", s.gfx_locate(layouts=[split], patch=[0, 0, 8, 8], ref="0x1000",
                                                count=1))
    assert got["code"] == "bad_argument"


def test_a_sweep_id_bounds_transparent_by_its_own_depth(monkeypatch: pytest.MonkeyPatch,
                                                        tmp_path: Path) -> None:
    _swept(monkeypatch, tmp_path)
    got = refused(r"transparent=2: a pixel of s1c1's 1 plane holds 0\.\.1", s.gfx_locate(
        layouts=["s1c1"], patch=[0, 0, 8, 8], tag="gfx1", transparent=2))
    assert got["code"] == "bad_argument"


def test_a_sweep_id_through_a_ref_with_its_count_is_searched(monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    ses, _ = _swept(monkeypatch, tmp_path)
    _serve(ses, "locate-gridlee-ref", screen="gridlee-screen", block="gridlee-space-800")
    out = s.gfx_locate(layouts=["s1c1"], patch=[96, 96, 8, 8], ref="0x800", count=8,
                       flips=["none"])
    assert out["status"] == "ok" and out["candidates"][0]["tiles_searched"] == [0, 8], out


# ------------------------------------------------------------------ what gfx_sweep hands on

def _sweep_reads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    """What each call hands to the one evaluation that reads the block and the pens."""
    import mame_gfx as gfx
    seen: list[tuple[Any, ...]] = []
    real = gfx.read_with_pens

    def spy(*args: Any) -> Any:
        seen.append(args)
        return real(*args)

    monkeypatch.setattr(gfx, "read_with_pens", spy)
    return seen


def test_a_sweep_of_a_cpu_space_range_reads_from_its_address(monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    """32 tiles from 0x1000 under 1, 2 and 4 bits: the deepest reaches 32 * 32 bytes."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-gridlee-ref", block="gridlee-space-1000")
    out = s.gfx_sweep(ref="0x1000", count=32, palette="palette", pen_base=944)
    assert out["status"] == "ok", out
    assert (out["kind"], out["addr"], out["offset"]) == ("space", "0x00001000", 0)
    assert out["addr_cpu"], out
    assert f", {0x1000}, {32 * 32})" in ses.stdin.getvalue().decode()


def test_a_sweep_hands_its_block_and_pens_request_to_one_evaluation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    seen = _sweep_reads(monkeypatch)
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    _serve(ses, "gfx-circus", block="circus-gfx1")
    out = msweep.gfx_sweep(cast(Any, ses), ses.scratch, "gfx1", "", 0, msweep.COUNT_DEFAULT, [1],
                           None, "palette", 0, 0, "", "", 5.0, _mark)
    assert out["status"] == "ok", out
    (args,) = seen
    assert args[4:9] == (None, 0, "palette", 0, 2), "the whole block, 2 pens for 1 bit"
    assert args[10] is _mark and args[11] == "gfx_sweep"


def test_a_sweep_draws_under_the_pens_it_read(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    """gridlee's pens from 928 are no grey ramp: each candidate's cells are drawn in the first
    2**planes of them, as the answer listed them."""
    ses = _channel(monkeypatch, tmp_path)
    drawn: list[list[Any]] = []
    real = msweep._cell

    def spy(res: Any, data: bytes, start: int, shown: int, colours: list[Any]) -> Any:
        drawn.append(colours)
        return real(res, data, start, shown, colours)

    monkeypatch.setattr(msweep, "_cell", spy)
    _serve(ses, "gfx-gridlee-sprites", block="gridlee-gfx1")
    assert s.gfx_sweep(tag="gfx1", palette="palette", pen_base=928)["status"] == "ok"
    text = (Path(__file__).parent / "fixtures" / "gfx" / "gfx-gridlee-sprites.txt").read_text()
    argb = [int(v, 16) for v in text.split("pens=")[1].split()[0].split(",")]
    pens = [((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF) for c in argb]
    assert drawn[0] == pens[:2] and drawn[-1] == pens[:16], drawn


def test_a_sweep_takes_its_dest_scale_and_sizes(monkeypatch: pytest.MonkeyPatch,
                                                tmp_path: Path) -> None:
    dest = tmp_path / "sheet.png"
    _, out = _swept(monkeypatch, tmp_path, dest=str(dest), scale=2, planes=[1],
                    sizes=[[16, 16]])
    assert out["image"]["path"] == str(dest) and out["image"]["scale"] == 2
    assert all(" 16x16 " in c["what"] for c in out["candidates"]), out["candidates"]
    assert out["how"] == f"gfx_sweep: {out['evaluated_by']}"
    assert out["next"] == ("gfx_locate(layouts=[<ids>]) proves one against the screen; "
                           'gfx_draft(choose={"candidate": <id>, "chosen_by": <who>}) records a '
                           "person's pick")


def test_a_sweep_under_a_palette_the_machine_lacks_is_refused_naming_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus-nosuch-palette", block="circus-gfx1")
    out = refused(r"no palette device named 'nosuch'", s.gfx_sweep(tag="gfx1", palette="nosuch"))
    assert "evaluated_by" in out


def test_a_sweep_under_a_palette_too_short_says_what_it_asked(monkeypatch: pytest.MonkeyPatch,
                                                              tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus-short", block="circus-gfx1")
    out = refused(r"^16 pens from 0x0 run past :palette, which has 2 entries",
                  s.gfx_sweep(tag="gfx1", palette="palette"))
    assert "evaluated_by" in out


def test_a_choice_names_its_candidate_and_carries_the_sweeps_palette(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Chosen before any match, the format is the candidate's layout under its own id, and the
    asset reads the pens the sheet was drawn under, from the sweep's base."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "gridlee")
    _serve(ses, "gfx-gridlee-sprites", block="gridlee-gfx1")
    assert s.gfx_sweep(tag="gfx1", palette="palette", pen_base=928)["status"] == "ok"
    chose = s.gfx_draft(choose={"candidate": "s1c1", "chosen_by": "the owner"})
    assert chose["status"] == "ok", chose
    report = json.loads(Path(chose["report"]["path"]).read_text())
    (fmt,) = report["formats"]
    assert report["formats"][fmt][0]["layout"]["name"] == "s1c1"
    (asset,) = report["assets"].values()
    assert asset["pen_base"] == 928, asset
    draft = Path(chose["manifest"]["path"]).read_text()
    assert 'palette: "palette"' in draft and "pen_base: 928" in draft, draft
    assert 'source: "the pens of the sheet it was chosen from;' in draft
    (kept,) = report["evidence"]["choices"]
    assert kept["candidate"] == "s1c1" and "key" not in kept, kept
    assert kept["chosen_by"] == chose["chose"]["chosen_by"] and "by" not in kept, kept


# ------------------------------------------------------------------ choices, several and repeated

def test_choices_on_one_block_are_written_in_the_order_of_their_keys_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An 8x8 and a 16x16 chosen in that order: `(16, 16)` sorts before `(8, 8)` as text."""
    _, out = _swept(monkeypatch, tmp_path, planes=[1], sizes=[[8, 8], [16, 16]])
    ids = {c["what"]: c["id"] for c in out["candidates"]}
    for what in ("1bpp 8x8 rows", "1bpp 16x16 rows"):
        assert s.gfx_draft(choose={"candidate": ids[what], "chosen_by": "me"})["status"] == "ok"
    draft = s.gfx_draft()
    text = Path(draft["manifest"]["path"]).read_text()
    assert list(mame_yaml.loads(text)["formats"]) == ["tiles_16x16x1", "tiles_8x8x1"], text


def test_a_choice_on_another_block_is_passed_over_not_the_end(monkeypatch: pytest.MonkeyPatch,
                                                              tmp_path: Path) -> None:
    """Two sweeps of one tag at 0x20 and 0x100: as text the second's choice sorts first, and
    the block at 0x20 still writes its own."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    for offset in (0x20, 0x100):
        _serve(ses, "gfx-circus", block="circus-gfx1")
        assert s.gfx_sweep(tag="gfx1", planes=[1], offset=offset)["status"] == "ok"
    for cid in ("s1c1", "s2c1"):
        assert s.gfx_draft(choose={"candidate": cid, "chosen_by": "me"})["status"] == "ok"
    report = json.loads(Path(s.gfx_draft()["report"]["path"]).read_text())
    offsets = sorted(e["source"]["offset"] for e in report["formats"]["tiles_8x8x1"])
    assert offsets == [0x20, 0x100], report["formats"]


def test_a_choice_among_layouts_the_screen_could_not_tell_apart_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _swept(monkeypatch, tmp_path, planes=[1])
    chosen = evidence.sweeps()[0]["candidates"][0]["resolved"]
    rival = dict(chosen, name="rival", xoffset=list(reversed(chosen["xoffset"])))
    both = [chosen, rival]
    mstate.STATE.evidence["locates"][:] = [{
        "n": 1, "frame_screen": 700, "palette": ":palette",
        "source": {"kind": "region", "tag": ":gfx1", "offset": 0}, "patch": [0, 0, 248, 256],
        "transparent": None, "flips": ["none"], "candidates": both, "searched_whole": [True] * 2,
        "matches_total": 2,
        "matches": [{"layout": lay["name"], "window": [88, 96], "tile": 1, "flip": "none",
                     "base": 0, "byte": 8, "shape": [8, 8, 10]} for lay in both]}]
    out = s.gfx_draft(choose={"candidate": "s1c1", "chosen_by": "me"})
    assert out["formats"] == {"tiles_8x8x1": "human"}, out
    assert (":gfx1: s1c1 is written as a person's choice among layouts the screen could not "
            "tell apart") in out["not_proved"], out["not_proved"]


def test_a_choice_made_again_and_then_failed_keeps_the_first(monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    _swept(monkeypatch, tmp_path)
    choose = {"candidate": "s1c1", "chosen_by": "the owner"}
    assert s.gfx_draft(choose=choose)["status"] == "ok"
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        refused("cannot be written", s.gfx_draft(dest=str(locked / "gfx.yaml"), choose=choose))
    finally:
        locked.chmod(0o700)
    assert [c["candidate"] for c in evidence.choices()] == ["s1c1"]


def test_an_id_no_sweep_holds_among_locates_candidates_is_named_by_its_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _swept(monkeypatch, tmp_path)
    refused(r"^layouts\[1\]='s1c9' names no candidate of this session's sweeps",
            s.gfx_locate(layouts=["s1c1", "s1c9"], patch=[0, 0, 8, 8], tag="gfx1"))
