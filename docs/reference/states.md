# The States tools

`state_write(method="save")` and `state_write(method="load")` need no Lua: the debugger console has `statesave`/`stateload`, and they work stopped. The state lands under `sta/<system>/` (the launch pins `-statename %g`, MAME's own default, so an ini cannot move the folder).

**MAME refuses a bad state in silence from the console**: a corrupt header and another system's state both come back "attempted" with nothing in `error.log` or on stdout. So the header is judged before the console, and what the save recorded is compared after the load. What cannot be judged is said as unavailable with its reason, never as a word in the value's place. The emulated clock runs on across a `stateload` instead of coming back with the state.

**MAME can hold a save or a load instead of running it.** It refuses while an anonymous timer is pending and leaves the operation scheduled for the end of the next timeslice, which left alone is inside the caller's next run. A stopped machine gets such a timer when a memory write runs a driver write handler that synchronizes, or, on a stub that refreshes the display after a console command or write ([the console's contract](lua.md)), when the screen update raises an input line.

So `state_write(method="save")`, `state_write(method="load")` and a `statesave` or `stateload` typed through `debug` read `error.log` after the command, and when MAME held it they step ONE instruction through the stub's `s`, which refreshes nothing: the timer fires and the operation completes. Nothing can end that step first, because while an operation is pending MAME calls no cpu's debugger hook, so no breakpoint, watchpoint or step stops the machine. The reply says so in `held` (`debug`: in `note`), and a save's frame, pc and registers are read after the step, so they are the file's. MAME keeps ONE pending operation, so a `debug` line that held several completes only the last. An operation still held after the step is `not_settled`, because it would land in the next run.

**A recording repeats from one saved state only on a driver whose game logic does not run while the screen is drawn.** A driver that does its logic from `screen_update` depends on when the screen was last drawn, which is not part of the saved state, so `state_write(method="load")` then `record` can give two different recordings. A recording compared as a regression check is made on a driver whose logic does not draw, or against a tolerance.

<!-- scry-reference:begin state_list -->
## `state_list`

*List the saved states*

```text
state_list()
```

List the saved states of the session's state folder.

Reply: `state_dir`, `states` (each `name`, `path`, `bytes`, `frame`, `pc`; unavailable with
`why` when not read).

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
  "summary": "state_list: 0 states in $TMPDIR/mame-mcp-qwnd_9kr/sta/radendur",
  "status": "ok",
  "state_dir": "$TMPDIR/mame-mcp-qwnd_9kr/sta/radendur",
  "states": []
}
```
<!-- scry-reference:end state_list -->

A `.sta` from an earlier session carries `frame` and `pc` unavailable, as `state_write(method="load")` reports it; a `.sta` that is no regular file (a link to nothing, a directory, a FIFO) also has `bytes` unavailable, its `why` saying what is there. The state folder is `sta/<system>` under the `state_dir` given to `start`, or the scratch's. It is a reading of a directory, so it answers while the machine runs.

<!-- scry-reference:begin state_write -->
## `state_write`

*Save or load a machine state*

```text
state_write(method, name)
```

Save or load a savestate `name` (`[A-Za-z0-9_-]`, never `-` first, 1..64
characters) through the debugger console. Needs the machine stopped.

`save`: write it, never overwriting. Reply: `name`, `path`, `bytes`, `frame`, `pc`,
`errorlog`, `held`, `stop_seq` (held for a timer).

`load`: restore it, altering the session; the header, the ROM and the stop are checked first.
Reply: `name`, `path`, `rom_check`, `verified` (true, or INVALID `readback_refused` with
`differs`), `saved`, `output`, `mark`, `held`, `taps_across` (a tap was live), and the stop
survey (`cause`, `stop_seq`, `cpu`, `pc`, `regs`, `frame`, `instruction`, `following`,
`errorlog`, `watches`, `watch_hit`, `regpoint_hit`).

Refused: a name of another shape; `load` of a `.sta` that is no regular file
(`unknown_ref`).

Reference: REFERENCE.md, Saved states.

| argument | type | default |
|---|---|---|
| `method` | one of `"save"`, `"load"` | required |
| `name` | string | required |

| reply field | type |
|---|---|
| `bytes` | integer |
| `cpu` | string |
| `following` | array of string |
| `instruction` | StopInstruction |
| `differs` | object |
| `errorlog` | object |
| `frame` | integer or object |
| `held` | string |
| `mark` | object |
| `name` | string |
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
  "method": "save",
  "name": "m11"
}
```

```json
{
  "summary": "state_write save: m11, 111781 bytes at frame 30",
  "status": "ok",
  "name": "m11",
  "path": "$TMPDIR/mame-mcp-qwnd_9kr/sta/radendur/m11.sta",
  "bytes": 111781,
  "frame": 30,
  "pc": "0x000e2cea",
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 66664}
}
```
<!-- scry-reference:end state_write -->

`load` judges the header first, checks the ROM again and compares the stop with what `save` recorded. The `save` reply's `held` and `stop_seq` appear only for a save MAME held. A `save` writes the file and then checks it opens with MAME's own magic.

`mark` is where each log channel ended as the load was sent: `log`/`log_wait`'s `since_mark` for that channel reads what came after it. It is a position in the file, not a moment, so a line written before the load and not yet flushed lands after it.

The stop survey after a `load` is the one described in REFERENCE.md, Advancing the machine; its `errorlog` is not `log`.
