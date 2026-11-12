-- the park is stamped before any item settles: a `stop` write is decided against it
dump_at_stops(T, T.settle, function()
  local now = manager.machine.time
  T.ps, T.pa = now.seconds, now.attoseconds
end)
