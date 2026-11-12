-- MAME's `ramdac_device`: an index byte write sets the index and sends the component
-- counter to 0; a data byte write lands on component `order[counter]` of the indexed pen, and
-- at three the counter returns to 0 and the index moves on when the device auto-increments.
local function lane(addr)
  local lo = addr - (addr % nb)
  return lo, (sp.endianness == "big" and (nb - 1 - (addr - lo)) * 8 or (addr - lo) * 8)
end
local comp = __SCRY_comp__
local ilo, ishift = lane(ip)
local dlo, dshift = lane(dp)
local itap = sp:install_write_tap(
  ilo,
  ilo + nb - 1,
  "mcp_ramdac_i_" .. id,
  guarded(t, function(_, data, mask)
    if ((mask >> ishift) & 0xff) == 0 then
      return
    end
    local v = (data >> ishift) & 0xff
    t.n, t.index_writes = t.n + 1, t.index_writes + 1
    t.idx, t.slot, t.sync, t.dirty = v & pmask, 0, true, true
    local w = by()
    local row = log("i %d %d %x %s %x", t.n, frame(), curpc.value, w, v & pmask)
    if w == "?" then
      undecided(row, nil)
    end
  end)
)
local dtap = sp:install_write_tap(
  dlo,
  dlo + nb - 1,
  "mcp_ramdac_d_" .. id,
  guarded(t, function(_, data, mask)
    if ((mask >> dshift) & 0xff) == 0 then
      return
    end
    local v = (data >> dshift) & 0xff
    local fr, pc, w = frame(), curpc.value, by()
    t.n, t.total, t.dirty = t.n + 1, t.total + 1, true
    if not t.sync then
      t.unsynced = t.unsynced + 1
      local row = log("d %d %d %x %s - - %x", t.n, fr, pc, w, v)
      if w == "?" then
        undecided(row, nil)
      end
      return
    end
    local pen, slot = base + t.idx, t.slot
    local p = t.pens[pen]
    if p == nil then
      p = { c = {}, count = 0 }
      t.pens[pen] = p
    end
    p.c[comp[slot + 1]] = v
    p.count, p.n, p.frame, p.pc, p.by = p.count + 1, t.n, fr, pc, w
    local row = log("d %d %d %x %s %x %d %x", t.n, fr, pc, w, pen, slot, v)
    if w == "?" then
      undecided(row, pen)
    end
    slot = slot + 1
    if slot == 3 then
      slot = 0
      if auto then
        t.idx = (t.idx + 1) & pmask
      end
    end
    t.slot = slot
  end)
)
local taps = { itap, dtap }
