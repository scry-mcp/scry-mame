local id, trig = __SCRY_id__, __SCRY_trig__
local head, rows = __SCRY_head__, __SCRY_rows__
--- __SCRY_bind_cpu__
local tsp = cpu.spaces[__SCRY_trigger_space__]
local curpc = cpu.state["CURPC"]
--- __SCRY_reader__
local screen = nil
for _, scr in pairs(manager.machine.screens) do
  screen = scr
  break
end
--- __SCRY_beam__
--- __SCRY_remove_old__
local t = {
  id = id,
  head = head,
  rows_path = rows,
  rows = 0,
  overflow_rows = 0,
  pending = {},
  npending = 0,
  errors = 0,
  seq = 0,
  dumped_frame = __SCRY_no_frame__,
  dirty = true,
  data_width = tsp.data_width,
  endianness = tsp.endianness,
  cpu = cpu.tag,
}
if old ~= nil then
  for _, k in ipairs({
    "rows",
    "overflow_rows",
    "pending",
    "npending",
    "errors",
    "first_error",
    "seq",
  }) do
    t[k] = old[k]
  end
end
if old == nil then
  os.remove(head)
  os.remove(head .. ".tmp")
  os.remove(rows)
end
local nb = tsp.data_width // 8
local lo = trig - (trig % nb)
local lane = trig - lo
local shift = tsp.endianness == "big" and (nb - 1 - lane) * 8 or lane * 8
t.tap = tsp:__SCRY_install__(
  lo,
  lo + nb - 1,
  "mcp_capture_" .. id,
  guarded(t, function(offset, data, mask)
    if ((mask >> shift) & 0xff) == 0 then
      return
    end
    if t.rows >= __SCRY_rows_max__ then
      t.overflow_rows = t.overflow_rows + 1
      t.dirty = true
      return
    end
    local now = manager.machine.time
    --- __SCRY_block__
    -- a row is counted once it is kept: a body that raised half-way leaves no hole in the file
    local n = t.npending + 1
    t.pending[n] = string.format(
      "r %d %d %d %d.%018d %x %x %x ",
      t.rows + 1,
      screen and screen:frame_number() or __SCRY_no_frame__,
      beam_line(),
      now.seconds,
      now.attoseconds,
      curpc.value,
      data,
      mask
    ) .. __SCRY_block_text__
    t.npending, t.rows, t.dirty = n, t.rows + 1, true
  end)
)
T.items[id] = t
--- __SCRY_dumper__
print(
  string.format("%s installed tally_id=%s trigger=%x ", __SCRY_answer__, id, trig)
    .. string.format("data_width=%d endianness=%s cpu=%s", tsp.data_width, tsp.endianness, cpu.tag)
)
