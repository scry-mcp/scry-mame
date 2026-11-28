# The Read tools

These tools read the program without writing to it: bytes of memory, the registers, the code at an address, the instructions that ran before a stop. They need the program stopped at the debugger; while it runs they refuse (`not_stopped`), except where an entry says otherwise.

An address is a `ref`: a symbol of your program, or a number written `0x`. Bare hex that names no symbol is refused (`unknown_ref`), with the `0x` spelling it most likely meant.

On a board with several cpus, a call that names no `cpu` acts on the one the debugger is showing. `read_memory`, `registers` and `memdump` read another only on a MAME whose gdbstub serves each cpu as a thread; `status` lists them in `threads`. Without that they read the first cpu and refuse any other (`bad_argument`).

## Three of them run one instruction

`read_block`, `screen_map_find` and `screen_map_write`'s `add` go through MAME's Lua console, which runs one instruction to answer. Their replies end with the readings of the new stop, as [`lua`](lua.md#lua)'s does. They write nothing to the program.

<!-- scry-reference:begin read_memory -->
## `read_memory`

Read a few bytes of memory at an address, as hex text.

```text
read_memory(ref, length=16, cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped at reset, right after `start`.

Ask:

> Read the two bytes of the IRQ vector, at 0xfff8.

Call:

```text
read_memory(ref="0xfff8", length=2)
```

Reply, 4 of 8 fields:

```json
{
  "summary": "read_memory 0xfff8 (irq+0x278): 2 bytes at 0x0000fff8 (irq+0x278): fd80",
  "addr": "0x0000fff8",
  "length": 2,
  "hex": "fd80"
}
```

The two bytes at `0xfff8` are `fd80`. They are the cpu's IRQ vector, so the interrupt routine starts at `0xfd80`.

<details><summary>The whole reply</summary>

```json
{
  "summary": "read_memory 0xfff8 (irq+0x278): 2 bytes at 0x0000fff8 (irq+0x278): fd80",
  "status": "ok",
  "ref": "0xfff8",
  "addr": "0x0000fff8",
  "length": 2,
  "hex": "fd80",
  "cpu": ":maincpu",
  "names": [
    {"field": "given.ref", "number": "0xfff8", "kind": "symbol", "name": "irq", "delta": 632},
    {"field": "addr", "number": "0x0000fff8", "kind": "symbol", "name": "irq", "delta": 632}
  ]
}
```

</details>

### Arguments

- `ref` (string, required): The address to read: a symbol or a `0x` address.
- `length` (integer (>= 1, <= 1024), default `16`): How many bytes: 1 to 1024. Left out, 16.
- `cpu` (string, default `""`): The cpu whose program memory is read. Left empty, the one the debugger is showing.

### What comes back

- `hex`: The bytes, two hex characters each, lowest address first.
- `addr`: The address `ref` resolved to.
- `cpu`: The cpu that was read.

<details><summary>All 5 reply fields</summary>

- `addr` (string)
- `cpu` (string or object)
- `hex` (string)
- `length` (integer)
- `ref` (string)

</details>

### What it refuses

- A range that runs past the cpu's program memory (`bad_argument`).

### Why it works this way

The reply is hex text in the conversation, so it is kept short: a screen's worth of video memory would bury everything else. For more, `memdump` writes the bytes to a file.

Memory the board can only write to reads back as zeros, with no error, because its values sit behind the write handler. `symbols_find` marks such an address `latch`, and `read_block` reads it.

### Related tools

- [`memdump`](#memdump)
- [`read_block`](#read_block)
- [`symbols_find`](symbols.md#symbols_find)
- [`write`](write.md#write)
- [`watch_add`](breakpoints.md#watch_add)

<details><summary>The contract your client receives</summary>

```text
Read `length` bytes (1..1024) at `ref` (a symbol or `0x` address) of `cpu` (`subcpu`;
the visible one when empty). A range past the cpu's program space is `bad_argument`.

Reply: `ref`, `addr`, `length`, `hex`, `cpu`. Above the ceiling use `memdump`. A write-only
range (`latch`) answers zeros with no error: use `read_block`.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end read_memory -->

<!-- scry-reference:begin read_block -->
## `read_block`

Read bytes MAME keeps under a tag and no cpu can read back: write-only memory, or a ROM outside every cpu's address space.

```text
read_block(tag="", ref="", offset=0, length=16, seconds=5.0, cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped once the game has drawn its sprites; the example session reads at frame 545.

Ask:

> Read four bytes of the sprite memory, from its byte 12 on.

Call:

```text
read_block(tag="spriteram", offset=12, length=4)
```

Reply, 6 of 28 fields:

```json
{
  "summary": "read_block share :spriteram: 4 bytes at offset 0x0000000c of 0x800: 5b009394",
  "kind": "share",
  "tag": ":spriteram",
  "size": 2048,
  "offset": "0x0000000c",
  "hex": "5b009394"
}
```

`spriteram` is a share, a block MAME keeps by name, 2048 bytes long. The four bytes from offset 12 are `5b009394`, one sprite's entry.

<details><summary>The whole reply</summary>

```json
{
  "summary": "read_block share :spriteram: 4 bytes at offset 0x0000000c of 0x800: 5b009394",
  "status": "ok",
  "kind": "share",
  "tag": ":spriteram",
  "size": 2048,
  "bytewidth": 1,
  "endianness": "big",
  "offset": "0x0000000c",
  "length": 4,
  "hex": "5b009394",
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#8",
  "pc_before": "0x0000fd80",
  "cause": "read_block: one step",
  "stop_seq": 10,
  "pc": "0x0000fd82",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0xff",
    "B": "0x72",
    "D": "0xff72",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd82",
    "S": "0x07f4",
    "CC": "0xf8",
    "DP": "0x00"
  },
  "instruction": {"address": "FD82", "bytes": "96B2", "text": "LDA    <$B2", "symbol": "irq", "delta": 2},
  "following": ["FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "... 9 more"],
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

- `tag` (string, default `""`): The block's name in MAME, `blitram` or `:blitram`. Give this or `ref`, never both.
- `ref` (string, default `""`): An address inside the block, instead of its tag: a symbol or a `0x` address whose address-map entry names the block.
- `offset` (integer or string, default `0`): Where to start inside the block, with `tag`: an integer or a `0x` string. Left out, its first byte.
- `length` (integer (>= 1, <= 1024), default `16`): How many bytes: 1 to 1024. Left out, 16.
- `seconds` (number (> 0, <= 600.0), default `5.0`): How long MAME's Lua console may take to answer. Left out, 5 seconds.
- `cpu` (string, default `""`): The cpu whose address map `ref` is looked up in. Left empty, the one the debugger is showing.

### What comes back

- `hex`: The bytes, two hex characters each.
- `kind`: `share` or `region`, MAME's two words for such a block.
- `tag`: The block's tag as MAME spells it in full.
- `size`: The block's length in bytes.
- `offset`: Where the read began inside the block. With `ref`, the address's distance into it.
- `start`: With `ref`: the first address of the map entry that names the block. `addr` and `addr_cpu` say what `ref` resolved to, and on which cpu.

<details><summary>All 34 reply fields</summary>

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
- `endianness` (string)
- `evaluated_by` (string)
- `hex` (string)
- `kind` (string)
- `length` (integer)
- `lines_ahead` (integer)
- `map_entry` (object)
- `offset` (string)
- `pc_before` (string)
- `pending` (boolean)
- `reader_steps` (integer)
- `regpoint_hit` (object)
- `seen_bytes` (integer)
- `size` (integer)
- `start` (string)
- `tag` (string)
- `tags` (object)
- `watch_hit` (object)

</details>

### What it refuses

- Both `tag` and `ref`, or neither; `offset` with `ref`; `cpu` with `tag`; a `tag` holding whitespace (`bad_argument`).
- A read that runs past the block's end (`bad_argument`).
- A tag the machine does not have; the refusal's `tags` lists the ones it has (`unknown_ref`).
- A `ref` no address-map entry covers, or whose entry names no block; `map_entry` then gives that entry's `start` and `end` (`unknown_ref`).

### Why it works this way

MAME keeps by tag two kinds of block that `read_memory` cannot reach. Memory that a handler only writes to, which MAME calls a share, answers zeros there. A ROM outside every cpu's address space, a region such as `gfx1`, is not there at all.

The bytes are the block after the instruction the read runs. To see the block as a write found it, stop one instruction earlier.

Past a block's end MAME answers zeros without complaint, which is why a read that runs past it is refused.

### Related tools

- [`read_memory`](#read_memory)
- [`machine_map`](machine.md#machine_map)
- [`symbols_find`](symbols.md#symbols_find)
- [`watch_add`](breakpoints.md#watch_add)
- [`lua`](lua.md#lua)

<details><summary>The contract your client receives</summary>

```text
Read `length` bytes (1..1024) of a block MAME keeps by tag: a share (what
`symbols_find` calls `latch`) or a region (a ROM no cpu maps).

`tag` (`blitram` or `:blitram`) with `offset`, or `ref` whose map entry names the block;
`cpu` names `ref`'s space; `seconds` bounds the console's answer.

Reply: `kind`, `tag`, `size`, `bytewidth`, `endianness`, `offset`, `length`, `hex`; with
`ref` also `addr`, `addr_cpu`, `start`; then the stop survey. `unknown_ref`: no such tag
(`tags` lists them) or `ref` in no entry naming a block. `bad_argument`: `offset` with
`ref`, `cpu` with `tag`, past the block's end.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end read_block -->

<!-- scry-reference:begin registers -->
## `registers`

Read the cpu's registers, now or as they were at the last stop.

```text
registers(from_last_stop=false, cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped by a watch right after the game wrote its third credit.

Ask:

> Show me the cpu's registers at this stop.

Call:

```text
registers()
```

Reply, 2 of 5 fields:

```json
{
  "summary": "registers: 10 registers",
  "cpu": ":maincpu"
}
```

Gridlee's cpu has ten registers. The whole reply, folded below, lists each under `regs`, and its width in bits under `register_bits`.

<details><summary>The whole reply</summary>

```json
{
  "summary": "registers: 10 registers",
  "status": "ok",
  "regs": {
    "A": "0x03",
    "B": "0xcf",
    "D": "0x03cf",
    "X": "0xe199",
    "Y": "0xf2e6",
    "U": "0x7acf",
    "PC": "0xb58f",
    "S": "0x07fc",
    "CC": "0x80",
    "DP": "0x00"
  },
  "register_bits": {"A": 8, "B": 8, "D": 16, "X": 16, "Y": 16, "U": 16, "PC": 16, "S": 16, "CC": 8, "DP": 8},
  "cpu": ":maincpu"
}
```

</details>

### Arguments

- `from_last_stop` (boolean, default `false`): `true` returns the registers the last stop recorded, and answers while the program runs. Left out, the registers are read now.
- `cpu` (string, default `""`): The cpu whose registers are read. Left empty, the one the debugger is showing.

### What comes back

- `regs`: Each register by name, as a hex string of its own width.
- `register_bits`: Each register's own width in bits.
- `superseded`: `true` with `from_last_stop`: the values are the last stop's, which `last_stop` identifies, not the current ones.
- `cpu`: The cpu the registers belong to.

<details><summary>All 4 reply fields</summary>

- `cpu` (string)
- `register_bits` (object)
- `regs` (object)
- `superseded` (boolean)

</details>

### What it refuses

- `from_last_stop` together with `cpu` (`bad_argument`).
- `from_last_stop` before the session's first stop (`no_stop`).
- A cpu whose registers MAME's gdbstub does not describe (`no_channel`).

### Why it works this way

Each value is printed at its register's own width, and `register_bits` states it, because a fixed eight digits would make a 16-bit register look 32-bit. A V30's 16-bit register is named `EAX` and says 16.

The names are the ones MAME's gdbstub gives the cpu. A 68000 has `D0` to `D7`, `A0` to `A5`, `FP`, `SP`, `PS` and `PC`; an x86 or a V30 has `EAX` to `GS` with `EIP`. `set_register` also takes the 68000 aliases `A6`, `A7`, `SR` and `USP`, which are not listed here.

<details><summary>More on why</summary>

The byte order is MAME's: the endianness of the cpu's program space, as `start` read it. It is not established when that read failed, or when it disagrees with the order measured for that architecture, and the cpu is then `no_channel`.

At a stop, the `regs` of such a cpu say `available: false` with a `why`, never another cpu's registers under its name.

</details>

### Related tools

- [`set_register`](write.md#set_register)
- [`cpu_info`](machine.md#cpu_info)
- [`step`](run.md#step)
- [`run_to`](run.md#run_to)
- [`history`](#history)

<details><summary>The contract your client receives</summary>

```text
Every register of `cpu` (`subcpu`; the visible one when empty), by the gdbstub's name.
`from_last_stop=True` returns the registers as of the last stop, answers on a running
machine, and is refused before any stop and beside `cpu`.

Reply: `regs` (name to hex string), `register_bits` (name to declared width), `cpu`,
`superseded` (with `from_last_stop`). A cpu with no register map or an unknown byte order is
`no_channel`.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end registers -->

<!-- scry-reference:begin disassemble -->
## `disassemble`

Disassemble the code at an address, one instruction a line, each marked as a call, a branch, a return or none of those.

```text
disassemble(ref, length=16, cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped at reset with the example session's symbol file loaded, which names `count_coin`.

Ask:

> Show me the first instructions of the routine that counts a coin.

Call:

```text
disassemble(ref="count_coin", length=12)
```

Reply, 4 of 11 fields:

```json
{
  "summary": "disassemble count_coin: 5 lines at 0x0000b583",
  "lines": [
    "B583: 7C 04 2B INC    $042B",
    "B586: 86 01    LDA    #$01",
    "B588: BB 04 2C ADDA   $042C",
    "B58B: 19       DAA",
    "B58C: B7 04 2C STA    $042C"
  ],
  "flow_source": "none",
  "note": "no mnemonic table for cpu type 'm6809' (tables: m68000, v30), so no line is classified"
}
```

Five instructions from `0xb583`: the routine adds one to `$042B`, then to the decimal copy at `$042C`. Gridlee's cpu is a 6809, one with no mnemonic table, so no line is classified and `note` says why.

<details><summary>The whole reply</summary>

```json
{
  "summary": "disassemble count_coin: 5 lines at 0x0000b583",
  "status": "ok",
  "ref": "count_coin",
  "addr": "0x0000b583",
  "length": 12,
  "lines": ["B583: 7C 04 2B INC    $042B", "B586: 86 01    LDA    #$01", "B588: BB 04 2C ADDA   $042C", "B58B: 19       DAA", "B58C: B7 04 2C STA    $042C"],
  "cpu": ":maincpu",
  "flow": ["unknown", "unknown", "unknown", "unknown", "unknown"],
  "flow_source": "none",
  "note": "no mnemonic table for cpu type 'm6809' (tables: m68000, v30), so no line is classified",
  "names": [
    {"field": "given.ref", "number": "0xB583", "kind": "symbol", "name": "count_coin"}
  ]
}
```

</details>

### Arguments

- `ref` (string, required): Where to start: a symbol or a `0x` address.
- `length` (integer (>= 1, <= 1024), default `16`): How many bytes to decode, 1 to 1024; left out, 16. The last instruction is completed even when it runs past them.
- `cpu` (string, default `""`): The cpu whose code is read. Left empty, the one the debugger is showing.

### What comes back

- `lines`: One instruction a line, as MAME's `dasm` prints it: address, bytes, text. A line with a comment ends ` // <text>`.
- `flow`: One word per line: `call`, `branch`, `return`, `sequential` or `unknown`.
- `flow_source`: What classified the lines: `mnemonic_table:<cpu type>`, or `none` with a `note` saying why no line was classified.
- `resolved`: Only when `start` was given `bases`: each direct memory operand as the address the board uses. Rows carry `line`, `operand`, `offset`, `class`, `linear`, `symbol` and `delta`.
- `addr`: The address `ref` resolved to.

<details><summary>All 9 reply fields</summary>

- `addr` (string)
- `cpu` (string or object)
- `flow` (array)
- `flow_source` (string)
- `length` (integer)
- `line_notes` (array)
- `lines` (array)
- `ref` (string)
- `resolved` (array)

</details>

### What it refuses

- A listing MAME's console did not write, or wrote empty (`unexpected_answer`).

### Why it works this way

`flow` is read off each mnemonic with a table per cpu type, because MAME's console does not say which instructions call or return.

On a segmented board MAME prints an operand as an offset inside its segment. `resolved` gives the address the board uses as `linear`, which `read_memory` and `watch_add` take, once per symbol class that has a base. An operand relative to a register is not resolved: its address is the register's value at run time.

A word MAME cannot decode is marked by MAME itself: `dc.w ...; ILLEGAL`.

### Related tools

- [`history`](#history)
- [`step`](run.md#step)
- [`symbols_find`](symbols.md#symbols_find)
- [`comment_write`](comments.md#comment_write)
- [`read_memory`](#read_memory)
- [`breakpoint_at`](breakpoints.md#breakpoint_at)

<details><summary>The contract your client receives</summary>

```text
Disassemble `length` bytes (1..1024) from `ref` of `cpu` (`subcpu`; the visible one
when empty), as MAME's `dasm`; the last instruction is completed.

Reply: `ref`, `addr`, `length`, `cpu`, `lines`, `flow` (per line: `call`, `branch`, `return`,
`sequential`, `unknown`), `flow_source`, `note`, and on a relocated board `resolved` (per
direct memory operand: `line`, `operand`, `offset`, `linear`, `symbol`, `delta`). The
printed operand is the map's offset: `read_memory` and `watch_add` take `linear`.
Register-relative operands are not resolved.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end disassemble -->

<!-- scry-reference:begin find -->
## `find`

Find every address in a range of memory that holds a given sequence of bytes.

```text
find(data_hex, ref="", length=0, symbol_class="", cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped at reset, right after `start`.

Ask:

> Find where the ROM holds the bytes 7c 04 2b, the instruction that adds one to the credits.

Call:

```text
find(data_hex="7c042b", ref="0xa000", length=24576)
```

Reply, 5 of 11 fields:

```json
{
  "summary": "find 7c042b in 0x6000 bytes at 0xa000 (credits_bcd+0x9BD4): 1 hit",
  "span": {"from": "0x0000a000", "length": 24576, "source": "ref+length"},
  "hits": ["0x0000b583"],
  "hits_total": 1,
  "truncated": false
}
```

One address holds those bytes, `0xb583`. `span` says which bytes were searched: 24576 from `0xa000`, the whole ROM.

<details><summary>The whole reply</summary>

```json
{
  "summary": "find 7c042b in 0x6000 bytes at 0xa000 (credits_bcd+0x9BD4): 1 hit",
  "status": "ok",
  "ref": "0xa000",
  "addr": "0x0000a000",
  "length": 24576,
  "span": {"from": "0x0000a000", "length": 24576, "source": "ref+length"},
  "hits": ["0x0000b583"],
  "hits_total": 1,
  "truncated": false,
  "cpu": ":maincpu",
  "names": [
    {"field": "given.ref", "number": "0xa000", "kind": "symbol", "name": "credits_bcd", "delta": 39892},
    {"field": "hits[]", "number": "0x0000b583", "kind": "symbol", "name": "count_coin"}
  ]
}
```

</details>

### Arguments

- `data_hex` (string, required): The bytes to look for, as hex: 1 to 126 whole bytes.
- `ref` (string, default `""`): Where the range begins: a symbol or a `0x` address. Give it with `length`, or give `symbol_class` instead.
- `length` (integer, default `0`): How many bytes to search from `ref`.
- `symbol_class` (string, default `""`): A class of the symbol file, `DATA` or `CODE` say, searched from its first symbol to its last. It replaces `ref` and `length`.
- `cpu` (string, default `""`): The cpu whose program memory is searched. Left empty, the one the debugger is showing.

### What comes back

- `hits`: The addresses where the bytes begin, at most 400; past that, the highest are kept.
- `hits_total`: How many addresses hold the bytes, listed or not.
- `truncated`: `true` when there are more hits than `hits` lists.
- `span`: The bytes that were searched, as `from`, `length` and `source`, so zero hits says where there are none.

<details><summary>All 9 reply fields</summary>

- `addr` (string)
- `cpu` (string or object)
- `hits` (array)
- `hits_total` (integer)
- `length` (integer)
- `ref` (string)
- `span` (object)
- `symbol_class` (string)
- `truncated` (boolean)

</details>

### What it refuses

- Both `symbol_class` and a `ref` with `length`, or neither (`bad_argument`).
- A class the symbol file does not have (`unknown_ref`).
- More than 126 bytes in `data_hex`, or hex that is not whole bytes (`bad_argument`).
- A range that runs past the cpu's program memory (`bad_argument`).
- A console answer that is neither hits nor `Not found` (`unexpected_answer`).

### Why it works this way

A hit is where the bytes begin, so a match that starts inside the range and runs past its end counts.

A linker map gives no sizes, so a class is searched only up to the start of its last symbol; `span` carries a `note` saying so.

There is no search of the whole address space, because the symbol file does not say where it ends. MAME's console takes each byte as a parameter of its own, which limits them to 126.

### Related tools

- [`scan`](scan.md#scan)
- [`read_memory`](#read_memory)
- [`memdump`](#memdump)
- [`symbols_find`](symbols.md#symbols_find)
- [`watch_add`](breakpoints.md#watch_add)

<details><summary>The contract your client receives</summary>

```text
Every address in `length` bytes from `ref` holding `data_hex` (whole hex bytes,
1..126), in the program space of `cpu` (`subcpu`; the visible one when empty).

`symbol_class` (`DATA`, `CODE`...) replaces `ref`+`length` with that class's symbol range,
which misses a match past the last symbol's start. Both, neither, or an unknown class is
refused. A range past the program space is `bad_argument`.

Reply: `ref` (with `ref`), `addr`, `length`, `span` (`from`, `length`, `source`), `hits` (at
most 400, highest kept), `hits_total`, `truncated`, `cpu`, `symbol_class`. An
unreadable console answer is `status: INVALID`.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end find -->

<!-- scry-reference:begin history -->
## `history`

List the last instructions a cpu ran before the stop, oldest first.

```text
history(limit=32, cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped by a watch right after the game wrote its third credit.

Ask:

> What were the last eight instructions the cpu ran before this stop?

Call:

```text
history(limit=8)
```

Reply, 2 of 5 fields:

```json
{
  "summary": "history: 8 instructions of 8 asked",
  "lines": [
    "B579: DEC    $0491",
    "B57C: JSR    $B583",
    "B583: INC    $042B",
    "B586: LDA    #$01",
    "B588: ADDA   $042C",
    "B58B: DAA",
    "... 2 more"
  ]
}
```

Oldest first: the call at `B57C` into the coin routine, then the routine's own instructions from `B583` on. All eight asked for came back.

<details><summary>The whole reply</summary>

```json
{
  "summary": "history: 8 instructions of 8 asked",
  "status": "ok",
  "asked": 8,
  "lines": ["B579: DEC    $0491", "B57C: JSR    $B583", "B583: INC    $042B", "B586: LDA    #$01", "B588: ADDA   $042C", "B58B: DAA", "... 2 more"],
  "cpu": ":maincpu"
}
```

</details>

### Arguments

- `limit` (integer (>= 1, <= 256), default `32`): How many instructions back: 1 to 256, the most MAME keeps for a cpu. Left out, 32.
- `cpu` (string, default `""`): The cpu whose instructions are listed. Left empty, the one the debugger is showing.

### What comes back

- `lines`: One instruction a line, `<address>: <instruction>`, oldest first. Fewer than asked means the cpu has run no more.
- `asked`: The `limit` the call asked for.
- `cpu`: The cpu the instructions belong to.

<details><summary>All 3 reply fields</summary>

- `asked` (integer)
- `cpu` (string or object)
- `lines` (array)

</details>

### What it refuses

- A cpu MAME has no disassembler for (`no_channel`).
- A console answer that is not a list of instructions (`unexpected_answer`).

### Why it works this way

A cpu that has run no instruction yet answers with no lines and a `note` saying so.

### Related tools

- [`disassemble`](#disassemble)
- [`step`](run.md#step)
- [`trace`](run.md#trace)
- [`run_to`](run.md#run_to)
- [`registers`](#registers)

<details><summary>The contract your client receives</summary>

```text
The last `limit` (1..256) instructions `cpu` retired before the stop, oldest
first.

Reply: `asked`, `lines` (`<addr>: <instruction>`), `cpu`, `note`. No disassembler:
`no_channel`.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end history -->

<!-- scry-reference:begin memdump -->
## `memdump`

Write a range of memory to a file, for ranges too large to read into the conversation.

```text
memdump(ref, length, dest, cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped at any moment: the range is ROM, which never changes.

Ask:

> Save the first 4096 bytes of the ROM at 0xa000 to a file.

Call:

```text
memdump(ref="0xa000", length=4096, dest="./tmp/demos/tour/rom.bin")
```

Reply, 5 of 9 fields:

```json
{
  "summary": "memdump 0xa000 (credits_bcd+0x9BD4): 4096 bytes to ./tmp/demos/tour/rom.bin",
  "addr": "0x0000a000",
  "length": 4096,
  "path": "./tmp/demos/tour/rom.bin",
  "bytes": 4096
}
```

The file holds 4096 bytes, as asked: `bytes` equals `length`. `path` is where it was written.

<details><summary>The whole reply</summary>

```json
{
  "summary": "memdump 0xa000 (credits_bcd+0x9BD4): 4096 bytes to ./tmp/demos/tour/rom.bin",
  "status": "ok",
  "ref": "0xa000",
  "addr": "0x0000a000",
  "length": 4096,
  "path": "./tmp/demos/tour/rom.bin",
  "bytes": 4096,
  "cpu": ":maincpu",
  "names": [
    {"field": "given.ref", "number": "0xa000", "kind": "symbol", "name": "credits_bcd", "delta": 39892},
    {"field": "addr", "number": "0x0000a000", "kind": "symbol", "name": "credits_bcd", "delta": 39892}
  ]
}
```

</details>

### Arguments

- `ref` (string, required): Where the range begins: a symbol or a `0x` address.
- `length` (integer, required): How many bytes to write.
- `dest` (string, required): The file to create, required: an absolute or `~`-led path, in a folder that exists, not there yet. The path holds no space, comma, semicolon, quote or bracket.
- `cpu` (string, default `""`): The cpu whose program memory is written out. Left empty, the one the debugger is showing.

### What comes back

- `path`: The file as written; a `note` says so when its name is not the one `dest` gave.
- `bytes`: The file's size, which equals `length`.
- `addr`: The address `ref` resolved to.

<details><summary>All 6 reply fields</summary>

- `addr` (string)
- `bytes` (integer)
- `cpu` (string or object)
- `length` (integer)
- `path` (string)
- `ref` (string)

</details>

### What it refuses

- A `dest` that is relative, already there, or in a folder that does not exist (`bad_argument`).
- A range that runs past the cpu's program memory (`bad_argument`).
- A file that is not `length` bytes, or whose first bytes differ from a direct read of the same memory (`readback_refused`).
- A debugger connection that breaks during that direct read (`session_broken`).

### Why it works this way

MAME's own `save` command writes the file, so the bytes never pass through the debugger connection. The server then reads the first bytes of the range directly and compares them with the file, which is what shows the file holds the memory asked for.

A range that runs past the cpu's program memory would hang `save`, so it is refused before anything is written and leaves no file.

### Related tools

- [`read_memory`](#read_memory)
- [`find`](#find)
- [`snapshot`](captures.md#snapshot)
- [`machine_map`](machine.md#machine_map)

<details><summary>The contract your client receives</summary>

```text
Write `length` bytes from `ref` of `cpu` (`subcpu`) to the new file `dest` (absolute or `~`-led, in a directory that exists, with no comma, semicolon, quote, whitespace, bracket or control character).

Reply: `ref`, `addr`, `length`, `path`, `bytes`, `cpu`. A file not `length` bytes, or whose
first bytes differ from a protocol read, is `status: INVALID`; a refused control read is
`readback_refused`, a broken channel `session_broken`. A range past the program space is
`bad_argument`.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end memdump -->

<!-- scry-reference:begin screen_map_find -->
## `screen_map_find`

Name the screen your program is showing, from its screen map: a file of the program's screens and the named areas of each.

```text
screen_map_find()
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped on the level card the game shows after START, just after the example of `screen_map_write` below added that screen.

Ask:

> Which screen of the map is the game showing?

Call:

```text
screen_map_find()
```

Reply, 5 of 23 fields:

```json
{
  "summary": "screen_map_find: level_card (session), 1 control",
  "matched": true,
  "screen": "level_card",
  "layer": "session",
  "controls": [
    {"name": "level", "rect": [88, 152, 72, 8], "centre": [124, 156]}
  ]
}
```

The game shows `level_card`, one of the screens added this session (`layer` `session`). Its area `level` is the rectangle at 88, 152, with its centre at 124, 156.

<details><summary>The whole reply</summary>

```json
{
  "summary": "screen_map_find: level_card (session), 1 control",
  "status": "ok",
  "matched": true,
  "screen": "level_card",
  "layer": "session",
  "kind": "pixel",
  "size": [256, 240],
  "controls": [
    {"name": "level", "rect": [88, 152, 72, 8], "centre": [124, 156]}
  ],
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#21",
  "pc_before": "0x0000a631",
  "cause": "screen_map_find: one step",
  "stop_seq": 27,
  "pc": "0x0000a633",
  "cpu": ":maincpu",
  "frame": 702,
  "regs": {
    "A": "0x00",
    "B": "0x99",
    "D": "0x0099",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xa633",
    "S": "0x0800",
    "CC": "0x84",
    "DP": "0x00"
  },
  "instruction": {"address": "A633", "bytes": "24FC", "text": "BCC    $A631", "symbol": "wait_frame", "delta": 2},
  "following": ["A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "A640: 7E F0 00 JMP    $F000", "... 6 more"],
  "errorlog": "<volatile>"
}
```

</details>

### Arguments

Takes no argument.

### What comes back

- `matched`: `true` when a screen of the map is the one showing.
- `screen`: The name of the screen that matched.
- `controls`: The matched screen's named areas, each with `name`, `rect` and `centre`, in the program's own units.
- `layer`: Where the screen was found: `session` for a screen added in this session, `file` for one of the loaded map.
- `screens_mapped`: When nothing matched: how many screens the map holds. `screens_tried` says how many had the right kind and size.
- `view_fits`: `false` when the picture's size cannot be the map's, seen through the `scale` and `margin` it was loaded with.

<details><summary>All 27 reply fields</summary>

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
- `controls` (array)
- `evaluated_by` (string)
- `kind` (string)
- `layer` (string)
- `lines_ahead` (integer)
- `matched` (boolean)
- `pc_before` (string)
- `reader_steps` (integer)
- `screen` (string)
- `screens_mapped` (integer)
- `screens_tried` (integer)
- `screens_unjudged` (integer)
- `size` (array)
- `view_fits` (boolean)

</details>

### What it refuses

- No screen mapped yet: load a map or add a screen with `screen_map_write` (`needs_call`).

### Why it works this way

A screen matches when its kind and size are the ones showing and each of its regions has the fingerprint the map recorded. Screens added this session are tried first, then the loaded file's.

The screen is captured once for the whole map, and sizes are compared before any fingerprint: a capture is a round trip through MAME's Lua console.

A screen added with `cells` `index` is compared by palette index, not by colour. Capturing the indices costs MAME more, so it happens only when the map holds such a screen.

### Related tools

- [`screen_map_write`](#screen_map_write)
- [`run_to`](run.md#run_to)
- [`screen_view`](screen.md#screen_view)
- [`screen_signature`](screen.md#screen_signature)

<details><summary>The contract your client receives</summary>

```text
Which mapped screen the machine shows. Reply: `matched`, `kind` and `size`; when matched,
`screen`, `layer`, `controls` (`name`, `rect`, `centre`), in the program's units; when not,
`screens_mapped` and, if the view fits the map, `screens_tried` and `screens_unjudged`
(signed by index on a screen whose pens cannot be read), else `view_fits` false. None mapped:
`needs_call`.

Reference: REFERENCE.md, Screen maps.
```

</details>
<!-- scry-reference:end screen_map_find -->

<!-- scry-reference:begin screen_map_write -->
## `screen_map_write`

Build the screen map, the file that names your program's screens and their areas: add the screen showing, load a file, or save one.

```text
screen_map_write(method, screen="", match=null, controls=null, cells="", anchor="", path="",
    scale=null, margin=null, dest="", overwrite=null)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped on the level card the game shows after START is pressed with a credit in.

Ask:

> Add this screen to the map as level_card, known by its title, with the level number as an area named level.

Call:

```text
screen_map_write(method="add", screen="level_card", match=[[24, 104, 208, 16]],
    controls=[{"name": "level", "rect": [88, 152, 72, 8]}])
```

Reply, 6 of 26 fields:

```json
{
  "summary": "screen_map_write add: level_card (pixel 256x240), 1 region, 1 control",
  "screen": "level_card",
  "size": [256, 240],
  "match": [
    {"crop": [24, 104, 208, 16], "signature": "5733a1938b03c102"}
  ],
  "controls": 1,
  "replaced": false
}
```

The screen is recorded as `level_card`, 256 by 240 pixels, with one named area. Its one region has the fingerprint `5733a1938b03c102` (`signature`), which is what later identifies it.

<details><summary>The whole reply</summary>

```json
{
  "summary": "screen_map_write add: level_card (pixel 256x240), 1 region, 1 control",
  "status": "ok",
  "screen": "level_card",
  "kind": "pixel",
  "size": [256, 240],
  "cells": "rgb",
  "match": [
    {"crop": [24, 104, 208, 16], "signature": "5733a1938b03c102"}
  ],
  "controls": 1,
  "replaced": false,
  "shadows_file": false,
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#20",
  "pc_before": "0x0000a633",
  "cause": "screen_map_write add: one step",
  "stop_seq": 26,
  "pc": "0x0000a631",
  "cpu": ":maincpu",
  "frame": 702,
  "regs": {
    "A": "0x00",
    "B": "0x99",
    "D": "0x0099",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xa631",
    "S": "0x0800",
    "CC": "0x84",
    "DP": "0x00"
  },
  "instruction": {"address": "A631", "bytes": "04B4", "text": "LSR    <$B4", "symbol": "wait_frame", "delta": 0},
  "following": ["A633: 24 FC    BCC    $A631", "A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "... 7 more"],
  "errorlog": "<volatile>",
  "kept": "3 saved for `promote`; maps/gridlee, perform/two-coins, start/gridlee: nothing this session read names its repository: promote(dry_run=true, root=<the repository>) lists what an approval would create"
}
```

</details>

### The three methods

| method | what it does |
|---|---|
| `add` | Records the screen showing now under a name, with the regions that identify it and its named areas. Needs the program stopped. |
| `load` | Reads a map file; nothing is written to disk. Works while the program runs. |
| `save` | Writes the loaded map and the screens added since as one file, which becomes the loaded map. Works while the program runs. |

### Arguments

- `method` (one of `"add"`, `"load"`, `"save"`, required): `add`, `load` or `save`, as above.
- `screen` (string, default `""`): For `add`: the name the screen is recorded under.
- `match` (array of array of integer, optional): For `add`: 1 to 16 rectangles `[x, y, width, height]` that always look the same on this screen. They are what identifies it.
- `controls` (array of object, optional): For `add`: the screen's named areas, each `{"name", "rect"}`. Left out, none.
- `cells` (one of `""`, `"rgb"`, `"index"`, default `""`): For `add`: `index` compares palette indices, not the colours shown, so one map serves a program shown through two palettes. Left out, `rgb`.
- `anchor` (string, default `""`): For `add`: a symbol or an address the program reaches once the screen is fully drawn. `run_to(screen=)` runs to it.
- `path` (string, default `""`): For `load`: the map file, named `<application>-screen-map.json`, as an absolute or `~`-led path.
- `scale` (integer, optional): For `load`: how many times larger this machine shows the program's picture, 1 to 8. Left out, 1.
- `margin` (array of integer, optional): For `load`: `[x, y]`, the border in machine pixels on each side of the program's picture. Left out, none.
- `dest` (string, default `""`): For `save`: the file to write, named `<application>-screen-map.json`, as an absolute or `~`-led path.
- `overwrite` (boolean, optional): For `save`: `true` replaces a file already at `dest`. Left out, an existing file is refused.

### What comes back

- `match`: `add`: each region as recorded, with its `crop` and its `signature`, the fingerprint taken from the screen.
- `replaced`: `add`: `true` when a screen of that name was already added this session. `shadows_file` is `true` when the loaded file has one too.
- `kept`: `add`: reads `N saved for promote` once the map is a candidate that `promote` can write into your repository's `.scry/` folder.
- `screens`: `load` and `save`: how many screens the map holds; `controls` counts their named areas.
- `mode`: `load` and `save`: `verified` when a screen is checked each time it is reached, `consolidated` when it is trusted without a check.
- `promoted`: `save`: the names of the screens added this session that the file now holds.

<details><summary>All 33 reply fields</summary>

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
- `anchor` (string)
- `application` (string)
- `cells` (string)
- `controls` (integer)
- `kind` (string)
- `kept` (string)
- `match` (array)
- `mode` (string)
- `path` (string)
- `pointer` (object)
- `promoted` (array)
- `replaced` (boolean)
- `screen` (string)
- `screens` (integer)
- `shadows_file` (boolean)
- `size` (array)
- `call` (string)
- `evaluated_by` (string)
- `lines_ahead` (integer)
- `pc_before` (string)
- `reader_steps` (integer)

</details>

### What it refuses

- An argument the method does not take.
- A name, rectangle, area or file that is not well formed, or a rectangle outside the screen (`bad_argument`).
- An `add` without `anchor` when the loaded map is `consolidated`, or a `save` of one holding a screen with none (`bad_argument`).
- `cells` `index` on a screen that has no palette (`no_channel`).
- A `save` with nothing mapped (`needs_call`).

### Why it works this way

A screen is recognised by a few regions that never change, not by the whole picture: a cursor or a moving ball would change a fingerprint of the whole screen.

The map has two layers. Screens you `add` live in the session and win over a loaded file's screen of the same name; `save` writes both as one file. A new `start` empties the session layer and keeps the file.

A map's `mode` says who keeps it true. In a `verified` map, `run_to(screen=)` checks the screen's regions on reaching it and refuses a map that no longer matches (`stale_map`). In a `consolidated` map the screen is trusted at its `anchor`, which lets one map serve two versions of a program whose pixels differ.

<details><summary>More on why</summary>

The mode is the file's own: `save` keeps the loaded map's, and writes `verified` when none was loaded. `screen_map_find` checks the regions in either mode.

Rectangles are in the program's pixels. With `scale` and `margin`, this machine's picture is the program's size times the scale, plus the margin on each side. A capture is sampled back to the program's size before it is compared.

A map file is kept in the program's repository, as `.scry/maps/<application>-screen-map.json`, and looks like this.

```json
{"format": "scry-screen-map/1", "application": "circus", "mode": "verified",
 "screens": [{"name": "attract", "kind": "pixel", "size": [248, 256],
              "match": [{"crop": [0, 0, 248, 8], "signature": "<16 hex>"}],
              "controls": [{"name": "high_score", "rect": [40, 112, 184, 8]}]}]}
```

On an arcade board a named area is somewhere to read, never something to click: its inputs go in by port and field. A file may also say where the program keeps a mouse pointer; this server keeps that entry, writes it back on `save` and does nothing else with it.

In the replay test `perform_export` writes, `load` and `add` are replayed as steps and `screen_map_find` becomes a check of what it matched. A `save` is left out, since a replay would find its file there.

</details>

### Related tools

- [`screen_map_find`](#screen_map_find)
- [`run_to`](run.md#run_to)
- [`screen_signature`](screen.md#screen_signature)
- [`screen_view`](screen.md#screen_view)
- [`promote`](project.md#promote)

<details><summary>The contract your client receives</summary>

```text
The screen map: an application's screens, each known by the signatures of its stable regions, and their controls, in a session layer and a file layer.

`add`: the screen shown now as `screen` in the session layer, one capture signing each `match` crop ([x, y, width, height], 1..16), `controls` ([{"name", "rect"}]) naming its places to read; needs the machine stopped. Reply: `screen`, `kind`, `size`, `cells`, `match`, `controls`, `replaced`, `shadows_file`, `anchor` (when given), `kept` (a complete map is kept for `promote`).

`add`'s `cells` `index` (a pixel screen; default
`rgb`) signs the palette indices drawn, not the colours shown, so one map knows a program
shown through two palettes; a screen with no palette refuses it (`no_channel`).

`add`'s `anchor` (a symbol or an address, as `run_to`'s `ref`) is the place after which the screen is whole,
what `run_to(screen=)` runs to: a consolidated map refuses an `add` without one (`bad_argument`),
since it enters its screens by theirs.

`load`: `path` (`<application>-screen-map.json`, absolute or `~`-led) as the file layer, held by the
server; nothing is written to disk. `scale` (1..8) and `margin` [x, y] (machine pixels on
each side) say how the program's picture sits on this machine's screen; maps and `add`'s
crops are in the program's units. Reply: `path`, `application`, `mode`, `screens`, `controls`, `pointer`
(a map that declares the program's pointer).

`save`: both layers as one map to `dest`, refused there without `overwrite`, made the file
layer, in the loaded map's `mode` (`verified` when none was loaded). Reply: `path`,
`application`, `mode`, `screens`, `controls`, `promoted`.

Refused: an argument the method does not take; a misshapen name, crop, control, view or file; an `add` without an `anchor` to a consolidated map, and a save of one holding a screen with none (`bad_argument`); neither a screen nor a `pointer` to save (`needs_call`).

Reference: REFERENCE.md, Screen maps.
```

</details>
<!-- scry-reference:end screen_map_write -->
