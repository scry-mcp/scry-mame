"""The FILE family: memory to a file, a PNG of the screen, the log channels and the wait on them.

Tools that answer with a PATH check the file they claim to have produced, and every `dest` is
judged before any console is touched, so a refused call never leaves a file behind.
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

from scry_core import judges, log_marks, prose
from scry_core import log_wait as core_wait
from scry_core import progress as mprogress
from scry_core import reply_contract as contract
from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable

import gdb_session as gs
import mame_cpus as cpus
import mame_envelope as menvelope
import mame_inputs as inputs
import mame_read as read
import mame_state as st
from mame_state import STATE

# How long a tool waits for a file the emulator writes at its own pace, and how often it looks.
FILE_WAIT_S = 2.0
FILE_POLL_S = 0.02
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_TRAILER = b"IEND\xaeB`\x82"

# The WAV MAME's mixer writes (`util::wav_open`): a 44-byte header, 16-bit PCM, the RIFF and data
# sizes written only when the file is closed. Chunks are an even byte count so no sample splits.
WAV_HEADER_BYTES = 44
WAV_HEADER = struct.Struct("<4sI4s4sIHHIIHH4sI")
WAV_CHUNK_BYTES = 1 << 20


Waited = TypeVar("Waited")


def wait_for(check: Callable[[], Waited], bound_s: float, poll_s: float) -> Waited:
    """`check()` until it answers (not None or False; 0 is an answer) or `bound_s` passes."""
    deadline = time.monotonic() + bound_s
    while True:
        got = check()
        if (got is not None and got is not False) or time.monotonic() >= deadline:
            return got
        time.sleep(poll_s)


def whole_file(path: Path, length: int, said: str, command: str, after: str = "",
               **fields: Any) -> None:
    """Refuse unless the file a console `command` was to write is there and `length` bytes.
    The console's own sentence is no proof: `save` clamps a span and still says it succeeded."""
    if not path.exists():
        raise st.Invalid("unexpected_answer", f"no file at {path} came out of the console's "
                         f"`{command}`; the console said {said.strip()!r}{after}", **fields)
    size = path.stat().st_size
    if size != length:
        raise st.Invalid("readback_refused", f"{prose.counted(size, 'byte')} came out of "
                                             f"`{command}` "
                         f"where {length} were asked; the file is left at {path}{after}", **fields)


def refuse_console_path(path: Path) -> None:
    """Refuse a server-made path the console would cut: the host's failure, not the caller's."""
    if broken := inputs.path_break(str(path)):
        raise st.Invalid("host_failed", f"the scratch path {str(path)!r} holds "
                         f"{broken!r}, which a path handed to the console may not hold")


def unreadable(thing: str, path: str, e: OSError, **fields: Any) -> st.Invalid:
    """The refusal of a caller's file the server cannot read."""
    return st.Invalid("bad_argument", f"cannot read the {thing} {path}: {e.strerror or e}",
                      **fields)


def not_utf8(path: str, e: UnicodeDecodeError, **fields: Any) -> st.Invalid:
    """The refusal of a caller's file that is not UTF-8 text."""
    return st.Invalid("bad_argument", f"{path} is not UTF-8 text: {e}", **fields)


def read_text(name: str, path: str, thing: str, **fields: Any) -> str:
    """A caller's text file, read whole; a fault in it is refused, never raised."""
    file = inputs.input_file(name, path, thing, **fields)
    try:
        return file.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise not_utf8(path, e, **fields) from None
    except OSError as e:
        raise unreadable(thing, path, e, **fields) from None


def check_memdump(length: int, dest: str, ref: str = "", **_: Any) -> Path:
    """`memdump`'s machine-independent half, handing back the `Path` it built. The path is judged
    first because a caller who named a file this server cannot write has to hear about it."""
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
    """The cpu `save` reads, the stub thread its control read uses, and the `:<cpu>` suffix.

    The control must read the same cpu `save` does; without the patched stub's threads it reads
    only its first cpu, so another cpu's file could not be checked."""
    if ses.threads:
        on, thread = cpus.thread_for(ses, cpu)
    else:
        on, thread = cpus.chosen(ses, cpu), 1
        if on is not None and on != (served := cpus.stub_cpu(ses)):
            raise st.Invalid("bad_argument",
                f"`save` reads {on}, and the file is checked against a read of the same range "
                f"through the stub, which without the gdbstub's thread patch reads only "
                f"{served}: `memdump(cpu={served!r})` is the dump it can check")
    return on, thread, (f":{on}" if on and (ses.threads or inputs.cpu_given(cpu)) else "")


@overload
def save_checked(ses: gs.Session, on: str | None, thread: int, suffix: str, addr: int,
                 length: int, path: Path, *, keep: Literal[True]) -> dict[str, Any] | None: ...
@overload
def save_checked(ses: gs.Session, on: str | None, thread: int, suffix: str, addr: int,
                 length: int, path: Path, *, keep: Literal[False]) -> dict[str, Any] | bytes: ...
def save_checked(ses: gs.Session, on: str | None, thread: int, suffix: str, addr: int,
                 length: int, path: Path, *, keep: bool) -> dict[str, Any] | bytes | None:
    """`save` `length` bytes at `addr` of `on` into `path`, and check its size and its first bytes
    against a protocol read through `thread`. Holding: None for a kept file, else the bytes.
    A range past the space and a short file RAISE; the control read's failures and a mismatch are
    RETURNED (a raised one that latched the session would be re-worded by the tool layer).
    `keep=False` is the server's own copy, which must not exist yet: removed on every exit."""
    # `save` never finishes when the masked end wraps below the start: the stub hangs until the
    # process is killed, so a range past the space is refused before it.
    read.space_bound(addr, length, on)
    if not keep and path.exists():
        raise st.Invalid("host_failed", "the range copy's file is there before the `save`: this "
                         "server writes and removes its own, and overwrites nothing")
    gone = "the range copy was removed"
    try:
        # Both fields are expressions: a bare `d0` is the register, so numbers keep the `0x`.
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
            # A stub `no` keeps the channel paired; any other failure is the channel breaking.
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


# `error.log` is what the core and drivers say through `logerror`; the process's stdout and
# stderr (`stdout.log`) is where `osd_printf_error` and `-verbose` go.
LOG_CHANNELS = ("emulator", "process", "all")
NO_GUEST = ". There is no `guest` channel: an arcade board has no port of the program's own"
LOG_FILES = {"emulator": "error.log", "process": "stdout.log"}


def log_path(scratch: Path, channel: str) -> Path:
    """Where one channel writes; the only place either file name is spelled. `all` raises."""
    return scratch / LOG_FILES[channel]


def check_channel(channel: str) -> None:
    vocab.one_of("channel", channel, LOG_CHANNELS, tail=NO_GUEST)


def channel_files(scratch: Path, channel: str) -> list[tuple[str, Path]]:
    """The files behind `channel`, each with its source tag, in a fixed order."""
    check_channel(channel)
    names = LOG_FILES if channel == "all" else {channel: LOG_FILES[channel]}
    return [(tag, scratch / name) for tag, name in names.items()]


def tagged(tag: str, line: str, channel: str) -> str:
    """A line as the reply carries it: bare for one channel, `[tag] line` for `all`."""
    return f"[{tag}] {line}" if channel == "all" else line


def label_counts(lines: list[str]) -> dict[str, int]:
    """How many lines carry each label, the first word once a source tag is stepped over."""
    counts: dict[str, int] = {}
    for ln in lines:
        words = re.sub(r"^\[(emulator|process)\] ", "", ln).split()
        if words:
            counts[words[0]] = counts.get(words[0], 0) + 1
    return counts


def _check_mark(since_mark: int, channel: str) -> None:
    """`since_mark`'s half that needs no log: one position cannot name a place in two files."""
    if since_mark and channel == "all":
        raise st.Invalid("bad_argument",
            f"since_mark is a position in one file, and `all` reads two "
            f"({' and '.join(LOG_FILES.values())}): ask `emulator` or `process`, each with its "
            f"own number from `mark`")
    log_marks.check_position(since_mark, channel)


def check_log(pattern: str, channel: str, limit: int = 40, since_mark: int = 0,
              **_: Any) -> re.Pattern[str]:
    """`log`'s machine-independent half: limit, regex, channel, mark, in that order. The regex
    is handed back compiled."""
    inputs.count("limit", limit, read.LOG_LIMIT_MAX)
    rx = inputs.regex("pattern", pattern)
    check_channel(channel)
    _check_mark(since_mark, channel)
    return rx


def check_log_wait(pattern: str, channel: str, seconds: float = 30.0, since_mark: int = 0,
                   **_: Any) -> re.Pattern[str]:
    """`log_wait`'s machine-independent half: bound, regex, channel, mark, in that order. The
    regex is handed back compiled."""
    vocab.check_wait(seconds)
    rx = inputs.regex("pattern", pattern)
    check_channel(channel)
    _check_mark(since_mark, channel)
    return rx


def channel_marks(scratch: Path) -> dict[str, int]:
    """Where each channel's file ends now, one number per channel (`all` has none of its own)."""
    return {tag: file_mark(scratch / name) for tag, name in LOG_FILES.items()}


def _from_mark(path: Path, since_mark: int, channel: str) -> int:
    """`since_mark` held to `path` as it stands (`log_marks.check_since_mark`)."""
    log_marks.check_since_mark(since_mark, file_mark(path), channel)
    return since_mark


def log(scratch: Path, pattern: str, limit: int, channel: str,
        labels: bool = False, since_mark: int = 0) -> dict[str, Any]:
    """The body of the `log` tool: the newest `limit` matching lines of `channel`."""
    rx = check_log(pattern, channel, limit, since_mark)
    files = channel_files(scratch, channel)
    present = [(tag, path) for tag, path in files if path.exists()]
    if not present:
        names = ", ".join(path.name for _tag, path in files)
        return menvelope.invalid("no_channel", f"no {names} at {scratch}: MAME has written nothing "
                                 "to it yet")
    hits: list[str] = []
    counts: dict[str, int] = {}
    for tag, path in present:
        # A driver may `logerror` a raw ROM byte, so decode with replacement; MAME opens
        # `error.log` with a byte-order mark, hence `utf-8-sig`.
        if since_mark:
            after, _ = lines_since(path, _from_mark(path, since_mark, channel))
            mine = [tagged(tag, line, channel) for line in after if rx.search(line)]
        else:
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
    """How many bytes `log` holds now (0 if unwritten): the mark taken before acting."""
    return log.stat().st_size if log.exists() else 0


def log_mark(scratch: Path, channel: str = "emulator") -> int:
    """`file_mark` of `channel`'s file in the scratch."""
    return file_mark(log_path(scratch, channel))


def errorlog_since(scratch: Path, mark: int) -> tuple[list[str], int]:
    """The whole lines `error.log` gained since byte `mark`, and the next mark."""
    return lines_since(log_path(scratch, "emulator"), mark)


lines_since = core_wait.lines_since


def check_snapshot(dest: str = "", **_: Any) -> Path | None:
    """`snapshot`'s machine-independent half; an empty `dest` lands in the scratch."""
    return inputs.optional_dest(dest)


# What the log already holds is answered first (marked `already`), then it waits. A timeout says
# what it examined, so "nothing matched" and "nothing to match against" differ. A stopped machine
# logs nothing, so waiting on one is refused at once.
def log_wait(ses: gs.Session, scratch: Path, alive: Callable[[], bool],
             on_stop: Callable[[], None], pattern: str, seconds: float, channel: str,
             progress: mprogress.Progress = mprogress.no_progress,
             since_mark: int = 0) -> dict[str, Any]:
    """The body of the `log_wait` tool, on the core's wait. `on_stop` records a stop the wait
    found (handed in because the running module imports this one)."""
    rx = check_log_wait(pattern, channel, seconds, since_mark)
    files = channel_files(scratch, channel)
    marks = {tag: _from_mark(path, since_mark, channel) for tag, path in files}
    recorded = False
    parked = not ses.running

    def fresh() -> list[str]:
        """What every file of the channel gained since its mark, tagged."""
        out: list[str] = []
        for tag, path in files:
            mine, marks[tag] = lines_since(path, marks[tag])
            out.extend(tagged(tag, ln, channel) for ln in mine)
        return out

    def stopped() -> bool:
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
    if got.ending == "STOPPED":
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
    if got.ending == "GONE":
        ses.latch("the emulator exited during a wait")
        return menvelope.invalid("session_broken", core_wait.gone_message(pattern, got, seconds),
                                 pattern=pattern)
    # The bound ran out: a verdict, not a refusal, as the machine is still running.
    return menvelope.envelope({
        "verdict": contract.TIMEOUT, "pattern": pattern, "channel": channel,
        "arrived_during": got.arrived_during, "lines_examined": got.lines_examined,
        "waited_s": st.spent_s(got.waited_s),
        "note": core_wait.timeout_note(pattern, got, "in the log", "driver")})


# The console's `snap` treats even an absolute path as relative to the snapshot directory, so the
# tool snaps under its own name and moves the file. "Saved screen" is not proof either: a full
# disk leaves a half-written PNG, hence the trailer check.

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
    return menvelope.envelope(judges.file_facts(final))


def _complete_png(path: Path) -> bool:
    """A PNG with both ends in place: a finished snapshot, not a partial one."""
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
    """A finished WAV's header; `samples` is frames per channel."""
    channels: int
    sample_rate: int
    data_bytes: int
    samples: int


def _wav_fields(path: Path) -> tuple[int, tuple[Any, ...]] | None:
    """The file's size and its unpacked header, or None."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(WAV_HEADER_BYTES)
    except OSError:
        return None
    return (size, WAV_HEADER.unpack(head)) if len(head) == WAV_HEADER_BYTES else None


def wav_header(path: Path) -> Wav | None:
    """The header of a finished 16-bit PCM WAV, or None: a file still open reads 0 in both sizes."""
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
    """A WAV header naming zero channels: what MAME writes for a machine with no speaker."""
    got = _wav_fields(path)
    if got is None:
        return False
    riff, _, wave, _, _, _, channels, *_ = got[1]
    return (riff, wave, channels) == (b"RIFF", b"WAVE", 0)


def wav_levels(path: Path) -> tuple[int, int]:
    """The lowest and highest sample over every channel: equal is one constant level, silence."""
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
    """Every line of a tap's rows file, none when not written yet."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            yield from fh
    except FileNotFoundError:
        return
