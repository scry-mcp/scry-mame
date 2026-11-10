"""How MAME's snapshot differs from the screen (`mismatch`), judged on m68k-dual's arming
capture (`fixtures/film/arm-m68k-dual.*`, whose snapshot IS its bare screen) with controlled
edits of the snapshot's words, so every case starts from a known equality and changes one
thing. A screen in direct colour, which has no pens, is a small one of its own.
"""

from __future__ import annotations

import gzip
from array import array
from pathlib import Path
from typing import Any

import pytest

from scry_mame import mismatch as mm  # noqa: E402
from scry_mame import screen as mscreen  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "film"
W, H = 336, 252
NO_PEN = 0x123457                  # a colour none of the capture's pens holds
PEN_OFF_SCREEN = 0x00FF00          # a pen's colour the screen does not show
BLOCK = [(x, y) for y in (0, 1) for x in (8, 9, 10)]   # 3x2 of one colour seen far beyond it
BLOCK_COLOUR = 0x2C1B1B


UNCOMPARED = {"available": False,
              "why": "the snapshot and the screen differ in size, so no pixel was compared"}


def _capture(tmp_path: Path) -> mscreen.Capture:
    """m68k-dual's arming capture, read by the parser the film arms with."""
    path = tmp_path / "screen.bin"
    path.write_bytes(gzip.decompress((FIX / "arm-m68k-dual-screen-bin.gz").read_bytes()))
    text = (FIX / "arm-m68k-dual.txt").read_text(errors="replace")
    return mscreen.parse_capture(text, path, {})


def _words(colours: list[int], alpha: int = 0xFF) -> bytes:
    return array("I", [(alpha << 24) | c for c in colours]).tobytes()


@pytest.fixture
def screen(tmp_path: Path) -> tuple[mscreen.Capture, list[int]]:
    cap = _capture(tmp_path)
    return cap, [c & mm.RGB for c in cap.colours]


def _measure(cap: mscreen.Capture, snap: list[int]) -> dict[str, Any]:
    got = mm.measure(cap, _words(snap), W, H)
    assert got is not None, "the edit left the snapshot equal to the screen"
    return got


def test_the_edits_start_from_a_snapshot_equal_to_the_screen(
    screen: tuple[mscreen.Capture, list[int]],
) -> None:
    cap, colours = screen
    snap = gzip.decompress((FIX / "arm-m68k-dual-snap-bin.gz").read_bytes())
    assert mm.colours(snap) == colours and mm.measure(cap, snap, W, H) is None
    pens = {p & mm.RGB for p in cap.pens}
    assert {colours[y * W + x] for x, y in BLOCK} == {BLOCK_COLOUR}
    assert colours.count(BLOCK_COLOUR) > len(BLOCK)
    assert NO_PEN not in pens and PEN_OFF_SCREEN in pens and PEN_OFF_SCREEN not in colours


def test_the_snapshots_alpha_is_not_compared(screen: tuple[mscreen.Capture, list[int]]) -> None:
    cap, colours = screen
    assert mm.measure(cap, _words(colours, alpha=0), W, H) is None


@pytest.mark.parametrize(("paint", "candidate", "in_pens"), [
    (NO_PEN, "overlay_or_artwork", False),
    (PEN_OFF_SCREEN, "frame_lag", True),
])
def test_a_block_that_differs_is_measured_and_named_by_its_rule(
    screen: tuple[mscreen.Capture, list[int]], paint: int, candidate: str, in_pens: bool,
) -> None:
    """The block's colour stays unchanged elsewhere, so one screen colour becomes two in the
    snapshot. In a colour no pen holds that is the overlay's mark; in a pen's colour, another
    picture's."""
    cap, colours = screen
    snap = list(colours)
    for x, y in BLOCK:
        snap[y * W + x] = paint
    got = _measure(cap, snap)
    assert got == {"screen_size": [W, H], "snapshot_size": [W, H], "differing_pixels": 6,
                   "screen_pixels": W * H, "bbox": [8, 0, 10, 1],
                   "snapshot_colours_are_pens": in_pens, "flip": "none",
                   "candidates": [candidate]}, got
    why = mm.why(got)
    assert why is not None and why.startswith("6 of 84672 pixels") and "[8, 0, 10, 1]" in why
    assert f"possible causes: {candidate} (see `mismatch`)" in why


def test_the_bbox_spans_every_differing_pixel_not_the_first_and_last(
    screen: tuple[mscreen.Capture, list[int]],
) -> None:
    cap, colours = screen
    snap = list(colours)
    snap[0 * W + 10] = snap[5 * W + 3] = snap[9 * W + 7] = NO_PEN
    assert _measure(cap, snap)["bbox"] == [3, 0, 10, 9]


def test_one_screen_colour_mapped_whole_to_another_is_a_colour_adjustment(
    screen: tuple[mscreen.Capture, list[int]],
) -> None:
    cap, colours = screen
    got = _measure(cap, [NO_PEN if c == BLOCK_COLOUR else c for c in colours])
    assert got["differing_pixels"] == colours.count(BLOCK_COLOUR)
    assert (got["snapshot_colours_are_pens"], got["flip"]) == (False, "none")
    assert got["candidates"] == ["colour_adjustment"], got


def test_two_screen_colours_drawn_as_one_are_no_colour_adjustment(
    screen: tuple[mscreen.Capture, list[int]],
) -> None:
    """Each screen colour still maps to one snapshot colour; it is the way back that fails, and a
    transform that merges two colours is not one the snapshot could be undone from."""
    cap, colours = screen
    other = next(c for c, _n in sorted(((c, colours.count(c)) for c in set(colours)),
                                       key=lambda cn: -cn[1]) if c != BLOCK_COLOUR)
    got = _measure(cap, [NO_PEN if c in (BLOCK_COLOUR, other) else c for c in colours])
    assert got["candidates"] == ["overlay_or_artwork"], got


@pytest.mark.parametrize("flip", ["x", "y", "xy"])
def test_a_mirrored_snapshot_is_an_orientation_and_says_which(
    screen: tuple[mscreen.Capture, list[int]], flip: str,
) -> None:
    cap, colours = screen
    rows = [colours[r * W:(r + 1) * W] for r in range(H)]
    if "x" in flip:
        rows = [row[::-1] for row in rows]
    if "y" in flip:
        rows = rows[::-1]
    mirrored = [c for row in rows for c in row]
    got = _measure(cap, mirrored)
    assert (got["flip"], got["candidates"]) == (flip, ["orientation"]), got
    mirrored[-1] = NO_PEN
    assert _measure(cap, mirrored)["flip"] == "none", "one pixel off in the last row is no mirror"


def test_a_snapshot_of_another_size_compares_nothing(
    screen: tuple[mscreen.Capture, list[int]],
) -> None:
    cap, _ = screen
    got = mm.measure(cap, bytes(4 * 672 * 504), 672, 504)
    assert got == {"screen_size": [W, H], "snapshot_size": [672, 504],
                   "differing_pixels": UNCOMPARED, "screen_pixels": W * H, "bbox": UNCOMPARED,
                   "snapshot_colours_are_pens": UNCOMPARED,
                   "flip": UNCOMPARED, "candidates": ["overlay_or_artwork"]}, got
    assert (mm.why(got) or "").startswith("MAME's snapshot here is 672x504 and the screen 336x252")


def _direct(colours: list[int], w: int, h: int) -> mscreen.Capture:
    return mscreen.Capture("t", w, h, 0, None, array("I", colours), None, [])


def test_a_screen_with_no_pens_leaves_the_pens_question_open_and_a_mirror_alone() -> None:
    cap = _direct([1, 2, 3, 4, 5, 6, 7, 8], 4, 2)
    got = mm.measure(cap, array("I", [4, 3, 2, 1, 8, 7, 6, 5]).tobytes(), 4, 2)
    assert got is not None and got["snapshot_colours_are_pens"]["available"] is False, got
    assert (got["flip"], got["candidates"]) == ("x", ["orientation"]), got


@pytest.mark.parametrize(("snap", "candidate"), [
    ([9, 2, 3, 4, 5, 6, 7, 8], "colour_adjustment"),
    ([1, 2, 3, 4, 5, 6, 7, 1], "overlay_or_artwork"),
])
def test_a_screen_with_no_pens_is_judged_by_its_colour_map_alone(
    snap: list[int], candidate: str,
) -> None:
    got = mm.measure(_direct([1, 2, 3, 4, 5, 6, 7, 8], 4, 2), array("I", snap).tobytes(), 4, 2)
    assert got is not None and got["candidates"] == [candidate], got
