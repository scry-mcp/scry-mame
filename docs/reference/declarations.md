# The Declarations tools

Breakpoints, registerpoints and watches are declarations: what the caller meant, kept by the server and armed in the debugger. What they share is in [REFERENCE.md, Declarations](../../REFERENCE.md#declarations); each tool's reasoning follows its block.

<!-- scry-reference:begin breakpoint_at -->
## `breakpoint_at`

*Declare a breakpoint*

```text
breakpoint_at(ref, by="auto", role="stop", condition="", cpu="")
```

Declare an execution breakpoint at `ref`, a place in the code, as a `stop` or a `control`
(never halts; hits counted in a `temp`, 10 at most, read by `run_to`). Stored,
re-armed at `start`.

`ref`: a symbol or linear `0x` address, never an expression. `condition` (a `stop` only):
console grammar, bare numbers hex, no `,`, `;`, braces or assignment. `cpu`: else the
visible one.

Refused: a `seg:off`; a `condition` the console refuses or too long (`command_chars`); an
unknown cpu (`unknown_ref`); an address another declaration holds; one ref under the other
role; a control past the 10 temps.

Reply: `ref`, `stored`, `already_stored`, `armed`, `state`, `temp` (a control), `addr` (once
`ref` resolves), `entry` (once armed).

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `ref` | string | required |
| `by` | one of `"auto"`, `"symbol"`, `"address"` | `"auto"` |
| `role` | one of `"stop"`, `"control"` | `"stop"` |
| `condition` | string | `""` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `addr` | string |
| `already_stored` | boolean |
| `armed` | boolean |
| `by` | string |
| `command_chars` | integer |
| `condition` | string |
| `condition_typed` | string |
| `cpu` | string |
| `entry` | string |
| `limit_chars` | integer |
| `ref` | string |
| `role` | string |
| `state` | string |
| `stored` | boolean |
| `temp` | string |
| `visible_cpu` | string |
| `while_running` | boolean |

Example, from a live run:

```json
{
  "ref": "exception_handler"
}
```

```json
{
  "summary": "breakpoint_at exception_handler: armed at 0x000025a4",
  "status": "ok",
  "ref": "exception_handler",
  "by": "symbol",
  "role": "stop",
  "cpu": ":maincpu",
  "stored": true,
  "while_running": false,
  "addr": "0x000025a4",
  "armed": true,
  "state": "armed",
  "entry": "1 @ 0025A4"
}
```
<!-- scry-reference:end breakpoint_at -->

**A control costs a run nothing**: MAME counts its hits through a conditioned console breakpoint (`bp addr:cpu,(++tempN)==0`) that never halts.

MAME's debugger skips the breakpoints of the instruction a stop lands on when the stop came from outside the instruction stream (end of a frame, a time, a step), and that instruction executes unchecked on release, unless the MAME carries mamedev/mame#16435, which evaluates it. This server counts nothing of its own for such a landing: on a MAME without that patch a control sitting on the instruction a stop lands on misses that landing (a run by frames lands on one every frame, often the first of the vblank handler), so there place a control off the stopped pc.

**A condition turns "run to the vblank until this variable reads X" from a great many round trips into one run.** A name spelled like a register of the row's cpu is refused as ambiguous. The condition is kept as typed for the reason the ref is kept by name: at `start` it re-resolves, so a variable the rebuild moved is compared where it now lives.

**It is evaluated once (`print {<condition>}`) before arming**, because the console arms a condition its evaluator refuses and that row never fires. `print` reads the visible cpu's symbols, so the row's cpu is shown through the stub and the visible one put back, which runs nothing. When the stub refuses the put-back the call refuses before storing and `visible_cpu` names the cpu left visible; `start`'s re-arm has no caller to answer, arms by cpu name and says so in its `rearm` `note`. At `start` a condition the console cannot evaluate is `unresolved` for a name this build lacks and `unarmable` otherwise, kept either way.

A `seg:off` is refused because addresses are linear on MAME's cpus. The condition is evaluated once before arming because the console arms a condition its evaluator refuses and that row never fires (`limit_chars` names the packet limit a too-long one hits). A name absent from this build is stored `unresolved` rather than refused; a row `bplist` does not list after the arm is `readback_refused` with the declaration kept (`armed: false`, `state: gone`); `note` is set when a cpu is ignored; `condition` and `condition_typed` carry the condition as the console reads it and as typed; `cpu` is the cpu it armed on.

<!-- scry-reference:begin regpoint_add -->
## `regpoint_add`

*Declare a registerpoint*

```text
regpoint_add(condition, cpu="")
```

Declare a registerpoint: the machine stops when `condition` comes true, wherever in the
program ("who puts this value in this register"). Stored, re-armed at `start`.

`condition`: console grammar, bare numbers hex (`d1==0x7fff`); compares, never assigns.
`cpu`: only the visible one; another is refused naming `cpu_focus`.

Refused: a condition the console refuses (`bad_argument`) or too long (`command_chars`,
`limit_chars`); one equal to another registerpoint's (`ambiguous_ref`); a debugger with no
registerpoints (`no_channel`).

Reply: `ref` (the condition as typed), `stored`, `already_stored`, `armed`, `state`,
`while_running`, `entry`, `cpu`, `note`.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `condition` | string | required |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `already_stored` | boolean |
| `armed` | boolean |
| `by` | string |
| `command_chars` | integer |
| `condition` | string |
| `cpu` | string or object |
| `entry` | string |
| `index` | integer |
| `limit_chars` | integer |
| `ref` | string |
| `state` | string |
| `stored` | boolean |
| `while_running` | boolean |

Example, from a live run:

```json
{
  "condition": "pc==0xfffffffe"
}
```

```json
{
  "summary": "regpoint_add pc==0xfffffffe: armed, index 1",
  "status": "ok",
  "ref": "pc==0xfffffffe",
  "cpu": ":maincpu",
  "by": "expr",
  "condition": "pc==0xfffffffe",
  "stored": true,
  "while_running": false,
  "armed": true,
  "state": "armed",
  "entry": "1 if pc==0xfffffffe",
  "index": 1
}
```
<!-- scry-reference:end regpoint_add -->

**A registerpoint has no address**, so it is never `stale` or `aliased` and has no `role`.

Adoption is by the exact condition ON THE VISIBLE CPU only: the same text under another cpu compares another register file and is left `foreign`.

**The condition is evaluated before storing**, because the debugger arms a registerpoint its own evaluator refuses and that row never fires.

At `start` each one is re-evaluated: `unresolved` when the console answers `unknown symbol`, else `unarmable` (a console that raised is that declaration's `unarmable` and the pass goes on). It re-arms only when its cpu is then the visible one, since `rpset` names none.

`run_to` and `run_for` answer `OTHER_STOP` for it, since a registerpoint is never a target. `rpset {<condition>}` typed through `debug` does not alter the session; an action after it counts as a write.

A registerpoint is evaluated after every instruction, so it fires again one instruction on while the condition holds; the stop's `cause` is ``registerpoint '<ref>'`` with `regpoint_hit`. A row `rplist` does not list after the `rpset` is `readback_refused` with the declaration kept (`armed: false`, `state: gone`, a `note`). `condition` in the reply is the condition as the console read it, and `index` the debugger's row number. It works on a running machine and marks nothing altered.

<!-- scry-reference:begin watch_add -->
## `watch_add`

*Declare a watch*

```text
watch_add(ref, mode, length=0, fmt="auto", by="auto", cpu="", condition="", trigger="", space="program", trigger_type="w")
```

Declare a watch at `ref`. Stored, re-armed at `start`.

`mode`: `show` (read at each stop), `change` (a write stops the machine), `count` (tallies
writes), `capture` (rows at `trigger`), `expr` (one debugger expression). `ref`: a symbol,
`0x` address or pointer place (`base->field`; stopped machine only). `fmt`: a scalar (`u8`
.. `f64`), an array (`u16[8]`), a string (`char[16]`) or a struct (`{x:i16,y:i16}`).
`length`: total bytes, needed unless `fmt` is sized or the symbol typed; at most
128 for show or capture, 1024 otherwise. `condition`: change only, a
debugger expression over `wpdata`, the value written (`wpdata==0x7f`).
`trigger`, `trigger_type`: capture only; a capture of reads (`r`) takes no `length` or
`fmt`. `space="io"`: a port tap, `count` or `capture` only, for this session only (never
stored).

Refused: a change watch on an unmapped write; a count range splitting a bus word; a ref
declared another way; an unknown pointer base or `cpu`.

Reply: `ref`, `mode`, `stored`, `already_stored`, `armed`, `state`, `reading` (on a stopped
machine), and each mode's own fields.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `ref` | string | required |
| `mode` | one of `"show"`, `"change"`, `"expr"`, `"count"`, `"capture"` | required |
| `length` | integer | `0` |
| `fmt` | string | `"auto"` |
| `by` | one of `"auto"`, `"symbol"`, `"address"`, `"pointer"` | `"auto"` |
| `cpu` | string | `""` |
| `condition` | string | `""` |
| `trigger` | string | `""` |
| `space` | one of `"program"`, `"io"` | `"program"` |
| `trigger_type` | one of `"w"`, `"r"` | `"w"` |

| reply field | type |
|---|---|
| `addr` | string |
| `already_stored` | boolean |
| `armed` | boolean |
| `by` | string |
| `call` | string |
| `condition` | string |
| `condition_typed` | string |
| `cpu` | string |
| `cpus_with_io` | array |
| `entry` | string |
| `fmt` | string |
| `index` | integer |
| `installed` | boolean |
| `length` | integer |
| `lines_ahead` | integer |
| `mine` | boolean |
| `mode` | string |
| `pending` | boolean |
| `pointer` | object |
| `read_maps_to` | string |
| `reading` | object |
| `ref` | string |
| `source` | object |
| `space` | string |
| `state` | string |
| `stored` | boolean |
| `tally_id` | string |
| `trigger` | string |
| `trigger_addr` | string |
| `trigger_maps_to` | string |
| `trigger_type` | string |
| `values_from` | string |
| `visible_cpu` | string |
| `while_running` | boolean |
| `write_maps_to` | string |

Example, from a live run:

```json
{
  "ref": "0x203200",
  "mode": "show",
  "length": 2
}
```

```json
{
  "summary": "watch_add 0x203200: show watch evaluated at 0x00203200, 2 bytes",
  "status": "ok",
  "ref": "0x203200",
  "by": "address",
  "mode": "show",
  "length": 2,
  "fmt": "u16",
  "cpu": ":maincpu",
  "while_running": false,
  "addr": "0x00203200",
  "stored": true,
  "armed": false,
  "state": "evaluated",
  "reading": {"available": true, "value": 0, "raw_hex": "0000"}
}
```
<!-- scry-reference:end watch_add -->

**A watch has two halves, `show` and `change`, and one ref may not be both.** One ref carries one declaration per cpu: another mode, shape, width, format, condition or trigger under it is refused until cleared (an address matched in any spelling; a symbol and its address are two refs). MAME arms no trap byte, and the rule is kept because one that holds only sometimes cannot be relied on.

**Overlap.** A change watch sharing a byte with a range another declaration arms on the same cpu is refused, since two watchpoints on one byte make "who wrote this byte" ambiguous. A count is refused only on an identical range and a capture on an identical block and trigger, since neither stops the machine. A region is `memdump`'s job, hence the size bounds.

**`state` is where the watch is PLACED; `reading` is what THAT call read**: `available: false` with the stub's refusal and never a zero, or `bus` with `last_wrote` for a write-only register. A change watch is `armed` and read at the same stop, which one word could not say.

**Show and expr.** A show or pointer watch is read at every stop on its own cpu through the gdbstub's thread patch; without it another cpu's is unavailable, saying why, and a pointer watch there is refused. An expr is read in ONE `print` beside the frame, so declaring more costs the stop nothing; it has no cpu.

**Change: who wrote this byte.** The write has LANDED when the machine stops, so the stop's `pc` is the instruction AFTER the writer. The stub's stop packet names address 0 for a console row, so attribution comes from the console's line in `debug.log` (`-debuglog`): watchpoint index, value, address, writer pc. `writes` lists every write logged since the previous stop (a 68000 writes a long as two words). `values_from: bus` means `map` says the address does not read back through the handler it is written through (a write-only latch): the values are the logged writes, never a memory read.

**The control of a watch is decided as `run_to`'s is, by naming what silences one.** The debugger ACCEPTS and lists a watchpoint on the ROM copy of a datum whose live copy is in RAM, and it can never fire. So the write side is asked of `map` before arming, and a change watch there is `INVALID`. A count, capture or film is a write TAP that sees every write the cpu makes whether or not anything handles it, so it arms on an unmapped write side with `write_maps_to: "unmapped"` and a `note`.

**Arming.** A watch set while running is taken and FIRES, so it is armed at once. `wplist` is read back after every arm; a row it does not list is `readback_refused` with NOTHING stored, since a watch is stored only once armed. Arming writes nothing, so `altered` stays false.

**A change condition** answers "who writes bits 0-1 of this byte", lost among a register's writes when each stops the machine. `wpdata` is the bus access as it landed, shifted down past the lanes it did not write and cut to those it did. It goes through a breakpoint's steps and is evaluated once, because MAME SETS a watchpoint whose condition it cannot evaluate and that row never fires; `print` answers outside a watchpoint since `wpdata`, `wpaddr` and `wpsize` live in the global symbol table. A watch through a still-null pointer is judged at the widest address its `wp` can spell, since the stop that finds the pointer set has no call left to refuse it in. The `wp` answers the same sentence with or without a condition, so the list is the proof: a row shown without the condition sent is `readback_refused`, and one listed at the range under another is `ambiguous_ref`.

**Count: the datum's twin of a control breakpoint.** A change watch stops at the first write; a census asks which values a register takes over a pass and from which pcs. The tap is composed by the server over the bus words the range touches and bound to its cpu when composed (`tally_id` names any cpu but the first). It sees its cpu's writes only, never a DMA or blitter's on its own bus. The install is SENT to the Lua console and evaluated when it next reads a line, so `watch_add` answers `installed: false`, `pending: true`.

A range that splits a bus word (a word at an odd address on a 16-bit bus, which a V30 writes as two bytes) is refused: a write lands in one bus word, so a word covered in part yields fragments with no `value`.

**The install is proved, not assumed.** A line the console ECHOED AND NEVER EVALUATED is sent again once at the next survey (`install_resent`); a second loss is `install_lost`, because a tally that never installed is a zero that reads as a measurement. Frames never age a line: a reader can stay busy across them, so a line not yet run stays `pending`.

**A tally counts WRITES to its own range only.** A census conditioned on ANOTHER register is a capture: two tallies cannot be joined afterwards, and a site that fires without rewriting the other word inherits its last value.

**Capture: the block as it stood at the one write that matters.** It is the count watch's tap put on the TRIGGER instead of the block, with the same machinery (sent, proved, re-armed at `start`, untouched by `disarm_watches`, errors counted). The tap runs BEFORE the write lands, so the block holds the trigger's value from before it when the trigger lies inside (capturing a counter's long on its low word, each row's low word is one less than `data`). `total` is every trigger access, so `rows + overflow_rows` is the census a count watch on the trigger gives.

The block is read where its values live: the memory share of the one address-map entry holding it whole (a write-only register block has no read side, and where entries overlap the bus answers with the one installed last), else the space's direct read, once `map` answers memory throughout. A block with a handler in it is refused: a direct read of a handler answers zeros that look like data, and a read through it would run it once per trigger. Each row carries a whole block, hence the bounds.

**`time_s` and `line`.** `time_s` is the accessing cpu's local time, so two accesses one cycle apart never share it, hence a double's full precision. `line` is MAME's `vpos()`, which Lua does not bind: time since line 0 plus half a pixel over the line's period, wrapped over the screen's own line count, never a driver's constant. Captures on two cpus share one clock, so order their rows by `time_s`, not by write order (MAME runs one cpu's slice then the next's).

**A capture of READS** (`trigger_type="r"`) keeps the access alone and no block, because a Lua read tap that reads memory in its callback re-enters the bus, which MAME does not survive. It sees no instruction fetch and no ROM read (served through direct access), so one on code or ROM keeps no row; it runs at every read past the row cap, so one on a polled word costs a Lua call per poll. Its `ref` is the trigger, so a write capture of the same word under that ref is refused. Every reader of a block (`gfx_blits`, `gfx_blit_source`, `gfx_draft`, a region write) takes write captures alone.

**A watch on a port** (`space="io"`): a board that drives palette or sound through `out` writes nothing into the program space, so a program-space tap is blind to it. Change, show and expr watches are refused there: a watchpoint and a stop's read are the debugger's, in the program space. An io tap is session-only because the store has no space and a reader would re-arm the port as the program address of the same number. It is cleared by its bare `ref` beside `space`, while its id carries the space (`6_2@io`): port 6 and RAM address 6 are two taps.

**Through a pointer**, because the field a C program writes lives in a heap struct reached through a global pointer. The pointer is read at its declared width (`ptr16{...}`, `ptr32{...}`) or else the stack pointer's, the one register as wide as a pointer on every cpu. On a board relocated by `bases`, a pointer read through a symbol of a relocated class is an offset in that class's segment, placed under its base as `disassemble` places a direct operand; a type names the class when it carries one (`ptr16@CODE`), which a routine's address kept in DATA needs. It is re-resolved at every stop: a change watch moves with it (`moved`), a null pointer is `null_pointer`, never a watch at zero.

`since_last_stop` is set at a STOP only: a `declaration_list(kind="watch")` between two stops consumes nothing, and a total that fell is a `reset`. `values` and `writers` are cumulative since the install; a write that found its table full is counted in `overflow_values` or `overflow_pcs` and never named. A stop's survey row of a capture lists no rows, which would drown every reply.

**A count or capture removal is SENT** and applied when the console next reads a line. It is never resent, because the id is the RANGE and a resend could carry away a tap declared since; a removal the console did not carry out repeats on every reply under `session.tallies_not_removed`. Declaring the range again installs over the old tap and CARRIES ITS COUNTS; over a removal that ran, it counts from nothing.

**The dump files are the range's**: a removed tap's can still be on disk when the range is declared again, so an install that finds no tap of its range deletes them before counting.

`count` tallies every write by value and writer pc and never stops; `capture` keeps one row per access to `trigger`; `expr` takes one debugger expression with no `,`, `;`, assignment, length or `fmt`. `fmt` is a scalar (`u8` .. `f64`), an array (`u16[8]`), a string (`char[16]`) or a struct (`{x:i16,y:i16}`); `auto` is a typed symbol's type, else the widest unsigned scalar `length` divides. `length` is required unless `fmt` is sized or the symbol typed. `condition` (change only) takes `breakpoint_at`'s grammar on the row's cpu, `wpdata` being the value written. `trigger_type` `r` captures reads of `ref` itself (no length, fmt or block). `space="io"` is session-only. A ref is a symbol, a `0x` address or a place through a pointer (`[base]+0x28`, `base->field`), re-resolved each stop; a capture's `ref` is what each row holds. A watch on a running machine is taken and fires; only a pointer place needs a stop. `already_stored` is a no-op re-declaration; `pointer` and `reading` appear when the ref goes through a pointer or the machine is stopped; `addr` once the ref resolves; `fmt` and `length` echo the place. Reply fields beyond these (`tally_id`, `installed`, `pending`, `values_from`, `trigger_addr` and the rest) are each mode's own.

<!-- scry-reference:begin declaration_list -->
## `declaration_list`

*List the declarations*

```text
declaration_list(kind="", cpu="")
```

List the declarations of `kind` (empty: every kind) with their state, against the
debugger's own list read back. `cpu` narrows the rows to it. Answers on a running machine.

Reply: `breakpoints`, `regpoints`, `watches` (each kind asked; each row `ref`, `by`,
`cpu`, `created_at`, `origin`, `inherited`, `age_s`, `state`, plus its kind's fields),
`foreign` (debugger rows no declaration placed), `cpu`.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `kind` | one of `""`, `"breakpoint"`, `"regpoint"`, `"watch"` | `""` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `breakpoints` | array |
| `cpu` | string or object |
| `foreign` | object |
| `regpoints` | array |
| `watches` | array |

Example, from a live run:

```json
{
  "kind": "breakpoint"
}
```

```json
{
  "summary": "declaration_list breakpoint: 1 breakpoint (1 armed)",
  "status": "ok",
  "breakpoints": [
    {
      "ref": "exception_handler",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": 0,
      "role": "stop",
      "addr": "0x000025a4",
      "state": "armed",
      "entry": "1 @ 0025A4"
    }
  ],
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"}
}
```
<!-- scry-reference:end declaration_list -->

<!-- scry-reference:begin declaration_clear -->
## `declaration_clear`

*Clear declarations*

```text
declaration_clear(kind, ref="", cpu="", all=false, space="program")
```

Clear the declarations of `kind` that `ref` names (as its declaring reply gave it), or
every one with `all=True` and no `ref`, on `cpu` or every cpu. Disarms what this server
armed; a foreign row is never deleted. `space="io"` clears a watch's io tap. Works on a
running machine.

Refused: an empty `ref` without `all`; a `ref` matching none (`unknown_ref`, naming the
refs held); `space` for a kind other than `watch`.

Reply: `declarations_cleared`, `disarmed`, `while_running`, `tallies_removed` (removing an io
tap), `note`.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `kind` | one of `"breakpoint"`, `"regpoint"`, `"watch"` | required |
| `ref` | string | `""` |
| `cpu` | string | `""` |
| `all` | boolean | `false` |
| `space` | one of `"program"`, `"io"` | `"program"` |

| reply field | type |
|---|---|
| `declarations_cleared` | integer |
| `disarmed` | array |
| `tallies_removed` | array |
| `while_running` | boolean |

Example, from a live run:

```json
{
  "kind": "breakpoint",
  "all": true
}
```

```json
{
  "summary": "declaration_clear breakpoint all: 1 cleared, 1 disarmed",
  "status": "ok",
  "declarations_cleared": 1,
  "disarmed": ["1 @ 0025A4"],
  "while_running": false
}
```
<!-- scry-reference:end declaration_clear -->
