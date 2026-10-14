"""WHAT A TOOL'S DOCSTRING STATES THAT THE CODE ALREADY KNOWS, filled at registration.

A tool's description is the one text a client reads before calling it, so its numbers are not
typed into it: each `{NAME}` placeholder is replaced by the constant that enforces it, and the
sentences several tools share are written once here. `server.tool` calls `filled` on every
docstring it registers, and a placeholder nothing fills fails the import.
"""

from __future__ import annotations

import re

import mame_advance as advance
import mame_blits as mblits
import mame_comment_file as mcomment_file
import mame_declarations as dec
import mame_draft as mdraft
import mame_film as mfilm
import mame_gfx as mgfx
import mame_inputs as inputs
import mame_layout as ml
import mame_lexer as lexer
import mame_locate as mlocate
import mame_lua as mlua
import mame_palette as mpalette
import mame_picture as picture
import mame_ramdac as mramdac
import mame_read as read
import mame_savestates as savestates
import mame_scan as mscan
import mame_screen as mscreen
import mame_sequence as sequence
import mame_state as st
import mame_sweep as msweep
import mame_trace as mtrace
import mame_transport as transport
import mame_watches as watches
import mame_write as mwrite

# THE SENTENCES THE TOOL DOCSTRINGS SHARE, each filled into the placeholder of its own name
# (`{NEEDS_STOPPED}`, ...; `DOC_VALUES` below is the whole list).
NEEDS_STOPPED = (
    "Needs the machine STOPPED: on a running one the reply is `status: INVALID` "
    "(`not_stopped`) with `last_stop` and `answers_while_running`"
)
STOP_FIELDS = (
    "the survey: `how`, `stop_seq`, `cpu` (the stop's), `pc`, `regs` (or `available: false`, "
    "`why`), `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or "
    "`regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine)"
)
PICTURE = (
    "The PNG is attached after the JSON when within the inline ceiling "
    f"({picture.INLINE_SIDE_MAX} px a side, {picture.INLINE_TOKENS_MAX} tiles of "
    f"{picture.TOKEN_SIDE} px); `image` names it either way (`path`, `sha256`, `width`, "
    "`height`, `scale`, `indexed`, `inline`, `not_inlined`)"
)
PICTURE_ARGS = (
    f"`scale` 0, the largest integer enlargement up to {picture.SCALE_MAX} that fits; "
    "`dest` a new absolute path, else the scratch, gone at `close`"
)
CPU_READS = (
    "Each cpu is served by its own thread of the gdbstub's thread patch (`status`'s `threads`); "
    "a build without it serves its first cpu alone, whatever is visible, and refuses another "
    "(`bad_argument`)"
)
NUMBER_ARG = "an integer or a `0x` string"
DEST_FILE = f"absolute, in a directory that exists, with {inputs.PATH_CHARS}"
SPACE_BOUND = (
    "A range whose last byte lies past that cpu's program space (the address mask `start` "
    "read) is `bad_argument` naming the mask; with no mask known the range is the console's"
)

# EVERY NUMBER A DOCSTRING STATES IS READ OFF THE CONSTANT THAT ENFORCES IT, filled at
# registration: a ceiling typed into prose drifts from the one the code refuses at, and a
# ceiling nobody typed is a limit the caller meets only by hitting it.
DOC_VALUES: dict[str, str] = {
    "NEEDS_STOPPED": NEEDS_STOPPED, "STOP_FIELDS": STOP_FIELDS, "CPU_READS": CPU_READS,
    "SPACE_BOUND": SPACE_BOUND, "NUMBER_ARG": NUMBER_ARG, "DEST_FILE": DEST_FILE,
    "BREAKPOINT_MATCH": dec.REF_MATCH["breakpoint"], "WATCH_MATCH": dec.REF_MATCH["watch"],
    "REGPOINT_MATCH": dec.REF_MATCH["regpoint"],
    "PICTURE": PICTURE, "PICTURE_ARGS": PICTURE_ARGS,
    "PALETTE_COUNT_MAX": str(mpalette.COUNT_MAX),
    "ROW_PENS": str(mpalette.ROW_PENS), "GFX_PIXELS_MAX": str(mgfx.TILE_PIXELS_MAX),
    "GFX_BLOCK_MAX": str(mgfx.BLOCK_BYTES_MAX), "SCREEN_PENS_MAX": str(mscreen.PENS_MAX),
    "GFX_PLANES_MAX": str(ml.PLANES_MAX), "GFX_TILES_MAX": str(mgfx.VIEW_TILES_MAX),
    "GFX_COLUMNS_MAX": str(mgfx.COLUMNS_MAX), "LOCATE_LAYOUTS_MAX": str(mlocate.LAYOUTS_MAX),
    "LOCATE_TILES_MAX": str(mlocate.SEARCH_TILES_MAX), "LOCATE_WORK_MAX": str(mlocate.WORK_MAX),
    "LOCATE_MATCHES_SHOWN": str(mlocate.MATCHES_SHOWN),
    "LOCATE_MATCHES_MAX": str(mlocate.MATCHES_MAX),
    "SWEEP_MAX": str(msweep.SWEEP_MAX), "SWEEP_COUNT_MAX": str(msweep.COUNT_MAX),
    "SWEEP_COUNT": str(msweep.COUNT_DEFAULT), "SWEEP_SIDE_MAX": str(max(msweep.SIDES)),
    "DRAFT_NOT_PROVED_SHOWN": str(mdraft.NOT_PROVED_SHOWN),
    "CONSOLE_READS": transport.CONSOLE_READS,
    "PALETTE_LOG_LIMIT_MAX": str(mramdac.LIMIT_MAX),
    "PALETTE_LOG_SETTERS_MAX": str(mramdac.SETTERS_LISTED_MAX),
    "PALETTE_LOG_ROWS_MAX": str(mramdac.ROWS_MAX), "FILM_FRAMES_MAX": str(mfilm.FRAMES_MAX),
    "FILM_FRAMES": str(mfilm.FRAMES_DEFAULT), "FILM_KEEP": str(mfilm.KEEP_DEFAULT),
    "FILM_KEEP_MAX": str(mfilm.KEEP_MAX), "BLIT_MARGIN_MAX": str(mblits.MARGIN_MAX),
    "READ_MAX": str(read.READ_MAX), "LIST_MAX": str(read.LOG_LIMIT_MAX),
    "SYMBOLS_MAX": str(read.SYMBOLS_LIMIT_MAX), "HISTORY_MAX": str(read.HISTORY_MAX),
    "FIND_BYTES_MAX": str(read.FIND_BYTES_MAX), "GRID_MIN": str(mlua.GRID_MIN),
    "GRID_MAX": str(mlua.GRID_MAX), "STEP_MAX": str(advance.step_max()),
    "WAIT_MAX_S": f"{inputs.WAIT_MAX_S:g}", "SCRIPT_MAX": str(transport.SCRIPT_MAX),
    "WATCH_SHOW_MAX": str(watches.SHOW_WATCH_MAX), "STATE_NAME_MAX": str(savestates.STATE_NAME_MAX),
    "OUTPUT_MAX": str(mwrite.DEBUG_MAX), "PIPE_STEPS_MAX": str(transport.PIPE_STEPS_MAX),
    "UNTIL_STEPS_MAX": str(sequence.UNTIL_STEPS_MAX), "ROWS_SHOWN": str(st.ROWS_SHOWN),
    "EVAL_WAIT_S": f"{mlua.EVAL_WAIT_S:g}", "EXPECT_WAIT_S": f"{sequence.DRIVE_EXPECT_WAIT_S:g}",
    "TEMPS": str(lexer.TEMPS), "SCAN_BYTES_MAX": f"{mscan.SCAN_BYTES_MAX:#x}",
    "COMMENT_TEXT_MAX": str(mcomment_file.TEXT_MAX_BYTES),
    "TRACE_FRAMES_MAX": str(mtrace.FRAMES_MAX), "TRACE_MS_MAX": str(mtrace.MILLISECONDS_MAX),
    "NOLOOP_FRAMES_MAX": str(mtrace.NOLOOP_FRAMES_MAX),
    "NOLOOP_MS_MAX": str(mtrace.NOLOOP_MILLISECONDS_MAX),
    "TRACE_SYMBOLS_SHOWN": str(mtrace.SYMBOLS_SHOWN),
}
_PLACEHOLDER = re.compile(r"\{[A-Z][A-Z0-9_]*\}")


def filled(name: str, doc: str) -> str:
    """`doc` with every `{NAME}` of `DOC_VALUES` filled, or a failure at import naming what is
    left: a placeholder that reaches a client reads as a word, not as a number that is missing."""
    for key, value in DOC_VALUES.items():
        doc = doc.replace("{" + key + "}", value)
    left = _PLACEHOLDER.findall(doc)
    if left:
        raise TypeError(f"{name}'s docstring names {left}, which nothing fills")
    return doc
