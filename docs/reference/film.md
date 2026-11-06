# The Film tools

The picture, which instant a decode shows and the source are on [Screen](screen.md).

**The project's knowledge** is stated once in a `gfx.yaml` (the format is under `gfx_load` below). Every entry carries a non-empty `source` and a `status`: `proved` (checked against the machine by something that could have failed, which `source` names), `declared` (transcribed from a driver line or a datasheet) or `human` (a person's choice). The file holds no figure, since it would expire there. With a manifest loaded, a `layout` argument may be a format's NAME or a sweep candidate's id.

<!-- scry-reference:begin gfx_load -->
## `gfx_load`

*Load the project's graphics manifest*

```text
gfx_load(path)
```

Load a project's `gfx.yaml` (an ABSOLUTE `path`): `formats`, `assets`, draw `commands`,
`palette_ports`. A load replaces the previous one; answers while running.

Judged whole: an unknown or missing key, wrong type or dangling name is `bad_argument`
naming its path; a manifest not listing the session's `system` is refused (`still_loaded`).

Reply: `loaded`, `replaced_path`, `path`, `draft`, `formats`, `assets`, `commands`,
`palette_ports`, `status_counts`, `note`.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `path` | string | required |

| reply field | type |
|---|---|
| `assets` | object |
| `commands` | object |
| `draft` | boolean |
| `formats` | object |
| `loaded` | boolean |
| `palette_ports` | object |
| `path` | string |
| `replaced_path` | string or object |
| `sha256` | string |
| `status_counts` | object |
| `still_loaded` | string or object |
| `system` | string |
| `systems` | array |

Example, from a live run:

```json
{
  "path": "/Users/Shared/scry-examples-20261106/bench-mame/m68k-dual/hardware/gfx.yaml"
}
```

```json
{
  "summary": "gfx_load /Users/Shared/scry-examples-20261106/bench-mame/m68k-dual/hardware/gfx.yaml: 1 format, 1 asset, 1 command, 1 palette port; 14 proved, 11 declared, 0 human",
  "status": "ok",
  "loaded": true,
  "replaced_path": {"available": false, "why": "no manifest was loaded in this session before this one"},
  "path": "/Users/Shared/scry-examples-20261106/bench-mame/m68k-dual/hardware/gfx.yaml",
  "sha256": "c595c36986dda4738dadb83211388e1251bfdf66e6f2cd02e4c1fd495c76ca1d",
  "draft": false,
  "systems": ["radendur", "wheelfir", "pwball", "kongball"],
  "formats": {"page_512x512x8": "declared"},
  "assets": {
    "pages": {"format": "page_512x512x8", "tag": "gfx1", "palette": "palette"}
  },
  "commands": {
    "blit": {
      "block": "0x00700000",
      "length": 32,
      "trigger_addr": "0x0070001e",
      "fires_with": "0xffff",
      "asset": "pages",
      "roles": ["dest_dir_x", "dest_dir_y", "dest_x", "dest_x_end", "dest_y", "dest_y_end", "... 7 more"],
      "flags": ["dest_y_half", "scroll_x", "scroll_y", "visible_page", "writes_index_0"],
      "planes": ["sprites", "background"]
    }
  },
  "palette_ports": {
    "ramdac": {
      "palette": "palette",
      "space": "program",
      "protocol": "ramdac",
      "index_port": "0x00720001",
      "data_port": "0x00720003",
      "index_flag_mask": {"available": false, "why": "only a latch's index word carries a flag"},
      "order": "rgb",
      "component_bits": 8,
      "components_bit_reversed": false,
      "pen_range": [0, 255]
    }
  },
  "status_counts": {"proved": 14, "declared": 11, "human": 0}
}
```
<!-- scry-reference:end gfx_load -->

The `gfx.yaml` format, which only this prose states: named `formats` (a `layout` in `gfx_view`'s terms), named `assets` (a region or share, a format, a palette device and first pen, whether coordinates `wrap` inside a tile) and draw `commands`.

A command is the register `block` a capture reads (`address`, `words`, `word_bytes`, `cpu`), the `fire` write that makes a row a blit (`word` and `value`, or `address` outside the block; no `value` when every write fires), the `asset`, `fields`, `flags` and `planes`.

`fields` are the ROLES the server computes with: `dest_x`, `dest_y`, either `dest_x_end`, `dest_y_end` (inclusive) or `width`, `height`; `dest_dir_x`, `dest_dir_y`; `source_x`, `source_y`, `source_tile`, `source_dir_x`, `source_dir_y`; `plane`; `reads_source`. What is shown and not interpreted goes under `flags`. A field is `parts` (the bits of `mask` from one `word`, low bit first, placed from bit `at`), plus an optional `add` and `sign: -1` for a value stored reversed; a fixed `width` or `height` is a `const`; a one-bit role says with `asserted` which value means it holds.

A plane is picked by the `plane` role's value (`when`), has a size it wraps at, an `order` (higher is drawn over), an origin (`origin_x`, `origin_y`: an integer, or `{field, scale, add}` read from the blit's own row) and, when drawn in pages, the field that names the `page`.

The reader refuses what another YAML reader could type differently (`no`, `012`, `1e3`, a date, `1:20`): quote such a scalar. Anchors, tags, block scalars, tabs and duplicate keys are outside the subset.

`palette_ports`: `palette`, `index_port`, `data_port` (in the `space` of `cpu`: `program` or `io`), `order` of `r`, `g`, `b`, `component_bits` (1 to 8), `auto_increment`, `pen_base`, `pen_count` (a power of two up to 1024, 256 by default, at most 256 for a byte index); two on one palette may not set the same pens. `protocol`: `ramdac` (default); `latch` (needs `index_flag_mask`, `index_port` optional); `sequence` (needs `index_port`); the packed two may set `components_bit_reversed`.

A `ramdacs` key is read as `palette_ports`, and `note` says so. `draft` is set when the first line is `gfx_draft`'s DRAFT marker; deleting it confirms the draft. Every entry carries a `status` (`proved`, `declared`, `human`) and a `source`. The reply also carries `sha256` and `systems`. A misspelt key is reported by its full path (`commands.blit.fields.dest_x.parts[1].maks`), and YAML outside the subset names its line. A manifest is judged whole so a half-loaded one never answers a later capture; a refusal keeps the previous load.

<!-- scry-reference:begin gfx_film -->
## `gfx_film`

*Film the frames where a write happened*

```text
gfx_film(trigger="", length=1, value=null, changed=false, pc="", cpu="", frames=600, keep=12, crop=null, film_dir="", first=0, clear=false, seconds=5.0, space="program")
```

The frames in which a write happened; one film per session.

Arm (STOPPED): `trigger` (symbol or `0x` on `cpu`; `space` `io` for a port) is a write of
`length` bytes, from `pc`, carrying `value` (an integer or a `0x` string), or with `changed=True` a value
unlike the one before. Judges `frames` (max 216000), keeps `keep` pictures (max
64) cropped to `crop`, into a new absolute `film_dir`.

Read (no `trigger`; works while running): a contact sheet from `first`. `clear=True` clears.

Reply (arm): `film`, `armed_now`. Reply (read): `film`, `state`, `judged`, `met`, `kept` (once
the film has dumped), `cells` (each `frame`, `pc`, `path`), `image` (once frames are kept),
`next_first` (more kept frames remain). `bad_argument`: film armed
already, none to read.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `trigger` | string | `""` |
| `length` | one of `1`, `2`, `4` | `1` |
| `value` | integer or string or null | `null` |
| `changed` | boolean | `false` |
| `pc` | string | `""` |
| `cpu` | string | `""` |
| `frames` | integer | `600` |
| `keep` | integer | `12` |
| `crop` | array of integer or null | `null` |
| `film_dir` | string | `""` |
| `first` | integer | `0` |
| `clear` | boolean | `false` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |
| `space` | one of `"program"`, `"io"` | `"program"` |

| reply field | type |
|---|---|
| `console_reruns` | integer |
| `cpu` | string |
| `following` | array of string |
| `instruction` | StopInstruction |
| `errorlog` | object |
| `frame` | integer |
| `pc` | string |
| `regs` | object |
| `resent` | integer |
| `stop_seq` | integer |
| `thread_errors` | integer |
| `animation` | object |
| `armed_now` | boolean |
| `baseline_value` | string or object |
| `call` | string |
| `callback_errors` | object |
| `cells` | array |
| `cleared` | boolean |
| `cost` | object |
| `cpus_with_io` | array |
| `dropped_frames` | array or object |
| `dropped_total` | integer |
| `evaluated_by` | string |
| `files_kept` | string |
| `film` | object |
| `frame_as_of` | integer |
| `frame_baseline` | integer or object |
| `height` | integer |
| `image` | object |
| `install_call` | string |
| `install_lines_ahead` | integer |
| `install_resent` | integer |
| `installed` | boolean |
| `judged` | integer |
| `judged_frames` | array or object |
| `kept` | integer |
| `lines_ahead` | integer |
| `listed` | object |
| `listing_path` | string |
| `lost` | object |
| `met` | integer |
| `next_first` | integer |
| `nothing_kept` | string |
| `pc_before` | string |
| `pending` | boolean |
| `pending_picture` | boolean |
| `reader_steps` | integer |
| `refused` | integer |
| `refused_frames` | array |
| `removal` | string |
| `state` | string |
| `superseded` | boolean |
| `tally_id` | string |
| `trigger_maps_to` | string |
| `watches` | array |
| `why` | string |
| `width` | integer |

Example, from a live run:

```json
{
  "trigger": "0x70001e",
  "length": 2,
  "value": 65535,
  "keep": 2,
  "frames": 4
}
```

```json
{
  "summary": "gfx_film on 0x70001e: armed, installed when the console next reads a line",
  "status": "ok",
  "armed_now": true,
  "film": {
    "trigger": "0x70001e",
    "trigger_addr": "0x0070001e",
    "length": 2,
    "value": "0xffff",
    "changed": false,
    "pc": {"available": false, "why": "no `pc` was given"},
    "pc_addr": {"available": false, "why": "no `pc` was given"},
    "cpu": ":maincpu",
    "frames": 4,
    "keep": 2,
    "crop": {"available": false, "why": "no `crop`: the whole screen"},
    "film_dir": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-mcp-<run>/film-1",
    "screen": ":screen",
    "checked": true,
    "space": "program"
  },
  "trigger_maps_to": "radendur_state::blit_w",
  "tally_id": "film",
  "installed": false,
  "pending": true,
  "install_call": "MAME_MCP_LUA_END#17",
  "install_lines_ahead": 0,
  "note": "the film judges from the first whole frame after the install, which runs when the console next reads a line; read it with `gfx_film()`",
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#16",
  "pc_before": "0x000027ac",
  "cause": "gfx_film: one step",
  "stop_seq": 15,
  "pc": "0x000027ac",
  "cpu": ":maincpu",
  "frame": 8,
  "regs": {
    "D0": "0x0103a922",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x00004842",
    "A1": "0x000f27de",
    "A2": "0x00720003",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00000000",
    "SP": "0x00200fc4",
    "PS": "0x2708",
    "PC": "0x000027ac"
  },
  "instruction": {
    "address": "0027AC",
    "bytes": "51C8FFFE",
    "text": "dbra    D0, $27ac",
    "symbol": "boot_init",
    "delta": 464
  },
  "following": ["0027B0: 33FC 0000 0070 0000 move.w  #$0, $700000.l", "0027B8: 33FC 0000 0070 0004 move.w  #$0, $700004.l", "0027C0: 33FC 0000 0070 000C move.w  #$0, $70000c.l", "0027C8: 33FC 000F 0070 000E move.w  #$f, $70000e.l"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14}
}
```
<!-- scry-reference:end gfx_film -->

A breakpoint cannot follow a write that happens many times a frame, which is what a film is for.

**Which frame a hit belongs to.** A write made in vblank still reads the previous counter though it is drawn into this frame, so each hit keeps the counter the tap read as well as the frame. A cell joins `gfx_blits(frame=...)` and a capture's rows by `hit_counters`, not by `frame`, which names the picture.

**`value` and `changed`.** A register a game writes every frame meets a fixed `value` on nearly every frame: a recording, not a filter. `changed=True` is the question a film is usually asked; its `pc` filter judges the write and not what it is compared with. A reset or a state load starts no new baseline. The two are refused together.

**The picture is read late**, at the next frame's end: MAME turns the screen's double buffer over before the frame notifiers run, so a notifier reads the frame just finished only after the next turn. A read at a debugger stop is not a notifier's, and that law is no evidence about it (see [Screen](screen.md), *Which instant a decode shows*). Under frameskip the buffer turns only on a frame that drew, so a skipped met frame is `lost`.

**The check against MAME's rendering.** Where MAME's snapshot is the bare screen, each kept frame is checked against it pixel for pixel and a differing one is refused with no picture. Elsewhere the film says `checked: false` and `mismatch` measures the difference at the arming stop and asserts no cause; its `candidates` is the one cause its rule leaves standing: `orientation` (a mirror matched), `frame_lag` (no mirror, every differing pixel in a pen's colour), `colour_adjustment` (each screen colour drawn as one snapshot colour, no two alike), else `overlay_or_artwork` (also a snapshot of another size, where nothing is compared).

**Lifetime.** `start` does not re-arm a film: it is no stored declaration, since it spends a budget of frames and pictures from the moment it is armed. `clear` keeps its files, so a later film writes into its own directory.

**Files,** in `film_dir` or a `film-N` of the scratch: `frame-K.png` per kept frame; `film.json` (every kept frame with file, sha256, check, `hits_in_frame`, `hit_counters` and its first hits, and every refused one with its reason); `sheet-F.png` per page read; `film-anim.png`, never attached. `cost` is the notifier's own host time inside MAME; the tap's cost per write is not in it.

<!-- scry-reference:begin palette_log -->
## `palette_log`

*Log a palette's port writes*

```text
palette_log(palette_port, pen=null, limit=16, clear=false, arm=false)
```

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

| argument | type | default |
|---|---|---|
| `palette_port` | string | required |
| `pen` | integer or string or null | `null` |
| `limit` | integer (>= 0, <= 256) | `16` |
| `clear` | boolean | `false` |
| `arm` | boolean | `false` |

| reply field | type |
|---|---|
| `across` | array |
| `armed_now` | boolean |
| `call` | string |
| `callback_errors` | object |
| `cleared` | boolean |
| `component_bits` | integer |
| `cpu` | string |
| `cpus_with_io` | array |
| `data_port` | string |
| `desyncs` | integer |
| `frame_as_of` | integer |
| `index_port` | string |
| `index_writes` | integer |
| `install_resent` | integer |
| `installed` | boolean |
| `lines_ahead` | integer |
| `not_proved` | array |
| `order` | string |
| `overflow_rows` | integer |
| `palette` | string |
| `palette_port` | string |
| `palette_ports` | array |
| `partial_writes` | integer |
| `pen_range` | array |
| `pen_state` | object |
| `pending` | boolean |
| `pens_written` | array |
| `protocol` | string |
| `removal` | string |
| `rows` | array |
| `rows_cut` | boolean |
| `rows_kept` | integer |
| `rows_max` | integer |
| `rows_path` | string |
| `sees_reset_and_load` | boolean |
| `setters` | array |
| `setters_path` | string or object |
| `setters_total` | integer |
| `space` | string |
| `state` | string |
| `superseded` | boolean |
| `synced_at_start` | boolean |
| `tally_id` | string |
| `unsynced_writes` | integer |
| `why` | string |
| `writes_total` | integer |

Example, from a live run:

```json
{
  "palette_port": "ramdac",
  "arm": true
}
```

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
<!-- scry-reference:end palette_log -->

A RAMDAC takes an index on one port and the components one after another on the other, so which pen a data write landed on is known only by following the device from the last index write; the log does that inside MAME with MAME's own `ramdac_device` law.

Telling `guest` from `debugger` writes takes the machine's time as well as the debugger's state: a stop from outside is requested before the cpu reaches the instruction it parks at, so the game's last instruction writes at `stop` too. Rows carry the beam `line` and `time_s` on the capture's own clock, so a mid-frame palette write is ordered against another cpu's captured traffic.

The other two protocols put a whole colour in one word, read little-endian from the port up to the end of its bus word; a big-endian bus, or an index port in the data port's bus word, is refused by the install (`install_failed`).
- `latch`: a data word with a bit of `index_flag_mask` set sets the index to its low bits; any other is the indexed pen's colour, written whole. A write to `index_port` merges into the index under its mask, and while the index is unknown only a write covering every index bit makes it known.
- `sequence`: each data write merges into the stored word of the pen at the offset under its mask; any write to `index_port`'s bus word resets the offset to 0. A driver that zeroes it once as its video starts leaves a log armed where `start` parked knowing it (`synced_at_start`); armed anywhere else it waits for a reset write a game may never make again.

In both, a pen has a colour only once every colour bit of its word has been seen written; a write merging into bits the log never saw is a `partial_writes` and the pen keeps no colour until they are.
