"""The FILE family: memory to a file, a PNG of the screen, the lines of `error.log`, and the
wait for a line of it.

The tools here that answer with a PATH and not with content each CHECK the file they claim
to have produced: `memdump` (the console's `save`, then the size and a protocol read of the
first bytes) and `snapshot` (the console's `snap`, then a complete PNG). Every `dest` is
judged before any console is touched (`mame_inputs.fresh_dest`), so a refused call never leaves
a file behind.
`log` reads the newest matching lines of a channel, capped; `log_wait` is its waiting form,
the one channel that answers while the machine RUNS; and `errorlog_since` is what a stop
reply shows of the log since the previous stop. `wav_header` and `wav_levels` read the WAV
MAME's mixer writes, for `audio_record` and for `captures`.
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import sys
import time
from array import array
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal, NamedTuple, TypeVar, overload

from scry_core import judges, prose
from scry_core import log_wait as core_wait
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core.reply_contract import or_unavailable

import gdb_session as gs
import mame_cpus as cpus
import mame_envelope as menvelope
import mame_inputs as inputs
import mame_read as read
import mame_state as st
from mame_state import STATE

# How long a tool waits for a file the emulator writes at its own pace after the command that
# asked for it (a `snap`'s PNG, a `statesave`, the AVI a recording closes on its way out), and
# how often it looks.
FILE_WAIT_S = 2.0
FILE_POLL_S = 0.02
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_TRAILER = b"IEND\xaeB`\x82"

# THE WAV MAME'S MIXER WRITES (`util::wav_open` in `src/lib/util/wavwrite.cpp`): a 44-byte header,
# 16-bit PCM, the RIFF and data sizes written only when the file is closed. The levels are read in
# bounded chunks, an even number of bytes so no sample is split, whatever the recording's length.
WAV_HEADER_BYTES = 44
WAV_HEADER = struct.Struct("<4sI4s4sIHHIIHH4sI")
WAV_CHUNK_BYTES = 1 << 20


Waited = TypeVar("Waited")


def wait_for(check: Callable[[], Waited], bound_s: float, poll_s: float) -> Waited:
    """`check()` until it answers (anything but None or False: a count of 0 is an answer) or
    `bound_s` passes; its last answer either way."""
    deadline = time.monotonic() + bound_s
    while True:
        got = check()
        if (got is not None and got is not False) or time.monotonic() >= deadline:
            return got
        time.sleep(poll_s)


def whole_file(path: Path, length: int, said: str, command: str, after: str = "",
               **fields: Any) -> None:
    """Refuse unless the file a console `command` was to write is there and `length` bytes;
    `after` closes the message and `fields` ride on the refusal. The console's own sentence is
    no proof: `save` and `saver` clamp a span at the end of what they read and still say they
    succeeded."""
    if not path.exists():
        raise st.Invalid("unexpected_answer", f"no file at {path} came out of the console's "
                         f"`{command}`; the console said {said.strip()!r}{after}", **fields)
    size = path.stat().st_size
    if size != length:
        raise st.Invalid("readback_refused", f"{prose.counted(size, 'byte')} came out of "
                                             f"`{command}` "
                         f"where {length} were asked; the file is left at {path}{after}", **fields)


def refuse_console_path(path: Path) -> None:
    """A path of the server's own making that the console would cut: the host's failure (its
    scratch sits somewhere unusual), never the caller's argument."""
    if broken := inputs.path_break(str(path)):
        raise st.Invalid("host_failed", f"the scratch path {str(path)!r} holds "
                         f"{broken!r}, which a path handed to the console may not hold")


def unreadable(thing: str, path: str, e: OSError, **fields: Any) -> st.Invalid:
    """The refusal of a caller's file the server cannot read: the caller's argument, naming it."""
    return st.Invalid("bad_argument", f"cannot read the {thing} {path}: {e.strerror or e}",
                      **fields)


def not_utf8(path: str, e: UnicodeDecodeError, **fields: Any) -> st.Invalid:
    """The refusal of a caller's file that is not UTF-8 text, naming it and where it broke."""
    return st.Invalid("bad_argument", f"{path} is not UTF-8 text: {e}", **fields)


def read_text(name: str, path: str, thing: str, **fields: Any) -> str:
    """A caller's TEXT file, read whole: `inputs.input_file`, then refused as `unreadable` or
    `not_utf8`, never an exception out of the tool. A fault in the caller's file is the caller's
    argument."""
    file = inputs.input_file(name, path, thing, **fields)
    try:
        return file.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise not_utf8(path, e, **fields) from None
    except OSError as e:
        raise unreadable(thing, path, e, **fields) from None


def check_memdump(length: int, dest: str, ref: str = "", **_: Any) -> Path:
    """`memdump`'s machine-independent half, and it hands back the `Path` it built so the caller
    that is about to write does not build it twice. The path goes FIRST because a caller who named
    a file this server cannot write has to hear about the file."""
    inputs.check_ref(ref)
    dest_path = inputs.fresh_dest("dest", dest)
    inputs.count("length", length, tail=": a length counts bytes")
    return dest_path


def memdump(ses: gs.Session, ref: str, length: int, dest: str, cpu: str = "") -> dict[str, Any]:
    """The body of the `memdump` tool."""
    dest_path = check_memdump(length, dest, ref)
    on, thread, suffix = save_target(ses, cpu)
    addr = STATE.resolve(ref, on)
    refused = save_checked(ses, on, thread, suffix, addr, length, dest_path, keep=True)
    if refused is not None:
        return refused
    return menvelope.envelope({
        "addr": st.hex_addr(addr), "length": length, "path": str(dest_path),
        "bytes": dest_path.stat().st_size, "cpu": or_unavailable(on, st.NO_CPU_READ_WHY),
    })


def save_target(ses: gs.Session, cpu: str) -> tuple[str | None, int, str]:
    """The cpu the console's `save` reads, the stub thread its control read goes through, and the
    `:<cpu>` suffix the `save` line carries.

    THE CONTROL READS THE SAME CPU `save` DOES, named in both: through that cpu's thread on the
    patched stub. Without one the stub reads only its first cpu, so a file of another cpu's
    memory could not be checked at all; there `save` keeps the visible cpu when no cpu is named,
    and a console that marks none leaves the cpu null and the check the first cpu's."""
    if ses.threads:
        on, thread = cpus.thread_for(ses, cpu)
    else:
        on, thread = cpus.chosen(ses, cpu), 1
        if on is not None and on != (served := cpus.stub_cpu(ses)):
            raise st.Invalid("bad_argument",
                f"`save` reads {on}, and the file is checked against a read of the same range "
                f"through the stub, which without the gdbstub's thread patch reads only "
                f"{served}: `memdump(cpu={served!r})` is the dump it can check")
    # `save <file>,<addr>[:<cpu>],<len>`, the cpu named wherever the control is its thread's
    return on, thread, (f":{on}" if on and (ses.threads or inputs.cpu_given(cpu)) else "")


@overload
def save_checked(ses: gs.Session, on: str | None, thread: int, suffix: str, addr: int,
                 length: int, path: Path, *, keep: Literal[True]) -> dict[str, Any] | None: ...
@overload
def save_checked(ses: gs.Session, on: str | None, thread: int, suffix: str, addr: int,
                 length: int, path: Path, *, keep: Literal[False]) -> dict[str, Any] | bytes: ...
def save_checked(ses: gs.Session, on: str | None, thread: int, suffix: str, addr: int,
                 length: int, path: Path, *, keep: bool) -> dict[str, Any] | bytes | None:
    """`save` `length` bytes at `addr` of `on` into `path`, and check the file: its size, and its
    first bytes against a protocol read of the same range through `thread`. When it holds: None
    for a kept file, and the copy's bytes for one that is not.
    A range past the space, and a file that did not come out whole, RAISE; the control read's
    two failures and a file that differs from it are RETURNED (a raised one that latched the
    session would be re-worded by the tool layer). `keep=False` is the server's own copy of the
    range, which must not exist yet: removed on every exit, and a refusal names no path."""
    # THE CONSOLE'S `save` WALKS FROM THE MASKED START TO THE MASKED END AND NEVER FINISHES WHEN
    # THE END WRAPS BELOW THE START: the stub hangs until the process is killed. A range past the
    # space, judged on the cpu `save` reads (`read.space_bound`), is refused before it, so no
    # range that wraps reaches it while the mask is known.
    read.space_bound(addr, length, on)
    if not keep and path.exists():
        raise st.Invalid("host_failed", "the range copy's file is there before the `save`: this "
                         "server writes and removes its own, and overwrites nothing")
    gone = "the range copy was removed"
    try:
        # The console evaluates both fields as EXPRESSIONS: a bare `d0` is the register, not
        # 0xD0, so the numbers travel with the `0x` prefix that no symbol can start with. They
        # are hex either way (`1000` there is 4096 bytes).
        said = ses.monitor(f"save {path},{addr:#x}{suffix},{length:#x}")
        try:
            whole_file(path, length, said, "save")
        except st.Invalid as e:
            if keep:
                raise
            if not path.exists():
                quoted = said.strip().replace(str(path), "<the range copy>")
                raise st.Invalid(e.code, f"`save` of {prose.counted(length, 'byte')} at {addr:#x} "
                                 f"wrote no range copy; the console said {quoted!r}") from None
            raise st.Invalid(e.code, f"`save` of {prose.counted(length, 'byte')} at {addr:#x} "
                                     f"wrote "
                             f"{prose.counted(path.stat().st_size, 'byte')}; {gone}") from None
        size = path.stat().st_size
        control_len = min(16, length)
        with open(path, "rb") as fh:
            first = fh.read(control_len)
        try:
            control = ses.read(addr, control_len, thread=thread)
        except gs.SessionError as e:
            # The file is on disk by now, so a kept one's refusal still names it, as `write`'s
            # does what landed. The stub's `no` keeps the channel paired, as `write`'s read-back
            # does; any other failure is the channel breaking, and it LATCHES like every other.
            refused = isinstance(e, gs.Refused)
            if not refused:
                ses.latch(str(e))
            where, then = ((f" at {path}", "the file is left there, unchecked") if keep
                           else ("", gone))
            return menvelope.invalid("readback_refused" if refused else "session_broken",
                                     f"{prose.counted(size, 'byte')} came out of `save`{where}, "
                                     "then the protocol read that checks its first "
                                     f"{prose.counted(control_len, 'byte')} failed: {e}; {then}",
                                     **({"path": str(path)} if keep else {}),
                                     addr=st.hex_addr(addr),
                                     length=length, bytes=size)
        if first != control:
            return menvelope.invalid("readback_refused",
                                     f"the file's first {prose.counted(control_len, 'byte')} "
                                     f"{prose.agrees(control_len, 'differs', 'differ')} from a "
                                     "protocol read of the same range; "
                                     + (f"the file is left at {path} for inspection" if keep
                                        else gone))
        return None if keep else path.read_bytes()
    finally:
        if not keep:
            path.unlink(missing_ok=True)


# THE CHANNELS MAME WRITES. `error.log` is what the core and the drivers say through
# `logerror` (`-log`); the process's own stdout and stderr, which the launcher captures into
# `stdout.log`, is where `osd_printf_error` and `-verbose` go. A driver that prints its
# counters through the second would otherwise be unreadable through the server. There is no
# `guest` channel: an arcade board has no port of the program's own.
LOG_CHANNELS = ("emulator", "process", "all")
NO_GUEST = ". There is no `guest` channel: an arcade board has no port of the program's own"
LOG_FILES = {"emulator": "error.log", "process": "stdout.log"}


def log_path(scratch: Path, channel: str) -> Path:
    """Where ONE of the two channels writes. THE ONLY PLACE EITHER FILE NAME IS SPELLED.

    `channel_files` below is the same map read for the READER: it serves `all` too and tags
    each path with its source, which is what a reader wants and what a single consumer does
    not -- so every consumer that already knew which channel it meant spelled the file name
    by hand to get at one path, and the constant sat there with one caller. `all` is not a
    file and raises here, which is the honest answer: there is no one path for both.
    """
    return scratch / LOG_FILES[channel]


def check_channel(channel: str) -> None:
    inputs.one_of("channel", channel, LOG_CHANNELS, tail=NO_GUEST)


def channel_files(scratch: Path, channel: str) -> list[tuple[str, Path]]:
    """The files behind `channel`, each with its source tag, in a fixed order."""
    check_channel(channel)
    names = LOG_FILES if channel == "all" else {channel: LOG_FILES[channel]}
    return [(tag, scratch / name) for tag, name in names.items()]


def tagged(tag: str, line: str, channel: str) -> str:
    """A line as the reply carries it: bare for one channel, `[tag] line` for `all`."""
    return f"[{tag}] {line}" if channel == "all" else line


def label_counts(lines: list[str]) -> dict[str, int]:
    """How many lines carry each LABEL, the line's first word once a source tag is
    stepped over: one glance at who is talking (`RE_DAC`, `RE_IRQ`); the `pattern` still
    selects."""
    counts: dict[str, int] = {}
    for ln in lines:
        words = re.sub(r"^\[(emulator|process)\] ", "", ln).split()
        if words:
            counts[words[0]] = counts.get(words[0], 0) + 1
    return counts


def check_log(pattern: str, channel: str, limit: int = 40, **_: Any) -> re.Pattern[str]:
    """`log`'s machine-independent half, in its own order: how many lines, then the regex, then
    the channel. None of the three needs an emulator to be wrong. The regex is handed back
    compiled, so the tool searches with the one it judged."""
    inputs.count("limit", limit, read.LOG_LIMIT_MAX)
    rx = inputs.regex("pattern", pattern)
    check_channel(channel)
    return rx


def check_log_wait(pattern: str, channel: str, seconds: float = 30.0,
                   **_: Any) -> re.Pattern[str]:
    """`log_wait`'s machine-independent half, in its own order: the bound, then the regex, then the
    channel. The bound comparison is `inputs.seconds_bound`, which every waiting tool shares; the
    regex is handed back compiled, as `check_log` hands back its own."""
    inputs.seconds_bound(seconds)
    rx = inputs.regex("pattern", pattern)
    check_channel(channel)
    return rx


def log(scratch: Path, pattern: str, limit: int, channel: str,
        labels: bool = False) -> dict[str, Any]:
    """The body of the `log` tool: the newest `limit` lines of `channel` matching `pattern`,
    each file read whole (the log is the emulator's, and text mode folds a CRLF log), and
    for `all` the files one after the other with every line tagged."""
    rx = check_log(pattern, channel, limit)
    files = channel_files(scratch, channel)
    present = [(tag, path) for tag, path in files if path.exists()]
    if not present:
        names = ", ".join(path.name for _tag, path in files)
        return menvelope.invalid("no_channel", f"no {names} at {scratch}: MAME has written nothing "
                                 "to it yet")
    hits: list[str] = []
    counts: dict[str, int] = {}
    for tag, path in present:
        # Decoded with replacement on purpose: a driver may `logerror` a raw byte out of ROM,
        # and one such byte must not turn the whole log into an exception. `utf-8-sig`, because
        # MAME opens `error.log` with a byte-order mark, which is not the first line's.
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            mine = [tagged(tag, line.rstrip("\n"), channel) for line in fh
                    if rx.search(line.rstrip("\n"))]
        counts[tag] = len(mine)
        hits.extend(mine)
    returned = hits[-limit:]
    reply: dict[str, Any] = {
        "pattern": pattern,
        "channel": channel,
        "lines_total": len(hits),
        "truncated": len(returned) < len(hits),
        "lines": returned,
    }
    if channel == "all":
        reply["counts"] = counts
    if labels:
        reply["labels"] = label_counts(returned)
    return menvelope.envelope(reply)


def file_mark(log: Path) -> int:
    """How many bytes `log` holds right now: the mark a caller takes before it acts, so what it
    reads back is only what its own action wrote; 0 for a file not written yet."""
    return log.stat().st_size if log.exists() else 0


def log_mark(scratch: Path, channel: str = "emulator") -> int:
    """`file_mark` of `channel`'s file in the scratch, `error.log` by default."""
    return file_mark(log_path(scratch, channel))


def errorlog_since(scratch: Path, mark: int) -> tuple[list[str], int]:
    """The WHOLE lines `error.log` gained since byte `mark`, and the next mark
    (`lines_since`)."""
    return lines_since(log_path(scratch, "emulator"), mark)


# The whole lines a log gained since a byte mark, the core's reader: MAME's `error.log` (what the
# driver logged) and its `debug.log` (what the debugger console printed, which is where a
# watchpoint stop names its writer) are read this way.
lines_since = core_wait.lines_since


def check_snapshot(dest: str = "", **_: Any) -> Path | None:
    """`snapshot`'s machine-independent half, handing back the `Path` it built. An EMPTY `dest` is
    not a mistake here: the file lands in the scratch under a name this module chooses."""
    return inputs.optional_dest(dest)


# WHY, for the reader of this code (the client gets the docstring above the code):
#
# THE ONE READER THAT ANSWERS WHILE THE MACHINE RUNS: what the log ALREADY holds is
# answered first (a line that went past before the
# call is still found, marked `already`), and only then does it wait. A bound that expires is
# `verdict: TIMEOUT` and says what it examined -- how many lines arrived during the wait, how
# many the log holds -- so "nothing matched" and "there was nothing to match against" never read the
# same. A STOPPED machine logs nothing, so a wait on one is refused at once, naming the stop,
# and a stop that lands DURING the wait ends it the same way after one last read of the log.
# Over `all`, each file keeps its own mark and the lines are tagged; the first match in
# file order wins the poll.
def log_wait(ses: gs.Session, scratch: Path, alive: Callable[[], bool],
             on_stop: Callable[[], None], pattern: str, seconds: float, channel: str,
             progress: mprogress.Progress = mprogress.no_progress) -> dict[str, Any]:
    """The body of the `log_wait` tool, on the core's wait (`scry_core.log_wait`). `on_stop`
    records a stop the wait found (the running module's survey, handed in because that module
    imports this one), so the refusal names the stop the machine is IN and the reply carries
    `stopped_on_its_own`."""
    rx = check_log_wait(pattern, channel, seconds)
    files = channel_files(scratch, channel)
    marks = {tag: 0 for tag, _ in files}
    recorded = False
    parked = not ses.running

    def fresh() -> list[str]:
        """What every file of the channel gained since its mark, tagged, marks moved."""
        out: list[str] = []
        for tag, path in files:
            mine, marks[tag] = lines_since(path, marks[tag])
            out.extend(tagged(tag, ln, channel) for ln in mine)
        return out

    def stopped() -> bool:
        # Asked passively (no console round trip); a stop the poll consumed is recorded once.
        nonlocal recorded
        if ses.running and not ses.poll_stop(0.0):
            return False
        if not recorded:
            on_stop()
            recorded = True
        return True

    got = core_wait.wait(rx, fresh, seconds=seconds, stopped=stopped, alive=alive,
                         progress=progress, label=f"log_wait {channel} /{pattern}/")
    if isinstance(got, core_wait.Found):
        return menvelope.envelope({"verdict": contract.TARGET, "pattern": pattern,
                                   "channel": channel,
                                   **got.fields(), "waited_s": st.spent_s(got.waited_s)})
    if got.how == "STOPPED":
        reason = ("the machine is STOPPED at the debugger" if parked else
                  "the machine STOPPED as the bound expired" if got.at_bound else
                  "the machine STOPPED during the wait")
        return menvelope.invalid("wait_stopped",
                                 f"{reason}: a stopped machine logs nothing, so the wait for "
                                 f"/{pattern}/ cannot end. "
                                 f"{prose.counted(got.arrived_during, 'line')} arrived during "
                                 f"{got.waited_s} s of it and none matched: `resume` lets it "
                                 "run, then `log_wait` again",
                                 pattern=pattern, last_stop=STATE.as_of())
    if got.how == "GONE":
        ses.latch("the emulator exited during a wait")
        return menvelope.invalid("session_broken", core_wait.gone_message(pattern, got, seconds),
                                 pattern=pattern)
    # THE BOUND RAN OUT AND THE WAIT ANSWERED: a verdict, not a refusal (the machine is still
    # running, and the caller decides whether to wait longer).
    return menvelope.envelope({
        "verdict": contract.TIMEOUT, "pattern": pattern, "channel": channel,
        "arrived_during": got.arrived_during, "lines_examined": got.lines_examined,
        "waited_s": st.spent_s(got.waited_s),
        "note": core_wait.timeout_note(pattern, got, "in the log", "driver")})


# WHY, for the reader of this code (the client gets the docstring above the code):
#
# MEASURED: the console's `snap` treats even an absolute path as RELATIVE to the snapshot
# directory (an absolute one produced `snap/Users/.../shot.png`), which is why the tool snaps under
# a name it controls and MOVES the file to `dest`. And "Saved screen" is what the console says, not
# what is on disk: a zero-byte or half-written PNG is what a full disk leaves, hence the trailer
# check.

def snapshot(ses: gs.Session, scratch: Path, dest: str) -> dict[str, Any]:
    """The body of the `snapshot` tool."""
    dest_path = check_snapshot(dest)
    name = f"snapshot-{STATE.next_number('snapshots')}.png"
    produced = scratch / "snap" / name
    ses.monitor(f"snap {name}")
    if not wait_for(lambda: _complete_png(produced), FILE_WAIT_S, FILE_POLL_S):
        state = (f"{prose.counted(produced.stat().st_size, 'byte')} so far" if produced.exists()
                 else "no file")
        return menvelope.invalid("unexpected_answer",
                                 f"no complete PNG {name} under {scratch / 'snap'} within "
                                 f"{FILE_WAIT_S} s of the console's `snap`: {state}")
    final = produced
    if dest_path is not None:
        shutil.move(str(produced), str(dest_path))
        final = dest_path
    STATE.captures.append(("png", str(final)))
    # THE HASH THE GOLDENS COMPARE, over the bytes handed back: a repo checked every capture
    # against its own `checksums.sha256` by hand, and the server had the bytes all along.
    return menvelope.envelope(judges.file_facts(final))


def _complete_png(path: Path) -> bool:
    """A PNG on disk with both ends in place: what tells a finished snapshot from a partial one."""
    if not path.is_file():
        return False
    with open(path, "rb") as fh:
        head = fh.read(len(PNG_SIGNATURE))
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - 12))
        tail = fh.read()
    return head == PNG_SIGNATURE and PNG_TRAILER in tail


class Wav(NamedTuple):
    """What a finished WAV's header declares: `samples` is sample frames per channel."""
    channels: int
    sample_rate: int
    data_bytes: int
    samples: int


def _wav_fields(path: Path) -> tuple[int, tuple[Any, ...]] | None:
    """The file's size and its 44-byte header unpacked, or None when it has no such header."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(WAV_HEADER_BYTES)
    except OSError:
        return None
    return (size, WAV_HEADER.unpack(head)) if len(head) == WAV_HEADER_BYTES else None


def wav_header(path: Path) -> Wav | None:
    """The header of a FINISHED 16-bit PCM WAV at `path`, or None.

    EVERY FIELD AGAINST THE OTHERS AND AGAINST THE FILE. MAME writes both sizes only when it
    closes the file, from where the file then ends, so a file still open reads 0 in both, and
    one cut after it closed disagrees with its own length."""
    got = _wav_fields(path)
    if got is None:
        return None
    size, (riff, riff_size, wave, fmt, fmt_size, fmt_tag, channels, rate, byte_rate, align,
           bits, data, data_size) = got
    if (riff, wave, fmt, data) != (b"RIFF", b"WAVE", b"fmt ", b"data"):
        return None
    if fmt_size != 16 or fmt_tag != 1 or bits != 16 or channels < 1 or rate <= 0:
        return None
    if align != 2 * channels or byte_rate != rate * align:
        return None
    if riff_size != size - 8 or data_size != size - WAV_HEADER_BYTES or data_size % align:
        return None
    return Wav(channels, rate, data_size, data_size // align)


def wav_without_channel(path: Path) -> bool:
    """A WAV header naming zero channels: what MAME writes for a machine with no speaker, since
    it opens the file with the sum of its speakers' inputs."""
    got = _wav_fields(path)
    if got is None:
        return False
    riff, _, wave, _, _, _, channels, *_ = got[1]
    return (riff, wave, channels) == (b"RIFF", b"WAVE", 0)


def wav_levels(path: Path) -> tuple[int, int]:
    """The lowest and the highest sample of a finished WAV's data, over every channel: equal is
    one constant level, which is silence to the ear whether it is zero or not."""
    lo = hi = None
    with open(path, "rb") as fh:
        fh.seek(WAV_HEADER_BYTES)
        while chunk := fh.read(WAV_CHUNK_BYTES):
            samples = array("h")
            samples.frombytes(chunk[: len(chunk) // 2 * 2])
            if sys.byteorder == "big":
                samples.byteswap()
            if samples:
                lo = min(samples) if lo is None else min(lo, min(samples))
                hi = max(samples) if hi is None else max(hi, max(samples))
    return (lo or 0, hi or 0)


def file_lines(path: Path) -> Iterator[str]:
    """Every line of a tap's rows file as written, none when it is not written yet."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            yield from fh
    except FileNotFoundError:
        return
