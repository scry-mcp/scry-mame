# The Project tools

A repository can keep three kinds of file in a `.scry/` folder it tracks. A start profile says how a session starts on it, a screen map names its program's screens and their areas, and a saved step list replays it. A later session then gives only what belongs to its own run.

A session saves what it learns as candidates and writes nothing into a repository by itself. A reply that saves one says so in `kept`, as "N saved for `promote`". `promote` reviews the candidates and writes the ones you approve.

<!-- scry-reference:begin promote -->
## `promote`

Review what the session learned and write the entries you approve into the repository's `.scry/` folder.

```text
promote(dry_run=false, entries=null, names=null, root="")
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, late in a session that started the game, added a screen map and exported a script. `root` names a folder with no `.scry/` yet.

Ask:

> Show me what this session would save into this folder's `.scry/`, without writing anything.

Call:

```text
promote(dry_run=true, root="./tmp/demos/tour")
```

Reply, 5 of 8 fields:

```json
{
  "store": "./tmp/demos/tour/.scry",
  "unchanged": [],
  "total_bytes": 3802,
  "store_bytes": 5477,
  "would_create": [".scry/", ".scry/about.json", ".scry/README.md"]
}
```

A review writes nothing: its candidates come to 3802 bytes, and the folder would hold 5467 with them and its two own files. `would_create` lists what a first approval adds.

<details><summary>The whole reply</summary>

```json
{
  "summary": "promote: 3 candidates in ./tmp/demos/tour/.scry; would create .scry/, .scry/about.json, .scry/README.md",
  "status": "ok",
  "store": "./tmp/demos/tour/.scry",
  "candidates": [
    {
      "entry": "maps/gridlee",
      "kind": "maps",
      "name": "gridlee",
      "file": ".scry/maps/gridlee-screen-map.json",
      "bytes": 440,
      "change": "new"
    },
    {
      "entry": "perform/two-coins",
      "kind": "perform",
      "name": "two-coins",
      "file": ".scry/perform/two-coins.json",
      "bytes": 2977,
      "change": "new"
    },
    {
      "entry": "start/gridlee",
      "kind": "start",
      "name": "gridlee",
      "file": ".scry/start/gridlee.json",
      "bytes": 385,
      "change": "new"
    }
  ],
  "unchanged": [],
  "total_bytes": 3802,
  "store_bytes": 5477,
  "would_create": [".scry/", ".scry/about.json", ".scry/README.md"]
}
```

</details>

### Arguments

- `dry_run` (boolean, default `false`): `true` reviews: it lists every candidate and writes nothing. It cannot be given together with `entries`.
- `entries` (array of string, optional): The entries to write, each `<kind>/<name>` with a kind of `start`, `maps` or `perform`. Only these are written.
- `names` (object, optional): A new name for an entry as it is written, as `{"<kind>/<name>": "<new name>"}`. Left out, each keeps its name.
- `root` (string, default `""`): The repository whose `.scry/` folder takes every entry of the call: absolute, or starting with `~`. Left out, each entry goes to its own repository.

### What comes back

- `candidates`: A review's list. Each `entry` has its `kind`, `name`, `file`, `bytes` and `change` (`new` or `update`), an update its `diff`, and one from another repository says `from`.
- `unchanged`: A review's entries that already equal their file in `.scry/`, so there is nothing to approve.
- `unwritable`: Entries this call cannot write, each with its `reason`: most often a repository with no `.scry/` folder, which a call with `root` creates.
- `written`: An approval's entries as written, in the fields `candidates` uses.
- `draft`: After an approval, the session's candidates not yet written to `.scry/`.
- `would_create`: What an approval would create that is not there yet: `.scry/`, its `about.json` and its `README.md`. An approval names what it created in `created`.

<details><summary>All 10 reply fields</summary>

- `candidates` (array)
- `unchanged` (array of string)
- `unwritable` (array)
- `written` (array)
- `would_create` (array of string)
- `created` (array of string)
- `draft` (array of string)
- `total_bytes` (integer)
- `store` (string)
- `store_bytes` (integer)

</details>

### What it refuses

- Nothing saved yet: no `start`, screen map or exported script of this session is a complete candidate (`needs_call`).
- Both `dry_run` and `entries`, or neither (`bad_argument`).
- An entry the session did not save, one named twice, or a name in `names` for an entry not in `entries` (`bad_argument`).
- Without `root`: no entry with a `.scry/` folder to go to, or entries of two repositories in one call (`bad_argument`).
- A name two repositories saved, unless `root` is one of them (`bad_argument`).
- Two entries that `names` would write to one file (`bad_argument`).
- An entry a review lists as `unwritable` (`bad_argument`).
- More entries of one kind, or more bytes, than a `.scry/` folder may hold (`bad_argument`).
- A `root` that is relative, is no directory, or names the `.scry/` folder itself (`bad_argument`).
- A file the host would not write; the message names what was written before it (`host_failed`).

### Why it works this way

Nothing is written into a repository until a call names the entries to write. The `.scry/` folder is tracked, so every entry is reviewed before it is written, and only an approved call creates the folder. [The `.scry/` folder](../../REFERENCE.md#the-scry-folder) says what it holds.

`dry_run=true` lists each candidate that would change the folder: its file, its size and whether it is new or an update, an update with what changes. It names the candidates that would change nothing, and what an approval would create beside the entries.

An entry belongs to one repository, fixed when it is saved: the one a call read it from, else the one whose profile the current `start` read. A `start` that read no profile names none, since no argument says where a program's repository is. Its entries are written only where `root` says.

<details><summary>More on why</summary>

A candidate is saved only when complete: a start profile with the arguments it cannot start without, a screen map its reader parses, a script with a check. A reply that saves one also names each repository with no `.scry/` folder and the `root` to give.

An entry a call loaded (`start(profile=)`, `screen_map_write(method="load")`, `perform(path=)`) gives its name to what is learned next, so saving it again is an update. An update keeps the keys that belong to a run as the file has them.

Every path in an entry is written as a placeholder ([the rule](https://github.com/scry-mcp/scry-core/blob/main/docs/store-paths.md)), so the tracked file reads the same on any machine. `close` names in `draft` what was left unwritten, and the candidates stay until the server ends.

`store` is the `.scry/` folder the call reads or writes, `store_bytes` its size with the entries written, and `total_bytes` the size of the candidates listed. A `diff` holds `added`, `removed` and `changed`, each change with its `path`, `was` and `now`; `changed_total` counts them when the list is cut.

</details>

### Related tools

- [`start`](session.md#start)
- [`screen_map_write`](read.md#screen_map_write)
- [`perform_export`](sequences.md#perform_export)
- [`perform`](sequences.md#perform)
- [`close`](session.md#close)

<details><summary>The contract your client receives</summary>

```text
What this session learned, written into the repository's store (`.scry/`) only when
approved. `start` keeps the recipe it ran, a map's `add` keeps the map, a
`perform_export` keeps the script; each is complete only with what its reader accepts
(the arguments a recipe cannot boot without, a map the map reader parses, a script
with a check), and a reply that keeps one says `N saved for promote` in `kept`, naming
each repository of the draft with no store and the `root` it takes. An entry belongs
to the repository it was learned in: the one whose store a call loaded it from, else
the current `start`'s, its profile's or where its program runs, where the server can
tell. The identity is
(repository, kind, name): an entry a call loaded (`start(profile=)`,
`screen_map_write` `load`, `perform(path=)`) names what is learned next, and a name
the store already holds is an update, which keeps the keys a run owns as the
store has them, and one that changes nothing is named in `unchanged`, not offered.
`dry_run=true` lists every other candidate with its
file, its size and whether it is new or an update, an update with its diff; `entries`
(`<kind>/<name>`, the kind one of `start`, `maps`, `perform`) writes only those,
`names` renames one as it is written, and only
that approved call creates `.scry/`, and with the server's name also `about.json` and
the rendered `README.md`; `dry_run`
names those in `would_create`, the approval in `created`. Without `root` each entry
goes only to its own repository's store, one store a call, and one whose repository
has none is unwritable; `root` names the repository whose store a call writes every
entry to, a candidate from another saying `from`. Every path is
written as a `project_store` placeholder, since a tracked file carries no path of this
machine; an approval of an entry a review calls unwritable is refused. Reply: `store`,
`candidates` and `unchanged` (a review), `unwritable`, each entry with its reason
(a review holding an entry it cannot write), `written` and `draft` (an approval),
`would_create` and `created` (the store, `about.json`, `README.md` not yet there),
`total_bytes`,
`store_bytes`; `close` names what was left unkept, which stays in the draft until the
server ends. Refused: nothing kept (`needs_call`); an entry the draft does not hold;
without `root`, a call none of whose entries has a store, or entries of two stores; a
name two repositories hold, unless `root` is one of them; two entries written to one
file; a kind or a store past its cap.

Reference: REFERENCE.md, The `.scry/` folder.
```

</details>
<!-- scry-reference:end promote -->
