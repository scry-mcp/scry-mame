"""What the server holds between calls: the one live machine, reached through `STATE`."""

from __future__ import annotations

import contextlib
import functools
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Literal, NoReturn, overload

from scry_core import boundary, cancel, guardian, picture, presence, screen_map
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_declarations as dec
import mame_idle as idle
import mame_inputs as inputs
import mame_presence as mpresence

if TYPE_CHECKING:
    import mame_cycles
    import mame_manifest
    import mame_scan

ROWS_SHOWN = 24
# Reply size in JSON characters, under the client's token limit (`MAX_MCP_OUTPUT_TOKENS`); an
# estimate at >= ~2 characters a token, asserted by the tests that build the longest list reply.
REPLY_BUDGET_CHARS = 40000


def utc_now() -> datetime:
    return datetime.now(UTC)


def now() -> str:
    return utc_now().isoformat(timespec="seconds")


# `close` waits QUIT_GRACE_S for a clean exit (it writes `cfg/` and `nvram/`) before SIGKILL;
# REAP_GRACE_S is the separate wait for the killed process to be reaped.
QUIT_GRACE_S = 5.0
REAP_GRACE_S = 5.0
EXIT_POLL_S = 0.1
NO_TABLE = gs.SymbolTable({}, {}, "none")


def wait_exit(proc: subprocess.Popen[bytes], seconds: float, progress: mprogress.Progress,
              what: str) -> int | None:
    """The exit code within `seconds`, or None; reports progress because `close` is watched."""
    clock = mprogress.Ticker(seconds, progress)
    while True:
        try:
            return int(proc.wait(timeout=EXIT_POLL_S))
        except subprocess.TimeoutExpired:
            pass
        if clock.expired():
            return None
        clock.tick("{what}, {elapsed:.0f}s of {seconds:g}", what=what, seconds=seconds)


def no_machine() -> NoReturn:
    why = idle.IDLE.note()
    raise Invalid("no_session", f"no machine running{'; ' + why if why else ''}; call `start` "
                  "first")


# One lock for one machine: overlapping calls would steal each other's breakpoints and stops.
LOCK = boundary.ServerLock()


class State:

    def __init__(self) -> None:
        # Outlives sessions: `origin` stamps stay unique across `close`/`start`. Not in `_reset`.
        self.start_seq = 0
        # A cancelled call's record rides on the next closing reply. Not in `_reset`.
        self.cancelled: cancel.Cancelled | None = None
        # Outlives a session: the file layer of `map_write(method="load")`.
        self.maps = screen_map.Maps()
        self._reset()

    def _reset(self) -> None:
        """Every per-session field at its pre-session value, shared by `__init__` and `kill`."""
        self.proc: subprocess.Popen[bytes] | None = None
        self.guard: subprocess.Popen[bytes] | None = None
        self.presence = presence.Shown()
        self.ses: gs.Session | None = None
        # Symbol tables by cpu tag: each cpu runs its own program. Read through `table`.
        self.tables: dict[str | None, gs.SymbolTable] = {}
        self.first_cpu: str | None = None
        self.system: str = ""
        self.boot_pc: int | None = None
        self.view: str | dict[str, Any] = "native"
        # Breakpoints armed here, by row index (MAME's counter spans cpus): `owner`, `addr`, `cpu`.
        self.breakpoints: dict[int, dict[str, Any]] = {}
        self.regpoints: dict[dec.Owner, dict[str, Any]] = {}
        # What the last pane feed said of each comment (`armed`/`unarmable`), for `comment_list`.
        self.comment_feed: dict[dec.Owner, dict[str, Any]] = {}
        self.conditions_unresolved: set[tuple[str, dec.Owner]] = set()
        self.console_writes: int = 0
        self.scratch: Path | None = None
        self.state_dir: str = ""
        self.cfg: dict[str, Any] | None = None
        self.port: int = 0
        self.stdout_log: IO[bytes] | None = None
        self.snapshots: int = 0
        self.debug_dumps: int = 0
        self.batches: int = 0
        self.recordings: int = 0
        self.captures: list[tuple[str, str]] = []
        # The open value scan; it outlives runs because the next filter compares current memory.
        self.scan: mame_scan.Scan | None = None
        # Console stdout offset read up to; raw `lua` calls, each a write (Lua text cannot say).
        self.console_mark: int = 0
        self.lua_calls: int = 0
        # Raw `lua` calls declared read-only: not counted as writes, but the claim is unverifiable.
        self.lua_read_only_claims: int = 0
        self.lua_seq: int = 0
        self.lua_answered: int = 0
        self.lua_lost: int = 0
        self.lua_pending: dict[int, tuple[str, int]] = {}
        # Pending calls this server composed (a tap install): the next reader's prompt settles them.
        self.lua_ours: set[int] = set()
        self.console_thread_errors: int = 0
        # Death count read up to here by position, so it is exactly-once across overlapping paths.
        self.console_counted: int = 0
        self.console_reruns_seen: int = 0
        self.console_lines_lost: int = 0
        # A `debug` run (`g`) sends no stop packet; the frame counter proves its stop.
        self.console_run: bool = False
        # A run the counter cannot prove (`no_progress`); only `stop`'s interrupt ends it.
        self.console_run_unprovable: bool = False
        self.unprovable_peek: int = 0
        self.states: dict[str, dict[str, Any]] = {}
        self.state_signature: int | None = None
        self.stale_counter: mame_cycles.StaleCounter | None = None
        self.reference: tuple[Path, int, int] | None = None
        # The last stop as its survey saw it; empty before the first stop.
        self.last_stop: dict[str, Any] = {}
        self.errorlog_mark: int = 0
        # A stop reached on its own, reported once on the next contact's reply.
        self.found_stop_last: dict[str, Any] = {}
        self.throttle_seen = False
        # Emulated and wall time at the last release, for the run's host speed; None when stopped.
        self.run_release: dict[str, float] | None = None
        # The declaration store, and the `origin` stamp that marks its own declarations.
        self.store: dec.DeclarationStore | None = None
        self.session_origin: str | None = None
        self.fingerprints: dict[str | None, str] = {}
        # Change watches armed, by owner: address, length, cpu, `wplist` row, last bytes (`before`).
        self.armed_watches: dict[dec.Owner, dict[str, Any]] = {}
        self.tallies: dict[dec.Owner, dict[str, Any]] = {}
        # Removals sent, unanswered; the record drops at send (`mame_tap.read_removal_answers`).
        self.tally_removals: list[dict[str, Any]] = []
        # Throttle switches unconfirmed, and those found not applied (latches; see `REFERENCE.md`).
        self.throttles_pending: list[dict[str, Any]] = []
        self.throttles_not_applied: list[dict[str, Any]] = []
        # Controls armed, by owner: address, `temp` hit counter, `bplist` row, `missed` hits.
        self.controls: dict[dec.Owner, dict[str, Any]] = {}
        self.debuglog_mark: int = 0
        self.machine_map: dict[str, Any] = {}
        # The console's frame counter: `frame`, `frame0` on several screens, None with no screen.
        self.frame_symbol: str | None = "frame"
        self.cpus: list[str] = []
        self.manifest: mame_manifest.Manifest | None = None
        self.evidence: dict[str, list[dict[str, Any]]] = {"locates": [], "sweeps": [],
                                                          "choices": []}

    def origin(self) -> str:
        """One stamp per `start`, unique across sessions and processes."""
        self.start_seq += 1
        return f"{now()}#{os.getpid()}.{self.start_seq}"

    def remember_stop(self, ses: gs.Session, pc: int, regs: dict[str, Any], frame: int | None,
                      cause: str, watch_hit: dict[str, Any] | None = None,
                      cpu: str | None = None) -> dict[str, Any]:
        self.last_stop = {
            "seq": int(self.last_stop.get("seq", 0)) + 1,
            "pc": hex_addr(pc),
            "cpu": cpu,
            "regs": dict(regs),
            "frame": frame,
            "cause": cause,
            "packet": ses.last_stop_packet,
            "stop_count": ses.stop_count,
            "when": time.monotonic(),
            "wall_at": now(),
        }
        if watch_hit is not None:
            self.last_stop["watch_hit"] = dict(watch_hit)
        return self.last_stop

    def record_image(self, path: Path) -> None:
        entry = ("image", str(path))
        if entry not in self.captures:
            self.captures.append(entry)

    def take_cancelled(self) -> cancel.Cancelled | None:
        record, self.cancelled = self.cancelled, None
        return record

    def end_call(self) -> None:
        """Drop the one-time account of a self-reached stop."""
        self.found_stop_last = {}

    def as_of(self) -> dict[str, Any]:
        if not self.last_stop:
            return unavailable(NO_STOP_YET_WHY)
        return {"stop_seq": self.last_stop["seq"], "pc": self.last_stop["pc"],
                "cpu": or_unavailable(self.last_stop.get("cpu"), NO_CPU_READ_WHY),
                "frame": frame_shown(self.last_stop["frame"]),
                "cause": self.last_stop["cause"],
                "since_s": spent_s(time.monotonic() - float(self.last_stop["when"])),
                "wall_at": self.last_stop["wall_at"]}

    def alive(self) -> gs.Session:
        if self.ses is None or self.proc is None:
            no_machine()
        code = self.proc.poll()
        if code is not None:
            # A machine that died is not "no machine": `close` reads its last words first.
            raise Invalid("session_broken",
                          f"MAME exited with code {code} under this session: `close` collects "
                          "its exit code and the last lines of each channel before the scratch "
                          "is deleted, then `start` a new one", exit_code=code)
        return self.ses

    def presence_shown(self) -> bool | dict[str, Any]:
        if self.presence.held is None:
            return self.presence.refused
        if self.proc is not None and self.proc.poll() is not None:
            return unavailable("MAME has exited under this session")
        why = mpresence.broken(self.scratch) if self.scratch is not None else ""
        return unavailable(f"the drawer stopped: {why}") if why else self.presence.held.reply()

    def live(self) -> tuple[gs.Session, Path]:
        ses = self.alive()
        assert self.scratch is not None
        return ses, self.scratch

    @property
    def broken(self) -> str | None:
        """Why the session can no longer be trusted, None with no session."""
        return self.ses.broken if self.ses is not None else None

    def next_number(self, kind: Literal["snapshots", "debug_dumps", "batches",
                                        "recordings"]) -> int:
        number = int(getattr(self, kind)) + 1
        setattr(self, kind, number)
        return number

    def altered(self) -> int:
        return (self.ses.writes if self.ses else 0) + self.console_writes + self.lua_calls

    def table(self, cpu: str | None = None) -> gs.SymbolTable:
        """`cpu`'s symbol table (first cpu's when None); a None-keyed table serves every cpu."""
        if None in self.tables:
            return self.tables[None]
        return self.tables.get(self.first_cpu if cpu is None else cpu, NO_TABLE)

    def table_owner(self, cpu: str | None = None) -> str | None:
        return None if None in self.tables else (self.first_cpu if cpu is None else cpu)

    def fingerprint(self, cpu: str | None = None) -> str | None:
        first = self.fingerprints.get(self.first_cpu)
        return first if cpu is None else self.fingerprints.get(cpu, first)

    def resolve(self, ref: str, cpu: str | None = None) -> int:
        """Where a ref points on `cpu`: a `0x` address or a symbol; an unknown name fails."""
        symbols = self.table(cpu).table
        text = ref.strip()
        if inputs.classify(text, symbols, cpu or self.first_cpu) == "address":
            return int(text, 16)
        if text.upper() in symbols:
            return symbols[text.upper()]
        raise Invalid("unknown_ref", inputs.not_a_ref("the ref", text, self.table_owner(cpu),
                                                      loaded=len(symbols)))

    def resolve_named(self, what: str, text: str, cpu: str | None = None) -> int:
        """`resolve` with a refusal naming the ref as `what`."""
        try:
            return self.resolve(text, cpu)
        except inputs.BareHex:
            raise
        except Invalid:
            raise Invalid("unknown_ref", inputs.not_a_ref(f"the {what}", text,
                                                          self.table_owner(cpu))) from None

    def _cfg_file(self) -> Path | None:
        root = self.state_dir or self.scratch
        if not root or not self.system:
            return None
        return Path(root) / "cfg" / f"{self.system}.cfg"

    def _cfg_marker(self) -> int | None:
        path = self._cfg_file()
        if path is None:
            return None
        return path.stat().st_mtime_ns if path.exists() else -1

    def _cfg_written(self, marker: int | None) -> bool | None:
        path = self._cfg_file()
        if path is None or marker is None:
            return None
        return path.exists() and path.stat().st_mtime_ns > marker

    def repaintable(self, scratch: Path) -> gs.Session | None:
        ses = self.ses
        if (ses is None or self.scratch != scratch or ses.running or self.broken is not None
                or not self.machine_alive()):
            return None
        return ses

    def machine_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def kill(self, progress: mprogress.Progress = mprogress.no_progress,
             grace: bool = True) -> dict[str, Any]:
        """End the session: ask MAME to QUIT through its console, then kill (`grace=False`: now).

        `ended_by`: `quit` (exited in grace and wrote its cfg), `exited` (no cfg), `killed`, `died`
        (already exited), `none`.
        """
        ended: dict[str, Any] = {"ended_by": "none", "exit_code": None,
                                 "state_written": None}
        if self.proc is not None and self.proc.poll() is not None:
            ended = {"ended_by": "died", "exit_code": self.proc.poll(),
                     "state_written": None}
        elif self.proc is not None:
            marker = self._cfg_marker()
            polite = grace and not self.broken
            if self.ses is not None and polite:
                with contextlib.suppress(gs.SessionError, OSError):
                    self.ses.quit()
            code = (wait_exit(self.proc, QUIT_GRACE_S, progress, "close: waiting for MAME to quit")
                    if polite else None)
            if code is not None:
                written = self._cfg_written(marker)
                ended = {"ended_by": "exited" if written is False else "quit", "exit_code": code,
                         "state_written": written}
            else:
                self.proc.kill()
                ended["ended_by"] = "killed"
                ended["state_written"] = False
                ended["exit_code"] = wait_exit(self.proc, REAP_GRACE_S, progress,
                                               "close: waiting for the SIGKILLed MAME to be reaped")
                if ended["exit_code"] is None:
                    ended["exit_code"] = unavailable(
                        f"pid {self.proc.pid} was SIGKILLed and still not reaped "
                        f"{REAP_GRACE_S} s later: an emulator may still be on the machine")
        # The installed cfg is read before the scratch goes: whether it still equals the repo's.
        if self.cfg is not None:
            installed = Path(self.cfg["installed"])
            changed: bool | dict[str, Any]
            try:
                changed = installed.read_bytes() != Path(self.cfg["source"]).read_bytes()
            except OSError as e:
                changed = unavailable(f"could not be read back: {e}")
            ended["cfg"] = {"installed_path": str(installed), "changed": changed}
        else:
            ended["cfg"] = unavailable(NO_CFG_WHY)
        if ended["exit_code"] is None:
            ended["exit_code"] = unavailable("no session was running")
        if ended["state_written"] is None:
            ended["state_written"] = unavailable(
                "no session was running" if ended["ended_by"] == "none" else
                "MAME had already exited, so this close saw no write" if ended["ended_by"] == "died"
                else "there was no cfg file to read MAME's write from")
        # Teardown first, each guarded so a raise cannot skip `_reset`.
        if self.ses:
            with contextlib.suppress(OSError):
                self.ses.close()
        if self.stdout_log:
            with contextlib.suppress(OSError):
                self.stdout_log.close()
        self.presence.close()
        # `state_dir` is the caller's and is never deleted.
        if self.scratch and self.scratch.exists():
            shutil.rmtree(self.scratch, ignore_errors=True)
        # The guardian stops only after MAME is reaped.
        if self.proc is None or self.proc.poll() is not None:
            guardian.stop(self.guard)
        self._reset()
        return ended


STATE = State()
publish = functools.partial(picture.publish, record=STATE.record_image)
data_file = functools.partial(picture.data_file, record=STATE.record_image)


# Re-exported so every module raises one name.
Invalid = contract.Invalid


def last_stop_frame() -> int | None:
    frame = (STATE.last_stop or {}).get("frame")
    return frame if isinstance(frame, int) else None


def stopped_frame() -> int | None:
    ses = STATE.ses
    return None if ses is None or ses.running else last_stop_frame()

def refuse_broken(ses: Any) -> None:
    reason = ses.broken
    if reason:
        raise Invalid("session_broken",
                      f"this session broke and nothing it answers can be trusted any more: "
                      f"{reason}. `close` it, then `start` a new one", broken=reason)


def mark_fields(line: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in re.findall(r'(\w+)=("[^"]*"|\S+)', line)}


def mark_lines(lines: list[str], tag: str) -> list[str]:
    closed = re.compile(re.escape(tag) + r"(?!\d)")
    return [ln for ln in lines if closed.search(ln)]


def mark_line(lines: list[str], tag: str) -> str | None:
    """The first line carrying `tag`, with the digits of its number closed.

    `...#1` matches `...#10`, so a bare substring test answers an older switch off a later line.
    """
    return next(iter(mark_lines(lines, tag)), None)


def settle_throttles(lines: list[str]) -> None:
    """Judge each pending throttle against `lines` (the error log since the last stop).

    Reads, never resends; a mark-less switch the console has answered past was never applied,
    and its row latches.
    """
    for rec in list(STATE.throttles_pending):
        seen = mark_line(lines, rec["tag"])
        if seen is not None:
            said = mark_fields(seen).get("throttled")
            # `on` is a bool everywhere; an unanticipated value is kept verbatim.
            reports: Any = {"true": True, "false": False}.get(said or "", said)
            STATE.throttles_pending.remove(rec)
            if reports is not rec["on"]:
                STATE.throttles_not_applied.append(
                    {"tag": rec["tag"], "asked": rec["on"], "machine_reports": reports,
                     "why": "the machine reports a throttle setting that is not the one this "
                            "session asked for. Ask again and read the answer; this row "
                            "records what happened and stands for the rest of the session"})
        elif STATE.lua_answered >= rec["seq"]:
            STATE.throttles_pending.remove(rec)
            STATE.throttles_not_applied.append(
                {"tag": rec["tag"], "asked": rec["on"],
                 "machine_reports": unavailable("the tag was never logged, so the machine "
                                                "reported nothing"),
                 "why": "the console worked past this line and never logged its tag, so the "
                        "switch was NEVER applied: the speed of everything measured since is "
                        "not the one that was asked for. Ask for it again; this row records "
                        "what happened and stands for the rest of the session"})


def bare_tag(tag: str | None) -> str:
    return (tag or "").lstrip(":")


# The line a Lua chunk ends on, `<LUA_SENTINEL>#<seq>`.
LUA_SENTINEL = "MAME_MCP_LUA_END"


def sentinel_line(seq: int) -> str:
    return f"{LUA_SENTINEL}#{seq}"


def hex_addr(addr: int) -> str:
    return f"{addr:#010x}"


# Reply reasons: `note` (a string), `why` (a row's), `unavailable(why)` in place of a datum.
NOTE_SEPARATOR = "; "


def join_notes(*parts: str | None) -> str | None:
    said = list(dict.fromkeys(p for p in parts if p))
    return NOTE_SEPARATOR.join(said) if said else None


def add_note(reply: dict[str, Any], *parts: str | None) -> dict[str, Any]:
    note = join_notes(reply.get("note"), *parts)
    if note is not None:
        reply["note"] = note
    return reply




NO_STOP_YET_WHY = "this session has not stopped yet"

NO_CFG_WHY = "no cfg was given, so MAME runs on its defaults"

NO_CPU_READ_WHY = "no cpu could be named: `cpulist` marked none visible"

NO_CPU_NAMED_WHY = "no cpu was named, so the rows are every cpu's"


NO_COUNTER_WHY = "this machine has no frame counter, so no frame was read"
FRAME_UNREAD_WHY = "the console did not answer the frame counter when it was read"


def frame_shown(frame: int | None) -> int | dict[str, Any]:
    """A recorded frame as a reply carries it: the number, or `unavailable` with why."""
    if frame is not None:
        return frame
    return unavailable(NO_COUNTER_WHY if STATE.frame_symbol is None else FRAME_UNREAD_WHY)


def merged(*parts: dict[str, Any]) -> dict[str, Any]:
    """Reply fields from several sources; notes are joined, any other repeated key raises."""
    out: dict[str, Any] = {}
    for part in parts:
        twice = sorted((out.keys() & part.keys()) - {"note"})
        if twice:
            raise TypeError(f"{twice} said by two sources of one reply")
        note = out.get("note")
        out.update(part)
        if note is not None and "note" in part:
            out["note"] = join_notes(note, part["note"])
    return out


# Seconds: `spent_s` (0.1) for spans a reader acts on, `measured_s` (1e-6) for measurements.
def spent_s(seconds: float) -> float:
    return round(seconds, 1)


@overload
def measured_s(seconds: float) -> float: ...
@overload
def measured_s(seconds: None) -> None: ...
def measured_s(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds, 6)


# Neither end was carried out; whether a tap is installed is the install's answer. Declaring
# the range again installs over it and carries the old counts.
_REMOVAL_WHY = {
    "refused": ("the console evaluated the removal and it RAISED, so the removal was not "
                "carried out and this server no longer holds the tally's record; whether a "
                "tap is installed is what the install's own answer said. Declaring the range "
                "again (`watch_add(mode=\"count\")`, `space=\"io\"` for a port's) installs over "
                "it and CARRIES ITS "
                "COUNTS: read the first total as this tally's, not as a fresh one"),
    "lost": ("the console took the removal line and never evaluated it (its echo is in "
             "`log`, channel `process`, with a reader death, the console's error or the next "
             "reader's prompt after it and no sentinel), so the removal was not "
             "carried out and this server no longer holds the tally's record; whether a tap "
             "is installed is what the install's own answer said. Declaring the range again "
             "(`watch_add(mode=\"count\")`, `space=\"io\"` for a port's) installs over it "
             "and CARRIES ITS COUNTS: read "
             "the first total as this tally's, not as a fresh one"),
}


def tallies_not_removed() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rem in STATE.tally_removals:
        if rem["state"] and rem["state"] != "removed":
            why = _REMOVAL_WHY[rem["state"]]
            out.append({"tally_id": rem["tally_id"], "state": rem["state"],
                        "why": f"{why}. The console said: {rem['error']}" if rem["error"] else why})
    return out
