local old = T.items[id]
if old ~= nil and old.tap ~= nil then
  old.tap:remove()
end
