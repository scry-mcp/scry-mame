**1. `start`**: OK start: speedf on MAME from the game's own recipe (9 keys), rom_check OK, 225 symbols

<details><summary>call and reply</summary>

```json
{
  "profile": "<host>",
  "inipath": "<host>",
  "state_dir": "<host>",
  "shared": true
}
```

```json
{
  "summary": "<volatile>",
  "status": "ok",
  "system": "speedf",
  "binary": "<volatile>",
  "binary_origin": "<volatile>",
  "version": "0.289 (unknown)",
  "pid": "<volatile>",
  "stub_port": "<volatile>",
  "scratch_dir": "<volatile>",
  "state_dir": "./tmp/demos/speedf/speedf-states",
  "cfg": {"available": false, "why": "no cfg was given, so MAME runs on its defaults"},
  "debugger": {
    "attached": "gdbstub",
    "note": "MAME runs with -debug under this stub. A capture taken at one of this session's stops can land a frame away from an autoboot golden taken by a frame notifier at the same count, in a scene that changes every frame: compare a live capture with a live golden"
  },
  "errorlog_path": "<volatile>",
  "stdout_path": "<volatile>",
  "rom_check": "OK",
  "symbols_total": 225,
  "symbols_format": "tsv",
  "symbols_by_class": {"CODE": 167, "DATA": 58},
  "symbols_by_cpu": {":maincpu": 225},
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
  "machine": {"cpus": 1, "spaces": 2, "address_map": 18, "regions": 2, "shares": 0, "screens": 1, "rom_files": 3},
  "declarations": {
    "persistent": true,
    "path": "./tmp/demos/speedf/speedf-states/declarations.json",
    "key": "<volatile>",
    "held": 0,
    "fingerprint": "e08811564190b354",
    "rearm": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": [], "evaluated": []},
    "comments": {"rearmed": [], "stale": [], "unresolved": [], "unarmable": []}
  },
  "recommended_release": "0.289",
  "window": {
    "display": 0,
    "bounds": {"x": 224, "y": 30, "width": 1600, "height": 1032},
    "onscreen": true,
    "front": true,
    "fullscreen": false
  },
  "kept": "kept 1 (promote to review)",
  "profile": {
    "name": "<volatile>",
    "file": "<volatile>",
    "supplied": ["bases", "binary", "boot_seconds", "reference_addr", "reference_base", "reference_rom", "rompath", "symbols", "system"]
  },
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

**2. `run_to`**: OK to the demo: stopped at startdemo

<details><summary>call and reply</summary>

```json
{
  "ref": "startdemo",
  "control": "new_irq_video",
  "seconds": 300
}
```

```json
{
  "summary": "run_to startdemo: TARGET, control counted 920",
  "status": "ok",
  "verdict": "TARGET",
  "control_hits": 920,
  "controls": [
    {"ref": "new_irq_video", "cpu": ":maincpu", "hits_in_run": 920}
  ],
  "cause": "target startdemo",
  "stop_seq": 2,
  "pc": "0x000f5e2f",
  "cpu": ":maincpu",
  "frame": 923,
  "regs": {
    "EAX": "0x0000",
    "ECX": "0x0000",
    "EDX": "0x0000",
    "EBX": "0x0421",
    "ESP": "0xbfce",
    "EBP": "0x0037",
    "ESI": "0x300f",
    "EDI": "0xb00f",
    "EIP": "0x000f5e2f",
    "EFLAGS": "0xf047",
    "CS": "0xed00",
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
  "instruction": {"address": "F5E2F", "bytes": "06", "text": "push    ds1", "symbol": "startdemo", "delta": 0},
  "following": ["F5E30: 1E             push    ds0", "F5E31: 1E             push    ds0", "F5E32: 07             pop     ds1", "F5E33: 0E             push    ps", "F5E34: 1F             pop     ds0", "F5E35: 8B D8          mov     bw,aw", "F5E37: D1 E3          shl     bw,1", "F5E39: D1 E3          shl     bw,1", "F5E3B: 26 8B B7 45 CE mov     ix,ds1:[bw-31BBh]", "F5E40: BF 35 CA       mov     iy,0CA35h", "F5E43: 2E 8B 0C       mov     cw,ps:[ix]", "F5E46: 83 C1 04       add     cw,4h", "F5E49: F3 A4          rep     movbkb  ", "F5E4B: 26 8B B7 47 CE mov     ix,ds1:[bw-31B9h]"],
  "errorlog": {
    "lines_total": 1,
    "truncated": false,
    "lines": ["[:] 0fa039: spider_blitter_w unhandled RAM access 000f7006 0000 ff00"],
    "mark": 126
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

**3. `read_memory`**: OK scene: _sceneId 2: the attract dispatcher's current scene

<details><summary>call and reply</summary>

```json
{
  "ref": "_sceneId",
  "length": 1
}
```

```json
{
  "summary": "read_memory _sceneId: 1 byte at 0x0000fd16: 02",
  "status": "ok",
  "addr": "0x0000fd16",
  "length": 1,
  "hex": "02",
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

**4. `read_memory`**: OK no credits: creditos holds 0

<details><summary>call and reply</summary>

```json
{
  "ref": "creditos",
  "length": 2
}
```

```json
{
  "summary": "read_memory creditos: 2 bytes at 0x0000c41c: 0000",
  "status": "ok",
  "addr": "0x0000c41c",
  "length": 2,
  "hex": "0000",
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

**5. `run_for`**: OK plays: the demo plays: ran to frame 1103, 24000010 cycles

<details><summary>call and reply</summary>

```json
{
  "milliseconds": 3000,
  "seconds": 300
}
```

```json
{
  "summary": "run_for 3000 ms: ELAPSED, frame 923 to 1103",
  "status": "ok",
  "verdict": "ELAPSED",
  "frame_before": 923,
  "frame_after": 1103,
  "emulated_before_s": 15.390295,
  "emulated_after_s": 18.390296,
  "cycles": 24000010,
  "reads": "<volatile>",
  "cause": "the console's `gtime` stop",
  "stop_seq": 3,
  "pc": "0x000f5dab",
  "cpu": ":maincpu",
  "frame": 1103,
  "regs": {
    "EAX": "0xd000",
    "ECX": "0x0014",
    "EDX": "0x4506",
    "EBX": "0x0046",
    "ESP": "0xbfa8",
    "EBP": "0x86de",
    "ESI": "0xc0e5",
    "EDI": "0xcda0",
    "EIP": "0x000f5dab",
    "EFLAGS": "0xf046",
    "CS": "0xed00",
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
    "address": "F5DAB",
    "bytes": "83062BC00A",
    "text": "add     word ptr [0C02Bh],0Ah",
    "symbol": "pushitem",
    "delta": 37
  },
  "following": ["F5DB0: FF 06 2D C0    inc     word ptr [0C02Dh]", "F5DB4: 1F             pop     ds0", "F5DB5: C3             ret     ", "F5DB6: 83 3E 29 C0 00 cmp     word ptr [0C029h],0h", "F5DBB: 74 71          be      0F5E2Eh", "F5DBD: 83 3E 2D C0 00 cmp     word ptr [0C02Dh],0h", "F5DC2: 74 6A          be      0F5E2Eh", "F5DC4: 06             push    ds1", "F5DC5: B8 00 20       mov     aw,2000h", "F5DC8: 8E C0          mov     ds1,aw", "F5DCA: BD 31 C0       mov     bp,0C031h"],
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

**6. `screen_view`**: OK screen: the demo, 320x200, sha256 e33dcad8f0dc

<details><summary>call and reply</summary>

```json
{
  "mode": "render",
  "dest": "./tmp/demos/speedf/screen.png",
  "scale": 2
}
```

```json
{
  "summary": "screen_view render :screen frame 1103 from indices; 640x400 PNG x2, inline",
  "status": "ok",
  "mode": "render",
  "screen": ":screen",
  "width": 320,
  "height": 200,
  "frame_screen": 1103,
  "palette": ":palette",
  "entries": 1024,
  "screen_indexed": true,
  "crop": [0, 0, 320, 200],
  "image": {
    "path": "./tmp/demos/speedf/screen.png",
    "bytes": 24292,
    "sha256": "e33dcad8f0dc68675f59d2472b51d586376fde9729262a87f19e1cb057b373fd",
    "width": 640,
    "height": 400,
    "scale": 2,
    "indexed": false,
    "inline": true
  },
  "evaluated_by": "one step",
  "lines_ahead": 0,
  "thread_errors": 0,
  "console_reruns": 0,
  "call": "MAME_MCP_LUA_END#1",
  "pc_before": "0x000f5dab",
  "cause": "screen_view: one step",
  "stop_seq": 4,
  "pc": "0x000f5db0",
  "cpu": ":maincpu",
  "frame": 1103,
  "regs": {
    "EAX": "0xd000",
    "ECX": "0x0014",
    "EDX": "0x4506",
    "EBX": "0x0046",
    "ESP": "0xbfa8",
    "EBP": "0x86de",
    "ESI": "0xc0e5",
    "EDI": "0xcda0",
    "EIP": "0x000f5db0",
    "EFLAGS": "0xf082",
    "CS": "0xed00",
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
    "address": "F5DB0",
    "bytes": "FF062DC0",
    "text": "inc     word ptr [0C02Dh]",
    "symbol": "pushitem",
    "delta": 42
  },
  "following": ["F5DB4: 1F             pop     ds0", "F5DB5: C3             ret     ", "F5DB6: 83 3E 29 C0 00 cmp     word ptr [0C029h],0h", "F5DBB: 74 71          be      0F5E2Eh", "F5DBD: 83 3E 2D C0 00 cmp     word ptr [0C02Dh],0h", "F5DC2: 74 6A          be      0F5E2Eh", "F5DC4: 06             push    ds1", "F5DC5: B8 00 20       mov     aw,2000h", "F5DC8: 8E C0          mov     ds1,aw", "F5DCA: BD 31 C0       mov     bp,0C031h", "F5DCD: 1E             push    ds0", "F5DCE: 8B 7E 04       mov     iy,[bp+4h]"],
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

Also attached: image/png.

</details>

**7. `close`**: OK close: closed: MAME quit on its own

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
  "draft": ["start/speedf"],
  "session": {"alive": false, "running": false, "altered": false}
}
```

</details>
