-- Reads placement vectors on stdin and prints each line again as the placement functions
-- compute it, for the test to compare with what was read.
local function words(line)
  local out = {}
  for word in line:gmatch("%S+") do
    out[#out + 1] = word
  end
  return out
end

local function join(list)
  local out = {}
  for _, p in ipairs(list) do
    out[#out + 1] = p[1] .. "," .. p[2]
  end
  return table.concat(out, " ")
end

for line in io.lines() do
  local w = words(line)
  if w[1] == "constants" then
    print(
      string.format(
        "constants band_divisor=%d columns=%d rows=%d margin=%d consecutive=%d start=%s sample_s=%g",
        BAND_DIVISOR,
        COLUMNS,
        ROWS,
        MARGIN,
        CONSECUTIVE,
        START,
        SAMPLE_S
      )
    )
  elseif w[1] == "points" then
    local top, bottom = band_points(tonumber(w[2]), tonumber(w[3]))
    print(string.format("points %s %s top %s bottom %s", w[2], w[3], join(top), join(bottom)))
  elseif w[1] == "score" then
    local colours = {}
    for i = 2, #w - 2 do
      colours[#colours + 1] = tonumber(w[i], 16)
    end
    print("score " .. table.concat(w, " ", 2, #w - 2) .. " = " .. band_score(colours))
  elseif w[1] == "walk" then
    local band, streak, bands, eq = w[2], 0, {}, 3
    while w[eq] ~= "=" do
      eq = eq + 1
    end
    for i = 3, eq - 1 do
      local top, bottom = w[i]:match("(%d+)/(%d+)")
      band, streak = band_step(band, streak, tonumber(top), tonumber(bottom))
      bands[#bands + 1] = band
    end
    print(
      "walk " .. w[2] .. " " .. table.concat(w, " ", 3, eq - 1) .. " = " .. table.concat(bands, " ")
    )
  end
end
