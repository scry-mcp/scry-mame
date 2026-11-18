# The Timeline tools

These three tools follow a board's graphics over time. `gfx_load` loads the project's `gfx.yaml`, the file that states what a project knows about its board's graphics. `gfx_film` shows the frames in which a write happened, as pictures, and `palette_log` records which code set each palette entry, which MAME calls a pen.

Every entry of a `gfx.yaml` carries a `status` and a non-empty `source`. `proved` means checked against the machine by something that could have failed, which `source` names. `declared` means copied from a driver line or a datasheet, and `human` is a person's choice.

With a manifest loaded, a `layout` argument of the Screen tools may be a format's name. How a picture is attached and which instant it shows are on [Screen](screen.md).

<!-- scry-reference:begin gfx_load -->
## `gfx_load`

Load a project's `gfx.yaml`, the file that names its tile formats, graphics assets, draw commands and palette ports for the other tools.

```text
gfx_load(path)
```

### Try it

On Gridlee, a free ROM from mamedev.org, at any stop. The manifest is the tour's, `docs/reference/tour/gridlee-gfx.yaml` in this repository.

Ask:

> Load the graphics manifest the tour keeps for Gridlee.

Call:

```text
gfx_load(path="./docs/reference/tour/gridlee-gfx.yaml")
```

Reply, 5 of 13 fields:

```json
{
  "summary": "gfx_load ./docs/reference/tour/gridlee-gfx.yaml: 1 format, 1 ... (125 characters)",
  "draft": false,
  "formats": {"sprite": "proved"},
  "assets": {
    "sprites": {"format": "sprite", "tag": "gfx1", "palette": "palette"}
  },
  "status_counts": {"proved": 9, "declared": 0, "human": 0}
}
```

One format and one asset, and all nine entries of the file are `proved`. The asset `sprites` reads the region `gfx1` in the format `sprite`, with the palette device `palette`.

<details><summary>The whole reply</summary>

```json
{
  "summary": "gfx_load ./docs/reference/tour/gridlee-gfx.yaml: 1 format, 1 asset, 1 command, 0 palette ports; 9 proved, 0 declared, 0 human",
  "status": "ok",
  "loaded": true,
  "replaced_path": {"available": false, "why": "no manifest was loaded in this session before this one"},
  "path": "./docs/reference/tour/gridlee-gfx.yaml",
  "sha256": "b79a770ebbbc34d15656c24e1aa3ec68ed95065ab8dc3606d69c43845846e753",
  "draft": false,
  "systems": ["gridlee"],
  "formats": {"sprite": "proved"},
  "assets": {
    "sprites": {"format": "sprite", "tag": "gfx1", "palette": "palette"}
  },
  "commands": {
    "player": {
      "block": "0x0000000c",
      "length": 4,
      "trigger_addr": "0x00000010",
      "fires_with": "any write",
      "asset": "sprites",
      "roles": ["dest_x", "dest_y", "height", "source_tile", "width"],
      "flags": [],
      "planes": []
    }
  },
  "palette_ports": {},
  "status_counts": {"proved": 9, "declared": 0, "human": 0}
}
```

</details>

### Arguments

- `path` (string, required): The absolute path of the `gfx.yaml`. A load replaces the one before.

### What comes back

- `draft`: `true` when the first line is `gfx_draft`'s draft marker. Deleting that line confirms the draft.
- `formats`: Each format's name with its status.
- `assets`: Each asset's `format`, `tag` and `palette`.
- `commands`: Each draw command: its `block` address and `length`, its `trigger_addr` and the value it `fires_with`, its `asset`, `roles`, `flags` and `planes`.
- `palette_ports`: Each entry's `palette`, `space`, `protocol`, `index_port`, `data_port`, `index_flag_mask`, `order`, `component_bits`, `components_bit_reversed` and `pen_range`.
- `status_counts`: How many entries are `proved`, `declared` and `human`.

<details><summary>All 13 reply fields</summary>

- `assets` (object)
- `commands` (object)
- `draft` (boolean)
- `formats` (object)
- `loaded` (boolean)
- `palette_ports` (object)
- `path` (string)
- `replaced_path` (string or object)
- `sha256` (string)
- `status_counts` (object)
- `still_loaded` (string or object)
- `system` (string)
- `systems` (array)

</details>

### What it refuses

- An unknown or missing key, a wrong type or a name that points at nothing; the message gives its full path (`bad_argument`).
- YAML outside the subset the reader takes; the message names the line (`bad_argument`).
- A manifest whose `systems` does not list the session's system (`bad_argument`).
- A `path` that is not absolute (`bad_argument`).

### Why it works this way

The file is checked whole, so a half-loaded manifest never answers a later call. A misspelt key is refused with its full path, such as `commands.blit.fields.dest_x.parts[1].maks`, because a key silently ignored is a setting silently left at its default. A refusal keeps the previous load and names it in `still_loaded`.

A manifest states what a project knows, and nothing in it runs; it loads while the program runs too. It holds no measured figure, which would go out of date there: a figure belongs in the report or the commit that measured it.

The reader takes a subset of YAML and refuses a value another YAML reader could type differently: `no`, `012`, `1e3`, a date, `1:20`. Quote such a value. Anchors, tags, block scalars, tabs and duplicate keys are outside the subset.

<details><summary>More on why</summary>

The format of a `gfx.yaml`, as a small manifest that loads:

```yaml
schema: 1
systems: [myboard]                 # the MAME systems it describes
formats:
  chars:
    layout:                        # as gfx_view takes one
      width: 8
      height: 8
      planes: 1
      planeoffset: [0]
      xoffset: '{ STEP8(0,1) }'
      yoffset: '{ STEP8(0,8) }'
      charincrement: 8*8
    status: declared
    source: myboard.cpp charlayout
assets:
  font: {format: chars, tag: gfx1, palette: palette, status: declared, source: myboard.cpp}
commands:
  blit:
    # the registers a capture watch records, and the write that makes a row a blit
    block: {address: 0x700000, words: 16, word_bytes: 2, status: declared, source: myboard.cpp}
    fire: {word: 15, value: 0xffff, status: declared, source: myboard.cpp}
    asset: font
    fields:                        # the roles the server computes with
      dest_x:
        parts:
          - {word: 0, mask: 0x00ff}
          - {word: 7, mask: 0x0040, at: 8}
        status: proved
        source: the boxes checked against the screen
      dest_y: {parts: [{word: 2, mask: 0x00ff}], status: declared, source: myboard.cpp}
      width: {const: 8, status: declared, source: myboard.cpp}
      height: {const: 8, status: declared, source: myboard.cpp}
palette_ports:
  ramdac:
    palette: palette
    index_port: 0x720001
    data_port: 0x720003
    order: [r, g, b]
    component_bits: 8
    auto_increment: true
    status: declared
    source: myboard.cpp
```

An asset may add `offset`, `pen_base` and `wrap`, for coordinates that wrap inside a tile. A command's `block` may name its `cpu`. Its `fire` is a `word` of the block with a `value`, or an `address` outside the block; with no `value`, every write there fires.

The roles are `dest_x`, `dest_y`, then `dest_x_end` and `dest_y_end` (inclusive) or `width` and `height`; `dest_dir_x`, `dest_dir_y`; `source_x`, `source_y`, `source_tile`, `source_dir_x`, `source_dir_y`; `plane`; `reads_source`. Anything else to show goes under `flags`, read the same way and never interpreted.

A field is a list of `parts`: each takes the bits of `mask` from one `word`, low bit first, and puts them from bit `at` of the value. An optional `add` is added, and `sign: -1` reads a value stored reversed. A fixed size is a `const`, and a one-bit role says with `asserted` which value means it holds.

A command's `planes` each have a `name` and the `width` and `height` they wrap at. One is picked by the `plane` role's value (`when`), and a higher `order` is drawn over a lower. `origin_x` and `origin_y` are an integer or `{field, scale, add}` read from the blit's own row, and `page` names the field that says which page.

A `palette_ports` entry may add `cpu`, `space` (`program` or `io`), `pen_base`, `pen_count` and `protocol`; `component_bits` is 1 to 8. Two entries on one palette may not set the same pens.

`protocol` is `ramdac` (the default), `latch`, which needs `index_flag_mask` and may leave `index_port` out, or `sequence`. The last two may set `components_bit_reversed`. `pen_count` is a power of two up to 1024, and always 256 for `ramdac`.

A section named `ramdacs` is read as `palette_ports`, and `note` says so. The reply also carries the file's `sha256` and its `systems`.

</details>

### Related tools

- [`gfx_draft`](screen.md#gfx_draft)
- [`gfx_view`](screen.md#gfx_view)
- [`gfx_blits`](screen.md#gfx_blits)
- [`palette_log`](#palette_log)
- [`gfx_locate`](screen.md#gfx_locate)

<details><summary>The contract your client receives</summary>

```text
Load a project's `gfx.yaml` (an ABSOLUTE `path`): `formats`, `assets`, draw `commands`,
`palette_ports`. A load replaces the previous one; answers while running.

Judged whole: an unknown or missing key, wrong type or dangling name is `bad_argument`
naming its path; a manifest not listing the session's `system` is refused (`still_loaded`).

Reply: `loaded`, `replaced_path`, `path`, `draft`, `formats`, `assets`, `commands`,
`palette_ports`, `status_counts`, `note`.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end gfx_load -->

<!-- scry-reference:begin gfx_film -->
## `gfx_film`

Keep a picture of each frame in which a chosen write happened, and read them back as one contact sheet.

```text
gfx_film(trigger="", length=1, value=null, changed=false, pc="", cpu="", frames=600, keep=12,
    crop=null, film_dir="", first=0, clear=false, seconds=5.0, space="program")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped in attract mode with the tour's symbols loaded, so `credits` names the byte that counts coins.

Ask:

> Keep a picture of every frame in the next 90 where the game writes its credits, two pictures at most.

Call:

```text
gfx_film(trigger="credits", frames=90, keep=2, film_dir="./tmp/demos/tour/film")
```

Reply, 4 of 26 fields:

```json
{
  "summary": "gfx_film on credits: armed, installed when the console next reads a line",
  "armed_now": true,
  "installed": false,
  "pending": true
}
```

Then, after a coin and those 90 frames, read the film:

Call:

```text
gfx_film()
```

Reply, 5 of 26 fields:

```json
{
  "summary": "gfx_film on credits: finished, 90 judged, 1 met, 1 kept; 792x864 PNG x3, inline",
  "state": "finished",
  "judged": 90,
  "met": 1,
  "kept": 1
}
```

The film waits to be installed, then checks 90 frames (`judged`). One of them held a write to `credits` (`met`), and its picture was kept.

<details><summary>The two replies, whole</summary>

The first call's:

```json
{
  "summary": "gfx_film on credits: armed, installed when the console next reads a line",
  "status": "ok",
  "armed_now": true,
  "film": {
    "trigger": "credits",
    "trigger_addr": "0x0000042b",
    "length": 1,
    "value": {"available": false, "why": "no `value` was given"},
    "changed": false,
    "pc": {"available": false, "why": "no `pc` was given"},
    "pc_addr": {"available": false, "why": "no `pc` was given"},
    "cpu": ":maincpu",
    "frames": 90,
    "keep": 2,
    "crop": {"available": false, "why": "no `crop`: the whole screen"},
    "film_dir": "./tmp/demos/tour/film",
    "screen": ":screen",
    "checked": true,
    "space": "program"
  },
  "trigger_maps_to": "memory@0",
  "tally_id": "film",
  "installed": false,
  "pending": true,
  "install_call": "MAME_MCP_LUA_END#5",
  "install_lines_ahead": 0,
  "note": "the film judges from the first whole frame after the install, which runs when the console next reads a line; read it with `gfx_film()`",
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#4",
  "pc_before": "0x0000a7d5",
  "cause": "gfx_film: one step",
  "stop_seq": 6,
  "pc": "0x0000a7dd",
  "cpu": ":maincpu",
  "frame": 419,
  "regs": {
    "A": "0x00",
    "B": "0x00",
    "D": "0x0000",
    "X": "0x0150",
    "Y": "0x00e1",
    "U": "0x00e3",
    "PC": "0xa7dd",
    "S": "0x07fe",
    "CC": "0x84",
    "DP": "0x00"
  },
  "instruction": {"address": "A7DD", "bytes": "33A4", "text": "LEAU   ,Y", "symbol": "wait_frame", "delta": 428},
  "following": ["A7DF: 31 3E       LEAY   -$2,Y", "A7E1: 11 93 80    CMPU   <$80", "A7E4: 26 E6       BNE    $A7CC", "A7E6: DE 84       LDU    <$84", "A7E8: 31 5E       LEAY   -$2,U", "A7EA: DC 80       LDD    <$80", "... 6 more"],
  "errorlog": "<volatile>"
}
```

The second call's:

```json
{
  "summary": "gfx_film on credits: finished, 90 judged, 1 met, 1 kept; 792x864 PNG x3, inline",
  "status": "ok",
  "film": {
    "trigger": "credits",
    "trigger_addr": "0x0000042b",
    "length": 1,
    "value": {"available": false, "why": "no `value` was given"},
    "changed": false,
    "pc": {"available": false, "why": "no `pc` was given"},
    "pc_addr": {"available": false, "why": "no `pc` was given"},
    "cpu": ":maincpu",
    "frames": 90,
    "keep": 2,
    "crop": {"available": false, "why": "no `crop`: the whole screen"},
    "film_dir": "./tmp/demos/tour/film",
    "screen": ":screen",
    "checked": true,
    "space": "program"
  },
  "tally_id": "film",
  "installed": true,
  "pending": false,
  "cpu": ":maincpu",
  "state": "finished",
  "frame_as_of": 543,
  "superseded": false,
  "callback_errors": {
    "count": 0,
    "first": {"available": false, "why": "no callback raised"}
  },
  "judged": 90,
  "judged_frames": [420, 509],
  "met": 1,
  "kept": 1,
  "refused": 0,
  "dropped_total": 0,
  "dropped_frames": {"available": false, "why": "no frame was dropped"},
  "lost": {},
  "pending_picture": false,
  "cost": "<volatile>",
  "listing_path": "./tmp/demos/tour/film/film.json",
  "cells": [
    {
      "k": 1,
      "frame": 425,
      "hits_in_frame": 1,
      "hit_counters": [425, 425],
      "pc": "0x0000b583",
      "value": "0x02",
      "symbol": "count_coin",
      "path": "./tmp/demos/tour/film/frame-1.png"
    }
  ],
  "listed": {"first": 0, "count": 1, "of": 1},
  "image": {
    "path": "./tmp/demos/tour/film/sheet-0.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 792,
    "height": 864,
    "scale": 3,
    "indexed": false,
    "inline": true
  },
  "animation": {
    "path": "./tmp/demos/tour/film/film-anim.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "frames": 1,
    "frame_period_s": 0.016896
  }
}
```

</details>

### Arguments

- `trigger` (string, default `""`): The address or symbol whose write is watched. Giving it arms the film, with the program stopped; left empty, the call reads the film.
- `length` (one of `1`, `2`, `4`, default `1`): How many bytes the write covers: 1, 2 or 4. Left out, 1.
- `value` (integer or string, optional): Only a write of this value counts: an integer or a `0x` string. Not taken with `changed`.
- `changed` (boolean, default `false`): `true` counts only a write whose value differs from the one before.
- `pc` (string, default `""`): Only a write made from this address or symbol counts.
- `cpu` (string, default `""`): The cpu whose memory `trigger` is in. Left empty, the one the debugger is showing.
- `frames` (integer, default `600`): How many frames the film checks before it finishes, up to 216000. Left out, 600.
- `keep` (integer, default `12`): How many pictures it keeps, up to 64. Left out, 12.
- `crop` (array of integer, optional): The rectangle of the screen each picture keeps, `[x, y, width, height]`. Left out, the whole screen.
- `film_dir` (string, default `""`): A new absolute folder for the film's files. Left empty, a new folder in the session's temporary folder.
- `first` (integer, default `0`): When reading, the first kept frame the sheet shows, counted from 0.
- `clear` (boolean, default `false`): `true` removes the film. Its files stay.
- `seconds` (number (> 0, <= 600.0), default `5.0`): The time limit of the read that arms the film, in seconds. Reading the sheet is not timed.
- `space` (one of `"program"`, `"io"`, default `"program"`): `io` when `trigger` is an I/O port. Left out, `program`, the cpu's memory.

### What comes back

- `armed_now`: `true` on the call that arms the film. It starts at the first whole frame after it is installed.
- `film`: What the film was armed with, and `checked`: whether each kept frame is compared with MAME's own rendering.
- `state`: When reading: `judging` while frames are still being checked, then `finished`. Before any result it is `no_dump_yet`, `install_failed` or `install_lost`, with `why`.
- `met`: How many of the `judged` frames held the write. `kept` counts the pictures kept and `refused` those that failed their check.
- `cells`: One row per kept frame on this page: `k`, `frame`, `hits_in_frame`, `hit_counters`, the first hit's `pc`, `symbol` and `value`, and the picture's `path`.
- `image`: The contact sheet of this page, once a frame is kept. `next_first` starts the next page.

<details><summary>All 57 reply fields</summary>

- `console_reruns` (integer)
- `cpu` (string)
- `following` (array of string)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer)
- `pc` (string)
- `regs` (object)
- `resent` (integer)
- `stop_seq` (integer)
- `thread_errors` (integer)
- `watches` (array)
- `animation` (object)
- `armed_now` (boolean)
- `baseline_value` (string or object)
- `call` (string)
- `callback_errors` (object)
- `cells` (array)
- `cleared` (boolean)
- `cost` (object)
- `cpus_with_io` (array)
- `dropped_frames` (array or object)
- `dropped_total` (integer)
- `evaluated_by` (string)
- `files_kept` (string)
- `film` (object)
- `frame_as_of` (integer)
- `frame_baseline` (integer or object)
- `height` (integer)
- `image` (object)
- `install_call` (string)
- `install_lines_ahead` (integer)
- `install_resent` (integer)
- `installed` (boolean)
- `judged` (integer)
- `judged_frames` (array or object)
- `kept` (integer)
- `lines_ahead` (integer)
- `listed` (object)
- `listing_path` (string)
- `lost` (object)
- `met` (integer)
- `next_first` (integer)
- `nothing_kept` (string)
- `pc_before` (string)
- `pending` (boolean)
- `pending_picture` (boolean)
- `reader_steps` (integer)
- `refused` (integer)
- `refused_frames` (array)
- `removal` (string)
- `state` (string)
- `superseded` (boolean)
- `tally_id` (string)
- `trigger_maps_to` (string)
- `why` (string)
- `width` (integer)

</details>

### What it refuses

- Arming while the program runs (`not_stopped`); reading and clearing need no stop.
- A second film while one is armed: one a session (`bad_argument`).
- A read with no film armed (`needs_call`).
- `value` together with `changed`, or an argument that arming, reading or clearing does not take (`bad_argument`).
- A `trigger` whose `length` bytes cross a bus word: one bus write must cover them (`bad_argument`).
- A `first` past the kept frames, or a `crop` off the screen (`bad_argument`).

### Why it works this way

A breakpoint cannot follow a write that happens many times a frame. So the film runs inside MAME at full speed: a hook on the write marks the frame, and at the frame's end only a marked frame has its picture kept.

A register a game writes every frame meets a fixed `value` on nearly every frame, which records everything and filters nothing. `changed` is the question a film is usually asked. Its `pc` filter applies to the write, not to the value it is compared with, and a reset or a state load starts no new comparison.

A write made during vblank belongs to this frame's picture, yet MAME's frame counter still reads the frame before. So each hit keeps the counter it read. A row joins `gfx_blits(frame=...)` and a capture's rows by `hit_counters`, never by `frame`, which names the picture.

<details><summary>More on why</summary>

Each picture is read one frame late, at the next frame's end. MAME turns the screen's double buffer over before its frame notifiers run, so one of them reads the frame that ended only after the next turn. That rule says nothing about a read at a debugger stop, which [Screen](screen.md) covers.

With frameskip the buffer turns only on a frame that was drawn, so a frame that held the write and was skipped is counted in `lost`.

Where MAME's snapshot is the bare screen, each kept frame is compared with it pixel for pixel, and one that differs is refused with no picture. `refused_frames` gives each one's `k`, `code` and `why`.

Elsewhere the film says `checked: false`, and `mismatch` measures how the snapshot differed at the stop where the film was armed. It asserts no cause: its `candidates` names the one its rule leaves standing.

| in `candidates` | when |
|---|---|
| `orientation` | a mirrored screen equals the snapshot |
| `frame_lag` | no mirror, and every differing pixel is in a pen's colour |
| `colour_adjustment` | each screen colour is drawn as one snapshot colour, no two alike |
| `overlay_or_artwork` | anything else, and a snapshot of another size, where nothing is compared |

A `start` does not arm the film again. A film spends its frames and pictures from the moment it is armed, and a new start would spend them on the boot. `clear` keeps the files, and a later film writes into a folder of its own.

- `frame-K.png`: one per kept frame.
- `film.json`: every kept frame with its file, `sha256`, check, `hits_in_frame`, `hit_counters` and first hits, and every refused one with its reason.
- `sheet-F.png`: one per page read.
- `film-anim.png`: every kept frame as an animation, never attached.

`cost` is the frame notifier's own host time inside MAME; the hook's cost per write is not in it.

</details>

### Related tools

- [`gfx_blits`](screen.md#gfx_blits)
- [`watch_add`](breakpoints.md#watch_add)
- [`palette_log`](#palette_log)
- [`series_capture`](captures.md#series_capture)
- [`record`](captures.md#record)
- [`captures`](captures.md#captures)

<details><summary>The contract your client receives</summary>

```text
The frames in which a write happened; one film per session.

Arm (STOPPED): `trigger` (symbol or `0x` on `cpu`; `space` `io` for a port) is a write of
`length` bytes, from `pc`, carrying `value` (an integer or a `0x` string), or with `changed=True` a value
unlike the one before. Judges `frames` (max 216000), keeps `keep` pictures (max
64) cropped to `crop`, into a new absolute `film_dir`.

Read (no `trigger`; works while running): a contact sheet from `first`. `clear=True` clears.
`seconds` bounds the read that arms the film, not the sheet's.

Reply (arm): `film`, `armed_now`. Reply (read): `film`, `state`, `judged`, `met`, `kept` (once
the film has dumped), `cells` (each `frame`, `pc`, `path`), `image` (once frames are kept),
`next_first` (more kept frames remain). `bad_argument`: film armed
already, none to read.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end gfx_film -->

<!-- scry-reference:begin palette_log -->
## `palette_log`

Find which code set a pen's colour on a board whose palette cannot be read back, by logging every write to its palette ports.

```text
palette_log(palette_port, pen=null, limit=16, clear=false, arm=false)
```

### Try it

This tool needs a board that sets its colours through ports; Gridlee's are fixed in PROMs, and neither free program has such a board. The reply shown comes from a test program that is not distributed.

Ask:

> Start logging every write to this board's palette ports, so I can ask later which code set a pen.

Call:

```text
palette_log(palette_port="ramdac", arm=true)
```

Reply, 6 of 20 fields:

```json
{
  "summary": "palette_log ramdac: armed, installed when the console next reads a line",
  "protocol": "ramdac",
  "index_port": "0x00720001",
  "data_port": "0x00720003",
  "installed": false,
  "pending": true
}
```

The log is armed on the two ports of the entry `ramdac`, an index port and a data port. It is not installed yet (`pending`): that happens when the console next reads a line, and it records from there.

<details><summary>The whole reply</summary>

```json
{
  "summary": "palette_log ramdac: armed, installed when the console next reads a line",
  "status": "ok",
  "palette_port": "ramdac",
  "palette": "palette",
  "cpu": ":maincpu",
  "space": "program",
  "protocol": "ramdac",
  "index_port": "0x00720001",
  "data_port": "0x00720003",
  "order": "rgb",
  "component_bits": 8,
  "pen_range": [0, 255],
  "armed_now": true,
  "tally_id": "ramdac_720001_1_720003",
  "installed": false,
  "pending": true,
  "lines_ahead": 0,
  "call": "MAME_MCP_LUA_END#15",
  "note": "the tap is installed when the console next reads a line (a step, the next frame emulated, or a debugger command on a stub that refreshes after one) and counts from there; the survey of the stop after that reads it back",
  "not_proved": ["palette_ports.ramdac"]
}
```

</details>

### Arguments

- `palette_port` (string, required): The name of an entry under `palette_ports` in the loaded `gfx.yaml`.
- `pen` (integer or string, optional): Show this pen alone: its state and the rows that wrote it. Left out, the reply lists the writers of every pen.
- `limit` (integer (>= 0, <= 256), default `16`): How many of the newest rows the reply shows, 0 to 256. Left out, 16.
- `clear` (boolean, default `false`): `true` removes the log.
- `arm` (boolean, default `false`): `true` starts the log. Without it the call reads the log, and never starts one.

### What comes back

- `installed`: `false` on the call that arms it. The log is installed when the console next reads a line, at a step or the next frame run, and records from there.
- `state`: Once armed: `logged` when there is a table to read. Otherwise `no_dump_yet`, `install_failed` or `install_lost`, with `why`.
- `writes_total`: Every write the log saw. `unsynced_writes` landed while the device's index was not known, and `desyncs` counts the times it was lost.
- `setters`: Without `pen`, the first 32 writers, most pens first: `pc`, `symbol`, `written_by`, how many `pens_set` and `which`. `setters_path` holds them all.
- `pen_state`: With `pen`: its `color`, whether it is `complete`, its `components`, its `writes_total` and the `last` write.
- `rows`: The newest `limit` rows in order, each with `n`, `frame`, `pc`, `written_by`, the screen `line`, `time_s`, and the `pen`, `component`, `value` and `color` it left.

<details><summary>All 46 reply fields</summary>

- `across` (array)
- `armed_now` (boolean)
- `call` (string)
- `callback_errors` (object)
- `cleared` (boolean)
- `component_bits` (integer)
- `cpu` (string)
- `cpus_with_io` (array)
- `data_port` (string)
- `desyncs` (integer)
- `frame_as_of` (integer)
- `index_port` (string)
- `index_writes` (integer)
- `install_resent` (integer)
- `installed` (boolean)
- `lines_ahead` (integer)
- `not_proved` (array)
- `order` (string)
- `overflow_rows` (integer)
- `palette` (string)
- `palette_port` (string)
- `palette_ports` (array)
- `partial_writes` (integer)
- `pen_range` (array)
- `pen_state` (object)
- `pending` (boolean)
- `pens_written` (array)
- `protocol` (string)
- `removal` (string)
- `rows` (array)
- `rows_cut` (boolean)
- `rows_kept` (integer)
- `rows_max` (integer)
- `rows_path` (string)
- `sees_reset_and_load` (boolean)
- `setters` (array)
- `setters_path` (string or object)
- `setters_total` (integer)
- `space` (string)
- `state` (string)
- `superseded` (boolean)
- `synced_at_start` (boolean)
- `tally_id` (string)
- `unsynced_writes` (integer)
- `why` (string)
- `writes_total` (integer)

</details>

### What it refuses

- No manifest loaded, or a read with no log armed; the message gives the call that arms it (`needs_call`).
- A `palette_port` the manifest does not have (`unknown_ref`).
- A `pen` the entry does not set (`bad_argument`).
- `arm` with `clear`, or `pen` or `limit` with either (`bad_argument`).
- A log armed from an entry the manifest has since changed: clear it and arm it again (`needs_call`).

### Why it works this way

A RAMDAC takes an index on one port and the colour's components one after another on a second port, so a data write names no pen. Which pen it landed on is known only by following the device from its last index write, which the log does inside MAME with the rule of MAME's own `ramdac_device`.

Until the first index write after arming, a reset or a state load, the index is not known. A write then counts in `unsynced_writes` and is given to no pen, because a guessed index is a plausible wrong pen.

`written_by` is `guest` for the program, or `debugger` for a write made while the machine stood in the debugger, whose `pc` is where the machine stood and not a writer. Rows carry the screen `line` being drawn and `time_s`, so a palette write in the middle of a frame can be ordered against another cpu's captured writes.

<details><summary>More on why</summary>

A stop asked for from outside is requested before the cpu reaches the instruction it stops at, so the program's last instruction still counts as `guest`. Every call of this tool answers while the program runs.

The other two protocols put a whole colour in one word, read little-endian from the port up to the end of its bus word. A big-endian bus, or an index port inside the data port's bus word, fails when the log is installed (`install_failed`).

`latch`: a data word with a bit of `index_flag_mask` set sets the index to its low bits; any other word is the indexed pen's colour, written whole. A write to `index_port` merges into the index under its mask. While the index is unknown, only a write covering every index bit makes it known.

`sequence`: each data write merges into the stored word of the pen at the current offset, under its mask. Any write to `index_port`'s bus word sets the offset back to 0.

A driver that zeroes that offset as its video starts leaves a log armed right after `start` knowing it (`synced_at_start`). Armed anywhere else, the log waits for a write a game may never make again.

In both, a pen has a colour only once every colour bit of its word has been seen written. A write that merges into bits the log never saw counts in `partial_writes`, and the pen has no colour until they are.

A row of an index write carries `index`, and one of a whole-colour write `word` and `mask`. A row that landed on no pen says `unsynced`; one where the index was lost says `desync` and `why`.

</details>

### Related tools

- [`gfx_load`](#gfx_load)
- [`screen_view`](screen.md#screen_view)
- [`palette`](screen.md#palette)
- [`gfx_film`](#gfx_film)
- [`watch_add`](breakpoints.md#watch_add)

<details><summary>The contract your client receives</summary>

```text
Who set this pen's colour, on a board whose colour RAM is write-only: every write to the
ports of the loaded manifest's `palette_port`, placed on its pen by the device's law.

`arm=True` arms the log; without it a call reads it; `clear=True` removes it. `pen` shows
that pen alone, `limit` the newest rows. Answers while running. Rows are capped at
100000, the rest counted.

Reply: `palette_port`, `protocol`, `armed_now`, `installed` (unless `clear`), `state`
(once armed), `writes_total`, `unsynced_writes`, `desyncs`, `rows_path` (once the log has
dumped). Without `pen`: `setters` (each `pc`, `symbol`,
`written_by`; the first 32). With `pen`: `pen_state`, `rows`.
`needs_call`: no manifest, entry or armed log; `bad_argument`: a pen it does not set.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end palette_log -->
