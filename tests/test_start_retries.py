"""`start` relaunches a MAME that died BY A SIGNAL before its gdbstub answered, other than an
assertion's abort or a stub with no description of the first cpu, a live stub that answered
without being ready, and, when the port was its own pick, a gdbstub port another process took;
nothing else (the why is `REFERENCE.md`, *The session*).

THE DOUBLES ARE REAL PROCESSES. Death by a signal is a property of the process, so the
emulator here is a shell script that sends SIGSEGV to itself, and `Popen` hands back its real
negative return code; an authored reply could not tell a signal from an exit code. Only the
gdbstub's side is stubbed, and it answers exactly when the script says it booted.

A side effect worth knowing: macOS writes a crash report for each self-SIGSEGV (`sh-*.ips` or
`bash-*.ips` under `~/Library/Logs/DiagnosticReports`), which is the cost of a double that
dies the way MAME does.
"""

import json
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_gdb_session import _Wire  # noqa: E402
from test_server import BANNER_LINE, _ExitingProcess, _RecordingSession, _stub_boot  # noqa: E402

import gdb_session as gs  # noqa: E402
import mame_boot_failures as failures  # noqa: E402
import mame_files as files  # noqa: E402
import mame_launch as launch  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_stub_owner as owner  # noqa: E402
import server as s  # noqa: E402

# The class itself, kept before `_stub_boot` replaces the module's name with its double.
REAL_SESSION = gs.Session
ABORTED = -signal.SIGABRT

IMAGE = bytes(range(256)) * 64

# The emulator double. `-listxml` is the query `start` asks before it boots, and answers no XML;
# `-version` answers one line, as a MAME does;
# the boot itself counts its launches in a file, dies by SIGSEGV while the count is at or below
# DEATHS (after LATE seconds, when set), and otherwise marks itself booted (the gdbstub double
# answers from then on) and stays alive the way a parked MAME does. EXIT, when set, is a plain
# exit code instead of a death; HANG keeps it alive and never booted; ABORT prints its line and
# dies by SIGABRT, the way a failed `assert` ends a debug MAME; FATAL prints its line and dies by
# SIGSEGV, the way a stock MAME ends when its stub has no description of the first cpu. A booted
# double prints the debugger's banner as MAME does, BANNER_AFTER seconds after it can be dialled,
# or never when that is None. While the count is at or below LOST it ends the way a MAME whose
# gdbstub port was taken under it does: MAME's fatal line naming the port it was given, exit 3.
DOUBLE = """#!/bin/sh
case " $* " in *" -listxml "*) exit 0 ;; *" -version "*) echo "0.0 (double)"; exit 0 ;; esac
here=$(dirname "$0")
rm -f "$here/booted"
n=$(( $(cat "$here/launches" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$here/launches"
echo "launch $n"
[ -n "%(exit)s" ] && exit %(exit)s
if [ "$n" -le %(lost)d ]; then
  port=; prev=; for a in "$@"; do [ "$prev" = "-debugger_port" ] && port=$a; prev=$a; done
  echo "Fatal error: gdbstub: failed to start listening on address localhost port $port" >&2
  exit 3
fi
[ -n "%(hang)s" ] && exec sleep 60
[ -n "%(abort)s" ] && { echo "%(abort)s"; kill -ABRT $$; }
[ -n "%(fatal)s" ] && { echo "Ignoring MAME exception: %(fatal)s"
                       echo "Fatal error: %(fatal)s" >&2; kill -SEGV $$; }
if [ "$n" -le %(deaths)d ]; then sleep %(late)s; kill -SEGV $$; fi
touch "$here/booted"
%(banner)s
exec sleep 60
"""


def _double(tmp_path: Path, deaths: int = 0, exit_code: str = "", hang: bool = False,
            late: float = 0, abort: str = "", fatal: str = "",
            banner_after: float | None = 0, lost: int = 0) -> Path:
    binary = tmp_path / "segv-mame"
    binary.write_text(DOUBLE % {"deaths": deaths, "exit": exit_code, "hang": "y" if hang else "",
                                "late": late, "abort": abort, "fatal": fatal, "lost": lost,
                                "banner": "" if banner_after is None else
                                f"sleep {banner_after}; printf '%s' '{BANNER_LINE}'"})
    binary.chmod(0o755)
    console = tmp_path / "plugins" / "console"
    console.mkdir(parents=True, exist_ok=True)
    (console / "init.lua").write_text("-- the console plugin's place, not its code\n")
    return binary


def _start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, binary: Path,
           wait: float = 10.0, real_grace: bool = False,
           handshake: Callable[..., None] | None = None,
           dial: Callable[[], None] | None = None, request_s: float | None = None,
           **start_kw: Any) -> dict[str, Any]:
    ses = _stub_boot(monkeypatch, tmp_path, IMAGE, 0)
    if request_s is not None:
        ses.timeout = request_s

    def booted() -> None:
        if not (tmp_path / "booted").exists():
            raise OSError("connection refused")

    ses.dial = dial or booted  # type: ignore[method-assign]
    if handshake is not None:
        ses.handshake = handshake  # type: ignore[method-assign]
    # The double never answers `quit`, so `close` would wait out the whole grace period before
    # its SIGKILL; that wait is `kill`'s own contract and not what these cases measure, except
    # where `real_grace` asks for it.
    if not real_grace:
        monkeypatch.setattr(mstate, "QUIT_GRACE_S", 0.2)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(IMAGE)
    out: dict[str, Any] = s.start(binary=str(binary), system="m68k", rompath=str(tmp_path),
                                  reference_rom=str(rom), seconds=wait, **start_kw)
    return out


def _launches(tmp_path: Path) -> int:
    return int((tmp_path / "launches").read_text())


@pytest.mark.parametrize("deaths", [1, launch.START_RETRIES_MAX])
def test_a_signal_death_before_the_stub_is_relaunched_and_the_death_is_in_the_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, deaths: int
) -> None:
    """(a) SIGSEGV, then a boot that answers, up to the last retry the cap allows: the session
    starts, and each death rides on the reply with its own last words, because its scratch is
    gone by then. A second `start` over it is refused as live, and says `start_retries` too."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, deaths=deaths))
    try:
        assert out["status"] == "ok", out
        assert _launches(tmp_path) == deaths + 1
        assert [d["exit_code"] for d in out["start_retries"]] == [-11] * deaths, out
        for n, death in enumerate(out["start_retries"], 1):
            assert death["kind"] == "died", death
            assert isinstance(death["after_s"], float) and death["after_s"] >= 0, death
            assert f"launch {n}" in death["stdout_tail"], death
        said = "1 relaunch" if deaths == 1 else f"{deaths} relaunches"
        assert out["summary"].endswith(f"after {said}"), out["summary"]
        assert list(out)[-1] == "session", "`session` stays the last key"
        again = s.start(binary="/x/mame", system="m68k", rompath="/x", reference_rom="/x/rom")
        assert again["code"] == "session_live" and again["start_retries"] == [], again
    finally:
        s.close()


def test_a_signal_death_every_time_is_refused_after_the_cap_with_every_death_in_the_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """(b) A MAME that always dies: three launches, the cap's two retries recorded, and the
    last death is the refusal itself, in its own `exit_code` and `stdout_tail`."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, deaths=99))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert _launches(tmp_path) == 1 + launch.START_RETRIES_MAX == 3
    assert [d["exit_code"] for d in out["start_retries"]] == [-11, -11], out["start_retries"]
    assert ["launch 1" in out["start_retries"][0]["stdout_tail"],
            "launch 2" in out["start_retries"][1]["stdout_tail"]] == [True, True]
    assert out["exit_code"] == -11 and "launch 3" in out["stdout_tail"], out
    assert out["session"]["alive"] is False, "the failed start owns nothing"


# What a stock MAME prints, captured live on alienar, when its gdbstub has no description of the
# board's first cpu: this on stdout after "Ignoring MAME exception: " and on stderr after
# "Fatal error: ", then a death by SIGSEGV.
NOT_SERVED = "gdbstub: cpuname mc6809e not found in gdb stub descriptions"


def test_a_first_cpu_the_stub_cannot_serve_is_refused_at_once_naming_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The stub says which cpu it cannot describe and the process dies by a signal: launching
    it again would meet the same cpu, so `start` refuses at once, as `no_channel`, naming the
    cpu and quoting MAME's own line."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, fatal=NOT_SERVED))
    assert out["status"] == "INVALID" and out["code"] == "no_channel", out
    assert _launches(tmp_path) == 1 and out["start_retries"] == [], out
    assert f"`Fatal error: {NOT_SERVED}`" in out["message"], out["message"]
    assert "the first cpu, mc6809e," in out["message"], out["message"]
    assert "patches/0004-gdbstub-one-thread-per-cpu.patch" in out["message"], "the way out"
    assert out["exit_code"] == -11 and isinstance(out["after_s"], float), out
    assert out["session"]["alive"] is False, "the failed start owns nothing"


@pytest.mark.parametrize(("tail", "code"), [
    # the stderr line glued behind a console prompt that stdout left without its newline
    ("\x1b[1;36m[MAME]\x1b[0m> Fatal error: gdbstub: cpuname mc6809e not found in gdb stub "
     "descriptions\n", -11),
    # a build whose fatal error exits instead of raising a signal: the same cause
    (f"Fatal error: {NOT_SERVED}\n", 2),
])
def test_the_unserved_cpu_is_read_wherever_its_line_lands_and_however_mame_ends(
    tail: str, code: int,
) -> None:
    refusal = failures.death_refusal(code, 1.5, tail)
    assert refusal.code == "no_channel" and "mc6809e" in str(refusal), refusal


@pytest.mark.parametrize("tail", [
    # the patched stub's line, which serves no registers for that cpu and does not die
    "gdbstub: cpuname mc6809e (:maincpu) not found in gdb stub descriptions, so its registers "
    "are not served\n",
    # stdout's half alone names the exception it ignored, never the fatal error
    f"Ignoring MAME exception: {NOT_SERVED}\n",
])
def test_a_death_without_the_fatal_line_stays_a_death(tail: str) -> None:
    refusal = failures.death_refusal(-11, 1.5, tail)
    assert isinstance(refusal, failures.DiedBeforeStub) and refusal.relaunch(True), refusal


def test_a_handshake_cut_by_the_unserved_cpus_death_is_refused_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The stub accepted the dial, and MAME died at its first stop while the handshake waited:
    the same refusal as a death before the dial, read from the same line."""
    def dial() -> None:
        while not (tmp_path / "launches").exists():
            time.sleep(0.01)

    def handshake(timeout: float | None = None) -> None:
        while mstate.STATE.proc is not None and mstate.STATE.proc.poll() is None:
            time.sleep(0.01)
        raise gs.ConnectionFailed("the stub closed the connection")

    began = time.monotonic()
    out = _start(monkeypatch, tmp_path, _double(tmp_path, fatal=NOT_SERVED), dial=dial,
                 handshake=handshake, request_s=1.0)
    assert time.monotonic() - began < 5.0, "a death ends the wait for the banner at once"
    assert out["code"] == "no_channel" and out["start_retries"] == [], out
    assert _launches(tmp_path) == 1, out


@pytest.mark.parametrize("lost", [1, launch.START_RETRIES_MAX])
def test_a_port_taken_before_mame_bound_it_is_relaunched_on_a_fresh_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lost: int
) -> None:
    """A port picked free and taken by another process before MAME listened on it: MAME says so
    and exits 3, which is not the caller's input being refused, so the launch is made again on a
    port picked afresh, and each lost launch rides on the reply with MAME's own line."""
    picked = iter(range(41001, 41001 + launch.START_RETRIES_MAX + 1))
    monkeypatch.setattr(launch, "free_port", lambda: next(picked))
    out = _start(monkeypatch, tmp_path, _double(tmp_path, lost=lost))
    try:
        assert out["status"] == "ok", out
        assert _launches(tmp_path) == lost + 1
        assert [d["exit_code"] for d in out["start_retries"]] == [3] * lost, out
        for n, retry in enumerate(out["start_retries"]):
            assert f"failed to start listening on address localhost port {41001 + n}" in \
                retry["stdout_tail"], retry
    finally:
        s.close()


def test_a_port_lost_on_every_launch_is_refused_after_the_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Lost on every launch, the relaunches stop at the cap like any other, and the last loss
    is the refusal, MAME's own line in its tail."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, lost=launch.START_RETRIES_MAX + 1))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert out["exit_code"] == 3, out
    assert _launches(tmp_path) == launch.START_RETRIES_MAX + 1
    assert len(out["start_retries"]) == launch.START_RETRIES_MAX, out
    assert "failed to start listening" in out["stdout_tail"], out


def test_a_port_the_caller_named_is_never_relaunched_on_another(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The caller's `stub_port` is the caller's: a session on a port they did not ask for would
    leave their other client talking to nothing, so a lost race on it is refused at once."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, lost=1), stub_port=launch.free_port())
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert _launches(tmp_path) == 1
    assert out["start_retries"] == [], out


@pytest.mark.parametrize("code", [2, 0, 3])
def test_an_exit_code_before_the_stub_is_never_relaunched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int
) -> None:
    """(c) An exit code is MAME refusing something the caller gave it (missing ROMs, a bad
    flag): launching it again would answer the same, so it is refused at once. Zero is the
    boundary: an exit, not a signal; 3 is the code a port taken under MAME exits with, refused
    here because MAME did not say its port was taken."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, exit_code=str(code)))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert _launches(tmp_path) == 1
    assert out["start_retries"] == [], out
    assert out["exit_code"] == code, out


def test_a_stub_that_never_answers_from_a_live_process_is_not_relaunched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A MAME still alive at the end of the wait did not die: it is slow or stuck, and a
    relaunch would pay the whole wait again for nothing."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=0.5)
    assert out["code"] == "session_broken" and "did not answer" in out["message"], out
    assert _launches(tmp_path) == 1 and out["start_retries"] == [], out


def test_a_start_that_failed_is_killed_without_the_grace_close_gives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The grace period is how long `close` lets a machine asked to quit write its state. A
    start that failed has no state worth writing and, with no session, nobody asked it to
    quit: with the real grace, its kill still takes well under a second."""
    kills: list[float] = []
    real = mstate.STATE.kill

    def timed(*a: Any, **k: Any) -> dict[str, Any]:
        began = time.monotonic()
        try:
            return real(*a, **k)
        finally:
            kills.append(time.monotonic() - began)

    monkeypatch.setattr(mstate.STATE, "kill", timed)
    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=0.5, real_grace=True)
    assert out["code"] == "session_broken", out
    assert kills and max(kills) < 1.0, kills


def test_a_kill_without_grace_asks_nothing_of_the_session() -> None:
    """A failed start can hold a session (a refusal after the handshake): discarding it neither
    asks MAME to quit nor waits for it, it kills."""
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    ended = mstate.STATE.kill(grace=False)
    assert ended["ended_by"] == "killed" and "quit" not in ses.events, ses.events
    assert ses.events[0] == "kill", ses.events


def test_every_dial_attempt_rides_on_the_refusal_folded_by_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stub that never listened is told from one that listened and refused later only by the
    whole run of attempts, not the last: consecutive identical errors fold into one entry with
    their first and last time from the launch and their count."""
    errors = iter([ConnectionRefusedError(61, "Connection refused")] * 2
                  + [TimeoutError("timed out")]
                  + [ConnectionRefusedError(61, "Connection refused")] * 99)

    def dial() -> None:
        raise next(errors)

    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=1.5, dial=dial)
    assert out["code"] == "session_broken" and "did not answer" in out["message"], out
    got = out["dial_attempts"]
    assert [(a["error"], a["count"] if i < 2 else "n") for i, a in enumerate(got)] == [
        ("ConnectionRefusedError: [Errno 61] Connection refused", 2),
        ("TimeoutError: timed out", 1),
        ("ConnectionRefusedError: [Errno 61] Connection refused", "n")], got
    assert got[2]["count"] >= 1
    times = [t for a in got for t in (a["first_s"], a["last_s"])]
    assert times == sorted(times) and times[0] >= 0 and times[-1] <= 1.5, got


def test_launch_folds_an_attempt_into_the_last_when_its_error_is_the_same() -> None:
    """The fold alone: a new error opens an entry, the same one moves `last_s` and counts."""
    attempts: list[dict[str, Any]] = []
    for at, error in ((0.0, OSError("a")), (0.3, OSError("a")), (0.6, OSError("b"))):
        failures.fold_attempt(attempts, at, error)
    assert attempts == [{"first_s": 0.0, "last_s": 0.3, "count": 2, "error": "OSError: a"},
                        {"first_s": 0.6, "last_s": 0.6, "count": 1, "error": "OSError: b"}]


def test_a_launch_failure_is_relaunched_only_when_its_class_says_so() -> None:
    """The default closes: a failure class that does not say launching again can change the
    answer is refused at once, so a new one cannot be relaunched by omission."""
    failed = failures.LaunchFailed("m", "w", {"kind": "k"})
    assert failed.relaunch(True) is False and failed.relaunch(False) is False
    assert failed.kind == "k"


def test_a_dial_that_failed_on_a_live_process_is_refused_at_once_with_its_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The connection was made and its first byte failed: MAME serves that one connection per
    session, so a second dial would be refused for the rest of the wait. Refused at once, not
    relaunched, with every attempt and the copy of what MAME printed."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    def dial() -> None:
        while not (tmp_path / "launches").exists():  # the double has counted its launch
            time.sleep(0.01)
        raise gs.DialFailed("the connection was made and its first byte failed: reset")

    began = time.monotonic()
    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=5.0, dial=dial)
    assert out["code"] == "session_broken" and time.monotonic() - began < 3.0, out
    assert _launches(tmp_path) == 1 and out["start_retries"] == [], out
    assert [a["error"] for a in out["dial_attempts"]] == [
        "DialFailed: the connection was made and its first byte failed: reset"], out
    assert Path(out["stdout_kept"]).exists() and out["alive"] is True, out


def test_a_dial_that_failed_because_mame_died_is_a_death(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A first byte lost to a reset is what a MAME that is dying does, and its sockets close
    before it can be reaped: the dial that failed while it was still going is a death, and
    relaunched as one, never refused as a dial."""
    first = {"done": False}

    def dial() -> None:
        if not first["done"]:
            while not (tmp_path / "launches").exists():   # the double is running, not dead yet
                time.sleep(0.01)
            first["done"] = True
            raise gs.DialFailed("reset")
        if not (tmp_path / "booted").exists():
            raise OSError("connection refused")

    out = _start(monkeypatch, tmp_path, _double(tmp_path, deaths=1, late=0.3), dial=dial)
    try:
        assert out["status"] == "ok", out
        assert [d["kind"] for d in out["start_retries"]] == ["died"], out
    finally:
        s.close()


def test_a_handshake_cut_because_mame_died_is_a_death(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The same race on the connection the dial made: MAME dying closes it before it can be
    reaped, so the handshake reads a closed channel from a process that is still going. That
    is a death, relaunched as one, never refused as a stub that hung up on a live MAME."""
    first = {"done": False}

    def dial() -> None:
        if not first["done"]:
            while not (tmp_path / "launches").exists():
                time.sleep(0.01)
            return
        if not (tmp_path / "booted").exists():
            raise OSError("connection refused")

    def handshake(timeout: float | None = None) -> None:
        if not first["done"]:
            first["done"] = True
            raise gs.ConnectionFailed("the stub closed the connection")

    out = _start(monkeypatch, tmp_path, _double(tmp_path, deaths=1, late=0.3), dial=dial,
                 handshake=handshake)
    try:
        assert out["status"] == "ok", out
        assert [d["kind"] for d in out["start_retries"]] == ["died"], out
    finally:
        s.close()


def _not_ready(tmp_path: Path, error: gs.SessionError, times: int) -> Callable[..., None]:
    """A handshake that raises `error` on its first `times` calls, as `handshake` leaves it:
    with the phase it failed at and the stub's answer. The launch it failed on is killed, so
    its `booted` mark goes too, or the next launch's first dial would read it as its own."""
    calls = {"n": 0}

    def handshake(timeout: float | None = None) -> None:
        calls["n"] += 1
        if calls["n"] <= times:
            (tmp_path / "booted").unlink(missing_ok=True)
            raise error

    return handshake


def _phased(error: gs.SessionError, phase: str, reply: str) -> gs.SessionError:
    error.phase, error.reply = phase, reply
    return error


_NOT_READY = [
    _phased(gs.NoRegisters("target.xml declares no registers"), "target.xml", "<target/>"),
    _phased(gs.BadTargetXml("target.xml is not a well-formed document"), "target.xml", "<ta"),
    _phased(gs.Refused("the stub refused `qSupported`: E01"), "qSupported", "E01"),
]


def test_the_handshake_waits_for_the_debuggers_banner_before_asking_the_description(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stub without the thread patch accepts before the debugger's first stop and caches the
    empty description it serves then: a stub handshake that answers `NoRegisters` while MAME's
    output lacks the banner, and the start waits for the banner and boots on one launch."""
    asked_early = []

    def handshake(timeout: float | None = None) -> None:
        assert mstate.STATE.scratch is not None
        log = files.log_path(mstate.STATE.scratch, "process")
        if launch.DEBUGGER_BANNER not in log.read_text(errors="replace"):
            asked_early.append(1)
            (tmp_path / "booted").unlink(missing_ok=True)
            raise _NOT_READY[0]

    out = _start(monkeypatch, tmp_path, _double(tmp_path, banner_after=2), handshake=handshake,
                 request_s=1.0)
    try:
        assert out["status"] == "ok" and out["start_retries"] == [], out
        assert asked_early == [] and _launches(tmp_path) == 1, out
    finally:
        s.close()


def test_a_banner_that_never_comes_leaves_the_handshake_its_request_and_no_more(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no banner the handshake still asks, with one request's time left of the bound, so
    the start ends within its `seconds` as it did before the wait existed."""
    asked_at: list[float] = []
    began = time.monotonic()
    out = _start(monkeypatch, tmp_path, _double(tmp_path, banner_after=None), wait=3.0,
                 handshake=lambda timeout=None: asked_at.append(time.monotonic() - began),
                 request_s=1.0)
    try:
        assert out["status"] == "ok", out
        assert len(asked_at) == 1 and 1.5 < asked_at[0] < 3.0, asked_at
    finally:
        s.close()


def test_the_debuggers_banner_is_the_line_mame_prints() -> None:
    """The constant is held to MAME's own output, captured, and to a log that lacks it."""
    for capture in sorted((Path(__file__).parent / "fixtures" / "console").glob("*.stdout")):
        text = capture.read_text()
        if "gdbstub: listening" in text:
            assert launch.DEBUGGER_BANNER in text, capture.name
            before = text[:text.index("MAME debugger version")]
            assert launch.DEBUGGER_BANNER not in before, capture.name
    assert launch.DEBUGGER_BANNER.strip(), "an empty banner is in every log"


@pytest.mark.parametrize("error", _NOT_READY, ids=["no-registers", "bad-xml", "refused"])
def test_a_live_stub_not_ready_is_relaunched_and_says_where_it_was_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: gs.SessionError
) -> None:
    """A stub that answered its handshake with no register description, a document that does
    not parse, or an `E` refusal, on a process still alive, was not ready: it is launched again
    like a death, under the same cap, the entry says which of the three it was, and the
    relaunch says so on the progress line."""
    lines: list[str] = []
    monkeypatch.setattr(s, "_progress", lambda ctx: lambda done, total, said: lines.append(said))
    out = _start(monkeypatch, tmp_path, _double(tmp_path),
                 handshake=_not_ready(tmp_path, error, 1))
    try:
        assert out["status"] == "ok", out
        assert _launches(tmp_path) == 2
        (entry,) = out["start_retries"]
        assert {k: entry[k] for k in ("kind", "error", "phase", "reply")} == {
            "kind": "stub_not_ready", "error": type(error).__name__, "phase": error.phase,
            "reply": error.reply}, entry
        assert isinstance(entry["after_s"], float) and entry["after_s"] >= 0, entry
        assert "launch 1" in entry["stdout_tail"], entry
        assert out["summary"].endswith("after 1 relaunch"), out["summary"]
        relaunched = [ln for ln in lines if "relaunching" in ln]
        assert relaunched == [f"start m68k: its gdbstub was not ready ({type(error).__name__} "
                              f"at {error.phase}); relaunching after stub_not_ready (1 of "
                              f"{launch.START_RETRIES_MAX})"], lines
    finally:
        s.close()


def test_a_stub_not_ready_is_hung_up_on_while_mame_still_holds_its_side(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The side that closes a connection first keeps its TIME_WAIT. Killed first, MAME's side
    keeps it, on the stub's own port, and the relaunch on a caller's fixed `stub_port` is then
    refused as a port not free: the connection is closed from here, while the
    process that failed still runs."""
    closes: list[tuple[int, bool]] = []
    real_close = REAL_SESSION.close

    def close(ses: gs.Session) -> None:
        proc = mstate.STATE.proc
        closes.append((_launches(tmp_path), proc is not None and proc.poll() is None))
        real_close(ses)

    monkeypatch.setattr(REAL_SESSION, "close", close)
    out = _start(monkeypatch, tmp_path, _double(tmp_path),
                 handshake=_not_ready(tmp_path, _NOT_READY[0], 1))
    try:
        assert out["status"] == "ok", out
        assert (1, True) in closes, closes
    finally:
        s.close()


def test_the_phase_the_real_handshake_marks_is_the_one_the_entry_carries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The seam between the two halves: the first launch's handshake is the REAL one, over a
    wire that serves a description with no register, so what the entry says was marked by
    `Session.handshake` and read by `start`, with nothing authored in between."""
    doc = "<target><architecture>m68k</architecture></target>"
    calls = {"n": 0}

    def handshake(timeout: float | None = None) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            (tmp_path / "booted").unlink(missing_ok=True)
            wired = REAL_SESSION(timeout=0.2)
            wired._sock = _Wire(["PacketSize=4000", "l" + doc])  # type: ignore[assignment]
            wired.handshake(timeout)

    out = _start(monkeypatch, tmp_path, _double(tmp_path), handshake=handshake)
    try:
        assert out["status"] == "ok", out
        (entry,) = out["start_retries"]
        assert (entry["error"], entry["phase"], entry["reply"]) == ("NoRegisters", "target.xml",
                                                                    doc), entry
    finally:
        s.close()


def test_a_stub_never_ready_is_refused_after_the_cap_with_every_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The last one is the refusal, and it is a refusal of a process that was alive: it carries
    what every such refusal carries, the copy of what MAME printed included."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    out = _start(monkeypatch, tmp_path, _double(tmp_path),
                 handshake=_not_ready(tmp_path, _NOT_READY[0], 99))
    assert out["code"] == "session_broken" and out["phase"] == "target.xml", out
    assert _launches(tmp_path) == 1 + launch.START_RETRIES_MAX, out
    assert [d["kind"] for d in out["start_retries"]] == ["stub_not_ready"] * 2, out
    assert out["error"] == "NoRegisters" and out["reply"] == "<target/>", out
    assert out["alive"] is True and out["exit_code"]["available"] is False, out
    assert isinstance(out["pid"], int) and isinstance(out["stub_port"], int), out
    assert "launch 3" in Path(out["stdout_kept"]).read_text(), out
    assert out["session"]["alive"] is False, "the failed start owns nothing"
    kept = list(Path(out["stdout_kept"]).parent.iterdir())
    assert kept == [Path(out["stdout_kept"])], "a launch that was relaunched keeps no copy"


@pytest.mark.parametrize("error", [gs.SessionError("garbled"), gs.Timeout("no answer")],
                         ids=["other", "timeout"])
def test_a_handshake_that_failed_otherwise_is_refused_saying_where_and_when(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: gs.SessionError
) -> None:
    """Any other handshake failure is not relaunched, and the refusal says what happened and
    when, never that the stub "did not answer within the wait" for a failure that came at
    once. An error that names no phase says `unknown`."""
    began = time.monotonic()
    out = _start(monkeypatch, tmp_path, _double(tmp_path), wait=5.0,
                 handshake=_not_ready(tmp_path, error, 99))
    assert out["code"] == "session_broken" and _launches(tmp_path) == 1, out
    assert "handshake failed at unknown after" in out["message"], out["message"]
    assert out["phase"] == "unknown", out
    assert "within the" not in out["message"] and time.monotonic() - began < 3.0, out


@pytest.mark.parametrize(("printed", "noted"), [
    ("Assertion failed: (0 > m_instance), function set_instance, file input_sdl3.cpp, "
     "line 1011.", True),
    ("Assertion failed: (m_ok), function start, file emu.cpp, line 1.", False),
], ids=["sdl3-joystick", "another-assert"])
def test_an_assertions_abort_before_the_stub_is_never_relaunched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, printed: str, noted: bool
) -> None:
    """An assertion is deterministic: the same build aborts the same way on every launch, so
    it is refused at once. When it is SDL3's joystick assertion, the refusal says what avoids
    it."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, abort=printed))
    assert out["code"] == "session_broken" and out["exit_code"] == ABORTED, out
    assert _launches(tmp_path) == 1 and out["start_retries"] == [], out
    assert ("note" in out) is noted, out
    if noted:
        assert "joystickprovider none" in out["note"] and "`inipath`" in out["note"], out


def test_an_abort_that_is_no_assertion_is_relaunched_like_any_signal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SIGABRT alone is not the assertion: `abort()` has other callers, and only the line an
    assertion prints makes the death deterministic."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, abort="libc++abi: terminating"))
    assert out["code"] == "session_broken" and out["exit_code"] == ABORTED, out
    assert _launches(tmp_path) == 1 + launch.START_RETRIES_MAX and "note" not in out, out
    assert [d["exit_code"] for d in out["start_retries"]] == [ABORTED] * 2, out


def test_a_stub_that_never_answers_from_a_live_process_keeps_what_mame_printed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`start` deletes the scratch on a refusal, and a live process whose stub never listened
    left nothing to read: the refusal names the process still there and keeps a copy of what
    it printed where the next reader can open it."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=0.5)
    assert out["code"] == "session_broken" and out["alive"] is True, out
    assert isinstance(out["pid"], int) and isinstance(out["stub_port"], int), out
    kept = Path(out["stdout_kept"])
    assert kept.parent == tmp_path / "state" / "mame-debug" / "failed-starts", kept
    assert kept.name.endswith("-m68k.log") and "launch 1" in kept.read_text(), kept


def test_the_failed_starts_kept_are_the_twenty_newest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The 21st copy written takes the oldest with it, so the folder cannot grow unbounded."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    folder = tmp_path / "state" / "mame-debug" / "failed-starts"
    folder.mkdir(parents=True)
    old = [folder / f"20260101T0000{i:02d}.000000Z-m68k.log" for i in range(20)]
    for path in old:
        path.write_text("an earlier start\n")
    (folder / "notes.log").write_text("somebody else's\n")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "stdout.log").write_text("this start\n")
    kept = Path(str(launch.keep_failed_start(scratch, "m68k")["stdout_kept"]))
    left = sorted(folder.glob("2*.log"))
    assert len(left) == launch.FAILED_STARTS_KEPT == 20 and left[-1] == kept, left
    assert not old[0].exists() and old[1].exists(), "the oldest goes, and only it"
    assert (folder / "notes.log").exists(), "only the copies this writes are rotated"


def test_a_failed_start_whose_output_cannot_be_kept_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The copy is decoration on a refusal: when it cannot be made, the path is null and the
    reason is said, never a sentence in the field a caller opens as a path."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    scratch = tmp_path / "scratch"
    scratch.mkdir()                                  # no stdout.log in it
    got = launch.keep_failed_start(scratch, "m68k")
    assert got["stdout_kept"]["available"] is False, got
    assert "stdout.log" in got["stdout_kept"]["why"] and "stdout_not_kept" not in got, got


def test_a_signal_death_during_the_last_poll_of_the_wait_is_still_a_death(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The process can die while the boot loop sleeps between polls and the wait runs out in
    that same sleep: the loop ends on the clock, not on a poll, and the death has to be read
    once more there or it is reported as a stub that never answered, and not retried."""
    # Polls at 0 and 1 s, a death at 1.2 s inside the second sleep, the wait over at 1.5 s; the
    # relaunch boots at once and is found by its second poll, inside the same wait.
    monkeypatch.setattr(launch, "BOOT_POLL_S", 1.0)
    out = _start(monkeypatch, tmp_path, _double(tmp_path, deaths=1, late=1.2), wait=1.5)
    try:
        assert out["status"] == "ok", out
        assert [d["exit_code"] for d in out["start_retries"]] == [-11], out
    finally:
        s.close()


def test_a_first_launch_that_answers_says_start_retries_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ALWAYS PRESENT, so a caller never has to tell "no retries" from "field missing"."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, deaths=0))
    try:
        assert out["status"] == "ok", out
        assert out["start_retries"] == [] and _launches(tmp_path) == 1, out
        assert "relaunch" not in out["summary"], out["summary"]
    finally:
        s.close()


def test_a_refusal_before_any_launch_also_carries_start_retries(tmp_path: Path) -> None:
    """A `start` judged wrong before anything is spawned still answers the field, empty."""
    out = s.start(binary=str(tmp_path / "absent"), system="m68k", rompath=str(tmp_path),
                  reference_rom=str(tmp_path / "absent.bin"))
    assert out["status"] == "INVALID" and out["start_retries"] == [], out


def test_a_start_the_schema_refuses_also_carries_start_retries() -> None:
    """The schema refuses a wrong TYPE before the tool body runs, in the server's envelope:
    that is a `start` reply too, and the field is promised on every one."""
    out = s.Envelope._refused("start", {"seconds": "soon"}, _schema_error())
    body = json.loads(out.content[0].text)
    assert body["code"] == "bad_argument" and body["start_retries"] == [], body


def _schema_error() -> ValidationError:
    class Wait(BaseModel):
        wait: float

    try:
        Wait.model_validate({"seconds": "soon"})
    except ValidationError as e:
        return e
    raise AssertionError("the schema accepted a word for a float")


def _one_connection_stub(ses: Any, answers_after_s: float) -> dict[str, Any]:
    """MAME's gdbstub as `posixsocket.cpp` serves it: ONE connection, after which the listening
    socket is closed, so a second dial is refused for the rest of the session; and a handshake
    that answers only once the boot reaches the debugger, `answers_after_s` into it."""
    stub: dict[str, Any] = {"listening": True, "dials": 0}

    def dial() -> None:
        if not stub["listening"]:
            raise ConnectionRefusedError(61, "Connection refused")
        stub["dials"] += 1
        stub["listening"] = False

    def handshake(timeout: float) -> None:
        if timeout < answers_after_s:
            raise gs.SessionError(f"no answer within {timeout} s")

    ses.timeout = 0.2
    ses.dial, ses.handshake = dial, handshake
    return stub


def test_a_connection_the_stub_accepted_is_kept_while_its_handshake_waits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dial the kernel completes is the ONE connection MAME will serve, even while the boot
    has not reached the debugger to read it. Dropping it when the handshake is slower than one
    request and dialling again leaves MAME accepting the dead one and closing its listener, and
    every later dial is refused until the wait runs out (measured in the live matrix: `listening
    on port N` in MAME's output, `Connection refused` for the whole wait). So the handshake gets
    what is left of the wait, on the connection already made."""
    ses = _stub_boot(monkeypatch, tmp_path, IMAGE, 0)
    stub = _one_connection_stub(ses, answers_after_s=1.0)
    monkeypatch.setattr(mstate, "QUIT_GRACE_S", 0.2)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(IMAGE)
    try:
        out = s.start(binary=str(_double(tmp_path)), system="m68k", rompath=str(tmp_path),
                      reference_rom=str(rom), seconds=3.0)
        assert out["status"] == "ok", out
        assert stub["dials"] == 1, "one connection, the one MAME serves"
    finally:
        s.close()


def test_a_handshake_that_never_answers_is_refused_without_a_second_dial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The connection was accepted and the stub never answered on it within the wait: the
    refusal says so, rather than reporting the refused dials a second connection would earn."""
    ses = _stub_boot(monkeypatch, tmp_path, IMAGE, 0)
    stub = _one_connection_stub(ses, answers_after_s=99.0)
    monkeypatch.setattr(mstate, "QUIT_GRACE_S", 0.2)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(IMAGE)
    out = s.start(binary=str(_double(tmp_path)), system="m68k", rompath=str(tmp_path),
                  reference_rom=str(rom), seconds=0.6)
    assert out["code"] == "session_broken" and stub["dials"] == 1, out
    assert "accepted the connection" in out["message"], out["message"]


def test_a_stub_proved_to_be_another_process_on_its_own_pick_is_relaunched_on_another_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The dial's proof found another pid on the port this server picked (`mame_stub_owner`):
    another instance took it first, nothing was sent to it, and a relaunch picks another, so
    the launch is made again and the stranger rides on the reply."""
    calls = [0]

    def dial() -> None:
        calls[0] += 1
        if calls[0] == 1:
            raise owner.StubNotOurs(4242, [777], 1)
        if not (tmp_path / "booted").exists():
            raise OSError("connection refused")

    out = _start(monkeypatch, tmp_path, _double(tmp_path), dial=dial)
    try:
        assert out["status"] == "ok", out
        assert calls[0] >= 2, "the second launch was dialled"
        [served] = out["start_retries"]
        assert served["kind"] == "port_served", served
        assert "port 4242 is served by pid 777" in served["error"], served
    finally:
        s.close()


def test_a_stub_proved_to_be_another_process_on_the_callers_port_is_refused_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """On the caller's own `stub_port` a relaunch would meet the same process: `host_failed`,
    the port and that pid named, the launched MAME killed, never relaunched."""
    def dial() -> None:
        raise owner.StubNotOurs(4242, [777], 1)

    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=5.0, dial=dial,
                 stub_port=launch.free_port())
    assert out["status"] == "INVALID" and out["code"] == "host_failed", out
    assert "port 4242 is served by pid 777" in out["message"], out
    assert "your `stub_port` is another process's" in out["message"], out
    assert out["start_retries"] == [], "refused at once, never relaunched"
    assert mstate.STATE.proc is None, "the launched MAME was killed with the refused start"


# MAME's own line, as a run that lost the race printed it.
CARD_LINE = ("Fatal error: gdbstub: failed to start listening on address localhost port 61726")


@pytest.mark.parametrize("exit_code, tail, taken", [
    (3, CARD_LINE, True),
    (3, "launch 1\n" + CARD_LINE + "\n", True),
    (0, CARD_LINE, False),
    (-11, CARD_LINE, False),
    (3, "Fatal error: gdbstub: cpuname m68000 not found in gdb stub descriptions", False),
    (3, "Fatal error: gdbstub: failed to start listening on address localhost port", False),
    (3, "", False),
])
def test_a_port_taken_is_mames_own_line_and_an_exit_code(exit_code: int, tail: str,
                                                         taken: bool) -> None:
    died = failures.DiedBeforeStub(exit_code, 1.0, tail)
    assert died.port_taken() is taken
    assert died.relaunch(port_picked=False) is (exit_code < 0)
    assert died.relaunch(port_picked=True) is (taken or exit_code < 0)


def test_a_real_launch_is_watched_by_a_guardian_that_ends_with_the_refused_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`boot` spawns the guardian for the process it launched, and the failed start stops it:
    seen live while the dial waits, gone once the refusal is out."""
    seen: list[Any] = []

    def dial() -> None:
        guard = mstate.STATE.guard
        seen.append((guard, guard is not None and guard.poll() is None,
                     mstate.STATE.proc.pid if mstate.STATE.proc else None))
        raise OSError("connection refused")

    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=0.5, dial=dial)
    assert out["status"] == "INVALID", out
    guard, running, _ = seen[0]
    assert guard is not None and running, seen
    assert guard.poll() is not None and mstate.STATE.guard is None


def test_a_host_that_cannot_prove_the_stub_is_refused_without_a_port_to_try(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No `lsof` to ask is the host's, and another port would meet the same host: `host_failed`
    with no advice to start on another port."""
    def dial() -> None:
        raise owner.StubUnproved("`lsof` is not on this host's PATH")

    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=5.0, dial=dial)
    assert out["status"] == "INVALID" and out["code"] == "host_failed", out
    assert "`lsof` is not on this host's PATH" in out["message"]
    assert "stub_port" not in out["message"] and out["start_retries"] == []


def test_a_connection_nobody_accepted_is_a_stub_that_did_not_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The same refusal as a stub that never listened, `session_broken` with the dials, never
    blamed on the host."""
    def dial() -> None:
        raise owner.StubNotAccepted("no process accepted it within the boot's bound")

    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=5.0, dial=dial)
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert "did not answer within 5.0 s: no process accepted it" in out["message"]
    assert "dial_attempts" in out and out["alive"] is True
