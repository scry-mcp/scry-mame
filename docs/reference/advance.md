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

*Run to a place, with a control*

```text
run_to(ref, control="", seconds=30.0, disarm_watches=false, condition="", cpu="")
```

Run to `ref` and stop, with the session's CONTROLS counting meanwhile.

Arguments: `ref`, the target, armed on `cpu` (the visible one when empty) and reached only by
that cpu. `control`: a ref declared as a control on the target's cpu
(`breakpoint_at(role="control")`: counts, never halts); with none there the run is refused, and
one named here is DECLARED and stored. `condition`: stop at `ref` only when it holds, in the
console's grammar, bare numbers hex (`w@DemoLen==0x25`; no `,`, `;`, braces or assignment).
`seconds`: the wall-clock bound. `disarm_watches=True`: change watches off
for this pass, re-armed after it (`disarmed_watches`, `not_rearmed`).

Refused before anything is declared: a target or a control this build does not resolve, a
`condition` too long for a packet (`command_chars`, `limit_chars`). Needs the machine STOPPED (else `not_stopped`).

Reply: `verdict` (`TARGET`; `TIMEOUT` within `seconds`, the machine STOPPED; `OTHER_STOP`, a
registerpoint included), `control_hits`, `controls` (each control's `ref`, `cpu`, `hits_in_run`
over THIS run), and the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine). A removal the stub refuses keeps the stop's reply, with
`target_disarmed: false` and a `note`; a stop packet landing during it is a TIMEOUT, `cause`
"answered late". A TARGET is `ok` with no control hit: reaching it proves the cpu ran. An
INVALID run carries no `verdict`: `control_silent` (a TIMEOUT with no control hit: the survey,
`control_dasm`, a `note`), `cut_by_other_stop`, `readback_refused` (a row listed bare is
removed first), `not_settled` (may be RUNNING: `stop`, and if `stop` fails as well, `close`
then `start`) or `session_broken`, which LATCHES until `close`.

Reference: REFERENCE.md, Advancing the machine.

| argument | type | default |
|---|---|---|
| `ref` | string | required |
| `control` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `30.0` |
| `disarm_watches` | boolean | `false` |
| `condition` | string | `""` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `addr` | string |
| `armed` | boolean |
| `command_chars` | integer |
| `condition` | string |
| `control` | string |
| `control_dasm` | array |
| `control_hits` | integer |
| `control_on` | array |
| `controls` | array |
| `cpu` | string or object |
| `dasm` | array or object |
| `disarmed_watches` | array |
| `errorlog` | object |
| `frame` | integer |
| `limit_chars` | integer |
| `not_rearmed` | array |
| `note` | string |
| `pc` | string |
| `ref` | string |
| `regpoint_hit` | object |
| `regs` | object |
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
    {
      "ref": "0x4a0",
      "cpu": ":maincpu",
      "hits_in_run": 0
    }
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
  "dasm": [
    "000400: 46FC 2700           move    #$2700, SR",
    "000404: 48E7 F000           movem.l D0-D3, -(A7)",
    "000408: 5279 0020 3200      addq.w  #1, $203200.l",
    "00040E: 52B9 0020 31FC      addq.l  #1, $2031fc.l",
    "000414: 33FC 0001 0020 91E8 move.w  #$1, $2091e8.l",
    "00041C: 4A79 0020 91EE      tst.w   $2091ee.l"
  ],
  "errorlog": {
    "lines_total": 768,
    "truncated": true,
    "lines": [
      "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002F8 = 0000 & FF00",
      "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002F8 = 0000 & 00FF",
      "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002FA = 0000 & FF00",
      "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002FA = 0000 & 00FF",
      "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002FC = 0000 & FF00",
      "[:maincpu] ':maincpu' (0E2C6C): unmapped program memory write to 0002FC = 0000 & 00FF",
      "... 2 more"
    ],
    "mark": 14,
    "how": "`log(pattern=\".\", channel=\"emulator\", since_mark=14, limit=400)` reads the newest 400"
  }
}
```
<!-- scry-reference:end run_to -->

**Why a control is always armed.** Several different mistakes leave a MAME breakpoint silent, and each looks exactly like "that routine is never called"; the control counting beside the target tells them apart. Both rows are read back from `bplist` before the machine moves, since a row the console took and does not list would come back TIMEOUT beside a control that fired.

**Whose stop is the target's.** A stop at the target's address is `TARGET` only when it is the target cpu's. A control on another cpu runs another program and fires while the target's cpu is held in reset, so it cannot say that cpu ran; naming one is `unknown_ref` with the `breakpoint_at(..., cpu=)` that would fix it.

**A TIMEOUT with silent controls is INVALID** because it cannot tell a wrong address from a right one rarer than assumed.

**`disarm_watches`** is for a watch on a byte written every frame, which would otherwise stop every later run. A `session_broken` leaves the disarmed watches disarmed.

**A `ref` that is the target carries no stop of its own**, because one row per address means a stop there could not be told from the target's.

**Unanswered interrupt at the bound.** `run_to` starts with the stub's own `c`, so an interrupt at the bound that is NOT ANSWERED is `not_settled` with no `cause` (no stop was read) and `target_disarmed` saying whether the temporary breakpoint's removal was confirmed; the session stays RUNNING and `stop` waits for the packet the run still owes. A removal the stub REFUSES after the stop is an answer, not a break: the stop is still the measurement, and the `note` names the `debug("bpclear 0x<row>")` that removes the row (`breakpoint_clear` clears declarations, and the target was never one).

<!-- scry-reference:begin run_for -->
## `run_for`

*Run for emulated time*

```text
run_for(milliseconds=0, frames=0, seconds=30.0, disarm_watches=false)
```

Run the machine for `milliseconds` of EMULATED time, or for `frames` of the frame COUNTER
(exactly one of the two), and wait until it has STOPPED.

Arguments: `milliseconds` (the console's `gtime`) or `frames` (one `gvblank` per tick, each
confirmed on the counter; sent through the first cpu, the one MAME's vblank stop lands on,
with a `note` when it had to be made visible; the first screen's counter on a board of
several; `no_channel` on a board with none). `seconds`: the wall-clock bound.
`disarm_watches` as in `run_to`. Needs the machine STOPPED (else `not_stopped`).

Reply: `verdict` (`ELAPSED`: it stopped by itself; `TIMEOUT`: still moving at `seconds`, so
interrupted; `OTHER_STOP`: a watch, stop breakpoint, registerpoint or row typed through `debug`
cut it, named by the survey; a CONTROL never cuts), `frame_before`, `frame_after`,
`emulated_before_s`, `emulated_after_s`, `cycles` (the visible cpu's `totalcycles` over what was
asked), each unavailable with why (no counter; `cycles` also across two cpus, after a load,
rewind or typed reset), `polls` (by frames, the `gvblank`s sent, N+1 after a mid-frame stop) or
`reads` (by milliseconds, its readings), and the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine). An INVALID run carries no
`verdict`: `no_progress` (by `milliseconds`, a counter or clock that did not move, as under one
frame: the survey, the machine STOPPED; by `frames`: no survey, the machine RUNNING until
`stop`), `frames_went_backwards`, `not_settled` (a counter or clock still moving at the bound;
may be RUNNING: `stop`, and if `stop` fails as well, `close` then `start`) or `session_broken`,
which LATCHES. Reports its progress while it waits; advancing alters nothing.

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
| `dasm` | array or object |
| `disarmed_watches` | array |
| `emulated_after_s` | number or object |
| `emulated_before_s` | number |
| `errorlog` | object |
| `frame` | integer or object |
| `frame_after` | integer or object |
| `frame_before` | integer or object |
| `limit_chars` | integer |
| `not_rearmed` | array |
| `note` | string |
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
  "dasm": [
    "0027AC: 51C8 FFFE           dbra    D0, $27ac",
    "0027B0: 33FC 0000 0070 0000 move.w  #$0, $700000.l",
    "0027B8: 33FC 0000 0070 0004 move.w  #$0, $700004.l",
    "0027C0: 33FC 0000 0070 000C move.w  #$0, $70000c.l",
    "0027C8: 33FC 000F 0070 000E move.w  #$f, $70000e.l"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 14
  },
  "watches": [
    {
      "ref": "0x700000",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 7,
      "callback_errors": {
        "count": 0,
        "first": {
          "available": false,
          "why": "no callback raised"
        }
      },
      "since_last_stop": 7
    }
  ],
  "omitted": [
    "addr",
    "by",
    "fmt",
    "frame_as_of",
    "install_resent",
    "installed",
    "... 12 more"
  ],
  "how": "`watch_list` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables"
}
```
<!-- scry-reference:end run_for -->

`cycles` spans WHAT WAS ASKED FOR, never the aligning `gvblank` a run from a mid-frame stop spends reaching the vblank it is inside; that tick moves no counter, and `polls` is the tell that it fired. `cycles` is unavailable on the first run after a load, rewind or typed reset: MAME's debugger refreshes `totalcycles` only when the cpu executes, so the span would be off by the distance between the two states.

<!-- scry-reference:begin step -->
## `step`

*Step instructions*

```text
step(count=1, mode="into", cpu="")
```

Execute `count` (1..300) instructions of `cpu` (`subcpu`; the visible one when empty)
and stop, the ceiling keeping the longest walk of `over`s inside the bound every wait takes (a
longer one is `run_to` or `run_for`):
`into` (the gdbstub's single step, one instruction) or `over` (the console's `over`: a call is
run to its return as one step). A named cpu is made visible first (the stub's `Hc`, needing
the thread patch); MAME runs every other cpu meanwhile, and `others` gives each one's program
counter register before and after. A stop on another cpu ends the steps there (`note`).
An `over` still moving at its bound is interrupted and answers INVALID (`not_settled`)
with the count; whether the call would have returned later is not seen. An `over` the
console REFUSED is `not_settled` too: it may have been taken, so the session is marked
RUNNING and `stop` recovers it; if `stop` fails as well, `close` then `start` is the way
out. An `into` whose stop does not arrive in time is `not_settled` as well, with `mode`
and `instructions_completed`: the stub still owes the stop packet of
that step, and `stop` waits for it. An `into` that reads anything else in a stop's place,
or whose connection failed, is `session_broken` with both, and it
LATCHES as `run_to`'s does; so does an `over` whose connection failed, or that the console
did not answer IN TIME: that answer is still owed and would be read as the next
request's, so `close` then `start` is the way out.
Needs the machine STOPPED (else `not_stopped`).

Reply: `mode`, `instructions_completed` (those that landed), `others` on a build with a thread
per cpu, then the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine).

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
| `dasm` | array or object |
| `errorlog` | object |
| `frame` | integer or object |
| `instructions_completed` | integer |
| `limit_chars` | integer |
| `mode` | string |
| `note` | string |
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
    ":subcpu": {
      "reg": "PC",
      "before": "0x00000542",
      "after": "0x00000542"
    }
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
  "dasm": [
    "0029EE: 51C8 FFFE dbra    D0, $29ee",
    "0029F2: 4CDF 3FFF movem.l (A7)+, D0-D7/A0-A5",
    "0029F6: 4E75      rts",
    "0029F8: 0000 0796 ori.b   #$96, D0",
    "0029FC: 0000 4854 ori.b   #$54, D0",
    "002A00: 0000 4860 ori.b   #$60, D0",
    "... 3 more"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 66062
  }
}
```
<!-- scry-reference:end step -->

Each step is confirmed on the program counter, because the console answers while the machine still runs to the return of an `over`. A run cut by a stop on another cpu reports no `cycles`, since that counter is each cpu's own.

<!-- scry-reference:begin resume -->
## `resume`

*Resume the machine*

```text
resume(seconds=0.0)
```

Let the machine RUN. With `seconds` at zero (the default) it comes back at once and the
machine runs with NO deadline, until a breakpoint fires, `stop`, or `close`; with a bound it
waits up to `seconds` for a stop and, if none comes, LEAVES IT RUNNING (unlike `run_to`, which
interrupts at its bound). Needs the machine STOPPED (else `not_stopped`), a second `resume` too.

Reply: with a bound, `waited_s` and `verdict`: `OTHER_STOP` (back at the debugger, with
the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine) and `average_speed`) or `TIMEOUT` (LEFT RUNNING, a `note`); with 0, neither.
`seconds` is 0 or a bound up to 600. While it runs the readers of the machine refuse,
naming `last_stop` and, in `answers_while_running`, every tool that answers. A wait that reads
something in a stop's place, or a release that could not be sent, is `status: INVALID`
(`session_broken`) and never a running session, and so is a stop that was read and could not be
surveyed: it LATCHES as `run_to`'s does, and the way out is `close`, then `start`. Reports its
progress while it waits.

Reference: REFERENCE.md, Advancing the machine.

| argument | type | default |
|---|---|---|
| `seconds` | number (>= 0, <= 600.0) | `0.0` |

| reply field | type |
|---|---|
| `average_speed` | object |
| `cpu` | string |
| `dasm` | array or object |
| `errorlog` | object |
| `frame` | integer |
| `note` | string |
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

<!-- scry-reference:begin stop -->
## `stop`

*Stop a running machine*

```text
stop()
```

Stop a RUNNING machine where it is (the stub's interrupt) and survey the stop.

Reply: `interrupted` (`true` with the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine) and `average_speed`; `false` when it was already
stopped, with `last_stop` and a `note`). An interrupt not answered in time, or a run the
console started whose frame counter still moves, is `status: INVALID` (`not_settled`): the
machine stays marked RUNNING, asking again is allowed and nothing counts the attempts, and
if `stop` fails as well, `close` then `start` is the way out. An interrupt answered by
something that is not a stop, a connection that failed, or a stop that was read and could
not be surveyed, is `session_broken`, and it LATCHES as `run_to`'s does. A run by frames
bailed out as `no_progress` is brought back here: the interrupt is its proof of rest.

Reference: REFERENCE.md, Advancing the machine.

Takes no argument.

| reply field | type |
|---|---|
| `average_speed` | object |
| `cpu` | string |
| `dasm` | array or object |
| `errorlog` | object |
| `frame` | integer or object |
| `interrupted` | boolean |
| `note` | string |
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
    "wall_at": "2026-10-24T16:07:10+00:00"
  }
}
```
<!-- scry-reference:end stop -->

<!-- scry-reference:begin trace -->
## `trace`

*Trace what a run executes*

```text
trace(milliseconds=0, frames=0, dest="", seconds=60.0, cpu="", noloop=false)
```

Run as `run_for` does with MAME's own tracer on one cpu, then hand back every address
that cpu executed, joined to its symbols. It takes no `ref`: the window is frames or
milliseconds, and no trace runs until a place is reached (`run_to` goes there, untraced).

Arguments: `milliseconds` or `frames` as in `run_for` (at most 5026 frames or
98143 ms; with `noloop`, 1648 and 32920). `dest`: an absolute
path not there yet; empty lands in the scratch. `seconds`: the wall-clock bound.
`cpu`: the visible one when empty. `noloop=True`: only for exact
`count`s and `instructions` (every instruction written), never for which addresses ran.
Needs the machine STOPPED (else `not_stopped`).

Reply: `run_for`'s, plus `trace`: `cpu`, `path` (the tracer's file), `bytes`, `set_path` (one
row per executed address, ascending: `addr`, `symbol` when placed, `count` under `noloop`),
`instructions`, `addresses`, `unplaced`, `symbols` (per routine: `symbol`, `addr`, `addresses`,
`first`, `last`, `instructions` under `noloop`; first 64), `symbols_total`,
`truncated`, `noloop`, `note`. Refused before anything is armed: an existing `dest` or
`<dest>.set.jsonl`, a cpu with no disassembler (`no_channel`). A trace with no instruction line
is `readback_refused`; a tracer that could not be closed is `readback_refused` with
`trace.closed: false` (unavailable when the session broke); an INVALID run carries `trace`
(`path`, `bytes`, `closed`) and no set file.

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
| `cpu` | string or object |
| `cycles` | integer |
| `dasm` | array |
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
  "dasm": [
    "0029EE: 51C8 FFFE dbra    D0, $29ee",
    "0029F2: 4CDF 3FFF movem.l (A7)+, D0-D7/A0-A5",
    "0029F6: 4E75      rts",
    "0029F8: 0000 0796 ori.b   #$96, D0",
    "0029FC: 0000 4854 ori.b   #$54, D0",
    "002A00: 0000 4860 ori.b   #$60, D0",
    "... 3 more"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 66062
  },
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
    "path": "$TMPDIR/mame-mcp-vr90lqz3/snap/trace-1.trace",
    "bytes": 13781,
    "set_path": "$TMPDIR/mame-mcp-vr90lqz3/snap/trace-1.trace.set.jsonl",
    "instructions": 23491,
    "addresses": 201,
    "unplaced": 0,
    "symbols": [
      {
        "symbol": "IRQ_VBLANK",
        "addr": "0x00000400",
        "addresses": 25,
        "first": "0x00000400",
        "last": "0x00000502"
      },
      {
        "symbol": "PAGE_BIT_COMPOSE_A",
        "addr": "0x00000506",
        "addresses": 4,
        "first": "0x00000506",
        "last": "0x00000516"
      },
      {
        "symbol": "ARM_LINE_COUNTER",
        "addr": "0x00000520",
        "addresses": 18,
        "first": "0x00000520",
        "last": "0x0000059a"
      },
      {
        "symbol": "MODE_CLEAR_BLITS",
        "addr": "0x00002856",
        "addresses": 15,
        "first": "0x00002986",
        "last": "0x000029ee"
      },
      {
        "symbol": "SOUND_STREAMER_ROM",
        "addr": "0x000f2446",
        "addresses": 116,
        "first": "0x000f2984",
        "last": "0x000f2df8"
      },
      {
        "symbol": "IRQ5_STREAMER_RAM",
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

<!-- scry-reference:begin series_capture -->
## `series_capture`

*Capture a series of frames*

```text
series_capture(at_frames=null, first=null, last=null, step=1, crop=null, dest="", seconds=60.0)
```

FRAMES OF THE SCREEN KEPT INSIDE MAME at emulation speed, as PNGs and one manifest:
the series `series_diff`, `region_track` and `golden_check` read, with no picture in the
reply. It runs the machine two frames past the last and stops there.

The frames, by the frame counter `run_for(frames=...)` counts, all still to come: `at_frames`
(a list, ascending) or `first`, `last` and `step`, at most 1000. `crop` `[x, y,
width, height]`, default the whole screen. `dest`: a new absolute or `~`-led directory, kept
after `close`; else one in the scratch, gone at `close` (`kept_after_close` says which).
`seconds`: the run's wall-clock bound. Needs the machine STOPPED (else `not_stopped`).

Each frame is MAME's own rendering of it, read by a frame notifier one frame late as
`gfx_film` reads its frames; a wanted frame frameskip did not draw is listed in `lost`. Its
PNG is RGB where `gfx_film`'s may be indexed: compare the two with `image_diff`.

Reply: `manifest` (its path), `count`, `first`, `last`, `crop`, `distinct` (signatures over
it), `frames_asked`, `lost` ([first, last] runs), `kept_after_close`, `frame_source`
(`frame_number`), then the run's own fields and the survey as `run_for` reports them.
`bad_argument`: a frame not ahead of the machine, a crop off the screen, a `dest` already
there; `cut_by_other_stop`: a stop cut the run before the last frame.

Reference: REFERENCE.md, Media files.

| argument | type | default |
|---|---|---|
| `at_frames` | array of integer or null | `null` |
| `first` | integer or null | `null` |
| `last` | integer or null | `null` |
| `step` | integer | `1` |
| `crop` | array of integer or null | `null` |
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
| `count` | integer |
| `crop` | array |
| `cycles` | integer |
| `distinct` | integer |
| `first` | integer |
| `frame_after` | integer |
| `frame_before` | integer |
| `frame_source` | string |
| `frames_asked` | integer |
| `kept_after_close` | boolean |
| `last` | integer |
| `lost` | array |
| `manifest` | string |
| `polls` | integer |
| `verdict` | string |

Example, from a live run:

```json
{
  "at_frames": [
    14
  ],
  "seconds": 10.0
}
```

```json
{
  "summary": "series_capture: 1 frame 14..14, 1 distinct, manifest $TMPDIR/mame-mcp-vr90lqz3/series/series-1/manifest.json",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 12,
  "frame_after": 16,
  "cycles": 1277930,
  "polls": 4,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 19,
  "pc": "0x00002986",
  "cpu": ":maincpu",
  "frame": 16,
  "regs": {
    "D0": "0x00005845",
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
    "PC": "0x00002986"
  },
  "dasm": [
    "002986: 51C8 FFFE           dbra    D0, $2986",
    "00298A: 33FC 0000 0070 0000 move.w  #$0, $700000.l",
    "002992: 33FC 0000 0070 0004 move.w  #$0, $700004.l",
    "00299A: 33FC 0000 0070 000C move.w  #$0, $70000c.l",
    "0029A2: 33FC 000F 0070 000E move.w  #$f, $70000e.l"
  ],
  "errorlog": {
    "lines_total": 0,
    "truncated": false,
    "lines": [],
    "mark": 66062
  },
  "manifest": "$TMPDIR/mame-mcp-vr90lqz3/series/series-1/manifest.json",
  "count": 1,
  "first": 14,
  "last": 14,
  "distinct": 1,
  "crop": [
    0,
    0,
    336,
    252
  ],
  "lost": [],
  "frames_asked": 1,
  "kept_after_close": false,
  "frame_source": "frame_number",
  "thread_errors": 0,
  "console_reruns": 0,
  "resent": 0
}
```
<!-- scry-reference:end series_capture -->

**On an indexed screen a series frame is an RGB PNG and a film frame an indexed one**, on purpose: the film's index is the pen, which a colour PNG would lose, and a series is for comparing what the screen showed. So the same frame from the two never has the same bytes and a golden of one never matches the other by `golden_check`; `image_diff` reads the colours a picture shows, so it compares them.
