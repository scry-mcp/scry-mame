-- `vpos()` as Lua cannot call it. It adds half a pixel to the time since line 0, so the tie half a
-- pixel before a line is already that line. Lua binds the periods as doubles, where the tie lands
-- either side by rounding error: the nudge of a billionth of a line is far above that error and far
-- below one cycle.
local function beam_line()
  if screen == nil then
    return __SCRY_no_frame__
  end
  local scan = screen.scan_period
  local since = screen.frame_period - screen:time_until_pos(0, 0)
  return math.floor((since + screen.pixel_period / 2) / scan + 1e-9)
    % math.floor(screen.frame_period / scan + 0.5)
end
