# The Session tools

A session is one MAME running under its debugger. `start` opens it and leaves the machine stopped at the debugger; `close` ends it. One session is open at a time.

`status`, `window` and `close` answer while the machine runs. `cpu_focus` and `rom_check` need it stopped.

A repository can keep how its program starts in its own `.scry/` folder, as a start profile: a file of `start` arguments. What every session shares, such as how a path is written and how a board with several cpus is addressed, is in [REFERENCE.md, The session](../../REFERENCE.md#the-session).

<!-- scry-reference:begin start -->
## `start`

Start MAME on a system, stopped at the debugger, after checking that it runs the program your reference image holds.

```text
start(system="", rompath="", reference_rom="", symbols="", reference_addr=0, inipath="",
    boot_seconds=8.0, shared=false, display=null, size=null, background=null, boot_lua="", env=null,
    bases=null, reference_base=0, stub_port=0, state_dir="", throttle_from_frame=0, types="",
    cfg="", binary="", presence=true,
    overlay={"calls": true, "keys": true, "pointer": true, "pause": true, "record": true, "place": "auto"},
    view="", names=true, profile="")
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org. The example session starts it for a person to watch, with seven symbols and a reference image of the program ROM at `0xa000`.

Ask:

> Start Gridlee in a window I can watch without losing my keyboard, with these symbols, checked against this image at 0xa000.

Call:

```text
start(shared=true, background=true, display="<host>", system="gridlee",
    reference_rom="./tmp/demos/tour/gridlee.ref", reference_addr="0xa000", reference_base="0xa000",
    inipath="./tmp/demos/tour/gridlee-ini", state_dir="./tmp/demos/tour/gridlee-states", … 3 more)
```

Reply, 7 of 35 fields:

```json
{
  "status": "ok",
  "system": "gridlee",
  "rom_check": "OK",
  "symbols_total": 7,
  "pc": "0x0000f000",
  "frame": 0,
  "kept": "1 saved for `promote`; start/gridlee: nothing this session r ... (166 characters)"
}
```

The check passed, seven symbols are loaded and the machine is stopped at `0x0000f000` on frame 0. `kept` says the arguments were saved as a start profile, for `promote` to write into a repository.

<details><summary>The whole reply</summary>

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "system": "gridlee",
  "binary": "<volatile>",
  "binary_origin": "<volatile>",
  "version": "0.289 (unknown)",
  "pid": "<volatile>",
  "stub_port": "<volatile>",
  "scratch_dir": "<volatile>",
  "state_dir": "./tmp/demos/tour/gridlee-states",
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "debugger": {
    "attached": "gdbstub",
    "note": "MAME runs with -debug under this stub. A capture taken at one of this session's stops can land a frame away from an autoboot golden taken by a frame notifier at the same count, in a scene that changes every frame: compare a live capture wit ... (255 characters)"
  },
  "errorlog_path": "<volatile>",
  "stdout_path": "<volatile>",
  "rom_check": "OK",
  "symbols_total": 7,
  "symbols_typed": 2,
  "symbols_format": "yaml",
  "symbols_by_class": {},
  "symbols_by_cpu": {":maincpu": 7},
  "registers": ["A", "B", "D", "X", "Y", "U", "... 4 more"],
  "pc": "0x0000f000",
  "frame": 0,
  "frame_symbol": "frame",
  "view": "native",
  "views": ["Screen 0 Standard (4:3)", "Screen 0 Pixel Aspect (16:15)", "Cocktail"],
  "background": true,
  "flags": "<volatile>",
  "boot_lua_path": "<volatile>",
  "presence": true,
  "machine": {
    "cpus": 1,
    "spaces": 1,
    "address_map": 14,
    "regions": 3,
    "shares": 3,
    "screens": 1,
    "rom_files": 13
  },
  "declarations": {
    "persistent": true,
    "path": "./tmp/demos/tour/gridlee-states/declarations.json",
    "key": "gridlee ./docs/reference/tour/gridlee-symbols.yaml",
    "held": 0,
    "fingerprint": "9ddedcc4d2bcbc14",
    "rearm": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": [], "evaluated": []},
    "comments": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": []}
  },
  "recommended_release": "0.289",
  "window": "<volatile>",
  "kept": "1 saved for `promote`; start/gridlee: nothing this session read names its repository: promote(dry_run=true, root=<the repository>) lists what an approval would create"
}
```

</details>

### Arguments

- `system` (string, default `""`): The system to run, by MAME's short name. Required unless a start profile gives it.
- `rompath` (string, default `""`): The folders that hold the system's ROMs, separated by `;`. Required unless a start profile gives it.
- `reference_rom` (string, default `""`): A binary image of the program you expect to be running, which the machine's memory is compared with. Required unless a start profile gives it.
- `symbols` (string or object, default `""`): A symbol file, so an address can be given by name: a YAML file or the linker's five-column map. One path is the first cpu's; `{cpu: path}` gives one per cpu.
- `reference_addr` (integer or string, default `0`): The address where 16 bytes of the machine are compared with the image: an integer or a `0x` string. Left out, 0.
- `inipath` (string, default `""`): The folders MAME reads its `.ini` files from, separated by `;`. Left empty, MAME's own.
- `boot_seconds` (number (> 0, <= 600.0), default `8.0`): How long to wait for MAME's debugger to answer, in seconds. Left out, 8.
- `shared` (boolean, default `false`): `true` when a person watches: a large window at real speed. Left out, a small window that runs unthrottled.
- `display` (integer, optional): Which display the window opens on, by the operating system's index. Needs `shared=true`; left out, 0, the main display.
- `size` (string, optional): The window's size as `WIDTHxHEIGHT`, in the host's unit. Needs `shared=true`; left out, the largest whole multiple of the screen that fits the display.
- `background` (boolean, optional): `true` opens the window behind your other windows and leaves the keyboard focus where it is; `false` opens it in front. Left out, behind unless `shared`.
- `boot_lua` (string, default `""`): A Lua file MAME runs at boot, after the server's own script. It is a path, never Lua text.
- `env` (object, optional): Environment variables for MAME's own process, as `{name: value}`. They are there for what `boot_lua` reads.
- `bases` (object, optional): For a linker's map: the address each class other than CODE is based at, as `0x` text or an integer, or `rom`. With per-cpu `symbols`, `{cpu: {class: base}}`.
- `reference_base` (integer or string, default `0`): The address of the image's first byte. Left out, 0.
- `stub_port` (integer (>= 0, <= 65535), default `0`): The TCP port of MAME's gdbstub, the remote-debugger connection this server uses. Left at 0, a free port is picked.
- `state_dir` (string, default `""`): The folder for saved states, `cfg/` and `nvram/`, which stays after `close`. Left empty, the session's temporary folder, deleted at `close`.
- `throttle_from_frame` (integer, default `0`): Runs unthrottled until this frame and at real speed from it on, with either kind of window. Left at 0, the speed follows `shared`.
- `types` (string or object, default `""`): A file of `name: format` lines, one per symbol whose value has a format. With per-cpu `symbols`, `{cpu: file}`.
- `cfg` (string, default `""`): A `.cfg` file the server installs as the system's own before it boots. Left empty, MAME runs on its defaults.
- `binary` (string, default `""`): The MAME to run: an executable, or a `.app` bundle holding one. Left empty, `MAME_BINARY`, else the `mame` on the PATH.
- `presence` (boolean, default `true`): Draws a border around the emulator's window while the session is open, brighter while a call runs the machine. `false` leaves it off.
- `overlay` (any, default `{"calls": true, "keys": true, "pointer": true, "pause": true, "record": true, "place": "auto"}`): Marks over the border, on by default: `calls` names each call, `keys` the fields held, `pause` a stopped machine, `record` a recording. `place` is `top`, `bottom` or `auto`.
- `view` (string, default `""`): What `snapshot` and `record` draw. Left empty, the emulated screen at its own size; else one of MAME's layout views, named by how its name begins.
- `names` (boolean, default `true`): `false` leaves a reply's numbers bare, with no `names` field and no name in its summary; the window's captions still name them.
- `profile` (string, default `""`): A start profile: a saved set of `start` arguments, by its name under `.scry/start/` or by a path. It fills only the arguments the call leaves out.

### What comes back

- `rom_check`: `OK` when the 16 bytes read from the machine equal the image's. A start whose check fails is refused.
- `pc`: Where the machine stands, stopped.
- `window`: With `shared`, where the window is. Its `front` is `true` when no other application's window covers its centre; it does not mean the window has the keyboard focus.
- `profile`: With a start profile: its `name`, its `file`, and `supplied`, the arguments it filled.
- `kept`: Says that this start's arguments were saved as a start profile for `promote`, the tool that writes one into your repository's `.scry/` folder.
- `start_retries`: Present when MAME had to be launched more than once: what each earlier attempt left.

<details><summary>All 51 reply fields</summary>

- `activation` (string)
- `asked_display` (integer)
- `seen` (object)
- `searched` (array)
- `kept` (string)
- `after_s` (number)
- `alive` (boolean)
- `background` (boolean)
- `binary` (string)
- `binary_origin` (string)
- `boot_lua_path` (string)
- `bundle` (string)
- `cfg` (object)
- `debugger` (object)
- `declarations` (object)
- `dial_attempts` (array)
- `env` (object)
- `error` (string)
- `errorlog_path` (string)
- `flags` (array)
- `frame` (integer or object)
- `frame_symbol` (string or object)
- `machine` (object)
- `overlay` (object)
- `pc` (string)
- `phase` (string)
- `pid` (integer)
- `presence` (boolean)
- `profile` (object)
- `recommended_release` (string)
- `registers` (array)
- `reply` (string)
- `rom_check` (string)
- `scratch_dir` (string)
- `start_retries` (array)
- `state_dir` (string)
- `stdout_kept` (string)
- `stdout_path` (string)
- `stdout_tail` (string)
- `stub_port` (integer)
- `symbols_by_class` (object)
- `symbols_by_cpu` (object)
- `symbols_format` (string)
- `symbols_total` (integer)
- `symbols_typed` (integer)
- `system` (string)
- `throttle_from_frame` (integer)
- `version` (string or object)
- `view` (string or object)
- `views` (array or object)
- `window` (object)

</details>

### What it refuses

- A session is already open (`session_live`).
- The 16 bytes differ from the image's; the session is closed (`readback_refused`).
- `system`, `rompath` or `reference_rom` given neither by the call nor by a start profile, a path that is not absolute, or a folder where a file is expected (`bad_argument`).
- A `reference_addr` outside the image, a `stub_port` that is not free, or a `cfg` MAME would not read (`bad_argument`).
- Per-cpu `symbols`, `bases` or `types` naming a cpu the machine does not have (`unknown_ref`).
- A class of a linker's map with no base, `bases` beside a YAML file, or a bad line in `types` (`bad_argument`).
- A `state_dir` that is the server's own folder for the saved breakpoints file, directly or through a link: a session with a `state_dir` keeps its own (`bad_argument`).
- `display` or `size` without `shared=true`, a `display` the host does not have, or a `size` larger than the display's usable area (`bad_argument`).
- A `profile` that no `.scry/` folder searched holds; `searched` lists them (`bad_argument`).
- A window that never appears on the display asked for. The session stays open for `window` or `close` (`window_not_visible`).
- A MAME that exits or never answers during the boot (`session_broken`).

### Why it works this way

Before it answers, `start` reads 16 bytes of the machine at `reference_addr` and compares them with `reference_rom`. If they differ, MAME is not running the program your addresses describe. The session is then closed, because one left open would answer the next call about another program.

`shared` says whether a person watches. Without it MAME opens a small window, unthrottled and behind your other windows, which `window` cannot report. With it the window opens on `display`, in front and at real speed; add `background=true` to watch without losing the keyboard focus.

A start profile is a file of `start` arguments, `.scry/start/<name>.json` in a repository, so a session starts with `start(profile="<name>")`. The call's own arguments win and the profile fills the rest. The `.scry/` folder is looked for upwards from the server's working directory, then from `rompath` and `binary`.

<details><summary>More on why</summary>

| you want | arguments | the window |
|---|---|---|
| Nobody watching | `shared=false`, the default | Small, unthrottled, behind. `window` refuses it as `no_channel`. |
| Somebody watching | `shared=true`, with `display` and `size` if wanted | On the display, in front, at real speed, confirmed in the host's window list. |
| Watching and keeping the keyboard focus | `shared=true`, `background=true` | The same, opened behind your other windows. |

**The window's size.**

A watched window is the largest whole multiple of the machine's first screen that fits the display's usable area. The window's frame counts; the menu bar, Dock and taskbar do not. MAME draws the picture at the view's aspect and scales it by whole pixels, so it is letterboxed where the view's shape is not the screen's.

`size` wins over that fit, in the host's unit: points on macOS, real pixels on Windows. One that does not fit is refused, naming the usable size. One that is not a whole multiple of the screen is scaled unevenly, and the `note` says so.

`start` waits until the host lists the window on that display. Do not select `-video none` yourself: on macOS it takes over the display.

`background` only chooses where the window opens. How the focus stays with you is the host's: on macOS the emulator starts as a background application, and on Windows no program may take the foreground while `start` launches. A click or ALT moves the focus as always.

**Fast-forward to a late scene.**

`throttle_from_frame=N` runs unthrottled to frame N, then at real speed, and logs `MAME_MCP throttled from frame N`. Waiting for that line with `log_wait` also restarts the span `close` measures `average_speed` over, so the speed is the real-speed part alone. It is fixed at launch; `throttle` switches the speed of an open session.

**The boot.**

- A MAME that exits while `start` waits ends the wait at once, and the refusal gives its exit code.
- One still alive when `boot_seconds` runs out is `session_broken`; `stdout_kept` is a saved copy of what it printed.
- A crash by a signal before the debugger answers, or a port another process took first, is launched again a few times. `start_retries` lists the attempts.
- An exit code (missing ROMs, an unknown system, a bad option) would come again, so it is refused at once.
- A MAME that dies after `start` answered is never launched again.
- An unknown `system` is refused in MAME's own words: after the launch, or before it on a `shared` start or with per-cpu `symbols`.
- A gdbstub that does not describe the board's first cpu is `no_channel`: that MAME build cannot serve the board.
- Another process listening on a `stub_port` you named is `host_failed`, naming its pid.
- `start` connects once, after MAME prints its debugger banner. A build that never prints it costs every start its whole `boot_seconds`.

**Symbols and files.**

- A symbol file belongs to one cpu, because each cpu runs its own program. With `{cpu: path}`, `bases` and `types` are per cpu too, and the single shape is refused.
- `symbols_total`, `symbols_typed`, `symbols_format` and `symbols_by_class` describe the first cpu's file; `symbols_by_cpu` counts each.
- `boot_lua` runs after the server's own boot script, so `boot_lua_path` is the combined script. One that calls `manager.machine:exit()` ends the machine under the session.
- With `state_dir` empty, saved states, `cfg/` and `nvram/` live in the temporary folder `scratch_dir` names. Nothing is written into your project either way.
- `cfg` is copied to where MAME reads it; your file is never touched. MAME reports a rejected `.cfg` on stderr only, so the server reads that and refuses the start.
- A `type:` line under a YAML symbol, or a `types` line, says what the symbol is, so a watch needs no `fmt`. A pointer's type names what it points at.

**What else the reply says.**

- `version` is the build's own `-version` line and `recommended_release` the MAME version this server is tested on. Another version starts with a `note`, never a refusal.
- `debugger.note`: the machine runs under the debugger, so a capture at a stop can land one frame from a reference capture an autoboot script took at the same frame count.
- `machine` holds counts only; `machine_map` has the rows. If MAME's `-listxml` fails, the start still works and the `note` says what is left empty.
- `frame_symbol` is the name the frame counter answers to; a board with no screen has none ([Run](run.md)).
- `flags`, `env`, `view`, `background`, `binary_origin`, `errorlog_path` and `stdout_path` say what the launch used, so a start can be told from another by its own reply.
- `presence` is `true` while the border is drawn. A failure drawing it never changes another reply: `presence`, here and in `status`, turns `available: false` with a `why`.
- `overlay` is there with the border on: the `layers` drawn, the `place` in effect, and in `lacking` why one is not. MAME has no pointer, so that layer is lacking.

</details>

### Related tools

- [`status`](#status)
- [`window`](#window)
- [`close`](#close)
- [`rom_check`](#rom_check)
- [`throttle`](lua.md#throttle)
- [`promote`](project.md#promote)

<details><summary>The contract your client receives</summary>

```text
Start MAME with its gdbstub, parked STOPPED and checked against the reference image.

Paths are absolute or `~`-led: `rompath` and `inipath` `;`-separated directories, `state_dir`
a directory, the rest files. `binary` names a MAME executable or a `.app` bundle carrying
one: the bundle is launched through `open`, which makes it an application the host captures
as one, and the reply names it in `bundle`; its exit status is then not this server's to
know, and `close` answers `unavailable` for it. The check: `reference_rom`, `reference_addr`,
`reference_base` (the image's first byte).
`symbols`, `bases`, `types`: one value, or `{cpu: ...}` per cpu.
`shared=True`: somebody watches (a window of the largest whole multiple of the screen that
fits the display's usable area, drawn at the view's aspect, real speed); false, nobody
watches: a small window run flat out. `display`: the OS's
display index for that window, 0 (the main display) when omitted; `size`:
`WIDTHxHEIGHT` of the window in the host's unit, which wins over the fit (a size that is not a
whole multiple of the screen is scaled by whole pixels, unevenly, and the reply's `note` says
so). Both
need `shared=True` and are refused otherwise; `size` is also refused when it, with its frame,
exceeds the display's usable area, naming that size; a `display` past the host's count is
refused naming the count. The server waits for the window to be
listed on that display and answers `window`; a later `window` judges a stated size.
`background`: launch behind, keeping the caller's focus, or in front, either window; omitted
it is behind unless `shared`; somebody watching without losing their focus is `shared=True`
with `background=True`. `throttle_from_frame`: flat out until that frame, real speed after,
either window.
`boot_lua`: a harness file, not Lua text. `boot_seconds`: the wait for MAME's first prompt.
`env`: variables MAME's own process gets. `cfg`: a `.cfg` file the server installs as the
system's own before it boots, judged for what MAME would refuse in silence.

`profile`: a repository's run recipe (`.scry/start/<name>.json`) or a path to one. Its keys
are this tool's arguments and fill only what the call does not give; the reply's `profile`
block names it and what it filled. The store is looked for from the server's working
directory, then `rompath` and `binary`.

Refused before MAME boots: a live session (`session_live`), an unknown cpu, a class with no
base, `bases` beside a YAML file, a bad `types` line, a busy `stub_port`, a `reference_addr`
outside the image (a `shared` start first asks MAME `-listxml`, whose time comes before that
refusal), a `profile` that no directory above holds (the refusal names them).
A mismatch: `readback_refused`, closed. A window that never appears on the asked display:
`window_not_visible`, the session left live to `window` or `close`.

Reply: `system`, `pid`, `window` (`display`, `bounds`, `onscreen`, `front`, `fullscreen`, with
`shared`; `front` says no other application's window covers its centre, not that it has the keyboard focus), `stub_port`, `rom_check`, `pc`, `frame`, `start_retries`,
`recommended_release` (0.289), with a profile `profile` (`name`, `file`,
`supplied`), and `kept` when the recipe is complete and the draft holds it; another release
boots with a `note` saying so.

Reference: REFERENCE.md, The session.

presence: Draw an edge around the emulator's window while this session is open: dim while idle, bright while a call runs the machine. No capture of this server carries it.

overlay: Layers drawn over the presence edge, each on by default: `calls` a caption naming each call and its arguments, abbreviated (paths by their last name); `keys` the keys or fields held down; `pointer` the guest's mouse pointer; `pause` a mark while the session holds the machine stopped; `record` a blinking mark while it records video or audio. `place`: where the captions go, `top`, `bottom`, or `auto`, the band of the picture that shows less. Ignored with `presence=false`.

view: What `snapshot` and `record` render through: empty, the emulated screen at its own size; else a layout view by prefix (`views` lists them, `view` says which was taken).

names: Name the numbers a reply shows: a port, interrupt, address or key gets its name in the reply's `names` and in its summary. `false` leaves replies bare; the window's captions keep their names.
```

</details>
<!-- scry-reference:end start -->

<!-- scry-reference:begin status -->
## `status`

Ask whether a session is open and what the machine is doing, without moving it.

```text
status()
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), right after that start: the machine is stopped and nothing has run.

Ask:

> Is the emulator still up, and where is it stopped?

Call:

```text
status()
```

Reply, 6 of 22 fields:

```json
{
  "summary": "status: gridlee alive at pc 0x0000f000",
  "status": "ok",
  "system": "gridlee",
  "pc": "0x0000f000",
  "in_debugger": {"breakpoints": [], "watches": [], "regpoints": []},
  "cpu_tags": [":maincpu"]
}
```

Gridlee is up and stopped at `0x0000f000`. `in_debugger` is empty because no breakpoint or watch is set yet, and `cpu_tags` names the board's one cpu.

<details><summary>The whole reply</summary>

```json
{
  "summary": "status: gridlee alive at pc 0x0000f000",
  "status": "ok",
  "system": "gridlee",
  "pid": "<volatile>",
  "stub_port": "<volatile>",
  "scratch_dir": "<volatile>",
  "state_dir": "./tmp/demos/tour/gridlee-states",
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "debugger": {
    "attached": "gdbstub",
    "note": "MAME runs with -debug under this stub. A capture taken at one of this session's stops can land a frame away from an autoboot golden taken by a frame notifier at the same count, in a scene that changes every frame: compare a live capture wit ... (255 characters)"
  },
  "presence": true,
  "fingerprint": "9ddedcc4d2bcbc14",
  "fingerprints": {":maincpu": "9ddedcc4d2bcbc14"},
  "errorlog_path": "<volatile>",
  "stdout_path": "<volatile>",
  "pc": "0x0000f000",
  "last_stop": {
    "stop_seq": 1,
    "pc": "0x0000f000",
    "cpu": ":maincpu",
    "frame": 0,
    "cause": "start",
    "since_s": "<volatile>",
    "wall_at": "<volatile>"
  },
  "in_debugger": {"breakpoints": [], "watches": [], "regpoints": []},
  "threads": {"1": ":maincpu"},
  "cpu_tags": [":maincpu"],
  "console_pending": 0,
  "tallies_pending_removal": [],
  "frame_symbol": "frame"
}
```

</details>

### Arguments

Takes no argument.

### What comes back

- `last_stop`: Where the machine last stopped: its `pc`, `cpu` and `cause`, and `since_s`, how long ago. Unavailable, with why, when there is no stop to report.
- `pc`: Where the machine stands now. Unavailable while it runs or once the session is broken; `last_stop.pc` is then the answer.
- `stopped_on_its_own`: Present when the machine had stopped and no call had reported it yet. `status` records that stop as the last one.
- `broken`: Present when the session can no longer be trusted, with the reason. The way out is `close`, then `start`.
- `in_debugger`: What MAME's debugger holds now: `breakpoints`, `watches` and `regpoints` (registerpoints, stops on a register condition), each by its `ref`, a symbol or an address, and its `cpu`.
- `fingerprint`: A hash of the system, the reference image and the symbol file. A breakpoint or watch saved under another one is not trusted; `fingerprints` has one per cpu.

<details><summary>All 21 reply fields</summary>

- `cfg` (object)
- `console_pending` (integer)
- `debugger` (object)
- `errorlog_path` (string)
- `fingerprint` (string)
- `fingerprints` (object)
- `frame_symbol` (string or object)
- `in_debugger` (object)
- `overlay` (object)
- `pc` (string or object)
- `pid` (integer)
- `presence` (boolean)
- `scratch_dir` (string)
- `state_dir` (string)
- `stdout_path` (string)
- `stub_port` (integer)
- `system` (string)
- `tallies_pending_removal` (array)
- `threads` (object)
- `throttles_pending` (array)
- `names_failed` (object)

</details>

### Why it works this way

`status` answers in every state: with no session, while the machine runs and once the session is broken. It is where you learn why another tool does not answer.

<details><summary>More on why</summary>

- With no session the reply is `last_stop` and, when there is one to give, a `note`. After MAME exited under the session it is `exit_code` and a `note`.
- `debugger.note` says a capture at a stop can land one frame from an autoboot reference capture; `start` says why.
- `threads` is empty on a MAME without the gdbstub thread patch, which gives each cpu a debugger thread. `cpu_tags` only names the cpus; what each is doing is `cpu_info`'s.
- `console_pending` counts Lua lines sent and not yet run. `throttles_pending` lists speed switches asked and not yet applied (`tag`, `on`).
- `tallies_pending_removal` lists write counts waiting to be removed (`tally_id`, `call`); a row that leaves is a removal done.
- `presence` is `true` when the border is drawn, `false` when it was asked off, or the reason it is not drawn.
- `overlay` is there with the border on, as `start` gave it: the `layers` drawn, the `place` in effect and, in `lacking`, why a layer is not.
- `last_stop` also carries `stop_seq`, `frame` and `wall_at`. `frame_symbol` is the frame counter's name, as `start` found it.
- `cfg`, `stdout_path`, `errorlog_path`, `scratch_dir` and `state_dir` are the session's files, as `start` named them.

</details>

### Related tools

- [`start`](#start)
- [`close`](#close)
- [`cpu_info`](machine.md#cpu_info)
- [`stop`](run.md#stop)
- [`declaration_list`](breakpoints.md#declaration_list)

<details><summary>The contract your client receives</summary>

```text
Whether a machine is alive, and which one. Safe on a running machine; a stop it finds the
machine reached on its own is recorded and reported in `stopped_on_its_own`.

Reply: `last_stop` (`stop_seq`, `pc`, `cpu`, `cause`, `since_s`, `wall_at`) with or without a
session, unavailable once a session has ended; with no session also a
`note` when there is one to give, or, for a process that exited under it, `exit_code` and a
`note`; with a session `system`, `pid`, `stub_port`, `scratch_dir`, `state_dir`, `presence`,
`debugger`, `fingerprint` (`fingerprints` per cpu), `errorlog_path`, `pc`, `in_debugger`
(`breakpoints`, `watches`, `regpoints`: each `ref`, `cpu`), `console_pending`,
`throttles_pending`, `tallies_pending_removal`, and `broken` when the session can no longer
be trusted: `close`, then `start`.

Reference: REFERENCE.md, The session.
```

</details>
<!-- scry-reference:end status -->

<!-- scry-reference:begin window -->
## `window`

Find where the session's window is on your displays and whether another window covers it, or bring it in front.

```text
window(front=false)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), started with `shared=true` so that it has a window to report.

Ask:

> Where is the emulator's window, and can I see it?

Call:

```text
window()
```

Reply, 1 of 3 fields:

```json
{
  "status": "ok"
}
```

The run hides the `window` block and the summary here, because where the window is differs on every host. `status` is `ok`: the host listed the window.

<details><summary>The whole reply</summary>

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "window": {
    "display": "<volatile>",
    "bounds": "<volatile>",
    "onscreen": true,
    "front": "<volatile>",
    "fullscreen": false
  }
}
```

</details>

### Arguments

- `front` (boolean, default `false`): `true` brings the window in front of whatever covers it and reads the result back. Left out, the window is reported where it is and nothing moves.

### What comes back

- `window`: Where it is: `display`, `bounds`, `onscreen`, `fullscreen` and `front`. `front` is `true` when no other application's window covers its centre; it does not mean the window has the keyboard focus.
- `size`: Only when `start` named a `size`: what was `asked`, what is `seen`, and whether it `matches` within `tolerance_px`.

<details><summary>All 5 reply fields</summary>

- `activation` (string)
- `asked_display` (integer)
- `seen` (object)
- `size` (object)
- `window` (object)

</details>

### What it refuses

- No session is open (`no_session`).
- The session's emulator died (`session_broken`).
- The session was started without `shared`, so there is no watched window to report (`no_channel`).
- The window never appears, or with `front` is still covered after it was activated. `seen` says what the host listed (`window_not_visible`).

### Why it works this way

`front` answers one question: can a person see the picture? It is `true` when the window is on screen and no other application's window covers its centre. It is not the keyboard focus, which a window nothing covers can be without.

`window` answers at any time, a running machine included. Without `front` it moves nothing and reports the window wherever you put it. With `front`, a session started with `background=true` may stay behind, and the refusal names that as the likely cause.

A `size` given to `start` is checked here, at any moment, a start still stopped included, because MAME sizes its window when it creates it. The size the server chose by itself is never checked.

<details><summary>More on why</summary>

- `compared` says which rectangle was measured: `client`, the area inside the frame, on Windows; `outer` on macOS, which has no client area, so a title bar's height is allowed.
- `height_free` is `true` when the emulator fits the height to the picture's aspect by itself, so only the width is checked. MAME does this on Windows.
- `display` is the operating system's index, and `fullscreen` is `true` when the window's bounds are the display's.
- On a `window_not_visible` refusal, `asked_display` is the display `start` asked for and `activation` what bringing it forward answered.

</details>

### Related tools

- [`start`](#start)
- [`status`](#status)
- [`snapshot`](captures.md#snapshot)

<details><summary>The contract your client receives</summary>

```text
Where the watched window is on the host, at any time, a running machine included. `front`
brings it in front of whatever covers it and reads that back.

Reply: `window` (`display`, the OS's index; `bounds`; `onscreen`; `front`, on screen with no other application's window covering its centre; `fullscreen`); `size` when the session was started with a stated `size`: `asked`, `seen`, which rectangle was `compared` (`client` or `outer`), `tolerance_px`, `height_free` and `matches`.

Refused: no session (`no_session`), one that died (`session_broken`), a session started without `shared` (`no_channel`), a window that never appears or, with `front`, is still covered after the activation (`window_not_visible`, naming what was seen; on a `background=true` session it names that as what may keep it behind). Without `front` the window is answered wherever the owner put it.

Reference: REFERENCE.md, The session.
```

</details>
<!-- scry-reference:end window -->

<!-- scry-reference:begin close -->
## `close`

End the session and the emulator with it, and learn how it ended.

```text
close(detail=false)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), at the end of the example session, after it saved a screen map and a list of steps.

Ask:

> We are done: close the emulator and tell me how it ended.

Call:

```text
close()
```

Reply, 7 of 12 fields:

```json
{
  "summary": "close: quit, exit code 0, last words left out (see `omitted`)",
  "status": "ok",
  "closed": true,
  "ended_by": "quit",
  "exit_code": 0,
  "cfg_written": true,
  "draft": ["maps/gridlee", "perform/two-coins", "start/gridlee"]
}
```

MAME quit when asked, with exit code 0, and wrote its cfg. `draft` names three things the session saved that `promote` can still write into a repository's `.scry/` folder.

<details><summary>The whole reply</summary>

```json
{
  "summary": "close: quit, exit code 0, last words left out (see `omitted`)",
  "status": "ok",
  "closed": true,
  "omitted": ["stdout_tail", "errorlog_tail"],
  "how": "close(detail=True) keeps the channels' last words on a clean quit too; once a close has answered they are gone with the scratch",
  "ended_by": "quit",
  "exit_code": 0,
  "cfg_written": true,
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "console_pending_before": 0,
  "console_drained": 0,
  "draft": ["maps/gridlee", "perform/two-coins", "start/gridlee"]
}
```

</details>

### Arguments

- `detail` (boolean, default `false`): `true` returns the last lines the emulator printed (`stdout_tail`, `errorlog_tail`) after a clean quit too. Left out, they come only when the end was not clean.

### What comes back

- `closed`: `true` when a session was ended; `false` when there was none to close.
- `ended_by`: How it ended: `quit`, `exited`, `killed`, `died` or `none`.
- `exit_code`: The emulator's exit code. It is `available: false` with a `why` when no session was running or the killed process could not be collected.
- `average_speed`: The emulation speed over the last run `resume` opened, as `percent`. Absent when no such run was open.
- `cfg`: With a `cfg` at `start`: `installed_path`, and `changed`, whether MAME rewrote the installed copy.
- `draft`: The names of what the session saved and `promote` has not yet written into your repository's `.scry/` folder.

<details><summary>All 10 reply fields</summary>

- `draft` (array of string)
- `average_speed` (object)
- `cfg` (object)
- `closed` (boolean)
- `console_drained` (integer)
- `console_pending_before` (integer)
- `ended_by` (string)
- `errorlog_tail` (string)
- `cfg_written` (boolean or object)
- `stdout_tail` (string)

</details>

### Why it works this way

`close` asks MAME to quit through its console and kills it only when it has not gone within the grace period. MAME writes `cfg/` and `nvram/` on a clean exit only, and ignores SIGTERM. `ended_by` says which happened, since `closed: true` would say the same of every ending.

It is the one way out of every state: it works on a running machine and on a broken session, and with no session it answers `closed: false`. The session's temporary folder is deleted; a `state_dir` you named stays.

`session` describes the state after the close: `alive`, `running` and `altered` are `false`, as with no session. A doubt about what the session reported, a console error count or a speed switch that never applied, is still there, because it stays true of the answers you have.

<details><summary>More on why</summary>

- `quit`: a clean exit. `cfg_written` says whether MAME wrote its cfg, and is unavailable when there was no cfg file to read.
- `exited`: it exited and wrote none.
- `killed`: killed after the grace period. `exit_code` is unavailable if the process is still not collected.
- `died`: it had already exited.
- `none`: there was no session.

- `average_speed` is the server's own measure, the debugger's emulated clock over the wall clock: MAME prints no speed line when it exits from the debugger.
- It holds `percent` and the two deltas, or `available: false` with a `why`.
- Lua lines still waiting in the console are run before the quit, because one left there can crash MAME on its way out. `console_pending_before` and `console_drained` count them.
- The `note` names the lines that could not be run, so a bad exit code has its likely cause beside it.
- `cfg` is unavailable when no cfg was given, and `changed` says so when the copy could not be read back.
- When the last lines are left out, `omitted` names them and `how` says what brings them.
- On a broken session `close` asks MAME nothing: no drain, no speed read and no `quit`, only the kill.
- The last lines are read before the temporary folder is deleted, so a MAME that died still gives its last words in `stdout_tail` and `errorlog_tail`.

</details>

### Related tools

- [`start`](#start)
- [`status`](#status)
- [`promote`](project.md#promote)
- [`resume`](run.md#resume)

<details><summary>The contract your client receives</summary>

```text
End the session: MAME is asked to `quit` and killed only if it has not gone within the
grace period. The scratch is deleted; a named `state_dir` stays. Works on a running machine;
with no session it answers `closed: false`.

Reply: `closed`, `ended_by` (`quit`, `exited`, `killed`, `died`, `none`), `exit_code` (an
integer, or unavailable with its `why` when no session was running or the process was not
reaped), `cfg_written` (MAME wrote its cfg as it quit),
`cfg` (`installed_path`, `changed`), `average_speed` (while a `resume` run was open), `note`;
`stdout_tail` and `errorlog_tail` when the end was not a clean `quit`, or with `detail=True`.
`session` is the block as it is after the close (`alive` and `running` false); a console doubt
or a throttle found not applied still rides there, and `draft` names the candidates the
session left waiting for `promote`.

Reference: REFERENCE.md, The session.
```

</details>
<!-- scry-reference:end close -->

<!-- scry-reference:begin cpu_focus -->
## `cpu_focus`

Choose which cpu MAME's debugger shows, the one every call that names no `cpu` acts on.

```text
cpu_focus(cpu)
```

### Try it

This needs a board with more than one cpu, which neither free ROM has. The reply shown comes from a test program that is not distributed.

Ask:

> Show me the main cpu in the debugger.

Call:

```text
cpu_focus(cpu="maincpu")
```

Reply, 8 of 8 fields:

```json
{
  "summary": "cpu_focus: :maincpu visible, was :maincpu, nothing ran (stub)",
  "status": "ok",
  "cpu": ":maincpu",
  "was": ":maincpu",
  "via": "stub",
  "machine_ran": false,
  "frame": 0,
  "unchanged": [":maincpu", ":subcpu"]
}
```

The main cpu was already the visible one. `via` `stub` and `machine_ran` `false` say nothing ran, and `unchanged` lists both cpus: their registers read the same before and after.

<details><summary>The whole reply</summary>

```json
{
  "summary": "cpu_focus: :maincpu visible, was :maincpu, nothing ran (stub)",
  "status": "ok",
  "cpu": ":maincpu",
  "was": ":maincpu",
  "via": "stub",
  "machine_ran": false,
  "frame": 0,
  "unchanged": [":maincpu", ":subcpu"]
}
```

</details>

### Arguments

- `cpu` (string, required): The cpu to show, by its tag in either spelling: `subcpu` or `:subcpu`. `machine_map` lists the tags.

### What comes back

- `cpu`: The cpu the debugger shows after the call, read back from its `cpulist`.
- `was`: The cpu it showed before.
- `via`: `stub` when the gdbstub switched it, which runs nothing; `console` when the debugger's `focus` command did.
- `machine_ran`: `true` when the machine ran to make the switch. The reply then also describes the stop it reached.
- `unchanged`: With `stub`: the cpus whose registers read the same before and after, which is the evidence that nothing ran.
- `ignored`: With `console`: the cpus the debugger now ignores.

<details><summary>All 17 reply fields</summary>

- `cpu` (string)
- `following` (array of string)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer or object)
- `ignored` (array)
- `machine_ran` (boolean)
- `pc` (string)
- `regpoint_hit` (object)
- `regs` (object)
- `stop_seq` (integer)
- `unchanged` (array)
- `unread` (array)
- `via` (string)
- `was` (string or object)
- `watch_hit` (object)
- `watches` (array)

</details>

### What it refuses

- The machine is running (`not_stopped`).
- A cpu the machine does not have (`unknown_ref`).
- With the gdbstub thread patch, a cpu the debugger ignores (`bad_argument`).
- The cpu read back afterwards is not the one asked for (`readback_refused`).
- Without the patch, the run the console started reached no stop that was read (`not_settled`).

### Why it works this way

MAME's debugger acts on one cpu at a time, the visible one, and every stop makes the cpu that stopped visible. A call that names a `cpu` acts on that cpu and leaves the visible one alone, so `cpu_focus` is the call that moves it. [REFERENCE.md, The session](../../REFERENCE.md#the-session) has the whole rule.

On a MAME built with the gdbstub thread patch, which gives each cpu its own debugger thread, nothing runs. The reply shows it: `machine_ran: false`, the `frame`, and `unchanged`. Without the patch the debugger's `focus` command ignores every other cpu, and the machine may run until the chosen cpu executes.

<details><summary>More on why</summary>

`unread` names a cpu whose registers the gdbstub would not give, so it is never counted as unchanged.

</details>

### Related tools

- [`cpu_info`](machine.md#cpu_info)
- [`machine_map`](machine.md#machine_map)
- [`registers`](read.md#registers)
- [`step`](run.md#step)

<details><summary>The contract your client receives</summary>

```text
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
```

</details>
<!-- scry-reference:end cpu_focus -->

<!-- scry-reference:begin rom_check -->
## `rom_check`

Check again that the machine runs the program your image holds, at any address and on any cpu.

```text
rom_check(reference_rom, reference_addr=0, reference_base=0, cpu="")
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), stopped, with the reference image `start` was given.

Ask:

> Check again that the ROM at 0xa000 is still the image I gave you.

Call:

```text
rom_check(reference_rom="./tmp/demos/tour/gridlee.ref", reference_addr="0xa000",
    reference_base="0xa000")
```

Reply, 4 of 6 fields:

```json
{
  "status": "ok",
  "rom_check": "OK",
  "deterministic": true,
  "cpu": ":maincpu"
}
```

The 16 bytes read from the machine equal the image's, and a second read gave the same bytes (`deterministic`). `cpu` names the cpu that was read.

<details><summary>The whole reply</summary>

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "rom_check": "OK",
  "deterministic": true,
  "query_s": "<volatile>",
  "cpu": ":maincpu"
}
```

</details>

### Arguments

- `reference_rom` (string, required): The binary image to compare the machine's memory with.
- `reference_addr` (integer or string, default `0`): The address where 16 bytes of the machine are compared with the image: an integer or a `0x` string. Left out, 0.
- `reference_base` (integer or string, default `0`): The address of the image's first byte. Left out, 0.
- `cpu` (string, default `""`): The cpu whose memory is read. Left empty, the one the debugger shows.

### What comes back

- `rom_check`: `OK`: the 16 bytes read from the machine equal the image's.
- `deterministic`: `true` when reading the same address again gives the same bytes.
- `query_s`: How long one read through the debugger takes, in seconds.
- `cpu`: The cpu that was read.

<details><summary>All 4 reply fields</summary>

- `cpu` (string or object)
- `deterministic` (boolean)
- `query_s` (number)
- `rom_check` (string)

</details>

### What it refuses

- The machine is running (`not_stopped`).
- The bytes differ. The refusal names the cpu that was read, and the session stays open (`readback_refused`).
- On a MAME without the gdbstub thread patch, which gives each cpu its own debugger thread, a cpu other than the first (`bad_argument`).

### Why it works this way

`start` makes this check once, with the image and address it was given. `rom_check` takes its arguments again on every call, so you can point it at another address, image or cpu. `state_write(method="load")` repeats `start`'s own check.

Name `cpu` once a stop has made another cpu the visible one, because an image is one cpu's program. The check is about the running machine, never about the MAME build. The second read is for `deterministic`, and `query_s` is what one read costs.

<details><summary>More on why</summary>

A MAME without the gdbstub thread patch reads its first cpu only, whatever the debugger shows.

</details>

### Related tools

- [`start`](#start)
- [`state_write`](states.md#state_write)
- [`cpu_focus`](#cpu_focus)
- [`read_memory`](read.md#read_memory)

<details><summary>The contract your client receives</summary>

```text
Re-validate the session: 16 bytes at `reference_addr` of `cpu` (empty: the visible one)
against `reference_rom` at `reference_base`. Needs the machine STOPPED (else `not_stopped`).

A mismatch is `readback_refused`.

Reply: `rom_check` (`OK`), `deterministic`, `query_s`, `cpu`.

Reference: REFERENCE.md, The session.
```

</details>
<!-- scry-reference:end rom_check -->
