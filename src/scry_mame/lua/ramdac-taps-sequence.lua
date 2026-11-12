-- v30's `twins_pal_w`: each data write merges into the pen at the offset under its mask
-- (`COMBINE_DATA`), and the offset moves on; any write to the bus word of the index port
-- (`porte_paloff0_w`) sends the offset back to 0.
local ilo = ip - (ip % nb)
local taps = {}
taps[1] = sp:install_write_tap(
  ilo,
  ilo + nb - 1,
  "mcp_ramdac_i_" .. id,
  guarded(t, function()
    local fr, pc, w = frame(), curpc.value, by()
    t.n, t.index_writes, t.dirty = t.n + 1, t.index_writes + 1, true
    t.idx, t.sync = 0, true
    local row = log("i %d %d %x %s 0", t.n, fr, pc, w)
    if w == "?" then
      undecided(row, nil)
    end
  end)
)
taps[2] = sp:install_write_tap(
  dlo,
  dlo + nb - 1,
  "mcp_ramdac_d_" .. id,
  guarded(t, function(_, data, mask)
    local m = (mask >> dshift) & dword
    if m == 0 then
      return
    end
    local v = (data >> dshift) & dword
    local fr, pc, w = frame(), curpc.value, by()
    t.n, t.total, t.dirty = t.n + 1, t.total + 1, true
    if not t.sync then
      unsynced(fr, pc, w, v, m)
      return
    end
    store(base + t.idx, v, m, fr, pc, w)
  end)
)
