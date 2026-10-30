"""The screen maps of this server (`scry_core.screen_map`), matched against one capture.

A board takes inputs by port and field, so a control is a place to read, never a pointer target.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from scry_core import progress as mprogress
from scry_core import raster, screen_map
from scry_core import vocabulary as vocab

from scry_mame import advance, running
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import lua as mlua
from scry_mame import palette as mpalette
from scry_mame import screen as mscreen
from scry_mame import state as st
from scry_mame.state import STATE

#: What a `run_for` stop carries that a `run_to` reply has no field for.
RUN_FOR_ONLY = frozenset({"polls", "reads", "emulated_before_s", "emulated_after_s",
                          "frame_before", "frame_after", "cycles"})


def check_load_map(path: object = "", scale: object = 1, margin: object = None,
                   **_: Any) -> None:
    screen_map.check_path("path", path)
    screen_map.judged_view(scale, margin)


def check_save_map(dest: object = "", overwrite: object = False, **_: Any) -> None:
    screen_map.check_save(dest, overwrite)


def check_add_map(screen: object = "", match: object = None, controls: object = None,
                  cells: object = "", anchor: object = "", **_: Any) -> None:
    vocab.one_of("cells", cells, screen_map.CELLS_WORDS)
    screen_map.check_add(screen, match, controls, cells, anchor)


def load_map(path: str, scale: int = 1, margin: list[int] | None = None) -> dict[str, Any]:
    """The body of `screen_map_write(method="load")`: the file layer, in any state."""
    check_load_map(path, scale, margin)
    return menvelope.envelope(STATE.maps.load(path, scale, margin))


def save_map(dest: str, overwrite: bool) -> dict[str, Any]:
    """The body of `screen_map_write(method="save")`: the two layers as one file, in any state."""
    check_save_map(dest, overwrite)
    return menvelope.envelope(STATE.maps.save(dest, overwrite))


def add_map(ses: gs.Session, scratch: Path, screen: str, match: list[list[int]],
            controls: list[dict[str, Any]] | None, cells: str = "rgb", anchor: str = "",
            progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of `screen_map_write(method="add")`: the screen in front, signed off one capture."""
    check_add_map(screen, match, controls, cells, anchor)
    common: dict[str, Any] = {}
    fields = STATE.maps.add(screen, match, controls, _reader(ses, scratch, common, progress),
                            cells, anchor)
    return running.stop_reply(ses, scratch, f"screen_map_write add: {common['evaluated_by']}",
                              **st.merged(fields, common))


def screen_map_find(ses: gs.Session, scratch: Path,
             progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of `screen_map_find`: which mapped screen this is, off one capture."""
    common: dict[str, Any] = {}
    fields = STATE.maps.find(_reader(ses, scratch, common, progress), None)
    reply = running.stop_reply(ses, scratch, f"screen_map_find: {common['evaluated_by']}",
                               **st.merged(fields, common))
    if STATE.maps.found is not None:
        # the capture can step the machine: the stop is the reply's, not the one before the call
        STATE.maps.found = dataclasses.replace(STATE.maps.found,
                                               stop=reply.get("stop_seq"))
    return reply


def run_to_screen(ses: gs.Session, scratch: Path, screen: str, control: str, seconds: float,
                  progress: mprogress.Progress = mprogress.no_progress,
                  **run: Any) -> dict[str, Any]:
    """`run_to(screen=)`: a run to the screen's anchor, the arrival judged as its map says; a
    screen with no anchor is run to a frame at a time until the map names it."""
    common: dict[str, Any] = {}

    def refuse_inapplicable() -> None:
        if applied := [k for k in ("condition", "disarm_watches", "cpu") if run.get(k)]:
            raise st.Invalid("bad_argument", f"screen {screen!r} names no anchor, so it is run to "
                             f"a frame at a time, and {', '.join(applied)} has nothing to apply "
                             "to: leave it out")
    def advanced(reply: dict[str, Any]) -> dict[str, Any]:
        common.clear()          # only a read after the last advance moved the machine on
        return reply
    out = screen_map.run_to_screen(
        STATE.maps, screen, control, seconds,
        step=lambda left: advanced(advance.run_for(ses, scratch, 0, left, progress, frames=1)),
        run_to_anchor=lambda anchor: advanced(advance.run_to(ses, scratch, anchor, control,
                                                             seconds, progress, **run)),
        read=_reader(ses, scratch, common, progress), stop_seq=lambda r: r.get("stop_seq"),
        run_for_only=RUN_FOR_ONLY, frame_run=refuse_inapplicable,
        declare=advance.NO_CONTROL_DECLARE)
    if not common:
        return out              # nothing was captured, so the machine is where the run left it
    # The capture that judged the screen stepped the machine: the stop is the one after it.
    kept = {k: v for k, v in out.items() if k not in ("summary", "session", "cause")}
    refreshed = running.stop_reply(ses, scratch, f"run_to screen: {common['evaluated_by']}",
                                   **{**kept, **common})
    if STATE.maps.found is not None:
        STATE.maps.found = dataclasses.replace(STATE.maps.found, stop=refreshed.get("stop_seq"))
    return refreshed


def _reader(ses: gs.Session, scratch: Path, common: dict[str, Any],
            progress: mprogress.Progress) -> screen_map.Read:
    """`screen_signature`'s capture as the one read a map is matched against, with the pens
    `screen_view` recovers when a screen signed by index asks for them."""
    def read(indices: bool = False) -> screen_map.Grid:
        cap, said = mscreen.capture(ses, scratch, indices, mlua.EVAL_WAIT_S, progress)
        common.update(said)
        return screen_map.Grid("pixel", cap.width, cap.height, mpalette.rgb_bytes(cap.colours),
                               None if cap.indices is None else raster.index_cells(cap.indices))
    return read
