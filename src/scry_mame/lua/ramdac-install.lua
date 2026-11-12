-- Installing again over the same id carries the state across, as a capture's install does,
-- because the console reruns a chunk now and then.
-- WHO WROTE, and why it takes two signals. A write the debugger makes (`ramdac.DEBUGGER_NOTE`
-- says who that is) reaches the tap with `execution_state` at `stop` and `CURPC` where the machine
-- stands, which is no writer. But `stop` alone is not enough: an asynchronous stop (a
-- frame's end) is requested before the cpu reaches the instruction it parks at, so the game's last
-- instruction before it writes at `stop` too. What tells them apart is the machine's time, which does
-- not move while the machine is parked: a `stop` write is held undecided with its time, and when the
-- machine parks (the periodic hook, at the top of the debugger's wait loop, or a chunk's `dump_lua`)
-- it is the debugger's if its time is the parked time, the game's if earlier. A chunk's own write
-- lands before the periodic has stamped that stop, which is why such a write waits for the park; a
-- write through the stub comes after the stamp and the stub then answers packet after packet without
-- the hook running again, so that one is decided at once, against the stamp.
local id = __SCRY_id__
local ip, dp, base = __SCRY_ip__, __SCRY_dp__, __SCRY_base__
local auto, pmask = __SCRY_auto__, __SCRY_pmask__
local dbg = manager.machine.debugger
--- __SCRY_bind_cpu__
local sp = cpu.spaces[__SCRY_space__]
local curpc = cpu.state["CURPC"]
local screen = nil
for _, scr in pairs(manager.machine.screens) do
  screen = scr
  break
end
--- __SCRY_beam__
--- __SCRY_guards__
--- __SCRY_remove_old__
local t = old
  or {
    id = id,
    head = __SCRY_head__,
    rows_path = __SCRY_rows__,
    n = 0,
    total = 0,
    index_writes = 0,
    unsynced = 0,
    desyncs = 0,
    rows = 0,
    overflow_rows = 0,
    pending = {},
    npending = 0,
    seq = 0,
    dumped_frame = __SCRY_no_frame__,
    dirty = true,
    sync = __SCRY_synced__,
    idx = 0,
    slot = 0,
    pens = {},
    notifiers = 0,
    undecided = {},
    partial = 0,
    errors = 0,
    data_width = sp.data_width,
    endianness = sp.endianness,
    cpu = cpu.tag,
  }
t.data_width, t.endianness, t.cpu = sp.data_width, sp.endianness, cpu.tag
local function frame()
  return screen and screen:frame_number() or __SCRY_no_frame__
end
local function by()
  if dbg == nil or dbg.execution_state ~= "stop" then
    return "g"
  end
  local now = manager.machine.time
  return (now.seconds == T.ps and now.attoseconds == T.pa) and "d" or "?"
end
local function log(fmt, ...)
  if t.rows >= __SCRY_rows_max__ then
    t.overflow_rows = t.overflow_rows + 1
    return nil
  end
  -- a row is counted once it is kept, as a capture's is; it ends with the beam line and the
  -- emulated time of its write, AFTER the fields the writer's `gsub` below matches by position
  local n = t.npending + 1
  local now = manager.machine.time
  t.pending[n] = string.format(fmt, ...)
    .. string.format(" %d %d %018d", beam_line(), now.seconds, now.attoseconds)
  t.npending, t.rows = n, t.rows + 1
  return n
end
local function undecided(row, pen)
  local now = manager.machine.time
  t.undecided[#t.undecided + 1] = {
    row = row,
    pen = pen,
    n = t.n,
    s = now.seconds,
    a = now.attoseconds,
  }
end
local nb = sp.data_width // 8
local function desync(why)
  t.sync, t.dirty = false, true
  t.desyncs, t.n = t.desyncs + 1, t.n + 1
  log("x %d %d %s", t.n, frame(), why)
end
--- __SCRY_taps__
local subs = {}
if emu.add_machine_reset_notifier ~= nil then
  subs[#subs + 1] = emu.add_machine_reset_notifier(guarded(t, function()
    desync("reset")
  end))
end
if emu.add_machine_post_load_notifier ~= nil then
  subs[#subs + 1] = emu.add_machine_post_load_notifier(guarded(t, function()
    desync("load")
  end))
end
t.notifiers = #subs
t.tap = {
  remove = function()
    for _, tap in ipairs(taps) do
      tap:remove()
    end
    for _, s in ipairs(subs) do
      s:unsubscribe()
    end
  end,
}
T.items[id] = t
if T.dump == nil then
  local function hx(v)
    return v == nil and "-" or string.format("%x", v)
  end
  T.decide = function(it)
    if #it.undecided == 0 then
      return
    end
    local now = manager.machine.time
    for _, u in ipairs(it.undecided) do
      local w = (u.s == now.seconds and u.a == now.attoseconds) and "d" or "g"
      if u.row ~= nil then
        it.pending[u.row] = it.pending[u.row]:gsub("^(%a %d+ %-?%d+ %x+) %?", "%1 " .. w, 1)
      end
      local p = u.pen ~= nil and it.pens[u.pen] or nil
      if p ~= nil and p.n == u.n then
        p.by = w
      end
    end
    it.undecided = {}
    it.dirty = true
  end
  T.dump = function(it, fr)
    T.decide(it)
    if it.npending > 0 then
      local r = opened(it, io.open(it.rows_path, "a"))
      if r == nil then
        return
      end
      r:write(table.concat(it.pending, "\n", 1, it.npending), "\n")
      r:close()
      it.pending, it.npending = {}, 0
    end
    it.seq = it.seq + 1
    local f = opened(it, io.open(it.head .. ".tmp", "w"))
    if f == nil then
      return
    end
    f:write(
      string.format(
        "%s %s seq=%d frame=%d total=%d index_writes=%d unsynced=%d ",
        __SCRY_header__,
        it.id,
        it.seq,
        fr,
        it.total,
        it.index_writes,
        it.unsynced
      )
    )
    f:write(
      string.format(
        "desyncs=%d rows=%d overflow_rows=%d notifiers=%d ",
        it.desyncs,
        it.rows,
        it.overflow_rows,
        it.notifiers
      )
    )
    f:write(
      string.format(
        "data_width=%d endianness=%s cpu=%s partial_writes=%d errors=%d\n",
        it.data_width,
        it.endianness,
        it.cpu,
        it.partial or 0,
        it.errors
      )
    )
    for pen, p in pairs(it.pens) do
      if p.w ~= nil then
        f:write(
          string.format(
            "w %x %d %d %d %x %s %x %x\n",
            pen,
            p.count,
            p.n,
            p.frame,
            p.pc,
            p.by,
            p.w,
            p.k
          )
        )
      else
        f:write(
          string.format(
            "p %x %d %d %d %x %s %s %s %s\n",
            pen,
            p.count,
            p.n,
            p.frame,
            p.pc,
            p.by,
            hx(p.c[1]),
            hx(p.c[2]),
            hx(p.c[3])
          )
        )
      end
    end
    if it.first_error ~= nil then
      f:write("e ", it.first_error, "\n")
    end
    f:write("end\n")
    f:close()
    replace(it.head .. ".tmp", it.head)
    it.dirty, it.dumped_frame = false, fr
  end
  T.settle = function(it, fr)
    T.decide(it)
    if it.dirty or it.dumped_frame ~= fr then
      T.dump(it, fr)
    end
  end
  T.dump_all = function()
    local fr = __SCRY_no_frame__
    for _, scr in pairs(manager.machine.screens) do
      fr = scr:frame_number()
      break
    end
    for _, it in pairs(T.items) do
      dump_guarded(it, T.dump, fr)
    end
  end
end
--- __SCRY_dumper__
print(
  string.format(
    "%s installed tally_id=%s index=%s data=%x ",
    __SCRY_answer__,
    id,
    ip and string.format("%x", ip) or "-",
    dp
  )
    .. string.format("data_width=%d endianness=%s cpu=%s", sp.data_width, sp.endianness, cpu.tag)
)
