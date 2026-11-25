"""`presence`: which tools drive, held against the registry; the drawer chunk the boot script
carries only when presence is on, drawing on the UI container from the one look; the state file
replaced whole; and what `start` and `status` say of it."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from lua_text import has, squash
from scry_core import overlay, presence

from scry_mame import launch  # noqa: E402
from scry_mame import presence as mpresence  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


def test_every_registered_tool_is_declared_driving_or_still_and_no_other() -> None:
    registered = {t.name for t in asyncio.run(s.mcp.list_tools())}
    assert presence.check_classified(registered, mpresence.DRIVING_TOOLS,
                                     mpresence.STILL_TOOLS) == []


def test_the_drawer_rides_the_boot_script_only_when_presence_is_on(tmp_path: Path) -> None:
    off = Path(launch.boot_harness(tmp_path, "", 0)).read_text(encoding="utf-8")
    on = Path(launch.boot_harness(tmp_path, "", 0, presence=True)).read_text(encoding="utf-8")
    assert "register_frame_done" not in off and on.startswith(off)
    assert on[len(off):] == mpresence.drawer(tmp_path)


def test_the_drawer_draws_on_the_ui_container_from_the_look_and_reads_its_file(
        tmp_path: Path) -> None:
    look = presence.Look(rgb=0x123456, edge=0.05, steps=3, acting_alpha=0.9, held_share=0.5,
                         fade_s=1.5)
    text = mpresence.drawer(tmp_path / 'a"b', look)
    assert "render.ui_container" in text and "screens[" not in text
    assert has(text, "local RGB, EDGE, STEPS = 0x123456, 0.05, 3")
    assert has(text, f"local ACTING, HELD, FADE, REREAD = 0.9, 0.45, 1.5, {mpresence.REREAD_S!r}")
    assert has(text, f"local REC_RGB, BLINK = 0x{presence.LOOK.record_rgb:06X}, "
                     f"{presence.LOOK.record_blink_s!r}")
    assert has(text, 'execution_state == "run"'), "a stopped machine is never drawn a fade"
    state = str(tmp_path / 'a"b' / mpresence.STATE_FILE)
    assert has(text, '"' + state.replace("\\", "\\\\").replace('"', '\\"') + '"')
    assert text.startswith("local path, broke = ")
    assert has(text, "local set_up, why = pcall(function()")
    assert squash(text).endswith(squash("if not set_up then stopped(why) end")), \
        "a drawer that could not be set up writes why, as one that raised does"


def test_a_state_replaces_the_file_whole(tmp_path: Path) -> None:
    adapter = made(tmp_path)
    adapter.show("held", presence.Payload(layers=("edge", "record"), recording="video"))
    adapter.show("acting", presence.Payload())
    assert (tmp_path / mpresence.STATE_FILE).read_text().splitlines()[0] == "acting"
    assert "rec=" not in (tmp_path / mpresence.STATE_FILE).read_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == [mpresence.STATE_FILE]


def test_the_state_file_carries_the_layers_and_what_is_recorded() -> None:
    text = mpresence.encode("acting", presence.Payload(
        layers=("edge", "pointer", "record"), recording="video"))
    assert text.splitlines() == ["acting", "layers=edge,record", "rec=video"]
    bare = mpresence.encode("held", presence.Payload())
    assert bare.splitlines() == ["held", "layers=edge"]


@pytest.mark.parametrize("recording", ["video", "audio", "both"])
def test_the_state_file_says_what_is_being_recorded(recording: presence.Recording) -> None:
    text = mpresence.encode("held", presence.Payload(layers=("edge", "record"),
                                                     recording=recording))
    assert text.splitlines() == ["held", "layers=edge,record", f"rec={recording}"]


def test_the_drawer_takes_the_recording_mark_s_colour_and_period_from_the_look(
        tmp_path: Path) -> None:
    look = presence.Look(record_rgb=0x123456, record_blink_s=2.5)
    assert has(mpresence.drawer(tmp_path, look), "local REC_RGB, BLINK = 0x123456, 2.5")


def test_the_reply_names_the_layers_drawn_and_says_why_mame_has_no_pointer() -> None:
    assert mpresence.overlay_reply(overlay.OVERLAY) == {
        "layers": ["edge", "record"],
        "lacking": {"pointer": mpresence.LACKING["pointer"]},
        "notes": mpresence.STOPPED_LIMITS}
    off = overlay.Overlay(record=False)
    assert mpresence.overlay_reply(off) == {
        "layers": ["edge"], "lacking": {"pointer": mpresence.LACKING["pointer"]}}


def test_status_and_start_say_what_the_session_holds() -> None:
    state = mstate.State()
    assert state.presence_shown() is False
    state.presence = presence.Shown(refused={"available": False, "why": "x"})
    assert state.presence_shown() == {"available": False, "why": "x"}

    class Drawn:
        def reply(self) -> bool:
            return True
    state.presence = presence.Shown(held=Drawn())  # type: ignore[arg-type]
    assert state.presence_shown() is True


def test_kill_closes_the_presence_and_forgets_it(tmp_path: Path) -> None:
    state = mstate.State()
    state.presence = presence.Presence.open(made(tmp_path),
                                            mpresence.DRIVING_TOOLS)
    p = state.presence.held
    assert p is not None and state.presence_shown() is True
    state.kill(grace=False)
    assert not p._thread.is_alive()
    assert state.presence == presence.Shown() and state.presence_shown() is False


def test_a_drawer_that_stopped_is_said_in_place_of_true(tmp_path: Path) -> None:
    state = mstate.State()
    state.presence = presence.Presence.open(made(tmp_path),
                                            mpresence.DRIVING_TOOLS)
    state.scratch = tmp_path
    assert state.presence_shown() is True and mpresence.broken(tmp_path) == ""
    (tmp_path / mpresence.BROKEN_FILE).write_text("attempt to index a nil value (ui_target)")
    assert state.presence_shown() == {
        "available": False, "why": "the drawer stopped: attempt to index a nil value (ui_target)"}
    (tmp_path / mpresence.BROKEN_FILE).write_text("")
    assert mpresence.broken(tmp_path) == "no reason given"
    state.presence.close()


def test_a_mame_that_exited_is_said_in_place_of_true(tmp_path: Path) -> None:
    state = mstate.State()
    state.presence = presence.Presence.open(made(tmp_path),
                                            mpresence.DRIVING_TOOLS)

    class Exited:
        def poll(self) -> int:
            return 0
    state.proc = Exited()  # type: ignore[assignment]
    said_now = state.presence_shown()
    assert isinstance(said_now, dict) and said_now["available"] is False, said_now
    state.presence.close()


class _Console:
    """A session double: whether it runs, and every console command it was sent."""

    def __init__(self, running: bool = False) -> None:
        self.running: bool = running
        self.broken: str | None = None
        self.sent: list[str] = []

    def monitor_owed(self, command: str, timeout: float = 10.0) -> None:
        self.sent.append(command)


class _Alive:
    def poll(self) -> None:
        return None


def _session(monkeypatch: Any, scratch: Path, ses: _Console) -> mpresence.FileAdapter:
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "proc", _Alive())
    monkeypatch.setattr(mstate.STATE, "scratch", scratch)
    return made(scratch)


def made(scratch: Path, pending: Any = None) -> mpresence.FileAdapter:
    """The adapter `start` makes, over the server's lock and session; `pending` stands in for
    the console's queue."""
    from scry_mame import transport
    return mpresence.FileAdapter(scratch, mstate.LOCK, mstate.STATE.repaintable,
                                 pending or transport.pending_lines)


def test_the_repaint_sends_one_console_command_to_a_stopped_machine_under_the_lock(
        monkeypatch: Any, tmp_path: Path) -> None:
    ses = _Console()
    held: list[bool] = []

    def still() -> bool:
        held.append(mstate.LOCK.held_here())
        return True
    _session(monkeypatch, tmp_path, ses).repaint(still)
    assert ses.sent == [mpresence.REPAINT] and held[-1] is True


def test_the_repaint_sends_nothing_to_a_running_broken_gone_or_other_session(
        monkeypatch: Any, tmp_path: Path) -> None:
    for field, value in (("running", True), ("broken", "the channel lost its place")):
        ses = _Console()
        setattr(ses, field, value)
        _session(monkeypatch, tmp_path, ses).repaint(lambda: True)
        assert ses.sent == []
    ses = _Console()
    _session(monkeypatch, tmp_path, ses)
    made(tmp_path / "another").repaint(lambda: True)
    assert ses.sent == [], "a writer left over from another session repaints nothing"
    monkeypatch.setattr(mstate.STATE, "ses", None)
    made(tmp_path).repaint(lambda: True)


def test_a_repaint_waits_for_a_call_holding_the_lock_and_gives_up_when_it_frees_moot(
        monkeypatch: Any, tmp_path: Path) -> None:
    import threading

    ses = _Console()
    adapter = _session(monkeypatch, tmp_path, ses)
    still = threading.Event()
    still.set()
    mstate.LOCK.acquire()
    worker = threading.Thread(target=adapter.repaint, args=(still.is_set,))
    worker.start()
    worker.join(0.3)
    assert worker.is_alive() and ses.sent == [], "it waits while a call holds the lock"
    still.clear()                             # a driving call began: the repaint is moot
    worker.join(0.3)
    assert worker.is_alive(), "it sleeps until the lock frees, asking nothing meanwhile"
    mstate.LOCK.release()
    worker.join(2)
    assert not worker.is_alive() and ses.sent == [], "freed, it finds itself moot"


class _Exited:
    def poll(self) -> int:
        return 0


def test_the_repaint_sends_nothing_to_a_machine_that_exited_or_with_a_lua_line_pending(
        monkeypatch: Any, tmp_path: Path) -> None:
    ses = _Console()
    adapter = _session(monkeypatch, tmp_path, ses)
    monkeypatch.setattr(mstate.STATE, "proc", _Exited())
    adapter.repaint(lambda: True)
    assert ses.sent == []
    monkeypatch.setattr(mstate.STATE, "proc", _Alive())
    made(tmp_path, pending=lambda scratch: 1).repaint(lambda: True)
    assert ses.sent == [], "a console command would have MAME evaluate the queued line"
    made(tmp_path, pending=lambda scratch: 0).repaint(lambda: True)
    assert ses.sent == [mpresence.REPAINT]


def test_a_repaint_sends_once_and_not_at_all_when_it_went_moot_under_the_lock(
        monkeypatch: Any, tmp_path: Path) -> None:
    ses = _Console()
    adapter = _session(monkeypatch, tmp_path, ses)
    answers = iter([True, True, True, True])
    adapter.repaint(lambda: next(answers))
    assert ses.sent == [mpresence.REPAINT], "one command, then done"
    moot = iter([True, False])               # true at the door, false once the lock is held
    adapter.repaint(lambda: next(moot))
    assert ses.sent == [mpresence.REPAINT]


def test_a_repaint_during_a_still_call_asks_whether_it_is_due_only_when_the_lock_frees(
        monkeypatch: Any, tmp_path: Path) -> None:
    """A still call holds the lock for as long as it waits (a `log_wait` of minutes): the repaint
    sleeps until it ends, never waking twenty times a second to ask."""
    import threading
    import time

    ses = _Console()
    adapter = _session(monkeypatch, tmp_path, ses)
    asked: list[float] = []

    def still() -> bool:
        asked.append(time.monotonic())
        return True

    mstate.LOCK.acquire()
    worker = threading.Thread(target=adapter.repaint, args=(still,))
    worker.start()
    time.sleep(0.5)
    mstate.LOCK.release()
    worker.join(2)
    assert not worker.is_alive() and ses.sent == [mpresence.REPAINT]
    assert len(asked) <= 4, f"asked {len(asked)} times while the lock was held"


def test_a_repaint_that_runs_out_is_the_presence_s_failure_and_never_breaks_the_session(
        monkeypatch: Any, tmp_path: Path) -> None:
    """The repaint is a display path: a console that does not answer it fails the presence, and
    the session stays whole (its answer is collected by the next request)."""
    from scry_mame import gdb_session as gs

    class _Silent(_Console):
        def monitor_owed(self, command: str, timeout: float = 10.0) -> None:
            super().monitor_owed(command, timeout)
            raise gs.Timeout("no answer within 10.0 s")

    ses = _Silent()
    with pytest.raises(gs.Timeout):
        _session(monkeypatch, tmp_path, ses).repaint(lambda: True)
    assert ses.broken is None and ses.sent == [mpresence.REPAINT]


class _Drawn:
    def reply(self) -> bool:
        return True


def test_overlay_is_in_the_reply_only_with_a_presence_that_is_on() -> None:
    state = mstate.State()
    assert state.overlay_field() == {}
    state.overlay = overlay.Overlay(pointer=True)
    assert state.overlay_field() == {}, "no presence, nothing drawn to describe"
    state.presence = presence.Shown(refused={"available": False, "why": "x"})
    assert state.overlay_field() == {}
    state.presence = presence.Shown(held=_Drawn())  # type: ignore[arg-type]
    assert state.overlay_field() == {"overlay": {
        "layers": ["edge", "record"],
        "lacking": {"pointer": mpresence.LACKING["pointer"]},
        "notes": mpresence.STOPPED_LIMITS}}


def test_the_session_holds_the_machine_stopped_only_while_alive_whole_and_not_running() -> None:
    class Ses:
        running = False
        broken: str | None = None

    class Proc:
        def __init__(self, code: int | None) -> None:
            self.code = code

        def poll(self) -> int | None:
            return self.code

    state = mstate.State()
    ses = Ses()
    assert state.holds_stopped() is False
    state.ses, state.proc = ses, Proc(None)  # type: ignore[assignment]
    assert state.holds_stopped() is True
    ses.running = True
    assert state.holds_stopped() is False
    ses.running, ses.broken = False, "lost its place"
    assert state.holds_stopped() is False
    ses.broken = None
    state.proc = Proc(0)  # type: ignore[assignment]
    assert state.holds_stopped() is False


def test_start_takes_the_overlay_as_one_object_and_a_profile_may_fill_it() -> None:
    tool = next(t for t in asyncio.run(s.mcp.list_tools()) if t.name == "start")
    assert "overlay" in tool.input_schema["properties"]
    assert "overlay" in s._PROFILE_KEYS
    assert s._START_DEFAULTS["overlay"] == overlay.OVERLAY.model_dump()


def test_a_profile_s_overlay_is_judged_like_a_call_s() -> None:
    assert launch.overlay_argument({"pointer": False}) == overlay.Overlay(pointer=False)
    assert launch.overlay_argument(overlay.OVERLAY) is overlay.OVERLAY
    for bad, said in (({"pointer": "no"}, "overlay.pointer"), ({"edge": True}, "overlay.edge"),
                      ("calls", "overlay")):
        with pytest.raises(mstate.Invalid) as refused:
            launch.overlay_argument(bad)  # type: ignore[arg-type]
        assert refused.value.code == "bad_argument" and said in str(refused.value), bad
