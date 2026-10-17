"""Every tool of the server, driven against a real MAME in every machine state, at every argument
boundary and across every pair of tools that share state, one printed line per cell.

`live_check.py` proves the guarantees one call at a time; this is the MATRIX around them. Its
cells are declared as data before anything boots, so the count of cells PLANNED is printed first
and a cell the run never reached is visible at the end instead of missing from it; every call
lands whole in a JSONL transcript. That machinery is `live_harness.py`'s, shared with section H
(`matrix_acceptance.py`), which this matrix runs last.

A cell is OK when the reply matches the tool's own published contract for that state and input,
FAIL when it contradicts it, raises, or leaves the session block disagreeing with the machine,
and BLOCKED when it could not be run, with the reason (`run_sections` says how it exits).

    timeout 1800 uv run python tests/live/live_matrix.py

`MAME_LIVE_SECTIONS` names the letters to run (all of them unset). `MAME_LIVE_JOBS` runs each
letter as a process of its own, as many at once as it says (unset, half the host's CPUs; `1`,
one after another in this process), merged from the summaries they declare through
`scry_core.live_pool`; section X, the focus gate, opens and closes the run in this process, so
its watch spans every job.

m68k-dual and section H's V30 boards run on their copies on the bench (`bench_boards`); a board
that cannot run there is BLOCKED with the reason.
Blocks D, J, K and Q, section H's circus and section T's 1942 also drive the free boards of
mamedev.org, which need a stock MAME and their zips (`free_boards_missing` says which
variables); section S's multi-cpu boards need a build whose stub serves a
thread per cpu (`multicpu_missing`). Unset, those cells are BLOCKED.
"""

import functools
import hashlib
import inspect
import json
import math
import os
import re
import struct
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench_boards import (
    BENCH,
    BLIT_HANDLER,
    MANIFEST,
    REFERENCE_ROM,
    SUB_ROM,
    SUB_SYMBOLS,
    SYMBOLS,
    bench_missing,
    m68k_dual_missing,
    value,
)
from gfx_layouts import BYTES_8X8, CIRCUS_CHAR, GRID_FB, GRID_SPRITE, WITCH_TILE
from live_harness import (
    BOOT,
    PENDING,
    SCRATCH,
    TRANSCRIPT,
    WAIT_CEILING_S,
    Blocked,
    Board,
    blocked,
    boards_cover,
    boot,
    call,
    cell,
    circus_boot,
    ensure_closed,
    free_boards_missing,
    free_boot,
    fresh,
    fresh_state,
    last_wall,
    ok,
    rearm_pairs,
    refused,
    run_boards,
    run_sections,
    said,
    section,
    session_is,
    unavailable_why,
    visible_of,
    whole,
)
from map_edges import program_edges
from matrix_acceptance import register_h
from matrix_audio import register_l
from matrix_comments import register_m
from matrix_console import register_c16
from matrix_cpus import register_r
from matrix_focus import register_x_control, register_x_verdict
from matrix_inputs import register_o
from matrix_landing import register_v
from matrix_lifetime import register_p
from matrix_media import register_y
from matrix_multicpu import register_s
from matrix_palette_stamps import register_u
from matrix_removals import (
    K_CAPTURE_LEFTOVER,
    K_REDECLARE_LIVE,
    K_REMOVALS,
    k_capture_leftover,
    k_redeclare_live,
    k_removals,
)
from matrix_stamps import register_t
from matrix_states import register_q
from matrix_traces import register_n
from matrix_watch_tick import register_w
from reader_fault import reader_fault, reader_fault_counts

from evidence import (  # isort: skip -- it imports the server's files, so after the harness
    console_disagreement,
    console_in_log,
    console_ran_the_throttle_first,
    sentinel_order,
)

import mame_breakpoints as breakpoints
import mame_conditions as conditions
import mame_transport as transport

import mame_callbacks as callbacks  # isort: skip
import mame_cpus as cpus  # isort: skip
import mame_capture as mcapture  # isort: skip
import mame_film as mfilm  # isort: skip
import mame_declarations as dec  # isort: skip
import mame_ramdac as mramdac  # isort: skip
import mame_read as read  # isort: skip
import mame_savestates as msavestates  # isort: skip
import mame_screen as mscreen  # isort: skip
import mame_watches as mwatches  # isort: skip
import server as s  # isort: skip
from scry_core import png, series  # isort: skip
from scry_core import value_format as vf  # isort: skip
from mame_state import REPLY_BUDGET_CHARS, STATE  # isort: skip

# THE FOCUS GATE'S CONTROL OPENS THE RUN, before any other section is registered, so the watch it
# starts samples every one of them; its verdict is registered last, below.
register_x_control()

# ================================================================ Block A: states x tools
#
# (S1 a, and interaction section 11.) Every tool in each machine state: no session, stopped,
# running, and after `close`. Its arguments are a valid call, so the state is the only variable.

STATES = ("none", "stopped", "running", "closed")
_saved: list[str] = []


def load_judged(r: dict[str, Any]) -> bool:
    """A load verified, or one with nothing run since its save, which cannot be told from no load:
    null and that why, where the stop stands at the saved frame."""
    return r.get("verified") is True or (
        unavailable_why(r.get("verified")) == msavestates.ALREADY_AS_SAVED
        and (r.get("saved") or {}).get("frame") == r.get("frame"))


def _state_to_load() -> str:
    return _saved[-1] if _saved else "never_saved"


def _save_name() -> str:
    _saved.append(fresh_state())
    return _saved[-1]


BLITTER, BLIT_TRIGGER = "0x700000", "0x70001e"


def _blits_ready(args: dict[str, Any]) -> dict[str, Any]:
    """`args`, with what a valid call of the two blit tools needs made true first on a stopped
    machine: the manifest loaded, the blitter's capture declared, and rows of a finished frame.
    With no stopped machine nothing is prepared: the call is then the state's own refusal."""
    here = s.status()
    if not here.get("alive") or here.get("running"):
        return args
    if STATE.manifest is None:
        call("gfx_load", path=MANIFEST)
    if not any(owner[0] == BLITTER for owner in STATE.tallies):
        call("watch_add", ref=BLITTER, mode="capture", length=32, trigger=BLIT_TRIGGER)
        # a boot's first blits come a few frames in; the frame asked for is one it finished
        call("run_for", frames=8, seconds=10.0)
    return args


def _manifest_ready(args: dict[str, Any]) -> dict[str, Any]:
    """`args`, with the manifest loaded first on a live machine, running or stopped, since
    `gfx_load` answers on both. With no session nothing is prepared."""
    if s.status().get("alive") and STATE.manifest is None:
        call("gfx_load", path=MANIFEST)
    return args


#: The film every state's probe reads: the blitter's strobe, the value that fires a blit.
FILM: dict[str, Any] = {"trigger": BLIT_TRIGGER, "length": 2, "value": 0xFFFF, "keep": 2,
                        "frames": 4}


def _series_ahead() -> dict[str, Any]:
    """A one-frame series two frames ahead of a stopped machine, read off its own screen's
    counter; with no session, or a running one, any frame: the call is the state's refusal."""
    here = s.status()
    if not here.get("alive") or here.get("running"):
        return {"frames": [1], "seconds": 10.0}
    now = s.screen_signature().get("frame_screen", 0)
    return {"frames": [now + 2], "seconds": 10.0}


#: The media file tools, probed with a file that is not there: they read files and never the
#: machine, so in EVERY state the answer is the missing file's own refusal.
MEDIA_ABSENT: dict[str, dict[str, Any]] = {
    "image_diff": {"a": "/nonexistent/a.png", "b": "/nonexistent/b.png"},
    "series_diff": {"a": "/nonexistent/a.json", "b": "/nonexistent/b.json"},
    "region_track": {"manifest": "/nonexistent/m.json"},
    "golden_check": {"manifest": "/nonexistent/m.json", "checksums": "/nonexistent/g.sha256"},
    "audio_measure": {"path": "/nonexistent/s.wav"},
    "audio_diff": {"a": "/nonexistent/a.wav", "b": "/nonexistent/b.wav"},
}


def _film_ready(args: dict[str, Any]) -> dict[str, Any]:
    """`args` (a READ of the film), with a film armed first on a live machine: arming needs a
    stop, so a running machine is stopped for it and let go again. With no session nothing is
    prepared: the call is then the state's own refusal."""
    here = s.status()
    if not here.get("alive") or mfilm.held() is not None:
        return args
    if here.get("running"):
        call("stop")
        call("gfx_film", **FILM)
        call("resume")
    else:
        call("gfx_film", **FILM)
    return args


#: The comment files `comment_save` wrote in this section, so `comment_load` reads the last one.
_comment_files: list[str] = []


def _comment_dest() -> str:
    _comment_files.append(fresh(".tsv"))
    return _comment_files[-1]


def _comment_source() -> str:
    return _comment_files[-1] if _comment_files else fresh(".tsv")


#: TOOL -> a valid call, built fresh each time (a `dest` or a state name is new per call). Every
#: wait is inside the ceiling.
PROBES: dict[str, Callable[[], dict[str, Any]]] = {
    "start": lambda: {**BOOT, "symbols": SYMBOLS},
    "status": dict,
    "close": dict,
    "rom_check": lambda: {"reference_rom": REFERENCE_ROM, "reference_addr": "0x0"},
    "run_to": lambda: {"ref": "irq_vblank", "control": "0x4a0", "seconds": 10.0},
    "run_for": lambda: {"frames": 1, "seconds": 10.0},
    "trace": lambda: {"frames": 1, "seconds": 10.0},
    "step": lambda: {"count": 1},
    "resume": dict,
    "stop": dict,
    "breakpoint_at": lambda: {"ref": "exception_handler"},
    "breakpoint_list": dict,
    "breakpoint_clear": lambda: {"all": True},
    "watch_add": lambda: {"ref": "0x203200", "mode": "show", "length": 2},
    "watch_list": dict,
    "watch_clear": lambda: {"all": True},
    # A condition that never comes true: the probe is of the tool, and one that fired would
    # stop the machine under the RUNNING state's other probes.
    "regpoint_add": lambda: {"condition": "pc==0xfffffffe"},
    "regpoint_list": dict,
    "regpoint_clear": lambda: {"all": True},
    # in this order on a stopped machine: the save writes what the load reads back, and the
    # delete takes what the add placed
    "comment_add": lambda: {"ref": "irq_vblank", "text": "matrix A", "cpu": "maincpu"},
    "comment_list": dict,
    "comment_save": lambda: {"dest": _comment_dest()},
    "comment_load": lambda: {"path": _comment_source()},
    "comment_delete": lambda: {"ref": "irq_vblank", "cpu": "maincpu"},
    "symbols_find": lambda: {"name": "irq_vblank"},
    "machine_map": dict,
    "cpu_info": dict,
    "read_memory": lambda: {"ref": "0x400", "length": 8},
    "read_block": lambda: {"tag": "maincpu", "offset": 0x400, "length": 8},
    "registers": dict,
    "disassemble": lambda: {"ref": "irq_vblank", "length": 8},
    "find": lambda: {"ref": "0x0", "length": 1024, "data_hex": "00"},
    "history": lambda: {"limit": 4},
    # opened, then closed at once by a `!` on the same stop, then cleared: the state is kept
    "scan_start": lambda: {"ref": "0x200000", "length": 0x100},
    "scan_filter": lambda: {"operator": "!"},
    "scan_clear": dict,
    "focus": lambda: {"cpu": "maincpu"},
    "write": lambda: {"ref": "0x200000", "data_hex": "00"},
    "set_register": lambda: {"name": "D0", "value": 0},
    "reset": dict,
    "memdump": lambda: {"ref": "0x0", "length": 16, "dest": fresh(".bin")},
    "snapshot": dict,
    "screen_signature": dict,
    "series_capture": _series_ahead,
    **{tool: functools.partial(dict, args) for tool, args in MEDIA_ABSENT.items()},
    "palette": dict,
    "screen_view": lambda: {"mode": "histogram"},
    "gfx_view": lambda: {"layout": BYTES_8X8, "palette": "none", "tag": "maincpu", "count": 16},
    "gfx_locate": lambda: {"layouts": [BYTES_8X8], "patch": [0, 0, 8, 8], "tag": "maincpu",
                           "count": 64},
    "gfx_sweep": lambda: {"tag": "maincpu", "planes": [1], "count": 8},
    # the locate above is this state's evidence: a draft of what it established
    "gfx_draft": lambda: {"dest": fresh(".yaml")},
    "gfx_load": lambda: {"path": MANIFEST},
    "gfx_blits": lambda: _blits_ready({"draw_command": "blit"}),
    "gfx_blit_source": lambda: _blits_ready({"draw_command": "blit", "index": 0}),
    "palette_log": lambda: _manifest_ready({"palette_port": "ramdac", "arm": True}),
    "gfx_film": lambda: _film_ready({}),
    "log": lambda: {"pattern": ".", "channel": "emulator", "limit": 3},
    "log_wait": lambda: {"pattern": ".", "channel": "emulator", "seconds": 5.0},
    "drive": lambda: {"act": [{"op": "run_for", "frames": 1, "seconds": 10.0}],
                      "settle_seconds": 2.0},
    "perform": lambda: {"steps": [{"op": "registers"}], "settle_seconds": 2.0},
    "debug": lambda: {"command": "print pc"},
    "lua": lambda: {"script": "print(1)", "read_only": True},
    "input": lambda: {"port": ":P1", "field": "Coin 1", "frames": 1, "seconds": 10.0},
    "record": lambda: {"frames": 2, "seconds": 10.0},
    "audio_record": lambda: {"frames": 2, "seconds": 10.0},
    "throttle": lambda: {"on": False, "seconds": 5.0},
    "state_save": lambda: {"name": _save_name()},
    "captures": dict,
    "state_list": dict,
    "state_load": lambda: {"name": _state_to_load()},
}

#: What answers on a RUNNING machine, from the server's `instructions` and each tool's own
#: docstring; everything else but the lifecycle refuses `not_stopped`.
RUNNING_ANSWERS = {"status", "log", "log_wait", "snapshot", "symbols_find", "throttle",
                   "breakpoint_at", "breakpoint_list", "breakpoint_clear", "watch_add",
                   "watch_list", "watch_clear", "regpoint_add", "regpoint_list",
                   "regpoint_clear", "comment_list", "comment_save", "state_list", "captures",
                   "machine_map", "cpu_info", "gfx_load", "palette_log", "gfx_film", "scan_clear",
                   "stop", "close"}

#: The fields a valid call's reply must carry on a STOPPED machine, one predicate per tool,
#: each from that tool's own `Reply:` paragraph.
STOPPED_SAYS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "status": lambda r: r.get("alive") is True and r.get("running") is False,
    "rom_check": lambda r: r.get("rom_check") == "OK",
    "run_to": lambda r: r.get("verdict") == "TARGET",
    "run_for": lambda r: r.get("verdict") == "ELAPSED",
    "trace": lambda r: (r.get("verdict") == "ELAPSED"
                        and (r.get("trace") or {}).get("addresses", 0) > 0),
    "step": lambda r: r.get("instructions_completed") == 1 and "regs" in r,
    "breakpoint_at": lambda r: r.get("armed") is True,
    "breakpoint_list": lambda r: isinstance(r.get("breakpoints"), list),
    "breakpoint_clear": lambda r: "declarations_cleared" in r,
    "watch_add": lambda r: r.get("state") == "evaluated"
    and r.get("reading", {}).get("available") is True and "value" in r["reading"],
    "watch_list": lambda r: isinstance(r.get("watches"), list),
    "watch_clear": lambda r: "declarations_cleared" in r,
    "regpoint_add": lambda r: r.get("armed") is True and r.get("cpu") == ":maincpu",
    "regpoint_list": lambda r: isinstance(r.get("regpoints"), list),
    "regpoint_clear": lambda r: "declarations_cleared" in r,
    "comment_add": lambda r: (r.get("comment") or {}).get("state") == "armed"
    and r.get("cpu") == ":maincpu",
    "comment_list": lambda r: r.get("comments_total") == 1 and len(r.get("comments", [])) == 1,
    "comment_save": lambda r: r.get("comments_total") == 1 and Path(str(r.get("path"))).is_file(),
    "comment_load": lambda r: r.get("parsed") == 1 and r.get("unchanged") == 1,
    "comment_delete": lambda r: (r.get("deleted") or {}).get("ref") == "irq_vblank",
    "symbols_find": lambda r: r.get("symbols_total") == 1,
    "machine_map": lambda r: bool(r.get("cpus")),
    # m68k-dual's two cpus, the main one visible, each pc read.
    "cpu_info": lambda r: [(c["cpu"], c["visible"], "value" in (c["pc"] or {}))
                           for c in r.get("cpus", [])]
    == [(":maincpu", True, True), (":subcpu", False, True)],
    "read_memory": lambda r: len(str(r.get("hex"))) == 16,
    "read_block": lambda r: len(str(r.get("hex"))) == 16,
    "registers": lambda r: "PC" in r.get("regs", {}),
    "disassemble": lambda r: bool(r.get("lines")),
    "find": lambda r: isinstance(r.get("hits_total"), int),
    "history": lambda r: bool(r.get("lines")),
    # The visible cpu shown again: nothing moves, and the reply reads it back.
    "focus": lambda r: r.get("cpu") == ":maincpu" and r.get("machine_ran") is False,
    "write": lambda r: r.get("verified") is True,
    "set_register": lambda r: r.get("verified") is True,
    "reset": lambda r: r.get("kind") == "softreset",
    "memdump": lambda r: r.get("bytes") == 16,
    "snapshot": lambda r: r.get("bytes", 0) > 0,
    "screen_signature": lambda r: isinstance(r.get("signature"), str)
    and len(r["signature"]) == 16,
    "series_capture": lambda r: r.get("count") == 1 and r.get("kept_after_close") is False,
    "palette": lambda r: r.get("entries", 0) > 0 and r.get("image", {}).get("inline") is True,
    "screen_view": lambda r: sum(n for _, n in r.get("histogram", []))
    == r.get("width", 0) * r.get("height", 0) > 0,
    "gfx_view": lambda r: r.get("count") == 16 and r.get("real_colors") is False,
    "gfx_locate": lambda r: r.get("candidates", [{}])[0].get("tiles_searched") == [0, 64],
    "gfx_sweep": lambda r: r.get("sweep", 0) >= 1 and r.get("image", {}).get("inline") is True
    and all(c["shown"] == 8 for c in r.get("candidates", [])),
    "gfx_draft": lambda r: Path(r.get("manifest", {}).get("path", "")).is_file()
    and Path(r.get("report", {}).get("path", "")).is_file(),
    "gfx_load": lambda r: r.get("loaded") is True and "blit" in r.get("commands", {}),
    # each state starts a machine with no log armed, so its call with `arm=True` arms one
    "palette_log": lambda r: r.get("palette_port") == "ramdac" and r.get("armed_now") is True,
    # each state arms a film before the probe, which reads it
    "gfx_film": lambda r: (r.get("film") or {}).get("trigger") == BLIT_TRIGGER
    and isinstance(r.get("installed"), bool) and isinstance(r.get("pending"), bool),
    "gfx_blits": lambda r: r.get("blits_in_frame", 0) > 0 and r.get("frame_complete") is True,
    "gfx_blit_source": lambda r: r.get("index") == 0 and r.get("image", {}).get("indexed") is True,
    "log": lambda r: isinstance(r.get("lines_total"), int),
    "drive": lambda r: r.get("act", {}).get("steps_completed") == 1,
    "perform": lambda r: r.get("steps_completed") == 1,
    "debug": lambda r: isinstance(r.get("output"), str),
    "lua": lambda r: r.get("output") == "1\n",
    "input": lambda r: r.get("released") is True,
    "record": lambda r: r.get("avi_frames") == 2,
    "audio_record": lambda r: (r.get("samples") or 0) > 0
    and r.get("frame_end", 0) - r.get("frame_begin", 0) + 1 == 2,
    "state_save": lambda r: Path(str(r.get("path"))).is_file(),
    "captures": lambda r: isinstance(r.get("captures"), list),
    "state_list": lambda r: isinstance(r.get("states"), list),
    "state_load": load_judged,
    "throttle": lambda r: r.get("pending") is True and str(r.get("mark", "")).startswith(
        "MAME_MCP_THROTTLE#"),
    "stop": lambda r: r.get("interrupted") is False,
    "resume": lambda r: "verdict" not in r and "halted" not in r,
    "close": lambda r: r.get("closed") is True,
    "scan_start": lambda r: r.get("hits_total") == 0x100 and r.get("space") == "program",
    "scan_filter": lambda r: r.get("closed") is True and r.get("hits_total") == 0,
    "scan_clear": lambda r: r.get("cleared") in (True, False),
}

def _says_running(r: dict[str, Any]) -> bool:
    """A reader on a running machine says so in its `session` block alone (`status` aside)."""
    return r.get("session", {}).get("running") is True and "running" not in r


RUNNING_SAYS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "scan_clear": lambda r: r.get("cleared") in (True, False),
    "status": lambda r: r.get("running") is True and r.get("last_stop") is not None,
    "log": lambda r: isinstance(r.get("lines_total"), int),
    "log_wait": lambda r: "line" in r,
    "snapshot": lambda r: r.get("bytes", 0) > 0,
    "symbols_find": lambda r: r.get("symbols_total") == 1
    and all(x.get("memory") == "unknown" for x in r.get("symbols", [])),
    "throttle": lambda r: r.get("pending") is False and isinstance(r.get("frame"), int),
    "breakpoint_at": lambda r: r.get("armed") is True and r.get("while_running") is True,
    "breakpoint_list": lambda r: _says_running(r) and "last_stop" in r,
    "breakpoint_clear": lambda r: r.get("while_running") is True,
    "watch_add": lambda r: r.get("state") == "evaluated" and "reading" not in r,
    "watch_list": lambda r: _says_running(r) and "last_stop" in r,
    "watch_clear": lambda r: r.get("while_running") is True,
    "regpoint_add": lambda r: r.get("armed") is True and r.get("while_running") is True,
    "regpoint_list": lambda r: _says_running(r) and "last_stop" in r,
    "regpoint_clear": lambda r: r.get("while_running") is True,
    "comment_list": lambda r: _says_running(r) and "last_stop" in r,
    "comment_save": lambda r: isinstance(r.get("comments_total"), int)
    and Path(str(r.get("path"))).is_file(),
    "state_list": lambda r: isinstance(r.get("states"), list),
    "captures": lambda r: isinstance(r.get("captures"), list),
    "machine_map": lambda r: bool(r.get("cpus")),
    # Running: every row, no pc read.
    "cpu_info": lambda r: _says_running(r) and len(r.get("cpus", [])) == 2
    and all(c["pc"].get("available") is False for c in r["cpus"]),
    "gfx_load": lambda r: r.get("loaded") is True,
    # each state starts a machine with no log armed, so its call with `arm=True` arms one
    "palette_log": lambda r: r.get("palette_port") == "ramdac" and r.get("armed_now") is True,
    "gfx_film": lambda r: (r.get("film") or {}).get("trigger") == BLIT_TRIGGER
    and isinstance(r.get("installed"), bool) and isinstance(r.get("pending"), bool),
    "stop": lambda r: r.get("interrupted") is True and isinstance(r.get("frame"), int),
    "close": lambda r: r.get("closed") is True,
}


def judge_a(tool: str, state: str, r: dict[str, Any]) -> tuple[bool, str]:
    """A tool's reply in a state against its contract, and whether the session block then agrees
    with the machine the state leaves behind."""
    if tool in MEDIA_ABSENT:
        good = refused(r, "bad_argument") and "is not a file" in str(r.get("message"))
        agrees = session_is(r, state not in ("none", "closed"), state == "running")
    elif state in ("none", "closed"):
        if tool == "status":
            good = ok(r) and r.get("alive") is False
        elif tool == "close":
            good = ok(r) and r.get("closed") is False and r.get("ended_by") == "none"
        elif tool == "start":
            good = ok(r) and r.get("rom_check") == "OK"
        else:
            good = refused(r, "no_session")
        agrees = session_is(r, tool == "start", False)
    elif state == "stopped":
        if tool == "start":
            good = refused(r, "session_live")
        elif tool == "log_wait":
            # The probe's `.` matches a line the log already holds, and that is answered at
            # once on a stopped machine too; the refusal is `log_wait on a stopped machine`.
            good = ok(r) and r.get("already") is True
        else:
            good = ok(r) and STOPPED_SAYS[tool](r)
        agrees = session_is(r, True, tool == "resume")
    else:
        if tool == "start":
            good = refused(r, "session_live")
        elif tool in RUNNING_ANSWERS:
            good = ok(r) and RUNNING_SAYS[tool](r)
        elif tool in ("perform", "drive"):
            # A console step while the machine runs past `settle_seconds`: the wait ran out, an
            # answer (`perform`'s verdict, `drive`'s act's), the step never sent.
            verdict = r.get("verdict") if tool == "perform" else r.get("act", {}).get("verdict")
            good = ok(r) and verdict == "TIMEOUT"
        else:
            good = (refused(r, "not_stopped") and isinstance(r.get("last_stop"), dict)
                    and "answers_while_running" in r)
        # `close` describes the session as it was BEFORE it: still running.
        agrees = session_is(r, True, tool != "stop")
    detail = said(r) if good else f"{r.get('code', '')} {said(r)}"
    if good and not agrees:
        detail = f"session block disagrees: {r.get('session')}"
    return good and agrees, detail


def _a(state: str, tool: str) -> str:
    return f"{tool} @ {state}"


#: The call that puts the machine back in the state under test after a cell that moved it out.
RESTORE = {("stopped", "resume"): "stop", ("stopped", "run_to"): "breakpoint_clear",
           ("stopped", "gfx_blit_source"): "watch_clear", ("running", "stop"): "resume"}
#: The clears a restore names take every declaration, which a clear only does when asked.
CLEARS = ("breakpoint_clear", "watch_clear", "regpoint_clear")


def restore(tool: str) -> dict[str, Any]:
    """A restoring call, a clear of every declaration of its kind when it is a clear."""
    return call(tool, all=True) if tool in CLEARS else call(tool)


def run_state(state: str, tools: list[str]) -> None:
    for tool in tools:
        label = _a(state, tool)
        try:
            r = call(tool, **PROBES[tool]())
        except Blocked as e:
            blocked(label, str(e))
            continue
        cell(label, *judge_a(tool, state, r))
        if (state, tool) in RESTORE:
            restore(RESTORE[state, tool])


# The order inside a state is the order that keeps the state: everything that leaves the
# machine where it found it first, then the calls that move it, the transitions last.
STOPPED_ORDER = [
    "status", "rom_check", "machine_map", "cpu_info", "symbols_find", "read_memory", "read_block",
    "registers", "disassemble", "find", "history", "scan_start", "scan_filter", "scan_clear",
    "focus", "log", "snapshot", "captures", "state_list", "breakpoint_at", "breakpoint_list",
    "breakpoint_clear", "watch_add", "watch_list", "watch_clear", "regpoint_add", "regpoint_list",
    "regpoint_clear", "comment_add", "comment_list", "comment_save", "comment_load",
    "comment_delete", "debug", "lua", "screen_signature", "image_diff", "series_diff",
    "region_track", "golden_check", "audio_measure", "audio_diff", "palette", "screen_view",
    "gfx_view", "gfx_locate", "gfx_sweep", "gfx_draft", "gfx_load", "gfx_blits", "gfx_blit_source",
    "palette_log", "gfx_film", "write", "set_register", "run_to", "run_for", "series_capture",
    "trace", "step", "input", "record", "audio_record", "memdump", "state_save", "state_load",
    "reset", "throttle", "perform", "drive", "log_wait", "stop", "start", "resume", "close"
]
RUNNING_ORDER = (
    [t for t in STOPPED_ORDER if t not in RUNNING_ANSWERS and t not in ("start", "resume")]
    + ["status", "log", "log_wait", "snapshot", "symbols_find", "throttle", "breakpoint_at",
       "breakpoint_list", "breakpoint_clear", "watch_add", "watch_list", "watch_clear",
       "regpoint_add", "regpoint_list", "regpoint_clear", "comment_list", "comment_save",
       "state_list", "captures", "machine_map", "cpu_info", "gfx_load", "palette_log",
       "gfx_film", "scan_clear", "resume",
       "start",
       "stop", "close"])
# NO SESSION, and AFTER `close`: every tool but the two that end the state go first, then
# `close` (a no-op there) and `start` last, which is the way out.
ABSENT_ORDER = [t for t in STOPPED_ORDER if t not in ("start", "close")] + ["close", "start"]
SURFACE = "the matrix probes exactly the tools the server registers"


@section("A", "states x tools: no session, stopped, running, after close (section 11)",
         [SURFACE] + [_a(st_, t) for st_, order in (("none", ABSENT_ORDER),
                                                    ("stopped", STOPPED_ORDER),
                                                    ("closed", ABSENT_ORDER),
                                                    ("running", RUNNING_ORDER))
                      for t in order])
def block_a() -> None:
    registered = sorted(t.name for t in s.mcp._tool_manager.list_tools())
    missing = sorted(set(registered) - set(PROBES))
    extra = sorted(set(PROBES) - set(registered))
    cell(SURFACE, not missing and not extra and sorted(STOPPED_ORDER) == registered,
         f"{len(registered)} tools; unprobed {missing}, unknown {extra}")
    # Every state but the first needs m68k-dual booted, and a probe that cannot boot it would
    # leave the next states judging a machine that is not there.
    if why := m68k_dual_missing():
        raise Blocked(why)
    ensure_closed()
    run_state("none", ABSENT_ORDER)            # ends with `start`: a stopped machine
    run_state("stopped", STOPPED_ORDER)        # `resume` leaves it running, then `close`
    run_state("closed", ABSENT_ORDER)          # ends with `start` again
    call("resume")
    run_state("running", RUNNING_ORDER)        # `stop`, then `close` from a run


# ======================================================= Block A by cpu: the same, per cpu
#
# m68k-dual has two 68000s. Every tool that takes `cpu` is probed naming each one, stopped and
# running, with `:maincpu` visible throughout: a probe on `:subcpu` names a cpu that is NOT the
# visible one, which is the case the model is about. A reply that touches a cpu names the one
# asked for, and the visible cpu does not move, except where MAME moves it (`step`, `focus`),
# which is put back. Releasing the machine makes the cpu it last stopped on visible again
# (`wait_for_debugger` re-sets it on the way out), so the last stop before the running half is
# on the main cpu, and one cell holds that rule itself. Nothing here asks for what MAME does not
# allow: `rpset` names no cpu, so a registerpoint on the sub cpu is a refusal, and the
# single-cpu matrix above stays as it is.

Judge = Callable[[dict[str, Any]], bool]
MAIN, SUB = ":maincpu", ":subcpu"


def _by_cpu(tag: str) -> dict[str, Callable[[], dict[str, Any]]]:
    """TOOL -> a valid call naming `tag`. Each address is one that cpu's program has: the main
    cpu's vblank handler with its hot `4a0`; on the sub cpu the idle loop at `542` as the
    control and `snd_reset`, run once at its release, as a cold target; a stop breakpoint where
    nothing executes (a vector, data)."""
    main = tag == MAIN
    return {
        "machine_map": lambda: {"cpu": tag},
        "cpu_info": lambda: {"cpu": tag},
        "symbols_find": lambda: {"name": "irq_vblank" if main else "snd_reset", "cpu": tag},
        "rom_check": lambda: {"reference_rom": REFERENCE_ROM if main else SUB_ROM,
                              "reference_addr": "0x0", "cpu": tag},
        "read_memory": lambda: {"ref": "0x400", "length": 8, "cpu": tag},
        "read_block": lambda: {"ref": "0x400", "length": 8, "cpu": tag},
        "registers": lambda: {"cpu": tag},
        "disassemble": lambda: {"ref": "0x400", "length": 8, "cpu": tag},
        "find": lambda: {"ref": "0x0", "length": 1024, "data_hex": "00", "cpu": tag},
        "history": lambda: {"limit": 4, "cpu": tag},
        "breakpoint_at": lambda: {"ref": "exception_handler" if main else "0x8", "cpu": tag},
        "breakpoint_list": lambda: {"cpu": tag},
        "breakpoint_clear": lambda: {"all": True, "cpu": tag},
        "watch_add": lambda: {"ref": "0x0", "mode": "show", "length": 2, "cpu": tag},
        "watch_list": lambda: {"cpu": tag},
        "watch_clear": lambda: {"all": True, "cpu": tag},
        "regpoint_add": lambda: {"condition": "pc==0xfffffffe", "cpu": tag},
        "regpoint_list": lambda: {"cpu": tag},
        "regpoint_clear": lambda: {"all": True, "cpu": tag},
        "comment_add": lambda: {"ref": "0x400", "text": f"by cpu {tag}", "cpu": tag},
        "comment_list": lambda: {"cpu": tag},
        "comment_delete": lambda: {"ref": "0x400", "cpu": tag},
        "write": lambda: {"ref": "0x200000", "data_hex": "00", "cpu": tag},
        "set_register": lambda: {"name": "D0", "value": 0, "cpu": tag},
        "memdump": lambda: {"ref": "0x0", "length": 16, "dest": fresh(".bin"), "cpu": tag},
        "scan_start": lambda: {"ref": "0x200000", "length": 0x100, "cpu": tag},
        "perform": lambda: {"steps": [{"op": "registers", "cpu": tag}], "settle_seconds": 2.0},
        "drive": lambda: {"act": [{"op": "registers", "cpu": tag}], "settle_seconds": 2.0},
        "run_to": lambda: ({"ref": "irq_vblank", "control": "0x4a0", "seconds": 10.0, "cpu": tag}
                           if main else {"ref": "snd_reset", "control": "0x542", "seconds": 1.0,
                                         "cpu": tag}),
        "step": lambda: {"count": 1, "cpu": tag},
        "trace": lambda: {"frames": 1, "seconds": 10.0, "cpu": tag},
        "focus": lambda: {"cpu": tag},
        "gfx_view": lambda: {"layout": BYTES_8X8, "palette": "none", "ref": "0x400", "count": 2,
                             "cpu": tag},
        "gfx_locate": lambda: {"layouts": [BYTES_8X8], "patch": [0, 0, 8, 8], "ref": "0x400",
                               "count": 4, "cpu": tag},
        "gfx_sweep": lambda: {"ref": "0x400", "count": 2, "planes": [1], "cpu": tag},
        # arming names the cpu whose writes it taps; a RAM word both programs map
        "gfx_film": lambda: {"trigger": "0x200000", "cpu": tag, "keep": 1, "frames": 2},
    }


def _refused_for_focus(r: dict[str, Any]) -> bool:
    return refused(r, "needs_call") and "focus" in str(r.get("message"))


def _names_it(tag: str) -> Judge:
    return lambda r: r.get("cpu") == tag


def _by_cpu_says(tag: str) -> dict[str, Judge]:
    """A valid call's reply on a STOPPED machine naming `tag`, from each tool's `Reply:`."""
    names = _names_it(tag)
    return {
        "machine_map": lambda r: [c["cpu"] for c in r.get("cpus", [])] == [tag],
        "cpu_info": lambda r: [c["cpu"] for c in r.get("cpus", [])] == [tag]
        and "value" in (r["cpus"][0]["pc"] or {}),
        "symbols_find": lambda r: r.get("symbols_total") == 1 and names(r),
        "rom_check": lambda r: r.get("rom_check") == "OK" and names(r),
        "read_memory": lambda r: len(str(r.get("hex"))) == 16 and names(r),
        "read_block": lambda r: len(str(r.get("hex"))) == 16 and r.get("addr_cpu") == tag,
        "registers": lambda r: "PC" in r.get("regs", {}) and names(r),
        "disassemble": lambda r: bool(r.get("lines")) and names(r),
        "find": lambda r: isinstance(r.get("hits_total"), int) and names(r),
        "history": lambda r: bool(r.get("lines")) and names(r),
        "breakpoint_at": lambda r: r.get("armed") is True and names(r),
        "breakpoint_list": lambda r: [(b.get("ref"), b.get("cpu"))
                                      for b in r.get("breakpoints", [])]
        == [("exception_handler" if tag == MAIN else "0x8", tag)],
        "breakpoint_clear": lambda r: r.get("declarations_cleared") == 1,
        "watch_add": lambda r: r.get("state") == "evaluated" and names(r)
        and r.get("reading", {}).get("available") is True,
        "watch_list": lambda r: [(w.get("ref"), w.get("cpu")) for w in r.get("watches", [])]
        == [("0x0", tag)],
        "watch_clear": lambda r: r.get("declarations_cleared") == 1,
        # `rpset` names no cpu: the visible one arms it, and another is refused naming `focus`;
        # the list narrows to any cpu, as `breakpoint_list` does.
        "regpoint_add": (lambda r: r.get("armed") is True and names(r)) if tag == MAIN
        else _refused_for_focus,
        "regpoint_list": lambda r: isinstance(r.get("regpoints"), list) and names(r),
        "regpoint_clear": lambda r: "declarations_cleared" in r,
        # `comadd` names no cpu: the comment is fed with its cpu made visible and the visible one
        # put back, which the loop's own check on the visible cpu holds
        "comment_add": lambda r: (r.get("comment") or {}).get("state") == "armed" and names(r),
        "comment_list": lambda r: [c.get("cpu") for c in r.get("comments", [])] == [tag]
        and names(r),
        "comment_delete": lambda r: (r.get("deleted") or {}).get("cpu") == tag and names(r),
        "write": lambda r: r.get("verified") is True and names(r),
        "set_register": lambda r: r.get("verified") is True and names(r),
        "memdump": lambda r: r.get("bytes") == 16 and names(r),
        "scan_start": lambda r: r.get("hits_total") == 0x100 and names(r),
        "perform": lambda r: r.get("steps_completed") == 1 and r["ran"][0].get("cpu") == tag
        and r.get("visible_cpu") == MAIN and r.get("visible_cpu_kept", {}).get("after") == MAIN,
        "drive": lambda r: r.get("act", {}).get("steps_completed") == 1
        and r["act"]["ran"][0].get("cpu") == tag,
        # A run to a main target is reached; the sub's target is cold and its silence is
        # measured by the sub's control alone.
        "run_to": (lambda r: r.get("verdict") == "TARGET" and names(r)) if tag == MAIN
        else (lambda r: r.get("verdict") == "TIMEOUT" and r.get("control_hits", 0) > 0
              and {c["cpu"] for c in r.get("controls", [])} == {SUB}),
        "step": lambda r: r.get("instructions_completed") == 1 and names(r),
        # never `names`: the top-level `cpu` is the survey's, and a run by frames stops on the
        # first cpu; the traced cpu is the trace block's own
        "trace": lambda r: (r.get("verdict") == "ELAPSED"
                            and (r.get("trace") or {}).get("cpu") == tag
                            and r["trace"].get("addresses", 0) > 0),
        "focus": lambda r: names(r) and r.get("machine_ran") is False,
        "gfx_view": lambda r: r.get("kind") == "space" and r.get("count") == 2
        and r.get("addr_cpu") == tag,
        "gfx_locate": lambda r: r.get("kind") == "space" and r.get("addr_cpu") == tag
        and r.get("candidates", [{}])[0].get("tiles_searched") == [0, 4],
        "gfx_sweep": lambda r: r.get("kind") == "space" and r.get("addr_cpu") == tag
        and r.get("candidates", [{}])[0].get("shown") == 2,
        "gfx_film": lambda r: r.get("armed_now") is True and r["film"]["cpu"] == tag,
    }


#: The per-cpu tools that answer on a RUNNING machine, and what they say there.
BY_CPU_RUNNING: dict[str, Judge] = {
    # The one list naming a cpu: that cpu alone. A symbol found in its cpu's table.
    "machine_map": lambda r: len(r.get("cpus", [])) == 1,
    "cpu_info": lambda r: len(r.get("cpus", [])) == 1
    and r["cpus"][0]["pc"].get("available") is False,
    "symbols_find": lambda r: r.get("symbols_total") == 1,
    **{t: RUNNING_SAYS[t] for t in ("breakpoint_at", "breakpoint_list", "breakpoint_clear",
                                    "watch_add", "watch_list", "watch_clear",
                                    "regpoint_list", "regpoint_clear")},
    # the store's rows, read with no machine: the stopped half deleted what it added
    "comment_list": lambda r: _says_running(r) and r.get("comments") == [],
}
#: The registerpoint call that has to name the visible cpu, on a running machine as stopped.
BY_CPU_VISIBLE_ONLY: dict[str, Judge] = {"regpoint_add": RUNNING_SAYS["regpoint_add"]}

#: MAME moves the visible cpu for these two: put back after each.
MOVES_VISIBLE = ("step", "focus")
BY_CPU_ORDER = [
    "machine_map", "cpu_info", "symbols_find", "rom_check", "read_memory", "read_block",
    "registers", "disassemble", "find", "history", "breakpoint_at", "breakpoint_list",
    "breakpoint_clear", "watch_add", "watch_list", "watch_clear", "regpoint_add", "regpoint_list",
    "regpoint_clear", "comment_add", "comment_list", "comment_delete", "write", "set_register",
    "memdump", "scan_start", "gfx_view", "gfx_locate",
    # `step` stays the last stop before `focus`: RELEASE_RESETS needs the sub's own stop, and a
    # trace by frames stops on the first cpu
    "gfx_sweep", "gfx_film", "perform", "drive", "run_to", "trace", "step", "focus",
]
BY_CPU_RUNNING_ORDER = [t for t in BY_CPU_ORDER if t not in ("perform", "drive")]
BY_CPU_SURFACE = "the per-cpu section probes exactly the tools that take `cpu`"
RELEASE_RESETS = ("a release makes the cpu the machine last stopped on visible again, "
                  "whatever `focus` showed while it was stopped")


def _on(tag: str, state: str, tool: str) -> str:
    return f"{tool} @ {state} on {tag}"


@section("A", "states x tools per cpu, on m68k-dual's two 68000s (B7.4)",
         [BY_CPU_SURFACE, RELEASE_RESETS] + [_on(tag, state, t) for tag in (MAIN, SUB)
                             for state, order in (("stopped", BY_CPU_ORDER),
                                                  ("running", BY_CPU_RUNNING_ORDER))
                             for t in order])
def block_a_by_cpu() -> None:
    taking = sorted(t.name for t in s.mcp._tool_manager.list_tools()
                    if "cpu" in inspect.signature(getattr(s, t.name)).parameters)
    probed = sorted(t for t in BY_CPU_ORDER if t not in ("perform", "drive"))
    cell(BY_CPU_SURFACE, taking == probed, f"take cpu {taking}; probed {probed}")
    for tag in (MAIN, SUB):
        ensure_closed()
        boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
        # The sub cpu leaves reset when the main one releases it, early in the boot.
        call("run_for", frames=60, seconds=10.0)
        probes, says = _by_cpu(tag), _by_cpu_says(tag)
        for tool in BY_CPU_ORDER:
            r = call(tool, **probes[tool]())
            good = says[tool](r) and (ok(r) or (tool in BY_CPU_VISIBLE_ONLY and tag == SUB))
            if tool in MOVES_VISIBLE:
                call("focus", cpu="maincpu")
            kept = cpus.visible_cpu(STATE.ses) == MAIN if STATE.ses is not None else False
            cell(_on(tag, "stopped", tool), good and kept and session_is(r, True, False),
                 said(r) if kept else f"the visible cpu moved: {said(r)}")
            if tool == "run_to":
                call("breakpoint_clear", all=True)     # the control it declared
            if tool == "scan_start":
                call("scan_clear")                     # one scan at a time: the next cpu's
        if tag == SUB:
            # The last stop was the sub's (`step`): `focus` shows the main cpu while stopped,
            # and the release makes the sub visible again, which a registerpoint then arms on.
            call("focus", cpu="maincpu")
            call("resume")
            r = call("regpoint_add", condition="pc==0xfffffffe")
            cell(RELEASE_RESETS, ok(r) and r.get("cpu") == SUB, said(r))
            call("stop")
            call("regpoint_clear", all=True)
        # The last stop on the main cpu, so it stays visible while the machine runs.
        call("run_for", frames=1, seconds=10.0)
        call("resume")
        for tool in BY_CPU_RUNNING_ORDER:
            r = call(tool, **probes[tool]())
            if tool in BY_CPU_RUNNING:
                good = ok(r) and BY_CPU_RUNNING[tool](r)
            elif tool in BY_CPU_VISIBLE_ONLY:
                # On a running machine as on a stopped one: the visible cpu's, another refused.
                good = (ok(r) and BY_CPU_VISIBLE_ONLY[tool](r)) if tag == MAIN else (
                    _refused_for_focus(r))
            else:
                good = (refused(r, "not_stopped") and isinstance(r.get("last_stop"), dict)
                        and "answers_while_running" in r)
            cell(_on(tag, "running", tool), good and session_is(r, True, True), said(r))
        call("stop")
        ensure_closed()


# ========================================================= Block B: every argument at its edge
#
# (S1 b, and interaction section 13.) Each argument at its documented MAXIMUM, one past it, far
# past it, at its minimum where one is documented, and absent where it is optional. The limits
# are each tool's own docstring's (`1..1024`, `outside (0, 600]`, "at most 128 bytes").

FAR = 10**9
WAIT_MAX = 600.0  # the documented ceiling of every wait (`inputs.WAIT_MAX_S`)
ONE_PAST_WAIT = WAIT_MAX + 0.001
PRE_GATE = "refused by the argument check, before any wait"


def is_ok(pred: Judge = lambda r: True) -> Judge:
    return lambda r: ok(r) and pred(r)


def is_refused(*codes: str) -> Judge:
    return lambda r: refused(r, *codes)


def refused_saying(words: str) -> Judge:
    """A `bad_argument` whose message holds `words`: the refusal of one judge, told from another
    layer's refusal of the same call."""
    return lambda r: refused(r, "bad_argument") and words in str(r.get("message"))


def prints(value: str) -> Judge:
    """A `debug` reply whose output is `value`, the console's hex with no leading zeros."""
    return lambda r: str(r.get("output", "")).strip().upper().lstrip("0") == value


def silent(r: dict[str, Any]) -> bool:
    """A cell whose contract does not settle the answer: whatever it is, it arrives in the
    envelope and not as an exception. The reply is in the transcript for the auditors."""
    return whole(r)


@dataclass
class Case:
    label: str
    tool: str
    kw: dict[str, Any]
    judge: Judge
    exempt: str = ""       # why this call cannot wait, when its own wait is above the ceiling
    then: str = ""         # the call that restores the machine after it


def waits(tool: str, arg: str, base: dict[str, Any], *, at_max: str = "",
          absent: str | None = None, zero_ok: bool = False) -> list[Case]:
    """The five edges of one WAIT argument. `at_max` and `absent` are the documented reasons a
    call cannot wait when they are given; without one the cell is BLOCKED by B1. `absent` is
    None for a default already inside the ceiling."""
    zero = is_ok() if zero_ok else is_refused("bad_argument")
    cases = [
        Case(f"{tool}.{arg} at max {WAIT_MAX:g}", tool, {**base, arg: WAIT_MAX}, is_ok(),
             exempt=at_max),
        Case(f"{tool}.{arg} one past max", tool, {**base, arg: ONE_PAST_WAIT},
             is_refused("bad_argument"), exempt=PRE_GATE),
        Case(f"{tool}.{arg} far past max", tool, {**base, arg: float(FAR)},
             is_refused("bad_argument"), exempt=PRE_GATE),
        Case(f"{tool}.{arg} at zero", tool, {**base, arg: 0.0}, zero),
    ]
    if absent is not None:
        cases.append(Case(f"{tool}.{arg} absent", tool, dict(base), is_ok(), exempt=absent))
    return cases


def counts(tool: str, arg: str, base: dict[str, Any], ceiling: int, reply_has: Judge,
           floor: int = 1) -> list[Case]:
    """The edges of one COUNT argument documented as `floor..ceiling`."""
    return [
        Case(f"{tool}.{arg} at max {ceiling}", tool, {**base, arg: ceiling}, is_ok(reply_has)),
        Case(f"{tool}.{arg} one past max", tool, {**base, arg: ceiling + 1},
             is_refused("bad_argument")),
        Case(f"{tool}.{arg} far past max", tool, {**base, arg: FAR}, is_refused("bad_argument")),
        Case(f"{tool}.{arg} at min {floor}", tool, {**base, arg: floor}, is_ok()),
        Case(f"{tool}.{arg} below min", tool, {**base, arg: floor - 1},
             is_refused("bad_argument")),
    ]


def hex_len(n: int) -> Judge:
    return lambda r: len(str(r.get("hex", ""))) == 2 * n


def _lua_of(n: int) -> str:
    """A script of exactly `n` characters that prints `1`: the rest is one comment line."""
    head = "print(1)\n--"
    return head + "x" * (n - len(head))


NAME_MAX = 64  # a state name: letters, digits, `_` and `-`, up to 64
MAX_NAME = "s" * NAME_MAX
RUN_ASKED = "the run is asked of a target that runs every frame: not a documented instant"
AT_A_STOP = "at a stop the log is read once, never waited on (drive's docstring)"
NO_RUN_STEP = "no step of the list lets the machine run, so nothing waits for a stop"
STOPPED_THROTTLE = "a stopped machine's throttle is pending and never waits (its docstring)"
# A line the act makes the EMULATOR log, so an `expect` has something to see: the throttle's own
# mark, which it writes there on the first frame run after it (its docstring).
SEEN_ACT: dict[str, Any] = {
    "act": [{"op": "throttle", "on": False}, {"op": "run_for", "frames": 1, "seconds": 10.0}],
    "expect": "MAME_MCP_THROTTLE#", "settle_seconds": 2.0}

STOPPED_CASES: list[Case] = [
    *counts("read_memory", "length", {"ref": "0x400"}, 1024, hex_len(1024)),
    Case("read_memory.length absent", "read_memory", {"ref": "0x400"}, is_ok(hex_len(16))),
    Case("read_memory.ref empty (contract silent)", "read_memory", {"ref": ""}, silent),
    *counts("disassemble", "length", {"ref": "0x400"}, 1024, lambda r: bool(r.get("lines"))),
    Case("disassemble.length absent", "disassemble", {"ref": "0x400"}, is_ok()),
    *counts("read_block", "length", {"tag": "maincpu"}, 1024, hex_len(1024)),
    Case("read_block.length absent", "read_block", {"tag": "maincpu"}, is_ok(hex_len(16))),
    *waits("read_block", "seconds", {"tag": "maincpu", "length": 8}, absent=None),
    Case("read_block.seconds absent", "read_block", {"tag": "maincpu", "length": 8}, is_ok()),
    Case("read_block.offset negative", "read_block", {"tag": "maincpu", "offset": -1},
         is_refused("bad_argument")),
    Case("read_block.tag and ref both empty", "read_block", {}, is_refused("bad_argument")),
    Case("read_block.tag and ref both given", "read_block", {"tag": "maincpu", "ref": "0x400"},
         is_refused("bad_argument")),
    Case("read_block.tag with whitespace", "read_block", {"tag": "main cpu"},
         is_refused("bad_argument")),
    Case("read_block.offset beside ref", "read_block", {"ref": "0x400", "offset": 4},
         is_refused("bad_argument")),
    Case("read_block.offset written 0x", "read_block", {"tag": "maincpu", "offset": "0x10",
         "length": 8}, is_ok(lambda r: r.get("offset") == 0x10)),
    Case("read_block.offset as decimal text", "read_block", {"tag": "maincpu", "offset": "16"},
         refused_saying("decimal text is refused")),
    *counts("history", "limit", {}, read.HISTORY_MAX,
            lambda r: 1 <= len(r.get("lines", [])) <= read.HISTORY_MAX),
    Case("history.limit absent", "history", {}, is_ok()),
    *counts("symbols_find", "limit", {"name": "vec"}, 50,
            lambda r: 1 <= len(r.get("symbols", [])) <= 50),
    Case("symbols_find.limit absent", "symbols_find", {"name": "vec"},
         is_ok(lambda r: len(r.get("symbols", [])) <= 10)),
    Case("symbols_find.name and linear both empty", "symbols_find", {},
         is_refused("bad_argument")),
    Case("symbols_find.name and linear both given", "symbols_find",
         {"name": "vec", "linear": "0x400"}, is_refused("bad_argument")),
    Case("symbols_find.linear not hex", "symbols_find", {"linear": "zz"},
         is_refused("bad_argument")),
    Case("symbols_find.linear bare hex", "symbols_find", {"linear": "400"},
         is_refused("bad_argument")),
    *counts("log", "limit", {"pattern": ".", "channel": "emulator"}, 400,
            lambda r: len(r.get("lines", [])) <= 400),
    Case("log.limit absent", "log", {"pattern": ".", "channel": "emulator"}, is_ok()),
    Case("log.channel guest is refused by name", "log", {"pattern": ".", "channel": "guest"},
         is_refused("bad_argument", "no_channel")),
    Case("log.channel empty", "log", {"pattern": ".", "channel": ""},
         is_refused("bad_argument", "no_channel")),
    Case("log.pattern unusable regex", "log", {"pattern": "(", "channel": "emulator"},
         is_refused("bad_argument")),
    Case("log.labels true adds labels", "log",
         {"pattern": ".", "channel": "emulator", "labels": True},
         is_ok(lambda r: isinstance(r.get("labels"), dict))),
    # The emulator log already holds a line at every stop after the boot, so these answer at
    # once: `log_wait`'s docstring promises it for a line the log already holds.
    *waits("log_wait", "seconds", {"pattern": ".", "channel": "emulator"},
           at_max="the log already holds the line: answered at once",
           absent="the log already holds the line: answered at once"),
    # A stopped machine logs nothing, so a line the log does not hold could never arrive:
    # INVALID at once, never an empty answer.
    Case("log_wait on a stopped machine, a line the log does not hold", "log_wait",
         {"pattern": "MAME_MCP never logged this", "channel": "emulator", "seconds": 5.0},
         is_refused("wait_stopped")),
    *counts("drive", "limit", {"act": [{"op": "run_for", "frames": 1, "seconds": 10.0}],
                               "settle_seconds": 2.0}, read.LOG_LIMIT_MAX,
            lambda r: len(r.get("looked", {}).get("emulator", {}).get("lines", []))
            <= read.LOG_LIMIT_MAX),
    Case("drive.limit absent", "drive", {"act": [{"op": "run_for", "frames": 1,
                                                  "seconds": 10.0}], "settle_seconds": 2.0},
         is_ok()),
    *waits("drive", "seconds", SEEN_ACT, at_max=AT_A_STOP, absent=None),
    Case("drive.seconds absent", "drive", SEEN_ACT, is_ok()),
    *waits("drive", "settle_seconds", {"act": [{"op": "registers"}]}, at_max=NO_RUN_STEP,
           absent=NO_RUN_STEP, zero_ok=True),
    *waits("perform", "settle_seconds", {"steps": [{"op": "registers"}]}, at_max=NO_RUN_STEP,
           absent=NO_RUN_STEP, zero_ok=True),
    Case("perform.steps empty (contract silent)", "perform", {"steps": [], "settle_seconds": 2.0},
         silent),
    Case("drive.act empty (contract silent)", "drive", {"act": [], "settle_seconds": 2.0}, silent),
    Case("watch_add.length show at max 128", "watch_add",
         {"ref": "0x200000", "mode": "show", "length": 128},
         is_ok(lambda r: r.get("length") == 128), then="watch_clear"),
    Case("watch_add.length show one past max", "watch_add",
         {"ref": "0x200000", "mode": "show", "length": 129}, is_refused("bad_argument")),
    Case("watch_add.length show far past max", "watch_add",
         {"ref": "0x200000", "mode": "show", "length": FAR}, is_refused("bad_argument")),
    Case("watch_add.length change at max 1024", "watch_add",
         {"ref": "0x200000", "mode": "change", "length": 1024},
         is_ok(lambda r: r.get("armed") is True and r.get("length") == 1024), then="watch_clear"),
    Case("watch_add.length change one past max", "watch_add",
         {"ref": "0x200000", "mode": "change", "length": 1025}, is_refused("bad_argument")),
    Case("watch_add.length change far past max", "watch_add",
         {"ref": "0x200000", "mode": "change", "length": FAR}, is_refused("bad_argument")),
    Case("watch_add.length negative", "watch_add", {"ref": "0x200000", "mode": "show",
                                                    "length": -1},
         is_refused("bad_argument")),
    Case("watch_add.length absent on an untyped address (contract silent)", "watch_add",
         {"ref": "0x200000", "mode": "show"}, silent, then="watch_clear"),
    Case("watch_add.fmt names a pointer class", "watch_add",
         {"ref": "0x200000", "mode": "show", "fmt": "ptr16@CODE"}, is_refused("bad_argument")),
    Case("watch_add.fmt a sized array needs no length", "watch_add",
         {"ref": "0x200000", "mode": "show", "fmt": "u16[4]"},
         is_ok(lambda r: r.get("length") == 8), then="watch_clear"),
    Case("watch_add.mode outside the vocabulary", "watch_add", {"ref": "0x200000", "mode": "poke"},
         is_refused("bad_argument")),
    Case("watch_add.by outside the vocabulary", "watch_add",
         {"ref": "200000", "mode": "show", "length": 2, "by": "guess"}, is_refused("bad_argument")),
    Case("watch_add.expr with a length", "watch_add", {"ref": "beamy", "mode": "expr", "length": 2},
         is_refused("bad_argument")),
    Case("watch_add.length capture at max 128", "watch_add",
         {"ref": "0x200000", "mode": "capture", "length": 128, "trigger": "0x200000"},
         is_ok(lambda r: r.get("length") == 128 and r.get("state") == "pending"),
         then="watch_clear"),
    Case("watch_add.length capture one past max", "watch_add",
         {"ref": "0x200000", "mode": "capture", "length": 129, "trigger": "0x200000"},
         is_refused("bad_argument")),
    Case("watch_add.trigger absent on a capture", "watch_add",
         {"ref": "0x200000", "mode": "capture", "length": 2}, is_refused("bad_argument")),
    Case("watch_add.trigger on a count watch", "watch_add",
         {"ref": "0x200000", "mode": "count", "length": 2, "trigger": "0x200000"},
         is_refused("bad_argument")),
    Case("watch_add.condition on a show watch", "watch_add",
         {"ref": "0x200000", "mode": "show", "length": 2, "condition": "wpdata==1"},
         is_refused("bad_argument")),
    Case("watch_add.condition the console cannot evaluate", "watch_add",
         {"ref": "0x200000", "mode": "change", "length": 2, "condition": "wpdata=="},
         is_refused("bad_argument")),
    Case("screen_signature.crop absent", "screen_signature", {},
         is_ok(lambda r: r.get("crop") == [0, 0, r.get("width"), r.get("height")])),
    *waits("screen_signature", "seconds", {}, absent=None),
    Case("screen_signature.seconds absent", "screen_signature", {"crop": [0, 0, 8, 8]},
         is_ok(lambda r: r.get("crop") == [0, 0, 8, 8])),
    Case("screen_signature.crop off the screen", "screen_signature",
         {"crop": [0, 0, 1, 100000]}, is_refused("bad_argument")),
    Case("screen_signature.crop of no width", "screen_signature", {"crop": [0, 0, 0, 8]},
         is_refused("bad_argument")),
    Case("lua.script at max 16000 chars", "lua", {"script": _lua_of(16000), "read_only": True},
         is_ok(lambda r: r.get("output") == "1\n")),
    Case("lua.script one past max", "lua", {"script": _lua_of(16001)},
         is_refused("bad_argument")),
    Case("lua.script far past max", "lua", {"script": _lua_of(10**6)},
         is_refused("bad_argument")),
    Case("lua.script empty", "lua", {"script": ""}, is_refused("bad_argument")),
    Case("lua.script whitespace only", "lua", {"script": "  \n "}, is_refused("bad_argument")),
    *waits("lua", "seconds", {"script": "print(1)", "read_only": True}, absent=None),
    Case("lua.seconds absent", "lua", {"script": "print(1)", "read_only": True}, is_ok()),
    Case("input.frames absent", "input", {"port": ":P1", "field": "Coin 1", "seconds": 10.0},
         is_ok(lambda r: r.get("frames") == 4 and r.get("released") is True)),
    Case("input.frames zero", "input",
         {"port": ":P1", "field": "Coin 1", "frames": 0, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("input.port empty", "input", {"port": "", "field": "Coin 1", "seconds": 10.0},
         is_refused("bad_argument")),
    Case("input.field empty", "input", {"port": ":P1", "field": "", "seconds": 10.0},
         is_refused("bad_argument")),
    Case("input.value written 0x", "input",
         {"port": ":P1", "field": "Coin 1", "value": "0x1", "frames": 1, "seconds": 10.0},
         is_ok(lambda r: r.get("value") == "0x00000001" and r.get("released") is True)),
    Case("input.value as decimal text", "input",
         {"port": ":P1", "field": "Coin 1", "value": "1", "frames": 1, "seconds": 10.0},
         refused_saying("decimal text is refused")),
    *waits("input", "seconds", {"port": ":P1", "field": "Coin 1", "frames": 1}, absent="",),
    # The frame notifier cannot end a recording on the call that begins it, so the minimum
    # is two and one is refused rather than recorded as two.
    Case("record.frames at min 2", "record", {"frames": 2, "seconds": 10.0},
         is_ok(lambda r: r.get("avi_frames") == 2)),
    Case("record.frames below min 2", "record", {"frames": 1, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("record.frames zero", "record", {"frames": 0, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("record.dest relative", "record", {"frames": 2, "dest": "rel.avi", "seconds": 10.0},
         is_refused("bad_argument")),
    *waits("record", "seconds", {"frames": 2}, absent=""),
    # The mixer writes whole updates of a fiftieth of an emulated second, so two frames is the
    # shortest span that holds one on a screen under 100 Hz; a bool is not a count.
    Case("audio_record.frames at min 2", "audio_record", {"frames": 2, "seconds": 10.0},
         is_ok(STOPPED_SAYS["audio_record"])),
    Case("audio_record.frames below min 2", "audio_record", {"frames": 1, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("audio_record.frames zero", "audio_record", {"frames": 0, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("audio_record.frames a bool", "audio_record", {"frames": True, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("audio_record.dest relative", "audio_record",
         {"frames": 2, "dest": "rel.wav", "seconds": 10.0}, is_refused("bad_argument")),
    *waits("audio_record", "seconds", {"frames": 2}, absent=""),
    *waits("throttle", "seconds", {"on": False}, at_max=STOPPED_THROTTLE, absent=None),
    Case("throttle.seconds absent", "throttle", {"on": False}, is_ok()),
    *waits("run_to", "seconds", {"ref": "irq_vblank", "control": "0x4a0"}, absent=""),
    Case("run_to.condition absent", "run_to",
         {"ref": "irq_vblank", "control": "0x4a0", "seconds": 10.0},
         is_ok(lambda r: r.get("verdict") == "TARGET"), then="breakpoint_clear"),
    Case("run_to.condition with a comma", "run_to",
         {"ref": "irq_vblank", "condition": "d0==1,d1==2", "seconds": 10.0},
         is_refused("bad_argument")),
    Case("run_to.condition that assigns", "run_to",
         {"ref": "irq_vblank", "condition": "d0=1", "seconds": 10.0}, is_refused("bad_argument")),
    Case("run_to.ref empty", "run_to", {"ref": "", "seconds": 10.0}, is_refused("bad_argument")),
    Case("run_to.control absent: refused", "run_to", {"ref": "irq_vblank", "seconds": 10.0},
         is_refused()),
    *waits("run_for", "seconds", {"frames": 1}, absent=""),
    Case("run_for.milliseconds and frames both absent", "run_for", {"seconds": 10.0},
         is_refused("bad_argument")),
    Case("run_for.milliseconds and frames both given", "run_for",
         {"milliseconds": 10, "frames": 1, "seconds": 10.0}, is_refused("bad_argument")),
    Case("run_for.frames negative", "run_for", {"frames": -1, "seconds": 10.0},
         is_refused("bad_argument")),
    *waits("trace", "seconds", {"frames": 1}, absent=""),
    Case("trace.milliseconds and frames both absent", "trace", {"seconds": 10.0},
         is_refused("bad_argument")),
    Case("trace.milliseconds and frames both given", "trace",
         {"milliseconds": 10, "frames": 1, "seconds": 10.0}, is_refused("bad_argument")),
    Case("trace.frames negative", "trace", {"frames": -1, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("trace.frames True", "trace", {"frames": True, "seconds": 10.0},
         is_refused("bad_argument")),
    Case("resume.seconds absent", "resume", {},
         is_ok(lambda r: "verdict" not in r and "halted" not in r),
         then="stop"),
    Case(f"resume.seconds at max {WAIT_MAX:g}", "resume", {"seconds": WAIT_MAX}, is_ok()),
    Case("resume.seconds one past max", "resume", {"seconds": ONE_PAST_WAIT},
         is_refused("bad_argument"), exempt=PRE_GATE),
    Case("resume.seconds far past max", "resume", {"seconds": float(FAR)},
         is_refused("bad_argument"), exempt=PRE_GATE),
    Case("resume.seconds negative", "resume", {"seconds": -1.0}, is_refused("bad_argument")),
    Case("step.count absent", "step", {}, is_ok(lambda r: r.get("instructions_completed") == 1)),
    Case("step.count zero", "step", {"count": 0}, is_refused("bad_argument")),
    Case("step.mode outside the vocabulary", "step", {"mode": "sideways"},
         is_refused("bad_argument")),
    Case(f"state_save.name at max {NAME_MAX}", "state_save", {"name": MAX_NAME}, is_ok()),
    Case("state_save.name one past max", "state_save", {"name": MAX_NAME + "s"},
         is_refused("bad_argument")),
    Case("state_save.name far past max", "state_save", {"name": "s" * 10_000},
         is_refused("bad_argument")),
    Case("state_save.name empty", "state_save", {"name": ""}, is_refused("bad_argument")),
    Case("state_save.name with a space", "state_save", {"name": "a b"},
         is_refused("bad_argument")),
    Case(f"state_load.name at max {NAME_MAX}", "state_load", {"name": MAX_NAME},
         is_ok(load_judged)),
    Case("state_load.name one past max", "state_load", {"name": MAX_NAME + "s"},
         is_refused("bad_argument")),
    Case("state_load.name far past max", "state_load", {"name": "s" * 10_000},
         is_refused("bad_argument")),
    Case("state_load.name empty", "state_load", {"name": ""}, is_refused("bad_argument")),
    Case("set_register.value at max of a 32-bit D0", "set_register",
         {"name": "D0", "value": 0xFFFFFFFF}, is_ok(lambda r: r.get("verified") is True)),
    Case("set_register.value one past max", "set_register",
         {"name": "D0", "value": 0x1_0000_0000}, is_refused("bad_argument")),
    Case("set_register.value far past max", "set_register", {"name": "D0", "value": 2**64},
         is_refused("bad_argument")),
    Case("set_register.value negative", "set_register", {"name": "D0", "value": -1},
         is_refused("bad_argument")),
    Case("set_register.value at max written 0x", "set_register",
         {"name": "D0", "value": "0xFFFFFFFF"},
         is_ok(lambda r: r.get("verified") is True and r.get("value") == "0xffffffff")),
    Case("set_register.value one past max written 0x", "set_register",
         {"name": "D0", "value": "0x100000000"}, refused_saying("does not fit")),
    Case("set_register.value as decimal text", "set_register", {"name": "D0", "value": "4660"},
         refused_saying("decimal text is refused")),
    Case("set_register.value 0x with no digits", "set_register", {"name": "D0", "value": "0x"},
         refused_saying("starts like hex")),
    Case("regpoint_clear.ref names a condition's number in the other spelling", "perform",
         {"steps": [{"op": "regpoint_add", "condition": "d0==0x7ff1"},
                    {"op": "regpoint_clear", "ref": "d0==7ff1"}], "settle_seconds": 2.0},
         is_ok(lambda r: r.get("steps_completed") == 2 and (r.get("ran") or [{}, {}])[1].get(
             "reply", {}).get("declarations_cleared") == 1)),
    # The console reads `$` as hex and `#` as decimal: 0x7ff2 is 32754.
    Case("regpoint_clear.ref names a `$` condition's number in its `#` spelling", "perform",
         {"steps": [{"op": "regpoint_add", "condition": "d0==$7ff2"},
                    {"op": "regpoint_clear", "ref": "d0==#32754"}], "settle_seconds": 2.0},
         is_ok(lambda r: r.get("steps_completed") == 2 and (r.get("ran") or [{}, {}])[1].get(
             "reply", {}).get("declarations_cleared") == 1)),
    # The fold above is the server's; these two are the console's own reading of the prefixes.
    *[Case(f"debug.command the console reads `{n}` as 0x{v}", "debug", {"command": f"print {n}"},
           is_ok(prints(v)))
      for n, v in (("#32754", "7FF2"), ("$7ff2", "7FF2"), ("0b101", "5"), ("0o17", "F"))],
    # A ref no cell declares, so the refusal holds in any order of the list.
    Case("regpoint_clear.ref never declared states the rule it is matched under",
         "regpoint_clear", {"ref": "d0==7ff3"},
         lambda r: refused(r, "unknown_ref") and all(words in " ".join(str(
             r.get("message")).split()) for words in (
                 "`regpoint_list`", f"Matching: {dec.REF_MATCH['regpoint']}."))),
    Case("perform.steps a set_register step written 0x", "perform",
         {"steps": [{"op": "set_register", "name": "D0", "value": "0x0"}], "settle_seconds": 2.0},
         is_ok(lambda r: r.get("steps_completed") == 1)),
    Case("set_register.name this cpu lacks", "set_register", {"name": "XX", "value": 0},
         is_refused()),
    Case("rom_check.reference_addr at the image's last 16 bytes", "rom_check",
         {"reference_rom": REFERENCE_ROM, "reference_addr": "0xffff0"}, is_ok()),
    Case("rom_check.reference_addr one past the image", "rom_check",
         {"reference_rom": REFERENCE_ROM, "reference_addr": "0xffff1"}, is_refused()),
    Case("rom_check.reference_addr far past the image", "rom_check",
         {"reference_rom": REFERENCE_ROM, "reference_addr": "0x10000000"}, is_refused()),
    Case("rom_check.reference_addr not hex", "rom_check",
         {"reference_rom": REFERENCE_ROM, "reference_addr": "zz"}, is_refused("bad_argument")),
    Case("memdump.length zero", "memdump", {"ref": "0x0", "length": 0, "dest": "/tmp/x"},
         is_refused("bad_argument")),
    Case("memdump.dest relative", "memdump", {"ref": "0x0", "length": 4, "dest": "rel.bin"},
         is_refused("bad_argument")),
    Case("memdump.dest already there", "memdump",
         {"ref": "0x0", "length": 4, "dest": str(TRANSCRIPT)}, is_refused("bad_argument")),
    Case("memdump.dest with a comma", "memdump",
         {"ref": "0x0", "length": 4, "dest": str(SCRATCH / "a,b.bin")}, is_refused("bad_argument")),
    Case("memdump.dest with a semicolon", "memdump",
         {"ref": "0x0", "length": 4, "dest": str(SCRATCH / "a;b.bin")}, is_refused("bad_argument")),
    Case("memdump.dest in a missing directory", "memdump",
         {"ref": "0x0", "length": 4, "dest": str(SCRATCH / "no" / "x.bin")},
         is_refused("bad_argument")),
    Case("snapshot.dest absent", "snapshot", {}, is_ok()),
    Case("snapshot.dest relative", "snapshot", {"dest": "rel.png"}, is_refused("bad_argument")),
    Case("write.data_hex empty", "write", {"ref": "0x200000", "data_hex": ""},
         is_refused("bad_argument")),
    Case("write.data_hex odd digits", "write", {"ref": "0x200000", "data_hex": "0"},
         is_refused("bad_argument")),
    # The ceiling is `read_memory`'s, since a write is read back through it; past one stub
    # packet the write is split, which the edge at the ceiling already crosses.
    Case(f"write.data_hex at max {read.READ_MAX} bytes", "write",
         {"ref": "0x200000", "data_hex": "11" * read.READ_MAX},
         is_ok(lambda r: r.get("verified") is True)),
    Case("write.data_hex one past max", "write",
         {"ref": "0x200000", "data_hex": "22" * (read.READ_MAX + 1)}, is_refused("bad_argument")),
    Case("find.data_hex empty", "find", {"ref": "0x0", "length": 16, "data_hex": ""},
         is_refused("bad_argument")),
    Case("find.symbol_class and ref both given", "find",
         {"ref": "0x0", "length": 16, "data_hex": "00", "symbol_class": "CODE"},
         is_refused("bad_argument")),
    Case("find.symbol_class and ref both absent", "find", {"data_hex": "00"},
         is_refused("bad_argument")),
    Case("find.symbol_class the table does not carry", "find",
         {"data_hex": "00", "symbol_class": "NOPE"},
         is_refused()),
    # Over the ROM, whose bytes no cell writes: its zeros make a console answer longer than one
    # window can carry, which is what `find`'s windows exist for.
    Case("find.hits past 400 keep the highest", "find",
         {"ref": "0x0", "length": 0x20000, "data_hex": "00"},
         is_ok(lambda r: r.get("hits_total", 0) > 400 and len(r.get("hits", [])) == 400
               and r.get("truncated") is True
               and r["hits"] == sorted(r["hits"], key=lambda h: int(h, 16)))),
    Case("breakpoint_at.role outside the vocabulary", "breakpoint_at",
         {"ref": "0x400", "role": "watch"}, is_refused("bad_argument")),
    Case("breakpoint_at.by outside the vocabulary", "breakpoint_at",
         {"ref": "400", "by": "guess"}, is_refused("bad_argument")),
    Case("breakpoint_at.condition on a control", "breakpoint_at",
         {"ref": "0x400", "role": "control", "condition": "d0==1"}, is_refused("bad_argument")),
    Case("breakpoint_at.ref segmented", "breakpoint_at", {"ref": "F000:9627"},
         is_refused("bad_argument")),
    Case("breakpoint_clear.ref no declaration holds", "breakpoint_clear", {"ref": "nosuch"},
         is_refused()),
    Case("breakpoint_clear.ref absent", "breakpoint_clear", {}, is_refused("bad_argument")),
    Case("breakpoint_clear.all", "breakpoint_clear", {"all": True}, is_ok()),
    Case("watch_clear.ref no declaration holds", "watch_clear", {"ref": "nosuch"},
         is_refused()),
    Case("watch_clear.ref absent", "watch_clear", {}, is_refused("bad_argument")),
    Case("watch_clear.all", "watch_clear", {"all": True}, is_ok()),
    Case("regpoint_clear.ref absent", "regpoint_clear", {}, is_refused("bad_argument")),
    Case("regpoint_clear.all", "regpoint_clear", {"all": True}, is_ok()),
    Case("machine_map.cpu absent", "machine_map", {}, is_ok(lambda r: len(r["cpus"]) == 2)),
    Case("machine_map.cpu bare tag", "machine_map", {"cpu": "maincpu"},
         is_ok(lambda r: [c["cpu"] for c in r["cpus"]] == [":maincpu"])),
    Case("machine_map.cpu full tag", "machine_map", {"cpu": ":subcpu"},
         is_ok(lambda r: [c["cpu"] for c in r["cpus"]] == [":subcpu"])),
    Case("machine_map.cpu the machine lacks", "machine_map", {"cpu": "nosuch"},
         is_refused("unknown_ref")),
    Case("debug.command empty (contract silent)", "debug", {"command": ""}, silent),
    Case("registers.from_last_stop true", "registers", {"from_last_stop": True},
         is_ok(lambda r: r.get("superseded") is True)),
]


def _tenth_control() -> tuple[Case, Case]:
    """The debugger's ten `temp` variables are the ceiling on controls: the tenth is taken,
    the eleventh is refused. The addresses are code in the vblank handler, never halted on."""
    return (Case("breakpoint_at.control the tenth", "breakpoint_at",
                 {"ref": f"{0x400 + 2 * 9:#x}", "role": "control"},
                 is_ok(lambda r: r.get("armed") is True)),
            Case("breakpoint_at.control the eleventh", "breakpoint_at",
                 {"ref": f"{0x400 + 2 * 10:#x}", "role": "control"}, is_refused()))


NO_SESSION_CASES: list[Case] = [
    Case("start.stub_port at max 65535", "start", {**BOOT, "stub_port": 65535},
         is_ok(lambda r: r.get("stub_port") == 65535), then="close"),
    Case("start.stub_port one past max", "start", {**BOOT, "stub_port": 65536},
         is_refused("bad_argument")),
    Case("start.stub_port far past max", "start", {**BOOT, "stub_port": FAR},
         is_refused("bad_argument")),
    Case("start.display on a quick start", "start", {**BOOT, "display": "secondary"},
         is_refused("bad_argument")),
    Case("start.throttle_from_frame negative", "start", {**BOOT, "throttle_from_frame": -1},
         is_refused("bad_argument")),
    Case("start.rompath relative", "start", {**BOOT, "rompath": "run/mame_roms"},
         is_refused("bad_argument")),
    Case("start.system the binary lacks", "start", {**BOOT, "system": "nosuchsystem"},
         is_refused()),
    Case("start.reference_addr at the image's last 16 bytes", "start",
         {**BOOT, "reference_addr": "0xffff0"}, is_ok(), then="close"),
    Case("start.reference_addr one past the image", "start",
         {**BOOT, "reference_addr": "0xffff1"}, is_refused()),
    Case("start.reference_addr far past the image", "start",
         {**BOOT, "reference_addr": "0x10000000"}, is_refused()),
]


def run_case(c: Case) -> dict[str, Any]:
    try:
        r = call(c.tool, b1_exempt=c.exempt, **c.kw)
    except Blocked as e:
        blocked(c.label, str(e))
        return {}
    good = c.judge(r)
    detail = said(r)
    if good and c.exempt and last_wall() > WAIT_CEILING_S:
        good, detail = False, f"took {last_wall():.1f} s where {c.exempt!r}"
    cell(c.label, good, detail if good else f"{r.get('code', '')} {detail}")
    if c.then:
        restore(c.then)
    return r


def killed_it(r: dict[str, Any]) -> bool:
    """Did this call leave no usable machine behind? A cell after it would fail for the
    machine's death and say nothing about its own tool."""
    return "exception" in r or r.get("session", {}).get("alive") is False


def run_cases_stopped(cases: list[Case]) -> None:
    """Each case on a stopped machine, booting a fresh one after a call that killed or hung it:
    the death is the cell that caused it, not every cell after."""
    for c in cases:
        if killed_it(run_case(c)):
            ensure_closed()
            boot()


# A CONSOLE COMMAND'S EDGE IS THE STUB'S OWN PACKET SIZE, which only the live session knows, so
# these three are judged at run time off the rule `Session.max_payload` states and never off a
# literal: the maximum, one past it, and the overflow.
DEBUG_EDGES = ["debug.command at the stub's packet limit answers ok",
               "debug.command one past the stub's packet limit is bad_argument at once",
               "debug.command four times the stub's packet limit is bad_argument at once"]


def _debug_edges() -> None:
    payload = STATE.ses.max_payload() if STATE.ses is not None else None
    if payload is None:
        for label in DEBUG_EDGES:
            blocked(label, "the stub advertised no packet size, so there is no limit to probe")
        return
    limit = (payload - len("qRcmd,")) // 2

    def command(n: int) -> str:
        # `print 1` padded with spaces, which the console's expression reader skips.
        return "print 1".ljust(n)

    r = call("debug", command=command(limit))
    cell(DEBUG_EDGES[0], ok(r) and r.get("output", "").strip() == "1",
         f"{limit} chars: {said(r)}")
    for label, n in ((DEBUG_EDGES[1], limit + 1), (DEBUG_EDGES[2], 4 * limit)):
        r = call("debug", command=command(n))
        cell(label, refused(r, "bad_argument") and r.get("command_chars") == n
             and r.get("limit_chars") == limit and last_wall() < 1.0,
             f"{n} chars in {last_wall()} s: {said(r)}")


# A CONDITION'S EDGE IS THE SAME PACKET, reached through the `bp` command the arming builds:
# a refusal there must leave nothing behind, neither a stored declaration nor a declared
# control nor a disarmed watch.
BP_CONDITION_EDGES = [
    "breakpoint_at.condition at the stub's packet limit is armed",
    "breakpoint_at.condition one past the stub's packet limit is bad_argument and stores nothing",
    "breakpoint_at.condition four times the stub's packet limit is bad_argument and stores "
    "nothing",
    "run_to.condition one past the stub's packet limit leaves the watch armed and declares no "
    "control",
    "breakpoint_list reads the at-limit row whole",
    "watch_list reads a foreign conditioned watchpoint row",
]


def _condition(addr: int, chars: int, evaluated: bool = True) -> str:
    """`d0==0x<zeros>1`, sized so the LONGEST command it goes out in is `chars` long: the `bp`
    at `addr` in its CONSOLE form, on the visible cpu it names, and for a declaration the
    `print {...}` that evaluates it first. Leading zeros change a hex literal's length and not
    its value."""
    cond = conditions.console_condition("d0==0x1")
    on = cpus.visible_cpu(STATE.ses) if STATE.ses is not None else None   # where it is armed
    sent = [breakpoints.bp_command(addr, cond, on)] + ([f"print {{{cond}}}"] if evaluated else [])
    zeros = chars - max(len(c) for c in sent)
    if zeros < 0:
        raise ValueError(f"no condition of this shape makes a {chars}-character command")
    return "d0==0x" + "0" * zeros + "1"


def _bp_condition_edges() -> None:
    payload = STATE.ses.max_payload() if STATE.ses is not None else None
    if payload is None:
        for label in BP_CONDITION_EDGES:
            blocked(label, "the stub advertised no packet size, so there is no limit to probe")
        return
    limit = (payload - len("qRcmd,")) // 2
    call("breakpoint_clear", all=True)
    at_limit = _condition(0x400, limit)
    r = call("breakpoint_at", ref="0x400", condition=at_limit)
    cell(BP_CONDITION_EDGES[0], ok(r) and r.get("armed") is True, f"{limit} chars: {said(r)}")
    listed = by_ref(call("breakpoint_list").get("breakpoints")).get("0x400", {})
    cell(BP_CONDITION_EDGES[4], listed.get("state") == "armed"
         and listed.get("condition") == at_limit
         and str(listed.get("entry", "")).endswith(f" if {conditions.console_condition(at_limit)}"),
         f"state {listed.get('state')}, entry of {len(str(listed.get('entry', '')))} chars")
    call("breakpoint_clear", all=True)
    for label, n in ((BP_CONDITION_EDGES[1], limit + 1), (BP_CONDITION_EDGES[2], 4 * limit)):
        before = call("breakpoint_list").get("breakpoints")
        r = call("breakpoint_at", ref="0x400", condition=_condition(0x400, n))
        after = call("breakpoint_list").get("breakpoints")
        cell(label, refused(r, "bad_argument") and r.get("command_chars") == n
             and r.get("limit_chars") == limit and isinstance(before, list) and after == before,
             f"{n} chars: {said(r)}; declarations {len(before or [])} -> {len(after or [])}")
    call("watch_add", ref="0x2031fc", mode="change", length=4)
    controls = dict(STATE.controls)
    target = STATE.resolve("irq_vblank")
    r = call("run_to", ref="irq_vblank", control="0x4a0", disarm_watches=True, seconds=5.0,
             condition=_condition(target, limit + 1, evaluated=False))
    w = by_ref(call("watch_list").get("watches")).get("0x2031fc", {})
    cell(BP_CONDITION_EDGES[3], refused(r, "bad_argument")
         and r.get("command_chars") == limit + 1 and w.get("state") == "armed"
         and STATE.controls == controls,
         f"{said(r)}; watch {w.get('state')}; controls {sorted(controls)} -> "
         f"{sorted(STATE.controls)}")
    call("watch_clear", all=True)
    call("breakpoint_clear", all=True)
    # A watchpoint row carries its condition the way a breakpoint row does, and one long
    # enough to wrap is still read as ONE foreign row.
    cond = "d0==0x" + "0" * 400 + "1"
    call("debug", command=f"wpset 0x2031fc,0x4,w,{cond}")
    r = call("watch_list")
    foreign = r.get("foreign") or []
    cell(BP_CONDITION_EDGES[5], ok(r) and len(foreign) == 1
         and str(foreign[0]).endswith(f"write if {cond}"),
         f"{len(foreign)} foreign: {[str(f)[:40] for f in foreign]}")
    call("debug", command="wpclear")


@section("B", "every argument at its documented edge, on a stopped machine",
         [c.label for c in STOPPED_CASES] + [c.label for c in _tenth_control()] + DEBUG_EDGES
         + BP_CONDITION_EDGES)
def block_b_stopped() -> None:
    boot()
    # In list order: `state_load.name at max` loads what `state_save.name at max` wrote.
    run_cases_stopped(STOPPED_CASES)
    _debug_edges()
    _bp_condition_edges()
    for i in range(9):
        call("breakpoint_at", ref=f"{0x400 + 2 * i:#x}", role="control")
    for c in _tenth_control():
        run_case(c)
    call("breakpoint_clear", all=True)


@section("B", "start's arguments at their edges, with no session",
         [c.label for c in NO_SESSION_CASES])
def block_b_start() -> None:
    ensure_closed()
    for c in NO_SESSION_CASES:
        run_case(c)


# Section 13: the readers at the address map's edges, which the machine declares at `start`.
EDGES = ("address 0", "the last mapped byte", "straddling the last mapped byte",
         "an unmapped hole", "straddling the space's end")
READERS_AT_EDGES = ("read_memory", "read_block", "disassemble", "find", "memdump")


def _edge_label(tool: str, edge: str) -> str:
    return f"{tool} at {edge}"


@section("B", "readers at the address map's edges (section 13)",
         [_edge_label(t, e) for t in READERS_AT_EDGES for e in EDGES]
         + ["history at one instruction"])
def block_b_edges() -> None:
    boot()
    reply = call("machine_map", cpu="maincpu")
    # BOTH EDGES ARE THE MACHINE'S, never a cpu's width written here, and both come from the
    # reply alone: an edge only this process could compute is one no MCP client could ask for.
    missing = {"an unmapped hole": "the program space's map leaves no hole",
               "straddling the space's end": "`machine_map` carries no program address mask"}
    at = {"address 0": (0, 8)}
    try:
        last, hole, space_end = program_edges(reply, reply["cpu"])
        at.update({"the last mapped byte": (last, 1),
                   "straddling the last mapped byte": (last - 3, 8)})
    except LookupError as exc:
        hole, space_end = None, None
        missing = dict.fromkeys(EDGES, str(exc))
    if hole is not None:
        at["an unmapped hole"] = (hole, 8)
    if space_end is not None:
        at["straddling the space's end"] = (space_end - 3, 8)
    for edge in EDGES:
        if edge not in at:
            for tool in READERS_AT_EDGES:
                blocked(_edge_label(tool, edge), missing[edge])
            continue
        addr, n = at[edge]
        ref = f"{addr:#x}"
        r = call("read_memory", ref=ref, length=n)
        # A read of a mapped byte answers it, and one past the space's end is refused; into a
        # hole the docstring names zeros only for a write-only block, so the rest is the
        # transcript's to judge.
        good = {"address 0": ok(r) and hex_len(n)(r),
                "the last mapped byte": ok(r) and hex_len(n)(r),
                "straddling the space's end": refused(r, "bad_argument")}.get(edge, whole(r))
        cell(_edge_label("read_memory", edge), good, said(r))
        r = call("read_block", ref=ref, length=n)
        # By address the block is the one the map entry names; a hole names none, and a read
        # past a block's end is refused because MAME answers zeros there in silence.
        good = {"address 0": ok(r) and r.get("offset") == 0,
                "an unmapped hole": refused(r, "unknown_ref")}.get(
            edge, refused(r, "unknown_ref", "bad_argument") or ok(r))
        cell(_edge_label("read_block", edge), good, said(r))
        r = call("disassemble", ref=ref, length=n)
        # A `read_block` refused above had already stepped the cpu for its evaluation: that
        # stop is its own, and this call must not find it as the machine's.
        cell(_edge_label("disassemble", edge), ok(r) and bool(r.get("lines"))
             and "stopped_on_its_own" not in r, said(r))
        # Past the space's end no address exists: `find` and `memdump` refuse the range, and the
        # console's `save` would hang on it besides.
        past = edge == "straddling the space's end"
        r = call("find", ref=ref, length=n, data_hex="00")
        cell(_edge_label("find", edge), refused(r, "bad_argument") if past
             else ok(r) and isinstance(r.get("hits_total"), int), said(r))
        r = call("memdump", ref=ref, length=n, dest=fresh(".bin"))
        good = refused(r, "bad_argument") if past else ok(r) and r.get("bytes") == n
        cell(_edge_label("memdump", edge), good, said(r))
        if killed_it(r):
            ensure_closed()
            boot()
    r = call("history", limit=1)
    cell("history at one instruction", ok(r) and len(r.get("lines", [])) == 1, said(r))


# ================================================== Block C: the tools that share state, in pairs
#
# (S1 c.) Each section is one item of the plan's interaction list: a sequence where one tool's
# effect is what the next one reads. The contract of each cell is the docstring of the tool that
# answers it.


def by_ref(items: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {str(w.get("ref")): w for w in items or []}


# A FAULT PLANTED FROM THE HARNESS, never from the server: one Lua chunk that reaches the tap's
# item in the server's registry and makes the tap's own body raise at its next write, the way a
# body with a bug would; uncaught, it reads as a tap that saw nothing (`mame_callbacks` says why).
# `plant` is Lua over the item `t`; `said` is a Lua expression printed at the same instant, a
# baseline the cell reads back.
FAULT = "planted fault"


def plant_fault(registry: str, item_id: str, plant: str, said: str = '""') -> dict[str, Any]:
    return call("lua", read_only=True, script=(
        f'local t = _G.{registry} and _G.{registry}.items["{item_id}"]\n'
        f'if t == nil then error("no item {item_id} in {registry}") end\n'
        f"{plant}\nprint(\"planted \" .. tostring({said}))"))


def planted_at(r: dict[str, Any]) -> int:
    """The baseline a `plant_fault` printed, or -1 when it did not answer."""
    m = re.search(r"planted (\d+)", str(r.get("output") or ""))
    return int(m.group(1)) if m else -1


def raised(w: dict[str, Any]) -> tuple[int, str]:
    """A reply's `callback_errors`, as (count, first), (-1, "") when it carries none."""
    errors = w.get("callback_errors") or {}
    return int(errors.get("count", -1)), str(errors.get("first") or "")


# A DUMPER FAULTED FROM THE HARNESS: the item's `endianness`, which only its dumper reads, and
# only once its `.tmp` is open (the head's last line), is made to raise when formatted, so the
# dump fails half-way through a write, as a dumper with a bug would. `mame_callbacks`'s guard
# then closes the file, logs `MCP_DUMP_FAILED <id>` once per run of failures, and the dump on
# disk stays the last one finished, which a later stop reads as superseded.
DUMPER_FAULT = ('t.endianness = setmetatable({}, {__tostring = function() error("' + FAULT
                + '") end})')


def open_files(pid: object) -> list[str] | None:
    """The paths `lsof` lists open in `pid`, resolved as `lsof` resolves them (`/var` is
    `/private/var` on this host), or None when it could not say."""
    r = subprocess.run(["lsof", "-a", "-p", str(pid), "-F", "n"], capture_output=True,
                       text=True, check=False)
    names = [ln[1:] for ln in r.stdout.splitlines() if ln.startswith("n")]
    return names if r.returncode == 0 and names else None


def dumper_fault_cell(label: str, registry: str, item_id: str, ref: str, dump: Path) -> None:
    """`label` judged over the item `item_id` of `registry`, whose dump is `dump`, on the stop
    survey, the one reading that judges a dump against the frame: before the plant the dump is
    current (the control), after it the guard's line is in `error.log` once over two stops, the
    `.tmp` the dumper opened exists and is closed (`lsof`, itself seen to list `error.log`
    open), and the dump read at the stop is superseded, its `why` naming the planted error."""
    status = call("status")
    errorlog, pid = Path(str(status.get("errorlog_path"))), status.get("pid")
    before = by_ref(call("run_for", frames=2, seconds=10.0).get("watches")).get(ref, {})
    at = planted_at(plant_fault(registry, item_id, DUMPER_FAULT, "t.seq"))
    call("run_for", frames=4, seconds=10.0)
    w = by_ref(call("run_for", frames=4, seconds=10.0).get("watches")).get(ref, {})
    said_line = f"{callbacks.DUMP_FAILED} {item_id} "
    logged = [ln for ln in errorlog.read_text(errors="replace").splitlines() if said_line in ln]
    tmp = Path(os.path.realpath(f"{dump}.tmp"))
    errorlog = Path(os.path.realpath(errorlog))
    names = open_files(pid)
    why = str(w.get("why"))
    still_open = None if names is None else str(tmp) in names
    detail = (f"before superseded {before.get('superseded')}; planted at seq {at}; logged "
              f"{logged}; .tmp there {tmp.exists()}, open {still_open}; "
              f"after superseded {w.get('superseded')}, why {why[-120:]!r}")
    if at < 0:
        blocked(label, f"the dumper fault was not planted, so nothing was faulted: {detail}")
        return
    if names is None or not any(n == str(errorlog) for n in names):
        blocked(label, f"lsof could not be read, or did not list error.log open: {detail}")
        return
    cell(label, before.get("superseded") is False and len(logged) == 1
         and FAULT in logged[0] and tmp.exists() and str(tmp) not in names
         and w.get("superseded") is True and "the dumper raised writing a newer one" in why
         and FAULT in why, detail)


def writes(r: dict[str, Any]) -> int:
    return int(r.get("session", {}).get("altering_writes", -1))


SEQ = re.compile(r"#(\d+)")


def seq_of(r: dict[str, Any]) -> int | None:
    """The console sequence number a reply names, in its `mark` (a throttle) or its `call`."""
    m = SEQ.search(str(r.get("mark") or r.get("call") or ""))
    return int(m.group(1)) if m else None


C1 = [
    "a symbol breakpoint comes back rearmed",
    "a raw-address control over the same build comes back rearmed",
    "a change watch by symbol comes back rearmed",
    "a count watch comes back rearmed, its install sent again",
    "a show watch and an expr watch come back evaluated",
    "nothing is stale, unresolved or unarmable over the same build",
    "held counts every declaration the store kept",
    "every breakpoint row the store brought back says inherited",
    "every watch row the store brought back says inherited",
    "the inherited raw-address control is listed armed",
    "the inherited count watch tallies on the next run",
    "a declaration made this session says inherited false",
    "a condition is stored as typed and replied as the console reads it",
    "a raw address over another build comes back stale, not armed",
    "a symbol over another build comes back rearmed",
    "the stale row is listed stale",
    "declaring the stale address again adopts it",
]


@section("C", "1. declarations across start", C1)
def c1_declarations() -> None:
    # A COPY of the table, so the second build below is this file edited, under the same key.
    table = SCRATCH / "c1-symbols.yaml"
    table.write_text(Path(SYMBOLS).read_text())
    boot(symbols=str(table))
    # The STOP is on a routine a healthy boot never runs: re-armed on the vblank it would cut
    # every run of this section at its first frame, which is the re-arm working, not a finding.
    call("breakpoint_at", ref="exception_handler")
    call("breakpoint_at", ref="0x4a0", role="control")
    call("watch_add", ref="main_ram", mode="change", length=4)
    call("watch_add", ref="0x203200", mode="show", length=2)
    call("watch_add", ref="0x2031fc", mode="count", length=4)
    call("watch_add", ref="beamy", mode="expr")
    call("close")
    r = boot(symbols=str(table))
    decl = r.get("declarations", {})
    rearm = decl.get("rearm", {})
    # EACH ENTRY NAMES ITS REF AND ITS CPU: every declaration here was made on the main cpu, the
    # one visible after a start, and an expr watch has none (the console evaluates it there).
    rearmed, evaluated = rearm_pairs(rearm, "rearmed"), rearm_pairs(rearm, "evaluated")
    cell(C1[0], ("exception_handler", ":maincpu") in rearmed, str(rearm))
    cell(C1[1], ("0x4a0", ":maincpu") in rearmed, str(rearmed))
    cell(C1[2], ("main_ram", ":maincpu") in rearmed, str(rearmed))
    cell(C1[3], ("0x2031fc", ":maincpu") in rearmed, str(rearmed))
    cell(C1[4], {("0x203200", ":maincpu"), ("beamy", None)} <= set(evaluated), str(evaluated))
    cell(C1[5], not any(rearm.get(k) for k in ("stale", "unresolved", "unarmable")), str(rearm))
    cell(C1[6], decl.get("held") == 6, f"held={decl.get('held')}")
    bps = call("breakpoint_list").get("breakpoints", [])
    cell(C1[7], len(bps) == 2 and all(b.get("inherited") is True for b in bps),
         str([(b.get("ref"), b.get("inherited")) for b in bps]))
    ws = call("watch_list").get("watches", [])
    cell(C1[8], len(ws) == 4 and all(w.get("inherited") is True for w in ws),
         str([(w.get("ref"), w.get("inherited")) for w in ws]))
    row4a0 = by_ref(bps).get("0x4a0", {})
    cell(C1[9], row4a0.get("state") == "armed" and row4a0.get("role") == "control", str(row4a0))
    # m68k-dual's vblank handler starts writing this counter only once the boot has settled, a
    # few frames in: sixty frames are past that, so a zero here would be the tally's, not the
    # game's.
    r = call("run_for", frames=60, seconds=10.0, disarm_watches=True)
    tally = by_ref(r.get("watches")).get("0x2031fc", {})
    cell(C1[10], tally.get("installed") is True and tally.get("total", 0) > 0,
         f"{r.get('verdict')} {tally}"[:160])
    call("breakpoint_at", ref="vec_trapv")
    bps = by_ref(call("breakpoint_list").get("breakpoints"))
    cell(C1[11], bps.get("vec_trapv", {}).get("inherited") is False,
         str(bps.get("vec_trapv")))
    call("breakpoint_clear", ref="vec_trapv")
    typed = "d0==irq_vblank"
    r = call("breakpoint_at", ref="vec_trapv", condition=typed)
    (rows,) = json.loads(Path(str(decl.get("path"))).read_text()).values()
    kept = by_ref(rows).get("vec_trapv", {}).get("condition")
    cell(C1[12], kept == typed and r.get("condition_typed") == typed
         and r.get("condition") == f"d0=={STATE.resolve('irq_vblank'):#x}",
         f"stored {kept!r}, replied {r.get('condition')!r} / {r.get('condition_typed')!r}")
    call("breakpoint_clear", ref="vec_trapv")
    call("close")
    # ANOTHER BUILD: the same file under the same key, one symbol more, so another fingerprint.
    table.write_text(table.read_text() + "  - addr: 0x00000500\n    name: c1_extra\n")
    r = boot(symbols=str(table))
    rearm = r.get("declarations", {}).get("rearm", {})
    cell(C1[13], ("0x4a0", ":maincpu") in rearm_pairs(rearm, "stale")
         and ("0x4a0", ":maincpu") not in rearm_pairs(rearm, "rearmed"),
         str(rearm))
    cell(C1[14], {("exception_handler", ":maincpu"), ("main_ram", ":maincpu")}
         <= set(rearm_pairs(rearm, "rearmed")),
         str(rearm))
    row4a0 = by_ref(call("breakpoint_list").get("breakpoints")).get("0x4a0", {})
    cell(C1[15], row4a0.get("state") == "stale", str(row4a0))
    r = call("breakpoint_at", ref="0x4a0", role="control")
    row4a0 = by_ref(call("breakpoint_list").get("breakpoints")).get("0x4a0", {})
    cell(C1[16], ok(r) and r.get("armed") is True and row4a0.get("state") == "armed",
         f"{said(r)} / {row4a0.get('state')}")


C2_WATCHES = ("0x203200", "0x2031fc", "0x20351c", "beamy", "[main_ram]")
C2 = [
    "state_load's survey carries every declared watch",
    "a show watch after state_load reads the restored bytes",
    "the change watch is listed armed after state_load",
    "the change watch still fires after state_load",
    "the count watch after state_load is in a documented state (contract silent)",
    "the expr watch evaluates after state_load",
    "the pointer watch re-resolves after state_load",
    "watch_list after state_load lists all five in a documented state",
]
WATCH_STATES = {"evaluated", "armed", "disabled", "gone", "stale", "unresolved", "tallied",
                "no_dump_yet", "install_failed", "not_installed", "null_pointer", "pending",
                "install_lost"}


@section("C", "2. watches across state_load", C2)
def c2_watches_across_load() -> None:
    boot()
    call("watch_add", ref="0x203200", mode="show", length=2)
    call("watch_add", ref="0x2031fc", mode="change", length=4)
    call("watch_add", ref="0x20351c", mode="count", length=1)
    call("watch_add", ref="beamy", mode="expr")
    call("watch_add", ref="[main_ram]", mode="show", length=4)
    call("run_for", frames=2, seconds=10.0, disarm_watches=True)
    before = by_ref(call("watch_list").get("watches")).get("0x203200", {}).get("reading", {}).get(
        "value")
    call("state_save", name="c2")
    call("run_for", frames=10, seconds=10.0, disarm_watches=True)
    r = call("state_load", name="c2")
    seen = by_ref(r.get("watches"))
    cell(C2[0], set(C2_WATCHES) <= set(seen), f"{said(r)}; {sorted(seen)}")
    after = seen.get("0x203200", {}).get("reading", {}).get("value")
    cell(C2[1], after == before, f"saved {before}, after load {after}")
    listed = by_ref(call("watch_list").get("watches"))
    cell(C2[2], listed.get("0x2031fc", {}).get("state") == "armed", str(listed.get("0x2031fc")))
    hit = call("resume", seconds=5.0)
    cell(C2[3], hit.get("verdict") == "OTHER_STOP"
         and str(hit.get("how", "")).startswith("watch 0x2031fc"), said(hit))
    if hit.get("verdict") != "OTHER_STOP":
        call("stop")
    cell(C2[4], listed.get("0x20351c", {}).get("state") in WATCH_STATES,
         str(listed.get("0x20351c"))[:140])
    cell(C2[5], isinstance(seen.get("beamy", {}).get("reading", {}).get("value"), int),
         str(seen.get("beamy")))
    ptr = seen.get("[main_ram]", {})
    cell(C2[6], ptr.get("state") in ("evaluated", "null_pointer") and "pointer" in ptr
         or ptr.get("state") == "null_pointer", str(ptr)[:140])
    cell(C2[7], set(listed) == set(C2_WATCHES)
         and all(w.get("state") in WATCH_STATES for w in listed.values()),
         str({k: w.get("state") for k, w in listed.items()}))


C3_TRIO = ("thread_errors", "console_reruns", "resent")
C3_CARRY = ("lua", "input", "record", "audio_record", "screen_signature", "read_block")
C3_BARE = ("throttle", "state_save", "state_load")
C3 = [
    "the console sequence numbers of the calls strictly increase",
    "a console command evaluated the stopped throttle's line before lua's own",
    "a console command on a stopped machine evaluates the Lua line ahead",
    "the stopped throttle's mark landed: throttles_pending is empty",
    "no throttle is recorded as not applied",
    "session.console agrees with the kept log",
    *[f"the per-call trio rides on {t}" for t in C3_CARRY],
    *[f"the per-call trio is absent from {t}" for t in C3_BARE],
]


def _pending_after(deadline_s: float) -> int:
    """The lines still ahead in the Lua console's pipe, read off the process log (a file read,
    which sends the stub nothing) until none is or `deadline_s` passes: the console's reader is a
    thread, so one read can land while it is still taking a line."""
    scratch = STATE.scratch
    assert scratch is not None
    end = time.monotonic() + deadline_s
    while (left := transport.pending_lines(scratch)) and time.monotonic() < end:
        time.sleep(0.2)
    return left


@section("C", "3. the Lua console's shared sequence", C3)
def c3_console_sequence() -> None:
    boot()
    replies = {
        "throttle": call("throttle", on=False),
        "lua": call("lua", script="print(2)", read_only=True),
        "input": call("input", port=":P1", field="Coin 1", frames=1, seconds=10.0),
        "record": call("record", frames=2, seconds=10.0),
        "audio_record": call("audio_record", frames=2, seconds=10.0),
        "screen_signature": call("screen_signature"),
        "read_block": call("read_block", tag="maincpu", length=4),
        "state_save": call("state_save", name="c3"),
    }
    replies["state_load"] = call("state_load", name="c3")
    numbered = [(t, n) for t, r in replies.items() if (n := seq_of(r)) is not None]
    nums = [n for _, n in numbered]
    cell(C3[0], len(nums) >= 4 and all(a < b for a, b in zip(nums, nums[1:], strict=False)),
         str(numbered))
    st_ = call("status")
    log = Path(str(st_.get("stdout_path", "")))
    cell(C3[1], console_ran_the_throttle_first(replies["lua"], replies["throttle"],
                                               log.read_bytes() if log.is_file() else b""),
         f"lines_ahead={replies['lua'].get('lines_ahead')}, ends in order: "
         f"{sentinel_order(log.read_bytes()) if log.is_file() else 'no log'}")
    cell(C3[3], st_.get("throttles_pending") == [], str(st_.get("throttles_pending")))
    cell(C3[4], "throttles_not_applied" not in st_.get("session", {}),
         str(st_.get("session", {}).get("throttles_not_applied")))
    # THE MECHANISM ITSELF, with nothing but one debugger command between the line and the read,
    # after the status above has judged the first throttle's mark.
    call("throttle", on=False)
    ahead = _pending_after(0.0)
    call("debug", command="print 0")
    after = _pending_after(3.0)
    cell(C3[2], ahead == 1 and after == 0,
         f"ahead after the throttle: {ahead}; after `print 0`: {after}")
    # THE SERVER PROMISES TO COUNT what the console did, not that its reader never dies: a
    # reader's death is MAME's, and on some hosts it is common. So the counts are held against
    # the process log, read by the cell's own rule, and only a disagreement fails. They are
    # `close`'s: before it, the counts hold only what the lua-family calls read back, and a
    # death after the last of them is on the log and in nobody's count yet.
    stdout = log.read_bytes() if log.is_file() else b""
    console = call("close").get("session", {}).get("console", {})
    if not console or console_in_log(stdout)["sentinels"] == 0:
        blocked(C3[5], f"nothing to compare: console={console}, sentinels in {log}: none")
    else:
        off = console_disagreement(stdout, console)
        cell(C3[5], not off, f"{console}; the log, where it differs: {off}")
    for t in C3_CARRY:
        r = replies[t]
        cell(f"the per-call trio rides on {t}", all(k in r for k in C3_TRIO),
             str({k: r.get(k) for k in C3_TRIO}))
    for t in C3_BARE:
        r = replies[t]
        cell(f"the per-call trio is absent from {t}", ok(r) and not any(k in r for k in C3_TRIO),
             said(r))


#: (door, the calls that open it, whether it must mark the session). From each tool's own
#: docstring: `write`, `set_register`, `reset` and `state_load` MODIFY; `debug` counts a mutating
#: command and a bare assignment and not its bookkeeping; raw `lua` alters unless declared
#: read-only; reads, saves and advances do not.
C4_DOORS: list[tuple[str, list[tuple[str, dict[str, Any]]], bool | None]] = [
    ("write", [("write", {"ref": "0x200000", "data_hex": "00"})], True),
    ("set_register", [("set_register", {"name": "D1", "value": 1})], True),
    ("debug with a fill", [("debug", {"command": "fill 0x200000,2,0x12,0x34"})], True),
    ("debug with a bare assignment", [("debug", {"command": "d0=1234"})], True),
    ("debug with a comparison", [("debug", {"command": "print {d0==1234}"})], False),
    ("debug reading", [("debug", {"command": "dasm /dev/null,0x400,1"})], False),
    ("debug bookkeeping", [("debug", {"command": "bpset 0x25a4"}),
                           ("debug", {"command": "bpclear"})], False),
    ("debug bplist", [("debug", {"command": "bplist"})], False),
    ("debug save", [("debug", {"command": "save {dest},0,10"})], False),
    ("perform carrying a write", [("perform", {"steps": [
        {"op": "write", "ref": "0x200000", "data_hex": "00"}], "settle_seconds": 2.0})], True),
    ("perform carrying a read", [("perform", {"steps": [
        {"op": "read_memory", "ref": "0x400"}], "settle_seconds": 2.0})], False),
    ("drive carrying a write", [("drive", {"act": [
        {"op": "write", "ref": "0x200000", "data_hex": "00"}], "settle_seconds": 2.0})], True),
    ("lua by default", [("lua", {"script": "print(1)"})], True),
    ("lua declared read_only", [("lua", {"script": "print(1)", "read_only": True})], False),
    ("read_block", [("read_block", {"tag": "maincpu", "length": 4})], False),
    ("screen_signature", [("screen_signature", {})], False),
    ("state_save", [("state_save", {"name": "c4"})], False),
    ("run_for", [("run_for", {"frames": 1, "seconds": 10.0})], False),
    ("step", [("step", {})], False),
    ("reset", [("reset", {})], True),
    ("state_load", [("state_load", {"name": "c4"})], True),
    ("input (contract silent)", [("input", {"port": ":P1", "field": "Coin 1", "frames": 1,
                                            "seconds": 10.0})], None),
]


def _c4(door: str, alters: bool | None) -> str:
    verb = {True: "marks", False: "does not mark", None: "is counted as it is"}[alters]
    return f"{door} {verb} the session"


C4 = ["a fresh session is not altered"] + [_c4(d, a) for d, _, a in C4_DOORS] + [
    "a read_only lua call is recorded as the caller's word"]


@section("C", "4. altered through every door", C4)
def c4_altered() -> None:
    r = boot()
    cell(C4[0], r.get("session", {}).get("altered") is False and writes(r) == 0,
         str(r.get("session")))
    for door, calls, alters in C4_DOORS:
        w0 = writes(call("status"))
        r = {}
        for tool, kw in calls:
            kw = {k: (v.format(dest=fresh(".bin")) if isinstance(v, str) and "{dest}" in v
                      else v) for k, v in kw.items()}
            r = call(tool, **kw)
        w1 = writes(r)
        moved = w1 > w0
        good = whole(r) and (alters is None or moved is alters)
        if alters:
            good = good and r["session"].get("altered") is True
        cell(_c4(door, alters), good, f"writes {w0} -> {w1}: {said(r, 80)}")
    ses = call("status").get("session", {})
    cell(C4[-1], ses.get("read_only_claims", 0) >= 1 and "caller" in str(ses.get("note")),
         f"claims={ses.get('read_only_claims')}")


C5 = [
    "run_to with the control named in the call reaches its target",
    "run_to with a control declared by breakpoint_at reaches its target",
    "run_to with a condition stops when it holds",
    "and the word reads the value the condition named",
    "run_to with a HOT control and a target that never runs is a TIMEOUT that counted",
    "and a TIMEOUT leaves the machine stopped",
    "run_to with a COLD control is control_silent with the listing and a hint",
    "run_to at a ref holding a stop declaration is refused",
    "run_for by frames with a debug breakpoint on the vblank ends OTHER_STOP",
    "run_for by milliseconds with the same breakpoint ends OTHER_STOP",
    "run_for by frames stops at the first hit of a breakpoint typed through debug, naming it",
    "and with that row cleared the same run reaches its bound",
    "step over runs one instruction through the console",
    "step into three instructions completes three",
    "without disarm_watches a change watch cuts run_to",
    "with disarm_watches run_to reaches its target and names the watch",
    "and the watch is armed again after the run",
]


@section("C", "5. advancing with stops declared", C5)
def c5_advancing() -> None:
    boot()
    r = call("run_to", ref="irq_vblank", control="0x4a0", seconds=10.0)
    cell(C5[0], r.get("verdict") == "TARGET" and "0x4a0" in str(r.get("controls")), said(r))
    call("breakpoint_clear", all=True)
    call("breakpoint_at", ref="irq_vblank", role="control")
    r = call("run_to", ref="0x4a0", seconds=10.0)
    cell(C5[1], r.get("verdict") == "TARGET", said(r))
    # The vblank handler adds one to the long at 0x2031fc every frame once the boot settles
    # (read off the machine, frame by frame), so a value three frames ahead is a condition that
    # holds within the bound.
    n = int(call("read_memory", ref="0x2031fc", length=4).get("hex", "0"), 16)
    cond = f"d@0x2031fc=={n + 3:#x}"
    r = call("run_to", ref="0x4a0", seconds=10.0, condition=cond)
    cell(C5[2], r.get("verdict") == "TARGET" and r.get("condition") == cond, said(r))
    after = int(call("read_memory", ref="0x2031fc", length=4).get("hex", "0"), 16)
    cell(C5[3], after == n + 3, f"{n} -> {after}")
    r = call("run_to", ref="exception_handler", seconds=3.0)
    cell(C5[4], r.get("verdict") == "TIMEOUT" and r.get("control_hits", 0) > 0,
         f"{said(r)} hits={r.get('control_hits')}")
    st_ = call("status")
    cell(C5[5], st_.get("running") is False, said(st_))
    call("breakpoint_clear", all=True)
    r = call("run_to", ref="exception_handler", control="vec_chk", seconds=3.0)
    cell(C5[6], refused(r, "control_silent") and "verdict" not in r
         and bool(r.get("control_dasm")) and all("dasm" in row for row in r["control_dasm"])
         and "note" in r, said(r))
    call("breakpoint_clear", all=True)
    call("breakpoint_at", ref="irq_vblank")
    r = call("run_to", ref="irq_vblank", control="0x4a0", seconds=5.0)
    cell(C5[7], refused(r), said(r))
    call("breakpoint_clear", all=True)
    call("debug", command="bpset 0x400")
    r = call("run_for", frames=5, seconds=10.0)
    cell(C5[8], r.get("verdict") == "OTHER_STOP", said(r))
    r = call("run_for", milliseconds=200, seconds=10.0)
    cell(C5[9], r.get("verdict") == "OTHER_STOP", said(r))
    call("debug", command="bpclear")
    # THE VBLANK HANDLER IS HOT EVERY FRAME, so a row there is hit well inside the bound: the
    # run ends at that hit, not absorbed into the frames. `polls` is the frames run, plus the
    # landing on the hit when it came before the tick, plus the aligning `gvblank` a
    # mid-frame stop spends first.
    call("debug", command="bpset 4a0")
    r = call("run_for", frames=60, seconds=10.0)
    ran = int(r.get("frame_after", 0)) - int(r.get("frame_before", 0))
    polls = int(r.get("polls", -1))
    cell(C5[10], r.get("verdict") == "OTHER_STOP" and int(str(r.get("pc", "0")), 16) == 0x4A0
         and "typed through `debug`" in str(r.get("how")) and polls - ran in (0, 1, 2),
         f"{r.get('verdict')} pc={r.get('pc')} polls={polls} ran={ran} how={r.get('how')}")
    call("debug", command="bpclear")
    r = call("run_for", frames=60, seconds=10.0)
    ran = int(r.get("frame_after", 0)) - int(r.get("frame_before", 0))
    cell(C5[11], r.get("verdict") == "ELAPSED" and ran == 60, f"ran={ran}: {said(r)}")
    pc0 = call("registers").get("regs", {}).get("PC")
    r = call("step", count=1, mode="over")
    cell(C5[12],
         r.get("mode") == "over" and r.get("instructions_completed") == 1 and r.get("pc") != pc0,
         f"{pc0} -> {r.get('pc')}: {said(r)}")
    r = call("step", count=3, mode="into")
    cell(C5[13], r.get("instructions_completed") == 3 and "regs" in r, said(r))
    call("breakpoint_at", ref="irq_vblank", role="control")
    call("watch_add", ref="0x2031fc", mode="change", length=4)
    # From the handler's second instruction, BEFORE its write to the watched long at 0x40e:
    # from anywhere past it the target comes first and the watch has nothing to cut.
    call("run_to", ref="0x404", seconds=5.0, disarm_watches=True)
    r = call("run_to", ref="0x4a0", seconds=5.0)
    cell(C5[14], r.get("verdict") == "OTHER_STOP" or refused(r, "cut_by_other_stop"), said(r))
    r = call("run_to", ref="0x4a0", seconds=5.0, disarm_watches=True)
    cell(C5[15], r.get("verdict") == "TARGET" and "0x2031fc" in str(r.get("disarmed_watches")),
         f"{said(r)} disarmed={r.get('disarmed_watches')}")
    w = by_ref(call("watch_list").get("watches")).get("0x2031fc", {})
    cell(C5[16], w.get("state") == "armed", str(w)[:120])


#: The readers the server's `instructions` name as refusing on a running machine.
RUNNING_READERS = ("registers", "read_memory", "disassemble", "find", "history", "memdump",
                   "debug", "step", "run_to", "run_for", "write", "set_register", "reset",
                   "rom_check", "lua", "read_block", "input", "record", "audio_record",
                   "state_save", "state_load", "trace")
C6 = [
    "every reader the instructions name refuses not_stopped while it runs",
    "log answers while it runs",
    "log_wait answers while it runs",
    "throttle applies at once while it runs, with the frame",
    "registers(from_last_stop=True) answers superseded with as_of while it runs",
    "a breakpoint armed while it runs stops it, found by the first contact",
    "the readers answer again at that stop",
    "stop interrupts a run and surveys it",
    "and the readers answer after it",
]


@section("C", "6. the running machine", C6)
def c6_running() -> None:
    boot()
    call("resume")
    bad = [t for t in RUNNING_READERS if not refused(call(t, **PROBES[t]()), "not_stopped")]
    cell(C6[0], not bad, f"answered: {bad}")
    cell(C6[1], ok(call("log", pattern=".", channel="emulator", limit=3)), said(PENDING[-1]
                                                                                ["reply"]))
    r = call("log_wait", pattern=".", channel="emulator", seconds=5.0)
    cell(C6[2], ok(r) and "line" in r, said(r))
    r = call("throttle", on=False, seconds=5.0)
    cell(C6[3], ok(r) and r.get("pending") is False and isinstance(r.get("frame"), int), said(r))
    r = call("registers", from_last_stop=True)
    cell(C6[4], ok(r) and r.get("superseded") is True and "last_stop" in r, said(r))
    call("breakpoint_at", ref="irq_vblank")
    time.sleep(0.3)
    r = call("status")
    cell(C6[5], r.get("running") is False and "stopped_on_its_own" in r, said(r))
    r = call("registers")
    cell(C6[6], ok(r), said(r))
    call("breakpoint_clear", all=True)
    call("resume")
    r = call("stop")
    cell(C6[7], r.get("interrupted") is True and "regs" in r, said(r))
    r = call("disassemble", ref="0x400", length=4)
    cell(C6[8], ok(r), said(r))


C7_MODES = ("show", "count", "expr", "pointer")
C7_ADVANCES = ("run_for", "run_to", "step")
C7_RAISED = ("a count watch whose tap raises counts each error beside its total, never an empty "
             "census")
C7_DUMPER = ("a count watch whose dumper raises after its open logs MCP_DUMP_FAILED once, "
             "closes its .tmp, and the superseded dump's why names the error")
C7 = [f"a {m} watch under {a}" for m in C7_MODES for a in C7_ADVANCES] + [
    C7_RAISED,
    C7_DUMPER,
    "a change watch cuts run_for, naming its writer",
    "a change watch cuts run_to",
    "a change watch rides a step's survey, evaluated",
]
C7_REF = {"show": "0x203200", "count": "0x20351c", "expr": "beamy", "pointer": "[main_ram]"}


def _c7_judge(mode: str, w: dict[str, Any], stop: dict[str, Any]) -> bool:
    reading = w.get("reading", {})
    if mode == "show":
        return (w.get("state") == "evaluated" and reading.get("available") is True
                and "value" in reading and "raw_hex" in reading)
    if mode == "count":
        return w.get("installed") is True and w.get("frame_as_of") == stop.get("frame")
    if mode == "expr":
        return isinstance(reading.get("value"), int) and "hex" in reading
    return w.get("state") in ("evaluated", "null_pointer")


@section("C", "7. watch modes x advances", C7)
def c7_watch_modes() -> None:
    boot()
    call("watch_add", ref="0x203200", mode="show", length=2)
    call("watch_add", ref="0x20351c", mode="count", length=1)
    call("watch_add", ref="beamy", mode="expr")
    call("watch_add", ref="[main_ram]", mode="show", length=4)
    advances: dict[str, Callable[[], dict[str, Any]]] = {
        "run_for": lambda: call("run_for", frames=2, seconds=10.0),
        "run_to": lambda: call("run_to", ref="irq_vblank", control="0x4a0", seconds=10.0),
        "step": lambda: call("step"),
    }
    for adv in C7_ADVANCES:
        stop = advances[adv]()
        seen = by_ref(stop.get("watches"))
        for mode in C7_MODES:
            w = seen.get(C7_REF[mode], {})
            cell(f"a {mode} watch under {adv}", _c7_judge(mode, w, stop),
                 f"{said(stop, 50)}: {str(w)[:110]}")
    call("watch_clear", all=True)
    call("breakpoint_clear", all=True)
    call("breakpoint_at", ref="irq_vblank", role="control")
    call("watch_add", ref="0x2031fc", mode="change", length=4)
    r = call("run_for", frames=2, seconds=10.0)
    cell(C7[-3], r.get("verdict") == "OTHER_STOP"
         and r.get("watch_hit", {}).get("writer_pc") is not None, said(r))
    r = call("run_to", ref="0x4a0", seconds=5.0)
    cell(C7[-2], r.get("verdict") == "OTHER_STOP" or refused(r, "cut_by_other_stop"), said(r))
    r = call("step")
    w = by_ref(r.get("watches")).get("0x2031fc", {})
    # The survey carries EVERY declared watch evaluated: a change watch rides it placed
    # `armed` and read, with its bytes now, whether or not this step wrote them.
    reading = w.get("reading", {})
    cell(C7[-1], w.get("state") == "armed" and "value" in reading and "raw_hex" in reading
         or "watch_hit" in r, f"{said(r, 50)}: {w}"[:150])
    call("watch_clear", all=True)
    call("breakpoint_clear", all=True)
    # the blitter's strobe, written many times a frame: every write after the plant raises
    tap = call("watch_add", ref=BLIT_TRIGGER, mode="count", length=2)
    call("run_for", frames=2, seconds=10.0)
    at = planted_at(plant_fault("MCP_TALLY", str(tap.get("tally_id")), (
        f'setmetatable(t.values, {{__index = function() error("{FAULT}") end}})\n'
        "for k in pairs(t.values) do t.values[k] = nil end"), "t.total"))
    call("run_for", frames=10, seconds=10.0)
    w = by_ref(call("watch_list").get("watches")).get(BLIT_TRIGGER, {})
    count, first = raised(w)
    total = int(w.get("total", -1))
    cell(C7_RAISED, at >= 0 and total > at and count == total - at and FAULT in first,
         f"total {at} -> {total}, errors {count}, first {first[:70]!r}")
    call("watch_clear", all=True)
    tap = call("watch_add", ref=BLIT_TRIGGER, mode="count", length=2)
    call("run_for", frames=2, seconds=10.0)
    scratch = Path(str(call("status").get("scratch_dir")))
    dumper_fault_cell(C7_DUMPER, "MCP_TALLY", str(tap.get("tally_id")), BLIT_TRIGGER,
                      scratch / f"tally-{tap.get('tally_id')}.txt")
    call("watch_clear", all=True)


C8 = [
    "captures lists the AVI record wrote, with its frames",
    "captures lists both PNGs snapshot wrote, present",
    "captures does not list what memdump wrote",
    "screen_signature writes no capture",
    "snapshot's sha256 is the file's own",
    "a PNG removed since is listed present false",
    "captures lists the WAV audio_record wrote, with its samples",
]


@section("C", "8. captures", C8)
def c8_captures() -> None:
    boot()
    avi, png = fresh(".avi"), fresh(".png")
    call("record", frames=3, dest=avi, seconds=10.0)
    wav = fresh(".wav")
    sound = call("audio_record", frames=3, dest=wav, seconds=10.0)
    shot = call("snapshot", dest=png)
    call("snapshot")
    dump = fresh(".bin")
    call("memdump", ref="0x0", length=16, dest=dump)
    caps = call("captures").get("captures", [])
    avis = [c for c in caps if c.get("kind") == "avi"]
    cell(C8[0], len(avis) == 1 and avis[0].get("avi_frames") == 3 and avis[0].get("present") is True
         and avis[0].get("path") == avi, str(avis)[:150])
    pngs = [c for c in caps if c.get("kind") == "png"]
    cell(C8[1], len(pngs) == 2 and all(c.get("present") and c.get("bytes", 0) > 0 for c in pngs),
         str(pngs)[:150])
    cell(C8[2], all(c.get("path") != dump for c in caps), str([c.get("path") for c in caps]))
    call("screen_signature")
    cell(C8[3], len(call("captures").get("captures", [])) == len(caps), said(PENDING[-1]["reply"]))
    digest = hashlib.sha256(Path(png).read_bytes()).hexdigest()
    cell(C8[4], shot.get("sha256") == digest, f"{shot.get('sha256')} vs {digest}")
    Path(png).unlink()
    gone = [c for c in call("captures").get("captures", []) if c.get("path") == png]
    cell(C8[5], len(gone) == 1 and gone[0].get("present") is False, str(gone))
    wavs = [c for c in caps if c.get("kind") == "wav"]
    cell(C8[6], len(wavs) == 1 and wavs[0].get("path") == wav and wavs[0].get("present") is True
         and (wavs[0].get("samples") or 0) > 0 and wavs[0].get("samples") == sound.get("samples"),
         str(wavs)[:150])


C9 = [
    "reset answers softreset, verified, with the stop survey",
    "the stop breakpoint and the control are still listed armed",
    "the change watch is still listed armed",
    "the show watch still reads at the reset's stop",
    "the control still counts after the reset",
    "the tally still reports after the reset (contract silent on the total)",
    "the session is altered after the reset",
]


@section("C", "9. reset with declarations armed", C9)
def c9_reset() -> None:
    boot()
    call("breakpoint_at", ref="vec_trapv")
    call("breakpoint_at", ref="irq_vblank", role="control")
    call("watch_add", ref="0x2031fc", mode="change", length=4)
    call("watch_add", ref="0x20351c", mode="count", length=1)
    call("watch_add", ref="0x203200", mode="show", length=2)
    before = call("run_for", frames=10, seconds=10.0, disarm_watches=True)
    t0 = by_ref(before.get("watches")).get("0x20351c", {}).get("total")
    r = call("reset")
    cell(C9[0], ok(r) and r.get("kind") == "softreset" and r.get("verified") is True
         and "regs" in r, said(r))
    bps = by_ref(call("breakpoint_list").get("breakpoints"))
    cell(C9[1], [bps.get(k, {}).get("state") for k in ("vec_trapv", "irq_vblank")]
         == ["armed", "armed"], str({k: b.get("state") for k, b in bps.items()}))
    w = by_ref(call("watch_list").get("watches")).get("0x2031fc", {})
    cell(C9[2], w.get("state") == "armed", str(w)[:120])
    rw = by_ref(r.get("watches")).get("0x203200", {})
    cell(C9[3], rw.get("state") == "evaluated" and rw.get("reading", {}).get("available") is True,
         str(rw))
    r = call("run_to", ref="exception_handler", seconds=3.0, disarm_watches=True)
    cell(C9[4], r.get("verdict") == "TIMEOUT" and r.get("control_hits", 0) > 0, said(r))
    r = call("run_for", frames=5, seconds=10.0, disarm_watches=True)
    t = by_ref(r.get("watches")).get("0x20351c", {})
    cell(C9[5], t.get("installed") is True and isinstance(t.get("total"), int),
         f"total {t0} before the reset, {t.get('total')} after")
    cell(C9[6], r.get("session", {}).get("altered") is True, str(r.get("session")))


def _media_files() -> dict[str, str]:
    """Files whose answers are known, for the media file tools in a batch, which cannot read a
    path an earlier step returns: a series of two different 2x2 frames with its goldens, and a
    one-second WAV of a tone."""
    folder = Path(fresh("-series"))
    folder.mkdir()
    for frame, level in ((0, 0), (1, 255)):
        (folder / series.frame_name(frame)).write_bytes(
            png.encode(png.Raster(2, 2, bytes([level]) * 12)))
    manifest = series.write_manifest(folder, "mame", "frame_number", None, [0, 1])["manifest"]
    sums = folder / "goldens.sha256"
    sums.write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                            for p in sorted(folder.glob("f*.png"))))
    tone = fresh(".wav")
    with wave.open(tone, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", round(8000 * math.sin(i / 4)))
                               for i in range(8000)))
    return {"png": str(folder / series.frame_name(0)), "manifest": str(manifest),
            "sums": str(sums), "wav": tone}


def _every_op_once(state: str, frame_now: int) -> list[dict[str, Any]]:
    """A batch holding every operation `perform` accepts, in an order the machine can take: the
    series first, its frames just ahead of `frame_now` (where the machine stands before the
    batch, which nothing has advanced yet), the console ops stopped, then `resume`, the
    running-ok ops, and `stop`."""
    tsv = fresh(".tsv")
    media = _media_files()
    return [
        {"op": "series_capture", "first": frame_now + 1, "last": frame_now + 2,
         "seconds": 10.0},
        {"op": "status"}, {"op": "machine_map"}, {"op": "cpu_info"},
        {"op": "symbols_find", "name": "irq_vblank"},
        {"op": "read_memory", "ref": "0x400", "length": 4},
        {"op": "read_block", "tag": "maincpu", "length": 4}, {"op": "registers"},
        {"op": "disassemble", "ref": "0x400", "length": 4},
        {"op": "find", "ref": "0x0", "length": 64, "data_hex": "00"},
        {"op": "history", "limit": 2}, {"op": "focus", "cpu": "maincpu"},
        {"op": "log", "pattern": ".", "channel": "emulator", "limit": 2},
        {"op": "snapshot"}, {"op": "captures"}, {"op": "state_list"},
        {"op": "breakpoint_at", "ref": "exception_handler"}, {"op": "breakpoint_list"},
        {"op": "breakpoint_clear", "all": True}, {"op": "watch_add", "ref": "0x203200",
                                                  "mode": "show",
                                     "length": 2},
        {"op": "watch_list"}, {"op": "watch_clear", "all": True},
        {"op": "regpoint_add", "condition": "pc==0xfffffffe"}, {"op": "regpoint_list"},
        {"op": "regpoint_clear", "all": True},
        {"op": "comment_add", "ref": "irq_vblank", "text": "batch"}, {"op": "comment_list"},
        {"op": "comment_save", "dest": tsv}, {"op": "comment_load", "path": tsv},
        {"op": "comment_delete", "ref": "irq_vblank"},
        {"op": "debug", "command": "print pc"},
        {"op": "lua", "script": "print(1)", "read_only": True}, {"op": "screen_signature"},
        {"op": "palette", "count": 4}, {"op": "screen_view", "mode": "histogram"},
        {"op": "image_diff", "a": media["png"], "b": media["png"]},
        {"op": "series_diff", "a": media["manifest"], "b": media["manifest"]},
        {"op": "region_track", "manifest": media["manifest"]},
        {"op": "golden_check", "manifest": media["manifest"], "checksums": media["sums"]},
        {"op": "audio_measure", "path": media["wav"]},
        {"op": "audio_diff", "a": media["wav"], "b": media["wav"]},
        {"op": "gfx_view", "layout": BYTES_8X8, "palette": "none", "tag": "maincpu", "count": 4},
        {"op": "gfx_locate", "layouts": [BYTES_8X8], "patch": [0, 0, 8, 8], "tag": "maincpu",
         "count": 4},
        {"op": "gfx_sweep", "tag": "maincpu", "planes": [1], "count": 4},
        {"op": "gfx_draft", "dest": fresh(".yaml")},
        {"op": "gfx_load", "path": MANIFEST},
        {"op": "watch_add", "ref": BLITTER, "mode": "capture", "length": 32,
         "trigger": BLIT_TRIGGER},
        {"op": "run_for", "frames": 8, "seconds": 10.0},
        {"op": "gfx_blits", "draw_command": "blit"}, {"op": "gfx_blit_source",
                                                      "draw_command": "blit",
                                                  "index": 0},
        {"op": "palette_log", "palette_port": "ramdac", "arm": True},
        {"op": "palette_log", "palette_port": "ramdac", "clear": True},
        {"op": "gfx_film", **FILM}, {"op": "run_for", "frames": 6, "seconds": 10.0},
        {"op": "gfx_film"}, {"op": "gfx_film", "clear": True},
        {"op": "watch_clear", "all": True},
        {"op": "write", "ref": "0x200000", "data_hex": "00"},
        {"op": "set_register", "name": "D1", "value": 0},
        {"op": "run_to", "ref": "irq_vblank", "control": "0x4a0", "seconds": 10.0},
        {"op": "breakpoint_clear", "all": True}, {"op": "run_for", "frames": 1, "seconds": 10.0},
        {"op": "trace", "frames": 1, "seconds": 10.0},
        {"op": "step"}, {"op": "input", "port": ":P1", "field": "Coin 1", "frames": 1,
                         "seconds": 10.0},
        {"op": "record", "frames": 2, "seconds": 10.0},
        {"op": "audio_record", "frames": 2, "seconds": 10.0},
        {"op": "memdump", "ref": "0x0", "length": 16, "dest": fresh(".bin")},
        {"op": "scan_start", "ref": "0x200000", "length": 0x100}, {"op": "scan_filter",
                                                                  "operator": "!"},
        {"op": "scan_clear"},
        {"op": "state_save", "name": state}, {"op": "state_load", "name": state},
        {"op": "reset"}, {"op": "throttle", "on": False},
        {"op": "resume"}, {"op": "log_wait", "pattern": ".", "channel": "emulator",
                           "seconds": 5.0},
        {"op": "stop"},
    ]


C10 = [
    "the batch covers every operation perform accepts",
    "perform runs a list holding every operation, in one call",
    "one refused step stops the list there, the steps before it ran",
    "a list with two bad steps is refused whole, nothing run, both listed",
    "drive with no expect says the verify was not checked",
    "drive with an expect the act meets says seen",
    "drive with an expect a stopped machine never met is wait_stopped with the act's account",
    "drive with a refused step is step_failed with the act and the look",
]


@section("C", "10. batches", C10)
def c10_batches() -> None:
    boot()
    steps = _every_op_once("c10", int(call("screen_signature").get("frame_screen") or 0))
    ops = {st_["op"] for st_ in steps}
    accepted = set(s._step_ops())
    cell(C10[0], ops == accepted,
         f"missing {sorted(accepted - ops)}, extra {sorted(ops - accepted)}")
    r = call("perform", steps=steps, settle_seconds=5.0, summaries=True)
    cell(C10[1],
         ok(r) and r.get("steps_completed") == len(steps)
         and (r.get("failed_at") or {}).get("available") is False,
         f"{said(r)} completed {r.get('steps_completed')} of {len(steps)} "
         f"({r.get('failed', {}).get('reply', {}).get('message', '')})"[:200])
    r = call("perform", steps=[{"op": "read_memory", "ref": "0x400", "length": 2},
                               {"op": "read_memory", "ref": "nosuchsymbol", "length": 2},
                               {"op": "read_memory", "ref": "0x400",
                                "length": 2}], settle_seconds=2.0)
    cell(C10[2], refused(r, "step_failed") and r.get("failed_at") == 1
         and r.get("steps_completed") == 1 and len(r.get("ran", [])) == 1, said(r))
    r = call("perform", steps=[{"op": "warp_core"}, {"op": "read_memory", "ref": "0x400",
                                                     "length": 0}], settle_seconds=2.0)
    cell(C10[3], refused(r) and r.get("steps_completed") == 0 and r.get("ran") == []
         and len(r.get("errors", [])) == 2, f"{said(r)} errors={r.get('errors')}"[:200])
    r = call("drive", act=[{"op": "run_for", "frames": 1, "seconds": 10.0}], settle_seconds=2.0)
    cell(C10[4], ok(r) and r.get("verify", {}).get("checked") is False, said(r))
    r = call("drive", **SEEN_ACT)
    cell(C10[5], ok(r) and r.get("verify", {}).get("seen") is True, said(r))
    r = call("drive", act=[{"op": "run_for", "frames": 1, "seconds": 10.0}],
             expect="no line ever says this", seconds=1.0, settle_seconds=2.0)
    cell(C10[6], refused(r, "wait_stopped") and r.get("act", {}).get("steps_completed") == 1,
         said(r))
    r = call("drive", act=[{"op": "read_memory", "ref": "nosuchsymbol"}], settle_seconds=2.0)
    cell(C10[7], refused(r, "step_failed") and "act" in r and "looked" in r, said(r))


C12_BARE = [
    "with no symbol file symbols_find is no_channel",
    "with no symbol file symbol_coverage is an empty list",
    "with no symbol file read_memory by name is refused, by 0x answered",
    "with no symbol file disassemble by name is refused",
    "with no symbol file run_to by name is refused",
    "with no symbol file breakpoint_at by name is kept unresolved, not refused",
    "with no symbol file watch_add by name is kept unresolved",
    "with no symbol file find by region is refused",
    "with no symbol file memdump by name is refused",
    "with no symbol file read_block by name is refused",
]
C12_TABLE = [
    "read_memory by symbol reads what the hex address holds",
    "disassemble by symbol starts at the table's address",
    "find by symbol finds the bytes at the table's address",
    "memdump by symbol writes what the hex address holds",
    "read_block by symbol names the block and the offset",
    "write by symbol lands at the table's address",
    "symbols_find by linear places an address inside the nearest symbol",
    "breakpoint_at by symbol arms the table's address",
    "watch_add by symbol watches the table's address",
    "run_to by symbol stops at the table's address",
    "a YAML table carries no classes: symbol_coverage is an empty list",
]


@section("C", "12. symbols, with a table and with none", C12_BARE + C12_TABLE)
def c12_symbols() -> None:
    boot(symbols=None)
    b = C12_BARE
    cell(b[0], refused(call("symbols_find", name="irq_vblank"), "no_channel"),
         said(PENDING[-1]["reply"]))
    cell(b[1], call("machine_map").get("symbol_coverage") == [], said(PENDING[-1]["reply"]))
    by_name, by_hex = call("read_memory", ref="irq_vblank"), call("read_memory", ref="0x400")
    cell(b[2], refused(by_name) and ok(by_hex), f"{said(by_name, 60)} / {said(by_hex, 40)}")
    cell(b[3], refused(call("disassemble", ref="irq_vblank")), said(PENDING[-1]["reply"]))
    cell(b[4], refused(call("run_to", ref="irq_vblank", control="0x4a0", seconds=5.0)),
         said(PENDING[-1]["reply"]))
    r = call("breakpoint_at", ref="irq_vblank")
    cell(b[5], ok(r) and r.get("state") == "unresolved", said(r))
    r = call("watch_add", ref="main_ram", mode="change", length=4)
    cell(b[6], ok(r) and r.get("state") == "unresolved", said(r))
    cell(b[7], refused(call("find", data_hex="00", symbol_class="CODE")),
         said(PENDING[-1]["reply"]))
    cell(b[8], refused(call("memdump", ref="irq_vblank", length=4, dest=fresh(".bin"))),
         said(PENDING[-1]["reply"]))
    cell(b[9], refused(call("read_block", ref="irq_vblank")), said(PENDING[-1]["reply"]))
    call("close")
    boot()
    t = C12_TABLE
    sym, hx = call("read_memory", ref="irq_vblank", length=8), call("read_memory", ref="0x400",
                                                                     length=8)
    cell(t[0], ok(sym) and sym.get("hex") == hx.get("hex") and sym.get("addr") == "0x00000400",
         said(sym))
    r = call("disassemble", ref="irq_vblank", length=4)
    cell(t[1], ok(r) and r.get("addr") == "0x00000400", said(r))
    r = call("find", ref="irq_vblank", length=8, data_hex=str(hx.get("hex", ""))[:4])
    cell(t[2], ok(r) and "0x00000400" in [h.lower() for h in r.get("hits", [])]
         or ok(r) and any(int(h, 16) == 0x400 for h in r.get("hits", [])), said(r))
    dest = fresh(".bin")
    r = call("memdump", ref="irq_vblank", length=8, dest=dest)
    cell(t[3], ok(r) and Path(dest).read_bytes().hex() == hx.get("hex"), said(r))
    r = call("read_block", ref="irq_vblank", length=4)
    cell(t[4], ok(r) and r.get("tag") == ":maincpu" and r.get("offset") == 0x400, said(r))
    r = call("write", ref="main_ram", data_hex="00")
    cell(t[5], ok(r) and r.get("addr") == "0x00200000", said(r))
    r = call("symbols_find", linear="0x40e")
    cell(t[6], ok(r) and r.get("name") == "IRQ_VBLANK" and r.get("delta") == 0xE, said(r))
    r = call("breakpoint_at", ref="irq_vblank")
    cell(t[7], ok(r) and r.get("addr") == "0x00000400", said(r))
    call("breakpoint_clear", all=True)
    r = call("watch_add", ref="main_ram", mode="show", length=4)
    cell(t[8], ok(r) and r.get("addr") == "0x00200000", said(r))
    call("watch_clear", all=True)
    r = call("run_to", ref="irq_vblank", control="0x4a0", seconds=10.0)
    cell(t[9], r.get("verdict") == "TARGET" and r.get("pc") == "0x00000400", said(r))
    cell(t[10], call("machine_map").get("symbol_coverage") == [], said(PENDING[-1]["reply"]))


C13 = [
    "regpoint_add arms d1==7fff on a fresh start, read back off rplist",
    "regpoint_list shows it armed, with its index and cpu",
    "a resume is cut by it: regpoint_hit, and D1 holds the value",
    "still armed, a run by frames is OTHER_STOP with the hit, never no_progress",
    "and the session is not handed back running",
    "regpoint_clear disarms it, read back",
    "the same run by frames then ELAPSES",
    "a malformed condition (d1==) is bad_argument in the console's words, and stores nothing",
    "a register this cpu lacks (eax==5) is bad_argument: unknown symbol",
    "an action after a comma is bad_argument before the console hears of it",
    "a registerpoint added WHILE RUNNING is armed, fires and is found by the next contact",
    "a second start re-arms the stored registerpoint and says so in rearm",
    "a registerpoint typed through debug is named by index and condition",
    "the same condition typed on the OTHER 68000 is not adopted: the add arms the main cpu's",
    "and the other cpu's row is listed foreign and survives the clear",
]


@section("C", "13. regpoints: declared, fired, cleared, re-armed", C13)
def c13_regpoints() -> None:
    t = C13
    boot()
    cond = "d1==7fff"
    r = call("regpoint_add", condition=cond)
    cell(t[0], ok(r) and r.get("armed") is True and r.get("index") == 1
         and r.get("entry") == f"1 if {cond}" and r.get("cpu") == ":maincpu"
         and r.get("session", {}).get("altered") is False, said(r))
    rows = call("regpoint_list").get("regpoints", [])
    cell(t[1], [(x.get("ref"), x.get("state"), x.get("cpu")) for x in rows]
         == [(cond, "armed", ":maincpu")] and "index" in rows[0], str(rows)[:150])
    r = call("resume", seconds=5.0)
    hit = r.get("regpoint_hit", {})
    cell(t[2], r.get("verdict") == "OTHER_STOP" and r.get("how") == f"registerpoint '{cond}'"
         and hit.get("ref") == cond and hit.get("pc") == r.get("pc")
         and r.get("regs", {}).get("D1") == "0x00007fff", said(r))
    r = call("run_for", frames=2, seconds=10.0)
    cell(t[3], r.get("verdict") == "OTHER_STOP" and r.get("regpoint_hit", {}).get("ref") == cond,
         said(r))
    cell(t[4], session_is(r, alive=True, running=False), str(r.get("session")))
    r = call("regpoint_clear", ref=cond)
    cell(t[5], r.get("declarations_cleared") == 1 and len(r.get("disarmed", [])) == 1
         and call("regpoint_list").get("regpoints") == [], said(r))
    r = call("run_for", frames=2, seconds=10.0)
    cell(t[6], r.get("verdict") == "ELAPSED", said(r))
    r = call("regpoint_add", condition="d1==")
    cell(t[7], refused(r, "bad_argument") and "stack underflow" in str(r.get("message"))
         and call("regpoint_list").get("regpoints") == []
         and call("debug", command="rplist").get("output", "").startswith("No registerpoints"),
         said(r))
    r = call("regpoint_add", condition="eax==5")
    cell(t[8], refused(r, "bad_argument") and "unknown symbol" in str(r.get("message")), said(r))
    r = call("regpoint_add", condition="d1==7fff,{g}")
    cell(t[9], refused(r, "bad_argument") and "ACTION" in str(r.get("message")), said(r))
    # WHILE RUNNING: `pc!=0` holds at once, so the machine stops by itself an instruction on.
    call("resume")
    r = call("regpoint_add", condition="pc!=0")
    time.sleep(0.5)
    found = call("status")
    cell(t[10], r.get("armed") is True and r.get("while_running") is True
         and found.get("running") is False
         and str(found.get("last_stop", {}).get("how")) == "registerpoint 'pc!=0'",
         f"{said(r)} / {found.get('last_stop')}")
    call("regpoint_clear", all=True)
    call("regpoint_add", condition=cond)
    call("close")
    r = boot()
    rearm = r.get("declarations", {}).get("rearm", {})
    rows = call("regpoint_list").get("regpoints", [])
    cell(t[11], rearm_pairs(rearm, "rearmed") == [(cond, ":maincpu")]
         and rearm.get("unarmable") == []
         and [(x.get("state"), x.get("inherited")) for x in rows] == [("armed", True)],
         f"{rearm} / {str(rows)[:100]}")
    call("regpoint_clear", all=True)
    call("debug", command="rpset {d1==7fff}")
    r = call("resume", seconds=5.0)
    cell(t[12], str(r.get("how")).startswith("registerpoint ")
         and "(if d1==7fff), typed through `debug`: `debug(\"rpclear " in str(r.get("how"))
         and "regpoint_hit" not in r, said(r))
    call("debug", command="rpclear")
    # THE BOARD HAS TWO 68000s, and `d1==7fff` on the sub cpu compares another D1.
    call("debug", command="focus subcpu")
    typed = call("debug", command="rpset {d1==7fff}").get("output", "")
    call("debug", command="focus maincpu")
    r = call("regpoint_add", condition=cond)
    rows = call("debug", command="rplist").get("output", "")
    cell(t[13], typed.startswith("Registerpoint ") and r.get("armed") is True
         and r.get("cpu") == ":maincpu" and rows.count(f"if {cond}") == 2
         and "Device ':subcpu' registerpoints:" in rows, f"{said(r)} / {rows!r}")
    listed = call("regpoint_list")
    call("regpoint_clear", all=True)
    after = call("debug", command="rplist").get("output", "")
    cell(t[14], len(listed.get("foreign", [])) == 1 and "Device ':subcpu'" in after
         and "Device ':maincpu'" not in after, f"{listed.get('foreign')} / {after!r}")
    call("debug", command="rpclear")


#: Per cpu: a ROM word of that cpu's program, and a pattern that is not what it holds.
REGION_AT = {MAIN: (0x7B8, "8020"), SUB: (0x544, "4e71")}
REGION_END = 0xFFFFE            # the last word of each program ROM region, both 1 MB


def _c14(tag: str, what: str) -> str:
    return f"{what} on {tag}"


C14_EACH = [
    "a region write reads back the pattern through the cpu, naming the region and offset",
    "read_memory through the cpu sees the pattern, and the other cpu's ROM did not move",
    "one byte at the odd address lands on that byte, its word's other byte kept",
    "the region's last word is written and read back",
    "two bytes from the region's last byte are refused before anything is sent",
    "a plain write there goes nowhere and points at region=True",
    "a region write to RAM is refused naming what map answers, and writes nothing",
    "restored: the original word written back through the region reads as before",
]
C14 = [_c14(tag, what) for tag in (MAIN, SUB) for what in C14_EACH]


@section("C", "14. the ROM region write, per cpu", C14)
def c14_region_write() -> None:
    boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
    call("run_for", frames=60, seconds=10.0)       # the sub cpu is out of reset
    for tag in (MAIN, SUB):
        t = [_c14(tag, what) for what in C14_EACH]
        other = SUB if tag == MAIN else MAIN
        addr, pattern = REGION_AT[tag]
        ref = f"{addr:#x}"

        def word(at: int, on: str = tag) -> str:
            return str(call("read_memory", ref=f"{at:#x}", length=2, cpu=on).get("hex"))

        before, beside, end_before = word(addr), word(addr, other), word(REGION_END)
        r = call("write", ref=ref, data_hex=pattern, cpu=tag, region=True)
        cell(t[0], ok(r) and r.get("verified") is True and r.get("readback") == pattern
             and (r.get("region"), r.get("region_offset"), r.get("cpu")) == (tag, addr, tag)
             and r["session"]["altered"] is True, said(r))
        cell(t[1], word(addr) == pattern and word(addr, other) == beside,
             f"{tag} {word(addr)}, {other} {word(addr, other)} (was {beside})")
        r = call("write", ref=f"{addr + 1:#x}", data_hex="5a", cpu=tag, region=True)
        cell(t[2], ok(r) and r.get("verified") is True and word(addr) == pattern[:2] + "5a",
             f"{said(r)} / {word(addr)}")
        r = call("write", ref=f"{REGION_END:#x}", data_hex="a55a", cpu=tag, region=True)
        cell(t[3], ok(r) and r.get("verified") is True and word(REGION_END) == "a55a", said(r))
        call("write", ref=f"{REGION_END:#x}", data_hex=end_before, cpu=tag, region=True)
        r = call("write", ref=f"{REGION_END + 1:#x}", data_hex="a55a", cpu=tag, region=True)
        cell(t[4], refused(r, "bad_argument") and "past the map entry's end" in str(
             r.get("message")) and word(REGION_END) == end_before, said(r))
        r = call("write", ref=ref, data_hex=before, cpu=tag)
        cell(t[5], ok(r) and r.get("verified") is False and r.get("target") == "rom"
             and "`region=True` writes them there" in str(r.get("note"))
             and word(addr) == pattern[:2] + "5a", said(r))
        writes_before = call("status")["session"]["altering_writes"]
        r = call("write", ref="0x200000", data_hex="00", cpu=tag, region=True)
        cell(t[6], refused(r, "bad_argument") and "answers ram at 0x200000" in str(
             r.get("message")) and r["session"]["altering_writes"] == writes_before, said(r))
        r = call("write", ref=ref, data_hex=before, cpu=tag, region=True)
        cell(t[7], ok(r) and r.get("verified") is True and word(addr) == before
             and word(REGION_END) == end_before, f"{said(r)} / {word(addr)} (was {before})")


#: The frame counter's long, written once a frame by IRQ_VBLANK, and its low word.
COUNTER, COUNTER_LOW = "0x2031fc", "0x2031fe"


def _c15(tag: str, what: str) -> str:
    return f"{what} on {tag}"


C15_MAIN = [
    "a change watch conditioned on the value written is armed with the condition in its row",
    "it stops only on writes its condition holds for, and each hit names the condition",
    "a pass with disarm_watches re-arms it under its condition",
    "a capture of the counter on its low word keeps one row per write, rows + overflow_rows "
    "equal to a count watch on the trigger",
    "each row holds the trigger's word from before its write, one less than its data",
    "a cleared capture sends its removal and drops its rows file",
    "a capture whose tap raises counts one error per trigger write and keeps no row, never an "
    "empty census",
    "a capture whose dumper raises after its open logs MCP_DUMP_FAILED once, closes its .tmp, "
    "and the superseded dump's why names the error",
    "a capture whose struct format would decode past the widest array's row is refused at "
    "watch_add, nothing installed, and one at that bound is taken",
]
C15_SUB = [
    "a conditioned change watch on the sub cpu's RAM is armed on that cpu",
    "a capture on the sub cpu's plain RAM is read through the space and installs on that cpu, "
    "its rows agreeing with a count watch there",
]
C15 = [_c15(MAIN, w) for w in C15_MAIN] + [_c15(SUB, w) for w in C15_SUB]


@section("C", "15. the conditioned change watch and the capture, per cpu", C15)
def c15_condition_and_capture() -> None:
    boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
    call("run_for", frames=60, seconds=10.0)       # the counter runs, the sub cpu is out of reset
    t = [_c15(MAIN, w) for w in C15_MAIN]
    cond = "(wpdata&3)==0"
    r = call("watch_add", ref=COUNTER_LOW, mode="change", length=2, condition=cond, cpu=MAIN)
    cell(t[0], ok(r) and r.get("armed") is True and str(r.get("entry")).endswith(f" if {cond}")
         and r.get("condition") == cond, said(r))
    wrote: list[int] = []
    named = True
    for _ in range(3):
        r = call("run_for", frames=12, seconds=10.0)
        hit = r.get("watch_hit") or {}
        named = named and (not hit or hit.get("condition") == cond)
        wrote += [int(w["wrote"], 16) for w in hit.get("writes", [])]
    cell(t[1], bool(wrote) and named and all(v & 3 == 0 for v in wrote),
         f"{[f'{v:x}' for v in wrote]}")
    call("run_for", frames=2, seconds=10.0, disarm_watches=True)
    w = by_ref(call("watch_list").get("watches")).get(COUNTER_LOW, {})
    cell(t[2], w.get("state") == "armed" and str(w.get("entry")).endswith(f" if {cond}"),
         str(w)[:160])
    call("watch_clear", all=True)
    cap = call("watch_add", ref=COUNTER, mode="capture", fmt="u16[2]", trigger=COUNTER_LOW,
               cpu=MAIN)
    call("watch_add", ref=COUNTER_LOW, mode="count", length=1, cpu=MAIN)
    call("run_for", frames=30, seconds=10.0)
    seen = by_ref(call("watch_list").get("watches"))
    c, k = seen.get(COUNTER, {}), seen.get(COUNTER_LOW, {})
    cell(t[3], ok(cap) and c.get("state") == "captured" and int(c.get("rows_kept", 0)) > 0
         and c.get("rows_kept", 0) + c.get("overflow_rows", 0) == k.get("total"),
         f"{c.get('rows_kept')} + {c.get('overflow_rows')} vs {k.get('total')}")
    rows = c.get("first_rows") or []
    cell(t[4], bool(rows) and all(r["block"][1] == int(r["data"], 16) - 1 for r in rows),
         str(rows[:2])[:160])
    gone = call("watch_clear", ref=COUNTER)
    cell(t[5], ok(gone) and bool(gone.get("tallies_removed"))
         and not Path(str(c.get("rows_path"))).exists(), said(gone))
    call("watch_clear", all=True)
    # the control is a count watch on the trigger, read in the planting chunk itself
    cap = call("watch_add", ref=COUNTER, mode="capture", fmt="u16[2]", trigger=COUNTER_LOW,
               cpu=MAIN)
    ctl = call("watch_add", ref=COUNTER_LOW, mode="count", length=1, cpu=MAIN)
    call("run_for", frames=4, seconds=10.0)
    kept = int(by_ref(call("watch_list").get("watches")).get(COUNTER, {}).get("rows_kept", -1))
    at = planted_at(plant_fault("MCP_CAPTURE", str(cap.get("tally_id")), (
        f't.pending = setmetatable({{}}, {{__newindex = function() error("{FAULT}") end}})'),
        f'_G.MCP_TALLY.items["{ctl.get("tally_id")}"].total'))
    call("run_for", frames=30, seconds=10.0)
    seen = by_ref(call("watch_list").get("watches"))
    c, k = seen.get(COUNTER, {}), seen.get(COUNTER_LOW, {})
    count, first = raised(c)
    grew = int(k.get("total", -1)) - at
    cell(t[6], at >= 0 and grew > 0 and count == grew and FAULT in first
         and kept > 0 and c.get("rows_kept") == kept,
         f"trigger writes since the plant {grew}, errors {count}, rows kept {kept} -> "
         f"{c.get('rows_kept')}, first {first[:60]!r}")
    call("watch_clear", all=True)
    cap = call("watch_add", ref=COUNTER, mode="capture", fmt="u16[2]", trigger=COUNTER_LOW,
               cpu=MAIN)
    call("run_for", frames=2, seconds=10.0)
    scratch = Path(str(call("status").get("scratch_dir")))
    dumper_fault_cell(t[7], "MCP_CAPTURE", str(cap.get("tally_id")), COUNTER,
                      scratch / f"capture-{cap.get('tally_id')}.txt")
    call("watch_clear", all=True)
    # the bound is the server's own, computed from the formats it already holds
    bound = mwatches.capture_block_chars_max()
    fields = [f"f{i:02d}" for i in range(16)]
    base = mcapture.block_chars_max(vf.parse("{" + ",".join(f"{f}:i8" for f in fields) + "}"), 0)
    fields[0] += "x" * (bound - base)
    at_bound = "{" + ",".join(f"{f}:i8" for f in fields) + "}"
    past = at_bound.replace(fields[0], fields[0] + "x", 1)
    over = call("watch_add", ref=COUNTER, mode="capture", fmt=past, trigger=COUNTER_LOW)
    listed = [w for w in call("watch_list").get("watches") or [] if w.get("ref") == COUNTER]
    taken = call("watch_add", ref=COUNTER, mode="capture", fmt=at_bound, trigger=COUNTER_LOW)
    cell(t[8], refused(over, "bad_argument") and "widest row" in str(over.get("message"))
         and listed == [] and ok(taken),
         f"{said(over, 80)} / listed {len(listed)} / {said(taken, 50)}")
    call("watch_clear", all=True)
    t = [_c15(SUB, w) for w in C15_SUB]
    r = call("watch_add", ref="0x200000", mode="change", length=2, condition="wpdata!=0", cpu=SUB)
    cell(t[0], ok(r) and r.get("armed") is True and r.get("cpu") == SUB
         and str(r.get("entry")).endswith(" if wpdata!=0"), said(r))
    call("watch_clear", all=True)
    cap = call("watch_add", ref="0x200000", mode="capture", fmt="u16[2]", trigger="0x200002",
               cpu=SUB)
    call("watch_add", ref="0x200002", mode="count", length=1, cpu=SUB)
    call("run_for", frames=10, seconds=10.0)
    seen = by_ref(call("watch_list").get("watches"))
    c, k = seen.get("0x200000", {}), seen.get("0x200002", {})
    cell(t[1], ok(cap) and (cap.get("source") or {}).get("kind") == "space"
         and c.get("installed") is True and c.get("cpu") == SUB
         and c.get("rows_kept", -1) + c.get("overflow_rows", -1) == k.get("total"),
         f"{said(cap, 60)} / {c.get('rows_kept')} vs {k.get('total')}")
    call("watch_clear", all=True)


# ================================================ Block D: the graphics tools on free boards
#
# The graphics tools' calibration: each known answer is the MACHINE'S OWN, read in the same
# session (circus's videoram names the char, gridlee's spriteram the sprite), and each negative is
# a board whose screen has no pens to give (starfire, direct colour; witchgme, a palette device
# its screen does not use; topgunnr, vector). The boards are the free sets of mamedev.org, which
# m68k-dual's binary does not carry, so the section runs a stock MAME named by MAME_STOCK_BINARY
# (its `plugins` directory beside it) over the zips in MAME_TEST_ROMS; without both, every cell is
# BLOCKED with that reason.

D_CELLS = [
    "circus: an indexed screen of two pens renders as an indexed PNG and alters nothing",
    "circus: the char videoram names at (88, 96) is located there, alone, as that tile",
    "circus: the patch one pixel over matches nothing, and the nearest says it is no match",
    "gridlee: the palette pages 2048 pens and says more are left",
    "gridlee: a 4-bit framebuffer patch is the tile at the line and column the driver lays out",
    "gridlee: the sprite spriteram places is found through transparency, image and bank",
    "witchgme: RGN_FRAC resolves its planes a third of gfx2 apart",
    "witchgme: an index mode on a screen drawn in direct colour is no_channel",
    "starfire: render answers colours, the index modes and the palette are no_channel",
    "topgunnr: no frame symbol at start; run_for by frames is no_channel and the session "
    "answers after it, by milliseconds it runs the emulated time asked; screen_view and "
    "gfx_locate are no_channel",
    "circus: a film says its frames are unchecked, measuring the snapshot's difference, and "
    "keeps them",
    "starfire: a film of a direct-colour screen keeps its frames in colour, each checked",
    "circus: a sweep of gfx2 labels its candidates, and the column-strip one is an id "
    "gfx_locate proves on the clown",
    "circus: the draft's command, from a capture of the RAM copied to port 2000, places the "
    "clown reversed at one frame's lag: x = 240 - byte 10, y = 239 - byte 11",
    "circus: the control, a capture of videoram on the same trigger, writes no command",
    "circus: the draft loads as a draft, and gfx_blits boxes the clown where gfx_locate finds it",
    "circus: the report regenerates byte for byte, and a manifest is never overwritten",
    "circus: a cleared film leaves its files where they were, its film.txt among them",
    "circus: under frameskip a drawn frame is kept, read at the next frame that drew, and a "
    "met frame the machine skipped is lost as skipped",
    "circus: a film of the clown's vertical position with changed=True meets exactly the frames "
    "an independent counter saw the value move in, fewer than it judged, and names its baseline",
    "circus: the control, a byte written every frame with one value (the paddle's copy at 1f), "
    "keeps nothing with changed=True and says so",
    "hardhat: the text videoram names in row 3, ink and paper in two banks, is found through a "
    "pen map, each letter at its place and no bank claimed",
    "hardhat: the same patch a pixel lower matches nothing, even through a pen map",
]

# THE INDEPENDENT COUNTER of the changed film's known answer: its own write tap and its own frame
# notifier, recording every span as the frame counter its end reads and whether a write to the
# trigger landed a value unlike the write before; the cell counts them over the frames the film
# says it judged, since the film's install runs a step after this one and its window is its own.
CHANGE_COUNTER_LUA = """local sp = manager.machine.devices[":maincpu"].spaces["program"]
local scr = manager.machine.screens[":screen"]
local C = {prev = nil, moved = false, spans = {}}
_G.MCP_CHANGES = C
C.tap = sp:install_write_tap(%#x, %#x, "mcp_live_changes", function(_, data)
  if C.prev ~= nil and data ~= C.prev then C.moved = true end
  C.prev = data
end)
C.sub = emu.add_machine_frame_notifier(function()
  if #C.spans < 400 then
    C.spans[#C.spans + 1] = string.format("%%d:%%d", scr:frame_number(), C.moved and 1 or 0)
  end
  C.moved = false
end)
print("counter armed")"""
CHANGE_COUNTER_READ = """local C = _G.MCP_CHANGES
C.tap:remove() C.sub:unsubscribe()
print("MCP_CHANGES " .. table.concat(C.spans, ","))"""


def counted_changes(said_by: str, first: int, last: int) -> tuple[int, int] | None:
    """The spans the counter saw end within frames `first`..`last`, and those a value moved in."""
    m = re.search(r"MCP_CHANGES (\S*)", said_by)
    if m is None:
        return None
    spans = [tuple(int(x) for x in item.split(":")) for item in m.group(1).split(",") if item]
    inside = [moved for frame, moved in spans if first <= frame <= last]
    return len(inside), sum(inside)


def _d_circus(t: list[str]) -> None:
    circus_boot()
    call("run_for", frames=600, seconds=10.0)
    before = call("status")["session"]["altering_writes"]
    r = call("screen_view", scale=1)
    cell(t[0], ok(r) and r.get("screen_indexed") is True and r.get("entries") == 2
         and r.get("image",
                   {}).get("indexed") is True and r["session"]["altering_writes"] == before,
         said(r))
    code = call("read_block", tag="videoram", offset=12 * 32 + 11, length=1).get("hex", "")
    r = call("gfx_locate", layouts=[CIRCUS_CHAR], patch=[88, 96, 8, 8], tag="gfx1",
             flips=["none"])
    m = (r.get("matches") or [{}])[0]
    cell(t[1], ok(r) and r.get("matches_total") == 1 and m.get("ambiguous") is False
         and f"{m.get('tile', -1):02x}" == code, f"videoram {code}; {said(r)}")
    r = call("gfx_locate", layouts=[CIRCUS_CHAR], patch=[89, 96, 8, 8], tag="gfx1",
             flips=["none"])
    near = r.get("nearest") or {}
    cell(t[2], ok(r) and r.get("matched") is False and near.get("is_a_match") is False
         and near.get("disagree", 0) > 0, said(r))
    armed = call("gfx_film", trigger="0x2000", keep=2, frames=4)
    call("run_for", frames=6, seconds=10.0)
    film = call("gfx_film")
    armed_film = armed.get("film") or {}
    mismatch = armed_film.get("mismatch") or {}
    cell(t[10], armed_film.get("checked") is False
         and isinstance(mismatch.get("differing_pixels"), int) and mismatch["differing_pixels"] > 0
         and "overlay_or_artwork" in (mismatch.get("candidates") or [])
         and film.get("kept") == 2 and film.get("film", {}).get("checked") is False, said(film))
    cleared = call("gfx_film", clear=True)
    folder = Path(str(armed_film.get("film_dir")))
    cell(t[17], cleared.get("cleared") is True and (folder / "film.txt").is_file()
         and (folder / "film.json").is_file(),
         f"{folder}: {sorted(p.name for p in folder.iterdir())}")
    # THE CLOWN'S VERTICAL POSITION (port 2000, MAME's `clown_x_w`) IS WRITTEN EVERY FRAME,
    # moved or not: `changed` keeps the frames it moved in, and an independent counter armed at
    # the same stop says which those are
    # the counter's install is sent after the film's, so the console runs the film's first and
    # both see the same first write, which is the film's baseline
    armed = call("gfx_film", trigger="0x2000", changed=True, keep=2, frames=120)
    call("lua", script=CHANGE_COUNTER_LUA % (0x2000, 0x2000))
    call("run_for", frames=125, seconds=10.0)
    film = call("gfx_film")
    said_by = str(call("lua", script=CHANGE_COUNTER_READ).get("output", ""))
    judged = film.get("judged_frames")
    window = judged if isinstance(judged, list) else [0, -1]
    counted = counted_changes(said_by, window[0], window[1])
    cell(t[19], ok(armed) and ok(film) and counted is not None
         and film.get("judged") == counted[0] == 120 and film.get("met") == counted[1]
         and 0 < film.get("met", 0) < 120
         and isinstance(film.get("frame_baseline"), int)
         and film["frame_baseline"] < window[0] and film.get("kept") == 2,
         f"counter over {window}: {counted}; {said(film)}")
    call("gfx_film", clear=True)
    call("gfx_film", trigger="0x1f", changed=True, keep=2, frames=60)
    call("run_for", frames=65, seconds=10.0)
    film = call("gfx_film")
    cell(t[20], ok(film) and film.get("judged") == 60 and film.get("met") == 0
         and "nothing_kept" in film and film.get("baseline_value") == "0x73", said(film))
    call("gfx_film", clear=True)
    # EVERY OTHER FRAME SKIPPED (`s_skiptable` level 6): half the met frames draw nothing and are
    # lost, and each drawn one is read at the next frame that drew, which its file counts
    call("lua", script="manager.machine.video.frameskip = 6")
    call("gfx_film", trigger="0x3000", keep=4, frames=8)
    call("run_for", frames=14, seconds=10.0)
    film = call("gfx_film")
    cell(t[18], ok(film) and film.get("kept") == 4 and film.get("refused") == 0
         and film.get("lost") == {"skipped": 4}, said(film))
    call("close")


def _d_gridlee(t: list[str]) -> None:
    free_boot("gridlee", ["gridfnla.bin"], "0xa000")
    call("run_for", frames=900, seconds=10.0)
    r = call("palette")
    cell(t[3], ok(r) and r.get("entries") == 2048 and r.get("count") == 256
         and r.get("truncated") is True, said(r))
    r = call("gfx_locate", layouts=[GRID_FB], patch=[96, 96, 8, 8], tag="videoram",
             offset=16 * 128, flips=["none"])
    m = (r.get("matches") or [{}])[0]
    cell(t[4], ok(r) and r.get("matches_total") == 1
         and m.get("tile") == (96 - 16) * 32 + 96 // 8, said(r))
    sprite = bytes.fromhex(str(call("read_block", tag="spriteram", length=4).get("hex", "")))
    image, y, x = sprite[0], sprite[2] + 17, sprite[3]     # visible row 0 is bitmap line 16
    r = call("gfx_locate", layouts=[GRID_SPRITE], patch=[x, y, 8, 16], tag="gfx1",
             transparent=0)
    tiles = {(mm.get("tile"), tuple(mm.get("window") or ())) for mm in r.get("matches") or []}
    cell(t[5], ok(r) and (image, (x, y)) in tiles
         and all(isinstance(mm.get("base"), int) and mm["base"] % 16 == 0
                 for mm in r.get("matches") or []),
         f"spriteram image {image:#x} at ({x}, {y}); {said(r)}")
    call("close")


def _d_witchgme(t: list[str]) -> None:
    free_boot("witchgme", ["hn58c256p.box12t1"], "0x4000")
    call("run_for", frames=300, seconds=10.0)
    r = call("gfx_view", layout=WITCH_TILE, palette="palette", tag="gfx2", count=64)
    cell(t[6], ok(r) and r.get("layout", {}).get("planeoffset") == [0, 0x1000 * 8, 0x2000 * 8],
         said(r))
    r = call("screen_view", mode="pixel", point=[10, 10])
    cell(t[7], refused(r, "no_channel") and "direct colour" in str(r.get("message")), said(r))
    call("close")


def _d_starfire(t: list[str]) -> None:
    free_boot("starfire", ["sfire.1a"], "0x0")
    call("run_for", frames=300, seconds=10.0)
    render = call("screen_view", scale=1)
    index_modes = [call("screen_view", mode="histogram"),
                   call("screen_view", mode="pixel", point=[1, 1]),
                   call("screen_view", mode="isolate", pens=[1])]
    pal = call("palette")
    cell(t[8], ok(render) and render.get("screen_indexed") is False
         and all(refused(r, "no_channel") for r in index_modes) and refused(pal, "no_channel"),
         f"{said(render, 50)} / {[said(r, 30) for r in index_modes]} / {said(pal, 50)}")
    # the byte its main loop writes every frame, found with a count watch over its scratch RAM
    armed = call("gfx_film", trigger="0x8014", keep=2, frames=4)
    call("run_for", frames=6, seconds=10.0)
    film = call("gfx_film")
    files = [Path(str(c["path"])) for c in film.get("cells", [])]
    colour = all(p.is_file() and p.read_bytes()[25] == 2 for p in files)
    cell(t[11], (armed.get("film") or {}).get("checked") is True and film.get("kept") == 2
         and film.get("refused") == 0 and colour and len(files) == 2, said(film))
    call("close")


def _d_topgunnr(t: list[str]) -> None:
    """A vector board has no screen device, so MAME's debugger defines no frame counter: the
    run by frames is refused before anything is released, the one by milliseconds runs on the
    emulated clock, and the screen readers have no screen to read."""
    started = free_boot("topgunnr", ["tgl-2.9r", "tgl-2.10r"], "0x804000")
    by_frames = call("run_for", frames=30, seconds=10.0)
    after = call("status")
    timed = call("run_for", milliseconds=200, seconds=10.0)
    # Rounded to the microsecond: two readings at the microsecond subtract with a float's error.
    span = round((timed.get("emulated_after_s") or 0.0)
                 - (timed.get("emulated_before_s") or 0.0), 6)
    view = call("screen_view")
    find = call("gfx_locate", layouts=[BYTES_8X8], patch=[0, 0, 8, 8], tag="maincpu", count=8)
    cell(t[9], (started.get("frame_symbol") or {}).get("available") is False
         and refused(by_frames, "no_channel") and ok(after) and after.get("broken") is None
         and ok(timed) and 0.2 <= span <= 0.25
         and refused(view, "no_channel") and refused(find, "no_channel"),
         f"{said(started, 40)} / {said(by_frames, 50)} / {said(timed, 60)} / span {span:.4f} "
         f"/ {said(view, 40)} / {said(find, 40)}")
    call("close")


def _d_discovery(t: list[str]) -> None:
    """The discovery on circus, the known answer read in its driver after the blind run: the
    clown is `clownlayout`, drawn at `256 - clown_y - 16`, `256 - clown_x - 16 - 1`, and the game
    copies RAM 0x0a and 0x0b to the ports that latch them."""
    circus_boot()
    call("run_for", frames=600, seconds=10.0)
    sweep = call("gfx_sweep", tag="gfx2", planes=[1], sizes=[[16, 16]], count=16)
    strips = next((c["id"] for c in sweep.get("candidates", [])
                   if c["what"] == "1bpp 16x16 cells down"), "")
    call("watch_add", ref="0x0", mode="capture", length=64, trigger="0x2000", by="address")
    call("watch_add", ref="0x4080", mode="capture", length=64, trigger="0x2000", by="address")
    last: dict[str, Any] = {}
    for _ in range(40):
        call("run_for", frames=7, seconds=10.0)
        last = call("gfx_locate", layouts=[strips], patch=[0, 0, 248, 256], tag="gfx2",
                    seconds=10.0)
    for _ in range(30):                     # end on a frame where the clown is in the clear
        if last.get("matches_total") == 1:
            break
        call("run_for", frames=1, seconds=10.0)
        last = call("gfx_locate", layouts=[strips], patch=[0, 0, 248, 256], tag="gfx2",
                    seconds=10.0)
    cell(t[12], ok(sweep) and bool(strips) and last.get("matched") is True, said(last))
    dest = Path(tempfile.mkdtemp(prefix="mame-live-draft-")) / "circus-gfx.yaml"
    draft = call("gfx_draft", dest=str(dest))
    report = (json.loads(Path(draft["report"]["path"]).read_text()) if ok(draft) else {})
    done = [c for c in report.get("correlations", []) if c.get("command")]
    fields = done[0]["fields"] if done else {}
    cell(t[13], draft.get("command_fields") == {
        "write_2000": ["dest_x", "dest_y", "height", "width"]}
         and len(done) == 1 and done[0]["capture"]["addr"] == "0x00000000" and done[0]["lag"] == 1
         and [fields.get(r, {}).get(k) for r in ("dest_x", "dest_y")
              for k in ("word", "sign", "add")] == [10, -1, 240, 11, -1, 239], said(draft))
    control = [c for c in report.get("correlations", []) if c["capture"]["addr"] == "0x00004080"]
    cell(t[14], len(control) == 1 and control[0]["command"] is None, str(control)[:110])
    loaded = call("gfx_load", path=str(dest))
    blits = call("gfx_blits", draw_command="write_2000", detail=True)
    box = ((blits.get("blits") or [{}])[0]).get("box", {})
    window = ((last.get("matches") or [{}])[0]).get("window")
    cell(t[15], loaded.get("draft") is True and blits.get("blits_in_frame") == 1
         and [box.get("x"), box.get("y")] == window, f"box {box}, located {window}")
    again = call("gfx_draft", dest=str(dest))
    confirmed = dest.with_name("confirmed.yaml")
    confirmed.write_text("schema: 1\nsystems: [circus]\n")
    over = call("gfx_draft", dest=str(confirmed))
    cell(t[16], again.get("report", {}).get("sha256") == draft.get("report", {}).get("sha256")
         and refused(over, "bad_argument")
         and confirmed.read_text() == "schema: 1\nsystems: [circus]\n", said(over))
    call("close")


def _d_hardhat(t: list[str]) -> None:
    """The hall of fame at frame 2400: its text is pen 5 over pen 0, two banks for a 1-bit char,
    drawn from `characterram` a bit a pixel (`exidy.cpp`, `draw_background`)."""
    free_boot("hardhat", ["hhl-2.11a"], "0xa000")
    ran: dict[str, Any] = {}
    for _ in range(4):                     # each leg inside one call's wait
        ran = call("run_for", frames=600, seconds=10.0)
    codes = bytes.fromhex(str(call("read_block", tag="videoram", offset=3 * 32 + 6,
                                   length=7).get("hex", "")))
    if ran.get("frame_after") != 2400:
        codes = b""                        # not the hall of fame: nothing below is its answer
    r = call("gfx_locate", layouts=[BYTES_8X8], patch=[48, 24, 64, 8], tag="characterram",
             count=256, flips=["none"])
    found = sorted((m.get("window", [0])[0], m.get("tile")) for m in r.get("matches") or [])
    cell(t[21], ok(r) and ran.get("frame_after") == 2400 and len(codes) == 7
         and found == [(48 + 8 * i, code) for i, code in enumerate(codes)]
         and all((m.get("base") or {}).get("available") is False and m.get("pen_map")
                 for m in r.get("matches") or [])
         and (r.get("pen_map") or {}).get("tried") is True,
         f"videoram {codes.hex()}; {said(r)}")
    r = call("gfx_locate", layouts=[BYTES_8X8], patch=[48, 25, 64, 8], tag="characterram",
             count=256, flips=["none"])
    cell(t[22], ok(r) and ran.get("frame_after") == 2400 and r.get("matched") is False
         and (r.get("pen_map") or {}).get("tried") is True, said(r))
    call("close")


# EACH BOARD AND THE CELLS IT JUDGES, by their index in D_CELLS (`run_boards` says why the table
# is checked both ways).
D_BOARDS = tuple(Board(run, owned, free_boards_missing) for run, owned in (
    (_d_circus, (0, 1, 2, 10, 17, 18, 19, 20)), (_d_gridlee, (3, 4, 5)), (_d_witchgme, (6, 7)),
    (_d_starfire, (8, 11)), (_d_topgunnr, (9,)), (_d_discovery, (12, 13, 14, 15, 16)),
    (_d_hardhat, (21, 22))))
boards_cover("D_BOARDS", D_CELLS, D_BOARDS)


@section("D", "the graphics tools on free boards: known answers and negatives", D_CELLS)
def block_d() -> None:
    run_boards(D_CELLS, D_BOARDS)


# ============================================ Block E: the project's manifest on m68k-dual

E_CELLS = [
    "gfx_load reads the project's manifest whole, every field with its status",
    "gfx_blits reads a finished frame of the blitter's capture as boxes over the screen",
    "the known answer: the sprite plane composed from each blit's source, in the order drawn, "
    "is the screen's pens wherever it is opaque, on the page the screen shows",
    "the control: the same composition from the row before each source origin disagrees",
    "an area inside one blit's box lists it among the blits covering it, in the order drawn",
    "gfx_blit_source is byte-identical to what the project's renderer samples for that rectangle",
    "the control: the renderer's rectangle a row over is not",
    "gfx_blits by default is a summary, no blit listed, its text under the reply budget",
    "no stop's survey lists the capture's rows; watch_list does",
    "isolate draws the pen asked for in the contrast colour and every other pen grey, indexed",
    "pixel answers a crop round the point, the point's own pixel its colour and ringed white",
    "a margin is a view: dimmed round the rectangle, which is ringed; `data` holds the exact "
    "window, and its rectangle is the source without a margin",
    "and none of the graphics reads altered the session",
]


def _every_blit(frame: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every blit of `frame`, paged through `detail=True` by `next_first`, and the first page."""
    first_page = page = call("gfx_blits", draw_command="blit", frame=frame, detail=True, scale=1)
    blits = list(page.get("blits", []))
    while ok(page) and "next_first" in page:
        page = call("gfx_blits", draw_command="blit", frame=frame, detail=True, scale=1,
                    first=page["next_first"])
        blits += page.get("blits", [])
    return blits, first_page


def _png(path: str) -> Any:
    """A PNG the server wrote, read by the suite's own reader (`tests/png_read.py`)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import png_read
    return png_read.read(Path(path).read_bytes())


def _compose(blits: list[dict[str, Any]], sources: dict[int, Any], page: int,
             shift: int) -> dict[tuple[int, int], int]:
    """The sprite plane's pixels on screen from each blit's source (read with a margin of one),
    later blits over earlier ones, source pixel 0 transparent: `shift` rows back from the row
    the blitter reads (0 is the known answer, 1 the control)."""
    out: dict[tuple[int, int], int] = {}
    for b in blits:
        if b["index"] not in sources or b.get("page") != page:
            continue
        pic, rect = sources[b["index"]]
        box = b["box"]
        for j in range(rect["height"]):
            row = j if rect["dir_y"] == 1 else rect["height"] - 1 - j
            y = (box["y"] + box["dir_y"] * j) % 512 - 256 * page
            for i in range(rect["width"]):
                col = i if rect["dir_x"] == 1 else rect["width"] - 1 - i
                v = pic.at(1 + col, 1 + row - shift)
                if v:
                    out[((box["x"] + box["dir_x"] * i) % 512, y)] = v
    return out


def _renderer_tile(tile: int, x: int, y: int, w: int, h: int) -> bytes | None:
    """What the project's renderer samples for a tile whose descriptor sends the blitter to page
    `tile` at (`x`, `y`), `w` x `h`: its own `tile()` over a descriptor written into a copy of its
    ROM. The bench holds one capture per argument set, taken by `fill`, because the renderer
    needs its project's own environment (numpy); the m68k-dual boot already checked every pin.
    None when no capture is pinned for these arguments: the rectangle is not the one pinned."""
    name = f"{value('m68k-dual', 'dir')}/renderer/tile{tile}_x{x}_y{y}_{w}x{h}.bin"
    return None if bench_missing(name) else (BENCH.root / name).read_bytes()


@section("E", "the project's manifest on m68k-dual: boxes, sources, the renderer", E_CELLS)
def block_e() -> None:
    t = E_CELLS
    boot()
    for _ in range(9):
        call("run_for", frames=100, seconds=10.0)
    before = call("status")["session"]["altering_writes"]
    man = call("gfx_load", path=MANIFEST)
    counts = man.get("status_counts", {})
    cell(t[0], ok(man) and "blit" in man.get("commands", {})
         and sum(counts.values()) > 0 and counts.get("proved", 0) > 0, said(man))
    call("watch_add", ref=BLITTER, mode="capture", length=32, trigger=BLIT_TRIGGER)
    call("run_for", frames=3, seconds=10.0)
    summary = call("gfx_blits", draw_command="blit", scale=1)
    blits, boxes = _every_blit(int(summary.get("frame_blit", -1)))
    cell(t[1], ok(boxes) and boxes.get("frame_complete") is True and bool(blits)
         and len(blits) == summary.get("blits_in_frame")
         and [b["index"] for b in blits] == list(range(len(blits)))
         and all(b["pc"] for b in blits), said(boxes))
    text = len(json.dumps(summary, indent=2))
    cell(t[7], ok(summary) and "blits" not in summary and text < REPLY_BUDGET_CHARS,
         f"{summary.get('blits_in_frame')} blits, {text} characters of text")
    survey = [w for w in summary.get("watches", []) if w.get("mode") == "capture"]
    listed = [w for w in call("watch_list").get("watches", []) if w.get("mode") == "capture"]
    cell(t[8], bool(survey) and all("first_rows" not in w and w.get("rows_listed_by")
                                    == "watch_list" for w in survey)
         and bool(listed) and all(w.get("first_rows") for w in listed),
         f"{len(survey)} in the survey, {len(listed)} listed")
    screen = call("screen_view", scale=1)
    pens = _png(str(screen.get("image", {}).get("path")))
    frame = boxes.get("frame_blit")
    drawn = [b for b in blits if b.get("plane") == "sprites" and b["fields"].get("reads_source")
             and not b["flags"].get("writes_index_0")]   # m68k-dual's driver skips those blits
    sources: dict[int, Any] = {}
    for b in drawn:
        src = call("gfx_blit_source", draw_command="blit", frame=frame, index=b["index"], margin=1,
                   scale=1)
        if ok(src):
            sources[b["index"]] = (_png(str(src["data"]["path"])), src["rect"])
    best: tuple[int, int, int] | None = None
    for page in (0, 1):
        plane = _compose(drawn, sources, page, 0)
        seen = [(x, y) for x, y in plane if 0 <= x < pens.width and 0 <= y < pens.height]
        agree = sum(1 for x, y in seen if pens.at(x, y) == plane[x, y])
        if seen and (best is None or agree - len(seen) > best[1] - best[2]):
            best = (page, agree, len(seen))
    shown = best[0] if best else -1
    cell(t[2], best is not None and best[1] == best[2] and len(sources) == len(drawn),
         f"page {shown}: {best[1] if best else 0} of {best[2] if best else 0} pixels agree, "
         f"{len(sources)} of {len(drawn)} sources read")
    off = _compose(drawn, sources, shown, 1)
    seen_off = [(x, y) for x, y in off if 0 <= x < pens.width and 0 <= y < pens.height]
    wrong = sum(1 for x, y in seen_off if pens.at(x, y) != off[x, y])
    cell(t[3], bool(seen_off) and wrong > 0, f"{wrong} of {len(seen_off)} disagree")
    first = next((b for b in drawn if b.get("page") == shown and b["on_screen"]), None)
    if first is None:
        cell(t[4], False, "no sprite blit of the shown page is on screen")
    else:
        x, y, w, h = first["screen"][0]
        area = call("gfx_blits", draw_command="blit", frame=frame, area=[x + w // 2, y + h // 2, 1,
                                                                         1],
                    scale=1)
        order = [b["index"] for b in area.get("blits", [])]
        cell(t[4], ok(area) and first["index"] in order and order == sorted(order), said(area))
    if first is None or first["index"] not in sources:
        cell(t[5], False, "no blit to compare")
        cell(t[6], False, "no blit to compare")
    else:
        src = call("gfx_blit_source", draw_command="blit", frame=frame, index=first["index"],
                   scale=1)
        rect = src.get("rect", {})
        pic = _png(str(src.get("image", {}).get("path")))
        # the register origin is the rectangle's first row less the manifest's declared add of 1
        mine = _renderer_tile(rect["tile"], rect["x"], rect["y"] - 1, rect["width"],
                              rect["height"])
        over = _renderer_tile(rect["tile"], rect["x"], rect["y"], rect["width"], rect["height"])
        where = (f"{rect.get('width')}x{rect.get('height')} at ({rect.get('x')}, "
                 f"{rect.get('y')}) of page {rect.get('tile')}")
        if mine is None or over is None:
            # A RECTANGLE NOBODY PINNED is the scene or the server's rect having moved: a FAIL
            # naming it, never a BLOCKED that would read as nothing wrong.
            cell(t[5], False, f"{where}: no renderer capture pinned on the bench for it")
            cell(t[6], False, f"{where}: no renderer capture pinned on the bench for it")
        else:
            cell(t[5], ok(src) and bytes(pic.pixels) == mine and len(mine) > 0,
                 f"{where}: {len(mine)} bytes")
            cell(t[6], len(over) == len(mine) and over != mine, f"{len(over)} bytes")
    _e_views(t, pens, first, frame)
    call("watch_clear", all=True)
    after = call("status")
    cell(t[-1],
         after["session"]["altering_writes"] == before and after["session"]["altered"] is False,
         f"writes {before} -> {after['session']['altering_writes']}")


def _e_views(t: list[str], pens: Any, first: dict[str, Any] | None, frame: Any) -> None:
    """The three views the owner's review reshaped, read back from the files they wrote."""
    pen = pens.at(46, 160)
    iso = call("screen_view", mode="isolate", pens=[pen], scale=1)
    pic = _png(str(iso.get("image", {}).get("path")))
    greys = [c for i, c in enumerate(pic.palette) if i != pen]
    cell(t[9], ok(iso) and pic.indexed and bytes(pic.pixels) == bytes(pens.pixels)
         and pic.palette[pen] == mscreen.ISOLATE_COLOUR and all(r == g == b for r, g, b in greys),
         f"pen {pen}: {said(iso, 80)}")
    px = call("screen_view", mode="pixel", point=[46, 160], scale=4)
    view = _png(str(px.get("image", {}).get("path")))
    ax, ay = px.get("point_in_crop", [0, 0])
    colour = tuple(int(str(px.get("color", "#000000"))[i:i + 2], 16) for i in (1, 3, 5))
    b = px.get("image", {}).get("border", 0)
    cell(t[10], ok(px) and px.get("pen") == pen and b == len(mscreen.POINT_RINGS)
         and view.at(b + ax * 4 + 1, b + ay * 4 + 1) == colour
         and view.at(b + ax * 4 - 1, b + ay * 4) == (255, 255, 255),
         f"{px.get('crop')} {said(px, 80)}")
    if first is None:
        cell(t[11], False, "no sprite blit of the shown page is on screen")
        return
    bare = call("gfx_blit_source", draw_command="blit", frame=frame, index=first["index"], scale=1)
    wide = call("gfx_blit_source", draw_command="blit", frame=frame, index=first["index"], margin=2,
                scale=1)
    exact = _png(str(bare.get("image", {}).get("path")))
    data = _png(str(wide.get("data", {}).get("path")))
    shown = _png(str(wide.get("image", {}).get("path")))
    w, h = exact.width, exact.height
    inner = bytes(data.pixels[(2 + j) * data.width + 2 + i] for j in range(h) for i in range(w))
    cell(t[11], ok(wide) and data.indexed and not shown.indexed and inner == bytes(exact.pixels)
         and shown.at(1, 2) == (255, 255, 255) and wide.get("box") == [2, 2, w, h],
         f"{w}x{h} with a margin of 2: {said(wide, 60)}")


#: The name of m68k-dual's palette port in m68k-dual's manifest, which is a RAMDAC.
RAMDAC = "ramdac"
F_CELLS = [
    "with no log armed, the pixel names the `palette_log` call that arms one",
    "a palette port the manifest does not declare is refused, naming the ones it does",
    "palette_log arms the RAMDAC the project's manifest declares",
    "a frame later the log placed the game's writes on pens",
    "before any write of the server's, every logged write is the game's, the last one before "
    "a frame's stop included",
    "the known answer: a pen the log saw completed by its third component, red and blue apart, "
    "holds in the palette device the colour the log composed",
    "the control: the same components read in the order b, g, r are not",
    "the server's own write of a pen is that pen's last setter at the pixel, the debugger's, "
    "agreeing with the live colour",
    "a state load unsyncs the log: no write lands on a pen until an index write",
    "and the log itself altered nothing: before the state load, the only writes counted are the "
    "server's four",
    "a log whose data tap raises counts one error per synced data write, never an empty census",
]


#: The most frames block F runs, one at a time, to find a pen `_completed_pen_red_blue_apart`
#: takes.
PEN_SEARCH_FRAMES_MAX = 30


def _completed_pen_red_blue_apart(r: dict[str, Any]) -> int | None:
    """Of a log read's rows, the newest pen whose own newest write is its third component (`b`)
    and leaves red and blue apart, or None: such a pen is whole in the device at any later stop
    until the game writes it again, and only red and blue apart lets the reversed order below tell
    two readings apart. Chosen from what the log recorded, so the cell asks no scene of a build."""
    seen: set[int] = set()
    for x in sorted((x for x in r.get("rows", []) if "pen" in x), key=lambda x: -x["n"]):
        if x["pen"] in seen:
            continue
        seen.add(x["pen"])
        color = str(x.get("color") or "")
        if x.get("component") == "b" and len(color) == 7 and color[1:3] != color[5:7]:
            return int(x["pen"])
    return None


@section("F", "the palette write log on m68k-dual: which pen, and who set it", F_CELLS)
def block_f() -> None:
    t = F_CELLS
    boot()
    call("gfx_load", path=MANIFEST)
    for frames in (100,) * 8 + (98,):
        call("run_for", frames=frames, seconds=10.0)
    before = call("status")["session"]["altering_writes"]
    call("run_for", milliseconds=6, seconds=10.0)
    px = call("screen_view", mode="pixel", point=[100, 100])
    cell(t[0], ok(px)
         and f'palette_log(palette_port="{RAMDAC}", arm=True)'
         in str(unavailable_why(px.get("set_by"))),
         said(px))
    nope = call("palette_log", palette_port="dac")
    cell(t[1], refused(nope, "unknown_ref") and nope.get("palette_ports") == [RAMDAC], said(nope))
    armed = call("palette_log", palette_port=RAMDAC, arm=True)
    cell(t[2], ok(armed) and armed.get("armed_now") is True, said(armed))
    call("run_for", frames=2, seconds=10.0)
    logged = call("palette_log", palette_port=RAMDAC, limit=4)
    cell(t[3], ok(logged) and logged.get("writes_total", 0) > 0 and bool(logged.get("pens_written"))
         and logged.get("index_writes", 0) > 0, said(logged))
    rows = list(mramdac.rows(Path(str(logged.get("rows_path")))))
    cell(t[4], bool(rows) and all(x.by == "guest" for x in rows if x.kind != "x"),
         f"{len(rows)} rows, {sum(1 for x in rows if x.by == 'debugger')} the debugger's")
    def find_pen() -> int | None:
        return _completed_pen_red_blue_apart(
            call("palette_log", palette_port=RAMDAC, limit=mramdac.LIMIT_MAX))
    pen, ran = find_pen(), 0
    while pen is None and ran < PEN_SEARCH_FRAMES_MAX:
        call("run_for", frames=1, seconds=10.0)
        pen, ran = find_pen(), ran + 1
    mine = ({} if pen is None else
            call("palette_log", palette_port=RAMDAC, pen=pen, limit=1).get("pen_state") or {})
    if pen is None:
        # The game offered no such pen: a fact about its scene, which says nothing of the log.
        why = f"no pen completed with red and blue apart in {PEN_SEARCH_FRAMES_MAX} frames"
        blocked(t[5], why)
        blocked(t[6], why)
    else:
        live = call("palette", first=pen, count=1).get("colors", [None])[0]
        cell(t[5], mine.get("color") == live and live is not None,
             f"pen {pen}: log {mine.get('color')}, palette {live}")
        c = mine.get("components", {})
        bgr = f"#{c.get('b', 0):02x}{c.get('g', 0):02x}{c.get('r', 0):02x}"
        cell(t[6], bgr != live,
             f"pen {pen}: b, g, r reads {bgr} against {live}")
    call("run_for", milliseconds=6, seconds=10.0)
    px = call("screen_view", mode="pixel", point=[100, 100])
    pen = px.get("pen")
    wrote = False
    if isinstance(pen, int) and pen < 256:
        wrote = ok(call("write", ref="0x720001", data_hex=f"{pen:02x}"))
        for v in ("12", "34", "56"):
            wrote = ok(call("write", ref="0x720003", data_hex=v)) and wrote
    after = call("screen_view", mode="pixel", point=[100, 100])
    by = after.get("set_by") or {}
    cell(t[7], wrote and after.get("color") == "#123456" and by.get("color") == "#123456"
         and by.get("last", {}).get("written_by") == "debugger" and by.get("agrees") is True,
         said(after))
    written = call("status")["session"]["altering_writes"]
    name = fresh_state()
    call("state_save", name=name)
    call("run_for", milliseconds=3, seconds=10.0)
    call("state_load", name=name)
    call("run_for", frames=1, seconds=10.0)
    loaded = call("palette_log", palette_port=RAMDAC, limit=1)
    rows = list(mramdac.rows(Path(str(loaded.get("rows_path")))))
    at = next((i for i, x in enumerate(rows) if x.kind == "x" and x.reason == "load"), None)
    tail = rows[at + 1:] if at is not None else []
    first_index = next((i for i, x in enumerate(tail) if x.kind == "i"), len(tail))
    placed_early = [x.n for x in tail[:first_index] if x.kind == "d" and x.pen is not None]
    cell(t[8], at is not None and loaded.get("desyncs", 0) >= 1 and not placed_early
         and any(x.kind == "d" and x.pen is not None for x in tail[first_index:]),
         f"desync at row {rows[at].n if at is not None else None}, {len(tail)} rows after, "
         f"placed before an index write: {placed_early[:4]}")
    call("palette_log", palette_port=RAMDAC, clear=True)
    cell(t[9], written - before == 4, f"writes {before} -> {written}")
    armed = call("palette_log", palette_port=RAMDAC, arm=True)
    call("run_for", frames=2, seconds=10.0)
    at = planted_at(plant_fault("MCP_RAMDAC", str(armed.get("tally_id")), (
        f'setmetatable(t.pens, {{__index = function() error("{FAULT}") end}})\n'
        "for k in pairs(t.pens) do t.pens[k] = nil end"), "t.total - t.unsynced"))
    call("run_for", frames=2, seconds=10.0)
    log = call("palette_log", palette_port=RAMDAC, limit=1)
    count, first = raised(log)
    grew = int(log.get("writes_total", -1)) - int(log.get("unsynced_writes", 0)) - at
    cell(t[10], at >= 0 and grew > 0 and count == grew and FAULT in first
         and "callbacks raised" in str(log.get("summary")),
         f"synced data writes since the plant {grew}, errors {count}, first {first[:60]!r}")
    call("palette_log", palette_port=RAMDAC, clear=True)


# ============================================ Block G: the conditioned film on m68k-dual

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
    rows_path = next((w.get("rows_path") for w in call("watch_list").get("watches", [])
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
    grew = int(by_ref(call("watch_list").get("watches")).get(BLIT_TRIGGER, {})
               .get("total", -1)) - at
    cell(t[10], at >= 0 and grew > 0 and count == grew and FAULT in first
         and 0 <= first_met < met and film.get("met") == met
         and "callbacks raised" in str(film.get("summary")),
         f"strobe writes since the plant {grew}, errors {count}, met {first_met} unplanted -> "
         f"{met}, then {film.get('met')} planted, first {first[:60]!r}")
    call("gfx_film", clear=True)
    call("watch_clear", all=True)


# ================================================= Section I: what `cpu_info` says of each cpu
#
# `cpu_info`'s rows on m68k-dual's two 68000s, each reading against an answer that does not come
# from `cpu_info`: the cpu's own `registers`, its `curpc` shown through `focus`, the console's
# listings, the `_list` tools' rows. "Moves nothing" is judged by readings that a step is proved
# to change, so the instrument can see a move.

I_CELLS = [
    "the sub cpu runs: its totalcycles grows across a frame",
    "cpu_info has a row for both cpus, each pc with its register and a value",
    "each cpu's pc equals its own registers' pc, numerically",
    "the sub cpu's pc equals its curpc shown through focus and back",
    "the visible cpu's pc equals status's pc",
    "after a step the visible cpu's pc is the step's, and it moved",
    "focus moves the visible row to the sub cpu, and back",
    "an ignored sub cpu is marked ignored and still read, and observe clears it",
    "a suspended sub cpu is marked suspended and still read, and resume clears it",
    "each cpu's counts equal the rows the _list tools give for it",
    "a bpclear typed at the console leaves the counts, and the rows read gone",
    "cpu_info moves nothing: frame, cycles, curpc, the listings, each cpu's registers",
    "the control: the same readings around a step differ in totalcycles and curpc",
]


# Read through `debug`, never the server's own readers: the answer each cell compares with
# `cpu_info` must not come from `cpu_info`'s code. -1 for an answer that is not a number, so a
# refused read fails its cell instead of ending the section.
def _printed(expr: str) -> int:
    words = str(call("debug", command=f"print {expr}").get("output") or "").split()
    try:
        return int(words[0], 16)
    except (IndexError, ValueError):
        return -1


def _sub_cycles() -> int:
    call("focus", cpu="subcpu")
    cycles = _printed("totalcycles")
    call("focus", cpu="maincpu")
    return cycles


def _rows(reply: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`cpu_info`'s rows by cpu."""
    return {row["cpu"]: row for row in reply.get("cpus") or []}


def _hex(value: Any) -> int:
    return int(value, 16) if isinstance(value, str) else -1


def _pc(rows: dict[str, dict[str, Any]], tag: str) -> dict[str, Any]:
    """A row's pc reading, empty when the row is absent or its pc unread."""
    return (rows.get(tag) or {}).get("pc") or {}


def _pc_of(rows: dict[str, dict[str, Any]], tag: str) -> int:
    """A row's pc value, or -1 when the row is absent or its pc unread."""
    return _hex(_pc(rows, tag).get("value"))


CYCLES, CURPC = "print frame,totalcycles", "print curpc"


def _readings() -> dict[str, Any]:
    """What a move would change, read through the console and each cpu's own thread."""
    out: dict[str, Any] = {c: call("debug", command=c).get("output") for c in (
        CYCLES, CURPC, "cpulist", "ignore", "suspend")}
    for tag in (MAIN, SUB):
        out[tag] = call("registers", cpu=tag).get("regs")
    return out


@section("I", "what cpu_info says of each cpu, on m68k-dual's two 68000s", I_CELLS)
def block_i_cpu_info() -> None:
    t = I_CELLS
    boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
    # The sub cpu leaves reset when the main one releases it, early in the boot.
    call("run_for", frames=60, seconds=10.0)
    before = _sub_cycles()
    call("run_for", frames=1, seconds=10.0)
    after = _sub_cycles()
    cell(t[0], after > before >= 0, f"{before:#x} -> {after:#x}")
    first_info = call("cpu_info")
    rows = _rows(first_info)
    cell(t[1], list(rows) == [MAIN, SUB]
         and all({"reg", "value"} <= set(r["pc"] or {}) for r in rows.values()),
         f"{[(c, r['pc']) for c, r in rows.items()]}")
    regs = {tag: call("registers", cpu=tag).get("regs", {}) for tag in (MAIN, SUB)}
    equal = {tag: _pc_of(rows, tag) >= 0
             and _pc_of(rows, tag) == _hex(regs[tag].get(_pc(rows, tag).get("reg", "")))
             for tag in (MAIN, SUB)}
    cell(t[2], all(equal.values()), f"{equal} {[r.get('PC') for r in regs.values()]}")
    call("focus", cpu="subcpu")
    curpc = _printed("curpc")
    call("focus", cpu="maincpu")
    cell(t[3], curpc >= 0 and _pc_of(rows, SUB) == curpc, f"{_pc_of(rows, SUB):#x} vs {curpc:#x}")
    st = call("status")
    cell(t[4], visible_of(first_info) == MAIN and _pc_of(rows, MAIN) == _hex(st.get("pc")),
         f"visible {visible_of(first_info)}, {_pc_of(rows, MAIN):#x} vs pc {st.get('pc')}")
    stepped = call("step", count=1)
    now = _rows(call("cpu_info"))
    cell(t[5], _pc_of(now, MAIN) == _hex(stepped.get("pc")) >= 0
         and _pc_of(now, MAIN) != _pc_of(rows, MAIN),
         f"{_pc_of(rows, MAIN):#x} -> {_pc_of(now, MAIN):#x}, step pc {stepped.get('pc')}")
    call("focus", cpu="subcpu")
    shown = visible_of(call("cpu_info"))
    call("focus", cpu="maincpu")
    back = visible_of(call("cpu_info"))
    cell(t[6], shown == SUB and back == MAIN, f"{shown}, then {back}")
    # The live cpu first: ignoring or suspending the cpu MAME is live on would run the machine.
    live = (call("status").get("last_stop") or {}).get("cpu")
    call("debug", command="ignore :subcpu")
    ignoring = _rows(call("cpu_info"))
    call("debug", command="observe :subcpu")
    cleared = _rows(call("cpu_info"))
    cell(t[7], live == MAIN and (ignoring.get(SUB) or {}).get("ignored") is True
         and (cleared.get(SUB) or {}).get("ignored") is False and _pc_of(ignoring, SUB) >= 0,
         f"live {live}, {ignoring.get(SUB)}, then {cleared.get(SUB)}")
    call("debug", command="suspend :subcpu")
    holding = _rows(call("cpu_info"))
    call("debug", command="resume :subcpu")
    released = _rows(call("cpu_info"))
    cell(t[8], (holding.get(SUB) or {}).get("suspended") is True
         and (released.get(SUB) or {}).get("suspended") is False and _pc_of(holding, SUB) >= 0,
         f"{holding.get(SUB)}, then {released.get(SUB)}")
    call("breakpoint_at", ref="exception_handler", cpu=MAIN)
    call("breakpoint_at", ref="0x8", cpu=SUB)
    call("watch_add", ref="0x200000", mode="change", length=2, cpu=SUB)
    call("regpoint_add", condition="pc==0xfffffffe")
    counts = {tag: row["declarations"] for tag, row in _rows(call("cpu_info")).items()}
    rows_listed = {tag: (len(call("breakpoint_list", cpu=tag).get("breakpoints", [])),
                         len(call("watch_list", cpu=tag).get("watches", [])))
                   for tag in (MAIN, SUB)}
    regpoints = len(call("regpoint_list").get("regpoints", []))
    cell(t[9], all((counts.get(tag, {}).get("breakpoints"), counts.get(tag, {}).get("watches"))
                   == rows_listed[tag] for tag in (MAIN, SUB))
         and counts.get(MAIN, {}).get("regpoints") == regpoints and rows_listed[SUB] == (1, 1),
         f"{counts} vs rows {rows_listed}, regpoints {regpoints}")
    call("debug", command="bpclear")
    kept = {tag: row["declarations"] for tag, row in _rows(call("cpu_info")).items()}
    states = [b.get("state") for b in call("breakpoint_list").get("breakpoints", [])]
    cell(t[10], kept == counts and states == ["gone", "gone"], f"{kept}, states {states}")
    call("breakpoint_clear", all=True)
    call("watch_clear", all=True)
    call("regpoint_clear", all=True)
    first = _readings()
    between = call("cpu_info")
    second = _readings()
    cell(t[11], ok(between) and first == second,
         f"{said(between, 40)}; differ in {[k for k in first if first[k] != second[k]]}")
    call("step", count=1)
    third = _readings()
    cell(t[12], third[CYCLES] != second[CYCLES] and third[CURPC] != second[CURPC],
         f"{second[CURPC]!r} -> {third[CURPC]!r}")
    ensure_closed()


# ================================ Block J: the value scan, against MAME's own cheat engine
#
# The independent answer is the console's `cheatinit`/`cheatnextf` at the same stops, compared
# with what was opened (`cheatnextf`), never a survivor address written here: the game decides
# which cells move, the engine says which ones did. m68k-dual's engine admits every cell but those
# the driver taps for writes, whose growth is discounted from its count.

J_CELLS = [
    "m68k-dual: a :maincpu scan narrows the credits and matches the console's cheat engine at "
    "every filter",
    "m68k-dual: a :subcpu scan names its cpu and an `=` after a `>` round closes it",
    "m68k-dual: a second scan_start, a filter with none open, a scan on a running machine are "
    "refused",
    "m68k-dual: the scan calls move neither pc, stop_seq nor the emulated time, and alter nothing",
    "circus: the clown's latch narrows the RAM to the console's own survivors at every filter",
]
_FOUND = re.compile(r"(\d+) cheats found")
_INIT = re.compile(r"(\d+) cheat locations initialized for .* '([^']+)' program space")
_LIST_ROW = re.compile(r"Possibility \d+: ([0-9A-F]+) \(([0-9A-F]+)\)")
# m68k-dual's write taps: no direct write pointer, so the engine's `cheatinit` leaves them out.
# The fixture the unit tests compare against is the one list of them, read when the board runs
# so that a missing file fails that board and not the whole matrix at import.
_TAPS_FILE = Path(__file__).parents[1] / "fixtures" / "scan" / "m68k-dual-ub-not-admitted.txt"


def _tap_addrs() -> tuple[int, ...]:
    return tuple(int(a, 16) for a in _TAPS_FILE.read_text().split())


def _engine_init(spec: str, tag: str) -> bool:
    """`cheatinit` on `tag`, true only when its line names that tag's program space."""
    m = _INIT.search(str(call("debug", command=f"cheatinit {spec},{tag}").get("output") or ""))
    return m is not None and m.group(2) == tag and int(m.group(1)) > 0


def _engine_rows() -> set[tuple[int, int]]:
    """The engine's survivors as (address, current value), off its own `cheatlist`."""
    path = Path(fresh(".xml"))
    call("debug", command=f"cheatlist {path}")
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {(int(a, 16), int(v, 16)) for a, v in _LIST_ROW.findall(text)}


def _hits(r: dict[str, Any]) -> set[tuple[int, int]]:
    return {(int(h["addr"], 16), int(h["value"], 16)) for h in r.get("hits") or []}


def _same(r: dict[str, Any], count: int, leave_out: tuple[int, ...] = ()) -> bool | None:
    """The tool's survivors against the engine's, as sets; None when the reply lists none (past
    the list ceiling), where only the counts compare, so a cell needs one True besides."""
    if r.get("truncated"):
        return None
    return {(a, v) for a, v in _hits(r) if a not in leave_out} == _engine_rows() and (
        len([1 for a, _ in _hits(r) if a not in leave_out]) == count)


def _engine(cond: str) -> int:
    """The console's own engine filtered against the opening: its count of survivors, or -1."""
    found = _FOUND.findall(str(call("debug", command=f"cheatnextf {cond}").get("output") or ""))
    return int(found[-1]) if found else -1


def _where() -> tuple[Any, ...]:
    """`pc`, `stop_seq` and the emulated time; None in any of them reads as not read."""
    st = call("status")
    return (st.get("pc"), (st.get("last_stop") or {}).get("stop_seq"),
            str(call("debug", command="time").get("output") or "").strip() or None)


def _taps(addrs: tuple[int, ...]) -> list[int]:
    return [int(call("read_memory", ref=f"{a:#x}", length=1).get("hex") or "-1", 16)
            for a in addrs]


def _j_m68k_dual(t: list[str]) -> None:
    boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
    call("run_for", frames=600, seconds=10.0)
    before = _where()
    opened = call("scan_start", ref="0x200000", length=0x10000, cpu="maincpu")
    shut = call("scan_filter", operator="!")
    after = _where()
    unaltered = not any((x.get("session") or {}).get("altered") for x in (opened, shut))
    cell(t[3], ok(opened) and shut.get("closed") is True and None not in before
         and before == after and unaltered, f"{before} -> {after}; {said(shut)}")
    call("scan_start", ref="0x200000", length=0x10000, cpu="maincpu")
    inited = _engine_init("ub,0x200000,0x10000", MAIN)
    taps = _tap_addrs()
    held, rounds = [True] * len(taps), []
    for k in (1, 2):                        # the credits after the k-th coin hold k
        call("input", port=":P1", field="Coin 1", seconds=10.0)
        call("run_for", frames=30, seconds=10.0)
        r = call("scan_filter", operator="=", value=k)
        held = [h and n == k for h, n in zip(held, _taps(taps), strict=True)]
        engine = _engine(f"equal,0x{k:x}")
        rounds.append((r.get("hits_total"), engine, sum(held), r.get("cpu"), r.get("space"),
                       _same(r, engine, taps)))
    cell(t[0], inited and len(rounds) == 2
         and all(h is not None and h - tap == e and c == MAIN and sp == "program"
                 and same is not False for h, e, tap, c, sp, same in rounds)
         and any(same for *_, same in rounds)
         and 0 < int(rounds[1][0] or 0) < int(rounds[0][0] or 0),
         f"(tool, engine, taps held, cpu, space, sets) {rounds}")
    call("scan_clear")
    sub = call("scan_start", ref="0x200000", length=0x10000, cpu="subcpu")
    inited = _engine_init("ub,0x200000,0x10000", SUB)
    call("run_for", frames=7, seconds=10.0)
    grew, engine = call("scan_filter", operator=">"), _engine("increase")
    same = _same(grew, engine)
    if grew.get("closed"):
        end, engine_end = grew, engine          # the `>` round itself closed it: that is the end
    else:
        end, engine_end = call("scan_filter", operator="="), _engine("equal")
    cell(t[1], inited and sub.get("cpu") == SUB and grew.get("cpu") == SUB and same is True
         and grew.get("hits_total") == engine and end.get("closed") is True and engine_end == 0,
         f"`>` {grew.get('hits_total')} vs engine {engine}; end {said(end)} engine {engine_end}")
    call("scan_start", ref="0x200000", length=0x100, cpu="maincpu")
    second = call("scan_start", ref="0x200000", length=0x100, cpu="maincpu")
    call("scan_clear")
    none = call("scan_filter", operator="=")
    call("resume")
    running = call("scan_start", ref="0x200000", length=0x100, cpu="maincpu")
    call("stop")
    cell(t[2], refused(second, "needs_call") and refused(none, "needs_call")
         and refused(running, "not_stopped"), f"{said(second, 40)}; {said(none, 40)}; "
         f"{said(running, 40)}")
    call("close")


def _wrote() -> str | None:
    r = call("resume", seconds=5.0)
    if r.get("verdict") != "OTHER_STOP":
        call("stop")
        return None
    writes = (r.get("watch_hit") or {}).get("writes") or []
    return str(writes[-1].get("wrote")) if writes else None


def _j_circus(t: list[str]) -> None:
    circus_boot()
    call("watch_add", ref="0x2000", mode="change", length=1)
    # The latch holds its first value through the attract's first seconds, climbs without a
    # repeat, then swings back and forth. A scan opened before the swing never sees the latch
    # come back to its opening, so it opens at the first value written twice in a row after
    # the latch has left its first one: a value the swing returns to.
    first = previous = _wrote()
    opening = None
    for _ in range(400):
        now = _wrote()
        if now is not None and now == previous and now != first:
            opening = now
            break
        previous = now
    call("scan_start", ref="0x0", length=0x200)
    inited = _engine_init("ub,0x0,0x200", MAIN)
    kinds, rounds, wrote = {"!": 0, "=": 0}, [], opening
    for _ in range(60):
        wrote = _wrote() or wrote
        op = "!" if wrote != opening else "="
        r = call("scan_filter", operator=op)
        engine = _engine("notequal" if op == "!" else "equal")
        rounds.append((op, r.get("hits_total"), engine, _same(r, engine)))
        kinds[op] += 1
        if r.get("closed") or min(kinds.values()) >= 2:
            break
    agree = (all(h == e and same is not False for _, h, e, same in rounds)
             and any(same for *_, same in rounds))
    enough = min(kinds.values()) >= 2
    cell(t[4], inited and opening is not None and agree and enough,
         ("too few movements: " if agree and not enough else "") + f"{kinds} {rounds[-4:]}")
    call("close")


J_BOARDS = (Board(_j_m68k_dual, (0, 1, 2, 3), m68k_dual_missing),
            Board(_j_circus, (4,), free_boards_missing))
boards_cover("J_BOARDS", J_CELLS, J_BOARDS)


@section("J", "the value scan: known answers and refusals", J_CELLS)
def block_j_scan() -> None:
    run_boards(J_CELLS, J_BOARDS)


# ============ Block K: a link for a state, a bool for a count, installs queued, resent and lost
#
# The state folder is the host's, so a name can be taken by something that holds no state; the
# server lists it and refuses it by name rather than escaping or calling it absent. And a bool is an
# `int` to Python: a count or a wait handed one is refused, never run as 1 or read as "no deadline".
# A client's schema refuses a bool before any tool runs, so only a direct call, which is what `call`
# makes, reaches these guards. And count watches declared back to back while stopped queue their
# installs: the console reads one line per run of its hook, so an unthrottled frame can leave the
# last one still to run, which is waiting, not lost. What IS lost is driven on demand, on both
# boards, with the reader faulted harness-side (`reader_fault`): killed once, killed twice,
# handed back with no death, and held back for frames, after a control that installs.

K_OWN = [
    "circus: state_list lists the saved state with its bytes",
    "circus: state_list lists a link to nothing with bytes unavailable and its why",
    "circus: state_load refuses a link to nothing as unknown_ref naming it",
    "circus: state_save refuses the link's name as already there",
    "circus: run_for refuses frames=True and the frame does not move",
    "circus: resume refuses seconds=False and the machine stays stopped",
    "circus: four count watches queued while stopped: none resent across four frames, all "
    "installed by then, none lost",
]
# The same cells on each board (`_k_resend`, then `matrix_removals.k_removals`), after circus's
# own; each board is handed its cells by name, so no index is written by hand.
K_RESEND = [
    "the reader fault kills its install line, where the control's install answers at once",
    "an install whose reader dies once is resent once and installed",
    "an install whose reader dies twice is install_lost at the stop, and stays lost",
    "an install handed back with no death is resent while the machine only steps",
    "an install whose reader lags three frames is neither resent nor lost, then installed",
]


def on_board(board: str, whats: list[str]) -> list[str]:
    """`whats` as `board`'s cells."""
    return [f"{board}: {what}" for what in whats]


K_LEFTOVER, K_REDECLARE = f"m68k-dual: {K_CAPTURE_LEFTOVER}", f"circus: {K_REDECLARE_LIVE}"
K_CELLS = (K_OWN + on_board("circus", K_RESEND + K_REMOVALS)
           + on_board("m68k-dual", K_RESEND + K_REMOVALS) + [K_LEFTOVER, K_REDECLARE])


def _states_by_name(r: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in r.get("states") or []}


def _stop_and_frame(status: dict[str, Any]) -> tuple[Any, Any]:
    """The last stop's number and frame, which a run that moved would change. Not the whole
    `last_stop`: its `since_s` ticks between two reads."""
    last = status.get("last_stop") or {}
    return last.get("stop_seq"), last.get("frame")


def _k_circus(_cells: list[str]) -> None:
    t = K_OWN
    circus_boot()
    saved = call("state_save", name="kept")
    listed = call("state_list")
    mine = _states_by_name(listed).get("kept", {})
    # THE CONTROL, taken before any link exists: it is OK on a server that never heard of one,
    # so a FAIL below is about the link and not about listing.
    cell(t[0], ok(saved) and ok(listed) and isinstance(mine.get("bytes"), int)
         and mine.get("bytes") == saved.get("bytes"), f"{said(saved, 50)}; {mine}")
    folder = Path(str(listed.get("state_dir")))
    link, target = folder / "dangle.sta", folder / "nowhere" / "dangle.sta"
    try:
        link.symlink_to(target)
        listed = call("state_list")
        row = _states_by_name(listed).get("dangle", {})
        gone = [row.get(k) or {} for k in ("bytes", "frame", "pc")]
        cell(t[1], ok(listed) and "why" not in row
             and all(g.get("available") is False and str(target) in str(g.get("why"))
                     for g in gone), said(listed) if not row else str(row))
        load = call("state_load", name="dangle")
        cell(t[2], refused(load, "unknown_ref") and str(link) in str(load.get("message"))
             and str(target) in str(load.get("message")), said(load, 160))
        again = call("state_save", name="dangle")
        cell(t[3], refused(again, "bad_argument") and "already exists" in str(again.get("message")),
             said(again))
    finally:
        link.unlink(missing_ok=True)
        (folder / "kept.sta").unlink(missing_ok=True)
    before = _stop_and_frame(call("status"))
    ran = call("run_for", frames=True, seconds=5.0)
    after = _stop_and_frame(call("status"))
    cell(t[4], refused(ran, "bad_argument") and None not in before and after == before,
         f"{said(ran)}; (stop_seq, frame) {before} -> {after}")
    released = call("resume", seconds=False)
    now = call("status")
    if now.get("running"):
        call("stop")
    cell(t[5], refused(released, "bad_argument") and now.get("running") is False,
         f"{said(released)}; running after it: {now.get('running')}")
    # THE QUEUE IS MADE, not waited for: the reader fault holds the first install for two
    # frames, so the other three wait behind it past the first frame's stop, whose own console
    # commands would drain a queue released at that frame (REFERENCE.md, *The console*). A
    # queue that does not show proves nothing about waiting, so it is BLOCKED, not judged.
    call("run_for", frames=3, seconds=5.0)
    call("throttle", on=False)
    call("step")
    planted = reader_fault(f"tally-{_tally_id('0x20', 1)}.txt", lag=2)
    adds = [call("watch_add", ref=ref, mode="count", length=1)
            for ref in ("0x20", "0x36", "0x1f", "0x1b")]
    ran = call("run_for", frames=1, seconds=5.0)
    rows = ran.get("watches") or []
    queued = [w.get("installed") for w in rows]
    later = [call("run_for", frames=1, seconds=5.0) for _ in range(3)][-1]
    settled = [(w.get("installed"), w.get("install_resent")) for w in later.get("watches") or []]
    lost = (later.get("session") or {}).get("console", {}).get("lost")
    detail = (f"lines_ahead {[a.get('lines_ahead') for a in adds]}; after one frame installed "
              f"{queued}, resent {[w.get('install_resent') for w in rows]}; "
              f"three frames on {settled}, lost {lost}")
    if not (ok(planted) and "planted" in str(planted.get("output"))):
        blocked(t[6], f"the reader fault was not planted, so nothing was held: {detail}")
    elif all(ok(a) for a in adds) and ok(ran) and queued == [True] * 4:
        blocked(t[6], f"no install was still queued after the frame, nothing to judge: {detail}")
    else:
        cell(t[6], all(ok(a) for a in adds) and ok(ran) and ok(later)
             and [w.get("install_resent") for w in rows] == [0, 0, 0, 0]
             and settled == [(True, 0)] * 4 and lost == 0, detail)
    call("watch_clear", all=True)
    refs = ("0x20", "0x36", "0x1f", "0x1b")
    _k_resend(on_board("circus", K_RESEND), refs, 1)
    k_removals(on_board("circus", K_REMOVALS), refs[1:], 1)
    call("close")


def _k_m68k_dual(_cells: list[str]) -> None:
    boot()
    call("run_for", frames=3, seconds=10.0)
    refs = ("0x70001e", "0x70001c", "0x70001a", "0x700018")
    _k_resend(on_board("m68k-dual", K_RESEND), refs, 2)
    # The last range is the frame counter's low word, written once a frame: the blitter's
    # ranges can go three frames unwritten, and that cell compares a total.
    k_removals(on_board("m68k-dual", K_REMOVALS), (refs[1], refs[2], "0x2031fe"), 2)
    k_capture_leftover(K_LEFTOVER, "0x2031fc", "0x2031fe")
    call("close")


def _k_circus_redeclare(_cells: list[str]) -> None:
    # 0x1b is written every frame; the cell holds the new install itself (`k_redeclare_live`)
    circus_boot()
    call("run_for", frames=3, seconds=10.0)
    k_redeclare_live(K_REDECLARE, "0x1b", 1)
    call("close")


def _tally_id(ref: str, length: int) -> str:
    """The `tally_id` the server gives a count watch on `ref`, `length` bytes long: what a reader
    fault targets, so it is known before the watch is added."""
    return f"{int(ref, 16):x}_{length}"


def _k_resend(t: list[str], refs: tuple[str, ...], length: int) -> None:
    """`K_RESEND`'s five cells on a stopped machine, one count watch at each of `refs` (four
    ranges the board writes on its first cpu), every one cleared before the next. Only the
    first cell carries the control; the rest stand on it, the fault's own count saying it
    fired."""
    def tid(ref: str) -> str:
        return _tally_id(ref, length)

    def add(ref: str) -> dict[str, Any]:
        r = call("watch_add", ref=ref, mode="count", length=length)
        r["mine"] = ok(r) and r.get("tally_id") == tid(ref)    # the id the fault targets
        return r

    def mine(r: dict[str, Any], ref: str) -> dict[str, Any]:
        return next((w for w in r.get("watches") or [] if w.get("tally_id") == tid(ref)), {})

    def seen(r: dict[str, Any], ref: str) -> tuple[Any, Any, Any]:
        w = mine(r, ref)
        return w.get("installed"), w.get("state"), w.get("install_resent")

    def fault(ref: str, **how: Any) -> bool:
        planted = reader_fault(f"tally-{tid(ref)}.txt", **how)
        return ok(planted) and "planted" in str(planted.get("output"))

    def lost() -> Any:
        return (call("status").get("session") or {}).get("console", {}).get("lost")

    def cell_if_planted(label: str, planted: bool, condition: bool, detail: str) -> None:
        """A cell that stands on the reader fault: BLOCKED when the plant did not take, since
        nothing was then faulted and the cell would judge the server on a fault never made."""
        if planted:
            cell(label, condition, detail)
        else:
            blocked(label, f"the reader fault was not planted, so nothing was faulted: {detail}")

    def log() -> bytes:
        return Path(str(call("status").get("stdout_path"))).read_bytes()

    # THE CONTROL: no fault planted and nothing ahead in the pipe, the install answers at the
    # first step.
    for _ in range(4):
        if not call("status").get("console_pending"):
            break
        call("run_for", frames=1, seconds=5.0)
    control = add(refs[0])
    ctl = seen(call("step"), refs[0])
    call("watch_clear", ref=refs[0])
    planted = fault(refs[1], kills=1)
    mark = len(log())
    added = add(refs[1])
    first = call("step")
    fired = reader_fault_counts()[0]
    # The death line whole, which the plant's own echo never carries (it travels split).
    after_add = log()[mark:]
    at = after_add.find(f"tally-{tid(refs[1])}.txt".encode())
    died = at >= 0 and b"[LUA ERROR] in thread: killed" in after_add[at:]
    cell_if_planted(t[0], planted, control["mine"] and control.get("lines_ahead") == 0
          and ctl == (True, "tallied", 0) and added["mine"] and fired == 1 and died,
          f"control {ctl}, lines_ahead {control.get('lines_ahead')}; planted {planted}; "
          f"fired {fired}; death behind the echo {died}")
    second = call("step")
    once = [seen(first, refs[1]), seen(second, refs[1])]
    cell_if_planted(t[1], planted, once[0][2] == 1 and once[0][0] is False
          and mine(first, refs[1]).get("pending") is True
          and once[1] == (True, "tallied", 1), f"step by step {once}")
    call("watch_clear", ref=refs[1])

    lost_before = lost()
    planted = fault(refs[2], kills=2)
    added = add(refs[2])
    twice = [seen(call("step"), refs[2]) for _ in range(3)]
    fired = reader_fault_counts()[0]
    cell_if_planted(t[2], planted, added["mine"] and fired == 2 and twice[0][2] == 1
          and twice[1:] == [(False, "install_lost", 1)] * 2
          and isinstance(lost_before, int) and lost() == lost_before + 2,
          f"fired {fired}; steps {twice}; lost {lost_before} -> {lost()}")
    call("watch_clear", ref=refs[2])

    before = _stop_and_frame(call("status"))[1]
    planted = fault(refs[3], kills=1, loud=False)
    mark = len(log())
    added = add(refs[3])
    quiet = [seen(call("step"), refs[3]) for _ in range(4)]
    after = _stop_and_frame(call("status"))[1]
    fired = reader_fault_counts()[0]
    # SILENT means nothing between the echo and the next prompt: no death, no console error,
    # so only the prompt can have aged the line.
    tail = log()[mark:]
    echo = tail.find(f"tally-{tid(refs[3])}.txt".encode())
    gap = tail[echo:tail.find(transport.CONSOLE_PROMPT, echo)] if echo >= 0 else b""
    silent = echo >= 0 and transport.CONSOLE_PROMPT in tail[echo:] and b"[LUA ERROR]" not in gap \
        and b"error:" not in gap
    cell_if_planted(t[3], planted, added["mine"] and fired == 1 and silent and before is not None
          and before == after and quiet[-1] == (True, "tallied", 1)
          and all(q[1] != "install_lost" for q in quiet),
          f"fired {fired}; prompt-only {silent}; frame {before} -> {after}; steps {quiet}")
    call("watch_clear", ref=refs[3])

    lost_before = lost()
    planted = fault(refs[0], lag=3)
    added = add(refs[0])
    lagging = [seen(call("run_for", frames=1, seconds=5.0), refs[0]) for _ in range(6)]
    _fired, lagged, held = reader_fault_counts()
    detail = (f"held {held} frames over {lagged} hook runs; frame by frame {lagging}; "
              f"lost {lost_before} -> {lost()}")
    if planted and added["mine"] and held < 1:
        # A reader never held past a frame tests nothing about frames.
        blocked(t[4], f"the reader was not held past a frame, nothing to judge: {detail}")
    else:
        cell_if_planted(t[4], planted, added["mine"]
              and all(lg[2] == 0 and lg[1] != "install_lost" for lg in lagging)
              and lagging[-1] == (True, "tallied", 0) and isinstance(lost_before, int)
              and lost() == lost_before, detail)
    call("watch_clear", all=True)


def k_owned(labels: list[str]) -> tuple[int, ...]:
    """The indexes of `labels` in `K_CELLS`, which a board owns."""
    return tuple(K_CELLS.index(label) for label in labels)


K_BOARDS = (Board(_k_circus, k_owned(K_OWN + on_board("circus", K_RESEND + K_REMOVALS)),
                  free_boards_missing),
            Board(_k_m68k_dual, k_owned(on_board("m68k-dual", K_RESEND + K_REMOVALS)
                                       + [K_LEFTOVER]), m68k_dual_missing),
            Board(_k_circus_redeclare, k_owned([K_REDECLARE]), free_boards_missing))
boards_cover("K_BOARDS", K_CELLS, K_BOARDS)


@section("K", "a link where a state goes, a bool given as a count, installs queued, resent and "
         "lost, removals lost and never resent", K_CELLS)
def block_k_defects() -> None:
    run_boards(K_CELLS, K_BOARDS)


# The sections kept in a module of their own, registered here so that they run after every
# other, H last.
register_c16()
register_l()
register_m()
register_n()
register_o()
register_p()
register_q()
register_r()
register_s()
register_t()
register_u()
register_v()
register_w()
register_y()
register_h()
# THE FOCUS GATE'S VERDICT CLOSES THE RUN, after every section, H included.
register_x_verdict()


# ======================================================================== the run itself


def main() -> None:
    run_sections("LIVE MATRIX")


if __name__ == "__main__":
    main()
