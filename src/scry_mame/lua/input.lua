-- A new script releases the previous notifier first: at most one is armed.
if _G._mame_mcp_input_release then
  _G._mame_mcp_input_release()
end
local p = manager.machine.ioport.ports[__SCRY_port__]
if p == nil then
  error("no port " .. __SCRY_port__)
end
local f = p.fields[__SCRY_field__]
if f == nil then
  error("port " .. __SCRY_port__ .. " has no field " .. __SCRY_field__)
end
local screen = nil
for _, s in pairs(manager.machine.screens) do
  screen = s
  break
end
local start = screen and screen:frame_number() or -1
local before = p:read()
f:set_value(__SCRY_value__)
local done = false
_G._mame_mcp_input_release = function()
  done = true
  f:clear_value()
end
_G._mame_mcp_input = emu.add_machine_frame_notifier(function()
  if done then
    return
  end
  local frame = screen and screen:frame_number() or -1
  if frame - start >= __SCRY_frames__ then
    done = true
    local held = p:read()
    f:clear_value()
    manager.machine:logerror(
      string.format("%s release frame=%d port_held=%08x\n", __SCRY_mark__, frame, held)
    )
  end
end)
manager.machine:logerror(
  string.format(
    "%s set name=%q player=%d mask=%08x defvalue=%08x port_before=%08x frame=%d\n",
    __SCRY_mark__,
    f.name,
    f.player,
    f.mask,
    f.defvalue,
    before,
    start
  )
)
