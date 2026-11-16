local id = __SCRY_id__
local cpu = __SCRY_cpu__
local sp = cpu.spaces[__SCRY_space__]
local curpc = cpu.state["CURPC"]
local v = manager.machine.video
local scr = manager.machine.screens[__SCRY_screen__]
local dir = __SCRY_dir__
local trig, len, want, wpc = __SCRY_trig__, __SCRY_len__, __SCRY_want__, __SCRY_wpc__
local frames_max, keep = __SCRY_frames_max__, __SCRY_keep__
local changed = __SCRY_changed__
local checkable = __SCRY_checkable__
--- __SCRY_remove_old__
local same = old ~= nil and old.head == __SCRY_head__
local t = same and old
  or {
    id = id,
    head = __SCRY_head__,
    seq = 0,
    dirty = true,
    dumped_frame = __SCRY_no_frame__,
    judged = 0,
    met = 0,
    taken = 0,
    dropped = 0,
    dropped_first = -1,
    dropped_last = -1,
    lost_reset = 0,
    lost_load = 0,
    lost_skipped = 0,
    nhits = 0,
    hits = {},
    pend = nil,
    fresh = true,
    finished = false,
    first = -1,
    last = -1,
    judge_ticks = 0,
    picture_ticks = 0,
    prev = nil,
    baseline_frame = -1,
    baseline_value = -1,
    errors = 0,
  }
local said = ""
local print = function(s)
  said = s
end
--- __SCRY_capture__
local nb = sp.data_width // 8
local big = sp.endianness == "big"
local lo = trig - (trig % nb)
local shifts = {}
for i = 0, len - 1 do
  local lane = trig + i - lo
  shifts[i + 1] = big and (nb - 1 - lane) * 8 or lane * 8
end
local function frame()
  return scr:frame_number()
end
local function put(path, data)
  local f = io.open(path, "wb")
  if f == nil then
    return false
  end
  f:write(data)
  f:close()
  return true
end
local function publish(path, text)
  if put(path .. ".tmp", text) then
    replace(path .. ".tmp", path)
  end
end
t.frame = frame
t.dump = function(fr)
  t.seq = t.seq + 1
  publish(
    t.head,
    string.format(
      "%s %s seq=%d frame=%d judged=%d met=%d taken=%d ",
      __SCRY_header__,
      t.id,
      t.seq,
      fr,
      t.judged,
      t.met,
      t.taken
    )
      .. string.format(
        "dropped=%d dropped_first=%d dropped_last=%d lost_reset=%d lost_load=%d ",
        t.dropped,
        t.dropped_first,
        t.dropped_last,
        t.lost_reset,
        t.lost_load
      )
      .. string.format(
        "lost_skipped=%d pending=%d finished=%d first=%d last=%d ",
        t.lost_skipped,
        t.pend and 1 or 0,
        t.finished and 1 or 0,
        t.first,
        t.last
      )
      .. string.format(
        "judge_ticks=%d picture_ticks=%d tps=%d ",
        t.judge_ticks,
        t.picture_ticks,
        emu.osd_ticks_per_second()
      )
      .. string.format(
        "baseline_frame=%d baseline_value=%d errors=%d\n",
        t.baseline_frame,
        t.baseline_value,
        t.errors
      )
      .. (t.first_error ~= nil and "e " .. t.first_error .. "\n" or "")
      .. "end\n"
  )
  t.dirty, t.dumped_frame = false, fr
end
local tapped = true
local tap = sp:install_write_tap(
  lo,
  lo + nb - 1,
  "mcp_film_" .. id,
  guarded(t, function(_, data, mask)
    if t.finished then
      return
    end
    local val = 0
    for i = 1, len do
      local s = shifts[i]
      if ((mask >> s) & 0xff) == 0 then
        return
      end
      local b = (data >> s) & 0xff
      if big then
        val = (val << 8) | b
      else
        val = val | (b << (8 * (i - 1)))
      end
    end
    if changed then
      -- every write moves the previous value, whoever wrote it; the film's first is the baseline
      local before = t.prev
      t.prev = val
      if before == nil then
        t.baseline_frame, t.baseline_value = frame(), val
        return
      end
      if val == before then
        return
      end
    end
    if want ~= nil and val ~= want then
      return
    end
    local pc = curpc.value
    if wpc ~= nil and pc ~= wpc then
      return
    end
    t.nhits = t.nhits + 1
    if t.nhits <= __SCRY_hits_kept__ then
      t.hits[t.nhits] = string.format("h %x %x %d", pc, val, frame())
    end
  end)
)
local function untap()
  if tapped then
    tapped = false
    tap:remove()
  end
end
--- __SCRY_pens__
local function develop(fr)
  local p = t.pend
  t.pend = nil
  local k = t.taken + 1
  t.taken = k
  local base = dir .. "/frame-" .. k
  said = ""
  local ok, err = pcall(mcp_capture, base .. ".bin", true)
  if not ok then
    said = "MCP_FILM_ERROR " .. tostring(err)
  end
  put(base .. ".pens", p.pens)
  put(base .. ".snap", p.snap)
  publish(
    base .. ".txt",
    string.format(
      "MCP_FILM_FRAME k=%d frame=%d hits=%d read_at=%d " .. "skipped=%d\n",
      k,
      p.frame,
      p.nhits,
      fr,
      p.skipped
    )
      .. table.concat(p.hits, "\n")
      .. (#p.hits > 0 and "\n" or "")
      .. "said "
      .. said:gsub("\n", " ")
      .. "\nend\n"
  )
end
local function lost(field)
  if t.pend ~= nil then
    t.pend = nil
    t[field] = t[field] + 1
  end
  t.fresh, t.nhits, t.hits, t.dirty = true, 0, {}, true
end
local subs = {}
subs[#subs + 1] = emu.add_machine_frame_notifier(guarded(t, function()
  if t.finished then
    return
  end
  local t0 = emu.osd_ticks()
  local fr = frame()
  local drew = not v.skip_this_frame
  if t.pend ~= nil then
    if not drew then
      t.pend.skipped = t.pend.skipped + 1
    else
      develop(fr)
      local t1 = emu.osd_ticks()
      t.picture_ticks = t.picture_ticks + (t1 - t0)
      t0 = t1
      dump_guarded(t, function()
        t.dump(fr)
      end, fr)
    end
  end
  if t.fresh then
    t.fresh, t.nhits, t.hits = false, 0, {}
  elseif t.judged < frames_max then
    t.judged = t.judged + 1
    if t.first < 0 then
      t.first = fr
    end
    t.last, t.dirty = fr, true
    if t.nhits > 0 then
      t.met = t.met + 1
      if not drew then
        t.lost_skipped = t.lost_skipped + 1
      elseif t.taken < keep then
        local ok, snap = true, ""
        if checkable then
          ok, snap = pcall(function()
            return v:snapshot_pixels()
          end)
        end
        t.pend = {
          frame = fr,
          nhits = t.nhits,
          hits = t.hits,
          pens = pens(),
          snap = ok and snap or "",
          skipped = 0,
        }
      else
        t.dropped = t.dropped + 1
        if t.dropped_first < 0 then
          t.dropped_first = fr
        end
        t.dropped_last = fr
      end
      t.nhits, t.hits = 0, {}
    end
  end
  if t.judged >= frames_max and t.pend == nil then
    t.finished = true
    untap()
    dump_guarded(t, function()
      t.dump(fr)
    end, fr)
  end
  t.judge_ticks = t.judge_ticks + (emu.osd_ticks() - t0)
end))
if emu.add_machine_reset_notifier ~= nil then
  subs[#subs + 1] = emu.add_machine_reset_notifier(guarded(t, function()
    lost("lost_reset")
  end))
end
if emu.add_machine_post_load_notifier ~= nil then
  subs[#subs + 1] = emu.add_machine_post_load_notifier(guarded(t, function()
    lost("lost_load")
  end))
end
t.tap = {
  remove = function()
    untap()
    for _, s in ipairs(subs) do
      s:unsubscribe()
    end
  end,
}
T.items[id] = t
--- __SCRY_dumper__
_G.print(
  string.format("%s installed tally_id=%s trigger=%x ", __SCRY_answer__, id, trig)
    .. string.format("data_width=%d endianness=%s cpu=%s", sp.data_width, sp.endianness, cpu.tag)
)
