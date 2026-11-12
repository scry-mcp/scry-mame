local tag = __SCRY_call__
if tag then
  local scr = manager.machine.screens[tag]
  local v = manager.machine.video
  local f = assert(io.open(__SCRY_snap__, "wb"))
  f:write(v:snapshot_pixels())
  f:close()
  local w, h = v:snapshot_size()
  local sp = __SCRY_cpu__.spaces[__SCRY_space__]
  print(
    string.format(
      "MCP_FILM_ARM snap_w=%d snap_h=%d data_width=%d endianness=%s " .. "refresh=%.6f",
      w,
      h,
      sp.data_width,
      sp.endianness,
      scr.refresh
    )
  )
end
