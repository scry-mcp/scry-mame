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

import gdb_session as gs
import mame_advance as advance
import mame_envelope as menvelope
import mame_lua as mlua
import mame_palette as mpalette
import mame_running as running
import mame_screen as mscreen
import mame_state as st
from mame_state import STATE


def check_load_map(path: object = "", scale: object = 1, margin: object = None,
                   **_: Any) -> None:
    screen_map.check_path("path", path)
    screen_map.view(scale, margin)


def check_save_map(dest: object = "", overwrite: object = False, **_: Any) -> None:
    screen_map.check_save(dest, overwrite)


def check_add_map(screen: object = "", match: object = None, controls: object = None,
                  cells: object = "", **_: Any) -> None:
    vocab.one_of("cells", cells, screen_map.CELLS_WORDS)
    screen_map.check_add(screen, match, controls, cells)


def load_map(path: str, scale: int = 1, margin: list[int] | None = None) -> dict[str, Any]:
    """The body of `screen_map_write(method="load")`: the file layer, in any state."""
    check_load_map(path, scale, margin)
    return menvelope.envelope(STATE.maps.load(path, scale, margin))


def save_map(dest: str, overwrite: bool) -> dict[str, Any]:
    """The body of `screen_map_write(method="save")`: the two layers as one file, in any state."""
    check_save_map(dest, overwrite)
    return menvelope.envelope(STATE.maps.save(dest, overwrite))


def add_map(ses: gs.Session, scratch: Path, screen: str, match: list[list[int]],
            controls: list[dict[str, Any]] | None, cells: str = "rgb",
            progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of `screen_map_write(method="add")`: the screen in front, signed off one capture."""
    check_add_map(screen, match, controls, cells)
    common: dict[str, Any] = {}
    fields = STATE.maps.add(screen, match, controls, _reader(ses, scratch, common, progress),
                            cells)
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
    """`run_to(screen=)`: a run to the screen's anchor, the arrival judged as its map says."""
    reply = advance.run_to(ses, scratch, STATE.maps.anchor(screen), control, seconds, progress,
                           **run)
    common: dict[str, Any] = {}
    out = screen_map.at_anchor(STATE.maps, screen, reply, _reader(ses, scratch, common, progress),
                               reply.get("stop_seq"))
    if not common:
        return out              # nothing was captured, so the machine is where the run left it
    # The capture that judged the screen stepped the machine: the stop is the one after it.
    kept = {k: v for k, v in out.items() if k not in ("summary", "session")}
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
