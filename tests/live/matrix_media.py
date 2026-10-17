"""Section Y of the live matrix: the media layer's scenarios, each asked twice over one answer.

THE PAIR IS THE POINT. A new tool has no "before" of its own, so each scenario is answered the
way a session answers it with the tools it had (`run_for` and `screen_view` per frame, a picture
looked at) and the new way (`series_capture` and `region_track`, `screen_signature`), from the
same machine state, and both must reach the same answer. What each way cost (calls, the text
units of its replies, the visual tokens of the pictures they attached) is in the cell's detail,
which is where the scenario table is read from.

S1, "which frames of N changed in region R": the hand way decodes each frame's PNG and compares
its pixels here, with this file's own comparison; the new way is the server's. Both run from
one saved state, so the frames are the same emulation, and the changes are compared by their
offset from the first frame, which holds whether or not a load restores the frame counter.
S2, "is this screen the golden": the golden is a PNG of the screen at one stop; the hand way
looks at the screen again and compares pixels, the new way compares one string. Its control is
the same question sixty frames later, which must come out no.

    uv run python tests/live/matrix_media.py
"""

import json
from pathlib import Path

from bench_boards import m68k_dual_missing
from live_harness import (
    PENDING,
    WAIT_CEILING_S,
    Board,
    boards_cover,
    boot,
    call,
    cell,
    fresh,
    fresh_state,
    ok,
    run_boards,
    said,
    section,
)
from scry_core import png, raster, traffic

#: Where S1 starts, how many frames it reads and the region asked about: m68k-dual's boot
#: repaints the screen from about frame 24, a frame at a time, so the screen is the region and
#: the run starts just before it.
S1_FROM = 20
S1_FRAMES = 12
S1_CROP: list[int] | None = None
#: How far S2's control moves the machine from the golden's stop: two of the boot's later
#: repaints are thirty frames apart and alike, so sixty.
S2_CONTROL_FRAMES = 60

Y_TITLE = "the media layer: each scenario the hand way and the new way, over one answer"
Y = [
    "m68k-dual S1 hand: run_for and screen_view per frame find which frames changed in the crop",
    "m68k-dual S1 new: series_capture and region_track find the same frames, with no picture",
    "m68k-dual S1 cost: the new way takes fewer calls and attaches no picture",
    "m68k-dual S2 hand: screen_view attaches the screen and its pixels equal the golden's",
    "m68k-dual S2 new: screen_signature equals the golden's signature, and differs 60 frames on",
    "m68k-dual S2 cost: the new way attaches no picture",
]


def _cost(since: int) -> dict[str, int]:
    """Calls, text units and image tokens of the replies recorded since `since`."""
    replies = [p["reply"] for p in PENDING[since:]]
    return {"calls": len(replies), "units": sum(traffic.json_units(r) for r in replies),
            "image_tokens": sum(traffic.image_tokens(r) for r in replies)}


def _changes(pictures: list[bytes]) -> list[int]:
    """The offsets, from the first picture, of each one whose pixels differ from the one
    before: this file's own comparison, of the decoded bytes."""
    return [i for i in range(1, len(pictures)) if pictures[i] != pictures[i - 1]]


def _kept(manifest: str) -> list[tuple[png.Raster, str]]:
    """Each frame of a series as its PNG decodes, beside the signature its row says."""
    folder = Path(manifest).parent
    rows = json.loads(Path(manifest).read_text(encoding="utf-8"))["frames"]
    return [(png.decode((folder / r["path"]).read_bytes()), r["signature"]) for r in rows]


def _y_m68k_dual(t: list[str]) -> None:
    boot()
    call("run_for", frames=S1_FROM, seconds=WAIT_CEILING_S)
    state = fresh_state()
    saved = call("state_save", name=state)
    # S1, the hand way.
    start = len(PENDING)
    pictures: list[bytes] = []
    for _ in range(S1_FRAMES):
        call("run_for", frames=1, seconds=10.0)
        view = call("screen_view", crop=S1_CROP, scale=1)
        if ok(view):
            # In the colours shown, as the series stores them: two pens of one colour are one.
            pictures.append(raster.rgb(png.decode(Path(view["image"]["path"]).read_bytes())))
    hand = _changes(pictures)
    hand_cost = _cost(start)
    cell(t[0], ok(saved) and len(pictures) == S1_FRAMES and bool(hand),
         f"changes at offsets {hand}; cost {hand_cost}")
    # S1, the new way, from the same state.
    loaded = call("state_load", name=state)
    start = len(PENDING)
    # The hand way's first picture was the frame after the saved one; the series' first is the
    # frame after the loaded one, whatever the counter reads after a load.
    first = call("screen_signature").get("frame_screen", 0) + 1
    series = call("series_capture", first=first, last=first + S1_FRAMES - 1, crop=S1_CROP,
                  seconds=WAIT_CEILING_S)
    track = (call("region_track", manifest=series["manifest"], measure="changed_pixels")
             if ok(series) else series)
    new = [f - first for f, _ in track.get("transitions", [])] if ok(track) else []
    new_cost = _cost(start)
    # The series' frames ARE the hand way's: the same pixels, and each row signed as its picture
    # is. Which frames changed is not enough, a consistent wrong colour moves no change.
    kept = _kept(series["manifest"]) if ok(series) else []
    same = len(kept) == len(pictures) and all(
        raster.rgb(picture) == hand_rgb and signature == raster.picture_signature(picture)
        for (picture, signature), hand_rgb in zip(kept, pictures, strict=False))
    cell(t[1], ok(loaded) and ok(track) and bool(hand) and new == hand and same
         and new_cost["image_tokens"] == 0,
         f"changes at offsets {new} (hand {hand}), pixels and signatures as the hand way's "
         f"{same}; cost {new_cost}; {said(track)}")
    # Cheaper only counts when the new way answered: a refused series is one call too.
    cell(t[2], ok(series) and ok(track) and new_cost["calls"] < hand_cost["calls"]
         and new_cost["image_tokens"] == 0 < hand_cost["image_tokens"],
         f"hand {hand_cost}, new {new_cost}")
    # S2: the golden is the screen at this stop.
    golden = fresh(".png")
    made = call("screen_view", scale=1, dest=golden)
    want = png.decode(Path(golden).read_bytes()) if ok(made) else None
    start = len(PENDING)
    look = call("screen_view", scale=1)
    hand_ok = (want is not None and ok(look) and look["image"].get("inline") is True
               and png.decode(Path(look["image"]["path"]).read_bytes()).pixels == want.pixels)
    hand_cost = _cost(start)
    cell(t[3], hand_ok, f"cost {hand_cost}; {said(look)}")
    start = len(PENDING)
    sig = call("screen_signature")
    new_cost = _cost(start)
    golden_sig = raster.picture_signature(want) if want is not None else None
    call("run_for", frames=S2_CONTROL_FRAMES, seconds=WAIT_CEILING_S)
    later = call("screen_signature")
    cell(t[4], ok(sig) and sig.get("signature") == golden_sig
         and ok(later) and later.get("signature") != golden_sig,
         f"golden {golden_sig}, now {sig.get('signature')}, "
         f"{S2_CONTROL_FRAMES} frames on {later.get('signature')}; cost {new_cost}")
    cell(t[5], new_cost["image_tokens"] == 0 < hand_cost["image_tokens"],
         f"hand {hand_cost}, new {new_cost}")
    call("close")


Y_BOARDS = (Board(_y_m68k_dual, (0, 1, 2, 3, 4, 5), m68k_dual_missing),)
boards_cover("Y_BOARDS", Y, Y_BOARDS)


def register_y() -> None:
    """Register section Y with the matrix: after every section registered before it."""
    section("Y", Y_TITLE, Y)(lambda: run_boards(Y, Y_BOARDS))


if __name__ == "__main__":
    from live_harness import run_sections
    register_y()
    run_sections("SECTION Y")
