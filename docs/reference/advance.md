# The Advance tools

**MAME cannot advance one cpu alone.** Every run and step goes through the visible cpu while every other cpu runs its share of the same emulated time. `step(cpu=X)` makes X visible with the stub's `Hc`, which runs nothing, and `others` shows what the rest did. Without the thread patch another cpu cannot be shown without running, so naming one is refused.

**Three ways to advance, and rest.** By ADDRESS (`run_to`, always with a control), by EMULATED TIME or frames (`run_for`), or with NO DEADLINE (`resume`). A running machine handed back unknowingly is the worst state a session can be in, so a run is ELAPSED only once rest is proved by two readings a tenth of a second apart: readings milliseconds apart agree on a machine running flat out.

**The frame counter.** **A board with no screen device has no frame counter, and is run by time.** MAME registers `frame` only on a machine with exactly one screen device (`frame0`, `frame1`... on several); a vector board has a display and no screen chip, so the screens `machine_map` lists are no guide, and `start` asks the console and reports `frame_symbol`. There, runs by frames are refused `no_channel`, and the emulated clock (the console's `time`) proves rest wherever the counter would. A stop's `frame` is unavailable, and the console refusing an expression is `no_channel`, an answer about the machine, never a broken session.

**Frame runs count the counter itself**, so a golden is a marker plus N frames, and N milliseconds is not N frames. MAME keeps "a vblank happened" as one flag that the first cpu to run after it consumes, so the run goes through the FIRST cpu; a build without the thread patch cannot make it visible and refuses a run by frames while another is.

**Stops that are not the run's own.** A stop breakpoint or change watch that halts the machine inside a run ends it as `OTHER_STOP`. A control's row never counts as a stop, which also keeps `stop`'s `cause` from naming a control. By frames a console-started run sends no stop packet, so the tell is a `gvblank` that moved the counter by nothing, or a `Stopped at ...` line in the console's log.

A row typed through `debug` ends a run the same way and is named from that line in `debug.log`, with the `bpclear`/`wpclear`/`rpclear` that removes it; a row this server armed keeps its own name. A registerpoint fires at every instruction while its condition holds, so a run started with it still true stops one instruction on with the counter where it was: `OTHER_STOP`, never `no_progress`.

**Every stop is one survey.** The stop is where round trips are worth saving, so every stop comes back as ONE survey, whatever the call was about. The park after `start` is stop 1, and `stop_seq` is the spelling `status` uses, so a caller counting stops can cross-check.

- `cause` spells a debug row's index `0x<hex>` in the clear command, because the console evaluates that argument as an expression and a bare `D0` or `A` names a register. A breakpoint this server armed names a stop only on its own cpu: two cpus run two programs.
- The field is `errorlog`; a caller reading `reply["log"]` off a survey finds nothing, in silence.
- `regpoint_hit` carries a `note` that the registerpoint is STILL ARMED and fires again one instruction on.

What a running or a broken session does to every tool is in [REFERENCE.md, Advancing the machine](../../REFERENCE.md#advancing-the-machine).

<!-- scry-reference:begin run_to -->
## `run_to`

*Run to a place or a mapped screen*

```text
run_to(ref="", control="", screen="", seconds=30.0, disarm_watches=false, condition="", cpu="")
```

Run to `ref` and stop, with a control counting meanwhile.

`ref` is armed on `cpu` (the visible one when empty). `control` is required with a `ref` or an
anchored screen: a place known to run, declared as a control on that cpu if it is new
(`breakpoint_at(role="control")` does the same ahead of time), and the cpu's other declared
controls count too. `condition`: stop only when it holds, bare numbers hex
(`w@DemoLen==0x25`). Needs a stopped machine. Refused: an unresolved ref, an empty or
unresolved control, an over-long `condition`.

`screen`: a mapped screen's name instead of `ref` (exactly one). If the screen names an `anchor` (set by `screen_map_write`), run to it (`control`
required): a `verified` map judges it there (`stale_map` when it no longer holds), a
`consolidated` one takes it as shown. If it names none, a frame at a time until the map names it,
within `seconds`; a `control` is refused there (`bad_argument`). Reply: `screen` (`screen`, `layer`,
`mode`, `judged`), `frames` run. Refused: an unmapped screen (`unknown_ref`).

Reply: `verdict` (`TARGET`, `TIMEOUT`, `OTHER_STOP`), `control_hits`, `controls` (each `ref`,
`cpu`, `hits_in_run`; a run to a ref or an anchor), `target_disarmed` (the target was left
armed or the interrupt went unanswered), `frames` (a screen with no anchor), the
stop survey (`stop_seq`, `pc`, `regs`, `instruction`, `following` when the listing runs on).
INVALID has no `verdict`: `control_silent`, `cut_by_other_stop`, `not_settled`, `stale_map`.

Reference: REFERENCE.md, Advancing the machine.

| argument | type | default |
|---|---|---|
| `ref` | string | `""` |
| `control` | string | `""` |
| `screen` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `30.0` |
| `disarm_watches` | boolean | `false` |
| `condition` | string | `""` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `addr` | string |
| `call` | string |
| `evaluated_by` | string |
| `lines_ahead` | integer |
| `pc_before` | string |
| `reader_steps` | integer |
| `resent` | integer |
| `thread_errors` | integer |
| `armed` | boolean |
| `command_chars` | integer |
| `condition` | string |
| `control` | string |
| `control_dasm` | array |
| `control_hits` | integer |
| `console_reruns` | integer |
| `control_on` | array |
| `controls` | array |
| `cpu` | string or object |
| `following` | array of string |
| `frames` | integer |
| `instruction` | StopInstruction |
| `disarmed_watches` | array |
| `errorlog` | object |
| `frame` | integer |
| `limit_chars` | integer |
| `not_rearmed` | array |
| `pc` | string |
| `ref` | string |
| `regpoint_hit` | object |
| `regs` | object |
| `screen` | object |
| `state` | string |
| `stop_seq` | integer |
| `stored` | boolean |
| `target_disarmed` | boolean |
| `verdict` | string |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "ref": "irq_vblank",
  "control": "0x4a0",
  "seconds": 10.0
}
```

```json
{
  "summary": "run_to irq_vblank: TARGET, control counted 0",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 0,
  "controls": [
    {"ref": "0x4a0", "cpu": ":maincpu", "hits_in_run": 0}
  ],
  "cause": "target irq_vblank",
  "stop_seq": 16,
  "pc": "0x00000400",
  "cpu": ":maincpu",
  "frame": 11,
  "regs": {
    "D0": "0x00000000",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x000002ff",
    "A1": "0x00000000",
    "A2": "0x00000000",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00000000",
    "SP": "0x00200ffa",
    "PS": "0x2300",
    "PC": "0x00000400"
  },
  "instruction": {
    "address": "000400",
    "bytes": "46FC2700",
    "text": "move    #$2700, SR",
    "symbol": "irq_vblank",
    "delta": 0
  },
  "following": ["000404: 48E7 F000           movem.l D0-D3, -(A7)", "000408: 5279 0020 3200      addq.w  #1, $203200.l", "00040E: 52B9 0020 31FC      addq.l  #1, $2031fc.l", "000414: 33FC 0001 0020 91E8 move.w  #$1, $2091e8.l", "00041C: 4A79 0020 91EE      tst.w   $2091ee.l"],
  "errorlog": {
    "lines_total": 768,
    "truncated": true,
    "lines": ["[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002F8 = 0000 & FF00", "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002F8 = 0000 & 00FF", "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002FA = 0000 & FF00", "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002FA = 0000 & 00FF", "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002FC = 0000 & FF00", "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002FC = 0000 & 00FF", "... 2 more"],
    "mark": 14,
    "how": "`log(pattern=\".\", channel=\"emulator\", since_mark=14, limit=400)` reads the newest 400"
  }
}
```
<!-- scry-reference:end run_to -->

**Why a control is armed for a place.** (A screen with no anchor is run to a frame at a time, which needs none.) Several different mistakes leave a MAME breakpoint silent, and each looks exactly like "that routine is never called"; the control counting beside the target tells them apart. Both rows are read back from `bplist` before the machine moves, since a row the console took and does not list would come back TIMEOUT beside a control that fired.

**Whose stop is the target's.** A stop at the target's address is `TARGET` only when it is the target cpu's. A control on another cpu runs another program and fires while the target's cpu is held in reset, so it cannot say that cpu ran; naming one is `unknown_ref` with the `breakpoint_at(..., cpu=)` that would fix it.

**A TIMEOUT with silent controls is INVALID** because it cannot tell a wrong address from a right one rarer than assumed.

**`disarm_watches`** is for a watch on a byte written every frame, which would otherwise stop every later run. A `session_broken` leaves the disarmed watches disarmed.

**A `ref` that is the target carries no stop of its own**, because one row per address means a stop there could not be told from the target's.

**Unanswered interrupt at the bound.** `run_to` starts with the stub's own `c`, so an interrupt at the bound that is NOT ANSWERED is `not_settled` with no `cause` (no stop was read) and `target_disarmed` saying whether the temporary breakpoint's removal was confirmed; the session stays RUNNING and `stop` waits for the packet the run still owes. A removal the stub REFUSES after the stop is an answer, not a break: the stop is still the measurement, and the `note` names the `debug("bpclear 0x<row>")` that removes the row (`declaration_clear(kind="breakpoint")` clears declarations, and the target was never one).

Reply details: `not_settled` may leave the machine RUNNING: `stop`, and if that fails as well, `close` then `start`; `session_broken` LATCHES until `close`. `control_silent` carries a survey, `control_dasm` and a `note`; `readback_refused` means a row listed bare is removed first. A removal the stub refuses keeps the stop's reply with `target_disarmed: false` and a `note`; a stop packet landing during it is a TIMEOUT with `cause` "answered late". A TARGET is `ok` with no control hit. Also in the reply: `target_disarmed`, `note`, `disarmed_watches`, `not_rearmed`. The stop survey every advancing tool returns is `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, and `watch_hit` or `regpoint_hit` if one stopped it. `disarm_watches` is `run_to`'s and `run_for`'s and `trace`'s shared option.

<!-- scry-reference:begin run_for -->
## `run_for`

*Run for emulated time*

```text
run_for(milliseconds=0, frames=0, seconds=30.0, disarm_watches=false)
```

Run for `milliseconds` of emulated time or `frames` of the frame counter (exactly one) and
wait until STOPPED. Needs the machine STOPPED (else `not_stopped`).

Reply: `verdict` (`ELAPSED`, `TIMEOUT`, `OTHER_STOP`; a control never cuts), `frame_before`,
`frame_after`, `emulated_before_s`, `emulated_after_s`, `cycles` (each unavailable with
why), `polls` (by frames) or `reads` (by milliseconds), and the stop survey of `run_to`.
INVALID has no `verdict`: `no_progress`, `frames_went_backwards`, `not_settled`,
`session_broken`; `no_channel` on a board with no counter.

Reference: REFERENCE.md, Advancing the machine.

| argument | type | default |
|---|---|---|
| `milliseconds` | integer | `0` |
| `frames` | integer | `0` |
| `seconds` | number (> 0, <= 600.0) | `30.0` |
| `disarm_watches` | boolean | `false` |

| reply field | type |
|---|---|
| `command_chars` | integer |
| `cpu` | string or object |
| `cycles` | integer or object |
| `following` | array of string |
| `instruction` | StopInstruction |
| `disarmed_watches` | array |
| `emulated_after_s` | number or object |
| `emulated_before_s` | number |
| `errorlog` | object |
| `frame` | integer or object |
| `frame_after` | integer or object |
| `frame_before` | integer or object |
| `limit_chars` | integer |
| `not_rearmed` | array |
| `pc` | string |
| `polls` | integer |
| `reads` | integer |
| `regpoint_hit` | object |
| `regs` | object |
| `stop_seq` | integer |
| `verdict` | string |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "frames": 8,
  "seconds": 10.0
}
```

```json
{
  "summary": "run_for 8 frames: ELAPSED, frame 0 to 8",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 0,
  "frame_after": 8,
  "emulated_before_s": 0.019968,
  "emulated_after_s": 0.179712,
  "cycles": 2555906,
  "polls": 9,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 12,
  "pc": "0x000027ac",
  "cpu": ":maincpu",
  "frame": 8,
  "regs": {
    "D0": "0x0103a925",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x00004842",
    "A1": "0x000f27de",
    "A2": "0x00720003",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00000000",
    "SP": "0x00200fc4",
    "PS": "0x2708",
    "PC": "0x000027ac"
  },
  "instruction": {
    "address": "0027AC",
    "bytes": "51C8FFFE",
    "text": "dbra    D0, $27ac",
    "symbol": "boot_init",
    "delta": 464
  },
  "following": ["0027B0: 33FC 0000 0070 0000 move.w  #$0, $700000.l", "0027B8: 33FC 0000 0070 0004 move.w  #$0, $700004.l", "0027C0: 33FC 0000 0070 000C move.w  #$0, $70000c.l", "0027C8: 33FC 000F 0070 000E move.w  #$f, $70000e.l"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 14},
  "watches": [
    {
      "ref": "0x700000",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 7,
      "callback_errors": {
        "count": 0,
        "first": {"available": false, "why": "no callback raised"}
      },
      "since_last_stop": 7
    }
  ],
  "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "... 12 more"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables"
}
```
<!-- scry-reference:end run_for -->

`cycles` spans WHAT WAS ASKED FOR, never the aligning `gvblank` a run from a mid-frame stop spends reaching the vblank it is inside; that tick moves no counter, and `polls` is the tell that it fired. `cycles` is unavailable on the first run after a load, rewind or typed reset: MAME's debugger refreshes `totalcycles` only when the cpu executes, so the span would be off by the distance between the two states.

`frames` goes through the first cpu because MAME's vblank stop lands there, with a `note` when it had to be made visible; the first screen's counter serves a board of several. `no_progress` by frames leaves the machine RUNNING until `stop` and carries no survey; by milliseconds it carries one. `cycles` is also unavailable across two cpus. `polls` is N+1 after a mid-frame stop. `not_settled` (a counter or clock still moving at the bound) may leave it RUNNING: `stop`, and if that fails, `close` then `start`; `session_broken` LATCHES. It reports progress while it waits. `disarm_watches` is as in `run_to`; `no_channel` is a board with no counter.

<!-- scry-reference:begin step -->
## `step`

*Step instructions*

```text
step(count=1, mode="into", cpu="")
```

Execute `count` (1..300) instructions of `cpu` (the visible one when empty): `into`
is one instruction, `over` runs a call to its return as one step. A named cpu is made
visible first; `others` gives every other cpu's program counter before and after. A stop on
another cpu ends the steps (`note`). Needs the machine STOPPED (else `not_stopped`).

Reply: `mode`, `instructions_completed`, `others` (on a build with a thread per cpu), and
the stop survey of `run_to`. A refused `over` may have run: the machine is marked RUNNING,
and `stop` recovers it. INVALID: `not_settled`, `session_broken`.

Reference: REFERENCE.md, Advancing the machine.

| argument | type | default |
|---|---|---|
| `count` | integer (>= 1, <= 300) | `1` |
| `mode` | one of `"into"`, `"over"` | `"into"` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `command_chars` | integer |
| `cpu` | string |
| `following` | array of string |
| `instruction` | StopInstruction |
| `errorlog` | object |
| `frame` | integer or object |
| `instructions_completed` | integer |
| `limit_chars` | integer |
| `mode` | string |
| `others` | object |
| `pc` | string |
| `regpoint_hit` | object |
| `regs` | object |
| `stop_seq` | integer |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "count": 1
}
```

```json
{
  "summary": "step 1 into: pc 0x000029ee",
  "status": "ok",
  "mode": "into",
  "instructions_completed": 1,
  "others": {
    ":subcpu": {"reg": "PC", "before": "0x00000542", "after": "0x00000542"}
  },
  "cause": "step 1",
  "stop_seq": 22,
  "pc": "0x000029ee",
  "cpu": ":maincpu",
  "frame": 17,
  "regs": {
    "D0": "0x0000e281",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x000002ff",
    "A1": "0x00000000",
    "A2": "0x00000000",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00200fe4",
    "SP": "0x00200fa4",
    "PS": "0x2108",
    "PC": "0x000029ee"
  },
  "instruction": {
    "address": "0029EE",
    "bytes": "51C8FFFE",
    "text": "dbra    D0, $29ee",
    "symbol": "mode_clear_blits",
    "delta": 408
  },
  "following": ["0029F2: 4CDF 3FFF movem.l (A7)+, D0-D7/A0-A5", "0029F6: 4E75      rts", "0029F8: 0000 0796 ori.b   #$96, D0", "0029FC: 0000 4854 ori.b   #$54, D0", "002A00: 0000 4860 ori.b   #$60, D0", "002A04: 0000 48C4 ori.b   #$c4, D0", "... 2 more"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 66062}
}
```
<!-- scry-reference:end step -->

Each step is confirmed on the program counter, because the console answers while the machine still runs to the return of an `over`. A run cut by a stop on another cpu reports no `cycles`, since that counter is each cpu's own.

The ceiling keeps the longest walk of `over`s inside the bound every wait takes. A named cpu is made visible by the stub's `Hc`, which needs the thread patch. An `over` still moving at its bound is interrupted and whether the call would have returned is not seen; a refused `over` may have been taken, so the session is marked RUNNING and `stop` recovers it (if `stop` fails, `close` then `start`). An `into` whose stop is late still owes its packet, which `stop` waits for, and `not_settled` carries `mode` and `instructions_completed`. An `into` that reads anything else in a stop's place, a failed connection, or an `over` the console did not answer in time is `session_broken` and LATCHES, because that answer would be read as the next request's.

<!-- scry-reference:begin resume -->
## `resume`

*Resume the machine*

```text
resume(seconds=0.0)
```

Let the machine run. `seconds` 0 (the default) returns at once with no deadline; a bound up
to 600 waits for a stop and, if none comes, leaves it running. Needs the machine STOPPED (else `not_stopped`).

Reply: with a bound, `waited_s` and `verdict` (`OTHER_STOP` with the stop survey and
`average_speed`; `TIMEOUT`, left running, with a `note`). INVALID: `session_broken`.

Reference: REFERENCE.md, Advancing the machine.

| argument | type | default |
|---|---|---|
| `seconds` | number (>= 0, <= 600.0) | `0.0` |

| reply field | type |
|---|---|
| `average_speed` | object |
| `cpu` | string |
| `following` | array of string |
| `instruction` | StopInstruction |
| `errorlog` | object |
| `frame` | integer |
| `pc` | string |
| `regpoint_hit` | object |
| `regs` | object |
| `stop_seq` | integer |
| `verdict` | string |
| `waited_s` | number |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "resume: running, no wait asked",
  "status": "ok"
}
```
<!-- scry-reference:end resume -->

While it runs, readers refuse naming `last_stop`, and `answers_while_running` lists every tool that answers. A wait that reads something in a stop's place, a release that could not be sent, or a stop that could not be surveyed is `session_broken` and LATCHES; the way out is `close`, then `start`. It reports progress while it waits.

<!-- scry-reference:begin stop -->
## `stop`

*Stop a running machine*

```text
stop()
```

Stop a running machine where it is and survey the stop.

Reply: `interrupted` (`true` with the stop survey and `average_speed`; `false` when already
stopped, with a `note`). INVALID: `not_settled` (the machine stays marked RUNNING; ask
again), `session_broken`.

Reference: REFERENCE.md, Advancing the machine.

Takes no argument.

| reply field | type |
|---|---|
| `average_speed` | object |
| `cpu` | string |
| `following` | array of string |
| `instruction` | StopInstruction |
| `errorlog` | object |
| `frame` | integer or object |
| `interrupted` | boolean |
| `pc` | string |
| `regpoint_hit` | object |
| `regs` | object |
| `stop_seq` | integer |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "stop: was already stopped",
  "status": "ok",
  "interrupted": false,
  "note": "the machine was already stopped",
  "last_stop": {
    "stop_seq": 28,
    "pc": "0x000025f6",
    "cpu": ":maincpu",
    "frame": 31,
    "cause": "the `gvblank` stop of the last frame asked",
    "since_s": 0.0,
    "wall_at": "<volatile>"
  }
}
```
<!-- scry-reference:end stop -->

If `stop` fails as well, `close` then `start`; nothing counts the attempts. `not_settled` also covers a console-started run whose frame counter still moves. An interrupt answered by something that is not a stop, a failed connection, or a stop that could not be surveyed is `session_broken` and LATCHES as under `run_to`. A run by frames bailed out as `no_progress` is brought back here: the interrupt is its proof of rest.

<!-- scry-reference:begin trace -->
## `trace`

*Trace what a run executes*

```text
trace(milliseconds=0, frames=0, dest="", seconds=60.0, cpu="", noloop=false)
```

Run as `run_for` does with MAME's tracer on one cpu, then return the addresses it executed,
joined to symbols. Window: `milliseconds` or `frames` (at most 5026 frames or
98143 ms; `noloop`, 1648 and 32920). `dest`: an absolute
new path. `noloop=True`: exact `count`s, not which addresses ran. Needs a stopped machine.

Reply: `run_for`'s, plus `trace` (`path`, `set_path`, `instructions`, `addresses`,
`unplaced`, `symbols` (first 64)). Refused: `dest` existing,
`no_channel`, `readback_refused`.

Reference: REFERENCE.md, Advancing the machine.

| argument | type | default |
|---|---|---|
| `milliseconds` | integer | `0` |
| `frames` | integer | `0` |
| `dest` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `60.0` |
| `cpu` | string | `""` |
| `noloop` | boolean | `false` |

| reply field | type |
|---|---|
| `emulated_after_s` | number or object |
| `emulated_before_s` | number or object |
| `cpu` | string or object |
| `cycles` | integer |
| `following` | array of string |
| `instruction` | StopInstruction |
| `errorlog` | object |
| `frame` | integer |
| `frame_after` | integer |
| `frame_before` | integer |
| `path` | string |
| `pc` | string or object |
| `polls` | integer |
| `regs` | object |
| `stop_seq` | integer |
| `trace` | object |
| `verdict` | string |

Example, from a live run:

```json
{
  "frames": 1,
  "seconds": 10.0
}
```

```json
{
  "summary": "trace :maincpu 1 frame: 201 addresses in 7 symbols, 13781 bytes",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 16,
  "frame_after": 17,
  "emulated_before_s": 0.339457,
  "emulated_after_s": 0.359424,
  "cycles": 319482,
  "polls": 1,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 21,
  "pc": "0x000029ee",
  "cpu": ":maincpu",
  "frame": 17,
  "regs": {
    "D0": "0x0000e282",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x000002ff",
    "A1": "0x00000000",
    "A2": "0x00000000",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00200fe4",
    "SP": "0x00200fa4",
    "PS": "0x2108",
    "PC": "0x000029ee"
  },
  "instruction": {
    "address": "0029EE",
    "bytes": "51C8FFFE",
    "text": "dbra    D0, $29ee",
    "symbol": "mode_clear_blits",
    "delta": 408
  },
  "following": ["0029F2: 4CDF 3FFF movem.l (A7)+, D0-D7/A0-A5", "0029F6: 4E75      rts", "0029F8: 0000 0796 ori.b   #$96, D0", "0029FC: 0000 4854 ori.b   #$54, D0", "002A00: 0000 4860 ori.b   #$60, D0", "002A04: 0000 48C4 ori.b   #$c4, D0", "... 2 more"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 66062},
  "stopped_on_its_own": {
    "stop_seq": 20,
    "pc": "0x00002986",
    "cpu": ":maincpu",
    "frame": 16,
    "cause": "stopped at no breakpoint this server armed",
    "packet": "T05thread:1;0e:00200fe4;0f:00200fa4;11:00002986;"
  },
  "trace": {
    "cpu": ":maincpu",
    "path": "$TMPDIR/mame-mcp-<run>/snap/trace-1.trace",
    "bytes": 13781,
    "set_path": "$TMPDIR/mame-mcp-<run>/snap/trace-1.trace.set.jsonl",
    "instructions": 23491,
    "addresses": 201,
    "unplaced": 0,
    "symbols": [
      {
        "symbol": "irq_vblank",
        "addr": "0x00000400",
        "addresses": 25,
        "first": "0x00000400",
        "last": "0x00000502"
      },
      {
        "symbol": "page_bit_compose_a",
        "addr": "0x00000506",
        "addresses": 4,
        "first": "0x00000506",
        "last": "0x00000516"
      },
      {
        "symbol": "arm_line_counter",
        "addr": "0x00000520",
        "addresses": 18,
        "first": "0x00000520",
        "last": "0x0000059a"
      },
      {
        "symbol": "mode_clear_blits",
        "addr": "0x00002856",
        "addresses": 15,
        "first": "0x00002986",
        "last": "0x000029ee"
      },
      {
        "symbol": "sound_streamer_rom",
        "addr": "0x000f2446",
        "addresses": 116,
        "first": "0x000f2984",
        "last": "0x000f2df8"
      },
      {
        "symbol": "irq5_streamer_ram",
        "addr": "0x00203164",
        "addresses": 22,
        "first": "0x00203164",
        "last": "0x002031f4"
      },
      "... 1 more"
    ],
    "symbols_total": 7,
    "truncated": false,
    "noloop": false,
    "note": "the pc :maincpu was parked on, 0x00002986, is counted: the window executed it first and the tracer, armed there, does not log it"
  }
}
```
<!-- scry-reference:end trace -->

**One call, armed and closed**, because a tracer left armed keeps writing on the next run of a client that forgot it. The machine is never let go of with the tracer open; a close the console does not confirm is `readback_refused` with `trace.closed: false`, and the way out is `stop`, then `debug("trace off,<cpu>")`, and if `stop` fails, `close` then `start`, since closing MAME closes the file. Arming replaces a trace typed through `debug` on that cpu.

**The parked edges.** The tracer logs a pc on arrival, before executing it. So the pc a stopped cpu is parked on is absent from a trace armed there although the window executes it first, and the pc the run ends parked on is logged although never executed; both are corrected and `note` says which applied. A core that yields mid-instruction (MAME's 68000) finishes the instruction it was in only after the window, unlogged.

**Condensing, and `noloop`.** By default the tracer keeps the last 64 pcs and skips a pc already twice among them. The SET survives that exactly, because a pc is logged before it is skipped, but for address 0 among the first 63 instructions (the history starts as zeros). The counts do not: `instructions` is exact only under `noloop`.

**What the tracer cannot see**: a cpu the debugger ignores, a cpu parked in its own wait, and a timeslice running with a save or a load pending, since MAME calls no instruction hook for any of them. A trace with no instruction line is therefore `readback_refused`, naming both causes it cannot tell apart (the cpu executed nothing; the tracer recorded nothing).

**The caps** bound how much one window can produce; a longer window is consecutive calls.

`set_path` is a JSON line per executed address, ascending (`addr`, `symbol` when placed, `count` under `noloop`); `symbols` rows carry `symbol`, `addr`, `addresses`, `first`, `last` and `instructions` under `noloop`. An empty `dest` lands in the scratch. Refusals before anything is armed: an existing `dest` or `<dest>.set.jsonl`, a cpu with no disassembler (`no_channel`). `readback_refused`: a trace with no instruction line, or a tracer that could not be closed (`trace.closed: false`, unavailable when the session broke). An INVALID run carries `trace` (`path`, `bytes`, `closed`) and no set file.
