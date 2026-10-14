# scry-mame

**Point an MCP client at an arcade board and ask the machine questions, live.** One MAME
stays open at its debugger; you ask what is in a register right now, who wrote this byte,
when this routine runs, what is on screen the instant the game says a scene is drawn, and
every answer says what it checked. A question costs a round trip over MAME's own gdbstub
instead of a boot.

If you reverse-engineer or develop for an arcade board under MAME you know the loop: boot,
wait for the attract screen, type one command into the debugger, read one number, quit. Two
questions are two boots. This server pays that cost once and then answers, and it is built
so that an autonomous session can be left alone with it: a breakpoint that never fires is a
measurement here, never a silence.

## What it can do

- **Hold a live machine open and answer from it.** `start` boots your system with the
  debugger attached, proves the loaded ROM against your reference image, reads your symbol
  file and parks the machine stopped, ready. Registers, memory, a disassembly, the driver's
  own log, a screenshot: each one is a call.
- **Names, not addresses.** Load the linker's own map or a YAML of `addr`/`name` pairs and
  say `Player1`, not `0x008400`. A class that lives in RAM is relocated the way the running
  board sees it (`bases={"DATA": "0x400"}`), so a symbol of any class reads at its live address.
- **Stop where you mean to, with a control beside it.** `run_to` a routine by name counts a
  control breakpoint you declared at a place known to be hot (or declares one with `control=`),
  reports how many times it fired, and refuses to run with none, so "the target never ran" is
  a verdict with evidence. Break when a variable reads a value.
  Break when a byte CHANGES and be told who wrote it, from which pc, with the value before
  and after. Break when a REGISTER reaches a value, wherever in the program that happens.
- **Name what you learned at an address.** Comments that follow a symbol through a rebuild,
  kept per project and in a file your repository versions, and shown in MAME's own disassembly.
- **Find a variable no map names.** `scan_start` takes every byte, word or dword of a range
  as a candidate and `scan_filter` keeps the cells that moved the way the variable did (`!`
  changed, `>` grew, `=` a value) until a handful are left, without moving the machine.
- **Advance by emulated time.** `run_for` by milliseconds of MAME's own clock or by frames
  of its counter, waiting until the machine has really stopped, so a goldens run is one call:
  a marker, N frames, a snapshot.
- **See what ran.** `trace` runs like `run_for` with MAME's own tracer on and hands back every
  address the cpu executed, joined to your symbols, with the whole file beside it.
- **Read the program's own account.** `log` and `log_wait` filter MAME's `error.log` and the
  process's stdout in the server, so a chatty driver costs a pattern and a limit, never a
  haystack.
- **Press its inputs and prove it.** `input` presses a field by MAME's own names (`:P1`,
  `Coin 1`), holds it for N frames and reads the port back. `record` writes an AVI of exactly
  N frames; `audio_record` writes the sound of N frames as a WAV, its levels in the reply;
  `screen_signature` folds the screen into one number so "did the image change?" costs no PNG;
  `throttle` switches real speed at a place.
- **One call per turn, not one per step.** `perform` runs a list of operations, checked whole
  before the first runs, stopping at the first failure with the account; `drive` is LOOK,
  ACT, VERIFY in one round trip against the emulator log.
- **Every cpu on the board, the way MAME's debugger has them.** A call with no `cpu` acts on
  the debugger's visible cpu, which every stop moves to the cpu that stopped; a call with
  `cpu="subcpu"` acts on that one and, `step` aside, moves nothing, and every reply that
  touches a cpu names it. Each cpu takes its own symbol file, and a breakpoint or a watch keeps
  its cpu across a restart. With the gdbstub patch below, another cpu's registers and memory
  read through its own thread, `focus` shows another cpu without running, and a `perform` list
  whose steps alternate cpus leaves the visible cpu where it found it. `cpu_info` says what the
  debugger sees of each cpu, one row each, without moving the machine. MAME's `rpset` names no cpu,
  so a registerpoint is the visible cpu's.
- **Honest replies, by construction.** Every reply opens with a one-line `summary` and closes
  with a `session` block carrying `altered` (has anything here written to the machine?). A
  session that cannot reproduce its ROM is refused and killed before anybody measures on it.
  A reader never answers from a running machine. A file it hands back was checked first.

## Two minutes to a first answer

You need a MAME build with the gdbstub (any recent one; `-debugger gdbstub` is the tell; the
stock stub stops MAME at start when the machine's FIRST cpu is not one its register maps
cover), its `console` plugin (`plugins/console` beside the binary, or `share/mame/plugins/console` under
the prefix of a packaged MAME), the ROM set of the system you debug, and
Python 3.11 or newer. No external `gdb` is involved: the remote protocol is plain text over
TCP and the client is stdlib only. One family of cpus needs a recent enough MAME: the stub's
register map for the NEC V20/V30/V33 and their relatives is in MAME from mamedev/mame#16131
on, so a board on one of those needs a MAME that includes it. And MAME's Lua console thread can
crash a boot (a data race on its one Lua state): `patches/0003-lua-thread-context-race.patch` is
the fix, proposed upstream as mamedev/mame#16229. A MAME built without it (an upstream build, a
packaged one) may lose a boot to that race, which `start` relaunches and lists in
`start_retries`, and every reply's `session.console` counts the console reader's deaths and the
chunks it ran again (`thread_errors`, `reruns`); the builds this server is tested against carry
it.
Beside it, `patches/0004-gdbstub-one-thread-per-cpu.patch` makes the stub serve one GDB thread
per cpu, so a client can read the registers and memory of any cpu on the board, and switch the
visible cpu, without letting the machine run. `patches/0005-debugger-fatal-exit-live-cpu.patch`
makes a fatal error raised under the debugger end MAME with its own exit code instead of a crash.

```sh
pip install .
claude mcp add mame -s user -- scry-mame
# or, from a checkout without installing:
claude mcp add mame -s user -- uv run --directory /path/to/scry-mame python server.py
```

Then, from the client:

```
start(binary="/path/to/mame", system="myboard", rompath="/path/to/proj/roms",
      reference_rom="/path/to/proj/build/game.bin", reference_addr="0x30000",
      symbols="/path/to/proj/build/game.map", bases={"DATA": "0x400", "TILES": "rom"})
-> {"summary": "start myboard: rom_check OK, 305 symbols, pc 0x000ffff0", "status": "ok",
    "rom_check": "OK", "symbols_total": 305,
    "symbols_by_class": {"DATA": 43, "CODE": 201, "TILES": 61},
    "pc": "0x000ffff0", ..., "session": {"alive": true, "altered": false, "altering_writes": 0}}
rom_check(reference_rom="/path/to/proj/build/game.bin", reference_addr="0x30000")
-> {"rom_check": "OK", "deterministic": true, ...}
registers()                   -> every register at its cpu's declared width
close()                       -> {"closed": true, "ended_by": "quit", ...}
```

Everything about *your* project comes from you: the binary, the system, the ROM paths, the
reference image, the symbol file, where a window goes. The server names no game and carries
no default that points anywhere. The same server serves a 68000 board and a V30 one.

## Examples

Every example below was run against a real board. Replies are abridged to the fields that
matter; the tools' own descriptions list the rest.

### Run to a routine by name, with the control that makes silence a measurement

```
run_to(ref="Next_Frame", control="Start_Machine_Code")
-> {"summary": "run_to Next_Frame: TARGET, control counted 1", "status": "ok",
    "verdict": "TARGET", "control_hits": 1, "pc": "0x00031883",
    "regs": {"EAX": "0x0000", "EBX": "0x2584", "ESP": "0x99d2", "EIP": "0x1883",
             "CS": "0x3000", "DS": "0x0040", ...},
    "session": {"alive": true, "altered": false, "altering_writes": 0}}
```

A `run_to` that timed out with no control counted is `INVALID` (`control_silent`) and still
surveys the stop it left, with each control's `dasm` and a note on choosing one: the
several mistakes that leave a MAME breakpoint silent all look like "that routine is never
called", and the control is what tells them apart.

### Read a symbol at the address the running board uses

```
read_memory(ref="Player1", length=16)
-> {"summary": "read_memory Player1: 16 bytes at 0x00008400: 01000300010000000300000000000000",
    "status": "ok", "addr": "0x00008400", "length": 16,
    "hex": "01000300010000000300000000000000",
    "session": {"alive": true, "altered": false, "altering_writes": 0}}
```

`Player1` is a DATA symbol: the map's own address for it is the ROM copy of its initial
value, which reads plausibly and is wrong. `bases` is what places it in RAM, and a class
with no base refuses the start rather than loading an image address in silence.

### Who wrote this byte

```
watch_add(ref="Scene", mode="change", length=1)
-> {"stored": true, "armed": true, "state": "armed", ...}
resume(seconds=10)
-> {"summary": "resume: OTHER_STOP at pc 0x000312f4 (watch Scene: 0x000084a2 written by pc 0x000312f0)",
    "status": "ok", "verdict": "OTHER_STOP", "how": "watch Scene: 0x000084a2 written by pc 0x000312f0",
    "watch_hit": {"ref": "Scene", "writer_pc": "0x000312f0", "before": 1, "after": 2,
                  "writes": [{"wrote": "0x02", "to": "0x000084a2", "pc": "0x000312f0"}], ...},
    "pc": "0x000312f4", "frame": 1841, ...}
```

The stop lands on the instruction AFTER the writer, and the writer's pc, the value and the
bytes before and after come off the debugger's own log. A watch on the ROM copy of a datum
is refused before it is armed, because the stub would take it and it could never fire.

### Who puts this value in this register

```
regpoint_add(condition="d1==7fff")
-> {"summary": "regpoint_add d1==7fff: armed, index 1", "status": "ok", "ref": "d1==7fff",
    "condition": "d1==7fff", "stored": true, "armed": true, "entry": "1 if d1==7fff",
    "index": 1, "cpu": ":maincpu", ...}
resume(seconds=5)
-> {"summary": "resume: OTHER_STOP at pc 0x000f2234 (registerpoint 'd1==7fff')", "status": "ok",
    "verdict": "OTHER_STOP", "how": "registerpoint 'd1==7fff'",
    "regpoint_hit": {"ref": "d1==7fff", "cpu": ":maincpu", "condition": "d1==7fff", "index": 1,
                     "pc": "0x000f2234", "note": "still armed: ..."},
    "regs": {"D1": "0x00007fff", ...}, ...}
regpoint_clear(ref="d1==7fff")
-> {"summary": "regpoint_clear d1==7fff: 1 cleared, 1 disarmed", "status": "ok",
    "declarations_cleared": 1, "disarmed": ["1 if d1==7fff"], ...}
```

A breakpoint needs an address and this needs none: the machine stops at whatever instruction
leaves the register holding the value. It stays armed after the hit and fires again one
instruction on while the condition holds, so clear it before advancing past it.

### A goldens run in one call

```
perform(steps=[{"op": "breakpoint_at", "ref": "Scene_Drawn", "role": "control"},
               {"op": "run_to", "ref": "Attract_Start"},
               {"op": "run_for", "frames": 120},
               {"op": "snapshot", "dest": "/path/to/proj/goldens/attract_120.png"}])
-> {"summary": "perform: 4 steps completed", "status": "ok", "steps_completed": 4, "failed_at": {"available": false, ...},
    "ran": [..., {"op": "snapshot", "reply": {"path": ".../attract_120.png", "bytes": 18211,
                                              "sha256": "3f9c...", ...}}], ...}
```

The whole list is checked before the first step runs: a wrong operation, a misspelt argument
or a value a tool would refuse on its own comes back as one `INVALID` naming every bad step,
with nothing run. `run_for` by `frames` counts the frame counter itself, one tick per frame,
because N milliseconds is not N frames.

### Two cpus in one call

```
start(..., symbols={":maincpu": ".../symbols_maincpu.yaml", ":subcpu": ".../symbols_subcpu.yaml"})
-> {"symbols_by_cpu": {":maincpu": 64, ":subcpu": 43}, ...}
perform(steps=[{"op": "breakpoint_at", "ref": "snd_reset", "cpu": "subcpu"},
               {"op": "breakpoint_at", "ref": "0x4a0", "role": "control"},
               {"op": "run_to", "ref": "irq_vblank"},
               {"op": "registers"},
               {"op": "registers", "cpu": "subcpu"}])
-> {"summary": "perform: 5 steps completed", "status": "ok", "steps_completed": 5,
    "ran": [{"op": "breakpoint_at", "cpu": ":subcpu",
             "reply": {"summary": "breakpoint_at snd_reset: armed at 0x00000400", ...}},
            {"op": "breakpoint_at", "cpu": ":maincpu",
             "reply": {"summary": "breakpoint_at 0x4a0: armed at 0x000004a0", ...}},
            {"op": "run_to", "cpu": ":maincpu",
             "reply": {"summary": "run_to irq_vblank: TARGET, control counted 1", ...}},
            {"op": "registers", "cpu": ":maincpu", "reply": {"regs": {"PC": "0x00000400", ...}}},
            {"op": "registers", "cpu": ":subcpu", "reply": {"regs": {"PC": "0x00000542", ...}}}],
    "visible_cpu": ":maincpu",
    "visible_cpu_kept": {"before": ":maincpu", "after": ":maincpu", "restored": false}, ...}
```

`snd_reset` resolves in the sub cpu's table, at the same address as the main cpu's
`irq_vblank`, and the two are different places. Both registers are read at one instant, each
through its own thread of the patched stub, and nothing ran between them. The control counts
on the main cpu, the target's: a control on another cpu fires while the target's cpu sits in
reset, so `run_to` counts only the controls on the target's cpu and refuses to run without
one. A stop on the sub cpu inside a list makes it the visible cpu, as MAME does, and at the
end the list puts back the one it found: `visible_cpu` is the tag after the list, and
`visible_cpu_kept` says how (`"restored": true`, with `moved_to`).

### Did the screen change, without a PNG

```
screen_signature(grid=8)
-> {"signature": 2837384238, "frame": 2210, "grid": 8, ...}
run_for(frames=1)
screen_signature(grid=8)
-> {"signature": 2837384238, ...}          the same number: nothing on screen moved
```

### Fly to a late scene, then measure at real speed

```
start(..., throttle_from_frame=9000)
resume()
log_wait(pattern="MAME_MCP throttled from frame", channel="emulator", seconds=60)
-> {"verdict": "TARGET", "already": false, "waited_s": 4.8, "line": "MAME_MCP throttled from frame 9000", ...}
close()
-> {"closed": true, "ended_by": "quit", "average_speed": {"percent": 99.6, "emulated_s": 30.0, "wall_s": 30.12}, ...}
```

The trip to frame 9000 runs unthrottled, the throttle comes on at the frame, `log_wait`
proves the arrival, and `close` reports the host's speed over the real-speed window alone.

### From an unknown board to a gfx.yaml draft

Circus (a free set from mamedev.org), knowing nothing of its driver: which format are its
sprites in, and which bytes place the clown?

```
run_for(frames=600)
gfx_sweep(tag="gfx2", planes=[1], sizes=[[16, 16]], count=16)
-> {"summary": "gfx_sweep region :gfx2: sweep 1, 3 candidates s1c1..s1c3, 3 drawn; ...",
    "candidates": [{"id": "s1c1", "what": "1bpp 16x16 rows", ...},
                   {"id": "s1c2", "what": "1bpp 16x16 cells across", ...},
                   {"id": "s1c3", "what": "1bpp 16x16 cells down", ...}], ...}
watch_add(ref="0x0", mode="capture", length=64, trigger="0x2000", by="address")
watch_add(ref="0x4080", mode="capture", length=64, trigger="0x2000", by="address")    a control
run_for(frames=7), then gfx_locate, many times, until one answer holds a single match:
gfx_locate(layouts=["s1c3"], patch=[0, 0, 248, 256], tag="gfx2")
-> {"summary": "gfx_locate region :gfx2 for patch [0, 0, 248, 256]: 1 match, ...",
    "matches": [{"layout": "s1c3", "window": [141, 127], "tile": 5, "flip": "none",
                 "ambiguous": false, ...}], "frame_screen": 894}
gfx_draft(dest="<dir>/circus-gfx.yaml")
-> {"summary": "gfx_draft <dir>/circus-gfx.yaml: 1 format (1 proved), ...; 2 not proved",
    "formats": {"tiles_16x16x1": "proved"}, "asset_names": ["gfx2"],
    "command_fields": {"write_2000": ["dest_x", "dest_y", "height", "width"]},
    "not_proved": ["write_2000: source_tile holds only at lag [0], ...",
                   "capture 4080_64_t2000 against gfx2: no lag at which both ...", ...]}
gfx_load(path="<dir>/circus-gfx.yaml")
gfx_blits(draw_command="write_2000", detail=True)
-> {"summary": "gfx_blits write_2000 frame 893: 1 blit by 1 writer; ...",
    "blits": [{"pc": "0x000012ef", "screen": [[141, 127, 16, 16]],
               "fields": {"dest_x": 141, "dest_y": 127, "width": 16, "height": 16}, ...}]}
```

The sweep draws each candidate layout of `gfx2` beside the others; the one whose cells look
like sprites is named by its label, and `gfx_locate` finds the clown under it alone. The
captures keep a block at every write to port `0x2000`, and the draft pairs their rows with the
located clown frame by frame: in RAM `0x00..0x3f`, byte 10 gives the clown's screen x as
`240 - byte` and byte 11 its screen y as `239 - byte`, one frame late (the lag the report
names), while the control block explains nothing and says so. Loaded back, the draft boxes the
clown where `gfx_locate` found it. What the evidence could not settle is listed in
`not_proved`, never written as a guess.

### Decode at the write that matters

A V30 board whose background is a framebuffer at `0x10000`, one byte a pixel, 320 a line.
Stop where the map says the video interrupt runs, then decode that window and read the screen
at the same stop:

```
FB = {"width": 320, "height": 204, "planes": 8, "planeoffset": "{ 0, 1, 2, 3, 4, 5, 6, 7 }",
      "xoffset": "{ STEP256(0,8), STEP64(2048,8) }",
      "yoffset": "{ STEP128(0,2560), STEP64(327680,2560), STEP8(491520,2560), STEP4(512000,2560) }",
      "charincrement": "320*204*8"}
run_to(ref="New_IRQ_Video", control="Next_Frame")
-> {"summary": "run_to New_IRQ_Video: TARGET, control counted 0", "status": "ok",
    "verdict": "TARGET", "pc": "0x000300ad", "frame": 601, ...}
perform(steps=[...,
  {"op": "gfx_view", "ref": "0x10000", "layout": FB, "palette": "palette", "count": 1, "scale": 1},
  {"op": "gfx_view", "ref": "0x10001", "layout": FB, "palette": "palette", "count": 1, "scale": 1},
  {"op": "screen_view", "mode": "render", "scale": 1}, ...])
-> {"summary": "perform: 9 steps completed", "status": "ok", "failed_at": {"available": false, ...},
    "ran": [...,
      {"op": "gfx_view", "reply": {"summary": "gfx_view space program: tiles 0..0 of 1,
         320x204x8, palette :palette; 320x204 PNG x1, inline", "addr": "0x00010000",
         "real_colors": true, "pc": "0x000300ae", "evaluated_by": "one step",
         "image": {"width": 320, "height": 204, "indexed": true, "sha256": "fe1a5dc2...", ...}}},
      {"op": "gfx_view", "reply": {..., "addr": "0x00010001",
         "image": {..., "sha256": "557f7139...", ...}}},
      {"op": "screen_view", "reply": {"summary": "screen_view render :screen frame 601 from
         indices; 320x204 PNG x1, inline", "pc": "0x000300b0",
         "image": {"width": 320, "height": 204, "indexed": true, "sha256": "fe1a5dc2...", ...}}},
      ...]}
```

`FB` is one 320x204 tile in MAME's own `gfx_layout` terms. On this still screen, at `pen_base`
0, the window and the screen read a step apart are the same indexed PNG byte for byte, pens
included; one byte to the right they are not. Where the bytes or the pens change within a
frame, the stop goes at that write instead (REFERENCE.md, Which instant a decode shows).

## The tools

Everything about *your* project comes from you: the binary, the system, the ROM paths, the
reference image, the symbol file, where a window goes. The server knows no project and
carries no default that points anywhere in particular.

| tool | what it does |
|---|---|
| `start` | boots the system with the debugger attached, proves the ROM against the reference image, reads the symbol file (one per cpu when given a mapping), re-arms what the declaration store held, each declaration on its own cpu, and parks the machine stopped; refused while a session is live; a boot that dies by a signal (an assertion's abort, or a first cpu the stub cannot describe, excepted) or meets a stub not ready is launched again, boundedly, each attempt launched again in `start_retries` |
| `status` | is it up, is it running, where it last stopped, what it has written, what its files are, which cpus there are |
| `close` | ends it, asking MAME to quit through its console before it ever kills, so `cfg/` and `nvram/` get written; says which ending it got (`ended_by`) and the host's `average_speed` over the last run |
| `rom_check` | a known-answer read of the reference image's first bytes on the STOPPED machine |
| `focus` | makes another cpu the debugger's visible one and reads it back: through the gdbstub's thread patch, proving nothing ran; without it, through the console's own `focus`, whose ignored cpus and run it reports |
| `cpu_info` | what the debugger sees of each cpu at the call, moving nothing: which cpu is visible, which are ignored or suspended, each program counter, and what is declared on each |
| `perform` | a LIST of the server's own operations, checked WHOLE before the first step runs (every refused step listed, a cpu the machine lacks included, nothing run) and then run in order, stopping at the first failure; each step names the cpu it touched, and the visible cpu is put back at the end; `summaries=True` keeps each step's summary line and the last step whole, and `until_frame=F` repeats the list until a stop reads frame F |
| `drive` | LOOK, ACT, VERIFY in one call: mark the emulator log, run the act as `perform` runs it (`summaries` included), wait for the expected line (`TARGET`, or `TIMEOUT` at its bound), hand back what landed since |
| `run_to` | run to a `ref` on `cpu` (the visible one by default) with a CONTROL on that cpu counted beside it; `TARGET`, `TIMEOUT` or `OTHER_STOP`, and `INVALID` (`control_silent`) when a timeout counted no control; takes a `condition` in the console's own grammar |
| `run_for` | advance by emulated `milliseconds` or by `frames` of the frame counter, waiting until the machine has really stopped; `cycles` is the exact clock behind it (unavailable, with why, right after a load, a rewind or a typed reset); a board with no frame counter (a vector display) runs by milliseconds only |
| `trace` | `run_for` with MAME's tracer on one cpu: the executed addresses as a set joined to the symbols, a per-symbol summary, the trace file and the set file, checked before their paths are given |
| `step` | `count` instructions of `cpu`, `into` through the stub or `over` through the console, each step confirmed on the program counter; MAME runs the other cpus meanwhile, and `others` says how far each moved |
| `resume` | let the machine RUN, with no deadline or with `seconds`: `OTHER_STOP` when a stop came, `TIMEOUT` when the bound left it running |
| `stop` | interrupt a running machine where it is and survey the stop |
| `breakpoint_at` | a breakpoint by symbol or address, stored as a declaration that survives a rebuild; `role="control"` makes it a counter MAME never halts on; `condition` makes it a value-conditioned stop |
| `breakpoint_list` | every declaration with its state, read back against MAME's own `bplist` |
| `breakpoint_clear` | one declaration by ref, or all with `all=True`; never touches watches or registerpoints |
| `regpoint_add` | a stop when a `condition` over the registers comes true, wherever in the program that happens (MAME's `rpset`, which names no cpu, so on the visible one); stored and re-armed like a breakpoint, and evaluated once before it is armed |
| `regpoint_list` | every registerpoint declaration with its state, read back against MAME's own `rplist` |
| `regpoint_clear` | one registerpoint by ref, or all with `all=True`; never touches breakpoints or watches |
| `comment_add` | a text on a `ref` of a cpu, by symbol (it follows the symbol through a rebuild) or by address, stored as a declaration and shown at the end of that line in MAME's own disassembly; one comment per place, so a second replaces the text |
| `comment_list` | every comment with its state (`armed` in the pane, `unarmable` with why, `unresolved`, `stale`), answered from the store while the machine runs too |
| `comment_delete` | the comment at the place a `ref` names, however it was spelled, from the store and the pane |
| `comment_save` | every comment to a file your repository can version beside its map: one tab-separated line each, sorted, replacing only a file of its own format |
| `comment_load` | a comment file into the store and the pane, all or nothing; the file wins where both comment one place |
| `watch_add` | `length` bytes at a `ref` as a FORMAT of the value grammar: `show` on every stop, `expr` (any expression the debugger evaluates), `change`, a write watchpoint whose stop names who wrote the byte (with a `condition` on the value written, `wpdata`, it stops only on the writes it holds for), `count`, a write tap that tallies every write over a pass by value and by writer pc without stopping, or `capture`, the same tap on a `trigger`, one row per write to it holding the whole block then, or per read of it (`trigger_type="r"`) holding the value read, each row stamped with its frame, beam line and emulated time, so two cpus' rows order by one clock; a `ref` through a pointer (`[base]+8`, `base->field`) follows it at every stop |
| `watch_list` | the watch declarations and their state, read back against `wplist` |
| `watch_clear` | one watch by ref (an io tap's with `space="io"`), or all with `all=True`; never touches breakpoints or registerpoints |
| `read_memory` | `length` bytes at a `ref`, at the address the running board uses |
| `read_block` | `length` bytes of a memory SHARE or REGION by MAME's `tag`, or by the `ref` whose map entry names it: the values of a write-only block, which `read_memory` answers as zeros |
| `registers` | every register of `cpu` at its declared width, with a `register_bits` map |
| `disassemble` | MAME's own lines at a `ref`, each classed as a `call`, a `branch`, a `return` or `sequential` by the cpu type's mnemonic table, every direct memory operand resolved under the class bases |
| `find` | every address in a range, or in a symbol class (`symbol_class`), holding the bytes; names the `span` it examined |
| `scan_start` | open a value scan over `length` bytes at a `ref` of `cpu`, in cells of `cell_bytes` (1, 2 or 4), every cell a candidate |
| `scan_filter` | keep the cells whose value satisfies `operator` against `value`, or against what each held when the scan opened; listed when few enough; none left closes the scan |
| `scan_clear` | drop the open scan |
| `history` | the last `limit` instructions executed, the console's own trail |
| `symbols_find` | a name in the table of `cpu`, or which symbol a runtime address is inside, and what the address IS to the machine (`ram`, `rom`, `latch`, `unmapped`) |
| `machine_map` | what the machine IS, not what is on it: its cpus with their clocks and spaces, every address map entry and the share or region it names, the blocks by tag and size, the screens, the ROM files with their crc. Cached at `start`, so it costs nothing and answers the same every time; every section names the source that backs it |
| `write` | bytes at a `ref`, READ BACK (`readback`, `verified`); the session is altered for good. On ROM it goes nowhere and names the region behind it; `region=True` patches that region live, in its own byte order |
| `set_register` | a register forced and read back; a 16-bit register answers to its short name too |
| `reset` | the soft reset, applied and read back against the boot pc; a hard reset is refused |
| `memdump` | `(ref, length, dest)`: memory to a **file** through the console's own `save`, checked against a protocol read before the path is given |
| `snapshot` | the screen as it is now to a PNG, complete and hashed (`sha256`), into the scratch or moved to `dest` |
| `log` | one `channel` of what MAME writes (`emulator` is `error.log`, `process` its stdout and stderr, `all` both tagged), filtered by a pattern **in the server** |
| `log_wait` | WHEN a line of a channel happened: answered at once if it already has, waited for if not (`TARGET`, or `TIMEOUT` at its bound); the one wait that answers while the machine runs |
| `captures` | every file `record`, `audio_record`, `trace`, `snapshot` and the graphics tools checked and handed back this session, re-read |
| `input` | press a field by MAME's own names (`:P1`, `Coin 1`) for `frames` frames, the port read back at the release |
| `record` | an AVI of exactly `frames` frames, checked by its own header |
| `audio_record` | the mixer's output over exactly `frames` frames, as a WAV checked by its own header |
| `throttle` | real speed on or off, switched at a PLACE: pending on a stopped machine, applied on a running one |
| `screen_signature` | one number for what is on screen, a `grid` x `grid` fold of the pixels |
| `palette` | the live pens of a palette device, as a table and as a labelled swatch picture: the colours of a board whose colour RAM is a write-only RAMDAC |
| `screen_view` | the screen as the PENS it holds, each pixel's palette index recovered exactly and the palette put back and proven: the picture, the pens asked for isolated, a histogram with the unused pens, or one pixel's pen, shown where it sits and, with a palette write log armed, the write that set it |
| `gfx_view` | bytes as tiles under a format you state in MAME's own `gfx_layout` terms, `RGN_FRAC` and `STEPn` included, through the live pens or a grey ramp that says it is not real colour |
| `gfx_locate` | a patch of the screen's pens searched in a block under candidate layouts and flips: a match proves the format, the tile's place and the palette bank against the screen, and what is ambiguous is said, never ranked |
| `gfx_sweep` | a block no format is known for, drawn under a fixed family of candidate layouts as one labelled sheet; each cell's id is a layout `gfx_locate` can prove against the screen, or a person's pick for `gfx_draft` |
| `gfx_draft` | a `gfx.yaml` draft derived from what the session proved: formats matched on the screen or chosen from a sheet, their assets, and the words of a captured block that hold a located object's x and y; every figure in a regenerable report beside it, and never written over a manifest |
| `gfx_load` | a project's `gfx.yaml`: named formats, assets and draw commands (which bits of which word hold each coordinate), every entry with its status and source, read by a strict YAML reader and refused whole on the first thing it does not know |
| `gfx_blits` | who painted this area: every blit of a frame, read from a capture of the command's register block, as a box over the screen in one colour per writer, summed up by default and listed a page at a time on request or for the blits covering an area, in the order drawn |
| `gfx_blit_source` | the rectangle one blit reads, decoded unscaled from the command's asset under the live pens, with a margin round it shown apart from the rectangle; the scale law stays the project's |
| `gfx_film` | the frames in which a write happened (a trigger, its value, its writer), kept inside MAME at emulation speed and handed back as a labelled contact sheet, one PNG per frame (indexed when its pens fit one), a listing and an animated PNG; each frame checked against MAME's own rendering of it where that is the bare screen, and how it differs measured where it is not |
| `palette_log` | who set a pen's colour on a write-only palette: every write to the ports the manifest declares (a byte RAMDAC, or one of two packed-word protocols, in the program or the io space), placed on its pen by the device's own state machine inside MAME, told as the game's or the debugger's, each row with the beam line and time of its write, the newest write of every pen always kept; `screen_view`'s pixel joins it to the pen under a point |
| `state_save` | the machine under a NAME through the debugger console, into the session's state directory |
| `state_list` | every state in the state directory, with its size, and the frame and pc of one this session wrote |
| `state_load` | a named state into the machine, the header judged before and the ROM checked after; the session is altered |
| `lua` | a script on MAME's own Lua console, one chunk under `pcall`; altered unless the caller declares `read_only=True`, a claim the session block counts |
| `debug` | one command to the debugger console; a mutating command counts as a write, and the console's own error answer is a refusal in its words |

## Going further

Every tool's own description, delivered to your client at connection, is its contract. The
WHY behind each contract, what each tool refuses and what it hands back in every case, the
symbol file, the running-machine rules, the Lua channel and how to run the tests are in
[`REFERENCE.md`](REFERENCE.md), one section per family in the order above.

## Licence

MIT. See `LICENSE`.

## Credits

Developed by Optimiza ([Marcos Hernández](https://www.linkedin.com/in/optimiza/)), in collaboration with [MS-DOS Club](https://msdos.club) and its [podcast](https://www.ivoox.com/podcast-ms-dos-club_sq_f11160693_1.html).
