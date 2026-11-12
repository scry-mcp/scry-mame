-- A rerun over a held id removes the old tap first, so it never taps twice.
local old = T.items[id]
if old ~= nil and old.tap ~= nil then
  old.tap:remove()
end
