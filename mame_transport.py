"""THE CONSOLE TRANSPORT: a Lua chunk sent down MAME's stdin and its answer read back off stdout.
Every Lua-family tool rides this; what the console's reader did on the way (a death, a rerun, a
line it took and never evaluated) is counted here, where the bytes are read. Why the channel
exists, and when the console evaluates a line, is `mame_lua`'s account.

Stdout is a file, so it is fully buffered, and everything a chunk printed is flushed by the
prompt linenoise prints right after it. An answer has come out DUPLICATED for a single echo,
and never reproduced, so the reader never counts lines.

HOW AN ANSWER IS FRAMED. Not by the prompt: a script is free to print the prompt's own
bytes, and a stale answer from an earlier call could hold the next call's text. Every call
carries a SEQUENCE NUMBER, in the chunk (so its echo is unique) and in a SENTINEL line the
chunk itself prints last, through `pcall`, with the outcome and the error beside it. The
answer is what sits between the echo and that sentinel, and the reader's mark moves past the
sentinel.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from scry_core import progress as mprogress
from scry_core import prose

import gdb_session as gs
import mame_files as files
import mame_state as st
from mame_state import STATE

# A script above this is a FILE, and `start` takes one as `boot_lua`: the console reads a
# line at a time, and a line this long is not a question.
SCRIPT_MAX = 16000


# How often the reader polls stdout for the sentinel.
POLL_S = 0.02


def lua_string(text: str) -> str:
    """`text` as a Lua double-quoted literal on ONE line."""
    escaped = (text.replace("\\", "\\\\").replace('"', '\\"')
               .replace("\r", "\\r").replace("\n", "\\n"))
    return f'"{escaped}"'


def chunk_line(script: str, seq: int) -> str:
    """A whole script as the ONE line the console reads: loaded as one chunk named `mcp`
    (so an error names `mcp:<line>`), run under `pcall`, and closed by the SENTINEL of call
    `seq` carrying the outcome, so a chunk that failed to compile or raised is read in its
    own words and never as a missing answer.
    """
    return (f'local f, e = load({lua_string(script)}, "=mcp") '
            f'if f == nil then print("{st.sentinel_line(seq)}", false, e) '
            f'else local ok, err = pcall(f) print("{st.sentinel_line(seq)}", ok, err) end')


def _stdin() -> Any:
    proc = STATE.proc
    if proc is None or proc.stdin is None:
        raise st.Invalid("no_channel",
            "this session holds no MAME process with a stdin pipe, so the Lua console cannot "
            "be reached: the channel exists only on a session this server started")
    return proc.stdin


def stdout_mark(scratch: Path) -> int:
    """The console's stdout mark (`files.log_mark` on its `process` channel), and a test seam:
    a test replaces it to place the mark inside a captured log. Taken before a caller writes,
    so what it reads back later is what arrived AFTER its own line and not the whole
    unconsumed tail. `find_answer`'s bytes start at the session's console mark, which
    only moves when an answer is CONSUMED, so a `[LUA ERROR] in thread` the session already
    survived sits in that tail for ever and would be read as this call's death."""
    return files.log_mark(scratch, "process")


def since(scratch: Path, mark: int) -> bytes:
    """The console's stdout from `mark` on."""
    log = files.log_path(scratch, "process")
    if not log.exists():
        return b""
    with open(log, "rb") as fh:
        fh.seek(mark)
        return fh.read()


def send(script: str, ours: bool = False) -> tuple[str, int]:
    """Put `script` in the pipe as one line and hand back that line and its sequence number.
    Refused above the ceiling and on an empty script BEFORE anything is written; a pipe
    the emulator has closed is the session broken, not a traceback. It returns only after
    the reader's settle (`READER_SETTLE_S`), so no caller can move the machine inside it.
    `ours`: this server composed the script, so it prints no prompt (`passed_over`)."""
    check_script(script)
    pipe = _stdin()
    seq = STATE.lua_seq + 1
    line = chunk_line(script, seq)
    size = stdout_mark(STATE.scratch) if STATE.scratch is not None else 0
    try:
        pipe.write(line.encode() + b"\n")
        pipe.flush()
    except OSError as e:
        # NOTHING WAS SENT, so nothing is counted as ahead in the pipe; and a console that
        # takes no line is a channel that died, which LATCHES like every other.
        if STATE.ses is not None:
            STATE.ses.latch(f"the console's pipe refused a line: {e}")
        raise st.Invalid("session_broken",
            f"the console's pipe refused the line: {e}; nothing sent through it reaches "
            "the console any more. `close` it, then `start` a new one") from None
    STATE.lua_seq = seq
    STATE.lua_pending[seq] = (line, size)
    if ours:
        STATE.lua_ours.add(seq)
    time.sleep(READER_SETTLE_S)
    return line, STATE.lua_seq


class Answer:
    """What the console printed for one call: the text before the sentinel, the outcome
    the sentinel carried (`ok`, and the error's words when it is not), and what the console
    did on the way: `thread_errors`, how many times its reader died starting up, and
    `reruns`, the sentinels of EARLIER calls printed again, each a chunk the console ran a
    second time (see `READER_SETTLE_S`)."""

    def __init__(self, text: str, ok: bool, error: str,
                 thread_errors: int = 0, reruns: list[str] | None = None) -> None:
        self.text, self.ok, self.error = text, ok, error
        self.thread_errors, self.reruns = thread_errors, reruns or []


def find_answer(scratch: Path, line: str, seq: int) -> tuple[Answer | None, bytes]:
    """ONE look at stdout for the answer to `line`: what sits between the echo of the line
    and the sentinel of call `seq`, searched from the session's console mark, which moves
    past the sentinel when the answer is there. With it, the bytes looked at."""
    log = files.log_path(scratch, "process")
    echo = (line + "\n").encode()
    sentinel = f"{st.sentinel_line(seq)}\t".encode()
    raw = b""
    if log.exists():
        with open(log, "rb") as fh:
            fh.seek(STATE.console_mark)
            raw = fh.read()
    count_deaths(scratch)
    i = raw.find(echo)
    j = raw.find(sentinel, i + len(echo)) if i >= 0 else -1
    end = raw.find(b"\n", j) if j >= 0 else -1
    if end < 0:
        return None, raw
    STATE.console_mark += end + 1
    outcome = raw[j + len(sentinel):end].decode("utf-8", errors="replace")
    ok, _, error = outcome.partition("\t")
    text = raw[i + len(echo):j].decode("utf-8", errors="replace")
    consumed = raw[:end]
    reruns = reruns_in(consumed, seq)
    STATE.lua_answered = max(STATE.lua_answered, seq)
    # THE RERUNS ARE HELD AGAINST THE SESSION HERE, where they are established: a rerun
    # is only knowable against the call being answered, so the answer is the one place
    # that can name one. The deaths are counted by POSITION instead (`count_deaths`),
    # because a death is a fact about the log and several paths can meet the same one.
    STATE.console_reruns_seen += len(reruns)
    return Answer(text, ok == "true", "" if ok == "true" else error,
                  thread_errors=consumed.count(THREAD_ERROR), reruns=reruns), raw


def reruns_in(consumed: bytes, seq: int) -> list[str]:
    """The sentinels in `consumed` of chunks the console ran AGAIN: a call already answered
    before this one (its first sentinel was consumed by an earlier look), or one printed
    twice inside this window. A line legitimately ahead in the pipe (a `throttle`'s, read by
    the step this call spent for it) prints its sentinel once, here, for the first time, and
    is not a rerun; a number this server never sent is a script's own text and never counts."""
    seen: dict[int, int] = {}
    for n_s in _SENTINEL_SEQ.findall(consumed):
        n = int(n_s)
        if n == seq or n > STATE.lua_seq:
            continue
        seen[n] = seen.get(n, 0) + 1
    out: list[str] = []
    for n, times in sorted(seen.items()):
        reran = times if n <= STATE.lua_answered else times - 1
        out.extend([st.sentinel_line(n)] * reran)
    return out


def count_deaths(scratch: Path) -> None:
    """Fold every reader death the console has printed and nobody has counted yet.

    BY POSITION, which is the only way this can be exactly-once. The paths that meet a death
    OVERLAP: a refusal reads bytes it never consumes, the resend of a lost line reads them
    again, and a later answer consumes the lot. Counting per path would either count one
    death several times or, on the path that raises, never at all, and a refusal would then
    name deaths that its own session block does not count.
    A byte offset can only be passed once, so it does not matter who asks or in what order.
    """
    size = stdout_mark(scratch)
    if size <= STATE.console_counted:
        return
    with open(files.log_path(scratch, "process"), "rb") as fh:
        fh.seek(STATE.console_counted)
        fresh = fh.read(size - STATE.console_counted)
    STATE.console_thread_errors += fresh.count(THREAD_ERROR)
    STATE.console_counted = size
    _settle_pending(scratch)


def _settle_pending(scratch: Path) -> None:
    """Settle each call still pending against the log: its sentinel means it ran, `eaten`
    (or, for a chunk of this server's own, `passed_over`) means it never will and it is
    counted lost. Asked where new bytes are counted, because
    only new bytes can settle one; `record_lost` can settle others on the way, so each entry
    is looked up again rather than taken from the snapshot."""
    for seq in list(STATE.lua_pending):
        entry = STATE.lua_pending.get(seq)
        if entry is None:
            continue
        line, mark = entry
        raw = since(scratch, mark)
        if f"{st.sentinel_line(seq)}\t".encode() in raw:
            STATE.lua_pending.pop(seq, None)
            STATE.lua_ours.discard(seq)
        elif passed_over(raw, line) if seq in STATE.lua_ours else eaten(raw, line):
            record_lost(seq)


def count_unread(scratch: Path) -> None:
    """Fold into the session what the console's stdout holds that no lua-family call has
    read: the reader deaths, by position (`count_deaths`), and the reruns in the tail no
    answer consumed. For `close`, whose session block would otherwise say three zeros about
    a log that shows a death and a chunk run twice. The consume mark does not move: nothing
    is answered here."""
    count_deaths(scratch)
    log = files.log_path(scratch, "process")
    if not log.exists():
        return
    with open(log, "rb") as fh:
        fh.seek(STATE.console_mark)
        raw = fh.read()
    STATE.console_reruns_seen += len(reruns_in(raw, 0))


def record_lost(seq: int) -> None:
    """Call `seq` was taken by the console and never evaluated: hold it against the session.

    ONE FUNCTION AND NOT SIX ASSIGNMENTS, because a count kept by hand at every loss site is a
    count that goes short the day a seventh path finds one. `lua_lost` is a MAXIMUM, which is
    what its own name promises: a later loss cannot lower it, and a path that assigned
    directly could. AND ONCE PER CALL: several paths can prove the same line eaten (the call
    that sent it, the tally's readers, the settling of what is pending), and only the first
    finds it still pending.
    """
    STATE.lua_ours.discard(seq)
    if STATE.lua_pending.pop(seq, None) is None:
        return
    STATE.lua_lost = max(STATE.lua_lost, seq)
    STATE.console_lines_lost += 1
    # AND THE DEATHS AROUND IT ARE COUNTED HERE TOO, because a loss can be established by a
    # path that never reads an answer: the tally's readers find one with `eaten` and nothing
    # else in that session may ever call the console again. Counting is by position, so
    # asking twice costs nothing and misses nothing.
    if STATE.scratch is not None:
        count_deaths(STATE.scratch)


def eaten(raw: bytes, line: str) -> bool:
    """Whether `line` was TAKEN by the console and never evaluated: its echo is there, one of
    the two failures below follows it, and no sentinel of the call ever came (the caller has
    already looked for one). A line taken and not evaluated runs ONCE when it is sent again,
    which is what makes a single resend safe for a script that writes.

    TWO SHAPES, BOTH SEEN ON THE SAME BOARD, and they are one fact to a caller:

    - THE READER DIED holding it, printing `[LUA ERROR] in thread:` (the first line
      of a session, echoed, then "return value must be string", and never run). Only one
      reader exists at a time, so a death after the echo is that reader's.
    - THE CONSOLE REPORTED THE LINE'S OWN top-level failure and carried on, printing its
      `error:` line and handing back the prompt. The reader is alive and the line is just as
      dead: `load` never ran, so the script inside it never did either.

    Missing the second shape costs exactly what `install_lost` exists to prevent: a tally
    whose install line failed this way would sit at `installed: false, pending: true` for ever,
    waiting for an answer that could not arrive.

    WHAT THE SECOND SHAPE HAS TO SATISFY is beside `_CONSOLE_ERROR` below, with the reason.
    Here: it must follow the ECHO, because the console's tail holds the whole session and a
    report sitting before this line belongs to another one.
    """
    i = raw.find((line + "\n").encode())
    if i < 0:
        return False
    after = raw[i:]
    if THREAD_ERROR in after:
        return True
    found = _CONSOLE_ERROR.search(after)
    return found is not None and CONSOLE_PROMPT in after[found.end():]


def passed_over(raw: bytes, line: str) -> bool:
    """Whether the console is DONE with `line` and never ran it, asked once its sentinel has
    been looked for and not found: `eaten`, or its echo followed by the console's prompt. Every
    reader prints the prompt before it reads, and the hook starts the next reader only once it
    has finished with the line the last one echoed (`plugins/console/init.lua`), so a prompt
    BEHIND the echo is the hook gone past the line, and the one before it is the reader that
    echoed it. A line the hook has not got to has no prompt behind it, however many frames pass.

    ONLY FOR THE SERVER'S OWN CHUNKS (`send(ours=True)`), which print no prompt: a script of
    the MCP caller's is free to print the prompt's bytes and then hang, which is why `eaten`
    asks for the console's own error framing first."""
    if eaten(raw, line):
        return True
    echo = (line + "\n").encode()
    i = raw.find(echo)
    return i >= 0 and CONSOLE_PROMPT in raw[i + len(echo):]


def emulator_gone() -> int | None:
    """The emulator's exit code once it has gone, or None while it is still there."""
    return STATE.proc.poll() if STATE.proc is not None else None


def died_waiting(code: int, waiting_for: str, tail: str = "", **fields: Any) -> st.Invalid:
    """The refusal a wait loop raises when MAME went while it waited.

    ONE SHAPE FOR EVERY SUCH LOOP, because it is the same lie wherever it is told: every
    bound here expires into words about a machine that will execute again ("still pending in
    the pipe", "the switch is still pending"), and about a process that is GONE those
    describe a busy machine. The caller then sits out the whole bound to be told to wait
    longer. Which loop it was is in `waiting_for`, so the refusal still says what it was
    doing rather than only what happened to it."""
    said = (f"MAME exited with code {code} while this call waited for {waiting_for}: it is "
            "gone, and no answer can come from it")
    return st.Invalid("session_broken", f"{said}. {tail}" if tail else said,
                      exit_code=code, **fields)


def _not_answered(seconds: float, seen: int) -> st.Invalid:
    return st.Invalid("wait_expired",
        f"the console did not answer within {seconds:g} s: no sentinel for the line is in "
        "the log, and the console evaluates a line only when its hook runs: a step, a frame, "
        "or a console command on a stub that refreshes the display after one",
        pending=True, seen_bytes=seen)


def await_answer(scratch: Path, line: str, seq: int, seconds: float,
                 progress: mprogress.Progress = mprogress.no_progress) -> Answer:
    """The console's answer to `line`, polled for up to `seconds`. The bound expiring means
    no sentinel for it arrived; whether the console had taken the line is not asked here."""
    clock = mprogress.Ticker(seconds, progress)
    while True:
        answer, raw = find_answer(scratch, line, seq)
        if answer is not None:
            return answer
        gone = emulator_gone()
        if gone is not None:
            raise died_waiting(gone, "the console's answer", seen_bytes=len(raw))
        if clock.expired():
            raise _not_answered(seconds, len(raw))
        clock.tick("lua: waiting for the console's answer, {elapsed:.0f}s of {seconds:g}s",
                   seconds=seconds)
        time.sleep(POLL_S)


# How many lines ahead of its own a `lua` call will step for; beyond that a frame drains
# them all at once, which is the cheaper route and does not move the pc one instruction
# per line.
PIPE_STEPS_MAX = 8


# THE CONSOLE'S READER IS A THREAD (`plugins/console/init.lua` starts the linenoise read in
# an `emu.thread`), and the periodic hook, run ONCE at a stop, returns without evaluating
# while that thread is still taking the line. On m68k-dual a signature sent right
# after another has its step land before the reader holds the line, and one more step
# evaluates it at once. So an answer is given this window after a step, then another step
# is spent, up to a cap that keeps a console that never answers a refusal rather than an
# endless walk.
READER_WAIT_S = 0.5
READER_STEPS_MAX = 3


# AND THE THREAD IS UNSAFE BY MAME'S OWN ADMISSION (`luaengine.cpp`, `thread_context::start`:
# "FIXME: this is unsafe as the thread function modifies members of the object"): the
# reader clears `busy` BEFORE it has finished unwinding, and the hook that finds it idle
# loads the next read into the SAME Lua state while it still runs there. A step sent the
# instant the line is written lands its stop inside that window: on m68k-dual the
# reader dies at start ("[LUA ERROR] in thread: attempt to index a nil value" in `require`,
# `setcompletion` read as a table, "return value must be string"), and after each death the
# hook, whose `result` a failed thread never clears, RUNS THE PREVIOUS CHUNK AGAIN (the same
# sentinel prints twice) before a new reader took the line. So every `send` waits this long
# after the write, before its caller can move the machine, which is what lets the reader
# finish (measured: the late-reader steps stopped being needed); what still happens is
# counted and said in the reply (`thread_errors`, `console_reruns`, its `note`), never
# silent, because a chunk run twice is a second write for a script that writes.
READER_SETTLE_S = 0.02
THREAD_ERROR = b"[LUA ERROR] in thread:"


# THE CONSOLE'S PROMPT, which is what says it has FINISHED with a line. Captured with its
# colour codes, because that is how it arrives.
CONSOLE_PROMPT = b"\x1b[1;36m[MAME]\x1b[0m> "


# HOW THE CONSOLE FRAMES A LINE'S OWN TOP-LEVEL FAILURE, captured from the board: `error:` at
# a line start, a TAB, then the chunk's name, and the PROMPT behind it. Both halves are
# required. The framing alone is reachable by an ordinary Lua idiom -- `print("error:", e)`
# joins its arguments with a tab, and a failed `load` hands back exactly
# `[string "..."]:N: ...` -- so a script that printed that and then HUNG would be read as a
# line the console gave up on, and resent. A resend is a SECOND execution of somebody's
# script, which is the one harm a wrong verdict here can do, and a hung script is the one
# thing that cannot produce a prompt.
_CONSOLE_ERROR = re.compile(rb'^error: \t\[string "', re.M)
_SENTINEL_SEQ = re.compile(re.escape(st.LUA_SENTINEL).encode() + rb"#(\d+)\t")


def answered_seq(scratch: Path) -> int:
    """The highest call number the console has printed a sentinel for: what it has READ
    from the pipe, against `STATE.lua_seq`, what was sent. Nothing printed is zero. A
    number this server never sent is a script printing the sentinel's text itself (the raw
    `lua` can), and it does not count: a fake higher than every real one would otherwise
    read every later line as already answered and buy it no step at all."""
    log = files.log_path(scratch, "process")
    printed = [int(x) for x in _SENTINEL_SEQ.findall(log.read_bytes())] if log.exists() else []
    # A line the reader died holding never prints and is not ahead either: it is gone.
    return max([STATE.lua_lost] + [n for n in printed if n <= STATE.lua_seq])


def pending_lines(scratch: Path) -> int:
    """The lines the console has not evaluated, for a caller that has not sent one: what
    `status` reports and what `close` drains. Same reading as `_lines_ahead`, named for the
    outside."""
    return _lines_ahead(scratch)


def drain(ses: gs.Session, scratch: Path, seconds: float = 2.0) -> tuple[int, int]:
    """Step the console's pipe empty on a STOPPED machine, and say how deep it was and how
    many lines went.

    WHY `close` DOES THIS. A chunk left unevaluated in the pipe is a chunk MAME's Lua state
    still holds at `quit`, and its garbage collector tore one down on the way out: SIGSEGV
    inside `lua_engine::close`, in `destroy_usertype_storage<natural_keyboard>`, which is
    the input binding an unevaluated `input` script had reached for. A clean exit is what
    writes `cfg/` and `nvram/`, so the backlog is spent before
    the exit is asked for, never after."""
    before = _lines_ahead(scratch)
    # A RUNNING MACHINE IS NOT STEPPED, and needs no help: its own periodic hook reads the
    # pipe every frame. Every other stepper in this package sits behind a stopped gate, and
    # `throttle` (the one wrapper callable while the guest runs) can leave a line queued
    # with the machine still going, so `close` reaches here on a live run. A step sent into
    # an outstanding continue is the desync this channel is built to avoid.
    if not before or ses.running:
        return before, 0
    clock = mprogress.Ticker(seconds, mprogress.no_progress)
    spent = 0
    while _lines_ahead(scratch) and spent < before + PIPE_STEPS_MAX and not clock.expired():
        try:
            ses.step()
        except gs.SessionError:
            break
        spent += 1
        time.sleep(POLL_S)
    return before, before - _lines_ahead(scratch)


def _too_deep(ahead: int) -> str:
    """The refusal when the pipe is deeper than the steps a call will spend on it.

    THE REMEDY IS A FRAME. A STEP evaluates one line; a FRAME evaluates several, though not
    necessarily every line queued, so a frame is the cheap route and a deep pipe may still want
    a few. It does
    not promise one frame is enough: `status` reports `console_pending`, so the caller can
    read the pipe empty instead of guessing."""
    return (f"{prose.counted(ahead, 'line')} are still ahead in the console's pipe, more than the "
            f"{PIPE_STEPS_MAX} steps this call would spend to reach its own: `run_for` a frame or "
            "a few to drain them (a frame evaluates several lines, a step one), and `status` "
            "reports `console_pending` so you can see it empty")


def refuse_if_too_deep(scratch: Path) -> int:
    """How deep the console's pipe is, refusing outright past what a call will step off.

    IT IS PUBLIC SO A CALLER CAN ASK BEFORE IT COUNTS ITSELF. `lua` stamps the session (a
    write, or a `read_only` claim) and then evaluates; with the refusal only inside the
    evaluation, a call turned away for a backlog somebody ELSE left had already been counted
    and the session block reported a call that never reached the console. Asking here first
    costs one read of a file this already reads."""
    ahead = _lines_ahead(scratch)
    if ahead > PIPE_STEPS_MAX:
        raise st.Invalid("bad_argument", _too_deep(ahead), lines_ahead=ahead)
    return ahead


def _lines_ahead(scratch: Path) -> int:
    """How many lines are still ahead in the console's pipe: what was sent against what the
    console has printed a sentinel for. ONE spelling, read by the raw form, by the wrappers
    and by `status`, so the number a caller sees before a call is the number that call acts
    on, except that on a stub that refreshes the display after a console command, the one a
    call opens with (its pc read) can take a line first."""
    count_deaths(scratch)   # a pending line the log now proves eaten is not ahead any more
    return max(0, STATE.lua_seq - answered_seq(scratch))


def evaluate(ses: gs.Session, scratch: Path, script: str, seconds: float,
             progress: mprogress.Progress, pc_before: int,
              alters: bool = True) -> tuple[Answer, int, str, int, int, int]:
    """Send `script` and buy its evaluation: the answer, the lines that were ahead of it,
    the words for how it was bought, the steps spent for the reader, how many times the
    line was sent again after the reader died holding it, and the call's number
    (its sentinel's, `call` in every reply, so a lost answer can be found in `log` without
    ambiguity). `alters` is what the caller counts: a refusal says the machine moved either
    way, and "altered" only when it is.

    THE CONSOLE READS ONE LINE EACH TIME ITS HOOK RUNS: a `throttle` asked while stopped leaves
    its line in the pipe, and one step bought for the script would evaluate the THROTTLE, never
    the script, answering `wait_expired` with the session altered. So the lines still ahead in
    the pipe are counted first (the sentinels the console has printed against the lines sent;
    on a stub that refreshes after a debugger command, the caller's own read of the pc has
    taken one already) and the machine is stepped once for each of them, then once for this
    line."""
    ahead = refuse_if_too_deep(scratch)
    line, seq = send(script)
    for _ in range(ahead + 1):
        ses.step()
    # The steps for the lines ahead and for this one are spent; then the answer is given
    # the reader's window after each step, and while it does not come one more step is
    # spent for the reader (`reader_steps`), within the bound and under the cap. A line the
    # reader died holding is sent again, once (`resent`): it was never evaluated.
    clock = mprogress.Ticker(seconds, progress)
    stepped_at = time.monotonic()
    reader_steps = 0
    resent = 0
    while True:
        answer, raw = find_answer(scratch, line, seq)
        if answer is not None:
            break
        steps = ahead + 1 + reader_steps + resent
        moved = (f"The machine was stepped {prose.counted(steps, 'time')} for it"
                 + (f" ({reader_steps} of them for the console's reader, which had not "
                    "taken the line at the stop)" if reader_steps else "")
                 + (" and the session is altered" if alters else ", which alters nothing"))
        common: dict[str, Any] = dict(pc_before=st.hex_addr(pc_before), lines_ahead=ahead,
                                      reader_steps=reader_steps, resent=resent,
                                      evaluated_by=_steps_word(steps),
                                      call=st.sentinel_line(seq))
        # THE EMULATOR ITSELF, asked before the bound is judged: a MAME that died mid-call
        # would otherwise be answered with `wait_expired`'s words about a machine that
        # executes again, and the caller sits out the whole bound to be told to wait longer.
        gone = emulator_gone()
        if gone is not None:
            raise died_waiting(gone, "the console's answer", moved, **common)
        if clock.expired():
            e = _not_answered(seconds, len(raw))
            raise st.Invalid(e.code, f"{e}. {moved}; the answer, when it comes, lands in "
                             f"`log` (channel `process`) as the line {st.sentinel_line(seq)} "
                             "followed by a tab (the echo of the command carries the same "
                             "text without it)", **e.fields, **common) from None
        if eaten(raw, line):
            record_lost(seq)
            if resent:
                raise st.Invalid("reader_died", f"{DIED_TWICE} {moved}", pending=False,
                                 thread_errors=raw.count(THREAD_ERROR),
                                 console_reruns=len(reruns_in(raw, seq)), **common)
            line, seq = send(script)
            resent += 1
            ses.step()
            stepped_at = time.monotonic()
            continue
        if (reader_steps < READER_STEPS_MAX
                and clock.now - stepped_at >= READER_WAIT_S):
            ses.step()
            reader_steps += 1
            stepped_at = time.monotonic()
        clock.tick("lua: waiting for the console's answer, {elapsed:.0f}s of {seconds:g}s",
                   seconds=seconds)
        time.sleep(POLL_S)
    return answer, ahead, _steps_word(ahead + 1 + reader_steps + resent), reader_steps, resent, seq


def _steps_word(steps: int) -> str:
    return "one step" if steps == 1 else prose.counted(steps, "step")


DIED_TWICE = ("the console took the line and never evaluated it, twice (its echo is in the "
              "log, with no sentinel after it and either a dead reader or the console's own "
              "`error:` beside it): the script was NEVER evaluated.")


def console_did(answer: Answer, resent: int = 0) -> dict[str, Any]:
    """The console's own mishaps around this answer, as reply fields: always present, so
    a zero is read as looked-at, and a `note` only when there is something to say, which a
    reply joins to its tool's own (`st.merged`), since both can have something to say.

    THE NOTE SPEAKS FOR EVERY NON-ZERO COUNTER, each in its own clause, because a counter at
    1 beside no sentence is two answers to one question. `resent` is the one that can stand
    ALONE: a line the console refused at its top level (`eaten`'s second shape) leaves no dead
    reader and no rerun behind."""
    out: dict[str, Any] = {"thread_errors": answer.thread_errors,
                           "console_reruns": len(answer.reruns), "resent": resent}
    said = []
    if answer.thread_errors:
        said.append(f"the console's reader died {prose.counted(answer.thread_errors, 'time')} "
                    "starting up")
    if answer.reruns:
        said.append(f"the console ran {prose.counted(len(answer.reruns), 'earlier chunk')} AGAIN "
                    f"({', '.join(answer.reruns)}): a chunk that wrote has written twice; MAME's "
                    "console thread is unsafe by its own admission")
    if resent:
        said.append("the console took this call's line and never evaluated it, so it was sent "
                    f"again ({prose.counted(resent, 'time')}) and evaluated once: a script that "
                    "writes has written once, not twice")
    return st.add_note(out, *said)


def check_script(script: str) -> None:
    """What a SCRIPT has to be before it goes in the pipe: present, and short enough for a console
    line. `send` is reached by callers with no bound of their own, which is why this is its own
    name rather than part of `check_lua`."""
    if not script.strip():
        raise st.Invalid("bad_argument", "the script is empty: nothing to evaluate")
    if len(script) > SCRIPT_MAX:
        raise st.Invalid("bad_argument",
            f"the script is {len(script)} chars, above the {SCRIPT_MAX} ceiling of a console "
            "line: a script that size is a file, and `start` takes one as `boot_lua`")


# When the console reads a line, in the shortest form that stays true, for the texts a client
# reads and cannot follow a link from: `throttle`'s description and `applies`, a tap's install
# `note`. The statement whole is REFERENCE.md's, under *The console*.
CONSOLE_READS = ("a step, the next frame emulated, or a debugger command on a stub that "
                 "refreshes after one")
