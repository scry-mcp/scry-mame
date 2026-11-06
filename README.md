<p align="center"><img src="docs/scry-logo.png" alt="Scry" width="480"></p>

# scry-mame

**Point an MCP client at an arcade board and ask the machine questions, live.** One MAME stays
open at its debugger; you ask what is in a register right now, who wrote this byte, when this
routine runs, what is on screen the instant the game says a scene is drawn, and every answer
says what it checked. A question costs a round trip over MAME's own gdbstub instead of a boot.

If you reverse-engineer or develop for a board under MAME you know the loop: boot, wait for the
attract screen, type one command into the debugger, read one number, quit. This server pays the
boot once and then answers, and it is built so that an autonomous session can be left alone
with it: a breakpoint that never fires is a measurement here, never a silence.

## What it can do

- **Hold a live machine open.** `start` boots your system with the debugger attached, proves the
  loaded ROM against your reference image, reads your symbol file and parks the machine
  stopped. Registers, memory, a disassembly, the driver's log, a screenshot: each is one call.
- **Start from your repository's recipe.** `start(profile=...)` takes the arguments a
  `.scry/start/` file declares, fills only what the call does not give, and names the file and
  what it filled in the reply.
- **Names, not addresses.** Load the linker's map or a YAML of names and say `Player1`, not
  `0x008400`; a class that lives in RAM is relocated the way the running board sees it.
- **Stop where you mean to, with a control beside it.** `run_to` counts a control breakpoint at
  a place known to be hot and refuses to run with none, so "the target never ran" is a verdict
  with evidence. Break on a value, on a byte that CHANGES (and be told who wrote it), or on a
  register reaching a value wherever that happens.
- **Find a variable no map names.** `scan(method="start")` and `scan(method="filter")` narrow every cell of a range
  to the ones that moved the way the variable did, without moving the machine.
- **Advance by emulated time.** `run_for` by milliseconds of MAME's clock or by frames of its
  counter, waiting until the machine has really stopped; `trace` hands back every address the
  cpu executed, joined to your symbols.
- **Press its inputs and prove it.** `input` presses a field by MAME's own names and reads the
  port back; `record` and `audio_record` write exactly N frames of video or sound.
- **A number before a picture.** `screen_signature` answers "did the image change?" with one
  string; the file tools compare PNGs, series and recordings with numbers and a control.
- **One call per turn.** `perform` runs a list of operations checked whole before the first
  runs; `drive` is look, act, verify in one round trip.
- **Every cpu on the board**, the way MAME's debugger has them: a call names its cpu, or acts on
  the visible one, and every reply that touches a cpu names it.
- **Honest replies.** Every reply opens with a one-line `summary` and closes with a `session`
  block saying whether anything was written to the machine. A session that cannot reproduce its
  ROM is refused before anybody measures on it.

## Two minutes to a first answer

You need git, Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), and a MAME built with the
gdbstub (`-debugger gdbstub`) and its `console` plugin. `start` runs the MAME its `binary`
argument names, else `MAME_BINARY`, else the `mame` on your `PATH`. The server is tested on one
MAME release, which `start` names in `recommended_release`; another release boots with a `note`
saying so. A board on a NEC V20/V30/V33 needs a
MAME from mamedev/mame#16131 on, where the stub learned their registers.

```sh
git clone https://github.com/scry-mcp/scry-mame
cd scry-mame
claude mcp add mame -s user -- uv run --directory "$PWD" scry-mame
```

Any other MCP client starts the same command over stdio:
`uv run --directory /path/to/scry-mame scry-mame`.

The quickest first answer is a demo on a free set: [`demos/starfire/`](demos/starfire/) has the
two commands that fetch and check its ROM, then `uv run python demos/starfire/demo.py --rompath
~/roms` runs it. For your own board, ask your client to `start` it with `binary`, `system` and
`rompath`, and, to prove the ROM and name your addresses, `reference_rom`, `reference_addr` and
`symbols` (the [`start` page](docs/reference/session.md#start) says what each takes). Everything
about your project comes from you; the server names no game and carries no default of its own.

To watch a machine, `start` takes `shared=true`, `display` (the OS's display index, 0 the main
display) and `size`, and proves the window is on the display you asked in the
host's window list, refusing by name (`window_not_visible`) when it is not. Somebody watching
through a stream (Moonlight) sees one display, so the window has to be on it, sized with `size`
when the fit is not what you want. The three situations (headless, a window kept behind, a window
somebody tests) are on [`start`'s page](docs/reference/session.md#start).

Three patches under `patches/`, each naming the MAME commit it was made against, make a build
better at this: `0003` closes a data race in the Lua console thread that can crash a boot
(proposed upstream as mamedev/mame#16229; without it `start` relaunches such a boot and lists it
in `start_retries`), `0004` serves one GDB thread per cpu, so any cpu's registers and memory read
without the machine running, and `0005` ends MAME with its own exit code on a fatal error under
the debugger (merged upstream as mamedev/mame#16363, so a MAME from it on carries it).

## Platforms

macOS and Windows: the server and its tests run on both. On Windows the server proves which
process serves MAME's gdbstub from the system's own TCP table instead of `lsof`, and a MAME
outlives no server: it runs in a job object the server holds, which Windows closes, ending MAME,
however the server ends. Linux runs the unit tests (`.github/workflows/ci.yml`) and nothing else:
the server supports macOS and Windows only.

## See it run

Two demos on free mamedev.org sets, each a `demo.py` that makes the calls a model would and
checks every answer. The calls and replies below are the last run's, written here by the demo
itself (`uv run python demos/<name>/demo.py --update-readme`), each cut to the fields that make
its point.

![Star Fire's attract screen, four coins in](demos/starfire/screen.png)

[`demos/starfire/`](demos/starfire/): Exidy's *Star Fire*, from a cold boot to the instruction
that counts its coins, and a saved state that takes one back.

<!-- demo-flow:begin starfire -->
```
start(system="starfire", reference_rom="/path/to/scry-mame/tmp/demos/starfire/starfire.ref", reference_addr="0x0", reference_base="0x0", inipath="/path/to/scry-mame/tmp/demos/starfire/starfire-ini", state_dir="/path/to/scry-mame/tmp/demos/starfire/starfire-states", boot_seconds=60, rompath="<host>")
-> {
  "rom_check": "OK",
  "pc": "0x00000000"
}
```

```
scan(method="start", ref="0x8000", length=1024)
-> {
  "summary": "scan start: 0x8000, 1024 1-byte candidates on :maincpu",
  "hits_total": 1024
}
```

```
perform(steps=[{"op": "input", "port": ":SYSTEM", "field": "Coin 1", "frames": 4, "seconds": 300}, {"op": "run_for", "milliseconds": 500, "seconds": 300}, {"op": "scan", "method": "filter", "operator": "=", "value": 3}], settle_seconds=300)
-> {
  "summary": "perform: 3 steps completed"
}
```

```
watch_add(ref="0x8299", mode="change", fmt="u8")
-> {
  "summary": "watch_add 0x8299: change watch armed at 0x00008299, 1 byte",
  "entry": "1 @ 8299-8299 write",
  "write_maps_to": "starfire_base_state::scratch_w"
}
```

```
input(port=":SYSTEM", field="Coin 1", frames=4, seconds=300)
-> {
  "summary": "input :SYSTEM 'Coin 1': still HELD from frame 284, releases at 288",
  "cause": "watch 0x8299: 0x00008299 written by pc 0x00001e48",
  "watch_hit": {
    "ref": "0x8299",
    "addr": "0x00008299",
    "cpu": ":maincpu",
    "index": 1,
    "writes_total": 1,
    "truncated": false,
    "writer_pc": "0x00001e48",
    "writes": [
      {"wrote": "0x04", "to": "0x00008299", "pc": "0x00001e48"}
    ],
    "values_from": "bus",
    "before": {
      "available": false,
      "why": "the first write logged since the watch was armed: no earlier write to compare"
    },
    "after": 4,
    "lines": ["Stopped at watchpoint 1 writing 04 to 8299 (PC=1E48)"]
  }
}
```

```
disassemble(ref="0x1e40", length=16)
-> {
  "summary": "disassemble 0x1e40: 9 lines at 0x00001e40",
  "lines": ["1E40: 2F       cpl", "1E41: E6 03    and  $03", "1E43: 28 BF    jr   z,$1E04", "1E45: 21 99 82 ld   hl,$8299", "1E48: 34       inc  (hl)", "1E49: 21 AF 82 ld   hl,$82AF", "... 3 more"]
}
```

```
state_write(method="save", name="four_credits")
-> {
  "summary": "state_write save: four_credits, 16860 bytes at frame 314",
  "frame": 314
}
```

```
state_write(method="load", name="four_credits")
-> {
  "summary": "state_write load: four_credits, rom_check OK, verified True, frame 314, pc 0x00002b38",
  "verified": true
}
```

```
read_memory(ref="0x8299", length=1)
-> {
  "summary": "read_memory 0x8299: 1 byte at 0x00008299: 04",
  "hex": "04"
}
```
<!-- demo-flow:end starfire -->

[`demos/gridlee/`](demos/gridlee/): Videa's *Gridlee*, where three bytes hold the same count and
write watches tell the credits from their BCD copy, then a START spends one.

<!-- demo-flow:begin gridlee -->
```
start(system="gridlee", reference_rom="/path/to/scry-mame/tmp/demos/gridlee/gridlee.ref", reference_addr="0xa000", reference_base="0xa000", inipath="/path/to/scry-mame/tmp/demos/gridlee/gridlee-ini", state_dir="/path/to/scry-mame/tmp/demos/gridlee/gridlee-states", boot_seconds=60, rompath="<host>")
-> {
  "rom_check": "OK",
  "pc": "0x0000f000"
}
```

```
perform(steps=[{"op": "input", "port": ":IN1", "field": "Coin 1", "frames": 4, "seconds": 300}, {"op": "run_for", "milliseconds": 2000, "seconds": 300}, {"op": "scan", "method": "filter", "operator": "=", "value": 3}], settle_seconds=300)
-> {
  "summary": "perform: 3 steps completed"
}
```

```
perform(steps=[{"op": "watch_add", "ref": "0x42b", "mode": "change", "fmt": "u8"}, {"op": "watch_add", "ref": "0x42c", "mode": "change", "fmt": "u8"}])
-> {
  "summary": "perform: 2 steps completed"
}
```

```
run_for(milliseconds=500, seconds=300)
-> {
  "summary": "run_for 500 ms: OTHER_STOP, frame 672 to 673",
  "watch_hit": {
    "ref": "0x42b",
    "addr": "0x0000042b",
    "cpu": ":maincpu",
    "index": 1,
    "writes_total": 1,
    "truncated": false,
    "writer_pc": "0x0000b583",
    "writes": [
      {"wrote": "0x04", "to": "0x0000042b", "pc": "0x0000b583"}
    ],
    "values_from": "memory",
    "before": 3,
    "after": 4,
    "lines": ["Stopped at watchpoint 1 writing 04 to 042B (PC=B583)"]
  }
}
```

```
run_for(milliseconds=500, seconds=300)
-> {
  "summary": "run_for 500 ms: OTHER_STOP, frame 673 to 673",
  "watch_hit": {
    "ref": "0x42c",
    "addr": "0x0000042c",
    "cpu": ":maincpu",
    "index": 2,
    "writes_total": 1,
    "truncated": false,
    "writer_pc": "0x0000b58c",
    "writes": [
      {"wrote": "0x04", "to": "0x0000042c", "pc": "0x0000b58c"}
    ],
    "values_from": "memory",
    "before": 3,
    "after": 4,
    "lines": ["Stopped at watchpoint 2 writing 04 to 042C (PC=B58C)"]
  }
}
```

```
read_memory(ref="0x42b", length=2)
-> {
  "summary": "read_memory 0x42b: 2 bytes at 0x0000042b: 0404",
  "hex": "0404"
}
```

```
input(port=":IN1", field="1 Player Start", frames=4, seconds=300)
-> {
  "summary": "input :IN1 '1 Player Start': still HELD from frame 702, releases at 706",
  "cause": "watch 0x42b: 0x0000042b written by pc 0x0000d676"
}
```

```
history(limit=8)
-> {
  "summary": "history: 8 instructions of 8 asked",
  "lines": ["D68D: RTS", "C5AD: JSR    $D676", "D676: DEC    $042B", "D679: LDA    #$99", "D67B: ADDA   $042C", "D67E: DAA", "... 2 more"]
}
```
<!-- demo-flow:end gridlee -->

[`demos/lineup/`](demos/lineup/) plays the arcade *LineUp* with the same script the DOSBox-X server
plays its PC port with: the routines and variables named off each build's own symbol map, every
screen recognised off one map signed by palette index, and the stage's music held, sample for
sample, to the board's own recording. It needs the game's romset, which is not distributed here.

## The tools

The tools by family, each with its arguments, its reply and a real example, are in the index
at the top of [REFERENCE.md](REFERENCE.md). A tool's own description, delivered to your client
at connection, is its contract.

## Going further

[REFERENCE.md](REFERENCE.md) holds what the families share (the session, what every reply
carries, names for addresses) and links each family's page, where every tool's block is
followed by why its contract is shaped that way. [CONTRIBUTING.md](CONTRIBUTING.md) is for
changing the server: its battery, its live tier and what proves a change.

What this server has in common with its sibling lives in [scry-core](https://github.com/scry-mcp/scry-core),
pinned by tag; its README lists every module.

## Licence

MIT. See `LICENSE`.

## Credits

Developed by Optimiza ([Marcos Hernández](https://www.linkedin.com/in/optimiza/)), in collaboration with [MS-DOS Club](https://msdos.club) and its [podcast](https://www.ivoox.com/podcast-ms-dos-club_sq_f11160693_1.html).
