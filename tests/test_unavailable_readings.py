"""A DATUM THAT COULD NOT BE READ IS `{"available": false, "why": ...}` in the place its value
would have taken, never a null beside a sibling: a reader finds the reason where it looked for
the value, and an inapplicable reading differs from an unreadable one only in its `why`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_ramdac import _armed, _loaded  # noqa: E402
from test_watches import STOP_LINE, _watching  # noqa: E402

from scry_mame import ramdac as mramdac  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402


def test_a_change_watch_with_no_earlier_reading_says_why_it_has_no_before(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("00000037")
    s.watch_add(ref="frame_lo", mode="change", length=4)
    for armed in mstate.STATE.armed_watches.values():
        armed["last"] = None                     # nothing read since it was armed
    (tmp_path / "debug.log").write_text("F2034\n" + "Data dumped successfully\n")
    s.resume()
    (tmp_path / "debug.log").open("a").write(STOP_LINE + "25F6\n")
    ses.memory[0x2031FC] = bytes.fromhex("00000038")
    ses.next_packet = "T05watch:2031fc;0e:00000000;11:0000040e;"
    ses.stops_after_polls = 1
    s.status()
    hit = mstate.STATE.last_stop["watch_hit"]
    assert hit["after"] == 0x38, hit
    assert hit["before"]["available"] is False and "none was read" in hit["before"]["why"], hit


def test_a_pen_the_log_never_saw_written_says_so_in_its_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _loaded(monkeypatch, tmp_path)
    _armed(ses)
    real = mramdac.parse_dump

    def without_the_last_pen(*a: Any, **k: Any) -> Any:
        dump: Any = real(*a, **k)
        dump["pens"] = {key: p for key, p in dump["pens"].items() if p.pen != 255}
        return dump

    monkeypatch.setattr(mramdac, "parse_dump", without_the_last_pen)
    written = s.palette_log(palette_port="ramdac")["pens_written"]
    out = s.palette_log(palette_port="ramdac", pen=255)
    assert out["status"] == "ok" and written == ["0x0-0xfe"], (written, out)
    assert out["pen_state"]["available"] is False, out["pen_state"]
    assert "no write of pen 255" in out["pen_state"]["why"], out["pen_state"]
