# The Knowledge tools

The knowledge base holds what a machine's documentation says about a number, and what this server measured the emulator doing about it.

Ask `knowledge_find` when a number appears and its meaning is not in your program: a vector, a chip register, an input, a device. It answers one entry whole: the document's rows with the lines each was read at, and the emulator's verdict beside any row it does not follow. No session is needed for what the base holds.

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
        {
          "n": "7",
          "on": "does",
          "of": "doc",
          "text": "The NMI response stores the Program Counter in the external stack and jumps to address 0066h.",
          "cites": [
            {"document": "Zilog Z80 CPU user manual", "lines": "905-906"}
          ],
          "verdicts": {"mame": "as documented"}
        },
        {
          "n": "8",
          "on": "is",
          "of": "doc",
          "text": "The service routine for the nonmaskable interrupt must begin at address 0066h if this interrupt is used.",
          "cites": [
            {"document": "Zilog Z80 CPU user manual", "lines": "906-908"}
          ]
        },
        {
          "n": "9",
          "on": "does",
          "of": "doc",
          "text": "Accepting an NMI resets IFF1; the manual says this prevents further interrupts until the programmer re-enables them.",
          "cites": [
            {"document": "Zilog Z80 CPU user manual", "lines": "1051-1052"}
          ],
          "verdicts": {"mame": "as documented"}
        },
        {
          "n": "10",
          "on": "is",
          "of": "doc",
          "text": "The CPU response to an NMI is similar to a normal memory read; the contents of the data bus are ignored.",
          "cites": [
            {"document": "Zilog Z80 CPU user manual", "lines": "904-905"}
          ]
        },
        {
          "n": "111",
          "on": "when",
          "of": "mame",
          "vs": "differs",
          "row": "2",
          "text": "MAME marks an NMI pending when the line goes from clear to asserted, but only if total_cycles() is not zero.",
          "cites": [
            {"file": "src/devices/cpu/z80/z80.cpp", "lines": "798-801"}
          ]
        },
        {
          "n": "112",
          "on": "place",
          "of": "mame",
          "vs": "place",
          "text": "check_interrupts runs take_nmi when the NMI-pending flag is set.",
          "cites": [
            {"file": "src/devices/cpu/z80/z80.lst", "lines": "1019-1020"}
          ]
        },
        {
          "n": "113",
          "on": "does",
          "of": "mame",
          "vs": "extra",
          "text": "take_nmi calls leave_halt, increments R, has a `+ 5` step, copies PC to WZ, sets NMI pending to 0; if HAS_LDAIR_QUIRK and the after-LD A,I flag are set, sets pv_val.",
          "cites": [
            {"file": "src/devices/cpu/z80/z80.lst", "lines": "892-895"},
            {"file": "src/devices/cpu/z80/z80.lst", "lines": "897-898"},
            {"file": "src/devices/cpu/z80/z80.lst", "lines": "901-902"}
          ]
        }
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
- `text` (string, default `""`): Words looked for in an entry's name, its aliases and the text of its rows. A word ending in `*` matches by prefix.
- `device` (string, default `""`): A chip's key, or a tag of the running machine such as `:ymsnd`: everything that belongs to it.
- `scope` (string, default `""`): A cpu or a chip: `z80`, `mc6845`. Left empty, the session's cpus and chips; with no session, all.
- `limit` (integer, default `10`): How many entries are listed: 1 to 50. Left out, 10.

### What comes back

- `entries`: Rows with `id`, `kind`, `key`, `name`; one match, or an `id`, answers whole, with its `rows` (each row's `text` and `cites`) and its `sources`. A machine's own row has `live: true`.
- `entries_total`: How many entries matched.
- `truncated`: `true` when more matched than `entries` lists.
- `examined`: How many entries were searched, so a zero says what it is a zero of.
- `nearest`: When nothing matched: the entries next to the number or the words.
- `note`: When nothing matched, or an entry is held back: that the number stays a number.

<details><summary>All 11 reply fields</summary>

- `entries` (array of object)
- `entries_total` (integer)
- `examined` (integer)
- `held_back` (integer)
- `kinds` (array of string)
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

- [`symbols_find`](symbols.md#symbols_find)
- [`machine_map`](machine.md#machine_map)
- [`read_memory`](read.md#read_memory)
- [`disassemble`](read.md#disassemble)

<details><summary>The contract your client receives</summary>

```text
What a number is called on the machine and what the base knows of it: a port, vector,
DOS or BIOS call, IRQ, memory address, input, device, register or command. One match, or an
`id`, answers the entry: its `rows`, the document's first with each emulator's `verdicts`,
then the emulators' notes (`vs`); `id=<id>#<n>`: a row, with URLs. More: a list. No session
except for a tag, inputs or memory.

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
`unconfirmed` lists ids held back. `kinds` on `no_channel`.

Scopes: acia6850, aica, am9517a, ay8910, c140, c219, c352, c6280, chip, es5505, es5506, hd44780, i8251, i8255, ins8250, k007232, k054539, m68000, m6809, mc146818, mc6845, mc68681, msm5205, nes_apu, okim6295, pia6821, pic8259, pit8253, pokey, ppu2c0x, qsound, rf5c68, saa1099, scsp, sega315_5124, sega315_5313, sn76496, tms9928a, upd1990a, upd7759, v30, v9938, x1010, ym2151, ym2203, ym2608, ym2610, ym2612, ym3526, ym3812, ymf262, ymf278b, z80, z80scc, z80sio.

Reference: REFERENCE.md, Knowledge base.
```

</details>
<!-- scry-reference:end knowledge_find -->
