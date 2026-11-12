local function mcp_block(path, name, addr, length)
  local mem = manager.machine.memory
  local kind, tag, blk
  if addr then
    local space = __SCRY_cpu__.spaces["program"]
    local data = space:read_range(addr, addr + length - 1, 8)
    local f = assert(io.open(path, "wb"))
    f:write(data)
    f:close()
    print(
      string.format(
        "MAME_MCP_GFX_BLOCK kind=space tag=%s size=%d bytewidth=%d endian=%s",
        space.name,
        #data,
        space.data_width // 8,
        tostring(space.endianness)
      )
    )
    return true
  end
  for _, cand in ipairs({ name, ":" .. name }) do
    if mem.regions[cand] then
      kind, tag, blk = "region", cand, mem.regions[cand]
      break
    end
    if mem.shares[cand] then
      kind, tag, blk = "share", cand, mem.shares[cand]
      break
    end
  end
  if kind == nil then
    local t = {}
    for k in pairs(mem.shares) do
      t[#t + 1] = k .. "=share"
    end
    for k in pairs(mem.regions) do
      t[#t + 1] = k .. "=region"
    end
    table.sort(t)
    print("MAME_MCP_GFX_BLOCK_NONE name=" .. name .. " tags=" .. table.concat(t, ","))
    return nil
  end
  if blk.size > (kind == "share" and __SCRY_share_max__ or __SCRY_bytes_max__) then
    print(string.format("MAME_MCP_GFX_BLOCK_BIG kind=%s tag=%s size=%d", kind, tag, blk.size))
    return nil
  end
  local data
  if kind == "region" then
    data = blk:read(0, blk.size)
  else
    local parts, bytes = {}, {}
    for i = 0, blk.size - 1 do
      bytes[#bytes + 1] = blk:read_u8(i)
      if #bytes == 4096 then
        parts[#parts + 1] = string.char(table.unpack(bytes))
        bytes = {}
      end
    end
    if #bytes > 0 then
      parts[#parts + 1] = string.char(table.unpack(bytes))
    end
    data = table.concat(parts)
  end
  local f = assert(io.open(path, "wb"))
  f:write(data)
  f:close()
  print(
    string.format(
      "MAME_MCP_GFX_BLOCK kind=%s tag=%s size=%d bytewidth=%d endian=%s",
      kind,
      tag,
      blk.size,
      blk.bytewidth,
      tostring(blk.endianness)
    )
  )
  return true
end
