# The Breakpoints tools

These tools set breakpoints and watches and keep them. Each is saved as you named it, a symbol or an address, so the server sets it again at the next `start`, even after a rebuild moved the code.

The tools call a saved breakpoint or watch a declaration, as in `declaration_list`. The debugger holds what is set now; the saved breakpoints file holds what you asked for. What they share is in [REFERENCE.md, Breakpoints and watches](../../REFERENCE.md#breakpoints-and-watches).

A registerpoint (`regpoint` in the tool names) is MAME's stop when a condition on the registers comes true.

## What each state means

Every reply of these tools, and every row they list, carries a `state`.

| `state` | what it means |
|---|---|
| `armed` | Set in the debugger and able to fire. |
| `disabled` | The debugger lists it switched off. It does not fire until it is enabled there. |
| `evaluated` | A `show` or `expr` watch. Nothing is set in the debugger: the value is read at every stop. |
| `pending` | A `count` or `capture` watch sent to MAME and not installed yet. |
| `unresolved` | Its symbol, or a symbol its condition names, is not in this build. It stays saved and sets nothing until a build has it. |
| `null_pointer` | A watch through a pointer that reads zero. It stays saved and is looked up again at every stop. |
| `stale` | A raw address saved over another build: another ROM or symbol file. It stays saved and is not set until you declare it again. |
| `gone` | Saved, but the debugger no longer lists its row. |
| `aliased` | Another saved breakpoint holds the debugger's row at this address, so this one sets nothing. |

A row also says `inherited: true` when an earlier session saved it. `foreign` lists debugger rows the server did not set, such as one typed through `debug`: they are listed and never deleted.

<!-- scry-reference:begin breakpoint_at -->
## `breakpoint_at`

Set a breakpoint at a symbol or an address, to stop there or to count how often the code runs.

```text
breakpoint_at(ref, by="auto", role="stop", condition="", cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped with a credit in and the example session's symbol file loaded, which names the routine `take_credit`.

Ask:

> Stop the game where it takes a credit to start a game.

Call:

```text
breakpoint_at(ref="take_credit")
```

Reply, 6 of 12 fields:

```json
{
  "summary": "breakpoint_at take_credit: armed at 0x0000d676",
  "status": "ok",
  "role": "stop",
  "addr": "0x0000d676",
  "state": "armed",
  "entry": "3 @ D676"
}
```

Then press START, held for four frames:

Call:

```text
input(port=":IN1", field="1 Player Start", frames=4, seconds=300)
```

Reply, 5 of 40 fields:

```json
{
  "summary": "input :IN1 '1 Player Start': still HELD from frame 552, releases at 556",
  "verdict": "OTHER_STOP",
  "cause": "breakpoint take_credit at 0xd676",
  "pc": "0x0000d676",
  "frame": 553
}
```

The breakpoint is armed at `0xd676`. Pressing START ends in `OTHER_STOP`, a stop the call did not ask for: `cause` names the breakpoint on `take_credit`.

<details><summary>The two replies, whole</summary>

The first call's:

```json
{
  "summary": "breakpoint_at take_credit: armed at 0x0000d676",
  "status": "ok",
  "ref": "take_credit",
  "by": "symbol",
  "role": "stop",
  "cpu": ":maincpu",
  "stored": true,
  "while_running": false,
  "addr": "0x0000d676",
  "armed": true,
  "state": "armed",
  "entry": "3 @ D676"
}
```

The second call's:

```json
{
  "summary": "input :IN1 '1 Player Start': still HELD from frame 552, releases at 556",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 552,
  "frame_after": 553,
  "emulated_before_s": 9.343506,
  "emulated_after_s": 9.347718,
  "cycles": 5265,
  "polls": 2,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":IN1",
  "field": "1 Player Start",
  "value": "0x00000001",
  "frames": 4,
  "name": "1 Player Start",
  "player": 0,
  "mask": "0x00000004",
  "defvalue": "0x00000004",
  "port_before": "0x000000cf",
  "frame_set": 552,
  "released": false,
  "active": {
    "available": false,
    "why": "the field is still HELD: the port is read at its release, which the run has not reached"
  },
  "port_held": {
    "available": false,
    "why": "the field is still HELD: the port is read at its release, which the run has not reached"
  },
  "frame_release_planned": 556,
  "note": "the field is still HELD: the run stopped before the release frame, and the script releases it when the machine reaches it",
  "cause": "breakpoint take_credit at 0xd676",
  "stop_seq": 21,
  "pc": "0x0000d676",
  "cpu": ":maincpu",
  "frame": 553,
  "regs": {
    "A": "0xcb",
    "B": "0xff",
    "D": "0xcbff",
    "X": "0x0431",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xd676",
    "S": "0x07fc",
    "CC": "0xa8",
    "DP": "0x00"
  },
  "instruction": {"address": "D676", "bytes": "7A042B", "text": "DEC    $042B", "symbol": "take_credit", "delta": 0},
  "following": ["D679: 86 99    LDA    #$99", "D67B: BB 04 2C ADDA   $042C", "D67E: 19       DAA", "D67F: B7 04 2C STA    $042C", "D682: 39       RTS", "D683: 8E 04 31 LDX    #$0431", "... 10 more"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "credits_bcd",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables"
}
```

</details>

### Arguments

- `ref` (string, required): Where to break: a symbol or a `0x` address in the code. Never an expression.
- `by` (one of `"auto"`, `"symbol"`, `"address"`, default `"auto"`): How `ref` is read: `symbol` or `address` forces one. Left at `auto`, a `0x` ref is an address and anything else a symbol.
- `role` (one of `"stop"`, `"control"`, default `"stop"`): `stop` halts the machine there. `control` never halts: it counts each time the code runs, for `run_to` to read.
- `condition` (string, default `""`): For a `stop` only: a debugger expression that must hold for the stop, such as `d0==1`. Bare numbers are hex.
- `cpu` (string, default `""`): The cpu whose code holds the breakpoint. Left empty, the one the debugger is showing.

### What comes back

- `state`: `armed` once the debugger lists it enabled, `unresolved` while `ref` names no symbol of this build. The top of the page lists the rest.
- `entry`: The debugger's own row for the breakpoint, once armed.
- `addr`: The address `ref` resolves to, once it does.
- `stored`: `true` when the server saved the breakpoint. It is set again at the next `start`.
- `already_stored`: `true` when the same breakpoint was saved already, so the call changed nothing.
- `temp`: For a `control`, the debugger variable that counts its hits, `temp0` to `temp9`.

<details><summary>All 17 reply fields</summary>

- `addr` (string)
- `already_stored` (boolean)
- `armed` (boolean)
- `by` (string)
- `command_chars` (integer)
- `condition` (string)
- `condition_typed` (string)
- `cpu` (string)
- `entry` (string)
- `limit_chars` (integer)
- `ref` (string)
- `role` (string)
- `state` (string)
- `stored` (boolean)
- `temp` (string)
- `visible_cpu` (string)
- `while_running` (boolean)

</details>

### What it refuses

- A `ref` with a segment (`seg:off`): an address here is one `0x` number (`bad_argument`).
- A `condition` the debugger cannot evaluate, or one that holds `,`, `;`, braces or an assignment (`bad_argument`).
- A `condition` too long for one console command: `command_chars` and `limit_chars` say by how much (`bad_argument`).
- A `condition` on a `control`, which counts every hit (`bad_argument`).
- A cpu the machine does not have (`unknown_ref`).
- An address another saved breakpoint already holds, or the same `ref` under the other role or another condition (`ambiguous_ref`).
- An eleventh `control`: the debugger has ten variables to count with (`bad_argument`).
- A breakpoint the debugger took and does not list back: nothing is armed, and it stays saved as `gone` (`readback_refused`).

### Why it works this way

A `control` is for an address you know runs. `run_to` counts it beside its target, so a target never reached can be told from code that never ran. MAME counts the hits inside the debugger without halting, so a control costs a run nothing.

A `condition` makes one run out of many: "stop at the vblank handler once this variable reads X" is a single `resume`. It is saved as typed, like `ref`, so after a rebuild a symbol in it is compared where it now lives.

The condition is evaluated once before the breakpoint is set, because the debugger accepts a condition it cannot evaluate and that breakpoint never fires. A name that is both a symbol and a register of that cpu is refused as ambiguous.

<details><summary>More on why</summary>

- A breakpoint set while the machine runs fires at once. `while_running` says the machine was running when the call came.
- `run_to` saves its own `control` as one, so every later run counts it too.
- A stop no instruction caused (the end of a frame, a time, a step) lands on an instruction whose breakpoints some MAME builds skip. A `control` there misses that hit.
- A run by frames lands on one such instruction every frame, often the first of the vblank handler. Put a control somewhere else.
- `condition` is the condition as the debugger reads it, your symbols replaced by addresses. `condition_typed` is what you typed, when the two differ.
- The condition is evaluated on the breakpoint's own cpu: the server makes it the visible one for that and puts the visible one back, which runs nothing.
- If the visible cpu cannot be put back, the call is refused before anything is saved and `visible_cpu` names the cpu left visible (`unexpected_answer`).
- At `start`, a saved condition the debugger cannot evaluate is reported `unresolved` when it names a symbol this build lacks and `unarmable` otherwise. It stays saved either way.
- `cpu` is the cpu the breakpoint is on. `note` warns when the debugger is set to ignore that cpu: the breakpoint has no effect until `debug("observe <cpu>")`.
- Each row is armed naming its cpu, `bp <addr>:<cpu>`, which never changes the visible cpu, at `start`'s re-arm too. A saved row with no cpu is the first cpu's.
- A row the debugger already lists there on that cpu, under the same condition and held by no other declaration, is taken over, not doubled, here and at `start`'s re-arm.
- A row `bplist` shows without the condition sent is not armed: the call is refused, and `start`'s re-arm lists it `unarmable`. Watches follow the same rule.

</details>

### Related tools

- [`run_to`](run.md#run_to)
- [`declaration_list`](#declaration_list)
- [`declaration_clear`](#declaration_clear)
- [`regpoint_add`](#regpoint_add)
- [`watch_add`](#watch_add)
- [`symbols_find`](names.md#symbols_find)

<details><summary>The contract your client receives</summary>

```text
Declare an execution breakpoint at `ref`, a place in the code, as a `stop` or a `control`
(never halts; hits counted in a `temp`, 10 at most, read by `run_to`). Stored,
re-armed at `start`.

`ref`: a symbol or linear `0x` address, never an expression. `condition` (a `stop` only):
console grammar, bare numbers hex, no `,`, `;`, braces or assignment. `cpu`: else the
visible one.

Refused: a `seg:off`; a `condition` the console refuses or too long (`command_chars`); an
unknown cpu (`unknown_ref`); an address another declaration holds; one ref under the other
role; a control past the 10 temps.

Reply: `ref`, `stored`, `already_stored`, `armed`, `state`, `temp` (a control), `addr` (once
`ref` resolves), `entry` (once armed).

Reference: REFERENCE.md, Breakpoints and watches.
```

</details>
<!-- scry-reference:end breakpoint_at -->

<!-- scry-reference:begin regpoint_add -->
## `regpoint_add`

Stop the machine when a condition on the registers comes true, wherever the program is, to find who puts a value in a register.

```text
regpoint_add(condition, cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped at `take_credit`, the routine that takes a credit when START is pressed.

Ask:

> Stop as soon as register A holds 0x99.

Call:

```text
regpoint_add(condition="a==99")
```

Reply, 6 of 12 fields:

```json
{
  "summary": "regpoint_add a==99: armed, index 1",
  "status": "ok",
  "ref": "a==99",
  "state": "armed",
  "entry": "1 if a==99",
  "index": 1
}
```

Then run for one frame at most:

Call:

```text
run_for(frames=1, seconds=300)
```

Reply, 5 of 22 fields:

```json
{
  "summary": "run_for 1 frame: OTHER_STOP, frame 553 to 553",
  "verdict": "OTHER_STOP",
  "cause": "registerpoint 'a==99'",
  "pc": "0x0000d67b",
  "frame": 553
}
```

A bare number in a condition is hex, so `a==99` compares with 0x99. The run ends in `OTHER_STOP`, a stop it did not ask for, with `pc` at `0xd67b`.

<details><summary>The two replies, whole</summary>

The first call's:

```json
{
  "summary": "regpoint_add a==99: armed, index 1",
  "status": "ok",
  "ref": "a==99",
  "cpu": ":maincpu",
  "by": "expr",
  "condition": "a==99",
  "stored": true,
  "while_running": false,
  "armed": true,
  "state": "armed",
  "entry": "1 if a==99",
  "index": 1
}
```

The second call's:

```json
{
  "summary": "run_for 1 frame: OTHER_STOP, frame 553 to 553",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 553,
  "frame_after": 553,
  "emulated_before_s": 9.347726,
  "emulated_after_s": 9.347726,
  "cycles": 0,
  "polls": 1,
  "cause": "registerpoint 'a==99'",
  "stop_seq": 22,
  "pc": "0x0000d67b",
  "cpu": ":maincpu",
  "frame": 553,
  "regs": {
    "A": "0x99",
    "B": "0xff",
    "D": "0x99ff",
    "X": "0x0431",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xd67b",
    "S": "0x07fc",
    "CC": "0xa8",
    "DP": "0x00"
  },
  "instruction": {"address": "D67B", "bytes": "BB042C", "text": "ADDA   $042C", "symbol": "take_credit", "delta": 5},
  "following": ["D67E: 19       DAA", "D67F: B7 04 2C STA    $042C", "D682: 39       RTS", "D683: 8E 04 31 LDX    #$0431", "D686: C6 5F    LDB    #$5F", "D688: 6F 85    CLR    B,X", "... 10 more"],
  "errorlog": "<volatile>",
  "regpoint_hit": {
    "ref": "a==99",
    "condition": "a==99",
    "pc": "0x0000d67b",
    "note": "still armed: a registerpoint stops at every instruction where its condition holds, so the next advance stops again; `declaration_clear(kind=\"regpoint\")` removes it",
    "cpu": ":maincpu",
    "index": 1
  },
  "watches": [
    {
      "ref": "credits_bcd",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables"
}
```

</details>

### Arguments

- `condition` (string, required): The condition, in the debugger's own expression grammar, where a bare number is hex: `d1==0x7fff`. It compares and never assigns.
- `cpu` (string, default `""`): Only the cpu the debugger is showing, which is also what leaving it empty means. Another cpu is refused, naming `cpu_focus`.

### What comes back

- `state`: `armed` once the debugger lists it enabled. The top of the page lists the rest.
- `ref`: The condition as typed. `declaration_clear` takes it.
- `condition`: The condition as the debugger read it, your symbols replaced by their addresses.
- `entry`: The debugger's own row for the registerpoint.
- `index`: The debugger's row number for it.
- `already_stored`: `true` when the same registerpoint was saved already, so the call changed nothing.

<details><summary>All 13 reply fields</summary>

- `already_stored` (boolean)
- `armed` (boolean)
- `by` (string)
- `command_chars` (integer)
- `condition` (string)
- `cpu` (string or object)
- `entry` (string)
- `index` (integer)
- `limit_chars` (integer)
- `ref` (string)
- `state` (string)
- `stored` (boolean)
- `while_running` (boolean)

</details>

### What it refuses

- A condition the debugger cannot evaluate, or one that assigns or holds `,`, `;` or braces (`bad_argument`).
- A condition too long for one console command: `command_chars` and `limit_chars` say by how much (`bad_argument`).
- A `cpu` that is not the one the debugger is showing: `cpu_focus` first (`needs_call`).
- A condition that reads the same as another saved registerpoint's once symbols are replaced (`ambiguous_ref`).
- A MAME whose debugger has no `rpset` command (`no_channel`).
- A registerpoint the debugger took and does not list back: it stays saved as `gone` (`readback_refused`).

### Why it works this way

A registerpoint has no address, so it is never `stale` or `aliased` and has no `role`. `run_to` and `run_for` answer `OTHER_STOP`, a stop the run did not ask for, because a registerpoint is never a run's target.

It is evaluated after every instruction, so while the condition stays true it fires again one instruction later. The stop's `cause` reads `registerpoint '<ref>'`, and `regpoint_hit` holds the details.

The condition is evaluated once before it is saved, because the debugger accepts a registerpoint it cannot evaluate and that one never fires.

<details><summary>More on why</summary>

- It belongs to the cpu the debugger is showing, because MAME's `rpset` names no cpu. At `start` it is set again only if its cpu is then the visible one.
- At `start` each saved condition is evaluated again: `unresolved` when the debugger answers `unknown symbol`, otherwise `unarmable`. One that fails does not stop the others.
- Saving the same condition again takes over the debugger's existing row only on the visible cpu. The same text under another cpu compares other registers and is left `foreign`.
- It works while the machine runs and does not mark the session `altered`, which means written to.
- `rpset {<condition>}` typed through `debug` does not mark it either, but an action after the condition counts as a write.
- `by` is always `expr`, and `while_running` says the machine was running when the call came.

</details>

### Related tools

- [`breakpoint_at`](#breakpoint_at)
- [`cpu_focus`](session.md#cpu_focus)
- [`registers`](read.md#registers)
- [`declaration_list`](#declaration_list)
- [`declaration_clear`](#declaration_clear)
- [`watch_add`](#watch_add)

<details><summary>The contract your client receives</summary>

```text
Declare a registerpoint: the machine stops when `condition` comes true, wherever in the
program ("who puts this value in this register"). Stored, re-armed at `start`.

`condition`: console grammar, bare numbers hex (`d1==0x7fff`); compares, never assigns.
`cpu`: only the visible one; another is refused naming `cpu_focus`.

Refused: a condition the console refuses (`bad_argument`) or too long (`command_chars`,
`limit_chars`); one equal to another registerpoint's (`ambiguous_ref`); a debugger with no
registerpoints (`no_channel`).

Reply: `ref` (the condition as typed), `stored`, `already_stored`, `armed`, `state`,
`while_running`, `entry`, `cpu`, `note`.

Reference: REFERENCE.md, Breakpoints and watches.
```

</details>
<!-- scry-reference:end regpoint_add -->

<!-- scry-reference:begin watch_add -->
## `watch_add`

Keep a variable in view at every stop, stop the machine when it is written, or count every write to it, by name.

```text
watch_add(ref, mode, length=0, fmt="auto", by="auto", cpu="", condition="", trigger="",
    space="program", trigger_type="w")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped in its coin routine right after a coin was counted, with the example session's symbol file loaded.

Ask:

> Stop the game when the BCD copy of the credits is written, and tell me which instruction did it.

Call:

```text
watch_add(ref="credits_bcd", mode="change")
```

Reply, 6 of 19 fields:

```json
{
  "summary": "watch_add credits_bcd: change watch armed at 0x0000042c, 1 byte",
  "status": "ok",
  "reading": {"available": true, "value": 2, "raw_hex": "02"},
  "state": "armed",
  "entry": "1 @ 042C-042C write",
  "values_from": "memory"
}
```

Then run for one frame at most:

Call:

```text
run_for(frames=1, seconds=300)
```

Reply, 5 of 22 fields:

```json
{
  "summary": "run_for 1 frame: OTHER_STOP, frame 552 to 552",
  "verdict": "OTHER_STOP",
  "cause": "watch credits_bcd: 0x0000042c written by pc 0x0000b58c",
  "pc": "0x0000b58f",
  "frame": 552
}
```

`OTHER_STOP` is a stop the run did not ask for: here, the watch. The writer is at `0xb58c`; `pc` is the instruction after it, since the write has landed.

<details><summary>The two replies, whole</summary>

The first call's:

```json
{
  "summary": "watch_add credits_bcd: change watch armed at 0x0000042c, 1 byte",
  "status": "ok",
  "ref": "credits_bcd",
  "by": "symbol",
  "mode": "change",
  "length": 1,
  "fmt": "u8",
  "cpu": ":maincpu",
  "while_running": false,
  "addr": "0x0000042c",
  "reading": {"available": true, "value": 2, "raw_hex": "02"},
  "stored": true,
  "armed": true,
  "state": "armed",
  "index": 1,
  "entry": "1 @ 042C-042C write",
  "write_maps_to": "memory@0",
  "read_maps_to": "memory@0",
  "values_from": "memory"
}
```

The second call's:

```json
{
  "summary": "run_for 1 frame: OTHER_STOP, frame 552 to 552",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 552,
  "frame_after": 552,
  "emulated_before_s": 9.32817,
  "emulated_after_s": 9.32817,
  "cycles": 0,
  "polls": 1,
  "cause": "watch credits_bcd: 0x0000042c written by pc 0x0000b58c",
  "stop_seq": 20,
  "pc": "0x0000b58f",
  "cpu": ":maincpu",
  "frame": 552,
  "regs": {
    "A": "0x03",
    "B": "0xcf",
    "D": "0x03cf",
    "X": "0xe199",
    "Y": "0xf2e6",
    "U": "0x7acf",
    "PC": "0xb58f",
    "S": "0x07fc",
    "CC": "0x80",
    "DP": "0x00"
  },
  "instruction": {"address": "B58F", "bytes": "39", "text": "RTS", "symbol": "count_coin", "delta": 12},
  "following": ["B590: 96 F4    LDA    <$F4", "B592: 27 21    BEQ    $B5B5", "B594: 96 B3    LDA    <$B3", "B596: 84 07    ANDA   #$07", "B598: 26 1A    BNE    $B5B4", "B59A: 8E F6 59 LDX    #$F659", "... 7 more"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "credits_bcd",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "watch_hit": {
    "ref": "credits_bcd",
    "addr": "0x0000042c",
    "cpu": ":maincpu",
    "index": 1,
    "writes_total": 1,
    "truncated": false,
    "writer_pc": "0x0000b58c",
    "writes": [
      {"wrote": "0x03", "to": "0x0000042c", "pc": "0x0000b58c"}
    ],
    "values_from": "memory",
    "before": 2,
    "after": 3,
    "lines": ["Stopped at watchpoint 1 writing 03 to 042C (PC=B58C)"]
  }
}
```

</details>

### The five modes

| mode | what it does | stops? |
|---|---|---|
| `show` | Reads the value at every stop. | no |
| `change` | Stops when the bytes are written. | yes |
| `expr` | Evaluates one debugger expression at every stop. | no |
| `count` | Counts every write and which instruction made it. | no |
| `capture` | Logs a row per access, with the screen line being drawn and the time. | no |

### Arguments

- `ref` (string, required): What to watch: a symbol, a `0x` address, or an address reached through a pointer (`[base]+0x28`, `base->field`). For `expr`, the expression itself.
- `mode` (one of `"show"`, `"change"`, `"expr"`, `"count"`, `"capture"`, required): `show`, `change`, `expr`, `count` or `capture`, as above.
- `length` (integer, default `0`): Total bytes; not needed when `fmt` has a size or the symbol has a type. At most 128 for `show` and `capture`, 1024 for the others.
- `fmt` (string, default `"auto"`): How the bytes read: a scalar (`u8` to `f64`), an array (`u16[8]`), a string (`char[16]`) or a struct (`{x:i16,y:i16}`).
- `by` (one of `"auto"`, `"symbol"`, `"address"`, `"pointer"`, default `"auto"`): How `ref` is read: `symbol`, `address` or `pointer` forces one; `auto` lets the server choose.
- `cpu` (string, default `""`): The cpu whose memory is watched. Left empty, the one the debugger is showing.
- `condition` (string, default `""`): For `change` only: a debugger expression that must hold for the stop, where `wpdata` is the value written: `wpdata==0x7f`.
- `trigger` (string, default `""`): For `capture` only: the address whose every write takes a row holding the block at `ref`.
- `space` (one of `"program"`, `"io"`, default `"program"`): `io` watches a port instead of memory: `count` or `capture` only, and for this session only.
- `trigger_type` (one of `"w"`, `"r"`, `"rw"`, default `"w"`): `w` takes writes. On a `capture`, `r` takes reads of `ref` itself, with no `trigger`, `length` or `fmt`; on a `count`, `r` or `rw` counts reads too.

### What comes back

- `state`: `armed` for a `change` watch set in the debugger, `evaluated` for `show` and `expr`, `pending` for `count` and `capture`. The top of the page lists the rest.
- `reading`: What this call read at `ref`, on a stopped machine: `value` and `raw_hex`, or `available: false` with the reason, never a zero.
- `entry`: The debugger's own row for the watch, once armed.
- `stored`: The server saved the watch, and sets it again at `start`. `false` for a port watch.
- `installed`: `false` for a `count` or `capture` just sent: MAME installs it when its console next reads a line, and `pending` stays `true` until then.
- `values_from`: `bus` when the address does not read back what is written to it, as a write-only register: the values are then the writes logged, never a memory read.

<details><summary>All 35 reply fields</summary>

- `addr` (string)
- `already_stored` (boolean)
- `armed` (boolean)
- `by` (string)
- `call` (string)
- `condition` (string)
- `condition_typed` (string)
- `cpu` (string)
- `cpus_with_io` (array)
- `entry` (string)
- `fmt` (string)
- `index` (integer)
- `installed` (boolean)
- `length` (integer)
- `lines_ahead` (integer)
- `mine` (boolean)
- `mode` (string)
- `pending` (boolean)
- `pointer` (object)
- `read_maps_to` (string)
- `reading` (object)
- `ref` (string)
- `source` (object)
- `space` (string)
- `state` (string)
- `stored` (boolean)
- `tally_id` (string)
- `trigger` (string)
- `trigger_addr` (string)
- `trigger_maps_to` (string)
- `trigger_type` (string)
- `values_from` (string)
- `visible_cpu` (string)
- `while_running` (boolean)
- `write_maps_to` (string)

</details>

### What it refuses

- A `change` watch where nothing handles the write, such as the ROM copy of a variable (`bad_argument`).
- A `count` range that covers part of a bus word, such as a word at an odd address on a 16-bit bus (`bad_argument`).
- One `ref` under two modes, sizes, formats, conditions or triggers: clear the first (`ambiguous_ref`).
- A `change` watch that shares a byte with another armed one on the same cpu, or a `count` on a range already counted (`ambiguous_ref`).
- A pointer base or a `trigger` that names no symbol, or a cpu the machine does not have (`unknown_ref`).
- A watch through a pointer while the machine runs (`not_stopped`).
- A `count` or `capture` through a pointer, or a `capture` block with a handler inside it (`bad_argument`).
- A `length` over the mode's maximum, or none where neither `fmt` nor the symbol gives a size (`bad_argument`).
- `condition` on any mode but `change`, `trigger` on any mode but `capture`, and a write capture without one (`bad_argument`).
- On a port: `show`, `change`, `expr` or a count of reads, or a cpu with no io space (`bad_argument`).
- A `change` watch the debugger took and does not list back: nothing is saved (`readback_refused`).

### Why it works this way

A `change` watch answers "who wrote this byte". The write has landed when the machine stops, so the stop's `pc` is the instruction after the writer. The stop's `watch_hit` names the writer and each write since the previous stop.

`count` and `capture` exist for what a stop cannot give: every value a variable takes over a stretch, and who wrote each, while the program keeps running.

`state` says where the watch stands and `reading` what this call read, since a `change` watch is armed and read at the same stop. One `ref` carries one watch per cpu: another mode, size, format, condition or trigger under it is refused until cleared.

<details><summary>More on why</summary>

On every watch:

- An address matches in any spelling; a symbol and its address are two refs.
- A region is `memdump`'s job, which is why lengths are limited.
- With `fmt` left at `auto`, a typed symbol reads as its type, else as the widest unsigned scalar that divides `length`.
- Arming writes nothing to the machine, so the session is not `altered`.
- A watch set while the machine runs is armed at once and fires. Only a ref through a pointer needs a stop.
- `reading` holds `available`, then `value` and `raw_hex` (`value` and `hex` for an `expr`), or `why` when nothing could be read.

On `show` and `expr`:

- A watch on another cpu is read only on a MAME whose gdbstub reads every cpu. Otherwise its `reading` is `available: false`, and a watch through a pointer there is refused.
- Every `expr` is read in one `print` at each stop, so one more costs a stop nothing.
- An `expr` has no cpu, and takes no `,`, `;`, assignment, `length` or `fmt`.

On `change`:

- The writer comes from the debugger's own log line for the stop. A 68000 writes a long as two words, so one write lists as two.
- The debugger accepts a watchpoint on the ROM copy of a variable whose live copy is in RAM, and it never fires. So the memory map is asked first.
- Two watchpoints on one byte would make "who wrote it" ambiguous, so an overlap is refused. A `count` or a `capture` never stops, so only an identical one is refused.
- The debugger's list is read back after every arm, and a watch is saved only once it is armed.
- For a write-only register a stop's reading is `bus` with `last_wrote`, the last value written.
- `write_maps_to` and `read_maps_to` say what the memory map has at the address for each direction.
- The writer's `pc` is a `0x` address, so it goes straight into `disassemble` or `breakpoint_at` as a `ref`. MAME names it only for a write by the watch's own cpu.

On a `condition`:

- It answers "who writes bits 0-1 of this byte" without a stop at every write of the register.
- `wpdata` is the value as it reached the bus, shifted down to the bytes written.
- It takes `breakpoint_at`'s grammar on the watch's cpu and is evaluated once before arming: MAME sets a watchpoint whose condition it cannot evaluate, and that one never fires.
- A watch through a pointer that is still null has its condition checked right away: the stop that finds the pointer set has no call left to refuse it.
- A row the debugger lists without the condition sent is `readback_refused`. A row already at that range under another condition is `ambiguous_ref`.

On `count`:

- It sees the writes of its own cpu only, never those a DMA or a blitter makes on its own bus.
- It counts writes to its own range only. To count one register's values by the value of another, use a `capture`: two counts cannot be joined afterwards.
- A write lands in one bus word, so a word covered in part would give fragments with no `value`. That is why such a range is refused.
- It sees every write the cpu makes, handled or not, so it arms where nothing handles the write: `write_maps_to` is then `unmapped`, with a `note`.
- `tally_id` names it: its range, plus the cpu when that is not the first one.
- A count that never started must not read as zero. An install the console echoed and never ran is sent once more (`install_resent`); lost twice, the state is `install_lost`.
- `lines_ahead` is how many console lines wait before the install, and `call` the line that marks it done.
- Declaring the range again installs over the old count and keeps its counts. After a clear that ran, it counts from zero.
- A count or capture whose periodic write keeps failing leaves its last finished dump on disk. Its reading is `superseded`, its `why` the error `error.log` logs as `MCP_DUMP_FAILED`.

On `capture`:

- The row is taken before the write lands. When `trigger` lies inside the block, the block holds the value from before the write.
- The block must be plain memory. Reading through a handler would run it at every trigger, and reading around it gives zeros that look like data.
- `source` says where the block is read: `kind`, then `addr` in the cpu's memory, or the `tag` and `offset` of a memory share or region.
- `time_s` is the accessing cpu's own clock at full precision, so two accesses one cycle apart never share it.
- Captures on two cpus share one clock: order their rows by `time_s`, not by position. `line` is the screen line being drawn.
- A capture of reads keeps the access and no block. It sees no instruction fetch and no ROM read, so on code or ROM it keeps no row.
- It runs at every read, so on an address the program polls it costs a Lua call per poll.
- A read capture's `ref` is its trigger, so a write capture of the same address under that ref is refused.
- `gfx_blits`, `gfx_blit_source`, `gfx_draft` and a region write read write captures only.
- `trigger_addr` is where `trigger` resolves, and `trigger_maps_to` what the memory map has there.

On a port (`space="io"`):

- A board that drives its palette or sound through `out` writes nothing to program memory, so only a port watch sees it.
- It lasts the session only. The saved breakpoints file knows no ports, and would set it again as the memory address of the same number.
- It is cleared with its `ref` and `space="io"`. Its `tally_id` carries the space (`6_2@io`): port 6 and address 6 are two watches.
- `cpus_with_io` lists the cpus that have ports, when the one named has none.

Through a pointer:

- It reaches a field a C program keeps in a heap struct behind a global pointer.
- The pointer is read at the width its type gives (`ptr16{...}`, `ptr32{...}`), else at the stack pointer's width.
- On a board whose symbol file sets `bases`, a pointer read through a symbol of a relocated class is an offset in that class's segment.
- A type can name the class (`ptr16@CODE`), which a routine's address kept in DATA needs.
- It is followed again at every stop. A `change` watch moves with it (`moved`), and a null pointer is `null_pointer`, never a watch at address zero.
- `pointer` holds where the pointer was read (`at`, `length`), its `value`, the `offset` and `field` added, and `relocated` (`class`, `base`, `class_from`).

</details>

### Related tools

- [`declaration_list`](#declaration_list)
- [`declaration_clear`](#declaration_clear)
- [`breakpoint_at`](#breakpoint_at)
- [`scan`](scan.md#scan)
- [`memdump`](read.md#memdump)
- [`resume`](run.md#resume)

<details><summary>The contract your client receives</summary>

```text
Declare a watch at `ref`. Stored, re-armed at `start`.

`mode`: `show` (read at each stop), `change` (a write stops the machine), `count` (tallies
writes by value and by writer pc; with `trigger_type` `r` or `rw` the reads are one count,
`reads`, apart), `capture` (rows at
`trigger`), `expr` (one debugger expression). `ref`: a symbol,
`0x` address or pointer place (`base->field`; stopped machine only). `fmt`: a scalar (`u8`
.. `f64`), an array (`u16[8]`), a string (`char[16]`) or a struct (`{x:i16,y:i16}`).
`length`: total bytes, needed unless `fmt` is sized or the symbol typed; at most
128 for show or capture, 1024 otherwise. `condition`: change only, a
debugger expression over `wpdata`, the value written (`wpdata==0x7f`).
`trigger`: capture only; `trigger_type` `w` or `r` there; a capture of reads (`r`) takes no
`length` or `fmt`. `space="io"`: a port tap, `count` or `capture` only, for this session only
(never
stored).

Refused: a change watch on an unmapped write; a count range splitting a bus word; a ref
declared another way; an unknown pointer base or `cpu`.

Reply: `ref`, `mode`, `stored`, `already_stored`, `armed`, `state`, `reading` (on a stopped
machine), and each mode's own fields.

Reference: REFERENCE.md, Breakpoints and watches.
```

</details>
<!-- scry-reference:end watch_add -->

<!-- scry-reference:begin declaration_list -->
## `declaration_list`

List the saved breakpoints, registerpoints and watches, each with its state checked against the debugger's own list.

```text
declaration_list(kind="", cpu="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, after the breakpoint, the registerpoint and the watch of the other entries were set, and a `run_to` left its control.

Ask:

> Which breakpoints and watches are set right now?

Call:

```text
declaration_list()
```

Reply, 3 of 6 fields:

```json
{
  "summary": "declaration_list: 2 breakpoints (2 armed), 1 regpoint (1 armed), 1 watch (1 armed)",
  "status": "ok",
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"}
}
```

Two breakpoints, one registerpoint and one watch are saved, and the debugger lists each as armed. No cpu was named, so the rows are every cpu's.

<details><summary>The whole reply</summary>

```json
{
  "summary": "declaration_list: 2 breakpoints (2 armed), 1 regpoint (1 armed), 1 watch (1 armed)",
  "status": "ok",
  "breakpoints": [
    {
      "ref": "wait_frame",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": "<volatile>",
      "role": "control",
      "addr": "0x0000a631",
      "state": "armed",
      "entry": "1 @ A631 if (++temp0)==0",
      "hits_since_armed": 3
    },
    {
      "ref": "take_credit",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": "<volatile>",
      "role": "stop",
      "addr": "0x0000d676",
      "state": "armed",
      "entry": "3 @ D676"
    }
  ],
  "regpoints": [
    {
      "ref": "a==99",
      "by": "expr",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": "<volatile>",
      "condition": "a==99",
      "state": "armed",
      "entry": "1 if a==99",
      "index": 1
    }
  ],
  "watches": [
    {
      "ref": "credits_bcd",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": "<volatile>",
      "mode": "change",
      "length": 1,
      "fmt": "u8",
      "addr": "0x0000042c",
      "state": "armed",
      "entry": "1 @ 042C-042C write",
      "values_from": "memory"
    }
  ],
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"}
}
```

</details>

### Arguments

- `kind` (one of `""`, `"breakpoint"`, `"regpoint"`, `"watch"`, default `""`): `breakpoint`, `regpoint` or `watch`. Left empty, every kind.
- `cpu` (string, default `""`): Narrows the rows to one cpu. Left empty, every cpu's.

### What comes back

- `breakpoints`: The saved breakpoints. Each row has `ref`, `role`, `addr`, `state` and, once armed, the debugger's `entry`.
- `regpoints`: The saved registerpoints, each with its `condition`, `state`, `entry` and the debugger's `index`.
- `watches`: The saved watches, each with `mode`, `length`, `fmt` and `state`. A `count` or a `capture` adds its tables.
- `foreign`: Debugger rows the server did not set, by kind, as the debugger lists them. They are listed and never deleted.
- `cpu`: The cpu the rows were narrowed to, or `available: false` when none was named.

<details><summary>All 5 reply fields</summary>

- `breakpoints` (array)
- `cpu` (string or object)
- `foreign` (object)
- `regpoints` (array)
- `watches` (array)

</details>

### What it refuses

- A cpu the machine does not have (`unknown_ref`).

### Why it works this way

It answers while the machine runs, and each state is the machine's own answer: every call reads the debugger's breakpoint, watchpoint and registerpoint lists back.

`inherited` is `true` on a row an earlier session saved, since no reply names this session to compare with. `age_s` counts the seconds since `created_at`; a date ahead of this computer's clock gives a negative age, never a zero that would read as "now".

<details><summary>More on why</summary>

What a row carries:

- Every row: `ref`, `by` (how the ref is read), `cpu`, `created_at`, `origin` (the session that saved it), `inherited`, `age_s`, `state`, and `why` where the state needs a reason.
- A breakpoint adds `role`, `addr`, `entry`, its `condition` (with `condition_typed` when the debugger reads it differently) and a control's `hits_since_armed`.
- A registerpoint adds `condition`, `entry` and `index`.
- A watch adds `mode`, `length`, `fmt`, `addr`, `reading` on a stopped machine, `pointer` for a ref through one, and a `change` watch's `entry` and `values_from`.
- A `count` or a `capture` adds `tally_id`, `installed`, `pending`, `install_resent`, `call`, `total`, `frame_as_of` and `superseded`.
- A `count` adds `values` (each `at`, `raw_hex`, `count`, and `value` or `partial`), `values_total` and `overflow_values`.
- It also adds `writers` (each `pc`, `count`, `symbol`), `writers_total`, `overflow_pcs`, and `reads` when it counts them.
- A `capture` adds `trigger`, `trigger_addr`, `trigger_type`, `source`, `rows_path`, `rows_kept`, `rows_max`, `overflow_rows` and `first_rows`.
- Each of `first_rows` has `n`, `frame`, `line`, `time_s`, `pc`, `symbol`, `data`, `mask`, and a write capture's `raw_hex` and `block`.
- A port watch adds `space` and `stored: false`.
- A reset or a state load under a count adds `across` (`event`, `frame_from`): its totals then span two runs.
- A callback that raised adds `callback_errors` (`count`, `first`). While the machine runs the reply adds `last_stop`.

The states of a `count` or a `capture`, beside those at the top of the page:

| `state` | what it means |
|---|---|
| `tallied`, `captured` | Installed, and its tables were read. |
| `no_dump_yet` | Nothing is on disk yet: MAME writes the tables at a stop. |
| `not_installed` | This session holds none for it: `start` did not send it, or it was cleared. |
| `install_failed` | MAME ran the install and it failed. `why` has the error. |
| `install_lost` | MAME's console never ran the install, twice. It recorded nothing: clear it and declare it again. |

What the tables say:

- `values` and `writers` add up from the install on. A write that found its table full is counted in `overflow_values` or `overflow_pcs` and not named.
- A capture's `total` counts every access to its trigger: `rows_kept` of them have a row, and `overflow_rows` came after the limit `rows_max`.
- The listing shows a capture's first rows only, since each holds a whole block. `rows_path` is the file with every row.
- `superseded` is `true` when the tables on disk are older than the frame the machine stands at. `frame_as_of` is the frame they were written at.
- A stop's reply adds `since_last_stop`, and `reset` when the total fell, and never the rows or tables. A listing between two stops uses up nothing.

</details>

### Related tools

- [`declaration_clear`](#declaration_clear)
- [`breakpoint_at`](#breakpoint_at)
- [`regpoint_add`](#regpoint_add)
- [`watch_add`](#watch_add)
- [`status`](session.md#status)

<details><summary>The contract your client receives</summary>

```text
List the declarations of `kind` (empty: every kind) with their state, against the
debugger's own list read back. `cpu` narrows the rows to it. Answers on a running machine.

Reply: `breakpoints`, `regpoints`, `watches` (each kind asked; each row `ref`, `by`,
`cpu`, `created_at`, `origin`, `inherited`, `age_s`, `state`, plus its kind's fields),
`foreign` (debugger rows no declaration placed), `cpu`.

Reference: REFERENCE.md, Breakpoints and watches.
```

</details>
<!-- scry-reference:end declaration_list -->

<!-- scry-reference:begin declaration_clear -->
## `declaration_clear`

Remove saved breakpoints, registerpoints or watches: one by its `ref`, or every one of a kind.

```text
declaration_clear(kind, ref="", cpu="", all=false, space="program")
```

### Try it

On Gridlee, a free ROM from mamedev.org, with two breakpoints saved: one on `take_credit`, and the control an earlier `run_to` left on `wait_frame`.

Ask:

> Remove every breakpoint.

Call:

```text
declaration_clear(kind="breakpoint", all=true)
```

Reply, 5 of 5 fields:

```json
{
  "summary": "declaration_clear breakpoint all: 2 cleared, 2 disarmed",
  "status": "ok",
  "declarations_cleared": 2,
  "disarmed": ["1 @ A631 if (++temp0)==0", "3 @ D676"],
  "while_running": false
}
```

Both saved breakpoints are gone, and `disarmed` shows the two debugger rows removed. The first was the control: its condition counts in `temp0` and never comes true.

<details><summary>The whole reply</summary>

```json
{
  "summary": "declaration_clear breakpoint all: 2 cleared, 2 disarmed",
  "status": "ok",
  "declarations_cleared": 2,
  "disarmed": ["1 @ A631 if (++temp0)==0", "3 @ D676"],
  "while_running": false
}
```

</details>

### Arguments

- `kind` (one of `"breakpoint"`, `"regpoint"`, `"watch"`, required): `breakpoint`, `regpoint` or `watch`: what to clear.
- `ref` (string, default `""`): The one to clear, as the reply that saved it gave its `ref`. Left empty with `all=True`.
- `cpu` (string, default `""`): Clear on this cpu only. Left empty, on every cpu.
- `all` (boolean, default `false`): `true` clears every one of `kind`, and takes no `ref`.
- `space` (one of `"program"`, `"io"`, default `"program"`): `io` when `ref` is a port watch. Only `watch` takes it.

### What comes back

- `declarations_cleared`: How many were removed from the saved breakpoints file.
- `disarmed`: The debugger rows removed, as the debugger listed them, checked by reading its list back.
- `tallies_removed`: The `count` and `capture` watches whose removal was sent to MAME, each with `tally_id`, `removal`, `lines_ahead` and `call`.
- `while_running`: `true` when the machine was running as the call arrived. The clear works either way.

<details><summary>All 4 reply fields</summary>

- `declarations_cleared` (integer)
- `disarmed` (array)
- `tallies_removed` (array)
- `while_running` (boolean)

</details>

### What it refuses

- An empty `ref` without `all`, or both together (`bad_argument`).
- A `ref` that matches nothing: the message names the refs saved (`unknown_ref`).
- `space` on a kind other than `watch`, or together with `all` (`bad_argument`).

### Why it works this way

It removes only what this server set: a `foreign` row, one typed through `debug`, is never deleted.

A `ref` is read once, so a clear reaches only its own kind, and a name is never taken for the address its letters spell. An address matches in any spelling; a symbol must be the one saved.

With no `cpu` it reaches that `ref` on every cpu. In a file several sessions use, `all=True` also clears rows another session saved, which read `inherited: true`: clear by `ref` when they are not yours.

<details><summary>More on why</summary>

- Removing a `count` or a `capture` is sent to MAME's console and applied when it next reads a line.
- It is never sent twice: the id is the range, and a second send could remove a watch declared since.
- A removal MAME did not carry out shows on every reply under `session.tallies_not_removed`.
- If the debugger still lists a row after its removal, `note` says so and names the `debug` command that removes it.
- `all=True` on `watch` removes the port watches too.
- A registerpoint's condition or an `expr` watch matches as typed but for its numbers, read as the console reads them: `7fff`, `0x7fff`, `$7fff` and `#32767` are one.
- There a run of letters such as `ab` stays a name and keeps its case. A saved address written in bare hex is that address.
- With a `state_dir`, `all=True` reaches only the rows saved in that folder. Without one, it reaches every session's rows of the same system and symbol file.
- Declaring the range again installs over a count not removed, keeping its totals, and a clear then removes it. Its `tallies_not_removed` row stays: this session counted past a removal.

</details>

### Related tools

- [`declaration_list`](#declaration_list)
- [`breakpoint_at`](#breakpoint_at)
- [`regpoint_add`](#regpoint_add)
- [`watch_add`](#watch_add)
- [`debug`](write.md#debug)

<details><summary>The contract your client receives</summary>

```text
Clear the declarations of `kind` that `ref` names (as its declaring reply gave it), or
every one with `all=True` and no `ref`, on `cpu` or every cpu. Disarms what this server
armed; a foreign row is never deleted. `space="io"` clears a watch's io tap. Works on a
running machine.

Refused: an empty `ref` without `all`; a `ref` matching none (`unknown_ref`, naming the
refs held); `space` for a kind other than `watch`.

Reply: `declarations_cleared`, `disarmed`, `while_running`, `tallies_removed` (removing an io
tap), `note`.

Reference: REFERENCE.md, Breakpoints and watches.
```

</details>
<!-- scry-reference:end declaration_clear -->
