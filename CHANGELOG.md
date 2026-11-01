# Changelog

What a client of the server notices.

## Unreleased

It needs the scry-core that serves `scry_core.window`, not the 0.80.0 this release was cut on.

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
