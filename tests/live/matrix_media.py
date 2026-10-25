"""Section Y of the live matrix: each media scenario answered the old way and the new way.

Both ways start from the same machine state and must reach the same answer; the cell detail
carries what each cost (calls, text units, image tokens).

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
    free_boards_missing,
    free_boot,
    fresh,
    fresh_state,
    ok,
    run_boards,
    said,
    section,
    zips_missing,
)
from scry_core import png, raster, traffic

#: m68k-dual's boot repaints the screen from about frame 24, a frame at a time.
S1_FROM = 20
S1_FRAMES = 12
S1_CROP: list[int] | None = None
#: Two of the boot's later repaints are thirty frames apart and alike, so the control goes sixty.
S2_CONTROL_FRAMES = 60

Y_TITLE = "the media layer: each scenario the hand way and the new way, over one answer"
Y = [
    "m68k-dual S1 hand: run_for and screen_view per frame find which frames changed in the crop",
    "m68k-dual S1 new: series_capture and image_compare region find the same frames, with no "
    "picture",
    "m68k-dual S1 cost: the new way takes fewer calls and attaches no picture",
    "m68k-dual S2 hand: screen_view attaches the screen and its pixels equal the golden's",
    "m68k-dual S2 new: screen_signature equals the golden's signature, and differs 60 frames on",
    "m68k-dual S2 cost: the new way attaches no picture",
    "gridlee, no view asked: `start` says `native` and lists the layout's views, and a "
    "snapshot is the screen alone, its pixels screen_view's",
    "gridlee, a view asked by a prefix in another case: `start` and every capture name the "
    "view MAME took, the layout's",
    "gridlee, that view's snapshot differs from the native one exactly inside the layout's box",
]
#: A box of a colour no game paints, over the screen at its own size (`_layout`).
VIEW_NAME, BOX = "Scry Test Box", (16, 24, 32, 20)


def _cost(since: int) -> dict[str, int]:
    """Calls, text units and image tokens of the replies recorded since `since`."""
    replies = [p["reply"] for p in PENDING[since:]]
    return {"calls": len(replies), "units": sum(traffic.json_units(r) for r in replies),
            "image_tokens": sum(traffic.image_tokens(r) for r in replies)}


def _changes(pictures: list[bytes]) -> list[int]:
    """Offsets of the pictures whose bytes differ from the one before."""
    return [i for i in range(1, len(pictures)) if pictures[i] != pictures[i - 1]]


def _kept(manifest: str) -> list[tuple[png.Raster, str]]:
    """Each frame of a series decoded, beside its row's signature."""
    folder = Path(manifest).parent
    rows = json.loads(Path(manifest).read_text(encoding="utf-8"))["frames"]
    return [(png.decode((folder / r["path"]).read_bytes()), r["signature"]) for r in rows]


def _y_m68k_dual(t: list[str]) -> None:
    boot()
    call("run_for", frames=S1_FROM, seconds=WAIT_CEILING_S)
    state = fresh_state()
    saved = call("state_write", method="save", name=state)
    start = len(PENDING)
    pictures: list[bytes] = []
    for _ in range(S1_FRAMES):
        call("run_for", frames=1, seconds=10.0)
        view = call("screen_view", crop=S1_CROP, scale=1)
        if ok(view):
            # Colours as the series stores them: two pens of one colour are one.
            pictures.append(raster.rgb(png.decode(Path(view["image"]["path"]).read_bytes())))
    hand = _changes(pictures)
    hand_cost = _cost(start)
    cell(t[0], ok(saved) and len(pictures) == S1_FRAMES and bool(hand),
         f"changes at offsets {hand}; cost {hand_cost}")
    loaded = call("state_write", method="load", name=state)
    start = len(PENDING)
    # The counter may not survive a load, so the first frame is read after it.
    first = call("screen_signature").get("frame_screen", 0) + 1
    series = call("series_capture", first=first, last=first + S1_FRAMES - 1, crop=S1_CROP,
                  seconds=WAIT_CEILING_S)
    track = (call("image_compare", method="region", manifest=series["manifest"],
                  measure="changed_pixels")
             if ok(series) else series)
    new = [f - first for f, _ in track.get("transitions", [])] if ok(track) else []
    new_cost = _cost(start)
    # Changed offsets alone would miss a consistently wrong colour, so pixels and signatures too.
    kept = _kept(series["manifest"]) if ok(series) else []
    same = len(kept) == len(pictures) and all(
        raster.rgb(picture) == hand_rgb and signature == raster.picture_signature(picture)
        for (picture, signature), hand_rgb in zip(kept, pictures, strict=False))
    cell(t[1], ok(loaded) and ok(track) and bool(hand) and new == hand and same
         and new_cost["image_tokens"] == 0,
         f"changes at offsets {new} (hand {hand}), pixels and signatures as the hand way's "
         f"{same}; cost {new_cost}; {said(track)}")
    # A refused series is one call too, so cheaper counts only if it answered.
    cell(t[2], ok(series) and ok(track) and new_cost["calls"] < hand_cost["calls"]
         and new_cost["image_tokens"] == 0 < hand_cost["image_tokens"],
         f"hand {hand_cost}, new {new_cost}")
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


def _layout(art: Path, width: int, height: int) -> None:
    """Write `art/gridlee/default.lay`: the screen plus `BOX` painted over it."""
    x, y, w, h = BOX
    (art / "gridlee").mkdir(parents=True)
    (art / "gridlee" / "default.lay").write_text(
        '<?xml version="1.0"?>\n<mamelayout version="2">\n'
        '<element name="scrybox"><rect><color red="1.0" green="0.0" blue="1.0"/></rect>'
        '</element>\n'
        f'<view name="{VIEW_NAME}">\n'
        f'<screen index="0"><bounds x="0" y="0" width="{width}" height="{height}"/></screen>\n'
        f'<element ref="scrybox"><bounds x="{x}" y="{y}" width="{w}" height="{h}"/></element>\n'
        '</view>\n</mamelayout>\n', encoding="utf-8")


def _colours(pic: png.Raster) -> list[tuple[int, ...]]:
    """Each pixel's colour, row by row, indexed or RGB."""
    if pic.palette is not None:
        return [pic.palette[i] for i in pic.pixels]
    return [tuple(pic.pixels[k:k + 3]) for k in range(0, len(pic.pixels), 3)]


def _snap() -> png.Raster | None:
    shot = call("snapshot")
    return png.decode(Path(str(shot["path"])).read_bytes()) if ok(shot) else None


def _y_gridlee_views(t: list[str]) -> None:
    art = Path(fresh("-art"))
    art.mkdir()
    free_boot("gridlee", ["gridfnla.bin"], "0xa000", ini_extra=f"artpath {art}\n")
    screens = call("machine_map", sections=["screens"]).get("screens") or [{}]
    width, height = int(screens[0].get("width", 0)), int(screens[0].get("height", 0))
    native = _snap()
    look = call("screen_view", scale=1)
    pens = png.decode(Path(look["image"]["path"]).read_bytes()) if ok(look) else None
    call("close")
    _layout(art, width, height)
    started = free_boot("gridlee", ["gridfnla.bin"], "0xa000", ini_extra=f"artpath {art}\n")
    # The default view must ignore the layout the set ships.
    shipped = _snap()
    cell(t[6], started.get("view") == "native" and VIEW_NAME in (started.get("views") or [])
         and native is not None and pens is not None and shipped is not None
         and _colours(native) == _colours(pens) == _colours(shipped)
         and (native.width, native.height) == (width, height),
         f"view {started.get('view')}, views {started.get('views')}, native "
         f"{native and (native.width, native.height)}, with the layout "
         f"{shipped and (shipped.width, shipped.height)}, screen {width}x{height}")
    call("close")
    named = free_boot("gridlee", ["gridfnla.bin"], "0xa000", ini_extra=f"artpath {art}\n",
                      view=VIEW_NAME[:8].lower())
    shot = call("snapshot")
    boxed = png.decode(Path(str(shot["path"])).read_bytes()) if ok(shot) else None
    cell(t[7], named.get("view") == VIEW_NAME and shot.get("view") == VIEW_NAME,
         f"start {named.get('view')}, snapshot {shot.get('view')}")
    x, y, w, h = BOX
    inside = {(i, j) for j in range(y, y + h) for i in range(x, x + w)}
    differs: set[tuple[int, int]] = set()
    if native is not None and boxed is not None and (native.width, native.height) == (
            boxed.width, boxed.height):
        a, b = _colours(native), _colours(boxed)
        differs = {(k % native.width, k // native.width) for k in range(len(a)) if a[k] != b[k]}
    cell(t[8], bool(differs) and differs == inside,
         f"{len(differs)} pixels differ, {len(inside)} in the box; sizes "
         f"{native and (native.width, native.height)} and {boxed and (boxed.width, boxed.height)}")
    call("close")


def _gridlee_missing() -> str:
    return free_boards_missing() or zips_missing("gridlee")


Y_BOARDS = (Board(_y_m68k_dual, (0, 1, 2, 3, 4, 5), m68k_dual_missing),
            Board(_y_gridlee_views, (6, 7, 8), _gridlee_missing))
boards_cover("Y_BOARDS", Y, Y_BOARDS)


def register_y() -> None:
    """Register section Y after every section registered before it."""
    section("Y", Y_TITLE, Y)(lambda: run_boards(Y, Y_BOARDS))


if __name__ == "__main__":
    from live_harness import run_sections
    register_y()
    run_sections("SECTION Y")
