"""The console reader faulted on demand, harness-side, for the cells that need a line the
console takes and never runs: section K's installs (`live_matrix.py`) and removals
(`matrix_removals.py`)."""

import json
import re
from typing import Any

from live_harness import call

# THE CONSOLE READER, FAULTED ON DEMAND, harness-side and nothing in the server. The console
# plugin's periodic hook holds its reader thread as the upvalue `conth` and reads `conth.busy`
# and then `conth.result`, the line the reader took, once per run. A proxy put in its place
# answers for the first `kills` lines carrying `target` an empty result, so the line is echoed
# and never evaluated (`loud`, the reader's death line is printed behind the echo, the log
# shape of a death; silent, only the next reader's prompt follows); and with `lag`, answers
# `busy` for that many FRAMES once the reader holds the first such line, a line the hook has
# not got to. Frames and not hook runs, because the hook runs once a frame on one board and
# several times on another; the first line only, because a stopped machine moves no frame and
# a lag on every line would hold the console for good; and a board with no screen has no frame
# to count, so it is never held. The target is split, and so is the death line, so that
# neither travels in the plant's own echo: the server would read either there as the fault.
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
    """Fault the console's reader on the lines carrying `target` (`READER_FAULT_LUA`); a new
    plant replaces the last one's counts and wraps the same reader."""
    half = len(target) // 2
    return call("lua", read_only=True, script=READER_FAULT_LUA % {
        # A JSON string of printable ASCII is a Lua literal too.
        "target": f"{json.dumps(target[:half])} .. {json.dumps(target[half:])}",
        "kills": kills, "loud": str(loud).lower(), "lag": lag})


def reader_fault_counts() -> tuple[int, int, int]:
    """How many lines the planted fault killed, how many hook runs it held back and across how
    many frames past the first; -1 each when it does not answer."""
    r = call("lua", read_only=True, script=(
        'local K = _G.mcp_reader_fault or {fired = -1, lagged = -1, held = -1}\n'
        'print(string.format("fault %d %d %d", K.fired, K.lagged, K.held))'))
    m = re.search(r"fault (-?\d+) (-?\d+) (-?\d+)", str(r.get("output") or ""))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (-1, -1, -1)
