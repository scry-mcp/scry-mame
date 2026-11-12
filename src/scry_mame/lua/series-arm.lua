MCP_SERIES = MCP_SERIES or {}
if MCP_SERIES.sub ~= nil then
  MCP_SERIES.sub:unsubscribe()
  MCP_SERIES.sub = nil
end
MCP_SERIES = nil
local dir = __SCRY_dir__
local wanted, last = {}, __SCRY_last__
--- __SCRY_wanted__
local v = manager.machine.video
local scr = nil
for _, s in pairs(manager.machine.screens) do
  scr = s
  break
end
if scr == nil then
  print("MCP_SERIES_NO_SCREEN")
  return
end
local t = { pend = nil, kept = 0, lost = {}, done = false, errors = 0, first_error = "" }
local said = ""
local print = function(s)
  said = s
end
--- __SCRY_capture__
local function put(path, data)
  local f = assert(io.open(path, "wb"))
  f:write(data)
  f:close()
end
--- __SCRY_pens__
t.sub = emu.add_machine_frame_notifier(function()
  if t.done then
    return
  end
  local ok, err = pcall(function()
    local fr = scr:frame_number()
    local drew = not v.skip_this_frame
    if t.pend ~= nil then
      if drew then
        said = ""
        local base = dir .. "/raw-" .. t.pend.frame
        local got, why = pcall(mcp_capture, base .. ".bin", true)
        if not got then
          said = "MCP_SERIES_ERROR " .. tostring(why)
        end
        put(base .. ".pens", t.pend.pens)
        put(
          base .. ".txt",
          string.format("frame=%d read_at=%d skipped=%d\n", t.pend.frame, fr, t.pend.skipped)
            .. said
        )
        t.kept, t.pend = t.kept + 1, nil
      else
        t.pend.skipped = t.pend.skipped + 1
      end
    end
    if wanted[fr] then
      if drew then
        t.pend = { frame = fr, pens = pens(), skipped = 0 }
      else
        t.lost[#t.lost + 1] = tostring(fr)
      end
    end
    if fr >= last and t.pend == nil then
      t.done = true
    end
  end)
  if not ok then
    t.errors = t.errors + 1
    if t.first_error == "" then
      t.first_error = tostring(err)
    end
  end
end)
MCP_SERIES = t
_G.print(
  string.format("MCP_SERIES_ARMED frame=%d w=%d h=%d", scr:frame_number(), scr.width, scr.height)
)
