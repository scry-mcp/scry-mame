"""A pen word as RGB, written once (`mame_palette.rgb_bytes`) for every place a pen or a pixel of
`pixels()` becomes a colour: the screen's cells, a crop, a series frame, the palette's swatch."""
from __future__ import annotations

import random
from array import array

import mame_palette as mpal


def test_one_pen_to_rgb_reads_every_word_as_the_shifts_would() -> None:
    """Its byte slicing, in the host's word order, against the arithmetic every copy wrote."""
    rng = random.Random(0)
    words = [0xFF123456, 0x00ABCDEF, 0, 0xFFFFFFFF] + [rng.getrandbits(32) for _ in range(500)]
    want = b"".join(bytes(((w >> 16) & 0xFF, (w >> 8) & 0xFF, w & 0xFF)) for w in words)
    assert mpal.rgb_bytes(words) == want == mpal.rgb_bytes(array("I", words))
    assert mpal.pen_rgb(0xFF123456) == (0x12, 0x34, 0x56)
    assert mpal.rgb_bytes([]) == b""
