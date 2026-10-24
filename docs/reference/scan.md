# The Scan tools



It reads through handlers, where MAME's own cheat engine sees only direct RAM. The scan is bound to one cpu because a scan bound to none would read whichever is visible at each filter.




<!-- scry-reference:begin scan -->
## `scan`

*Value scan*

```text
scan(method, ref="", length=null, cell_bytes=null, cpu="", operator=null, value=null, limit=null)
```

Value scan: find a variable no map names, in one cpu's program space only, no io
ports. One scan at a time; it outlives runs, writes, `reset` and state loads; `close`
ends it.

`start`: every cell of `cell_bytes` from `ref` on `cpu` is a candidate;
`length` counts bytes, at most 0x100000. Reply: `addr`, `length`, `cell_bytes`,
`hits_total`, `cpu`, `space`.

`filter`: keep the cells whose value satisfies `operator` (`=` default) against
`value` (an integer or a `0x` string), or with no `value` against what each held at `start`; none left
closes the scan. Reply: `operator`, `value`, `iterations`, `closed`, `hits` (the first
`limit`, default 40), `hits_total`, `truncated`, `cpu`, `space`.

`clear`: end the scan. Reply: `cleared`, `note`.

Refused: an argument the method does not take; a second `start` or no scan open
(`needs_call`); a range past the cpu's program space (`bad_argument`).

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `method` | one of `"start"`, `"filter"`, `"clear"` | required |
| `ref` | string | `""` |
| `length` | integer or null | `null` |
| `cell_bytes` | one of `1`, `2`, `4` or null | `null` |
| `cpu` | string | `""` |
| `operator` | one of `"="`, `"!"`, `">"`, `">="`, `"<"`, `"<="` or null | `null` |
| `value` | integer or string or null | `null` |
| `limit` | integer (>= 1, <= 400) or null | `null` |

| reply field | type |
|---|---|
| `addr` | string |
| `cell_bytes` | integer |
| `cleared` | boolean |
| `closed` | boolean |
| `cpu` | string |
| `hits` | array |
| `hits_total` | integer |
| `iterations` | integer |
| `length` | integer |
| `note` | string |
| `operator` | string |
| `space` | string |
| `truncated` | boolean |
| `value` | string or object |

Example, from a live run:

```json
{
  "method": "start",
  "ref": "0x200000",
  "length": 256
}
```

```json
{
  "summary": "scan start: 0x200000, 256 1-byte candidates on :maincpu",
  "status": "ok",
  "addr": "0x00200000",
  "length": 256,
  "cell_bytes": 1,
  "hits_total": 256,
  "cpu": ":maincpu",
  "space": "program"
}
```
<!-- scry-reference:end scan -->
