local ilo, ishift, iword = word_lane(ip)
taps[#taps + 1] = sp:install_write_tap(
  ilo,
  ilo + nb - 1,
  "mcp_ramdac_i_" .. id,
  guarded(t, function(_, data, mask)
    local m = (mask >> ishift) & iword
    if m == 0 then
      return
    end
    local v = (data >> ishift) & iword
    local fr, pc, w = frame(), curpc.value, by()
    t.n, t.index_writes, t.dirty = t.n + 1, t.index_writes + 1, true
    if t.sync then
      t.idx = ((t.idx & ~m) | (v & m)) & pmask
    elseif (m & pmask) == pmask then
      t.idx, t.sync = v & pmask, true
    else
      desync("index_partial")
      return
    end
    local row = log("i %d %d %x %s %x", t.n, fr, pc, w, t.idx)
    if w == "?" then
      undecided(row, nil)
    end
  end)
)
