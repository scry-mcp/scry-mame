manager.machine.video.throttled = __SCRY_on__
local screen = nil
for _, s in pairs(manager.machine.screens) do
  screen = s
  break
end
manager.machine:logerror(
  string.format(
    "%s throttled=%s frame=%d\n",
    __SCRY_mark__,
    tostring(manager.machine.video.throttled),
    screen and screen:frame_number() or -1
  )
)
