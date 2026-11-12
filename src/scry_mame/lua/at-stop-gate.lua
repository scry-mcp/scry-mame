-- Written by the mame MCP server: the gate of one screen_wait on a declared stop.
local state_path, ctl_path = __SCRY_state__, __SCRY_ctl__
local cpu = manager.machine.devices[__SCRY_cpu__]
local dbg = manager.machine.debugger
local screen = nil
for _, s in pairs(manager.machine.screens) do
  screen = s
  break
end
local sp = cpu.spaces["program"]
--- __SCRY_beam__
local T = {
  kind = __SCRY_kind__,
  pc = __SCRY_pc__,
  waddr = __SCRY_waddr__,
  wwidth = __SCRY_wwidth__,
  firings = 0,
  examined = 0,
  window = 0,
  line = -1,
  seq = 0,
  candidate = nil,
  waiting = false,
  rejected = {},
  lastt = nil,
  mode = "wait",
  token = "",
  held = "",
}
local missing = nil
for _, name in ipairs(__SCRY_registers__) do
  if cpu.state[name] == nil then
    missing = name
  end
end
local function bytes()
  local t = {}
  for i = 0, T.wwidth - 1 do
    t[#t + 1] = string.char(sp:read_u8(T.waddr + i))
  end
  return table.concat(t)
end
local before = T.kind == "watch" and bytes() or nil
-- A change watch also stops on a write of the value already there, so its firing is the
-- console's own line (`Stopped at watchpoint N writing V to A`), read since the last stop, or
-- else its bytes differing.
local function lines()
  local ok, n = pcall(function()
    return #dbg.consolelog
  end)
  return ok and n or 0
end
local read_to = lines()
local function watch_logged()
  local ok, hit = pcall(function()
    local n, found = #dbg.consolelog, false
    for i = read_to + 1, n do
      local a = dbg.consolelog[i]:match("Stopped at watchpoint %x+ writing %x+ to (%x+)")
      if a ~= nil and tonumber(a, 16) >= T.waddr and tonumber(a, 16) < T.waddr + T.wwidth then
        found = true
      end
    end
    read_to = n
    return found
  end)
  return ok and hit
end
local function condition()
  return __SCRY_condition__
end
local function now()
  return manager.machine.time:as_double()
end
local function save(outcome)
  T.seq = T.seq + 1
  local f = assert(io.open(state_path .. ".tmp", "w"))
  f:write(
    string.format(
      "seq=%d outcome=%s firings=%d examined=%d line=%d pc=%x\n",
      T.seq,
      outcome,
      T.firings,
      T.examined,
      T.line,
      cpu.state["CURPC"].value
    )
  )
  f:close()
  -- Windows' rename refuses an existing target.
  if not os.rename(state_path .. ".tmp", state_path) then
    os.remove(state_path)
    assert(os.rename(state_path .. ".tmp", state_path))
  end
end
-- The server's word: nothing until `go N` (the console's reader steps the machine after the
-- install, and that stop is nobody's firing); each new N releases a stop held for it; `off`
-- ends the gate and lets its pictures go.
local function control()
  if T.mode ~= "off" then
    local f = io.open(ctl_path, "r")
    if f then
      local word, n = (f:read("l") or ""):match("^(%a+)%s*(%d*)$")
      f:close()
      if word == "off" then
        T.mode, T.rejected, T.candidate = "off", {}, nil
        save("off")
      elseif word == "go" then
        T.mode, T.token = "go", n
      end
    end
  end
  return T.mode
end
local function hold(outcome)
  T.waiting, T.held = true, T.token
  save(outcome)
end
if missing ~= nil then
  save("noregister")
  return
end
emu.register_periodic(function()
  local mode = control()
  if mode ~= "go" then
    if mode == "wait" and dbg.execution_state == "stop" then
      T.lastt = now()
    end
    return
  end
  if T.waiting then
    if T.token == T.held then
      return
    end
    T.waiting = false
    -- Released: everything up to here was the server's (its reads step the machine), so the
    -- stop it stands at, the console's lines and the watched bytes are taken as seen.
    T.lastt, read_to = now(), lines()
    if T.kind == "watch" then
      before = bytes()
    end
    if T.candidate ~= nil then
      table.insert(T.rejected, T.candidate)
      if #T.rejected > __SCRY_rejected_max__ then
        table.remove(T.rejected, 1)
      end
      T.candidate = nil
    end
  end
  if dbg.execution_state ~= "stop" then
    return
  end
  local t = now()
  if T.lastt == t then
    return
  end
  T.lastt = t
  if T.candidate ~= nil then
    hold("candidate")
    return
  end
  local fired
  if T.kind == "breakpoint" then
    fired = cpu.state["CURPC"].value == T.pc
  else
    local b = bytes()
    fired, before = watch_logged() or b ~= before, b
  end
  if not fired then
    hold("other")
    return
  end
  T.firings = T.firings + 1
  if condition() then
    T.window = __SCRY_window__
    T.line = beam_line()
  end
  dbg.execution_state = "run"
end)
emu.register_frame_done(function()
  if control() ~= "go" or T.waiting or T.candidate ~= nil or T.window <= 0 then
    return
  end
  T.window = T.window - 1
  T.examined = T.examined + 1
  local px = screen:pixels()
  for _, r in ipairs(T.rejected) do
    if r == px then
      return
    end
  end
  T.candidate = px
  dbg.execution_state = "stop"
end)
save("installed")
