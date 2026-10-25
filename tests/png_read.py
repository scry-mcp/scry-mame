"""A PNG reader for the suite, so tests assert on the file's own pixels and palette.

Reads only what the server writes: 8-bit indexed or RGB, filter none, no interlace. Checks CRCs.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass
class Png:
    width: int
    height: int
    indexed: bool
    pixels: bytes                       # one byte per pixel (indexed) or three (RGB)
    palette: list[tuple[int, int, int]]

    def at(self, x: int, y: int) -> int | tuple[int, int, int]:
        if self.indexed:
            return self.pixels[y * self.width + x]
        i = (y * self.width + x) * 3
        return (self.pixels[i], self.pixels[i + 1], self.pixels[i + 2])


def _chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data[:8] == SIGNATURE, "not a PNG signature"
    pos, chunks = 8, []
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF, f"bad CRC on {kind!r}"
        chunks.append((kind, body))
        pos += 12 + length
    assert chunks[0][0] == b"IHDR" and chunks[-1][0] == b"IEND", [k for k, _ in chunks]
    return chunks


def read(data: bytes) -> Png:
    chunks = _chunks(data)
    return _image(chunks, b"".join(b for k, b in chunks if k == b"IDAT"))


def read_animation(data: bytes) -> tuple[int, list[tuple[int, int]], list[Png]]:
    """An APNG: play count, per-frame delays (num, den) and frames; sequence numbers checked."""
    chunks = _chunks(data)
    actl = [b for k, b in chunks if k == b"acTL"]
    assert len(actl) == 1, "an animation has one acTL"
    frames, plays = struct.unpack(">II", actl[0])
    seq, delays, pictures, current = 0, [], [], None
    streams: list[bytes] = []
    for kind, body in chunks:
        if kind == b"fcTL":
            (n,) = struct.unpack(">I", body[:4])
            assert n == seq, f"fcTL sequence {n}, expected {seq}"
            seq += 1
            delays.append(struct.unpack(">HH", body[20:24]))
            if current is not None:
                streams.append(current)
            current = b""
        elif kind == b"IDAT":
            assert current is not None, "the first frame's IDAT follows its fcTL"
            current += body
        elif kind == b"fdAT":
            (n,) = struct.unpack(">I", body[:4])
            assert n == seq, f"fdAT sequence {n}, expected {seq}"
            seq += 1
            assert current is not None
            current += body[4:]
    assert current is not None
    streams.append(current)
    assert len(streams) == frames, f"acTL counts {frames} frames and {len(streams)} are there"
    pictures = [_image(chunks, stream) for stream in streams]
    return plays, delays, pictures


def _image(chunks: list[tuple[bytes, bytes]], stream: bytes) -> Png:
    width, height, depth, colour, comp, filt, lace = struct.unpack(">IIBBBBB", chunks[0][1])
    assert (depth, comp, filt, lace) == (8, 0, 0, 0) and colour in (2, 3), chunks[0][1]
    indexed = colour == 3
    plte = b"".join(b for k, b in chunks if k == b"PLTE")
    palette = [(plte[i], plte[i + 1], plte[i + 2]) for i in range(0, len(plte), 3)]
    raw = zlib.decompress(stream)
    stride = width * (1 if indexed else 3)
    rows = []
    for y in range(height):
        row = raw[y * (stride + 1):(y + 1) * (stride + 1)]
        assert row[0] == 0, f"row {y} uses filter {row[0]}"
        rows.append(row[1:])
    return Png(width, height, indexed, b"".join(rows), palette)
