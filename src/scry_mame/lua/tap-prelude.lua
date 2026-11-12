local T = _G.__SCRY_registry__
if T == nil then
  T = { items = {}, periodic = false }
  _G.__SCRY_registry__ = T
end
