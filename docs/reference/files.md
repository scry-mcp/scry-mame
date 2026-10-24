# The Files tools

**The signature** is BLAKE2b with an 8-byte digest, 16 lowercase hex characters, over `scry-sig/1|pixel|<w>x<h>|` (the crop's size) and the crop's pixels row by row as RGB. A pixel is its resolved colour, never its pen, so a palette change is a new signature and two screens that look the same have one.

**A crop** is `[x, y, width, height]`; one that leaves the picture is refused with its size, never padded, since a padded crop compares pixels nobody drew.

**A series** is PNGs beside one `scry-series/1` manifest: `server`, `source`, `crop`, and a row per frame `{frame, path, sha256, bytes, signature}`. Reading it hashes every file and signs each picture again, so a changed frame or a hand-edited row is refused rather than trusted.

**The file tools** touch no machine, so they answer with it running or with none, and they are scry-core's, the same body and text on both servers. Every series and golden comparison carries its control, because a result that cannot come out the other way is no result: a series whose frames never change says nothing about another (`control_silent`), two series with no frame in common compare nothing, a region whose measure never moves was missed, and goldens whose names meet no file examined nothing.

<!-- scry-reference:begin image_diff -->
## `image_diff`

*Compare two pictures*

```text
image_diff(a, b, crop=null, shift=null, tolerance=0)
```

Compare two PNG files pixel by pixel, in the colours they show, and answer where they
differ without sending either picture.

`a`, `b`: paths of PNGs (8-bit, indexed or RGB). `crop` [x, y, width, height] is
the rectangle compared on both; it must lie inside both (it is never padded), and pictures
of two sizes need one. `shift` [dx, dy] compares pixel (x, y) of `a` with (x + dx, y + dy) of
`b`, over the part of the crop both stay in: a sprite that moved compares equal at its
move. `tolerance` (0..255) is the per-channel difference still counted equal.

Reply: `differing_pixels`, `bbox` ([x, y, w, h] in `a`'s pixels, unavailable when none
differ),
`max_delta` ([r, g, b], the largest channel difference seen), `width` and `height` (`a`'s),
`crop` (the rectangle of `a` compared), `shift`, `tolerance`, and `a` and `b` (`path`,
`sha256`).

Reads files only: it needs no machine and alters nothing. Every path is absolute or starts with `~`.

Reference: REFERENCE.md, Media files.

| argument | type | default |
|---|---|---|
| `a` | string | required |
| `b` | string | required |
| `crop` | array of integer or null | `null` |
| `shift` | array of integer or null | `null` |
| `tolerance` | integer | `0` |

| reply field | type |
|---|---|
| `a` | object |
| `b` | object |
| `bbox` | array or object |
| `crop` | array |
| `differing_pixels` | integer |
| `height` | integer |
| `max_delta` | array |
| `shift` | array |
| `tolerance` | integer |
| `width` | integer |

Example, from a live run:

```json
{
  "a": "/nonexistent/a.png",
  "b": "/nonexistent/b.png"
}
```

```json
{
  "summary": "image_diff: INVALID (bad_argument), a: /nonexistent/a.png is not a file",
  "status": "INVALID",
  "code": "bad_argument",
  "message": "a: /nonexistent/a.png is not a file"
}
```
<!-- scry-reference:end image_diff -->

<!-- scry-reference:begin series_diff -->
## `series_diff`

*Compare two series*

```text
series_diff(a, b, crop=null)
```

Compare two series frame by frame, paired by frame number, after checking that each one
can tell frames apart at all.

`a`, `b`: paths of `scry-series/1` manifests (what `series_capture` writes); every
file a manifest lists is checked against its sha256 first. `crop` [x, y, width, height] is
compared on every frame of both, inside the PNGs. THE CONTROLS: a series whose every frame
has one signature over the crop is `control_silent` naming it, since it says nothing about
the other one; two series with no frame number in common are `control_silent` too.

Reply: `pairs`, `identical`, `differing`, `first_differing` (`frame`, `differing_pixels`,
`bbox`, or unavailable), `only_in_a` and `only_in_b` (frames with no partner, as [first, last]
runs), `crop` (the rectangle compared), and `a`, `b`.

Reads files only: it needs no machine and alters nothing. Every path is absolute or starts with `~`.

Reference: REFERENCE.md, Media files.

| argument | type | default |
|---|---|---|
| `a` | string | required |
| `b` | string | required |
| `crop` | array of integer or null | `null` |

| reply field | type |
|---|---|
| `a` | string |
| `b` | string |
| `crop` | array |
| `differing` | integer |
| `first_differing` | object |
| `identical` | integer |
| `only_in_a` | array |
| `only_in_b` | array |
| `pairs` | integer |

Example, from a live run:

```json
{
  "a": "/nonexistent/a.json",
  "b": "/nonexistent/b.json"
}
```

```json
{
  "summary": "series_diff: INVALID (bad_argument), a: /nonexistent/a.json is not a file",
  "status": "INVALID",
  "code": "bad_argument",
  "message": "a: /nonexistent/a.json is not a file"
}
```
<!-- scry-reference:end series_diff -->

<!-- scry-reference:begin region_track -->
## `region_track`

*Track a region through a series*

```text
region_track(manifest, crop=null, measure="signature", ref="", threshold=0.98, limit=40)
```

Follow one region through a series and answer the frames where it changes, as numbers,
never as pictures.

`manifest`: the path of a `scry-series/1` manifest. `crop` [x, y, width, height],
inside its PNGs (default the whole picture). `measure`: `signature` (the region's
signature; a transition is a new one), `changed_pixels` (pixels changed since the previous
frame; a transition is a frame where any did), `match` (the fraction of the region equal to
`ref`, the path of a PNG of the crop's size; on at `threshold` or more, default
0.98, and a transition is a flip). `limit` (1..1000, default 40): transitions listed. THE
CONTROL: a measure that never changes over the series is `control_silent`, the crop having
missed.

Reply: `start` ([frame, value] at the first frame; unavailable for `changed_pixels`),
`transitions` ([frame, value]: the new signature, the count, or true/false), `gaps` (frame
numbers between consecutive transitions), `transitions_total`, `frames`, `measure`, `crop`
(the rectangle measured), `manifest`, and `path`, a JSON file beside the manifest holding
every transition and each frame's value; a list cut at `limit` says so in `omitted` and
`how`.

Reads files and writes one, `path`: it needs no machine. Every path is absolute or starts with `~`.

Reference: REFERENCE.md, Media files.

| argument | type | default |
|---|---|---|
| `manifest` | string | required |
| `crop` | array of integer or null | `null` |
| `measure` | string | `"signature"` |
| `ref` | string | `""` |
| `threshold` | number | `0.98` |
| `limit` | integer | `40` |

| reply field | type |
|---|---|
| `crop` | array |
| `frames` | integer |
| `gaps` | array |
| `manifest` | string |
| `measure` | string |
| `path` | string |
| `start` | array or object |
| `transitions` | array |
| `transitions_total` | integer |

Example, from a live run:

```json
{
  "manifest": "$TMPDIR/mame-mcp-_b1vof95/series/series-1/manifest.json",
  "measure": "changed_pixels"
}
```

```json
{
  "summary": "region_track changed_pixels: 9 transitions over 12 frames",
  "status": "ok",
  "measure": "changed_pixels",
  "crop": [
    0,
    0,
    336,
    252
  ],
  "frames": 12,
  "start": {
    "available": false,
    "why": "`changed_pixels` counts a change from the frame before, and the first frame has none"
  },
  "transitions": [
    [
      24,
      14790
    ],
    [
      25,
      23888
    ],
    [
      26,
      30995
    ],
    [
      27,
      39139
    ],
    [
      28,
      31816
    ],
    [
      29,
      16125
    ],
    "... 3 more"
  ],
  "gaps": [
    1,
    1,
    1,
    1,
    1,
    1,
    "... 2 more"
  ],
  "transitions_total": 9,
  "path": "$TMPDIR/mame-mcp-_b1vof95/series/series-1/track-1.json",
  "manifest": "$TMPDIR/mame-mcp-_b1vof95/series/series-1/manifest.json"
}
```
<!-- scry-reference:end region_track -->

<!-- scry-reference:begin golden_check -->
## `golden_check`

*Check files against goldens*

```text
golden_check(manifest="", dir="", checksums="", limit=40)
```

Check a series, or a directory of PNGs, against goldens written by `shasum -a 256`:
exact bytes, by file name.

ONE of `manifest`, the path of a `scry-series/1` manifest (its frames), or `dir`, a
directory (its `*.png`); and `checksums`, the path of a file of
`<sha256>  <name>` lines (the name's last part is matched, so a line may carry a directory).
A file and a golden that meet nowhere compare nothing, so no name in common is
`control_silent`; a line that does not parse is refused naming it.

Reply: `matched` (a count), `differing`, `missing` (goldens with no file) and `extra` (files
with no golden), each a sorted list of names cut at `limit` (1..1000, default 40) with its
whole count beside it (`differing_total`, `missing_total`, `extra_total`; a cut list says so
in `omitted` and `how`), and `checksums`, and `manifest` or `dir`.

Reads files only: it needs no machine and alters nothing. Every path is absolute or starts with `~`.

Reference: REFERENCE.md, Media files.

| argument | type | default |
|---|---|---|
| `manifest` | string | `""` |
| `dir` | string | `""` |
| `checksums` | string | `""` |
| `limit` | integer | `40` |

| reply field | type |
|---|---|
| `checksums` | string |
| `differing` | array |
| `differing_total` | integer |
| `dir` | string |
| `extra` | array |
| `extra_total` | integer |
| `manifest` | string |
| `matched` | integer |
| `missing` | array |
| `missing_total` | integer |

Example, from a live run:

```json
{
  "manifest": "/nonexistent/m.json",
  "checksums": "/nonexistent/g.sha256"
}
```

```json
{
  "summary": "golden_check: INVALID (bad_argument), checksums: /nonexistent/g.sha256 is not a file",
  "status": "INVALID",
  "code": "bad_argument",
  "message": "checksums: /nonexistent/g.sha256 is not a file"
}
```
<!-- scry-reference:end golden_check -->

<!-- scry-reference:begin audio_measure -->
## `audio_measure`

*Measure a WAV recording*

```text
audio_measure(path, window=null, channel=null)
```

Measure a WAV (what `audio_record` writes) and answer whether it sounded, how loud, when
and whether it clipped, as numbers: the sound itself never comes back.

`path`: the path of an 8- or 16-bit PCM WAV. `window` [from_s, to_s], seconds
(default the whole file). `channel` (default every channel).

A chip resting at a steady level is silent: the RMS and the plateau read the window less its
mean, the silences read it through a DC blocker, the onset against its first sample, the
peak as written (a square wave's flat top reads as a plateau too).
Reply, per channel in `measures` (`channel`, 0 the first, the left of a stereo file):
`peak_dbfs` and `rms_dbfs` (unavailable for zero), `silent` (an RMS under 0.5% of full scale),
`silence_spans` (`count`, and the `first` [from_s, to_s] quieter than -60 dBFS for 50 ms or
more, unavailable with none), `onset_s` (the first sample over 2% of the peak, from the
file's start; unavailable when silent), `clipping_run` (the longest run of flat samples at
95% of the peak or above) and `clipped` (a run past 8); then `sample_rate_hz`, `channels`,
`bits`, `window` and `pcm_sha256` (the window's frames, every channel's, for an exact
comparison), and `path`.

Reads files only: it needs no machine and alters nothing. Every path is absolute or starts with `~`.

Reference: REFERENCE.md, Media files.

| argument | type | default |
|---|---|---|
| `path` | string | required |
| `window` | array of number or null | `null` |
| `channel` | integer or null | `null` |

| reply field | type |
|---|---|
| `bits` | integer |
| `channels` | integer |
| `measures` | array |
| `path` | string |
| `pcm_sha256` | string |
| `sample_rate_hz` | integer |
| `window` | array |

Example, from a live run:

```json
{
  "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/L/f4.wav"
}
```

```json
{
  "summary": "audio_measure: ch0 peak -8.55 dBFS, onset 0.0001 s",
  "status": "ok",
  "sample_rate_hz": 48000,
  "channels": 1,
  "bits": 16,
  "window": [
    0.0,
    0.6
  ],
  "measures": [
    {
      "channel": 0,
      "peak_dbfs": -8.55,
      "rms_dbfs": -12.36,
      "silent": false,
      "silence_spans": {
        "count": 0,
        "first": {
          "available": false,
          "why": "no silence in the window"
        }
      },
      "onset_s": 0.0001,
      "clipping_run": 0,
      "clipped": false
    }
  ],
  "pcm_sha256": "9c808cd852605b03eea32b76138f7c9f518c7f2f29e3b9ca76530161be7301fb",
  "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/L/f4.wav"
}
```
<!-- scry-reference:end audio_measure -->

<!-- scry-reference:begin audio_diff -->
## `audio_diff`

*Compare two WAV recordings*

```text
audio_diff(a, b, window=null, align=true)
```

Compare two WAVs of one format, `b` the reference, and answer how close they are as
numbers.

`a`, `b`: paths of 8- or 16-bit PCM WAVs of one rate, channel count and width.
`window` [from_s, to_s], seconds, on each. `align` (default true) drops the head of the
later one so the two onsets meet, so a recording that starts later is not called different
for it. Each channel is compared with its twin and the worst grades. THE CONTROL: two
recordings both `silent` (as `audio_measure` says) over the window compare nothing, so that
is `control_silent`.

Reply: `exact` (the windows' bytes equal), `snr_db` (signal to error, the reference's
energy over the difference's, the worst channel's; unavailable when equal after alignment),
`class` (`exact`, `inaudible` at 60 dB or more, `audible` 30 to 60, `different` under 30 or
lengths a tenth of a second apart), `envelope_correlation` (of the 64-window energy
envelopes, the worst channel's), `onset_delta_ms` (a's onset minus b's),
`length_delta_samples` (a's minus b's), `aligned_by_samples` (positive: a's head dropped;
negative: b's), and `a`, `b`.

Reads files only: it needs no machine and alters nothing. Every path is absolute or starts with `~`.

Reference: REFERENCE.md, Media files.

| argument | type | default |
|---|---|---|
| `a` | string | required |
| `b` | string | required |
| `window` | array of number or null | `null` |
| `align` | boolean | `true` |

| reply field | type |
|---|---|
| `a` | string |
| `b` | string |
| `aligned_by_samples` | integer |
| `envelope_correlation` | number |
| `exact` | boolean |
| `length_delta_samples` | integer |
| `onset_delta_ms` | number |
| `snr_db` | number or object |
| `class` | string |

Example, from a live run:

```json
{
  "a": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/L/f7.wav",
  "b": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/L/f4.wav"
}
```

```json
{
  "summary": "audio_diff: exact, equal, envelope 1.0",
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
  "a": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/L/f7.wav",
  "b": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/L/f4.wav"
}
```
<!-- scry-reference:end audio_diff -->

Channels are compared one by one, never through a mixdown: a channel in antiphase cancels, and two swapped channels average to one sound.

<!-- scry-reference:begin map_load -->
## `map_load`

*Load a screen map*

```text
map_load(path)
```

An application's SCREEN MAP as the FILE layer, replacing any loaded one: its screens, each known by the `scry-sig/1` signatures of declared stable regions, and the named controls on each. `path`: `<application>.scry-map.json`, absolute or `~`-led. It lives for the server; a `start` keeps it. Any state, before a session too.

Reply: `path`, `application`, `screens`, `controls` (counts). Refused whole, naming the first fault: a file that is not `scry-map/1`, a name used twice, a rectangle off its screen, an `application` other than the file's name says (`bad_argument`).

Reference: REFERENCE.md, Screen maps.

| argument | type | default |
|---|---|---|
| `path` | string | required |

| reply field | type |
|---|---|
| `application` | string |
| `controls` | integer |
| `path` | string |
| `screens` | integer |

Example, from a live run:

```json
{
  "path": "/nonexistent/m.scry-map.json"
}
```

```json
{
  "summary": "map_load: INVALID (bad_argument), path: no map file at /nonexistent/m.scry-map.json",
  "status": "INVALID",
  "code": "bad_argument",
  "message": "path: no map file at /nonexistent/m.scry-map.json"
}
```
<!-- scry-reference:end map_load -->

<!-- scry-reference:begin map_save -->
## `map_save`

*Save the screen map*

```text
map_save(dest, overwrite=false)
```

The file layer and the session layer written as ONE map, the session's screens winning, and that file made the file layer (the session's screens are `promoted`). `dest` is the file to write, named as `map_load`'s `path` is; one already there is refused unless `overwrite`. Any state.

Reply: `path` (the `dest` written), `application`, `screens`, `controls`, `promoted`. Refused: nothing mapped (`needs_call`); a `dest` not named as a map is, or there without `overwrite` (`bad_argument`).

Reference: REFERENCE.md, Screen maps.

| argument | type | default |
|---|---|---|
| `dest` | string | required |
| `overwrite` | boolean | `false` |

| reply field | type |
|---|---|
| `application` | string |
| `controls` | integer |
| `path` | string |
| `promoted` | array |
| `screens` | integer |

Example, from a live run:

```json
{
  "dest": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f8.scry-map.json",
  "overwrite": true
}
```

```json
{
  "summary": "map_save: 1 screen to f8.scry-map.json, 1 promoted from the session",
  "status": "ok",
  "path": "$TMPDIR/mame-live-matrix-4d06f0dea223/jobs-scratch/A/f8.scry-map.json",
  "application": "f8",
  "screens": 1,
  "controls": 0,
  "promoted": [
    "probe"
  ]
}
```
<!-- scry-reference:end map_save -->

<!-- scry-reference:begin snapshot -->
## `snapshot`

*Snapshot the screen to a PNG*

```text
snapshot(dest="")
```

Save a PNG of the screen as it is NOW, through the session's `view`, numbered in the scratch,
or moved to `dest`.

Reply: `path`, `bytes`, `sha256` (of the file, the hash a golden's `checksums.sha256` compares),
`view` (`start`'s).
The file must be a complete PNG (signature and IEND trailer) within a short wait, else
`status: INVALID` with `message`. `dest` must be absolute or `~`-led, in a directory that exists, with no comma, semicolon, quote, whitespace, bracket or control character, and not there yet, judged before
the console is touched. A SEMANTIC frame is `run_to` the point where the drawer finishes, then
this; a scratch snapshot dies with `close`, so give a `dest` to keep one. Works on a
RUNNING machine, which is what a watched run wants.

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
  "summary": "snapshot: 441 bytes at $TMPDIR/mame-mcp-vr90lqz3/snap/snapshot-1.png",
  "status": "ok",
  "path": "$TMPDIR/mame-mcp-vr90lqz3/snap/snapshot-1.png",
  "bytes": 441,
  "sha256": "59fdab49a181cabd8045fbef879ebff22316aa2704e290511c90809736f1adcf",
  "view": "native"
}
```
<!-- scry-reference:end snapshot -->

The console's `snap` treats even an absolute path as relative to the snapshot directory, which is why the tool snaps under its own name and moves the file.

<!-- scry-reference:begin captures -->
## `captures`

*List this session's captures*

```text
captures()
```

Every file `record` (an AVI), `audio_record` (a WAV), `trace` (a `.trace`; its set file is
not listed), `snapshot` (a PNG) and a graphics tool (an `image`) checked and handed back THIS
session, in the scratch or at the `dest` they were given, re-read now; a recording its call
answered still open or not begun is not listed, its path being in that reply. `kind` is the
extension (`avi`, `wav`, `png`, `trace`) or `image`. `bytes`, and for an AVI the `avi_frames`
its header declares, for a WAV its `samples`, `channels` and `sample_rate_hz` (each unavailable
once the file no longer reads as finished, or is gone); a file gone since is listed with
`present: false` rather than dropped. Answers while the machine runs.

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
      "path": "$TMPDIR/mame-mcp-vr90lqz3/snap/snapshot-1.png",
      "present": true,
      "bytes": 441
    }
  ]
}
```
<!-- scry-reference:end captures -->
