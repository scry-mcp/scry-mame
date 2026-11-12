local mem = manager.machine.memory
local function block(name)
  for _, cand in ipairs({ name, ":" .. name }) do
    if mem.shares[cand] then
      return "share", cand, mem.shares[cand]
    end
    if mem.regions[cand] then
      return "region", cand, mem.regions[cand]
    end
  end
  return nil
end
local function tags()
  local t = {}
  for tag in pairs(mem.shares) do
    t[#t + 1] = tag .. "=share"
  end
  for tag in pairs(mem.regions) do
    t[#t + 1] = tag .. "=region"
  end
  table.sort(t)
  return table.concat(t, ",")
end
local kind, tag, blk, start
local offset = __SCRY_offset__
local addr = __SCRY_addr__
if addr then
  local space = __SCRY_cpu__.spaces["program"]
  local hit = nil
  for _, e in ipairs(space.map.entries) do
    if e.address_start <= addr and addr <= e.address_end then
      hit = e
      break
    end
  end
  if hit == nil then
    print(string.format("MAME_MCP_BLOCK_NOENTRY addr=%x", addr))
  elseif hit.share == nil and hit.region == nil then
    print(
      string.format("MAME_MCP_BLOCK_NOBLOCK start=%x end=%x", hit.address_start, hit.address_end)
    )
  else
    kind, tag, blk = block(hit.share or hit.region)
    if kind == nil then
      print("MAME_MCP_BLOCK_NONE name=" .. (hit.share or hit.region) .. " tags=" .. tags())
    else
      start = hit.address_start
      offset = addr - start + (hit.share and 0 or (hit.region_offset or 0))
    end
  end
else
  kind, tag, blk = block(__SCRY_tag__)
  if kind == nil then
    print("MAME_MCP_BLOCK_NONE name=" .. __SCRY_tag__ .. " tags=" .. tags())
  end
end
if kind then
  local length = __SCRY_length__
  if offset + length > blk.size then
    print(
      string.format(
        "MAME_MCP_BLOCK_OUTSIDE kind=%s tag=%s size=%d offset=%d length=%d",
        kind,
        tag,
        blk.size,
        offset,
        length
      )
    )
  else
    local t = {}
    for i = offset, offset + length - 1 do
      t[#t + 1] = string.format("%02x", blk:read_u8(i))
    end
    print(
      string.format(
        "MAME_MCP_BLOCK kind=%s tag=%s size=%d bytewidth=%d endian=%s "
          .. "start=%s offset=%d hex=%s",
        kind,
        tag,
        blk.size,
        blk.bytewidth,
        tostring(blk.endianness),
        start and string.format("%x", start) or "-",
        offset,
        table.concat(t)
      )
    )
  end
end
