# scry-mame: reference

The [README](README.md) is the surface. This is the part behind each tool: what it takes,
what it refuses, what it hands back in every case, and why the contract is shaped that way.
Read the section for the family you are about to lean on.

## The session

Reverse-engineering an arcade board means asking the machine questions, and each costs a
whole emulator boot (seconds at best, close to a minute to reach a late screen) unless
something holds the machine between them. A shell command is a fresh process, so a debug
session dies between one question and the next; an MCP is a long-lived process that holds
exactly that state. No external `gdb` is involved: the remote protocol is plain text over
TCP and the client is stdlib only, which matters because no host needs a `gdb` that speaks
m68k. What the server deliberately does not do is watch a run with no end: `trace` hands back
what a bounded window executed (and, under `noloop`, how often), while a count across a whole
open-ended run is a question for a Lua tracer. This server answers what is here, now, and what
happens next.

**`start` asks which name the frame counter answers to** (`frame_symbol`, carried by `start`,
`status` and `machine_map`), because a board with no screen device has none: Advancing the
machine says what that changes.

**`start` refuses to hand back a session that cannot reproduce the reference image, and
kills it.** A failed check that leaves the lying session alive is reachable by the next call,
so the refusal is also the ending. `rom_check` is the same known-answer read on demand, on
the STOPPED machine. `start` refuses while a session is live (one machine per server, and
ending it is the caller's act), and `start`'s `seconds` is only how long the stub is given to
answer (its debugger's banner included, below), held to the same ceiling as every other wait. A MAME that EXITS during that wait ends
it at once, and the refusal says it exited and with which code rather than that the stub did
not answer: the two send a reader to
different places, and a dead process is known dead without waiting a boot's length. A MAME
still ALIVE at the end of the wait is refused `session_broken` with `pid`, `stub_port`, `alive:
true` and `stdout_kept`, the path of a copy of everything it printed, written under
`$XDG_STATE_HOME/mame-debug/failed-starts/` (default `~/.local/state`) before the scratch is
deleted, a bounded number of the newest kept (`FAILED_STARTS_KEPT`), or `stdout_kept`
unavailable, its `why` saying why the copy could not be made. `alive` is the process as the
wait ended; the failed start then kills it, at once: the grace a `close` gives MAME to write its
state buys nothing for a start that failed. The tail in the reply is short, and a hang
nobody can read afterwards cannot be told from a slow boot or a port somebody else took. The
same refusal carries `dial_attempts`, every dial of the wait, consecutive identical errors
folded into one `{"first_s", "last_s", "count", "error"}` (seconds from the launch): a stub
that never listened reads as one run of `NotListening: nothing listens on port N yet`, and one
that listened and was lost reads as something else first.

**A MAME this server spawned does not outlive it, nor an abandoned session.** MAME has no reason
of its own to exit (end-of-file on its Lua console only stops the console, and a dropped stub
connection leaves the machine running), and a server that is SIGKILLed or crashes runs no
cleanup. So a guardian process beside every MAME, in a session of its own, SIGKILLs it the
moment the server is gone (MAME ignores SIGTERM), and `close` stops the guardian with the MAME
(`mame_guardian.py`). And a session no tool has touched for an hour (`IDLE_CLOSE_S` in
`mame_idle.py`, counted from the end of the last call, so a call's own wait never counts) is
closed by the server itself, the ordinary `close`, a running machine included: the next reply
that finds no machine says so, in the `no_session` refusal's message and in `status`'s `note`.
An hour outlasts any pause a working session makes between calls and bounds what a forgotten
machine costs.

**The stub is proved to be this launch's MAME by its pid, never by its port.** A connected stub
leaves nothing listening on its port, so a second MAME told the same port listens beside a live
session, and a dial reaches whichever listens first: two starts racing between a free-port probe
and MAME's own bind drive each other's machines. So `start`, around its one dial, asks which
process listens on the port and then which holds the far end of the connection
(`mame_stub_owner.py`, through `lsof`, a host dependency of `start`):

- nothing on the port yet is the boot under way, waited for like a refused dial;
- another process listening is never dialled, so its one connection is not taken;
- a far end held by another process (the race the listener check cannot close) has the
  connection closed before its first byte, so nothing is sent to that process;
- either of those on a port `start` picked itself is launched again, on another port it picks,
  under the cap below and listed in `start_retries` as `port_served`; on the caller's own
  `stub_port` it is refused `host_failed` naming the port and that pid, since another launch
  there would meet the same process;
- a MAME that exits before it accepts is a death, as above;
- a connection nobody accepts within `seconds` (never less than one request's wait) is a stub
  that did not answer, `session_broken`;
- a host whose `lsof` is absent, fails or hangs is `host_failed`, because whose stub it is
  cannot be established there.

The launched MAME is killed with each refusal.

**The first connection that goes through is the only one `start` makes.** MAME's stub serves one
connection per session and closes its listening socket the moment it accepts it, while the
kernel completes a dial long before the boot reaches the debugger and reads anything. So a
dial that went through is kept, and its handshake waits for what is left of `seconds`. Before it
asks, the boot waits until MAME's output carries its debugger's banner, `Currently targeting `:
a stub without the thread patch fills its target description at the debugger's first stop and
keeps an empty one if asked earlier, and its port accepts long before that stop. Nothing in
MAME's source orders the banner against the stop, so the rule stands on measurement (asked at
the stub's `listening`, the description came back empty on some launches; at the banner, on
none). The wait ends at the banner, at MAME's death, or when one request's time is left of
`seconds`, and the handshake then asks all the same: a build that never prints the banner costs
each start its whole `seconds`. Dialling
again after a slow first answer would leave MAME accepting the abandoned connection and
refusing every later one, which reads as a stub that never listened. For the same reason a
connection whose first byte cannot be sent is refused at once, with `dial_attempts` and the
other fields of a live process's refusal, unless MAME dies within a moment of it, which makes it
a death: a dying process closes its sockets before it can be reaped, and a connection it cut
during the handshake is judged the same way. The handshake's two paged answers, the target
description and the thread list, share one deadline, what is left of `seconds` and never less
than one request's timeout: a stub that never sends the last page is a `Timeout`, not a wait
with no end. A handshake failure that is not a stub not ready (below) is refused
`session_broken` with the fields of a live process's refusal but no `dial_attempts`, saying the
connection was accepted, which of its questions failed (`phase`: `qSupported`, `target.xml`,
`threads`, or `unknown`) and after how long.

**A MAME that dies BY A SIGNAL before its gdbstub answers, other than an assertion's abort or a
stub with no description of the first cpu, a live stub that answers without being ready, and,
on a port `start` picked itself, a port another process took first, are launched again, at most
`START_RETRIES_MAX` more times.** MAME can die inside its own Lua console thread at boot (the console plugin's
thread and the main thread race on one `lua_State`, and it falls in `ll_require`), and the
server cannot prevent a crash inside the emulator, only react to it.
`patches/0003-lua-thread-context-race.patch` removes the race from a build that carries it; on
any build, a relaunch is listed in `start_retries` and every reply's `session.console` counts
the console reader's deaths and the chunks it ran again. A signal at boot is never
the caller's argument's fault, so a bounded relaunch is honest; an EXIT CODE is (missing ROMs,
an unknown system, a bad flag) and would answer the same again, so it is refused at once, except
the one MAME gives with `Fatal error: gdbstub: failed to start listening on address ... port N`
for a port it picked: another process held it, and another launch picks another. So is
an ASSERTION's abort, SIGABRT with the `Assertion failed` line the macOS libc prints: the same
build asserts the same way on every launch. When that assertion is in `input_sdl3.cpp`, the
refusal's `note` names the way round it. A stub with no description of the board's FIRST cpu
is refused at once too, and as `no_channel`, since the build cannot serve that board: a stub
without the thread patch says `Fatal error: gdbstub: cpuname <cpu> not found in gdb stub
descriptions` and ends MAME on every launch, and the refusal quotes that line and carries
`exit_code`, `after_s` and `stdout_tail`. Both ways MAME can end there are this one refusal: its
fatal-error exit code, or, on a build without `patches/0005-debugger-fatal-exit-live-cpu.patch`,
a segfault's signal in the teardown; only `exit_code` and the message's account of how MAME
ended differ. A stub not ready is a LIVE process whose stub accepted the connection and answered the handshake with a target description that declares no register
(`NoRegisters`), one that does not parse (`BadTargetXml`), or an `E` refusal (`Refused`);
nothing the caller gave is wrong there either. The wait for the banner keeps a stub without the
thread patch from being asked too early; what still reaches this is a description empty after
the banner, or a build that prints none. A death after `start` returned is not
relaunched, because its state is gone. Each relaunch is a whole fresh `start`, and nothing of a
failed attempt is reused but its evidence: `start_retries`, ALWAYS in the reply, refusals
included, one entry per relaunch, each with `kind` and its own fields, since the scratch holding
MAME's words is deleted with the attempt; only the refusal keeps a copy of them (`stdout_kept`),
since copies of attempts launched again would push out the kept ones. `died` carries
`exit_code`, `after_s` and `stdout_tail`; `stub_not_ready` carries `error` (the exception's
type), `phase`, `reply` (the
stub's answer, cut short, empty when none came), `after_s` and `stdout_tail`. `[]` means the
first launch answered, never a missing field. When the relaunches run out the reply is
`session_broken` for the last failure, carrying that failure's own fields beside the earlier
ones in `start_retries`, and a success after a relaunch says so in its `summary`.

**The machine runs under the debugger, and `start` and `status` say so in `debugger`.** Every
session attaches the gdbstub. `-debug` itself does not move a capture: an autoboot capture comes
out byte-identical with and without the debugger attached, and one frame either side does not.
What can differ is the method, since a capture taken at one of this session's stops and an
autoboot golden taken by a frame notifier at the same count can land a frame apart in a scene
that changes every frame. The field is `{"attached", "note"}`: the debugger the command line
names, and that sentence beside it, so the difference is read as the method and not as a
regression. It is not repeated on every stop: the fact belongs to the session, and those two
replies are where a session is described.

**Which MAME runs is resolved for each launch, and said.** The ladder is the `binary` argument
(an absolute path), else the `MAME_BINARY` variable, else the `mame` the PATH finds, and the
first rung holding a value is the one taken. A relative value is refused at its argument or
variable; one naming no executable file is refused (`bad_argument`) naming what all three rungs
held and why the one taken is not a program (`no such file`, `a directory`, `not executable`),
and is never passed over for the next, because a caller who named a build and got another would
be measuring the wrong emulator. The ladder is climbed after the session gate, so a live or
broken session answers as such whatever executable `binary` or `MAME_BINARY` names, and a
relaunch after a crash climbs it again. The reply carries `binary` (absolute), `binary_origin`
(`argument`, `MAME_BINARY` or `PATH`) and `version`: the first non-blank line `-version` prints,
asked after the inputs are judged so a refused input spawns nothing, or `{"available": false,
"why": ...}` when it printed nothing, did not return in 5 s or could not run; the start goes on
either way.

**Every path argument is absolute or starts with `~`, judged at the argument.** One rule, scry-core's,
serves every path this server takes: `binary`, `rompath`, each element of `inipath`,
`reference_rom`, `symbols` and `types` and each entry of their mappings, `boot_lua`, `cfg`,
`state_dir`, `gfx_load`'s `path`, every `dest`, and the media file tools' paths. A relative path
is refused because MAME runs from a scratch directory of the server's own, so it would be judged
in one directory and used in another; `~` (and `~user`) is expanded as a shell would, because it
is what a person types and no shell stands between a client and the argument; a NUL or a lone
surrogate is refused because no file call can take either; an empty one where the argument is
required. The refusal of a relative path is one sentence, "`<argument>=<value>` must be an
absolute path or start with `~`", followed by why. `start` judges every
input before it writes anything into `state_dir`. An `inipath` element that does not exist is
handed to MAME, which skips an ini directory it cannot find; an empty one is refused.

**Every input file `start` takes has to be a FILE, and a directory is refused at the argument.**
The reference ROM, the symbol and types files, the boot harness and the cfg are each checked
with `is_file()`; the binary is judged by the ladder above, which also needs the exec bit; the
ROM path is the one input that has to be a directory. `exists()` answers yes to a folder, so
under that check alone a directory carrying a file's name would be taken for the file, and what
refuses it would arrive out of the spawn, after a scratch directory has been made, naming a path
and not the argument. `is_file()` excludes it. Every one of these but the binary, and the ROM
directory, reads `no such <thing>: <path>` from one composer, as does every missing input file
another tool reads (`gfx_load`'s manifest). A file that is there and wrong is the caller's argument too, never a failure of the
tool: one nobody may read is `cannot read the <thing> <path>`, one that is not UTF-8 text is
`<path> is not UTF-8 text`, the same two sentences for the `types` file, the symbol file and the
manifest; whatever else the symbol reader finds wrong in the symbol file, or in `bases` against
it, is refused as `symbols: <what it found>`, an entry of a mapping named as the caller keyed
it (`symbols['maincpu']: ...`).

**The rest of what `start` takes, and what it answers about the table it loaded.** A
`reference_addr` the image does not cover is refused as OUTSIDE it, rather than compared
against bytes nobody supplied. `bases` beside a YAML symbol file is refused: the YAML already
carries each symbol's runtime address. `types` is merged over any `type:` the YAML symbol file
carries beside a `name:`, and a line naming a symbol the table lacks or a format outside the
grammar is refused; the reply's `symbols_typed` says how many of the loaded symbols it formats,
beside `symbols_total` (the count), `symbols_format` (`yaml`, `tsv`, `none`) and
`symbols_by_class`.

**A symbol table belongs to one cpu**, because each cpu runs its own program: the main cpu's
`irq_vblank` says nothing about the sub's. `symbols` given as one path is the FIRST cpu's table
(the stub's thread 1); given as `{cpu: path}` it is one table per cpu,
the shape a board's repository already keeps (`symbols-<set>_<cpu>.yaml`), a cpu spelled
`subcpu` or `:subcpu`. Beside a mapping `bases` is `{cpu: {class: base}}` and `types` is
`{cpu: path}`, and either one in the other shape is refused, since it does not say whose
program it describes. A mapping names cpus, so `start` waits for `-listxml` before it spawns
anything and refuses a cpu the machine lacks. The four fields above describe the first cpu's
table, and `symbols_by_cpu` counts every table loaded, by its cpu. The declarations store keeps
the first cpu's file as its key, so a start that adds another cpu's table keeps what was
declared before; a mapping that gives the first cpu no table keys it by the first cpu it does
give one, named in the key.
`boot_lua` is a harness the server chains after its own and must never call
`manager.machine:exit()`, which would end the session under the debugger; `env` is handed to
it and `inipath` to MAME. The reply's `boot_lua_path` is ALWAYS the server's composed script (it
gathers the machine's inventory on every start, adds the throttle when a frame was asked for,
and chains yours after both), so the path there is never the one passed.

**`close` quits through the console before it kills, and says which it did.** MAME writes
`cfg/` and `nvram/` on a clean exit and ignores SIGTERM, and the console's `quit` only
schedules the exit, so a machine stopped in the debugger has to be let run one step for it
to happen; a RUNNING machine takes the `quit` as it runs. The reply's `ended_by` is `quit` (it
exited within the grace period and wrote its cfg on the way out, which is the proof of a clean
exit, read as `state_written`), `exited` (it exited within the grace period and wrote no cfg),
`killed` or `died` (the emulator had already exited on its own, with its code), because the
endings are not the same ending and `closed: true` would say the same about all of them;
a kill the process did not answer leaves `exit_code` unavailable, its `why` saying so, and the reply's `session` block
describes the state BEFORE closing. When it ends a run the machine was still in, `close`
reports `average_speed`: the speed the host held over the last run window, computed from
the debugger's own emulated clock over the wall clock, because MAME suppresses its own
speed line on a debugger exit. A clock that could not be read is said in that field
(`available: false`, with its `why`) and `close` answers all the same: it is the one way out
of every state, and the speed is decoration on it. The channels' last words (`stdout_tail`,
`errorlog_tail`) come back when the end was not a clean `quit` with exit code 0, which is when
they say something; on a clean one they come back only with `detail=True`, and the reply's
`omitted` names them with `how`.

**A reply that answers less than everything says so.** Where the whole answer is larger than
the question usually asked (`close`'s last words on a clean quit, `machine_map`'s `rom_files`),
the default reply answers that question and carries `omitted`, the names it left out, and
`how`, the argument that brings them; a reply that left nothing out carries neither.

**The console's pipe is emptied before the exit is asked for**, because a chunk MAME's Lua
state still holds at `quit` can take its collector down on the way out; `console_pending_before`
and `console_drained` say what was there and what went, and the `note` names what could
not be drained, so an ugly exit code has its likely cause beside it. The `session` block of the
reply describes the state as it was BEFORE closing, so its `altered` is the truth about the
session this call ended; that is why it reads `alive: true` next to `closed: true`, and the
reply carries `session_describes` to say so in the answer itself. A `status` straight
afterwards reports `alive: false`, which is the state now.

**What a live session looks like from outside, and the contract on it.** A project's own
`make stop` kills by binary path, and this server spawns the SAME binary, so the command line
is the only thing that tells a live session from the project's own run, and a kill path
that does not look at it ends a live session in silence:

- **The mark is the literal `mame-mcp-` in the emulator's argv**, and it is a CONTRACT: a kill
  path that excludes it leaves the live session alone. It rides on `-snapshot_directory`,
  whose value is `snap/` INSIDE the session's scratch directory, so the scratch's own name is
  in the argv; always emitted, never optional. `SCRATCH_PREFIX` in `mame_launch.py` is the
  one place the spelling lives; changing it changes every project's kill path.
- **`start` and `status` report `pid`, `stub_port`, `scratch_dir`, `state_dir`, `errorlog_path` and
  `stdout_path`**, so a reader outside the server can CHECK a claim about the session: which
  process, which stub, where its files are. A pid is a claim to verify, never a handle to
  signal: `close` is the ending. **And `start` reports what it handed the driver**: `env`
  (the variables this call added), `display`, `background`, `flags` (window and speed),
  `throttle_from_frame` and `boot_lua_path`, so a watched run can say which variant it is from
  its own reply.
- **`stub_port` is the gdbstub's**, and named so beside `input`'s `port`, which is MAME's input
  port tag: `0` takes a port the kernel hands out as free (never a walk from a fixed number,
  which two starts at once would share; the proof above is what guarantees the stub is ours);
  a named port is refused if not free. A
  caller who names one names it for a reason, and a silent swap would leave their other
  client talking to nothing.
- **`state_dir` decides the session's SHAPE.** Empty is the fresh, disposable boot: `cfg/`
  and `nvram/` in the scratch, gone on `close`. An ABSOLUTE path is a persistent session:
  created if absent, holding `cfg/` and `nvram/` that two passes can share, and NEVER
  deleted by this server. A path that is a file, or runs through one, is refused
  (`bad_argument`). Given a symbol file, it holds the session's declarations too, and
  the store other sessions share is never opened (*Declarations*).
- **`cfg` installs the project's `.cfg` where MAME reads it, and proves MAME read it.** A
  cabinet's key map is a versioned file in the project, the one source of those keys when
  the driver carries no `PORT_CODE`, and without this a live session plays on MAME's generic
  defaults with nothing saying so. The file is judged before the boot for the two ways MAME
  meets one in silence (a `<port>` without `tag`, `mask` and `defvalue` binds nothing and is
  overwritten on exit; a `--` inside a comment makes MAME refuse the whole file), copied to
  `<state>/cfg/<system>.cfg`, the file `-cfg_directory` makes MAME read, and checked after
  the boot against MAME's own stderr, the `process` channel: MAME prints the parse error as
  an OSD warning (`config.cpp` through `osd_printf_warning`, which the OSD sends to stderr),
  so it never reaches `error.log`, which only `logerror` writes, and a control reading that
  file cannot fire. A session booted on the defaults is closed and the start is INVALID,
  like the ROM check. The project's file is never touched, and `close` says whether MAME
  rewrote the copy in its canonical form on the way out (`cfg.changed`), which is what a
  caller deciding to commit a cfg wants to know.
- **`display` is the session's answer to "main or secondary?", carried on every shared
  start.** Left empty, the server reads `WINDOW_SHARED_DISPLAY` if it inherited it, else the
  secondary, passes that to the helper explicitly and REPORTS it. On a quick run it is
  refused: nobody is watching, and the helper would ignore it out loud on a stderr no caller
  of this server ever sees.
- **`background` decides whether the launch takes the owner's focus**, through SDL3's
  `SDL_MAC_BACKGROUND_APP`: `true` launches behind, `false` in front; omitted, a quick start
  goes behind and a shared one in front. The hint is set or removed in the spawned
  environment, never inherited from the server's, and `env` naming it is refused, so the
  reply's `background` is what the process obeyed.

**Window placement.** Placement and geometry come from an external helper named by
`WINDOW_APP`, so no project re-derives them; a helper that is there and fails is reported in
its own words (exit code and stderr) rather than as absent, and its absence degrades to a
small window rather than taking `start` down (`subprocess.run` on a missing file RAISES
rather than returning non-zero). Quick runs (nobody is watching) get a small window and
uncapped speed; shared runs get the display the session answered with at most of its height,
and real speed. Never `-video none` by hand: on macOS it takes over the display.

**Three more things a shared tool needs to survive outside the machine it was written on**:
each session runs in its own scratch directory, so one project's EEPROM never ends up inside
the shared tool; and the tools serialize on one lock, because two overlapping `run_to` calls
steal each other's breakpoint stops and the first reports a verdict about a PC that is not
its own.

**A board with several cpus is addressed the way MAME's debugger addresses it.** The debugger acts on one cpu at a time, the VISIBLE one, and
makes the cpu that stopped the visible one at every stop, and again when it releases the machine
(`wait_for_debugger` re-sets it on its way out). So a cpu shown by `focus` stays visible while
the machine is stopped, and once it runs the visible cpu is the one it last stopped on. A call that names no `cpu` acts on
it, as a console command that names none does (`help bpset`); a call that names one (`subcpu`
or `:subcpu`) acts on that cpu and leaves the visible one where it was, as `bp addr:cpu`
does; `step` is the one exception, since MAME steps through the visible cpu, so it shows the
cpu it steps.
The visible cpu is READ off the console's `cpulist`, never remembered, and every reply that
touches a cpu names it in `cpu`. A declaration keeps the cpu it was made on and its `ref`
resolves in that cpu's symbol table. What MAME cannot address by cpu is refused rather than
faked: `rpset` names none, so a registerpoint is the visible cpu's and `regpoint_add` naming
another is refused naming `focus`. A stock gdbstub serves its FIRST cpu's registers and memory
alone; `patches/0004-gdbstub-one-thread-per-cpu.patch` serves one GDB thread per cpu, and with
it every register and memory call reads its own cpu's thread and `focus` shows a cpu without
running. Without it another cpu's registers and memory are refused, and `focus` goes through
the console. A board of one cpu answers the same on either build.

**`focus` makes another cpu the visible one, and says what that did to the machine.** On a
build whose gdbstub serves a thread per cpu (`status`'s `threads`), `focus` sends the stub's
`Hc`, which ignores no cpu and releases nothing, and the reply proves it: the frame counter and
every cpu's whole register block read the same before and after (`machine_ran: false`, `unchanged`).
Without that patch the console's own `focus` is the only way, and it IGNORES every other cpu (a
breakpoint or a watch on one has no effect until `debug("observe <cpu>")`); when the cpu it
ignores was the visible one, the debugger runs until the focused cpu executes, and the reply
carries the survey of that stop. Either way the cpu is read back off the console's `cpulist`.

**What `machine_map` and `cpu_info` say of each cpu.** A cpu's identity is `machine_map`'s,
gathered once at `start`: its tag, its type and name, its clock, and each address space it has
with its data width (`cpus`, `spaces`). What it is doing is `cpu_info`'s, read at every call,
one row per cpu `cpulist` lists, in its order: `visible` (the cpu a call naming none acts on),
`ignored`, `suspended` (the debugger's own `suspend`, which stops a cpu without ignoring its
rows), `pc` and `declarations`; `status` lists the `cpus`, read once a session. `pc` is the
cpu's program counter register read off its own thread, `reg` and `value`, as `step`'s `others`
reads it, so no cpu is made visible and nothing runs; a cpu the debugger ignores or suspends
answers the same way. Its `pc` is unavailable, with why, for a register the stub refuses or
cannot decode, and, on a build without the thread patch, for every cpu but the one the stub
serves. The register is the one the stub names the program counter: `PC` on a 68000, and on
the NEC family `EIP`, which the stub serves as MAME's generic pc, the linear address, so on both
it agrees with `status`'s `pc` for the visible cpu. `pc` is unavailable while the machine runs;
`visible` is unavailable when `cpulist` marks no cpu, and `ignored` and `suspended` when the
console answers neither of their shapes, each saying why; a read that latches the session refuses the call rather than
answer a half-read row. `declarations` counts this server's breakpoints, watches and
registerpoints on the cpu in any state, an io tap as a watch; a cpu a declaration names that
`cpulist` does not list gets a row of its own, its declarations counted and every other field
unavailable, and `cpu` can name it; an expr watch has no cpu and is counted nowhere. Counting records
rather than reading the machine, it answers on a running machine too, and a count moves with a
declaration, not with the debugger: a row the console lost is still counted, and
`breakpoint_list` shows it `gone`. Two things no reply carries, because neither the console nor
Lua shows them without moving the machine: a cpu the BOARD holds in reset or on its halt line,
since MAME lists its own suspension alone; and, on a build without the thread patch, the
registers of any cpu but the first, which only the console's `focus` (which runs the machine
there) or a Lua chunk (which steps it) could reach.

**The `cpu` and `space` words.** `cpu` is a tag in either spelling (`subcpu` or `:subcpu`), resolved
one way for every tool (`mame_cpus.match_tag`, through `named`) and refused `unknown_ref` naming the
cpus there are. Empty, it is the visible cpu for a tool that acts or reads at a place and every
cpu for a tool that lists or clears (`machine_map`, `cpu_info`, the `_list` and `_clear` tools); `focus` needs a cpu named, and
`regpoint_add` takes the visible cpu alone, as said above. A reply names the absolute tag in
`cpu`, and a second cpu in the same reply by its role (`read_block`'s `addr_cpu`, `focus`'s `was`).
`space` is MAME's own space name, as `machine_map`'s `spaces[].space` lists it, `program` by
default: a tool takes only the spaces it implements and refuses any other `bad_argument` naming
them, and refuses `io` on a cpu that has none, `bad_argument` naming the cpus that have one, as
`watch_add` and `gfx_film` do. A watch row names its `space` only when it is `io`.

## What every reply carries

Every reply opens with a one-line `summary` and closes with a `session` block (`alive`,
`running`, `altered`, `altering_writes` (how many calls wrote to the machine), `console`, `broken` with the reason once a session
broke, and a `note` once the session is modified or a `lua` call was declared read-only),
composed once the tool's work is done, so it says what the machine is doing after the call
(`close`'s alone describes the state before it, and says so). Whether the machine runs is said
there, and at the top level only by `status`, whose subject it is. Every
refusal of an argument's shape names it and comes before the emulator is touched; what only the
machine can decide (a tag it lacks, a value its console refused, a run that did not end as
asked: `wait_expired`, `readback_refused`, `control_silent`, `not_settled`...) is refused after
it was asked, and says what was asked and what it was left doing. Every number the server sends to the console travels with `0x`, because
to MAME's expression parser a bare `d0` is a register. Every wait with a caller's bound
(`run_to`, `run_for`, `resume` with a bound, `log_wait`, the Lua wrappers) and the two a
person watches longest (`start` waiting for the gdbstub and then its debugger's banner, `close`
waiting for MAME to quit)
report their progress with a message the client paints live, so a long wait and a hung server
stop looking the same; the short file waits behind `memdump`, `snapshot` and `state_save`
finish inside a couple of seconds and say nothing. What the value measures is the work when the
work has a size: `run_for(frames=N)` reports frames done of N and ends at N once the machine is
proved at rest, and `perform` with `until_frame`, begun on a stopped machine whose last stop read
the frame, reports frames done of its window and ends at the window. A retry of `start` reports
its count of the retries allowed. Every other wait reports its elapsed time with no total, because
a bar filling towards the bound would read as progress towards failure; the message says what is
being waited for, in seconds. Within one call the value never goes back: a wait that counts from
zero again (a retry of `start`, a wait between a sequence's steps) continues from the last value
sent, so from then on the value is that offset plus the new count, and a report that would not
rise is dropped.

**A reply that touches a cpu says which one, in `cpu`.** On a board with several cpus two of
them are in play at once, and they are not always the same one. Every tool that acts on a cpu
acts on the one its `cpu` names, and without one on the VISIBLE cpu, which MAME moves to the cpu
that stopped at every stop and which is read off the console's `cpulist` every time a call needs
it, never remembered. The stub's register and memory packets (`registers`, `read_memory`,
`write`, `set_register`, `rom_check`) reach a cpu through its own GDB thread, on a build whose
gdbstub serves one per cpu (`status`'s `threads`): the session selects that thread before each
packet, so a write, its read-back and the next read are all the one cpu's. A build without that
patch serves its FIRST cpu alone, the first `cpulist` lists, so there a call naming no cpu reads
that one whatever is visible, and one naming another is refused (`bad_argument`). On the patched
build a visible cpu `cpulist` does not mark is refused as `unexpected_answer` rather than guessed,
and `registers` and `set_register` on a cpu the stub does not describe (no register map), or whose
byte order is not established, are `no_channel`; a watch's value there is unavailable with why,
unless every scalar of its format is one byte, which has no order to establish. A cpu's byte
order is MAME's: the endianness of its program space, which `start`'s inventory reads and which
is the very value the stub encodes its registers by. It is not established when that inventory
could not be read (its `machine_map` says why, and then no cpu of the board has one) or holds no
program space for the cpu, and when an architecture measured here the other way round (the rows
of `gdb_session._BYTE_ORDER`) disagrees with it, since one of the two is wrong for that cpu.
The console's readers (`disassemble`, `find`, `history`, `memdump`) go through their own
command's syntax (`dasm ...,1,<cpu>`, `find <addr>:<cpu>,...`, `history <cpu>,<n>`, `save
<file>,<addr>:<cpu>,<len>`). `read_block(ref=, cpu=)` looks
the address up in that cpu's map and names it in `addr_cpu`; beside a `tag`, in `read_block` and
the graphics readers alike, a `cpu` would choose nothing and is refused. `breakpoint_list` and `watch_list`
take `cpu` as a filter (`bplist <cpu>`, `wplist <cpu>`), and so does `regpoint_list`; a
registerpoint is armed on the visible cpu alone, since `rpset` names none, so `regpoint_add`
refuses another naming `focus`. A stop's survey is ONE cpu's, the one it stopped on, which MAME makes the visible cpu
at every stop: its `cpu`, its `pc`, its listing, and its `regs` read through its own thread. A
build without the thread patch, or a cpu the stub does not describe, cannot read that cpu's
registers, and `regs` then says `available: false` with `why`, never another cpu's file under
its name. The stop's record carries the same `cpu` into `last_stop`, `stopped_on_its_own` and
`registers(from_last_stop=True)`, and `watch_hit` and `regpoint_hit` name their row's. An
arming reply and each list row carry the `cpu` of the row the
debugger listed, and a `note` when the debugger ignores that cpu, whose rows then have no
effect. `status` names the `cpus`; `cpu_info` says what each is doing. A console that lists no cpu
leaves an annotation unread rather than guessed: `cpu_info`'s readings (unavailable, saying why),
`focus`'s `was` when `cpulist` marked none before the call, `memdump`'s `cpu` on a build
without the thread patch (its file is then checked against the first cpu), and `debug`'s `ignored`
when `ignore` answered neither of its shapes, where `note` says whether the line released the
machine was not judged.

**Writing to a live machine is allowed, and every reply afterwards says the session was
altered.** `debug` counts too: a `fill` or a `softreset` typed through it alters the machine,
and the session says so rather than declaring itself intact. A measurement on a forced state
is not a measurement of the game, and the reader three questions later has no other way to
know.

**What the console channel did to this session is in `session.console`, on every reply.**
Three counts, cumulative: `thread_errors`, how many times the Lua console's reader died;
`reruns`, how many chunks the console ran AGAIN, an earlier call's or the call's own; `lost`,
how many lines it took and never evaluated. Each is counted when a lua-family call reads its
answer back and once more at `close`, which reads what nobody did, so a line sent and never
read back (a `throttle` asked while stopped) moves none of them until the next such read or
the close, and three zeros before `close` describe what has been read rather than the whole
of what the console did. They are three and not one because a reader that restarted harmlessly and a
chunk that WROTE TWICE are not the same event, and the per-call fields that distinguish them
(`thread_errors`, `console_reruns`, `resent`) describe one line's window and are gone from the
next answer. A healthy session reports three zeros rather than omitting the object, because
a zero that is always there is read as looked-at, and an object that appears only when
something went wrong is one a caller never learns to read. The per-call trio is narrower: it
rides, zeros included, on every reply that read a Lua chunk's answer back, and on no other (a
wrapper's pending reply carries `resent` alone). The tools that read one are the Lua family's
`lua`, `input`, `record` and `audio_record`, and the readers that compose one chunk,
`read_block`, `palette`, `screen_view`, `screen_signature`, `series_capture`, `gfx_view`,
`gfx_locate`, `gfx_sweep`,
`gfx_blits`, `gfx_blit_source` and `gfx_film` when it arms. A wrapper's own script that raises
is refused by what it raised: `input` naming a port or field the machine lacks is `unknown_ref`,
a recording on a machine with no screen `no_channel`, anything else `unexpected_answer`; `lua`'s
script is the caller's, `bad_argument`. `throttle` sends a line and proves
it by its mark in `error.log`, and `state_save` and `state_load` speak to the debugger's console
rather than Lua's, so none of the three carries it.
A death is counted by its POSITION in the console's log, so it is counted once whichever call
meets it and in whatever order: a refusal reads bytes it never consumes and a later answer
consumes them again, and a count that followed the path rather than the byte would report
one death twice or, on the path that raises, not at all. A rerun is counted where it is
established instead, against the call being answered, because that is the only place one
can be recognised.

**A throttle that never landed says so on every reply until it is dealt with.** A
`throttle` asked on a STOPPED machine cannot wait for its own mark, because nothing reads its
line while it would wait (the machine executes nothing and the call sends the debugger nothing
more); it answers `pending` and records what it sent. The next
stop's survey reads the log for that mark, and so do `status` and `close`, the last before the
scratch the log lives in is deleted. One that arrives adds no row;
what shows it is `status`, whose `throttles_pending` (`mark`, `on`) lists every switch still
waiting, is always present, and loses the row when the mark is logged. One the console demonstrably worked past without writing, or a machine reporting
the OTHER setting, puts a row in `session.throttles_not_applied` (`mark`, `asked`,
`machine_reports`, `why`) and the row LATCHES: the declaration it would otherwise hang from is
already answered, so a caller who does not happen to ask again would never hear of it, and
every timing they take meanwhile describes a speed nobody chose. Until the console has worked
past the line there is no row, because the `pending` the caller was given is true: the console
may simply not have read the line yet.

**Nothing clears a row but the end of the session, and that is said rather than implied.**
Asking for the switch again fixes the MACHINE; the row is a record that this session measured
at a speed nobody chose, and a reading taken under it stays taken. It is the same kind of
accounting `tallies_not_removed` does -- a pending demoted to a stuck record rather than left
silent -- and the two differ in three ways worth knowing, because a reader who knows one will
otherwise assume the other: `tallies_not_removed` rides on `watch_list`'s own reply and this
rides on the `session` block of every reply; that one is computed when `watch_list` is called
and this one at every STOP; and a tally row DISAPPEARS when the console confirms the removal,
while a throttle row, once earned, does not. What they SHARE is the waiting: `status` lists a
removal the console has not run yet under `tallies_pending_removal` exactly as it lists a
switch under `throttles_pending`, so on both sides a success is a row leaving a list the
caller can see, and never a row of its own.

**A refusal is one contract, and a class holds it.** `status` is `ok` or `INVALID`; an
INVALID carries `code`, one word from a fixed table (`no_session`, `not_stopped`,
`bad_argument`, `needs_call`, `unknown_ref`, `no_channel`, `wait_expired`, `control_silent`,
`session_broken`, `reader_died`...), and `message`, the prose, flat beside whatever context
the refusal has (`last_stop`, `control_hits`, `left_armed`). `verdict` is a measurement's
word (`TARGET`, `TIMEOUT`, `ELAPSED`, `OTHER_STOP`) and an INVALID run carries none. **A wait
answers one too, `status: ok`**: `TARGET` when what it waited for came, `TIMEOUT` when its bound
ran out, `OTHER_STOP` when a stop it did not ask for ended it. `TIMEOUT` is "interrupted at the
bound" on `run_to` and `run_for`, and "left running at the bound" on `resume`, `log_wait`,
`perform` and `drive`. A wait nobody asked for (`resume` with `seconds` 0, `settle_seconds` 0)
carries none, and no boolean restates a verdict. What could not finish still refuses:
`wait_stopped` (a stopped machine logs nothing), `not_settled`, a console step `perform` could
not send with no wait asked (`not_stopped`), and the Lua wrappers' `wait_expired`. A stop's `how`
is prose naming what stopped it, never the verdict again; how `close` ended is `ended_by`.
`bad_argument` asks for another value; `needs_call` for another call first (no scan open, no
manifest loaded, no film armed, a cpu to observe or focus first), which its message names. The
table and the class live in `scry_core.reply_contract`: a code outside the table, an empty message
or a word that is not a refusal's (`why`, a row's or a field's reason, and `reason` or `cause`,
the spellings `message` replaced) is refused where it is written, as a
programmer's error, so a malformed refusal never reaches a caller looking like a verdict. A
bad argument is a refusal too, not an execution failure: the SDK's `isError` is for a bug,
and "I could not look" is a verdict. An argument of the wrong TYPE (a list where an integer
is due) never reaches a tool: the schema refuses it first, and the refusal comes back in this
same envelope as `bad_argument`, naming the argument. The schema is STRICT: nothing is
coerced (`"16"` is not 16, a list sent as a JSON string is a string), except that an integer
stands for a number and a value or an offset also takes a `0x` string (*Names for addresses*),
and an argument name the tool does not take is refused the same way,
never dropped. A direct call (a test, a harness) is judged by the same rule behind the schema:
every count is one judge's, so a bool or a string is refused in the tool's own sentence, an
integral float such as `6.0` is the count it equals (what a client's schema hands over as `6`),
and a fractional one, `nan` or an infinity is refused. An argument held to a fixed vocabulary
(`mode`, `by`, `role`, `space`, `cell_bytes`, `operator`, `channel`, `display`, `gfx_film`'s
`length`) lists its words as its schema's `enum`, made from the tuple the tool judges it
against; a word outside it still reaches the tool and is refused there, `bad_argument` naming
the list. `display`'s list holds `""`, which is not given; `length`'s words are the integers
1, 2 and 4. `breakpoint_at`'s `by` lists the three a breakpoint takes,
and its refusal of another word names every declaration's, `expr` and `pointer` among them,
which the declaration then refuses for a breakpoint. A list whose items are held the same way
publishes them on its items: an `enum` on each of `gfx_locate`'s `flips` and on each side of
`gfx_sweep`'s `sizes`, a `minimum` and `maximum` on each of `gfx_sweep`'s `planes`; the list's own judge still answers,
refusing an empty list and a repeated item too. A vocabulary that depends on the machine (its
cpus, its screens, its palettes) has no static list and publishes none.

**One spelling per concept.** `debug` for the console (`monitor` is the gdb protocol's word,
and it stays in the client), `run_to` for a run to a place, `read_memory` for bytes, `ref`
for how a place is named, `seconds` for how long a wait may take, `count` for how many
steps, `length` for how many bytes (a read's, a watch's, a dump's), `limit` for how many rows
come back (`log`, `history`, `symbols_find`, `drive`), `pattern` for a regex over a
log, `<list>_total` for how many a list holds, listed or not (a scan's addresses are
`hits_total` from `scan_start` on), `frame_<event>` for a reading of the frame counter
(`frame_screen`, `frame_blit`, `frame_as_of`, `frame_baseline`, `frame_from`),
`frame_<event>_planned` for a frame not reached yet and `frames` only for a count of them, a
span of frames `frame_begin` to `frame_end` with its end inclusive, `<what>_frames` the first
and last frame of a set (`judged_frames`, `dropped_frames`),
`<what>_s` for a reply's seconds, `path` for the file a tool reads or writes (`comment_load`'s
argument as well as its reply) and `<what>_path` for any other file a reply names, always the
whole path (`boot_lua_path`; a film cell's `path`), `<what>_dir` for a directory (`scratch_dir`,
`state_dir`, `film_dir`),
`<done>_by` for who or what did it (`written_by`, `chosen_by`, `set_by`, `evaluated_by`;
`by` alone is how a declaration names its place), a tap's `installed` always a boolean, with
`pending: true` beside it while its install has no answer, `indexed` for a PNG whose pixels are
a palette's indices and `screen_indexed` for a screen read as pen indices (the two differ: a
screen of more than 256 pens is read as indices and written as colours), `source` for where in
memory a block is read (`kind`, `tag`, `offset`; a manifest entry's and memdump's span's
`source` are the provenance of a value, a string), `palette` for a palette device a tool takes
and `tag` for a share, a region or a device in `machine_map`'s rows,
`breakpoint_at` / `breakpoint_list` / `breakpoint_clear` for the family (and
`regpoint_add` / `regpoint_list` / `regpoint_clear` for its own), `value` for what
`set_register` forces, `memdump(ref, length, dest)` with its subject first, `bytes` for
a byte count and `raw_hex` for the bytes themselves as hex text. A count names what it counts
and, where the span differs between replies, over what: `bytes_written`, `lines_written`,
`altering_writes`, `steps_completed` (a sequence's), `instructions_completed` (a `step`'s),
`hits_in_run` (a control over one run), `hits_since_armed` (a control in `breakpoint_list`),
`hits_in_frame` (a film cell's trigger hits), `reads` (the readings of a run by
milliseconds) beside `polls` (the `gvblank`s of a run by frames); `hits` is always a list of
what was hit, and `machine_ran` says whether the machine ran. Every tool declares a `title`, and every reader a `readOnlyHint`, so a client
can tell the two calls apart on the line it paints and run the readers in parallel.

**The stub's EMPTY packet is "unsupported", never "done".** A client that refuses only an `E`
reply takes a packet the stub does not implement (`$#00` on the wire) as a good answer, and
`write`, `set_register` and `breakpoint` then report an operation that has not happened; the
readbacks catch the first two after the fact, and a breakpoint that never armed silences the
very control `run_to` relies on, so the client itself says no.

**A write is READ BACK, and so is a forced register.** `bytes_written: 4` is not a reply while a
write to ROM has changed nothing; `readback` and `verified` are what a caller can act on.

**A register prints at its cpu's declared width**, in every tool that prints one. A fixed
eight digits makes a 16-bit V30 register look 32-bit and its own ceiling look like a broken
tool, so `registers` carries a `register_bits` map stating each in bits, and a 16-bit register
answers to its short name too (`AX` for the `EAX` a V30 is served under). The widths, the names
and the byte order are each cpu's own: the stub describes each cpu on its own thread, the
session reads each description once, and the byte order is MAME's word for that cpu, so two
cpus of different architectures are each read as what they are.

**One vocabulary for a reason, in every reply.** `note` is a reply's note, or a sub-object's:
one string, its sentences joined by `; `, and when a reply has two things to say (the tool's own
and the console's account of a chunk, say) both stand in it. `why` is a row's or a field's
reason, the server's, and where it rests on what the console said it quotes those words in it (a
tap the console refused, a refused removal: never an `error` beside it); `error` is only ever
the words another program answered, quoted as the datum itself (`debug`'s `refused` rows,
`start`'s failed attempts). A flag a row raises is a boolean beside its `why` (`desync: true`).
**A datum that could not be read is `{"available": false, "why": ...}` in the place its value
would have taken, and no reply carries a null**, whether the datum could not be read or does not
apply here: the two differ only in their `why`. So a stop's `frame` on a board with no counter, a
cpu's `pc` while it runs, a list tool's `cpu` when none was named, `failed_at` of a list that did
not fail, a `cfg` nobody gave, a row's `created_at` from before rows were dated, an expr watch's
`length`, a file's fields once the file is gone, and a watch's `reading` that could not be read.
A watch's `reading` that was read says `available: true` beside its value.

**One spelling for each kind of number a reply carries.** An address or a port a reply reads
back is eight hex digits (`0x0070001e`); a ref stays in the spelling a call names it back by
(`0x2031fc`, a symbol as typed), and a trigger is that ref, `trigger`, beside `trigger_addr` where
it resolved (`watch_list` carries `trigger_addr` alone). An offset into a block, a region or a
share is an integer. A value or a mask is `0x` text, at the width it was written at where the
reply knows it (a capture row's `data` and `mask` at the bus's width, a scan's values at its
cell's, a watch hit's `wrote` at the access's, `input`'s `value` as the 32-bit port value it set, a
correlation's `mask` at the bus word's); what a watch DECODES under its format (its `value`, a
`watch_hit`'s `before` and `after` read from memory) is what that format reads, a number, a
string, a list or a struct, and a bus watch's `before` and `after` are the integer written. A time is `_s`, rounded
by what it is for: a span a reader acts on (`waited_s`, `since_s`, `after_s`) to the tenth of a
second, and a time that is itself the reading, often below a tenth (`emulated_*_s`,
`average_speed`'s two, `query_s`, a film's `frame_period_s` and its costs per frame), to the
microsecond; a capture row's `time_s`, the instant of one access, at a double's full precision,
since two accesses one cycle apart are nanoseconds apart; a declaration's `age_s` is whole
seconds. A bus's width, which no argument names, says its unit: `data_width_bits`; a scan's cell
says its own, `cell_bytes`; every other `width` is the word its tool's own argument takes (bytes on
a watch, pixels on a screen, as a screen's `height` is), `size` is bytes, and a rate says its
unit (`refresh_hz`, `sample_rate_hz`). A wall-clock instant is `<event>_at`: a declaration's
`created_at`, a stop's `wall_at` in `last_stop`.

**One rule for every wait.** `seconds` is the wall-clock bound of the call, or of the one wait its
description names, from more than zero to the ceiling the descriptions print; `frames` and
`milliseconds` are EMULATED time, never the wall clock's. Zero is a wait of its own kind in two
places only, each saying so: `resume(seconds=0)` waits for nothing and leaves the machine
running, and `perform`'s and `drive`'s `settle_seconds=0` never waits for a stop.

### A long wait, and a cancelled call

A wait that can run for seconds reports its progress about once a second, as MCP progress
notifications a client paints in the call's row: the frames or milliseconds done of those
asked, a count it is waiting on, or the seconds of the bound when time is all there is. A step
of `perform` or `drive` reports through the sequence's own line (an `until_frame` list reports the
frames instead),
`perform step 2 of 5 (run_for): ...`, so the line never goes back.

A call the client cancels ends at the next poll of its wait, the way its own bound would have
ended it, and answers nothing: the protocol sends no response to a cancelled request. A tool
with no wait of its own (a read, a single console command) runs to its end first. The next reply, whatever tool it
is, says once what that call left (a step of a sequence is the sequence's cancel): in `cancelled` (`tool`, `after_s`, `left`, one of `stopped`,
`running`, `closed` or `unknown`, and `earlier`, the cancelled calls before it that no reply
reported) and in its summary, `after a cancelled run_for (stopped): ...`. A call cancelled while
it waited for another to finish did nothing, and leaves no record.

A call that had finished its work when the cancel arrived is recorded the same way, with no
end applied, and what its reply carried (a stop it found, what a stop applied) is said by the
next reply instead. A cancel that arrives after the server's last look, while the reply is on
its way, is not seen.

Each tool declares its end:

| End | What the cancel leaves | Tools |
|---|---|---|
| `stop` | the machine stopped through `stop`'s own path; a stop the call made on its way is recorded as its own | `step`, `run_to`, `run_for`, `trace`, `series_capture`, `perform`, `input`, `record`, `audio_record` |
| `kill` | the emulator ended, with the grace that writes `cfg/` and `nvram/` when a session is up to be asked; a MAME still booting is killed at once | `start`, `close` |
| `none` | the machine as the call found it | `resume`, `read_block`, `screen_signature`, `palette`, `screen_view`, `gfx_view`, `gfx_locate`, `gfx_sweep`, `gfx_blits`, `gfx_blit_source`, `gfx_film`, `log_wait`, `drive`, `lua`, `throttle` |

Any other tool that meets a cancel ends `none`.

## Names for addresses

The symbol file is the project's YAML (`addr:`/`name:` pairs) or the linker's own
five-column map (`name`, linear, segment, offset, `class`), and the second needs no
converter. A map row's address is the runtime one only for CODE: DATA is copied to RAM at
boot and addressed off a segment register, so its runtime address is a base the running
board decides plus the row's offset, while the map's linear address for it is the ROM copy
of its INITIAL value, which reads plausibly and is wrong (a scene id reads zero off the map's
address while RAM holds the live scene). So `bases` maps each non-CODE class to the `0x` base
the board uses (`{"DATA": "0x400"}` on a V30 with DS=0x40) or to the word `rom` for a class
resident where the map says (a tile sheet in ROM), and a class with no base REFUSES the
start rather than loading an image address in silence. `reference_base` says where the
reference image's first byte sits in cpu space, so a raw linker output checks without
anybody padding zeros onto it.

**An address is written `0x`, and nothing else is one.** `0x4a0` (or `0X4A0`) is an address in
every tool that takes a ref, a pointer's base included; any other ref is a symbol, so `adc` names the symbol even where it is
also valid hex. Bare hex that names no symbol of the cpu's table is refused (`unknown_ref`) with
the `0x` spelling it most likely meant, because the table deciding would read one build's name as
another build's address; a declaration stored by such a name stays reachable by it, as an
expression watch (a register such as `d0`, on no cpu) stays clearable by its text with no `cpu`,
and a capture can be declared again on its block and the trigger name it is held on, kept and
capturing nothing while the build lacks that name. A ref is
read once, so a clear reaches only declarations of its own kind (a name never the row at the
address its letters spell), under the rule each clear's description and refusal state for its
family (`REF_MATCH` in `mame_declarations.py`): a `0x` address in any spelling, a symbol in any
case, a pointer's base as either, an expression as typed but for its numbers, each read as the
console reads it (bare, `0x` and `$` hex, `#` decimal, `0o` octal, `0b` binary: `7fff`,
`0x7fff`, `$7fff` and `#32767` are one; a run of letters such as `ab` stays a name, and a name
keeps its case), and, with `space="io"`, an io tap's port as an address or its block as a symbol,
as above; a comment, one per place, is reached at its place too (*A comment is a declaration too*). A table
name that itself starts `0x` cannot be reached by ref. What the comment file or the store already
holds keeps the reading its file gives it: a hex-shaped ref in the comment file is a symbol, a
stored pointer base and a stored capture trigger are an address when written `0x` and a name
otherwise (one a rebuild dropped points nowhere, as any lost name does), and a stored row
by address in bare hex is that address, listed in the `0x` spelling, and one by symbol in the
`0x` spelling is the address it spells. The same spelling holds offline, before any table: text
that starts `0x` and is not hex is refused; `by="address"` takes a `0x` ref and `by="symbol"`
never does; every address ARGUMENT (`reference_addr`, `reference_base`, `linear`, a `bases`
value) and every io port is written `0x`, bare hex refused (`bad_argument`) naming the `0x`
spelling. A writer's `pc` (`gfx_film`, `gfx_blit_source`) is a ref: a symbol or a `0x` address.
Conditions and `debug` are the console's own grammar, where a bare number is hex; `lua` is
Lua's, where it is decimal.

**A value, a byte offset or a pen is an integer or a `0x` string.** A number the debugger
shows in hex (the `value` of `set_register`, `scan_filter`, `gfx_film` and `input`; the `offset` of
`read_block`, `gfx_view`, `gfx_locate` and `gfx_sweep`; every pen: `pen_base` of `gfx_view`
and `gfx_sweep`, `palette`'s `first` (a pen, where `gfx_view`'s `first` counts tiles),
`palette_log`'s `pen`, each of `screen_view`'s `pens`) takes a JSON integer or a string written `0x` (`"0x1234"` is 4660), in a call and in
a `perform` or `drive` step alike, and nothing else: decimal text is refused, because `"4660"`
reads as plausibly as the digits of `0x4660`, and so is a bool, and either spelling past 64 bits,
the widest number MAME's debugger holds, which a `0x` string could otherwise spell past what any
reply can print. The number is judged by the tool's
own range whichever spelling carried it, and a reply hands it back in a form the argument takes
again: an integer, or, where the reply shows it beside what the machine holds (`set_register`'s
`value` beside its `readback`, `gfx_film`'s `value`, its hits' and its `baseline_value`), `0x`
hex at the register's or the trigger's width. A count (`frames`, `length`, `limit`, `count`, a
listing's `first`, `keep`) is an integer only, judged in one sentence: `length=0 is outside
1..1024`, or `is below 1` where nothing caps it.

**A name is a name of ONE cpu's table**: every tool that takes a `ref` resolves it against the
table of the cpu the call names, else of the visible one (a reader or a writer, `run_to`'s
target and control, a declaration and the symbols of its condition), so a name only the other
cpu's program has is an unknown symbol here, and the same name in both tables is not ambiguous:
the cpu decides. A declaration resolves against its own cpu's table wherever it is read.

`symbols_find` looks a name up in a cpu's table (`cpu`'s, else the visible one's, named in the
reply as `cpu`; case aside), or says which symbol
a RUNTIME address (after `bases`, not a map's own `linear` column) is inside, and says what
each address IS to the machine from the console's `map` (`memory`: `ram`, `rom`, `latch`,
`unmapped`; `unknown` while it runs), so a change watch on the ROM copy of a datum is known
before it is tried. A `ref` with a segment in it (`12345:0010`) is refused on every tool that
takes a `ref`, cold or with a machine, because the address here is linear; an unknown NAME
waits for the machine, being a symbol in THAT machine's table.

**A type file** (`types`, YAML) or a `type:` beside a symbol names what a symbol IS: a scalar,
an array, a string, a struct or a pointer of the value grammar (`scry_core.value_format`), so a
watch on it needs no format and a pointer says what it points at.

## Declarations

The debugger holds the ARMED instances; the server holds what the caller MEANT: a breakpoint
or a watch at a SYMBOL, or at a raw address, or a registerpoint's condition as typed. Keeping the
intent is what makes a rebuild free: an address moves when the program is relinked, a name
does not. So `breakpoint_at`, `watch_add`, `regpoint_add` and their lists and clears work on
declarations, each stamped with the session
that made it (`origin`) and when, and each list row says whether it is `inherited`, brought
back from the store at `start` rather than declared this session, because no reply names the
session's own origin to compare against, and how old it is (`age_s`, whole seconds since
`created_at`, computed when it is listed; unavailable for a row with no date or one with no offset;
negative for a stamp ahead of this host's clock, floored and never clamped, since a zero would
claim "just now"); a re-declaration adopts, takes the new session's stamp, and never stacks a
second breakpoint; a name absent from THIS build is stored `unresolved`, kept, and said so (a
registerpoint's is the exception at the ADD, which refuses what the console cannot evaluate, and
is kept `unresolved` only across a `start`); and
every list reads the debugger's own `bplist`, `wplist` or `rplist` back, so `armed` is the machine's
answer and a row the debugger holds that no declaration placed is `foreign`. A row is known by
its INDEX, which MAME numbers with one counter across every cpu: the row a call armed is the index
that appeared in the list, a re-declaration adopts only a row nobody holds on the visible cpu (the
one `cpulist` marks, where an arm lands), a row typed through `debug` at a declaration's address
or one under another cpu stays `foreign`, and a clear removes its own row by index (`bpclear`).
One row is one declaration: a second ref on the same address of the same cpu is refused naming
the first. A stop adopts a listed row only under its own condition: a row whose condition is not
the declaration's, another one or none, is `ambiguous_ref` saying both and naming the `bpclear`
that removes it, at the declaration and at `start`'s re-arm alike, and a `bp` whose row `bplist`
shows without the condition sent is not armed at either.

**A declaration keeps its cpu**: the one `cpu` names, else the visible one, read when it is
declared, and every list row and arming reply says it as `cpu`. Each cpu runs its own program,
so the same ref on two cpus is TWO declarations, each with its own row (or tap), and "one row,
one declaration" compares (cpu, address): the same address on the other cpu is another place. A
declaration made again with no `cpu` after a stop moved the visible cpu is therefore the new
visible cpu's, a second one; naming the first cpu again adopts its own row. The clears take
`cpu` as the lists do: with it, that cpu's declarations of the ref alone; without it, every
cpu's. A row is armed through the console with the cpu named (`bp <addr>:<cpu>`,
`wp <addr>:<cpu>,<len>,w`), which never moves the visible cpu. A count watch's tap is bound to
that cpu when its install is composed, not when the pipe runs it, and its `tally_id` names any
cpu but the first. The next `start` re-arms each declaration on its own cpu, named, so the re-arm never moves the
visible cpu, and a row already listed is adopted only under that cpu; a registerpoint re-arms
only when its cpu is the visible one then, since `rpset` names no other, and is otherwise
`unarmable` naming the `focus` that lets `regpoint_add` place it again. A show or pointer watch is read at
every stop on its own cpu, through that cpu's thread of the gdbstub's thread patch, as a change
watch's bytes are; without the patch another cpu's are unavailable, saying why, and a pointer
watch there is refused, since its pointer cannot be read. An expr watch has no cpu: the console
evaluates it on the visible cpu, and another `cpu` is refused.

**The store is keyed by the system name plus the RESOLVED path of the symbol file `start` was
given**, in an XDG state directory (`mame-debug/declarations.json`), or, for a session started
with a `state_dir`, in `<state_dir>/declarations.json` beside its `cfg/`, `nvram/` and `sta/`,
and `start` reports which (`declarations`: `persistent`, `path`, `key`, `held`). Two
spellings of one file are one key; two boards sharing a map (a family of sets) are told apart by
the system; two maps of one board by the path. A session started with NO symbol file gets no key, because nothing could
re-resolve by name: its declarations are by address and die with the session, and the reply
says so. A corrupt file refuses the start, before the emulator is spawned, and is never
discarded.

**A `state_dir` session never opens the project store**, so nothing it declares, adopts or
clears reaches another session's rows, and nothing another session left re-arms in it. A
directory named for the first time starts with an empty store, since copying the project's rows
in would bring back exactly what naming it keeps out; a directory named again brings back what
earlier passes declared there. The project store's own directory is refused as a `state_dir`,
directly or through a link, and `comment_save` refuses the project store's file from any session.
Which store is in use is `start`'s `declarations.path`, and it decides what a clear with
`all=True` reaches (each family's clear reaches that family only; an empty `ref` is refused). With a `state_dir`, the rows
declared under that directory, by this session and any earlier pass over it: safe when the
directory is this session's. Without one, the project store every session of that system and
symbol file shares: a row another session declared reads `inherited: true`, with `age_s` since
it was last declared, so a caller who did not declare it clears by `ref`.

A declaration is stamped with its cpu's build FINGERPRINT (system, ROM image and
that cpu's symbol file, hashed, with the tag for any cpu but the first; `start` and `status`
report the first cpu's as `fingerprint`, and `status` each cpu's as `fingerprints`), so a
rebuild of one cpu's program leaves the other's raw addresses alone, and a raw address is
re-armed at the
next `start` only over the same fingerprint, whoever declared it, and listed `stale` over
another (declaring it again adopts it): an address re-resolves against nothing, and armed
blind it lands on whatever the new build put there. A name re-resolves whatever the build.

**What the store held comes back at the next `start`**, re-resolved against the table that
start loaded and re-armed before the park's survey, and the reply's `declarations.rearm`
accounts for every one of them, and all of it is INHERITED, since nothing of the new session
is declared yet, each entry the row a list gives the same declaration (its `origin`, `inherited`
and `age_s` above among it). A row the store holds with no cpu,
written before a declaration had one, is read as the first cpu's, the only table a start then
took: `rearmed` (a breakpoint, a registerpoint or a change watch armed and read back
from the debugger's list, by name whatever the build and by raw address over the same
fingerprint, whichever session declared it; a breakpoint's, stop or control, a change watch's or
a registerpoint's row the debugger lists disabled is adopted with `state: disabled` and a `note`
naming the command that enables it), `stale` (a raw address
declared over another build), `unresolved`, `unarmable` (with why: a change watch's write side unmapped in
this build, a row the debugger did not list or lists under another condition, or an address, a
change watch's byte or a
registerpoint's row that another declaration in the store already holds) and `evaluated` (a show
watch, which needs no arming). Nothing is dropped and nothing is silent: a name this build lacks re-resolves at
the next one, or the caller clears it.

**A watch has two halves, `show` (read at every stop) and `change` (a write watchpoint), and ONE REF MAY NOT BE BOTH.**
One ref carries one declaration per cpu: the store refuses a `ref` already declared under the
other half, or under another mode or shape, an address matched in any spelling (`0x1000` and
`0x01000` are one ref), while a symbol and the address it resolves to are two refs. MAME arms no trap byte (the bytes read the same before and after), and the rule is
kept anyway, because a rule that holds only sometimes is one nobody can rely on. A row a
store holds under the retired mode `read` is read as `show`, and written so at the next write.

**A control is a breakpoint declared with `role="control"`**: MAME counts its hits in one of
its ten `temp` variables through a conditioned console breakpoint (`bp addr:cpu,(++tempN)==0`)
and never halts on it, so it costs a run nothing. The temps are the debugger's, one pool for
every cpu (measured), so a control on each cpu counts in a temp of its own from that pool.
MAME's debugger skips the breakpoints of the instruction a stop lands on when the stop came from
outside the instruction stream (the end of a frame, of a time, of a step), and on release that
instruction executes unchecked. A run by frames lands on one such instruction every frame, often
the first of the handler the vblank interrupt enters, so `run_for(frames=N)` counts each landing
it releases for a control sitting on it, the stop a previous run by frames ended at included. A
release from any other such stop (a step, a run by time, `resume`, `run_to`, the steps a Lua read
spends) still misses that one entry, so a control is best not placed on the pc the machine is
stopped at. A
stop breakpoint, declared or the target of a `run_to`, takes a `condition` in the console's own
expression grammar (`w@DemoLen==0x25`; a symbol of the table is replaced by its address first,
and one spelled like a register of the cpu the row is armed on, as the boot gather read that
cpu's names, is refused as ambiguous), which is what turns "run to the vblank until this variable reads X" from hundreds of round trips into
one run. A declared breakpoint KEEPS its condition as typed, for the reason it keeps its ref
by name: at the next `start` the symbols re-resolve against that build's table, so a variable
the rebuild moved is compared where it now lives, and a row already listed is adopted only
under the text THIS build produces. The reply and the list carry `condition` as the console
reads it now, and `condition_typed` when that differs from what the caller wrote. The
condition is evaluated once (`print {<condition>}`) before it is armed, as a registerpoint's is
and for the same reason, on the row's cpu: `print` reads the visible cpu's symbols, so that cpu
is shown through the stub for the evaluation and the visible one put back, which runs nothing.
A put-back the stub refuses (the cpu to put back is one the debugger ignores) never hides the
evaluation and never goes unsaid: `breakpoint_at` and `watch_add` refuse before anything is
stored, the message saying what the evaluation found and `visible_cpu` naming the cpu left
visible, so the caller chooses the visible cpu and declares again; `start`'s re-arm has no
caller to answer and arms each row by its cpu's name, which the visible cpu does not change,
so it keeps the row and says it in the `note` of its `rearm` block. A condition the console
cannot evaluate is refused at `breakpoint_at` with the console's words and nothing stored; at `start`, `unresolved` for a name this build lacks and `unarmable` for anything
else, and kept either way; `breakpoint_list` says `unresolved` for the former beside the
`addr` its ref resolved to, as `regpoint_list` does for a registerpoint's. A condition too long
for one packet of the stub, in the `bp` that arms it or in the `print` that evaluates it, is
`bad_argument` judged before the declaration is stored; a ref that does not resolve yet sends
nothing, so its condition is judged when a later `start` re-arms it, which reports it
`unarmable` if it does not fit. A row the debugger's
`bplist` does not list after an arm is `readback_refused` with the declaration KEPT, and the
reply says so (`stored`, `armed: false`, `state: gone`, and a `note` naming the next `start`,
which re-arms it, and the `breakpoint_clear` that removes it). A row `bplist` still lists
after `breakpoint_clear` sent its removal keeps its record, as a watch's does: `disarmed`
does not name it, the reply's `note` says which row is held and names the `bpclear` that
removes it, and a stop there is then named by its address.

**Watches: who wrote this byte.** A watch is `length` bytes at a `ref`, rendered as a format
of the value grammar (a scalar `u16`, N of them by `length`; an array `u16[8]`; a string
`char[16]`; a struct `{x:i16,y:i16,flags:u8}`; a sized format implying its length; a symbol
the table types reading as its type with no format named) in its cpu's own byte order. With
no `fmt` the widest unsigned format the length is a whole number of is chosen (`length=2` is
`u16`), so a narrow watch needs no format. A **show** watch arms nothing: its value rides in
`watches` on every stop survey, and `watch_add` and `watch_list` read it too whenever the
machine is stopped. All three speak one vocabulary on two axes, each in its own field.
`state` is where the watch is PLACED (`evaluated` for a show or expr watch, which arms
nothing; `armed`, `disabled`, `gone` or `stale` for a change watch, read against the
debugger's `wplist` in the list and in the survey alike; `unresolved`, `null_pointer`).
`reading` is what THAT call read: `available: true` with `value` and `raw_hex`, `available: false`
with the stub's refusal and never a zero, or `bus` with `last_wrote` for a write-only register; a
running machine answers no read, so there is no `reading` then. A change watch is `armed`
and read at the same stop, which one word could never say. An **expr** watch is any expression the debugger evaluates
(`beamy`, `totalcycles`, `a0+4`), checked once on the console and read at every stop in ONE
`print` beside the frame. A **change** watch is a WRITE watchpoint armed through the console
on its cpu (`wp <addr>:<cpu>,<len>,w`), and the stop it produces says who wrote the byte: the
write has LANDED when the machine stops, the stop's `pc` is the instruction AFTER the writer,
and the console's own line, which `-debuglog` sends to `debug.log` in the scratch, names the
watchpoint by its index, the value written, the address written and the writer's pc. The
stub's stop packet for a console row names address 0 (measured), so that line is the
attribution. So the stop's `how` is `watch <ref>:
<addr> written by pc <writer>` and its `watch_hit` carries `writer_pc`, `wrote`, `to`,
`before` (the bytes this server last saw there), `after` (the bytes now), every write the
console logged since the previous stop (a 68000 writes a long as two words, and the console
prints one line per write) and the lines themselves, with `values_from: memory` when the address
reads back through the handler it is written through and `values_from: bus` when the console's
`map` says it does not (a write-only latch), in which case the values are the writes the
console logged and never a memory read; a watch stop with no line in the log says no row can
be named rather than guessing one, a stop by a row this server never armed (one typed through
`debug`) is named as such by its line, and `rearmed` says the watch was a leftover re-armed
from an earlier session rather than declared this one.

**The control of a watch is decided the way `run_to`'s is, by naming what silences one.**
The ROM copy of a datum whose live copy is in RAM: the debugger ACCEPTS a watchpoint on a ROM
address, lists it in `wplist`, and it can never fire, which is exactly the silence `run_to`'s
control exists to expose. So `watch_add` asks the console's `map` for the write side of the
address on the watch's cpu (`map <addr>:<cpu>`) BEFORE arming, and for a change watch
`unmapped` is `status: INVALID` naming the line. A count, a capture or a film is a write TAP, and a tap
sees every write the cpu makes there whether or not anything handles it (measured, program and
io), so it arms on an unmapped write side with `write_maps_to: "unmapped"` and a `note` saying
the guest's write goes nowhere (and, on an address that reads as ROM, where the live datum is);
`write_maps_to` in the reply says where it does map, read past
the names MAME prints before the handler for a watchpoint or a Lua tap already there. A watch set while running is taken and FIRES, like a breakpoint, so
it is armed at once and the reply says `while_running`. The debugger's `wplist` is read back
after every arm and every clear, so `armed` and `disarmed` are the machine's answers; a row
`wplist` does not list after the `wp` is `readback_refused` with NOTHING stored, since a watch
is written to the store only once it is armed (the reply says `stored: false`, `state: gone`
and a `note` saying to declare it again once the list shows the row); a row
still listed after its removal was sent keeps its record, as a breakpoint's does, and
`watch_clear`'s `note` names it (a stop that row then produces is named by that ref, says the
declaration was cleared, and names the `wpclear` that removes the row); a row it holds that this server never placed is `foreign`,
listed and never deleted. Arming writes nothing to the machine, so `altered` stays false.

**A change watch conditioned on the value written: `condition`.** "Who writes bits 0-1 of
this byte" is lost among a register's writes when every one of them stops the machine, and a
count watch never stops at all. So a change watch takes a `condition` in `breakpoint_at`'s
grammar, where `wpdata` is the value being written (`wpaddr` the address, `wpsize` the size),
and arms `wp <addr>:<cpu>,<len>,w,<condition>`: the console evaluates it at every write and
halts only when it holds, logging the stop line only then, so every write a `watch_hit` lists
is one the condition let through, and the hit names the `condition`. `wpdata` is the bus access
as it landed, shifted down past the lanes it did not write and cut to those it did
(`points.cpp`), so a byte write is the byte and a word write over a one-byte watch is the word. The condition goes through the same steps as a breakpoint's: a symbol
of the table becomes its address, one spelled like a register or like `wpdata`, `wpaddr` or
`wpsize` is ambiguous, it is evaluated once (`print {<condition>}`, which answers outside a
watchpoint because those three live in the debugger's global symbol table) and refused with the
console's words when it cannot be, because MAME SETS a watchpoint whose condition it cannot
evaluate and that row never fires. It is judged before anything is stored, a watch through a
pointer that is null yet included, at the widest address its `wp` can spell, since the stop
that finds the pointer set arms it with no call left to refuse it in. The declaration keeps it
as typed and re-substitutes it at the next `start`, `unresolved` there for a name the build lacks. The reply and the list carry
`condition` as the console reads it and `condition_typed` when that differs. Only a change
watch takes one, since only it stops. The `wp` answers the same sentence with a condition or
without, so the list is the proof: a row `wplist` shows without the condition sent is
`readback_refused`, and a row already listed at the range whose condition is not the watch's is
never adopted (`ambiguous_ref`, the breakpoints' refusal: both conditions said, the `wpclear` that
removes it, and `watch_clear` for a row a declaration of this server owns). A pass run with
`disarm_watches` re-arms the watch under its condition.

**A watch that COUNTS: `mode="count"`, the datum's twin of a control breakpoint.** A change watch
stops at the first write, and a census asks the other question: which values does this register take
over a whole pass, and from which pcs. A count watch is a write tap composed by the server (MAME's
own `install_write_tap` on the visible cpu's program space, over the bus words the range touches,
keeping only the writes that land inside it) that counts every write by value and by writer pc and
never stops the machine for one. The install is SENT to the Lua console, like a `throttle` asked
while stopped, and evaluated when the console next reads a line (*The console* says when), so
`watch_add` moves nothing and answers `installed: false` with `pending: true`; a periodic hook writes each tally to a
file in the scratch at every debugger stop, and the stop survey reads it back as of that stop:
`installed` and `pending`, both booleans (`installed` true; false with `pending` true until the
console answers; false with the console's own words in its `why`, which is how a tap MAME refuses is
reported rather than counting zero for ever), `frame_as_of`, `superseded` (the tally on disk is
older than the stop surveyed), `total`, `since_last_stop` (at a STOP only: a `watch_list` between
two stops is a look and consumes nothing, and a total that fell is a `reset`, never a negative
count), `values` (each bus write decoded to the bytes it landed, with `value` in the watch's own
format when one write covers the range whole and `partial` otherwise; a 68000 writes a long as two
words, so a u32 tally sees words), `writers` (`pc`, `count`, and `symbol` when the table places it),
the top rows in a survey and the whole tables in `watch_list`, with `overflow_values` and
`overflow_pcs` past the bucket cap. Both tables are cumulative since the install, not since the last
stop, and capped at that one number of rows each: a write whose value, or whose writer, found its
table full is counted in `overflow_*`, and that value or writer is never named; only
`since_last_stop` is per stop. A tally of zero is a measurement, said beside the frame it is as of;
a dump the hook has not written is `no_dump_yet`. A range that splits a bus word of its cpu's
program space, covering part of one at an edge (a word at an odd address on a 16-bit bus, which a
V30 writes as two bytes), is refused `bad_argument` before anything is sent: a write lands in one
bus word, so the rows of a word covered only in part are fragments with no `value`, where a range of
whole words is counted word by word. The refusal names one count per bus word the range touches, and
the re-arm at `start` accounts a stored one `unarmable` in the same words; on a cpu whose program
space `start` did not gather, `watch_add` takes the range and its `note` says the check did not run.
A port's count (`space="io"`) is judged the same way over the io space's own width, since a word
`out` at an odd port reaches the tap as two fragments too, and its refusal names the counts in
`space="io"`. The write side is then asked of `map`, as a change watch's is, and an unmapped one is
armed with its `note` (*The control of a watch*); one range carries one tally; it is by symbol or by address, never through a pointer; `disarm_watches` never touches it;
`watch_clear` SENDS the removal, `status` lists it under `tallies_pending_removal` until the console
has run it, and what the console did with it comes back under `tallies_not_removed` on `watch_list`
when it did not happen: `refused` (evaluated, and it raised, the console's own words in its `why`) or
`lost` (the console done with the line and never having evaluated it, by the install's rule below),
the tap still in the guest with its record no longer held here. A removal is never resent, because
the id is the RANGE and a resend could carry away a tap declared since; the row repeats on every
call instead, and declaring the range again installs over the old tap and CARRIES ITS COUNTS; over a
removal that ran, it counts from nothing. The files are the range's, so a removed tap's can be on
disk when the range is declared again (the dumper rewrites them at every stop until the removal
runs): an install still pending reads none of them. The one exception is an install that replaced
its range's record with no removal in between, which reads them, since they are the live tap's own.
An install that finds no tap of its range registered deletes them before it counts, so every dump
read after it is its own (a capture's rows file is kept where a tap is there, since its rows are
what the install carries on appending to). A stored tally comes back at the next `start` with the
rest. It sees its cpu's writes and nothing a DMA or a blitter writes on its own bus, because that
traffic never passes the program space.

The install is proved rather than assumed. An install line the console ECHOED AND NEVER
EVALUATED (no sentinel, and behind the echo a dead reader, the console reporting the line's
own top-level failure, or a prompt: every reader prints one before it reads, and the console
starts the next reader only once it is done with the line, so a prompt behind the echo is the
console gone past it) is sent again once, at the next survey, and `install_resent` says so
(the console trio's `resent` counts a call's own line); a second loss is the state
`install_lost` with `installed: false` and a `why`, because a tally that never installed is a
zero that reads as a measurement. Nothing else ages a line, frames least of all: the console
runs a line only once the reader that echoed it is idle, and a reader can stay busy across
frames. A line echoed and not yet run, or not yet echoed, is `pending` and waits, for as long
as the console never gets past it. The reply to `watch_add` carries
`tally_id`, `installed: false` with `pending: true`, `lines_ahead`, `call` (the console line's number), a `note`,
and both `write_maps_to` and `read_maps_to`; a survey's `values` are ordered most written
first, with `values_total` beside the top rows.

**A callback that raises is counted, never read as a zero.** The taps, the notifiers and the
dumpers of the censuses (the count watch, the capture, `palette_log` and `gfx_film`) run their
bodies under `pcall` (`mame_callbacks` says why: MAME itself drops a tap's error silently), and the
reply carries what they caught where the census it qualifies lives, as `callback_errors`: `count`,
the times a body raised, and `first`, the first message, cut to one line of printable ASCII,
unavailable while none has. It rides on each count and capture row of a survey and of `watch_list`, on
`palette_log`'s reply and on the pixel's `set_by`, on `gfx_film`'s reply, on `gfx_blits`' and
`gfx_blit_source`'s replies and on the refusals that read the capture's rows, and on each capture
of `gfx_draft`'s correlations. A census beside a count above zero is short of what happened: a body
that raised kept nothing of that event, or part of it (a count watch's `total` moves before its
tables do), and a draft proves no command from such a capture. A dumper that keeps failing counts
once per run of failures, and leaves the dump before it, if there is one, on disk; the guard
closes whatever file it had opened, and logs `MCP_DUMP_FAILED <id> <message>` to `error.log`, so a
count watch's or a capture's reply over that older dump says, in its `why`, the error that stopped
the newer one rather than a timing. The summaries of
`watch_list`, `palette_log`, `gfx_film` and `gfx_blits` say so, as do a `set_by` that finds no
write to its pen and a film's `nothing_kept`. A row is counted only once it is kept, so a body that
raises half-way leaves no hole in a rows file. The wrappers' own notifiers (`input`, `record`,
`audio_record`, the launch's throttle) are not guarded: each proves itself by a mark in
`error.log`, so one that raises leaves its mark missing and its reply pending or unfinished, never
a clean zero, and its `[LUA ERROR]` line stays in `log`.

**A tally counts WRITES to its own range and nothing else.** A census conditioned on ANOTHER
register (the value of word 7 at each write of word 15, the whole block at each trigger) is not
a count: a site that fires without rewriting the other word inherits its last value, and two
independent tallies cannot be joined afterwards. That question is a capture.

**A watch that CAPTURES: `mode="capture"` with a `trigger`.** The joint question a count cannot
answer ("the scale each blit carries", on a register block the raster routine also writes)
needs the block as it stood at the one write that matters, every word together, per event. A
capture is the count watch's tap put on the TRIGGER instead of the block, with the same
machinery (sent, never stepped for, `installed` proved by its sentinel and resent once, removed
by a send, re-armed at `start`, never touched by `disarm_watches`, its errors counted): it
keeps each bus write whose lanes cover the trigger's byte and appends one row: the `frame`, the
beam `line` and the emulated `time_s` of the write, the writer's pc (`CURPC`, placed in the symbol
table), the trigger write's own `data` and lane `mask`, and the `block` in the watch's format with
its `raw_hex`. The block is read where its values live: the memory
share or region of the one address map entry that reaches it, when that entry holds it whole
(a write-only register block has no read side, so the space would answer zeros; and where
entries overlap MAME's bus answers with the one installed last, so a first match would read
the memory under an overlay), else the space's direct read, once the console's `map` answers
memory at the block's first byte and at the first byte of every entry reaching into it; a
block with a handler anywhere in it is refused, since a direct read of a handler answers zeros
that look like data and a read through it would run it once per trigger. The trigger is a
symbol or a `0x` address on the capture's cpu, its write side (a read capture's read side)
asked of `map` as a count watch's range is (an unmapped one is armed, with its `note`), and one naming a symbol the
build lacks is refused at `watch_add`, unless it is the name the capture on that block is already
held on, which is declared again and kept (*An address is written `0x`*), and `unresolved` at the
next `start`; an address is kept
in a ref's one spelling (`0x2031fe`), so two spellings are one capture, and is a raw address,
`stale` over another build. The tap runs BEFORE the write lands, so the block
holds every word already written and, when the trigger lies inside it, the trigger's value from
before this write (measured: capturing a counter's long on its low word, each row's low word is
one less than the row's `data`); the write's own value is `data`. The first rows are kept up to
a cap and the rest counted in `overflow_rows`, and `total` is every trigger access, so `rows +
overflow_rows` is the census a count watch on the trigger gives over the same pass. The rows
wait in the guest until a debugger stop, where the periodic hook appends them to `rows_path` in
the scratch; `watch_list` shows the first rows of that file as `first_rows`, cut at the
listing ceiling, since each row carries a whole block and a longer list crossed what a client
takes in line; the rest is in `rows_path`, which holds every row. That ceiling holds only if a
row is bounded too, and a struct's field names are the caller's: so a capture's format is
refused at `watch_add` when its widest decoded block prints wider than the widest an array or
a string makes over the largest block a capture holds, and a stored one past it is `unarmable` at
`start`. A stop's survey lists NO row
and says `rows_listed_by: "watch_list"`: every reply carries a survey whatever the call was
about, and a block of rows in each one drowned the answer that was asked for. Beside them:
`rows_kept`, `overflow_rows`, `rows_max`, `since_last_stop`, `trigger_addr`, `trigger_type`,
`source` (a write capture's) and `tally_id`, the tap's id as a count watch's is. The
block is at most `SHOW_WATCH_MAX` bytes (the tool's description gives the number), as a show
watch is, since each row carries it; a capture is by
symbol or by address, never through a pointer; one ref carries one declaration, so the same
block on another trigger is another capture under another ref, and one block on one trigger
under a second ref is refused naming the first.

**When, to the cycle: a row's `line` and `time_s`.** The time is MAME's own clock as the tap
reads it, which inside a tap is the accessing cpu's local time: two accesses one cycle apart never
share it, and `time_s` carries a double's full precision for that reason, never a rounded value.
The line is MAME's `vpos()`, which Lua does not bind: the time since line 0 plus half a pixel,
over the line's period, wrapped over the `frame_period / scan_period` lines the screen has, never
a driver's constant, so a tie half a pixel before a line is that line, as `vpos()` has it. A
machine with no screen stamps `frame` and `line` unavailable and still its time. The live matrix holds
the line to the debugger's `beamy`, read before and after the instruction that makes the write,
with a derivation one line ahead as the control that has to miss. In `rows_path` a row is one
line, `r n frame line seconds.attoseconds pc data mask block`, with `-1` for a frame and a line
the reply shows unavailable, and the time exact to the attosecond.

**One clock across cpus.** Two captures on two cpus, a write on one and a read on the other,
carry the same clock, so their rows order by `time_s` as the board ran them; the order the rows
were written in is not that order, since MAME runs one cpu's slice and then the next's. Below the
driver's interleave, the time a slice lasts, the order of two cpus' accesses is the scheduler's
choice and not the hardware's: two accesses that close are ordered by the emulation, which is the
answer the emulation gives and the only one this server can.

**A capture of READS: `trigger_type="r"`.** `wpset`'s word for a read, beside the default `w`.
The tap sits on the trigger's reads, through MAME's read tap, and its row is the access alone:
`frame`, `line`, `time_s`, `pc`, the value read as `data` and its `mask`, and no block, because a
Lua read tap that reads memory inside its callback re-enters the bus, which MAME does not survive.
So `ref` is the trigger itself, which `trigger` names again or leaves out, and a length or a
format is refused naming why. The trigger's read side is the one asked of `map`: none named is
refused, and an unmapped one is armed with a `note` saying the cpu reads the bus's unmapped value
there. A read tap sees no instruction fetch, and no ROM read, which MAME serves through direct
access, so a read capture on code or ROM keeps no row; and it runs at every
read of the trigger, past the row cap too, so one on a word a loop polls costs a Lua call per
poll for as long as it is held. Its id carries an `r`, so its tap is never a write capture's;
but its `ref` is the trigger, and one ref holds one declaration, so a write capture of that same
word under that ref is refused, the refusal saying which access the held one captures. It is stored and re-armed as a write capture is, counts its
`callback_errors` as one does, and is listed with `trigger_type`. Every reader of a block
(`gfx_blits`, `gfx_blit_source`, `gfx_draft`, a region write naming the captures it moves) takes
write captures alone. A read capture of a port is refused: `space="io"` takes a write trigger.

**A watch on a port: `space="io"`.** A board that drives its palette or its sound through ports
writes them with `out`, and nothing of that lands in the program space, so a program-space tap is
blind to it. `space="io"` puts a count watch's range, or a capture's trigger, in the cpu's io space
(MAME's `cpu.spaces["io"]`); a capture's block stays in the program space, where a block lives, by
symbol (typed by the table like any block) or by address. A port's count that splits a bus word of
the io space is refused as a program count's is (*A watch that COUNTS*). A port is written `0x` like
every address (the io space has no symbols); its write side is asked of the console's `mapi` as an
address's is of `map`, and a port nothing handles is armed with `write_maps_to: "unmapped"`
and its `note`, as an unmapped address is. A cpu with no io space is refused naming the ones that have one (`cpus_with_io`). Change, show
and expr watches are refused there: a watchpoint and a stop's read are the debugger's, in the
program space. An io tap is for this session only: the declaration store has no space, and a server
that reads it would re-arm the port as the program address of the same number, so the reply says
`stored: false` and its `note` says why, and the tap is listed and surveyed by its bare `ref`
beside `space: "io"`, and cleared the same way (`watch_clear(ref="0x6", space="io")`; a ref
written `0x6@io` is refused naming `space`), while its id carries the space (`6_2@io`): port 6
and RAM address 6 are two taps. Its row carries `created_at` and `age_s` from the declarations' clock, as
theirs do. One ref holds one tap, as a stored declaration does: another length, trigger or mode
under a held ref is refused until it is cleared, because a second install would leave the first
counting where no list reaches it. A capture a port triggers is never a manifest command's, whose
fire word is a program address.

**The rest of what `watch_add` takes.** A show watch is at most `SHOW_WATCH_MAX` bytes, and a
change or count watch at most `read_memory`'s ceiling: a region is `memdump`'s job. With no
`fmt` and a `length` alone the widest unsigned scalar the length divides is chosen (`1` is `u8`, `2` is `u16`, `4`
and `8` are `u32`), so a narrow watch needs none; name one to read as signed or as a float, and
a named `fmt` the width is not a multiple of is refused. One ref carries one declaration, so
another width, format, mode, condition, trigger or trigger type under the same ref is refused
until it is cleared, and a change
watch sharing a byte with a range another declaration already arms on the same cpu is refused
naming it, since two watchpoints on one byte make "who wrote this byte" ambiguous (a count watch
is refused only on an identical range and a capture on an identical block and trigger, since
neither stops the machine). `by` is `auto` unless a caller must
force one, and `auto` is the address rule (*Names for addresses*): a `0x` ref an address, a name
the table knows a symbol, bare hex naming none refused, and any other name a symbol not yet
defined, kept `unresolved`. An expr watch is checked on the console once, a
name it cannot evaluate refused with its answer, then read at every stop in one `print`, so
declaring more costs the stop nothing; its survey entry carries `value` and `hex`, it arms
nothing, is never stale, and comes back `evaluated` at the next `start`. A change watch's
`watch_hit` carries `writes` (each with `wrote`, `to` and `pc`), and the last
written value of a watch whose `values_from` is `bus` rides on every later stop's `watches` as
`last_wrote`.

**What `watch_add` answers, by mode.** Every reply: `ref`, `by`, `mode`, `stored`, `armed`,
`state`, and `already_stored` and `while_running` (an io tap, session-only, answers `space`
instead of both). A watch at a place adds `length`, `fmt`, `cpu`, its `addr` once resolved and
`pointer` through one. A show watch, and an expr watch, add `reading` when stopped. A change
watch adds its row's `entry` and `index`, `condition` (and `condition_typed`), `values_from`,
`write_maps_to` and `read_maps_to`, and `reading` only when its values come from memory. A count
watch adds `tally_id`, `installed`, `pending`, `write_maps_to`, `read_maps_to` and the console's
account of the install; a capture the same tap fields with `trigger`, `trigger_type`,
`trigger_addr`, `trigger_maps_to` and, triggered by a write, the `source` its block is read
from.

**A watch reached through a pointer.** The question a C program asks is "who writes this
field", and the field lives in a struct on the heap, reached only through a global pointer.
So `ref` takes `[base]`, `[base]+0x28`, `[base]-0x4` or `base->field`, with `base` a symbol or
an address holding the pointer (an offset whose digits read as decimal and as hex, `+10`, is
written `0x`; one digit or a hex letter reads one way): the pointer is read there, at the width its type declares
(`ptr16{...}`/`ptr32{...}` in `types`, the grammar's pointer format, which also names what it
points at so `->` knows the field's offset and format) or else the width of the stack
pointer, the one register as wide as a pointer on every cpu (the program counter is not: a
V30's is served as a 32-bit linear address while its near pointers are 16-bit offsets), the
offset added, and the watch placed at the result; the reply's `pointer` block says through what. On
a board relocated by `bases` a pointer read through a symbol of a relocated class is an
offset in a class's segment, placed under that class's base the way `disassemble` places a
direct operand (the raw offset reads a plausible wrong place): `pointer.relocated` says so,
and `class_from` says who named the class. The type does when it carries one (`ptr16@CODE`,
`ptr16@CODE{...}`), which is what a routine's address kept in DATA needs (read as its base
symbol's class it lands in DATA, where there is no routine): the base is the caller's
`bases` entry for that class, else the map's own segment base (`linear - offset` of its
rows, what CODE and a `rom` class run at), and a class the table does not carry is refused
naming the ones it does. Otherwise the class is the base symbol's, right for a data pointer
kept in data; the address form of the base relocates nothing. It is re-resolved at every
stop, because the pointer can move: a change watch is moved with it (`moved: {from, to}`),
and a null pointer is the state `null_pointer`, never a watch at zero. A base the table
lacks is refused naming what it most likely is, a stack local, which has no stable address
to start from.

**A registerpoint is a declaration with no address**: `regpoint_add(condition)` arms MAME's own
registerpoint (`rpset`), which the debugger evaluates after every instruction, so the machine
stops wherever the condition comes true. Its `ref` IS the condition, as typed, in the grammar
`breakpoint_at` and `run_to` take for theirs; what is sent is that text with this start's
addresses in place of its symbols, and the reply carries both (`ref`, `condition`). Keeping
the typed text is what lets a symbol inside it re-resolve at the next `start`, and having no
address is why a registerpoint is never `stale`, never `aliased` and has no `role`: its list row
carries `condition`, `index` and `cpu` where a breakpoint's carries `addr`. The same
condition declared again is the same declaration, and a row the debugger already lists under
exactly that condition ON THE VISIBLE CPU is adopted, as a breakpoint's row is; the same
text under another cpu compares another register file and is left alone, listed `foreign`.
It is armed on the visible cpu, the one the console targets, and `cpu` says which; the
row this server placed is known by the index the console gave it. Two conditions that differ
as typed and read the same once their symbols are addresses are one row, so the second is
refused `ambiguous_ref` naming the first, as a second breakpoint on one address is.

The condition is EVALUATED ONCE before anything is stored (`print {<condition>}`), because
the debugger arms a registerpoint whose condition its own evaluator refuses, and such a row
never fires: a malformed condition, or a register this cpu lacks, is `bad_argument` quoting
the console, and nothing is stored or sent. An action can never be given, since a comma, a
brace or an assignment is refused before the console hears of it. A debugger that does not
know `rpset` is `no_channel`. The list is read back after the `rpset`, so `armed` is the
machine's answer, and a row it does not list is `readback_refused` with the declaration KEPT,
the reply saying so (`stored`, `armed: false`, `state: gone`, a `note` naming the next
`start` and the `regpoint_clear` that removes it); `regpoint_clear` sends the row's index as
the list spells it (hex) and reports as `disarmed` only the rows the list lost. At `start`
every stored registerpoint is re-resolved and evaluated again: `rearmed`, `unresolved` when the
console answers `unknown symbol`, or `unarmable` with why (a console that raised while
evaluating one is that declaration's `unarmable`, and the pass goes on); none is dropped.

When one fires the server changes nothing: the stop's `how` is ``registerpoint '<ref>'`` (with the
inherited clause when the declaration came from the store), the reply carries `regpoint_hit`
(`ref`, `condition`, `index`, `cpu`, `pc`, `note`), and the registerpoint stays armed and stored. A
registerpoint fires at EVERY instruction while its condition holds, so the next advance stops
one instruction on until the register moves or `regpoint_clear` removes it, which is what the
`note` says. `run_to` and `run_for` answer `OTHER_STOP` for it, since a registerpoint is never a
target, and a `run_to` whose controls had not fired yet answers `cut_by_other_stop` for it, as
for any other stop. Like a breakpoint, it changes what stops the machine and nothing in it, so
it does not
mark the session altered; `rpset {<condition>}` typed through `debug` is counted the same way,
and an action after it is counted as a write.

**A comment is a declaration too: a text at a place, kept in the store and shown in MAME's own
disassembly.** `comment_add(ref, text, cpu)` holds it on one cpu by symbol or by raw address, so by
symbol it follows its name through a rebuild and by address it is listed `stale` over another build;
`start` feeds again those that resolve and are not stale, one per place, and lists them all in
`declarations.comments` under `rearmed`, `stale`, `unresolved` and `unarmable`, each row the one a
list gives (an `unarmable` one with `why`) as `declarations.rearm` lists the rest, the whole rows
being `comment_list`'s, which asks the machine nothing and answers while it runs.
`declarations.held` counts comments with the rest; `cpu_info`'s counts do not, since a comment
neither stops nor watches, and a comment shares its ref with a watch or a breakpoint. A place
carries ONE comment per cpu, the place being the resolved address, or for a name this build lacks
the name itself: a second `comment_add` there in any spelling replaces the text and keeps the first
`ref` and `by`, so a comment made by symbol keeps following it. `comment_delete(ref)` removes the
comment of `ref`'s kind whose own ref `ref` spells, else the one at the place `ref` names, however
it was spelled; there is no delete-all. A `stale` comment of the other kind is out of both: its
place is another build's, so only its own spelling replaces or deletes it. A rebuild can bring
several comments to one place: all are kept, the pane shows the first the store holds that it can
show, and each other is `unarmable` with its why (a `stale` one is `stale`, and is never fed); an
add, a load or a delete there reaches the one its ref spells, else the one the pane shows, and
whichever is fed last takes the pane. A comment at such a place whose new text the pane cannot show,
or a delete of the one it showed, hands the place to the next it can show. The text is one printable
line, no tab and no edge whitespace, at most the bytes one line of MAME's `comlist` holds before its
console wraps. The pane is a VIEW of the store: each comment is fed through the console's `comadd`,
which names no cpu, so a comment on another cpu is fed by making that cpu visible through the stub
and putting the visible one back, and each is read back off one `dasm` line, which ends ` //
<text>`. One the pane does not show stays in the store as `unarmable` with its `why`: a text holding
`"` (the console keeps the backslash that escapes it) or ending in `\`, a command past the stub's
packet, a cpu a build without the thread patch cannot show, a `comadd` the console answered with
text, a line that does not read back. A text the console cannot carry (a `"`, a final `\`, a command
past the packet) replacing one the pane showed clears the old one from the pane; a `comadd` the
console answered with text, or a cpu the stub cannot show, leaves the old text where it was, and a
delete of the comment clears it. A delete says, from the line read back, whether the pane still
shows the deleted text. MAME also keys a comment by a CRC of the instruction bytes under it, so code
that moves in RAM hides its comment in the pane while the store keeps it, and a delete over bytes
that changed since leaves MAME holding it, hidden, until `close`, which the delete's `note` says. A
session error raised after the store was written (the session breaking, or the stub refusing the
pane's command) says in its message that the store holds the change: the store is written first, and
the next `start` feeds the pane from it. MAME writes the comments it holds into its comment
directory whenever a debugger session exits; the server pins that directory inside the session's
scratch whatever an ini says, so the file dies with the session and nothing the store dropped comes
back from it. MAME binds no comment call to Lua, hence the console.

**The comment file is the record a project versions beside its symbol file**, written by
`comment_save(dest)` and read by `comment_load(path)`, never implicitly; the convention is
`<symbol file name without its extension>.comments.tsv` beside the symbol file, the first cpu's on a
board with several. It is UTF-8 with no byte order mark and LF line ends; line 1 is exactly `#
comments v1: ref<TAB>cpu<TAB>created_at<TAB>text`, and every other line is one comment in that
order, separated by tabs, the text last and so the rest of the line, sorted by cpu and then ref in
code-point order, so a re-save moves only what changed. `cpu` is the absolute tag (`:maincpu`) and
never empty here; `created_at` is a date, a time and an offset from UTC
(`YYYY-MM-DDTHH:MM:SS+00:00`). In a file an address is always `0x` and hex and anything else is a
symbol, so a saved symbol `fade` never comes back as an address. `comment_load` is all or nothing:
it refuses the whole file naming the first line that breaks the format (lines of nothing but spaces
and tabs, and `#` lines, are skipped after the header; CRLF reads as LF), a cpu this machine lacks,
an address past its space, an expression where a ref goes (what the cpu's table does not name and
holds an operator or a bracket), or one comment named twice in any spelling of its ref. Two rows a
rebuild put at one place are both loaded, as the store keeps them through the rebuild, so what
`comment_save` writes of such a store `comment_load` reads back; where the store already comments a
place the file comments too, the file wins, the first file row there replacing the store's row and
any other coming in beside it (a `stale` row of the other kind excepted, as for `comment_add`) and
each row it replaced comes back whole, a row already holding the file's text is kept (brought to
this build when it was stale), and rows only the store holds stay. The file has no column for the
build, so a raw address loaded into another build is trusted for it: what has to survive a rebuild
is commented by symbol. `comment_save` never writes the declaration store's own file, and replaces a
file only when it is a regular file that reads whole as a comment file, naming each row the old file
held that the store does not, whatever the spelling of its ref and cpu.

## Advancing the machine

**MAME cannot advance one cpu alone.** Every run and step goes through the visible cpu, and every
other cpu runs its share of the same emulated time. `step(cpu=X)` makes X visible first with the
stub's `Hc`, which runs nothing, then X executes while the others run; its reply carries
`others`, each other cpu's program counter REGISTER before and after (read on its own thread:
`PC` on a 68000, `EIP` on the NEC family, as `cpu_info`'s `pc` reads it). A stop leaves
the visible cpu where MAME puts it, the cpu that stopped, and the survey's `cpu` names it. On a
build without the thread patch another cpu cannot be shown without running, so `step(cpu=)`
naming one is refused.

A live session advances by ADDRESS (`run_to`, always with a control), by EMULATED TIME
(`run_for(milliseconds)`, through the console's `gtime`, or `run_for(frames)` through
`gvblank`), or with NO DEADLINE (`resume`). The first two hand the machine back stopped.
`run_for` proves the time moved with MAME's frame counter before and after, and it waits
until that counter stops moving before answering, because the stub answers the console while
the machine still runs, and a running machine handed back UNKNOWINGLY is the worst state a
session can be in.

**A board with no screen device has no frame counter, and is run by time.** MAME's debugger
registers `frame` (with `beamx`, `beamy` and the vblank stop) only on a machine with exactly one
screen device, `frame0`, `frame1`... on one with several, and nothing on one with none: a vector
board has a display and no screen chip, and `print frame` there is an unknown symbol. The
screens `machine_map` lists are no guide, since it lists that vector display, so `start` asks
the console, `frame0` first, and `start`, `status` and `machine_map` carry the answer as
`frame_symbol`, unavailable with the reason when neither name exists. On such a board `run_for(frames=)`,
`perform(until_frame=)` and a `lua` run over frames are refused `no_channel` before anything is
released; `run_for(milliseconds=)` works, its rest proved by the emulated clock (the console's
`time`) reading the same instead of the counter, and `no_progress` there means the clock did not
move. Every `run_for(milliseconds=)` reply that released the machine, on every board, carries
`emulated_before_s` and `emulated_after_s`, each unavailable where `time` answered no time. The same clock stands in for the counter wherever rest is proved: a step
`over`, a `stop` of a run the console started, the first contact after one. A stop's `frame` is
unavailable there, `focus` proves nothing ran by the register blocks alone, and the console refusing an
expression is `no_channel`, an answer about the machine, never a broken session.

**Running to a target always arms a CONTROL breakpoint and reports its hit count.** Several
different mistakes leave a MAME breakpoint silent, and every one of them looks exactly like
"that routine is never called". Both rows are read back from `bplist` before the machine
moves: a row the console took and does not list would come back TIMEOUT beside a control that
fired. The target is armed through the console on `cpu`, or on the visible cpu when none is
named, and removed by its index; a stop at its address is `TARGET` only when it is that cpu's,
and a row of another cpu at the same address is another place and does not block it. `run_to`
arms the target alone, reads its
row back before the machine moves, reads the count of every control on the target's cpu around
the run (`control_hits`, `controls`, each entry naming its control's `ref`, `cpu` and `hits_in_run`) and refuses
to run with none there, naming the cpus the declared ones are on (`control=` declares one on the
way, on the target's cpu, its shape judged before anything as every ref's is; a `control`
name that does not resolve in the target cpu's table is refused (`unknown_ref`) naming that cpu, and when the name is a control declared on another cpu the refusal
says so, names that cpu, and names the `breakpoint_at(ref, role="control", cpu=...)` that
would put one on the target's). A control on another cpu runs another program: it fires while the
target's cpu is held in reset, so it cannot say that cpu ran. When the target's cpu or a
control's is unknown, the control counts by its address alone, as a row's adoption falls back. A
run that timed out and whose controls never counted is INVALID and still surveys the stop
it left, with each control's `dasm` and a note on choosing one; a run that reached its
target is `ok` whatever the controls counted, since the target proves the cpu ran. A run refused
at the readback or broken under the run carries `message` alone. `disarm_watches=True` disarms
the armed change watches for that one pass and re-arms them after it, whatever the run
answered (`disarmed_watches`, and `not_rearmed` when the list lost one, each by `ref` and
`cpu`; a re-sent row is read back only under its own cpu), because a watch on a
byte written every frame otherwise stops every later run of the session; a `session_broken`
leaves the ones it disarmed disarmed. The stop's `watches` are surveyed while they are off, so
the rows of those re-armed are placed against a `wplist` read after the re-arm, as `watch_list`
places them. An INVALID run carries no `verdict`, and its `code` says
which way it failed: `control_silent`, with `control_dasm` (each control's `dasm`, by
`ref` and `cpu`: is it code?) and a `note` on what a control is chosen from, since "wrong
address" and "right address,
rarer than assumed" read the same; `cut_by_other_stop`, any other stop (a watch, a
registerpoint, a foreign breakpoint) that ended the run before a control could fire, so nothing
about the controls was measured;
`readback_refused` (a row listed without the condition sent is removed first, since nobody
would own it), `not_settled` or `session_broken`. `condition` stops at the target only when
it holds, in the console's expression grammar with the table's symbols replaced by their
address, and the reply carries it as sent: it turns "run to the vblank until this variable
reads X" from a round trip per frame into one run, with the control counting beside it. One too
long for a packet of the stub is judged before the control is declared and before any watch is
disarmed, so the refusal changes nothing. A `ref` that is the
target carries no stop of its own, because one row per address means a stop there could not
be told from the target's: declare the stop elsewhere or clear it before `run_to`.

**`run_for` by frames counts the frame counter itself**: `gvblank`, one per counter tick, each
confirmed on the counter, so a golden is a marker plus N frames, and N milliseconds is not N frames.
MAME keeps "a vblank happened" as one flag that the first cpu to run after it consumes, and stops
there only if that cpu's own `gvblank` is set, so on a board of several cpus the run goes through
the FIRST cpu: after a stop on another, or a `focus`, the stub's `Hc` makes it visible first (it
runs nothing) and the reply's `note` says so. A build without the thread patch cannot, and refuses
the run by frames while another cpu is visible, as it does when the debugger ignores the first cpu;
by milliseconds stops on any cpu. The last landing is proved at rest, two readings a tenth of a
second apart, before the run is ELAPSED: the readings that confirm each landing come milliseconds
apart, and on a machine running flat out they agree without it having stopped. A stop breakpoint or
a change watch that halts the machine inside either run ends it as `OTHER_STOP`. By frames a
console-started run sends no stop packet, so the tell is a `gvblank` that moved the counter by
nothing, or a `Stopped at ...` line in the console's log, looked for after every `gvblank`: the
counter ticks as a run leaves a vblank stop, so a stop later in that frame lands with it moved. A
control's row never counts as a stop wherever the machine lands, which is also what keeps
`stop`'s `how` from naming a control. A breakpoint typed through `debug` ends either run as
`OTHER_STOP` too, named ``breakpoint <n> at <pc>, typed through `debug`: `debug("bpclear 0x<n>")`
removes it``: its only trace is the console's own `Stopped at breakpoint <n>` line, read
off the same `debug.log` a foreign watchpoint is named from; the index is what says whose the row
is, and a row this server armed keeps its own name. Every survey reads that line, so a `resume` or a
`stop` that lands on such a row names it the same way. A registerpoint (the console's `rpset`) is
named off its own line, `Stopped at registerpoint <n>`, with the condition its row lists and the
`rpclear` that removes it; a watchpoint typed through `debug` the same, off its `Stopped at
watchpoint <n>` line, with what it wrote and the `wpclear`. In all three the index is spelled as the
debugger's list prints it (hex), so it can be pasted into that command. It fires at every
instruction while its condition holds, so a run started with it still true stops one instruction on
with the frame counter where it was, and that is `OTHER_STOP`, never `no_progress`. `run_for`
reports `cycles`, the visible cpu's `totalcycles` over WHAT WAS ASKED FOR: the exact clock behind
the duration, and by frames the N frames requested and never the ALIGNING `gvblank`. That one is the
tick a run from a mid-frame stop spends reaching the vblank of the frame it is already inside; it
moves no counter, so counting it made a session's FIRST advance report roughly double the clock it
took while `frame_after - frame_before` stayed exactly N. `polls` reports the `gvblank`s sent and is
the tell that the alignment fired: N+1 for N frames. So the same one frame reads `polls: 2` from a
stop inside a frame (a breakpoint's, or the park `start` leaves) and `polls: 1` from the vblank a
frame run ends on, while `cycles` spans the N frames asked for either way. By milliseconds `reads`
counts the readings of the frame counter (the emulated clock on a board with none) until they
rested. The first run after `state_load` whose
baseline still reads what `totalcycles` read right after the load has `cycles` unavailable,
with why: MAME's debugger refreshes that counter only when the cpu executes, so the span would
be off by the distance between the two states, too short after loading an older one and too long
after a newer one; anything that executed in between (a step, an aligning `gvblank`) makes it count
again. A `stateload`/`sl` or a `rewind`/`rw` typed through `debug` leaves it the same way, and so
does a `softreset` typed there, for another reason its `why` names: the console's reset is
applied by the next run, which restarts the count inside it. The `reset` tool steps to apply its
reset, which refreshes the counter, so the run after it reports cycles; a typed line that also runs
the machine marks nothing either, and neither does a lone `rewind` the console refused ("Rewind
error occured", which MAME prints only when it could not step back), since it replaced nothing. A
run by milliseconds whose counter (or clock) did not move is INVALID `no_progress` with the survey
saying where the machine is, and the machine is stopped; a run shorter than one frame lands here,
and one that went down is `frames_went_backwards`. By frames, a counter that did not move over its
`gvblank`s cannot be told from a machine still running, so that `no_progress` has no survey and
leaves the machine RUNNING until `stop`.

**`trace(milliseconds, frames, dest, seconds, cpu, noloop)`** is `run_for` with MAME's own
tracer on one cpu: the console's `trace <file>,<cpu>` is armed, `run_for`'s own body runs
(the same bound and the same reply, with `trace` added just before `session`; no
`disarm_watches`, and `seconds` defaults longer, since a trace also writes and parses a file),
and `trace off` closes it, all in the one call, because a tracer left armed keeps writing on the
next run of a client that forgot it. The machine is never let go of with the tracer open: a run
that bailed out leaving it moving is stopped first, then the tracer is closed, and a close the
console does not confirm is INVALID `readback_refused` with `trace.closed: false`, the run's
own outcome in the message, and the way out (`stop`, then `debug("trace off,<cpu>")`, and if
`stop` fails, `close` then `start`, since closing MAME closes the file). Arming replaces a
trace typed through `debug` on that cpu.

**The file and the set.** The tracer's file lands at `dest`, or as `trace-<n>.trace` in the
scratch's `snap/`, listed by `captures` as kind `trace` once its set is answered (a refused
trace's path is in its own reply); beside it, `<file>.set.jsonl` holds one
row per executed address, ascending: `addr` in the spelling of every reply, `symbol` (`NAME` or
`NAME+0x12`, as a writer's pc is named) when the cpu's table places it, and `count` under
`noloop`. The reply's `trace` gives `cpu`, both paths, `bytes`, `instructions` (the instruction
lines, plus what the loop lines say they stood for, with the parked edges below applied),
`addresses`, `unplaced` (the addresses no symbol places: those below every symbol, or all of
them on a cpu with no table), and per routine `symbol`, `addr` (its base), `addresses`,
`first`, `last` (and `instructions` under `noloop`), the first ones inline and every one
derivable from the set file. The file is read back by shape before the set is answered: an
instruction line whose pc is not as wide as the cpu's program space prints it, past its mask,
or paged, is `no_channel`, and a line of no shape the tracer prints is `unexpected_answer`,
naming its number. A cpu with no program-space row is read with no width judgement, said in
`note`.

**The parked edges.** The tracer logs a pc on arrival, before executing it. So the pc a stopped
cpu is parked on is absent from a trace armed there although the window executes it first: when
the traced cpu is the parked one and the visible one (read before the run), it is counted once
more and added to the set if absent. The pc the run ends parked on is logged although never
executed: when the survey stopped on the traced cpu and the file's last line is that pc, it is
counted once less, and leaves the set unless it also ran earlier (condensed, unless it occurs
elsewhere in the file). `note` says which applied, or that a parked cpu was not visible and its
pc not read. A cpu the run did not stop on has no end edge: its last line is the last
instruction it began, which a core that yields mid-instruction (MAME's 68000 does) finishes only
after the window; `note` says so, and that line is counted as it stands. Its twin at the start:
on such a core, a cpu the last stop did not park may be inside an instruction when the window
begins, which it resumes with no hook, so it is finished in the window, unlogged, and missing
from the set and from `noloop`'s counts unless the window reached it again; `note` says that too.

**Condensing, and `noloop`.** By default the tracer keeps the last 64 pcs it logged and skips a pc
already twice among them, writing `(loops for N instructions)` when the run leaves the loop. The SET
survives that exactly, because a pc is logged before it is ever skipped, with one exception: the
history starts as zeros, so address 0 among the first 63 logged instructions is skipped as a loop.
The counts do not survive: `instructions` falls short by a loop still pending when the tracer
closes, since that line is never written, so it is exact only under `noloop`, and then but for the
first instruction of a cpu the stop did not park and the last of one the run did not stop on.
`noloop=True` writes every instruction, so every row carries its `count`, with the same exception,
at a larger file.

**What the tracer cannot see**: a cpu the debugger ignores (`debug("ignore <cpu>")`), a cpu parked
in its own wait (a `stop` or `hlt` waiting for an interrupt), and a timeslice that runs with a save
or a load pending: MAME's source calls no instruction hook for any of them. Its interrupt hook is
another matter, and an ignored cpu's trace, live, held only `(interrupted at ...)` lines. So a
trace with no instruction line, empty or not, is INVALID `readback_refused`, naming both causes it
cannot tell apart (the cpu executed nothing; the tracer recorded nothing) and saying so when
`cpu_info` lists the cpu as ignored.

**The refusals.** Before anything is armed: `run_for`'s own judgement of the bound, an existing
`dest` or an existing `<dest>.set.jsonl` beside it, no cpu named while `cpulist` marks none visible
(`unexpected_answer`), a cpu with no disassembler (`no_channel`: the tracer disassembles every
line), a scratch path the console would cut (`host_failed`), and a run by frames the board cannot
route. MAME failing to open the file is `host_failed`. A close the session broke under is
`session_broken` with `trace.closed` unavailable, and a session error during the run answers as any
tool's would, with `trace` beside it. An INVALID run keeps its own code and carries `trace`
(`path`, `bytes`, `closed`), with no set file. The asked work is capped, by frames and by
milliseconds, with a pair of its own under `noloop` (the description names them): each cap is the work
at which the heaviest window measured on any board fills a gibibyte, a bound taken from bytes
because bytes do not depend on the host; a window heavier than every one measured can write more
than a gibibyte within the caps. A longer window is consecutive calls, their sets unioned.

**`step(count, mode, cpu)`** steps `into` through the stub or `over` through the console's `over`,
each step confirmed on the program counter because the console answers while the machine
still runs to the return, and an `over` still moving at its bound is interrupted and answers
INVALID with `instructions_completed`, without saying whether the call would have returned. A named `cpu`
is shown first, and `others` says what the rest did (the start of this section); a stop that
lands on another cpu (its breakpoint or watch fired meanwhile) ends the steps there, named, with a
`note`, and a run cut there reports no `cycles`, since that counter is each cpu's own.

**Every stop comes back as ONE survey**, because the stop is where the round trips are worth
saving: `how` it stopped, `cpu` (the one it stopped on, whose `pc`, `regs` and listing these
are), `pc`, `frame`, `regs`, the `dasm` at the pc (a handful of MAME's own
lines), `watches` and `watch_hit`, and the `errorlog` lines the driver logged since the
previous stop (the count whole, the newest few shown). The park at the debugger right after
`start` is stop 1, and every stop reply carries its number as `stop_seq`, the spelling
`status`'s `last_stop` and `stopped_on_its_own` use, so a caller counting stops can cross-check
against the machine with the reply it already holds.

- `how` names what stopped it: a registerpoint as ``registerpoint '<ref>'``, and a row typed
  through `debug`, in any family, by its index as the debugger's list spells it
  (hex), with the `bpclear`/`wpclear`/`rpclear` that removes it named at the end, its index
  spelled `0x<hex>` there because the console evaluates that argument as an expression and a
  bare `D0` or `A` names a register on the cpu that has one. A breakpoint
  this server armed names a stop only on its own cpu: two cpus run two programs, so a stop of
  `:subcpu` at an address a `:maincpu` row holds is not that row's.
- `errorlog` carries `lines_total` (every line since the last stop), the newest of those lines
  and `truncated`, in `log`'s words. The
  field is spelled `errorlog`, and a caller reading `reply["log"]` off a survey finds nothing, in
  silence.
- `watches` evaluates every declared watch, when there is any: `state` is where it is PLACED, as
  `watch_list` places it, and `reading` what was read (`available: true`, `value`, `raw_hex`; an
  expr watch's `value` with `hex`, `available: false` with `why`, or `bus` with `last_wrote` for a
  write-only register).
- `watch_hit` rides when a change watch stopped it, naming who wrote the byte; `regpoint_hit`
  when a registerpoint of this server did (`ref`, `condition`, `index`, `cpu`, `pc`, and a `note` that
  it is STILL ARMED and fires again one instruction on while its condition holds).

**The RUNNING guest is a contract.** `resume()` lets the machine run and comes back at once;
`resume(seconds=N)` waits that long for a stop and, if none comes, LEAVES IT RUNNING (unlike
`run_to`, which interrupts at its bound). While it runs, every reader of the machine refuses
with an INVALID reply that names `last_stop` (where it was last seen, how, and how long ago)
and `answers_while_running`: `status`, `log`, `log_wait`, `snapshot` (the console's `snap`
answers while it runs), `breakpoint_at` and `breakpoint_clear` (the console takes a `bp` while
running and it FIRES, so nothing is queued and the reply says `while_running`: whether the
machine was running when the call ARRIVED, read once at its entry, so a stop the call's own
round trips let through, a condition it armed firing an instruction later, is the next
contact's `last_stop`; every declaring tool's `while_running` means the same),
`breakpoint_list` (dated `as_of` the last stop), the `regpoint_*` tools on the same terms (the
console takes an `rpset` while running and it fires), the `watch_*` tools likewise (the console takes a `wp` while running and it fires; the list is dated `as_of`),
`symbols_find`, `machine_map`, `captures` and `state_list` (a table, a cache, a list of
files and a directory: nothing in them is read off the machine), `cpu_info` (the console's
listings, with no pc read), `gfx_load`, `palette_log` and `gfx_film` (its arming excepted),
`registers(from_last_stop=True)` (the last
stop's registers, marked `superseded`), `scan_clear` (the server's own scan, no machine read),
`throttle`, `close`, and `stop`, which interrupts the
machine where it is and surveys the stop. A stop the machine reaches on its own, at a breakpoint while
nobody waited, is recorded by the first tool that finds it, whose reply says
`stopped_on_its_own`. The refusal is a decision and not a limit of the stub: the stub serves
`m` and `qRcmd` to a running machine too, but a value read off a moving machine is a sample
of no state, and the stop packet the stub sends on its own can land in front of the read's
answer. A run the console owns typed through `debug` (the `g` family, `step N`, `over`,
`out`, `next`) marks the session RUNNING too; the stub sends no stop packet for such a run, so its
stop is proved on the frame counter by `stop`, by the first contact after a breakpoint the
console's run reached, and by the waits of `perform` and `drive`. **A `run_for` or a `step
over` that BAILS OUT marks it the same way**, because each of those hands the machine back
under a console-started run it could not see end: the readers refuse until the counter proves
the stop, which costs one `stop` when the machine was in fact at rest and saves a value
sampled off a moving one when it was not. A `no_progress` by frames is the counter itself not
moving, so there nothing but `stop`'s interrupt proves rest. A `gvblank` or an `over` whose answer
or landing the console REFUSED counts as a bail-out too: the command may have been taken, so
the reply is `not_settled`, says what went out and names `stop`, and past it the way out if
`stop` fails as well, `close` then `start`. One that the console did not answer IN TIME is not a
bail-out: it breaks the session, as the next paragraph says. The reason it
fails that way round is the stub: it answers `?` with a stop whether the machine runs or
not and serves packets to a running machine, so no query proves rest and "it may be RUNNING"
is the only honest word. `run_to` started its run with the stub's own `c`, so when its
interrupt at the bound is NOT ANSWERED the reply is `not_settled` as well, with
`target_disarmed` saying whether the temporary breakpoint's removal was confirmed and no
`how`, because no stop was read; the session stays RUNNING and `stop` waits for the packet
that run still owes. When that packet lands while the target is being removed, the machine
did stop: the run is the ordinary TIMEOUT with its survey, `how` reads "interrupt at the
bound, answered late", and `target_disarmed` still says whether the removal was confirmed.
A removal the stub REFUSES after the run reached its stop is an answer, not a break: the stop
is still the measurement, so the reply is the ordinary one with `target_disarmed: false` and a
`note` naming the row that may still be armed and the `debug("bpclear 0x<row>")` that removes
it (`breakpoint_clear` clears declarations, and the target was never one). Any other failure
of the removal breaks the session.
A `step` into whose stop does not arrive in time is `not_settled` for
the same reason, with `mode` and `instructions_completed`, and so is a `stop` whose own interrupt is not
answered in time: the machine stays marked RUNNING, nothing counts the attempts, and the
caller decides when to give up, with `close` then `start` named beside `stop`.

**A BROKEN session says so until it is closed: `session_broken` LATCHES until `close`.** When
a tool reads something that is not a stop where one was due, cannot survey a stop it did
read, or the connection fails under it, the two ends no longer agree where a packet starts,
and the stub honours an interrupt only BETWEEN packets: not even `stop` can be believed from
there. Any session error no tool answered on its own latches where it surfaces, in the one
wrapper every tool passes; the stub's own `no` is the exception, because it keeps the channel
paired: an `E` reply is `readback_refused`, an empty packet (a capability this build lacks)
`no_channel`, and neither latches. A MAME that died under the session answers
`session_broken` with its `exit_code` from every tool, and `close` is the step it names first,
since it reads the process's last words before the scratch is deleted. **A request the stub did not answer in time breaks it
too**, whichever tool sent it (a `gvblank`, a `step` over, a read): nothing in the protocol
numbers a reply, so the answer it is still owed would be read as the NEXT request's, and no
reply can be paired with its request again. The client sends nothing more on such a session.
A wait for a STOP is not a request and keeps its own `not_settled`, because a stop packet
says what it is. The reply of the call it broke under, whichever tool that was, is
`session_broken` and names the way out itself,
and from then on every
tool but `status` and `close` answers `session_broken` too, quoting what broke it and naming
the way out (`close`, then `start`); it never describes the machine as running, which is one
of the things such a channel can no longer establish, so the `session` block reads
`running: false` beside `broken`, the reason. A step that breaks the session inside a
`perform` or a `drive` carries its `session_broken` in the step's own reply, under the
sequence's `step_failed`. `status` carries the reason as `broken` (absent on a healthy session)
and asks the machine nothing; `close` skips the drain, the speed read and the `quit`, which
have no channel to believe, and kills the process, so nothing is written to a `state_dir`.
A restart costs seconds, and a wrong value costs the measurement.

**Flying to a late scene: `start(throttle_from_frame=N)`.** A shared session opens at real
speed from frame zero, and reaching a late attract screen at real speed costs the whole trip
in wall-clock with nothing to watch. MAME's debugger console has NO throttle command (the
whole command table was read, and `throttle` answers "unknown command"), and the stub speaks
nothing but the debugger; what CAN switch the throttle is Lua, and the one Lua the launch can
run is the autoboot script. So `start` writes a boot harness into the scratch, adds
`-nothrottle` so the trip is fast, and the harness lifts the throttle on arrival at the
frame: many times the board's rate until the target, the board's own rate from there. It
logs `MAME_MCP throttled from frame N` through `logerror`, so `log_wait` proves the arrival.
A caller's own `boot_lua` still runs, chained after it. It is decided at launch, at a FRAME;
the live switch, at a place or after the start, is `throttle`, through the Lua channel.

**And the arrival is where a real-speed measurement begins.** `close` reports
`average_speed` over the last run window, which opens at `resume`; a fly-then-play run
started at frame zero would blend the fast ramp with the real-speed play. Waiting on the
throttle mark (`log_wait "MAME_MCP throttled from frame"` on the emulator channel) both
proves the fly is done AND resets the speed window to that instant, so `close`'s
`average_speed` is the real-speed number alone: the recipe for "does the host hold real
speed at a late frame" is `start(throttle_from_frame=N)`, `resume`, `log_wait` the mark,
watch, `close`, read `average_speed` (near 100% when the host keeps up, below it when it
falls behind).

## Reading and writing

Every reader takes a `ref`, by symbol or `0x` address. `read_memory` answers at the address the
running board uses, with a ceiling in bytes above which it names `memdump`. On a board
relocated by `bases`, `disassemble` resolves every DIRECT memory operand of its listing
(`word ptr [0C014h]`, the map's offset and not an address) to the `linear` address
`read_memory` takes under each class base, with the symbol it lands in, because a raw offset
read as an address answers a plausible wrong byte with no error.

**A range past the end of a cpu's program space is refused, by one judge.** `read_memory`,
`write`, `find` and `memdump` refuse a range whose last byte lies past the address mask `start`
read for the program space of the cpu they reach (`bad_argument`, naming the last byte and the
mask): the stub masks an address, so a byte past the space would answer the space's first bytes
again, a plausible value for a place that does not exist, and `write` would land there. With no
mask known, the console judges the range.

**`disassemble` classes every line of its listing, and says it read the class off the
mnemonic.** `flow` tells a call (worth stepping over) from a branch or a return (the flow leaves)
and from a line that falls through, which is what following an unfamiliar binary by eye needs.
MAME computes the same distinction and no channel hands it on, so the class comes from a table
per cpu `type` (the shortname `machine_map` records), and `flow_source`
says `mnemonic_table:<type>` on every reply so it is never mistaken for MAME's own assertion.
Why the tables and what each mirrors is `mame_flow.py`'s docstring; why the mnemonic comes off a
second listing without opcode bytes is `mame_read.flows`'. A word a table does not list is
`unknown`, never `sequential`, and a type with no table borrows none: every line `unknown`, one
`note`, no second call.

`find` names the `span` it
examined and where it came from (a class's symbols' [min, max], which is not the segment, or
the exact range asked), so a zero says over which bytes; `find(symbol_class="DATA", data_hex=...)`
searches within a symbol class instead of a hand-counted range, which is how a one-byte
pattern skips the CODE where its opcode also lives: a byte there is a character and an opcode
at once. There is no whole-address-space sweep, because the space's extent is not something
the symbol table says, so a call with neither a `symbol_class` nor a range is refused naming
both.

**A value scan finds a variable no map names, by how it moves.** `scan_start(ref, length,
cell_bytes, cpu)` takes every cell of the range as a candidate, where `cell_bytes` is the cell
size, 1, 2 or 4, decoded in the scan's cpu's order, the length counted in bytes whatever the
cell (a whole number of cells) up to the ceiling its
description states and an odd start allowed; the space is the cpu's program space only (no
`space` argument: an io port is never scanned);
`scan_filter(operator, value)` keeps the cells whose value satisfies `=`, `!`, `>`, `>=`, `<`
or `<=` (unsigned) against `value`, or, with none, against what each cell held when
`scan_start` opened the scan, so a cell changed once keeps passing `!` and one written back to
its opening value stops, as in scry-dosbox-x (whose `iterations` is null for a scan its server did
not open, which a scan here cannot be); `scan_clear` ends it. Each read is the console's `save`
from the first survivor to the last, which at `scan_start` is the whole range (a cell outside
that span can no longer change the answer), compared in Python: it reads through handlers, where
MAME's own cheat engine sees only direct RAM, with the debugger's side effects disabled, and it
neither steps nor writes, so a scan moves nothing and alters nothing. Every filter answers
`operator`, `value`, `iterations` (filters since `scan_start`), `closed`, `hits`
(each `addr` and its `value` now) whole up to the list ceiling, else empty with `truncated`
true, `hits_total` (the survivors, listed or not; `scan_start` answers the same key for the
range it opened), `cpu` and `space`; none left closes the scan (`hits` empty, `hits_total` 0).
One scan at a time, bound to the cpu it opened on; it outlives runs, writes, `reset` and
`state_load` (the next filter compares whatever memory holds then) and dies with `close`. A
second `scan_start` and a filter with none open are `needs_call` naming the tool that answers,
a value wider than the cell is refused against the open scan, a refused filter leaves it as it
was, no `cpu` named on a console that marks none visible is `unexpected_answer` (a scan bound to
no cpu would read whichever is visible at each filter), and both need the machine stopped;
`scan_clear` answers while it runs.

`history(limit)` is the console's
own trail. The console readers answer INVALID, never a zero, when the console said something
they were not captured answering; the captured shapes live under `tests/fixtures/console/`
with their provenance. On a RUNNING machine every reader refuses, naming `last_stop` and what
does answer.

**A write-only block reads back zeros, and `read_block` is where its values are.** A range
mapped as a handler with a share (`.w(handler).share("x")`) has no read side: `read_memory`
answers zero for every byte with no error, `symbols_find` calls it `latch`, and the words
live in the share, which MAME keeps by tag under `manager.machine.memory.shares`; a ROM no
cpu's space maps (`gfx1`) is a region under `regions` the same way. `read_block`
reads either through the Lua console: by `tag` (as MAME names it, `blitram` or `:blitram`,
the full spelling tried second because MAME's map names a share bare and a region either way)
with an `offset` into it, or by `ref`, the address whose map entry names the block, walking the
debugger's visible cpu's program space and answering `addr`, `start` and the `offset` the
address came to (an `offset` given beside a `ref` is refused rather than added). It costs
the step every console line costs, reports that cost as `lua` does, and alters nothing. A
tag the machine lacks is `unknown_ref` with `tags`, every block the machine has with its
kind; an address in no entry, or in an entry with no block (a handler that keeps its values
on the bus), is `unknown_ref` too, naming the address (`addr`) or the entry (`map_entry`); a read past the block's
`size` is `bad_argument`, because MAME answers zeros past the end in silence, and so is a
tag with whitespace, which no MAME tag has.

**What the machine IS, as opposed to what is on it: `machine_map`.** Every other reader here
answers about a value on the board; this one answers about the board. Its cpus and the spaces
each exposes, every entry of every one of those address maps with the share or region it
names, the memory shares and regions by tag and size, the screens, and the ROM files with
their crc and sha1. It is CACHED AT `start` and serves that cache: no subprocess, no read of
the machine, no step, nothing altered, and the same answer every time, which is why it is the
one tool here that declares `idempotentHint` as well as `readOnlyHint`. It answers on a
RUNNING machine for the same reason: nothing in it is a value read off one.

**It answers every section but `rom_files` unless asked.** `sections` names the ones to answer
(`cpus`, `spaces`, `address_map`, `regions`, `shares`, `screens`, `rom_files`,
`symbol_coverage`); left out, the ROM files are not answered and `omitted` names them, with
`how`. `counts` and `sources` cover the sections answered, so `symbol_coverage` below is
present, empty or not, only when it is one of them. An empty or unknown list is refused
`bad_argument` before the machine is asked.

**Two of its sources are the emulator's, because neither of those carries the whole answer,
and each SECTION says which backs it** (`sources`). MAME's `-listxml`, run once against THIS
session's binary, is the only
one with a cpu's clock, a screen's rotation and a ROM file's crc and sha1; the live machine is
the only one with the memory shares, the regions' sizes, the address map and a cpu's `type`
(MAME's shortname for the device, `m68000`, `v30`), because on the Lua channel a device's clock
reads back nil. Labelling by section is what makes a
disagreement between the two VISIBLE: where both back a field and they differ, the
`note` names both values and where each came from. The field itself carries the LIVE
one, and that is not a coin toss: the live half is read off the machine that is actually
running, while `-listxml` describes what the build says a machine of that name is. Nothing
decides which is CORRECT; what the design buys is that the disagreement is in front of you
instead of resolved in silence. A field NEITHER source backs is absent rather than null or guessed: a ROM
nobody has dumped carries no crc and no sha1 at all, a map entry that names no block
carries neither `share` nor `region`. A map entry names its block by the full tag the `shares`
and `regions` sections carry (`:maincpu`, `:videoram`), whichever spelling the driver declared
it in, so an entry and the block it names always line up. Every `spaces` row carries its own `address_mask` (MAME's
own word for it, and the space's last address), on the row and not beside the sections because
the reply can be narrowed by `cpu`, and a value has to stay with its subject.

**The live half is gathered by the boot harness, and that was measured rather than chosen.**
Both routes were run on a two-cpu board and compared: the harness this server already writes
for `-autoboot_script`, and a console evaluation at the park, the route `read_block` takes.
They produced the same bytes, and the harness cost the machine nothing while the console route
costs a single-step and moves the pc, so the harness owns the live data WHOLE. One route owns
it because a gather split between two is where two accounts of one fact quietly diverge. The
gather runs inside a `pcall` so that whatever it meets on an unfamiliar board it cannot stop
the throttle harness installing or the caller's own harness running, and a dump that does not
carry both of its sentinels is refused rather than parsed: a truncated inventory cannot be
told from a small machine.

**Which devices count as cpus is the live channel's own answer**, not the XML's: a device MAME
gives a `debug` is one that EXECUTES, which is what a cpu is in its model, and the XML half
cannot be depended on for it because a build that fails `-listxml` must still produce a
session. So the address map is the map of the machine's executing devices, and a device that
merely exposes an address space of its own is not in it, though its shares and regions are.
The `note` says that; it says the one caveat that stops a range being a fixed fact,
that a BANKED range answers for whichever bank is selected, so what is reported is the map the
machine was wired with; and it says that these sections are what the machine WAS when `start`
read them, since nothing re-reads them and an emulator that has died since leaves the session
block saying `alive: false` beside an inventory that still describes the board that ran.

`symbol_coverage` is the other half of the join, one row per symbol CLASS, and it is the one
section a THIRD source backs: the symbol table the caller handed `start`, named in `sources`
with `start`'s own word for it, `symbols`. Neither emulator source knows that section exists,
which is exactly why it has to say so out loud -- a section whose provenance is the one thing
missing cannot be told apart from an oversight, and the populated case is the bad one, because
the note explaining an EMPTY section is suppressed the moment there are rows to explain. It is
the span the
caller's own table covers, which is `find`'s span and `find`'s caveat, from the same constant,
because two tools answering two different spans for one class is worse than either answer.
`base` is unavailable, deliberately and not absent, for a class the bases do not disambiguate. Each
row names the `cpu` whose table it is, the cpu `start` was given that file for, which is all
that attributes a class to a cpu, since a linker map carries none (unavailable for a one-path table
whose cpu the console did not name); `cpu=` narrows the section to that cpu's rows as it
narrows the others. The list is present and EMPTY when the table carries no classes or there is no
table, because the absence of symbol coverage is itself the answer.

Every list section is bounded by the readers' own listing ceiling, `symbol_coverage` included,
with `counts` keeping each section's FULL number and `truncated` saying whether anything was
cut. `truncated` is a BOOLEAN here because it is a boolean on every other tool of this server,
and one spelling has to mean one shape; which section was cut needs no field of its own,
because a section shorter than its own `counts` entry is the one. `cpu=` narrows the cpus, the
spaces and the address map to one, taking the tag in either spelling as `read_block` takes a
block's;
the blocks, the screens and the ROM files are the board's and stay whole, because narrowing
those would answer that the other cpu's ROMs do not exist. A tag the machine lacks is
`unknown_ref` naming the ones it has, and no machine at all is `no_session`.

**A system the binary does not carry refuses `start`, in MAME's own words.** Each repository
ships its own narrow build, so which systems exist is that binary's answer. The question is PUT
before the boot and COLLECTED once the boot is over, so it runs inside the seconds the boot already
spends waiting for the gdbstub to listen: dead time, in which it costs nothing at all, and no
constant had to be invented to bound it. Its bound is the caller's own `seconds`, because a query
that has not answered by the time a whole arcade board has booted is broken rather than slow.
The refusal therefore arrives after the emulator was spawned, and the same guard that covers
every other raise kills it and deletes the scratch, so a start that did not start still owns
nothing. A
`-listxml` that fails for any OTHER reason leaves the start working with the sections only it
backs empty and the reason quoted in the `note`, because a debug session must not be
blocked on an inventory and a silently missing section cannot be told from a machine that has
none. `start`'s own reply carries `machine`, the counts alone: a board's whole inventory
riding on every start would be paid for by every caller, and the rows are here, free.

`write` and `set_register` READ BACK what landed (`readback`, `verified`); every later reply's
`session` block carries `altered: true`. A `write` that does not read back asks the console's
`map` why, on that failing path only: when the program space has no write side there it is
ROM, the bytes went nowhere, and the reply says `target: "rom"` with the `region` that backs
the address and its `region_offset`, from the address map `start` cached, plus a `note`. The
write, its read-back and that `map` are ONE cpu's, the one the reply names in `cpu`, and the
`map` names it (`map <addr>:<cpu>`), so on a board where two cpus back the address with a region
the region is that cpu's. None is named when the console named no cpu the write went to, when
the map was not gathered, or when more than one entry of the map holds the address; a mirror
copy is matched through its mirror bits, and a masked entry names its region without an offset.

`write(..., region=True)` puts the bytes where that explanation says they live. The address is
placed the same way, on the write's cpu, and the bytes go into the region through the console:
`saver` copies the span to a file in the scratch, the bytes are patched into it, and `loadr`
loads it back, raw, with no guest step (a Lua region write would cost one on a stopped
machine). MAME keeps a region wider than a byte in the host's byte order, so the patch is made
in the cpu's order and swapped within the region's width on the way in, and a write that
starts or ends inside a region word is widened to whole words, the rest of each written back
as `saver` found it. Neither command's word is taken for the span: `saver` says it succeeded
even when it clamped at the region's end, and `loadr` loads no more than its file holds, so
`saver`'s file must hold the whole span (`readback_refused` when it is short,
`unexpected_answer` when there is none, and nothing is loaded) and `loadr`'s sentence must name
the whole range (`unexpected_answer`). A `loadr` counts as a write from the moment it is sent.
The read-back goes through the cpu, `verified` as for any write, and the reply adds `region`
and `region_offset`, kept on a read-back that fails. A capture whose block that region backs
reads it off the bus, as this write lands, so its rows would show the table change between two
of them with nothing saying why: `captures_reading_it` names each one the write reached. What backs the address decides, not its
write side (a region entry's write side may be unmapped or a handler): refused `bad_argument`
before `saver`, naming what the console's `map` answers there, is an address no region backs
or whose offset the map cannot place, a span past the map entry's end or the region's, and a
region `start` did not inventory. A scratch path holding a character a path handed to the
console may not hold (below, *every `dest`*) is `host_failed`. A plain `write` never takes
this route on its own: on ROM it goes nowhere, and its note offers `region=True` only where
the region would take the bytes.

A `write` then re-reads every armed watch on that cpu it touched, so the next stop's `before` is
what the write left; if that re-read fails, the reply still
carries `addr`, `bytes_written`, `readback` and `verified`, because the write had already landed.
If the read BACK itself fails, the reply carries `addr` and `bytes_written` only: the bytes were
sent, and with no reading there is nothing to call verified or not. Either failure is
`readback_refused` when the stub ANSWERED (a refusal, a short read: the channel kept its
place, nothing latches and the next call is served), and `session_broken`, latched until
`close` like every other, for anything else (the connection went, the request ran out, an
answer out of place). `reset` is the soft reset, applied and read back
against the boot pc, surveyed and recorded as the stop it is (the step that applies it is
one), answering `frame_at_reset` because the frame counter does NOT restart and a later
stop's frame is a cold boot's only after subtracting it; a hard reset is refused because the
stub does not survive it. **A count or capture watch counts on across a reset or a
`stateload`**, because its tables are the host's and survive the machine being replaced, so
its totals then mix two runs of the same code: the reply names every tap that did in
`taps_across`, and each of its surveys carries `across`, the event and the frame it came
from. Nothing is zeroed behind the caller's back; `watch_clear` and declaring it again is a
fresh count.

**What comes back as a FILE.** A live session answers into the conversation, and two things
do not fit there: a frame's worth of bytes, and a driver's log. The tools below return a PATH
instead of the content and check the file they claim to have produced:

- **`memdump(ref, length, dest)`** writes memory to `dest` through the console's own `save`,
  so the bytes never cross the socket; then the file must be exactly `length` bytes and its
  first bytes must equal a protocol read of the same range, or the reply is INVALID naming
  what came out. `save` and both checks read the cpu the call names, else the visible one: a
  range past its program space is refused (Reading and writing), which also keeps out a range
  that wraps, one the console's `save` never finishes, and the protocol read goes through that
  cpu's thread of the gdbstub's thread patch. A build without the patch reads only its first
  cpu, so a dump of another cpu is refused, naming the dump it can check, rather than checked
  against the wrong memory.
- **`snapshot(dest="")`** saves the screen as it is now: into the scratch, numbered, or moved
  to `dest`. The console's `snap` treats even an absolute path as relative to the snapshot
  directory, which is why the tool snaps under its own name and moves the file. The file
  must be a COMPLETE PNG (signature and IEND trailer) or the reply is INVALID, and it carries
  its `sha256`, the hash a golden's checksums compare. A SEMANTIC frame is `run_to` the
  point where the drawer finishes, then `snapshot`: a flat PNG at the scene's start and a far
  larger, drawn one a couple of emulated seconds later.

Every `dest` is absolute, in a directory that exists, free of commas, semicolons, quotes,
whitespace and brackets (the console's command line splits, ends, quotes or refuses a line at
each, and one rule serves every tool) and of control characters (whatever reads the path back, a
terminal or a log, acts on one), and not there yet, a link that points nowhere included, all
judged before the console is touched and before the session gate, because a `dest` is a verdict
about a string and answers with no machine: a refusal that arrives after the console wrote the
file leaves a file nobody asked for. `gfx_draft`'s `dest` is held to the same rule, at two costs
chosen for one contract: its missing directory is refused rather than made, and a space is
refused although no console line carries that file. It alone may find something there already:
an earlier draft, which it replaces, the one writer here that overwrites (below). `debug`
answers above a ceiling go to a file in the scratch, with a bounded preview and the path in the
reply; the `session` envelope stays in front of the caller either way.

## The log

`log(pattern, channel, limit)` reads one channel of what MAME writes: `emulator` is
`error.log`, what `logerror` wrote, which from a live session goes NOWHERE unless `start`
passes `-log`; `process` is the process's own stdout and stderr, captured at launch, where
`osd_printf_error` and `-verbose` go (a driver's own counters, say); `all` is both, each line
tagged with its source. A chatty driver fills it fast, so the pattern and the limit are the
whole interface, and the pattern is never empty (`.` is every line, written: an empty one left
by mistake would hand back the whole log, so `log`, `log_wait` and `drive` refuse it); the reply carries the lines, and counts what matched and what it returned,
and `labels=True` counts the first word of each line. **`log_wait(pattern, channel,
seconds)`** is the waiting form: what the log already holds is answered first (`already`),
else it waits, and it is the one wait that answers while the machine RUNS. A bound that
expires is `verdict: TIMEOUT` and says how many lines arrived during it; a STOPPED machine logs
nothing, so a wait on one for a line the log does not already hold is refused at once naming
the stop, and a stop that lands during the wait ends it the same way after one last read of
the log. `channel="guest"` is refused naming the two channels an arcade board has: there is
no guest port here.

`start` and `status` report `errorlog_path` and `stdout_path`, both in the scratch: MAME's own
`error.log`, and its stdout and stderr in one file. A third file sits beside them
unreported, `debug.log` (`-debuglog`): the debugger console's own output, which the stop
survey reads for a watchpoint's writer.

## Sequences in one call

`perform(steps)` runs a non-empty LIST of the server's own operations in ONE call: every step checked
before the first runs (op, argument names against the tool's signature, a refusal of an unknown
one carrying the tool's names as `takes`, the values the tools
refuse on their own, a wrong type, a missing argument), every refusal listed so a batch is
fixed once, stopped at the first INVALID with the steps that ran as the account. Each step's
`cpu` is judged against the machine's cpus before the first step runs too, once the rest of
the list is sound, so a cpu the machine lacks refuses the whole list (`unknown_ref`, with `cpus`) and never a step after others moved
the machine. Each step's refs are read by the address rule then as well, wherever the table is
known before the list runs (the step names its cpu, or no earlier step can move the visible one),
so bare hex naming no symbol refuses the whole list the same way (`unknown_ref`, without `cpus`).
A pointer's base is read by the rule whether `by` is `pointer` or `auto`; a name an earlier step
declares `by="symbol"` on the same cpu, and a trigger name the capture on the step's block is
held on, are read as that name; a ref past that point is read when its step runs. Each entry
of `ran` names the `cpu` its reply names, in a brief as well. A list
that alternates cpus does not leave the visible cpu moved: a stop inside it moves the visible
cpu as MAME does, and at its end, failed or not, the list puts back the cpu it keeps through
the stub's `Hc`, which runs nothing. That cpu is the one visible before the first step, or the
one the last `focus` step read back (a `debug` line that shows or ignores cpus counts as one),
so a stop after a `focus` is undone too. Like `focus`, the put-back holds while the machine is
stopped: a release makes the cpu it last stopped on visible again. The reply's `visible_cpu`
is the tag visible after the list, as `debug`'s is, and `visible_cpu_kept` says how: `before`,
`asked`,
`moved_to`, `after` and `restored` (read back), and `why` when a put-back was due and not made (the list ended running, or a
build without the thread patch, which cannot show a cpu without running). A board of one cpu
reads nothing for it and carries neither. A `resume`
is followed only by running-ok ops until the next console op, before which the sequence
waits for the stop, bounded by `settle_seconds`: a wait that ran out ends the list `TIMEOUT`,
the steps after it unsent. A goldens run is one call: a control declared once,
then `run_to` each marker (or `run_for` by `frames`) and `snapshot`. What only its step can
judge still refuses there, with `failed_at` and `ran` as the honest account: a symbol against
the table, a file an earlier step writes, and anything that needs the machine. Raw console
commands are deliberately not steps.

**`summaries=True` is how a long list stays one call, and the program does the counting.**
Each step's account in `ran` becomes a COMPACT ROW, keeping whole the step that matters: the
last of a completed list, the one that left the machine running when a console step could not
follow it, and a failing step under `failed`. A compact row is the step's `step` (its index in
the list), `op` and `cpu`, and a `reply` of `summary` and `status`; a stop keeps `how`, `pc`,
`frame`, `stop_seq`, its `watch_hit` without the `writes` list, and its `regpoint_hit`; any step
keeps the `stopped_on_its_own` its contact found. The
rule is the stop without its lists (`regs`, `dasm`, `errorlog`, `watches`, `writes`), spelled
as the full reply spells them. `ran` shows the FIRST rows, up to the same ceiling that cuts a
capture's `first_rows`, then the kept step, with `steps_total` and `truncated`; every compact
row is in `ran_path` and every full reply in `replies_path`, JSON Lines in the scratch (one
step a line, `step` first), numbered per call and kept until `close`; the failing step and the
stop the tail waited for are whole in the reply and in neither file. `stops` is the machine's
count of the stops the session numbered during the call, read off its own counter before and
after, or up to the newest stop a reply carries when that is newer (a session buried mid-list
clears the counter): `stop_seq_first` and `stop_seq_last` (unavailable when none was numbered),
`surveyed` (the ones
a reply here carries, a step's own stop, a `stopped_on_its_own` a step's contact found, the
failing step's and the tail's), `by_how` (a count per `how`, the writer taken off so one watch
is one key) and `unaccounted`, the stops numbered in that range that no reply here surveyed (a
single step a refusing reader took, or a stop a console command released the machine to). It
is reported, never refused. WHY: a series of captures a frame apart is a `run_for` and a
`snapshot` per capture, each `run_for` carrying a stop survey, and the whole reply crossed
what the client shows; cut to a summary line it lost every stop's hit, and a count assembled
from what was left came out wrong and clean. A count is read from `stops`, and a table longer
than the reply shows is read from `ran_path`.

**`until_frame=F` makes a window of frames one call whose length the program finds.** The list
is a cycle, repeated until a stop reply carries a `frame` at or past F, and the reply adds
`until_frame` and `frame_reached`. The window is the frames BEFORE F: the call ends right after
the first step whose stop reads F, even in the middle of the list, so a stop a watch makes later
in frame F is not in it. `step` and `failed_at` count the steps run; the list position is that
number modulo the list's length. It needs `summaries=True` and a `run_for` step (`frames: 1`
walks the window), because `run_for` carries on past a watch's stop at its next step where
`run_to` and `step` end at the first; and a frame the machine already stands at or past is
refused, since the first step would end the window with a count of one. A stop that carries no
frame ends the list INVALID `unexpected_answer`, since nothing then says whether the window is
over, and a list that never reaches F ends at a bound in steps or in the ceiling every wait here
takes, `verdict: TIMEOUT` with the whole account (reaching F is `TARGET`); the wait reports its
progress. WHY: every stop a watch makes inside the
window takes a step without moving the frame, so the steps a window needs are its frames plus
its stops, and the stops are the thing being measured. A list sized by guessing ends short of
the window with a smaller count that looks clean.

`drive` is look-act-verify with the channel an arcade board has: the emulator log is marked
first, the `act` (a list in `perform`'s vocabulary) runs as `perform` runs it, an `expect` is
read off the log from the mark (waited for only while the machine runs, bounded by
`seconds`), and `looked.emulator` is what landed since it, matching `pattern` and cut to the
last `limit`, in `log`'s words (`lines`, `lines_total`, `truncated`). An empty `expect` is none;
`seconds` with no `expect` is refused rather than ignored. An expectation not met on a stopped
machine is `wait_stopped` (no line can come), as `log_wait` says it; on a running one the
verify answers `verdict: TIMEOUT` at its bound (`TARGET` when the line came), and an act that
ran out its own wait verifies nothing (`verify.available: false`). Every refusal before
anything ran has `drive`'s own shape. The two verify fields
mean different things, and each has its own word: `checked` is whether an `expect` was given
and a check ran at all, `seen` whether the expected line arrived. `summaries` is
`perform`'s, applied to the act's `ran` by the same rule, with the same count and the same
files under `act`.

## From an investigation to a bench

Every session is recorded from the `start` that succeeds, and cleared by the next one; `close`
keeps it. `perform_export(path)` writes it as `perform`'s own document, and the runner plays it
back with no model, from this repository:

```sh
uv run python -m scry_core.replay <document> [--binary PATH] [--rompath DIR] [--transcript PATH]
```

It exits 0 when every step held, 1 when a step diverged or failed, 2 on a usage error, and 3 when
nothing was demonstrated (a document that is not one, a start the server refused, a saved state
it loads and the server lacks, a server that did not start); the whole transcript goes to
`tmp/replays/<document stem>/transcript.md`.

What the export keeps is what moved the machine and what was checked:

| A call of | Becomes |
|---|---|
| a tool that changes the machine or what the next call acts on (`write`, `run_to`, `run_for`, `step`, `trace`, `input`, `record`, `audio_record`, `series_capture`, `focus`, `state_load`, a declaration...) | a step; one that left the machine at a new stop holds to its `pc` and `frame` |
| `read_memory` | a check of `hex` |
| `read_block` | a check of `hex`, and of the `pc` and `frame` of the step it reads by |
| `registers` | a check of `regs` |
| `screen_signature` | a check of `signature`, and of the `pc` and `frame` of the step it reads by |
| `golden_check` | a check of `matched`, `differing`, `missing` and `extra` |
| a `resume` (a release), a `resume(seconds=)` that came back stopped, a call whose wall-clock bound ended it (`TIMEOUT`) | the end of the document, named in the reply's `cut`: whatever ends such a run, the clock or a breakpoint, stops the cpu at a place inside its frame that no replayed advance reaches (a count of frames ends at the frame's edge, a `run_to` at the first arrival), and every stop after it inherits the shift |
| any other read, `throttle`, `snapshot`, `memdump`, `comment_*`, the picture and `gfx_*` tools, the scan | dropped, named in the reply with why; one that stepped the guest to read it is kept as a step |
| a call the server refused | dropped, named; one that moved the machine first ends the document |
| a call that ended with no reply, or around which the machine could not be read | the end of the document: the reply's `cut` names it and why |

`perform` and `drive` are recorded as their steps. A step's check is `"recorded": {<field>:
<value>}` inside it, and `perform` holds the step's own reply to it: a mismatch is INVALID
`diverged` at that step, with `field`, `recorded` and `got`, the list stopping there. Under
`until_frame` every lap holds each step to its `recorded` again, so a stop recorded on the first
lap diverges on the second: an exported document carries no `until_frame`. The
document's `needs.states` lists the saved states it loads and does not save, which the runner
checks against `state_list` before it plays anything. A recording holds at most 5000 calls, past
which the export says it is cut there.

What a replay cannot hold to, it says at the step (`diverged`) rather than passing over it. So a
session meant for a bench advances by `run_for`, `run_to` and `step`, which stop where the
machine does on every run, and leaves `resume` for the end. The document carries the `start`'s arguments as given, host paths included (`--binary`
and `--rompath` replace the emulator's and the sets'), and the start re-arms the declarations it
finds stored, as any start does; a file a step wrote by name (`dest`, a saved state) is there on
the next replay and the step refuses it, so a session meant for a bench leaves `dest` empty and
keeps its states in a directory of its own. A `golden_check` over files dropped calls wrote is
dropped too: the replay would not write them, so it would hold to the session's own.

## Input and the screen

The typed wrappers over the Lua channel are scripts this server composed, each knowing what
it does, so none of them marks the session altered for a read, and each proves its effect
through `error.log`: their scripts write marks with `logerror`, which is flushed as it is
written, where a `print` from a frame notifier sits in the stdio buffer until the next
prompt. They are QUEUED and evaluated by the advance the wrapper itself makes, and the
notifier a chunk registers runs in the same frame update that evaluated it. Every wrapper
but `throttle` needs the machine stopped, because it is the wrapper's own run that evaluates
the script; `throttle` also answers on a running machine, where the next frame evaluates
it. A run another stop cuts short leaves a wrapper's notifier armed (the field held, the
recording open), and the reply SAYS so with the frame the notifier acts on. A stop before that
frame update, with the chunk evaluated at the stop, leaves a recording not yet begun, and the
reply says so too (`began: false`, `frame_begin_planned`): the notifier begins it on the next frame
the machine reaches, unless the next call of the same tool releases it first. That frame is
the counter's at the evaluation, or the one after it inside a vblank, since MAME calls the
notifiers as a vblank begins and moves the counter as it ends; the chunk logs which (a driver
that updates its screen after the vblank is called at the end, which Lua cannot see, so a
chunk evaluated inside that vblank is predicted one frame late). A chunk that answered and
logged no mark at all, not even that line, is refused as lost marks. A recording whose run did
not settle is that run's own refusal (`not_settled`) with the file's `path`, its message saying
the notifier may still be armed, never the recording's fields under a refusal: the machine may
still be running, so nothing read off it is a state of the recording. A recording refused once
its run began has moved the machine by that run, and says so in the run refusals' own
`frame_before` and `frame_after`. Marks carry the
call's own number so a stale one is never attributed to a later call, and a new script of
the same family releases the previous one's effect first:

- **`input(port, field, value, frames)`** presses a field by NAME (`:P1`, `Coin 1`), the shape
  MAME's own API has and the right one for a board with no keyboard; the script holds it for
  `frames` frames of the counter and releases it, and the port is READ BACK at the release,
  so `active` is computed from the port against the field's own default, never assumed. A
  game that detects an EDGE needs a release between two presses, so a double press is two
  calls. The press is set on the field from inside the machine, so it takes no window, no
  focus and no host event, and the reply's `route` says so: `ioport`. Lines already in the console's pipe (a `throttle` asked while stopped leaves one) are
  stepped off BEFORE the script is sent, so the frames asked for are spent on this input and
  not on somebody else's line. A run whose frames the console had not read the line by leaves
  the script `pending`, and the note counts the frames that DID pass rather than asserting
  none did. A run that did not settle is that run's own refusal (`not_settled`), as a
  recording's is, saying what the script did and that it may still hold or release the field,
  never the field's half under it.
- **`record(frames, dest)`** writes an AVI of exactly `frames` frames, begun and ended by the
  frame counter, and the file is checked by its own header (`avih` declares the count)
  before the path is given. It takes two frames or more: the frame notifier begins the
  recording on its first call and can end it no earlier than the next, so one frame asked
  for would be two recorded and is refused instead. A `seconds` that would hold the server's
  lock past its ceiling is refused too.
- **`audio_record(frames, dest)`** writes the sound of exactly `frames` frames as a WAV: the
  mixer's own output (`sound:start_recording`, the Lua side of `-wavwrite`), the speakers' input
  mix before any effect, the same samples MAME hands an AVI. It is begun and ended on the frame
  notifier as `record`'s is, ending one notifier call later than `record`'s script so that the
  span between its marks is `frames` frame periods of emulated time, which `emulated_s`
  measures. The mixer writes in whole updates of a fiftieth of an emulated second, so the sound
  begins up to one update before the first frame and ends up to one before the last, and the
  samples are the span at the rate within one update (a recording that holds the session's first
  update carries one sample more). The file is checked before its path is given: a header that
  agrees with the length on disk (MAME's writer checks none of its writes and writes both sizes
  only when it closes the file, so a file still open reads 0 in both), the counter moved by
  exactly `frames`, the span `frames` periods, and that span's samples. Zero samples, a machine
  with no speaker (MAME writes a WAV with no channel) and a mixer that refused to begin are
  refused; an ini naming `wavwrite` is already recording the session, and the script never
  stops a recording it did not begin: the mixer has one file, so when a `lua` call stops the
  tool's file and begins another, the script finds its own file's sizes already written and
  leaves the other recording, and the cut recording is refused once it lacks more than an
  update's samples. Silence is reported, `sample_min` equal to `sample_max`,
  never refused: it is a fact about the game, and a constant level is silence to the ear
  whether it is zero or not. A recording open while the machine stands at the debugger gains
  nothing for that time, since no mixer update runs there. It takes two frames or more, the
  fewest that always hold an update on a screen under 100 Hz.
- **`throttle(on)`** switches real speed at a PLACE: pending on a stopped machine (with the
  mark to `log_wait` for), applied and read back on a running one; a running machine that stops
  before its next frame leaves it pending the same way, and one whose bound runs out is
  refused and still recorded. The mark's number is the
  session's console sequence, shared with every call that sends the console a line (the tools
  that carry the console's trio, above), so the second throttle
  of a session need not be `#2`; and `log_wait` takes a regex, so a mark is matched with its digits
  closed (`MAME_MCP_THROTTLE#1(?![0-9])`), the same way the server matches its own, or `#1`
  also matches `#10`.
- **`screen_signature(crop)`** answers "did the image change?" with one string and no PNG:
  the whole screen, or `crop` of it, by the definition in *Media files* below.

`snapshot` and `captures` are the screen's other half: the still as a complete, hashed PNG,
and every file `record`, `audio_record`, `trace`, `snapshot` and the graphics tools checked and
handed back this session, re-read, answering while the machine runs (a recording its call
answered still open or not begun is finished, or released, by a later run, which reads no file,
so it is not listed). A still taken at a stop here can land a frame away from an autoboot golden
at the same count: `debugger` in `start` and `status` (The session).

### Graphics

`palette`, `screen_view`, `gfx_view` and `gfx_locate` look at what the machine draws and what it
draws it from, on stock MAME, through the Lua console; `gfx_load`, `gfx_blits`,
`gfx_blit_source` and `palette_log` read it through what a project states about its board.
They answer the question a colour snapshot cannot, which is WHICH PEN: the wrong pixel is pen N, pen N is used
here and nowhere else, these bytes under this format are the tile the screen shows. They show
the bytes under a format the caller states and the pens the screen holds, never what a
driver's `GFXDECODE` believes the graphics are, which is what is wanted when the driver is the
thing being fixed. Tilemaps and MAME's own `gfx_element`s are out of reach on purpose: stock
Lua binds neither, and a binding is a fork. Each is one Lua evaluation of a chunk this server
composed: one step, the state AFTER the instruction at the stop's pc, the session not altered.
They are operations of `perform` too, where each step's `image` is named by path. One more,
`gfx_film`, works differently: it keeps the frames in which a write happened, inside MAME, as
the machine runs (below).

**The picture.** Each answers with ONE PNG, written to the scratch (or to `dest`: `close`
deletes the scratch, so a picture meant to outlive the session takes one), named in
the reply's `image` (`path`, `sha256`, `bytes`, `width`, `height`, `scale`, `indexed`,
`inline`) and attached after the JSON when the model can see it as it is. Past a side of
1568 px, or past 1568 tiles of 28 px, the API resamples a picture, and a resampled picture of
pixel art is a plausible wrong one: pens blend, one-pixel lines vanish. So such a picture is
written and not attached, `not_inlined` says why, and the caller asks for a `crop` or a smaller
`scale`. Inside the ceiling a small picture is enlarged by an integer factor, nearest
neighbour, so each pixel is a square of one pen (`scale=0`, the default, is the largest factor
up to 8 that fits). The attachment is the file, hashed again at the MCP boundary. An indexed
PNG keeps each pixel's index in the file, so the file is the data and a golden can compare
pens: the screen is indexed when its palette has at most 256 entries (the PNG index IS the
pen), a tile sheet always (the index is the pixel value). A picture that is a VIEW of the data
(a margin dimmed, a point ringed, boxes outlined) is RGB, since an indexed file cannot dim a pen
without a second palette entry a 256-pen board does not have; where the data matters beside it,
the reply names it too (`gfx_blit_source`'s `data`).

**`palette`** reads a palette device's pens as MAME holds them, `manager.machine.palettes`: on
the boards this server drives the colour RAM is a write-only RAMDAC or an array inside the
driver, and the device is the one honest route. The swatch writes each row's first pen in hex
at its left, because a pen counted across a row is a pen named wrong. `truncated` means what it
means on every tool here, that the answer was cut: only a read to the end (`count` 0) past the
cap is; a `count` the caller chose cut nothing, however many pens come after it.

**`screen_view`** recovers the index of every pixel. Stock `screen:pixels()` resolves an
indexed screen to colours through the palette, so ONE chunk saves every pen, sets pen `i` to
the colour `i`, reads the screen, puts every pen back, reads them back and reads the screen
again, into one file. No guest instruction runs inside a chunk, so nothing the game does can
see the encoded pens, and the encoding and its read run under `pcall`, so the pens go back even
when that read raises. Four checks make the reply INVALID rather than a picture: an index past
the palette's entries; an index whose saved pen is not the colour the screen showed (a palette
adjusted by contrast or gamma draws other colours than its pens); a pen that did not read back
as it was saved; a screen that changed across the restore. A pen that did not come back is the
one case that counts as a write, because then the machine is not as the game left it. A
palette with shadows or highlights draws indices past its entries, which the encoding cannot
name, and is refused; so is a vector or LCD screen (`screen_type`), for which MAME would hand
back a blank bitmap, and a machine with several screens. A screen drawn in direct colour names
no palette whatever palette devices the machine has: `render` shows its colours and the index
modes refuse. `frame_screen` is the screen's own counter, beside the stop's `frame`. Mode
`isolate` draws the pens asked for in ONE saturated colour, `isolate_color`, and every other pen
grey by its luminance, in a band with no black and no white: dimming the rest left a dark pen
sunk in a screen gone dark round it, and a hue over greys stands out whatever the pen's own
colour; the PNG stays indexed, its index still the pen. Mode `pixel` answers the pen and its
colour with a picture of where the point is: a crop round it (`crop`, `point_in_crop`), kept
inside the screen, in the screen's colours, the point ringed white then black just outside its
own pixel, which no ring covers. At the screen's edge the point is at the crop's edge too, so the
picture carries a grey `border` as wide as the rings reach, outside the screen, on every side.
It also answers who set the pen's colour, `set_by`, when
`palette_log` is logging the ports that set it (below).

**`gfx_view`** decodes bytes under a layout stated in MAME's own `gfx_layout` terms, the seven
fields a `GFXDECODE_ENTRY` names, in bits, with the macros drivers write them with:
`RGN_FRAC(n,d)` (`n/d` of the WHOLE block's length, whatever the offset, as `digfx.cpp`
resolves it), `STEPn(a,b)` inside a list, `+`, `-`, `*` and hex, a list as JSON or as the
driver's own braced string. So a layout transcribes by copy and paste, and formats that bit
depth plus "planar" cannot say (CPS1's planes interleaved by byte, planes a third of a region
apart, packed nibbles, a linear framebuffer) all can. Plane 0 is the pixel's most significant
bit and bits are read most significant first, as `gfx_element::decode` reads them. A region is
read whole through `region:read`, a copy of the host's memory, and put back in the block's own
byte order when its endianness is not the host's, which is what MAME's `xormask` does on the
bit address; a share is read a byte at a time in its own order, since stock Lua binds no bulk
read for one, so a share has a smaller size bound than a region, the size such a loop dumps well
inside the console's default wait, and past it is refused by its size; a `ref` reads a range of a
cpu's program space, which is a fraction of nothing, so `RGN_FRAC` is refused there. Every
reader of a block (`gfx_view`, `gfx_locate`, `gfx_sweep`) answers THE SOURCE in one shape: `kind`,
`tag`, `size`, `bytewidth`, `endianness` and `offset`, and for a `ref` the `addr` and its
`addr_cpu`; a description saying "the source" means these. No palette
is invented: `palette` names a device, whose pens from `pen_base` are read in the same chunk,
is empty for the machine's only one (`ambiguous_ref` when it has several), or is `none`, the
default, a grey ramp the reply calls not real; fewer pens than the depth needs is refused,
never padded. A list of colours is not a palette `gfx_view` takes: the pens a tile is drawn
with are the device's at the stop the caller chose, and colours known from elsewhere recolour
the indexed PNG on the caller's side by replacing its PLTE, since its index is the pixel value.

**Which instant a decode shows.** `palette`, `screen_view` and the decoders (`gfx_view`,
`gfx_locate`, `gfx_sweep`, `gfx_draft`, `gfx_blits`, `gfx_blit_source`) need the machine stopped
and refuse a running one. What each reads is the state its chunk finds one step past the stop,
more when its `evaluated_by` says so, and its `pc` says where; in a `perform` each further read
is that much later again. At a stop in the vblank handler, `screen_view` matched the framebuffer
decoded at the same stop and not the one decoded at the stop before, on a pair whose framebuffer
moved between the two; at a stop in the middle of a frame, what it shows is not established. So
the stop is chosen by the write to what the read reads: for a decode, the block and the palette
device's pens. A count watch over a pass names which tables are written and by whom, and it
counts writes, not changes, so whether a table moved is read by comparing it at two stops. A
change watch stops on the instruction after its writer, the write landed, and a `resume` with a
bound answers that stop with its `watch_hit`; it stops on a write of the value already there
too, so the read at its stop can equal the one before it. A `run_to` the writer's own pc stops
before the write, which the read's step then runs. A change or count watch whose address nothing
writes, the ROM copy of a datum, is refused (the control of a watch, under Declarations).

**`gfx_locate`** is the known-answer case that validates the decoder. A pixel of an indexed
screen is `base + value`, `base` the palette bank aligned to `2^planes`; every tile-sized window
of the patch is tried against every tile of the range under the `flips` the hardware draws, and
a match needs one bank for the window and every value equal. A window of one pen matches every
blank tile and is counted and skipped; one spanning two banks is not one bank's pens, and is
counted and left to the pen map.

A board can draw a tile's ink and paper from two banks (a 1-bit char's ink in one colour
register and its paper in another), or one value in two pens (a colour attribute beside the
pixel), and then no window is `base + value`. So when that search matched nothing, a PEN MAP is
tried, every window of two pens or more included: per window and tile, a table from each pen of
the window to the value it stands for, which has to be a function, a pen standing for two values
being no table, and has to read two values, since a tile of one value proves nothing. Each match
carries its table (`pen_map`, `[pen, value]` pairs) and no `base`: it proves the format and the
tile, never the bank, and it proves less, since a tile whose pens part the window the same way
matches too, which `ambiguous` then says. With `transparent` the left-out pixels are free, and a
1-bit tile, which compares one value, proves its shape only if the ink's pens are nowhere among
them. The reply's `pen_map` is unavailable when the first search matched, else `tried` with its
`matches`, or `tried: false` with `why` when the two searches together would pass the work
bound; when it was tried, each candidate's row adds its own `pen_map_matches`.
With one bit a pixel, few lit pixels and symmetric glyphs match more than the tile that is
drawn there (a glyph flipped is itself one pixel over), which is why a match says whether its
window was `ambiguous` and `flips` narrows to what the hardware can do. `transparent` leaves a
sprite's see-through pixels uncompared and so proves less: a match carries how many pixels it
`compared` and needs two values among them, and it is a value every candidate's pixel can hold.
Nothing is ranked, because a heuristic that looks like proof is worse than an honest list; a
person or another patch decides. With no match, `nearest` is the candidate with the smallest
share of disagreeing pixels (a count across layouts of different sizes would rank the small tile
first by construction) found within a budget of comparisons, listed, marked `is_a_match: false`,
and `complete` says whether any comparison was left undone. `count` 0 searches every tile the
block holds up to the same cap an explicit `count` has, and each candidate's row says how many
it searched beside how many there are (`tiles_searched`, `tiles_available`) and how its windows
fell (`windows` tried, `windows_uniform`, `windows_mixed_bank`, `matches`). The work is bounded before anything is compared, counted
in the pixel operations the search spends over every candidate of the call: every tile decoded,
every window gathered, and, with `transparent`, every window compared with every tile pixel by
pixel under each flip. The matches one call holds are bounded too, because a pattern repeated
across the patch and the block matches without end and tells nothing apart. The screen and the block
are read by one chunk, so they are of one instant. Each match carries its window's `shape`: its
distinct rows, its distinct columns and the pixels of its rarest pen, which with the answer's
other matches is what says whether it could have matched by chance (below, `gfx_draft`).

**The project's knowledge: `gfx_load`.** A project states its graphics once, in a `gfx.yaml` this
server reads by absolute path and holds for the session, as it holds the symbol tables: named
`formats` (a `layout` in `gfx_view`'s terms), named `assets` (a region or share, a format, a palette
device and its first pen, and whether coordinates `wrap` inside a tile), and draw `commands`. A
command is the register `block` a capture reads (`address`, `words`, `word_bytes`, `cpu`), the
`fire` write that makes a row a blit (`word` and `value`, or `address` for a trigger outside the
block, the port a game copies it to, with `value` left out when every write fires), the `asset` it
reads, its `fields` and `flags`, and its `planes`. The `fields` are ROLES the server computes with,
and no others: `dest_x`, `dest_y` and either `dest_x_end`, `dest_y_end` (inclusive) or `width`,
`height`; `dest_dir_x`, `dest_dir_y`; `source_x`, `source_y`, `source_tile`, `source_dir_x`,
`source_dir_y`; `plane`; `reads_source`. A misspelt role is refused rather than read as something
else; what a project wants shown and not interpreted goes under `flags`. A field is `parts` (each
the bits of `mask` from one `word`, low bit first, placed from bit `at` of the value), because
hardware splits a coordinate across words, plus an optional `add`, and `sign: -1` for a value stored
reversed (`add` minus the bits); a `width` or `height` the hardware fixes is a `const` instead of
parts; a one-bit role says with `asserted` which value means it holds (increasing, reads). A plane
is picked by the `plane` role's value (`when`, inside the range the role can hold, its sign
included), has a size it wraps at, an `order` (higher is drawn over), an origin on the screen
(`origin_x`, `origin_y`: an integer, or `{field, scale, add}` read from the blit's own row) and,
when it is drawn in pages, the field that names the `page`. Every entry carries `status` (`proved`:
checked against the machine by something that could have failed, which `source` names; `declared`:
transcribed, from a driver line or a datasheet; `human`: a person's choice) and a non-empty
`source`. A figure has no place in it: it would expire there. The file is judged WHOLE: the first
unknown key, missing key, wrong type, dangling name, overlapping part or mask wider than its word
refuses all of it, naming the path that holds it, and a refused load keeps the manifest loaded
before (`still_loaded`); a manifest whose `systems` lack this session's system is refused too. It is
read by a strict reader of the YAML such a file needs (comments, block mappings and sequences,
one-line flow collections, decimal and hex integers, `true`, `false`, strings plain or quoted on one
line) that refuses, with its line, anything another YAML reader could read differently: `no`, `012`,
`1e3`, `2026-09-28` and `1:20` are typed by one reader or another, so a plain scalar that looks like
any of them is refused and asks to be quoted, and anchors, tags, block scalars, tabs and a key given
twice are outside the subset. With a manifest loaded, `gfx_view`'s `layout` and each of
`gfx_locate`'s `layouts` may be a format's NAME (or a sweep candidate's id, below); a manifest whose
first line is the DRAFT marker loads like any other and says `draft: true`; an asset is used where a
source is taken, not where a format is, because it carries a source and a palette too. A board
states the ports that set its pens under `palette_ports`, whatever the protocol (a RAMDAC, a latch
or a sequence, below): the `palette` device whose pens it sets, its `index_port` and `data_port` (in
the `space` of `cpu`: `program`, the default, or `io`), the `order` its data port takes `r`, `g`,
`b` in, `component_bits` (1 to 8), `auto_increment`, `pen_base` (MAME's `set_color_base`) and
`pen_count` (a power of two up to 1024, 256 by default, at most 256 for a byte index); two on one
palette may not set the same pens. `protocol` says how the writes become pens (`palette_log`,
below): `ramdac` by default; `latch`, which needs `index_flag_mask` and takes `index_port`
optionally; `sequence`, which needs `index_port`. The two packed ones may set
`components_bit_reversed`. The section's old name, `ramdacs`, is read as `palette_ports`, and
`gfx_load`'s `note` names the new one; a file that spells both is refused.

**`gfx_blits`** answers who painted an area. It reads the capture the `draw_command` (a
draw command of the manifest, named in the reply too) describes, the
capture watch on its block whose trigger is the fire word (none: refused with the `watch_add`
call that declares it, because a manifest that armed a tap on its own would change the run
behind the caller's back; one whose install the console refused or never evaluated: refused
naming that `state` and the `watch_clear` to issue, since it records nothing and waiting would
wait for ever; captures on two cpus for a command whose `block:` names no cpu: refused naming
both in `captured_on`, rather than answered from whichever was declared first), and every row whose trigger write is the fire value is a blit. The
frame is the newest one with blits before the stop's own, which is still being drawn and is
`frame_complete: false` when asked for; a capture keeps its rows in order and drops every one
past its cap, so the frame of its last kept row may have lost some and says `rows_cut`, and a
frame past the rows kept is refused saying so. A blit's box is its destination walk, from its start to its inclusive end in its
declared direction, wrapped at its plane's size, moved onto the screen by its plane's origin
read from the same row, and cut to the visible area into rectangles, `clipped` or not
`on_screen` when the screen shows part or none of it; a blit placed nowhere (a plane value no
plane declares, a walk that covers no pixel) says `why`. The picture is the screen's colours with
each box outlined, one colour per writer pc (`legend`), drawn after the enlargement so an
outline covers as little as the scale allows; it is RGB, a picture ABOUT the data, where
`screen_view` is the data. By default the reply is a SUMMARY: `blits_in_frame`, the `legend`,
`by_plane` (each plane and page with its blits and how many are on screen) and the picture,
because a frame's every blit with every field crossed what the client takes in and arrived cut.
The blits are LISTED with an `area` (the ones whose box covers it) or with `detail=True` (all of
them), a page at a time: `listed` says which (`first`, `count`, `of`), `next_first` names the
next page while one remains, and a page is asked again with the same `frame`, since the rows of
a finished frame do not change. A listed blit carries `index` (its place in the frame, what
`gfx_blit_source` takes), `n` (its capture row), `pc` and `symbol`, `box`, `plane`, `page`,
`screen`, `on_screen`, `clipped`, `why`, and its `fields` and `flags` as read. With an `area`
the blits are in the
order drawn, and `topmost` is the last of the highest plane over every covering blit, not only
the page: covering is not painting, because
what painted a pixel also needs the source pixels, their transparency and the scale, and the
reply says so. A plane drawn in pages names each blit's page, and says that which page the
screen shows is not in the rows: a frame's rows can hold both. `not_proved` names every field
and plane the answer leaned on whose status is not `proved`, and the flags too when it lists
blits, since each listed blit carries them.

**`gfx_blit_source`** shows the rectangle ONE blit reads, picked by its `index` in the frame or
by the `pc` that fired it (refused, with the indexes, when that pc fired more than one). The
rectangle starts at the source origin (each field's `add` applied) in tile `source_tile` of the
asset's format, has the destination walk's size, and is laid out in the tile's own orientation,
the source directions saying which end the walk starts at. It is decoded through the tile's own
layout with its offsets windowed onto the rectangle, which is exact for every layout MAME's
language states, and wraps inside the tile when the asset says so; past the tile's edge
otherwise it is refused. `box` says where the rectangle sits. With no `margin` the PNG is the
data, indexed, each index the pixel value. A `margin` shows that many pixels round it, dimmed,
the rectangle ringed white just outside itself: drawn like the rectangle, the neighbouring
pixels read as part of the blit, an offset that does not exist. That picture is a view, so the
reply also names `data`, the whole window unscaled as an indexed PNG, never attached.
It is UNSCALED on purpose: a scaled blit reads another extent, and that law is the project's, so
the reply says the extent is the destination's. A blit whose `reads_source` says it read nothing
still shows where its registers point, and says that too.

**`palette_log`** answers the other half of a wrong colour: the pixel holds the right pen, and
the pen holds the wrong colour. A RAMDAC takes an index on one port and the components one after
another on the other, the index moving on by itself after the last, so which pen a data write
landed on is known only by following the device from the last index write. The log does that
inside MAME, at emulation speed, with a tap on each port and MAME's own `ramdac_device` law:
an index write sets the index and restarts the components; a data write lands on pen `pen_base
+ index`, component `order[k]`, and after the third the index moves on when the device
auto-increments. Until an index write follows the arming, a reset or a state load (both seen
through Lua's notifiers), the index is not known and such a write is counted `unsynced`, on no
pen, rather than guessed. Each write says who made it in `written_by`: `guest`, the game's instruction, or
`debugger`, made while the machine stood in the debugger (this server's `write`, a console
command, a Lua chunk), whose `pc` is where the machine stood. Telling them apart takes the
machine's time as well as the debugger's state: a stop that arrives from outside (a frame's end)
is requested before the cpu reaches the instruction it parks at, so the game's last instruction
writes at `stop` too, at a time earlier than the park. A call with `arm=True` for a palette port
(its `palette_port`, the entry's name) ARMS the log, installed when the console next reads a
line; a call without it reads it, and a read of a log nobody armed is `needs_call` naming
`arm=True`, since a read never arms; `clear` removes it, and
`close` ends it. What it keeps: for every pen, the newest write that landed on it and the
components as the log composed them, never cut, which is what answers who set a pen after any
length of run; and the ordered rows, the first ones kept and the rest counted, as a capture's
are, each data row with the colour it left. **Every row says WHEN, as a capture row does**: the
beam `line` and the emulated `time_s` of its own write (an index write, a data write, a desync),
derived by the capture's own line function on the same clock, so a palette write mid-frame is
placed on the beam and ordered against another cpu's captured traffic (a state load's `desync`
row, `desync: true` with its `why`, carries the time after the load, earlier than the rows before it); an index and a data byte
are `0x` text at the width written. Without `pen` the reply ranks the `setters`, each
writer of a pen's newest write and which pens it set, most pens first: the first ones, with
`setters_total` beside them and `setters_path` naming a JSON file that holds them all (rewritten
by each read without `pen`, removed with the log; unavailable with why when the scratch
refuses it), since a guest that uploads its palette through
an unrolled loop has a writer per pen; with `pen`, that pen whole as `pen_state`. A colour is the components
widened to 8 bits the way MAME's `palNbit` widens them.

That law is the entry's `protocol` `ramdac`. Two other drivers put a whole colour in one word,
and the entry names which (`protocol`), the words being read little-endian from the port's
address up to the end of its bus word; a big-endian bus, or an index port in the data port's bus
word, is refused by the install itself (`state` `install_failed`, the console's words in its `why`), before it touches a log already armed. **`latch`** (v30-alt's `paldat_w`): a word on
the data port with a bit of `index_flag_mask` set sets the index to its low bits, and any other
word is the colour of the indexed pen, written whole (the driver takes no mask); a write to the
optional `index_port` merges into the index under its mask (`COMBINE_DATA`), and while the index
is unknown only a write covering every index bit makes it known (one that does not is a
`desync` row, its `why` saying so). **`sequence`** (v30's `twins_pal_w`): each data write merges
into the stored word of the pen at the offset under its mask; any write to the bus word of
`index_port` sends the offset back to 0. In both, a colour write moves the index on by one when
`auto_increment`. v30's driver zeroes its offset once, as its video starts, before the first
instruction, so a `sequence` log armed where `start` parked, before the machine ever executed,
starts knowing it (`synced_at_start`); armed anywhere else it waits for a write to the reset
port, which a game may never make again. In both, the colour is
`order`'s components from bit 0 up, `component_bits` each, bit-reversed when
`components_bit_reversed` (v30's `bitswap<8>(x,7,6,5,0,1,2,3,4)`), and a pen has a colour
only once every colour bit of its word has been seen written: a write that merges into a pen
whose other bits the log never saw is counted in `partial_writes`, and the pen keeps no colour
until they are. A packed pen shows its `word`, and a packed row its `word` and `mask`, where a
byte-wide RAMDAC's shows `component` and `value`. The index wraps at `pen_count`.

`screen_view`'s `pixel` joins the two: the pen under the point, its colour now, and `set_by`,
the pen's newest logged write, dumped by the same chunk that read the screen, so the three are
one instant. `agrees` says whether the colour that write left is the pen's colour now. When it
is not, something other than a port write changed the pen since (a driver copying pens itself,
as m68k-dual's does at vblank from a snapshot taken at the page flip, a Lua `set_pen_color`, a
state load), and the reply says so and names `same_color_write`, the newest kept row that left
the pen that colour, instead of guessing. The `note` keeps every sentence that applies: a
write the debugger made and a colour it did not leave are two facts, and saying one does not
unsay the other. With no manifest, no `palette_ports` entry for that palette, no log
armed or no write to that pen yet, `set_by` is unavailable and its `why` names what is missing.

**`gfx_film`** answers "what did the screen look like in the frames where this happened", which a
breakpoint cannot follow once the thing happens hundreds of times a frame. A write tap marks the
frame (a write landing all `length` bytes of `trigger`, carrying `value` if given, from the
instruction at `pc` if given), a frame notifier judges the mark when the frame ends, and only a
frame that met the condition has its picture kept, all inside MAME at emulation speed. A film
frame is the span from one notifier to the next, named by the frame counter the notifier at its
end reads; each hit keeps the counter the tap read as well, so a write made in vblank (still the
previous counter, drawn into this frame) is not given to another frame. A reply cell's
`hit_counters` carry them, the lowest and highest counter of its listed hits (unavailable when it lists
none), and a cell joins `gfx_blits(frame=...)` and a capture's rows by `hit_counters`, not by
`frame`, which names the picture. The first span after the
install, a reset or a state load began part-way, so it is not judged. `space="io"` puts the
trigger on a port, written `0x`, by `out` (the same rules as a watch on a port); `pc` stays a
program address, and `film.space` says which space the trigger is in.

`value` names one fixed value, and a register a game writes every frame whether it moved or not
meets it on nearly every frame: a recording, not a filter. `changed=True` asks the other
question, the one a film is usually asked: a write meets it when its value differs from the
previous write to the trigger in this film, whichever instruction made that one, so the pc
filter, when given, judges the write and not what it is compared with. The film's first write
has nothing before it: it is the baseline, meets nothing, and the reply names its frame and
value (`frame_baseline`, `baseline_value`, unavailable before any write). A reset or a state load
starts no new baseline: the write before is the film's own last one, whatever came between.
`changed` and `value` are two answers to one question and are refused together.

A kept frame's picture is read one frame LATE, at the next frame's end, and that lateness is the
FRAME NOTIFIER's: MAME turns the screen's double buffer over before the frame notifiers run, so
a notifier reads the frame just finished only after the next turn (`mame_film.py` tells the
mechanism). A read at a debugger stop is not a notifier's, and that law is no evidence about
it: *Which instant a decode shows* says what was measured at a stop. Under frameskip the buffer
turns only on a frame that drew, so a met frame the machine skipped drawing is `lost` as
`skipped`, and a kept one is read at the first frame after it that drew, its frame file counting
the skipped frames it waited out. Its colours are the pens saved at its own end. Where
MAME's snapshot is the bare screen (arming compares the two at the stop), each kept frame is
also checked against MAME's rendering of it, pixel for pixel, and one that differs is refused
with its reason and has no picture; elsewhere the film says `checked: false`, and `mismatch`
measures how the snapshot differs and lists the possible causes.

`mismatch` is measured at the arming stop and asserts no cause: `screen_size` and
`snapshot_size`, `differing_pixels` of `screen_pixels` and their `bbox` (`[min_x, min_y, max_x,
max_y]`), `snapshot_colours_are_pens` (every differing snapshot pixel has the colour of one of
the pens the screen holds at the stop; unavailable on a screen in direct colour, which has none),
`flip` (`x`, `y`, then `xy`: the first mirror of the screen that equals the snapshot exactly;
`none`) and `candidates`, the one cause its rule leaves standing. `orientation`: a mirror
matched, which accounts for every pixel. `frame_lag`: no mirror, and every differing pixel is in
a pen's colour, as another picture in the same pens would be (an overlay drawn in pen colours
reads the same). `colour_adjustment`: otherwise, each screen colour drawn as one snapshot colour
and no two alike, what a colour transform applied pixel by pixel does. `overlay_or_artwork`:
otherwise, one screen colour drawn as two or two drawn as one; and a snapshot of another size
(artwork round the screen, or a scaled snapshot), where `differing_pixels`, `bbox`,
`snapshot_colours_are_pens` and `flip` are unavailable because nothing is compared. The pens are the
stop's, so a snapshot of an earlier palette reads as colours no pen holds. A snapshot file whose
length is not the size MAME declared is refused, `unexpected_answer`.

Arming needs the machine stopped: it resolves the names, asks the trigger's write side (an unmapped
one is armed, `trigger_maps_to: "unmapped"` and its `note`), and reads the screen once. The install runs when the console next reads a line. One film at a time, the
session's: it is not a stored declaration and `start` does not re-arm it, because it spends a
budget of frames (`frames`, then it is `finished`) and of pictures (`keep`; later frames that
met the condition are dropped, counted in `dropped_total`, the first and last in
`dropped_frames`) from the moment it is armed. `clear` removes it; its
files stay, `film.txt` among them: a later film writes into a directory of its own. Reading answers on a running machine too, from the files the film wrote.

What it writes, in `film_dir` or a `film-N` directory of the scratch: `frame-K.png` per kept frame
(indexed when the pens fit a PLTE, its index the pen; the `crop` when given), `film.json` listing
every kept frame with its file, sha256, check, `hits_in_frame`, `hit_counters` and listed hits (the first
ones the tap kept, each with its own `counter`, which joins a cell whose hits straddle two
counters hit by hit) and every refused one with its reason,
`sheet-F.png` for each page read, and `film-anim.png`, an animated PNG of every kept frame shown
for one frame of the screen each, never attached. The reply's `image` is the contact sheet: as
many cells as fit the inline ceiling unenlarged from `first` (`listed`, `next_first`), the page
then enlarged by the largest whole factor that still fits (`scale`), never shrunk, each labelled
in its own pixels with its frame, its hits, and its first hit's pc and value. `cost` is the
notifier's own host time, measured inside MAME, per judged frame and per kept picture; the tap's
cost per write is not in it. A film that kept nothing says so in `nothing_kept`, with the frames
it judged.

**Discovering a board nobody has described: `gfx_sweep`, `gfx_locate`, `gfx_draft`.** A block with
no stated format is drawn under a FIXED family of candidate layouts, never a guess: the depths in
`planes`, the tile sizes in `sizes`, the pixel order (`rows`; for a tile of several 8x8 cells, the
cells `across` then down, or `down` then across, the column strips many sprites are made of) and,
past one plane, the planes `packed` into each pixel, `planar` a byte each per 8 pixels, or `split`
a fraction of the block apart. Candidates with the same offsets are one, and a sheet holds a
bounded number. The sheet is one picture, every cell labelled in its own pixels with its id
(`S1C3`) and what it is, its tiles enlarged by one integer factor inside the inline ceiling (the
reply's `cell_scale`, apart from the picture's own `scale`);
nothing ranks the cells, because a heuristic that looks like proof is worse than an honest choice.
The id is the argument of the next call: `gfx_locate` and `gfx_view` take it wherever they take a
layout.

Every `gfx_locate` answer, sweep and choice is kept as the session's EVIDENCE (gone at `close` and
at `start`), and `gfx_draft` derives a DRAFT manifest from that record alone. A layout is `proved`
on a block when a match of it varies along both axes (a line decodes the same under layouts that
differ along the other axis) and proves it in one of two ways: BY SHAPE, its rarest pen covering at
least the tile's longer side (a dot is found by chance among hundreds of tiles); or BY UNIQUENESS,
at three planes or more and with its rarest pen still covering half the longer side, as its
layout's one match in an answer that searched every tile of the block (a window of many pens says
more than its rarest pen covers, and chance would match it elsewhere too; with `ref` the block is
the range the call read, `count` tiles of the layout that spans the most bytes). The proof is only
as strong as the search is wide, and the caller sets the width: a patch cut to one window matches
once whenever it matches, so the windows tried cannot say how strong it was, and the rarest pen
can (`mame_draft.py`'s module paragraph). The evidence keeps each match's `compared`, the pixels
it compared. Either way it overlaps no
other block's match on the same frame (a pixel has one origin: a letter drawn from one block is
found by chance in another's tiles), and, for every other layout of its tile size that matched
there, some answer tried both and it matched a window the other did not. Layouts of different sizes
are not rivals, since one block is often decoded both ways. A rival never told apart is not
written, and `not_proved` says so. The report's `unproving` counts a layout's windows that proved
nothing: `contested` ones, and `flat` ones by the `causes` they failed (`rows`, `cols`, `rarest`,
and, for a window varying along both axes at three planes or more, `not_unique` or
`partial_search`), which `not_proved` names. A person's pick from a sheet (`choose`, whose
`chosen_by` names who picked; one choice however often the same person makes it, and none when the draft fails) is
`human` where nothing of its size is proved, promoted when a match proves the same layout, and
named as contradicted when a match proves another. An asset follows for each block and bank a
written format was drawn through; a format proved only through a pen map proves no bank, so no
asset is written for it, and `not_proved` says why, rather than an asset with a bank nobody saw.

A command comes from a capture watch the session holds, against the answers whose matches all sit
in one window: each is an object at a known place, its tile known when one tile matched there (a
block holding one image twice leaves only the place). An answer of screen frame F pairs with the
capture's one row of frame F minus a lag, and each word of the block, or byte of a wider word, is
tried as `dest_x`, `dest_y` and `source_tile`, with a sign (coordinates stored reversed are common)
and an `add`. A reading holds when it agrees on every paired answer where the role is known, on
enough of them, the role taking more than one value. The lag is one law for the group, the one at
which both x and y hold; none or several settle nothing. A role two words hold, or a word holding
two roles, is ambiguous and not assigned; a role that holds only at another lag is named
(`elsewhere`), since the block is read at the trigger and a word written at another time of the
frame is one frame off. A command is written when x and y are proved, its box the located tile's
size.

The draft is YAML in this schema, its first line the DRAFT marker. Its `dest` is judged like every
`dest`; one that exists without the marker is refused, so a confirmed manifest is never overwritten;
the owner confirms a draft by deleting the line. The draft is read back by the loader before the
reply, so a discovered command can be tried with `gfx_blits` before anybody confirms it. Every
figure (the matches, the banks, the pairing counts, every reading that held) is in the REPORT beside
it, `dest` with `.report.json`, JSON regenerated byte for byte from the same evidence; the draft's
`source` strings name the report's key and carry no figure.

## Media files

The tools that answer about pictures and sound follow one order, so a reply is the cheapest
thing that answers the question: a signature or a number first ("is it the same screen" is two
strings compared, never two pictures sent); the full picture
last, and only from a tool whose purpose is to show (`screen_view`, `palette`, the `gfx_*`
views); and a reply that answers with numbers names what it compared, over which region, and
its path. Every tool that signs or compares the screen or a series takes a `crop`.

**The signature** (`screen_signature`, every row of a series, `raster.picture_signature` in
scry-core) is BLAKE2b with an 8-byte digest, 16 lowercase hex characters, over
`scry-sig/1|pixel|<w>x<h>|` (the crop's size) and the crop's pixels row by row as RGB. A
pixel is its resolved colour, never its pen, so a palette change is a new signature and two
screens that look the same have one. The whole screen is read in one chunk, colours only:
`screen:pixels()` is one call, cheap enough at a stop that sampling a grid buys nothing.

**A crop** is `[x, y, width, height]` inside the picture; one that leaves it is refused with
the picture's size, never padded, since a padded crop compares pixels nobody drew.

**`series_capture`** keeps frames inside MAME at emulation speed with a frame notifier and
writes them as PNGs beside one `scry-series/1` manifest: `server`, `source`, `crop`, and a row
per frame `{frame, path, sha256, bytes, signature}`. The frame numbers are the counter
`run_for(frames=...)` counts, and each picture is MAME's own rendering of its frame, read one
frame late from the notifier for the reason `gfx_film` gives (*Graphics*). A wanted frame that
frameskip did not draw is listed in `lost`, never filled in. Its colours are the pens saved at
its own end, so a palette that moves while the picture waits to be read does not repaint it.
The run goes two frames past the last, where the machine stops. With `dest` the series outlives
`close`; without it, it lives in the scratch and goes with it.

**The file tools** (`image_diff`, `series_diff`, `region_track`, `golden_check`) read files
and touch no machine, so they answer with the machine running or with none, and they are
scry-core's, the same body and text on both servers; `region_track` writes one file, the
whole track as JSON, beside the manifest. Every series and golden comparison carries its control,
because a result that cannot come out the other way is no result: a series whose frames never
change says nothing about another (`control_silent` naming it), two series with no frame in
common compare nothing, a region whose measure never moves was missed, and goldens whose names
meet no file examined nothing. Reading a manifest hashes every file it lists, so a frame
changed since it was written is refused rather than trusted.

**Sound is measured, never sent.** The model cannot take audio in, so `audio_measure` and
`audio_diff` answer what `audio_record` wrote as numbers beside its path, with a tracker's own
audio gates' measures: a peak and an RMS in dBFS; silence as an RMS under 0.5% of full scale;
spans quieter than -60 dBFS lasting 50 ms or more; the onset as the first sample over 2% of the
peak; clipping as the longest run of flat samples near the peak, because a clipped top is flat
at any level. An emulated chip at rest sits at a steady level, not at zero (the AY on the v30
board at volume 0 does), and a steady level is no sound: the RMS, the comparison and the
plateau read the window less its mean, the silences read it through a DC blocker, the onset
against the level it starts at, and the peak is read as written, the headroom left. Two recordings are compared
channel by channel, the worst grading, never through a
mixdown (a channel in antiphase cancels and two swapped channels average to one sound): by their
signal-to-error ratio (`exact`, `inaudible` at 60 dB or more, `audible` from 30, `different`
under it, or lengths a tenth of a second apart) and by the correlation of their 64-window energy
envelopes, after lining up their onsets unless `align` is false; two that are both silent
compare nothing and are `control_silent`.

**Why the picture is sized as it is** (*Graphics*, *The picture*, has the mechanics):
Anthropic's own guidance is to send an image already inside the model's limits so nothing is
resampled on the way, to crop or zoom for fine detail, not to go below about 960x540 for
screen work, where small elements are lost, and to start at 1280x720
(Anthropic, *Best practices for computer and browser use*; the limits and the cost of an
image, `ceil(w/28) x ceil(h/28)` tokens, are in Anthropic's API documentation, *Vision*). An integer enlargement
also makes pixel art more legible to a vision model, since smaller patches relative to the
content raise its accuracy
([Wang et al., *Scaling Laws in Patchification*, arXiv:2502.03738](https://arxiv.org/abs/2502.03738)).
The saving comes from the order above, not from shrinking a picture.

## Saved states

`state_save(name)` and `state_load(name)` need no Lua: the debugger console has
`statesave`/`stateload`, and they work stopped. The state lands under `sta/<system>/` beside
`cfg/` and `nvram/`, the third occupant of `state_dir` (the launch pins `-statename %g`, MAME's
own default, so an ini cannot move the folder the tools look in), and `state_list` reads that
folder without loading. **MAME refuses a bad state in SILENCE from the console**: a corrupt header
and another system's state both come back "attempted" with nothing in `error.log` or on
stdout. So the header is judged BEFORE the console (the magic, the system's name, the
signature of the states this session wrote), the load marks the session altered (it
replaces the machine) and re-runs `start`'s ROM check, and what the save recorded is compared
after the load: the frame and pc where there is a frame counter, and every register of every
cpu the stub reads (each cpu's on the patched stub, the first cpu's alone on one without
threads; a cpu with no register map is left out), compared as the stub prints them, so a cpu
whose byte order is not established here is judged all the same. A load MAME
did not take is `readback_refused`: naming the frame and pc, or, for a register, carrying
`differs` (`cpu`, `register`, `saved`, `loaded`, each value as every reply spells a register,
the stub's digits where the byte order is not established), and the stop it surveyed is
recorded all the same. **Equality after a load proves it only if something differed before
it**: the same frame, pc and registers are read just before `stateload`, and between the two
readings only the load takes effect, so a machine that already read as the save (a loop that comes back
to the saved place, or nothing run since the save) leaves `verified` unavailable
with that reason. A cpu read at the save and unreadable after the load is left out of the
comparison and named in `note`. What cannot be judged is said as unavailable with its reason,
never as a word in the value's place: `verified` for a state this session did not write, for a
machine that already read as the save, and for a board with no frame counter whose stub reads no register (the emulated clock
proves nothing either: it runs on across a `stateload` instead of coming back with the state);
`rom_check` when no reference is held; and `state_list`'s `frame` and `pc`, each with its
`why`, and its `bytes` too for a `.sta` that holds no state, judged by what its path
RESOLVES to before anything opens it: a link through which no file is reached, a directory, a
link to one, a FIFO (whose open would hold the call until a writer came), a socket or a device.
That name is taken by something that is not a state, so `state_load` refuses it `unknown_ref`
saying what is there, and `state_save` refuses it as already there. A `.sta` removed while the
folder is read is not listed.

**MAME can HOLD a save or a load instead of running it in the command.** It refuses to save or
load while an anonymous timer is pending (`device_scheduler::can_save`), logs "Failed save state
attempt due to anonymous timers" with a timer dump to `error.log`, and leaves the operation
scheduled for the end of the next timeslice, which left alone is inside the caller's next run.
A stopped machine gets such a timer two ways, and nothing fires it until the machine runs. On
any build, a memory write through the stub runs the driver's write handler, and one that
synchronizes queues a timer due now (victory's sound command at `0xf800`). On a stub that
refreshes the display after a console command or a memory write (*The console*), the refresh
runs the driver's screen update, and a driver that raises an input line from there (circus
asserts its IRQ on a sprite collision) queues that line's event the same way. So
`state_save`, `state_load` and a `statesave` or `stateload` typed through `debug` read
`error.log` after the command, and when MAME held it they step ONE instruction through the
stub's `s`, which is no console command and refreshes nothing: the timeslice ends, the timer
fires, the operation completes, and the stop that follows is the machine the operation left.
Nothing can end that step before the operation lands: while one is pending MAME calls no cpu's
debugger hook (`compute_debug_flags`), so no breakpoint, watchpoint or step on any cpu stops
the machine first, and a step after which MAME logs no second hold has completed it.
The reply says so in `held` (`debug`: in `note`), the step is recorded as a stop (`stop_seq`),
and a save's frame, pc and registers are read after it, so they are the file's. MAME keeps ONE
pending operation, each replacing the one before, so a `debug` line that had several held
completes only the last, and the note says so. An operation still held after the step, or a
step that brings no stop, is `not_settled`, because it would land in the next run.

## The console

`debug` sends one command to the debugger console through the protocol's `monitor` escape;
anything the debugger window can do, a mutating command counts as a write (each word of the
line is resolved as the console resolves it, the command it names or the one command it is a
prefix of, and classified by that command off MAME's own command table, every command of which
the classifier places, on the cautious side:
an assignment, `fill`, `load`/`loadr`, `stateload`/`sl`, `softreset`,
`rewind`/`rw`, `mount`, `suspend` and `resume` naming a cpu, `do`, `source` (a file of console
commands, any of which may write), any run the console owns, and an ACTION, found by the
parameter each command takes it in, braced or bare: the third of a `bp` or an `ep`, the second
of an `rp`, the fifth of a `wp`, the fourth of a `trace`/`traceover`; a condition, braced or
not, is evaluated and never run, so it writes only through an assignment. With no parameter,
`suspend`, `resume`, `ignore` and `observe` only list, so they are no write and set no cpu.
`//` and `/*` are `comadd` and `commit` under other names, the comment pane's, and a comment's
text is never evaluated, so an assignment is looked for in its address alone; `input` posts
keys the game reads only if it runs, which is play and not a write, the rule the `input` tool
states. A line holding a `hardreset` is refused before it is sent (`bad_argument`): it
re-creates the machine and the stub's connection dies with it, so `close` then `start` is that
reset, as the `reset` tool says. A word the core does not have is a driver's own command or one
the console refuses, and counts as nothing; a comparison is never an assignment, so
`print {d1==7fff}` is a read; an assignment is looked for OUTSIDE quoted strings only, since the
console prints a string and never evaluates it, so `printf "pc=%x\n",pc` is a read and
`printf "%d",d0=1` a write (a `"` after a backslash does not close the string, the console's own
rule); and an assignment to a debugger temp (`temp9=0`, a control's
`(++temp9)==0` on a `bpset`) is not a write, since the temps are the debugger's and not the
guest's, while `temp0=w@100=1` still is, because the chain reaches memory. A line of
several commands is split where the console splits it, at a `;` outside brackets and quotes,
and each command is judged alone, for a write as for a release, a clear or a control's
counter. A `focus`, `ignore` or `observe` naming a cpu anywhere on a line that releases nothing, in any
prefix the console takes, has the reply read back `visible_cpu` and `ignored`. When the line ignored the cpu MAME
is LIVE on (the one the last stop was on, which the patched stub's `?` names and an `Hc` does
not move), MAME runs until another cpu executes, answering the console meanwhile, so the
visible cpu is read once it stops on a cpu it observes, and `note` says it ran; ignoring a
visible cpu that is not the live one runs nothing and leaves an ignored cpu visible, which
`note` says too (`focus` the tool shows a cpu without a run on a build with the thread patch). A `condition` still refuses a temp assignment: the controls count in the
temps. A line that assigns a control's temp names the control in `note`: assigned now, it
moves the cumulative `hits_since_armed` of `breakpoint_list` and not a run's `control_hits`, which
is a difference taken across the run, and -1 makes the control halt at its next hit;
assigned by a row the line arms, it is written at every evaluation and both counts see it),
and a long answer goes to a file. A command whose packet would be past the size the stub
advertised is refused as `bad_argument` BEFORE it is sent, with `command_chars` and
`limit_chars`: the stub drops such a packet unanswered, so sending it would only buy a wait
that ends in a timeout blaming the wrong thing. The check sits where every console command is
made, so a long `condition`, `find` pattern or `memdump` path is refused the same way. A
`condition` is judged before anything is stored, declared or disarmed, in every command it
goes out in: the `print` that evaluates a declared breakpoint's is longer than the `bp` that
arms it at a short address. One that was stored
without being judged (its ref did not resolve, or another binary's stub took it) and does not
fit this stub is `unarmable` at `start`, with that reason, and kept. The console wraps every
line at its text buffer's width (MAME's own, `CONSOLE_WRAP_COLS` here), and the breakpoint and
watchpoint lists are read back as whole rows, so a condition up to the packet limit stays
listable and clearable. MAME's comment commands are the comment tools' channel to its pane
(Declarations): a `comadd` typed through `debug` is shown in the pane for the session and is
neither stored nor listed.

**The console has no exit code, so its own error answers are read.** A line it refuses
answers text like any other, and `debug` once answered `ok` over it with the error only in
`output`, a `perform` going on to the next step. Now the shapes the console was captured
printing (`tests/fixtures/console/refused.*`: `Error in expression` with its caret line,
`Invalid breakpoint number`, `Invalid registerpoint number`, `Invalid watchpoint type`, `Error
opening file`, and the parse
errors `unknown command`, `ambiguous command`, `unbalanced parentheses`, `unbalanced quotes`,
`not enough parameters for command`, `too many parameters for command`, `error in assignment
expression`) make the reply INVALID, `bad_argument`, the message quoting the console's line
and naming the refused command, with `output` kept whole as an `ok` reply keeps it, `refused`
(each refused command, its `index` on the line, its `error`; bounded, with `refused_total`)
and `not_run`. Each shape is
matched anchored at a line's start, and a shape not captured is not matched. The two families
differ in what ran: a parse error is printed as the echoed line, a caret under the failing
command and the reason, and the console stops the line there, so the commands before it ran
and the rest did not; an error a command prints while running (`Error in expression` from a
`print` or a `bp`, `Invalid ...`, `Error opening file`) leaves the rest of the line running.
The commands a parse error stopped never ran, so they are left out of the writes, the
release and the cpu setters of the line: a `g` behind a refused command leaves the machine
stopped. A command refused while it ran stays counted, on the cautious side, because the
console evaluates its parameters in order and a `print d0=5,zzz` writes D0 before it refuses
`zzz` (captured); so a `load` of a missing file counts as a write by its prefix even though
nothing landed. The clears of the line re-read their lists whatever was refused. An error the
answer cannot pin on one command (two `bpclear`s and one `Invalid breakpoint number`) names
the whole line and counts every command. A bare comparison typed as a command (`print
d1==1234`) is an ASSIGNMENT EXPRESSION to the console's parser, one parameter holding `=`,
and is refused as such; braced (`print {d1==1234}`) it is a command and answers. The echo and
the caret line of a parse error are read back through the console's wrap, so a long line's
refusal is still pinned; a run-time error line longer than the wrap is not read. A `perform` or a `drive` step that is refused this way ends the list there
(`step_failed`, the step's reply `bad_argument`), which is the whole point: a reading after
a refused command is a reading nobody asked for.

**The Lua channel is MAME's own console**, `-console`, over the process's standard input, and
it works with no terminal attached: `start` spawns the emulator with stdin a pipe, and what
the console prints lands in the same `stdout.log` the `process` channel reads. The console
is a PLUGIN, and `start` names its directory on the command line: the first, relative to the
RESOLVED binary, that holds `console/init.lua`, of `plugins/` beside it (a source build) and
`../share/mame/plugins` (a packaged install, under its prefix). MAME's own default looks in its
working directory (the scratch, here) and in one version also under the home directory, so two
builds given the same command line can boot and die respectively; a binary with the plugin in
neither place is refused by `start` before anything is spawned, naming each file it looked
for, because without it MAME's `-console` is fatal ("Console plugin not found").

- **The console evaluates when its periodic hook runs.** The hook runs once per frame while
  the machine runs, and once per stop on the way into the debugger's wait loop; inside that
  loop the gdbstub spins in its own packet loop. A gdbstub that ends a debugger console
  command with `refresh_display()` (a newer `handle_q` does, an older one does not) runs the
  hook once more per command, since that refresh is a `frame_update` asked by the debugger.
  So a line sent to a STOPPED machine sits in the pipe until the console next reads a line: the
  machine's next step or frame, or, on such a stub, the next console command a tool sends
  (most tools send one, if only to read the pc). ONE single-step buys it whatever the stub,
  and so does the first frame of any run. AND THE HOOK READS ONE LINE EACH TIME IT RUNS
  (in `plugins/console/init.lua` the `emu.register_periodic` callback takes one line from its
  linenoise coroutine per call and holds `stopped` while the chunk runs): a `throttle` asked
  while stopped leaves its line ahead, and where nothing reads it first, the step `lua` buys
  evaluates the throttle and not the script. So `lua` counts the lines still ahead (the
  sentinels printed against the lines sent) after the debugger command it opens with (it reads
  the pc it starts from), which on a refreshing stub has already read one of them, and steps
  once for each before its own, and says so (`lines_ahead`, `evaluated_by`). AND THE READER IS A
  THREAD: the plugin starts the linenoise read in an `emu.thread`, and the hook at a stop
  returns without evaluating while that thread is still taking the line, so a step sent
  right after the line can land before the reader holds it. So an answer is given a short
  window after each step, and while it does not come one more step is spent, under a cap;
  the reply counts them (`reader_steps`). AND THAT THREAD IS UNSAFE BY MAME'S OWN ADMISSION
  (`luaengine.cpp`, `thread_context::start`: "FIXME: this is unsafe"): the reader clears
  `busy` before it has finished unwinding, and the hook that finds it idle loads the next
  read into the same Lua state while the old one still runs there. A step landing in that
  window kills the reader (`[LUA ERROR] in thread`), and after each death the hook, whose
  `result` a dead thread never clears, RUNS THE PREVIOUS CHUNK AGAIN, its sentinel printed
  twice; or the reader echoes the line and dies holding it, and the chunk never runs at all.
  So every line written waits a moment before anything can move the machine, which is what
  lets the reader finish; a line the console took and never evaluated (the reader died
  holding it, or the console refused it at its top level) is sent again once (`resent`),
  and twice is the refusal
  `reader_died`; and every reply that reads the console counts the deaths, names the chunks
  run again and the lines sent again (`thread_errors`, `console_reruns`, `resent`, each
  spelled out in the reply's `note` when it is not zero), because a chunk that wrote has then
  written twice and `altered` alone cannot say so. The call's OWN chunk run again is
  invisible to the sentinels, whose own number is the one skipped, so `input`, `record` and
  `audio_record` count their own marks: one logged twice is the refusal `console_rerun`, the
  repeats counted in `console_reruns`, named in the message, and counted in
  `session.console.reruns`. When their line has no answer
  after the run and one more step and a reader death is in the log since it was sent, with no
  echo pinning it on the line, the refusal is `reader_died` with `pending: true`: the script
  has not run YET and may still run on a later reader (the console has been captured
  answering lines after a death), so it stays ahead in the pipe and is not counted `lost`,
  a count kept for lines the echo proves eaten. Every line sent is settled against the log as
  it grows, whichever call sent it: its sentinel, or its echo with a failure after it, which
  counts it `lost` once and takes it out of the lines ahead, so no wrapper steps the machine
  for it again. Each wrapper's `drain_steps`, on every reply and refusal, says how many steps
  it spent on the lines ahead before sending its own. `throttle` proves itself by its mark in `error.log` and reads no console, so
  it carries none of these: the next call that does read the console counts what happened
  around it.
- **Every answer is framed by its own sentinel, never by the prompt** (a tap's install, which
  prints no prompt, is judged UNRUN by a prompt behind its echo, never answered by one).
  Stdout is a file and fully buffered, flushed by the prompt linenoise prints after each
  chunk; but a script is
  free to print the prompt's bytes, and after a script that raises MAME prints a `[LUA
  ERROR] in thread` and the last line a SECOND time (the channel goes on). So every call
  carries a sequence number, in the chunk (its echo is unique) and in a sentinel line the
  chunk prints last with the outcome, and the answer is what sits between the echo and that
  sentinel; the reader keeps a mark past the last sentinel it consumed.
- **A whole script is ONE chunk under `pcall`.** The console loads each line as its own
  chunk, so a two-line script would lose its `local`s between them; the script travels as a
  Lua string literal inside one line that loads it, runs it under `pcall` and prints the
  sentinel with `ok` and the error, so a script that fails to compile or raises is refused in
  its own words and never read as a missing answer.

**`lua(script)` is the raw form, and it is honest about what it costs.** Nothing in a Lua
string says whether it wrote, so the call marks the session ALTERED always, once the script
has been judged; it needs the machine stopped, like every reader, and buys the evaluation
with one step per line still ahead in the pipe plus its own, plus one more when the
console's reader had not taken the line at the stop, which the reply declares
(`lines_ahead`, `reader_steps`, `evaluated_by`, `pc_before`, `pc`). Its output is bounded
like `debug`'s. A console `error:` line is a refusal in the console's words.

- **`read_only=True` is the caller's word, and it is recorded as such.** It is not counted as a
  write and nothing verifies it: there is no honest classifier for Lua the way `debug` has one
  for a closed command vocabulary. The session block then carries `read_only_claims` and a note
  saying `altered` rests on the caller's word for those calls. The default is the honest one;
  the flag exists so that a session that only ever read is not stamped modified for the rest
  of its life.
- **What the script reads is the state after the steps `lua` buys**, one per line still
  ahead and then its own, since the last of them is the first thing to run the console's hook
  once its line is sent (no console command goes in between): with nothing ahead, the state
  AFTER the instruction at the stop's pc, so a stop ON a write reads it written. More
  than eight lines ahead in the pipe is refused, naming `run_for` a frame to drain them, since
  each costs a step. A `wait_expired` says how many steps were taken: the machine moved, and
  the answer, when it comes, lands in `log` on the `process` channel, found by the call's
  sentinel (`MAME_MCP_LUA_END#N` followed by a tab; the command's echo carries it without one).
- **Only what prints comes back.** A `return` value never reaches the console, so `return
  emu.romname()` answers an empty `output` and `print(emu.romname())` the name; an empty
  output from a script with no `print` carries a `note` saying so. A reader that dies holding
  the line twice is `reader_died`, and the script never ran.
- **A callback the script installs is the script's to guard.** Its own chunk runs under `pcall`,
  but a write tap, a notifier or a periodic hook it registers runs later, outside it, and this
  server does not wrap what the caller wrote. Measured: an error raised in a write tap goes
  NOWHERE (not stdout, not `error.log`) and the tap keeps firing and raising at every write; one
  raised in a frame notifier or a periodic hook lands in `log`, channel `process`, as `[LUA ERROR]
  error in machine frame callback: ...` or `[LUA ERROR] in execute_function: ...`, one line per
  call, and it keeps firing too. So a census of the caller's own is honest only with its body under
  `pcall` and its errors counted, the way this server's own taps report `callback_errors`.

## Development

The server file holds what is about the SURFACE and nothing else; each kind of work has its
module:

- **`gdb_session.py`**: the protocol client. Register numbers and widths come from the target
  description of each cpu's thread rather than being guessed, the byte order the one `start`
  hands it from MAME's inventory, cross-checked against the architectures measured here (and a
  cpu with no word from MAME refuses instead of guessing); every register or
  memory packet goes through the one method that selects its thread; memory, registers, the
  protocol's `monitor` escape hatch into MAME's console (the `debug` tool), and the reader of
  the project's symbol file in both its shapes.
- **`server.py`**: the tools, each registered with its description and its one-line
  `summary`, and the one tool that is a known-answer read (`rom_check`). Every tool's
  description is written for the client, inside the prefix the client delivers: what it does,
  its arguments, what it refuses, what it returns, and the section of this reference that holds
  the why.
- **`mame_mcp.py`**: the MCP boundary every tool is wrapped in: the server object and its
  `instructions` (what a session receives at connection), the lock over the one machine, the
  decorator that registers a tool, and this server's hooks into `scry_core.boundary` (how a
  body is called and which errors are answers, how a cancelled call ends, the reply a call the
  schema refused gets); the core closes every reply (`summary` first, `session` last).
- **`mame_state.py`**: what is held between calls (the process, the session, each cpu's symbols, the
  breakpoints this server armed, the scratch, the last stop as its survey saw it).
- **`mame_envelope.py`**: the envelope every reply carries, built from that state: `status`, the
  tool's fields, the `session` block.
- **`mame_progress.py`**: the progress line of a bounded wait (`Ticker`) and the one rule a
  call's notifications keep, never going backwards.
- **`mame_inputs.py`**: the judge of every input two tools share (a count, a yes or no, a ref,
  an address argument written `0x`, a number given as an integer or `0x`, a closed vocabulary, a
  wait, a regular expression, a path), each rule written once.
- **`mame_args.py`**: the table of which argument each tool judges BEFORE the session gate,
  one function per rule owned by the module that does the work, read by the surface and by
  the batch executor alike.
- **`mame_launch.py`**: the command line as a pure function, the window flags, the port
  probe, `start` and `close`.
- **`mame_binary.py`**: which MAME `start` runs, by the ladder *The session* sets out, and the
  build's own version line.
- **`mame_stub_owner.py`**, **`mame_guardian.py`**, **`mame_idle.py`**: whose gdbstub a port
  serves, proved by the process that holds it; the guardian beside every MAME, so it dies with
  the server however the server ends; and the idle bound, which closes a session no tool has
  touched for `IDLE_CLOSE_S`.
- **`mame_boot_failures.py`**: what a launch that failed before its session existed says, and
  whether `start` launches it again: a death, a stub not ready, the assertion's abort, a first
  cpu the stub cannot describe, and the dial attempts of one boot.
- **`mame_symbols.py`**: the symbol tables `start` loads, one per cpu, with their `bases` and
  `types`, the store's key and the build fingerprint.
- **`mame_advance.py`**: `run_to` with its control, `run_for` by the frame counter, `step`,
  and the breakpoints.
- **`mame_cpu_info.py`**: `cpu_info`, one row per cpu of what the debugger sees of it now, and
  the count of this server's declarations on each.
- **`mame_cpus.py`**: the machine's cpus and which one a reply is about: the visible cpu read
  off `cpulist`, a cpu a call names matched against the inventory, the stub's thread for a cpu,
  each cpu's pc register read off that thread, every served cpu's register block, the debugger's
  `ignore` and `suspend` listings, and `Hc`, the one way the visible cpu is moved without
  running, with `on_cpus`, the one bracket that shows a cpu, acts and puts the visible one back.
- **`mame_focus.py`**: `focus`, through the stub's `Hc` with the proof that nothing ran, or
  through the console's own `focus`, and the wait for the stop a typed line that ignored the
  live cpu leads to.
- **`mame_machine.py`**: `machine_map`'s inventory, gathered once at `start` from `-listxml`
  and the live machine's Lua channel, each section naming its source.
- **`mame_running.py`**: the RUNNING guest: the one survey every stop comes back as, the stop
  the machine reached on its own recorded by the first contact that finds it, the readers'
  refusal that names the last stop, `resume` and `stop`.
- **`mame_read.py`**: bytes, a disassembly, a search, the trail, the registers, each capped
  and each refusing a console answer of the wrong shape; and the placer, the one rule that
  puts an address inside a symbol, a sorted table bisected per address.
- **`mame_scan.py`**: the value scan, `scan_start`, `scan_filter` and `scan_clear`: a range
  read through the console's `save` and compared here, never through MAME's cheat engine.
- **`mame_trace.py`**: `trace`, the console's tracer armed and closed around `run_for`'s body,
  its file parsed by shape and joined to the placer into the set file and the summary.
- **`mame_flow.py`**: the mnemonic tables per cpu type that class a disassembly's lines as a
  call, a branch, a return or the next instruction, each mirroring its disassembler's flags.
- **`mame_files.py`**: the tools that answer with a PATH and check the file first, the wait
  for a file the emulator writes at its own pace and the first free name in a folder, and
  `log_wait`, the wait for a line of the driver's log.
- **`mame_declarations.py`**: the INTENT behind a breakpoint or a watch, declared by a symbol
  name or a raw address, or behind a registerpoint, declared by its condition, and the store that keeps it on disk keyed by the system and the
  symbol file.
- **`mame_arming.py`**: what every family shares where a declaration meets the machine: the
  store, a declaration's shape and its list row, how a call's ref is classed and resolved, and
  the stop lines the console logs for a row of its own lists.
- **`mame_lists.py`**: the debugger's own `bplist` and `wplist` read back into rows, and a row
  adopted rather than stacked.
- **`mame_conditions.py`**: a condition as the console reads it, refused for what it may not
  hold and judged on its cpu before it is armed.
- **`mame_clear.py`**: a row cleared by its index, the refusal of a ref that matches nothing,
  and a row this server did not arm named with the command that removes it.
- **`mame_breakpoints.py`**: the breakpoint family, stop breakpoints and counting controls,
  and the naming of a stop at one.
- **`mame_watches.py`**: the watch family, armed, sent as a tap or read at a stop, the
  evaluation of every watch at a stop, and who wrote the byte a watchpoint stopped on.
- **`mame_map.py`**: where an address goes, from the console's `map` and `mapi`: each side's
  handler, read before anything is armed there, what the address is (`memory_kind`), the
  refusal of a change watch on an unmapped write and the note a tap there says.
- **`mame_rearm.py`**: `start`'s re-arm of the whole store in one pass over both families.
- **`mame_tally.py`**: the count watch, a Lua write tap composed by the server that tallies
  every write to a range by value and by writer pc without stopping, read back at every stop.
- **`mame_tap.py`**: what every tap shares, whatever it keeps: the install script's skeleton,
  the record, the install's proof, the removal and the dump read at a stop.
- **`mame_callbacks.py`**: the guard every callback the server installs runs its body under, and
  how a dump carries what it caught (`callback_errors`).
- **`mame_capture.py`**: the capture, the same tap on a trigger, appending a row at each write to
  it (the whole block) or each read (the value read), with where the block is read from.
- **`mame_space.py`**: the address space a tap is installed in, the program's or an io port's,
  and the bus-word arithmetic a tap's range is judged by.
- **`mame_iotaps.py`**: taps in a cpu's io space, a count watch on a port and a capture a port's
  write triggers.
- **`mame_regpoints.py`**: the registerpoint family over the debugger's `rpset`: the condition
  evaluated before it is armed, `rplist` read back, the registerpoint half of `start`'s re-arm, and
  the naming of the stop a registerpoint makes, this server's or one typed through `debug`.
- **`mame_comments.py`**, **`mame_comment_pane.py`**, **`mame_comment_file.py`**: comments, a
  text at a place in the program held as a declaration, and their tools; MAME's disassembly pane,
  the view each comment is fed to and read back from, and how a place is handed over when the
  comment it shows leaves; the TSV a project versions, read by `comment_load` and written by
  `comment_save`.
- **`mame_write.py`**: what CHANGES the machine: bytes and a register, each read back; the
  soft reset, applied and read back; and `debug`, the door to the whole console.
- **`mame_console.py`**: the console's grammar `debug` judges a line by: its commands and their
  parameters as the console cuts them, which of them write, release the machine, set a cpu, arm
  something evaluated later or leave `totalcycles` stale, and the console's own refusals.
- **`mame_lexer.py`**: beneath that grammar, where a quoted string ends, what counts as an
  assignment and which debugger temps a line writes.
- **`mame_sequence.py`**: the executor behind `perform` and `drive`, taking its operation
  table FROM the server.
- **`mame_lua.py`**: the Lua CHANNEL and the typed wrappers composed on it (`input`,
  `throttle`), and the queued run every wrapper makes.
- **`mame_transport.py`**: the bytes of the channel: a chunk sent down stdin, its answer framed
  by a sequence number and a sentinel and read back off stdout, and what the console's reader did
  on the way.
- **`mame_recording.py`**: `record`, the bounded run every recording shares (`recording_run`)
  with its replies for a recording not begun, still open or whose run did not settle, and
  `captures`, which lists every file a tool of this session checked and handed back.
- **`mame_audio.py`**: `audio_record`, the mixer's WAV over a counted span, on
  `recording_run`, its file read back by `mame_files`' WAV reader.
- **`mame_savestates.py`**: the savestates through the debugger console's `statesave` and
  `stateload`, each judged by the file's header and the frame, pc and register blocks the save
  recorded, and the one instruction that completes either when MAME held it (`debug` uses it
  too).
- **`mame_cycles.py`**: the `totalcycles` a load, a rewind or a typed reset left stale, and the
  reason the run that would start from it gives for its unavailable `cycles`.
- **`mame_region.py`**: the ROM region behind an address, a region's bytes in the order the cpu
  reads them (`logical`), and `write(region=True)`'s route into it through the console's
  `saver` and `loadr`.
- **`mame_block.py`**: `read_block`, a memory share or region read through that channel, by
  tag or by the address whose map entry names it.
- **`mame_chunk.py`**: one Lua chunk that reads, evaluated for a graphics tool, and the refusals
  every such chunk shares.
- **`mame_screen.py`**: `screen_view`, `screen_signature`, and the index capture every tool that
  looks at the screen shares.
- **`mame_series.py`**: `series_capture`, its frame notifier and the PNGs it develops.
- **`mame_palette.py`**: `palette`, and the pens a tile sheet is drawn through.
- **`mame_layout.py`**, **`mame_gfx.py`**, **`mame_locate.py`**: the `gfx_layout` language and
  its decoder, `gfx_view` with the reader of the bytes a layout is stated over, and `gfx_locate`.
- **`mame_yaml.py`**, **`mame_manifest.py`**: the strict YAML subset a project's `gfx.yaml` is
  read in, and its schema, its loader and `gfx_load`.
- **`mame_evidence.py`**, **`mame_correlate.py`**, **`mame_sweep.py`**, **`mame_draft.py`**: what
  this session established about the board's graphics, in order; which word of a captured block
  holds a drawn object's x, y and tile, proved against the screen; `gfx_sweep`, one block under a
  family of candidate layouts as one labelled sheet; and `gfx_draft`, a `gfx.yaml` draft derived
  from that evidence.
- **`mame_blits.py`**: a capture's rows through a draw command, `gfx_blits` and
  `gfx_blit_source`.
- **`mame_ramdac.py`**, **`mame_ramdac_lua.py`**: the palette write log, `palette_log`, and
  the pixel's `set_by`; the Lua taps the log runs inside MAME, for every kind of palette port.
- **`mame_film.py`**, **`mame_sheet.py`**, **`mame_font.py`**, **`mame_mismatch.py`**: the
  conditioned film, `gfx_film`; the contact sheet it answers with; the 5x7 font the sheet is
  labelled in; how MAME's snapshot differs from the screen, the film's `mismatch`.
- **`scry_core.reply_contract`**, **`scry_core.value_format`**,
  **`scry_core.strict_arguments`**: the refusal contract, the watch value grammar and the strict
  schema, held once in the `scry-core` package both Scry servers pin.
- **`mame_summaries.py`**, **`mame_docs.py`**: the one line every reply opens with, one function
  per tool; and what a tool's description states that the code already knows, filled from the
  constants that enforce it at registration.

### Tests

```sh
uv run pytest tests       # installs the package and its dev tools first
```

Every guarantee in this document has a test that was seen RED against the defect before it
was fixed, and the console parsers are held to text captured live rather than authored (the
captures live under `tests/fixtures/console/` with their provenance). The live half is
`tests/live/live_check.py` against a real board, which drives every tool through the server,
the running contract and the throttle flight included. The boards it drives run on a bench
under `MAME_LIVE_BENCH` (`~/.local/share/scry-bench/mame` when unset): copies of their
binaries, ROMs and symbol files pinned by hash in the bench's own `bench.json`, and an
`identity.json` beside it that says which set, binary and files each board's label stands for
(its keys: `IDENTITY_KEYS` in `tests/live/bench_boards.py`).
Neither is tracked, because both name the programs the copies came from; the tracked live code
names only the labels. `uv run python -m scry_core.live_bench fill --bench <bench> --from
<source_repo>=<checkout>` copies them from their checkouts and `check --bench <bench>` says
whether they still match, and a board whose identity is incomplete or whose copies are absent
or wrong is BLOCKED naming what is wrong rather than run on something else.
The live half is deselected by default (`-m live`), so a stranger running `pytest tests` from a
clone never launches an emulator per case.

### Proving a change

The session that edits this server cannot exercise its change through it: a running server
answers from the state it was launched with. A change is proved out of process, with a stdio
client in a fresh process binding the server from the files as they stand and calling a
fixed sequence, and the verdict block it prints says of every reply whether the first key is
`summary` and the last is `session`.
