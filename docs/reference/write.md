# The Write tools

<!-- scry-reference:begin write -->
## `write`

*Write memory*

```text
write(ref, data_hex, cpu="", region=false)
```

Write bytes to memory at `ref` of `cpu` and read them back through it; needs the machine
stopped.

`data_hex` is 1..1024 bytes. `region=True` patches ROM in the memory region backing
the address (refused where none does, or past its end); without it a ROM write goes
nowhere and says why. A range past the program space is `bad_argument`.

Reply: `addr`, `bytes_written`, `readback`, `verified`, `cpu`; with `region` also
`region`, `region_offset`, `captures_reading_it`; on ROM `target`, `note`. A failed
re-read is `readback_refused` or `session_broken`.

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `ref` | string | required |
| `data_hex` | string | required |
| `cpu` | string | `""` |
| `region` | boolean | `false` |

| reply field | type |
|---|---|
| `addr` | string |
| `bytes_written` | integer |
| `captures_reading_it` | array |
| `cpu` | string or object |
| `readback` | string |
| `region` | string |
| `region_offset` | integer |
| `target` | string |
| `verified` | boolean |

Example, from a live run:

```json
{
  "ref": "0x200000",
  "data_hex": "00"
}
```

```json
{
  "summary": "write 0x200000: 1 byte, verified True",
  "status": "ok",
  "addr": "0x00200000",
  "bytes_written": 1,
  "readback": "00",
  "verified": true,
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end write -->

**`region=True` goes through the console with no guest step**: `saver` copies the span to a file in the scratch, the bytes are patched into it, and `loadr` loads it back raw (a Lua region write would cost a step on a stopped machine). The patch is made in the cpu's byte order and swapped to the region's. Neither command's word is taken for the span: `saver` says it succeeded even when it clamped at the region's end, and `loadr` loads no more than its file holds, so a short or missing file is refused and nothing is loaded.

A failed re-read of the watches the write touched, or of the readback, is `readback_refused` when the stub ANSWERED (the channel kept its place) and `session_broken` otherwise.

**Why a ROM write needs `region`.** Without it the write would silently go nowhere, so the flag makes patching ROM a deliberate act.

**Why `verified: false` is not always a failure.** A hardware register may answer something else, which is the register doing its job; for RAM it means the write went nowhere.

**Why `captures_reading_it` exists.** A capture reading the block a region write changed would show the table change with nothing saying why, so the reply names each capture reached.

**Why a cpu argument needs the thread patch.** Each cpu is served by its own gdbstub thread; a build without the patch serves its first cpu only and refuses another with `bad_argument`.

**Why a range is bounded by the program space.** A last byte past the cpu's address mask (the one `start` read) is refused naming the mask; with no mask known the range is the console's.

<!-- scry-reference:begin set_register -->
## `set_register`

*Force a register*

```text
set_register(name, value, cpu="")
```

Force register `name` of `cpu` to `value` and read it back. Modifies the machine; needs it
stopped.

Refuses an unknown name (listing the cpu's) and a value wider than the register.

Reply: `register`, `value`, `readback`, `verified`, `cpu`. A cpu the stub does not
describe is `no_channel`.

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `name` | string | required |
| `value` | integer or string | required |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `cpu` | string |
| `readback` | string |
| `register` | string |
| `value` | string |
| `verified` | boolean |

Example, from a live run:

```json
{
  "name": "D0",
  "value": 0
}
```

```json
{
  "summary": "set_register D0 = 0x00000000, verified True",
  "status": "ok",
  "register": "D0",
  "value": "0x00000000",
  "readback": "0x00000000",
  "verified": true,
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end set_register -->

**Why `verified: false` is not always a failure.** A register that masks or answers something else is doing its job.

**Why a short name works.** A V30 is served under `EAX`, so `AX` is accepted and the reply carries the stub's name.

**Why `cpu` follows the thread patch.** Each cpu is served by its own gdbstub thread; a build without the patch serves its first cpu only and refuses another with `bad_argument`.

<!-- scry-reference:begin reset -->
## `reset`

*Reset the machine*

```text
reset()
```

Soft reset, applied, without relaunching. Modifies the machine; needs it stopped. A hard
reset is `close` then `start`.

Reply: `kind`, `pc`, `boot_pc`, `verified` (the two agree), `frame_at_reset`, `taps_across` (a
tap was live), and the stop's survey (`cause`, `stop_seq`, `cpu`, `regs`, `frame`,
`instruction`, `following`, `errorlog`, `watches`, `watch_hit`, `regpoint_hit`). The frame
counter does not restart: subtract `frame_at_reset` before comparing with a cold boot.

Reference: REFERENCE.md, Reading and writing.

Takes no argument.

| reply field | type |
|---|---|
| `boot_pc` | string or object |
| `cpu` | string |
| `following` | array of string |
| `instruction` | StopInstruction |
| `errorlog` | object |
| `frame` | integer |
| `frame_at_reset` | integer |
| `kind` | string |
| `pc` | string |
| `regpoint_hit` | object |
| `regs` | object |
| `stop_seq` | integer |
| `taps_across` | array |
| `verified` | boolean |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "reset: softreset applied at frame 30, pc 0x000f2034 verified True",
  "status": "ok",
  "kind": "softreset",
  "pc": "0x000f2034",
  "boot_pc": "0x000f2034",
  "verified": true,
  "frame_at_reset": 30,
  "taps_across": [
    {"ref": "ramdac:ramdac", "cpu": ":maincpu"},
    {"ref": "film", "cpu": ":maincpu"}
  ],
  "cause": "softreset",
  "stop_seq": 27,
  "cpu": ":maincpu",
  "frame": 30,
  "regs": {
    "D0": "0x00010000",
    "D1": "0x00000032",
    "D2": "0x000001dc",
    "D3": "0x00000020",
    "D4": "0x0000000f",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x000001dc",
    "A1": "0x0020829c",
    "A2": "0x00203208",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00200fd8",
    "SP": "0x00201000",
    "PS": "0x2704",
    "PC": "0x000f2034"
  },
  "instruction": {
    "address": "0F2034",
    "bytes": "46FC2700",
    "text": "move    #$2700, SR",
    "symbol": "RESET",
    "delta": 0
  },
  "following": ["0F2038: 33FC 0000 0020 351C      move.w  #$0, $20351c.l", "0F2040: 4EB8 25DC                jsr     $25dc.w", "0F2044: 33FC D800 0020 351C      move.w  #$d800, $20351c.l", "0F204C: 4EB9 000F 24DE           jsr     $f24de.l", "0F2052: 23FC 000F 4414 0020 2EA4 move.l  #$f4414, $202ea4.l"],
  "errorlog": {"lines_total": 1, "truncated": false, "lines": ["Soft reset"], "mark": 66664}
}
```
<!-- scry-reference:end reset -->

**A count or capture watch counts on across a reset or a `stateload`**, because its tables are the host's and survive the machine being replaced; nothing is zeroed behind the caller's back, and `declaration_clear(kind="watch")` then declaring it again is a fresh count.

**Why the reset is a stop of its own.** The console's reset is a timer that fires when the machine next runs, so the call steps once to apply it; that step is surveyed and recorded like `step`'s, leaving nothing to attribute to the machine alone afterwards.

**Why there is no hard reset.** It re-creates the machine and the gdbstub connection dies with it, which is `close` then `start`; it would save only the process launch, none of the emulated time to the screen that matters.

<!-- scry-reference:begin debug -->
## `debug`

*Debugger console command*

```text
debug(command)
```

Run any MAME debugger command, `command`. Prefer the typed readers: a wide `find` takes
MAME down. Needs the machine stopped.

A line that changes the machine (`fill`, `load`, `stateload`, a reset, a run or step, an
assignment) is a write. `hardreset` is refused unsent. The `g` family, `step N`, `over`
and `next` mark the session RUNNING until `stop`. A too long packet, or the console's own
error answer, is `bad_argument`.

Reply: `command`, `mutates`, `output`, `clipped`, `note`; past 4000 characters the
text goes to a file (`output_chars`, `output_path`); `visible_cpu`, `ignored` (a line that
sets cpus); on refusal `command_chars`, `limit_chars`, `refused`, `refused_total`, `not_run`.

Reference: REFERENCE.md, The console.

| argument | type | default |
|---|---|---|
| `command` | string | required |

| reply field | type |
|---|---|
| `clipped` | boolean |
| `command` | string |
| `command_chars` | integer |
| `ignored` | array or object |
| `limit_chars` | integer |
| `mutates` | boolean |
| `not_run` | array |
| `output` | string |
| `output_chars` | integer |
| `output_path` | string |
| `refused` | array |
| `refused_total` | integer |
| `visible_cpu` | string or object |

Example, from a live run:

```json
{
  "command": "print pc"
}
```

```json
{
  "summary": "debug 'print pc'",
  "status": "ok",
  "command": "print pc",
  "mutates": false,
  "output": "F203A\n\n",
  "clipped": false
}
```
<!-- scry-reference:end debug -->

**What counts as a write.** Beyond the words named above, each word is classified off MAME's own command table on the cautious side; `suspend` and `resume` naming a cpu count, as do `source` (a file of console commands) and an ACTION, found by the parameter each command takes it in: the third of a `bp` or `ep`, the second of an `rp`, the fifth of a `wp`, the fourth of a `trace`/`traceover`. A bare `suspend`, `resume`, `ignore` or `observe` only lists.

- `//` and `/*` are the comment pane's `comadd` and `commit`; a comment's text is never evaluated, and a `comadd` typed here is neither stored nor listed.
- A comparison is never an assignment (`print {d1==7fff}` is a read), and an assignment is looked for outside quoted strings only.
- An assignment to a debugger temp is not a write, while `temp0=w@100=1` still is, because the chain reaches memory. A line that assigns a control's temp names the control in `note`: it moves `declaration_list(kind="breakpoint")`'s cumulative `hits_since_armed` and not a run's `control_hits`, and -1 makes the control halt at its next hit.
- A line of several commands is split at a `;` outside brackets and quotes, and each is judged alone.

**Packet size.** A command whose packet would pass the size the stub advertised is refused before it is sent, because the stub drops such a packet unanswered and the wait would blame the wrong thing. It covers every console command, so a long `condition`, `find` pattern or `memdump` path is refused the same way.

**The console has no exit code, so its own error answers are read.** An `ok` over a refused line would let a `perform` go on to the next step. So the shapes the console was captured printing make the reply INVALID `bad_argument`, matched anchored at a line's start (a shape not captured is not matched): `Error in expression`, `Invalid breakpoint number`, `Invalid registerpoint number`, `Invalid watchpoint type`, `Error opening file`, and the parse errors `unknown command`, `ambiguous command`, `unbalanced parentheses`, `unbalanced quotes`, `not enough parameters for command`, `too many parameters for command`, `error in assignment expression`.

The two families differ in what ran. A parse error stops the line there, so the commands after it never ran (`not_run`) and are left out of its writes, release and cpu setters (a `g` behind a refused command leaves the machine stopped). An error printed while a command ran leaves the rest running, and the command stays counted as a write, because the console evaluates parameters in order and `print d0=5,zzz` writes D0 before it refuses `zzz`. An error the answer cannot pin on one command names the whole line. A bare comparison typed as a command (`print d1==1234`) is an assignment expression to the console's parser and is refused; braced it answers.
