-- Runs inside a `pcall`: this is the first chunk of the `-autoboot_script`, and a raise would
-- keep the throttle and caller harnesses behind it from installing. A failure is written into
-- the dump instead.
local function mame_mcp_inventory()
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
  -- MAME gives an entry's missing share or region as nil or as ""; neither is a tag, so both
  -- dump as the one spelling of absent.
  local function dash_if_absent(v)
    if v == nil or v == "" then
      return "-"
    end
    return v
  end
  add(__SCRY_begin__)
  local devices = manager.machine.devices
  local cpus = {}
  for _, tag in ipairs(sorted(devices)) do
    if devices[tag].debug ~= nil then
      cpus[#cpus + 1] = tag
    end
  end
  for _, tag in ipairs(cpus) do
    local dev = devices[tag]
    local names = sorted(dev.spaces)
    add(
      string.format(
        "CPU %s type=%s name=%s spaces=%s",
        tag,
        dev.shortname,
        dev.name,
        table.concat(names, ",")
      )
    )
    -- The console's names for this cpu's registers: its symbol table takes each state entry.
    local regs = sorted(dev.state)
    add(string.format("REGS %s %s", tag, table.concat(regs, ",")))
    for _, sname in ipairs(names) do
      local space = dev.spaces[sname]
      local entries = space.map.entries
      add(
        string.format(
          "SPACE %s %s data_width=%d endianness=%s entries=%d " .. "address_mask=%x",
          tag,
          sname,
          space.data_width,
          tostring(space.endianness),
          #entries,
          space.address_mask
        )
      )
      for i = 1, #entries do
        local e = entries[i]
        add(
          string.format(
            "ENTRY %s %s %d start=%x end=%x mirror=%x mask=%x share=%s "
              .. "region=%s region_offset=%d",
            tag,
            sname,
            i,
            e.address_start,
            e.address_end,
            e.address_mirror,
            e.address_mask,
            dash_if_absent(e.share),
            dash_if_absent(e.region),
            e.region_offset or 0
          )
        )
      end
    end
  end
  local mem = manager.machine.memory
  for _, tag in ipairs(sorted(mem.regions)) do
    local r = mem.regions[tag]
    add(
      string.format(
        "REGION %s size=%d bytewidth=%d endianness=%s",
        tag,
        r.size,
        r.bytewidth,
        tostring(r.endianness)
      )
    )
  end
  for _, tag in ipairs(sorted(mem.shares)) do
    local s = mem.shares[tag]
    add(
      string.format(
        "SHARE %s size=%d bytewidth=%d endianness=%s",
        tag,
        s.size,
        s.bytewidth,
        tostring(s.endianness)
      )
    )
  end
  local screens = manager.machine.screens
  for _, tag in ipairs(sorted(screens)) do
    local sc = screens[tag]
    add(
      string.format(
        "SCREEN %s width=%d height=%d refresh=%.6f",
        tag,
        sc.width,
        sc.height,
        sc.refresh
      )
    )
  end
  -- THE VIEWS, in a pcall of their own: a board with no render target (no video) lists none,
  -- and that may not cost the inventory above. `SNAPVIEW` is the view MAME's snapshots are
  -- taken through, as MAME resolved `-snapview` (a prefix it matched, or its own fallback).
  pcall(function()
    for _, name in pairs(manager.machine.render.targets[1].view_names) do
      add("VIEW " .. name)
    end
  end)
  pcall(function()
    add("SNAPVIEW " .. manager.machine.video.snapshot_target.current_view.name)
  end)
  add(__SCRY_end__)
  return out
end
local gathered, gather_error = pcall(function()
  local f = assert(io.open(__SCRY_dump__, "w"))
  for _, line in ipairs(mame_mcp_inventory()) do
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
