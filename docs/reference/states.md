# The States tools

A saved state is the whole emulated machine as it stood at one instant, written to a file. `state_write` saves one under a name and loads it back, and `state_list` shows the ones in the session's state folder.

Loading a state replaces the machine, so it counts as a write. From then on the `session` block of every reply carries `altered`, which says this session has written to the machine.

<!-- scry-reference:begin state_list -->
## `state_list`

List the session's saved states, with the size of each and where it was saved.

```text
state_list()
```

### Try it

On Gridlee, a free ROM from mamedev.org, after a state was saved as `two_credits`. The example session gives `start` a `state_dir` of its own.

Ask:

> Which saved states does this session have?

Call:

```text
state_list()
```

Reply, 3 of 4 fields:

```json
{
  "summary": "state_list: 1 state in ./tmp/demos/tour/gridlee-states/sta/gridlee",
  "status": "ok",
  "state_dir": "./tmp/demos/tour/gridlee-states/sta/gridlee"
}
```

The summary counts one state, and `state_dir` is the folder it is in: `sta/gridlee` under the `state_dir` given to `start`.

<details><summary>The whole reply</summary>

```json
{
  "summary": "state_list: 1 state in ./tmp/demos/tour/gridlee-states/sta/gridlee",
  "status": "ok",
  "state_dir": "./tmp/demos/tour/gridlee-states/sta/gridlee",
  "states": [
    {
      "name": "two-credits",
      "path": "./tmp/demos/tour/gridlee-states/sta/gridlee/two-credits.sta",
      "bytes": "<volatile>",
      "frame": 543,
      "pc": "0x0000b502"
    }
  ]
}
```

</details>

### Arguments

Takes no argument.

### What comes back

- `state_dir`: The folder the states are in: `sta/<system>` under the `state_dir` given to `start`, or under the session's temporary folder, which `close` deletes.
- `states`: One row per `.sta` file: `name`, `path`, `bytes`, and the `frame` and `pc` it was saved at. A value not read is unavailable, with `why`.

<details><summary>All 2 reply fields</summary>

- `state_dir` (string)
- `states` (array)

</details>

### Why it works this way

The list is read from the folder, not from the machine, so it answers while the program runs.

`frame` and `pc` are known only for a state this session saved. A `.sta` from an earlier session has them unavailable, as a `load` of it reports.

A `.sta` that is no regular file (a link to nothing, a directory, a FIFO) has `bytes` unavailable too, its `why` saying what is there. So has one under a name no `load` reads, such as `Boss_1.sta` where a state is `boss-1`: its `why` says to rename it.

### Related tools

- [`state_write`](#state_write)
- [`start`](session.md#start)

<details><summary>The contract your client receives</summary>

```text
List the saved states of the session's state folder.

Reply: `state_dir`, `states` (each `name`, `path`, `bytes`, `frame`, `pc`; unavailable with
`why` when not read).

Reference: REFERENCE.md, Saved states.
```

</details>

### Built on

It stands on nothing in the emulator: it reads the state files.
<!-- scry-reference:end state_list -->

<!-- scry-reference:begin state_write -->
## `state_write`

Save the emulated machine to a file under a name, or load a saved one back.

```text
state_write(method, name)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped after two coins went in. The example session then plays on to the level card before it loads the state back.

Ask:

> Save the machine here under the name two_credits, so I can come back to it.

Call:

```text
state_write(method="save", name="two_credits")
```

Reply, 5 of 8 fields:

```json
{
  "status": "ok",
  "name": "two-credits",
  "path": "./tmp/demos/tour/gridlee-states/sta/gridlee/two-credits.sta",
  "frame": 543,
  "pc": "0x0000b502"
}
```

Later, with the game on its level card, the load:

Call:

```text
state_write(method="load", name="two_credits")
```

Reply, 5 of 19 fields:

```json
{
  "summary": "state_write load: two-credits, rom_check OK, verified True, frame 543, pc 0x0000b502",
  "rom_check": "OK",
  "verified": true,
  "saved": {"frame": 543, "pc": "0x0000b502"},
  "frame": 543
}
```

The name is kept as `two-credits`, saved at frame 543. The load puts the machine back at that frame: `verified` says it reads as it did at the save, and `rom_check` that the ROM still matches.

<details><summary>The two replies, whole</summary>

The first call's:

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "name": "two-credits",
  "path": "./tmp/demos/tour/gridlee-states/sta/gridlee/two-credits.sta",
  "bytes": "<volatile>",
  "frame": 543,
  "pc": "0x0000b502",
  "errorlog": "<volatile>"
}
```

The second call's:

```json
{
  "summary": "state_write load: two-credits, rom_check OK, verified True, frame 543, pc 0x0000b502",
  "status": "ok",
  "name": "two-credits",
  "path": "./tmp/demos/tour/gridlee-states/sta/gridlee/two-credits.sta",
  "rom_check": "OK",
  "verified": true,
  "saved": {"frame": 543, "pc": "0x0000b502"},
  "output": "State load attempted.  Please refer to window message popup for results.",
  "mark": "<volatile>",
  "taps_across": [
    {"ref": "film", "cpu": ":maincpu"}
  ],
  "cause": "stateload two-credits",
  "stop_seq": 28,
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
  "errorlog": "<volatile>"
}
```

</details>

### The two methods

| method | what it does |
|---|---|
| `save` | Writes the machine to a new file. It never overwrites one. |
| `load` | Replaces the machine with a saved one. Every later reply then carries `altered`: this session has written to the machine. |

### Arguments

- `method` (one of `"save"`, `"load"`, required): `save` or `load`, as above.
- `name` (string, required): The state's name, spelled as a file name is: `Boss_1` becomes `boss-1`. At most 64 characters, with at least one letter or digit.

### What comes back

- `path`: The state's file: `<name>.sta` in the state folder.
- `frame`: The frame the machine is at. On `save` it is the frame the file holds, kept with `pc` to check a later `load`.
- `verified`: On `load`: `true` when the machine reads as it did at the save. Unavailable, saying why, when nothing could prove the load.
- `saved`: On `load`: the `frame` and `pc` the save recorded. Unavailable for a state this session did not save.
- `rom_check`: On `load`: `OK` when the ROM still matches the `reference_rom` given to `start`. Unavailable when the session has none.
- `held`: Set when MAME held the save or load for a pending timer: one instruction was stepped to complete it, and this says where the machine stopped.

<details><summary>All 23 reply fields</summary>

- `bytes` (integer)
- `cpu` (string)
- `following` (array of string)
- `instruction` (StopInstruction)
- `differs` (object)
- `errorlog` (object)
- `frame` (integer or object)
- `held` (string)
- `mark` (object)
- `name` (string)
- `output` (string)
- `path` (string)
- `pc` (string)
- `regpoint_hit` (object)
- `regs` (object)
- `rom_check` (string or object)
- `saved` (object)
- `stop_seq` (integer)
- `system` (string)
- `taps_across` (array)
- `verified` (boolean or object)
- `watch_hit` (object)
- `watches` (array)

</details>

### What it refuses

- A machine that is running (`not_stopped`).
- A name with no letter or digit, or longer than 64 characters (`bad_argument`).
- A `save` under a name that already has a file (`bad_argument`).
- A `load` of a name with no state, or whose `.sta` is no regular file (`unknown_ref`).
- A `save` that leaves no file, a file that is not a MAME state, or a state of another machine, which `system` names (`readback_refused`).
- A `load` after which the ROM no longer matches, or the machine does not read as saved: `differs` gives the `cpu`, the `register`, and its `saved` and `loaded` values (`readback_refused`).
- A save or load MAME still holds after one instruction: it would land inside the next run (`not_settled`).

### Why it works this way

MAME's console refuses a bad state in silence: a damaged file and another machine's state both come back as attempted, with nothing in the log. So the file's header is checked before the console sees it, and after a load the machine is compared with what the save recorded.

`verified` is `true` only when that comparison could tell a load from no load. For a state this session did not save, or a machine that already read as saved, it is unavailable and says why.

MAME can also hold a save or a load instead of running it, when a timer is pending on the stopped machine. Left alone it would run inside your next run, so the tool steps one instruction to complete it and says so in `held`.

<details><summary>More on why</summary>

Both methods use the debugger console's `statesave` and `stateload`, which work on a stopped machine. MAME is started with `-statename %g`, so the file is in `sta/<system>` whatever an ini file says.

A stopped machine gets a pending timer when a memory write runs a driver handler that synchronizes. On a MAME build that redraws the screen after a console command, a redraw that raises an input line does it too. Nothing can end the one step early: while a save or load is pending, MAME stops at no breakpoint or watchpoint.

A held save's `frame`, `pc` and registers are read after that step, so they are the file's, and `stop_seq` numbers the stop the step made.

MAME's emulated clock runs on across a load: it does not go back with the state.

A recording repeats from one saved state only on a driver whose game logic does not run while the screen is drawn. Logic run from the screen update depends on when the screen was last drawn, which a state does not hold, so `load` then `record` can give two different recordings. Compare such recordings against a tolerance.

`mark` is where each log ended as the load was sent, one position for `emulator` and one for `process`. `log` and `log_wait` take it as `since_mark` to read what came after. It is a position in the file, not a moment, so a line written before the load and not yet flushed lands after it.

A load is a stop of its own, with the readings every stop returns, described on the [Run](run.md) page. Its `errorlog` is the lines MAME's log gained (`lines_total`, `truncated`, `lines`, `mark`), not what the `log` tool reads. `taps_across` lists each count or capture that was running across the load, as [`reset`](write.md#reset) does.

</details>

### Related tools

- [`state_list`](#state_list)
- [`record`](captures.md#record)
- [`log`](machine.md#log)
- [`log_wait`](machine.md#log_wait)
- [`reset`](write.md#reset)
- [`rom_check`](session.md#rom_check)

<details><summary>The contract your client receives</summary>

```text
Save or load a savestate `name`, kept as a file name is (`Boss_1` is `boss-1`, at most
64 characters), through the debugger console. `method`: `save` or `load`, the
only two it takes. Needs the machine stopped.

`save`: write it, never overwriting. Reply: `name`, `path`, `bytes`, `frame`, `pc`,
`errorlog`, `held`, `stop_seq` (held for a timer).

`load`: restore it, altering the session; the header, the ROM and the stop are checked first.
Reply: `name`, `path`, `rom_check`, `verified` (true, or INVALID `readback_refused` with
`differs`), `saved`, `output`, `mark`, `held`, `taps_across` (a tap was live), and the stop
survey (`cause`, `stop_seq`, `cpu`, `pc`, `regs`, `frame`, `instruction`, `following`,
`errorlog`, `watches`, `watch_hit`, `regpoint_hit`).

Refused: a name with no letter or digit; `load` of a `.sta` that is no regular file
(`unknown_ref`).

Reference: REFERENCE.md, Saved states.
```

</details>

### Built on

It stands on MAME's own save states.
<!-- scry-reference:end state_write -->
