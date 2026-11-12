-- The callback is the hot path (hundreds of thousands of writes per line): the writer's state
-- entry is looked up once at install, the value key is an integer, and a bus-aligned range
-- skips the lane test.
local curpc = cpu.state["CURPC"]
local wtap = sp:install_write_tap(
  lo,
  hi,
  "mcp_tally_" .. id,
  guarded(t, function(offset, data, mask)
    if not aligned and not lands(offset, mask) then
      return
    end
    t.total = t.total + 1
    local at = t.values[offset]
    if at == nil then
      at = {}
      t.values[offset] = at
    end
    local k = ((data & mask) << 32) | mask
    local c = at[k]
    if c ~= nil then
      at[k] = c + 1
    elseif t.nvalues < __SCRY_buckets_max__ then
      at[k] = 1
      t.nvalues = t.nvalues + 1
    else
      t.overflow_values = t.overflow_values + 1
    end
    local pc = curpc.value
    local p = t.pcs[pc]
    if p ~= nil then
      t.pcs[pc] = p + 1
    elseif t.npcs < __SCRY_buckets_max__ then
      t.pcs[pc] = 1
      t.npcs = t.npcs + 1
    else
      t.overflow_pcs = t.overflow_pcs + 1
    end
    t.dirty = true
  end)
)
