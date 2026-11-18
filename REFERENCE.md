# scry-mame: reference

This page is for a rule that several tools share. It holds the list of tools, the fields every reply carries, and those rules.

Each tool has its own entry, with arguments, reply and example, on its family's page under `docs/reference/`; a family is a group of tools. To install, see the [README](README.md).

Each example is a call of the example session: one session on Gridlee, a free ROM from mamedev.org, kept whole in [`docs/reference/tour/TRANSCRIPT.md`](docs/reference/tour/TRANSCRIPT.md).

A path in an example that starts with `./` stands for the folder of your clone, and `$TMPDIR` for your temporary folder. Write the whole path in your own call: a relative one is refused.

## Index

<!-- scry-reference:begin index -->
- [Session](docs/reference/session.md): Starting a MAME session, asking what state it is in, finding its window, choosing a cpu and ending it. [`start`](docs/reference/session.md#start), [`status`](docs/reference/session.md#status), [`window`](docs/reference/session.md#window), [`close`](docs/reference/session.md#close), [`cpu_focus`](docs/reference/session.md#cpu_focus), [`rom_check`](docs/reference/session.md#rom_check)
- [Machine](docs/reference/machine.md): What the emulated machine is made of, how the debugger holds each cpu, and what MAME writes to its logs. [`cpu_info`](docs/reference/machine.md#cpu_info), [`machine_map`](docs/reference/machine.md#machine_map), [`log`](docs/reference/machine.md#log), [`log_wait`](docs/reference/machine.md#log_wait)
- [Names](docs/reference/names.md): Symbol names for addresses: look up a name or an address in the symbol table of your program. [`symbols_find`](docs/reference/names.md#symbols_find)
- [Run](docs/reference/run.md): The tools that let the program run and stop it again. [`run_to`](docs/reference/run.md#run_to), [`run_for`](docs/reference/run.md#run_for), [`step`](docs/reference/run.md#step), [`resume`](docs/reference/run.md#resume), [`stop`](docs/reference/run.md#stop), [`trace`](docs/reference/run.md#trace), [`screen_wait`](docs/reference/run.md#screen_wait)
- [Breakpoints](docs/reference/breakpoints.md): Breakpoints and watches the server saves by name and sets again in later sessions. [`breakpoint_at`](docs/reference/breakpoints.md#breakpoint_at), [`regpoint_add`](docs/reference/breakpoints.md#regpoint_add), [`watch_add`](docs/reference/breakpoints.md#watch_add), [`declaration_list`](docs/reference/breakpoints.md#declaration_list), [`declaration_clear`](docs/reference/breakpoints.md#declaration_clear)
- [Read](docs/reference/read.md): Reading what the stopped program holds: memory, registers, code, and which of its screens is showing. [`read_memory`](docs/reference/read.md#read_memory), [`read_block`](docs/reference/read.md#read_block), [`registers`](docs/reference/read.md#registers), [`disassemble`](docs/reference/read.md#disassemble), [`find`](docs/reference/read.md#find), [`history`](docs/reference/read.md#history), [`memdump`](docs/reference/read.md#memdump), [`screen_map_find`](docs/reference/read.md#screen_map_find), [`screen_map_write`](docs/reference/read.md#screen_map_write)
- [Screen](docs/reference/screen.md): Seeing a board's graphics as data: the palette entry behind each pixel, tiles decoded from ROM or memory, and the draws a board makes. [`palette`](docs/reference/screen.md#palette), [`screen_view`](docs/reference/screen.md#screen_view), [`screen_signature`](docs/reference/screen.md#screen_signature), [`gfx_view`](docs/reference/screen.md#gfx_view), [`gfx_locate`](docs/reference/screen.md#gfx_locate), [`gfx_sweep`](docs/reference/screen.md#gfx_sweep), [`gfx_draft`](docs/reference/screen.md#gfx_draft), [`gfx_blits`](docs/reference/screen.md#gfx_blits), [`gfx_blit_source`](docs/reference/screen.md#gfx_blit_source)
- [Timeline](docs/reference/timeline.md): MAME's tools that load a project's graphics manifest and show, frame by frame, when a write happened and which code set a colour. [`gfx_load`](docs/reference/timeline.md#gfx_load), [`gfx_film`](docs/reference/timeline.md#gfx_film), [`palette_log`](docs/reference/timeline.md#palette_log)
- [Scan](docs/reference/scan.md): Finding the address of a value nobody has named yet. [`scan`](docs/reference/scan.md#scan)
- [Write](docs/reference/write.md): Changing the machine: memory, a register, a reset, and any line the debugger console takes. [`write`](docs/reference/write.md#write), [`set_register`](docs/reference/write.md#set_register), [`reset`](docs/reference/write.md#reset), [`debug`](docs/reference/write.md#debug)
- [Comments](docs/reference/comments.md): Notes on addresses of the program, saved with the breakpoints and shown in the disassembly. [`comment_list`](docs/reference/comments.md#comment_list), [`comment_write`](docs/reference/comments.md#comment_write)
- [Lua](docs/reference/lua.md): Pressing the board's inputs, running Lua inside MAME, and choosing whether the machine runs at real speed. [`input`](docs/reference/lua.md#input), [`lua`](docs/reference/lua.md#lua), [`throttle`](docs/reference/lua.md#throttle)
- [States](docs/reference/states.md): Saved states: the whole emulated machine written to a file, listed, and loaded back. [`state_list`](docs/reference/states.md#state_list), [`state_write`](docs/reference/states.md#state_write)
- [Captures](docs/reference/captures.md): Saving the screen and the sound to files: a still, a series of frames, a video, a recording, and the list of them. [`series_capture`](docs/reference/captures.md#series_capture), [`record`](docs/reference/captures.md#record), [`audio_record`](docs/reference/captures.md#audio_record), [`snapshot`](docs/reference/captures.md#snapshot), [`captures`](docs/reference/captures.md#captures)
- [Files](docs/reference/files.md): Comparing pictures and recordings on disk, in numbers, with no machine running. [`image_compare`](docs/reference/files.md#image_compare), [`audio_compare`](docs/reference/files.md#audio_compare)
- [Sequences](docs/reference/sequences.md): Running several calls as one: a list of steps, an input with its check, and a session written as a replay script. [`perform`](docs/reference/sequences.md#perform), [`drive`](docs/reference/sequences.md#drive), [`perform_export`](docs/reference/sequences.md#perform_export)
- [Project](docs/reference/project.md): Saving what a session learned into the repository's `.scry/` folder, after a review. [`promote`](docs/reference/project.md#promote)
<!-- scry-reference:end index -->

## The session

A session is one MAME that `start` launches and the server keeps until `close`, so every call reaches the same machine.

- **One call at a time.** Calls take turns: a second one waits for the first.
- **Which MAME runs.** `start` uses `binary`, else the `MAME_BINARY` variable, else the `mame` on your `PATH`: the first of these that is set. A value that names no executable is refused, never skipped.
- **Paths.** A path argument is absolute or starts with `~`; a relative one is refused, because MAME runs from the session's temporary folder. So is an empty required path, or one with a NUL or an unpaired surrogate.
- **The server's end.** However the server stops, its MAME stops too. On Windows the system ends it; elsewhere a watchdog process does, listed as `scry-mame-guardian`.
- **An idle hour.** After an hour with no call, counted from the end of the last one, the server closes the session, a running program included. The next reply says so, in a `no_session` refusal or in `status`'s `note`.
- **Your own kill script.** The command line of a MAME the server launched contains `mame-mcp-`: skip those. End a session with `close`, never with a signal.

### Boards with several cpus

MAME's debugger acts on one cpu at a time, the visible one, and every stop makes the cpu that stopped visible.

- With no `cpu`, a call uses the visible cpu; a tool that lists or clears covers every cpu.
- With a `cpu`, a call uses that one and leaves the visible one alone. Only `step` shows the cpu it steps.
- `cpu` is MAME's tag, `subcpu` or `:subcpu`. An unknown one is refused `unknown_ref`, listing the board's cpus.
- A reply that touches a cpu names it in `cpu`.
- A registerpoint, MAME's stop on a condition over registers, is always the visible cpu's: MAME's `rpset` names none.
- Another cpu's registers and memory need a MAME built with the patches under `patches/`. Without them MAME serves its first cpu only, and a call that needs another says so.

`space` is MAME's name for an address space, `program` by default. A tool refuses a space it cannot read, and `io` on a cpu that has none.

### The orange edge of the window

While a session is live MAME's window has an orange edge, so a person at the computer knows it is in use. It is bright while a call that can run or change the program is in progress, and dim otherwise, even over a program `resume` left running. `start(presence=False)` turns it off, and no capture shows it.

The tools: [Session](docs/reference/session.md), [Machine](docs/reference/machine.md).

## What every reply carries

Every reply has the same outer fields, whichever tool answers, so you read any answer the same way.

<!-- scry-reference:begin envelope -->
- `summary` (string)
- `status` (one of `"ok"`, `"INVALID"`)
- `code` (string)
- `message` (string)
- `omitted` (array of string)
- `how` (string)
- `note` (string)
- `cancelled` (object)
- `session` (object)
- `answers_while_running` (array)
- `exit_code` (integer or object)
- `last_stop` (object)
- `stopped_on_its_own` (object)
- `broken` (string)
- `cause` (string)
- `cpu_tags` (array of string)
<!-- scry-reference:end envelope -->

What each one is for:

- `summary`: one line saying what happened.
- `status`: `ok`, or `INVALID` for a refusal.
- `code`, `message`: a refusal's word, from a fixed list, and its reason.
- `omitted`, `how`: fields left out to keep the reply short, and the call that returns them.
- `note`: what the other fields do not say; absent when there is nothing to add.
- `session`, `cancelled`: described below.
- `answers_while_running`: on a refusal because the program runs, the tools that still answer.
- `last_stop`: the last stop the server saw: its number, address, frame, cause and age.
- `stopped_on_its_own`: the program stopped while no call waited; said once, by the next reply.
- `exit_code`: MAME's, when it ended during the session.
- `broken`: on `status`, what broke the session.
- `cause`: on a reply that ends at a stop, what stopped the program.
- `cpu_tags`: the board's cpus, on `status` and on a refused `cpu`.

### The `session` block

`session` closes every reply and is read after the tool's work. It says `alive` (MAME is up), `running` (the program runs, not stopped at the debugger) and `altered`.

**`altered` says something wrote to the machine.** A write is allowed: `write`, `set_register`, a `lua` script, a `debug` line that changes the machine. Every later reply then says `altered: true`, because a measurement on a forced value does not describe the game's own run.

A warning appears only while it holds:

- `broken`: see [Running and stopping](#running-and-stopping).
- `console`: trouble on MAME's Lua console, once a count is not zero. It counts reader failures (`thread_errors`), scripts run twice (`reruns`) and lines never run (`lost`).
- `throttles_not_applied`: speed changes MAME has not confirmed, which put later timings in doubt.
- `tallies_not_removed`: a counting watch that was cleared and still counts inside MAME, listed until the session ends.
- `read_only_claims`: `lua` calls you declared read-only, which the server did not count as writes.

`start` and `status` also carry the plain counts, such as `altering_writes`; other replies may name them in `omitted` instead.

### A refusal

A refused call answers `status: INVALID` with `code` and `message`, and its context in plain fields beside them, such as `last_stop`.

- `bad_argument` asks for another value; `needs_call` for another call first, which the message names.
- An argument's form is checked before MAME is asked anything. What only the machine can decide is refused afterwards, saying what state the machine is left in.
- The schema refuses a wrong type as `bad_argument`, and an unknown argument name too. Nothing is converted: `"16"` is not 16.
- A fixed list of words or a range is published in the schema as `enum`, `minimum` and `maximum`.
- A refusal is a normal reply: MCP's `isError` is for a failure of the server itself.

A field that could not be read is `{"available": false, "why": "..."}` where its value would be; no reply carries a null. Every tool publishes its reply's shape as `outputSchema`, and its description says when a field comes only in some cases.

### One name for each thing

- `seconds` is the real time a call may wait; `frames` and `milliseconds` are emulated time.
- `count` is how many, `first` from where, `length` how many bytes, `limit` how many rows come back.
- `dest` is the file a call writes, `path` the file it reads, `<what>_path` any other file, always whole.
- `_s` ends a name in seconds, `_at` a clock time, `_by` who did it, `_total` how many a list holds.
- `hits` is always a list; a count says what it counts, as `bytes_written` does.
- `note` is one string, its sentences joined by `; `; `why` is one row's reason; `error` quotes another program.
- A width names its unit, as `cell_bytes` and `refresh_hz` do; `size` alone is bytes.

### How a wait ends

A tool that waits answers `status: ok` with a `verdict`:

- `TARGET`: what it waited for happened.
- `ELAPSED`: the emulated time you asked for passed.
- `TIMEOUT`: `seconds` ran out. `run_to` and `run_for` then stop the program; `resume`, `log_wait`, `perform` and `drive` leave it running.
- `OTHER_STOP`: a stop the call did not ask for ended it.

A call that could not finish is a refusal, with no `verdict`. Zero means no wait in `resume(seconds=0)` and in `settle_seconds=0`, a sequence's wait for a stop.

### A long wait, and a cancelled call

A long wait reports progress about once a second, as MCP progress notifications: frames done out of N for `run_for(frames=N)`, elapsed seconds with no total otherwise. The value never goes back.

**A cancelled call answers nothing**, since the protocol sends no response to one. It ends at the next check of its wait, as its own time limit would end it; a tool with no wait finishes first.

**The next reply says what it left**, once, in `summary` and in `cancelled`: `tool`, `after_s`, `left` and `earlier`. `left` is `stopped`, `running`, `closed` or `unknown`; `earlier` names cancelled calls not yet reported.

A call cancelled while it waited its turn did nothing and leaves no record. One that had already finished is recorded with nothing done to the machine, and a cancel that arrives after its last check is not seen.

| End | What the cancel leaves | Tools |
|---|---|---|
| `stop` | The program stopped, as `stop` leaves it; a stop the call had already reached is recorded as its own. | `step`, `run_to`, `run_for`, `screen_wait`, `trace`, `series_capture`, `perform`, `input`, `record`, `audio_record` |
| `kill` | MAME ended: asked to quit first when a session is up, which writes `cfg/` and `nvram/`, and killed at once while still booting. | `start`, `close` |
| `none` | The machine as the call found it. | `status`, `window`, `cpu_focus`, `cpu_info`, `rom_check`, `resume`, `stop`, `breakpoint_at`, `regpoint_add`, `watch_add`, `declaration_list`, `declaration_clear`, `comment_list`, `comment_write`, `symbols_find`, `machine_map`, `read_memory`, `read_block`, `registers`, `disassemble`, `find`, `scan`, `history`, `write`, `set_register`, `reset`, `memdump`, `snapshot`, `screen_signature`, `screen_map_find`, `screen_map_write`, `image_compare`, `audio_compare`, `palette`, `screen_view`, `gfx_view`, `gfx_locate`, `gfx_sweep`, `gfx_draft`, `gfx_load`, `gfx_blits`, `gfx_blit_source`, `palette_log`, `gfx_film`, `log`, `log_wait`, `drive`, `perform_export`, `debug`, `lua`, `throttle`, `captures`, `state_list`, `state_write`, `promote` |

The tools: every one in the [Index](#index).

## Names for addresses

An address argument, `ref` in most tools, is a `0x` number or a symbol of your program.

- **`0x` makes an address; anything else is a symbol.** So `adc` is the symbol, though it is also valid hex. Bare hex naming no symbol is refused `unknown_ref`, with the `0x` spelling you probably meant; an I/O port takes `0x` too.
- **Symbols come from the file you give `start`**: your project's YAML or the linker's map. A map gives data its address in ROM, not in the RAM the program uses, so `start`'s `bases` says where each class lives. A class with no base is refused.
- **A symbol belongs to one cpu**: the one the call names, else the visible one. The same name in two cpus' files is not ambiguous.
- **Addresses are linear.** A `ref` with a segment, such as `12345:0010`, is refused.
- **A value, an offset or a palette index is an integer or a `0x` string**, in a call and in a `perform` step: `"0x1234"` is 4660. Decimal text is refused, since `"4660"` could be the digits of `0x4660`. A count is an integer only.
- **A reply spells a number so the argument takes it back**: an address or a block offset as `0x0070001e`, eight digits; a value as `0x` text at its width.
- **Two tools have their own grammar.** A condition or a `debug` line reaches MAME's console as typed, where a bare number is hex. In a `lua` script it is decimal.

The tools: [Names](docs/reference/names.md), [Breakpoints](docs/reference/breakpoints.md), [Read](docs/reference/read.md).

## Breakpoints and watches

The server saves each breakpoint, watch and registerpoint as you asked for it, and sets it again in later sessions.

You give a symbol or an address, and a condition as typed; MAME's debugger holds what is set now. A rebuild moves an address but not a name, so a breakpoint by name survives it. The tools call a saved one a declaration, and each row they list has a `state`:

- `armed`: set in the debugger now, as MAME's own `bplist`, `wplist` or `rplist` reports it.
- `unresolved`: its symbol is not in this build. It stays saved and is tried at the next `start`.
- `stale`: a raw address saved over another build, not set because other code may be there now.

`inherited: true` marks a row an earlier session saved. `foreign` lists debugger rows the server did not set, such as one typed through `debug`; they are never deleted.

- **Asking twice gives one row**, which takes this session's `origin` and `created_at`. Another condition at the same cpu and address is refused `ambiguous_ref`.
- **A row keeps its cpu**, so one `ref` on two cpus is two rows. Name the `cpu` on a board with several, since a stop can change the visible one. `declaration_clear` without `cpu` clears the `ref` on every cpu.
- **A callback that fails is counted, never read as a zero.** A counting or capturing watch, `palette_log`, `gfx_film`, `gfx_blits` and `gfx_blit_source` collect through callbacks inside MAME. The reply that reports them carries `callback_errors`, and with a count above zero there the numbers are short of what happened.

### What is saved between sessions

- **One file per program.** The saved breakpoints file is found by the system's name and the path of the symbol file `start` was given. With no symbol file nothing is saved, and the rows end with the session.
- **`start` sets every saved row again** before it answers, looking each symbol up in this build. `declarations.rearm` accounts for each one.
- **A raw address belongs to one build**, by a fingerprint of the system, the ROM image and that cpu's symbol file. On another build it is `stale`.
- **A damaged file refuses the `start`** before MAME launches, and is never thrown away.
- **`start(state_dir=...)` uses a file of its own** in that folder, empty the first time, and never opens the project's. `declarations.path` names the file in use. `declaration_clear(all=True)` clears all of it, other sessions' rows included.

The tools: [Breakpoints](docs/reference/breakpoints.md), and [Comments](docs/reference/comments.md) for the comments saved beside them.

## Running and stopping

The program is either stopped at the debugger or running, and most tools need it stopped.

`start` leaves it stopped; `run_to`, `run_for` and `step` run it and stop it again; `resume` lets it run and returns. Every reply that ends at a stop carries the same readings, listed on the Run page.

**While it runs, a tool that reads the machine refuses** `not_stopped`, with `last_stop` and `answers_while_running`. A value read off a moving machine belongs to no moment. These answer:

- every tool of Machine, Names, Breakpoints, Timeline, Files, Sequences and Project;
- `status`, `window`, `close`, `stop`, `comment_list`, `throttle`, `state_list`, `snapshot`, `captures`;
- `comment_write(method="save")`, `scan(method="clear")`, `screen_map_write` with `load` or `save`, and `registers(from_last_stop=True)`.

A tool that answers may still refuse one of its modes while the program runs: its entry says which.

**A breakpoint set while it runs works at once**, and the reply's `while_running` says whether the program ran when the call came in. A stop nobody waited for is reported once, in `stopped_on_its_own`. A run typed through `debug`, such as `g` or `step N`, counts as running until `stop`.

### When a stop cannot be confirmed

`not_settled` means the server cannot tell whether the program stopped: a run ended where it could not see, or `stop` got no answer. Call `stop`; if `stop` fails as well, `close` then `start`.

### A broken session stays broken until `close`

**`session_broken` stays set until `close`.** A session breaks when the server can no longer match MAME's answers to its requests. That is a request with no answer in time, something other than a stop where one was due, or a failed connection.

**Whichever tool meets the failure, every tool reports it.** From then on each tool but `status` and `close` answers `session_broken`, with what broke it and the way out: `close`, then `start`. No answer can be trusted after it, not even `stop`'s, so `session` shows `running: false` beside `broken`.

**A MAME that died answers `session_broken` with its `exit_code`.** Call `close` first: it returns MAME's last output before the temporary folder is deleted. On a broken session `close` kills MAME without asking it to quit, so MAME writes nothing to a `state_dir`.

Two refusals leave the session usable: `readback_refused`, where the debugger answered no, and `no_channel`, where this MAME or this cpu lacks what the call needs.

The tools: [Run](docs/reference/run.md).

## Reading and writing

Every tool that reads or writes memory takes a `ref` and works at the address the running board uses.

- **A range of bytes past the end of a cpu's program space is refused** `bad_argument`. MAME would wrap round and answer the first bytes again, a believable value for an address that does not exist. Where the server knows no address mask, MAME's console decides.
- **A tool that reads through the console refuses an answer it did not ask for**, as `unexpected_answer`, and never returns a zero in its stead.
- **`write` and `set_register` read back what the machine now holds**, and set `altered`. A read alters nothing.

### An answer that is a file

A memory dump, a recording or a picture does not fit in a conversation, so those tools write a file and answer with its path.

- **`dest` is absolute or starts with `~`**, in a folder that exists, with nothing at its name yet, a dangling link included. Left empty where a tool allows it, the file goes to the session's temporary folder, deleted at `close`.
- **The file's name is written by [one rule](https://github.com/scry-mcp/scry-core/blob/main/docs/file-names.md)**: `My Dump.BIN` becomes `my-dump.bin`, and a name with no extension is refused. The reply's path is the file as written, with a `note` when the name changed. A folder `dest` keeps its name.
- **The folders of the path hold no comma, semicolon, quote, space, bracket or control character**, where MAME's console would cut the line.
- **All of it is checked before MAME is asked anything**, even with no session, so a refusal leaves no file behind.

The tools: [Read](docs/reference/read.md), [Scan](docs/reference/scan.md), [Write](docs/reference/write.md), and `machine_map` on [Machine](docs/reference/machine.md).

## The log

MAME writes two logs, and `log` and `log_wait` search them by pattern, since a busy driver fills a log fast.

- **`channel` picks the log**: `emulator` for `error.log`, what MAME's core and drivers write with `logerror`; `process` for MAME's standard output and error; `all` for both.
- **`pattern` is a regular expression, never empty.** `.` matches every line. An empty pattern would return the whole log, so `log`, `log_wait` and `drive` refuse it.
- **`since_mark` reads only what follows a position.** After a saved state is loaded the program writes the same lines again, so only a position tells old from new. A state load answers it as `mark`.
- **A `mark` is a byte position in one file, not a moment.** A line MAME had not written out when the load was sent lands after it. `all` reads two files, so it takes none.

The tools: [Machine](docs/reference/machine.md) for `log` and `log_wait`, [Sequences](docs/reference/sequences.md) for `drive`.

## Several calls as one

`perform` runs a list of calls in order as one call, and `drive` runs a list and then waits for a line of the log.

- **The whole list is checked before its first step runs**, every problem listed at once. No refusal comes after earlier steps have moved the machine.
- **What only the machine can decide is refused at its step**, such as a symbol this build lacks. The reply says where in `failed_at` and what ran before in `ran`.
- **After a `resume` step, a step that answers on a running program runs at once.** One that needs a stop waits for it, up to `settle_seconds`.
- **Messages count steps from 1**; the indexes in a reply, `failed_at` and each `step`, count from 0.

The tools: [Sequences](docs/reference/sequences.md).

## From a session to a test that replays itself

A session can be written out as a list of steps and played back later with no model, as a test.

Every session is recorded from the `start` that succeeds; the next `start` clears the recording and `close` keeps it. `perform_export` writes it as a document `perform` can run, and this command plays it back from this repository:

```sh
uv run python -m scry_core.replay <document> [--binary PATH] [--rompath DIR] [--transcript PATH]
```

- Exit 0: every step gave its recorded values again.
- Exit 1: a step failed or gave other values.
- Exit 2: the command line was wrong.
- Exit 3: nothing was shown. No step has recorded values, the `start` was refused, the server broke, or a saved state or breakpoint the document needs is missing.

A step's expected values are its `recorded` field, and a step that gives others is `diverged`. Both a failed step and a diverged one set `failed_at`; `code` says which.

The tools: [Sequences](docs/reference/sequences.md).

## The `.scry/` folder

A repository can keep how a session starts on its program in a `.scry/` folder it tracks, so a session gives only what belongs to its own run.

- `.scry/start/`: start profiles, each a saved set of `start` arguments, for `start(profile=...)`.
- `.scry/maps/`: screen maps, for `screen_map_write(method="load")`.
- `.scry/perform/`: saved step lists, for `perform(path=...)`.

**A session writes nothing there by itself.** It saves what it learned as drafts; `promote` shows them for review and writes the ones you approve. Paths in these files use placeholders, by [this rule](https://github.com/scry-mcp/scry-core/blob/main/docs/store-paths.md), so a file reads the same on any computer.

**Each draft belongs to one repository**: the one a call read it from, else the one whose profile `start` read. Without `root`, `promote` writes a draft only there, never into another repository or the server's own clone. A `start` with no profile names no repository, so its drafts need `root`.

The tools: [Project](docs/reference/project.md).

## Input and the screen

Input goes in inside the emulated machine and the screen is read from it, so neither depends on your window, keyboard or mouse.

- **`input`, `record`, `audio_record` and `throttle` are Lua scripts the server writes.** Each acts on a frame and confirms what it did from lines it writes to MAME's `error.log`. None counts as a write.
- **A run cut short leaves the script waiting**: a key still held, a recording still open. The reply names the frame it acts on, and the next call of the same tool finishes it.
- **Captures go through one view, fixed at `start`**, since a running MAME cannot change it; `snapshot` and `record` name it in `view`. `screen_view`, `screen_signature`, `series_capture` and a `gfx_film`'s frames read the screen's own pixels instead. Under a named view, a `gfx_film`'s frames are not checked against MAME's snapshot.
- **`captures` lists every file that `record`, `audio_record`, `trace`, `snapshot` and the graphics tools checked and handed back this session.** It reads each again, and answers while the program runs.
- **The graphics tools answer which palette index, a pen in MAME's words, a pixel holds**, from bytes decoded under a format you state.

The tools: [Lua](docs/reference/lua.md) for `input` and `throttle`, [Captures](docs/reference/captures.md), [Screen](docs/reference/screen.md), [Timeline](docs/reference/timeline.md).

## Media files

The tools that answer about pictures and sound give the cheapest answer that settles the question.

A fingerprint or a number comes first: "is it the same screen" is two strings compared, never two pictures sent. The whole picture comes last, only from a tool made to show one. A reply of numbers says what it compared, over which region, and each file's path.

The tools: [Captures](docs/reference/captures.md), [Files](docs/reference/files.md), [Screen](docs/reference/screen.md).

## Screen maps

A screen map is a file that names a program's screens and the areas of each, so you ask "which screen is this" and get a name.

Its format is on the Read page.

The tools: [Read](docs/reference/read.md) for `screen_map_find` and `screen_map_write`.

## Saved states

A saved state goes through MAME's debugger console, where MAME can hold a save or a load back while a timer is pending.

`state_write` completes a held save or load and checks the state's file, since the console refuses a bad state in silence. A `statesave` or `stateload` typed through `debug` is completed the same way.

The tools: [States](docs/reference/states.md).

## The console

Two tools reach MAME's own consoles, for what no other tool covers.

`debug` sends one line to the debugger console and returns what it printed. `lua` runs a script on MAME's Lua console, which the server feeds through MAME's standard input, so no terminal is needed. `input`, `record`, `audio_record` and `throttle` use that console too, and the Lua page holds the rules they share.

The tools: [Write](docs/reference/write.md) for `debug`, [Lua](docs/reference/lua.md) for `lua`, `input` and `throttle`.
