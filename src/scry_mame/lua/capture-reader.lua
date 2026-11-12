-- A write capture's block reader.
local width, off = __SCRY_width__, __SCRY_off__
--- __SCRY_source__
local fmt = string.rep("%02x", width)
