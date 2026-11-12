-- What both packed protocols share: the colour's bits (`store` reads `cmask`, so it is
-- declared first), the port's word, and the pen a colour write lands on.
local cmask = __SCRY_cmask__
local function word_lane(addr)
  local lo = addr - (addr % nb)
  return lo, (addr - lo) * 8, (1 << ((nb - (addr - lo)) * 8)) - 1
end
local dlo, dshift, dword = word_lane(dp)
local function unsynced(fr, pc, w, v, m)
  t.unsynced = t.unsynced + 1
  local row = log("w %d %d %x %s - %x %x", t.n, fr, pc, w, v, m)
  if w == "?" then
    undecided(row, nil)
  end
end
local function store(pen, v, m, fr, pc, w)
  local p = t.pens[pen]
  if p == nil then
    p = { w = 0, k = 0, count = 0 }
    t.pens[pen] = p
  end
  p.w, p.k = (p.w & ~m) | (v & m), p.k | m
  if (p.k & cmask) ~= cmask then
    t.partial = t.partial + 1
  end
  p.count, p.n, p.frame, p.pc, p.by = p.count + 1, t.n, fr, pc, w
  local row = log("w %d %d %x %s %x %x %x", t.n, fr, pc, w, pen, v, m)
  if w == "?" then
    undecided(row, pen)
  end
  if auto then
    t.idx = (t.idx + 1) & pmask
  end
end
