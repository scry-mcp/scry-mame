# The Read tools

<!-- scry-reference:begin read_memory -->
## `read_memory`

*Read memory*

```text
read_memory(ref, length=16, cpu="")
```

Read `length` bytes of memory at `ref` (a symbol name or a `0x` address), `length` in
1..1024, of `cpu` (`subcpu`; the visible one when empty). Each cpu is served by its own thread of the gdbstub's thread patch (`status`'s `threads`); a build without it serves its first cpu alone, whatever is visible, and refuses another (`bad_argument`). A range whose last byte lies past that cpu's program space (the address mask `start` read) is `bad_argument` naming the mask; with no mask known the range is the console's.

Reply: `addr`, `length`, `hex`, `cpu` (the one read). Above the ceiling the answer
is `memdump`, which writes to a file: a read comes back as hex text, two characters per byte,
and a frame of VRAM through it is a haystack in the conversation rather than data. A range whose
read side is unmapped (a write-only block, `latch` to `symbols_find`) answers ZEROS here with no
error: the values live in the share behind its handler, and `read_block(ref=...)` reads them.
Needs the machine STOPPED (else `not_stopped`).

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

<!-- scry-reference:begin read_block -->
## `read_block`

*Read a memory share or region*

```text
read_block(tag="", ref="", offset=0, length=16, seconds=5.0, cpu="")
```

Read `length` bytes (1..1024) of a memory BLOCK MAME keeps by tag: a SHARE (a block a
map entry writes through a handler and reads nowhere, so `read_memory` there answers zeros with
no error and `symbols_find` calls it `latch`) or a REGION (a ROM no cpu's space maps,
`gfx1` say). It alters nothing.

Arguments, one block per call: `tag` (as MAME names it, `blitram` or `:blitram`) with `offset`
(an integer or a `0x` string) into it, or `ref` (a symbol or `0x` address in the program space) whose
map entry names the block, the offset then being the address's distance into it; `length`,
the count asked (left out, a default); `cpu` (`subcpu`) names the cpu whose space `ref` is
in, the visible one when empty. `seconds`: the wait for the console's answer.

It goes through MAME's Lua console and costs what `lua` costs, so the read is of the state
AFTER the instruction at the stop's pc: to read the block as a write there found it, stop one
instruction earlier. Needs the machine STOPPED (else `not_stopped`).

Reply: `kind` (`share` | `region`), `tag` (the full one), `size`, `bytewidth`, `endianness`,
`offset`, `length`, `hex`; with `ref` also `addr`, `addr_cpu` and `start` (the entry's first
address); the console's account as `lua` reports it; then the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine).
INVALID `unknown_ref` when the tag matches none (with `tags`, every block the machine HAS),
when `ref` is inside no map entry (with `addr`), or when its entry names no block (with
`map_entry`); `bad_argument` for `offset` beside `ref`, `cpu` beside `tag`, a tag with
whitespace, and past the block's end, where MAME answers zeros in silence.

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
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0F2038: 33FC 0000 0020 351C      move.w  #$0, $20351c.l",
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

<!-- scry-reference:begin registers -->
## `registers`

*Read the registers*

```text
registers(from_last_stop=false, cpu="")
```

Every register of `cpu` (`subcpu`; the visible one when empty), by the name MAME's gdbstub
gives it, each printed at its own declared width. Each cpu is served by its own thread of the gdbstub's thread patch (`status`'s `threads`); a build without it serves its first cpu alone, whatever is visible, and refuses another (`bad_argument`). Needs the machine STOPPED (else `not_stopped`).
`from_last_stop=True` hands back the registers AS THEY WERE at the last stop, marked
`superseded: true` with `last_stop` and the `cpu` it stopped on, never as the current value, and
answers on a running machine; refused before any stop, and beside `cpu`: those are the stop
survey's.

Reply: `regs` (name to hex string), `register_bits` (name to the declared width in bits, so a
16-bit V30 register named `EAX` says 16 rather than leaving it to a digit count) and `cpu` (the
one read). The names come from the target description: a 68000 board answers
D0..D7/A0..A5/FP/SP/PS/PC, an x86 or V30 board EAX..GS with EIP. The m68k aliases `A6`, `A7`,
`SR`, `USP` are accepted by `set_register` but not listed here. A cpu the stub does not describe
(no register map), or whose byte order is not established, is `no_channel`.

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

<!-- scry-reference:begin disassemble -->
## `disassemble`

*Disassemble*

```text
disassemble(ref, length=16, cpu="")
```

Disassemble `length` BYTES (1..1024) from `ref` of `cpu` (`subcpu`; the visible one
when empty), as MAME's own `dasm` prints them.

Reply: `addr`, `length`, `cpu` (the one decoded), `lines` (MAME's text verbatim, one line per
decoded item; a word MAME could not decode is marked by MAME, `dc.w ...; ILLEGAL`; the listing
completes the instruction that straddles the end, so it may run a little past `length`), and on
a board whose table was relocated by `bases`, `resolved`: every DIRECT memory operand (`word ptr
[0C014h]`) with `line` (its index in `lines`), `operand`, `offset`, and per relocated `class`
the `linear` address under that base with the nearest `symbol` at or below it and `delta`. THE
OPERAND AS PRINTED IS THE MAP'S OFFSET, NOT AN ADDRESS: `read_memory` and `watch_add` take
`linear`. Register-relative operands (`ds1:[bw-31BBh]`, `[ix]`) are not resolved: their address
is the register's at run time. `flow`, one class per line of `lines` (`call`, `branch`,
`return`, `sequential`, or `unknown` for a word the table does not list), and `flow_source`,
where the class came from: `mnemonic_table:<type>` (read off the mnemonic by a table for the
cpu's MAME type, since MAME's console drops its own step flags), or `none` with a `note`
saying why no line was classified (no table for the type, or the listing without opcode bytes
did not come out). A line MAME holds a comment for ends ` // <text>` (`comment_add`).
`status: INVALID` with `message` when the console wrote no listing, or an empty one.
Needs the machine STOPPED (else `not_stopped`).

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
| `note` | string |
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

<!-- scry-reference:begin find -->
## `find`

*Find bytes in memory*

```text
find(data_hex, ref="", length=0, symbol_class="", cpu="")
```

Every address in `length` bytes from `ref` holding the bytes `data_hex` (whole hex bytes,
two digits each, 1..126 of them: the console takes each byte as a parameter of
its own), in the program space of `cpu` (`subcpu`; the visible one when empty).

`symbol_class` searches within a SYMBOL CLASS instead of a hand-counted `ref`+`length`: a class
name the symbol file carries (`DATA`, `CODE`, ...), whose loaded symbols give the range, so a
one-byte pattern in DATA skips the CODE where its opcode also lives. The span is that class's
symbols' [min, max] address; a match PAST the last symbol's own start is not covered, because
a linker map carries no sizes, so pass `ref`+`length` for an exact range. `symbol_class` with
`ref` or `length` is refused, and a class the table does not carry is refused naming it.

Reply: `addr`, `length`, `span` (WHAT WAS EXAMINED, so a zero says over which bytes: `from`,
`length`, `source` (`class symbols`, with a `note` on the uncovered tail; or `ref+length`)),
`hits` (hex addresses in address order, at most 400: when truncated, the HIGHEST
addresses are kept; a hit is where the pattern STARTS, so one running past the window's end is
counted), `hits_total` (every hit), `truncated`, `cpu` (the one searched), and `symbol_class`
when one was given. A console answer other than `Found at <addr>` lines or `Not found` is
`status: INVALID` with `message`, never a count read off half of it. With neither `symbol_class`
nor `ref`+`length` the call is refused naming both: there is
no whole-address-space sweep. A range whose last byte lies past that cpu's program space (the address mask `start` read) is `bad_argument` naming the mask; with no mask known the range is the console's. Needs the machine STOPPED (else `not_stopped`).

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

<!-- scry-reference:begin history -->
## `history`

*Instruction history*

```text
history(limit=32, cpu="")
```

The last `limit` (1..256, MAME's own depth) instructions `cpu` (`subcpu`; the
visible one when empty) executed before the stop, as MAME's `history` lists them, oldest first.

Reply: `asked` (the argument), `lines` (MAME's text verbatim, `<addr>: <instruction>`: fewer
than asked when fewer have retired, one at the boot, none with a `note` for a cpu that has
retired none), `cpu` (the one whose trail it is). A cpu MAME cannot disassemble is
`no_channel`; a reply whose lines are not of that shape is `status: INVALID` with `message`,
never a trail. Needs the machine STOPPED (else `not_stopped`).

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
| `note` | string |

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

<!-- scry-reference:begin memdump -->
## `memdump`

*Dump memory to a file*

```text
memdump(ref, length, dest, cpu="")
```

Write `length` bytes of memory from `ref` of `cpu` (`subcpu`; the visible one when empty) to
the file `dest`, and CHECK the file.

Reply: `addr`, `length`, `path`, `bytes`, `cpu` (the one dumped). The dump is written by MAME's
own console `save`, so the bytes never cross the socket; the file must then be exactly `length`
bytes and its first bytes must equal a protocol read of the same range (the known-answer
control), else the reply is `status: INVALID` with `message`; a control read that breaks the
channel is `session_broken` naming the `path` the file was left at. `dest` must be absolute or `~`-led, in a directory that exists, with no comma, semicolon, quote, whitespace, bracket or control character,
and not there yet. A range whose last byte lies past that cpu's program space (the address mask `start` read) is `bad_argument` naming the mask; with no mask known the range is the console's. A range that wraps would hang the console's
`save`, and one past the space never reaches it. The control reads the same cpu, through its own
thread of the gdbstub's thread patch; a build without it reads only its first cpu, and another
is refused. Each refusal happens before `save`, so a refused call never leaves a file behind. A
control read the stub refuses is `readback_refused`; one that breaks the channel is
`session_broken`, which LATCHES. Needs the machine STOPPED (else `not_stopped`).

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
  "dest": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f10.bin"
}
```

```json
{
  "summary": "memdump 0x0: 16 bytes to $TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f10.bin",
  "status": "ok",
  "addr": "0x00000000",
  "length": 16,
  "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f10.bin",
  "bytes": 16,
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end memdump -->

<!-- scry-reference:begin map_add -->
## `map_add`

*Map the screen in front of you*

```text
map_add(screen, match, controls=null)
```

Map the screen the machine shows NOW as `screen` in the SESSION layer: one capture signs
each `match` crop (`[x, y, width, height]`, 1..16, regions that stay still on that screen,
never a moving sprite or a counter), and `controls` (`[{"name", "rect"}]`, a `rect` shaped as
a crop) name its controls, in the screen's pixels. A screen of the same name in the file is
shadowed (`shadows_file`). A board takes its inputs by port and field (`input`): a control is
a place to read, not one to click. Needs the machine STOPPED (else `not_stopped`); a `start` empties the session layer.

Reply: `screen`, `kind`, `size`, `match` (each crop with its `signature`), `controls`,
`replaced`, `shadows_file`, the console's account, the survey. Refused: a misshapen name, crop
or control, a rectangle off the screen (`bad_argument`).

Reference: REFERENCE.md, Screen maps.

| argument | type | default |
|---|---|---|
| `screen` | string | required |
| `match` | array of array of integer | required |
| `controls` | array of object or null | `null` |

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
| `controls` | integer |
| `evaluated_by` | string |
| `kind` | string |
| `lines_ahead` | integer |
| `match` | array |
| `pc_before` | string |
| `reader_steps` | integer |
| `replaced` | boolean |
| `screen` | string |
| `shadows_file` | boolean |
| `size` | array |

Example, from a live run:

```json
{
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
  "summary": "map_add: probe (pixel 336x252), 1 region, 0 controls",
  "status": "ok",
  "screen": "probe",
  "kind": "pixel",
  "size": [
    336,
    252
  ],
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
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
  "call": "MAME_MCP_LUA_END#4",
  "pc_before": "0x000025dc",
  "cause": "map_add: one step",
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
  "dasm": [
    "0025E0: 33FC FFFF 0072 0004 move.w  #$ffff, $720004.l",
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
<!-- scry-reference:end map_add -->

<!-- scry-reference:begin map_find -->
## `map_find`

*Which mapped screen is this*

```text
map_find()
```

WHICH MAPPED SCREEN the machine shows, from ONE capture and no picture: the session layer
first, then the file's; a screen matches when its size is the screen's and every region's
signature is. Needs the machine STOPPED (else `not_stopped`).

Reply: `matched`; matched, `screen`, `layer` (`session` or `file`), `kind`, `size`,
`controls` (each `name`, `rect`, `centre`); not matched, `kind`, `size`, `screens_mapped`,
`screens_tried` (of that size); the console's account, the survey. Refused: no screen mapped
(`needs_call`).

Reference: REFERENCE.md, Screen maps.

Takes no argument.

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
| `size` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "map_find: probe (session), 0 controls",
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
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
  "call": "MAME_MCP_LUA_END#5",
  "pc_before": "0x000025e0",
  "cause": "map_find: one step",
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
  "dasm": [
    "0025E8: 41F9 0020 1000      lea     $201000.l, A0",
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
<!-- scry-reference:end map_find -->

It captures the screen once for all the mapped screens, with the size compared before any signature: each capture is a Lua chunk, and a map of many screens must not cost one per screen.
