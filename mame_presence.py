"""PRESENCE ON MAME: the edge `scry_core.presence` holds, drawn by MAME's own Lua over the window.

WHERE IT IS DRAWN decides whether it can reach the evidence. The drawer draws on the render
manager's UI container (`manager.machine.render.ui_container`), which the window's target shows
and the snapshot target, the one `snapshot` and `record` render through, does not; the screen
views read `screen:pixels()`, the screen's own bitmap, which no container reaches. A screen's
container would be the wrong one: it is composed into the snapshot and the recording.

WHEN IT IS DRAWN is MAME's frame-done hook (`emu.register_frame_done`), the one the UI's own
overlays use, which runs at every repaint: every frame while the machine runs, and while the
debugger holds it at the stop and at each command sent through the debugger's console (a
register or memory read through the stub does not repaint). So once a call that ends stopped is
over and `held` is in the file, the adapter sends one console command of its own (`REPAINT`),
between calls, and the window goes dim as it would on a machine that repaints by itself.

THE STATE travels in a file of the session's scratch, one word, replaced whole (`os.replace`),
and read by the hook at each repaint: no console line, so nothing queues behind the debugger,
and the Lua channel stays the transport's alone. The look is substituted into the drawer once,
at `start`, from `scry_core.presence.LOOK`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from scry_core import boundary, presence

#: The state file's name in the scratch.
STATE_FILE = "presence.state"

#: The calls during which the session drives the machine, so presence is `acting`: a call that
#: can move the guest on or change what it holds (it lets the machine run or stops it, feeds it
#: input, records it running, writes its memory or registers, resets or restores it), or that
#: cannot be told from one (`lua`, `debug`, and `focus`, which may run the machine on a stub that
#: serves one cpu). Every other tool is `STILL_TOOLS`, and the two lists are written out so a new
#: tool has to be put on one side: the suite holds them against the registry.
DRIVING_TOOLS = frozenset({
    "run_to", "run_for", "trace", "step", "resume", "stop", "series_capture", "input", "record",
    "audio_record", "reset", "state_load", "throttle", "drive", "perform", "lua", "debug",
    "focus", "write", "set_register"})
STILL_TOOLS = frozenset({
    "audio_diff", "audio_measure", "breakpoint_at", "breakpoint_clear", "breakpoint_list",
    "captures", "close", "comment_add", "comment_delete", "comment_list", "comment_load",
    "comment_save", "cpu_info", "disassemble", "find", "gfx_blit_source", "gfx_blits",
    "gfx_draft", "gfx_film", "gfx_load", "gfx_locate", "gfx_sweep", "gfx_view", "golden_check",
    "history", "image_diff", "log", "log_wait", "machine_map", "map_add", "map_find", "map_load",
    "map_save", "memdump", "palette", "palette_log", "perform_export", "read_block",
    "read_memory", "region_track", "registers", "regpoint_add", "regpoint_clear",
    "regpoint_list", "rom_check", "scan_clear", "scan_filter", "scan_start", "screen_signature",
    "screen_view", "series_diff", "snapshot", "start", "state_list",
    "state_save", "status", "symbols_find", "watch_add", "watch_clear", "watch_list"})

# THE DRAWER, one chunk of the boot harness inside its own `pcall` like the others. Its file holds
# `held`, `acting`, or nothing at all (no session state yet), which draws nothing. Each band of the
# edge is a ring of four boxes that do not overlap, so no pixel is blended twice; the alpha falls
# from the rim inwards. The fade from `acting` to `held` runs over `fade` seconds of the host's
# clock while the machine RUNS; a stopped machine is repainted only now and then, so what a
# repaint there draws is the state as it is, never a frame of a fade. While the machine runs the
# file is read at most every `REREAD` seconds, so a thousand frames a second do not cost a
# thousand reads. A drawer that raises, or one that could not be set up at all, draws no more and
# writes why beside the state file, where `status` reads it.
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

#: How often a running machine's drawer reads the state file: well inside the latency a state
#: change may take to show, and far below the frame rate of a machine running flat out.
REREAD_S = 0.05
#: THE REPAINT: a console command that touches nothing (pc, the cycle count and memory are the
#: same across it) and repaints a stopped machine once. A `print` of a constant answers at once.
REPAINT = "print 0"

#: What the drawer writes, beside the state file, when it raises.
BROKEN_FILE = "presence.broken"


def drawer(scratch: Path, look: presence.Look = presence.LOOK) -> str:
    """The drawer's chunk for a session whose scratch is `scratch`."""
    # IMPORTED HERE: the session state reads this module, and the transport reads the state.
    import mame_transport as transport
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


#: A session to repaint, asked by the scratch of the session the adapter was made for: None when
#: that session is gone, broken, running or exited.
Repaintable = Callable[[Path], "Console | None"]


class Console(Protocol):
    """What the repaint sends through: a console command whose answer nobody reads."""

    def monitor_owed(self, command: str, timeout: float = ...) -> None: ...


class FileAdapter:
    """`scry_core.presence.Adapter` over the state file: each state replaces the file whole, so
    the hook reads one word or the previous one, never half of either. The repaint's server
    lock, the session it repaints and the console's queue are handed in, never reached for."""

    def __init__(self, scratch: Path, lock: boundary.ServerLock, session: Repaintable,
                 pending: Callable[[Path], int]) -> None:
        self._path = scratch / STATE_FILE
        self._lock, self._session, self._pending = lock, session, pending

    def show(self, state: presence.State) -> None:
        part = self._path.with_suffix(".part")
        part.write_text(state + "\n", encoding="ascii")
        os.replace(part, self._path)

    def wake(self) -> None:
        """A repaint waiting for the lock asks `still()` again now (`ServerLock.wake`)."""
        self._lock.wake()

    def repaint(self, still: Callable[[], bool]) -> None:
        """`REPAINT` sent through the session's console, under the server's lock, taken while
        `still()` holds and asked again only when a call frees the lock (`ServerLock`), so a long
        still call costs no wake-ups and a driving call makes it moot; sent only to this
        session's machine, alive, unbroken and stopped (a running one repaints by itself), and
        never while a Lua line waits in the console's pipe, which a console command would have
        MAME evaluate there and then. Its console request runs out as the presence's failure
        and never breaks the session (`monitor_owed`)."""
        if not self._lock.acquire_while(still):
            return
        try:
            scratch = self._path.parent
            if still() and (ses := self._session(scratch)) is not None \
                    and not self._pending(scratch):
                ses.monitor_owed(REPAINT)
        finally:
            self._lock.release()
