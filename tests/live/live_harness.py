"""What every live script shares: the board, the run's own declaration store, the ledger of
checks and cells, and the verdict that closes the run.

Importing it puts the repository root on the path, for `demos`; call `isolate_state(prefix)`
before the first `start`.
"""

import atexit
import inspect
import os
import signal
import sys
import tempfile
import time
import traceback
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any

from scry_core import live_ledger, live_pool, prose

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import build_header  # noqa: E402
from evidence import keep  # noqa: E402

from scry_mame import binary as mame_binary  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame.state import STATE  # noqa: E402

from bench_boards import (  # noqa: E402  # isort: skip
    BENCH,
    BINARY as BINARY,
    M68K_DUAL_BINARY,
    M68K_DUAL_ROMS,
    M68K_DUAL_SYSTEM,
    NO_JOYSTICK_INI as NO_JOYSTICK_INI,
    REFERENCE_ROM,
    SYMBOLS,
    args_missing,
    binary_missing,
    m68k_dual_missing,
)

from scry_core.verdict import EXIT_FAIL as EXIT_FAIL  # noqa: E402
from scry_core.verdict import EXIT_INVALID as EXIT_INVALID  # noqa: E402
from scry_core.verdict import EXIT_PASS as EXIT_PASS  # noqa: E402

SCRATCH_PREFIX = "mame-live-matrix-"
SUMMARY_VAR = "MAME_LIVE_SUMMARY"


class _MameLedger(live_ledger.Ledger):
    """The one ledger of a live run; what proves a FAIL here is the session's own scratch."""

    def keep_evidence(self, label: str) -> None:
        if STATE.scratch is None:
            return
        try:
            if (kept := keep(STATE.scratch, self.evidence, label)) is not None:
                self.kept.append(kept)
        except OSError as exc:
            print(f"  evidence NOT kept for {label}: {exc}")


LEDGER = _MameLedger(SCRATCH_PREFIX, SUMMARY_VAR, unjudged="BLOCKED")
RUN = LEDGER.host


def _unfinished() -> None:
    RUN.unfinished(lambda: STATE.kill())


def invalid(message: str) -> None:
    _unfinished()
    print(f"INVALID: {message}", file=sys.stderr)
    sys.exit(EXIT_INVALID)


BOOT = dict(binary=M68K_DUAL_BINARY, system=M68K_DUAL_SYSTEM, rompath=M68K_DUAL_ROMS,
            reference_rom=REFERENCE_ROM, reference_addr="0x0", boot_seconds=25.0, presence=False,
            inipath=NO_JOYSTICK_INI)

#: The `.app` a session is launched as; `MAME_BINARY` stays the executable inside it.
BUNDLE = os.environ.get("MAME_LIVE_BUNDLE", "")

# Unset: each `start`'s default; 1 or 0 forces all behind or in front.
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
    os.environ["XDG_STATE_HOME"] = str(live_tmp(prefix))
    return os.environ["XDG_STATE_HOME"]


def row(word: str, label: str, detail: str = "") -> None:
    print(f"  {word:<4}  {label}{'  ' + detail if detail else ''}")


def check(label: str, condition: bool, detail: str = "") -> None:
    """One check with no section behind it, for a script that plans none."""
    LEDGER.check(label, condition, detail)


def list_blocked() -> None:
    """Repeat the BLOCKED rows the verdict has not yet repeated, so it is read beside them."""
    for label, reason in BLOCKED[LISTED[0]:]:
        row("BLOCKED", label, reason)
    LISTED[0] = len(BLOCKED)


def finish(name: str) -> None:
    """A script that runs no section: close the run, repeat what failed, and speak its verdict."""
    _close_run()
    RUN.finished = True
    print()
    print(f"{prose.counted(len(failures), 'check')} failed")
    for label in failures:
        print(f"  FAIL  {label}")
    list_blocked()
    RUN.leave(kept=bool(failures))
    print(f"==> {name} " + ("FAILED" if failures else "PASSED"))
    sys.exit(EXIT_FAIL if failures else EXIT_PASS)


def _canary_argv() -> list[str] | None:
    if not m68k_dual_missing():
        return mame_binary.canary_argv(str(BOOT["binary"]), str(BOOT["system"]),
                                       str(BOOT["rompath"]))
    if not free_boards_missing():
        return mame_binary.canary_argv(BINARY, "circus", FREE_ROMS,
                                       "-joystickprovider", "none")
    return None


def begin() -> None:
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)):
        signal.signal(sig, _leave)
    atexit.register(_unfinished)
    if why := RUN.begin(_canary_argv(), "MAME"):
        invalid(why)


def _close_run() -> None:
    if line := RUN.close(lambda: STATE.kill()):
        print(line)
        failures.append(line.removeprefix("FAIL  "))


# Made on first write, or every importer would leave a directory.
SCRATCH = RUN.scratch
TRANSCRIPT = SCRATCH / "transcript.jsonl"


def scratch() -> Path:
    return RUN.made()


def live_tmp(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=scratch()))


# Rule B1: a matrix that waits on a hung channel measures the wait. A boot wait is exempt.
WAIT_CEILING_S = 10.0
START_WAIT_S = 30.0
WAIT_ARGS = ("seconds", "settle_seconds")
#: Starts the reason of a cell BLOCKED by the wait ceiling.
B1_PREFIX = "B1: "


SECTIONS = LEDGER.sections
PENDING = LEDGER.calls
BLOCKED = LEDGER.blocked_why
#: The detail of every FAIL, for a pooled job's summary.
FAIL_WHY = LEDGER.reasons
#: How many of `BLOCKED` the verdict has already repeated.
LISTED = [0]
TALLY = LEDGER.tally
# A FAILED cell's session logs, copied out before `close` deletes its scratch.
EVIDENCE = LEDGER.evidence
KEPT = LEDGER.kept
failures = LEDGER.failed
Section = live_ledger.Section
Cell = live_ledger.Cell
Blocked = live_ledger.Blocked


def section(block: str, title: str, labels: list[str], alone: bool = False,
            spans: bool = False, opens: bool = False
            ) -> Callable[[Callable[[], None]], Callable[[], None]]:
    return LEDGER.section(block, title, [live_ledger.Cell(label) for label in labels],
                          alone=alone, spans=spans, opens=opens)


cannot_be_judged = live_ledger.cannot_be_judged


def cell(label: str, condition: bool, detail: str = "") -> None:
    """The verdict of one planned cell; an unplanned or repeated label FAILs."""
    LEDGER.judge(label, condition, detail)


def blocked(label: str, reason: str) -> None:
    """A BLOCKED row; outside a section (`live_check.py` runs none) it is the row and the tally."""
    LEDGER.block(label, reason)


def folded(name: str, kw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tool, _, value = name.partition(" ")
    if not value:
        return tool, kw
    return tool, {"kind" if tool.startswith("declaration_") else "method": value, **kw}


def call(tool: str, b1_exempt: str = "", **kw: Any) -> dict[str, Any]:
    """Call a tool the way the client would, keeping the whole reply for the transcript.

    An exception becomes a reply carrying it. A wait above the ceiling raises `Blocked` unless
    `b1_exempt` says why this call cannot wait. A fold is named `<tool> <value>`.
    """
    tool, kw = folded(tool, kw)
    fn = getattr(s, tool)
    if why := args_missing(kw):
        raise Blocked(why)
    if tool == "start" and BACKGROUND is not None:
        kw.setdefault("background", BACKGROUND)
    if tool == "start":
        kw.setdefault("presence", False)
    params = inspect.signature(fn).parameters
    for name in WAIT_ARGS:
        if name in params:
            value = kw.get(name, params[name].default)
            if isinstance(value, int | float) and value > WAIT_CEILING_S and not b1_exempt:
                raise Blocked(f"{B1_PREFIX}{tool}({name}={value}) may wait past "
                              f"{WAIT_CEILING_S:g} s")
    t0 = time.monotonic()
    try:
        reply: dict[str, Any] = fn(**kw)
    except Exception as e:  # noqa: BLE001 -- the reply IS the evidence of the exception
        reply = {"exception": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}
    LEDGER.record(tool, kw, time.monotonic() - t0, reply)
    return reply


def last_wall() -> float:
    return float(PENDING[-1]["wall_s"]) if PENDING else 0.0

# A board boots throttled to real speed, so a frame run goes in legs inside one call's wait; a
# leg that ran out short is BLOCKED, never a FAIL of what a cell read next.
REAL_SPEED_FPS = 60
LEG_FRAMES = int(WAIT_CEILING_S * REAL_SPEED_FPS) // 2


def run_frames(frames: int, leg_frames: int = LEG_FRAMES) -> dict[str, Any]:
    if frames < 1 or leg_frames < 1:
        raise ValueError(f"run_frames runs at least one frame in legs of at least one, not "
                         f"{frames} in legs of {leg_frames}")
    end: int | None = None
    left = frames
    while True:
        leg = min(left, leg_frames)
        began = time.monotonic()
        reply = call("run_for", frames=leg, seconds=WAIT_CEILING_S)
        spent = time.monotonic() - began
        before, after = reply.get("frame_before"), reply.get("frame_after")
        if not (isinstance(before, int) and isinstance(after, int)):
            return reply
        # A loaded host runs slow, it does not stop: a counter that stood still is the cell's.
        if (reply.get("code") == "not_settled" and before < after < before + leg
                and spent >= WAIT_CEILING_S):
            raise Blocked(f"run_for({leg} frames, {WAIT_CEILING_S:g} s) reached frame {after} "
                          f"of {before + leg} in {spent:.1f} s: the host could not hold the "
                          "board's speed, so this known answer was not reached")
        if not ok(reply) or reply.get("verdict") != "ELAPSED":
            return reply
        end = before + frames if end is None else end
        left = end - after
        if left <= 0:
            return reply



def whole(r: dict[str, Any]) -> bool:
    keys = list(r)
    if not keys or keys[0] != "summary" or keys[-1] != "session":
        return False
    if r.get("status") == "ok":
        return True
    return r.get("status") == "INVALID" and bool(r.get("code")) and bool(r.get("message"))


def ok(r: dict[str, Any]) -> bool:
    return whole(r) and r.get("status") == "ok"


def unavailable_why(value: Any) -> str | None:
    return value.get("why") if isinstance(value, dict) and value.get("available") is False else None


def rearm_pairs(rearm: dict[str, Any], which: str) -> list[tuple[str | None, str | None]]:
    return [(e.get("ref"), e.get("cpu") if isinstance(e.get("cpu"), str) else None)
            for e in rearm.get(which, [])]


def refused(r: dict[str, Any], *codes: str) -> bool:
    return whole(r) and r.get("status") == "INVALID" and (not codes or r.get("code") in codes)


def visible_of(cpu_info: dict[str, Any]) -> str | None:
    return next((row["cpu"] for row in cpu_info.get("cpus") or [] if row["visible"] is True),
                None)


def ignored_of(cpu_info: dict[str, Any]) -> list[str] | None:
    rows = cpu_info.get("cpus") or []
    if not rows or any(not isinstance(row["ignored"], bool) for row in rows):
        return None
    return [row["cpu"] for row in rows if row["ignored"] is True]


def said(r: dict[str, Any], limit: int = 110) -> str:
    text = r.get("exception") or r.get("summary") or str(r)[:limit]
    return str(text)[:limit]


def session_is(r: dict[str, Any], alive: bool, running: bool) -> bool:
    ses = r.get("session", {})
    return ses.get("alive") is alive and ses.get("running") is running


_names = count(1)


def fresh(suffix: str) -> str:
    return str(scratch() / f"f{next(_names)}{suffix}")


def fresh_state() -> str:
    return f"m{next(_names)}"


def boot(**extra: Any) -> dict[str, Any]:
    kw: dict[str, Any] = {**BOOT, "symbols": SYMBOLS, **extra}
    if kw["symbols"] is None:
        kw.pop("symbols")
    return call("start", **kw)


def ensure_closed() -> None:
    try:
        alive = s.status().get("session", {}).get("alive")
    except Exception:  # noqa: BLE001 -- a status that cannot answer is a machine to close
        alive = True
    if alive:
        call("close")


# A run that dies half-way must not leave a MAME on the owner's display.
atexit.register(lambda: STATE.kill())


FREE_ROMS = os.environ.get("MAME_TEST_ROMS", "")


def free_image(system: str, members: list[str], dest: Path, held: Path | None = None) -> str:
    """The reference image of a free set out of its zip: one file, or two byte-interleaved."""
    with zipfile.ZipFile((held or Path(FREE_ROMS)) / f"{system}.zip") as z:
        parts = [z.read(m) for m in members]
    data = (parts[0] if len(parts) == 1
            else bytes(b for pair in zip(*parts, strict=True) for b in pair))
    out = dest / f"{system}.ref"
    out.write_bytes(data)
    return str(out)


def no_joystick_ini(extra: str = "") -> str:
    """An ini directory naming no joystick provider (`NO_JOYSTICK_INI`); `extra` lines follow it
    in one of the run's own."""
    if not extra:
        return NO_JOYSTICK_INI
    ini = Path(fresh("-ini"))
    ini.mkdir()
    (ini / "mame.ini").write_text("joystickprovider none\n" + extra)
    return str(ini)


class BootFailed(Exception):
    """A board's `start` was not `ok`."""


def require_booted(system: str, r: dict[str, Any]) -> dict[str, Any]:
    """`r` if the `start` booted; else `BootFailed`, which `run_boards` turns into FAILs."""
    if ok(r):
        return r
    tail = str(r.get("stdout_tail") or "").strip().splitlines()
    raise BootFailed(f"start {system}: {str(r.get('message') or said(r))[:200]} / "
                     f"{tail[-1][:200] if tail else 'no stdout_tail'}")


def free_boot(system: str, members: list[str], addr: str, ini_extra: str = "",
              binary: str = "", **launch: Any) -> dict[str, Any]:
    binary = binary or BUNDLE or BINARY
    folder = Path(fresh("-image"))
    folder.mkdir()
    image = free_image(system, members, folder)
    return require_booted(system, call(
        "start", binary=binary, system=system, rompath=FREE_ROMS, reference_rom=image,
        reference_addr=addr, reference_base=addr, inipath=no_joystick_ini(ini_extra),
        boot_seconds=START_WAIT_S, **launch))


def circus_boot(ini_extra: str = "", **launch: Any) -> dict[str, Any]:
    return free_boot("circus", ["9004a.1a"], "0x1000", ini_extra, **launch)


def free_boards_missing() -> str:
    if why := binary_missing():
        return f"{why}, to run the free boards"
    return "" if FREE_ROMS and Path(FREE_ROMS).is_dir() else (
        "set MAME_TEST_ROMS (the sets' zips) to run the free boards")


# Kept in its own folder: MAME wants a dump of its PAL that the set lacks, and runs once a file of
# that size stands in, because the driver never reads the `pld` region.
PANGOFUN_FOLDER = "pending-pangofun"
PANGOFUN_PAL_NAME = "palce20v8h.u42"
PANGOFUN_PAL_BYTES = 0x157


def pangofun_missing() -> str:
    zip_path = Path(FREE_ROMS) / PANGOFUN_FOLDER / "pangofun.zip"
    return free_boards_missing() or ("" if zip_path.is_file()
                                     else f"{PANGOFUN_FOLDER}/pangofun.zip not in MAME_TEST_ROMS")


def pangofun_boot() -> dict[str, Any]:
    held = Path(FREE_ROMS) / PANGOFUN_FOLDER
    rompath = Path(fresh("-roms"))
    (rompath / "pangofun").mkdir(parents=True)
    for z in held.glob("*.zip"):
        (rompath / z.name).symlink_to(z)
    (rompath / "pangofun" / PANGOFUN_PAL_NAME).write_bytes(bytes(PANGOFUN_PAL_BYTES))
    # The 64 KB bios ends at 4 GB, and the i386 family resets 16 bytes below the top.
    return require_booted("pangofun", call(
        "start", binary=BINARY, system="pangofun", rompath=str(rompath),
        reference_rom=free_image("pangofun", ["bios.bin"], rompath, held),
        reference_addr="0xfffffff0", reference_base="0xffff0000", inipath=no_joystick_ini(),
        boot_seconds=START_WAIT_S))


# A PC such as 0x0000 reads the same reversed, so it would judge no byte order.
PC_STEPS_MAX = 50


def pc_of(reply: dict[str, Any]) -> str | None:
    return next((str(v) for k, v in (reply.get("regs") or {}).items() if k.lower() == "pc"), None)


def tells_byte_order(pc: object) -> bool:
    if not isinstance(pc, str) or not pc.startswith("0x") or len(pc) % 2:
        return False
    raw = bytes.fromhex(pc[2:])
    return raw != raw[::-1]


def registers_at_a_telling_pc(cpu: str = "") -> dict[str, Any]:
    """`registers` of `cpu` at a stop whose PC tells the byte order, stepping up to `PC_STEPS_MAX`
    times; a refused read or step is returned at once."""
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
    """MAME's console `print <symbol>` for `cpu` when named, restoring the visible cpu after.
    None when `focus` was refused or ran the machine, or the answer is not a number."""
    before = visible_of(call("cpu_info")) if cpu else None
    if cpu:
        shown = call("cpu_focus", cpu=cpu)
        if not ok(shown) or shown.get("machine_ran") is not False:
            return None
    words = str(call("debug", command=f"print {symbol}").get("output", "")).split()
    if before is not None and before != cpu:
        call("cpu_focus", cpu=before)
    return int(words[0], 16) if words and all(
        c in "0123456789abcdefABCDEF" for c in words[0]) else None


def make_visible(cpu: str) -> bool:
    return ok(call("cpu_focus", cpu=cpu)) and visible_of(call("cpu_info")) == cpu


def zips_missing(*systems: str) -> str:
    absent = [s for s in systems if not (Path(FREE_ROMS) / f"{s}.zip").is_file()]
    return f"{', '.join(absent)} not in MAME_TEST_ROMS" if absent else ""


@dataclass(frozen=True)
class Board:
    """A board's run, the cells it judges, and why it cannot run here (empty when it can),
    stated rather than defaulted so a new board does not run unguarded."""
    run: Callable[[list[str]], None]
    owned: tuple[int, ...]
    missing: Callable[[], str]


def boards_cover(name: str, cells: list[str], boards: tuple[Board, ...]) -> None:
    if sorted(i for b in boards for i in b.owned) != list(range(len(cells))):
        invalid(f"{name} does not give every cell of its section to exactly one board")


def run_boards(cells: list[str], boards: tuple[Board, ...]) -> None:
    """Run each board in turn and hold it to the cells it owns: BLOCKED when it cannot run here,
    FAILED when it does not boot."""
    assert LEDGER.current is not None
    judged = LEDGER.current.judged
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
            for label in mine:
                if label not in judged:
                    blocked(label, str(e))
        except Exception as e:  # noqa: BLE001 -- a board's end is judged here, whatever it was
            # BLOCKED never counts against the run, so a crash FAILS the open cells.
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


SECTIONS_VAR = "MAME_LIVE_SECTIONS"
JOBS_VAR = "MAME_LIVE_JOBS"


def _chosen() -> list[Section]:
    wanted = os.environ.get(SECTIONS_VAR, "").strip().upper()
    letters = {sec.block for sec in SECTIONS}
    if unknown := sorted(set(wanted) - letters):
        print(f"INVALID: {SECTIONS_VAR} names no section {unknown}; "
              f"there are {''.join(sorted(letters))}")
        raise SystemExit(EXIT_INVALID)
    return [sec for sec in SECTIONS if not wanted or sec.block in wanted]


def _workers() -> int:
    held = os.environ.get(JOBS_VAR, "").strip()
    if not held:
        return live_pool.default_workers()
    if not (held.isascii() and held.isdigit() and int(held) >= 1):
        print(f"{JOBS_VAR}={held!r} is not a job count: a whole number, at least 1")
        raise SystemExit(2)
    return int(held)


def _pool(pooled: list[Section], workers: int) -> live_pool.PoolResult:
    out = scratch() / "jobs"
    print(f"jobs: {workers} at once, logs and summaries in {out}", flush=True)
    letters = sorted({sec.block for sec in pooled})
    script = str(Path(sys.argv[0]).resolve())
    jobs = [live_pool.Job(letter, [sys.executable, script],
                          env={SECTIONS_VAR: letter, JOBS_VAR: "1", **RUN.job_env(letter)},
                          planned=tuple(x for sec in pooled if sec.block == letter
                                        for x in sec.labels))
            for letter in letters]

    def ended(r: live_pool.JobResult) -> None:
        n = {k: sum(1 for v in r.outcomes().values() if v == k) for k in ("OK", "FAIL", "BLOCKED")}
        print(f"  [{r.job.name}] OK {n['OK']} FAIL {n['FAIL']} BLOCKED {n['BLOCKED']}  "
              f"{r.elapsed_s:.0f} s  log: {r.log}", flush=True)
    return live_pool.run_pool(jobs, workers, out, SUMMARY_VAR, on_done=ended)


def _invalid_run(why: str) -> None:
    _unfinished()
    print(f"INVALID: {why}")
    raise SystemExit(EXIT_INVALID)


def _leave(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def _kill_the_machine() -> None:
    STATE.kill()


def run_sections(name: str) -> None:
    """Run the chosen sections in order, then the tally and the verdict `name` speaks for: exit 0
    with no FAIL, 1 with any, 3 when nothing ran, a cell is planned twice or a pooled merge is not
    believable. With more than one job (`MAME_LIVE_JOBS`) sections not `alone` run one job per
    letter."""
    chosen = _chosen()
    summary = os.environ.get(SUMMARY_VAR, "")
    workers = _workers()
    begin()
    if not summary:
        for line in build_header.lines(BENCH.root, str(M68K_DUAL_BINARY), BINARY):
            print(line)
        if workers <= 1:
            print("jobs: 1, every section in this process", flush=True)
    LEDGER.on_end = _kill_the_machine

    def _isolate(_block: str) -> None:
        # What one section declared must not re-arm in the next one's `start`.
        isolate_state("mame-live-matrix-state-")

    rc = LEDGER.run([sec.block for sec in chosen], dict(os.environ), ensure_closed, _isolate,
                    pool=(lambda pooled: _pool(pooled, workers))
                    if workers > 1 and not summary else None,
                    summary=Path(summary) if summary else None, name=name)
    assert len(failures) == TALLY["FAIL"], "the harness and the tally disagree"
    sys.exit(rc)
