"""How MAME's snapshot at a stop differs from the screen a film reads, with the one cause
each rule leaves standing named as a candidate and none asserted.

It classifies and never diagnoses: an overlay drawn in pen colours leaves another picture's
mark. What each field and candidate means is docs/reference/timeline.md's, in the `gfx_film` section.
"""

from __future__ import annotations

from array import array
from typing import Any

from scry_core import prose
from scry_core.reply_contract import unavailable

from scry_mame import screen as mscreen

RGB = 0xFFFFFF             # a colour word without its alpha
FLIPS = (("x", True, False), ("y", False, True), ("xy", True, True))


def colours(snap: bytes) -> list[int]:
    """MAME's snapshot words as colours: its alpha is not the pens', so only RGB is compared."""
    return [c & RGB for c in array("I", snap)]


def differing(shown: list[int], got: list[int]) -> list[int]:
    """The indices, ascending, of the pixels whose colours differ."""
    return [i for i, (a, b) in enumerate(zip(shown, got, strict=True)) if a != b]


def _flip(shown: list[int], got: list[int], w: int, h: int) -> str:
    """The first of `FLIPS` under which the screen equals the snapshot exactly, else `none`."""
    rows = [shown[r * w:(r + 1) * w] for r in range(h)]
    for name, fx, fy in FLIPS:
        if all((row[::-1] if fx else row) == got[r * w:(r + 1) * w]
               for r, row in enumerate(rows[::-1] if fy else rows)):
            return name
    return "none"


def _one_to_one(shown: list[int], got: list[int]) -> bool:
    """Every screen colour maps to one snapshot colour and back."""
    ahead: dict[int, int] = {}
    back: dict[int, int] = {}
    return all(ahead.setdefault(a, b) == b and back.setdefault(b, a) == a
               for a, b in zip(shown, got, strict=True))


def measure(cap: mscreen.Capture, snap: bytes, snap_w: int,
            snap_h: int) -> dict[str, Any] | None:
    """The `mismatch` of the snapshot `snap` (`snap_w` x `snap_h` words, which the caller has
    checked) against the screen `cap`, or None when it is the bare screen."""
    w, h = cap.width, cap.height
    uncompared = unavailable("the snapshot and the screen differ in size, so no pixel was "
                                "compared")
    out: dict[str, Any] = {"screen_size": [w, h], "snapshot_size": [snap_w, snap_h],
                           "differing_pixels": uncompared, "screen_pixels": w * h,
                           "bbox": uncompared, "snapshot_colours_are_pens": uncompared,
                           "flip": uncompared, "candidates": ["overlay_or_artwork"]}
    if (snap_w, snap_h) != (w, h):
        return out
    shown = [c & RGB for c in cap.colours]
    got = colours(snap)
    apart = differing(shown, got)
    if not apart:
        return None
    pens = {p & RGB for p in cap.pens}
    in_pens: bool | dict[str, Any] = (all(got[i] in pens for i in apart) if pens else
                                      unavailable("the screen holds no pens to compare with"))
    flip = _flip(shown, got, w, h)
    if flip != "none":
        candidate = "orientation"
    elif in_pens is True:
        candidate = "frame_lag"
    elif _one_to_one(shown, got):
        candidate = "colour_adjustment"
    else:
        candidate = "overlay_or_artwork"
    xs = [i % w for i in apart]
    out.update(differing_pixels=len(apart),
               bbox=[min(xs), apart[0] // w, max(xs), apart[-1] // w],
               snapshot_colours_are_pens=in_pens, flip=flip, candidates=[candidate])
    return out


def why(mismatch: dict[str, Any] | None) -> str | None:
    """`check_why`: what the measurement found, in one line, or None when nothing differs."""
    if mismatch is None:
        return None
    (w, h), (sw, sh) = mismatch["screen_size"], mismatch["snapshot_size"]
    what = (f"MAME's snapshot here is {sw}x{sh} and the screen {w}x{h}"
            if isinstance(mismatch["differing_pixels"], dict) else
            f"{mismatch['differing_pixels']} of "
            f"{prose.counted(mismatch['screen_pixels'], 'pixel')} of MAME's snapshot differ from "
            f"the screen at the stop, in {mismatch['bbox']}")
    return (f"{what}; possible causes: {', '.join(mismatch['candidates'])} (see `mismatch`); so "
            "no kept frame is checked against MAME's own rendering of it, and its picture rests "
            "on the double buffer's law alone")
