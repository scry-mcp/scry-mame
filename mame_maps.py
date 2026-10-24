"""The screen maps on this server (`scry_core.screen_map`): an application's screens, each known
by the `scry-sig/1` signatures of regions that stay still on it, and the named controls on each.

ONE CAPTURE PER IDENTIFICATION. A screen is read the way `screen_signature` reads it, colours only
in one Lua chunk, so no pen is touched, and every candidate's regions are cut from that one read:
each read is a console round trip, and a map of many screens must not cost one per screen.

IDENTIFICATION ONLY. A board takes its inputs by port and field (`input`), so there is no pointer
for a control to be aimed at: the controls a map names are places to read, and `map_find` answers
where each is.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from scry_core import progress as mprogress
from scry_core import screen_map

import gdb_session as gs
import mame_envelope as menvelope
import mame_lua as mlua
import mame_palette as mpalette
import mame_running as running
import mame_screen as mscreen
import mame_state as st
from mame_state import STATE


def check_load_map(path: object = "", **_: Any) -> None:
    screen_map.check_path("path", path)


def check_save_map(dest: object = "", overwrite: object = False, **_: Any) -> None:
    screen_map.check_save(dest, overwrite)


def check_add_map(screen: object = "", match: object = None, controls: object = None,
                  **_: Any) -> None:
    screen_map.check_add(screen, match, controls)


def load_map(path: str) -> dict[str, Any]:
    """The body of `map_write(method="load")`: the file layer, in any state."""
    check_load_map(path)
    return menvelope.envelope(STATE.maps.load(path))


def save_map(dest: str, overwrite: bool) -> dict[str, Any]:
    """The body of `map_write(method="save")`: the two layers as one file, in any state."""
    check_save_map(dest, overwrite)
    return menvelope.envelope(STATE.maps.save(dest, overwrite))


def add_map(ses: gs.Session, scratch: Path, screen: str, match: list[list[int]],
            controls: list[dict[str, Any]] | None,
            progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of `map_write(method="add")`: the screen in front, signed off one capture."""
    check_add_map(screen, match, controls)
    common: dict[str, Any] = {}
    fields = STATE.maps.add(screen, match, controls, _reader(ses, scratch, common, progress))
    return running.stop_reply(ses, scratch, f"map_write add: {common['evaluated_by']}",
                              **st.merged(fields, common))


def map_find(ses: gs.Session, scratch: Path,
             progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of `map_find`: which mapped screen this is, off one capture."""
    common: dict[str, Any] = {}
    fields = STATE.maps.find(_reader(ses, scratch, common, progress), None)
    reply = running.stop_reply(ses, scratch, f"map_find: {common['evaluated_by']}",
                               **st.merged(fields, common))
    if STATE.maps.found is not None:
        # DATED AFTER THE READ: the capture can step the machine, so the stop the screen was read
        # at is the one this reply recorded, not the one before the call.
        STATE.maps.found = dataclasses.replace(STATE.maps.found,
                                               stop=reply.get("stop_seq"))
    return reply


def _reader(ses: gs.Session, scratch: Path, common: dict[str, Any],
            progress: mprogress.Progress) -> screen_map.Read:
    """`screen_signature`'s capture as the one read a map is matched against; the console's
    account it gave lands in `common` for the reply."""
    def read() -> screen_map.Grid:
        cap, said = mscreen.capture(ses, scratch, False, mlua.EVAL_WAIT_S, progress)
        common.update(said)
        return screen_map.Grid("pixel", cap.width, cap.height, mpalette.rgb_bytes(cap.colours))
    return read
