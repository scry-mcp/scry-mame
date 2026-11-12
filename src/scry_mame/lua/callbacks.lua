-- Windows' `rename` refuses an existing target: `replace` takes it away first, so a reader meets
-- the dump whole or absent, never the first one for ever.
-- No varargs in `guarded`: a tap is the hot path. The first error is cut to printable ASCII on
-- one line so the `e` line reads back whole.
local function fault(t, err)
  t.errors = (t.errors or 0) + 1
  if t.first_error == nil then
    t.first_error =
      string.sub((tostring(err):gsub("[^\32-\126]+", " ")), 1, __SCRY_first_error_max__)
  end
  t.dirty = true
end
local function replace(tmp, path)
  if not os.rename(tmp, path) then
    os.remove(path)
    assert(os.rename(tmp, path))
  end
end
local function guarded(t, f)
  return function(a, b, c)
    local ok, err = pcall(f, a, b, c)
    if not ok then
      fault(t, err)
    end
  end
end
local function opened(it, f)
  if f ~= nil then
    it.handles[#it.handles + 1] = f
  end
  return f
end
local function dump_guarded(it, dump, fr)
  it.handles = {}
  local ok, err = pcall(dump, it, fr)
  for _, h in ipairs(it.handles) do
    if io.type(h) == "file" then
      pcall(h.close, h)
    end
  end
  it.handles = nil
  if ok then
    it.dump_failing = nil
  elseif not it.dump_failing then
    it.dump_failing = true
    fault(it, err)
    manager.machine:logerror(
      string.format(
        "%s %s %s\n",
        __SCRY_dump_failed__,
        tostring(it.id),
        (tostring(err):gsub("[^\32-\126]+", " "))
      )
    )
  end
end
local function dump_at_stops(T, dump, before)
  emu.register_periodic(function()
    local d = manager.machine.debugger
    if d == nil or d.execution_state ~= "stop" then
      return
    end
    if before ~= nil then
      before()
    end
    local fr = __SCRY_no_frame__
    for _, scr in pairs(manager.machine.screens) do
      fr = scr:frame_number()
      break
    end
    for _, it in pairs(T.items) do
      dump_guarded(it, dump, fr)
    end
  end)
end
