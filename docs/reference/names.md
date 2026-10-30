# The Names tools

<!-- scry-reference:begin symbols_find -->
## `symbols_find`

*Look a symbol up*

```text
symbols_find(name="", linear="", limit=10, cpu="")
```

Look a symbol up in the table `start` loaded for `cpu`, else the visible cpu. One question
per call: `name` (exact, else prefix matches by address, case ignored, each in the
spelling the map gave, up to `limit` 1..50; the name never reaches MAME's
console), or `linear`, a `0x` run-time address as `disassemble` shows it, not a
linker map's column: the nearest symbol at or below, and the distance. Works while running.

Refused: no table (`no_channel`); an address below every symbol (`unknown_ref`). A name the
file gives twice is listed here with every row, and refused by a tool that takes one address
(`ambiguous_ref`, naming each): use the `0x` address of the one meant.

Reply: by name, `query`, `symbols_total`, `symbols` (`name`, `addr`, `memory`), `truncated`;
by address, `linear`, `name`, `addr`, `delta`, `memory`; and `cpu`, `note`.

Reference: REFERENCE.md, Names for addresses.

| argument | type | default |
|---|---|---|
| `name` | string | `""` |
| `linear` | string | `""` |
| `limit` | integer (>= 1, <= 50) | `10` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `addr` | string |
| `cpu` | string |
| `delta` | integer |
| `linear` | string |
| `memory` | string |
| `name` | string |
| `query` | string |
| `symbols` | array |
| `symbols_total` | integer |
| `truncated` | boolean |

Example, from a live run:

```json
{
  "name": "irq_vblank"
}
```

```json
{
  "summary": "symbols_find irq_vblank: 1 match",
  "status": "ok",
  "query": "irq_vblank",
  "cpu": ":maincpu",
  "symbols_total": 1,
  "symbols": [
    {"name": "irq_vblank", "addr": "0x00000400", "memory": "rom"}
  ],
  "truncated": false
}
```
<!-- scry-reference:end symbols_find -->

`memory` is answered so that a change watch on the ROM copy of a datum is known to be pointless before it is tried.

`memory` values: `ram`, `rom`, `latch`, `handlers`, `unmapped`, or `unknown`. Each symbol answered costs the console one `map`, hence the `limit` cap. `linear` is the address after `bases`, since a linker map's column is before them and passed here answers a plausible symbol with an absurd delta; the delta is a distance above the symbol because the table carries no sizes. `memory` is what the address is to the machine, from the console's `map`: `ram` is written and read through memory, so a change watch fires there; `rom` is never written (the ROM copy of a datum, or code); `latch` is written through a handler and read nowhere, so `read_memory` answers zeros and, when the map entry keeps a share, `read_block(ref=...)` reads it; `handlers` is read and written through handlers, a paired region: readable, not plain memory; `unknown` is answered on a running machine (the `note` says so) or where `map` names no side. The table is not a value read off the machine, which is why it answers while running.
