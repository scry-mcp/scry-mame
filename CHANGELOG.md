# Changelog

What a client of the server notices.

## Unreleased

- A caption wider than the window is cut and marked with `..`, never scrolled: a line that moves
  cannot be read while the machine runs.
- Replies and captions call a number by its name where the server knows one. A reply lists
  each in `names` and in its `summary`; `names=false` on `start` leaves replies bare, and the
  window's captions keep their names. A symbol you typed names itself; an address is named by the
  nearest symbol, else by the memory the map names. With `names=false` a
  disassembled line carries no note either.
- An entry of the knowledge base says what the chip's or the cpu's own document says, row by row,
  with MAME's verdict on each row it judged (as documented, differs, absent, unfollowed) and
  MAME's own notes after them. Each row cites the lines it was read from; a chip with no public
  document is answered from MAME's source, and says so. Any other number stays a number.
- The reference has a Knowledge base section: what the base holds and what an entry says.
- `knowledge_find` asks what a number is called and what the base says of it: one match, or an
  `id`, answers the entry whole, and `id=<entry id>#<n>` one row, with a link to each line it
  cites. With a session it also lists the machine's input fields, its devices and its memory map.
||||||| /tmp/mc-base.md
- A caption wider than the window is cut and marked with `..`, never scrolled: a line that moves
  cannot be read while the machine runs.
- Replies and captions call a number by its name where the server knows one. A reply lists
  each in `names` and in its `summary`; `names=false` on `start` leaves replies bare, and the
  window's captions keep their names. A symbol you typed names itself; an address is named by a
  vector, else by the nearest symbol, else by a shared chip, else by the memory the map names.
- Each entry of the knowledge base is checked against the source it cites. The Z80's vectors and
  the chips both servers share are named; any other number stays a number. `status` answers
  `knowledge` with the entries the base serves.
- The reference has a Knowledge base section: what the base answers, that each entry is checked
  against its source, and where the base is going.
- `knowledge_find` asks what a number is called and what the server knows about it, with the
  public source each fact was read from. A key the base has no checked entry for stays a number;
  one whose entry is held back answers its id in `unconfirmed`, never its text.
  With a session it also lists the machine's input fields, its devices and its memory map.
- A write to a chip's index handler names the register it selects, whether the register is told
  apart by direction, sits in a range or in a second bank. With `names=false` a disassembled line carries no note either.

- Replies call a number by its name where the server knows one. A reply lists each in `names`
  and in its `summary`; `names=false` on `start` leaves replies bare. A symbol you typed names
  itself; an address is named by a vector, else by the nearest symbol, else by a shared chip,
  else by the memory the map names.
- Each entry of the knowledge base is checked against the source it cites. The Z80's vectors and
  the chips both servers share are named; any other number stays a number. `status` answers
  `knowledge` with the entries the base serves.
- The reference has a Knowledge base section: what the base answers, that each entry is checked
  against its source, and where the base is going.
- `knowledge_find` asks what a number is called and what the server knows about it, with the
  public source each fact was read from. A key the base has no checked entry for stays a number;
  one whose entry is held back answers its id in `unconfirmed`, never its text.
  With a session it also lists the machine's input fields, its devices and its memory map.
- A write to a chip's index handler names the register it selects, whether the register is told
  apart by direction, sits in a range or in a second bank. With `names=false` a disassembled line carries no note either.
- `disassemble` gains `line_notes` for an instruction that states an operand the base names, and
  the stop's `instruction` a `note`. They are apart from `comment_list`'s comments.
- `start` and `status` answer, in `overlay`'s `notes`, what a layer is drawn without while the
  machine is stopped: the record mark stays lit instead of blinking.
- The orange edge can carry a record mark: while `record` or `audio_record` runs, a red dot
  blinks in the top right corner of the window, with REC for a video, with a note for audio,
  with both for both. `start` takes `overlay` to choose it (`record`), and `start` and `status`
  answer with an `overlay` that lists what is drawn and why a layer is not: MAME has no
  pointer. Like the rest of the edge, no capture carries it. `overlay` is left out when the
  presence is not drawn: a drawer that stopped, or a delivery that failed, shows in `presence`.
- Every demo is shown moving: a `loop.webp` beside its README replaces `loop.mp4`. It holds
  up to five moments cut from `record` calls of the demo's own run, scaled up so its pixels
  stay sharp.
- The Star Fire demo presses START and films a mission, and the LineUp demo fires three more
  shots.
- Each demo's page offers the steps to try, each with what to ask, the call and the reply it
  got. The whole run is in `TRANSCRIPT.md`.
- The README opens with what the server lets you ask, its lead demo moving at the page's width
  and one exchange of that demo's run. Its `## Install` section has the lines to paste for ten
  MCP clients and a first question to ask.
- Takes the scry-core release `pyproject.toml` pins.
- Each tool's reference entry opens with what the tool does and an example to try: what to
  ask, the call and the reply it got. Its arguments, what comes back, what it refuses and why
  follow, each under its own heading.
- The examples are calls of one session on Gridlee, a ROM mamedev.org distributes for free. The
  whole session is `docs/reference/tour/TRANSCRIPT.md`.
- The groups of tools have names that say what they hold: Run, Breakpoints, Sequences, Project
  and Timeline. The `instructions`, the reference's pages and the sections of `REFERENCE.md`
  carry them.
- A scan's summary says how many candidates are left ("3 left"). `drive`'s says "reaction
  seen", "no reaction seen (TIMEOUT)" or "sent, reaction not checked".
- A reply that saves a candidate for `promote` says "N saved for `promote`" in `kept`.
- `series_capture`'s `errorlog` holds the lines MAME wrote during the series and while its
  notifier was removed. It held only the second part.
- `series_capture` answers the stop the machine rests at, one step past its run's. It answered
  the run's stop, and the next call reported the step as a stop of the machine's own.
- The descriptions of `start` and `window` say what `front` means: on screen, with no other
  application's window over its centre. It does not mean the window has the keyboard.
- `palette`, `gfx_view`, `gfx_sweep`, `screen_signature`, the two screen-map tools and `trace`
  publish `watches`. Their replies carried it whenever a watch was declared, against their own
  schema.
- On Windows a `start` behind (`background=true`, or left out on an unwatched start) leaves the
  foreground where it was: no program may take it while the start launches. The flag did
  nothing there, and MAME's window took the caller's keyboard.
- `rompath` takes a `;`-separated list of directories, as `inipath` does, each checked on its
  own (`rompath[i]` in a refusal). A list was refused as one missing directory.
- A `start` profile's `rompath` and `inipath` resolve each of their `;`-separated folders
  against the base of the `.scry/` folder. Only the first was resolved, and `inipath` not at
  all.
- `run_to`'s `cut_by_other_stop` refusal spells `disarm_watches=true` as a client sends it.
- `promote` refuses a `start` profile or a `perform` document holding a `${...}` that is no
  placeholder, typed text included. It used to write a file that `perform(path=)` refused.
- A `perform` document the `.scry/` folder holds is replayed with its placeholders resolved,
  `${state}` naming the session's temporary folder. Its steps ran with `${root}` in their paths
  and were refused.
- `perform` and `drive` end a list at a `screen_wait` that ran out, as at a `log_wait`: the
  steps after it were built on a screen that never came.
- `close`, `run_for`, `disassemble` and `debug` carry the titles the tools of the same names
  carry on the other server (`run_for`'s now names the frames it takes). `screen_wait`'s schema
  publishes `every`'s bound of 0 to 600, which it refused before without saying so.
- `screen_wait` is listed under Run, where it runs the machine until its predicate holds. Its
  page moved from `docs/reference/screen.md` to `docs/reference/run.md`.
- `start`'s description says that `throttle_from_frame` runs at real speed after its frame. It also says
  that `background` brings either window to the front, watched or not, so neither reads as a
  reason for `shared`.
- On Windows, a `start` refused after it launched MAME (another process serving its
  `stub_port`, say) answers once that MAME is gone. It could answer while the process
  was still ending.
- On Windows, `close` answers a killed MAME it could not see gone as not reaped and leaves
  running the job that ends it. It reported the MAME reaped and stopped that job.
- On Windows, a `gfx_film` frame is checked even when a program holds the film's header open
  while MAME replaces it. The failed publication is counted once in the reply's callback errors
  and the header you read stays the last whole one until the next stop. The frame used to go
  unchecked.
- `screen_wait` under `on_breakpoint` or `on_watch` that runs out after firings says where it
  checked them. It says "was not found at the frame's end after any of N firings", where it
  said "was not found after any of".
- `start` refused for a `profile` no directory above holds carries `searched`, the directories
  it looked in, beside the message that already named them.
- A reply that wrote a file under another name than the `dest` you gave (`Shot_1.PNG` as
  `shot-1.png`) says so in its `note`; its path already named the file written.
- `comment_write(method="save")` names the file it replaced by the path it wrote. A save it
  refused over what is there names that path beside the `dest` you gave, where both quoted
  your spelling of a file that may not exist under it.
- On the Mac a window positioned to fit a display's usable area sees a Dock or menu bar that
  showed, hid or moved within a few seconds. It kept the first area it read for the life of the
  server.
- A map `screen_map_write` loaded names the entry it was read from. An `add` after the load
  updates that map in the `.scry/` folder it came from, as the `promote` description says. It
  was kept as a new map of the current `start`'s repository.
- `screen_wait`'s description gives `condition` a register of the stopped cpu, never a register
  this server refuses.
- `promote` writes an entry only into the `.scry/` folder of the repository it was learned in.
  That is the one a call read it from, else the one whose profile the current `start` read. A
  session that ran programs of two repositories never files one in the other's.
- A `start` that read no profile names no repository, so what it keeps takes `root`. An entry
  with no `.scry/` folder of its own is `unwritable` in a review, with its reason, and refused
  in an approval, naming the `root` to pass.
- The `kept` line of a `promote` names that `.scry/` folder. A call writes one folder; with
  `root`, a candidate kept in another repository says `from`.
- `record` whose run reaches its `seconds` bound releases the recording there and, when the
  release answers, answers its file (`ended: true`, `bytes`, `avi_frames`). It used to refuse
  `not_settled` and leave the file open.
- That `record` reply also carries the console's account (`thread_errors`, `console_reruns`,
  `resent`), as a run that settled says it. The description says what a bound does when its
  release answers.
- A `promote` that names `root` no longer fails when the working directory is gone.
- An approved `promote` into a repository with no `.scry/` also writes its `about.json` and
  `README.md`. `dry_run` lists what it would create in `would_create`, the approval says what it
  created in `created`. A reply that kept something for `promote` says when there is no `.scry/`
  above the project, and how to see what an approval would create.
- Offsets read as addresses do, in `0x` hex: `read_block`'s `offset`, the graphics tools' source
  `offset`, `machine_map`'s `region_offset` and ROM `offset`, `write`'s `region_offset`, and
  the offset of each operand `disassemble` resolves.
- On macOS the server reads the screens from a child process when it positions a window. It is
  no longer held as an application, so Activity Monitor cannot show it as not responding.
- `screen_wait` on `on_breakpoint` or `on_watch` answers the clocks its reply promises
  (`frame_before`, `frame_after`, `emulated_before_s`, `emulated_after_s`, `cycles`), which it
  left out, so a client that validates the reply refused it. `emulated_before_s`, like the
  other clocks, may be `unavailable` when the console reads no time.
- The demos arrive by the game's code: LineUp waits for each screen at the frame after the
  game's tick and reads each move once the game has taken it. A transcript hides what the
  host decides (the window, the log's byte positions, a compressed state's size).
- On Windows the LineUp recording matches `win32/music.wav`.
- `screen_wait` takes `on_breakpoint` or `on_watch`: the screen is checked only at the frame's
  end after a firing of that declared breakpoint or change watch, never by sampling. A
  `condition` filters the firings first.
- The reply of that `screen_wait` counts `firings` and `frames_examined` in place of `polls`;
  a row that never fires is `never_fired`. `perform_export` keeps such a wait as the same call,
  and `changed` waits for a mapped screen other than the one shown at the start.
- MAME's Lua counts the firings and stops the machine only on a picture this wait has not
  already rejected, so a firing costs no round trip.
- On Windows, `close` ends an emulator started through a launcher script together with the
  launcher, and removes the session's temporary folder, which stayed behind.
- The descriptions say that a start nobody watches has a small window run at full speed (`start`).
  They say that a `count` watch tallies writes by value and by writer (`watch_add`). They say
  that `gfx_sweep`'s `tag` is a memory region's or a share's.
- The files the server writes follow
  [one rule](https://github.com/scry-mcp/scry-core/blob/main/docs/file-names.md): lowercase
  words joined by hyphens and one extension. A file `dest` is written under its normalised name
  (`Dump.BIN` as `dump.bin`) and the reply's path names that file. One with no extension is
  refused, and a directory `dest` keeps its name.
- A state saved as `Boss_1` is `boss-1`, loaded by either spelling. A state or a screen map
  kept under an earlier spelling (`Boss_1.sta`, `<application>.screen-map.json`) is not found
  until its file is renamed; `state_list` says so.
- A trace's set file is `<name>-<extension>-set.jsonl`, a draft's report `<name>-report.json`.
  A screen map `<application>-screen-map.json`, the files of a list of steps `batch-<n>-ran.jsonl` and
  `batch-<n>-replies.jsonl`, and a failed start's copy `<utc stamp>-<system>.log` in lowercase.
- `record` refuses a `dest` that is not an `.avi` file: MAME adds `.avi` to any other name, and
  the reply named a file that was not the one written.
- Two tally, capture or palette-log ids that differ only in punctuation no longer share one
  file in the session's temporary folder. The file of an id on another cpu or in the I/O space carries a
  short digest after its words.
- `close` no longer names an entry the `.scry/` folder already holds as it is.
- `promote` no longer looks for the `.scry/` folder from the binary's folder.
- A count watch with `trigger_type` `r` or `rw` also counts reads, returned apart as `reads`.
- `promote`: a map or a script learned under a loaded start profile looks for the `.scry/`
  folder from that profile.
- `run_to` says when a condition the console rejects is why it never stopped.
- `perform` takes `path`: a `perform` document (`.scry/perform/<name>.json`, or a file
  `perform_export` wrote) whose steps are replayed on the session. `steps` and `path` are
  refused together, and a document whose version this server does not read is refused by name.
- `start` has no `fullscreen` argument, so it could only be refused. No supported host shows a
  full-screen window for MAME: `-nowindow` opens a window the display's work area holds, never
  the display.
- `status` with no session says `no session is live, so there is no stop to report` for
  `last_stop`, not that the session has not stopped yet.
- A control on the instruction a stop lands on is counted by MAME alone. The server no longer
  adds a hit of its own for each landing of a run by frames. That is exact on a MAME that
  evaluates the landing; on one that does not, such a control misses it, as the Breakpoints
  page says.
- `start`'s description names `session_live`, the code a second `start` gets while a session is
  up, and the README says how to watch a machine.
- `start` takes `size` (`WIDTHxHEIGHT` in the host's unit), which wins over the default. A
  watched window is now the largest whole multiple of the machine's screen that fits the
  display's usable area, menu bar, Dock and taskbar excluded. `window` checks a stated
  size and answers `size`.
- MAME draws the picture at its view's aspect inside that window and scales it by whole
  pixels, never blurred. The multiple is pixel-exact only where the view's aspect is the
  screen's. A size that is not a whole multiple is scaled by whole pixels, unevenly between the
  axes, and the `note` says so.
- `start` takes `display` (the OS's index, the main display when omitted), and a watched start
  answers `window`, proved in the host's window list. A window that never appears on the asked
  display is `window_not_visible`. `SCRY_EMULATOR_ARGS` is gone.
- A new tool, `window`, answers where the window is at any time, and with `front=true` brings it
  in front of what covers it. Without `front` it answers the window wherever you put it,
  another display included. A `front` that fails on a session started with `background=true`
  names that as what may keep it behind and what to do.
- `focus` is now `cpu_focus`: it moved the debugger's visible cpu, never the window, and a
  caller reading "focus" expected the window brought forward. The same name is the `op` of
  `perform` and `drive`.
- `start` takes `profile`: the name of a `.scry/start/<name>.json` a repository holds, or a
  path to one. Its keys are `start`'s own arguments and fill only what the call does not give,
  every path resolved against the directory holding `.scry/`.
- The reply's `profile` block names the file and what it filled, and an argument neither the
  call nor a profile gives is refused by name. `system`, `rompath` and `reference_rom` are
  optional now, so a profile can carry them.
- `machine_map` takes `dest`: every row of the sections read is written to that new file as
  JSON and the reply names it in `path`. A cut list with no `dest` says how to get every row.
- `read_memory`, `disassemble`, `find`, `memdump`, `scan` (its `start`) and `write` echo the
  caller's `ref` beside the `addr` it resolved to.
- `close` lists in its schema the `exit_code` it always answered: an integer, or
  unavailable with its `why`.
  `symbols_find`'s `linear`, `start`'s and `rom_check`'s `reference_addr` and `reference_base`,
  and the values of `bases` take an address as `0x` text or an integer, as every other address.
- `screen_wait`'s reply no longer lists `disarmed_watches` and `not_rearmed`, which only `run_to`
  and `run_for` send.
- A `lua` script that prints past 4000 characters and then raises keeps its text in a file, as an
  answer does, where the refusal carried it whole.

## 0.1.0

First release. It needs scry-core 0.80.0.

- A symbol name the table gives twice loads, and a lookup of it is refused as `ambiguous_ref`
  naming every address. `symbols_find` lists every row and keeps the map's own spelling; a tie on
  an address goes to the first row of the file.
- `regpoint_hit` carries the same common fields as the other server's (`ref`, `condition`, `pc`,
  and the note that the registerpoint stays armed), plus MAME's `cpu` and `index`.
- `status` with no session answers what survives the session; `close` with no session says so
  instead of inventing a pid; `state_dir` is the named folder, else the scratch one, in `start`
  and `status`.
- `trace` reads a file written with CR LF line ends, as MAME writes it on Windows.
- `comment_write(method="delete")` still deletes a comment kept by a name that has since become
  ambiguous; a capture trigger that is ambiguous is refused as `ambiguous_ref`.
- On Windows the server proves which process serves MAME's gdbstub from the system's TCP table, and
  a MAME outlives no server (a job object).
