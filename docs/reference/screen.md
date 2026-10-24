# The Screen tools

These tools answer the question a colour snapshot cannot, WHICH PEN: the wrong pixel is pen N, pen N is used here and nowhere else, these bytes under this format are the tile the screen shows. They show bytes under a format the caller states, never what a driver's `GFXDECODE` believes, which is what is wanted when the driver is the thing being fixed. Tilemaps and MAME's own `gfx_element`s are out of reach on purpose: stock Lua binds neither, and a binding is a fork.

**The picture.** Past the inline ceiling the API resamples, and a resampled picture of pixel art is a plausible wrong one (pens blend, one-pixel lines vanish), so such a picture is written and not attached and `not_inlined` says why. A picture inside a `perform` step is never attached (`nested`): only a reply's own crosses. Enlargement is an integer factor, nearest neighbour, so each pixel is a square of one pen.

An indexed PNG keeps each pixel's index, so the file is the data and a golden can compare pens: the screen is indexed when its palette has at most 256 entries, a tile sheet always. A picture that is a VIEW of the data (dimmed, outlined) is RGB, since an indexed file cannot dim a pen without a second palette entry a 256-pen board does not have; the reply names the data file beside it.

**Which instant a decode shows.** At a stop in the vblank handler `screen_view` matches the framebuffer decoded at the same stop; at a stop in the middle of a frame what it shows is not established. So the stop is chosen by the write to what the read reads (a block, the palette device's pens). A count watch counts writes, not changes, so whether a table moved is read by comparing it at two stops. A change watch stops after its writer, also on a write of the value already there, so the read can equal the one before. A `run_to` the writer's own pc stops before the write.

**The source.** Every block reader answers THE SOURCE in one shape: `kind`, `tag`, `size`, `bytewidth`, `endianness` and `offset`, and for a `ref` the `addr` and `addr_cpu`.

**Discovering a board nobody has described** is a chain: `gfx_sweep` draws a block under candidate layouts, `gfx_locate` checks one against the screen, `gfx_draft` writes a manifest from what the session proved. Nothing in the chain ranks its candidates: a heuristic that looks like proof is worse than an honest list. Every `gfx_locate` answer, sweep and choice is kept as the session's EVIDENCE (gone at `close` and at `start`), and `gfx_draft` derives from that record alone.

**Screen maps.** A screen map names an application's screens and the controls on each, so a caller asks "which screen is this" and gets a name instead of a picture. It is a file, `<application>.scry-map.json`, kept in the application's own repository beside the program, in the format `scry-map/1`:

```json
{"format": "scry-map/1", "application": "circus",
 "screens": [{"name": "attract", "kind": "pixel", "size": [248, 256],
              "match": [{"crop": [0, 0, 248, 8], "signature": "<16 hex>"}],
              "controls": [{"name": "high_score", "rect": [40, 112, 184, 8]}]}]}
```

Everything is in the screen's pixels. A screen is known by the signatures of regions that stay still on it, never by the whole screen, whose signature a sprite or a counter changes from one stop to the next.

**Two layers.** `map_load` fills the FILE layer, which a `start` keeps. `map_add` fills the SESSION layer, which a `start` empties, since its screens were read off another run. `map_find` tries the session first, then the file; `map_save` writes the two as one file, the session winning, and that file becomes the file layer.

**In an export**, `map_load` and `map_add` are steps, so a replay knows the map an identification was made against; `map_find` is a check holding to what it matched (`matched`, `screen`) and where (`pc`, `frame`); `map_save` is dropped, since a replay would find its file there.

<!-- scry-reference:begin palette -->
## `palette`

*The live pens of a palette device*

```text
palette(palette="", first=0, count=0, scale=0, dest="", seconds=5.0)
```

The pens of a palette device as MAME holds them NOW, as a table and a swatch (16
a row, the row's first pen in hex at its left): the route to the colours on a board whose colour
RAM is a write-only RAMDAC. The PNG is attached after the JSON when within the inline ceiling (1568 px a side, 1568 tiles of 28 px); `image` names it either way (`path`, `bytes`, `sha256`, `width`, `height`, `scale`, `indexed`, `border`, `inline`, `not_inlined`).

`palette` (the device's tag, as `gfx_view` takes it; empty: the machine's only palette
device), `first` and `count` (0: to the end, at most 256; `truncated` says
whether that cap cut it), `scale` and `dest`
(`scale` 0, the largest integer enlargement up to 8 that fits; `dest` a new path, else the scratch, gone at `close`), `seconds` (the console's wait).

One step, the pens AFTER the instruction at the stop's pc, nothing altered. Needs the machine STOPPED (else `not_stopped`).

Reply: `palette`, `entries`, `first`, `count`, `truncated`, `colors` (`#rrggbb`), `alpha` (when
a pen is not opaque), `indirect_entries`, `indirect`, `shadows`, `highlights`, `image`, the
console's account, then the stop's survey. `unknown_ref` (a device it lacks), `ambiguous_ref`
(several, none named), `no_channel` (none), `bad_argument` (past the last pen, naming
`entries`).

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
| `dasm` | array or object |
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
  "colors": [
    "#000000",
    "#ff0000",
    "#00ff00",
    "#ffff00",
    "#0000ff",
    "#ff00ff",
    "... 250 more"
  ],
  "image": {
    "path": "$TMPDIR/mame-mcp-vr90lqz3/gfx/palette-1.png",
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
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0025EE: 203C 0000 E927      move.l  #$e927, D0",
    "0025F4: 4218                clr.b   (A0)+",
    "0025F6: 51C8 FFFC           dbra    D0, $25f4",
    "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l",
    "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l",
    "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  }
}
```
<!-- scry-reference:end palette -->

<!-- scry-reference:begin screen_view -->
## `screen_view`

*The screen as palette indices*

```text
screen_view(mode="render", pens=null, point=null, crop=null, scale=0, dest="", attach=true, seconds=5.0)
```

The screen as the PENS it holds: every pixel's palette index recovered exactly by one Lua
chunk that sets pen i to the colour i, reads the screen and puts every pen back.
The PNG is attached after the JSON when within the inline ceiling (1568 px a side, 1568 tiles of 28 px); `image` names it either way (`path`, `bytes`, `sha256`, `width`, `height`, `scale`, `indexed`, `border`, `inline`, `not_inlined`); up to 256 pens the PNG is indexed and its index IS the pen.

`mode`: `render` (the picture; a direct-colour screen shows its colours), `isolate` (to SEE
where the `pens` you name are, 1..64, all in `isolate_color` over the rest in
grey; `pixels`, `bbox`),
`histogram` (to COUNT: which pens are used, pixels each as `[pen, pixels]`, and which are
not, `unused`, as `0xa-0xf` runs; no picture), `pixel`
(`point` `[x, y]`: `pen`, `color`, and `set_by`, the pen's newest `palette_log` write, same
step, with `agrees`, or unavailable with why; the picture is a crop round the point,
`point_in_crop` ringed, in a `border`). `crop` `[x, y, width, height]` narrows all but
`pixel`. `scale`, `dest` (`pixel` too): `scale` 0, the largest integer enlargement up to 8 that fits; `dest` a new path, else the scratch, gone at `close`; `attach` false writes the file, unattached.

One step, the screen AFTER the instruction at the stop's pc, nothing altered. Needs the machine STOPPED (else `not_stopped`).

Reply: `mode`, `screen`, `width`, `height`, `frame_screen`, `palette`, `entries`,
`screen_indexed` (false: direct colour), `crop`, the
mode's fields, `image`, the console's account, the survey. `no_channel`: no pens to read (an
index mode in direct colour, a vector or LCD screen, shadows or highlights, over 2^24 pens);
`no_channel` or `ambiguous_ref`: no screen or several;
`readback_refused`: a pen not back (a write) or a failed check;
`bad_argument`: `point` or `crop` off the screen.

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
| `dasm` | array or object |
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
| `note` | string |
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
  "crop": [
    0,
    0,
    336,
    252
  ],
  "histogram": [
    [
      0,
      84672
    ]
  ],
  "pens_used": 1,
  "unused": [
    "0x1-0xff"
  ],
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0025F4: 4218                clr.b   (A0)+",
    "0025F6: 51C8 FFFC           dbra    D0, $25f4",
    "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l",
    "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l",
    "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l",
    "002610: 1039 0020 351C      move.b  $20351c.l, D0"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  }
}
```
<!-- scry-reference:end screen_view -->

Stock `screen:pixels()` resolves an indexed screen to colours, so ONE chunk saves every pen, sets pen `i` to the colour `i`, reads the screen, puts every pen back and reads the screen again. No guest instruction runs inside a chunk, so the game never sees the encoded pens, and they go back even when the read raises (`pcall`).

Four checks make the reply INVALID rather than a picture: an index past the palette's entries; a saved pen that is not the colour the screen showed (contrast or gamma); a pen that did not read back; a screen that changed across the restore. A pen that did not come back counts as a write.

`isolate` greys the other pens in a band with no black or white: dimming would sink a dark pen in a dark screen, and a hue over greys stands out whatever the pen's colour.

`pixel`: `agrees` says whether the colour `set_by`'s write left is the pen's colour now. When it is not, something other than a port write changed the pen since (a driver copying pens itself, a Lua `set_pen_color`, a state load), and the reply names `same_color_write`, the newest kept row that left that colour, instead of guessing.

<!-- scry-reference:begin screen_signature -->
## `screen_signature`

*Signature of the screen*

```text
screen_signature(crop=null, seconds=5.0)
```

One hex string for what is on screen, or on `crop` of it, so "is it the same screen" is
answered by comparing two strings and no picture crosses the conversation. It is the
signature every Scry tool computes (`scry-sig/1`: the crop's colours, pixel by pixel), so it
equals the one `series_capture` writes for a frame over the same crop, and a palette change
is a new signature.

`crop` `[x, y, width, height]`, default the whole screen.

One step, the whole screen read in one chunk AFTER the instruction at the stop's pc, nothing
altered. Needs the machine STOPPED (else `not_stopped`).

Reply: `signature` (16 hex characters), `kind` (`pixel`), `width` and `height` (the
screen's), `crop` (the rectangle hashed), `screen`, `frame_screen`, the console's account,
the survey. `bad_argument`: `crop` off the screen; `no_channel` or `ambiguous_ref`: no
screen or several, or a vector screen.

Reference: REFERENCE.md, Media files.

| argument | type | default |
|---|---|---|
| `crop` | array of integer or null | `null` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |

| reply field | type |
|---|---|
| `console_reruns` | integer |
| `cpu` | string |
| `dasm` | array or object |
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
  "crop": [
    0,
    0,
    336,
    252
  ],
  "screen": ":screen",
  "frame_screen": 0,
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0025DC: 48E7 FFFC           movem.l D0-D7/A0-A5, -(A7)",
    "0025E0: 33FC FFFF 0072 0004 move.w  #$ffff, $720004.l",
    "0025E8: 41F9 0020 1000      lea     $201000.l, A0",
    "0025EE: 203C 0000 E927      move.l  #$e927, D0",
    "0025F4: 4218                clr.b   (A0)+",
    "0025F6: 51C8 FFFC           dbra    D0, $25f4",
    "... 1 more"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  }
}
```
<!-- scry-reference:end screen_signature -->

<!-- scry-reference:begin gfx_view -->
## `gfx_view`

*Bytes as tiles, under a gfx_layout*

```text
gfx_view(layout, palette="none", tag="", ref="", offset=0, first=0, count=0, columns=16, pen_base=0, scale=0, dest="", attach=true, cpu="", seconds=5.0)
```

Bytes as tiles under a format YOU state in MAME's `gfx_layout` terms, not what a driver
believes. The PNG is attached after the JSON when within the inline ceiling (1568 px a side, 1568 tiles of 28 px); `image` names it either way (`path`, `bytes`, `sha256`, `width`, `height`, `scale`, `indexed`, `border`, `inline`, `not_inlined`); the PNG is indexed, its index the pixel value.

`layout`: a format's NAME in the loaded manifest, or `width`, `height`, `planes`
(1..8), `planeoffset`, `xoffset`, `yoffset`, `charincrement` in BITS, and an
optional `name`; a value is an integer or a string with `RGN_FRAC(n,d)`, `+`, `-`, `*`, hex;
a list is a JSON list or a braced string where `STEPn(a,b)` expands. A driver's layout
transcribes as it is (`total` is `first` and `count`). Plane 0 is the top bit.

Source: `tag` (a region or share, read whole in its own byte order; `RGN_FRAC` is of all of
it) with `offset` (bytes), or `ref` (tile 0 in `cpu`'s program space; `count` required);
`offset` and `pen_base`: an integer or a `0x` string.
`first`, `count` (0: what the block holds, at most 1024), `columns`
(1..64). `palette`: `none` (grey, not real), a device tag or empty for the only
one, its pens `pen_base` .. `pen_base + 2^planes - 1` read live. `scale`,
`dest`: `scale` 0, the largest integer enlargement up to 8 that fits; `dest` a new path, else the scratch, gone at `close`; `attach` false writes the file, unattached.

One step; the state AFTER the stop's instruction; unaltered. Needs the machine STOPPED (else `not_stopped`).

Reply: `layout`, the source, `first`, `count`, `tiles_available`, `columns`, `palette`,
`pen_base`, `real_colors`, `note`, `image`, the console's account, the survey. `bad_argument`: a
layout that is not one, tiles past the block, too few pens (`entries`), past 1048576
pixels or a 67108864-byte block; `unknown_ref`: a tag, palette or name it lacks.

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
| `dasm` | array or object |
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
| `note` | string |
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
    "planeoffset": [
      0
    ],
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
    "planeoffset": [
      0
    ],
    "xoffset": [
      0,
      1,
      2,
      3,
      4,
      5,
      "... 2 more"
    ],
    "yoffset": [
      0,
      8,
      16,
      24,
      32,
      40,
      "... 2 more"
    ],
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
    "path": "$TMPDIR/mame-mcp-vr90lqz3/gfx/gfx-1.png",
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
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0025F6: 51C8 FFFC           dbra    D0, $25f4",
    "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l",
    "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l",
    "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l",
    "002610: 1039 0020 351C      move.b  $20351c.l, D0"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  }
}
```
<!-- scry-reference:end gfx_view -->

The layout is MAME's own `gfx_layout` terms, so a driver's transcribes by copy and paste, and formats that bit depth plus "planar" cannot say (byte-interleaved planes, planes a third of a region apart, packed nibbles, a linear framebuffer) all can.

A region is read whole and put in the block's own byte order, as MAME's `xormask` does. A share is read a byte at a time, since stock Lua binds no bulk read for one, so its size bound is smaller. A `ref` is a fraction of nothing, so `RGN_FRAC` is refused there.

Fewer pens than the depth needs is refused, never padded. A list of colours is not a palette it takes: recolour the indexed PNG by replacing its PLTE, since its index is the pixel value.

<!-- scry-reference:begin gfx_locate -->
## `gfx_locate`

*Find a screen patch in a block*

```text
gfx_locate(layouts, patch, tag="", ref="", offset=0, first=0, count=0, transparent=null, flips=null, cpu="", seconds=5.0)
```

Search a screen `patch` `[x, y, width, height]` for a block's tiles under `layouts`, a
LIST of 1..8 candidates (plural even for one), each `gfx_view`'s `layout`
or a `gfx_sweep` candidate's id (`s1c3`): a match proves the format and the tile's place,
against the screen.

Every tile-sized window is tried against tiles `first`.. (`count`, 1..65536; 0:
all, capped) under `flips` (of `none`, `x`, `y`, `xy`: `["none"]` for a board that never flips a
tile; all four when absent). A pixel is `base + value`, `base` aligned to `2^planes`, one per
window: exact or nothing, proving the bank; one-pen windows are counted, not tried. When nothing
matches so, a PEN MAP is tried (one value per pen, two-bank windows too): its matches carry
`pen_map` and no `base`. `transparent` (a pixel value) leaves those tile pixels out, proving
less; nothing is ranked. At most 16777216 pixel operations
and 65536 matches a call. Source: `tag` with `offset` (an integer or a `0x` string), or `ref` on
`cpu`, as `gfx_view`'s.

One step, altering nothing; kept as `gfx_draft`'s evidence.
Needs the machine STOPPED (else `not_stopped`).

Reply: `patch`, `screen`, `frame_screen`, `palette`, the source, `transparent`, `flips`,
`candidates` (counts per layout), `matched`, `matches_total`, `matches` (first
32: `layout`, `window`, `tile`, `flip`, `base`, `bit`, `byte`, `compared`,
`ambiguous`, `shape`, `pen_map`), `ambiguous`, `ambiguous_windows`, `pen_map` (unavailable, or
`tried` with `matches` or `why`); unmatched, `nearest` (`disagree` of `of`, `pixels` `[x, y,
pen, value]`, `is_a_match: false`, `complete`) or a `note` on why none; `evidence`; the
console's account, survey. Refusals: `gfx_view`'s and `screen_view`'s capture's, `no_channel`
for a screen with no pens, `bad_argument`: a patch off the screen or holding no whole tile, or
past a bound.

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
| `dasm` | array or object |
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
| `note` | string |
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
      "planeoffset": [
        0
      ],
      "xoffset": "{ STEP8(0,1) }",
      "yoffset": "{ STEP8(0,8) }",
      "charincrement": "8*8"
    }
  ],
  "patch": [
    0,
    0,
    8,
    8
  ],
  "tag": "maincpu",
  "count": 64
}
```

```json
{
  "summary": "gfx_locate region :maincpu for patch [0, 0, 8, 8]: no match",
  "status": "ok",
  "patch": [
    0,
    0,
    8,
    8
  ],
  "screen": ":screen",
  "frame_screen": 0,
  "palette": ":palette",
  "kind": "region",
  "tag": ":maincpu",
  "size": 1048576,
  "bytewidth": 2,
  "endianness": "big",
  "offset": 0,
  "transparent": {
    "available": false,
    "why": "no `transparent`: every pixel compared"
  },
  "flips": [
    "none",
    "x",
    "y",
    "xy"
  ],
  "candidates": [
    {
      "layout": {
        "name": "layout0",
        "width": 8,
        "height": 8,
        "planes": 1,
        "planeoffset": [
          0
        ],
        "xoffset": [
          0,
          1,
          2,
          3,
          4,
          5,
          "... 2 more"
        ],
        "yoffset": [
          0,
          8,
          16,
          24,
          32,
          40,
          "... 2 more"
        ],
        "charincrement": 64
      },
      "tiles_searched": [
        0,
        64
      ],
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
  "pen_map": {
    "tried": true,
    "matches": 0
  },
  "nearest": {
    "available": false,
    "why": "no window came close enough to name (the note says why)"
  },
  "note": "no nearest candidate: every window was of one pen or of two banks; the pen map read none of them as a tile",
  "evidence": {
    "locate": 1
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0025F4: 4218                clr.b   (A0)+",
    "0025F6: 51C8 FFFC           dbra    D0, $25f4",
    "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l",
    "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l",
    "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l",
    "002610: 1039 0020 351C      move.b  $20351c.l, D0"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  }
}
```
<!-- scry-reference:end gfx_locate -->

It is the known-answer case that validates the decoder. A window of one pen matches every blank tile and is counted and skipped; one spanning two banks is not one bank's pens and is left to the pen map.

**The pen map.** A board can draw a tile's ink and paper from two banks, or one value in two pens, and then no window is `base + value`. So when that search matched nothing, a table from each pen of the window to the value it stands for is tried: it has to be a function and read two values, since a tile of one value proves nothing. It proves the format and the tile, never the bank, and less (`ambiguous`).

**What a match proves.** With one bit a pixel, few lit pixels and symmetric glyphs match more than the tile drawn there, hence `ambiguous` and `flips`. Under `transparent` a 1-bit tile proves its shape only if the ink's pens are nowhere among the compared ones. A match's `shape` says whether it could have matched by chance (see `gfx_draft`).

`nearest` is the smallest SHARE of disagreeing pixels, since a count across layouts of different sizes would rank the small tile first by construction. The matches one call holds are bounded because a pattern repeated across the patch and the block matches without end and tells nothing apart.

<!-- scry-reference:begin gfx_sweep -->
## `gfx_sweep`

*A block under candidate layouts*

```text
gfx_sweep(tag="", ref="", offset=0, count=32, planes=null, sizes=null, palette="none", pen_base=0, scale=0, dest="", cpu="", seconds=5.0)
```

A block no format is known for, drawn under a FIXED family of candidate layouts as ONE
sheet, each cell labelled with its id (`S1C3`) and what it is; nothing is ranked. The PNG is attached after the JSON when within the inline ceiling (1568 px a side, 1568 tiles of 28 px); `image` names it either way (`path`, `bytes`, `sha256`, `width`, `height`, `scale`, `indexed`, `border`, `inline`, `not_inlined`).

The family: `planes` (depths, default [1, 2, 4]) x `sizes` ([width, height], each side a
whole number of 8-pixel cells up to 32; default [[8, 8]]) x pixel order
(`rows`; for tiles of several 8x8 cells, `cells across` or `cells down`) x, past one
plane, `packed`, `planar` or `split` (planes a block fraction apart, `tag` only). At most
16 candidates, else narrow. `count`: tiles a cell shows (1..64,
default 32). Source: `tag`, a region or share (`offset` bytes into it,
an integer or a `0x` string), or `ref`,
an address in `cpu`'s program space. Bits a pixel or a tile size the request names go in
`planes` or `sizes`; leave out what it does not name.
`palette`: `none` (default, grey), a device tag, or empty for the only one, from
`pen_base` (an integer or a `0x` string). `scale`, `dest`: `scale` 0, the largest integer enlargement up to 8 that fits; `dest` a new path, else the scratch, gone at `close`.

NEXT: a candidate's id is a layout for `gfx_locate` (against the screen) and `gfx_view`;
`gfx_draft(choose=...)` records a person's pick.

One step; unaltered. Needs the machine STOPPED (else `not_stopped`).

Reply: the source, `sweep` (its number), `count`, `palette`, `real_colors`,
`cell_scale`, `candidates` (`id`, `what`,
`tiles_available`, `shown`), `next`, `note`, `image`, the
console's account, the survey. `bad_argument`: past the candidates a sheet holds, a
block with no whole tile, a sheet past the ceiling; `unknown_ref`: a tag or palette it lacks.

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
| `dasm` | array or object |
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
| `note` | string |
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
  "planes": [
    1
  ],
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
    {
      "id": "s1c1",
      "what": "1bpp 8x8 rows",
      "tiles_available": 131072,
      "shown": 8
    }
  ],
  "next": "gfx_locate(layouts=[<ids>]) proves one against the screen; gfx_draft(choose={\"candidate\": <id>, \"chosen_by\": <who>}) records a person's pick",
  "note": "palette `none`: a grey ramp over the pixel values, NOT the machine's colours",
  "image": {
    "path": "$TMPDIR/mame-mcp-vr90lqz3/gfx/sweep-1.png",
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
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0025F6: 51C8 FFFC           dbra    D0, $25f4",
    "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l",
    "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l",
    "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l",
    "002610: 1039 0020 351C      move.b  $20351c.l, D0"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  }
}
```
<!-- scry-reference:end gfx_sweep -->

<!-- scry-reference:begin gfx_draft -->
## `gfx_draft`

*Draft a gfx.yaml from the evidence*

```text
gfx_draft(dest="", choose=null)
```

Write a `gfx.yaml` DRAFT from what THIS session proved, and a JSON report beside it
holding every figure. A format is `proved` on a source by a `gfx_locate` match whose window
varies along both axes, its rarest pen covering the tile's longer side (or, at 3+ planes,
its layout's one match in a search of every tile), where no other source matched on that
frame; two layouts of ONE tile size that both matched there are rivals, and one is proved
only where an answer that tried both saw it match a window the other missed (else both are
ambiguous, none written), while layouts of different sizes are each proved on their own;
`human` when chosen from a sweep's sheet; an asset per source and bank; a command per
capture watch whose words agree with the located object's x and y on every paired event (one
window per answer, one row per frame, at one lag for the group, a coordinate stored reversed
as `sign: -1`). Refused with no evidence.

`dest`: an absolute `.yaml` in a directory that exists, free of the characters every `dest`
refuses (the scratch's when empty); an earlier draft there is replaced, anything else there
(its first line not the DRAFT marker, a link) refused; the report is
`dest` with `.report.json`, regenerated byte for byte from the same evidence. `choose`:
`{"candidate": "s1c3", "chosen_by": "<who>"}` records a person's pick first, once however often
it is made, and not when the draft fails. The draft is loaded
back before the reply; `gfx_load` takes it and says `draft: true`. Needs the machine STOPPED (else `not_stopped`).

Reply: `manifest` and `report` (`path`, `sha256`), `formats` (name to status),
`asset_names`, `command_fields` (each command's proved fields), `evidence` (counts),
`not_proved` (why, first 8), `chose`, `confirm`.

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
  "dest": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f9.yaml"
}
```

```json
{
  "summary": "gfx_draft $TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f9.yaml: 0 formats, 0 assets, 0 commands",
  "status": "ok",
  "manifest": {
    "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f9.yaml",
    "sha256": "262671d092f843070be95654627c4aecd8573d1c23f73e834769350d5ab51c18"
  },
  "report": {
    "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f9.report.json",
    "sha256": "992649f5904f8c11853ce245387bc92ccb8bf4ebec8f37d6fe75433c5aed5f34"
  },
  "formats": {},
  "asset_names": [],
  "command_fields": {},
  "evidence": {
    "locates": 1,
    "sweeps": 1,
    "choices": 0,
    "correlations": 0
  },
  "not_proved": [],
  "confirm": "the owner confirms the draft by deleting its first line; `gfx_load` loads it before that and says `draft: true`"
}
```
<!-- scry-reference:end gfx_draft -->

**What is proved.** A match is only as strong as the search is wide, and the caller sets the width: a patch cut to one window matches once whenever it matches, so the windows tried cannot say how strong it was, and the rarest pen can. A layout also overlaps no other block's match on the same frame (a pixel has one origin: a letter drawn from one block is found by chance in another's tiles).

**A person's pick.** `choose` is `human` where nothing of its size is proved, promoted when a match proves the same layout, and named as contradicted when a match proves another.

**Assets and commands.** A format proved only through a pen map proves no bank, so no asset is written for it. A command comes from a capture watch, against the answers whose matches all sit in one window. An answer of screen frame F pairs with the capture's one row of frame F minus a lag; each word of the block is tried as `dest_x`, `dest_y` and `source_tile`, with a sign and an `add`, and a reading holds when it agrees on every paired answer where the role is known, on enough of them, the role taking more than one value. The lag is one law for the group, the one at which both x and y hold; none or several settle nothing. An ambiguous role is not assigned; one that holds only at another lag is named (`elsewhere`), since a word written at another time of the frame is one frame off.

**The draft.** A `dest` that exists without the DRAFT marker is refused, so a confirmed manifest is never overwritten. The draft is read back by the loader, so a discovered command can be tried with `gfx_blits` before anybody confirms it. Every figure is in the report; the draft's `source` strings name its key.

<!-- scry-reference:begin gfx_blits -->
## `gfx_blits`

*Blit boxes over the screen*

```text
gfx_blits(draw_command, frame=null, area=null, detail=false, first=0, scale=0, dest="", seconds=5.0)
```

WHO PAINTED THIS AREA: every blit of a `frame`, from the capture the loaded manifest's
`draw_command` describes, as a box over the screen, one colour per writer pc. The PNG is attached after the JSON when within the inline ceiling (1568 px a side, 1568 tiles of 28 px); `image` names it either way (`path`, `bytes`, `sha256`, `width`, `height`, `scale`, `indexed`, `border`, `inline`, `not_inlined`); RGB, a
picture ABOUT the data (`screen_view` is the data).

Rows: the capture watch on the command's block triggered by its fire word (none: refused, naming
the `watch_add`); a blit is a row writing the fire value. `frame`: default the
newest with blits BEFORE this stop's (the stop's own is still drawn).
By default a SUMMARY: counts, `legend` by writer, `by_plane`, the picture. `area`
`[x, y, width, height]` LISTS the blits covering it, in the order drawn, and `topmost`, the
last of the highest plane; `detail=True` lists every blit. A
listing is a page of 24 from `first`, `next_first` while more remain.
`scale`, `dest`: `scale` 0, the largest integer enlargement up to 8 that fits; `dest` a new path, else the scratch, gone at `close`.

A box: the destination walk wrapped at its plane's size, moved by the plane's origin from the
same row, cut to the screen; a paged plane names each blit's `page`. Needs the machine STOPPED (else `not_stopped`).

Reply: `draw_command`, `frame_blit`, `frame_complete`, `rows_cut`, `screen`, `frame_screen`,
`rows_path`, `rows_kept`, `overflow_rows`, `frames_with_blits`, `callback_errors`,
`blits_in_frame`, `colors_repeat`, `legend`, `by_plane`, `area`, `covering`, `topmost`,
`listed` (`first`, `count`, `of`), `next_first`, `blits`, `not_proved`, `note`, `image`, the
console's account, the survey. `bad_argument`: no manifest, capture or rows; a frame
with no blit or past the rows kept; a bad `first`;
`unknown_ref`: a command it lacks.

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
| `dasm` | array or object |
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
| `note` | string |
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
  "rows_path": "$TMPDIR/mame-mcp-vr90lqz3/capture-700000_32_t70001e.rows",
  "rows_kept": 7,
  "overflow_rows": 0,
  "callback_errors": {
    "count": 0,
    "first": {
      "available": false,
      "why": "no callback raised"
    }
  },
  "frames_with_blits": {
    "first": 4,
    "last": 8,
    "count": 3
  },
  "blits_in_frame": 1,
  "legend": [
    {
      "pc": "0x00002738",
      "symbol": "BOOT_INIT+0x15c",
      "color": "#ff4040",
      "blits": 1
    }
  ],
  "colors_repeat": false,
  "by_plane": [
    {
      "plane": "sprites",
      "page": 0,
      "blits": 1,
      "on_screen": 1
    }
  ],
  "note": "a plane drawn in pages: `by_plane` and each listed blit name the `page`, and which page the screen shows is not in the rows",
  "not_proved": [
    "dest_x",
    "scroll_y",
    "source_dir_y",
    "source_x",
    "source_y",
    "planes.sprites",
    "... 1 more"
  ],
  "image": {
    "path": "$TMPDIR/mame-mcp-vr90lqz3/gfx/blits-1.png",
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
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0027AC: 51C8 FFFE           dbra    D0, $27ac",
    "0027B0: 33FC 0000 0070 0000 move.w  #$0, $700000.l",
    "0027B8: 33FC 0000 0070 0004 move.w  #$0, $700004.l",
    "0027C0: 33FC 0000 0070 000C move.w  #$0, $70000c.l",
    "0027C8: 33FC 000F 0070 000E move.w  #$f, $70000e.l"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  },
  "watches": [
    {
      "ref": "0x700000",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 7,
      "callback_errors": {
        "count": 0,
        "first": {
          "available": false,
          "why": "no callback raised"
        }
      },
      "since_last_stop": 0
    }
  ],
  "omitted": [
    "addr",
    "by",
    "fmt",
    "frame_as_of",
    "install_resent",
    "installed",
    "... 12 more"
  ],
  "how": "`watch_list` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables"
}
```
<!-- scry-reference:end gfx_blits -->

A manifest that armed a tap on its own would change the run behind the caller's back, so a missing capture is refused with the `watch_add` that declares it. Also refused: a watch whose install never took (waiting would wait for ever), and captures on two cpus for a command whose `block:` names none.

A capture keeps its rows in order and drops every one past its cap, so the last kept frame may have lost some and says `rows_cut`; a frame past the rows kept is refused.

The summary is the default because every blit of a frame with every field comes back cut. Page again with the same `frame`; a finished frame's rows do not change.

**Covering is not painting.** With an `area`, `topmost` is the last of the highest plane over every covering blit. What painted a pixel also needs the source pixels, their transparency and the scale, and the reply says so. Which page of a paged plane the screen shows is not in the rows. `not_proved` names every field and plane the answer leaned on whose status is not `proved`.

<!-- scry-reference:begin gfx_blit_source -->
## `gfx_blit_source`

*A blit's source, unscaled*

```text
gfx_blit_source(draw_command, frame=null, index=null, pc="", margin=0, scale=0, dest="", seconds=5.0)
```

The rectangle ONE blit reads, decoded from the manifest command's `asset` under the live
palette. The PNG is attached after the JSON when within the inline ceiling (1568 px a side, 1568 tiles of 28 px); `image` names it either way (`path`, `bytes`, `sha256`, `width`, `height`, `scale`, `indexed`, `border`, `inline`, `not_inlined`); with no `margin` it is indexed, its index the pixel value.

The blit: `frame` (as `gfx_blits`'s) and `index` (its place, as `gfx_blits` lists it) or
`pc` (the writer, a symbol or `0x`; refused, with the indexes, when it fired more than
once).
The rectangle: the source origin (with each field's declared `add`) in tile `source_tile` of
the asset's format, the destination walk's size, in the tile's own orientation; it wraps
inside the tile when the asset says `wrap`, else past the edge is refused. Always
UNSCALED: no blit's zoom or scale registers are applied (the `note` says so).
`margin` (0..16): pixels shown round it, dimmed, the rectangle ringed:
`image` is a view (RGB), `data` the exact indexed PNG; `box` places the rectangle.
`scale`, `dest`: `scale` 0, the largest integer enlargement up to 8 that fits; `dest` a new path, else the scratch, gone at `close`.

One step dumps the asset's block and reads its pens; nothing altered. Needs the machine STOPPED (else `not_stopped`).

Reply: `draw_command`, `frame_blit`, `index`, `n`, `blit_pc`, `blit_symbol`, `asset`, `tag`,
`format`, `palette`, `pen_base`, `rect` (`tile`, `x`, `y`, `width`, `height`, `dir_x`, `dir_y`),
`margin`, `box`, `wrap`, `destination`, `not_proved`, `reads_source`, `image`, `data`,
`callback_errors`, a `note`, the console's account, the survey.
`bad_argument`: `gfx_blits`'s, no `asset` or source roles, a tile past the block, a
rectangle past the tile or past 1048576 pixels, a pc that fired none or several;
`unknown_ref`: a pc naming no symbol.

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
| `dasm` | array or object |
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
| `note` | string |
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
  "blit_symbol": "BOOT_INIT+0x15c",
  "callback_errors": {
    "count": 0,
    "first": {
      "available": false,
      "why": "no callback raised"
    }
  },
  "asset": "pages",
  "tag": ":gfx1",
  "format": "page_512x512x8",
  "palette": ":palette",
  "pen_base": 0,
  "rect": {
    "tile": 0,
    "x": 22,
    "y": 11,
    "width": 2,
    "height": 1,
    "dir_x": 1,
    "dir_y": 1
  },
  "margin": 0,
  "box": [
    0,
    0,
    2,
    1
  ],
  "wrap": true,
  "destination": {
    "x": 0,
    "y": 0,
    "width": 2,
    "height": 1,
    "dir_x": 1,
    "dir_y": 1
  },
  "note": "shown unscaled: the rectangle is the destination walk's size from the source origin; a scaled blit reads another extent, which is the project's scale law and is not applied here",
  "not_proved": [
    "dest_x",
    "source_dir_y",
    "source_x",
    "source_y",
    "planes.sprites",
    "planes.background"
  ],
  "reads_source": true,
  "image": {
    "path": "$TMPDIR/mame-mcp-vr90lqz3/gfx/source-1.png",
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
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0027AC: 51C8 FFFE           dbra    D0, $27ac",
    "0027B0: 33FC 0000 0070 0000 move.w  #$0, $700000.l",
    "0027B8: 33FC 0000 0070 0004 move.w  #$0, $700004.l",
    "0027C0: 33FC 0000 0070 000C move.w  #$0, $70000c.l",
    "0027C8: 33FC 000F 0070 000E move.w  #$f, $70000e.l"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  },
  "watches": [
    {
      "ref": "0x700000",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 7,
      "callback_errors": {
        "count": 0,
        "first": {
          "available": false,
          "why": "no callback raised"
        }
      },
      "since_last_stop": 0
    }
  ],
  "omitted": [
    "addr",
    "by",
    "fmt",
    "frame_as_of",
    "install_resent",
    "installed",
    "... 12 more"
  ],
  "how": "`watch_list` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables"
}
```
<!-- scry-reference:end gfx_blit_source -->

It is UNSCALED on purpose: a scaled blit reads another extent, and that law is the project's. A blit whose `reads_source` says it read nothing still shows where its registers point. The layout's offsets are windowed onto the rectangle, which is exact for every layout MAME's language states. A `margin` is dimmed because drawn like the rectangle its pixels would read as part of the blit, an offset that does not exist.
