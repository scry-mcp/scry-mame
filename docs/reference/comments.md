# The Comments tools

A comment is a declaration too: a text at a place, shown in MAME's own disassembly. The shared contract and the comment file's format are in [REFERENCE.md, Declarations](../../REFERENCE.md#declarations).

<!-- scry-reference:begin comment_add -->
## `comment_add`

*Add a comment*

```text
comment_add(ref, text, cpu="")
```

Put `text` on `ref` of a cpu as a COMMENT: a declaration in the store, and the line MAME's
own disassembly shows (`disassemble` ends it ` // <text>`). By symbol it follows the symbol
through a rebuild; by address it is listed `stale` once the build changes. One comment per
place on a cpu: a second at the same place, in any spelling, replaces the text and keeps the
first `ref`. Kept per system and symbol file and fed back at the next `start`; with no symbol
file `declarations.persistent` is false and it dies at `close`.

Arguments: `ref`, a symbol or a LINEAR `0x` address (`0x4a0`; a `seg:off`, a pointer,
whitespace or a leading `#` is refused). `text`: one printable line, no tab, no edge spaces,
at most 237 UTF-8 bytes; else `bad_argument`, nothing stored. `cpu`: its cpu,
else the visible one; a comment on another cpu is fed with that cpu made visible and the
visible one put back (a `note` says so if it cannot be).

Refused: an address past the cpu's program space; `0x` before anything but hex (a file reads
`0x` as an address). A name absent from THIS build (not bare hex) is stored `unresolved`. A
text the console cannot carry (a `"`, a trailing `\`) is stored and not shown (`unarmable`,
a `note`). Needs the machine STOPPED (else `not_stopped`).

Reply: `comment` (the row as `comment_list` gives it), `replaced_comments` (the row this
place held, or empty), `declarations` (`persistent`, `path`: the store), `cpu`, `note`. A store
that cannot be written: `host_failed` with `held_in_memory: true`.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `ref` | string | required |
| `text` | string | required |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `comment` | object |
| `cpu` | string |
| `declarations` | object |
| `held_in_memory` | boolean |
| `note` | string |
| `replaced_comments` | array |

Example, from a live run:

```json
{
  "ref": "irq_vblank",
  "text": "matrix A",
  "cpu": "maincpu"
}
```

```json
{
  "summary": "comment_add irq_vblank: :maincpu 0x00000400, stored, persistent",
  "status": "ok",
  "comment": {
    "ref": "irq_vblank",
    "by": "symbol",
    "cpu": ":maincpu",
    "created_at": "2026-10-24T16:07:07+00:00",
    "origin": "2026-10-24T16:07:07+00:00#32680.1",
    "inherited": false,
    "age_s": 0,
    "text": "matrix A",
    "addr": "0x00000400",
    "state": "armed"
  },
  "replaced_comments": [],
  "declarations": {
    "persistent": true,
    "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/mame-live-matrix-state-t5au50_9/mame-debug/declarations.json"
  },
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end comment_add -->

**A rebuild can bring several comments to one place.** All are kept; the pane shows the first the store holds that it can show, and each other is `unarmable` (a `stale` one is `stale`, never fed). An add, load or delete there reaches the one its ref spells, else the one the pane shows. A `stale` comment of the other kind is outside the one-per-place rule: only its own spelling replaces or deletes it. A replacing add keeps the first `ref` and `by`, so a comment made by symbol keeps following it.

**The pane is a VIEW of the store.** MAME binds no comment call to Lua, so each comment is fed through the console's `comadd`, which names no cpu: another cpu's is fed by making it visible and putting the visible one back, and each is read back off one `dasm` line ending ` // <text>`. A text the console cannot carry replacing one the pane showed clears the old one; a `comadd` answered with text, or a cpu the stub cannot show, leaves the old text.

**The store is written first**, and a session error after that says so; the next `start` feeds the pane from it. MAME writes its comments into a directory the server pins inside the session's scratch, so nothing the store dropped comes back from it.

<!-- scry-reference:begin comment_list -->
## `comment_list`

*List the comments*

```text
comment_list(cpu="")
```

Every comment of the store, or `cpu`'s, as held and as MAME's pane last took it. Answers on
a running machine too (with `last_stop`): it asks the machine nothing.

Reply: `comments`, each with `ref`, `by`, `cpu`, `created_at`, `origin`, `inherited`, `age_s`,
`text`, `addr` once it resolves, and `state`: `armed` (shown in the pane), `unarmable` (not
shown, `why`), `unresolved` (a symbol this build lacks) or `stale` (a raw address declared over
another build); at most 24 rows, with `comments_total` and `truncated` (the whole set
is `comment_save`'s). Also `declarations` (`persistent`, `path`), and `cpu` (unavailable for
every cpu).

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
      "created_at": "2026-10-24T16:07:07+00:00",
      "origin": "2026-10-24T16:07:07+00:00#32680.1",
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
    "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/mame-live-matrix-state-t5au50_9/mame-debug/declarations.json"
  },
  "cpu": {
    "available": false,
    "why": "no cpu was named, so the rows are every cpu's"
  }
}
```
<!-- scry-reference:end comment_list -->

<!-- scry-reference:begin comment_delete -->
## `comment_delete`

*Delete a comment*

```text
comment_delete(ref, cpu="")
```

Delete the comment at the place `ref` names on a cpu (the visible one when `cpu` is empty),
however that comment was spelled, from the store and from MAME's pane. One at a time: `ref`
is required and an empty one is refused, so unlike the `*_clear` tools there is no
delete-all (and no `comment_clear`): one place per call.

Refused: a `ref` that matches no comment there (`unknown_ref`, naming the comments held). The
store's removal is the fact; a pane line still showing the text (MAME keys a comment by the
bytes too) is a `note`. Needs the machine STOPPED (else `not_stopped`).

Reply: `deleted` (the row), `declarations` (`persistent`, `path`), `cpu`, `note`. A store that
cannot be written: `host_failed` with `held_in_memory: true`.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `ref` | string | required |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `cpu` | string |
| `declarations` | object |
| `deleted` | object |
| `held_in_memory` | boolean |
| `note` | string |

Example, from a live run:

```json
{
  "ref": "irq_vblank",
  "cpu": "maincpu"
}
```

```json
{
  "summary": "comment_delete irq_vblank: :maincpu 0x00000400 deleted",
  "status": "ok",
  "deleted": {
    "ref": "irq_vblank",
    "by": "symbol",
    "cpu": ":maincpu",
    "created_at": "2026-10-24T16:07:07+00:00",
    "origin": "2026-10-24T16:07:07+00:00#32680.1",
    "inherited": false,
    "age_s": 0,
    "text": "matrix A",
    "addr": "0x00000400",
    "state": "armed"
  },
  "declarations": {
    "persistent": true,
    "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/mame-live-matrix-state-t5au50_9/mame-debug/declarations.json"
  },
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end comment_delete -->

MAME also keys a comment by a CRC of the instruction bytes under it, so code that moves in RAM hides its comment in the pane while the store keeps it, and a delete over bytes that changed since leaves MAME holding it, hidden, until `close`.

<!-- scry-reference:begin comment_save -->
## `comment_save`

*Save the comments to a file*

```text
comment_save(dest)
```

Write every comment of the store, every cpu, to `dest`, the comment file (REFERENCE.md): a
header line, then one line per comment, `ref`, `cpu`, `created_at` and `text` separated by
tabs, sorted, so a project versions it beside its symbol file. Answers on a running machine
too.

Arguments: `dest`, absolute or `~`-led, in a directory that exists, with no comma, semicolon, quote, whitespace, bracket or control character. A file there is REPLACED only when it is a comment file this
server reads whole (the header, then every row by the format); anything else, a directory, a
link, a FIFO or a device, and the declaration store's own file are refused naming why and left
as they are.
A new file is readable by others; a replaced one keeps its mode.

Reply: `path`, `comments_total` (rows written), `dropped_comments` (each `ref` and `cpu` the
replaced file held and the store does not, at most 24), `dropped_total`,
`truncated`, `note`. A file that cannot be written: `host_failed`.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `dest` | string | required |

| reply field | type |
|---|---|
| `comments_total` | integer |
| `dropped_comments` | array |
| `dropped_total` | integer |
| `note` | string |
| `path` | string |
| `truncated` | boolean |

Example, from a live run:

```json
{
  "dest": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f7.tsv"
}
```

```json
{
  "summary": "comment_save: 1 comment to $TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f7.tsv",
  "status": "ok",
  "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f7.tsv",
  "comments_total": 1,
  "dropped_comments": [],
  "dropped_total": 0,
  "truncated": false
}
```
<!-- scry-reference:end comment_save -->

<!-- scry-reference:begin comment_load -->
## `comment_load`

*Load comments from a file*

```text
comment_load(path)
```

Read the comment file at `path` (absolute) into the store and MAME's pane, all or
nothing: a bad header, a row short of a column, a text or ref that breaks the format, a cpu
this machine lacks, an address past its space, or one place named twice refuses the whole
file naming the line. `0x` and hex is an address, anything else a symbol. Where the store
already comments a place the file comments, the FILE wins; rows only the store holds stay.
Needs the machine STOPPED (else `not_stopped`).

Reply: `path` (the file read), `parsed` (rows read), `added`, `replaced_comments` (each store
row the file replaced, whole, at most 24), `replaced_total`, `truncated`,
`unchanged` (places already holding the file's text, a stale one brought to this
build), `comments_total` (the store's after), `declarations` (`persistent`, `path`), `note`. A
store that cannot be written: `host_failed` with `held_in_memory: true`.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `path` | string | required |

| reply field | type |
|---|---|
| `added` | integer |
| `comments_total` | integer |
| `declarations` | object |
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
  "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f7.tsv"
}
```

```json
{
  "summary": "comment_load: 1 read, 0 added, 0 replaced",
  "status": "ok",
  "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f7.tsv",
  "parsed": 1,
  "added": 0,
  "replaced_comments": [],
  "replaced_total": 0,
  "truncated": false,
  "unchanged": 1,
  "comments_total": 1,
  "declarations": {
    "persistent": true,
    "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/mame-live-matrix-state-t5au50_9/mame-debug/declarations.json"
  }
}
```
<!-- scry-reference:end comment_load -->

Two rows a rebuild put at one place are both loaded, so what `comment_save` writes of such a store reads back. The first file row at a place the store comments replaces the store's row and any other comes in beside it (a `stale` row of the other kind excepted).
