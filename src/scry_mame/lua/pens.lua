local function mcp_pens(name, first, n)
  local pals = manager.machine.palettes
  local t = {}
  for k in pairs(pals) do
    t[#t + 1] = k
  end
  table.sort(t)
  local p = nil
  if name == "" then
    if #t == 1 then
      p = pals[t[1]]
    end
  else
    p = pals[name] or pals[":" .. name]
  end
  if p == nil then
    local shown = name == "" and "-" or name
    print("MAME_MCP_GFX_PENS_NONE name=" .. shown .. " palettes=" .. table.concat(t, ","))
    return
  end
  if first + n > p.entries then
    print(string.format("MAME_MCP_GFX_PENS_SHORT tag=%s entries=%d", p.device.tag, p.entries))
    return
  end
  local out = {}
  for i = first, first + n - 1 do
    out[#out + 1] = string.format("%08x", p:pen_color(i))
  end
  print(
    string.format(
      "MAME_MCP_GFX_PENS tag=%s entries=%d pens=%s",
      p.device.tag,
      p.entries,
      table.concat(out, ",")
    )
  )
end
