"""The presence drawer run for real in Lua 5.4 over a fake MAME world (`tests/lua/`): what it draws
for each state file, with the clock and the guest picture set by the scenario."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from scry_core import placement, presence

from scry_mame import presence as mpresence

#: What `tests/lua/presence_world.lua` makes each character measure.
CHAR_WIDTH = 0.01
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


def state(lines: str, *, caption: str = "", keys: tuple[str, ...] = (), layers: str = "edge",
          place: str = "top", paused: bool = False, serial: int = 1, held: str = "held") -> str:
    """A state file as `mpresence.encode` writes it, by hand so the test names each line."""
    body = [held, f"paused={int(paused)}", f"place={place}", f"layers={layers}"]
    if caption:
        body += [f"serial={serial}", "rgb=FF8C00", f"caption={caption}"]
    body += [f"key={k}" for k in keys]
    return "\n".join([*body, lines]).rstrip("\n") + "\n"


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


def fits(frame: Frame) -> bool:
    """Whether the caption's text, as the fake world measures it, ends inside the box behind it
    (the one filled black), whose right edge is its fourth word."""
    (box,) = [p for p in frame if p[0] == "box" and int(p[6]) & 0xFFFFFF == 0 and int(p[6]) > 0]
    text = next(p for p in frame if p[0] == "text")
    return float(text[1]) + len(" ".join(text[3:-2])) * CHAR_WIDTH <= float(box[3]) + 1e-9


def boxes(frame: Frame) -> int:
    return sum(1 for p in frame if p[0] == "box")


def ys(frame: Frame) -> list[float]:
    return [float(p[2]) for p in frame if p[0] == "text"]


def lit(text: str) -> str:
    """A Lua string literal of `text`."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def test_a_state_with_only_the_edge_draws_the_edge_and_nothing_over_it(tmp_path: Path) -> None:
    frames = run(tmp_path, f"put_state({lit(state(''))})\nshot(1.0)\n")
    assert boxes(frames[0]) == presence.LOOK.steps * 4 and texts(frames[0]) == []


def test_a_caption_is_drawn_whole_in_the_band_place_names(tmp_path: Path) -> None:
    said = "read_memory 0x1000 16"
    expected: tuple[tuple[str, Callable[[float], bool]], ...] = (
        ("top", lambda y: y < 0.3), ("bottom", lambda y: y > 0.7))
    for place, expect in expected:
        body = lit(state("", caption=said, layers="edge,calls", place=place))
        frames = run(tmp_path, f"put_state({body})\nshot(0.0)\nshot(1.0)\n")
        assert texts(frames[1]) == [said]
        assert all(expect(y) for y in ys(frames[1])), (place, ys(frames[1]))


def test_a_layer_not_asked_draws_nothing_of_its_own(tmp_path: Path) -> None:
    body = state("", caption="read_memory 1", keys=("P1 Button 1",), layers="edge", paused=True)
    frames = run(tmp_path, f"put_state({lit(body)})\nshot(1.0)\n")
    assert texts(frames[0]) == [] and boxes(frames[0]) == presence.LOOK.steps * 4
    keys_only = state("", caption="read_memory 1", keys=("P1 Button 1",), layers="edge,keys",
                      paused=True)
    shown = run(tmp_path, f"put_state({lit(keys_only)})\nshot(0.0)\nshot(1.0)\n")[1]
    assert texts(shown) == ["P1 Button 1"] and boxes(shown) == presence.LOOK.steps * 4 + 1


def test_keys_are_drawn_by_name_one_cap_each_in_the_second_row(tmp_path: Path) -> None:
    body = state("", caption="log", keys=("P1 Left", "P1 Button 1"), layers="edge,calls,keys")
    frame = run(tmp_path, f"put_state({lit(body)})\nshot(0.0)\nshot(1.0)\n")[1]
    assert texts(frame) == ["log", "P1 Left", "P1 Button 1"]
    row = ys(frame)
    assert row[1] == row[2] > row[0], "the keys sit in their own row, further in than the caption"


def test_a_pause_mark_adds_a_backdrop_and_two_bars_only_while_paused(tmp_path: Path) -> None:
    quiet = state("", layers="edge,pause")
    paused = state("", layers="edge,pause", paused=True)
    first, second = run(tmp_path, f"put_state({lit(quiet)})\nshot(1.0)\n"
                        f"put_state({lit(paused)})\nshot(2.0)\n")
    assert boxes(second) - boxes(first) == 3


def test_a_caption_wider_than_the_band_scrolls_while_running_and_is_cut_while_stopped(
        tmp_path: Path) -> None:
    said = "write_memory 0x1000 " + "00112233445566778899AABBCCDDEEFF" * 4
    body = lit(state("", caption=said, layers="edge,calls"))
    head, later, much_later, halted = run(
        tmp_path, f"put_state({body})\nshot(0.0)\nshot(1.0)\nshot(3.0)\nshot(9.0)\n"
        "halt(true)\nshot(9.5)\n")[1:]
    for frame in (head, later, much_later, halted):
        assert fits(frame), "the text stays inside its box"
    shown = [texts(f)[0] for f in (head, later, much_later)]
    assert shown[0] == said[:len(shown[0])] and len(shown[0]) < len(said)
    assert shown[1] != shown[0] and shown[2] != shown[1], "a running caption moves"
    cut = texts(halted)[0]
    assert cut.endswith("..") and cut[:-2] == said[:len(cut) - 2], "a stopped one is cut"


def test_a_caption_fades_out_when_it_leaves_and_at_once_on_a_stopped_machine(
        tmp_path: Path) -> None:
    kept = lit(state("", caption="log", layers="edge,calls"))
    gone = lit(state("", layers="edge,calls"))
    fading, over = run(tmp_path, f"put_state({kept})\nshot(0.0)\nshot(1.0)\nput_state({gone})\n"
                       "shot(2.0)\nshot(2.1)\nshot(3.0)\n")[3:]
    assert texts(fading) == ["log"] and texts(over) == []
    (halted,) = run(tmp_path, f"put_state({kept})\nshot(0.0)\nshot(1.0)\nhalt(true)\n"
                    f"put_state({gone})\nshot(1.1)\n")[2:]
    assert texts(halted) == []


def test_a_new_caption_with_the_same_text_starts_again(tmp_path: Path) -> None:
    said = "0123456789" * 20
    first = lit(state("", caption=said, layers="edge,calls"))
    again = lit(state("", caption=said, layers="edge,calls", serial=2))
    frames = run(tmp_path, f"put_state({first})\nshot(0.0)\nshot(0.5)\nshot(9.0)\n"
                 f"put_state({again})\nshot(9.1)\nshot(9.5)\n")
    head, scrolled, restarted = frames[1], frames[2], frames[4]
    assert texts(scrolled) != texts(head) == texts(restarted), "it scrolls on, then begins again"


def test_auto_leaves_the_busy_band_after_two_samples_and_never_on_a_still_picture(
        tmp_path: Path) -> None:
    body = lit(state("", caption="log", layers="edge,calls", place="auto"))
    busy = "for x = 0, 319 do for y = 190, 199 do paint(x, y, x * 4099 + y) end end\n"
    still, moved = run(tmp_path, f"put_state({body})\nshot(1.0)\nshot(2.0)\nshot(3.0)\n"
                       f"{busy}shot(4.0)\nshot(5.0)\nshot(6.0)\n")[2::3]
    assert ys(still)[0] > 0.7, "an empty picture keeps the start band"
    assert ys(moved)[0] < 0.3, "a busy bottom band sends the caption to the top"


def test_the_placement_functions_replay_scry_core_s_vectors(tmp_path: Path) -> None:
    source = mpresence.placement_lua()
    driver = tmp_path / "replay.lua"
    queries = [line for line in placement.vectors_file().splitlines()
               if line and not line.startswith("#")]
    # The committed walks never sample a difference of exactly the margin twice in a row.
    edge: list[tuple[placement.Band, list[tuple[int, int]]]] = [
        ("bottom", [(6, 10), (6, 10)]), ("top", [(10, 6), (10, 6)]),
        ("bottom", [(6, 10), (5, 10)])]
    queries += [f"walk {band} " + " ".join(f"{t}/{b}" for t, b in scores) + " = "
                + " ".join(placement.walk(scores, band)) for band, scores in edge]
    driver.write_text(source + (LUA_DIR / "placement_replay.lua").read_text(encoding="utf-8"),
                      encoding="utf-8")
    done = subprocess.run([_lua(), str(driver)], input="\n".join(queries) + "\n",
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == queries



def busy_columns(first: int, last: int) -> str:
    return f"for x = {first}, {last} do for y = 0, 199 do paint(x, y, x + y) end end"


def busy_rows(first: int, last: int) -> str:
    return f"for x = 0, 319 do for y = {first}, {last} do paint(x, y, x + y) end end"


def test_auto_reads_a_rotated_or_flipped_picture_as_the_window_shows_it(tmp_path: Path) -> None:
    """The picture is 320 x 200 raw. The band that is busy lies where the turn puts the window's
    bottom: raw columns for a quarter turn, raw rows for a half turn or a vertical flip."""
    cases = (
        ("orient(90, false, false)", busy_columns(280, 319)),
        ("orient(270, false, false)", busy_columns(0, 39)),
        ("orient(180, false, false)", busy_rows(0, 24)),
        ("orient(0, false, true)", busy_rows(0, 24)),
    )
    body = lit(state("", caption="log", layers="edge,calls", place="auto"))
    for turn, busy in cases:
        moved = run(tmp_path, f"{turn}\nput_state({body})\nshot(1.0)\n{busy}\nshot(2.0)\n"
                    "shot(3.0)\nshot(4.0)\n")[3]
        assert ys(moved)[0] < 0.3, f"{turn}: a busy bottom of the window sends the caption up"


def test_a_screen_with_no_visible_area_leaves_the_drawer_running(tmp_path: Path) -> None:
    body = lit(state("", caption="log", layers="edge,calls", place="auto"))
    frames = run(tmp_path, f"resize(0, 0)\nput_state({body})\nshot(1.0)\nshot(2.0)\nshot(3.0)\n")
    assert all(not any(p[0] == "logerror" for p in f) and boxes(f) for f in frames)
