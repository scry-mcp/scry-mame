# Fixtures

A fixture is named by the case it covers, the board, the cpu, the shape it holds, never by the
program it was captured from. The boards this tree runs are labelled by what they are:
`m68k-dual` (two 68000s, a RAMDAC, a blitter) and `v30` (a single V30), each with an `-alt` twin
that is a second board of the same kind with its own edge to cover.

A set from MAME's own free sets, or a well-known set of a collection, may be named, since a set's
name is MAME's public information; a test that needs a collection set says which set and never
where to get it.

A directory's PROVENANCE, where it has one, says how its files were captured.

`console.stdout` and `console-error.log` are one session on `m68k-dual` through the server, its
console's output from the first chunk on and the error log's `[luaengine]` lines: a probe, a
script that raises, 300 frames run, `input` on `:P1` `Coin 1`, the same on a field the port lacks,
`record` of 30 frames and `throttle(on=False)`. They are re-captured whenever a script under
`src/scry_mame/lua/` that they hold changes, since a test finds the chunk the server sends in them.
`console-0288.stdout` is the same session on MAME 0.288, kept for the raised chunk's sentinel,
which that console printed twice.
