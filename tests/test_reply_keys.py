"""One spelling per reply key: where two tools answer one concept, the key and its shape are the
ones a precedent already gave it, and a row of one kind carries every key of its kind. Each case
reads the reply a caller reads and asserts the new key present and the old one gone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server_support import _running  # noqa: E402
from session_doubles import IDENTITY_KEYS, ref_cpu  # noqa: E402
from test_address_rule import _stale_raw_and_unshowable_symbol  # noqa: E402
from test_comments import MAIN  # noqa: E402
from test_tally import _survey, _tallying  # noqa: E402
from test_watches import _watching  # noqa: E402

import mame_recording as mrec
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


def test_the_comments_re_arm_lists_rows_as_the_declarations_re_arm_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    out = _stale_raw_and_unshowable_symbol(monkeypatch, tmp_path)
    assert ref_cpu(out["stale"]) == [("0x900", MAIN)] and set(out["stale"][0]) == IDENTITY_KEYS, out
    assert out["rearmed"] == [] and out["unresolved"] == [], out
    (unarmable,) = out["unarmable"]
    assert set(unarmable) == IDENTITY_KEYS | {"why"} and unarmable["ref"] == "irq_vblank", out


def test_every_list_tool_names_its_cpu_unavailable_when_none_was_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _watching(monkeypatch, tmp_path)
    for reply in (s.declaration_list("breakpoint"), s.declaration_list("watch"),
                  s.declaration_list("regpoint")):
        assert reply["cpu"] == {"available": False, "why": mstate.NO_CPU_NAMED_WHY}, reply


def test_a_capture_row_carries_every_key_of_its_kind_null_once_the_file_is_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _running(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "captures", [("avi", str(tmp_path / "gone.avi")),
                                                   ("wav", str(tmp_path / "gone.wav"))])
    avi, wav = s.captures()["captures"]
    gone = {"available": False, "why": "the file is gone"}
    assert avi["present"] is False and avi["avi_frames"] == gone and "frames" not in avi, avi
    assert wav["present"] is False, wav
    assert (wav["samples"], wav["channels"], wav["sample_rate_hz"]) == (gone,) * 3, wav


def test_a_recording_not_begun_says_why_its_begin_is_not_read(tmp_path: Path) -> None:
    ran = {"status": "ok", "session": {}}
    out = mrec._not_begun(ran, "record", {"frame": "60", "vblank": "false"}, tmp_path / "r.avi",
                         30, 29, ())
    assert out["began"] is False and out["frame_begin"]["available"] is False, out
    assert out["recording_after"]["available"] is False, out


def test_a_taps_address_has_the_one_spelling_every_address_has(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _tallying(monkeypatch, tmp_path)
    assert s.watch_add(ref="frame_lo", mode="count", length=4)["status"] == "ok"
    assert _survey(ses, 1)["addr"] == "0x002031fc"


def test_perform_names_the_visible_cpu_as_debug_does_and_keeps_its_account_apart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`visible_cpu` is a tag in every reply, `debug`'s and `perform`'s alike: the cpu visible
    after the list; how the list kept it is `visible_cpu_kept`."""
    from test_perform_per_cpu import SUB, _patched
    _patched(monkeypatch, tmp_path)
    out = s.perform(steps=[{"op": "focus", "cpu": "subcpu"}, {"op": "registers"}])
    assert out["visible_cpu"] == SUB, out
    assert out["visible_cpu_kept"]["asked"] == SUB and out["visible_cpu_kept"]["after"] == SUB


def test_a_reading_older_than_the_stop_is_superseded_and_never_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`stale` is a raw declaration of another build (a `state`); a reading older than the last
    stop is `superseded`, so one reply never says `stale` for two things."""
    from test_reply_cpu import _sub_visible
    _sub_visible(monkeypatch, tmp_path)
    out = s.registers(from_last_stop=True)
    assert out["superseded"] is True and "stale" not in out, out


def test_drive_carries_the_tag_and_the_account_under_its_act(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`drive` runs its act through `perform`'s machinery, so its `act` says the same two keys."""
    from test_perform_per_cpu import SUB, _patched
    _patched(monkeypatch, tmp_path)
    out = s.drive(act=[{"op": "focus", "cpu": "subcpu"}, {"op": "registers"}])
    act = out["act"]
    assert act["visible_cpu"] == SUB and act["visible_cpu_kept"]["after"] == SUB, out


def test_a_superseded_tap_says_so_in_its_summary() -> None:
    import mame_summaries as summaries
    reply = {"palette_port": ":ramdac", "frame_as_of": 7, "writes_total": 2,
             "pens_written": ["0x01"],
             "rows_kept": 2, "overflow_rows": 0}
    assert "(superseded)" not in summaries.palette_log({}, {**reply, "superseded": False})
    assert "frame 7 (superseded):" in summaries.palette_log({}, {**reply, "superseded": True})
