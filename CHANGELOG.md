# Changelog

What a client of the server notices.

## Unreleased

- scry-core 0.112.0 pinned: the probe resolves `{tmp}` and `{anchor}` in a task file, so a
  task set spelled through them is judged the same on Windows as on the Mac.
- scry-core 0.111.2 pinned: the pre-commit hook starts the `jscpd.cmd` npm installs on Windows,
  so the hook's cases run there, and a FIFO the tests release is released for a reader that
  opens late too.
- A map `screen_map_write` loaded names the entry it was read from, so an `add` after the
  load updates that map in the store it came from, as the `promote` description says,
  where it was kept as a new map of the current `start`'s repository.
- `window`'s `front` is said as it is computed: on screen, with no other application's
  window over its centre.
- On the pinned scry-core (`pyproject.toml`), `screen_wait`'s description gives `condition`
  a register of the stopped cpu, never a register this server refuses.
- On the pinned scry-core (`pyproject.toml`), `promote` writes an entry only into the store of
  the repository it was learned in (the one whose store a call read it from, else the one whose
  profile the current `start` read), so a session that ran programs of two repositories never
  files one in the other's and the server's own directory never lends its store. A start that
  read no profile names no repository, so what it keeps takes `root`. An entry with no store
  of its own is `unwritable` in a review and refused in an approval, naming the `root` to pass;
  the `kept` line names it; a call writes one store; with `root`, a candidate kept in another
  repository says `from`.
- The demos ship a loop: each demo's `loop.mp4` sits beside its `screen.png`, recorded by the
  runner after the step that takes the still.
- On the pinned scry-core (`pyproject.toml`), which carries the window every demo asks of
  its `start`.

- On the pinned scry-core (`pyproject.toml`), whose demo runner fails a loop a bound or a
  stop cut.

- On the pinned scry-core (`pyproject.toml`), whose demo runner reports the stop that ends
  a loop as the host's too.

- On the pinned scry-core (`pyproject.toml`), whose demo runner reports a loop's own timing
  as the host's, so a demo's two runs give one transcript.

- On the pinned scry-core (`pyproject.toml`), whose demo runner takes `--display`, so a
  demo can be recorded on one of the host's own displays.

- On the pinned scry-core (`pyproject.toml`), which renders a repository's `.scry/README.md` from
  one template and holds the `record` text both servers answer.
- On the pinned scry-core (`pyproject.toml`), whose `record` words say what a bound does when its
  release answers, so a server that answers `ended: false` over a capture it could not turn off
  is not contradicted.
- On the pinned scry-core (`pyproject.toml`), whose demo runner records a demo's loop and
  converts it to its `loop.mp4` beside the capture.
- `record` whose run reaches its `seconds` bound releases the recording there and, when the
  release answers, answers its file (`ended: true`, `bytes`, `avi_frames`), where it used to
  refuse `not_settled` and leave the file open. That reply now also carries the console's
  account (`thread_errors`, `console_reruns`, `resent`), as a run that settled says it.
- A `promote` that names `root` no longer fails when the working directory is gone.
- An approved `promote` into a repository with no `.scry/` also writes its `about.json` and
  `README.md`: `dry_run` lists what it would create in `would_create`, the approval says what it
  created in `created`. A reply that kept something for `promote` says when there is no `.scry/`
  above the project, and how to see what an approval would create.
- Offsets read as addresses do, in `0x` hex: `read_block`'s `offset`, the graphics tools' source
  `offset`, `machine_map`'s `region_offset` and ROM `offset`, `write`'s `region_offset`, and
  the offset of each operand `disassemble` resolves.
- On macOS the server reads the screens from a child process when it places a window, so it is
  no longer held as an application and Activity Monitor cannot show it as not responding.
- `screen_wait` on `on_breakpoint` or `on_watch` answers the clocks its reply promises
  (`frame_before`, `frame_after`, `emulated_before_s`, `emulated_after_s`, `cycles`), which it
  left out, so a client that validates the reply refused it. `emulated_before_s`, like the
  other clocks, may be `unavailable` when the console reads no time.
- The demos arrive by the game's code: LineUp waits for each screen at the frame after the
  game's tick and reads each move once the game has taken it. A transcript hides what the
  host decides (the window, the log's byte positions, a compressed state's size), and the
  LineUp recording is held to `win32/music.wav` on Windows.
- `screen_wait` takes `on_breakpoint` or `on_watch`: the screen is judged only at the frame's
  end after a firing of that declared breakpoint or change watch, never by sampling, and a
  `condition` filters the firings first. The reply counts `firings` and `frames_examined` in
  place of `polls`; a row that never fires is `never_fired`, and `perform_export` keeps such a
  wait as the same call. `changed` waits for a mapped screen other than the one shown
  at the start.
  MAME's Lua counts the firings and stops the machine only on a picture this wait has not
  already rejected, so a firing costs no round trip.
- On Windows, `close` ends an emulator started through a launcher script together with the
  launcher, and removes the session's scratch folder, which stayed behind.
- The descriptions say that a start nobody watches has a small window run flat out (`start`),
  that a `count` watch tallies writes by value and by writer (`watch_add`), and that a sweep's
  `tag` is a memory region's or a share's (`gfx_sweep`).
- The files the server writes follow
  [one rule](https://github.com/scry-mcp/scry-core/blob/main/docs/file-names.md): lowercase
  words joined by hyphens and one extension. A file `dest` is written under its normalised name
  (`Dump.BIN` as `dump.bin`) and the reply's path names that file; one with no extension is
  refused, and a directory `dest` keeps its name. A state saved as `Boss_1` is `boss-1`, loaded
  by either spelling. A state or a screen map kept under an earlier spelling (`Boss_1.sta`,
  `<application>.screen-map.json`) is not found until its file is renamed; `state_list` says
  so. A trace's set file
  is `<name>-<extension>-set.jsonl`, a draft's report `<name>-report.json`, a screen map
  `<application>-screen-map.json`, a batch's files `batch-<n>-ran.jsonl` and
  `batch-<n>-replies.jsonl`, and a failed start's copy `<utc stamp>-<system>.log` in lowercase.
- `record` refuses a `dest` that is not an `.avi` file: MAME adds `.avi` to any other name, and
  the reply named a file that was not the one written.
- Two tally, capture or palette-log ids that differ only in punctuation no longer share one
  file in the scratch: the file of an id on another cpu or in the I/O space carries a short
  digest after its words.
- A `promote` review lists apart, in `unwritable` with its reason, each entry it cannot write,
  and shows the rest.
- `close` no longer names an entry the store already holds as it is.
- `promote` no longer looks for the store from the binary's folder.
- A count watch with `trigger_type` `r` or `rw` also counts reads, returned apart as `reads`.
- `promote`: a map or a script learned from a loaded recipe looks for the store from that
  recipe.
- `run_to` says when a condition the console rejects is why it never stopped.

It needs the scry-core that serves `scry_core.window`, `recording.read_document` and
`recording.steps_to_replay`, not an older one: the tag pinned in `pyproject.toml` is the
floor.

- `perform` takes `path`: a `perform` document (`.scry/perform/<name>.json`, or a file
  `perform_export` wrote) whose steps are replayed on the session; `steps` and `path` are
  refused together, and a document whose version this server does not read is refused by
  name.
- `start` has no `fullscreen` argument: no supported host shows a full-screen window for MAME (`-nowindow` opens a
  window the display's work area holds, never the display), so it could only be refused.
- `status` with no session says `no session is live, so there is no stop to report` for `last_stop`, not that the
  session has not stopped yet.
- A control on the instruction a stop lands on is counted by MAME alone: the server no longer adds a hit of its own
  for each landing of a run by frames. That is exact on a MAME that evaluates the landing (mamedev/mame#16435); on one
  that does not, such a control misses the landing, as the `declare` page says.
- `start`'s description names `session_live`, the code a second `start` gets while a session is up, and the README
  says how to watch a machine.
- `start` takes `size` (`WIDTHxHEIGHT` in the host's unit), which wins over the default: a watched window
  is now the largest whole multiple of the machine's screen that fits the display's usable area
  (menu bar, Dock and taskbar excluded), not a fixed bound, and `window` judges a stated size and
  answers `size`. MAME draws the picture at its view's aspect inside that window and scales it by
  whole pixels, never blurred, so the multiple is pixel-exact only where the view's aspect is the
  screen's. A size that is not a whole multiple is scaled by whole pixels, unevenly between the
  axes, and the `note` says so.
- `start` takes `display` (the OS's index, the main display when omitted), and a watched start
  answers `window`, proved in the host's window list; a window that never appears on the asked
  display is `window_not_visible`. `SCRY_EMULATOR_ARGS` is gone.
- A new tool, `window`, answers where the window is at any time, and with `front=true` brings it
  in front of what covers it. Without `front` it answers the window
  wherever the owner put it, another display included. A `front` that fails on a session
  started with `background=true` names that as what may keep it behind and what to do.
- `focus` is now `cpu_focus`: it moved the debugger's visible cpu, never the window, and a caller
  reading "focus" expected the window brought forward. The same name is the `op` of `perform` and
  `drive`.
- The cases that move the owner's Space carry the `window` marker and are out of every default run.
- `start` takes `profile`: the name of a `.scry/start/<name>.json` a repository declares, or a
  path to one. Its keys are `start`'s own arguments and fill only what the call does not give,
  every path resolved against the directory holding `.scry/`; the reply's `profile` block names
  the file and what it filled, and an argument neither the call nor a profile gives is refused
  by name. `system`, `rompath` and `reference_rom` are optional now, so a profile can carry them.

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
