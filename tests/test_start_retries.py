"""`start` relaunches a MAME that died by a signal before its gdbstub answered, a live stub that
answered unready, and a stub port taken by another process; nothing else (the why is
`REFERENCE.md`, *The session*).

The emulator double is a real shell process that sends itself SIGSEGV, because an authored reply
could not tell a signal from an exit code; only the gdbstub's side is stubbed. macOS writes a
crash report per self-SIGSEGV under `~/Library/Logs/DiagnosticReports`.
"""

import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from scry_core import host_program
from server_support import BANNER_LINE, _ExitingProcess, _RecordingSession, _stub_boot  # noqa: E402
from test_gdb_session import _Wire  # noqa: E402

from scry_mame import boot_failures as failures  # noqa: E402
from scry_mame import (
    files,  # noqa: E402
    launch,  # noqa: E402
)
from scry_mame import gdb_session as gs  # noqa: E402
from scry_mame import mcp as mame_mcp  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402
from scry_mame import stub_owner as owner  # noqa: E402

# Kept before `_stub_boot` replaces the module's name with its double.
REAL_SESSION = gs.Session
ABORTED = -signal.SIGABRT

IMAGE = bytes(range(256)) * 64

# Knobs: DEATHS launches die by SIGSEGV (after LATE s); EXIT is a plain exit code; HANG never
# boots; ABORT/FATAL print their line then die by SIGABRT/SIGSEGV; SAID is a line a live MAME
# prints; CPUS are the tags `-listxml` lists, in order; the banner prints BANNER_AFTER s after
# boot (never when None); the first LOST launches end as MAME does on a taken port, exit 3.
DOUBLE = """import os, signal, sys, time
from pathlib import Path
args = sys.argv[1:]
if "-listxml" in args:
    if %(cpus)r:
        print('<mame><machine name="m68k">'
              + "".join(f'<chip type="cpu" tag="{t}" name="cpu"/>' for t in %(cpus)r)
              + "</machine></mame>")
    sys.exit(0)
if "-version" in args:
    print("0.0 (double)")
    sys.exit(0)
here = Path(sys.argv[0]).parent
(here / "booted").unlink(missing_ok=True)
launches = here / "launches"
n = int(launches.read_text()) + 1 if launches.exists() else 1
launches.write_text(str(n))
print(f"launch {n}", flush=True)
if %(exit)r:
    sys.exit(int(%(exit)r))
if n <= %(lost)d:
    port = args[args.index("-debugger_port") + 1] if "-debugger_port" in args else ""
    sys.stderr.write("Fatal error: gdbstub: failed to start listening on address localhost "
                     f"port {port}\\n")
    sys.exit(3)
if %(hang)r:
    time.sleep(60)
    sys.exit(0)
if %(abort)r:
    print(%(abort)r, flush=True)
    os.kill(os.getpid(), signal.SIGABRT)
if %(fatal)r:
    print("Ignoring MAME exception: " + %(fatal)r, flush=True)
    sys.stderr.write("Fatal error: " + %(fatal)r + "\\n")
    sys.stderr.flush()
    os.kill(os.getpid(), signal.SIGSEGV)
if n <= %(deaths)d:
    time.sleep(%(late)r)
    os.kill(os.getpid(), signal.SIGSEGV)
if %(said)r:
    print(%(said)r, flush=True)
(here / "booted").touch()
%(banner)s
time.sleep(60)
"""


def _double(tmp_path: Path, deaths: int = 0, exit_code: str = "", hang: bool = False,
            late: float = 0, abort: str = "", fatal: str = "",
            banner_after: float | None = 0, lost: int = 0, said: str = "",
            cpus: tuple[str, ...] = ()) -> Path:
    if sys.platform == "win32" and (deaths or abort or fatal):
        pytest.skip("a death by signal is POSIX's: Windows ends a process with an exit code")
    binary = host_program.write(tmp_path / "segv-mame", DOUBLE % {
        "deaths": deaths, "exit": exit_code, "hang": hang, "late": late, "abort": abort,
        "fatal": fatal, "lost": lost, "said": said, "cpus": cpus,
        "banner": "" if banner_after is None else
        f"time.sleep({banner_after!r})\nsys.stdout.write({BANNER_LINE!r})\nsys.stdout.flush()"})
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
    # The double never answers `quit`; the grace wait is not what these cases measure.
    if not real_grace:
        monkeypatch.setattr(mstate, "QUIT_GRACE_S", 0.2)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(IMAGE)
    out: dict[str, Any] = s.start(binary=str(binary), system="m68k", rompath=str(tmp_path),
                                  reference_rom=str(rom), boot_seconds=wait, **start_kw)
    return out


def _launches(tmp_path: Path) -> int:
    return int((tmp_path / "launches").read_text())


@pytest.mark.parametrize("deaths", [1, launch.START_RETRIES_MAX])
def test_a_signal_death_before_the_stub_is_relaunched_and_the_death_is_in_the_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, deaths: int
) -> None:
    """(a) SIGSEGV then a boot that answers, up to the cap: each death rides on the reply."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, deaths=deaths))
    try:
        assert out["status"] == "ok", out
        assert _launches(tmp_path) == deaths + 1
        assert [d["exit_code"] for d in out.get("start_retries", [])] == [-11] * deaths, out
        for n, death in enumerate(out.get("start_retries", []), 1):
            assert death["kind"] == "died", death
            assert isinstance(death["after_s"], float) and death["after_s"] >= 0, death
            assert f"launch {n}" in death["stdout_tail"], death
        said = "1 relaunch" if deaths == 1 else f"{deaths} relaunches"
        assert out["summary"].endswith(f"after {said}"), out["summary"]
        assert list(out)[-1] == "session", "`session` stays the last key"
        again = s.start(binary="/x/mame", system="m68k", rompath="/x", reference_rom="/x/rom")
        assert again["code"] == "session_live" and again.get("start_retries", []) == [], again
    finally:
        s.close()


def test_a_signal_death_every_time_is_refused_after_the_cap_with_every_death_in_the_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """(b) A MAME that always dies: the cap's retries recorded, the last death is the refusal."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, deaths=99))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert _launches(tmp_path) == 1 + launch.START_RETRIES_MAX == 3
    assert [d["exit_code"] for d in out.get("start_retries", [])] == [-11,
                                                                      -11], out.get("start_retries",
                                                                                    [])
    assert ["launch 1" in out.get("start_retries", [])[0]["stdout_tail"],
            "launch 2" in out.get("start_retries", [])[1]["stdout_tail"]] == [True, True]
    assert out["exit_code"] == -11 and "launch 3" in out["stdout_tail"], out
    assert out["session"]["alive"] is False, "the failed start owns nothing"


# A stock MAME's line when its gdbstub lacks the first cpu, before it dies by SIGSEGV.
NOT_SERVED = "gdbstub: cpuname mc6809e not found in gdb stub descriptions"


def test_a_first_cpu_the_stub_cannot_serve_is_refused_at_once_naming_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A first cpu the stub cannot describe is refused at once as `no_channel`."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, fatal=NOT_SERVED))
    assert out["status"] == "INVALID" and out["code"] == "no_channel", out
    assert _launches(tmp_path) == 1 and out.get("start_retries", []) == [], out
    assert f"`Fatal error: {NOT_SERVED}`" in out["message"], out["message"]
    assert "the first cpu, mc6809e," in out["message"], out["message"]
    assert "a build whose stub describes that cpu" in out["message"], "the way out"
    assert "0004" not in out["message"], "0004 serves no first cpu its stub cannot describe"
    assert out["exit_code"] == -11 and isinstance(out["after_s"], float), out
    assert out["session"]["alive"] is False, "the failed start owns nothing"


# The line a gdbstub serving a thread per cpu prints for a cpu it cannot describe; it lives on.
UNSERVED = ("gdbstub: cpuname mc6809e (:maincpu) not found in gdb stub descriptions, so its "
            "registers are not served")


@pytest.mark.parametrize("ending", ["", "\r"], ids=["line-feed", "carriage-return"])
def test_a_live_stub_that_cannot_describe_the_first_cpu_is_refused_at_once_naming_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ending: str
) -> None:
    """A stub that lives on without the first cpu refuses `target.xml` on every launch, so the
    start is `no_channel` at once, quoting MAME's line, never relaunched as a stub not ready.
    A Windows MAME writes that line with a carriage return before the newline."""
    out = _start(monkeypatch, tmp_path,
                 _double(tmp_path, said=UNSERVED + ending, cpus=("maincpu", "soundcpu")),
                 handshake=_not_ready(tmp_path, _target_xml_refused(),
                                      launch.START_RETRIES_MAX + 1))
    assert out["status"] == "INVALID" and out["code"] == "no_channel", out
    assert _launches(tmp_path) == 1 and out.get("start_retries", []) == [], out
    assert f"`{UNSERVED}`" in out["message"] and "mc6809e (:maincpu)" in out["message"], out
    assert "a build whose stub describes that cpu" in out["message"], out["message"]
    assert out["session"]["alive"] is False, "the failed start owns nothing"


def _target_xml_refused() -> gs.SessionError:
    return _phased(gs.Refused("the stub refused `qXfer:features:read:target.xml:0,400`: E01"),
                   "target.xml", "E01")


@pytest.mark.parametrize(("said", "error"), [
    ("", _target_xml_refused),
    # a later cpu unserved: no reason for thread 1's description to fail
    (UNSERVED.replace("mc6809e (:maincpu)", "m6808 (:soundcpu)"), _target_xml_refused),
    # the first cpu's line beside a refusal of another question, or of another kind
    (UNSERVED, lambda: _phased(gs.Refused("the stub refused `qSupported`: E01"), "qSupported",
                               "E01")),
    (UNSERVED, lambda: _phased(gs.NoRegisters("target.xml declares no registers"), "target.xml",
                               "<target/>")),
], ids=["no-line", "later-cpu", "other-phase", "other-error"])
def test_a_refused_handshake_the_first_cpus_line_does_not_explain_is_a_stub_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, said: str,
    error: Callable[[], gs.SessionError],
) -> None:
    out = _start(monkeypatch, tmp_path,
                 _double(tmp_path, said=said, cpus=("maincpu", "soundcpu")),
                 handshake=_not_ready(tmp_path, error(), 1))
    try:
        assert out["status"] == "ok", out
        assert [d["kind"] for d in out.get("start_retries", [])] == ["stub_not_ready"], out
    finally:
        s.close()


@pytest.mark.parametrize(("tail", "code"), [
    # glued behind a console prompt
    ("\x1b[1;36m[MAME]\x1b[0m> Fatal error: gdbstub: cpuname mc6809e not found in gdb stub "
     "descriptions\n", -11),
    # a build that exits instead of raising a signal
    (f"Fatal error: {NOT_SERVED}\n", 2),
    # the same line as a Windows MAME writes it
    (f"Fatal error: {NOT_SERVED}\r\n", 2),
])
def test_the_unserved_cpu_is_read_wherever_its_line_lands_and_however_mame_ends(
    tail: str, code: int,
) -> None:
    refusal = failures.death_refusal(code, 1.5, tail)
    assert refusal.code == "no_channel" and "mc6809e" in str(refusal), refusal


@pytest.mark.parametrize("tail", [
    # the patched stub's line: no registers served, no death
    "gdbstub: cpuname mc6809e (:maincpu) not found in gdb stub descriptions, so its registers "
    "are not served\n",
    # stdout's half alone
    f"Ignoring MAME exception: {NOT_SERVED}\n",
])
def test_a_death_without_the_fatal_line_stays_a_death(tail: str) -> None:
    refusal = failures.death_refusal(-11, 1.5, tail)
    assert isinstance(refusal, failures.DiedBeforeStub) and refusal.relaunch(True), refusal


def test_a_handshake_cut_by_the_unserved_cpus_death_is_refused_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A handshake cut by the unserved cpu's death is refused like a death before the dial."""
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
    assert out["code"] == "no_channel" and out.get("start_retries", []) == [], out
    assert _launches(tmp_path) == 1, out


@pytest.mark.parametrize("lost", [1, launch.START_RETRIES_MAX])
def test_a_port_taken_before_mame_bound_it_is_relaunched_on_a_fresh_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lost: int
) -> None:
    """A port taken before MAME bound it (exit 3 with its line) is relaunched on a fresh port."""
    picked = iter(range(41001, 41001 + launch.START_RETRIES_MAX + 1))
    monkeypatch.setattr(launch, "free_port", lambda: next(picked))
    out = _start(monkeypatch, tmp_path, _double(tmp_path, lost=lost))
    try:
        assert out["status"] == "ok", out
        assert _launches(tmp_path) == lost + 1
        assert [d["exit_code"] for d in out.get("start_retries", [])] == [3] * lost, out
        for n, retry in enumerate(out.get("start_retries", [])):
            assert f"failed to start listening on address localhost port {41001 + n}" in \
                retry["stdout_tail"], retry
    finally:
        s.close()


def test_a_port_lost_on_every_launch_is_refused_after_the_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Lost on every launch: the relaunches stop at the cap and the last loss is the refusal."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, lost=launch.START_RETRIES_MAX + 1))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert out["exit_code"] == 3, out
    assert _launches(tmp_path) == launch.START_RETRIES_MAX + 1
    assert len(out.get("start_retries", [])) == launch.START_RETRIES_MAX, out
    assert "failed to start listening" in out["stdout_tail"], out


def test_a_port_the_caller_named_is_never_relaunched_on_another(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The caller's `stub_port` is never swapped: a lost race on it is refused at once."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, lost=1), stub_port=launch.free_port())
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert _launches(tmp_path) == 1
    assert out.get("start_retries", []) == [], out


@pytest.mark.parametrize("code", [2, 0, 3])
def test_an_exit_code_before_the_stub_is_never_relaunched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int
) -> None:
    """(c) An exit code is MAME refusing the caller's input, so it is refused at once."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, exit_code=str(code)))
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert _launches(tmp_path) == 1
    assert out.get("start_retries", []) == [], out
    assert out["exit_code"] == code, out


def test_a_stub_that_never_answers_from_a_live_process_is_not_relaunched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A MAME still alive at the end of the wait is slow or stuck, so it is not relaunched."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=0.5)
    assert out["code"] == "session_broken" and "did not answer" in out["message"], out
    assert _launches(tmp_path) == 1 and out.get("start_retries", []) == [], out


def test_a_start_that_failed_is_killed_without_the_grace_close_gives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed start is killed without the grace `close` gives a machine asked to quit."""
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
    """Discarding a failed start's session kills it without asking MAME to quit."""
    ses = _RecordingSession()
    mstate.STATE.ses, mstate.STATE.proc = ses, _ExitingProcess(ses.events, exits=True)  # type: ignore[assignment]
    ended = mstate.STATE.kill(grace=False)
    assert ended["ended_by"] == "killed" and "quit" not in ses.events, ses.events
    assert ses.events[0] == "kill", ses.events


def test_every_dial_attempt_rides_on_the_refusal_folded_by_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Consecutive identical dial errors fold into one entry with first/last time and count."""
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
    """A new error opens an entry; the same one moves `last_s` and counts."""
    attempts: list[dict[str, Any]] = []
    for at, error in ((0.0, OSError("a")), (0.3, OSError("a")), (0.6, OSError("b"))):
        failures.fold_attempt(attempts, at, error)
    assert attempts == [{"first_s": 0.0, "last_s": 0.3, "count": 2, "error": "OSError: a"},
                        {"first_s": 0.6, "last_s": 0.6, "count": 1, "error": "OSError: b"}]


def test_a_launch_failure_is_relaunched_only_when_its_class_says_so() -> None:
    """The default closes: a failure class is relaunched only when it says so."""
    failed = failures.LaunchFailed("m", "w", {"kind": "k"})
    assert failed.relaunch(True) is False and failed.relaunch(False) is False
    assert failed.kind == "k"


def test_a_dial_that_failed_on_a_live_process_is_refused_at_once_with_its_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed first byte on a live process is refused at once: MAME serves one connection."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    def dial() -> None:
        while not (tmp_path / "launches").exists():  # the double has counted its launch
            time.sleep(0.01)
        raise gs.DialFailed("the connection was made and its first byte failed: reset")

    began = time.monotonic()
    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=5.0, dial=dial)
    assert out["code"] == "session_broken" and time.monotonic() - began < 3.0, out
    assert _launches(tmp_path) == 1 and out.get("start_retries", []) == [], out
    assert [a["error"] for a in out["dial_attempts"]] == [
        "DialFailed: the connection was made and its first byte failed: reset"], out
    assert Path(out["stdout_kept"]).exists() and out["alive"] is True, out


def test_a_dial_that_failed_because_mame_died_is_a_death(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dial that failed because MAME was dying is a death, relaunched as one."""
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
        assert [d["kind"] for d in out.get("start_retries", [])] == ["died"], out
    finally:
        s.close()


def test_a_handshake_cut_because_mame_died_is_a_death(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A handshake cut because MAME was dying is a death, relaunched as one."""
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
        assert [d["kind"] for d in out.get("start_retries", [])] == ["died"], out
    finally:
        s.close()


def _not_ready(tmp_path: Path, error: gs.SessionError, times: int) -> Callable[..., None]:
    """A handshake that raises `error` on its first `times` calls, with its phase and reply;
    it also removes `booted`, or the next launch's first dial would read it as its own."""
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
    """The handshake waits for the debugger's banner before asking for the description."""
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
        assert out["status"] == "ok" and out.get("start_retries", []) == [], out
        assert asked_early == [] and _launches(tmp_path) == 1, out
    finally:
        s.close()


def test_a_banner_that_never_comes_leaves_the_handshake_its_request_and_no_more(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no banner the handshake still asks, with one request's time left of the bound."""
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
    """The banner constant is held to MAME's captured output and to a log that lacks it."""
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
    """A live stub that is not ready is relaunched like a death and the entry says where."""
    lines: list[str] = []
    monkeypatch.setattr(s, "bridge", lambda ctx: lambda done, total, said: lines.append(said))
    out = _start(monkeypatch, tmp_path, _double(tmp_path),
                 handshake=_not_ready(tmp_path, error, 1))
    try:
        assert out["status"] == "ok", out
        assert _launches(tmp_path) == 2
        (entry,) = out.get("start_retries", [])
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
    """The connection is closed from here while the process still runs: killed first, MAME's side
    would keep TIME_WAIT and a fixed `stub_port` would then be refused as not free."""
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
    """The first launch's handshake is the real one, so the entry's phase is what it marked."""
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
        (entry,) = out.get("start_retries", [])
        assert (entry["error"], entry["phase"], entry["reply"]) == ("NoRegisters", "target.xml",
                                                                    doc), entry
    finally:
        s.close()


def test_a_stub_never_ready_is_refused_after_the_cap_with_every_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The last unready stub is the refusal of a live process, with the copy of its output."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    out = _start(monkeypatch, tmp_path, _double(tmp_path),
                 handshake=_not_ready(tmp_path, _NOT_READY[0], 99))
    assert out["code"] == "session_broken" and out["phase"] == "target.xml", out
    assert _launches(tmp_path) == 1 + launch.START_RETRIES_MAX, out
    assert [d["kind"] for d in out.get("start_retries", [])] == ["stub_not_ready"] * 2, out
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
    """Any other handshake failure is refused with where and when; no phase is `unknown`."""
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
    """An assertion's abort is refused at once; SDL3's joystick one adds a note."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, abort=printed))
    assert out["code"] == "session_broken" and out["exit_code"] == ABORTED, out
    assert _launches(tmp_path) == 1 and out.get("start_retries", []) == [], out
    assert ("note" in out) is noted, out
    if noted:
        assert "joystickprovider none" in out["note"] and "`inipath`" in out["note"], out


def test_an_abort_that_is_no_assertion_is_relaunched_like_any_signal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SIGABRT alone is not an assertion: only the printed line makes the death deterministic."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, abort="libc++abi: terminating"))
    assert out["code"] == "session_broken" and out["exit_code"] == ABORTED, out
    assert _launches(tmp_path) == 1 + launch.START_RETRIES_MAX and "note" not in out, out
    assert [d["exit_code"] for d in out.get("start_retries", [])] == [ABORTED] * 2, out


def test_a_stub_that_never_answers_from_a_live_process_keeps_what_mame_printed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A live process whose stub never listened leaves a kept copy of its output on the refusal."""
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
    """The 21st copy takes the oldest with it, so the folder stays bounded."""
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
    """A copy that cannot be made says why in a null-path field, never a sentence in a path."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    scratch = tmp_path / "scratch"
    scratch.mkdir()                                  # no stdout.log in it
    got = launch.keep_failed_start(scratch, "m68k")
    assert got["stdout_kept"]["available"] is False, got
    assert "stdout.log" in got["stdout_kept"]["why"] and "stdout_not_kept" not in got, got


def test_a_signal_death_during_the_last_poll_of_the_wait_is_still_a_death(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A death in the sleep where the wait runs out is read once more, not called a hang."""
    # One poll at 0, then one sleep that outlasts the wait. The double would sleep a minute;
    # it is killed inside that sleep, so the death lands there whatever the host's load, where
    # a death timed by the clock can fall after the wait on a busy host.
    monkeypatch.setattr(launch, "BOOT_POLL_S", 1.5)
    real_sleep = time.sleep
    killed: list[int] = []

    def sleep(seconds: float) -> None:
        proc = mstate.STATE.proc
        if not killed and seconds == launch.BOOT_POLL_S and proc is not None:
            killed.append(proc.pid)
            while not (tmp_path / "launches").exists() and proc.poll() is None:  # counted
                real_sleep(0.01)
            os.kill(proc.pid, signal.SIGSEGV)
            proc.wait(timeout=30)
            monkeypatch.setattr(launch, "BOOT_POLL_S", 0.05)  # the relaunch polls as usual
        real_sleep(seconds)

    monkeypatch.setattr(time, "sleep", sleep)
    out = _start(monkeypatch, tmp_path, _double(tmp_path, deaths=1, late=60), wait=1.5)
    try:
        assert out["status"] == "ok", out
        assert [d["exit_code"] for d in out.get("start_retries", [])] == [-11], out
    finally:
        s.close()


def test_a_first_launch_that_answers_says_start_retries_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`start_retries` is always present, empty when the first launch answered."""
    out = _start(monkeypatch, tmp_path, _double(tmp_path, deaths=0))
    try:
        assert out["status"] == "ok", out
        assert out.get("start_retries", []) == [] and _launches(tmp_path) == 1, out
        assert "relaunch" not in out["summary"], out["summary"]
    finally:
        s.close()


def test_a_refusal_before_any_launch_also_carries_start_retries(tmp_path: Path) -> None:
    """A start refused before any spawn still answers `start_retries`, empty."""
    out = s.start(binary=str(tmp_path / "absent"), system="m68k", rompath=str(tmp_path),
                  reference_rom=str(tmp_path / "absent.bin"))
    assert out["status"] == "INVALID" and out.get("start_retries", []) == [], out


def test_a_start_the_schema_refuses_also_carries_start_retries() -> None:
    """A schema refusal is a `start` reply too and carries `start_retries`."""
    body = mame_mcp.refusal("start", {"boot_seconds": "soon"}, _schema_error())
    assert body["code"] == "bad_argument" and body.get("start_retries", []) == [], body


def _schema_error() -> ValidationError:
    class Wait(BaseModel):
        wait: float

    try:
        Wait.model_validate({"seconds": "soon"})
    except ValidationError as e:
        return e
    raise AssertionError("the schema accepted a word for a float")


def _one_connection_stub(ses: Any, answers_after_s: float) -> dict[str, Any]:
    """MAME's gdbstub as `posixsocket.cpp` serves it: one connection, then the listener closes;
    the handshake answers only `answers_after_s` into the boot."""
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
    """The connection a dial completed is the only one MAME serves, so a slow handshake gets what is
    left of the wait on it; dialling again would be refused for the rest of the wait."""
    ses = _stub_boot(monkeypatch, tmp_path, IMAGE, 0)
    stub = _one_connection_stub(ses, answers_after_s=1.0)
    monkeypatch.setattr(mstate, "QUIT_GRACE_S", 0.2)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(IMAGE)
    try:
        out = s.start(binary=str(_double(tmp_path)), system="m68k", rompath=str(tmp_path),
                      reference_rom=str(rom), boot_seconds=3.0)
        assert out["status"] == "ok", out
        assert stub["dials"] == 1, "one connection, the one MAME serves"
    finally:
        s.close()


def test_a_handshake_that_never_answers_is_refused_without_a_second_dial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A handshake that never answers on an accepted connection is refused without a second dial."""
    ses = _stub_boot(monkeypatch, tmp_path, IMAGE, 0)
    stub = _one_connection_stub(ses, answers_after_s=99.0)
    monkeypatch.setattr(mstate, "QUIT_GRACE_S", 0.2)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(IMAGE)
    out = s.start(binary=str(_double(tmp_path)), system="m68k", rompath=str(tmp_path),
                  reference_rom=str(rom), boot_seconds=0.6)
    assert out["code"] == "session_broken" and stub["dials"] == 1, out
    assert "accepted the connection" in out["message"], out["message"]


def test_a_stub_proved_to_be_another_process_on_its_own_pick_is_relaunched_on_another_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Another pid on a port this server picked: relaunched, the stranger on the reply."""
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
        [served] = out.get("start_retries", [])
        assert served["kind"] == "port_served", served
        assert "port 4242 is served by pid 777" in served["error"], served
        assert not list((tmp_path / "xdg-state" / "mame-debug" / "failed-starts").glob("*")), \
            "a launch that was relaunched keeps no copy"
    finally:
        s.close()


def test_a_stub_proved_to_be_another_process_on_the_callers_port_is_refused_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Another owner on the caller's `stub_port` is `host_failed`, never relaunched."""
    def dial() -> None:
        raise owner.StubNotOurs(4242, [777], 1)

    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=5.0, dial=dial,
                 stub_port=launch.free_port())
    assert out["status"] == "INVALID" and out["code"] == "host_failed", out
    assert "port 4242 is served by pid 777" in out["message"], out
    assert "your `stub_port` is another process's" in out["message"], out
    assert out.get("start_retries", []) == [], "refused at once, never relaunched"
    assert mstate.STATE.proc is None, "the launched MAME was killed with the refused start"


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


@pytest.mark.parametrize("exit_code, ended", [(-11, "died by signal 11"),
                                              (7, "exited with code 7")])
def test_a_death_before_the_stub_says_how_the_process_ended_in_one_voice(
    exit_code: int, ended: str
) -> None:
    """A signal death is a signal and an exit code is a code, in the refusal and in the line that
    names the fatal gdbstub error alike."""
    died = failures.DiedBeforeStub(exit_code, 1.0, "")
    assert ended in str(died) and ended in died.what, died
    fatal = failures.death_refusal(exit_code, 1.0, NOT_SERVED)
    assert ended in str(fatal), fatal


def test_a_real_launch_is_watched_by_a_guardian_that_ends_with_the_refused_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The failed start stops the guardian `boot` spawned for the launched process."""
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
    """No `lsof` to ask is the host's: `host_failed` with no advice to change port."""
    def dial() -> None:
        raise owner.StubUnproved("`lsof` is not on this host's PATH")

    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=5.0, dial=dial)
    assert out["status"] == "INVALID" and out["code"] == "host_failed", out
    assert "`lsof` is not on this host's PATH" in out["message"]
    assert "stub_port" not in out["message"] and out.get("start_retries", []) == []


def test_a_connection_nobody_accepted_is_a_stub_that_did_not_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A connection nobody accepted is `session_broken` with the dials, not blamed on the host."""
    def dial() -> None:
        raise owner.StubNotAccepted("no process accepted it within the boot's bound")

    out = _start(monkeypatch, tmp_path, _double(tmp_path, hang=True), wait=5.0, dial=dial)
    assert out["status"] == "INVALID" and out["code"] == "session_broken", out
    assert "did not answer within 5.0 s: no process accepted it" in out["message"]
    assert "dial_attempts" in out and out["alive"] is True
