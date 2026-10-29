from __future__ import annotations

import random
from array import array

from scry_mame import palette as mpal


def test_one_pen_to_rgb_reads_every_word_as_the_shifts_would() -> None:
    """Byte slicing matches the shift arithmetic."""
    rng = random.Random(0)
    words = [0xFF123456, 0x00ABCDEF, 0, 0xFFFFFFFF] + [rng.getrandbits(32) for _ in range(500)]
    want = b"".join(bytes(((w >> 16) & 0xFF, (w >> 8) & 0xFF, w & 0xFF)) for w in words)
    assert mpal.rgb_bytes(words) == want == mpal.rgb_bytes(array("I", words))
    assert mpal.pen_rgb(0xFF123456) == (0x12, 0x34, 0x56)
    assert mpal.rgb_bytes([]) == b""
