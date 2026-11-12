local rtap = sp:install_read_tap(
  lo,
  hi,
  "mcp_tally_r_" .. id,
  guarded(t, function(offset, data, mask)
    if not aligned and not lands(offset, mask) then
      return
    end
    t.reads = t.reads + 1
    t.dirty = true
  end)
)
