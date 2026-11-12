-- The Lua the server sends MAME (src/scry_mame/lua/), checked as the scripts are rendered:
-- most files are fragments that read the locals of the one they are composed into.
std = "lua54"
-- MAME's Lua engine; the server's own registries and the console's sentinel live in `_G`.
-- `manager` is written as well as read: `video.throttled`, `debugger.execution_state`.
read_globals = { "emu" }
globals = { "manager", "MCP_SERIES", "MCP_CAPTURE", "MCP_TALLY", "MCP_RAMDAC", "MCP_FILM" }
-- `for _, s in pairs(t) do first = s break end` takes a table's first value, on purpose.
-- The shared prelude (`callbacks.lua`) defines `opened` for the dumpers that open before they
-- write; a film composes its text first and never calls it.
ignore = { "512", "211/opened" }
-- A write tap's callback takes MAME's whole signature, whichever arguments it reads.
unused_args = false
-- StyLua owns the layout; a rendered line carries paths as long as the caller's.
max_line_length = false
