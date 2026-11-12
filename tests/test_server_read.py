"""The server's guarantees: reading and writing memory, the console and the files."""

from __future__ import annotations

import hashlib
import inspect
import time
from pathlib import Path
from typing import Any

import pytest
from scry_core import prose
from server_support import (  # noqa: E402
    _PNG,
    FIXTURES,
    MAME_ASSIGNMENTS,
    _boot_args,
    _console,
    _ConsoleSession,
    _DroppingWire,
    _FakeSession,
    _first_window,
    _install,
    _listing_pair,
    _masked,
    _refusal_text,
    _RegisterSession,
    _running,
    _snapping,
    _stub_boot,
    _StubProcess,
)
from session_doubles import (  # noqa: E402
    captured,
    refused,
    use_table,  # noqa: E402
)

from scry_mame import (
    conditions,  # noqa: E402
    files,  # noqa: E402
    inputs,
    launch,
    read,  # noqa: E402
    running,  # noqa: E402
)
from scry_mame import console as mconsole  # noqa: E402
from scry_mame import envelope as menvelope  # noqa: E402
from scry_mame import gdb_session as g  # noqa: E402
from scry_mame import mcp as mame_mcp  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


@pytest.mark.parametrize(
    "command",
    # EVERY SPELLING MAME'S CONSOLE RESOLVES (src/emu/debug/debugcmd.cpp): a command, its alias,
    # and a unique prefix of it (`softr`), which the console runs as the command itself.
    ["fill 0x1000,1,0", "filld 0,1,0", "softreset", "softr", "hardreset", "g", "step", "n",
     "over", "o", "load x,0,10", "loadr x,0,0,:gfx", "stateload s", "sl s", "gtime 100",
     "gvblank", "gint 3", "rewind", "rw", "mount cart x", "suspend 1",
     "d0=1234", "pc = 0x400", "w@0x2031fc=1", "d0++", "do d0=1",
     # An assignment AFTER a comma is executed too: `print` takes a list of expressions,
     # and a breakpoint's action (`bpset a,{cond},{action}`) runs its expression on each hit.
     "print pc,d0=1", "bpset 0x400,1,{d0=1}",
     # An ACTION in braces runs a console command list at every hit, `=` or not.
     "bpset 0x400,1,{fill 0x100,1,1}", "wpset 0,4,w,1,{g}"],
)
def test_mutating_commands_are_recognised(command: str) -> None:
    """Without this, a session touched through the console kept declaring itself intact."""
    assert mconsole.mutates(command), f"{command!r} writes and is not marked"


@pytest.mark.parametrize(
    "command", ["dasm x,0x400,20", "find 0,0xffff,1234", "print pc", "help", "history", "symlist",
                # The two LISTS write nothing, and `==` is a comparison, not an assignment.
                "bplist", "wplist", "print d0==1", "print d0!=1",
                # Arming, clearing or disabling a breakpoint or a watchpoint is the debugger's
                # own bookkeeping: nothing in the machine changes.
                "bpset 0x400", "bpset 0x400,w@0x2031fc==0x25", "wpset 0,4,w", "bpclear 1",
                "bpdisable 2", "wpclear"]
)
def test_read_only_commands_are_not_marked(command: str) -> None:
    """The other side of the contract: over-marking turns the warning into noise."""
    assert not mconsole.mutates(command), f"{command!r} only reads and is marked"


@pytest.mark.parametrize(
    ("text", "assigns"),
    [("d0=1", True), ("w@0x2031fc=1", True), ("d0++", True), ("d0--", True), ("d0+=1", True),
     ("(d0=1)==0", True),
     ("d0==1", False), ("d0!=1", False), ("d0<=1", False), ("d0>=1", False), ("d0<1", False),
     ("d0>1", False), ("d0<<1", False), ("d0>>1", False), ("w@0x2031fc==0x25", False),
     ("pc==0x400", False)],
)
def test_a_condition_and_a_typed_line_agree_on_what_assigns(text: str, assigns: bool) -> None:
    """ONE DECISION, TWO CONSUMERS."""
    try:
        conditions.check_condition(text)
        refused_as_condition = False
    except mstate.Invalid:
        refused_as_condition = True
    marked_as_line = mconsole.mutates(text)
    assert (refused_as_condition, marked_as_line) == (assigns, assigns), text


@pytest.mark.parametrize("operator", MAME_ASSIGNMENTS)
def test_every_assignment_mame_parses_assigns_for_both_consumers(operator: str) -> None:
    """A write to a register through each operator is refused as a condition and marked on a
    `debug` line; the same operator on a debugger temp is still no write to the guest."""
    text = "d0" + operator + ("" if operator in ("++", "--") else "1")
    with pytest.raises(mstate.Invalid):
        conditions.check_condition(text)
    assert mconsole.mutates(text) is True, text
    assert mconsole.mutates(text.replace("d0", "temp0")) is False, text


@pytest.mark.parametrize(
    ("command", "mutates"),
    [("temp9=0", False), ("temp9=0;temp8=0", False), ("++temp9", False), ("temp9++", False),
     ("bpset 201060:subcpu,(++temp9)==0", False),
     ("d0=1234", True), ("temp0=w@100=1", True), ("temp0=d0=1", True),
     ("bpset 0x400,1,{temp0=1}", True),
     ("temp9=0;fill 100,1,1", True), ("print 1;fill 100,1,1", True), ("temp0=1;g", True),
     ('print "a;fill 1,1,1"', False), ("TEMP1=0", False), ("w@ temp1=3", True)],
    ids=lambda v: str(v),
)
def test_a_write_to_a_debugger_temp_alone_is_not_a_write(command: str, mutates: bool) -> None:
    """`lexer.without_temp_writes` says why a temp alone is not a write."""
    assert mconsole.mutates(command) is mutates, command


def test_a_condition_still_refuses_a_temp_the_debug_line_does_not_mark() -> None:
    """THE ONE PLACE THE TWO CONSUMERS DIFFER, on purpose."""
    with pytest.raises(mstate.Invalid):
        conditions.check_condition("(++temp3)==0")
    assert mconsole.mutates("(++temp3)==0") is False


def test_a_softreset_whose_step_fails_is_counted_as_the_write_it_may_have_been() -> None:
    """The console's `softreset` is a timer the next step fires."""
    ses = g.Session()
    ses.monitor = lambda command, timeout=None: ""  # type: ignore[method-assign]

    def step() -> str:
        raise g.Timeout("no answer within 0.2 s")

    ses.step = step  # type: ignore[method-assign]
    with pytest.raises(g.Timeout):
        ses.reset()
    assert ses.writes == 1


def test_a_writing_console_line_left_unanswered_counts_as_a_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "console_writes", 0)

    def owed(command: str, timeout: float = 10.0) -> str:
        raise g.Timeout(f"`{command}` got no answer")

    monkeypatch.setattr(ses, "monitor", owed)
    out = s.debug(command="fill 400,10,0")
    assert out["status"] == "INVALID" and out["session"]["altered"] is True, out


def test_a_write_that_goes_nowhere_says_so(monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path) -> None:
    """THE REGRESSION THIS EXISTS FOR."""
    fake = _FakeSession(bytes.fromhex("7ffff3ff"), writable=False)
    _install(monkeypatch, fake, tmp_path)
    monkeypatch.setattr(mstate.STATE, "machine_map", {})
    out = s.write("0x20000", "aa55aa55")
    assert out["verified"] is False
    assert out["readback"] == "7ffff3ff"
    assert out["bytes_written"] == 4, "it still reports what was attempted"
    assert fake.written == (0x20000, bytes.fromhex("aa55aa55"))
    # WHY it went nowhere, and with no inventory cached, no region is guessed at.
    assert out["target"] == "rom" and "region" not in out, out
    assert "the address map was not gathered" in out["note"], out


def test_a_readback_that_fails_after_the_write_refuses_as_session_broken(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A read-back whose connection goes after the write is `session_broken` naming what was
    written and where, with no `readback` and no `verified`."""
    fake = _FakeSession(bytes.fromhex("aa55aa55"))
    _install(monkeypatch, fake, tmp_path)

    def broken(addr: int, n: int, *, thread: int) -> bytes:
        raise g.ConnectionFailed("the stub closed the connection")

    monkeypatch.setattr(fake, "read", broken)
    out = s.write("0x1000", "aa55aa55")
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert out["addr"] == "0x00001000" and out["bytes_written"] == 4, out
    assert "readback" not in out and "verified" not in out, out
    assert "the session broke reading the write back" in out["message"], out
    assert "closed the connection" in out["message"], out
    assert fake.written == (0x1000, bytes.fromhex("aa55aa55"))


def test_a_debug_command_past_the_packet_size_is_a_bad_argument_at_once(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A command the stub would drop is refused as the ARGUMENT it is, naming its length and
    the limit, at once and with nothing on the wire."""
    ses = g.Session(timeout=0.2)
    wire = _DroppingWire()
    ses._sock = wire  # type: ignore[assignment]
    ses.packet_size = 0x40
    limit = (0x40 - len("qRcmd,")) // 2
    _install(monkeypatch, ses, tmp_path)
    started = time.monotonic()
    out = s.debug("print " + "1" * limit)
    assert time.monotonic() - started < 1.0, "refused at once, not at a bound"
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert (out["command_chars"], out["limit_chars"]) == (limit + 6, limit), out
    assert f"{limit + 6} characters" in out["message"] and f"{limit}" in out["message"], out
    assert wire.sent == [] and ses.writes == 0, wire.sent


def test_a_read_above_the_ceiling_is_refused_and_names_memdump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A frame is 64000 bytes of VRAM."""
    _console(monkeypatch, tmp_path, _ConsoleSession(bytes(read.READ_MAX + 1)))
    refused("memdump",
    s.read_memory("0x0", length=read.READ_MAX + 1))
    refused("memdump",
    s.read_memory("0x0", length=0))
    whole = s.read_memory("0x0", length=read.READ_MAX)
    assert len(whole["hex"]) == 2 * read.READ_MAX, "the ceiling itself is fine"


def test_a_read_summary_carries_its_bytes_whole_to_a_ceiling_and_counts_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Under `perform(summaries=True)` the summary line is all a read step keeps."""
    image = bytes(range(256)) * 4
    _console(monkeypatch, tmp_path, _ConsoleSession(image))
    short = s.read_memory("0x2", length=2)
    assert short["summary"] == "read_memory 0x2: 2 bytes at 0x00000002: 0203", short["summary"]
    cap = prose.HEX_BYTES_SHOWN
    long = s.read_memory("0x0", length=cap + 3)
    assert long["summary"].endswith(image[:cap].hex() + "... (3 more bytes in `hex`)"), (
        long["summary"])
    assert long["hex"] == image[:cap + 3].hex(), "the reply itself is never cut"


def test_memdump_refuses_a_bad_dest_before_touching_the_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A refusal that arrives AFTER the console wrote the file leaves a file the caller did
    not ask for. Relative, or already there, is judged first, and the fake records zero
    commands."""
    ses = _ConsoleSession(bytes(64))
    _console(monkeypatch, tmp_path, ses)
    refused("must be an absolute path",
    s.memdump("0", length=16, dest="dump.bin"))
    existing = tmp_path / "there.bin"
    existing.write_bytes(b"x")
    refused("exists",
    s.memdump("0", length=16, dest=str(existing)))
    refused("length",
    s.memdump("0", length=0, dest=str(tmp_path / "fresh.bin")))
    refused("is not a directory",
    s.memdump("0", length=16, dest=str(tmp_path / "missing" / "dump.bin")))
    (tmp_path / "a,b").mkdir()
    refused("comma",
    s.memdump("0", length=16, dest=str(tmp_path / "a,b" / "x.bin")))
    (tmp_path / "folder.bin").mkdir()
    refused("exists",
    s.memdump("0", length=16, dest=str(tmp_path / "folder.bin")))
    assert ses.commands == [], "the console was touched on a refused input"


def test_a_semicolon_in_a_dest_is_refused_before_the_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The console ends a command at a `;`."""
    (tmp_path / "a;b").mkdir()
    split = str(tmp_path / "a;b" / "x.bin")
    message = _refusal_text(inputs.fresh_dest, "dest", split)
    assert "semicolon" in message and "';'" in message, message
    # Anywhere in the value, inside brackets too, and the console's brackets themselves: an
    # unbalanced one stops the whole line before it runs, as late as the `;` did.
    for name, char in [(";a", ";"), ("a;", ";"), ("a(;)b", "("), ("a(b", "("), ("a)b", ")"),
                       ("a[b", "["), ("a]b", "]"), ("a{b", "{"), ("a}b", "}")]:
        (tmp_path / name).mkdir()
        said = _refusal_text(inputs.fresh_dest, "dest", str(tmp_path / name / "x.bin"))
        assert f"{char!r}" in said, (name, said)
    ses = _ConsoleSession(bytes(64))
    _console(monkeypatch, tmp_path, ses)
    refused("semicolon",
    s.memdump("0", length=16, dest=split))
    refused("semicolon",
    s.snapshot(dest=str(tmp_path / "a;b" / "x.png")))
    assert ses.commands == [], "the console was touched on a refused input"


def test_memdump_refuses_a_range_that_wraps_the_program_space(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The console's `save` walks from the masked start to the masked end and never finishes
    when the end wraps below the start, so a range past the space is refused before the console
    (`read.space_bound`), which keeps that wrap out of reach. A range ending at the mask is
    inside; one lying wholly beyond a mask that is not all ones is past the space too, and with
    no mask known nothing is refused."""
    ses = _ConsoleSession(bytes(64), replies={"save": lambda cmd: "Data saved successfully",
                                              "cpulist": captured("cpulist-main-visible.txt")})
    _console(monkeypatch, tmp_path, ses)
    monkeypatch.setattr(mstate.STATE, "machine_map", _masked(0xFFFFFF))
    refused("wraps", s.memdump("0xfffffc", length=8, dest=str(tmp_path / "over.bin")))
    assert ses.commands == ["cpulist"], "only the cpu was read on a refused range"
    s.memdump("0xfffffc", length=4, dest=str(tmp_path / "edge.bin"))
    assert ses.commands[-1] == f"save {tmp_path / 'edge.bin'},0xfffffc,0x4", ses.commands
    # THE EDGE ITSELF: one byte at the top of the space is a range; one past the mask wraps.
    refused("wraps", s.memdump("0xfffffe", length=3, dest=str(tmp_path / "past.bin")))
    s.memdump("0xffffff", length=1, dest=str(tmp_path / "top.bin"))
    assert ses.commands[-1] == f"save {tmp_path / 'top.bin'},0xffffff,0x1", ses.commands
    # A MASK THAT IS NOT ALL ONES: a range that wraps and one wholly past it are both refused.
    monkeypatch.setattr(mstate.STATE, "machine_map", _masked(0x3FFF))
    refused("wraps", s.memdump("0x3ffc", length=8, dest=str(tmp_path / "wrap.bin")))
    refused("mask is 0x3fff", s.memdump("0x4000", length=4, dest=str(tmp_path / "alias.bin")))
    assert not ses.commands[-1].startswith("save"), ses.commands
    monkeypatch.setattr(mstate.STATE, "machine_map", {})
    s.memdump("0xfffffc", length=8, dest=str(tmp_path / "unknown.bin"))
    assert ses.commands[-1].startswith("save"), "with no mask known the range is the console's"


def test_memdump_checks_the_file_against_a_read_of_the_cpu_save_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`save` reads the visible cpu, so the control does too."""
    def save(command: str) -> str:
        path, _start, length = command[len("save "):].split(",")
        Path(path).write_bytes(bytes(int(length, 16)))
        return "Data saved successfully\n"

    ses = _ConsoleSession(bytes(64), replies={"save": save,
                                              "cpulist": captured("cpulist-sub-visible.txt")})
    _console(monkeypatch, tmp_path, ses)
    out = refused(r"reads only :maincpu: `memdump\(cpu=':maincpu'\)` is the dump it can check",
                  s.memdump("0x0", length=8, dest=str(tmp_path / "nothread.bin")))
    assert out["code"] == "bad_argument" and not any(c.startswith("save") for c in ses.commands)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    out = s.memdump("0x0", length=8, dest=str(tmp_path / "sub.bin"))
    assert out["status"] == "ok" and out["cpu"] == ":subcpu" and "m@2" in ses.commands, out


def test_memdump_writes_the_bytes_and_checks_them_against_a_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The console's `save` takes HEX for the address and the length."""
    # NOT periodic: a repeating image lets a control read at the wrong address stay green.
    image = bytes((i * 7 + i // 256) & 0xFF for i in range(4096))

    def save(command: str) -> str:
        # `save <path>,<addr>,<length>`, hex fields with the `0x` prefix, as the tool sends them.
        path, addr, length = command[len("save "):].split(",")
        Path(path).write_bytes(image[int(addr, 16) : int(addr, 16) + int(length, 16)])
        return "Data saved successfully"

    ses = _ConsoleSession(image, replies={"save": save})
    _console(monkeypatch, tmp_path, ses)
    dest = tmp_path / "dump.bin"
    out = s.memdump("0x123", length=0x800, dest=str(dest))
    assert out["path"] == str(dest) and out["bytes"] == 0x800 and out["length"] == 0x800
    assert out["addr"] == f"{0x123:#010x}"
    assert dest.read_bytes() == image[0x123 : 0x123 + 0x800]
    # `0x` on both numbers: a bare `d0` would be the REGISTER to MAME's expression parser.
    assert ses.commands == ["cpulist", f"save {dest},0x123,0x800"], ses.commands
    assert out["session"]["altered"] is False and s.status()["session"]["altering_writes"] == 0, \
        "a file write is not a machine write"
    # A dump shorter than the control window compares only what there is.
    small = s.memdump("0xd0", length=8, dest=str(tmp_path / "small.bin"))
    assert small["bytes"] == 8 and small["addr"] == f"{0xD0:#010x}"
    assert ses.commands[-1] == f"save {tmp_path / 'small.bin'},0xd0,0x8"


def test_memdump_writes_a_mixed_case_dest_under_the_name_its_reply_gives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The free-name check judges the name written, and a name with no extension is refused."""
    image = bytes(range(64))

    def save(command: str) -> str:
        path, addr, length = command[len("save "):].split(",")
        Path(path).write_bytes(image[int(addr, 16) : int(addr, 16) + int(length, 16)])
        return "Data saved successfully"

    ses = _ConsoleSession(image, replies={"save": save})
    _console(monkeypatch, tmp_path, ses)
    out = s.memdump("0x0", length=8, dest=str(tmp_path / "Dump_A.BIN"))
    assert out["path"] == str(tmp_path / "dump-a.bin") and (tmp_path / "dump-a.bin").is_file()
    refused("exists", s.memdump("0x0", length=8, dest=str(tmp_path / "DUMP A.bin")))
    refused("no extension", s.memdump("0x0", length=8, dest=str(tmp_path / "dump")))


def test_memdump_is_invalid_when_the_file_comes_out_wrong(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A short file, or one whose bytes do not match what the protocol reads, is INVALID naming
    what came out, never a reply with a plausible size."""
    image = bytes(range(256))

    def short(command: str) -> str:
        Path(command[len("save "):].split(",")[0]).write_bytes(image[:8])
        return "Data saved successfully"

    _console(monkeypatch, tmp_path, _ConsoleSession(image, replies={"save": short}))
    out = s.memdump("0x0", length=32, dest=str(tmp_path / "short.bin"))
    assert out["status"] == "INVALID" and out["code"] == "readback_refused"
    assert "8 bytes" in out["message"] and "32 were asked" in out["message"]

    def wrong(command: str) -> str:
        Path(command[len("save "):].split(",")[0]).write_bytes(bytes(32))
        return "Data saved successfully"

    _console(monkeypatch, tmp_path, _ConsoleSession(image, replies={"save": wrong}))
    out = s.memdump("0x0", length=32, dest=str(tmp_path / "wrong.bin"))
    assert out["status"] == "INVALID" and "differ" in out["message"]

    _console(monkeypatch, tmp_path, _ConsoleSession(image, replies={"save": "Error opening x"}))
    out = s.memdump("0x0", length=32, dest=str(tmp_path / "none.bin"))
    assert out["status"] == "INVALID" and "no file" in out["message"]
    assert "Error opening x" in out["message"], "the console's own words are the only diagnostic"


def test_a_save_not_kept_leaves_no_file_and_names_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A save the server makes for itself."""
    image = bytes((i * 7 + i // 256) & 0xFF for i in range(4096))
    path = tmp_path / "snap.bin"

    def writing(data: bytes) -> Any:
        def save(command: str) -> str:
            Path(command[len("save "):].split(",")[0]).write_bytes(data)
            return "Data saved successfully"
        return save

    ses: Any = _ConsoleSession(image, replies={"save": writing(image[0x10:0x30])})
    _console(monkeypatch, tmp_path, ses)
    snapshot = files.save_checked(ses, None, 1, "", 0x10, 0x20, path, keep=False)
    assert snapshot == image[0x10:0x30], "the copy's bytes, read before the file goes"
    assert ses.commands[-1] == f"save {path},0x10,0x20" and not path.exists()
    ses.replies["save"] = writing(bytes(0x20))
    out = files.save_checked(ses, None, 1, "", 0x10, 0x20, path, keep=False)
    assert isinstance(out, dict) and out["code"] == "readback_refused", out
    assert "removed" in out["message"] and str(path) not in out["message"] and "path" not in out
    assert not path.exists()
    ses.replies["save"] = writing(image[:8])
    with pytest.raises(mstate.Invalid) as raised:
        files.save_checked(ses, None, 1, "", 0x10, 0x20, path, keep=False)
    said = str(raised.value)
    assert raised.value.code == "readback_refused" and "8 bytes" in said and "removed" in said
    assert str(path) not in said and "path" not in raised.value.fields and not path.exists()
    # The console's own refusal names the file it could not open: quoted without the path, and
    # with nothing written there is nothing to say was removed.
    ses.replies["save"] = f"Error opening file '{path}'"
    with pytest.raises(mstate.Invalid) as raised:
        files.save_checked(ses, None, 1, "", 0x10, 0x20, path, keep=False)
    said = str(raised.value)
    assert raised.value.code == "unexpected_answer" and "Error opening file" in said, said
    assert str(path) not in said and "removed" not in said and not path.exists()
    # A file already there is not the server's to overwrite or delete.
    path.write_bytes(b"somebody's")
    with pytest.raises(mstate.Invalid) as raised:
        files.save_checked(ses, None, 1, "", 0x10, 0x20, path, keep=False)
    assert raised.value.code == "host_failed" and path.read_bytes() == b"somebody's"
    path.unlink()

    class Refusing(_ConsoleSession):
        def read(self, addr: int, n: int, *, thread: int) -> bytes:
            raise g.Refused("E01")

    refusing: Any = Refusing(image, replies={"save": writing(image[0x10:0x30])})
    out = files.save_checked(refusing, None, 1, "", 0x10, 0x20, path, keep=False)
    assert isinstance(out, dict) and out["code"] == "readback_refused" and "path" not in out, out
    assert "removed" in out["message"] and str(path) not in out["message"]
    assert not path.exists()

    class Breaking(_ConsoleSession):
        broken: str | None = None

        def read(self, addr: int, n: int, *, thread: int) -> bytes:
            raise g.SessionError("the stub closed the connection")

    breaking: Any = Breaking(image, replies={"save": writing(image[0x10:0x30])})
    out = files.save_checked(breaking, None, 1, "", 0x10, 0x20, path, keep=False)
    assert isinstance(out, dict) and out["code"] == "session_broken" and "path" not in out, out
    assert breaking.broken and "removed" in out["message"] and not path.exists()


def test_log_returns_the_newest_matching_lines_and_counts_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reply's shape."""
    scratch = _console(monkeypatch, tmp_path, _ConsoleSession())
    (scratch / "error.log").write_text(
        "".join(f"[:] blit start {i}\n" if i % 2 else f"other {i}\n" for i in range(100))
    , newline="")
    out = s.log("blit start", channel="emulator", limit=3)
    assert out["lines_total"] == 50 and len(out["lines"]) == 3 and out["truncated"] is True
    assert out["lines"] == ["[:] blit start 95", "[:] blit start 97", "[:] blit start 99"]
    assert out["pattern"] == "blit start"
    everything = s.log("blit start", channel="emulator", limit=read.LOG_LIMIT_MAX)
    assert len(everything["lines"]) == 50 and everything["truncated"] is False
    none = s.log("never-written", channel="emulator")
    assert none["lines_total"] == 0 and none["lines"] == []
    # A raw byte out of ROM, and a CRLF log from elsewhere: neither raises, neither leaks a `\r`.
    (scratch / "error.log").write_bytes(b"ok\r\n\xff raw\r\nend\r\n")
    rough = s.log("^(ok|end)$", channel="emulator")
    assert rough["lines_total"] == 2 and rough["lines"] == ["ok", "end"]


def test_log_refuses_a_bad_limit_or_regex_and_is_invalid_without_a_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch = _console(monkeypatch, tmp_path, _ConsoleSession())
    out = s.log("x", channel="emulator")
    assert out["status"] == "INVALID" and "error.log" in out["message"]
    (scratch / "error.log").write_text("a\n", newline="")
    refused("limit",
    s.log("x", channel="emulator", limit=0))
    refused("limit",
    s.log("x", channel="emulator", limit=read.LOG_LIMIT_MAX + 1))
    refused("does not compile",
    s.log("(unclosed", channel="emulator"))


def test_snapshot_without_a_dest_lands_in_the_scratch_and_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _ConsoleSession()
    scratch = _console(monkeypatch, tmp_path, ses)
    ses.replies["snap"] = _snapping(scratch / "snap")
    monkeypatch.setattr(mstate.STATE, "snapshots", 0)
    first = s.snapshot()
    second = s.snapshot()
    assert Path(first["path"]).parent == scratch / "snap"
    assert first["path"] != second["path"], "two snapshots are two files"
    assert first["bytes"] == len(_PNG) and Path(first["path"]).read_bytes() == _PNG
    # THE HASH THE GOLDENS COMPARE, computed by the server over the bytes it hands back, so
    # a repo need not check every capture against its `checksums.sha256` by hand.
    assert first["sha256"] == hashlib.sha256(_PNG).hexdigest()
    assert first["sha256"] == second["sha256"]
    assert ses.commands == ["snap snapshot-1.png", "snap snapshot-2.png"]
    # A CAPTURE SAYS WHICH VIEW MADE IT, the one the session was launched with.
    assert first["view"] == "native" and list(first)[-1] == "session", first
    monkeypatch.setattr(mstate.STATE, "view", "Shifter-R Overlay")
    assert s.snapshot()["view"] == "Shifter-R Overlay"


def test_snapshot_with_a_dest_moves_the_file_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MAME writes `snap <abs path>` RELATIVE to its snapshot directory."""
    ses = _ConsoleSession()
    scratch = _console(monkeypatch, tmp_path, ses)
    ses.replies["snap"] = _snapping(scratch / "snap")
    monkeypatch.setattr(mstate.STATE, "snapshots", 0)
    dest = tmp_path / "frame.png"
    out = s.snapshot(dest=str(dest))
    assert out["path"] == str(dest) and dest.exists() and out["bytes"] == len(_PNG)
    assert not list((scratch / "snap").iterdir()), "nothing left behind in the scratch"
    refused("exists",
    s.snapshot(dest=str(dest)))
    refused("must be an absolute path",
    s.snapshot(dest="frame.png"))
    refused("is not a directory",
    s.snapshot(dest=str(tmp_path / "missing" / "frame.png")))
    assert ses.commands == ["snap snapshot-1.png"], "the refusals touched no console"


def test_snapshot_is_invalid_when_no_file_appears(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _console(monkeypatch, tmp_path, _ConsoleSession(replies={"snap": "Saved screen #0 ..."}))
    monkeypatch.setattr(files, "FILE_WAIT_S", 0.2)
    out = s.snapshot()
    assert out["status"] == "INVALID" and out["code"] == "unexpected_answer"
    assert "snapshot-" in out["message"] and "no file" in out["message"]


def test_snapshot_is_invalid_when_the_png_is_not_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A zero-byte or half-written file is what a full disk leaves; existence is not a snapshot."""
    ses = _ConsoleSession()
    scratch = _console(monkeypatch, tmp_path, ses)

    def half(command: str) -> str:
        (scratch / "snap" / command[len("snap "):]).write_bytes(_PNG[:-6])
        return "Saved"

    ses.replies["snap"] = half
    monkeypatch.setattr(files, "FILE_WAIT_S", 0.2)
    out = s.snapshot()
    assert out["status"] == "INVALID" and f"{len(_PNG) - 6} bytes so far" in out["message"]


def test_the_console_fixtures_were_captured_and_say_so() -> None:
    """The parsers below are written against MAME's OWN text, captured live."""
    provenance = (FIXTURES / "provenance.txt").read_text()
    assert provenance.startswith("Captured live from MAME")
    fixtures = sorted(f.name for f in FIXTURES.iterdir() if f.name != "provenance.txt")
    assert fixtures, "no fixtures at all is not a clean directory, it is nothing examined"
    for name in fixtures:
        assert (FIXTURES / name).stat().st_size > 0, name
        assert name in provenance, f"{name} has no line in provenance.txt saying what produced it"
    # The two shapes the parsers depend on are really in the captured text.
    assert "Found at " in (FIXTURES / "find.txt").read_text()
    assert (FIXTURES / "find-none.txt").read_text().strip() == "Not found"


def test_disassemble_reads_the_file_the_console_wrote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`dasm` writes a FILE, not a reply: the tool names the file, asks, reads it back."""

    ses = _ConsoleSession()
    scratch = _console(monkeypatch, tmp_path, ses)

    def dasm(command: str) -> str:
        name = command[len("dasm "):].split(",")[0]
        (scratch / name).write_bytes((FIXTURES / "dasm.txt").read_bytes())
        return (FIXTURES / "dasm-reply.txt").read_text()

    ses.replies["dasm"] = dasm
    out = s.disassemble("0x0", length=16)
    assert out["addr"] == f"{0:#010x}" and out["length"] == 16
    assert out["lines"][0] == "000000: 0020 1000 ori.b   #$0, -(A0)"
    assert len(out["lines"]) == 5, "16 bytes of this ROM came out as five lines"
    # A RELATIVE name: MAME's cwd is the scratch, so no path ever enters the console command.
    assert ses.commands == ["cpulist", "dasm dasm.txt,0x0,0x10"]
    assert (scratch / "dasm.txt").exists(), "the fake wrote where the real console would"
    assert out["session"]["altered"] is False
    refused("length",
    s.disassemble("0x0", length=read.READ_MAX + 1))


def test_a_stop_instruction_is_read_off_the_first_listing_line() -> None:
    """The stop's `instruction` splits address, opcode bytes and text, whatever the cpu."""
    got = read.stop_instruction("000404: 48E7 F000 movem.l D0-D3, -(A7)", 0x404, None)
    assert got["address"] == "000404" and got["bytes"] == "48E7F000", got
    assert got["text"] == "movem.l D0-D3, -(A7)", got
    x86 = read.stop_instruction("F5BC7: 83 3E 14 C0 01    cmp     word ptr [0C014h],1h // x",
                                0xF5BC7, None)
    assert x86["bytes"] == "833E14C001" and x86["text"].startswith("cmp     word ptr"), x86


def test_a_stop_instruction_tells_a_68000_abcd_from_an_opcode_word() -> None:
    """`abcd` has no size suffix, so it reads like a hex word; an operand pair gives it away."""
    mnemonic = read.stop_instruction("0010: C300 abcd D1, D0", 0x10, None)
    assert (mnemonic["bytes"], mnemonic["text"]) == ("C300", "abcd D1, D0"), mnemonic
    word = read.stop_instruction("0020: 0680 0000 ABCD addi.l #$1, D0", 0x20, None)
    assert (word["bytes"], word["text"]) == ("06800000ABCD", "addi.l #$1, D0"), word


def test_a_stop_instruction_drops_the_listing_s_padding_and_keeps_the_comment_apart() -> None:
    padded = read.stop_instruction("30000: FA                di      ", 0x30000, None)
    assert padded["text"] == "di" and "comment" not in padded, padded
    noted = read.stop_instruction("000400: 46FC 2700 move    #$2700, SR // the reset", 0x400, None)
    assert (noted["text"], noted["comment"]) == ("move    #$2700, SR", "the reset"), noted


def test_a_stop_instruction_reads_opcode_words_of_eight_digits() -> None:
    got = read.stop_instruction("0100: E1A00000 mov     r0, r0", 0x100, None)
    assert (got["bytes"], got["text"]) == ("E1A00000", "mov     r0, r0"), got


def test_a_stop_instruction_without_opcode_bytes_says_they_are_unavailable() -> None:
    got = read.stop_instruction("4a0: move.l d0,d1", 0x4A0, None)
    assert got["text"] == "move.l d0,d1" and got["bytes"]["available"] is False, got


def test_a_stop_instruction_names_the_symbol_that_places_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(read, "nearest_symbol", lambda addr, cpu=None: (0x400, "Main"))
    got = read.stop_instruction("000404: 4E71 nop", 0x404, None)
    assert (got["symbol"], got["delta"]) == ("Main", 4), got
    monkeypatch.setattr(read, "nearest_symbol", lambda addr, cpu=None: None)
    none = read.stop_instruction("000404: 4E71 nop", 0x404, None)
    assert none["symbol"]["available"] is False and none["delta"]["available"] is False, none


def test_an_operand_quoted_in_a_comment_is_not_resolved() -> None:
    """A note quoting where a value lives is not an operand of the line it sits on."""
    lines = ["F5BC7: 83 3E 14 C0 01    cmp     word ptr [0C014h],1h // the copy at [0E849h]",
             "F5BCC: 75 03             bne     0F5BD1h              // see [0C014h] // [0D000h]"]
    out = read.resolve_operands(lines, {"DATA": 0x400}, {}, {})
    assert [(r["line"], r["operand"], r["offset"]) for r in out] == [
        (0, "0C014h", "0x0000c014")], out


def test_a_resolved_operand_names_its_symbol_as_the_map_spelled_it() -> None:
    lines = ["F5BC7: 83 3E 14 C0 01    cmp     word ptr [0C014h],1h"]
    out = read.resolve_operands(lines, {"DATA": 0x400}, {"IN_IRQ": 0xC414}, {"IN_IRQ": "DATA"},
                                spelled={"IN_IRQ": "in_Irq"})
    assert [r["symbol"] for r in out] == ["in_Irq"], out


def test_an_operand_is_named_by_the_first_row_at_its_address_and_by_a_repeated_names_own_class(
) -> None:
    from scry_mame import gdb_session as gs
    lines = ["F5BC7: 83 3E 14 C0 01    cmp     word ptr [0C014h],1h"]
    names = gs.Names()
    for key, at, klass in (("TWIN_A", 0xC414, "DATA"), ("TWIN_B", 0xC414, "DATA"),
                           ("DUP", 0xC400, "CODE"), ("DUP", 0xC410, "DATA")):
        names.add(key, at, klass)
    classes = {"TWIN_A": "DATA", "TWIN_B": "DATA", "DUP": "CODE"}
    out = read.resolve_operands(lines, {"DATA": 0x400}, names, classes)
    assert [r["symbol"] for r in out] == ["TWIN_A"], "the first row of the file wins a tie"
    near = read.resolve_operands(["F5BC7: 83 3E 11 C0 01    cmp     word ptr [0C011h],1h"],
                                 {"DATA": 0x400}, names, classes)
    assert [r["symbol"] for r in near] == ["DUP"] and near[0]["delta"] == 1, (
        "the DATA row of a name that is CODE elsewhere is placed in DATA")


def test_disassemble_is_invalid_when_no_file_comes_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _ConsoleSession(replies={"dasm": "Error"})
    scratch = _console(monkeypatch, tmp_path, ses)
    out = s.disassemble("0x0")
    assert out["status"] == "INVALID" and "Error" in out["message"]
    refused("length",
    s.disassemble("0x0", length=0))
    # A listing left by an EARLIER call must not be read as this call's answer.
    (scratch / "dasm.txt").write_text("000000: stale line from before\n")
    again = s.disassemble("0x0")
    assert again["status"] == "INVALID", "a stale listing was reported as a fresh one"
    # A listing that exists and is empty is a fault, not zero instructions.
    ses.replies["dasm"] = lambda cmd: (scratch / "dasm.txt").write_text("\n") or "Data dumped"
    empty = s.disassemble("0x0")
    assert empty["status"] == "INVALID" and "empty" in empty["message"]


def test_disassemble_classifies_each_line_off_the_listing_without_opcode_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`flow` holds one class per line of `lines`."""
    ses = _ConsoleSession(replies={"cpulist": captured("cpulist-main-visible.txt")})
    scratch = _console(monkeypatch, tmp_path, ses)
    # TWO CPUS OF DIFFERENT TYPES, so a class read off one cpu's words with the other's table
    # cannot come out right by coincidence.
    monkeypatch.setattr(mstate.STATE, "machine_map", {"cpus": [
        {"tag": ":maincpu", "type": "m68000"}, {"tag": ":subcpu", "type": "v30"}]})
    ses.replies["dasm"] = _listing_pair(scratch, "dasm-m68k-560")
    out = s.disassemble("0x560", length=0x40)
    assert out["status"] == "ok" and out["flow_source"] == "mnemonic_table:m68000", out
    assert len(out["flow"]) == len(out["lines"]) and "note" not in out
    assert [(line.split(":")[0], c) for line, c in zip(out["lines"], out["flow"], strict=True)
            if c != "sequential"] == [("000578", "branch"), ("00058C", "call"),
                                      ("00059A", "return")]
    # THE SECOND LISTING NAMES THE CPU THE TABLE IS FOR, even when the call named none: left to
    # the console it would decode whichever cpu is visible then, under `:maincpu`'s table.
    assert [c for c in ses.commands if c.startswith("dasm")] == [
        "dasm dasm.txt,0x560,0x40", "dasm dasm-bare.txt,0x560,0x40,0,:maincpu"]
    # A CPU NAMED travels to both listings, and picks its own type's table.
    ses.commands.clear()
    ses.replies["dasm"] = _listing_pair(scratch, "dasm-v30-30000")
    out = s.disassemble("0x30000", length=0xb0, cpu="subcpu")
    assert [c for c in ses.commands if c.startswith("dasm")] == [
        "dasm dasm.txt,0x30000,0xb0,1,:subcpu", "dasm dasm-bare.txt,0x30000,0xb0,0,:subcpu"]
    assert out["flow_source"] == "mnemonic_table:v30" and "unknown" not in out["flow"], out


def test_disassemble_without_a_table_marks_every_line_unknown_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A type with no table, a type the inventory never recorded."""
    ses = _ConsoleSession(replies={"cpulist": captured("cpulist-main-visible.txt")})
    scratch = _console(monkeypatch, tmp_path, ses)
    ses.replies["dasm"] = _listing_pair(scratch, "dasm-m68k-560")
    monkeypatch.setattr(mstate.STATE, "machine_map", {"cpus": [
        {"tag": ":maincpu", "type": "m68010"}]})
    out = s.disassemble("0x560", length=0x40)
    assert out["status"] == "ok" and len(out["lines"]) == 15
    assert out["flow"] == ["unknown"] * 15 and out["flow_source"] == "none"
    assert "'m68010'" in out["note"] and "m68000, v30" in out["note"], out["note"]
    assert [c for c in ses.commands if c.startswith("dasm")] == ["dasm dasm.txt,0x560,0x40"]
    monkeypatch.setattr(mstate.STATE, "machine_map", {})
    out = s.disassemble("0x560", length=0x40)
    assert out["flow_source"] == "none" and ":maincpu" in out["note"], out["note"]
    # THE SECOND LISTING FAILS: the first one is still the answer, and nothing is classified.
    monkeypatch.setattr(mstate.STATE, "machine_map", {"cpus": [
        {"tag": ":maincpu", "type": "m68000"}]})
    first = _listing_pair(scratch, "dasm-m68k-560")
    ses.replies["dasm"] = lambda cmd: first(cmd) if cmd.startswith("dasm dasm.txt") else "Error"
    out = s.disassemble("0x560", length=0x40)
    assert out["status"] == "ok" and out["flow"] == ["unknown"] * 15, out
    assert "without opcode bytes did not come out" in out["note"], out["note"]
    # THE SECOND LISTING DESCRIBES OTHER INSTRUCTIONS: no class is shifted onto a neighbour.
    other = _listing_pair(scratch, "dasm-v30-30000")
    ses.replies["dasm"] = lambda cmd: first(cmd) if cmd.startswith("dasm dasm.txt") else other(cmd)
    out = s.disassemble("0x560", length=0x40)
    assert out["flow"] == ["unknown"] * 15 and "same addresses" in out["note"], out


def test_find_parses_hits_and_an_empty_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The captured `find` answered two hits for the image's first four bytes over 64 KB."""
    ses = _ConsoleSession(replies={"find": _first_window((FIXTURES / "find.txt").read_text())})
    _console(monkeypatch, tmp_path, ses)
    out = s.find(ref="0x0", length=0x10000, data_hex="00201000")
    assert out["hits"] == ["0x00000000", "0x000025ea"] and out["hits_total"] == 2
    assert out["addr"] == "0x00000000" and out["length"] == 0x10000 and out["truncated"] is False
    assert out["session"]["altered"] is False
    # Every byte travels prefixed: a bare `d0` is a register to the console's expression parser.
    assert ses.commands == ["cpulist", "find 0x0,0x8000,0x00,0x20,0x10,0x00",
                            "find 0x8000,0x8000,0x00,0x20,0x10,0x00"]
    ses.replies["find"] = (FIXTURES / "find-none.txt").read_text()
    none = s.find(ref="0x0", length=0x10000, data_hex="DEADBEEFCAFE")
    assert none["hits"] == [] and none["hits_total"] == 0
    assert ses.commands[-1] == "find 0x8000,0x8000,0xde,0xad,0xbe,0xef,0xca,0xfe", (
        "lower, prefixed")
    one = s.find(ref="0x10", length=16, data_hex="D0")
    assert ses.commands[-1] == "find 0x10,0x10,0xd0" and one["hits_total"] == 0
    before = len(ses.commands)
    for bad in ("abc", "", "zz"):
        refused("data_hex",
        s.find(ref="0x0", length=16, data_hex=bad))
    refused("length",
    s.find(ref="0x0", length=0, data_hex="00"))
    assert len(ses.commands) == before, "a refused input reached the console"


def test_find_is_invalid_when_the_console_answers_something_else(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Zero hits is a measurement only when the console said `Not found`."""
    ses = _ConsoleSession()
    _console(monkeypatch, tmp_path, ses)
    for answer in ("Invalid memory space", "", "OK", "Found at 000000 (mirror)", "Not found at 0",
                   # A HIT BESIDE A LINE OF ANOTHER SHAPE is not a count of hits.
                   "Found at 000000\nInvalid memory space"):
        ses.replies["find"] = answer
        out = s.find(ref="0x0", length=16, data_hex="00")
        assert out["status"] == "INVALID", answer
        assert repr(answer.strip()) in out["message"] or answer == ""


def test_a_pattern_is_held_to_the_parameters_the_consoles_find_takes() -> None:
    """Each byte is a parameter of its own after the address and the length."""
    assert len(read.check_find(ref="0x0", length=16, data_hex="00" * read.FIND_BYTES_MAX)) == 126
    with pytest.raises(mstate.Invalid, match=r"byte count of data_hex=127 is outside 1\.\.126"):
        read.check_find(ref="0x0", length=16, data_hex="00" * (read.FIND_BYTES_MAX + 1))


def test_a_listing_with_a_raw_byte_is_decoded_with_replacement_never_an_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A comment or a label the disassembler prints raw out of ROM."""
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor

    def raw_listing(command: str, timeout: float = 10.0) -> str:
        if command.startswith("dasm "):
            (tmp_path / command[5:].split(",")[0]).write_bytes(b"000000: dc.b \xff\n")
            return ""
        return real(command, timeout)

    monkeypatch.setattr(ses, "monitor", raw_listing)
    out = s.disassemble(ref="0x0", length=1)
    assert out["status"] == "ok" and out["lines"] == ["000000: dc.b \ufffd"], out


def test_find_caps_the_hits_it_hands_back_and_keeps_the_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A search for one byte over an address space is legitimate; its answer in the reply is not."""
    many = "\n".join(f"Found at {i:06X}" for i in range(read.LOG_LIMIT_MAX + 50)) + "\n"
    _console(monkeypatch, tmp_path, _ConsoleSession(replies={"find": _first_window(many)}))
    out = s.find(ref="0x0", length=0x00100000, data_hex="00")
    assert out["hits_total"] == read.LOG_LIMIT_MAX + 50
    assert len(out["hits"]) == read.LOG_LIMIT_MAX and out["truncated"] is True
    assert out["hits"][-1] == f"{read.LOG_LIMIT_MAX + 49:#010x}", "the tail, newest last"
    # EXACTLY AT THE CAP nothing is cut, and the reply says so.
    exact = "\n".join(f"Found at {i:06X}" for i in range(read.LOG_LIMIT_MAX)) + "\n"
    _console(monkeypatch, tmp_path, _ConsoleSession(replies={"find": _first_window(exact)}))
    out = s.find(ref="0x0", length=0x00100000, data_hex="00")
    assert out["hits_total"] == read.LOG_LIMIT_MAX == len(out["hits"]) and out["truncated"] is False


def test_history_returns_the_consoles_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _ConsoleSession(replies={"history": (FIXTURES / "history.txt").read_text()})
    _console(monkeypatch, tmp_path, ses)
    out = s.history(limit=8)
    assert len(out["lines"]) == 8 and out["asked"] == 8
    assert out["lines"][0] == "0025E8: lea     $201000.l, A0"
    assert out["lines"][-1] == "0025F6: dbra    D0, $25f4"
    # `0x` here too: the console reads a bare number as hex, so `,10` would be sixteen lines.
    assert ses.commands == ["cpulist", "history ,0x8"]
    # MAME'S OWN DEPTH (`HISTORY_SIZE`), which it would clamp to in silence: at it, one past it.
    assert s.history(limit=read.HISTORY_MAX)["status"] == "ok"
    for bad in (0, read.HISTORY_MAX + 1):
        refused("limit",
        s.history(limit=bad))
    # The console complaining is not a trail.
    for answer in ("OK", "Not enough history", "0025E8: lea $1, A0\nError: x"):
        ses.replies["history"] = answer
        out = s.history(limit=8)
        assert out["status"] == "INVALID", answer
    # NOTHING is a trail of none: MAME prints no line for a cpu that has retired none yet.
    ses.replies["history"] = ""
    out = s.history(limit=8)
    assert out["status"] == "ok" and out["lines"] == [] and "retired no" in out["note"]
    ses.replies["history"] = "No disassembler available for device :dsp"
    assert s.history(limit=8)["code"] == "no_channel"


@pytest.mark.parametrize(
    "command", ["dasm x,0,10", "find 0,ffff,00", "history ,8", "snap shot.png", "save f,0,10"]
)
def test_the_console_readers_do_not_count_as_writes(command: str) -> None:
    """`save` writes a FILE, not the machine, and a pattern like `save\\w*` meant for save states,
    which are `state*`, marks it by accident. A reader marked as a writer turns `altered` into
    noise. The go-family (`gtime` included) is NOT here: it moves the machine, and sits with `g`
    and `step` in the mutating list above."""
    assert not mconsole.mutates(command), f"{command!r} only reads and is marked"


def test_set_register_takes_an_integer_and_answers_hex(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    """The value reaches the stub as the integer given."""
    ses = _RegisterSession(bits=16)
    _install(monkeypatch, ses, tmp_path)
    out = s.set_register("EAX", 0x1234)
    assert ses.values["EAX"] == 0x1234, "the integer reached the stub as it came"
    assert out["value"] == "0x1234" and out["register"] == "EAX"
    assert out["readback"] == "0x1234" and out["verified"] is True
    assert out["summary"] == "set_register EAX = 0x1234, verified True"
    refused("negative",
    s.set_register("EAX", -1))
    got = refused("unknown register", s.set_register("NOTAREG", 1))
    assert got["code"] == "bad_argument", got
    got = refused("does not fit", s.set_register("EAX", 1 << 16))
    assert got["code"] == "bad_argument" and ses.values["EAX"] == 0x1234, got
    # ZERO IS A VALUE a register holds, and the width is asked of the register BY NAME.
    widths = ses.register_width
    monkeypatch.setattr(ses, "register_width",
                        lambda name: widths(str(name).upper()) if name else 1 / 0)
    out = s.set_register("EAX", 0)
    assert out["value"] == "0x0000" and out["readback"] == "0x0000" and out["verified"] is True
    ses.values["EAX"] = 0x1234
    ses.set_reg = lambda name, value, *, thread: None  # type: ignore[method-assign]  # the stub takes it, nothing lands
    out = s.set_register("EAX", 0x5678)
    assert out["readback"] == "0x1234" and out["verified"] is False
    assert out["summary"] == "set_register EAX = 0x5678, verified False"


def test_every_tool_declares_a_title_and_the_readers_a_read_only_hint() -> None:
    """`title` is what the client shows; `readOnlyHint` is what lets it run readers in parallel."""
    tools = {t.name: t for t in s.mcp._tool_manager.list_tools()}
    untitled = sorted(n for n, t in tools.items() if not t.title)
    assert not untitled, f"tools with no title: {untitled}"
    read_only = {n for n, t in tools.items()
                 if t.annotations is not None and t.annotations.read_only_hint}
    assert read_only == {"status", "read_memory", "disassemble", "find", "history", "log",
                         "log_wait", "registers", "declaration_list", "rom_check",
                         "symbols_find", "state_list", "captures", "machine_map",
                         "cpu_info", "comment_list", "audio_compare"}, read_only
    idempotent = {n for n, t in tools.items()
                  if t.annotations is not None and t.annotations.idempotent_hint}
    assert idempotent == {"machine_map"}, idempotent


def test_the_front_door_sends_the_reader_to_the_generated_index_and_keeps_no_table() -> None:
    """The roster a stranger reads is REFERENCE.md's index, generated from the registry and held
    to it by the reference pages' drift test; a table typed into the front door is a second copy
    that falls behind the day a tool is added, so the front door links the index and holds none."""
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    assert "## The tools" in readme, "the front door lost its tools section"
    tools = readme.split("## The tools", 1)[1].split("\n## ", 1)[0]
    assert "](REFERENCE.md)" in tools, "the tools section does not link the index"
    assert "| tool |" not in readme, "a hand-kept tool table is back in the front door"


def test_registers_states_each_width_explicitly_beside_the_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The width is in the digit count of a zero-padded value."""
    ses = _RegisterSession(bits=16)
    _install(monkeypatch, ses, tmp_path)
    use_table(monkeypatch, table={})
    out = s.registers()
    assert out["register_bits"] == {"EAX": 16, "EIP": 16}, out
    wide = _RegisterSession(bits=32)
    _install(monkeypatch, wide, tmp_path)
    assert s.registers()["register_bits"] == {"EAX": 32, "EIP": 32}
    # A stop reply carries the values but NOT the widths block: no noise on every stop.
    out2 = s.run_to(ref="0xf2034", control="0x4a0", seconds=1.0)
    assert "register_bits" not in out2, out2


@pytest.mark.parametrize(("threads", "shown"), [
    ({1: ":maincpu", 2: ":subcpu"}, {"1": ":maincpu", "2": ":subcpu"}),
    ({}, {}),
], ids=["patched", "unpatched"])
def test_status_names_the_stubs_threads_and_none_on_a_stub_without_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, threads: dict[int, str],
    shown: dict[str, str],
) -> None:
    """Whether this build's stub serves a thread per cpu is read at `connect` and reported,
    never assumed from the binary's path: empty is the build that serves the first cpu."""
    ses = _running(monkeypatch, tmp_path)
    ses.threads = threads
    assert s.status()["threads"] == shown


def test_renaming_a_log_channel_reaches_every_consumer_through_the_constant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE CONSTANT EXISTED AND ALMOST NOBODY DRANK FROM IT."""
    from scry_mame import transport
    monkeypatch.setitem(files.LOG_FILES, "emulator", "renamed-emulator.log")
    monkeypatch.setitem(files.LOG_FILES, "process", "renamed-process.log")
    (tmp_path / "renamed-emulator.log").write_text("DRIVER: a line\n", encoding="utf-8", newline="")
    (tmp_path / "renamed-process.log").write_text(
        f"{launch.CFG_PARSE_ERROR}: nonsense\n", encoding="utf-8", newline="")
    # THE OLD NAMES ARE WRITTEN BY NOBODY, which is what makes every assertion below a
    # statement about the constant rather than about a file that happens to be there twice.
    assert not (tmp_path / "error.log").exists() and not (tmp_path / "stdout.log").exists()

    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path)
    assert launch.channels() == {"errorlog_path": str(tmp_path / "renamed-emulator.log"),
                                 "stdout_path": str(tmp_path / "renamed-process.log")}
    assert launch.cfg_parse_error(tmp_path) is not None, "the cfg guard reads the process log"
    assert "nonsense" in launch.stdout_tail(tmp_path)
    assert "DRIVER" in launch.channel_tail(tmp_path, "emulator")
    assert files.errorlog_since(tmp_path, 0)[0] == ["DRIVER: a line"]
    assert [path.name for _tag, path in files.channel_files(tmp_path, "all")] == [
        "renamed-emulator.log", "renamed-process.log"]
    # THE LUA CHANNEL READS THE PROCESS LOG BY BYTE, and a mark of 0 over a missing file is
    # exactly what a fresh console looks like, so the size is the assertion that bites.
    assert transport.stdout_mark(tmp_path) > 0
    assert b"nonsense" in transport.since(tmp_path, 0)
    assert files.log_mark(tmp_path) > 0, "and the error log the same way"
    answered = f"echo-me\n{mstate.LUA_SENTINEL}#7\ttrue\t\n"
    (tmp_path / "renamed-process.log").write_text(answered, encoding="utf-8", newline="")
    monkeypatch.setattr(mstate.STATE, "console_mark", 0)
    monkeypatch.setattr(mstate.STATE, "lua_seq", 7)
    monkeypatch.setattr(mstate.STATE, "lua_lost", 0)
    assert transport.answered_seq(tmp_path) == 7
    monkeypatch.setattr(mstate.STATE, "console_mark", 0)
    found, _raw = transport.find_answer(tmp_path, "echo-me", 7)
    assert found is not None and found.ok


def test_a_renamed_log_channel_reaches_the_call_that_creates_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE WRITER, which the reader gate above cannot reach."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    monkeypatch.setitem(files.LOG_FILES, "emulator", "renamed-emulator.log")
    monkeypatch.setitem(files.LOG_FILES, "process", "renamed-process.log")
    out = s.start(**_boot_args(tmp_path, image))
    try:
        scratch = Path(out["scratch_dir"])
        assert out["stdout_path"] == str(scratch / "renamed-process.log")
        assert out["errorlog_path"] == str(scratch / "renamed-emulator.log")
        # THE HANDLE THE PROCESS WAS GIVEN, which is the writer itself and not a path the
        # reply computed a second time: the two could disagree and only this says they do not.
        handed = _StubProcess.last_kwargs
        assert getattr(handed["stdout"], "name", None) == str(scratch / "renamed-process.log")
        assert not (scratch / "stdout.log").exists(), "the writer kept the old name"
    finally:
        s.close()


def test_every_registered_tool_is_named_in_the_instructions() -> None:
    """A tool registered but not named in the `instructions` string is one a session never
    learns exists."""
    registered = [t.name for t in s.mcp._tool_manager.list_tools()]
    assert mame_mcp.ROSTER.unlisted(registered) == []
    assert mame_mcp.ROSTER.text() in (s.mcp.instructions or ""), "the roster is not rendered"


def test_write_refuses_empty_data_and_reset_and_a_mutating_debug_count_as_writes(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The three decision points of the write family the battery executed through no test."""
    ses = _running(monkeypatch, tmp_path)
    refused("nothing to write",  # the tool's error, as an
    s.write(ref="0x100", data_hex=""))
    assert ses.writes == 0
    assert s.reset()["kind"] == "softreset" and ses.writes == 1
    monkeypatch.setattr(mstate.STATE, "console_writes", 0)
    assert s.debug(command="bplist")["mutates"] is False
    assert mstate.STATE.console_writes == 0
    assert s.debug(command="d1=1")["mutates"] is True
    assert mstate.STATE.console_writes == 1
    assert s.debug(command="d2=2")["mutates"] is True and mstate.STATE.console_writes == 2
    # AN EMPTY LINE asks the console nothing and is no write; a `g` releases the machine
    # and the reply says so.
    assert s.debug(command="")["mutates"] is False
    out = s.debug(command="g")
    assert out["session"]["running"] is True and "released the machine" in out["note"], out


@pytest.mark.parametrize("command, mutates", [
    ("print {d1==7fff}", False),
    ("print {d1!=7fff}", False),
    ("print {d1<=7fff}", False),
    ("print {d1>=7fff}", False),
    ("print pc,d1==7fff", False),
    ("rpset {d1==7fff}", False),
    ("d0=1234", True),
    ("print pc,d0=1", True),
    ("bpset 400,1,{d0=1}", True),
    ("bp 0x400,1,{fill 100,1,1}", True),
    ("wpset 400,2,w,1,{ temp0++ ; g }", True),
    ("rpset {d1==7fff},{d0=1}", True),
    ("bpset 400,1,{d0==1}", True),          # an action, whatever it holds
    ("wpdset 400,2,w,1,{ g }", True),
    ("bpdisable 1", False),
    ("rpset{d1==7fff}", False),
    ("statesave x", False),
    ("stateload x", True),
    ("temp9=0", False),
    ("temp9=0;fill 100,1,1", True),
])
def test_a_comparison_typed_through_debug_is_a_read_and_an_assignment_or_an_action_a_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str, mutates: bool,
) -> None:
    """A comparison operator is never an assignment."""
    _console(monkeypatch, tmp_path, _ConsoleSession(replies={"print": "0\n"}))
    monkeypatch.setattr(mstate.STATE, "console_writes", 0)
    out = s.debug(command=command)
    assert out["mutates"] is mutates, (command, out["mutates"])
    assert out["command"] == command
    assert mstate.STATE.console_writes == (1 if mutates else 0)
    assert out["session"]["altered"] is mutates, out["session"]


def test_reset_is_soft_applied_and_read_back_and_a_hard_reset_is_refused(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The console's `softreset` is a timer that fires when the machine next runs."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "boot_pc", 0xF2034)
    # NO HARD RESET IS OFFERED: it would end the session, which is `close` and `start`.
    assert "hard" not in inspect.signature(s.reset).parameters
    assert ses.writes == 0 and "hardreset" not in ses.commands
    ses.frame = 661
    ses.pcs = [0xF2034, 0xF2034]
    out = s.reset()
    assert out["kind"] == "softreset" and out["pc"] == f"{0xF2034:#010x}", out
    assert out["verified"] is True and out["boot_pc"] == f"{0xF2034:#010x}"
    # The double's stop moves its counter, as a real step does: the frame read is the one
    # AFTER the reset landed, whatever it is, never the 661 the machine held before.
    assert out["frame_at_reset"] == ses.frame != 661, out
    assert ses.writes == 1 and out["session"]["altered"] is True
    assert "softreset" in ses.commands
    last_frame_read = len(ses.commands) - 1 - ses.commands[::-1].index("print frame")
    assert ses.commands.index("softreset") < last_frame_read, (
        "the frame is read AFTER the reset is applied")
    assert out["summary"] == (f"reset: softreset applied at frame {ses.frame}, pc 0x000f2034 "
                              "verified True")
    assert out["cause"] == "softreset" and out["frame"] == ses.frame and "regs" in out, out
    after = s.status()
    assert "stopped_on_its_own" not in after, after
    assert after["last_stop"]["cause"] == "softreset" and after["last_stop"]["frame"] == ses.frame

    ses.pcs = [0xF2034, 0x1000]
    assert s.reset()["verified"] is False


def test_find_can_search_within_a_symbol_class_region(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A one-byte pattern searched over the whole address space drowns in false positives."""
    ses = _ConsoleSession(replies={"find": (FIXTURES / "find-none.txt").read_text()})
    _console(monkeypatch, tmp_path, ses)
    use_table(monkeypatch, table={"MSG_A": 0x420, "MSG_B": 0x480})
    use_table(monkeypatch, class_span={"DATA": (0x420, 0x480), "CODE": (0x0, 0x200)})
    out = s.find(symbol_class="DATA", data_hex="AD")
    assert out["status"] == "ok", out
    assert out["symbol_class"] == "DATA" and out["addr"] == "0x00000420"
    # length spans lo..hi inclusive of the last symbol's first byte.
    assert ses.commands[-1] == "find 0x420,0x61,0xad", ses.commands[-1]
    assert out["span"] == {"from": "0x00000420", "length": 0x61, "source": "class symbols",
                           "note": "the class's symbols' [min, max]: a match past the last "
                                   "symbol's own start is not covered"}, out
    by_range = s.find(ref="0x0", length=16, data_hex="AD")
    assert by_range["span"] == {"from": "0x00000000", "length": 16,
                                "source": "ref+length"}, by_range
    refused("not both", s.find(ref="0x0", data_hex="AD", symbol_class="DATA"))   # a ref alone, too
    both = s.find(ref="0x0", length=16, data_hex="AD", symbol_class="DATA")
    assert both["status"] == "INVALID" and "symbol_class" in both["message"], both
    unknown = s.find(symbol_class="NOPE", data_hex="AD")
    assert unknown["status"] == "INVALID" and "NOPE" in unknown["message"], unknown
    # NO RANGE AT ALL names the two sources of one, instead of complaining about a length.
    for none in (s.find(data_hex="AD"), s.find(length=16, data_hex="AD")):
        assert none["status"] == "INVALID" and "symbol_class" in none["message"] \
            and "ref" in none["message"], none


def test_every_registered_tool_carries_a_description() -> None:
    """A tool can reach the client with no `description` at all."""
    import asyncio
    tools = asyncio.run(s.mcp.list_tools())
    assert len(tools) > 30, "the registry answered almost nothing"
    mute = sorted(t.name for t in tools if not (t.description or "").strip())
    assert mute == [], f"tools with no description: {mute}"


def test_history_counts_what_came_back_and_keeps_what_was_asked_apart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """At the boot only one instruction has retired."""
    ses = _ConsoleSession(replies={"history": "0025E8: lea     $201000.l, A0\n"})
    _console(monkeypatch, tmp_path, ses)
    out = s.history(limit=8)
    assert out["asked"] == 8 and len(out["lines"]) == 1, out
    assert out["summary"] == "history: 1 instruction of 8 asked", out["summary"]


def test_find_summary_names_the_pattern_and_where_it_looked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A session's summaries are what a reader has to tell one search from the next."""
    ses = _ConsoleSession(replies={"find": _first_window((FIXTURES / "find.txt").read_text())})
    _console(monkeypatch, tmp_path, ses)
    out = s.find(ref="0x0", length=0x10000, data_hex="00201000")
    assert out["summary"] == "find 00201000 in 0x10000 bytes at 0x0: 2 hits", out["summary"]
    use_table(monkeypatch, class_span={"CODE": (0x0, 0xFFFF)})
    by_region = s.find(symbol_class="code", data_hex="e8")
    assert by_region["summary"] == "find e8 in CODE: 2 hits", by_region["summary"]


def test_a_console_run_found_at_rest_is_named_where_it_is_and_is_no_longer_a_console_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    ses.pcs = [0x4A0]
    monkeypatch.setattr(running, "frame_at_rest", lambda ses_, reads=3, gap_s=0.1: True)
    ses.running = True
    monkeypatch.setattr(mstate.STATE, "console_run", True)
    found = s.status()["stopped_on_its_own"]
    assert found == {"stop_seq": 2, "pc": "0x000004a0", "cpu": ":maincpu", "frame": ses.frame,
                     "cause": "breakpoint at 0x4a0",
                     "packet": "none: a run the console started"}, found
    assert mstate.STATE.console_run is False and ses.running is False


@pytest.mark.parametrize(("offset", "accepted"), [
    ("10", False), ("0x10", True), ("0X10", True), ("4", True), ("9", True), ("1c", True),
    ("1C", True), ("99", False)])
def test_a_pointer_offset_that_reads_two_ways_is_written_0x(offset: str, accepted: bool) -> None:
    """`[PTR]+10` reads as 0x10 (sixteen bytes) in the shared grammar and as ten in decimal."""
    from scry_mame import inputs as minputs
    if accepted:
        minputs.check_pointer_offset(f"[PTR]+{offset}")
    else:
        with pytest.raises(mstate.Invalid, match=f"write `0x{offset}` or `{int(offset):#x}`"):
            minputs.check_pointer_offset(f"[PTR]+{offset}")
        with pytest.raises(mstate.Invalid, match="written without `0x`"):
            minputs.check_pointer_offset(f"[PTR]-{offset}")


def test_watch_add_refuses_a_pointer_offset_that_reads_two_ways_before_any_session() -> None:
    out = refused("write `0x10`", s.watch_add(ref="[PTR]+10", mode="change", length=2))
    assert out["code"] == "bad_argument", out


def test_each_mark_reads_its_own_channel_and_a_missing_file_is_zero(tmp_path: Path) -> None:
    """The stdout mark is the process channel's, `error.log`'s the emulator's."""
    from scry_mame import transport
    assert files.log_mark(tmp_path) == 0 and transport.stdout_mark(tmp_path) == 0
    files.log_path(tmp_path, "process").write_bytes(b"x" * 7)
    assert transport.stdout_mark(tmp_path) == 7 == files.log_mark(tmp_path, "process")
    assert files.log_mark(tmp_path) == 0, "the emulator's channel is not the process's"
    files.log_path(tmp_path, "emulator").write_bytes(b"y" * 3)
    assert files.log_mark(tmp_path) == 3 and transport.stdout_mark(tmp_path) == 7


def test_any_one_console_count_not_zero_is_an_alarm_on_every_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mstate.STATE, "ses", None)
    for field in ("console_thread_errors", "console_reruns_seen", "console_lines_lost"):
        for name in ("console_thread_errors", "console_reruns_seen", "console_lines_lost"):
            monkeypatch.setattr(mstate.STATE, name, int(name == field))
        block = menvelope.session_block()
        assert sum(block["console"].values()) == 1, (field, block)
        assert "console" not in block.get("omitted", []), field
    for name in ("console_thread_errors", "console_reruns_seen", "console_lines_lost"):
        monkeypatch.setattr(mstate.STATE, name, 0)
    assert "console" not in menvelope.session_block()
    assert menvelope.session_block(whole=True)["console"] == {
        "thread_errors": 0, "reruns": 0, "lost": 0}
