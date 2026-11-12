local function dump(it, fr)
  if not it.dirty and it.dumped_frame == fr then
    return
  end
  it.seq = it.seq + 1
  local f = opened(it, io.open(it.path .. ".tmp", "w"))
  if f == nil then
    return
  end
  f:write(
    string.format(
      "%s %s seq=%d frame=%d total=%d reads=%d values=%d pcs=%d ",
      __SCRY_header__,
      it.id,
      it.seq,
      fr,
      it.total,
      it.reads,
      it.nvalues,
      it.npcs
    )
  )
  f:write(
    string.format(
      "overflow_values=%d overflow_pcs=%d data_width=%d ",
      it.overflow_values,
      it.overflow_pcs,
      it.data_width
    )
  )
  f:write(string.format("endianness=%s cpu=%s errors=%d\n", it.endianness, it.cpu, it.errors))
  for offset, at in pairs(it.values) do
    for k, c in pairs(at) do
      f:write(string.format("v %x %x %x %d\n", offset, (k >> 32) & 0xffffffff, k & 0xffffffff, c))
    end
  end
  for pc, c in pairs(it.pcs) do
    f:write(string.format("p %x %d\n", pc, c))
  end
  if it.first_error ~= nil then
    f:write("e ", it.first_error, "\n")
  end
  f:write("end\n")
  f:close()
  replace(it.path .. ".tmp", it.path)
  it.dirty = false
  it.dumped_frame = fr
end
dump_at_stops(T, dump)
