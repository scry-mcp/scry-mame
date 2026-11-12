local function mcp_capture(path, want_indices)
  local list = {}
  for tag in pairs(manager.machine.screens) do
    list[#list + 1] = tag
  end
  table.sort(list)
  if #list ~= 1 then
    print("MAME_MCP_SCREEN_COUNT screens=" .. table.concat(list, ","))
    return nil
  end
  local tag = list[1]
  local shot = manager.machine.screens[tag]
  local kind = shot.screen_type
  if kind == nil then
    kind = "raster"
    for _, d in pairs(manager.machine.devices) do
      if d.shortname == "vector_device" then
        kind = "vector"
      end
    end
  end
  if kind ~= "raster" then
    print(string.format("MAME_MCP_SCREEN_KIND tag=%s type=%s", tag, kind))
    return nil
  end
  local frame = shot.frame_number
  if type(frame) == "function" then
    frame = shot:frame_number()
  end
  local pal = shot.palette
  local head = string.format("tag=%s w=%d h=%d frame=%d", tag, shot.width, shot.height, frame)
  if want_indices and pal ~= nil and (pal.shadows_enabled or pal.highlights_enabled) then
    print(string.format("MAME_MCP_SCREEN_SHADOWS %s palette=%s", head, pal.device.tag))
    return nil
  end
  if want_indices and pal ~= nil and pal.entries > __SCRY_encodable__ then
    print(string.format("MAME_MCP_SCREEN_TOO_MANY %s entries=%d", head, pal.entries))
    return nil
  end
  local colour = shot:pixels()
  local f = assert(io.open(path, "wb"))
  f:write(colour)
  if pal == nil or not want_indices then
    f:close()
    print(string.format("MAME_MCP_SCREEN %s palette=- entries=0", head))
    return tag
  end
  local n = pal.entries
  local saved, pens, back = {}, {}, {}
  for i = 0, n - 1 do
    saved[i] = pal:pen_color(i)
  end
  local ok, enc = pcall(function()
    for i = 0, n - 1 do
      pal:set_pen_color(i, 0xff000000 | i)
    end
    return shot:pixels()
  end)
  for i = 0, n - 1 do
    pal:set_pen_color(i, saved[i])
  end
  if not ok then
    f:close()
    error(enc, 0)
  end
  for i = 0, n - 1 do
    pens[#pens + 1] = string.pack("=I4", saved[i])
    back[#back + 1] = string.pack("=I4", pal:pen_color(i))
  end
  local after = shot:pixels()
  f:write(enc)
  f:write(after)
  f:write(table.concat(pens))
  f:write(table.concat(back))
  f:close()
  print(string.format("MAME_MCP_SCREEN %s palette=%s entries=%d", head, pal.device.tag, n))
  return tag
end
