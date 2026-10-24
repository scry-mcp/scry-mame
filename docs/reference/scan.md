# The Scan tools

<!-- scry-reference:begin scan_start -->
## `scan_start`

*Start a value scan*

```text
scan_start(ref, length, cell_bytes=1, cpu="")
```

Open a VALUE SCAN, the search for a variable no map names, in one cpu's PROGRAM space
only: there is no `space` argument, and io ports are never scanned. Every cell of
`cell_bytes` (1, 2 or 4, in the cpu's byte order) from `ref`, for `length` bytes, on `cpu`
(`subcpu`; the visible one when empty) is a candidate, then `scan_filter` keeps the ones
that moved as the variable did. `length` counts BYTES whatever the cell (a multiple of
`cell_bytes`, at most 0x100000); an odd start is allowed.

Reply: `addr`, `length`, `cell_bytes`, `hits_total` (the addresses the scan holds),
`cpu` (bound: every filter reads this cpu whatever is visible later), `space` (`program`).
The range is read with the console's `save`, through handlers, stepping and writing nothing.
One scan at a time: a second is `needs_call` naming the open one (its `addr`, `cpu` and
`hits_total`; `scan_clear` it); it outlives runs, writes,
`reset` and `state_load`, and dies with `close`. A range whose last byte lies past that cpu's program space (the address mask `start` read) is `bad_argument` naming the mask; with no mask known the range is the console's. Needs the machine STOPPED (else `not_stopped`).

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `ref` | string | required |
| `length` | integer | required |
| `cell_bytes` | one of `1`, `2`, `4` | `1` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `addr` | string |
| `cell_bytes` | integer |
| `cpu` | string |
| `hits_total` | integer |
| `length` | integer |
| `space` | string |

Example, from a live run:

```json
{
  "ref": "0x200000",
  "length": 256
}
```

```json
{
  "summary": "scan_start 0x200000: 256 1-byte candidates on :maincpu",
  "status": "ok",
  "addr": "0x00200000",
  "length": 256,
  "cell_bytes": 1,
  "hits_total": 256,
  "cpu": ":maincpu",
  "space": "program"
}
```
<!-- scry-reference:end scan_start -->

It reads through handlers, where MAME's own cheat engine sees only direct RAM. The scan is bound to one cpu because a scan bound to none would read whichever is visible at each filter.

<!-- scry-reference:begin scan_filter -->
## `scan_filter`

*Filter the value scan*

```text
scan_filter(operator="=", value=null, limit=40)
```

Keep the cells of the open scan whose value satisfies `operator` (`=`, `!` not equal,
`>`, `>=`, `<`, `<=`, unsigned) against `value` (an integer or a `0x` string), or, with no
`value`, against what each
cell held when `scan_start` opened the scan (`!` keeps a cell that differs from it, `>` one
larger).

Reply: `operator`, `value` (`0x` at the cell's width; unavailable without one), `iterations`
(filters since `scan_start`, this one included), `closed`, `hits` (the first `limit`, each
`addr` and its `value` now, address order), `hits_total` (the survivors), `truncated` (more
survive than `hits` shows), `cpu`, `space`. None left CLOSES the scan
(`hits` empty, `hits_total` 0). No scan open is `needs_call`; a value wider than the cell is
`bad_argument`; a refused filter leaves the scan as it was. Needs the machine STOPPED (else `not_stopped`).

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `operator` | one of `"="`, `"!"`, `">"`, `">="`, `"<"`, `"<="` | `"="` |
| `value` | integer or string or null | `null` |
| `limit` | integer (>= 1, <= 400) | `40` |

| reply field | type |
|---|---|
| `closed` | boolean |
| `cpu` | string |
| `hits` | array |
| `hits_total` | integer |
| `iterations` | integer |
| `operator` | string |
| `space` | string |
| `truncated` | boolean |
| `value` | string or object |

Example, from a live run:

```json
{
  "operator": "!"
}
```

```json
{
  "summary": "scan_filter !: 0 survivors, scan closed",
  "status": "ok",
  "operator": "!",
  "value": {
    "available": false,
    "why": "no `value` was given, so each cell was compared with its value at `scan_start`"
  },
  "iterations": 1,
  "closed": true,
  "hits": [],
  "hits_total": 0,
  "truncated": false,
  "cpu": ":maincpu",
  "space": "program"
}
```
<!-- scry-reference:end scan_filter -->

<!-- scry-reference:begin scan_clear -->
## `scan_clear`

*Clear the value scan*

```text
scan_clear()
```

End the value scan `scan_start` opened. Reply: `cleared`, with a `note` when none was
open. It is the server's own state, so it answers on a RUNNING machine.

Reference: REFERENCE.md, Reading and writing.

Takes no argument.

| reply field | type |
|---|---|
| `cleared` | boolean |
| `note` | string |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "scan_clear: nothing was open",
  "status": "ok",
  "cleared": false,
  "note": "no scan was open"
}
```
<!-- scry-reference:end scan_clear -->
