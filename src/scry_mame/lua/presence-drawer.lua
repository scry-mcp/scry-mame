-- Drawn on the render manager's UI container, which the window shows and the snapshot target
-- and `screen:pixels()` do not.
-- A drawer that raises writes why beside the state file, where `status` reads it.
-- Written by the mame MCP server for ONE session: the presence edge.
local path, broke = __SCRY_path__, __SCRY_broke__
local function stopped(err)
  local f = io.open(broke, "w")
  if f then
    f:write(tostring(err))
    f:close()
  end
  manager.machine:logerror("MAME_MCP_PRESENCE stopped: " .. tostring(err) .. "\n")
end
local set_up, why = pcall(function()
  local RGB, EDGE, STEPS = __SCRY_rgb__, __SCRY_edge__, __SCRY_steps__
  local ACTING, HELD, FADE, REREAD = __SCRY_acting__, __SCRY_held__, __SCRY_fade__, __SCRY_reread__
  local now, since, read_at, broken = "off", -1e9, -1e9, false
  -- The repaints drawn in each state: what the live cells read back to see it drawn.
  _G.scry_presence_frames = { held = 0, acting = 0 }
  emu.register_frame_done(function()
    if broken then
      return
    end
    local ok, err = pcall(function()
      local t = emu.osd_ticks() / emu.osd_ticks_per_second()
      local running = manager.machine.debugger == nil
        or manager.machine.debugger.execution_state == "run"
      if not running or t - read_at >= REREAD then
        read_at = t
        local f = io.open(path, "r")
        local was = now
        now = "off"
        if f then
          now = f:read("l") or "off"
          f:close()
        end
        if now ~= was then
          since = t
        end
      end
      if now ~= "held" and now ~= "acting" then
        return
      end
      local alpha = HELD
      if now == "acting" then
        alpha = ACTING
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
if not set_up then
  stopped(why)
end
