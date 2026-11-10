# The Screen tools

These tools answer the question a colour snapshot cannot, WHICH PEN: the wrong pixel is pen N, pen N is used here and nowhere else, these bytes under this format are the tile the screen shows. They show bytes under a format the caller states, never what a driver's `GFXDECODE` believes, which is what is wanted when the driver is the thing being fixed. Tilemaps and MAME's own `gfx_element`s are out of reach on purpose: stock Lua binds neither, and a binding is a fork.

**The picture.** Every picture tool attaches its PNG after the JSON when it is within the inline ceiling and names it in `image` either way; `scale` 0 is the largest integer enlargement that fits, and `dest` is a new path, else the session's scratch. Past the inline ceiling the API resamples, and a resampled picture of pixel art is a plausible wrong one (pens blend, one-pixel lines vanish), so such a picture is written and not attached and `not_inlined` says why. A picture inside a `perform` step is never attached (`nested`): only a reply's own crosses. Enlargement is an integer factor, nearest neighbour, so each pixel is a square of one pen.

An indexed PNG keeps each pixel's index, so the file is the data and a golden can compare pens: the screen is indexed when its palette has at most 256 entries, a tile sheet always. A picture that is a VIEW of the data (dimmed, outlined) is RGB, since an indexed file cannot dim a pen without a second palette entry a 256-pen board does not have; the reply names the data file beside it.

**Which instant a decode shows.** At a stop in the vblank handler `screen_view` matches the framebuffer decoded at the same stop; at a stop in the middle of a frame what it shows is not established. So the stop is chosen by the write to what the read reads (a block, the palette device's pens). A count watch counts writes, not changes, so whether a table moved is read by comparing it at two stops. A change watch stops after its writer, also on a write of the value already there, so the read can equal the one before. A `run_to` the writer's own pc stops before the write.

**The source.** Every block reader answers THE SOURCE in one shape: `kind`, `tag`, `size`, `bytewidth`, `endianness` and `offset`, and for a `ref` the `addr` and `addr_cpu`.

**Discovering a board nobody has described** is a chain: `gfx_sweep` draws a block under candidate layouts, `gfx_locate` checks one against the screen, `gfx_draft` writes a manifest from what the session proved. Nothing in the chain ranks its candidates: a heuristic that looks like proof is worse than an honest list. Every `gfx_locate` answer, sweep and choice is kept as the session's EVIDENCE (gone at `close` and at `start`), and `gfx_draft` derives from that record alone.

**Screen maps.** (A map may carry a `pointer` declaration, for a server that moves a mouse; this server has none, so it keeps the declaration, writes it back on `save` and uses it for nothing.) A screen map names an application's screens and the controls on each, so a caller asks "which screen is this" and gets a name instead of a picture. It is a file, `<application>-screen-map.json`, kept in the application's own store, `.scry/maps/<application>-screen-map.json` (a game both servers run keeps one copy in each port's repository), in the format `scry-screen-map/1`:

```json
{"format": "scry-screen-map/1", "application": "circus", "mode": "verified",
 "screens": [{"name": "attract", "kind": "pixel", "size": [248, 256],
              "match": [{"crop": [0, 0, 248, 8], "signature": "<16 hex>"}],
              "controls": [{"name": "high_score", "rect": [40, 112, 184, 8]}]}]}
```

Everything is in the program's pixels. A screen is known by the signatures of regions that stay still on it, never by the whole screen, whose signature a sprite or a counter changes from one stop to the next. A screen may instead say `"cells": "index"` (`screen_map_write(method="add", cells="index")`): its regions are then signed by the palette index each pixel was drawn with, not by the colour it shows, so one map knows a program on two machines whose palettes resolve one index to different colours. That needs a screen drawn through a palette: on any other it is refused `no_channel`. A screen that says nothing is signed in colour. Capturing the pens costs MAME more than capturing the colours, so they are asked for only when such a screen is mapped.

**Who answers for a map.** `mode` is required. A `verified` map belongs to something still moving (a driver being fixed, a game being written), so every way into a screen judges its signatures and a stale map is caught by the server: `run_to(screen=)` runs to the screen's `anchor` and refuses `stale_map` when the screen there no longer matches, leaving the machine at the anchor. A `consolidated` map belongs to a finished program whose authors keep it current: every screen names its `anchor`, the place after which it is whole, and `run_to(screen=)` takes the screen as shown there without a capture, so its controls can be named at once. `screen_map_find` judges the signatures on either mode, when asked.

**A board that shows the picture larger.** A map is in the program's own pixels. A machine that draws the same program enlarged, a port that doubles it with a border, is described at `load` by an integer `scale` and a `margin` [x, y] in its own pixels on each side, so its screen is the program's size times the scale plus twice the margin. A capture is sampled back into the program's pixels before it is signed, and a control's centre is aimed in the machine's. A capture of a size the view does not fit answers `view_fits: false`.

**Two layers.** `screen_map_write(method="load")` fills the FILE layer, which a `start` keeps. `screen_map_write(method="add")` fills the SESSION layer, which a `start` empties, since its screens were read off another run. `screen_map_find` tries the session first, then the file; `screen_map_write(method="save")` writes the two as one file, the session winning, and that file becomes the file layer.

**In an export**, `screen_map_write(method="load")` and `screen_map_write(method="add")` are steps, so a replay knows the map an identification was made against; `screen_map_find` is a check holding to what it matched (`matched`, `screen`) and where (`pc`, `frame`); `screen_map_write(method="save")` is dropped, since a replay would find its file there.

<!-- scry-reference:begin palette -->
## `palette`

*The live pens of a palette device*

```text
palette(palette="", first=0, count=0, scale=0, dest="", seconds=5.0)
```

The pens of a palette device as the machine holds them now, as a table and a swatch: the
route to the colours of a write-only RAMDAC.

`palette` is the device tag (empty: the only one).
`scale`: the integer the swatch is enlarged by, 0 the largest that fits; `dest`: a new
path it is written to, else the session's scratch; `seconds` bounds the read.

Reply: `palette`, `entries`, `first`, `count`, `truncated`, `colors`, `alpha` (not fully
opaque), `indirect_entries`, `image`. `unknown_ref`, `ambiguous_ref`, `no_channel`: no such
device, several, none. `bad_argument`: past the last pen.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `palette` | string | `""` |
| `first` | integer or string | `0` |
| `count` | integer | `0` |
| `scale` | integer | `0` |
| `dest` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |

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
| `alpha` | array |
| `call` | string |
| `colors` | array |
| `count` | integer |
| `entries` | integer |
| `evaluated_by` | string |
| `first` | integer |
| `highlights` | boolean |
| `image` | object |
| `indirect_entries` | integer |
| `lines_ahead` | integer |
| `palette` | string |
| `palettes` | array |
| `pc_before` | string |
| `reader_steps` | integer |
| `shadows` | boolean |
| `truncated` | boolean |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "palette :palette: pens 0x0..0xff of 256; 1096x1024 PNG x8, inline",
  "status": "ok",
  "palette": ":palette",
  "entries": 256,
  "first": 0,
  "count": 256,
  "truncated": false,
  "shadows": false,
  "highlights": false,
  "indirect_entries": 0,
  "colors": ["#000000", "#ff0000", "#00ff00", "#ffff00", "#0000ff", "#ff00ff", "... 250 more"],
  "image": {
    "path": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-mcp-<run>/gfx/palette-1.png",
    "bytes": 47843,
    "sha256": "1a96fb336cc940f265123a98ddfa794658442656815d4fbaca4182479ba27942",
    "width": 1096,
    "height": 1024,
    "scale": 8,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#6",
  "pc_before": "0x000025e8",
  "cause": "palette: one step",
  "stop_seq": 7,
  "pc": "0x000025ee",
  "cpu": ":maincpu",
  "frame": 0,
  "regs": {
    "D0": "0x00000000",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x00201000",
    "A1": "0x00000000",
    "A2": "0x00000000",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00000000",
    "SP": "0x00200fc4",
    "PS": "0x2708",
    "PC": "0x000025ee"
  },
  "instruction": {
    "address": "0025EE",
    "bytes": "203C0000E927",
    "text": "move.l  #$e927, D0",
    "symbol": "boot_init",
    "delta": 18
  },
  "following": ["0025F4: 4218                clr.b   (A0)+", "0025F6: 51C8 FFFC           dbra    D0, $25f4", "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l", "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l", "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14}
}
```
<!-- scry-reference:end palette -->

`count` 0 runs to the end. The pens are read after the instruction at the stop's pc; nothing is altered. `count` has a ceiling, and `truncated` says whether it cut the read.

<!-- scry-reference:begin screen_view -->
## `screen_view`

*The screen as palette indices*

```text
screen_view(mode="render", pens=null, point=null, crop=null, scale=0, dest="", attach=true, seconds=5.0)
```

The screen as the pens it holds: each pixel's palette index, recovered exactly.

`mode`: `render`, `isolate` (`pens`, 1..64, in `isolate_color` over grey),
`histogram` (pens used, no picture), `pixel` (`point` `[x, y]`). `crop` `[x, y, width,
height]` narrows all but `pixel`. `scale`: the integer the picture is enlarged by, for
every mode but histogram (enlarged four times is `scale=4`), 0 the largest that fits;
`dest`: a new path it is written to, else the session's scratch;
`attach=false` writes it without attaching it to the reply; `seconds` bounds the read.

Reply: `mode`, `screen`, `width`, `height`, `frame_screen`, `palette`, `entries`,
`screen_indexed`, `crop`, `image` (not for mode histogram); `isolate`: `pixels`, `bbox`,
`pens`, `isolate_color`; mode histogram: `histogram`, `pens_used`, `unused`; `pixel`: `x`,
`y`, `pen`, `color`, `set_by`, `point_in_crop`. `no_channel`: no pens to read, or no screen.
`ambiguous_ref`: several screens. `readback_refused`: a pen did not read back. `bad_argument`:
off the screen.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `mode` | one of `"render"`, `"isolate"`, `"histogram"`, `"pixel"` | `"render"` |
| `pens` | array of integer or string or null | `null` |
| `point` | array of integer or null | `null` |
| `crop` | array of integer or null | `null` |
| `scale` | integer | `0` |
| `dest` | string | `""` |
| `attach` | boolean | `true` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |

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
| `bbox` | array |
| `call` | string |
| `color` | string |
| `crop` | array |
| `entries` | integer |
| `evaluated_by` | string |
| `frame_screen` | integer |
| `height` | integer |
| `histogram` | array |
| `image` | object |
| `isolate_color` | string |
| `lines_ahead` | integer |
| `mode` | string |
| `palette` | string or object |
| `pc_before` | string |
| `pen` | integer |
| `pens` | array |
| `pens_not_restored` | array |
| `pens_used` | integer |
| `pixels` | integer |
| `point_in_crop` | array |
| `reader_steps` | integer |
| `rows_cut` | boolean |
| `same_color_write` | object |
| `screen` | string |
| `screen_indexed` | boolean |
| `screen_type` | string |
| `screens` | array |
| `set_by` | object |
| `unused` | array |
| `watches` | array |
| `width` | integer |
| `x` | integer |
| `y` | integer |

Example, from a live run:

```json
{
  "mode": "histogram"
}
```

```json
{
  "summary": "screen_view histogram :screen frame 0: 1 of 256 pens used",
  "status": "ok",
  "mode": "histogram",
  "screen": ":screen",
  "width": 336,
  "height": 252,
  "frame_screen": 0,
  "palette": ":palette",
  "entries": 256,
  "screen_indexed": true,
  "crop": [0, 0, 336, 252],
  "histogram": [
    [0, 84672]
  ],
  "pens_used": 1,
  "unused": ["0x1-0xff"],
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#7",
  "pc_before": "0x000025ee",
  "cause": "screen_view: one step",
  "stop_seq": 8,
  "pc": "0x000025f4",
  "cpu": ":maincpu",
  "frame": 0,
  "regs": {
    "D0": "0x0000e927",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x00201000",
    "A1": "0x00000000",
    "A2": "0x00000000",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00000000",
    "SP": "0x00200fc4",
    "PS": "0x2700",
    "PC": "0x000025f4"
  },
  "instruction": {"address": "0025F4", "bytes": "4218", "text": "clr.b   (A0)+", "symbol": "boot_init", "delta": 24},
  "following": ["0025F6: 51C8 FFFC           dbra    D0, $25f4", "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l", "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l", "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l", "002610: 1039 0020 351C      move.b  $20351c.l, D0"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14}
}
```
<!-- scry-reference:end screen_view -->

Stock `screen:pixels()` resolves an indexed screen to colours, so ONE chunk saves every pen, sets pen `i` to the colour `i`, reads the screen, puts every pen back and reads the screen again. No guest instruction runs inside a chunk, so the game never sees the encoded pens, and they go back even when the read raises (`pcall`).

Four checks make the reply INVALID rather than a picture: an index past the palette's entries; a saved pen that is not the colour the screen showed (contrast or gamma); a pen that did not read back; a screen that changed across the restore. A pen that did not come back counts as a write.

`isolate` greys the other pens in a band with no black or white: dimming would sink a dark pen in a dark screen, and a hue over greys stands out whatever the pen's colour.

`pixel`: `agrees` says whether the colour `set_by`'s write left is the pen's colour now. When it is not, something other than a port write changed the pen since (a driver copying pens itself, a Lua `set_pen_color`, a state load), and the reply names `same_color_write`, the newest kept row that left that colour, instead of guessing.

Up to 256 pens the PNG is indexed and its index is the pen. The pixel mode's picture is a crop round the point, ringed in a `border`.

<!-- scry-reference:begin screen_signature -->
## `screen_signature`

*Signature of the screen*

```text
screen_signature(crop=null, seconds=5.0)
```

One hex string for the screen, or its `crop` `[x, y, width, height]`: "same screen?" is two
strings compared; `series_capture` writes it too. `seconds` bounds the read.

Reply: `signature`, `width`, `height`. `bad_argument`: `crop` off the screen. `no_channel`,
`ambiguous_ref`: no or several screens, or a vector one.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `crop` | array of integer or null | `null` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |

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
| `call` | string |
| `crop` | array |
| `evaluated_by` | string |
| `frame_screen` | integer |
| `height` | integer |
| `kind` | string |
| `lines_ahead` | integer |
| `pc_before` | string |
| `reader_steps` | integer |
| `screen` | string |
| `signature` | string |
| `width` | integer |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "screen_signature 336x252 at [0, 0]: b78c68b342d821d6",
  "status": "ok",
  "signature": "b78c68b342d821d6",
  "kind": "pixel",
  "width": 336,
  "height": 252,
  "crop": [0, 0, 336, 252],
  "screen": ":screen",
  "frame_screen": 0,
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#3",
  "pc_before": "0x000f2040",
  "cause": "screen_signature: one step",
  "stop_seq": 4,
  "pc": "0x000025dc",
  "cpu": ":maincpu",
  "frame": 0,
  "regs": {
    "D0": "0x00000000",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x00000000",
    "A1": "0x00000000",
    "A2": "0x00000000",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00000000",
    "SP": "0x00200ffc",
    "PS": "0x2704",
    "PC": "0x000025dc"
  },
  "instruction": {
    "address": "0025DC",
    "bytes": "48E7FFFC",
    "text": "movem.l D0-D7/A0-A5, -(A7)",
    "symbol": "boot_init",
    "delta": 0
  },
  "following": ["0025E0: 33FC FFFF 0072 0004 move.w  #$ffff, $720004.l", "0025E8: 41F9 0020 1000      lea     $201000.l, A0", "0025EE: 203C 0000 E927      move.l  #$e927, D0", "0025F4: 4218                clr.b   (A0)+", "0025F6: 51C8 FFFC           dbra    D0, $25f4", "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14}
}
```
<!-- scry-reference:end screen_signature -->

The signature is `scry-sig/1`: 16 hex characters of the crop's colours pixel by pixel, so a palette change is a new signature.

<!-- scry-reference:begin screen_wait -->
## `screen_wait`

*Wait for a mapped screen or a black palette*

```text
screen_wait(text="", screen="", palette="", every=0, seconds=30.0)
```

Run the machine until ONE predicate holds, and stop there.

`screen`: the loaded map's screen is on the frame (`screen_map_write`; enters it). `palette`
(`black`: every DAC entry black, which is how a fade ends). Exactly one of the two, or
`bad_argument`; `text` is refused `no_channel`, because this server hands the screen as
pixels and a text mode's characters are DOSBox-X's to read.

`every`: 0 judges every frame; N runs N frames per poll, which is how a screen whose read
costs a console round trip is waited on in reasonable time, and a screen alive for fewer
than N is passed over. `seconds` bounds the polls, counted from the opening judge; the
recovery stop comes after it. Needs a stopped machine. Already true: answered at once, the
machine not moved. The emulator's own frame notifier is not used: measured, it reads the
screen a frame late and sometimes mid-draw, so the judge is the server's at the stop.

Reply: `verdict` `TARGET` (`predicate`, `already`, `waited_s`, `polls`, `sampled_every`;
screen adds `screen`, palette adds `entries`) or `TIMEOUT` (the same, with `note` and the
stop survey of `run_for`), the stop's own fields; a poll the bound itself cut is stopped
there first, so the machine is never left running under a wait that gave up. Refused:
`bad_argument`, `unknown_ref` (no such mapped screen), `no_channel`, and `wait_stopped` when
a stop nobody asked for ends a poll before the bound (its `cause` and the stop's fields ride
beside it).

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `text` | string | `""` |
| `screen` | string | `""` |
| `palette` | one of `""`, `"black"` | `""` |
| `every` | integer | `0` |
| `seconds` | number (> 0, <= 600.0) | `30.0` |

| reply field | type |
|---|---|
| `command_chars` | integer |
| `cpu` | string or object |
| `cycles` | integer or object |
| `following` | array of string |
| `instruction` | StopInstruction |
| `disarmed_watches` | array |
| `emulated_after_s` | number or object |
| `emulated_before_s` | number |
| `errorlog` | object |
| `frame` | integer or object |
| `frame_after` | integer or object |
| `frame_before` | integer or object |
| `limit_chars` | integer |
| `not_rearmed` | array |
| `pc` | string |
| `polls` | integer |
| `reads` | integer |
| `regpoint_hit` | object |
| `regs` | object |
| `stop_seq` | integer |
| `verdict` | string |
| `watch_hit` | object |
| `watches` | array |
| `already` | boolean |
| `entries` | integer |
| `frames` | integer |
| `palette` | string |
| `predicate` | string |
| `sampled_every` | integer |
| `screen` | object |
| `waited_s` | number |

Example, from a live run:

```json
{
  "palette": "black",
  "seconds": 0.2
}
```

```json
{
  "summary": "screen_wait a black palette: already on screen",
  "status": "ok",
  "verdict": "TARGET",
  "predicate": "palette",
  "already": true,
  "polls": 0,
  "sampled_every": 0,
  "frames": 0,
  "waited_s": 0.1,
  "palette": "black",
  "entries": 256
}
```
<!-- scry-reference:end screen_wait -->

<!-- scry-reference:begin gfx_view -->
## `gfx_view`

*Bytes as tiles, under a gfx_layout*

```text
gfx_view(layout, palette="none", tag="", ref="", offset=0, first=0, count=0, columns=16, pen_base=0, scale=0, dest="", attach=true, cpu="", seconds=5.0)
```

Bytes as tiles in a format you state, as MAME's `gfx_layout`.

`layout`: a manifest format's name, or `width`, `height`, `planes` (1..8),
`planeoffset`, `xoffset`, `yoffset`, `charincrement` in bits; values may use
`RGN_FRAC(n,d)`, `+ - *`, hex, `STEPn(a,b)`.

Source: `tag` with `offset` (an integer or a `0x` string), or `ref` (tile 0; `count` required). `count` 0:
the block, at most 1024; `columns` 1..64; `first` starts the tiles
at that index. `palette`: `none` or a tag. `pen_base`: the pen each pixel starts at.
`scale`: the integer the picture is enlarged by, 0 the largest that fits; `dest`: a new path
it is written to, else the scratch; `attach=false` writes it without attaching it; `cpu`:
whose address space, the visible one when empty; `seconds` bounds the read.

Reply: `layout`, `tiles_available`, `palette`, `real_colors`, `image`. `bad_argument`: not a
layout, tiles past the block, too few pens, over 1048576 pixels or 67108864
bytes. `unknown_ref`: missing tag, palette or name.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `layout` | object or string | required |
| `palette` | string | `"none"` |
| `tag` | string | `""` |
| `ref` | string | `""` |
| `offset` | integer or string | `0` |
| `first` | integer | `0` |
| `count` | integer | `0` |
| `columns` | integer (>= 1, <= 64) | `16` |
| `pen_base` | integer or string | `0` |
| `scale` | integer | `0` |
| `dest` | string | `""` |
| `attach` | boolean | `true` |
| `cpu` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |

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
| `addr` | string |
| `addr_cpu` | string |
| `bytewidth` | integer |
| `call` | string |
| `columns` | integer |
| `count` | integer |
| `endianness` | string |
| `entries` | integer |
| `evaluated_by` | string |
| `first` | integer |
| `formats` | array |
| `image` | object |
| `kind` | string |
| `layout` | object |
| `lines_ahead` | integer |
| `offset` | integer |
| `palette` | string |
| `palettes` | array |
| `pc_before` | string |
| `pen_base` | integer |
| `pending` | boolean |
| `reader_steps` | integer |
| `real_colors` | boolean |
| `seen_bytes` | integer |
| `size` | integer |
| `tag` | string |
| `tags` | object |
| `tiles_available` | integer |

Example, from a live run:

```json
{
  "layout": {
    "width": 8,
    "height": 8,
    "planes": 1,
    "planeoffset": [0],
    "xoffset": "{ STEP8(0,1) }",
    "yoffset": "{ STEP8(0,8) }",
    "charincrement": "8*8"
  },
  "palette": "none",
  "tag": "maincpu",
  "count": 16
}
```

```json
{
  "summary": "gfx_view region :maincpu: tiles 0..15 of 131072, 8x8x1, palette none; 1024x64 PNG x8, inline",
  "status": "ok",
  "layout": {
    "name": "",
    "width": 8,
    "height": 8,
    "planes": 1,
    "planeoffset": [0],
    "xoffset": [0, 1, 2, 3, 4, 5, "... 2 more"],
    "yoffset": [0, 8, 16, 24, 32, 40, "... 2 more"],
    "charincrement": 64
  },
  "kind": "region",
  "tag": ":maincpu",
  "size": 1048576,
  "bytewidth": 2,
  "endianness": "big",
  "offset": 0,
  "first": 0,
  "count": 16,
  "tiles_available": 131072,
  "columns": 16,
  "palette": "none",
  "pen_base": 0,
  "real_colors": false,
  "note": "palette `none`: a grey ramp over the pixel values, NOT the machine's colours; the PNG's index is the pixel value either way",
  "image": {
    "path": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-mcp-<run>/gfx/gfx-1.png",
    "bytes": 649,
    "sha256": "f7ace1f0bdaded024a4351bbdd8367042aaac59b0c2364f6a928a3e068512d1e",
    "width": 1024,
    "height": 64,
    "scale": 8,
    "indexed": true,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#8",
  "pc_before": "0x000025f4",
  "cause": "gfx_view: one step",
  "stop_seq": 9,
  "pc": "0x000025f6",
  "cpu": ":maincpu",
  "frame": 0,
  "regs": {
    "D0": "0x0000e927",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x00201001",
    "A1": "0x00000000",
    "A2": "0x00000000",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00000000",
    "SP": "0x00200fc4",
    "PS": "0x2704",
    "PC": "0x000025f6"
  },
  "instruction": {
    "address": "0025F6",
    "bytes": "51C8FFFC",
    "text": "dbra    D0, $25f4",
    "symbol": "boot_init",
    "delta": 26
  },
  "following": ["0025FA: 4EB9 000F 24D0      jsr     $f24d0.l", "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l", "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l", "002610: 1039 0020 351C      move.b  $20351c.l, D0"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14}
}
```
<!-- scry-reference:end gfx_view -->

The layout is MAME's own `gfx_layout` terms, so a driver's transcribes by copy and paste, and formats that bit depth plus "planar" cannot say (byte-interleaved planes, planes a third of a region apart, packed nibbles, a linear framebuffer) all can.

A region is read whole and put in the block's own byte order, as MAME's `xormask` does. A share is read a byte at a time, since stock Lua binds no bulk read for one, so its size bound is smaller. A `ref` is a fraction of nothing, so `RGN_FRAC` is refused there.

Fewer pens than the depth needs is refused, never padded. A list of colours is not a palette it takes: recolour the indexed PNG by replacing its PLTE, since its index is the pixel value.

Plane 0 is the top bit. A driver's layout transcribes as it is (`total` is `first` and `count`). The PNG is indexed, its index the pixel value.

<!-- scry-reference:begin gfx_locate -->
## `gfx_locate`

*Find a screen patch in a block*

```text
gfx_locate(layouts, patch, tag="", ref="", offset=0, first=0, count=0, transparent=null, flips=null, cpu="", seconds=5.0)
```

Search a screen `patch` `[x, y, width, height]` for a block's tiles under `layouts`, a list
of 1..8 (plural even for one), each a `gfx_view` layout or a `gfx_sweep`
id (`s1c3`).

Tiles `first`.. (`count` 1..65536, 0 all) are tried under `flips` (absent: all
four). `transparent` leaves a pixel value out. `cpu`: whose address space, the visible one
when empty; `seconds` bounds the capture read, not the search. Source as `gfx_view` (`tag`,
`ref`, `offset`:
an integer or a `0x` string).

Reply: `candidates`, `matched`, `matches_total`, `matches` (first 32:
`layout`, `window`, `tile`, `flip`, `base`, `shape`), `ambiguous`, `pen_map`, `nearest`
(nothing matched), `evidence`. `bad_argument`: a patch off the screen or without a whole tile,
past a bound; else `gfx_view`'s.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `layouts` | array of object or string | required |
| `patch` | array of integer | required |
| `tag` | string | `""` |
| `ref` | string | `""` |
| `offset` | integer or string | `0` |
| `first` | integer | `0` |
| `count` | integer | `0` |
| `transparent` | integer or string or null | `null` |
| `flips` | array of one of `"none"`, `"x"`, `"y"`, `"xy"` or null | `null` |
| `cpu` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |

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
| `addr` | string |
| `addr_cpu` | string |
| `ambiguous` | boolean |
| `ambiguous_windows` | integer |
| `bytewidth` | integer |
| `call` | string |
| `candidates` | array |
| `endianness` | string |
| `evaluated_by` | string |
| `evidence` | object |
| `flips` | array |
| `frame_screen` | integer |
| `height` | integer |
| `kind` | string |
| `lines_ahead` | integer |
| `matched` | boolean |
| `matches` | array |
| `matches_total` | integer |
| `nearest` | object |
| `offset` | integer |
| `palette` | string |
| `patch` | array |
| `pc_before` | string |
| `pen_map` | object |
| `pending` | boolean |
| `reader_steps` | integer |
| `screen` | string |
| `screen_type` | string |
| `screens` | array |
| `seen_bytes` | integer |
| `size` | integer |
| `tag` | string |
| `tiles_available` | integer |
| `transparent` | integer or object |
| `watches` | array |
| `width` | integer |

Example, from a live run:

```json
{
  "layouts": [
    {
      "width": 8,
      "height": 8,
      "planes": 1,
      "planeoffset": [0],
      "xoffset": "{ STEP8(0,1) }",
      "yoffset": "{ STEP8(0,8) }",
      "charincrement": "8*8"
    }
  ],
  "patch": [0, 0, 8, 8],
  "tag": "maincpu",
  "count": 64
}
```

```json
{
  "summary": "gfx_locate region :maincpu for patch [0, 0, 8, 8]: no match",
  "status": "ok",
  "patch": [0, 0, 8, 8],
  "screen": ":screen",
  "frame_screen": 0,
  "palette": ":palette",
  "kind": "region",
  "tag": ":maincpu",
  "size": 1048576,
  "bytewidth": 2,
  "endianness": "big",
  "offset": 0,
  "transparent": {"available": false, "why": "no `transparent`: every pixel compared"},
  "flips": ["none", "x", "y", "xy"],
  "candidates": [
    {
      "layout": {
        "name": "layout0",
        "width": 8,
        "height": 8,
        "planes": 1,
        "planeoffset": [0],
        "xoffset": [0, 1, 2, 3, 4, 5, "... 2 more"],
        "yoffset": [0, 8, 16, 24, 32, 40, "... 2 more"],
        "charincrement": 64
      },
      "tiles_searched": [0, 64],
      "windows": 0,
      "windows_uniform": 1,
      "windows_mixed_bank": 0,
      "matches": 0,
      "tiles_available": 131072,
      "pen_map_matches": 0
    }
  ],
  "matched": false,
  "matches_total": 0,
  "matches": [],
  "ambiguous": false,
  "ambiguous_windows": 0,
  "pen_map": {"tried": true, "matches": 0},
  "nearest": {"available": false, "why": "no window came close enough to name (the note says why)"},
  "note": "no nearest candidate: every window was of one pen or of two banks; the pen map read none of them as a tile",
  "evidence": {"locate": 1},
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#9",
  "pc_before": "0x000025f6",
  "cause": "gfx_locate: one step",
  "stop_seq": 10,
  "pc": "0x000025f4",
  "cpu": ":maincpu",
  "frame": 0,
  "regs": {
    "D0": "0x0000e926",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x00201001",
    "A1": "0x00000000",
    "A2": "0x00000000",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00000000",
    "SP": "0x00200fc4",
    "PS": "0x2704",
    "PC": "0x000025f4"
  },
  "instruction": {"address": "0025F4", "bytes": "4218", "text": "clr.b   (A0)+", "symbol": "boot_init", "delta": 24},
  "following": ["0025F6: 51C8 FFFC           dbra    D0, $25f4", "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l", "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l", "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l", "002610: 1039 0020 351C      move.b  $20351c.l, D0"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14}
}
```
<!-- scry-reference:end gfx_locate -->

It is the known-answer case that validates the decoder. A window of one pen matches every blank tile and is counted and skipped; one spanning two banks is not one bank's pens and is left to the pen map.

**The pen map.** A board can draw a tile's ink and paper from two banks, or one value in two pens, and then no window is `base + value`. So when that search matched nothing, a table from each pen of the window to the value it stands for is tried: it has to be a function and read two values, since a tile of one value proves nothing. It proves the format and the tile, never the bank, and less (`ambiguous`).

**What a match proves.** With one bit a pixel, few lit pixels and symmetric glyphs match more than the tile drawn there, hence `ambiguous` and `flips`. Under `transparent` a 1-bit tile proves its shape only if the ink's pens are nowhere among the compared ones. A match's `shape` says whether it could have matched by chance (see `gfx_draft`).

`nearest` is the smallest SHARE of disagreeing pixels, since a count across layouts of different sizes would rank the small tile first by construction. The matches one call holds are bounded because a pattern repeated across the patch and the block matches without end and tells nothing apart.

A match proves the format and the tile's place. A pixel is `base + value`, exact or nothing; failing that a pen map is tried. A match is kept as `gfx_draft`'s evidence. A call is bounded in pixel operations and in matches kept.

<!-- scry-reference:begin gfx_sweep -->
## `gfx_sweep`

*A block under candidate layouts*

```text
gfx_sweep(tag="", ref="", offset=0, count=32, planes=null, sizes=null, palette="none", pen_base=0, scale=0, dest="", cpu="", seconds=5.0)
```

A block of unknown format drawn under a fixed family of candidate layouts as one sheet, each
cell labelled (`S1C3`); nothing is ranked.

The family: `planes` x `sizes` ([width, height], sides 8..32) x pixel order x
`packed`, `planar` or `split` (`tag` only); at most 16 candidates. `count`: tiles a
cell shows (1..64). Source: `tag` with `offset` (an integer or a `0x` string), or `ref`.
`palette` as `gfx_view`. `pen_base`: the pen each pixel starts at; `dest`: a new path the
sheet is written to, else the scratch; `cpu`: whose address space, the visible one when
empty; `seconds` bounds the read.

Reply: `sweep`, `count`, `cell_scale`, `candidates` (`id`, `what`, `tiles_available`,
`shown`), `next`, `image`. `bad_argument`: too many candidates, no whole tile, a sheet past
the ceiling. `unknown_ref`: a tag or palette it lacks.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `tag` | string | `""` |
| `ref` | string | `""` |
| `offset` | integer or string | `0` |
| `count` | integer (>= 1, <= 64) | `32` |
| `planes` | array of integer (>= 1, <= 8) or null | `null` |
| `sizes` | array of array of one of `8`, `16`, `24`, `32` or null | `null` |
| `palette` | string | `"none"` |
| `pen_base` | integer or string | `0` |
| `scale` | integer | `0` |
| `dest` | string | `""` |
| `cpu` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |

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
| `addr` | string |
| `addr_cpu` | string |
| `bytewidth` | integer |
| `call` | string |
| `candidates` | integer or array |
| `cell_scale` | integer |
| `count` | integer |
| `endianness` | string |
| `entries` | integer |
| `evaluated_by` | string |
| `image` | object |
| `kind` | string |
| `lines_ahead` | integer |
| `next` | string |
| `offset` | integer |
| `palette` | string |
| `palettes` | array |
| `pc_before` | string |
| `pen_base` | integer |
| `pending` | boolean |
| `reader_steps` | integer |
| `real_colors` | boolean |
| `seen_bytes` | integer |
| `size` | integer |
| `sweep` | integer |
| `tag` | string |

Example, from a live run:

```json
{
  "tag": "maincpu",
  "planes": [1],
  "count": 8
}
```

```json
{
  "summary": "gfx_sweep region :maincpu: sweep 1, 1 candidate s1c1, 1 drawn; 1320x480 PNG x5, inline",
  "status": "ok",
  "kind": "region",
  "tag": ":maincpu",
  "size": 1048576,
  "bytewidth": 2,
  "endianness": "big",
  "offset": 0,
  "sweep": 1,
  "count": 8,
  "palette": "none",
  "pen_base": 0,
  "real_colors": false,
  "cell_scale": 4,
  "candidates": [
    {"id": "s1c1", "what": "1bpp 8x8 rows", "tiles_available": 131072, "shown": 8}
  ],
  "next": "gfx_locate(layouts=[<ids>]) proves one against the screen; gfx_draft(choose={\"candidate\": <id>, \"chosen_by\": <who>}) records a person's pick",
  "note": "palette `none`: a grey ramp over the pixel values, NOT the machine's colours",
  "image": {
    "path": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-mcp-<run>/gfx/sweep-1.png",
    "bytes": 8583,
    "sha256": "f44f27e948aad92357d377aac52407f930c87da6b005aacc123e12cc43d4b040",
    "width": 1320,
    "height": 480,
    "scale": 5,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#10",
  "pc_before": "0x000025f4",
  "cause": "gfx_sweep: one step",
  "stop_seq": 11,
  "pc": "0x000025f6",
  "cpu": ":maincpu",
  "frame": 0,
  "regs": {
    "D0": "0x0000e926",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x00201002",
    "A1": "0x00000000",
    "A2": "0x00000000",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00000000",
    "SP": "0x00200fc4",
    "PS": "0x2704",
    "PC": "0x000025f6"
  },
  "instruction": {
    "address": "0025F6",
    "bytes": "51C8FFFC",
    "text": "dbra    D0, $25f4",
    "symbol": "boot_init",
    "delta": 26
  },
  "following": ["0025FA: 4EB9 000F 24D0      jsr     $f24d0.l", "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l", "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l", "002610: 1039 0020 351C      move.b  $20351c.l, D0"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14}
}
```
<!-- scry-reference:end gfx_sweep -->

Name in `planes` or `sizes` only what the request states. A candidate's id is a layout for `gfx_locate` and `gfx_view`; `gfx_draft(choose=...)` records a person's pick.

<!-- scry-reference:begin gfx_draft -->
## `gfx_draft`

*Draft a gfx.yaml from the evidence*

```text
gfx_draft(dest="", choose=null)
```

Write a `gfx.yaml` draft from what this session proved, and a JSON report beside it with
every figure. Refused with no evidence.

`dest`: an absolute `.yaml` in an existing directory (empty: the scratch); an earlier draft
there is replaced, anything else is refused. `choose` `{"candidate": "s1c3", "chosen_by":
"<who>"}` records a person's pick first.

Reply: `manifest` and `report` (each `path`, `sha256`), `formats` (name to status),
`asset_names`, `command_fields`, `evidence`, `not_proved` (first 8),
`chose` (with `choose`), `confirm`.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `dest` | string | `""` |
| `choose` | object or null | `null` |

| reply field | type |
|---|---|
| `asset_names` | array |
| `chose` | object |
| `command_fields` | object |
| `confirm` | string |
| `draft` | string |
| `evidence` | object |
| `formats` | object |
| `manifest` | object |
| `marker` | string |
| `not_proved` | array |
| `not_proved_more` | integer |
| `report` | object |

Example, from a live run:

```json
{
  "dest": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/jobs-scratch/A/f9.yaml"
}
```

```json
{
  "summary": "gfx_draft /var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/jobs-scratch/A/f9.yaml: 0 formats, 0 assets, 0 commands",
  "status": "ok",
  "manifest": {
    "path": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/jobs-scratch/A/f9.yaml",
    "sha256": "262671d092f843070be95654627c4aecd8573d1c23f73e834769350d5ab51c18"
  },
  "report": {
    "path": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/jobs-scratch/A/f9.report.json",
    "sha256": "a4ccdc97aa30f7e1651a433dae67507ed2862f2313e6c5a89390ed1d71ea7197"
  },
  "formats": {},
  "asset_names": [],
  "command_fields": {},
  "evidence": {"locates": 1, "sweeps": 1, "choices": 0, "correlations": 0},
  "not_proved": [],
  "confirm": "the owner confirms the draft by deleting its first line; `gfx_load` loads it before that and says `draft: true`"
}
```
<!-- scry-reference:end gfx_draft -->

**What is proved.** A match is only as strong as the search is wide, and the caller sets the width: a patch cut to one window matches once whenever it matches, so the windows tried cannot say how strong it was, and the rarest pen can. A layout also overlaps no other block's match on the same frame (a pixel has one origin: a letter drawn from one block is found by chance in another's tiles).

**A person's pick.** `choose` is `human` where nothing of its size is proved, promoted when a match proves the same layout, and named as contradicted when a match proves another.

**Assets and commands.** A format proved only through a pen map proves no bank, so no asset is written for it. A command comes from a capture watch, against the answers whose matches all sit in one window. An answer of screen frame F pairs with the capture's one row of frame F minus a lag; each word of the block is tried as `dest_x`, `dest_y` and `source_tile`, with a sign and an `add`, and a reading holds when it agrees on every paired answer where the role is known, on enough of them, the role taking more than one value. The lag is one law for the group, the one at which both x and y hold; none or several settle nothing. An ambiguous role is not assigned; one that holds only at another lag is named (`elsewhere`), since a word written at another time of the frame is one frame off.

**The draft.** A `dest` that exists without the DRAFT marker is refused, so a confirmed manifest is never overwritten. The draft is read back by the loader, so a discovered command can be tried with `gfx_blits` before anybody confirms it. Every figure is in the report; the draft's `source` strings name its key.

A format is proved by a `gfx_locate` match whose window varies along both axes, with its rarest pen covering the tile's longer side, where no other source matched on that frame. Two layouts of one tile size that both matched are rivals, and both stay ambiguous unless an answer that tried both saw one match a window the other missed. A source is `human` when chosen from a sweep's sheet. An asset is written per source and bank. A command comes from a capture watch whose words agree with the located object's x and y on every paired event, at one lag for the group, a reversed coordinate as `sign: -1`. The report is regenerated byte for byte from the same evidence, and `choose` is recorded once however often it is made, and not when the draft fails. The draft is loaded back before the reply; `gfx_load` takes it and says `draft: true`.

<!-- scry-reference:begin gfx_blits -->
## `gfx_blits`

*Blit boxes over the screen*

```text
gfx_blits(draw_command, frame=null, area=null, detail=false, first=0, scale=0, dest="", seconds=5.0)
```

Who painted this area: every blit of a `frame` from the manifest's `draw_command` capture,
as a box over the screen, one colour per writer pc.

A missing capture is refused, naming the `watch_add`. `frame` defaults to the newest with
blits. A summary by default; `area` `[x, y, width, height]` lists the blits covering it in
drawn order; `detail` lists all, 24 a page from `first`. `scale`: the integer the
picture is enlarged by, 0 the largest that fits; `dest`: a new path it is written to, else
the scratch; `seconds` bounds the read.

Reply: `frame_blit`, `rows_cut`, `blits_in_frame`, `legend`, `by_plane`, `covering`,
`topmost` (with `area`), `listed`, `blits` (with `area` or `detail`), `next_first` (more
blits remain), `not_proved`, `image`. `bad_argument`: no
manifest, capture or rows; a frame without blits or past the rows kept. `unknown_ref`: no
such command.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `draw_command` | string | required |
| `frame` | integer or null | `null` |
| `area` | array of integer or null | `null` |
| `detail` | boolean | `false` |
| `first` | integer | `0` |
| `scale` | integer | `0` |
| `dest` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |

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
| `area` | array |
| `blits` | array |
| `blits_in_frame` | integer |
| `by_plane` | array |
| `call` | string |
| `callback_errors` | object |
| `colors_repeat` | boolean |
| `commands` | array |
| `covering` | integer |
| `declare` | string |
| `draw_command` | string |
| `evaluated_by` | string |
| `frame_blit` | integer |
| `frame_complete` | boolean |
| `frame_screen` | integer |
| `frames_with_blits` | object |
| `height` | integer |
| `image` | object |
| `legend` | array |
| `lines_ahead` | integer |
| `listed` | object |
| `listed_of` | integer |
| `next_first` | integer |
| `not_proved` | array |
| `overflow_rows` | integer |
| `pc_before` | string |
| `reader_steps` | integer |
| `rows_cut` | boolean |
| `rows_kept` | integer |
| `rows_path` | string |
| `screen` | string |
| `tally_id` | string |
| `topmost` | object |
| `watches` | array |
| `width` | integer |

Example, from a live run:

```json
{
  "draw_command": "blit"
}
```

```json
{
  "summary": "gfx_blits blit frame 6: 1 blit by 1 writer; 1008x756 PNG x3, inline",
  "status": "ok",
  "draw_command": "blit",
  "frame_blit": 6,
  "frame_complete": true,
  "rows_cut": false,
  "screen": ":screen",
  "frame_screen": 8,
  "width": 336,
  "height": 252,
  "rows_path": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-mcp-<run>/capture-700000_32_t70001e.rows",
  "rows_kept": 7,
  "overflow_rows": 0,
  "callback_errors": {
    "count": 0,
    "first": {"available": false, "why": "no callback raised"}
  },
  "frames_with_blits": {"first": 4, "last": 8, "count": 3},
  "blits_in_frame": 1,
  "legend": [
    {"pc": "0x00002738", "symbol": "boot_init+0x15c", "color": "#ff4040", "blits": 1}
  ],
  "colors_repeat": false,
  "by_plane": [
    {"plane": "sprites", "page": 0, "blits": 1, "on_screen": 1}
  ],
  "note": "a plane drawn in pages: `by_plane` and each listed blit name the `page`, and which page the screen shows is not in the rows",
  "not_proved": ["dest_x", "scroll_y", "source_dir_y", "source_x", "source_y", "planes.sprites", "... 1 more"],
  "image": {
    "path": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-mcp-<run>/gfx/blits-1.png",
    "bytes": 2312,
    "sha256": "800103185243eee53008b7207f4d210e06054e9ea9bc5d3e1215578315da44ac",
    "width": 1008,
    "height": 756,
    "scale": 3,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#12",
  "pc_before": "0x000027ac",
  "cause": "gfx_blits: one step",
  "stop_seq": 13,
  "pc": "0x000027ac",
  "cpu": ":maincpu",
  "frame": 8,
  "regs": {
    "D0": "0x0103a924",
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
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14},
  "watches": [
    {
      "ref": "0x700000",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 7,
      "callback_errors": {
        "count": 0,
        "first": {"available": false, "why": "no callback raised"}
      },
      "since_last_stop": 0
    }
  ],
  "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "... 12 more"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables"
}
```
<!-- scry-reference:end gfx_blits -->

A manifest that armed a tap on its own would change the run behind the caller's back, so a missing capture is refused with the `watch_add` that declares it. Also refused: a watch whose install never took (waiting would wait for ever), and captures on two cpus for a command whose `block:` names none.

A capture keeps its rows in order and drops every one past its cap, so the last kept frame may have lost some and says `rows_cut`; a frame past the rows kept is refused.

The summary is the default because every blit of a frame with every field comes back cut. Page again with the same `frame`; a finished frame's rows do not change.

**Covering is not painting.** With an `area`, `topmost` is the last of the highest plane over every covering blit. What painted a pixel also needs the source pixels, their transparency and the scale, and the reply says so. Which page of a paged plane the screen shows is not in the rows. `not_proved` names every field and plane the answer leaned on whose status is not `proved`.

The picture is RGB and about the data; `screen_view` is the data. A box is the destination walk wrapped at its plane's size, moved by the plane's origin from the same row and cut to the screen; a paged plane names each blit's `page`.

<!-- scry-reference:begin gfx_blit_source -->
## `gfx_blit_source`

*A blit's source, unscaled*

```text
gfx_blit_source(draw_command, frame=null, index=null, pc="", margin=0, scale=0, dest="", seconds=5.0)
```

The rectangle one blit reads, decoded from the manifest command's `asset` under the live
palette. Always unscaled: no zoom or scale register is applied, so it never shows the blit as
it lands on screen.

The blit: `frame` (as `gfx_blits`) and `index`, or `pc` (the writer; refused when it fired
more than once). `draw_command` is the name of a `gfx_blits` capture. `margin`
(0..16) dims pixels round the rectangle: `image` is that view, `data` the
exact indexed PNG. `dest`: a new path the picture is written to, else the scratch;
`seconds` bounds the read.

Reply: `frame_blit`, `index`, `blit_pc`, `asset`, `format`, `palette`, `rect` (`tile`, `x`,
`y`, `width`, `height`), `margin`, `box`, `wrap`, `not_proved`, `reads_source`, `image`,
`data` (with `margin` above 0). `bad_argument`: `gfx_blits`'s, no `asset`, a tile or rectangle
past its bounds, a pc that fired none or several. `unknown_ref`: an unknown symbol.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `draw_command` | string | required |
| `frame` | integer or null | `null` |
| `index` | integer or null | `null` |
| `pc` | string | `""` |
| `margin` | integer (>= 0, <= 16) | `0` |
| `scale` | integer | `0` |
| `dest` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |

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
| `asset` | string |
| `blit_pc` | string |
| `blit_symbol` | string |
| `blits_in_frame` | integer |
| `box` | array |
| `call` | string |
| `callback_errors` | object |
| `data` | object |
| `destination` | object |
| `draw_command` | string |
| `entries` | integer |
| `evaluated_by` | string |
| `format` | string |
| `frame_blit` | integer |
| `image` | object |
| `index` | integer |
| `indexes` | array |
| `lines_ahead` | integer |
| `margin` | integer |
| `n` | integer |
| `not_proved` | array |
| `palette` | string |
| `palettes` | array |
| `pc_before` | string |
| `pen_base` | integer |
| `reader_steps` | integer |
| `reads_source` | boolean |
| `rect` | object |
| `source_tile` | integer |
| `tag` | string |
| `tile_height` | integer |
| `tile_width` | integer |
| `tiles_available` | integer |
| `watches` | array |
| `wrap` | boolean |

Example, from a live run:

```json
{
  "draw_command": "blit",
  "index": 0
}
```

```json
{
  "summary": "gfx_blit_source blit frame 6 #0 pc 0x00002738: pages tile 0 (22, 11) 2x1; 16x8 PNG x8, inline",
  "status": "ok",
  "draw_command": "blit",
  "frame_blit": 6,
  "index": 0,
  "n": 5,
  "blit_pc": "0x00002738",
  "blit_symbol": "boot_init+0x15c",
  "callback_errors": {
    "count": 0,
    "first": {"available": false, "why": "no callback raised"}
  },
  "asset": "pages",
  "tag": ":gfx1",
  "format": "page_512x512x8",
  "palette": ":palette",
  "pen_base": 0,
  "rect": {"tile": 0, "x": 22, "y": 11, "width": 2, "height": 1, "dir_x": 1, "dir_y": 1},
  "margin": 0,
  "box": [0, 0, 2, 1],
  "wrap": true,
  "destination": {"x": 0, "y": 0, "width": 2, "height": 1, "dir_x": 1, "dir_y": 1},
  "note": "shown unscaled: the rectangle is the destination walk's size from the source origin; a scaled blit reads another extent, which is the project's scale law and is not applied here",
  "not_proved": ["dest_x", "source_dir_y", "source_x", "source_y", "planes.sprites", "planes.background"],
  "reads_source": true,
  "image": {
    "path": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-mcp-<run>/gfx/source-1.png",
    "bytes": 849,
    "sha256": "d147b5bc26274e4d196bf3c27fcb8a7865b5eae821931c399885c1416b71d2b1",
    "width": 16,
    "height": 8,
    "scale": 8,
    "indexed": true,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#13",
  "pc_before": "0x000027ac",
  "cause": "gfx_blit_source: one step",
  "stop_seq": 14,
  "pc": "0x000027ac",
  "cpu": ":maincpu",
  "frame": 8,
  "regs": {
    "D0": "0x0103a923",
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
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14},
  "watches": [
    {
      "ref": "0x700000",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 7,
      "callback_errors": {
        "count": 0,
        "first": {"available": false, "why": "no callback raised"}
      },
      "since_last_stop": 0
    }
  ],
  "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "... 12 more"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables"
}
```
<!-- scry-reference:end gfx_blit_source -->

It is UNSCALED on purpose: a scaled blit reads another extent, and that law is the project's. A blit whose `reads_source` says it read nothing still shows where its registers point. The layout's offsets are windowed onto the rectangle, which is exact for every layout MAME's language states. A `margin` is dimmed because drawn like the rectangle its pixels would read as part of the blit, an offset that does not exist.

No blit zoom or scale register is applied. The origin carries each field's declared `add`; the rectangle wraps inside the tile when the asset says `wrap`, else past the edge is refused. A pc may be a symbol or `0x`; the refusal lists the indexes.
