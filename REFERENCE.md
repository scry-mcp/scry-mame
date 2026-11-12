# scry-mame: reference

The [README](README.md) is the front door. This page holds the contract several families share: the session, what every reply carries, names for addresses. Each family's tools, with arguments, replies and the reason behind each contract, are under `docs/reference/`.

## Index

<!-- scry-reference:begin index -->
- [Session](docs/reference/session.md): [`start`](docs/reference/session.md#start), [`status`](docs/reference/session.md#status), [`window`](docs/reference/session.md#window), [`close`](docs/reference/session.md#close), [`cpu_focus`](docs/reference/session.md#cpu_focus), [`rom_check`](docs/reference/session.md#rom_check)
- [Machine](docs/reference/machine.md): [`cpu_info`](docs/reference/machine.md#cpu_info), [`machine_map`](docs/reference/machine.md#machine_map), [`log`](docs/reference/machine.md#log), [`log_wait`](docs/reference/machine.md#log_wait)
- [Names](docs/reference/names.md): [`symbols_find`](docs/reference/names.md#symbols_find)
- [Advance](docs/reference/advance.md): [`run_to`](docs/reference/advance.md#run_to), [`run_for`](docs/reference/advance.md#run_for), [`step`](docs/reference/advance.md#step), [`resume`](docs/reference/advance.md#resume), [`stop`](docs/reference/advance.md#stop), [`trace`](docs/reference/advance.md#trace)
- [Declarations](docs/reference/declarations.md): [`breakpoint_at`](docs/reference/declarations.md#breakpoint_at), [`regpoint_add`](docs/reference/declarations.md#regpoint_add), [`watch_add`](docs/reference/declarations.md#watch_add), [`declaration_list`](docs/reference/declarations.md#declaration_list), [`declaration_clear`](docs/reference/declarations.md#declaration_clear)
- [Read](docs/reference/read.md): [`read_memory`](docs/reference/read.md#read_memory), [`read_block`](docs/reference/read.md#read_block), [`registers`](docs/reference/read.md#registers), [`disassemble`](docs/reference/read.md#disassemble), [`find`](docs/reference/read.md#find), [`history`](docs/reference/read.md#history), [`memdump`](docs/reference/read.md#memdump), [`screen_map_find`](docs/reference/read.md#screen_map_find), [`screen_map_write`](docs/reference/read.md#screen_map_write)
- [Screen](docs/reference/screen.md): [`palette`](docs/reference/screen.md#palette), [`screen_view`](docs/reference/screen.md#screen_view), [`screen_signature`](docs/reference/screen.md#screen_signature), [`screen_wait`](docs/reference/screen.md#screen_wait), [`gfx_view`](docs/reference/screen.md#gfx_view), [`gfx_locate`](docs/reference/screen.md#gfx_locate), [`gfx_sweep`](docs/reference/screen.md#gfx_sweep), [`gfx_draft`](docs/reference/screen.md#gfx_draft), [`gfx_blits`](docs/reference/screen.md#gfx_blits), [`gfx_blit_source`](docs/reference/screen.md#gfx_blit_source)
- [Film](docs/reference/film.md): [`gfx_load`](docs/reference/film.md#gfx_load), [`gfx_film`](docs/reference/film.md#gfx_film), [`palette_log`](docs/reference/film.md#palette_log)
- [Scan](docs/reference/scan.md): [`scan`](docs/reference/scan.md#scan)
- [Write](docs/reference/write.md): [`write`](docs/reference/write.md#write), [`set_register`](docs/reference/write.md#set_register), [`reset`](docs/reference/write.md#reset), [`debug`](docs/reference/write.md#debug)
- [Comments](docs/reference/comments.md): [`comment_list`](docs/reference/comments.md#comment_list), [`comment_write`](docs/reference/comments.md#comment_write)
- [Lua](docs/reference/lua.md): [`input`](docs/reference/lua.md#input), [`lua`](docs/reference/lua.md#lua), [`throttle`](docs/reference/lua.md#throttle)
- [States](docs/reference/states.md): [`state_list`](docs/reference/states.md#state_list), [`state_write`](docs/reference/states.md#state_write)
- [Captures](docs/reference/captures.md): [`series_capture`](docs/reference/captures.md#series_capture), [`record`](docs/reference/captures.md#record), [`audio_record`](docs/reference/captures.md#audio_record), [`snapshot`](docs/reference/captures.md#snapshot), [`captures`](docs/reference/captures.md#captures)
- [Files](docs/reference/files.md): [`image_compare`](docs/reference/files.md#image_compare), [`audio_compare`](docs/reference/files.md#audio_compare)
- [Lists](docs/reference/lists.md): [`perform`](docs/reference/lists.md#perform), [`drive`](docs/reference/lists.md#drive), [`perform_export`](docs/reference/lists.md#perform_export)
- [Store](docs/reference/store.md): [`promote`](docs/reference/store.md#promote)
<!-- scry-reference:end index -->

## The session

A debug session has to outlive the question: a shell command is a fresh process and each question would cost a whole emulator boot, so an MCP, a long-lived process, holds the machine between them. The server does not watch a run with no end: `trace` hands back what a bounded window executed, and a count across an open-ended run is a question for a Lua tracer.

The tools: [Session](docs/reference/session.md), [Machine](docs/reference/machine.md).

**A MAME this server spawned does not outlive it, nor an abandoned session.** MAME has no reason of its own to exit and a SIGKILLed server runs no cleanup, so a guardian process beside every MAME (named `scry-mame-guardian` in the process list), in a session of its own, SIGKILLs it within one poll of the server being gone, since MAME ignores SIGTERM. A SIGTERM, a SIGHUP or a Ctrl-C to the server itself ends its machine before it leaves. On Windows the same promise is kept by a job object the server holds and places MAME in once it has started: the system closes it when the server ends, however it ends, and MAME with it. A session no tool has touched for an hour, counted from the end of the last call so a call's own wait never counts, is closed by the ordinary `close`, a running machine included; the next reply that finds no machine says so, in `no_session` and in `status`'s `note`.

**A live session is recognised from outside by the literal `mame-mcp-` in the emulator's argv, and that is a contract.** A project's own `make stop` kills by binary path and this server spawns the same binary, so the command line is all that tells them apart; a kill path that excludes the mark leaves the live session alone. It rides on `-snapshot_directory`, always emitted, and changing its spelling changes every project's kill path. A pid is a claim to verify, never a handle to signal: `close` is the ending.

**Every path argument is absolute or starts with `~`, judged at the argument.** MAME runs from a scratch directory of the server's own, so a relative path would be judged in one directory and used in another. `~` is expanded as a shell would, because no shell stands between a client and the argument. A NUL, a lone surrogate or an empty required path is refused.

**Each session has its own scratch directory, and the tools serialize on one lock**, so no project's EEPROM ends up inside the shared tool and overlapping `run_to` calls never steal each other's stops.

**A board with several cpus is addressed the way MAME's debugger addresses it.** The debugger acts on one cpu at a time, the VISIBLE one, and makes the cpu that stopped the visible one at every stop and again when it releases the machine. A call that names no `cpu` acts on the visible one; a call that names one acts on that cpu and leaves the visible one where it was, as `bp addr:cpu` does (`step` alone shows the cpu it steps). The visible cpu is read off the console's `cpulist`, never remembered. A declaration keeps its cpu and its `ref` resolves in that cpu's symbol table. What MAME cannot address by cpu is refused rather than faked: `rpset` names none, so a registerpoint is the visible cpu's. A stock gdbstub serves its first cpu alone; `patches/0004-gdbstub-one-thread-per-cpu.patch` serves one GDB thread per cpu, so every register and memory call reads its own cpu and `cpu_focus` shows a cpu without running.

**`cpu` and `space`.** `cpu` is a tag in either spelling (`subcpu` or `:subcpu`), refused `unknown_ref` naming the cpus there are. Empty, it is the visible cpu for a tool that acts or reads at a place and every cpu for one that lists or clears. `space` is MAME's own name, `program` by default; a tool takes only the spaces it implements and refuses `io` on a cpu that has none, naming the cpus that have one.

### The presence indicator

While a session holds the window, an orange edge says so: dim from `start` to `close`, bright while a call that can move the guest on or change what it holds runs, so whoever sits at the host knows whether to keep their hands off. A stopped machine is repainted only at a stop and at each console command, so once a driving call that leaves it stopped is over the server sends one command of its own (`print 0`, which moves neither pc, cycle count nor memory) and the edge goes dim. A machine left running by `resume` shows the dim edge: the indicator marks the calls, not the machine. `start(presence=False)` leaves it off, and a failure drawing it never changes any other reply. It is drawn by MAME's Lua on the UI container, which the snapshot target does not show, so `snapshot`, `record` and the screen readers never carry it.

## What every reply carries

<!-- scry-reference:begin envelope -->
| field | type |
|---|---|
| `summary` | string |
| `status` | one of `"ok"`, `"INVALID"` |
| `code` | string |
| `message` | string |
| `omitted` | array of string |
| `how` | string |
| `note` | string |
| `cancelled` | object |
| `session` | object |
| `answers_while_running` | array |
| `exit_code` | integer or object |
| `last_stop` | object |
| `stopped_on_its_own` | object |
| `broken` | string |
| `cause` | string |
| `cpu_tags` | array of string |
<!-- scry-reference:end envelope -->

**Every tool publishes its reply as its `outputSchema`**: each field is its value or `unavailable(why)`, `status` is required, and the fields an `ok` reply always carries are required of it (unless its `omitted` names them). A field that comes only under a condition says which in the tool's `Reply:` sentence.

Every reply opens with a one-line `summary` and closes with a `session` block composed after the tool's work, so it says what the machine is doing after the call (`close`'s alone describes the state before it). Alarms ride on every reply (`altered`, `broken`, `console` once a count is not zero, `throttles_not_applied`, `tallies_not_removed`, a `note`); what only counts rides on `start`, `status` and `close`.

**A reply that answers less than everything says so**: it carries `omitted`, the names it left out, and `how` brings them; one that left nothing out carries neither.

Every refusal of an argument's shape names it and comes before the emulator is touched; what only the machine can decide (`wait_expired`, `readback_refused`, `control_silent`, `not_settled`...) is refused after it was asked, and says what was asked and what it was left doing. Every number sent to the console travels with `0x`, because to MAME's expression parser a bare `d0` is a register.

**A reply that touches a cpu says which, in `cpu`.** Where the stub cannot read that cpu's registers, `regs` says `available: false` with `why`, never another cpu's file under its name. A cpu the stub does not describe, or whose byte order is not established, is `no_channel`: the order is MAME's, the endianness of the cpu's program space as `start`'s inventory read it, and it is not established when that read failed or when a known architecture measured the other way disagrees, since one of the two is wrong.

**Writing to a live machine is allowed, and every reply afterwards says the session was altered**, `debug` included. A measurement on a forced state is not a measurement of the game, and the reader three questions later has no other way to know.

**The stub's EMPTY packet is "unsupported", never "done".** A client that refuses only an `E` reply takes a packet the stub does not implement as a good answer, and `write`, `set_register` and breakpoints then report an operation that has not happened, silencing the control `run_to` relies on. So the client says no itself.

**`session.console` counts what the console channel did to this session**: `thread_errors` (the Lua reader died), `reruns` (chunks run again), `lost` (lines taken and never evaluated). They are three because a reader that restarted harmlessly and a chunk that WROTE TWICE are different events. They are counted when a lua-family call reads its answer back and once more at `close`, so a line sent and never read back (a `throttle` asked while stopped) moves none until then. The per-call fields describe one line's window: `thread_errors` and `console_reruns` ride, zeros included, on every reply that read a Lua chunk's answer back, and `resent` rides only when the line was sent again. A wrapper's own script that raises is refused by what it raised: a port or field the machine lacks is `unknown_ref`, a recording with no screen `no_channel`, anything else `unexpected_answer`; `lua`'s script is the caller's, `bad_argument`.

**A `tallies_not_removed` row stays until the session ends.** Asking again fixes the machine; the row is the record that this session counted past a removal. It rides on every reply while it holds, because the call that would naturally report it is one nobody is obliged to make. `status` lists a removal the console has not run yet (`tallies_pending_removal`), so a success is a row leaving a list the caller can see.

**A refusal is one contract.** `status` is `ok` or `INVALID`; an INVALID carries `code`, one word from a fixed table, and `message`, flat beside the context (`last_stop`, `control_hits`, `left_armed`). `verdict` is a measurement's word (`TARGET`, `TIMEOUT`, `ELAPSED`, `OTHER_STOP`) and an INVALID run carries none. A wait answers one too, `status: ok`: `TARGET` when what it waited for came, `TIMEOUT` when its bound ran out (interrupted on `run_to` and `run_for`, left running on `resume`, `log_wait`, `perform` and `drive`), `OTHER_STOP` when a stop it did not ask for ended it. What could not finish still refuses. A stop's `cause` is prose; how `close` ended is `ended_by`. `bad_argument` asks for another value, `needs_call` for another call first, which its message names. A malformed refusal (a code outside the table, an empty message) is refused where it is written, so it never looks like a verdict. A bad argument is a refusal, not an execution failure: the SDK's `isError` is for a bug, and "I could not look" is a verdict.

**The schema is strict.** An argument of the wrong TYPE never reaches a tool: the schema refuses it first, in this same envelope as `bad_argument` naming the argument. Nothing is coerced (`"16"` is not 16) except that an integer stands for a number, a value or offset also takes a `0x` string; an unknown argument name is refused, never dropped. A fixed vocabulary or range is published as `enum`, `minimum` and `maximum`; a word outside still reaches the tool and is refused there, naming the list. A vocabulary that depends on the machine publishes none.

**One spelling per concept, in every tool.** `seconds` is a call's wait, `count` how many, `first` from where, `length` how many bytes, `limit` how many rows come back, `dest` the file a call writes, `path` the file it reads, `<what>_path` any other file a reply names (always whole), `<what>_s` seconds, `<what>_at` a wall-clock instant, `<done>_by` who did it, `<list>_total` how many a list holds, listed or not. A count names what it counts and over what (`bytes_written`, `hits_in_run`, `hits_since_armed`); `hits` is always a list. `note` is one string, its sentences joined by `; `; `why` is a row's or field's reason, quoting what the console said where it rests on that; `error` is only ever the words another program answered.

**A datum that could not be read is `{"available": false, "why": ...}` in the place its value would have taken, and no reply carries a null**: whether it could not be read or does not apply here, the two differ only in their `why`.

**One spelling for each kind of number.** An address or port a reply reads back is eight hex digits (`0x0070001e`); a ref stays in the spelling a call names it back by; an offset into a block, region or share is an integer. A value or mask is `0x` text at the width it was written at; what a watch DECODES under its format is what that format reads. A span a reader acts on is rounded to the tenth of a second, a time that is itself the reading to the microsecond, and a capture row's `time_s` is at full precision since two accesses one cycle apart are nanoseconds apart. A width says its unit (`data_width_bits`, `cell_bytes`, `refresh_hz`); `size` is bytes.

**One rule for every wait.** `seconds` is the wall-clock bound of the call, or of the one wait its description names; `frames` and `milliseconds` are EMULATED time. Zero is a wait of its own kind in two places only: `resume(seconds=0)` waits for nothing, and `settle_seconds=0` never waits for a stop.

### A long wait, and a cancelled call

A wait that can run for seconds reports its progress about once a second, as MCP progress notifications. The value measures the work when the work has a size (`run_for(frames=N)`: frames done of N); every other wait reports elapsed time with no total, because a bar filling towards the bound would read as progress towards failure. Within one call the value never goes back.

A call the client cancels ends at the next poll of its wait, the way its own bound would have ended it, and answers nothing: the protocol sends no response to a cancelled request. A tool with no wait of its own runs to its end first. The next reply, whatever tool it is, says once what that call left, in `cancelled` (`tool`, `after_s`, `left`: `stopped`, `running`, `closed` or `unknown`; `earlier`, the cancelled calls no reply reported) and in its summary. A call cancelled while it waited for another did nothing and leaves no record; one that had finished its work is recorded with no end applied; a cancel after the server's last look is not seen.

Every tool ends one of three ways, and one that declares no end ends `none`:

| End | What the cancel leaves | Tools |
|---|---|---|
| `stop` | the machine stopped through `stop`'s own path; a stop the call made on its way is recorded as its own | `step`, `run_to`, `run_for`, `screen_wait`, `trace`, `series_capture`, `perform`, `input`, `record`, `audio_record` |
| `kill` | the emulator ended, with the grace that writes `cfg/` and `nvram/` when a session is up to be asked; a MAME still booting is killed at once | `start`, `close` |
| `none` | the machine as the call found it | `status`, `window`, `cpu_focus`, `cpu_info`, `rom_check`, `resume`, `stop`, `breakpoint_at`, `regpoint_add`, `watch_add`, `declaration_list`, `declaration_clear`, `comment_list`, `comment_write`, `symbols_find`, `machine_map`, `read_memory`, `read_block`, `registers`, `disassemble`, `find`, `scan`, `history`, `write`, `set_register`, `reset`, `memdump`, `snapshot`, `screen_signature`, `screen_map_find`, `screen_map_write`, `image_compare`, `audio_compare`, `palette`, `screen_view`, `gfx_view`, `gfx_locate`, `gfx_sweep`, `gfx_draft`, `gfx_load`, `gfx_blits`, `gfx_blit_source`, `palette_log`, `gfx_film`, `log`, `log_wait`, `drive`, `perform_export`, `debug`, `lua`, `throttle`, `captures`, `state_list`, `state_write`, `promote` |

## Names for addresses

A symbol file is the project's YAML or the linker's own five-column map. A map row's address is the runtime one only for CODE: DATA is copied to RAM at boot, so the map's linear address for it is the ROM copy of its INITIAL value, which reads plausibly and is wrong. So `bases` maps each non-CODE class to the `0x` base the board uses or to `rom`, and a class with no base REFUSES the start rather than loading an image address in silence.

**An address is written `0x`, and nothing else is one.** Any other ref is a symbol, so `adc` names the symbol even where it is also valid hex. Bare hex that names no symbol is refused (`unknown_ref`) with the `0x` spelling it most likely meant, because the table deciding would read one build's name as another build's address. Every address ARGUMENT and every io port is written `0x`; text that starts `0x` and is not hex is refused. A writer's `pc` is a ref. Conditions and `debug` are the console's own grammar, where a bare number is hex; `lua` is Lua's, where it is decimal.

A ref is read once, so a clear reaches only declarations of its own kind: a name is never the row at the address its letters spell. Each is read as the console reads it (`7fff`, `0x7fff`, `$7fff` and `#32767` are one; a run of letters such as `ab` stays a name, and a name keeps its case). What the comment file or the store already holds keeps the reading its file gives it: a hex-shaped ref there is a symbol, and a stored row by address in bare hex is that address.

**A value, a byte offset or a pen is an integer or a `0x` string** (`"0x1234"` is 4660), in a call and in a `perform` or `drive` step alike. Decimal text is refused, because `"4660"` reads as plausibly as the digits of `0x4660`, as is a bool or either spelling past 64 bits, the widest number MAME's debugger holds. A reply hands the number back in a form the argument takes again. A count is an integer only.

**A name is a name of ONE cpu's table**: a `ref` resolves against the table of the cpu the call names, else of the visible one, so a name only the other cpu's program has is an unknown symbol here, and the same name in both tables is not ambiguous: the cpu decides. A `ref` with a segment in it (`12345:0010`) is refused, because the address here is linear; an unknown NAME waits for the machine, being a symbol in THAT machine's table.

**A type file** (`types`) or a `type:` beside a symbol names what a symbol IS, so a watch on it needs no format and a pointer says what it points at.

The tools: [Names](docs/reference/names.md), [Declarations](docs/reference/declarations.md), [Read](docs/reference/read.md).

## Declarations

The debugger holds the ARMED instances; the server holds what the caller MEANT: a symbol or a raw address, a condition as typed. Keeping the intent makes a rebuild free, since an address moves when the program is relinked and a name does not. Each declaration is stamped with its session (`origin`) and `created_at`.

The tools: [Declarations](docs/reference/declarations.md) (breakpoints, registerpoints, watches) and [Comments](docs/reference/comments.md).

**Lists.** `inherited` says the row came back from the store at `start`; no reply names the session's own origin to compare against. `age_s` is negative for a stamp ahead of this host's clock, floored and never clamped, since a zero would claim "just now". Every list reads the debugger's own `bplist`, `wplist` or `rplist` back, so `armed` is the machine's answer; a row no declaration placed is `foreign`: listed, never deleted.

**Declaring is idempotent and nothing is silent.** A re-declaration adopts and takes the new session's stamp, never stacking a row. A name absent from THIS build is kept `unresolved`, except a registerpoint at the ADD, which refuses what the console cannot evaluate.

**A row is known by its INDEX**, which MAME numbers with one counter across every cpu. A re-declaration adopts only a row nobody holds on the visible cpu (where an arm lands); a row typed through `debug`, or one under another cpu, stays `foreign`. One row is one declaration per (cpu, address): a stop adopts a listed row only under its own condition, any other is `ambiguous_ref` naming the console command that removes it, at the declaration and at `start`'s re-arm alike. A `bp` whose row `bplist` shows without the condition sent is not armed. Watches and registerpoints apply the same rule.

**A declaration keeps its cpu**, read when declared. Each cpu runs its own program, so the same ref on two cpus is two declarations; one made again with no `cpu` after a stop moved the visible cpu is a second one, and naming the first cpu adopts its own row. A clear with `cpu` reaches that cpu's declarations of the ref, without it every cpu's. Rows are armed with the cpu named (`bp <addr>:<cpu>`), which never moves the visible cpu, at `start`'s re-arm too. A stored row with no cpu is the first cpu's.

**The store is keyed by the system name plus the RESOLVED path of the symbol file `start` was given**: two spellings of one file are one key, two boards sharing a map differ by system, two maps of one board by path. With no symbol file there is no key, because nothing could re-resolve by name: declarations are by address and die with the session. A corrupt store refuses the start before the emulator spawns and is never discarded.

**A `state_dir` session never opens the project store**, so nothing it does reaches another session's rows. A directory named for the first time starts empty, since copying the project's rows in would bring back what naming it keeps out. The project store's directory is refused as a `state_dir`, directly or through a link. `declarations.path` says which store is in use and so what `all=True` reaches: with a `state_dir`, rows declared under it; without, every session's rows of that system and symbol file, where a row another session declared reads `inherited: true`, so a caller who did not declare it clears by `ref`.

**A raw address is bound to a build.** Declarations are stamped with their cpu's build FINGERPRINT (system, ROM image and that cpu's symbol file, hashed), so a rebuild of one cpu's program leaves the other's raw addresses alone. A raw address is re-armed only over the same fingerprint, whoever declared it, and listed `stale` over another: armed blind it would land on whatever the new build put there. A name re-resolves whatever the build.

**What the store held comes back at `start`**, re-resolved against that start's table and re-armed before the park's survey; `declarations.rearm` accounts for every one. Nothing is dropped: a name this build lacks re-resolves at the next `start`, or the caller clears it.

**A callback that raises is counted, never read as a zero.** The taps, notifiers and dumpers of the censuses (count watch, capture, `palette_log`, `gfx_film`) run under `pcall`, because MAME drops a tap's error silently; the census reply carries `callback_errors` (`count`, `first`). A census beside a count above zero is short of what happened, and a draft proves no command from such a capture. A dumper that keeps failing leaves the earlier dump on disk and logs `MCP_DUMP_FAILED <id> <message>` to `error.log`, which a reply over that dump gives as its `why`. The wrappers' own notifiers (`input`, `record`, `audio_record`, the launch's throttle) are unguarded: each proves itself by a mark in `error.log`, so a raise leaves its reply pending, never a clean zero.

**The comment file is what a project versions beside its symbol file**, written only by `comment_write(method="save")` and read only by `comment_write(method="load")`; by convention `<symbol file name without extension>.comments.tsv`, the first cpu's on a multi-cpu board. UTF-8, no byte order mark, LF line ends. Line 1 is exactly `# comments v1: ref<TAB>cpu<TAB>created_at<TAB>text`; every other line is one comment in that order, the text last and so the rest of the line, sorted by cpu then ref in code-point order so a re-save moves only what changed. `cpu` is the absolute tag (`:maincpu`); `created_at` is `YYYY-MM-DDTHH:MM:SS+00:00`. An address is always `0x` and hex and anything else a symbol, so a saved symbol `fade` never comes back as an address. The file has no build column, so a raw address loaded into another build is trusted: what must survive a rebuild is commented by symbol.

## Advancing the machine

The tools: [Advance](docs/reference/advance.md), whose page holds how a run is chosen, the frame counter, the stops that are not a run's own and the survey every stop returns. What every tool shares about a running or a broken session follows.

### The running guest is a contract

While a released machine runs, every reader refuses, naming `last_stop` and `answers_while_running`. The refusal is a decision and not a limit of the stub: it serves `m` and `qRcmd` to a running machine too, but a value read off a moving machine is a sample of no state, and the stop packet the stub sends on its own can land in front of the read's answer.

What answers reads nothing off the machine, plus the declarations: the console takes a `bp`, `rpset` or `wp` while running and it FIRES, so nothing is queued and the reply says `while_running`, meaning whether the machine was running when the call ARRIVED, read once at entry. A stop its own round trips let through is the next contact's `last_stop`. A stop reached on its own while nobody waited is recorded by the first tool that finds it (`stopped_on_its_own`).

A run the console owns, typed through `debug` (the `g` family, `step N`, `over`, `out`, `next`), marks the session RUNNING too, and its stop is proved on the frame counter, by `stop` or the first contact after. **A `run_for` or a `step over` that BAILS OUT marks it the same way**, because each hands the machine back under a console-started run it could not see end. A `no_progress` by frames is the counter itself not moving, so only `stop`'s interrupt proves rest there.

A `gvblank` or an `over` the console REFUSED is a bail-out too: the command may have been taken, so the reply is `not_settled`, names `stop`, and past it, if `stop` fails as well, `close` then `start`. An unanswered `stop` interrupt is `not_settled` the same way; nothing counts the attempts, and the caller decides when to give up. The reason is the stub: it answers `?` with a stop whether the machine runs or not, so no query proves rest and "it may be RUNNING" is the only honest word. A request the console did not answer IN TIME is not a bail-out; it breaks the session, below.

### A broken session says so until it is closed

**`session_broken` LATCHES until `close`.** When a tool reads something that is not a stop where one was due, cannot survey a stop it did read, or the connection fails under it, the two ends no longer agree where a packet starts, and the stub honours an interrupt only BETWEEN packets: not even `stop` can be believed from there. The stub's own `no` is the exception, because it keeps the channel paired: an `E` reply is `readback_refused`, an empty packet (a capability this build lacks) `no_channel`, and neither latches. A MAME that died under the session answers `session_broken` with its `exit_code`, and `close` is named first, since it reads the process's last words before the scratch is deleted.

**A request the stub did not answer in time breaks it too**, whichever tool sent it: nothing in the protocol numbers a reply, so the answer still owed would be read as the NEXT request's. A wait for a STOP is not a request and keeps its own `not_settled`.

From then on every tool but `status` and `close` answers `session_broken`, quoting what broke it and the way out (`close`, then `start`). It never describes the machine as running, which such a channel can no longer establish: `running: false` beside `broken`. `close` skips the drain, the speed read and the `quit`, which have no channel to believe, and kills the process, so nothing is written to a `state_dir`. A restart costs seconds, and a wrong value costs the measurement.

## Reading and writing

The tools: [Read](docs/reference/read.md), [Scan](docs/reference/scan.md), [Write](docs/reference/write.md), and `machine_map` on [Machine](docs/reference/machine.md).

Every reader takes a `ref`, by symbol or `0x` address, and answers at the address the running board uses. On a RUNNING machine every reader refuses (Advancing the machine, *The running guest is a contract*).

**A range past the end of a cpu's program space is refused, by one judge**, for every tool that reads or writes a range: the stub masks an address, so a byte past the space would answer the space's first bytes again, a plausible value for a place that does not exist, and a write would land there. With no mask known, the console judges.

**The console readers answer INVALID, never a zero**, when the console said something they were not captured answering.

**`write` and `set_register` READ BACK what landed**; every later reply's `session` block carries `altered: true`, and `close` reports it for the session that ended. A read through the console without stepping or writing alters nothing.

### What comes back as a file

A live session answers into the conversation, and a frame's worth of bytes or a driver's log do not fit there, so those tools return a PATH.

Every `dest` is absolute, in a directory that exists, and not there yet, a dangling link included. A file's own name is written by [one rule](https://github.com/scry-mcp/scry-core/blob/main/docs/file-names.md) (`My Dump.BIN` as `my-dump.bin`, a name with no extension refused) and the reply's path names the file as written; a directory `dest` (`series_capture`, `gfx_film`'s `film_dir`) keeps its name. The directories of the path are free of commas, semicolons, quotes, whitespace, brackets (the console's command line splits, ends, quotes or refuses a line at each) and control characters. All of it is judged before the console is touched and before the session gate, because a `dest` is a verdict about a string and answers with no machine: a refusal after the console wrote the file leaves a file nobody asked for. `gfx_draft` alone may find something there already, which it replaces; its missing directory is refused rather than made, and a space in its directories is refused although no console line carries that file.

## The log

A chatty driver fills the log fast, so the pattern and the limit are the whole interface.

**The pattern is never empty.** `.` is every line, written out: an empty pattern left by mistake would hand back the whole log, so `log`, `log_wait` and `drive` refuse it.

**`since_mark` asks "after Y".** A machine that replays a saved timeline writes lines that look like the ones before the load, so content cannot tell them apart; a position can. The mark is a position in the file, not a moment: a line the emulator had not yet flushed when the load was sent lands after it. One position cannot name a place in two files, so `all` is asked channel by channel.

**Files.** A third file sits beside the two channels, unreported: `debug.log` (`-debuglog`), the debugger console's own output, which the stop survey reads for a watchpoint's writer.

The tools: [Machine](docs/reference/machine.md) (`log`, `log_wait`); `drive` takes the same pattern ([Lists](docs/reference/lists.md)).

## Sequences in one call

`perform` runs a list of the server's own operations in one call, and `drive` runs `perform`'s rules around an input.

**The whole list is checked before the first step runs**, every refusal listed, so a batch is fixed once and a refusal never lands after other steps have moved the machine. What only its step can judge still refuses there, with `failed_at` and `ran` as the honest account (a symbol against the table, a file an earlier step writes, anything that needs the machine).

**Counting.** Messages count steps from 1, as the progress line does; the indexes a reply carries (`failed_at`, a row's `step`, `errors`' `step`) count from 0.

The tools: [Lists](docs/reference/lists.md).

## From an investigation to a bench

Every session is recorded from the `start` that succeeds, and cleared by the next one; `close` keeps it. `perform_export` writes it as `perform`'s own document, and the runner plays it back with no model, from this repository:

```sh
uv run python -m scry_core.replay <document> [--binary PATH] [--rompath DIR] [--transcript PATH]
```

It exits 0 when every step held; 1 when a step diverged or failed; 2 on a usage error; 3 when nothing was demonstrated (no step with a `recorded` answer, a start the server refused, a needed saved state or declaration the replay lacks, a server that broke).

A step's check is `"recorded": {<field>: <value>}` inside it, and a mismatch is `diverged` at that step. A caller keys on `failed_at`, which a failed step and a diverged one both carry; the code says which. Under `until_frame` every lap holds each step to its `recorded` again, so a stop recorded on the first lap diverges on the second: an exported document carries no `until_frame`.

The tools: [Lists](docs/reference/lists.md).

## The store

A repository can declare how a session starts on it, the screen maps of its program and the scripts that replay it, in a `.scry/` store it tracks, so a session gives only what is its own run's (`start(profile=...)`, `screen_map_write(method="load")`, `perform(path=...)`). A session keeps what it learned as drafts and writes nothing into the repository until a `promote` call names what to write: the store is tracked, so every entry is reviewed first, and every path in it is a placeholder ([the rule](https://github.com/scry-mcp/scry-core/blob/main/docs/store-paths.md)), so the file reads the same on any machine.

The tool: [Store](docs/reference/store.md) (`promote`).

## Input and the screen

**Every capture is taken through one view, fixed at `start`**, because a running MAME cannot switch the view its snapshots take. `snapshot` and `record` render through it and carry `view`; the readers of the screen's own pixels (`screen_view`, `screen_signature`, `series_capture`, a film's frames) never do and carry none. Under a named view a film's frames are unchecked against MAME's snapshot.

**Input is injected inside the machine.** The typed Lua wrappers (`input`, `record`, `audio_record`, `throttle`) are scripts this server composed, so none marks the session altered for a read, and each proves its effect through `error.log`: their scripts write marks with `logerror`, flushed as written, where a `print` from a frame notifier sits in the stdio buffer until the next prompt.

A run another stop cuts short leaves the notifier armed (field held, recording open or not begun) and the reply names the frame it acts on; the next call of the same tool releases it. That frame is predicted from the counter at the evaluation, one later inside a vblank, since MAME calls notifiers as a vblank begins and moves the counter as it ends. A driver that updates its screen after the vblank is called at the end, which Lua cannot see, so a chunk evaluated inside that vblank is predicted one frame late.

A chunk that answered with no mark at all is refused as lost marks. A wrapper whose run did not settle is `not_settled`, its message saying the notifier may still be armed, never the wrapper's fields: the machine may still be running, so nothing read off it is a state of the wrapper. A wrapper refused once its run began has moved the machine, and says so in `frame_before` and `frame_after`. Marks carry the call's own number so a stale one is never attributed to a later call.

The tools: [Lua](docs/reference/lua.md) (`input`, `throttle`), [Captures](docs/reference/captures.md) (`record`, `audio_record`), and `screen_signature` on [Screen](docs/reference/screen.md).

`snapshot` and `captures` ([Captures](docs/reference/captures.md)) are the screen's other half: the still as a complete, hashed PNG, and every file `record`, `audio_record`, `trace`, `snapshot` and the graphics tools checked and handed back this session, re-read, answering while the machine runs.

### Graphics

These tools answer the question a colour snapshot cannot, WHICH PEN, from bytes under a format the caller states, never from what a driver's `GFXDECODE` believes. Their shared contract (the picture, which instant a decode shows, the source, how a board is discovered) is on [Screen](docs/reference/screen.md), and the `gfx.yaml` project knowledge on [Film](docs/reference/film.md).

The tools: [Screen](docs/reference/screen.md) (`palette`, `screen_view`, `screen_signature`, `gfx_view`, `gfx_locate`, `gfx_sweep`, `gfx_draft`, `gfx_blits`, `gfx_blit_source`) and [Film](docs/reference/film.md) (`gfx_load`, `gfx_film`, `palette_log`).

## Media files

The tools that answer about pictures and sound follow one order, so a reply is the cheapest thing that answers the question: a signature or a number first ("is it the same screen" is two strings compared, never two pictures sent); the full picture last, and only from a tool whose purpose is to show; and a reply that answers with numbers names what it compared, over which region, and its path.

The signature, crop and series formats and the rules of the file tools are on [Files](docs/reference/files.md).

The tools: [Captures](docs/reference/captures.md); [Files](docs/reference/files.md); [Screen](docs/reference/screen.md).

## Screen maps

A screen map names an application's screens and their controls in a file, so a caller asks "which screen is this" and gets a name; its format and its two layers are on [Screen](docs/reference/screen.md).

The tools: [Read](docs/reference/read.md) (`screen_map_write` with its three methods, `screen_map_find`).

## Saved states

A saved state goes through the debugger console, and MAME can hold a save or a load instead of running it; `state_write(method="save")`, `state_write(method="load")` and a `statesave` or `stateload` typed through `debug` all settle that the same way.

The tools: [States](docs/reference/states.md).

## The console

`debug` goes through the protocol's `monitor` escape; `lua` and the wrappers that run a script go through MAME's Lua console, `-console` over the process's standard input, which works with no terminal attached. The console's shared contract is on [Lua](docs/reference/lua.md).

The tools: [Write](docs/reference/write.md) (`debug`); [Lua](docs/reference/lua.md) (`lua`, `input`, `throttle`).
