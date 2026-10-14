"""A contact sheet: pictures of one size on one page, each under its own label, as many as fit the
inline ceiling unenlarged; the page is then enlarged by a whole factor where one fits.

WHY WHOLE CELLS AND PAGES. A sheet that shrank its cells to fit would resample them, the
plausible wrong picture `mame_picture` refuses to attach; so a page holds the largest grid of
whole cells the ceiling takes, and the caller pages through the rest. A cell is as wide as the
widest label of every cell on every page, so the pages of one sheet lay out alike and a cell is
found at the same place whichever page it is on.
"""

from __future__ import annotations

from dataclasses import dataclass

import mame_font as font
import mame_picture as picture
import mame_png as png

# Each label in the 5x7 font at twice its size, over its picture, cells a gap apart on dark.
LABEL_SCALE = 2
LABEL_PAD = 4
CELL_GAP = 4
GROUND = (24, 24, 24)
INK = (255, 255, 255)


@dataclass(frozen=True)
class Layout:
    """Where everything of a sheet goes: each cell's picture size, its label lines, its size."""

    picture: tuple[int, int]
    lines: int
    cell: tuple[int, int]

    def label_origin(self, col: int, row: int) -> tuple[int, int]:
        """Where the first label line of the cell at (`col`, `row`) starts."""
        return (CELL_GAP + col * (self.cell[0] + CELL_GAP) + LABEL_PAD,
                CELL_GAP + row * (self.cell[1] + CELL_GAP) + LABEL_PAD)

    def picture_origin(self, col: int, row: int) -> tuple[int, int]:
        """Where the picture of the cell at (`col`, `row`) starts, under its label."""
        return (CELL_GAP + col * (self.cell[0] + CELL_GAP),
                CELL_GAP + row * (self.cell[1] + CELL_GAP) + self.label_height())

    def label_height(self) -> int:
        return self.lines * font.line_height(LABEL_SCALE) + 2 * LABEL_PAD

    def size(self, cols: int, rows: int) -> tuple[int, int]:
        """A page of `cols` x `rows` cells."""
        return (cols * self.cell[0] + (cols + 1) * CELL_GAP,
                rows * self.cell[1] + (rows + 1) * CELL_GAP)


def layout(picture_size: tuple[int, int], labels: list[tuple[str, ...]]) -> Layout:
    """The layout of a sheet whose pictures are `picture_size` and whose cells carry `labels`
    (every cell's, not one page's)."""
    lines = max((len(lab) for lab in labels), default=0)
    widest = max((font.width(line, LABEL_SCALE) for lab in labels for line in lab), default=0)
    lay = Layout(picture_size, lines, (0, 0))
    return Layout(picture_size, lines, (max(picture_size[0], widest + 2 * LABEL_PAD),
                                        lay.label_height() + picture_size[1]))


def page_shape(lay: Layout, n: int) -> tuple[int, int]:
    """Columns and rows of the page holding the most of `n` cells inside the inline ceiling; one
    cell when even one does not fit (it is then written and not attached)."""
    best = (1, 1)
    for cols in range(1, n + 1):
        if not picture.within_ceiling(*lay.size(cols, 1)):
            break
        rows = 1
        while rows < -(-n // cols) and picture.within_ceiling(*lay.size(cols, rows + 1)):
            rows += 1
        # a tie goes to the wider page: cells read left to right before they wrap
        if min(cols * rows, n) >= min(best[0] * best[1], n):
            best = (cols, rows)
    return best


def compose(lay: Layout, cells: list[tuple[tuple[str, ...], bytes]]) -> png.Raster:
    """One page: each cell's label lines and its RGB picture, laid out as `page_shape` says."""
    cols, rows = page_shape(lay, len(cells))
    width, height = lay.size(cols, rows)
    px = bytearray(bytes(GROUND) * (width * height))
    pw, ph = lay.picture
    for i, (lines, rgb) in enumerate(cells):
        col, row = i % cols, i // cols
        lx, ly = lay.label_origin(col, row)
        for n, line in enumerate(lines):
            font.draw(px, width, line, lx, ly + n * font.line_height(LABEL_SCALE), LABEL_SCALE,
                      INK)
        left, top = lay.picture_origin(col, row)
        for yy in range(ph):
            at = ((top + yy) * width + left) * 3
            px[at:at + 3 * pw] = rgb[yy * pw * 3:(yy + 1) * pw * 3]
    return png.Raster(width, height, bytes(px))
