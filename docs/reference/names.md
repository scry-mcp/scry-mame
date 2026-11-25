# The Names tools

A symbol table gives names to the addresses of a program: its routines and its variables. With one loaded, a tool that takes an address takes a name as well.

Here `start` loads the table, from the file its `symbols` argument names, one table per cpu. `symbols_find` looks a name or an address up in it.

`knowledge_find` asks the [knowledge base](../../REFERENCE.md#knowledge-base) what a number is called.

<!-- scry-reference:begin symbols_find -->
## `symbols_find`

Find a symbol's address by its name, or find which symbol an address falls in.

```text
symbols_find(name="", linear=null, limit=10, cpu="")
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org, started with the symbol file of the reference's own run, `docs/reference/tour/gridlee-symbols.yaml`.

Ask:

> Which symbols start with "cred", and where are they?

Call:

```text
symbols_find(name="cred")
```

Reply, 3 of 7 fields:

```json
{
  "summary": "symbols_find cred: 2 matches",
  "symbols": [
    {"name": "credits", "addr": "0x0000042b", "memory": "ram"},
    {"name": "credits_bcd", "addr": "0x0000042c", "memory": "ram"}
  ],
  "truncated": false
}
```

No symbol is named `cred`, so the two that start with it are listed: the credits and their BCD copy, one byte apart. `memory` says both sit in RAM.

<details><summary>The whole reply</summary>

```json
{
  "summary": "symbols_find cred: 2 matches",
  "status": "ok",
  "query": "cred",
  "cpu": ":maincpu",
  "symbols_total": 2,
  "symbols": [
    {"name": "credits", "addr": "0x0000042b", "memory": "ram"},
    {"name": "credits_bcd", "addr": "0x0000042c", "memory": "ram"}
  ],
  "truncated": false
}
```

</details>

### Arguments

- `name` (string, default `""`): The symbol to look up, case ignored. An exact match wins; with none, every symbol that starts with it is listed, by address.
- `linear` (integer or string, optional): An address as the running program uses it, as `disassemble` shows it. The reply is the nearest symbol at or below it.
- `limit` (integer (>= 1, <= 50), default `10`): How many symbols a name lookup lists: 1 to 50. Left out, 10.
- `cpu` (string, default `""`): The cpu whose table is read. Left empty, the one the debugger is showing.

### What comes back

- `symbols`: By name: the first `limit` matches, each with its `name` as the file spells it, its `addr` and its `memory`.
- `symbols_total`: By name: how many symbols matched.
- `truncated`: By name: `true` when more matched than `symbols` lists.
- `name`: By address: the nearest symbol at or below the address, with its own `addr`.
- `delta`: By address: how many bytes the address is past that symbol's start.
- `memory`: What kind of memory the symbol sits in: `ram`, `rom`, `latch`, `handlers`, `unmapped` or `unknown`.

<details><summary>All 10 reply fields</summary>

- `addr` (string)
- `cpu` (string)
- `delta` (integer)
- `linear` (string)
- `memory` (string)
- `name` (string)
- `query` (string)
- `symbols` (array)
- `symbols_total` (integer)
- `truncated` (boolean)

</details>

### What it refuses

- Both `name` and `linear`, or neither: one question per call (`bad_argument`).
- A session started with no symbol file for that cpu (`no_channel`).
- An address below every symbol of the table (`unknown_ref`).

### Why it works this way

`memory` tells you, before you set one, that a watch for changes on the ROM copy of a variable can never fire. It costs the debugger's `map` command one question per symbol, hence the limit of 50.

The table is the server's own copy, not read from the machine, so the lookup answers while the program runs. While it runs `memory` is `unknown`, and `note` says why.

`linear` is a run-time address, after `start`'s `bases` moved the data to where the board keeps it. A linker map's column is before that, and finds a plausible symbol with an absurd `delta`. `delta` is a distance past the symbol's start because the table holds no sizes.

<details><summary>More on why</summary>

| `memory` | meaning |
|---|---|
| `ram` | Read and written as plain memory: a watch for changes fires. |
| `rom` | Never written: code, or the ROM copy of a variable. |
| `latch` | Written through a handler, read nowhere: `read_memory` answers zeros; `read_block` reads it when the map entry keeps a share. |
| `handlers` | Read and written through handlers: readable, not plain memory. |
| `unmapped` | Nothing answers there. |
| `unknown` | The program is running, or `map` named no side. |

</details>

### Related tools

- [`read_memory`](read.md#read_memory)
- [`read_block`](read.md#read_block)
- [`watch_add`](breakpoints.md#watch_add)
- [`breakpoint_at`](breakpoints.md#breakpoint_at)
- [`disassemble`](read.md#disassemble)
- [`machine_map`](machine.md#machine_map)

<details><summary>The contract your client receives</summary>

```text
Look a symbol up in the table `start` loaded for `cpu`, else the visible cpu. One question
per call: `name` (exact, else prefix matches by address, case ignored, each in the
spelling the map gave, up to `limit` 1..50; the name never reaches MAME's
console), or `linear`, a run-time address as `disassemble` shows it, not a
linker map's column: the nearest symbol at or below, and the distance. Works while running.

Refused: no table (`no_channel`); an address below every symbol (`unknown_ref`). A name the
file gives twice is listed here with every row, and refused by a tool that takes one address
(`ambiguous_ref`, naming each): use the `0x` address of the one meant.

Reply: by name, `query`, `symbols_total`, `symbols` (`name`, `addr`, `memory`), `truncated`;
by address, `linear`, `name`, `addr`, `delta`, `memory`; and `cpu`, `note`.

Reference: REFERENCE.md, Names for addresses.
```

</details>
<!-- scry-reference:end symbols_find -->

<!-- scry-reference:begin knowledge_find -->
## `knowledge_find`

Ask what a number is called on this machine and what the server knows about it: a vector, a chip register, an input, a device.

```text
knowledge_find(id="", kind="", key="", text="", device="", scope="", limit=10)
```

### Try it

On [Gridlee](../../demos/gridlee/README.md), a free ROM from mamedev.org. The base needs no session for what it holds, so it answers about a Z80 too.

Ask:

> What does the Z80 do at 0x66?

Call:

```text
knowledge_find(kind="vector", key="0x66", scope="z80")
```

Reply, 3 of 8 fields:

```json
{
  "summary": "kind vector key 0x66: NMI",
  "entries_total": 1,
  "examined": 9
}
```

One entry matches, so `entries` answers it whole: the NMI vector, what the Z80 does when it is taken, and its source lines. `examined` counts the entries the search read: nine.

<details><summary>The whole reply</summary>

```json
{
  "summary": "kind vector key 0x66: NMI",
  "status": "ok",
  "query": {"kind": "vector", "key": "0x66"},
  "scope": ["z80"],
  "entries_total": 1,
  "entries": [
    {
      "id": "z80:vector:0x66",
      "kind": "vector",
      "key": "0x66",
      "name": "NMI",
      "scope": "z80",
      "rows": [
        {
          "n": "1",
          "on": "is",
          "of": "doc",
          "text": "NMI is the Nonmaskable Interrupt input.",
          "cites": [
            {"document": "Zilog Z80 CPU user manual", "lines": "694"}
          ]
        },
        {
          "n": "2",
          "on": "when",
          "of": "doc",
          "text": "The NMI input is negative edge-triggered.",
          "cites": [
            {"document": "Zilog Z80 CPU user manual", "lines": "694"}
          ],
          "verdicts": {"mame": "differs"}
        },
        {
          "n": "3",
          "on": "when",
          "of": "doc",
          "text": "NMI has a higher priority than INT.",
          "cites": [
            {"document": "Zilog Z80 CPU user manual", "lines": "694-695"}
          ],
          "verdicts": {"mame": "as documented"}
        },
        {
          "n": "4",
          "on": "when",
          "of": "doc",
          "text": "NMI is accepted regardless of the status of the interrupt enable flip-flop.",
          "cites": [
            {"document": "Zilog Z80 CPU user manual", "lines": "695-696"},
            {"document": "Zilog Z80 CPU user manual", "lines": "1080"}
          ],
          "verdicts": {"mame": "as documented"}
        },
        {
          "n": "5",
          "on": "does",
          "of": "doc",
          "text": "An accepted NMI makes the CPU restart at address 0066h.",
          "cites": [
            {"document": "Zilog Z80 CPU user manual", "lines": "696-697"},
            {"document": "Zilog Z80 CPU user manual", "lines": "1081-1082"}
          ],
          "verdicts": {"mame": "as documented"}
        },
        {
          "n": "6",
          "on": "is",
          "of": "doc",
          "text": "The NMI restart is like a restart instruction to a location outside the eight software restart locations; a restart is a call to an address in Page 0.",
          "cites": [
            {"document": "Zilog Z80 CPU user manual", "lines": "1082-1084"}
          ]
        },
        "... 7 more"
      ],
      "aliases": ["non-maskable interrupt"],
      "sources": [
        {"where": "Zilog Z80 CPU user manual", "url": "http://www.z80.info/zip/z80cpu_um.pdf"},
        {
          "where": "src/devices/cpu/z80/z80.cpp",
          "url": "https://github.com/mamedev/mame/blob/mame0289/src/devices/cpu/z80/z80.cpp"
        },
        {
          "where": "src/devices/cpu/z80/z80.lst",
          "url": "https://github.com/mamedev/mame/blob/mame0289/src/devices/cpu/z80/z80.lst"
        }
      ]
    }
  ],
  "truncated": false,
  "examined": 9
}
```

</details>

### Arguments

- `id` (string, default `""`): An entry's id, as another reply cites it, such as `z80:vector:0x66`. Answers that entry whole.
- `kind` (one of `""`, `"vector"`, `"call"`, `"error"`, `"port"`, `"irq"`, `"memory"`, `"input"`, `"device"`, `"register"`, `"command"`, default `""`): What the number is: `vector`, `call`, `error`, `port`, `irq`, `memory`, `input`, `device`, `register` or `command`. Left empty, every kind.
- `key` (string, default `""`): The number as a reply prints it, or a range such as `0x3C0..0x3CF`; for an `input`, `:IN1/Coin 1`.
- `text` (string, default `""`): Words looked for in names, aliases, descriptions and behaviour. A word ending in `*` matches by prefix.
- `device` (string, default `""`): A chip's key, or a tag of the running machine such as `:ymsnd`: everything that belongs to it.
- `scope` (string, default `""`): A cpu or a chip: `z80`, `mc6845`. Left empty, the session's cpus and chips; with no session, all.
- `limit` (integer, default `10`): How many entries are listed: 1 to 50. Left out, 10.

### What comes back

- `entries`: Rows with `id`, `kind`, `key`, `name`; one match, or an `id`, answers whole with `description`, `behaviour` and `sources`. A machine's own row has `live: true`.
- `entries_total`: How many entries matched.
- `truncated`: `true` when more matched than `entries` lists.
- `examined`: How many entries were searched, so a zero says what it is a zero of.
- `nearest`: When nothing matched: the entries next to the number or the words.
- `note`: When nothing matched, or an entry is held back: that the number stays a number.

<details><summary>All 10 reply fields</summary>

- `entries` (array of object)
- `entries_total` (integer)
- `examined` (integer)
- `held_back` (integer)
- `nearest` (array of object)
- `query` (object)
- `scope` (array of string)
- `served` (integer)
- `truncated` (boolean)
- `unconfirmed` (array of string)

</details>

### What it refuses

- None of `id`, `kind`, `key`, `text`, `device` (`bad_argument`).
- A `key` that is no number or range of that `kind`, or a `scope` the server does not hold (`bad_argument`).
- An `id` or a `device` the base does not hold (`unknown_ref`); one whose entry is held back is no refusal: it answers `unconfirmed`.
- A kind read from the machine with no session (`no_session`).

### Why it works this way

Each entry was checked against its source, and an answer says where it was read. A key the base has not confirmed answers `unconfirmed` and stays a number. The base is the server's own copy: it answers while the program runs.

What the machine says about itself (inputs, devices, the memory map) was read at `start` and is never asked of MAME again, so it cannot slow a call.

### Related tools

- [`symbols_find`](#symbols_find)
- [`machine_map`](machine.md#machine_map)
- [`read_memory`](read.md#read_memory)
- [`disassemble`](read.md#disassemble)

<details><summary>The contract your client receives</summary>

```text
What a number is called on the machine and what the base knows of it: a port, vector,
DOS or BIOS call, IRQ, memory address, input, device, register or command. One match, or an
`id`, answers the entry: its `rows`, the document's first with each emulator's `verdicts`,
then the emulators' notes (`vs`); `id=<id>#<n>`: a row, with URLs. More: a list. No session
is needed except for a device by tag, inputs and memory.

`id`: an entry's id. `kind`: `vector`, `call`, `error`, `port`, `irq`, `memory`, `input`,
`device`, `register` or `command`; empty searches all. `key`: the number as a reply prints it,
or a range. `text`: words in names, aliases, rows; `*` ends a prefix. `device`: all of
that device. `scope`: the system, cpu or device; empty, the live session's. `limit` 1..50.

Examples: `key=0x3C8`; `kind=vector key=0xFFF8 scope=<scope>`; `kind=call key=0x21/0x4C`,
a variant `kind=call key=0x10/0x12/BL=0x36`;
a live device by tag `kind=device key=:maincpu`; its registers
`kind=register device=<device>`; `text=palette*`.

Refused (INVALID): nothing to look up, a bad `key`, or a `scope` it lacks
(`bad_argument`; `6809` is read as `m6809`); an `id` or `device` it
lacks (`unknown_ref`); a kind it holds none of (`no_channel`); a tag or live kind with no
session (`no_session`).

Reply: `query`, `scope`, `entries_total`, `entries`, `truncated`, `examined`, `served`,
`held_back`; nothing matched: no entry, `nearest` and a `note`: it stays a number.
`unconfirmed` lists ids held back.

Scopes: acia6850, aica, am9517a, ay8910, c140, c219, c352, c6280, chip, es5505, es5506, hd44780, i8251, i8255, ins8250, k007232, k054539, m68000, m6809, mc146818, mc6845, mc68681, msm5205, nes_apu, okim6295, pia6821, pic8259, pit8253, pokey, ppu2c0x, qsound, rf5c68, saa1099, scsp, sega315_5124, sega315_5313, sn76496, tms9928a, upd1990a, upd7759, v30, v9938, x1010, ym2151, ym2203, ym2608, ym2610, ym2612, ym3526, ym3812, ymf262, ymf278b, z80, z80scc, z80sio.

Reference: REFERENCE.md, Knowledge base.
```

</details>
<!-- scry-reference:end knowledge_find -->
