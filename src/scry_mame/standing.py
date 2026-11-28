"""What each tool stands on in MAME: the debugger, the Lua console, a writer of MAME's own, or
the patch this project's build carries, and whether MAME ships it.

`scry_core.reference` writes the one sentence each reference entry ends with from here, and
`tests/test_mame_standing.py` fails naming a registered tool that declares nothing, or a
declaration for no tool.
"""
from __future__ import annotations

from collections.abc import Iterable

from scry_core import reference

#: The debugger console, reached over the gdbstub's `qRcmd`.
DEBUGGER = reference.Facility("debugger commands")
#: MAME's own Lua console, fed through the process's stdin.
LUA = reference.Facility("Lua console")
#: The gdbstub itself, which `start` opens.
GDB = reference.Facility("gdbstub")
#: The two inventories MAME answers about its own machine.
INVENTORY = reference.Facility("`-listxml`")
#: MAME's own writers, and its save states.
SNAPSHOT = reference.Facility("screen snapshots")
VIDEO = reference.Facility("AVI writer")
SOUND = reference.Facility("WAV writer")
STATES = reference.Facility("save states")
LOGFILE = reference.Facility("the log MAME writes")
#: The gdbstub patch under `patches/`: each cpu on its own thread, so another cpu can be read.
THREADS = reference.Facility("the gdbstub's thread patch", reference.BUILD)


def host(what: str) -> reference.Facility:
    """A tool whose answer never reaches the emulator."""
    return reference.Facility(f"nothing in the emulator: {what}", reference.HOST)


STANDS_ON: dict[str, tuple[reference.Facility, ...]] = {
    "start": (GDB,),
    "status": (host("it reads the session's own process"),),
    "window": (host("it reads the window MAME opened"),),
    "close": (DEBUGGER,),
    "cpu_focus": (DEBUGGER, THREADS),
    "rom_check": (DEBUGGER, THREADS),
    "cpu_info": (DEBUGGER, THREADS),
    "machine_map": (INVENTORY, DEBUGGER),
    "log": (LOGFILE,),
    "log_wait": (LOGFILE,),
    "symbols_find": (host("it reads the symbol table `start` loaded"),),
    "knowledge_find": (host("it reads the knowledge base"),),
    "run_to": (DEBUGGER,),
    "run_for": (DEBUGGER,),
    "step": (DEBUGGER, THREADS),
    "resume": (DEBUGGER,),
    "stop": (DEBUGGER,),
    "trace": (DEBUGGER, THREADS),
    "screen_wait": (LUA, DEBUGGER),
    "breakpoint_at": (DEBUGGER,),
    "regpoint_add": (DEBUGGER,),
    "watch_add": (DEBUGGER,),
    "declaration_list": (DEBUGGER,),
    "declaration_clear": (DEBUGGER,),
    "read_memory": (DEBUGGER, THREADS),
    "read_block": (LUA, THREADS),
    "registers": (DEBUGGER, THREADS),
    "disassemble": (DEBUGGER, THREADS),
    "find": (DEBUGGER, THREADS),
    "history": (DEBUGGER,),
    "memdump": (DEBUGGER, THREADS),
    "screen_map_find": (LUA,),
    "screen_map_write": (host("it writes the screen map file"),),
    "palette": (LUA,),
    "screen_view": (LUA,),
    "screen_signature": (LUA,),
    "gfx_view": (LUA,),
    "gfx_locate": (LUA,),
    "gfx_sweep": (LUA,),
    "gfx_draft": (host("it writes the draft from what the session proved"),),
    "gfx_blits": (LUA,),
    "gfx_blit_source": (LUA,),
    "write": (DEBUGGER, THREADS),
    "set_register": (DEBUGGER, THREADS),
    "reset": (DEBUGGER,),
    "debug": (DEBUGGER,),
    "scan": (DEBUGGER,),
    "promote": (host("it writes the files the session keeps"),),
    "comment_list": (host("it reads the comment file"),),
    "comment_write": (host("it writes the comment file"),),
    "state_list": (host("it reads the state files"),),
    "state_write": (STATES,),
    "series_capture": (LUA,),
    "record": (VIDEO,),
    "audio_record": (SOUND,),
    "snapshot": (SNAPSHOT,),
    "captures": (host("it reads the files the session wrote"),),
    "image_compare": (host("it compares the files the session wrote"),),
    "audio_compare": (host("it compares the files the session wrote"),),
    "perform": (host("nothing of its own: it runs the tools it lists"),),
    "drive": (host("nothing of its own: it runs the steps it lists"),),
    "perform_export": (host("it writes the call list to a file"),),
    "gfx_load": (host("it reads the manifest"),),
    "gfx_film": (LUA,),
    "palette_log": (LUA,),
    "input": (LUA,),
    "lua": (LUA,),
    "throttle": (LUA,),
}


def missing(names: Iterable[str]) -> list[str]:
    """Which of `names` declares nothing it stands on, and which declarations name no tool."""
    tools = set(names)
    return ([f"`{n}` declares nothing it stands on" for n in sorted(tools - set(STANDS_ON))]
            + [f"`{n}` declares what it stands on, and is no tool"
               for n in sorted(set(STANDS_ON) - tools)])
