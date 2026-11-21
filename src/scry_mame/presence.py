"""Presence on MAME, drawn by `lua/presence-drawer.lua`. A stopped machine repaints only on a
console command, so the adapter sends `REPAINT` once `held` is in the state file."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from scry_core import boundary, overlay, placement, presence

STATE_FILE = "presence.state"

#: The two sides `scry_core.presence.check_classified` holds against the registry.
DRIVING_TOOLS = frozenset({
    "run_to", "run_for", "screen_wait", "trace", "step", "resume", "stop", "series_capture",
    "input", "record",
    "audio_record", "reset", "state_write", "throttle", "drive", "perform", "lua", "debug",
    "cpu_focus", "write", "set_register"})
STILL_TOOLS = frozenset({
    "audio_compare", "breakpoint_at", "captures", "close", "comment_list", "comment_write",
    "cpu_info", "declaration_clear", "declaration_list", "disassemble", "find",
    "gfx_blit_source", "gfx_blits", "gfx_draft", "gfx_film", "gfx_load", "gfx_locate",
    "gfx_sweep", "gfx_view", "history", "image_compare", "log", "log_wait", "machine_map",
    "screen_map_find", "screen_map_write", "memdump", "palette", "palette_log", "perform_export",
    "read_block",
    "read_memory", "registers", "regpoint_add", "rom_check", "scan", "screen_signature",
    "screen_view", "snapshot", "start", "state_list", "status", "symbols_find", "watch_add",
    "window", "promote"})


#: Seconds between state-file reads while running.
REREAD_S = 0.05
#: Seconds a caption fades in and out: the emulator's animation, so not in `Look`.
CAPTION_FADE_S = 0.25
#: Seconds a scrolling caption rests at its head before it moves.
SCROLL_DWELL_S = 1.0
#: The layers MAME cannot draw and why: its inputs are port fields and it has no pointer.
LACKING: dict[overlay.Layer, str] = {
    "pointer": "MAME has no pointer to draw: its inputs are port fields, not a mouse"}
#: A console command that touches nothing and repaints a stopped machine once.
REPAINT = "print 0"

BROKEN_FILE = "presence.broken"


def drawer(scratch: Path, look: presence.Look = presence.LOOK) -> str:
    """The drawer's chunk for `scratch`."""
    # Imported here: the session state reads this module, and the loader reads the state.
    from scry_mame import lua_source
    return lua_source.render("presence-drawer", path=str(scratch / STATE_FILE),
                             broke=str(scratch / BROKEN_FILE),
                             rgb=lua_source.Code(f"0x{look.rgb:06X}"), edge=look.edge,
                             steps=look.steps, acting=look.acting_alpha, held=look.held_alpha,
                             fade=look.fade_s, reread=REREAD_S,
                             text_rgb=lua_source.Code(f"0x{look.caption_text_rgb:06X}"),
                             cap_alpha=look.caption_alpha,
                             key_rgb=lua_source.Code(f"0x{look.keycap_rgb:06X}"),
                             key_text_rgb=lua_source.Code(f"0x{look.keycap_text_rgb:06X}"),
                             key_alpha=look.keycap_alpha, cps=look.scroll_cps,
                             cap_fade=CAPTION_FADE_S, dwell=SCROLL_DWELL_S,
                             rec_rgb=lua_source.Code(f"0x{look.record_rgb:06X}"),
                             blink=look.record_blink_s,
                             placement=lua_source.Code(placement_lua()))


def placement_lua() -> str:
    """The placement rule as Lua, from `scry_core.placement`'s constants."""
    from scry_mame import lua_source
    return lua_source.render("presence-placement", divisor=placement.BAND_DIVISOR,
                             columns=placement.COLUMNS, rows=placement.ROWS,
                             margin=placement.MARGIN, consecutive=placement.CONSECUTIVE,
                             start=placement.START, sample_s=placement.SAMPLE_S)


def broken(scratch: Path) -> str:
    """Why the drawer stopped, or ""."""
    path = scratch / BROKEN_FILE
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip() or "no reason given"


def _ascii(text: str) -> str:
    """One printable ASCII line: the file is lines, and the drawer's font is not asked for more."""
    return "".join(c if " " <= c <= "~" else "?" for c in text)


def encode(state: presence.State, payload: presence.Payload) -> str:
    """The state file's text: `state`, then one `name=value` line each (`layers` as MAME can
    draw them, `rec` while something is recorded, the caption as `serial`, `rgb`, `caption`)
    and one `key` per key down."""
    drawn = [layer for layer in payload.layers if layer not in LACKING]
    lines = [state, f"paused={int(payload.paused)}", f"place={payload.place}",
             f"layers={','.join(drawn)}"]
    if payload.recording != "none":
        lines.append(f"rec={payload.recording}")
    if payload.caption is not None:
        lines += [f"serial={payload.caption.serial}", f"rgb={payload.caption.rgb:06X}",
                  f"caption={_ascii(payload.caption.text)}"]
    lines += [f"key={_ascii(name)}" for name in payload.keys]
    return "\n".join(lines) + "\n"


def overlay_reply(asked: overlay.Overlay) -> overlay.OverlayReply:
    """`start`'s and `status`'s `overlay`; `auto` stays `auto`, the drawer samples itself."""
    return overlay.reply(asked, {layer: why for layer, why in LACKING.items()
                                 if layer in asked.asked()}, asked.place)


class Listener(presence.Slot):
    """The boundary's listener, which also says whether the session holds the machine stopped:
    not while a driving call runs, and as it stands once any call has ended."""

    def __init__(self, current: Callable[[], presence.Presence | None],
                 stopped: Callable[[], bool]) -> None:
        super().__init__(current)
        self._current_presence = current
        self._stopped = stopped

    def began(self, call: boundary.Call) -> None:
        super().began(call)
        if not call.nested and call.tool in DRIVING_TOOLS and (
                p := self._current_presence()) is not None:
            p.paused(False)

    def ended(self, call: boundary.Call, outcome: boundary.Outcome) -> None:
        super().ended(call, outcome)
        if not call.nested and (p := self._current_presence()) is not None:
            p.paused(self._stopped())


#: The console of the adapter's session, or None when it is gone, broken, running or exited.
Repaintable = Callable[[Path], "Console | None"]


class Console(Protocol):

    def monitor_owed(self, command: str, timeout: float = ...) -> None: ...


class FileAdapter:
    """`scry_core.presence.Adapter` over the state file, replaced whole."""

    def __init__(self, scratch: Path, lock: boundary.ServerLock, session: Repaintable,
                 pending: Callable[[Path], int]) -> None:
        self._path = scratch / STATE_FILE
        self._lock, self._session, self._pending = lock, session, pending

    def show(self, state: presence.State, payload: presence.Payload) -> None:
        part = self._path.with_suffix(".part")
        part.write_text(encode(state, payload), encoding="ascii")
        os.replace(part, self._path)

    def wake(self) -> None:
        """A repaint waiting for the lock asks `still()` again."""
        self._lock.wake()

    def repaint(self, still: Callable[[], bool]) -> None:
        """Send `REPAINT` under the server lock while `still()` holds, never while a Lua line
        waits in the pipe: a console command makes MAME evaluate it there and then."""
        if not self._lock.acquire_while(still):
            return
        try:
            scratch = self._path.parent
            if still() and (ses := self._session(scratch)) is not None \
                    and not self._pending(scratch):
                ses.monitor_owed(REPAINT)
        finally:
            self._lock.release()
