"""What every live script of this server shares: the board to drive, a declaration store of the
run's own, the ledger of checks and the verdict that closes it.

Importing it puts the server's own directory on the path, which is what lets the scripts beside
it `import server` and run the code on disk; the boards on the bench are `bench_boards`'. It does
NOT isolate the store: a script calls `isolate_state(prefix)` before its first `start`, and that
call is what keeps the owner's own declaration store untouched.

It also holds the MATRIX's ledger (a section declared with its cells before anything boots,
each cell judged once, every call kept whole in a transcript), the boots more than one section
shares, and the runner of boards that own their cells, so that a section kept in a module of its
own registers with the same machinery rather than a copy of it. `run_sections` runs whatever
sections were registered, which is how such a module runs alone. Importing it therefore also
makes the run's scratch directory and sees to it that no emulator outlives the process.
"""

import atexit
import inspect
import json
import os
import sys
import tempfile
import time
import traceback
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# The server's own files, found through the path just set, which is why they come after it.
from evidence import keep  # noqa: E402

import server as s  # noqa: E402
from mame_state import STATE  # noqa: E402

from bench_boards import (  # noqa: E402  # isort: skip
    M68K_DUAL_BINARY,
    M68K_DUAL_ROMS,
    M68K_DUAL_SYSTEM,
    REFERENCE_ROM,
    SYMBOLS,
    args_missing,
)

# THE THREE OUTCOMES, spelled once for every live script: a run that examined nothing is never
# folded into either of the other two.
EXIT_PASSED, EXIT_FAILED, EXIT_INVALID = 0, 1, 3


def invalid(message: str) -> None:
    """Refuse the whole run: nothing here is a verdict about the server."""
    print(f"INVALID: {message}", file=sys.stderr)
    sys.exit(EXIT_INVALID)


# m68k-dual's boot, every live script's: the board on the bench (`bench_boards`).
BOOT = dict(binary=M68K_DUAL_BINARY, system=M68K_DUAL_SYSTEM, rompath=M68K_DUAL_ROMS,
            reference_rom=REFERENCE_ROM, reference_addr="0x0", seconds=25.0)

# WHETHER THIS RUN'S MACHINES TAKE THE OWNER'S FOCUS, asked per run and never per cell: unset,
# each `start` keeps its own default; `1` or `0` forces every one of this run behind or in front.
# Read once, handed to every `start` (`BOOT` for the direct callers, `call` for the rest), and
# printed, so a run says which way it ran.
BACKGROUND_VAR = "MAME_BACKGROUND"
_background = os.environ.get(BACKGROUND_VAR, "")
if _background not in ("", "0", "1"):
    invalid(f"{BACKGROUND_VAR}={_background!r}: `1` (every start behind), `0` (every start in "
            "front), or unset (each start by who watches it)")
BACKGROUND: bool | None = None if not _background else _background == "1"
if BACKGROUND is not None:
    BOOT["background"] = BACKGROUND
print(f"background: {'each start its own default' if BACKGROUND is None else BACKGROUND} "
      f"({BACKGROUND_VAR}={_background or 'unset'})")


def isolate_state(prefix: str) -> str:
    """Point the declaration store at a scratch of this run, and answer where.

    Declarations persist per system and symbol file and re-arm on every `start`, by design: a
    watch another session left on this board would stop the machine at every frame here, and
    the checks on control hits and on "one armed watch" would fail over somebody else's state.
    The store's location is read when the session starts, so this runs before the `start` it is
    meant for.
    """
    os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix=prefix)
    return os.environ["XDG_STATE_HOME"]


# EVERY CHECK THAT FAILED, BY LABEL, and the verdict is derived from it: two names for one
# fact (a boolean beside a list) drift the moment one of them is set and the other forgotten.
failures: list[str] = []


def row(word: str, label: str, detail: str = "") -> None:
    """One result line: the word in a fixed column, so the labels line up whatever it says."""
    print(f"  {word:<4}  {label}{'  ' + detail if detail else ''}")


def check(label: str, condition: bool, detail: str = "") -> None:
    row("OK" if condition else "FAIL", label, detail)
    if not condition:
        failures.append(label)


def finish(name: str) -> None:
    """Print the failing labels, then the verdict as the LAST line, and exit by the outcome.

    THE REASONS SIT ABOVE THE VERDICT. A reader who takes the tail of this output gets the
    failing labels AND the word that judges them together; a verdict at the end with its
    reasons only at the top of a long run is the truncation trap that reads a red run as green.
    """
    print()
    print(f"{len(failures)} check(s) failed")
    for label in failures:
        print(f"  FAIL  {label}")
    print(f"==> {name} " + ("FAILED" if failures else "PASSED"))
    sys.exit(EXIT_FAILED if failures else EXIT_PASSED)


# ============================================================ the matrix's ledger

SCRATCH = Path(tempfile.mkdtemp(prefix="mame-live-matrix-"))
TRANSCRIPT = SCRATCH / "transcript.jsonl"

# ONE CALL'S OWN WAIT (the matrix's rule B1), and the reason a cell is BLOCKED rather than run: a
# matrix that waits on a hung channel measures the wait. A `start`'s boot wait is exempt, since a
# boot is not a channel that hung; the boards booted here other than m68k-dual get START_WAIT_S.
WAIT_CEILING_S = 10.0
START_WAIT_S = 30.0
WAIT_ARGS = ("seconds", "settle_seconds")


class Blocked(Exception):
    """A call the matrix refuses to make, and why: the cell it belonged to is BLOCKED."""


@dataclass
class Section:
    block: str
    title: str
    labels: list[str]
    run: Callable[[], None]
    judged: dict[str, str] = field(default_factory=dict)


SECTIONS: list[Section] = []
CURRENT: list[Section] = []
PENDING: list[dict[str, Any]] = []
BLOCKED: list[tuple[str, str]] = []
TALLY = {"OK": 0, "FAIL": 0, "BLOCKED": 0}
# The logs of a FAILED cell's session, copied out before `close` deletes its scratch: a cell
# that fails once in many runs leaves nothing else to be read afterwards.
EVIDENCE = SCRATCH / "evidence"
KEPT: list[Path] = []


def section(block: str, title: str, labels: list[str]) -> Callable[[Callable[[], None]], None]:
    """Declare a section and the cells it will judge, BEFORE anything runs."""
    def register(fn: Callable[[], None]) -> None:
        SECTIONS.append(Section(block, title, labels, fn))
    return register


def _record(label: str, verdict: str) -> None:
    """Every call made since the last judged cell fed this one: they go to the transcript under
    its label and verdict."""
    sec = CURRENT[0]
    with TRANSCRIPT.open("a") as fh:
        for rec in PENDING:
            fh.write(json.dumps({"section": f"[{sec.block}] {sec.title}", "label": label,
                                 "verdict": verdict, **rec}, default=str) + "\n")
    PENDING.clear()


def cell(label: str, condition: bool, detail: str = "") -> None:
    """Judge one PLANNED cell, once."""
    sec = CURRENT[0]
    if label not in sec.labels or label in sec.judged:
        # A label nobody planned, or one judged twice, is the section's defect: it fails
        # under its own name rather than passing as the cell it collided with.
        label = f"UNPLANNED OR REPEATED: {label}"
        condition = False
    verdict = "OK" if condition else "FAIL"
    check(label, condition, detail)
    sec.judged[label] = verdict
    TALLY[verdict] += 1
    if verdict == "FAIL" and STATE.scratch is not None:
        # A copy that fails costs this cell its evidence and nothing else: raised from here it
        # would abort the section and BLOCK cells that had nothing wrong with them.
        try:
            if (kept := keep(STATE.scratch, EVIDENCE, label)) is not None:
                KEPT.append(kept)
        except OSError as exc:
            print(f"  evidence NOT kept for {label}: {exc}")
    _record(label, verdict)


def blocked(label: str, reason: str) -> None:
    sec = CURRENT[0]
    row("BLOCKED", label, reason)
    sec.judged[label] = "BLOCKED"
    BLOCKED.append((label, reason))
    TALLY["BLOCKED"] += 1
    _record(label, "BLOCKED")


def call(tool: str, b1_exempt: str = "", **kw: Any) -> dict[str, Any]:
    """Call a tool the way the client would, and keep the WHOLE reply for the transcript.

    An exception is caught and turned into a reply carrying it, so the cell that reads it FAILS
    by name instead of the run dying. A wait above the ceiling is not made at all (`Blocked`),
    unless `b1_exempt` says why this call cannot wait: a value refused before any wait, or a
    line the contract answers at once. Nor is a call handed a file of the bench whose board is
    off its pins (`args_missing`).
    """
    fn = getattr(s, tool)
    if why := args_missing(kw):
        raise Blocked(why)
    if tool == "start" and BACKGROUND is not None:
        kw.setdefault("background", BACKGROUND)
    params = inspect.signature(fn).parameters
    for name in WAIT_ARGS:
        if name in params and not (tool == "start" and name == "seconds"):
            value = kw.get(name, params[name].default)
            if isinstance(value, int | float) and value > WAIT_CEILING_S and not b1_exempt:
                raise Blocked(f"B1: {tool}({name}={value}) may wait past {WAIT_CEILING_S:g} s")
    t0 = time.monotonic()
    try:
        reply: dict[str, Any] = fn(**kw)
    except Exception as e:  # noqa: BLE001 -- the reply IS the evidence of the exception
        reply = {"exception": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}
    PENDING.append({"tool": tool, "args": kw, "wall_s": round(time.monotonic() - t0, 3),
                    "reply": reply})
    return reply


def last_wall() -> float:
    return float(PENDING[-1]["wall_s"]) if PENDING else 0.0


# ------------------------------------------------------------------ what every reply promises


def whole(r: dict[str, Any]) -> bool:
    """The envelope every reply promises: `summary` first, `session` last, `status` either word,
    and a refusal carrying its `code` and its `message`."""
    keys = list(r)
    if not keys or keys[0] != "summary" or keys[-1] != "session":
        return False
    if r.get("status") == "ok":
        return True
    return r.get("status") == "INVALID" and bool(r.get("code")) and bool(r.get("message"))


def ok(r: dict[str, Any]) -> bool:
    return whole(r) and r.get("status") == "ok"


def unavailable_why(value: Any) -> str | None:
    """The reason a reply gives for a datum it could not read, `{"available": false, "why"}`,
    or None when the datum is a value."""
    return value.get("why") if isinstance(value, dict) and value.get("available") is False else None


def rearm_pairs(rearm: dict[str, Any], which: str) -> list[tuple[str | None, str | None]]:
    """One bucket of `start`'s re-arm account as (ref, cpu) pairs, the two keys that name a
    declaration; a row that names no cpu answers it unavailable, and the pair holds None."""
    return [(e.get("ref"), e.get("cpu") if isinstance(e.get("cpu"), str) else None)
            for e in rearm.get(which, [])]


def refused(r: dict[str, Any], *codes: str) -> bool:
    return whole(r) and r.get("status") == "INVALID" and (not codes or r.get("code") in codes)


def visible_of(cpu_info: dict[str, Any]) -> str | None:
    """The cpu a `cpu_info` reply marks visible, or None: no rows, or none marked."""
    return next((row["cpu"] for row in cpu_info.get("cpus") or [] if row["visible"] is True),
                None)


def ignored_of(cpu_info: dict[str, Any]) -> list[str] | None:
    """The cpus a `cpu_info` reply marks ignored, or None when it could not say: a refusal, no
    rows, or a row whose listing the console did not answer."""
    rows = cpu_info.get("cpus") or []
    if not rows or any(not isinstance(row["ignored"], bool) for row in rows):
        return None
    return [row["cpu"] for row in rows if row["ignored"] is True]


def said(r: dict[str, Any], limit: int = 110) -> str:
    """What a reply said, short: the exception if it raised, else its summary line."""
    text = r.get("exception") or r.get("summary") or str(r)[:limit]
    return str(text)[:limit]


def session_is(r: dict[str, Any], alive: bool, running: bool) -> bool:
    ses = r.get("session", {})
    return ses.get("alive") is alive and ses.get("running") is running


_names = count(1)


def fresh(suffix: str) -> str:
    """An absolute path that does not exist yet, in this run's scratch: a `dest` every tool
    takes."""
    return str(SCRATCH / f"f{next(_names)}{suffix}")


def fresh_state() -> str:
    return f"m{next(_names)}"


def boot(**extra: Any) -> dict[str, Any]:
    kw: dict[str, Any] = {**BOOT, "symbols": SYMBOLS, **extra}
    if kw["symbols"] is None:
        kw.pop("symbols")
    return call("start", **kw)


def ensure_closed() -> None:
    """No machine at a section's edge: each section boots what it needs and ends with none.

    It never raises: a stub that hung makes `status` itself time out, and a teardown that died
    there took every later section and the verdict with it. Anything but a clear "no machine"
    is closed, which kills after the grace period whatever the stub does."""
    try:
        alive = s.status().get("alive")
    except Exception:  # noqa: BLE001 -- a status that cannot answer is a machine to close
        alive = True
    if alive:
        call("close")


# THE LAST WORD ON THE EMULATOR IS THIS PROCESS'S: a run that dies half-way must not leave a
# MAME behind it on the owner's display.
atexit.register(lambda: STATE.kill())


# ======================================================== the free boards of mamedev.org

FREE_BINARY = os.environ.get("MAME_STOCK_BINARY", "")
FREE_ROMS = os.environ.get("MAME_TEST_ROMS", "")
# A build whose gdbstub is patched to serve a thread per cpu, for the boards with several: the
# stock stub serves its first cpu alone.
MULTICPU_BINARY = os.environ.get("MAME_MULTICPU_BINARY", "")


def free_image(system: str, members: list[str], dest: Path, held: Path | None = None) -> str:
    """The reference image of a free set, out of its zip in `held` (MAME_TEST_ROMS unless
    named): one file, or two interleaved a byte each (`ROM_LOAD16_BYTE`)."""
    with zipfile.ZipFile((held or Path(FREE_ROMS)) / f"{system}.zip") as z:
        parts = [z.read(m) for m in members]
    data = (parts[0] if len(parts) == 1
            else bytes(b for pair in zip(*parts, strict=True) for b in pair))
    out = dest / f"{system}.ref"
    out.write_bytes(data)
    return str(out)


def no_joystick_ini(extra: str = "") -> str:
    """An ini directory whose `mame.ini` names no joystick provider, made on first use: the free
    boards run on whatever build they are given, and a debug build may abort at boot with a
    controller connected (`mame_boot_failures.SDL3_JOYSTICK_NOTE` says why). `extra` lines
    follow it, in a directory of their own."""
    ini = Path(fresh("-ini")) if extra else SCRATCH / "ini-no-joystick"
    if not ini.is_dir():
        ini.mkdir()
        (ini / "mame.ini").write_text("joystickprovider none\n" + extra)
    return str(ini)


class BootFailed(Exception):
    """A board's `start` was not `ok`: its message, and the last line MAME printed."""


def require_booted(system: str, r: dict[str, Any]) -> dict[str, Any]:
    """`r`, the reply of a `start` that booted; otherwise `BootFailed`, which `run_boards` turns
    into a FAIL of every cell the board owns, rather than each cell failing on the missing
    session with `no_session` where the reason is the boot."""
    if ok(r):
        return r
    tail = str(r.get("stdout_tail") or "").strip().splitlines()
    raise BootFailed(f"start {system}: {str(r.get('message') or said(r))[:200]} / "
                     f"{tail[-1][:200] if tail else 'no stdout_tail'}")


def free_boot(system: str, members: list[str], addr: str, ini_extra: str = "",
              binary: str = FREE_BINARY, **launch: Any) -> dict[str, Any]:
    """A free board booted on `binary` (the stock MAME unless named), `start` checking its image
    at `addr`, and refused unless it booted (`require_booted`); `ini_extra` added to its ini
    (`no_joystick_ini`)."""
    folder = Path(fresh("-image"))
    folder.mkdir()
    image = free_image(system, members, folder)
    return require_booted(system, call(
        "start", binary=binary, system=system, rompath=FREE_ROMS, reference_rom=image,
        reference_addr=addr, reference_base=addr, inipath=no_joystick_ini(ini_extra),
        seconds=START_WAIT_S, **launch))


def circus_boot(ini_extra: str = "", **launch: Any) -> dict[str, Any]:
    """circus, checked against its one program ROM, which its cpu sees at 0x1000, `ini_extra`
    added to its ini, `launch` passed to `start` (`background`)."""
    return free_boot("circus", ["9004a.1a"], "0x1000", ini_extra, **launch)


def _boards_missing(binary: str, variable: str, what: str, boards: str) -> str:
    """Why `boards` cannot run on this host (`binary` or the zips absent), or empty."""
    if binary and FREE_ROMS and Path(binary).is_file() and Path(FREE_ROMS).is_dir():
        return ""
    return (f"set {variable} ({what}, its plugins beside it) and MAME_TEST_ROMS (the sets' "
            f"zips) to run {boards}")


def free_boards_missing() -> str:
    """Why the free boards cannot run on this host, or empty when they can."""
    return _boards_missing(FREE_BINARY, "MAME_STOCK_BINARY", "a stock MAME", "the free boards")


def multicpu_missing() -> str:
    """Why the multi-cpu boards cannot run on this host, or empty when they can."""
    return _boards_missing(MULTICPU_BINARY, "MAME_MULTICPU_BINARY",
                           "a MAME whose gdbstub serves a thread per cpu", "the multi-cpu boards")


# ================================================= pangofun, a set kept apart for not verifying

# PANGOFUN IS KEPT IN ITS OWN FOLDER under MAME_TEST_ROMS: MAME wants a dump of its PAL that its
# set does not carry, and runs it once a file of that size stands in (a WRONG CHECKSUMS warning,
# nothing more), because the driver loads it into the `pld` region and never reads that region.
# The stand-in is written to this run's scratch only.
PANGOFUN_FOLDER = "pending-pangofun"
PANGOFUN_PAL_NAME = "palce20v8h.u42"
PANGOFUN_PAL_BYTES = 0x157


def pangofun_missing() -> str:
    """Why pangofun cannot run here: the free boards' reason, or its zip absent from its folder."""
    zip_path = Path(FREE_ROMS) / PANGOFUN_FOLDER / "pangofun.zip"
    return free_boards_missing() or ("" if zip_path.is_file()
                                     else f"{PANGOFUN_FOLDER}/pangofun.zip not in MAME_TEST_ROMS")


def pangofun_boot() -> dict[str, Any]:
    """pangofun (an i486) booted on the stock MAME from a scratch rompath holding its zips and
    the PAL's stand-in, `start` checking its bios, and refused unless it booted
    (`require_booted`)."""
    held = Path(FREE_ROMS) / PANGOFUN_FOLDER
    rompath = Path(fresh("-roms"))
    (rompath / "pangofun").mkdir(parents=True)
    for z in held.glob("*.zip"):
        (rompath / z.name).symlink_to(z)
    (rompath / "pangofun" / PANGOFUN_PAL_NAME).write_bytes(bytes(PANGOFUN_PAL_BYTES))
    # The 64 KB bios ends at 4 GB, and the i386 family resets 16 bytes below the top.
    return require_booted("pangofun", call(
        "start", binary=FREE_BINARY, system="pangofun", rompath=str(rompath),
        reference_rom=free_image("pangofun", ["bios.bin"], rompath, held),
        reference_addr="0xfffffff0", reference_base="0xffff0000", inipath=no_joystick_ini(),
        seconds=START_WAIT_S))


# ======================================================== a cpu's PC against MAME's own console

# Instructions a cpu is stepped to reach a PC that reads differently with its bytes reversed,
# which a PC such as 0x0000 does not: it would judge no byte order.
PC_STEPS_MAX = 50


def pc_of(reply: dict[str, Any]) -> str | None:
    """The PC a `registers` reply holds, or None."""
    return next((str(v) for k, v in (reply.get("regs") or {}).items() if k.lower() == "pc"), None)


def tells_byte_order(pc: object) -> bool:
    """Whether `pc` (`0x` and whole bytes) reads differently with its bytes reversed."""
    if not isinstance(pc, str) or not pc.startswith("0x") or len(pc) % 2:
        return False
    raw = bytes.fromhex(pc[2:])
    return raw != raw[::-1]


def registers_at_a_telling_pc(cpu: str = "") -> dict[str, Any]:
    """`registers` of `cpu` (the visible one when empty) at a stop whose PC tells the byte order
    (`tells_byte_order`), stepping that cpu up to `PC_STEPS_MAX` times; a refused read or step
    at once, as the reply to judge, and the last reading when no stop told."""
    named = {"cpu": cpu} if cpu else {}
    regs = call("registers", **named)
    for _ in range(PC_STEPS_MAX):
        if not ok(regs) or tells_byte_order(pc_of(regs)):
            break
        stepped = call("step", **named)
        if not ok(stepped):
            return stepped
        regs = call("registers", **named)
    return regs


def console_pc(cpu: str = "", symbol: str = "curpc") -> int | None:
    """MAME's console's own `print <symbol>` (`curpc` unless named), for `cpu` when named: made
    visible for it by `focus`, which must say nothing ran, and the cpu visible before put back.
    None when the focus was refused or ran the machine, or the console's answer is not a
    number."""
    before = visible_of(call("cpu_info")) if cpu else None
    if cpu:
        shown = call("focus", cpu=cpu)
        if not ok(shown) or shown.get("machine_ran") is not False:
            return None
    words = str(call("debug", command=f"print {symbol}").get("output", "")).split()
    if before is not None and before != cpu:
        call("focus", cpu=before)
    return int(words[0], 16) if words and all(
        c in "0123456789abcdefABCDEF" for c in words[0]) else None


def make_visible(cpu: str) -> bool:
    """`cpu` made the visible one, read back through `cpu_info`: a call that names another cpu
    is then judged with the named cpu NOT the one a call naming none would act on."""
    return ok(call("focus", cpu=cpu)) and visible_of(call("cpu_info")) == cpu


def zips_missing(*systems: str) -> str:
    """Why one of `systems` cannot run here: its zip absent from MAME_TEST_ROMS, or empty."""
    absent = [s for s in systems if not (Path(FREE_ROMS) / f"{s}.zip").is_file()]
    return f"{', '.join(absent)} not in MAME_TEST_ROMS" if absent else ""


# ========================================================== boards that own their cells

@dataclass(frozen=True)
class Board:
    """A board's run, handed the section's cells; the indexes of the cells it judges; and why
    it cannot run on this host, empty when it can, which every board states rather than
    defaults, so a board added without it does not run unguarded."""
    run: Callable[[list[str]], None]
    owned: tuple[int, ...]
    missing: Callable[[], str]


def boards_cover(name: str, cells: list[str], boards: tuple[Board, ...]) -> None:
    """Refuse the run unless `boards` gives every cell of `cells` to exactly one board."""
    if sorted(i for b in boards for i in b.owned) != list(range(len(cells))):
        invalid(f"{name} does not give every cell of its section to exactly one board")


def run_boards(cells: list[str], boards: tuple[Board, ...]) -> None:
    """Run each board in turn, each ending with no machine, and hold it to the cells it owns.

    A board that cannot run here has its cells BLOCKED with the reason; one that does not boot
    FAILS them with it, rather than each failing on the missing session. The table is checked
    both ways, since a cell left out of it would be BLOCKED as never reached, which no verdict
    counts: `boards_cover` at import says it names every cell once, and after each board runs,
    what the board judged must be what it owns.
    """
    judged = CURRENT[0].judged
    for board in boards:
        run, mine = board.run, [cells[i] for i in board.owned]
        if why := board.missing():
            for label in mine:
                blocked(label, why)
            continue
        before = set(judged)
        try:
            run(cells)
        except Blocked as e:
            # A CALL THE MATRIX REFUSED (a wait past the ceiling, a bench copy gone wrong): the
            # cells it left open could not be run, which is BLOCKED and never a FAIL.
            for label in mine:
                if label not in judged:
                    blocked(label, str(e))
        except Exception as e:  # noqa: BLE001 -- a board's end is judged here, whatever it was
            # A CRASH FAILS THE BOARD'S OPEN CELLS: left to the section it would BLOCK them,
            # the next boards' included, and BLOCKED never counts against the run.
            why = (str(e) if isinstance(e, BootFailed)
                   else f"{run.__name__} raised {type(e).__name__}: {e}")
            PENDING.append({"tool": "(board)", "args": {}, "wall_s": 0.0,
                            "reply": {"exception": why, "traceback": traceback.format_exc()}})
            for label in mine:
                if label not in judged:
                    cell(label, False, why)
        finally:
            ensure_closed()
        for label in sorted(x for x in set(judged) - before - set(mine) if x in cells):
            cell(f"{run.__name__} judged a cell the table gives another board: {label}", False)
        for label in mine:
            if label not in judged:
                cell(label, False, f"{run.__name__} owns this cell and never judged it")


# ================================================================ the run itself


def run_sections(name: str) -> None:
    """Run every registered section in order, each on a declaration store of its own, and close
    with the tally and the verdict `finish` prints under `name`: exit 0 with no FAIL, 1 with
    any, 3 when nothing ran or the plan names a cell twice."""
    print(f"transcript: {TRANSCRIPT}")
    planned = [label for sec in SECTIONS for label in sec.labels]
    dupes = sorted({x for x in planned if planned.count(x) > 1})
    print(f"cells PLANNED: {len(planned)} in {len(SECTIONS)} sections")
    if dupes:
        print(f"INVALID: the plan names these cells twice: {dupes}")
        raise SystemExit(EXIT_INVALID)
    t0 = time.monotonic()
    for sec in SECTIONS:
        print(f"\n== [{sec.block}] {sec.title}")
        CURRENT[:] = [sec]
        # A clean declaration store per section: what one section declared cannot re-arm in
        # the next one's `start` and cut its runs.
        isolate_state("mame-live-matrix-state-")
        try:
            sec.run()
        except Exception as e:  # noqa: BLE001 -- the rest of the section is reported, not lost
            reason = f"section aborted: {type(e).__name__}: {e}"
            PENDING.append({"tool": "(matrix)", "args": {}, "wall_s": 0.0,
                            "reply": {"exception": reason, "traceback": traceback.format_exc()}})
            for label in sec.labels:
                if label not in sec.judged:
                    blocked(label, reason)
        for label in sec.labels:
            if label not in sec.judged:
                blocked(label, "never reached: the section ended without judging it")
        try:
            ensure_closed()
        finally:
            _record("(teardown)", "setup")
    run = TALLY["OK"] + TALLY["FAIL"]
    print(f"\ntranscript: {TRANSCRIPT}")
    if KEPT:
        print(f"evidence: {EVIDENCE}")
    print(f"elapsed: {time.monotonic() - t0:.0f} s")
    for label, reason in BLOCKED:
        row("BLOCKED", label, reason)
    print(f"cells: PLANNED {len(planned)}  RUN {run}  OK {TALLY['OK']}  FAIL {TALLY['FAIL']}  "
          f"BLOCKED {TALLY['BLOCKED']}")
    if run == 0:
        print("INVALID: no cell ran, so there is no verdict")
        raise SystemExit(EXIT_INVALID)
    assert len(failures) == TALLY["FAIL"], "the harness and the tally disagree"
    finish(name)
