# Gridlee: the game keeps its credits twice

<!-- demo-motion:begin -->
<p align="center"><picture><source media="(prefers-reduced-motion: reduce)" srcset="screen.png"><img src="loop.webp" alt="Gridlee starting a game, then counting a coin after a saved state is loaded"></picture></p>

1. `disassemble` reads the coin routine at `0xb583`: the binary add, then the BCD.
2. `read_memory` reads the two credit bytes back: 4 in binary and 04 in BCD.
3. `screen_view` captures the game in play, at twice its pixels.
4. `state_write` loads the saved state and `input` drops a coin: CREDITS goes from 4 to 5.
5. `input` presses START on the five credits: the game starts with four left.

<!-- moments-ms: 2534,2534,2534,2534,2534 -->
<!-- demo-motion:end -->

Videa's *Gridlee* (1983) runs on a 6809. This demo drops three coins into it and looks for the
credits with a value scan, which ends on three bytes, not one. Watches on two of them show why:
the coin routine counts in binary in one and in BCD in the other.

## The ROM

[mamedev.org](https://www.mamedev.org/roms/) distributes this ROM for free, non-commercial use,
from its own site only, so it is not in this repository. Get it and check it with your MAME:

```sh
mkdir -p ~/roms
curl -fL -o ~/roms/gridlee.zip https://www.mamedev.org/roms/gridlee/gridlee.zip
mame -rompath ~/roms -verifyroms gridlee
```

## Run it

```sh
uv run python demos/gridlee/demo.py --rompath ~/roms
```

Each line it prints is one call and its check. The window opens behind the others, so the run
does not take your keyboard; `--watch` brings it in front, for when you want to watch it.

- `--binary PATH` picks the MAME to start. Left out, it is `MAME_BINARY`, else the `mame` on
  your `PATH`.
- `--display N` opens the window on that display. Left out, it opens on the main one.
- `--watch` shows the run: the window comes in front and takes your keyboard until the run ends.
- `--transcript PATH` moves the whole transcript; the run's other files go beside it.
- `--update-readme` rewrites this page's generated parts, `TRANSCRIPT.md`, `screen.png`,
  `loop.webp` and the README's example calls, from a run where every step passed. It needs
  ffmpeg and `img2webp` on your `PATH`, and Pillow and numpy (the `decorate` extra), which
  draw the border and the pointer over the loop.

Exit codes: 0 every step passed, 1 a step failed, 2 a usage error, 3 nothing was demonstrated.
That last one is a missing ROM, a relative path or a server that did not start.

## Try it yourself

[Add the server to your client](../../README.md#install) and ask it to start `gridlee` with
the ROM in `~/roms`. Each of these is a step of the demo, in the order the demo makes them.

<!-- demo-transcript:begin -->
### 1. Narrow a scan with each coin

Ask:

> Three coins are in. Keep only the bytes of the scan that hold 3 now.

Call:

```text
scan(method="filter", operator="=", value=3)
```

Reply, 3 of 13 fields:

```json
{
  "summary": "scan filter: = 0x03, 3 left",
  "hits_total": 3,
  "hits": [
    {"addr": "0x000003ee", "value": "0x03"},
    {"addr": "0x0000042b", "value": "0x03"},
    {"addr": "0x0000042c", "value": "0x03"}
  ]
}
```

Three bytes hold 3, and a scan cannot say which is the credits. "3 left" counts the bytes still in the scan; the watches of the next step tell them apart.

<details><summary>The whole reply</summary>

```json
{
  "summary": "scan filter: = 0x03, 3 left",
  "status": "ok",
  "operator": "=",
  "value": "0x03",
  "iterations": 3,
  "closed": false,
  "hits": [
    {"addr": "0x000003ee", "value": "0x03"},
    {"addr": "0x0000042b", "value": "0x03"},
    {"addr": "0x0000042c", "value": "0x03"}
  ],
  "hits_total": 3,
  "truncated": false,
  "cpu": ":maincpu",
  "space": "program",
  "names": [
    {"field": "hits[].addr", "number": "0x000003ee", "kind": "memory", "name": "spriteram"},
    {"field": "hits[].addr", "number": "0x0000042b", "kind": "memory", "name": "spriteram"},
    {"field": "hits[].addr", "number": "0x0000042c", "kind": "memory", "name": "spriteram"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

### 2. Let a watch name the writer

Ask:

> Change watches are on `0x42b` and `0x42c` and a fourth coin is in. Run half a second and tell me what stopped it.

Call:

```text
run_for(milliseconds=500, seconds=300)
```

Reply, 3 of 23 fields:

```json
{
  "summary": "run_for 500 ms: OTHER_STOP, frame 672 to 673",
  "verdict": "OTHER_STOP",
  "cause": "watch 0x42b: 0x0000042b written by pc 0x0000b583"
}
```

`OTHER_STOP` means a watch stopped the run before its half second ended. `cause` names the byte and the instruction that wrote it.

<details><summary>The whole reply</summary>

```json
{
  "summary": "run_for 500 ms: OTHER_STOP, frame 672 to 673",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 672,
  "frame_after": 673,
  "emulated_before_s": 11.371026,
  "emulated_after_s": 11.372898,
  "cycles": 2340,
  "reads": "<volatile>",
  "cause": "watch 0x42b: 0x0000042b written by pc 0x0000b583",
  "stop_seq": 10,
  "pc": "0x0000b586",
  "cpu": ":maincpu",
  "frame": 673,
  "regs": {
    "A": "0x01",
    "B": "0xcf",
    "D": "0x01cf",
    "X": "0xf609",
    "Y": "0xf2e6",
    "U": "0x7afa",
    "PC": "0xb586",
    "S": "0x07fc",
    "CC": "0xa0",
    "DP": "0x00"
  },
  "instruction": {
    "address": "B586",
    "bytes": "8601",
    "text": "LDA    #$01",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["B588: BB 04 2C ADDA   $042C", "B58B: 19       DAA", "B58C: B7 04 2C STA    $042C", "B58F: 39       RTS", "B590: 96 F4    LDA    <$F4", "B592: 27 21    BEQ    $B5B5", "B594: 96 B3    LDA    <$B3", "B596: 84 07    ANDA   #$07", "B598: 26 1A    BNE    $B5B4", "B59A: 8E F6 59 LDX    #$F659", "B59D: 96 F5    LDA    <$F5", "B59F: 27 03    BEQ    $B5A4", "B5A1: 8E F7 49 LDX    #$F749", "B5A4: CE 0A 85 LDU    #$0A85"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0x42b",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 4, "raw_hex": "04"}
    },
    {
      "ref": "0x42c",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "<volatile>",
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
  },
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

### 3. Read the routine it stopped in

Ask:

> Disassemble 12 bytes from `0xb583`, where the first watch stopped.

Call:

```text
disassemble(ref="0xb583", length=12)
```

Reply, 2 of 12 fields:

```json
{
  "summary": "disassemble 0xb583 (maincpu): 5 lines at 0x0000b583 (maincpu)",
  "lines": [
    "B583: 7C 04 2B INC    $042B",
    "B586: 86 01    LDA    #$01",
    "B588: BB 04 2C ADDA   $042C",
    "B58B: 19       DAA",
    "B58C: B7 04 2C STA    $042C"
  ]
}
```

The coin routine increments `$042B`, then adds one to `$042C` in BCD (`ADDA`, `DAA`, `STA`). The game keeps its credits twice, in binary and in BCD.

<details><summary>The whole reply</summary>

```json
{
  "summary": "disassemble 0xb583 (maincpu): 5 lines at 0x0000b583 (maincpu)",
  "status": "ok",
  "ref": "0xb583",
  "addr": "0x0000b583",
  "length": 12,
  "lines": ["B583: 7C 04 2B INC    $042B", "B586: 86 01    LDA    #$01", "B588: BB 04 2C ADDA   $042C", "B58B: 19       DAA", "B58C: B7 04 2C STA    $042C"],
  "cpu": ":maincpu",
  "flow": ["unknown", "unknown", "unknown", "unknown", "unknown"],
  "flow_source": "none",
  "note": "no mnemonic table for cpu type 'm6809' (tables: m68000, v30), so no line is classified",
  "names": [
    {"field": "given.ref", "number": "0xb583", "kind": "memory", "name": "maincpu"},
    {"field": "addr", "number": "0x0000b583", "kind": "memory", "name": "maincpu"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

### 4. See what ran before a stop

Ask:

> START was pressed and a watch stopped it. Show me the last eight instructions.

Call:

```text
history(limit=8)
```

Reply, 1 of 6 fields:

```json
{
  "lines": [
    "D68D: RTS",
    "C5AD: JSR    $D676",
    "D676: DEC    $042B",
    "D679: LDA    #$99",
    "D67B: ADDA   $042C",
    "D67E: DAA",
    "D67F: STA    $042C",
    "D682: RTS"
  ]
}
```

`history` lists what the CPU ran up to the stop, oldest first. START takes a credit from both counters: `DEC $042B`, then the BCD one by adding 99.

<details><summary>The whole reply</summary>

```json
{
  "summary": "history: 8 instructions of 8 asked",
  "status": "ok",
  "asked": 8,
  "lines": ["D68D: RTS", "C5AD: JSR    $D676", "D676: DEC    $042B", "D679: LDA    #$99", "D67B: ADDA   $042C", "D67E: DAA", "D67F: STA    $042C", "D682: RTS"],
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>
<!-- demo-transcript:end -->

<details><summary>The whole demo as one prompt</summary>

1. Start `gridlee` with the ROMs in `~/roms`, checked against its first program ROM (CRC
   1C43539E) as the reference image at `0xa000`.
2. Let the attract mode run for five seconds, then open a value scan over `0x0`, 2 KB.
3. Three times: drop a coin (`:IN1`, `Coin 1`, four frames), run two seconds, and keep only
   the bytes that equal the coins so far.
4. Put a watch that stops on a change of `0x42b` and another on `0x42c`, and drop a fourth
   coin.
5. Run half a second at a time until both watches have stopped the machine and a third half
   second runs clean; tell me which instruction writes each.
6. Disassemble 12 bytes from `0xb583`, read both bytes and save a state.
7. Press `1 Player Start`, run one frame on after the first stop, and show the last eight
   instructions and the registers.
8. Clear both watches, record 480 frames to an AVI, read both bytes and take a picture.
9. Load the state, read both bytes, drop a fifth coin, record 120 frames, read them again
   and close.

</details>

## Tools this demo uses

| Group | Tools |
|---|---|
| [Session](../../docs/reference/session.md) | `start`, `close` |
| [Run](../../docs/reference/run.md) | `run_for` |
| [Scan](../../docs/reference/scan.md) | `scan` |
| [Breakpoints](../../docs/reference/breakpoints.md) | `watch_add`, `declaration_clear` |
| [Read](../../docs/reference/read.md) | `read_memory`, `disassemble`, `history`, `registers` |
| [Lua](../../docs/reference/lua.md) | `input` |
| [Sequences](../../docs/reference/sequences.md) | `perform` |
| [States](../../docs/reference/states.md) | `state_write` |
| [Screen](../../docs/reference/screen.md) | `screen_view` |
| [Captures](../../docs/reference/captures.md) | `record` |

Each group is a page of the reference. Four of the names need a word:

- Run: the tools that let the program run and stop it again.
- Breakpoints: breakpoints and watches.
- Sequences: the tools that run several calls as one.
- Lua: the tools that reach MAME's own scripting, `input` among them.

## The transcript

[TRANSCRIPT.md](TRANSCRIPT.md) has every call of the run with its reply. The run reached the
ROM and MAME through links under the repository's own `tmp/`, so its paths read the same on
any computer.
