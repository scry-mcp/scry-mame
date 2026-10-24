# The Session tools

A session is one MAME under the debugger, parked STOPPED by `start` and ended by `close`. The contract every family shares is in [REFERENCE.md, The session](../../REFERENCE.md).

<!-- scry-reference:begin start -->
## `start`

*Start a MAME session*

```text
start(system, rompath, reference_rom, symbols="", reference_addr="0x0", inipath="", boot_seconds=8.0, shared=false, background=null, boot_lua="", env=null, bases=null, reference_base="0x0", display="", stub_port=0, state_dir="", throttle_from_frame=0, types="", cfg="", binary="", presence=true, view="")
```

Start MAME with its gdbstub, parked STOPPED and checked against the reference image.

Arguments (every path absolute; `rompath`, `inipath`, `state_dir` directories, the rest files):
- `system`, `rompath`; `binary` (omitted: `MAME_BINARY`, else the PATH's `mame`).
- `reference_rom`, `reference_addr` (`0x`), `reference_base` (`0x`, the image's first byte).
- `symbols`: a YAML or the linker's five-column map, the first cpu's. `bases`
  maps each non-CODE class of a map to a `0x` base or to `rom`. `types`: a file of `name:
  format` lines. Several cpus: `symbols` `{cpu: path}`, `bases` `{cpu: {class: base}}`,
  `types` `{cpu: file}`.
- `shared=True`: somebody WATCHES (big window, real speed); `display` (`main` | `secondary`),
  its screen, needs it. `throttle_from_frame`: flat out until it.
- `background`: `true` behind, your focus kept, watched (`shared`) or not; `false` in front;
  omitted, by `shared`.
- `boot_lua`, an EXISTING harness file, never Lua text (never `manager.machine:exit()`),
  `env` for it, `inipath`,
  `boot_seconds` (the stub's wait), `stub_port` (`0`: a free one).
- `state_dir` (empty: disposable; else kept), `cfg`.

Refused before any spawn: a live session, a missing file, a cpu
the machine lacks, a class with no base, `bases` beside a YAML file, a bad `types` line,
a `stub_port` in use,
a `reference_addr` OUTSIDE the image; a `system` the binary lacks. A stranger on your
`stub_port`: `host_failed`. 16 bytes that do not match: `readback_refused`, closed.

Reply: `system`, `binary`, `binary_origin`, `version`, `pid`, `stub_port`, `scratch_dir`,
`state_dir`, `cfg`, `debugger`, `errorlog_path`, `stdout_path`, `rom_check`,
`symbols_total`, `symbols_typed`, `symbols_format`, `symbols_by_class` (first cpu),
`symbols_by_cpu`, `registers`, `pc`, `frame`, `frame_symbol`, `machine`, what
reached the driver (`env`, `display`, `view`, `background`, `flags`, `throttle_from_frame`,
`boot_lua_path`), `views`, `presence`, `declarations` and `start_retries`.

Reference: REFERENCE.md, The session.

| argument | type | default |
|---|---|---|
| `system` | string | required |
| `rompath` | string | required |
| `reference_rom` | string | required |
| `symbols` | string or object | `""` |
| `reference_addr` | string | `"0x0"` |
| `inipath` | string | `""` |
| `boot_seconds` | number (> 0, <= 600.0) | `8.0` |
| `shared` | boolean | `false` |
| `background` | boolean or null | `null` |
| `boot_lua` | string | `""` |
| `env` | object or null | `null` |
| `bases` | object or null | `null` |
| `reference_base` | string | `"0x0"` |
| `display` | one of `""`, `"main"`, `"secondary"` | `""` |
| `stub_port` | integer (>= 0, <= 65535) | `0` |
| `state_dir` | string | `""` |
| `throttle_from_frame` | integer | `0` |
| `types` | string or object | `""` |
| `cfg` | string | `""` |
| `binary` | string | `""` |
| `presence` | boolean | `true` |
| `view` | string | `""` |

- `presence`: Draw an edge around the emulator's window while this session is open: dim while idle, bright while a call runs the machine. No capture, recording or screen reader of this server carries it; a recording of the window made from outside does.
- `view`: What `snapshot` and `record` render through, for the whole session: empty, the emulated screen alone, at its own size (MAME's `native`); else a layout view by prefix, MAME's own default when none matches (the reply's `views` lists the set's, and `view` says which was taken).

| reply field | type |
|---|---|
| `after_s` | number |
| `alive` | boolean |
| `background` | boolean |
| `binary` | string |
| `binary_origin` | string |
| `boot_lua_path` | string |
| `cfg` | object |
| `debugger` | object |
| `declarations` | object |
| `dial_attempts` | array |
| `display` | string |
| `env` | object |
| `error` | string |
| `errorlog_path` | string |
| `flags` | array |
| `frame` | integer or object |
| `frame_symbol` | string or object |
| `machine` | object |
| `note` | string |
| `pc` | string |
| `phase` | string |
| `pid` | integer |
| `presence` | boolean |
| `registers` | array |
| `reply` | string |
| `rom_check` | string |
| `scratch_dir` | string |
| `start_retries` | array |
| `state_dir` | string |
| `stdout_kept` | string |
| `stdout_path` | string |
| `stdout_tail` | string |
| `stub_port` | integer |
| `symbols_by_class` | object |
| `symbols_by_cpu` | object |
| `symbols_format` | string |
| `symbols_total` | integer |
| `symbols_typed` | integer |
| `system` | string |
| `throttle_from_frame` | integer |
| `version` | string or object |
| `view` | string or object |
| `views` | array or object |

Example, from a live run:

```json
{
  "binary": "/path/to/mame-builds/stock-9c28def3/mamed",
  "system": "circus",
  "rompath": "/path/to/roms",
  "reference_rom": "$TMPDIR/mame-live-matrix-4d06f0dea223/f2-image/circus.ref",
  "reference_addr": "0x1000",
  "reference_base": "0x1000",
  "inipath": "$TMPDIR/mame-live-matrix-4d06f0dea223/ini-no-joystick",
  "boot_seconds": 30.0,
  "background": false,
  "presence": false
}
```

```json
{
  "summary": "start circus on /path/to/mame-builds/stock-9c28def3/mamed (argument): rom_check OK, 0 symbols, pc 0x00001000, machine: 1 cpu, 1 screen, 15 ROM files, 4 regions, 2 shares",
  "status": "ok",
  "system": "circus",
  "binary": "/path/to/mame-builds/stock-9c28def3/mamed",
  "binary_origin": "argument",
  "version": "0.289 (unknown)",
  "pid": 32476,
  "stub_port": 62785,
  "scratch_dir": "$TMPDIR/mame-mcp-qy6dfwnf",
  "state_dir": "",
  "cfg": {
    "available": false,
    "why": "no cfg was given, so MAME runs on its defaults"
  },
  "debugger": {
    "attached": "gdbstub",
    "note": "MAME runs with -debug under this stub. A capture taken at one of this session's stops can land a frame away from an autoboot golden taken by a frame notifier at the same count, in a scene that changes every frame: compare a live capture wit ... (255 characters)"
  },
  "errorlog_path": "$TMPDIR/mame-mcp-qy6dfwnf/error.log",
  "stdout_path": "$TMPDIR/mame-mcp-qy6dfwnf/stdout.log",
  "rom_check": "OK",
  "symbols_total": 0,
  "symbols_typed": 0,
  "symbols_format": "none",
  "symbols_by_class": {},
  "symbols_by_cpu": {},
  "registers": [
    "A",
    "X",
    "Y",
    "P",
    "SP",
    "PC"
  ],
  "pc": "0x00001000",
  "frame": 0,
  "frame_symbol": "frame",
  "env": {},
  "display": "",
  "view": "native",
  "views": [
    "Color Overlay",
    "Screen 0 Standard (4:3)",
    "Screen 0 Pixel Aspect (31:32)",
    "Cocktail"
  ],
  "background": false,
  "flags": [
    "-window",
    "-nomaximize",
    "-resolution",
    "320x240",
    "-nothrottle",
    "-screen0",
    "... 1 more"
  ],
  "throttle_from_frame": 0,
  "boot_lua_path": "$TMPDIR/mame-mcp-qy6dfwnf/boot.lua",
  "presence": false,
  "machine": {
    "cpus": 1,
    "spaces": 1,
    "address_map": 10,
    "regions": 4,
    "shares": 2,
    "screens": 1,
    "rom_files": 15
  },
  "declarations": {
    "persistent": false,
    "path": {
      "available": false,
      "why": "no `symbols` file was given, so nothing can be re-resolved by name: declarations are by address and die with this session"
    },
    "key": {
      "available": false,
      "why": "no `symbols` file was given, so nothing can be re-resolved by name: declarations are by address and die with this session"
    },
    "held": 0,
    "fingerprint": "cbc781678431dfe1",
    "rearm": {
      "rearmed": [],
      "stale": [],
      "unresolved": [],
      "unarmable": [],
      "evaluated": []
    },
    "comments": {
      "rearmed": [],
      "stale": [],
      "unresolved": [],
      "unarmable": []
    }
  },
  "start_retries": []
}
```
<!-- scry-reference:end start -->

**A failed reference check closes the session**, because a lying session left alive is reachable by the next call.

**`start` asks which name the frame counter answers to**, because a board with no screen device has none ([Advance](advance.md), *The frame counter*, says what that changes).

**The wait.** A MAME that exits during it ends it at once, and the refusal says it exited and with which code rather than that the stub did not answer: the two send a reader to different places. One still alive at the end is `session_broken` with `stdout_kept`, a copy of what it printed saved before the scratch is deleted, because a hang nobody can read cannot be told from a slow boot or a port somebody else took.

**The stub is proved to be this launch's MAME by its pid, never by its port.** A connected stub leaves nothing listening, so a second MAME told the same port listens beside a live session and a dial reaches whichever listens first. So `start` asks which process listens and which holds the far end of its one connection (through `lsof`, a host dependency), and never dials or keeps another's. On a port `start` picked that is a relaunch on another port; on the caller's own `stub_port` it is `host_failed` naming the pid, since another launch there would meet the same process.

**The first connection that goes through is the only one `start` makes.** MAME's stub closes its listening socket the moment it accepts, while the kernel completes a dial long before the boot reaches the debugger; dialling again would leave MAME refusing every later connection, which reads as a stub that never listened. So the boot waits for the debugger's banner before it asks (a stub without the thread patch fills its target description at the debugger's first stop). Nothing in MAME's source orders the banner against the stop, so the rule rests on observation, and a build that never prints it costs each start its whole `boot_seconds`.

**What is launched again and what is not.** A death BY A SIGNAL before the gdbstub answers (MAME can die inside its own Lua console thread at boot, which the server can only react to), a live stub that answers without being ready, and a port another process took first are launched again, a bounded number of times. An EXIT CODE (missing ROMs, an unknown system, a bad flag) or an assertion's abort would answer the same again, so it is refused at once, as is a stub with no description of the board's FIRST cpu (`no_channel`: the build cannot serve that board). A death after `start` returned is not relaunched, because its state is gone.

**`start_retries` is the evidence of the attempts, and it is always in the reply**, because the scratch holding MAME's words is deleted with each attempt. `[]` means the first launch answered, never a missing field.

**The machine runs under the debugger, and `start` and `status` say so in `debugger`.** A capture at one of this session's stops and an autoboot golden at the same frame count can land a frame apart in a scene that changes every frame; the `note` lets that be read as the method and not as a regression.

**Which MAME runs is resolved for each launch, and said.** The first rung holding a value (`binary`, `MAME_BINARY`, the PATH's `mame`) is taken, and one naming no executable is refused, never passed over for the next: a caller who named a build and got another would be measuring the wrong emulator.

**Every input file has to be a FILE, and a directory is refused at the argument**, because `exists()` answers yes to a folder and what refuses it would arrive out of the spawn, naming a path and not the argument. A file that is there and wrong is the caller's argument too, never a failure of the tool.

**A symbol table belongs to one cpu**, because each cpu runs its own program: the main cpu's `irq_vblank` says nothing about the sub's. `symbols` as one path is the FIRST cpu's table; as `{cpu: path}`, one per cpu, and then `bases` and `types` are keyed by cpu too (the other shape is refused, since it does not say whose program it describes). The `symbols_*` totals describe the first cpu's table; `symbols_by_cpu` counts each.

**`boot_lua` is chained after the server's own script**, so `boot_lua_path` is the composed script, never the path passed.

**`stub_port` is the gdbstub's**, named so beside `input`'s `port`, which is MAME's input port tag. `0` takes a port the kernel hands out as free; a named port is refused if not free, since a silent swap would leave the caller's other client talking to nothing.

**`cfg` installs the project's `.cfg` where MAME reads it, and proves MAME read it.** Without it a live session plays on MAME's generic defaults with nothing saying so. MAME prints a parse error as an OSD warning on stderr and never in `error.log`, which only `logerror` writes, so the check reads stderr; a session booted on the defaults is closed and the start is INVALID. The project's file is never touched, and `cfg.changed` on `close` says whether MAME rewrote the copy, which a caller deciding to commit a cfg wants to know.

**`display` and window placement.** Left empty, `display` is `WINDOW_SHARED_DISPLAY`, else the secondary; on a run nobody watches it is refused, since the helper would ignore it on a stderr no caller sees. Placement comes from the helper `WINDOW_APP` names, so no project re-derives it; its absence degrades to a small window. Never `-video none` by hand: on macOS it takes over the display.

**Flying to a late scene: `throttle_from_frame=N`.** MAME's debugger console has no throttle command and the stub speaks nothing but the debugger; what CAN switch the throttle is Lua, and the one Lua a launch can run is the autoboot script. So `start` writes a boot harness and adds `-nothrottle`, and the harness lifts the throttle on arrival at the frame, logging `MAME_MCP throttled from frame N` so `log_wait` proves it. It is decided at launch, at a FRAME; the live switch is `throttle`.

**The arrival is where a real-speed measurement begins.** `close` reports `average_speed` over the last run window, which opens at `resume`, so a fly-then-play run would blend the fast ramp with real-speed play. `log_wait` on the mark proves the fly is done AND resets the window to that instant.

**A system the binary does not carry refuses `start`, in MAME's own words.** The `-listxml` question is put before the boot and collected after it, in the seconds the boot already spends waiting for the gdbstub, so it costs nothing; the refusal therefore arrives after the spawn, and the guard kills the emulator and deletes the scratch. A `-listxml` that fails for any OTHER reason leaves the start working with the sections only it backs empty and the reason in the `note`: a debug session must not be blocked on an inventory. `machine` in the reply is counts alone, the rows are in `machine_map`.

<!-- scry-reference:begin status -->
## `status`

*Session status*

```text
status()
```

Whether a machine is alive, and which one. Safe on a running machine; a stop it finds
the machine reached on its own is recorded and reported in `stopped_on_its_own`.

Reply (`alive` and `running` are the `session` block's): with no machine, a `note` when the
server closed the last session after an hour with no call; with `exit_code` and a `note` when
MAME died under the session (`close` collects its last words before anything is deleted); when
alive `system`, `pid`, `stub_port`, `scratch_dir`, `state_dir`, `cfg`, `presence` (`true` drawn,
`false` asked off, or why not), `debugger` (`attached`, and a `note`: a capture taken at a stop
here can land a frame away from an autoboot golden), `fingerprint` (the build the declarations
are judged against, the first cpu's) and `fingerprints` (each cpu's), `errorlog_path`,
`stdout_path`, `pc` (the machine's, read now; unavailable with why while it runs or once the
session broke: `last_stop.pc`), `last_stop` (`stop_seq`, `pc`, `cpu`, `frame`, `cause`,
`since_s`, `wall_at`; the park after `start` is stop 1), `in_debugger` (`breakpoints`, `watches`
(the change watches) and `regpoints`: each `ref` this server armed in the debugger, and its
`cpu`), `threads` (the stub's thread per cpu; empty without the thread patch), `cpu_tags` (what
each is doing is `cpu_info`'s), `frame_symbol` (the frame counter's name as `start` asked it,
unavailable on a board with none), and, always present, `console_pending` (Lua lines sent and
not yet evaluated, which `close` drains before its `quit`), `throttles_pending` (`tag`, `on`)
and `tallies_pending_removal` (`tally_id`, `call`), where a switch that landed is its row
leaving. `broken` (absent on a healthy session) says why it can no longer be trusted: the
machine is then asked nothing, and the way out is `close`, then `start`.

Reference: REFERENCE.md, The session.

Takes no argument.

| reply field | type |
|---|---|
| `cfg` | object |
| `console_pending` | integer |
| `debugger` | object |
| `errorlog_path` | string |
| `fingerprint` | string |
| `fingerprints` | object |
| `frame_symbol` | string or object |
| `in_debugger` | object |
| `note` | string |
| `pc` | string or object |
| `pid` | integer |
| `presence` | boolean |
| `scratch_dir` | string |
| `state_dir` | string |
| `stdout_path` | string |
| `stub_port` | integer |
| `system` | string |
| `tallies_pending_removal` | array |
| `threads` | object |
| `throttles_pending` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "status: no machine",
  "status": "ok"
}
```
<!-- scry-reference:end status -->

<!-- scry-reference:begin close -->
## `close`

*Close the MAME session*

```text
close(detail=false)
```

End the session: MAME is asked to `quit` through its console and killed only if it has not
gone within the grace period. The scratch (snapshots included) is deleted; a `state_dir` stays.
Works on a RUNNING machine too. Refuses nothing: with no session it answers `closed: false`.

Reply: `closed`, `stdout_tail` and `errorlog_tail` (the last words of each channel, read before
the scratch goes) when the end was not a clean `quit` with exit code 0, or with `detail=True`,
else `omitted` names them with `how`; `ended_by` (`quit`: a clean exit that wrote its cfg;
`exited`: it exited and wrote none; `killed`: SIGKILL after the grace period; `died`: it had
already exited; `none`: no session), `state_written`, `exit_code` (unavailable with its `why`
when SIGKILLed and still not reaped: an emulator may still be on the machine), `cfg`
(`installed_path`, `changed`: did MAME rewrite the copy, `available: false` with its `why` when
a file could not be read back; unavailable when no cfg was given; the repo's file is never
touched), `console_pending_before`, `console_drained` and a `note` (the Lua pipe, emptied
before the `quit`), and `average_speed` when it ends a run (`percent` with the two deltas, or
`available: false` with its `why`; absent on a broken session). The `session` block describes
the state BEFORE closing (so `altered` is the truth about the session that ended), plus any
throttle found not applied: `alive: true` beside `closed: true` is that, not a contradiction.

Reference: REFERENCE.md, The session.

| argument | type | default |
|---|---|---|
| `detail` | boolean | `false` |

| reply field | type |
|---|---|
| `average_speed` | object |
| `cfg` | object |
| `closed` | boolean |
| `console_drained` | integer |
| `console_pending_before` | integer |
| `ended_by` | string |
| `errorlog_tail` | string |
| `note` | string |
| `state_written` | boolean or object |
| `stdout_tail` | string |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "close: quit, exit code 0, last words left out (see `omitted`)",
  "status": "ok",
  "closed": true,
  "omitted": [
    "stdout_tail",
    "errorlog_tail"
  ],
  "how": "close(detail=True) keeps the channels' last words on a clean quit too; once a close has answered they are gone with the scratch",
  "ended_by": "quit",
  "exit_code": 0,
  "state_written": true,
  "cfg": {
    "available": false,
    "why": "no cfg was given, so MAME runs on its defaults"
  },
  "average_speed": {
    "percent": 2076.74,
    "emulated_s": 83.121073,
    "wall_s": 4.002478
  },
  "console_pending_before": 0,
  "console_drained": 0
}
```
<!-- scry-reference:end close -->

**`close` quits through the console before it kills, and says which it did.** MAME writes `cfg/` and `nvram/` on a clean exit and ignores SIGTERM, and the console's `quit` only schedules the exit, so a machine stopped in the debugger is let run one step for it to happen. The endings are not the same ending and `closed: true` would say the same about all of them, hence `ended_by`.

**`average_speed` is the host's**, from the debugger's emulated clock over the wall clock, because MAME suppresses its own speed line on a debugger exit. An unreadable clock is said in that field and `close` answers all the same: it is the one way out of every state.

**The console's pipe is emptied before the exit is asked for**, because a chunk MAME's Lua state still holds at `quit` can take its collector down on the way out; the `note` names what could not be drained, so an ugly exit code has its likely cause beside it.

<!-- scry-reference:begin focus -->
## `focus`

*Show another cpu*

```text
focus(cpu)
```

Make `cpu` (`subcpu` or `:subcpu`) the debugger's VISIBLE cpu, and read it back off the
console's `cpulist`. Needs the machine STOPPED (else `not_stopped`).

THE MODEL, every tool's: no `cpu` is the visible cpu, which a stop moves to the cpu that
stopped and a release back to it (`cpu_info`'s `visible`); `cpu` names another, and the
visible one stays (`step` alone shows the cpu it steps). A reply that touches a cpu names
it (`cpu`). A declaration keeps its cpu, its `ref` resolving in that cpu's symbols. `rpset`
names no cpu: a registerpoint is the visible cpu's. Another cpu's registers and memory need
the thread patch.

On a build whose gdbstub serves a thread per cpu (`status`'s `threads`) it is the stub's `Hc`,
which ignores no cpu and releases nothing, and the reply PROVES nothing ran: `machine_ran:
false`, the `frame`, and `unchanged`, the cpus whose whole register block read the same before
and after (`unread`: one whose block the stub refuses). Without that patch it is the console's
own `focus`, which IGNORES every other cpu (a breakpoint or watch on one has no effect until
`debug("observe <cpu>")`) and, when it ignores the visible cpu, RUNS until `cpu` executes:
`ignored` lists them, and a run adds the survey of where it stopped.

Refused: a cpu the machine lacks (`unknown_ref` with `cpu_tags`); on the patched stub, a cpu the
debugger ignores (`bad_argument`). A visible cpu read back other than `cpu` is
`readback_refused`; a console run that reached no stop on an observed cpu is `not_settled`.

Reply: `cpu` (read back), `was`, `via` (`stub` or `console`), `machine_ran`, and `frame`,
`unchanged`, `unread` (stub) or `ignored` and on a run the survey: `cause`, `stop_seq`, `cpu` (the stop's), `pc`, `regs`, `frame`, `dasm`, `errorlog` (not `log`), `watches`, `watch_hit` or `regpoint_hit` if one stopped it (REFERENCE.md, Advancing the machine) (console).

Reference: REFERENCE.md, The session.

| argument | type | default |
|---|---|---|
| `cpu` | string | required |

| reply field | type |
|---|---|
| `cpu` | string |
| `dasm` | array |
| `errorlog` | object |
| `frame` | integer or object |
| `ignored` | array |
| `machine_ran` | boolean |
| `pc` | string |
| `regpoint_hit` | object |
| `regs` | object |
| `stop_seq` | integer |
| `unchanged` | array |
| `unread` | array |
| `via` | string |
| `was` | string or object |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "cpu": "maincpu"
}
```

```json
{
  "summary": "focus: :maincpu visible, was :maincpu, nothing ran (stub)",
  "status": "ok",
  "cpu": ":maincpu",
  "was": ":maincpu",
  "via": "stub",
  "machine_ran": false,
  "frame": 0,
  "unchanged": [
    ":maincpu",
    ":subcpu"
  ]
}
```
<!-- scry-reference:end focus -->

<!-- scry-reference:begin rom_check -->
## `rom_check`

*Check the ROM against its image*

```text
rom_check(reference_rom, reference_addr="0x0", reference_base="0x0", cpu="")
```

Re-validate the session: the 16 bytes at `reference_addr` of `cpu` (`subcpu`; the visible
one when empty) against the reference image `reference_rom` (placed at `reference_base`), a
repeated read for determinism, and the cost of a query. Each cpu is served by its own thread of the gdbstub's thread patch (`status`'s `threads`); a build without it serves its first cpu alone, whatever is visible, and refuses another (`bad_argument`).

Reply: `rom_check` (`OK`), `deterministic`, `query_s`, `cpu` (the one read). The three
arguments come again on every call (`state_load` checks against the image `start` held; this
is the check a caller points where it likes), with `cpu` naming the image's cpu once a stop
has made another one visible; a mismatch is `readback_refused`, naming the cpu read and both
sides. It is about the live machine, never about the build. Needs the machine STOPPED (else `not_stopped`).

Reference: REFERENCE.md, The session.

| argument | type | default |
|---|---|---|
| `reference_rom` | string | required |
| `reference_addr` | string | `"0x0"` |
| `reference_base` | string | `"0x0"` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `cpu` | string or object |
| `deterministic` | boolean |
| `query_s` | number |
| `rom_check` | string |

Example, from a live run:

```json
{
  "reference_rom": "$MAME_LIVE_BENCH/m68k-dual/disasm/img/radendur_maincpu.bin",
  "reference_addr": "0x0"
}
```

```json
{
  "summary": "rom_check :maincpu: OK, 1.286 ms per query",
  "status": "ok",
  "rom_check": "OK",
  "deterministic": true,
  "query_s": 0.001286,
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end rom_check -->
