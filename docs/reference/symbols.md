# The Symbols tools

A symbol table gives names to the addresses of a program: its routines and its variables. With one loaded, a tool that takes an address takes a name as well.

Here `start` loads the table, from the file its `symbols` argument names, one table per cpu. `symbols_find` looks a name or an address up in it.

<!-- scry-reference:begin symbols_find -->
## `symbols_find`

Find a symbol's address by its name, or find which symbol an address falls in.

```text
symbols_find(name="", linear=null, limit=10, cpu="")
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, started with the symbol file of the reference's own run, `docs/reference/tour/gridlee-symbols.yaml`.

Ask:

> Which symbols start with "cred", and where are they?

Call:

```text
symbols_find(name="cred")
```

Reply, 3 of 7 fields:

```json
{
  "summary": "symbols_find cred: 2 matches",
  "symbols": [
    {"name": "credits", "addr": "0x0000042b", "memory": "ram"},
    {"name": "credits_bcd", "addr": "0x0000042c", "memory": "ram"}
  ],
  "truncated": false
}
```

No symbol is named `cred`, so the two that start with it are listed: the credits and their BCD copy, one byte apart. `memory` says both sit in RAM.

<details><summary>The whole reply</summary>

```json
{
  "summary": "symbols_find cred: 2 matches",
  "status": "ok",
  "query": "cred",
  "cpu": ":maincpu",
  "symbols_total": 2,
  "symbols": [
    {"name": "credits", "addr": "0x0000042b", "memory": "ram"},
    {"name": "credits_bcd", "addr": "0x0000042c", "memory": "ram"}
  ],
  "truncated": false
}
```

</details>

### Arguments

- `name` (string, default `""`): The symbol to look up, case ignored. An exact match wins; with none, every symbol that starts with it is listed, by address.
- `linear` (integer or string, optional): An address as the running program uses it, as `disassemble` shows it. The reply is the nearest symbol at or below it.
- `limit` (integer (>= 1, <= 50), default `10`): How many symbols a name lookup lists: 1 to 50. Left out, 10.
- `cpu` (string, default `""`): The cpu whose table is read. Left empty, the one the debugger is showing.

### What comes back

- `symbols`: By name: the first `limit` matches, each with its `name` as the file spells it, its `addr` and its `memory`.
- `symbols_total`: By name: how many symbols matched.
- `truncated`: By name: `true` when more matched than `symbols` lists.
- `name`: By address: the nearest symbol at or below the address, with its own `addr`.
- `delta`: By address: how many bytes the address is past that symbol's start.
- `memory`: What kind of memory the symbol sits in: `ram`, `rom`, `latch`, `handlers`, `unmapped` or `unknown`.

<details><summary>All 10 reply fields</summary>

- `addr` (string)
- `cpu` (string)
- `delta` (integer)
- `linear` (string)
- `memory` (string)
- `name` (string)
- `query` (string)
- `symbols` (array)
- `symbols_total` (integer)
- `truncated` (boolean)

</details>

### What it refuses

- Both `name` and `linear`, or neither: one question per call (`bad_argument`).
- A session started with no symbol file for that cpu (`no_channel`).
- An address below every symbol of the table (`unknown_ref`).

### Why it works this way

`memory` tells you, before you set one, that a watch for changes on the ROM copy of a variable can never fire. It costs the debugger's `map` command one question per symbol, hence the limit of 50.

The table is the server's own copy, not read from the machine, so the lookup answers while the program runs. While it runs `memory` is `unknown`, and `note` says why.

`linear` is a run-time address, after `start`'s `bases` moved the data to where the board keeps it. A linker map's column is before that, and finds a plausible symbol with an absurd `delta`. `delta` is a distance past the symbol's start because the table holds no sizes.

<details><summary>More on why</summary>

| `memory` | meaning |
|---|---|
| `ram` | Read and written as plain memory: a watch for changes fires. |
| `rom` | Never written: code, or the ROM copy of a variable. |
| `latch` | Written through a handler, read nowhere: `read_memory` answers zeros; `read_block` reads it when the map entry keeps a share. |
| `handlers` | Read and written through handlers: readable, not plain memory. |
| `unmapped` | Nothing answers there. |
| `unknown` | The program is running, or `map` named no side. |

</details>

### Related tools

- [`read_memory`](read.md#read_memory)
- [`read_block`](read.md#read_block)
- [`watch_add`](breakpoints.md#watch_add)
- [`breakpoint_at`](breakpoints.md#breakpoint_at)
- [`disassemble`](read.md#disassemble)
- [`machine_map`](machine.md#machine_map)

<details><summary>The contract your client receives</summary>

```text
Look a symbol up in the table `start` loaded for `cpu`, else the visible cpu. One question
per call: `name` (exact, else prefix matches by address, case ignored, each in the
spelling the map gave, up to `limit` 1..50; the name never reaches MAME's
console), or `linear`, a run-time address as `disassemble` shows it, not a
linker map's column: the nearest symbol at or below, and the distance. Works while running.

Refused: no table (`no_channel`); an address below every symbol (`unknown_ref`). A name the
file gives twice is listed here with every row, and refused by a tool that takes one address
(`ambiguous_ref`, naming each): use the `0x` address of the one meant.

Reply: by name, `query`, `symbols_total`, `symbols` (`name`, `addr`, `memory`), `truncated`;
by address, `linear`, `name`, `addr`, `delta`, `memory`; and `cpu`, `note`.

Reference: REFERENCE.md, Names for addresses.
```

</details>
<!-- scry-reference:end symbols_find -->
