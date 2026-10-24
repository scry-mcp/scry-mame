# The States tools

`state_save` and `state_load` need no Lua: the debugger console has `statesave`/`stateload`, and they work stopped. The state lands under `sta/<system>/` (the launch pins `-statename %g`, MAME's own default, so an ini cannot move the folder).

**MAME refuses a bad state in silence from the console**: a corrupt header and another system's state both come back "attempted" with nothing in `error.log` or on stdout. So the header is judged before the console, and what the save recorded is compared after the load. What cannot be judged is said as unavailable with its reason, never as a word in the value's place. The emulated clock runs on across a `stateload` instead of coming back with the state.

**MAME can hold a save or a load instead of running it.** It refuses while an anonymous timer is pending and leaves the operation scheduled for the end of the next timeslice, which left alone is inside the caller's next run. A stopped machine gets such a timer when a memory write runs a driver write handler that synchronizes, or, on a stub that refreshes the display after a console command or write ([the console's contract](lua.md)), when the screen update raises an input line.

So `state_save`, `state_load` and a `statesave` or `stateload` typed through `debug` read `error.log` after the command, and when MAME held it they step ONE instruction through the stub's `s`, which refreshes nothing: the timer fires and the operation completes. Nothing can end that step first, because while an operation is pending MAME calls no cpu's debugger hook, so no breakpoint, watchpoint or step stops the machine. The reply says so in `held` (`debug`: in `note`), and a save's frame, pc and registers are read after the step, so they are the file's. MAME keeps ONE pending operation, so a `debug` line that held several completes only the last. An operation still held after the step is `not_settled`, because it would land in the next run.

**A recording repeats from one saved state only on a driver whose game logic does not run while the screen is drawn.** A driver that does its logic from `screen_update` depends on when the screen was last drawn, which is not part of the saved state, so `state_load` then `record` can give two different recordings. A recording compared as a regression check is made on a driver whose logic does not draw, or against a tolerance.

<!-- scry-reference:begin state_save -->
## `state_save`

*Save the machine state*

```text
state_save(name)
```

Write a savestate `name` (`[A-Za-z0-9_-]`, 1..64 characters) through the
debugger console (`statesave`), under the
session's state directory (`state_dir/sta`, or the scratch's), and CHECK the file: it
must appear and open with MAME's own magic. Never overwrites. A save that runs in the
command alters nothing; one MAME holds is completed by one instruction (REFERENCE.md,
Saved states).
Whether the driver restores everything it should is the driver's promise
(`MACHINE_SUPPORTS_SAVE`); `state_load` measures it with the ROM check, the frame and the
registers this records.
Needs the machine STOPPED (else `not_stopped`).

Reply: `name`, `path`, `bytes`, `frame`, `pc`, `errorlog` (what MAME logged meanwhile, as a
stop's survey carries it), and for a held save `held` (what was stepped, and where the
machine stopped) and `stop_seq`.

Reference: REFERENCE.md, Saved states.

| argument | type | default |
|---|---|---|
| `name` | string | required |

| reply field | type |
|---|---|
| `bytes` | integer |
| `errorlog` | object |
| `frame` | integer or object |
| `held` | string |
| `name` | string |
| `path` | string |
| `pc` | string |
| `stop_seq` | integer |
| `system` | string |

Example, from a live run:

```json
{
  "name": "m11"
}
```

```json
{
  "summary": "state_save m11: 111781 bytes at frame 30",
  "status": "ok",
  "name": "m11",
  "path": "$TMPDIR/mame-mcp-vr90lqz3/sta/radendur/m11.sta",
  "bytes": 111781,
  "frame": 30,
  "pc": "0x000e2cea",
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 66664
  }
}
```
<!-- scry-reference:end state_save -->

<!-- scry-reference:begin state_load -->
## `state_load`

*Load a machine state*

```text
state_load(name)
```

Restore the savestate `name` through the debugger console (`stateload`). It REPLACES
the machine, so the session is ALTERED. MAME refuses a bad state IN SILENCE, so the file's
header is judged first (magic, system name, this session's save signatures), the ROM is
checked again against `start`'s reference, and the stop is surveyed and compared with
what `state_save` recorded, the frame and pc and every register of every cpu the stub reads:
`verified` is true, or INVALID (`readback_refused`) naming the frame and pc or
carrying `differs` (`cpu`, `register`, `saved`, `loaded`), the stop it surveyed recorded all
the same. `verified` is `available: false` with its `why` for a state this session did not
write, a
machine that already read as the save BEFORE the load (equality after would prove nothing),
or a board with no frame counter and no readable register; with no reference image held
`rom_check` is unavailable with why. A `.sta` that is no regular file (a link to
nothing, a directory, a FIFO) is `unknown_ref`, never opened. Needs the machine STOPPED (else `not_stopped`).

Reply: `name`, `path`, `rom_check`, `verified`, `saved`, `output` (what the debugger console
printed for `stateload`, named as `debug` names it), `mark` (where each log channel ended as the load was sent: `log`/`log_wait`'s `since_mark` for that channel reads what came after it; a position in the file, not a moment, so a line written before the load and not yet flushed lands after), `held` when MAME held the load
and one instruction completed it (REFERENCE.md, Saved states), `taps_across` as `reset`'s,
then the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine); that `errorlog` runs from the last stop, the load's own lines included.

Reference: REFERENCE.md, Saved states.

| argument | type | default |
|---|---|---|
| `name` | string | required |

| reply field | type |
|---|---|
| `cpu` | string |
| `dasm` | array or object |
| `differs` | object |
| `errorlog` | object |
| `frame` | integer or object |
| `held` | string |
| `mark` | object |
| `name` | string |
| `note` | string |
| `output` | string |
| `path` | string |
| `pc` | string |
| `regpoint_hit` | object |
| `regs` | object |
| `rom_check` | string or object |
| `saved` | object |
| `stop_seq` | integer |
| `system` | string |
| `taps_across` | array |
| `verified` | boolean or object |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "name": "m11"
}
```

```json
{
  "summary": "state_load m11: rom_check OK, verified unavailable, frame 30, pc 0x000e2cea",
  "status": "ok",
  "name": "m11",
  "path": "$TMPDIR/mame-mcp-vr90lqz3/sta/radendur/m11.sta",
  "rom_check": "OK",
  "verified": {
    "available": false,
    "why": "the machine already read as the save before the load (the frame and pc where there is a counter, and every register block judged), so the load cannot be told from no load: a loop that comes back to the saved place reads the same"
  },
  "saved": {
    "frame": 30,
    "pc": "0x000e2cea"
  },
  "output": "State load attempted.  Please refer to window message popup for results.",
  "mark": {
    "emulator": 66664,
    "process": 87975
  },
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
  "cause": "stateload m11",
  "stop_seq": 26,
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
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 66664
  }
}
```
<!-- scry-reference:end state_load -->

<!-- scry-reference:begin state_list -->
## `state_list`

*List the saved states*

```text
state_list()
```

Every state under this session's state folder (`sta/<system>` under the `state_dir`
given to `start`, or the scratch's), with its size and, for a state THIS session wrote,
the frame and pc `state_save` recorded; a state from an earlier session carries both
unavailable, as `state_load` reports it, and a `.sta` that is no regular file (a link to
nothing, a directory, a FIFO) `bytes` too, its `why` saying what is there. A reading of
a directory: answers while the machine runs.

Reply: `state_dir`, `states` (`name`, `path`, `bytes`, `frame`, `pc`, each unavailable with
its `why` when not read).

Reference: REFERENCE.md, Saved states.

Takes no argument.

| reply field | type |
|---|---|
| `state_dir` | string |
| `states` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "state_list: 0 states in $TMPDIR/mame-mcp-vr90lqz3/sta/radendur",
  "status": "ok",
  "state_dir": "$TMPDIR/mame-mcp-vr90lqz3/sta/radendur",
  "states": []
}
```
<!-- scry-reference:end state_list -->
