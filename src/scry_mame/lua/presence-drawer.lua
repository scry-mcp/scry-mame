-- Drawn on the render manager's UI container, which the window shows and the snapshot target
-- and `screen:pixels()` do not.
-- A drawer that raises writes why beside the state file, where `status` reads it.
-- Written by the mame MCP server for ONE session: the presence edge and the layers over it. The
-- state file says what to draw (caption, keys, pause, recording, where); this only animates it.
local path, broke = __SCRY_path__, __SCRY_broke__
-- `scry_drawn` marks this chunk loaded: MAME runs every callback registered, so a second load
-- would register a second drawer and draw each box twice, darkening a band drawn at less than
-- full alpha. One line, because the console takes no script longer than the transport's bound.
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
  local TEXT_RGB, CAP_ALPHA, KEY_RGB = __SCRY_text_rgb__, __SCRY_cap_alpha__, __SCRY_key_rgb__
  local KEY_TEXT_RGB, KEY_ALPHA = __SCRY_key_text_rgb__, __SCRY_key_alpha__
  local CPS, CAP_FADE, DWELL = __SCRY_cps__, __SCRY_cap_fade__, __SCRY_dwell__
  local REC_RGB, BLINK = __SCRY_rec_rgb__, __SCRY_blink__
  --- __SCRY_placement__
  local ui = manager.ui
  local cur, raw, since, read_at, broken = { state = "off" }, nil, -1e9, -1e9, false
  local cap, cap_rgb, cap_up, gone_at = nil, nil, 0, nil
  local rec_since, rec_w = -1e9, nil
  local band, streak, sampled_at = START, 0, -1e9
  -- The repaints drawn in each state: what the live cells read back to see it drawn.
  _G.scry_presence_frames = { held = 0, acting = 0 }

  local function parse(text)
    local out = {
      state = "off",
      paused = false,
      place = "bottom",
      rec = "none",
      layers = {},
      keys = {},
      key_w = {},
    }
    local first = true
    for line in text:gmatch("[^\n]+") do
      local k, v = line:match("^(%w+)=(.*)$")
      if first then
        out.state, first = line, false
      elseif k == "paused" then
        out.paused = v == "1"
      elseif k == "place" then
        out.place = v
      elseif k == "layers" then
        for layer in v:gmatch("[^,]+") do
          out.layers[layer] = true
        end
      elseif k == "rec" then
        out.rec = v
      elseif k == "serial" then
        out.serial = tonumber(v)
      elseif k == "rgb" then
        out.rgb = tonumber(v, 16)
      elseif k == "caption" then
        out.caption = v
      elseif k == "key" then
        out.keys[#out.keys + 1] = v
        out.key_w[#out.keys] = ui:get_string_width(v)
      end
    end
    return out
  end

  -- The caption's text with the width of every prefix of it, looped once for the scroll.
  local function measure(text)
    local loop = text .. "   " .. text
    local widths = { [0] = 0 }
    for i = 1, #loop do
      widths[i] = widths[i - 1] + ui:get_string_width(loop:sub(i, i))
    end
    return { text = text, loop = loop, widths = widths, whole = widths[#text], lap = #text + 3 }
  end

  local function shown_text(m, room, running, t)
    if m.whole <= room then
      return m.text, m.whole
    end
    local from = 0
    if running then
      from = math.floor(math.max(0, t - cap_up - DWELL) * CPS) % m.lap
    end
    local to = from
    local cut = running and 0 or ui:get_string_width("..")
    while to < #m.loop and m.widths[to + 1] - m.widths[from] + cut <= room do
      to = to + 1
    end
    local text = m.loop:sub(from + 1, to) .. (running and "" or "..")
    return text, m.widths[to] - m.widths[from] + cut
  end

  local function sample()
    local screen
    for _, s in pairs(manager.machine.screens) do
      screen = s
      break
    end
    if screen == nil then
      return
    end
    local px, w, h = screen:pixels()
    if w < 1 or h < 1 then
      return
    end
    local angle, flip_x, flip_y = screen:orientation()
    local pw, ph = w, h
    if angle == 90 or angle == 270 then
      pw, ph = h, w
    end
    local function colours(list)
      local out = {}
      for i, p in ipairs(list) do
        local u, v = p[1], p[2]
        if flip_x then
          u = pw - 1 - u
        end
        if flip_y then
          v = ph - 1 - v
        end
        local x, y = u, v
        if angle == 90 then
          x, y = v, h - 1 - u
        elseif angle == 180 then
          x, y = w - 1 - u, h - 1 - v
        elseif angle == 270 then
          x, y = w - 1 - v, u
        end
        out[i] = string.unpack("<I4", px, (y * w + x) * 4 + 1) & 0xFFFFFF
      end
      return out
    end
    local top, bottom = band_points(pw, ph)
    band, streak = band_step(band, streak, band_score(colours(top)), band_score(colours(bottom)))
  end

  local function argb(alpha, rgb)
    return (math.floor(255 * alpha + 0.5) << 24) | rgb
  end

  -- A filled disc as stacked boxes: the UI container has no round primitive.
  local function disc(c, cx, cy, d, ux, col)
    local rows = 7
    for i = 0, rows - 1 do
      local y0 = cy - d / 2 + i * d / rows
      local y1 = y0 + d / rows
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
          if cur.caption ~= was.caption or cur.serial ~= was.serial then
            if cur.caption then
              cap, gone_at = measure(cur.caption), nil
              cap_rgb = cur.rgb or RGB -- the state file drops the tint with the caption
              if cur.serial ~= was.serial then
                cap_up = t
              end
            elseif cap then
              gone_at = t
            end
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
        local x0, y0 = ex * i / STEPS, ey * i / STEPS
        local x1, y1 = ex * (i + 1) / STEPS, ey * (i + 1) / STEPS
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
      local wants_band = cur.layers.calls or cur.layers.keys
      if wants_band and cur.place == "auto" and t - sampled_at >= SAMPLE_S then
        sampled_at = t
        sample()
      end
      if wants_band or cur.layers.pause then
        local where = cur.place == "auto" and band or cur.place
        local function row_y(n)
          if where == "top" then
            return ey + gap + n * (rowh + gap)
          end
          return 1 - ey - gap - rowh - n * (rowh + gap)
        end
        local left, right = ex + gap, 1 - ex - gap
        if where == "top" and mark_w > 0 then
          right = right - mark_w - gap
        end
        if cur.layers.pause and cur.paused then
          local bar, y = lh * 0.3 * ux, row_y(0)
          local x = right - (2 * bar + bar * 0.8 + 2 * pad * ux)
          c:draw_box(x, y, right, y + rowh, 0, argb(KEY_ALPHA, KEY_RGB))
          local bx = x + pad * ux
          c:draw_box(bx, y + pad, bx + bar, y + pad + lh, 0, argb(0.9, TEXT_RGB))
          c:draw_box(bx + bar * 1.8, y + pad, bx + bar * 2.8, y + pad + lh, 0, argb(0.9, TEXT_RGB))
          right = x - gap
        end
        if cur.layers.calls and cap then
          local fade = 1
          if running and gone_at then
            fade = 1 - (t - gone_at) / CAP_FADE
          elseif running then
            fade = math.min(1, (t - cap_up) / CAP_FADE)
          elseif gone_at then
            fade = 0
          end
          if gone_at and fade <= 0 then
            cap, gone_at = nil, nil
          elseif fade > 0 then
            local y = row_y(0)
            local room = right - left - 2 * pad * ux
            local text, width = shown_text(cap, room, running, t)
            local x = left + pad * ux + (room - width) / 2
            -- the band is the call's own tint, as the clip draws it, never black on black
            c:draw_box(left, y, right, y + rowh, 0, argb(CAP_ALPHA * fade, cap_rgb or RGB))
            c:draw_text(x, y + pad, text, argb(fade, TEXT_RGB), 0)
          end
        end
        if cur.layers.keys and #cur.keys > 0 then
          local y, widths, total = row_y(1), {}, 0
          for i = 1, #cur.keys do
            widths[i] = cur.key_w[i] + 2 * pad * ux
            total = total + widths[i] + gap * ux
          end
          local x = math.max(left, (left + right - (total - gap * ux)) / 2)
          for i, name in ipairs(cur.keys) do
            if x + widths[i] > right then
              break
            end
            c:draw_box(x, y, x + widths[i], y + rowh, 0, argb(KEY_ALPHA, KEY_RGB))
            c:draw_text(x + pad * ux, y + pad, name, argb(1, KEY_TEXT_RGB), 0)
            x = x + widths[i] + gap * ux
          end
        end
      end
      -- Top right whatever `place` says; a stopped machine repaints only on a console command,
      -- so there it stays lit instead of blinking.
      if mark_w > 0 and (not running or (t - rec_since) % BLINK < BLINK / 2) then
        local y, right = ey + gap, 1 - ex - gap
        local x = right - mark_w
        c:draw_box(x, y, right, y + rowh, 0, argb(KEY_ALPHA, KEY_RGB))
        x = x + pad * ux
        disc(c, x + lh * 0.35 * ux, y + rowh / 2, lh * 0.7, ux, argb(1, REC_RGB))
        x = x + lh * 0.7 * ux + pad * ux
        if video then
          c:draw_text(x, y + pad, "REC", argb(1, TEXT_RGB), 0)
          x = x + rec_w + pad * ux
        end
        if audio then
          note(c, x, y + pad, lh, ux, argb(1, TEXT_RGB))
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
