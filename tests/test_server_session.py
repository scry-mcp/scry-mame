"""The server's guarantees: the session: start, close, boot, the window helper and the paths."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from array import array
from pathlib import Path
from typing import Any

import pytest
from scry_core import presence as presence_mod
from scry_core import progress as mprogress  # noqa: E402
from scry_core import window as core_window
from scry_core import window_size
from server_support import (  # noqa: E402
    MACHINE_INDEPENDENT,
    _AlreadyDead,
    _boot_against,
    _boot_args,
    _boot_judged,
    _ClosedPresence,
    _closing,
    _console,
    _ConsoleSession,
    _CrashedProcess,
    _DroppingWire,
    _ExitingProcess,
    _FakeSession,
    _install,
    _never_spawns,
    _query_that_outlives_the_boot,
    _RecordingSession,
    _RegisterSession,
    _running,
    _stub_boot,
    _StubProcess,
    _UnreapableProcess,
)
from session_doubles import (  # noqa: E402
    fake_mame,  # noqa: E402
    prints_file,
    refused,
    rewrite_mame,
    use_table,  # noqa: E402
)

from scry_mame import declarations as dec  # noqa: E402
from scry_mame import (
    files,  # noqa: E402
    inputs,
    launch,
    machine,  # noqa: E402
    read,  # noqa: E402
)
from scry_mame import gdb_session as g  # noqa: E402
from scry_mame import mcp as mame_mcp  # noqa: E402
from scry_mame import scan as mscan  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import session as msession
from scry_mame import state as mstate  # noqa: E402
from scry_mame import stub_owner as owner  # noqa: E402
from scry_mame import write as mwrite  # noqa: E402

UNWATCHED = ["-window", "-nomaximize", "-resolution", "320x240", "-nothrottle"]


ASKED = core_window.WindowRequest(0, False, (0, 0), usable=(0, 0, 1920, 1080))


@pytest.mark.parametrize("screens, flags", [
    # The largest whole multiple whose window, title bar included, fits a 1080p usable area.
    ([{"tag": ":screen", "width": 320, "height": 240}],
     ["-window", "-nomaximize", "-resolution", "1280x960"]),
    ([{"tag": ":screen", "width": 256, "height": 224}],
     ["-window", "-nomaximize", "-resolution", "1024x896"]),
    ([{"tag": ":screen", "width": 640, "height": 480}],
     ["-window", "-nomaximize", "-resolution", "1280x960"]),
    ([{"tag": ":screen", "width": 864, "height": 224}],
     ["-window", "-nomaximize", "-resolution", "1728x448"]),
    # A vertical board's window is as tall as its rotated screen.
    ([{"tag": ":screen", "width": 256, "height": 224, "rotation": 90}],
     ["-window", "-nomaximize", "-resolution", "896x1024"]),
    ([{"tag": ":screen", "width": 2000, "height": 1200}],
     ["-window", "-nomaximize", "-resolution", "2000x1200"]),
    # No size `-listxml` could give: MAME sizes the window itself.
    ([], ["-window", "-nomaximize"]),
    ([{"tag": ":screen"}], ["-window", "-nomaximize"]),
    ([{"tag": ":screen", "width": 0, "height": 240}], ["-window", "-nomaximize"]),
    ([{"tag": ":screen", "width": 320, "height": 0}], ["-window", "-nomaximize"]),
])
def test_a_watched_window_is_scaled_from_the_machine_s_screen_and_named_a_display(
    screens: list[dict[str, Any]], flags: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    assert launch.window_flags(ASKED, screens) == [*flags, "-screen0", "screen0"]


def test_an_unwatched_window_is_small_and_flat_out() -> None:
    assert launch.window_flags(None, [{"tag": ":screen", "width": 320, "height": 240}]) \
        == UNWATCHED


@pytest.mark.parametrize(("asked", "flags"), [
    (core_window.WindowRequest(1, False, (1920, 0)), ["-screen0", "screen1"]),
    (core_window.WindowRequest(1, True, (1920, 0)), ["-nowindow", "-screen0", "screen1"]),
    (core_window.WindowRequest(0, True, (0, 0)), ["-nowindow", "-screen0", "screen0"]),
])
def test_the_display_asked_is_the_one_mame_is_told_and_fullscreen_drops_the_window(
    asked: core_window.WindowRequest, flags: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    got = launch.window_flags(asked, [])
    assert got[-len(flags):] == flags, got
    assert ("-window" in got) is not asked.fullscreen, got


def test_the_tools_are_serialized() -> None:
    """Two calls at once over ONE machine steal each other's breakpoint stops."""
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


def test_the_spawn_sentinel_can_fire(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The red control for every `_never_spawns` case above."""
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


def test_start_checks_the_image_at_its_base_and_reports_the_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The happy path of `start`, which no test read before."""
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
    assert list(dead)[0] == "summary" and dead["summary"] == "status: no session"


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
        assert "timing" not in debugger["note"] and "autoboot" in debugger["note"]
        assert s.status()["debugger"] == debugger, "one fact, one shape, in both replies"
    finally:
        s.close()
    assert "debugger" not in s.status(), "no machine, nothing attached"


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


def test_a_reader_too_long_to_send_leaves_an_open_run_window_alone(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A refusal belongs to its own command."""
    ses = g.Session(timeout=0.2)
    ses._sock = _DroppingWire()  # type: ignore[assignment]
    ses.packet_size = 0x40
    _install(monkeypatch, ses, tmp_path)
    window = {"emulated": 1.0, "wall": 2.0}
    monkeypatch.setattr(mstate.STATE, "run_release", window)
    assert s.debug("print " + "1" * 40)["code"] == "bad_argument"
    assert mstate.STATE.run_release is window




def test_the_command_line_carries_the_mark_and_its_directories(tmp_path: Path) -> None:
    """A repo's own `make stop` kills by binary path."""
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


def test_a_taken_port_is_refused_before_the_emulator_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A caller who names a port names it for a reason."""
    import socket as _s

    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    with _s.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        held = holder.getsockname()[1]
        refused(re.escape(str(held)),
        s.start(
            binary=str(binary), system="none", rompath=str(tmp_path),
            reference_rom=str(rom), stub_port=held,
        ))


def test_a_given_port_and_the_pid_are_used_and_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`start` and `status` say which process and which port this session is."""
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
        assert st["scratch_dir"] == out["scratch_dir"]
        assert st["state_dir"] == out["state_dir"] == out["scratch_dir"]
    finally:
        s.close()


def test_a_shared_start_sizes_the_window_from_the_listed_screen_and_names_the_display(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """At the level of `start`: the screen `-listxml` lists and the display asked reach the argv."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    xml = Path(__file__).parent / "fixtures" / "machine" / "listxml-m68k-dual.xml"
    rewrite_mame(args["binary"], prints_file(xml))
    out = s.start(**{**args, "system": "m68k-dual"}, shared=True, display=1)
    try:
        argv = _StubProcess.last_argv
        shown = core_window.host().displays()[1]
        fitted = window_size.integer_fit((336, 252), shown.work, shown.scale, sys.platform)
        assert argv[argv.index("-resolution") + 1] == "x".join(map(str, fitted))
        assert out["flags"][-2:] == ["-screen0", "screen1"], out["flags"]
        assert out["window"]["display"] == 1 and out["window"]["onscreen"] is True, out
    finally:
        s.close()


@pytest.mark.parametrize("port", [-1, 65536, 70000])
def test_a_port_outside_the_tcp_range_is_refused_not_overflowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, port: int
) -> None:
    """`socket.bind` answers OverflowError for these."""
    _never_spawns(monkeypatch, tmp_path)
    binary = fake_mame(tmp_path)
    rom = tmp_path / "ref.bin"
    rom.write_bytes(bytes(64))
    refused("port",
    s.start(
        binary=str(binary), system="none", rompath=str(tmp_path), reference_rom=str(rom),
        stub_port=port,
    ))


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
    assert closed["session"] == {"alive": False, "running": False, "altered": False}, closed


def test_close_reports_the_session_as_it_is_after_closing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _closing(monkeypatch, tmp_path, exits=False)
    mstate.STATE.console_writes = 3
    closed = s.close()
    assert closed["closed"] is True
    assert closed["session"]["alive"] is False and closed["session"]["running"] is False, closed


def test_a_quit_that_exits_nonzero_keeps_the_last_words_unasked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The crash on the way out MAME's Lua collector is known for."""
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


def test_close_carries_the_tail_of_each_log_before_the_scratch_goes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`close` deletes the scratch, and with it the only record of what MAME printed last."""
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


def test_close_asks_mame_to_quit_before_it_kills() -> None:
    """MAME writes `cfg/` and `nvram/` on a CLEAN exit and ignores SIGTERM."""
    ses = _RecordingSession(quit_raises=True)
    proc = _ExitingProcess(ses.events, exits=True)
    mstate.STATE.ses, mstate.STATE.proc = ses, proc  # type: ignore[assignment]
    closed = s.close()
    assert closed["closed"] is True and closed["session"]["alive"] is False, "as it is AFTER"
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
    """`quit` is guarded and the scratch's removal ignores errors."""

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
    """`closed."""
    mstate.STATE.ses = mstate.STATE.proc = None
    closed = s.close()
    assert closed["closed"] is False and closed["ended_by"] == "none"
    assert "no session" in closed["note"]
    assert closed["summary"] == "close: no session"


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


def test_start_passes_log_and_reports_both_channels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`logerror`, the channel the repos' tracers read, went NOWHERE."""
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


def test_find_sends_a_long_range_in_windows_and_merges_their_hits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`FIND_WINDOW`, whose comment says why."""
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


def test_every_reply_opens_with_a_summary_and_closes_with_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The line the client paints is the tool's name, its arguments and its reply."""
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


@pytest.mark.parametrize("name", sorted(MACHINE_INDEPENDENT))
def test_an_argument_the_machine_cannot_judge_is_refused_with_no_machine(name: str) -> None:
    """THE RULE IS THE PROPERTY, NOT THE ARGUMENT'S NAME."""
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


def test_status_with_no_session_keeps_no_stop_of_the_one_that_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mstate.STATE, "last_stop", {"seq": 3, "pc": "0x10"})
    mstate.STATE._reset()
    out = s.status()
    assert out["last_stop"] == {"available": False, "why": mstate.NO_STOP_YET_WHY}, out


def test_status_on_a_machine_that_died_under_its_session_names_the_exit_and_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Not the bare `alive."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "proc", _CrashedProcess())
    out = s.status()
    assert (out["status"] == "ok" and out["session"]["alive"] is False
            and out["exit_code"] == -11), out
    assert "`close` collects the exit code" in out["note"], out


def test_status_of_a_machine_that_exited_carries_the_stop_it_last_made(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "proc", _CrashedProcess())
    monkeypatch.setattr(mstate.STATE, "last_stop", {
        "seq": 3, "pc": "0x10", "frame": 7, "cause": "breakpoint", "when": time.monotonic(),
        "wall_at": "2026-10-31T00:00:00Z"})
    assert s.status()["last_stop"]["stop_seq"] == 3




def test_start_reports_the_env_and_the_flags_it_handed_over(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A watched run has to say which variant it is."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    out = s.start(**_boot_args(tmp_path, image), shared=True, env={"M68K_DUAL_SWITCH": "on"})
    try:
        assert out.get("env", {}) == {"M68K_DUAL_SWITCH": "on"} and "display" not in out
        assert out["flags"] == ["-window", "-nomaximize", "-screen0", "screen0"]
        assert out.get("throttle_from_frame", 0) == 0
        assert _StubProcess.last_kwargs.get("env", {})["M68K_DUAL_SWITCH"] == "on"
        assert Path(out["boot_lua_path"]).parent == mstate.STATE.scratch, (
            "the server writes the one boot script on every start, for the inventory")
        assert isinstance(out["frame"], int) or out["frame"]["available"] is False
    finally:
        s.close()
    out = s.start(**_boot_args(tmp_path, image))
    try:
        assert "env" not in out, "a quick run was given no environment"
    finally:
        s.close()


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
    """Two spellings of one switch let the reply name one while the process obeys the other."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    _never_spawns(monkeypatch, tmp_path)
    out = refused("background=True", s.start(**_boot_args(tmp_path, image),
                                             env={"SDL_MAC_BACKGROUND_APP": value},
                                             background=background))
    assert out["code"] == "bad_argument" and "SDL_MAC_BACKGROUND_APP" in out["message"]
    assert mstate.STATE.proc is None and mstate.STATE.scratch is None, (
        "a start that did not start owns nothing")


def test_when_the_boot_fails_the_query_holds_the_cause_and_it_outranks_the_symptom(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The query is put before the boot and collected after the park."""
    image = bytes(range(64))
    args = _boot_args(tmp_path, image)
    rewrite_mame(args["binary"], "if '-listxml' in sys.argv:\n"
                 "    sys.stderr.write(f\"No matching machines found for '{sys.argv[1]}'\\n\")\n"
                 "    sys.exit(5)")
    out = refused("does not carry",
                  s.start(**{**args, "system": "notthisone", "boot_seconds": 0.6}))
    assert "No matching machines found for 'notthisone'" in out["message"]
    assert "gdbstub did not answer" not in out["message"], (
        "the symptom won: the caller is told the stub is silent and not that they named a "
        "system this build has never heard of")
    assert mstate.STATE.ses is None and mstate.STATE.scratch is None


def test_a_start_that_did_not_start_leaves_no_query_running_behind_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A start owns nothing when it fails, and that includes the process it asked a question of."""
    args, held = _query_that_outlives_the_boot(monkeypatch, tmp_path)
    out = s.start(**{**args, "boot_seconds": 0.4})
    assert out["status"] == "INVALID", out
    proc = held[0][0]
    assert proc is not None
    assert proc.poll() is not None, "the query is still running after a start that failed"


def test_a_boot_that_raises_anything_but_a_refusal_reaps_the_query_and_the_error_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard above collects the query on a REFUSAL."""
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
    """The `symbols` mapping path waits for the query in `judge`."""
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


def test_start_says_the_shape_of_the_board_on_its_summary_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The client paints a tool's name, its arguments and its reply and nothing else."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    xml = Path(__file__).parent / "fixtures" / "machine" / "listxml-m68k-dual.xml"
    rewrite_mame(args["binary"], prints_file(xml))
    out = s.start(**{**args, "system": "m68k-dual"})
    try:
        assert out["machine"]["cpus"] == 2 and out["machine"]["rom_files"] == 22
        assert "machine: 2 cpus" in out["summary"], out["summary"]
        assert "22 ROM files" in out["summary"], out["summary"]
    finally:
        s.close()


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


def test_a_refusal_that_never_reached_the_machine_reports_nothing_about_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """THE MIRROR OF THE CASE ABOVE, and it is new because the boundary is."""
    ses = _running(monkeypatch, tmp_path)
    s.resume()
    ses.stops_after_polls = 1                        # a breakpoint fired meanwhile
    out = s.write(ref="0x0", data_hex="zz")
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "stopped_on_its_own" not in out, (
        "a refusal that never asked the machine anything reported a stop it could not have seen")
    later = s.registers()
    assert later["stopped_on_its_own"]["stop_seq"] == 2, (
        "the stop was lost: the next call to make contact owes the account")


def test_kill_clears_every_field_of_the_session_it_ends() -> None:
    """Deleting one reset line from `kill` left the suite green."""
    ses = _RecordingSession()
    proc = _ExitingProcess(ses.events, exits=True)
    mstate.STATE.ses, mstate.STATE.proc = ses, proc  # type: ignore[assignment]
    fd, tmp_log = tempfile.mkstemp()
    os.close(fd)                        # Windows removes no file a descriptor still holds
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
        "scratch": Path(tempfile.mkdtemp(prefix="mame-mcp-kill-test-")), "named_state_dir": "/x",
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
        "window": core_window.WindowRequest(1, True, (1920, 0)),
        "background": True,
        "manifest": "the old session's manifest",
        "evidence": {"locates": [{"n": 1}], "sweeps": [], "choices": []},
        "stdout_log": open(tmp_log, "wb"),  # noqa: SIM115 (kill closes it)
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


def test_start_refuses_while_a_session_is_live(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`start` must not kill whatever was live and boot again in silence."""
    ses = _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "m68k-dual")
    e = refused("live",
    s.start(**_boot_args(tmp_path, b"\0" * 32)))
    assert "m68k-dual" in e["message"] and "4242" in e["message"] and "`close`" in e["message"]
    assert mstate.STATE.ses is ses, "the live session was left alone"  # type: ignore[comparison-overlap]


def test_close_reports_a_process_that_had_already_died_and_the_session_as_it_was() -> None:
    """Two things `close` said wrong."""
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _AlreadyDead()  # type: ignore[assignment]
    mstate.STATE.console_writes = 3
    mstate.STATE.console_thread_errors = 2
    mstate.STATE.console_reruns_seen = 1
    mstate.STATE.console_lines_lost = 1
    closed = s.close()
    assert closed["closed"] is True and closed["ended_by"] == "died" and closed["exit_code"] == -11
    assert ses.events == ["close"], "no quit is sent to a process that is gone"
    assert closed["session"] == {"alive": False, "running": False, "altered": False,
                                 "console": {"thread_errors": 2, "reruns": 1, "lost": 1}}
    assert closed["summary"] == "close: the emulator had already exited, exit code -11"
    assert mstate.STATE.console_writes == 0
    ses2 = _RecordingSession(quit_raises=True)
    proc = _ExitingProcess(ses2.events, exits=True)
    mstate.STATE.ses, mstate.STATE.proc = ses2, proc  # type: ignore[assignment]
    ses2.writes = 1
    closed = s.close()
    assert closed["ended_by"] == "quit" and closed["session"]["alive"] is False
    assert closed["session"]["altered"] is False


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
    from scry_mame import binary as mame_binary
    monkeypatch.setattr(mame_binary, "resolve", lambda b: SimpleNamespace(path=b,
                                                                          origin="argument"))
    monkeypatch.setattr(mstate.STATE, "ses", None)
    for asked in (True, False):
        with pytest.raises(Stop):
            launch.start("mame", "sys", "/r", "/r/x.bin", "", "0x0", "", 1.0, False, "", None,
                         None, "0x0", 0, "", presence=asked)
    assert seen == [True, False]


def test_boot_names_a_gdbstub_that_never_answers_within_its_wait(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The connect loop keeps trying until `wait` runs out and then names the last refusal."""
    refusal = _boot_against(monkeypatch, tmp_path, exit_code=None, wait=0.05)
    assert "did not answer within 0.05 s: connection refused" in str(refusal), refusal


def test_boot_connects_the_stub_on_the_judged_port_and_names_a_zero_wait_honestly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two things the connect loop must get right that no case held."""

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

    judged = _boot_judged(monkeypatch, tmp_path, Refusing, Spawned, port=23999, wait=0.05,
                          presence=False)
    with pytest.raises(mstate.Invalid) as e:
        launch.boot(judged)
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
        launch.boot(judged)
    assert "did not answer within 0" in str(e.value) and "exited" not in str(e.value)
    assert e.value.fields["exit_code"]["available"] is False


def test_start_records_for_the_later_tools_everything_it_judged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """What `start` writes into STATE for the tools that come after it, held field by field."""
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


def test_close_reports_the_console_pipe_as_it_found_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Three shapes of the drain's account."""
    from scry_mame import transport

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
    from scry_mame import transport

    scratch = tmp_path / f"{launch.SCRATCH_PREFIX}unread"
    scratch.mkdir()
    (scratch / "stdout.log").write_bytes(b"boot\n")
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    mstate.STATE.scratch = scratch
    monkeypatch.setattr(transport, "drain", lambda ses_, scratch_: (0, 0))
    closed = s.close()
    assert "console" not in closed["session"], closed["session"]
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


def test_free_port_takes_the_kernels_choice_and_refuses_when_there_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`free_port` asks the kernel for a port."""
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
    """The real kernel."""
    port = launch.free_port()
    assert port != 23946 and launch.port_is_free(port), port


def test_the_top_of_the_tcp_range_is_a_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """65535 is the last port and was refused as if it were one past it."""
    monkeypatch.setattr(launch, "port_is_free", lambda p: True)
    args = _boot_args(tmp_path, bytes(16))
    judged = launch.judge(**args, symbols="", reference_addr="0x0", inipath="", wait=1.0,
                          shared=False, boot_lua="", env=None, bases=None, reference_base="0x0",
                          port=65535, state_dir="", throttle_from_frame=0,
                          background=None)
    machine.listxml(judged.listxml, judged.binary, judged.system, judged.wait)
    assert judged.port == 65535


def test_judge_refuses_a_view_that_would_read_as_an_option(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The refusals of the caller's input are `judge`'s, whoever calls it."""
    monkeypatch.setattr(launch, "port_is_free", lambda p: True)
    args = _boot_args(tmp_path, bytes(16))
    with pytest.raises(mstate.Invalid, match="view='-video' starts with `-`"):
        launch.judge(**args, symbols="", reference_addr="0x0", inipath="", wait=1.0,
                     shared=False, boot_lua="", env=None, bases=None, reference_base="0x0",
                     port=65535, state_dir="", throttle_from_frame=0, background=None,
                     view="-video")


def test_check_ref_refuses_a_value_that_is_not_a_string_in_the_envelope() -> None:
    with pytest.raises(mstate.Invalid) as e:
        inputs.check_ref(5)
    assert e.value.code == "bad_argument" and "not a string" in str(e.value)


def test_wait_exit_polls_the_process_at_the_exit_poll_and_never_for_ever() -> None:
    import subprocess

    seen: list[float | None] = []

    class Stuck:
        def wait(self, timeout: float | None = None) -> int:
            seen.append(timeout)
            raise subprocess.TimeoutExpired("mame", timeout or 0)

    assert mstate.wait_exit(Stuck(), 0.05, mprogress.no_progress, "x") is None  # type: ignore[arg-type]
    assert seen and all(t == mstate.EXIT_POLL_S for t in seen), seen


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


def test_a_port_not_written_0x_is_refused_naming_its_argument() -> None:
    out = refused(r"^ref='6' must be a port", s.watch_add(ref="6", mode="count", length=2,
                                                           space="io"))
    assert out["code"] == "bad_argument" and "0x6" in out["message"], out
    out = refused(r"^trigger='beam' must be a port",
                  s.watch_add(ref="0x2031fc", mode="capture", length=4, trigger="beam",
                              space="io"))


def test_a_media_file_tool_answers_in_this_server_s_envelope(tmp_path: Path) -> None:
    """The file tools' bodies are scry-core's and answer bare fields."""
    from scry_core import png
    pic = tmp_path / "a.png"
    pic.write_bytes(png.encode(png.Raster(2, 2, bytes(12))))
    r = s.image_compare("image", a=str(pic), b=str(pic))
    assert r["status"] == "ok" and "session" in r, r
    assert r["summary"].startswith("image_compare image: no pixel differs"), r["summary"]


@pytest.mark.skipif(sys.platform == "win32",
                    reason="behind a `.cmd`, the double's own pid is not the one launched")
def test_a_live_runs_ledger_learns_every_mame_launched_a_start_that_fails_included(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The run's proof that no emulator outlived it reads this ledger."""
    from scry_core import live_host

    pid_file = tmp_path / "pid"
    binary = fake_mame(tmp_path)
    rewrite_mame(str(binary), "if '-listxml' in sys.argv or '-version' in sys.argv:\n"
                 "    sys.exit(0)\n"
                 f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))")
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
    args = _boot_args(tmp_path, bytes(16))
    judged = launch.judge(**args, symbols="", reference_addr="0x0", inipath="", wait=1.0,
                          shared=False, boot_lua="", env=None, bases=None, reference_base="0x0",
                          port=0, state_dir="", throttle_from_frame=0,
                          background=None, presence=asked)
    machine.listxml(judged.listxml, judged.binary, judged.system, judged.wait)
    assert judged.presence is asked


SCREEN_320 = [{"tag": ":screen", "width": 320, "height": 240}]


@pytest.mark.parametrize(("size", "screens", "said"), [
    ((640, 960), SCREEN_320, True),                                          # unequal factors
    ((1280, 960), SCREEN_320, False),                                        # 4 and 4
    ((448, 512), [{"tag": ":screen", "width": 256, "height": 224, "rotation": 90}], False),
    ((744, 768), [{"tag": ":screen", "width": 256, "height": 224}], True),
    ((744, 768), [], False),                                                 # nothing to compare
])
def test_a_stated_size_that_is_not_a_whole_multiple_of_the_screen_is_said(
        size: tuple[int, int], screens: list[dict[str, Any]], said: bool) -> None:
    asked = core_window.WindowRequest(0, False, (0, 0), size=size)
    got = launch.scaled_note(asked, screens)
    assert (got is not None) is said, got
    assert said is False or "whole multiple" in str(got)


def test_a_size_the_server_chose_is_never_called_scaled() -> None:
    chosen = core_window.WindowRequest(0, False, (0, 0), size=(700, 700), fitted=True)
    assert launch.scaled_note(chosen, SCREEN_320) is None


def test_the_fit_is_held_by_the_request_as_the_server_s_own_and_judged_by_none(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    got = launch.fitted_request(ASKED, SCREEN_320)
    assert got is not None and got.size == (1280, 960) and got.fitted is True
    assert launch.fitted_request(got, SCREEN_320) == got, "fitting twice changes nothing"


@pytest.mark.parametrize(("platform", "kept"), [("darwin", True), ("win32", False)])
def test_the_fit_drops_nomaximize_on_windows_where_it_would_be_ignored(
        monkeypatch: pytest.MonkeyPatch, platform: str, kept: bool) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    flags = launch.window_flags(ASKED, SCREEN_320)
    assert ("-nomaximize" in flags) is kept, flags
