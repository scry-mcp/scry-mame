# The Lua tools

`debug` goes through the protocol's `monitor` escape; `lua` and the wrappers that run a script (`input`, `record`, `audio_record`, `throttle`, `screen_signature`, `map_add`, `map_find`) go through MAME's Lua console, `-console` over the process's standard input, which works with no terminal attached. The contract they share:

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

Press an input by NAME, as MAME names it, hold it for `frames` frames of the frame
counter and release it, then hand the machine back stopped one frame later. Reports its
progress while it waits.

Arguments: `port` (the tag, `:P1`), `field` (the field's name: `Coin 1`, `1 Player Start`,
`P1 Right`), `value` (an integer or a `0x` string; a digital field is active for any non-zero
value; an analog one takes a
value in its own range), `frames` (one or more), `seconds` (the wall-clock bound of the WHOLE
call: every run and every wait for the console inside it takes what is
left, and a run it has no room left for is `wait_expired`). A press is play, not a write: it
leaves `altered` as it was. A game that detects an
EDGE needs a release between two presses: call twice. Needs the machine STOPPED (else `not_stopped`); every wrapper but
`throttle` shares that.

Reply: the frame run's `verdict`, `frame_before`, `frame_after`, `cycles` and `polls`;
`lines_ahead`, `drain_steps` and `reader_steps` (the pipe, stepped off BEFORE this script
is sent, and the steps that cost), the
console's account (`thread_errors`, `console_reruns`, `resent`, its `note`: see `lua`);
`route` (`ioport`: set inside the machine), `port`, `field`, `value`, `frames`, `name`,
`player`, `mask`, `defvalue`, `port_before`, `frame_set`, `released`, `port_held`,
`frame_released`, `active` (the port READ BACK at the release: false when the press never
reached it); then the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine). A run another stop cuts
short leaves the field HELD and says so (`released: false`, `frame_release_planned`, a `note`).
A script the console ran twice is INVALID (`console_rerun`): the field was set twice.

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
| `dasm` | array or object |
| `errorlog` | object |
| `frame` | integer |
| `pc` | string |
| `regs` | object |
| `resent` | integer |
| `stop_seq` | integer |
| `thread_errors` | integer |
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
| `note` | string |
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
  "cycles": 638966,
  "polls": 2,
  "lines_ahead": 0,
  "drain_steps": 0,
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0E2CDC: 3239 0020 10C8 move.w  $2010c8.l, D1",
    "0E2CE2: 3001           move.w  D1, D0",
    "0E2CE4: 9079 0020 10C6 sub.w   $2010c6.l, D0",
    "0E2CEA: C1C3           muls.w  D3, D0",
    "0E2CEC: 48C0           ext.l   D0",
    "0E2CEE: 81C1           divs.w  D1, D0",
    "... 4 more"
  ],
  "errorlog": {
    "lines_total": 4,
    "truncated": false,
    "lines": [
      "[luaengine] MAME_MCP_INPUT#21 set name=\"Coin 1\" player=0 mask=00000400 defvalue=00000400 port_before=0000dfff frame=17",
      "",
      "[luaengine] MAME_MCP_INPUT#21 release frame=18 port_held=0000dbff",
      ""
    ],
    "mark": 66062
  }
}
```
<!-- scry-reference:end input -->

A field by NAME is the right shape for a board with no keyboard.

<!-- scry-reference:begin record -->
## `record`

*Record frames to an AVI*

```text
record(frames, dest="", seconds=60.0)
```

Record exactly `frames` frames of the screen to an AVI, bounded by the frame counter
(begun and ended by the machine's own frame notifier, so the count is emulated frames and
not wall time), then hand the machine back stopped. The file is CHECKED before its path
is given: a finished AVI whose header declares its frames, and zero frames is INVALID.
`dest` is an absolute path not there yet; empty lands in the scratch, which `close`
deletes. `seconds` is the wall-clock bound of the whole call, as `input`'s
is. Reports its progress while it waits. `frames` is 2 or more: the frame notifier cannot end a
recording on the call that begins it, so one frame is refused rather than recorded as two.
Needs the machine STOPPED (else `not_stopped`).

A run cut short leaves the recording OPEN (`ended: false`, `frame_end_planned`), or not begun
when cut before its first frame (`began: false`, `frame_begin_planned`), with a `note`. Lines
already in the console's pipe are stepped off before this script is sent, so the frames asked
for are the recording's own; `lines_ahead` says how deep the pipe was.

Reply: the frame run's `verdict`, `frame_before`, `frame_after`, `cycles` and `polls`;
`lines_ahead`, `drain_steps` and `reader_steps`, the console's own account (`thread_errors`,
`console_reruns`, `resent`, and a `note` when there is something to say: see
`lua`); `path`, `frames`, `began`, `frame_begin`, `recording_after`, `ended`, `bytes`,
`avi_frames`, `frame_end`, `view` (`start`'s); then the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine). A script the console ran
twice logs its own mark twice, and is `status: INVALID` (`console_rerun`) naming the
repeated marks: a recording begun twice on one file.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `frames` | integer | required |
| `dest` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `60.0` |

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
| `avi_frames` | integer or object |
| `began` | boolean |
| `bytes` | integer or object |
| `cycles` | integer or object |
| `drain_steps` | integer |
| `ended` | boolean |
| `frame_after` | integer |
| `frame_before` | integer |
| `frame_begin` | integer or object |
| `frame_begin_planned` | integer |
| `frame_end` | integer |
| `frame_end_planned` | integer |
| `frames` | integer |
| `instructions_completed` | integer |
| `lines_ahead` | integer |
| `mode` | string |
| `note` | string |
| `path` | string |
| `pending` | boolean |
| `polls` | integer |
| `reader_steps` | integer |
| `recording_after` | boolean or object |
| `regpoint_hit` | object |
| `tagged_lines` | array |
| `verdict` | string |
| `view` | string or object |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "frames": 2,
  "seconds": 10.0
}
```

```json
{
  "summary": "record: 2 frames, 666220 bytes at $TMPDIR/mame-mcp-vr90lqz3/snap/record-2.avi",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 19,
  "frame_after": 24,
  "cycles": 1597548,
  "polls": 5,
  "lines_ahead": 0,
  "drain_steps": 0,
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
  "path": "$TMPDIR/mame-mcp-vr90lqz3/snap/record-2.avi",
  "frames": 2,
  "began": true,
  "frame_begin": 20,
  "recording_after": true,
  "ended": true,
  "bytes": 666220,
  "avi_frames": 2,
  "frame_end": 21,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 24,
  "pc": "0x000e2cf0",
  "cpu": ":maincpu",
  "frame": 24,
  "regs": {
    "D0": "0x002d000d",
    "D1": "0x00000032",
    "D2": "0x000000fc",
    "D3": "0x0000008b",
    "D4": "0x0000000f",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x000000fc",
    "A1": "0x002088a0",
    "A2": "0x00203208",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00200fd8",
    "SP": "0x00200fcc",
    "PS": "0x2100",
    "PC": "0x000e2cf0"
  },
  "dasm": [
    "0E2CF0: 1180 9800      move.b  D0, (A0,A1.l)",
    "0E2CF4: 5242           addq.w  #1, D2",
    "0E2CF6: B47C 02FF      cmp.w   #$2ff, D2",
    "0E2CFA: 6FD4           ble     $e2cd0",
    "0E2CFC: 5379 0020 10C6 subq.w  #1, $2010c6.l",
    "0E2D02: 2079 0020 7990 movea.l $207990.l, A0",
    "... 2 more"
  ],
  "errorlog": {
    "lines_total": 6,
    "truncated": false,
    "lines": [
      "[luaengine] MAME_MCP_RECORD#22 armed frame=19 vblank=true",
      "",
      "[luaengine] MAME_MCP_RECORD#22 begin frame=20 recording=true",
      "",
      "[luaengine] MAME_MCP_RECORD#22 end frame=21",
      ""
    ],
    "mark": 66249
  },
  "view": "native"
}
```
<!-- scry-reference:end record -->

A `seconds` that would hold the server's lock past its ceiling is refused.

<!-- scry-reference:begin audio_record -->
## `audio_record`

*Record the sound to a WAV*

```text
audio_record(frames, dest="", seconds=60.0)
```

Record the sound of exactly `frames` frames to a WAV: the mixer's own output, the
speakers' input mix before any effect, begun and ended by the machine's frame notifier as
`record`'s AVI is, then hand the machine back stopped. The mixer writes in whole updates, so
the sound begins and ends up to one update off the frame edges. The file is CHECKED before
its path is given: a header that agrees with the file, the counter moved by exactly
`frames`, the emulated span `frames` frame periods, and the samples that span holds at the
header's rate, within one update. A span with no mixer update, a machine with no speaker,
or a mixer already recording (an ini naming `wavwrite`) is INVALID; silence is reported
(`sample_min` equals `sample_max`), never refused. `dest` is an absolute path not there
yet; empty lands in the scratch, which `close` deletes. `seconds` bounds the whole call.
`frames` is 2 or more. Needs the machine STOPPED (else `not_stopped`).

A run cut short leaves the recording OPEN (`ended: false`, `frame_end_planned`), or not begun
when cut before its first frame (`began: false`, `frame_begin_planned`), with a `note`. Lines
already in the console's pipe are stepped off first; `lines_ahead` says how deep it was.

Reply: the frame run's `verdict`, `frame_before`, `frame_after`, `cycles` and `polls`;
`lines_ahead`, `drain_steps`, `reader_steps` and the console's own account (see `lua`);
`path`, `frames`, `began`, `frame_begin`, `recording_after`, `ended`, `bytes`, `channels`,
`sample_rate_hz`, `samples` (per channel), `emulated_s`, `sample_min`, `sample_max`,
`frame_end`; then the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine). A script the console ran twice is INVALID
(`console_rerun`).

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `frames` | integer | required |
| `dest` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `60.0` |

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
| `began` | boolean |
| `bytes` | integer or object |
| `channels` | integer or object |
| `cycles` | integer |
| `drain_steps` | integer |
| `emulated_s` | number or object |
| `ended` | boolean |
| `frame_after` | integer |
| `frame_before` | integer |
| `frame_begin` | integer or object |
| `frame_begin_planned` | integer |
| `frame_end` | integer |
| `frame_end_planned` | integer |
| `frames` | integer |
| `instructions_completed` | integer |
| `lines_ahead` | integer |
| `mode` | string |
| `note` | string |
| `path` | string |
| `pending` | boolean |
| `polls` | integer |
| `reader_steps` | integer |
| `recording_after` | boolean or object |
| `regpoint_hit` | object |
| `sample_max` | integer or object |
| `sample_min` | integer or object |
| `sample_rate_hz` | integer or object |
| `samples` | integer or object |
| `tagged_lines` | array |
| `verdict` | string |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "frames": 2,
  "seconds": 10.0
}
```

```json
{
  "summary": "audio_record: 1920 samples at 48000 Hz x 2 at $TMPDIR/mame-mcp-vr90lqz3/snap/audio-3.wav",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 24,
  "frame_after": 30,
  "cycles": 1916822,
  "polls": 6,
  "lines_ahead": 0,
  "drain_steps": 0,
  "reader_steps": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
  "path": "$TMPDIR/mame-mcp-vr90lqz3/snap/audio-3.wav",
  "frames": 2,
  "began": true,
  "frame_begin": 25,
  "recording_after": true,
  "ended": true,
  "bytes": 7724,
  "channels": 2,
  "sample_rate_hz": 48000,
  "samples": 1920,
  "emulated_s": 0.039936,
  "sample_min": -10050,
  "sample_max": -6589,
  "frame_end": 26,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 25,
  "pc": "0x000e2cea",
  "cpu": ":maincpu",
  "frame": 30,
  "regs": {
    "D0": "0x0001000b",
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
    "SP": "0x00200fcc",
    "PS": "0x2100",
    "PC": "0x000e2cea"
  },
  "dasm": [
    "0E2CEA: C1C3           muls.w  D3, D0",
    "0E2CEC: 48C0           ext.l   D0",
    "0E2CEE: 81C1           divs.w  D1, D0",
    "0E2CF0: 1180 9800      move.b  D0, (A0,A1.l)",
    "0E2CF4: 5242           addq.w  #1, D2",
    "0E2CF6: B47C 02FF      cmp.w   #$2ff, D2",
    "... 4 more"
  ],
  "errorlog": {
    "lines_total": 6,
    "truncated": false,
    "lines": [
      "[luaengine] MAME_MCP_AUDIO#23 armed frame=24 vblank=true",
      "",
      "[luaengine] MAME_MCP_AUDIO#23 begin frame=25 ok=true recording=true time=0.51916800000000007 period=0.019968000000000003",
      "",
      "[luaengine] MAME_MCP_AUDIO#23 end frame=27 time=0.55910400000000005",
      ""
    ],
    "mark": 66415
  }
}
```
<!-- scry-reference:end audio_record -->

It ends one notifier call later than `record`'s script, so the span between its marks is `frames` frame periods of emulated time. The mixer writes in updates of a fiftieth of an emulated second, so the sound begins up to one update before the first frame and ends up to one before the last. The header is checked because MAME's writer checks none of its writes and writes both sizes only at close, so an open file reads 0 in both. Silence is a fact about the game, not a refusal: a constant level is silence to the ear whether zero or not. An open recording gains nothing while the machine stands at the debugger, since no mixer update runs there. 2 is the fewest `frames` that always holds an update on a screen under 100 Hz.

<!-- scry-reference:begin lua -->
## `lua`

*Evaluate Lua on the machine*

```text
lua(script, seconds=5.0, read_only=false)
```

Evaluate a Lua `script` on MAME's own Lua console (the whole scripting API). THE RAW
FORM: prefer the typed wrappers (`input`, `record`, `audio_record`, `throttle`, `state_save`,
`state_load`).

Arguments: `script`, ONE chunk of at most 16000 characters (a `local` on line 1 is seen
on line 2); only what it `print`s comes back, never a `return` value. `seconds`: the wait for
its answer. `read_only=True` is YOUR word that it only reads: without it the
call marks the session ALTERED, and nothing verifies the claim (`read_only_claims`).

It costs steps: the machine is stepped once per line still ahead in the console's pipe plus
its own, and the script reads the state after the last step (with nothing ahead, AFTER the
instruction at the stop's pc). More than
8 lines ahead is refused, naming `run_for` a frame to drain them. A chunk that
fails to load or raises is INVALID with the console's own `error:` words; `wait_expired` says
how many steps were taken, and a late answer lands in `log` (`process`); `reader_died` means
the script never ran. Needs the machine STOPPED (else `not_stopped`).

Guard the callbacks it installs with `pcall`: a write tap's error goes NOWHERE and the tap
keeps firing; a notifier's or periodic's is a `[LUA ERROR]` line per call in `log`
(`process`).

Reply: `script_chars`, `evaluated_by`, `lines_ahead`, `reader_steps`, `resent`,
`thread_errors` and `console_reruns` (the reader's deaths, and EARLIER chunks run twice: one
that wrote, wrote twice), `call` (a lost answer's sentinel in `log`), `pc_before`, `output`
and `clipped` (`output_chars`, `output_path` for a large one), a `note` (what the console
did, or nothing printed), then the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine).

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
| `dasm` | array or object |
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
| `note` | string |
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
  "reader_steps": 0,
  "call": "MAME_MCP_LUA_END#2",
  "pc_before": "0x000f2038",
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0,
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
  "dasm": [
    "0F2040: 4EB8 25DC                jsr     $25dc.w",
    "0F2044: 33FC D800 0020 351C      move.w  #$d800, $20351c.l",
    "0F204C: 4EB9 000F 24DE           jsr     $f24de.l",
    "0F2052: 23FC 000F 4414 0020 2EA4 move.l  #$f4414, $202ea4.l",
    "0F205C: 23FC 0000 4942 0020 2EA8 move.l  #$4942, $202ea8.l"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  }
}
```
<!-- scry-reference:end lua -->

<!-- scry-reference:begin throttle -->
## `throttle`

*Switch the throttle*

```text
throttle(on, seconds=5.0)
```

Switch real-speed throttling `on` or off at a PLACE: stopped at a breakpoint, ask for it
and `resume`, and the machine runs at real speed from its first frame. The switch is evaluated
when the Lua console next reads a line (a step, the next frame emulated, or a debugger command on a stub that refreshes after one), so on a STOPPED machine the reply
says `pending: true` and names the `tag` `log_wait` can wait for on the `emulator` channel. THE
TAG'S NUMBER IS THE SESSION'S CONSOLE SEQUENCE, shared with every call that sends the console a
line, so it counts nothing about throttles; and `log_wait` takes a regex, so close the digits
(`MAME_MCP_THROTTLE#1(?![0-9])`) or `#1` also matches `#10`. On a RUNNING machine the tool waits
up to `seconds` for the tag and reports the frame it applied at; one that
stops before its next frame leaves the switch pending as a stopped one does, and one whose
bound runs out is `wait_expired`, recorded all the same. `start`'s `throttle_from_frame` is the
same switch decided at launch.

A PENDING SWITCH IS COME BACK TO: the next stop's survey, `status` and `close` read the log
for its tag. One that arrives leaves `status`'s `throttles_pending`; one the console worked
past without writing puts a row in `session.throttles_not_applied` that REPEATS on every reply
afterwards, since a caller who never asks again would otherwise measure at a speed nobody
chose, and so does a machine reporting the OTHER setting (the running path's refusal
`readback_refused`).

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
