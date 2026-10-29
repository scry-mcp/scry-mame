# The Machine tools

<!-- scry-reference:begin cpu_info -->
## `cpu_info`

*What the debugger sees of each cpu*

```text
cpu_info(cpu="")
```

What the debugger sees of each cpu now: visibility, ignored or suspended, program counter,
and the breakpoints, watches and registerpoints declared on it. Moves nothing; answers on a
running machine.

Arguments: `cpu`, a tag in either spelling (`subcpu` or `:subcpu`), narrows the rows.

Refused: a tag no row names (`unknown_ref`); no machine (`no_session`); a broken session
(`session_broken`).

Reply: `cpus` (each `cpu`, `visible`, `ignored`, `suspended`, `pc`, `declarations`), `cpu`.

Reference: REFERENCE.md, The session.

| argument | type | default |
|---|---|---|
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `cpu` | string or object |
| `cpus` | array |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "cpu_info: 2 cpus, :maincpu visible",
  "status": "ok",
  "cpus": [
    {
      "cpu": ":maincpu",
      "visible": true,
      "ignored": false,
      "suspended": false,
      "pc": {"reg": "PC", "value": "0x000f2034"},
      "declarations": {"breakpoints": 0, "watches": 0, "regpoints": 0}
    },
    {
      "cpu": ":subcpu",
      "visible": false,
      "ignored": false,
      "suspended": false,
      "pc": {"reg": "PC", "value": "0x00000000"},
      "declarations": {"breakpoints": 0, "watches": 0, "regpoints": 0}
    }
  ],
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"}
}
```
<!-- scry-reference:end cpu_info -->

Two things no reply carries, because neither the console nor Lua shows them without moving the machine: a cpu the BOARD holds in reset or on its halt line, and, without the thread patch, the registers of any cpu but the first.

A cpu's type and clock are `machine_map`'s, not this tool's. `visible` is the cpu a call naming none acts on, and a stop moves it; `ignored` means its breakpoints and watches have no effect; `suspended` is the debugger's own `suspend`. Rows follow `cpulist`'s order, then any other cpu a declaration names; for a cpu `cpulist` does not list, the first three are unavailable. `declarations` counts this server's breakpoints, watches (an io tap among them) and regpoints in any state, and an expr watch names no cpu. Naming `cpu` reads only that cpu's pc. The listings are the console's own and each pc is read off the stub, which is why no cpu is made visible and nothing runs; `unknown_ref` names the tags that do have rows.

<!-- scry-reference:begin machine_map -->
## `machine_map`

*Map the machine*

```text
machine_map(cpu="", sections=null)
```

What the machine is: its cpus and spaces, address map, regions, shares, screens and ROM
files. Cached at `start()`, free; answered on a running machine.

Arguments: `cpu`, a tag in either spelling, narrows `cpus`, `spaces`, `address_map` and
`symbol_coverage`. `sections` picks sections; left out, all but `rom_files`.

Refused: an empty or unknown `sections` (`bad_argument`); an unknown tag (`unknown_ref`); no
machine (`no_session`); a broken session (`session_broken`).

Reply: `cpus`, `spaces`, `address_map`, `regions`, `shares`, `screens`, `rom_files`,
`symbol_coverage`, `counts`, `truncated` (lists are cut to 400 rows), `sources`,
`note`, `frame_symbol`. A field no source backs is absent.

Reference: REFERENCE.md, Reading and writing.

| argument | type | default |
|---|---|---|
| `cpu` | string | `""` |
| `sections` | array of one of `"cpus"`, `"spaces"`, `"address_map"`, `"regions"`, `"shares"`, `"screens"`, `"rom_files"`, `"symbol_coverage"` or null | `null` |

| reply field | type |
|---|---|
| `address_map` | array |
| `counts` | object |
| `cpu` | string or object |
| `cpus` | array |
| `frame_symbol` | string or object |
| `regions` | array |
| `rom_files` | array |
| `screens` | array |
| `shares` | array |
| `sources` | object |
| `spaces` | array |
| `symbol_coverage` | array |
| `truncated` | boolean |

Example, from a live run:

```json
{}
```

```json
{
  "summary": "machine_map: 2 cpus, 4 spaces, 32 address map entries, 4 regions, 2 shares, 1 screen, left out: rom_files (see `omitted`)",
  "status": "ok",
  "cpus": [
    {
      "cpu": ":maincpu",
      "name": "Motorola MC68000",
      "clock_hz": 16000000,
      "type": "m68000",
      "spaces": ["cpu_space", "program"]
    },
    {
      "cpu": ":subcpu",
      "name": "Motorola MC68000",
      "clock_hz": 16000000,
      "type": "m68000",
      "spaces": ["cpu_space", "program"]
    }
  ],
  "spaces": [
    {
      "cpu": ":maincpu",
      "space": "cpu_space",
      "data_width_bits": 16,
      "endianness": "big",
      "entries": 7,
      "address_mask": "0x00ffffff"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "data_width_bits": 16,
      "endianness": "big",
      "entries": 13,
      "address_mask": "0x00ffffff"
    },
    {
      "cpu": ":subcpu",
      "space": "cpu_space",
      "data_width_bits": 16,
      "endianness": "big",
      "entries": 7,
      "address_mask": "0x00ffffff"
    },
    {
      "cpu": ":subcpu",
      "space": "program",
      "data_width_bits": 16,
      "endianness": "big",
      "entries": 5,
      "address_mask": "0x00ffffff"
    }
  ],
  "address_map": [
    {"cpu": ":maincpu", "space": "cpu_space", "index": 1, "start": "0x00fffff3", "end": "0x00fffff3"},
    {"cpu": ":maincpu", "space": "cpu_space", "index": 2, "start": "0x00fffff5", "end": "0x00fffff5"},
    {"cpu": ":maincpu", "space": "cpu_space", "index": 3, "start": "0x00fffff7", "end": "0x00fffff7"},
    {"cpu": ":maincpu", "space": "cpu_space", "index": 4, "start": "0x00fffff9", "end": "0x00fffff9"},
    {"cpu": ":maincpu", "space": "cpu_space", "index": 5, "start": "0x00fffffb", "end": "0x00fffffb"},
    {"cpu": ":maincpu", "space": "cpu_space", "index": 6, "start": "0x00fffffd", "end": "0x00fffffd"},
    "... 26 more"
  ],
  "regions": [
    {"tag": ":gfx1", "size": 16777216, "bytewidth": 1, "endianness": "little"},
    {"tag": ":maincpu", "size": 1048576, "bytewidth": 2, "endianness": "big"},
    {"tag": ":plds", "size": 741, "bytewidth": 1, "endianness": "little"},
    {"tag": ":subcpu", "size": 1048576, "bytewidth": 2, "endianness": "big"}
  ],
  "shares": [
    {"tag": ":blitram", "size": 32, "bytewidth": 2, "endianness": "big"},
    {"tag": ":mainram", "size": 65536, "bytewidth": 2, "endianness": "big"}
  ],
  "screens": [
    {
      "tag": ":screen",
      "width": 336,
      "height": 252,
      "refresh_hz": 50.080128,
      "rotation": 0,
      "type": "raster"
    }
  ],
  "symbol_coverage": [],
  "counts": {
    "cpus": 2,
    "spaces": 4,
    "address_map": 32,
    "regions": 4,
    "shares": 2,
    "screens": 1,
    "symbol_coverage": 0
  },
  "truncated": false,
  "sources": {
    "cpus": ["live", "-listxml"],
    "spaces": ["live"],
    "address_map": ["live"],
    "regions": ["live"],
    "shares": ["live"],
    "screens": ["live", "-listxml"],
    "symbol_coverage": ["symbols"]
  },
  "note": "the address map is the map of the machine's EXECUTING devices, which is what MAME gives a debugger: a device that only exposes an address space of its own is not in it, though its shares and regions are; the map reported is the STATICALLY C ... (844 characters)",
  "omitted": ["rom_files"],
  "how": "sections=[...] names the sections to answer",
  "frame_symbol": "frame",
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"}
}
```
<!-- scry-reference:end machine_map -->

**Two sources are the emulator's, because neither carries the whole answer, and each section says which backs it** (`sources`). `-listxml`, run once against THIS session's binary, is the only one with a clock, a rotation and a ROM file's crc and sha1; the live machine is the only one with the shares, the regions' sizes, the address map and a cpu's `type`, because on the Lua channel a device's clock reads back nil. Where both back a field and differ, the `note` names both and the field carries the LIVE one, which is the machine actually running; nothing decides which is correct, so the disagreement is in front of you instead of resolved in silence. A field NEITHER source backs is absent, never null or guessed.

**The live half is gathered by the boot harness**, not by a console evaluation at the park (the route `read_block` takes), which costs a step and moves the pc. One route owns it whole, because a gather split between two is where two accounts of one fact diverge. A dump missing a sentinel is refused: a truncated inventory cannot be told from a small machine.

**The cpus are the devices MAME gives a `debug`**, those that EXECUTE; the XML half cannot decide it, because a build that fails `-listxml` must still produce a session.

**`symbol_coverage` names its source** (`symbols`) because a section whose provenance is missing cannot be told from an oversight, and `cpu=` leaves the ROM files whole because narrowing them would say the other cpu's ROMs do not exist.

Row fields. `cpus`: `cpu`, `type` (MAME's shortname, `m68000`), `name`, `clock_hz`, `spaces`. `spaces`: `cpu`, `space`, `data_width_bits`, `endianness`, `entries`, and `address_mask` where a source backs it. `address_map`: `cpu`, `space`, `index`, `start`, `end`, `share` or `region`+`region_offset` by the full tag `regions` and `shares` carry, and the entry's own `mirror` and `address_mask` when not zero. `regions`/`shares`: `tag`, `size`, `bytewidth`, `endianness`. `screens`: `tag`, `width`, `height`, `refresh_hz`, `rotation`, `type`. `rom_files`: `name`, `size`, `crc`, `sha1`, `dump_status`, `region`, `offset`. `symbol_coverage`: one row per class of each cpu's table (`cpu`, `span`, `symbols`, `base`), an empty list when no table has classes. `counts` is each section's full count; `omitted` and `how` name the sections left out. `note` records a disagreement between sources (the live value kept), banked ranges, and that this is the machine as `start` read it. `frame_symbol` is the frame counter's name, unavailable on a board with none. A refused tag's `unknown_ref` names the ones the machine has.

<!-- scry-reference:begin log -->
## `log`

*Read the log*

```text
log(pattern, channel, limit=40, labels=false, since_mark=0)
```

The newest lines of one `channel` of what MAME writes matching the regex `pattern` (`.` for
all; never empty). Works while running.

`channel`: `emulator`, `process` or `all` (lines tagged `[emulator] `, `[process] `);
`guest` is refused. `labels=True` adds `labels`, lines counted by first word.
`since_mark` reads only what follows that log byte position.

Reply: `pattern`, `channel`, `lines` (the newest `limit`, 1..400, oldest first),
`lines_total`, `truncated`, `counts` (on channel `all`), `labels`. A bad `limit`, regex or
`since_mark` is refused.

Reference: REFERENCE.md, The log.

| argument | type | default |
|---|---|---|
| `pattern` | string | required |
| `channel` | one of `"emulator"`, `"process"`, `"all"` | required |
| `limit` | integer (>= 1, <= 400) | `40` |
| `labels` | boolean | `false` |
| `since_mark` | integer (>= 0) | `0` |

| reply field | type |
|---|---|
| `channel` | string |
| `counts` | object |
| `labels` | object |
| `lines` | array |
| `lines_total` | integer |
| `pattern` | string |
| `truncated` | boolean |

Example, from a live run:

```json
{
  "pattern": ".",
  "channel": "emulator",
  "limit": 3
}
```

```json
{
  "summary": "log emulator /./: 1 of 1 line",
  "status": "ok",
  "pattern": ".",
  "channel": "emulator",
  "lines_total": 1,
  "truncated": false,
  "lines": ["Soft reset"]
}
```
<!-- scry-reference:end log -->

The `emulator` channel is `error.log`, which every launch writes.

Pass a pattern that narrows: `.` is a last resort. `since_mark` is a byte position in the channel's log (the `mark` a state load or a stop's log block gives): only what was written after it is read; 0, the default, reads the whole log, and it is not accepted over `all`, two files. `emulator` is `error.log` (core and driver `logerror`), `process` is `stdout.log` (stdout and stderr). A driver's own `logerror` traffic can run to hundreds of lines per emulated second, so a default-pattern read is mostly somebody else's noise with the wanted line buried in it; the same goes for `drive`'s `pattern`. `process` is where `osd_printf_error`, `-verbose` and a driver's own counters go, and `labels` gives one glance at who is talking (`RE_DAC`, `RE_IRQ`). `guest` is a channel an arcade board does not have.

<!-- scry-reference:begin log_wait -->
## `log_wait`

*Wait for a log line*

```text
log_wait(pattern, channel, seconds=30.0, since_mark=0)
```

Wait up to `seconds` for a line of `channel` matching the regex `pattern` (never empty);
at once if the log holds it. Answers while running. `channel`, `since_mark` as in `log`.

Refused: `wait_stopped` when stopped and the log lacks the line; `session_broken`; a bad
`seconds`, regex or `since_mark`.

Reply: `verdict` `TARGET`, `line` (the first match), `already`, `waited_s`, `lines_before`,
`lines_total`, `arrived_during`, `lines_examined`; on timeout `verdict` `TIMEOUT`, `note`.

Reference: REFERENCE.md, The log.

| argument | type | default |
|---|---|---|
| `pattern` | string | required |
| `channel` | one of `"emulator"`, `"process"`, `"all"` | required |
| `seconds` | number (> 0, <= 600.0) | `30.0` |
| `since_mark` | integer (>= 0) | `0` |

| reply field | type |
|---|---|
| `already` | boolean |
| `arrived_during` | integer |
| `channel` | string |
| `line` | string |
| `lines_before` | integer |
| `lines_examined` | integer |
| `lines_total` | integer |
| `pattern` | string |
| `verdict` | string |
| `waited_s` | number |

Example, from a live run:

```json
{
  "pattern": ".",
  "channel": "emulator",
  "seconds": 5.0
}
```

```json
{
  "summary": "log_wait emulator /./: matched already there",
  "status": "ok",
  "verdict": "TARGET",
  "pattern": ".",
  "channel": "emulator",
  "line": "Soft reset",
  "already": true,
  "lines_total": 779,
  "lines_before": 0,
  "arrived_during": 0,
  "waited_s": 0.0,
  "lines_examined": 788
}
```
<!-- scry-reference:end log_wait -->

It is the proof that a run reached what it was meant to reach; `log` is the tool for the newest match. With `since_mark`, "already" means since the mark, which is how "after the load" is asked. A stopped machine logs nothing, so the wait could not end; a stop landing during the wait is reported the same way after one last read of the log. On a timeout the machine still runs. It reports progress while it waits.
