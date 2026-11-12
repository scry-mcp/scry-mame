local mem = manager.machine.memory
local blk = mem.__SCRY_blocks__[__SCRY_tag__]
if blk == nil then
  error("no " .. __SCRY_kind__ .. " named " .. __SCRY_tag__)
end
