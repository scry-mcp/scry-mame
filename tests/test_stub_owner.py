"""Whose gdbstub a port serves, proved against real processes and the host's real instrument:
`lsof` on POSIX, the TCP table on Windows, read here also from rows captured on one."""

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from process_probes import heard, listener  # noqa: E402

import gdb_session as gs  # noqa: E402
import mame_stub_owner as owner  # noqa: E402

NOT_A_PID = 2**22 + 7  # above macOS's pid ceiling: a pid no process can hold
#: The cases about `lsof` itself, which Windows replaces with its TCP table.
LSOF = pytest.mark.skipif(sys.platform == "win32", reason="Windows reads its TCP table")
#: Cases about a connection queued and not accepted, which Windows already lists as the
#: listener's.
QUEUED_UNOWNED = pytest.mark.skipif(sys.platform == "win32",
                                    reason="Windows owns a queued connection to its listener")
#: Rows `GetExtendedTcpTable` returned on Windows (`fixtures/stub_owner/PROVENANCE.txt`).
CAPTURED = json.loads((Path(__file__).parent / "fixtures" / "stub_owner" / "tcp_rows.json")
                      .read_text(encoding="utf-8"))


def _proof(pid: int, port: int, seconds: float = 5.0, alive: bool = True) -> owner.StubOwner:
    return owner.StubOwner(pid=pid, port=port, deadline=time.monotonic() + seconds,
                           alive=lambda: alive)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def test_listeners_names_the_process_that_listens_and_nobody_on_a_free_port() -> None:
    proc, port = listener("hold")
    try:
        assert owner.listeners(port) == {proc.pid}
        assert owner.listeners(_free_port()) == set(), "nobody on it is an honest empty answer"
    finally:
        proc.kill()
        proc.wait()


def test_another_pid_listening_is_refused_and_never_dialled() -> None:
    """Refused before the dial: it would take the other MAME's one connection."""
    proc, port = listener("accept", timeout_s=1.0)
    try:
        ses = gs.Session(port=port, owner=_proof(NOT_A_PID, port))
        with pytest.raises(owner.StubNotOurs) as e:
            ses.dial()
        assert e.value.port == port and e.value.pids == [proc.pid], e.value
        assert f"port {port}" in str(e.value) and str(proc.pid) in str(e.value)
        assert heard(proc) == "none", "the other process was dialled"
        assert ses.local_port is None
    finally:
        proc.kill()
        proc.wait()


def test_our_pid_beside_another_listening_is_refused_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SO_REUSEPORT allows two listeners: ours among them is not enough."""
    monkeypatch.setattr(owner, "bind_probe", lambda port: None)
    monkeypatch.setattr(owner, "listeners", lambda port: {10, 20})
    with pytest.raises(owner.StubNotOurs) as e:
        _proof(10, 1).before_dial()
    assert e.value.pids == [20]


@LSOF
def test_nothing_on_the_port_is_the_boot_under_way_and_asks_no_lsof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_lsof(args: list[str]) -> list[str]:
        raise AssertionError("lsof was asked about a port that binds")

    monkeypatch.setattr(owner, "_fields", no_lsof)
    with pytest.raises(owner.NotListening) as e:
        _proof(1, _free_port()).before_dial()
    assert isinstance(e.value, OSError), "the boot's wait treats it as a refused dial"


def test_a_port_held_only_by_a_connection_is_not_yet_ours_listening() -> None:
    """A served session's port with its listener closed does not bind and has no listener."""
    lst = socket.socket()
    lst.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lst.bind(("127.0.0.1", 0))
    lst.listen(1)
    port = lst.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    served, _ = lst.accept()
    lst.close()
    try:
        with pytest.raises(owner.NotListening):
            _proof(1, port).before_dial()
    finally:
        served.close()
        client.close()


def test_the_far_end_in_another_process_is_closed_with_nothing_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The race the listener check cannot close: closed before the first byte is sent."""
    proc, port = listener("accept")
    try:
        monkeypatch.setattr(owner, "listeners", lambda p: {NOT_A_PID})
        ses = gs.Session(port=port, owner=_proof(NOT_A_PID, port))
        with pytest.raises(owner.StubNotOurs) as e:
            ses.dial()
        assert e.value.pids == [proc.pid], e.value
        assert ses.local_port is None, "the connection was closed"
        assert heard(proc) == "b''", "the other process read something"
    finally:
        proc.kill()
        proc.wait()


def test_the_far_end_in_our_process_passes_and_the_first_byte_goes_out() -> None:
    """Control of the case above: the same child named as ours gets the dial through."""
    proc, port = listener("accept")
    try:
        ses = gs.Session(port=port, owner=_proof(proc.pid, port))
        ses.dial()
        assert ses.local_port is not None
        assert heard(proc) == "b'+'"
        ses.close()
    finally:
        proc.kill()
        proc.wait()


@QUEUED_UNOWNED
def test_a_connection_nobody_accepts_is_not_accepted_at_the_deadline() -> None:
    """A queued connection has no owner until accepted: the deadline is `StubNotAccepted`."""
    proc, port = listener("hold")
    try:
        began = time.monotonic()
        ses = gs.Session(port=port, owner=_proof(proc.pid, port, seconds=0.5))
        with pytest.raises(owner.StubNotAccepted) as e:
            ses.dial()
        assert time.monotonic() - began >= 0.5
        assert "no process accepted it" in str(e.value) and ses.local_port is None
    finally:
        proc.kill()
        proc.wait()


@QUEUED_UNOWNED
def test_a_mame_that_dies_before_it_accepts_ends_the_wait_as_a_death() -> None:
    """`MameGone`, an `OSError` the boot reads as a death, long before the deadline."""
    proc, port = listener("hold")
    dead = threading.Event()
    try:
        proof = owner.StubOwner(pid=proc.pid, port=port, deadline=time.monotonic() + 30,
                                alive=lambda: not dead.is_set())
        ses = gs.Session(port=port, owner=proof)
        threading.Timer(0.3, dead.set).start()
        began = time.monotonic()
        with pytest.raises(owner.MameGone) as e:
            ses.dial()
        assert isinstance(e.value, OSError) and time.monotonic() - began < 5
    finally:
        proc.kill()
        proc.wait()


@LSOF
def test_an_absent_lsof_is_a_host_that_cannot_prove_never_nobody_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(owner.StubUnproved) as e:
        owner.listeners(1)
    assert "`lsof` is not on this host's PATH" in str(e.value)


@LSOF
@pytest.mark.parametrize(("rc", "stderr"), [(1, "lsof: unsupported option"), (2, "")])
def test_an_lsof_that_complains_or_fails_is_unproved_never_an_empty_answer(
    monkeypatch: pytest.MonkeyPatch, rc: int, stderr: str,
) -> None:
    """`lsof` answers 1 for "no match" and for a failure: stderr tells them apart."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], rc, stdout="", stderr=stderr))
    with pytest.raises(owner.StubUnproved) as e:
        owner.listeners(1)
    assert f"exit code {rc}" in str(e.value)


@LSOF
def test_a_hung_lsof_is_unproved(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired("lsof", owner.LSOF_TIMEOUT_S)

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(owner.StubUnproved) as e:
        owner.listeners(1)
    assert "could not be run" in str(e.value) and "timed out" in str(e.value)


@LSOF
def test_accepted_by_reads_the_far_end_and_skips_this_process_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In `lsof -Fpn` output the pair owning the stub port, peered to ours, is the far end."""
    lines = "p10\nf3\nn127.0.0.1:5000->127.0.0.1:6000\np20\nf4\nn127.0.0.1:6000->127.0.0.1:5000\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout=lines, stderr=""))
    assert owner.accepted_by(5000, 6000) == {10}
    assert owner.accepted_by(5000, 6001) == set()


def _captured_table(family: str) -> bytes:
    rows = [bytes.fromhex(r) for r in CAPTURED["rows"][family]]
    return len(rows).to_bytes(4, "little") + b"".join(rows)


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Windows branch on any host, its TCP table the captured one."""
    tables = {socket.AF_INET: _captured_table("v4"), socket.AF_INET6: _captured_table("v6")}
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(owner, "_tcp_table", lambda family: tables[family])


def test_the_captured_table_reads_as_the_probe_held_it() -> None:
    pid, p4, p6, near = (CAPTURED[k] for k in ("pid", "listen4", "listen6", "client_local"))
    v4 = owner.tcp_rows(_captured_table("v4"), socket.AF_INET)
    assert v4 == [owner.TcpRow(owner.TCP_LISTEN, p4, 0, pid),
                  owner.TcpRow(owner.TCP_ESTABLISHED, p4, near, pid),
                  owner.TcpRow(owner.TCP_ESTABLISHED, near, p4, pid)]
    v6 = owner.tcp_rows(_captured_table("v6"), socket.AF_INET6)
    assert v6 == [owner.TcpRow(owner.TCP_LISTEN, p6, 0, pid)]


@pytest.mark.usefixtures("on_windows")
def test_on_windows_the_table_names_the_listener_and_the_far_end_of_a_connection() -> None:
    pid, p4, p6, near = (CAPTURED[k] for k in ("pid", "listen4", "listen6", "client_local"))
    assert owner.listeners(p4) == {pid} and owner.listeners(p6) == {pid}
    assert owner.listeners(near) == set(), "a connection's end is no listener"
    assert owner.accepted_by(p4, near) == {pid}
    assert owner.accepted_by(p4, near + 1) == set(), "another connection's far end"


@pytest.mark.usefixtures("on_windows")
def test_on_windows_a_port_only_a_connection_holds_is_not_free() -> None:
    """Windows binds such a port, so a bind alone would call a served session free."""
    assert owner.bind_probe(CAPTURED["client_local"]) is None
    free = _free_port()
    assert owner.bind_probe(free) == free, "the control: a port in no row binds"


@pytest.mark.parametrize("table", [b"", b"\x02\x00\x00\x00" + bytes(24)])
def test_a_tcp_table_shorter_than_it_says_is_unproved(table: bytes) -> None:
    with pytest.raises(owner.StubUnproved, match="the TCP table claims"):
        owner.tcp_rows(table, socket.AF_INET)


@pytest.mark.skipif(sys.platform == "win32", reason="this host reads it")
def test_on_another_host_the_tcp_table_is_never_read() -> None:
    with pytest.raises(owner.StubUnproved, match="on Windows only"):
        owner._tcp_table(socket.AF_INET)
