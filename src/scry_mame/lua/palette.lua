local pals = manager.machine.palettes
local names = {}
for tag in pairs(pals) do
  names[#names + 1] = tag
end
table.sort(names)
local want = __SCRY_tag__
local tag = nil
if want ~= "" then
  for _, cand in ipairs({ want, ":" .. want }) do
    if pals[cand] then
      tag = cand
      break
    end
  end
  if tag == nil then
    print("MAME_MCP_PAL_NONE name=" .. want .. " palettes=" .. table.concat(names, ","))
    return
  end
elseif #names ~= 1 then
  print("MAME_MCP_PAL_NONE name=- palettes=" .. table.concat(names, ","))
  return
else
  tag = names[1]
end
local p = pals[tag]
local n = p.entries
local first, count = __SCRY_first__, __SCRY_count__
if first >= n or first + count > n then
  print(string.format("MAME_MCP_PAL_PAST tag=%s entries=%d", tag, n))
  return
end
if count == 0 then
  count = math.min(n - first, __SCRY_count_max__)
end
local pens, ind = {}, {}
for i = first, first + count - 1 do
  pens[#pens + 1] = string.format("%08x", p:pen_color(i))
  if p.indirect_entries > 0 then
    ind[#ind + 1] = tostring(p:pen_indirect(i))
  end
end
print(
  string.format(
    "MAME_MCP_PAL tag=%s entries=%d indirect=%d shadows=%s highlights=%s "
      .. "first=%d pens=%s ind=%s",
    tag,
    n,
    p.indirect_entries,
    tostring(p.shadows_enabled),
    tostring(p.highlights_enabled),
    first,
    table.concat(pens, ","),
    table.concat(ind, ",")
  )
)
