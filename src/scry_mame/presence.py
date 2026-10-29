"""Presence on MAME: the edge `scry_core.presence` holds, drawn by MAME's own Lua.

Drawn on the render manager's UI container, which the window shows and the snapshot target and
`screen:pixels()` do not. A stopped machine repaints only on debugger console commands, so the
adapter sends `REPAINT` between calls once `held` is in the state file.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from scry_core import boundary, presence

#: The state file's name in the scratch.
STATE_FILE = "presence.state"

#: Calls that can move the guest or change what it holds, or cannot be told from one (`lua`,
#: `debug`, `focus`): presence is `acting`. Every other tool is in `STILL_TOOLS`; both are
#: written out so a new tool must be placed (the suite holds them against the registry).
DRIVING_TOOLS = frozenset({
    "run_to", "run_for", "trace", "step", "resume", "stop", "series_capture", "input", "record",
    "audio_record", "reset", "state_write", "throttle", "drive", "perform", "lua", "debug",
    "focus", "write", "set_register"})
STILL_TOOLS = frozenset({
    "audio_compare", "breakpoint_at", "captures", "close", "comment_list", "comment_write",
    "cpu_info", "declaration_clear", "declaration_list", "disassemble", "find",
    "gfx_blit_source", "gfx_blits", "gfx_draft", "gfx_film", "gfx_load", "gfx_locate",
    "gfx_sweep", "gfx_view", "history", "image_compare", "log", "log_wait", "machine_map",
    "screen_map_find", "screen_map_write", "memdump", "palette", "palette_log", "perform_export",
    "read_block",
    "read_memory", "registers", "regpoint_add", "rom_check", "scan", "screen_signature",
    "screen_view", "snapshot", "start", "state_list", "status", "symbols_find", "watch_add"})

# A drawer that raises writes why beside the state file, where `status` reads it.
DRAWER = """-- Written by the mame MCP server for ONE session: the presence edge.
local path, broke = %(path)s, %(broke)s
local function stopped(err)
  local f = io.open(broke, "w")
  if f then f:write(tostring(err)); f:close() end
  manager.machine:logerror("MAME_MCP_PRESENCE stopped: " .. tostring(err) .. "\\n")
end
local set_up, why = pcall(function()
  local RGB, EDGE, STEPS = %(rgb)d, %(edge)r, %(steps)d
  local ACTING, HELD, FADE, REREAD = %(acting)r, %(held)r, %(fade)r, %(reread)r
  local now, since, read_at, broken = "off", -1e9, -1e9, false
  -- The repaints drawn in each state: what the live cells read back to see it drawn.
  _G.scry_presence_frames = {held = 0, acting = 0}
  emu.register_frame_done(function()
    if broken then return end
    local ok, err = pcall(function()
      local t = emu.osd_ticks() / emu.osd_ticks_per_second()
      local running = manager.machine.debugger == nil
        or manager.machine.debugger.execution_state == "run"
      if not running or t - read_at >= REREAD then
        read_at = t
        local f = io.open(path, "r")
        local was = now
        now = "off"
        if f then now = f:read("l") or "off"; f:close() end
        if now ~= was then since = t end
      end
      if now ~= "held" and now ~= "acting" then return end
      local alpha = HELD
      if now == "acting" then alpha = ACTING
      elseif running and FADE > 0 and t - since < FADE then
        alpha = HELD + (ACTING - HELD) * (1 - (t - since) / FADE)
      end
      local c = manager.machine.render.ui_container
      local tg = manager.machine.render.ui_target
      local side = math.min(tg.width, tg.height) * EDGE
      local ex, ey = side / tg.width, side / tg.height
      for i = 0, STEPS - 1 do
        local a = math.floor(255 * alpha * (1 - i / STEPS) + 0.5)
        local col = (a << 24) | RGB
        local x0, y0 = ex * i / STEPS, ey * i / STEPS
        local x1, y1 = ex * (i + 1) / STEPS, ey * (i + 1) / STEPS
        c:draw_box(x0, y0, 1 - x0, y1, 0, col)
        c:draw_box(x0, 1 - y1, 1 - x0, 1 - y0, 0, col)
        c:draw_box(x0, y1, x1, 1 - y1, 0, col)
        c:draw_box(1 - x1, y1, 1 - x0, 1 - y1, 0, col)
      end
      _G.scry_presence_frames[now] = _G.scry_presence_frames[now] + 1
    end)
    if not ok then
      broken = true
      stopped(err)
    end
  end)
end)
if not set_up then stopped(why) end
"""

#: Seconds between state-file reads while running.
REREAD_S = 0.05
#: A console command that touches nothing and repaints a stopped machine once.
REPAINT = "print 0"

BROKEN_FILE = "presence.broken"


def drawer(scratch: Path, look: presence.Look = presence.LOOK) -> str:
    """The drawer's chunk for a session whose scratch is `scratch`."""
    # Imported here: the session state reads this module, and the transport reads the state.
    from scry_mame import transport
    return DRAWER % {"path": transport.lua_string(str(scratch / STATE_FILE)),
                     "broke": transport.lua_string(str(scratch / BROKEN_FILE)), "rgb": look.rgb,
                     "edge": look.edge, "steps": look.steps, "acting": look.acting_alpha,
                     "held": look.held_alpha, "fade": look.fade_s, "reread": REREAD_S}


def broken(scratch: Path) -> str:
    """Why the session's drawer stopped, or "" while it draws."""
    path = scratch / BROKEN_FILE
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip() or "no reason given"


#: The console of the adapter's session, or None when it is gone, broken, running or exited.
Repaintable = Callable[[Path], "Console | None"]


class Console(Protocol):
    """The console the repaint sends through."""

    def monitor_owed(self, command: str, timeout: float = ...) -> None: ...


class FileAdapter:
    """`scry_core.presence.Adapter` over the state file, replaced whole (no half reads)."""

    def __init__(self, scratch: Path, lock: boundary.ServerLock, session: Repaintable,
                 pending: Callable[[Path], int]) -> None:
        self._path = scratch / STATE_FILE
        self._lock, self._session, self._pending = lock, session, pending

    def show(self, state: presence.State) -> None:
        part = self._path.with_suffix(".part")
        part.write_text(state + "\n", encoding="ascii")
        os.replace(part, self._path)

    def wake(self) -> None:
        """Make a repaint waiting for the lock ask `still()` again."""
        self._lock.wake()

    def repaint(self, still: Callable[[], bool]) -> None:
        """Send `REPAINT` under the server lock while `still()` holds.

        Never while a Lua line waits in the console's pipe: a console command would make MAME
        evaluate it there and then.
        """
        if not self._lock.acquire_while(still):
            return
        try:
            scratch = self._path.parent
            if still() and (ses := self._session(scratch)) is not None \
                    and not self._pending(scratch):
                ses.monitor_owed(REPAINT)
        finally:
            self._lock.release()
