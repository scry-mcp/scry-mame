# The Session tools

A session is one MAME under the debugger, parked STOPPED by `start` and ended by `close`. The contract every family shares is in [REFERENCE.md, The session](../../REFERENCE.md).

<!-- scry-reference:begin start -->
## `start`

*Start a MAME session*

```text
start(system, rompath, reference_rom, symbols="", reference_addr="0x0", inipath="", boot_seconds=8.0, shared=false, background=null, boot_lua="", env=null, bases=null, reference_base="0x0", stub_port=0, state_dir="", throttle_from_frame=0, types="", cfg="", binary="", presence=true, view="")
```

Start MAME with its gdbstub, parked STOPPED and checked against the reference image.

Paths are absolute or `~`-led: `rompath`, `inipath`, `state_dir` directories, the rest
files. The check: `reference_rom`, `reference_addr`, `reference_base` (`0x`, the image's first
byte).
`symbols`, `bases`, `types`: one value, or `{cpu: ...}` per cpu.
`shared=True`: somebody watches (a window scaled to be seen, real speed).
`background`: behind, the caller's focus kept; independent of `shared`, whose default it
follows. `throttle_from_frame`: flat out until it.
`boot_lua`: a harness file, not Lua text.

Refused before MAME boots: a live session, an unknown cpu, a class with no base, `bases`
beside a YAML file, a bad `types` line, a busy `stub_port`, a `reference_addr` outside the
image (a `shared` start first asks MAME `-listxml`, whose time comes before that refusal).
A mismatch: `readback_refused`, closed.

Reply: `system`, `pid`, `stub_port`, `rom_check`, `pc`, `frame`, `start_retries`,
`recommended_release` (0.289); another release boots with a `note` saying so.

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
| `stub_port` | integer (>= 0, <= 65535) | `0` |
| `state_dir` | string | `""` |
| `throttle_from_frame` | integer | `0` |
| `types` | string or object | `""` |
| `cfg` | string | `""` |
| `binary` | string | `""` |
| `presence` | boolean | `true` |
| `view` | string | `""` |

- `presence`: Draw an edge around the emulator's window while this session is open: dim while idle, bright while a call runs the machine. No capture of this server carries it.
- `view`: What `snapshot` and `record` render through: empty, the emulated screen at its own size; else a layout view by prefix (`views` lists them, `view` says which was taken).

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
| `env` | object |
| `error` | string |
| `errorlog_path` | string |
| `flags` | array |
| `frame` | integer or object |
| `frame_symbol` | string or object |
| `machine` | object |
| `pc` | string |
| `phase` | string |
| `pid` | integer |
| `presence` | boolean |
| `recommended_release` | string |
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
  "binary": "~/.local/share/scry-bench/mame/m68k-dual/upstream/radendu",
  "system": "radendur",
  "rompath": "~/.local/share/scry-bench/mame/m68k-dual/run/mame_roms",
  "reference_rom": "~/.local/share/scry-bench/mame/m68k-dual/disasm/img/radendur_maincpu.bin",
  "reference_addr": "0x0",
  "boot_seconds": 25.0,
  "presence": false,
  "inipath": "/path/to/scry-mame/tests/live/fixtures/ini-no-joystick",
  "symbols": "~/.local/share/scry-bench/mame/m68k-dual/disasm/symbols-radendur_maincpu.yaml"
}
```

```json
{
  "summary": "start radendur on ~/.local/share/scry-bench/mame/m68k-dual/upstream/radendu (argument): rom_check OK, 64 symbols, pc 0x000f2034, machine: 2 cpus, 1 screen, 22 ROM files, 4 regions, 2 shares",
  "status": "ok",
  "system": "radendur",
  "binary": "~/.local/share/scry-bench/mame/m68k-dual/upstream/radendu",
  "binary_origin": "argument",
  "version": "0.289 (unknown)",
  "pid": 8765,
  "stub_port": 63701,
  "scratch_dir": "$TMPDIR/mame-mcp-nfbv0wdj",
  "state_dir": "",
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "debugger": {
    "attached": "gdbstub",
    "note": "MAME runs with -debug under this stub. A capture taken at one of this session's stops can land a frame away from an autoboot golden taken by a frame notifier at the same count, in a scene that changes every frame: compare a live capture wit ... (255 characters)"
  },
  "errorlog_path": "$TMPDIR/mame-mcp-nfbv0wdj/error.log",
  "stdout_path": "$TMPDIR/mame-mcp-nfbv0wdj/stdout.log",
  "rom_check": "OK",
  "symbols_total": 64,
  "symbols_format": "yaml",
  "symbols_by_class": {},
  "symbols_by_cpu": {":maincpu": 64},
  "registers": ["D0", "D1", "D2", "D3", "D4", "D5", "... 12 more"],
  "pc": "0x000f2034",
  "frame": 0,
  "frame_symbol": "frame",
  "view": "native",
  "views": ["Screen 0 Standard (4:3)", "Cocktail"],
  "background": true,
  "flags": ["-window", "-nomaximize", "-resolution", "320x240", "-nothrottle", "-screen0", "... 1 more"],
  "boot_lua_path": "$TMPDIR/mame-mcp-nfbv0wdj/boot.lua",
  "presence": false,
  "machine": {
    "cpus": 2,
    "spaces": 4,
    "address_map": 32,
    "regions": 4,
    "shares": 2,
    "screens": 1,
    "rom_files": 22
  },
  "declarations": {
    "persistent": true,
    "path": "$TMPDIR/mame-live-matrix-cce0ee570094/jobs-scratch/A/mame-live-matrix-state-og793lbk/mame-debug/declarations.json",
    "key": "radendur ~/.local/share/scry-bench/mame/m68k-dual/disasm/symbols-radendur_maincpu.yaml",
    "held": 0,
    "fingerprint": "07549ca6b6e1c4ed",
    "rearm": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": [], "evaluated": []},
    "comments": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": []}
  },
  "recommended_release": "0.289"
}
```
<!-- scry-reference:end start -->

**A failed reference check closes the session**, because a lying session left alive is reachable by the next call.

**`start` asks which name the frame counter answers to**, because a board with no screen device has none ([Advance](advance.md), *The frame counter*, says what that changes).

**The wait.** A MAME that exits during it ends it at once, and the refusal says it exited and with which code rather than that the stub did not answer: the two send a reader to different places. One still alive at the end is `session_broken` with `stdout_kept`, a copy of what it printed saved before the scratch is deleted, because a hang nobody can read cannot be told from a slow boot or a port somebody else took.

**The stub is proved to be this launch's MAME by its pid, never by its port.** A connected stub leaves nothing listening, so a second MAME told the same port listens beside a live session and a dial reaches whichever listens first. So `start` asks which process listens and which holds the far end of its one connection (through `lsof`, a host dependency), and never dials or keeps another's. On a port `start` picked that is a relaunch on another port; on the caller's own `stub_port` it is `host_failed` naming the pid, since another launch there would meet the same process.

**The first connection that goes through is the only one `start` makes.** MAME's stub closes its listening socket the moment it accepts, while the kernel completes a dial long before the boot reaches the debugger; dialling again would leave MAME refusing every later connection, which reads as a stub that never listened. So the boot waits for the debugger's banner before it asks (a stub without the thread patch fills its target description at the debugger's first stop). Nothing in MAME's source orders the banner against the stop, so the rule rests on observation, and a build that never prints it costs each start its whole `boot_seconds`.

**What is launched again and what is not.** A death BY A SIGNAL before the gdbstub answers (MAME can die inside its own Lua console thread at boot, which the server can only react to), a live stub that answers without being ready, and a port another process took first are launched again, a bounded number of times. An EXIT CODE (missing ROMs, an unknown system, a bad flag) or an assertion's abort would answer the same again, so it is refused at once, as is a stub with no description of the board's FIRST cpu (`no_channel`: the build cannot serve that board). A death after `start` returned is not relaunched, because its state is gone.

**`start_retries` is the evidence of the attempts**, because the scratch holding MAME's words is deleted with each attempt; left out, the first launch answered.

**The machine runs under the debugger, and `start` and `status` say so in `debugger`.** A capture at one of this session's stops and an autoboot golden at the same frame count can land a frame apart in a scene that changes every frame; the `note` lets that be read as the method and not as a regression.

**Which MAME runs is resolved for each launch, and said.** The first rung holding a value (`binary`, `MAME_BINARY`, the PATH's `mame`) is taken, and one naming no executable is refused, never passed over for the next: a caller who named a build and got another would be measuring the wrong emulator. The build's `version` is its own first line of `-version`, and `recommended_release` the release this server is tested on: another boots with a `note` saying so, never a refusal, because which tools another release breaks is not known until one of them meets it.

**Every input file has to be a FILE, and a directory is refused at the argument**, because `exists()` answers yes to a folder and what refuses it would arrive out of the spawn, naming a path and not the argument. A file that is there and wrong is the caller's argument too, never a failure of the tool.

**A symbol table belongs to one cpu**, because each cpu runs its own program: the main cpu's `irq_vblank` says nothing about the sub's. `symbols` as one path is the FIRST cpu's table; as `{cpu: path}`, one per cpu, and then `bases` and `types` are keyed by cpu too (the other shape is refused, since it does not say whose program it describes). The `symbols_*` totals describe the first cpu's table; `symbols_by_cpu` counts each.

**`boot_lua` is chained after the server's own script**, so `boot_lua_path` is the composed script, never the path passed.

**`stub_port` is the gdbstub's**, named so beside `input`'s `port`, which is MAME's input port tag. `0` takes a port the kernel hands out as free; a named port is refused if not free, since a silent swap would leave the caller's other client talking to nothing.

**`cfg` installs the project's `.cfg` where MAME reads it, and proves MAME read it.** Without it a live session plays on MAME's generic defaults with nothing saying so. MAME prints a parse error as an OSD warning on stderr and never in `error.log`, which only `logerror` writes, so the check reads stderr; a session booted on the defaults is closed and the start is INVALID. The project's file is never touched, and `cfg.changed` on `close` says whether MAME rewrote the copy, which a caller deciding to commit a cfg wants to know.

**The window, and the host's own arguments.** A watched run (`shared=True`) opens MAME's window at the largest integer scale of the machine's first screen (as `-listxml` lists it, turned for a vertical board) that fits 1800x960: it fits a 1080p display, and an integer scale never blurs a pixel. With no size listed, MAME picks one. A run nobody watches gets a small window and `-nothrottle`. `SCRY_EMULATOR_ARGS` in the server's environment holds the host's own MAME arguments, one token a line so a value may hold a space, and they go after the server's on every start, watched or not, since both open a window; they win where both name an option, so which display the window opens on (`-screen0 screen1`) is the host's to say, never the caller's. Nothing here checks them: MAME refuses an option it does not know, and that refusal is `start`'s, as for any flag. Never `-video none` by hand: on macOS it takes over the display.

**Flying to a late scene: `throttle_from_frame=N`.** MAME's debugger console has no throttle command and the stub speaks nothing but the debugger; what CAN switch the throttle is Lua, and the one Lua a launch can run is the autoboot script. So `start` writes a boot harness and adds `-nothrottle`, and the harness lifts the throttle on arrival at the frame, logging `MAME_MCP throttled from frame N` so `log_wait` proves it. It is decided at launch, at a FRAME; the live switch is `throttle`.

**The arrival is where a real-speed measurement begins.** `close` reports `average_speed` over the last run window, which opens at `resume`, so a fly-then-play run would blend the fast ramp with real-speed play. `log_wait` on the mark proves the fly is done AND resets the window to that instant.

**A system the binary does not carry refuses `start`, in MAME's own words.** The `-listxml` question is put before the boot and collected after it, in the seconds the boot already spends waiting for the gdbstub, so it costs nothing; the refusal therefore arrives after the spawn, and the guard kills the emulator and deletes the scratch. A watched start and a `symbols` mapping wait for it before the spawn instead, since the window's size and the cpus come from it. A `-listxml` that fails for any OTHER reason leaves the start working with the sections only it backs empty and the reason in the `note`: a debug session must not be blocked on an inventory. `machine` in the reply is counts alone, the rows are in `machine_map`.

**`background` is a placement choice, not a mode.** `true` starts the window behind and keeps the caller's focus, `false` in front; left out it follows `shared`, because a watched session is the one somebody looks at.

**`boot_seconds` bounds the stub's wait, and `stub_port` `0` takes a free port.** A fixed port is refused when busy rather than swapped, so the caller's other client never talks to nothing.

**`env` is for `boot_lua` only, and `boot_lua` is never Lua text.** A harness that calls `manager.machine:exit()` would end the machine under the session.

**`state_dir` empty is disposable.** States, `cfg/` and `nvram/` go under the session's scratch (`status` names it as `scratch_dir`; its `state_dir` stays empty) and leave with it at `close`; a named directory is kept. Nothing is written into the project's tree either way.

**The reply also carries what reached the driver** (`binary_origin`, `env`, `view`, `background`, `flags`, `throttle_from_frame`, `boot_lua_path`, `debugger`, `symbols_typed`, `symbols_format`, `symbols_by_class`, `frame_symbol`, `errorlog_path`, `stdout_path`, `cfg`), so a start can be attributed from its own output.

**Also refused**: a stranger on your `stub_port` is `host_failed`; an unknown `system` is refused after the spawn, or before it on a watched start or a `symbols` mapping. `symbols` is a YAML or the linker's five-column map; `bases` maps each non-CODE class of a map to a `0x` base or to `rom`; `types` is a file of `name: format` lines; with several cpus `symbols` is `{cpu: path}`, `bases` `{cpu: {class: base}}`, `types` `{cpu: file}`. `shared=True` means somebody watches (a window scaled to be seen, real speed).

<!-- scry-reference:begin status -->
## `status`

*Session status*

```text
status()
```

Whether a machine is alive, and which one. Safe on a running machine; a stop it finds the
machine reached on its own is recorded and reported in `stopped_on_its_own`.

Reply: with no machine, a `note`; alive, `system`, `pid`, `stub_port`, `scratch_dir`,
`state_dir`, `presence`, `debugger`, `fingerprint` (`fingerprints` per cpu),
`errorlog_path`, `pc`, `in_debugger` (`breakpoints`, `watches`, `regpoints`: each `ref`,
`cpu`), `console_pending`, `throttles_pending`, `tallies_pending_removal`. Also
`last_stop` (`stop_seq`, `pc`, `cpu`, `cause`) and `broken` when the session can no longer
be trusted: `close`, then `start`.

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
  "summary": "status: no session",
  "status": "ok"
}
```
<!-- scry-reference:end status -->

**`status` is the one reader that answers on a running machine and on a broken session**, so it is where a caller learns why nothing else answers.

**`debugger` carries a `note`** that a capture taken at a stop here can land a frame away from an autoboot golden (the machine runs under the debugger); `start`'s own text says why.

**`fingerprint` is the build the declarations are judged against**: a declaration made against another build is not trusted. `threads` is empty without the stub's thread patch, and `cpu_tags` only names the cpus; what each is doing is `cpu_info`'s.

**`console_pending` and `tallies_pending_removal` are always present, `throttles_pending` when it holds a row**: Lua lines sent and not yet evaluated (`close` drains them before its `quit`), switches asked and not yet landed (`tag`, `on`), and tallies waiting to be removed (`tally_id`, `call`), where a switch that landed is its row leaving.

**`presence`** is `true` drawn, `false` asked off, or the reason it is not drawn. **`pc`** is read now; while the machine runs or once the session broke it is unavailable with why, and `last_stop.pc` is the answer.

**Also in the reply**: `cfg`, `stdout_path`, `threads` and `frame_symbol` (the frame counter's name as `start` asked it), `last_stop`'s `frame`, `since_s` and `wall_at`, and `exit_code` with a `note` when MAME died under the session.

<!-- scry-reference:begin close -->
## `close`

*Close the MAME session*

```text
close(detail=false)
```

End the session: MAME is asked to `quit` and killed only if it has not gone within the
grace period. The scratch is deleted; a `state_dir` stays. Works on a running machine;
with no session it answers `closed: false`.

Reply: `closed`, `ended_by` (`quit`, `exited`, `killed`, `died`, `none`), `cfg_written`
(MAME wrote its cfg as it quit),
`cfg` (`installed_path`, `changed`), `average_speed` (while a `resume` run was open), `note`;
`stdout_tail` and `errorlog_tail` when the end was not a clean `quit`, or with `detail=True`.
`session` is the block as it is after the close (`alive` and `running` false); a console doubt
or a throttle found not applied still rides there.

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
| `cfg_written` | boolean or object |
| `stdout_tail` | string |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "close: no session",
  "status": "ok",
  "closed": false,
  "ended_by": "none",
  "exit_code": {"available": false, "why": "no session was running"},
  "cfg_written": {"available": false, "why": "no session was running"},
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "note": "there was no session to close"
}
```
<!-- scry-reference:end close -->

**`close` quits through the console before it kills, and says which it did.** MAME writes `cfg/` and `nvram/` on a clean exit and ignores SIGTERM, and the console's `quit` only schedules the exit, so a machine stopped in the debugger is let run one step for it to happen. The endings are not the same ending and `closed: true` would say the same about all of them, hence `ended_by`.

**`average_speed` is the host's**, from the debugger's emulated clock over the wall clock, because MAME suppresses its own speed line on a debugger exit. An unreadable clock is said in that field and `close` answers all the same: it is the one way out of every state.

**The console's pipe is emptied before the exit is asked for**, because a chunk MAME's Lua state still holds at `quit` can take its collector down on the way out; the `note` names what could not be drained, so an ugly exit code has its likely cause beside it.

**The five `ended_by` values** are `quit` (a clean exit that wrote its cfg), `exited` (it exited and wrote none), `killed` (SIGKILL after the grace period), `died` (it had already exited) and `none` (no session): `closed: true` would say the same about all of them.

**`cfg`** carries `available: false` with its `why` when a file could not be read back, and is unavailable when no cfg was given; the repo's file is never touched. **`average_speed`** is `percent` with the two deltas, or `available: false` with its `why`, and absent on a broken session.

**The `session` block describes the state after closing**: `alive` and `running` are false and `altered` is false, as with no session at all; a console doubt (its tallies) or a throttle found not applied is carried over, because it stays true of what the session reported.

**Also in the reply**: `console_pending_before`, `console_drained`, `exit_code` (unavailable with its `why` when SIGKILLed and still not reaped), and `omitted` naming the tails with `how` when they are left out.

<!-- scry-reference:begin focus -->
## `focus`

*Show another cpu*

```text
focus(cpu)
```

Make `cpu` (`subcpu` or `:subcpu`) the debugger's visible cpu, read back off the console's
`cpulist`. Needs the machine STOPPED (else `not_stopped`).

With the stub's thread patch nothing runs. Without it the console's `focus` ignores every
other cpu and may run until `cpu` executes.

Refused: a cpu the machine lacks (`unknown_ref`); on the patched stub, a cpu the debugger
ignores (`bad_argument`). A visible cpu read back other than `cpu`: `readback_refused`; a
console run reaching no stop: `not_settled`.

Reply: `cpu`, `was`, `via` (`stub` or `console`), `machine_ran`; `frame`, `unchanged`,
`unread` (stub); `ignored` and, on a run, its survey (console).

Reference: REFERENCE.md, The session.

| argument | type | default |
|---|---|---|
| `cpu` | string | required |

| reply field | type |
|---|---|
| `cpu` | string |
| `following` | array of string |
| `instruction` | StopInstruction |
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
  "unchanged": [":maincpu", ":subcpu"]
}
```
<!-- scry-reference:end focus -->

**The cpu model is every tool's, and `focus` is its only direct handle.** No `cpu` acts on the visible cpu, which a stop moves to the cpu that stopped and a release back to it (`cpu_info`'s `visible`); `cpu` names another and the visible one stays (`step` alone shows the cpu it steps). A reply that touches a cpu names it. A declaration keeps its cpu, its `ref` resolving in that cpu's symbols. `rpset` names no cpu: a registerpoint is the visible cpu's. Another cpu's registers and memory need the thread patch.

**On the patched stub the reply proves nothing ran**: `machine_ran: false`, the `frame`, and `unchanged`, the cpus whose whole register block read the same before and after (`unread`: one whose block the stub refuses). It is the stub's `Hc`, which ignores no cpu and releases nothing.

<!-- scry-reference:begin rom_check -->
## `rom_check`

*Check the ROM against its image*

```text
rom_check(reference_rom, reference_addr="0x0", reference_base="0x0", cpu="")
```

Re-validate the session: 16 bytes at `reference_addr` of `cpu` (empty: the visible one)
against `reference_rom` at `reference_base`. Needs the machine STOPPED (else `not_stopped`).

A mismatch is `readback_refused`.

Reply: `rom_check` (`OK`), `deterministic`, `query_s`, `cpu`.

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
  "reference_rom": "~/.local/share/scry-bench/mame/m68k-dual/disasm/img/radendur_maincpu.bin",
  "reference_addr": "0x0"
}
```

```json
{
  "summary": "rom_check :maincpu: OK, 1.266 ms per query",
  "status": "ok",
  "rom_check": "OK",
  "deterministic": true,
  "query_s": 0.001266,
  "cpu": ":maincpu"
}
```
<!-- scry-reference:end rom_check -->

**The three arguments come again on every call** because this is the check a caller points where it likes; `state_write(method="load")` checks against the image `start` held. `cpu` names the image's cpu once a stop has made another one visible.

**Each cpu is served by its own thread of the gdbstub's thread patch** (`status`'s `threads`); a build without it serves its first cpu alone, whatever is visible, and refuses another (`bad_argument`). The check is about the live machine, never about the build; the repeated read is for determinism and `query_s` is the cost of a query.
