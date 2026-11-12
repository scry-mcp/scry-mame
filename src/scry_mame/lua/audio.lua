-- Ends one notifier call after `record`'s script does. It stops only its own recording and only
-- while the mixer still writes it: a session whose ini names `wavwrite`, or a `lua` call, may have
-- replaced the file, and MAME writes the RIFF size only on close, so a size there means it is
-- no longer this script's.
if _G._mame_mcp_audio_release then
  _G._mame_mcp_audio_release()
end
local snd = manager.machine.sound
local path = __SCRY_path__
local screen = nil
for _, s in pairs(manager.machine.screens) do
  screen = s
  break
end
if screen == nil then
  error(__SCRY_no_screen__ .. " to count frames by")
end
local counted = -1
local began = false
local done = false
local function stop_own()
  if not began then
    return
  end
  began = false
  local f = io.open(path, "rb")
  if f ~= nil then
    f:seek("set", 4)
    local size = f:read(4)
    f:close()
    if size ~= nil and #size == 4 and string.unpack("<I4", size) ~= 0 then
      return
    end
  end
  snd:stop_recording()
end
_G._mame_mcp_audio_release = function()
  done = true
  stop_own()
end
_G._mame_mcp_audio = emu.add_machine_frame_notifier(function()
  if done then
    return
  end
  if counted < 0 then
    began = snd:start_recording(path)
    counted = 0
    manager.machine:logerror(
      string.format(
        "%s begin frame=%d ok=%s recording=%s time=%.17g period=%.17g\n",
        __SCRY_mark__,
        screen:frame_number(),
        tostring(began),
        tostring(snd.recording),
        manager.machine.time:as_double(),
        screen.frame_period
      )
    )
    if not began then
      done = true
    end
    return
  end
  counted = counted + 1
  if counted >= __SCRY_frames__ then
    done = true
    stop_own()
    manager.machine:logerror(
      string.format(
        "%s end frame=%d time=%.17g\n",
        __SCRY_mark__,
        screen:frame_number(),
        manager.machine.time:as_double()
      )
    )
  end
end)
