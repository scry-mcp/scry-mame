"""Whose gdbstub a port serves (`mame_stub_owner`), proved against REAL processes and the real
`lsof`: the property is about which process holds a socket, which no double can stand for."""

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
    """The dial would take the one connection that other MAME serves: refused before it, so the
    other listener's accept times out with nothing (`none`, where a dial closed unread would be
    `b''`)."""
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
    """Two listeners on one port (SO_REUSEPORT allows it): a dial could reach either, so ours
    being among them is not enough."""
    monkeypatch.setattr(owner, "bind_probe", lambda port: None)
    monkeypatch.setattr(owner, "listeners", lambda port: {10, 20})
    with pytest.raises(owner.StubNotOurs) as e:
        _proof(10, 1).before_dial()
    assert e.value.pids == [20]


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
    """A served session's port, listener closed: it does not bind, `lsof` finds no listener,
    and the boot waits for its own MAME to listen there."""
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
    """The race the listener check cannot close: the port looked like ours and the connection
    landed in another process. Closed before the first byte, so that process reads `b''`."""
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
    """THE CONTROL of the case above: the same child named as ours, and the dial goes through,
    its first byte read on the far side."""
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


def test_a_connection_nobody_accepts_is_not_accepted_at_the_deadline() -> None:
    """A connection in the listen queue belongs to no process's files until it is accepted, so
    the proof waits for the accept, and a deadline reached first is `StubNotAccepted`."""
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


def test_a_mame_that_dies_before_it_accepts_ends_the_wait_as_a_death() -> None:
    """Its exit is known at once: `MameGone`, an `OSError` the boot reads as a death, long
    before the deadline."""
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


def test_an_absent_lsof_is_a_host_that_cannot_prove_never_nobody_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(owner.StubUnproved) as e:
        owner.listeners(1)
    assert "`lsof` is not on this host's PATH" in str(e.value)


@pytest.mark.parametrize(("rc", "stderr"), [(1, "lsof: unsupported option"), (2, "")])
def test_an_lsof_that_complains_or_fails_is_unproved_never_an_empty_answer(
    monkeypatch: pytest.MonkeyPatch, rc: int, stderr: str,
) -> None:
    """`lsof` answers 1 for "no match" AND for a failure: stderr is what tells them apart, and
    any other exit code is a failure outright."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], rc, stdout="", stderr=stderr))
    with pytest.raises(owner.StubUnproved) as e:
        owner.listeners(1)
    assert f"exit code {rc}" in str(e.value)


def test_a_hung_lsof_is_unproved(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired("lsof", owner.LSOF_TIMEOUT_S)

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(owner.StubUnproved) as e:
        owner.listeners(1)
    assert "could not be run" in str(e.value) and "timed out" in str(e.value)


def test_accepted_by_reads_the_far_end_and_skips_this_process_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The field lines as `lsof -Fpn` prints them: the pair whose own port is the stub's and
    whose peer is our local port is the far end; the reverse pair is this process's own."""
    lines = "p10\nf3\nn127.0.0.1:5000->127.0.0.1:6000\np20\nf4\nn127.0.0.1:6000->127.0.0.1:5000\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout=lines, stderr=""))
    assert owner.accepted_by(5000, 6000) == {10}
    assert owner.accepted_by(5000, 6001) == set()
