"""What the server HOLDS between calls.

One live machine: the MAME process, the gdbstub session on it, the symbols the caller's
file gave `start`, the breakpoints this server armed, the scratch directory the
session writes into, and the LAST STOP as its survey saw it, which is what the server
can still say about the machine while it runs. Every module of this package reads and
writes it through the one `STATE` instance below, so a test that installs a fake session
does it in ONE place and every tool sees it. The reply built from it is `mame_envelope`'s.
"""

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

from scry_core import cancel, picture, screen_map
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core.reply_contract import or_unavailable, unavailable

import gdb_session as gs
import mame_declarations as dec
import mame_guardian as guardian
import mame_idle as idle
import mame_inputs as inputs

if TYPE_CHECKING:
    import mame_cycles
    import mame_manifest
    import mame_scan

# ROWS OF ONE TABLE A REPLY SHOWS: one number for every view that cuts a table, so two views
# of one table cut it at the same row.
ROWS_SHOWN = 24
# THE SIZE A REPLY IS BUILT TO STAY UNDER, in characters of its JSON. Past a limit counted in
# tokens (`MAX_MCP_OUTPUT_TOKENS`) the client saves a tool result to a file and hands the
# conversation a path instead, which is the failure this bounds; its earlier warning is noise, not
# a loss. The limit is in tokens and this budget in characters, and no tokenizer here converts
# one to the other: the budget ASSUMES a reply of decimal lists and hex spends no less than a
# couple of characters a token, and is an estimate on that assumption. Nothing checks it at run
# time: the tests that build the longest reply a list can make assert against it.
REPLY_BUDGET_CHARS = 40000


def utc_now() -> datetime:
    """The one clock a declaration is stamped and aged by."""
    return datetime.now(UTC)


def now() -> str:
    return utc_now().isoformat(timespec="seconds")


def age_s(stamp: str | None) -> int | None:
    """Whole seconds since `stamp` (a `now()` stamp, or any date with an offset), read at the
    moment of asking; None when the row carries no date, or one that names no instant. A zero
    would read as "declared just now", which is the one thing an undated row cannot claim."""
    try:
        then = datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None
    if then is None or then.utcoffset() is None:
        return None
    return int((utc_now() - then).total_seconds() // 1)


# How long `close` gives MAME to exit on its own after the console's `quit`, before SIGKILL.
# A clean exit is what writes `cfg/` and `nvram/`; see `State.kill`. And how long a SIGKILLed
# process is given to be reaped before `close` reports its `exit_code` unavailable: a different
# question, so a different name, whatever the numbers happen to be today.
QUIT_GRACE_S = 5.0
REAP_GRACE_S = 5.0
# How often `wait_exit` asks whether the process is gone.
EXIT_POLL_S = 0.1
# The table of a cpu `start` was given no symbol file for: no names, and nothing to resolve.
NO_TABLE = gs.SymbolTable({}, {}, "none")


def wait_exit(proc: subprocess.Popen[bytes], seconds: float, progress: mprogress.Progress,
              what: str) -> int | None:
    """The process's exit code within `seconds`, or None: a `proc.wait(timeout)` that reports
    its progress, because `close` is a wait the owner watches (MAME writes its state files on
    the way out, and a quit that takes seconds looks exactly like a hung server without the
    line). The poll is the reap's, not a busy loop."""
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
    """The one sentence for "there is no machine", raised by two different conditions: no session
    at all, and a session with no declaration store."""
    why = idle.IDLE.note()
    raise Invalid("no_session", f"no machine running{'; ' + why if why else ''}; call `start` "
                  "first")


class State:
    """The one live machine. One at a time on purpose: there is no second use yet."""

    def __init__(self) -> None:
        # THE ONE COUNTER THAT OUTLIVES THE SESSIONS IT NUMBERS, and the whole of the
        # difference between a fresh State and a killed one. `origin` stamps every declaration
        # with it, so two sessions of one process inside the same second must not be able to
        # mint the same stamp -- which they could if a `close` sent it back to zero. It is set
        # HERE and deliberately not in `_reset`.
        self.start_seq = 0
        # A CALL THE CLIENT CANCELLED has no reply of its own, so what it left rides on the next
        # reply that closes, whatever tool that is, and is then forgotten (`take_cancelled`).
        # Not in `_reset` either: the next call may be the `close` or `start` that kills.
        self.cancelled: cancel.Cancelled | None = None
        # THE SCREEN MAPS outlive a session too: the file layer a `map_load` read stays, and a
        # `start` empties the session layer and forgets the last identification.
        self.maps = screen_map.Maps()
        self._reset()

    def _reset(self) -> None:
        """Every field of ONE session, at the value it has before a session exists.

        `__init__` and `kill` both come here, because this list was written out twice and a
        field added to one copy was a field the other left standing: an `armed_watches` entry
        surviving a close attributes the next session's watch stop to the last session's ref,
        and `symbols` and `system` were simply never cleared at all. A case comparing the two
        lists is what caught that, and it stays -- as a net under this, not as the support.
        """
        self.proc: subprocess.Popen[bytes] | None = None
        # THE GUARDIAN BESIDE `proc` (`mame_guardian`), stopped with the session it watches.
        self.guard: subprocess.Popen[bytes] | None = None
        self.ses: gs.Session | None = None
        # THE SYMBOL TABLES, ONE PER CPU, by the cpu's tag (`mame_symbols`): each cpu runs its
        # own program, so a name is an address in one cpu's table. What each table carries
        # (the names, their types and classes, each class's span and bases) is
        # `gdb_session.SymbolTable`'s. `table` is the one way to read them.
        self.tables: dict[str | None, gs.SymbolTable] = {}
        # The cpu a table given as ONE path belongs to: the stub's first cpu, read at `start`.
        self.first_cpu: str | None = None
        self.system: str = ""
        self.boot_pc: int | None = None          # where `start` parked: `reset` reads back to it
        # THE BREAKPOINTS THIS SERVER ARMED, by the row's INDEX, each held by ONE declaration's
        # `owner` (its ref and cpu, `Declaration.owner`) with the row's `addr` and `cpu`. MAME
        # numbers breakpoints with one counter across every cpu, so the index is the row and the
        # address is only where it sits: a row typed through `debug` at an address held here, or one
        # under another cpu, is somebody else's (`run_to`'s own two rows never enter here).
        self.breakpoints: dict[int, dict[str, Any]] = {}
        # THE REGISTERPOINTS THIS SERVER ARMED OR ADOPTED, by the declaration's owner, each
        # written only after the debugger's list was read back (`index`, `cpu`, and the
        # `condition` as the console read it).
        self.regpoints: dict[dec.Owner, dict[str, Any]] = {}
        # WHAT THE LAST FEED OF MAME'S PANE SAID OF EACH COMMENT, by owner: `armed`, or
        # `unarmable` with `why` (`mame_comments`). `comment_list` reports it without asking the
        # machine, which is what lets it answer while the machine runs.
        self.comment_feed: dict[dec.Owner, dict[str, Any]] = {}
        # THE DECLARATIONS WHOSE CONDITION THIS START'S CONSOLE ANSWERED `unknown symbol` FOR,
        # as `(kind, owner)`, breakpoints and registerpoints in one set: each family's list
        # reports its members `unresolved`, its clear drains its own, and arming one drops it.
        self.conditions_unresolved: set[tuple[str, dec.Owner]] = set()
        self.console_writes: int = 0
        self.scratch: Path | None = None
        self.state_dir: str = ""
        # The repo's cfg this session installed for MAME (`source`, `installed`), or None.
        self.cfg: dict[str, Any] | None = None
        self.port: int = 0
        self.stdout_log: IO[bytes] | None = None
        self.snapshots: int = 0    # numbers the files `snapshot` writes into the scratch
        self.debug_dumps: int = 0  # numbers the files a clipped `debug` or `lua` answer goes to
        self.batches: int = 0      # numbers the files a `perform` or `drive` with summaries writes
        self.recordings: int = 0   # numbers the files `record`, `audio_record` and `trace` write
        # WHAT `record`, `audio_record`, `trace`, `snapshot` AND THE GRAPHICS TOOLS CHECKED AND
        # HANDED BACK THIS SESSION, in order, as (kind, path): the list `captures` reads back,
        # because each tool handed back a path and nothing remembered it.
        self.captures: list[tuple[str, str]] = []
        # THE OPEN VALUE SCAN: one at a time, and it outlives whatever the machine does, because
        # the next filter compares whatever memory holds then.
        self.scan: mame_scan.Scan | None = None
        # THE CONSOLE CHANNEL: where its stdout was last read up to (`mame_transport`, the byte
        # after the last prompt consumed), and how many raw `lua` calls were made (`mame_lua`),
        # each of which counts as a write because nothing in a Lua string says whether it
        # wrote.
        self.console_mark: int = 0
        self.lua_calls: int = 0
        # RAW `lua` CALLS THE CALLER DECLARED READ-ONLY. They are NOT counted as writes, which
        # is the whole point of the flag, and they are counted HERE so the session can say so:
        # the server cannot verify the claim and never could, so the one thing it must not do
        # is let it pass in silence. A reader of any reply sees how many were made and whose
        # word they are.
        self.lua_read_only_claims: int = 0
        self.lua_seq: int = 0        # numbers every chunk sent, for its echo and sentinel
        self.lua_answered: int = 0   # the highest call whose answer was consumed
        self.lua_lost: int = 0       # the highest call the console's reader died holding
        # EVERY CALL SENT AND NOT YET SETTLED against the log (`mame_transport._settle_pending`):
        # its number to its line and the stdout offset before it was sent.
        self.lua_pending: dict[int, tuple[str, int]] = {}
        # THE PENDING CALLS WHOSE CHUNK THIS SERVER COMPOSED (a tap's install), which print no
        # prompt of their own and so may be settled by the next reader's
        # (`mame_transport.passed_over`).
        self.lua_ours: set[int] = set()
        # WHAT THE CONSOLE CHANNEL DID TO THIS SESSION, cumulative, reported in every reply.
        # Why there are three of them and not one is the contract's, and it is written once,
        # in `REFERENCE.md`.
        self.console_thread_errors: int = 0   # reader deaths the console has printed
        # HOW FAR THE DEATH COUNT HAS READ. The count is by POSITION and not by whichever
        # path noticed, because the paths overlap: a refusal reads bytes it does not
        # consume and a later answer consumes them again. A byte offset can only be passed
        # once, so the count is exactly-once whoever asks and in whatever order.
        self.console_counted: int = 0
        self.console_reruns_seen: int = 0     # chunks the console ran AGAIN
        self.console_lines_lost: int = 0      # lines taken and never evaluated
        # A RUN THE CONSOLE STARTED (`g` through `debug`): the stub sends no stop packet for
        # it, so its stop is proved on the frame counter by the first contact after it.
        self.console_run: bool = False
        # ...and one the counter CANNOT prove: a run bailed out because the counter did not
        # move (`no_progress`), so two agreeing readings are exactly what it already showed.
        # Only `stop`'s interrupt ends it.
        self.console_run_unprovable: bool = False
        # THE STATES THIS SESSION SAVED, by name: the frame, the pc and the register blocks at
        # the save, which a load is judged against, and the signature MAME wrote into their
        # headers.
        self.states: dict[str, dict[str, Any]] = {}
        self.state_signature: int | None = None
        # WHAT `totalcycles` READ RIGHT AFTER A COMMAND THAT LEFT IT STALE, until the next run's
        # baseline consumes it (`mame_cycles`). None: nothing waiting.
        self.stale_counter: mame_cycles.StaleCounter | None = None
        # THE REFERENCE `start` was checked against (image, address, base), kept so a
        # `state_load` can run the same check on the machine the state replaced.
        self.reference: tuple[Path, int, int] | None = None
        # THE LAST STOP, as its one survey saw it: the program counter, the registers, the
        # frame, how it came to stop and when. Filled by every stop reply and by the first
        # contact that finds a stop the machine reached on its own; it is what a refusal on
        # a running machine names, and what `registers(from_last_stop=True)` answers from.
        # Empty means no stop yet in this session. Cleared by `kill`.
        self.last_stop: dict[str, Any] = {}
        # Where `error.log` ended at the last stop, so a stop reply can show only what the
        # driver logged since. Bytes, because the log is read by seeking, never re-parsed.
        self.errorlog_mark: int = 0
        # A stop the machine reached ON ITS OWN, found by the first contact after it: the
        # account rides on that contact's reply (`stopped_on_its_own`) and is then forgotten,
        # whatever tool that contact was.
        self.found_stop_last: dict[str, Any] = {}
        # Set once the throttle harness's lift mark has been seen in error.log this session,
        # so the speed window is reset to the real-speed start only once, not on every read.
        self.throttle_seen = False
        # When the machine was last RELEASED to run and left running: its emulated time
        # (the console's `time`) and the wall clock then, so the stop that ends the run --
        # or `close` on a watched run -- can report the speed the host held over it
        # (emulated seconds / wall seconds). None when the machine is stopped.
        self.run_release: dict[str, float] | None = None
        # THE DECLARATIONS of this session's guest (`mame_declarations`), created by `start`
        # with the session, and the stamp every declaration this session makes carries as
        # its `origin`, which is what tells a declaration made here from one the store
        # brought back at `start` (a list row's `inherited`). Whether a raw address re-arms
        # is the build's question, not the session's: `dec.is_stale`.
        self.store: dec.DeclarationStore | None = None
        self.session_origin: str | None = None
        # THE BUILD THIS SESSION RUNS, per cpu: the fingerprint of the system, the ROM image and
        # that cpu's symbol file (`mame_symbols.fingerprint`). What a raw-address declaration
        # is judged stale against, on its own cpu. `fingerprint` reads it.
        self.fingerprints: dict[str | None, str] = {}
        # WHAT THIS SESSION ARMED IN THE DEBUGGER for each change watch, by owner: the address,
        # length and cpu of the `wp`, the row `wplist` listed for it (its index is what the
        # console's stop line names), and the bytes last seen there at a stop, which is what
        # `before` means when the watch fires. A clear removes THAT row whatever the name
        # resolves to by then.
        self.armed_watches: dict[dec.Owner, dict[str, Any]] = {}
        # THE TALLIES THIS SESSION SENT (`mame_tally`), by owner: the id the Lua registry
        # holds the tap under, the range, the dump file, the install's line and call number
        # (its answer is read at the first survey after it) and what the last survey read.
        self.tallies: dict[dec.Owner, dict[str, Any]] = {}
        # THE REMOVALS THIS SESSION SENT, until the console says what became of each. The
        # record above is dropped the moment a removal is SENT, because keeping it would
        # let a later tally on the same range read this one's numbers; this holds what is
        # left to ask ABOUT, which is only the tap's id and the line's own accounting.
        # `mame_tap.read_removal_answers` owns what the two bad ends mean.
        self.tally_removals: list[dict[str, Any]] = []
        # THE THROTTLE SWITCHES THIS SESSION ASKED FOR AND NOBODY HAS CONFIRMED, and the
        # ones a survey found had demonstrably not landed. The second list LATCHES: nothing
        # clears a row but the end of the session. What either means to a caller is the
        # contract's, and it is written once, in `REFERENCE.md`.
        self.throttles_pending: list[dict[str, Any]] = []
        self.throttles_not_applied: list[dict[str, Any]] = []
        # THE CONTROLS THIS SESSION ARMED, by owner: the address, which of the debugger's ten
        # `temp` variables counts its hits, the row `bplist` listed (this is what says which
        # console row is whose), and `missed`, the hits MAME skipped on a frame stop's landing
        # (`mame_breakpoints.count_landing`), added to the temp wherever a count is read.
        self.controls: dict[dec.Owner, dict[str, Any]] = {}
        # Where `debug.log` (the console's own output, `-debuglog`) ended at the last stop,
        # read like `errorlog_mark`: a watchpoint stop's writer is named there.
        self.debuglog_mark: int = 0
        # THE MACHINE'S INVENTORY, gathered ONCE by `start` (`mame_machine`) and served from
        # here: what the board is made of, each section with the source that backs it, and the
        # note that says what could not be gathered. ONE dict, because the note is part of the
        # answer and not a second fact to keep beside it. Empty until a machine has started.
        self.machine_map: dict[str, Any] = {}
        # THE CONSOLE'S NAME FOR THE FRAME COUNTER, asked at `start`
        # (`mame_read.probe_frame_symbol`): `frame` on one screen, `frame0` on several, None on a
        # board with no screen device, where MAME defines no counter and no vblank stop.
        # `frame` until a start asks, the name an unasked board is read by.
        self.frame_symbol: str | None = "frame"
        # EVERY CPU IN THE DEBUGGER'S ORDER, as the console's `cpulist` lists them: read once a
        # session, the first time a reply names a cpu (`mame_cpus.cpu_list`), since a board's
        # cpus do not change under it. Which one is VISIBLE changes, and is read every time.
        self.cpus: list[str] = []
        # THE PROJECT'S GRAPHICS MANIFEST (`gfx_load`), held for the session like the symbol
        # tables: it describes this board, so it goes when the board does.
        self.manifest: mame_manifest.Manifest | None = None
        # WHAT THIS SESSION ESTABLISHED ABOUT ITS BOARD'S GRAPHICS (`mame_evidence`): every
        # `gfx_locate` answer, sweep and choice, in order. A draft states this machine, so the
        # evidence goes when the machine does.
        self.evidence: dict[str, list[dict[str, Any]]] = {"locates": [], "sweeps": [],
                                                          "choices": []}

    def origin(self) -> str:
        """One stamp per `start`: the clock, this process and a counter, so two sessions of
        one process inside a second, and two processes over one guest, never share one."""
        self.start_seq += 1
        return f"{now()}#{os.getpid()}.{self.start_seq}"

    def remember_stop(self, ses: gs.Session, pc: int, regs: dict[str, Any], frame: int | None,
                      how: str, watch_hit: dict[str, Any] | None = None,
                      cpu: str | None = None) -> dict[str, Any]:
        """Record a stop as the last one and hand the record back: `cpu` is the one it
        happened on, whose `pc` and `regs` these are."""
        self.last_stop = {
            "seq": int(self.last_stop.get("seq", 0)) + 1,
            "pc": hex_addr(pc),
            "cpu": cpu,
            "regs": dict(regs),
            "frame": frame,
            "how": how,
            "packet": ses.last_stop_packet,
            "stop_count": ses.stop_count,
            "when": time.monotonic(),
            "wall_at": now(),
        }
        if watch_hit is not None:
            self.last_stop["watch_hit"] = dict(watch_hit)
        return self.last_stop

    def record_image(self, path: Path) -> None:
        """A picture a graphics tool wrote, listed among the session's captures once: a film's
        sheet drawn again on a later read is the same file."""
        entry = ("image", str(path))
        if entry not in self.captures:
            self.captures.append(entry)

    def take_cancelled(self) -> cancel.Cancelled | None:
        """The record a cancelled call left, handed once to the next reply that closes."""
        record, self.cancelled = self.cancelled, None
        return record

    def end_call(self) -> None:
        """The OUTER call is over, and with it the one-time account of a stop the machine
        reached on its own: it rode on this call's reply, and kept it would ride on the next,
        unrelated one. The record itself stays (`status` shows it)."""
        self.found_stop_last = {}

    def as_of(self) -> dict[str, Any]:
        """The last stop as a dated reference for an answer given while the machine runs,
        unavailable when this session has not stopped yet."""
        if not self.last_stop:
            return unavailable(NO_STOP_YET_WHY)
        return {"stop_seq": self.last_stop["seq"], "pc": self.last_stop["pc"],
                "cpu": or_unavailable(self.last_stop.get("cpu"), NO_CPU_READ_WHY),
                "frame": frame_shown(self.last_stop["frame"]),
                "how": self.last_stop["how"],
                "since_s": spent_s(time.monotonic() - float(self.last_stop["when"])),
                "wall_at": self.last_stop["wall_at"]}

    def alive(self) -> gs.Session:
        if self.ses is None or self.proc is None:
            no_machine()
        code = self.proc.poll()
        if code is not None:
            # A MACHINE THAT DIED UNDER A SESSION is not "no machine": its scratch still holds
            # what it printed on the way out, and `start` would delete it. `close` reads those
            # last words and the exit code first, so it is the one step named.
            raise Invalid("session_broken",
                          f"MAME exited with code {code} under this session: `close` collects "
                          "its exit code and the last lines of each channel before the scratch "
                          "is deleted, then `start` a new one", exit_code=code)
        return self.ses

    def live(self) -> tuple[gs.Session, Path]:
        """The live session and its scratch, or the refusal `alive` gives when there is none."""
        ses = self.alive()
        assert self.scratch is not None
        return ses, self.scratch

    @property
    def broken(self) -> str | None:
        """Why the session can no longer be trusted (`Session.broken`), or None, with no session
        too: the one reading of the latch for code that may run before `start` or after `close`."""
        return self.ses.broken if self.ses is not None else None

    def next_number(self, kind: Literal["snapshots", "debug_dumps", "batches",
                                        "recordings"]) -> int:
        """The next number of a kind of scratch file, counted from 1 for the session: the one
        place its counter moves, before the file is named."""
        number = int(getattr(self, kind)) + 1
        setattr(self, kind, number)
        return number

    def altered(self) -> int:
        """Protocol writes PLUS the ones made through the debugger console PLUS every raw
        `lua` call, which is a write until proven otherwise."""
        return (self.ses.writes if self.ses else 0) + self.console_writes + self.lua_calls

    def table(self, cpu: str | None = None) -> gs.SymbolTable:
        """`cpu`'s symbol table, the first cpu's when none is named, and an empty one for a cpu
        `start` was given none for. A table whose cpu the start could not name (a console that
        listed no cpu) serves every cpu, since nothing says which one it belongs to."""
        if None in self.tables:
            return self.tables[None]
        return self.tables.get(self.first_cpu if cpu is None else cpu, NO_TABLE)

    def table_owner(self, cpu: str | None = None) -> str | None:
        """The cpu whose table `table(cpu)` answers from, None when one table serves every cpu:
        what a refusal names as the table it looked in."""
        return None if None in self.tables else (self.first_cpu if cpu is None else cpu)

    def fingerprint(self, cpu: str | None = None) -> str | None:
        """The build `cpu`'s declarations are judged against, the first cpu's when none is
        named or the start computed none for it (a cpu the console did not list)."""
        first = self.fingerprints.get(self.first_cpu)
        return first if cpu is None else self.fingerprints.get(cpu, first)

    def resolve(self, ref: str, cpu: str | None = None) -> int:
        """Where a ref of a CALL points on `cpu` (the first cpu's table when none is named): a
        `0x` address, or a symbol of that table (`inputs.classify`). A name the table lacks
        fails instead of reading rubbish."""
        symbols = self.table(cpu).table
        text = ref.strip()
        if inputs.classify(text, symbols, cpu or self.first_cpu) == "address":
            return int(text, 16)
        if text.upper() in symbols:
            return symbols[text.upper()]
        raise Invalid("unknown_ref", inputs.not_a_ref("the ref", text, self.table_owner(cpu),
                                                      loaded=len(symbols)))

    def resolve_named(self, what: str, text: str, cpu: str | None = None) -> int:
        """`resolve` for a ref a call names under `what` (`trigger`, `pc`): bare hex naming no
        symbol keeps its own refusal, and a name the build lacks is named as `what`, with where
        to look it up."""
        try:
            return self.resolve(text, cpu)
        except inputs.BareHex:
            raise
        except Invalid:
            raise Invalid("unknown_ref", inputs.not_a_ref(f"the {what}", text,
                                                          self.table_owner(cpu))) from None

    def _cfg_file(self) -> Path | None:
        """The cfg MAME writes as it exits cleanly, `<state>/cfg/<system>.cfg`, which is the
        proof `close` reads that the exit was clean; None when this State holds no directory
        or no system to name it (a session that never booted, a double)."""
        root = self.state_dir or self.scratch
        if not root or not self.system:
            return None
        return Path(root) / "cfg" / f"{self.system}.cfg"

    def _cfg_marker(self) -> int | None:
        """Where the cfg stood BEFORE the exit was asked for: its mtime, -1 for a file not
        there yet, None when there is nothing to read."""
        path = self._cfg_file()
        if path is None:
            return None
        return path.stat().st_mtime_ns if path.exists() else -1

    def _cfg_written(self, marker: int | None) -> bool | None:
        """Whether MAME wrote its cfg since the marker was taken: the file is there and newer,
        or there where it was not. None when there was nothing to read."""
        path = self._cfg_file()
        if path is None or marker is None:
            return None
        return path.exists() and path.stat().st_mtime_ns > marker

    def machine_alive(self) -> bool:
        """Whether this session's MAME is running: spawned, and not exited."""
        return self.proc is not None and self.proc.poll() is None

    def kill(self, progress: mprogress.Progress = mprogress.no_progress,
             grace: bool = True) -> dict[str, Any]:
        """End the session: ask MAME to QUIT through its own console, and only then kill.
        `grace=False` asks nothing and kills at once (`killed`), for a start that failed.

        MAME writes `cfg/` and `nvram/` when it EXITS, and it ignores SIGTERM (measured, and
        written in the MAME reference), so a session ended with SIGKILL left a `state_dir`
        empty forever: the persistent shape kept nothing. `Session.quit` is the clean exit,
        through the connection this server already holds, and its docstring carries the
        measured detail of why it is two steps. A machine that does not exit within the grace
        period is killed as before: a stuck emulator is not allowed to hold `close` hostage.

        THE ENDING IS THE ANSWER, because the endings are not the same ending: `ended_by` is
        `quit` (the process exited within the grace period after `quit` was asked for AND
        wrote its cfg on the way out, which is the proof of a clean exit: MAME rewrites
        `<state>/cfg/<system>.cfg` as it exits), `exited` (it exited within the grace period
        and wrote no cfg: a crash on the way out, or an exit `quit` did not cause), `killed`
        (the grace period ran out, or none was given), `died` (the process had already exited
        on its own, and `poll` held its code, which is not "no session") or `none` (nothing
        was running);
        `state_written` is that proof as read (true, false, or unavailable when there was no
        directory to read it in), `exit_code` is what the process returned, and
        a SIGKILLed process still not reaped has `exit_code` unavailable, its `why` saying so,
        because there was nothing to read, and `close` answers rather than raising.
        """
        ended: dict[str, Any] = {"ended_by": "none", "exit_code": None,
                                 "state_written": None}
        if self.proc is not None and self.proc.poll() is not None:
            ended = {"ended_by": "died", "exit_code": self.proc.poll(),
                     "state_written": None}
        elif self.proc is not None:
            marker = self._cfg_marker()
            # A BROKEN CHANNEL IS NOT ASKED TO QUIT: the request would wait out its own
            # timeout on a conversation that lost its place, and then the grace period on top.
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
        # THE INSTALLED CFG, READ BEFORE THE SCRATCH GOES: MAME rewrites it in its canonical
        # form on a clean exit, and whether the copy still equals the repo's file is what a
        # caller deciding to commit a cfg wants to know; the source is never touched here.
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
        # NEVER A NULL: what this ending could not read says why, by how it ended.
        if ended["exit_code"] is None:
            ended["exit_code"] = unavailable("no session was running")
        if ended["state_written"] is None:
            ended["state_written"] = unavailable(
                "no session was running" if ended["ended_by"] == "none" else
                "MAME had already exited, so this close saw no write" if ended["ended_by"] == "died"
                else "there was no cfg file to read MAME's write from")
        # THE TEARDOWN COMES FIRST, because these three fields hold something to CLOSE or to
        # DELETE and not merely a value to drop: the connection, the captured stdout, and the
        # directory this session owns. `_reset` below only sets values.
        # GUARDED LIKE THE QUIT ABOVE AND THE RMTREE BELOW: a close that raised here skipped
        # `_reset`, so the dead session's fields stood under an error about something else.
        if self.ses:
            with contextlib.suppress(OSError):
                self.ses.close()
        if self.stdout_log:
            with contextlib.suppress(OSError):
                self.stdout_log.close()
        # The scratch is this session's and dies with it. A `state_dir` is the CALLER's: it was
        # named so that `cfg/` and `nvram/` outlive one boot, and nothing here deletes it.
        if self.scratch and self.scratch.exists():
            shutil.rmtree(self.scratch, ignore_errors=True)
        guardian.stop(self.guard)
        # AND EVERY FIELD GOES BACK THROUGH THE ONE LIST THAT BUILDS A FRESH STATE. Written out
        # a second time here, this is where a field added to `__init__` was left standing.
        self._reset()
        return ended


STATE = State()
#: scry-core's picture writers with this server's recorder bound once: every picture a tool
#: writes is listed among the session's captures, so none can forget to say so.
publish = functools.partial(picture.publish, record=STATE.record_image)
data_file = functools.partial(picture.data_file, record=STATE.record_image)


# THE REFUSAL is `scry_core.reply_contract`'s class, re-exported so every module raises one
# name; the input judges, which this module imports, take the same class from the contract itself.
Invalid = contract.Invalid


def last_stop_frame() -> int | None:
    """The frame the last recorded stop read, or None before any stop or on a stop that read
    none. The one reader of that fact: `stopped_frame` and a recording's frames both ask it."""
    frame = (STATE.last_stop or {}).get("frame")
    return frame if isinstance(frame, int) else None


def stopped_frame() -> int | None:
    """The frame the machine stands at when it is stopped at a recorded stop, else None: a
    machine that runs has no frame a dump can honestly be judged against."""
    ses = STATE.ses
    return None if ses is None or ses.running else last_stop_frame()

def refuse_broken(ses: Any) -> None:
    """Refuse on a session that BROKE (`Session.broken`), quoting what broke it and naming
    the way out, and never saying the machine is running."""
    reason = ses.broken
    if reason:
        raise Invalid("session_broken",
                      f"this session broke and nothing it answers can be trusted any more: "
                      f"{reason}. `close` it, then `start` a new one", broken=reason)


def mark_fields(line: str) -> dict[str, str]:
    """`key=value` pairs off a mark line; a `%q`-quoted value keeps its text.

    IT LIVES HERE rather than beside its first caller because two modules now read a mark
    and neither may import the other: the Lua wrappers read their own marks, and the stop
    survey reads a throttle's. Written twice, one copy would learn about a quoting the other
    did not.
    """
    return {k: v.strip('"') for k, v in re.findall(r'(\w+)=("[^"]*"|\S+)', line)}


def mark_lines(lines: list[str], tag: str) -> list[str]:
    """Every line carrying `tag`, with the digits of its number CLOSED. `mark_line` below
    says why a bare substring test is wrong; the Lua wrappers read their own marks through
    this, so the closing is a property of the one construction and not of each caller."""
    closed = re.compile(re.escape(tag) + r"(?!\d)")
    return [ln for ln in lines if closed.search(ln)]


def mark_line(lines: list[str], tag: str) -> str | None:
    """The first line carrying `tag`, with the digits of its number CLOSED.

    A BARE SUBSTRING TEST IS WRONG HERE AND SILENTLY SO: `MAME_MCP_THROTTLE#1` is a substring
    of `MAME_MCP_THROTTLE#10`, so an older record could be answered off a later line's data.
    The direction it fails in is the worst one available: the older switch is the one whose
    own line is missing BECAUSE it never ran, and matching it against a younger line that
    agrees drops it with no row at all, which is the defect this whole mechanism exists to
    report. A caller who asks for several switches while stopped reaches two-digit numbers
    without doing anything unusual.
    """
    return next(iter(mark_lines(lines, tag)), None)


def settle_throttles(lines: list[str]) -> None:
    """What became of every throttle this session left pending, judged against `lines`: the
    error log since the last stop, which the survey has already read.

    IT READS AND NEVER RESENDS, for the reason `mame_tap.read_removal_answers` gives: a
    look can be wrong about nothing. A switch whose mark arrived is dropped and earns no row,
    because a throttle that worked is not news (it leaves `status`'s `throttles_pending`,
    which is how a caller sees it land); one that never arrives is a ROW, and the row
    latches, so the caller is told again on every reply until they act on it.

    WHAT SAYS THE MARK IS OVERDUE, rather than merely late: the console has ANSWERED a call
    at or past this line's own number. The mark is written by the line itself, so a console
    that has worked its way past it and left no mark did not apply the switch. Until then the
    console may simply not have read the line, and the `pending` the caller was given is true.
    """
    for rec in list(STATE.throttles_pending):
        seen = mark_line(lines, rec["mark"])
        if seen is not None:
            said = mark_fields(seen).get("throttled")
            # THE MACHINE'S ANSWER IN THE TOOL'S OWN VOCABULARY. `on` is a bool everywhere
            # `throttle` speaks, so the row spells it the same way rather than inventing a
            # second spelling of one concept; anything that is neither word is kept VERBATIM,
            # because a value nobody anticipated is exactly the one worth reading.
            reports: Any = {"true": True, "false": False}.get(said or "", said)
            STATE.throttles_pending.remove(rec)
            if reports is not rec["on"]:
                # THE SAME DISAGREEMENT THE RUNNING PATH REFUSES ON, reached by a caller who
                # could not wait for it. It cannot be a refusal here, because the call that
                # finds it asked about something else entirely.
                STATE.throttles_not_applied.append(
                    {"mark": rec["mark"], "asked": rec["on"], "machine_reports": reports,
                     "why": "the machine reports a throttle setting that is not the one this "
                            "session asked for. Ask again and read the answer; this row "
                            "records what happened and stands for the rest of the session"})
        elif STATE.lua_answered >= rec["seq"]:
            STATE.throttles_pending.remove(rec)
            STATE.throttles_not_applied.append(
                {"mark": rec["mark"], "asked": rec["on"],
                 "machine_reports": unavailable("the mark was never logged, so the machine "
                                                "reported nothing"),
                 "why": "the console worked past this line and never logged its mark, so the "
                        "switch was NEVER applied: the speed of everything measured since is "
                        "not the one that was asked for. Ask for it again; this row records "
                        "what happened and stands for the rest of the session"})


def bare_tag(tag: str | None) -> str:
    """A device tag without its leading colon: a manifest writes `palette`, MAME answers
    `:palette`, and both name one device."""
    return (tag or "").lstrip(":")


# THE LINE A LUA CHUNK OF THIS SERVER ENDS ON, `<LUA_SENTINEL>#<seq>`: the one spelling the
# chunk writes, the reader looks for and every reply names as `call`. Here, where every module
# that names a call (the transport, `mame_running`, the wrappers) can import it.
LUA_SENTINEL = "MAME_MCP_LUA_END"


def sentinel_line(seq: int) -> str:
    """The sentinel line chunk `seq` ends on, as a reply names it."""
    return f"{LUA_SENTINEL}#{seq}"


def hex_addr(addr: int) -> str:
    """ONE SPELLING FOR AN ADDRESS in every reply: eight digits, the widest space this server
    drives, so a breakpoint's `addr`, a stop's `pc` and a writer's pc naming one place are one
    string and compare as one."""
    return f"{addr:#010x}"


# THE REPLY VOCABULARY OF A REASON: `note` is a reply's note, or a sub-object's, one string;
# `why` is a row's or a field's reason; a datum that could not be read is `unavailable(why)`
# in place of its value, spelled by the contract's builder (`unavailable` below). One builder for
# each, so a note is joined one way everywhere.
NOTE_SEPARATOR = "; "


def join_notes(*parts: str | None) -> str | None:
    """The parts said, in order, each once, as one note; None when nothing was said."""
    said = list(dict.fromkeys(p for p in parts if p))
    return NOTE_SEPARATOR.join(said) if said else None


def add_note(reply: dict[str, Any], *parts: str | None) -> dict[str, Any]:
    """`parts` added to `reply["note"]` after what it already says; the key appears only when
    something is said. Returns the reply, for a caller that builds it in place."""
    note = join_notes(reply.get("note"), *parts)
    if note is not None:
        reply["note"] = note
    return reply




#: `last_stop` before the session's first stop.
NO_STOP_YET_WHY = "this session has not stopped yet"

#: `cfg` when none was given to `start`.
NO_CFG_WHY = "no cfg was given, so MAME runs on its defaults"

#: A reply's `cpu` when none could be named: no thread per cpu and `cpulist` marking none.
NO_CPU_READ_WHY = "no cpu could be named: `cpulist` marked none visible"

#: A list tool's `cpu` when the call named none: the filter that was not applied.
NO_CPU_NAMED_WHY = "no cpu was named, so the rows are every cpu's"


#: Why a recorded frame is not a number, by cause: the record keeps None, a reply says which.
NO_COUNTER_WHY = "this machine has no frame counter, so no frame was read"
FRAME_UNREAD_WHY = "the console did not answer the frame counter when it was read"


def frame_shown(frame: int | None) -> int | dict[str, Any]:
    """A recorded frame as a reply carries it: the number, or `unavailable` saying why not (the
    board has no counter, which `start` read, or the read failed)."""
    if frame is not None:
        return frame
    return unavailable(NO_COUNTER_WHY if STATE.frame_symbol is None else FRAME_UNREAD_WHY)


def merged(*parts: dict[str, Any]) -> dict[str, Any]:
    """Reply fields from several sources, in order, as one reply: each source may carry a `note`,
    and the notes are joined so none is lost to another (`console_did`'s beside a tool's own);
    any other key said by two sources is two answers to one question, refused as a repeated
    keyword would be."""
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


# THE TWO ROUNDINGS OF A TIME IN SECONDS, by what the time is for: one a reader acts on (how long
# a wait or an attempt took, how long ago a stop was) is worth a tenth of a second; one that IS
# the reading (the machine's emulated time, a host span a speed or a cost is computed from, the
# cost of one query) is often smaller than a tenth, and is kept to the microsecond. A
# declaration's `age_s` is whole seconds: it counts days.
def spent_s(seconds: float) -> float:
    """A span a reader acts on, as every such `*_s` is spelled."""
    return round(seconds, 1)


@overload
def measured_s(seconds: float) -> float: ...
@overload
def measured_s(seconds: None) -> None: ...
def measured_s(seconds: float | None) -> float | None:
    """A time that is itself the measurement, as every such `*_s` is spelled."""
    return None if seconds is None else round(seconds, 6)
