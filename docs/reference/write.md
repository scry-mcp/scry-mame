# The Write tools

These tools change the machine instead of reading it: bytes in memory, a register, a soft reset, and `debug`, which sends any line to MAME's debugger console. All four need the machine stopped.

Every write marks the session. From then on the `session` block of every reply carries `altered`: this session has written to the machine, so a later measurement is of a changed program.

<!-- scry-reference:begin write -->
## `write`

Write bytes into memory at an address or a symbol, and see what the memory holds afterwards.

```text
write(ref, data_hex, cpu="", region=false)
```

### Try it

On Gridlee, a free ROM from mamedev.org, at any stop, with the example session's symbols loaded: `credits` names the first of the two bytes the game keeps its credits in.

Ask:

> Give me nine credits: write 9 into both bytes the game keeps its credits in.

Call:

```text
write(ref="credits", data_hex="0909")
```

Reply, 5 of 8 fields:

```json
{
  "summary": "write credits: 2 bytes, verified True",
  "addr": "0x0000042b",
  "bytes_written": 2,
  "readback": "0909",
  "verified": true
}
```

Both bytes from `0x42b` now hold 9. `readback` is what the memory holds after the write, and `verified` says it is what was sent.

<details><summary>The whole reply</summary>

```json
{
  "summary": "write credits: 2 bytes, verified True",
  "status": "ok",
  "ref": "credits",
  "addr": "0x0000042b",
  "bytes_written": 2,
  "readback": "0909",
  "verified": true,
  "cpu": ":maincpu"
}
```

</details>

### Arguments

- `ref` (string, required): Where the bytes go: a `0x` address or a symbol.
- `data_hex` (string, required): The bytes to write, as hex digits, two per byte: 1 to 1024 bytes.
- `cpu` (string, default `""`): The cpu whose memory is written. Left empty, the one the debugger is showing.
- `region` (boolean, default `false`): `true` patches ROM, in the memory region that holds the address. Left out, a write to ROM changes nothing and the reply says why.

### What comes back

- `readback`: The bytes at the address after the write, as hex, read through the same cpu.
- `verified`: `true` when `readback` is what was sent.
- `bytes_written`: How many bytes were sent, whether or not they landed.
- `target`: `rom`, when a write without `region` did not land because the address is ROM. `note` then says where its bytes live.
- `region`: The memory region that holds the address, with `region_offset` the offset in it: where a `region` write went, or where a ROM address keeps its bytes.
- `captures_reading_it`: With `region`: each capture watch that reads the block the write changed, by `ref`, `cpu` and, for a port, `space`.

<details><summary>All 10 reply fields</summary>

- `addr` (string)
- `bytes_written` (integer)
- `captures_reading_it` (array)
- `cpu` (string or object)
- `readback` (string)
- `ref` (string)
- `region` (string)
- `region_offset` (string)
- `target` (string)
- `verified` (boolean)

</details>

### What it refuses

- A machine that is running (`not_stopped`).
- `data_hex` that is not whole hex bytes, is empty, or holds more than 1024 (`bad_argument`).
- A range that runs past the cpu's program memory (`bad_argument`).
- `region=true` where no memory region holds the address, or where the bytes run past its end (`bad_argument`).
- A `cpu` other than the first, on a MAME build whose debugger connection serves one cpu only (`bad_argument`).
- A failed read after the write, with the session still usable (`readback_refused`) or not (`session_broken`).

### Why it works this way

The reply says what the memory holds after the write, never what was sent. A write to ROM is taken and changes nothing, and `readback` is where that shows. `verified: false` on RAM means the write went nowhere; on a hardware register it can be the register answering something else, which is its job.

ROM is patched only with `region`, so it never happens by accident. As the cpu sees it ROM has no write side: its bytes live in a memory region, and `region=true` changes them there without running an instruction.

The write marks the session: the `session` block of every later reply carries `altered`, which says this session has written to the machine.

<details><summary>More on why</summary>

A capture watch, `watch_add(mode="capture")`, records a block of memory each time its trigger address is accessed. A `region` write changes that block with no write on the bus, so the watch would show the change with nothing saying why; the reply names each watch it reaches.

With `region`, `data_hex` is still in the order the cpu reads the bytes, whatever order the region keeps them in. The write lands whole or not at all: when the console cannot copy the whole span out and back, it is refused and nothing is loaded.

</details>

### Related tools

- [`read_memory`](read.md#read_memory)
- [`set_register`](#set_register)
- [`machine_map`](machine.md#machine_map)
- [`watch_add`](breakpoints.md#watch_add)
- [`memdump`](read.md#memdump)
- [`debug`](#debug)

<details><summary>The contract your client receives</summary>

```text
Write bytes to memory at `ref` of `cpu` and read them back through it; needs the machine
stopped.

`data_hex` is 1..1024 bytes. `region=True` patches ROM in the memory region backing
the address (refused where none does, or past its end); without it a ROM write goes
nowhere and says why. A range past the program space is `bad_argument`.

Reply: `ref`, `addr`, `bytes_written`, `readback`, `verified`, `cpu`; with `region` also
`region`, `region_offset`, `captures_reading_it`; on ROM `target`, `note`. A failed
re-read is `readback_refused` or `session_broken`.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end write -->

<!-- scry-reference:begin set_register -->
## `set_register`

Force a register to a value you choose, and see what the cpu holds afterwards.

```text
set_register(name, value, cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, at any stop.

Ask:

> Force register A to 0x42.

Call:

```text
set_register(name="A", value="0x42")
```

Reply, 6 of 7 fields:

```json
{
  "summary": "set_register A = 0x42, verified True",
  "register": "A",
  "value": "0x42",
  "readback": "0x42",
  "verified": true,
  "cpu": ":maincpu"
}
```

Register A of `:maincpu` now holds `0x42`. `readback` is what the register held after the write, and `verified` says it equals what was asked.

<details><summary>The whole reply</summary>

```json
{
  "summary": "set_register A = 0x42, verified True",
  "status": "ok",
  "register": "A",
  "value": "0x42",
  "readback": "0x42",
  "verified": true,
  "cpu": ":maincpu"
}
```

</details>

### Arguments

- `name` (string, required): The register, by a name `registers` lists (`D0`, `PC`). A 16-bit register served under an `E` name takes its short one: `AX` for `EAX` on a V30.
- `value` (integer or string, required): The value to set: an integer or a `0x` string, not negative and no wider than the register.
- `cpu` (string, default `""`): The cpu whose register is set. Left empty, the one the debugger is showing.

### What comes back

- `register`: The register as the debugger names it, which can differ from the name given (`EAX` for `AX`).
- `value`: What was asked, as `0x` text at the register's width.
- `readback`: What the register holds after the write, in the same spelling.
- `verified`: `true` when `readback` equals `value`.

<details><summary>All 5 reply fields</summary>

- `cpu` (string)
- `readback` (string)
- `register` (string)
- `value` (string)
- `verified` (boolean)

</details>

### What it refuses

- A machine that is running (`not_stopped`).
- A name the cpu does not have; the message lists the ones it has (`bad_argument`).
- A negative value, or one wider than the register (`bad_argument`).
- A bool, or a value of either spelling wider than 64 bits, the widest number MAME's debugger holds (`bad_argument`).
- A `cpu` other than the first, on a MAME build whose debugger connection serves one cpu only (`bad_argument`).
- A cpu whose registers the debugger connection does not describe (`no_channel`).

### Why it works this way

The value is read back because a register can refuse part of it. `verified: false` is not always a failure: a register that masks the value, or answers something else, is doing its job.

The write marks the session: the `session` block of every later reply carries `altered`, which says this session has written to the machine.

### Related tools

- [`registers`](read.md#registers)
- [`write`](#write)
- [`cpu_info`](machine.md#cpu_info)
- [`step`](run.md#step)

<details><summary>The contract your client receives</summary>

```text
Force register `name` of `cpu` to `value` and read it back. Modifies the machine; needs it
stopped.

Refuses an unknown name (listing the cpu's) and a value wider than the register.

Reply: `register`, `value`, `readback`, `verified`, `cpu`. A cpu the stub does not
describe is `no_channel`.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end set_register -->

<!-- scry-reference:begin reset -->
## `reset`

Soft-reset the machine without restarting MAME, and stop where its boot begins.

```text
reset()
```

### Try it

On Gridlee, a free ROM from mamedev.org, at any stop. The example session resets at frame 630, with a game under way.

Ask:

> Reset the game without restarting MAME.

Call:

```text
reset()
```

Reply, 6 of 16 fields:

```json
{
  "summary": "reset: softreset applied at frame 630, pc 0x0000f000 verified True",
  "kind": "softreset",
  "pc": "0x0000f000",
  "boot_pc": "0x0000f000",
  "verified": true,
  "frame_at_reset": 630
}
```

The machine is back at `0xf000`, the address `start` first stopped it at, so `verified` is true. The frame counter did not restart: `frame_at_reset` is 630.

<details><summary>The whole reply</summary>

```json
{
  "summary": "reset: softreset applied at frame 630, pc 0x0000f000 verified True",
  "status": "ok",
  "kind": "softreset",
  "pc": "0x0000f000",
  "boot_pc": "0x0000f000",
  "verified": true,
  "frame_at_reset": 630,
  "taps_across": [
    {"ref": "film", "cpu": ":maincpu"}
  ],
  "cause": "softreset",
  "stop_seq": 61,
  "cpu": ":maincpu",
  "frame": 630,
  "regs": {
    "A": "0x42",
    "B": "0xd8",
    "D": "0x42d8",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xf000",
    "S": "0x07f4",
    "CC": "0xd0",
    "DP": "0x00"
  },
  "instruction": {"address": "F000", "bytes": "1A50", "text": "ORCC   #$50", "symbol": "take_credit", "delta": 6538},
  "following": ["F002: 4F          CLRA", "F003: 1F 8B       TFR    A,DP", "F005: 10 CE 08 00 LDS    #$0800", "F009: BD D1 21    JSR    $D121", "F00C: B6 95 02    LDA    $9502", "F00F: 97 BC       STA    <$BC", "... 6 more"],
  "errorlog": "<volatile>"
}
```

</details>

### Arguments

Takes no argument.

### What comes back

- `kind`: Always `softreset`: the only reset this tool makes.
- `pc`: Where the machine is after the reset.
- `boot_pc`: Where `start` left the machine at boot. Unavailable when `start` read no address then.
- `verified`: `true` when `pc` and `boot_pc` agree: the machine is back where it boots.
- `frame_at_reset`: The frame counter at the reset. It does not restart, so subtract this before comparing a frame with a fresh start's.
- `taps_across`: Each count or capture that was running across the reset, by `ref`, `cpu` and, for a port, `space`. Its totals carry on.

<details><summary>All 16 reply fields</summary>

- `boot_pc` (string or object)
- `cpu` (string)
- `following` (array of string)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer)
- `frame_at_reset` (integer)
- `kind` (string)
- `pc` (string)
- `regpoint_hit` (object)
- `regs` (object)
- `stop_seq` (integer)
- `taps_across` (array)
- `verified` (boolean)
- `watch_hit` (object)
- `watches` (array)

</details>

### What it refuses

- A machine that is running (`not_stopped`).

### Why it works this way

The reset is a stop of its own: MAME applies it only when the machine next runs, so the call steps one instruction. That stop is recorded with the readings every stop returns, described on the [Run](run.md) page.

There is no hard reset: it re-creates the machine and ends the debugger connection, which is `close` then `start`. It would save only MAME's launch, none of the emulated time to the screen that matters.

A reset is a write: the `session` block of every later reply carries `altered`, which says this session has written to the machine.

<details><summary>More on why</summary>

A count or capture watch counts on across a reset, because its tables live outside the machine. For a fresh count, `declaration_clear(kind="watch")` and add the watch again.

</details>

### Related tools

- [`start`](session.md#start)
- [`close`](session.md#close)
- [`run_to`](run.md#run_to)
- [`state_write`](states.md#state_write)
- [`declaration_clear`](breakpoints.md#declaration_clear)

<details><summary>The contract your client receives</summary>

```text
Soft reset, applied, without relaunching. Modifies the machine; needs it stopped. A hard
reset is `close` then `start`.

Reply: `kind`, `pc`, `boot_pc`, `verified` (the two agree), `frame_at_reset`, `taps_across` (a
tap was live), and the stop's survey (`cause`, `stop_seq`, `cpu`, `regs`, `frame`,
`instruction`, `following`, `errorlog`, `watches`, `watch_hit`, `regpoint_hit`). The frame
counter does not restart: subtract `frame_at_reset` before comparing with a cold boot.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end reset -->

<!-- scry-reference:begin debug -->
## `debug`

Send one line to MAME's debugger console and read what it printed, for what no other tool does.

```text
debug(command)
```

### Try it

On Gridlee, a free ROM from mamedev.org, at any stop.

Ask:

> Ask MAME's debugger what handles address 0x9380.

Call:

```text
debug(command="map 9380")
```

Reply, 4 of 6 fields:

```json
{
  "summary": "debug 'map 9380'",
  "command": "map 9380",
  "mutates": false,
  "output": "   Read: 9380 logical program == 9380 physical program -> un ... (224 characters)"
}
```

`output` holds what the console's `map` command printed, shown here cut short: the whole reply below has it all. `mutates` is false: the line changed nothing.

<details><summary>The whole reply</summary>

```json
{
  "summary": "debug 'map 9380'",
  "status": "ok",
  "command": "map 9380",
  "mutates": false,
  "output": "   Read: 9380 logical program == 9380 physical program -> unmapped\n  Write: 9380 logical program == 9380 physical program -> watchdog_timer_device::reset_w\n  Fetch: 9380 logical program == 9380 physical program -> unmapped\n\n",
  "clipped": false
}
```

</details>

### Arguments

- `command` (string, required): One line for the debugger console, as you would type it there. Several commands go on one line, with `;` between them.

### What comes back

- `output`: What the console printed. Past 4000 characters it is cut: `clipped` is `true` and `output_path` names a file with all `output_chars` of it.
- `mutates`: `true` when the line can change the machine: it then counts as a write.
- `note`: What the line did beyond printing: it let the machine run, completed a held save or load, or moved a counter.
- `visible_cpu`: After a line that changes which cpus the debugger shows or skips: the cpu it shows now. `ignored` lists the ones it skips.
- `refused`: On a refusal: each command the console refused, with its `index` in the line, the `command` and the console's `error`. `not_run` lists the commands that never ran.

<details><summary>All 13 reply fields</summary>

- `clipped` (boolean)
- `command` (string)
- `command_chars` (integer)
- `ignored` (array or object)
- `limit_chars` (integer)
- `mutates` (boolean)
- `not_run` (array)
- `output` (string)
- `output_chars` (integer)
- `output_path` (string)
- `refused` (array)
- `refused_total` (integer)
- `visible_cpu` (string or object)

</details>

### What it refuses

- A machine that is running (`not_stopped`).
- A line holding `hardreset`, before anything is sent: `close` then `start` is that reset (`bad_argument`).
- A line the console answers with an error of its own, such as an unknown command or a bad expression (`bad_argument`).
- A line too long for one packet of the debugger connection, before it is sent; `command_chars` and `limit_chars` say by how much (`bad_argument`).
- A `statesave` or `stateload` MAME still holds after one instruction (`not_settled`).

### Why it works this way

A line that can change the machine counts as a write, whether it fills memory, loads a file, resets, runs or assigns a value. It marks the session: the `session` block of every later reply carries `altered`, which says this session has written to the machine.

A line that lets the machine run (`g` and its family, `step N`, `over`, `next`) leaves the session running until `stop`, and tools that read the machine refuse until then.

The console has no exit code, so its error answers are read. Otherwise a refused line would come back `ok`, and a `perform`, which runs several calls as one, would go on to its next step.

<details><summary>More on why</summary>

Each command is classified from MAME's own command table, on the cautious side. The cases that are not obvious:

- `suspend` and `resume` count when they name a cpu, and so does `source`, which runs a file of console commands.
- A bare `suspend`, `resume`, `ignore` or `observe` only lists.
- An action given to `bp`, `ep`, `rp`, `wp`, `trace` or `traceover` counts: it is a command list run at every hit.
- `//` and `/*` are the console's `comadd` and `commit`. A comment's text is never evaluated, and a `comadd` typed here is not saved or listed by the comment tools.
- A comparison is never an assignment: `print {d1==7fff}` is a read. An assignment is looked for outside quoted strings only.
- An assignment to a debugger temporary variable is not a write, but `temp0=w@100=1` is: the chain reaches memory.
- A line of several commands is split at each `;` outside brackets and quotes, and each command is classified alone.

A line that assigns the temporary variable of a `control`, an address counted beside a run's target, names that control in `note`. The write moves the `hits_since_armed` that `declaration_list(kind="breakpoint")` reports, not a run's `control_hits`. Writing -1 makes the control stop the machine at its next hit.

MAME drops a packet longer than its debugger connection takes, without answering, and the wait that followed would blame the wrong thing. The same limit covers every tool that sends a console command: a long `condition`, a `find` pattern, a `memdump` path.

A parse error, such as `unknown command` or `unbalanced quotes`, stops the line there: the commands after it never ran, and a `g` behind it leaves the machine stopped. An error printed while a command ran, such as `Error in expression` or `Error opening file`, leaves the rest running.

A command refused while it ran still counts as a write, because the console evaluates parameters in order: `print d0=5,zzz` writes D0 before it refuses `zzz`. An error the answer cannot pin on one command names the whole line. Only the error shapes the console is known to print are matched, each at the start of a line.

A bare comparison typed as a command, `print d1==1234`, is an assignment expression to the console's parser and is refused; in braces it answers.

A `statesave` or `stateload` typed here is completed as [`state_write`](states.md#state_write) completes its own when MAME holds it, and `note` says so. MAME keeps one held save or load at a time, so a line that held several completes only the last.

</details>

### Related tools

- [`registers`](read.md#registers)
- [`read_memory`](read.md#read_memory)
- [`find`](read.md#find)
- [`lua`](lua.md#lua)
- [`state_write`](states.md#state_write)
- [`stop`](run.md#stop)

<details><summary>The contract your client receives</summary>

```text
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
```

</details>
<!-- scry-reference:end debug -->
