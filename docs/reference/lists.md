# The Lists tools

<!-- scry-reference:begin perform -->
## `perform`

*Run a sequence of steps*

```text
perform(steps=null, path="", settle_seconds=30.0, summaries=false, until_frame=0)
```

A sequence of this server's operations in one call, in order, stopping at the first
failure; `drive` is this plus a wait for a line of the emulator log.

`steps`: `{"op": <tool>, ...}`, any tool but `start`, `close`, `rom_check`, `perform`,
`drive`, `perform_export`. `path`: a `perform` document (absolute or `~`-led:
`.scry/perform/<name>.json`, or a file `perform_export` wrote) whose steps are replayed; give
`steps` or `path`, never both.
`until_frame=F` needs `summaries=True` (a window is hundreds of steps) and a `run_for` step, and repeats the list until a stop reads frame F, within 5000 steps and 600 s; `no_channel` if there is no frame counter. A step's `recorded`, `{field: value}` of its own reply,
must hold, else INVALID `diverged`. A refused step: INVALID `errors`, nothing run.
`settle_seconds` bounds each wait for a stop before a step that needs one (0: never wait).

Reply: `ran`, `steps_completed`, `held`, `failed_at`, `failed` (`step_failed`),
`verdict` (once the list waited; `TARGET` adds `stopped`, `TIMEOUT` `note`), else
`still_running`; `frame_reached` (with `until_frame`).

Reference: REFERENCE.md, Sequences in one call.

| argument | type | default |
|---|---|---|
| `steps` | array of object or null | `null` |
| `path` | string | `""` |
| `settle_seconds` | number (>= 0, <= 600.0) | `30.0` |
| `summaries` | boolean | `false` |
| `until_frame` | integer | `0` |

- `summaries`: True (of the call, never of a step) makes each step but the last a compact row; `ran` shows the first 24 (`truncated`), `ran_path` and `replies_path` hold all; `stops` counts the stops.

| reply field | type |
|---|---|
| `errors` | array |
| `failed` | object |
| `field` | string |
| `got` | any |
| `ran_path` | string or object |
| `recorded` | any |
| `replies_path` | string or object |
| `steps_total` | integer |
| `still_running` | boolean |
| `stopped` | object |
| `stops` | object |
| `truncated` | boolean |
| `verdict` | string |
| `failed_at` | integer or object |
| `held` | integer |
| `ran` | array |
| `steps_completed` | integer |
| `frame_reached` | integer or object |
| `operations` | array |
| `until_frame` | integer |
| `visible_cpu` | string or object |
| `visible_cpu_kept` | object |

Example, from a live run:

```json
{
  "steps": [
    {"op": "registers"}
  ],
  "settle_seconds": 2.0
}
```

```json
{
  "summary": "perform: 1 step completed",
  "status": "ok",
  "ran": [
    {
      "op": "registers",
      "cpu": ":maincpu",
      "reply": {
        "summary": "registers: 18 registers",
        "status": "ok",
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
        "register_bits": {
          "D0": 32,
          "D1": 32,
          "D2": 32,
          "D3": 32,
          "D4": 32,
          "D5": 32,
          "D6": 32,
          "D7": 32,
          "A0": 32,
          "A1": 32,
          "A2": 32,
          "A3": 32,
          "A4": 32,
          "A5": 32,
          "FP": 32,
          "SP": 32,
          "PS": 16,
          "PC": 32
        },
        "cpu": ":maincpu",
        "session": {
          "alive": true,
          "running": false,
          "altered": true,
          "read_only_claims": 1,
          "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for  ... (349 characters)",
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
    }
  ],
  "steps_completed": 1,
  "failed_at": {"available": false, "why": "no step failed"},
  "held": 0,
  "visible_cpu": ":maincpu",
  "visible_cpu_kept": {"before": ":maincpu", "after": ":maincpu", "restored": false}
}
```
<!-- scry-reference:end perform -->

**The visible cpu.** A list that alternates cpus does not leave the visible cpu moved: at its end, failed or not, it puts back the cpu visible before the first step (or the one the last `cpu_focus` read back) through the stub's `Hc`, which runs nothing. The put-back holds while the machine is stopped; a release makes the cpu it last stopped on visible again.

**Waiting.** A wait that ran out ends the list `TIMEOUT`, and so does a step whose own wait missed (a `log_wait` that timed out): the steps after it were built on what it waited for.

**Read `stops`, and `ran_path` for a long table.** A count assembled from a table cut to fit the reply comes out wrong and clean.

**`until_frame=F` is a window of frames whose length the program finds.** Every stop a watch makes inside the window takes a step without moving the frame, so the steps a window needs are its frames plus its stops, and the stops are the thing being measured; a list sized by guessing ends short with a smaller count that looks clean. The window is the frames before F: the call ends right after the first step whose stop reads F, even mid-list. It needs a `run_for` step, because `run_for` carries on past a watch's stop where `run_to` and `step` end at the first. A frame already reached is refused, and a stop with no frame ends the list INVALID `unexpected_answer`, since nothing says whether the window is over.

Before a console op the list waits up to `settle_seconds` for the machine to stop, and only running-ok ops go on while it runs. `visible_cpu` and `visible_cpu_kept` report the cpu the list put back. `summaries` is an argument of the call, never of a step. A step is any tool, with `op` plus its own arguments; the whole list is checked before the first step for ops, argument names, types, the values the tools refuse alone, each step's `cpu` and a bare hex ref whose table is known, and what only a step can judge refuses at that step. `recorded` is the field-to-value pairs a replay holds a reply to, and `perform_export` writes them. A step's reply row carries the `cpu` it names.

<!-- scry-reference:begin drive -->
## `drive`

*Drive an input and verify it*

```text
drive(act, expect="", seconds=null, pattern=".", limit=40, settle_seconds=30.0, summaries=false)
```

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

Reference: REFERENCE.md, Sequences in one call.

| argument | type | default |
|---|---|---|
| `act` | array of object | required |
| `expect` | string | `""` |
| `seconds` | number (> 0, <= 600.0) or null | `null` |
| `pattern` | string | `"."` |
| `limit` | integer (>= 1, <= 400) | `40` |
| `settle_seconds` | number (>= 0, <= 600.0) | `30.0` |
| `summaries` | boolean | `false` |

- `summaries`: True (of the call, never of a step) makes each step but the last a compact row; `ran` shows the first 24 (`truncated`), `ran_path` and `replies_path` hold all; `stops` counts the stops.

| reply field | type |
|---|---|
| `act` | object |
| `looked` | object |
| `operations` | array |
| `verify` | object |

Example, from a live run:

```json
{
  "act": [
    {"op": "run_for", "frames": 1, "seconds": 10.0}
  ],
  "settle_seconds": 2.0
}
```

```json
{
  "summary": "drive: no expectation",
  "status": "ok",
  "act": {
    "ran": [
      {
        "op": "run_for",
        "cpu": ":maincpu",
        "reply": {
          "summary": "run_for 1 frame: ELAPSED, frame 30 to 31",
          "status": "ok",
          "verdict": "ELAPSED",
          "frame_before": 30,
          "frame_after": 31,
          "emulated_before_s": 0.619011,
          "emulated_after_s": 0.638976,
          "cycles": 319450,
          "polls": 1,
          "cause": "the `gvblank` stop of the last frame asked",
          "stop_seq": 29,
          "pc": "0x000025f6",
          "cpu": ":maincpu",
          "frame": 31,
          "regs": {
            "D0": "0x0000b079",
            "D1": "0x00000032",
            "D2": "0x000001dc",
            "D3": "0x00000020",
            "D4": "0x0000000f",
            "D5": "0x00000000",
            "D6": "0x00000000",
            "D7": "0x00000000",
            "A0": "0x002048af",
            "A1": "0x0020829c",
            "A2": "0x00203208",
            "A3": "0x00000000",
            "A4": "0x00000000",
            "A5": "0x00000000",
            "FP": "0x00200fd8",
            "SP": "0x00200fc4",
            "PS": "0x2704",
            "PC": "0x000025f6"
          },
          "instruction": {
            "address": "0025F6",
            "bytes": "51C8FFFC",
            "text": "dbra    D0, $25f4",
            "symbol": "boot_init",
            "delta": 26
          },
          "following": ["0025FA: 4EB9 000F 24D0      jsr     $f24d0.l", "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l", "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l", "002610: 1039 0020 351C      move.b  $20351c.l, D0"],
          "errorlog": {
            "lines_total": 2,
            "truncated": false,
            "lines": ["[luaengine] MAME_MCP_THROTTLE#25 throttled=false frame=30", ""],
            "mark": 66675
          },
          "session": {
            "alive": true,
            "running": false,
            "altered": true,
            "read_only_claims": 1,
            "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for  ... (349 characters)",
            "omitted": ["altering_writes", "console"],
            "how": "call `status`"
          }
        }
      }
    ],
    "steps_completed": 1,
    "failed_at": {"available": false, "why": "no step failed"},
    "held": 0,
    "visible_cpu": ":maincpu",
    "visible_cpu_kept": {"before": ":maincpu", "after": ":maincpu", "restored": false}
  },
  "verify": {
    "checked": false,
    "why": "no `expect` given; the act's own steps carried whatever verification they asked for"
  },
  "looked": {
    "emulator": {
      "available": true,
      "since_mark": 66734,
      "lines_written": 0,
      "lines_total": 0,
      "truncated": false,
      "lines": [],
      "pattern": "."
    }
  }
}
```
<!-- scry-reference:end drive -->

An arcade board has no guest port, so the channel is the emulator log (`error.log`: what the driver and this server's scripts `logerror`). The log is marked before `act` runs, so only lines since the mark count. A chatty driver logs hundreds of lines per emulated second, hence the narrow `pattern`. With an `expect`, the act's tail does not wait for a stop because the verify is the wait, so a trailing `resume` is answered within `seconds`. `settle_seconds` and `summaries` are `perform`'s, with the same meaning. `act.verdict` `TIMEOUT` makes `verify` report `available: false`; with no `expect`, `verify` is `checked: false` with a `why`. `looked.emulator` also carries `lines_written`, `since_mark` and `pattern`. A still of the screen is `snapshot`, a number for it `screen_signature`; the look holds no screen. Refusals before anything ran also include `unknown_ref` with `cpu_tags` for a cpu. Reply `act` has `perform`'s tail, and with `summaries` its `steps_total`, `truncated`, `ran_path`, `replies_path` and `stops`.

<!-- scry-reference:begin perform_export -->
## `perform_export`

*Export the session as a replay*

```text
perform_export(dest, overwrite=false)
```

Write the session's calls since `start` to `dest` as a `perform` document.

Kept: moving calls and checks (`read_memory`, `read_block`, `registers`,
`screen_signature`, `screen_map_find`, `image_compare(method="golden")`), each held to its
`recorded` reply. Other calls drop; the first no replay can place, or past 5000, cuts
the rest.

`dest` (`.json`) is refused if present unless `overwrite`. Reply: `path`, `steps`,
`checks`, `dropped`, `dropped_total`, `cut`, `replay`, and `kept` when the document is kept
for `promote`; `no_recording` if empty.

Reference: REFERENCE.md, From an investigation to a bench.

| argument | type | default |
|---|---|---|
| `dest` | string | required |
| `overwrite` | boolean | `false` |

| reply field | type |
|---|---|
| `checks` | integer |
| `cut` | object |
| `dropped` | array |
| `dropped_total` | integer |
| `path` | string |
| `replay` | string |
| `steps` | integer |
| `kept` | string |

Example, from a live run:

```json
{
  "dest": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/jobs-scratch/A/f12.json"
}
```

```json
{
  "summary": "perform_export: 44 steps, 7 checks, 41 dropped to /var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/jobs-scratch/A/f12.json",
  "status": "ok",
  "path": "/var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/jobs-scratch/A/f12.json",
  "steps": 44,
  "checks": 7,
  "dropped": [
    {"call": 2, "op": "machine_map", "why": "a read the export does not check"},
    {"call": 3, "op": "cpu_info", "why": "a read the export does not check"},
    {"call": 4, "op": "symbols_find", "why": "a read the export does not check"},
    {"call": 8, "op": "disassemble", "why": "a read the export does not check"},
    {"call": 9, "op": "find", "why": "a read the export does not check"},
    {"call": 10, "op": "history", "why": "a read the export does not check"},
    "... 34 more"
  ],
  "dropped_total": 41,
  "cut": {"available": false, "why": "the recording kept every call a replay takes"},
  "replay": "uv run python -m scry_core.replay /var/folders/_2/sx7y70hj2kb1nqr6fpfrxsd40000gq/T/mame-live-matrix-<run>/jobs-scratch/A/f12.json"
}
```
<!-- scry-reference:end perform_export -->

Whatever ends a run, the clock or a breakpoint, stops the cpu at a place inside its frame that no replayed advance reaches, and every stop after it inherits the shift: that is why a `resume` ends the document. A `debug` line is a step whose printed answer is never held to; one that moved the machine holds to its stop like any advance. A `image_compare(method="golden")` over files dropped calls wrote is dropped too.

**Shaping a session for a bench.** Advance by `run_for`, `run_to` and `step`, which stop where the machine does on every run, and leave `resume` for the end. Leave `dest` empty. A Lua reader's step count follows the wall clock, so on a rare run its step lands elsewhere and the replay says so there.

**The document** carries the `start`'s arguments as given, host paths included (`--binary` and `--rompath` replace them). `needs.states` lists the saved states it loads and does not save, checked against `state_list` before anything plays; `needs.declarations` the breakpoints, watches and registerpoints held as the recorded `start` began, which the replay's lists are held to.

Cut calls are the first one no replay can place: a `resume`, a wall-clock bound that ended a run, a call with no reply, a refusal after the machine moved, a machine found elsewhere than the call before left it, a step that wrote a file the session named. A reader that steps the guest is kept as a step. Dropped: a refused call, any other read, a call that changes nothing in the emulated machine. The replay is `uv run python -m scry_core.replay <dest>`, from this server's repository, and exits 0 when every step held; the reply's `replay` is that command line. `dropped` shows the last 40 rows. `cut` is unavailable when nothing was cut. `no_recording` also covers a `start` that was cancelled.
