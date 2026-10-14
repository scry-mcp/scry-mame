# stub-two-cpus fixtures

CAPTURED, none typed, from MAME's own gdbstub at the fleet's pinned commit on `radendur`, a board
with two 68000s, parked at the debugger right after the boot:

- `target.xml`: the description the stub answers to `qXfer:features:read:target.xml`. The main
  cpu's registers sit under `org.gnu.gdb.m68k.core`; the stub appends every other device's
  visible state under a feature named `mame./<tag>`, here the second 68000's.
- `g.reply`: the stub's answer to `g`, which carries both groups.
- `p.json`: the stub's answer to `p<n>` for each of the main cpu's registers, by name: the
  known answer the `g` reply is cut against.
- `target.thread2.xml`, `g.thread1.reply`, `g.thread2.reply`: the build patched to serve a GDB
  thread per cpu, stopped at one instant after sixty frames. Thread 2's description is the second
  cpu's: its own registers first, then the first cpu's state under `mame./maincpu`, where thread
  1's appends `mame./subcpu`. Each `g` reply is that thread's cpu's registers first: the pc is
  `0xb90` on thread 1 and `0x542` on thread 2.
