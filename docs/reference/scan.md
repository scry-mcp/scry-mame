# The Scan tools

A scan finds where a program keeps a value when no symbol names it: the credits, a score, a timer. It starts from every byte of a range and narrows the list each time the value changes.

<!-- scry-reference:begin scan -->
## `scan`

Find the byte that holds a value nobody has named: start from a whole range and keep only what changes as the value does.

```text
scan(method, ref="", length=null, cell_bytes=null, cpu="", operator=null, value=null, limit=null)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, five seconds after power-on. The demo drops three coins and filters after each; these are its first call and its last.

Ask:

> Find the byte where this game counts its credits: scan the first 2 KB and filter after each of three coins.

Call:

```text
scan(method="start", ref="0x0", length=2048)
```

Reply, 6 of 9 fields:

```json
{
  "summary": "scan start: 0x0, 2048 1-byte candidates on :maincpu",
  "status": "ok",
  "length": 2048,
  "cell_bytes": 1,
  "hits_total": 2048,
  "cpu": ":maincpu"
}
```

Then, after the third coin:

Call:

```text
scan(method="filter", operator="=", value=3)
```

Reply, 5 of 11 fields:

```json
{
  "summary": "scan filter: = 0x03, 3 survivors",
  "status": "ok",
  "iterations": 3,
  "hits": [
    {"addr": "0x000003ee", "value": "0x03"},
    {"addr": "0x0000042b", "value": "0x03"},
    {"addr": "0x0000042c", "value": "0x03"}
  ],
  "hits_total": 3
}
```

Three bytes still hold 3 after three coins. Two of them, `0x42b` and `0x42c`, are the credits, which the game keeps twice.

<details><summary>The two replies, whole</summary>

The first call's:

```json
{
  "summary": "scan start: 0x0, 2048 1-byte candidates on :maincpu",
  "status": "ok",
  "ref": "0x0",
  "addr": "0x00000000",
  "length": 2048,
  "cell_bytes": 1,
  "hits_total": 2048,
  "cpu": ":maincpu",
  "space": "program"
}
```

The second call's:

```json
{
  "summary": "scan filter: = 0x03, 3 survivors",
  "status": "ok",
  "operator": "=",
  "value": "0x03",
  "iterations": 3,
  "closed": false,
  "hits": [
    {"addr": "0x000003ee", "value": "0x03"},
    {"addr": "0x0000042b", "value": "0x03"},
    {"addr": "0x0000042c", "value": "0x03"}
  ],
  "hits_total": 3,
  "truncated": false,
  "cpu": ":maincpu",
  "space": "program"
}
```

</details>

### The three methods

| method | what it does |
|---|---|
| `start` | Opens a scan: every cell of the range is a candidate. |
| `filter` | Keeps the candidates whose value passes a comparison. |
| `clear` | Ends the scan. |

### Arguments

- `method` (one of `"start"`, `"filter"`, `"clear"`, required): `start`, `filter` or `clear`, as above.
- `ref` (string, default `""`): Where the range begins, for `start`: a `0x` address or a symbol.
- `length` (integer, optional): How many bytes to scan, for `start`: at most `0x100000`.
- `cell_bytes` (one of `1`, `2`, `4`, optional): The size of each candidate: 1, 2 or 4 bytes. Left out, one byte.
- `cpu` (string, default `""`): The cpu whose program memory is scanned. Left empty, the one the debugger is showing.
- `operator` (one of `"="`, `"!"`, `">"`, `">="`, `"<"`, `"<="`, optional): The comparison a `filter` makes. Left out, `=`.
- `value` (integer or string, optional): What each candidate is compared with: an integer or a `0x` string. Left out, what it held at `start`.
- `limit` (integer (>= 1, <= 400), optional): How many of the candidates left the reply lists: 1 to 400. Left out, 40.

### What comes back

- `hits_total`: How many candidates are left.
- `hits`: The first `limit` of them, each with its address and its value now.
- `iterations`: How many filters this scan has taken.
- `closed`: `true` when a filter left no candidate, which ends the scan.
- `truncated`: `true` when there are more candidates than `hits` lists.

<details><summary>All 14 reply fields</summary>

- `addr` (string)
- `cell_bytes` (integer)
- `cleared` (boolean)
- `closed` (boolean)
- `cpu` (string)
- `hits` (array)
- `hits_total` (integer)
- `iterations` (integer)
- `length` (integer)
- `operator` (string)
- `ref` (string)
- `space` (string)
- `truncated` (boolean)
- `value` (string or object)

</details>

### What it refuses

- An argument the method does not take.
- A second `start` while a scan is open, or a `filter` with none (`needs_call`).
- A range that runs past the cpu's program memory (`bad_argument`).

### Why it works this way

The scan reads memory the way the cpu does, through the board's own handlers, so it sees what MAME's cheat search cannot. It belongs to one cpu, because every filter must read the same memory.

One scan is open at a time, and nothing you do between filters ends it: running, writing, a reset or loading a saved state. That is what lets a coin go in between two filters.

### Related tools

- [`watch_add`](breakpoints.md#watch_add)
- [`find`](read.md#find)
- [`read_memory`](read.md#read_memory)
- [`input`](lua.md#input)

<details><summary>The contract your client receives</summary>

```text
Value scan: find a variable no map names, in one cpu's program space only, no io
ports. One scan at a time; it outlives runs, writes, `reset` and state loads; `close`
ends it.

`start`: every cell of `cell_bytes` from `ref` on `cpu` is a candidate;
`length` counts bytes, at most 0x100000. Reply: `ref`, `addr`, `length`, `cell_bytes`,
`hits_total`, `cpu`, `space`.

`filter`: keep the cells whose value satisfies `operator` (`=` default) against
`value` (an integer or a `0x` string), or with no `value` against what each held at `start`; none left
closes the scan. Reply: `operator`, `value`, `iterations`, `closed`, `hits` (the first
`limit`, default 40), `hits_total`, `truncated`, `cpu`, `space`.

`clear`: end the scan. Reply: `cleared`, `note`.

Refused: an argument the method does not take; a second `start` or no scan open
(`needs_call`); a range past the cpu's program space (`bad_argument`).

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end scan -->
