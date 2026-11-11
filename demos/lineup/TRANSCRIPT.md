**1. `start`**: OK start: lineup on MAME, rom_check OK, 306 symbols

<details><summary>call and reply</summary>

```json
{
  "system": "lineup",
  "reference_rom": "./tmp/demos/lineup/lineup.ref",
  "reference_addr": "0x30000",
  "reference_base": "0x0",
  "symbols": "./tmp/demos/lineup/lineup.map",
  "bases": {"DATA": "0x400", "LUP_JUKEBOX": "rom"},
  "inipath": "./tmp/demos/lineup/lineup-ini",
  "state_dir": "./tmp/demos/lineup/lineup-states",
  "shared": true,
  "boot_seconds": 60,
  "rompath": "<host>"
}
```

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "system": "lineup",
  "binary": "<volatile>",
  "binary_origin": "<volatile>",
  "version": "0.289 (unknown)",
  "pid": "<volatile>",
  "stub_port": "<volatile>",
  "scratch_dir": "<volatile>",
  "state_dir": "./tmp/demos/lineup/lineup-states",
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "debugger": {
    "attached": "gdbstub",
    "note": "MAME runs with -debug under this stub. A capture taken at one of this session's stops can land a frame away from an autoboot golden taken by a frame notifier at the same count, in a scene that changes every frame: compare a live capture with a live golden"
  },
  "errorlog_path": "<volatile>",
  "stdout_path": "<volatile>",
  "rom_check": "OK",
  "symbols_total": 306,
  "symbols_format": "tsv",
  "symbols_by_class": {"DATA": 44, "CODE": 201, "LUP_JUKEBOX": 61},
  "symbols_by_cpu": {":maincpu": 306},
  "registers": ["EAX", "ECX", "EDX", "EBX", "ESP", "EBP", "ESI", "EDI", "EIP", "EFLAGS", "CS", "SS", "DS", "ES", "FS", "GS", "ST0", "ST1", "ST2", "ST3", "ST4", "ST5", "ST6", "ST7", "FCTRL", "FSTAT", "FTAG", "FISEG", "FIOFF", "FOSEG", "FOOFF", "FOP"],
  "pc": "0x000ffff0",
  "frame": 0,
  "frame_symbol": "frame",
  "view": "native",
  "views": ["Screen 0 Standard (4:3)", "Screen 0 Pixel Aspect (8:5)", "Cocktail"],
  "background": false,
  "flags": "<volatile>",
  "boot_lua_path": "<volatile>",
  "presence": true,
  "machine": {"cpus": 1, "spaces": 2, "address_map": 7, "regions": 2, "shares": 0, "screens": 1, "rom_files": 3},
  "declarations": {
    "persistent": true,
    "path": "./tmp/demos/lineup/lineup-states/declarations.json",
    "key": "lineup ./tmp/demos/lineup/lineup.map",
    "held": 0,
    "fingerprint": "8670fcf45164056f",
    "rearm": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": [], "evaluated": []},
    "comments": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": []}
  },
  "recommended_release": "0.289",
  "window": "<volatile>",
  "kept": "kept 1 (promote to review)",
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

**2. `screen_map_write`**: OK map: 4 screens and 10 controls loaded

<details><summary>call and reply</summary>

```json
{
  "method": "load",
  "path": "./tmp/demos/lineup/lineup-screen-map.json"
}
```

```json
{
  "summary": "screen_map_write load: 4 screens, 10 controls of lineup",
  "status": "ok",
  "path": "./tmp/demos/lineup/lineup-screen-map.json",
  "application": "lineup",
  "mode": "verified",
  "screens": 4,
  "controls": 10,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**3. `run_to`**: OK to the high scores: stopped at Draw_High_Scores_Screen

<details><summary>call and reply</summary>

```json
{
  "ref": "Draw_High_Scores_Screen",
  "control": "Check_Money25",
  "seconds": 120
}
```

```json
{
  "summary": "run_to Draw_High_Scores_Screen: TARGET, control counted 250",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 250,
  "controls": [
    {"ref": "Check_Money25", "cpu": ":maincpu", "hits_in_run": 250}
  ],
  "cause": "target Draw_High_Scores_Screen",
  "stop_seq": 2,
  "pc": "0x000317ff",
  "cpu": ":maincpu",
  "frame": 251,
  "regs": {
    "EAX": "0x0500",
    "ECX": "0x0000",
    "EDX": "0x73ca",
    "EBX": "0x0000",
    "ESP": "0x99db",
    "EBP": "0xbe31",
    "ESI": "0x6992",
    "EDI": "0xfb28",
    "EIP": "0x000317ff",
    "EFLAGS": "0xf006",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {
    "address": "317FF",
    "bytes": "1E",
    "text": "push    ds0",
    "symbol": "Draw_High_Scores_Screen",
    "delta": 0
  },
  "following": ["31800: E8 21 FE call    31624h", "31803: B8 01 00 mov     aw,1h", "31806: E8 29 73 call    38B32h", "31809: E8 50 36 call    34E5Ch", "3180C: E8 8F FF call    3179Eh", "3180F: 1F       pop     ds0", "31810: C3       ret     ", "31811: 1E       push    ds0", "31812: E8 0F FE call    31624h", "31815: B8 00 00 mov     aw,0h", "31818: E8 17 73 call    38B32h", "3181B: E8 80 FF call    3179Eh", "3181E: 1F       pop     ds0"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**4. `breakpoint_at`**: OK drawn: tick: a stop on Check_Money100

<details><summary>call and reply</summary>

```json
{
  "ref": "Check_Money100"
}
```

```json
{
  "summary": "breakpoint_at Check_Money100: armed at 0x00031457",
  "status": "ok",
  "ref": "Check_Money100",
  "by": "symbol",
  "role": "stop",
  "cpu": ":maincpu",
  "stored": true,
  "while_running": false,
  "addr": "0x00031457",
  "armed": true,
  "state": "armed",
  "entry": "3 @ 31457",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**5. `screen_wait`**: OK drawn: the table drawn

<details><summary>call and reply</summary>

```json
{
  "screen": "hiscores",
  "on_breakpoint": "Check_Money100",
  "seconds": 120
}
```

```json
{
  "summary": "screen_wait screen 'hiscores': found after 9 firings of breakpoint 'Check_Money100'",
  "status": "ok",
  "verdict": "TARGET",
  "predicate": "screen",
  "already": false,
  "waited_s": "<volatile>",
  "waited_on": {"kind": "breakpoint", "ref": "Check_Money100"},
  "firings": 9,
  "frames_examined": 18,
  "fired_line": 212,
  "emulated_before_s": 5.033893,
  "emulated_after_s": 5.233217,
  "frame_before": 251,
  "frame_after": 261,
  "cycles": 1594590,
  "screen": {"name": "hiscores", "layer": "file"},
  "cause": "stopped at no breakpoint this server armed",
  "stop_seq": 5,
  "pc": "0x0003145a",
  "cpu": ":maincpu",
  "frame": 261,
  "regs": {
    "EAX": "0x0040",
    "ECX": "0x0000",
    "EDX": "0x0002",
    "EBX": "0xbe0b",
    "ESP": "0x99a7",
    "EBP": "0xbe31",
    "ESI": "0x87ac",
    "EDI": "0xbf99",
    "EIP": "0x0003145a",
    "EFLAGS": "0xf046",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {
    "address": "3145A",
    "bytes": "8ED8",
    "text": "mov     ds0,aw",
    "symbol": "Check_Money100",
    "delta": 3
  },
  "following": ["3145C: B8 00 10          mov     aw,1000h", "3145F: 8E C0             mov     ds1,aw", "31461: 83 3E 4E 8D 00    cmp     word ptr [8D4Eh],0h", "31466: 74 09             be      31471h", "31468: F7 06 A0 82 01 00 test    word ptr [82A0h],1h", "3146E: 74 10             be      31480h", "31470: C3                ret     ", "31471: F7 06 A0 82 01 00 test    word ptr [82A0h],1h", "31477: 74 18             be      31491h", "31479: C7 06 4E 8D 01 00 mov     word ptr [8D4Eh],1h"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**6. `declaration_clear`**: OK drawn: untick: the tick's stop cleared

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
  "disarmed": ["1 @ 3140C if (++temp0)==0", "3 @ 31457"],
  "while_running": false,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**7. `screen_map_find`**: OK is hiscores: the hiscores screen, its controls table, credits

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "screen_map_find: hiscores (file), 2 controls",
  "status": "ok",
  "matched": true,
  "screen": "hiscores",
  "layer": "file",
  "kind": "pixel",
  "size": [320, 200],
  "controls": [
    {"name": "table", "rect": [64, 30, 192, 145], "centre": [160, 102]},
    {"name": "credits", "rect": [230, 186, 76, 12], "centre": [268, 192]}
  ],
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#4",
  "pc_before": "0x0003145a",
  "cause": "screen_map_find: one step",
  "stop_seq": 6,
  "pc": "0x0003145c",
  "cpu": ":maincpu",
  "frame": 261,
  "regs": {
    "EAX": "0x0040",
    "ECX": "0x0000",
    "EDX": "0x0002",
    "EBX": "0xbe0b",
    "ESP": "0x99a7",
    "EBP": "0xbe31",
    "ESI": "0x87ac",
    "EDI": "0xbf99",
    "EIP": "0x0003145c",
    "EFLAGS": "0xf046",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {
    "address": "3145C",
    "bytes": "B80010",
    "text": "mov     aw,1000h",
    "symbol": "Check_Money100",
    "delta": 5
  },
  "following": ["3145F: 8E C0             mov     ds1,aw", "31461: 83 3E 4E 8D 00    cmp     word ptr [8D4Eh],0h", "31466: 74 09             be      31471h", "31468: F7 06 A0 82 01 00 test    word ptr [82A0h],1h", "3146E: 74 10             be      31480h", "31470: C3                ret     ", "31471: F7 06 A0 82 01 00 test    word ptr [82A0h],1h", "31477: 74 18             be      31491h", "31479: C7 06 4E 8D 01 00 mov     word ptr [8D4Eh],1h"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**8. `read_memory`**: OK no credits: Credits holds 0

<details><summary>call and reply</summary>

```json
{
  "ref": "Credits",
  "length": 2
}
```

```json
{
  "summary": "read_memory Credits: 2 bytes at 0x0000914a: 0000",
  "status": "ok",
  "addr": "0x0000914a",
  "length": 2,
  "hex": "0000",
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**9. `input`**: OK press coin: COIN pressed

<details><summary>call and reply</summary>

```json
{
  "port": ":P1",
  "field": "Coin 1",
  "frames": 4
}
```

```json
{
  "summary": "input :P1 'Coin 1': held 4 frames, active True, released at frame 265",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 261,
  "frame_after": 266,
  "emulated_before_s": 5.233218,
  "emulated_after_s": 5.331457,
  "cycles": 785919,
  "polls": 5,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":P1",
  "field": "Coin 1",
  "value": "0x00000001",
  "frames": 4,
  "name": "Coin 1",
  "player": 0,
  "mask": "0x00000001",
  "defvalue": "0x00000001",
  "port_before": "0x000000ff",
  "frame_set": 261,
  "released": true,
  "port_held": "0x000000fe",
  "frame_released": 265,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 7,
  "pc": "0x000300a9",
  "cpu": ":maincpu",
  "frame": 266,
  "regs": {
    "EAX": "0x7000",
    "ECX": "0x0000",
    "EDX": "0x73ca",
    "EBX": "0x05ba",
    "ESP": "0x99d3",
    "EBP": "0xbe31",
    "ESI": "0x8db6",
    "EDI": "0x89db",
    "EIP": "0x000300a9",
    "EFLAGS": "0xf046",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300A9", "bytes": "55", "text": "push    bp", "symbol": "New_IRQ_Video", "delta": 0},
  "following": ["300AA: 50             push    aw", "300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**10. `breakpoint_at`**: OK counted: tick: a stop on Check_Money100

<details><summary>call and reply</summary>

```json
{
  "ref": "Check_Money100"
}
```

```json
{
  "summary": "breakpoint_at Check_Money100: armed at 0x00031457",
  "status": "ok",
  "ref": "Check_Money100",
  "by": "symbol",
  "role": "stop",
  "cpu": ":maincpu",
  "stored": true,
  "while_running": false,
  "addr": "0x00031457",
  "armed": true,
  "state": "armed",
  "entry": "4 @ 31457",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**11. `screen_wait`**: OK counted: the coin counted

<details><summary>call and reply</summary>

```json
{
  "screen": "insert",
  "on_breakpoint": "Check_Money100",
  "seconds": 120
}
```

```json
{
  "summary": "screen_wait screen 'insert': found after 1 firing of breakpoint 'Check_Money100'",
  "status": "ok",
  "verdict": "TARGET",
  "predicate": "screen",
  "already": false,
  "waited_s": "<volatile>",
  "waited_on": {"kind": "breakpoint", "ref": "Check_Money100"},
  "firings": 1,
  "frames_examined": 1,
  "fired_line": 226,
  "emulated_before_s": 5.331457,
  "emulated_after_s": 5.351426,
  "frame_before": 266,
  "frame_after": 267,
  "cycles": 159748,
  "screen": {"name": "insert", "layer": "file"},
  "cause": "stopped at no breakpoint this server armed",
  "stop_seq": 9,
  "pc": "0x000300aa",
  "cpu": ":maincpu",
  "frame": 267,
  "regs": {
    "EAX": "0x7000",
    "ECX": "0x0000",
    "EDX": "0x73ca",
    "EBX": "0x05ba",
    "ESP": "0x99d1",
    "EBP": "0xbe31",
    "ESI": "0x8db6",
    "EDI": "0x89db",
    "EIP": "0x000300aa",
    "EFLAGS": "0xf046",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300AA", "bytes": "50", "text": "push    aw", "symbol": "New_IRQ_Video", "delta": 1},
  "following": ["300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy", "300C9: 5E             pop     ix"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**12. `declaration_clear`**: OK counted: untick: the tick's stop cleared

<details><summary>call and reply</summary>

```json
{
  "kind": "breakpoint",
  "all": true
}
```

```json
{
  "summary": "declaration_clear breakpoint all: 1 cleared, 1 disarmed",
  "status": "ok",
  "declarations_cleared": 1,
  "disarmed": ["4 @ 31457"],
  "while_running": false,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**13. `screen_map_find`**: OK is insert: the insert screen, its controls banner, credits

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "screen_map_find: insert (file), 2 controls",
  "status": "ok",
  "matched": true,
  "screen": "insert",
  "layer": "file",
  "kind": "pixel",
  "size": [320, 200],
  "controls": [
    {"name": "banner", "rect": [0, 6, 320, 22], "centre": [160, 17]},
    {"name": "credits", "rect": [230, 186, 76, 12], "centre": [268, 192]}
  ],
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#8",
  "pc_before": "0x000300aa",
  "cause": "screen_map_find: one step",
  "stop_seq": 10,
  "pc": "0x000300ab",
  "cpu": ":maincpu",
  "frame": 267,
  "regs": {
    "EAX": "0x7000",
    "ECX": "0x0000",
    "EDX": "0x73ca",
    "EBX": "0x05ba",
    "ESP": "0x99cf",
    "EBP": "0xbe31",
    "ESI": "0x8db6",
    "EDI": "0x89db",
    "EIP": "0x000300ab",
    "EFLAGS": "0xf046",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300AB", "bytes": "53", "text": "push    bw", "symbol": "New_IRQ_Video", "delta": 2},
  "following": ["300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy", "300C9: 5E             pop     ix", "300CA: 5A             pop     dw"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**14. `read_memory`**: OK credits: Credits holds 3

<details><summary>call and reply</summary>

```json
{
  "ref": "Credits",
  "length": 2
}
```

```json
{
  "summary": "read_memory Credits: 2 bytes at 0x0000914a: 0300",
  "status": "ok",
  "addr": "0x0000914a",
  "length": 2,
  "hex": "0300",
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**15. `input`**: OK press start: START pressed

<details><summary>call and reply</summary>

```json
{
  "port": ":P1",
  "field": "1 Player Start",
  "frames": 4
}
```

```json
{
  "summary": "input :P1 '1 Player Start': held 4 frames, active True, released at frame 271",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 267,
  "frame_after": 272,
  "emulated_before_s": 5.351427,
  "emulated_after_s": 5.451265,
  "cycles": 798706,
  "polls": 5,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":P1",
  "field": "1 Player Start",
  "value": "0x00000001",
  "frames": 4,
  "name": "1 Player Start",
  "player": 0,
  "mask": "0x00000002",
  "defvalue": "0x00000002",
  "port_before": "0x000000ff",
  "frame_set": 267,
  "released": true,
  "port_held": "0x000000fd",
  "frame_released": 271,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 11,
  "pc": "0x000300a9",
  "cpu": ":maincpu",
  "frame": 272,
  "regs": {
    "EAX": "0x0000",
    "ECX": "0x0084",
    "EDX": "0x73ca",
    "EBX": "0xc580",
    "ESP": "0x99cb",
    "EBP": "0xbe31",
    "ESI": "0xbe10",
    "EDI": "0x3340",
    "EIP": "0x000300a9",
    "EFLAGS": "0xf082",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300A9", "bytes": "55", "text": "push    bp", "symbol": "New_IRQ_Video", "delta": 0},
  "following": ["300AA: 50             push    aw", "300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**16. `run_to`**: OK to the level: stopped at Level_Write

<details><summary>call and reply</summary>

```json
{
  "ref": "Level_Write",
  "control": "Check_Money25",
  "seconds": 120
}
```

```json
{
  "summary": "run_to Level_Write: TARGET, control counted 180",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 180,
  "controls": [
    {"ref": "Check_Money25", "cpu": ":maincpu", "hits_in_run": 180}
  ],
  "cause": "target Level_Write",
  "stop_seq": 12,
  "pc": "0x000343d0",
  "cpu": ":maincpu",
  "frame": 451,
  "regs": {
    "EAX": "0x1000",
    "ECX": "0x0000",
    "EDX": "0x0002",
    "EBX": "0x43d0",
    "ESP": "0x99d9",
    "EBP": "0xbe31",
    "ESI": "0x8000",
    "EDI": "0xfaa0",
    "EIP": "0x000343d0",
    "EFLAGS": "0xf002",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {
    "address": "343D0",
    "bytes": "BB8834",
    "text": "mov     bw,3488h",
    "symbol": "Level_Write",
    "delta": 0
  },
  "following": ["343D3: 8B 7C 34    mov     iy,[ix+34h]", "343D6: E8 8E 07    call    34B67h", "343D9: 8B 44 2E    mov     aw,[ix+2Eh]", "343DC: 3D 04 00    cmp     aw,4h", "343DF: 72 05       bc      343E6h", "343E1: 2D 03 00    sub     aw,3h", "343E4: EB F6       br      343DCh", "343E6: B9 01 00    mov     cw,1h", "343E9: 8B 7C 34    mov     iy,[ix+34h]", "343EC: 81 C7 24 1E add     iy,1E24h"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**17. `breakpoint_at`**: OK level shown: tick: a stop on Check_Money100

<details><summary>call and reply</summary>

```json
{
  "ref": "Check_Money100"
}
```

```json
{
  "summary": "breakpoint_at Check_Money100: armed at 0x00031457",
  "status": "ok",
  "ref": "Check_Money100",
  "by": "symbol",
  "role": "stop",
  "cpu": ":maincpu",
  "stored": true,
  "while_running": false,
  "addr": "0x00031457",
  "armed": true,
  "state": "armed",
  "entry": "7 @ 31457",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**18. `screen_wait`**: OK level shown: LEVEL 1 written

<details><summary>call and reply</summary>

```json
{
  "screen": "level",
  "on_breakpoint": "Check_Money100",
  "seconds": 120
}
```

```json
{
  "summary": "screen_wait screen 'level': found after 1 firing of breakpoint 'Check_Money100'",
  "status": "ok",
  "verdict": "TARGET",
  "predicate": "screen",
  "already": false,
  "waited_s": "<volatile>",
  "waited_on": {"kind": "breakpoint", "ref": "Check_Money100"},
  "firings": 1,
  "frames_examined": 1,
  "fired_line": 212,
  "emulated_before_s": 9.026471,
  "emulated_after_s": 9.065475,
  "frame_before": 451,
  "frame_after": 453,
  "cycles": 312037,
  "screen": {"name": "level", "layer": "file"},
  "cause": "stopped at no breakpoint this server armed",
  "stop_seq": 14,
  "pc": "0x000300aa",
  "cpu": ":maincpu",
  "frame": 453,
  "regs": {
    "EAX": "0x8183",
    "ECX": "0x0001",
    "EDX": "0x0017",
    "EBX": "0x1680",
    "ESP": "0x99c9",
    "EBP": "0xbe31",
    "ESI": "0x1684",
    "EDI": "0x7a6f",
    "EIP": "0x000300aa",
    "EFLAGS": "0xf006",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x81a2",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300AA", "bytes": "50", "text": "push    aw", "symbol": "New_IRQ_Video", "delta": 1},
  "following": ["300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy", "300C9: 5E             pop     ix"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**19. `declaration_clear`**: OK level shown: untick: the tick's stop cleared

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
  "disarmed": ["5 @ 3140C if (++temp0)==0", "7 @ 31457"],
  "while_running": false,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**20. `screen_map_find`**: OK is level: the level screen, its controls p1_well, p2_well, credits

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "screen_map_find: level (file), 3 controls",
  "status": "ok",
  "matched": true,
  "screen": "level",
  "layer": "file",
  "kind": "pixel",
  "size": [320, 200],
  "controls": [
    {"name": "p1_well", "rect": [15, 0, 98, 194], "centre": [64, 97]},
    {"name": "p2_well", "rect": [207, 0, 98, 194], "centre": [256, 97]},
    {"name": "credits", "rect": [152, 190, 16, 10], "centre": [160, 195]}
  ],
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#12",
  "pc_before": "0x000300aa",
  "cause": "screen_map_find: one step",
  "stop_seq": 15,
  "pc": "0x000300ab",
  "cpu": ":maincpu",
  "frame": 453,
  "regs": {
    "EAX": "0x8183",
    "ECX": "0x0001",
    "EDX": "0x0017",
    "EBX": "0x1680",
    "ESP": "0x99c7",
    "EBP": "0xbe31",
    "ESI": "0x1684",
    "EDI": "0x7a6f",
    "EIP": "0x000300ab",
    "EFLAGS": "0xf006",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x81a2",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300AB", "bytes": "53", "text": "push    bw", "symbol": "New_IRQ_Video", "delta": 2},
  "following": ["300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy", "300C9: 5E             pop     ix", "300CA: 5A             pop     dw"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**21. `read_memory`**: OK one spent: Credits holds 2

<details><summary>call and reply</summary>

```json
{
  "ref": "Credits",
  "length": 2
}
```

```json
{
  "summary": "read_memory Credits: 2 bytes at 0x0000914a: 0200",
  "status": "ok",
  "addr": "0x0000914a",
  "length": 2,
  "hex": "0200",
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**22. `read_memory`**: OK first stage: Stage_Act holds 0

<details><summary>call and reply</summary>

```json
{
  "ref": "Stage_Act",
  "length": 2
}
```

```json
{
  "summary": "read_memory Stage_Act: 2 bytes at 0x000086a6: 0000",
  "status": "ok",
  "addr": "0x000086a6",
  "length": 2,
  "hex": "0000",
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**23. `breakpoint_at`**: OK play: tick: a stop on Check_Money100

<details><summary>call and reply</summary>

```json
{
  "ref": "Check_Money100"
}
```

```json
{
  "summary": "breakpoint_at Check_Money100: armed at 0x00031457",
  "status": "ok",
  "ref": "Check_Money100",
  "by": "symbol",
  "role": "stop",
  "cpu": ":maincpu",
  "stored": true,
  "while_running": false,
  "addr": "0x00031457",
  "armed": true,
  "state": "armed",
  "entry": "8 @ 31457",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**24. `screen_wait`**: OK play: the board filled and the player in it

<details><summary>call and reply</summary>

```json
{
  "screen": "play",
  "on_breakpoint": "Check_Money100",
  "condition": "d@Player1 == 0x30001",
  "seconds": 120
}
```

```json
{
  "summary": "screen_wait screen 'play': found after 151 firings of breakpoint 'Check_Money100'",
  "status": "ok",
  "verdict": "TARGET",
  "predicate": "screen",
  "already": false,
  "waited_s": "<volatile>",
  "waited_on": {"kind": "breakpoint", "ref": "Check_Money100", "condition": "d@Player1 == 0x30001"},
  "firings": 151,
  "frames_examined": 5,
  "fired_line": 212,
  "emulated_before_s": 9.065476,
  "emulated_after_s": 12.080643,
  "frame_before": 453,
  "frame_after": 604,
  "cycles": 24121332,
  "screen": {"name": "play", "layer": "file"},
  "cause": "stopped at no breakpoint this server armed",
  "stop_seq": 18,
  "pc": "0x000300aa",
  "cpu": ":maincpu",
  "frame": 604,
  "regs": {
    "EAX": "0x811f",
    "ECX": "0x0027",
    "EDX": "0x0020",
    "EBX": "0x1680",
    "ESP": "0x99bb",
    "EBP": "0xbe31",
    "ESI": "0x19bd",
    "EDI": "0x6f09",
    "EIP": "0x000300aa",
    "EFLAGS": "0xf002",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x81a2",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300AA", "bytes": "50", "text": "push    aw", "symbol": "New_IRQ_Video", "delta": 1},
  "following": ["300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy", "300C9: 5E             pop     ix"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**25. `declaration_clear`**: OK play: untick: the tick's stop cleared

<details><summary>call and reply</summary>

```json
{
  "kind": "breakpoint",
  "all": true
}
```

```json
{
  "summary": "declaration_clear breakpoint all: 1 cleared, 1 disarmed",
  "status": "ok",
  "declarations_cleared": 1,
  "disarmed": ["8 @ 31457"],
  "while_running": false,
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**26. `screen_map_find`**: OK is play: the play screen, its controls p1_well, p2_well, credits

<details><summary>call and reply</summary>

```json
{}
```

```json
{
  "summary": "screen_map_find: play (file), 3 controls",
  "status": "ok",
  "matched": true,
  "screen": "play",
  "layer": "file",
  "kind": "pixel",
  "size": [320, 200],
  "controls": [
    {"name": "p1_well", "rect": [15, 0, 98, 194], "centre": [64, 97]},
    {"name": "p2_well", "rect": [207, 0, 98, 194], "centre": [256, 97]},
    {"name": "credits", "rect": [152, 190, 16, 10], "centre": [160, 195]}
  ],
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#16",
  "pc_before": "0x000300aa",
  "cause": "screen_map_find: one step",
  "stop_seq": 19,
  "pc": "0x000300ab",
  "cpu": ":maincpu",
  "frame": 604,
  "regs": {
    "EAX": "0x811f",
    "ECX": "0x0027",
    "EDX": "0x0020",
    "EBX": "0x1680",
    "ESP": "0x99b9",
    "EBP": "0xbe31",
    "ESI": "0x19bd",
    "EDI": "0x6f09",
    "EIP": "0x000300ab",
    "EFLAGS": "0xf002",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x81a2",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300AB", "bytes": "53", "text": "push    bw", "symbol": "New_IRQ_Video", "delta": 2},
  "following": ["300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy", "300C9: 5E             pop     ix", "300CA: 5A             pop     dw"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**27. `read_memory`**: OK player in play: in play

<details><summary>call and reply</summary>

```json
{
  "ref": "Player1",
  "length": 12
}
```

```json
{
  "summary": "read_memory Player1: 12 bytes at 0x00008400: 010003000100000003000000",
  "status": "ok",
  "addr": "0x00008400",
  "length": 12,
  "hex": "010003000100000003000000",
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**28. `input`**: OK press right: RIGHT pressed

<details><summary>call and reply</summary>

```json
{
  "port": ":P1",
  "field": "P1 Right",
  "frames": 4
}
```

```json
{
  "summary": "input :P1 'P1 Right': held 4 frames, active True, released at frame 608",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 604,
  "frame_after": 609,
  "emulated_before_s": 12.080644,
  "emulated_after_s": 12.180481,
  "cycles": 798697,
  "polls": 5,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":P1",
  "field": "P1 Right",
  "value": "0x00000001",
  "frames": 4,
  "name": "P1 Right",
  "player": 0,
  "mask": "0x00000020",
  "defvalue": "0x00000020",
  "port_before": "0x000000ff",
  "frame_set": 604,
  "released": true,
  "port_held": "0x000000df",
  "frame_released": 608,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 20,
  "pc": "0x000300a9",
  "cpu": ":maincpu",
  "frame": 609,
  "regs": {
    "EAX": "0x0000",
    "ECX": "0x0002",
    "EDX": "0x0000",
    "EBX": "0x497c",
    "ESP": "0x99c7",
    "EBP": "0xbe31",
    "ESI": "0x1532",
    "EDI": "0xae4a",
    "EIP": "0x000300a9",
    "EFLAGS": "0xf086",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x6182",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300A9", "bytes": "55", "text": "push    bp", "symbol": "New_IRQ_Video", "delta": 0},
  "following": ["300AA: 50             push    aw", "300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**29. `run_to`**: OK moved: the move taken

<details><summary>call and reply</summary>

```json
{
  "ref": "Gest_Scores",
  "control": "Check_Money25",
  "seconds": 120
}
```

```json
{
  "summary": "run_to Gest_Scores: TARGET, control counted 1",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 1,
  "controls": [
    {"ref": "Check_Money25", "cpu": ":maincpu", "hits_in_run": 1}
  ],
  "cause": "target Gest_Scores",
  "stop_seq": 21,
  "pc": "0x0003092f",
  "cpu": ":maincpu",
  "frame": 610,
  "regs": {
    "EAX": "0x0000",
    "ECX": "0x0000",
    "EDX": "0x0002",
    "EBX": "0x1680",
    "ESP": "0x99db",
    "EBP": "0xbe31",
    "ESI": "0x8048",
    "EDI": "0x64d0",
    "EIP": "0x0003092f",
    "EFLAGS": "0xf006",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {
    "address": "3092F",
    "bytes": "F70600802000",
    "text": "test    word ptr [8000h],20h",
    "symbol": "Gest_Scores",
    "delta": 0
  },
  "following": ["30935: 75 25             bne     3095Ch", "30937: A1 0C 80          mov     aw,[800Ch]", "3093A: 3B 06 0E 80       cmp     aw,[800Eh]", "3093E: 74 07             be      30947h", "30940: FF 06 0E 80       inc     word ptr [800Eh]", "30944: A1 0E 80          mov     aw,[800Eh]", "30947: BF 78 96          mov     iy,9678h", "3094A: B9 05 00          mov     cw,5h", "3094D: E8 E3 3F          call    34933h"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**30. `read_memory`**: OK player one column right: one column right

<details><summary>call and reply</summary>

```json
{
  "ref": "Player1",
  "length": 12
}
```

```json
{
  "summary": "read_memory Player1: 12 bytes at 0x00008400: 010004000100000003000000",
  "status": "ok",
  "addr": "0x00008400",
  "length": 12,
  "hex": "010004000100000003000000",
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**31. `input`**: OK press fire1: FIRE1 pressed

<details><summary>call and reply</summary>

```json
{
  "port": ":P1",
  "field": "P1 Button 2",
  "frames": 4
}
```

```json
{
  "summary": "input :P1 'P1 Button 2': held 4 frames, active True, released at frame 614",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 610,
  "frame_after": 615,
  "emulated_before_s": 12.200449,
  "emulated_after_s": 12.300289,
  "cycles": 798718,
  "polls": 6,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":P1",
  "field": "P1 Button 2",
  "value": "0x00000001",
  "frames": 4,
  "name": "P1 Button 2",
  "player": 0,
  "mask": "0x00000080",
  "defvalue": "0x00000080",
  "port_before": "0x000000ff",
  "frame_set": 610,
  "released": true,
  "port_held": "0x0000007f",
  "frame_released": 614,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 22,
  "pc": "0x000300a9",
  "cpu": ":maincpu",
  "frame": 615,
  "regs": {
    "EAX": "0x8183",
    "ECX": "0x0060",
    "EDX": "0x000d",
    "EBX": "0x1680",
    "ESP": "0x99cb",
    "EBP": "0xbe31",
    "ESI": "0x1684",
    "EDI": "0x8690",
    "EIP": "0x000300a9",
    "EFLAGS": "0xf002",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x81a2",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300A9", "bytes": "55", "text": "push    bp", "symbol": "New_IRQ_Video", "delta": 0},
  "following": ["300AA: 50             push    aw", "300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**32. `run_to`**: OK raised: the colour taken

<details><summary>call and reply</summary>

```json
{
  "ref": "Gest_Scores",
  "control": "Check_Money25",
  "seconds": 120
}
```

```json
{
  "summary": "run_to Gest_Scores: TARGET, control counted 1",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 1,
  "controls": [
    {"ref": "Check_Money25", "cpu": ":maincpu", "hits_in_run": 1}
  ],
  "cause": "target Gest_Scores",
  "stop_seq": 23,
  "pc": "0x0003092f",
  "cpu": ":maincpu",
  "frame": 615,
  "regs": {
    "EAX": "0x0000",
    "ECX": "0x0000",
    "EDX": "0x0000",
    "EBX": "0x1680",
    "ESP": "0x99db",
    "EBP": "0xbe31",
    "ESI": "0x8048",
    "EDI": "0x96d0",
    "EIP": "0x0003092f",
    "EFLAGS": "0xf006",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {
    "address": "3092F",
    "bytes": "F70600802000",
    "text": "test    word ptr [8000h],20h",
    "symbol": "Gest_Scores",
    "delta": 0
  },
  "following": ["30935: 75 25             bne     3095Ch", "30937: A1 0C 80          mov     aw,[800Ch]", "3093A: 3B 06 0E 80       cmp     aw,[800Eh]", "3093E: 74 07             be      30947h", "30940: FF 06 0E 80       inc     word ptr [800Eh]", "30944: A1 0E 80          mov     aw,[800Eh]", "30947: BF 78 96          mov     iy,9678h", "3094A: B9 05 00          mov     cw,5h", "3094D: E8 E3 3F          call    34933h"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**33. `read_memory`**: OK player the next colour: the next colour

<details><summary>call and reply</summary>

```json
{
  "ref": "Player1",
  "length": 12
}
```

```json
{
  "summary": "read_memory Player1: 12 bytes at 0x00008400: 010004000200000003000000",
  "status": "ok",
  "addr": "0x00008400",
  "length": 12,
  "hex": "010004000200000003000000",
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**34. `input`**: OK press up: UP pressed

<details><summary>call and reply</summary>

```json
{
  "port": ":P1",
  "field": "P1 Up",
  "frames": 4
}
```

```json
{
  "summary": "input :P1 'P1 Up': held 4 frames, active True, released at frame 619",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 615,
  "frame_after": 620,
  "emulated_before_s": 12.305077,
  "emulated_after_s": 12.400129,
  "cycles": 760414,
  "polls": 5,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "route": "ioport",
  "port": ":P1",
  "field": "P1 Up",
  "value": "0x00000001",
  "frames": 4,
  "name": "P1 Up",
  "player": 0,
  "mask": "0x00000004",
  "defvalue": "0x00000004",
  "port_before": "0x000000ff",
  "frame_set": 615,
  "released": true,
  "port_held": "0x000000fb",
  "frame_released": 619,
  "active": true,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 24,
  "pc": "0x000300a9",
  "cpu": ":maincpu",
  "frame": 620,
  "regs": {
    "EAX": "0xffff",
    "ECX": "0x0000",
    "EDX": "0x0002",
    "EBX": "0x490a",
    "ESP": "0x99d7",
    "EBP": "0xbe31",
    "ESI": "0x8048",
    "EDI": "0xfaa0",
    "EIP": "0x000300a9",
    "EFLAGS": "0xf097",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300A9", "bytes": "55", "text": "push    bp", "symbol": "New_IRQ_Video", "delta": 0},
  "following": ["300AA: 50             push    aw", "300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**35. `run_to`**: OK shot: the shot launched

<details><summary>call and reply</summary>

```json
{
  "ref": "Gest_Scores",
  "control": "Check_Money25",
  "seconds": 120
}
```

```json
{
  "summary": "run_to Gest_Scores: TARGET, control counted 2",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 2,
  "controls": [
    {"ref": "Check_Money25", "cpu": ":maincpu", "hits_in_run": 2}
  ],
  "cause": "target Gest_Scores",
  "stop_seq": 25,
  "pc": "0x0003092f",
  "cpu": ":maincpu",
  "frame": 621,
  "regs": {
    "EAX": "0x0000",
    "ECX": "0x0000",
    "EDX": "0x0000",
    "EBX": "0x1680",
    "ESP": "0x99db",
    "EBP": "0xbe31",
    "ESI": "0x8048",
    "EDI": "0x96d0",
    "EIP": "0x0003092f",
    "EFLAGS": "0xf006",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {
    "address": "3092F",
    "bytes": "F70600802000",
    "text": "test    word ptr [8000h],20h",
    "symbol": "Gest_Scores",
    "delta": 0
  },
  "following": ["30935: 75 25             bne     3095Ch", "30937: A1 0C 80          mov     aw,[800Ch]", "3093A: 3B 06 0E 80       cmp     aw,[800Eh]", "3093E: 74 07             be      30947h", "30940: FF 06 0E 80       inc     word ptr [800Eh]", "30944: A1 0E 80          mov     aw,[800Eh]", "30947: BF 78 96          mov     iy,9678h", "3094A: B9 05 00          mov     cw,5h", "3094D: E8 E3 3F          call    34933h"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**36. `read_memory`**: OK player a shot of it: a shot of it

<details><summary>call and reply</summary>

```json
{
  "ref": "Player1",
  "length": 12
}
```

```json
{
  "summary": "read_memory Player1: 12 bytes at 0x00008400: 030004000200040006000200",
  "status": "ok",
  "addr": "0x00008400",
  "length": 12,
  "hex": "030004000200040006000200",
  "cpu": ":maincpu",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**37. `audio_record`**: OK record: 101 frames recorded, the first whole frames past 2000 ms

<details><summary>call and reply</summary>

```json
{
  "frames": 101,
  "dest": "./tmp/demos/lineup/music.wav"
}
```

```json
{
  "summary": "audio_record: 96000 samples at 48000 Hz x 1 at ./tmp/demos/lineup/music.wav",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 621,
  "frame_after": 726,
  "emulated_before_s": 12.425151,
  "emulated_after_s": 14.516737,
  "cycles": 16732685,
  "polls": 105,
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "path": "<volatile>",
  "frames": 101,
  "began": true,
  "frame_begin": 622,
  "recording_after": true,
  "ended": true,
  "bytes": 192044,
  "channels": 1,
  "sample_rate_hz": 48000,
  "samples": 96000,
  "emulated_s": 2.016768,
  "sample_min": -11988,
  "sample_max": -3484,
  "frame_end": 722,
  "cause": "the `gvblank` stop of the last frame asked",
  "stop_seq": 26,
  "pc": "0x000300a9",
  "cpu": ":maincpu",
  "frame": 726,
  "regs": {
    "EAX": "0x02d4",
    "ECX": "0x0000",
    "EDX": "0x0002",
    "EBX": "0x490a",
    "ESP": "0x99d7",
    "EBP": "0xbe31",
    "ESI": "0x8048",
    "EDI": "0xfaa0",
    "EIP": "0x000300a9",
    "EFLAGS": "0xf097",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300A9", "bytes": "55", "text": "push    bp", "symbol": "New_IRQ_Video", "delta": 0},
  "following": ["300AA: 50             push    aw", "300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**38. `audio_compare`**: OK heard: a sound, peaking at -8.73 dBFS

<details><summary>call and reply</summary>

```json
{
  "method": "measure",
  "path": "./tmp/demos/lineup/music.wav"
}
```

```json
{
  "summary": "audio_compare measure: ch0 peak -8.73 dBFS, onset 0.0 s",
  "status": "ok",
  "sample_rate_hz": 48000,
  "channels": 1,
  "bits": 16,
  "window": "<volatile>",
  "measures": [
    {
      "channel": 0,
      "peak_dbfs": -8.73,
      "rms_dbfs": -35.52,
      "silent": false,
      "silence_spans": {
        "count": 0,
        "first": {"available": false, "why": "no silence in the window"}
      },
      "onset_s": 0.0,
      "clipping_run": 0,
      "clipped": false
    }
  ],
  "pcm_sha256": "<volatile>",
  "path": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**39. `audio_compare`**: OK exact: the recording is music.wav, sample for sample

<details><summary>call and reply</summary>

```json
{
  "method": "diff",
  "a": "./tmp/demos/lineup/music.wav",
  "b": "./demos/lineup/music.wav",
  "align": false
}
```

```json
{
  "summary": "audio_compare diff: exact, equal, envelope 1.0",
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
  "a": "./tmp/demos/lineup/music.wav",
  "b": "./demos/lineup/music.wav",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**40. `screen_view`**: OK screen: the board, 320x200

<details><summary>call and reply</summary>

```json
{
  "dest": "./tmp/demos/lineup/screen.png",
  "attach": false
}
```

```json
{
  "summary": "screen_view render :screen frame 726 from indices; 1280x800 PNG x4, not inlined",
  "status": "ok",
  "mode": "render",
  "screen": ":screen",
  "width": 320,
  "height": 200,
  "frame_screen": 726,
  "palette": ":palette",
  "entries": 256,
  "screen_indexed": true,
  "crop": [0, 0, 320, 200],
  "image": {
    "path": "./tmp/demos/lineup/screen.png",
    "bytes": "<volatile>",
    "sha256": "<volatile>",
    "width": 1280,
    "height": 800,
    "scale": 4,
    "indexed": true,
    "inline": false,
    "not_inlined": "attach=false"
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#21",
  "pc_before": "0x000300a9",
  "cause": "screen_view: one step",
  "stop_seq": 27,
  "pc": "0x000300aa",
  "cpu": ":maincpu",
  "frame": 726,
  "regs": {
    "EAX": "0x02d4",
    "ECX": "0x0000",
    "EDX": "0x0002",
    "EBX": "0x490a",
    "ESP": "0x99d5",
    "EBP": "0xbe31",
    "ESI": "0x8048",
    "EDI": "0xfaa0",
    "EIP": "0x000300aa",
    "EFLAGS": "0xf097",
    "CS": "0x3000",
    "SS": "0x0040",
    "DS": "0x0040",
    "ES": "0x1000",
    "FS": "0x00000000",
    "GS": "0x00000000",
    "ST0": "0x00000000000000000000",
    "ST1": "0x00000000000000000000",
    "ST2": "0x00000000000000000000",
    "ST3": "0x00000000000000000000",
    "ST4": "0x00000000000000000000",
    "ST5": "0x00000000000000000000",
    "ST6": "0x00000000000000000000",
    "ST7": "0x00000000000000000000",
    "FCTRL": "0x00000000",
    "FSTAT": "0x00000000",
    "FTAG": "0x00000000",
    "FISEG": "0x00000000",
    "FIOFF": "0x00000000",
    "FOSEG": "0x00000000",
    "FOOFF": "0x00000000",
    "FOP": "0x00000000"
  },
  "instruction": {"address": "300AA", "bytes": "50", "text": "push    aw", "symbol": "New_IRQ_Video", "delta": 1},
  "following": ["300AB: 53             push    bw", "300AC: 51             push    cw", "300AD: 52             push    dw", "300AE: 56             push    ix", "300AF: 57             push    iy", "300B0: 1E             push    ds0", "300B1: 06             push    ds1", "300B2: 9C             push    psw", "300B3: B8 40 00       mov     aw,40h", "300B6: 8E D8          mov     ds0,aw", "300B8: B8 00 10       mov     aw,1000h", "300BB: 8E C0          mov     ds1,aw", "300BD: FC             clr1    dir", "300BE: 83 3E C8 8D 01 cmp     word ptr [8DC8h],1h", "300C3: 75 0B          bne     300D0h", "300C5: 9D             pop     psw", "300C6: 07             pop     ds1", "300C7: 1F             pop     ds0", "300C8: 5F             pop     iy", "300C9: 5E             pop     ix"],
  "errorlog": "<volatile>",
  "session": {
    "alive": true,
    "running": false,
    "altered": false,
    "omitted": ["altering_writes", "console"],
    "how": "<volatile>"
  }
}
```

</details>

**41. `close`**: OK close: closed: quit

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
  "how": "<volatile>",
  "ended_by": "quit",
  "exit_code": 0,
  "cfg_written": true,
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "console_pending_before": 0,
  "console_drained": 0,
  "draft": ["start/lineup"],
  "session": {"alive": false, "running": false, "altered": false}
}
```

</details>
