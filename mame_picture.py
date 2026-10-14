"""The picture a graphics tool answers with: ONE PNG on disk, its `image` block in the reply, and
the same bytes attached beside the JSON when the model can see them unresampled.

THE CEILING. Past a long side of `INLINE_SIDE_MAX` pixels, or past
`INLINE_TOKENS_MAX` tiles of `TOKEN_SIDE` pixels, the API resamples an image before the model sees
it, and a resampled picture of pixel art is a plausible wrong picture: pens blend, one-pixel
lines vanish. So a picture above it is written, named and NOT attached, and the reply says why;
the caller asks for a crop. Transport is not the limit: a far larger PNG crosses the protocol
intact, and it is the resampling that would make it wrong.

THE SCALE. Inside the ceiling a small source is enlarged by an integer factor, nearest neighbour,
so every source pixel is a square of one pen and nothing is resampled; the factor is in the
reply. `scale=0` picks the largest factor that stays inside.

WHY THE ATTACHMENT IS READ BACK FROM THE FILE. The body names a path and a sha256, and the
picture beside it is the file at that path, hashed again at the MCP boundary: a picture that is
not provably the file the body names would be two answers to one question.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult, ImageContent, TextContent

import mame_files as files
import mame_inputs as inputs
import mame_png as png
from mame_state import STATE

INLINE_SIDE_MAX = 1568
INLINE_TOKENS_MAX = 1568
TOKEN_SIDE = 28
SCALE_MAX = 8
BORDER_COLOUR = (0x80, 0x80, 0x80)     # a neutral grey: what lies outside the picture's source


def within_ceiling(width: int, height: int) -> bool:
    """Whether a `width` x `height` picture reaches the model as it is."""
    tiles = math.ceil(width / TOKEN_SIDE) * math.ceil(height / TOKEN_SIDE)
    return max(width, height) <= INLINE_SIDE_MAX and tiles <= INLINE_TOKENS_MAX


def auto_scale(width: int, height: int, border: int = 0) -> int:
    """The largest factor in 1..`SCALE_MAX` that keeps the enlarged picture, and a `border` of
    output pixels round it, inside the ceiling; 1 when even the source is above it (it is then
    written and not attached)."""
    for factor in range(SCALE_MAX, 1, -1):
        if within_ceiling(width * factor + 2 * border, height * factor + 2 * border):
            return factor
    return 1


def check_scale(scale: int) -> None:
    """A `scale` is 0 (the largest that fits) or a factor in 1..`SCALE_MAX`."""
    inputs.natural("scale", scale, ": 0 picks the largest integer enlargement inside the inline "
                   f"ceiling, or name a factor in 1..{SCALE_MAX}", hi=SCALE_MAX)


def check_picture(scale: int = 0, dest: str = "") -> Path | None:
    """What every graphics tool judges before the machine: the scale, and a `dest` that is a
    fresh absolute path (`mame_inputs.fresh_dest`), handed back as the `Path` it built."""
    check_scale(scale)
    return inputs.optional_dest(dest)


#: A rectangle marked over a picture: `x`, `y`, `width`, `height` in source pixels, and its RGB.
Mark = tuple[int, int, int, int, tuple[int, int, int]]
#: A mark drawn round a rectangle instead: the same, and how many output pixels OUTSIDE it the
#: ring runs (1 hugs it), so two rings of different colours frame one pixel on any background.
Ring = tuple[int, int, int, int, tuple[int, int, int], int]


def publish(raster: png.Raster, scale: int, dest: Path | None, scratch: Path,
            stem: str, marks: list[Mark] | None = None,
            rings: list[Ring] | None = None, border: int = 0) -> dict[str, Any]:
    """Write `raster` as ONE PNG, enlarged by `scale` (0: the largest that fits), to `dest` or to
    a numbered file in the scratch, and answer its `image` block. Marks and rings (RGB pictures
    only) are drawn AFTER the enlargement, one output pixel wide: a mark along its rectangle's
    outer pixel squares, a ring OUTSIDE them, so a ring covers none of what it frames. A `border`
    of that many output pixels in `BORDER_COLOUR` goes round the picture first (RGB only), where
    a ring round a pixel at the picture's edge has room; the block names it."""
    factor = scale or auto_scale(raster.width, raster.height, border)
    big = png.enlarged(raster, factor)
    if border:
        big = bordered(big, border)
    if marks or rings:
        big = outlined(big, marks or [], rings or [], factor, border)
    data = png.encode(big)
    dest = _written(data, dest, scratch, stem)
    block: dict[str, Any] = {
        **_file_block(dest, data), "width": big.width, "height": big.height, "scale": factor,
        "indexed": raster.palette is not None,
        "inline": within_ceiling(big.width, big.height),
    }
    if border:
        block["border"] = border
    if not block["inline"]:
        block["not_inlined"] = (
            f"{big.width}x{big.height} is past the inline ceiling (a side of "
            f"{INLINE_SIDE_MAX} px, {INLINE_TOKENS_MAX} tiles of {TOKEN_SIDE} px), where the API "
            "would resample it: the file is written; ask for a crop or a smaller scale")
    return block


def data_file(raster: png.Raster, scratch: Path, stem: str) -> dict[str, Any]:
    """Write `raster` unscaled as the DATA beside a picture that is a view of it (a view dims or
    marks, and an indexed data PNG cannot), and answer its block. Never attached: the view is."""
    data = png.encode(raster)
    dest = _written(data, None, scratch, stem)
    return {**_file_block(dest, data), "width": raster.width, "height": raster.height,
            "indexed": raster.palette is not None}


def _written(data: bytes, dest: Path | None, scratch: Path, stem: str) -> Path:
    """`data` at `dest`, or at the next numbered `stem` of the scratch's `gfx`, recorded as a
    capture of the session."""
    if dest is None:
        folder = scratch / "gfx"
        folder.mkdir(exist_ok=True)
        dest = files.first_free(folder, lambda number: f"{stem}-{number}.png")
    dest.write_bytes(data)
    STATE.captures.append(("image", str(dest)))
    return dest


def _file_block(dest: Path, data: bytes) -> dict[str, Any]:
    return {"path": str(dest), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def bordered(raster: png.Raster, border: int) -> png.Raster:
    """`raster` (RGB) framed by `border` output pixels of `BORDER_COLOUR` on every side."""
    if raster.palette is not None:
        raise ValueError("a border is drawn round an RGB picture: an indexed one is data")
    width = raster.width + 2 * border
    edge = bytes(BORDER_COLOUR) * width
    side = bytes(BORDER_COLOUR) * border
    rows = [side + raster.pixels[y * raster.width * 3:(y + 1) * raster.width * 3] + side
            for y in range(raster.height)]
    return png.Raster(width, raster.height + 2 * border,
                      edge * border + b"".join(rows) + edge * border)


def outlined(raster: png.Raster, marks: list[Mark], rings: list[Ring],
             factor: int, origin: int = 0) -> png.Raster:
    """`raster` (RGB, already enlarged by `factor`, its source's pixel (0, 0) at output pixel
    (`origin`, `origin`)) with each mark's outline, then each ring, drawn in, in order."""
    if raster.palette is not None:
        raise ValueError("marks are drawn over an RGB picture: an indexed one is data")
    px = bytearray(raster.pixels)
    width = raster.width

    def put(x: int, y: int, rgb: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < raster.height:
            at = (y * width + x) * 3
            px[at:at + 3] = bytes(rgb)

    def square(left: int, top: int, right: int, bottom: int, rgb: tuple[int, int, int]) -> None:
        for xx in range(left, right + 1):
            put(xx, top, rgb)
            put(xx, bottom, rgb)
        for yy in range(top, bottom + 1):
            put(left, yy, rgb)
            put(right, yy, rgb)

    o = origin
    for x, y, w, h, rgb in marks:
        square(o + x * factor, o + y * factor, o + (x + w) * factor - 1,
               o + (y + h) * factor - 1, rgb)
    for x, y, w, h, rgb, gap in rings:
        square(o + x * factor - gap, o + y * factor - gap, o + (x + w) * factor - 1 + gap,
               o + (y + h) * factor - 1 + gap, rgb)
    return png.Raster(raster.width, raster.height, bytes(px))


def attached(result: Any) -> Any:
    """`result` with its picture beside the JSON, when its body's `image` says `inline`: the
    one place a reply gains an `ImageContent`, at the MCP boundary, so a tool body and a test
    handle a plain dict. The file is hashed again first; a file that no longer matches its
    `sha256` is not attached, and the body says so."""
    if not isinstance(result, CallToolResult) or not isinstance(result.structured_content, dict):
        return result
    body = result.structured_content
    image = body.get("image")
    if not isinstance(image, dict) or image.get("inline") is not True:
        return result
    data = Path(image["path"]).read_bytes() if Path(image["path"]).is_file() else b""
    if hashlib.sha256(data).hexdigest() != image["sha256"]:
        body = {**body, "image": {**image, "inline": False,
                                  "not_inlined": "the file no longer matches its sha256, so the "
                                                 "picture it holds is not the one this reply "
                                                 "describes"}}
        return CallToolResult(content=[_text(body)], structured_content=body)
    picture = ImageContent(type="image", data=base64.b64encode(data).decode("ascii"),
                           mime_type="image/png")
    return CallToolResult(content=[*result.content, picture], structured_content=body)


def _text(body: dict[str, Any]) -> TextContent:
    return TextContent(type="text", text=json.dumps(body, indent=2))
