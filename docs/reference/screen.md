# The Screen tools

These tools answer what a colour snapshot cannot: which palette entry each pixel is. MAME calls a palette entry a pen. They show bytes in a format you state, never what a driver's `GFXDECODE` says, which is what you want when the driver is the thing being fixed.

`palette` and `screen_view` read the pens and the screen. `gfx_view` decodes tiles; with an unknown format, `gfx_sweep` draws candidates, `gfx_locate` checks one against the screen and `gfx_draft` writes down what was proved. `gfx_blits` and `gfx_blit_source` read the draws a board makes.

Tilemaps and the graphics MAME itself has decoded are out of reach: MAME's stock Lua exposes neither.

## The picture a reply attaches

Every tool that draws attaches its PNG after the JSON and describes it in `image`: `path`, `bytes`, `sha256`, `width`, `height`, `scale`, `indexed` and `inline`. A picture too large to reach the client unresampled is written but not attached, and `not_inlined` says why. Resampled pixel art is a plausible wrong picture: pens blend and one-pixel lines vanish.

`scale` enlarges by a whole factor, so each pixel stays a square of one pen; 0 picks the largest that fits. `dest` names a new file; left empty, the picture goes to the session's temporary folder, removed at `close`. A picture made inside a `perform` step is never attached (`nested`).

An indexed PNG keeps each pixel's pen, so the file is the data and two files can be compared pen by pen. The screen is indexed when its palette has at most 256 entries, a tile sheet always. A picture that is a view of the data, dimmed or outlined, is RGB; the reply names the data file beside it.

## Which instant a decode shows

At a stop inside the vblank handler, `screen_view` matches the framebuffer decoded at the same stop. At a stop in the middle of a frame, what it shows is not established. So choose the stop by the write to what you are about to read: a block of memory, or the palette's pens.

A `watch_add` in `count` mode counts writes, not changes, so compare a table at two stops to know whether it moved. One in `change` mode stops after the write, also when the value written is the one already there. A `run_to` to the writing instruction's own address stops before the write.

<!-- scry-reference:begin palette -->
## `palette`

Read the colours the palette holds now, as a list and as a picture of colour swatches.

```text
palette(palette="", first=0, count=0, scale=0, dest="", seconds=5.0)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped while its attract mode plays. Entry 838, in the range asked for, is the colour of a pixel of the player's sprite.

Ask:

> Show me the 32 palette entries from 832 on, and save the swatches as palette.png.

Call:

```text
palette(first=832, count=32, dest="./tmp/demos/tour/palette.png")
```

Reply, 2 of 30 fields:

```json
{
  "summary": "palette :palette: pens 0x340..0x35f of 2048, more after; 1128x128 PNG x8, inline",
  "colors": [
    "#8866bb",
    "#ff0000",
    "#cc0000",
    "#660000",
    "#ccff88",
    "#77cc44",
    "... 26 more"
  ]
}
```

The summary's `pens` are palette entries: this palette has 2048, and the reply lists 32 of them, from 832 (`0x340`), as colours. The swatches went to a PNG enlarged 8 times.

<details><summary>The whole reply</summary>

```json
{
  "summary": "palette :palette: pens 0x340..0x35f of 2048, more after; 1128x128 PNG x8, inline",
  "status": "ok",
  "palette": ":palette",
  "entries": 2048,
  "first": 832,
  "count": 32,
  "truncated": false,
  "shadows": false,
  "highlights": false,
  "indirect_entries": 0,
  "colors": ["#8866bb", "#ff0000", "#cc0000", "#660000", "#ccff88", "#77cc44", "... 26 more"],
  "image": {
    "path": "./tmp/demos/tour/palette.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 1128,
    "height": 128,
    "scale": 8,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#10",
  "pc_before": "0x0000fd84",
  "cause": "palette: one step",
  "stop_seq": 12,
  "pc": "0x0000fd86",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0x00",
    "B": "0x72",
    "D": "0x0072",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd86",
    "S": "0x07f4",
    "CC": "0xf4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD86", "bytes": "2604", "text": "BNE    $FD8C", "symbol": "irq", "delta": 6},
  "following": ["FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "... 9 more"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
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

</details>

### Arguments

- `palette` (string, default `""`): The palette device to read, by its MAME tag. Left empty, the machine's only one.
- `first` (integer or string, default `0`): The first entry to read: an integer or a `0x` string. Left out, 0.
- `count` (integer, default `0`): How many entries to read, at most 256. Left at 0, to the end; read a larger palette in pages, with `first`.
- `scale` (integer, default `0`): The whole factor the picture is enlarged by, 1 to 8. Left at 0, the largest that fits.
- `dest` (string, default `""`): A new path for the PNG, absolute or starting with `~`. Left empty, the session's temporary folder, deleted at `close`.
- `seconds` (number (> 0, <= 600.0), default `5.0`): The time limit of the read, in seconds of your clock. Left out, 5.

### What comes back

- `colors`: Each entry read, as `#rrggbb`, in order from `first`.
- `entries`: How many entries the palette has.
- `truncated`: `true` when a read to the end stopped at 256 entries with more left.
- `alpha`: Each entry's alpha, listed only when some entry is not fully opaque.
- `indirect_entries`: How many entries MAME's second, indirect colour table holds for this device.
- `image`: The PNG: its `path`, `bytes`, `sha256`, `width`, `height` and `scale`, whether it is `indexed`, and `inline` or the reason in `not_inlined`.

<details><summary>All 29 reply fields</summary>

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
- `alpha` (array)
- `call` (string)
- `colors` (array)
- `count` (integer)
- `entries` (integer)
- `evaluated_by` (string)
- `first` (integer)
- `highlights` (boolean)
- `image` (object)
- `indirect_entries` (integer)
- `lines_ahead` (integer)
- `palette` (string)
- `palettes` (array)
- `pc_before` (string)
- `reader_steps` (integer)
- `shadows` (boolean)
- `truncated` (boolean)

</details>

### What it refuses

- A `palette` tag the machine does not have; the refusal lists its `palettes` (`unknown_ref`).
- An empty `palette` on a machine with several palette devices (`ambiguous_ref`) or with none (`no_channel`).
- A `first` and `count` that reach past the last entry (`bad_argument`).
- A machine that is running (`not_stopped`).

### Why it works this way

The colours come from MAME's own palette device, the entries the screen is drawn with. On many boards nothing else can be read: a RAMDAC is write-only, and some drivers keep their colours in an array of their own.

The read costs one instruction of the program: MAME's console runs a line only when the machine moves, so the call steps once and reads after it. Nothing is altered. The reply is also a stop, and `pc_before` says where the program stood.

In the picture each row holds 16 entries, with the index of its first entry written at its left in hexadecimal, so no entry has to be counted across.

<details><summary>More on why</summary>

`shadows` and `highlights` say whether the device has those two of MAME's tables on. The fields about MAME's console (`evaluated_by`, `lines_ahead`, `reader_steps`, `resent`, `thread_errors`, `console_reruns`, `call`) are explained on the [Lua](lua.md) page.

</details>

### Related tools

- [`screen_view`](#screen_view)
- [`palette_log`](timeline.md#palette_log)
- [`gfx_view`](#gfx_view)

<details><summary>The contract your client receives</summary>

```text
The pens of a palette device as the machine holds them now, as a table and a swatch: the
route to the colours of a write-only RAMDAC.

`palette` is the device tag (empty: the only one).
`scale`: the integer the swatch is enlarged by, 0 the largest that fits; `dest`: a new
path it is written to, else the session's scratch; `seconds` bounds the read.

Reply: `palette`, `entries`, `first`, `count`, `truncated`, `colors`, `alpha` (not fully
opaque), `indirect_entries`, `image`. `unknown_ref`, `ambiguous_ref`, `no_channel`: no such
device, several, none. `bad_argument`: past the last pen.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end palette -->

<!-- scry-reference:begin screen_view -->
## `screen_view`

Read the screen at a stop: its picture, the pixels that hold chosen palette indices, the indices in use, or one pixel.

```text
screen_view(mode="render", pens=null, point=null, crop=null, scale=0, dest="", attach=true,
    seconds=5.0)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped while its attract mode plays. The point is a pixel of the player's sprite at that stop; any point of the 256x240 screen can be asked.

Ask:

> Which palette index does the pixel at 151, 172 hold, and what colour does it show?

Call:

```text
screen_view(mode="pixel", point=[151, 172], dest="./tmp/demos/tour/pixel.png")
```

Reply, 8 of 36 fields:

```json
{
  "mode": "pixel",
  "x": 151,
  "y": 172,
  "pen": 838,
  "color": "#449933",
  "entries": 2048,
  "crop": [127, 148, 48, 48],
  "point_in_crop": [24, 24]
}
```

The pixel holds `pen` 838, a palette index out of 2048 entries, which shows as `#449933`. The picture written is the 48-pixel square `crop` round the point, which sits at its centre.

<details><summary>The whole reply</summary>

```json
{
  "summary": "screen_view pixel :screen frame 545: (151, 172) is pen 0x346 #449933; no logged write to it: no manifest is loaded: `gfx_load` a gfx.yaml whose `palette_ports` names this palette, then `palette_log(palette_port=..., arm=True)` arms the log  ... (290 characters)",
  "status": "ok",
  "mode": "pixel",
  "screen": ":screen",
  "width": 256,
  "height": 240,
  "frame_screen": 545,
  "palette": ":palette",
  "entries": 2048,
  "screen_indexed": true,
  "x": 151,
  "y": 172,
  "pen": 838,
  "color": "#449933",
  "set_by": {
    "available": false,
    "why": "no manifest is loaded: `gfx_load` a gfx.yaml whose `palette_ports` names this palette, then `palette_log(palette_port=..., arm=True)` arms the log that answers who set a pen"
  },
  "crop": [127, 148, 48, 48],
  "point_in_crop": [24, 24],
  "image": {
    "path": "./tmp/demos/tour/pixel.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 388,
    "height": 388,
    "scale": 8,
    "indexed": false,
    "inline": true,
    "border": 2
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#9",
  "pc_before": "0x0000fd82",
  "cause": "screen_view: one step",
  "stop_seq": 11,
  "pc": "0x0000fd84",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0xbc",
    "B": "0x72",
    "D": "0xbc72",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd84",
    "S": "0x07f4",
    "CC": "0xf8",
    "DP": "0x00"
  },
  "instruction": {"address": "FD84", "bytes": "8403", "text": "ANDA   #$03", "symbol": "irq", "delta": 4},
  "following": ["FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "... 9 more"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
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

</details>

### The four modes

| mode | what it answers |
|---|---|
| `render` | The screen as a PNG. On a screen drawn through a palette, each pixel of the file is its palette index. |
| `isolate` | The picture with the palette indices in `pens` in magenta and every other pixel grey, and how many pixels hold them. |
| `histogram` | No picture: each palette index in use with how many pixels hold it, and the ranges nothing uses. |
| `pixel` | The palette index and the colour under `point`, with a small picture of the pixels round it. |

### Arguments

- `mode` (one of `"render"`, `"isolate"`, `"histogram"`, `"pixel"`, default `"render"`): `render`, `isolate`, `histogram` or `pixel`, as above. Left out, `render`.
- `pens` (array of integer or string, optional): For `isolate`: the palette indices to show, 1 to 64 of them. A pen is the palette index a pixel holds.
- `point` (array of integer, optional): For `pixel`: the pixel to read, `[x, y]` on the screen.
- `crop` (array of integer, optional): The rectangle to read, `[x, y, width, height]`; not for `pixel`. Left out, the whole screen.
- `scale` (integer, default `0`): The whole factor the picture is enlarged by, 1 to 8; not for `histogram`. Left at 0, the largest that fits.
- `dest` (string, default `""`): A new path for the PNG, absolute or starting with `~`. Left empty, the session's temporary folder, deleted at `close`.
- `attach` (boolean, default `true`): `false` writes the picture without attaching it to the reply. Left out, `true`.
- `seconds` (number (> 0, <= 600.0), default `5.0`): The time limit of the read, in seconds of your clock. Left out, 5.

### What comes back

- `image`: The PNG: its `path`, `bytes`, `sha256`, `width`, `height` and `scale`, whether it is `indexed`, and `inline` or the reason in `not_inlined`. Not for `histogram`.
- `screen_indexed`: `true` when the screen is drawn through a palette. The PNG itself is indexed when that palette has at most 256 entries.
- `pen`: For `pixel`: the palette index under the point; `color` is the colour it shows.
- `set_by`: For `pixel`: the newest write `palette_log` recorded for that entry, or the reason there is none.
- `histogram`: For `histogram`: one `[pen, pixels]` pair for each palette index in use. `pens_used` counts them; `unused` lists the rest as ranges.
- `pixels`: For `isolate`: how many pixels hold the indices asked for. `bbox` is the rectangle that holds them all, as `[left, top, right, bottom]`.

<details><summary>All 45 reply fields</summary>

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
- `bbox` (array)
- `call` (string)
- `color` (string)
- `crop` (array)
- `entries` (integer)
- `evaluated_by` (string)
- `frame_screen` (integer)
- `height` (integer)
- `histogram` (array)
- `image` (object)
- `isolate_color` (string)
- `lines_ahead` (integer)
- `mode` (string)
- `palette` (string or object)
- `pc_before` (string)
- `pen` (integer)
- `pens` (array)
- `pens_not_restored` (array)
- `pens_used` (integer)
- `pixels` (integer)
- `point_in_crop` (array)
- `reader_steps` (integer)
- `rows_cut` (boolean)
- `same_color_write` (object)
- `screen` (string)
- `screen_indexed` (boolean)
- `screen_type` (string)
- `screens` (array)
- `set_by` (object)
- `unused` (array)
- `width` (integer)
- `x` (integer)
- `y` (integer)

</details>

### What it refuses

- An argument the mode does not take: `pens` outside `isolate`, `point` outside `pixel`, a picture argument with `histogram` (`bad_argument`).
- A `crop` or a `point` off the screen (`bad_argument`).
- `isolate`, `histogram` or `pixel` on a screen drawn in direct colour, which holds no palette index (`no_channel`).
- A machine with no screen, a vector screen, or a palette with `shadows` or `highlights` on (`no_channel`).
- A machine with several screens (`ambiguous_ref`).
- A palette entry that did not read back as saved, or a screen that changed across the read (`readback_refused`).
- A machine that is running (`not_stopped`).

### Why it works this way

A colour picture cannot say which palette index a pixel holds, and two entries can share a colour. MAME hands the screen back as colours, so one script saves every palette entry, sets entry `i` to the colour `i`, reads the screen and puts every entry back.

No instruction of the program runs inside that script, so the program never sees the changed palette, and the entries go back even when the read fails. The reply is refused, never drawn, when the picture cannot be trusted.

`isolate` draws the other pixels in greys with no black or white. Dimming would lose a dark entry in a dark screen, and one hue over greys stands out whatever the entry's colour.

<details><summary>More on why</summary>

The read costs one instruction of the program, as [`palette`](#palette) explains, and the reply is also a stop.

- Refused: an index past the palette's entries.
- Refused: a saved entry that is not the colour the screen showed, as under a contrast or gamma setting.
- Refused: an entry that did not read back. It counts as a write to the machine, and `pens_not_restored` lists it.
- Refused: a screen that changed across the read.

For `pixel`, `agrees` inside `set_by` says whether the colour that write left is the entry's colour now. When it is not, something other than a port write changed the entry: a driver copying entries itself, a Lua `set_pen_color`, a loaded state.

The reply then names `same_color_write`, the newest recorded write that left that colour; `rows_cut` says whether the log had lost rows.

For `pixel` the picture is a crop of 48 pixels round the point, in colour, with the point ringed and a `border` round the crop. `point_in_crop` is the point inside it.

A refusal names what it found: `screens` lists the screens of a machine with several, `screen_type` the kind of a screen that has no pixels to read. `frame_screen` is the screen's own frame number at the read.

The fields about MAME's console (`evaluated_by`, `lines_ahead`, `reader_steps`, `resent`, `thread_errors`, `console_reruns`, `call`) are explained on the [Lua](lua.md) page.

</details>

### Related tools

- [`palette`](#palette)
- [`screen_signature`](#screen_signature)
- [`palette_log`](timeline.md#palette_log)
- [`snapshot`](captures.md#snapshot)
- [`gfx_view`](#gfx_view)
- [`gfx_locate`](#gfx_locate)

<details><summary>The contract your client receives</summary>

```text
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
```

</details>
<!-- scry-reference:end screen_view -->

<!-- scry-reference:begin screen_signature -->
## `screen_signature`

Get a short hash of what the screen shows, so two screens can be told the same without comparing pictures.

```text
screen_signature(crop=null, seconds=5.0)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped five seconds after power-on, with its attract screen showing.

Ask:

> Give me the signature of the screen as it is now, so I can tell later whether it changed.

Call:

```text
screen_signature()
```

Reply, 4 of 24 fields:

```json
{
  "summary": "screen_signature 256x240 at [0, 0]: 0b0a637e5b000571",
  "signature": "0b0a637e5b000571",
  "kind": "pixel",
  "crop": [0, 0, 256, 240]
}
```

`0b0a637e5b000571` stands for the whole 256x240 screen, hashed by the colour of each pixel (`kind` `pixel`). The same screen gives the same 16 characters at any later stop.

<details><summary>The whole reply</summary>

```json
{
  "summary": "screen_signature 256x240 at [0, 0]: 0b0a637e5b000571",
  "status": "ok",
  "signature": "0b0a637e5b000571",
  "kind": "pixel",
  "width": 256,
  "height": 240,
  "crop": [0, 0, 256, 240],
  "screen": ":screen",
  "frame_screen": 295,
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#2",
  "pc_before": "0x0000a631",
  "cause": "screen_signature: one step",
  "stop_seq": 3,
  "pc": "0x0000a633",
  "cpu": ":maincpu",
  "frame": 295,
  "regs": {
    "A": "0x0a",
    "B": "0x4b",
    "D": "0x0a4b",
    "X": "0xc901",
    "Y": "0xf2e6",
    "U": "0xbef1",
    "PC": "0xa633",
    "S": "0x0800",
    "CC": "0xc4",
    "DP": "0x00"
  },
  "instruction": {"address": "A633", "bytes": "24FC", "text": "BCC    $A631", "symbol": "wait_frame", "delta": 2},
  "following": ["A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "A640: 7E F0 00 JMP    $F000", "... 6 more"],
  "errorlog": "<volatile>"
}
```

</details>

### Arguments

- `crop` (array of integer, optional): The rectangle to hash, `[x, y, width, height]`. Left out, the whole screen.
- `seconds` (number (> 0, <= 600.0), default `5.0`): The time limit of the read, in seconds of your clock. Left out, 5.

### What comes back

- `signature`: 16 hex characters. Two screens, or two crops of one size, show the same when their signatures are equal.
- `crop`: The rectangle that was hashed.

<details><summary>All 24 reply fields</summary>

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
- `call` (string)
- `crop` (array)
- `evaluated_by` (string)
- `frame_screen` (integer)
- `height` (integer)
- `kind` (string)
- `lines_ahead` (integer)
- `pc_before` (string)
- `reader_steps` (integer)
- `screen` (string)
- `signature` (string)
- `width` (integer)

</details>

### What it refuses

- A `crop` that leaves the screen (`bad_argument`).
- A machine with no screen, or a vector screen (`no_channel`).
- A machine with several screens (`ambiguous_ref`).
- A machine that is running (`not_stopped`).

### Why it works this way

The signature answers "is it the same screen" with two strings, never two pictures. A caller that waits for a screen, compares two moments or keeps a reference holds 16 characters, not a PNG.

It is made of the colour each pixel shows, never its palette index, so a palette change is a new signature and two screens that look the same have one. Only a screen map can be told to fingerprint palette indices ([`screen_map_write`](read.md#screen_map_write)).

`series_capture` writes the same signature for each frame it keeps, so a frame of a series and the screen now compare directly.

<details><summary>More on why</summary>

The format is `scry-sig/1`: BLAKE2b with an 8-byte digest, 16 lowercase hex characters. It covers the text `scry-sig/1|pixel|<w>x<h>|`, with the crop's size, and then the crop's pixels row by row as RGB.

The read costs one instruction of the program, as [`palette`](#palette) explains, and the reply is also a stop.

`kind` is `pixel`, `screen` is the screen's MAME tag and `frame_screen` its own frame number at the read. The fields about MAME's console (`evaluated_by`, `lines_ahead`, `reader_steps`, `resent`, `thread_errors`, `console_reruns`, `call`) are explained on the [Lua](lua.md) page.

</details>

### Related tools

- [`screen_wait`](run.md#screen_wait)
- [`screen_map_find`](read.md#screen_map_find)
- [`series_capture`](captures.md#series_capture)
- [`image_compare`](files.md#image_compare)
- [`screen_view`](#screen_view)

<details><summary>The contract your client receives</summary>

```text
One hex string for the screen, or its `crop` `[x, y, width, height]`: "same screen?" is two
strings compared; `series_capture` writes it too. `seconds` bounds the read.

Reply: `signature`, `width`, `height`. `bad_argument`: `crop` off the screen. `no_channel`,
`ambiguous_ref`: no or several screens, or a vector one.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end screen_signature -->

<!-- scry-reference:begin gfx_view -->
## `gfx_view`

Draw bytes of a ROM region or of memory as tiles, in a layout you state in MAME's `gfx_layout` terms.

```text
gfx_view(layout, palette="none", tag="", ref="", offset=0, first=0, count=0, columns=16, pen_base=0,
    scale=0, dest="", attach=true, cpu="", seconds=5.0)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped in attract mode. The example session's manifest, `docs/reference/tour/gridlee-gfx.yaml`, is loaded and names the format `sprite`.

Ask:

> Show me sprite tiles 88 to 95 of Gridlee's graphics ROM in the palette's colours, starting at pen 832.

Call:

```text
gfx_view(layout="sprite", tag="gfx1", palette="palette", first=88, count=8, columns=8, pen_base=832,
    dest="./tmp/demos/tour/tiles.png")
```

Reply, 4 of 35 fields:

```json
{
  "summary": "gfx_view region :gfx1: tiles 88..95 of 256, 8x16x4, palette  ... (92 characters)",
  "status": "ok",
  "tiles_available": 256,
  "real_colors": true
}
```

Tiles 88 to 95 of the 256 the region holds, 8 by 16 pixels at 4 bits a pixel. `real_colors` says they are drawn in the machine's own colours.

<details><summary>The whole reply</summary>

```json
{
  "summary": "gfx_view region :gfx1: tiles 88..95 of 256, 8x16x4, palette :palette; 512x128 PNG x8, inline",
  "status": "ok",
  "layout": {
    "name": "sprite",
    "width": 8,
    "height": 16,
    "planes": 4,
    "planeoffset": [0, 1, 2, 3],
    "xoffset": [0, 4, 8, 12, 16, 20, "... 2 more"],
    "yoffset": [0, 32, 64, 96, 128, 160, "... 10 more"],
    "charincrement": 512
  },
  "kind": "region",
  "tag": ":gfx1",
  "size": 16384,
  "bytewidth": 1,
  "endianness": "little",
  "offset": "0x00000000",
  "first": 88,
  "count": 8,
  "tiles_available": 256,
  "columns": 8,
  "palette": ":palette",
  "pen_base": 832,
  "real_colors": true,
  "image": {
    "path": "./tmp/demos/tour/tiles.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 512,
    "height": 128,
    "scale": 8,
    "indexed": true,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#13",
  "pc_before": "0x0000fd8a",
  "cause": "gfx_view: one step",
  "stop_seq": 15,
  "pc": "0x0000fd8c",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0x00",
    "B": "0x72",
    "D": "0x0072",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd8c",
    "S": "0x07f4",
    "CC": "0xf0",
    "DP": "0x00"
  },
  "instruction": {"address": "FD8C", "bytes": "B603BE", "text": "LDA    $03BE", "symbol": "irq", "delta": 12},
  "following": ["FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "... 8 more"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
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

</details>

### Arguments

- `layout` (object or string, required): The tile format: an object, a format name of the loaded `gfx.yaml` or a `gfx_sweep` candidate's id. An object has `width`, `height`, `planes`, `planeoffset`, `xoffset`, `yoffset` and `charincrement`, in bits.
- `palette` (string, default `"none"`): The colours: `none` for a grey ramp, a palette device's tag, or empty for the machine's only palette. Left out, `none`.
- `tag` (string, default `""`): The memory region or share to read, such as `gfx1`. Give this or `ref`, never both.
- `ref` (string, default `""`): An address or symbol in a cpu's memory where tile 0 starts, instead of `tag`. It needs `count`.
- `offset` (integer or string, default `0`): Bytes into the `tag` block where tile 0 starts: an integer or a `0x` string. Not taken with `ref`.
- `first` (integer, default `0`): The index of the first tile drawn. Left out, 0.
- `count` (integer, default `0`): How many tiles to draw, at most 1024. 0 draws every tile the block holds, up to that many.
- `columns` (integer (>= 1, <= 64), default `16`): Tiles in a row of the picture, 1 to 64. Left out, 16.
- `pen_base` (integer or string, default `0`): The first pen of the palette the tiles are drawn with. It needs a `palette` other than `none`.
- `scale` (integer, default `0`): The whole factor the picture is enlarged by, up to 8. 0 picks the largest that fits.
- `dest` (string, default `""`): A new file the PNG is written to. Left empty, it goes to the session's temporary folder.
- `attach` (boolean, default `true`): `false` writes the picture without attaching it to the reply.
- `cpu` (string, default `""`): The cpu whose memory `ref` is in. Left empty, the one the debugger is showing; not taken with `tag`.
- `seconds` (number (> 0, <= 600.0), default `5.0`): The time limit of the read, in seconds.

### What comes back

- `image`: The PNG. It is indexed, and its index is the pixel value under any palette.
- `tiles_available`: How many whole tiles of this layout the block holds from the offset.
- `real_colors`: `false` under palette `none`: the greys are not the machine's colours.
- `layout`: The layout with every expression worked out to numbers, and its `name`.
- `kind`: Where the bytes came from: `region`, `share` or `space`, a cpu's memory. `tag`, `size`, `bytewidth`, `endianness` and `offset` describe it, and a `ref` adds `addr` and `addr_cpu`.

<details><summary>All 40 reply fields</summary>

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
- `addr` (string)
- `addr_cpu` (string)
- `bytewidth` (integer)
- `call` (string)
- `columns` (integer)
- `count` (integer)
- `endianness` (string)
- `entries` (integer)
- `evaluated_by` (string)
- `first` (integer)
- `formats` (array)
- `image` (object)
- `kind` (string)
- `layout` (object)
- `lines_ahead` (integer)
- `offset` (string)
- `palette` (string)
- `palettes` (array)
- `pc_before` (string)
- `pen_base` (integer)
- `pending` (boolean)
- `reader_steps` (integer)
- `real_colors` (boolean)
- `seen_bytes` (integer)
- `size` (integer)
- `tag` (string)
- `tags` (object)
- `tiles_available` (integer)

</details>

### What it refuses

- A `layout` that is not one, or one that uses `RGN_FRAC` with `ref` (`bad_argument`).
- Both `tag` and `ref`, neither, or `ref` without `count` (`bad_argument`).
- Tiles past the end of the block, or a palette with fewer pens than the depth needs, which is never padded (`bad_argument`).
- More than 1048576 pixels in one call, or a block too large to read (`bad_argument`).
- A tag, a palette or a format name that is not there (`unknown_ref`).

### Why it works this way

The layout is written in MAME's own `gfx_layout` terms, so a driver's layout copies over as it is. Its `total` becomes `first` and `count`, and plane 0 is the top bit. Those terms also state formats a bit depth cannot: byte-interleaved planes, planes a third of a region apart, packed nibbles, a linear framebuffer.

To try other colours, replace the palette inside the PNG: the tool takes a palette device, never a list of colours.

`tag` names a memory region, the ROM data MAME loads, or a share, RAM a driver names. A region is read whole, in the block's own byte order. A share is read a byte at a time, so the largest share it reads is smaller.

<details><summary>More on why</summary>

`RGN_FRAC` is a fraction of a block's length, and a range of a cpu's memory has no length of its own, so `ref` refuses it.

</details>

### Related tools

- [`gfx_locate`](#gfx_locate)
- [`gfx_sweep`](#gfx_sweep)
- [`gfx_load`](timeline.md#gfx_load)
- [`palette`](#palette)
- [`screen_view`](#screen_view)
- [`read_block`](read.md#read_block)

<details><summary>The contract your client receives</summary>

```text
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
```

</details>
<!-- scry-reference:end gfx_view -->

<!-- scry-reference:begin gfx_locate -->
## `gfx_locate`

Find which tile of a block is drawn in a patch of the screen, and so prove the tile format against the picture.

```text
gfx_locate(layouts, patch, tag="", ref="", offset=0, first=0, count=0, transparent=null, flips=null,
    cpu="", seconds=5.0)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped in attract mode with the player's sprite on screen. A `gfx_sweep` of the region `gfx1` has given the id `s1c1`.

Ask:

> Which tile of the graphics ROM is the sprite at (148, 164) on screen, 8 by 16 pixels, with value 0 transparent?

Call:

```text
gfx_locate(layouts=["s1c1"], patch=[148, 164, 8, 16], tag="gfx1", transparent=0)
```

Reply, 5 of 40 fields:

```json
{
  "summary": "gfx_locate region :gfx1 for patch [148, 164, 8, 16]: 1 match ... (101 characters)",
  "matched": true,
  "matches_total": 1,
  "ambiguous": false,
  "evidence": {"locate": 1}
}
```

One tile of the region equals the window on screen, and nothing else matched it (`ambiguous`). Which tile, with its flip and its palette base, is in `matches`, in the whole reply below.

<details><summary>The whole reply</summary>

```json
{
  "summary": "gfx_locate region :gfx1 for patch [148, 164, 8, 16]: 1 match, first s1c1 tile 91 flip none base 0x340",
  "status": "ok",
  "patch": [148, 164, 8, 16],
  "screen": ":screen",
  "frame_screen": 545,
  "palette": ":palette",
  "kind": "region",
  "tag": ":gfx1",
  "size": 16384,
  "bytewidth": 1,
  "endianness": "little",
  "offset": "0x00000000",
  "transparent": 0,
  "flips": ["none", "x", "y", "xy"],
  "candidates": [
    {
      "layout": {
        "name": "s1c1",
        "width": 8,
        "height": 16,
        "planes": 4,
        "planeoffset": [0, 1, 2, 3],
        "xoffset": [0, 4, 8, 12, 16, 20, "... 2 more"],
        "yoffset": [0, 32, 64, 96, 128, 160, "... 10 more"],
        "charincrement": 512
      },
      "tiles_searched": [0, 256],
      "windows": 1,
      "windows_uniform": 0,
      "windows_mixed_bank": 0,
      "matches": 1,
      "tiles_available": 256
    }
  ],
  "matched": true,
  "matches_total": 1,
  "matches": [
    {
      "layout": "s1c1",
      "window": [148, 164],
      "tile": 91,
      "flip": "none",
      "base": 832,
      "bit": 46592,
      "byte": 5824,
      "compared": 78,
      "shape": [16, 8, 1],
      "ambiguous": false
    }
  ],
  "ambiguous": false,
  "ambiguous_windows": 0,
  "pen_map": {"available": false, "why": "the single-bank search matched, so no pen map was tried"},
  "evidence": {"locate": 1},
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#12",
  "pc_before": "0x0000fd88",
  "cause": "gfx_locate: one step",
  "stop_seq": 14,
  "pc": "0x0000fd8a",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0x00",
    "B": "0x72",
    "D": "0x0072",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd8a",
    "S": "0x07f4",
    "CC": "0xf8",
    "DP": "0x00"
  },
  "instruction": {"address": "FD8A", "bytes": "0CB4", "text": "INC    <$B4", "symbol": "irq", "delta": 10},
  "following": ["FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "... 8 more"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
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

</details>

### Arguments

- `layouts` (array of object or string, required): A list of 1 to 8 formats to try, a list even for one. Each is a `gfx_view` layout or a `gfx_sweep` candidate's id such as `s1c3`.
- `patch` (array of integer, required): The rectangle of the screen to search, `[x, y, width, height]`. It must hold a whole tile.
- `tag` (string, default `""`): The memory region or share whose tiles are searched. Give this or `ref`.
- `ref` (string, default `""`): An address or symbol where tile 0 starts, instead of `tag`. It needs `count`.
- `offset` (integer or string, default `0`): Bytes into the `tag` block where tile 0 starts: an integer or a `0x` string.
- `first` (integer, default `0`): The index of the first tile tried. Left out, 0.
- `count` (integer, default `0`): How many tiles are tried, up to 65536. 0 tries every tile the block holds.
- `transparent` (integer or string, optional): A pixel value left out of the comparison, as for a sprite over a background. Left out, every pixel is compared.
- `flips` (array of one of `"none"`, `"x"`, `"y"`, `"xy"`, optional): The flips tried, from `none`, `x`, `y` and `xy`. Left out, all four.
- `cpu` (string, default `""`): The cpu whose memory `ref` is in. Left empty, the one the debugger is showing.
- `seconds` (number (> 0, <= 600.0), default `5.0`): The time limit of reading the screen and the block, in seconds. The search itself is not timed.

### What comes back

- `matched`: `true` when a tile equals a window of the patch pixel for pixel. `matches_total` counts the matches.
- `matches`: The first 32, each with `layout`, `window`, `tile`, `flip`, `base`, `bit`, `byte`, `compared`, `shape` and its own `ambiguous`.
- `ambiguous`: `true` when more than one tile or flip matched the same window. `ambiguous_windows` counts such windows.
- `pen_map`: Whether the second search ran (`tried`) and its `matches`, or `why` it did not.
- `nearest`: With no match, the closest miss: `layout`, `window`, `tile`, `flip`, `disagree` pixels out of `of`, the first `pixels` that differ, `is_a_match` and `complete`.
- `candidates`: One row per layout: `layout`, `tiles_searched`, `tiles_available`, `windows`, `windows_uniform`, `windows_mixed_bank`, `matches` and `pen_map_matches`.

<details><summary>All 47 reply fields</summary>

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
- `addr` (string)
- `addr_cpu` (string)
- `ambiguous` (boolean)
- `ambiguous_windows` (integer)
- `bytewidth` (integer)
- `call` (string)
- `candidates` (array)
- `endianness` (string)
- `evaluated_by` (string)
- `evidence` (object)
- `flips` (array)
- `frame_screen` (integer)
- `height` (integer)
- `kind` (string)
- `lines_ahead` (integer)
- `matched` (boolean)
- `matches` (array)
- `matches_total` (integer)
- `nearest` (object)
- `offset` (string)
- `palette` (string)
- `patch` (array)
- `pc_before` (string)
- `pen_map` (object)
- `pending` (boolean)
- `reader_steps` (integer)
- `screen` (string)
- `screen_type` (string)
- `screens` (array)
- `seen_bytes` (integer)
- `size` (integer)
- `tag` (string)
- `tiles_available` (integer)
- `transparent` (integer or object)
- `width` (integer)

</details>

### What it refuses

- A `patch` that leaves the screen or holds no whole tile of any layout (`bad_argument`).
- A search larger than one call does, or a pattern repeated so often that its matches tell nothing apart (`bad_argument`).
- A screen drawn in direct colour, which holds no pens to search for (`no_channel`).
- Whatever `gfx_view` refuses of a layout or of `tag`, `ref`, `offset` and `cpu`.

### Why it works this way

`gfx_view` draws bytes in a format you state, and nothing there says the format is right. A match here does: a tile whose pixels are exactly the pens on screen proves the format, where the tile sits in the block and its palette bank together. Each pixel must equal `base` plus the tile's value, exactly.

A `window` is a tile-sized rectangle of the patch, named by its top-left corner, and every one is tried against every tile. A window of one pen matches every blank tile, so it is counted and skipped. With one bit a pixel, sparse or symmetric glyphs match more than the tile drawn there, hence `ambiguous` and `flips`.

Nothing is ranked. Each answer is kept for `gfx_draft`, and `evidence` gives its number in the session's record. `shape` is the window's distinct rows, distinct columns and rarest pen's pixels, by which `gfx_draft` rules out a chance match.

<details><summary>More on why</summary>

A board can draw a tile's ink and paper from two palette banks, or show one value in two pens, and then no window is `base` plus value. So when the first search matches nothing, a second tries a table from each pen of the window to the value it stands for.

That table must give each pen one value and read at least two, since a tile of one value proves nothing. Its match proves the format and the tile, never the palette bank: it carries `pen_map` and no `base`.

With `transparent`, a match needs two different values among the pixels compared. A one-bit tile has one, so it matches only through the pen table, and proves its shape only when the ink's pens appear nowhere among the pixels left out.

`nearest` goes by the smallest share of disagreeing pixels, never their count, which would favour the smallest tile. Each of its `pixels` is `[x, y, screen pen, decoded value]`.

</details>

### Related tools

- [`gfx_view`](#gfx_view)
- [`gfx_sweep`](#gfx_sweep)
- [`gfx_draft`](#gfx_draft)
- [`screen_view`](#screen_view)

<details><summary>The contract your client receives</summary>

```text
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
```

</details>
<!-- scry-reference:end gfx_locate -->

<!-- scry-reference:begin gfx_sweep -->
## `gfx_sweep`

Draw a block of unknown format under a set of candidate layouts on one labelled sheet, to pick the one that looks like graphics.

```text
gfx_sweep(tag="", ref="", offset=0, count=32, planes=null, sizes=null, palette="none", pen_base=0,
    scale=0, dest="", cpu="", seconds=5.0)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped in attract mode. `gfx1` is the region that holds its sprites.

Ask:

> I don't know the format of Gridlee's sprite ROM: draw its first 16 tiles as 4-bit 8 by 16 candidates on one sheet.

Call:

```text
gfx_sweep(tag="gfx1", planes=[4], sizes=[[8, 16]], count=16, dest="./tmp/demos/tour/sweep.png")
```

Reply, 3 of 36 fields:

```json
{
  "summary": "gfx_sweep region :gfx1: sweep 1, 3 candidates s1c1..s1c3, 3  ... (90 characters)",
  "candidates": [
    {"id": "s1c1", "what": "4bpp 8x16 packed, rows", "tiles_available": 256, "shown": 16},
    {"id": "s1c2", "what": "4bpp 8x16 planar, rows", "tiles_available": 256, "shown": 16},
    {"id": "s1c3", "what": "4bpp 8x16 split, rows", "tiles_available": 256, "shown": 16}
  ],
  "real_colors": false
}
```

Three arrangements of 4 bits a pixel were drawn, each with an id the next call can take, such as `s1c1`. `real_colors` is false: the greys are not the game's colours.

<details><summary>The whole reply</summary>

```json
{
  "summary": "gfx_sweep region :gfx1: sweep 1, 3 candidates s1c1..s1c3, 3 drawn; 1568x384 PNG x2, inline",
  "status": "ok",
  "kind": "region",
  "tag": ":gfx1",
  "size": 16384,
  "bytewidth": 1,
  "endianness": "little",
  "offset": "0x00000000",
  "sweep": 1,
  "count": 16,
  "palette": "none",
  "pen_base": 0,
  "real_colors": false,
  "cell_scale": 4,
  "candidates": [
    {"id": "s1c1", "what": "4bpp 8x16 packed, rows", "tiles_available": 256, "shown": 16},
    {"id": "s1c2", "what": "4bpp 8x16 planar, rows", "tiles_available": 256, "shown": 16},
    {"id": "s1c3", "what": "4bpp 8x16 split, rows", "tiles_available": 256, "shown": 16}
  ],
  "next": "gfx_locate(layouts=[<ids>]) proves one against the screen; gfx_draft(choose={\"candidate\": <id>, \"chosen_by\": <who>}) records a person's pick",
  "note": "palette `none`: a grey ramp over the pixel values, NOT the machine's colours",
  "image": {
    "path": "./tmp/demos/tour/sweep.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 1568,
    "height": 384,
    "scale": 2,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#11",
  "pc_before": "0x0000fd86",
  "cause": "gfx_sweep: one step",
  "stop_seq": 13,
  "pc": "0x0000fd88",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0x00",
    "B": "0x72",
    "D": "0x0072",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd88",
    "S": "0x07f4",
    "CC": "0xf4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD88", "bytes": "0CB3", "text": "INC    <$B3", "symbol": "irq", "delta": 8},
  "following": ["FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "... 8 more"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
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

</details>

### Arguments

- `tag` (string, default `""`): The memory region or share to draw. Give this or `ref`.
- `ref` (string, default `""`): An address or symbol in a cpu's memory to draw from, instead of `tag`.
- `offset` (integer or string, default `0`): Bytes into the `tag` block where the tiles start: an integer or a `0x` string.
- `count` (integer (>= 1, <= 64), default `32`): How many tiles each cell of the sheet shows, 1 to 64. Left out, 32.
- `planes` (array of integer (>= 1, <= 8), optional): The bit depths to try, each 1 to 8. Left out, 1, 2 and 4.
- `sizes` (array of array of one of `8`, `16`, `24`, `32`, optional): The tile sizes to try, each `[width, height]` with sides of 8, 16, 24 or 32. Left out, 8 by 8.
- `palette` (string, default `"none"`): The colours: `none` for a grey ramp, a palette device's tag, or empty for the machine's only palette. Left out, `none`.
- `pen_base` (integer or string, default `0`): The first pen the tiles are drawn with, under a palette other than `none`.
- `scale` (integer, default `0`): The whole factor the sheet is enlarged by, up to 8. 0 picks the largest that fits.
- `dest` (string, default `""`): A new file the sheet is written to. Left empty, it goes to the session's temporary folder.
- `cpu` (string, default `""`): The cpu whose memory `ref` is in. Left empty, the one the debugger is showing.
- `seconds` (number (> 0, <= 600.0), default `5.0`): The time limit of the read, in seconds.

### What comes back

- `candidates`: One row per layout tried: its `id` such as `s1c3`, `what` it is in words, its `tiles_available` and how many are `shown`.
- `sweep`: The number of this sheet in the session, the first half of each candidate's id.
- `image`: The sheet, each cell labelled with its id and its layout.
- `cell_scale`: The factor the tiles inside each cell are enlarged by.
- `next`: The two calls that take an id from this sheet, written out.
- `real_colors`: `false` under palette `none`: the greys are not the machine's colours.

<details><summary>All 38 reply fields</summary>

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
- `addr` (string)
- `addr_cpu` (string)
- `bytewidth` (integer)
- `call` (string)
- `candidates` (integer or array)
- `cell_scale` (integer)
- `count` (integer)
- `endianness` (string)
- `entries` (integer)
- `evaluated_by` (string)
- `image` (object)
- `kind` (string)
- `lines_ahead` (integer)
- `next` (string)
- `offset` (string)
- `palette` (string)
- `palettes` (array)
- `pc_before` (string)
- `pen_base` (integer)
- `pending` (boolean)
- `reader_steps` (integer)
- `real_colors` (boolean)
- `seen_bytes` (integer)
- `size` (integer)
- `sweep` (integer)
- `tag` (string)

</details>

### What it refuses

- More than 16 candidates: narrow `planes` or `sizes` (`bad_argument`).
- A block that holds no whole tile of any candidate, or a sheet too large to attach (`bad_argument`).
- Both `tag` and `ref`, or neither (`bad_argument`).
- A tag or a palette the machine does not have (`unknown_ref`).

### Why it works this way

A board nobody has described has no format to state, and a format must not be guessed. So the block is drawn under every arrangement MAME's layouts are made of, side by side, and you pick the cell that looks like graphics.

Nothing ranks the cells: a ranking that looks like proof is worse than an honest list. A candidate's id is a layout for `gfx_view` and for `gfx_locate`, which checks it against the screen. `gfx_draft(choose=...)` records your pick.

The set of candidates is fixed and never tuned to a board. Give `planes` or `sizes` only when you know them.

<details><summary>More on why</summary>

Each candidate is a depth, a tile size, a pixel order and, past one plane, a plane arrangement, in the words `what` uses. Candidates with the same offsets are drawn once.

| in `what` | meaning |
|---|---|
| `rows` | pixels row by row |
| `cells across` | a tile of several 8x8 cells, across and then down |
| `cells down` | the cells down and then across |
| `packed` | a pixel's bits together, plane 0 the top bit |
| `planar` | the planes' bytes of each 8-pixel group in turn |
| `split` | each plane a fraction of the block apart: `tag` only |

</details>

### Related tools

- [`gfx_locate`](#gfx_locate)
- [`gfx_draft`](#gfx_draft)
- [`gfx_view`](#gfx_view)
- [`machine_map`](machine.md#machine_map)

<details><summary>The contract your client receives</summary>

```text
A block of unknown format drawn under a fixed family of candidate layouts as one sheet, each
cell labelled (`S1C3`); nothing is ranked.

The family: `planes` x `sizes` ([width, height], sides 8..32) x pixel order x
`packed`, `planar` or `split` (`tag` only); at most 16 candidates. `count`: tiles a
cell shows (1..64). Source: a memory region's or share's `tag` with
`offset` (an integer or a `0x` string), or `ref`.
`palette` as `gfx_view`. `pen_base`: the pen each pixel starts at; `dest`: a new path the
sheet is written to, else the scratch; `cpu`: whose address space, the visible one when
empty; `seconds` bounds the read.

Reply: `sweep`, `count`, `cell_scale`, `candidates` (`id`, `what`, `tiles_available`,
`shown`), `next`, `image`. `bad_argument`: too many candidates, no whole tile, a sheet past
the ceiling. `unknown_ref`: a tag or palette it lacks.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end gfx_sweep -->

<!-- scry-reference:begin gfx_draft -->
## `gfx_draft`

Write a draft `gfx.yaml` from what this session's `gfx_locate` answers and your picks proved, with a report of every figure beside it.

```text
gfx_draft(dest="", choose=null)
```

### Try it

On Gridlee, a free ROM from mamedev.org, after the `gfx_sweep` and `gfx_locate` calls shown on this page. The pick of `s1c1` is recorded as the example session's.

Ask:

> Write down what we worked out about Gridlee's sprite format as a draft manifest, and record that the tour picked candidate s1c1.

Call:

```text
gfx_draft(dest="./tmp/demos/tour/gridlee-gfx-draft.yaml",
    choose={"candidate": "s1c1", "chosen_by": "the tour"})
```

Reply, 5 of 11 fields:

```json
{
  "summary": "gfx_draft ./tmp/demos/tour/gridlee-gfx-draft.yaml: 1 format  ... (105 characters)",
  "formats": {"tiles_8x16x4": "human"},
  "evidence": {"locates": 1, "sweeps": 1, "choices": 1, "correlations": 0},
  "not_proved": [
    ":gfx1: s1c1 matched only windows that prove no layout (faile ... (70 characters)",
    ":gfx1: no asset for tiles_8x16x4, chosen under no palette"
  ],
  "chose": {"candidate": "s1c1", "chosen_by": "the tour"}
}
```

The one format written is the recorded pick, marked `human`: `not_proved` says the match found here proves no layout. No asset is written, since the pick was made under no palette.

<details><summary>The whole reply</summary>

```json
{
  "summary": "gfx_draft ./tmp/demos/tour/gridlee-gfx-draft.yaml: 1 format (1 human), 0 assets, 0 commands; 2 not proved",
  "status": "ok",
  "manifest": {
    "path": "./tmp/demos/tour/gridlee-gfx-draft.yaml",
    "sha256": "227b32e68e59f87c84a0ed70236c92d935c8c42bb20b8f66a6a3269c8aca106d"
  },
  "report": {
    "path": "./tmp/demos/tour/gridlee-gfx-draft-report.json",
    "sha256": "65b69eb2078b4578cfc071c2d3f6fc75014b6d825e9a28910ebfe958ca5d2cf0"
  },
  "formats": {"tiles_8x16x4": "human"},
  "asset_names": [],
  "command_fields": {},
  "evidence": {"locates": 1, "sweeps": 1, "choices": 1, "correlations": 0},
  "not_proved": [":gfx1: s1c1 matched only windows that prove no layout (failed: rarest)", ":gfx1: no asset for tiles_8x16x4, chosen under no palette"],
  "confirm": "the owner confirms the draft by deleting its first line; `gfx_load` loads it before that and says `draft: true`",
  "chose": {"candidate": "s1c1", "chosen_by": "the tour"}
}
```

</details>

### Arguments

- `dest` (string, default `""`): An absolute `.yaml` path in an existing folder, where only an earlier draft is replaced. Left empty, the session's temporary folder.
- `choose` (object, optional): Records a person's pick from a `gfx_sweep` sheet before drafting: `{"candidate": "s1c3", "chosen_by": "<who>"}`.

### What comes back

- `manifest`: The draft: its `path` and `sha256`. `report` gives the same two for the JSON report.
- `formats`: Each format written, by name, with its status: `proved` or `human`.
- `not_proved`: The first 8 things the session could not settle, in words. `not_proved_more` counts the rest.
- `evidence`: What the draft was worked out from: how many `locates`, `sweeps`, `choices` and `correlations`.
- `chose`: With `choose`, the pick recorded: `candidate` and `chosen_by`.
- `confirm`: How the draft becomes a manifest: delete its first line.

<details><summary>All 12 reply fields</summary>

- `asset_names` (array)
- `chose` (object)
- `command_fields` (object)
- `confirm` (string)
- `draft` (string)
- `evidence` (object)
- `formats` (object)
- `manifest` (object)
- `marker` (string)
- `not_proved` (array)
- `not_proved_more` (integer)
- `report` (object)

</details>

### What it refuses

- A session with no `gfx_locate` answer and no pick (`needs_call`).
- A `dest` that exists and is not a draft, so a confirmed manifest is never overwritten (`bad_argument`).
- A `dest` that is not a `.yaml` file, or a `choose` of another shape (`bad_argument`).
- A `dest` holding a space, comma, semicolon, quote, bracket or control character, although no console line carries that file: one rule serves every path (`bad_argument`).
- A `choose` that names no candidate of this session's sheets (`unknown_ref`).

### Why it works this way

The draft holds only what the session's record establishes: every `gfx_locate` answer, every `gfx_sweep` sheet and every pick, kept until `close` or the next `start`. Each entry is written with its status and what proved it. What the record cannot settle is listed in `not_proved`.

A format is `proved` by a match whose window varies along both axes and whose rarest pen covers the tile's longer side. No other block may match those pixels on the same frame, since a pixel has one origin. A dot or a line is found by chance among hundreds of tiles.

The draft's first line marks it as a draft, and deleting that line confirms it. `gfx_load` takes it before that and says `draft: true`, so a draw command the draft found can be tried with `gfx_blits` first.

<details><summary>More on why</summary>

A match is only as strong as the search is wide, and you set the width. A patch cut to one window matches once whenever it matches, so the number of windows tried says nothing; the rarest pen does. At three planes or more, a layout's only match in a search of every tile also proves it.

Two layouts of one tile size that both matched are rivals. One is proved only when an answer that tried both saw it match a window the other missed; otherwise neither is written. Layouts of different sizes are not rivals.

A pick from a `gfx_sweep` sheet is written as `human` where nothing of its tile size is proved. A match that proves the same layout turns it into `proved`, and a match that proves another is reported as contradicting it.

An asset is written for each block and palette bank a format was drawn with; `asset_names` lists them. A format matched only through `gfx_locate`'s pen table proves no bank, so it gets no asset.

A draw command comes from a capture watch (`watch_add`), paired with the answers whose matches all sit in one window. An answer of screen frame F pairs with the capture's row of frame F minus a lag. Each word of the block is tried as `dest_x`, `dest_y` and `source_tile`, with a sign and an `add`.

A capture whose callbacks raised is short of writes, so the draft proves no draw command from it and says why in `not_proved`.

A reading holds when it agrees on every paired answer, on enough of them, with a value that changes. The lag is the one at which both x and y hold; none or several settle nothing. A role that holds only at another lag is left out and named (`elsewhere`); `command_fields` lists what was written.

Every figure lives in the report, which the same record regenerates byte for byte, and the draft's `source` lines name the report's key. A `choose` is recorded once however often it is made, and not at all when the draft fails.

</details>

### Related tools

- [`gfx_locate`](#gfx_locate)
- [`gfx_sweep`](#gfx_sweep)
- [`gfx_load`](timeline.md#gfx_load)
- [`gfx_blits`](#gfx_blits)
- [`watch_add`](breakpoints.md#watch_add)

<details><summary>The contract your client receives</summary>

```text
Write a `gfx.yaml` draft from what this session proved, and a JSON report beside it with
every figure. Refused with no evidence.

`dest`: an absolute `.yaml` in an existing directory (empty: the scratch); an earlier draft
there is replaced, anything else is refused. `choose` `{"candidate": "s1c3", "chosen_by":
"<who>"}` records a person's pick first.

Reply: `manifest` and `report` (each `path`, `sha256`), `formats` (name to status),
`asset_names`, `command_fields`, `evidence`, `not_proved` (first 8),
`chose` (with `choose`), `confirm`.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end gfx_draft -->

<!-- scry-reference:begin gfx_blits -->
## `gfx_blits`

Show every draw (blit) a board made in one frame as a box over the screen, coloured by the code that issued it.

```text
gfx_blits(draw_command, frame=null, area=null, detail=false, first=0, scale=0, dest="", seconds=5.0)
```

### Try it

On Gridlee, a free ROM from mamedev.org, with the example session's manifest loaded. A capture watch on the player's sprite entry (`0xc`, 4 bytes, trigger `0x10`) has recorded two frames.

Ask:

> Which code drew over the rectangle at (148, 164), 8 by 16 pixels, in frame 545?

Call:

```text
gfx_blits(draw_command="player", frame=545, area=[148, 164, 8, 16],
    dest="./tmp/demos/tour/blits.png")
```

Reply, 3 of 45 fields:

```json
{
  "summary": "gfx_blits player frame 545: 1 of 1 blit covers [148, 164, 8, ... (115 characters)",
  "legend": [
    {"pc": "0x0000a81f", "symbol": "write_sprites+0x29", "color": "#ff4040", "blits": 1}
  ],
  "topmost": {
    "index": 0,
    "n": 3,
    "pc": "0x0000a81f",
    "plane": {"available": false, "why": "the command declares no plane"}
  }
}
```

One blit covers the area, issued from `write_sprites+0x29`, whose boxes are drawn in `#ff4040`. `topmost` names it as the likeliest painter; its `n` is the capture's row, and it has no plane because the command names none.

<details><summary>The whole reply</summary>

```json
{
  "summary": "gfx_blits player frame 545: 1 of 1 blit covers [148, 164, 8, 16], topmost #0 pc 0x0000a81f; 1024x960 PNG x4, inline",
  "status": "ok",
  "draw_command": "player",
  "frame_blit": 545,
  "frame_complete": false,
  "rows_cut": false,
  "screen": ":screen",
  "frame_screen": 545,
  "width": 256,
  "height": 240,
  "rows_path": "<volatile>",
  "rows_kept": 3,
  "overflow_rows": 0,
  "callback_errors": {
    "count": 0,
    "first": {"available": false, "why": "no callback raised"}
  },
  "frames_with_blits": {"first": 543, "last": 545, "count": 3},
  "blits_in_frame": 1,
  "legend": [
    {"pc": "0x0000a81f", "symbol": "write_sprites+0x29", "color": "#ff4040", "blits": 1}
  ],
  "colors_repeat": false,
  "by_plane": [
    {
      "plane": {"available": false, "why": "the command declares no plane"},
      "page": {"available": false, "why": "the plane is not drawn in pages"},
      "blits": 1,
      "on_screen": 1
    }
  ],
  "area": [148, 164, 8, 16],
  "covering": 1,
  "topmost": {
    "index": 0,
    "n": 3,
    "pc": "0x0000a81f",
    "plane": {"available": false, "why": "the command declares no plane"}
  },
  "note": "a box COVERS the area; what painted a pixel also needs the source pixels, their transparency and the scale, which the rows do not carry: `topmost` is the last covering blit of the highest plane, the likeliest painter, not a proven one",
  "listed": {"first": 0, "count": 1, "of": 1},
  "blits": [
    {
      "index": 0,
      "n": 3,
      "pc": "0x0000a81f",
      "box": {"x": 148, "y": 164, "width": 8, "height": 16, "dir_x": 1, "dir_y": 1},
      "plane": {"available": false, "why": "the command declares no plane"},
      "screen": [
        [148, 164, 8, 16]
      ],
      "on_screen": true,
      "clipped": false,
      "fields": {"source_tile": 91, "dest_y": 164, "dest_x": 148, "width": 8, "height": 16},
      "flags": {},
      "symbol": "write_sprites+0x29"
    }
  ],
  "not_proved": [],
  "image": {
    "path": "./tmp/demos/tour/blits.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 1024,
    "height": 960,
    "scale": 4,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#14",
  "pc_before": "0x0000fd8c",
  "cause": "gfx_blits: one step",
  "stop_seq": 16,
  "pc": "0x0000fd8f",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0x00",
    "B": "0x72",
    "D": "0x0072",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd8f",
    "S": "0x07f4",
    "CC": "0xf4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD8F", "bytes": "2628", "text": "BNE    $FDB9", "symbol": "irq", "delta": 15},
  "following": ["FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "... 9 more"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
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

</details>

### Arguments

- `draw_command` (string, required): The name of a draw command in the loaded `gfx.yaml`, whose register block a capture watch is recording.
- `frame` (integer, optional): The frame whose blits are shown. Left out, the newest frame before this stop that has any.
- `area` (array of integer, optional): A rectangle of the screen, `[x, y, width, height]`. The reply then lists the blits covering it, in the order drawn.
- `detail` (boolean, default `false`): `true` lists every blit of the frame, 24 a page.
- `first` (integer, default `0`): The first blit of the list to show, for the next page. It needs `area` or `detail`.
- `scale` (integer, default `0`): The whole factor the picture is enlarged by, up to 8. 0 picks the largest that fits.
- `dest` (string, default `""`): A new file the PNG is written to. Left empty, it goes to the session's temporary folder.
- `seconds` (number (> 0, <= 600.0), default `5.0`): The time limit of the read, in seconds.

### What comes back

- `frame_blit`: The frame shown. `frame_complete` is `false` when this stop is still inside it or rows were lost.
- `legend`: One row per writer: its `pc`, its `symbol`, the `color` of its boxes and how many `blits` it made.
- `by_plane`: The blits by `plane` and `page`: how many `blits`, and how many are `on_screen`.
- `topmost`: With `area`, the last covering blit of the highest plane: its `index`, `n` (the capture's row), `pc` and `plane`.
- `blits`: With `area` or `detail`, a page of blits: `index`, `n`, `pc`, `box`, `plane`, `page`, the `screen` rectangles, `on_screen`, `clipped`, `fields` and `flags`.
- `not_proved`: The fields and planes of the command this answer relied on whose status in the manifest is not `proved`.

<details><summary>All 46 reply fields</summary>

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
- `area` (array)
- `blits` (array)
- `blits_in_frame` (integer)
- `by_plane` (array)
- `call` (string)
- `callback_errors` (object)
- `colors_repeat` (boolean)
- `commands` (array)
- `covering` (integer)
- `declare` (string)
- `draw_command` (string)
- `evaluated_by` (string)
- `frame_blit` (integer)
- `frame_complete` (boolean)
- `frame_screen` (integer)
- `frames_with_blits` (object)
- `height` (integer)
- `image` (object)
- `legend` (array)
- `lines_ahead` (integer)
- `listed` (object)
- `listed_of` (integer)
- `next_first` (integer)
- `not_proved` (array)
- `overflow_rows` (integer)
- `pc_before` (string)
- `reader_steps` (integer)
- `rows_cut` (boolean)
- `rows_kept` (integer)
- `rows_path` (string)
- `screen` (string)
- `tally_id` (string)
- `topmost` (object)
- `width` (integer)

</details>

### What it refuses

- No manifest loaded (`needs_call`), or a command it does not have (`unknown_ref`).
- No capture watch on the command's block; `declare` gives the `watch_add` call that sets one (`bad_argument`).
- A capture that was never installed, or one with no rows yet (`bad_argument`).
- A frame with no blit, or one past the rows the capture kept (`bad_argument`).
- Captures on two cpus for a command whose `block` names none (`bad_argument`).
- An `area` off the screen, or a `first` past the list (`bad_argument`).

### Why it works this way

Covering is not painting. A box says where a blit's destination lands; what painted a pixel also depends on the source pixels, their transparency and any scaling, which the rows do not carry. So `topmost` is the likeliest painter, not a proven one.

The tool reads rows a capture watch already recorded and never sets one itself: a watch set behind your back would change the run. With none, the refusal gives the `watch_add` call to make, and the rows start at the next run.

The reply is a summary by default, because every blit of a frame with every field would not fit a reply. Ask for an `area` or for `detail`, and page with the same `frame`: a finished frame's rows do not change.

<details><summary>More on why</summary>

A capture keeps its rows in order and drops every row past its limit. Only the last kept frame can have lost some, and it says `rows_cut`.

A box is the destination rectangle wrapped at its plane's size, moved by the plane's origin read from the same row, and cut to the screen. On a plane drawn in pages each blit names its `page`; which page the screen shows is not in the rows.

The picture is RGB, the screen's colours with the boxes over them: a view of the data. `screen_view` gives the pens themselves. A listed blit that covers no pixel says `why`.

</details>

### Related tools

- [`gfx_blit_source`](#gfx_blit_source)
- [`gfx_load`](timeline.md#gfx_load)
- [`watch_add`](breakpoints.md#watch_add)
- [`gfx_film`](timeline.md#gfx_film)
- [`screen_view`](#screen_view)
- [`declaration_list`](breakpoints.md#declaration_list)

<details><summary>The contract your client receives</summary>

```text
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
```

</details>
<!-- scry-reference:end gfx_blits -->

<!-- scry-reference:begin gfx_blit_source -->
## `gfx_blit_source`

Show the rectangle of graphics one blit reads, decoded from the command's asset with the live palette, always unscaled.

```text
gfx_blit_source(draw_command, frame=null, index=null, pc="", margin=0, scale=0, dest="",
    seconds=5.0)
```

### Try it

This tool needs a board whose draw command states where in the source each blit reads; neither free program has one. The reply shown comes from a test program that is not distributed.

Ask:

> Show me the graphics the first blit of the newest frame reads from its source.

Call:

```text
gfx_blit_source(draw_command="blit", index=0)
```

Reply, 4 of 41 fields:

```json
{
  "summary": "gfx_blit_source blit frame 6 #0 pc 0x00002738: pages tile 0  ... (93 characters)",
  "rect": {"tile": 0, "x": 22, "y": 11, "width": 2, "height": 1, "dir_x": 1, "dir_y": 1},
  "wrap": true,
  "reads_source": true
}
```

The first blit of frame 6 reads a 2 by 1 rectangle at (22, 11) of tile 0 of the asset `pages`. `reads_source` is true: the manifest says this blit does read its source.

<details><summary>The whole reply</summary>

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
    "path": "$TMPDIR/mame-mcp-<run>/gfx/source-1.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
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

</details>

### Arguments

- `draw_command` (string, required): The name of a draw command in the loaded `gfx.yaml`, as for `gfx_blits`.
- `frame` (integer, optional): The frame the blit belongs to. Left out, the newest frame before this stop that has blits.
- `index` (integer, optional): The blit's order in its frame, as `gfx_blits` lists it. Give this or `pc`.
- `pc` (string, default `""`): The address or symbol of the code that issued the blit, instead of `index`. It must have issued one blit in the frame.
- `margin` (integer (>= 0, <= 16), default `0`): Pixels of context shown round the rectangle, 0 to 16, dimmed. Left out, none.
- `scale` (integer, default `0`): The whole factor the picture is enlarged by, up to 8. 0 picks the largest that fits.
- `dest` (string, default `""`): A new file the PNG is written to. Left empty, it goes to the session's temporary folder.
- `seconds` (number (> 0, <= 600.0), default `5.0`): The time limit of the read, in seconds.

### What comes back

- `rect`: What the blit reads: the `tile`, the `x`, `y`, `width` and `height` inside it, and the directions `dir_x` and `dir_y`.
- `image`: The picture. With a `margin` it is a view: the context dimmed, the rectangle ringed in white.
- `data`: With a `margin`, the exact indexed PNG of the whole window, each pixel its value.
- `box`: Where the rectangle sits inside the picture: `[x, y, width, height]`.
- `reads_source`: `false` when the manifest says this blit reads no source. The rectangle is then where its registers point, not what it drew.
- `not_proved`: The command's fields this answer relied on whose status in the manifest is not `proved`.

<details><summary>All 46 reply fields</summary>

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
- `asset` (string)
- `blit_pc` (string)
- `blit_symbol` (string)
- `blits_in_frame` (integer)
- `box` (array)
- `call` (string)
- `callback_errors` (object)
- `data` (object)
- `destination` (object)
- `draw_command` (string)
- `entries` (integer)
- `evaluated_by` (string)
- `format` (string)
- `frame_blit` (integer)
- `image` (object)
- `index` (integer)
- `indexes` (array)
- `lines_ahead` (integer)
- `margin` (integer)
- `n` (integer)
- `not_proved` (array)
- `palette` (string)
- `palettes` (array)
- `pc_before` (string)
- `pen_base` (integer)
- `reader_steps` (integer)
- `reads_source` (boolean)
- `rect` (object)
- `source_tile` (integer)
- `tag` (string)
- `tile_height` (integer)
- `tile_width` (integer)
- `tiles_available` (integer)
- `wrap` (boolean)

</details>

### What it refuses

- Whatever `gfx_blits` refuses of the manifest, the capture or the frame.
- A command with no `asset`, or without the `source_x` and `source_y` roles (`bad_argument`).
- Both `index` and `pc`, or neither (`bad_argument`).
- A `pc` that issued no blit in the frame, or several; `indexes` lists them (`bad_argument`).
- A tile past the asset's block, or a rectangle that leaves a tile whose asset does not wrap (`bad_argument`).
- A `pc` symbol the session does not know (`unknown_ref`).

### Why it works this way

The picture is unscaled on purpose. A blit drawn enlarged or shrunk reads another extent of the source, and how a board scales is that project's rule, which is not applied here. The rectangle is the size of the destination, taken from the source origin.

A `margin` is dimmed because, drawn like the rectangle, its pixels would read as part of the blit: an offset that does not exist. That view is RGB, since an indexed file cannot dim a pen without a second palette entry, which a board using all 256 pens does not have.

<details><summary>More on why</summary>

The rectangle is decoded with the tile's own layout, its offsets narrowed to the rectangle, which is exact for every layout MAME's layout terms can state. The origin carries each field's `add` from the manifest, and the rectangle wraps inside the tile when the asset says `wrap`.

</details>

### Related tools

- [`gfx_blits`](#gfx_blits)
- [`gfx_view`](#gfx_view)
- [`gfx_load`](timeline.md#gfx_load)

<details><summary>The contract your client receives</summary>

```text
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
```

</details>
<!-- scry-reference:end gfx_blit_source -->
