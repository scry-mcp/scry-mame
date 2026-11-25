# The Sequences tools

These tools run other tools of this server for you. `perform` runs a list of steps in one call, and `drive` runs a list and then checks that the program reacted. `perform_export` writes the session so far as a script that replays with no model.

A step is a tool call written as an object, such as `{"op": "run_for", "frames": 2}`. Every tool can be a step except `start`, `close`, `rom_check`, `window`, `promote` and the three on this page.

<!-- scry-reference:begin perform -->
## `perform`

Run a list of this server's tools in one call, in order, stopping at the first step that fails.

```text
perform(steps=null, path="", settle_seconds=30.0, summaries=false, until_frame=0)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, stopped with one coin in and a `scan` of the first 2 KB open.

Ask:

> Drop a second coin, let the game run two seconds, then keep only the scanned bytes that now hold 2.

Call:

```text
perform(steps=[… 3 items], settle_seconds=…)
```

Reply, 4 of 6 fields:

```json
{
  "summary": "perform: 3 steps completed",
  "steps_completed": 3,
  "failed_at": {"available": false, "why": "no step failed"},
  "held": 0
}
```

All three steps ran and none failed, so `failed_at` only says why it holds no number. `held` is 0 because no step carried `recorded` values to give again.

<details><summary>The whole reply</summary>

```json
{
  "summary": "perform: 3 steps completed",
  "status": "ok",
  "ran": [
    {
      "op": "input",
      "cpu": ":maincpu",
      "reply": {
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
        "errorlog": "<volatile>",
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      },
      "frame_before": 419,
      "frame_after": 424
    },
    {
      "op": "run_for",
      "cpu": ":maincpu",
      "reply": {
        "summary": "run_for 2000 ms: ELAPSED, frame 424 to 543",
        "status": "ok",
        "verdict": "ELAPSED",
        "frame_before": 424,
        "frame_after": 543,
        "emulated_before_s": 7.180818,
        "emulated_after_s": 9.180819,
        "cycles": 2500002,
        "reads": "<volatile>",
        "cause": "the console's `gtime` stop",
        "stop_seq": 8,
        "pc": "0x0000b502",
        "cpu": ":maincpu",
        "frame": 543,
        "regs": {
          "A": "0x02",
          "B": "0x70",
          "D": "0x0270",
          "X": "0xda5c",
          "Y": "0x0101",
          "U": "0xab79",
          "PC": "0xb502",
          "S": "0x07fc",
          "CC": "0xa9",
          "DP": "0x00"
        },
        "instruction": {
          "address": "B502",
          "bytes": "26F4",
          "text": "BNE    $B4F8",
          "symbol": "write_sprites",
          "delta": 3340
        },
        "following": ["B504: DC 86    LDD    <$86", "B506: 8E DA 62 LDX    #$DA62", "B509: 10 A3 81 CMPD   ,X++", "B50C: 23 07    BLS    $B515", "B50E: 0C 81    INC    <$81", "B510: 8C DA 6A CMPX   #$DA6A", "... 9 more"],
        "errorlog": "<volatile>",
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      },
      "frame_before": 424,
      "frame_after": 543
    },
    {
      "op": "scan",
      "cpu": ":maincpu",
      "reply": {
        "summary": "scan filter: = 0x02, 11 left",
        "status": "ok",
        "operator": "=",
        "value": "0x02",
        "iterations": 1,
        "closed": false,
        "hits": [
          {"addr": "0x00000084", "value": "0x02"},
          {"addr": "0x000000da", "value": "0x02"},
          {"addr": "0x000000ed", "value": "0x02"},
          {"addr": "0x000000ef", "value": "0x02"},
          {"addr": "0x000001b6", "value": "0x02"},
          {"addr": "0x00000299", "value": "0x02"},
          "... 5 more"
        ],
        "hits_total": 11,
        "truncated": false,
        "cpu": ":maincpu",
        "space": "program",
        "names": [
          {"field": "hits[].addr", "number": "0x00000084", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x000000da", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x000000ed", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x000000ef", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x000001b6", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x00000299", "kind": "memory", "name": "spriteram"},
          "... 5 more"
        ],
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      },
      "frame_before": 543,
      "frame_after": 543
    }
  ],
  "steps_completed": 3,
  "failed_at": {"available": false, "why": "no step failed"},
  "held": 0
}
```

</details>

### Arguments

- `steps` (array of object, optional): The list to run: each step is `{"op": <tool>, ...}` with that tool's own arguments. Give this or `path`, never both.
- `path` (string, default `""`): A saved step list to replay in place of `steps`: a file under `.scry/perform/` or one `perform_export` wrote. Absolute, or starting with `~`.
- `settle_seconds` (number (>= 0, <= 600.0), default `30.0`): How long each wait for the program to stop may take, before a step that needs it stopped. 0 never waits; left out, 30 seconds.
- `summaries` (boolean, default `false`): `true` cuts each step's reply but the last to a short row and writes the full replies to a file. Left out, every reply comes back whole.
- `until_frame` (integer, default `0`): A frame number: the list repeats until a stop reads that frame. Needs `summaries` and a `run_for` step; left at 0, the list runs once.

### What comes back

- `ran`: One row per step that ran: its `op`, its `reply` and the `cpu` that reply names. With `summaries` a row adds its `step`, and `ran_path` and `replies_path` hold them all.
- `held`: How many steps carried `recorded`, the values a replayed step must give again, and gave them. 0 when no step carried any.
- `failed_at`: The step that failed, counted from 0, with its `op` and `reply` in `failed`. When none failed it is `available: false` with a `why`.
- `errors`: Every step refused before anything ran, each with its `step`, `op`, `code` and `message`.
- `verdict`: Comes once the list waited for a stop: `TARGET` with the stop in `stopped`, or `TIMEOUT` with a `note`. A list that waited for none says `still_running`.
- `stops`: With `summaries`, the server's own count of the stops: `stop_seq_first`, `stop_seq_last`, `surveyed` (how many a reply described), `by_cause` and `unaccounted`.

<details><summary>All 22 reply fields</summary>

- `errors` (array)
- `failed` (object)
- `field` (string)
- `got` (any)
- `ran_path` (string or object)
- `recorded` (any)
- `replies_path` (string or object)
- `steps_total` (integer)
- `still_running` (boolean)
- `stopped` (object)
- `stops` (object)
- `truncated` (boolean)
- `verdict` (string)
- `failed_at` (integer or object)
- `held` (integer)
- `ran` (array)
- `steps_completed` (integer)
- `frame_reached` (integer or object)
- `operations` (array)
- `until_frame` (integer)
- `visible_cpu` (string or object)
- `visible_cpu_kept` (object)

</details>

### What it refuses

- A step that names no tool, an argument its tool does not take or a value it refuses. Nothing runs, and `operations` lists the tools a step may name (`bad_argument`).
- A step's `cpu` the machine does not have, or a bare hex `ref` that names no symbol, also before anything runs (`unknown_ref`).
- Both `steps` and `path`, neither, or an empty list (`bad_argument`).
- A step that answers INVALID: the list ends there (`step_failed`).
- A step whose reply differs from its `recorded` values; the reply names the `field`, the `recorded` value and what it `got` (`diverged`).
- A step that needs the program stopped while it still runs and `settle_seconds` is 0 (`not_stopped`).
- `until_frame` without `summaries`, without a `run_for` step, or at a frame the program has already reached (`bad_argument`).
- `until_frame` on a machine with no screen device, which has no frame to count (`no_channel`).
- A stop that reads no frame under `until_frame`, since nothing then says whether the frame came (`unexpected_answer`).
- The emulator gone before a step could run (`session_broken`).

### Why it works this way

The whole list is checked before its first step runs, so a refusal never arrives after earlier steps changed the machine. What only a running step can know refuses at that step: a symbol against the table loaded by then, a file an earlier step writes.

A step that needs the program stopped waits up to `settle_seconds` for the stop. A wait that runs out ends the list `TIMEOUT`: the steps after it were built on what it waited for. So does a step whose own wait missed, a `log_wait` or `screen_wait` that timed out.

A step may carry `recorded`, a `{field: value}` object of its own reply, and a reply with other values ends the list. That turns a list into a test, and `perform_export` writes such lists from a session.

<details><summary>More on why</summary>

`until_frame` counts what happens before a frame when nobody can know how many steps that takes. Every stop a watch makes takes a step without moving the frame, so a list sized by guessing ends short, with a smaller count that looks right.

The call ends right after the first step whose stop reads the frame, even mid-list, and `frame_reached` says which. It needs a `run_for` step because `run_for` carries on past a watch's stop, where `run_to` and `step` end at the first.

On a running program the first stop starts the count. Running out of steps or seconds is a `TIMEOUT` that names the last frame read.

Every pass compares each step with its `recorded` values again, so a stop recorded on the first pass diverges on the second. A document `perform_export` writes carries no `until_frame`.

With `summaries`, `steps_total` counts the rows and `truncated` says the reply shows fewer. Read `stops` for a count and `ran_path` for the whole table: a count made by hand from cut rows comes out wrong and looks right.

On a machine with several cpus the list leaves the visible cpu, the one the debugger shows, as it found it. At its end, failed or not, it puts back the cpu visible before the first step, or the one the last `cpu_focus` step chose, running nothing. Once the program runs, the next stop decides.

`visible_cpu` is that cpu after the list, and `visible_cpu_kept` tells how it was kept: `before`, `asked`, `after`, `restored`, `moved_to`, and a `why` when it was not put back.

</details>

### Related tools

- [`drive`](#drive)
- [`perform_export`](#perform_export)
- [`run_for`](run.md#run_for)
- [`log_wait`](machine.md#log_wait)
- [`screen_wait`](run.md#screen_wait)

<details><summary>The contract your client receives</summary>

```text
A sequence of this server's operations in one call, in order, stopping at the first
failure; `drive` is this plus a wait for a line of the emulator log.

`steps`: `{"op": <tool>, ...}`, any tool but `start`, `close`, `rom_check`, `perform`,
`drive`, `perform_export`, `window`, `promote`. `path`: a `perform` document (absolute or `~`-led:
`.scry/perform/<name>.json`, or a file `perform_export` wrote) whose steps are replayed; give
`steps` or `path`, never both.
`until_frame=F` needs `summaries=True` (a window is hundreds of steps) and a `run_for` step, and repeats the list until a stop reads frame F, within 5000 steps and 600 s; `no_channel` if there is no frame counter. A step's `recorded`, `{field: value}` of its own reply,
must hold, else INVALID `diverged`. A refused step: INVALID `errors`, nothing run.
`settle_seconds` bounds each wait for a stop before a step that needs one (0: never wait).

Reply: `ran`, `steps_completed`, `held`, `failed_at`, `failed` (INVALID `step_failed`),
`verdict` (once the list waited; `TARGET` adds `stopped`, `TIMEOUT` `note`), else
`still_running`; `frame_reached` (with `until_frame`).

Reference: REFERENCE.md, Several calls as one.

summaries: True (of the call, never of a step) makes each step but the last a compact row; `ran` shows the first 24 (`truncated`), `ran_path` and `replies_path` hold all; `stops` counts the stops.
```

</details>
<!-- scry-reference:end perform -->

<!-- scry-reference:begin drive -->
## `drive`

Send an input as a list of steps, then check the program reacted by waiting for a new line in the log.

```text
drive(act, expect="", seconds=null, pattern=".", limit=40, settle_seconds=30.0, summaries=false)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, stopped in its attract mode five seconds after power-on.

Ask:

> Drop a coin and check the game counted it: wait for its coin counter line in the log.

Call:

```text
drive(act=[… 2 items], expect=…)
```

Reply, 2 of 5 fields:

```json
{
  "summary": "drive: reaction seen",
  "status": "ok"
}
```

The summary says a new log line matched `expect` after the coin went in. The line itself is under `verify` in the whole reply, with the lines `looked` kept.

<details><summary>The whole reply</summary>

```json
{
  "summary": "drive: reaction seen",
  "status": "ok",
  "act": {
    "ran": [
      {
        "op": "input",
        "cpu": ":maincpu",
        "reply": {
          "summary": "input :IN1 'Coin 1': held 4 frames, active True, released at frame 299",
          "status": "ok",
          "verdict": "ELAPSED",
          "frame_before": 295,
          "frame_after": 300,
          "emulated_before_s": 5.001233,
          "emulated_after_s": 5.085713,
          "cycles": 105600,
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
          "frame_set": 295,
          "released": true,
          "port_held": "0x000000ce",
          "frame_released": 299,
          "active": true,
          "cause": "the `gvblank` stop of the last frame asked",
          "stop_seq": 4,
          "pc": "0x0000fd80",
          "cpu": ":maincpu",
          "frame": 300,
          "regs": {
            "A": "0x00",
            "B": "0xfe",
            "D": "0x00fe",
            "X": "0x02db",
            "Y": "0xf2e6",
            "U": "0xbef1",
            "PC": "0xfd80",
            "S": "0x07f4",
            "CC": "0xd4",
            "DP": "0x00"
          },
          "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
          "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "... 9 more"],
          "errorlog": "<volatile>",
          "session": {
            "alive": true,
            "running": false,
            "altered": false,
            "omitted": ["altering_writes", "console"],
            "how": "call `status`"
          }
        },
        "frame_before": 295,
        "frame_after": 300
      },
      {
        "op": "run_for",
        "cpu": ":maincpu",
        "reply": {
          "summary": "run_for 2000 ms: ELAPSED, frame 300 to 419",
          "status": "ok",
          "verdict": "ELAPSED",
          "frame_before": 300,
          "frame_after": 419,
          "emulated_before_s": 5.085713,
          "emulated_after_s": 7.085713,
          "cycles": 2500000,
          "reads": "<volatile>",
          "cause": "the console's `gtime` stop",
          "stop_seq": 5,
          "pc": "0x0000a7d5",
          "cpu": ":maincpu",
          "frame": 419,
          "regs": {
            "A": "0x00",
            "B": "0x00",
            "D": "0x0000",
            "X": "0x0150",
            "Y": "0x00e1",
            "U": "0x00e3",
            "PC": "0xa7d5",
            "S": "0x07fe",
            "CC": "0x84",
            "DP": "0x00"
          },
          "instruction": {"address": "A7D5", "bytes": "2406", "text": "BCC    $A7DD", "symbol": "wait_frame", "delta": 420},
          "following": ["A7D7: EC A4    LDD    ,Y", "A7D9: AF A4    STX    ,Y", "A7DB: ED C4    STD    ,U", "A7DD: 33 A4    LEAU   ,Y", "A7DF: 31 3E    LEAY   -$2,Y", "A7E1: 11 93 80 CMPU   <$80", "... 8 more"],
          "errorlog": "<volatile>",
          "session": {
            "alive": true,
            "running": false,
            "altered": false,
            "omitted": ["altering_writes", "console"],
            "how": "call `status`"
          }
        },
        "frame_before": 300,
        "frame_after": 419
      }
    ],
    "steps_completed": 2,
    "failed_at": {"available": false, "why": "no step failed"},
    "held": 0
  },
  "verify": {
    "checked": true,
    "seen": true,
    "verdict": "TARGET",
    "expected": "coin counter on",
    "line": "[:] coin counter on",
    "lines_before": 4,
    "lines_total": 1,
    "waited_s": "<volatile>"
  },
  "looked": {
    "emulator": {
      "available": true,
      "since_mark": "<volatile>",
      "lines_written": 13,
      "lines_total": 11,
      "truncated": false,
      "lines": ["[luaengine] MAME_MCP_INPUT#3 set name=\"Coin 1\" player=0 mask=00000001 defvalue=00000001 port_before=000000cf frame=295", "[luaengine] MAME_MCP_INPUT#3 release frame=299 port_held=000000ce", "[:] coin counter on", "[:maincpu] ':maincpu' (FE4A): unmapped program memory read from 9020 & FF", "[:] coin counter off", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "... 5 more"],
      "pattern": "."
    }
  }
}
```

</details>

### Arguments

- `act` (array of object, required): The steps to run, in the shape `perform` takes: `{"op": <tool>, ...}`. Required, and never empty.
- `expect` (string, default `""`): A regular expression: the log line that shows the program reacted, waited for after the steps. Left out, nothing is checked and `verify` says `checked: false`.
- `seconds` (number (> 0, <= 600.0), optional): How long to wait for the `expect` line. Left out, 5 seconds; given without `expect`, the call is refused.
- `pattern` (string, default `"."`): A regular expression that picks which new log lines `looked` shows. It changes nothing in the check; left out, every line.
- `limit` (integer (>= 1, <= 400), default `40`): How many of those lines `looked` shows, the newest: 1 to 400. Left out, 40.
- `settle_seconds` (number (>= 0, <= 600.0), default `30.0`): As in `perform`. With `expect`, the last step's stop is not waited for: waiting for the line is the wait.
- `summaries` (boolean, default `false`): As in `perform`: `true` cuts each step's reply but the last to a short row.

### What comes back

- `act`: What the steps did, in the fields of a `perform` reply: `ran`, `steps_completed`, `failed_at` and the rest.
- `verify`: The check: `checked` says whether one ran and `seen` whether the line came, with the `line`, the `verdict` (`TARGET` or `TIMEOUT`) and `waited_s`.
- `looked`: Under `emulator`, the newest `lines` written since the steps began that match `pattern`, with `lines_total` and `truncated`.

<details><summary>All 4 reply fields</summary>

- `act` (object)
- `looked` (object)
- `operations` (array)
- `verify` (object)

</details>

### What it refuses

- `seconds` without `expect`, or an empty `act` (`bad_argument`).
- A bad step or argument in `act`, before anything runs; `operations` lists the tools a step may name (`bad_argument`).
- A step's `cpu` the machine does not have, answered with its `cpu_tags` (`unknown_ref`).
- A step that answers INVALID (`step_failed`).
- The program stopped at the debugger without the line: a stopped program logs nothing more, so waiting would not help (`wait_stopped`).
- A refusal of the steps themselves comes back with its own code, such as `not_stopped`, `session_broken` or `diverged`.

### Why it works this way

The log is marked once, before the first step, so a line written before the input is never taken for a reaction.

An arcade board has no debug port to write to, so the line is looked for in the emulator log: what MAME's driver and this server's scripts write with `logerror`. A driver that logs a lot fills it fast, so keep `pattern` narrow.

The reply holds no picture of the screen: `snapshot` takes one, and `screen_signature` gives a number for it. With no line to wait for, `perform` is the call to make.

<details><summary>More on why</summary>

`verify` also carries `expected`, `lines_before` and `lines_total`, and a `why` when no line came or nothing was checked. If the steps ran out their own wait, nothing is checked and it says `available: false`. `looked.emulator` adds `lines_written`, `since_mark` and `pattern`; `act` adds, with `summaries`, `steps_total`, `truncated`, `ran_path`, `replies_path` and `stops`.

</details>

### Related tools

- [`perform`](#perform)
- [`input`](lua.md#input)
- [`log_wait`](machine.md#log_wait)
- [`log`](machine.md#log)
- [`snapshot`](captures.md#snapshot)
- [`screen_signature`](screen.md#screen_signature)

<details><summary>The contract your client receives</summary>

```text
A sequence that also waits for a line of the emulator log: marks the log, runs `act`
(steps as in `perform`), then checks the log since the mark. With no line to wait for,
`perform` is the call.

`expect` (regex) waits up to `seconds` (default 5, at most 600)
for a matching line, only while the machine runs; `seconds` without `expect` is refused.
`settle_seconds` bounds each wait for a stop before a step that needs one (0: never wait).
`looked.emulator` is the last `limit` (1..400) lines matching `pattern`. A failed
step is INVALID `step_failed`; a stopped machine lacking the line, `wait_stopped`; a bad
`act` step or argument, `bad_argument` before anything ran. With no `expect`, `verify`
is `checked: false`.

Reply: `act`, `verify` (`checked`, `seen`, `verdict` `TARGET` or `TIMEOUT`, `line`,
`waited_s`), `looked` (`emulator`).

Reference: REFERENCE.md, Several calls as one.

summaries: True (of the call, never of a step) makes each step but the last a compact row; `ran` shows the first 24 (`truncated`), `ran_path` and `replies_path` hold all; `stops` counts the stops.
```

</details>
<!-- scry-reference:end drive -->

<!-- scry-reference:begin perform_export -->
## `perform_export`

Write the session's calls since `start` as a script that replays them and checks their answers, with no model.

```text
perform_export(dest, overwrite=false)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, in a session that dropped two coins and read the credits.

Ask:

> Save what we did in this session as a script that replays and checks it without you.

Call:

```text
perform_export(dest="./tmp/demos/tour/two-coins.json")
```

Reply, 6 of 10 fields:

```json
{
  "path": "./tmp/demos/tour/two-coins.json",
  "steps": 9,
  "checks": 3,
  "dropped_total": 15,
  "cut": {"available": false, "why": "the recording kept every call a replay takes"},
  "kept": "2 saved for `promote`; perform/two-coins, start/gridlee: not ... (185 characters)"
}
```

Nine calls replay, three of them as checks, and 14 calls were left out. `cut` is unavailable because nothing ended the script early; `kept` says the script is now a candidate for `promote`.

<details><summary>The whole reply</summary>

```json
{
  "summary": "perform_export: 9 steps, 3 checks, 15 dropped to ./tmp/demos/tour/two-coins.json",
  "status": "ok",
  "path": "./tmp/demos/tour/two-coins.json",
  "steps": 9,
  "checks": 3,
  "dropped": [
    {"call": 1, "op": "status", "why": "a read the export does not check"},
    {"call": 2, "op": "machine_map", "why": "it changes nothing in the emulated machine"},
    {"call": 3, "op": "cpu_info", "why": "a read the export does not check"},
    {"call": 4, "op": "symbols_find", "why": "a read the export does not check"},
    {"call": 6, "op": "knowledge_find", "why": "a read the export does not check"},
    {"call": 7, "op": "disassemble", "why": "a read the export does not check"},
    "... 9 more"
  ],
  "dropped_total": 15,
  "cut": {"available": false, "why": "the recording kept every call a replay takes"},
  "replay": "uv run python -m scry_core.replay ./tmp/demos/tour/two-coins.json",
  "kept": "2 saved for `promote`; perform/two-coins, start/gridlee: nothing this session read names its repository: promote(dry_run=true, root=<the repository>) lists what an approval would create"
}
```

</details>

### Arguments

- `dest` (string, required): The `.json` file to write, required: absolute, or starting with `~`. Refused when it exists, unless `overwrite`.
- `overwrite` (boolean, default `false`): `true` replaces a `dest` that is already there. Left out, an existing file is refused.

### What comes back

- `steps`: How many calls the script replays; `path` is the file written.
- `checks`: How many of them compare a reading with its `recorded` values, the answer the session got.
- `dropped`: The last 40 calls left out (reads the script does not check, refused calls, calls that change nothing), each with its `call`, `op` and `why`; `dropped_total` counts all.
- `cut`: The call the script ends before, with its `call`, `op` and `why`. It is `available: false` when every call a replay can run was kept.
- `replay`: The command that [replays the script](../../REFERENCE.md#from-a-session-to-a-test-that-replays-itself), run from this server's repository. It exits 0 when every step gave its `recorded` values again.
- `kept`: Says the script was saved as a candidate for `promote`: it reads "N saved for `promote`", and names a repository that has no `.scry/` folder yet.

<details><summary>All 8 reply fields</summary>

- `checks` (integer)
- `cut` (object)
- `dropped` (array)
- `dropped_total` (integer)
- `path` (string)
- `replay` (string)
- `steps` (integer)
- `kept` (string)

</details>

### What it refuses

- A `dest` that does not end in `.json`, is a directory, or exists without `overwrite` (`bad_argument`).
- No `start` that succeeded, one that was cancelled, or no call left that a replay could run (`no_recording`).

### Why it works this way

The script keeps the calls that move the program and a few readings as checks, each with the answer it got as `recorded`. A call that left the program at a new stop is checked on that stop's `pc` and `frame`.

The script ends at the first call no replay can reach. A `resume`, or a run that the clock or a `stop` ended, stops the cpu at a point inside its frame that no replayed run reaches. Every later stop would inherit the shift.

So move with `run_for`, `run_to` and `step`, which stop at the same point on every run, and keep `resume` for the end. Leave the `dest` of a step that writes a file empty: a file the session named is still there on replay, and the step is refused.

<details><summary>More on why</summary>

When the frames are known, `cut` says how many the run took, and a `run_for` of that many replays it up to that frame's start. The script also ends at a call with no reply, a refusal after the program moved, and a program found elsewhere than the call before left it.

A `debug` line is replayed and its printed answer never checked; one that moved the program is checked on its stop. An `image_compare(method="golden")` over files that dropped calls wrote is dropped too.

A reader that steps the program to read is kept as a step. How far a Lua reader steps follows the host's clock, so on a rare run it lands elsewhere and the replay says so at that step.

The script carries `start`'s arguments as given, host paths included; the replay's `--binary` and `--rompath` replace them. `needs.states` lists the saved states it loads and does not save, checked before anything plays. `needs.declarations` lists the breakpoints, watches and registerpoints saved when the recorded `start` began, which a replay must find again.

</details>

### Related tools

- [`perform`](#perform)
- [`promote`](project.md#promote)
- [`run_for`](run.md#run_for)
- [`run_to`](run.md#run_to)
- [`step`](run.md#step)
- [`state_write`](states.md#state_write)

<details><summary>The contract your client receives</summary>

```text
Write the session's calls since `start` to `dest` as a `perform` document.

Kept: moving calls and checks (`read_memory`, `read_block`, `registers`,
`screen_signature`, `screen_map_find`, `image_compare(method="golden")`), each held to its
`recorded` reply. Other calls drop; the first no replay can place, or past 5000, cuts
the rest.

`dest` (`.json`) is refused if present unless `overwrite`. Reply: `path`, `steps`,
`checks`, `dropped`, `dropped_total`, `cut`, `replay`, and `kept` when the document is kept
for `promote`; `no_recording` if empty.

Reference: REFERENCE.md, From a session to a test that replays itself.
```

</details>
<!-- scry-reference:end perform_export -->
