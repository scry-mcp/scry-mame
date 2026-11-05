# Changelog

What a client of the server notices.

## Unreleased

It needs the scry-core that serves `scry_core.window`, not an older one: the tag pinned in `pyproject.toml` is the floor.

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
