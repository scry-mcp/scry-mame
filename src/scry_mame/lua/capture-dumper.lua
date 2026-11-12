local function dump(it, fr)
  if not it.dirty and it.dumped_frame == fr then
    return
  end
  if it.npending > 0 then
    local r = opened(it, io.open(it.rows_path, "a"))
    if r ~= nil then
      r:write(table.concat(it.pending, "\n", 1, it.npending), "\n")
      r:close()
      it.pending, it.npending = {}, 0
    end
  end
  it.seq = it.seq + 1
  local f = opened(it, io.open(it.head .. ".tmp", "w"))
  if f == nil then
    return
  end
  f:write(
    string.format(
      "%s %s seq=%d frame=%d total=%d rows=%d ",
      __SCRY_header__,
      it.id,
      it.seq,
      fr,
      it.rows + it.overflow_rows,
      it.rows
    )
  )
  f:write(
    string.format(
      "overflow_rows=%d data_width=%d endianness=%s cpu=%s errors=%d\n",
      it.overflow_rows,
      it.data_width,
      it.endianness,
      it.cpu,
      it.errors
    )
  )
  if it.first_error ~= nil then
    f:write("e ", it.first_error, "\n")
  end
  f:write("end\n")
  f:close()
  replace(it.head .. ".tmp", it.head)
  it.dirty = false
  it.dumped_frame = fr
end
dump_at_stops(T, dump)
