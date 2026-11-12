local function pens()
  local pal = scr.palette
  if pal == nil then
    return ""
  end
  local p = {}
  for i = 0, pal.entries - 1 do
    p[i + 1] = string.pack("=I4", pal:pen_color(i))
  end
  return table.concat(p)
end
