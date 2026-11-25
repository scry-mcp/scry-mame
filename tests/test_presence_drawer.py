"""The presence drawer run for real in Lua 5.4 over a fake MAME world (`tests/lua/`): what it draws
for each state file, with the clock set by the scenario."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import cast

import pytest
from scry_core import overlay as ov
from scry_core import presence

from scry_mame import presence as mpresence

LUA_DIR = Path(__file__).parent / "lua"
WORLD = LUA_DIR / "presence_world.lua"
LUA = ("lua5.4", "/opt/homebrew/opt/lua@5.4/bin/lua5.4", "lua")
Frame = list[list[str]]


def _lua() -> str:
    for name in LUA:
        found = shutil.which(name)
        if found is not None:
            version = subprocess.run([found, "-v"], capture_output=True, text=True,
                                     check=True).stdout
            if version.startswith("Lua 5.4"):
                return found
    pytest.fail("no Lua 5.4 interpreter is installed: the drawer is not run without one")


def state(layers: str = "edge", *, rec: str = "") -> str:
    """A state file as `mpresence.encode` writes it, so the writer and the drawer cannot drift."""
    asked = tuple(cast(ov.Layer, name) for name in layers.split(","))
    return mpresence.encode("held", presence.Payload(
        layers=asked, recording=cast(presence.Recording, rec or "none")))


def run(tmp_path: Path, scenario: str, look: presence.Look = presence.LOOK) -> list[Frame]:
    """The frames `scenario` drew, each a list of primitives split into words. `put(text)`
    writes the state file; `shot(t)` draws a frame at `t` seconds."""
    (tmp_path / "drawer.lua").write_text(mpresence.drawer(tmp_path, look), encoding="utf-8")
    script = tmp_path / "scenario.lua"
    script.write_text(
        f"dofile({lit(str(WORLD))})\ndofile({lit(str(tmp_path / 'drawer.lua'))})\n"
        f"local function put_state(text)\n put({lit(str(tmp_path / mpresence.STATE_FILE))}, text)\n"
        "end\n"
        + scenario, encoding="utf-8")
    done = subprocess.run([_lua(), str(script)], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    frames: list[Frame] = [[]]
    for line in done.stdout.splitlines():
        if line == "--":
            frames.append([])
        else:
            frames[-1].append(line.split(" "))
    return frames[:-1]


def texts(frame: Frame) -> list[str]:
    """What each text primitive drew: after x and y, up to the two colours."""
    return [" ".join(p[3:-2]) for p in frame if p[0] == "text"]


def boxes(frame: Frame) -> int:
    return sum(1 for p in frame if p[0] == "box")


def lit(text: str) -> str:
    """A Lua string literal of `text`."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def test_a_drawer_loaded_twice_draws_once(tmp_path: Path) -> None:
    """MAME runs every registered callback, so a second load that registered again would draw
    each box twice and the semi-transparent edge would darken."""
    body = lit(state())
    once = run(tmp_path, f"put_state({body})\nshot(1.0)\n")
    twice = run(tmp_path, f"dofile({lit(str(tmp_path / 'drawer.lua'))})\n"
                          f"put_state({body})\nshot(1.0)\n")
    assert boxes(twice[0]) == boxes(once[0]) == presence.LOOK.steps * 4


def test_a_state_with_only_the_edge_draws_the_edge_and_nothing_over_it(tmp_path: Path) -> None:
    frames = run(tmp_path, f"put_state({lit(state())})\nshot(1.0)\n")
    assert boxes(frames[0]) == presence.LOOK.steps * 4 and texts(frames[0]) == []


def acted() -> str:
    """A state file with the machine acting, as `mpresence.encode` writes it."""
    return mpresence.encode("acting", presence.Payload(layers=("edge",)))


def _edge_alpha(frame: Frame) -> int:
    """The alpha of the edge's first band, out of the primitive's colour."""
    top = next(p for p in frame if p[0] == "box")
    return int(top[6]) >> 24


def test_the_edge_is_drawn_in_the_band_the_look_names(tmp_path: Path) -> None:
    """The first band's rectangle and colour, from the target's size and the look's edge."""
    look = presence.LOOK
    held, = run(tmp_path, f"put_state({lit(state())})\nshot(0.0)\nshot(3.0)\n")[1:]
    top = next(p for p in held if p[0] == "box")
    assert [float(v) for v in top[1:5]] == pytest.approx(
        [0.0, 0.0, 1.0, look.edge / look.steps])
    assert int(top[6]) == (int(255 * look.held_alpha + 0.5) << 24) | look.rgb


def test_the_edge_fades_from_acting_to_held_while_the_machine_runs(tmp_path: Path) -> None:
    look = presence.LOOK

    def level(alpha: float) -> int:
        return int(255 * alpha + 0.5)
    frames = run(tmp_path, f"put_state({lit(state())})\nshot(0.0)\nshot(3.0)\n"
                f"put_state({lit(acted())})\nhalt(false)\nshot(4.0)\n"
                f"put_state({lit(state())})\nshot(5.0)\nshot(6.0)\nshot(8.0)\n")
    got = [_edge_alpha(frame) for frame in frames]
    assert got[1] == level(look.held_alpha), "the first fade has ended"
    assert got[2] == level(look.acting_alpha), "a call, at its brightest"
    assert got[3] == level(look.acting_alpha), "the change is where the fade starts"
    assert level(look.held_alpha) < got[4] < got[3], "one second into the fade"
    assert got[5] == level(look.held_alpha), "the fade has ended"


RED = presence.LOOK.record_rgb


def red(frame: Frame) -> list[list[str]]:
    """The boxes drawn in the recording mark's colour: the dot."""
    return [p for p in frame if p[0] == "box" and int(p[6]) & 0xFFFFFF == RED]


def extras(frame: Frame) -> int:
    """The primitives drawn beyond the edge's own."""
    return len(frame) - presence.LOOK.steps * 4


def recording(rec: str) -> str:
    return lit(state("edge,record", rec=rec))


def test_a_video_recording_draws_a_red_dot_and_rec_in_the_top_right(tmp_path: Path) -> None:
    (lit_frame,) = run(tmp_path, f"put_state({recording('video')})\nshot(0.0)\n")
    assert texts(lit_frame) == ["REC"]
    assert red(lit_frame)
    assert all(float(p[1]) > 0.5 and float(p[2]) < 0.3 for p in red(lit_frame) + [
        q for q in lit_frame if q[0] == "text"]), red(lit_frame)


def test_an_audio_recording_draws_a_red_dot_and_a_note_and_no_rec(tmp_path: Path) -> None:
    (frame,) = run(tmp_path, f"put_state({recording('audio')})\nshot(0.0)\n")
    (video,) = run(tmp_path, f"put_state({recording('video')})\nshot(0.0)\n")
    assert texts(frame) == [] and red(frame)
    assert extras(frame) > len(red(frame)) + 1, "the note is a drawn shape beside the dot"
    assert len(red(frame)) == len(red(video)), "the same dot in both"


def test_both_recordings_draw_the_dot_rec_and_the_note_in_one_mark(tmp_path: Path) -> None:
    (both,) = run(tmp_path, f"put_state({recording('both')})\nshot(0.0)\n")
    (audio,) = run(tmp_path, f"put_state({recording('audio')})\nshot(0.0)\n")
    (video,) = run(tmp_path, f"put_state({recording('video')})\nshot(0.0)\n")
    assert texts(both) == ["REC"] and len(red(both)) == len(red(video))
    assert extras(both) == extras(video) + extras(audio) - len(red(video)) - 1


def test_the_mark_is_shown_the_first_half_of_each_period_and_the_period_is_the_looks(
        tmp_path: Path) -> None:
    def lit_at(frames: list[Frame]) -> list[bool]:
        return [bool(red(f)) for f in frames]

    first = run(tmp_path, f"put_state({recording('video')})\nshot(0.0)\nshot(0.4)\nshot(0.6)\n"
                "shot(0.9)\nshot(1.1)\nshot(1.6)\n")
    assert lit_at(first) == [True, True, False, False, True, False]
    slow = run(tmp_path, f"put_state({recording('video')})\nshot(0.0)\nshot(0.9)\nshot(1.1)\n"
               "shot(2.1)\n", presence.Look(record_blink_s=2.0))
    assert lit_at(slow) == [True, True, False, True]


def test_a_stopped_machine_keeps_the_mark_lit_and_does_not_blink_it(tmp_path: Path) -> None:
    frames = run(tmp_path, f"put_state({recording('video')})\nshot(0.0)\nhalt(true)\n"
                 "shot(0.6)\nshot(1.6)\n")
    assert [bool(red(f)) for f in frames] == [True, True, True]


def test_no_mark_without_its_layer_or_with_nothing_recording(tmp_path: Path) -> None:
    unasked = lit(state("edge", rec="video"))
    none = lit(state("edge,record", rec="none"))
    quiet = lit(state("edge,record"))
    frames = run(tmp_path, f"put_state({unasked})\nshot(0.0)\nput_state({none})\nshot(0.1)\n"
                 f"put_state({quiet})\nshot(0.2)\n")
    assert all(red(f) == [] and texts(f) == [] for f in frames)
