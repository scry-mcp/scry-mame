"""The graphics tools against what real boards answered.

EVERY DOUBLE IS CAPTURED, in `tests/fixtures/gfx/`: `<case>.txt` is what MAME 0.289's console
printed for the chunk the tool sent, through its sentinel, and `<board>-*.bin.gz` the file the
chunk wrote (a screen's capture, a block's dump), from live runs of `circus` (1-bit chars, two
pens), `gridlee` (4-bit sprites and framebuffer, 2048 pens), `starfire` (a direct-colour screen),
`topgunnr` (a vector screen), `witchgme` (3-bit tiles a third of a region apart) and `hardhat`
(its hall of fame at frame 2400: text in pen 5 over pen 0, two banks for a 1-bit char). The one
exception is named where it is used. The known answers are the machines' own: circus's
`videoram` holds "GAME" at the place the chars are found, gridlee's `spriteram` names image
0xbf at the place the sprite is found, and hardhat's `videoram` row 3 from column 6 holds
`11 0a 1b 0d 11 0a 1d`, "HARDHAT", drawn from `characterram` a bit a pixel (`exidy.cpp`,
`draw_background`), which is `BYTES_8X8` over its first plane.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import re
import sys
from array import array
from pathlib import Path
from typing import Any, cast

import png_read  # noqa: E402
import pytest
from lua_support import _channel, _ChannelSession  # noqa: E402
from mcp.types import CallToolResult
from scry_core import pens as scry_pens  # noqa: E402
from scry_core import picture as mpicture  # noqa: E402
from scry_core import png, raster  # noqa: E402
from scry_core import progress as mprogress  # noqa: E402
from scry_core.file_names import written_as  # noqa: E402
from session_doubles import refused  # noqa: E402

from scry_mame import chunk as mchunk  # noqa: E402
from scry_mame import gfx  # noqa: E402
from scry_mame import layout as ml  # noqa: E402
from scry_mame import locate as mlocate  # noqa: E402
from scry_mame import palette as mpalette  # noqa: E402
from scry_mame import screen as mscreen  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent / "live"))
from gfx_layouts import BYTES_8X8, CIRCUS_CHAR, GRID_FB, GRID_SPRITE, WITCH_TILE  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "gfx"
def _serve(ses: _ChannelSession, case: str, **files: str) -> None:
    """The next call answers what `case` captured, renumbered as that call, and finds the files
    its chunk wrote (`screen=` a capture, `block=` a dump) where it would have written them."""
    seq = mstate.STATE.lua_seq + 1
    text = (FIX / f"{case}.txt").read_bytes()
    ses.answers[seq] = re.sub(rb"MAME_MCP_LUA_END#\d+", b"MAME_MCP_LUA_END#%d" % seq, text)
    for prefix, name in files.items():
        (ses.scratch / f"{prefix}-{seq}.bin").write_bytes(
            gzip.decompress((FIX / f"{name}-bin.gz").read_bytes()))


def _capture(name: str) -> bytes:
    return gzip.decompress((FIX / f"{name}-bin.gz").read_bytes())


def _png(out: dict[str, Any]) -> png_read.Png:
    data = Path(out["image"]["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == out["image"]["sha256"]
    return png_read.read(data)


def _left_clean(ses: _ChannelSession) -> None:
    left = sorted(p.name for p in ses.scratch.glob("*.bin"))
    assert left == [], f"a chunk's file was left in the scratch: {left}"


# ------------------------------------------------------------------ screen_signature

def _signature_by_hand(words: array[int], width: int, crop: list[int]) -> str:
    """The `scry-sig/1` definition worked from the capture's raw ARGB words, written here
    rather than called, so the server is held to the definition and not to its own helper."""
    x0, y0, w, h = crop
    cells = b"".join(bytes(((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF))
                     for y in range(y0, y0 + h) for c in words[y * width + x0:y * width + x0 + w])
    return hashlib.blake2b(b"scry-sig/1|pixel|%dx%d|" % (w, h) + cells, digest_size=8).hexdigest()


def test_screen_signature_hashes_the_whole_screen_by_the_core_definition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    words = array("I", _capture("gridlee-screen")[:256 * 240 * 4])
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    out = s.screen_signature()
    assert out["status"] == "ok", out
    assert out["signature"] == _signature_by_hand(words, 256, [0, 0, 256, 240])
    assert (out["kind"], out["width"], out["height"], out["crop"]) == ("pixel", 256, 240,
                                                                         [0, 0, 256, 240])
    assert out["screen"] == ":screen" and out["frame_screen"] == 900
    assert out["session"]["altered"] is False and out["evaluated_by"] == "one step"
    assert "image" not in out, "a signature answers a string, never a picture"
    assert out["summary"] == f"screen_signature 256x240 at [0, 0]: {out['signature']}"
    sent = ses.stdin.getvalue().decode()
    assert "mcp_capture(" in sent and ", false)" in sent, "colours only: no pen is touched"
    _left_clean(ses)


def test_a_cropped_signature_is_the_crops_and_one_off_the_screen_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    words = array("I", _capture("gridlee-screen")[:256 * 240 * 4])
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    whole = s.screen_signature()["signature"]
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    out = s.screen_signature(crop=[16, 40, 32, 24])
    assert out["signature"] == _signature_by_hand(words, 256, [16, 40, 32, 24])
    assert out["signature"] != whole and out["crop"] == [16, 40, 32, 24]
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    out = refused("leaves the 256x240 screen", s.screen_signature(crop=[250, 0, 7, 1]))
    assert out["code"] == "bad_argument"
    _left_clean(ses)


def test_the_signature_of_the_screen_is_the_signature_of_its_picture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """One definition across tools: the PNG `screen_view` writes at scale 1 hashes, through
    `scry_core.raster`, to the string `screen_signature` answers at the same stop."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    view = s.screen_view(scale=1, crop=[8, 8, 64, 48])
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    sig = s.screen_signature(crop=[8, 8, 64, 48])
    picture = png.decode(Path(view["image"]["path"]).read_bytes())
    assert raster.picture_signature(picture) == sig["signature"]


def test_every_picture_a_view_writes_is_listed_among_the_sessions_captures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The views publish through scry-core with this server's recorder: what `captures` reads
    back. Listed once, however many times the same file is recorded."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    view = s.screen_view(scale=1)
    _serve(ses, "palette-circus")
    pal = s.palette()
    for out in (view, pal):
        assert ("image", out["image"]["path"]) in mstate.STATE.captures, out["summary"]
    mstate.STATE.record_image(Path(view["image"]["path"]))
    assert mstate.STATE.captures.count(("image", view["image"]["path"])) == 1


# ------------------------------------------------------------------ palette

def test_palette_reads_the_live_pens_as_a_table_and_a_labelled_swatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "palette-gridlee-928-32")
    out = s.palette(first=928, count=32)
    assert out["status"] == "ok", out
    assert out["palette"] == ":palette" and out["entries"] == 2048 and out["count"] == 32
    assert "tag" not in out, "the device is `palette`, as `gfx_view` names it"
    assert out["first"] == 928 and out["truncated"] is False and out["indirect_entries"] == 0
    assert len(out["colors"]) == 32 and all(re.fullmatch(r"#[0-9a-f]{6}", c)
                                            for c in out["colors"])
    assert "alpha" not in out, "every pen was opaque"
    assert out["session"]["altered"] is False and out["evaluated_by"] == "one step"
    assert out["summary"].startswith("palette :palette: pens 0x3a0..0x3bf of 2048, more after")
    pic = _png(out)
    k = out["image"]["scale"]
    label_w = mpalette.label_width(2048)
    # The first cell of the second row is pen 928 + 16, the first cell of the first pen 928.
    for pen, (col, row) in ((0, (0, 0)), (17, (1, 1)), (31, (15, 1))):
        x, y = (label_w + col * mpalette.CELL + 3) * k, (row * mpalette.CELL + 3) * k
        want = out["colors"][pen]
        assert pic.at(x, y) == tuple(int(want[i:i + 2], 16) for i in (1, 3, 5)), pen
    # THE LABEL IS THERE: ink in the label column of each row, paper beside the digits.
    for row in range(2):
        inks = {pic.at((1 + gx) * k, (row * mpalette.CELL + 1 + gy) * k)
                for gx in range(3) for gy in range(5)}
        assert (255, 255, 255) in inks, f"row {row} carries no label"


def test_palette_reads_a_whole_small_palette(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "palette-circus")
    out = s.palette()
    assert out["colors"] == ["#000000", "#ffffff"] and out["truncated"] is False
    assert out["summary"] == ("palette :palette: pens 0x0..0x1 of 2; "
                              f"{out['image']['width']}x{out['image']['height']} PNG "
                              f"x{out['image']['scale']}, inline")


def test_palette_refusals_the_machine_decides(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "palette-starfire")
    out = refused("no palette device", s.palette())
    assert out["code"] == "no_channel" and out["palettes"] == []
    _serve(ses, "palette-circus-nosuch")
    out = refused("no palette device named 'nosuch'", s.palette(palette="nosuch"))
    assert out["code"] == "unknown_ref" and out["palettes"] == [":palette"]
    _serve(ses, "palette-circus-past")
    out = refused("reaches past the last pen", s.palette(first=1, count=2))
    assert out["code"] == "bad_argument" and out["entries"] == 2
    assert out["palette"] == ":palette" and "tag" not in out, "the device under its one name"


def test_palette_with_several_devices_and_no_tag_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """AUTHORED, the one double here that is: no board in the free inventory carries two palette
    devices, and the line is the chunk's own `MAME_MCP_PAL_NONE` with two names in it."""
    ses = _channel(monkeypatch, tmp_path)
    ses.answers[1] = (b"MAME_MCP_PAL_NONE name=- palettes=:palette,:palette2\n"
                      + ses.sentinel(1))
    out = refused("2 palette devices", s.palette())
    assert "name one with `palette`" in out["message"], out["message"]
    assert out["code"] == "ambiguous_ref" and out["palettes"] == [":palette", ":palette2"]


@pytest.mark.parametrize("kwargs, said", [
    ({"count": mpalette.COUNT_MAX + 1}, "count="),
    ({"first": -1}, "first=-1"),
    ({"palette": "a b"}, "whitespace"),
    ({"scale": 99}, "scale=99"),
    ({"dest": "relative.png"}, "must be an absolute path"),
    ({"seconds": 0}, "seconds"),
])
def test_palette_arguments_are_judged_before_the_machine(kwargs: dict[str, Any],
                                                         said: str) -> None:
    out = refused(said, s.palette(**kwargs))
    assert out["code"] == "bad_argument"


# ------------------------------------------------------------------ screen_view

def test_render_of_an_indexed_screen_is_an_indexed_png_whose_index_is_the_pen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-circus", screen="circus-screen")
    out = s.screen_view(scale=1)
    assert out["status"] == "ok", out
    assert (out["width"], out["height"], out["entries"]) == (248, 256, 2)
    assert out["screen_indexed"] is True and out["palette"] == ":palette"
    assert " from indices; " in out["summary"], out["summary"]
    assert out["session"]["altered"] is False, "the pens were put back and proven"
    pic = _png(out)
    assert pic.indexed and pic.palette == [(0, 0, 0), (255, 255, 255)]
    raw = _capture("circus-screen")
    size = 248 * 256 * 4
    encoded = raw[size:2 * size]
    for x, y in ((0, 0), (90, 97), (247, 255), (100, 100)):
        at = (y * 248 + x) * 4
        assert pic.at(x, y) == int.from_bytes(encoded[at:at + 3], "little"), (x, y)
    _left_clean(ses)


def test_render_of_a_screen_with_more_pens_than_a_plte_is_rgb_of_the_same_colours(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    out = s.screen_view(scale=1)
    pic = _png(out)
    assert not pic.indexed and out["entries"] == 2048
    colours = _capture("gridlee-screen")[:256 * 240 * 4]
    for x, y in ((0, 0), (64, 50), (100, 100), (255, 239)):
        c = int.from_bytes(colours[(y * 256 + x) * 4:(y * 256 + x) * 4 + 4], "little")
        assert pic.at(x, y) == ((c >> 16) & 255, (c >> 8) & 255, c & 255), (x, y)


def test_histogram_counts_every_pixel_and_names_the_unused_pens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    out = s.screen_view(mode="histogram")
    assert sum(n for _, n in out["histogram"]) == 256 * 240
    assert out["pens_used"] == len(out["histogram"]) and "image" not in out
    used = {p for p, _ in out["histogram"]}
    assert all(944 <= p <= 959 or 929 <= p <= 943 for p in used), "two halves of one bank"
    assert out["unused"][0] == f"0x0-{min(used) - 1:#x}" and out["unused"][-1].endswith("0x7ff")
    assert out["summary"] == (f"screen_view histogram :screen frame 900: {len(used)} of 2048 "
                              "pens used")


def test_isolate_shows_the_pens_asked_for_and_where_they_are(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    out = s.screen_view(mode="isolate", pens=[929, 930, 931, 932, 933], scale=1)
    raw = _capture("gridlee-screen")
    size = 256 * 240 * 4
    idx = [int.from_bytes(raw[size + i:size + i + 3], "little") for i in range(0, size, 4)]
    hits = [(i % 256, i // 256) for i, v in enumerate(idx) if 929 <= v <= 933]
    assert out["pixels"] == len(hits) > 0
    assert out["bbox"] == [min(x for x, _ in hits), min(y for _, y in hits),
                           max(x for x, _ in hits), max(y for _, y in hits)]
    pic = _png(out)
    colours = raw[:size]

    def colour(x: int, y: int) -> tuple[int, int, int]:
        c = int.from_bytes(colours[(y * 256 + x) * 4:(y * 256 + x) * 4 + 4], "little")
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)

    x, y = hits[0]
    assert pic.at(x, y) == scry_pens.ISOLATE_COLOUR, "a selected pen in the one contrast colour"
    grey = pic.at(0, 0)
    assert isinstance(grey, tuple) and grey[0] == grey[1] == grey[2] != colour(0, 0)[0], (
        "every other pen grey")
    assert out["isolate_color"] == "#ff00ff"


def test_isolate_makes_a_dark_pen_stand_out_on_an_indexed_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """m68k-dual's title, pen 221, the dark brown of the background: dimmed, the rest of the screen
    went dark round it and the view read as the same screen darker. In the contrast colour over
    greys it stands out, and the PNG is still indexed with the pen as its index."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-m68k-dual", screen="m68k-dual-screen")
    out = s.screen_view(mode="isolate", pens=[221], scale=1)
    assert out["status"] == "ok", out
    pic = _png(out)
    raw = _capture("m68k-dual-screen")
    size = 336 * 252 * 4
    idx = bytes(raw[size + i] for i in range(0, size, 4))
    assert pic.indexed and pic.pixels == idx, "the index is still the pen"
    assert pic.palette[221] == scry_pens.ISOLATE_COLOUR
    others = [c for pen, c in enumerate(pic.palette) if pen != 221]
    assert all(r == g == b for r, g, b in others), "every other pen is a grey"
    assert all(scry_pens.GREY_LOW <= r <= scry_pens.GREY_HIGH for r, _, _ in others), (
        "no grey is black or white, so nothing competes with the contrast colour")
    assert len({r for r, _, _ in others}) > 1, "the greys keep the pens' shapes apart"


def test_pixel_names_the_pen_and_its_colour(monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    out = s.screen_view(mode="pixel", point=[100, 100])
    assert (out["pen"], out["color"]) == (956, "#446677")
    # the third answer needs a manifest and a log armed before the frame, and says so, in the
    # summary too
    assert out["set_by"]["available"] is False and "no manifest is loaded" in out["set_by"]["why"]
    assert out["summary"] == ("screen_view pixel :screen frame 900: (100, 100) is pen 0x3bc "
                              f"#446677; no logged write to it: {out['set_by']['why']}; 388x388 "
                              "PNG x8, inline")


def _screen_rgb(name: str, width: int, x: int, y: int) -> tuple[int, int, int]:
    c = int.from_bytes(_capture(name)[(y * width + x) * 4:(y * width + x) * 4 + 4], "little")
    return ((c >> 16) & 255, (c >> 8) & 255, c & 255)


@pytest.mark.parametrize("point, crop, at", [
    ([100, 100], [76, 76, 48, 48], [24, 24]),
    ([2, 3], [0, 0, 48, 48], [2, 3]),
    ([255, 239], [208, 192, 48, 48], [47, 47]),
])
def test_pixel_shows_where_the_point_is_on_a_crop_round_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, point: list[int], crop: list[int],
    at: list[int],
) -> None:
    """The numbers alone did not say where (46, 160) falls: a crop round the point, in the
    screen's colours, kept inside the screen at an edge, the point ringed white then black just
    outside it, so the point's own pixel is never covered."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    out = s.screen_view(mode="pixel", point=point, scale=4)
    assert out["status"] == "ok", out
    assert out["crop"] == crop and out["point_in_crop"] == at
    pic = _png(out)
    b = out["image"]["border"]
    assert b == len(scry_pens.POINT_RINGS)
    assert not pic.indexed and (pic.width, pic.height) == (48 * 4 + 2 * b, 48 * 4 + 2 * b)
    px, py = at
    colour = _screen_rgb("gridlee-screen", 256, *point)
    assert all(pic.at(b + px * 4 + i, b + py * 4 + j) == colour
               for i in range(4) for j in range(4)), "the point's own square is its colour, whole"
    rings = [(px * 4 - 1, py * 4, (255, 255, 255)), ((px + 1) * 4, py * 4, (255, 255, 255)),
             (px * 4 - 2, py * 4, (0, 0, 0)), ((px + 1) * 4 + 1, py * 4, (0, 0, 0))]
    for x, y, rgb in rings:
        assert pic.at(b + x, b + y) == rgb, (x, y)
    far = (0, 0) if px > 8 else (47, 47)
    assert pic.at(b + far[0] * 4, b + far[1] * 4) == _screen_rgb(
        "gridlee-screen", 256, crop[0] + far[0], crop[1] + far[1]), "the rest is the screen"
    assert pic.at(0, 0) == mpicture.BORDER_COLOUR, "the border is outside the screen"


def test_a_crop_narrows_the_picture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-circus", screen="circus-screen")
    out = s.screen_view(crop=[88, 96, 32, 8], scale=1)
    pic = _png(out)
    assert (pic.width, pic.height) == (32, 8) and out["crop"] == [88, 96, 32, 8]
    _serve(ses, "screen-circus", screen="circus-screen")
    full = _png(s.screen_view(scale=1))
    assert all(pic.at(x, y) == full.at(88 + x, 96 + y) for x in range(32) for y in range(8))


def test_a_crop_or_point_off_the_screen_is_refused_with_its_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-circus", screen="circus-screen")
    out = refused("leaves the 248x256 screen", s.screen_view(crop=[240, 0, 16, 16]))
    assert (out["width"], out["height"]) == (248, 256)
    _serve(ses, "screen-circus", screen="circus-screen")
    refused("is off the 248x256 screen", s.screen_view(mode="pixel", point=[248, 0]))
    _left_clean(ses)


def test_a_direct_colour_screen_renders_its_colours_and_refuses_the_index_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-starfire", screen="starfire-screen")
    out = s.screen_view(scale=1)
    assert out["status"] == "ok" and out["screen_indexed"] is False
    assert out["palette"]["available"] is False, out
    assert " from colours; " in out["summary"], out["summary"]
    assert not _png(out).indexed
    for mode, extra in (("histogram", {}), ("pixel", {"point": [1, 1]}),
                        ("isolate", {"pens": [1]})):
        _serve(ses, "screen-starfire", screen="starfire-screen")
        got = refused("direct colour", s.screen_view(mode=mode, **extra))
        assert got["code"] == "no_channel" and got["screen"] == ":screen"


def test_a_vector_screen_is_refused_by_every_raster_tool(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-topgunnr")
    out = refused("vector screen", s.screen_view())
    assert out["code"] == "no_channel" and out["screen_type"] == "vector"
    _serve(ses, "screen-topgunnr")
    out = refused("vector screen", s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[0, 0, 8, 8],
                                                tag="gfx1"))
    assert out["code"] == "no_channel"


def _tampered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, edit: Any) -> dict[str, Any]:
    """A REAL circus capture with one piece of its evidence altered by `edit(bytearray)`, the
    failure the check exists for injected into what the machine really wrote."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-circus", screen="circus-screen")
    path = ses.scratch / f"screen-{mstate.STATE.lua_seq + 1}.bin"
    data = bytearray(path.read_bytes())
    edit(data)
    path.write_bytes(bytes(data))
    out: dict[str, Any] = s.screen_view()
    return out


SIZE = 248 * 256 * 4


def test_a_pen_that_did_not_come_back_is_refused_and_counts_as_a_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    def edit(d: bytearray) -> None:
        d[3 * SIZE + 8 + 4] ^= 0x10         # the second pen as read back after the restore
    out = refused("did not read back", _tampered(monkeypatch, tmp_path, edit))
    assert out["code"] == "readback_refused" and out["pens_not_restored"] == [1]
    assert out["session"]["altered"] is True, "the palette is not as the game left it"


def test_a_screen_that_changed_across_the_restore_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    def edit(d: bytearray) -> None:
        d[2 * SIZE] ^= 0xFF                  # the first pixel of the screen after the restore
    out = refused("differs from the screen before", _tampered(monkeypatch, tmp_path, edit))
    assert out["session"]["altered"] is False


def test_an_index_past_the_entries_is_refused(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    def edit(d: bytearray) -> None:
        d[SIZE] = 7                          # an encoded pixel naming pen 7 of 2
    refused("past the 2 entries", _tampered(monkeypatch, tmp_path, edit))


def test_an_index_whose_pen_is_not_the_colour_shown_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    def edit(d: bytearray) -> None:
        d[SIZE] ^= 1                         # an encoded pixel naming the other pen
    refused("1 pixel mapped through the saved pens does not give the colour the screen "
            "showed", _tampered(monkeypatch, tmp_path, edit))


def test_a_short_capture_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def edit(d: bytearray) -> None:
        del d[-4:]
    refused("holds", _tampered(monkeypatch, tmp_path, edit))


@pytest.mark.parametrize("kwargs, said", [
    ({"mode": "zoom"}, "mode is one of .*; got 'zoom'"),
    ({"pens": [1]}, "`pens` goes with mode `isolate`"),
    ({"mode": "isolate"}, "`pens` goes with mode `isolate`"),
    ({"mode": "isolate", "pens": []}, "pens="),
    ({"mode": "isolate", "pens": [1] * (scry_pens.PENS_MAX + 1)}, "pens="),
    ({"mode": "pixel"}, "`point` goes with mode `pixel`"),
    ({"point": [1, 1]}, "`point` goes with mode `pixel`"),
    ({"mode": "pixel", "point": [1]}, "point="),
    ({"crop": [0, 0, 0, 8]}, "crop="),
    ({"mode": "pixel", "point": [1, 1], "crop": [0, 0, 8, 8]}, "crop="),
    ({"mode": "histogram", "scale": 2}, "answers no picture"),
    ({"mode": "histogram", "dest": "/tmp/x.png"}, "answers no picture"),
])
def test_screen_view_arguments_are_judged_before_the_machine(kwargs: dict[str, Any],
                                                             said: str) -> None:
    assert refused(said, s.screen_view(**kwargs))["code"] == "bad_argument"


# ------------------------------------------------------------------ gfx_view

def test_gfx_view_decodes_circus_chars_as_the_screen_shows_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """TWO CAPTURED SOURCES AGREE: tile 71 ('G') decoded from the gfx1 dump is the pixels the
    circus screen capture holds at (88, 96), where its videoram says 'G' is drawn."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus", block="circus-gfx1")
    out = s.gfx_view(layout=CIRCUS_CHAR, palette="palette", tag="gfx1", scale=1)
    assert out["status"] == "ok", out
    assert out["count"] == 256 == out["tiles_available"] and out["columns"] == 16
    assert out["layout"]["xoffset"] == list(range(8)) and out["layout"]["name"] == "charlayout"
    assert out["real_colors"] is True and "note" not in out
    pic = _png(out)
    assert pic.indexed and pic.palette == [(0, 0, 0), (255, 255, 255)]
    raw = _capture("circus-screen")
    tx, ty = (71 % 16) * 8, (71 // 16) * 8
    for y in range(8):
        for x in range(8):
            at = SIZE + ((96 + y) * 248 + 88 + x) * 4
            assert pic.at(tx + x, ty + y) == raw[at], (x, y)
    _left_clean(ses)


def test_gfx_view_takes_the_pens_from_the_base_it_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """gridlee's sprites through pens 928..943: the PLTE is those sixteen pens as the palette
    answer for them captured them, and the sprite spriteram places at (64, 43), image 0xbf, is
    the screen's pens there wherever it is not transparent."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-gridlee-sprites", block="gridlee-gfx1")
    out = s.gfx_view(layout=GRID_SPRITE, palette="palette", tag="gfx1", pen_base=928, count=64,
                     scale=1)
    pic = _png(out)
    assert out["pen_base"] == 928 and len(pic.palette) == 16
    pens = re.search(rb"pens=([0-9a-f,]+)", (FIX / "palette-gridlee-928-32.txt").read_bytes())
    assert pens is not None
    argb = [int(v, 16) for v in pens.group(1).split(b",")][:16]
    assert pic.palette == [((c >> 16) & 255, (c >> 8) & 255, c & 255) for c in argb]
    size = 256 * 240 * 4
    raw = _capture("gridlee-screen")
    tile = ml.decode(ml.resolve(ml.parse_layout(GRID_SPRITE, allow_name=True), 16384 * 8),
                      gzip.decompress((FIX / "gridlee-gfx1-bin.gz").read_bytes()), 0, 0xBF)
    opaque = [(x, y) for y in range(16) for x in range(8) if tile[y * 8 + x]]
    assert len(opaque) > 16
    for x, y in opaque:
        at = size + ((43 + y) * 256 + 64 + x) * 4
        assert int.from_bytes(raw[at:at + 3], "little") == 928 + tile[y * 8 + x], (x, y)


def test_gfx_view_resolves_rgn_frac_against_the_whole_region(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-witchgme", block="witchgme-gfx2")
    out = s.gfx_view(layout=WITCH_TILE, palette="palette", tag="gfx2", count=256, scale=1)
    assert out["layout"]["planeoffset"] == [0, 0x1000 * 8, 0x2000 * 8] and out["size"] == 0x3000
    assert out["tiles_available"] == 512
    pic = _png(out)
    block = gzip.decompress((FIX / "witchgme-gfx2-bin.gz").read_bytes())
    # The pixel value, from the three planes by hand: plane 0 (0x0000) is the top bit.
    for t, x, y in ((0, 0, 0), (37, 3, 5), (255, 7, 7)):
        bits = [(block[p + t * 8 + y] >> (7 - x)) & 1 for p in (0, 0x1000, 0x2000)]
        want = bits[0] << 2 | bits[1] << 1 | bits[2]
        assert pic.at((t % 16) * 8 + x, (t // 16) * 8 + y) == want, (t, x, y)


def test_gfx_view_through_a_cpu_space_range(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-gridlee-ref", block="gridlee-space-1000")
    out = s.gfx_view(layout=GRID_FB, palette="palette", ref="0x1000", count=32, pen_base=944)
    assert out["status"] == "ok", out
    assert out["kind"] == "space" and out["addr"] == "0x00001000" and out["count"] == 32
    assert (out["bytewidth"], out["endianness"]) == (1, "big"), "the 6809's space, as it said"
    assert "addr_cpu" in out
    # The span is tile 0 at the address to the end of tile 31: 32 lines of 128 bytes, less the
    # last line's unread tail (the tile is 4 bytes wide).
    assert f", {0x1000}, {31 * 4 + 7 * 128 + 4})" in ses.stdin.getvalue().decode()


def test_gfx_view_palette_none_is_a_grey_ramp_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus", block="circus-gfx1")
    out = s.gfx_view(layout=CIRCUS_CHAR, palette="none", tag="gfx1", count=16)
    assert out["real_colors"] is False and "NOT the machine's colours" in out["note"]
    assert _png(out).palette == [(0, 0, 0), (255, 255, 255)]
    assert "mcp_pens" not in ses.stdin.getvalue().decode(), "no pens are read for `none`"


def test_gfx_view_refusals_the_machine_decides(monkeypatch: pytest.MonkeyPatch,
                                               tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus-nosuch-tag")
    out = refused("no share or region named 'nosuch'", s.gfx_view(
        layout=CIRCUS_CHAR, palette="palette", tag="nosuch"))
    assert out["code"] == "unknown_ref" and ":gfx1" in out["tags"]
    _serve(ses, "gfx-circus-nosuch-palette", block="circus-gfx1")
    out = refused("no palette device named 'nosuch'", s.gfx_view(
        layout=CIRCUS_CHAR, palette="nosuch", tag="gfx1"))
    assert out["code"] == "unknown_ref"
    _serve(ses, "gfx-circus-short", block="circus-gfx1")
    out = refused("smaller than the depth needs", s.gfx_view(
        layout=CIRCUS_CHAR, palette="palette", tag="gfx1", pen_base=1))
    assert out["entries"] == 2
    _serve(ses, "gfx-circus", block="circus-gfx1")
    out = refused("not all inside region :gfx1", s.gfx_view(
        layout=CIRCUS_CHAR, palette="palette", tag="gfx1", first=200, count=100))
    assert out["size"] == 0x800 and out["tiles_available"] == 256
    _left_clean(ses)


@pytest.mark.parametrize("kwargs, said", [
    ({"layout": {**CIRCUS_CHAR, "total": 1}}, "`total` is `first`"),
    ({"palette": "a b"}, "no palette is invented"),
    ({"tag": "", "ref": ""}, "one source per call"),
    ({"ref": "0x1000"}, "one source per call"),
    ({"tag": "", "ref": "0x1000", "layout": WITCH_TILE}, "RGN_FRAC"),
    ({"count": gfx.VIEW_TILES_MAX + 1}, "count="),
    ({"columns": 0}, "columns=0"),
    ({"pen_base": -1}, "pen_base=-1"),
    ({"palette": "none", "pen_base": 4}, "with palette `none`"),
    ({"scale": -1}, "scale=-1"),
])
def test_gfx_view_arguments_are_judged_before_the_machine(kwargs: dict[str, Any],
                                                          said: str) -> None:
    call: dict[str, Any] = {"layout": CIRCUS_CHAR, "palette": "palette", "tag": "gfx1", **kwargs}
    assert refused(said, s.gfx_view(**call))["code"] == "bad_argument"


def test_gfx_view_with_a_ref_names_its_count(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    _channel(monkeypatch, tmp_path)
    refused("name `count`", s.gfx_view(layout=GRID_FB, palette="palette", ref="0x1000"))


# ------------------------------------------------------------------ gfx_locate

def test_locate_finds_the_char_videoram_says_is_there(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], tag="gfx1", flips=["none"])
    assert out["status"] == "ok", out
    assert out["matched"] and out["matches_total"] == 1 and out["ambiguous"] is False
    m = out["matches"][0]
    assert (m["tile"], m["flip"], m["base"], m["window"]) == (0x47, "none", 0, [88, 96])
    assert m["byte"] == 0x47 * 8 and m["compared"] == 64 and m["ambiguous"] is False
    assert out["flips"] == ["none"] and out["session"]["altered"] is False
    assert out["summary"] == ("gfx_locate region :gfx1 for patch [88, 96, 8, 8]: 1 match, "
                              "first charlayout tile 71 flip none base 0x0")
    _left_clean(ses)


def test_a_shifted_patch_does_not_match_and_the_nearest_is_called_what_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-shifted", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[89, 96, 8, 8], tag="gfx1", flips=["none"])
    assert out["matched"] is False and out["matches"] == []
    near = out["nearest"]
    assert near["is_a_match"] is False and 0 < near["disagree"] < near["of"] == 64
    assert len(near["pixels"]) == min(near["disagree"], mlocate.DISAGREE_SHOWN)


def test_every_window_of_a_patch_is_tried_and_ambiguity_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[80, 92, 48, 16], tag="gfx1")
    found = {(m["window"][0], m["window"][1], m["tile"]) for m in out["matches"]
             if m["flip"] == "none"}
    assert {(88, 96, 71), (96, 96, 65), (104, 96, 77), (112, 96, 69)} <= found, "GAME"
    row = out["candidates"][0]
    assert row["windows"] + row["windows_uniform"] + row["windows_mixed_bank"] == 41 * 9
    assert out["ambiguous"] is True and out["ambiguous_windows"] >= 1
    assert any(m["ambiguous"] for m in out["matches"])
    assert all(not m["ambiguous"] for m in out["matches"] if m["window"] == [88, 96]), (
        "the G's window matched the G alone")


def test_locate_on_a_4bit_framebuffer_in_a_share(monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    """gridlee's framebuffer, 128 bytes a line: from `offset` 16 lines in, tile `t` is line
    16 + t // 32 at column (t % 32) * 8, which is where the patch is."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-gridlee-fb", screen="gridlee-screen", block="gridlee-videoram")
    out = s.gfx_locate(layouts=[GRID_FB], patch=[96, 96, 8, 8], tag="videoram",
                       offset=16 * 128, flips=["none"])
    m = out["matches"][0]
    assert out["matches_total"] == 1 and m["tile"] == (96 - 16) * 32 + 96 // 8
    assert m["base"] == 944 and m["compared"] == 64
    _serve(ses, "locate-gridlee-fb-shifted", screen="gridlee-screen", block="gridlee-videoram")
    out = s.gfx_locate(layouts=[GRID_FB], patch=[99, 96, 8, 8], tag="videoram",
                       offset=16 * 128)
    assert not out["matched"] and out["nearest"]["disagree"] > 0


def test_locate_with_transparency_finds_the_sprite_spriteram_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """spriteram's first sprite is image 0xbf at x 0x40, y 0x1a + 17 on the bitmap, which is
    visible row 43; opaque, the window spans two banks (sprite and background), so no single
    bank reads it and the pen map does, the background's pen standing for 0: it finds 0xbf, and
    beside it a tile whose pens part the window the same way, so the window is ambiguous."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-gridlee-sprite", screen="gridlee-screen", block="gridlee-gfx1")
    out = s.gfx_locate(layouts=[GRID_SPRITE], patch=[64, 43, 8, 16], tag="gfx1", transparent=0)
    assert out["matches_total"] == 1 and out["ambiguous"] is False
    m = out["matches"][0]
    assert (m["tile"], m["base"], m["flip"]) == (0xBF, 928, "none")
    assert 0 < m["compared"] < 128 and out["transparent"] == 0
    _serve(ses, "locate-gridlee-sprite", screen="gridlee-screen", block="gridlee-gfx1")
    out = s.gfx_locate(layouts=[GRID_SPRITE], patch=[64, 43, 8, 16], tag="gfx1")
    assert out["candidates"][0]["windows_mixed_bank"] == 1 and out["pen_map"]["tried"] is True
    assert 0xBF in {m["tile"] for m in out["matches"]} and out["ambiguous"] is True, out
    assert all(m["base"]["available"] is False and m["pen_map"] for m in out["matches"])


def test_locate_through_a_cpu_space_range(monkeypatch: pytest.MonkeyPatch,
                                          tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-gridlee-ref", screen="gridlee-screen", block="gridlee-space-800")
    out = s.gfx_locate(layouts=[GRID_FB], patch=[96, 96, 8, 8], ref="0x800", count=7680,
                       flips=["none"])
    assert out["kind"] == "space" and out["addr"] == "0x00000800"
    assert out["addr_cpu"] == ":maincpu", "the cpu whose space the range is"
    assert out["matches"][0]["tile"] == 96 * 32 + 12


def test_locate_refuses_work_past_its_bound(monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = refused("one call gathers and compares", s.gfx_locate(
        layouts=[CIRCUS_CHAR], patch=[0, 0, 248, 256], tag="gfx1"))
    assert out["code"] == "bad_argument"
    _left_clean(ses)


def test_locate_bounds_the_pixels_it_gathers_into_windows_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """One tile and one flip against the whole screen compares little and GATHERS a great deal:
    every window's pens. Both are held to the bound."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mlocate, "WORK_MAX", 1 << 20)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    refused("one call gathers and compares", s.gfx_locate(
        layouts=[CIRCUS_CHAR], patch=[0, 0, 248, 256], tag="gfx1", count=1, flips=["none"]))


def test_the_work_bound_is_the_calls_not_each_candidates(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    """Two candidates, each exactly at the bound: the call spends twice it, and is refused."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    one = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[80, 92, 48, 16], tag="gfx1")
    n = one["candidates"][0]["tiles_searched"][1]
    monkeypatch.setattr(mlocate, "WORK_MAX", mlocate._work(41 * 9, n, 4, 64, False))
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    assert s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[80, 92, 48, 16],
                        tag="gfx1")["status"] == "ok", "one candidate at the bound is inside it"
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    refused("one call gathers and compares", s.gfx_locate(
        layouts=[CIRCUS_CHAR, dict(CIRCUS_CHAR, name="again")], patch=[80, 92, 48, 16],
        tag="gfx1"))
    _left_clean(ses)


def test_the_matches_one_call_holds_are_bounded(monkeypatch: pytest.MonkeyPatch,
                                                tmp_path: Path) -> None:
    """A pattern repeated across the screen and the block matches every window with many tiles:
    past the bound the call is refused, never an answer that grew without one."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    whole = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[80, 92, 48, 16], tag="gfx1")
    assert whole["matches_total"] > 3
    monkeypatch.setattr(mlocate, "MATCHES_MAX", whole["matches_total"] - 1, raising=False)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = refused("matches", s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[80, 92, 48, 16],
                                          tag="gfx1"))
    assert out["code"] == "bad_argument"
    _left_clean(ses)


def test_a_windows_shape_is_measured_once_however_many_tiles_it_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    calls: list[int] = []
    real = mlocate._shape
    def counted(*a: Any) -> list[int]:
        calls.append(1)
        return real(*a)

    monkeypatch.setattr(mlocate, "_shape", counted)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[80, 92, 48, 16], tag="gfx1")
    windows = {tuple(m["window"]) for m in out["matches"]}
    assert out["matches_total"] == len(out["matches"]) > len(windows), "a window matched twice"
    assert len(calls) == len(windows)


def test_locate_refuses_a_patch_off_the_screen(monkeypatch: pytest.MonkeyPatch,
                                               tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    refused("leaves the 248x256 screen", s.gfx_locate(layouts=[CIRCUS_CHAR],
                                                      patch=[244, 0, 8, 8], tag="gfx1"))
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    refused("holds no whole tile", s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[0, 0, 4, 4],
                                                tag="gfx1"))


@pytest.mark.parametrize("kwargs, said", [
    ({"layouts": []}, "1..8 candidate"),
    ({"layouts": [CIRCUS_CHAR, CIRCUS_CHAR]}, "share a name"),
    ({"patch": [0, 0, 8]}, "patch="),
    ({"patch": [0, 0, 0, 8]}, "patch="),
    ({"flips": ["none", "none"]}, "flips="),
    ({"flips": ["z"]}, "flips="),
    ({"flips": []}, "flips="),
    ({"transparent": -1}, "transparent=-1"),
    ({"tag": "", "ref": "0x800"}, "name `count`"),
    ({"tag": "", "ref": "0x800", "count": 4, "layouts": [WITCH_TILE]}, "RGN_FRAC"),
    ({"count": mlocate.SEARCH_TILES_MAX + 1}, "count="),
])
def test_gfx_locate_arguments_are_judged_before_the_machine(kwargs: dict[str, Any],
                                                            said: str) -> None:
    call: dict[str, Any] = {"layouts": [CIRCUS_CHAR], "patch": [0, 0, 8, 8], "tag": "gfx1",
                            **kwargs}
    assert refused(said, s.gfx_locate(**call))["code"] == "bad_argument"


# ------------------------------------------------------------------ the picture at the boundary

def test_a_graphics_reply_reaches_the_client_with_its_picture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THROUGH THE MCP BOUNDARY, as a client receives it: the JSON first, then the PNG, which is
    the file `image` names, byte for byte."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "palette-circus")
    got = asyncio.run(s.mcp.call_tool("palette", {}))
    assert isinstance(got, CallToolResult)
    assert [c.type for c in got.content] == ["text", "image"]
    body = got.structured_content
    assert body is not None and body["status"] == "ok"
    data = base64.b64decode(got.content[1].data)  # type: ignore[union-attr]
    assert hashlib.sha256(data).hexdigest() == body["image"]["sha256"]
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    got = asyncio.run(s.mcp.call_tool("screen_view", {"mode": "histogram"}))
    assert [c.type for c in got.content] == ["text"], "a mode with no picture attaches none"


# ------------------------------------------------------------------ the paths no free board takes
#
# AUTHORED, every answer line in this section, and each is the chunk's own format: no board in
# the free inventory has two screens or none, a palette with shadows, one past 24 bits of pens,
# a block past the dump's ceiling, or a big-endian region of words. The bytes, where there are
# any, are still a real capture's.

def _answer(ses: _ChannelSession, line: bytes) -> None:
    seq = mstate.STATE.lua_seq + 1
    ses.answers[seq] = line + b"\n" + ses.sentinel(seq)


@pytest.mark.parametrize("line, code, said", [
    (b"MAME_MCP_SCREEN_COUNT screens=", "no_channel", "has no screen"),
    (b"MAME_MCP_SCREEN_COUNT screens=:lscreen,:rscreen", "ambiguous_ref", "2 screens"),
    (b"MAME_MCP_SCREEN_SHADOWS tag=:screen w=8 h=8 frame=1 palette=:palette", "no_channel",
     "shadows or highlights"),
    (b"MAME_MCP_SCREEN_TOO_MANY tag=:screen w=8 h=8 frame=1 entries=16777217", "no_channel",
     "past the 16777216"),
    (b"nothing a screen chunk prints", "unexpected_answer", "printed no screen line"),
])
def test_the_capture_refuses_in_its_own_words(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                              line: bytes, code: str, said: str) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _answer(ses, line)
    out = refused(said, s.screen_view())
    assert out["code"] == code and out["session"]["altered"] is False
    _left_clean(ses)


@pytest.mark.parametrize("line, code, said", [
    (b"MAME_MCP_GFX_BLOCK_BIG kind=region tag=:gfx1 size=134217728", "bad_argument",
     "read whole into a file"),
    (b"nothing a dump prints", "unexpected_answer", "printed no dump line"),
])
def test_the_dump_refuses_in_its_own_words(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                           line: bytes, code: str, said: str) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _answer(ses, line)
    out = refused(said, s.gfx_view(layout=CIRCUS_CHAR, palette="none", tag="gfx1"))
    assert out["code"] == code
    _left_clean(ses)


def test_a_dump_shorter_than_announced_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus", block="circus-gfx1")
    path = ses.scratch / f"block-{mstate.STATE.lua_seq + 1}.bin"
    path.write_bytes(path.read_bytes()[:-1])
    refused("holds 2047 bytes and the console said 2048",
            s.gfx_view(layout=CIRCUS_CHAR, palette="palette", tag="gfx1"))
    _left_clean(ses)


def test_a_big_endian_word_region_decodes_as_its_bytes_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """End to end through the dump: gridlee's gfx1 as a host would copy it out of a 16-bit
    region of the other byte order (each word's bytes swapped) decodes to the same sheet as the
    real byte region, because the words are put back in the block's own order first."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-gridlee-sprites", block="gridlee-gfx1")
    straight = _png(s.gfx_view(layout=GRID_SPRITE, palette="none", tag="gfx1", count=64,
                               scale=1))
    real = gzip.decompress((FIX / "gridlee-gfx1-bin.gz").read_bytes())
    swapped = b"".join(real[i:i + 2][::-1] for i in range(0, len(real), 2))
    other = "big" if sys.byteorder == "little" else "little"
    seq = mstate.STATE.lua_seq + 1
    ses.answers[seq] = (f"MAME_MCP_GFX_BLOCK kind=region tag=:gfx1 size={len(real)} "
                        f"bytewidth=2 endian={other}\n").encode() + ses.sentinel(seq)
    (ses.scratch / f"block-{seq}.bin").write_bytes(swapped)
    out = s.gfx_view(layout=GRID_SPRITE, palette="none", tag="gfx1", count=64, scale=1)
    assert (out["bytewidth"], out["endianness"]) == (2, other)
    assert _png(out).pixels == straight.pixels


def test_a_sheet_past_the_pixels_one_call_decodes_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(gfx, "TILE_PIXELS_MAX", 64 * 3)
    _serve(ses, "gfx-circus", block="circus-gfx1")
    refused("past the 192 one call decodes",
            s.gfx_view(layout=CIRCUS_CHAR, palette="palette", tag="gfx1", count=4))


def test_a_ref_with_no_count_is_refused_before_a_batch_could_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In the check itself, which `perform` asks for every step before running any: judged only
    in the body, a batch would run its earlier steps and then refuse this one."""
    with pytest.raises(mstate.Invalid, match="name `count`"):
        gfx.check_gfx_view(layout=GRID_FB, palette="none", ref="0x1000")


def test_several_candidates_are_each_searched_and_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two different candidates: circus's chars, and a 16x16 layout the 8x8 patch holds no
    window of. The first finds the G, the second reports it had nothing to compare."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    big = {"name": "sixteen", "width": 16, "height": 16, "planes": 1, "planeoffset": [0],
           "xoffset": "{ STEP16(0,1) }", "yoffset": "{ STEP16(0,16) }", "charincrement": 256}
    out = s.gfx_locate(layouts=[CIRCUS_CHAR, big], patch=[88, 96, 8, 8], tag="gfx1",
                       flips=["none"])
    rows = {r["layout"]["name"]: r for r in out["candidates"]}
    assert set(rows) == {"charlayout", "sixteen"}
    assert rows["charlayout"]["matches"] == 1 and rows["sixteen"]["windows"] == 0
    assert [(m["layout"], m["tile"]) for m in out["matches"]] == [("charlayout", 0x47)]
    assert out["ambiguous"] is False


def test_the_nearest_says_when_its_budget_cut_the_search_short(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-shifted", screen="circus-screen", block="circus-gfx1")
    whole = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[89, 96, 8, 8], tag="gfx1",
                         flips=["none"])
    assert whole["nearest"]["complete"] is True
    monkeypatch.setattr(mlocate, "NEAREST_WORK_MAX", 100)
    _serve(ses, "locate-circus-shifted", screen="circus-screen", block="circus-gfx1")
    cut = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[89, 96, 8, 8], tag="gfx1", flips=["none"])
    assert cut["nearest"]["complete"] is False and cut["nearest"]["layout"] == "charlayout"
    assert cut["nearest"]["disagree"] >= whole["nearest"]["disagree"]


def test_a_nearest_under_a_flip_names_the_pixels_where_they_are_on_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The comparison is made in the flipped window's frame, and every disagreement is reported
    at its place on the screen: its pen there is the screen's."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-shifted", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[89, 96, 8, 8], tag="gfx1",
                       flips=["xy"])
    raw = _capture("circus-screen")
    near = out["nearest"]
    tile = ml.decode(ml.resolve(ml.parse_layout(CIRCUS_CHAR, allow_name=True), 2048 * 8),
                     gzip.decompress((FIX / "circus-gfx1-bin.gz").read_bytes()), 0, near["tile"])
    drawn = mlocate._flipped(tile, 8, 8, "xy")      # the tile as it would sit on the screen
    assert near["pixels"], "a nearest that disagrees nowhere is a match"
    for x, y, pen, value in near["pixels"]:
        at = SIZE + (y * 248 + x) * 4
        assert 89 <= x < 97 and 96 <= y < 104 and int.from_bytes(raw[at:at + 3], "little") == pen
        assert drawn[(y - 96) * 8 + (x - 89)] == value != pen, (x, y, pen, value)


def test_an_unnamed_candidate_that_collides_with_a_named_one_is_refused_saying_why() -> None:
    named = {**CIRCUS_CHAR, "name": "layout1"}
    out = refused("an unnamed one is called", s.gfx_locate(
        layouts=[named, {k: v for k, v in CIRCUS_CHAR.items() if k != "name"}],
        patch=[0, 0, 8, 8], tag="gfx1"))
    assert out["code"] == "bad_argument"


# ------------------------------------------------------------------ bounds, orders and leftovers

def test_a_layout_that_resolves_below_zero_through_a_ref_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A range of a cpu's space is resolved before the machine is asked how long a span to
    read: a layout that does not resolve is the reply contract's refusal, not an exception."""
    _channel(monkeypatch, tmp_path)
    backwards = {**GRID_FB, "xoffset": "{ STEP8(0,-4) }"}
    out = refused("resolves below zero", s.gfx_view(layout=backwards, palette="none",
                                                    ref="0x1000", count=1))
    assert out["code"] == "bad_argument"


def test_count_zero_searches_at_most_the_tiles_one_call_searches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`count=0` takes every tile the block holds, AT MOST `SEARCH_TILES_MAX`, as `gfx_view`
    caps at its own; the row says how many were searched beside how many there are."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mlocate, "SEARCH_TILES_MAX", 100)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], tag="gfx1", flips=["none"])
    assert out["status"] == "ok", out
    row = out["candidates"][0]
    assert row["tiles_searched"] == [0, 100] and row["tiles_available"] == 256
    assert [m["tile"] for m in out["matches"]] == [0x47]


def test_the_transparent_search_is_charged_for_every_pixel_it_compares(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With `transparent` every window is compared with every tile pixel by pixel, so the bound
    counts windows x flips x tiles x pixels: one 8x16 window against gridlee's 256 sprites under
    four flips is far more than the windows x tiles x flips the opaque path's table costs."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mlocate, "WORK_MAX", 5000)
    _serve(ses, "locate-gridlee-sprite", screen="gridlee-screen", block="gridlee-gfx1")
    out = refused("one call gathers and compares", s.gfx_locate(
        layouts=[GRID_SPRITE], patch=[64, 43, 8, 16], tag="gfx1", transparent=0))
    assert out["code"] == "bad_argument"
    _left_clean(ses)
    # one operation short of the pixel-by-pixel cost, far above the opaque path's cost
    cost = mlocate._work(1, 256, 4, 8 * 16, True)
    assert cost > 2 * mlocate._work(1, 256, 4, 8 * 16, False)
    for bound, ok in ((cost - 1, False), (cost, True)):
        monkeypatch.setattr(mlocate, "WORK_MAX", bound)
        _serve(ses, "locate-gridlee-sprite", screen="gridlee-screen", block="gridlee-gfx1")
        got = s.gfx_locate(layouts=[GRID_SPRITE], patch=[64, 43, 8, 16], tag="gfx1",
                           transparent=0)
        assert (got["status"] == "ok") is ok, (bound, got.get("message"))


def test_the_nearest_across_sizes_is_the_smaller_share_of_its_pixels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """On circus's screen at (176, 32) no tile matches: the 8x8 chars come nearest at one pixel
    of 64, a 16x16 layout at three of 256. Three of 256 is the nearer, whatever the count."""
    ses = _channel(monkeypatch, tmp_path)
    big = {"name": "sixteen", "width": 16, "height": 16, "planes": 1, "planeoffset": [0],
           "xoffset": "{ STEP16(0,1) }", "yoffset": "{ STEP16(0,16) }", "charincrement": 256}
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR, big], patch=[176, 32, 16, 16], tag="gfx1",
                       flips=["none"])
    assert out["status"] == "ok" and out["matched"] is False, out
    near = out["nearest"]
    assert (near["layout"], near["disagree"], near["of"]) == ("sixteen", 3, 256), near


def test_a_search_the_budget_just_covered_is_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`complete` says whether a comparison was left undone, not whether budget is left: a
    budget that runs out on the very last comparison looked at everything."""
    ses = _channel(monkeypatch, tmp_path)
    spent: list[mlocate.Budget] = []
    real = mlocate._nearest

    def measure(*args: Any) -> Any:
        got = real(*args)
        spent.append(args[-1])
        return got

    monkeypatch.setattr(mlocate, "_nearest", measure)
    _serve(ses, "locate-circus-shifted", screen="circus-screen", block="circus-gfx1")
    whole = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[89, 96, 8, 8], tag="gfx1",
                         flips=["none"])
    assert whole["nearest"]["complete"] is True
    used = mlocate.NEAREST_WORK_MAX - spent[0].left
    monkeypatch.setattr(mlocate, "NEAREST_WORK_MAX", used)
    _serve(ses, "locate-circus-shifted", screen="circus-screen", block="circus-gfx1")
    exact = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[89, 96, 8, 8], tag="gfx1",
                         flips=["none"])
    assert exact["nearest"] == whole["nearest"], "the same search, to its last comparison"


@pytest.mark.parametrize("transparent, said", [(1.5, "transparent is an integer or a `0x` hex "
                                                     "string; got 1.5"),
                                               (2, "transparent=2"),
                                               (True, "transparent is an integer or a `0x` hex "
                                                      "string; got True")])
def test_transparent_is_a_pixel_value_the_layout_can_hold(transparent: Any, said: str) -> None:
    out = refused(said, s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[0, 0, 8, 8], tag="gfx1",
                                     transparent=transparent))
    assert out["code"] == "bad_argument"


def test_a_bad_palette_is_named_before_the_tile_range(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus-nosuch-palette", block="circus-gfx1")
    out = refused("no palette device named 'nosuch'", s.gfx_view(
        layout=CIRCUS_CHAR, palette="nosuch", tag="gfx1", first=200, count=100))
    assert out["code"] == "unknown_ref"
    _left_clean(ses)


@pytest.mark.parametrize("tool", ["gfx_view", "screen_view"])
def test_a_chunk_that_fails_in_any_way_leaves_no_file_behind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool: str,
) -> None:
    """The dump or the capture the chunk wrote is removed whatever went wrong after it, not only
    on a refusal: nothing else ever removes a block of up to `BLOCK_BYTES_MAX` bytes."""
    from scry_mame import chunk as mame_chunk

    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus", block="circus-gfx1", screen="circus-screen")

    def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("the channel went away")

    monkeypatch.setattr(mame_chunk, "run", broken)
    live = cast(Any, ses)              # the channel double stands in for the session
    with pytest.raises(RuntimeError):
        if tool == "gfx_view":
            gfx.gfx_view(live, ses.scratch, CIRCUS_CHAR, "none", "gfx1", "", 0, 0, 16, 16, 0, 0,
                         "", "", 5.0)
        else:
            mscreen.capture(live, ses.scratch, True, 5.0, mprogress.no_progress)
    prefix = "block" if tool == "gfx_view" else "screen"
    assert not list(ses.scratch.glob(f"{prefix}-*.bin")), "the chunk's own file was left"


def test_palette_says_truncated_only_when_the_cap_cut_a_read_to_the_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`truncated` is "cut" on every tool here: a `count` the caller chose cut nothing, however
    many pens come after it, which the summary still says."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "palette-gridlee-928-32")
    out = s.palette(first=928, count=32)
    assert out["truncated"] is False, out
    assert out["summary"].startswith("palette :palette: pens 0x3a0..0x3bf of 2048, more after")


def test_a_refused_capture_runs_nothing_after_it(monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    """The pixel question's log dump runs only when the capture answered: a capture that
    refused (it returns nil) leaves nothing done behind it."""
    ses = _channel(monkeypatch, tmp_path)
    _answer(ses, b"MAME_MCP_SCREEN_COUNT screens=:lscreen,:rscreen")
    refused("2 screens", s.screen_view(mode="pixel", point=[0, 0]))
    chunk = ses.stdin.getvalue().decode().splitlines()[-1]
    call = chunk.index("mcp_capture(")
    assert re.search(r"if mcp_capture\([^)]*\) then\\n.*R\.dump_all\(\).*\\nend", chunk), (
        chunk[call - 20:])


@pytest.mark.parametrize("point", [[0, 0], [255, 239], [0, 239], [100, 100]])
def test_the_rings_round_a_point_are_whole_even_at_the_screens_edge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, point: list[int],
) -> None:
    """At a corner the point sits on the crop's edge, because the screen ends there, so the
    rings need room outside the screen: all four sides of both rings are in the picture."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    out = s.screen_view(mode="pixel", point=point, scale=4)
    assert out["status"] == "ok", out
    pic = _png(out)
    border = out["image"].get("border", 0)
    px, py = (border + v * 4 for v in out["point_in_crop"])
    for gap, rgb in enumerate(scry_pens.POINT_RINGS, 1):
        sides = [(px - gap, py), (px + 3 + gap, py), (px, py - gap), (px, py + 3 + gap)]
        for x, y in sides:
            assert 0 <= x < pic.width and 0 <= y < pic.height, ("off the picture", x, y)
            assert pic.at(x, y) == rgb, (gap, x, y)


# ------------------------------------------------------------------ gfx_locate's pen map

HARDHAT_TEXT = [0x11, 0x0A, 0x1B, 0x0D, 0x11, 0x0A, 0x1D]      # videoram row 3, "HARDHAT"


def _hardhat(ses: _ChannelSession, patch: list[int]) -> dict[str, Any]:
    _serve(ses, "locate-hardhat", screen="hardhat-screen", block="hardhat-characterram")
    out: dict[str, Any] = s.gfx_locate(layouts=[BYTES_8X8], patch=patch, tag="characterram",
                                       count=256, flips=["none"])
    return out


def test_a_char_whose_ink_and_paper_sit_in_two_banks_is_found_through_a_pen_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """No window is one bank's (pen 0 and pen 5 of a 1-bit layout), so the single-bank search
    tries none; the pen map then finds each letter at its place in the row, as the board's
    `videoram` names it, each with the table that read it."""
    ses = _channel(monkeypatch, tmp_path)
    out = _hardhat(ses, [48, 24, 64, 8])
    assert out["status"] == "ok", out
    found = sorted((m["window"][0], m["tile"]) for m in out["matches"])
    assert found == [(48 + 8 * i, code) for i, code in enumerate(HARDHAT_TEXT)], found
    assert all(m["pen_map"] == [[0, 0], [5, 1]] and m["base"]["available"] is False
               for m in out["matches"])
    assert all((m["window"][1], m["flip"], m["compared"]) == (24, "none", 64)
               for m in out["matches"])
    assert "evaluated_by" in out and out["cause"] == f"gfx_locate: {out['evaluated_by']}"
    assert out["pen_map"] == {"tried": True, "matches": len(HARDHAT_TEXT)}, out["pen_map"]
    assert out["candidates"][0]["windows_mixed_bank"] > 0 and "nearest" not in out
    _left_clean(ses)


def test_the_same_patch_a_pixel_lower_matches_nothing_even_through_a_pen_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control: no row of the patch starts a char row, so no window is any tile, however
    its pens are read."""
    ses = _channel(monkeypatch, tmp_path)
    out = _hardhat(ses, [48, 25, 64, 8])
    assert out["status"] == "ok", out
    assert out["matched"] is False and out["pen_map"] == {"tried": True, "matches": 0}, out
    assert out["nearest"]["available"] is False and "pen map" in out["note"], out


def test_a_match_in_one_bank_never_asks_the_pen_map(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], tag="gfx1", flips=["none"])
    assert out["matches"][0]["base"] == 0 and "pen_map" not in out["matches"][0]
    assert out["pen_map"]["available"] is False, "the single-bank search matched"


def test_a_pen_map_reads_each_pen_as_one_value_and_never_the_reverse() -> None:
    """A table from each pen of the window to the value it stands for: a pen standing for two
    values is no table, while two pens for one value is a board's colour attribute."""
    tile = [0, 1, 1, 0]
    assert mlocate._pen_map_match(tile, [9, 4, 5, 9], None, 1) == ({4: 1, 5: 1, 9: 0}, 4)
    assert mlocate._pen_map_match(tile, [9, 4, 4, 4], None, 1) is None, "pen 4 is 1 and 0"
    assert mlocate._pen_map_match([1, 1, 1, 1], [9, 4, 5, 9], None, 1) is None, "a blank tile"


def test_a_transparent_one_bit_tile_is_proved_by_its_inks_place_alone() -> None:
    """One value compared proves a shape only if the ink's pen is nowhere else in the window:
    the left-out pixels may hold any pen but that one."""
    tile = [0, 1, 1, 0]
    assert mlocate._pen_map_match(tile, [7, 3, 3, 9], 0, 1) == ({3: 1}, 2)
    assert mlocate._pen_map_match(tile, [3, 3, 3, 9], 0, 1) is None, "ink where the tile has none"
    assert mlocate._pen_map_match(tile, [7, 3, 2, 9], 0, 1) == ({3: 1, 2: 1}, 2)
    two = [0, 1, 2, 0]
    assert mlocate._pen_map_match(two, [3, 5, 6, 5], 0, 2) == ({5: 1, 6: 2}, 2), (
        "deeper tiles keep the two-values rule, and their left-out pixels are free")
    assert mlocate._pen_map_match([0, 1, 1, 0], [7, 5, 6, 5], 0, 2) is None, "one value, 2 bits"


def test_a_pen_map_past_the_work_bound_is_not_tried_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The bound counts both passes: with room for the single-bank one and not for the pen map,
    the call answers what the first found and says the second was not tried, and why."""
    ses = _channel(monkeypatch, tmp_path)
    wins, n, pixels = (64 - 8 + 1) * (8 - 8 + 1), 256, 64
    monkeypatch.setattr(mlocate, "WORK_MAX", mlocate._work(wins, n, 1, pixels, False))
    out = _hardhat(ses, [48, 24, 64, 8])
    assert out["status"] == "ok" and out["matched"] is False, out
    assert out["pen_map"]["tried"] is False and "narrow" in out["pen_map"]["why"], out["pen_map"]
    assert all("pen_map_matches" not in row for row in out["candidates"])
    assert "pen map" not in out["note"]


def test_each_candidates_row_counts_its_own_pen_map_matches(monkeypatch: pytest.MonkeyPatch,
                                                            tmp_path: Path) -> None:
    """Two candidates of one layout each read the whole text: each row counts its own seven, the
    reply all fourteen, and every window is then ambiguous between them."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-hardhat", screen="hardhat-screen", block="hardhat-characterram")
    out = s.gfx_locate(layouts=[BYTES_8X8, dict(BYTES_8X8, name="again")],
                       patch=[48, 24, 64, 8], tag="characterram", count=256, flips=["none"])
    assert [row["pen_map_matches"] for row in out["candidates"]] == [7, 7], out["candidates"]
    assert out["pen_map"] == {"tried": True, "matches": 14} and out["ambiguous_windows"] == 7


def test_the_pen_map_is_tried_with_the_bound_exactly_spent(monkeypatch: pytest.MonkeyPatch,
                                                           tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    wins, n, pixels = 57, 256, 64
    monkeypatch.setattr(mlocate, "WORK_MAX", mlocate._work(wins, n, 1, pixels, False)
                        + mlocate._work(wins, n, 1, pixels, True))
    out = _hardhat(ses, [48, 24, 64, 8])
    assert out["pen_map"] == {"tried": True, "matches": 7}, out["pen_map"]


def test_the_matches_bound_holds_across_candidates_and_on_the_pen_maps_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The room left is what the call has not spent: seven matches fill a bound of seven, so the
    second candidate's first match is past it, on either pass; the refusal carries the account."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mlocate, "MATCHES_MAX", 7)
    _serve(ses, "locate-hardhat", screen="hardhat-screen", block="hardhat-characterram")
    out = refused("past 7 matches", s.gfx_locate(
        layouts=[BYTES_8X8, dict(BYTES_8X8, name="again")], patch=[48, 24, 64, 8],
        tag="characterram", count=256, flips=["none"]))
    assert out["code"] == "bad_argument" and "evaluated_by" in out
    monkeypatch.setattr(mlocate, "MATCHES_MAX", 1 << 16)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    one = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[80, 92, 48, 16], tag="gfx1")
    monkeypatch.setattr(mlocate, "MATCHES_MAX", one["matches_total"])
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    refused("matches", s.gfx_locate(layouts=[CIRCUS_CHAR, dict(CIRCUS_CHAR, name="again")],
                                    patch=[80, 92, 48, 16], tag="gfx1"))


def test_first_bounds_the_tiles_every_search_tries(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    """The tile that matches lies below `first`: the one-bank search, the transparent one, the
    pen map and the nearest each look only from `first` on."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], tag="gfx1", first=0x48,
                       count=10, flips=["none"])
    assert out["matched"] is False and out["nearest"]["tile"] >= 0x48, out
    _serve(ses, "locate-gridlee-sprite", screen="gridlee-screen", block="gridlee-gfx1")
    out = s.gfx_locate(layouts=[GRID_SPRITE], patch=[64, 43, 8, 16], tag="gfx1", transparent=0,
                       first=0xC0, count=16)
    assert out["matched"] is False
    assert out["nearest"]["available"] is False and "with `transparent`" in out["note"], out
    _serve(ses, "locate-hardhat", screen="hardhat-screen", block="hardhat-characterram")
    out = s.gfx_locate(layouts=[BYTES_8X8], patch=[48, 24, 64, 8], tag="characterram",
                       first=0x12, count=100, flips=["none"])
    assert sorted(m["tile"] for m in out["matches"]) == [0x1B, 0x1D], out["matches"]


def test_a_match_behind_an_offset_names_its_bit_in_the_block(monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], tag="gfx1", offset=8,
                       flips=["none"])
    m = out["matches"][0]
    assert (m["tile"], m["bit"], m["byte"]) == (0x46, 8 * 8 + 0x46 * 64, 8 + 0x46 * 8)
    assert isinstance(m["byte"], int)


def test_every_refusal_of_the_patch_and_the_range_carries_what_it_measured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    for patch in ([0, 250, 8, 8], [245, 0, 8, 8]):
        _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
        out = refused("leaves the 248x256 screen", s.gfx_locate(
            layouts=[CIRCUS_CHAR], patch=patch, tag="gfx1"))
        assert (out["width"], out["height"]) == (248, 256) and "evaluated_by" in out
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = refused("not all inside", s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8],
                                                 tag="gfx1", first=250, count=10))
    assert (out["code"], out["size"], out["tiles_available"]) == ("bad_argument", 0x800, 256)
    assert "evaluated_by" in out
    for patch in ([0, 0, 4, 8], [0, 0, 8, 4]):
        _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
        out = refused("holds no whole tile", s.gfx_locate(layouts=[CIRCUS_CHAR], patch=patch,
                                                          tag="gfx1"))
        assert "evaluated_by" in out
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = refused("one call gathers and compares", s.gfx_locate(
        layouts=[CIRCUS_CHAR], patch=[0, 0, 248, 256], tag="gfx1"))
    assert "evaluated_by" in out


def test_count_zero_searches_from_first_to_the_blocks_end(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], tag="gfx1", first=10,
                       flips=["none"])
    assert out["candidates"][0]["tiles_searched"] == [10, 246]


def test_the_cost_of_a_candidate_is_its_decoding_and_its_comparisons() -> None:
    assert mlocate._work(3, 5, 7, 11, False) == 5 * 11 + max(3 * 11, 3 * 7 * 5)
    assert mlocate._work(3, 5, 7, 11, True) == 5 * 11 + 3 * 7 * 5 * 11


def test_a_transparent_match_reads_its_bank_and_counts_what_it_compared() -> None:
    assert mlocate._transparent_match([0, 1, 2, 0], [0x10, 0x11, 0x12, 0x33], 0x3, 0) == (
        0x10, 2)
    assert mlocate._transparent_match([1, 2], [0x11, 0x12], 0x3, None) == (0x10, 2)
    assert mlocate._transparent_match([1, 1], [0x11, 0x11], 0x3, None) is None, "one value"


def test_every_legal_argument_edge_is_taken() -> None:
    eight = [dict(CIRCUS_CHAR, name=f"c{i}") for i in range(mlocate.LAYOUTS_MAX)]
    assert len(mlocate.check_gfx_locate(layouts=eight, patch=[0, 0, 8, 8], tag="gfx1")) == 8
    mlocate.check_gfx_locate(layouts=[CIRCUS_CHAR], patch=[0, 0, 8, 8], tag="gfx1",
                             flips=["none", "x", "y", "xy"])
    mlocate.check_gfx_locate(layouts=[GRID_FB], patch=[0, 0, 8, 8], ref="0x800", count=8)
    with pytest.raises(mstate.Invalid, match="count"):
        mlocate.check_gfx_locate(layouts=[GRID_FB], patch=[0, 0, 8, 8], ref="0x800")


# ------------------------------------------------------------------ gfx_locate: the nearest by hand

def _near(tiles: list[list[int]], left: int) -> tuple[dict[str, Any] | None, mlocate.Budget]:
    """`_nearest` over one 2x2 window reading 0 1 / 0 1, one flip, against `tiles` in order."""
    budget = mlocate.Budget(left)
    got = mlocate._nearest([mlocate.Window(0, 0, [0, 1, 0, 1])], lambda t: tiles[t], 0,
                           len(tiles), 2, 2, 1, "hand", ("none",), budget)
    return got, budget


def test_a_nearest_stops_when_the_budget_is_spent_and_not_one_comparison_later() -> None:
    got, budget = _near([[1, 1, 1, 1], [0, 1, 0, 1]], 4)
    assert got is not None and got["tile"] == 0 and budget.cut is True and budget.left == 0


def test_a_nearest_starts_a_comparison_with_one_pixel_of_budget_left() -> None:
    got, budget = _near([[1, 1, 1, 1], [0, 1, 0, 1]], 5)
    assert got is not None and got["tile"] == 1 and budget.cut is False


def test_a_nearest_spends_one_comparison_a_pixel() -> None:
    got, budget = _near([[1, 1, 1, 1], [0, 1, 0, 1]], 8)
    assert got is not None and got["tile"] == 1 and (budget.cut, budget.left) == (False, 0)


def test_a_nearest_keeps_the_better_tile_against_a_worse_one_after_it() -> None:
    got, _ = _near([[0, 1, 0, 1], [1, 0, 1, 0]], 100)
    assert got is not None and (got["tile"], got["disagree"]) == (0, 0)


def test_the_first_tile_is_the_nearest_so_far_however_much_it_disagrees() -> None:
    got, _ = _near([[1, 0, 1, 0]], 100)
    assert got is not None and (got["tile"], got["disagree"]) == (0, 4)


def test_a_comparison_stops_as_soon_as_it_is_no_better_than_the_best() -> None:
    _, budget = _near([[1, 1, 0, 1], [1, 0, 1, 0]], 100)
    assert budget.left == 100 - 4 - 1, "the second tile's first pixel ties the best's one"


# ------------------------------------------------------------------ what gfx_locate hands on

def test_a_transparent_pixel_is_left_out_of_the_pen_maps_table(monkeypatch: pytest.MonkeyPatch,
                                                                tmp_path: Path) -> None:
    """With the paper's value left out, each letter is read by its ink alone: the table names
    pen 5 only, and only the ink's pixels are compared; a 1-bit tile needs the ink's place to
    prove it, which only a candidate's own depth says."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-hardhat", screen="hardhat-screen", block="hardhat-characterram")
    out = s.gfx_locate(layouts=[BYTES_8X8], patch=[48, 24, 64, 8], tag="characterram",
                       count=256, flips=["none"], transparent=0)
    assert out["status"] == "ok", out
    found = sorted((m["window"][0], m["tile"]) for m in out["matches"])
    assert found == [(48 + 8 * i, code) for i, code in enumerate(HARDHAT_TEXT)], found
    assert all(m["pen_map"] == [[5, 1]] and 0 < m["compared"] < 64 for m in out["matches"])


def test_every_window_of_two_banks_is_counted_as_such(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    row = _hardhat(ses, [48, 24, 64, 8])["candidates"][0]
    assert row["windows"] == 0 and row["windows_mixed_bank"] > 1
    assert row["windows_uniform"] + row["windows_mixed_bank"] == 64 - 8 + 1


def test_a_match_off_a_byte_boundary_names_its_bit_and_no_byte() -> None:
    """Tiles one bit apart: a 2x1 tile starting at bit 1 matches, and bit 1 is no byte."""
    lay = {"name": "bits", "width": 2, "height": 1, "planes": 1, "planeoffset": [0],
           "xoffset": [0, 1], "yoffset": [0], "charincrement": 1}
    res = ml.resolve(ml.parse_layout(lay, allow_name=True), 8)
    cap = mscreen.Capture(":screen", 2, 1, 0, ":palette", array("I", [0, 0]), array("I", [4, 5]),
                          [0] * 8)
    blk = gfx.Block("region", ":gfx1", 1, 1, "little", bytes([0b0010_0000]))
    found, _, _ = mlocate._search(cap, blk, 0, res, 0, 7, [0, 0, 2, 1], None, ("none",),
                                  mlocate.Budget(100), 10, {}, False)
    assert [(m["tile"], m["bit"], m["byte"]) for m in found] == [(1, 1, None)], found


def _mark(*_: object) -> None:
    """A progress reporter no other call holds, to tell this call's from any default."""


def test_the_screen_capture_and_the_chunks_name_are_handed_to_the_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    seen: list[tuple[Any, ...]] = []
    real = mchunk.run

    def spy(*args: Any) -> Any:
        seen.append(args)
        return real(*args)

    monkeypatch.setattr(mchunk, "run", spy)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    mlocate.gfx_locate(cast(Any, ses), ses.scratch, [CIRCUS_CHAR], [88, 96, 8, 8], "gfx1", "", 0,
                       0, 0, None, ["none"], "", 5.0, _mark)
    (args,) = seen
    assert args[4] is _mark and args[5] == "gfx_locate"


def test_a_direct_colour_screen_holds_no_pens_to_locate(monkeypatch: pytest.MonkeyPatch,
                                                        tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-starfire", screen="starfire-screen")
    out = refused("drawn in direct colour", s.gfx_locate(layouts=[CIRCUS_CHAR],
                                                         patch=[0, 0, 8, 8], tag="gfx1"))
    assert out["code"] == "no_channel" and out["screen"] == ":screen" and "evaluated_by" in out
    assert "holds no pens to search for" in out["message"]
    _left_clean(ses)


def test_the_block_and_each_layout_are_read_with_the_calls_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    seen: dict[str, dict[str, Any]] = {}
    for name in ("parse_block", "resolved_for"):
        real = getattr(gfx, name)

        def spy(*args: Any, _real: Any = real, _name: str = name) -> Any:
            seen[_name] = args[-1]
            return _real(*args)

        monkeypatch.setattr(gfx, name, spy)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    s.gfx_locate(layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], tag="gfx1", flips=["none"])
    assert set(seen) == {"parse_block", "resolved_for"}
    assert all("evaluated_by" in common for common in seen.values()), seen


def test_a_first_past_the_block_with_no_count_searches_nothing(monkeypatch: pytest.MonkeyPatch,
                                                               tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = refused("nothing would be compared", s.gfx_locate(
        layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], tag="gfx1", first=300, flips=["none"]))
    assert out["code"] == "bad_argument"


def test_the_pen_map_is_not_tried_one_operation_past_both_candidates_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Both passes of both candidates are counted, the pen map's at its pixel-by-pixel cost."""
    ses = _channel(monkeypatch, tmp_path)
    wins, n, pixels = 57, 256, 64
    both = 2 * (mlocate._work(wins, n, 1, pixels, False) + mlocate._work(wins, n, 1, pixels, True))
    monkeypatch.setattr(mlocate, "WORK_MAX", both - 1)
    _serve(ses, "locate-hardhat", screen="hardhat-screen", block="hardhat-characterram")
    out = s.gfx_locate(layouts=[BYTES_8X8, dict(BYTES_8X8, name="again")], patch=[48, 24, 64, 8],
                       tag="characterram", count=256, flips=["none"])
    assert out["pen_map"]["tried"] is False, out["pen_map"]


def test_the_nearest_across_candidates_keeps_the_first_of_two_as_near(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-circus-shifted", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[CIRCUS_CHAR, dict(CIRCUS_CHAR, name="again")],
                       patch=[89, 96, 8, 8], tag="gfx1", flips=["none"])
    assert out["nearest"]["layout"] == "charlayout", out["nearest"]


def test_the_nearest_across_candidates_is_not_taken_from_a_farther_later_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The 16x16 layout comes nearest at three of 256 pixels, the chars at one of 64: listed
    first, the nearer stays the nearest."""
    ses = _channel(monkeypatch, tmp_path)
    big = {"name": "sixteen", "width": 16, "height": 16, "planes": 1, "planeoffset": [0],
           "xoffset": "{ STEP16(0,1) }", "yoffset": "{ STEP16(0,16) }", "charincrement": 256}
    _serve(ses, "locate-circus-g", screen="circus-screen", block="circus-gfx1")
    out = s.gfx_locate(layouts=[big, CIRCUS_CHAR], patch=[176, 32, 16, 16], tag="gfx1",
                       flips=["none"])
    assert (out["nearest"]["layout"], out["nearest"]["disagree"]) == ("sixteen", 3), out


def test_a_window_two_candidates_both_read_is_ambiguous_in_every_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-hardhat", screen="hardhat-screen", block="hardhat-characterram")
    out = s.gfx_locate(layouts=[BYTES_8X8, dict(BYTES_8X8, name="again")],
                       patch=[48, 24, 64, 8], tag="characterram", count=256, flips=["none"])
    assert out["matches"] and all(m["ambiguous"] for m in out["matches"])


def test_an_unmatched_opaque_search_says_why_no_window_was_compared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    out = _hardhat(ses, [48, 25, 64, 8])
    assert "every window was of one pen or of two banks" in out["note"], out


def test_a_cpu_space_range_is_read_for_the_span_every_candidate_needs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Tile t starts t * 4 bytes on (32 to a 128-byte line) and reaches 7 lines and 4 bytes
    further: the span from 0x800 ends where the last of the 7680 tiles does."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "locate-gridlee-ref", screen="gridlee-screen", block="gridlee-space-800")
    s.gfx_locate(layouts=[GRID_FB], patch=[96, 96, 8, 8], ref="0x800", count=7680, flips=["none"])
    span = 7679 * 4 + 7 * 128 + 4
    assert f", {0x800}, {span})" in ses.stdin.getvalue().decode()


# ------------------------------------------------------------------ attach


def test_a_view_asked_not_to_attach_writes_its_picture_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`attach` false keeps the picture out of the reply and still writes the file it names."""
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-circus", screen="circus-screen")
    screen = s.screen_view(scale=1, attach=False)
    assert screen["status"] == "ok", screen
    assert screen["image"]["inline"] is False and screen["image"]["not_inlined"] == "attach=false"
    assert Path(screen["image"]["path"]).is_file()


def test_a_view_attaches_its_picture_unless_asked_not_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-circus", screen="circus-screen")
    shown = s.screen_view(scale=1)
    assert shown["image"]["inline"] is True and "not_inlined" not in shown["image"], shown


def test_the_pixel_crop_asked_not_to_attach_goes_to_its_dest_unattached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    dest = tmp_path / "pixel.png"
    out = s.screen_view(mode="pixel", point=[100, 100], dest=str(dest), attach=False)
    assert out["status"] == "ok", out
    assert out["image"]["not_inlined"] == "attach=false" and out["image"]["path"] == str(dest)
    assert dest.is_file() and "note" not in out
    _serve(ses, "screen-gridlee", screen="gridlee-screen")
    renamed = s.screen_view(mode="pixel", point=[100, 100], dest=str(tmp_path / "Pixel_2.PNG"),
                            attach=False)
    assert renamed["image"]["path"] == str(tmp_path / "pixel-2.png"), renamed
    assert renamed["note"] == written_as("dest", str(tmp_path / "Pixel_2.PNG")), renamed


def test_gfx_view_asked_not_to_attach_writes_its_picture_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus", block="circus-gfx1")
    out = s.gfx_view(layout=CIRCUS_CHAR, palette="palette", tag="gfx1", scale=1, attach=False)
    assert out["status"] == "ok", out
    assert out["image"]["inline"] is False and out["image"]["not_inlined"] == "attach=false"
    assert Path(out["image"]["path"]).is_file()


def test_gfx_view_and_palette_write_a_dest_by_the_file_name_rule_and_say_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    _serve(ses, "gfx-circus", block="circus-gfx1")
    view = s.gfx_view(layout=CIRCUS_CHAR, palette="palette", tag="gfx1", scale=1,
                      dest=str(tmp_path / "Chars_1.PNG"))
    assert view["image"]["path"] == str(tmp_path / "chars-1.png"), view
    assert view["note"].endswith(str(written_as("dest", str(tmp_path / "Chars_1.PNG")))), view
    _serve(ses, "palette-circus")
    pal = s.palette(dest=str(tmp_path / "Pens_1.PNG"))
    assert pal["image"]["path"] == str(tmp_path / "pens-1.png"), pal
    assert pal["note"].endswith(str(written_as("dest", str(tmp_path / "Pens_1.PNG")))), pal
    _serve(ses, "palette-circus")
    kept = s.palette(dest=str(tmp_path / "pens-2.png"))
    assert "written as" not in kept.get("note", ""), kept


@pytest.mark.parametrize(("call", "said"), [
    (lambda: s.screen_view(mode="histogram", attach=False), "would do nothing"),
    (lambda: s.screen_view(attach="no"), "attach is true or false"),
    (lambda: s.gfx_view(layout=CIRCUS_CHAR, tag="gfx1", attach=1), "attach is true or false"),
], ids=["histogram has no picture", "screen_view", "gfx_view"])
def test_an_attach_that_is_no_yes_or_no_or_would_do_nothing_is_refused(
        call: Any, said: str) -> None:
    refused = call()
    assert refused["status"] == "INVALID" and refused["code"] == "bad_argument", refused
    assert said in refused["message"]
