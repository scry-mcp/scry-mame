# The Read tools

<!-- scry-reference:begin read_memory -->
## `read_memory`

*Read memory*

```text
read_memory(ref, length=16, cpu="")
```

Read `length` bytes (1..1024) at `ref` (a symbol or `0x` address) of `cpu` (`subcpu`;
the visible one when empty). A range past the cpu's program space is `bad_argument`.

Reply: `addr`, `length`, `hex`, `cpu`. Above the ceiling use `memdump`. A write-only range
(`latch`) answers zeros with no error: use `read_block`.

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `ref` | string | required |
| `length` | integer (>= 1, <= 1024) | `16` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `addr` | string |
| `cpu` | string or object |
| `hex` | string |
| `length` | integer |

Example, from a live run:

```json
{
  "ref": "0x400",
  "length": 8
}
```

```json
{
  "summary": "read_memory 0x400: 8 bytes at 0x00000400: 46fc270048e7f000",
  "status": "ok",
  "addr": "0x00000400",
  "length": 8,
  "hex": "46fc270048e7f000",
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end read_memory -->

Reads come back as hex text, two characters per byte; a frame of VRAM through them is a haystack in the conversation rather than data, which is why the ceiling exists and `memdump` writes a file. A write-only range answers zeros because its values live in the share behind the write handler, not on the read side. Each cpu is served by its own thread of the gdbstub's thread patch; a build without it serves only its first cpu and refuses another with `bad_argument`. With no address mask known the range bound is the console's.

<!-- scry-reference:begin read_block -->
## `read_block`

*Read a memory share or region*

```text
read_block(tag="", ref="", offset=0, length=16, seconds=5.0, cpu="")
```

Read `length` bytes (1..1024) of a block MAME keeps by tag: a share (what
`symbols_find` calls `latch`) or a region (a ROM no cpu maps).

`tag` (`blitram` or `:blitram`) with `offset`, or `ref` whose map entry names the block;
`cpu` names `ref`'s space; `seconds` bounds the console's answer.

Reply: `kind`, `tag`, `size`, `bytewidth`, `endianness`, `offset`, `length`, `hex`; with
`ref` also `addr`, `addr_cpu`, `start`; then the stop survey. `unknown_ref`: no such tag
(`tags` lists them) or `ref` in no entry naming a block. `bad_argument`: `offset` with
`ref`, `cpu` with `tag`, past the block's end.

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `tag` | string | `""` |
| `ref` | string | `""` |
| `offset` | integer or string | `0` |
| `length` | integer (>= 1, <= 1024) | `16` |
| `seconds` | number (> 0, <= 600.0) | `5.0` |
| `cpu` | string | `""` |

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
| `endianness` | string |
| `evaluated_by` | string |
| `hex` | string |
| `kind` | string |
| `length` | integer |
| `lines_ahead` | integer |
| `map_entry` | object |
| `offset` | integer |
| `pc_before` | string |
| `pending` | boolean |
| `reader_steps` | integer |
| `regpoint_hit` | object |
| `seen_bytes` | integer |
| `size` | integer |
| `start` | string |
| `tag` | string |
| `tags` | object |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "tag": "maincpu",
  "offset": 1024,
  "length": 8
}
```

```json
{
  "summary": "read_block region :maincpu: 8 bytes at offset 0x400 of 0x100000: 46fc270048e7f000",
  "status": "ok",
  "kind": "region",
  "tag": ":maincpu",
  "size": 1048576,
  "bytewidth": 2,
  "endianness": "big",
  "offset": 1024,
  "length": 8,
  "hex": "46fc270048e7f000",
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#1",
  "pc_before": "0x000f2034",
  "cause": "read_block: one step",
  "stop_seq": 2,
  "pc": "0x000f2038",
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
    "SP": "0x00201000",
    "PS": "0x2700",
    "PC": "0x000f2038"
  },
  "instruction": {
    "address": "0F2038",
    "bytes": "33FC00000020351C",
    "text": "move.w  #$0, $20351c.l",
    "symbol": "RESET",
    "delta": 4
  },
  "following": [
    "0F2040: 4EB8 25DC                jsr     $25dc.w",
    "0F2044: 33FC D800 0020 351C      move.w  #$d800, $20351c.l",
    "0F204C: 4EB9 000F 24DE           jsr     $f24de.l",
    "0F2052: 23FC 000F 4414 0020 2EA4 move.l  #$f4414, $202ea4.l"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  }
}
```
<!-- scry-reference:end read_block -->

By `tag`, the spelling tried second is the full one (`:blitram`), because MAME names a share bare and a region either way.

A share is a block a map entry writes through a handler and reads nowhere, so `read_memory` there answers zeros; a region is a ROM no cpu's space maps, `gfx1` say. The call alters nothing. It goes through MAME's Lua console and costs what `lua` costs, so the read is of the state after the instruction at the stop's pc; to see the block as a write there found it, stop one instruction earlier. Past the block's end MAME answers zeros in silence, which is why the call refuses. A `tag` is tried bare first, then in its full spelling (`:blitram`), because MAME names a share bare and a region either way. A tag with whitespace is `bad_argument`. Offset is an integer or a `0x` string; with `ref` it is the address's distance into the block.

<!-- scry-reference:begin registers -->
## `registers`

*Read the registers*

```text
registers(from_last_stop=false, cpu="")
```

Every register of `cpu` (`subcpu`; the visible one when empty), by the gdbstub's name.
`from_last_stop=True` returns the registers as of the last stop, answers on a running
machine, and is refused before any stop and beside `cpu`.

Reply: `regs` (name to hex string), `register_bits` (name to declared width), `cpu`,
`superseded` (with `from_last_stop`). A cpu with no register map or an unknown byte order is
`no_channel`.

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `from_last_stop` | boolean | `false` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `cpu` | string |
| `register_bits` | object |
| `regs` | object |
| `superseded` | boolean |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "registers: 18 registers",
  "status": "ok",
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
    "SP": "0x00201000",
    "PS": "0x2700",
    "PC": "0x000f2038"
  },
  "register_bits": {
    "D0": 32,
    "D1": 32,
    "D2": 32,
    "D3": 32,
    "D4": 32,
    "D5": 32,
    "D6": 32,
    "D7": 32,
    "A0": 32,
    "A1": 32,
    "A2": 32,
    "A3": 32,
    "A4": 32,
    "A5": 32,
    "FP": 32,
    "SP": 32,
    "PS": 16,
    "PC": 32
  },
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end registers -->

A fixed eight digits would make a 16-bit register look 32-bit and its own ceiling look like a broken tool.

Each register prints at its declared width, so a 16-bit V30 register named `EAX` says 16 rather than leaving it to a digit count. Names come from the target description: a 68000 board answers D0..D7/A0..A5/FP/SP/PS/PC, an x86 or V30 board EAX..GS with EIP; the m68k aliases A6, A7, SR, USP are accepted by `set_register` but not listed. A stop's registers are marked `superseded` so they are never read as the current value. Each cpu is served by its own thread of the gdbstub's thread patch; a build without it serves only its first cpu and refuses another with `bad_argument`.

<!-- scry-reference:begin disassemble -->
## `disassemble`

*Disassemble*

```text
disassemble(ref, length=16, cpu="")
```

Disassemble `length` bytes (1..1024) from `ref` of `cpu` (`subcpu`; the visible one
when empty), as MAME's `dasm`; the last instruction is completed.

Reply: `addr`, `length`, `cpu`, `lines`, `flow` (per line: `call`, `branch`, `return`,
`sequential`, `unknown`), `flow_source`, `note`, and on a relocated board `resolved` (per
direct memory operand: `line`, `operand`, `offset`, `linear`, `symbol`, `delta`). The
printed operand is the map's offset: `read_memory` and `watch_add` take `linear`.
Register-relative operands are not resolved.

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `ref` | string | required |
| `length` | integer (>= 1, <= 1024) | `16` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `addr` | string |
| `cpu` | string or object |
| `flow` | array |
| `flow_source` | string |
| `length` | integer |
| `lines` | array |
| `resolved` | array |

Example, from a live run:

```json
{
  "ref": "irq_vblank",
  "length": 8
}
```

```json
{
  "summary": "disassemble irq_vblank: 2 lines at 0x00000400",
  "status": "ok",
  "addr": "0x00000400",
  "length": 8,
  "lines": [
    "000400: 46FC 2700 move    #$2700, SR",
    "000404: 48E7 F000 movem.l D0-D3, -(A7)"
  ],
  "cpu": ":maincpu",
  "flow": [
    "sequential",
    "sequential"
  ],
  "flow_source": "mnemonic_table:m68000"
}
```
<!-- scry-reference:end disassemble -->

`flow` is read off the mnemonic by a table per cpu type, because MAME computes the same distinction and no channel hands it on.

`flow` is read off the mnemonic by a table per cpu type, because MAME's console drops its own step flags; `flow_source` is `mnemonic_table:<type>`, or `none` with a `note` when no table exists or the opcode-less listing did not come out. A word MAME cannot decode is marked by MAME (`dc.w ...; ILLEGAL`). A line MAME holds a comment for ends ` // <text>`. A register-relative operand's address is the register's at run time, so it cannot be resolved. A console that wrote no listing, or an empty one, is `status: INVALID` with `message`.

<!-- scry-reference:begin find -->
## `find`

*Find bytes in memory*

```text
find(data_hex, ref="", length=0, symbol_class="", cpu="")
```

Every address in `length` bytes from `ref` holding `data_hex` (whole hex bytes,
1..126), in the program space of `cpu` (`subcpu`; the visible one when empty).

`symbol_class` (`DATA`, `CODE`...) replaces `ref`+`length` with that class's symbol range,
which misses a match past the last symbol's start. Both, neither, or an unknown class is
refused. A range past the program space is `bad_argument`.

Reply: `addr`, `length`, `span` (`from`, `length`, `source`), `hits` (at most 400,
highest kept), `hits_total`, `truncated`, `cpu`, `symbol_class`. An unreadable console
answer is `status: INVALID`.

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `data_hex` | string | required |
| `ref` | string | `""` |
| `length` | integer | `0` |
| `symbol_class` | string | `""` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `addr` | string |
| `cpu` | string or object |
| `hits` | array |
| `hits_total` | integer |
| `length` | integer |
| `span` | object |
| `symbol_class` | string |
| `truncated` | boolean |

Example, from a live run:

```json
{
  "ref": "0x0",
  "length": 1024,
  "data_hex": "00"
}
```

```json
{
  "summary": "find 00 in 0x400 bytes at 0x0: 510 hits",
  "status": "ok",
  "addr": "0x00000000",
  "length": 1024,
  "span": {
    "from": "0x00000000",
    "length": 1024,
    "source": "ref+length"
  },
  "hits": [
    "0x000000e0",
    "0x000000e1",
    "0x000000e4",
    "0x000000e5",
    "0x000000e8",
    "0x000000e9",
    "... 394 more"
  ],
  "hits_total": 510,
  "truncated": true,
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end find -->

`span` says over which bytes a zero was found. There is no whole-address-space sweep, because the space's extent is not something the symbol table says.

The console takes each byte as a parameter of its own, which bounds the pattern. `span` says over which bytes a zero was found. A hit is where the pattern starts, so one running past the window's end is counted. A linker map carries no sizes, so a class's span ends at its last symbol's start; a note on `span` says so. There is no whole-address-space sweep because the extent of the space is not something the symbol table says.

<!-- scry-reference:begin history -->
## `history`

*Instruction history*

```text
history(limit=32, cpu="")
```

The last `limit` (1..256) instructions `cpu` retired before the stop, oldest
first.

Reply: `asked`, `lines` (`<addr>: <instruction>`), `cpu`, `note`. No disassembler:
`no_channel`.

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `limit` | integer (>= 1, <= 256) | `32` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `asked` | integer |
| `cpu` | string or object |
| `lines` | array |

Example, from a live run:

```json
{
  "limit": 4
}
```

```json
{
  "summary": "history: 2 instructions of 4 asked",
  "status": "ok",
  "asked": 4,
  "lines": [
    "0F2034: move    #$2700, SR",
    "0F2038: move.w  #$0, $20351c.l"
  ],
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end history -->

A cpu that has retired none answers no lines with a `note`; a reply whose lines are not of the `<addr>: <instruction>` shape is `status: INVALID`, never a trail.

<!-- scry-reference:begin memdump -->
## `memdump`

*Dump memory to a file*

```text
memdump(ref, length, dest, cpu="")
```

Write `length` bytes from `ref` of `cpu` (`subcpu`) to the new file `dest` (absolute or `~`-led, in a directory that exists, with no comma, semicolon, quote, whitespace, bracket or control character).

Reply: `addr`, `length`, `path`, `bytes`, `cpu`. A file not `length` bytes, or whose first
bytes differ from a protocol read, is `status: INVALID`; a refused control read is
`readback_refused`, a broken channel `session_broken`. A range past the program space is
`bad_argument`.

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `ref` | string | required |
| `length` | integer | required |
| `dest` | string | required |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `addr` | string |
| `bytes` | integer |
| `cpu` | string or object |
| `length` | integer |
| `path` | string |

Example, from a live run:

```json
{
  "ref": "0x0",
  "length": 16,
  "dest": "$TMPDIR/mame-live-matrix-5322d43c2c7c/jobs-scratch/A/f10.bin"
}
```

```json
{
  "summary": "memdump 0x0: 16 bytes to $TMPDIR/mame-live-matrix-5322d43c2c7c/jobs-scratch/A/f10.bin",
  "status": "ok",
  "addr": "0x00000000",
  "length": 16,
  "path": "$TMPDIR/mame-live-matrix-5322d43c2c7c/jobs-scratch/A/f10.bin",
  "bytes": 16,
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end memdump -->

The dump is written by MAME's own console `save`, so the bytes never cross the socket; the first-bytes comparison is the known-answer control. A range that wraps would hang `save`, which is why every refusal comes before it and leaves no file. The control reads the same cpu through its own thread of the gdbstub's thread patch; a build without it reads only its first cpu and another is refused.

<!-- scry-reference:begin screen_map_find -->
## `screen_map_find`

*Which mapped screen is this*

```text
screen_map_find()
```

Which mapped screen the machine shows. Reply: `matched`, `kind` and `size`; when matched,
`screen`, `layer`, `controls` (`name`, `rect`, `centre`), in the program's units; when not,
`screens_mapped` and, if the view fits the map, `screens_tried` and `screens_unjudged`
(signed by index on a screen with no palette), else `view_fits` false. None mapped:
`needs_call`.

Reference: REFERENCE.md, Screen maps.

Takes no argument.

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
| `controls` | array |
| `evaluated_by` | string |
| `kind` | string |
| `layer` | string |
| `lines_ahead` | integer |
| `matched` | boolean |
| `pc_before` | string |
| `reader_steps` | integer |
| `screen` | string |
| `screens_mapped` | integer |
| `screens_tried` | integer |
| `screens_unjudged` | integer |
| `size` | array |
| `view_fits` | boolean |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "screen_map_find: probe (session), 0 controls",
  "status": "ok",
  "matched": true,
  "screen": "probe",
  "layer": "session",
  "kind": "pixel",
  "size": [
    336,
    252
  ],
  "controls": [],
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#5",
  "pc_before": "0x000025e0",
  "cause": "screen_map_find: one step",
  "stop_seq": 6,
  "pc": "0x000025e8",
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
    "SP": "0x00200fc4",
    "PS": "0x2708",
    "PC": "0x000025e8"
  },
  "instruction": {
    "address": "0025E8",
    "bytes": "41F900201000",
    "text": "lea     $201000.l, A0",
    "symbol": "BOOT_INIT",
    "delta": 12
  },
  "following": [
    "0025EE: 203C 0000 E927      move.l  #$e927, D0",
    "0025F4: 4218                clr.b   (A0)+",
    "0025F6: 51C8 FFFC           dbra    D0, $25f4",
    "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l",
    "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  }
}
```
<!-- scry-reference:end screen_map_find -->

It captures the screen once for all the mapped screens, session layer first and then the file's, with the size compared before any signature: each capture is a Lua chunk, and a map of many screens must not cost one per screen. A screen matches when its size and every region's signature are the screen's, each region signed in colour or, on a screen that says `"cells": "index"`, by palette index; the capture recovers the pens only when such a screen is mapped.

<!-- scry-reference:begin screen_map_write -->
## `screen_map_write`

*Write the screen map*

```text
screen_map_write(method, screen="", match=null, controls=null, cells="", path="", scale=null, margin=null, dest="", overwrite=null)
```

The screen map: an application's screens, each known by the signatures of its stable
regions, and their controls, in a session layer and a file layer.

`add`: the screen shown now as `screen` in the session layer, one capture signing each
`match` crop ([x, y, width, height], 1..16), `controls` ([{"name", "rect"}]) naming its
places to read; needs the machine stopped. `cells` `index` (a pixel screen; default
`rgb`) signs the palette indices drawn, not the colours shown, so one map knows a program
shown through two palettes; a screen with no palette refuses it (`no_channel`). Reply: `screen`, `kind`, `size`,
`cells`, `match`, `controls`, `replaced`, `shadows_file`.

`load`: `path` (`<application>.screen-map.json`, absolute or `~`-led) as the file layer, held by the
server; nothing is written to disk. `scale` (1..8) and `margin` [x, y] (machine pixels on
each side) say how the program's picture sits on this machine's screen; maps and `add`'s
crops are in the program's units. Reply: `path`, `application`, `mode`, `screens`, `controls`.

`save`: both layers as one map to `dest`, refused there without `overwrite`, made the file
layer, in the loaded map's `mode` (`verified` when none was loaded). Reply: `path`,
`application`, `mode`, `screens`, `controls`, `promoted`.

Refused: an argument the method does not take; a misshapen name, crop, control, view or
file (`bad_argument`); nothing mapped to save (`needs_call`).

Reference: REFERENCE.md, Screen maps.

| argument | type | default |
|---|---|---|
| `method` | one of `"add"`, `"load"`, `"save"` | required |
| `screen` | string | `""` |
| `match` | array of array of integer or null | `null` |
| `controls` | array of object or null | `null` |
| `cells` | one of `""`, `"rgb"`, `"index"` | `""` |
| `path` | string | `""` |
| `scale` | integer or null | `null` |
| `margin` | array of integer or null | `null` |
| `dest` | string | `""` |
| `overwrite` | boolean or null | `null` |

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
| `application` | string |
| `call` | string |
| `cells` | string |
| `controls` | integer |
| `evaluated_by` | string |
| `kind` | string |
| `lines_ahead` | integer |
| `match` | array |
| `mode` | string |
| `path` | string |
| `pc_before` | string |
| `promoted` | array |
| `reader_steps` | integer |
| `replaced` | boolean |
| `screen` | string |
| `screens` | integer |
| `shadows_file` | boolean |
| `size` | array |

Example, from a live run:

```json
{
  "method": "add",
  "screen": "probe",
  "match": [
    [
      0,
      0,
      8,
      8
    ]
  ]
}
```

```json
{
  "summary": "screen_map_write add: probe (pixel 336x252), 1 region, 0 controls",
  "status": "ok",
  "screen": "probe",
  "kind": "pixel",
  "size": [
    336,
    252
  ],
  "cells": "rgb",
  "match": [
    {
      "crop": [
        0,
        0,
        8,
        8
      ],
      "signature": "d275923c4035816a"
    }
  ],
  "controls": 0,
  "replaced": false,
  "shadows_file": false,
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#4",
  "pc_before": "0x000025dc",
  "cause": "screen_map_write add: one step",
  "stop_seq": 5,
  "pc": "0x000025e0",
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
    "SP": "0x00200fc4",
    "PS": "0x2704",
    "PC": "0x000025e0"
  },
  "instruction": {
    "address": "0025E0",
    "bytes": "33FCFFFF00720004",
    "text": "move.w  #$ffff, $720004.l",
    "symbol": "BOOT_INIT",
    "delta": 4
  },
  "following": [
    "0025E8: 41F9 0020 1000      lea     $201000.l, A0",
    "0025EE: 203C 0000 E927      move.l  #$e927, D0",
    "0025F4: 4218                clr.b   (A0)+",
    "0025F6: 51C8 FFFC           dbra    D0, $25f4",
    "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  }
}
```
<!-- scry-reference:end screen_map_write -->
