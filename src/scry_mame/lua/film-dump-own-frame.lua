-- A film's frame is its screen's.
dump_at_stops(T, function(it)
  local fr = it.frame()
  if it.dirty or it.dumped_frame ~= fr then
    it.dump(fr)
  end
end)
