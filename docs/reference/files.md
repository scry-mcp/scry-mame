# The Files tools

These tools read files and need no running machine: they answer while the program runs, and with no session at all. They compare two pictures, two series of frames or two recordings, and answer in numbers.

A comparison that could not have come out different is refused, not answered, with the code `control_silent`. Two series that never change, or two silent recordings, would otherwise pass as equal.

## A series of frames

A series is a folder of PNGs beside one manifest, a JSON file in the format `scry-series/1`. The manifest names the `server`, the `source` of the frame numbers, the `crop`, and one row per frame: `frame`, `path`, `sha256`, `bytes`, `signature`.

Reading a manifest hashes every file again and fingerprints every picture again. A frame changed since, or a row edited by hand, is refused.

<!-- scry-reference:begin image_compare -->
## `image_compare`

Compare two pictures, two series of frames, or one region across a series, and get the difference as numbers.

```text
image_compare(method, a="", b="", crop=null, shift=null, tolerance=null, manifest="", measure="",
    ref="", threshold=null, limit=null, dir="", checksums="")
```

### Try it

On two frames of the series the Gridlee example of [`series_capture`](captures.md#series_capture) wrote, frames 557 and 581. No machine is running.

Ask:

> How different are frames 557 and 581 of the series?

Call:

```text
image_compare(method="image", a="./tmp/demos/tour/series/f000557.png",
    b="./tmp/demos/tour/series/f000581.png")
```

Reply, 7 of 12 fields:

```json
{
  "summary": "image_compare image: 8975 pixels differ over 256x240, bbox [4, 17, 242, 213]",
  "differing_pixels": 8975,
  "bbox": [4, 17, 242, 213],
  "max_delta": [255, 255, 255],
  "width": 256,
  "height": 240,
  "tolerance": 0
}
```

8975 pixels differ between the two 256x240 pictures, all inside the rectangle `bbox`: 242 wide and 213 high, from (4, 17). A `tolerance` of 0 counts any difference.

<details><summary>The whole reply</summary>

```json
{
  "summary": "image_compare image: 8975 pixels differ over 256x240, bbox [4, 17, 242, 213]",
  "status": "ok",
  "differing_pixels": 8975,
  "bbox": [4, 17, 242, 213],
  "max_delta": [255, 255, 255],
  "width": 256,
  "height": 240,
  "crop": [0, 0, 256, 240],
  "shift": [0, 0],
  "tolerance": 0,
  "a": {"path": "./tmp/demos/tour/series/f000557.png", "sha256": "<volatile>"},
  "b": {"path": "./tmp/demos/tour/series/f000581.png", "sha256": "<volatile>"}
}
```

</details>

### The four methods

| method | what it compares |
|---|---|
| `image` | Two PNGs, pixel by pixel: how many pixels differ, and where. |
| `series` | Two series, frame by frame: how many frames are equal, and the first that differs. |
| `region` | One rectangle across a series: the frames at which it changes. |
| `golden` | A series or a folder of PNGs against a file of reference checksums. |

### Arguments

- `method` (one of `"image"`, `"series"`, `"region"`, `"golden"`, required): `image`, `series`, `region` or `golden`, as above.
- `a` (string, default `""`): The first PNG for `image`, or the first manifest for `series`. An absolute path, or one starting with `~`.
- `b` (string, default `""`): The second PNG or manifest, compared with `a`.
- `crop` (array of integer, optional): The rectangle to compare, `[x, y, width, height]`, for every method but `golden`. Left out, the whole picture.
- `shift` (array of integer, optional): For `image`: `[dx, dy]`, how far `b` is moved before the two are compared. Left out, no move.
- `tolerance` (integer, optional): For `image`: the difference in one colour component still counted as equal, 0 to 255. Left out, 0.
- `manifest` (string, default `""`): For `region` and `golden`: the series to read, by the path of its manifest.
- `measure` (string, default `""`): For `region`, what is followed: the rectangle's `signature`, its `changed_pixels` since the frame before, or its `match` with `ref`. Left out, `signature`.
- `ref` (string, default `""`): For the measure `match`: the PNG, of the crop's size, the rectangle is compared with.
- `threshold` (number, optional): For `match`: the fraction of the rectangle's pixels that must equal `ref`, above 0 and at most 1. Left out, 0.98.
- `limit` (integer, optional): For `region` and `golden`: how many items each list shows, 1 to 1000. Left out, 40; the whole count is beside the list.
- `dir` (string, default `""`): For `golden`: a folder of PNGs to check, in place of `manifest`.
- `checksums` (string, default `""`): For `golden`: the file of reference checksums, in the format `shasum -a 256` writes.

### What comes back

- `differing_pixels`: For `image`: how many pixels differ by more than `tolerance`. Zero means the two are equal over the rectangle compared.
- `bbox`: For `image`: the rectangle that holds every differing pixel, `[x, y, width, height]` in the coordinates of `a`.
- `first_differing`: For `series`: the first frame that differs, with its `frame` number, its `differing_pixels` and its `bbox`.
- `differing`: For `series`: how many paired frames differ. For `golden`: the names of the files whose checksum differs.
- `transitions`: For `region`: each change as `[frame, value]`, the first `limit` of them; `transitions_total` counts them all.
- `path`: For `region`: a JSON file written beside the manifest, with every transition and each frame's value.

<details><summary>All 33 reply fields</summary>

- `a` (object or string)
- `b` (object or string)
- `bbox` (array or object)
- `checksums` (string)
- `crop` (array)
- `differing` (integer or array)
- `differing_pixels` (integer)
- `differing_total` (integer)
- `dir` (string)
- `extra` (array)
- `extra_total` (integer)
- `first_differing` (object)
- `frames` (integer)
- `gaps` (array)
- `height` (integer)
- `identical` (integer)
- `manifest` (string)
- `matched` (integer)
- `max_delta` (array)
- `measure` (string)
- `missing` (array)
- `missing_total` (integer)
- `only_in_a` (array)
- `only_in_b` (array)
- `pairs` (integer)
- `path` (string)
- `series` (string)
- `shift` (array)
- `start` (array or object)
- `tolerance` (integer)
- `transitions` (array)
- `transitions_total` (integer)
- `width` (integer)

</details>

### What it refuses

- An argument the method does not take (`bad_argument`).
- Two pictures of different sizes with no `crop` that lies inside both (`bad_argument`).
- A `crop` that leaves the picture, or a `shift` that moves it wholly off itself (`bad_argument`).
- A path that is relative or missing, or a file that is no PNG or no `scry-series/1` manifest (`bad_argument`).
- A manifest with a frame changed since it was written, or a row edited by hand (`bad_argument`).
- A series that never changes, two series with no frame number in common, a region that never changes, or checksums that name no file examined (`control_silent`).

### Why it works this way

`image` compares the colours two pictures show, so an indexed PNG and an RGB one of the same screen are equal. `golden` compares file bytes through their checksums, so those two files differ.

Two pictures of different sizes are refused unless a `crop` lies inside both. A tool that shows a picture enlarges it by its `scale`, so take both at `scale=1` before comparing them.

A `crop` that leaves the picture is refused, never padded: a padded crop would compare pixels nobody drew.

<details><summary>More on why</summary>

- `series` pairs frames by number. Frames only one series has come back in `only_in_a` and `only_in_b` as `[first, last]` ranges.
- `region` answers `start`, the first frame and its value, then the transitions. `gaps` counts the frames between one transition and the next.
- `golden` pairs files and checksum lines by file name. `matched` counts the equal ones, `missing` lists lines with no file, `extra` files with no line.
- The reply repeats the arguments it took, each path in full. For `image`, `a` and `b` come back with the file's `path` and `sha256`.

</details>

### Related tools

- [`series_capture`](captures.md#series_capture)
- [`snapshot`](captures.md#snapshot)
- [`screen_signature`](screen.md#screen_signature)
- [`screen_view`](screen.md#screen_view)
- [`audio_compare`](#audio_compare)

<details><summary>The contract your client receives</summary>

```text
Compare PNGs, series or a region of one, in numbers. `crop` [x, y, w, h]; `limit` 1..1000
(default 40) cuts a list, its count beside it. Replies also echo the arguments they took.

`image`: PNGs `a`, `b`; two sizes need `crop`; `shift` [dx, dy] moves `b`; `tolerance`
0..255. Reply: `differing_pixels`, `bbox`, `max_delta`, `width`, `height`.

`series`: `scry-series/1` manifests `a`, `b`. Reply: `pairs`, `identical`, `differing`,
`first_differing`, `only_in_a`, `only_in_b`; `control_silent` names the `series` when a
series that cannot differ stopped it.

`region`: `crop` of `manifest` by `measure`: `signature`, `changed_pixels`, or `match`
against `ref` at `threshold` (0.98). Reply: `start`, `transitions`, `gaps`,
`transitions_total`, `frames`, `path`.

`golden`: `manifest` or `dir` against `checksums` (`shasum -a 256`). Reply: `matched`,
`differing`, `missing`, `extra`, `differing_total`, `missing_total`, `extra_total`.

Refused: an argument the method does not take; `control_silent` when nothing can differ.

Reads files, and `region` writes one, `path`: it needs no machine. Every path is absolute or starts with `~`.

Reference: REFERENCE.md, Media files.
```

</details>
<!-- scry-reference:end image_compare -->

<!-- scry-reference:begin audio_compare -->
## `audio_compare`

Measure a WAV recording, or compare two, and get loudness, silence, timing and closeness as numbers.

```text
audio_compare(method, path="", a="", b="", window=null, channel=null, align=null)
```

### Try it

On the WAV the Gridlee example of [`audio_record`](captures.md#audio_record) wrote. No machine is running.

Ask:

> Did card.wav record any sound? Measure it.

Call:

```text
audio_compare(method="measure", path="./tmp/demos/tour/card.wav")
```

Reply, 6 of 9 fields:

```json
{
  "summary": "audio_compare measure: ch0 silent",
  "sample_rate_hz": 48000,
  "channels": 1,
  "bits": 16,
  "window": [0.0, 0.5],
  "pcm_sha256": "bb918147fe10391b43adeba4bd21b9ef32e5bd6c5076c3517733a05ed6dd0569"
}
```

The summary's `ch0` is the first and only one of the file's `channels`, and it is silent over its half second. Gridlee's sound samples are not in the free set, hence the silence.

<details><summary>The whole reply</summary>

```json
{
  "summary": "audio_compare measure: ch0 silent",
  "status": "ok",
  "sample_rate_hz": 48000,
  "channels": 1,
  "bits": 16,
  "window": [0.0, 0.5],
  "measures": [
    {
      "channel": 0,
      "peak_dbfs": {"available": false, "why": "a level of zero has no value in dB"},
      "rms_dbfs": {"available": false, "why": "a level of zero has no value in dB"},
      "silent": true,
      "silence_spans": {"count": 1, "first": [0.0, 0.5]},
      "onset_s": {"available": false, "why": "a silent window has no onset"},
      "clipping_run": 0,
      "clipped": false
    }
  ],
  "pcm_sha256": "bb918147fe10391b43adeba4bd21b9ef32e5bd6c5076c3517733a05ed6dd0569",
  "path": "./tmp/demos/tour/card.wav"
}
```

</details>

### The two methods

| method | what it answers |
|---|---|
| `measure` | One recording: how loud it is, whether it is silent, when the sound begins and whether it clips. |
| `diff` | Two recordings: whether they are equal and, if not, how close they are. |

### Arguments

- `method` (one of `"measure"`, `"diff"`, required): `measure` or `diff`, as above.
- `path` (string, default `""`): For `measure`: the WAV to measure, 8- or 16-bit PCM. An absolute path, or one starting with `~`.
- `a` (string, default `""`): For `diff`: the recording under test.
- `b` (string, default `""`): For `diff`: the reference recording, of the same sample rate, `channels` and bit depth as `a`.
- `window` (array of number, optional): The part of the recording to read, `[from_s, to_s]` in seconds. Left out, the whole file.
- `channel` (integer, optional): For `measure`: which of the file's `channels` to measure, numbered from 0. Left out, each of them.
- `align` (boolean, optional): For `diff`: `true` lines up where the two sounds begin before comparing them; `false` compares from the first sample. Left out, `true`.

### What comes back

- `measures`: For `measure`: one row for each of the `channels`, with `channel`, `peak_dbfs`, `rms_dbfs`, `silent`, `silence_spans` (its `count` and `first`), `onset_s`, `clipping_run` and `clipped`.
- `pcm_sha256`: For `measure`: the SHA-256 of the samples in the window, equal for two files that hold the same sound.
- `exact`: For `diff`: `true` when the two windows hold the same bytes.
- `class`: For `diff`, the verdict in one word: `exact`, `inaudible`, `audible` or `different`.
- `snr_db`: For `diff`: the signal-to-noise ratio of `a` against `b`, the worst of the `channels`. Unavailable when the two are equal once lined up.
- `aligned_by_samples`: For `diff`: how many samples `a` was moved to line up with `b`.

<details><summary>All 16 reply fields</summary>

- `a` (string)
- `b` (string)
- `aligned_by_samples` (integer)
- `bits` (integer)
- `channels` (integer)
- `envelope_correlation` (number)
- `exact` (boolean)
- `length_delta_samples` (integer)
- `measures` (array)
- `onset_delta_ms` (number)
- `path` (string)
- `pcm_sha256` (string)
- `sample_rate_hz` (integer)
- `snr_db` (number or object)
- `window` (array)
- `class` (string)

</details>

### What it refuses

- An argument the method does not take (`bad_argument`).
- A file that is not 8- or 16-bit PCM, holds no sample or cannot be read (`bad_argument`).
- A `window` outside the recording, or a `channel` number the file does not have (`bad_argument`).
- For `diff`, two recordings that differ in sample rate, `channels` or bit depth (`bad_argument`).
- For `diff`, two recordings that are both silent over the window (`control_silent`).

### Why it works this way

The sound itself never comes back, only numbers, so a client that cannot listen checks a recording through them.

Each of the `channels` is measured and compared on its own, never mixed down first. Mixed, one in antiphase would cancel, and two swapped ones would average to the same sound.

`diff` lines up the two sounds unless `align` is `false`, so a recording that starts a few samples later is not called different. With `align` `false`, two recordings made from the same stop are compared sample for sample.

<details><summary>More on why</summary>

- A steady level that is not zero is no sound: loudness, silence and the comparison read the window less its mean.
- Two recordings whose lengths are more than a tenth of a second apart are `different`.
- The reply repeats `path`, `a`, `b` and the `window` it read.

</details>

### Related tools

- [`audio_record`](captures.md#audio_record)
- [`captures`](captures.md#captures)
- [`image_compare`](#image_compare)

<details><summary>The contract your client receives</summary>

```text
Measure a WAV or compare two, in numbers. 8- or 16-bit PCM; `window` [from_s, to_s],
seconds, default the whole file.

`measure`: `path`, every channel or `channel` (0 the first). Reply: `measures`, per channel
`channel`, `peak_dbfs`, `rms_dbfs`, `silent` (RMS under 0.5% of full scale),
`silence_spans` (under -60 dBFS for 50 ms or more), `onset_s` (over 2% of the peak),
`clipping_run` (flat at 95% of the peak or above), `clipped` (a run past 8); then
`sample_rate_hz`, `channels`, `bits`, `pcm_sha256`.

`diff`: `a` against the reference `b`, of one format; `align` (default true) meets the
onsets, then the waveforms; false compares from the starts. Reply: `exact`, `snr_db`,
`class` (`exact`; `inaudible` 60 dB or more; `audible` 30 to 60; `different`),
`envelope_correlation` (64-window envelopes), `onset_delta_ms`, `length_delta_samples`,
`aligned_by_samples`.

Refused: an argument the method does not take; `control_silent` when both are silent.

Reads files only: it needs no machine and alters nothing. Every path is absolute or starts with `~`.

Reference: REFERENCE.md, Media files.
```

</details>
<!-- scry-reference:end audio_compare -->
