# LineUp: one script plays the arcade board and its DOS version

<!-- demo-motion:begin -->
<p align="center"><picture><source media="(prefers-reduced-motion: reduce)" srcset="screen.png"><img src="loop.webp" alt="LineUp played on the arcade board: three shots, each from another column or colour"></picture></p>

1. `input` presses fire, and `record` films the shot.
2. `input` moves the player one column right and fires again.
3. `input` raises the next colour and fires a third time.

<!-- moments-ms: 1018,1018,1018 -->
<!-- demo-motion:end -->

*LineUp* (Eco-Games / GAMART, 1994) ran on an NEC V30 arcade board, and its team ported the
same source to MS-DOS. This demo plays the board by the game's own routine and variable names:
a coin, a game started, a move, a colour, a shot, each read back from memory.

## The program

LineUp is not distributed with this repository. The demo needs three things:

- its ROM set, `lineup.zip`, with the linker's symbol map, `lineup.map`, in the same directory,
  which `--rompath` names;
- a MAME whose driver list includes `lineup`;
- a directory, which `--cwd` names, holding the game's `.scry/` folder: its
  `.scry/maps/lineup-screen-map.json` is the screen map the demo loads, a file that names the
  game's screens.

## Run it

```sh
uv run python demos/lineup/demo.py --rompath /path/to/romset --cwd /path/to/game
```

Each line it prints is one call and its check. The window opens behind the others, so the run
does not take your keyboard; `--watch` brings it in front, for when you want to watch it.

- `--binary PATH` picks the MAME to start. Left out, it is `MAME_BINARY`, else the `mame` on
  your `PATH`.
- `--cwd PATH` (absolute or `~`-led) is the directory holding the game.
- `--display N` opens the window on that display. Left out, it opens on the main one.
- `--watch` shows the run: the window comes in front and takes your keyboard until the run ends.
- `--transcript PATH` moves the whole transcript; the run's other files go beside it.
- `--update-readme` rewrites this page's generated parts, `TRANSCRIPT.md`, `screen.png` and
  `loop.webp`, from a run where every step passed. It needs ffmpeg and `img2webp` on your
  `PATH`, and Pillow and numpy (the `decorate` extra), which draw the border and the pointer
  over the loop.

Exit codes: 0 every step passed, 1 a step failed, 2 a usage error, 3 nothing was demonstrated.
That last one is a missing ROM set, a relative path, a copy without the game's map or a
server that did not start.

Nothing in the run waits a fixed time: each screen is waited for at a breakpoint on the game's
own 50 Hz tick. A screen is recognised by a screen map written in palette indices, because the
board and a VGA card show the same pixels in slightly different colours.

The script is `scry_core.games.lineup`, and scry-dosbox-x runs the DOS version with the same
symbols, screens and checks. Only a few settings differ per emulator: how the game starts,
which input is each control, the screen's refresh rate, and the reference recording of its music.

## Try it yourself

[Add the server to your client](../../README.md#install) and ask it to start `lineup` with your
ROM set and its symbol map. Each of these is a step of the demo, in the order the demo makes
them.

<!-- demo-transcript:begin -->
### 1. Run to a routine by its name

Ask:

> Run the game until it starts drawing its high-score table, and count `Check_Money25` on the way.

Call:

```text
run_to(ref="Draw_High_Scores_Screen", control="Check_Money25", seconds=120)
```

Reply, 3 of 15 fields:

```json
{
  "summary": "run_to Draw_High_Scores_Screen: TARGET, control counted 250",
  "verdict": "TARGET",
  "control_hits": 250
}
```

`TARGET` means the game stopped where `Draw_High_Scores_Screen` begins. `control_hits` counts an address that runs on every tick, so a run that misses its target still says the game was running.

<details><summary>The whole reply</summary>

```json
{
  "summary": "run_to Draw_High_Scores_Screen: TARGET, control counted 250",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 250,
  "controls": [
    {"ref": "Check_Money25", "cpu": ":maincpu", "hits_in_run": 250}
  ],
  "cause": "target Draw_High_Scores_Screen",
  "stop_seq": 2,
  "pc": "0x000317ff",
  "cpu": ":maincpu",
  "frame": 251,
  "regs": {
    "EAX": "0x0500",
    "ECX": "0x0000",
    "EDX": "0x73ca",
    "EBX": "0x0000",
    "ESP": "0x99db",
    "EBP": "0xbe31",
    "ESI": "0x6992",
    "EDI": "0xfb28",
    "EIP": "0x000317ff",
    "EFLAGS": "0xf006",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {
    "address": "317FF",
    "bytes": "1E",
    "text": "push    ds0",
    "symbol": "Draw_High_Scores_Screen",
    "delta": 0
  },
  "following": ["31800: E8 21 FE call    31624h", "31803: B8 01 00 mov     aw,1h", "31806: E8 29 73 call    38B32h", "31809: E8 50 36 call    34E5Ch", "3180C: E8 8F FF call    3179Eh", "3180F: 1F       pop     ds0", "31810: C3       ret     ", "31811: 1E       push    ds0", "31812: E8 0F FE call    31624h", "31815: B8 00 00 mov     aw,0h", "31818: E8 17 73 call    38B32h", "3181B: E8 80 FF call    3179Eh", "3181E: 1F       pop     ds0"],
  "errorlog": "<volatile>",
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

### 2. Read a variable by its name

Ask:

> Read the game's `Credits` variable now that the coin is in.

Call:

```text
read_memory(ref="Credits", length=2)
```

Reply, 3 of 8 fields:

```json
{
  "summary": "read_memory Credits: 2 bytes at 0x0000914a: 0300",
  "addr": "0x0000914a",
  "hex": "0300"
}
```

`Credits` is a name from the game's own symbol map, so the same call works on the arcade board and on the PC port. `hex` is the value, low byte first: three credits for one coin.

<details><summary>The whole reply</summary>

```json
{
  "summary": "read_memory Credits: 2 bytes at 0x0000914a: 0300",
  "status": "ok",
  "ref": "Credits",
  "addr": "0x0000914a",
  "length": 2,
  "hex": "0300",
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

### 3. Compare a recording with its reference

Ask:

> Compare the music you just recorded with the reference recording, sample by sample.

Call:

```text
audio_compare(method="diff", a="./tmp/demos/lineup/music.wav", b="<host>", align=false)
```

Reply, 2 of 12 fields:

```json
{
  "summary": "audio_compare diff: exact, equal, envelope 1.0",
  "exact": true
}
```

`exact` is true only when every sample is equal, so a changed sound, a different mixer or a late start fails the run.

<details><summary>The whole reply</summary>

```json
{
  "summary": "audio_compare diff: exact, equal, envelope 1.0",
  "status": "ok",
  "exact": true,
  "snr_db": {
    "available": false,
    "why": "the two are equal after alignment: there is no error to measure the signal against"
  },
  "class": "exact",
  "envelope_correlation": 1.0,
  "onset_delta_ms": 0.0,
  "length_delta_samples": 0,
  "aligned_by_samples": 0,
  "a": "./tmp/demos/lineup/music.wav",
  "b": "<volatile>",
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

1. Start `lineup` with the ROM set directory, checked against the image its two ROM halves
   make at `0x30000`.
2. In that same call take its symbols from `lineup.map`, with `DATA` at `0x400` and
   `LUP_JUKEBOX` left where the map puts it.
3. Load the game's screen map, `.scry/maps/lineup-screen-map.json` in the copy.
4. Run to `Draw_High_Scores_Screen` counting `Check_Money25`.
5. Put a breakpoint on `Check_Money100` and wait, looking at the screen only when it stops
   there, until the map names `hiscores`; clear it and read `Credits`.
6. Drop a coin, wait the same way for `insert`, and read `Credits` again.
7. Press START, run to `Level_Write`, wait the same way for `level`, and read `Credits` and
   `Stage_Act`.
8. Wait the same way for `play` with `Player1`'s first double word at 0x30001, and read the
   first six words of `Player1`.
9. Move right, take the next colour and shoot, running to `Gest_Scores` after each before
   reading `Player1`.
10. Record two seconds of sound, measure it and compare it with `music.wav`.
11. Shoot three more times: where the player stands, one column to the right, and with the
    next colour. Record a second of video after each shot.
12. Take a picture of the screen and close.

</details>

## Tools this demo uses

| Group | Tools |
|---|---|
| [Session](../../docs/reference/session.md) | `start`, `close` |
| [Run](../../docs/reference/run.md) | `run_to`, `screen_wait` |
| [Breakpoints](../../docs/reference/breakpoints.md) | `breakpoint_at`, `declaration_clear` |
| [Read](../../docs/reference/read.md) | `screen_map_write`, `screen_map_find`, `read_memory` |
| [Lua](../../docs/reference/lua.md) | `input` |
| [Captures](../../docs/reference/captures.md) | `record`, `audio_record` |
| [Files](../../docs/reference/files.md) | `audio_compare` |
| [Screen](../../docs/reference/screen.md) | `screen_view` |

Each group is a page of the reference. Three of the names need a word:

- Run: the tools that let the program run and stop it again.
- Breakpoints: breakpoints and watches.
- Lua: the tools that reach MAME's own scripting, `input` among them.

## The transcript

[TRANSCRIPT.md](TRANSCRIPT.md) has every call of the run with its reply. The two seconds of
music it records must equal [`music.wav`](music.wav) sample for sample (`win32/music.wav` on
Windows, where MAME mixes the sound differently).
