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
the store already holds is an update. `dry_run=true` lists every candidate with its
file, its size and whether it is new or an update, an update with its diff; `entries`
(`<kind>/<name>`, the kind one of `start`, `maps`, `perform`) writes only those,
`names` renames one as it is written, and only
that approved call creates `.scry/`. `root` names the repository the store is in or
becomes; without it the nearest `.scry/` above this server's directory or the draft's
paths is used, and a promotion that finds none is refused. Every path is written as a
`project_store` placeholder; one that would leave them is refused, since a tracked
file carries no path of this machine. Reply: `store`, `candidates` (a review), `written`
and `draft` (an approval), `total_bytes`, `store_bytes`; `close` names what was left
unkept. Refused: nothing kept (`needs_call`); an entry the draft does not hold; two
entries written to one file; a candidate the caps cannot hold; an entry that is there
and cannot be read as JSON.

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
| `written` | array |
| `draft` | array of string |
| `total_bytes` | integer |
| `store` | string |
| `store_bytes` | integer |

Example, from a live run:

```json
{
  "dry_run": true,
  "root": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/mame-live-promote-<run>"
}
```

```json
{
  "summary": "promote: 4 candidates in /var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/mame-live-promote-<run>/.scry",
  "status": "ok",
  "store": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/mame-live-promote-<run>/.scry",
  "candidates": [
    {
      "entry": "maps/radendur",
      "kind": "maps",
      "name": "radendur",
      "file": ".scry/maps/radendur.screen-map.json",
      "bytes": 333,
      "change": "new"
    },
    {
      "entry": "start/m68k-dual",
      "kind": "start",
      "name": "m68k-dual",
      "file": ".scry/start/m68k-dual.json",
      "bytes": 464,
      "change": "new"
    },
    {
      "entry": "start/probe-profile",
      "kind": "start",
      "name": "probe-profile",
      "file": ".scry/start/probe-profile.json",
      "bytes": 444,
      "change": "new"
    },
    {
      "entry": "start/radendur",
      "kind": "start",
      "name": "radendur",
      "file": ".scry/start/radendur.json",
      "bytes": 343,
      "change": "new"
    }
  ],
  "total_bytes": 1584,
  "store_bytes": 1584
}
```
<!-- scry-reference:end promote -->
