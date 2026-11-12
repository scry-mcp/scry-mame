-- v30-alt's `paldat_w`: a data word with a bit of `index_flag_mask` set sets the index
-- to its low bits; any other word is a whole colour for the indexed pen (the driver takes no
-- mask), and the index moves on when it auto-increments. The optional index port merges into
-- the index under the write's mask (`paloff_w`'s `COMBINE_DATA`).
local flag = __SCRY_flag__
local taps = {}
taps[1] = sp:install_write_tap(
  dlo,
  dlo + nb - 1,
  "mcp_ramdac_d_" .. id,
  guarded(t, function(_, data, mask)
    if (mask >> dshift) & dword == 0 then
      return
    end
    local v = (data >> dshift) & dword
    local fr, pc, w = frame(), curpc.value, by()
    t.n, t.dirty = t.n + 1, true
    if (v & flag) ~= 0 then
      t.index_writes, t.idx, t.sync = t.index_writes + 1, v & pmask, true
      local row = log("i %d %d %x %s %x", t.n, fr, pc, w, t.idx)
      if w == "?" then
        undecided(row, nil)
      end
      return
    end
    t.total = t.total + 1
    if not t.sync then
      unsynced(fr, pc, w, v, dword)
      return
    end
    store(base + t.idx, v, dword, fr, pc, w)
  end)
)
