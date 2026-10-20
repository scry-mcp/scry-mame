"""`mame_presence`: which tools drive, held against the registry; the drawer chunk the boot script
carries only when presence is on, drawing on the UI container from the one look; the state file
replaced whole; and what `start` and `status` say of it."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from scry_core import presence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mame_launch as launch  # noqa: E402
import mame_presence as mpresence  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


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
    assert f"local RGB, EDGE, STEPS = {0x123456}, 0.05, 3" in text
    assert f"local ACTING, HELD, FADE, REREAD = 0.9, 0.45, 1.5, {mpresence.REREAD_S!r}" in text
    assert 'execution_state == "run"' in text, "a stopped machine is never drawn a fade"
    assert '"' + str(tmp_path).replace("\\", "\\\\") + '/a\\"b/presence.state"' in text
    assert text.startswith("-- ") and "\npcall(function()" in text


def test_a_state_replaces_the_file_whole(tmp_path: Path) -> None:
    adapter = mpresence.FileAdapter(tmp_path)
    adapter.show("held")
    adapter.show("acting")
    assert (tmp_path / mpresence.STATE_FILE).read_text() == "acting\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [mpresence.STATE_FILE]


def test_status_and_start_say_what_the_session_holds() -> None:
    state = mstate.State()
    assert state.presence_shown() is False
    state.presence_reply = {"available": False, "why": "x"}
    assert state.presence_shown() == {"available": False, "why": "x"}

    class Shown:
        def reply(self) -> bool:
            return True
    state.presence = Shown()  # type: ignore[assignment]
    assert state.presence_shown() is True


def test_kill_closes_the_presence_and_forgets_it(tmp_path: Path) -> None:
    state = mstate.State()
    p, said = presence.Presence.open(mpresence.FileAdapter(tmp_path), mpresence.DRIVING_TOOLS)
    assert p is not None and said is True
    state.presence, state.presence_reply = p, said
    state.kill(grace=False)
    assert not p._thread.is_alive()
    forgotten: object = state.presence      # read after the kill, which mypy cannot see reset it
    assert forgotten is None and state.presence_shown() is False


def test_a_drawer_that_stopped_is_said_in_place_of_true(tmp_path: Path) -> None:
    state = mstate.State()
    p, said = presence.Presence.open(mpresence.FileAdapter(tmp_path), mpresence.DRIVING_TOOLS)
    assert p is not None
    state.presence, state.presence_reply, state.scratch = p, said, tmp_path
    assert state.presence_shown() is True and mpresence.broken(tmp_path) == ""
    (tmp_path / mpresence.BROKEN_FILE).write_text("attempt to index a nil value (ui_target)")
    assert state.presence_shown() == {
        "available": False, "why": "the drawer stopped: attempt to index a nil value (ui_target)"}
    (tmp_path / mpresence.BROKEN_FILE).write_text("")
    assert mpresence.broken(tmp_path) == "no reason given"
    p.close()


def test_a_mame_that_exited_is_said_in_place_of_true(tmp_path: Path) -> None:
    state = mstate.State()
    p, said = presence.Presence.open(mpresence.FileAdapter(tmp_path), mpresence.DRIVING_TOOLS)
    assert p is not None and said is True
    state.presence, state.presence_reply = p, said

    class Exited:
        def poll(self) -> int:
            return 0
    state.proc = Exited()  # type: ignore[assignment]
    said_now = state.presence_shown()
    assert isinstance(said_now, dict) and said_now["available"] is False, said_now
    p.close()
