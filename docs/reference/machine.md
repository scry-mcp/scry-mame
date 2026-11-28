# The Machine tools

These tools describe the machine a session runs and read what MAME logs about it. `cpu_info` and `machine_map` say what is there: the cpus, their memory, the screens, the ROM files. `log` and `log_wait` read the lines MAME writes.

All four answer while the program runs. A cpu is named by its MAME tag, with or without the leading colon: `subcpu` or `:subcpu`.

<!-- scry-reference:begin cpu_info -->
## `cpu_info`

List each cpu as the debugger sees it: visible, ignored or suspended, its program counter, and the breakpoints and watches set on it.

```text
cpu_info(cpu="")
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, stopped at reset, right after `start`.

Ask:

> Which cpus does this machine have, and which one is the debugger showing?

Call:

```text
cpu_info()
```

Reply, 1 of 5 fields:

```json
{
  "cpus": [
    {
      "cpu": ":maincpu",
      "visible": true,
      "ignored": false,
      "suspended": false,
      "pc": {"reg": "PC", "value": "0x0000f000"},
      "declarations": {"breakpoints": 0, "watches": 0, "regpoints": 0}
    }
  ]
}
```

Gridlee has one cpu, `:maincpu`. It is the `visible` one, which a call that names no cpu acts on; it sits at `0xf000` and nothing is set on it yet.

<details><summary>The whole reply</summary>

```json
{
  "summary": "cpu_info: 1 cpu, :maincpu visible",
  "status": "ok",
  "cpus": [
    {
      "cpu": ":maincpu",
      "visible": true,
      "ignored": false,
      "suspended": false,
      "pc": {"reg": "PC", "value": "0x0000f000"},
      "declarations": {"breakpoints": 0, "watches": 0, "regpoints": 0}
    }
  ],
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"},
  "names": [
    {
      "field": "cpus[].pc.value",
      "number": "0x0000f000",
      "kind": "symbol",
      "name": "take_credit",
      "delta": 6538
    }
  ]
}
```

</details>

### Arguments

- `cpu` (string, default `""`): The tag of one cpu: only its row comes back and only its `pc` is read. Left empty, every cpu is listed.

### What comes back

- `cpus`: One row per cpu: its tag `cpu`, `visible`, `ignored`, `suspended`, its program counter `pc`, and `declarations`, the count of what is set on it.
- `cpu`: The full tag of the cpu you named; with none named, an object that says so.

<details><summary>All 2 reply fields</summary>

- `cpu` (string or object)
- `cpus` (array)

</details>

### What it refuses

- A tag that names no cpu; the message lists the tags there are (`unknown_ref`).
- A call with no session open (`no_session`).
- A session that broke and has to be closed (`session_broken`).

### Why it works this way

Answering runs nothing and makes no cpu visible: the flags come from the debugger's own listings and each `pc` is read as a register. `visible` marks the cpu that a call naming none acts on, and a stop moves it. `ignored` means breakpoints and watches on that cpu have no effect.

A `pc` is unavailable, with the reason, while the program runs, and for every cpu but the first where MAME's gdbstub serves one cpu. A cpu the board itself holds in reset or halted shows nowhere: telling would mean moving the machine.

<details><summary>More on why</summary>

- `declarations` counts `breakpoints`, `watches` and `regpoints`, armed or not. A regpoint is MAME's registerpoint, a stop on a condition over registers.
- A watch on an io port counts; one on a debugger expression belongs to no cpu and is not counted.
- `suspended` is the debugger's own `suspend`.
- Rows follow the debugger's `cpulist`, then any other cpu a saved breakpoint or watch names; of such a cpu only the counts are read.

</details>

### Related tools

- [`machine_map`](#machine_map)
- [`cpu_focus`](session.md#cpu_focus)
- [`registers`](read.md#registers)
- [`declaration_list`](breakpoints.md#declaration_list)
- [`status`](session.md#status)

<details><summary>The contract your client receives</summary>

```text
What the debugger sees of each cpu now: visibility, ignored or suspended, program counter,
and how many breakpoints, watches and registerpoints are declared on it. Moves nothing;
answers on a running machine.

Arguments: `cpu`, a tag in either spelling (`subcpu` or `:subcpu`), narrows the rows.

Refused: a tag no row names (`unknown_ref`); no machine (`no_session`); a broken session
(`session_broken`).

Reply: `cpus` (each `cpu`, `visible`, `ignored`, `suspended`, `pc`, `declarations`), `cpu`.

Reference: REFERENCE.md, The session.
```

</details>
<!-- scry-reference:end cpu_info -->

<!-- scry-reference:begin machine_map -->
## `machine_map`

Get the layout of the machine: its cpus and their address spaces, the address map, memory regions and shares, screens and ROM files.

```text
machine_map(cpu="", sections=null, dest="")
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, stopped at reset, right after `start`.

Ask:

> What is this board made of: its cpu, its ROMs, its RAM, its screen?

Call:

```text
machine_map()
```

Reply, 2 of 17 fields:

```json
{
  "regions": [
    {"tag": ":gfx1", "size": 16384, "bytewidth": 1, "endianness": "little"},
    {"tag": ":maincpu", "size": 65536, "bytewidth": 1, "endianness": "big"},
    {"tag": ":proms", "size": 6144, "bytewidth": 1, "endianness": "little"}
  ],
  "shares": [
    {"tag": ":nvram", "size": 256, "bytewidth": 1, "endianness": "big"},
    {"tag": ":spriteram", "size": 2048, "bytewidth": 1, "endianness": "big"},
    {"tag": ":videoram", "size": 30720, "bytewidth": 1, "endianness": "big"}
  ]
}
```

`regions` are the ROMs MAME loaded and `shares` the blocks of RAM the board's devices share, each with its size in bytes. The sprite RAM is 2048 bytes.

<details><summary>The whole reply</summary>

```json
{
  "summary": "machine_map: 1 cpu, 1 space, 14 address map entries, 3 regions, 3 shares, 1 screen, left out: rom_files (see `omitted`)",
  "status": "ok",
  "cpus": [
    {
      "cpu": ":maincpu",
      "name": "MC6809 (legacy)",
      "clock_hz": 1250000,
      "type": "m6809",
      "spaces": ["program"]
    }
  ],
  "spaces": [
    {
      "cpu": ":maincpu",
      "space": "program",
      "data_width_bits": 8,
      "endianness": "big",
      "entries": 14,
      "address_mask": "0x0000ffff"
    }
  ],
  "address_map": [
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 1,
      "start": "0x00000000",
      "end": "0x000007ff",
      "share": ":spriteram",
      "read": "ram",
      "write": "ram"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 2,
      "start": "0x00000800",
      "end": "0x00007fff",
      "share": ":videoram",
      "read": "ram",
      "write": "delegate/gridlee_state::gridlee_videoram_w"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 3,
      "start": "0x00009000",
      "end": "0x00009000",
      "read": "none",
      "write": "delegate/[this] (offs_t offset, u8 data) { m_latch->write_d0(offset >> 4, data); }"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 4,
      "start": "0x00009200",
      "end": "0x00009200",
      "read": "none",
      "write": "delegate/gridlee_state::gridlee_palette_select_w"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 5,
      "start": "0x00009380",
      "end": "0x00009380",
      "read": "none",
      "write": "delegate/watchdog_timer_device::reset_w"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 6,
      "start": "0x00009500",
      "end": "0x00009501",
      "read": "delegate/gridlee_state::analog_port_r",
      "write": "none"
    },
    "... 8 more"
  ],
  "regions": [
    {"tag": ":gfx1", "size": 16384, "bytewidth": 1, "endianness": "little"},
    {"tag": ":maincpu", "size": 65536, "bytewidth": 1, "endianness": "big"},
    {"tag": ":proms", "size": 6144, "bytewidth": 1, "endianness": "little"}
  ],
  "shares": [
    {"tag": ":nvram", "size": 256, "bytewidth": 1, "endianness": "big"},
    {"tag": ":spriteram", "size": 2048, "bytewidth": 1, "endianness": "big"},
    {"tag": ":videoram", "size": 30720, "bytewidth": 1, "endianness": "big"}
  ],
  "screens": [
    {
      "tag": ":screen",
      "width": 256,
      "height": 240,
      "refresh_hz": 59.185606,
      "rotation": 0,
      "type": "raster"
    }
  ],
  "symbol_coverage": [],
  "counts": {
    "cpus": 1,
    "spaces": 1,
    "address_map": 14,
    "regions": 3,
    "shares": 3,
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
  "how": "sections=[...] names the sections to read; dest=<absolute path> writes every section read whole",
  "frame_symbol": "frame",
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"}
}
```

</details>

### Arguments

- `cpu` (string, default `""`): The tag of one cpu, to narrow `cpus`, `spaces`, `address_map` and `symbol_coverage` to it. Left empty, every cpu's rows come back.
- `sections` (array of one of `"cpus"`, `"spaces"`, `"address_map"`, `"regions"`, `"shares"`, `"screens"`, `"rom_files"`, `"symbol_coverage"`, optional): Which sections to read. Left out, all of them but `rom_files`.
- `dest` (string, default `""`): A file to write every row of the sections read, as JSON: an absolute or `~` path that does not exist yet. Left empty, no file is written.

### What comes back

- `cpus`: One row per cpu: its tag `cpu`, MAME's short name `type`, `name`, `clock_hz` and the names of its `spaces`.
- `address_map`: One row per entry of a cpu's memory map: `cpu`, `space`, `index`, `start`, `end`, and the `share` or `region` behind it.
- `sources`: For each section, where its rows came from: `live` (the running machine), `-listxml` (MAME's own description of it) or `symbols` (your symbol table).
- `counts`: How many rows each section has in full, so a list cut short shows.
- `truncated`: `true` when a section had more than 400 rows and its list was cut; `dest` gets them all.
- `path`: With `dest`, the file that was written.

<details><summary>All 14 reply fields</summary>

- `address_map` (array)
- `counts` (object)
- `cpu` (string or object)
- `cpus` (array)
- `frame_symbol` (string or object)
- `path` (string)
- `regions` (array)
- `rom_files` (array)
- `screens` (array)
- `shares` (array)
- `sources` (object)
- `spaces` (array)
- `symbol_coverage` (array)
- `truncated` (boolean)

</details>

### What it refuses

- An empty `sections`, a name that is no section, or a `dest` that already exists (`bad_argument`).
- A tag that names no cpu; the message lists the ones the machine has (`unknown_ref`).
- A call with no session open (`no_session`).
- A session that broke and has to be closed (`session_broken`).

### Why it works this way

The map is read once, while `start` boots the machine, so asking costs nothing and it answers while the program runs. It is the machine as `start` found it: nothing reads it again, even after the emulator has died.

Two sources fill it, because neither has everything. MAME's `-listxml`, run on this session's own binary, alone knows a clock, a screen's rotation and a ROM file's checksums. The running machine alone knows the shares, the region sizes, the address map and a cpu's `type`.

Where the two disagree the field carries the running machine's value, and `note` names both. A field neither source has is absent, never null or guessed.

<details><summary>More on why</summary>

The address map covers the devices that execute, the ones MAME gives a debugger. It is the map as wired: a banked range answers for whichever bank is selected at the time.

- `spaces`: `cpu`, `space`, `data_width_bits`, `endianness`, `entries`, `address_mask`.
- `address_map`: also `region_offset` beside a `region`, and the entry's own `mirror` and `address_mask` when not zero. A `share` or `region` carries the tag `shares` and `regions` list it under.
- `regions` and `shares`: `tag`, `size`, `bytewidth`, `endianness`.
- `screens`: `tag`, `width`, `height`, `refresh_hz`, `rotation`, `type`.
- `rom_files`: `name`, `size`, `crc`, `sha1`, `dump_status`, `region`, `offset`. It is left out by default because it answers a ROM audit, not a debugging question.
- `symbol_coverage`: one row per class of each cpu's symbol table, with `class`, `cpu`, `span` (`from`, `length`), `symbols` and `base`. It is empty when the table has no classes.
- `cpu` leaves the regions, shares, screens and ROM files whole: they are the board's, and a shorter list would say the other cpu's ROMs do not exist.
- When `-listxml` fails, `rom_files`, the clocks and the rotation are empty and `note` quotes why.
- `frame_symbol` names the machine's frame counter, unavailable on a board with none. `omitted` and `how` name the sections left out and how to ask for them.

</details>

### Related tools

- [`cpu_info`](#cpu_info)
- [`read_block`](read.md#read_block)
- [`read_memory`](read.md#read_memory)
- [`rom_check`](session.md#rom_check)
- [`symbols_find`](symbols.md#symbols_find)

<details><summary>The contract your client receives</summary>

```text
What the machine is: its cpus and spaces, address map, regions, shares, screens and ROM
files. Cached at `start()`, free; answered on a running machine.

Arguments: `cpu`, a tag in either spelling, narrows `cpus`, `spaces`, `address_map` and
`symbol_coverage`. `sections` picks sections; left out, all but `rom_files`. `dest`
(absolute or `~`-led, new) writes every row of the sections read as JSON.

Refused: an empty or unknown `sections`, or an existing `dest` (`bad_argument`); an unknown
tag (`unknown_ref`); no machine (`no_session`); a broken session (`session_broken`).

Reply: `cpus`, `spaces`, `address_map`, `regions`, `shares`, `screens`, `rom_files`,
`symbol_coverage`, `counts`, `truncated` (lists cut to 400 rows; `dest` holds all),
`sources`,
`path` (with `dest`), `note`, `frame_symbol`. A field no source backs is absent.

Reference: REFERENCE.md, Reading and writing.
```

</details>
<!-- scry-reference:end machine_map -->

<!-- scry-reference:begin log -->
## `log`

Read the newest log lines that match a pattern: from MAME's own log, from the process's output, or from both.

```text
log(pattern, channel, limit=40, labels=false, since_mark=0)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, after one coin has been dropped.

Ask:

> What has MAME logged about the coin counter?

Call:

```text
log(pattern="coin counter", channel="emulator")
```

Reply, 2 of 7 fields:

```json
{
  "summary": "log emulator /coin counter/: 3 of 3 lines",
  "lines": ["[:] coin counter off", "[:] coin counter on", "[:] coin counter off"]
}
```

Three lines of MAME's own log match, oldest first: the driver reports the coin counter off, then on for the coin, then off again.

<details><summary>The whole reply</summary>

```json
{
  "summary": "log emulator /coin counter/: 3 of 3 lines",
  "status": "ok",
  "pattern": "coin counter",
  "channel": "emulator",
  "lines_total": 3,
  "truncated": false,
  "lines": ["[:] coin counter off", "[:] coin counter on", "[:] coin counter off"]
}
```

</details>

### Arguments

- `pattern` (string, required): A regular expression each line is searched for. It is never empty: `.` matches every line.
- `channel` (one of `"emulator"`, `"process"`, `"all"`, required): Which log to read. `emulator` is MAME's `error.log`, `process` its stdout and stderr, `all` both with each line tagged `[emulator] ` or `[process] `.
- `limit` (integer (>= 1, <= 400), default `40`): How many of the newest matching lines to return: 1 to 400. Left out, 40.
- `labels` (boolean, default `false`): `true` adds `labels`: the lines returned, counted by their first word. Left out, no count.
- `since_mark` (integer (>= 0), default `0`): A byte position in the log: only lines written after it are read. Left out or 0, the whole log is read.

### What comes back

- `lines`: The newest `limit` matching lines, oldest first.
- `lines_total`: How many lines matched in all, not how many came back.
- `truncated`: `true` when more matched than came back.
- `counts`: On `all`, how many lines matched in each of the two logs.
- `labels`: With `labels=true`, the returned lines counted by their first word: a quick view of who is writing.

<details><summary>All 7 reply fields</summary>

- `channel` (string)
- `counts` (object)
- `labels` (object)
- `lines` (array)
- `lines_total` (integer)
- `pattern` (string)
- `truncated` (boolean)

</details>

### What it refuses

- An empty pattern, or one that is not a regular expression (`bad_argument`).
- A `limit` outside 1 to 400 (`bad_argument`).
- `channel` `guest`: an arcade board has no log written by the program itself (`bad_argument`).
- A `since_mark` with `all`, or one past the end of the log (`bad_argument`).
- A log MAME has written nothing to yet (`no_channel`).

### Why it works this way

A driver can fill the log fast, so the pattern and the limit are how a line is found. Pass a pattern that narrows: `.` is the last resort, and `labels` shows at a glance who is writing.

`emulator` is what MAME's core and the drivers write with `logerror`. `process` is where MAME's own error messages, its `-verbose` output and a driver's counters go.

`since_mark` takes the `mark` that a state load, or the log part of a stop's reply, gives for that log. It is a position in one file, so `all`, which reads two, takes none.

### Related tools

- [`log_wait`](#log_wait)
- [`drive`](sequences.md#drive)
- [`state_write`](states.md#state_write)
- [`run_to`](run.md#run_to)

<details><summary>The contract your client receives</summary>

```text
The newest lines of one `channel` of what MAME writes matching the regex `pattern` (`.` for
all; never empty). Works while running.

`channel`: `emulator`, `process` or `all` (lines tagged `[emulator] `, `[process] `);
`guest` is refused. `labels=True` adds `labels`, lines counted by first word.
`since_mark` reads only what follows that log byte position.

Reply: `pattern`, `channel`, `lines` (the newest `limit`, 1..400, oldest first),
`lines_total`, `truncated`, `counts` (on channel `all`), `labels`. A bad `limit`, regex or
`since_mark` is refused.

Reference: REFERENCE.md, The log.
```

</details>
<!-- scry-reference:end log -->

<!-- scry-reference:begin log_wait -->
## `log_wait`

Wait until a log line matches a pattern, or get the line at once when the log already has it.

```text
log_wait(pattern, channel, seconds=30.0, since_mark=0)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, after turning the throttle off and letting the game run five seconds.

Ask:

> Check MAME's log for the line that says the throttle went off.

Call:

```text
log_wait(pattern="MAME_MCP_THROTTLE#1", channel="emulator")
```

Reply, 4 of 12 fields:

```json
{
  "summary": "log_wait emulator /MAME_MCP_THROTTLE#1/: matched already there",
  "verdict": "TARGET",
  "line": "[luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=0",
  "already": true
}
```

`TARGET` means a line matched, and `already` that the log held it before the call, so nothing was waited for. The line is the one MAME wrote when the throttle went off.

<details><summary>The whole reply</summary>

```json
{
  "summary": "log_wait emulator /MAME_MCP_THROTTLE#1/: matched already there",
  "status": "ok",
  "verdict": "TARGET",
  "pattern": "MAME_MCP_THROTTLE#1",
  "channel": "emulator",
  "line": "[luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=0",
  "already": true,
  "lines_total": 1,
  "lines_before": 4,
  "arrived_during": 0,
  "waited_s": "<volatile>",
  "lines_examined": 6
}
```

</details>

### Arguments

- `pattern` (string, required): A regular expression each line is searched for. It is never empty: `.` matches every line.
- `channel` (one of `"emulator"`, `"process"`, `"all"`, required): Which log to wait on: `emulator`, `process` or `all`, as in [`log`](#log).
- `seconds` (number (> 0, <= 600.0), default `30.0`): How long to wait at most, in seconds, up to 600. Left out, 30.
- `since_mark` (integer (>= 0), default `0`): A byte position in the log: only lines written after it count, the ones already there included. Left out or 0, the whole log counts.

### What comes back

- `verdict`: `TARGET` when a line matched, `TIMEOUT` when the time ran out with none; `note` then says what was read.
- `line`: The first line that matched; for the newest one, use `log`.
- `already`: `true` when the log held the line before the call, so nothing was waited for.
- `waited_s`: Seconds spent waiting; 0 when the line was already there.
- `arrived_during`: How many lines were written during the wait, whether or not they matched.
- `lines_examined`: How many lines were read in all: those the log held and those that came during the wait.

<details><summary>All 10 reply fields</summary>

- `already` (boolean)
- `arrived_during` (integer)
- `channel` (string)
- `line` (string)
- `lines_before` (integer)
- `lines_examined` (integer)
- `lines_total` (integer)
- `pattern` (string)
- `verdict` (string)
- `waited_s` (number)

</details>

### What it refuses

- A machine stopped at the debugger, or one that stops during the wait, while the log lacks the line: a stopped machine logs nothing (`wait_stopped`).
- An emulator that exits during the wait (`session_broken`).
- `seconds` out of range, an empty or malformed pattern, or a `since_mark` past the end of the log (`bad_argument`).

### Why it works this way

The log is read before any waiting, so a line written before the call is found at once, where a tool that only waited would report that it never came. `already` marks such a line.

A `TIMEOUT` says what it read. `arrived_during` counts the lines written during the wait and `lines_examined` every line read, so a program that wrote nothing is told apart from one whose lines did not match.

A stop during the wait is refused like a machine already stopped, after one last read of the log. After a `TIMEOUT` the program still runs. Progress is reported while it waits.

<details><summary>More on why</summary>

`lines_before` counts the lines read before the match and `lines_total` the matches in that read.

</details>

### Related tools

- [`log`](#log)
- [`resume`](run.md#resume)
- [`drive`](sequences.md#drive)
- [`run_to`](run.md#run_to)

<details><summary>The contract your client receives</summary>

```text
Wait up to `seconds` for a line of `channel` matching the regex `pattern` (never empty);
at once if the log holds it. Answers while running. `channel`, `since_mark` as in `log`.

Refused: `wait_stopped` when stopped and the log lacks the line; `session_broken`; a bad
`seconds`, regex or `since_mark`.

Reply: `verdict` `TARGET`, `line` (the first match), `already`, `waited_s`, `lines_before`,
`lines_total`, `arrived_during`, `lines_examined`; on timeout `verdict` `TIMEOUT`, `note`.

Reference: REFERENCE.md, The log.
```

</details>
<!-- scry-reference:end log_wait -->
