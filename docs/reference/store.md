# The Store tools

<!-- scry-reference:begin promote -->
## `promote`

*Promote what the session learned*

```text
promote(dry_run=false, entries=null, names=null, root="")
```

What this session learned, written into the repository's store (`.scry/`) only when
approved. `start` keeps the recipe it ran, a map's `add` keeps the map, a
`perform_export` keeps the script; each is complete only with what its reader accepts
(the arguments a recipe cannot boot without, a map the map reader parses, a script
with a check), and a reply that keeps one says `kept N (promote to review)`. The
identity is (kind, name): an entry a call loaded (`start(profile=)`,
`screen_map_write` `load`, `perform(path=)`) names what is learned next, and a name
the store already holds is an update, which keeps the keys a run owns as the
store has them, and one that changes nothing is named in `unchanged`, not offered.
`dry_run=true` lists every other candidate with its
file, its size and whether it is new or an update, an update with its diff; `entries`
(`<kind>/<name>`, the kind one of `start`, `maps`, `perform`) writes only those,
`names` renames one as it is written, and only
that approved call creates `.scry/`. `root` names the repository the store is in or
becomes; without it the first `.scry/` found walking up from the file a loaded recipe
came from, the draft's paths, then this server's directory, is used, and a promotion
that finds none is refused. Every path is
written as a `project_store` placeholder, since a tracked file carries no path of this
machine; an approval of an entry a review calls unwritable is refused. Reply: `store`,
`candidates` and `unchanged` (a review), `unwritable`, each entry with its reason
(a review holding an entry it cannot write), `written` and `draft` (an approval),
`total_bytes`,
`store_bytes`; `close` names what was left unkept, which stays in the draft until the
server ends. Refused: nothing kept (`needs_call`); an entry the draft does not hold; two
entries written to one file; a kind or a store past its cap.

Reference: REFERENCE.md, The store.

| argument | type | default |
|---|---|---|
| `dry_run` | boolean | `false` |
| `entries` | array of string or null | `null` |
| `names` | object or null | `null` |
| `root` | string | `""` |

| reply field | type |
|---|---|
| `candidates` | array |
| `unchanged` | array of string |
| `unwritable` | array |
| `written` | array |
| `draft` | array of string |
| `total_bytes` | integer |
| `store` | string |
| `store_bytes` | integer |

Example, from a live run:

```json
{
  "dry_run": true,
  "root": "$TMPDIR/mame-live-matrix-<run>/jobs-scratch/P/mame-live-promote-<run>"
}
```

```json
{
  "summary": "promote: 2 candidates in $TMPDIR/mame-live-matrix-<run>/jobs-scratch/P/mame-live-promote-<run>/.scry",
  "status": "ok",
  "store": "$TMPDIR/mame-live-matrix-<run>/jobs-scratch/P/mame-live-promote-<run>/.scry",
  "candidates": [
    {
      "entry": "maps/radendur",
      "kind": "maps",
      "name": "radendur",
      "file": ".scry/maps/radendur-screen-map.json",
      "bytes": 333,
      "change": "new"
    },
    {
      "entry": "start/radendur",
      "kind": "start",
      "name": "radendur",
      "file": ".scry/start/radendur.json",
      "bytes": 385,
      "change": "new"
    }
  ],
  "unchanged": [],
  "total_bytes": 718,
  "store_bytes": 718
}
```
<!-- scry-reference:end promote -->
