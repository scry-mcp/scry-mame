# The Files tools

**The signature** is BLAKE2b with an 8-byte digest, 16 lowercase hex characters, over `scry-sig/1|pixel|<w>x<h>|` (the crop's size) and the crop's pixels row by row as RGB. A pixel is its resolved colour, never its pen, so a palette change is a new signature and two screens that look the same have one; only a screen map can be told to sign pens ([Screen maps](screen.md)).

**A crop** is `[x, y, width, height]`; one that leaves the picture is refused with its size, never padded, since a padded crop compares pixels nobody drew.

**A series** is PNGs beside one `scry-series/1` manifest: `server`, `source`, `crop`, and a row per frame `{frame, path, sha256, bytes, signature}`. Reading it hashes every file and signs each picture again, so a changed frame or a hand-edited row is refused rather than trusted.

**The file tools** touch no machine, so they answer with it running or with none, and they are scry-core's, the same body and text on both servers. Every series and golden comparison carries its control, because a result that cannot come out the other way is no result: a series whose frames never change says nothing about another (`control_silent`), two series with no frame in common compare nothing, a region whose measure never moves was missed, and goldens whose names meet no file examined nothing.

Channels are compared one by one, never through a mixdown: a channel in antiphase cancels, and two swapped channels average to one sound.

<!-- scry-reference:begin image_compare -->
## `image_compare`

*Compare pictures*

```text
image_compare(method, a="", b="", crop=null, shift=null, tolerance=null, manifest="", measure="", ref="", threshold=null, limit=null, dir="", checksums="")
```

Compare PNGs, series or a region of one, in numbers. `crop` [x, y, w, h]; `limit` 1..1000
(default 40) cuts a list, its count beside it. Replies also echo the arguments they took.

`image`: PNGs `a`, `b`; two sizes need `crop`; `shift` [dx, dy] moves `b`; `tolerance`
0..255. Reply: `differing_pixels`, `bbox`, `max_delta`, `width`, `height`.

`series`: `scry-series/1` manifests `a`, `b`. Reply: `pairs`, `identical`, `differing`,
`first_differing`, `only_in_a`, `only_in_b`.

`region`: `crop` of `manifest` by `measure`: `signature`, `changed_pixels`, or `match`
against `ref` at `threshold` (0.98). Reply: `start`, `transitions`, `gaps`,
`transitions_total`, `frames`, `path`.

`golden`: `manifest` or `dir` against `checksums` (`shasum -a 256`). Reply: `matched`,
`differing`, `missing`, `extra`, `differing_total`, `missing_total`, `extra_total`.

Refused: an argument the method does not take; `control_silent` when nothing can differ.

Reads files, and `region` writes one, `path`: it needs no machine. Every path is absolute or starts with `~`.

Reference: REFERENCE.md, Media files.

| argument | type | default |
|---|---|---|
| `method` | one of `"image"`, `"series"`, `"region"`, `"golden"` | required |
| `a` | string | `""` |
| `b` | string | `""` |
| `crop` | array of integer or null | `null` |
| `shift` | array of integer or null | `null` |
| `tolerance` | integer or null | `null` |
| `manifest` | string | `""` |
| `measure` | string | `""` |
| `ref` | string | `""` |
| `threshold` | number or null | `null` |
| `limit` | integer or null | `null` |
| `dir` | string | `""` |
| `checksums` | string | `""` |

| reply field | type |
|---|---|
| `a` | object or string |
| `b` | object or string |
| `bbox` | array or object |
| `checksums` | string |
| `crop` | array |
| `differing` | integer or array |
| `differing_pixels` | integer |
| `differing_total` | integer |
| `dir` | string |
| `extra` | array |
| `extra_total` | integer |
| `first_differing` | object |
| `frames` | integer |
| `gaps` | array |
| `height` | integer |
| `identical` | integer |
| `manifest` | string |
| `matched` | integer |
| `max_delta` | array |
| `measure` | string |
| `missing` | array |
| `missing_total` | integer |
| `only_in_a` | array |
| `only_in_b` | array |
| `pairs` | integer |
| `path` | string |
| `shift` | array |
| `start` | array or object |
| `tolerance` | integer |
| `transitions` | array |
| `transitions_total` | integer |
| `width` | integer |

Example, from a live run:

```json
{
  "method": "region",
  "manifest": "$TMPDIR/mame-mcp-jg2kthn4/series/series-1/manifest.json",
  "measure": "changed_pixels"
}
```

```json
{
  "summary": "image_compare region: changed_pixels, 9 transitions over 12 frames",
  "status": "ok",
  "measure": "changed_pixels",
  "crop": [0, 0, 336, 252],
  "frames": 12,
  "start": {
    "available": false,
    "why": "`changed_pixels` counts a change from the frame before, and the first frame has none"
  },
  "transitions": [
    [24, 14790],
    [25, 23888],
    [26, 30995],
    [27, 39139],
    [28, 31816],
    [29, 16125],
    "... 3 more"
  ],
  "gaps": [1, 1, 1, 1, 1, 1, "... 2 more"],
  "transitions_total": 9,
  "path": "$TMPDIR/mame-mcp-jg2kthn4/series/series-1/track-1.json",
  "manifest": "$TMPDIR/mame-mcp-jg2kthn4/series/series-1/manifest.json"
}
```
<!-- scry-reference:end image_compare -->

Replies echo the arguments they were given (`a`, `b`, `crop`, `shift`, `tolerance`, `manifest`, `dir`, `checksums`).

<!-- scry-reference:begin audio_compare -->
## `audio_compare`

*Measure or compare WAV recordings*

```text
audio_compare(method, path="", a="", b="", window=null, channel=null, align=null)
```

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

| argument | type | default |
|---|---|---|
| `method` | one of `"measure"`, `"diff"` | required |
| `path` | string | `""` |
| `a` | string | `""` |
| `b` | string | `""` |
| `window` | array of number or null | `null` |
| `channel` | integer or null | `null` |
| `align` | boolean or null | `null` |

| reply field | type |
|---|---|
| `a` | string |
| `b` | string |
| `aligned_by_samples` | integer |
| `bits` | integer |
| `channels` | integer |
| `envelope_correlation` | number |
| `exact` | boolean |
| `length_delta_samples` | integer |
| `measures` | array |
| `onset_delta_ms` | number |
| `path` | string |
| `pcm_sha256` | string |
| `sample_rate_hz` | integer |
| `snr_db` | number or object |
| `window` | array |
| `class` | string |

Example, from a live run:

```json
{
  "method": "measure",
  "path": "$TMPDIR/mame-live-matrix-5322d43c2c7c/jobs-scratch/L/f4.wav"
}
```

```json
{
  "summary": "audio_compare measure: ch0 peak -8.55 dBFS, onset 0.0001 s",
  "status": "ok",
  "sample_rate_hz": 48000,
  "channels": 1,
  "bits": 16,
  "window": [0.0, 0.6],
  "measures": [
    {
      "channel": 0,
      "peak_dbfs": -8.55,
      "rms_dbfs": -12.36,
      "silent": false,
      "silence_spans": {
        "count": 0,
        "first": {"available": false, "why": "no silence in the window"}
      },
      "onset_s": 0.0001,
      "clipping_run": 0,
      "clipped": false
    }
  ],
  "pcm_sha256": "9c808cd852605b03eea32b76138f7c9f518c7f2f29e3b9ca76530161be7301fb",
  "path": "$TMPDIR/mame-live-matrix-5322d43c2c7c/jobs-scratch/L/f4.wav"
}
```
<!-- scry-reference:end audio_compare -->

Replies echo `path`, `a`, `b` and `window`. The sound itself never comes back, which is why every result is a number.

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
  "summary": "snapshot: 441 bytes at $TMPDIR/mame-mcp-qwnd_9kr/snap/snapshot-1.png",
  "status": "ok",
  "path": "$TMPDIR/mame-mcp-qwnd_9kr/snap/snapshot-1.png",
  "bytes": 441,
  "sha256": "59fdab49a181cabd8045fbef879ebff22316aa2704e290511c90809736f1adcf",
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
    {
      "kind": "png",
      "path": "$TMPDIR/mame-mcp-qwnd_9kr/snap/snapshot-1.png",
      "present": true,
      "bytes": 441
    }
  ]
}
```
<!-- scry-reference:end captures -->

`kind` is the extension (`avi`, `wav`, `png`, `trace`) or `image`. The `trace` set file is not listed, and a recording its call answered still open or not begun is not listed either, its path being in that reply. `avi_frames` is the frame count the AVI header declares; `samples`, `channels` and `sample_rate_hz` are a WAV's. Each is unavailable once the file no longer reads as finished, and a file gone since stays listed with `present: false` rather than dropped.
