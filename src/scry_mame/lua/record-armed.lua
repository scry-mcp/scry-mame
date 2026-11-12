-- Predicts where a notifier the debugger evaluated first runs. A chunk evaluated at a stop
-- inside a vblank is first called on the next frame (frame notifiers run at vblank start, the
-- counter moves at vblank end: `screen.cpp`); the running frame update's own chunk is called in
-- that same update. Wrong by one frame under `VIDEO_UPDATE_AFTER_VBLANK`, which Lua cannot see.
manager.machine:logerror(
  string.format(
    "%s armed frame=%d vblank=%s\n",
    __SCRY_mark__,
    screen:frame_number(),
    tostring(
      screen:time_until_vblank_end():as_double() < screen:time_until_vblank_start():as_double()
    )
  )
)
