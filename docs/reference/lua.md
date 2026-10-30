# The Lua tools

[`debug`](write.md#debug) goes through the protocol's `monitor` escape; `lua` and the wrappers that run a script (`input`, [`record`](captures.md#record), [`audio_record`](captures.md#audio_record), `throttle`, [`screen_signature`](screen.md#screen_signature), [`screen_map_write`](read.md#screen_map_write) with `method="add"`, [`screen_map_find`](read.md#screen_map_find)) go through MAME's Lua console, `-console` over the process's standard input, which works with no terminal attached. The contract they share:

- **The console is a plugin** and `start` names its directory on the command line, because MAME's own default looks in its working directory and two builds given the same command line can boot and die respectively. A binary with the plugin in neither place `start` looks is refused before anything is spawned, because without it `-console` is fatal.
- **The console evaluates when its periodic hook runs**: once per frame while the machine runs, once per stop, and on a newer stub once per console command. So a line sent to a stopped machine waits in the pipe until the next step, frame or console command.
- **The hook reads one line each time it runs**, so a `throttle` asked while stopped leaves its line ahead and the step a script buys would evaluate the throttle and not the script. A wrapper therefore steps once for each line still ahead before its own, and says so (`lines_ahead`, `evaluated_by`).
- **The reader is a thread, and an unsafe one by MAME's own admission.** A step sent right after the line can land before the reader holds it, so an answer is given a short window and, while it does not come, one more step under a cap (`reader_steps`). A step landing while the reader unwinds kills it, after which the hook runs the previous chunk again or the line never runs. So every line written waits a moment before anything can move the machine, and a line the console took and never evaluated is sent again once (`resent`); twice is `reader_died`. Every reply that reads the console counts the deaths and reruns (`thread_errors`, `console_reruns`), because a chunk that wrote has then written twice and `altered` alone cannot say so.
- **A call's own chunk run again is invisible to the sentinels**, so `input`, `record` and `audio_record` count their own marks: one logged twice is `console_rerun`. A line with no answer and a reader death in the log is `reader_died` with `pending: true`: the script may still run on a later reader, so it stays ahead in the pipe and is not counted `lost`, a count kept for lines the echo proves eaten.
- **Every answer is framed by its own sentinel, never by the prompt.** Stdout is fully buffered and a script is free to print the prompt's bytes, so every call carries a sequence number in the chunk and in a sentinel line the chunk prints last with the outcome; the answer is what sits between them.
- **A whole script is one chunk under `pcall`**, because the console loads each line as its own chunk: a script that fails to compile or raises is refused in its own words, never read as a missing answer.

What the wrappers share beyond the console (evaluation, a run cut short, marks) is in [REFERENCE.md, Input and the screen](../../REFERENCE.md#input-and-the-screen).

<!-- scry-reference:begin input -->
## `input`

*Hold an input field*

```text
input(port, field, value=1, frames=4, seconds=30.0)
```

Press input `field` of `port` by name, hold it `frames` frames, release it, stop one frame
later. Needs the machine STOPPED (else `not_stopped`).

A non-zero `value` activates a digital field. `seconds` bounds the whole call. A press
leaves `altered` as it was; an edge-detecting game needs a release between presses: call
twice.

Reply, once answered: `verdict`, `frame_before`, `frame_after`, `port_before`, `frame_set`,
`released`, `frame_released`, `active` (read back at release), `name`, `mask`, `note`, the
stop survey. Without an answer, `pending`.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `port` | string | required |
| `field` | string | required |
| `value` | integer or string | `1` |
| `frames` | integer | `4` |
| `seconds` | number (> 0, <= 600.0) | `30.0` |

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
| `emulated_after_s` | number or object |
| `emulated_before_s` | number or object |
| `active` | boolean or object |
| `cycles` | integer |
| `defvalue` | string |
| `drain_steps` | integer |
| `field` | string |
| `frame_after` | integer |
| `frame_before` | integer |
| `frame_release_planned` | integer |
| `frame_released` | integer |
| `frame_set` | integer |
| `frames` | integer |
| `instructions_completed` | integer |
| `lines_ahead` | integer |
| `mask` | string |
| `mode` | string |
| `name` | string |
| `pending` | boolean |
| `player` | integer |
| `polls` | integer |
| `port` | string |
| `port_before` | string |
| `port_held` | string or object |
| `reader_steps` | integer |
| `regpoint_hit` | object |
| `released` | boolean |
| `route` | string |
| `seen_bytes` | integer |
| `tagged_lines` | array |
| `value` | string |
| `verdict` | string |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "port": ":P1",
  "field": "Coin 1",
  "frames": 1,
  "seconds": 10.0
}
```

```json
{
  "summary": "input :P1 'Coin 1': held 1 frame, active True, released at frame 18",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 17,
  "frame_after": 19,
  "emulated_before_s": 0.359425,
  "emulated_after_s": 0.39936,
  "cycles": 638966,
  "polls": 2,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":P1",
  "field": "Coin 1",
  "value": "0x00000001",
  "frames": 1,
  "name": "Coin 1",
  "player": 0,
  "mask": "0x00000400",
  "defvalue": "0x00000400",
  "port_before": "0x0000dfff",
  "frame_set": 17,
  "released": true,
  "port_held": "0x0000dbff",
  "frame_released": 18,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 23,
  "pc": "0x000e2cdc",
  "cpu": ":maincpu",
  "frame": 19,
  "regs": {
    "D0": "0x00000000",
    "D1": "0x00000032",
    "D2": "0x0000002e",
    "D3": "0x0000007b",
    "D4": "0x0000000f",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x0000002e",
    "A1": "0x00207996",
    "A2": "0x00203208",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00200fd8",
    "SP": "0x00200fcc",
    "PS": "0x2100",
    "PC": "0x000e2cdc"
  },
  "instruction": {
    "address": "0E2CDC",
    "bytes": "3239002010C8",
    "text": "move.w  $2010c8.l, D1",
    "symbol": "palette_range_table",
    "delta": 49610
  },
  "following": ["0E2CE2: 3001           move.w  D1, D0", "0E2CE4: 9079 0020 10C6 sub.w   $2010c6.l, D0", "0E2CEA: C1C3           muls.w  D3, D0", "0E2CEC: 48C0           ext.l   D0", "0E2CEE: 81C1           divs.w  D1, D0", "0E2CF0: 1180 9800      move.b  D0, (A0,A1.l)", "... 3 more"],
  "errorlog": {
    "lines_total": 4,
    "truncated": false,
    "lines": ["[luaengine] MAME_MCP_INPUT#21 set name=\"Coin 1\" player=0 mask=00000400 defvalue=00000400 port_before=0000dfff frame=17", "", "[luaengine] MAME_MCP_INPUT#21 release frame=18 port_held=0000dbff", ""],
    "mark": 66062
  }
}
```
<!-- scry-reference:end input -->

A field by NAME is the right shape for a board with no keyboard.

The reply ends with the stop survey (`cause`, `stop_seq`, `cpu`, `pc`, `regs`, `frame`, `dasm`, `errorlog`, `watches`, `watch_hit` or `regpoint_hit`), which every wrapper that advances the machine shares. `value` is an integer or a `0x` string; an analog field takes a value in its own range. `seconds` is the wall-clock bound of the whole call, so every run and every console wait inside it takes what is left. A press is play, not a write, hence `altered` is untouched. `lines_ahead`, `drain_steps`, `reader_steps`, `thread_errors`, `console_reruns`, `resent` are the console's account, described under `lua`. A script the console ran twice sets the field twice, which is why it is INVALID.

<!-- scry-reference:begin lua -->
## `lua`

*Evaluate Lua on the machine*

```text
lua(script, seconds=5.0, read_only=false)
```

Evaluate a Lua `script` on MAME's Lua console; prefer the typed wrappers. Needs the machine STOPPED (else `not_stopped`).

`script`: one chunk of at most 16000 characters; only what it `print`s comes back.
`read_only=True` declares it only reads, else the session is marked ALTERED. More than
8 lines ahead in the pipe is refused. A chunk that fails to load or raises
is INVALID with the console's `error:`; `reader_died` means the script never ran.

Reply: `output`, `clipped`, `output_path` (past 4000 characters), `evaluated_by`,
`pc_before`, `lines_ahead`, `console_reruns`, `note`, the stop survey.

Reference: REFERENCE.md, The console.

| argument | type | default |
|---|---|---|
| `script` | string | required |
| `seconds` | number (> 0, <= 600.0) | `5.0` |
| `read_only` | boolean | `false` |

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
| `clipped` | boolean |
| `evaluated_by` | string |
| `lines_ahead` | integer |
| `output` | string |
| `output_chars` | integer |
| `output_path` | string |
| `pc_before` | string |
| `pending` | boolean |
| `reader_steps` | integer |
| `regpoint_hit` | object |
| `script_chars` | integer |
| `seen_bytes` | integer |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "script": "print(1)",
  "read_only": true
}
```

```json
{
  "summary": "lua: 2 chars back, pc 0x000f2040 after one step",
  "status": "ok",
  "script_chars": 8,
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "call": "MAME_MCP_LUA_END#2",
  "pc_before": "0x000f2038",
  "thread_errors": 0,
  "console_reruns": 0,
  "output": "1\n",
  "clipped": false,
  "cause": "lua: one step",
  "stop_seq": 3,
  "pc": "0x000f2040",
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
    "PS": "0x2704",
    "PC": "0x000f2040"
  },
  "instruction": {
    "address": "0F2040",
    "bytes": "4EB825DC",
    "text": "jsr     $25dc.w",
    "symbol": "reset",
    "delta": 12
  },
  "following": ["0F2044: 33FC D800 0020 351C      move.w  #$d800, $20351c.l", "0F204C: 4EB9 000F 24DE           jsr     $f24de.l", "0F2052: 23FC 000F 4414 0020 2EA4 move.l  #$f4414, $202ea4.l", "0F205C: 23FC 0000 4942 0020 2EA8 move.l  #$4942, $202ea8.l"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14}
}
```
<!-- scry-reference:end lua -->

Typed wrappers exist for `state_write(method="save")` and `state_write(method="load")` too. The machine is stepped once per line still ahead in the console's pipe plus its own, and the script reads state after the last step (with nothing ahead, after the instruction at the stop's pc); over the limit, `run_for` a frame drains them. A `local` on line 1 is seen on line 2. Nothing verifies `read_only`. `wait_expired` says how many steps were taken and a late answer lands in `log` (`process`). Guard installed callbacks with `pcall`: a write tap's error goes nowhere and the tap keeps firing; a notifier's or periodic's is a `[LUA ERROR]` line per call in `log`. `console_reruns` counts the reader's deaths and earlier chunks run twice (one that wrote, wrote twice); `call` is a lost answer's sentinel in `log`; `output_chars` and `output_path` describe a large output; the stop survey is the one every advancing wrapper returns.

<!-- scry-reference:begin throttle -->
## `throttle`

*Switch the throttle*

```text
throttle(on, seconds=5.0)
```

Switch real-speed throttling `on` or off; it applies when the console next reads a line.

Stopped, the reply is `pending: true` with a `tag` for `log_wait` on the `emulator`
channel. Running, it waits up to `seconds` for the tag; a bound that runs out is
`wait_expired`.

Reply: `on`, `pending`, `tag`; pending: `applies`, `confirmed_by`; applied: `frame`,
`waited_s`.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `on` | boolean | required |
| `seconds` | number (> 0, <= 600.0) | `5.0` |

| reply field | type |
|---|---|
| `applies` | string |
| `confirmed_by` | string |
| `frame` | integer |
| `on` | boolean |
| `pending` | boolean |
| `tag` | string |
| `tagged_lines` | array |
| `waited_s` | number |

Example, from a live run:

```json
{
  "on": false,
  "seconds": 5.0
}
```

```json
{
  "summary": "throttle off: pending until the console next reads a line",
  "status": "ok",
  "on": false,
  "pending": true,
  "applies": "when the console next reads a line: a step, the next frame emulated, or a debugger command on a stub that refreshes after one",
  "tag": "MAME_MCP_THROTTLE#24",
  "confirmed_by": "its tag in the error log, read by the next stop's survey, by `status` and by `close`; `status` lists it in `throttles_pending` until then, and if the tag never comes, every reply after that says so in `session.throttles_not_applied`"
}
```
<!-- scry-reference:end throttle -->

**A throttle asked on a STOPPED machine cannot wait for its own tag**, because nothing reads its line while it would wait. The tag is a word in the log (`MAME_MCP_THROTTLE#n`), never a `mark`, which is only ever a position in a log.

**The `throttles_not_applied` row LATCHES** for a switch the console demonstrably worked past without writing, or a machine reporting the OTHER setting: a caller who does not ask again would never hear of it, and every timing they take meanwhile describes a speed nobody chose. Until the console has worked past the line there is no row, because the `pending` the caller was given is true. Asking again fixes the machine, but the row stays until the session ends: it is the record that this session measured at a speed nobody chose, and it rides on every reply while it holds, because the call that would naturally report it is one nobody is obliged to make. `status` lists a switch not yet applied (`throttles_pending`), so a success is a row leaving a list the caller can see.

Stopped at a breakpoint, ask and `resume`: the machine runs at real speed from its first frame. The console reads on a step, the next frame emulated, or a debugger command on a stub that refreshes after one. The tag's number is the session's console sequence, shared with every call sending the console a line, so it counts nothing about throttles; `log_wait` takes a regex, so unclosed digits (`#1`) also match `#10`. One that stops before its next frame stays pending. `start`'s `throttle_from_frame` is the same switch decided at launch. A pending switch is revisited by the next stop's survey, `status` and `close`; one that arrives leaves `throttles_pending`; one that does not puts the latching row described above (`readback_refused`).
