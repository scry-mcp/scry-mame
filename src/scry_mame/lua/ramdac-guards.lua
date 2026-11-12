-- A PACKED PORT is read as the bytes from its own address up to the end of its bus word, which
-- is what a 16-bit port on a 16-bit bus is whole. That reading holds on a little-endian bus; on a
-- big-endian one the port's first byte is the word's high one, so the install refuses there
-- rather than log words it reads in the wrong order. And an index port
-- in the data port's bus word would see every colour as an index write. Both are judged before
-- the old tap goes, so a refused re-arm leaves the log it replaces in place.
if sp.endianness ~= "little" then
  error("a packed palette port is read little-endian, and this bus is " .. sp.endianness)
end
if ip ~= nil and ip - ip % (sp.data_width // 8) == dp - dp % (sp.data_width // 8) then
  error("the index port and the data port share a bus word, so each would see the other's writes")
end
