-- The names the machine gives, read once at boot into a dump of their own and never asked for
-- again: the namer and `knowledge_find` answer from it. Each section is in a pcall of its own, so
-- a machine that lacks one (no ports, an unfamiliar handler) still gives the rest. Tab-separated,
-- because a field's name holds blanks.
local function mame_mcp_names()
  local out = {}
  local function add(s)
    out[#out + 1] = s
  end
  local function sorted(t)
    local keys = {}
    for k in pairs(t) do
      keys[#keys + 1] = k
    end
    table.sort(keys)
    return keys
  end
  -- A handler as `<type>` or `<type>/<name>`; none is `-`.
  local function handler(entry, which)
    local h = entry[which]
    if h == nil then
      return "-"
    end
    local name = h.name
    if name == nil or name == "" then
      return h.handlertype or "unknown"
    end
    return (h.handlertype or "unknown") .. "/" .. name
  end
  add(__SCRY_begin__)
  local devices = manager.machine.devices
  pcall(function()
    for _, tag in ipairs(sorted(devices)) do
      local dev = devices[tag]
      add(string.format("DEVICE\t%s\t%s\t%s", tag, dev.shortname, dev.name))
    end
  end)
  pcall(function()
    local ports = manager.machine.ioport.ports
    for _, tag in ipairs(sorted(ports)) do
      local fields = ports[tag].fields
      for _, fname in ipairs(sorted(fields)) do
        add(string.format("INPUT\t%s\t%s\t%x", tag, fname, fields[fname].mask))
      end
    end
  end)
  pcall(function()
    for _, tag in ipairs(sorted(devices)) do
      local dev = devices[tag]
      if dev.debug ~= nil then
        for _, sname in ipairs(sorted(dev.spaces)) do
          local entries = dev.spaces[sname].map.entries
          for i = 1, #entries do
            local r, w = handler(entries[i], "read"), handler(entries[i], "write")
            if r ~= "-" or w ~= "-" then
              add(string.format("HANDLER\t%s\t%s\t%d\t%s\t%s", tag, sname, i, r, w))
            end
          end
        end
      end
    end
  end)
  add(__SCRY_end__)
  return out
end
local gathered, gather_error = pcall(function()
  local f = assert(io.open(__SCRY_dump__, "w"))
  for _, line in ipairs(mame_mcp_names()) do
    f:write(line .. "\n")
  end
  f:close()
end)
if not gathered then
  local f = io.open(__SCRY_dump__, "w")
  if f then
    f:write(__SCRY_failed__ .. " " .. tostring(gather_error) .. "\n")
    f:close()
  end
end
