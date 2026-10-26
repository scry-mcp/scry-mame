# The Comments tools

A comment is a declaration too: a text at a place, shown in MAME's own disassembly. The shared contract and the comment file's format are in [REFERENCE.md, Declarations](../../REFERENCE.md#declarations).



**A rebuild can bring several comments to one place.** All are kept; the pane shows the first the store holds that it can show, and each other is `unarmable` (a `stale` one is `stale`, never fed). An add, load or delete there reaches the one its ref spells, else the one the pane shows. A `stale` comment of the other kind is outside the one-per-place rule: only its own spelling replaces or deletes it. A replacing add keeps the first `ref` and `by`, so a comment made by symbol keeps following it.

**The pane is a VIEW of the store.** MAME binds no comment call to Lua, so each comment is fed through the console's `comadd`, which names no cpu: another cpu's is fed by making it visible and putting the visible one back, and each is read back off one `dasm` line ending ` // <text>`. A text the console cannot carry replacing one the pane showed clears the old one; a `comadd` answered with text, or a cpu the stub cannot show, leaves the old text.

**The store is written first**, and a session error after that says so; the next `start` feeds the pane from it. MAME writes its comments into a directory the server pins inside the session's scratch, so nothing the store dropped comes back from it.

<!-- scry-reference:begin comment_list -->
## `comment_list`

*List the comments*

```text
comment_list(cpu="")
```

Every comment of the store, or `cpu`'s. Answers on a running machine too.

Reply: `comments` (each `ref`, `text`, `addr`, `state`; at most 24),
`comments_total`, `truncated`, `declarations`, `cpu`.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `comments` | array |
| `comments_total` | integer |
| `cpu` | string or object |
| `declarations` | object |
| `truncated` | boolean |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "comment_list: 1 comment",
  "status": "ok",
  "comments": [
    {
      "ref": "irq_vblank",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "2026-10-24T22:09:55+00:00",
      "origin": "2026-10-24T22:09:54+00:00#65429.1",
      "inherited": false,
      "age_s": 0,
      "text": "matrix A",
      "addr": "0x00000400",
      "state": "armed"
    }
  ],
  "comments_total": 1,
  "truncated": false,
  "declarations": {
    "persistent": true,
    "path": "$TMPDIR/mame-live-matrix-1674617bb625/jobs-scratch/A/mame-live-matrix-state-gtki_cyl/mame-debug/declarations.json"
  },
  "cpu": {
    "available": false,
    "why": "no cpu was named, so the rows are every cpu's"
  }
}
```
<!-- scry-reference:end comment_list -->



MAME also keys a comment by a CRC of the instruction bytes under it, so code that moves in RAM hides its comment in the pane while the store keeps it, and a delete over bytes that changed since leaves MAME holding it, hidden, until `close`.





Two rows a rebuild put at one place are both loaded, so what `comment_write(method="save")` writes of such a store reads back. The first file row at a place the store comments replaces the store's row and any other comes in beside it (a `stale` row of the other kind excepted).

`state` meanings: `armed` is shown in the pane, `unarmable` is not shown (`why`), `unresolved` names a symbol this build lacks, `stale` is a raw address declared over another build. Rows past the shown cap are not listed; `comment_write(method="save")` writes the whole set. Each row also carries `by`, `cpu`, `created_at`, `origin`, `inherited` and `age_s`.

<!-- scry-reference:begin comment_write -->
## `comment_write`

*Write the comments*

```text
comment_write(method, ref="", text="", cpu="", dest="", path="")
```

Change the store's comments.

`add`: `text` (one printable line, at most 237 UTF-8 bytes) on `ref`,
a symbol or a linear `0x` address, of `cpu` (default the visible one); a second there
replaces it.
Reply: `comment`, `replaced_comments`, `declarations`, `cpu`, `note`.

`delete`: the comment at `ref`. Reply: `deleted`, `declarations`, `cpu`, `note`.

`save`: every comment to `dest`, an absolute or `~`-led path, replacing a comment file
there (rows only it held in `dropped_comments`); any other file is refused; answers on a
running machine. Reply: `path`, `comments_total`, `dropped_comments`, `dropped_total`,
`truncated`, `note`.

`load`: the comment file at `path`, all or nothing, the file winning. Reply: `path`,
`parsed`, `added`, `replaced_comments`, `replaced_total`, `truncated`, `unchanged`,
`comments_total`, `declarations`, `note`.

`add`, `delete` and `load` need the machine stopped. Refused: an argument the method
does not take, a misshapen `ref` or `text`, an unknown `ref` (`unknown_ref`), an
unwritable store (`host_failed`, `held_in_memory`).

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `method` | one of `"add"`, `"delete"`, `"save"`, `"load"` | required |
| `ref` | string | `""` |
| `text` | string | `""` |
| `cpu` | string | `""` |
| `dest` | string | `""` |
| `path` | string | `""` |

| reply field | type |
|---|---|
| `added` | integer |
| `comment` | object |
| `comments_total` | integer |
| `cpu` | string |
| `declarations` | object |
| `deleted` | object |
| `dropped_comments` | array |
| `dropped_total` | integer |
| `held_in_memory` | boolean |
| `note` | string |
| `parsed` | integer |
| `path` | string |
| `replaced_comments` | array |
| `replaced_total` | integer |
| `truncated` | boolean |
| `unchanged` | integer |

Example, from a live run:

```json
{
  "method": "add",
  "ref": "irq_vblank",
  "text": "matrix A",
  "cpu": "maincpu"
}
```

```json
{
  "summary": "comment_write add: irq_vblank at :maincpu 0x00000400, stored, persistent",
  "status": "ok",
  "comment": {
    "ref": "irq_vblank",
    "by": "symbol",
    "cpu": ":maincpu",
    "created_at": "2026-10-24T22:09:55+00:00",
    "origin": "2026-10-24T22:09:54+00:00#65429.1",
    "inherited": false,
    "age_s": 0,
    "text": "matrix A",
    "addr": "0x00000400",
    "state": "armed"
  },
  "replaced_comments": [],
  "declarations": {
    "persistent": true,
    "path": "$TMPDIR/mame-live-matrix-1674617bb625/jobs-scratch/A/mame-live-matrix-state-gtki_cyl/mame-debug/declarations.json"
  },
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end comment_write -->

By symbol a comment follows the symbol through a rebuild; by address it goes `stale` once the build changes. `save` replaces only a comment file, and its `dest` is in a directory that exists and carries no comma, semicolon, quote, whitespace, bracket or control character.
