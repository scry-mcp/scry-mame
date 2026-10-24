# The Declarations tools

Breakpoints, registerpoints and watches are declarations: what the caller meant, kept by the server and armed in the debugger. What they share is in [REFERENCE.md, Declarations](../../REFERENCE.md#declarations); each tool's reasoning follows its block.

<!-- scry-reference:begin breakpoint_at -->
## `breakpoint_at`

*Declare a breakpoint*

```text
breakpoint_at(ref, by="auto", role="stop", condition="", cpu="")
```

Declare an execution breakpoint at `ref`, a PLACE in the code, and arm it on a cpu, as a
`stop` or a `control` (never halts: MAME counts its hits in one of its 10 `temp`
variables, read by `run_to`). STORED and re-armed at the next `start`; armed until
`breakpoint_clear` or `close`.

Arguments: `ref`, a symbol or a LINEAR `0x` address (`0x4a0`; a `seg:off` is refused). `by`:
`auto`, `symbol` or `address` only: an expression is never a place here (`expr` and `pointer`
are refused; a halt when one holds is `regpoint_add`'s). `role`: `stop` or `control`.
`condition` (a `stop` only): halt only when it holds, in the console's
grammar, bare numbers hex (`w@DemoLen==0x25`; no `,`, `;`, braces or assignment), kept as
typed and evaluated once before arming, on the row's cpu (a build without the thread patch
refuses one on another cpu). `cpu` (`subcpu`): its cpu, else the visible one, which never
moves; one ref on two cpus is two declarations.

Refused: a `condition` the console's evaluator refuses or one too long for a packet
(`command_chars`, `limit_chars`); a cpu the machine lacks (`unknown_ref` with `cpu_tags`); a
second declaration at an address another holds on its cpu; one ref under the other role; a
control past the 10 temps; a row already there it cannot adopt. A refusal stores nothing. A
name absent from THIS build (not bare hex) is stored `unresolved`. Works on a RUNNING machine
too (`while_running`).

Reply: `ref` (the string that clears it), `by`, `role`, `stored`, `already_stored`, `condition`
(as the console reads it) and `condition_typed` when that differs, `armed`, `state` (`armed`,
`disabled`, `unresolved` with a `note`), `while_running`, a control's `temp`, and once it
resolves `addr`, `entry` (the debugger's row), its `cpu`, and a `note` when that cpu is
ignored. A row `bplist` does not list after the arm is `readback_refused` with the
declaration KEPT (`armed: false`, `state: gone`).

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
| `note` | string |
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
  "already_stored": false,
  "while_running": false,
  "addr": "0x000025a4",
  "armed": true,
  "state": "armed",
  "entry": "1 @ 0025A4"
}
```
<!-- scry-reference:end breakpoint_at -->

**A control costs a run nothing**: MAME counts its hits through a conditioned console breakpoint (`bp addr:cpu,(++tempN)==0`) that never halts.

MAME's debugger skips the breakpoints of the instruction a stop lands on when the stop came from outside the instruction stream (end of a frame, a time, a step), and that instruction executes unchecked on release. A run by frames lands on such an instruction every frame, often the first of the vblank handler, so `run_for(frames=N)` counts each landing it releases for a control sitting there. Any other such release still misses it, so place a control off the stopped pc.

**A condition turns "run to the vblank until this variable reads X" from a great many round trips into one run.** A name spelled like a register of the row's cpu is refused as ambiguous. The condition is kept as typed for the reason the ref is kept by name: at `start` it re-resolves, so a variable the rebuild moved is compared where it now lives.

**It is evaluated once (`print {<condition>}`) before arming**, because the console arms a condition its evaluator refuses and that row never fires. `print` reads the visible cpu's symbols, so the row's cpu is shown through the stub and the visible one put back, which runs nothing. When the stub refuses the put-back the call refuses before storing and `visible_cpu` names the cpu left visible; `start`'s re-arm has no caller to answer, arms by cpu name and says so in its `rearm` `note`. At `start` a condition the console cannot evaluate is `unresolved` for a name this build lacks and `unarmable` otherwise, kept either way.

<!-- scry-reference:begin breakpoint_list -->
## `breakpoint_list`

*List the breakpoint declarations*

```text
breakpoint_list(cpu="")
```

Every breakpoint declaration and its state, against the debugger's own `bplist` read back.
Reply: `breakpoints`, each with `ref`, `by`, `cpu`, `role`, `created_at`, `origin`, `inherited`
(true for a declaration the store brought back at `start`, false for one made this session),
`age_s` (whole seconds since `created_at`, unavailable with no date), `condition` and
`condition_typed`
as `breakpoint_at` replies them, `addr`, `hits_since_armed` for an armed control (its count
since it was armed), `state` (`armed` or `disabled` with its `entry` and `cpu`, `gone` for one
that owns no row, `stale` for a raw address declared over another build, `aliased` with `why`
for a declaration from before the one-row rule whose address another declaration owns,
`unresolved` for a symbol this build lacks, in the ref or in the CONDITION: the latter keeps its
`addr`, since the ref resolved, as the registerpoint family lists its own), and `foreign`:
breakpoints the debugger holds that no declaration placed (one typed through `debug`, or a
`run_to`'s while it runs). Answers on a running machine too, with `last_stop`. `cpu` (`subcpu`;
left out, every cpu) narrows both to that cpu's rows (`bplist <cpu>`); the reply's `cpu` names
it, unavailable when none was.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `breakpoints` | array |
| `cpu` | string or object |
| `foreign` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "breakpoint_list: 1 declared, 1 armed",
  "status": "ok",
  "breakpoints": [
    {
      "ref": "exception_handler",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "2026-10-24T16:07:07+00:00",
      "origin": "2026-10-24T16:07:07+00:00#32680.1",
      "inherited": false,
      "age_s": 0,
      "role": "stop",
      "addr": "0x000025a4",
      "state": "armed",
      "entry": "1 @ 0025A4"
    }
  ],
  "foreign": [],
  "cpu": {
    "available": false,
    "why": "no cpu was named, so the rows are every cpu's"
  }
}
```
<!-- scry-reference:end breakpoint_list -->

<!-- scry-reference:begin breakpoint_clear -->
## `breakpoint_clear`

*Clear breakpoint declarations*

```text
breakpoint_clear(ref="", cpu="", all=false)
```

Clear breakpoint declarations: those named by the `ref` their `breakpoint_at` reply
carried, or every one with `all=True` and no `ref`, on every cpu or, with `cpu`, on that one
alone,
disarming what this server armed for each and reading the debugger's list back. A foreign
breakpoint is never deleted. Works on a running machine too. `all=True` takes every
breakpoint declaration of the store `start` named (`declarations.path`): without a
`state_dir`, other sessions' rows too, listed `inherited` with their `age_s`. An empty `ref`
is refused.

Reply: `declarations_cleared`, `disarmed` (the debugger's rows that went), `while_running`.
A row the debugger still lists after its removal was sent keeps its record, as a
watch's does, so `disarmed` does not name it and `note` says which row is still held
and names the `bpclear` that removes it; a stop there is then named by its address.
Matching: a `0x` address in any spelling (`0x00ff` is `0xff`), and a symbol in any case. A `ref` that matches no breakpoint declaration is
`status: INVALID`, naming the refs held; `all=True` on an empty store is `ok` with 0.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `ref` | string | `""` |
| `cpu` | string | `""` |
| `all` | boolean | `false` |

| reply field | type |
|---|---|
| `declarations_cleared` | integer |
| `disarmed` | array |
| `note` | string |
| `while_running` | boolean |

Example, from a live run:

```json
{
  "all": true
}
```

```json
{
  "summary": "breakpoint_clear all: 1 cleared, 1 disarmed",
  "status": "ok",
  "declarations_cleared": 1,
  "disarmed": [
    "1 @ 0025A4"
  ],
  "while_running": false
}
```
<!-- scry-reference:end breakpoint_clear -->

<!-- scry-reference:begin regpoint_add -->
## `regpoint_add`

*Declare a registerpoint*

```text
regpoint_add(condition, cpu="")
```

Declare a REGISTERPOINT and arm it: the machine stops when `condition` comes true,
WHEREVER in the program that happens (MAME's own `rpset`, evaluated after every
instruction). It is for "who puts this value in this register", which needs no address.
STORED like a breakpoint, with the condition as typed, and re-armed at the next `start`.

Arguments: `condition`, in the console's grammar that `breakpoint_at` and `run_to` take (bare
numbers hex: `d1==0x7fff`, `a0==GameState && d0!=0`), a symbol replaced by its address; it
compares, never assigns, and carries no action. `cpu`: MAME's `rpset` takes none and arms on the
visible cpu, so another is refused naming `focus`.

Refused, storing and arming nothing: a condition the console's evaluator refuses, a register
this cpu lacks included (`bad_argument` in the console's words); one too long for a packet
(`command_chars`, `limit_chars`); one reading the same as another registerpoint's once its
symbols are addresses (`ambiguous_ref` naming it); a debugger with no registerpoints
(`no_channel`). The same condition again is adopted, never a second row. Works on a RUNNING
machine too: the console takes it and it fires (`while_running`). It marks nothing altered.

Reply: `ref` (the condition as typed, the string that clears it), `by` (`expr`), `condition`
(as the console read it), `stored`, `already_stored`, `while_running`, `armed`, `state`
(`armed`, or `disabled`), `entry` (the debugger's row), `index` and `cpu` (the visible cpu it
is armed on), with a `note` when the debugger ignores that cpu. A row `rplist` does not list
after the `rpset` is `readback_refused` with the declaration KEPT (`armed: false`, `state:
gone`, a `note`). When it fires, the stop's `cause` is ``registerpoint '<ref>'`` (with
the stop's `regpoint_hit`), and it fires again one instruction on while the condition holds.

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
| `note` | string |
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
  "already_stored": false,
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

<!-- scry-reference:begin regpoint_list -->
## `regpoint_list`

*List the registerpoint declarations*

```text
regpoint_list(cpu="")
```

Every registerpoint declaration and its state, against the debugger's own `rplist` read
back. Reply: `regpoints`, each with `ref`, `by`, `cpu`, `created_at`, `origin`, `inherited`
(true for a declaration the store brought back at `start`, false for one made this
session), `age_s` (whole seconds since `created_at`, unavailable with no date), `condition` (as
the console reads it now), `state` (`armed` or `disabled` with its `entry`, `index` and
`cpu`; `gone` for one the debugger no longer lists; `unresolved` for one whose symbol this
start's build lacks, or with `why` when a symbol now collides with a name the console
knows), and `foreign`: registerpoints the debugger holds that no declaration placed (one
typed through `debug`). It has no `addr`, `role`, `stale` or `aliased`: those belong to an
address, and a registerpoint has none. Answers on a running machine too, with
`last_stop`. `cpu` (left out, every cpu) narrows both to its rows and is named in `cpu`, as
`breakpoint_list`'s does.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `cpu` | string or object |
| `foreign` | array |
| `regpoints` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "regpoint_list: 1 declared, 1 armed",
  "status": "ok",
  "regpoints": [
    {
      "ref": "pc==0xfffffffe",
      "by": "expr",
      "cpu": ":maincpu",
      "created_at": "2026-10-24T16:07:07+00:00",
      "origin": "2026-10-24T16:07:07+00:00#32680.1",
      "inherited": false,
      "age_s": 0,
      "condition": "pc==0xfffffffe",
      "state": "armed",
      "entry": "1 if pc==0xfffffffe",
      "index": 1
    }
  ],
  "foreign": [],
  "cpu": {
    "available": false,
    "why": "no cpu was named, so the rows are every cpu's"
  }
}
```
<!-- scry-reference:end regpoint_list -->

<!-- scry-reference:begin regpoint_clear -->
## `regpoint_clear`

*Clear registerpoint declarations*

```text
regpoint_clear(ref="", cpu="", all=false)
```

Clear registerpoint declarations: those named by the `ref` their `regpoint_add` reply
carried, or every one with `all=True` and no `ref`, on every cpu or on `cpu` alone,
disarming what this server armed or adopted for it and reading the debugger's list back. A
foreign registerpoint is never deleted. Works on a running machine too. `all=True` takes every
registerpoint declaration of the store `start` named, as `breakpoint_clear`'s; an empty
`ref` is refused.

Reply: `declarations_cleared`, `disarmed` (the debugger's rows that went), `while_running`.
A row the debugger still lists after its removal was sent keeps its record, as a
breakpoint's does, so `disarmed` does not name it and `note` names the `rpclear` that
removes it. Matching: an expression as typed but for its numbers, each read as the console reads it: bare, `0x` and `$` numbers are hex, `#` decimal, `0o` octal and `0b` binary (`d1==7fff`, `d1==0x7fff`, `d1==$7fff` and `d1==#32767` match). A `ref` that matches no registerpoint declaration
is `status: INVALID`, naming the refs held; `all=True` on an empty store is `ok` with 0.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `ref` | string | `""` |
| `cpu` | string | `""` |
| `all` | boolean | `false` |

| reply field | type |
|---|---|
| `declarations_cleared` | integer |
| `disarmed` | array |
| `note` | string |
| `while_running` | boolean |

Example, from a live run:

```json
{
  "all": true
}
```

```json
{
  "summary": "regpoint_clear all: 1 cleared, 1 disarmed",
  "status": "ok",
  "declarations_cleared": 1,
  "disarmed": [
    "1 if pc==0xfffffffe"
  ],
  "while_running": false
}
```
<!-- scry-reference:end regpoint_clear -->

<!-- scry-reference:begin watch_add -->
## `watch_add`

*Declare a watch*

```text
watch_add(ref, mode, length=0, fmt="auto", by="auto", cpu="", condition="", trigger="", space="program", trigger_type="w")
```

Declare a WATCH at `ref`, in its cpu's byte order. STORED, re-armed at the next `start`.

Arguments:
- `mode`: `show` (read at each stop, arms nothing), `change` (a WRITE watchpoint: a write
stops the machine, and `watch_hit` says WHO WROTE THIS BYTE), `count` (tallies
every write by value and writer pc, never stopping), `capture` (one
row per access to `trigger`, never stops) or `expr`
(`ref` is ONE reading debugger expression, `beamy`: no `,`, `;`, assignment, length or
fmt).
- `ref`: a symbol, a `0x` address, or a place through a POINTER (`[base]+0x28`,
`base->field`), re-resolved each stop; a capture's `ref` is what each row HOLDS.
- `fmt`: a scalar (`u8` .. `f64`), an array (`u16[8]`), a string
(`char[16]`) or a struct (`{x:i16,y:i16}`). `auto`: a typed symbol's type, else the WIDEST
unsigned scalar `length` divides.
- `length`: TOTAL bytes, REQUIRED unless `fmt` is sized or the symbol is typed; at most
128 for a show or capture watch, 1024 otherwise.
- `by`: `auto` unless forced.
- `cpu`: its cpu, else the visible one.
- `condition` (change only): stop only on a write it holds for (`breakpoint_at`'s grammar
on the row's cpu; `wpdata` is the value written).
- `trigger`, `trigger_type` (capture only): the symbol or `0x` address whose WRITES (`w`)
or READS (`r`: of `ref` itself; no length, fmt or block) make rows.
- `space`: `io` when `ref` (count) or `trigger` (capture) is a `0x` PORT; session-only.

Refused: a change watch on an unmapped write; a count range splitting a bus word;
a ref declared again another way; a range another declaration arms; what the console
cannot evaluate; an unknown pointer base or `cpu`.
Works on a RUNNING machine, not through a POINTER (`not_stopped`).

Reply: `ref`, `by`, `mode`, `stored`, `already_stored`, `armed`, `state`, `while_running`; at a
place `length`, `fmt`, `addr` once resolved, `pointer` through one, `reading` when stopped; and
each mode's own fields (REFERENCE.md, Declarations; rows: `watch_list`).

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
| `note` | string |
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
  "already_stored": false,
  "armed": false,
  "state": "evaluated",
  "reading": {
    "available": true,
    "value": 0,
    "raw_hex": "0000"
  }
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

<!-- scry-reference:begin watch_list -->
## `watch_list`

*List the watch declarations*

```text
watch_list(cpu="")
```

Every watch declaration and its state, and each io tap (`space: "io"`, `stored: false`).
Reply: `watches`, each with `ref`, `by`, `cpu`, `created_at`, `origin`, `inherited` (true if the
store brought it back; an io tap has neither), `age_s` (whole seconds since `created_at`,
unavailable with no date), `mode`, `length`, `fmt`, `addr`, `state`, where it is PLACED (a show
or expr watch: `evaluated`, or `unresolved`, `null_pointer`; stopped, a show watch adds
`reading`, `available` with `value` and `raw_hex`, or unavailable with `why`; a change watch:
`armed` or `disabled` with its `entry`, `cpu` and `values_from`, `gone`, `stale` for a raw
address declared over another build, `unresolved` (the ref, or a name in its `condition`); a
count watch: `tallied` with its whole value and writer tables (`total`, `since_last_stop`,
`frame_as_of`, `superseded`, `across`), `no_dump_yet`, `install_failed` (its `why`),
`install_lost` (`install_resent`) or `not_installed`; a capture: `captured` with `rows_kept`,
`overflow_rows`, `first_rows` (each with `frame`, `line` and `time_s`) and `rows_path` (every
row), or those same states; both: `callback_errors`, `count` and `first`, the times the tap's
body raised, which a census beside a non-zero count is short of), and `foreign`: watchpoints the
debugger holds that this server never armed. The debugger's own `wplist` is read back, on a
running machine too, where the reply adds `last_stop`. `cpu` (`subcpu`; left out, every cpu)
narrows both to that cpu's watches (`wplist <cpu>`), named in `cpu` (unavailable when none was).
The `session` block carries a row (in its `tallies_not_removed`) for a count watch whose removal
was NOT carried out by the console (`state` `refused`, the console's words in its `why`, or
`lost`): the tap is still in the guest and this server no longer holds its record. It is NEVER
resent, and each row repeats on every call until the session ends; its `why` says what declaring
the range again does.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `cpu` | string or object |
| `foreign` | array |
| `watches` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "watch_list: 1 declared, 0 armed",
  "status": "ok",
  "watches": [
    {
      "ref": "0x203200",
      "by": "address",
      "cpu": ":maincpu",
      "created_at": "2026-10-24T16:07:07+00:00",
      "origin": "2026-10-24T16:07:07+00:00#32680.1",
      "inherited": false,
      "age_s": 0,
      "mode": "show",
      "length": 2,
      "fmt": "u16",
      "addr": "0x00203200",
      "state": "evaluated",
      "reading": {
        "available": true,
        "value": 0,
        "raw_hex": "0000"
      }
    }
  ],
  "foreign": [],
  "cpu": {
    "available": false,
    "why": "no cpu was named, so the rows are every cpu's"
  }
}
```
<!-- scry-reference:end watch_list -->

`since_last_stop` is set at a STOP only: a `watch_list` between two stops consumes nothing, and a total that fell is a `reset`. `values` and `writers` are cumulative since the install; a write that found its table full is counted in `overflow_values` or `overflow_pcs` and never named. A stop's survey row of a capture lists no rows, which would drown every reply.

<!-- scry-reference:begin watch_clear -->
## `watch_clear`

*Clear watch declarations*

```text
watch_clear(ref="", cpu="", all=false, space="program")
```

Clear watch declarations: those named by the `ref` their `watch_add` reply carried, with
its `space` (`io` for an io tap's), or every one with `all=True` and no `ref` or `space`, on
every cpu or on `cpu` alone. Disarms from the debugger what THIS server armed (a show watch
armed nothing) and reads the list back; a foreign watchpoint is never deleted. Works on a
running machine too. `all=True` takes every watch declaration of the store `start` named, as
`breakpoint_clear`'s, and every io tap; an empty `ref` is refused.

Reply: `declarations_cleared`, `disarmed` (the debugger's rows that went), `while_running`,
and `tallies_removed` when a count or capture watch went (its removal is SENT to the console
and applied when the console next reads a line; the record and its files go at once). A row the
debugger still lists after its removal was sent keeps its record, as a breakpoint's does,
so `disarmed` does not name it and `note` says which row is still held.
Matching: a `0x` address in any spelling (`0x00ff` is `0xff`), a symbol in any case, a pointer's base as either of those, an expression as typed but for its numbers, each read as the console reads it: bare, `0x` and `$` numbers are hex, `#` decimal, `0o` octal and `0b` binary (`d1==7fff`, `d1==0x7fff`, `d1==$7fff` and `d1==#32767` match), and with `space="io"`, an io tap's port as an address or its block as a symbol, in those spellings. A `ref` that matches no watch declaration is `status: INVALID`,
naming the refs held; `all=True` on an empty store is `ok` with 0.

Reference: REFERENCE.md, Declarations.

| argument | type | default |
|---|---|---|
| `ref` | string | `""` |
| `cpu` | string | `""` |
| `all` | boolean | `false` |
| `space` | one of `"program"`, `"io"` | `"program"` |

| reply field | type |
|---|---|
| `declarations_cleared` | integer |
| `disarmed` | array |
| `note` | string |
| `tallies_removed` | array |
| `while_running` | boolean |

Example, from a live run:

```json
{
  "all": true
}
```

```json
{
  "summary": "watch_clear all: 1 cleared, 0 disarmed",
  "status": "ok",
  "declarations_cleared": 1,
  "disarmed": [],
  "while_running": false
}
```
<!-- scry-reference:end watch_clear -->

**A count or capture removal is SENT** and applied when the console next reads a line. It is never resent, because the id is the RANGE and a resend could carry away a tap declared since; a removal the console did not carry out repeats on every reply under `session.tallies_not_removed`. Declaring the range again installs over the old tap and CARRIES ITS COUNTS; over a removal that ran, it counts from nothing.

**The dump files are the range's**: a removed tap's can still be on disk when the range is declared again, so an install that finds no tap of its range deletes them before counting.
