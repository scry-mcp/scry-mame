-- Written by the mame MCP server for ONE session: the state file says what to draw, and this
-- only animates it. It draws on the UI container, which the window shows and a capture does not;
-- a drawer that raises writes why beside the state file, where `status` reads it.
local path, broke = __SCRY_path__, __SCRY_broke__
-- `scry_drawn` marks this chunk loaded: MAME runs every callback registered, so a second load
-- would register a second drawer and draw each box twice, darkening the edge. One line, because
-- the console takes no script longer than the transport's bound.
if _G.scry_drawn then
  return
end
_G.scry_drawn = true
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
  local REC_RGB, BLINK = __SCRY_rec_rgb__, __SCRY_blink__
  local ui = manager.ui
  local cur, raw, since, read_at, broken = { state = "off" }, nil, -1e9, -1e9, false
  local rec_since, rec_w = -1e9, nil
  -- The repaints drawn in each state: what the live cells read back to see it drawn.
  _G.scry_presence_frames = { held = 0, acting = 0 }

  local function parse(text)
    local out = { state = "off", rec = "none", layers = {} }
    local first = true
    for line in text:gmatch("[^\n]+") do
      local k, v = line:match("^([%w_]+)=(.*)$")
      if first then
        out.state, first = line, false
      elseif k == "layers" then
        for layer in v:gmatch("[^,]+") do
          out.layers[layer] = true
        end
      elseif k == "rec" then
        out.rec = v
      end
    end
    return out
  end

  local function argb(alpha, rgb)
    return (math.floor(255 * alpha + 0.5) << 24) | rgb
  end

  -- A filled disc as stacked boxes: the UI container has no round primitive.
  local function disc(c, cx, cy, d, ux, col)
    for i = 0, 6 do
      local y0 = cy - d / 2 + i * d / 7
      local y1 = y0 + d / 7
      local dy = (y0 + y1) / 2 - cy
      local half = math.sqrt((d / 2) ^ 2 - dy ^ 2) * ux
      c:draw_box(cx - half, y0, cx + half, y1, 0, col)
    end
  end

  -- An eighth note from a disc, a stem and a flag: MAME's UI font is not asked for a glyph.
  local function note(c, x, y, lh, ux, col)
    local head, stem = lh * 0.36, lh * 0.07 * ux
    disc(c, x + head * ux / 2, y + lh - head / 2, head, ux, col)
    local sx = x + head * ux - stem
    c:draw_box(sx, y, sx + stem, y + lh - head / 2, 0, col)
    c:draw_box(sx, y, sx + lh * 0.2 * ux, y + lh * 0.12, 0, col)
  end

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
        local text = f and f:read("a") or ""
        if f then
          f:close()
        end
        if text ~= raw then
          local was = cur
          raw, cur = text, parse(text)
          if cur.state ~= was.state then
            since = t
          end
          if cur.rec ~= was.rec then
            rec_since = t
          end
        end
      end
      local now = cur.state
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
        local x0, y0, x1, y1 =
          ex * i / STEPS, ey * i / STEPS, ex * (i + 1) / STEPS, ey * (i + 1) / STEPS
        c:draw_box(x0, y0, 1 - x0, y1, 0, col)
        c:draw_box(x0, 1 - y1, 1 - x0, 1 - y0, 0, col)
        c:draw_box(x0, y1, x1, 1 - y1, 0, col)
        c:draw_box(1 - x1, y1, 1 - x0, 1 - y1, 0, col)
      end
      local lh = ui.line_height
      local ux = tg.height / tg.width
      local pad, gap = lh * 0.2, lh * 0.25
      local rowh = lh + 2 * pad
      local rec = cur.layers.record and cur.rec or "none"
      local video, audio = rec ~= "audio", rec ~= "video"
      local mark_w = 0
      if rec ~= "none" then
        rec_w = rec_w or ui:get_string_width("REC")
        local dot = lh * 0.7 * ux
        mark_w = pad * ux * 2
          + dot
          + (video and pad * ux + rec_w or 0)
          + (audio and pad * ux + lh * 0.49 * ux or 0)
      end
      -- Top right; a stopped machine repaints on a console command only, so there it stays lit.
      if mark_w > 0 and (not running or (t - rec_since) % BLINK < BLINK / 2) then
        local y, right = ey + gap, 1 - ex - gap
        local x = right - mark_w
        c:draw_box(x, y, right, y + rowh, 0, argb(0.8, 0x202020))
        x = x + pad * ux
        disc(c, x + lh * 0.35 * ux, y + rowh / 2, lh * 0.7, ux, argb(1, REC_RGB))
        x = x + lh * 0.7 * ux + pad * ux
        if video then
          c:draw_text(x, y + pad, "REC", argb(1, 0xFFFFFF), 0)
          x = x + rec_w + pad * ux
        end
        if audio then
          note(c, x, y + pad, lh, ux, argb(1, 0xFFFFFF))
        end
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
