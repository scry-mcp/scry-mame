local T = _G.__SCRY_registry__
local id = __SCRY_id__
local it = T and T.items[id]
if it ~= nil then
  if it.tap ~= nil then
    it.tap:remove()
  end
  T.items[id] = nil
  print(__SCRY_answer__ .. " removed tally_id=" .. id)
else
  print(__SCRY_answer__ .. " absent tally_id=" .. id)
end
