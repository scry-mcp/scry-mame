"""Section A of the live matrix: every tool in every machine state, and per cpu."""


import functools
import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bench_boards import (
    MANIFEST,
    REFERENCE_ROM,
    SUB_ROM,
    SUB_SYMBOLS,
    SYMBOLS,
    m68k_dual_missing,
)
from gfx_layouts import BYTES_8X8
from live_harness import (
    BOOT,
    Blocked,
    blocked,
    boot,
    call,
    cell,
    ensure_closed,
    folded,
    fresh,
    fresh_state,
    ok,
    refused,
    said,
    section,
    session_is,
    unavailable_why,
)
from scry_core.host_program import absolute

from scry_mame import cpus  # isort: skip
from scry_mame import film as mfilm  # isort: skip
from scry_mame import savestates as msavestates  # isort: skip
from scry_mame import server as s  # isort: skip
from scry_mame.state import STATE  # isort: skip

STATES = ("none", "stopped", "running", "closed")
_saved: list[str] = []


def load_judged(r: dict[str, Any]) -> bool:
    """A load verified, or unverifiable only because nothing ran since its save."""
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
    """`args`, after preparing a stopped machine for the blit tools; otherwise untouched."""
    here = s.status()
    if not here.get("session", {}).get("alive") or here.get("session", {}).get("running"):
        return args
    if STATE.manifest is None:
        call("gfx_load", path=MANIFEST)
    if not any(owner[0] == BLITTER for owner in STATE.tallies):
        call("watch_add", ref=BLITTER, mode="capture", length=32, trigger=BLIT_TRIGGER)
        # a boot's first blits come a few frames in
        call("run_for", frames=8, seconds=10.0)
    return args


def _manifest_ready(args: dict[str, Any]) -> dict[str, Any]:
    """`args`, with the manifest loaded first on a live machine (`gfx_load` answers running too)."""
    if s.status().get("session", {}).get("alive") and STATE.manifest is None:
        call("gfx_load", path=MANIFEST)
    return args


#: The blitter's strobe and the value that fires a blit.
FILM: dict[str, Any] = {"trigger": BLIT_TRIGGER, "length": 2, "value": 0xFFFF, "keep": 2,
                        "frames": 4}


def _series_ahead() -> dict[str, Any]:
    """A one-frame series two frames ahead of a stopped machine; any frame otherwise."""
    here = s.status()
    if not here.get("session", {}).get("alive") or here.get("session", {}).get("running"):
        return {"at_frames": [1], "seconds": 10.0}
    now = s.screen_signature().get("frame_screen", 0)
    return {"at_frames": [now + 2], "seconds": 10.0}


#: A path no host has: absolute on this one, so only its being absent is judged.
_absent = functools.partial(absolute, "nonexistent")

#: Media tools read files, never the machine: in every state a missing file is refused by name.
MEDIA_ABSENT: dict[str, dict[str, Any]] = {
    "image_compare image": {"a": _absent("a.png"), "b": _absent("b.png")},
    "image_compare series": {"a": _absent("a.json"), "b": _absent("b.json")},
    "image_compare region": {"manifest": _absent("m.json")},
    "image_compare golden": {"manifest": _absent("m.json"),
                             "checksums": _absent("g.sha256")},
    "audio_compare measure": {"path": _absent("s.wav")},
    "audio_compare diff": {"a": _absent("a.wav"), "b": _absent("b.wav")},
}


def _film_ready(args: dict[str, Any]) -> dict[str, Any]:
    """`args`, with a film armed first on a live machine (arming needs a stop)."""
    here = s.status()
    if not here.get("session", {}).get("alive") or mfilm.held() is not None:
        return args
    if here.get("session", {}).get("running"):
        call("stop")
        call("gfx_film", **FILM)
        call("resume")
    else:
        call("gfx_film", **FILM)
    return args


#: What `comment_write` save wrote, so load reads the last one.
_comment_files: list[str] = []


def _comment_dest() -> str:
    _comment_files.append(fresh(".tsv"))
    return _comment_files[-1]


def _comment_source() -> str:
    return _comment_files[-1] if _comment_files else fresh(".tsv")



def _exported(r: dict[str, Any]) -> bool:
    """A `perform_export` reply whose file holds the steps it counts."""
    try:
        doc = json.loads(Path(str(r.get("path"))).read_text())
    except (OSError, ValueError):
        return False
    return (isinstance(r.get("steps"), int) and r["steps"] >= 1
            and isinstance(doc, dict) and len(doc.get("steps") or []) == r["steps"])

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
    "declaration_list breakpoint": dict,
    "declaration_clear breakpoint": lambda: {"all": True},
    "watch_add": lambda: {"ref": "0x203200", "mode": "show", "length": 2},
    "declaration_list watch": dict,
    "declaration_clear watch": lambda: {"all": True},
    # never true: a firing one would stop the machine under the running state's other probes
    "regpoint_add": lambda: {"condition": "pc==0xfffffffe"},
    "declaration_list regpoint": dict,
    "declaration_clear regpoint": lambda: {"all": True},
    # in this order: the save writes what the load reads back, the delete takes what add placed
    "comment_write add": lambda: {"ref": "irq_vblank", "text": "matrix A", "cpu": "maincpu"},
    "comment_list": dict,
    "comment_write save": lambda: {"dest": _comment_dest()},
    "comment_write load": lambda: {"path": _comment_source()},
    "comment_write delete": lambda: {"ref": "irq_vblank", "cpu": "maincpu"},
    "symbols_find": lambda: {"name": "irq_vblank"},
    "machine_map": dict,
    "cpu_info": dict, "window": dict,
    "read_memory": lambda: {"ref": "0x400", "length": 8},
    "read_block": lambda: {"tag": "maincpu", "offset": 0x400, "length": 8},
    "registers": dict,
    "disassemble": lambda: {"ref": "irq_vblank", "length": 8},
    "find": lambda: {"ref": "0x0", "length": 1024, "data_hex": "00"},
    "history": lambda: {"limit": 4},
    # opened, closed at once by `!` on the same stop, then cleared
    "scan start": lambda: {"ref": "0x200000", "length": 0x100},
    "scan filter": lambda: {"operator": "!"},
    "scan clear": dict,
    "cpu_focus": lambda: {"cpu": "maincpu"},
    "write": lambda: {"ref": "0x200000", "data_hex": "00"},
    "set_register": lambda: {"name": "D0", "value": 0},
    "reset": dict,
    "memdump": lambda: {"ref": "0x0", "length": 16, "dest": fresh(".bin")},
    "snapshot": dict,
    "screen_signature": dict,
    "screen_map_write load": lambda: {"path": _absent("m.screen-map.json")},
    "screen_map_write add": lambda: {"screen": "probe", "match": [[0, 0, 8, 8]]},
    "screen_map_find": dict,
    "screen_map_write save": lambda: {"dest": fresh(".screen-map.json"), "overwrite": True},
    "series_capture": _series_ahead,
    **{tool: functools.partial(dict, args) for tool, args in MEDIA_ABSENT.items()},
    "palette": dict,
    "screen_wait": lambda: {"palette": "black", "seconds": 0.2},
    "screen_view": lambda: {"mode": "histogram"},
    "gfx_view": lambda: {"layout": BYTES_8X8, "palette": "none", "tag": "maincpu", "count": 16},
    "gfx_locate": lambda: {"layouts": [BYTES_8X8], "patch": [0, 0, 8, 8], "tag": "maincpu",
                           "count": 64},
    "gfx_sweep": lambda: {"tag": "maincpu", "planes": [1], "count": 8},
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
    "perform_export": lambda: {"dest": fresh(".json")},
    "debug": lambda: {"command": "print pc"},
    "lua": lambda: {"script": "print(1)", "read_only": True},
    "input": lambda: {"port": ":P1", "field": "Coin 1", "frames": 1, "seconds": 10.0},
    "record": lambda: {"frames": 2, "seconds": 10.0},
    "audio_record": lambda: {"frames": 2, "seconds": 10.0},
    "throttle": lambda: {"on": False, "seconds": 5.0},
    "state_write save": lambda: {"name": _save_name()},
    "captures": dict,
    "state_list": dict,
    "state_write load": lambda: {"name": _state_to_load()},
}

#: What answers on a running machine; everything else but the lifecycle refuses `not_stopped`.
RUNNING_ANSWERS = {"status", "window", "log", "log_wait", "snapshot", "symbols_find", "throttle",
                   "breakpoint_at", "declaration_list breakpoint", "declaration_clear breakpoint",
                   "watch_add", "declaration_list watch", "declaration_clear watch", "regpoint_add",
                   "declaration_list regpoint", "declaration_clear regpoint", "comment_list",
                   "comment_write save", "state_list", "captures", "machine_map", "cpu_info",
                   "gfx_load", "palette_log", "gfx_film", "scan clear", "perform_export", "stop",
                   "close"}

#: Per tool, what a valid call's reply carries on a stopped machine.
STOPPED_SAYS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "status": lambda r: (r.get("session", {}).get("alive") is True
                         and r.get("session", {}).get("running") is False),
    "rom_check": lambda r: r.get("rom_check") == "OK",
    "run_to": lambda r: r.get("verdict") == "TARGET",
    "run_for": lambda r: r.get("verdict") == "ELAPSED",
    "trace": lambda r: (r.get("verdict") == "ELAPSED"
                        and (r.get("trace") or {}).get("addresses", 0) > 0),
    "step": lambda r: r.get("instructions_completed") == 1 and "regs" in r,
    "breakpoint_at": lambda r: r.get("armed") is True,
    "declaration_list breakpoint": lambda r: isinstance(r.get("breakpoints"), list),
    "declaration_clear breakpoint": lambda r: "declarations_cleared" in r,
    "watch_add": lambda r: r.get("state") == "evaluated"
    and r.get("reading", {}).get("available") is True and "value" in r["reading"],
    "declaration_list watch": lambda r: isinstance(r.get("watches"), list),
    "declaration_clear watch": lambda r: "declarations_cleared" in r,
    "regpoint_add": lambda r: r.get("armed") is True and r.get("cpu") == ":maincpu",
    "declaration_list regpoint": lambda r: isinstance(r.get("regpoints"), list),
    "declaration_clear regpoint": lambda r: "declarations_cleared" in r,
    "comment_write add": lambda r: (r.get("comment") or {}).get("state") == "armed"
    and r.get("cpu") == ":maincpu",
    "comment_list": lambda r: r.get("comments_total") == 1 and len(r.get("comments", [])) == 1,
    "comment_write save": lambda r: r.get("comments_total") == 1
    and Path(str(r.get("path"))).is_file(),
    "comment_write load": lambda r: r.get("parsed") == 1 and r.get("unchanged") == 1,
    "comment_write delete": lambda r: (r.get("deleted") or {}).get("ref") == "irq_vblank",
    "symbols_find": lambda r: r.get("symbols_total") == 1,
    "machine_map": lambda r: bool(r.get("cpus")),
    "cpu_info": lambda r: [(c["cpu"], c["visible"], "value" in (c["pc"] or {}))
                           for c in r.get("cpus", [])]
    == [(":maincpu", True, True), (":subcpu", False, True)],
    "read_memory": lambda r: len(str(r.get("hex"))) == 16,
    "read_block": lambda r: len(str(r.get("hex"))) == 16,
    "registers": lambda r: "PC" in r.get("regs", {}),
    "disassemble": lambda r: bool(r.get("lines")),
    "find": lambda r: isinstance(r.get("hits_total"), int),
    "history": lambda r: bool(r.get("lines")),
    "cpu_focus": lambda r: r.get("cpu") == ":maincpu" and r.get("machine_ran") is False,
    "write": lambda r: r.get("verified") is True,
    "set_register": lambda r: r.get("verified") is True,
    "reset": lambda r: r.get("kind") == "softreset",
    "memdump": lambda r: r.get("bytes") == 16,
    "snapshot": lambda r: r.get("bytes", 0) > 0,
    "screen_signature": lambda r: isinstance(r.get("signature"), str)
    and len(r["signature"]) == 16,
    "screen_map_write add": lambda r: r.get("kind") == "pixel"
    and len(str(r["match"][0]["signature"])) == 16,
    "screen_map_find": lambda r: r.get("matched") is True and r.get("screen") == "probe",
    "series_capture": lambda r: r.get("count") == 1 and r.get("kept_after_close") is False,
    "palette": lambda r: r.get("entries", 0) > 0 and r.get("image", {}).get("inline") is True,
    "screen_wait": lambda r: r.get("verdict") == "TIMEOUT"
    and r.get("predicate") == "palette" and isinstance(r.get("polls"), int),
    "screen_view": lambda r: sum(n for _, n in r.get("histogram", []))
    == r.get("width", 0) * r.get("height", 0) > 0,
    "gfx_view": lambda r: r.get("count") == 16 and r.get("real_colors") is False,
    "gfx_locate": lambda r: r.get("candidates", [{}])[0].get("tiles_searched") == [0, 64],
    "gfx_sweep": lambda r: r.get("sweep", 0) >= 1 and r.get("image", {}).get("inline") is True
    and all(c["shown"] == 8 for c in r.get("candidates", [])),
    "gfx_draft": lambda r: Path(r.get("manifest", {}).get("path", "")).is_file()
    and Path(r.get("report", {}).get("path", "")).is_file(),
    "gfx_load": lambda r: r.get("loaded") is True and "blit" in r.get("commands", {}),
    # each state starts with no log armed, so `arm=True` arms one
    "palette_log": lambda r: r.get("palette_port") == "ramdac" and r.get("armed_now") is True,
    "gfx_film": lambda r: (r.get("film") or {}).get("trigger") == BLIT_TRIGGER
    and isinstance(r.get("installed"), bool) and isinstance(r.get("pending"), bool),
    "gfx_blits": lambda r: r.get("blits_in_frame", 0) > 0 and r.get("frame_complete") is True,
    "gfx_blit_source": lambda r: r.get("index") == 0 and r.get("image", {}).get("indexed") is True,
    "log": lambda r: isinstance(r.get("lines_total"), int),
    "drive": lambda r: r.get("act", {}).get("steps_completed") == 1,
    "perform": lambda r: r.get("steps_completed") == 1,
    "perform_export": _exported,
    "debug": lambda r: isinstance(r.get("output"), str),
    "lua": lambda r: r.get("output") == "1\n",
    "input": lambda r: r.get("released") is True,
    "record": lambda r: r.get("avi_frames") == 2,
    "audio_record": lambda r: (r.get("samples") or 0) > 0
    and r.get("frame_end", 0) - r.get("frame_begin", 0) + 1 == 2,
    "state_write save": lambda r: Path(str(r.get("path"))).is_file(),
    "captures": lambda r: isinstance(r.get("captures"), list),
    "state_list": lambda r: isinstance(r.get("states"), list),
    "state_write load": load_judged,
    "throttle": lambda r: r.get("pending") is True and str(r.get("tag", "")).startswith(
        "MAME_MCP_THROTTLE#"),
    "stop": lambda r: r.get("interrupted") is False,
    "resume": lambda r: "verdict" not in r and "halted" not in r,
    "close": lambda r: r.get("closed") is True,
    "scan start": lambda r: r.get("hits_total") == 0x100 and r.get("space") == "program",
    "scan filter": lambda r: r.get("closed") is True and r.get("hits_total") == 0,
    "scan clear": lambda r: r.get("cleared") in (True, False),
}

def _says_running(r: dict[str, Any]) -> bool:
    """A reader on a running machine says so in its `session` block alone."""
    return r.get("session", {}).get("running") is True and "running" not in r


RUNNING_SAYS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "scan clear": lambda r: r.get("cleared") in (True, False),
    "status": lambda r: (r.get("session", {}).get("running") is True
                         and "pc" in (r.get("last_stop") or {})
                         and (r.get("pc") or {}).get("available") is False),
    "log": lambda r: isinstance(r.get("lines_total"), int),
    "log_wait": lambda r: "line" in r,
    "snapshot": lambda r: r.get("bytes", 0) > 0,
    "symbols_find": lambda r: r.get("symbols_total") == 1
    and all(x.get("memory") == "unknown" for x in r.get("symbols", [])),
    "throttle": lambda r: r.get("pending") is False and isinstance(r.get("frame"), int),
    "breakpoint_at": lambda r: r.get("armed") is True and r.get("while_running") is True,
    "declaration_list breakpoint": lambda r: _says_running(r) and "last_stop" in r,
    "declaration_clear breakpoint": lambda r: r.get("while_running") is True,
    "watch_add": lambda r: r.get("state") == "evaluated" and "reading" not in r,
    "declaration_list watch": lambda r: _says_running(r) and "last_stop" in r,
    "declaration_clear watch": lambda r: r.get("while_running") is True,
    "regpoint_add": lambda r: r.get("armed") is True and r.get("while_running") is True,
    "declaration_list regpoint": lambda r: _says_running(r) and "last_stop" in r,
    "declaration_clear regpoint": lambda r: r.get("while_running") is True,
    "comment_list": lambda r: _says_running(r) and "last_stop" in r,
    "comment_write save": lambda r: isinstance(r.get("comments_total"), int)
    and Path(str(r.get("path"))).is_file(),
    "state_list": lambda r: isinstance(r.get("states"), list),
    "captures": lambda r: isinstance(r.get("captures"), list),
    "machine_map": lambda r: bool(r.get("cpus")),
    "cpu_info": lambda r: _says_running(r) and len(r.get("cpus", [])) == 2
    and all(c["pc"].get("available") is False for c in r["cpus"]),
    "gfx_load": lambda r: r.get("loaded") is True,
    "palette_log": lambda r: r.get("palette_port") == "ramdac" and r.get("armed_now") is True,
    "gfx_film": lambda r: (r.get("film") or {}).get("trigger") == BLIT_TRIGGER
    and isinstance(r.get("installed"), bool) and isinstance(r.get("pending"), bool),
    "stop": lambda r: r.get("interrupted") is True and isinstance(r.get("frame"), int),
    "close": lambda r: r.get("closed") is True,
}


def judge_a(tool: str, state: str, r: dict[str, Any]) -> tuple[bool, str]:
    """A tool's reply in a state against its contract, and the session block against the machine."""
    if tool in MEDIA_ABSENT:
        good = refused(r, "bad_argument") and "no file at" in str(r.get("message"))
        agrees = session_is(r, state not in ("none", "closed"), state == "running")
    elif tool in ("screen_map_write load", "screen_map_write save"):
        # a load of a missing file is refused by name; a save needs a map first
        good = (refused(r, "bad_argument") and "no map file" in str(r.get("message"))
                if tool == "screen_map_write load" else
                refused(r, "needs_call") if state == "none" else
                ok(r) and Path(str(r.get("path"))).is_file())
        agrees = session_is(r, state not in ("none", "closed"), state == "running")
    elif state in ("none", "closed"):
        if tool == "status":
            good = ok(r) and r.get("session", {}).get("alive") is False
        elif tool == "close":
            good = ok(r) and r.get("closed") is False and r.get("ended_by") == "none"
        elif tool == "start":
            good = ok(r) and r.get("rom_check") == "OK"
        elif tool == "perform_export":
            # after `close` the closed session's recording still exports
            good = (refused(r, "no_recording") if state == "none"
                    else ok(r) and _exported(r))
        else:
            good = refused(r, "no_session")
        agrees = session_is(r, tool == "start", False)
    elif state == "stopped":
        if tool == "start":
            good = refused(r, "session_live")
        elif tool == "log_wait":
            # `.` matches a line the log already holds, so it answers at once
            good = ok(r) and r.get("already") is True
        elif tool == "window":
            # the matrix starts unwatched: the server placed no window and proves none
            good = refused(r, "no_channel") and "shared=true" in str(r.get("message"))
        else:
            good = ok(r) and STOPPED_SAYS[tool](r)
        # `close` reports the session after it, which is over
        agrees = (session_is(r, False, False) if tool == "close"
                  else session_is(r, True, tool == "resume"))
    else:
        if tool == "start":
            good = refused(r, "session_live")
        elif tool == "perform_export":
            good = refused(r, "no_recording") and "cut at call 1" in str(r.get("message"))
        elif tool == "window":
            good = refused(r, "no_channel") and "shared=true" in str(r.get("message"))
        elif tool in RUNNING_ANSWERS:
            good = ok(r) and RUNNING_SAYS[tool](r)
        elif tool in ("perform", "drive"):
            # the wait ran out: an answer, with the step never sent
            verdict = r.get("verdict") if tool == "perform" else r.get("act", {}).get("verdict")
            good = ok(r) and verdict == "TIMEOUT"
        else:
            good = (refused(r, "not_stopped") and isinstance(r.get("last_stop"), dict)
                    and "answers_while_running" in r)
        agrees = (session_is(r, False, False) if tool == "close"
                  else session_is(r, True, tool != "stop"))
    detail = said(r) if good else f"{r.get('code', '')} {said(r)}"
    if good and not agrees:
        detail = f"session block disagrees: {r.get('session')}"
    return good and agrees, detail


def _a(state: str, tool: str) -> str:
    return f"{tool} @ {state}"


#: The call that puts the machine back in the state under test after a cell that moved it out.
RESTORE = {("stopped", "resume"): "stop", ("stopped", "run_to"): "declaration_clear breakpoint",
           ("stopped", "gfx_blit_source"): "declaration_clear watch", ("running", "stop"): "resume"}
#: The clears a restore names take every declaration, which a clear only does when asked.
CLEARS = ("declaration_clear breakpoint", "declaration_clear watch", "declaration_clear regpoint")


def restore(tool: str) -> dict[str, Any]:
    """A restoring call; a clear takes every declaration of its kind."""
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


# Calls that leave the machine as found go first, then those that move it, transitions last.
STOPPED_ORDER = [
    "status", "window", "rom_check", "machine_map", "cpu_info", "symbols_find", "read_memory",
    "read_block", "registers", "disassemble", "find", "history", "scan start", "scan filter",
    "scan clear",
    "cpu_focus", "log", "snapshot", "captures", "state_list", "breakpoint_at",
    "declaration_list breakpoint", "declaration_clear breakpoint", "watch_add",
    "declaration_list watch", "declaration_clear watch", "regpoint_add",
    "declaration_list regpoint", "declaration_clear regpoint", "comment_write add", "comment_list",
    "comment_write save", "comment_write load", "comment_write delete", "debug", "lua",
    "screen_signature", "screen_map_write add", "screen_map_find", "screen_map_write save",
    "screen_map_write load",
    "image_compare image", "image_compare series", "image_compare region", "image_compare golden",
    "audio_compare measure", "audio_compare diff", "palette", "screen_view", "gfx_view",
    "gfx_locate", "gfx_sweep", "gfx_draft", "gfx_load", "gfx_blits", "gfx_blit_source",
    "palette_log", "gfx_film", "write", "set_register", "run_to", "run_for", "screen_wait",
    "series_capture",
    "trace", "step", "input", "record", "audio_record", "memdump", "state_write save",
    "state_write load", "reset", "throttle", "perform", "drive", "perform_export", "log_wait",
    "stop", "start", "resume", "close"
]
RUNNING_ORDER = (
    [t for t in STOPPED_ORDER if t not in RUNNING_ANSWERS and t not in ("start", "resume")]
    + ["status", "window", "log", "log_wait", "snapshot", "symbols_find", "throttle",
       "breakpoint_at",
       "declaration_list breakpoint", "declaration_clear breakpoint", "watch_add",
       "declaration_list watch", "declaration_clear watch",
       "regpoint_add", "declaration_list regpoint", "declaration_clear regpoint", "comment_list",
       "comment_write save",
       "state_list", "captures", "machine_map", "cpu_info", "gfx_load", "palette_log",
       "gfx_film", "scan clear", "perform_export", "resume",
       "start",
       "stop", "close"])
# `start` last is the way out of no-session and closed.
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
    probed = {folded(p, {})[0] for p in PROBES}
    missing = sorted(set(registered) - probed)
    extra = sorted(probed - set(registered))
    cell(SURFACE, not missing and not extra and set(PROBES) == set(STOPPED_ORDER)
         and len(STOPPED_ORDER) == len(set(STOPPED_ORDER)),
         f"{len(registered)} tools; unprobed {missing}, unknown {extra}")
    # a failed boot would leave the next states judging a machine that is not there
    if why := m68k_dual_missing():
        raise Blocked(why)
    ensure_closed()
    run_state("none", ABSENT_ORDER)
    run_state("stopped", STOPPED_ORDER)
    run_state("closed", ABSENT_ORDER)
    call("resume")
    run_state("running", RUNNING_ORDER)


# Every tool taking `cpu` is probed naming each of m68k-dual's two 68000s, with `:maincpu`
# visible throughout; `:subcpu` is the cpu that is not the visible one. Releasing the machine
# makes the cpu it last stopped on visible again, so the last stop before the running half is
# on the main cpu.

Judge = Callable[[dict[str, Any]], bool]
MAIN, SUB = ":maincpu", ":subcpu"


def _by_cpu(tag: str) -> dict[str, Callable[[], dict[str, Any]]]:
    """TOOL -> a valid call naming `tag`; the addresses are ones that cpu's program has.

    On the sub cpu `542` (idle loop) is the control and `snd_reset`, run once at release, is cold.
    """
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
        "declaration_list breakpoint": lambda: {"cpu": tag},
        "declaration_clear breakpoint": lambda: {"all": True, "cpu": tag},
        "watch_add": lambda: {"ref": "0x0", "mode": "show", "length": 2, "cpu": tag},
        "declaration_list watch": lambda: {"cpu": tag},
        "declaration_clear watch": lambda: {"all": True, "cpu": tag},
        "regpoint_add": lambda: {"condition": "pc==0xfffffffe", "cpu": tag},
        "declaration_list regpoint": lambda: {"cpu": tag},
        "declaration_clear regpoint": lambda: {"all": True, "cpu": tag},
        "comment_write add": lambda: {"ref": "0x400", "text": f"by cpu {tag}", "cpu": tag},
        "comment_list": lambda: {"cpu": tag},
        "comment_write delete": lambda: {"ref": "0x400", "cpu": tag},
        "write": lambda: {"ref": "0x200000", "data_hex": "00", "cpu": tag},
        "set_register": lambda: {"name": "D0", "value": 0, "cpu": tag},
        "memdump": lambda: {"ref": "0x0", "length": 16, "dest": fresh(".bin"), "cpu": tag},
        "scan start": lambda: {"ref": "0x200000", "length": 0x100, "cpu": tag},
        "perform": lambda: {"steps": [{"op": "registers", "cpu": tag}], "settle_seconds": 2.0},
        "drive": lambda: {"act": [{"op": "registers", "cpu": tag}], "settle_seconds": 2.0},
        "run_to": lambda: ({"ref": "irq_vblank", "control": "0x4a0", "seconds": 10.0, "cpu": tag}
                           if main else {"ref": "snd_reset", "control": "0x542", "seconds": 1.0,
                                         "cpu": tag}),
        "step": lambda: {"count": 1, "cpu": tag},
        "trace": lambda: {"frames": 1, "seconds": 10.0, "cpu": tag},
        "cpu_focus": lambda: {"cpu": tag},
        "gfx_view": lambda: {"layout": BYTES_8X8, "palette": "none", "ref": "0x400", "count": 2,
                             "cpu": tag},
        "gfx_locate": lambda: {"layouts": [BYTES_8X8], "patch": [0, 0, 8, 8], "ref": "0x400",
                               "count": 4, "cpu": tag},
        "gfx_sweep": lambda: {"ref": "0x400", "count": 2, "planes": [1], "cpu": tag},
        # a RAM word both programs map
        "gfx_film": lambda: {"trigger": "0x200000", "cpu": tag, "keep": 1, "frames": 2},
    }


def _refused_for_focus(r: dict[str, Any]) -> bool:
    return refused(r, "needs_call") and "focus" in str(r.get("message"))


def _names_it(tag: str) -> Judge:
    return lambda r: r.get("cpu") == tag


def _by_cpu_says(tag: str) -> dict[str, Judge]:
    """Per tool, what a valid call's reply says on a stopped machine naming `tag`."""
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
        "declaration_list breakpoint": lambda r: [(b.get("ref"), b.get("cpu"))
                                      for b in r.get("breakpoints", [])]
        == [("exception_handler" if tag == MAIN else "0x8", tag)],
        "declaration_clear breakpoint": lambda r: r.get("declarations_cleared") == 1,
        "watch_add": lambda r: r.get("state") == "evaluated" and names(r)
        and r.get("reading", {}).get("available") is True,
        "declaration_list watch": lambda r: [(w.get("ref"), w.get("cpu")) for w in r.get("watches",
                                                                                         [])]
        == [("0x0", tag)],
        "declaration_clear watch": lambda r: r.get("declarations_cleared") == 1,
        # `rpset` names no cpu: another than the visible one is refused naming `focus`
        "regpoint_add": (lambda r: r.get("armed") is True and names(r)) if tag == MAIN
        else _refused_for_focus,
        "declaration_list regpoint": lambda r: isinstance(r.get("regpoints"), list) and names(r),
        "declaration_clear regpoint": lambda r: "declarations_cleared" in r,
        # `comadd` names no cpu: the server makes it visible, then puts the visible one back
        "comment_write add": lambda r: (r.get("comment") or {}).get("state") == "armed"
        and names(r),
        "comment_list": lambda r: [c.get("cpu") for c in r.get("comments", [])] == [tag]
        and names(r),
        "comment_write delete": lambda r: (r.get("deleted") or {}).get("cpu") == tag and names(r),
        "write": lambda r: r.get("verified") is True and names(r),
        "set_register": lambda r: r.get("verified") is True and names(r),
        "memdump": lambda r: r.get("bytes") == 16 and names(r),
        "scan start": lambda r: r.get("hits_total") == 0x100 and names(r),
        "perform": lambda r: r.get("steps_completed") == 1 and r["ran"][0].get("cpu") == tag
        and r.get("visible_cpu") == MAIN and r.get("visible_cpu_kept", {}).get("after") == MAIN,
        "drive": lambda r: r.get("act", {}).get("steps_completed") == 1
        and r["act"]["ran"][0].get("cpu") == tag,
        # the sub's target is cold: only its control proves the run
        "run_to": (lambda r: r.get("verdict") == "TARGET" and names(r)) if tag == MAIN
        else (lambda r: r.get("verdict") == "TIMEOUT" and r.get("control_hits", 0) > 0
              and {c["cpu"] for c in r.get("controls", [])} == {SUB}),
        "step": lambda r: r.get("instructions_completed") == 1 and names(r),
        # not `names`: the top-level `cpu` is the survey's; the traced cpu is the trace block's
        "trace": lambda r: (r.get("verdict") == "ELAPSED"
                            and (r.get("trace") or {}).get("cpu") == tag
                            and r["trace"].get("addresses", 0) > 0),
        "cpu_focus": lambda r: names(r) and r.get("machine_ran") is False,
        "gfx_view": lambda r: r.get("kind") == "space" and r.get("count") == 2
        and r.get("addr_cpu") == tag,
        "gfx_locate": lambda r: r.get("kind") == "space" and r.get("addr_cpu") == tag
        and r.get("candidates", [{}])[0].get("tiles_searched") == [0, 4],
        "gfx_sweep": lambda r: r.get("kind") == "space" and r.get("addr_cpu") == tag
        and r.get("candidates", [{}])[0].get("shown") == 2,
        "gfx_film": lambda r: r.get("armed_now") is True and r["film"]["cpu"] == tag,
    }


BY_CPU_RUNNING: dict[str, Judge] = {
    "machine_map": lambda r: len(r.get("cpus", [])) == 1,
    "cpu_info": lambda r: len(r.get("cpus", [])) == 1
    and r["cpus"][0]["pc"].get("available") is False,
    "symbols_find": lambda r: r.get("symbols_total") == 1,
    **{t: RUNNING_SAYS[t] for t in ("breakpoint_at", "declaration_list breakpoint",
                                    "declaration_clear breakpoint",
                                    "watch_add", "declaration_list watch",
                                    "declaration_clear watch",
                                    "declaration_list regpoint", "declaration_clear regpoint")},
    # read with no machine: the stopped half deleted what it added
    "comment_list": lambda r: _says_running(r) and r.get("comments") == [],
}
#: The registerpoint call must name the visible cpu, running or stopped.
BY_CPU_VISIBLE_ONLY: dict[str, Judge] = {"regpoint_add": RUNNING_SAYS["regpoint_add"]}

#: MAME moves the visible cpu for these two.
MOVES_VISIBLE = ("step", "cpu_focus")
BY_CPU_ORDER = [
    "machine_map", "cpu_info", "symbols_find", "rom_check", "read_memory", "read_block",
    "registers", "disassemble", "find", "history", "breakpoint_at", "declaration_list breakpoint",
    "declaration_clear breakpoint", "watch_add", "declaration_list watch",
                "declaration_clear watch", "regpoint_add", "declaration_list regpoint",
    "declaration_clear regpoint", "comment_write add", "comment_list", "comment_write delete",
                "write", "set_register",
    "memdump", "scan start", "gfx_view", "gfx_locate",
    # `step` stays last before `focus`: RELEASE_RESETS needs the sub's own stop
    "gfx_sweep", "gfx_film", "perform", "drive", "run_to", "trace", "step", "cpu_focus",
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
    probed = sorted({folded(t, {})[0] for t in BY_CPU_ORDER if t not in ("perform", "drive")})
    cell(BY_CPU_SURFACE, taking == probed, f"take cpu {taking}; probed {probed}")
    for tag in (MAIN, SUB):
        ensure_closed()
        boot(symbols={MAIN: SYMBOLS, SUB: SUB_SYMBOLS})
        # the sub cpu leaves reset when the main one releases it
        call("run_for", frames=60, seconds=10.0)
        probes, says = _by_cpu(tag), _by_cpu_says(tag)
        for tool in BY_CPU_ORDER:
            r = call(tool, **probes[tool]())
            good = says[tool](r) and (ok(r) or (tool in BY_CPU_VISIBLE_ONLY and tag == SUB))
            if tool in MOVES_VISIBLE:
                call("cpu_focus", cpu="maincpu")
            kept = cpus.visible_cpu(STATE.ses) == MAIN if STATE.ses is not None else False
            cell(_on(tag, "stopped", tool), good and kept and session_is(r, True, False),
                 said(r) if kept else f"the visible cpu moved: {said(r)}")
            if tool == "run_to":
                call("declaration_clear", kind="breakpoint", all=True)
            if tool == "scan start":
                call("scan", method="clear")
        if tag == SUB:
            # the last stop was the sub's: the release makes it visible again
            call("cpu_focus", cpu="maincpu")
            call("resume")
            r = call("regpoint_add", condition="pc==0xfffffffe")
            cell(RELEASE_RESETS, ok(r) and r.get("cpu") == SUB, said(r))
            call("stop")
            call("declaration_clear", kind="regpoint", all=True)
        # the last stop on the main cpu keeps it visible while running
        call("run_for", frames=1, seconds=10.0)
        call("resume")
        for tool in BY_CPU_RUNNING_ORDER:
            r = call(tool, **probes[tool]())
            if tool in BY_CPU_RUNNING:
                good = ok(r) and BY_CPU_RUNNING[tool](r)
            elif tool in BY_CPU_VISIBLE_ONLY:
                good = (ok(r) and BY_CPU_VISIBLE_ONLY[tool](r)) if tag == MAIN else (
                    _refused_for_focus(r))
            else:
                good = (refused(r, "not_stopped") and isinstance(r.get("last_stop"), dict)
                        and "answers_while_running" in r)
            cell(_on(tag, "running", tool), good and session_is(r, True, True), said(r))
        call("stop")
        ensure_closed()
