-- Refused before the old tap goes: a big-endian bus, or index and data in one word.
if sp.endianness ~= "little" then
  error("a packed palette port is read little-endian, and this bus is " .. sp.endianness)
end
if ip ~= nil and ip - ip % (sp.data_width // 8) == dp - dp % (sp.data_width // 8) then
  error("the index port and the data port share a bus word, so each would see the other's writes")
end
