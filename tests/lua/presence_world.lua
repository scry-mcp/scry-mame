-- A fake MAME world for the presence drawer: the engine's names, a clock the scenario sets, and a
-- UI container that records what is drawn as one line per primitive.
local drawn, clock, frame_done = {}, 0, nil
local pixels, size, turn = {}, { 320, 200 }, { 0, false, false }

local function show(...)
  local out = {}
  for i = 1, select("#", ...) do
    out[i] = tostring((select(i, ...)))
  end
  return table.concat(out, " ")
end
local container = {
  draw_box = function(_, ...)
    drawn[#drawn + 1] = "box " .. show(...)
  end,
  draw_text = function(_, ...)
    drawn[#drawn + 1] = "text " .. show(...)
  end,
}
local screen = {
  pixels = function()
    local w, h = size[1], size[2]
    local parts = {}
    for y = 0, h - 1 do
      for x = 0, w - 1 do
        parts[#parts + 1] = string.pack("<I4", pixels[y * w + x] or 0)
      end
    end
    return table.concat(parts), w, h
  end,
  orientation = function()
    return table.unpack(turn)
  end,
}
emu = {
  register_frame_done = function(fn)
    frame_done = fn
  end,
  osd_ticks = function()
    return math.floor(clock * 1000)
  end,
  osd_ticks_per_second = function()
    return 1000
  end,
}
manager = {
  ui = {
    line_height = 0.04,
    get_string_width = function(_, text)
      return #text * 0.01
    end,
  },
  machine = {
    logerror = function(_, text)
      drawn[#drawn + 1] = "logerror " .. text
    end,
    debugger = { execution_state = "run" },
    screens = { screen },
    render = { ui_container = container, ui_target = { width = 1000, height = 500 } },
  },
}

-- The scenario's tools: `put` writes the state file, `frame` draws one frame at `t` seconds
-- and returns its primitives, `paint` colours a guest pixel, `halt` stops or runs the machine.
function put(path, text)
  local f = assert(io.open(path, "w"))
  f:write(text)
  f:close()
end
function frame(t)
  clock, drawn = t, {}
  frame_done()
  return drawn
end
function paint(x, y, colour)
  pixels[y * size[1] + x] = colour
end
function resize(w, h)
  size = { w, h }
end
function orient(angle, flip_x, flip_y)
  turn = { angle, flip_x, flip_y }
end
function halt(stopped)
  manager.machine.debugger.execution_state = stopped and "stop" or "run"
end
function out(lines)
  for _, line in ipairs(lines) do
    print(line)
  end
end
function shot(t)
  out(frame(t))
  print("--")
end
