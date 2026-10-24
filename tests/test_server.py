"""Gate for the server's guarantees: the things that, when broken, return a FALSE measurement.

None of these needs a live MAME, and that is exactly why they exist: they are the places where
the server can lie SILENTLY, and a silent lie is not found by looking.

Every test here comes from a REAL fault found auditing the server, and is written to go RED
against the previous code:

- the classification of `debug` commands, which was the open door in the `altered` guarantee;
- the window helper, whose absence killed the whole of `start` on anyone else's machine;
- the lock, without which two overlapping calls steal each other's stops;
- the MAME command line, which already had its test and is kept.
"""

import ast
import asyncio
import hashlib
import inspect
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from array import array
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scry_core import log_marks, placement
from scry_core import log_wait as core_wait
from scry_core import presence as presence_mod
from scry_core import progress as mprogress  # noqa: E402
from scry_core.reply_contract import unavailable  # noqa: E402
from session_doubles import (  # noqa: E402
    MAP_RAM,
    MAP_ROM,
    SessionFields,
    bp_records,
    bplist_add,
    captured,
    debugger_lists,
    documented,
    fake_mame,  # noqa: E402
    published,
    reading_session,
    refused,
    use_table,  # noqa: E402
)

import gdb_session as g  # noqa: E402
import mame_advance as advance  # noqa: E402
import mame_block as block  # noqa: E402
import mame_conditions as conditions  # noqa: E402
import mame_console as mconsole  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_docs as mdocs  # noqa: E402
import mame_envelope as menvelope  # noqa: E402
import mame_files as files  # noqa: E402
import mame_inputs as inputs
import mame_launch as launch
import mame_lists as mlists  # noqa: E402
import mame_machine as machine  # noqa: E402
import mame_mcp  # noqa: E402
import mame_read as read  # noqa: E402
import mame_running as running  # noqa: E402
import mame_scan as mscan  # noqa: E402
import mame_session as msession
import mame_state as mstate  # noqa: E402
import mame_stub_owner as owner  # noqa: E402
import mame_summaries as summaries  # noqa: E402
import mame_watches as watches  # noqa: E402
import mame_write as mwrite  # noqa: E402
import server as s  # noqa: E402


def _wait_emulator(ses: Any, scratch: Path, alive: Any, on_stop: Any, pattern: str,
                   seconds: float, progress: Any = mprogress.no_progress) -> dict[str, Any]:
    """`files.log_wait` on the emulator channel, positional as these tests wrote it."""
    return files.log_wait(ses, scratch, alive, on_stop, pattern, seconds, "emulator", progress)


def _install(monkeypatch: pytest.MonkeyPatch, ses: Any, tmp_path: Path) -> None:
    """Install `ses` as the live session with a scratch under `tmp_path`: the gate every tool
    goes through asks for both, because a stop survey writes its listing into the scratch."""
    monkeypatch.setattr(mstate.STATE, "alive", lambda: ses)
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path)
    # No stop is on record for a session a test installs, so the first contact surveys
    # nothing; a record left by an earlier test would make it survey a stop that is not this
    # double's.
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    monkeypatch.setattr(mstate.STATE, "errorlog_mark", 0)
    monkeypatch.setattr(mstate.STATE, "found_stop_last", {})
    # What `start` creates beside every session: a store (session-lived here), the stamp
    # and the controls table, so a tool that declares (`run_to` with a `control`) works on
    # any installed double.
    monkeypatch.setattr(mstate.STATE, "store", dec.DeclarationStore("test", path=None))
    monkeypatch.setattr(mstate.STATE, "session_origin", "s1")
    monkeypatch.setattr(mstate.STATE, "first_cpu", ":maincpu")      # the doubles' first cpu
    monkeypatch.setattr(mstate.STATE, "fingerprints", {":maincpu": "fp-test"})
    monkeypatch.setattr(mstate.STATE, "controls", {})


@pytest.mark.parametrize(
    "command",
    # EVERY SPELLING MAME'S CONSOLE RESOLVES (src/emu/debug/debugcmd.cpp): a command, its alias,
    # and a unique prefix of it (`softr`), which the console runs as the command itself.
    ["fill 0x1000,1,0", "filld 0,1,0", "softreset", "softr", "hardreset", "g", "step", "n",
     "over", "o", "load x,0,10", "loadr x,0,0,:gfx", "stateload s", "sl s", "gtime 100",
     "gvblank", "gint 3", "rewind", "rw", "mount cart x", "suspend 1",
     # A bare ASSIGNMENT is how the console writes a register or a byte without any command
     # word: its own parser treats a one-parameter line holding `=`, `++` or `--` as an
     # expression to execute, so a prefix list alone could never see it.
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
    """ONE DECISION, TWO CONSUMERS: what the console counts as an assignment refuses a
    breakpoint CONDITION and marks a `debug` line as mutating. The day `+=` or `|=` has to
    count differently, both must move together, or a condition slips a write past the refusal
    that `debug` would have flagged. The inputs are ones only the assignment rule decides."""
    try:
        conditions.check_condition(text)
        refused_as_condition = False
    except mstate.Invalid:
        refused_as_condition = True
    marked_as_line = mconsole.mutates(text)
    assert (refused_as_condition, marked_as_line) == (assigns, assigns), text


# EVERY OPERATOR THAT WRITES in MAME's expression parser, read from its lexer
# (`src/emu/debug/express.cpp`, `parse_string_into_tokens`): the eleven `TVL_ASSIGN*` and the
# two steps, `TVL_PLUSPLUS` and `TVL_MINUSMINUS`. Listed whole, so an operator the rule misses
# fails by its own name rather than hiding behind the ones it happens to catch.
MAME_ASSIGNMENTS = ["=", "*=", "/=", "%=", "+=", "-=", "<<=", ">>=", "&=", "^=", "|=", "++", "--"]


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
    """`mame_lexer.without_temp_writes` says why a temp alone is not a write; a chain that
    reaches memory or a register, an action in braces, and a second command after a `;`
    still write."""
    assert mconsole.mutates(command) is mutates, command


def test_a_condition_still_refuses_a_temp_the_debug_line_does_not_mark() -> None:
    """THE ONE PLACE THE TWO CONSUMERS DIFFER, on purpose: a condition that writes a temp
    would change a control's count at every hit, so it is refused; the same text typed
    through `debug` touches nothing of the guest."""
    with pytest.raises(mstate.Invalid):
        conditions.check_condition("(++temp3)==0")
    assert mconsole.mutates("(++temp3)==0") is False


def test_altered_counts_both_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Protocol writes and console writes go into the SAME counter."""
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "console_writes", 0)
    assert menvelope.session_block()["altered"] is False
    monkeypatch.setattr(mstate.STATE, "console_writes", 1)
    block = menvelope.session_block()
    assert block["altered"] is True
    assert menvelope.session_block(True)["altering_writes"] == 1
    assert block["omitted"] == ["altering_writes", "console"]
    assert "MODIFIED" in block["note"]
    assert list(menvelope.envelope({})) == ["status"], "the boundary adds the block, once"


def test_a_softreset_whose_step_fails_is_counted_as_the_write_it_may_have_been() -> None:
    """The console's `softreset` is a timer the next step fires: a step that fails leaves the
    reset scheduled, and a write the counter missed is `altered: false` on a machine that no
    longer runs the game from where it was."""
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


def test_starts_fine_without_the_window_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing OPTIONAL helper must not take the start down, which a raise would."""
    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "does-not-exist"))
    flags = launch.window_flags(shared=False)
    assert "-window" in flags and "-nomaximize" in flags


def test_a_shared_session_without_the_helper_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """And here NO geometry is invented: without knowing where the screen is, the window is lost."""
    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "does-not-exist"))
    with pytest.raises(mstate.Invalid, match="geometry"):
        launch.window_flags(shared=True)


def test_a_helper_that_is_there_but_not_executable_does_not_take_start_down(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE THIRD STATE, and `exists()` could not see it.

    The helper is reached through a SYMLINK. A checkout that did not materialise it leaves a
    short text file, mode 644, no shebang, where the program should be -- and that is neither
    "absent" nor "working". A guard of `helper.exists()` answers True here, and
    `subprocess.run` then raises PermissionError: an OSError, which `check=False` does NOT
    suppress, so the whole of `start` comes down. Both cases above test only the ABSENT state.
    """
    fake = tmp_path / "place-window"
    fake.write_text("place-window.sh")          # what an unmaterialised symlink looks like
    fake.chmod(0o644)
    monkeypatch.setenv("WINDOW_APP", str(fake))
    flags = launch.window_flags(shared=False)
    assert "-window" in flags and "-nomaximize" in flags


def test_a_shared_session_refuses_on_a_helper_that_is_not_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """And the shared path still refuses rather than inventing a size, for the same reason."""
    fake = tmp_path / "place-window"
    fake.write_text("place-window.sh")
    fake.chmod(0o644)
    monkeypatch.setenv("WINDOW_APP", str(fake))
    with pytest.raises(mstate.Invalid, match="geometry"):
        launch.window_flags(shared=True)


def test_a_helper_that_cannot_be_executed_at_all_is_caught_rather_than_raised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The state the exec bit cannot rule out: executable, and still impossible to run.

    A symlink that DID materialise, onto a `.sh` whose interpreter is not on this machine,
    passes both `is_file()` and `os.access(X_OK)` and then fails inside `execve`. That is an
    OSError too, and `check=False` does not suppress it either, so the guard alone is not
    enough and the call needs its own `except`.
    """
    fake = tmp_path / "place-window"
    fake.write_text("#!/nonexistent/interpreter\necho hi\n")
    fake.chmod(0o755)
    monkeypatch.setenv("WINDOW_APP", str(fake))
    flags = launch.window_flags(shared=False)
    assert "-window" in flags and "-nomaximize" in flags


def test_with_no_window_app_no_helper_is_looked_for_anywhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`WINDOW_APP` is the only route to a window helper: unset, none is run, wherever one might
    sit beside the package, so a clone reads the same on every machine. A quick start takes the
    default flags; a shared one refuses as `host_failed`, naming the variable that would fix it.
    A working helper is planted where a default could have pointed, so a default that survived
    would answer with its flags instead of refusing."""
    planted = tmp_path / "place-window.sh"
    planted.write_text('#!/bin/sh\nprintf -- "-window\\n-planted\\n"\n')
    planted.chmod(0o755)
    monkeypatch.delenv("WINDOW_APP", raising=False)
    monkeypatch.setattr(launch, "WINDOW_HELPER", planted, raising=False)
    ran: list[list[str]] = []
    real_run = subprocess.run

    def recorded(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        ran.append(cmd)
        return real_run(cmd, **kw)

    # BY BEHAVIOUR, not by a name: whatever a default might be called, running it is the tell.
    monkeypatch.setattr(subprocess, "run", recorded)
    assert launch.window_flags(shared=False) == ["-window", "-nomaximize", "-resolution", "320x240"]
    assert ran == [], f"a helper ran with WINDOW_APP unset: {ran}"
    monkeypatch.setenv("WINDOW_APP", "   ")
    with pytest.raises(mstate.Invalid, match="WINDOW_APP is not set"):
        launch.window_flags(shared=True)
    monkeypatch.delenv("WINDOW_APP")
    with pytest.raises(mstate.Invalid) as refused:
        launch.window_flags(shared=True)
    assert refused.value.code == "host_failed", refused.value.code
    assert "WINDOW_APP is not set" in str(refused.value), str(refused.value)


def test_the_tools_are_serialized() -> None:
    """Two calls at once over ONE machine steal each other's breakpoint stops.

    The probe is REMOVED from the registry afterwards. `@mame_mcp.tool` registers into the real
    server, so without the cleanup this test left a tool named after itself in the live surface,
    and any assertion about that surface became order-dependent. Found by the roster gate below
    on its first run, which is what a roster gate is for.
    """
    order: list[str] = []

    @mame_mcp.tool("Slow probe", summary=lambda args, reply: "slow_probe: ok")
    def slow_probe() -> dict[str, str]:
        order.append("enter")
        threading.Event().wait(0.05)
        order.append("leave")
        return {"status": "ok"}

    threads = [threading.Thread(target=slow_probe) for _ in range(3)]
    for h in threads:
        h.start()
    for h in threads:
        h.join()
    # Serialized, entries and exits alternate. Without the lock, they overlap.
    assert order == ["enter", "leave"] * 3
    s.mcp._tool_manager.remove_tool("slow_probe")
    mame_mcp.BOUNDARY.summaries.pop("slow_probe", None)
    mame_mcp.BOUNDARY.bodies.pop("slow_probe", None)


def test_the_mame_line_carries_the_harness_and_the_port() -> None:
    cmd = launch.build_command(
        "/bin/mame", "wheelfir", "/roms", 23946, ["-window"], "/scratch/mame-mcp-t",
        boot_lua="/tmp/x.lua"
    )
    assert cmd[:2] == ["/bin/mame", "wheelfir"]
    assert "-debugger_port" in cmd and "23946" in cmd
    assert cmd[cmd.index("-autoboot_script") + 1] == "/tmp/x.lua"
    assert cmd[cmd.index("-autoboot_delay") + 1] == "0"


def test_startup_leaves_no_state_in_the_servers_directory() -> None:
    """MAME writes `cfg/` and `nvram/` into its cwd, and that cwd was the SHARED tool's own.

    One project's EEPROM ended up inside the server and the next project to use it inherited it.
    """
    here = Path(s.__file__).resolve().parent
    for leftover in ("cfg", "nvram"):
        assert not (here / leftover).exists(), (
            f"{leftover}/ inside the server: one project's state in a shared tool"
        )


def test_a_timeout_leaves_the_machine_stopped() -> None:
    """`run_to` must not hand back a session whose machine is still RUNNING.

    No unit test could see it because none of them touches the
    wire: after `resume` times out, the machine keeps running, and the very next memory read comes
    back as something that is not hex at all, because the stub will not serve `m` to a target
    that is not stopped. The session looks alive and answers garbage, which is the worst state
    a debug session can be in: it does not fail, it lies.

    Here the contract is pinned structurally, since the behaviour itself needs a live machine:
    the client must expose an interrupt, and `run_to` must call it on the TIMEOUT path before
    removing its breakpoints.
    """
    import inspect

    assert hasattr(g.Session, "interrupt"), "the client has no way to stop a running machine"
    src = inspect.getsource(advance._run_to)
    assert "interrupt()" in src, "run_to does not stop the machine it left running"
    assert src.index("interrupt()") < src.index("mclear.clear_command("), (
        "the breakpoints are removed before the machine is stopped, which is the same gamble"
    )


def test_the_server_declares_instructions_and_they_name_what_a_caller_needs() -> None:
    """The `instructions` field is how the PROTOCOL hands a session the server's own contract.

    It replaced a `SessionStart` hook that pasted equivalent prose by hand, and nothing asserted
    it: deleting the `instructions=` argument, or truncating it to "", left both suites green
    while every session lost the text. The failure direction was silence, which is what a
    compliant server looks like.

    It asserts the CLAIMS, not the wording, and the two it forbids are the two a text copied
    from the sibling server gets wrong: `rom_check` described with a sentence true there and
    false here, and the console reader told to take a `pattern` it does not have.
    """
    text = s.mcp.instructions
    assert text, "the server declares no instructions at all"
    # ABSENCE, not just presence. A presence assertion cannot say "and does not ALSO claim X",
    # so it passes against a text carrying the true sentence beside the false one.
    for phrase, why in (
        ("ToolSearch", "the deferred-tools rule is the session's own, loaded every session, "
                       "and it describes the CLIENT rather than this server"),
        ("haystack", "the generic 'ask narrowly' is the session's own rule too"),
        ("byte for byte", "rom_check reads 16 bytes at one address; 'byte for byte against the "
                          "ROM' is what a caller reads as the whole image"),
        ("wall-clock", "the MAME clock rule is the session's own"),
        ("flat out", "the MAME clock rule is the session's own"),
    ):
        assert phrase not in text, f"the instructions carry {phrase!r}: {why}"
    assert "reference_rom" in text, (
        "rom_check needs the reference ROM and the server does not remember it"
    )
    assert "reference_base" in text, (
        "a caller following the instructions with a raw V30 image is otherwise refused OUTSIDE"
    )
    # The tools that answer with a PATH, and only those: a caller told everything comes back in
    # the reply would read a file-returning tool as a broken one, and one told `log` returns a
    # path looks for a field its reply, which carries `lines`, does not have.
    # `series_capture` and `image_compare(method="region")` answer with a path too, and their own
    # descriptions say
    # so: the room went to saying the file tools answer in any state, which no description
    # placed after a refusal could.
    assert ("`memdump`, `snapshot` answer with a PATH"
            in " ".join(text.split())), "the instructions do not name the file-returning tools"
    assert "Files" in mame_mcp.ROSTER.answering_split()[0] and (
        mame_mcp.ROSTER.running_sentence() in " ".join(text.split())), (
        "a caller with the machine running would stop it before a file tool")
    assert "16 bytes" in text, "a spot check must not read as the whole image"
    assert "STOPPED" in text, (
        "rom_check is a memory read, and a read against a RUNNING machine does not come back as "
        "data: a caller told to run it after `monitor go` gets a transport error, from the one "
        "tool whose job is to say whether the instrument is honest"
    )


def test_every_tool_this_server_promises_is_actually_registered() -> None:
    """`mcp.tool()` returns the function unchanged, so dropping the registration leaves every
    ordinary test green while the server exposes NOTHING: no ordinary assertion can see that
    hole, which is why the MCP surface gets one of its own.

    The names are stated, not derived, because deriving them from the same object under test is
    how a roster proves itself: this list is the SECOND statement, and the comparison is the gate.
    """
    registered = sorted(t.name for t in s.mcp._tool_manager.list_tools())
    assert registered == sorted([
        "breakpoint_at", "declaration_clear", "declaration_list", "close", "debug", "disassemble",
        "focus", "cpu_info", "input", "log", "log_wait", "lua", "find", "history", "machine_map",
        "memdump",
        "perform", "perform_export", "palette", "screen_view", "gfx_view", "gfx_locate",
        "gfx_load", "gfx_blits",
        "gfx_blit_source", "palette_log", "gfx_film", "gfx_sweep", "gfx_draft",
        "screen_signature", "drive", "series_capture",
        "image_compare", "audio_compare", "map_find", "map_write",
        "read_memory", "read_block", "record", "audio_record", "registers", "regpoint_add",
        "reset", "resume", "run_for", "trace", "comment_list", "comment_write",
        "run_to",
        "captures", "rom_check", "set_register", "snapshot", "start", "state_list", "state_write",
        "status",
        "step", "stop", "symbols_find", "throttle", "watch_add",
        "write", "scan",
    ]), f"the registered surface changed: {registered}"


# ------------------------------------------------- what a start refuses before anything exists


def test_a_missing_rom_directory_is_refused_before_the_emulator_is_spawned(
        tmp_path: Path) -> None:
    """A missing ROM directory is the worst shaped failure if it reaches MAME: it starts
    without its ROMs, the gdbstub never listens, and the caller waits the whole `seconds` to be
    told the STUB did not answer. The refusal names the argument, and nothing is spawned."""
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    refused("no such ROM directory",
    s.start(binary=str(binary), system="none", rompath=str(tmp_path / "run" / "mame_roms"),
            reference_rom=str(rom), boot_seconds=0.2))
    assert mstate.STATE.proc is None, "a refused start spawned something"


def test_a_missing_symbol_file_is_refused_before_the_emulator_is_spawned(tmp_path: Path) -> None:
    """IT WAS THE ONE PATH NOT CHECKED UP FRONT, and the cost was not cosmetic: it was read
    after MAME had been launched and the ROM verified, so a typo surfaced as a bare OSError
    from deep inside and left a running emulator nobody owned. Refusing here means there is
    nothing to clean up."""
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    refused("no such symbol file",
    s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(rom), symbols=str(tmp_path / "absent.sym"),
    ))


def test_a_missing_reference_rom_is_refused_too(tmp_path: Path) -> None:
    """The control for the case above: the neighbouring check still refuses as it should."""
    binary = fake_mame(tmp_path)
    refused("no such reference ROM",
    s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(tmp_path / "absent.bin"),
    ))


def _never_spawns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Whatever `start` does past its checks, it may not reach the emulator in these cases.

    The window helper is pointed at nothing first: `subprocess.run` is `Popen` underneath, so
    without that the sentinel fires on the helper call and blames the emulator for it.
    """
    import subprocess

    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "no-helper"))

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("start SPAWNED the emulator on an input it should have refused")

    monkeypatch.setattr(subprocess, "Popen", boom)


@pytest.mark.parametrize(("argument", "refusal"), [
    ("binary", r"MAME binary resolves from the argument rung: .*\(a directory\)"),
    ("reference_rom", "no such reference ROM"),
    ("symbols", "no such symbol file"),
    ("boot_lua", "no such boot harness"),
    ("cfg", "no such cfg"),
])
def test_a_directory_where_a_file_is_due_is_refused_naming_the_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argument: str, refusal: str
) -> None:
    """Each of the five path arguments refuses a DIRECTORY, at the argument and before
    anything is spawned. The reason `is_file()` is the check and not `exists()` lives with the
    check, in `mame_launch.judge`, and for `binary` in the ladder (`mame_binary`), which says
    why the path it was given is no executable; what this pins is that every one asks it."""
    _never_spawns(monkeypatch, tmp_path)
    folder = tmp_path / "a-directory-not-a-file"
    folder.mkdir()
    args: dict[str, Any] = {**_boot_args(tmp_path, bytes(16)), argument: str(folder)}
    refused(refusal, s.start(**args))
    assert mstate.STATE.proc is None, "a refused start spawned something"


def test_a_binary_that_is_a_file_and_cannot_be_run_is_refused_as_such(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The other half of the binary's check, and the reason it is two sentences and not one:
    a file that is there and has no exec bit is not missing, and telling its owner "no such
    MAME binary" would send them looking for a path that is exactly where they put it."""
    _never_spawns(monkeypatch, tmp_path)
    args = _boot_args(tmp_path, bytes(16))
    unrunnable = tmp_path / "not-a-program"
    unrunnable.write_text("#!/bin/sh\nexit 0\n")
    unrunnable.chmod(0o644)
    refused(r"\(not executable\)", s.start(**{**args, "binary": str(unrunnable)}))


def test_a_map_class_with_no_base_refuses_start_before_the_emulator_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reading the symbol file AFTER the boot and the ROM check makes a refusal here cost a
    whole boot (the guard does kill the process) to say what the file already said.
    Every input is judged before anything exists."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    sym = tmp_path / "game.map"
    sym.write_text("_start\tED000\t_TEXT\t0\tCODE\nstack\t2B000\t_STACK\t0\tSTACK\n")
    out = refused("STACK", s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(rom), symbols=str(sym), bases={"DATA": "0x400"},
    ))
    assert out["code"] == "bad_argument" and out["message"].startswith("symbols: "), out


def test_bases_beside_a_yaml_file_refuse_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    sym = tmp_path / "s.yaml"
    sym.write_text("- addr: 16\n  name: first\n")
    out = refused("YAML|yaml", s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(rom), symbols=str(sym), bases={"DATA": "0x400"},
    ))
    assert out["code"] == "bad_argument" and "bases" in out["message"], out


def test_a_bases_value_of_rom_means_the_class_stays_at_its_linear_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The word `rom` where a hex base would go: the class is ROM-resident and runs where the
    map says. Spelled at the boundary, so a caller never computes `linear - offset` to say it."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    sym = tmp_path / "game.map"
    sym.write_text("_start\tED000\t_TEXT\t0\tCODE\njuke\t60000\tJUKE\t0\tV30_JUKEBOX\n")
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym), bases={"V30_JUKEBOX": "rom"})
    try:
        assert out["symbols_total"] == 2
        assert out["symbols_by_class"] == {"CODE": 1, "V30_JUKEBOX": 1}
        assert mstate.STATE.resolve("juke") == 0x60000
    finally:
        s.close()


def test_a_bases_value_that_is_not_hex_refuses_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`bases` values are hex strings like `reference_addr`; one that is not is the caller's."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    sym = tmp_path / "game.map"
    sym.write_text("_start\tED000\t_TEXT\t0\tCODE\n")
    refused("DATA", s.start(
            binary=str(binary), system="none", rompath=str(tmp_path),
            reference_rom=str(rom), symbols=str(sym), bases={"DATA": "0x4zz"},
        ))


def test_bases_with_no_symbol_file_refuse_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `bases` with nothing to apply it to is a parameter honoured by nothing, and it is the
    CALLER's: it was the one refusal of `judge` raised as a bare ValueError, which the tool
    wrapper does not translate, so it escaped as an execution failure where every neighbour
    answers `bad_argument` in the envelope."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    out = refused("no `symbols`", s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(rom), bases={"DATA": "0x400"},
    ))
    assert out["code"] == "bad_argument"
    assert mstate.STATE.proc is None, "a refused start spawned something"


def test_a_reference_address_outside_the_image_refuses_start_before_the_emulator_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The window is a function of the file's LENGTH and three numbers; asked only once the
    machine is up, a raw V30 image with the wrong base pays a whole boot to be told OUTSIDE.
    The same goes for a `reference_addr` that is not hex."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "raw.bin"
    rom.write_bytes(bytes(64))
    common = dict(binary=str(binary), system="none", rompath=str(tmp_path), reference_rom=str(rom))
    refused("OUTSIDE", s.start(reference_addr="0x20010", **common))
    refused("reference_addr", s.start(reference_addr="0x4zz", **common))
    refused("reference_base", s.start(reference_addr="0x10", reference_base="-20000", **common))


def test_the_spawn_sentinel_can_fire(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The red control for every `_never_spawns` case above: with inputs that pass every check,
    `start` DOES reach the emulator, and the sentinel says so. Without this, a refusal arriving
    for any reason at all would satisfy those tests, and they would prove nothing about ORDER."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    with pytest.raises(AssertionError, match="SPAWNED"):
        s.start(
            binary=str(binary), system="none", rompath=str(tmp_path),
            reference_rom=str(rom), reference_addr="0x10",
        )
    # And a spawn that raises leaves nothing behind: the scratch was made and is gone again.
    assert mstate.STATE.scratch is None and mstate.STATE.port == 0 and mstate.STATE.state_dir == ""


# ------------------------------------------------- the reference image and its base


# The debugger's banner as `tests/fixtures/console/session.volume.stdout` captured it.
BANNER_LINE = launch.DEBUGGER_BANNER + "m68k-dual (m68k-dual)\n"


class _StubProcess:
    """What `start` gets back from `Popen`: alive until killed, with a pid, and nothing else."""

    PID = 4242
    last_argv: list[str] = []  # what the most recent `Popen` was handed, for the argv tests
    last_kwargs: dict[str, Any] = {}

    def __init__(self, *a: object, **k: object) -> None:
        self.killed = False
        self.pid = self.PID
        argv = a[0] if a else k.get("args")
        assert isinstance(argv, list)
        _StubProcess.last_argv = list(argv)
        _StubProcess.last_kwargs = dict(k)
        # The banner every MAME under `-debug` prints, as the console fixtures captured it.
        out = k.get("stdout")
        assert isinstance(out, io.BufferedIOBase), "`boot` hands MAME a file for its output"
        out.write(BANNER_LINE.encode())
        out.flush()

    def poll(self) -> int | None:
        return 1 if self.killed else None

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return 1


def _stub_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, image: bytes, at: int
) -> g.Session:
    """Everything `start` needs to run its happy path with no emulator: a helper that is not
    there (small-window defaults), a `Popen` that returns `_StubProcess`, and a REAL `Session`
    serving `image` at `at` whose wire-touching methods are stubbed."""
    import subprocess

    ses = reading_session(image, at)
    ses.dial = lambda: None  # type: ignore[method-assign]
    ses.handshake = lambda timeout=None: None  # type: ignore[method-assign]
    ses._layouts[1] = g.Layout({}, 0, "", [])      # what that connect described: no register
    ses.current_pc = lambda: at  # type: ignore[method-assign]
    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "no-helper"))
    real_popen = subprocess.Popen

    # Only the EMULATOR is stubbed, and what makes an invocation the emulator is `-debugger`,
    # not the binary's name. `_window_flags` reaches the helper through `subprocess.run`, which
    # is `Popen` underneath, and a test that points `WINDOW_APP` at a recording double needs
    # that one to really run; `start` asks the SAME binary `-listxml` before it boots, and
    # that one has to really run too, or the double answers for a question it was not built
    # for (it has no context manager, which is what `subprocess.run` needs).
    def popen(*a: Any, **k: Any) -> Any:
        argv = a[0] if a else k["args"]
        if str(argv[0]).endswith("fake-mame") and "-debugger" in argv:
            return _StubProcess(*a, **k)
        return real_popen(*a, **k)

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(g, "Session", lambda port, owner=None: ses)
    return ses


def _boot_args(tmp_path: Path, image: bytes) -> dict[str, Any]:
    """The `start` arguments that pass every check against a `_stub_boot` session serving
    `image` at address 0 (the defaults for `reference_addr` and `reference_base`)."""
    binary = fake_mame(tmp_path)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(image)
    return dict(binary=str(binary), system="m68k", rompath=str(tmp_path), reference_rom=str(rom))


def test_start_checks_the_image_at_its_base_and_reports_the_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The happy path of `start`, which no test read before: the base reaches the comparison
    (a raw image placed at 0x20000 passes), the parsed `bases` reach the table (a DATA row
    resolves to base + offset, in HEX), and the reply carries the table's shape. Delete
    `base=` from the `rom_check` call, or read `bases` in decimal, and this goes red."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0x20000)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "raw.bin"
    rom.write_bytes(image)
    sym = tmp_path / "game.map"
    sym.write_text("_start\tED000\t_TEXT\t0\tCODE\ndemo_count\t2A007\t_DATA\tA007\tDATA\n")
    out = s.start(
        binary=str(binary), system="v30", rompath=str(tmp_path), reference_rom=str(rom),
        reference_addr="0x20010", reference_base="0x20000", symbols=str(sym),
        bases={"DATA": "0x400"},
    )
    try:
        assert out["rom_check"] == "OK"
        assert out["symbols_total"] == 2
        assert out["symbols_format"] == "tsv"
        assert out["symbols_by_class"] == {"CODE": 1, "DATA": 1}
        assert mstate.STATE.resolve("demo_count") == 0x400 + 0xA007
        assert mstate.STATE.resolve("_start") == 0xED000
    finally:
        s.close()
    dead = s.status()
    assert dead["session"]["alive"] is False
    assert list(dead)[0] == "summary" and dead["summary"] == "status: no machine"


def test_start_on_a_machine_that_does_not_hold_the_rom_is_refused_in_the_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The known-answer check failing is a VERDICT about the machine, answered in the reply
    shape every `start` has (`start_retries` included), never an execution failure; and the
    session it refused is gone."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, bytes(64), at=0)       # the machine serves zeros
    out = s.start(**_boot_args(tmp_path, image))
    assert out["status"] == "INVALID" and out["code"] == "readback_refused", out
    assert "LIES" in out["message"] and out.get("start_retries", []) == [], out
    assert list(out)[-1] == "session" and s.status()["session"]["alive"] is False


def test_start_without_a_symbol_file_reports_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The third value of `symbols_format`, which the reader never produces and the server
    does: no file given is not a YAML file with nothing in it."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    out = s.start(**_boot_args(tmp_path, image))
    try:
        assert out["symbols_total"] == 0
        assert out["symbols_format"] == "none"
        assert out["symbols_by_class"] == {}
    finally:
        s.close()


def test_start_and_status_say_the_machine_runs_under_the_debugger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`start` and `status` say which debugger the machine runs under, the one the command
    line attaches, with a note that a capture taken through this session's stops can land a
    frame away from an autoboot golden, so a comparison across the two methods is not read as
    a regression."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    out = s.start(**_boot_args(tmp_path, image))
    try:
        debugger = out["debugger"]
        assert set(debugger) == {"attached", "note"}, debugger
        argv = launch.build_command("mame", "m68k", "/r", 1, [], str(tmp_path))
        assert argv[argv.index("-debugger") + 1] == debugger["attached"] == "gdbstub"
        assert "-debug" in argv and "frame" in debugger["note"], debugger["note"]
        # An autoboot capture is byte-identical with and without `-debug
        # -debugger gdbstub`, and one frame either side is not, so the note may not blame the
        # debugger for the frame; what differs is where in the frame each method takes it.
        assert "timing" not in debugger["note"] and "autoboot" in debugger["note"]
        assert s.status()["debugger"] == debugger, "one fact, one shape, in both replies"
    finally:
        s.close()
    assert "debugger" not in s.status(), "no machine, nothing attached"


def test_rom_check_takes_the_reference_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The tool passes the base through to the comparison, so a raw linker image works. It IS
    the base that makes the difference: the case below, same image and address, no base,
    is refused."""
    ses = reading_session(bytes(range(64)), 0x20000)
    _install(monkeypatch, ses, tmp_path)
    rom = tmp_path / "raw.bin"
    rom.write_bytes(bytes(range(64)))
    monkeypatch.setattr(ses, "cost_per_query", lambda *_a, **_k: 0.0012345678, raising=False)
    out = s.rom_check(reference_rom=str(rom), reference_addr="0x20010", reference_base="0x20000")
    assert out["rom_check"] == "OK"
    assert out["query_s"] == 0.001235, "the cost of one query, in seconds, to the microsecond"


def test_rom_check_without_the_base_indexes_the_file_as_cpu_space(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The control: the default base is zero, so a raw image the board places elsewhere is
    refused as OUTSIDE rather than compared at the wrong offset, and refused as an ARGUMENT,
    in the envelope, the way `start` refuses it."""
    ses = reading_session(bytes(range(64)), 0x20000)
    _install(monkeypatch, ses, tmp_path)
    rom = tmp_path / "raw.bin"
    rom.write_bytes(bytes(range(64)))
    got = s.rom_check(reference_rom=str(rom), reference_addr="0x20010")
    assert got["code"] == "bad_argument" and "OUTSIDE" in got["message"], got


# ------------------------------------------------------ a write says whether the bytes landed


class _FakeSession(SessionFields):
    """A tiny addressed memory that accepts writes, and a `writable` switch to model ROM.

    IT HOLDS STATE ON PURPOSE, which is the whole point of this double. One answering `read`
    from a constant slice, ignoring `addr` and unaffected by `write`, lets `verified` be
    decided by the fixture and never by the write: the tool's write can then be replaced by
    `pass` and the cases below still pass. A double that cannot reproduce the property under
    test (read after write sees what was written) turns its cases into decoration.

    `writable=False` is how a ROM address is modelled: the write is accepted and sent,
    exactly as a real stub accepts it, and the memory simply does not change. That is the
    real board's behaviour and the reason the tool reads back at all.
    """

    def __init__(self, holds: bytes, *, writable: bool = True) -> None:
        self.mem = bytearray(holds)
        self.base = 0
        self.writable = writable
        self.written: tuple[int, bytes] | None = None
        self.writes = 0
        self.threads: dict[int, str] = {}

    def write(self, addr: int, data: bytes, *, thread: int) -> None:
        self.written = (addr, data)
        self.writes += 1
        if self.writable:
            self.base = addr
            self.mem = bytearray(data)

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        if self.writable and addr != self.base:
            return bytes(n)          # nothing was ever written here
        return bytes(self.mem[:n])

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        """`map` as the console answers it: ROM when the double models ROM, RAM otherwise, and
        `cpulist` as the two-cpu board answers it, which a reply reads to name its cpu."""
        if command == "cpulist":
            return captured("cpulist.main-visible.txt")
        assert command.startswith("map "), f"this double's console answers only `map`: {command}"
        return MAP_RAM if self.writable else MAP_ROM


def test_a_write_that_lands_reports_verified(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    fake = _FakeSession(bytes.fromhex("aa55aa55"))
    _install(monkeypatch, fake, tmp_path)
    out = s.write("0x1000", "aa55aa55")
    assert out["verified"] is True
    assert out["readback"] == "aa55aa55"
    assert out["addr"] == "0x00001000" and out["bytes_written"] == 4, out
    # The readback must come from the ADDRESS that was written, not from wherever the tool
    # happened to look: a readback aimed one address over would otherwise stay green.
    assert fake.written == (0x1000, bytes.fromhex("aa55aa55"))


def test_a_write_that_goes_nowhere_says_so(monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path) -> None:
    """THE REGRESSION THIS EXISTS FOR: answering `written: 4` and nothing else reports a count
    of what was SENT. On a real 68000 board a write to ROM comes back with that
    same `written: 4` while the memory still holds its old bytes."""
    fake = _FakeSession(bytes.fromhex("7ffff3ff"), writable=False)
    _install(monkeypatch, fake, tmp_path)
    monkeypatch.setattr(mstate.STATE, "machine_map", {})
    out = s.write("0x20000", "aa55aa55")
    assert out["verified"] is False
    assert out["readback"] == "7ffff3ff"
    assert out["bytes_written"] == 4, "it still reports what was attempted"
    # `written` is the tool echoing len(data), so it proves nothing on its own: this is what
    # pins that the write was ATTEMPTED against the right address. Without it, deleting the
    # write from the tool leaves this case green -- a ROM readback is unchanged either way.
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


class _DroppingWire:
    """A socket whose stub DROPS everything, as MAME's does a packet past its size: whatever is
    sent is recorded and no answer ever comes."""

    def __init__(self, answers: tuple[str, ...] = ()) -> None:
        self.sent: list[bytes] = []
        self.answers = [f"${a}#{g._checksum(a)}".encode() for a in answers]

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def settimeout(self, seconds: float) -> None:
        pass

    def recv(self, n: int) -> bytes:
        if self.answers:
            return self.answers.pop(0)
        raise TimeoutError


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


def test_a_go_command_too_long_to_send_leaves_the_machine_stopped_and_no_run_window(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A go-family command reads the emulated clock to open its run window before it is sent;
    refused as too long, it is refused before that read too, so nothing at all reaches the
    stub, the session is not marked running and no window is opened."""
    ses = g.Session(timeout=0.2)
    wire = _DroppingWire(answers=(b"1.0".hex(),))     # the console's `time`, never asked
    ses._sock = wire  # type: ignore[assignment]
    ses.packet_size = 0x40
    _install(monkeypatch, ses, tmp_path)
    out = s.debug("gtime " + "1" * 40)
    assert out["code"] == "bad_argument", out
    assert ses.running is False and mstate.STATE.console_run is False
    assert mstate.STATE.run_release is None
    assert wire.sent == [], wire.sent


def test_a_reader_too_long_to_send_leaves_an_open_run_window_alone(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A refusal belongs to its own command: a window a console run opened earlier, not yet
    closed by the stop that ends it, survives an unrelated command refused as too long."""
    ses = g.Session(timeout=0.2)
    ses._sock = _DroppingWire()  # type: ignore[assignment]
    ses.packet_size = 0x40
    _install(monkeypatch, ses, tmp_path)
    window = {"emulated": 1.0, "wall": 2.0}
    monkeypatch.setattr(mstate.STATE, "run_release", window)
    assert s.debug("print " + "1" * 40)["code"] == "bad_argument"
    assert mstate.STATE.run_release is window


# ------------------------------------------------- the start contract: argv mark, display, port


def test_the_command_line_carries_the_mark_and_its_directories(tmp_path: Path) -> None:
    """A repo's own `make stop` kills by binary path, and a live session's MAME is the same
    binary: the ONLY thing that tells them apart is the argv. The scratch directory is unique
    already; putting it on the command line, on the flag that points the console's `snap` at
    the scratch, is what a `ps | awk` in another repo can exclude. `cfg/` and `nvram/` go where
    the caller's state lives: the scratch by default, a `state_dir` when one is given."""
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}abc"
    cmd = launch.build_command("/bin/mame", "m68k-dual", "/roms", 23946, ["-window"], str(scratch))
    snap = Path(cmd[cmd.index("-snapshot_directory") + 1])
    assert snap == scratch / "snap"
    assert snap.parent.name.startswith(launch.SCRATCH_PREFIX), "the mark is the scratch's own name"
    assert cmd[cmd.index("-cfg_directory") + 1] == str(scratch / "cfg")
    assert cmd[cmd.index("-nvram_directory") + 1] == str(scratch / "nvram")

    state = tmp_path / "state"
    cmd = launch.build_command(
        "/bin/mame", "m68k-dual", "/roms", 23946, ["-window"], str(scratch), state_dir=str(state)
    )
    assert cmd[cmd.index("-snapshot_directory") + 1] == str(scratch / "snap"), (
        "snapshots stay in the scratch: they are this session's output, not the game's state"
    )
    assert cmd[cmd.index("-cfg_directory") + 1] == str(state / "cfg")
    assert cmd[cmd.index("-nvram_directory") + 1] == str(state / "nvram")
    assert launch.SCRATCH_PREFIX == "mame-mcp-", "the mark is a contract other repos exclude on"


def test_a_display_on_a_quick_run_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The helper ignores `--display` without `--shared`, out loud on stderr, which a caller of
    this server never sees: a parameter that silently does nothing is refused here instead."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    refused("nobody watches",
    s.start(
        binary=str(binary), system="none", rompath=str(tmp_path), reference_rom=str(rom),
        display="main",
    ))


def test_an_unknown_display_is_refused_before_the_helper_is_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The helper exits 1 on a bad value, and `_window_flags` would then report that as "no
    geometry", blaming the helper for the caller's typo. Judged here, by name."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    e = refused("tv",
    s.start(
        binary=str(binary), system="none", rompath=str(tmp_path), reference_rom=str(rom),
        shared=True, display="tv",
    ))
    assert "main" in e["message"] and "secondary" in e["message"]


def _recording_helper(tmp_path: Path) -> tuple[Path, Path]:
    """A `place-window` double that records its argv and prints a plausible flag list.
    Returns the double's path (for `WINDOW_APP`) and the log it writes."""
    log = tmp_path / "argv.log"
    fake = tmp_path / "place-window.sh"
    fake.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\nprintf -- "-window\\n-nomaximize\\n"\n'
    )
    fake.chmod(0o755)
    return fake, log


def test_a_shared_session_hands_the_display_to_the_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The one place the display reaches the helper, spelled as the helper spells it."""
    fake, log = _recording_helper(tmp_path)
    monkeypatch.setenv("WINDOW_APP", str(fake))
    flags = launch.window_flags(shared=True, display="main")
    assert flags == ["-window", "-nomaximize"]
    assert log.read_text().split() == ["mame", "--shared", "--display", "main"]
    # The control: a quick run asks for nothing but the tool, and a shared one with no display
    # leaves the choice to the helper (the secondary, by default and not by law).
    launch.window_flags(shared=False)
    assert log.read_text().split() == ["mame"]
    launch.window_flags(shared=True)
    assert log.read_text().split() == ["mame", "--shared"]


def test_a_taken_port_is_refused_before_the_emulator_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A caller who names a port names it for a reason (a repo's own gdb client expects it),
    so a port somebody else holds is refused rather than silently swapped for a free one."""
    import socket as _s

    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    with _s.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        held = holder.getsockname()[1]
        refused(str(held),
        s.start(
            binary=str(binary), system="none", rompath=str(tmp_path),
            reference_rom=str(rom), stub_port=held,
        ))


def test_a_given_port_and_the_pid_are_used_and_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`start` and `status` say which process and which port this session is: what a repo's
    kill path or a second client needs, and what otherwise lives only in the server's
    memory."""
    import socket as _s

    with _s.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    out = s.start(**_boot_args(tmp_path, image), stub_port=free)
    try:
        assert out["stub_port"] == free
        assert out["pid"] == _StubProcess.PID
        argv = _StubProcess.last_argv
        assert argv[argv.index("-debugger_port") + 1] == str(free), "the argv carries it too"
        st = s.status()
        assert st["stub_port"] == free and st["pid"] == _StubProcess.PID
        assert st["scratch_dir"] == out["scratch_dir"] and st["state_dir"] == ""
    finally:
        s.close()


def test_a_state_dir_survives_close_and_the_scratch_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two session shapes in one parameter: no `state_dir` is today's fresh, disposable boot;
    a path is a persistent one whose `cfg/` and `nvram/` two passes can share, and which this
    server NEVER deletes because it did not create the decision to keep it."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    state = tmp_path / "state"
    out = s.start(**_boot_args(tmp_path, image), state_dir=str(state))
    scratch = Path(out["scratch_dir"])
    try:
        assert out["state_dir"] == str(state)
        assert (state / "cfg").is_dir() and (state / "nvram").is_dir()
        assert scratch.is_dir() and scratch.name.startswith(launch.SCRATCH_PREFIX)
        assert (scratch / "snap").is_dir()
        assert not (scratch / "cfg").exists(), "state went to the state_dir, not the scratch"
        assert s.status()["state_dir"] == str(state)
        # What reached MAME, not only what the server created: the argv names the same places.
        argv = _StubProcess.last_argv
        assert argv[argv.index("-cfg_directory") + 1] == str(state / "cfg")
        assert argv[argv.index("-nvram_directory") + 1] == str(state / "nvram")
        assert argv[argv.index("-snapshot_directory") + 1] == str(scratch / "snap")
        assert launch.SCRATCH_PREFIX in argv[argv.index("-snapshot_directory") + 1]
    finally:
        s.close()
    assert not scratch.exists(), "the scratch is this session's and dies with it"
    assert (state / "cfg").is_dir(), "the state_dir outlives the session"
    dead = s.status()
    assert dead["session"]["alive"] is False
    assert list(dead)[0] == "summary" and dead["summary"] == "status: no machine"
    # The second pass finds the first one's state, and a pre-existing state_dir is not an error.
    (state / "cfg" / "m68k.cfg").write_text("<mameconfig/>")
    again = s.start(**_boot_args(tmp_path, image), state_dir=str(state))
    try:
        assert again["state_dir"] == str(state)
        assert (state / "cfg" / "m68k.cfg").exists(), "the second session found the first's cfg"
    finally:
        s.close()


def test_a_shared_start_hands_the_display_to_the_helper_and_uses_its_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """At the level of `start`, not of `_window_flags`: revert the one line that passes
    `display` through and `_window_flags` alone would still pass its own test."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    fake, log = _recording_helper(tmp_path)
    monkeypatch.setenv("WINDOW_APP", str(fake))
    s.start(**_boot_args(tmp_path, image), shared=True, display="main")
    try:
        assert log.read_text().split() == ["mame", "--shared", "--display", "main"]
        assert "-nomaximize" in _StubProcess.last_argv, "the helper's flags reached MAME"
    finally:
        s.close()


def test_an_unknown_display_never_reaches_the_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The order pinned on purpose: the helper's log does not exist after the refusal."""
    _never_spawns(monkeypatch, tmp_path)
    fake, log = _recording_helper(tmp_path)
    monkeypatch.setenv("WINDOW_APP", str(fake))
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    refused("tv",
    s.start(
        binary=str(binary), system="none", rompath=str(tmp_path), reference_rom=str(rom),
        shared=True, display="tv",
    ))
    assert not log.exists(), "the helper was asked about a value already known to be wrong"


@pytest.mark.parametrize("port", [-1, 65536, 70000])
def test_a_port_outside_the_tcp_range_is_refused_not_overflowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, port: int
) -> None:
    """`socket.bind` answers OverflowError for these, which is not an OSError, so it escaped
    `_port_is_free` as the interpreter's own wording, after the live session was already gone."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    refused("port",
    s.start(
        binary=str(binary), system="none", rompath=str(tmp_path), reference_rom=str(rom),
        stub_port=port,
    ))


def test_a_relative_or_unusable_state_dir_is_refused_and_leaves_no_scratch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Relative, MAME would resolve it against ITS cwd (the scratch) and the persistent half
    would die with the session while this server created a stray copy under its own cwd. A
    file where a directory should be is the caller's, named as such, and neither refusal may
    leave a scratch directory behind."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    common = dict(binary=str(binary), system="none", rompath=str(tmp_path), reference_rom=str(rom))
    refused("must be an absolute path",
    s.start(state_dir="state", **common))
    a_file = tmp_path / "a-file"
    a_file.write_text("not a directory")
    e = refused("state_dir",
    s.start(state_dir=str(a_file), **common))
    assert "cfg" in e["message"] and e["code"] == "bad_argument", "the caller's, not the host's"
    assert "name a directory" in e["message"]
    assert mstate.STATE.scratch is None and mstate.STATE.state_dir == ""


class _RecordingSession(SessionFields):
    """A session that only records what `kill` asks of it."""

    def __init__(self, quit_raises: bool = False) -> None:
        self.events: list[str] = []
        self.quit_raises = quit_raises
        self.writes = 0
        self.running = False

    def quit(self) -> None:
        self.events.append("quit")
        if self.quit_raises:
            raise g.SessionError("the stub closed the connection")

    def close(self) -> None:
        self.events.append("close")


def _closing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exits: bool,
             code: int = 0) -> None:
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}tails"
    scratch.mkdir()
    (scratch / "stdout.log").write_text("bye\n")
    (scratch / "error.log").write_text("[luaengine] routine\n")
    monkeypatch.setattr(mstate.STATE, "scratch", scratch)
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=exits, code=code)  # type: ignore[assignment]


def test_a_clean_close_names_the_last_words_it_left_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _closing(monkeypatch, tmp_path, exits=True)
    closed = s.close()
    assert closed["ended_by"] == "quit" and closed["exit_code"] == 0, closed
    assert "stdout_tail" not in closed and "errorlog_tail" not in closed, closed
    assert closed["omitted"] == ["stdout_tail", "errorlog_tail"]
    assert closed["how"] == msession.CLOSE_HOW and "detail=True" in closed["how"]
    assert closed["summary"].endswith(", last words left out (see `omitted`)"), closed["summary"]


def test_a_quit_that_exits_nonzero_keeps_the_last_words_unasked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The crash on the way out MAME's Lua collector is known for: `quit` was taken, the code
    says something went wrong, and the words are what says what."""
    _closing(monkeypatch, tmp_path, exits=True, code=-11)
    closed = s.close()
    assert closed["ended_by"] == "quit" and closed["exit_code"] == -11, closed
    assert closed["stdout_tail"] == "bye\n" and "omitted" not in closed, closed


def test_a_close_that_had_to_kill_keeps_the_last_words_unasked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _closing(monkeypatch, tmp_path, exits=False)
    closed = s.close()
    assert closed["ended_by"] == "killed", closed
    assert closed["stdout_tail"] == "bye\n" and "omitted" not in closed, closed


class _ExitingProcess:
    """A process that exits when asked through `quit`, or never, and records the order."""

    pid = 99

    def __init__(self, events: list[str], exits: bool, code: int = 0) -> None:
        self.events, self.exits, self.gone, self.code = events, exits, False, code

    def poll(self) -> int | None:
        return self.code if self.gone else None

    def wait(self, timeout: float | None = None) -> int:
        import subprocess

        # One `wait` per stretch: the real wait is sliced so the line can be painted, and
        # the ORDER is what these events prove, not how many slices a stretch took.
        if self.events[-1:] != ["wait"]:
            self.events.append("wait")
        if self.exits or "kill" in self.events:
            self.gone = True
            return self.code
        raise subprocess.TimeoutExpired("mame", timeout or 0)

    def kill(self) -> None:
        self.events.append("kill")


def test_close_carries_the_tail_of_each_log_before_the_scratch_goes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`close` deletes the scratch, and with it the only record of what MAME printed last:
    a crash on the way out cannot be read through the server afterwards. The reply carries
    the tail of each channel, read BEFORE the kill, so the last words survive the
    directory."""
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}close"
    scratch.mkdir()
    (scratch / "stdout.log").write_text("boot\n" + "x" * 20 + "\nSegmentation fault\n")
    (scratch / "error.log").write_text("[luaengine] MAME_MCP_THROTTLE#1\n")
    monkeypatch.setattr(mstate.STATE, "scratch", scratch)
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    closed = s.close(detail=True)
    assert closed["ended_by"] == "quit" and "how" not in closed, closed
    assert "omitted" not in closed, closed
    assert closed["stdout_tail"].endswith("Segmentation fault\n"), closed["stdout_tail"]
    assert closed["errorlog_tail"] == "[luaengine] MAME_MCP_THROTTLE#1\n"
    assert not scratch.exists(), "the scratch still dies with the session"
    assert list(closed)[-1] == "session"
    none = s.close()
    assert none["closed"] is False and "stdout_tail" not in none, "no session, no log"


def test_the_instructions_warn_that_the_target_of_run_to_carries_no_stop_of_its_own() -> None:
    """Declaring a stop at X and then `run_to(ref=X)` is the natural order and is refused,
    rightly: one row per address. The refusal says so well; the instructions have to say it
    first, or a caller meets the rule only by tripping over it."""
    text = s.mcp.instructions or ""
    assert "run_to" in text and "no stop of its own" in text, "the sentence is missing"


def test_close_asks_mame_to_quit_before_it_kills() -> None:
    """MAME writes `cfg/` and `nvram/` on a CLEAN exit and ignores SIGTERM, so a session ended
    with SIGKILL leaves a persistent `state_dir` empty forever: a `close` followed
    by a second `start` on the same `state_dir` finds nothing to share. The console's `quit`
    is the clean exit, through the connection the server already holds."""
    ses = _RecordingSession(quit_raises=True)   # the connection drops as the process goes
    proc = _ExitingProcess(ses.events, exits=True)
    mstate.STATE.ses, mstate.STATE.proc = ses, proc  # type: ignore[assignment]
    closed = s.close()
    assert closed["closed"] is True and closed["session"]["alive"] is True, "as it was BEFORE"
    assert closed["ended_by"] == "quit" and closed["exit_code"] == 0 and "reap_failed" not in closed
    assert list(closed)[0] == "summary" and closed["summary"].startswith("close: quit, exit code 0")
    assert ses.events == ["quit", "wait", "close"], ses.events
    assert "kill" not in ses.events, "a clean exit needs no signal"
    assert mstate.STATE.ses is None and mstate.STATE.proc is None


def test_close_kills_a_machine_that_ignores_quit() -> None:
    """The grace period is a bound, not a promise: a stuck emulator does not hold `close`."""
    ses = _RecordingSession()
    proc = _ExitingProcess(ses.events, exits=False)
    mstate.STATE.ses, mstate.STATE.proc = ses, proc  # type: ignore[assignment]
    closed = s.close()
    assert ses.events == ["quit", "wait", "kill", "wait", "close"], ses.events
    assert proc.gone
    # THE TWO ENDINGS ARE TOLD APART: a clean quit writes `cfg/` and `nvram/`, a SIGKILL
    # does not, and `closed: true` alone said the same thing about both.
    assert closed["ended_by"] == "killed" and closed["exit_code"] == 0
    assert "reap_failed" not in closed
    assert closed["summary"] == "close: killed after the grace period, exit code 0"


class _UnreapableProcess(_ExitingProcess):
    """SIGKILLed and still not reaped within the second wait: what a wedged host does."""

    def wait(self, timeout: float | None = None) -> int:
        import subprocess

        self.events.append("wait")
        raise subprocess.TimeoutExpired("mame", timeout or 0)


def test_close_reports_a_kill_that_could_not_be_reaped_instead_of_raising() -> None:
    """The second `wait` after SIGKILL escaping as a traceback leaves the caller of `close`
    with neither a reply nor a session block. `exit_code` is unavailable, its `why` the
    reason, because there is nothing to read."""
    ses = _RecordingSession()
    proc = _UnreapableProcess(ses.events, exits=False)
    mstate.STATE.ses, mstate.STATE.proc = ses, proc  # type: ignore[assignment]
    closed = s.close()
    assert closed["ended_by"] == "killed" and closed["exit_code"]["available"] is False
    why = closed["exit_code"]["why"]
    assert "not reaped" in why and "99" in why and "reap_failed" not in closed, closed
    assert mstate.STATE.ses is None and mstate.STATE.proc is None
    assert "reap failed" in closed["summary"]


@pytest.mark.parametrize("which", ["session", "stdout_log"])
def test_kill_resets_the_state_even_when_a_close_raises(which: str) -> None:
    """`quit` is guarded and the scratch's removal ignores errors, but the two closes between
    them were not: a raise there skipped `_reset`, so the dead session's fields stood under an
    error about something else, and the original failure `start`'s guard was reporting was
    masked by it."""

    class _Raising:
        def close(self) -> None:
            raise OSError("close failed")

    ses = _RecordingSession()
    proc = _ExitingProcess(ses.events, exits=True)
    mstate.STATE.ses, mstate.STATE.proc = ses, proc  # type: ignore[assignment]
    mstate.STATE.system = "m68k-dual"
    if which == "session":
        ses.close = _Raising().close  # type: ignore[method-assign]
    else:
        mstate.STATE.stdout_log = _Raising()  # type: ignore[assignment]
    ended = mstate.STATE.kill()
    assert ended["ended_by"] == "quit"
    assert mstate.STATE.ses is None and mstate.STATE.proc is None
    assert mstate.STATE.stdout_log is None and mstate.STATE.system == ""


def test_close_with_no_session_says_so() -> None:
    """`closed: true` with nothing to close is a green about nothing, so the answer is
    `closed: false` with a note."""
    mstate.STATE.ses = mstate.STATE.proc = None
    closed = s.close()
    assert closed["closed"] is False and closed["ended_by"] == "none"
    assert "no session" in closed["note"]
    assert closed["summary"] == "close: no session"


# ------------------------------------------- outputs to files, and the result channels


def _masked(mask: int, cpu: str = ":maincpu") -> dict[str, Any]:
    """An inventory holding one cpu's program space and its address mask, as `start` caches it."""
    return {"spaces": [{"cpu": cpu, "space": "program", "address_mask": f"{mask:#010x}"}]}


class _ConsoleSession(SessionFields):
    """A session whose console answers from canned replies, and whose memory is `image`.

    A reply may be text, or a callable taking the command and returning text, so a fake `save`
    or `snap` can WRITE THE FILE the tool then checks: the property under test is the file the
    console produced, and a double that only answered "OK" could not exercise it.
    """

    def __init__(self, image: bytes = b"", replies: dict[str, Any] | None = None) -> None:
        self.image = image
        self.replies = replies or {}
        self.commands: list[str] = []
        self.writes = 0
        self.threads: dict[int, str] = {}

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        """The same image whichever thread reads it, a thread other than the first noted."""
        if thread != 1:
            self.commands.append(f"m@{thread}")
        return self.image[addr : addr + n]

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        self.commands.append(command)
        head = command.split()[0]
        reply = self.replies.get(head, "")
        return str(reply(command)) if callable(reply) else str(reply)


def _console(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ses: _ConsoleSession) -> Path:
    """Install `ses` as the live session and give the server a scratch under `tmp_path`."""
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}test"
    (scratch / "snap").mkdir(parents=True, exist_ok=True)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "scratch", scratch)
    monkeypatch.setattr(mstate.STATE, "snapshots", 0)
    monkeypatch.setattr(mstate.STATE, "debug_dumps", 0)
    return scratch


def test_a_read_above_the_ceiling_is_refused_and_names_memdump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A frame is 64000 bytes of VRAM; through `read` that is a hex string on the wire and again
    in the reply, two characters a byte and never compressed. The ceiling is on the bytes
    asked for, and the refusal names the tool that keeps them off the socket."""
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
    """Under `perform(summaries=True)` the summary line is all a read step keeps, and a
    `read_memory` cut to `2 bytes at 0x0020bd5c` cost a step and answered nothing. The line
    carries the bytes whole up to the ceiling; past it, the count left in `hex`, never a
    cut inside a byte."""
    image = bytes(range(256)) * 4
    _console(monkeypatch, tmp_path, _ConsoleSession(image))
    short = s.read_memory("0x2", length=2)
    assert short["summary"] == "read_memory 0x2: 2 bytes at 0x00000002: 0203", short["summary"]
    cap = summaries.HEX_BYTES_SHOWN
    long = s.read_memory("0x0", length=cap + 3)
    assert long["summary"].endswith(image[:cap].hex() + "... (3 more bytes in `hex`)"), (
        long["summary"])
    assert long["hex"] == image[:cap + 3].hex(), "the reply itself is never cut"


def test_a_long_console_answer_goes_to_a_file_and_the_envelope_stays(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The haystack goes to a file and the honesty envelope stays in front of the caller."""
    long = "\n".join(f"line {i}" for i in range(2000))
    assert len(long) > mwrite.DEBUG_MAX
    scratch = _console(monkeypatch, tmp_path, _ConsoleSession(replies={"help": long}))
    out = s.debug("help")
    assert out["clipped"] is True
    assert out["output"] == "line 0..."
    assert out["output_chars"] == len(long)
    path = Path(out["output_path"])
    assert path.parent == scratch and path.read_text() == long
    assert "altered" in out["session"] and "altering_writes" in out["session"]["omitted"]
    assert out["mutates"] is False
    short = s.debug("print pc")
    assert short["clipped"] is False and "output_path" not in short
    # A haystack with no newline must not ride back whole as its own "first line".
    ses = mstate.STATE.alive()
    ses.replies["find"] = "x" * 5000  # type: ignore[attr-defined]
    one_line = s.debug("find 0,ffff,00")
    assert one_line["clipped"] is True
    assert len(one_line["output"]) == mwrite.DEBUG_PREVIEW + 3
    assert Path(one_line["output_path"]).name == "debug-2.txt", "each clip its own file"
    # Exactly the ceiling is not above it.
    ses.replies["symlist"] = "y" * mwrite.DEBUG_MAX  # type: ignore[attr-defined]
    assert s.debug("symlist")["clipped"] is False


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
    refused("comma",
    s.memdump("0", length=16, dest=str(tmp_path / "a,b.bin")))
    refused("exists",
    s.memdump("0", length=16, dest=str(tmp_path)))
    assert ses.commands == [], "the console was touched on a refused input"


def test_a_semicolon_in_a_dest_is_refused_before_the_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The console ends a command at a `;` (`debugcon.cpp`), so a path holding one reaches it as
    the first command's broken parameter: refused as the caller's argument, naming the
    character, before any console line, and the same for every tool that takes a `dest`."""
    split = str(tmp_path / "a;b.bin")
    message = _refusal_text(inputs.fresh_dest, "dest", split)
    assert "semicolon" in message and "';'" in message, message
    # Anywhere in the value, inside brackets too, and the console's brackets themselves: an
    # unbalanced one stops the whole line before it runs, as late as the `;` did.
    for name, char in [(";a.bin", ";"), ("a.bin;", ";"), ("a(;)b.bin", "("), ("a(b.bin", "("),
                       ("a)b.bin", ")"), ("a[b.bin", "["), ("a]b.bin", "]"), ("a{b.bin", "{"),
                       ("a}b.bin", "}")]:
        said = _refusal_text(inputs.fresh_dest, "dest", str(tmp_path / name))
        assert f"{char!r}" in said, (name, said)
    ses = _ConsoleSession(bytes(64))
    _console(monkeypatch, tmp_path, ses)
    refused("semicolon",
    s.memdump("0", length=16, dest=split))
    refused("semicolon",
    s.snapshot(dest=str(tmp_path / "a;b.png")))
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
                                              "cpulist": captured("cpulist.main-visible.txt")})
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


def test_memdump_judges_the_range_by_the_mask_of_the_cpu_it_saves_from(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`save` reads the VISIBLE cpu's program space, read off `cpulist` at the call, so the wrap
    is judged by that cpu's own mask: after a `focus` another cpu's mask never decides. The two
    masks here are AUTHORED apart (m68k-dual's are equal) so the case can tell them apart."""
    def save(command: str) -> str:
        path, _start, length = command[len("save "):].split(",")
        Path(path).write_bytes(bytes(int(length, 16)))
        return "Data saved successfully\n"

    ses = _ConsoleSession(bytes(0x5000), replies={"save": save,
                                                  "cpulist": captured("cpulist.sub-visible.txt")})
    _console(monkeypatch, tmp_path, ses)
    ses.threads = {1: ":maincpu", 2: ":subcpu"}
    two = {"spaces": _masked(0xFFFFFF)["spaces"] + _masked(0x3FFF, ":subcpu")["spaces"]}
    monkeypatch.setattr(mstate.STATE, "machine_map", two)
    refused("wraps", s.memdump("0x3ffc", length=8, dest=str(tmp_path / "sub.bin")))
    ses.replies["cpulist"] = captured("cpulist.main-visible.txt")
    out = s.memdump("0x3ffc", length=8, dest=str(tmp_path / "main.bin"))
    assert out["status"] == "ok" and out["cpu"] == ":maincpu", out


def test_memdump_checks_the_file_against_a_read_of_the_cpu_save_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`save` reads the visible cpu, so the control does too: through that cpu's thread on
    the patched stub. Without threads the stub reads its first cpu only, and another visible
    cpu is refused before `save`, naming `focus`, rather than checked against the wrong one."""
    def save(command: str) -> str:
        path, _start, length = command[len("save "):].split(",")
        Path(path).write_bytes(bytes(int(length, 16)))
        return "Data saved successfully\n"

    ses = _ConsoleSession(bytes(64), replies={"save": save,
                                              "cpulist": captured("cpulist.sub-visible.txt")})
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
    """The console's `save` takes HEX for the address and the length (`1000` writes
    4096 bytes), and the file it writes is checked twice: its size, and its first bytes against
    a protocol `read` of the same range, the known-answer control inside the tool."""
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
    """A save the server makes for itself (`keep=False`, the value scan's range copy) answers its
    bytes and is removed, on success and on every refusal, and a refusal then names no path: the
    file is the session's, and one left behind is state nobody owns."""
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


def test_memdump_names_the_file_it_left_when_the_control_read_breaks_the_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The file is on disk when the control read is made, so a channel that breaks there
    is `session_broken` naming the file, its size and the range, as `write` names what
    landed; before, the exception escaped and the caller could not learn a file was left."""
    image = bytes(range(64))

    def save(command: str) -> str:
        path, _addr, length = command[len("save "):].split(",")
        Path(path).write_bytes(image[:int(length, 16)])
        return "Data saved successfully"

    ses = _ConsoleSession(image, replies={"save": save})
    _console(monkeypatch, tmp_path, ses)

    def broken(addr: int, n: int, *, thread: int) -> bytes:
        raise g.SessionError("the stub closed the connection")

    monkeypatch.setattr(ses, "read", broken)
    dest = tmp_path / "left.bin"
    out = s.memdump("0x0", length=32, dest=str(dest))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert out["path"] == str(dest) and out["bytes"] == 32 and out["length"] == 32, out
    assert out["addr"] == "0x00000000", out
    assert "closed the connection" in out["message"] and "left there" in out["message"]
    assert dest.read_bytes() == image[:32], "the file is left for inspection"
    assert getattr(ses, "broken") and s.registers()["code"] == "session_broken", (  # noqa: B009
        "and the channel LATCHED")
    setattr(ses, "broken", None)          # noqa: B010  # a fresh session, for the short case
    out = s.memdump("0x0", length=8, dest=str(tmp_path / "short.bin"))
    assert out["code"] == "session_broken" and out["bytes"] == 8, "a control shorter than 16"


def test_log_returns_the_newest_matching_lines_and_counts_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reply's shape: `lines_total` is the total in the file, `lines` the slice handed
    back, newest last, and `truncated` says whether they differ."""
    scratch = _console(monkeypatch, tmp_path, _ConsoleSession())
    (scratch / "error.log").write_text(
        "".join(f"[:] blit start {i}\n" if i % 2 else f"other {i}\n" for i in range(100))
    )
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
    (scratch / "error.log").write_text("a\n")
    refused("limit",
    s.log("x", channel="emulator", limit=0))
    refused("limit",
    s.log("x", channel="emulator", limit=read.LOG_LIMIT_MAX + 1))
    refused("does not compile",
    s.log("(unclosed", channel="emulator"))


def _snapping(image_dir: Path) -> Any:
    """A fake console `snap` that writes a small PNG-looking file where MAME would."""

    def snap(command: str) -> str:
        name = command[len("snap "):]
        (image_dir / name).write_bytes(_PNG)
        return f"Saved screen #0 snapshot as '{name}'"

    return snap


# The smallest thing that passes for a finished PNG here: signature, padding, IEND trailer.
_PNG = files.PNG_SIGNATURE + bytes(64) + b"\x00\x00\x00\x00" + files.PNG_TRAILER


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
    """MAME writes `snap <abs path>` RELATIVE to its snapshot directory, so an
    absolute path produces `snap/Users/.../shot.png`. The tool therefore snaps into the
    scratch under a name it controls and MOVES the file to `dest`. `dest` must be absolute and
    must not exist, judged before the console is touched."""
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


def test_snapshot_waits_for_a_file_that_arrives_late(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The wait loop's one reason to exist: the console answers before the file is whole."""
    import threading

    ses = _ConsoleSession()
    scratch = _console(monkeypatch, tmp_path, ses)

    def later(command: str) -> str:
        target = scratch / "snap" / command[len("snap "):]
        target.write_bytes(_PNG[:10])                       # a partial file first
        threading.Timer(0.15, lambda: target.write_bytes(_PNG)).start()
        return "Saved"

    ses.replies["snap"] = later
    out = s.snapshot()
    assert "verdict" not in out and out["bytes"] == len(_PNG)


def test_start_passes_log_and_reports_both_channels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`logerror`, the channel the repos' tracers read, went NOWHERE: `start` never passed
    `-log`, and stdout and stderr went to DEVNULL. Both now land in the scratch and the reply
    says where."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    out = s.start(**_boot_args(tmp_path, image))
    try:
        argv = _StubProcess.last_argv
        assert "-log" in argv
        scratch = Path(out["scratch_dir"])
        # THE NAMES COME FROM THE CONSTANT, never spelled here: a literal in the test agrees
        # with a literal in the code for exactly as long as nobody moves either.
        emulator_log = scratch / files.LOG_FILES["emulator"]
        process_log = scratch / files.LOG_FILES["process"]
        assert out["errorlog_path"] == str(emulator_log)
        assert out["stdout_path"] == str(process_log)
        assert process_log.exists(), "opened by start: a silent MAME leaves it empty"
        # Not only that the file exists: the PROCESS writes into it, both streams.
        import subprocess

        handed = _StubProcess.last_kwargs
        assert getattr(handed["stdout"], "name", None) == str(process_log)
        assert handed["stderr"] == subprocess.STDOUT
        st = s.status()
        assert st["errorlog_path"] == out["errorlog_path"]
        assert st["stdout_path"] == out["stdout_path"]
    finally:
        s.close()
    assert mstate.STATE.stdout_log is None and handed["stdout"].closed, "close releases the handle"


# --------------------------------------------- typed console reads, against captured text

FIXTURES = Path(__file__).parent / "fixtures" / "console"


def _first_window(answer: str) -> Callable[[str], str]:
    """A console that holds `answer`'s hits in the window starting at zero and none after it:
    a captured `find` replayed under the windows the tool now sends, so one capture over a
    range wider than a window is not counted once per window."""
    none = (FIXTURES / "find.none.txt").read_text()
    return lambda cmd: answer if cmd.split()[1].startswith("0x0,") else none


def test_the_console_fixtures_were_captured_and_say_so() -> None:
    """The parsers below are written against MAME's OWN text, captured live; a fixture authored
    from memory is the double that answers a question the real tool does not. The list of
    fixtures is the DIRECTORY, so a new one is covered the day it lands, and every one has to be
    named in the provenance, so a fixture with no recorded command cannot slip in."""
    provenance = (FIXTURES / "PROVENANCE.txt").read_text()
    assert provenance.startswith("Captured live from MAME")
    fixtures = sorted(f.name for f in FIXTURES.iterdir() if f.name != "PROVENANCE.txt")
    assert fixtures, "no fixtures at all is not a clean directory, it is nothing examined"
    for name in fixtures:
        assert (FIXTURES / name).stat().st_size > 0, name
        assert name in provenance, f"{name} has no line in PROVENANCE.txt saying what produced it"
    # The two shapes the parsers depend on are really in the captured text.
    assert "Found at " in (FIXTURES / "find.txt").read_text()
    assert (FIXTURES / "find.none.txt").read_text().strip() == "Not found"


def test_disassemble_reads_the_file_the_console_wrote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`dasm` writes a FILE, not a reply: the tool names the file, asks, reads it back."""

    ses = _ConsoleSession()
    scratch = _console(monkeypatch, tmp_path, ses)

    def dasm(command: str) -> str:
        name = command[len("dasm "):].split(",")[0]
        (scratch / name).write_bytes((FIXTURES / "dasm.txt").read_bytes())
        return (FIXTURES / "dasm.reply.txt").read_text()

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


def test_an_operand_quoted_in_a_comment_is_not_resolved() -> None:
    """A note quoting where a value lives is not an operand of the line it sits on, and a note
    holding ` // ` itself is cut at the first. The instructions are captured V30 lines, padded to
    one column as `dasm` pads a listing before its comments."""
    lines = ["F5BC7: 83 3E 14 C0 01    cmp     word ptr [0C014h],1h // the copy at [0E849h]",
             "F5BCC: 75 03             bne     0F5BD1h              // see [0C014h] // [0D000h]"]
    out = read.resolve_operands(lines, {"DATA": 0x400}, {}, {})
    assert [(r["line"], r["operand"]) for r in out] == [(0, "0C014h")], out


def test_disassemble_resolves_direct_memory_operands_under_the_bases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A DIRECT memory operand on a segmented board prints as the raw offset inside its
    class (`word ptr [0C014h]`), which is the map's `offset` column and NOT the linear
    address `read_memory` and `watch_add` take (`0x400 + offset` with DS=0x40). On
    v30-alt a caller reads and watches the wrong byte, and gets a
    plausible zero with no error. So the listing carries `resolved`: each direct operand's
    linear address under every class base `start` was given, with the symbol it lands in.
    Register-relative (`ds1:[bw-31BBh]`, `[ix]`), an immediate (`0CA35h`) and a call target
    are NOT direct operands and are left alone. Captured listings, not authored."""
    ses = _ConsoleSession()
    scratch = _console(monkeypatch, tmp_path, ses)
    # A CODE symbol sits just below a DATA linear address on purpose: the placement is
    # among the symbols of the operand's OWN class, never the nearest of any class, which
    # would name a routine for a datum on a board whose classes interleave.
    use_table(monkeypatch, table={"IN_IRQ": 0xC414, "TOTALTIME": 0xEC49,
                                  "DEMOSTATE": 0xCA30, "SOME_CODE": 0xC415})
    use_table(monkeypatch, classes={"IN_IRQ": "DATA", "TOTALTIME": "DATA", "DEMOSTATE": "DATA",
                                    "SOME_CODE": "CODE"})
    use_table(monkeypatch, bases={"DATA": 0x400})
    fixture = {"f5bc0": "dasm.v30.new_irq_video.txt", "f5e2f": "dasm.v30.startdemo.txt"}

    def dasm(command: str) -> str:
        name, addr, _length = command[len("dasm "):].split(",")
        (scratch / name).write_bytes((FIXTURES / fixture[addr[2:]]).read_bytes())
        return ""

    ses.replies["dasm"] = dasm
    out = s.disassemble("0xf5bc0", length=48)
    assert out["status"] == "ok", out
    assert out["resolved"] == [
        {"line": 4, "operand": "0C014h", "offset": 0xC014, "class": "DATA",
         "linear": "0x0000c414", "symbol": "IN_IRQ", "delta": 0},
        {"line": 16, "operand": "0C014h", "offset": 0xC014, "class": "DATA",
         "linear": "0x0000c414", "symbol": "IN_IRQ", "delta": 0},
        {"line": 21, "operand": "0E849h", "offset": 0xE849, "class": "DATA",
         "linear": "0x0000ec49", "symbol": "TOTALTIME", "delta": 0},
        {"line": 22, "operand": "0C016h", "offset": 0xC016, "class": "DATA",
         "linear": "0x0000c416", "symbol": "IN_IRQ", "delta": 2},
    ], out["resolved"]
    out = s.disassemble("0xf5e2f", length=48)
    assert out["resolved"] == [
        {"line": 21, "operand": "0CA34h", "offset": 0xCA34, "class": "DATA",
         "linear": "0x0000ce34", "symbol": "DEMOSTATE", "delta": 0x404},
    ], "only the one direct operand resolves; the register-relative ones are left alone"
    # TWO RELOCATED CLASSES answer one entry each per operand, and a class with no symbol
    # below the address answers `symbol` unavailable rather than another class's name.
    use_table(monkeypatch, bases={"DATA": 0x400, "OTHER": 0x20000})
    none_below = {"available": False, "why": "no symbol of class OTHER lies at or below it"}
    out = s.disassemble("0xf5e2f", length=48)
    assert [(r["class"], r["linear"], r["symbol"], r["delta"]) for r in out["resolved"]] == [
        ("DATA", "0x0000ce34", "DEMOSTATE", 0x404), ("OTHER", "0x0002ca34", none_below, none_below)]
    # AN EMPTY TABLE still resolves the address: the symbol is what is missing, not the base.
    use_table(monkeypatch, table={})
    use_table(monkeypatch, classes={})
    use_table(monkeypatch, bases={"DATA": 0x400})
    out = s.disassemble("0xf5e2f", length=48)
    below = {"available": False, "why": "no symbol of class DATA lies at or below it"}
    assert out["resolved"] == [{"line": 21, "operand": "0CA34h", "offset": 0xCA34,
                                "class": "DATA", "linear": "0x0000ce34", "symbol": below,
                                "delta": below}]
    # THE CONTROL: a board with no bases (a 68000 with a YAML table) carries no `resolved`
    # at all, rather than an empty list that reads as "nothing to resolve here".
    use_table(monkeypatch, bases={})
    out = s.disassemble("0xf5bc0", length=48)
    assert "resolved" not in out, out


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


def _listing_pair(scratch: Path, name: str) -> Callable[[str], str]:
    """A console `dasm` that writes the captured listing of one range, with its opcode bytes or
    without them as the command's `opcodes` flag asks, where the real console would."""
    def dasm(command: str) -> str:
        file, _addr, _length, *rest = command[len("dasm "):].split(",")
        bare = bool(rest) and rest[0] == "0"
        (scratch / file).write_bytes((FIXTURES / f"{name}{'.bare' if bare else ''}.txt")
                                     .read_bytes())
        return (FIXTURES / "dasm.reply.txt").read_text()
    return dasm


def test_disassemble_classifies_each_line_off_the_listing_without_opcode_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`flow` holds one class per line of `lines`, and `flow_source` says the class was READ
    OFF A MNEMONIC TABLE for the cpu's type, which `start` cached: MAME computes the same
    distinction and its console drops it (`mame_flow`). The mnemonic comes off a second
    listing written without the opcode bytes, on the same cpu the first one named."""
    ses = _ConsoleSession(replies={"cpulist": captured("cpulist.main-visible.txt")})
    scratch = _console(monkeypatch, tmp_path, ses)
    # TWO CPUS OF DIFFERENT TYPES, so a class read off one cpu's words with the other's table
    # cannot come out right by coincidence.
    monkeypatch.setattr(mstate.STATE, "machine_map", {"cpus": [
        {"tag": ":maincpu", "type": "m68000"}, {"tag": ":subcpu", "type": "v30"}]})
    ses.replies["dasm"] = _listing_pair(scratch, "dasm.m68k.560")
    out = s.disassemble("0x560", length=0x40)
    assert out["status"] == "ok" and out["flow_source"] == "mnemonic_table:m68000", out
    assert len(out["flow"]) == len(out["lines"]) and "note" not in out
    assert [(line.split(":")[0], c) for line, c in zip(out["lines"], out["flow"], strict=True)
            if c != "sequential"] == [("000578", "branch"), ("00058C", "call"),
                                      ("00059A", "return")]
    # THE SECOND LISTING NAMES THE CPU THE TABLE IS FOR, even when the call named none: left to
    # the console it would decode whichever cpu is visible then, under `:maincpu`'s table.
    assert [c for c in ses.commands if c.startswith("dasm")] == [
        "dasm dasm.txt,0x560,0x40", "dasm dasm.bare.txt,0x560,0x40,0,:maincpu"]
    # A CPU NAMED travels to both listings, and picks its own type's table.
    ses.commands.clear()
    ses.replies["dasm"] = _listing_pair(scratch, "dasm.v30.30000")
    out = s.disassemble("0x30000", length=0xb0, cpu="subcpu")
    assert [c for c in ses.commands if c.startswith("dasm")] == [
        "dasm dasm.txt,0x30000,0xb0,1,:subcpu", "dasm dasm.bare.txt,0x30000,0xb0,0,:subcpu"]
    assert out["flow_source"] == "mnemonic_table:v30" and "unknown" not in out["flow"], out


def test_disassemble_without_a_table_marks_every_line_unknown_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A type with no table, a type the inventory never recorded, and a second listing that
    did not come out each leave `lines` whole and every class `unknown`, with ONE `note`
    saying why and `flow_source: none`. The first two cost no second call; none of the three is
    a guess from the nearest family's table."""
    ses = _ConsoleSession(replies={"cpulist": captured("cpulist.main-visible.txt")})
    scratch = _console(monkeypatch, tmp_path, ses)
    ses.replies["dasm"] = _listing_pair(scratch, "dasm.m68k.560")
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
    first = _listing_pair(scratch, "dasm.m68k.560")
    ses.replies["dasm"] = lambda cmd: first(cmd) if cmd.startswith("dasm dasm.txt") else "Error"
    out = s.disassemble("0x560", length=0x40)
    assert out["status"] == "ok" and out["flow"] == ["unknown"] * 15, out
    assert "without opcode bytes did not come out" in out["note"], out["note"]
    # THE SECOND LISTING DESCRIBES OTHER INSTRUCTIONS: no class is shifted onto a neighbour.
    other = _listing_pair(scratch, "dasm.v30.30000")
    ses.replies["dasm"] = lambda cmd: first(cmd) if cmd.startswith("dasm dasm.txt") else other(cmd)
    out = s.disassemble("0x560", length=0x40)
    assert out["flow"] == ["unknown"] * 15 and "same addresses" in out["note"], out


def test_find_parses_hits_and_an_empty_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The captured `find` answered two hits for the image's first four bytes over 64 KB, and
    "Not found" for a pattern that is not there; both shapes are the parser's whole input."""
    ses = _ConsoleSession(replies={"find": _first_window((FIXTURES / "find.txt").read_text())})
    _console(monkeypatch, tmp_path, ses)
    out = s.find(ref="0x0", length=0x10000, data_hex="00201000")
    assert out["hits"] == ["0x00000000", "0x000025ea"] and out["hits_total"] == 2
    assert out["addr"] == "0x00000000" and out["length"] == 0x10000 and out["truncated"] is False
    assert out["session"]["altered"] is False
    # Every byte travels prefixed: a bare `d0` is a register to the console's expression parser.
    assert ses.commands == ["cpulist", "find 0x0,0x8000,0x00,0x20,0x10,0x00",
                            "find 0x8000,0x8000,0x00,0x20,0x10,0x00"]
    ses.replies["find"] = (FIXTURES / "find.none.txt").read_text()
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
    """Zero hits is a measurement only when the console said `Not found`; an error, an empty
    reply or a line of another shape is the console complaining, and a zero there would be the
    false all-clear this whole server exists to refuse."""
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
    """Each byte is a parameter of its own after the address and the length, and the console
    takes `MAX_COMMAND_PARAMS` (src/emu/debug/debugcon.h): at the edge, and one past it."""
    assert len(read.check_find(ref="0x0", length=16, data_hex="00" * read.FIND_BYTES_MAX)) == 126
    with pytest.raises(mstate.Invalid, match=r"byte count of data_hex=127 is outside 1\.\.126"):
        read.check_find(ref="0x0", length=16, data_hex="00" * (read.FIND_BYTES_MAX + 1))


def test_a_listing_with_a_raw_byte_is_decoded_with_replacement_never_an_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A comment or a label the disassembler prints raw out of ROM: the line comes back
    with the replacement character, as a log line does, and the listing stands."""
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


def test_find_is_bounded_by_the_program_space_when_the_mask_is_known(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `length` past what the program space holds is refused naming the space and its mask
    (`read.space_bound`, every range-taking tool's judge); the space is the one `start` read
    from the address mask, and with none known the range is the console's."""
    ses = _ConsoleSession(replies={"find": "Not found\n",
                                   "cpulist": captured("cpulist.main-visible.txt")})
    _console(monkeypatch, tmp_path, ses)
    monkeypatch.setattr(mstate.STATE, "machine_map", _masked(0x3FFF))
    out = refused("past the program space",
                  s.find(ref="0x0", length=0x4001, data_hex="00"))
    assert out["code"] == "bad_argument" and "mask is 0x3fff" in out["message"], out
    assert ses.commands == ["cpulist"], "refused before the search: only the cpu was read"
    whole = s.find(ref="0x0", length=0x4000, data_hex="00")
    assert whole["hits_total"] == 0, "the whole space is a range"
    monkeypatch.setattr(mstate.STATE, "machine_map", {})
    unmasked = s.find(ref="0x0", length=0x00100000, data_hex="00")
    assert unmasked["hits_total"] == 0, "no mask: the console's"


def test_find_sends_a_long_range_in_windows_and_merges_their_hits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`FIND_WINDOW`, whose comment says why: the windows tile the range with no gap and no
    overlap, the last one short, and their hits merge in address order."""
    window = read.FIND_WINDOW

    def answer(cmd: str) -> str:
        start = int(cmd.split()[1].split(",")[0], 16)
        return f"Found at {start:06X}\n"

    ses = _ConsoleSession(replies={"find": answer})
    _console(monkeypatch, tmp_path, ses)
    out = s.find(ref="0x0", length=2 * window + 0x10, data_hex="00")
    assert ses.commands == ["cpulist", f"find 0x0,{window:#x},0x00",
                            f"find {window:#x},{window:#x},0x00",
                            f"find {2 * window:#x},0x10,0x00"], ses.commands
    assert out["hits_total"] == 3 and out["hits"] == [f"{i * window:#010x}" for i in range(3)], out
    assert out["length"] == 2 * window + 0x10 and out["span"]["length"] == 2 * window + 0x10


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


def test_every_reply_opens_with_a_summary_and_closes_with_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The line the client paints is the tool's name, its arguments and its reply, so the
    reply's FIRST field is the one-line summary and the `session` block stays last. Decided
    in the wrapper, so it is read through a registered tool and not through `_envelope`."""
    ses = _RegisterSession(bits=32)
    _install(monkeypatch, ses, tmp_path)
    use_table(monkeypatch, table={})
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    monkeypatch.setattr(mstate.STATE, "store", dec.DeclarationStore("test", path=None))
    monkeypatch.setattr(mstate.STATE, "session_origin", "s1")
    out = s.breakpoint_at("0xf2034")
    assert list(out)[0] == "summary" and list(out)[-1] == "session", list(out)
    assert out["summary"] == "breakpoint_at 0xf2034: armed at 0x000f2034", out["summary"]
    listed = s.declaration_list("breakpoint")
    assert [b["addr"] for b in listed["breakpoints"]] == ["0x000f2034"]
    assert listed["summary"] == "declaration_list breakpoint: 1 breakpoint (1 armed)"
    refused = s.declaration_clear("breakpoint", ref="0x4a0")
    assert refused["status"] == "INVALID" and refused["summary"].startswith(
        "declaration_clear: INVALID (unknown_ref), '0x4a0' matches no breakpoint declaration")
    assert " ".join(refused["message"].split()).endswith(
        "`declaration_list(kind=\"breakpoint\")` shows as `ref`. Matching: "
        f"{dec.REF_MATCH['breakpoint']}."), (
        "the refusal names its own family's list and rule")
    s.breakpoint_at("0x4a0")
    one = s.declaration_clear("breakpoint", ref="0x4a0")
    assert one["disarmed"] == ["2 @ 0004A0"]
    assert one["summary"] == "declaration_clear breakpoint 0x4a0: 1 cleared, 1 disarmed"
    assert [b["addr"] for b in s.declaration_list("breakpoint")["breakpoints"]] == ["0x000f2034"], (
        "only the named one went")
    cleared = s.declaration_clear("breakpoint", all=True)
    assert cleared["disarmed"] == ["1 @ 0F2034"]
    assert s.declaration_list("breakpoint")["breakpoints"] == []
    assert cleared["summary"] == "declaration_clear breakpoint all: 1 cleared, 1 disarmed"
    # an INVALID reply's summary says so and quotes the why, on the same first line
    ses.frame_answers = ["10"] * 5
    flat = s.run_for(milliseconds=1)
    assert flat["status"] == "INVALID" and list(flat)[0] == "summary"
    assert flat["summary"] == f"run_for: INVALID ({flat['code']}), {flat['message'][:120]}"


def test_set_register_takes_an_integer_and_answers_hex(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    """The value reaches the stub as the integer given (its `0x` spelling is
    `test_number_args.py`'s). The reply prints it back as hex at the register's width, which is
    how every register reads here; a negative is refused before it reaches the stub."""
    ses = _RegisterSession(bits=16)
    _install(monkeypatch, ses, tmp_path)
    out = s.set_register("EAX", 0x1234)
    assert ses.values["EAX"] == 0x1234, "the integer reached the stub as it came"
    assert out["value"] == "0x1234" and out["register"] == "EAX"
    # READ BACK, as `write` is: a reply that echoes the argument reports what was SENT and
    # says nothing about a register that answers something else. And at
    # the register's OWN width, asked of the session, which resolves an alias too.
    assert out["readback"] == "0x1234" and out["verified"] is True
    assert out["summary"] == "set_register EAX = 0x1234, verified True"
    refused("negative",
    s.set_register("EAX", -1))
    # THE CLIENT'S OWN REFUSALS ARE ARGUMENT REFUSALS: an unknown register and a value that
    # does not fit its width would otherwise escape as the session's error, outside the
    # contract.
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


def test_every_tool_has_a_live_case_calling_it_through_the_server() -> None:
    """A tool with no live case is a tool whose green means nothing: one can ship having
    never once worked, with the whole contract tier green over it. The population is the MCP
    registry, so a tool added tomorrow turns this red
    until `tests/live/live_check.py` CALLS it through the server; the calls are found by AST
    (`s.<tool>(...)` on the server alias), never by searching the text, so a comment naming a
    tool does not count."""
    import ast

    live = Path(__file__).parent / "live" / "live_check.py"
    called: set[str] = set()
    for node in ast.walk(ast.parse(live.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "s"):
            called.add(node.func.attr)
    registered = {t.name for t in s.mcp._tool_manager.list_tools()}
    missing = sorted(registered - called)
    assert not missing, (
        f"these tools have no live case that CALLS them through the server: {missing}")


def test_every_tool_declares_a_title_and_the_readers_a_read_only_hint() -> None:
    """`title` is what the client shows; `readOnlyHint` is what lets it run readers in
    parallel. A writer WITH the hint is a lie a client would act on, so the writers are pinned
    as not read-only by name: anything that advances the machine, writes to it, or writes a
    file."""
    tools = {t.name: t for t in s.mcp._tool_manager.list_tools()}
    untitled = sorted(n for n, t in tools.items() if not t.title)
    assert not untitled, f"tools with no title: {untitled}"
    read_only = {n for n, t in tools.items()
                 if t.annotations is not None and t.annotations.read_only_hint}
    assert read_only == {"status", "read_memory", "disassemble", "find", "history", "log",
                         "log_wait", "registers", "declaration_list", "rom_check",
                         "symbols_find", "state_list", "captures", "machine_map",
                         "cpu_info", "comment_list", "audio_compare"}, read_only
    # IDEMPOTENT IS A STRONGER CLAIM than read-only and almost nothing here can make it: a
    # reader of a machine that moves answers differently on the second call. Held as an exact
    # set so a tool that grows a cache, or loses one, cannot drift into or out of it quietly.
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


# ------------------------------------------- one register width, and a run that ends by itself


class _OwnRegisterFile:
    """A double that is its own register file for every thread: `values` by name, each `bits`
    wide, the program counter named as `Layout.pc_name` names it (`PC`, `EIP` or `RIP`)."""

    values: dict[str, int]
    bits = 32

    def layout(self, thread: int) -> Any:
        return self

    @property
    def pc_name(self) -> str:
        return next(n for n in ("PC", "EIP", "RIP") if n in self.values)

    @property
    def register_names(self) -> list[str]:
        return list(self.values)

    @property
    def register_bits(self) -> dict[str, int]:
        return dict.fromkeys(self.values, self.bits)

    def register_texts(self, *, thread: int) -> dict[str, str]:
        """`values` as the stub prints them, big-endian digits at the declared width."""
        return {n: f"{v:0{self.bits // 4}x}" for n, v in self.values.items()}


class _RegisterSession(_OwnRegisterFile, SessionFields):
    """A session with a register file of a declared width, a frame counter and a console.

    The frame counter is a MACHINE, not a list: `emulating=True` makes every `print frame`
    answer one more than the last (a machine still emulating), `emulating=False` answers the
    same value (a machine stopped in the debugger). `gtime` starts it emulating and `stop_after`
    says after how many polled readings it stops by itself; `halt` stops it at once. This is
    what lets a test tell "the tool waited for the stop" from "the tool read the counter once
    and left". `running`, `stop_count`, `go` and `poll_stop` are the PROTOCOL's half, the one
    `resume`/`run_to` drive: a `go` runs, and the stop arrives at the first poll.

    `frameless=True` is a board with no screen device: every `print` naming a frame symbol
    answers the console's captured refusal, and the emulated clock (`emulated_seconds`) is
    the machine instead, one millisecond further at each reading while it emulates.

    `stale_after_load=True` keeps `statesave`'s frame by name and gives it back at `stateload`,
    and `totalcycles` then answers the count from BEFORE the load until the cpu next executes
    (a `gvblank`, a `gtime`, a `go`, a step), as the capture `totalcycles-after-load.txt` shows
    MAME doing; `cycles_offset` is the count at frame 0, which a real board does not start at zero.
    With it, a `rewind`/`rw` goes back one frame with the counter left as it was, and a
    `softreset` leaves the counter as it was until the cpu executes, which applies the reset and
    restarts the count from zero there, as MAME does for each typed through `debug`.
    """

    def __init__(self, bits: int, frame: int = 10, stop_after: int | None = 3,
                 values: dict[str, int] | None = None) -> None:
        self.bits = bits
        self.byte_order = "big"               # a register file a cpu's order decodes
        self.frame = frame
        self.stop_after = stop_after
        self.emu_clock = 0.0                  # emulated seconds the console's `time` reports
        self.emulating = False
        self.running = False
        self.stop_count = 0
        self.last_stop_packet = ""
        self.polls_since_gtime = 0
        self.threads: dict[int, str] = {}
        self.values = values or {"EAX": 0x1234, "EIP": 0x8B56}
        self.temps: dict[int, int] = {}
        self.cycles_per_frame = 0x1000          # `totalcycles` is the frame times this
        self.frozen = False                     # a `gvblank` that moves no frame
        self.pcs = [0xF2034, 0xF2100]
        self.commands: list[str] = []
        self.writes = 0
        self.interrupted = False
        self.received: list[float] = []
        self.frame_answers: list[str] | None = None
        self.bplist_rows: list[str] = []
        self.bp_next_index = 1
        self.bp_devices: dict[int, str] | None = None
        self.rplist_rows: list[tuple[int, str, bool]] = []
        self.rp_next_index = 1
        self.packet_size: int | None = None   # what a stub advertises; this one says nothing
        self.frameless = False
        self.cycles_offset = 0
        self.stale_after_load = False
        self.saved_frames: dict[str, int] = {}
        self.stale_cycles: int | None = None    # what `totalcycles` holds until the cpu runs
        self.reset_pending = False              # a typed `softreset` the next execution applies

    # The real rules, not copies of them: they read nothing but `packet_size`.
    max_payload = g.Session.max_payload
    console_packet = g.Session.console_packet

    def emulated_seconds(self) -> float:
        if self.frameless and self.emulating:
            self.emu_clock = round(self.emu_clock + 0.001, 6)
            self.polls_since_gtime += 1
            if self.stop_after is not None and self.polls_since_gtime >= self.stop_after:
                self.emulating = False
        return self.emu_clock

    def totalcycles(self) -> int:
        if self.stale_cycles is not None:
            return self.stale_cycles
        return self.frame * self.cycles_per_frame + self.cycles_offset

    def executed(self) -> None:
        """The cpu ran: MAME's `totalcycles` is up to date again, and counts from zero at a reset
        that run applied."""
        self.stale_cycles = None
        if self.reset_pending:
            self.reset_pending = False
            self.cycles_offset = -self.frame * self.cycles_per_frame

    def close(self) -> None:
        """A no-op: these tests reach `close` only to read `average_speed` before the kill,
        never to exercise the process teardown (that is `_RecordingSession`'s job)."""

    def registers(self, *, thread: int) -> dict[str, int]:
        return dict(self.values)

    def current_pc(self) -> int:
        # The machine is somewhere else once it has run: the pc before `gtime` is not the one after.
        ran = any(c.startswith("gtime") for c in self.commands)
        return self.pcs[-1] if ran else self.pcs[0]

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        self.commands.append(command)
        if (listed := debugger_lists(self, command)) is not None:
            return listed
        if self.frameless and command.startswith("print ") and (
                named := re.search(r"\bframe\d*\b", command)):
            return (FIXTURES / f"print-{named.group(0)}-no-screen.txt").read_text()
        if self.stale_after_load and command.startswith("statesave "):
            self.saved_frames[command[10:]] = self.frame
        if self.stale_after_load and command.split()[0] in ("stateload", "sl"):
            self.stale_cycles = self.totalcycles()
            self.frame = self.saved_frames[command.split()[1].split(";")[0]]
        if self.stale_after_load and command in ("rewind", "rw"):
            self.stale_cycles = self.totalcycles()
            self.frame -= 1
        if self.stale_after_load and command == "softreset":
            self.stale_cycles = self.totalcycles()
            self.reset_pending = True
        if command.startswith("gtime"):
            self.executed()
            self.emulating = True
            self.polls_since_gtime = 0
            return ""
        if command == "gvblank":
            self.executed()
            # One frame per `gvblank`, unless the double is frozen.
            if not self.frozen:
                self.frame += 1
            return ""
        if command in ("print frame", "print frame,totalcycles"):
            if self.frame_answers is not None:
                answer = self.frame_answers.pop(0)
                if command == "print frame,totalcycles" and answer.strip():
                    answer += f" {self.totalcycles():x}"
                return answer + "\n"
            if self.emulating:
                self.frame += 1
                self.polls_since_gtime += 1
                if self.stop_after is not None and self.polls_since_gtime >= self.stop_after:
                    self.emulating = False
            if command == "print frame,totalcycles":
                return f"{self.frame:x} {self.totalcycles():x}\n"
            return f"{self.frame:x}\n"
        if command == "print totalcycles":
            return f"{self.totalcycles():x}\n"
        if command == "print curpc":
            return f"{self.current_pc():x}\n"
        return ""

    def _receive(self, timeout: float | None = None) -> str:
        self.received.append(timeout if timeout is not None else -1.0)
        raise g.SessionError("no answer within the drain")

    def halt(self) -> None:
        self.interrupted = True
        self.emulating = False

    def interrupt(self, timeout: float = 5.0) -> str:
        self.interrupted = True
        self.running = False
        self.stop_count += 1
        return "T05"

    def breakpoint(self, addr: int, remove: bool = False) -> None:
        if remove:
            self.bplist_rows = [r for r in self.bplist_rows if not r.endswith(f"@ {addr:06X}")]
        else:
            bplist_add(self, addr)

    def set_reg(self, name: str, value: int, *, thread: int) -> None:
        # The client's own judgement, as it makes it: a value too wide for the register
        # is refused before a byte reaches the stub.
        if value >= 1 << self.bits:
            raise g.SessionError(f"{name.upper()} is {self.bits} bits on this cpu and "
                                 f"{value:#x} does not fit it")
        self.values[name.upper()] = value

    def reg(self, name: str, *, thread: int) -> int:
        return self.values[name.upper()]

    def register_width(self, name: str) -> int:
        return self.bits

    def register_name(self, name: str) -> str:
        if name.upper() not in self.values:
            raise g.SessionError(f"unknown register {name!r}; this CPU has {list(self.values)}")
        return name.upper()

    def go(self) -> None:
        self.executed()
        self.running = True

    def poll_stop(self, timeout: float = 0.0) -> bool:
        if self.running:
            self.running = False
            self.stop_count += 1
            self.last_stop_packet = "T05"
        return True


def test_run_to_prints_registers_at_their_declared_width(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE REGRESSION THIS EXISTS FOR: `registers` learned to pad each value to the width the
    target description declares, and `run_to` kept its fixed ten characters, so the same V30
    register read `0x8b56` in one reply and `0x00008b56` in the next. One helper, two callers."""
    ses = _RegisterSession(bits=16)
    _install(monkeypatch, ses, tmp_path)
    use_table(monkeypatch, table={})
    narrow = s.registers()["regs"]
    assert narrow == {"EAX": "0x1234", "EIP": "0x8b56"}
    out = s.run_to(ref="0xf2034", control="0x4a0", seconds=1.0)
    assert out["verdict"] == "TARGET"
    assert out["regs"] == narrow, "the two tools disagree on the width of one register"
    wide = _RegisterSession(bits=32)
    _install(monkeypatch, wide, tmp_path)
    assert s.registers()["regs"] == {"EAX": "0x00001234", "EIP": "0x00008b56"}
    # A width that is not a multiple of four rounds UP to a whole hex digit: 13 bits is FOUR
    # digits, not three (12 bits would not tell the two roundings apart).
    odd = _RegisterSession(bits=13, values={"EAX": 0x12, "EIP": 0x345})
    _install(monkeypatch, odd, tmp_path)
    assert s.registers()["regs"] == {"EAX": "0x0012", "EIP": "0x0345"}


def test_registers_states_each_width_explicitly_beside_the_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The width is in the digit count of a zero-padded value, but reading it means COUNTING
    digits, and a V30 register named EAX at 16 bits is exactly where a reader second-guesses.
    So `registers` states it: a `register_bits` map beside `regs`, the cpu's declared bits per
    register. It rides only on `registers`, whose job is to answer about the register file;
    a stop reply carries the values, and the width stays in their digits there."""
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


def test_run_for_waits_until_the_frame_counter_stops_moving(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The console answers `print frame` while the machine still runs, so
    reading it once after `gtime` would report a mid-run count under ELAPSED and hand back a
    running machine. The tool polls until three readings agree; the milliseconds travel in hex
    like every other console number (a bare `gtime 100` runs 0x100 ms)."""
    ses = _RegisterSession(bits=32, frame=10, stop_after=4)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    # THE PREVIOUS STOP'S PACKET IS NOT THIS RUN'S. A run the console starts (`gtime`) ends
    # with no stop packet, so the packet of the stop before it (a watchpoint's, say) is
    # still the last one the stub sent, and a survey reading it named this ELAPSED stop a
    # watch's, with a `watch_hit` whose own before/after said nothing was written.
    ses.last_stop_packet = "T05watch:2031fc;thread:1;"
    out = s.run_for(milliseconds=250)
    assert out["verdict"] == "ELAPSED"
    assert out["cause"] == "the console's `gtime` stop" and "watch_hit" not in out, out
    assert ses.last_stop_packet == "", "the stale packet survived the console-started run"
    assert out["frame_before"] == 10 and out["frame_after"] == 14
    # Before, gtime, then the poll: four moving readings and then the three that agree.
    # `cpulist` first: which cpu the run's `totalcycles` is counted on.
    assert ses.commands[:3] == ["cpulist", "print frame,totalcycles", "gtime 0xfa"]
    assert ses.commands[3:9] == ["print frame"] * 6
    # Then the stop survey: the visible cpu, the frame and the listing at the pc (the double's
    # `current_pc` answers without the console).
    assert ses.commands[9:] == ["cpulist", "print frame", "dasm dasm.txt,0xf2100,0x20",
                                "print totalcycles"]
    assert out["reads"] == 6 and "polls" not in out
    assert not ses.interrupted, "a machine that stopped by itself is not interrupted"
    assert ses.received == [g.STOP_REPLY_DRAIN_S], (
        "the drain is bounded by its named constant")
    assert out["pc"] == f"{0xF2100:#010x}", "the pc is read AFTER the run, not before"
    assert out["session"]["altered"] is False, "advancing the machine is not forcing its state"
    refused("milliseconds",
    s.run_for(milliseconds=0))


def test_run_for_is_invalid_when_the_counter_did_not_move_or_went_backwards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _RegisterSession(bits=32, frame=10)
    ses.frame_answers = ["a"] * 5   # a run shorter than a frame: the counter never moved
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    out = s.run_for(milliseconds=1)
    assert out["status"] == "INVALID" and "shorter than one frame" in out["message"]
    assert out["code"] == "no_progress"
    # INVALID AND STILL A STOP: the machine is where the run left it, and the survey rides
    # on the reply as it does on `run_to`'s INVALID. Without it a watch that stopped the
    # machine inside the run was thrown away with the verdict, while `run_to` kept it.
    assert "pc" in out and "regs" in out and "dasm" in out, out
    back = _RegisterSession(bits=32, frame=10, stop_after=0)
    back.frame_answers = ["64", "3", "3", "3", "3"]   # the counter fell under the run
    _install(monkeypatch, back, tmp_path)
    out = s.run_for(milliseconds=100)
    assert out["status"] == "INVALID" and "this call saw only the counter" in out["message"]
    assert out["code"] == "frames_went_backwards"
    assert "pc" in out and "regs" in out, out


def test_run_for_interrupts_a_machine_still_moving_at_the_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The grace is a bound, not a promise: a machine still emulating at `timeout` is stopped by
    the tool and the verdict says so, because a running machine handed back is the worst state
    a session can be in."""
    import time as _time

    ses = _RegisterSession(bits=32, frame=10, stop_after=None)   # never stops by itself
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.01)
    t0 = _time.time()
    out = s.run_for(milliseconds=60000, seconds=0.2)
    assert _time.time() - t0 < 2.0, "the bound is the caller's timeout, not the console's"
    assert ses.interrupted, "the machine was left running"
    assert out["verdict"] == "TIMEOUT" and out["frame_after"] > out["frame_before"]
    # After the halt: the frame read that proves the stop, then the stop survey (the visible
    # cpu, its own frame read and the listing at the pc).
    assert ses.commands[-5:] == ["print frame", "cpulist", "print frame",
                                 "dasm dasm.txt,0xf2100,0x20", "print totalcycles"]


def test_run_for_treats_a_non_numeric_frame_as_a_refusal_and_stops_the_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stop packet or an error line where a number was expected must not escape as a bare
    ValueError, skipping the interrupt: it is the console refusing, and the machine is
    stopped before the tool answers."""
    ses = _RegisterSession(bits=32, frame=10, stop_after=None)
    ses.frame_answers = ["a", "T05thread:01;"]
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)

    def after_halt() -> None:
        ses.frame_answers = None   # the machine, stopped, answers numbers again
        ses.frame = 20             # and it had run meanwhile
        ses.interrupted = True
        ses.emulating = False

    ses.halt = after_halt  # type: ignore[method-assign]
    out = s.run_for(milliseconds=100)
    assert ses.interrupted and out["verdict"] == "TIMEOUT"


# ------------------------------------- which argument is judged before the machine is asked for


#: AN ARGUMENT WHOSE VALIDITY DOES NOT DEPEND ON THE MACHINE, and the refusal it earns with no
#: machine running. A relative `dest`, a `length` of zero, a regex that does not compile: every
#: one of these is exactly as wrong on a running machine as on no machine at all, so answering
#: "no machine running" withholds the only thing the caller needed to hear.
#: A directory that does not exist under the system temp dir, so no path built from it can be
#: there; its PARENT does exist, for the rows that need a directory and a file that is not.
_FRESH: Path = Path(tempfile.gettempdir()) / "mame-boundary-never-created"

MACHINE_INDEPENDENT: dict[str, Any] = {
    "read_memory": lambda: s.read_memory(ref="0x0", length=0),
    "disassemble": lambda: s.disassemble(ref="0x0", length=0),
    "find": lambda: s.find(ref="0x0", length=4, data_hex="zz"),
    "history": lambda: s.history(limit=0),
    "log": lambda: s.log(channel="emulator", pattern="[", limit=0),
    "log-channel": lambda: s.log(channel="nosuch", pattern="."),
    # A name nothing creates, under a directory that exists: the row must be refused for the
    # LENGTH it names, and the message is asserted below because a leftover file would refuse it
    # for the path instead.
    "memdump-length": lambda: s.memdump(
        ref="0x0", length=0, dest=str(_FRESH.parent / "mame-boundary-probe-never-written.bin")),
    "memdump-relative": lambda: s.memdump(ref="0x0", length=4, dest="relative.bin"),
    "memdump-nul": lambda: s.memdump(ref="0x0", length=4, dest="/tmp/pro\x00be.bin"),
    "snapshot-relative": lambda: s.snapshot(dest="relative.png"),
    "snapshot-nul": lambda: s.snapshot(dest="/tmp/pro\x00be.png"),
    "record-frames": lambda: s.record(frames=0, dest="/tmp/probe.avi"),
    "record-relative": lambda: s.record(frames=4, dest="relative.avi"),
    "audio_record-frames": lambda: s.audio_record(frames=0, dest="/tmp/probe.wav"),
    "audio_record-relative": lambda: s.audio_record(frames=4, dest="relative.wav"),
    "run_for": lambda: s.run_for(milliseconds=0),
    "step": lambda: s.step(count=0),
    "resume": lambda: s.resume(seconds=-1),
    "log_wait": lambda: s.log_wait(channel="emulator", pattern="[", seconds=0),
    # Tools whose arguments are judged before the gate only through the batch path or a bound.
    "run_for-seconds": lambda: s.run_for(milliseconds=100, seconds=0),
    "perform-a-step's-value": lambda: s.perform(steps=[{"op": "status"},
                                                       {"op": "step", "count": 0}]),
    "perform-a-step's-dest": lambda: s.perform(steps=[{"op": "status"},
                                                      {"op": "memdump", "ref": "0x0", "length": 8,
                                                       "dest": "relative.bin"}]),
    "drive-a-step's-value": lambda: s.drive(act=[{"op": "step", "count": 0}], pattern="."),
    # Tools with a machine-independent argument that is easy to leave past the gate: a bound, a
    # vocabulary, a file that must exist, a name that becomes a file name.
    "breakpoint_at-by-address": lambda: s.breakpoint_at(ref="PLAYER_X", by="address"),
    "breakpoint_at-pointer": lambda: s.breakpoint_at(ref="[4a0]+0x4"),
    "watch_add-negative-width": lambda: s.watch_add(ref="0x0", mode="show", length=-4),
    "watch_add-length": lambda: s.watch_add(ref="0x0", mode="show", length=9999),
    "record-seconds": lambda: s.record(frames=2, seconds=0),
    "audio_record-seconds": lambda: s.audio_record(frames=2, seconds=0),
    "input-seconds": lambda: s.input(port=":P1", field="Coin 1", seconds=0),
    "throttle-seconds": lambda: s.throttle(on=True, seconds=0),
    "resume-ceiling": lambda: s.resume(seconds=1e9),
    "rom_check-addr": lambda: s.rom_check(reference_rom="/nope", reference_addr="zz"),
    "rom_check-file": lambda: s.rom_check(reference_rom=str(_FRESH / "rom.bin")),
    "state_write save-name": lambda: s.state_write("save", name="../x"),
    "state_write load-name": lambda: s.state_write("load", name="../x"),
    "perform-a-snapshot-step's-dest": lambda: s.perform(
        steps=[{"op": "status"}, {"op": "snapshot", "dest": "relative.png"}]),
    "perform-a-lua-step's-script": lambda: s.perform(
        steps=[{"op": "status"}, {"op": "lua", "script": "   "}]),
}


#: AND THE OTHER HALF, WHICH IS WHAT KEEPS THE RULE HONEST: an argument only the machine can
#: judge. A `ref` is a symbol in THAT machine's table or an address its stub serves, so a verdict
#: about one with no machine running would be a verdict about a table that does not exist. These
#: still answer `no_session`, and a change that moved them would be the mechanical reading of the
#: rule rather than the rule.
MACHINE_DEPENDENT: dict[str, Any] = {
    "read_memory": lambda: s.read_memory(ref="no_such_symbol", length=4),
    "disassemble": lambda: s.disassemble(ref="no_such_symbol", length=4),
    "memdump": lambda: s.memdump(ref="no_such_symbol", length=4, dest="/tmp/probe.bin"),
    "run_to": lambda: s.run_to(ref="no_such_symbol"),
    "symbols_find": lambda: s.symbols_find(name="no_such_symbol"),
}


@pytest.mark.parametrize("name", sorted(MACHINE_INDEPENDENT))
def test_an_argument_the_machine_cannot_judge_is_refused_with_no_machine(name: str) -> None:
    """THE RULE IS THE PROPERTY, NOT THE ARGUMENT'S NAME: an argument is judged before the gate
    when its validity does not depend on the machine.

    The opposite rule (EVERY argument waits for the machine) has its own defect: a caller told off
    about a `length` on a machine that does not exist. What it gets right is `MACHINE_DEPENDENT`
    below; what it over-reaches on is here. A relative `dest` is not a verdict about a machine, it
    is a verdict
    about a string, and the server runs MAME from a scratch directory of its own whether or not
    one is booted.

    Which is why the rule names the property and not the argument.
    """
    mstate.STATE.kill()
    got = MACHINE_INDEPENDENT[name]()
    assert got["status"] == "INVALID", got
    assert got["code"] == "bad_argument", (
        f"{name} answered {got['code']!r}: this argument is as wrong with a machine as without "
        f"one, so the machine is not what the caller needs to hear about")
    assert "no machine running" not in got["message"], got["message"]
    # THE RULE THE ROW NAMES, not just a refusal: a row refused for a different reason than its
    # id says is a green about nothing (a path that happens to exist would refuse the row first).
    named = name.split("-", 1)[1] if "-" in name else None
    if named in ("length", "seconds", "width", "name", "addr", "file", "ceiling"):
        assert named in got["message"] or (named == "addr" and "reference_addr" in got["message"]) \
            or (named == "file" and "ROM" in got["message"]) \
            or (named == "ceiling" and "seconds" in got["message"]), (name, got["message"])


def test_a_batch_is_refused_whole_before_any_step_runs_even_with_no_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """NOTHING IN A STEP NEEDS A MACHINE TO BE WRONG, and `perform`'s own docstring has always
    promised the whole list is checked before its first step runs. It was checked inside
    `run_steps`, which the server only reaches after fetching the session, so the promise held on a
    warm server and not on a cold one -- and on a warm one a later step's `dest` was never checked
    at all, so the earlier steps ran for real first.
    """
    mstate.STATE.kill()
    for later in ({"op": "memdump", "ref": "0x0", "length": 8, "dest": "relative.bin"},
                  {"op": "snapshot", "dest": "relative.png"},
                  {"op": "record", "frames": 2, "dest": "relative.avi"},
                  {"op": "audio_record", "frames": 2, "dest": "relative.wav"}):
        out = s.perform(steps=[{"op": "status"}, later])
        assert out["code"] == "bad_argument", (later, out)
        assert (out["ran"] == []
                and out["steps_completed"] == 0), "a step ran before the list was refused"
        assert out["failed_at"] == 1, out
        assert "must be an absolute path" in out["errors"][0]["message"], out["errors"][0]


def test_a_warm_batch_is_also_refused_whole_for_a_later_steps_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE SAME THING WITH A MACHINE UP, which is the half that was observed from the outside: the
    earlier steps ran and the bad path was reported as an ordinary step failure. The list is refused
    whole now, and `ran` being empty is what says so."""
    _running(monkeypatch, tmp_path)
    # `snapshot` is the step the repository actually tried, and the one the batch table had left
    # out: `memdump` alone was covered, so a green here on `memdump` said nothing about `snapshot`.
    for later in ({"op": "memdump", "ref": "0x0", "length": 8, "dest": "relative.bin"},
                  {"op": "snapshot", "dest": "relative.png"}):
        out = s.perform(steps=[{"op": "status"}, later])
        assert out["code"] == "bad_argument", (later, out)
        assert (out["ran"] == []
                and out["steps_completed"] == 0), "a step ran before the list was refused"


@pytest.mark.parametrize("name", sorted(MACHINE_DEPENDENT))
def test_an_argument_only_the_machine_can_judge_still_waits_for_it(name: str) -> None:
    """THE CONTROL FOR THE RULE ABOVE, and without it that rule is half a sentence. A `ref` is
    resolved against the symbol table of a machine, so with none running there is nothing to
    resolve it against and `no_session` is the honest answer. A refactor that moved every
    argument in front of the gate would leave the test above green and this one red, which is the
    whole reason it exists.
    """
    mstate.STATE.kill()
    got = MACHINE_DEPENDENT[name]()
    got = refused("no machine running", got)
    assert got["code"] == "no_session", (
        f"{name} judged a machine-dependent argument with no machine to judge it against")


# ----------------------------------------------------------------- the RUNNING guest


class _RunningSession(_OwnRegisterFile, SessionFields):
    """A session with the PROTOCOL's running state: `go` runs, a stop arrives at a poll when
    the test has scheduled one (`stops_after_polls`), `interrupt` stops it at once, and the
    console answers `print frame`, `print curpc` and a `dasm` that WRITES its listing, so the
    stop survey the tools build is exercised against a file the way the real console feeds it.
    """

    def __init__(self, scratch: Path, pcs: list[int] | None = None) -> None:
        self.scratch = scratch
        self.running = False
        self.stop_count = 0
        self.threads: dict[int, str] = {}
        self.last_stop_packet = ""
        self.broken: str | None = None
        self.stops_after_polls: int | None = None
        self.polls = 0
        self.pcs = pcs or [0xF2034, 0x4A0, 0x25A4]
        self.pointer_width = 4                   # a 68000: a pointer is a long
        self.frame = 100
        self.values = {"D0": 0x1234, "PC": 0xF2034}
        self.commands: list[str] = []
        self.armed: list[tuple[int, bool]] = []
        self.bplist_rows: list[str] = []      # what the console's `bplist` lists on a real board
        self.bp_next_index = 1                # MAME's breakpoint counter, never reused
        self.bp_devices: dict[int, str] | None = None   # a row's cpu, by index
        self.rplist_rows: list[tuple[int, str, bool]] = []   # what `rplist` lists
        self.rp_next_index = 1                # the registerpoints' own counter, never reused
        self.rp_devices: dict[int, str] = {}       # the cpu of a row that is not the main one's
        self.rp_errors: dict[str, str] = {}        # what `rpset` AND `print` refuse, by condition
        self.rp_print_errors: dict[str, str] = {}  # what `print` alone refuses (MAME arms it)
        self.temps: dict[int, int] = {}       # the debugger's temp variables, moved by a test
        self.exprs: dict[str, int] = {}       # what `print <name>` answers for an expression
        self.writes = 0
        self.interrupted = 0
        self.byte_order = "big"               # read by the watch family on any session
        self.packet_size: int | None = None   # what a stub advertises; this one says nothing
        self.emu_clock = 0.0
        self.visible_cpu = ":maincpu"            # the cpu `cpulist` marks, moved by a test
        self.ignoring: list[str] = []            # the cpus `ignore` lists
        self.no_map: set[int] = set()            # threads whose register block is refused
        self.live: str | None = None             # the cpu the last stop was on; None: visible

    # The real rules, not copies of them: they read nothing but `packet_size`.
    max_payload = g.Session.max_payload
    console_packet = g.Session.console_packet

    def emulated_seconds(self) -> float:
        return self.emu_clock

    def know_endianness(self, by_thread: dict[int, str]) -> None:
        self.endianness = dict(by_thread)    # the layout double decodes big whatever it hears

    def registers(self, *, thread: int) -> dict[str, int]:
        self._on("g", thread)
        return dict(self.values)

    def _on(self, packet: str, thread: int) -> None:
        """A register or memory packet for a thread other than the first, noted as
        `<packet>@<thread>`: what a case reads to know which cpu a call went through."""
        if thread != 1:
            self.commands.append(f"{packet}@{thread}")

    def current_pc(self) -> int:
        return self.pcs[min(self.stop_count, len(self.pcs) - 1)]

    def go(self) -> None:
        self.running = True
        self.polls = 0

    def _stop(self) -> None:
        self.running = False
        self.stop_count += 1
        self.frame += 60
        self.last_stop_packet = "T05"

    def poll_stop(self, timeout: float = 0.0) -> bool:
        if not self.running:
            return True
        self.polls += 1
        if self.stops_after_polls is not None:
            self.stops_after_polls -= 1           # a countdown, so it is set at any moment
            if self.stops_after_polls <= 0:
                self.stops_after_polls = None
                self._stop()
                return True
        return False

    def interrupt(self, timeout: float = 5.0) -> str:
        self.interrupted += 1
        self._stop()
        return "T05"

    def step(self) -> str:
        self.running = True
        self._stop()
        return "T05"

    def breakpoint(self, addr: int, remove: bool = False) -> None:
        """What a plain `bp` does to the debugger's list, which the console half routes here
        (`session_doubles.control_console`): a row under the next index, logged in `armed`. A
        case replaces it to stand in for the debugger, one that takes a row and lists none."""
        self.armed.append((addr, False))
        bplist_add(self, addr)

    def make_visible(self, thread: int) -> None:
        """`Hc`, as the patched stub answers it: the thread's cpu visible and no ignore flag
        touched; a cpu the debugger ignores is refused (`E01`, captured)."""
        self.commands.append(f"Hc{thread:x}")
        tag = self.threads[thread]
        if tag in self.ignoring:
            raise g.Refused(f"the stub refused `Hc{thread:x}`: E01")
        self.visible_cpu = tag

    def stopped_thread(self) -> int | None:
        """`?`: the thread of the cpu the last stop was on, which an `Hc` does not move."""
        self.commands.append("?")
        tag = self.live or self.visible_cpu
        return next((tid for tid, name in self.threads.items() if name == tag), None)

    def register_block(self, thread: int) -> str:
        """One thread's whole `g` reply, which a run changes: the thread and the frame in it.
        A thread in `no_map` is refused, as the stub refuses a cpu with no register map."""
        self.commands.append(f"g{thread:x}")
        if thread in self.no_map:
            raise g.Refused("the stub refused `g`: E01")
        return f"{thread:08x}{self.frame:08x}"

    def read(self, addr: int, n: int, *, thread: int) -> bytes:
        self._on("m", thread)
        return bytes(n)

    def write(self, addr: int, data: bytes, *, thread: int) -> None:
        self._on("M", thread)
        self.writes += 1

    def reg(self, name: str, *, thread: int) -> int:
        self._on("p", thread)
        return self.values[name.upper()]

    def register_width(self, name: str) -> int:
        return 32

    def register_name(self, name: str) -> str:
        return name.upper()

    def set_reg(self, name: str, value: int, *, thread: int) -> None:
        self._on("P", thread)
        self.writes += 1
        self.values[name.upper()] = value

    # The lifecycle and the known-answer half, inert: the tests of those drive `start` and
    # `close` on their own doubles; these exist so THIS double has the whole surface the
    # package calls on a session, which the AST case below holds it to.
    def connect(self) -> None:
        pass

    def dial(self) -> None:
        pass

    def handshake(self, timeout: float | None = None) -> None:
        pass

    def close(self) -> None:
        pass

    def quit(self) -> None:
        self.commands.append("quit")

    def halt(self) -> None:
        self._stop()

    def reset(self) -> int:
        # The real one steps once to apply the reset, and that step is a STOP the stub
        # counts: a reset that leaves it unrecorded is found by the next contact as a stop
        # the machine reached on its own.
        self.commands.append("softreset")
        self.writes += 1
        self._stop()
        return self.current_pc()

    def request(self, cmd: str, timeout: float | None = None) -> str:
        self.commands.append(cmd)
        return "OK"

    def self_check(self, rom: bytes, addr: int, n: int = 16, base: int = 0, *,
                   thread: int) -> None:
        self._on("rom", thread)

    def determinism(self, addr: int, n: int = 16, times: int = 5, *, thread: int) -> bool:
        return True

    def cost_per_query(self, addr: int, n: int = 16, times: int = 200, *,
                       thread: int) -> float:
        return 0.0

    def monitor(self, command: str, timeout: float = 10.0) -> str:
        self.commands.append(command)
        if (listed := debugger_lists(self, command)) is not None:
            return listed
        if command.startswith("print "):
            values: list[str] = []
            for name in command[6:].split(","):
                if name == "frame":
                    values.append(f"{self.frame:x}")
                elif name == "curpc":
                    values.append(f"{self.current_pc():x}")
                elif name in self.exprs:
                    values.append(f"{self.exprs[name]:x}")
                elif name == "totalcycles":
                    values.append(f"{self.frame * 0x1000:x}")
                else:
                    return f"Error: unable to evaluate {name}\n"   # a double's spelling
            return " ".join(values) + "\n"
        if command.startswith("dasm "):
            name, addr = command[5:].split(",")[:2]      # a cpu may follow the length
            (self.scratch / name).write_text(f"{addr[2:]}: move.l d0,d1\n{addr[2:]}+2: rts\n")
            return ""
        return ""

    def monitor_owed(self, command: str, timeout: float = 10.0) -> None:
        self.monitor(command, timeout)


class _AliveProcess:
    """A process that is up, and nothing else: what `log_wait`'s liveness check reads."""

    pid = 4242

    def poll(self) -> int | None:
        return None


def _running(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
             ses: _RunningSession | None = None) -> _RunningSession:
    """Install a running-capable double, parked at its first stop the way `start` parks."""
    ses = ses or _RunningSession(tmp_path)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    use_table(monkeypatch, table={})
    monkeypatch.setattr(mstate.STATE, "proc", _AliveProcess())
    monkeypatch.setattr(mstate.STATE, "ses", ses)      # the envelope reads `running` off it
    # What `start` creates beside the session: a session-lived store and the stamp.
    monkeypatch.setattr(mstate.STATE, "store", dec.DeclarationStore("test", path=None))
    monkeypatch.setattr(mstate.STATE, "session_origin", "s1")
    monkeypatch.setattr(mstate.STATE, "first_cpu", ":maincpu")      # the doubles' first cpu
    monkeypatch.setattr(mstate.STATE, "fingerprints", {":maincpu": "fp-test"})
    monkeypatch.setattr(mstate.STATE, "armed_watches", {})
    monkeypatch.setattr(mstate.STATE, "tallies", {})
    monkeypatch.setattr(mstate.STATE, "controls", {})
    monkeypatch.setattr(mstate.STATE, "debuglog_mark", 0)
    running.record_park(ses, tmp_path)  # type: ignore[arg-type]
    return ses


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


def test_resume_without_a_bound_lets_the_machine_run_and_the_readers_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE RUNNING-GUEST CONTRACT: a reader on a running machine
    answers INVALID, names the last stop and the tools that DO answer, and never a value
    read off a moving machine."""
    ses = _running(monkeypatch, tmp_path)
    out = s.resume()
    assert "verdict" not in out and out["session"]["running"] is True and ses.running
    assert out["session"]["running"] is True
    assert out["summary"] == "resume: running, no wait asked"
    calls: dict[str, Callable[[], dict[str, Any]]] = {
        "registers": lambda: s.registers(),
        "read_memory": lambda: s.read_memory(ref="0x0"),
        "disassemble": lambda: s.disassemble(ref="0x0"),
        "find": lambda: s.find(ref="0x0", length=4, data_hex="00"),
        "history": lambda: s.history(),
        "memdump": lambda: s.memdump(ref="0x0", length=4, dest=str(tmp_path / "x.bin")),
        "debug": lambda: s.debug(command="print pc"),
        "step": lambda: s.step(),
        "run_to": lambda: s.run_to(ref="0x4a0", control="0x25a4"),
        "run_for": lambda: s.run_for(milliseconds=10),
        "write": lambda: s.write(ref="0x0", data_hex="00"),
        "set_register": lambda: s.set_register(name="D0", value=1),
        "reset": lambda: s.reset(),
        "resume": lambda: s.resume(),
    }
    for name, call in calls.items():
        refused = call()
        assert refused["status"] == "INVALID", name
        assert "no stop has been read since" in refused["message"], refused
        assert refused["summary"].startswith(f"{name}: INVALID")
        assert refused["last_stop"]["stop_seq"] == 1 and refused["last_stop"]["cause"] == "start"
        assert refused["last_stop"]["pc"] == "0x000f2034"
        assert "status" in refused["answers_while_running"]
        # THE REMEDY ANSWERS: every tool the refusal sends the caller to is one that answers
        # while the machine runs, never a reader that refuses for the same reason.
        named = [n for n in re.findall(r"`([a-z_]+)`", refused["message"])
                 if callable(getattr(s, n, None))]
        assert named and all(n in refused["answers_while_running"] or n == name
                             for n in named), (name, named)
        assert list(refused)[-1] == "session", "the envelope holds on a refusal too"
    assert "a second `resume` has no state" in s.resume()["message"].lower()
    assert ses.running, "no refusal stopped the machine"
    assert ses.commands == ["cpulist", "print frame", "dasm dasm.txt,0xf2034,0x20"], (
        "nothing was read off the running machine: only the park's survey touched the console")
    # What answers meanwhile: the last stop's registers, marked superseded and dated.
    older = s.registers(from_last_stop=True)
    assert older["superseded"] is True and older["regs"] == {"D0": "0x00001234", "PC": "0x000f2034"}
    assert older["last_stop"]["stop_seq"] == 1 and "from the last stop" in older["summary"]
    listed = s.declaration_list("breakpoint")
    assert listed["session"]["running"] is True and listed["last_stop"]["stop_seq"] == 1
    st = s.status()
    assert (st["session"]["running"] is True and isinstance(st["pc"], dict)
            and st["last_stop"]["pc"] == "0x000f2034")
    assert st["last_stop"]["stop_seq"] == 1
    assert "RUNNING" in st["summary"]


def test_a_stop_the_machine_reached_on_its_own_is_recorded_by_the_first_contact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A breakpoint fires while nobody waits: the first tool that touches the session finds
    the stop packet, surveys the stop once, records it as the last stop and says so in its
    reply, ONCE. Without that, `last_stop` stays on the previous stop while `registers`
    reads the address of the new one."""
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    s.resume()
    ses.stops_after_polls = 1                    # the breakpoint fires
    st = s.status()
    assert st["session"]["running"] is False and st["stopped_on_its_own"]["stop_seq"] == 2
    assert st["stopped_on_its_own"]["cause"] == "breakpoint at 0x4a0"
    assert st["last_stop"]["stop_seq"] == 2 and st["pc"] == "0x000004a0"
    assert "stopped_on_its_own" not in s.status(), "reported once, by the contact that found it"
    regs = s.registers()
    assert regs["status"] == "ok", "the readers answer again"


def test_a_call_that_steps_and_then_refuses_owns_its_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A refusal that comes after the call's own step owns that stop (`record_own_stop` says
    why): the next contact finds nothing on its own, and the record names the tool."""
    _running(monkeypatch, tmp_path)

    def steps_then_refuses(ses_: Any, *_: Any) -> dict[str, Any]:
        ses_.step()
        raise mstate.Invalid("unknown_ref", "the map entry names no share and no region")

    monkeypatch.setattr(block, "read_block", steps_then_refuses)
    refused_ = s.read_block(ref="0x4a0")
    assert refused_["code"] == "unknown_ref", refused_
    after = s.status()
    assert "stopped_on_its_own" not in after, after["stopped_on_its_own"]
    assert after["last_stop"]["stop_seq"] == 2, after["last_stop"]
    assert after["last_stop"]["cause"].startswith("read_block"), after["last_stop"]
    assert after["pc"] == after["last_stop"]["pc"], "the record describes where the machine is"


def test_a_refusal_that_moved_nothing_records_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The other side of `record_own_stop`: a refusal before any step leaves the record as it
    was and never surveys, so an ordinary argument refusal costs the console nothing."""
    _running(monkeypatch, tmp_path)

    def must_not_survey(*_: Any) -> dict[str, Any]:
        raise AssertionError("a refusal that moved nothing surveyed the machine")

    monkeypatch.setattr(running, "survey", must_not_survey)
    refused_ = s.read_block(tag="main cpu")
    assert refused_["code"] == "bad_argument", refused_
    assert mstate.STATE.last_stop["seq"] == 1 and mstate.STATE.last_stop["cause"] == "start"


class _GoneProcess:
    def poll(self) -> int | None:
        return 0


class _CrashedProcess:
    """A MAME that died of a signal while the session still held it."""

    pid = 4242

    def poll(self) -> int | None:
        return -11


def test_status_on_a_machine_that_died_under_its_session_names_the_exit_and_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Not the bare `alive: false` of no session at all: the process is gone while the session
    still holds it, so the reply carries the exit code and says `close` collects the rest."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "proc", _CrashedProcess())
    out = s.status()
    assert (out["status"] == "ok" and out["session"]["alive"] is False
            and out["exit_code"] == -11), out
    assert "`close` collects the exit code" in out["note"], out


@pytest.mark.parametrize("state", ["running", "process gone", "no process", "no scratch"])
def test_a_stop_is_not_recorded_for_a_machine_that_cannot_be_surveyed(
    state: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The states a refusal can find the session in: a machine let go, an emulator that
    went, a session half torn down."""
    ses = _running(monkeypatch, tmp_path)
    ses.step()
    if state == "running":
        ses.running = True
    elif state == "no scratch":
        monkeypatch.setattr(mstate.STATE, "scratch", None)
    else:
        monkeypatch.setattr(mstate.STATE, "proc",
                            _GoneProcess() if state == "process gone" else None)

    def must_not_survey(*_: Any) -> dict[str, Any]:
        raise AssertionError(f"surveyed with {state}")

    monkeypatch.setattr(running, "survey", must_not_survey)
    running.record_own_stop("lua")
    assert mstate.STATE.last_stop["seq"] == 1


def test_a_stop_that_cannot_be_surveyed_leaves_the_refusal_as_it_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The record of the refusing call's own stop is a courtesy to the NEXT call, never a new
    way for this one to fail: a session that broke under it keeps its refusal, and the stop
    stays for the next contact to find."""
    _running(monkeypatch, tmp_path)

    def steps_then_refuses(ses_: Any, *_: Any) -> dict[str, Any]:
        ses_.step()
        raise mstate.Invalid("unknown_ref", "the map entry names no share and no region")

    def broken(*_: Any) -> dict[str, Any]:
        raise g.SessionError("the stub closed the connection")

    monkeypatch.setattr(block, "read_block", steps_then_refuses)
    monkeypatch.setattr(running, "survey", broken)
    refused_ = s.read_block(ref="0x4a0")
    assert refused_["status"] == "INVALID" and refused_["code"] == "unknown_ref", refused_
    assert mstate.STATE.last_stop["seq"] == 1, "nothing was recorded from a survey that broke"


def test_resume_with_a_bound_waits_for_the_stop_and_returns_the_survey(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(running, "RESUME_POLL_S", 0.0)
    ses.stops_after_polls = 3
    out = s.resume(seconds=2.0)
    assert "running" not in out, out
    assert out["verdict"] == "OTHER_STOP" and out["session"]["running"] is False
    assert out["waited_s"] < 1.0
    assert out["cause"] == "stopped at no breakpoint this server armed"
    assert out["pc"] == "0x000004a0" and out["frame"] == 160
    assert out["regs"] == {"D0": "0x00001234", "PC": "0x000f2034"}
    assert out["dasm"] == ["4a0: move.l d0,d1", "4a0+2: rts"]
    assert out["errorlog"] == {"lines_total": 0, "truncated": False, "lines": [], "mark": 0}
    assert out["summary"] == ("resume: OTHER_STOP at pc 0x000004a0 (stopped at no breakpoint "
                              "this server armed)")
    # And a bound that expires LEAVES IT RUNNING, unlike run_to.
    out = s.resume(seconds=0.05)
    assert "running" not in out, out
    assert out["verdict"] == "TIMEOUT" and out["session"]["running"] is True and ses.running
    assert "was LEFT RUNNING" in out["note"] and ses.interrupted == 0


def test_stop_interrupts_a_running_machine_and_surveys_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.resume()
    out = s.stop()
    assert out["interrupted"] is True and out["cause"] == "interrupt" and ses.interrupted == 1
    assert out["pc"] == "0x000004a0"
    assert out["summary"] == "stop: interrupted at pc 0x000004a0, frame 160"
    again = s.stop()
    assert again["interrupted"] is False and again["last_stop"]["stop_seq"] == 2
    assert ses.interrupted == 1, "nothing is sent to a stopped machine"


def test_the_stop_survey_shows_the_log_since_the_previous_stop_capped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The delta is what the driver logged BETWEEN two stops, not the whole log, and above the
    cap the count stays whole while the lines are the newest."""
    log = tmp_path / "error.log"
    log.write_text("boot\n")
    ses = _running(monkeypatch, tmp_path)              # stop 1 reads `boot`
    assert mstate.STATE.errorlog_mark == 5
    with open(log, "a") as fh:
        fh.write("".join(f"line {i}\n" for i in range(10)))
    ses.stops_after_polls = 1
    out = s.resume(seconds=1.0)
    assert out["errorlog"]["lines_total"] == 10 and len(out["errorlog"]["lines"]) == 8
    assert out["errorlog"]["truncated"] is True and out["errorlog"]["lines"][-1] == "line 9"
    assert out["errorlog"]["lines"][0] == "line 2"
    ses.stops_after_polls = 1
    assert s.resume(seconds=1.0)["errorlog"]["lines_total"] == 0


def test_breakpoints_arm_and_clear_while_running_and_say_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `Z0` sent to a running machine is taken and FIRES, so nothing
    is queued; the reply says it was armed while running."""
    ses = _running(monkeypatch, tmp_path)
    s.resume()
    armed = s.breakpoint_at(ref="0x25a4")
    assert armed["while_running"] is True and ses.armed == [(0x25A4, False)]
    assert armed["summary"] == "breakpoint_at 0x25a4: armed at 0x000025a4 while running"
    cleared = s.declaration_clear("breakpoint", ref="0x25a4")
    assert cleared["while_running"] is True and "bpclear 0x1" in ses.commands
    assert ses.running


def test_log_wait_answers_the_log_first_then_waits_and_refuses_honestly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import threading

    log = tmp_path / "error.log"
    log.write_text("boot done\n")
    ses = _running(monkeypatch, tmp_path)
    # Already there: no wait, and the machine may be stopped for that.
    out = s.log_wait(channel="emulator", pattern="boot", seconds=1.0)
    assert out["already"] is True and out["line"] == "boot done" and out["waited_s"] == 0.0
    assert out["summary"] == "log_wait emulator /boot/: matched already there"
    # Not there and the machine STOPPED: refused at once, naming the stop.
    out = s.log_wait(channel="emulator", pattern="scene", seconds=1.0)
    assert out["status"] == "INVALID" and "STOPPED" in out["message"]
    assert out["last_stop"]["stop_seq"] == 1
    # Running: a line that arrives during the wait is found, with its counts.
    s.resume()

    def later() -> None:
        time.sleep(0.15)
        with open(log, "a") as fh:
            fh.write("noise\nscene 3 drawn\n")

    threading.Thread(target=later).start()
    out = s.log_wait(channel="emulator", pattern="scene", seconds=3.0)
    assert out["already"] is False and out["line"] == "scene 3 drawn" and out["waited_s"] > 0.1
    assert out["arrived_during"] == 2 and out["lines_before"] == 2 and out["lines_examined"] == 3
    # A bound that expires is a TIMEOUT and says what it examined.
    out = s.log_wait(channel="emulator", pattern="never", seconds=0.15)
    assert out["status"] == "ok" and out["verdict"] == "TIMEOUT", out
    assert "bound that expired" in out["note"]
    assert out["arrived_during"] == 0 and "NOTHING" in out["note"]
    # A stop DURING the wait ends it, naming the stop, after one last read.
    ses.stops_after_polls = 2
    out = s.log_wait(channel="emulator", pattern="never", seconds=1.0)
    assert out["status"] == "INVALID" and "STOPPED during" in out["message"]
    assert out["last_stop"]["stop_seq"] == 2 and not ses.running
    assert out["stopped_on_its_own"]["stop_seq"] == 2, "the stop the wait found is recorded"
    # Bad arguments are refused; the machine is asked for FIRST (the no-machine test).
    refused("seconds",
    s.log_wait(channel="emulator", pattern=".", seconds=0))
    refused("does not compile",
    s.log_wait(channel="emulator", pattern="[", seconds=1))


def test_log_wait_reports_progress_while_it_waits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.go()
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    ticks: list[tuple[float, float | None, str]] = []
    out = _wait_emulator(ses, tmp_path, lambda: True, lambda: None,
                              "never", 0.1, lambda p, t, m: ticks.append((p, t, m)))
    assert out["verdict"] == "TIMEOUT"
    assert ticks and all(t is None and "log_wait emulator /never/" in m for _p, t, m in ticks)


def test_run_to_and_run_for_report_progress_while_they_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    ticks: list[str] = []
    ses.stops_after_polls = 3
    out = advance.run_to(ses, tmp_path, "0x4a0", "0x25a4", 1.0,  # type: ignore[arg-type]
                         lambda p, t, m: ticks.append(m))
    assert out["verdict"] == "TARGET" and ticks and "run_to 0x4a0" in ticks[0]
    reg = _RegisterSession(bits=32, frame=10, stop_after=4)
    _install(monkeypatch, reg, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    ticks.clear()
    out = advance.run_for(reg, tmp_path, 100, 5.0,  # type: ignore[arg-type]
                          lambda p, t, m: ticks.append(m))
    assert out["verdict"] == "ELAPSED" and ticks and "run_for 100 ms" in ticks[0]


class _RecordingCtx:
    """The SDK's `Context` as far as progress goes: every report, in order."""

    def __init__(self) -> None:
        self.got: list[tuple[float, float | None, str | None]] = []

    async def report_progress(self, progress: float, total: float | None = None,
                              message: str | None = None) -> None:
        self.got.append((progress, total, message))


def test_the_sdk_injects_the_context_and_the_schema_does_not_show_it() -> None:
    """`ctx` is found by its type through the wrapper (`functools.wraps` carries the
    annotations), it is not an argument the client can pass, and it stays out of the summary."""
    for name in ("run_to", "run_for", "resume", "log_wait"):
        tool = s.mcp._tool_manager.get_tool(name)
        assert tool is not None and tool.context_kwarg == "ctx", name
        assert "ctx" not in tool.parameters.get("properties", {}), name
    for name in ("step", "stop", "registers"):
        tool = s.mcp._tool_manager.get_tool(name)
        assert tool is not None and tool.context_kwarg is None, name


def test_the_session_block_says_whether_the_machine_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    assert menvelope.session_block()["running"] is False
    ses.go()
    assert menvelope.session_block()["running"] is True
    assert list(menvelope.session_block()) == ["alive", "running", "altered", "omitted",
                                                       "how"]
    assert list(menvelope.session_block(True)) == ["alive", "running", "altered",
                                                   "altering_writes", "console"]


def test_log_wait_reads_the_log_one_last_time_before_every_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The loop checks the condition FIRST and reads LAST, so a line written in between was
    never looked for: the exit trace of a driver going away, the reaction logged just before
    a breakpoint fired, the line that lands between the final poll and the clock. Each path
    reads once more, and only then refuses."""
    log = tmp_path / "error.log"
    log.write_text("boot\n")
    ses = _running(monkeypatch, tmp_path)
    ses.go()
    monkeypatch.setattr(core_wait, "POLL_S", 0.0)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)

    def writes(line: str) -> Callable[[], None]:
        def write() -> None:
            with open(log, "a") as fh:
                fh.write(line + "\n")
        return write

    # A stop DURING the wait: the reaction logged just before the breakpoint is found.
    ses.stops_after_polls = 2
    out = _wait_emulator(ses, tmp_path, lambda: True,
                              writes("reaction before the stop"), "reaction", 1.0)
    assert out["status"] == "ok" and out["line"] == "reaction before the stop"
    assert out["already"] is False and not ses.running
    # The emulator GONE: the exit trace is found; with nothing to find, the refusal says GONE.
    ses.go()
    gone = writes("driver exit")
    out = _wait_emulator(ses, tmp_path, lambda: (gone(), False)[1],
                              lambda: None, "exit", 1.0)
    assert out["status"] == "ok" and out["line"] == "driver exit"
    out = _wait_emulator(ses, tmp_path, lambda: False, lambda: None,
                              "never", 1.0)
    assert out["status"] == "INVALID" and "GONE" in out["message"]
    # The two cases at the CLOCK are scripted (a hundredth per reading), so the loop runs
    # exactly one iteration and what happens after it is deterministic.
    class _Clock:
        now = 0.0

        def monotonic(self) -> float:
            self.now += 0.01
            return self.now

        def sleep(self, seconds: float) -> None:
            pass

    clock = _Clock()
    monkeypatch.setattr(core_wait, "time", clock)
    monkeypatch.setattr(mstate, "time", clock)
    monkeypatch.setattr(mprogress, "time", clock)  # the Ticker reads the same scripted clock
    # A line landing between the final read and the deadline is found by the last look (the
    # progress callback fires after the read, so it plays the driver writing right then).
    out = _wait_emulator(ses, tmp_path, lambda: True, lambda: None,
                              "late", 0.015, lambda p, t, m: writes("late line")())
    assert out["status"] == "ok" and out["line"] == "late line" and out["already"] is False, out
    assert out["waited_s"] == 0.0, ("a wait is spelled to the tenth of a second, and this one "
                                    "took a hundredth", out)
    # And a stop that lands as the bound expires is named as such: one clock read per
    # iteration now, so a bound of one and a half readings expires after the first poll,
    # and the second poll is the last look's.
    ses.stops_after_polls = 2
    out = _wait_emulator(ses, tmp_path, lambda: True, lambda: None,
                              "never", 0.015)
    assert out["status"] == "INVALID" and "STOPPED as the bound expired" in out["message"]


def test_renaming_a_log_channel_reaches_every_consumer_through_the_constant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE CONSTANT EXISTED AND ALMOST NOBODY DRANK FROM IT. `LOG_FILES` held the two names
    while the launcher and the Lua channel spelled them by hand at ten sites between them, so
    a rename of either channel would have moved one map and left ten readers opening a file
    nothing writes any more -- and every one of those readers answers EMPTY for a file that is
    not there, which is indistinguishable from a quiet emulator.

    So the rename is what this asks for: both names are changed and every consumer that can
    answer without an emulator is put to it. A consumer still holding the literal reads a
    file that does not exist, and the empty answer it gives back is what goes red here."""
    import mame_transport as transport
    monkeypatch.setitem(files.LOG_FILES, "emulator", "renamed-emulator.log")
    monkeypatch.setitem(files.LOG_FILES, "process", "renamed-process.log")
    (tmp_path / "renamed-emulator.log").write_text("DRIVER: a line\n", encoding="utf-8")
    (tmp_path / "renamed-process.log").write_text(
        f"{launch.CFG_PARSE_ERROR}: nonsense\n", encoding="utf-8")
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
    # THE TWO LUA READERS THAT LOOK FOR A SHAPE, not merely for bytes: both answer None/0 for
    # a file that is not there, which is what a consumer still holding the literal produces
    # and is indistinguishable from a console that has not replied yet.
    answered = f"echo-me\n{mstate.LUA_SENTINEL}#7\ttrue\t\n"
    (tmp_path / "renamed-process.log").write_text(answered, encoding="utf-8")
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
    """THE WRITER, which the reader gate above cannot reach.

    Every consumer in that test READS a log. The one call that OPENS the file MAME's stdout is
    captured into lives inside `boot`, behind a launch, so a gate that never launches cannot
    see it: this is the one case that goes red when that line reverts to the literal. A writer
    spelling one name while every reader spells
    another produces an empty log and a session that looks quiet."""
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


def test_a_log_shorter_than_its_mark_is_read_from_the_start(tmp_path: Path) -> None:
    """A mark past the end describes a file that no longer exists (MAME rewrote it)."""
    log = tmp_path / "error.log"
    log.write_text("a\nb\nc\n")
    assert files.errorlog_since(tmp_path, 0) == (["a", "b", "c"], 6)
    assert files.errorlog_since(tmp_path, 4) == (["c"], 6)
    log.write_text("x\n")
    assert files.errorlog_since(tmp_path, 6) == (["x"], 2)
    # A CRLF log, and a line still being written: the half line is NOT a line yet, the mark
    # stays before it, and it is seen whole, once, when its newline arrives.
    log.write_text("p\r\nq")
    assert files.errorlog_since(tmp_path, 0) == (["p"], 3)
    with open(log, "a") as fh:
        fh.write("uiet\n")
    assert files.errorlog_since(tmp_path, 3) == (["quiet"], 9)
    assert files.errorlog_since(tmp_path / "none", 0) == ([], 0)


def test_a_frame_that_is_not_a_number_is_the_consoles_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _RunningSession(tmp_path)
    ses.monitor = lambda command, timeout=10.0: "T05thread:01;\n"  # type: ignore[method-assign]
    with pytest.raises(g.SessionError, match="print frame"):
        read.frame(ses)  # type: ignore[arg-type]
    ses.monitor = lambda command, timeout=10.0: ""  # type: ignore[method-assign]
    with pytest.raises(g.SessionError, match="nothing"):
        read.frame(ses)  # type: ignore[arg-type]


def test_resume_refuses_a_negative_bound_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    refused(r"^seconds=-1 is not a bound: .*0 \(no deadline\)",
    s.resume(seconds=-1))
    assert not ses.running, "a refused resume never released the machine"
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    monkeypatch.setattr(running, "RESUME_POLL_S", 0.0)
    ticks: list[str] = []
    out = running.resume(ses, tmp_path, 0.02, lambda p, t, m: ticks.append(m))  # type: ignore[arg-type]
    assert out["verdict"] == "TIMEOUT" and ticks and ticks[0].startswith("resume: running")


# --------------------------------------- what start hands the driver, and says it handed


def test_start_reports_the_env_the_display_and_the_flags_it_handed_over(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A watched run has to say which variant it is: the reply carries the variables this
    call added, the display it went to (the session's exported answer when `display` is
    empty), and the flags, so a reader of the reply and not of the process can check them."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    fake, log = _recording_helper(tmp_path)
    monkeypatch.setenv("WINDOW_APP", str(fake))
    monkeypatch.setenv("WINDOW_SHARED_DISPLAY", "main")
    out = s.start(**_boot_args(tmp_path, image), shared=True, env={"M68K_DUAL_SWITCH": "on"})
    try:
        assert out.get("display", "") == "main" and out.get("env", {}) == {"M68K_DUAL_SWITCH": "on"}
        assert log.read_text().split() == ["mame", "--shared", "--display", "main"], (
            "the exported answer reaches the helper explicitly, so the reply and the helper agree")
        assert out["flags"] == ["-window", "-nomaximize"] and out.get("throttle_from_frame", 0) == 0
        assert _StubProcess.last_kwargs.get("env", {})["M68K_DUAL_SWITCH"] == "on"
        assert Path(out["boot_lua_path"]).parent == mstate.STATE.scratch, (
            "the server writes the one boot script on every start, for the inventory")
        assert isinstance(out["frame"], int) or out["frame"]["available"] is False
    finally:
        s.close()
    monkeypatch.delenv("WINDOW_SHARED_DISPLAY")
    out = s.start(**_boot_args(tmp_path, image), shared=True)
    try:
        assert out.get("display", "") == "secondary", "the helper's default, said out loud"
    finally:
        s.close()
    out = s.start(**_boot_args(tmp_path, image))
    try:
        assert "display" not in out and "env" not in out, "a quick run has no display to report"
    finally:
        s.close()
    monkeypatch.setenv("WINDOW_SHARED_DISPLAY", "tv")
    _never_spawns(monkeypatch, tmp_path)
    refused("WINDOW_SHARED_DISPLAY",
    s.start(**_boot_args(tmp_path, image), shared=True))


@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize(("shared", "background", "behind"), [
    (False, None, True), (True, None, False),
    (False, False, False), (True, True, True),
])
def test_start_launches_behind_by_who_watches_unless_background_says_otherwise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, shared: bool, background: bool | None,
    behind: bool, inherited: bool,
) -> None:
    """A quick start nobody watches leaves the owner's focus alone, a shared one comes to the
    front, and `background` overrides either for one run. The hint is read from the SPAWNED
    environment, the only place MAME reads it; with the server's own environment holding it or
    not, a launch behind proves it was added and one in front that it was removed."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    fake, _log = _recording_helper(tmp_path)
    monkeypatch.setenv("WINDOW_APP", str(fake))
    if inherited:
        monkeypatch.setenv("SDL_MAC_BACKGROUND_APP", "1")
    else:
        monkeypatch.delenv("SDL_MAC_BACKGROUND_APP", raising=False)
    out = s.start(**_boot_args(tmp_path, image), shared=shared, background=background)
    try:
        assert out["status"] == "ok", out
        assert out["background"] is behind, "the reply says which way it was launched"
        spawned = _StubProcess.last_kwargs.get("env", {})
        assert spawned.get("SDL_MAC_BACKGROUND_APP") == ("1" if behind else None), (
            "the name SDL3 reads, spelled out: a typo in the constant would pass with it")
    finally:
        s.close()


@pytest.mark.parametrize("value", ["1", "0", ""])
@pytest.mark.parametrize("background", [None, False, True])
def test_env_carrying_the_background_hint_is_refused_before_any_emulator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str, background: bool | None
) -> None:
    """Two spellings of one switch let the reply name one while the process obeys the other,
    so the hint is `background`'s alone, whatever value `env` gives it and whatever
    `background` says beside it."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    _never_spawns(monkeypatch, tmp_path)
    out = refused("background=True", s.start(**_boot_args(tmp_path, image),
                                             env={"SDL_MAC_BACKGROUND_APP": value},
                                             background=background))
    assert out["code"] == "bad_argument" and "SDL_MAC_BACKGROUND_APP" in out["message"]
    assert mstate.STATE.proc is None and mstate.STATE.scratch is None, (
        "a start that did not start owns nothing")


def test_a_system_this_build_does_not_carry_refuses_the_start_in_mame_s_own_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each repository ships its own narrow MAME, so which systems exist is the BINARY's
    answer. `start` asks it beside the boot, and a system it does not carry is refused in
    MAME's own words, the emulator killed, instead of as a gdbstub that never answers after the
    whole `wait`."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    # The shape of the real refusal: exit code 5, the sentence on stderr.
    Path(args["binary"]).write_text(
        "#!/bin/sh\necho \"No matching machines found for '$1'\" >&2\nexit 5\n")
    Path(args["binary"]).chmod(0o755)
    out = refused("does not carry", s.start(**{**args, "system": "notthisone"}))
    assert "No matching machines found for 'notthisone'" in out["message"]
    assert out["exit_code"] == 5
    assert mstate.STATE.ses is None and mstate.STATE.scratch is None, (
        "a start that did not start owns nothing")


def test_when_the_boot_fails_the_query_holds_the_cause_and_it_outranks_the_symptom(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The query is put before the boot and collected after the park, so a system the build
    does not carry is not refused until the emulator has already failed to come up. What the
    boot reports then is that the gdbstub never answered, which is true and useless; the query
    holds the real diagnosis in MAME's own words, and it is collected FIRST so that the cause
    outranks the symptom.

    Nothing is stubbed here but the clock: the binary really runs, really answers rc=5, and
    really fails to serve a gdbstub."""
    image = bytes(range(64))
    args = _boot_args(tmp_path, image)
    Path(args["binary"]).write_text(
        "#!/bin/sh\nfor a in \"$@\"; do [ \"$a\" = -listxml ] && "
        "{ echo \"No matching machines found for '$1'\" >&2; exit 5; }; done\nexit 0\n")
    Path(args["binary"]).chmod(0o755)
    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "no-helper"))
    out = refused("does not carry",
                  s.start(**{**args, "system": "notthisone", "boot_seconds": 0.6}))
    assert "No matching machines found for 'notthisone'" in out["message"]
    assert "gdbstub did not answer" not in out["message"], (
        "the symptom won: the caller is told the stub is silent and not that they named a "
        "system this build has never heard of")
    assert mstate.STATE.ses is None and mstate.STATE.scratch is None


def _query_that_outlives_the_boot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                  ) -> tuple[dict[str, str], list[Any]]:
    """A binary whose `-listxml` sleeps past any boot, and the query `start` asks of it
    HELD, so a test can read whether the process was collected: the `start` arguments and
    the list the `Popen` lands in."""
    args = _boot_args(tmp_path, bytes(range(64)))
    Path(args["binary"]).write_text(
        '#!/bin/sh\n[ "$1" = -version ] && { echo "0.0 (a slow query)"; exit 0; }\nsleep 30\n')
    Path(args["binary"]).chmod(0o755)
    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "no-helper"))
    held: list[Any] = []
    real_ask = machine.ask_listxml

    def remembered(binary: str, system: str) -> Any:
        held.append(real_ask(binary, system))
        return held[-1]

    monkeypatch.setattr(machine, "ask_listxml", remembered)
    return args, held


def test_a_start_that_did_not_start_leaves_no_query_running_behind_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A start owns nothing when it fails, and that includes the process it asked a question
    of: one left running with this server as its parent is reachable by nobody and reaped by
    nothing. Here the query outlives the boot on purpose, so a start that collected it only on
    the happy path would strand it.

    The guarantee is STRUCTURAL rather than a cleanup: the answer is read the moment the boot
    is over, on both its paths, so there is no window to forget. This case watches the
    guarantee, not the mechanism, and stays honest if the mechanism changes again.

    WHAT IT DOES NOT REACH, said rather than left to be assumed: it exercises the path where
    the BOOT fails. Moving the collect back to after the park was tried as a mutation and this
    stayed green, because on this path the failure handler collects the query either way. The
    other path needs a raise between two adjacent statements, and a test that injected one
    would be a test about its own injection.
    """
    args, held = _query_that_outlives_the_boot(monkeypatch, tmp_path)
    out = s.start(**{**args, "boot_seconds": 0.4})
    assert out["status"] == "INVALID", out
    proc = held[0][0]
    assert proc is not None
    assert proc.poll() is not None, "the query is still running after a start that failed"


def test_a_boot_that_raises_anything_but_a_refusal_reaps_the_query_and_the_error_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard above collects the query on a REFUSAL, because MAME's own words outrank the
    symptom there. A boot that raises anything else (a bug, a broken helper) went through
    the outer guard alone, which kills the session and never collects the query, so the
    `-listxml` process was left with this server as its parent and reaped by nothing. Now
    it is killed and reaped, and the ORIGINAL exception still propagates."""
    args, held = _query_that_outlives_the_boot(monkeypatch, tmp_path)
    def boom(judged: Any, progress: Any = None, last_launch: bool = True) -> Any:
        raise RuntimeError("boom: the boot itself is broken")

    monkeypatch.setattr(launch, "boot", boom)
    with pytest.raises(RuntimeError, match="boom"):
        s.start(**{**args, "boot_seconds": 0.4})
    proc = held[0][0]
    assert proc is not None
    assert proc.poll() is not None, "the query is still running after a boot that raised"
    assert mstate.STATE.ses is None and mstate.STATE.scratch is None


def test_discard_has_nothing_to_do_for_a_query_already_read_or_never_asked() -> None:
    """The `symbols` mapping path waits for the query in `judge`, and a binary that could not
    be run asked none: both leave `discard` nothing to reap, and neither raises."""
    import subprocess
    from types import SimpleNamespace
    from typing import cast

    def judged(**fields: Any) -> launch.Judged:
        return cast(launch.Judged, SimpleNamespace(**fields))

    launch.discard(judged(listxml=(None, "not run"), listed=None))
    done = subprocess.Popen(["true"])
    done.wait()
    launch.discard(judged(listxml=(done, ""), listed=({}, "")))
    exited = subprocess.Popen(["true"])
    exited.wait()
    launch.discard(judged(listxml=(exited, ""), listed=None))
    assert exited.returncode == 0


def test_a_listxml_that_fails_for_any_other_reason_leaves_the_start_working(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A debug session must not be blocked on an inventory: `start` works today without one.
    But a silently missing section cannot be told from a machine that has none, so the
    failure is NAMED in the coverage note and the sections it backs come back empty."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    Path(args["binary"]).write_text("#!/bin/sh\necho 'Fatal error: no memory' >&2\nexit 3\n")
    Path(args["binary"]).chmod(0o755)
    out = s.start(**args)
    try:
        assert out["rom_check"] == "OK", "the session still came up"
        cached = mstate.STATE.machine_map
        assert cached["rom_files"] == [] and cached["sources"]["rom_files"] == ["-listxml"]
        assert "exit code 3" in cached["note"]
        assert "no memory" in cached["note"]
    finally:
        s.close()


def test_start_says_the_shape_of_the_board_on_its_summary_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The client paints a tool's name, its arguments and its reply and nothing else, so a
    multi-cpu board has to be visible on the ONE line `start` writes. Counts only: a whole
    inventory riding on every start would be paid for by every caller, and `machine_map`
    serves the rows free."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    xml = Path(__file__).parent / "fixtures" / "machine" / "listxml-m68k-dual.xml"
    Path(args["binary"]).write_text(f"#!/bin/sh\ncat {xml}\n")
    Path(args["binary"]).chmod(0o755)
    out = s.start(**{**args, "system": "m68k-dual"})
    try:
        assert out["machine"]["cpus"] == 2 and out["machine"]["rom_files"] == 22
        assert "machine: 2 cpus" in out["summary"], out["summary"]
        assert "22 ROM files" in out["summary"], out["summary"]
    finally:
        s.close()


def test_a_throttle_frame_flies_unthrottled_and_hands_the_harness_the_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The throttle on arrival is a boot harness this server writes: `-nothrottle` on the
    command line (once, whatever the helper emitted), the frame in the environment, the
    harness on `-autoboot_script`, and the caller's own harness chained after it."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    mine = tmp_path / "mine.lua"
    mine.write_text("-- the caller's\n")
    out = s.start(**_boot_args(tmp_path, image), throttle_from_frame=2790, boot_lua=str(mine))
    try:
        argv = _StubProcess.last_argv
        assert argv.count("-nothrottle") == 1
        harness = Path(argv[argv.index("-autoboot_script") + 1])
        assert harness == Path(out["boot_lua_path"]) and harness.parent == mstate.STATE.scratch
        text = harness.read_text()
        assert launch.THROTTLE_MARK in text and "video.throttled = true" in text
        assert text.rstrip().endswith(f'dofile("{mine.resolve()}")')
        assert out.get("env", {}) == {launch.THROTTLE_FRAME_VAR: "2790"}
        assert _StubProcess.last_kwargs.get("env", {})[launch.THROTTLE_FRAME_VAR] == "2790"
        assert out.get("throttle_from_frame", 0) == 2790
        assert argv[argv.index("-autoboot_delay") + 1] == "0"
    finally:
        s.close()
    out = s.start(**_boot_args(tmp_path, image), throttle_from_frame=10)
    try:
        assert "dofile" not in Path(out["boot_lua_path"]).read_text()
    finally:
        s.close()
    out = s.start(**_boot_args(tmp_path, image), boot_lua=str(mine))
    try:
        # THE CALLER'S HARNESS IS CHAINED, NEVER SENT ON ITS OWN, because the server now
        # always writes a script of its own for the inventory: what reaches MAME is the
        # composed one, and the caller's is reached from inside it.
        composed = Path(out["boot_lua_path"])
        assert composed.parent == mstate.STATE.scratch
        text = composed.read_text()
        assert text.rstrip().endswith(f'dofile("{mine.resolve()}")')
        assert launch.THROTTLE_MARK not in text, "no throttle frame, no throttle harness"
        assert "-nothrottle" not in _StubProcess.last_argv
    finally:
        s.close()
    _never_spawns(monkeypatch, tmp_path)
    refused("throttle_from_frame",
    s.start(**_boot_args(tmp_path, image), throttle_from_frame=-1))


@pytest.mark.parametrize(("argument", "value"), [
    ("throttle_from_frame", True), ("throttle_from_frame", "5"), ("throttle_from_frame", -1),
    ("stub_port", True), ("stub_port", "5"), ("stub_port", -1), ("stub_port", 65536),
])
def test_starts_counts_refuse_a_bool_a_string_and_their_edges_before_any_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argument: str, value: object
) -> None:
    _never_spawns(monkeypatch, tmp_path)
    out = refused(rf"^{argument}={re.escape(repr(value))} is not a (frame number: an integer, "
                  r"never negative|TCP port)",
                  s.start(**_boot_args(tmp_path, bytes(64)), **{argument: value}))
    assert out["code"] == "bad_argument", out


# --------------------------------------------------- what the review of the change found


def test_run_to_counts_a_control_off_its_temp_and_ticks_meanwhile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control is MAME's own counting breakpoint: the machine is never stopped for it,
    so the run is one `go` and one stop, and its hits are the counter's delta. The tick
    still fires while the run waits: releasing the machine at every control hit would cost a
    round trip per firing, and a hot control would starve the tick."""
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x4A0]                      # park, target
    ses.stops_after_polls = 3
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    ticks: list[str] = []
    gos: list[int] = []
    real_go = ses.go

    def go() -> None:
        gos.append(ses.stop_count)
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 2      # the control fires twice meanwhile

    ses.go = go  # type: ignore[method-assign]
    out = advance.run_to(ses, tmp_path, "0x4a0", "0x25a4", 2.0,  # type: ignore[arg-type]
                         lambda p, t, m: ticks.append(m))
    assert (out["verdict"] == "TARGET" and out["control_hits"] == 2
            and out["cause"] == "target 0x4a0")
    assert out["controls"] == [{"ref": "0x25a4", "cpu": ":maincpu", "hits_in_run": 2}]
    assert gos == [0], "released once: a control never stops the machine"
    assert len(ticks) >= 2 and "run_to 0x4a0" in ticks[-1]
    assert ses.armed == [(0x4A0, False), (0x4A0, True)], "the target alone, armed and removed"
    assert any(r.endswith("if (++temp0)==0") for r in ses.bplist_rows), "the control stays"


def test_run_to_stops_elsewhere_and_times_out_with_the_right_verdicts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x1000]                      # park, somewhere else
    ses.stops_after_polls = 1
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 1       # the control counted once meanwhile

    ses.go = go  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["control_hits"] == 1
    assert (out["cause"] == "stopped at no breakpoint this server armed"
            and out["pc"] == "0x00001000")
    # A timeout: the control counts, the target never, the machine is interrupted at the bound.
    ses.pcs = [0xF2034, 0x25A4]
    ses.stop_count = 0
    ses.stops_after_polls = None
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["verdict"] == "TIMEOUT" and out["control_hits"] == 1 and ses.interrupted == 1
    assert out["cause"] == "interrupt at the bound" and not ses.running


def test_run_to_reports_a_session_that_broke_under_the_run_as_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The stub closing the connection must come back neither as a TIMEOUT nor as a bare
    traceback: it is INVALID, naming why."""
    ses = _running(monkeypatch, tmp_path)

    def poll(timeout: float = 0.0) -> bool:
        raise g.SessionError("the stub closed the connection")

    ses.poll_stop = poll  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and "closed the connection" in out["message"]
    assert "Nothing about 0x4a0 was measured" in out["message"] and ses.interrupted == 0


def test_run_for_refuses_to_survey_a_machine_that_did_not_settle_after_the_interrupt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The interrupt of a console-started run gets no reply, so the proof of the stop is the
    frame counter at rest, the same proof the ELAPSED path uses; one reading after the 0x03
    proved nothing about a machine that had not processed it yet."""
    ses = _RegisterSession(bits=32, frame=10, stop_after=None)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.05)
    ses.halt = lambda: setattr(ses, "interrupted", True)  # type: ignore[method-assign]
    out = s.run_for(milliseconds=1000, seconds=0.05)
    assert out["status"] == "INVALID" and "did not come to rest" in out["message"]
    assert out["code"] == "not_settled"
    assert ses.interrupted and "dasm" not in out, "a moving machine is not surveyed"


def test_a_stop_found_by_a_call_that_then_refused_is_not_carried_to_the_next_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.resume()
    ses.stops_after_polls = 1                        # a breakpoint fired meanwhile
    # THE REFUSAL HAS TO BE ONE THAT MAKES CONTACT, which `data_hex="zz"` is not: a malformed
    # hex string is judged before the machine is asked for. An unresolvable `ref` is the refusal
    # that still reaches the machine, because resolving it is what needs the table.
    out = s.write(ref="no_such_symbol", data_hex="00")
    assert out["status"] == "INVALID", out
    assert out["stopped_on_its_own"]["stop_seq"] == 2, "the account rides on the refusal itself"
    assert mstate.STATE.last_stop["seq"] == 2, "the record stands"
    out = s.registers()
    assert "stopped_on_its_own" not in out, "the account was delivered with the call it belonged to"


def test_a_refusal_that_never_reached_the_machine_reports_nothing_about_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE MIRROR OF THE CASE ABOVE, and it is new because the boundary is. A refusal judged before
    the gate never contacts the machine, so it cannot have found a stop and says nothing about one
    -- which is the honest answer, not a loss: the call asked the machine nothing. The stop is
    still delivered exactly once, by the next call that does make contact.

    Without this case the change is invisible: the case above would simply have moved its scenario
    and nothing would pin what happens on the path it left behind.
    """
    ses = _running(monkeypatch, tmp_path)
    s.resume()
    ses.stops_after_polls = 1                        # a breakpoint fired meanwhile
    out = s.write(ref="0x0", data_hex="zz")            # judged before the gate: no contact at all
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "stopped_on_its_own" not in out, (
        "a refusal that never asked the machine anything reported a stop it could not have seen")
    later = s.registers()
    assert later["stopped_on_its_own"]["stop_seq"] == 2, (
        "the stop was lost: the next call to make contact owes the account")


def test_stop_landing_on_an_armed_breakpoint_is_attributed_to_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    s.resume()
    out = s.stop()
    assert out["interrupted"] is True and out["cause"] == "breakpoint at 0x4a0"
    again = s.stop()
    assert again["summary"] == "stop: was already stopped"


def test_the_survey_says_when_the_console_gave_no_listing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _RegisterSession(bits=32, frame=10, stop_after=3)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    out = s.run_for(milliseconds=100)
    assert out["dasm"]["available"] is False and "wrote no file" in out["dasm"]["why"]
    assert out["frame"] == 13 and out["errorlog"]["lines_total"] == 0
    run = _running(monkeypatch, tmp_path)
    stepped = s.step(count=2)
    assert stepped["cause"] == "step 2" and stepped["pc"] == "0x000025a4" and run.stop_count == 2
    assert stepped["dasm"] == ["25a4: move.l d0,d1", "25a4+2: rts"]


def test_the_tools_carry_the_clients_context_to_their_waits(tmp_path: Path) -> None:
    """End to end: a tool called with the SDK's context, from the worker thread the SDK uses,
    ticks through it. Dropping the `bridge(ctx)` argument at a call site leaves every
    direct test green; this one goes red."""
    import anyio

    got: list[str] = []

    class _Ctx:
        async def report_progress(self, progress: float, total: float | None = None,
                                  message: str | None = None) -> None:
            got.append(str(message))

    async def main() -> None:
        with pytest.MonkeyPatch.context() as mp:
            ses = _running(mp, tmp_path)
            mp.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
            mp.setattr(running, "RESUME_POLL_S", 0.0)
            mp.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
            mp.setattr(core_wait, "POLL_S", 0.0)
            await anyio.to_thread.run_sync(lambda: s.resume(seconds=0.02, ctx=_Ctx()))
            assert got and got[-1].startswith("resume: running")
            got.clear()
            ses.go()
            await anyio.to_thread.run_sync(
                lambda: s.log_wait(channel="emulator", pattern="never", seconds=0.02, ctx=_Ctx()))
            assert got and got[-1].startswith("log_wait emulator /never/")

    anyio.run(main)


def test_the_advance_family_refuses_its_malformed_arguments_and_a_cold_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A control at the target's own address, a step of nothing, and a bound that expires
    with the control never having fired: the last is the INVALID that makes a silence a
    measurement only when the control spoke."""
    ses = _running(monkeypatch, tmp_path)
    refused("same address",
    s.run_to(ref="0x4a0", control="0x4a0", seconds=1.0))
    refused(r"count=0 is outside 1\.\.300",
    s.step(count=0))
    refused(r"count=301 is outside 1\.\.300: a longer walk is `run_to` or `run_for`",
    s.step(count=advance.step_max() + 1))
    assert advance.step_max() == 300
    advance.check_step(count=advance.step_max())                      # AT the ceiling: taken
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "INVALID" and "never fired" in out["message"]
    assert out["code"] == "control_silent"
    # THE LISTING AT EACH CONTROL AND THE HINT: a control that never fires reads the same
    # for a wrong address and for a right one that runs rarely; the listing says whether
    # the address decodes as code, without another pass.
    listed = out["control_dasm"]
    assert [(c["ref"], c["cpu"]) for c in listed] == [("0x25a4", ":maincpu")], out
    assert isinstance(listed[0]["dasm"], list) and listed[0]["dasm"], out
    assert "listing" not in listed[0], "a listing is `dasm`, as the survey's"
    assert "ENTRY of something periodic" in out["note"]
    assert out["control_hits"] == 0 and ses.interrupted == 1, "the bound stopped the machine"
    # A LISTING THE CONSOLE CANNOT PRODUCE is said so, and the reply still comes back.
    real = read.dasm_lines

    def no_listing(ses: Any, scratch: Path, addr: int, length: int,
                   cpu: str | None = None) -> list[str]:
        if length == advance.CONTROL_DASM_BYTES:
            raise g.SessionError("the console's `dasm` wrote no file")
        lines: list[str] = real(ses, scratch, addr, length, cpu)
        return lines

    monkeypatch.setattr(read, "dasm_lines", no_listing)
    again = s.run_to(ref="0x4a2", seconds=0.05)
    assert again["code"] == "control_silent"
    assert again["control_dasm"][0]["dasm"]["available"] is False, "the survey's own shape"


def test_every_registered_tool_is_named_in_the_instructions() -> None:
    """A tool registered but not named in the `instructions` string is one a session never
    learns exists."""
    registered = [t.name for t in s.mcp._tool_manager.list_tools()]
    assert mame_mcp.ROSTER.unlisted(registered) == []
    assert mame_mcp.ROSTER.text() in (s.mcp.instructions or ""), "the roster is not rendered"


def test_a_run_to_that_comes_back_invalid_still_records_the_stop_it_made(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The INVALID paths (a cold control at the bound, a stop elsewhere with a cold control)
    leave the machine STOPPED, and an unrecorded stop means the next contact finds a stop
    the record does not describe and reports the server's own interrupt as
    `stopped_on_its_own`, attributed to no breakpoint. An INVALID run carries the survey of
    where it left the machine, as every other stop does."""
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x3000]
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "INVALID" and out["cause"] == "interrupt at the bound"
    assert out["pc"] == "0x00003000" and "regs" in out and "dasm" in out
    seq = mstate.STATE.last_stop["seq"]
    nxt = s.status()
    assert "stopped_on_its_own" not in nxt and mstate.STATE.last_stop["seq"] == seq
    # A stop ELSEWHERE before the control ever fired: INVALID too, and surveyed where it is.
    ses.pcs = [0xF2034, 0x1000]
    ses.stop_count = 0
    ses.stops_after_polls = 1
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and out["control_hits"] == 0
    assert (out["cause"] == "stopped at no breakpoint this server armed"
            and out["pc"] == "0x00001000")
    assert "stopped_on_its_own" not in s.status()


def test_run_to_reads_bplist_back_after_arming_its_two_breakpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`breakpoint_at` and the re-arm read `bplist` after every arm, because a row taken can be
    one the console does not list; `run_to` once armed its target on the stub's OK alone, and
    a target the console never listed then came back TIMEOUT beside a control that fired,
    which the contract reads as "the routine never ran". The list is read after the target is
    armed, and a row missing is INVALID naming it, before the machine moves."""
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bp 0x4a0"):
            return "Breakpoint 9 set\n\n"            # taken, listed by nobody
        return str(real(command, timeout))

    monkeypatch.setattr(ses, "monitor", monitor)
    released = []
    ses.go = lambda: released.append(True)  # type: ignore[method-assign]
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and "bplist" in out["message"]
    assert "bp 0x4a0" in out["message"], out
    assert released == [], "the machine was never released: the list was read BEFORE `go`"
    assert not ses.running and (0x4A0, True) not in ses.armed, "no `z0` for an unlisted row"
    assert [r for r in ses.bplist_rows if "temp0" in r], "the declared control keeps its row"
    assert "bplist" in ses.commands


class _ClosedPresence:
    """A session's presence as `kill` meets it: closed once, and nothing else asked of it."""

    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


def test_kill_clears_every_field_of_the_session_it_ends() -> None:
    """Deleting one reset line from `kill` left the suite green: nothing exercised a close
    followed by a fresh session and read what the old one left. `armed_watches` is the one
    that bites, since a watch stop is attributed by the range it brackets and a leftover
    entry names the wrong ref; `symbols` and `system` were never cleared at all."""
    ses = _RecordingSession()
    proc = _ExitingProcess(ses.events, exits=True)
    mstate.STATE.ses, mstate.STATE.proc = ses, proc  # type: ignore[assignment]
    # EVERY field is dirtied, or a reset dropped from `kill` for a field this test left at
    # its default would pass on the default: the comparison walks a fresh State's fields
    # and this list is held to that same set, so a field added and not dirtied here is red.
    dirty: dict[str, Any] = {
        "captures": [("avi", "/x/record-1.avi")],
        "guard": subprocess.Popen(["sleep", "60"]),
        "tables": {":old": g.SymbolTable({"OLD": 0x100}, {}, "yaml", types={"OLD": "u16"})},
        "first_cpu": ":old",
        "system": "old", "boot_pc": 0x100, "view": "Shifter-R Overlay",
        "armed_watches": {"old": {"addr": 0x100, "length": 4}}, "debuglog_mark": 77,
        "tallies": {"old": {"id": "100_4", "addr": 0x100, "width": 4}},
        "controls": {"old": {"addr": 0x100, "temp": 0, "index": 1, "missed": 0}},
        "breakpoints": {1: {"owner": ("old", ":old"), "addr": 0x100, "cpu": ":old"}},
        "last_stop": {"seq": 9},
        "console_writes": 2,
        "regpoints": {"d1==1": {"index": 1, "cpu": ":old", "condition": "d1==1"}},
        "comment_feed": {("old", ":old"): {"state": "armed"}},
        "conditions_unresolved": {("regpoint", "d0==Old")},
        "machine_map": {"cpus": [{"tag": ":old"}]}, "cpus": [":old"], "frame_symbol": None,
        "scratch": Path(tempfile.mkdtemp(prefix="mame-mcp-kill-test-")), "state_dir": "/x",
        "cfg": {"source": Path("/x/a.cfg"), "installed": Path("/x/cfg/m68k.cfg")},
        "port": 23999, "snapshots": 3, "debug_dumps": 1, "batches": 4, "errorlog_mark": 5,
        "recordings": 2, "console_mark": 9, "lua_calls": 1, "lua_read_only_claims": 2,
        "console_thread_errors": 3, "console_reruns_seen": 2, "console_lines_lost": 1,
        "console_counted": 12,
        "lua_seq": 4, "lua_answered": 3,
        "lua_lost": 2, "lua_pending": {1: ("line", 0)}, "lua_ours": {1},
        "console_run": True,
        "console_run_unprovable": True, "unprovable_peek": 42,
        "tally_removals": [{"tally_id": "old", "seq": 1}],
        "throttles_pending": [{"tag": "MAME_MCP_THROTTLE#1", "on": True, "seq": 1}],
        "throttles_not_applied": [{"tag": "MAME_MCP_THROTTLE#1"}],
        "states": {"old": {"frame": 1, "pc": 2}}, "state_signature": 7,
        "scan": mscan.Scan(0x100, 4, 1, ":old", 1, "little", array("I", [0]), array("B", [1]),
                           array("B", [1]), 1),
        "stale_counter": ("x", 9, "y"),
        "reference": (Path("/x/rom.bin"), 0, 0),
        "found_stop_last": {"stop_seq": 2}, "run_release": {"emulated": 1.0, "wall": 2.0},
        "throttle_seen": True, "store": dec.DeclarationStore("t", None),
        "session_origin": "s9", "fingerprints": {":old": "fp9"},
        "manifest": "the old session's manifest",
        "evidence": {"locates": [{"n": 1}], "sweeps": [], "choices": []},
        "stdout_log": open(tmp_log := tempfile.mkstemp()[1], "wb"),  # noqa: SIM115 (kill closes it)
        "presence": presence_mod.Shown(held=_ClosedPresence()),  # type: ignore[arg-type]
    }
    fresh = mstate.State()
    # `cancelled` is the calls', not the session's: a cancel's record outlives the kill it made,
    # for the next reply to say. `maps` is the server's: a map file loaded outlives a session.
    untouched = sorted(set(vars(fresh)) - set(dirty) - {"ses", "proc", "start_seq", "cancelled",
                                                        "maps"})
    assert untouched == [], f"fields this test does not dirty: {untouched}"
    for name, value in dirty.items():
        setattr(mstate.STATE, name, value)
    mstate.STATE.maps.application = "kept"
    mstate.STATE.kill()
    assert mstate.STATE.maps.application == "kept", "a loaded map went with the session"
    mstate.STATE.maps.application = ""
    Path(tmp_log).unlink(missing_ok=True)
    assert dirty["guard"].poll() is not None, "the guardian outlived the session it watched"
    stale = {name: getattr(mstate.STATE, name) for name in vars(fresh)
             if name not in ("start_seq", "maps")
             and getattr(mstate.STATE, name) != getattr(fresh, name)}
    assert stale == {}, f"fields a killed session left behind: {stale}"


def test_a_window_helper_that_ran_and_failed_is_reported_with_its_own_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The helper's stderr was captured and dropped, and the refusal then said the helper was
    "not at" a path it had just been run from: a bad display or a topology failure read as
    a missing program. A shared start now names the exit code and the stderr; a quick run
    keeps its default, since nobody is watching it, and says nothing."""
    helper = tmp_path / "place-window"
    helper.write_text("#!/bin/sh\necho 'display-topology: no such display' >&2\nexit 1\n")
    helper.chmod(0o755)
    monkeypatch.setenv("WINDOW_APP", str(helper))
    with pytest.raises(mstate.Invalid) as e:
        launch.window_flags(shared=True, display="main")
    assert "not at" not in str(e.value)
    assert "exit code 1" in str(e.value) and "no such display" in str(e.value)
    assert "-window" in launch.window_flags(shared=False)


def test_start_refuses_while_a_session_is_live(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`start` must not kill whatever was live and boot again in silence: it refuses and
    asks for `close`. One machine per server, and ending one is a deliberate act."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    e = refused("live",
    s.start(**_boot_args(tmp_path, b"\0" * 32)))
    assert "m68k-dual" in e["message"] and "4242" in e["message"] and "`close`" in e["message"]
    assert mstate.STATE.ses is ses, "the live session was left alone"  # type: ignore[comparison-overlap]


def test_the_doubles_surface_is_derived_from_the_package_and_held_to_the_real_session(
        tmp_path: Path) -> None:
    """Every attribute the package reads on a session is derived by AST from the package's
    own source, per file against that file's own imports
    (so prose cannot contribute and `subprocess.run` cannot either), and held in two
    directions. Every callable name must exist on the real `Session`, or the server calls a
    method the client lacks; and the running double must carry every one, or a tool moved
    onto a method the double never had crashes on the real path with a traceback the
    wrapper does not translate, while the suite stays green. A floor of names the server
    plainly uses guards the derivation itself against going blind."""
    package = Path(str(s.__file__)).parent
    used: set[str] = set()
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {a.asname or a.name.split(".")[0]
                   for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {a.asname or a.name
                    for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                 and not (isinstance(n.value, ast.Name) and n.value.id in modules)}
    called = {n for n in used if not n.startswith("_") and callable(getattr(g.Session, n, None))}
    for sentinel in ("read", "registers", "monitor", "make_visible", "register_block", "poll_stop",
                     "go", "interrupt", "step", "current_pc", "quit", "set_reg", "write"):
        assert sentinel in called, (
            f"the derivation no longer sees `{sentinel}`, which the package plainly calls on "
            "a session: it has gone blind and this check is empty")
    double = _RunningSession(tmp_path)
    for name in sorted(called):
        assert hasattr(g.Session, name), f"the package calls `Session.{name}`, which does not exist"
        assert callable(getattr(double, name, None)), (
            f"the running double has fallen behind: the package calls `{name}` on the session "
            "and `_RunningSession` does not have it")
    # And the non-callable attributes the package reads, which a double answers as fields.
    fields = {n for n in used if not n.startswith("_") and hasattr(g.Session, n)
              and not callable(getattr(g.Session, n))}
    # `host`, `port` and `timeout` are the socket's and `owner` the dial's proof, read by the
    # client alone; `pc_name` is resolved inside the client. Everything else the package reads
    # on a session, the double answers, `byte_order` among them, which the watch family reads.
    missing = sorted(n for n in fields if not hasattr(double, n)
                     and n not in ("host", "port", "timeout", "owner", "pc_name"))
    assert missing == [], f"session fields the package reads and the double lacks: {missing}"


def test_the_live_interlock_is_declared_in_the_package() -> None:
    """The live tier of this package is a script and pytest collects none of it today, which is
    a naming accident and not a declared property: the day a `test_*_live.py` joins
    `tests/live/`, a stranger running `pytest` from a clone would launch an emulator per case.
    The package deselects the tier by itself."""
    here = Path(__file__).resolve().parent.parent
    mine = tomllib.loads((here / "pyproject.toml").read_text(encoding="utf-8"))
    section = mine.get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert "-m 'not live'" in section.get("addopts", ""), (
        "this package does not deselect the live tier by itself")
    assert any(m.startswith("live:") for m in section.get("markers", [])), section


def test_run_to_over_a_declared_breakpoint_leaves_the_declaration_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A `run_to` over a declared STOP breakpoint leaves that declaration armed: the target's
    row is the only one the run adds and removes, and a declared stop is not a control (one
    ref is one role; naming a declared stop as the control is refused by name)."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "store", dec.DeclarationStore("t", None))
    monkeypatch.setattr(mstate.STATE, "session_origin", "s1")
    assert s.breakpoint_at(ref="0x4a0")["armed"] is True
    refused("already declared as a stop", s.run_to(ref="0x25a4", control="0x4a0", seconds=1.0))
    ses.pcs = [0xF2034, 0x25A4]
    ses.stops_after_polls = 1
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = 1

    ses.go = go  # type: ignore[method-assign]
    out = s.run_to(ref="0x25a4", control="0x600", seconds=1.0)
    assert out["verdict"] == "TARGET" and out["control_hits"] == 1
    assert [r for r in ses.bplist_rows if r.endswith("@ 0004A0")], "the declaration's row stays"
    listed = {b["ref"]: b for b in s.declaration_list("breakpoint")["breakpoints"]}
    assert listed["0x4a0"]["state"] == "armed" and listed["0x4a0"]["role"] == "stop"
    assert listed["0x600"]["role"] == "control" and listed["0x600"]["hits_since_armed"] == 1


class _AlreadyDead:
    """A process that exited on its own before `close` was called: `poll` knows the code."""

    pid = 77

    def poll(self) -> int | None:
        return -11


def test_close_reports_a_process_that_had_already_died_and_the_session_as_it_was() -> None:
    """Two things `close` said wrong. A MAME that crashed between calls came back as
    `closed: false, note: there was no session to close`, the same reply as a server that
    never started anything, with the exit code `poll` already held thrown away; it is
    `ended_by: died` with that code. And the reply's `session` block was built after the kill,
    so it read `altered: false` about a session that had been written to; it now describes
    the state as it was BEFORE closing, so its `altered` is the truth about the session
    that ended."""
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _AlreadyDead()  # type: ignore[assignment]
    mstate.STATE.console_writes = 3
    # NONZERO ON PURPOSE, like `console_writes` beside it: the reply describes the session
    # as it was BEFORE the kill, so a block built after the reset would read three zeros
    # and an all-zero expectation could not tell the two apart.
    mstate.STATE.console_thread_errors = 2
    mstate.STATE.console_reruns_seen = 1
    mstate.STATE.console_lines_lost = 1
    closed = s.close()
    assert closed["closed"] is True and closed["ended_by"] == "died" and closed["exit_code"] == -11
    assert ses.events == ["close"], "no quit is sent to a process that is gone"
    assert closed["session"] == {"alive": False, "running": False, "altered": True,
                                 "altering_writes": 3,
                                 "console": {"thread_errors": 2, "reruns": 1, "lost": 1},
                                 "note": closed["session"]["note"]}
    assert closed["summary"] == "close: the emulator had already exited, exit code -11"
    assert mstate.STATE.console_writes == 0
    ses2 = _RecordingSession(quit_raises=True)
    proc = _ExitingProcess(ses2.events, exits=True)
    mstate.STATE.ses, mstate.STATE.proc = ses2, proc  # type: ignore[assignment]
    ses2.writes = 1
    closed = s.close()
    assert closed["ended_by"] == "quit" and closed["session"]["alive"] is True
    assert closed["session"]["altered"] is True and closed["session"]["altering_writes"] == 1


def test_a_window_helper_that_hangs_is_bounded_and_one_that_prints_nothing_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`subprocess.run` on the helper had no bound, so a hung helper held `start` forever
    with the lock; and a helper that failed printing NOTHING was never exercised, though
    it is the shape a crash leaves. Both name the helper and what happened."""
    slow = tmp_path / "slow"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    monkeypatch.setenv("WINDOW_APP", str(slow))
    with monkeypatch.context() as tight:            # the tiny bound is for the hung helper only
        tight.setattr(placement, "HELPER_TIMEOUT_S", 0.2)
        with pytest.raises(mstate.Invalid, match="did not answer within") as e:
            launch.window_flags(shared=True, display="main")
    assert "not at" not in str(e.value)
    mute = tmp_path / "mute"
    mute.write_text("#!/bin/sh\nexit 3\n")
    mute.chmod(0o755)
    monkeypatch.setenv("WINDOW_APP", str(mute))
    with pytest.raises(mstate.Invalid, match="exit code 3 and printed 'nothing'"):
        launch.window_flags(shared=True, display="main")


def test_run_to_refused_at_the_readback_removes_only_what_was_listed_and_says_if_it_could_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The refusal after the `bplist` readback must not send a removal for the unlisted
    target too: nothing is sent for a row the debugger never listed, and the declared control
    is not the run's to remove."""
    ses = _running(monkeypatch, tmp_path)
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bp 0x4a0"):
            ses.commands.append(command)
            return "Breakpoint 9 set\n\n"            # taken, listed by nobody
        return str(real(command, timeout))

    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["status"] == "INVALID" and "bp 0x4a0" in out["message"]
    assert out["code"] == "readback_refused" and out["control_hits"] == 0
    assert not any(c.startswith("bpclear") for c in ses.commands), (
        "no removal for a row the debugger never listed, and the control stays")


def test_write_refuses_empty_data_and_reset_and_a_mutating_debug_count_as_writes(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The three decision points of the write family the battery executed through no
    test: an empty `data_hex` is refused before anything is sent, `reset` reports its
    kind and counts as a write, and a `debug` command the classifier marks as mutating
    bumps the console-write count while a reader leaves it alone."""
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
    ("print {d1==7fff}", False),        # the captured probe line: the console answered `0`
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
    ("wpdset 400,2,w,1,{ g }", True),        # the abbreviated spellings of the family
    ("bpdisable 1", False),
    ("rpset{d1==7fff}", False),              # the bare condition with no space before it
    ("statesave x", False),                  # a state written OUT changes nothing
    ("stateload x", True),
    ("temp9=0", False),                      # a debugger temp alone is not the guest
    ("temp9=0;fill 100,1,1", True),          # the second command is judged too
])
def test_a_comparison_typed_through_debug_is_a_read_and_an_assignment_or_an_action_a_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str, mutates: bool,
) -> None:
    """A comparison operator is never an assignment, so `print {d1==7fff}` is a read; an
    assignment anywhere on the line, and an action in braces on a `bp`/`wp`/`rp` line, count
    as writes whatever the action holds, and a registerpoint's bare condition does not."""
    _console(monkeypatch, tmp_path, _ConsoleSession(replies={"print": "0\n"}))
    monkeypatch.setattr(mstate.STATE, "console_writes", 0)
    out = s.debug(command=command)
    assert out["mutates"] is mutates, (command, out["mutates"])
    assert out["command"] == command
    assert mstate.STATE.console_writes == (1 if mutates else 0)
    assert out["session"]["altered"] is mutates, out["session"]


def _boot_against(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                  exit_code: int | None, wait: float, presence: bool = False) -> Any:
    """`boot` against a gdbstub that refuses every connection and a process whose `poll`
    answers `exit_code` (None: alive). Hands back the refusal it raised."""
    from types import SimpleNamespace

    class Refusing:
        def __init__(self, port: int, owner: object = None) -> None:
            self.port = port

        def dial(self) -> None:
            raise OSError("connection refused")

    class Spawned:
        pid = 1

        def poll(self) -> int | None:
            return exit_code

    import subprocess
    monkeypatch.setattr(g, "Session", Refusing)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Spawned())
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "proc", None)       # restored: the double has no poll
    judged = SimpleNamespace(
        state_dir="", boot_lua="", env={}, throttle_from_frame=0, binary="mame",
        system="sys", rompath=str(tmp_path), port=1, flags=[], inipath="", wait=wait,
        ref=tmp_path / "ref.bin", ref_addr=0, ref_base=0, cfg=None, background=False,
        presence=presence, view="")
    with pytest.raises(mstate.Invalid) as e:
        launch.boot(judged)  # type: ignore[arg-type]
    assert mstate.STATE.ses is None
    return e.value


@pytest.mark.parametrize("presence", [True, False])
def test_boot_composes_the_drawer_exactly_when_presence_is_asked(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, presence: bool) -> None:
    _boot_against(monkeypatch, tmp_path, exit_code=None, wait=0.05, presence=presence)
    script = (tmp_path / "boot.lua").read_text(encoding="utf-8")
    assert ("register_frame_done" in script) is presence


def test_start_hands_presence_to_the_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []

    class Stop(Exception):
        pass

    def judge(**kw: Any) -> None:
        seen.append(kw["presence"])
        raise Stop
    from types import SimpleNamespace
    monkeypatch.setattr(launch, "judge", judge)
    import mame_binary
    monkeypatch.setattr(mame_binary, "resolve", lambda b: SimpleNamespace(path=b,
                                                                          origin="argument"))
    monkeypatch.setattr(mstate.STATE, "ses", None)
    for asked in (True, False):
        with pytest.raises(Stop):
            launch.start("mame", "sys", "/r", "/r/x.bin", "", "0x0", "", 1.0, False, "", None,
                         None, "0x0", "", 0, "", presence=asked)
    assert seen == [True, False]


def test_the_boundary_tells_the_session_s_presence_of_each_call(
        monkeypatch: pytest.MonkeyPatch) -> None:
    heard: list[tuple[str, str]] = []

    class Heard:
        def began(self, tool: str) -> None:
            heard.append(("began", tool))

        def ended(self, tool: str) -> None:
            heard.append(("ended", tool))
    monkeypatch.setattr(mstate.STATE, "presence", presence_mod.Shown(held=Heard()))  # type: ignore[arg-type]
    assert s.status()["status"] == "ok"
    assert heard == [("began", "status"), ("ended", "status")]


def test_boot_names_a_gdbstub_that_never_answers_within_its_wait(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The connect loop keeps trying until `wait` runs out and then names the last
    refusal: a stub that never answers is reported as such, not as a hang."""
    refusal = _boot_against(monkeypatch, tmp_path, exit_code=None, wait=0.05)
    assert "did not answer within 0.05 s: connection refused" in str(refusal), refusal


def test_boot_names_a_process_that_died_without_waiting_out_the_bound(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A MAME THAT DIED IS KNOWN DEAD AT ONCE, and waiting out a bound sized for a whole
    board's boot to learn it costs the caller that bound for nothing. It is a different
    diagnosis from a stub that never answered, and sends a reader somewhere else, so the
    refusal says the process exited and with which code."""
    began = time.monotonic()
    refusal = _boot_against(monkeypatch, tmp_path, exit_code=7, wait=5.0)
    took = time.monotonic() - began
    assert took < 1.0, f"a dead process cost {took:.2f} s of a 5 s bound"
    assert refusal.code == "session_broken" and refusal.fields["exit_code"] == 7, refusal
    assert "exited with code 7" in str(refusal) and "did not answer" not in str(refusal)


def test_reset_is_soft_applied_and_read_back_and_a_hard_reset_is_refused(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The console's `softreset` is a timer that fires when the
    machine next runs, so the pc read right after it is the old one and one `step` lands on
    the boot pc; `hardreset` re-creates the machine and the stub connection dies with it,
    taking the session. So `reset` schedules the soft one, steps once, and reads the pc back
    against the pc `start` parked at; the hard one is refused with the way to do it
    (`close`, then `start`). Both are writes: the session is altered afterwards."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "boot_pc", 0xF2034)
    # NO HARD RESET IS OFFERED: it would end the session, which is `close` and `start`.
    assert "hard" not in inspect.signature(s.reset).parameters
    assert ses.writes == 0 and "hardreset" not in ses.commands
    # THE FRAME COUNTER DOES NOT RESTART across a soft reset, so the reply carries the frame
    # the reset was applied at, and a later stop's frame is compared with a cold boot's by
    # subtracting it. A reset that answered no frame would leave every golden's frame
    # number after it looking like a cold boot's, and nothing in the reply would say so.
    ses.frame = 661
    ses.pcs = [0xF2034, 0xF2034]        # the step that applies the reset lands on the boot pc
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
    # THE RESET IS A STOP OF ITS OWN, surveyed and recorded like `step`'s (left unrecorded,
    # the next call on a V30 board reports it as `stopped_on_its_own` at no
    # breakpoint this server armed). So the reply carries the stop survey, and the next
    # contact finds nothing to attribute to the machine alone.
    assert out["cause"] == "softreset" and out["frame"] == ses.frame and "regs" in out, out
    after = s.status()
    assert "stopped_on_its_own" not in after, after
    assert after["last_stop"]["cause"] == "softreset" and after["last_stop"]["frame"] == ses.frame

    ses.pcs = [0xF2034, 0x1000]        # the step lands elsewhere: not verified
    assert s.reset()["verified"] is False


def test_find_can_search_within_a_symbol_class_region(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A one-byte pattern searched over the whole address space drowns in false positives
    (0xAD is the LODSW opcode as well as the inverted CP437 mark, and text tables live in
    CODE), so `find` takes an optional `symbol_class`: a class name whose loaded symbols
    give the range to search, instead of a hand-counted ref and length. The class span is
    the min and max address of that class's symbols; a match past the last symbol's own
    start is not covered, because a linker map carries no sizes. Without `region` it is the
    old ref+length search, and giving both is refused."""
    ses = _ConsoleSession(replies={"find": (FIXTURES / "find.none.txt").read_text()})
    _console(monkeypatch, tmp_path, ses)
    use_table(monkeypatch, table={"MSG_A": 0x420, "MSG_B": 0x480})
    use_table(monkeypatch, class_span={"DATA": (0x420, 0x480), "CODE": (0x0, 0x200)})
    out = s.find(symbol_class="DATA", data_hex="AD")
    assert out["status"] == "ok", out
    assert out["symbol_class"] == "DATA" and out["addr"] == "0x00000420"
    # length spans lo..hi inclusive of the last symbol's first byte.
    assert ses.commands[-1] == "find 0x420,0x61,0xad", ses.commands[-1]
    # THE SPAN EXAMINED IS IN THE REPLY, with where it came from: a class's span is its
    # symbols' [min, max] and not the segment, so a zero over it is "not among the symbols"
    # and never "not in DATA"; a caller reading `region: DATA` alone took it for the latter
    # (the span ends at the last DATA symbol, well short of the segment).
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


def test_resume_then_close_reports_the_speed_the_host_held_over_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """MAME's own `Average speed` line is suppressed on a debugger-driven exit, so
    the speed is COMPUTED from the debugger's own emulated clock (`time`) and the wall clock:
    over the run a `resume` opened, emulated seconds / wall seconds. A watched run ended by
    `close` carries it on the close reply; a run that stops first carries
    it on that stop. Here: released at emulated 5.0s / wall 100.0s, closed at 6.0s / 102.0s,
    so 1 emulated second over 2 wall seconds is 50% -- the host ran the guest at half real
    speed over that window."""
    ses = _RegisterSession(bits=32)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)      # close/kill read STATE.ses directly
    wall = [100.0]                            # a mutable wall clock the phases set
    monkeypatch.setattr("mame_running.time.monotonic", lambda: wall[0])
    ses.emu_clock = 5.0
    r = s.resume()
    assert "verdict" not in r and "running" not in r and ses.running, r
    wall[0] = 102.0
    ses.emu_clock = 6.0
    ses.running = False                       # the watched run is ended by close
    closed = s.close()
    assert closed["average_speed"] == {"percent": 50.0, "emulated_s": 1.0,
                                       "wall_s": 2.0}, closed


def test_a_stop_found_by_a_later_contact_ends_the_run_and_carries_its_speed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The window a `resume` opened closes at the stop that ends the run, whoever finds it."""
    ses = _running(monkeypatch, tmp_path)
    wall = [100.0]
    monkeypatch.setattr("mame_running.time.monotonic", lambda: wall[0])
    ses.emu_clock = 5.0
    assert s.resume()["session"]["running"] is True
    ses.stops_after_polls = 1
    wall[0], ses.emu_clock = 102.0, 6.0
    found = s.status()["stopped_on_its_own"]
    assert found["average_speed"] == {"percent": 50.0, "emulated_s": 1.0,
                                      "wall_s": 2.0}, found
    assert mstate.STATE.run_release is None
    wall[0], ses.emu_clock = 702.0, 6.5
    assert "average_speed" not in s.step(count=1), "a step long after opened no window"


def test_a_close_with_no_run_open_reports_no_speed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A session closed without a `resume` in flight has no window to measure, so `close`
    carries no `average_speed` rather than a zero or a division by no time."""
    ses = _RegisterSession(bits=32)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    closed = s.close()
    assert "average_speed" not in closed, closed


def _window(monkeypatch: pytest.MonkeyPatch, wall_s: float, emulated_s: float) -> Any:
    """An open run window `wall_s` and `emulated_s` long, on a double whose clock is read."""
    ses = _RegisterSession(bits=32)
    ses.emu_clock = 1.0 + emulated_s
    monkeypatch.setattr(mstate.STATE, "run_release", {"emulated": 1.0, "wall": 0.0})
    monkeypatch.setattr("mame_running.time.monotonic", lambda: wall_s)
    return ses


def test_the_speed_and_its_two_times_are_rounded_to_what_each_can_carry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ses = _window(monkeypatch, wall_s=2.5004613579, emulated_s=1.23456789)
    assert running.average_speed(ses) == {"percent": 49.37, "emulated_s": 1.234568,
                                          "wall_s": 2.500461}


@pytest.mark.parametrize("wall_s", [0.01, 0.5])
def test_a_window_of_a_hundredth_of_a_second_or_more_is_a_speed(
    wall_s: float, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor keeps a division by almost nothing out, and it is a hundredth, inclusive."""
    ses = _window(monkeypatch, wall_s=wall_s, emulated_s=wall_s)
    speed = running.average_speed(ses)
    assert speed is not None and speed["wall_s"] == wall_s, speed


def test_a_release_whose_clock_cannot_be_read_opens_no_window_and_the_stop_still_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    wall = [100.0]
    monkeypatch.setattr("mame_running.time.monotonic", lambda: wall[0])
    monkeypatch.setattr(ses, "emulated_seconds", lambda: None)
    assert s.resume()["session"]["running"] is True
    monkeypatch.setattr(ses, "emulated_seconds", lambda: 6.0)
    wall[0] = 102.0
    out = s.stop()
    assert out["interrupted"] is True and "average_speed" not in out, out


def test_a_bounded_resume_asks_the_socket_in_polls_no_longer_than_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    asked: list[float | None] = []
    real = ses.poll_stop

    def poll_stop(timeout: float = 0.0) -> bool:
        asked.append(timeout)
        return real(timeout)

    monkeypatch.setattr(ses, "poll_stop", poll_stop)
    ses.stops_after_polls = 2
    assert s.resume(seconds=5.0)["verdict"] == "OTHER_STOP"
    polls = asked[-2:]
    assert all(t is not None and 0.0 <= t <= running.RESUME_POLL_S for t in polls), asked


def test_a_stop_of_a_run_the_console_started_is_proved_on_the_counter_and_says_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _RegisterSession(bits=32, stop_after=None)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "console_run", True)
    monkeypatch.setattr("mame_running.time.sleep", lambda gap_s: None)
    ses.running = ses.emulating = True
    out = s.stop()
    assert "running" not in out and out["status"] == "ok" and out["interrupted"] is True, out
    assert out["session"]["running"] is False and ses.running is False, out["session"]
    assert ses.interrupted and ses.received == [g.STOP_REPLY_DRAIN_S]
    again = s.stop()
    assert again["interrupted"] is False and again["session"]["running"] is False, again
    assert "note" in again and again["last_stop"]["cause"] == "interrupt", again


def test_the_throttle_lift_resets_the_speed_window_to_the_real_speed_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A P5 run flies flat out to a late frame and drops to REAL speed there, all inside one
    `resume`. Its speed window opened at the resume (the ramp), so `average_speed` over the
    whole run blends the fast ramp with the real-speed play. When the server sees the throttle
    harness's lift mark in error.log -- the natural way a caller learns the fly is done is
    `log_wait` on it -- the window is reset to that moment, so the real-speed part is
    what `close` reports. Reset once, and only while a run window is open."""
    ses = _RegisterSession(bits=32)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    (tmp_path / "error.log").write_text("boot\nMAME_MCP throttled from frame 900\n")
    mstate.STATE.run_release = {"emulated": 0.0, "wall": 100.0}   # the ramp's start
    ses.emu_clock = 15.0                                          # emulated at the lift
    monkeypatch.setattr("mame_running.time.monotonic", lambda: 200.0)
    out = s.log(channel="emulator", pattern="throttled from frame")
    assert out["status"] == "ok" and out["lines_total"] == 1, out
    assert mstate.STATE.run_release == {"emulated": 15.0, "wall": 200.0}, mstate.STATE.run_release
    assert mstate.STATE.throttle_seen is True
    # A second read does NOT reset again: the window now belongs to the real-speed run.
    ses.emu_clock = 40.0
    s.log(channel="emulator", pattern="throttled from frame")
    assert mstate.STATE.run_release == {"emulated": 15.0, "wall": 200.0}, "reset more than once"


def test_a_binary_with_no_console_plugin_in_any_place_is_refused_before_the_boot(
    tmp_path: Path,
) -> None:
    """MAME's `-console` is fatal without the console plugin, and its default search does
    not reach a build's tree from this server's working directory: the refusal names every
    file it looked for and the remedy, and nothing is spawned."""
    binary = tmp_path / "bare-mame"
    binary.write_text("#!/bin/sh\nexit 0\n")
    # EXECUTABLE, because this case is about the PLUGINS and nothing else: the check that asks
    # whether the binary can be RUN fires first and answers a different question.
    binary.chmod(0o755)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    out = refused("no console plugin for", s.start(
        binary=str(binary), system="none", rompath=str(tmp_path),
        reference_rom=str(rom), boot_seconds=0.2))
    assert out["code"] == "bad_argument"
    for place in (tmp_path / "plugins", tmp_path.parent / "share" / "mame" / "plugins"):
        assert str(place.resolve() / "console" / "init.lua") in out["message"], (
            "every place it looked is named", place)
    assert "pass as `binary`, or set MAME_BINARY to, the executable" in out["message"]
    assert mstate.STATE.proc is None, "a refused start spawned something"


@pytest.mark.skipif(os.name == "nt", reason="the build is a POSIX shell program")
def test_a_plugin_less_build_the_path_found_is_the_host_s_to_fix_and_says_which_rung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same build reached by the PATH rung: nothing the caller passed is wrong, so the
    refusal is the host's, and it names the rung the build came from and both ways past it."""
    (tmp_path / "bin").mkdir()
    binary = tmp_path / "bin" / "mame"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.delenv("MAME_BINARY", raising=False)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    out = refused("no console plugin for", s.start(
        system="none", rompath=str(tmp_path), reference_rom=str(rom), boot_seconds=0.2))
    assert out["code"] == "host_failed", out
    assert "the PATH rung" in out["message"] and "MAME_BINARY" in out["message"], out["message"]
    assert mstate.STATE.proc is None, "a refused start spawned something"


def test_a_packaged_mame_finds_its_console_plugin_under_its_prefixs_share(
    tmp_path: Path,
) -> None:
    """A Homebrew keg: `bin/mame` is a symlink into `Cellar/mame/<version>/bin/`, and the
    plugins are installed under `share/mame/plugins` of the keg. Resolved first, so the
    symlink's own directory is not where it is looked; a `plugins/` beside the executable
    without the console plugin is passed over; one holding it is asked first."""
    version = "1.0"
    keg = tmp_path / "Cellar" / "mame" / version
    (keg / "bin").mkdir(parents=True)
    real = keg / "bin" / "mame"
    real.write_text("#!/bin/sh\nexit 0\n")
    real.chmod(0o755)
    console = keg / "share" / "mame" / "plugins" / "console"
    console.mkdir(parents=True)
    (console / "init.lua").write_text("-- the console plugin's place, not its code\n")
    (tmp_path / "bin").mkdir()
    link = tmp_path / "bin" / "mame"
    link.symlink_to(Path("..") / "Cellar" / "mame" / version / "bin" / "mame")
    (keg / "bin" / "plugins" / "console").mkdir(parents=True)        # no init.lua in it
    assert launch.plugins_dir(str(link)) == console.parent.resolve()
    cmd = launch.build_command(str(link), "circus", "/roms", 23946, [], str(tmp_path))
    assert cmd[cmd.index("-pluginspath") + 1] == str(console.parent.resolve())
    # BESIDE THE EXECUTABLE STILL WINS, a source build's place asked first.
    beside = keg / "bin" / "plugins" / "console"
    (beside / "init.lua").write_text("--\n")
    assert launch.plugins_dir(str(link)) == beside.parent.resolve()


def test_the_command_line_names_the_plugins_beside_the_binary(tmp_path: Path) -> None:
    binary = fake_mame(tmp_path)
    cmd = launch.build_command(str(binary), "m68k-dual", "/roms", 23946, [], str(tmp_path))
    at = cmd.index("-pluginspath")
    assert cmd[at + 1] == str((tmp_path / "plugins").resolve())
    assert "-console" in cmd


def test_every_registered_tool_carries_a_description() -> None:
    """A tool can reach the client with no `description` at all: a docstring composed with
    `+` is an expression, not a docstring, so `__doc__` is None and the tool is registered
    mute."""
    import asyncio
    tools = asyncio.run(s.mcp.list_tools())
    assert len(tools) > 30, "the registry answered almost nothing"
    mute = sorted(t.name for t in tools if not (t.description or "").strip())
    assert mute == [], f"tools with no description: {mute}"


def test_registers_from_the_last_stop_before_any_stop_is_no_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stale read before the session has recorded a stop has nothing to hand back, and
    says so with its own code rather than an empty register map."""
    _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    out = s.registers(from_last_stop=True)
    assert out["status"] == "INVALID" and out["code"] == "no_stop", out
    assert "no stop yet" in out["message"]


def test_history_counts_what_came_back_and_keeps_what_was_asked_apart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """At the boot only one instruction has retired: `instructions` is what the console
    LISTED, never an echo of the argument, which three repos read as eight lines."""
    ses = _ConsoleSession(replies={"history": "0025E8: lea     $201000.l, A0\n"})
    _console(monkeypatch, tmp_path, ses)
    out = s.history(limit=8)
    assert out["asked"] == 8 and len(out["lines"]) == 1, out
    assert out["summary"] == "history: 1 instruction of 8 asked", out["summary"]


def test_find_summary_names_the_pattern_and_where_it_looked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A session's summaries are what a reader has to tell one search from the next: the
    pattern and the place, not `find : 452 hits` with a hole where the ref should be."""
    ses = _ConsoleSession(replies={"find": _first_window((FIXTURES / "find.txt").read_text())})
    _console(monkeypatch, tmp_path, ses)
    out = s.find(ref="0x0", length=0x10000, data_hex="00201000")
    assert out["summary"] == "find 00201000 in 0x10000 bytes at 0x0: 2 hits", out["summary"]
    use_table(monkeypatch, class_span={"CODE": (0x0, 0xFFFF)})
    by_region = s.find(symbol_class="code", data_hex="e8")
    assert by_region["summary"] == "find e8 in CODE: 2 hits", by_region["summary"]


# ------------------------------------------------------------ the cabinet's cfg, installed

CFG_OK = """<?xml version="1.0"?>
<mameconfig version="10">
    <system name="m68k">
        <input>
            <port tag=":P1" type="P1_BUTTON1" mask="64" defvalue="64">
                <newseq type="standard">KEYCODE_DOWN</newseq>
            </port>
        </input>
    </system>
</mameconfig>
"""


def test_start_installs_the_repos_cfg_where_mame_reads_it_and_close_says_if_it_changed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The cabinet's key map is a versioned `.cfg` in the repo, the ONE source of those keys
    (the driver carries no PORT_CODE), and without it a live session plays on MAME's generic
    defaults with nothing saying so. `start(cfg=)` copies it to `<state>/cfg/<system>.cfg`,
    the file `-cfg_directory` makes MAME read, and the reply says so; `close` never touches
    the repo's file and says whether MAME rewrote the copy on its way out."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    source = tmp_path / "repo" / "run" / "cfg" / "v30.cfg"
    source.parent.mkdir(parents=True)
    source.write_text(CFG_OK)
    out = s.start(**_boot_args(tmp_path, image), cfg=str(source))
    assert out["status"] == "ok", out
    scratch = Path(out["scratch_dir"])
    installed = scratch / "cfg" / "m68k.cfg"
    assert out["cfg"] == {"source_path": str(source), "installed_path": str(installed),
                          "replaced": False}
    assert installed.read_text() == CFG_OK
    argv = _StubProcess.last_argv
    assert argv[argv.index("-cfg_directory") + 1] == str(installed.parent)
    assert s.status()["cfg"] == out["cfg"]
    installed.write_text(CFG_OK.replace("KEYCODE_DOWN", "KEYCODE_UP"))   # MAME canonising
    closed = s.close()
    assert closed["cfg"] == {"installed_path": str(installed), "changed": True}, closed
    assert source.read_text() == CFG_OK, "the repo's file is never touched"
    # Into a persistent state_dir the copy lands there, and an unchanged copy says so.
    state = tmp_path / "state"
    out = s.start(**_boot_args(tmp_path, image), cfg=str(source), state_dir=str(state))
    assert out["cfg"]["installed_path"] == str(state / "cfg" / "m68k.cfg")
    assert out["cfg"]["replaced"] is False
    closed = s.close()
    assert closed["cfg"] == {"installed_path": str(state / "cfg" / "m68k.cfg"), "changed": False}
    # A second pass over the same state_dir finds the earlier copy and SAYS it replaced it.
    out = s.start(**_boot_args(tmp_path, image), cfg=str(source), state_dir=str(state))
    assert out["cfg"]["replaced"] is True
    s.close()
    # No cfg: nothing installed, and the replies say so with `null`.
    out = s.start(**_boot_args(tmp_path, image))
    assert out["cfg"]["available"] is False and s.close()["cfg"]["available"] is False


def test_a_cfg_mame_would_not_bind_is_refused_before_the_boot_naming_the_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two XML subtleties MAME meets in SILENCE (the MAME reference carries both): a `<port>`
    without `tag`, `mask` and `defvalue` parses, binds nothing and is overwritten on exit;
    a comment holding `--` makes MAME log "Error parsing XML configuration file" and load
    the defaults. Both are refused before anything is spawned, naming the line; so is a
    cfg for another system, a relative path and a missing file."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    cfg = tmp_path / "bad.cfg"
    cfg.write_text(CFG_OK.replace(' mask="64" defvalue="64"', ""))
    out = refused("`mask`", s.start(**args, cfg=str(cfg)))
    assert "line 5" in out["message"], out["message"]
    # THE LINE IS THE PARSER'S: a comment quoting a port and two ports on one line do not
    # shift it (the audit found a count over the text that both would move).
    cfg.write_text(CFG_OK.replace("<input>", "<!-- <port> used to be here -->\n        <input>")
                   .replace('<port tag=":P1" type="P1_BUTTON1" mask="64" defvalue="64">',
                            '<port tag=":P1" type="P1_START" mask="1" defvalue="1"><newseq '
                            'type="standard">KEYCODE_1</newseq></port><port tag=":P1" '
                            'type="P1_BUTTON1" defvalue="64">'))
    out = refused("`mask`", s.start(**args, cfg=str(cfg)))
    assert "line 6" in out["message"], out["message"]
    # A refused cfg beside a fresh state_dir leaves NO directory behind.
    state = tmp_path / "never"
    refused("`mask`", s.start(**args, cfg=str(cfg), state_dir=str(state)))
    assert not state.exists(), "a refused start created the caller's state_dir"
    cfg.write_text(CFG_OK.replace("<input>", "<!-- a -- b -->\n        <input>"))
    refused("comment", s.start(**args, cfg=str(cfg)))
    cfg.write_text(CFG_OK.replace('name="m68k"', 'name="v30"'))
    refused("v30", s.start(**args, cfg=str(cfg)))
    refused("must be an absolute path", s.start(**args, cfg="run/cfg/v30.cfg"))
    refused("no such cfg", s.start(**args, cfg=str(tmp_path / "missing.cfg")))
    assert s.status()["session"]["alive"] is False, "nothing was spawned"


def test_a_cfg_mame_did_not_read_ends_the_session_it_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The control AFTER the boot. MAME says it refused the file with `osd_printf_warning`
    (`config.cpp`, `load_xml`), and the OSD sends the WARNING channel to stderr
    (`osdobj_common.cpp`, `output_callback`), never to `error.log`, which is `logerror`'s:
    the line lands in the `stdout.log` this server captures both streams into. The first
    version read `error.log`, so the control could never fire. The line planted where MAME
    writes it is INVALID with the session closed, like the ROM check; planted in
    `error.log` it is not the proof."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    cfg = tmp_path / "good.cfg"
    cfg.write_text(CFG_OK)
    line = "Error parsing XML configuration file m68k.cfg\n"

    class _Complaining(_StubProcess):
        """A MAME that refuses its cfg: the warning goes down the stdout handle it was
        handed, the way the real one's stderr does (`stderr=STDOUT`)."""

        def __init__(self, *a: object, **k: object) -> None:
            super().__init__(*a, **k)
            out = k["stdout"]
            assert isinstance(out, io.BufferedIOBase), "start opens stdout.log in binary"
            out.write(b"boot\n" + line.encode())
            out.flush()

    import subprocess
    real_popen = subprocess.Popen
    # `-debugger` is what makes an invocation the EMULATOR: `start` asks the same binary
    # `-listxml` first, and that one must really run rather than meet a double built for
    # the boot.
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _Complaining(*a, **k)
                        if (str((a[0] if a else k["args"])[0]).endswith("fake-mame")
                            and "-debugger" in (a[0] if a else k["args"]))
                        else real_popen(*a, **k))
    out = refused("did not read", s.start(**_boot_args(tmp_path, image), cfg=str(cfg)))
    assert "Error parsing XML configuration file m68k.cfg" in out["message"], out["message"]
    assert "`process` channel" in out["message"] and out["stdout_path"].endswith("stdout.log")
    assert s.status()["session"]["alive"] is False, (
        "a session MAME booted on the defaults was left alive")
    # The reader itself: it reads the captured stdout, and a line in `error.log` is not it.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assert launch.cfg_parse_error(scratch) is None
    (scratch / "error.log").write_text("boot\n" + line)
    assert launch.cfg_parse_error(scratch) is None, "error.log is not where MAME writes it"
    (scratch / "stdout.log").write_text("boot\n" + line + "more\n")
    assert launch.cfg_parse_error(scratch) == line.strip()


def test_a_tilde_path_is_expanded_and_a_relative_one_says_why(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A `~` path is ABSOLUTE to the person who typed it and no shell stands between them and
    this argument, so the judge expands it; a relative one is refused saying why."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert inputs.absolute("binary", "~/mame") == tmp_path / "mame"
    with pytest.raises(mstate.Invalid, match="must be an absolute path or start with `~`"):
        inputs.absolute("binary", "upstream/v30")
    assert inputs.absolute("binary", str(tmp_path / "mame")) == tmp_path / "mame"


def _refusal_text(fn: Any, *a: Any) -> str:
    """The words of the `Invalid` `fn(*a)` raises, or a failure saying it raised nothing."""
    try:
        fn(*a)
    except mstate.Invalid as e:
        return str(e)
    raise AssertionError(f"{fn.__name__}{a} refused nothing, so this case examined nothing")


def test_every_path_refusal_names_the_remedy_and_not_only_the_rule() -> None:
    """A refusal that only says "must be an absolute path" names the rule and withholds the
    reason: every path argument says why a relative one is refused, in one sentence."""
    relative = _refusal_text(inputs.fresh_dest, "dest", "snap/x.png")
    assert "would be judged in one directory and used in another" in relative, relative
    assert "start with `~`" in relative, relative


def test_close_lists_its_fields_in_the_order_its_docstring_promises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The last words of each channel come right after `closed`, then how it ended: the
    order the `Reply:` line gives, which a reader of the JSON follows."""
    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}order"
    scratch.mkdir()
    (scratch / "stdout.log").write_text("bye\n")
    (scratch / "error.log").write_text("")
    monkeypatch.setattr(mstate.STATE, "scratch", scratch)
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    keys = list(s.close(detail=True))
    promised = ["closed", "stdout_tail", "errorlog_tail", "ended_by", "exit_code"]
    assert [k for k in keys if k in promised] == promised, keys


def test_an_invalid_summary_is_cut_at_a_word_and_says_so() -> None:
    """The summary is one line a person reads without the JSON, so a long refusal is cut
    there: at a word, with a mark that says the rest is in `message`, never mid-word."""
    message = "the write side of 0x4a0 is unmapped: " + "a change watch there can never fire " * 6
    line = mame_mcp.BOUNDARY.line("watch_add", {}, {"status": "INVALID", "code": "bad_argument",
                                        "message": message})
    head = "watch_add: INVALID (bad_argument), "
    assert line.startswith(head), line
    shown = line.removeprefix(head)
    assert shown.endswith("...") and len(shown) <= 124, shown
    kept = shown.removesuffix("...")
    assert message.startswith(kept) and message[len(kept)] == " ", "cut at a word, never inside one"
    short = mame_mcp.BOUNDARY.line("x", {}, {"status": "INVALID", "code": "c", "message": "short"})
    assert short == "x: INVALID (c), short"


def test_a_docstring_placeholder_is_filled_from_its_constant_or_fails_the_import() -> None:
    """A number a description states is the constant that enforces it, and a placeholder
    nothing fills is a failure at import: shipped, it would read as a word, not a number."""
    assert mdocs.filled("x", "at most {READ_MAX} bytes") == f"at most {read.READ_MAX} bytes"
    with pytest.raises(TypeError, match=r"x's docstring names \['\{NOPE\}'\]"):
        mdocs.filled("x", "at most {NOPE} bytes")
    assert mdocs.filled("x", "a {lowercase} brace is prose") == "a {lowercase} brace is prose"


def test_the_docstrings_name_what_the_replies_carry_and_what_by_accepts() -> None:
    """`start` answers `symbols_typed` beside `symbols`, and `by` on a breakpoint takes
    five words: a docstring that names three teaches a caller two of them do not exist."""
    assert "`symbols_typed`" in documented("start")
    (tool,) = [t for t in asyncio.run(s.mcp.list_tools()) if t.name == "breakpoint_at"]
    assert tool.input_schema["properties"]["by"]["enum"] == ["auto", "symbol", "address"]
    assert "never an expression" in published("breakpoint_at")


# --------------------------------------- what moves the machine, held at the fields it answers


def test_a_controls_hits_are_the_delta_and_the_count_after_only_when_it_fell() -> None:
    main = ":maincpu"
    before: dict[tuple[str, str | None], int] = {("same", main): 5, ("rose", main): 5,
                                                 ("fell", main): 5}
    after: dict[tuple[str, str | None], int] = {("same", main): 5, ("rose", main): 8,
                                                ("fell", main): 3}
    assert advance._hits(before, after, list(after)) == [
        {"ref": "same", "cpu": ":maincpu", "hits_in_run": 0},
        {"ref": "rose", "cpu": ":maincpu", "hits_in_run": 3},
        {"ref": "fell", "cpu": ":maincpu", "hits_in_run": 3}]
    assert advance._hits(before, after, [("rose", main)]) == [
        {"ref": "rose", "cpu": ":maincpu", "hits_in_run": 3}], "only the owners asked for"


def test_run_to_refuses_a_target_a_breakpoint_already_holds_in_the_words_of_that_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x4a0")
    out = refused(r"already has breakpoint 1 at 0x4a0: a stop there", s.run_to(
        ref="0x4a0", control="0x25a4", seconds=1.0))
    assert "(condition" not in out["message"], out["message"]
    s.declaration_clear("breakpoint", all=True)
    s.breakpoint_at(ref="0x4a0", condition="d0 == 1")
    out = refused(r"at 0x4a0 \(condition \S.*\): a stop there", s.run_to(
        ref="0x4a0", control="0x25a4", seconds=1.0))
    assert ses.running is False


def test_a_target_the_console_does_not_list_is_refused_in_the_words_of_how_it_was_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(ses, "breakpoint", lambda addr, remove=False: None)   # taken, not listed
    out = refused("the console took `bp 0x4a0::maincpu` and its `bplist` does not list it",
                  s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0))
    assert out["code"] == "readback_refused" and out["control_hits"] == 0, out


def test_run_to_polls_inside_its_bound_and_names_the_stop_it_did_not_ask_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    s.breakpoint_at(ref="0x1000")
    ses.pcs = [0xF2034, 0x1000]
    ses.stops_after_polls = 1
    bounds: list[float] = []
    poll = ses.poll_stop

    def polled(timeout: float = 0.0) -> bool:
        bounds.append(timeout)
        return poll(timeout)

    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 1

    monkeypatch.setattr(ses, "poll_stop", polled)
    monkeypatch.setattr(ses, "go", go)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=2.0)
    assert out["verdict"] == "OTHER_STOP" and out["cause"] == "breakpoint at 0x1000", out
    assert "condition" not in out, "a run with no condition carries none"
    assert bounds and all(isinstance(b, float) and 0.0 <= b <= advance.RUN_POLL_S for b in bounds)


def test_a_run_to_that_found_nothing_to_trust_still_answers_with_every_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # The session broke under the run: the count is a zero that says nothing was measured.
    ses = _running(monkeypatch, tmp_path)

    def poll(timeout: float = 0.0) -> bool:
        raise g.SessionError("the stub closed the connection")

    disarmed: list[bool] = []
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bpclear"):
            disarmed.append(True)
            raise g.SessionError("the stub closed the connection")
        return str(real(command, timeout))

    monkeypatch.setattr(ses, "poll_stop", poll)
    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["code"] == "session_broken" and out["control_hits"] == 0, out
    assert disarmed == [True], "the removal is tried, and its failure is not the news"
    # The control never fired: the stop is surveyed, each control listed with its listing.
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x1000]
    ses.stops_after_polls = None
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)
    real_monitor = ses.monitor

    def no_listing(command: str, timeout: float = 10.0) -> str:
        if command.startswith("dasm ") and "0x25a4" in command:
            raise g.SessionError("the console refused the listing")
        return real_monitor(command, timeout)

    monkeypatch.setattr(ses, "monitor", no_listing)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["code"] == "control_silent", out
    assert out["controls"] == [{"ref": "0x25a4", "cpu": ":maincpu", "hits_in_run": 0}], out
    assert out["control_dasm"] == [{"ref": "0x25a4", "cpu": ":maincpu", "dasm": {
        "available": False, "why": "the console refused the listing"}}], out
    assert out["message"].startswith("the control (0x25a4) never fired"), out["message"]
    # A stop that was not the target's, before any control fired: cut, with the controls listed.
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x1000]
    ses.stops_after_polls = 1
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0)
    assert out["code"] == "cut_by_other_stop"
    assert out["controls"] == [{"ref": "0x25a4", "cpu": ":maincpu", "hits_in_run": 0}]


def test_an_interrupt_the_stub_refuses_at_the_bound_does_not_escape_run_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.stops_after_polls = None
    monkeypatch.setattr(advance, "RUN_POLL_S", 0.0)

    def wedged(timeout: float = 5.0) -> str:
        raise g.Timeout("no answer within 5 s")     # as the real one: no stop was noted

    monkeypatch.setattr(ses, "interrupt", wedged)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=0.05)
    assert out["status"] == "INVALID" and out["code"] == "not_settled", out


def test_a_conditional_run_to_carries_the_condition_as_the_console_read_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.pcs = [0xF2034, 0x4A0]
    ses.stops_after_polls = 1
    real_go = ses.go

    def go() -> None:
        real_go()
        ses.temps[0] = ses.temps.get(0, 0) + 1

    monkeypatch.setattr(ses, "go", go)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, condition="  d0 == 1 ")
    assert out["verdict"] == "TARGET", out
    assert out["condition"] == conditions.console_condition("  d0 == 1 ") == "d0 == 1", out


def test_the_account_of_a_stop_found_later_has_every_field_and_the_name_of_where_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr("mame_running.time.monotonic", lambda: 100.0)   # no span, so no speed
    s.breakpoint_at(ref="0x4a0")
    ses.pcs = [0xF2034, 0x4A0]
    s.resume()
    ses.stops_after_polls = 1
    bounds: list[float] = []
    poll = ses.poll_stop

    def polled(timeout: float = 0.0) -> bool:
        bounds.append(timeout)
        return poll(timeout)

    monkeypatch.setattr(ses, "poll_stop", polled)
    found = s.status()["stopped_on_its_own"]
    assert found == {"stop_seq": 2, "pc": "0x000004a0", "cpu": ":maincpu", "frame": ses.frame,
                     "cause": "breakpoint at 0x4a0", "packet": "T05"}, found
    assert bounds == [0.0], "the first contact looks and never waits"


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


def test_a_console_run_found_at_rest_carries_the_speed_of_the_window_it_ends(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    wall = [100.0]
    monkeypatch.setattr("mame_running.time.monotonic", lambda: wall[0])
    monkeypatch.setattr(running, "frame_at_rest", lambda ses_, reads=3, gap_s=0.1: True)
    ses.emu_clock = 5.0
    assert s.resume()["session"]["running"] is True
    monkeypatch.setattr(mstate.STATE, "console_run", True)
    wall[0], ses.emu_clock = 102.0, 6.0
    found = s.status()["stopped_on_its_own"]
    assert found["packet"] == "none: a run the console started", found
    assert found["average_speed"] == {"percent": 50.0, "emulated_s": 1.0,
                                      "wall_s": 2.0}, found
    assert mstate.STATE.run_release is None


def test_a_reader_refused_on_a_running_machine_is_told_the_last_stop_or_that_there_is_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.running = True
    with pytest.raises(g.NotStopped,
                       match=r"; last seen stopped at pc 0x000f2034 on :maincpu \(start, "):
        running.require_stopped(ses, "a read")  # type: ignore[arg-type]
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    with pytest.raises(g.NotStopped, match="; no stop recorded yet. Wait for"):
        running.require_stopped(ses, "a read")  # type: ignore[arg-type]


def test_the_survey_says_truncated_only_past_what_it_shows_and_dates_the_watches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    log = files.log_path(tmp_path, "emulator")
    shown = log_marks.STOP_LINES_SHOWN
    log.write_text("".join(f"line {n}\n" for n in range(shown)))
    monkeypatch.setattr(mstate.STATE, "errorlog_mark", 0)
    seen = running.survey(ses, tmp_path)  # type: ignore[arg-type]
    assert seen["errorlog"]["lines_total"] == shown and seen["errorlog"]["mark"] == 0
    assert seen["errorlog"]["truncated"] is False, "exactly what is shown is not truncated"
    assert "how" not in seen["errorlog"], "a whole block names no way to ask for more"
    # One past what is shown: cut, from the mark where the previous stop left the log, and the
    # block names the call that reads the rest from there.
    since = log.stat().st_size
    with log.open("a") as fh:
        fh.write("".join(f"more {n}\n" for n in range(shown + 1)))
    cut = running.survey(ses, tmp_path)["errorlog"]  # type: ignore[arg-type]
    assert cut["truncated"] and cut["lines_total"] == shown + 1 and cut["mark"] == since, cut
    assert cut["lines"][0] == "more 1" and f"since_mark={since}" in cut["how"], cut
    handed: list[tuple[Any, ...]] = []
    monkeypatch.setattr(watches, "evaluate_watches",
                        lambda *a: handed.append(a) or [])  # type: ignore[func-returns-value]
    running.survey(ses, tmp_path)  # type: ignore[arg-type]
    assert handed[0][1] == {} and handed[0][2] == {} and handed[0][3] == ses.frame, handed
    # An expression list the console refuses whole takes the expressions down, never the frame.
    monkeypatch.setattr(watches, "expression_refs", lambda: ["nope"])
    running.survey(ses, tmp_path)  # type: ignore[arg-type]
    assert isinstance(handed[1][2], g.SessionError) and handed[1][3] == ses.frame, handed[1]
    # And an answer shorter than the list asked for is never paired off silently.
    monkeypatch.setattr(read, "print_values", lambda ses_, names: [ses.frame])
    with pytest.raises(ValueError, match="zip"):
        running.survey(ses, tmp_path)  # type: ignore[arg-type]


def test_a_conditional_target_the_console_does_not_list_is_refused_as_the_console_took_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    real_monitor = ses.monitor

    def deaf(command: str, timeout: float = 10.0) -> str:
        return "" if command.startswith("bp 0x4a0:") else real_monitor(command, timeout)

    monkeypatch.setattr(ses, "monitor", deaf)
    out = refused(r"the console took `bp 0x4a0::maincpu,.+` and its `bplist` does not list it",
                  s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, condition="d0 == 1"))
    assert out["code"] == "readback_refused", out


def test_a_target_listed_without_its_condition_is_removed_before_the_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A row armed bare where a conditioned one was sent stops at every pass, and nobody would
    own it: the refusal takes it down first, by its index."""
    ses = _running(monkeypatch, tmp_path)
    real_monitor = ses.monitor

    def bare(command: str, timeout: float = 10.0) -> str:
        if command.startswith("bp 0x4a0:") and "," in command:
            command = command.split(",", 1)[0]          # the console dropped the condition
        return real_monitor(command, timeout)

    monkeypatch.setattr(ses, "monitor", bare)
    out = s.run_to(ref="0x4a0", control="0x25a4", seconds=1.0, condition="d0 == 1")
    assert out["code"] == "readback_refused" and "without its condition" in out["message"], out
    assert not any(r["addr"] == 0x4A0 for r in mlists.bp_held(ses)  # type: ignore[arg-type]
                   ), "the bare row is gone"


# ------------------------------------------------ the two runs the console starts, at their edges


def _by_frames(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kw: Any) -> _RegisterSession:
    ses = _RegisterSession(bits=32, frame=10, **kw)
    _install(monkeypatch, ses, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", {})
    monkeypatch.setattr(mstate.STATE, "console_run", False)
    monkeypatch.setattr(advance, "VBLANK_SETTLE_S", 0.0)
    monkeypatch.setattr(advance, "FRAME_POLL_S", 0.0)
    return ses


def test_a_run_by_frames_that_elapsed_says_so_with_its_clock_its_polls_and_its_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    ses.last_stop_packet = "T05watch:200fd4;"
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    said: list[str] = []
    out = advance.run_for(ses, tmp_path, 0, 5.0,  # type: ignore[arg-type]
                          lambda _p, _t, m: said.append(m), frames=2)
    assert out["verdict"] == "ELAPSED" and "elapsed" not in out["cause"], out
    assert (out["frame_before"], out["frame_after"], out["polls"]) == (10, 12, 2), out
    assert out["cycles"] == 2 * ses.cycles_per_frame, out
    assert said[0] == "run_for 2 frames: frame 11 of 12, 0s of 5s", said
    assert ses.last_stop_packet == "", "the packet of the stop before the run is not this stop's"
    assert ses.commands.count("print frame") == 2 * 2 + 2 + 1, (
        "two agreeing reads confirm each landing, two a gap apart prove the last one at rest, "
        "and the survey reads the frame once")


def test_a_run_by_frames_reports_frames_done_of_the_frames_asked_and_ends_at_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The measure of a frame run is its frames, not its wall-clock bound: a run that finishes
    well inside `seconds` ends its bar at 100%, and one report comes when the loop ends,
    whatever the period let through before it."""
    ses = _by_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    got: list[tuple[float, float | None]] = []

    def record(p: float, t: float | None, _m: str) -> None:
        got.append((p, t))

    out = advance.run_for(ses, tmp_path, 0, 5.0,  # type: ignore[arg-type]
                          mprogress.RebasedProgress(record), frames=3)
    assert out["verdict"] == "ELAPSED", out
    assert got[-1] == (3.0, 3.0), got
    assert all(t == 3 for _p, t in got) and all(0 <= p <= 3 for p, _t in got), got
    values = [p for p, _t in got]
    assert all(b > a for a, b in zip(values, values[1:], strict=False)), got
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 3600.0)
    got.clear()
    out = advance.run_for(ses, tmp_path, 0, 5.0, record, frames=2)  # type: ignore[arg-type]
    assert out["verdict"] == "ELAPSED", out
    assert got == [(2.0, 2.0)], got


def test_the_waits_measured_in_time_report_no_total(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    totals: list[float | None] = []
    ses.stops_after_polls = 3
    advance.run_to(ses, tmp_path, "0x4a0", "0x25a4", 1.0,  # type: ignore[arg-type]
                   lambda _p, t, _m: totals.append(t))
    assert totals and all(t is None for t in totals), totals
    totals.clear()
    ses.stops_after_polls = 3
    running.resume(ses, tmp_path, 1.0, lambda _p, t, _m: totals.append(t))  # type: ignore[arg-type]
    assert totals and all(t is None for t in totals), totals


def test_a_run_by_frames_whose_alignment_clock_cannot_be_read_reports_no_cycles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    ses.frozen = True                           # the aligning tick: the counter does not move
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "print totalcycles" and ses.frozen:
            ses.frozen = False
            raise g.SessionError("the console refused `print totalcycles`")
        return real(command, timeout)

    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_for(frames=1)
    assert out["verdict"] == "ELAPSED" and out["polls"] == 2, out
    assert out["cycles"] == {"available": False, "why": "`totalcycles` could not be read before "
                                                         "the run, so there is no baseline"}, out


def test_a_run_by_frames_that_never_moves_gives_up_one_gvblank_past_the_alignment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    ses.frozen = True
    out = s.run_for(frames=1)
    assert out["code"] == "no_progress" and ses.commands.count("gvblank") == 3, out
    assert (out["frame_before"], out["frame_after"]) == (10, 10), out
    assert ses.running is True and mstate.STATE.console_run is True
    # THE COUNTER THAT NEVER MOVED CANNOT PROVE REST: the next reader's contact reads it
    # frozen, which is what it already was, so the machine stays RUNNING until `stop`.
    assert s.read_memory(ref="0x400")["code"] == "not_stopped"
    assert ses.running is True, "no contact took the frozen counter for a stop"


class _ScriptedClock(mprogress.Ticker):
    """A bound that runs out when the test says so, one answer per look."""

    answers: list[bool] = []

    def expired(self) -> bool:
        return self.answers.pop(0) if self.answers else True


@pytest.mark.parametrize("looks,reads,after", [
    ([False, True], ["a"], 10),                 # no reading of the landing (the survey's one)
    ([False, False, True], ["b"], 11),          # one reading, and it is the landing's
    ([False, False, False, True], ["b", "c"], 12),   # two that disagree: the LAST one
])
def test_a_run_by_frames_out_of_clock_reports_the_last_frame_it_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, looks: list[bool], reads: list[str],
    after: int,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    ses.frame_answers = ["a", *reads]           # the first is the reading before the run
    monkeypatch.setattr(_ScriptedClock, "answers", list(looks))
    monkeypatch.setattr(mprogress, "Ticker", _ScriptedClock)
    out = s.run_for(frames=5)
    assert out["code"] == "not_settled", out
    assert (out["frame_before"], out["frame_after"]) == (10, after), out


def test_a_run_by_frames_cut_by_a_stop_this_server_armed_counts_the_clock_up_to_the_cut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "here", 0xF2034)))
    out = s.run_for(frames=3)
    assert out["verdict"] == "OTHER_STOP" and out["polls"] == 1, out
    assert (out["frame_before"], out["frame_after"]) == (10, 11), out
    assert out["cycles"] == ses.cycles_per_frame, out
    # With the clock unreadable at the cut the cycles are None, never a guess.
    ses = _by_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "here", 0xF2034)))
    real = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command == "print totalcycles":
            raise g.SessionError("the console refused `print totalcycles`")
        return real(command, timeout)

    monkeypatch.setattr(ses, "monitor", monitor)
    out = s.run_for(frames=3)
    assert out["verdict"] == "OTHER_STOP" and out["cycles"]["available"] is False, out
    # And a clock that could not be read at the ALIGNING tick stays unknown at the cut, even
    # when the console answers again by then.
    ses = _by_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "here", 0xF2034)))
    ses.frozen = True
    real_again = ses.monitor
    refused_once: list[bool] = []

    def once(command: str, timeout: float = 10.0) -> str:
        if command == "print totalcycles" and not refused_once:
            refused_once.append(True)
            raise g.SessionError("the console refused `print totalcycles`")
        return real_again(command, timeout)

    monkeypatch.setattr(ses, "monitor", once)
    out = s.run_for(frames=3)
    assert out["verdict"] == "OTHER_STOP" and out["cycles"]["available"] is False, out


def test_each_reason_a_run_has_no_cycles_is_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cycles` unavailable names which of the three it is: no baseline, two cpus' counters, or
    a counter that could not be read after the run."""
    def refused(_ses: object, _names: list[str]) -> list[int]:
        raise g.SessionError("the console refused `print totalcycles`")

    assert "no baseline" in str(advance._span(None, None, None, None))  # type: ignore[arg-type]
    assert "each cpu keeps its own" in str(
        advance._span(None, 100, ":maincpu", ":subcpu"))  # type: ignore[arg-type]
    monkeypatch.setattr(read, "print_values", refused)
    assert advance._span(None, 100, ":maincpu", ":maincpu") == unavailable(  # type: ignore[arg-type]
        "`totalcycles` could not be read after the run: the console refused `print totalcycles`")


def test_a_run_by_time_that_made_no_progress_still_says_how_it_ended_and_between_which_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    ses.frame_answers = ["a"] * 5
    out = s.run_for(milliseconds=1)
    assert out["code"] == "no_progress" and out["cause"] == "the console's `gtime` stop", out
    assert (out["frame_before"], out["frame_after"]) == (10, 10), out


def test_a_run_by_time_cut_at_a_breakpoint_this_server_armed_is_named_by_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "breakpoints", bp_records((1, "there", 0xF2100)))
    ses.frame_answers = ["a"] * 5               # cut before a frame elapsed
    out = s.run_for(milliseconds=1)
    assert out["status"] == "ok" and out["verdict"] == "OTHER_STOP", out
    assert out["cause"] == running.attribute(0xF2100, ":maincpu") != (
        "stopped at no breakpoint this server armed")


@pytest.mark.parametrize("refusal", [g.SessionError("the socket went"), OSError("broken pipe")])
def test_a_run_by_time_at_its_bound_reports_the_frame_the_machine_came_to_rest_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, refusal: Exception,
) -> None:
    """The interrupt lands a few readings late, and a refused one is not the news: the frame
    reported is the one the counter RESTED at, and the progress line names the frame it read."""
    ses = _by_frames(monkeypatch, tmp_path, stop_after=None)
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)

    def halt() -> None:
        ses.interrupted = True
        ses.stop_after = ses.polls_since_gtime + 3      # three more frames go by first
        halted_at.append(len(ses.commands))
        raise refusal

    halted_at: list[int] = []
    monkeypatch.setattr(ses, "halt", halt)
    said: list[str] = []
    out = advance.run_for(ses, tmp_path, 60000, 0.05,  # type: ignore[arg-type]
                          lambda _p, _t, m: said.append(m))
    assert out["verdict"] == "TIMEOUT" and out["cause"] == "interrupt at the bound", out
    assert out["frame_after"] == ses.frame and out["frame_before"] == 10, out
    assert re.fullmatch(r"run_for 60000 ms: frame \d+, 0s of 0.05s", said[0]), said[0]
    rested = [c for c in ses.commands if c == "print frame"]
    assert out["reads"] == len(rested) - 1, "every reading but the survey's own is counted"
    after_halt = ses.commands[halted_at[0]:]
    assert after_halt[:7] == ["print frame"] * 5 + ["cpulist", "print frame"], (
        "three moving readings, then the third that agrees ends the wait; the sixth, after "
        "the visible cpu, is the survey's")
    assert after_halt[7] != "print frame"


def test_a_run_by_time_that_never_rests_reports_the_last_frame_it_saw_moving(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _by_frames(monkeypatch, tmp_path, stop_after=None)
    monkeypatch.setattr(running, "CONSOLE_HALT_SETTLE_S", 0.05)
    monkeypatch.setattr(ses, "halt", lambda: None)
    out = s.run_for(milliseconds=1000, seconds=0.05)
    assert out["code"] == "not_settled", out
    assert (out["frame_before"], out["frame_after"]) == (10, ses.frame), out


# ------------------------ what the mutation survivors of launch and state left loose


def test_boot_hands_the_inipath_and_the_scratch_as_cwd_to_the_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`build_command` is tested alone; whether `boot` hands it the caller's `inipath` and
    runs the process IN the scratch was not. A driver's `mame.ini` routed in through
    `-inipath` fell out of the argv in silence, and a MAME run anywhere else writes its
    `cfg/` where it stands rather than where the reply says."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    ini = tmp_path / "ini"
    ini.mkdir()
    out = s.start(**_boot_args(tmp_path, image), inipath=str(ini))
    try:
        argv = _StubProcess.last_argv
        assert argv[argv.index("-inipath") + 1] == str(ini)
        assert str(_StubProcess.last_kwargs["cwd"]) == out["scratch_dir"]
    finally:
        s.close()


def test_boot_connects_the_stub_on_the_judged_port_and_names_a_zero_wait_honestly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two things the connect loop must get right that no case held: the session is opened on
    the port `judge` chose, and a `wait` of zero, which never enters the loop, is reported as
    a stub that did not answer and never as a process that exited with an empty code."""
    import subprocess
    from types import SimpleNamespace

    ports: list[int] = []
    owners: list[Any] = []

    class Refusing:
        def __init__(self, port: int, owner: object = None) -> None:
            ports.append(port)
            owners.append(owner)

        def dial(self) -> None:
            raise OSError("connection refused")

    class Spawned:
        pid = 4321

        def poll(self) -> int | None:
            return None

    monkeypatch.setattr(g, "Session", Refusing)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Spawned())
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "proc", None)
    judged = SimpleNamespace(
        state_dir="", boot_lua="", env={}, throttle_from_frame=0, binary="mame",
        system="sys", rompath=str(tmp_path), port=23999, flags=[], inipath="", wait=0.05,
        ref=tmp_path / "ref.bin", ref_addr=0, ref_base=0, cfg=None, background=False,
        presence=False, view="")
    with pytest.raises(mstate.Invalid) as e:
        launch.boot(judged)  # type: ignore[arg-type]
    assert ports and set(ports) == {23999}, ports
    # THE PROOF IS THIS LAUNCH'S: the spawned pid on the judged port, a deadline no sooner than
    # one request's wait, and the liveness of this session's MAME.
    proof = owners[0]
    assert (proof.pid, proof.port) == (4321, 23999), proof
    assert proof.deadline - time.monotonic() > g.REQUEST_TIMEOUT_S - 1, proof
    assert proof.alive == mstate.STATE.machine_alive
    assert "did not answer within 0.05 s: connection refused" in str(e.value)
    judged.wait = 0.0
    (tmp_path / "second").mkdir()
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path / "second")
    with pytest.raises(mstate.Invalid) as e:
        launch.boot(judged)  # type: ignore[arg-type]
    assert "did not answer within 0" in str(e.value) and "exited" not in str(e.value)
    assert e.value.fields["exit_code"]["available"] is False


def test_start_records_for_the_later_tools_everything_it_judged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """What `start` writes into STATE for the tools that come after it, held field by field:
    `system` (`status`), `reference` (`state_write(method="load")`'s ROM check), `boot_pc`
    (`reset`'s
    readback), the table's spans, bases, classes and segment bases (`find`, `disassemble`,
    the pointer watches), which a `types` file must not strip when it rebuilds the table, a
    `bases` key in any case, and the `wait` handed to the `-listxml` collection, which bounds
    a query that would otherwise be waited for without limit, on the boot that works and on
    the one that fails."""
    image = bytes(range(64))
    ses = _stub_boot(monkeypatch, tmp_path, image, at=0x20000)
    waits: list[tuple[str, float]] = []
    real = machine.listxml

    def recording(asked: Any, binary: str, system: str, seconds: float) -> Any:
        waits.append((system, seconds))
        return real(asked, binary, system, seconds)

    monkeypatch.setattr(machine, "listxml", recording)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "raw.bin"
    rom.write_bytes(image)
    sym = tmp_path / "game.map"
    sym.write_text("_start\tED000\t_TEXT\t0\tCODE\ndemo_count\t2A007\t_DATA\tA007\tDATA\n")
    types = tmp_path / "types.txt"
    types.write_text("demo_count: u16\n")
    common = dict(binary=str(binary), system="v30", rompath=str(tmp_path), reference_rom=str(rom),
                  reference_addr="0x20010", reference_base="0x20000", symbols=str(sym),
                  bases={"data": "0x400"}, types=str(types))
    out = s.start(**common, boot_seconds=3.5)
    try:
        assert waits == [("v30", 3.5)]
        assert mstate.STATE.system == "v30"
        assert mstate.STATE.reference == (rom, 0x20010, 0x20000)
        assert mstate.STATE.boot_pc == 0x20000
        assert out["symbols_by_class"] == {"CODE": 1, "DATA": 1}
        assert out["symbols_format"] == "tsv" and out.get("symbols_typed", 0) == 1
        assert mstate.STATE.resolve("demo_count") == 0x400 + 0xA007
        table = mstate.STATE.table()
        assert table.class_span and table.bases and table.classes
        assert table.segment_bases
    finally:
        s.close()
    # THE BOOT THAT FAILS collects the query with the same bound, before it names the symptom.
    monkeypatch.setattr(ses, "dial", lambda: (_ for _ in ()).throw(OSError("refused")))
    refused("did not answer", s.start(**common, boot_seconds=0.2))
    assert waits[-1] == ("v30", 0.2), waits


def test_start_hands_its_progress_to_the_kill_its_guard_makes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The kill a failed boot triggers is a wait the owner watches, and it paints through the
    progress `start` was given; handed None, the first tick would raise inside the guard."""
    image = bytes(range(64))
    ses = _stub_boot(monkeypatch, tmp_path, image, at=0)
    monkeypatch.setattr(ses, "dial", lambda: (_ for _ in ()).throw(OSError("refused")))
    seen: list[Any] = []
    real = mstate.wait_exit

    def recording(proc: Any, seconds: float, progress: Any, what: str) -> int | None:
        seen.append(progress)
        return real(proc, seconds, progress, what)

    monkeypatch.setattr(mstate, "wait_exit", recording)
    refused("did not answer", s.start(**_boot_args(tmp_path, image), boot_seconds=0.2))
    assert seen and all(p is mprogress.no_progress for p in seen), seen


def test_close_reports_the_console_pipe_as_it_found_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Three shapes of the drain's account: a session that BROKE is drained of nothing and
    says zero and zero with no note; a drain the channel refuses falls back to the count of
    lines still in the pipe with nothing drained, and the note says stepping did not evaluate
    them (the machine was stopped); a drain that emptied the pipe earns no note at all."""
    import mame_transport as transport

    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}pipe"
    scratch.mkdir()
    ses = _RecordingSession()
    ses.broken = "the stub answered nonsense"
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.scratch = scratch
    closed = s.close()
    assert closed["console_pending_before"] == 0 and closed["console_drained"] == 0
    assert "note" not in closed and "average_speed" not in closed
    scratch.mkdir()
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.scratch = scratch

    def refusing(ses_: Any, scratch_: Path) -> tuple[int, int]:
        raise g.SessionError("the stub went away")

    def three(scratch_: Path) -> int:
        assert scratch_ == scratch
        return 3

    monkeypatch.setattr(transport, "drain", refusing)
    monkeypatch.setattr(transport, "pending_lines", three)
    closed = s.close()
    assert closed["console_pending_before"] == 3 and closed["console_drained"] == 0
    assert "stepping the machine did not" in closed["note"], closed["note"]
    scratch.mkdir()
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.scratch = scratch
    monkeypatch.setattr(transport, "drain", lambda ses_, scratch_: (2, 2))
    closed = s.close()
    assert closed["console_pending_before"] == 2 and closed["console_drained"] == 2
    assert "note" not in closed


def test_close_counts_the_deaths_and_reruns_no_lua_call_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A session whose only console traffic was a `throttle` while stopped never had its
    stdout read by a detector, so a reader death and a chunk run twice stayed at three zeros
    on every reply, `close`'s included. `close` reads what nobody did: the deaths by position
    and the reruns in the unconsumed tail, and its session block says so. A log with none of
    either stays at zeros (the control)."""
    import mame_transport as transport

    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}unread"
    scratch.mkdir()
    (scratch / "stdout.log").write_bytes(b"boot\n")
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.scratch = scratch
    monkeypatch.setattr(transport, "drain", lambda ses_, scratch_: (0, 0))
    closed = s.close()
    assert closed["session"]["console"] == {"thread_errors": 0, "reruns": 0, "lost": 0}
    scratch.mkdir()
    (scratch / "stdout.log").write_bytes(
        b"boot\n" + transport.THREAD_ERROR + b" x\n"
        + 2 * (mstate.LUA_SENTINEL.encode() + b"#1\ttrue\tnil\n"))
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.scratch = scratch
    mstate.STATE.lua_seq, mstate.STATE.lua_answered = 1, 0
    closed = s.close()
    assert closed["session"]["console"] == {"thread_errors": 1, "reruns": 1, "lost": 0}, (
        closed["session"])


def test_close_proves_the_clean_exit_by_the_cfg_mame_writes_on_its_way_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`how: quit` must not mean only "exited within the grace period after quit was asked for",
    which a crash on the way out also satisfies. MAME rewrites `<state>/cfg/<system>.cfg`
    as it exits cleanly, so that file, newer than it was before the quit, is the proof:
    with it the ending is `quit`, without it `exited`, and `state_written` carries the
    reading; a State with no directory to read it in says null and keeps `quit`."""
    import os

    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}proof"
    (scratch / "cfg").mkdir(parents=True)
    cfg = scratch / "cfg" / "m68k-dual.cfg"
    cfg.write_text("<mameconfig/>")
    os.utime(cfg, ns=(1_000_000_000, 1_000_000_000))       # long before any exit

    class _Writing(_ExitingProcess):
        """A MAME that writes its cfg as it quits, the way the real one does."""

        def wait(self, timeout: float | None = None) -> int:
            cfg.write_text("<mameconfig>rewritten</mameconfig>")
            return super().wait(timeout)

    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _Writing(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.scratch, mstate.STATE.system = scratch, "m68k-dual"
    closed = s.close()
    assert closed["ended_by"] == "quit" and closed["state_written"] is True, closed
    assert closed["summary"].startswith("close: quit, exit code 0")
    (scratch / "cfg").mkdir(parents=True)
    cfg.write_text("<mameconfig/>")
    os.utime(cfg, ns=(1_000_000_000, 1_000_000_000))
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.scratch, mstate.STATE.system = scratch, "m68k-dual"
    closed = s.close()
    assert closed["ended_by"] == "exited" and closed["state_written"] is False, closed
    assert closed["summary"] == "close: exited without writing its state, exit code 0"
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    closed = s.close()
    assert closed["ended_by"] == "quit" and closed["state_written"]["available"] is False, closed


def test_a_cfg_that_cannot_be_read_back_says_which_file_and_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`changed: null` alone left a caller deciding whether to commit a cfg with no idea
    which of the two files could not be read; the `why` names it."""
    import os

    source = tmp_path / "repo.cfg"
    source.write_text("<mameconfig/>")
    installed = tmp_path / "installed.cfg"
    installed.write_text("<mameconfig/>")
    installed.chmod(0)
    if os.access(installed, os.R_OK):
        pytest.skip("this account reads a file with no permission bits (root?)")
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.cfg = {"source": source, "installed": installed, "replaced": False}
    try:
        closed = s.close()
    finally:
        installed.chmod(0o644)
    assert closed["cfg"]["changed"]["available"] is False, closed["cfg"]
    assert "installed.cfg" in closed["cfg"]["changed"]["why"], closed["cfg"]
    assert "could not be read back" in closed["cfg"]["changed"]["why"]


def test_free_port_takes_the_kernels_choice_and_refuses_when_there_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`free_port` asks the kernel for a port (a bind on 0) and never walks from a fixed number,
    which two starts at once would share; a kernel that hands out nothing is `host_failed` in
    the envelope. The bind is a double here,
    so the choice is judged on its own and never on what the host happens to hold."""
    asked: list[int] = []

    def bind(port: int) -> int:
        asked.append(port)
        return 51234

    monkeypatch.setattr(owner, "bind_probe", bind)
    assert launch.free_port() == 51234 and asked == [0], asked
    monkeypatch.setattr(owner, "bind_probe", lambda p: None)
    with pytest.raises(mstate.Invalid) as e:
        launch.free_port()
    assert e.value.code == "host_failed" and "free port" in str(e.value)


def test_a_free_port_is_the_kernels_and_binds() -> None:
    """The real kernel: the port it hands out is one a bind accepts, and it is not the stub's
    usual 23946 a walk would have started from."""
    port = launch.free_port()
    assert port != 23946 and launch.port_is_free(port), port


def test_the_top_of_the_tcp_range_is_a_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """65535 is the last port and was refused as if it were one past it."""
    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "no-helper"))
    monkeypatch.setattr(launch, "port_is_free", lambda p: True)
    args = _boot_args(tmp_path, bytes(16))
    judged = launch.judge(**args, symbols="", reference_addr="0x0", inipath="", wait=1.0,
                          shared=False, boot_lua="", env=None, bases=None, reference_base="0x0",
                          display="", port=65535, state_dir="", throttle_from_frame=0,
                          background=None)
    machine.listxml(judged.listxml, judged.binary, judged.system, judged.wait)
    assert judged.port == 65535


def test_judge_cfg_refuses_a_wrong_root_an_unreadable_file_and_a_cut_off_document_in_the_envelope(
    tmp_path: Path,
) -> None:
    """Three refusals of `judge_cfg` no case reached: each is `bad_argument` naming the file,
    and a document cut off before its closing tags is refused as not XML rather than parsed
    as a whole one (the parser is told the buffer is FINAL)."""
    import os

    wrong_root = tmp_path / "root.cfg"
    wrong_root.write_text('<?xml version="1.0"?>\n<foo><system name="m68k"/></foo>\n')
    with pytest.raises(mstate.Invalid) as e:
        launch.judge_cfg(str(wrong_root), "m68k")
    assert e.value.code == "bad_argument" and "not <mameconfig>" in str(e.value)
    cut = tmp_path / "cut.cfg"
    cut.write_text('<?xml version="1.0"?>\n<mameconfig version="10"><system name="m68k">\n')
    with pytest.raises(mstate.Invalid) as e:
        launch.judge_cfg(str(cut), "m68k")
    assert e.value.code == "bad_argument" and "not XML" in str(e.value)
    unreadable = tmp_path / "locked.cfg"
    unreadable.write_text(CFG_OK)
    unreadable.chmod(0)
    try:
        if os.access(unreadable, os.R_OK):
            pytest.skip("this account reads a file with no permission bits (root?)")
        with pytest.raises(mstate.Invalid) as e:
            launch.judge_cfg(str(unreadable), "m68k")
        assert e.value.code == "bad_argument" and "cannot read the cfg" in str(e.value)
    finally:
        unreadable.chmod(0o644)


def test_check_ref_refuses_a_value_that_is_not_a_string_in_the_envelope() -> None:
    with pytest.raises(mstate.Invalid) as e:
        inputs.check_ref(5)
    assert e.value.code == "bad_argument" and "not a string" in str(e.value)


def test_a_broken_sessions_refusal_carries_the_reason_as_a_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ses = _running(monkeypatch, tmp_path)
    ses.broken = "the stub sent nonsense"
    out = s.registers()
    assert out["code"] == "session_broken" and out["broken"] == "the stub sent nonsense"


def test_settle_throttles_keeps_the_machines_word_verbatim_and_flags_the_other_setting() -> None:
    """A mark whose `throttled=` is neither word is kept VERBATIM in the row, because a value
    nobody anticipated is the one worth reading; and `false` after asking for `on` is the
    other setting, a row, never a switch that landed."""
    mstate.STATE.throttles_pending = [{"tag": "MAME_MCP_THROTTLE#1", "on": True, "seq": 1},
                                      {"tag": "MAME_MCP_THROTTLE#2", "on": True, "seq": 2}]
    mstate.settle_throttles(["[luaengine] MAME_MCP_THROTTLE#1 throttled=maybe frame=3",
                             "[luaengine] MAME_MCP_THROTTLE#2 throttled=false frame=4"])
    rows = mstate.STATE.throttles_not_applied
    assert [r["machine_reports"] for r in rows] == ["maybe", False], rows
    assert mstate.STATE.throttles_pending == []


def test_wait_exit_polls_the_process_at_the_exit_poll_and_never_for_ever() -> None:
    import subprocess

    seen: list[float | None] = []

    class Stuck:
        def wait(self, timeout: float | None = None) -> int:
            seen.append(timeout)
            raise subprocess.TimeoutExpired("mame", timeout or 0)

    assert mstate.wait_exit(Stuck(), 0.05, mprogress.no_progress, "x") is None  # type: ignore[arg-type]
    assert seen and all(t == mstate.EXIT_POLL_S for t in seen), seen


# ---------------------- what the mutation survivors of the tool surface's helpers left loose


@pytest.mark.parametrize(("name", "args", "reply", "expected"), [
    ("memdump", {"ref": "0x0"}, {"bytes": 32, "path": "/p"}, "memdump 0x0: 32 bytes to /p"),
    ("disassemble", {"ref": "0x0"}, {"lines": ["a", "b", "c"], "addr": "0x0"},
     "disassemble 0x0: 3 lines at 0x0"),
    ("snapshot", {}, {"bytes": 448, "path": "/p"}, "snapshot: 448 bytes at /p"),
    ("write", {"ref": "0x2031fc"}, {"bytes_written": 4, "verified": True},
     "write 0x2031fc: 4 bytes, verified True"),
    ("run_to", {"ref": "0x4a0"}, {"verdict": "TARGET", "control_hits": 3},
     "run_to 0x4a0: TARGET, control counted 3"),
    ("debug", {"command": "help"}, {"mutates": False, "clipped": False}, "debug 'help'"),
    ("debug", {"command": "poke"}, {"mutates": True, "clipped": True, "output_chars": 9000},
     "debug 'poke', mutates, 9000 chars to a file"),
    ("rom_check", {}, {"rom_check": "OK", "query_s": 0.0011, "cpu": ":maincpu"},
     "rom_check :maincpu: OK, 1.1 ms per query"),
    ("state_write", {"method": "save"}, {"name": "s1", "bytes": 100, "frame": 7},
     "state_write save: s1, 100 bytes at frame 7"),
    ("log_wait", {"channel": "emulator", "pattern": "x"},
     {"verdict": "TARGET", "already": False, "waited_s": 1.5},
     "log_wait emulator /x/: matched after 1.5 s"),
    ("log_wait", {"channel": "emulator", "pattern": "x"},
     {"verdict": "TARGET", "already": True, "waited_s": 0.0},
     "log_wait emulator /x/: matched already there"),
    ("log_wait", {"channel": "emulator", "pattern": "x"},
     {"verdict": "TIMEOUT", "waited_s": 2.0, "arrived_during": 3},
     "log_wait emulator /x/: TIMEOUT, no match in 2.0 s, 3 lines arrived"),
    ("resume", {"seconds": 0}, {}, "resume: running, no wait asked"),
    ("resume", {"seconds": 2.0}, {"verdict": "TIMEOUT", "waited_s": 2.0},
     "resume: TIMEOUT, still running after 2.0 s"),
    ("resume", {"seconds": 2.0}, {"verdict": "OTHER_STOP", "pc": "0x000004a0", "cause": "b"},
     "resume: OTHER_STOP at pc 0x000004a0 (b)"),
    ("perform", {}, {"steps_completed": 2, "verdict": "TIMEOUT"},
     "perform: 2 steps completed, TIMEOUT"),
    ("drive", {}, {"verify": {"checked": True, "seen": False, "verdict": "TIMEOUT"}},
     "drive: effect not seen, TIMEOUT"),
    ("drive", {}, {"act": {"verdict": "TIMEOUT"}, "verify": {"available": False}},
     "drive: act TIMEOUT, nothing verified"),
    ("drive", {}, {"verify": {"checked": False}}, "drive: no expectation"),
    ("registers", {}, {"regs": {"D0": "0", "D1": "1"}}, "registers: 2 registers"),
    ("registers", {}, {"regs": {"D0": "0"}, "superseded": True},
     "registers: 1 register, from the last stop"),
    ("breakpoint_at", {"ref": "0x4a0"}, {"armed": True, "while_running": True, "addr": "0x4a0"},
     "breakpoint_at 0x4a0: armed at 0x4a0 while running"),
    ("breakpoint_at", {"ref": "0x4a0"}, {"armed": True, "while_running": False, "addr": "0x4a0"},
     "breakpoint_at 0x4a0: armed at 0x4a0"),
    ("declaration_list", {"kind": "regpoint"},
     {"regpoints": [{"state": "armed"}, {"state": "armed"}, {"state": "gone"}]},
     "declaration_list regpoint: 3 regpoints (2 armed)"),
    ("regpoint_add", {}, {"ref": "d1==1", "armed": True, "while_running": True, "index": 1},
     "regpoint_add d1==1: armed, index 1 while running"),
    ("regpoint_add", {}, {"ref": "d1==1", "armed": True, "while_running": False, "index": 1},
     "regpoint_add d1==1: armed, index 1"),
    ("declaration_list", {"kind": "watch"},
     {"watches": [{"state": "armed"}, {"state": "armed"}, {"state": "evaluated"}]},
     "declaration_list watch: 3 watches (2 armed)"),
    ("declaration_list", {"kind": "watch"},
     {"watches": [{"state": "tallied"}, {"state": "captured"}, {"state": "evaluated"},
                  {"state": "no_dump_yet", "installed": True},
                  {"state": "no_dump_yet", "installed": False, "pending": True}]},
     "declaration_list watch: 5 watches (3 armed)"),
    ("step", {"count": 5}, {"instructions_completed": 2, "mode": "into", "pc": "0x000004a0"},
     "step 2 into: pc 0x000004a0"),
    ("watch_add", {"ref": "x"}, {"mode": "expr", "state": "evaluated", "reading": {"hex": "0x1"}},
     "watch_add x: expr watch evaluated, 0x1"),
    ("run_for", {"milliseconds": 100},
     {"verdict": "ELAPSED", "frame_before": 0, "frame_after": 5},
     "run_for 100 ms: ELAPSED, frame 0 to 5"),
    ("machine_map", {}, {"counts": {"cpus": 2}, "truncated": False}, "machine_map: 2 cpus"),
    ("machine_map", {}, {"counts": {"cpus": 2}, "truncated": True},
     "machine_map: 2 cpus, some sections cut (see `counts`)"),
])
def test_the_summary_line_of_each_tool_says_what_came_back(
    name: str, args: dict[str, Any], reply: dict[str, Any], expected: str,
) -> None:
    """One line per tool, in the tool's own words: the client paints nothing else, so a tool
    whose case fell out of `_summary` reads `<name>: ok` and two calls of it cannot be told
    apart. Each case here is a tool's line with its reply's own fields, and the branch of a
    line that reads one way or the other (stale, while running, cut, mutates, seen)."""
    assert mame_mcp.BOUNDARY.line(name, args, {"status": "ok", **reply}) == expected


def test_a_start_summary_names_the_re_armed_declarations_only_when_there_are_any() -> None:
    reply: dict[str, Any] = {"status": "ok", "system": "m68k-dual", "rom_check": "OK",
             "binary": "/opt/mame/mame", "binary_origin": "PATH", "symbols_total": 61,
             "pc": "0x000f2034", "machine": {n: 0 for n in machine.SECTIONS},
             "declarations": {"rearm": {"rearmed": []}}, "start_retries": []}
    assert mame_mcp.BOUNDARY.line("start", {}, reply) == (
        "start m68k-dual on /opt/mame/mame (PATH): rom_check OK, 61 symbols, pc 0x000f2034")
    reply["declarations"]["rearm"]["rearmed"] = [{"ref": "0x4a0", "cpu": ":maincpu"}]
    assert mame_mcp.BOUNDARY.line("start", {}, reply).endswith(
        ", 1 declaration re-armed: 0x4a0 on :maincpu")
    reply["declarations"]["rearm"]["rearmed"] = [{"ref": "0x4a0", "cpu": None}]
    assert mame_mcp.BOUNDARY.line("start", {}, reply).endswith(", 1 declaration re-armed: 0x4a0")


def test_a_refusal_is_clipped_for_the_summary_line_at_a_word_and_never_inside_one() -> None:
    """The ceiling is where a line stops being a line: a text at the ceiling is whole, one
    past it is cut at the last space before the ceiling with the mark, a text with no space
    is cut hard, and a space at the very start is not a word to cut at."""
    assert summaries.clipped("a" * 120) == "a" * 120
    assert summaries.clipped("a" * 121) == "a" * 120 + "..."
    assert summaries.clipped("a" * 100 + " " + "b" * 30) == "a" * 100 + "..."
    assert summaries.clipped(" " + "b" * 130) == " " + "b" * 119 + "..."
    assert summaries.clipped("a b" + "c" * 130) == "a..."
    assert summaries.clipped("a" * 121 + " b") == "a" * 120 + "..."


def test_the_schemas_refusal_carries_its_body_as_structured_content_too() -> None:
    """The seam answers the client twice, as text and as the structured half a typed client
    reads: the same body in both, or one of the two halves says nothing."""
    result = asyncio.run(s.mcp.call_tool("read_memory", {"ref": 5, "length": 16}))
    body = result.structured_content
    assert body is not None and body["status"] == "INVALID" and body["code"] == "bad_argument"
    assert body["summary"].startswith("read_memory: INVALID (bad_argument)")
    assert json.loads(result.content[0].text) == body


def test_a_by_outside_breakpoint_ats_words_lists_only_the_words_it_takes() -> None:
    """A closed vocabulary's refusal names the words the tool takes: listing `expr` and
    `pointer` to `breakpoint_at` sends the caller to a value it then refuses."""
    out = refused("by is one of", s.breakpoint_at(ref="0x4a0", by="bogus"))
    assert "'address'" in out["message"] and "expr" not in out["message"], out["message"]
    assert "pointer" not in out["message"], out["message"]
    out = refused("by is one of", s.watch_add(ref="0x4a0", mode="change", by="bogus", length=2))
    assert "'pointer'" in out["message"] and "'expr'" not in out["message"], (
        "a watch takes a pointer, and an expr watch is its mode, never its `by`")


@pytest.mark.parametrize(("offset", "accepted"), [
    ("10", False), ("0x10", True), ("0X10", True), ("4", True), ("9", True), ("1c", True),
    ("1C", True), ("99", False)])
def test_a_pointer_offset_that_reads_two_ways_is_written_0x(offset: str, accepted: bool) -> None:
    """`[PTR]+10` reads as 0x10 (sixteen bytes) in the shared grammar and as ten in decimal, so a
    call spells it `0x`: one digit or a hex letter reads one way."""
    import mame_inputs as minputs
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


def test_a_port_not_written_0x_is_refused_naming_its_argument() -> None:
    out = refused(r"^ref='6' must be a port", s.watch_add(ref="6", mode="count", length=2,
                                                           space="io"))
    assert out["code"] == "bad_argument" and "0x6" in out["message"], out
    out = refused(r"^trigger='beam' must be a port",
                  s.watch_add(ref="0x2031fc", mode="capture", length=4, trigger="beam",
                              space="io"))


def test_a_control_carrying_a_segment_is_refused_before_any_session() -> None:
    """A `control` is a ref like `ref`, and the shape every ref is held to is judged offline:
    a segment, or `0x` before what is not hex."""
    out = refused("carries a segment", s.run_to(ref="0x4a0", control="12:34"))
    assert out["code"] == "bad_argument", out
    refused(r"control='0xzz'", s.run_to(ref="0x4a0", control="0xzz"))


def test_a_steps_unknown_argument_is_refused_naming_the_ones_its_tool_takes() -> None:
    out = s.perform(steps=[{"op": "run_for", "frame": 3}])
    assert out["status"] == "INVALID" and "got an unexpected keyword argument 'frame'" in (
        out["message"]), out
    assert "`takes` names `run_for`'s" in out["message"], out["message"]
    takes = out["errors"][0]["takes"]
    assert "frames" in takes and "milliseconds" in takes and "ctx" not in takes, takes


def test_the_port_probe_answers_the_port_it_bound() -> None:
    """The real bind, not a double: the kernel's pick is a port, and a named free one is itself."""
    chosen = owner.bind_probe(0)
    assert chosen is not None and chosen > 0, chosen
    assert owner.bind_probe(chosen) == chosen


def test_each_mark_reads_its_own_channel_and_a_missing_file_is_zero(tmp_path: Path) -> None:
    """The stdout mark is the process channel's, `error.log`'s the emulator's: sizes told apart,
    and a channel not written yet is 0, never a FileNotFoundError on a fresh scratch."""
    import mame_transport as transport
    assert files.log_mark(tmp_path) == 0 and transport.stdout_mark(tmp_path) == 0
    files.log_path(tmp_path, "process").write_bytes(b"x" * 7)
    assert transport.stdout_mark(tmp_path) == 7 == files.log_mark(tmp_path, "process")
    assert files.log_mark(tmp_path) == 0, "the emulator's channel is not the process's"
    files.log_path(tmp_path, "emulator").write_bytes(b"y" * 3)
    assert files.log_mark(tmp_path) == 3 and transport.stdout_mark(tmp_path) == 7


def test_a_media_file_tool_answers_in_this_server_s_envelope(tmp_path: Path) -> None:
    """The file tools' bodies are scry-core's and answer bare fields; through this server each
    wears the envelope every other reply wears: `status`, `session` and its own summary."""
    from scry_core import png
    pic = tmp_path / "a.png"
    pic.write_bytes(png.encode(png.Raster(2, 2, bytes(12))))
    r = s.image_compare("image", a=str(pic), b=str(pic))
    assert r["status"] == "ok" and "session" in r, r
    assert r["summary"].startswith("image_compare image: no pixel differs"), r["summary"]


def test_a_live_runs_ledger_learns_every_mame_launched_a_start_that_fails_included(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The run's proof that no emulator outlived it reads this ledger: a start whose MAME
    never answered is exactly the one that would stay behind unrecorded. The fake writes its
    own pid, which is the one the ledger has to hold; outside a live run nothing is written."""
    from scry_core import live_host

    pid_file = tmp_path / "pid"
    binary = fake_mame(tmp_path)
    binary.write_text(f'#!/bin/sh\ncase "$*" in *-listxml*|*-version*) exit 0;; esac\n'
                      f'echo $$ > {pid_file}\nexit 0\n')
    rom = tmp_path / "ref.bin"
    rom.write_bytes(b"\x00" * 16)
    ledger = tmp_path / "emulators.tsv"
    for named in (True, False):
        pid_file.unlink(missing_ok=True)
        if named:
            monkeypatch.setenv(live_host.LEDGER_VAR, str(ledger))
        else:
            monkeypatch.delenv(live_host.LEDGER_VAR)
            ledger.unlink()
        reply = s.start(binary=str(binary), system="none", rompath=str(tmp_path),
                        reference_rom=str(rom), boot_seconds=1.0)
        assert reply["status"] == "INVALID", reply
        assert pid_file.is_file(), "the fake MAME never ran"
        if named:
            pid = int(pid_file.read_text())
            assert live_host.EmulatorLedger(ledger).recorded() == {pid: binary.name}
        else:
            assert not ledger.exists()


@pytest.mark.parametrize("asked", [True, False])
def test_judge_carries_presence_to_the_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, asked: bool
) -> None:
    """What `start` was asked of the presence reaches the boot that composes the drawer."""
    monkeypatch.setenv("WINDOW_APP", str(tmp_path / "no-helper"))
    args = _boot_args(tmp_path, bytes(16))
    judged = launch.judge(**args, symbols="", reference_addr="0x0", inipath="", wait=1.0,
                          shared=False, boot_lua="", env=None, bases=None, reference_base="0x0",
                          display="", port=0, state_dir="", throttle_from_frame=0,
                          background=None, presence=asked)
    machine.listxml(judged.listxml, judged.binary, judged.system, judged.wait)
    assert judged.presence is asked


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
