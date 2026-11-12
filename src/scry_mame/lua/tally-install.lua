-- The tap covers whole bus words (MAME refuses an unaligned one) and keeps the writes that
-- land inside; `CURPC` is the writer's pc (`PC` is the prefetch). With no tap of the range,
-- a dump at `path` is a removed tap's and goes.
local id, first, last = __SCRY_id__, __SCRY_first__, __SCRY_last__
local path = __SCRY_path__
--- __SCRY_bind_cpu__
local sp = cpu.spaces[__SCRY_space__]
--- __SCRY_remove_old__
local t = {
  id = id,
  path = path,
  total = 0,
  reads = 0,
  values = {},
  nvalues = 0,
  pcs = {},
  npcs = 0,
  overflow_values = 0,
  overflow_pcs = 0,
  errors = 0,
  dirty = true,
  seq = 0,
  dumped_frame = __SCRY_no_frame__,
  data_width = sp.data_width,
  endianness = sp.endianness,
  cpu = cpu.tag,
}
if old ~= nil then
  for _, k in ipairs({
    "total",
    "reads",
    "values",
    "nvalues",
    "pcs",
    "npcs",
    "overflow_values",
    "overflow_pcs",
    "errors",
    "first_error",
    "seq",
  }) do
    t[k] = old[k]
  end
end
if old == nil then
  os.remove(path)
  os.remove(path .. ".tmp")
end
local nb = sp.data_width // 8
local big = sp.endianness == "big"
local lo, hi = first - (first % nb), last + (nb - 1 - (last % nb))
local aligned = lo == first and hi == last
local function lands(offset, mask)
  for i = 0, nb - 1 do
    local shift = big and (nb - 1 - i) * 8 or i * 8
    if ((mask >> shift) & 0xff) ~= 0 and offset + i >= first and offset + i <= last then
      return true
    end
  end
  return false
end
--- __SCRY_taps__
T.items[id] = t
--- __SCRY_dumper__
print(
  string.format("%s installed tally_id=%s first=%x last=%x ", __SCRY_answer__, id, first, last)
    .. string.format("data_width=%d endianness=%s cpu=%s", sp.data_width, sp.endianness, cpu.tag)
)
