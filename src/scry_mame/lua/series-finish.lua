local t = MCP_SERIES or {}
if t.sub ~= nil then
  t.sub:unsubscribe()
  t.sub = nil
end
MCP_SERIES = nil
print(
  string.format(
    "MCP_SERIES_DONE kept=%d lost=%s errors=%d first_error=%s",
    t.kept or 0,
    table.concat(t.lost or {}, ","),
    t.errors or 0,
    (t.first_error or ""):gsub("\n", " ")
  )
)
