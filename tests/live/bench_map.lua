-- The map this boot declares: a line per entry of every cpu's program space.
local f = assert(io.open(__SCRY_dump__, "w"))
local ok, err = pcall(function()
  local devices = manager.machine.devices
  local tags = {}
  for tag, _ in pairs(devices) do
    tags[#tags + 1] = tag
  end
  table.sort(tags)
  for _, tag in ipairs(tags) do
    local dev = devices[tag]
    if dev.debug ~= nil and dev.spaces.program ~= nil then
      local space = dev.spaces.program
      f:write(
        string.format("SPACE %s width=%d mask=%x\n", tag, space.data_width, space.address_mask)
      )
      for i, e in ipairs(space.map.entries) do
        f:write(
          string.format(
            "ENTRY %s %d %x %x %s %d\n",
            tag,
            i,
            e.address_start,
            e.address_end,
            e.region or "-",
            e.region_offset or 0
          )
        )
      end
    end
  end
end)
if not ok then
  f:write("ERROR " .. tostring(err) .. "\n")
end
f:close()
