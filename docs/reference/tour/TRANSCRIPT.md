Every call of the run with its reply, in order: 77 calls. `<volatile>` stands for a value that changes from run to run, and `<host>` for one this host decides.

**1. `start`**: OK start: gridlee on MAME 0.289 (unknown), rom_check OK, pc 0x0000f000, 7 symbols

<details><summary>call and reply</summary>

```json
{
  "shared": true,
  "background": true,
  "display": "<host>",
  "system": "gridlee",
  "reference_rom": "./tmp/demos/tour/gridlee.ref",
  "reference_addr": "0xa000",
  "reference_base": "0xa000",
  "inipath": "./tmp/demos/tour/gridlee-ini",
  "state_dir": "./tmp/demos/tour/gridlee-states",
  "boot_seconds": 60,
  "symbols": "./docs/reference/tour/gridlee-symbols.yaml",
  "rompath": "<host>"
}
```

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "system": "gridlee",
  "binary": "<volatile>",
  "binary_origin": "<volatile>",
  "version": "0.289 (unknown)",
  "pid": "<volatile>",
  "stub_port": "<volatile>",
  "scratch_dir": "<volatile>",
  "state_dir": "./tmp/demos/tour/gridlee-states",
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "debugger": {
    "attached": "gdbstub",
    "note": "MAME runs with -debug under this stub. A capture taken at one of this session's stops can land a frame away from an autoboot golden taken by a frame notifier at the same count, in a scene that changes every frame: compare a live capture with a live golden"
  },
  "errorlog_path": "<volatile>",
  "stdout_path": "<volatile>",
  "rom_check": "OK",
  "symbols_total": 7,
  "symbols_typed": 2,
  "symbols_format": "yaml",
  "symbols_by_class": {},
  "symbols_by_cpu": {":maincpu": 7},
  "registers": ["A", "B", "D", "X", "Y", "U", "PC", "S", "CC", "DP"],
  "pc": "0x0000f000",
  "frame": 0,
  "frame_symbol": "frame",
  "view": "native",
  "views": ["Screen 0 Standard (4:3)", "Screen 0 Pixel Aspect (16:15)", "Cocktail"],
  "background": true,
  "flags": "<volatile>",
  "boot_lua_path": "<volatile>",
  "presence": true,
  "overlay": {
    "layers": ["edge", "record"],
    "lacking": {"pointer": "MAME has no pointer to draw: its inputs are port fields, not a mouse"},
    "notes": {
      "record": "a stopped machine is not repainted to animate, so the mark stays lit and does not blink"
    }
  },
  "machine": {
    "cpus": 1,
    "spaces": 1,
    "address_map": 14,
    "regions": 3,
    "shares": 3,
    "screens": 1,
    "rom_files": 13
  },
  "declarations": {
    "persistent": true,
    "path": "./tmp/demos/tour/gridlee-states/declarations.json",
    "key": "gridlee ./docs/reference/tour/gridlee-symbols.yaml",
    "held": 0,
    "fingerprint": "9ddedcc4d2bcbc14",
    "rearm": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": [], "evaluated": []},
    "comments": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": []}
  },
  "recommended_release": "0.289",
  "window": "<volatile>",
  "kept": "1 saved for `promote`; start/gridlee: nothing this session read names its repository: promote(dry_run=true, root=<the repository>) lists what an approval would create",
  "names": [
    {"field": "pc", "number": "0x0000f000", "kind": "symbol", "name": "take_credit", "delta": 6538}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "altering_writes": 0,
    "console": {"thread_errors": 0, "reruns": 0, "lost": 0}
  }
}
```

</details>

**2. `status`**: OK status: gridlee alive, parked at 0x0000f000

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "status: gridlee alive at pc 0x0000f000 (take_credit+0x198A)",
  "status": "ok",
  "system": "gridlee",
  "pid": "<volatile>",
  "stub_port": "<volatile>",
  "scratch_dir": "<volatile>",
  "state_dir": "./tmp/demos/tour/gridlee-states",
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "debugger": {
    "attached": "gdbstub",
    "note": "MAME runs with -debug under this stub. A capture taken at one of this session's stops can land a frame away from an autoboot golden taken by a frame notifier at the same count, in a scene that changes every frame: compare a live capture with a live golden"
  },
  "presence": true,
  "overlay": {
    "layers": ["edge", "record"],
    "lacking": {"pointer": "MAME has no pointer to draw: its inputs are port fields, not a mouse"},
    "notes": {
      "record": "a stopped machine is not repainted to animate, so the mark stays lit and does not blink"
    }
  },
  "fingerprint": "9ddedcc4d2bcbc14",
  "fingerprints": {":maincpu": "9ddedcc4d2bcbc14"},
  "errorlog_path": "<volatile>",
  "stdout_path": "<volatile>",
  "pc": "0x0000f000",
  "last_stop": {
    "stop_seq": 1,
    "pc": "0x0000f000",
    "cpu": ":maincpu",
    "frame": 0,
    "cause": "start",
    "since_s": "<volatile>",
    "wall_at": "<volatile>"
  },
  "in_debugger": {"breakpoints": [], "watches": [], "regpoints": []},
  "threads": {"1": ":maincpu"},
  "cpu_tags": [":maincpu"],
  "console_pending": 0,
  "tallies_pending_removal": [],
  "frame_symbol": "frame",
  "knowledge": {"served": 1008, "held_back": 0},
  "names": [
    {"field": "pc", "number": "0x0000f000", "kind": "symbol", "name": "take_credit", "delta": 6538}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "altering_writes": 0,
    "console": {"thread_errors": 0, "reruns": 0, "lost": 0}
  }
}
```

</details>

**3. `window`**: OK window: the window is on screen, not fullscreen

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "window": {
    "display": "<volatile>",
    "bounds": "<volatile>",
    "onscreen": true,
    "front": "<volatile>",
    "fullscreen": false
  },
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**4. `machine_map`**: OK machine: 1 cpu, 14 map entries, 3 regions, 3 shares

<details><summary>call and reply</summary>

```json
{}
```

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
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 7,
      "start": "0x00009502",
      "end": "0x00009502",
      "read": "port",
      "write": "none"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 8,
      "start": "0x00009503",
      "end": "0x00009503",
      "read": "port",
      "write": "none"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 9,
      "start": "0x00009600",
      "end": "0x00009600",
      "read": "port",
      "write": "none"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 10,
      "start": "0x00009700",
      "end": "0x00009700",
      "read": "port",
      "write": "nop"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 11,
      "start": "0x00009820",
      "end": "0x00009820",
      "read": "delegate/gridlee_state::random_num_r",
      "write": "none"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 12,
      "start": "0x00009828",
      "end": "0x0000993f",
      "read": "none",
      "write": "delegate/gridlee_sound_device::gridlee_sound_w"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 13,
      "start": "0x00009c00",
      "end": "0x00009cff",
      "share": ":nvram",
      "read": "ram",
      "write": "ram"
    },
    {
      "cpu": ":maincpu",
      "space": "program",
      "index": 14,
      "start": "0x0000a000",
      "end": "0x0000ffff",
      "region": ":maincpu",
      "region_offset": "0x0000a000",
      "read": "rom",
      "write": "none"
    }
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
  "note": "the address map is the map of the machine's EXECUTING devices, which is what MAME gives a debugger: a device that only exposes an address space of its own is not in it, though its shares and regions are; the map reported is the STATICALLY CONFIGURED one: a banked range answers for whichever bank is selected at the time, so a range here is what the machine was wired with and not a promise about what is behind it right now; this is what the machine WAS when `start` read it, and nothing re-reads it: if the emulator has since died the session block says `alive: false` while these sections still describe the board that was running; `symbol_coverage` is empty: this session's symbol table carries no classes (a YAML table has none, and a session started without symbols has no table at all), so there is no span to report and none is invented",
  "omitted": ["rom_files"],
  "how": "sections=[...] names the sections to read; dest=<absolute path> writes every section read whole",
  "frame_symbol": "frame",
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"},
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**5. `cpu_info`**: OK cpus: :maincpu, visible, pc 0x0000f000

<details><summary>call and reply</summary>

```json
{}
```

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
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**6. `rom_check`**: OK rom: the ROM at 0xa000 is the reference image

<details><summary>call and reply</summary>

```json
{
  "reference_rom": "./tmp/demos/tour/gridlee.ref",
  "reference_addr": "0xa000",
  "reference_base": "0xa000"
}
```

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "rom_check": "OK",
  "deterministic": true,
  "query_s": "<volatile>",
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**7. `symbols_find`**: OK names: credits at 0x0000042b, credits_bcd at 0x0000042c

<details><summary>call and reply</summary>

```json
{
  "name": "cred"
}
```

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
  "truncated": false,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**8. `read_memory`**: OK irq vector: the IRQ vector points at 0xfd80, which the symbols name irq

<details><summary>call and reply</summary>

```json
{
  "ref": "0xfff8",
  "length": 2
}
```

```json
{
  "summary": "read_memory 0xfff8 (irq+0x278): 2 bytes at 0x0000fff8 (irq+0x278): fd80",
  "status": "ok",
  "ref": "0xfff8",
  "addr": "0x0000fff8",
  "length": 2,
  "hex": "fd80",
  "cpu": ":maincpu",
  "names": [
    {"field": "given.ref", "number": "0xfff8", "kind": "symbol", "name": "irq", "delta": 632},
    {"field": "addr", "number": "0x0000fff8", "kind": "symbol", "name": "irq", "delta": 632}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**9. `knowledge_find`**: OK base: the base answers the AY-3-8910's channel amplitude whole, in 6 rows

<details><summary>call and reply</summary>

```json
{
  "kind": "register",
  "key": "0x08",
  "scope": "ay8910"
}
```

```json
{
  "summary": "kind register key 0x08: channel amplitude",
  "status": "ok",
  "query": {"kind": "register", "key": "0x08"},
  "scope": ["ay8910"],
  "entries_total": 1,
  "entries": [
    {
      "id": "ay8910:register:0x08..0x0A",
      "kind": "register",
      "key": "0x08..0x0A",
      "name": "channel amplitude",
      "scope": "ay8910",
      "rows": [
        {
          "n": "1",
          "on": "is",
          "of": "doc",
          "text": "R10, R11 and R12 are the amplitude registers of channels A, B and C; the lower 5 bits, B4 to B0, determine the amplitude.",
          "cites": [
            {
              "document": "General Instrument AY-3-8910/8912 programmable sound generator data manual",
              "lines": "721-724"
            },
            {
              "document": "General Instrument AY-3-8910/8912 programmable sound generator data manual",
              "lines": "725-729"
            }
          ]
        },
        {
          "n": "2",
          "on": "write",
          "of": "doc",
          "text": "A write to an amplitude register sets, in bits L3 to L0, the fixed amplitude level, which counts only when M is 0.",
          "cites": [
            {
              "document": "General Instrument AY-3-8910/8912 programmable sound generator data manual",
              "lines": "736-743"
            }
          ],
          "verdicts": {"mame": "differs"}
        },
        {
          "n": "3",
          "on": "write",
          "of": "doc",
          "text": "A write to an amplitude register sets the mode bit M: 0 selects a fixed level amplitude and 1 the envelope generator's output.",
          "cites": [
            {
              "document": "General Instrument AY-3-8910/8912 programmable sound generator data manual",
              "lines": "734-735"
            },
            {
              "document": "General Instrument AY-3-8910/8912 programmable sound generator data manual",
              "lines": "744-750"
            }
          ],
          "verdicts": {"mame": "differs"}
        },
        {
          "n": "5",
          "on": "is",
          "of": "doc",
          "text": "A fixed level amplitude is one of the 16 levels, set by the decimal value of bits L3 to L0.",
          "cites": [
            {
              "document": "General Instrument AY-3-8910/8912 programmable sound generator data manual",
              "lines": "780-784"
            }
          ]
        },
        {
          "n": "6",
          "on": "write",
          "of": "mame",
          "vs": "differs",
          "row": "2",
          "text": "In expanded mode MAME keeps a 5-bit fixed level, where the document gives L3 to L0, 4 bits.",
          "cites": [
            {"file": "src/devices/sound/ay8910.h", "lines": "277"}
          ]
        },
        {
          "n": "7",
          "on": "write",
          "of": "mame",
          "vs": "differs",
          "row": "3",
          "text": "In expanded mode MAME takes the envelope mode from bit 5; a chip with extended envelope keeps a 2-bit mode, not the 1-bit M.",
          "cites": [
            {"file": "src/devices/sound/ay8910.h", "lines": "278"}
          ]
        }
      ],
      "aliases": ["volume"],
      "sources": [
        {
          "where": "General Instrument AY-3-8910/8912 programmable sound generator data manual",
          "url": "https://archive.org/download/GI_AY-3-8910_Feb-1979/GI_AY-3-8910_Feb-1979_text.pdf"
        },
        {
          "where": "src/devices/sound/ay8910.h",
          "url": "https://github.com/mamedev/mame/blob/mame0289/src/devices/sound/ay8910.h"
        }
      ]
    }
  ],
  "truncated": false,
  "examined": 7,
  "served": 1008,
  "held_back": 0,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**10. `disassemble`**: OK coin routine: the coin routine: INC $042B, then ADDA $042C, DAA, STA $042C

<details><summary>call and reply</summary>

```json
{
  "ref": "count_coin",
  "length": 12
}
```

```json
{
  "summary": "disassemble count_coin: 5 lines at 0x0000b583",
  "status": "ok",
  "ref": "count_coin",
  "addr": "0x0000b583",
  "length": 12,
  "lines": ["B583: 7C 04 2B INC    $042B", "B586: 86 01    LDA    #$01", "B588: BB 04 2C ADDA   $042C", "B58B: 19       DAA", "B58C: B7 04 2C STA    $042C"],
  "cpu": ":maincpu",
  "flow": ["unknown", "unknown", "unknown", "unknown", "unknown"],
  "flow_source": "none",
  "note": "no mnemonic table for cpu type 'm6809' (tables: m68000, v30), so no line is classified",
  "names": [
    {"field": "given.ref", "number": "0xB583", "kind": "symbol", "name": "count_coin"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**11. `find`**: OK find: one INC $042B in the ROMs, at 0x0000b583

<details><summary>call and reply</summary>

```json
{
  "data_hex": "7c042b",
  "ref": "0xa000",
  "length": 24576
}
```

```json
{
  "summary": "find 7c042b in 0x6000 bytes at 0xa000 (credits_bcd+0x9BD4): 1 hit",
  "status": "ok",
  "ref": "0xa000",
  "addr": "0x0000a000",
  "length": 24576,
  "span": {"from": "0x0000a000", "length": 24576, "source": "ref+length"},
  "hits": ["0x0000b583"],
  "hits_total": 1,
  "truncated": false,
  "cpu": ":maincpu",
  "names": [
    {"field": "given.ref", "number": "0xa000", "kind": "symbol", "name": "credits_bcd", "delta": 39892},
    {"field": "hits[]", "number": "0x0000b583", "kind": "symbol", "name": "count_coin"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**12. `comment_write`**: OK comment: a comment on count_coin: a coin: INC credits, then the BCD copy

<details><summary>call and reply</summary>

```json
{
  "method": "add",
  "ref": "count_coin",
  "text": "a coin: INC credits, then the BCD copy"
}
```

```json
{
  "summary": "comment_write add: count_coin at :maincpu 0x0000b583, stored, persistent",
  "status": "ok",
  "comment": {
    "ref": "count_coin",
    "by": "symbol",
    "cpu": ":maincpu",
    "created_at": "<volatile>",
    "origin": "<volatile>",
    "inherited": false,
    "age_s": "<volatile>",
    "text": "a coin: INC credits, then the BCD copy",
    "addr": "0x0000b583",
    "state": "armed"
  },
  "replaced_comments": [],
  "declarations": {"persistent": true, "path": "./tmp/demos/tour/gridlee-states/declarations.json"},
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**13. `comment_list`**: OK comments: one comment, on count_coin

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "comment_list: 1 comment",
  "status": "ok",
  "comments": [
    {
      "ref": "count_coin",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": "<volatile>",
      "text": "a coin: INC credits, then the BCD copy",
      "addr": "0x0000b583",
      "state": "armed"
    }
  ],
  "comments_total": 1,
  "truncated": false,
  "declarations": {"persistent": true, "path": "./tmp/demos/tour/gridlee-states/declarations.json"},
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"},
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**14. `throttle`**: OK throttle: the throttle goes off at the next run, tagged MAME_MCP_THROTTLE#1

<details><summary>call and reply</summary>

```json
{
  "on": false
}
```

```json
{
  "summary": "throttle off: pending until the console next reads a line",
  "status": "ok",
  "on": false,
  "pending": true,
  "applies": "when the console next reads a line: a step, the next frame emulated, or a debugger command on a stub that refreshes after one",
  "tag": "MAME_MCP_THROTTLE#1",
  "confirmed_by": "its tag in the error log, read by the next stop's survey, by `status` and by `close`; `status` lists it in `throttles_pending` until then, and if the tag never comes, every reply after that says so in `session.throttles_not_applied`",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**15. `run_for`**: OK attract: attract mode ran to frame 295, 6250000 cycles

<details><summary>call and reply</summary>

```json
{
  "milliseconds": 5000,
  "seconds": 300
}
```

```json
{
  "summary": "run_for 5000 ms: ELAPSED, frame 0 to 295",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 0,
  "frame_after": 295,
  "emulated_before_s": 3e-06,
  "emulated_after_s": 5.000003,
  "cycles": 6250000,
  "reads": "<volatile>",
  "cause": "the console's `gtime` stop",
  "stop_seq": 2,
  "pc": "0x0000a631",
  "cpu": ":maincpu",
  "frame": 295,
  "regs": {
    "A": "0x0a",
    "B": "0x4b",
    "D": "0x0a4b",
    "X": "0xc901",
    "Y": "0xf2e6",
    "U": "0xbef1",
    "PC": "0xa631",
    "S": "0x0800",
    "CC": "0xc4",
    "DP": "0x00"
  },
  "instruction": {"address": "A631", "bytes": "04B4", "text": "LSR    <$B4", "symbol": "wait_frame", "delta": 0},
  "following": ["A633: 24 FC    BCC    $A631", "A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "A640: 7E F0 00 JMP    $F000", "A643: BD B5 2B JSR    $B52B", "A646: BD C5 67 JSR    $C567", "A649: B6 04 28 LDA    $0428", "A64C: 81 0C    CMPA   #$0C", "A64E: 24 51    BCC    $A6A1", "A650: B6 96 00 LDA    $9600"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**16. `log_wait`**: OK throttle applied: the log holds the tag: [luaengine] MAME_MCP_THROTTLE#1 throttled=false frame=0

<details><summary>call and reply</summary>

```json
{
  "pattern": "MAME_MCP_THROTTLE#1",
  "channel": "emulator"
}
```

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
  "lines_examined": 6,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**17. `screen_signature`**: OK signature: the attract screen signs as 0b0a637e5b000571

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "screen_signature 256x240 at [0, 0]: 0b0a637e5b000571",
  "status": "ok",
  "signature": "0b0a637e5b000571",
  "kind": "pixel",
  "width": 256,
  "height": 240,
  "crop": [0, 0, 256, 240],
  "screen": ":screen",
  "frame_screen": 295,
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#2",
  "pc_before": "0x0000a631",
  "cause": "screen_signature: one step",
  "stop_seq": 3,
  "pc": "0x0000a633",
  "cpu": ":maincpu",
  "frame": 295,
  "regs": {
    "A": "0x0a",
    "B": "0x4b",
    "D": "0x0a4b",
    "X": "0xc901",
    "Y": "0xf2e6",
    "U": "0xbef1",
    "PC": "0xa633",
    "S": "0x0800",
    "CC": "0xc4",
    "DP": "0x00"
  },
  "instruction": {"address": "A633", "bytes": "24FC", "text": "BCC    $A631", "symbol": "wait_frame", "delta": 2},
  "following": ["A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "A640: 7E F0 00 JMP    $F000", "A643: BD B5 2B JSR    $B52B", "A646: BD C5 67 JSR    $C567", "A649: B6 04 28 LDA    $0428", "A64C: 81 0C    CMPA   #$0C", "A64E: 24 51    BCC    $A6A1", "A650: B6 96 00 LDA    $9600"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**18. `scan`**: OK scan: 2048 candidate bytes in 0x0+0x800

<details><summary>call and reply</summary>

```json
{
  "method": "start",
  "ref": "0x0",
  "length": 2048
}
```

```json
{
  "summary": "scan start: 0x0 (spriteram), 2048 1-byte candidates on :maincpu",
  "status": "ok",
  "ref": "0x0",
  "addr": "0x00000000",
  "length": 2048,
  "cell_bytes": 1,
  "hits_total": 2048,
  "cpu": ":maincpu",
  "space": "program",
  "names": [
    {"field": "given.ref", "number": "0x0", "kind": "memory", "name": "spriteram"},
    {"field": "addr", "number": "0x00000000", "kind": "memory", "name": "spriteram"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**19. `drive`**: OK coin 1: a coin, and the log said: [:] coin counter on

<details><summary>call and reply</summary>

```json
{
  "act": [
    {"op": "input", "port": ":IN1", "field": "Coin 1", "frames": 4, "seconds": 300},
    {"op": "run_for", "milliseconds": 2000, "seconds": 300}
  ],
  "expect": "coin counter on"
}
```

```json
{
  "summary": "drive: reaction seen",
  "status": "ok",
  "act": {
    "ran": [
      {
        "op": "input",
        "cpu": ":maincpu",
        "reply": {
          "summary": "input :IN1 'Coin 1': held 4 frames, active True, released at frame 299",
          "status": "ok",
          "verdict": "ELAPSED",
          "frame_before": 295,
          "frame_after": 300,
          "emulated_before_s": 5.001233,
          "emulated_after_s": 5.085713,
          "cycles": 105600,
          "polls": 6,
          "lines_ahead": 0,
          "thread_errors": 0,
          "console_reruns": 0,
          "route": "ioport",
          "port": ":IN1",
          "field": "Coin 1",
          "value": "0x00000001",
          "frames": 4,
          "name": "Coin 1",
          "player": 0,
          "mask": "0x00000001",
          "defvalue": "0x00000001",
          "port_before": "0x000000cf",
          "frame_set": 295,
          "released": true,
          "port_held": "0x000000ce",
          "frame_released": 299,
          "active": true,
          "cause": "the `gvblank` stop of the last frame asked",
          "stop_seq": 4,
          "pc": "0x0000fd80",
          "cpu": ":maincpu",
          "frame": 300,
          "regs": {
            "A": "0x00",
            "B": "0xfe",
            "D": "0x00fe",
            "X": "0x02db",
            "Y": "0xf2e6",
            "U": "0xbef1",
            "PC": "0xfd80",
            "S": "0x07f4",
            "CC": "0xd4",
            "DP": "0x00"
          },
          "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
          "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
          "errorlog": "<volatile>",
          "session": {
            "alive": true,
            "running": false,
            "altered": false,
            "omitted": ["altering_writes", "console"],
            "how": "call `status`"
          }
        },
        "frame_before": 295,
        "frame_after": 300
      },
      {
        "op": "run_for",
        "cpu": ":maincpu",
        "reply": {
          "summary": "run_for 2000 ms: ELAPSED, frame 300 to 419",
          "status": "ok",
          "verdict": "ELAPSED",
          "frame_before": 300,
          "frame_after": 419,
          "emulated_before_s": 5.085713,
          "emulated_after_s": 7.085713,
          "cycles": 2500000,
          "reads": "<volatile>",
          "cause": "the console's `gtime` stop",
          "stop_seq": 5,
          "pc": "0x0000a7d5",
          "cpu": ":maincpu",
          "frame": 419,
          "regs": {
            "A": "0x00",
            "B": "0x00",
            "D": "0x0000",
            "X": "0x0150",
            "Y": "0x00e1",
            "U": "0x00e3",
            "PC": "0xa7d5",
            "S": "0x07fe",
            "CC": "0x84",
            "DP": "0x00"
          },
          "instruction": {"address": "A7D5", "bytes": "2406", "text": "BCC    $A7DD", "symbol": "wait_frame", "delta": 420},
          "following": ["A7D7: EC A4    LDD    ,Y", "A7D9: AF A4    STX    ,Y", "A7DB: ED C4    STD    ,U", "A7DD: 33 A4    LEAU   ,Y", "A7DF: 31 3E    LEAY   -$2,Y", "A7E1: 11 93 80 CMPU   <$80", "A7E4: 26 E6    BNE    $A7CC", "A7E6: DE 84    LDU    <$84", "A7E8: 31 5E    LEAY   -$2,U", "A7EA: DC 80    LDD    <$80", "A7EC: C3 00 02 ADDD   #$0002", "A7EF: DD 80    STD    <$80", "A7F1: 11 93 80 CMPU   <$80", "A7F4: 26 D6    BNE    $A7CC"],
          "errorlog": "<volatile>",
          "session": {
            "alive": true,
            "running": false,
            "altered": false,
            "omitted": ["altering_writes", "console"],
            "how": "call `status`"
          }
        },
        "frame_before": 300,
        "frame_after": 419
      }
    ],
    "steps_completed": 2,
    "failed_at": {"available": false, "why": "no step failed"},
    "held": 0
  },
  "verify": {
    "checked": true,
    "seen": true,
    "verdict": "TARGET",
    "expected": "coin counter on",
    "line": "[:] coin counter on",
    "lines_before": 4,
    "lines_total": 1,
    "waited_s": "<volatile>"
  },
  "looked": {
    "emulator": {
      "available": true,
      "since_mark": "<volatile>",
      "lines_written": 13,
      "lines_total": 11,
      "truncated": false,
      "lines": ["[luaengine] MAME_MCP_INPUT#3 set name=\"Coin 1\" player=0 mask=00000001 defvalue=00000001 port_before=000000cf frame=295", "[luaengine] MAME_MCP_INPUT#3 release frame=299 port_held=000000ce", "[:] coin counter on", "[:maincpu] ':maincpu' (FE4A): unmapped program memory read from 9020 & FF", "[:] coin counter off", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF"],
      "pattern": "."
    }
  },
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**20. `log`**: OK log: 3 lines name the coin counter

<details><summary>call and reply</summary>

```json
{
  "pattern": "coin counter",
  "channel": "emulator"
}
```

```json
{
  "summary": "log emulator /coin counter/: 3 of 3 lines",
  "status": "ok",
  "pattern": "coin counter",
  "channel": "emulator",
  "lines_total": 3,
  "truncated": false,
  "lines": ["[:] coin counter off", "[:] coin counter on", "[:] coin counter off"],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**21. `gfx_film`**: OK film: a film of the frames that write credits: 90 to judge, at most 2 pictures to keep

<details><summary>call and reply</summary>

```json
{
  "trigger": "credits",
  "frames": 90,
  "keep": 2,
  "film_dir": "./tmp/demos/tour/film"
}
```

```json
{
  "summary": "gfx_film on credits: armed, installed when the console next reads a line",
  "status": "ok",
  "armed_now": true,
  "film": {
    "trigger": "credits",
    "trigger_addr": "0x0000042b",
    "length": 1,
    "value": {"available": false, "why": "no `value` was given"},
    "changed": false,
    "pc": {"available": false, "why": "no `pc` was given"},
    "pc_addr": {"available": false, "why": "no `pc` was given"},
    "cpu": ":maincpu",
    "frames": 90,
    "keep": 2,
    "crop": {"available": false, "why": "no `crop`: the whole screen"},
    "film_dir": "./tmp/demos/tour/film",
    "screen": ":screen",
    "checked": true,
    "space": "program"
  },
  "trigger_maps_to": "memory@0",
  "tally_id": "film",
  "installed": false,
  "pending": true,
  "install_call": "MAME_MCP_LUA_END#5",
  "install_lines_ahead": 0,
  "note": "the film judges from the first whole frame after the install, which runs when the console next reads a line; read it with `gfx_film()`",
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#4",
  "pc_before": "0x0000a7d5",
  "cause": "gfx_film: one step",
  "stop_seq": 6,
  "pc": "0x0000a7dd",
  "cpu": ":maincpu",
  "frame": 419,
  "regs": {
    "A": "0x00",
    "B": "0x00",
    "D": "0x0000",
    "X": "0x0150",
    "Y": "0x00e1",
    "U": "0x00e3",
    "PC": "0xa7dd",
    "S": "0x07fe",
    "CC": "0x84",
    "DP": "0x00"
  },
  "instruction": {"address": "A7DD", "bytes": "33A4", "text": "LEAU   ,Y", "symbol": "wait_frame", "delta": 428},
  "following": ["A7DF: 31 3E       LEAY   -$2,Y", "A7E1: 11 93 80    CMPU   <$80", "A7E4: 26 E6       BNE    $A7CC", "A7E6: DE 84       LDU    <$84", "A7E8: 31 5E       LEAY   -$2,U", "A7EA: DC 80       LDD    <$80", "A7EC: C3 00 02    ADDD   #$0002", "A7EF: DD 80       STD    <$80", "A7F1: 11 93 80    CMPU   <$80", "A7F4: 26 D6       BNE    $A7CC", "A7F6: CE 00 00    LDU    #$0000", "A7F9: 10 8E 00 D9 LDY    #$00D9"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**22. `perform`**: OK coin 2: 11 bytes still hold 2

<details><summary>call and reply</summary>

```json
{
  "steps": [
    {"op": "input", "port": ":IN1", "field": "Coin 1", "frames": 4, "seconds": 300},
    {"op": "run_for", "milliseconds": 2000, "seconds": 300},
    {"op": "scan", "method": "filter", "operator": "=", "value": 2}
  ],
  "settle_seconds": 300
}
```

```json
{
  "summary": "perform: 3 steps completed",
  "status": "ok",
  "ran": [
    {
      "op": "input",
      "cpu": ":maincpu",
      "reply": {
        "summary": "input :IN1 'Coin 1': held 4 frames, active True, released at frame 423",
        "status": "ok",
        "verdict": "ELAPSED",
        "frame_before": 419,
        "frame_after": 424,
        "emulated_before_s": 7.096336,
        "emulated_after_s": 7.180818,
        "cycles": 105602,
        "polls": 6,
        "lines_ahead": 0,
        "thread_errors": 0,
        "console_reruns": 0,
        "route": "ioport",
        "port": ":IN1",
        "field": "Coin 1",
        "value": "0x00000001",
        "frames": 4,
        "name": "Coin 1",
        "player": 0,
        "mask": "0x00000001",
        "defvalue": "0x00000001",
        "port_before": "0x000000cf",
        "frame_set": 419,
        "released": true,
        "port_held": "0x000000ce",
        "frame_released": 423,
        "active": true,
        "cause": "the `gvblank` stop of the last frame asked",
        "stop_seq": 7,
        "pc": "0x0000fd80",
        "cpu": ":maincpu",
        "frame": 424,
        "regs": {
          "A": "0x00",
          "B": "0x00",
          "D": "0x0000",
          "X": "0x0150",
          "Y": "0x00e3",
          "U": "0x00e5",
          "PC": "0xfd80",
          "S": "0x07f2",
          "CC": "0x90",
          "DP": "0x00"
        },
        "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
        "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
        "errorlog": "<volatile>",
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      },
      "frame_before": 419,
      "frame_after": 424
    },
    {
      "op": "run_for",
      "cpu": ":maincpu",
      "reply": {
        "summary": "run_for 2000 ms: ELAPSED, frame 424 to 543",
        "status": "ok",
        "verdict": "ELAPSED",
        "frame_before": 424,
        "frame_after": 543,
        "emulated_before_s": 7.180818,
        "emulated_after_s": 9.180819,
        "cycles": 2500002,
        "reads": "<volatile>",
        "cause": "the console's `gtime` stop",
        "stop_seq": 8,
        "pc": "0x0000b502",
        "cpu": ":maincpu",
        "frame": 543,
        "regs": {
          "A": "0x02",
          "B": "0x70",
          "D": "0x0270",
          "X": "0xda5c",
          "Y": "0x0101",
          "U": "0xab79",
          "PC": "0xb502",
          "S": "0x07fc",
          "CC": "0xa9",
          "DP": "0x00"
        },
        "instruction": {
          "address": "B502",
          "bytes": "26F4",
          "text": "BNE    $B4F8",
          "symbol": "write_sprites",
          "delta": 3340
        },
        "following": ["B504: DC 86    LDD    <$86", "B506: 8E DA 62 LDX    #$DA62", "B509: 10 A3 81 CMPD   ,X++", "B50C: 23 07    BLS    $B515", "B50E: 0C 81    INC    <$81", "B510: 8C DA 6A CMPX   #$DA6A", "B513: 26 F4    BNE    $B509", "B515: 96 81    LDA    <$81", "B517: C6 05    LDB    #$05", "B519: 3D       MUL", "B51A: DB 80    ADDB   <$80", "B51C: D7 80    STB    <$80", "B51E: 86 07    LDA    #$07", "B520: 3D       MUL", "B521: D7 88    STB    <$88"],
        "errorlog": "<volatile>",
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      },
      "frame_before": 424,
      "frame_after": 543
    },
    {
      "op": "scan",
      "cpu": ":maincpu",
      "reply": {
        "summary": "scan filter: = 0x02, 11 left",
        "status": "ok",
        "operator": "=",
        "value": "0x02",
        "iterations": 1,
        "closed": false,
        "hits": [
          {"addr": "0x00000084", "value": "0x02"},
          {"addr": "0x000000da", "value": "0x02"},
          {"addr": "0x000000ed", "value": "0x02"},
          {"addr": "0x000000ef", "value": "0x02"},
          {"addr": "0x000001b6", "value": "0x02"},
          {"addr": "0x00000299", "value": "0x02"},
          {"addr": "0x0000029a", "value": "0x02"},
          {"addr": "0x000003ee", "value": "0x02"},
          {"addr": "0x00000425", "value": "0x02"},
          {"addr": "0x0000042b", "value": "0x02"},
          {"addr": "0x0000042c", "value": "0x02"}
        ],
        "hits_total": 11,
        "truncated": false,
        "cpu": ":maincpu",
        "space": "program",
        "names": [
          {"field": "hits[].addr", "number": "0x00000084", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x000000da", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x000000ed", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x000000ef", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x000001b6", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x00000299", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x0000029a", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x000003ee", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x00000425", "kind": "memory", "name": "spriteram"},
          {"field": "hits[].addr", "number": "0x0000042b", "kind": "symbol", "name": "credits"},
          {"field": "hits[].addr", "number": "0x0000042c", "kind": "symbol", "name": "credits_bcd"}
        ],
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      },
      "frame_before": 543,
      "frame_after": 543
    }
  ],
  "steps_completed": 3,
  "failed_at": {"available": false, "why": "no step failed"},
  "held": 0,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**23. `gfx_film`**: OK frames filmed: of 90 frames one wrote credits, 425, from count_coin

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "gfx_film on credits: finished, 90 judged, 1 met, 1 kept; 792x864 PNG x3, inline",
  "status": "ok",
  "film": {
    "trigger": "credits",
    "trigger_addr": "0x0000042b",
    "length": 1,
    "value": {"available": false, "why": "no `value` was given"},
    "changed": false,
    "pc": {"available": false, "why": "no `pc` was given"},
    "pc_addr": {"available": false, "why": "no `pc` was given"},
    "cpu": ":maincpu",
    "frames": 90,
    "keep": 2,
    "crop": {"available": false, "why": "no `crop`: the whole screen"},
    "film_dir": "./tmp/demos/tour/film",
    "screen": ":screen",
    "checked": true,
    "space": "program"
  },
  "tally_id": "film",
  "installed": true,
  "pending": false,
  "cpu": ":maincpu",
  "state": "finished",
  "frame_as_of": 543,
  "superseded": false,
  "callback_errors": {
    "count": 0,
    "first": {"available": false, "why": "no callback raised"}
  },
  "judged": 90,
  "judged_frames": [420, 509],
  "met": 1,
  "kept": 1,
  "refused": 0,
  "dropped_total": 0,
  "dropped_frames": {"available": false, "why": "no frame was dropped"},
  "lost": {},
  "pending_picture": false,
  "cost": "<volatile>",
  "listing_path": "./tmp/demos/tour/film/film.json",
  "cells": [
    {
      "k": 1,
      "frame": 425,
      "hits_in_frame": 1,
      "hit_counters": [425, 425],
      "pc": "0x0000b583",
      "value": "0x02",
      "symbol": "count_coin",
      "path": "./tmp/demos/tour/film/frame-1.png"
    }
  ],
  "listed": {"first": 0, "count": 1, "of": 1},
  "image": {
    "path": "./tmp/demos/tour/film/sheet-0.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 792,
    "height": 864,
    "scale": 3,
    "indexed": false,
    "inline": true
  },
  "animation": {
    "path": "./tmp/demos/tour/film/film-anim.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "frames": 1,
    "frame_period_s": 0.016896
  },
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

Also attached: image/png.

</details>

**24. `read_memory`**: OK credits: credits 2 in binary, 02 in BCD

<details><summary>call and reply</summary>

```json
{
  "ref": "credits",
  "length": 2
}
```

```json
{
  "summary": "read_memory credits: 2 bytes at 0x0000042b: 0202",
  "status": "ok",
  "ref": "credits",
  "addr": "0x0000042b",
  "length": 2,
  "hex": "0202",
  "cpu": ":maincpu",
  "names": [
    {"field": "given.ref", "number": "0x042B", "kind": "symbol", "name": "credits"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**25. `perform_export`**: OK export: 9 steps exported whole: the vector, the signature and the credits are their checks

<details><summary>call and reply</summary>

```json
{
  "dest": "./tmp/demos/tour/two-coins.json"
}
```

```json
{
  "summary": "perform_export: 9 steps, 3 checks, 15 dropped to ./tmp/demos/tour/two-coins.json",
  "status": "ok",
  "path": "./tmp/demos/tour/two-coins.json",
  "steps": 9,
  "checks": 3,
  "dropped": [
    {"call": 1, "op": "status", "why": "a read the export does not check"},
    {"call": 2, "op": "machine_map", "why": "it changes nothing in the emulated machine"},
    {"call": 3, "op": "cpu_info", "why": "a read the export does not check"},
    {"call": 4, "op": "symbols_find", "why": "a read the export does not check"},
    {"call": 6, "op": "knowledge_find", "why": "a read the export does not check"},
    {"call": 7, "op": "disassemble", "why": "a read the export does not check"},
    {"call": 8, "op": "find", "why": "a read the export does not check"},
    {"call": 9, "op": "comment_write", "why": "it changes nothing in the emulated machine"},
    {"call": 10, "op": "comment_list", "why": "a read the export does not check"},
    {"call": 11, "op": "throttle", "why": "it changes nothing in the emulated machine"},
    {"call": 13, "op": "log_wait", "why": "a read the export does not check"},
    {"call": 15, "op": "scan", "why": "it changes nothing in the emulated machine"},
    {"call": 18, "op": "log", "why": "a read the export does not check"},
    {"call": 22, "op": "scan", "why": "it changes nothing in the emulated machine"},
    {"call": 23, "op": "gfx_film", "why": "it changes nothing in the emulated machine"}
  ],
  "dropped_total": 15,
  "cut": {"available": false, "why": "the recording kept every call a replay takes"},
  "replay": "uv run python -m scry_core.replay ./tmp/demos/tour/two-coins.json",
  "kept": "2 saved for `promote`; perform/two-coins, start/gridlee: nothing this session read names its repository: promote(dry_run=true, root=<the repository>) lists what an approval would create",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**26. `state_write`**: OK save: state two-credits saved at frame 543

<details><summary>call and reply</summary>

```json
{
  "method": "save",
  "name": "two_credits"
}
```

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "name": "two-credits",
  "path": "./tmp/demos/tour/gridlee-states/sta/gridlee/two-credits.sta",
  "bytes": "<volatile>",
  "frame": 543,
  "pc": "0x0000b502",
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**27. `state_list`**: OK states: one state, two-credits, saved at frame 543

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "state_list: 1 state in ./tmp/demos/tour/gridlee-states/sta/gridlee",
  "status": "ok",
  "state_dir": "./tmp/demos/tour/gridlee-states/sta/gridlee",
  "states": [
    {
      "name": "two-credits",
      "path": "./tmp/demos/tour/gridlee-states/sta/gridlee/two-credits.sta",
      "bytes": "<volatile>",
      "frame": 543,
      "pc": "0x0000b502"
    }
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**28. `perform`**: OK capture: a capture of the player's entry on each write of the next one, and frame 545 reached

<details><summary>call and reply</summary>

```json
{
  "steps": [
    {"op": "watch_add", "ref": "0xc", "mode": "capture", "length": 4, "trigger": "0x10"},
    {"op": "run_for", "frames": 2, "seconds": 300}
  ]
}
```

```json
{
  "summary": "perform: 2 steps completed",
  "status": "ok",
  "ran": [
    {
      "op": "watch_add",
      "cpu": ":maincpu",
      "reply": {
        "summary": "watch_add 0xc (spriteram): capture watch pending at 0x0000000c (spriteram), 4 bytes",
        "status": "ok",
        "ref": "0xc",
        "by": "address",
        "mode": "capture",
        "length": 4,
        "fmt": "u32",
        "cpu": ":maincpu",
        "while_running": false,
        "trigger": "0x10",
        "trigger_type": "w",
        "addr": "0x0000000c",
        "stored": true,
        "armed": false,
        "state": "pending",
        "trigger_addr": "0x00000010",
        "trigger_maps_to": "memory@0",
        "source": {"kind": "share", "tag": ":spriteram", "offset": "0x0000000c"},
        "tally_id": "c_4_t10",
        "installed": false,
        "pending": true,
        "lines_ahead": 0,
        "call": "MAME_MCP_LUA_END#7",
        "note": "the tap is installed when the console next reads a line (a step, the next frame emulated, or a debugger command on a stub that refreshes after one) and counts from there; the survey of the stop after that reads it back",
        "names": [
          {"field": "given.ref", "number": "0xc", "kind": "memory", "name": "spriteram"},
          {"field": "addr", "number": "0x0000000c", "kind": "memory", "name": "spriteram"}
        ],
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      },
      "frame_before": 543,
      "frame_after": 543
    },
    {
      "op": "run_for",
      "cpu": ":maincpu",
      "reply": {
        "summary": "run_for 2 frames: ELAPSED, frame 543 to 545",
        "status": "ok",
        "verdict": "ELAPSED",
        "frame_before": 543,
        "frame_after": 545,
        "emulated_before_s": 9.19144,
        "emulated_after_s": 9.225231,
        "cycles": 42239,
        "polls": 3,
        "cause": "the `gvblank` stop of the last frame asked",
        "stop_seq": 9,
        "pc": "0x0000fd80",
        "cpu": ":maincpu",
        "frame": 545,
        "regs": {
          "A": "0xff",
          "B": "0x72",
          "D": "0xff72",
          "X": "0x0100",
          "Y": "0x00f1",
          "U": "0xc66d",
          "PC": "0xfd80",
          "S": "0x07f4",
          "CC": "0xf4",
          "DP": "0x00"
        },
        "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
        "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
        "errorlog": "<volatile>",
        "watches": [
          {
            "ref": "0xc",
            "cpu": ":maincpu",
            "state": "captured",
            "total": 3,
            "callback_errors": {
              "count": 0,
              "first": {"available": false, "why": "no callback raised"}
            },
            "since_last_stop": 2
          }
        ],
        "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "length", "mode", "overflow_rows", "pending", "rows_kept", "rows_max", "rows_path", "source", "superseded", "tally_id", "trigger_addr", "trigger_type"],
        "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      },
      "frame_before": 543,
      "frame_after": 545
    }
  ],
  "steps_completed": 2,
  "failed_at": {"available": false, "why": "no step failed"},
  "held": 0,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**29. `read_block`**: OK sprite entry: the entry 5b009394: tile 91, drawn at (148, 164)

<details><summary>call and reply</summary>

```json
{
  "tag": "spriteram",
  "offset": 12,
  "length": 4
}
```

```json
{
  "summary": "read_block share :spriteram: 4 bytes at offset 0x0000000c of 0x800: 5b009394",
  "status": "ok",
  "kind": "share",
  "tag": ":spriteram",
  "size": 2048,
  "bytewidth": 1,
  "endianness": "big",
  "offset": "0x0000000c",
  "length": 4,
  "hex": "5b009394",
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#8",
  "pc_before": "0x0000fd80",
  "cause": "read_block: one step",
  "stop_seq": 10,
  "pc": "0x0000fd82",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0xff",
    "B": "0x72",
    "D": "0xff72",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd82",
    "S": "0x07f4",
    "CC": "0xf8",
    "DP": "0x00"
  },
  "instruction": {"address": "FD82", "bytes": "96B2", "text": "LDA    <$B2", "symbol": "irq", "delta": 2},
  "following": ["FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF", "FDA1: D7 BF    STB    <$BF"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
      "callback_errors": {
        "count": 0,
        "first": {"available": false, "why": "no callback raised"}
      },
      "since_last_stop": 0
    }
  ],
  "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "length", "mode", "overflow_rows", "pending", "rows_kept", "rows_max", "rows_path", "source", "superseded", "tally_id", "trigger_addr", "trigger_type"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**30. `screen_view`**: OK pixel: pixel (151, 172) is pen 838, #449933

<details><summary>call and reply</summary>

```json
{
  "mode": "pixel",
  "point": [151, 172],
  "dest": "./tmp/demos/tour/pixel.png"
}
```

```json
{
  "summary": "screen_view pixel :screen frame 545: (151, 172) is pen 0x346 #449933; no logged write to it: no manifest is loaded: `gfx_load` a gfx.yaml whose `palette_ports` names this palette, then `palette_log(palette_port=..., arm=True)` arms the log that answers who set a pen; 388x388 PNG x8, inline",
  "status": "ok",
  "mode": "pixel",
  "screen": ":screen",
  "width": 256,
  "height": 240,
  "frame_screen": 545,
  "palette": ":palette",
  "entries": 2048,
  "screen_indexed": true,
  "x": 151,
  "y": 172,
  "pen": 838,
  "color": "#449933",
  "set_by": {
    "available": false,
    "why": "no manifest is loaded: `gfx_load` a gfx.yaml whose `palette_ports` names this palette, then `palette_log(palette_port=..., arm=True)` arms the log that answers who set a pen"
  },
  "crop": [127, 148, 48, 48],
  "point_in_crop": [24, 24],
  "image": {
    "path": "./tmp/demos/tour/pixel.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 388,
    "height": 388,
    "scale": 8,
    "indexed": false,
    "inline": true,
    "border": 2
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#9",
  "pc_before": "0x0000fd82",
  "cause": "screen_view: one step",
  "stop_seq": 11,
  "pc": "0x0000fd84",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0xbc",
    "B": "0x72",
    "D": "0xbc72",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd84",
    "S": "0x07f4",
    "CC": "0xf8",
    "DP": "0x00"
  },
  "instruction": {"address": "FD84", "bytes": "8403", "text": "ANDA   #$03", "symbol": "irq", "delta": 4},
  "following": ["FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF", "FDA1: D7 BF    STB    <$BF", "FDA3: 97 BD    STA    <$BD"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
      "callback_errors": {
        "count": 0,
        "first": {"available": false, "why": "no callback raised"}
      },
      "since_last_stop": 0
    }
  ],
  "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "length", "mode", "overflow_rows", "pending", "rows_kept", "rows_max", "rows_path", "source", "superseded", "tally_id", "trigger_addr", "trigger_type"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

Also attached: image/png.

</details>

**31. `palette`**: OK palette: 32 pens from 832 of 2048

<details><summary>call and reply</summary>

```json
{
  "first": 832,
  "count": 32,
  "dest": "./tmp/demos/tour/palette.png"
}
```

```json
{
  "summary": "palette :palette: pens 0x340..0x35f of 2048, more after; 1128x128 PNG x8, inline",
  "status": "ok",
  "palette": ":palette",
  "entries": 2048,
  "first": 832,
  "count": 32,
  "truncated": false,
  "shadows": false,
  "highlights": false,
  "indirect_entries": 0,
  "colors": ["#8866bb", "#ff0000", "#cc0000", "#660000", "#ccff88", "#77cc44", "#449933", "#ff77ff", "#ff9900", "#990000", "#00bb22", "#777777", "#cccccc", "#000000", "#889999", "#ffffff", "#11ffdd", "#55bbff", "#55aaff", "#5599ff", "#222222", "#dd22ee", "#dd2244", "#22ddbb", "#33bbaa", "#1188ff", "#4477bb", "#5566aa", "#446677", "#115555", "#5577dd", "#5577aa"],
  "image": {
    "path": "./tmp/demos/tour/palette.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 1128,
    "height": 128,
    "scale": 8,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#10",
  "pc_before": "0x0000fd84",
  "cause": "palette: one step",
  "stop_seq": 12,
  "pc": "0x0000fd86",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0x00",
    "B": "0x72",
    "D": "0x0072",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd86",
    "S": "0x07f4",
    "CC": "0xf4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD86", "bytes": "2604", "text": "BNE    $FD8C", "symbol": "irq", "delta": 6},
  "following": ["FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF", "FDA1: D7 BF    STB    <$BF", "FDA3: 97 BD    STA    <$BD", "FDA5: F6 95 00 LDB    $9500"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
      "callback_errors": {
        "count": 0,
        "first": {"available": false, "why": "no callback raised"}
      },
      "since_last_stop": 0
    }
  ],
  "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "length", "mode", "overflow_rows", "pending", "rows_kept", "rows_max", "rows_path", "source", "superseded", "tally_id", "trigger_addr", "trigger_type"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

Also attached: image/png.

</details>

**32. `gfx_sweep`**: OK sweep: 3 candidates drawn, s1c1 is 4bpp 8x16 packed, rows

<details><summary>call and reply</summary>

```json
{
  "tag": "gfx1",
  "planes": [4],
  "sizes": [
    [8, 16]
  ],
  "count": 16,
  "dest": "./tmp/demos/tour/sweep.png"
}
```

```json
{
  "summary": "gfx_sweep region :gfx1: sweep 1, 3 candidates s1c1..s1c3, 3 drawn; 1568x384 PNG x2, inline",
  "status": "ok",
  "kind": "region",
  "tag": ":gfx1",
  "size": 16384,
  "bytewidth": 1,
  "endianness": "little",
  "offset": "0x00000000",
  "sweep": 1,
  "count": 16,
  "palette": "none",
  "pen_base": 0,
  "real_colors": false,
  "cell_scale": 4,
  "candidates": [
    {"id": "s1c1", "what": "4bpp 8x16 packed, rows", "tiles_available": 256, "shown": 16},
    {"id": "s1c2", "what": "4bpp 8x16 planar, rows", "tiles_available": 256, "shown": 16},
    {"id": "s1c3", "what": "4bpp 8x16 split, rows", "tiles_available": 256, "shown": 16}
  ],
  "next": "gfx_locate(layouts=[<ids>]) proves one against the screen; gfx_draft(choose={\"candidate\": <id>, \"chosen_by\": <who>}) records a person's pick",
  "note": "palette `none`: a grey ramp over the pixel values, NOT the machine's colours",
  "image": {
    "path": "./tmp/demos/tour/sweep.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 1568,
    "height": 384,
    "scale": 2,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#11",
  "pc_before": "0x0000fd86",
  "cause": "gfx_sweep: one step",
  "stop_seq": 13,
  "pc": "0x0000fd88",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0x00",
    "B": "0x72",
    "D": "0x0072",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd88",
    "S": "0x07f4",
    "CC": "0xf4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD88", "bytes": "0CB3", "text": "INC    <$B3", "symbol": "irq", "delta": 8},
  "following": ["FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF", "FDA1: D7 BF    STB    <$BF", "FDA3: 97 BD    STA    <$BD", "FDA5: F6 95 00 LDB    $9500"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
      "callback_errors": {
        "count": 0,
        "first": {"available": false, "why": "no callback raised"}
      },
      "since_last_stop": 0
    }
  ],
  "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "length", "mode", "overflow_rows", "pending", "rows_kept", "rows_max", "rows_path", "source", "superseded", "tally_id", "trigger_addr", "trigger_type"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

Also attached: image/png.

</details>

**33. `gfx_locate`**: OK locate: tile 91 of gfx1 is on the screen at (148, 164), where the entry draws it

<details><summary>call and reply</summary>

```json
{
  "layouts": ["s1c1"],
  "patch": [148, 164, 8, 16],
  "tag": "gfx1",
  "transparent": 0
}
```

```json
{
  "summary": "gfx_locate region :gfx1 for patch [148, 164, 8, 16]: 1 match, first s1c1 tile 91 flip none base 0x340",
  "status": "ok",
  "patch": [148, 164, 8, 16],
  "screen": ":screen",
  "frame_screen": 545,
  "palette": ":palette",
  "kind": "region",
  "tag": ":gfx1",
  "size": 16384,
  "bytewidth": 1,
  "endianness": "little",
  "offset": "0x00000000",
  "transparent": 0,
  "flips": ["none", "x", "y", "xy"],
  "candidates": [
    {
      "layout": {
        "name": "s1c1",
        "width": 8,
        "height": 16,
        "planes": 4,
        "planeoffset": [0, 1, 2, 3],
        "xoffset": [0, 4, 8, 12, 16, 20, 24, 28],
        "yoffset": [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 480],
        "charincrement": 512
      },
      "tiles_searched": [0, 256],
      "windows": 1,
      "windows_uniform": 0,
      "windows_mixed_bank": 0,
      "matches": 1,
      "tiles_available": 256
    }
  ],
  "matched": true,
  "matches_total": 1,
  "matches": [
    {
      "layout": "s1c1",
      "window": [148, 164],
      "tile": 91,
      "flip": "none",
      "base": 832,
      "bit": 46592,
      "byte": 5824,
      "compared": 78,
      "shape": [16, 8, 1],
      "ambiguous": false
    }
  ],
  "ambiguous": false,
  "ambiguous_windows": 0,
  "pen_map": {"available": false, "why": "the single-bank search matched, so no pen map was tried"},
  "evidence": {"locate": 1},
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#12",
  "pc_before": "0x0000fd88",
  "cause": "gfx_locate: one step",
  "stop_seq": 14,
  "pc": "0x0000fd8a",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0x00",
    "B": "0x72",
    "D": "0x0072",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd8a",
    "S": "0x07f4",
    "CC": "0xf8",
    "DP": "0x00"
  },
  "instruction": {"address": "FD8A", "bytes": "0CB4", "text": "INC    <$B4", "symbol": "irq", "delta": 10},
  "following": ["FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF", "FDA1: D7 BF    STB    <$BF", "FDA3: 97 BD    STA    <$BD", "FDA5: F6 95 00 LDB    $9500", "FDA8: 1F 98    TFR    B,A"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
      "callback_errors": {
        "count": 0,
        "first": {"available": false, "why": "no callback raised"}
      },
      "since_last_stop": 0
    }
  ],
  "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "length", "mode", "overflow_rows", "pending", "rows_kept", "rows_max", "rows_path", "source", "superseded", "tally_id", "trigger_addr", "trigger_type"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**34. `gfx_draft`**: OK draft: a draft with the format chosen, tiles_8x16x4

<details><summary>call and reply</summary>

```json
{
  "dest": "./tmp/demos/tour/gridlee-gfx-draft.yaml",
  "choose": {"candidate": "s1c1", "chosen_by": "the tour"}
}
```

```json
{
  "summary": "gfx_draft ./tmp/demos/tour/gridlee-gfx-draft.yaml: 1 format (1 human), 0 assets, 0 commands; 2 not proved",
  "status": "ok",
  "manifest": {
    "path": "./tmp/demos/tour/gridlee-gfx-draft.yaml",
    "sha256": "227b32e68e59f87c84a0ed70236c92d935c8c42bb20b8f66a6a3269c8aca106d"
  },
  "report": {
    "path": "./tmp/demos/tour/gridlee-gfx-draft-report.json",
    "sha256": "f9ebfb3bc5a0cd52f14c89d301a93ab81dd4ec28918273278768ac5bd4151b42"
  },
  "formats": {"tiles_8x16x4": "human"},
  "asset_names": [],
  "command_fields": {},
  "evidence": {"locates": 1, "sweeps": 1, "choices": 1, "correlations": 0},
  "not_proved": [":gfx1: s1c1 matched only windows that prove no layout (failed: rarest)", ":gfx1: no asset for tiles_8x16x4, chosen under no palette"],
  "confirm": "the owner confirms the draft by deleting its first line; `gfx_load` loads it before that and says `draft: true`",
  "chose": {"candidate": "s1c1", "chosen_by": "the tour"},
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**35. `gfx_load`**: OK manifest: formats ['sprite'], commands ['player', 'player_in_play']

<details><summary>call and reply</summary>

```json
{
  "path": "./docs/reference/tour/gridlee-gfx.yaml"
}
```

```json
{
  "summary": "gfx_load ./docs/reference/tour/gridlee-gfx.yaml: 1 format, 1 asset, 2 commands, 0 palette ports; 16 proved, 0 declared, 0 human",
  "status": "ok",
  "loaded": true,
  "replaced_path": {"available": false, "why": "no manifest was loaded in this session before this one"},
  "path": "./docs/reference/tour/gridlee-gfx.yaml",
  "sha256": "4f19460d57d18c6d2a23b84017798676eeaff818bdecae8bae3e845c88fab2e1",
  "draft": false,
  "systems": ["gridlee"],
  "formats": {"sprite": "proved"},
  "assets": {
    "sprites": {"format": "sprite", "tag": "gfx1", "palette": "palette"}
  },
  "commands": {
    "player": {
      "block": "0x0000000c",
      "length": 4,
      "trigger_addr": "0x00000010",
      "fires_with": "any write",
      "asset": "sprites",
      "roles": ["dest_x", "dest_y", "height", "source_tile", "width"],
      "flags": [],
      "planes": []
    },
    "player_in_play": {
      "block": "0x00000020",
      "length": 4,
      "trigger_addr": "0x00000024",
      "fires_with": "any write",
      "asset": "sprites",
      "roles": ["dest_x", "dest_y", "height", "source_tile", "width"],
      "flags": [],
      "planes": []
    }
  },
  "palette_ports": {},
  "status_counts": {"proved": 16, "declared": 0, "human": 0},
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**36. `gfx_view`**: OK tiles: tiles 88 to 95 in the palette's colours

<details><summary>call and reply</summary>

```json
{
  "layout": "sprite",
  "tag": "gfx1",
  "palette": "palette",
  "first": 88,
  "count": 8,
  "columns": 8,
  "pen_base": 832,
  "dest": "./tmp/demos/tour/tiles.png"
}
```

```json
{
  "summary": "gfx_view region :gfx1: tiles 88..95 of 256, 8x16x4, palette :palette; 512x128 PNG x8, inline",
  "status": "ok",
  "layout": {
    "name": "sprite",
    "width": 8,
    "height": 16,
    "planes": 4,
    "planeoffset": [0, 1, 2, 3],
    "xoffset": [0, 4, 8, 12, 16, 20, 24, 28],
    "yoffset": [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 480],
    "charincrement": 512
  },
  "kind": "region",
  "tag": ":gfx1",
  "size": 16384,
  "bytewidth": 1,
  "endianness": "little",
  "offset": "0x00000000",
  "first": 88,
  "count": 8,
  "tiles_available": 256,
  "columns": 8,
  "palette": ":palette",
  "pen_base": 832,
  "real_colors": true,
  "image": {
    "path": "./tmp/demos/tour/tiles.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 512,
    "height": 128,
    "scale": 8,
    "indexed": true,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#13",
  "pc_before": "0x0000fd8a",
  "cause": "gfx_view: one step",
  "stop_seq": 15,
  "pc": "0x0000fd8c",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0x00",
    "B": "0x72",
    "D": "0x0072",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd8c",
    "S": "0x07f4",
    "CC": "0xf0",
    "DP": "0x00"
  },
  "instruction": {"address": "FD8C", "bytes": "B603BE", "text": "LDA    $03BE", "symbol": "irq", "delta": 12},
  "following": ["FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF", "FDA1: D7 BF    STB    <$BF", "FDA3: 97 BD    STA    <$BD", "FDA5: F6 95 00 LDB    $9500", "FDA8: 1F 98    TFR    B,A", "FDAA: D0 BC    SUBB   <$BC"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
      "callback_errors": {
        "count": 0,
        "first": {"available": false, "why": "no callback raised"}
      },
      "since_last_stop": 0
    }
  ],
  "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "length", "mode", "overflow_rows", "pending", "rows_kept", "rows_max", "rows_path", "source", "superseded", "tally_id", "trigger_addr", "trigger_type"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

Also attached: image/png.

</details>

**37. `gfx_blits`**: OK blits: frame 545: the box of tile 91, written from write_sprites+0x29, is where gfx_locate found it

<details><summary>call and reply</summary>

```json
{
  "draw_command": "player",
  "frame": 545,
  "area": [148, 164, 8, 16],
  "dest": "./tmp/demos/tour/blits.png"
}
```

```json
{
  "summary": "gfx_blits player frame 545: 1 of 1 blit covers [148, 164, 8, 16], topmost #0 pc 0x0000a81f; 1024x960 PNG x4, inline",
  "status": "ok",
  "draw_command": "player",
  "frame_blit": 545,
  "frame_complete": false,
  "rows_cut": false,
  "screen": ":screen",
  "frame_screen": 545,
  "width": 256,
  "height": 240,
  "rows_path": "<volatile>",
  "rows_kept": 3,
  "overflow_rows": 0,
  "callback_errors": {
    "count": 0,
    "first": {"available": false, "why": "no callback raised"}
  },
  "frames_with_blits": {"first": 543, "last": 545, "count": 3},
  "blits_in_frame": 1,
  "legend": [
    {"pc": "0x0000a81f", "symbol": "write_sprites+0x29", "color": "#ff4040", "blits": 1}
  ],
  "colors_repeat": false,
  "by_plane": [
    {
      "plane": {"available": false, "why": "the command declares no plane"},
      "page": {"available": false, "why": "the plane is not drawn in pages"},
      "blits": 1,
      "on_screen": 1
    }
  ],
  "area": [148, 164, 8, 16],
  "covering": 1,
  "topmost": {
    "index": 0,
    "n": 3,
    "pc": "0x0000a81f",
    "plane": {"available": false, "why": "the command declares no plane"}
  },
  "note": "a box COVERS the area; what painted a pixel also needs the source pixels, their transparency and the scale, which the rows do not carry: `topmost` is the last covering blit of the highest plane, the likeliest painter, not a proven one",
  "listed": {"first": 0, "count": 1, "of": 1},
  "blits": [
    {
      "index": 0,
      "n": 3,
      "pc": "0x0000a81f",
      "box": {"x": 148, "y": 164, "width": 8, "height": 16, "dir_x": 1, "dir_y": 1},
      "plane": {"available": false, "why": "the command declares no plane"},
      "screen": [
        [148, 164, 8, 16]
      ],
      "on_screen": true,
      "clipped": false,
      "fields": {"source_tile": 91, "dest_y": 164, "dest_x": 148, "width": 8, "height": 16},
      "flags": {},
      "symbol": "write_sprites+0x29"
    }
  ],
  "not_proved": [],
  "image": {
    "path": "./tmp/demos/tour/blits.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 1024,
    "height": 960,
    "scale": 4,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#14",
  "pc_before": "0x0000fd8c",
  "cause": "gfx_blits: one step",
  "stop_seq": 16,
  "pc": "0x0000fd8f",
  "cpu": ":maincpu",
  "frame": 545,
  "regs": {
    "A": "0x00",
    "B": "0x72",
    "D": "0x0072",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd8f",
    "S": "0x07f4",
    "CC": "0xf4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD8F", "bytes": "2628", "text": "BNE    $FDB9", "symbol": "irq", "delta": 15},
  "following": ["FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF", "FDA1: D7 BF    STB    <$BF", "FDA3: 97 BD    STA    <$BD", "FDA5: F6 95 00 LDB    $9500", "FDA8: 1F 98    TFR    B,A", "FDAA: D0 BC    SUBB   <$BC", "FDAC: C4 0F    ANDB   #$0F", "FDAE: 85 10    BITA   #$10"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "0xc",
      "cpu": ":maincpu",
      "state": "captured",
      "total": 3,
      "callback_errors": {
        "count": 0,
        "first": {"available": false, "why": "no callback raised"}
      },
      "since_last_stop": 0
    }
  ],
  "omitted": ["addr", "by", "fmt", "frame_as_of", "install_resent", "installed", "length", "mode", "overflow_rows", "pending", "rows_kept", "rows_max", "rows_path", "source", "superseded", "tally_id", "trigger_addr", "trigger_type"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

Also attached: image/png.

</details>

**38. `declaration_clear`**: OK clear capture: 1 watch cleared

<details><summary>call and reply</summary>

```json
{
  "kind": "watch",
  "all": true
}
```

```json
{
  "summary": "declaration_clear watch all: 1 cleared, 0 disarmed, 1 tap removed",
  "status": "ok",
  "declarations_cleared": 1,
  "disarmed": [],
  "while_running": false,
  "tallies_removed": [
    {"tally_id": "c_4_t10", "removal": "pending", "lines_ahead": 0, "call": "MAME_MCP_LUA_END#15"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**39. `input`**: OK coin 3: a coin, held four frames and released

<details><summary>call and reply</summary>

```json
{
  "port": ":IN1",
  "field": "Coin 1",
  "frames": 4,
  "seconds": 300
}
```

```json
{
  "summary": "input :IN1 'Coin 1': held 4 frames, active True, released at frame 549",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 545,
  "frame_after": 550,
  "emulated_before_s": 9.225259,
  "emulated_after_s": 9.309714,
  "cycles": 105569,
  "polls": 5,
  "lines_ahead": 1,
  "drain_steps": 1,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":IN1",
  "field": "Coin 1",
  "value": "0x00000001",
  "frames": 4,
  "name": "Coin 1",
  "player": 0,
  "mask": "0x00000001",
  "defvalue": "0x00000001",
  "port_before": "0x000000cf",
  "frame_set": 545,
  "released": true,
  "port_held": "0x000000ce",
  "frame_released": 549,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 17,
  "pc": "0x0000fd80",
  "cpu": ":maincpu",
  "frame": 550,
  "regs": {
    "A": "0xff",
    "B": "0x6d",
    "D": "0xff6d",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd80",
    "S": "0x07f4",
    "CC": "0xf4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**40. `run_to`**: OK to the coin: reached count_coin, the control counted 1

<details><summary>call and reply</summary>

```json
{
  "ref": "count_coin",
  "control": "wait_frame",
  "seconds": 300
}
```

```json
{
  "summary": "run_to count_coin: TARGET, control counted 1",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 1,
  "controls": [
    {"ref": "wait_frame", "cpu": ":maincpu", "hits_in_run": 1}
  ],
  "cause": "target count_coin",
  "stop_seq": 18,
  "pc": "0x0000b583",
  "cpu": ":maincpu",
  "frame": 552,
  "regs": {
    "A": "0x01",
    "B": "0xcf",
    "D": "0x01cf",
    "X": "0xe199",
    "Y": "0xf2e6",
    "U": "0x7acf",
    "PC": "0xb583",
    "S": "0x07fc",
    "CC": "0xa4",
    "DP": "0x00"
  },
  "instruction": {
    "address": "B583",
    "bytes": "7C042B",
    "text": "INC    $042B",
    "symbol": "count_coin",
    "delta": 0,
    "comment": "a coin: INC credits, then the BCD copy"
  },
  "following": ["B586: 86 01    LDA    #$01", "B588: BB 04 2C ADDA   $042C", "B58B: 19       DAA", "B58C: B7 04 2C STA    $042C", "B58F: 39       RTS", "B590: 96 F4    LDA    <$F4", "B592: 27 21    BEQ    $B5B5", "B594: 96 B3    LDA    <$B3", "B596: 84 07    ANDA   #$07", "B598: 26 1A    BNE    $B5B4", "B59A: 8E F6 59 LDX    #$F659", "B59D: 96 F5    LDA    <$F5", "B59F: 27 03    BEQ    $B5A4", "B5A1: 8E F7 49 LDX    #$F749"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**41. `step`**: OK step: one instruction, INC $042B, and pc 0x0000b586

<details><summary>call and reply</summary>

```json
{
  "count": 1
}
```

```json
{
  "summary": "step 1 into: pc 0x0000b586",
  "status": "ok",
  "mode": "into",
  "instructions_completed": 1,
  "cause": "step 1",
  "stop_seq": 19,
  "pc": "0x0000b586",
  "cpu": ":maincpu",
  "frame": 552,
  "regs": {
    "A": "0x01",
    "B": "0xcf",
    "D": "0x01cf",
    "X": "0xe199",
    "Y": "0xf2e6",
    "U": "0x7acf",
    "PC": "0xb586",
    "S": "0x07fc",
    "CC": "0xa0",
    "DP": "0x00"
  },
  "instruction": {"address": "B586", "bytes": "8601", "text": "LDA    #$01", "symbol": "count_coin", "delta": 3},
  "following": ["B588: BB 04 2C ADDA   $042C", "B58B: 19       DAA", "B58C: B7 04 2C STA    $042C", "B58F: 39       RTS", "B590: 96 F4    LDA    <$F4", "B592: 27 21    BEQ    $B5B5", "B594: 96 B3    LDA    <$B3", "B596: 84 07    ANDA   #$07", "B598: 26 1A    BNE    $B5B4", "B59A: 8E F6 59 LDX    #$F659", "B59D: 96 F5    LDA    <$F5", "B59F: 27 03    BEQ    $B5A4", "B5A1: 8E F7 49 LDX    #$F749", "B5A4: CE 0A 85 LDU    #$0A85"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**42. `watch_add`**: OK watch: a change watch on credits_bcd, 0x0000042c

<details><summary>call and reply</summary>

```json
{
  "ref": "credits_bcd",
  "mode": "change"
}
```

```json
{
  "summary": "watch_add credits_bcd: change watch armed at 0x0000042c, 1 byte",
  "status": "ok",
  "ref": "credits_bcd",
  "by": "symbol",
  "mode": "change",
  "length": 1,
  "fmt": "u8",
  "cpu": ":maincpu",
  "while_running": false,
  "addr": "0x0000042c",
  "reading": {"available": true, "value": 2, "raw_hex": "02"},
  "stored": true,
  "armed": true,
  "state": "armed",
  "index": 1,
  "entry": "1 @ 042C-042C write",
  "write_maps_to": "memory@0",
  "read_maps_to": "memory@0",
  "values_from": "memory",
  "names": [
    {"field": "given.ref", "number": "0x042C", "kind": "symbol", "name": "credits_bcd"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**43. `run_for`**: OK bcd written: the BCD credits: Stopped at watchpoint 1 writing 03 to 042C (PC=B58C)

<details><summary>call and reply</summary>

```json
{
  "frames": 1,
  "seconds": 300
}
```

```json
{
  "summary": "run_for 1 frame: OTHER_STOP, frame 552 to 552",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 552,
  "frame_after": 552,
  "emulated_before_s": 9.32817,
  "emulated_after_s": 9.32817,
  "cycles": 0,
  "polls": 1,
  "cause": "watch credits_bcd: 0x0000042c written by pc 0x0000b58c",
  "stop_seq": 20,
  "pc": "0x0000b58f",
  "cpu": ":maincpu",
  "frame": 552,
  "regs": {
    "A": "0x03",
    "B": "0xcf",
    "D": "0x03cf",
    "X": "0xe199",
    "Y": "0xf2e6",
    "U": "0x7acf",
    "PC": "0xb58f",
    "S": "0x07fc",
    "CC": "0x80",
    "DP": "0x00"
  },
  "instruction": {"address": "B58F", "bytes": "39", "text": "RTS", "symbol": "count_coin", "delta": 12},
  "following": ["B590: 96 F4    LDA    <$F4", "B592: 27 21    BEQ    $B5B5", "B594: 96 B3    LDA    <$B3", "B596: 84 07    ANDA   #$07", "B598: 26 1A    BNE    $B5B4", "B59A: 8E F6 59 LDX    #$F659", "B59D: 96 F5    LDA    <$F5", "B59F: 27 03    BEQ    $B5A4", "B5A1: 8E F7 49 LDX    #$F749", "B5A4: CE 0A 85 LDU    #$0A85", "B5A7: B6 04 32 LDA    $0432", "B5AA: 27 03    BEQ    $B5AF", "B5AC: CE 0A C3 LDU    #$0AC3"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "credits_bcd",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "watch_hit": {
    "ref": "credits_bcd",
    "addr": "0x0000042c",
    "cpu": ":maincpu",
    "index": 1,
    "writes_total": 1,
    "truncated": false,
    "writer_pc": "0x0000b58c",
    "writes": [
      {"wrote": "0x03", "to": "0x0000042c", "pc": "0x0000b58c"}
    ],
    "values_from": "memory",
    "before": 2,
    "after": 3,
    "lines": ["Stopped at watchpoint 1 writing 03 to 042C (PC=B58C)"]
  },
  "names": [
    {
      "field": "watch_hit.writer_pc",
      "number": "0x0000b58c",
      "kind": "symbol",
      "name": "count_coin",
      "delta": 9
    }
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**44. `history`**: OK trail: the trail: INC $042B, LDA #$01, ADDA $042C, DAA, STA $042C

<details><summary>call and reply</summary>

```json
{
  "limit": 8
}
```

```json
{
  "summary": "history: 8 instructions of 8 asked",
  "status": "ok",
  "asked": 8,
  "lines": ["B579: DEC    $0491", "B57C: JSR    $B583", "B583: INC    $042B", "B586: LDA    #$01", "B588: ADDA   $042C", "B58B: DAA", "B58C: STA    $042C", "B58F: RTS"],
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**45. `registers`**: OK registers: PC 0xb58f, A 0x03: the BCD credits just written

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "registers: 10 registers",
  "status": "ok",
  "regs": {
    "A": "0x03",
    "B": "0xcf",
    "D": "0x03cf",
    "X": "0xe199",
    "Y": "0xf2e6",
    "U": "0x7acf",
    "PC": "0xb58f",
    "S": "0x07fc",
    "CC": "0x80",
    "DP": "0x00"
  },
  "register_bits": {"A": 8, "B": 8, "D": 16, "X": 16, "Y": 16, "U": 16, "PC": 16, "S": 16, "CC": 8, "DP": 8},
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**46. `breakpoint_at`**: OK breakpoint: a breakpoint on take_credit, 0x0000d676

<details><summary>call and reply</summary>

```json
{
  "ref": "take_credit"
}
```

```json
{
  "summary": "breakpoint_at take_credit: armed at 0x0000d676",
  "status": "ok",
  "ref": "take_credit",
  "by": "symbol",
  "role": "stop",
  "cpu": ":maincpu",
  "stored": true,
  "while_running": false,
  "addr": "0x0000d676",
  "armed": true,
  "state": "armed",
  "entry": "3 @ D676",
  "names": [
    {"field": "given.ref", "number": "0xD676", "kind": "symbol", "name": "take_credit"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**47. `input`**: OK press start: START stopped at the breakpoint, 0x0000d676, still held

<details><summary>call and reply</summary>

```json
{
  "port": ":IN1",
  "field": "1 Player Start",
  "frames": 4,
  "seconds": 300
}
```

```json
{
  "summary": "input :IN1 '1 Player Start': still HELD from frame 552, releases at 556",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 552,
  "frame_after": 553,
  "emulated_before_s": 9.343506,
  "emulated_after_s": 9.347718,
  "cycles": 5265,
  "polls": 2,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":IN1",
  "field": "1 Player Start",
  "value": "0x00000001",
  "frames": 4,
  "name": "1 Player Start",
  "player": 0,
  "mask": "0x00000004",
  "defvalue": "0x00000004",
  "port_before": "0x000000cf",
  "frame_set": 552,
  "released": false,
  "active": {
    "available": false,
    "why": "the field is still HELD: the port is read at its release, which the run has not reached"
  },
  "port_held": {
    "available": false,
    "why": "the field is still HELD: the port is read at its release, which the run has not reached"
  },
  "frame_release_planned": 556,
  "note": "the field is still HELD: the run stopped before the release frame, and the script releases it when the machine reaches it",
  "cause": "breakpoint take_credit at 0xd676",
  "stop_seq": 21,
  "pc": "0x0000d676",
  "cpu": ":maincpu",
  "frame": 553,
  "regs": {
    "A": "0xcb",
    "B": "0xff",
    "D": "0xcbff",
    "X": "0x0431",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xd676",
    "S": "0x07fc",
    "CC": "0xa8",
    "DP": "0x00"
  },
  "instruction": {"address": "D676", "bytes": "7A042B", "text": "DEC    $042B", "symbol": "take_credit", "delta": 0},
  "following": ["D679: 86 99    LDA    #$99", "D67B: BB 04 2C ADDA   $042C", "D67E: 19       DAA", "D67F: B7 04 2C STA    $042C", "D682: 39       RTS", "D683: 8E 04 31 LDX    #$0431", "D686: C6 5F    LDB    #$5F", "D688: 6F 85    CLR    B,X", "D68A: 5A       DECB", "D68B: 2A FB    BPL    $D688", "D68D: 39       RTS", "D68E: 0F B9    CLR    <$B9", "D690: D6 9A    LDB    <$9A", "D692: 86 03    LDA    #$03", "D694: 3D       MUL", "D695: 8E AB 76 LDX    #$AB76"],
  "errorlog": "<volatile>",
  "watches": [
    {
      "ref": "credits_bcd",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**48. `regpoint_add`**: OK regpoint: a registerpoint on a==99

<details><summary>call and reply</summary>

```json
{
  "condition": "a==99"
}
```

```json
{
  "summary": "regpoint_add a==99: armed, index 1",
  "status": "ok",
  "ref": "a==99",
  "cpu": ":maincpu",
  "by": "expr",
  "condition": "a==99",
  "stored": true,
  "while_running": false,
  "armed": true,
  "state": "armed",
  "entry": "1 if a==99",
  "index": 1,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**49. `run_for`**: OK a is 99: A became 0x99 at 0x0000d67b, after LDA #$99

<details><summary>call and reply</summary>

```json
{
  "frames": 1,
  "seconds": 300
}
```

```json
{
  "summary": "run_for 1 frame: OTHER_STOP, frame 553 to 553",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 553,
  "frame_after": 553,
  "emulated_before_s": 9.347726,
  "emulated_after_s": 9.347726,
  "cycles": 0,
  "polls": 1,
  "cause": "registerpoint 'a==99'",
  "stop_seq": 22,
  "pc": "0x0000d67b",
  "cpu": ":maincpu",
  "frame": 553,
  "regs": {
    "A": "0x99",
    "B": "0xff",
    "D": "0x99ff",
    "X": "0x0431",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xd67b",
    "S": "0x07fc",
    "CC": "0xa8",
    "DP": "0x00"
  },
  "instruction": {"address": "D67B", "bytes": "BB042C", "text": "ADDA   $042C", "symbol": "take_credit", "delta": 5},
  "following": ["D67E: 19       DAA", "D67F: B7 04 2C STA    $042C", "D682: 39       RTS", "D683: 8E 04 31 LDX    #$0431", "D686: C6 5F    LDB    #$5F", "D688: 6F 85    CLR    B,X", "D68A: 5A       DECB", "D68B: 2A FB    BPL    $D688", "D68D: 39       RTS", "D68E: 0F B9    CLR    <$B9", "D690: D6 9A    LDB    <$9A", "D692: 86 03    LDA    #$03", "D694: 3D       MUL", "D695: 8E AB 76 LDX    #$AB76", "D698: 3A       ABX", "D699: A6 80    LDA    ,X+"],
  "errorlog": "<volatile>",
  "regpoint_hit": {
    "ref": "a==99",
    "condition": "a==99",
    "pc": "0x0000d67b",
    "note": "still armed: a registerpoint stops at every instruction where its condition holds, so the next advance stops again; `declaration_clear(kind=\"regpoint\")` removes it",
    "cpu": ":maincpu",
    "index": 1
  },
  "watches": [
    {
      "ref": "credits_bcd",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "names": [
    {
      "field": "regpoint_hit.pc",
      "number": "0x0000d67b",
      "kind": "symbol",
      "name": "take_credit",
      "delta": 5
    }
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**50. `declaration_list`**: OK declarations: two breakpoints, a registerpoint and a watch are declared

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "declaration_list: 2 breakpoints (2 armed), 1 regpoint (1 armed), 1 watch (1 armed)",
  "status": "ok",
  "breakpoints": [
    {
      "ref": "wait_frame",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": "<volatile>",
      "role": "control",
      "addr": "0x0000a631",
      "state": "armed",
      "entry": "1 @ A631 if (++temp0)==0",
      "hits_since_armed": 3
    },
    {
      "ref": "take_credit",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": "<volatile>",
      "role": "stop",
      "addr": "0x0000d676",
      "state": "armed",
      "entry": "3 @ D676"
    }
  ],
  "regpoints": [
    {
      "ref": "a==99",
      "by": "expr",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": "<volatile>",
      "condition": "a==99",
      "state": "armed",
      "entry": "1 if a==99",
      "index": 1
    }
  ],
  "watches": [
    {
      "ref": "credits_bcd",
      "by": "symbol",
      "cpu": ":maincpu",
      "created_at": "<volatile>",
      "origin": "<volatile>",
      "inherited": false,
      "age_s": "<volatile>",
      "mode": "change",
      "length": 1,
      "fmt": "u8",
      "addr": "0x0000042c",
      "state": "armed",
      "entry": "1 @ 042C-042C write",
      "values_from": "memory"
    }
  ],
  "cpu": {"available": false, "why": "no cpu was named, so the rows are every cpu's"},
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**51. `declaration_clear`**: OK clear breakpoints: 2 breakpoints cleared

<details><summary>call and reply</summary>

```json
{
  "kind": "breakpoint",
  "all": true
}
```

```json
{
  "summary": "declaration_clear breakpoint all: 2 cleared, 2 disarmed",
  "status": "ok",
  "declarations_cleared": 2,
  "disarmed": ["1 @ A631 if (++temp0)==0", "3 @ D676"],
  "while_running": false,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**52. `declaration_clear`**: OK clear regpoint: 1 registerpoint cleared

<details><summary>call and reply</summary>

```json
{
  "kind": "regpoint",
  "all": true
}
```

```json
{
  "summary": "declaration_clear regpoint all: 1 cleared, 1 disarmed",
  "status": "ok",
  "declarations_cleared": 1,
  "disarmed": ["1 if a==99"],
  "while_running": false,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**53. `declaration_clear`**: OK clear watch: 1 watch cleared

<details><summary>call and reply</summary>

```json
{
  "kind": "watch",
  "all": true
}
```

```json
{
  "summary": "declaration_clear watch all: 1 cleared, 1 disarmed",
  "status": "ok",
  "declarations_cleared": 1,
  "disarmed": ["1 @ 042C-042C write"],
  "while_running": false,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**54. `series_capture`**: OK series: 4 frames, 557 to 581, and their manifest

<details><summary>call and reply</summary>

```json
{
  "first": 557,
  "last": 581,
  "step": 8,
  "dest": "./tmp/demos/tour/series",
  "seconds": 300
}
```

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
  "following": ["FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF", "FDA1: D7 BF    STB    <$BF"],
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
  "console_reruns": 0,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**55. `run_for`**: OK to the card: the level card ran to frame 702, 2500004 cycles

<details><summary>call and reply</summary>

```json
{
  "milliseconds": 2000,
  "seconds": 300
}
```

```json
{
  "summary": "run_for 2000 ms: ELAPSED, frame 583 to 702",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 583,
  "frame_after": 702,
  "emulated_before_s": 9.867285,
  "emulated_after_s": 11.867288,
  "cycles": 2500004,
  "reads": "<volatile>",
  "cause": "the console's `gtime` stop",
  "stop_seq": 25,
  "pc": "0x0000a633",
  "cpu": ":maincpu",
  "frame": 702,
  "regs": {
    "A": "0x00",
    "B": "0x99",
    "D": "0x0099",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xa633",
    "S": "0x0800",
    "CC": "0x84",
    "DP": "0x00"
  },
  "instruction": {"address": "A633", "bytes": "24FC", "text": "BCC    $A631", "symbol": "wait_frame", "delta": 2},
  "following": ["A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "A640: 7E F0 00 JMP    $F000", "A643: BD B5 2B JSR    $B52B", "A646: BD C5 67 JSR    $C567", "A649: B6 04 28 LDA    $0428", "A64C: 81 0C    CMPA   #$0C", "A64E: 24 51    BCC    $A6A1", "A650: B6 96 00 LDA    $9600"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**56. `screen_map_write`**: OK map: the level card mapped by its title, fingerprinted 5733a1938b03c102

<details><summary>call and reply</summary>

```json
{
  "method": "add",
  "screen": "level_card",
  "match": [
    [24, 104, 208, 16]
  ],
  "controls": [
    {"name": "level", "rect": [88, 152, 72, 8]}
  ]
}
```

```json
{
  "summary": "screen_map_write add: level_card (pixel 256x240), 1 region, 1 control",
  "status": "ok",
  "screen": "level_card",
  "kind": "pixel",
  "size": [256, 240],
  "cells": "rgb",
  "match": [
    {"crop": [24, 104, 208, 16], "signature": "5733a1938b03c102"}
  ],
  "controls": 1,
  "replaced": false,
  "shadows_file": false,
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#20",
  "pc_before": "0x0000a633",
  "cause": "screen_map_write add: one step",
  "stop_seq": 26,
  "pc": "0x0000a631",
  "cpu": ":maincpu",
  "frame": 702,
  "regs": {
    "A": "0x00",
    "B": "0x99",
    "D": "0x0099",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xa631",
    "S": "0x0800",
    "CC": "0x84",
    "DP": "0x00"
  },
  "instruction": {"address": "A631", "bytes": "04B4", "text": "LSR    <$B4", "symbol": "wait_frame", "delta": 0},
  "following": ["A633: 24 FC    BCC    $A631", "A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "A640: 7E F0 00 JMP    $F000", "A643: BD B5 2B JSR    $B52B", "A646: BD C5 67 JSR    $C567", "A649: B6 04 28 LDA    $0428", "A64C: 81 0C    CMPA   #$0C", "A64E: 24 51    BCC    $A6A1", "A650: B6 96 00 LDA    $9600"],
  "errorlog": "<volatile>",
  "kept": "3 saved for `promote`; maps/gridlee, perform/two-coins, start/gridlee: nothing this session read names its repository: promote(dry_run=true, root=<the repository>) lists what an approval would create",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**57. `screen_map_find`**: OK which screen: the screen is level_card, with its control level

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "screen_map_find: level_card (session), 1 control",
  "status": "ok",
  "matched": true,
  "screen": "level_card",
  "layer": "session",
  "kind": "pixel",
  "size": [256, 240],
  "controls": [
    {"name": "level", "rect": [88, 152, 72, 8], "centre": [124, 156]}
  ],
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#21",
  "pc_before": "0x0000a631",
  "cause": "screen_map_find: one step",
  "stop_seq": 27,
  "pc": "0x0000a633",
  "cpu": ":maincpu",
  "frame": 702,
  "regs": {
    "A": "0x00",
    "B": "0x99",
    "D": "0x0099",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xa633",
    "S": "0x0800",
    "CC": "0x84",
    "DP": "0x00"
  },
  "instruction": {"address": "A633", "bytes": "24FC", "text": "BCC    $A631", "symbol": "wait_frame", "delta": 2},
  "following": ["A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "A640: 7E F0 00 JMP    $F000", "A643: BD B5 2B JSR    $B52B", "A646: BD C5 67 JSR    $C567", "A649: B6 04 28 LDA    $0428", "A64C: 81 0C    CMPA   #$0C", "A64E: 24 51    BCC    $A6A1", "A650: B6 96 00 LDA    $9600"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**58. `state_write`**: OK load: state two-credits loaded and verified, frame 543

<details><summary>call and reply</summary>

```json
{
  "method": "load",
  "name": "two_credits"
}
```

```json
{
  "summary": "state_write load: two-credits, rom_check OK, verified True, frame 543, pc 0x0000b502",
  "status": "ok",
  "name": "two-credits",
  "path": "./tmp/demos/tour/gridlee-states/sta/gridlee/two-credits.sta",
  "rom_check": "OK",
  "verified": true,
  "saved": {"frame": 543, "pc": "0x0000b502"},
  "output": "State load attempted.  Please refer to window message popup for results.",
  "mark": "<volatile>",
  "taps_across": [
    {"ref": "film", "cpu": ":maincpu"}
  ],
  "cause": "stateload two-credits",
  "stop_seq": 28,
  "pc": "0x0000b502",
  "cpu": ":maincpu",
  "frame": 543,
  "regs": {
    "A": "0x02",
    "B": "0x70",
    "D": "0x0270",
    "X": "0xda5c",
    "Y": "0x0101",
    "U": "0xab79",
    "PC": "0xb502",
    "S": "0x07fc",
    "CC": "0xa9",
    "DP": "0x00"
  },
  "instruction": {
    "address": "B502",
    "bytes": "26F4",
    "text": "BNE    $B4F8",
    "symbol": "write_sprites",
    "delta": 3340
  },
  "following": ["B504: DC 86    LDD    <$86", "B506: 8E DA 62 LDX    #$DA62", "B509: 10 A3 81 CMPD   ,X++", "B50C: 23 07    BLS    $B515", "B50E: 0C 81    INC    <$81", "B510: 8C DA 6A CMPX   #$DA6A", "B513: 26 F4    BNE    $B509", "B515: 96 81    LDA    <$81", "B517: C6 05    LDB    #$05", "B519: 3D       MUL", "B51A: DB 80    ADDB   <$80", "B51C: D7 80    STB    <$80", "B51E: 86 07    LDA    #$07", "B520: 3D       MUL", "B521: D7 88    STB    <$88"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "note": "this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**59. `input`**: OK start again: START, held four frames and released

<details><summary>call and reply</summary>

```json
{
  "port": ":IN1",
  "field": "1 Player Start",
  "frames": 4,
  "seconds": 300
}
```

```json
{
  "summary": "input :IN1 '1 Player Start': held 4 frames, active True, released at frame 547",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 543,
  "frame_after": 548,
  "emulated_before_s": 9.191441,
  "emulated_after_s": 9.275924,
  "cycles": 105604,
  "polls": 6,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":IN1",
  "field": "1 Player Start",
  "value": "0x00000001",
  "frames": 4,
  "name": "1 Player Start",
  "player": 0,
  "mask": "0x00000004",
  "defvalue": "0x00000004",
  "port_before": "0x000000cf",
  "frame_set": 543,
  "released": true,
  "port_held": "0x000000cb",
  "frame_released": 547,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 29,
  "pc": "0x0000fd80",
  "cpu": ":maincpu",
  "frame": 548,
  "regs": {
    "A": "0xdd",
    "B": "0xdd",
    "D": "0xdddd",
    "X": "0x4748",
    "Y": "0x03ff",
    "U": "0x0433",
    "PC": "0xfd80",
    "S": "0x07f0",
    "CC": "0xd9",
    "DP": "0x00"
  },
  "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "note": "this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**60. `screen_wait`**: OK card: the level card is whole at frame 561, 13 frames on

<details><summary>call and reply</summary>

```json
{
  "screen": "level_card",
  "seconds": 300
}
```

```json
{
  "summary": "screen_wait screen 'level_card': found after 13 frames",
  "status": "ok",
  "verdict": "TARGET",
  "frame_before": 560,
  "frame_after": 561,
  "emulated_before_s": 9.478676,
  "emulated_after_s": 9.495568,
  "cycles": 21115,
  "polls": 13,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 55,
  "pc": "0x0000fd80",
  "cpu": ":maincpu",
  "frame": 561,
  "regs": {
    "A": "0x01",
    "B": "0x1d",
    "D": "0x011d",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xfd80",
    "S": "0x07f4",
    "CC": "0xd4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
  "errorlog": "<volatile>",
  "predicate": "screen",
  "already": false,
  "sampled_every": 0,
  "frames": 13,
  "waited_s": "<volatile>",
  "screen": {"name": "level_card", "layer": "session"},
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "note": "this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**61. `record`**: OK record: recorded 30 frames in ./tmp/demos/tour/card.avi

<details><summary>call and reply</summary>

```json
{
  "frames": 30,
  "dest": "./tmp/demos/tour/card.avi",
  "seconds": 300
}
```

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
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
  "errorlog": "<volatile>",
  "view": "native",
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "note": "this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**62. `audio_record`**: OK sound: 24000 samples at 48000 Hz, from 0 to 0

<details><summary>call and reply</summary>

```json
{
  "frames": 30,
  "dest": "./tmp/demos/tour/card.wav",
  "seconds": 300
}
```

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
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "note": "this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**63. `snapshot`**: OK snapshot: a picture of 256 x 240, saved through the native view

<details><summary>call and reply</summary>

```json
{
  "dest": "./tmp/demos/tour/card.png"
}
```

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "path": "./tmp/demos/tour/card.png",
  "bytes": "<volatile>",
  "sha256": "<volatile>",
  "view": "native",
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "note": "this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**64. `trace`**: OK trace: 9398 instructions at 192 addresses, in ['count_coin', 'irq', 'wait_frame', 'write_sprites']

<details><summary>call and reply</summary>

```json
{
  "frames": 2,
  "dest": "./tmp/demos/tour/trace.txt",
  "seconds": 300
}
```

```json
{
  "summary": "trace :maincpu 2 frames: 192 addresses in 4 symbols, 19627 bytes",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 628,
  "frame_after": 630,
  "emulated_before_s": 10.627602,
  "emulated_after_s": 10.661393,
  "cycles": 42239,
  "polls": 2,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 59,
  "pc": "0x0000fd80",
  "cpu": ":maincpu",
  "frame": 630,
  "regs": {
    "A": "0x00",
    "B": "0xd8",
    "D": "0x00d8",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xfd80",
    "S": "0x07f4",
    "CC": "0xd4",
    "DP": "0x00"
  },
  "instruction": {"address": "FD80", "bytes": "0CB2", "text": "INC    <$B2", "symbol": "irq", "delta": 0},
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
  "errorlog": "<volatile>",
  "trace": {
    "cpu": ":maincpu",
    "path": "./tmp/demos/tour/trace.txt",
    "bytes": 19627,
    "set_path": "./tmp/demos/tour/trace-txt-set.jsonl",
    "instructions": 9398,
    "addresses": 192,
    "unplaced": 0,
    "symbols": [
      {
        "symbol": "wait_frame",
        "addr": "0x0000a631",
        "addresses": 26,
        "first": "0x0000a631",
        "last": "0x0000a79b"
      },
      {
        "symbol": "write_sprites",
        "addr": "0x0000a7f6",
        "addresses": 25,
        "first": "0x0000b52b",
        "last": "0x0000b561"
      },
      {
        "symbol": "count_coin",
        "addr": "0x0000b583",
        "addresses": 36,
        "first": "0x0000b58f",
        "last": "0x0000cc5b"
      },
      {
        "symbol": "irq",
        "addr": "0x0000fd80",
        "addresses": 105,
        "first": "0x0000fd80",
        "last": "0x0000ffa0"
      }
    ],
    "symbols_total": 4,
    "truncated": false,
    "noloop": false,
    "note": "the pc :maincpu was parked on, 0x0000fd80, is counted: the window executed it first and the tracer, armed there, does not log it"
  },
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "note": "this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**65. `captures`**: OK captures: 15 files, of kinds ['avi', 'image', 'png', 'trace', 'wav']

<details><summary>call and reply</summary>

```json
{}
```

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
    {"kind": "image", "path": "./tmp/demos/tour/blits.png", "present": true, "bytes": "<volatile>"},
    {
      "kind": "image",
      "path": "./tmp/demos/tour/series/f000557.png",
      "present": true,
      "bytes": "<volatile>"
    },
    {
      "kind": "image",
      "path": "./tmp/demos/tour/series/f000565.png",
      "present": true,
      "bytes": "<volatile>"
    },
    {
      "kind": "image",
      "path": "./tmp/demos/tour/series/f000573.png",
      "present": true,
      "bytes": "<volatile>"
    },
    {
      "kind": "image",
      "path": "./tmp/demos/tour/series/f000581.png",
      "present": true,
      "bytes": "<volatile>"
    },
    {
      "kind": "avi",
      "path": "./tmp/demos/tour/card.avi",
      "present": true,
      "bytes": "<volatile>",
      "avi_frames": 30
    },
    {
      "kind": "wav",
      "path": "./tmp/demos/tour/card.wav",
      "present": true,
      "bytes": "<volatile>",
      "samples": 24000,
      "channels": 1,
      "sample_rate_hz": 48000
    },
    {"kind": "png", "path": "./tmp/demos/tour/card.png", "present": true, "bytes": "<volatile>"},
    {"kind": "trace", "path": "./tmp/demos/tour/trace.txt", "present": true, "bytes": "<volatile>"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "note": "this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**66. `memdump`**: OK dump: 4096 bytes from 0xa000, the reference image's

<details><summary>call and reply</summary>

```json
{
  "ref": "0xa000",
  "length": 4096,
  "dest": "./tmp/demos/tour/rom.bin"
}
```

```json
{
  "summary": "memdump 0xa000 (credits_bcd+0x9BD4): 4096 bytes to ./tmp/demos/tour/rom.bin",
  "status": "ok",
  "ref": "0xa000",
  "addr": "0x0000a000",
  "length": 4096,
  "path": "./tmp/demos/tour/rom.bin",
  "bytes": 4096,
  "cpu": ":maincpu",
  "names": [
    {"field": "given.ref", "number": "0xa000", "kind": "symbol", "name": "credits_bcd", "delta": 39892},
    {"field": "addr", "number": "0x0000a000", "kind": "symbol", "name": "credits_bcd", "delta": 39892}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "note": "this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**67. `lua`**: OK lua: the machine describes itself as Gridlee

<details><summary>call and reply</summary>

```json
{
  "script": "print(manager.machine.system.description)",
  "read_only": true
}
```

```json
{
  "summary": "lua: 8 chars back, pc 0x0000fd82 after one step",
  "status": "ok",
  "script_chars": 41,
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "call": "MAME_MCP_LUA_END#39",
  "pc_before": "0x0000fd80",
  "thread_errors": 0,
  "console_reruns": 0,
  "output": "Gridlee\n",
  "clipped": false,
  "cause": "lua: one step",
  "stop_seq": 60,
  "pc": "0x0000fd82",
  "cpu": ":maincpu",
  "frame": 630,
  "regs": {
    "A": "0x00",
    "B": "0xd8",
    "D": "0x00d8",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xfd82",
    "S": "0x07f4",
    "CC": "0xd0",
    "DP": "0x00"
  },
  "instruction": {"address": "FD82", "bytes": "96B2", "text": "LDA    <$B2", "symbol": "irq", "delta": 2},
  "following": ["FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF", "FDA1: D7 BF    STB    <$BF"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "read_only_claims": 1,
    "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for those calls; this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**68. `debug`**: OK console: 0x9380 is written through watchdog_timer_device::reset_w

<details><summary>call and reply</summary>

```json
{
  "command": "map 9380"
}
```

```json
{
  "summary": "debug 'map 9380'",
  "status": "ok",
  "command": "map 9380",
  "mutates": false,
  "output": "   Read: 9380 logical program == 9380 physical program -> unmapped\n  Write: 9380 logical program == 9380 physical program -> watchdog_timer_device::reset_w\n  Fetch: 9380 logical program == 9380 physical program -> unmapped\n\n",
  "clipped": false,
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "read_only_claims": 1,
    "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for those calls; this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**69. `write`**: OK write: both credit bytes written 9 and read back

<details><summary>call and reply</summary>

```json
{
  "ref": "credits",
  "data_hex": "0909"
}
```

```json
{
  "summary": "write credits: 2 bytes, verified True",
  "status": "ok",
  "ref": "credits",
  "addr": "0x0000042b",
  "bytes_written": 2,
  "readback": "0909",
  "verified": true,
  "cpu": ":maincpu",
  "names": [
    {"field": "given.ref", "number": "0x042B", "kind": "symbol", "name": "credits"}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "read_only_claims": 1,
    "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for those calls; this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**70. `set_register`**: OK force: A forced to 0x42

<details><summary>call and reply</summary>

```json
{
  "name": "A",
  "value": "0x42"
}
```

```json
{
  "summary": "set_register A = 0x42, verified True",
  "status": "ok",
  "register": "A",
  "value": "0x42",
  "readback": "0x42",
  "verified": true,
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "read_only_claims": 1,
    "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for those calls; this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**71. `promote`**: OK promote: a review, nothing written: maps/gridlee, perform/two-coins, start/gridlee

<details><summary>call and reply</summary>

```json
{
  "dry_run": true,
  "root": "./tmp/demos/tour"
}
```

```json
{
  "summary": "promote: 3 candidates in ./tmp/demos/tour/.scry; would create .scry/, .scry/about.json, .scry/README.md",
  "status": "ok",
  "store": "./tmp/demos/tour/.scry",
  "candidates": [
    {
      "entry": "maps/gridlee",
      "kind": "maps",
      "name": "gridlee",
      "file": ".scry/maps/gridlee-screen-map.json",
      "bytes": 440,
      "change": "new"
    },
    {
      "entry": "perform/two-coins",
      "kind": "perform",
      "name": "two-coins",
      "file": ".scry/perform/two-coins.json",
      "bytes": 3031,
      "change": "new"
    },
    {
      "entry": "start/gridlee",
      "kind": "start",
      "name": "gridlee",
      "file": ".scry/start/gridlee.json",
      "bytes": 352,
      "change": "new"
    }
  ],
  "unchanged": [],
  "total_bytes": 3823,
  "store_bytes": 5498,
  "would_create": [".scry/", ".scry/about.json", ".scry/README.md"],
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "read_only_claims": 1,
    "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for those calls; this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**72. `reset`**: OK reset: a soft reset, back at 0x0000f000

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "reset: softreset applied at frame 630, pc 0x0000f000 (take_credit+0x198A) verified True",
  "status": "ok",
  "kind": "softreset",
  "pc": "0x0000f000",
  "boot_pc": "0x0000f000",
  "verified": true,
  "frame_at_reset": 630,
  "taps_across": [
    {"ref": "film", "cpu": ":maincpu"}
  ],
  "cause": "softreset",
  "stop_seq": 61,
  "cpu": ":maincpu",
  "frame": 630,
  "regs": {
    "A": "0x42",
    "B": "0xd8",
    "D": "0x42d8",
    "X": "0x0014",
    "Y": "0xf2e6",
    "U": "0x4071",
    "PC": "0xf000",
    "S": "0x07f4",
    "CC": "0xd0",
    "DP": "0x00"
  },
  "instruction": {"address": "F000", "bytes": "1A50", "text": "ORCC   #$50", "symbol": "take_credit", "delta": 6538},
  "following": ["F002: 4F          CLRA", "F003: 1F 8B       TFR    A,DP", "F005: 10 CE 08 00 LDS    #$0800", "F009: BD D1 21    JSR    $D121", "F00C: B6 95 02    LDA    $9502", "F00F: 97 BC       STA    <$BC", "F011: 97 B8       STA    <$B8", "F013: 97 B7       STA    <$B7", "F015: B7 02 64    STA    $0264", "F018: B6 95 03    LDA    $9503", "F01B: B7 02 63    STA    $0263", "F01E: B6 97 00    LDA    $9700"],
  "errorlog": "<volatile>",
  "names": [
    {"field": "pc", "number": "0x0000f000", "kind": "symbol", "name": "take_credit", "delta": 6538}
  ],
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "read_only_claims": 1,
    "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for those calls; this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**73. `resume`**: OK resume: the machine runs

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "resume: running, no wait asked",
  "status": "ok",
  "session": {
    "alive": true,
    "running": true,
    "altered": true,
    "read_only_claims": 1,
    "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for those calls; this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**74. `stop`**: OK stop: stopped where it was

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "interrupted": true,
  "cause": "interrupt",
  "stop_seq": 62,
  "pc": "<volatile>",
  "cpu": ":maincpu",
  "frame": "<volatile>",
  "regs": "<volatile>",
  "instruction": "<volatile>",
  "following": "<volatile>",
  "errorlog": "<volatile>",
  "average_speed": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": true,
    "read_only_claims": 1,
    "note": "1 raw `lua` call was declared read_only BY THE CALLER and are not counted as writes. Nothing verified that claim: a Lua string can read a byte or rewrite RAM and the text does not say which, so `altered` here rests on the caller's word for those calls; this session has been MODIFIED: what is measured here does not describe a normal run of the game",
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**75. `close`**: OK close: closed: MAME quit on its own

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "close: quit, exit code 0, last words left out (see `omitted`)",
  "status": "ok",
  "closed": true,
  "omitted": ["stdout_tail", "errorlog_tail"],
  "how": "close(detail=True) keeps the channels' last words on a clean quit too; once a close has answered they are gone with the scratch",
  "ended_by": "quit",
  "exit_code": 0,
  "cfg_written": true,
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "console_pending_before": 0,
  "console_drained": 0,
  "draft": ["maps/gridlee", "perform/two-coins", "start/gridlee"],
  "session": {"alive": false, "running": false, "altered": false}
}
```

</details>

**76. `image_compare`**: OK compare: 8975 pixels differ between the two frames

<details><summary>call and reply</summary>

```json
{
  "method": "image",
  "a": "./tmp/demos/tour/series/f000557.png",
  "b": "./tmp/demos/tour/series/f000581.png"
}
```

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
  "b": {"path": "./tmp/demos/tour/series/f000581.png", "sha256": "<volatile>"},
  "session": {
    "alive": false,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>

**77. `audio_compare`**: OK measure: one channel at 48000 Hz, silent True

<details><summary>call and reply</summary>

```json
{
  "method": "measure",
  "path": "./tmp/demos/tour/card.wav"
}
```

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
  "path": "./tmp/demos/tour/card.wav",
  "session": {
    "alive": false,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "call `status`"
  }
}
```

</details>
