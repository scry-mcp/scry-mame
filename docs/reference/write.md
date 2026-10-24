# The Write tools

<!-- scry-reference:begin write -->
## `write`

*Write memory*

```text
write(ref, data_hex, cpu="", region=false)
```

Write bytes to memory at `ref` of `cpu` (`subcpu`; the visible one when empty) and READ THEM
BACK through the same cpu. Each cpu is served by its own thread of the gdbstub's thread patch (`status`'s `threads`); a build without it serves its first cpu alone, whatever is visible, and refuses another (`bad_argument`). A range whose last byte lies past that cpu's program space (the address mask `start` read) is `bad_argument` naming the mask; with no mask known the range is the console's. MODIFIES the machine: every later
reply says so.
`data_hex` holds 1..1024 bytes, `read_memory`'s ceiling: a larger image is loaded from a
file (`debug("load ...")`).

`region=True` patches ROM live: the bytes go into the memory REGION that backs the address on
that cpu's map (the console's `saver` and `loadr`, in the region's own byte order, a partial
word widened to whole words), then are read back through the cpu. Refused where no region
backs the address or its offset cannot be placed, and past the entry's or the region's end.
Never taken on its own: without it a ROM write goes nowhere and says why.

Reply: `addr`, `bytes_written` (sent), `readback`, `verified` (readback equals what was sent),
`cpu`, and with `region` the `region`, `region_offset` and any `captures_reading_it`.
`verified: false` is not always a failure: a hardware register that answers something else is
doing its job; for RAM the write went nowhere; on ROM the reply adds `target: "rom"`, a `note`,
and the `region` backing it when the address map can say which. A watched range that cannot be
re-read afterwards carries the fields above so the landed write is not lost; a read BACK that
fails carries `addr` and `bytes_written` only. Either is `readback_refused` when the stub
refused, else `session_broken`. Needs the machine STOPPED (else `not_stopped`).

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
| `note` | string |
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

**`region=True` goes through the console with no guest step**: `saver` copies the span to a file in the scratch, the bytes are patched into it, and `loadr` loads it back raw (a Lua region write would cost a step on a stopped machine). The patch is made in the cpu's byte order and swapped to the region's. Neither command's word is taken for the span: `saver` says it succeeded even when it clamped at the region's end, and `loadr` loads no more than its file holds, so a short or missing file is refused and nothing is loaded. A capture reading the block that region backs would show the table change with nothing saying why, so `captures_reading_it` names each one the write reached.

A failed re-read of the watches the write touched, or of the readback, is `readback_refused` when the stub ANSWERED (the channel kept its place) and `session_broken` otherwise.

<!-- scry-reference:begin set_register -->
## `set_register`

*Force a register*

```text
set_register(name, value, cpu="")
```

Force the register `name` of `cpu` (`subcpu`; the visible one when empty) to `value`
(an integer or a `0x` string) and READ IT BACK. Each cpu is served by its own thread of the gdbstub's thread patch (`status`'s `threads`); a build without it serves its first cpu alone, whatever is visible, and refuses another (`bad_argument`). MODIFIES the machine.
Refuses a name this cpu does not have, naming the ones it has (a 16-bit register also answers
to its short name: `AX` for the `EAX` a V30 is served under; the reply
carries the stub's name), and a value wider than the
register, naming its width.

Reply: `register`, `value` (what was sent), `readback` (the register read again; both hex at its
width), `verified` (readback equals what was sent; false is not always a failure: a register
that masks or answers something else is doing its job), `cpu` (the one forced). A cpu the stub
does not describe, or whose byte order is not established, is `no_channel`. Needs the machine STOPPED (else `not_stopped`).

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

<!-- scry-reference:begin reset -->
## `reset`

*Reset the machine*

```text
reset()
```

SOFT reset of the machine, applied, without relaunching the process. MODIFIES the machine.

Reply: `kind` (`softreset`), `pc` read back after the reset, `boot_pc` (where `start` parked),
`verified` (the two agree), `frame_at_reset`, `taps_across` (every count or capture watch
whose totals now span the reset, which each survey then says in `across`), and
the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine): the step that applies
the reset is a stop of its own, surveyed and recorded like `step`'s, so the next call
finds nothing to attribute to the machine alone. The console's reset is a timer that
fires when the machine next runs, so this steps once to apply it. THE FRAME COUNTER
DOES NOT RESTART, so a frame number after a
reset is NOT a cold boot's: subtract `frame_at_reset`, the counter read once the reset
was applied, before comparing a later stop's `frame` with one taken from a cold boot.
There is no hard reset: it re-creates the machine and the gdbstub connection dies with it,
which is `close` followed by `start`, and it would save only the process launch, none of
the emulated time to the screen that matters. Needs the machine STOPPED (else `not_stopped`).

Reference: REFERENCE.md, Reading and writing.

Takes no argument.

| reply field | type |
|---|---|
| `boot_pc` | string or object |
| `cpu` | string |
| `dasm` | array |
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
    {
      "ref": "ramdac:ramdac",
      "cpu": ":maincpu"
    },
    {
      "ref": "film",
      "cpu": ":maincpu"
    }
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
  "dasm": [
    "0F2034: 46FC 2700                move    #$2700, SR",
    "0F2038: 33FC 0000 0020 351C      move.w  #$0, $20351c.l",
    "0F2040: 4EB8 25DC                jsr     $25dc.w",
    "0F2044: 33FC D800 0020 351C      move.w  #$d800, $20351c.l",
    "0F204C: 4EB9 000F 24DE           jsr     $f24de.l",
    "0F2052: 23FC 000F 4414 0020 2EA4 move.l  #$f4414, $202ea4.l"
  ],
  "errorlog": {
    "lines_total": 1,
    "truncated": false,
    "lines": [
      "Soft reset"
    ],
    "mark": 66664
  }
}
```
<!-- scry-reference:end reset -->

**A count or capture watch counts on across a reset or a `stateload`**, because its tables are the host's and survive the machine being replaced; nothing is zeroed behind the caller's back, and `watch_clear` then declaring it again is a fresh count.

<!-- scry-reference:begin debug -->
## `debug`

*Debugger console command*

```text
debug(command)
```

Run ANY MAME debugger command, `command` (its only argument), and return its text.
The read-only recipes have typed tools: prefer them, above all for a command whose answer can
run past the console's text buffer (`find` or `dump` over a wide range), which takes MAME down.

Reply: `command`, `mutates`, `output`, `clipped`, and a `note` when there is
something to say; above 4000 characters the text goes to a file (`output_chars`,
`output_path`, a bounded preview). Every `;` command of a line is judged, each word resolved as
the console resolves it (the command or the one it prefixes). One that changes the machine
(`fill`, `load`, `stateload`/`sl`, a reset, `rewind`, `mount`, `do`, any run or console step, an
assignment such as `d0=1234`) counts as a write and `altered` says so, on the cautious side; a
comparison, quoted text or a debugger temp alone (`temp9=0`) does not; `source` and an ACTION
count, by the parameter each command takes it in, braced or bare (a `bp`, `wp`, `rp`, `ep` or
`trace` line); a bare `suspend`, `resume`, `ignore` or `observe` only lists; a `hardreset` is
refused unsent (`close` then `start`). A run the console owns (the `g` family, `step N`, `over`,
`next`) marks the session RUNNING: no stop packet comes for it, so the readers refuse until the
frame counter proves the stop, and `stop` brings it back. A `focus`, `ignore` or `observe`
naming a cpu adds `visible_cpu` and `ignored`, read back. A command too long for one packet is
`bad_argument` (`command_chars`, `limit_chars`), never sent. The console's own error answer
(`Error in expression`, `unknown command`, `Unable to find device` and its other printed
refusals) is INVALID (`bad_argument`) quoting its line, with `output` whole, `refused` (by
`index`, with its `error`) and `not_run` (what a parse error left unexecuted); a `perform` stops
there.
Needs the machine STOPPED (else `not_stopped`).

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
| `note` | string |
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

**What counts as a write.** Beyond the description's list, each word is classified off MAME's own command table on the cautious side; `suspend` and `resume` naming a cpu count, as do `source` (a file of console commands) and an ACTION, found by the parameter each command takes it in: the third of a `bp` or `ep`, the second of an `rp`, the fifth of a `wp`, the fourth of a `trace`/`traceover`.

- `//` and `/*` are the comment pane's `comadd` and `commit`; a comment's text is never evaluated, and a `comadd` typed here is neither stored nor listed.
- A comparison is never an assignment (`print {d1==7fff}` is a read), and an assignment is looked for outside quoted strings only.
- An assignment to a debugger temp is not a write, while `temp0=w@100=1` still is, because the chain reaches memory. A line that assigns a control's temp names the control in `note`: it moves `breakpoint_list`'s cumulative `hits_since_armed` and not a run's `control_hits`, and -1 makes the control halt at its next hit.
- A line of several commands is split at a `;` outside brackets and quotes, and each is judged alone.

**Packet size.** A command whose packet would pass the size the stub advertised is refused before it is sent, because the stub drops such a packet unanswered and the wait would blame the wrong thing. It covers every console command, so a long `condition`, `find` pattern or `memdump` path is refused the same way.

**The console has no exit code, so its own error answers are read.** An `ok` over a refused line would let a `perform` go on to the next step. So the shapes the console was captured printing make the reply INVALID `bad_argument`, matched anchored at a line's start (a shape not captured is not matched): `Error in expression`, `Invalid breakpoint number`, `Invalid registerpoint number`, `Invalid watchpoint type`, `Error opening file`, and the parse errors `unknown command`, `ambiguous command`, `unbalanced parentheses`, `unbalanced quotes`, `not enough parameters for command`, `too many parameters for command`, `error in assignment expression`.

The two families differ in what ran. A parse error stops the line there, so the commands after it never ran and are left out of its writes, release and cpu setters (a `g` behind a refused command leaves the machine stopped). An error printed while a command ran leaves the rest running, and the command stays counted as a write, because the console evaluates parameters in order and `print d0=5,zzz` writes D0 before it refuses `zzz`. An error the answer cannot pin on one command names the whole line. A bare comparison typed as a command (`print d1==1234`) is an assignment expression to the console's parser and is refused; braced it answers.
