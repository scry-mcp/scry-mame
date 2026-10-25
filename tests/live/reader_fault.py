import json
import re
from typing import Any

from live_harness import call

# Proxy over the hook's `conth` upvalue: the first `kills` lines carrying `target` are echoed
# and never run; `lag` holds `busy` for that many frames (not hook runs, which vary by board)
# after the first such line only. Target and death line are split so the plant's own echo
# does not carry them to the server.
READER_FAULT_LUA = """local target = %(target)s
local found, seen = {}, {}
local function scan(v, depth)
  if type(v) == "function" then
    for i = 1, 255 do
      local n, u = debug.getupvalue(v, i)
      if n == nil then break end
      if n == "conth" then found[#found + 1] = {f = v, i = i, u = u} end
    end
  elseif type(v) == "table" and depth > 0 and not seen[v] then
    seen[v] = true
    for _, x in next, v do scan(x, depth - 1) end   -- raw: a sol container refuses `pairs`
  end
end
scan(debug.getregistry(), 4)
if #found == 0 then error("no function holds the console's reader as `conth`") end
local function frame_now()
  for _, sc in pairs(manager.machine.screens) do return sc:frame_number() end
end
local K = {fired = 0, kills = %(kills)d, loud = %(loud)s, lag = %(lag)d, lagged = 0, held = 0}
_G.mcp_reader_fault = K
for _, h in ipairs(found) do
  local real = (type(h.u) == "table" and rawget(h.u, "_mcp_real")) or h.u
  debug.setupvalue(h.f, h.i, setmetatable({_mcp_real = real}, {__index = function(_, k)
    local v = real[k]
    -- `result` is read only where the hook reads it, with the reader idle: the thread writes it.
    local line = k == "busy" and not v and K.lag > 0 and real.result
    if type(line) == "string" and line:find(target, 1, true) and (K.line or line) == line then
      local now = frame_now()
      if K.line == nil then K.line, K.from = line, now end
      if now ~= nil and K.from ~= nil and now < K.from + K.lag then
        K.lagged = K.lagged + 1
        K.held = math.max(K.held, now - K.from)
        return true
      end
    end
    if k == "result" and K.fired < K.kills and type(v) == "string"
        and v:find(target, 1, true) then
      K.fired = K.fired + 1
      if K.loud then print("[LUA ERROR]" .. " in thread: killed by the live harness") end
      return ""
    end
    if type(v) == "function" then return function(_, ...) return v(real, ...) end end
    return v
  end}))
end
print("planted " .. #found)"""


def reader_fault(target: str, kills: int = 0, loud: bool = True, lag: int = 0) -> dict[str, Any]:
    """Fault the console reader on lines carrying `target`."""
    half = len(target) // 2
    return call("lua", read_only=True, script=READER_FAULT_LUA % {
        "target": f"{json.dumps(target[:half])} .. {json.dumps(target[half:])}",
        "kills": kills, "loud": str(loud).lower(), "lag": lag})


def reader_fault_counts() -> tuple[int, int, int]:
    """Lines killed, hook runs held, frames held; -1 each when unanswered."""
    r = call("lua", read_only=True, script=(
        'local K = _G.mcp_reader_fault or {fired = -1, lagged = -1, held = -1}\n'
        'print(string.format("fault %d %d %d", K.fired, K.lagged, K.held))'))
    m = re.search(r"fault (-?\d+) (-?\d+) (-?\d+)", str(r.get("output") or ""))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (-1, -1, -1)
