"""A Lua chunk sent down MAME's stdin and its answer read back off stdout. `mame_lua` says why
the channel exists.

An answer is framed by a sequence number in the chunk and in a sentinel line it prints last
through `pcall`, never by the prompt (a script can print those bytes).
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

SCRIPT_MAX = 16000


POLL_S = 0.02


def lua_string(text: str) -> str:
    """`text` as a Lua double-quoted literal on ONE line."""
    escaped = (text.replace("\\", "\\\\").replace('"', '\\"')
               .replace("\r", "\\r").replace("\n", "\\n"))
    return f'"{escaped}"'


def chunk_line(script: str, seq: int) -> str:
    """A script as the one console line, closed by call `seq`'s sentinel."""
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
    """The console's stdout mark; a test seam. Taken before a write so a survived `[LUA ERROR]
    in thread` in the unconsumed tail is not read as this call's death."""
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
    """Write `script` to the pipe; return the line and its sequence number. Returns after
    `READER_SETTLE_S`. `ours`: this server's own script, which prints no prompt."""
    check_script(script)
    pipe = _stdin()
    seq = STATE.lua_seq + 1
    line = chunk_line(script, seq)
    size = stdout_mark(STATE.scratch) if STATE.scratch is not None else 0
    try:
        pipe.write(line.encode() + b"\n")
        pipe.flush()
    except OSError as e:
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
    """One call's answer; `reruns` are sentinels of earlier calls printed again."""

    def __init__(self, text: str, ok: bool, error: str,
                 thread_errors: int = 0, reruns: list[str] | None = None) -> None:
        self.text, self.ok, self.error = text, ok, error
        self.thread_errors, self.reruns = thread_errors, reruns or []


def _echo(raw: bytes, line: str) -> tuple[int, int]:
    """Where `line`'s echo starts in `raw` and how long it is, or (-1, 0). MAME on Windows writes
    its stdout in text mode, so a line there ends in CRLF."""
    found = [(i, len(e)) for e in ((line + "\r\n").encode(), (line + "\n").encode())
             if (i := raw.find(e)) >= 0]
    return min(found) if found else (-1, 0)


def find_answer(scratch: Path, line: str, seq: int) -> tuple[Answer | None, bytes]:
    """One look for the text between `line`'s echo and `seq`'s sentinel; also the bytes read."""
    log = files.log_path(scratch, "process")
    sentinel = f"{st.sentinel_line(seq)}\t".encode()
    raw = b""
    if log.exists():
        with open(log, "rb") as fh:
            fh.seek(STATE.console_mark)
            raw = fh.read()
    count_deaths(scratch)
    i, echoed = _echo(raw, line)
    j = raw.find(sentinel, i + echoed) if i >= 0 else -1
    end = raw.find(b"\n", j) if j >= 0 else -1
    if end < 0:
        return None, raw
    STATE.console_mark += end + 1
    outcome = raw[j + len(sentinel):end].rstrip(b"\r").decode("utf-8", errors="replace")
    ok, _, error = outcome.partition("\t")
    text = raw[i + echoed:j].replace(b"\r\n", b"\n").decode("utf-8", errors="replace")
    consumed = raw[:end]
    reruns = reruns_in(consumed, seq)
    STATE.lua_answered = max(STATE.lua_answered, seq)
    STATE.console_reruns_seen += len(reruns)
    return Answer(text, ok == "true", "" if ok == "true" else error,
                  thread_errors=consumed.count(THREAD_ERROR), reruns=reruns), raw


def reruns_in(consumed: bytes, seq: int) -> list[str]:
    """Sentinels in `consumed` of chunks run again; a number never sent is a script's own text."""
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
    """Fold uncounted reader deaths into the session, by byte position: the paths that meet
    one read overlapping bytes."""
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
    """Settle each pending call: ran, lost, or still pending. Entries are re-looked-up as
    `record_lost` can settle others."""
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
    """Fold the deaths and the reruns in the unconsumed tail into the session, for `close`."""
    count_deaths(scratch)
    log = files.log_path(scratch, "process")
    if not log.exists():
        return
    with open(log, "rb") as fh:
        fh.seek(STATE.console_mark)
        raw = fh.read()
    STATE.console_reruns_seen += len(reruns_in(raw, 0))


def record_lost(seq: int) -> None:
    """Hold lost call `seq` against the session, once: several paths can prove it eaten."""
    STATE.lua_ours.discard(seq)
    if STATE.lua_pending.pop(seq, None) is None:
        return
    STATE.lua_lost = max(STATE.lua_lost, seq)
    STATE.console_lines_lost += 1
    # A loss can be found by a path that never reads an answer.
    if STATE.scratch is not None:
        count_deaths(STATE.scratch)


def eaten(raw: bytes, line: str) -> bool:
    """Whether the console took `line` and never evaluated it, so a resend runs it once.
    Two shapes after the echo: the reader died holding it, or the console reported the line's
    own `error:` and returned the prompt (`_CONSOLE_ERROR`).
    """
    i, _ = _echo(raw, line)
    if i < 0:
        return False
    after = raw[i:]
    if THREAD_ERROR in after:
        return True
    found = _CONSOLE_ERROR.search(after)
    return found is not None and CONSOLE_PROMPT in after[found.end():]


def passed_over(raw: bytes, line: str) -> bool:
    """Whether the console is done with `line` and never ran it: `eaten`, or a prompt behind
    the echo. Only for the server's own chunks: a caller's script can print the prompt and hang."""
    if eaten(raw, line):
        return True
    i, echoed = _echo(raw, line)
    return i >= 0 and CONSOLE_PROMPT in raw[i + echoed:]


def emulator_gone() -> int | None:
    """The emulator's exit code once it has gone, or None while it is still there."""
    return STATE.proc.poll() if STATE.proc is not None else None


def died_waiting(code: int, waiting_for: str, tail: str = "", **fields: Any) -> st.Invalid:
    """The refusal when MAME went while a loop waited, instead of "still pending" words."""
    said = (f"MAME {prose.ended_by(code)} while this call waited for {waiting_for}: it is "
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
    """The console's answer to `line`, polled for up to `seconds`."""
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


PIPE_STEPS_MAX = 8


# The periodic hook returns without evaluating while the reader thread still takes the line.
READER_WAIT_S = 0.5
READER_STEPS_MAX = 3


# The reader thread is unsafe by MAME's own admission (`luaengine.cpp`, `thread_context::start`):
# it clears `busy` before unwinding, so a step in that window kills it and the hook reruns the
# previous chunk. Every `send` waits this long; what still happens is counted in the reply.
READER_SETTLE_S = 0.02
THREAD_ERROR = b"[LUA ERROR] in thread:"


CONSOLE_PROMPT = b"\x1b[1;36m[MAME]\x1b[0m> "


# Both halves are required: `print("error:", e)` reproduces the framing, and a script that
# printed it and hung would be resent, a second execution. A hung script prints no prompt.
_CONSOLE_ERROR = re.compile(rb'^error: \t\[string "', re.M)
_SENTINEL_SEQ = re.compile(re.escape(st.LUA_SENTINEL).encode() + rb"#(\d+)\t")


def answered_seq(scratch: Path) -> int:
    """The highest call number the console has printed a sentinel for, zero if none; a number
    never sent is ignored, or a fake would read later lines as answered."""
    log = files.log_path(scratch, "process")
    printed = [int(x) for x in _SENTINEL_SEQ.findall(log.read_bytes())] if log.exists() else []
    return max([STATE.lua_lost] + [n for n in printed if n <= STATE.lua_seq])


def pending_lines(scratch: Path) -> int:
    """Lines the console has not evaluated, for `status` and `close`."""
    return _lines_ahead(scratch)


def drain(ses: gs.Session, scratch: Path, seconds: float = 2.0) -> tuple[int, int]:
    """Step the pipe empty on a stopped machine; return its depth and the lines that went.
    An unevaluated chunk at `quit` makes MAME SIGSEGV in `lua_engine::close`, losing `cfg/`
    and `nvram/`."""
    before = _lines_ahead(scratch)
    # A step sent into an outstanding continue is a desync; a running machine reads the pipe.
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
    """The refusal when the pipe is deeper than the steps a call will spend."""
    return (f"{prose.counted(ahead, 'line')} are still ahead in the console's pipe, more than the "
            f"{PIPE_STEPS_MAX} steps this call would spend to reach its own: `run_for` a frame or "
            "a few to drain them (a frame evaluates several lines, a step one), and `status` "
            "reports `console_pending` so you can see it empty")


def refuse_if_too_deep(scratch: Path) -> int:
    """How deep the pipe is, refusing past the step cap. Public so `lua` asks before it
    stamps the session."""
    ahead = _lines_ahead(scratch)
    if ahead > PIPE_STEPS_MAX:
        raise st.Invalid("bad_argument", _too_deep(ahead), lines_ahead=ahead)
    return ahead


def _lines_ahead(scratch: Path) -> int:
    """Lines still ahead in the pipe: sent against sentinels printed."""
    count_deaths(scratch)   # a line the log now proves eaten is not ahead
    return max(0, STATE.lua_seq - answered_seq(scratch))


def evaluate(ses: gs.Session, scratch: Path, script: str, seconds: float,
             progress: mprogress.Progress, pc_before: int,
              alters: bool = True) -> tuple[Answer, int, str, int, int, int]:
    """Send `script` and step for its evaluation. Returns the answer, the lines ahead, the
    words for how it was bought, the reader steps, the resends, and the call's number.
    `alters`: whether the refusal says "altered".

    The console reads one line per hook run, so lines ahead (a `throttle`) are stepped for first."""
    ahead = refuse_if_too_deep(scratch)
    line, seq = send(script)
    for _ in range(ahead + 1):
        ses.step()
    # Extra steps for the reader under the cap; a line it died holding is resent once.
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
    """The console's mishaps as reply fields, plus a `note` for every non-zero counter."""
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
    """A script must be non-empty and short enough for a console line."""
    if not script.strip():
        raise st.Invalid("bad_argument", "the script is empty: nothing to evaluate")
    if len(script) > SCRIPT_MAX:
        raise st.Invalid("bad_argument",
            f"the script is {len(script)} chars, above the {SCRIPT_MAX} ceiling of a console "
            "line: a script that size is a file, and `start` takes one as `boot_lua`")


# For client texts that cannot link out; REFERENCE.md, *The console*, has it whole.
CONSOLE_READS = ("a step, the next frame emulated, or a debugger command on a stub that "
                 "refreshes after one")
