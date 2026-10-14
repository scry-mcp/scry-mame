"""A PNG writer in the standard library, indexed or RGB, and the nearest-neighbour enlargement.

WHY NOT PILLOW. The server takes no dependency it can do without, and a PNG is five chunks and
a zlib stream. What matters here is the INDEXED form: a picture of palette indices written as an
indexed PNG keeps the index of every pixel in the file, so the file is the data and not only a
view of it, which is what lets a golden compare pens and not colours that two pens can share.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import mame_prose as prose

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PLTE_MAX = 256
_INDEXED, _RGB = 3, 2          # PNG colour types
_FILTER_NONE = b"\x00"


@dataclass(frozen=True)
class Raster:
    """A picture before it is encoded: one byte per pixel with `palette` (the PLTE, each entry
    `(r, g, b)`), or three bytes per pixel with none."""

    width: int
    height: int
    pixels: bytes
    palette: tuple[tuple[int, int, int], ...] | None = None

    def __post_init__(self) -> None:
        depth = 1 if self.palette is not None else 3
        if self.width < 1 or self.height < 1:
            raise ValueError(f"a raster is at least 1x1; got {self.width}x{self.height}")
        if len(self.pixels) != self.width * self.height * depth:
            need = prose.counted(self.width * self.height * depth, "byte")
            raise ValueError(f"{self.width}x{self.height} at {prose.counted(depth, 'byte')} a "
                             f"pixel is {need}; got {len(self.pixels)}")
        if self.palette is not None and not 1 <= len(self.palette) <= PLTE_MAX:
            raise ValueError(f"a PLTE holds 1..{PLTE_MAX} entries; got {len(self.palette)}")


def enlarged(raster: Raster, factor: int) -> Raster:
    """`raster` with every pixel a `factor` x `factor` square of itself: nothing is resampled,
    so an indexed picture keeps its indices."""
    if factor == 1:
        return raster
    depth = 1 if raster.palette is not None else 3
    stride = raster.width * depth
    rows = []
    for y in range(raster.height):
        row = raster.pixels[y * stride:(y + 1) * stride]
        wide = b"".join(row[x:x + depth] * factor for x in range(0, stride, depth))
        rows.append(wide * factor)
    return Raster(raster.width * factor, raster.height * factor, b"".join(rows), raster.palette)


def encode(raster: Raster) -> bytes:
    """The PNG file of `raster`: 8 bits a sample, filter none on every row."""
    out = _head(raster)
    out += [_chunk(b"IDAT", _stream(raster)), _chunk(b"IEND", b"")]
    return b"".join(out)


def encode_animation(frames: list[Raster], delay: tuple[int, int]) -> bytes:
    """An animated PNG (APNG) of `frames`, every one shown for `delay` (numerator, denominator,
    in seconds) and played for ever. The first frame is the file's still image as well, so a
    viewer that knows no animation shows it. APNG is three more chunk kinds over a PNG: `acTL`
    counts the frames, an `fcTL` places each, and `fdAT` carries every frame after the first
    under one sequence of numbers shared with the `fcTL`s. All frames share the first one's
    size and palette."""
    if not frames:
        raise ValueError("an animation has at least one frame")
    first = frames[0]
    for f in frames[1:]:
        if (f.width, f.height, f.palette) != (first.width, first.height, first.palette):
            raise ValueError("every frame of an animation has the first one's size and palette")
    out = _head(first)
    out.append(_chunk(b"acTL", struct.pack(">II", len(frames), 0)))
    seq = 0
    for i, frame in enumerate(frames):
        out.append(_chunk(b"fcTL", struct.pack(">IIIIIHHBB", seq, frame.width, frame.height, 0,
                                               0, delay[0], delay[1], 0, 0)))
        seq += 1
        if i == 0:
            out.append(_chunk(b"IDAT", _stream(frame)))
        else:
            out.append(_chunk(b"fdAT", struct.pack(">I", seq) + _stream(frame)))
            seq += 1
    out.append(_chunk(b"IEND", b""))
    return b"".join(out)


def _head(raster: Raster) -> list[bytes]:
    """The signature, `IHDR`, and `PLTE` when the raster is indexed."""
    header = struct.pack(">IIBBBBB", raster.width, raster.height, 8,
                         _INDEXED if raster.palette is not None else _RGB, 0, 0, 0)
    out = [PNG_SIGNATURE, _chunk(b"IHDR", header)]
    if raster.palette is not None:
        out.append(_chunk(b"PLTE", b"".join(bytes(c) for c in raster.palette)))
    return out


def _stream(raster: Raster) -> bytes:
    """The compressed image data of `raster`, filter none on every row."""
    stride = raster.width * (1 if raster.palette is not None else 3)
    body = b"".join(_FILTER_NONE + raster.pixels[y * stride:(y + 1) * stride]
                    for y in range(raster.height))
    return zlib.compress(body, 6)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
