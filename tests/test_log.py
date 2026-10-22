"""`log` and `log_wait`: ONE pair of tools over every channel the emulator writes.

MAME writes two things: `error.log` (`-log`: what the core and the drivers say through
`logerror`) and the process's own stdout and stderr (`osd_printf_error`, `-verbose`), which
the launcher already captures into `stdout.log`. A driver that prints its counters through
`osd_printf_error` is unreadable through the server, and a session ends up opening the file
by hand. So the reader takes a `channel`: `emulator` (error.log), `process` (stdout.log) or
`all` (both, each line tagged with its source). The stop survey's `errorlog` block is
unchanged: it is a field, not a tool.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from scry_core import vocabulary as vocab

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import refused  # noqa: E402
from test_server import _console, _ConsoleSession, _running  # noqa: E402

import mame_files as files  # noqa: E402
import mame_read as read  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


class _DeadProcess:
    """A process that has exited: what `log_wait`'s liveness check reads once MAME is gone."""

    pid = 4242

    def poll(self) -> int | None:
        return 1


def test_the_old_tool_names_are_gone_and_the_pair_is_registered() -> None:
    names = {t.name for t in s.mcp._tool_manager.list_tools()}
    assert {"log", "log_wait"} <= names
    assert not {"errorlog", "errorlog_wait"} & names


def test_log_reads_the_channel_asked_for_and_tags_lines_when_asked_for_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    scratch = _console(monkeypatch, tmp_path, _ConsoleSession())
    (scratch / "error.log").write_text("[:] blit start 1\nnoise\n[:] blit start 2\n")
    (scratch / "stdout.log").write_text("RE_DAC lost=21\nRE_DAC lost=7\n")
    out = s.log(pattern="blit", channel="emulator")
    assert out["status"] == "ok" and out["channel"] == "emulator"
    assert out["lines"] == ["[:] blit start 1", "[:] blit start 2"] and out["lines_total"] == 2
    assert out["summary"] == "log emulator /blit/: 2 of 2 lines"
    out = s.log(pattern=".", channel="emulator")
    assert out["lines_total"] == 3 and out["lines"][1] == "noise", "one channel reads ONE file"
    out = s.log(pattern="lost", channel="process", limit=1)
    assert out["lines"] == ["RE_DAC lost=7"] and out["lines_total"] == 2 and out["truncated"]
    out = s.log(pattern=".", channel="all")
    assert out["lines"] == ["[emulator] [:] blit start 1", "[emulator] noise",
                            "[emulator] [:] blit start 2", "[process] RE_DAC lost=21",
                            "[process] RE_DAC lost=7"]
    assert out["counts"] == {"emulator": 3, "process": 2}
    refused("channel", s.log(pattern=".", channel="guest"))
    refused("limit", s.log(pattern=".", channel="emulator", limit=0))
    refused("does not compile", s.log(pattern="(unclosed", channel="emulator"))


def test_log_labels_count_the_first_word_of_each_matching_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    scratch = _console(monkeypatch, tmp_path, _ConsoleSession())
    (scratch / "stdout.log").write_text("RE_DAC lost=21\nRE_IRQ n=49\nRE_DAC lost=7\n")
    out = s.log(pattern=".", channel="process", labels=True)
    assert out["labels"] == {"RE_DAC": 2, "RE_IRQ": 1}
    assert "labels" not in s.log(pattern=".", channel="process")


def test_log_is_invalid_when_the_channel_has_no_file_yet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _console(monkeypatch, tmp_path, _ConsoleSession())
    out = s.log(pattern=".", channel="process")
    assert out["status"] == "INVALID" and out["code"] == "no_channel"
    assert "stdout.log" in out["message"]
    out = s.log(pattern=".", channel="all")
    assert out["status"] == "INVALID" and out["code"] == "no_channel"


def test_log_wait_takes_the_channel_and_finds_a_process_line_that_arrives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    (tmp_path / "stdout.log").write_text("boot\n")
    out = s.log_wait(pattern="boot", channel="process", seconds=1.0)
    assert out["already"] is True and out["line"] == "boot" and out["channel"] == "process"
    assert out["summary"] == "log_wait process /boot/: matched already there"
    assert out["pattern"] == "boot" and out["lines_total"] == 1 and out["lines_before"] == 0
    assert out["waited_s"] == 0.0, "a line already there cost no wait"
    out = s.log_wait(pattern="boot", channel="all", seconds=1.0)
    assert out["already"] is True and out["line"] == "[process] boot", "tagged over `all`"
    # A STOPPED machine logs nothing: refused at once, naming the pattern.
    out = s.log_wait(pattern="zzz", channel="process", seconds=1.0)
    assert out["status"] == "INVALID" and out["code"] == "wait_stopped"
    assert out["message"].endswith(": `resume` lets it run, then `log_wait` again"), out
    assert out["pattern"] == "zzz", out
    s.resume()

    def later() -> None:
        time.sleep(0.15)
        with open(tmp_path / "error.log", "a") as fh:
            fh.write("scene 3 drawn\n")

    t = threading.Thread(target=later)
    t.start()
    out = s.log_wait(pattern="scene", channel="all", seconds=2.0)
    t.join()
    assert out["status"] == "ok" and out["line"] == "[emulator] scene 3 drawn"
    assert out["already"] is False and out["waited_s"] > 0
    assert ses.running
    # A BOUND THAT EXPIRES says what it examined, field by field.
    out = s.log_wait(pattern="zzz", channel="all", seconds=0.3)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert out["pattern"] == "zzz" and out["arrived_during"] == 0
    assert out["lines_examined"] == 2 and out["waited_s"] >= 0.3, out
    # THE EMULATOR GONE mid-wait: `session_broken`, still naming the pattern.
    monkeypatch.setattr(mstate.STATE, "proc", _DeadProcess())
    out = s.log_wait(pattern="zzz", channel="all", seconds=0.5)
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert out["pattern"] == "zzz", out
    refused("channel", s.log_wait(pattern=".", channel="guest", seconds=1.0))
    # THE BOUND'S OWN EDGES: the ceiling is a bound, one past it is not.
    vocab.check_wait(vocab.WAIT_MAX_S)          # the ceiling itself is a bound: no refusal
    refused("not a bound",
            s.log_wait(pattern=".", channel="process", seconds=vocab.WAIT_MAX_S + 0.5))
    monkeypatch.setattr(read, "LOG_LIMIT_MAX", read.LOG_LIMIT_MAX)


# CAPTURED, never authored: the first bytes MAME writes to `error.log` (PROVENANCE.txt).
_LOG_START = (Path(__file__).parent / "fixtures" / "console" / "errorlog.start.txt").read_bytes()


def test_the_mark_mame_writes_at_the_start_of_error_log_is_not_part_of_its_first_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """MAME opens `error.log` with a UTF-8 byte-order mark before `Soft reset`. The mark is
    the file's and not the first line's, so no reader hands it back (an anchored pattern
    finds the line, `labels` counts its own first word); a mark past the file's start reads
    none, since the same bytes there are a line's own."""
    assert _LOG_START.startswith(b"\xef\xbb\xbf"), "the capture carries the mark"
    scratch = _console(monkeypatch, tmp_path, _ConsoleSession())
    (scratch / "error.log").write_bytes(_LOG_START + b"[:] blit start 1\n")
    # AND TWO SHAPES A LOG CAN HOLD: a raw byte out of ROM (decoded with replacement, never
    # an exception) and a CRLF line whose trailing spaces and letters are its own.
    (scratch / "error.log").open("ab").write(b"\xffraw\nxX  \r\nendX\r\n")
    assert s.log(pattern="raw", channel="emulator")["lines"] == ["\ufffdraw"]
    assert s.log(pattern="xX  $", channel="emulator")["lines"] == ["xX  "]
    assert s.log(pattern="X$", channel="emulator")["lines"] == ["endX"]
    assert files.lines_since(scratch / "error.log", 0)[0][-3:] == ["\ufffdraw", "xX  ", "endX"]
    (scratch / "error.log").write_bytes(_LOG_START + b"[:] blit start 1\n")
    out = s.log(pattern="^Soft reset$", channel="emulator", labels=True)
    assert out["lines"] == ["Soft reset"] and out["labels"] == {"Soft": 1}, out
    lines, mark = files.lines_since(scratch / "error.log", 0)
    assert lines == ["Soft reset", "[:] blit start 1"], lines
    assert mark == len(_LOG_START) + len(b"[:] blit start 1\n"), "the mark counts the bytes"
    assert files.lines_since(scratch / "error.log", len(_LOG_START))[0] == ["[:] blit start 1"]
    # THE CONTROL: the same bytes past the start are a line's own and stay.
    (scratch / "error.log").write_bytes(b"x\n" + _LOG_START)
    assert files.lines_since(scratch / "error.log", 0)[0] == ["x", "\ufeffSoft reset"]
    assert files.lines_since(scratch / "error.log", 2)[0] == ["\ufeffSoft reset"], (
        "a mark that lands on those bytes mid-file reads them as the line's")


def test_label_counts_skip_an_empty_line() -> None:
    import mame_files as files
    assert files.label_counts(["", "[process] RE_DAC x", "   "]) == {"RE_DAC": 1}


def test_log_since_mark_reads_only_what_was_written_after_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    scratch = _console(monkeypatch, tmp_path, _ConsoleSession())
    log = scratch / "error.log"
    log.write_text("PERF 1\nPERF 2\n")
    mark = log.stat().st_size
    with open(log, "a") as fh:
        fh.write("PERF 2\n")           # the replayed timeline writes the same line again
    out = s.log(pattern="PERF", channel="emulator", since_mark=mark)
    assert out["status"] == "ok" and out["lines"] == ["PERF 2"] and out["lines_total"] == 1, out
    assert s.log(pattern="PERF", channel="emulator")["lines_total"] == 3, "0 reads the whole log"
    assert s.log(pattern="PERF", channel="emulator", since_mark=log.stat().st_size)["lines"] == []


def test_a_mark_that_names_no_position_of_the_channel_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    scratch = _console(monkeypatch, tmp_path, _ConsoleSession())
    (scratch / "error.log").write_bytes(b"a\n")       # bytes: a mark is a byte position
    (scratch / "stdout.log").write_bytes(b"b\n")
    refused("0 or more", s.log(pattern=".", channel="emulator", since_mark=-1))
    refused(r"past where the emulator log ends now \(2 bytes\)",
            s.log(pattern=".", channel="emulator", since_mark=3))
    refused("`all` reads two", s.log(pattern=".", channel="all", since_mark=1))
    assert s.log(pattern=".", channel="all", since_mark=0)["lines_total"] == 2
    refused("`all` reads two", s.log_wait(pattern=".", channel="all", since_mark=1, seconds=1.0))
    refused("0 or more", s.log_wait(pattern=".", channel="process", since_mark=-1, seconds=1.0))


def test_log_wait_since_mark_takes_a_line_before_the_mark_for_history_not_an_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    s.resume()
    log = tmp_path / "stdout.log"
    log.write_text("scene 3\n")
    mark = log.stat().st_size
    out = s.log_wait(pattern="scene 3", channel="process", seconds=0.3, since_mark=mark)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    with open(log, "a") as fh:
        fh.write("scene 3\n")
    out = s.log_wait(pattern="scene 3", channel="process", seconds=1.0, since_mark=mark)
    assert out["verdict"] == "TARGET" and out["already"] is True and out["lines_before"] == 0, out
