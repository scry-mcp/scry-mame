-- Begun at the notifier's first call and ended N - 1 calls later, the recording holds N
-- frames whatever the console's timing.
if _G._mame_mcp_record_release then
  _G._mame_mcp_record_release()
end
local v = manager.machine.video
local screen = nil
for _, s in pairs(manager.machine.screens) do
  screen = s
  break
end
if screen == nil then
  error(__SCRY_no_screen__ .. " to record")
end
local counted = -1
local done = false
_G._mame_mcp_record_release = function()
  done = true
  if v.is_recording then
    v:end_recording()
  end
end
_G._mame_mcp_record = emu.add_machine_frame_notifier(function()
  if done then
    return
  end
  if counted < 0 then
    v:begin_recording(__SCRY_path__, "avi")
    counted = 0
    manager.machine:logerror(
      string.format(
        "%s begin frame=%d recording=%s\n",
        __SCRY_mark__,
        screen:frame_number(),
        tostring(v.is_recording)
      )
    )
    return
  end
  counted = counted + 1
  if counted >= __SCRY_frames__ - 1 then
    done = true
    v:end_recording()
    manager.machine:logerror(
      string.format("%s end frame=%d\n", __SCRY_mark__, screen:frame_number())
    )
  end
end)
