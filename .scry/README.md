# `.scry/`

This repository's run recipes: what it declares about how its boards run, so a session can boot one without composing `start`'s arguments by hand.

SCRY is a set of MCP servers that let an assistant run a program in an emulator and inspect it
live. This folder is what this repository declares for it: how the program starts and, where it
has them, what its screens look like and a session that drives it.

## How to start

Call the `mame` server's `start` tool with a recipe's name: `start(profile="<name>")`. An argument in the same call wins over the recipe's. A recipe's paths resolve against the directory holding `.scry/`, and what would be this machine's path is a [placeholder](https://github.com/scry-mcp/scry-core/blob/main/docs/store-paths.md).

## Recipes

A recipe is the arguments of `start`, so a session boots a program without composing them by hand.

- `free` (`start/free.json`): a free set from `MAME_TEST_ROMS`, its system and reference image given by the call.
- `m68k-dual-alt` (`start/m68k-dual-alt.json`): the bench's `m68k-dual-alt` board (`rltennis`).
- `m68k-dual` (`start/m68k-dual.json`): the bench's `m68k-dual` board (`radendur`) with its symbol table.
- `v30-alt` (`start/v30-alt.json`): the bench's `v30-alt` board (`speedf`) on the shared MAME.
- `v30` (`start/v30.json`): the bench's `v30` board (`lineup`) on the shared MAME.

The board recipes name their paths through `MAME_LIVE_BENCH`, which the live tier exports with `~/.local/share/scry-bench/mame` as its default and a private copy overrides. Each recipe spells the directory and system its bench's `identity.json` declares; a bench that renames either declares a store of its own. `v30`, `v30-alt` and `free` name the executable through `MAME_BINARY`, the one MAME the games are developed on.

`free` names its sets through `MAME_TEST_ROMS`; the reference image of a free set is unpacked per run, so the call gives `system`, `reference_rom`, `reference_addr` and `reference_base`. Given those, `free_boot("circus", ...)` keeps the call's own system and reference image.

---

This page is rendered by the servers' `promote` from `about.json` and the files beside it; edit
those, never this page. To render it by hand, run `uv run python -m scry_core.scry_readme
<this repository>` from a scry-core checkout.
