# The Machine tools

<!-- scry-reference:begin cpu_info -->
## `cpu_info`

*What the debugger sees of each cpu*

```text
cpu_info(cpu="")
```

WHAT THE DEBUGGER SEES OF EACH CPU at the call, one row per cpu: whether it is visible,
ignored or suspended, its program counter, and how many breakpoints, watches and
registerpoints are declared on it, moving nothing: the listings are the console's own and
each pc register is read off the stub, so no cpu is made visible and nothing runs. Answers
on a RUNNING machine too. What a cpu IS (its type, clock, spaces) is `machine_map`'s.

Arguments: `cpu`, a tag in either spelling (`subcpu` or `:subcpu`), narrows the rows to that
cpu's, and only its pc is read; empty is every cpu.

Refused: a tag no row names (`unknown_ref` naming the ones that do); no machine
(`no_session`); a session that broke, a read that latched it included (`session_broken`).

Reply: `cpus`, one row per cpu `cpulist` lists, in its order, then one per other cpu a
declaration names: `cpu`, `visible` (the cpu a call naming none acts on; a stop moves it),
`ignored` (its breakpoints and watches have no effect), `suspended` (held by the debugger's
own `suspend`), `pc` (its program counter register, `reg` and `value`, or unavailable with
why, as while it runs), `declarations` (this server's `breakpoints`, `watches`, an io tap
among them, and `regpoints` on it, counted in any state; an expr watch names no cpu).
`visible`, `ignored` and `suspended` are unavailable when the console did not answer, and
all four for a cpu `cpulist` does not list; `declarations` is always counted. `cpu` (unavailable
unless named).

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
      "pc": {
        "reg": "PC",
        "value": "0x000f2034"
      },
      "declarations": {
        "breakpoints": 0,
        "watches": 0,
        "regpoints": 0
      }
    },
    {
      "cpu": ":subcpu",
      "visible": false,
      "ignored": false,
      "suspended": false,
      "pc": {
        "reg": "PC",
        "value": "0x00000000"
      },
      "declarations": {
        "breakpoints": 0,
        "watches": 0,
        "regpoints": 0
      }
    }
  ],
  "cpu": {
    "available": false,
    "why": "no cpu was named, so the rows are every cpu's"
  }
}
```
<!-- scry-reference:end cpu_info -->

Two things no reply carries, because neither the console nor Lua shows them without moving the machine: a cpu the BOARD holds in reset or on its halt line, and, without the thread patch, the registers of any cpu but the first.

<!-- scry-reference:begin machine_map -->
## `machine_map`

*Map the machine*

```text
machine_map(cpu="", sections=null)
```

WHAT THE MACHINE IS, rather than what is on it: its cpus and their spaces, every address map
entry and the share or region it names, the blocks by tag and size, its screens, and its ROM
files with their crc. Cached at `start()`: free, the same every time, and answered on a
RUNNING machine too.

Arguments: `cpu`, a tag in either spelling (`maincpu` or `:maincpu`), narrows `cpus`, `spaces`,
`address_map` and `symbol_coverage` to one; the blocks, screens and ROM files stay whole.
`sections` names the sections to answer; left out, all but `rom_files` (then in `omitted`).

Refused: an empty or unknown `sections` (`bad_argument`); a tag this machine lacks
(`unknown_ref` naming the ones it has); no machine (`no_session`); a broken session
(`session_broken`).

Reply: `cpus` (`cpu`, `type` (MAME's shortname, `m68000`), `name`, `clock_hz`, `spaces`),
`spaces` (`cpu`, `space`, `data_width_bits`, `endianness`, `entries`, and the space's last
address `address_mask` where a source backs it), `address_map` (`cpu`, `space`, `index`,
`start`, `end`, `share` or `region`+`region_offset` by the full tag `regions` and `shares`
carry, and the ENTRY's own `mirror` and `address_mask` when not zero), `regions` and `shares`
(`tag`, `size`, `bytewidth`, `endianness`), `screens` (`tag`, `width`, `height`, `refresh_hz`,
`rotation`, `type`), `rom_files` (`name`, `size`, `crc`, `sha1`, `dump_status`, `region`,
`offset`), `symbol_coverage` (one row per class of each cpu's table: `cpu`, `span`, `symbols`,
`base`; an empty list when no table has classes), `counts` (each section's full count),
`truncated` (a boolean: each list section is cut to 400 rows), `sources` (which source
backs each section; a field none backs is ABSENT), `omitted`/`how`, `note` (a disagreement
between sources, the live value kept; banked ranges; and that this is the machine as `start`
read it), and `frame_symbol` (the frame counter's name; unavailable, saying what that changes,
on a board with none).

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
| `note` | string |
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
      "spaces": [
        "cpu_space",
        "program"
      ]
    },
    {
      "cpu": ":subcpu",
      "name": "Motorola MC68000",
      "clock_hz": 16000000,
      "type": "m68000",
      "spaces": [
        "cpu_space",
        "program"
      ]
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
    {
      "cpu": ":maincpu",
      "space": "cpu_space",
      "index": 1,
      "start": "0x00fffff3",
      "end": "0x00fffff3"
    },
    {
      "cpu": ":maincpu",
      "space": "cpu_space",
      "index": 2,
      "start": "0x00fffff5",
      "end": "0x00fffff5"
    },
    {
      "cpu": ":maincpu",
      "space": "cpu_space",
      "index": 3,
      "start": "0x00fffff7",
      "end": "0x00fffff7"
    },
    {
      "cpu": ":maincpu",
      "space": "cpu_space",
      "index": 4,
      "start": "0x00fffff9",
      "end": "0x00fffff9"
    },
    {
      "cpu": ":maincpu",
      "space": "cpu_space",
      "index": 5,
      "start": "0x00fffffb",
      "end": "0x00fffffb"
    },
    {
      "cpu": ":maincpu",
      "space": "cpu_space",
      "index": 6,
      "start": "0x00fffffd",
      "end": "0x00fffffd"
    },
    "... 26 more"
  ],
  "regions": [
    {
      "tag": ":gfx1",
      "size": 16777216,
      "bytewidth": 1,
      "endianness": "little"
    },
    {
      "tag": ":maincpu",
      "size": 1048576,
      "bytewidth": 2,
      "endianness": "big"
    },
    {
      "tag": ":plds",
      "size": 741,
      "bytewidth": 1,
      "endianness": "little"
    },
    {
      "tag": ":subcpu",
      "size": 1048576,
      "bytewidth": 2,
      "endianness": "big"
    }
  ],
  "shares": [
    {
      "tag": ":blitram",
      "size": 32,
      "bytewidth": 2,
      "endianness": "big"
    },
    {
      "tag": ":mainram",
      "size": 65536,
      "bytewidth": 2,
      "endianness": "big"
    }
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
    "cpus": [
      "live",
      "-listxml"
    ],
    "spaces": [
      "live"
    ],
    "address_map": [
      "live"
    ],
    "regions": [
      "live"
    ],
    "shares": [
      "live"
    ],
    "screens": [
      "live",
      "-listxml"
    ],
    "symbol_coverage": [
      "symbols"
    ]
  },
  "note": "the address map is the map of the machine's EXECUTING devices, which is what MAME gives a debugger: a device that only exposes an address space of its own is not in it, though its shares and regions are; the map reported is the STATICALLY C ... (844 characters)",
  "omitted": [
    "rom_files"
  ],
  "how": "sections=[...] names the sections to answer",
  "frame_symbol": "frame",
  "cpu": {
    "available": false,
    "why": "no cpu was named, so the rows are every cpu's"
  }
}
```
<!-- scry-reference:end machine_map -->

**Two sources are the emulator's, because neither carries the whole answer, and each section says which backs it** (`sources`). `-listxml`, run once against THIS session's binary, is the only one with a clock, a rotation and a ROM file's crc and sha1; the live machine is the only one with the shares, the regions' sizes, the address map and a cpu's `type`, because on the Lua channel a device's clock reads back nil. Where both back a field and differ, the `note` names both and the field carries the LIVE one, which is the machine actually running; nothing decides which is correct, so the disagreement is in front of you instead of resolved in silence. A field NEITHER source backs is absent, never null or guessed.

**The live half is gathered by the boot harness**, not by a console evaluation at the park (the route `read_block` takes), which costs a step and moves the pc. One route owns it whole, because a gather split between two is where two accounts of one fact diverge. A dump missing a sentinel is refused: a truncated inventory cannot be told from a small machine.

**The cpus are the devices MAME gives a `debug`**, those that EXECUTE; the XML half cannot decide it, because a build that fails `-listxml` must still produce a session.

**`symbol_coverage` names its source** (`symbols`) because a section whose provenance is missing cannot be told from an oversight, and `cpu=` leaves the ROM files whole because narrowing them would say the other cpu's ROMs do not exist.

<!-- scry-reference:begin symbols_find -->
## `symbols_find`

*Look a symbol up*

```text
symbols_find(name="", linear="", limit=10, cpu="")
```

Look a symbol up in a cpu's table, the one `start` loaded for it: `cpu`'s (`subcpu`),
else the visible cpu's, named in the reply as `cpu`. One question per call: `name` (exact
match, else prefix matches ordered by address, up to `limit` (1..50: each symbol
answered costs the console one `map`), `truncated` saying whether it bit; matched WITHOUT regard
to case, so `vec_irq1` finds `VEC_IRQ1`), or `linear` (a `0x` address as the debugger shows it:
what am I inside? The nearest symbol AT OR BELOW and the distance above it, since the table
carries no sizes).

`linear` IS THE ADDRESS AT RUN TIME, after `bases`: the one `read_memory`, `disassemble`
and a stop's `pc` show. It is NOT the `linear` column a linker map prints, which is the
address BEFORE the bases `start` applied; that column passed here answers a plausible
symbol with an absurd delta.

Reply: by name, `query`, `symbols_total` (how many matched) and `symbols` (`name`, `addr`,
`memory`);
by address, `linear`, `name`, `addr`, `delta`, `memory`. `memory` is what the address IS
to the machine, from the console's `map`: `ram` (written and read through memory, a
change watch fires there), `rom` (nothing writes it: the ROM copy of a datum, or code),
`latch` (written through a handler, read nowhere: `read_memory` answers zeros there,
and when the map entry keeps a share, `read_block(ref=...)` reads it), `handlers` (read
and written through
handlers, a paired region: readable, not plain memory), `unmapped`; `unknown` on a RUNNING
machine, where the console cannot be asked (the `note` says so), or where `map` names no
side. `status: INVALID` with no symbol table (`no_channel`), or for an address below every
symbol (`unknown_ref`). Answers on a running machine: the table is not a value read off it.

Reference: REFERENCE.md, Names for addresses.

| argument | type | default |
|---|---|---|
| `name` | string | `""` |
| `linear` | string | `""` |
| `limit` | integer (>= 1, <= 50) | `10` |
| `cpu` | string | `""` |

| reply field | type |
|---|---|
| `addr` | string |
| `cpu` | string |
| `delta` | integer |
| `linear` | string |
| `memory` | string |
| `name` | string |
| `note` | string |
| `query` | string |
| `symbols` | array |
| `symbols_total` | integer |
| `truncated` | boolean |

Example, from a live run:

```json
{
  "name": "irq_vblank"
}
```

```json
{
  "summary": "symbols_find irq_vblank: 1 match",
  "status": "ok",
  "query": "irq_vblank",
  "cpu": ":maincpu",
  "symbols_total": 1,
  "symbols": [
    {
      "name": "IRQ_VBLANK",
      "addr": "0x00000400",
      "memory": "rom"
    }
  ],
  "truncated": false
}
```
<!-- scry-reference:end symbols_find -->

`memory` is answered so that a change watch on the ROM copy of a datum is known to be pointless before it is tried.

<!-- scry-reference:begin log -->
## `log`

*Read the log*

```text
log(pattern, channel, limit=40, labels=false, since_mark=0)
```

The newest lines of one `channel` of what MAME writes, matching the regex `pattern` (`.`
for every line; never empty).

`channel` is `emulator` (`error.log`: what the core and the drivers say through
`logerror`), `process` (`stdout.log`: the process's own stdout and stderr, where
`osd_printf_error` and `-verbose` go, a driver's own counters among them) or `all` (both,
each line tagged `[emulator] ` or `[process] `, with `counts` per source); `guest` names a
channel an arcade board does not have, and is refused by name.
`labels=True` adds `labels`, how many returned lines carry each first word (`RE_DAC`,
`RE_IRQ`): one glance at who is talking. `since_mark`, a byte position in the channel's log (the `mark` a `state_load` or a stop's log block gives for it): only what was written after it is read; 0, the default, reads the whole log (not over `all`, two files).

PASS A PATTERN THAT NARROWS, always, and treat `.` as a last resort. A driver's own
`logerror` traffic can run to hundreds of lines per emulated second, so a default-pattern read
is mostly somebody else's noise
with the line you want buried in it. The same goes for `drive`'s `pattern`.

Reply: `pattern`, `channel`, `lines` (the newest `limit` matches, 1..400, oldest
first), `lines_total` (every match in the file), `truncated`. `status: INVALID` with `message`
when no file of the channel exists yet; a bad `limit`, an unusable regex, an unknown channel
or a `since_mark` that names no position of the log is refused. Works on a running machine.

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
  "lines": [
    "Soft reset"
  ]
}
```
<!-- scry-reference:end log -->

The `emulator` channel is `error.log`, which every launch writes.

<!-- scry-reference:begin log_wait -->
## `log_wait`

*Wait for a log line*

```text
log_wait(pattern, channel, seconds=30.0, since_mark=0)
```

WHEN a line of `channel` matching the regex `pattern` (`.` for any; never empty) was
logged: at once if the log
already holds it, else wait up to `seconds` for it. The one wait that answers while the
machine RUNS, and the proof that a run reached what it was meant to reach.

`channel` as in `log` (`emulator`, `process`, `all`; over `all` the first match in either
file wins and the line carries its tag). `since_mark` as in `log`: "already" is then "since
the mark", which is how "after the load" is asked.

Reply: `verdict` `TARGET`, `channel`, `line` (the FIRST match; `log` is the tool for the
newest), `already` (it was in the log before this call), `waited_s` (0.0 when already),
`lines_before`, `lines_total`, `arrived_during`, `lines_examined`; when the bound ran out,
`verdict` `TIMEOUT` with `arrived_during`, `lines_examined`, `waited_s` and a `note` (the
machine still runs). `status: INVALID`: `wait_stopped` when the machine is STOPPED and the
log does not already hold the line (a stopped machine logs nothing, so the wait could not
end; the refusal names `last_stop`, and a stop that lands DURING the wait is reported the
same way after one last read of the log), `session_broken` (LATCHED) when the emulator
went away. A
bad `seconds`, an unusable regex, an unknown channel or a
`since_mark` that names no position of the log is refused. Reports its progress while it waits.

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
| `note` | string |
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
