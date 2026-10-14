"""The picture in the reply: the stdlib PNG writer, the inline ceiling, and the attachment
beside the JSON at the MCP boundary.

Each case reads the written file back with the suite's own reader (`png_read`), so what is held is
the file's pixels and palette, never the writer's idea of them.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import zlib
from pathlib import Path

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import png_read  # noqa: E402
from session_doubles import blank_session  # noqa: E402

import mame_picture as picture  # noqa: E402
import mame_png as mpng  # noqa: E402
import mame_state as mstate  # noqa: E402


@pytest.fixture(autouse=True)
def _blank(monkeypatch: pytest.MonkeyPatch) -> None:
    blank_session(monkeypatch)


def test_an_indexed_raster_keeps_every_index_and_its_palette() -> None:
    """THE FILE IS THE DATA: an indexed PNG carries the index of every pixel, so two pens that
    share a colour stay two pens in the file."""
    palette = ((0, 0, 0), (0, 0, 0), (255, 0, 0))          # pens 0 and 1 are both black
    raster = mpng.Raster(3, 2, bytes([0, 1, 2, 2, 1, 0]), palette)
    out = png_read.read(mpng.encode(raster))
    assert out.indexed and (out.width, out.height) == (3, 2)
    assert out.pixels == bytes([0, 1, 2, 2, 1, 0]) and out.palette == list(palette)


def test_an_rgb_raster_is_written_as_rgb() -> None:
    raster = mpng.Raster(2, 1, bytes([1, 2, 3, 250, 251, 252]))
    out = png_read.read(mpng.encode(raster))
    assert not out.indexed and out.at(0, 0) == (1, 2, 3) and out.at(1, 0) == (250, 251, 252)


def test_an_enlargement_is_nearest_neighbour_and_keeps_the_indices() -> None:
    raster = mpng.Raster(2, 2, bytes([0, 1, 2, 3]), ((0, 0, 0),) * 4)
    big = mpng.enlarged(raster, 3)
    assert (big.width, big.height) == (6, 6)
    out = png_read.read(mpng.encode(big))
    for y in range(6):
        for x in range(6):
            assert out.at(x, y) == [0, 1, 2, 3][(y // 3) * 2 + x // 3], (x, y)
    rgb = mpng.enlarged(mpng.Raster(1, 1, bytes([9, 8, 7])), 2)
    assert rgb.pixels == bytes([9, 8, 7]) * 4


def test_a_malformed_raster_is_refused_where_it_is_built() -> None:
    with pytest.raises(ValueError, match="bytes; got"):
        mpng.Raster(2, 2, bytes(3), ((0, 0, 0),))
    with pytest.raises(ValueError, match="PLTE holds"):
        mpng.Raster(1, 1, bytes(1), ((0, 0, 0),) * 257)


def test_the_ceiling_is_the_side_and_the_tile_count() -> None:
    """The inline ceiling at its edges: a side of exactly the maximum fits, one more does not;
    a picture whose sides fit but whose tiles of 28 px add up past the budget does not either."""
    side = picture.INLINE_SIDE_MAX
    assert picture.within_ceiling(side, 28)
    assert not picture.within_ceiling(side + 1, 28)
    # 40 x 40 tiles = 1600 > 1568, with both sides well under the side maximum.
    assert not picture.within_ceiling(40 * picture.TOKEN_SIDE, 40 * picture.TOKEN_SIDE)
    assert picture.within_ceiling(39 * picture.TOKEN_SIDE, 40 * picture.TOKEN_SIDE)


def test_the_automatic_scale_is_the_largest_that_fits() -> None:
    assert picture.auto_scale(8, 8) == picture.SCALE_MAX, "a tile is enlarged all the way"
    factor = picture.auto_scale(256, 224)
    assert picture.within_ceiling(256 * factor, 224 * factor)
    assert not picture.within_ceiling(256 * (factor + 1), 224 * (factor + 1))
    assert picture.auto_scale(2000, 10) == 1, "a source past the ceiling is not shrunk"
    side = picture.INLINE_SIDE_MAX // picture.SCALE_MAX
    assert picture.auto_scale(side, 10) == picture.SCALE_MAX
    assert picture.auto_scale(side, 10, border=2) == picture.SCALE_MAX - 1, (
        "a border is part of the picture the ceiling judges")


def test_a_border_frames_an_rgb_picture_and_refuses_an_indexed_one() -> None:
    rgb = mpng.Raster(2, 1, bytes([1, 2, 3, 4, 5, 6]))
    framed = picture.bordered(rgb, 1)
    grey = bytes(picture.BORDER_COLOUR)
    assert (framed.width, framed.height) == (4, 3)
    assert framed.pixels == grey * 4 + grey + bytes([1, 2, 3, 4, 5, 6]) + grey + grey * 4
    with pytest.raises(ValueError, match="an indexed one is data"):
        picture.bordered(mpng.Raster(1, 1, b"\x00", ((0, 0, 0),)), 1)


@pytest.mark.parametrize("bad", [-1, picture.SCALE_MAX + 1, True, 1.5])
def test_a_scale_outside_its_range_is_refused(bad: object) -> None:
    with pytest.raises(mstate.Invalid, match="scale="):
        picture.check_scale(bad)  # type: ignore[arg-type]


def test_publish_writes_one_png_and_names_it(tmp_path: Path) -> None:
    raster = mpng.Raster(4, 4, bytes(range(16)), tuple((i, i, i) for i in range(16)))
    image = picture.publish(raster, 0, None, tmp_path, "palette")
    path = Path(image["path"])
    data = path.read_bytes()
    assert path.parent == tmp_path / "gfx" and path.name == "palette-1.png"
    assert image["sha256"] == hashlib.sha256(data).hexdigest() and image["bytes"] == len(data)
    assert image["scale"] == picture.SCALE_MAX and image["inline"] is True
    assert (image["width"], image["height"]) == (4 * picture.SCALE_MAX, 4 * picture.SCALE_MAX)
    assert "not_inlined" not in image and image["indexed"] is True
    assert mstate.STATE.captures == [("image", str(path))], "`captures` lists it"
    again = picture.publish(raster, 1, None, tmp_path, "palette")
    assert Path(again["path"]).name == "palette-2.png", "a second picture never overwrites"


def test_a_picture_past_the_ceiling_is_written_and_not_inlined(tmp_path: Path) -> None:
    raster = mpng.Raster(picture.INLINE_SIDE_MAX + 1, 1, bytes(picture.INLINE_SIDE_MAX + 1),
                         ((0, 0, 0),))
    image = picture.publish(raster, 0, None, tmp_path, "screen")
    assert image["inline"] is False and Path(image["path"]).is_file()
    assert "crop" in image["not_inlined"] and image["scale"] == 1


def _result(image: dict[str, object]) -> CallToolResult:
    body = {"summary": "x", "status": "ok", "image": image}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(body))],
                          structured_content=body)


def test_the_picture_is_attached_after_the_json_and_is_the_file(tmp_path: Path) -> None:
    image = picture.publish(mpng.Raster(2, 2, bytes(4), ((1, 2, 3),)), 0, None, tmp_path, "p")
    out = picture.attached(_result(image))
    assert [c.type for c in out.content] == ["text", "image"]
    shown = out.content[1]
    assert isinstance(shown, ImageContent) and shown.mime_type == "image/png"
    assert hashlib.sha256(base64.b64decode(shown.data)).hexdigest() == image["sha256"]
    assert out.structured_content == _result(image).structured_content


def test_nothing_is_attached_when_the_body_says_not_inline(tmp_path: Path) -> None:
    image = picture.publish(mpng.Raster(2, 2, bytes(4), ((1, 2, 3),)), 0, None, tmp_path, "p")
    out = picture.attached(_result({**image, "inline": False}))
    assert [c.type for c in out.content] == ["text"]
    plain = CallToolResult(content=[TextContent(type="text", text="{}")], structured_content={})
    assert picture.attached(plain) is plain, "a reply with no image is left alone"


def test_a_file_that_changed_is_not_attached_and_the_body_says_so(tmp_path: Path) -> None:
    image = picture.publish(mpng.Raster(2, 2, bytes(4), ((1, 2, 3),)), 0, None, tmp_path, "p")
    Path(str(image["path"])).write_bytes(b"not the picture")
    out = picture.attached(_result(image))
    assert [c.type for c in out.content] == ["text"]
    assert out.structured_content is not None
    said = out.structured_content["image"]
    assert said["inline"] is False and "sha256" in said["not_inlined"]
    text = out.content[0]
    assert isinstance(text, TextContent) and json.loads(text.text)["image"]["inline"] is False


def test_a_numbered_picture_never_lands_on_a_file_already_there(tmp_path: Path) -> None:
    (tmp_path / "gfx").mkdir()
    (tmp_path / "gfx" / "screen-1.png").write_bytes(b"somebody else's")
    (tmp_path / "gfx" / "palette-1.png").write_bytes(b"another tool's")
    image = picture.publish(mpng.Raster(1, 1, bytes(1), ((0, 0, 0),)), 1, None, tmp_path,
                            "screen")
    assert Path(image["path"]).name == "screen-2.png"
    assert (tmp_path / "gfx" / "screen-1.png").read_bytes() == b"somebody else's"


def test_a_reply_whose_body_is_not_an_object_is_left_alone() -> None:
    bare = CallToolResult(content=[TextContent(type="text", text="x")], structured_content=None)
    assert picture.attached(bare) is bare
    assert picture.attached("not a result") == "not a result"


def test_a_raster_below_one_pixel_a_side_is_refused() -> None:
    for w, h in ((0, 5), (5, 0)):
        with pytest.raises(ValueError, match="at least 1x1"):
            mpng.Raster(w, h, b"")


def test_an_animation_is_a_still_first_frame_then_placed_frames_any_viewer_plays() -> None:
    """The first frame's data is a plain IDAT, what a viewer that knows no animation shows; each
    later one an fdAT under the sequence the fcTLs share; every frame placed at the origin,
    drawn over nothing kept (dispose none) and replacing what is there (blend source)."""
    import struct
    frames = [mpng.Raster(2, 1, bytes([k] * 6)) for k in (10, 20, 30)]
    data = mpng.encode_animation(frames, (1, 60))
    plays, delays, pictures = png_read.read_animation(data)
    assert (plays, delays, len(pictures)) == (0, [(1, 60)] * 3, 3)
    chunks = [(k, b) for k, b in png_read._chunks(data) if k in (b"fcTL", b"IDAT", b"fdAT")]
    assert [k for k, _ in chunks] == [b"fcTL", b"IDAT", b"fcTL", b"fdAT", b"fcTL", b"fdAT"]
    assert zlib.decompress(chunks[1][1]) == b"\x00" + bytes([10] * 6), "frame one, bare"
    placed = [struct.unpack(">IIIIIHHBB", body) for kind, body in chunks if kind == b"fcTL"]
    assert [p[0] for p in placed] == [0, 1, 3], "the IDAT takes no number, each fdAT one"
    assert all((w, h, x, y, dispose, blend) == (2, 1, 0, 0, 0, 0)
               for _seq, w, h, x, y, _num, _den, dispose, blend in placed)
