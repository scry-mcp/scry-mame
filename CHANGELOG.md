# Changelog

What a client of the server notices.

## Unreleased

- `screen_wait` on `on_breakpoint` or `on_watch` answers the clocks its reply promises
  (`frame_before`, `frame_after`, `emulated_before_s`, `emulated_after_s`, `cycles`), which it
  left out, so a client that validates the reply refused it. `emulated_before_s`, like the
  other clocks, may be `unavailable` when the console reads no time.
- The demos arrive by the game's code: LineUp waits for each screen at the frame after the
  game's tick and reads each move once the game has taken it. A transcript hides what the
  host decides (the window, the log's byte positions, a compressed state's size), and the
  LineUp recording is held to `music-win32.wav` on Windows.
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
  answers `size`. MAME draws the picture at its view's aspect inside that window, so the multiple
  is pixel-exact only where the view's aspect is the screen's. A size that is not a whole multiple
  is stretched by a fraction, and the `note` says so.
- `start` takes `display` (the OS's index, the main display when omitted) and `fullscreen`, and a
  watched start answers `window`, proved in the host's window list; a window that never appears on
  the asked display is `window_not_visible`. `SCRY_EMULATOR_ARGS` is gone. `fullscreen` is refused on
  macOS and Windows, where MAME's `-nowindow` opens a window the display's work area holds, never
  the display.
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
