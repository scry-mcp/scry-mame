"""Placeholders for tool docstrings, filled at registration from the constants that enforce them."""
from __future__ import annotations

from scry_core import comment_file as core_comments
from scry_core import (
    docs,
    file_names,
    frame_window,
    log_marks,
    picture,
    recording,
    roster,
    screen_map,
    series,
    stop_wait,
)
from scry_core import pens as scry_pens
from scry_core import promote as core_promote
from scry_core import (
    scan_vocabulary as words,
)
from scry_core import vocabulary as vocab
from scry_core import window as core_window

from scry_mame import advance, inputs, lexer, read, sequence, transport, watches
from scry_mame import binary as binaries
from scry_mame import blits as mblits
from scry_mame import draft as mdraft
from scry_mame import film as mfilm
from scry_mame import gfx as mgfx
from scry_mame import layout as ml
from scry_mame import locate as mlocate
from scry_mame import ramdac as mramdac
from scry_mame import scan as mscan
from scry_mame import state as st
from scry_mame import sweep as msweep
from scry_mame import trace as mtrace
from scry_mame import write as mwrite

# Sentences shared by the tool docstrings. The server instructions already say which readers
# refuse on a running machine, so it is not repeated here (each repeat counts against the cap).
NEEDS_STOPPED = "Needs the machine STOPPED (else `not_stopped`)"
NUMBER_ARG = "an integer or a `0x` string"
DEST_FILE = f"absolute or `~`-led, in a directory that exists, with {inputs.PATH_CHARS}"
PENDING = "Without an answer, `pending`."

# A ceiling typed into prose drifts from the one the code refuses at.
DOC_VALUES: dict[str, str] = {
    "NEEDS_STOPPED": NEEDS_STOPPED, "MAME_RELEASE": binaries.RELEASE,
    "NUMBER_ARG": NUMBER_ARG, "DEST_FILE": DEST_FILE, "PENDING": PENDING,
    "ADD_READ": "capture", "ADD_PLACES": "naming its places to read",
    # scry-core's, alike on both servers.
    **picture.DOC_VALUES, **series.DOC_VALUES, **screen_map.DOC_VALUES, **recording.DOC_VALUES,
    **core_comments.DOC_VALUES, **frame_window.DOC_VALUES,
    **core_promote.DOC_VALUES, **roster.DOC_VALUES, **core_window.DOC_VALUES,
    "RECORD_MAX": str(frame_window.UNTIL_STEPS_MAX),
    "GFX_PIXELS_MAX": str(mgfx.TILE_PIXELS_MAX),
    "GFX_BLOCK_MAX": str(mgfx.BLOCK_BYTES_MAX), "SCREEN_PENS_MAX": str(scry_pens.PENS_MAX),
    "GFX_PLANES_MAX": str(ml.PLANES_MAX), "GFX_TILES_MAX": str(mgfx.VIEW_TILES_MAX),
    "GFX_COLUMNS_MAX": str(mgfx.COLUMNS_MAX), "LOCATE_LAYOUTS_MAX": str(mlocate.LAYOUTS_MAX),
    "LOCATE_TILES_MAX": str(mlocate.SEARCH_TILES_MAX),
    "LOCATE_MATCHES_SHOWN": str(mlocate.MATCHES_SHOWN),
    "SWEEP_MAX": str(msweep.SWEEP_MAX), "SWEEP_COUNT_MAX": str(msweep.COUNT_MAX),
    "SWEEP_SIDE_MAX": str(max(msweep.SIDES)),
    "DRAFT_NOT_PROVED_SHOWN": str(mdraft.NOT_PROVED_SHOWN),
    "PALETTE_LOG_SETTERS_MAX": str(mramdac.SETTERS_LISTED_MAX),
    "PALETTE_LOG_ROWS_MAX": str(mramdac.ROWS_MAX), "FILM_FRAMES_MAX": str(mfilm.FRAMES_MAX),
    "FILM_KEEP_MAX": str(mfilm.KEEP_MAX), "BLIT_MARGIN_MAX": str(mblits.MARGIN_MAX),
    "READ_MAX": str(read.READ_MAX), "LIST_MAX": str(read.LOG_LIMIT_MAX),
    **log_marks.DOC_VALUES,
    "SYMBOLS_MAX": str(read.SYMBOLS_LIMIT_MAX), "HISTORY_MAX": str(read.HISTORY_MAX),
    "FIND_BYTES_MAX": str(read.FIND_BYTES_MAX), "STEP_MAX": str(advance.step_max()),
    "WAIT_MAX_S": f"{vocab.WAIT_MAX_S:g}", "SCRIPT_MAX": str(transport.SCRIPT_MAX),
    "WATCH_SHOW_MAX": str(watches.SHOW_WATCH_MAX),
    "STATE_NAME_MAX": str(file_names.WORD_MAX),
    "OUTPUT_MAX": str(mwrite.DEBUG_MAX), "PIPE_STEPS_MAX": str(transport.PIPE_STEPS_MAX),
    "ROWS_SHOWN": str(st.ROWS_SHOWN),
    "EXPECT_WAIT_S": f"{sequence.DRIVE_EXPECT_WAIT_S:g}",
    "TEMPS": str(lexer.TEMPS), "SCAN_BYTES_MAX": f"{mscan.SCAN_BYTES_MAX:#x}",
    "HITS_DEFAULT": str(words.HITS_DEFAULT),
    "TRACE_FRAMES_MAX": str(mtrace.FRAMES_MAX), "TRACE_MS_MAX": str(mtrace.MILLISECONDS_MAX),
    "NOLOOP_FRAMES_MAX": str(mtrace.NOLOOP_FRAMES_MAX),
    "NOLOOP_MS_MAX": str(mtrace.NOLOOP_MILLISECONDS_MAX),
    "TRACE_SYMBOLS_SHOWN": str(mtrace.SYMBOLS_SHOWN),
    "PALETTES": ", ".join(f"`{p}`" for p in advance.PALETTES),
    **stop_wait.DOC_VALUES,
}


def filled(name: str, doc: str) -> str:
    """`doc` with this server's `DOC_VALUES` filled (`scry_core.docs.filled`)."""
    return docs.filled(name, doc, DOC_VALUES)
