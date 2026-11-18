# The Lua tools

These tools work through MAME's Lua console. `input` presses one of the board's inputs, `lua` runs a script of yours, and `throttle` sets whether the machine runs at real speed.

The console runs a line only when the machine moves: once a frame while it runs, and once each time it stops. A line sent to a stopped machine waits for the next step or frame. That is why `lua` steps the machine once, and why a `throttle` asked while stopped is not applied yet.

## How input gets into the program

`input` sets a named field of one of MAME's input ports, inside the machine, keeps it set for the frames asked and clears it. No key is sent to the emulator's window.

An input that was sent is not an input the game took. The reply reads the port back as the field is let go: `active` says the port showed the press, not what the game did with it.

<!-- scry-reference:begin input -->
## `input`

Press one of the board's inputs by name (a coin, a start button), hold it for some frames and let go.

```text
input(port, field, value=1, frames=4, seconds=30.0)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, stopped about seven seconds after power-on. The example session drops this coin as the first step of a `perform`.

Ask:

> Drop a coin into the first slot and keep it pressed for four frames.

Call:

```text
input(port=":IN1", field="Coin 1", frames=4, seconds=300)
```

Reply, 7 of 36 fields:

```json
{
  "summary": "input :IN1 'Coin 1': held 4 frames, active True, released at frame 423",
  "status": "ok",
  "port_before": "0x000000cf",
  "port_held": "0x000000ce",
  "frame_set": 419,
  "frame_released": 423,
  "active": true
}
```

Bit 0 of the port went low while pressed (`0xcf` to `0xce`), from frame 419 to frame 423. `active` confirms the port showed the press; whether the game counted the coin is for its memory to say.

<details><summary>The whole reply</summary>

```json
{
  "summary": "input :IN1 'Coin 1': held 4 frames, active True, released at frame 423",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 419,
  "frame_after": 424,
  "emulated_before_s": 7.096336,
  "emulated_after_s": 7.180818,
  "cycles": 105602,
  "polls": 6,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":IN1",
  "field": "Coin 1",
  "value": "0x00000001",
  "frames": 4,
  "name": "Coin 1",
  "player": 0,
  "mask": "0x00000001",
  "defvalue": "0x00000001",
  "port_before": "0x000000cf",
  "frame_set": 419,
  "released": true,
  "port_held": "0x000000ce",
  "frame_released": 423,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 7,
  "pc": "0x0000fd80",
  "cpu": ":maincpu",
  "frame": 424,
  "regs": {
    "A": "0x00",
    "B": "0x00",
    "D": "0x0000",
    "X": "0x0150",
    "Y": "0x00e3",
    "U": "0x00e5",
    "PC": "0xfd80",
    "S": "0x07f2",
    "CC": "0x90",
    "DP": "0x00"
  },
  "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "... 9 more"],
  "errorlog": "<volatile>"
}
```

</details>

### Arguments

- `port` (string, required): The input port that has the field, as MAME names it: `:P1`.
- `field` (string, required): The field of that port to press, as MAME names it: `Coin 1`.
- `value` (integer or string, default `1`): What the field is set to: non-zero presses a digital field, an analog one takes a value in its range. Left out, 1; a string is a `0x` number.
- `frames` (integer, default `4`): How many frames the field stays pressed: one or more. Left out, 4.
- `seconds` (number (> 0, <= 600.0), default `30.0`): The time limit of the whole call, in real seconds, up to 600. Left out, 30.

### What comes back

- `released`: `true` when the field was let go. `false` when another stop cut the run first: the field is still pressed, and `frame_release_planned` is the frame that lets it go.
- `active`: Whether the port showed the press, read back as the field was let go. `false` means the press never reached the port.
- `frame_set`: The frame at which the field was pressed; `frame_released` is the frame at which it was let go.
- `port_before`: The port's value before the press. `port_held` is its value while pressed, and `mask` the field's bits in it.
- `verdict`: How the run of frames ended: `ELAPSED` when every frame asked ran, `OTHER_STOP` when a breakpoint or a watch stopped it first.
- `pending`: `true` when the script got no answer: the press has not happened, and may still happen when the console next runs a line.

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
- `emulated_after_s` (number or object)
- `emulated_before_s` (number or object)
- `active` (boolean or object)
- `cycles` (integer)
- `defvalue` (string)
- `drain_steps` (integer)
- `field` (string)
- `frame_after` (integer)
- `frame_before` (integer)
- `frame_release_planned` (integer)
- `frame_released` (integer)
- `frame_set` (integer)
- `frames` (integer)
- `instructions_completed` (integer)
- `lines_ahead` (integer)
- `mask` (string)
- `mode` (string)
- `name` (string)
- `pending` (boolean)
- `player` (integer)
- `polls` (integer)
- `port` (string)
- `port_before` (string)
- `port_held` (string or object)
- `reader_steps` (integer)
- `regpoint_hit` (object)
- `released` (boolean)
- `route` (string)
- `seen_bytes` (integer)
- `tagged_lines` (array)
- `value` (string)
- `verdict` (string)
- `watch_hit` (object)

</details>

### What it refuses

- A machine that is running (`not_stopped`).
- An empty `port` or `field`, or `frames` below 1 (`bad_argument`).
- A port the machine does not have, or a field that port does not have (`unknown_ref`).
- A machine with no screen, a vector display for one: the press is timed by counting frames (`no_channel`).
- More than 8 lines still waiting in the console (`bad_argument`).
- A script the console ran twice, which pressed the field twice, so the reply would describe neither press (`console_rerun`).
- A script that ran and logged no press: the field was not shown pressed (`readback_refused`).
- A time limit that ran out before the frames ran (`wait_expired`).
- A run that was not confirmed stopped: the field may still be pressed (`not_settled`).
- A console that died before it ran the script (`reader_died`).

### Why it works this way

An arcade board has no keyboard. Its coin slots, buttons and switches are named fields of input ports, so pressing a field by name works on any board.

A game that detects the edge of a press needs the field let go between two presses: two coins are two calls.

A press is play, not a write. It leaves `altered`, the mark that this session has written to the machine, as it was.

<details><summary>More on why</summary>

`seconds` covers the whole call: every run of frames and every wait for the console takes what is left of it.

Only one press waits at a time. A new `input` first lets go of a field an earlier call left pressed.

Before its own line the call steps the machine once for each line still waiting in the console (`lines_ahead`, `drain_steps`). The console's other counts are described under [`lua`](#lua).

`route` says which way the press went in: always `ioport` here, MAME's input ports. `name`, `player` and `defvalue` are what MAME says of the field: its name, its player and its value when not pressed.

The reply ends with what every stop returns, described in [Running and stopping](../../REFERENCE.md#running-and-stopping).

</details>

### Related tools

- [`drive`](sequences.md#drive)
- [`run_for`](run.md#run_for)
- [`scan`](scan.md#scan)
- [`watch_add`](breakpoints.md#watch_add)
- [`lua`](#lua)

<details><summary>The contract your client receives</summary>

```text
Press input `field` of `port` by name, hold it `frames` frames, release it, stop one frame
later. Needs the machine STOPPED (else `not_stopped`).

A non-zero `value` activates a digital field. `seconds` bounds the whole call. A press
leaves `altered` as it was; an edge-detecting game needs a release between presses: call
twice.

Reply, once answered: `verdict`, `frame_before`, `frame_after`, `port_before`, `frame_set`,
`released`, `frame_released`, `active` (read back at release), `name`, `mask`, `note`, the
stop survey. Without an answer, `pending`.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end input -->

<!-- scry-reference:begin lua -->
## `lua`

Run a Lua script inside MAME, with all of MAME's Lua interface, and get back what it prints.

```text
lua(script, seconds=5.0, read_only=false)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, stopped anywhere. The example session asks this late in a game.

Ask:

> Ask MAME itself which machine this is, with one line of Lua that only reads.

Call:

```text
lua(script="print(manager.machine.system.description)", read_only=true)
```

Reply, 6 of 20 fields:

```json
{
  "summary": "lua: 8 chars back, pc 0x0000fd82 after one step",
  "status": "ok",
  "evaluated_by": "one step",
  "pc_before": "0x0000fd80",
  "output": "Gridlee\n",
  "clipped": false
}
```

The script printed `Gridlee`, and only what it prints comes back. `evaluated_by` says the console needed one step of the machine to run the line, which is why the program counter moved on from `pc_before`.

<details><summary>The whole reply</summary>

```json
{
  "summary": "lua: 8 chars back, pc 0x0000fd82 after one step",
  "status": "ok",
  "script_chars": 41,
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "call": "MAME_MCP_LUA_END#39",
  "pc_before": "0x0000fd80",
  "thread_errors": 0,
  "console_reruns": 0,
  "output": "Gridlee\n",
  "clipped": false,
  "cause": "lua: one step",
  "stop_seq": 60,
  "pc": "0x0000fd82",
  "cpu": ":maincpu",
  "frame": 630,
  "regs": {
    "A": "0x00",
    "B": "0xd8",
    "D": "0x00d8",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xfd82",
    "S": "0x07f4",
    "CC": "0xd0",
    "DP": "0x00"
  },
  "instruction": {"address": "FD82", "bytes": "96B2", "text": "LDA    <$B2", "symbol": "irq", "delta": 2},
  "following": ["FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "... 9 more"],
  "errorlog": "<volatile>"
}
```

</details>

### Arguments

- `script` (string, required): The Lua to run: one chunk of at most 16000 characters. Only what it `print`s comes back; a `return` value does not.
- `seconds` (number (> 0, <= 600.0), default `5.0`): How long to wait for the console's answer, in real seconds, up to 600. Left out, 5.
- `read_only` (boolean, default `false`): `true` says the script only reads, and nothing checks it. Left out, the session is marked `altered`: written to by this session.

### What comes back

- `output`: What the script printed. Past 4000 characters it is cut: `clipped` is `true` and `output_path` names a file with all `output_chars` of it.
- `evaluated_by`: How the console came to run the script: `one step`, or more steps when other lines were waiting ahead of it.
- `pc_before`: The program counter before the step that ran the script; `pc` is where the machine stopped after it.
- `lines_ahead`: How many lines were waiting in the console before this one. The machine was stepped once for each.
- `console_reruns`: How many earlier scripts the console ran a second time during this call. One that wrote has written twice.

<details><summary>All 26 reply fields</summary>

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
- `clipped` (boolean)
- `evaluated_by` (string)
- `lines_ahead` (integer)
- `output` (string)
- `output_chars` (integer)
- `output_path` (string)
- `pc_before` (string)
- `pending` (boolean)
- `reader_steps` (integer)
- `regpoint_hit` (object)
- `script_chars` (integer)
- `seen_bytes` (integer)
- `watch_hit` (object)

</details>

### What it refuses

- A machine that is running (`not_stopped`).
- An empty script, or one over 16000 characters (`bad_argument`).
- More than 8 lines still waiting in the console: `run_for` one frame runs them (`bad_argument`).
- A script that fails to compile or raises, with the console's own `error:` text (`bad_argument`).
- No answer within `seconds`; a late answer shows in `log`, on the `process` log (`wait_expired`).
- A console that died before it ran the script; with `pending: true` the script may still run later (`reader_died`).

### Why it works this way

The other tools check what they did: `input`, `throttle`, `record`, `state_write`. `lua` is for what none of them does, and it promises less: nothing checks what the script changed, so the session is marked `altered` unless you say `read_only`.

The console runs a line only when the machine moves, so the call steps the machine once. The script reads the machine after the instruction at the stop has run. With lines waiting ahead it steps once for each, and the script reads the state after the last step.

The whole script is one chunk: a `local` on line 1 is seen on line 2, and a script that fails says so in the console's own words. Guard any callback you install with `pcall`, because its error does not come back to the call that installed it.

<details><summary>More on why</summary>

A callback's error goes elsewhere. A write tap's goes nowhere, and the tap keeps firing. A frame notifier's or a periodic callback's is a `[LUA ERROR]` line per call in `log`.

MAME's console is a plugin. `start` refuses a MAME that does not have it, before anything is launched.

`call` is the line that closes this call's output in the `process` log. When `seconds` runs out, the refusal says how many steps were taken, and a late answer shows in `log`, ending with that line.

MAME reads the console on a thread its own source calls unsafe: a step at the wrong moment can make it run the previous script again, or drop a line. Every reply that reads the console counts what happened:

- `lines_ahead`: lines waiting before this call's own. `drain_steps` or `evaluated_by` says how they were run first.
- `reader_steps`: extra steps given because the console had not picked the line up.
- `resent`: the console took the line and never ran it, so it was sent again. A second time is refused `reader_died`.
- `thread_errors`: how many times the console's reading thread died.
- `console_reruns`: earlier scripts run a second time. `altered` alone cannot say a write happened twice.
- `thread_errors`, `console_reruns` and `resent` are on every reply that read a script's answer back, zero included.
- Session totals sit under `session.console`. They grow when a call reads its answer back and once more at `close`, so a `throttle` asked while stopped adds none till then.

The tools that send a script of the server's own carry the same counts: `input`, `throttle`, `record`, `audio_record`, `screen_signature`, `screen_map_find` and `screen_map_write` with `method="add"`. [`debug`](write.md#debug) does not use this console: it talks to MAME's debugger.

A script of the server's own that raises is refused by its error. A port or field the machine lacks is `unknown_ref`, a recording with no screen `no_channel`, anything else `unexpected_answer`.

</details>

### Related tools

- [`debug`](write.md#debug)
- [`input`](#input)
- [`run_for`](run.md#run_for)
- [`log`](machine.md#log)
- [`state_write`](states.md#state_write)
- [`write`](write.md#write)

<details><summary>The contract your client receives</summary>

```text
Evaluate a Lua `script` on MAME's Lua console; prefer the typed wrappers. Needs the machine STOPPED (else `not_stopped`).

`script`: one chunk of at most 16000 characters; only what it `print`s comes back.
`seconds` bounds the console's answer. `read_only=True` declares it only reads, else the
session is marked ALTERED. More than
8 lines ahead in the pipe is refused. A chunk that fails to load or raises
is INVALID with the console's `error:`; `reader_died` means it had not run when the reader
died, and with `pending: true` it may still run on a later reader.

Reply: `output`, `clipped`, `output_path` (past 4000 characters), `evaluated_by`,
`pc_before`, `lines_ahead`, `console_reruns`, `note`, the stop survey.

Reference: REFERENCE.md, The console.
```

</details>
<!-- scry-reference:end lua -->

<!-- scry-reference:begin throttle -->
## `throttle`

Choose whether the machine runs at real speed or as fast as the host can.

```text
throttle(on, seconds=5.0)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, stopped at reset before anything has run. The example session then runs the game five seconds.

Ask:

> Turn real-speed throttling off so the game fast-forwards, then confirm the switch was applied.

Call:

```text
throttle(on=false)
```

Reply, 5 of 7 fields:

```json
{
  "summary": "throttle off: pending until the console next reads a line",
  "status": "ok",
  "on": false,
  "pending": true,
  "tag": "MAME_MCP_THROTTLE#1"
}
```

Then, once the game has run, look for the tag in MAME's log:

Call:

```text
log_wait(pattern="MAME_MCP_THROTTLE#1", channel="emulator")
```

Reply, 4 of 12 fields:

```json
{
  "summary": "log_wait emulator /MAME_MCP_THROTTLE#1/: matched already there",
  "status": "ok",
  "verdict": "TARGET",
  "line": "[luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=0"
}
```

`pending` means the switch waits for the machine to move, and `tag` is the text it writes to MAME's log once applied. The second call finds that line, `throttled=false`: `TARGET` means the pattern matched.

<details><summary>The two replies, whole</summary>

The first call's:

```json
{
  "summary": "throttle off: pending until the console next reads a line",
  "status": "ok",
  "on": false,
  "pending": true,
  "applies": "when the console next reads a line: a step, the next frame emulated, or a debugger command on a stub that refreshes after one",
  "tag": "MAME_MCP_THROTTLE#1",
  "confirmed_by": "its tag in the error log, read by the next stop's survey, by `status` and by `close`; `status` lists it in `throttles_pending` until then, and if the tag never comes, every reply after that says so in `session.throttles_not_applied`"
}
```

The second call's:

```json
{
  "summary": "log_wait emulator /MAME_MCP_THROTTLE#1/: matched already there",
  "status": "ok",
  "verdict": "TARGET",
  "pattern": "MAME_MCP_THROTTLE#1",
  "channel": "emulator",
  "line": "[luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=0",
  "already": true,
  "lines_total": 1,
  "lines_before": 4,
  "arrived_during": 0,
  "waited_s": "<volatile>",
  "lines_examined": 6
}
```

</details>

### Arguments

- `on` (boolean, required): `true` runs the machine at real speed; `false` fast-forwards it, as fast as the host can.
- `seconds` (number (> 0, <= 600.0), default `5.0`): With the machine running, how long to wait for the switch to be confirmed, in real seconds, up to 600. Left out, 5.

### What comes back

- `pending`: `true` when the switch is not applied yet: the machine is stopped, and the console runs the line when it next moves. `false` once applied.
- `tag`: The text the switch writes in MAME's log when it applies, `MAME_MCP_THROTTLE#n`. Give it to `log_wait` on the `emulator` log to wait for it.
- `on`: The setting asked for.
- `frame`: The frame at which the switch applied, and `waited_s` how long that took. Only when `pending` is `false`.
- `applies`: For a switch not applied yet, when it takes effect; `confirmed_by` says which later replies confirm it.

<details><summary>All 8 reply fields</summary>

- `applies` (string)
- `confirmed_by` (string)
- `frame` (integer)
- `on` (boolean)
- `pending` (boolean)
- `tag` (string)
- `tagged_lines` (array)
- `waited_s` (number)

</details>

### What it refuses

- A switch not confirmed within `seconds` on a running machine: it is still waiting, and `status` lists it (`wait_expired`).
- A machine that reports the other setting after the switch (`readback_refused`).

### Why it works this way

The switch is a line sent to MAME's console, and the console runs a line only when the machine moves. Asked on a stopped machine it cannot wait for its own confirmation, because nothing runs the line while it waits. The reply is `pending`, with the `tag` to look for.

So, stopped at a breakpoint, ask and then `resume`: the machine runs at the new speed from its first frame. A switch not applied yet is looked for again at the next stop, by `status` and by `close`. Until then `status` lists it in `throttles_pending`.

A switch that never took effect is not forgotten. When the console went past the line without applying it, or the machine reports the other setting, every later reply says so in `session.throttles_not_applied`, which stays set until `close`. Asking again fixes the speed and the record stays: this session measured at a speed nobody chose.

<details><summary>More on why</summary>

No call is refused over a switch that was not applied. The record is on every reply because the call that would report it is one nobody has to make. Until the console has gone past the line there is no record: the `pending` you were given is still true.

The console reads a line on a step, on the next frame emulated, or after a debugger command on a MAME build that refreshes after one. A machine that stops again before its next frame leaves the switch waiting.

The `tag` is text to search the log for, never a `mark`, which is a position in a log. Its number counts every line this session sent to the console, not the switches. `log_wait` takes a regular expression, so `#1` also matches `#10`.

`start`'s `throttle_from_frame` is the same switch decided at launch: fast-forward up to that frame, real speed after it.

`tagged_lines`, on a refusal, are the log lines that carry the tag.

</details>

### Related tools

- [`resume`](run.md#resume)
- [`log_wait`](machine.md#log_wait)
- [`status`](session.md#status)
- [`start`](session.md#start)
- [`run_for`](run.md#run_for)

<details><summary>The contract your client receives</summary>

```text
Switch real-speed throttling `on` or off; it applies when the console next reads a line.

Stopped, the reply is `pending: true` with a `tag` for `log_wait` on the `emulator`
channel. Running, it waits up to `seconds` for the tag; a bound that runs out is
`wait_expired`.

Reply: `on`, `pending`, `tag`; pending: `applies`, `confirmed_by`; applied: `frame`,
`waited_s`.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end throttle -->
