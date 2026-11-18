# The Run tools

These tools let the program run and stop it again: to an address, for a number of frames, one instruction at a time, or with no deadline. Most other tools read the machine only while it is stopped, and [REFERENCE.md](../../REFERENCE.md#running-and-stopping) says which ones answer while it runs.

MAME cannot run one cpu alone. Every run and every step goes through the cpu the debugger is showing, called the visible cpu on this page. Every other cpu runs its share of the same emulated time meanwhile.

## What every stop returns

A reply that ends at a stop carries the same readings whatever the call was about, because a stop is where the next question starts.

- `cause`: what stopped the machine, by name: the target, a breakpoint, a watch, the end of the frames asked for.
- `stop_seq`: the number of this stop in the session. The stop `start` leaves is 1, and `status` counts the same way.
- `cpu`, `pc`, `regs`, `frame`: the cpu that stopped, its program counter, its registers and the frame counter.
- `instruction`: the instruction at `pc`, as `address`, `bytes` and `text`, with `symbol` and `delta` when a symbol is near. `following` holds the next lines of the listing.
- `errorlog`: what MAME's error log gained since the last stop, as `lines`, `lines_total`, `truncated`, `mark` and `how`. The field is not named `log`.
- `watches`: every watch and what it saw. `watch_hit` or `regpoint_hit` describes the one that stopped the machine.

`cause` also names a breakpoint, a watch or a registerpoint typed through `debug`, with the `bpclear`, `wpclear` or `rpclear` command that removes it. It writes that row's number as `0x` hex, because MAME's console reads a bare `D0` or `A` as a register.

A breakpoint names a stop only on its own cpu, since two cpus run two programs. A registerpoint, MAME's stop on a register condition, fires at every instruction while its condition holds, so `regpoint_hit` carries a `note` that it is still armed. A control, the often-run address `run_to` counts, never counts as a stop.

<!-- scry-reference:begin run_to -->
## `run_to`

Run until the program reaches an address, or a screen of the screen map, and stop there.

```text
run_to(ref="", control="", screen="", seconds=30.0, disarm_watches=false, condition="", cpu="")
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, started with the names in [gridlee-symbols.yaml](tour/gridlee-symbols.yaml) and stopped right after a coin is dropped.

Ask:

> Run until the game counts the coin I dropped, and check that its frame-wait loop keeps running meanwhile.

Call:

```text
run_to(ref="count_coin", control="wait_frame", seconds=300)
```

Reply, 5 of 14 fields:

```json
{
  "summary": "run_to count_coin: TARGET, control counted 1",
  "verdict": "TARGET",
  "control_hits": 1,
  "controls": [
    {"ref": "wait_frame", "cpu": ":maincpu", "hits_in_run": 1}
  ],
  "pc": "0x0000b583"
}
```

The run reached `count_coin`, which is what `TARGET` says. The control `wait_frame` ran once on the way, so breakpoints were firing.

<details><summary>The whole reply</summary>

```json
{
  "summary": "run_to count_coin: TARGET, control counted 1",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 1,
  "controls": [
    {"ref": "wait_frame", "cpu": ":maincpu", "hits_in_run": 1}
  ],
  "cause": "target count_coin",
  "stop_seq": 18,
  "pc": "0x0000b583",
  "cpu": ":maincpu",
  "frame": 552,
  "regs": {
    "A": "0x01",
    "B": "0xcf",
    "D": "0x01cf",
    "X": "0xe199",
    "Y": "0xf2e6",
    "U": "0x7acf",
    "PC": "0xb583",
    "S": "0x07fc",
    "CC": "0xa4",
    "DP": "0x00"
  },
  "instruction": {
    "address": "B583",
    "bytes": "7C042B",
    "text": "INC    $042B",
    "symbol": "count_coin",
    "delta": 0,
    "comment": "a coin: INC credits, then the BCD copy"
  },
  "following": ["B586: 86 01    LDA    #$01", "B588: BB 04 2C ADDA   $042C", "B58B: 19       DAA", "B58C: B7 04 2C STA    $042C", "B58F: 39       RTS", "B590: 96 F4    LDA    <$F4", "... 8 more"],
  "errorlog": "<volatile>"
}
```

</details>

### Arguments

- `ref` (string, default `""`): The address to stop at: a `0x` address or a symbol. Give this or `screen`, never both.
- `control` (string, default `""`): An address known to run often, counted beside the target, so that "the target never ran" can be told from "nothing ran". Required with `ref` or an anchored `screen`.
- `screen` (string, default `""`): A screen of the loaded screen map, the file naming a program's screens. With an `anchor`, an address the map gives it, the run goes there; without, frame by frame.
- `seconds` (number (> 0, <= 600.0), default `30.0`): How long to wait for the stop, in real seconds, before the server interrupts the machine. Left out, 30.
- `disarm_watches` (boolean, default `false`): `true` takes your watches off for this run, so none of them stops it, and sets them again at the end.
- `condition` (string, default `""`): Stop at the target only when this expression holds, in the debugger's own grammar with bare numbers read as hex: `w@DemoLen==0x25`.
- `cpu` (string, default `""`): The cpu the target and the control are set on. Left empty, the visible one.

### What comes back

- `verdict`: How the run ended: `TARGET`, the target was reached; `TIMEOUT`, the wait gave up; `OTHER_STOP`, a breakpoint or a watch nobody targeted stopped it first.
- `control_hits`: How many times the controls ran during the run. A `TARGET` is `ok` even with none.
- `controls`: One row per control counted on the target's cpu: its `ref`, its `cpu` and `hits_in_run`. It comes with a run to a `ref` or an anchor.
- `target_disarmed`: Whether the run's own breakpoint at the target was removed. It comes only when it was not, or when the interrupt at the time limit was answered late or never.
- `frames`: How many frames a run to a screen with no `anchor` took.
- `screen`: After a run to a screen: its `screen`, `layer` and `mode`, and `judged`, whether the map checked the screen there.

<details><summary>All 38 reply fields</summary>

- `disarmed_watches` (array)
- `not_rearmed` (array)
- `addr` (string)
- `call` (string)
- `evaluated_by` (string)
- `lines_ahead` (integer)
- `pc_before` (string)
- `reader_steps` (integer)
- `resent` (integer)
- `thread_errors` (integer)
- `armed` (boolean)
- `command_chars` (integer)
- `condition` (string)
- `control` (string)
- `control_dasm` (array)
- `control_hits` (integer)
- `console_reruns` (integer)
- `control_on` (array)
- `controls` (array)
- `cpu` (string or object)
- `following` (array of string)
- `frames` (integer)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer)
- `limit_chars` (integer)
- `pc` (string)
- `ref` (string)
- `regpoint_hit` (object)
- `regs` (object)
- `screen` (object)
- `state` (string)
- `stop_seq` (integer)
- `stored` (boolean)
- `target_disarmed` (boolean)
- `verdict` (string)
- `watch_hit` (object)
- `watches` (array)

</details>

### What it refuses

- A `ref`, a `control` or a `screen` that the symbol table or the screen map does not name (`unknown_ref`).
- No `control` with a `ref` or an anchored screen, or a `control` or `disarm_watches` with a screen that has no anchor (`bad_argument`).
- A target at a control's address, or at an address where one of your breakpoints already stops (`bad_argument`).
- A `condition` too long for one console command; the reply gives `command_chars` and `limit_chars` (`bad_argument`).
- A target MAME's console accepted and does not list, found before the machine moves (`readback_refused`).
- A `TIMEOUT` during which no control ran: nothing was learned about the target (`control_silent`).
- Another stop before any control ran (`cut_by_other_stop`).
- An interrupt at the time limit that got no answer: the machine may still be running, so call `stop` (`not_settled`).
- A screen map that no longer matches the screen at its anchor (`stale_map`).
- A machine that is running (`not_stopped`).

### Why it works this way

Several different mistakes leave a MAME breakpoint silent, and each looks exactly like "that routine is never called". The control counting beside the target tells them apart. A `TIMEOUT` with no control hit is refused, because it cannot tell a wrong address from a right one that runs less often than assumed.

The target is a temporary breakpoint of the run's own, removed when the run ends. It cannot share an address with a breakpoint you set, since a stop there could not be told from the target's. A stop at the target's address is `TARGET` only when it is the target cpu's.

`disarm_watches` is for a watch on a byte written every frame, which would otherwise stop every later run.

<details><summary>More on why</summary>

A control on another cpu runs another program, and runs even while the target's cpu is held in reset, so it cannot say that cpu ran. Naming one is `unknown_ref`, with `control_on` and the `breakpoint_at(..., cpu=)` call that fixes it.

Both breakpoints are read back from MAME's list before the machine moves. A target the console took and does not list would otherwise come back `TIMEOUT` beside a control that ran. One listed without its `condition` is removed first, or every later run would stop there.

When the time limit passes the server interrupts the machine. An interrupt answered late is a `TIMEOUT` whose `cause` says "answered late". One never answered is `not_settled` with no `cause`: call `stop`, and if `stop` fails as well, `close` then `start`.

A removal MAME refuses after the stop does not undo the stop. The reply keeps its readings with `target_disarmed: false`, and `note` names the `debug("bpclear 0x<row>")` that removes the breakpoint. `declaration_clear` cannot, because the target was never one of yours.

- `control_silent` still carries the stop's readings, a `note`, and `control_dasm`: the code at each control (`ref`, `cpu`, `dasm`).
- `disarmed_watches` lists the watches taken off and `not_rearmed` those not set again, by `ref` and `cpu`. After `session_broken` they stay off.

</details>

### Related tools

- [`breakpoint_at`](breakpoints.md#breakpoint_at)
- [`run_for`](#run_for)
- [`stop`](#stop)
- [`screen_map_write`](read.md#screen_map_write)
- [`screen_wait`](#screen_wait)
- [`declaration_clear`](breakpoints.md#declaration_clear)

<details><summary>The contract your client receives</summary>

```text
Run to `ref` and stop, with a control counting meanwhile.

`ref` is armed on `cpu` (the visible one when empty). `control` is required with a `ref` or an
anchored screen: a place the program runs often while the target is awaited, counted each time
it does, declared as a control on that cpu if it is new (`breakpoint_at(role="control")` does
the same ahead of time), and the cpu's other declared controls count too. `condition`: stop
only when it holds, bare numbers hex (`w@DemoLen==0x25`). `disarm_watches=true` disarms the watches for this pass, so none of them cuts it. Needs a stopped
machine. Refused: an unresolved ref, an empty or unresolved control, an over-long
`condition`.

`screen`: a mapped screen's name instead of `ref` (exactly one). If the screen names an `anchor` (set by `screen_map_write`), run to it (`control`
required): a `verified` map judges it there (`stale_map` when it no longer holds), a
`consolidated` one takes it as shown. If it names none, a frame at a time until the map names it,
within `seconds`; a `control` or `disarm_watches` is refused there (`bad_argument`). Reply: `screen` (`screen`, `layer`,
`mode`, `judged`), `frames` run. Refused: an unmapped screen (`unknown_ref`).

Reply: `verdict` (`TARGET`, `TIMEOUT`, `OTHER_STOP`), `control_hits`, `controls` (each `ref`,
`cpu`, `hits_in_run`; a run to a ref or an anchor), `target_disarmed` (the target was left
armed or the interrupt went unanswered), `frames` (a screen with no anchor), the
stop survey (`stop_seq`, `pc`, `regs`, `instruction`, `following` when the listing runs on).
INVALID has no `verdict`: `control_silent`, `cut_by_other_stop`, `not_settled`, `stale_map`.

Reference: REFERENCE.md, Running and stopping.
```

</details>
<!-- scry-reference:end run_to -->

<!-- scry-reference:begin run_for -->
## `run_for`

Run for a number of frames or milliseconds of emulated time and come back stopped.

```text
run_for(milliseconds=0, frames=0, seconds=30.0, disarm_watches=false)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, right after `start`.

Ask:

> Let the game run for five seconds of its own time, then stop.

Call:

```text
run_for(milliseconds=5000, seconds=300)
```

Reply, 6 of 18 fields:

```json
{
  "summary": "run_for 5000 ms: ELAPSED, frame 0 to 295",
  "verdict": "ELAPSED",
  "frame_before": 0,
  "frame_after": 295,
  "emulated_after_s": 5.000003,
  "cycles": 6250000
}
```

`ELAPSED` says the five seconds ran out as asked. The frame counter went from 0 to 295, the emulated clock reads a little over 5 seconds, and the cpu spent 6250000 cycles.

<details><summary>The whole reply</summary>

```json
{
  "summary": "run_for 5000 ms: ELAPSED, frame 0 to 295",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 0,
  "frame_after": 295,
  "emulated_before_s": 3e-06,
  "emulated_after_s": 5.000003,
  "cycles": 6250000,
  "reads": "<volatile>",
  "cause": "the console's `gtime` stop",
  "stop_seq": 2,
  "pc": "0x0000a631",
  "cpu": ":maincpu",
  "frame": 295,
  "regs": {
    "A": "0x0a",
    "B": "0x4b",
    "D": "0x0a4b",
    "X": "0xc901",
    "Y": "0xf2e6",
    "U": "0xbef1",
    "PC": "0xa631",
    "S": "0x0800",
    "CC": "0xc4",
    "DP": "0x00"
  },
  "instruction": {"address": "A631", "bytes": "04B4", "text": "LSR    <$B4", "symbol": "wait_frame", "delta": 0},
  "following": ["A633: 24 FC    BCC    $A631", "A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "... 7 more"],
  "errorlog": "<volatile>"
}
```

</details>

### Arguments

- `milliseconds` (integer, default `0`): How much emulated time to run, in milliseconds. Give this or `frames`, never both.
- `frames` (integer, default `0`): How many frames to run, counted on MAME's frame counter. Give this or `milliseconds`, never both.
- `seconds` (number (> 0, <= 600.0), default `30.0`): How long to wait for the run to end, in real seconds. Left out, 30.
- `disarm_watches` (boolean, default `false`): `true` takes your watches off for this run, so none of them stops it, and sets them again at the end.

### What comes back

- `verdict`: How the run ended: `ELAPSED`, the frames or time asked for ran out, as asked; `TIMEOUT`, the wait gave up; `OTHER_STOP`, a breakpoint or a watch stopped it first.
- `frame_after`: The frame counter after the run; `frame_before` is the one before. Unavailable, with why, on a board with no frame counter.
- `emulated_after_s`: The emulated clock after the run, in seconds; `emulated_before_s` is the one before.
- `cycles`: The cpu cycles the run took, for what was asked and nothing else. Unavailable, with why, when they cannot be counted.
- `polls`: By frames: how many single-frame runs were sent. One more than `frames` means the run began in the middle of a frame.
- `reads`: By milliseconds: how many times the counter was read until it stood still.

<details><summary>All 23 reply fields</summary>

- `command_chars` (integer)
- `cpu` (string or object)
- `cycles` (integer or object)
- `following` (array of string)
- `instruction` (StopInstruction)
- `emulated_after_s` (number or object)
- `emulated_before_s` (number or object)
- `errorlog` (object)
- `frame` (integer or object)
- `frame_after` (integer or object)
- `frame_before` (integer or object)
- `limit_chars` (integer)
- `pc` (string)
- `polls` (integer)
- `reads` (integer)
- `regpoint_hit` (object)
- `regs` (object)
- `stop_seq` (integer)
- `verdict` (string)
- `watch_hit` (object)
- `watches` (array)
- `disarmed_watches` (array)
- `not_rearmed` (array)

</details>

### What it refuses

- Both `milliseconds` and `frames`, or neither (`bad_argument`).
- `frames` on a board with no frame counter: run it by `milliseconds` (`no_channel`).
- A run during which the counter did not move (`no_progress`).
- A counter that went backwards: something put the machine back during the run (`frames_went_backwards`).
- A counter or a clock still moving at the time limit: the machine may still be running, so call `stop` (`not_settled`).
- A machine that is running (`not_stopped`).

### Why it works this way

A run by frames counts MAME's frame counter itself, so a capture can be taken again at the same frame; N milliseconds is not N frames. A run is `ELAPSED` only once several readings spaced apart agree the machine has stopped: one handed back still running is the worst state for a session.

By frames the run goes through the first cpu: MAME keeps "a vblank happened", the end of a frame's drawing, as one flag. The first cpu to run after it consumes the flag, so only that cpu stops there. `note` says when that cpu had to be made visible.

`cycles` spans what was asked for. A run that starts in the middle of a frame first spends one single-frame run reaching the vblank it is inside. That one moves no counter, and `polls` is how it shows.

<details><summary>More on why</summary>

`cycles` is unavailable on the first run after a load, a rewind or a reset typed through `debug`. MAME's debugger refreshes its cycle counter only when the cpu executes, so the span would be off by the distance between the two states. It is also unavailable when the run was counted on one cpu and stopped on another.

A board with no screen device has no frame counter and is run by `milliseconds`. MAME registers `frame` on a machine with one screen device and `frame0`, `frame1` and so on with several, where the first one is used. `start` asks MAME and reports the name as `frame_symbol`.

A vector board has a display and no screen device, so the screens `machine_map` lists are no guide. There a stop's `frame` is unavailable and the emulated clock confirms the stop. An expression MAME's console refuses there is `no_channel`: an answer about the machine, not a broken session.

- A MAME without one debugger thread per cpu cannot change the visible cpu without running, so it refuses `frames` while another cpu is visible.
- `no_progress` by frames leaves the machine running until `stop` and carries no stop readings. By milliseconds it carries them.
- After `not_settled`, call `stop`. If `stop` fails as well, `close` then `start`.
- The call reports progress to the client while it waits.
- A run started while a registerpoint's condition still holds stops one instruction later as `OTHER_STOP`, never `no_progress`.

</details>

### Related tools

- [`run_to`](#run_to)
- [`resume`](#resume)
- [`stop`](#stop)
- [`trace`](#trace)
- [`screen_wait`](#screen_wait)
- [`status`](session.md#status)

<details><summary>The contract your client receives</summary>

```text
Run for `milliseconds` of emulated time or `frames` of the frame counter (exactly one) and
wait until STOPPED. `disarm_watches=true` disarms the watches for this pass, so none of them cuts it. Needs the machine STOPPED (else `not_stopped`).

Reply: `verdict` (`ELAPSED`, `TIMEOUT`, `OTHER_STOP`; a control never cuts), `frame_before`,
`frame_after`, `emulated_before_s`, `emulated_after_s`, `cycles` (each unavailable with
why), `polls` (by frames) or `reads` (by milliseconds), and the stop survey of `run_to`.
INVALID has no `verdict`: `no_progress`, `frames_went_backwards`, `not_settled`,
`session_broken`; `no_channel` on a board with no counter.

Reference: REFERENCE.md, Running and stopping.
```

</details>
<!-- scry-reference:end run_for -->

<!-- scry-reference:begin step -->
## `step`

Execute a few instructions of one cpu, going into calls or over them.

```text
step(count=1, mode="into", cpu="")
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, stopped at `count_coin`, where the `run_to` example above ends.

Ask:

> Execute one instruction and show me where the cpu is now.

Call:

```text
step(count=1)
```

Reply, 6 of 13 fields:

```json
{
  "summary": "step 1 into: pc 0x0000b586",
  "mode": "into",
  "instructions_completed": 1,
  "pc": "0x0000b586",
  "cpu": ":maincpu",
  "frame": 552
}
```

One instruction ran, going into any call, and the main cpu is now at `0xb586`, in frame 552. The whole reply shows the instruction that runs next.

<details><summary>The whole reply</summary>

```json
{
  "summary": "step 1 into: pc 0x0000b586",
  "status": "ok",
  "mode": "into",
  "instructions_completed": 1,
  "cause": "step 1",
  "stop_seq": 19,
  "pc": "0x0000b586",
  "cpu": ":maincpu",
  "frame": 552,
  "regs": {
    "A": "0x01",
    "B": "0xcf",
    "D": "0x01cf",
    "X": "0xe199",
    "Y": "0xf2e6",
    "U": "0x7acf",
    "PC": "0xb586",
    "S": "0x07fc",
    "CC": "0xa0",
    "DP": "0x00"
  },
  "instruction": {"address": "B586", "bytes": "8601", "text": "LDA    #$01", "symbol": "count_coin", "delta": 3},
  "following": ["B588: BB 04 2C ADDA   $042C", "B58B: 19       DAA", "B58C: B7 04 2C STA    $042C", "B58F: 39       RTS", "B590: 96 F4    LDA    <$F4", "B592: 27 21    BEQ    $B5B5", "... 8 more"],
  "errorlog": "<volatile>"
}
```

</details>

### The two modes

| mode | what it does |
|---|---|
| `into` | Executes one instruction, and enters a call. |
| `over` | Runs a call to its return as one step. |

### Arguments

- `count` (integer (>= 1, <= 300), default `1`): How many instructions to execute. Left out, one.
- `mode` (one of `"into"`, `"over"`, default `"into"`): `into` or `over`, as above.
- `cpu` (string, default `""`): The cpu to step, made visible first. Left empty, the visible one.

### What comes back

- `instructions_completed`: How many instructions ran. Fewer than `count` when a stop on another cpu ended the steps, which `note` says.
- `mode`: The `mode` the steps ran in.
- `others`: Every other cpu's program counter `before` and `after` the steps, with its register's name in `reg`. Only on a MAME built with one debugger thread per cpu.

<details><summary>All 16 reply fields</summary>

- `command_chars` (integer)
- `cpu` (string)
- `following` (array of string)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer or object)
- `instructions_completed` (integer)
- `limit_chars` (integer)
- `mode` (string)
- `others` (object)
- `pc` (string)
- `regpoint_hit` (object)
- `regs` (object)
- `stop_seq` (integer)
- `watch_hit` (object)
- `watches` (array)

</details>

### What it refuses

- A named `cpu` on a MAME that cannot show another cpu without running it (`bad_argument`).
- A step whose stop did not come in time: the machine may still be running, so call `stop` (`not_settled`).
- An answer that is not a stop where one was due, a failed connection, or an `over` MAME did not answer in time (`session_broken`).
- A machine that is running (`not_stopped`).

### Why it works this way

Each step is confirmed on the program counter, because MAME's console answers an `over` while the machine is still running to the call's return.

The largest `count` is what keeps the longest run of `over` steps inside the time limit every wait has. Past it the tool to use is `run_to` or `run_for`.

Naming a `cpu` makes it the visible one first, which runs nothing, and `others` shows what the rest did meanwhile. That needs a MAME built with one debugger thread per cpu: without it another cpu cannot be shown without running, so naming one is refused.

<details><summary>More on why</summary>

An `over` still moving at its time limit is interrupted, and whether the call would have returned is not seen. An `over` MAME refused may still have been taken, so the session is marked as running and `stop` brings it back; if `stop` fails as well, `close` then `start`.

An `into` whose stop is late still has that stop to come, and `stop` waits for it. The `not_settled` reply carries `mode` and `instructions_completed`.

An `into` that reads anything else in a stop's place, a failed connection, or an `over` the console did not answer in time is `session_broken`. That stays set until `close`, because the late answer would otherwise be read as the next request's.

</details>

### Related tools

- [`run_to`](#run_to)
- [`run_for`](#run_for)
- [`stop`](#stop)
- [`disassemble`](read.md#disassemble)
- [`registers`](read.md#registers)
- [`cpu_focus`](session.md#cpu_focus)

<details><summary>The contract your client receives</summary>

```text
Execute `count` (1..300) instructions of `cpu` (the visible one when empty): `into`
is one instruction, `over` runs a call to its return as one step. A named cpu is made
visible first; `others` gives every other cpu's program counter before and after. A stop on
another cpu ends the steps (`note`). Needs the machine STOPPED (else `not_stopped`).

Reply: `mode`, `instructions_completed`, `others` (on a build with a thread per cpu), and
the stop survey of `run_to`. A refused `over` may have run: the machine is marked RUNNING,
and `stop` recovers it. INVALID: `not_settled`, `session_broken`.

Reference: REFERENCE.md, Running and stopping.
```

</details>
<!-- scry-reference:end step -->

<!-- scry-reference:begin resume -->
## `resume`

Let the machine run, either with no deadline or waiting a while for it to stop.

```text
resume(seconds=0.0)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, stopped right after a reset.

Ask:

> Let the game run.

Call:

```text
resume()
```

Reply, 2 of 2 fields:

```json
{
  "summary": "resume: running, no wait asked",
  "status": "ok"
}
```

Then stop it again:

Call:

```text
stop()
```

Reply, 3 of 13 fields:

```json
{
  "interrupted": true,
  "cause": "interrupt",
  "stop_seq": 62
}
```

With no `seconds` the call returns at once and the game keeps running. The `stop` after it interrupted the machine: the session's stop number 62.

<details><summary>The two replies, whole</summary>

The first call's:

```json
{
  "summary": "resume: running, no wait asked",
  "status": "ok"
}
```

The second call's:

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "interrupted": true,
  "cause": "interrupt",
  "stop_seq": 62,
  "pc": "<volatile>",
  "cpu": ":maincpu",
  "frame": "<volatile>",
  "regs": "<volatile>",
  "instruction": "<volatile>",
  "following": "<volatile>",
  "errorlog": "<volatile>",
  "average_speed": "<volatile>"
}
```

</details>

### Arguments

- `seconds` (number (>= 0, <= 600.0), default `0.0`): How long to wait for a stop, in real seconds. Left at 0, the call returns at once and the machine keeps running.

### What comes back

- `verdict`: With `seconds`: `OTHER_STOP`, a breakpoint or a watch stopped the machine, and the stop's readings follow; `TIMEOUT`, nothing did, and it is left running with a `note`.
- `waited_s`: With `seconds`: how long the call waited.
- `average_speed`: With a stop: how fast the machine ran, as `percent` of real time, over `emulated_s` and `wall_s`.

<details><summary>All 14 reply fields</summary>

- `average_speed` (object)
- `cpu` (string)
- `following` (array of string)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer)
- `pc` (string)
- `regpoint_hit` (object)
- `regs` (object)
- `stop_seq` (integer)
- `verdict` (string)
- `waited_s` (number)
- `watch_hit` (object)
- `watches` (array)

</details>

### What it refuses

- A machine that is already running (`not_stopped`).
- An answer that is not a stop where one was due, a resume that could not be sent, or a stop that could not be read (`session_broken`).

### Why it works this way

While the machine runs, the tools that read it refuse. Each refusal names `last_stop`, the stop the machine was last seen at, and `answers_while_running`, the tools that still answer.

A `resume` with `seconds` reports progress while it waits. After `session_broken` the way out is `close`, then `start`.

### Related tools

- [`stop`](#stop)
- [`run_to`](#run_to)
- [`run_for`](#run_for)
- [`breakpoint_at`](breakpoints.md#breakpoint_at)
- [`status`](session.md#status)

<details><summary>The contract your client receives</summary>

```text
Let the machine run. `seconds` 0 (the default) returns at once with no deadline; a bound up
to 600 waits for a stop and, if none comes, leaves it running. Needs the machine STOPPED (else `not_stopped`).

Reply: with a bound, `waited_s` and `verdict` (`OTHER_STOP` with the stop survey and
`average_speed`; `TIMEOUT`, left running, with a `note`). INVALID: `session_broken`.

Reference: REFERENCE.md, Running and stopping.
```

</details>
<!-- scry-reference:end resume -->

<!-- scry-reference:begin stop -->
## `stop`

Stop a running machine where it is and read where it stopped.

```text
stop()
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, running after a `resume`.

Ask:

> Stop the game where it is.

Call:

```text
stop()
```

Reply, 4 of 13 fields:

```json
{
  "interrupted": true,
  "cause": "interrupt",
  "stop_seq": 62,
  "cpu": ":maincpu"
}
```

`interrupted: true` means this call stopped the machine. It is the session's stop number 62, on the main cpu; where it lands differs from run to run.

<details><summary>The whole reply</summary>

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "interrupted": true,
  "cause": "interrupt",
  "stop_seq": 62,
  "pc": "<volatile>",
  "cpu": ":maincpu",
  "frame": "<volatile>",
  "regs": "<volatile>",
  "instruction": "<volatile>",
  "following": "<volatile>",
  "errorlog": "<volatile>",
  "average_speed": "<volatile>"
}
```

</details>

### Arguments

Takes no argument.

### What comes back

- `interrupted`: `true` when this call stopped the machine, with the stop's readings. `false` when it was already stopped, with a `note`.
- `average_speed`: How fast the machine ran since it was resumed: `percent` of real time, over `emulated_s` and `wall_s`.

<details><summary>All 13 reply fields</summary>

- `average_speed` (object)
- `cpu` (string)
- `following` (array of string)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer or object)
- `interrupted` (boolean)
- `pc` (string)
- `regpoint_hit` (object)
- `regs` (object)
- `stop_seq` (integer)
- `watch_hit` (object)
- `watches` (array)

</details>

### What it refuses

- An interrupt the machine did not answer, or a frame counter that still moves: the machine stays marked as running, so ask again (`not_settled`).
- An interrupt answered by something that is not a stop, a failed connection, or a stop that could not be read (`session_broken`).

### Why it works this way

`stop` is the way back from any run that ended without knowing whether the machine stopped. A run by frames refused as `no_progress` is brought back here: the interrupt is what confirms the stop.

Nothing counts the attempts. If `stop` fails as well, `close` then `start`.

<details><summary>More on why</summary>

`not_settled` also covers a run started from MAME's console, through `debug`, whose frame counter still moves.

</details>

### Related tools

- [`resume`](#resume)
- [`run_for`](#run_for)
- [`status`](session.md#status)
- [`close`](session.md#close)
- [`start`](session.md#start)

<details><summary>The contract your client receives</summary>

```text
Stop a running machine where it is and survey the stop.

Reply: `interrupted` (`true` with the stop survey and `average_speed`; `false` when already
stopped, with a `note`). INVALID: `not_settled` (the machine stays marked RUNNING; ask
again), `session_broken`.

Reference: REFERENCE.md, Running and stopping.
```

</details>
<!-- scry-reference:end stop -->

<!-- scry-reference:begin trace -->
## `trace`

Run for a number of frames or milliseconds and get every address one cpu executed, grouped by symbol.

```text
trace(milliseconds=0, frames=0, dest="", seconds=60.0, cpu="", noloop=false)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, started with the names in [gridlee-symbols.yaml](tour/gridlee-symbols.yaml) and stopped about a second into a new game.

Ask:

> Trace the next two frames and tell me which routines the game runs.

Call:

```text
trace(frames=2, dest="./tmp/demos/tour/trace.txt", seconds=300)
```

Reply, 5 of 19 fields:

```json
{
  "summary": "trace :maincpu 2 frames: 192 addresses in 4 symbols, 19627 bytes",
  "verdict": "ELAPSED",
  "frame_before": 628,
  "frame_after": 630,
  "cycles": 42239
}
```

In two frames, 628 to 630, the main cpu ran through 192 distinct addresses under 4 symbols, and the log is 19627 bytes. `trace`, in the whole reply, lists each symbol.

<details><summary>The whole reply</summary>

```json
{
  "summary": "trace :maincpu 2 frames: 192 addresses in 4 symbols, 19627 bytes",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 628,
  "frame_after": 630,
  "emulated_before_s": 10.627602,
  "emulated_after_s": 10.661393,
  "cycles": 42239,
  "polls": 2,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 59,
  "pc": "0x0000fd80",
  "cpu": ":maincpu",
  "frame": 630,
  "regs": {
    "A": "0x00",
    "B": "0xd8",
    "D": "0x00d8",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xfd80",
    "S": "0x07f4",
    "CC": "0xd4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "... 9 more"],
  "errorlog": "<volatile>",
  "trace": {
    "cpu": ":maincpu",
    "path": "./tmp/demos/tour/trace.txt",
    "bytes": 19627,
    "set_path": "./tmp/demos/tour/trace-txt-set.jsonl",
    "instructions": 9398,
    "addresses": 192,
    "unplaced": 0,
    "symbols": [
      {
        "symbol": "wait_frame",
        "addr": "0x0000a631",
        "addresses": 26,
        "first": "0x0000a631",
        "last": "0x0000a79b"
      },
      {
        "symbol": "write_sprites",
        "addr": "0x0000a7f6",
        "addresses": 25,
        "first": "0x0000b52b",
        "last": "0x0000b561"
      },
      {
        "symbol": "count_coin",
        "addr": "0x0000b583",
        "addresses": 36,
        "first": "0x0000b58f",
        "last": "0x0000cc5b"
      },
      {
        "symbol": "irq",
        "addr": "0x0000fd80",
        "addresses": 105,
        "first": "0x0000fd80",
        "last": "0x0000ffa0"
      }
    ],
    "symbols_total": 4,
    "truncated": false,
    "noloop": false,
    "note": "the pc :maincpu was parked on, 0x0000fd80, is counted: the window executed it first and the tracer, armed there, does not log it"
  }
}
```

</details>

### Arguments

- `milliseconds` (integer, default `0`): The window to trace, in milliseconds of emulated time. Give this or `frames`, never both.
- `frames` (integer, default `0`): The window to trace, in frames. Give this or `milliseconds`, never both.
- `dest` (string, default `""`): Where MAME writes the trace: an absolute path to a new file. Left empty, a file in the session's temporary folder.
- `seconds` (number (> 0, <= 600.0), default `60.0`): How long to wait for the run to end, in real seconds. Left out, 60.
- `cpu` (string, default `""`): The cpu to trace. Left empty, the visible one.
- `noloop` (boolean, default `false`): `true` logs every instruction, so the counts are exact and the largest window is shorter. Left out, MAME condenses loops and only the list of addresses is exact.

### What comes back

- `trace`: The result: `path` to MAME's log, `set_path` to the list of addresses, `instructions`, `addresses`, `unplaced` (addresses no symbol covers) and `symbols`.
- `verdict`: How the run ended, as in `run_for`: `ELAPSED`, the window ran out as asked; `TIMEOUT`, the wait gave up; `OTHER_STOP`, a breakpoint or a watch stopped it first.
- `frame_after`: The frame counter after the run, with `frame_before`, the clock and `cycles` as `run_for` returns them.

<details><summary>All 18 reply fields</summary>

- `emulated_after_s` (number or object)
- `emulated_before_s` (number or object)
- `cpu` (string or object)
- `cycles` (integer)
- `following` (array of string)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer)
- `frame_after` (integer)
- `frame_before` (integer)
- `path` (string)
- `pc` (string or object)
- `polls` (integer)
- `regs` (object)
- `stop_seq` (integer)
- `trace` (object)
- `verdict` (string)
- `watches` (array)

</details>

### What it refuses

- A `dest` that exists already, or whose list file `<name>-<extension>-set.jsonl` does (`bad_argument`).
- A cpu with no disassembler, since the tracer disassembles every line it writes (`no_channel`).
- A trace with no instruction line: the cpu executed nothing or the tracer recorded nothing, and the two look alike (`readback_refused`).
- A tracer that could not be shown closed, with `trace.closed: false` (`readback_refused`).
- A file MAME could not open (`host_failed`).

### Why it works this way

The tracer is armed and closed inside one call, because one left armed keeps writing on the next run of a client that forgot it. Arming replaces a trace typed through `debug` on that cpu. The limits on the window keep one call's output small; a longer window is consecutive calls.

MAME's tracer logs an address when the cpu reaches it, before executing it. So the address a stopped cpu is waiting at is missing from a trace armed there, and the address the run ends at is logged although never executed. Both are corrected, and `note` says which applied.

By default the tracer condenses loops: it keeps the last addresses and skips one it has seen twice among them. The list of addresses survives that, because an address is logged before it is skipped. The counts do not, so `instructions` is exact only under `noloop`.

<details><summary>More on why</summary>

| in `trace` | what it holds |
|---|---|
| `path`, `bytes` | MAME's own log and its size |
| `set_path` | a file with one JSON line per executed address, ascending: `addr`, `symbol` when one covers it, `count` under `noloop` |
| `instructions`, `addresses`, `unplaced` | instructions logged, distinct addresses, addresses no symbol covers |
| `symbols` | the first rows, by address: `symbol`, `addr`, `addresses`, `first`, `last`, and `instructions` under `noloop` |
| `symbols_total`, `truncated` | how many symbols ran, and whether `symbols` leaves some out |
| `cpu`, `noloop`, `note` | the cpu traced, whether loops were kept whole, and the corrections applied |
| `closed` | on a refusal: whether the tracer was closed |

The tracer cannot see a cpu the debugger ignores, a cpu waiting on its own, or a stretch that runs with a save or a load pending. MAME calls no instruction hook for them. A cpu that pauses in the middle of an instruction, as MAME's 68000 does, finishes it after the window, unlogged.

When the tracer cannot be shown closed, the way out is `stop`, then `debug("trace off,<cpu>")`. If `stop` fails, `close` then `start`, since closing MAME closes the file. A run that ends `INVALID` carries `trace` with `path`, `bytes` and `closed`, and no list file.

One address can go missing from a condensed trace: address 0, when it runs among the first instructions, because the tracer's history starts as zeros.

</details>

### Related tools

- [`run_for`](#run_for)
- [`symbols_find`](names.md#symbols_find)
- [`history`](read.md#history)
- [`disassemble`](read.md#disassemble)
- [`captures`](captures.md#captures)

<details><summary>The contract your client receives</summary>

```text
Run as `run_for` does with MAME's tracer on one cpu, then return the addresses it executed,
joined to symbols. Window: `milliseconds` or `frames` (at most 5026 frames or
98143 ms; `noloop`, 1648 and 32920). `dest`: an absolute
new path. `noloop=True`: exact `count`s, not which addresses ran. Needs a stopped machine.

Reply: `run_for`'s, plus `trace` (`path`, `set_path`, `instructions`, `addresses`,
`unplaced`, `symbols` (first 64)). Refused: `dest` existing,
`no_channel`, `readback_refused`.

Reference: REFERENCE.md, Running and stopping.
```

</details>
<!-- scry-reference:end trace -->

<!-- scry-reference:begin screen_wait -->
## `screen_wait`

Run until the screen shows a mapped screen, a black palette or a change of screen, and stop there.

```text
screen_wait(text="", screen="", palette="", changed=false, every=0, on_breakpoint="", on_watch="",
    condition="", cpu="", seconds=30.0)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, with a screen map that names its level card, stopped right after START is pressed with two credits.

Ask:

> Run until the level card is on screen.

Call:

```text
screen_wait(screen="level_card", seconds=300)
```

Reply, 6 of 24 fields:

```json
{
  "summary": "screen_wait screen 'level_card': found after 13 frames",
  "verdict": "TARGET",
  "predicate": "screen",
  "already": false,
  "polls": 13,
  "screen": {"name": "level_card", "layer": "session"}
}
```

The map's `level_card` screen was not up at the call, which is `already: false`. It came up 13 frames later, and the machine stopped there.

<details><summary>The whole reply</summary>

```json
{
  "summary": "screen_wait screen 'level_card': found after 13 frames",
  "status": "ok",
  "verdict": "TARGET",
  "frame_before": 560,
  "frame_after": 561,
  "emulated_before_s": 9.478676,
  "emulated_after_s": 9.495568,
  "cycles": 21115,
  "polls": 13,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 55,
  "pc": "0x0000fd80",
  "cpu": ":maincpu",
  "frame": 561,
  "regs": {
    "A": "0x01",
    "B": "0x1d",
    "D": "0x011d",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xfd80",
    "S": "0x07f4",
    "CC": "0xd4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "... 9 more"],
  "errorlog": "<volatile>",
  "predicate": "screen",
  "already": false,
  "sampled_every": 0,
  "frames": 13,
  "waited_s": "<volatile>",
  "screen": {"name": "level_card", "layer": "session"}
}
```

</details>

### Arguments

- `text` (string, default `""`): Not available here: MAME gives the screen as pixels, so waiting for text is refused. Map the screen with `screen_map_write` and wait on `screen`.
- `screen` (string, default `""`): Wait until this screen of the loaded screen map, the file naming a program's screens, is the one shown.
- `palette` (one of `""`, `"black"`, default `""`): `black` waits until every palette entry is black, which is how a fade ends.
- `changed` (boolean, default `false`): `true` waits until the screen map names a different screen from the one it named at the start. A frame it cannot name counts as in between.
- `every` (integer (>= 0, <= 600), default `0`): How many frames to run between two looks at the screen. Left at 0, every frame; a screen shown for fewer frames than this can be missed.
- `on_breakpoint` (string, default `""`): Look at the screen only at the end of a frame in which this breakpoint fired: the `ref` of a `stop` breakpoint you set.
- `on_watch` (string, default `""`): The same for a watch: the `ref` of a `change` watch you set.
- `condition` (string, default `""`): Counts only the firings where this holds. Up to four terms joined by `&&`, each a register or a memory read (`b@ref`, `w@ref`, `d@ref`) compared with a hex value.
- `cpu` (string, default `""`): The cpu whose breakpoint or watch `on_breakpoint` and `on_watch` name. Left empty, the visible one.
- `seconds` (number (> 0, <= 600.0), default `30.0`): How long to keep looking, in real seconds, counted from the first look. Left out, 30.

### What comes back

- `verdict`: `TARGET` when what you waited for is on screen. `TIMEOUT` when the wait gave up, with a `note` and the machine stopped.
- `already`: `true` when it was on screen at the call, so the machine did not move.
- `predicate`: Which of `screen`, `palette` or `changed` was waited on.
- `polls`: How many frames ran, also given as `frames`; `sampled_every` repeats `every`.
- `screen`: The screen found, as `name` and `layer`. With `changed`, `started_on` is the screen it replaced.
- `firings`: With `on_breakpoint` or `on_watch`: how many times it fired. `frames_examined` counts the frames looked at after a firing.

<details><summary>All 34 reply fields</summary>

- `command_chars` (integer)
- `cpu` (string or object)
- `cycles` (integer or object)
- `following` (array of string)
- `instruction` (StopInstruction)
- `emulated_after_s` (number or object)
- `emulated_before_s` (number or object)
- `errorlog` (object)
- `frame` (integer or object)
- `frame_after` (integer or object)
- `frame_before` (integer or object)
- `limit_chars` (integer)
- `pc` (string)
- `polls` (integer)
- `reads` (integer)
- `regpoint_hit` (object)
- `regs` (object)
- `stop_seq` (integer)
- `verdict` (string)
- `watch_hit` (object)
- `watches` (array)
- `waited_on` (object)
- `firings` (integer)
- `frames_examined` (integer)
- `fired_line` (integer or object)
- `already` (boolean)
- `entries` (integer)
- `frames` (integer)
- `palette` (string)
- `predicate` (string)
- `sampled_every` (integer)
- `screen` (object)
- `started_on` (string or object)
- `waited_s` (number)

</details>

### What it refuses

- None or several of `screen`, `palette` and `changed` (`bad_argument`).
- `text`, or a palette that cannot be read at a stop (`no_channel`).
- A screen the map does not name, or a breakpoint or watch you did not set (`unknown_ref`).
- `changed` with no screen map loaded (`needs_call`).
- A breakpoint or watch that never fired within `seconds`: no screen was looked at (`never_fired`).
- A stop nobody asked for that ends the wait early; its `cause` and the stop's readings come with it (`wait_stopped`).

### Why it works this way

The server looks at the screen itself, at a stop at the end of a frame. MAME's own frame notifier is not used: it reads the screen a frame late and sometimes in the middle of a draw.

Without `on_breakpoint` or `on_watch` the wait looks every frame, or every `every` frames, which is how a screen that is slow to read is waited on in reasonable time. With one, MAME counts the firings and stops only at a picture this wait has not yet rejected.

A wait that gives up never leaves the machine running: the last run is stopped first. If the screen is already there the reply comes at once, except under `on_breakpoint` or `on_watch`, where the first firing is awaited even so.

<details><summary>More on why</summary>

- `waited_on` repeats what was waited on: its `kind`, its `ref`, and the `condition` if any.
- `fired_line` is the screen line being drawn at the firing that counted, or unavailable when no firing met the `condition`.
- `palette` and `entries` come with a black palette: the value asked for, and how many palette entries were read.
- Under `on_breakpoint` or `on_watch`, these fields replace `polls` and `sampled_every`.

</details>

### Related tools

- [`screen_map_write`](read.md#screen_map_write)
- [`screen_map_find`](read.md#screen_map_find)
- [`run_to`](#run_to)
- [`run_for`](#run_for)
- [`palette`](screen.md#palette)
- [`breakpoint_at`](breakpoints.md#breakpoint_at)

<details><summary>The contract your client receives</summary>

```text
Run the machine until ONE predicate holds, and stop there.

`screen`: the loaded map's screen is on the frame (`screen_map_write`; enters it). `palette`
(`black`: every DAC entry black, which is how a fade ends). `changed`: the map names a
screen other than the one it named at the start; a frame it names nothing is a transition.
Exactly one, or `bad_argument`; `text` is refused `no_channel`, because this server hands
the screen as pixels and a text mode's characters are DOSBox-X's to read.

`on_breakpoint` / `on_watch`: judge only at the frame's end after a firing of that declared
`stop` breakpoint or `change` watch (its `ref`, on `cpu`), never sampling; `condition`
(up to 4 terms joined by `&&`, each a register of the stopped cpu or a memory read (`b@ref`, `w@ref`, `d@ref`), a comparison (`==`, `!=`, `<`, `<=`, `>`, `>=`) and a hex value (`0x` allowed)) filters the firings first. MAME's Lua counts the firings and stops
only on a picture this wait has not rejected; the first firing is awaited even when the
predicate already holds.

`every`: 0 judges every frame; N runs N frames per poll, which is how a screen whose read
costs a console round trip is waited on in reasonable time, and a screen alive for fewer
than N is passed over. `seconds` bounds the polls, counted from the opening judge; the
recovery stop comes after it. Needs a stopped machine. Already true: answered at once, the
machine not moved. The emulator's own frame notifier is not used: it reads the screen a
frame late and sometimes mid-draw, so the judge is the server's at the stop.

Reply: `verdict` `TARGET` (`predicate`, `already`, `waited_s`, `polls`, `sampled_every`;
screen adds `screen`, palette adds `entries`, `changed` adds `screen` and `started_on`) or
`TIMEOUT` (the same, with `note` and the stop survey of `run_for`), the stop's own fields;
under `on_*`, `waited_on`, `firings`, `frames_examined` (the frames looked at after a firing) and `fired_line` in place of `polls` and `sampled_every`. A poll the bound itself cut is
stopped there first, so the machine is never left running under a wait that gave up.
Refused: `bad_argument`, `unknown_ref` (no such mapped screen or declared row), `needs_call`
(`changed` with no map loaded), `no_channel`, `never_fired` (the row never fired within
`seconds`), and `wait_stopped` when a stop nobody asked for ends the wait before the bound
(its `cause` and the stop's fields ride beside it).

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end screen_wait -->
