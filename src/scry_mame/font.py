"""A 5x7 bitmap font for labels drawn into a picture, at an integer scale.

Pixels rather than a caption so a test can read a label back off the PNG. The alphabet is what
the labels say (hex digits, film and sweep words, `=`, space); any other character raises.
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
    """Draw `text` into the RGB picture `px` (`stride_px` wide) at (`x`, `y`), background kept."""
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
