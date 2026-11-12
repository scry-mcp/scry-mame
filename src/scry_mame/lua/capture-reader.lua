-- What reads the block a write captures; a read capture takes no block.
local width, off = __SCRY_width__, __SCRY_off__
--- __SCRY_source__
local fmt = string.rep("%02x", width)
