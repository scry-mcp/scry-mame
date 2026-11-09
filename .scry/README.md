# `.scry/`: this repository's run recipes

What this repository declares about how its boards run, so a session can boot one without
composing `start`'s arguments by hand. The server reads it; nothing here is written by a tool.

    .scry/
      README.md             this page
      start/<name>.json     a run recipe: `start`'s arguments, in the `scry-start/1` format

`maps/` and `perform/` hold a screen map and a `perform` document when this repository has one.

## The recipes

| name | boots |
| --- | --- |
| `m68k-dual` | the bench's `m68k-dual` board (`radendur`) with its symbol table |
| `m68k-dual-alt` | the bench's `m68k-dual-alt` board (`rltennis`) |
| `v30` | the bench's `v30` board (`lineup`) on the shared MAME |
| `v30-alt` | the bench's `v30-alt` board (`speedf`) on the shared MAME |
| `free` | a free set from `MAME_TEST_ROMS`, its system and reference image given by the call |

The four boards name their paths through `MAME_LIVE_BENCH`, which the live tier exports with
`~/.local/share/scry-bench/mame` as its default and a private copy overrides. Each recipe
spells the directory and system its bench's `identity.json` declares; a bench that renames
either declares a store of its own. `v30`, `v30-alt`
and `free` name the executable through `MAME_BINARY`, the one MAME the games are developed on.
`free` names its sets through `MAME_TEST_ROMS`; the reference image of a free set is unpacked
per run, so the call gives `system`, `reference_rom`, `reference_addr` and `reference_base`.

## How a path is written

Every recipe resolves against one base, the directory holding `.scry/`, so a relative path is
relative to this repository. What a tracked file must not carry, a host path, is written as a
[placeholder](https://github.com/scry-mcp/scry-core/blob/main/docs/store-paths.md).

## The caller wins

A recipe fills only what the call does not give, so `boot(symbols=None)` drops the board's
symbol table and `free_boot("circus", ...)` keeps the call's own system and reference image.
The reply's `profile` block names the file and every key it supplied.

## What stays out

A recipe declares how a board starts: paths, arguments, how long a boot waits. What a board's
trace means (which stop serves a case, which palette a pen takes, what an address proves) stays
in this repository's rules and its tests, because only this repository holds the gate that keeps
it true.
