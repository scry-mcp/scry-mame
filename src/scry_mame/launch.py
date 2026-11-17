"""The body of `start`: MAME's command line, window, port and boot."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.parsers import expat

from scry_core import (
    app_launch,
    file_names,
    guardian,
    judges,
    live_host,
    log_marks,
    project_store,
    window_size,
    window_words,
)
from scry_core import presence as scry_presence
from scry_core import progress as mprogress
from scry_core import vocabulary as vocab
from scry_core import window as core_window
from scry_core.judges import NumberArg
from scry_core.reply_contract import unavailable

from scry_mame import binary as binaries
from scry_mame import boot_failures as failures
from scry_mame import (
    comments,
    cpus,
    files,
    idle,
    inputs,
    lua_source,
    machine,
    read,
    regpoints,
    running,
    transport,
)
from scry_mame import declarations as dec
from scry_mame import envelope as menvelope
from scry_mame import gdb_session as gs
from scry_mame import presence as mpresence
from scry_mame import rearm as rearming
from scry_mame import state as st
from scry_mame import stub_owner as owner
from scry_mame import symbols as syms
from scry_mame.state import STATE

# The mark a live session carries in its argv, which other repos' kill paths exclude on: they
# kill by binary path and this server spawns the same binary. Changing it changes every one.
SCRATCH_PREFIX = "mame-mcp-"

BOOT_POLL_S = 0.3
# Printed when the debugger console is built. A stub without the thread patch caches an empty
# target description if asked before the first stop, and its port accepts long before that, so
# the handshake waits for this line. MAME's source does not order the line against the stop; an
# empty description anyway is the `NoRegisters` a relaunch answers.
DEBUGGER_BANNER = "Currently targeting "
START_RETRIES_MAX = 2
# A dying process closes its sockets before it can be reaped; that closed channel is its death.
CLOSED_EXIT_WAIT_S = 1.0

PROCESS_NAME = "scry-mame"
GUARDIAN_NAME = guardian.name_of(PROCESS_NAME)

# The throttle on arrival is a boot harness: MAME's debugger console has no throttle command and
# the stub speaks only the debugger, so only Lua (`manager.machine.video.throttled`) can switch
# it, and at launch the Lua that runs is the autoboot script. `-nothrottle` makes the trip fast
# and the harness lifts the throttle at the target frame, logging the mark to `error.log` for
# `log_wait`.
THROTTLE_FRAME_VAR = "MAME_MCP_THROTTLE_FRAME"
THROTTLE_MARK = "MAME_MCP throttled from frame"


def check_rom_check(reference_rom: str, reference_addr: NumberArg = 0,
                    reference_base: NumberArg = 0, **_: Any) -> None:
    """`rom_check`'s machine-independent half: two addresses and a readable file."""
    inputs.address_arg("reference_addr", reference_addr)
    inputs.address_arg("reference_base", reference_base)
    reference_window_in_image(reference_rom_file(reference_rom), reference_addr, reference_base)


def reference_window_in_image(ref: Path, reference_addr: NumberArg,
                              reference_base: NumberArg) -> tuple[int, int]:
    """The known-answer read's address and base, parsed and held inside the image, or the refusal.

    The image's size is the file's, so an address it does not cover is the caller's argument and
    needs no machine."""
    addr = inputs.address_arg("reference_addr", reference_addr)
    base = inputs.address_arg("reference_base", reference_base)
    try:
        gs.reference_window(ref.stat().st_size, addr, 16, base)
    except gs.SessionError as e:
        raise st.Invalid("bad_argument", str(e)) from None
    return addr, base


def reference_rom_file(reference_rom: str) -> Path:
    """The reference ROM as a readable path, or the refusal."""
    ref = inputs.input_file("reference_rom", reference_rom, "reference ROM")
    if not os.access(ref, os.R_OK):
        raise st.Invalid("bad_argument", f"the reference ROM {ref} is not readable")
    return ref


def native_size(screens: list[dict[str, Any]]) -> tuple[int, int] | None:
    """The first screen's size as the player sees it (a rotated board swaps its sides), or None
    when `-listxml` gave none."""
    if not screens or screens[0].get("width", 0) <= 0 or screens[0].get("height", 0) <= 0:
        return None
    w, h = screens[0]["width"], screens[0]["height"]
    return (h, w) if screens[0].get("rotation") in (90, 270) else (w, h)


def fitted_request(asked: core_window.WindowRequest | None,
                   screens: list[dict[str, Any]]) -> core_window.WindowRequest | None:
    """`asked` with the largest whole multiple of the screen whose window fits the display's usable
    area as its size, marked as the server's own choice; unchanged where a size was stated, the
    window fills the display, or the screen or the usable area is not known."""
    native = native_size(screens)
    if asked is None or not native:
        return asked
    return core_window.fit_size(
        asked, lambda usable, scale: window_size.integer_fit(native, usable, scale, sys.platform),
        height_free=window_size.height_free("mame", sys.platform))


def window_flags(asked: core_window.WindowRequest | None,
                 screens: list[dict[str, Any]]) -> list[str]:
    """The window's flags: small and flat out for a run nobody watches; for a watched one the
    display asked for, in a window of the stated or fitted size, else MAME's own."""
    if asked is None:
        return ["-window", "-nomaximize", "-resolution", "320x240", "-nothrottle"]
    # `-nounevenstretch` makes MAME scale by whole pixels: the whole-multiple window is then a
    # whole-multiple picture, never a blurred fractional stretch, even where the view's aspect
    # (4:3) differs from the screen's.
    return [*window_words.mame(fitted_request(asked, screens) or asked), "-nounevenstretch"]


def scaled_note(asked: core_window.WindowRequest | None,
                screens: list[dict[str, Any]]) -> str | None:
    """Says so when a stated size is not a whole multiple of the screen: MAME then scales the
    picture by whole pixels, unevenly between the axes, at its view's aspect inside the window."""
    native = native_size(screens)
    if asked is None or asked.size is None or asked.fitted or native is None:
        return None
    if asked.size[0] % native[0] == 0 and asked.size[1] % native[1] == 0 \
            and asked.size[0] // native[0] == asked.size[1] // native[1]:
        return None
    return (f"`size` {asked.size[0]}x{asked.size[1]} is not a whole multiple of this machine's "
            f"{native[0]}x{native[1]} screen: MAME scales the picture by whole pixels, "
            "unevenly between the axes")


def port_is_free(port: int) -> bool:
    """Whether the gdbstub could listen on `port` (`owner.bind_probe`)."""
    return owner.bind_probe(port) is not None


def free_port() -> int:
    """A port the kernel hands out as free, never a walk from a fixed number (two servers would
    land on it together). Sharing one stays possible; the dial's proof makes it harmless."""
    chosen = owner.bind_probe(0)
    if chosen is None:
        raise st.Invalid("host_failed", "the kernel would not hand out a free port for the "
                         "gdbstub")
    return chosen


DEBUGGER = "gdbstub"


def debugger_report() -> dict[str, str]:
    """What `start` and `status` say about the debugger, so a frame's difference from a golden is
    not read as a regression. The note blames the method, not `-debug`."""
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
    """The whole MAME command line, pure so a flag's arrival is testable without a launch.

    `scratch/snap` always rides on the snapshot directory flag: that is the `SCRATCH_PREFIX`
    mark. `cfg/` and `nvram/` go under `state_dir` when named, else the scratch. Both are
    absolute because MAME resolves a relative one against its working directory, the scratch.
    """
    state = state_dir or scratch
    # `-log` sends `logerror` to `error.log` in the scratch. `-debuglog` sends the console's
    # output to `debug.log`, the one place a watchpoint stop names the value and the writer's pc.
    cmd = [binary, system, "-rompath", rompath, "-skip_gameinfo", "-log", "-debuglog",
           "-debug", "-debugger", DEBUGGER, "-debugger_port", str(port),
           "-snapshot_directory", str(Path(scratch) / "snap"),
           # A running MAME cannot switch its capture view; `native` is the screen alone.
           "-snapview", view or "native",
           "-cfg_directory", str(Path(state) / "cfg"),
           "-nvram_directory", str(Path(state) / "nvram"),
           # Pinned: an ini given through `inipath` may rename the subfolder, and
           # `state_write(method="save")` looks for the file here.
           "-state_directory", str(Path(state) / "sta"), "-statename", "%g",
           # In the scratch so the file dies with the session: a stale one under `state_dir`
           # would show a deleted comment to the next plain MAME, which writes nothing once it
           # holds none.
           "-comment_directory", str(Path(scratch) / "comments"),
           "-console"]
    plugins = plugins_dir(binary)
    if plugins is not None:
        cmd += ["-pluginspath", str(plugins)]
    if inipath:
        cmd += ["-inipath", inipath]
    if boot_lua:
        cmd += ["-autoboot_script", boot_lua, "-autoboot_delay", "0"]
    return cmd + flags


def cfg_report() -> dict[str, Any]:
    """The installed cfg, unavailable when MAME runs on its defaults."""
    if STATE.cfg is None:
        return unavailable(st.NO_CFG_WHY)
    return {"source_path": str(STATE.cfg["source"]),
            "installed_path": str(STATE.cfg["installed"]),
            "replaced": bool(STATE.cfg["replaced"])}


def symbols_fields() -> dict[str, Any]:
    """What `start` answers about the loaded tables; a flat table counts in `symbols_total` only."""
    first = STATE.table()
    return {"symbols_total": len(first.table), "symbols_typed": len(first.types),
            "symbols_format": first.format, "symbols_by_class": first.by_class,
            "symbols_by_cpu": {cpu: len(t.table) for cpu, t in STATE.tables.items()
                               if cpu is not None}}


def channels() -> dict[str, str]:
    """Where the session's two output channels are."""
    assert STATE.scratch is not None
    return {
        "errorlog_path": str(files.log_path(STATE.scratch, "emulator")),
        "stdout_path": str(files.log_path(STATE.scratch, "process")),
    }



def judge_background(background: bool | None, shared: bool, env: dict[str, str] | None) -> bool:
    """Whether MAME launches behind: `background` when given, else unless shared.

    `env` carrying the hint is refused: two spellings of one switch let the reply name one while
    the process obeys the other."""
    if env and core_window.BACKGROUND_VAR in env:
        raise st.Invalid("bad_argument",
            f"`env` sets {core_window.BACKGROUND_VAR}, which is what `background` sets: pass "
            "`background=True` or `background=False` instead")
    return core_window.judge_background(background, shared)


#: What the console's stdin holds unread, as a POSIX pipe does: lines queue there while the machine
#: is stopped, and a full pipe blocks the writer with no bound. Windows' default is far smaller.
CONSOLE_PIPE_BYTES = 65536

#: The console's stdin when the emulator runs as an app: a FIFO `open -i` connects to it.
CONSOLE_FIFO = "console.fifo"


def console_popen(cmd: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
    """`cmd` started with a writable stdin of `CONSOLE_PIPE_BYTES`."""
    if sys.platform == "win32":
        import _winapi
        import msvcrt
        read, write = _winapi.CreatePipe(None, CONSOLE_PIPE_BYTES)
        read_fd = msvcrt.open_osfhandle(read, os.O_RDONLY)
        try:
            proc = subprocess.Popen(cmd, stdin=read_fd, **kwargs)
        except BaseException:
            _winapi.CloseHandle(write)
            raise
        finally:
            os.close(read_fd)
        proc.stdin = open(msvcrt.open_osfhandle(write, 0), "wb")  # noqa: SIM115 (the proc's)
        return proc
    else:
        return subprocess.Popen(cmd, stdin=subprocess.PIPE, **kwargs)


def boot_harness(scratch: Path, boot_lua: str, throttle_from_frame: int,
                 presence: bool = False) -> str:
    """Write the one `-autoboot_script` (MAME takes a single one) and return its path.

    Inventory first, inside its own `pcall` so an unfamiliar board cannot stop the rest, then the
    throttle, the presence drawer, and the caller's harness through `dofile`.
    """
    text = machine.harness(scratch / machine.DUMP_NAME)
    if throttle_from_frame:
        text += lua_source.render("autoboot-throttle", var=THROTTLE_FRAME_VAR, mark=THROTTLE_MARK)
    if presence:
        text += mpresence.drawer(scratch)
    if boot_lua:
        text += f"dofile({transport.lua_string(str(Path(boot_lua).resolve()))})\n"
    path = scratch / "boot.lua"
    path.write_text(text, encoding="utf-8")
    return str(path)


@dataclass(frozen=True, kw_only=True)
class Judged:
    """What `start` decided from its arguments before anything exists, plus the launch inputs.

    `judge` refuses with nothing to clean up. Built by keyword only: most fields are strings, and
    a swap would type-check."""

    flags: list[str]
    port: int
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
    listxml: machine.Asked
    cfg: Path | None = None       # None for MAME's defaults
    listed: machine.Listed | None = None
    background: bool = False
    presence: bool = False
    window: core_window.WindowRequest | None = None
    scaled: str | None = None     # a stated size MAME scales, said in the reply
    picked: bool = False          # the port is this server's pick
    view: str = ""                # empty is MAME's `native`
    #: The `.app` the caller named instead of an executable; empty goes through `Popen`.
    bundle: str = ""


def collect(judged: Judged) -> machine.Listed:
    """The `-listxml` answer, waited for in `judge` or collected now."""
    if judged.listed is not None:
        return judged.listed
    return machine.listxml(judged.listxml, judged.binary, judged.system, judged.wait)


def discard(judged: Judged) -> None:
    """Kill and reap the unread `-listxml` query, so a raised boot strands no child."""
    proc = judged.listxml[0]
    if proc is None or judged.listed is not None:
        return
    if proc.poll() is None:
        proc.kill()
    proc.communicate()


# Where a MAME keeps its console plugin, relative to the resolved binary (a packager's symlink
# points elsewhere); MAME's own default is relative to the scratch and reaches neither.
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


# Printed when MAME refuses a cfg and loads its defaults (a `--` in a comment does it). It goes
# to stderr via `osd_printf_warning`, not `error.log`, so the reader opens `stdout.log`. It is
# there by the time the stub answers: settings load before the soft reset that opens the socket.
CFG_PARSE_ERROR = "Error parsing XML configuration file"
# Without these a `<port>` parses, binds nothing and is overwritten on exit, in silence.
PORT_ATTRS = ("tag", "mask", "defvalue")


def judge_folders(name: str, value: str) -> list[tuple[str, Path]]:
    """Judge a `;`-separated list of absolute directories (`-rompath`, `-inipath`): each folder
    with the name a refusal gives it, `name[i]` in a list of several."""
    parts = value.split(";") if value else []
    folders: list[tuple[str, Path]] = []
    for i, part in enumerate(parts):
        if not part:
            raise st.Invalid("bad_argument",
                             f"{name}={value!r} holds an empty element: it is a `;`-separated "
                             "list of absolute directories")
        named = name if len(parts) == 1 else f"{name}[{i}]"
        folders.append((named, inputs.absolute(named, part)))
    return folders


def judge_cfg(cfg: str, system: str) -> Path:
    """Judge the `.cfg` before the boot for what MAME meets in silence: a `<port>` missing an
    attribute, XML its parser refuses, or another system's file. Lines come from the parser as
    each `<port>` opens, so a comment quoting a port cannot shift them."""
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
    """The captured stdout line saying MAME refused the cfg, or None."""
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
    """`state_dir` as a directory this session may own, never the project store's."""
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


PORT_MAX = 65535

#: `start`'s arguments that hold paths, which a profile resolves against its store's base.
START_PATHS = ("binary", "rompath", "inipath", "reference_rom", "symbols", "boot_lua",
               "state_dir", "cfg", "types")


def with_profile(profile: str, *, keys: Collection[str], arguments: dict[str, Any],
                 given: Collection[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """`arguments`, every one `start` takes, with the profile `profile` filling only the names
    `given` does not carry; and the reply's `profile` block. The store is looked for from this
    process's directory, then from `rompath` and `binary`, which name the run and not the
    repository that declares it."""
    starting: list[str] = [os.getcwd()]
    starting += [part for part in str(arguments.get("rompath") or "").split(";") if part]
    if binary := str(arguments.get("binary") or ""):
        starting.append(str(Path(judges.expanded(binary)).parent))
    found = project_store.applied(profile, starting=starting, keys=keys,
                                  path_keys=START_PATHS, given=given, arguments=arguments)
    return found.arguments, found.shown()


def check_start(binary: str = "", rompath: str = "", reference_rom: str = "",
                system: str = "", profile: str = "", symbols: syms.Given = "",
                inipath: str = "", boot_lua: str = "", state_dir: str = "",
                cfg: str = "", types: syms.Types = "", view: str = "", **_: Any) -> None:
    """`start`'s machine-independent half: the shape of every path, in `judge`'s reading order.
    Whether files exist is the host's. A call naming a `profile` may leave to it what it fills:
    the tool reads the profile and gates the merged arguments, so only what both lack is empty."""
    if not profile:
        project_store.demanded({"system": system, "rompath": rompath,
                                "reference_rom": reference_rom},
                               ("system", "rompath", "reference_rom"), tool="start")
    if binary:          # empty climbs `binary`'s ladder, which judges what it lands on
        inputs.absolute("binary", binary)
    if reference_rom:
        inputs.absolute("reference_rom", reference_rom)
    judge_folders("rompath", rompath)
    judge_folders("inipath", inipath)            # a missing one MAME skips
    if cfg:
        inputs.absolute("cfg", cfg)
    if boot_lua:
        inputs.absolute("boot_lua", boot_lua)
    for name, path, _thing in syms.named_files(symbols, types):
        inputs.absolute(name, path)
    if state_dir:
        inputs.absolute("state_dir", state_dir)
    check_view(view)


def check_view(view: str) -> None:
    """`view` is one command-line argument: no NUL, no lone surrogate, no leading `-`."""
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
          symbols: syms.Given, reference_addr: NumberArg, inipath: str, wait: float, shared: bool,
          boot_lua: str, env: dict[str, str] | None, bases: syms.Bases | None,
          reference_base: NumberArg, port: int, state_dir: str,
          throttle_from_frame: int, types: syms.Types = "", cfg: str = "",
          background: bool | None = None, presence: bool = False,
          binary_origin: str = binaries.ARGUMENT, view: str = "", display: int | None = None,
          size: str | None = None, bundle: str = "") -> Judged:
    """Every refusal of the caller's input, before the emulator exists: after the boot a bad
    path surfaces as a bare error naming no argument, with a machine possibly running.

    Path shapes first (`check_start`), then arguments in reading order; `state_dir` is written
    last."""
    check_start(binary=binary, system=system, rompath=rompath, reference_rom=reference_rom,
                symbols=symbols,
                inipath=inipath, boot_lua=boot_lua, state_dir=state_dir, cfg=cfg, types=types,
                view=view)
    wanted = core_window.requested(shared, display, None, size, emulator="mame")
    # Inputs below use `is_file()`, never `exists()`: a directory with a file's name would
    # otherwise be refused at the spawn, naming no argument.
    if plugins_dir(binary) is None:
        looked = "; ".join(str(d / CONSOLE_PLUGIN) for d in plugin_places(binary))
        raise st.Invalid("bad_argument" if binary_origin == binaries.ARGUMENT else "host_failed",
                         f"no console plugin for {binary} (from the {binary_origin} rung) in "
                         f"any of: {looked}. The Lua console this server connects to stdin is "
                         "MAME's `console` plugin, and without it MAME refuses to boot "
                         "(\"Console plugin not found\"): pass as `binary`, or set "
                         f"{binaries.VARIABLE} to, the executable of a MAME build or install "
                         "that ships its plugins")
    ref = reference_rom_file(reference_rom)
    # Reaching MAME, a missing ROM directory looks like a stub that never answers, after the
    # whole `boot_seconds`.
    for named, roms in judge_folders("rompath", rompath):
        if not roms.is_dir():
            inputs.no_such(named, "ROM directory", str(roms))
    inputs.natural("throttle_from_frame", throttle_from_frame,
                   " is not a frame number: an integer, never negative, and 0 is off")
    behind = judge_background(background, shared, env)
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
    # A mapping names cpus, so the list is waited for here: a cpu it lacks is refused with
    # nothing spawned, and the store is keyed by the first cpu's file. A watched window is
    # sized from the screen it lists.
    listed: machine.Listed | None = None
    tags: list[str] = []
    if shared or syms.is_mapping(symbols):
        listed = machine.listxml(machine.ask_listxml(binary, system), binary, system, wait)
    screens = listed[0]["screens"] if listed is not None else []
    flags = window_flags(wanted, screens)
    if throttle_from_frame and "-nothrottle" not in flags:
        flags.append("-nothrottle")
    if listed is not None and syms.is_mapping(symbols):
        tags = [row["tag"] for row in listed[0]["cpus"]]
        if not tags:
            raise st.Invalid("bad_argument",
                             f"a `symbols` mapping names cpus, and this machine's list of them "
                             f"could not be read: {listed[1]}")
    loaded = syms.load(symbols, bases, types, tags)
    # Opened before the emulator exists so a corrupt file refuses with nothing to clean up.
    # Session-lived without a symbol file, since nothing could re-resolve by name; a `state_dir`
    # keeps the store there and never opens the shared project store.
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
    # Created after every judgement: this server never deletes it, so a refusal must not leave
    # `cfg/` and `nvram/` in it.
    if state is not None:
        try:
            for sub in ("cfg", "nvram"):
                (state / sub).mkdir(parents=True, exist_ok=True)
        except NotADirectoryError as e:
            raise st.Invalid("bad_argument", cannot_hold(state_dir, str(e)) +
                             "; name a directory, or one that does not exist yet") from None
        except OSError as e:
            raise st.Invalid("host_failed", cannot_hold(state_dir, str(e))) from None
    asked = machine.ask_listxml(binary, system) if listed is None else (None, "")
    return Judged(flags=flags, port=port, tables=loaded, store=store, declarations=declarations,
                  ref=ref, ref_addr=ref_addr, ref_base=ref_base, binary=binary, system=system,
                  rompath=rompath, inipath=inipath, wait=wait, boot_lua=boot_lua,
                  env=dict(env or {}), state_dir=state_dir, throttle_from_frame=throttle_from_frame,
                  listxml=asked, cfg=cfg_source, listed=listed, background=behind,
                  presence=presence, picked=picked, view=view, bundle=bundle,
                  window=fitted_request(wanted, screens), scaled=scaled_note(wanted, screens))


VIEW_ARGUMENT = ("What `snapshot` and `record` render through: empty, the emulated screen at its "
                 "own size; else a layout view by prefix (`views` lists them, `view` says which "
                 "was taken).")



_VERSIONS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mame-version")


def view_shown(asked: str, inventory: dict[str, Any]) -> str | dict[str, Any]:
    """The view captures are taken through: `native` when none was asked, else what MAME
    resolved the name to, whether by prefix or by its own fallback."""
    if not asked:
        return "native"
    taken = inventory.get(machine.SNAPVIEW, "")
    return taken or unavailable("MAME did not say which view its snapshots take: the boot "
                                "harness read no snapshot target")


def views_shown(inventory: dict[str, Any]) -> list[str] | dict[str, Any]:
    """The set's layout views, or why none was listed."""
    views = inventory.get(machine.VIEWS) or []
    return views or unavailable("no render target listed a view: a machine run with no "
                                "video has none, and `view` then takes `native` alone")


def stdout_tail(scratch: Path | None) -> str:
    return channel_tail(scratch, "process")


def channel_tail(scratch: Path | None, channel: str) -> str:
    """The last of one channel, named by channel so file names stay in `files`."""
    log = files.log_path(scratch, channel) if scratch else None
    if log is None or not log.exists():
        return ""
    return log_marks.tail(log)


def _alive_fields(judged: Judged, keep: bool = True) -> dict[str, Any]:
    """What a refusal carries while MAME is alive; `keep` copies its output past the scratch
    (a launch that will be retried keeps none, or its copies would push the kept ones out)."""
    assert STATE.proc is not None and STATE.scratch is not None
    return {"exit_code": unavailable("MAME is still running"), "pid": STATE.proc.pid,
            "stub_port": judged.port, "alive": True,
            "stdout_tail": stdout_tail(STATE.scratch),
            **(keep_failed_start(STATE.scratch, judged.system) if keep else {})}


def _no_answer(judged: Judged, cause: object, attempts: list[dict[str, Any]]) -> st.Invalid:
    """The refusal of a live MAME whose stub never answered, with every dial."""
    return st.Invalid("session_broken",
                      f"the gdbstub did not answer within {judged.wait} s: {cause}",
                      dial_attempts=attempts, **_alive_fields(judged))


def _exit_code(error: BaseException, progress: mprogress.Progress) -> int | dict[str, Any] | None:
    """MAME's exit code, or None while it runs; a closed channel gets `CLOSED_EXIT_WAIT_S`.

    An app route answers `unavailable`: nothing here reaps the app it started."""
    assert STATE.proc is not None
    code = STATE.proc.poll()
    if code is None and isinstance(error, (gs.DialFailed, gs.ConnectionFailed)):
        code = st.wait_exit(STATE.proc, CLOSED_EXIT_WAIT_S, progress,
                            "start: MAME closed the gdbstub's connection")
    return app_launch.exit_status(STATE.proc, code) if code is not None else None


FAILED_STARTS_KEPT = 20


def keep_failed_start(scratch: Path, system: str) -> dict[str, Any]:
    """Copy `stdout.log` to `<state>/failed-starts/<utc>-<system>.log`, rotating to the newest
    `FAILED_STARTS_KEPT` of that name shape, and answer `stdout_kept`. A failed copy is
    unavailable: the refusal it rides on is the news."""
    folder = dec.state_home() / "failed-starts"
    try:
        kept = folder / file_names.name(file_names.stamp(datetime.now(UTC)),
                                        file_names.word(system, "system"), extension="log")
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files.log_path(scratch, "process"), kept)
        for old in sorted(folder.glob("[0-9]*[tT]*[zZ]-*.log"))[:-FAILED_STARTS_KEPT]:
            old.unlink()
    except (OSError, st.Invalid) as e:
        return {"stdout_kept": unavailable(str(e))}
    return {"stdout_kept": str(kept)}


def _await_banner(judged: Judged, clock: mprogress.Ticker, request_s: float) -> None:
    """Wait for `DEBUGGER_BANNER` or the process's death, leaving the handshake `request_s`."""
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
    """The scratch, the process, the connected stub and the ROM check; the env, harness and argv
    come back for the reply. The caller holds the guard.

    MAME writes `cfg/` and `nvram/` into its working directory, so a session gets its own and
    takes them along, unless `state_dir` is named. They are made here so a missing one is this
    server's mistake, not a silent fallback."""
    assert STATE.scratch is not None
    (STATE.scratch / "snap").mkdir()
    if not judged.state_dir:
        for sub in ("cfg", "nvram"):
            (STATE.scratch / sub).mkdir()
    if judged.cfg is not None:
        installed = Path(judged.state_dir or STATE.scratch) / "cfg" / f"{judged.system}.cfg"
        # A persistent `state_dir` may hold an earlier copy; the reply says it was replaced.
        replaced = installed.exists()
        shutil.copyfile(judged.cfg, installed)
        STATE.cfg = {"source": judged.cfg, "installed": installed, "replaced": replaced}
    given = dict(judged.env)
    if judged.throttle_from_frame:
        given[THROTTLE_FRAME_VAR] = str(judged.throttle_from_frame)
    harness = boot_harness(STATE.scratch, judged.boot_lua, judged.throttle_from_frame,
                           judged.presence)
    cmd = build_command(judged.binary, judged.system, judged.rompath, judged.port, judged.flags,
                        str(STATE.scratch), judged.inipath, harness, judged.state_dir,
                        judged.view)
    STATE.stdout_log = None
    if judged.bundle:
        # `open` writes the process log itself and reads the console from the FIFO, so the same
        # readers keep working; the pid is found by the port this session alone holds.
        STATE.proc = app_launch.launch(
            judged.bundle, cmd,
            stdout=str(files.log_path(STATE.scratch, "process")),
            stdin_fifo=str(STATE.scratch / CONSOLE_FIFO),
            env=core_window.launch_environment(given, judged.background),
            cwd=str(STATE.scratch),
            token=f"-debugger_port {judged.port}")
    else:
        # One file: a driver's and the OSD's complaints would be lost sent to DEVNULL.
        STATE.stdout_log = open(files.log_path(STATE.scratch, "process"),  # noqa: SIM115
                                "wb")
        # stdin is the Lua console's; unconnected it reads end-of-file and stops for good.
        STATE.proc = console_popen(
            cmd, stdout=STATE.stdout_log, stderr=subprocess.STDOUT,
            env=core_window.launch_environment({**os.environ, **given}, judged.background),
            cwd=STATE.scratch,
        )
    if (ledger := live_host.EmulatorLedger.from_environment()) is not None:
        ledger.record(STATE.proc.pid, cmd[0])
    STATE.guard = guardian.spawn(STATE.proc, PROCESS_NAME)
    clock = mprogress.Ticker(judged.wait, progress)
    last: Exception | None = None
    died: int | dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = []
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
            raise failures.PortServed(
                e, judged.picked,
                **_alive_fields(judged, keep=last_launch or not judged.picked)) from None
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
            died = _exit_code(e, progress)
            if died is not None:
                break
            if isinstance(e, gs.DialFailed):
                raise st.Invalid("session_broken",
                                 f"the gdbstub's connection failed as it was made: {e}. "
                                 f"{failures.ONE_CONNECTION}", dial_attempts=attempts,
                                 **_alive_fields(judged)) from None
            clock.tick("start {system}: waiting for the gdbstub on port {port}, {elapsed:.0f}s "
                       "of {wait:g}", system=judged.system, port=judged.port, wait=judged.wait)
            time.sleep(BOOT_POLL_S)
    if STATE.ses is not None:
        _await_banner(judged, clock, STATE.ses.timeout)
        try:
            STATE.ses.handshake(max(clock.left(), STATE.ses.timeout))
        except (OSError, gs.SessionError) as e:
            # Hung up from here: the side that closes first keeps the TIME_WAIT, and on MAME's
            # side that would leave `stub_port` taken for a relaunch.
            STATE.ses.close()
            STATE.ses = None
            if (died := _exit_code(e, progress)) is not None:
                raise failures.death_refusal(died, clock.elapsed(),
                                             stdout_tail(STATE.scratch)) from None
            tail = stdout_tail(STATE.scratch)
            if isinstance(e, gs.Refused) and failures.unserved_line(e, tail):
                first = next((row["tag"] for row in collect(judged)[0]["cpus"]), "")
                if (line := failures.unserved_first_cpu(tail, first)) is not None:
                    raise failures.unserved_refusal(e, clock.elapsed(), line,
                                                    **_alive_fields(judged)) from None
            if isinstance(e, failures.NOT_READY_ERRORS):
                raise failures.StubNotReady(e, clock.elapsed(),
                                            **_alive_fields(judged, keep=last_launch)) from None
            phase = getattr(e, "phase", gs.SessionError.phase)
            raise st.Invalid("session_broken",
                             f"{failures.handshake_failed(phase, clock.elapsed(), e)}. "
                             f"{failures.ONE_CONNECTION}", phase=phase,
                             **_alive_fields(judged)) from None
    if STATE.ses is None and died is None:
        died = STATE.proc.poll()
    if STATE.ses is None:
        # The scratch is deleted on failure, so what MAME printed rides on the refusal. A death
        # is read in its output, a stub that never answered in the port and the boot's length.
        if died is not None:
            raise failures.death_refusal(died, clock.elapsed(), stdout_tail(STATE.scratch))
        raise _no_answer(judged, last, attempts)
    try:
        STATE.ses.self_check(judged.ref.read_bytes(), judged.ref_addr, base=judged.ref_base,
                             thread=1)
    except gs.Mismatch as e:
        raise st.Invalid("readback_refused", f"{e} The session is closed.") from e
    if judged.cfg is not None:
        refused = cfg_parse_error(STATE.scratch)
        if refused is not None:
            raise st.Invalid("bad_argument",
                f"MAME did not read {judged.cfg}: its `process` channel "
                f"({files.LOG_FILES['process']}) says `{refused}`, so the machine booted on "
                "the default inputs; the session is closed",
                stdout_path=str(files.log_path(STATE.scratch, "process")))
    return given, harness, cmd


def start(binary: str, system: str, rompath: str, reference_rom: str, symbols: syms.Given,
          reference_addr: NumberArg, inipath: str, wait: float, shared: bool, boot_lua: str,
          env: dict[str, str] | None, bases: syms.Bases | None, reference_base: NumberArg,
          port: int, state_dir: str,
          throttle_from_frame: int = 0, types: syms.Types = "", cfg: str = "",
          background: bool | None = None, *, presence: bool, view: str = "",
          display: int | None = None, size: str | None = None,
          progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `start` tool: one launch, relaunched whole up to `START_RETRIES_MAX` times
    for a `failures.LaunchFailed` that says so. Only its evidence survives, as `start_retries`."""
    binary, reference_rom, boot_lua, cfg, state_dir = (
        judges.expanded(v) for v in (binary, reference_rom, boot_lua, cfg, state_dir))
    rompath, inipath = (";".join(judges.expanded(p) for p in v.split(";")) if v else v
                        for v in (rompath, inipath))
    symbols = syms.expanded(symbols)
    types = syms.expanded(types)
    retries: list[dict[str, Any]] = []
    # Windows: a start behind keeps the foreground where it is until its window is up.
    with core_window.foreground_kept(core_window.judge_background(background, shared)):
        try:
            while True:
                try:
                    return _launch(binary, system, rompath, reference_rom, symbols, reference_addr,
                                   inipath, wait, shared, boot_lua, env, bases, reference_base,
                                   port, state_dir, throttle_from_frame, types, cfg,
                                   background, presence, retries, progress, view, display,
                                   size)
                except failures.LaunchFailed as failed:
                    if (not failed.relaunch(port_picked=not port)
                            or len(retries) == START_RETRIES_MAX):
                        raise
                    retries.append(failed.evidence())
                    progress(len(retries), START_RETRIES_MAX,
                             f"start {system}: {failed.what}; relaunching after {failed.kind} "
                             f"({len(retries)} of {START_RETRIES_MAX})")
        except st.Invalid as refused:
            refused.fields["start_retries"] = retries
            raise
        except gs.SessionError as e:
            raise st.Invalid("session_broken", f"the boot's channel failed: {e}. The session is "
                             "closed; `start` again", start_retries=retries) from e


def _launch(binary: str, system: str, rompath: str, reference_rom: str, symbols: syms.Given,
            reference_addr: NumberArg, inipath: str, wait: float, shared: bool, boot_lua: str,
            env: dict[str, str] | None, bases: syms.Bases | None, reference_base: NumberArg,
            port: int, state_dir: str, throttle_from_frame: int,
            types: syms.Types, cfg: str, background: bool | None, presence: bool,
            retries: list[dict[str, Any]], progress: mprogress.Progress,
            view: str = "", display: int | None = None, size: str | None = None) -> dict[str, Any]:
    """One launch: judge, boot under one guard, re-arm, park, reply."""
    # Ending a live session is the caller's act: a stray second `start` must not throw away a
    # session somebody is measuring on.
    if STATE.ses is not None and STATE.proc is not None and STATE.proc.poll() is None:
        st.refuse_broken(STATE.ses)
        raise st.Invalid("session_live",
            f"a session is live ({STATE.system}, pid {STATE.proc.pid}), and this server holds "
            "one machine: `close` it first, then `start`"
        )
    STATE.kill(progress, grace=False)
    resolved = binaries.resolve(binary)
    binary = resolved.path
    judged = judge(binary=binary, system=system, rompath=rompath, reference_rom=reference_rom,
                   symbols=symbols, reference_addr=reference_addr, inipath=inipath, wait=wait,
                   shared=shared, boot_lua=boot_lua, env=env, bases=bases,
                   reference_base=reference_base, port=port,
                   state_dir=state_dir, throttle_from_frame=throttle_from_frame, types=types,
                   cfg=cfg, background=background, presence=presence,
                   binary_origin=resolved.origin, view=view, display=display,
                   size=size, bundle=resolved.bundle or "")
    # From the scratch on, everything sits under one guard: a failed ROM check or any raise
    # kills the session, or the next call would measure on a lying one, or leave an orphaned
    # emulator. A start that did not start owns nothing, not even the directory.
    STATE.scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX))
    STATE.named_state_dir = state_dir
    STATE.port = judged.port
    try:
        try:
            # After `judge` so a refusal spawns nothing, beside the boot under the launch's
            # environment, bounded by the boot's wait so a hanging build costs nothing.
            version = _VERSIONS.submit(
                binaries.facts, resolved,
                core_window.launch_environment({**os.environ, **judged.env}, judged.background),
                min(binaries.VERSION_TIMEOUT_S, judged.wait))
            given, harness, _cmd = boot(judged, progress,
                                        last_launch=len(retries) == START_RETRIES_MAX)
        except st.Invalid:
            # The cause outranks the symptom: a system this build lacks reports a stub that never
            # answered, while the query holds MAME's own diagnosis and raises first if it has one.
            collect(judged)
            raise
        except BaseException:
            discard(judged)
            raise
        # Collected before anything else can raise, so no query is stranded with this server as
        # its parent.
        listed = collect(judged)
        binary_facts = version.result()
        assert STATE.ses is not None
        STATE.system = system
        STATE.maps.started()
        # The one path's table is the first cpu's: the stub's thread 1, else `cpulist`, else
        # `-listxml`.
        STATE.first_cpu = (cpus.stub_cpu(STATE.ses)
                           or next((row["tag"] for row in listed[0]["cpus"]), None))
        STATE.tables = judged.tables.keyed(STATE.first_cpu)
        STATE.session_origin = STATE.origin()
        first = STATE.first_cpu
        machine_cpus = [row["tag"] for row in listed[0]["cpus"]] or cpus.cpu_list(STATE.ses)
        STATE.fingerprints = {
            cpu: syms.fingerprint(system, judged.ref, judged.tables.path_of(cpu, first),
                                  None if cpu == first else cpu)
            for cpu in dict.fromkeys([first, *machine_cpus])}
        judged.declarations["fingerprint"] = STATE.fingerprint()
        STATE.store = judged.store
        STATE.reference = (judged.ref, judged.ref_addr, judged.ref_base)
        # Read off the scratch, not the machine, so no pc moves; before the re-arm, which judges
        # conditions against its register names. A gap is a note, never a failed start.
        STATE.machine_map = machine.cache(STATE.scratch, listed)
        STATE.view = view_shown(judged.view, STATE.machine_map)
        STATE.window = judged.window
        STATE.background = judged.background
        STATE.ses.know_endianness(cpus.program_endianness(STATE.ses, STATE.machine_map,
                                                          STATE.first_cpu))
        if judged.presence:
            STATE.presence = scry_presence.Presence.open(
                mpresence.FileAdapter(STATE.scratch, st.LOCK, STATE.repaintable,
                                      transport.pending_lines), mpresence.DRIVING_TOOLS)
        STATE.frame_symbol = read.probe_frame_symbol(STATE.ses)
        # Before the park's survey so the first stop carries every watch evaluated.
        judged.declarations["rearm"] = rearming.rearm_breakpoints_and_watches(STATE.ses)
        regpoints.rearm(STATE.ses, judged.declarations["rearm"])
        judged.declarations["comments"] = comments.rearm(STATE.ses, STATE.scratch)
        park = running.record_park(STATE.ses, STATE.scratch)
        STATE.boot_pc = int(park["pc"], 16)      # what `reset` reads its pc back against
        started = menvelope.envelope({
            "system": system,
            **binary_facts,
            "pid": STATE.proc.pid if STATE.proc else None,
            "stub_port": judged.port,
            "scratch_dir": str(STATE.scratch),
            **({"bundle": judged.bundle} if judged.bundle else {}),
            "state_dir": STATE.state_dir,
            "cfg": cfg_report(),
            "debugger": debugger_report(),
            **channels(),
            "rom_check": "OK",
            **symbols_fields(),
            "registers": STATE.ses.layout(1).register_names,
            "pc": park["pc"],
            "frame": st.frame_shown(park["frame"]),
            **read.frame_fields(),
            "env": given,
            "view": STATE.view,
            "views": views_shown(STATE.machine_map),
            "background": judged.background,
            "flags": judged.flags,
            "throttle_from_frame": throttle_from_frame,
            "boot_lua_path": harness,
            "presence": STATE.presence_shown(),
            "machine": {name: len(STATE.machine_map[name]) for name in machine.SECTIONS},
            "declarations": judged.declarations,
            "start_retries": list(retries),
            "recommended_release": binaries.RELEASE,
        })
        st.add_note(started, binaries.release_note(binary_facts["version"]), judged.scaled)
        idle.IDLE.clear_note()
    except Exception:
        STATE.kill(progress, grace=False)
        raise
    # A refusal here leaves the session live, as its message says: `window` and `close` still act.
    if judged.window is not None:
        assert STATE.proc is not None
        started["window"] = core_window.prove(STATE.proc.pid, judged.window).block()
    return started
