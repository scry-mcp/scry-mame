-- The placement rule of `scry_core.placement`: which band, top or bottom, shows less of the
-- picture, so the captions go in the other. Integers only, so every renderer computes alike;
-- the test replays scry-core's placement_vectors.txt through these functions.
local BAND_DIVISOR, COLUMNS, ROWS = __SCRY_divisor__, __SCRY_columns__, __SCRY_rows__
local MARGIN, CONSECUTIVE, START, SAMPLE_S =
  __SCRY_margin__, __SCRY_consecutive__, __SCRY_start__, __SCRY_sample_s__

local function band_points(width, height)
  local band = math.max(1, height // BAND_DIVISOR)
  local xs, ys = {}, {}
  for i = 0, COLUMNS - 1 do
    xs[#xs + 1] = (2 * i + 1) * width // (2 * COLUMNS)
  end
  for j = 0, ROWS - 1 do
    ys[#ys + 1] = (2 * j + 1) * band // (2 * ROWS)
  end
  local top, bottom = {}, {}
  for _, y in ipairs(ys) do
    for _, x in ipairs(xs) do
      top[#top + 1] = { x, y }
      bottom[#bottom + 1] = { x, height - band + y }
    end
  end
  return top, bottom
end

local function band_score(colours)
  local counts, most = {}, 0
  for _, c in ipairs(colours) do
    counts[c] = (counts[c] or 0) + 1
    most = math.max(most, counts[c])
  end
  return #colours - most
end

local function band_step(band, streak, top, bottom)
  local here, other = bottom, top
  if band == "top" then
    here, other = top, bottom
  end
  if here - other < MARGIN then
    return band, 0
  end
  if streak + 1 < CONSECUTIVE then
    return band, streak + 1
  end
  return band == "top" and "bottom" or "top", 0
end
