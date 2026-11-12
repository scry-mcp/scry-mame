-- `vpos()`: half a pixel past a line counts as the next; the 1e-9 nudge beats rounding.
local function beam_line()
  if screen == nil then
    return __SCRY_no_frame__
  end
  local scan = screen.scan_period
  local since = screen.frame_period - screen:time_until_pos(0, 0)
  return math.floor((since + screen.pixel_period / 2) / scan + 1e-9)
    % math.floor(screen.frame_period / scan + 0.5)
end
