"""The Lua the palette write log (`mame_ramdac`) runs inside MAME, for every kind of palette
port the manifest states (a RAMDAC, a latch, a sequence): a write tap on each of the entry's
ports, its protocol's state machine over them, the reset and state-load notifiers that
unsync it, and the dumper that writes the pens and the ordered rows to the scratch. What the log
means and how its files are read is `mame_ramdac`'s; this module composes the chunk, so the
dump and row lines written here and `mame_ramdac`'s parsers of them change together.

WHO WROTE, and why it takes two signals. A write the debugger makes (`mame_ramdac.DEBUGGER_NOTE`
says who that is) reaches the tap with `execution_state` at `stop` and `CURPC` where the machine
stands, which is no writer. But `stop` alone is not enough, measured: an asynchronous stop (a
frame's end) is requested before the cpu reaches the instruction it parks at, so the game's last
instruction before it writes at `stop` too. What tells them apart is the machine's time, which does
not move while the machine is parked: a `stop` write is held undecided with its time, and when the
machine parks (the periodic hook, at the top of the debugger's wait loop, or a chunk's `dump_lua`)
it is the debugger's if its time is the parked time, the game's if earlier. A chunk's own write
lands before the periodic has stamped that stop, which is why such a write waits for the park; a
write through the stub comes after the stamp and the stub then answers packet after packet without
the hook running again, so that one is decided at once, against the stamp.
"""

from __future__ import annotations

from pathlib import Path

import mame_callbacks as callbacks
import mame_capture as capture
import mame_manifest as mm
import mame_tap as mtap
import mame_transport as transport

REGISTRY = "MCP_RAMDAC"
HEADER = "MCP_RAMDAC"
NOTIFIERS = 2             # the reset one and the state-load one the chunk subscribes


_STAMP_THEN_SETTLE = """\
  -- the park is stamped before any item settles: a `stop` write is decided against it
  dump_at_stops(T, T.settle, function()
    local now = manager.machine.time
    T.ps, T.pa = now.seconds, now.attoseconds
  end)
"""


def install_script(log_id: str, r: mm.PalettePort, head: Path, rows: Path, cpu: str | None,
                   synced: bool = False) -> str:
    """The Lua that installs the log `log_id`: a tap on each port's bus word, the protocol's
    state machine over them (`_TAPS`), the reset and state-load notifiers, and the dumper.
    `synced` starts the index known at 0, which a `sequence` log armed before the machine ever
    executed may (`mame_ramdac.fresh`). Installing again over the same id carries the state
    across, as a capture's install does, because the console reruns a chunk now and then."""
    ip = "nil" if r.index_port is None else f"{r.index_port:#x}"
    return mtap.tap_prelude(REGISTRY) + f"""\
local id = {transport.lua_string(log_id)}
local ip, dp, base = {ip}, {r.data_port:#x}, {r.pen_base}
local auto, pmask = {"true" if r.auto_increment else "false"}, {r.pen_count - 1:#x}
{mtap.bound_cpu(cpu)}
local sp = cpu.spaces["{r.space}"]
local curpc = cpu.state["CURPC"]
local screen = nil
for _, scr in pairs(manager.machine.screens) do screen = scr break end
{capture.BEAM_LINE_LUA}{_GUARDS if r.packed() else ""}{mtap.REMOVE_OLD_TAP}
local t = old or {{id = id, head = {transport.lua_string(str(head))},
  rows_path = {transport.lua_string(str(rows))},
  n = 0, total = 0, index_writes = 0, unsynced = 0, desyncs = 0, rows = 0, overflow_rows = 0,
  pending = {{}}, npending = 0, seq = 0, dumped_frame = {callbacks.NO_FRAME}, dirty = true,
  sync = {"true" if synced else "false"}, idx = 0, slot = 0, pens = {{}}, notifiers = 0,
  undecided = {{}}, partial = 0, errors = 0,
  data_width = sp.data_width, endianness = sp.endianness, cpu = cpu.tag}}
t.data_width, t.endianness, t.cpu = sp.data_width, sp.endianness, cpu.tag
local function frame() return screen and screen:frame_number() or {callbacks.NO_FRAME} end
local function by()
  if dbg == nil or dbg.execution_state ~= "stop" then return "g" end
  local now = manager.machine.time
  return (now.seconds == T.ps and now.attoseconds == T.pa) and "d" or "?"
end
local function log(fmt, ...)
  if t.rows >= {capture.ROWS_MAX} then t.overflow_rows = t.overflow_rows + 1 return nil end
  -- a row is counted once it is kept, as a capture's is; it ends with the beam line and the
  -- emulated time of its write, AFTER the fields the writer's `gsub` below matches by position
  local n = t.npending + 1
  local now = manager.machine.time
  t.pending[n] = string.format(fmt, ...) .. string.format(" %d %d %018d", beam_line(),
    now.seconds, now.attoseconds)
  t.npending, t.rows = n, t.rows + 1
  return n
end
local function undecided(row, pen)
  local now = manager.machine.time
  t.undecided[#t.undecided + 1] = {{row = row, pen = pen, n = t.n, s = now.seconds,
                                   a = now.attoseconds}}
end
local nb = sp.data_width // 8
local function lane(addr)
  local lo = addr - (addr % nb)
  return lo, (sp.endianness == "big" and (nb - 1 - (addr - lo)) * 8 or (addr - lo) * 8)
end
local function desync(why)
  t.sync, t.dirty = false, true
  t.desyncs, t.n = t.desyncs + 1, t.n + 1
  log("x %d %d %s", t.n, frame(), why)
end
{_TAPS[r.protocol](r)}
local subs = {{}}
if emu.add_machine_reset_notifier ~= nil then
  subs[#subs + 1] = emu.add_machine_reset_notifier(guarded(t, function() desync("reset") end))
end
if emu.add_machine_post_load_notifier ~= nil then
  subs[#subs + 1] = emu.add_machine_post_load_notifier(guarded(t, function() desync("load") end))
end
t.notifiers = #subs
t.tap = {{remove = function()
  for _, tap in ipairs(taps) do tap:remove() end
  for _, s in ipairs(subs) do s:unsubscribe() end
end}}
T.items[id] = t
if T.dump == nil then
  local function hx(v) return v == nil and "-" or string.format("%x", v) end
  T.decide = function(it)
    if #it.undecided == 0 then return end
    local now = manager.machine.time
    for _, u in ipairs(it.undecided) do
      local w = (u.s == now.seconds and u.a == now.attoseconds) and "d" or "g"
      if u.row ~= nil then
        it.pending[u.row] = it.pending[u.row]:gsub("^(%a %d+ %-?%d+ %x+) %?", "%1 " .. w, 1)
      end
      local p = u.pen ~= nil and it.pens[u.pen] or nil
      if p ~= nil and p.n == u.n then p.by = w end
    end
    it.undecided = {{}}
    it.dirty = true
  end
  T.dump = function(it, fr)
    T.decide(it)
    if it.npending > 0 then
      local r = {callbacks.OPENED}(it, io.open(it.rows_path, "a"))
      if r == nil then return end
      r:write(table.concat(it.pending, "\\n", 1, it.npending), "\\n")
      r:close()
      it.pending, it.npending = {{}}, 0
    end
    it.seq = it.seq + 1
    local f = {callbacks.OPENED}(it, io.open(it.head .. ".tmp", "w"))
    if f == nil then return end
    f:write(string.format("{HEADER} %s seq=%d frame=%d total=%d index_writes=%d unsynced=%d ",
      it.id, it.seq, fr, it.total, it.index_writes, it.unsynced))
    f:write(string.format("desyncs=%d rows=%d overflow_rows=%d notifiers=%d ", it.desyncs,
      it.rows, it.overflow_rows, it.notifiers))
    f:write(string.format("data_width=%d endianness=%s cpu=%s partial_writes=%d errors=%d\\n",
      it.data_width, it.endianness, it.cpu, it.partial or 0, it.errors))
    for pen, p in pairs(it.pens) do
      if p.w ~= nil then
        f:write(string.format("w %x %d %d %d %x %s %x %x\\n", pen, p.count, p.n, p.frame, p.pc,
          p.by, p.w, p.k))
      else
        f:write(string.format("p %x %d %d %d %x %s %s %s %s\\n", pen, p.count, p.n, p.frame,
          p.pc, p.by, hx(p.c[1]), hx(p.c[2]), hx(p.c[3])))
      end
    end
    if it.first_error ~= nil then f:write("e ", it.first_error, "\\n") end
    f:write("end\\n")
    f:close()
    os.rename(it.head .. ".tmp", it.head)
    it.dirty, it.dumped_frame = false, fr
  end
  T.settle = function(it, fr)
    T.decide(it)
    if it.dirty or it.dumped_frame ~= fr then T.dump(it, fr) end
  end
  T.dump_all = function()
    local fr = {callbacks.NO_FRAME}
    for _, scr in pairs(manager.machine.screens) do fr = scr:frame_number() break end
    for _, it in pairs(T.items) do dump_guarded(it, T.dump, fr) end
  end
end
{mtap.register_dumper_once(_STAMP_THEN_SETTLE)}
print(string.format("{mtap.ANSWER_PREFIX} installed tally_id=%s index=%s data=%x ", id,
  ip and string.format("%x", ip) or "-", dp)
  .. string.format("data_width=%d endianness=%s cpu=%s", sp.data_width, sp.endianness, cpu.tag))"""


def _ramdac_taps(r: mm.PalettePort) -> str:
    """MAME's `ramdac_device`: an index byte write sets the index and sends the component
    counter to 0; a data byte write lands on component `order[counter]` of the indexed pen, and
    at three the counter returns to 0 and the index moves on when the device auto-increments."""
    slots = ", ".join(str(mm.COMPONENTS.index(c) + 1) for c in r.order)
    return f"""local comp = {{{slots}}}
local ilo, ishift = lane(ip)
local dlo, dshift = lane(dp)
local itap = sp:install_write_tap(ilo, ilo + nb - 1, "mcp_ramdac_i_" .. id,
    guarded(t, function(_, data, mask)
  if ((mask >> ishift) & 0xff) == 0 then return end
  local v = (data >> ishift) & 0xff
  t.n, t.index_writes = t.n + 1, t.index_writes + 1
  t.idx, t.slot, t.sync, t.dirty = v & pmask, 0, true, true
  local w = by()
  local row = log("i %d %d %x %s %x", t.n, frame(), curpc.value, w, v & pmask)
  if w == "?" then undecided(row, nil) end
end))
local dtap = sp:install_write_tap(dlo, dlo + nb - 1, "mcp_ramdac_d_" .. id,
    guarded(t, function(_, data, mask)
  if ((mask >> dshift) & 0xff) == 0 then return end
  local v = (data >> dshift) & 0xff
  local fr, pc, w = frame(), curpc.value, by()
  t.n, t.total, t.dirty = t.n + 1, t.total + 1, true
  if not t.sync then
    t.unsynced = t.unsynced + 1
    local row = log("d %d %d %x %s - - %x", t.n, fr, pc, w, v)
    if w == "?" then undecided(row, nil) end
    return
  end
  local pen, slot = base + t.idx, t.slot
  local p = t.pens[pen]
  if p == nil then p = {{c = {{}}, count = 0}} t.pens[pen] = p end
  p.c[comp[slot + 1]] = v
  p.count, p.n, p.frame, p.pc, p.by = p.count + 1, t.n, fr, pc, w
  local row = log("d %d %d %x %s %x %d %x", t.n, fr, pc, w, pen, slot, v)
  if w == "?" then undecided(row, pen) end
  slot = slot + 1
  if slot == 3 then
    slot = 0
    if auto then t.idx = (t.idx + 1) & pmask end
  end
  t.slot = slot
end))
local taps = {{itap, dtap}}"""


# A PACKED PORT is read as the bytes from its own address up to the end of its bus word, which
# is what a 16-bit port on a 16-bit bus is whole. That reading holds on a little-endian bus; on a
# big-endian one the port's first byte is the word's high one, so the install refuses there
# rather than log words it reads in the wrong order. And an index port in the data port's bus
# word would see every colour as an index write. Both are judged before the old tap goes, so a
# refused re-arm leaves the log it replaces in place.
_GUARDS = """if sp.endianness ~= "little" then
  error("a packed palette port is read little-endian, and this bus is " .. sp.endianness)
end
if ip ~= nil and ip - ip % (sp.data_width // 8) == dp - dp % (sp.data_width // 8) then
  error("the index port and the data port share a bus word, so each would see the other's writes")
end
"""
_PACKED = """local function word_lane(addr)
  local lo = addr - (addr % nb)
  return lo, (addr - lo) * 8, (1 << ((nb - (addr - lo)) * 8)) - 1
end
local dlo, dshift, dword = word_lane(dp)
local function unsynced(fr, pc, w, v, m)
  t.unsynced = t.unsynced + 1
  local row = log("w %d %d %x %s - %x %x", t.n, fr, pc, w, v, m)
  if w == "?" then undecided(row, nil) end
end
local function store(pen, v, m, fr, pc, w)
  local p = t.pens[pen]
  if p == nil then p = {w = 0, k = 0, count = 0} t.pens[pen] = p end
  p.w, p.k = (p.w & ~m) | (v & m), p.k | m
  if (p.k & cmask) ~= cmask then t.partial = t.partial + 1 end
  p.count, p.n, p.frame, p.pc, p.by = p.count + 1, t.n, fr, pc, w
  local row = log("w %d %d %x %s %x %x %x", t.n, fr, pc, w, pen, v, m)
  if w == "?" then undecided(row, pen) end
  if auto then t.idx = (t.idx + 1) & pmask end
end
"""


def _packed(r: mm.PalettePort) -> str:
    """What both packed protocols share: the colour's bits (`store` reads `cmask`, so it is
    declared first), the port's word, and the pen a colour write lands on."""
    return f"local cmask = {r.colour_mask():#x}\n" + _PACKED


def _latch_taps(r: mm.PalettePort) -> str:
    """v30-alt's `paldat_w`: a data word with a bit of `index_flag_mask` set sets the index
    to its low bits; any other word is a whole colour for the indexed pen (the driver takes no
    mask), and the index moves on when it auto-increments. The optional index port merges into
    the index under the write's mask (`paloff_w`'s `COMBINE_DATA`)."""
    index = "" if r.index_port is None else """local ilo, ishift, iword = word_lane(ip)
taps[#taps + 1] = sp:install_write_tap(ilo, ilo + nb - 1, "mcp_ramdac_i_" .. id,
    guarded(t, function(_, data, mask)
  local m = (mask >> ishift) & iword
  if m == 0 then return end
  local v = (data >> ishift) & iword
  local fr, pc, w = frame(), curpc.value, by()
  t.n, t.index_writes, t.dirty = t.n + 1, t.index_writes + 1, true
  if t.sync then
    t.idx = ((t.idx & ~m) | (v & m)) & pmask
  elseif (m & pmask) == pmask then
    t.idx, t.sync = v & pmask, true
  else
    desync("index_partial")
    return
  end
  local row = log("i %d %d %x %s %x", t.n, fr, pc, w, t.idx)
  if w == "?" then undecided(row, nil) end
end))
"""
    return _packed(r) + f"""local flag = {r.index_flag_mask or 0:#x}
local taps = {{}}
taps[1] = sp:install_write_tap(dlo, dlo + nb - 1, "mcp_ramdac_d_" .. id,
    guarded(t, function(_, data, mask)
  if (mask >> dshift) & dword == 0 then return end
  local v = (data >> dshift) & dword
  local fr, pc, w = frame(), curpc.value, by()
  t.n, t.dirty = t.n + 1, true
  if (v & flag) ~= 0 then
    t.index_writes, t.idx, t.sync = t.index_writes + 1, v & pmask, true
    local row = log("i %d %d %x %s %x", t.n, fr, pc, w, t.idx)
    if w == "?" then undecided(row, nil) end
    return
  end
  t.total = t.total + 1
  if not t.sync then unsynced(fr, pc, w, v, dword) return end
  store(base + t.idx, v, dword, fr, pc, w)
end))
""" + index


def _sequence_taps(r: mm.PalettePort) -> str:
    """v30's `twins_pal_w`: each data write merges into the pen at the offset under its mask
    (`COMBINE_DATA`), and the offset moves on; any write to the bus word of the index port
    (`porte_paloff0_w`) sends the offset back to 0."""
    return _packed(r) + """local ilo = ip - (ip % nb)
local taps = {}
taps[1] = sp:install_write_tap(ilo, ilo + nb - 1, "mcp_ramdac_i_" .. id, guarded(t, function()
  local fr, pc, w = frame(), curpc.value, by()
  t.n, t.index_writes, t.dirty = t.n + 1, t.index_writes + 1, true
  t.idx, t.sync = 0, true
  local row = log("i %d %d %x %s 0", t.n, fr, pc, w)
  if w == "?" then undecided(row, nil) end
end))
taps[2] = sp:install_write_tap(dlo, dlo + nb - 1, "mcp_ramdac_d_" .. id,
    guarded(t, function(_, data, mask)
  local m = (mask >> dshift) & dword
  if m == 0 then return end
  local v = (data >> dshift) & dword
  local fr, pc, w = frame(), curpc.value, by()
  t.n, t.total, t.dirty = t.n + 1, t.total + 1, true
  if not t.sync then unsynced(fr, pc, w, v, m) return end
  store(base + t.idx, v, m, fr, pc, w)
end))
"""


_TAPS = {"ramdac": _ramdac_taps, "latch": _latch_taps, "sequence": _sequence_taps}


def dump_lua() -> str:
    """The line a chunk ends with to write every log's dump at the instant it read the screen,
    so the pen, its colour and its last write are one state."""
    return f"local R = _G.{REGISTRY} if R ~= nil and R.dump_all ~= nil then R.dump_all() end"
