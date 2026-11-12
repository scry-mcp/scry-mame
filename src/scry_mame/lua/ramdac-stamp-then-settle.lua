-- Stamp the park for `stop` writes.
dump_at_stops(T, T.settle, function()
  local now = manager.machine.time
  T.ps, T.pa = now.seconds, now.attoseconds
end)
