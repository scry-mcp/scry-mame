# The Captures tools

These tools save what the machine shows and plays to files on your disk: `snapshot` a still, `series_capture` chosen frames, `record` a video and `audio_record` the sound. `captures` lists what the session wrote.

A reply names its file by path and never carries the picture or the sound. `image_compare` and `audio_compare`, on the [Files](files.md) page, read those files back as numbers.

`record`, `audio_record` and `series_capture` count emulated frames, not seconds of your clock, so a call captures the same stretch at any speed. `snapshot` and `record` draw the screen through the MAME view chosen at `start`; `series_capture` reads the screen's own pixels.

<!-- scry-reference:begin series_capture -->
## `series_capture`

Save chosen frames of the screen as PNGs beside a manifest, for `image_compare` to read.

```text
series_capture(at_frames=null, first=null, last=null, step=1, crop=null, dest="", seconds=60.0)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped at frame 553, as a game begins. The frames asked for must be ahead of the frame the machine is at.

Ask:

> Keep every eighth frame from 557 to 581 as pictures in a folder named series.

Call:

```text
series_capture(first=557, last=581, step=8, dest="./tmp/demos/tour/series", seconds=300)
```

Reply, 8 of 30 fields:

```json
{
  "summary": "series_capture: 4 frames 557..581, 3 distinct, manifest ./tm ... (93 characters)",
  "verdict": "ELAPSED",
  "frame_before": 553,
  "frame_after": 583,
  "count": 4,
  "distinct": 3,
  "lost": [],
  "kept_after_close": true
}
```

Four frames between 557 and 581 were kept, three of them different pictures, and none was lost. `ELAPSED` means the run reached its end: the machine went from frame 553 to 583.

<details><summary>The whole reply</summary>

```json
{
  "summary": "series_capture: 4 frames 557..581, 3 distinct, manifest ./tmp/demos/tour/series/manifest.json",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 553,
  "frame_after": 583,
  "emulated_before_s": 9.3604,
  "emulated_after_s": 9.86728,
  "cycles": 633600,
  "polls": 31,
  "cause": "series_capture: one step",
  "stop_seq": 24,
  "pc": "0x0000fd82",
  "cpu": ":maincpu",
  "frame": 583,
  "regs": {
    "A": "0x01",
    "B": "0x10",
    "D": "0x0110",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xfd82",
    "S": "0x07f4",
    "CC": "0xd0",
    "DP": "0x00"
  },
  "instruction": {"address": "FD82", "bytes": "96B2", "text": "LDA    <$B2", "symbol": "irq", "delta": 2},
  "following": ["FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "... 9 more"],
  "errorlog": "<volatile>",
  "manifest": "./tmp/demos/tour/series/manifest.json",
  "count": 4,
  "first": 557,
  "last": 581,
  "distinct": 3,
  "crop": [0, 0, 256, 240],
  "lost": [],
  "frames_asked": 4,
  "kept_after_close": true,
  "frame_source": "frame_number",
  "thread_errors": 0,
  "console_reruns": 0
}
```

</details>

### Arguments

- `at_frames` (array of integer, optional): The frames to keep, as an ascending list of frame numbers. Give this or `first` and `last`, never both.
- `first` (integer, optional): The first frame of an evenly spaced range, given with `last`.
- `last` (integer, optional): The last frame of the range. A series holds at most 1000 frames.
- `step` (integer, default `1`): The spacing of the range: every `step`-th frame from `first`. Left out, 1.
- `crop` (array of integer, optional): The rectangle of the screen each PNG holds, `[x, y, width, height]`. Left out, the whole screen.
- `dest` (string, default `""`): A new folder for the series, absolute or starting with `~`, which outlives `close`. Left empty, a folder in the session's temporary folder, deleted at `close`.
- `seconds` (number (> 0, <= 600.0), default `60.0`): The time limit of the run, in seconds of your clock. Left out, 60.

### What comes back

- `manifest`: The path of the series' manifest, `manifest.json`; the PNGs sit beside it, named by frame as `f000123.png`.
- `count`: How many frames were written; `first` and `last` are their lowest and highest numbers.
- `distinct`: How many different pictures the series holds. One means nothing changed on screen.
- `kept_after_close`: `true` when the series is in a `dest` you named, `false` when `close` deletes it.
- `lost`: Frames asked for that the emulator skipped drawing, as `[first, last]` ranges. They have no picture and are left out.
- `verdict`: How the run ended, as `run_for` reports it: `ELAPSED` when every frame ran.

<details><summary>All 29 reply fields</summary>

- `console_reruns` (integer)
- `cpu` (string)
- `following` (array of string)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer)
- `pc` (string)
- `regs` (object)
- `resent` (integer)
- `stop_seq` (integer)
- `thread_errors` (integer)
- `watches` (array)
- `emulated_after_s` (number or object)
- `emulated_before_s` (number or object)
- `count` (integer)
- `crop` (array)
- `cycles` (integer)
- `distinct` (integer)
- `first` (integer)
- `frame_after` (integer)
- `frame_before` (integer)
- `frame_source` (string)
- `frames_asked` (integer)
- `kept_after_close` (boolean)
- `last` (integer)
- `lost` (array)
- `manifest` (string)
- `polls` (integer)
- `verdict` (string)

</details>

### What it refuses

- Both `at_frames` and a range, or neither; a list that is not ascending; more than 1000 frames (`bad_argument`).
- A frame that is not ahead of the frame the machine is at (`bad_argument`).
- A `crop` that leaves the screen, or a `dest` that exists (`bad_argument`).
- An `at_frames` list too long for one console line: give `first`, `last` and `step` (`bad_argument`).
- A run another stop ends before the last frame is read: no series is written from part of one (`cut_by_other_stop`).
- A run in which every frame asked for was skipped (`no_progress`).
- A machine with no screen (`no_channel`), or one that is running (`not_stopped`).

### Why it works this way

Frame numbers are the emulated frame counter, the one `run_for(frames=)` counts, and every frame asked for must still be ahead. The call runs the program to two frames past the last one and stops there.

Each picture is MAME's own rendering of its frame, in the colours the palette held at the frame's end, read one frame later. A frame the emulator skipped drawing is listed in `lost`, never filled in.

A series frame is always an RGB PNG, because a series is for comparing what the screen showed. `gfx_film` may write the same frame as an indexed PNG, so their checksums never match: compare the two with `image_compare(method="image")`.

<details><summary>More on why</summary>

The reply is also a stop: it carries `verdict` and the fields `run_for` returns, with the readings taken at each stop.

`frames_asked` is how many frames the call named, and `frame_source` says what the numbers count: `frame_number`, the emulated frame counter.

</details>

### Related tools

- [`image_compare`](files.md#image_compare)
- [`run_for`](run.md#run_for)
- [`snapshot`](#snapshot)
- [`screen_signature`](screen.md#screen_signature)
- [`gfx_film`](timeline.md#gfx_film)

<details><summary>The contract your client receives</summary>

```text
Screen frames kept inside MAME as PNGs and a manifest, for `image_compare`. Stops two frames
past the last.

Frames by `run_for`'s counter, all ahead: `at_frames` or `first`, `last`, `step`, at most
1000. `crop` is `[x, y, width, height]`. `dest`: a new absolute or `~`-led
directory, kept after `close`. Needs a stopped machine; `seconds` bounds the read.

Reply: `manifest`, `count`, `first`, `last`, `crop`, `distinct`, `lost`, `kept_after_close`,
`run_for`'s fields. Refused: `bad_argument`, `cut_by_other_stop`.

Reference: REFERENCE.md, Media files.
```

</details>
<!-- scry-reference:end series_capture -->

<!-- scry-reference:begin record -->
## `record`

Record an exact number of frames of the screen to an AVI video, then stop the program again.

```text
record(frames, dest="", seconds=60.0)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped on the card that announces a level, right after START is pressed with two credits.

Ask:

> Record the next 30 frames of the screen to a video named card.avi.

Call:

```text
record(frames=30, dest="./tmp/demos/tour/card.avi", seconds=300)
```

Reply, 8 of 31 fields:

```json
{
  "summary": "record: 30 frames, 5659194 bytes at ./tmp/demos/tour/card.avi",
  "verdict": "ELAPSED",
  "frame_begin": 562,
  "frame_end": 591,
  "began": true,
  "ended": true,
  "avi_frames": 30,
  "view": "native"
}
```

The video holds 30 frames, 562 to 591, and the recording is closed (`ended`). `ELAPSED` means every frame ran, and `native` is the MAME view the video was drawn through.

<details><summary>The whole reply</summary>

```json
{
  "summary": "record: 30 frames, 5659194 bytes at ./tmp/demos/tour/card.avi",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 561,
  "frame_after": 594,
  "emulated_before_s": 9.495573,
  "emulated_after_s": 10.053138,
  "cycles": 696956,
  "polls": 33,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "path": "./tmp/demos/tour/card.avi",
  "frames": 30,
  "began": true,
  "frame_begin": 562,
  "recording_after": true,
  "ended": true,
  "bytes": 5659194,
  "avi_frames": 30,
  "frame_end": 591,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 57,
  "pc": "0x0000fd80",
  "cpu": ":maincpu",
  "frame": 594,
  "regs": {
    "A": "0x00",
    "B": "0xfc",
    "D": "0x00fc",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xfd80",
    "S": "0x07f4",
    "CC": "0xd4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "... 9 more"],
  "errorlog": "<volatile>",
  "view": "native"
}
```

</details>

### Arguments

- `frames` (integer, required): How many emulated frames to record: 2 or more.
- `dest` (string, default `""`): An absolute `.avi` path that does not exist yet. Left empty, the file goes to the session's temporary folder, deleted at `close`.
- `seconds` (number (> 0, <= 600.0), default `60.0`): The time limit of the whole call, in seconds of your clock. Left out, 60.

### What comes back

- `path`: The AVI, once the reply has read it back as a finished file.
- `avi_frames`: How many frames the file's own header says it holds.
- `ended`: `true` once the recording is closed. `false` when a stop cut the run short: it stays open until the machine reaches `frame_end_planned`.
- `began`: `false` when a stop came before the first frame: the recording begins at `frame_begin_planned`.
- `verdict`: How the run ended, as `run_for` reports it: `ELAPSED` when every frame ran, `TIMEOUT` when `seconds` ran out first.
- `view`: The MAME view the video was drawn through, chosen at `start`.

<details><summary>All 40 reply fields</summary>

- `console_reruns` (integer)
- `cpu` (string)
- `following` (array of string)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer)
- `pc` (string)
- `regs` (object)
- `resent` (integer)
- `stop_seq` (integer)
- `thread_errors` (integer)
- `watches` (array)
- `emulated_after_s` (number or object)
- `emulated_before_s` (number or object)
- `ended` (boolean)
- `frame_after` (integer)
- `frame_before` (integer)
- `frame_begin` (integer or object)
- `frame_begin_planned` (integer)
- `frame_end` (integer)
- `frame_end_planned` (integer)
- `frames` (integer)
- `instructions_completed` (integer)
- `lines_ahead` (integer)
- `mode` (string)
- `path` (string)
- `pending` (boolean)
- `polls` (integer)
- `reader_steps` (integer)
- `recording_after` (boolean or object)
- `regpoint_hit` (object)
- `avi_frames` (integer or object)
- `began` (boolean)
- `bytes` (integer or object)
- `cycles` (integer or object)
- `drain_steps` (integer)
- `tagged_lines` (array)
- `verdict` (string)
- `view` (string or object)
- `watch_hit` (object)

</details>

### What it refuses

- `frames` under 2, or a `dest` that is not a new `.avi` path (`bad_argument`).
- A machine that is running (`not_stopped`).
- A machine with no screen or no frame counter (`no_channel`).
- A file that does not read back as a finished AVI with frames in it (`readback_refused`).
- A script MAME's console ran twice, which begins two recordings on one file (`console_rerun`).
- A run that did not come to a stop within `seconds` and could not be ended (`not_settled`).

### Why it works this way

The recording is counted in emulated frames, so no time of your clock goes into the file. A script inside MAME begins and ends it as frames are drawn, and it cannot end a recording on the frame that begins it: one frame is refused.

A stop that is not the time limit, such as a breakpoint, cuts the run short and leaves the recording open or not begun. It goes on when the machine reaches the planned frame, unless the next `record` call cancels it.

When `seconds` runs out first, the recording is closed there and the reply reads the file back: `ended: true`, with the frames it ran.

<details><summary>More on why</summary>

Lines already waiting in MAME's console are run before the script is sent, one instruction each, so the frames asked for are the recording's own.

The reply is also a stop: it carries `verdict` and the fields `run_for` returns, with the readings taken at each stop. `frame_before` and `frame_after` say how far the machine moved.

A reply with `pending: true` means the console had not run the script when the call ended, so nothing is known about the recording yet.

</details>

### Related tools

- [`captures`](#captures)
- [`snapshot`](#snapshot)
- [`audio_record`](#audio_record)
- [`run_for`](run.md#run_for)
- [`series_capture`](#series_capture)

<details><summary>The contract your client receives</summary>

```text
Record exactly `frames` emulated frames of the screen to an AVI, then stop.
Needs the machine STOPPED (else `not_stopped`).

`dest`: an absolute `.avi` path not there yet; empty lands in the session's scratch, gone at `close`, and the reply names it either way. `frames` is 2 or more. `seconds` bounds the wait for the recording. The AVI is read before its path is given.

A run cut at that bound is released before the reply: when the release answers, the reply says `ended: true` and names the AVI it read back, and a file that does not read as finished is INVALID. A release that does not answer leaves the run's own refusal. A stop that is
not the bound leaves the recording open (`ended: false`) until the machine reaches its last
frame.

Reply, once answered: `verdict`, `frames`, `path`, `began`, `ended`, `bytes`, `avi_frames`, `view`, `note`, the stop survey. Without an answer, `pending`.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end record -->

<!-- scry-reference:begin audio_record -->
## `audio_record`

Record an exact number of frames of sound to a WAV file, then stop the program again.

```text
audio_record(frames, dest="", seconds=60.0)
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped on the card that announces a level. The free set lacks Gridlee's sound samples, so the game is silent here.

Ask:

> Record the sound of the next 30 frames to a file named card.wav.

Call:

```text
audio_record(frames=30, dest="./tmp/demos/tour/card.wav", seconds=300)
```

Reply, 8 of 35 fields:

```json
{
  "summary": "audio_record: 24000 samples at 48000 Hz x 1, silent at ./tmp/demos/tour/card.wav",
  "verdict": "ELAPSED",
  "channels": 1,
  "sample_rate_hz": 48000,
  "samples": 24000,
  "emulated_s": 0.50688,
  "sample_min": 0,
  "sample_max": 0
}
```

The file holds 24000 samples for about half an emulated second. `sample_min` and `sample_max` are both 0: the recording is silent, because Gridlee's sound samples are not in the free set.

<details><summary>The whole reply</summary>

```json
{
  "summary": "audio_record: 24000 samples at 48000 Hz x 1, silent at ./tmp/demos/tour/card.wav",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 594,
  "frame_after": 628,
  "emulated_before_s": 10.053138,
  "emulated_after_s": 10.627602,
  "cycles": 718080,
  "polls": 34,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "path": "./tmp/demos/tour/card.wav",
  "frames": 30,
  "began": true,
  "frame_begin": 595,
  "recording_after": true,
  "ended": true,
  "bytes": 48044,
  "channels": 1,
  "sample_rate_hz": 48000,
  "samples": 24000,
  "emulated_s": 0.50688,
  "sample_min": 0,
  "sample_max": 0,
  "frame_end": 624,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 58,
  "pc": "0x0000fd80",
  "cpu": ":maincpu",
  "frame": 628,
  "regs": {
    "A": "0x00",
    "B": "0xda",
    "D": "0x00da",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xfd80",
    "S": "0x07f4",
    "CC": "0xd4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "... 9 more"],
  "errorlog": "<volatile>"
}
```

</details>

### Arguments

- `frames` (integer, required): How many emulated frames of sound to record: 2 or more.
- `dest` (string, default `""`): An absolute path that does not exist yet. Left empty, the file goes to the session's temporary folder, deleted at `close`.
- `seconds` (number (> 0, <= 600.0), default `60.0`): The time limit of the whole call, in seconds of your clock. Left out, 60.

### What comes back

- `path`: The WAV, once it has been checked.
- `samples`: How many samples the file holds, at `sample_rate_hz` a second, for each of its `channels`.
- `emulated_s`: The emulated time the recording spans, in seconds.
- `sample_min`: The lowest sample value in the file, beside `sample_max`. The two equal mean a constant level: silence.
- `ended`: `true` once the recording is closed. `false` when a stop cut the run short: it stays open until the machine reaches `frame_end_planned`.
- `verdict`: How the run ended, as `run_for` reports it: `ELAPSED` when every frame ran, `TIMEOUT` when `seconds` ran out first.

<details><summary>All 44 reply fields</summary>

- `console_reruns` (integer)
- `cpu` (string)
- `following` (array of string)
- `instruction` (StopInstruction)
- `errorlog` (object)
- `frame` (integer)
- `pc` (string)
- `regs` (object)
- `resent` (integer)
- `stop_seq` (integer)
- `thread_errors` (integer)
- `watches` (array)
- `emulated_after_s` (number or object)
- `emulated_before_s` (number or object)
- `ended` (boolean)
- `frame_after` (integer)
- `frame_before` (integer)
- `frame_begin` (integer or object)
- `frame_begin_planned` (integer)
- `frame_end` (integer)
- `frame_end_planned` (integer)
- `frames` (integer)
- `instructions_completed` (integer)
- `lines_ahead` (integer)
- `mode` (string)
- `path` (string)
- `pending` (boolean)
- `polls` (integer)
- `reader_steps` (integer)
- `recording_after` (boolean or object)
- `regpoint_hit` (object)
- `began` (boolean)
- `bytes` (integer or object)
- `channels` (integer or object)
- `cycles` (integer)
- `drain_steps` (integer)
- `emulated_s` (number or object)
- `sample_max` (integer or object)
- `sample_min` (integer or object)
- `sample_rate_hz` (integer or object)
- `samples` (integer or object)
- `tagged_lines` (array)
- `verdict` (string)
- `watch_hit` (object)

</details>

### What it refuses

- `frames` under 2, or a `dest` that exists (`bad_argument`).
- A machine that is running (`not_stopped`).
- A machine with no screen or no frame counter (`no_channel`).
- A stretch with no mixer update, a machine with no speaker, or a mixer already recording (`readback_refused`).
- A WAV whose header, length or sample count does not agree with the run (`readback_refused`).
- A script MAME's console ran twice (`console_rerun`).

### Why it works this way

The recording spans exactly `frames` frame periods of emulated time. MAME's mixer writes in updates of a fiftieth of an emulated second. So the sound begins up to one update before the first frame and ends up to one before the last.

The file is checked before its path is given, because MAME's writer checks none of its writes and fills the header's two sizes only at close. The header must agree with the file, and the samples with the stretch, within one update.

Silence is reported, never refused: it is a fact about the program. A constant level is silence to the ear whether it is zero or not.

<details><summary>More on why</summary>

Two is the fewest `frames` that always hold a mixer update on a screen under 100 Hz.

A stop that cuts the run short leaves the recording open or not begun, as [`record`](#record) explains. An open recording gains nothing while the machine stands at the debugger, since no mixer update runs there.

</details>

### Related tools

- [`audio_compare`](files.md#audio_compare)
- [`captures`](#captures)
- [`record`](#record)
- [`run_for`](run.md#run_for)

<details><summary>The contract your client receives</summary>

```text
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
```

</details>
<!-- scry-reference:end audio_record -->

<!-- scry-reference:begin snapshot -->
## `snapshot`

Save a still of the screen as it is now to a PNG file.

```text
snapshot(dest="")
```

### Try it

On Gridlee, a free ROM from mamedev.org, stopped while the card that announces a level is on screen.

Ask:

> Save a picture of the screen as it is now to card.png.

Call:

```text
snapshot(dest="./tmp/demos/tour/card.png")
```

Reply, 2 of 6 fields:

```json
{
  "path": "./tmp/demos/tour/card.png",
  "view": "native"
}
```

The still is a complete PNG at `path`. `native` is the MAME view it was drawn through.

<details><summary>The whole reply</summary>

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "path": "./tmp/demos/tour/card.png",
  "bytes": "<volatile>",
  "sha256": "<volatile>",
  "view": "native"
}
```

</details>

### Arguments

- `dest` (string, default `""`): A new path for the PNG, absolute or starting with `~`, in a folder that exists. Left empty, the session's temporary folder, deleted at `close`.

### What comes back

- `path`: The PNG, checked to be complete.
- `sha256`: The file's SHA-256: the value a line of reference checksums holds for `image_compare(method="golden")`.
- `view`: The MAME view the still was drawn through, chosen at `start`.

<details><summary>All 4 reply fields</summary>

- `bytes` (integer)
- `path` (string)
- `sha256` (string)
- `view` (string or object)

</details>

### What it refuses

- A `dest` that exists, is relative, or sits in a folder that does not exist (`bad_argument`).
- A `dest` holding a comma, semicolon, quote, space, bracket or control character (`bad_argument`).
- A PNG that is not complete on disk in time (`unexpected_answer`).

### Why it works this way

The still is MAME's own snapshot, and it works while the program runs. To capture a finished picture and not one half drawn, `run_to` the address where the drawing routine ends, then take the snapshot.

MAME's `snap` command treats even an absolute path as relative to its snapshot folder, so the tool takes the still under its own name and moves the file. MAME's command line cannot carry the characters refused in `dest`.

A `dest` is checked before MAME is asked, so a refused path costs no snapshot.

### Related tools

- [`captures`](#captures)
- [`image_compare`](files.md#image_compare)
- [`screen_view`](screen.md#screen_view)
- [`record`](#record)
- [`run_to`](run.md#run_to)

<details><summary>The contract your client receives</summary>

```text
Save a PNG of the screen now, through `view`, in the scratch or moved to `dest`, which must
be a new absolute or `~`-led path in an existing directory. Works while running.

Reply: `path`, `bytes`, `sha256`, `view`. An incomplete PNG is `INVALID`.

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end snapshot -->

<!-- scry-reference:begin captures -->
## `captures`

List the files this session's tools wrote, each read again now: whether it is still there, its size, what it holds.

```text
captures()
```

### Try it

On Gridlee, a free ROM from mamedev.org, near the end of a session that has recorded a video, a sound and a trace and saved pictures.

Ask:

> List the files this session has written so far.

Call:

```text
captures()
```

Reply, 1 of 3 fields:

```json
{
  "summary": "captures: 15 files, 1 avi, 1 png, 11 image, 1 wav, 1 trace"
}
```

Fifteen files: a video, a snapshot (`png`), a sound file, a trace and eleven pictures (`image`) that the graphics tools and the series wrote.

<details><summary>The whole reply</summary>

```json
{
  "summary": "captures: 15 files, 1 avi, 1 png, 11 image, 1 wav, 1 trace",
  "status": "ok",
  "captures": [
    {
      "kind": "image",
      "path": "./tmp/demos/tour/film/frame-1.png",
      "present": true,
      "bytes": "<volatile>"
    },
    {
      "kind": "image",
      "path": "./tmp/demos/tour/film/sheet-0.png",
      "present": true,
      "bytes": "<volatile>"
    },
    {"kind": "image", "path": "./tmp/demos/tour/pixel.png", "present": true, "bytes": "<volatile>"},
    {"kind": "image", "path": "./tmp/demos/tour/palette.png", "present": true, "bytes": "<volatile>"},
    {"kind": "image", "path": "./tmp/demos/tour/sweep.png", "present": true, "bytes": "<volatile>"},
    {"kind": "image", "path": "./tmp/demos/tour/tiles.png", "present": true, "bytes": "<volatile>"},
    "... 9 more"
  ]
}
```

</details>

### Arguments

Takes no argument.

### What comes back

- `captures`: One row per file: `kind`, `path`, `present` and `bytes`. An AVI adds `avi_frames`; a WAV adds `samples`, `channels` and `sample_rate_hz`.

<details><summary>All 1 reply fields</summary>

- `captures` (array)

</details>

### Why it works this way

Every file is read again at each call, so the list says what is on disk now, and it answers while the program runs. A file deleted since stays listed, with `present: false`.

`kind` is the file's extension (`avi`, `wav`, `png`, `trace`), or `image` for a picture a graphics tool or a series wrote. An AVI's or a WAV's counts are unavailable once the file no longer reads as finished.

The file of addresses a `trace` writes beside its trace is not listed. Neither is an unfinished recording: a recording its call answered still open or not begun is not listed, since that call's reply holds its path.

### Related tools

- [`record`](#record)
- [`audio_record`](#audio_record)
- [`snapshot`](#snapshot)
- [`series_capture`](#series_capture)
- [`trace`](run.md#trace)

<details><summary>The contract your client receives</summary>

```text
List the files `record`, `audio_record`, `trace`, `snapshot` and the graphics tools made
this session, re-read now; works while running.

Reply: `captures` (`kind`, `path`, `present`, `bytes`, `avi_frames`, `samples`, `channels`,
`sample_rate_hz`).

Reference: REFERENCE.md, Input and the screen.
```

</details>
<!-- scry-reference:end captures -->
