"""Section G of the live matrix: the conditioned film on m68k-dual."""


import contextlib
import hashlib
import json
import sys
from pathlib import Path

from bench_boards import (
    BLIT_HANDLER,
)
from live_harness import (
    boot,
    call,
    cell,
    ok,
    refused,
    said,
    section,
)

from scry_mame import capture as mcapture  # isort: skip
from matrix_edges import (  # noqa: E402
    by_ref,
)
from matrix_pairs import (  # noqa: E402
    FAULT,
    plant_fault,
    planted_at,
    raised,
)
from matrix_tools_by_state import (  # noqa: E402
    BLIT_TRIGGER,
    BLITTER,
    FILM,
)

G_CELLS = [
    "gfx_film arms on the blitter's strobe, its frames checkable, the strobe's writer named",
    "a run later it kept its frames, each passing MAME's rendering of it, the sheet inline",
    "every hit a kept frame lists is a row the capture on the same strobe recorded",
    "each kept frame's file is an indexed PNG of the screen, its sha256 the listing's",
    "the control: a value the strobe never carries keeps nothing, and says so with its frames",
    "the pc filter: a pc that never writes the strobe keeps nothing, the writer's own keeps",
    "a second film while one is held is refused naming the clear",
    "arming on a running machine is not_stopped; reading and clearing answer there",
    "the notifier's cost is reported, with the condition false",
    "and the films altered nothing",
    "a film whose tap raises counts its errors and marks no frame after the fault, where the "
    "same film unplanted marked frames over as many",
    "a header a reader holds open while the film publishes it costs the film no frame: every "
    "frame is judged, a failed publication is counted once, and the film reads whole after",
]


@section("G", "the conditioned film on m68k-dual: frames kept where a write happened", G_CELLS)
def block_g() -> None:
    t = G_CELLS
    boot()
    for frames in (100,) * 8 + (98,):
        call("run_for", frames=frames, seconds=10.0)
    before = call("status")["session"]["altering_writes"]
    call("watch_add", ref=BLITTER, mode="capture", length=32, trigger=BLIT_TRIGGER)
    armed = call("gfx_film", **{**FILM, "keep": 3, "frames": 8})
    cell(t[0], armed.get("armed_now") is True and armed["film"]["checked"] is True
         and armed.get("trigger_maps_to") == BLIT_HANDLER, said(armed))
    call("run_for", frames=10, seconds=10.0)
    film = call("gfx_film")
    cell(t[1], film.get("kept") == 3 and film.get("refused") == 0
         and (film.get("image") or {}).get("inline") is True, said(film))
    listing = json.loads(Path(str(film.get("listing_path"))).read_text())
    rows_path = next((w.get("rows_path") for w in call("declaration_list",
                                                       kind="watch").get("watches", [])
                      if w.get("ref") == BLITTER), "")
    rows = {(row.pc, row.data, row.frame) for row in mcapture.rows(Path(str(rows_path)))}
    hits = [(int(h["pc"], 16), int(h["value"], 16), h["counter"])
            for f in listing["frames"] for h in f["listed_hits"]]
    cell(t[2], bool(hits) and all(h in rows for h in hits),
         f"{len(hits)} hits, missing from the capture: {[h for h in hits if h not in rows][:3]}")
    folder = Path(listing["film"]["film_dir"])
    good = []
    for f in listing["frames"]:
        data = (folder / f["file"]).read_bytes()
        good.append(hashlib.sha256(data).hexdigest() == f["sha256"] and data[25] == 3
                    and data[16:24] == (336).to_bytes(4, "big") + (252).to_bytes(4, "big"))
    cell(t[3], len(good) == 3 and all(good), f"{good}")
    writer = listing["frames"][0]["listed_hits"][0]["pc"]
    call("gfx_film", clear=True)
    call("gfx_film", **{**FILM, "value": "0x1234", "frames": 6})
    call("run_for", frames=8, seconds=10.0)
    never = call("gfx_film")
    cell(t[4], never.get("state") == "finished" and never.get("kept") == 0
         and never.get("judged") == 6 and "nothing_kept" in never and "image" not in never
         and (never.get("film") or {}).get("value") == "0x1234",
         said(never))
    cost = never.get("cost", {})
    cell(t[8], cost.get("judge_s_per_frame", -1) >= 0 and "measured_by" in cost,
         f"{cost.get('judge_s_per_frame')} s a judged frame")
    call("gfx_film", clear=True)
    call("gfx_film", **{**FILM, "pc": "0x400", "frames": 4})
    call("run_for", frames=6, seconds=10.0)
    other = call("gfx_film")
    call("gfx_film", clear=True)
    call("gfx_film", **{**FILM, "pc": writer, "frames": 4})
    call("run_for", frames=6, seconds=10.0)
    own = call("gfx_film")
    cell(t[5], other.get("kept") == 0 and other.get("judged") == 4 and own.get("kept") == 2,
         f"pc 0x400: {said(other, 50)} / pc {writer}: {said(own, 50)}")
    again = call("gfx_film", **FILM)
    cell(t[6], refused(again, "bad_argument") and "clear=True" in str(again.get("message")),
         said(again))
    call("resume")
    running = call("gfx_film", **FILM)
    read = call("gfx_film")
    gone = call("gfx_film", clear=True)
    call("stop")
    cell(t[7], refused(running, "not_stopped") and ok(read) and read.get("kept") == 2
         and gone.get("cleared") is True and Path(own["film"]["film_dir"], "film.json").is_file(),
         f"{said(running, 40)} / {said(read, 40)} / {said(gone, 40)}")
    after = call("status")["session"]
    cell(t[9], after["altering_writes"] == before and after["altered"] is False,
         f"writes {before} -> {after['altering_writes']}, altered {after['altered']}")
    # `changed` reads the previous write first: with it unreadable, every write the film's tap
    # takes raises before it can mark a frame; the control counts the strobe's writes meanwhile.
    # The frame the plant lands in drops the marks it already had, so none is met from before it
    ctl = call("watch_add", ref=BLIT_TRIGGER, mode="count", length=2)
    armed = call("gfx_film", trigger=BLIT_TRIGGER, length=2, changed=True, keep=2, frames=60)
    call("run_for", frames=2, seconds=10.0)
    first_met = call("gfx_film").get("met", -1)
    # THE UNPLANTED CONTRAST: the same film over the same frames before the fault meets more, so
    # a `met` that stays put after the plant is the fault's doing and not a film that never meets
    call("run_for", frames=6, seconds=10.0)
    met = call("gfx_film").get("met", -1)
    at = planted_at(plant_fault("MCP_FILM", str(armed.get("tally_id")), (
        "t.prev, t.nhits, t.hits = nil, 0, {}\n"
        f'setmetatable(t, {{__index = function(_, k) if k == "prev" then error("{FAULT}") end '
        "end})"), f'_G.MCP_TALLY.items["{ctl.get("tally_id")}"].total'))
    call("run_for", frames=6, seconds=10.0)
    film = call("gfx_film")
    count, first = raised(film)
    grew = int(by_ref(call("declaration_list", kind="watch").get("watches")).get(BLIT_TRIGGER, {})
               .get("total", -1)) - at
    cell(t[10], at >= 0 and grew > 0 and count == grew and FAULT in first
         and 0 <= first_met < met and film.get("met") == met
         and "callbacks raised" in str(film.get("summary")),
         f"strobe writes since the plant {grew}, errors {count}, met {first_met} unplanted -> "
         f"{met}, then {film.get('met')} planted, first {first[:60]!r}")
    call("gfx_film", clear=True)
    call("declaration_clear", kind="watch", all=True)
    call("watch_add", ref=BLITTER, mode="capture", length=32, trigger=BLIT_TRIGGER)
    armed = call("gfx_film", **{**FILM, "keep": 3, "frames": 8})
    head = Path(str(armed["film"]["film_dir"])) / "film.txt"
    present = head.is_file()
    # a handle open for reading refuses the replacement of its file on Windows, and not on POSIX
    with head.open("rb") if present else contextlib.nullcontext():
        call("run_for", frames=10, seconds=10.0)
    call("run_for", frames=4, seconds=10.0)
    held = call("gfx_film")
    count, first = raised(held)
    counted_once = count == 1 and first != ""
    cell(t[11], present and held.get("state") == "finished" and held.get("judged") == 8
         and held.get("kept") == 3 and (counted_once if sys.platform == "win32" else count <= 0),
         f"{said(held, 90)}; errors {count} {first[:50]!r}")
    call("gfx_film", clear=True)
    call("declaration_clear", kind="watch", all=True)
