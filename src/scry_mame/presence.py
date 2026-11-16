"""Presence on MAME, drawn by `lua/presence-drawer.lua`. A stopped machine repaints only on a
console command, so the adapter sends `REPAINT` once `held` is in the state file."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from scry_core import boundary, presence

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
                             fade=look.fade_s, reread=REREAD_S)


def broken(scratch: Path) -> str:
    """Why the drawer stopped, or ""."""
    path = scratch / BROKEN_FILE
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip() or "no reason given"


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

    def show(self, state: presence.State) -> None:
        part = self._path.with_suffix(".part")
        part.write_text(state + "\n", encoding="ascii")
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
