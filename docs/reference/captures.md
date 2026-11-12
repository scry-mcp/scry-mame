# The Captures tools

<!-- scry-reference:begin series_capture -->
## `series_capture`

*Capture a series of frames*

```text
series_capture(at_frames=null, first=null, last=null, step=1, crop=null, dest="", seconds=60.0)
```

Screen frames kept inside MAME as PNGs and a manifest, for `image_compare`. Stops two frames
past the last.

Frames by `run_for`'s counter, all ahead: `at_frames` or `first`, `last`, `step`, at most
1000. `crop` is `[x, y, width, height]`. `dest`: a new absolute or `~`-led
directory, kept after `close`. Needs a stopped machine; `seconds` bounds the read.

Reply: `manifest`, `count`, `first`, `last`, `crop`, `distinct`, `lost`, `kept_after_close`,
`run_for`'s fields. Refused: `bad_argument`, `cut_by_other_stop`.

Reference: REFERENCE.md, Media files.

| argument | type | default |
|---|---|---|
| `at_frames` | array of integer or null | `null` |
| `first` | integer or null | `null` |
| `last` | integer or null | `null` |
| `step` | integer | `1` |
| `crop` | array of integer or null | `null` |
| `dest` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `60.0` |

| reply field | type |
|---|---|
| `console_reruns` | integer |
| `cpu` | string |
| `following` | array of string |
| `instruction` | StopInstruction |
| `errorlog` | object |
| `frame` | integer |
| `pc` | string |
| `regs` | object |
| `resent` | integer |
| `stop_seq` | integer |
| `thread_errors` | integer |
| `emulated_after_s` | number or object |
| `emulated_before_s` | number or object |
| `count` | integer |
| `crop` | array |
| `cycles` | integer |
| `distinct` | integer |
| `first` | integer |
| `frame_after` | integer |
| `frame_before` | integer |
| `frame_source` | string |
| `frames_asked` | integer |
| `kept_after_close` | boolean |
| `last` | integer |
| `lost` | array |
| `manifest` | string |
| `polls` | integer |
| `verdict` | string |

Example, from a live run:

```json
{
  "at_frames": [14],
  "seconds": 10.0
}
```

```json
{
  "summary": "series_capture: 1 frame 14..14, 1 distinct, manifest $TMPDIR/mame-mcp-<run>/series/series-1/manifest.json",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 12,
  "frame_after": 16,
  "emulated_before_s": 0.259586,
  "emulated_after_s": 0.339456,
  "cycles": 1277920,
  "polls": 4,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 20,
  "pc": "0x00002986",
  "cpu": ":maincpu",
  "frame": 16,
  "regs": {
    "D0": "0x00005845",
    "D1": "0x00000000",
    "D2": "0x00000000",
    "D3": "0x00000000",
    "D4": "0x00000000",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x000002ff",
    "A1": "0x00000000",
    "A2": "0x00000000",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00200fe4",
    "SP": "0x00200fa4",
    "PS": "0x2108",
    "PC": "0x00002986"
  },
  "instruction": {
    "address": "002986",
    "bytes": "51C8FFFE",
    "text": "dbra    D0, $2986",
    "symbol": "mode_clear_blits",
    "delta": 304
  },
  "following": ["00298A: 33FC 0000 0070 0000 move.w  #$0, $700000.l", "002992: 33FC 0000 0070 0004 move.w  #$0, $700004.l", "00299A: 33FC 0000 0070 000C move.w  #$0, $70000c.l", "0029A2: 33FC 000F 0070 000E move.w  #$f, $70000e.l"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 66062},
  "manifest": "$TMPDIR/mame-mcp-<run>/series/series-1/manifest.json",
  "count": 1,
  "first": 14,
  "last": 14,
  "distinct": 1,
  "crop": [0, 0, 336, 252],
  "lost": [],
  "frames_asked": 1,
  "kept_after_close": false,
  "frame_source": "frame_number",
  "thread_errors": 0,
  "console_reruns": 0
}
```
<!-- scry-reference:end series_capture -->

**On an indexed screen a series frame is an RGB PNG and a film frame an indexed one**, on purpose: the film's index is the pen, which a colour PNG would lose, and a series is for comparing what the screen showed. So the same frame from the two never has the same bytes and a golden of one never matches the other by `image_compare(method="golden")`; `image_compare(method="image")` reads the colours a picture shows, so it compares them.

Each frame is MAME's own rendering, read by a frame notifier one frame late as `gfx_film` reads its frames. Its PNG is RGB where `gfx_film`'s may be indexed; compare the two with `image_compare(method="image")`. A reply carries `verdict`, the run's counters and the survey as `run_for` reports them.

<!-- scry-reference:begin record -->
## `record`

*Record frames to an AVI*

```text
record(frames, dest="", seconds=60.0)
```

Record exactly `frames` emulated frames of the screen to an AVI, then stop.
Needs the machine STOPPED (else `not_stopped`).

`dest`: an absolute `.avi` path not there yet; empty lands in the scratch. `frames` is 2 or
more. The AVI is checked before its path is given; zero frames is INVALID. A run cut short
leaves the recording open (`ended: false`); `seconds` bounds the wait for it.

Reply, once answered: `verdict`, `path`, `began`, `ended`, `bytes`, `avi_frames`, `view`,
`note`, the stop survey. Without an answer, `pending`.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `frames` | integer | required |
| `dest` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `60.0` |

| reply field | type |
|---|---|
| `console_reruns` | integer |
| `cpu` | string |
| `following` | array of string |
| `instruction` | StopInstruction |
| `errorlog` | object |
| `frame` | integer |
| `pc` | string |
| `regs` | object |
| `resent` | integer |
| `stop_seq` | integer |
| `thread_errors` | integer |
| `emulated_after_s` | number or object |
| `emulated_before_s` | number or object |
| `ended` | boolean |
| `frame_after` | integer |
| `frame_before` | integer |
| `frame_begin` | integer or object |
| `frame_begin_planned` | integer |
| `frame_end` | integer |
| `frame_end_planned` | integer |
| `frames` | integer |
| `instructions_completed` | integer |
| `lines_ahead` | integer |
| `mode` | string |
| `path` | string |
| `pending` | boolean |
| `polls` | integer |
| `reader_steps` | integer |
| `recording_after` | boolean or object |
| `regpoint_hit` | object |
| `avi_frames` | integer or object |
| `began` | boolean |
| `bytes` | integer or object |
| `cycles` | integer or object |
| `drain_steps` | integer |
| `tagged_lines` | array |
| `verdict` | string |
| `view` | string or object |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "frames": 2,
  "seconds": 10.0
}
```

```json
{
  "summary": "record: 2 frames, 666220 bytes at $TMPDIR/mame-mcp-<run>/snap/record-2.avi",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 19,
  "frame_after": 24,
  "emulated_before_s": 0.39936,
  "emulated_after_s": 0.499207,
  "cycles": 1597548,
  "polls": 5,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "path": "$TMPDIR/mame-mcp-<run>/snap/record-2.avi",
  "frames": 2,
  "began": true,
  "frame_begin": 20,
  "recording_after": true,
  "ended": true,
  "bytes": 666220,
  "avi_frames": 2,
  "frame_end": 21,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 25,
  "pc": "0x000e2cf0",
  "cpu": ":maincpu",
  "frame": 24,
  "regs": {
    "D0": "0x002d000d",
    "D1": "0x00000032",
    "D2": "0x000000fc",
    "D3": "0x0000008b",
    "D4": "0x0000000f",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x000000fc",
    "A1": "0x002088a0",
    "A2": "0x00203208",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00200fd8",
    "SP": "0x00200fcc",
    "PS": "0x2100",
    "PC": "0x000e2cf0"
  },
  "instruction": {
    "address": "0E2CF0",
    "bytes": "11809800",
    "text": "move.b  D0, (A0,A1.l)",
    "symbol": "palette_range_table",
    "delta": 49630
  },
  "following": ["0E2CF4: 5242           addq.w  #1, D2", "0E2CF6: B47C 02FF      cmp.w   #$2ff, D2", "0E2CFA: 6FD4           ble     $e2cd0", "0E2CFC: 5379 0020 10C6 subq.w  #1, $2010c6.l", "0E2D02: 2079 0020 7990 movea.l $207990.l, A0", "0E2D08: 30BC 0001      move.w  #$1, (A0)", "... 1 more"],
  "errorlog": {
    "lines_total": 6,
    "truncated": false,
    "lines": ["[luaengine] MAME_MCP_RECORD#23 armed frame=19 vblank=true", "", "[luaengine] MAME_MCP_RECORD#23 begin frame=20 recording=true", "", "[luaengine] MAME_MCP_RECORD#23 end frame=21", ""],
    "mark": 66249
  },
  "view": "native"
}
```
<!-- scry-reference:end record -->

A `seconds` that would hold the server's lock past its ceiling is refused.

The frame notifier begins and ends the recording, so the count is emulated frames, and it cannot end a recording on the call that begins it: one frame is refused rather than recorded as two. `seconds` bounds the whole call like `input`'s. Lines already in the console's pipe are stepped off before the script is sent so the frames asked for are the recording's own. A script run twice logs its mark twice, a recording begun twice on one file. Cut short, a run leaves the recording open (`frame_end_planned`) or not begun (`began: false`, `frame_begin_planned`). The stop survey is the one every advancing wrapper returns.

<!-- scry-reference:begin audio_record -->
## `audio_record`

*Record the sound to a WAV*

```text
audio_record(frames, dest="", seconds=60.0)
```

Record the mixer's output for exactly `frames` frames to a WAV, then stop.
Needs the machine STOPPED (else `not_stopped`).

`dest`: an absolute path not there yet; empty lands in the scratch. `frames` is 2 or more.
`seconds` bounds the wait for the recording to end.
The WAV is checked before its path is given; a span with no mixer update, no speaker, or a
mixer already recording is INVALID. Silence is reported, never refused.

Reply, once answered: `verdict`, `path`, `began`, `ended`, `bytes`, `channels`,
`sample_rate_hz`, `samples`, `emulated_s`, `sample_min`, `sample_max`, `note`, the stop
survey. Without an answer, `pending`.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `frames` | integer | required |
| `dest` | string | `""` |
| `seconds` | number (> 0, <= 600.0) | `60.0` |

| reply field | type |
|---|---|
| `console_reruns` | integer |
| `cpu` | string |
| `following` | array of string |
| `instruction` | StopInstruction |
| `errorlog` | object |
| `frame` | integer |
| `pc` | string |
| `regs` | object |
| `resent` | integer |
| `stop_seq` | integer |
| `thread_errors` | integer |
| `emulated_after_s` | number or object |
| `emulated_before_s` | number or object |
| `ended` | boolean |
| `frame_after` | integer |
| `frame_before` | integer |
| `frame_begin` | integer or object |
| `frame_begin_planned` | integer |
| `frame_end` | integer |
| `frame_end_planned` | integer |
| `frames` | integer |
| `instructions_completed` | integer |
| `lines_ahead` | integer |
| `mode` | string |
| `path` | string |
| `pending` | boolean |
| `polls` | integer |
| `reader_steps` | integer |
| `recording_after` | boolean or object |
| `regpoint_hit` | object |
| `began` | boolean |
| `bytes` | integer or object |
| `channels` | integer or object |
| `cycles` | integer |
| `drain_steps` | integer |
| `emulated_s` | number or object |
| `sample_max` | integer or object |
| `sample_min` | integer or object |
| `sample_rate_hz` | integer or object |
| `samples` | integer or object |
| `tagged_lines` | array |
| `verdict` | string |
| `watch_hit` | object |
| `watches` | array |

Example, from a live run:

```json
{
  "frames": 2,
  "seconds": 10.0
}
```

```json
{
  "summary": "audio_record: 1920 samples at 48000 Hz x 2 at $TMPDIR/mame-mcp-<run>/snap/audio-3.wav",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 24,
  "frame_after": 30,
  "emulated_before_s": 0.499207,
  "emulated_after_s": 0.619008,
  "cycles": 1916822,
  "polls": 6,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "path": "$TMPDIR/mame-mcp-<run>/snap/audio-3.wav",
  "frames": 2,
  "began": true,
  "frame_begin": 25,
  "recording_after": true,
  "ended": true,
  "bytes": 7724,
  "channels": 2,
  "sample_rate_hz": 48000,
  "samples": 1920,
  "emulated_s": 0.039936,
  "sample_min": -10050,
  "sample_max": -6589,
  "frame_end": 26,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 26,
  "pc": "0x000e2cea",
  "cpu": ":maincpu",
  "frame": 30,
  "regs": {
    "D0": "0x0001000b",
    "D1": "0x00000032",
    "D2": "0x000001dc",
    "D3": "0x00000020",
    "D4": "0x0000000f",
    "D5": "0x00000000",
    "D6": "0x00000000",
    "D7": "0x00000000",
    "A0": "0x000001dc",
    "A1": "0x0020829c",
    "A2": "0x00203208",
    "A3": "0x00000000",
    "A4": "0x00000000",
    "A5": "0x00000000",
    "FP": "0x00200fd8",
    "SP": "0x00200fcc",
    "PS": "0x2100",
    "PC": "0x000e2cea"
  },
  "instruction": {
    "address": "0E2CEA",
    "bytes": "C1C3",
    "text": "muls.w  D3, D0",
    "symbol": "palette_range_table",
    "delta": 49624
  },
  "following": ["0E2CEC: 48C0           ext.l   D0", "0E2CEE: 81C1           divs.w  D1, D0", "0E2CF0: 1180 9800      move.b  D0, (A0,A1.l)", "0E2CF4: 5242           addq.w  #1, D2", "0E2CF6: B47C 02FF      cmp.w   #$2ff, D2", "0E2CFA: 6FD4           ble     $e2cd0", "... 3 more"],
  "errorlog": {
    "lines_total": 6,
    "truncated": false,
    "lines": ["[luaengine] MAME_MCP_AUDIO#24 armed frame=24 vblank=true", "", "[luaengine] MAME_MCP_AUDIO#24 begin frame=25 ok=true recording=true time=0.51916800000000007 period=0.019968000000000003", "", "[luaengine] MAME_MCP_AUDIO#24 end frame=27 time=0.55910400000000005", ""],
    "mark": 66415
  }
}
```
<!-- scry-reference:end audio_record -->

It ends one notifier call later than `record`'s script, so the span between its marks is `frames` frame periods of emulated time. The mixer writes in updates of a fiftieth of an emulated second, so the sound begins up to one update before the first frame and ends up to one before the last. The header is checked because MAME's writer checks none of its writes and writes both sizes only at close, so an open file reads 0 in both. Silence is a fact about the game, not a refusal: a constant level is silence to the ear whether zero or not. An open recording gains nothing while the machine stands at the debugger, since no mixer update runs there. 2 is the fewest `frames` that always holds an update on a screen under 100 Hz.

The check covers a header that agrees with the file, the counter moved by exactly `frames`, the span of `frames` frame periods and the samples that span holds at the header's rate, within one update. Cut short, the run leaves the recording open (`ended: false`, `frame_end_planned`) or not begun (`began: false`, `frame_begin_planned`). A script run twice is INVALID (`console_rerun`). The stop survey is the one every advancing wrapper returns.

<!-- scry-reference:begin snapshot -->
## `snapshot`

*Snapshot the screen to a PNG*

```text
snapshot(dest="")
```

Save a PNG of the screen now, through `view`, in the scratch or moved to `dest`, which must
be a new absolute or `~`-led path in an existing directory. Works while running.

Reply: `path`, `bytes`, `sha256`, `view`. An incomplete PNG is `INVALID`.

Reference: REFERENCE.md, Input and the screen.

| argument | type | default |
|---|---|---|
| `dest` | string | `""` |

| reply field | type |
|---|---|
| `bytes` | integer |
| `path` | string |
| `sha256` | string |
| `view` | string or object |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "snapshot: 441 bytes at $TMPDIR/mame-mcp-<run>/snap/snapshot-1.png",
  "status": "ok",
  "path": "$TMPDIR/mame-mcp-<run>/snap/snapshot-1.png",
  "bytes": "<volatile>",
  "sha256": "<volatile>",
  "view": "native"
}
```
<!-- scry-reference:end snapshot -->

The console's `snap` treats even an absolute path as relative to the snapshot directory, which is why the tool snaps under its own name and moves the file.

A `dest` is refused with a comma, semicolon, quote, whitespace, bracket or control character, because the console command line cannot carry them; the check runs before the console is touched, so a refused path costs no snapshot. The file's `sha256` is the hash a golden's `checksums.sha256` compares. A scratch snapshot dies with `close`, so give a `dest` to keep one. A semantic frame is `run_to` the point where the drawer finishes, then `snapshot`.

<!-- scry-reference:begin captures -->
## `captures`

*List this session's captures*

```text
captures()
```

List the files `record`, `audio_record`, `trace`, `snapshot` and the graphics tools made
this session, re-read now; works while running.

Reply: `captures` (`kind`, `path`, `present`, `bytes`, `avi_frames`, `samples`, `channels`,
`sample_rate_hz`).

Reference: REFERENCE.md, Input and the screen.

Takes no argument.

| reply field | type |
|---|---|
| `captures` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "captures: 1 file, 1 png",
  "status": "ok",
  "captures": [
    {"kind": "png", "path": "$TMPDIR/mame-mcp-<run>/snap/snapshot-1.png", "present": true, "bytes": 441}
  ]
}
```
<!-- scry-reference:end captures -->

`kind` is the extension (`avi`, `wav`, `png`, `trace`) or `image`. The `trace` set file is not listed, and a recording its call answered still open or not begun is not listed either, its path being in that reply. `avi_frames` is the frame count the AVI header declares; `samples`, `channels` and `sample_rate_hz` are a WAV's. Each is unavailable once the file no longer reads as finished, and a file gone since stays listed with `present: false` rather than dropped.
