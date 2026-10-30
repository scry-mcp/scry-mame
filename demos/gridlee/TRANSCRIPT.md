**1. `start`**: OK start: gridlee on MAME 0.289 (unknown), rom_check OK, pc 0x0000f000

<details><summary>call and reply</summary>

```json
{
  "system": "gridlee",
  "reference_rom": "./tmp/demos/gridlee/gridlee.ref",
  "reference_addr": "0xa000",
  "reference_base": "0xa000",
  "inipath": "./tmp/demos/gridlee/gridlee-ini",
  "state_dir": "./tmp/demos/gridlee/gridlee-states",
  "boot_seconds": 60,
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
  "state_dir": "./tmp/demos/gridlee/gridlee-states",
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "debugger": {
    "attached": "gdbstub",
    "note": "MAME runs with -debug under this stub. A capture taken at one of this session's stops can land a frame away from an autoboot golden taken by a frame notifier at the same count, in a scene that changes every frame: compare a live capture with a live golden"
  },
  "errorlog_path": "<volatile>",
  "stdout_path": "<volatile>",
  "rom_check": "OK",
  "symbols_total": 0,
  "symbols_format": "none",
  "symbols_by_class": {},
  "symbols_by_cpu": {},
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
    "persistent": false,
    "path": {
      "available": false,
      "why": "no `symbols` file was given, so nothing can be re-resolved by name: declarations are by address and die with this session"
    },
    "key": {
      "available": false,
      "why": "no `symbols` file was given, so nothing can be re-resolved by name: declarations are by address and die with this session"
    },
    "held": 0,
    "fingerprint": "97ce0328334c18e9",
    "rearm": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": [], "evaluated": []},
    "comments": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": []}
  },
  "recommended_release": "0.289",
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

**2. `run_for`**: OK attract: attract mode ran to frame 295, 6250000 cycles

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
  "instruction": {
    "address": "A631",
    "bytes": "04B4",
    "text": "LSR    <$B4",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["A633: 24 FC    BCC    $A631", "A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "A640: 7E F0 00 JMP    $F000", "A643: BD B5 2B JSR    $B52B", "A646: BD C5 67 JSR    $C567", "A649: B6 04 28 LDA    $0428", "A64C: 81 0C    CMPA   #$0C", "A64E: 24 51    BCC    $A6A1", "A650: B6 96 00 LDA    $9600"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 195},
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

**3. `scan`**: OK scan: 2048 candidate bytes in 0x0+0x800

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
  "summary": "scan start: 0x0, 2048 1-byte candidates on :maincpu",
  "status": "ok",
  "addr": "0x00000000",
  "length": 2048,
  "cell_bytes": 1,
  "hits_total": 2048,
  "cpu": ":maincpu",
  "space": "program",
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

**4. `perform`**: OK coin 1: coin 1: 22 bytes still hold 1

<details><summary>call and reply</summary>

```json
{
  "steps": [
    {"op": "input", "port": ":IN1", "field": "Coin 1", "frames": 4, "seconds": 300},
    {"op": "run_for", "milliseconds": 2000, "seconds": 300},
    {"op": "scan", "method": "filter", "operator": "=", "value": 1}
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
        "stop_seq": 3,
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
        "instruction": {
          "address": "FD80",
          "bytes": "0CB2",
          "text": "INC    <$B2",
          "symbol": {"available": false, "why": "no symbol table places this address"},
          "delta": {"available": false, "why": "no symbol table places this address"}
        },
        "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
        "errorlog": {
          "lines_total": 2,
          "truncated": false,
          "lines": ["[luaengine] MAME_MCP_INPUT#1 release frame=299 port_held=000000ce", ""],
          "mark": 315
        },
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
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
        "stop_seq": 4,
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
        "instruction": {
          "address": "A7D5",
          "bytes": "2406",
          "text": "BCC    $A7DD",
          "symbol": {"available": false, "why": "no symbol table places this address"},
          "delta": {"available": false, "why": "no symbol table places this address"}
        },
        "following": ["A7D7: EC A4    LDD    ,Y", "A7D9: AF A4    STX    ,Y", "A7DB: ED C4    STD    ,U", "A7DD: 33 A4    LEAU   ,Y", "A7DF: 31 3E    LEAY   -$2,Y", "A7E1: 11 93 80 CMPU   <$80", "A7E4: 26 E6    BNE    $A7CC", "A7E6: DE 84    LDU    <$84", "A7E8: 31 5E    LEAY   -$2,U", "A7EA: DC 80    LDD    <$80", "A7EC: C3 00 02 ADDD   #$0002", "A7EF: DD 80    STD    <$80", "A7F1: 11 93 80 CMPU   <$80", "A7F4: 26 D6    BNE    $A7CC"],
        "errorlog": {
          "lines_total": 9,
          "truncated": true,
          "lines": ["[:maincpu] ':maincpu' (FE4A): unmapped program memory read from 9020 & FF", "[:] coin counter off", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF"],
          "mark": 382,
          "how": "`log(pattern=\".\", channel=\"emulator\", since_mark=382, limit=9)` reads them all"
        },
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
    },
    {
      "op": "scan",
      "cpu": ":maincpu",
      "reply": {
        "summary": "scan filter: = 0x01, 22 survivors",
        "status": "ok",
        "operator": "=",
        "value": "0x01",
        "iterations": 1,
        "closed": false,
        "hits": [
          {"addr": "0x0000008c", "value": "0x01"},
          {"addr": "0x0000008d", "value": "0x01"},
          {"addr": "0x0000008e", "value": "0x01"},
          {"addr": "0x000000d9", "value": "0x01"},
          {"addr": "0x000000db", "value": "0x01"},
          {"addr": "0x000000dd", "value": "0x01"},
          {"addr": "0x000000df", "value": "0x01"},
          {"addr": "0x000000e1", "value": "0x01"},
          {"addr": "0x000000e3", "value": "0x01"},
          {"addr": "0x000000e5", "value": "0x01"},
          {"addr": "0x000000e7", "value": "0x01"},
          {"addr": "0x000000e9", "value": "0x01"},
          {"addr": "0x000000eb", "value": "0x01"},
          {"addr": "0x00000172", "value": "0x01"},
          {"addr": "0x00000278", "value": "0x01"},
          {"addr": "0x00000297", "value": "0x01"},
          {"addr": "0x00000298", "value": "0x01"},
          {"addr": "0x000002ff", "value": "0x01"},
          {"addr": "0x000003ee", "value": "0x01"},
          {"addr": "0x0000042b", "value": "0x01"},
          {"addr": "0x0000042c", "value": "0x01"},
          {"addr": "0x000007f6", "value": "0x01"}
        ],
        "hits_total": 22,
        "truncated": false,
        "cpu": ":maincpu",
        "space": "program",
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
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

**5. `perform`**: OK coin 2: coin 2: 3 bytes still hold 2

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
        "stop_seq": 5,
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
        "instruction": {
          "address": "FD80",
          "bytes": "0CB2",
          "text": "INC    <$B2",
          "symbol": {"available": false, "why": "no symbol table places this address"},
          "delta": {"available": false, "why": "no symbol table places this address"}
        },
        "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
        "errorlog": {
          "lines_total": 2,
          "truncated": false,
          "lines": ["[luaengine] MAME_MCP_INPUT#2 release frame=423 port_held=000000ce", ""],
          "mark": 1061
        },
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
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
        "stop_seq": 6,
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
          "symbol": {"available": false, "why": "no symbol table places this address"},
          "delta": {"available": false, "why": "no symbol table places this address"}
        },
        "following": ["B504: DC 86    LDD    <$86", "B506: 8E DA 62 LDX    #$DA62", "B509: 10 A3 81 CMPD   ,X++", "B50C: 23 07    BLS    $B515", "B50E: 0C 81    INC    <$81", "B510: 8C DA 6A CMPX   #$DA6A", "B513: 26 F4    BNE    $B509", "B515: 96 81    LDA    <$81", "B517: C6 05    LDB    #$05", "B519: 3D       MUL", "B51A: DB 80    ADDB   <$80", "B51C: D7 80    STB    <$80", "B51E: 86 07    LDA    #$07", "B520: 3D       MUL", "B521: D7 88    STB    <$88"],
        "errorlog": {
          "lines_total": 11,
          "truncated": true,
          "lines": ["[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF"],
          "mark": 1128,
          "how": "`log(pattern=\".\", channel=\"emulator\", since_mark=1128, limit=11)` reads them all"
        },
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
    },
    {
      "op": "scan",
      "cpu": ":maincpu",
      "reply": {
        "summary": "scan filter: = 0x02, 3 survivors",
        "status": "ok",
        "operator": "=",
        "value": "0x02",
        "iterations": 2,
        "closed": false,
        "hits": [
          {"addr": "0x000003ee", "value": "0x02"},
          {"addr": "0x0000042b", "value": "0x02"},
          {"addr": "0x0000042c", "value": "0x02"}
        ],
        "hits_total": 3,
        "truncated": false,
        "cpu": ":maincpu",
        "space": "program",
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
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

**6. `perform`**: OK coin 3: coin 3: three bytes hold 3, among them 0x42b and 0x42c

<details><summary>call and reply</summary>

```json
{
  "steps": [
    {"op": "input", "port": ":IN1", "field": "Coin 1", "frames": 4, "seconds": 300},
    {"op": "run_for", "milliseconds": 2000, "seconds": 300},
    {"op": "scan", "method": "filter", "operator": "=", "value": 3}
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
        "summary": "input :IN1 'Coin 1': held 4 frames, active True, released at frame 547",
        "status": "ok",
        "verdict": "ELAPSED",
        "frame_before": 543,
        "frame_after": 548,
        "emulated_before_s": 9.19144,
        "emulated_after_s": 9.275921,
        "cycles": 105601,
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
        "frame_set": 543,
        "released": true,
        "port_held": "0x000000ce",
        "frame_released": 547,
        "active": true,
        "cause": "the `gvblank` stop of the last frame asked",
        "stop_seq": 7,
        "pc": "0x0000fd80",
        "cpu": ":maincpu",
        "frame": 548,
        "regs": {
          "A": "0xff",
          "B": "0x6f",
          "D": "0xff6f",
          "X": "0x0100",
          "Y": "0x00f1",
          "U": "0xc66d",
          "PC": "0xfd80",
          "S": "0x07f4",
          "CC": "0xf4",
          "DP": "0x00"
        },
        "instruction": {
          "address": "FD80",
          "bytes": "0CB2",
          "text": "INC    <$B2",
          "symbol": {"available": false, "why": "no symbol table places this address"},
          "delta": {"available": false, "why": "no symbol table places this address"}
        },
        "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
        "errorlog": {
          "lines_total": 2,
          "truncated": false,
          "lines": ["[luaengine] MAME_MCP_INPUT#3 release frame=547 port_held=000000ce", ""],
          "mark": 1955
        },
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
    },
    {
      "op": "run_for",
      "cpu": ":maincpu",
      "reply": {
        "summary": "run_for 2000 ms: ELAPSED, frame 548 to 667",
        "status": "ok",
        "verdict": "ELAPSED",
        "frame_before": 548,
        "frame_after": 667,
        "emulated_before_s": 9.275921,
        "emulated_after_s": 11.275922,
        "cycles": 2500001,
        "reads": "<volatile>",
        "cause": "the console's `gtime` stop",
        "stop_seq": 8,
        "pc": "0x0000a7d5",
        "cpu": ":maincpu",
        "frame": 667,
        "regs": {
          "A": "0x00",
          "B": "0x00",
          "D": "0x0000",
          "X": "0x0136",
          "Y": "0x00df",
          "U": "0x00e1",
          "PC": "0xa7d5",
          "S": "0x07fe",
          "CC": "0xa4",
          "DP": "0x00"
        },
        "instruction": {
          "address": "A7D5",
          "bytes": "2406",
          "text": "BCC    $A7DD",
          "symbol": {"available": false, "why": "no symbol table places this address"},
          "delta": {"available": false, "why": "no symbol table places this address"}
        },
        "following": ["A7D7: EC A4    LDD    ,Y", "A7D9: AF A4    STX    ,Y", "A7DB: ED C4    STD    ,U", "A7DD: 33 A4    LEAU   ,Y", "A7DF: 31 3E    LEAY   -$2,Y", "A7E1: 11 93 80 CMPU   <$80", "A7E4: 26 E6    BNE    $A7CC", "A7E6: DE 84    LDU    <$84", "A7E8: 31 5E    LEAY   -$2,U", "A7EA: DC 80    LDD    <$80", "A7EC: C3 00 02 ADDD   #$0002", "A7EF: DD 80    STD    <$80", "A7F1: 11 93 80 CMPU   <$80", "A7F4: 26 D6    BNE    $A7CC"],
        "errorlog": {
          "lines_total": 9,
          "truncated": true,
          "lines": ["[:maincpu] ':maincpu' (FE4A): unmapped program memory read from 9020 & FF", "[:] coin counter off", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF"],
          "mark": 2022,
          "how": "`log(pattern=\".\", channel=\"emulator\", since_mark=2022, limit=9)` reads them all"
        },
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
    },
    {
      "op": "scan",
      "cpu": ":maincpu",
      "reply": {
        "summary": "scan filter: = 0x03, 3 survivors",
        "status": "ok",
        "operator": "=",
        "value": "0x03",
        "iterations": 3,
        "closed": false,
        "hits": [
          {"addr": "0x000003ee", "value": "0x03"},
          {"addr": "0x0000042b", "value": "0x03"},
          {"addr": "0x0000042c", "value": "0x03"}
        ],
        "hits_total": 3,
        "truncated": false,
        "cpu": ":maincpu",
        "space": "program",
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
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

**7. `perform`**: OK watch: change watches armed on 0x42b and 0x42c

<details><summary>call and reply</summary>

```json
{
  "steps": [
    {"op": "watch_add", "ref": "0x42b", "mode": "change", "fmt": "u8"},
    {"op": "watch_add", "ref": "0x42c", "mode": "change", "fmt": "u8"}
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
        "summary": "watch_add 0x42b: change watch armed at 0x0000042b, 1 byte",
        "status": "ok",
        "ref": "0x42b",
        "by": "address",
        "mode": "change",
        "length": 1,
        "fmt": "u8",
        "cpu": ":maincpu",
        "while_running": false,
        "addr": "0x0000042b",
        "reading": {"available": true, "value": 3, "raw_hex": "03"},
        "stored": true,
        "armed": true,
        "state": "armed",
        "index": 1,
        "entry": "1 @ 042B-042B write",
        "write_maps_to": "memory@0",
        "read_maps_to": "memory@0",
        "values_from": "memory",
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
    },
    {
      "op": "watch_add",
      "cpu": ":maincpu",
      "reply": {
        "summary": "watch_add 0x42c: change watch armed at 0x0000042c, 1 byte",
        "status": "ok",
        "ref": "0x42c",
        "by": "address",
        "mode": "change",
        "length": 1,
        "fmt": "u8",
        "cpu": ":maincpu",
        "while_running": false,
        "addr": "0x0000042c",
        "reading": {"available": true, "value": 3, "raw_hex": "03"},
        "stored": true,
        "armed": true,
        "state": "armed",
        "index": 2,
        "entry": "2 @ 042C-042C write",
        "write_maps_to": "memory@0",
        "read_maps_to": "memory@0",
        "values_from": "memory",
        "session": {
          "alive": true,
          "running": false,
          "altered": false,
          "omitted": ["altering_writes", "console"],
          "how": "call `status`"
        }
      }
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

**8. `input`**: OK coin 4: the fourth coin, held four frames and released

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
  "summary": "input :IN1 'Coin 1': held 4 frames, active True, released at frame 671",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 667,
  "frame_after": 672,
  "emulated_before_s": 11.286546,
  "emulated_after_s": 11.371026,
  "cycles": 105601,
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
  "frame_set": 667,
  "released": true,
  "port_held": "0x000000ce",
  "frame_released": 671,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 9,
  "pc": "0x0000fd80",
  "cpu": ":maincpu",
  "frame": 672,
  "regs": {
    "A": "0xfe",
    "B": "0xf3",
    "D": "0xfef3",
    "X": "0x0100",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xfd80",
    "S": "0x07f4",
    "CC": "0xf4",
    "DP": "0x00"
  },
  "instruction": {
    "address": "FD80",
    "bytes": "0CB2",
    "text": "INC    <$B2",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["FD82: 96 B2    LDA    <$B2", "FD84: 84 03    ANDA   #$03", "FD86: 26 04    BNE    $FD8C", "FD88: 0C B3    INC    <$B3", "FD8A: 0C B4    INC    <$B4", "FD8C: B6 03 BE LDA    $03BE", "FD8F: 26 28    BNE    $FDB9", "FD91: F6 95 01 LDB    $9501", "FD94: 1F 98    TFR    B,A", "FD96: D0 BD    SUBB   <$BD", "FD98: C4 0F    ANDB   #$0F", "FD9A: 85 10    BITA   #$10", "FD9C: 26 01    BNE    $FD9F", "FD9E: 50       NEGB", "FD9F: DB BF    ADDB   <$BF"],
  "errorlog": {
    "lines_total": 4,
    "truncated": false,
    "lines": ["[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF", "[luaengine] MAME_MCP_INPUT#4 release frame=671 port_held=000000ce", ""],
    "mark": 2701
  },
  "watches": [
    {
      "ref": "0x42b",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    },
    {
      "ref": "0x42c",
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

**9. `run_for`**: OK binary: the binary credits: Stopped at watchpoint 1 writing 04 to 042B (PC=B583)

<details><summary>call and reply</summary>

```json
{
  "milliseconds": 500,
  "seconds": 300
}
```

```json
{
  "summary": "run_for 500 ms: OTHER_STOP, frame 672 to 673",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 672,
  "frame_after": 673,
  "emulated_before_s": 11.371026,
  "emulated_after_s": 11.372898,
  "cycles": 2340,
  "reads": "<volatile>",
  "cause": "watch 0x42b: 0x0000042b written by pc 0x0000b583",
  "stop_seq": 10,
  "pc": "0x0000b586",
  "cpu": ":maincpu",
  "frame": 673,
  "regs": {
    "A": "0x01",
    "B": "0xcf",
    "D": "0x01cf",
    "X": "0xf609",
    "Y": "0xf2e6",
    "U": "0x7afa",
    "PC": "0xb586",
    "S": "0x07fc",
    "CC": "0xa0",
    "DP": "0x00"
  },
  "instruction": {
    "address": "B586",
    "bytes": "8601",
    "text": "LDA    #$01",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["B588: BB 04 2C ADDA   $042C", "B58B: 19       DAA", "B58C: B7 04 2C STA    $042C", "B58F: 39       RTS", "B590: 96 F4    LDA    <$F4", "B592: 27 21    BEQ    $B5B5", "B594: 96 B3    LDA    <$B3", "B596: 84 07    ANDA   #$07", "B598: 26 1A    BNE    $B5B4", "B59A: 8E F6 59 LDX    #$F659", "B59D: 96 F5    LDA    <$F5", "B59F: 27 03    BEQ    $B5A4", "B5A1: 8E F7 49 LDX    #$F749", "B5A4: CE 0A 85 LDU    #$0A85"],
  "errorlog": {"lines_total": 1, "truncated": false, "lines": ["[:] coin counter on"], "mark": 2916},
  "watches": [
    {
      "ref": "0x42b",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 4, "raw_hex": "04"}
    },
    {
      "ref": "0x42c",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "watch_hit": {
    "ref": "0x42b",
    "addr": "0x0000042b",
    "cpu": ":maincpu",
    "index": 1,
    "writes_total": 1,
    "truncated": false,
    "writer_pc": "0x0000b583",
    "writes": [
      {"wrote": "0x04", "to": "0x0000042b", "pc": "0x0000b583"}
    ],
    "values_from": "memory",
    "before": 3,
    "after": 4,
    "lines": ["Stopped at watchpoint 1 writing 04 to 042B (PC=B583)"]
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

**10. `run_for`**: OK bcd: the BCD credits: Stopped at watchpoint 2 writing 04 to 042C (PC=B58C)

<details><summary>call and reply</summary>

```json
{
  "milliseconds": 500,
  "seconds": 300
}
```

```json
{
  "summary": "run_for 500 ms: OTHER_STOP, frame 673 to 673",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 673,
  "frame_after": 673,
  "emulated_before_s": 11.372898,
  "emulated_after_s": 11.37291,
  "cycles": 14,
  "reads": "<volatile>",
  "cause": "watch 0x42c: 0x0000042c written by pc 0x0000b58c",
  "stop_seq": 11,
  "pc": "0x0000b58f",
  "cpu": ":maincpu",
  "frame": 673,
  "regs": {
    "A": "0x04",
    "B": "0xcf",
    "D": "0x04cf",
    "X": "0xf609",
    "Y": "0xf2e6",
    "U": "0x7afa",
    "PC": "0xb58f",
    "S": "0x07fc",
    "CC": "0x80",
    "DP": "0x00"
  },
  "instruction": {
    "address": "B58F",
    "bytes": "39",
    "text": "RTS",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["B590: 96 F4    LDA    <$F4", "B592: 27 21    BEQ    $B5B5", "B594: 96 B3    LDA    <$B3", "B596: 84 07    ANDA   #$07", "B598: 26 1A    BNE    $B5B4", "B59A: 8E F6 59 LDX    #$F659", "B59D: 96 F5    LDA    <$F5", "B59F: 27 03    BEQ    $B5A4", "B5A1: 8E F7 49 LDX    #$F749", "B5A4: CE 0A 85 LDU    #$0A85", "B5A7: B6 04 32 LDA    $0432", "B5AA: 27 03    BEQ    $B5AF", "B5AC: CE 0A C3 LDU    #$0AC3"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 2936},
  "watches": [
    {
      "ref": "0x42b",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 4, "raw_hex": "04"}
    },
    {
      "ref": "0x42c",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 4, "raw_hex": "04"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "watch_hit": {
    "ref": "0x42c",
    "addr": "0x0000042c",
    "cpu": ":maincpu",
    "index": 2,
    "writes_total": 1,
    "truncated": false,
    "writer_pc": "0x0000b58c",
    "writes": [
      {"wrote": "0x04", "to": "0x0000042c", "pc": "0x0000b58c"}
    ],
    "values_from": "memory",
    "before": 3,
    "after": 4,
    "lines": ["Stopped at watchpoint 2 writing 04 to 042C (PC=B58C)"]
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

**11. `disassemble`**: OK writer: the coin routine: INC $042B, then ADDA $042C, DAA, STA $042C

<details><summary>call and reply</summary>

```json
{
  "ref": "0xb583",
  "length": 12
}
```

```json
{
  "summary": "disassemble 0xb583: 5 lines at 0x0000b583",
  "status": "ok",
  "addr": "0x0000b583",
  "length": 12,
  "lines": ["B583: 7C 04 2B INC    $042B", "B586: 86 01    LDA    #$01", "B588: BB 04 2C ADDA   $042C", "B58B: 19       DAA", "B58C: B7 04 2C STA    $042C"],
  "cpu": ":maincpu",
  "flow": ["unknown", "unknown", "unknown", "unknown", "unknown"],
  "flow_source": "none",
  "note": "no mnemonic table for cpu type 'm6809' (tables: m68000, v30), so no line is classified",
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

**12. `run_for`**: OK settle: ran on to frame 702 with no other write

<details><summary>call and reply</summary>

```json
{
  "milliseconds": 500,
  "seconds": 300
}
```

```json
{
  "summary": "run_for 500 ms: ELAPSED, frame 673 to 702",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 673,
  "frame_after": 702,
  "emulated_before_s": 11.37291,
  "emulated_after_s": 11.872913,
  "cycles": 625004,
  "reads": "<volatile>",
  "cause": "the console's `gtime` stop",
  "stop_seq": 12,
  "pc": "0x0000ae19",
  "cpu": ":maincpu",
  "frame": 702,
  "regs": {
    "A": "0x01",
    "B": "0xd5",
    "D": "0x01d5",
    "X": "0x014e",
    "Y": "0xf2e6",
    "U": "0xab79",
    "PC": "0xae19",
    "S": "0x07fe",
    "CC": "0xe4",
    "DP": "0x00"
  },
  "instruction": {
    "address": "AE19",
    "bytes": "7F02DF",
    "text": "CLR    $02DF",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["AE1C: A6 0A       LDA    $A,X", "AE1E: 85 01       BITA   #$01", "AE20: 10 27 00 B0 LBEQ   $AED4", "AE24: 85 40       BITA   #$40", "AE26: 27 06       BEQ    $AE2E", "AE28: BD B8 34    JSR    $B834", "AE2B: 7E AE D4    JMP    $AED4", "AE2E: 85 80       BITA   #$80", "AE30: 10 26 00 82 LBNE   $AEB6", "AE34: 85 20       BITA   #$20", "AE36: 10 26 00 AA LBNE   $AEE4"],
  "errorlog": {
    "lines_total": 4,
    "truncated": false,
    "lines": ["[:maincpu] ':maincpu' (FE4A): unmapped program memory read from 9020 & FF", "[:] coin counter off", "[:maincpu] ':maincpu' (A685): unmapped program memory read from 9010 & FF", "[:maincpu] ':maincpu' (A688): unmapped program memory read from 9000 & FF"],
    "mark": 2936
  },
  "watches": [
    {
      "ref": "0x42b",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 4, "raw_hex": "04"}
    },
    {
      "ref": "0x42c",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 4, "raw_hex": "04"}
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

**13. `read_memory`**: OK both: credits 4 in binary, 04 in BCD

<details><summary>call and reply</summary>

```json
{
  "ref": "0x42b",
  "length": 2
}
```

```json
{
  "summary": "read_memory 0x42b: 2 bytes at 0x0000042b: 0404",
  "status": "ok",
  "addr": "0x0000042b",
  "length": 2,
  "hex": "0404",
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

**14. `state_write`**: OK save: state four_credits saved at frame 702

<details><summary>call and reply</summary>

```json
{
  "method": "save",
  "name": "four_credits"
}
```

```json
{
  "summary": "state_write save: four_credits, 10845 bytes at frame 702",
  "status": "ok",
  "name": "four_credits",
  "path": "./tmp/demos/gridlee/gridlee-states/sta/gridlee/four_credits.sta",
  "bytes": 10845,
  "frame": 702,
  "pc": "0x0000ae19",
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 3179},
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

**15. `input`**: OK press start: START stopped on the binary: Stopped at watchpoint 1 writing 03 to 042B (PC=D676)

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
  "summary": "input :IN1 '1 Player Start': still HELD from frame 702, releases at 706",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 702,
  "frame_after": 703,
  "emulated_before_s": 11.877906,
  "emulated_after_s": 11.882058,
  "cycles": 5189,
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
  "frame_set": 702,
  "released": false,
  "active": {
    "available": false,
    "why": "the field is still HELD: the port is read at its release, which the run has not reached"
  },
  "port_held": {
    "available": false,
    "why": "the field is still HELD: the port is read at its release, which the run has not reached"
  },
  "frame_release_planned": 706,
  "note": "the field is still HELD: the run stopped before the release frame, and the script releases it when the machine reaches it",
  "cause": "watch 0x42b: 0x0000042b written by pc 0x0000d676",
  "stop_seq": 13,
  "pc": "0x0000d679",
  "cpu": ":maincpu",
  "frame": 703,
  "regs": {
    "A": "0xcb",
    "B": "0xff",
    "D": "0xcbff",
    "X": "0x0431",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xd679",
    "S": "0x07fc",
    "CC": "0xa0",
    "DP": "0x00"
  },
  "instruction": {
    "address": "D679",
    "bytes": "8699",
    "text": "LDA    #$99",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["D67B: BB 04 2C ADDA   $042C", "D67E: 19       DAA", "D67F: B7 04 2C STA    $042C", "D682: 39       RTS", "D683: 8E 04 31 LDX    #$0431", "D686: C6 5F    LDB    #$5F", "D688: 6F 85    CLR    B,X", "D68A: 5A       DECB", "D68B: 2A FB    BPL    $D688", "D68D: 39       RTS", "D68E: 0F B9    CLR    <$B9", "D690: D6 9A    LDB    <$9A", "D692: 86 03    LDA    #$03", "D694: 3D       MUL", "D695: 8E AB 76 LDX    #$AB76", "D698: 3A       ABX"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 3307},
  "watches": [
    {
      "ref": "0x42b",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    },
    {
      "ref": "0x42c",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 4, "raw_hex": "04"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "watch_hit": {
    "ref": "0x42b",
    "addr": "0x0000042b",
    "cpu": ":maincpu",
    "index": 1,
    "writes_total": 1,
    "truncated": false,
    "writer_pc": "0x0000d676",
    "writes": [
      {"wrote": "0x03", "to": "0x0000042b", "pc": "0x0000d676"}
    ],
    "values_from": "memory",
    "before": 4,
    "after": 3,
    "lines": ["Stopped at watchpoint 1 writing 03 to 042B (PC=D676)"]
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

**16. `run_for`**: OK start bcd: then on the BCD credits: Stopped at watchpoint 2 writing 03 to 042C (PC=D67F)

<details><summary>call and reply</summary>

```json
{
  "frames": 1,
  "seconds": 300
}
```

```json
{
  "summary": "run_for 1 frame: OTHER_STOP, frame 703 to 703",
  "status": "ok",
  "verdict": "OTHER_STOP",
  "frame_before": 703,
  "frame_after": 703,
  "emulated_before_s": 11.882069,
  "emulated_after_s": 11.882069,
  "cycles": 0,
  "polls": 1,
  "cause": "watch 0x42c: 0x0000042c written by pc 0x0000d67f",
  "stop_seq": 14,
  "pc": "0x0000d682",
  "cpu": ":maincpu",
  "frame": 703,
  "regs": {
    "A": "0x03",
    "B": "0xff",
    "D": "0x03ff",
    "X": "0x0431",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xd682",
    "S": "0x07fc",
    "CC": "0x81",
    "DP": "0x00"
  },
  "instruction": {
    "address": "D682",
    "bytes": "39",
    "text": "RTS",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["D683: 8E 04 31    LDX    #$0431", "D686: C6 5F       LDB    #$5F", "D688: 6F 85       CLR    B,X", "D68A: 5A          DECB", "D68B: 2A FB       BPL    $D688", "D68D: 39          RTS", "D68E: 0F B9       CLR    <$B9", "D690: D6 9A       LDB    <$9A", "D692: 86 03       LDA    #$03", "D694: 3D          MUL", "D695: 8E AB 76    LDX    #$AB76", "D698: 3A          ABX", "D699: A6 80       LDA    ,X+", "D69B: B7 01 BC    STA    $01BC", "D69E: EC 84       LDD    ,X", "D6A0: 10 83 10 10 CMPD   #$1010"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 3307},
  "watches": [
    {
      "ref": "0x42b",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    },
    {
      "ref": "0x42c",
      "cpu": ":maincpu",
      "state": "armed",
      "reading": {"available": true, "value": 3, "raw_hex": "03"}
    }
  ],
  "omitted": ["addr", "by", "entry", "fmt", "length", "mode"],
  "how": "`declaration_list(kind=\"watch\")` answers each watch whole: its declaration, the debugger's row for it, and a count's or a capture's tables",
  "watch_hit": {
    "ref": "0x42c",
    "addr": "0x0000042c",
    "cpu": ":maincpu",
    "index": 2,
    "writes_total": 1,
    "truncated": false,
    "writer_pc": "0x0000d67f",
    "writes": [
      {"wrote": "0x03", "to": "0x0000042c", "pc": "0x0000d67f"}
    ],
    "values_from": "memory",
    "before": 4,
    "after": 3,
    "lines": ["Stopped at watchpoint 2 writing 03 to 042C (PC=D67F)"]
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

**17. `history`**: OK trail: the trail: DEC $042B, then LDA #$99, ADDA $042C, DAA, STA $042C

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
  "lines": ["D68D: RTS", "C5AD: JSR    $D676", "D676: DEC    $042B", "D679: LDA    #$99", "D67B: ADDA   $042C", "D67E: DAA", "D67F: STA    $042C", "D682: RTS"],
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

**18. `registers`**: OK registers: the stop landed at PC 0xd682, A 0x03

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
    "B": "0xff",
    "D": "0x03ff",
    "X": "0x0431",
    "Y": "0x00f1",
    "U": "0xc66d",
    "PC": "0xd682",
    "S": "0x07fc",
    "CC": "0x81",
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

**19. `declaration_clear`**: OK unwatch: both watches cleared

<details><summary>call and reply</summary>

```json
{
  "kind": "watch",
  "all": true
}
```

```json
{
  "summary": "declaration_clear watch all: 2 cleared, 2 disarmed",
  "status": "ok",
  "declarations_cleared": 2,
  "disarmed": ["1 @ 042B-042B write", "2 @ 042C-042C write"],
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

**20. `run_for`**: OK play: the game plays on: ran to frame 1176, 10000004 cycles

<details><summary>call and reply</summary>

```json
{
  "milliseconds": 8000,
  "seconds": 300
}
```

```json
{
  "summary": "run_for 8000 ms: ELAPSED, frame 703 to 1176",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 703,
  "frame_after": 1176,
  "emulated_before_s": 11.882069,
  "emulated_after_s": 19.882072,
  "cycles": 10000004,
  "reads": "<volatile>",
  "cause": "the console's `gtime` stop",
  "stop_seq": 15,
  "pc": "0x0000a633",
  "cpu": ":maincpu",
  "frame": 1176,
  "regs": {
    "A": "0x00",
    "B": "0x00",
    "D": "0x0000",
    "X": "0x0204",
    "Y": "0x00f1",
    "U": "0x0238",
    "PC": "0xa633",
    "S": "0x0800",
    "CC": "0xe4",
    "DP": "0x00"
  },
  "instruction": {
    "address": "A633",
    "bytes": "24FC",
    "text": "BCC    $A631",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "A640: 7E F0 00 JMP    $F000", "A643: BD B5 2B JSR    $B52B", "A646: BD C5 67 JSR    $C567", "A649: B6 04 28 LDA    $0428", "A64C: 81 0C    CMPA   #$0C", "A64E: 24 51    BCC    $A6A1", "A650: B6 96 00 LDA    $9600"],
  "errorlog": {
    "lines_total": 130,
    "truncated": true,
    "lines": ["[:maincpu] ':maincpu' (CF61): unmapped program memory write to 8078 = FF & FF", "[:maincpu] ':maincpu' (CF61): unmapped program memory write to 8079 = FF & FF", "[:maincpu] ':maincpu' (CF61): unmapped program memory write to 807A = FF & FF", "[:maincpu] ':maincpu' (CF61): unmapped program memory write to 807B = FF & FF", "[:maincpu] ':maincpu' (CF61): unmapped program memory write to 807C = FF & FF", "[:maincpu] ':maincpu' (CF61): unmapped program memory write to 807D = FF & FF", "[:maincpu] ':maincpu' (CF61): unmapped program memory write to 807E = FF & FF", "[:maincpu] ':maincpu' (CF61): unmapped program memory write to 807F = FF & FF"],
    "mark": 3307,
    "how": "`log(pattern=\".\", channel=\"emulator\", since_mark=3307, limit=130)` reads them all"
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

**21. `read_memory`**: OK after start: credits 3 in binary, 03 in BCD

<details><summary>call and reply</summary>

```json
{
  "ref": "0x42b",
  "length": 2
}
```

```json
{
  "summary": "read_memory 0x42b: 2 bytes at 0x0000042b: 0303",
  "status": "ok",
  "addr": "0x0000042b",
  "length": 2,
  "hex": "0303",
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

**22. `screen_view`**: OK screen: the game in play, 256x240, sha256 0c1f099a0cae

<details><summary>call and reply</summary>

```json
{
  "mode": "render",
  "dest": "./tmp/demos/gridlee/screen.png",
  "scale": 2
}
```

```json
{
  "summary": "screen_view render :screen frame 1176 from indices; 512x480 PNG x2, inline",
  "status": "ok",
  "mode": "render",
  "screen": ":screen",
  "width": 256,
  "height": 240,
  "frame_screen": 1176,
  "palette": ":palette",
  "entries": 2048,
  "screen_indexed": true,
  "crop": [0, 0, 256, 240],
  "image": {
    "path": "./tmp/demos/gridlee/screen.png",
    "bytes": 8175,
    "sha256": "0c1f099a0caeb830ec9022c58ed2317731cd7d197dedfb07d572148eb1b434ce",
    "width": 512,
    "height": 480,
    "scale": 2,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#6",
  "pc_before": "0x0000a633",
  "cause": "screen_view: one step",
  "stop_seq": 16,
  "pc": "0x0000a631",
  "cpu": ":maincpu",
  "frame": 1176,
  "regs": {
    "A": "0x00",
    "B": "0x00",
    "D": "0x0000",
    "X": "0x0204",
    "Y": "0x00f1",
    "U": "0x0238",
    "PC": "0xa631",
    "S": "0x0800",
    "CC": "0xe4",
    "DP": "0x00"
  },
  "instruction": {
    "address": "A631",
    "bytes": "04B4",
    "text": "LSR    <$B4",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["A633: 24 FC    BCC    $A631", "A635: B7 93 80 STA    $9380", "A638: B6 97 00 LDA    $9700", "A63B: 43       COMA", "A63C: 85 20    BITA   #$20", "A63E: 27 03    BEQ    $A643", "A640: 7E F0 00 JMP    $F000", "A643: BD B5 2B JSR    $B52B", "A646: BD C5 67 JSR    $C567", "A649: B6 04 28 LDA    $0428", "A64C: 81 0C    CMPA   #$0C", "A64E: 24 51    BCC    $A6A1", "A650: B6 96 00 LDA    $9600"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 13358},
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

**23. `state_write`**: OK load: state four_credits loaded and verified, frame 702

<details><summary>call and reply</summary>

```json
{
  "method": "load",
  "name": "four_credits"
}
```

```json
{
  "summary": "state_write load: four_credits, rom_check OK, verified True, frame 702, pc 0x0000ae19",
  "status": "ok",
  "name": "four_credits",
  "path": "./tmp/demos/gridlee/gridlee-states/sta/gridlee/four_credits.sta",
  "rom_check": "OK",
  "verified": true,
  "saved": {"frame": 702, "pc": "0x0000ae19"},
  "output": "State load attempted.  Please refer to window message popup for results.",
  "mark": {"emulator": 13358, "process": 10434},
  "cause": "stateload four_credits",
  "stop_seq": 17,
  "pc": "0x0000ae19",
  "cpu": ":maincpu",
  "frame": 702,
  "regs": {
    "A": "0x01",
    "B": "0xd5",
    "D": "0x01d5",
    "X": "0x014e",
    "Y": "0xf2e6",
    "U": "0xab79",
    "PC": "0xae19",
    "S": "0x07fe",
    "CC": "0xe4",
    "DP": "0x00"
  },
  "instruction": {
    "address": "AE19",
    "bytes": "7F02DF",
    "text": "CLR    $02DF",
    "symbol": {"available": false, "why": "no symbol table places this address"},
    "delta": {"available": false, "why": "no symbol table places this address"}
  },
  "following": ["AE1C: A6 0A       LDA    $A,X", "AE1E: 85 01       BITA   #$01", "AE20: 10 27 00 B0 LBEQ   $AED4", "AE24: 85 40       BITA   #$40", "AE26: 27 06       BEQ    $AE2E", "AE28: BD B8 34    JSR    $B834", "AE2B: 7E AE D4    JMP    $AED4", "AE2E: 85 80       BITA   #$80", "AE30: 10 26 00 82 LBNE   $AEB6", "AE34: 85 20       BITA   #$20", "AE36: 10 26 00 AA LBNE   $AEE4"],
  "errorlog": {"lines_total": 0, "truncated": false, "lines": [], "mark": 13358},
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

**24. `read_memory`**: OK back: credits 4 in binary, 04 in BCD

<details><summary>call and reply</summary>

```json
{
  "ref": "0x42b",
  "length": 2
}
```

```json
{
  "summary": "read_memory 0x42b: 2 bytes at 0x0000042b: 0404",
  "status": "ok",
  "addr": "0x0000042b",
  "length": 2,
  "hex": "0404",
  "cpu": ":maincpu",
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

**25. `close`**: OK close: closed: MAME quit on its own

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
  "session": {"alive": false, "running": false, "altered": false}
}
```

</details>
