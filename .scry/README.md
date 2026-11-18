# `.scry/`

This repository's start profiles: how each of its test boards starts, so a session can boot one without composing `start`'s arguments by hand.

SCRY is a set of MCP servers that let an assistant run a program in an emulator and inspect it
live. This folder is what this repository keeps for it: how the program starts. Where it has
them, it also holds what its screens look like and a list of steps that drives it.

## How to start

Call the `mame` server's `start` tool with a start profile's name: `start(profile="<name>")`. An argument in the same call wins over the profile's. A profile's paths resolve against the directory holding `.scry/`, and what would be this machine's path is a [placeholder](https://github.com/scry-mcp/scry-core/blob/main/docs/store-paths.md).

## Start profiles

A start profile is a saved set of `start` arguments, so a session boots a program without composing them by hand.

- `free` (`start/free.json`): a free set from `MAME_TEST_ROMS`, its system and reference image given by the call.
- `m68k-dual-alt` (`start/m68k-dual-alt.json`): the `m68k-dual-alt` test board (`rltennis`).
- `m68k-dual` (`start/m68k-dual.json`): the `m68k-dual` test board (`radendur`) with its symbol table.
- `v30-alt` (`start/v30-alt.json`): the `v30-alt` test board (`speedf`) on the shared MAME.
- `v30` (`start/v30.json`): the `v30` test board (`lineup`) on the shared MAME.

The board profiles name their paths through `MAME_LIVE_BENCH`, the folder of test programs. With it unset, the tests against a real emulator refuse every board by that name.

Each profile spells the directory and the system its board's `identity.json` gives. A folder that renames either keeps a `.scry/` of its own.

`v30`, `v30-alt` and `free` name the executable through `MAME_BINARY`, the one MAME the games are developed on.

`free` names its sets through `MAME_TEST_ROMS`. The reference image of a free set is unpacked per run, so the call gives `system`, `reference_rom`, `reference_addr` and `reference_base`, and those win over the profile's.

---

This page is rendered by the servers' `promote` from `about.json` and the files beside it; edit
those, never this page. To render it by hand, run `uv run python -m scry_core.scry_readme
<this repository>` from a scry-core checkout.
