"""The LAUNCH: MAME's command line, its window, its port, and the session's start.

`start` has its body here, with the pure function that builds the argv
(`build_command`, testable without a launch), the window flags the placement helper
decides, the port probe that asks by BIND and never by connecting, and where the session's
two output channels are. The contracts (the docstrings the client reads) stay with the
registrations in `server.py`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.parsers import expat

from scry_core import guardian, judges, live_host, log_marks, placement
from scry_core import presence as scry_presence
from scry_core import progress as mprogress
from scry_core import vocabulary as vocab
from scry_core.reply_contract import unavailable

import gdb_session as gs
import mame_binary as binaries
import mame_boot_failures as failures
import mame_comments as comments
import mame_cpus as cpus
import mame_declarations as dec
import mame_envelope as menvelope
import mame_files as files
import mame_idle as idle
import mame_inputs as inputs
import mame_machine as machine
import mame_presence as mpresence
import mame_read as read
import mame_rearm as rearming
import mame_regpoints as regpoints
import mame_running as running
import mame_state as st
import mame_stub_owner as owner
import mame_symbols as syms
import mame_transport as transport
from mame_state import STATE

# THE MARK A LIVE SESSION CARRIES IN ITS ARGV, and a contract other repositories exclude on.
# A repo's own `make stop` kills by binary path, and this server spawns the SAME binary, so the
# command line is the only thing that tells a live session from the repo's own run. The scratch
# directory is unique already; `build_command` puts it on the command line, on the snapshot
# directory flag, so `ps -Ao pid,args` shows this literal on the emulator's line and a kill path
# written as `ps | awk` can leave it alone. Documented in `REFERENCE.md`; changing it is a change
# to every repo's kill path.
SCRATCH_PREFIX = "mame-mcp-"

# THE BACKGROUND LAUNCH (`live_host.BACKGROUND_VAR` says why). The captures do not move with it:
# MAME draws them from the emulated screen.
BACKGROUND_VAR = live_host.BACKGROUND_VAR
# How often the boot asks the gdbstub's port whether it listens yet.
BOOT_POLL_S = 0.3
# THE DEBUGGER CONSOLE'S BANNER, printed when the debugger console is built (`debugcon.cpp`). A
# stub without the thread patch fills its target description at the debugger's first stop and
# caches an empty one when asked before it, and its port accepts long before that stop, so the
# handshake asks once this line is out. Nothing in MAME's source orders the line against the stop:
# the rule stands on measurement, and a description that still comes back empty is the
# `NoRegisters` a relaunch answers.
DEBUGGER_BANNER = "Currently targeting "
# How many more times `start` launches a boot that failed in a way launching again can change
# (`mame_boot_failures`).
START_RETRIES_MAX = 2
# How long a MAME that closed the stub's connection is given to be reaped: a dying process
# closes its sockets before it can be waited for, and that closed channel is its death, not a
# refusal.
CLOSED_EXIT_WAIT_S = 1.0

#: What this server, and after it the guardian beside every MAME, are called in the host's
#: process list.
PROCESS_NAME = "scry-mame"
GUARDIAN_NAME = guardian.name_of(PROCESS_NAME)

# THE THROTTLE ON ARRIVAL, which is a boot harness and not a live switch, and the measurement
# behind that shape: MAME's debugger console has NO throttle command (the whole command table
# was read, and `throttle` answers "unknown command"), and the stub speaks nothing but the
# debugger. What CAN switch it is Lua (`manager.machine.video.throttled`), and at launch the Lua
# that runs is the autoboot script (the live switch is the `throttle` tool). So `start` writes this
# harness into the scratch with the target frame in the environment, adds `-nothrottle` so the
# trip is fast, and the harness lifts the throttle on arrival: frames fly by at many times the
# board's rate and drop to it from the target on. The mark
# it logs through `logerror` lands in `error.log`, where `log_wait` can prove the
# arrival. A caller's own `boot_lua` still runs, after it, through `dofile`.
THROTTLE_FRAME_VAR = "MAME_MCP_THROTTLE_FRAME"
THROTTLE_MARK = "MAME_MCP throttled from frame"
# INSIDE A `pcall`, FOR THE SAME REASON THE INVENTORY GATHER IS. The two are composed into ONE
# `-autoboot_script` now, and MAME stops executing that script at the first error: a raise here
# would take the caller's own harness, chained after it, down with it, silently, while the reply
# still named the composed script as installed. Whichever chunk fails, the others still run.
THROTTLE_LUA = """-- Written by the mame MCP server for ONE session: fly flat out to a frame, real
-- speed from there. The frame comes from the environment; the caller's harness runs after.
pcall(function()
  local screen = nil
  for _, s in pairs(manager.machine.screens) do screen = s break end
  local TARGET = tonumber(os.getenv("%(var)s") or "0")
  local done = screen == nil
  _G._mame_mcp_throttle = emu.add_machine_frame_notifier(function()
      if done then return end
      if screen:frame_number() >= TARGET then
          done = true
          manager.machine.video.throttled = true
          manager.machine:logerror(string.format("%(mark)s %%d\\n", screen:frame_number()))
      end
  end)
end)
"""


def check_rom_check(reference_rom: str, reference_addr: str = "0x0",
                    reference_base: str = "0x0", **_: Any) -> None:
    """`rom_check`'s machine-independent half: two `0x` addresses and a file that has to exist and
    be readable, refused as arguments rather than escaping as an execution failure from a tool whose
    whole job is a verdict. The two addresses are named before the file, in the order they
    always were."""
    inputs.hex_arg("reference_addr", reference_addr)
    inputs.hex_arg("reference_base", reference_base)
    reference_window_in_image(reference_rom_file(reference_rom), reference_addr, reference_base)


def reference_window_in_image(ref: Path, reference_addr: str,
                              reference_base: str) -> tuple[int, int]:
    """The address and base of the known-answer read, parsed and held INSIDE the image, or the
    refusal: the image's size is the file's, so an address it does not cover is the caller's
    argument and needs no machine. `start` and `rom_check` both ask it, and the ROM check itself
    raises the same finding as a session error, which no tool translates."""
    addr = inputs.hex_arg("reference_addr", reference_addr)
    base = inputs.hex_arg("reference_base", reference_base)
    try:
        gs.reference_window(ref.stat().st_size, addr, 16, base)
    except gs.SessionError as e:
        raise st.Invalid("bad_argument", str(e)) from None
    return addr, base


def reference_rom_file(reference_rom: str) -> Path:
    """The reference ROM as a path that exists, or the refusal: `start` and `rom_check` both take
    one, and the sentence lives here so the two cannot say it differently."""
    ref = inputs.input_file("reference_rom", reference_rom, "reference ROM")
    if not os.access(ref, os.R_OK):
        raise st.Invalid("bad_argument", f"the reference ROM {ref} is not readable")
    return ref


def window_flags(shared: bool, display: str = "") -> list[str]:
    """Window flags: the placement helper's (`scry_core.placement`) when it answers, a sensible
    default when it does not and nobody is watching.

    This server has to start just the same on a machine without the helper, which lives in its
    author's private environment, and the default is right for the normal case, nobody watching.
    A watched run is refused instead: inventing a size there is how windows end up off-screen."""
    placed = placement.ask("mame", shared, display)
    # FOR `mame` THE HELPER ALWAYS PRINTS THE WINDOW'S MODE, so no flags is a helper that could
    # not compute them, never the one-display answer it is for the other apps.
    if placed.flags:
        return placed.flags
    why = placed.why or "the helper printed no flags"
    if shared:
        raise st.Invalid("host_failed",
            f"a shared session needs the screen geometry, and {why}. Fix that, or start "
            "without `shared`: inventing a size here is how windows end up off-screen."
        )
    return ["-window", "-nomaximize", "-resolution", "320x240"]


def port_is_free(port: int) -> bool:
    """Whether the gdbstub could listen on `port` (`owner.bind_probe`)."""
    return owner.bind_probe(port) is not None


def free_port() -> int:
    """A port the kernel hands out as free (`owner.bind_probe(0)`), never a walk from a fixed
    number: two servers walking from one number land on it together while neither MAME has
    bound it yet.
    The kernel's pick makes a shared port unlikely; the dial's proof (`mame_stub_owner`) is what
    makes it harmless."""
    chosen = owner.bind_probe(0)
    if chosen is None:
        raise st.Invalid("host_failed", "the kernel would not hand out a free port for the "
                         "gdbstub")
    return chosen


#: THE DEBUGGER EVERY SESSION ATTACHES, named once for the command line and for the replies that
#: say so.
DEBUGGER = "gdbstub"


def debugger_report() -> dict[str, str]:
    """What `start` and `status` say about the debugger the machine runs under, with the note
    beside the fact so a frame's difference from a golden is not read as a regression. The note
    blames the method and not `-debug`: measured, an autoboot capture comes out byte-identical
    with and without the debugger attached, while one frame either side does not."""
    return {"attached": DEBUGGER,
            "note": "MAME runs with -debug under this stub. A capture taken at one of this "
                    "session's stops can land a frame away from an autoboot golden taken by a "
                    "frame notifier at the same count, in a scene that changes every frame: "
                    "compare a live capture with a live golden"}


def build_command(
    binary: str,
    system: str,
    rompath: str,
    port: int,
    flags: list[str],
    scratch: str,
    inipath: str = "",
    boot_lua: str = "",
    state_dir: str = "",
    view: str = "",
) -> list[str]:
    """The whole MAME command line, as a pure function, so it can be tested without launching.

    Composed apart from `start` so that whether a flag reaches the process can be checked
    without looking at the process: a harness routed in through `-inipath` with its own
    `mame.ini` can fail to arrive, and finding that out from game memory costs boots.

    `scratch` is this session's own directory, and its `snap/` ALWAYS reaches the command line
    as the snapshot directory: that is the mark `SCRATCH_PREFIX` describes, riding on the flag
    that tells the console's `snap` where to write. `cfg/` and `nvram/`, which MAME would
    otherwise write into its working directory, go under `state_dir` when the caller names one
    and under the scratch when not, so a boot is repeatable by default and persistent on request.
    Both directories are given ABSOLUTE: MAME resolves a relative one against ITS working
    directory, which is the scratch, and `start` refuses a relative `state_dir` for that reason.
    """
    state = state_dir or scratch
    # `-log` sends `logerror` to `error.log` in MAME's working directory, the scratch. Without it
    # the channel every repo's tracer reads went NOWHERE from a live session. `-debuglog` sends
    # the debugger CONSOLE's own output to `debug.log` beside it, which is the one place a
    # watchpoint stop names the value written and the writer's pc (the stub's packet carries
    # only the address); measured, and read by the stop survey.
    cmd = [binary, system, "-rompath", rompath, "-skip_gameinfo", "-log", "-debuglog",
           *flags, "-debug", "-debugger", DEBUGGER, "-debugger_port", str(port),
           "-snapshot_directory", str(Path(scratch) / "snap"),
           # THE VIEW A CAPTURE IS TAKEN THROUGH, chosen at launch because a running MAME cannot
           # switch it: `native` is the emulated screen alone, at its own size, whatever layout
           # the set ships; a name is a layout view, matched by prefix as MAME matches it.
           "-snapview", view or "native",
           "-cfg_directory", str(Path(state) / "cfg"),
           "-nvram_directory", str(Path(state) / "nvram"),
           # The states are the third occupant of the caller's state directory (`state_save`),
           # in the subfolder MAME names by default (`%g`, the system), PINNED: an ini given
           # through `inipath` may rename it, and `state_save` looks for the file it wrote here.
           "-state_directory", str(Path(state) / "sta"), "-statename", "%g",
           # MAME writes the comments it holds into this directory whenever a debugger session
           # exits. PINNED in the scratch, so the file dies with the session: the store is the
           # record, and a stale file under `state_dir` would show a deleted comment again to the
           # next plain MAME, since MAME writes nothing once it holds none.
           "-comment_directory", str(Path(scratch) / "comments"),
           # THE LUA CHANNEL: MAME's own Lua console reads stdin, which `boot` connects as a
           # pipe; see `mame_lua` for what it can and cannot do beside the gdbstub.
           "-console"]
    plugins = plugins_dir(binary)
    if plugins is not None:
        cmd += ["-pluginspath", str(plugins)]
    if inipath:
        cmd += ["-inipath", inipath]
    if boot_lua:
        # `-autoboot_delay 0` on purpose: the session starts STOPPED in the debugger, so the
        # delay only makes the harness start later than anyone wants.
        cmd += ["-autoboot_script", boot_lua, "-autoboot_delay", "0"]
    return cmd


def cfg_report() -> dict[str, Any]:
    """The cfg this session installed, for `start` and `status`: unavailable when MAME runs on
    its defaults."""
    if STATE.cfg is None:
        return unavailable(st.NO_CFG_WHY)
    return {"source_path": str(STATE.cfg["source"]),
            "installed_path": str(STATE.cfg["installed"]),
            "replaced": bool(STATE.cfg["replaced"])}


def symbols_fields() -> dict[str, Any]:
    """What `start` answers about the tables it loaded: the first cpu's count
    (`symbols_total`), `symbols_typed`, `symbols_format` and `symbols_by_class`, and
    `symbols_by_cpu`, each table loaded for a named cpu counted by its tag. A flat table names no
    cpu, so it is counted in `symbols_total` alone."""
    first = STATE.table()
    return {"symbols_total": len(first.table), "symbols_typed": len(first.types),
            "symbols_format": first.format, "symbols_by_class": first.by_class,
            "symbols_by_cpu": {cpu: len(t.table) for cpu, t in STATE.tables.items()
                               if cpu is not None}}


def channels() -> dict[str, str]:
    """Where this session's two output channels are: MAME's `error.log` and its stdout+stderr."""
    assert STATE.scratch is not None
    return {
        "errorlog_path": str(files.log_path(STATE.scratch, "emulator")),
        "stdout_path": str(files.log_path(STATE.scratch, "process")),
    }



def judge_background(background: bool | None, shared: bool, env: dict[str, str] | None) -> bool:
    """Whether MAME is launched behind: `background` when given, else behind for a run nobody
    watches and in front for a shared one. `env` carrying the hint is refused: two spellings of one
    switch let the reply name one while the process obeys the other."""
    if env and BACKGROUND_VAR in env:
        raise st.Invalid("bad_argument",
            f"`env` sets {BACKGROUND_VAR}, which is what `background` sets: pass "
            "`background=True` or `background=False` instead")
    return not shared if background is None else background


def launch_environment(given: dict[str, str], background: bool) -> dict[str, str]:
    """The environment MAME is spawned with: this server's, the variables this start adds, and
    the background hint set or REMOVED, never inherited: a server started with the hint in its
    own environment would otherwise launch every machine behind, `background=False` included."""
    spawned = {**os.environ, **given}
    if background:
        spawned[BACKGROUND_VAR] = "1"
    else:
        spawned.pop(BACKGROUND_VAR, None)
    return spawned


def boot_harness(scratch: Path, boot_lua: str, throttle_from_frame: int,
                 presence: bool = False) -> str:
    """Write the ONE `-autoboot_script` this server sends, and return its path for the command
    line: the machine's inventory always, the throttle when a frame was asked for, the presence
    drawer when presence is on (`mame_presence`), and the caller's own harness chained after
    them with `dofile`.

    ONE function because there is ONE script: MAME takes a single `-autoboot_script`, so every
    harness the server wants has to be composed into it, and the chaining rule (whose text goes
    first, how the caller's is reached) is the thing that must not exist twice. The inventory
    goes FIRST and inside its own `pcall`, so that whatever it meets on an unfamiliar board it
    cannot stop the throttle installing or the caller's harness running.
    """
    text = machine.harness(scratch / machine.DUMP_NAME)
    if throttle_from_frame:
        text += THROTTLE_LUA % {"var": THROTTLE_FRAME_VAR, "mark": THROTTLE_MARK}
    if presence:
        text += mpresence.drawer(scratch)
    if boot_lua:
        text += f"dofile({transport.lua_string(str(Path(boot_lua).resolve()))})\n"
    path = scratch / "boot.lua"
    path.write_text(text, encoding="utf-8")
    return str(path)


@dataclass(frozen=True)
class Judged:
    """Everything `start` decided from its arguments BEFORE anything exists (the window
    flags, the port, the display it will report, the symbol table, the declarations store
    and its account, the reference window), together with the launch inputs the boot needs
    as the caller gave them. A refusal happens in `judge`, with nothing to clean up; `boot`
    takes this and nothing else. `judge` takes its arguments by KEYWORD: ten of them are
    strings, and a swap of two at the one call site would type-check and fail at runtime
    against the wrong argument."""

    flags: list[str]
    port: int
    display: str
    tables: syms.Loaded
    store: dec.DeclarationStore
    declarations: dict[str, Any]
    ref: Path
    ref_addr: int
    ref_base: int
    binary: str
    system: str
    rompath: str
    inipath: str
    wait: float
    boot_lua: str
    env: dict[str, str]
    state_dir: str
    throttle_from_frame: int
    # THE `-listxml` QUERY, STILL RUNNING. `judge` puts the question and does not wait for it,
    # so it runs inside the seconds the boot spends waiting for the gdbstub: dead time, in
    # which it costs nothing. `start` collects it the moment the boot is over.
    listxml: machine.Asked
    cfg: Path | None = None       # the repo's cfg to install, judged; None for MAME's defaults
    # Its answer, when `judge` already waited for it (a `symbols` mapping names cpus).
    listed: machine.Listed | None = None
    background: bool = False      # `judge_background`'s answer
    presence: bool = False        # the caller's `presence`
    picked: bool = False          # the port is this server's pick, not the caller's `stub_port`
    view: str = ""                # the caller's `view`: empty is MAME's `native`


def collect(judged: Judged) -> machine.Listed:
    """The `-listxml` answer: the one `judge` already waited for, else collected now."""
    if judged.listed is not None:
        return judged.listed
    return machine.listxml(judged.listxml, judged.binary, judged.system, judged.wait)


def discard(judged: Judged) -> None:
    """The `-listxml` query ended WITHOUT being read: killed if it still runs, and reaped
    either way, so a boot that raised leaves no process with this server as its parent. For
    a boot that raised something other than a refusal there is no MAME diagnosis to prefer
    over the exception, so the answer is not collected, only the process."""
    proc = judged.listxml[0]
    if proc is None or judged.listed is not None:
        return
    if proc.poll() is None:
        proc.kill()
    proc.communicate()


# WHERE A MAME KEEPS ITS CONSOLE PLUGIN, relative to the directory of the RESOLVED binary (a
# packager's symlink points elsewhere), the first place holding it winning. MAME's own default
# (`plugins`, relative to its working directory, here the scratch) reaches neither, and one
# version also reads a home directory another does not, which is how one board boots and another
# dies on the same command line.
PLUGIN_PLACES = (
    "plugins",                # a source build: its tree, the one the binary was built with
    "../share/mame/plugins",  # a packaged install: under its prefix
)
CONSOLE_PLUGIN = Path("console") / "init.lua"


def plugin_places(binary: str) -> list[Path]:
    """Every directory `plugins_dir` looks in for `binary`, in order."""
    at = Path(binary).resolve().parent
    return [(at / place).resolve() for place in PLUGIN_PLACES]


def plugins_dir(binary: str) -> Path | None:
    """The first of `plugin_places` holding the console plugin, or None."""
    return next((d for d in plugin_places(binary) if (d / CONSOLE_PLUGIN).is_file()), None)


# THE LINE MAME PRINTS when it refuses a cfg and loads its defaults: the one proof, after the
# boot, that the file installed was not the file read. Measured in the MAME reference: a
# comment holding `--` produces it, and MAME overwrites the file on exit. WHERE it lands is
# read off MAME's source: `config.cpp` prints it with `osd_printf_warning`, and the OSD
# sends that channel to stderr (`osdobj_common.cpp`), never to `error.log`, which only
# `logerror` reaches. So the reader below opens the captured stdout+stderr, `stdout.log`.
# AND IT IS THERE BY THE TIME THE STUB ANSWERS: `running_machine::run` loads the settings
# before the `soft_reset` whose first instruction opens the gdbstub's socket, and `cerr`
# is unit-buffered, so a read after `connect` cannot come too early.
CFG_PARSE_ERROR = "Error parsing XML configuration file"
# What a `<port>` needs for MAME to bind it to the driver's PORT_BIT: without these three the
# file parses, binds nothing and is overwritten on exit, in silence (the MAME reference).
PORT_ATTRS = ("tag", "mask", "defvalue")


def judge_inipath(inipath: str) -> None:
    """`-inipath` is MAME's `;`-separated list of directories: each element is a path argument
    like any other, and an empty one is a slip, not a directory. One that does not exist is
    not judged, because MAME skips an ini directory it cannot find."""
    parts = inipath.split(";") if inipath else []
    for i, part in enumerate(parts):
        if not part:
            raise st.Invalid("bad_argument",
                             f"inipath={inipath!r} holds an empty element: it is a `;`-separated "
                             "list of absolute directories")
        inputs.absolute("inipath" if len(parts) == 1 else f"inipath[{i}]", part)


def judge_cfg(cfg: str, system: str) -> Path:
    """The repo's `.cfg` judged BEFORE the boot, for the two ways MAME meets one in silence:
    a `<port>` missing `tag`, `mask` or `defvalue` (parses, binds nothing, overwritten on
    exit) and XML MAME's parser refuses (a `--` inside a comment), plus a file for another
    system, which would be installed under this one's name and bind nothing. Each refusal
    names the line, read off the parser itself as each `<port>` opens, so a comment quoting
    a port or two ports on one line cannot shift it. The path is absolute, like every path
    this server takes."""
    path = inputs.input_file("cfg", cfg, "cfg")
    try:
        text = path.read_bytes()
    except OSError as e:
        raise files.unreadable("cfg", cfg, e) from None
    ports: list[tuple[int, dict[str, str]]] = []
    systems: list[str] = []
    root: list[str] = []
    parser = expat.ParserCreate()

    def opened(name: str, attrs: dict[str, str]) -> None:
        if not root:
            root.append(name)
        if name == "system":
            systems.append(attrs.get("name", ""))
        elif name == "port":
            ports.append((parser.CurrentLineNumber, attrs))

    parser.StartElementHandler = opened
    try:
        parser.Parse(text, True)
    except expat.ExpatError as e:
        raise st.Invalid("bad_argument",
            f"{cfg} is not XML MAME's parser would read ({e}); a comment holding `--` is the "
            f"usual cause, and MAME would log `{CFG_PARSE_ERROR}`, load its defaults and "
            "overwrite the file on exit") from None
    if root != ["mameconfig"]:
        raise st.Invalid("bad_argument", f"{cfg}: the root element is <{root[0] if root else ''}>, "
                                         "not <mameconfig>")
    if system not in systems:
        raise st.Invalid("bad_argument",
            f"{cfg} carries <system name=...> for {systems or 'no system'}, not for "
            f"{system!r}: installed as {system}.cfg it would bind nothing")
    for n, attrs in ports:
        missing = [a for a in PORT_ATTRS if a not in attrs]
        if missing:
            raise st.Invalid("bad_argument",
                f"{cfg} line {n}: a <port> needs `tag`, `mask` and `defvalue` for MAME to bind "
                f"it to the driver's PORT_BIT, and this one lacks "
                f"{', '.join(f'`{a}`' for a in missing)}: MAME would parse it, associate no "
                "input, and overwrite the file on exit")
    return path


def cfg_parse_error(scratch: Path) -> str | None:
    """The line of the captured stdout saying MAME refused the cfg it was given, or None."""
    log = files.log_path(scratch, "process")
    if not log.exists():
        return None
    for line in log.read_text(errors="replace").splitlines():
        if CFG_PARSE_ERROR in line:
            return line.strip()
    return None


def cannot_hold(state_dir: str, why: str) -> str:
    return f"state_dir={state_dir!r} cannot hold cfg/ and nvram/: {why}"


def judge_state_dir(state_dir: str) -> Path:
    """`state_dir` as a directory this session may own: absolute, not a file (its store is
    read under it before `cfg/` and `nvram/` are made, so the refusal names the argument and
    not a file inside a file), and never the project store's own directory, which would hand
    the session the shared store under a reply that reads as its own."""
    state = inputs.absolute("state_dir", state_dir)
    if state.exists() and not state.is_dir():
        raise st.Invalid("bad_argument", cannot_hold(state_dir, "it is not a directory") +
                         "; name a directory, or one that does not exist yet")
    if dec.store_path(state).resolve() == dec.default_path().resolve():
        raise st.Invalid("bad_argument",
            f"state_dir={state_dir!r} is the project store's own directory "
            f"({dec.state_home()}): a session with a state_dir keeps its declarations apart, "
            "so name a directory of its own")
    return state


#: The highest TCP port.
PORT_MAX = 65535


def check_start(binary: str = "", rompath: str = "", reference_rom: str = "",
                symbols: syms.Given = "", inipath: str = "", boot_lua: str = "",
                state_dir: str = "", cfg: str = "", types: syms.Types = "", display: str = "",
                view: str = "", **_: Any) -> None:
    """`start`'s machine-independent half, asked by `judge` first: the shape of every path
    argument (`inputs.absolute`: absolute or `~`-led, no NUL and no lone surrogate)
    in the order `judge` reads them, and `display`'s word, which is wrong on any machine.
    Whether each file is there, and what it holds, is the host's, and `judge`'s."""
    if binary:          # empty climbs `mame_binary`'s ladder, which judges what it lands on
        inputs.absolute("binary", binary)
    inputs.absolute("reference_rom", reference_rom)
    inputs.absolute("rompath", rompath)
    judge_inipath(inipath)
    if cfg:
        inputs.absolute("cfg", cfg)
    if boot_lua:
        inputs.absolute("boot_lua", boot_lua)
    for name, path, _thing in syms.named_files(symbols, types):
        inputs.absolute(name, path)
    if state_dir:
        inputs.absolute("state_dir", state_dir)
    vocab.one_of("display", display, placement.DISPLAY_OPTIONS)
    check_view(view)


def check_view(view: str) -> None:
    """`view` is one argument of MAME's command line: no NUL and no lone surrogate, which no
    command line can carry, and no leading `-`, which MAME would read as an option."""
    if "\x00" in view:
        raise st.Invalid("bad_argument", f"view={view!r} holds a NUL, which no command line "
                         "carries")
    try:
        view.encode("utf-8")
    except UnicodeEncodeError:
        raise st.Invalid("bad_argument", f"view={view!r} holds a lone surrogate, which no "
                         "command line carries") from None
    if view.startswith("-"):
        raise st.Invalid("bad_argument", f"view={view!r} starts with `-`, which MAME would read "
                         "as an option of its own: a view's name is its prefix")


def judge(*, binary: str, system: str, rompath: str, reference_rom: str,
          symbols: syms.Given, reference_addr: str, inipath: str, wait: float, shared: bool,
          boot_lua: str, env: dict[str, str] | None, bases: syms.Bases | None,
          reference_base: str, display: str, port: int, state_dir: str,
          throttle_from_frame: int, types: syms.Types = "", cfg: str = "",
          background: bool | None = None, presence: bool = False,
          binary_origin: str = binaries.ARGUMENT, view: str = "") -> Judged:
    """EVERY REFUSAL OF THE CALLER'S INPUT, before the emulator exists: judged after the boot,
    a bad path or symbol surfaces as a bare error from deep inside naming the path but not the
    argument, with the caller unsure whether a machine is now running. The shape of every path
    comes first (`check_start`, the half the surface also asks before the session gate); after
    it, the order is the order the arguments are read, except that every input is judged before
    `state_dir` is written."""
    check_start(binary=binary, rompath=rompath, reference_rom=reference_rom, symbols=symbols,
                inipath=inipath, boot_lua=boot_lua, state_dir=state_dir, cfg=cfg, types=types,
                display=display)
    # THE BINARY IS AN EXECUTABLE FILE ALREADY: `binary` here is what `mame_binary.resolve`
    # landed on, and `shutil.which` approves neither a directory nor a file without its exec
    # bit. The inputs below take `is_file()`, never `exists()`, which answers True for a
    # directory, so a folder carrying a file's name would reach the spawn and be refused there,
    # after the scratch has been made and with nothing in the message naming the argument.
    if plugins_dir(binary) is None:
        looked = "; ".join(str(d / CONSOLE_PLUGIN) for d in plugin_places(binary))
        # WHOSE TO FIX FOLLOWS THE RUNG, as the ladder's own refusals do: a build the caller
        # named is the caller's, one the host's variable or PATH found is the host's.
        raise st.Invalid("bad_argument" if binary_origin == binaries.ARGUMENT else "host_failed",
                         f"no console plugin for {binary} (from the {binary_origin} rung) in "
                         f"any of: {looked}. The Lua console this server connects to stdin is "
                         "MAME's `console` plugin, and without it MAME refuses to boot "
                         "(\"Console plugin not found\"): pass as `binary`, or set "
                         f"{binaries.VARIABLE} to, the executable of a MAME build or install "
                         "that ships its plugins")
    ref = reference_rom_file(reference_rom)
    # A MISSING ROM DIRECTORY IS THE WORST SHAPED FAILURE IF IT REACHES MAME: it starts without
    # its ROMs, the gdbstub never listens, and the caller waits the whole `boot_seconds` to be told
    # the STUB did not answer.
    if not (roms := inputs.absolute("rompath", rompath)).is_dir():
        inputs.no_such("ROM directory", str(roms))
    placement.check_display(shared, display)
    inputs.natural("throttle_from_frame", throttle_from_frame,
                   " is not a frame number: an integer, never negative, and 0 is off")
    display = placement.shared_display(shared, display)
    behind = judge_background(background, shared, env)
    # THE WAIT FOR THE STUB, held like every other wait: zero or less would spawn an emulator
    # only to report that it never answered, and no bound at all would hold the one lock.
    vocab.check_wait(wait, "boot_seconds")
    inputs.natural("stub_port", port, f" is not a TCP port (0 picks a free one, else "
                   f"1..{PORT_MAX})", hi=PORT_MAX)
    if port and not port_is_free(port):
        raise st.Invalid("bad_argument",
            f"stub_port {port} is not free: something holds it, or it is still closing, and a "
            "session on a port you did not ask for would leave your other client talking to "
            "nothing"
        )
    picked = not port
    port = port or free_port()
    cfg_source = judge_cfg(cfg, system) if cfg else None
    if boot_lua:
        inputs.input_file("boot_lua", boot_lua, "boot harness")
    syms.check_files(symbols, types)
    state = judge_state_dir(state_dir) if state_dir else None
    flags = window_flags(shared, display)
    if throttle_from_frame and "-nothrottle" not in flags:
        flags.append("-nothrottle")
    # A MAPPING NAMES CPUS, so the machine's own list is waited for here and not after the
    # boot: a cpu it lacks is refused with nothing spawned, and the store is keyed by the
    # first cpu's file. One path names none and leaves the question to run beside the boot.
    listed: machine.Listed | None = None
    tags: list[str] = []
    if syms.is_mapping(symbols):
        listed = machine.listxml(machine.ask_listxml(binary, system), binary, system, wait)
        tags = [row["tag"] for row in listed[0]["cpus"]]
        if not tags:
            raise st.Invalid("bad_argument",
                             f"a `symbols` mapping names cpus, and this machine's list of them "
                             f"could not be read: {listed[1]}")
    loaded = syms.load(symbols, bases, types, tags)
    # THE DECLARATIONS STORE, opened BEFORE the emulator exists so a corrupt file refuses the
    # start with nothing to clean up. Keyed by system and symbol file when there is one;
    # session-lived when there is none, because nothing could re-resolve by name. A `state_dir`
    # is the caller saying this session is its own, so its store lives there and the project
    # store, which every other session of this board shares, is never opened.
    try:
        if (key := syms.store_key(system, loaded, tags)) is not None:
            path = dec.store_path(state)
            store = dec.DeclarationStore(key, path)
            declarations: dict[str, Any] = {"persistent": True, "path": str(path), "key": key}
        else:
            store = dec.DeclarationStore(system, None)
            declarations = {"persistent": False,
                            "path": unavailable(dec.SESSION_LIVED_WHY),
                            "key": unavailable(dec.SESSION_LIVED_WHY)}
    except dec.DeclarationError as e:
        raise st.Invalid("host_failed", str(e)) from None
    declarations["held"] = len(store.declarations())
    ref_addr, ref_base = reference_window_in_image(ref, reference_addr, reference_base)
    # THE STATE DIRECTORY IS CREATED AFTER EVERY JUDGEMENT OF THE CALLER'S INPUT: it is a
    # directory this server never deletes, so a refusal must not leave `cfg/` and `nvram/` in it.
    # A path that is a file, or one that cannot be created, is the caller's and named as such.
    if state is not None:
        try:
            for sub in ("cfg", "nvram"):
                (state / sub).mkdir(parents=True, exist_ok=True)
        except NotADirectoryError as e:     # a file on the caller's path: the caller's
            raise st.Invalid("bad_argument", cannot_hold(state_dir, str(e)) +
                             "; name a directory, or one that does not exist yet") from None
        except OSError as e:
            raise st.Invalid("host_failed", cannot_hold(state_dir, str(e))) from None
    # THE QUESTION IS PUT AND NOT WAITED FOR. It asks THIS binary what it knows about this
    # system; the answer is read once the boot is over, by which time it arrived free, inside the
    # seconds the boot was already spending. It goes LAST among the judgements so that every
    # refusal that needs no process still happens with nothing started: a port out of range is
    # an answer already in hand and does not deserve a spawn.
    asked = machine.ask_listxml(binary, system) if listed is None else (None, "")
    return Judged(flags, port, display, loaded, store, declarations, ref, ref_addr, ref_base,
                  binary, system, rompath, inipath, wait, boot_lua, dict(env or {}), state_dir,
                  throttle_from_frame, asked, cfg_source, listed, background=behind,
                  presence=presence, picked=picked, view=view)


#: `start`'s `view`, described once in its schema.
VIEW_ARGUMENT = ("What `snapshot` and `record` render through, for the whole session: empty, the "
                 "emulated screen alone, at its own size (MAME's `native`); else a layout view "
                 "by prefix, MAME's own default when none matches (the reply's `views` lists "
                 "the set's, and `view` says which was taken).")


#: Where a launch's `-version` probe runs beside its boot: one at a time, as launches are.
_VERSIONS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mame-version")


def view_shown(asked: str, inventory: dict[str, Any]) -> str | dict[str, Any]:
    """The view this session's captures are taken through: `native` (the emulated screen alone)
    when none was asked, else the view MAME resolved the name to, read off the machine, which
    is the truth whether it matched the prefix or fell back to its own choice."""
    if not asked:
        return "native"
    taken = inventory.get(machine.SNAPVIEW, "")
    return taken or unavailable("MAME did not say which view its snapshots take: the boot "
                                "harness read no snapshot target")


def views_shown(inventory: dict[str, Any]) -> list[str] | dict[str, Any]:
    """The set's layout views, which `view` takes by name, or why none was listed."""
    views = inventory.get(machine.VIEWS) or []
    return views or unavailable("no render target listed a view: a machine run with no "
                                "video has none, and `view` then takes `native` alone")


def stdout_tail(scratch: Path | None) -> str:
    return channel_tail(scratch, "process")


def channel_tail(scratch: Path | None, channel: str) -> str:
    """The last of what ONE channel holds. It takes the CHANNEL and not a file name, so the
    two names stay in `mame_files` where the reader family already reads them from."""
    log = files.log_path(scratch, channel) if scratch else None
    if log is None or not log.exists():
        return ""
    return log.read_text(errors="replace")[-log_marks.TAIL_CHARS:]


def _alive_fields(judged: Judged, keep: bool = True) -> dict[str, Any]:
    """What a refusal of the wait for the stub carries while MAME is alive: the process and its
    port as the wait ended, what it printed, and, when `keep`, a copy of that kept where it
    survives the scratch (a launch `start` relaunches keeps none, or its copies would push the
    kept ones out). The failed start then kills it."""
    assert STATE.proc is not None and STATE.scratch is not None
    return {"exit_code": unavailable("MAME is still running"), "pid": STATE.proc.pid,
            "stub_port": judged.port, "alive": True,
            "stdout_tail": stdout_tail(STATE.scratch),
            **(keep_failed_start(STATE.scratch, judged.system) if keep else {})}


def _no_answer(judged: Judged, cause: object, attempts: list[dict[str, Any]]) -> st.Invalid:
    """The refusal of a live MAME whose stub never answered within the wait, with every dial
    of it and what the process printed."""
    return st.Invalid("session_broken",
                      f"the gdbstub did not answer within {judged.wait} s: {cause}",
                      dial_attempts=attempts, **_alive_fields(judged))


def _exit_code(error: BaseException, progress: mprogress.Progress) -> int | None:
    """MAME's exit code, or None while it runs. A channel MAME closed (a first byte lost, a
    connection cut) is given `CLOSED_EXIT_WAIT_S` to become its exit, since a dying process
    closes its sockets before it can be reaped."""
    assert STATE.proc is not None
    code = STATE.proc.poll()
    if code is None and isinstance(error, (gs.DialFailed, gs.ConnectionFailed)):
        code = st.wait_exit(STATE.proc, CLOSED_EXIT_WAIT_S, progress,
                            "start: MAME closed the gdbstub's connection")
    return code


# HOW MANY COPIES OF A FAILED START'S OUTPUT ARE KEPT: enough to hold a run of failures
# someone is chasing, bounded so the folder cannot grow for ever.
FAILED_STARTS_KEPT = 20


def keep_failed_start(scratch: Path, system: str) -> dict[str, Any]:
    """Copy the scratch's `stdout.log` to `<state>/failed-starts/<utc>-<system>.log`, keep the
    newest `FAILED_STARTS_KEPT` of the copies this writes, and answer `stdout_kept`, the copy's
    path. The UTC stamp leads the name, so the names sort as the starts happened, and only
    names in that shape are rotated. A copy that cannot be made is `stdout_kept` unavailable,
    its `why` saying why: the refusal it rides on is the news, not this."""
    folder = dec.state_home() / "failed-starts"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    kept = folder / f"{stamp}-{system}.log"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files.log_path(scratch, "process"), kept)
        for old in sorted(folder.glob("[0-9]*T*Z-*.log"))[:-FAILED_STARTS_KEPT]:
            old.unlink()
    except OSError as e:
        return {"stdout_kept": unavailable(str(e))}
    return {"stdout_kept": str(kept)}


def _await_banner(judged: Judged, clock: mprogress.Ticker, request_s: float) -> None:
    """Wait until MAME's output carries `DEBUGGER_BANNER` or the process is gone, leaving the
    handshake `request_s` of the boot's bound: past that the handshake asks all the same and is
    judged as before, so the start ends when it always did."""
    assert STATE.scratch is not None and STATE.proc is not None
    log = files.log_path(STATE.scratch, "process")
    banner = DEBUGGER_BANNER.encode()
    while not clock.expired() and clock.left() > request_s and STATE.proc.poll() is None:
        if log.exists() and banner in log.read_bytes():
            return
        clock.tick("start {system}: waiting for MAME's debugger, {elapsed:.0f}s of {wait:g}",
                   system=judged.system, wait=judged.wait)
        time.sleep(BOOT_POLL_S)


def boot(judged: Judged, progress: mprogress.Progress = mprogress.no_progress,
         last_launch: bool = True
         ) -> tuple[dict[str, str], str, list[str]]:
    """The scratch, the process and the connected stub, and the ROM check on it; what was
    handed to the driver comes back (`env`, the harness, the argv) for the reply. The caller
    holds the guard: anything raised here leaves nothing behind.

    MAME writes `cfg/` and `nvram/` into its working directory. Running from the server's own
    directory, ONE project's EEPROM and configuration ended up INSIDE the shared tool, where
    the next project to use it inherited them. Each session gets its own and takes them along
    when it dies, unless the caller names a `state_dir`, in which case keeping them IS the
    point. The scratch's directories are created here rather than left to MAME, so a missing
    one is this server's mistake and not a silent fallback."""
    assert STATE.scratch is not None
    (STATE.scratch / "snap").mkdir()
    if not judged.state_dir:
        for sub in ("cfg", "nvram"):
            (STATE.scratch / sub).mkdir()
    if judged.cfg is not None:
        # THE COPY IS WHAT MAME READS: `-cfg_directory` names `<state>/cfg`, and MAME reads
        # `<system>.cfg` there; the repo's file is never the one on the command line, so
        # MAME's rewrite on exit lands on the copy and the source stays the repo's.
        installed = Path(judged.state_dir or STATE.scratch) / "cfg" / f"{judged.system}.cfg"
        # A persistent `state_dir` may hold the copy an earlier session left, canonised by
        # MAME on its way out: `cfg=` asks for the repo's file, so it is installed, and the
        # reply says a file was replaced rather than doing it in silence.
        replaced = installed.exists()
        shutil.copyfile(judged.cfg, installed)
        STATE.cfg = {"source": judged.cfg, "installed": installed, "replaced": replaced}
    given = dict(judged.env)
    if judged.throttle_from_frame:
        given[THROTTLE_FRAME_VAR] = str(judged.throttle_from_frame)
    # THE SERVER ALWAYS WRITES THE SCRIPT NOW, because the inventory is gathered on every
    # start: the caller's own harness is chained inside it rather than reaching the command
    # line on its own, and `boot_lua_path` in the reply names the composed script.
    harness = boot_harness(STATE.scratch, judged.boot_lua, judged.throttle_from_frame,
                           judged.presence)
    cmd = build_command(judged.binary, judged.system, judged.rompath, judged.port, judged.flags,
                        str(STATE.scratch), judged.inipath, harness, judged.state_dir,
                        judged.view)
    # stdout and stderr land in one file in the scratch, named in the reply: sent to DEVNULL,
    # a driver's own complaints and the OSD's would be lost with the process.
    STATE.stdout_log = open(files.log_path(STATE.scratch, "process"),  # noqa: SIM115 (kill closes)
                            "wb")
    # stdin is the Lua console's (`-console` above): a PIPE this server writes lines into.
    # Left connected to nothing, the console reads end-of-file at once and stops for good.
    STATE.proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=STATE.stdout_log, stderr=subprocess.STDOUT,
        env=launch_environment(given, judged.background), cwd=STATE.scratch,
    )
    if (ledger := live_host.EmulatorLedger.from_environment()) is not None:
        ledger.record(STATE.proc.pid, cmd[0])
    STATE.guard = guardian.spawn(STATE.proc, PROCESS_NAME)
    # THE LONGEST WAIT A SESSION MAKES, and the one the owner watches: the boot of a whole
    # arcade board until its gdbstub listens and its debugger's banner is out. It reports where it
    # is, like every bounded wait.
    clock = mprogress.Ticker(judged.wait, progress)
    last: Exception | None = None
    died: int | None = None
    attempts: list[dict[str, Any]] = []
    # THE STUB IS PROVED TO BE THIS LAUNCH'S MAME around the dial (`mame_stub_owner`). The
    # accept is waited for as long as the handshake would wait, never less than one request.
    proof = owner.StubOwner(STATE.proc.pid, judged.port,
                            time.monotonic() + max(clock.left(), gs.REQUEST_TIMEOUT_S),
                            STATE.machine_alive)
    while not clock.expired():
        try:
            STATE.ses = gs.Session(port=judged.port, owner=proof)
            STATE.ses.dial()
            break
        except owner.StubNotOurs as e:
            STATE.ses = None
            raise failures.PortServed(e, judged.picked, **_alive_fields(judged)) from None
        except owner.StubUnproved as e:
            STATE.ses = None
            raise st.Invalid("host_failed", f"{e}. The launched MAME is killed",
                             **_alive_fields(judged)) from None
        except owner.StubNotAccepted as e:
            STATE.ses = None
            raise _no_answer(judged, e, attempts) from None
        except (OSError, gs.DialFailed) as e:
            last = e
            STATE.ses = None
            failures.fold_attempt(attempts, clock.elapsed(), e)
            # A PROCESS THAT EXITED WILL NEVER ANSWER, and it is known at once: the bound is
            # sized for a whole board's boot, and waiting it out buys nothing.
            died = _exit_code(e, progress)
            if died is not None:
                break
            if isinstance(e, gs.DialFailed):
                # THE ONE CONNECTION MAME SERVES WAS MADE AND IS GONE: its listener closed on
                # accepting it, so every later dial would be refused for the rest of the wait.
                raise st.Invalid("session_broken",
                                 f"the gdbstub's connection failed as it was made: {e}. "
                                 f"{failures.ONE_CONNECTION}", dial_attempts=attempts,
                                 **_alive_fields(judged)) from None
            clock.tick("start {system}: waiting for the gdbstub on port {port}, {elapsed:.0f}s "
                       "of {wait:g}", system=judged.system, port=judged.port, wait=judged.wait)
            time.sleep(BOOT_POLL_S)
    if STATE.ses is not None:
        _await_banner(judged, clock, STATE.ses.timeout)
        # THE CONNECTION MADE IS THE ONLY ONE THERE WILL BE (`Session.dial`): the handshake waits
        # on it for what is left of the boot's bound rather than dialling again, which MAME would
        # refuse for the rest of the session.
        try:
            STATE.ses.handshake(max(clock.left(), STATE.ses.timeout))
        except (OSError, gs.SessionError) as e:
            # HUNG UP FROM HERE, while MAME still holds its side: the side that closes first
            # keeps the TIME_WAIT, and on MAME's side that is the stub's port, which a relaunch
            # on the caller's `stub_port` would then find taken.
            STATE.ses.close()
            STATE.ses = None
            # A DEATH WHILE THE HANDSHAKE WAITED is a death before the stub answered, judged
            # as any death, and not a stub that sat on its connection.
            if (died := _exit_code(e, progress)) is not None:
                raise failures.death_refusal(died, clock.elapsed(),
                                             stdout_tail(STATE.scratch)) from None
            if isinstance(e, failures.NOT_READY_ERRORS):
                raise failures.StubNotReady(e, clock.elapsed(),
                                            **_alive_fields(judged, keep=last_launch)) from None
            phase = getattr(e, "phase", gs.SessionError.phase)
            raise st.Invalid("session_broken",
                             f"{failures.handshake_failed(phase, clock.elapsed(), e)}. "
                             f"{failures.ONE_CONNECTION}", phase=phase,
                             **_alive_fields(judged)) from None
    if STATE.ses is None and died is None:
        # A DEATH IN THE LAST SLEEP: the loop can end on the clock and not on a poll, and a
        # process that died meanwhile would be reported as a stub that never answered.
        died = STATE.proc.poll()
    if STATE.ses is None:
        # THE DIAGNOSIS TRAVELS WITH THE REFUSAL: `start` kills the session and deletes the
        # scratch on failure, so what MAME printed before it died (a plugin it could not
        # find, a ROM set it refused, a fatal error) would otherwise be gone with it.
        # WHICH OF TWO DIAGNOSES, because they send a reader to different places: a process
        # that DIED is read in its own output, a stub that never ANSWERED in the port and the
        # boot's length.
        if died is not None:
            raise failures.death_refusal(died, clock.elapsed(), stdout_tail(STATE.scratch))
        # A LIVE PROCESS WHOSE STUB NEVER LISTENED: what it printed rides on the refusal.
        raise _no_answer(judged, last, attempts)
    try:
        STATE.ses.self_check(judged.ref.read_bytes(), judged.ref_addr, base=judged.ref_base,
                             thread=1)
    except gs.Mismatch as e:
        raise st.Invalid("readback_refused", f"{e} The session is closed.") from e
    if judged.cfg is not None:
        # THE CONTROL AFTER THE BOOT: MAME says on its stderr when it refused the file and
        # loaded its defaults; a session playing on those while the reply names the
        # cabinet's cfg is the lie this stops, and the caller's guard closes the session.
        refused = cfg_parse_error(STATE.scratch)
        if refused is not None:
            raise st.Invalid("bad_argument",
                f"MAME did not read {judged.cfg}: its `process` channel "
                f"({files.LOG_FILES['process']}) says `{refused}`, so the machine booted on "
                "the default inputs; the session is closed",
                stdout_path=str(files.log_path(STATE.scratch, "process")))
    return given, harness, cmd


def start(binary: str, system: str, rompath: str, reference_rom: str, symbols: syms.Given,
          reference_addr: str, inipath: str, wait: float, shared: bool, boot_lua: str,
          env: dict[str, str] | None, bases: syms.Bases | None, reference_base: str,
          display: str, port: int, state_dir: str,
          throttle_from_frame: int = 0, types: syms.Types = "", cfg: str = "",
          background: bool | None = None, *, presence: bool, view: str = "",
          progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `start` tool: one launch, and again for a `failures.LaunchFailed` that
    says so, up to `START_RETRIES_MAX` more times. Each relaunch is a WHOLE fresh launch,
    as if the caller had called `start` again: nothing of a failed attempt is reused but its
    evidence, which every reply carries as `start_retries`, refusals included, so an empty
    list is an answer and never a missing field."""
    # `~` EXPANDED ONCE, HERE, where every path is handed on as text (MAME's command line, a
    # `;`-split list, a mapping's values), so no later reader meets it unexpanded.
    binary, rompath, reference_rom, boot_lua, cfg, state_dir = (
        judges.expanded(v) for v in (binary, rompath, reference_rom, boot_lua, cfg, state_dir))
    inipath = ";".join(judges.expanded(p) for p in inipath.split(";")) if inipath else inipath
    symbols = syms.expanded(symbols)
    types = syms.expanded(types)
    retries: list[dict[str, Any]] = []
    try:
        while True:
            try:
                return _launch(binary, system, rompath, reference_rom, symbols, reference_addr,
                               inipath, wait, shared, boot_lua, env, bases, reference_base,
                               display, port, state_dir, throttle_from_frame, types, cfg,
                               background, presence, retries, progress, view)
            except failures.LaunchFailed as failed:
                if not failed.relaunch(port_picked=not port) or len(retries) == START_RETRIES_MAX:
                    raise
                retries.append(failed.evidence())
                progress(len(retries), START_RETRIES_MAX,
                         f"start {system}: {failed.what}; relaunching after {failed.kind} "
                         f"({len(retries)} of {START_RETRIES_MAX})")
    except st.Invalid as refused:
        refused.fields["start_retries"] = retries
        raise
    except gs.SessionError as e:
        # THE BOOT'S CHANNEL FAILED after the stub answered: `_launch` has already killed the
        # machine, so there is no session left to latch, and the reply says so in the shape
        # every `start` reply has, `start_retries` included.
        raise st.Invalid("session_broken", f"the boot's channel failed: {e}. The session is "
                         "closed; `start` again", start_retries=retries) from e


def _launch(binary: str, system: str, rompath: str, reference_rom: str, symbols: syms.Given,
            reference_addr: str, inipath: str, wait: float, shared: bool, boot_lua: str,
            env: dict[str, str] | None, bases: syms.Bases | None, reference_base: str,
            display: str, port: int, state_dir: str, throttle_from_frame: int,
            types: syms.Types, cfg: str, background: bool | None, presence: bool,
            retries: list[dict[str, Any]], progress: mprogress.Progress,
            view: str = "") -> dict[str, Any]:
    """ONE launch: judge, boot under one guard, re-arm, park, reply."""
    # ONE MACHINE PER SERVER, and ending it is the caller's act: a start over a live session
    # that killed it and booted again in silence would let a second `start` typed by mistake
    # throw away a session somebody was measuring on. It refuses and asks for `close`.
    if STATE.ses is not None and STATE.proc is not None and STATE.proc.poll() is None:
        st.refuse_broken(STATE.ses)
        raise st.Invalid("session_live",
            f"a session is live ({STATE.system}, pid {STATE.proc.pid}), and this server holds "
            "one machine: `close` it first, then `start`"
        )
    # Whatever is left here is a process with no session to write state for (a live one was
    # refused above), so it is not given the grace a `close` gives.
    STATE.kill(progress, grace=False)
    # THE BINARY LADDER is climbed after the session gate, so a live or broken session answers
    # as such whatever executable `binary` or `MAME_BINARY` names; a relaunch climbs it again.
    resolved = binaries.resolve(binary)
    binary = resolved.path
    judged = judge(binary=binary, system=system, rompath=rompath, reference_rom=reference_rom,
                   symbols=symbols, reference_addr=reference_addr, inipath=inipath, wait=wait,
                   shared=shared, boot_lua=boot_lua, env=env, bases=bases,
                   reference_base=reference_base, display=display, port=port,
                   state_dir=state_dir, throttle_from_frame=throttle_from_frame, types=types,
                   cfg=cfg, background=background, presence=presence,
                   binary_origin=resolved.origin, view=view)
    # FROM THE SCRATCH ON, EVERYTHING SITS UNDER ONE GUARD. If the ROM check fails, the session
    # is KILLED: an error merely propagated leaves the lying session alive and reachable, and
    # the next call measures on it quite happily. A guarantee that leaves
    # standing what it has just declared invalid is not a guarantee. And so is everything else
    # that can raise before this returns: a refusal raised past the guard would leave the
    # emulator running with the server as its parent, reachable by nobody and reaped by
    # nothing. The guard starts at the scratch
    # itself, so a `Popen` that raises, or a stub that never answers, leaves no directory
    # behind either. A start that did not start owns nothing.
    STATE.scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX))
    STATE.state_dir = state_dir
    STATE.port = judged.port
    try:
        try:
            # Asked after `judge`, so a refused input spawns nothing, `-version` included, and
            # inside the guard, so whatever escapes it still collects the `-listxml` query. It
            # runs as the boot will (the launch's environment), and BESIDE the boot, as the
            # `-listxml` query does: inside the seconds the boot spends waiting for the stub,
            # under a bound no longer than them, so a build that hangs on it costs nothing.
            version = _VERSIONS.submit(
                binaries.facts, resolved,
                launch_environment(dict(judged.env), judged.background),
                min(binaries.VERSION_TIMEOUT_S, judged.wait))
            given, harness, _cmd = boot(judged, progress,
                                        last_launch=len(retries) == START_RETRIES_MAX)
        except st.Invalid:
            # THE CAUSE OUTRANKS THE SYMPTOM. A system this build does not carry cannot boot,
            # and what the boot reports is that the gdbstub never answered, which is true and
            # useless. The query put before the boot holds the real diagnosis in MAME's own
            # words, so it is collected HERE, first: it raises the refusal that names the
            # caller's mistake, and only if it has nothing to say does the boot's own failure
            # stand. This is what pays for asking the question early instead of waiting for it.
            collect(judged)
            raise
        except BaseException:
            # ANYTHING ELSE HAS NO DIAGNOSIS TO PREFER: the query is killed and reaped, and
            # the original exception propagates as the bug it is. Only the refusal above
            # collects, because only there can MAME's own words outrank the symptom.
            discard(judged)
            raise
        # COLLECTED THE MOMENT THE BOOT IS OVER, whether or not the cache is built yet. It
        # finished long ago, inside those seconds. Reading it here rather than after the park
        # leaves NO window in which a raise could strand the query with this server as its
        # parent, reachable by nobody: the guarantee that a start owns nothing when it fails
        # is then structural, instead of resting on a cleanup somebody has to remember.
        listed = collect(judged)
        binary_facts = version.result()
        assert STATE.ses is not None
        STATE.system = system
        STATE.maps.started()
        # THE ONE PATH'S TABLE IS THE FIRST CPU'S: the stub's thread 1, else the first cpu
        # `cpulist` lists, else the first `-listxml` names.
        STATE.first_cpu = (cpus.stub_cpu(STATE.ses)
                           or next((row["tag"] for row in listed[0]["cpus"]), None))
        STATE.tables = judged.tables.keyed(STATE.first_cpu)
        STATE.session_origin = STATE.origin()
        # ONE BUILD PER CPU: each cpu's raw addresses are judged against its own table.
        first = STATE.first_cpu
        machine_cpus = [row["tag"] for row in listed[0]["cpus"]] or cpus.cpu_list(STATE.ses)
        STATE.fingerprints = {
            cpu: syms.fingerprint(system, judged.ref, judged.tables.path_of(cpu, first),
                                  None if cpu == first else cpu)
            for cpu in dict.fromkeys([first, *machine_cpus])}
        judged.declarations["fingerprint"] = STATE.fingerprint()
        STATE.store = judged.store
        STATE.reference = (judged.ref, judged.ref_addr, judged.ref_base)
        # THE INVENTORY IS READ OFF THE SCRATCH, not off the machine: the boot harness wrote
        # it during the boot, so this costs the machine nothing and moves no pc, and it comes
        # before the re-arm, which judges each condition against its cpu's register names here.
        # What it could not gather is a note inside the answer, never a reason to fail a start.
        STATE.machine_map = machine.cache(STATE.scratch, listed)
        STATE.view = view_shown(judged.view, STATE.machine_map)
        # EACH CPU'S BYTE ORDER IS MAME'S, read off that inventory, before the re-arm and the
        # park below decode anything.
        STATE.ses.know_endianness(cpus.program_endianness(STATE.ses, STATE.machine_map,
                                                          STATE.first_cpu))
        # PRESENCE OPENS BEFORE THE CONSOLE IS FIRST ASKED ANYTHING: a stopped MAME repaints at
        # each console command, so the ones this start sends from here on draw the edge, and the
        # window shows it by the time the reply says it is drawn.
        if judged.presence:
            STATE.presence = scry_presence.Presence.open(
                mpresence.FileAdapter(STATE.scratch, st.LOCK, STATE.repaintable,
                                      transport.pending_lines), mpresence.DRIVING_TOOLS)
        # WHICH NAME THE FRAME COUNTER ANSWERS TO, asked before the re-arm and the park, both
        # of which survey the frame: a board with no screen device has none to survey.
        STATE.frame_symbol = read.probe_frame_symbol(STATE.ses)
        # WHAT THE STORE HELD COMES BACK: re-resolved against this table and re-armed, before
        # the park's survey so the first stop already carries every watch evaluated.
        judged.declarations["rearm"] = rearming.rearm_breakpoints_and_watches(STATE.ses)
        regpoints.rearm(STATE.ses, judged.declarations["rearm"])
        judged.declarations["comments"] = comments.rearm(STATE.ses, STATE.scratch)
        # The park at the debugger is stop 1: what the readers name until something moves it.
        park = running.record_park(STATE.ses, STATE.scratch)
        STATE.boot_pc = int(park["pc"], 16)      # what `reset` reads its pc back against
        started = menvelope.envelope({
            "system": system,
            **binary_facts,
            "pid": STATE.proc.pid if STATE.proc else None,
            "stub_port": judged.port,
            "scratch_dir": str(STATE.scratch),
            "state_dir": state_dir,
            "cfg": cfg_report(),
            "debugger": debugger_report(),
            **channels(),
            "rom_check": "OK",
            **symbols_fields(),
            "registers": STATE.ses.layout(1).register_names,
            "pc": park["pc"],
            "frame": st.frame_shown(park["frame"]),
            **read.frame_fields(),
            # What was handed to the driver, so a watched run can say which variant it is.
            "env": given,
            "display": judged.display,
            "view": STATE.view,
            "views": views_shown(STATE.machine_map),
            "background": judged.background,
            "flags": judged.flags,
            "throttle_from_frame": throttle_from_frame,
            "boot_lua_path": harness,
            "presence": STATE.presence_shown(),
            # THE MACHINE'S SHAPE AS COUNTS, never as rows: `start` already carries a lot,
            # and a board's whole inventory riding on every one of them would be paid for by
            # every caller whether or not they wanted it. `machine_map` serves the rows, free.
            "machine": {name: len(STATE.machine_map[name]) for name in machine.SECTIONS},
            "declarations": judged.declarations,
            "start_retries": list(retries),
        })
        idle.IDLE.clear_note()
    except Exception:
        # A START THAT FAILED IS DISCARDED, not closed: nothing it holds is worth the grace a
        # `close` waits for MAME to write its state in.
        STATE.kill(progress, grace=False)
        raise
    return started
