# The Lists tools

<!-- scry-reference:begin perform -->
## `perform`

*Run a sequence of steps*

```text
perform(steps, settle_seconds=30.0, summaries=false, until_frame=0)
```

Run a LIST of the server's own operations in order, in ONE round trip, stopping at the
first failure with the whole account.

Arguments: `steps`, a non-empty list, each `{"op": <tool name>, ...its arguments}`, any tool but
`start`, `close`, `rom_check`, `perform`, `drive` and `perform_export`. While the machine runs
only running-ok ops go on at once, and before the next console op the sequence WAITS up to
`settle_seconds` for the machine to stop.
`until_frame=F` (with `summaries` and a `run_for` step) repeats the list until a stop reads
frame F, within 5000 steps and 600 s: never a list you size; `no_channel`
with no frame counter.

A step's `recorded`, `{field: value}`, is what its reply must hold (a replay,
`perform_export`): else INVALID `diverged` there, with `field`, `recorded` and `got`.

Refused before the first step runs: the WHOLE list is checked (ops, argument names, types,
the values the tools refuse alone, each step's `cpu`, a bare hex ref whose table is known),
INVALID with `errors` listing EVERY refused step, nothing run. Anything else, at its step.

Reply: `ran` (each step's `op`, the `cpu` its reply names, and `reply`), `steps_completed`,
`held` (the steps held to their `recorded` answer), `failed_at` (unavailable on success); on a
step's refusal INVALID (`step_failed`) with `failed` (`op`, `reply`); once it waited, `verdict`:
`TARGET` (a list ending running adds `stopped`, the survey) or `TIMEOUT` (the steps after the
wait unsent, a `note`); with no wait, `not_stopped` before a console step, or `still_running`;
`until_frame` and `frame_reached`. With several cpus, `visible_cpu` and `visible_cpu_kept`: the
list puts back the cpu it found, or its last `focus`'s.

Reference: REFERENCE.md, Sequences in one call.

| argument | type | default |
|---|---|---|
| `steps` | array of object | required |
| `settle_seconds` | number (>= 0, <= 600.0) | `30.0` |
| `summaries` | boolean | `false` |
| `until_frame` | integer | `0` |

- `summaries`: True keeps a long list readable (an argument of the call, never of a step): each step but the one the list ended on becomes a compact row (a failed one stays whole under `failed`); `ran` shows the first 24 (`truncated`, of `steps_total`), `ran_path` and `replies_path` hold all, and `stops` counts the stops.

| reply field | type |
|---|---|
| `errors` | array |
| `failed` | object |
| `failed_at` | integer or object |
| `field` | string |
| `got` | any |
| `held` | integer |
| `note` | string |
| `ran` | array |
| `ran_path` | string or object |
| `recorded` | any |
| `replies_path` | string or object |
| `steps_completed` | integer |
| `steps_total` | integer |
| `still_running` | boolean |
| `stopped` | object |
| `stops` | object |
| `truncated` | boolean |
| `verdict` | string |
| `frame_reached` | integer or object |
| `operations` | array |
| `until_frame` | integer |
| `visible_cpu` | string or object |
| `visible_cpu_kept` | object |

Example, from a live run:

```json
{
  "steps": [
    {
      "op": "registers"
    }
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
          "omitted": [
            "altering_writes",
            "console"
          ],
          "how": "call `status`"
        }
      }
    }
  ],
  "steps_completed": 1,
  "failed_at": {
    "available": false,
    "why": "no step failed"
  },
  "held": 0,
  "visible_cpu": ":maincpu",
  "visible_cpu_kept": {
    "before": ":maincpu",
    "after": ":maincpu",
    "restored": false
  }
}
```
<!-- scry-reference:end perform -->

**The visible cpu.** A list that alternates cpus does not leave the visible cpu moved: at its end, failed or not, it puts back the cpu visible before the first step (or the one the last `focus` read back) through the stub's `Hc`, which runs nothing. The put-back holds while the machine is stopped; a release makes the cpu it last stopped on visible again.

**Waiting.** A wait that ran out ends the list `TIMEOUT`, and so does a step whose own wait missed (a `log_wait` that timed out): the steps after it were built on what it waited for.

**Read `stops`, and `ran_path` for a long table.** A count assembled from a table cut to fit the reply comes out wrong and clean.

**`until_frame=F` is a window of frames whose length the program finds.** Every stop a watch makes inside the window takes a step without moving the frame, so the steps a window needs are its frames plus its stops, and the stops are the thing being measured; a list sized by guessing ends short with a smaller count that looks clean. The window is the frames before F: the call ends right after the first step whose stop reads F, even mid-list. It needs a `run_for` step, because `run_for` carries on past a watch's stop where `run_to` and `step` end at the first. A frame already reached is refused, and a stop with no frame ends the list INVALID `unexpected_answer`, since nothing says whether the window is over.

<!-- scry-reference:begin drive -->
## `drive`

*Drive an input and verify it*

```text
drive(act, expect="", seconds=null, pattern=".", limit=40, settle_seconds=30.0, summaries=false)
```

LOOK, ACT, VERIFY in one call: the way a browser is driven, for an arcade board. The
channel is the EMULATOR log (`error.log`: what the driver and this server's scripts
`logerror`). The waits inside report their progress.

The log is MARKED first; `act` (a list of steps in `perform`'s vocabulary, typically
`input`, `run_for`, `run_to`) runs with `perform`'s rules; with `expect` (a regex; empty
for none) the call then looks for a matching line since the mark, waiting up to `seconds`
(default 5, at most 600) only while the machine RUNS (at a stop the log
is read once); and `looked.emulator` is what landed since the mark, matching `pattern` (a
regex, as `log` takes it; NARROW it, since a chatty driver logs hundreds of lines per emulated
second) and cut to the LAST `limit` (1..400, default 40). `settle_seconds` is
`perform`'s, and
with an `expect` the act's TAIL does not wait for a stop (the verify is the wait), so a
trailing `resume` is answered within `seconds`. `seconds` with no `expect` is refused.

Reply: `act` (`ran`, `steps_completed`, `failed`, `failed_at`, `perform`'s tail, and with
`summaries` its `steps_total`, `truncated`, `ran_path`, `replies_path` and `stops`), `verify`
(`checked`: whether a check ran at all; `seen`, and `verdict` `TARGET` or `TIMEOUT`; `line`,
`lines_before`, `lines_total`, `waited_s`; `checked: false` with `why` when no `expect` was
given; `available: false` when `act.verdict` is `TIMEOUT`), and `looked.emulator`
(`lines_written`, `lines_total`, `truncated`, `lines`, `since_mark`, `pattern`). INVALID with
the same `act`, `verify` and `looked` when a step failed (`step_failed`), when a stopped machine
lacks the line (`wait_stopped`), and before anything ran, whichever argument or step was
refused (`bad_argument`; `unknown_ref`, with `cpu_tags` for a cpu). No screen in the look: a
still is `snapshot`, a number for it `screen_signature`.

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

- `summaries`: True keeps a long list readable (an argument of the call, never of a step): each step but the one the list ended on becomes a compact row (a failed one stays whole under `failed`); `ran` shows the first 24 (`truncated`, of `steps_total`), `ran_path` and `replies_path` hold all, and `stops` counts the stops.

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
    {
      "op": "run_for",
      "frames": 1,
      "seconds": 10.0
    }
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
          "cycles": 319450,
          "polls": 1,
          "cause": "the `gvblank` stop of the last frame asked",
          "stop_seq": 28,
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
          "dasm": [
            "0025F6: 51C8 FFFC           dbra    D0, $25f4",
            "0025FA: 4EB9 000F 24D0      jsr     $f24d0.l",
            "002600: 13FC 00D8 0020 351C move.b  #$d8, $20351c.l",
            "002608: 33FC 0007 0020 F772 move.w  #$7, $20f772.l",
            "002610: 1039 0020 351C      move.b  $20351c.l, D0"
          ],
          "errorlog": {
            "lines_total": 2,
            "truncated": false,
            "lines": [
              "[luaengine] MAME_MCP_THROTTLE#24 throttled=false frame=30",
              ""
            ],
            "mark": 66675
          },
          "session": {
            "alive": true,
            "running": false,
            "altered": true,
            "read_only_claims": 1,
            "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for  ... (349 characters)",
            "omitted": [
              "altering_writes",
              "console"
            ],
            "how": "call `status`"
          }
        }
      }
    ],
    "steps_completed": 1,
    "failed_at": {
      "available": false,
      "why": "no step failed"
    },
    "held": 0,
    "visible_cpu": ":maincpu",
    "visible_cpu_kept": {
      "before": ":maincpu",
      "after": ":maincpu",
      "restored": false
    }
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

The channel is the emulator log because an arcade board has no guest port.

<!-- scry-reference:begin perform_export -->
## `perform_export`

*Export the session as a replay*

```text
perform_export(dest, overwrite=false)
```

Write what this session did since its `start` to `dest` as `perform`'s own document, so an investigation becomes a bench: `uv run python -m scry_core.replay <dest>`, from this server's repository, plays it with no model and exits 0 when every step held. Answers in any state, a closed session's included.

Kept: what moved the machine, as steps (a reader that steps the guest included), and the
reads that are checks (`read_memory`, `read_block`, `registers`, `screen_signature`,
`golden_check`), each holding to what its reply said (`recorded`).
Dropped, each named with why: a refused call, any other read, a call that changes nothing in
the emulated machine. Cut, named: the first call no replay can place (a `resume`, whose run
stops inside a frame where no replay reaches, a wall-clock bound that ended a run, no reply, a
refusal after the machine moved, a machine found elsewhere than the call before left it, a
step that wrote a file the session named, past 5000 calls kept).

`dest` absolute or `~`-led, ending `.json`; refused if it is there unless `overwrite`. Reply: `path` (the file written), `steps`, `checks`, `dropped` (the last 40, each `call`, `op`, `why`) and `dropped_total`, `cut` (`call`, `op`, `why`, or unavailable) and `replay`, the runner's command line. `no_recording` before a `start` succeeded, after one was cancelled, or when no recorded call is a step a replay could take.

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

Example, from a live run:

```json
{
  "dest": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f12.json"
}
```

```json
{
  "summary": "perform_export: 43 steps, 7 checks, 41 dropped to $TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f12.json",
  "status": "ok",
  "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f12.json",
  "steps": 43,
  "checks": 7,
  "dropped": [
    {
      "call": 2,
      "op": "machine_map",
      "why": "a read the export does not check"
    },
    {
      "call": 3,
      "op": "cpu_info",
      "why": "a read the export does not check"
    },
    {
      "call": 4,
      "op": "symbols_find",
      "why": "a read the export does not check"
    },
    {
      "call": 8,
      "op": "disassemble",
      "why": "a read the export does not check"
    },
    {
      "call": 9,
      "op": "find",
      "why": "a read the export does not check"
    },
    {
      "call": 10,
      "op": "history",
      "why": "a read the export does not check"
    },
    "... 34 more"
  ],
  "dropped_total": 41,
  "cut": {
    "available": false,
    "why": "the recording kept every call a replay takes"
  },
  "replay": "uv run python -m scry_core.replay $TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f12.json"
}
```
<!-- scry-reference:end perform_export -->

Whatever ends a run, the clock or a breakpoint, stops the cpu at a place inside its frame that no replayed advance reaches, and every stop after it inherits the shift: that is why a `resume` ends the document. A `debug` line is a step whose printed answer is never held to; one that moved the machine holds to its stop like any advance. A `golden_check` over files dropped calls wrote is dropped too.

**Shaping a session for a bench.** Advance by `run_for`, `run_to` and `step`, which stop where the machine does on every run, and leave `resume` for the end. Leave `dest` empty. A Lua reader's step count follows the wall clock, so on a rare run its step lands elsewhere and the replay says so there.

**The document** carries the `start`'s arguments as given, host paths included (`--binary` and `--rompath` replace them). `needs.states` lists the saved states it loads and does not save, checked against `state_list` before anything plays; `needs.declarations` the breakpoints, watches and registerpoints held as the recorded `start` began, which the replay's lists are held to.
