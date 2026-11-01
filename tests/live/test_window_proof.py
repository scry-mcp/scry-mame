"""The window MAME's `start` proves, read from the host's own window list, on any host: it is on the
asked display and shown, `window` says where the host lists it, and `fullscreen` either fills the
display or is refused by name. Opens windows (`-m window`); a host with one display cannot ask for
display 1, and those cases skip naming that."""

from __future__ import annotations

import os
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from scry_core import window as core_window

from scry_mame import launch
from scry_mame import server as s

BINARY = os.environ.get("MAME_BINARY", "")
ROMS = os.environ.get("MAME_TEST_ROMS", "")
NEEDS = pytest.mark.skipif(not (BINARY and ROMS), reason="set MAME_BINARY and MAME_TEST_ROMS")
pytestmark = [pytest.mark.live, pytest.mark.window, NEEDS]


def _start(tmp_path: Path, **window: Any) -> dict[str, Any]:
    image = tmp_path / "circus.ref"
    with zipfile.ZipFile(Path(ROMS) / "circus.zip") as z:
        image.write_bytes(z.read("9004a.1a"))
    ini = tmp_path / "ini"
    ini.mkdir()
    (ini / "mame.ini").write_text("joystickprovider none\n")
    return cast(dict[str, Any], s.start(
        binary=BINARY, system="circus", rompath=ROMS, reference_rom=str(image),
        reference_addr="0x1000", reference_base="0x1000", boot_seconds=30.0, presence=False,
        inipath=str(ini), background=True, **window))


@pytest.fixture
def closing() -> Iterator[None]:
    yield
    s.close()


def _listed(pid: int) -> core_window.Seen | None:
    return core_window.main_window(pid, core_window.host().windows())


def _displays() -> list[core_window.Display]:
    return core_window.host().displays()


@pytest.mark.usefixtures("closing")
@pytest.mark.parametrize("display", [0, 1])
def test_a_watched_start_is_listed_on_the_display_it_asked(tmp_path: Path, display: int) -> None:
    shown = _displays()
    if display >= len(shown):
        pytest.skip(f"this host has {len(shown)} display(s): display {display} does not exist")
    got = _start(tmp_path, shared=True, display=display)
    assert got["status"] == "ok", got
    block = got["window"]
    assert block["display"] == display and block["onscreen"] is True, block
    listed = _listed(got["pid"])
    x, y, w, h = shown[display].bounds
    assert listed is not None and listed.onscreen
    assert block["fullscreen"] is False and listed.bounds != shown[display].bounds
    assert x <= listed.bounds[0] < x + w and y <= listed.bounds[1] < y + h, (listed, shown)
    said = cast(dict[str, Any], s.window())["window"]["bounds"]
    assert (said["x"], said["y"], said["width"], said["height"]) == listed.bounds


@pytest.mark.usefixtures("closing")
def test_an_unwatched_start_has_no_channel_for_window(tmp_path: Path) -> None:
    """The control: the server placed no window, so it proves none."""
    got = _start(tmp_path, shared=False)
    assert got["status"] == "ok", got
    refused = cast(dict[str, Any], s.window())
    assert refused["status"] == "INVALID" and refused["code"] == "no_channel", refused


@pytest.mark.usefixtures("closing")
def test_fullscreen_fills_the_display_or_is_refused_by_name(tmp_path: Path) -> None:
    """Where `-nowindow` was measured not to fill the display the start is refused naming it, up
    front; elsewhere the window either fills the display or the start says it did not."""
    got = _start(tmp_path, shared=True, display=0, fullscreen=True)
    shown = _displays()[0].bounds
    pid = cast(dict[str, Any], s.status()).get("pid")
    listed = _listed(pid) if isinstance(pid, int) else None
    print(f"\nfullscreen start: status={got['status']} code={got.get('code')} display={shown} "
          f"window={listed.bounds if listed else None} seen={got.get('seen')}")
    if sys.platform in launch.NO_FULLSCREEN_ON:
        assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
        assert "-nowindow" in got["message"] and listed is None, got
    elif got["status"] == "ok":
        assert got["window"]["fullscreen"] is True and listed is not None
        assert listed.bounds == shown
    else:
        assert got["code"] == "window_not_visible", got
