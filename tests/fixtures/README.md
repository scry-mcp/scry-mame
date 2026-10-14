# Fixtures

A fixture is named by the case it covers, the board, the cpu, the shape it holds, never by the
program it was captured from. The boards this tree runs are labelled by what they are:
`m68k-dual` (two 68000s, a RAMDAC, a blitter) and `v30` (a single V30), each with an `-alt` twin
that is a second board of the same kind with its own edge to cover.

A set from MAME's own free sets, or a well-known set of a collection, may be named, since a set's
name is MAME's public information; a test that needs a collection set says which set and never
where to get it.

A directory's PROVENANCE, where it has one, says how its files were captured.
