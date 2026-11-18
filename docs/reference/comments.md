# The Comments tools

A comment is one line of text on an address of the program. The server saves it with the breakpoints and watches and feeds it to MAME's own disassembly, and a stop's `instruction` carries it as `comment`.

MAME's disassembly is a view of the saved comments, never the record. A comment is saved first; one the view cannot show stays saved and reads `unarmable`, with the reason in `why`.

By symbol a comment follows the symbol through a rebuild; by address it goes `stale` once the build changes. The file a project keeps them in is described in [REFERENCE.md, Breakpoints and watches](../../REFERENCE.md#breakpoints-and-watches).

<!-- scry-reference:begin comment_list -->
## `comment_list`

List every saved comment, or one cpu's, each with its address and whether MAME's disassembly shows it.

```text
comment_list(cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped at reset, right after the comment of the entry below was added.

Ask:

> Which comments are saved for this game?

Call:

```text
comment_list()
```

Reply, 5 of 7 fields:

```json
{
  "summary": "comment_list: 1 comment",
  "status": "ok",
  "comments_total": 1,
  "truncated": false,
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"}
}
```

One comment is saved, and `truncated` is `false`: the reply lists every one. No cpu was named, so the rows are every cpu's.

<details><summary>The whole reply</summary>

```json
{
  "summary": "comment_list: 1 comment",
  "status": "ok",
  "comments": [
    {
      "ref": "count_coin",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": "<volatile>",
      "text": "a coin: INC credits, then the BCD copy",
      "addr": "0x0000b583",
      "state": "armed"
    }
  ],
  "comments_total": 1,
  "truncated": false,
  "declarations": {"persistent": true, "path": "./tmp/demos/tour/gridlee-states/declarations.json"},
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"}
}
```

</details>

### Arguments

- `cpu` (string, default `""`): Lists this cpu's comments only. Left empty, every cpu's.

### What comes back

- `comments`: The comments this reply shows. Each row has `ref`, `text`, `addr` once resolved, `state`, and `why` when it is not shown.
- `comments_total`: How many comments are saved, listed or not.
- `truncated`: `true` when there are more comments than the reply lists. `comment_write(method="save")` writes them all.
- `declarations`: The saved breakpoints file the comments live in: its `path`, and `persistent`, `false` when they last only this session.

<details><summary>All 5 reply fields</summary>

- `comments` (array)
- `comments_total` (integer)
- `cpu` (string or object)
- `declarations` (object)
- `truncated` (boolean)

</details>

### What it refuses

- A cpu the machine does not have (`unknown_ref`).

### Why it works this way

It reads the saved comments and asks the machine nothing, so it answers while the program runs.

MAME also ties a comment to a checksum of the instruction bytes under it. Code that moves in RAM hides its comment in MAME's disassembly, while the comment stays saved.

<details><summary>More on why</summary>

What `state` says of a comment:

- `armed`: MAME's disassembly shows it.
- `unarmable`: saved but not shown. `why` says the reason.
- `unresolved`: its symbol is not in this build.
- `stale`: a raw address saved over another build.

- Each row also carries `by`, `cpu`, `created_at`, `origin`, `inherited` and `age_s`, as a saved breakpoint's row does.
- A rebuild can bring several comments to one address. All are kept: MAME's disassembly shows the first it can, and each other reads `unarmable`.
- A field with nothing to give is an object: `available` is `false` and `why` says the reason, as `cpu` when none was named.
- While the machine runs the reply adds `last_stop`.

</details>

### Related tools

- [`comment_write`](#comment_write)
- [`disassemble`](read.md#disassemble)
- [`declaration_list`](breakpoints.md#declaration_list)

<details><summary>The contract your client receives</summary>

```text
Every comment of the store, or `cpu`'s. Answers on a running machine too.

Reply: `comments` (each `ref`, `text`, `addr`, `state`; at most 24),
`comments_total`, `truncated`, `declarations`, `cpu`.

Reference: REFERENCE.md, Breakpoints and watches.
```

</details>
<!-- scry-reference:end comment_list -->

<!-- scry-reference:begin comment_write -->
## `comment_write`

Change the saved comments: add or delete one, or save them all to a file and load them back.

```text
comment_write(method, ref="", text="", cpu="", dest="", path="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped at reset with the example session's symbol file loaded, which names the coin routine `count_coin`.

Ask:

> Leave a note on the coin routine: a coin increments the credits, then the BCD copy.

Call:

```text
comment_write(method="add", ref="count_coin", text="a coin: INC credits, then the BCD copy")
```

Reply, 4 of 6 fields:

```json
{
  "summary": "comment_write add: count_coin at :maincpu 0x0000b583, stored, persistent",
  "status": "ok",
  "replaced_comments": [],
  "cpu": ":maincpu"
}
```

The comment is saved on `count_coin`, which is `0xb583` on the main cpu, in a file that outlasts the session. Nothing was there before, so `replaced_comments` is empty.

<details><summary>The whole reply</summary>

```json
{
  "summary": "comment_write add: count_coin at :maincpu 0x0000b583, stored, persistent",
  "status": "ok",
  "comment": {
    "ref": "count_coin",
    "by": "symbol",
    "cpu": ":maincpu",
    "created_at": "<volatile>",
    "origin": "<volatile>",
    "inherited": false,
    "age_s": "<volatile>",
    "text": "a coin: INC credits, then the BCD copy",
    "addr": "0x0000b583",
    "state": "armed"
  },
  "replaced_comments": [],
  "declarations": {"persistent": true, "path": "./tmp/demos/tour/gridlee-states/declarations.json"},
  "cpu": ":maincpu"
}
```

</details>

### The four methods

| method | what it does |
|---|---|
| `add` | Puts `text` on `ref`. A comment already there is replaced. |
| `delete` | Removes the comment at `ref`. |
| `save` | Writes every comment to the file `dest`. |
| `load` | Reads the comment file at `path` into the saved comments, all or nothing. |

### Arguments

- `method` (one of `"add"`, `"delete"`, `"save"`, `"load"`, required): `add`, `delete`, `save` or `load`, as above.
- `ref` (string, default `""`): For `add` and `delete`: a symbol or a `0x` address.
- `text` (string, default `""`): For `add`: one printable line, at most 237 UTF-8 bytes.
- `cpu` (string, default `""`): For `add` and `delete`: the cpu whose code is commented. Left empty, the one the debugger is showing.
- `dest` (string, default `""`): For `save`: the file to write, an absolute or `~`-led path. A comment file already there is replaced; any other file is refused.
- `path` (string, default `""`): For `load`: the comment file to read, an absolute path.

### What comes back

- `comment`: `add`: the comment as saved, a row as `comment_list` gives it.
- `replaced_comments`: `add` and `load`: the comments whose text was replaced, as they were.
- `deleted`: `delete`: the comment removed.
- `dropped_comments`: `save`: comments only the replaced file held, each by `ref` and `cpu`. They are gone from the file.
- `added`: `load`: how many comments are new. `unchanged` counts those already saved with the same text, `parsed` the rows read.
- `held_in_memory`: `true` when the saved breakpoints file could not be written: the change lasts until `close`.

<details><summary>All 15 reply fields</summary>

- `added` (integer)
- `comment` (object)
- `comments_total` (integer)
- `declarations` (object)
- `deleted` (object)
- `dropped_comments` (array)
- `dropped_total` (integer)
- `parsed` (integer)
- `path` (string)
- `replaced_comments` (array)
- `replaced_total` (integer)
- `truncated` (boolean)
- `unchanged` (integer)
- `cpu` (string)
- `held_in_memory` (boolean)

</details>

### What it refuses

- An argument the method does not take (`bad_argument`).
- `add`, `delete` or `load` while the program runs (`not_stopped`).
- A `ref` that is a pointer, an expression or a `seg:off`, or a `text` that is empty, too long or not one printable line (`bad_argument`).
- Bare hex that names no symbol, or a `delete` whose `ref` matches no comment (`unknown_ref`).
- A `dest` that is the saved breakpoints file itself, a link, or a file that is not a comment file (`bad_argument`).
- A `load` file with a bad row or a cpu the machine lacks: nothing is loaded (`bad_argument`).
- A saved breakpoints file that cannot be written: the change is kept in memory (`host_failed`).

### Why it works this way

The change is saved first, and MAME's disassembly is fed after. If the session breaks in between, the message says so, and the next `start` feeds the saved comments again.

One address shows one comment. An `add` where one exists replaces its text and keeps its `ref`, so a comment made by symbol keeps following its symbol.

`save` and `load` are how a project keeps its comments under version control beside its symbol file. `load` is all or nothing, and the file wins where both comment an address.

<details><summary>More on why</summary>

- A comment's `state` is `armed` once MAME's disassembly shows it. `unresolved` names a symbol this build lacks: the comment stays saved and is shown once a build has it.
- The file has no build column, so a raw address loaded into another build is trusted. Comment by symbol what must survive a rebuild.
- A rebuild can bring several comments to one address. An `add`, `delete` or `load` there reaches the one whose `ref` it spells, else the one MAME's disassembly shows.
- A `stale` comment made the other way, by symbol where yours is by address or the reverse, is reached only by its own spelling.
- `save`'s `dest` is in a folder that exists, and its path holds no comma, semicolon, quote, space, bracket or control character.
- MAME's console cannot carry a text holding `"` or ending in `\`: it is saved and reads `unarmable`. If it replaces one that was shown, the old text is cleared.
- A `delete` over instruction bytes that changed since leaves MAME holding the old text, hidden, until `close`.
- A file with two comments a rebuild put at one address loads both, so what `save` writes of them reads back.
- MAME writes its own comment files into a folder inside the session's temporary folder, so nothing deleted here comes back from them.
- `comments_total`, `dropped_total` and `replaced_total` count the whole lists; `truncated` says a list was cut. `declarations` names the saved breakpoints file, as in `comment_list`.

- The file `save` writes is UTF-8 with no byte order mark, and its lines end in LF.
- Line 1 is exactly `# comments v1: ref<TAB>cpu<TAB>created_at<TAB>text`, and each row after it holds those four columns.
- Rows are sorted by cpu, then by ref, so a diff shows only what changed.
- `cpu` is the cpu's absolute tag, and `created_at` reads `YYYY-MM-DDTHH:MM:SS+00:00`.

</details>

### Related tools

- [`comment_list`](#comment_list)
- [`disassemble`](read.md#disassemble)
- [`symbols_find`](names.md#symbols_find)
- [`declaration_list`](breakpoints.md#declaration_list)

<details><summary>The contract your client receives</summary>

```text
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
does not take, a misshapen `ref` or `text`, an unknown `ref` (`unknown_ref`), a `save`
`dest` that is the declaration store's file (compared without regard to case, on any
volume), an unwritable store (`host_failed`, `held_in_memory`).

Reference: REFERENCE.md, Breakpoints and watches.
```

</details>
<!-- scry-reference:end comment_write -->
