-- One session's throttle: flat out to the frame the environment names, real speed after.
-- In a `pcall`: an error would stop the whole autoboot script, harness included.
pcall(function()
  local screen = nil
  for _, s in pairs(manager.machine.screens) do
    screen = s
    break
  end
  local TARGET = tonumber(os.getenv(__SCRY_var__) or "0")
  local done = screen == nil
  _G._mame_mcp_throttle = emu.add_machine_frame_notifier(function()
    if done then
      return
    end
    if screen:frame_number() >= TARGET then
      done = true
      manager.machine.video.throttled = true
      manager.machine:logerror(string.format("%s %d\n", __SCRY_mark__, screen:frame_number()))
    end
  end)
end)
