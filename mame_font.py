"""A 5x7 bitmap font for the labels a picture carries, drawn at an integer scale.

WHY PIXELS AND NOT A CAPTION. A contact sheet shows many frames in one picture, and each cell has
to say which frame it is, where the model and a person both look: in the picture. The glyphs are
the classic 5x7 matrix, enough to be read at twice their size without a font file or a library,
and each one differs from every other, which is what lets a test read a label back off the PNG
instead of trusting the string the writer meant to draw.

THE ALPHABET IS WHAT THE LABELS SAY and no more: hex digits, the letters of a film's `FRAME`,
`HITS` and `PC` and of a sweep's candidates (`S1C3`, `4BPP 16X16`, `PLANAR CELLS DOWN`), `=` and
the space. A character outside it is a programming error, never a blank.
"""

from __future__ import annotations

GLYPH_W, GLYPH_H = 5, 7

GLYPHS: dict[str, tuple[str, ...]] = {
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "=": (".....", ".....", "#####", ".....", "#####", ".....", "....."),
    " ": (".....",) * GLYPH_H,
}


def advance(scale: int) -> int:
    """How far one character moves the pen: the glyph and one column of space, scaled."""
    return (GLYPH_W + 1) * scale


def line_height(scale: int) -> int:
    """How far one line moves the pen down: the glyph and one row of space, scaled."""
    return (GLYPH_H + 1) * scale


def width(text: str, scale: int) -> int:
    """The pixels `text` covers across, without the space after its last glyph."""
    return max(len(text) * advance(scale) - scale, 0)


def draw(px: bytearray, stride_px: int, text: str, x: int, y: int, scale: int,
         rgb: tuple[int, int, int]) -> None:
    """Draw `text` into `px`, an RGB picture `stride_px` pixels wide, its top left at (`x`, `y`),
    each glyph pixel a `scale` x `scale` square of `rgb`; the background is left as it is."""
    colour = bytes(rgb)
    for i, ch in enumerate(text):
        glyph = GLYPHS.get(ch)
        if glyph is None:
            raise ValueError(f"{ch!r} is not in the label font's alphabet")
        left = x + i * advance(scale)
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit != "#":
                    continue
                for dy in range(scale):
                    at = ((y + gy * scale + dy) * stride_px + left + gx * scale) * 3
                    px[at:at + 3 * scale] = colour * scale
