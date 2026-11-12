-- The next frame if stopped in vblank (one off under VIDEO_UPDATE_AFTER_VBLANK).
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
