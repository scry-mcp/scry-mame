"""The conditioned film (`film`, `gfx_film`): arming it, reading what it wrote, and the sheet,
the per-frame files, the listing and the animation it answers with.

THE m68k-dual CASE IS CAPTURED, on its own build through this server: stopped at frame
898, a capture declared on the blitter (`0x700000`, 32 bytes, trigger `0x70001e`) and a film armed
on the strobe (`0x70001e`, 2 bytes, `0xffff`, keep 3, frames 12), then run 14 frames. The arming
chunk's answer and files are `arm-m68k-dual.*`; `film.txt` is the header the film wrote and
`frame-1.*`, `frame-2.*` the first two kept frames as the notifier left them (frames 900 and 901,
each read at the next frame); `capture-m68k-dual-rows.gz` the capture's rows of frames 899..902.
`arm-circus.*` is the arming on the stock `circus` at frame 600, where MAME's snapshot is not
the bare screen: it holds colours none of the screen's two pens does. `MAP_BLIT` is the
console's `map 0x70001e` on m68k-dual.
"""

from __future__ import annotations

import contextlib
import dataclasses
import gzip
import json
import re
import sys
from array import array
from pathlib import Path
from typing import Any

import png_read  # noqa: E402
import pytest
from lua_support import _channel, _ChannelSession  # noqa: E402
from scry_core import picture  # noqa: E402
from session_doubles import MAP_ROM, io_board, refused, use_table  # noqa: E402
from test_callbacks import assert_every_callback_guarded  # noqa: E402

from scry_mame import callbacks as mcallbacks
from scry_mame import film as mf  # noqa: E402
from scry_mame import (
    font,  # noqa: E402
    transport,  # noqa: E402
)
from scry_mame import screen as mscreen
from scry_mame import server as s  # noqa: E402
from scry_mame import sheet as msheet  # noqa: E402
from scry_mame import state as mstate  # noqa: E402
from scry_mame import tap as mtap  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "film"
MAP_BLIT = ("   Read: 70001E logical program == 70001E physical program -> unmapped\n"
            "  Write: 70001E logical program == 70001E physical program -> "
            "m68k_dual_state::blit_w\n"
            "  Fetch: 70001E logical program == 70001E physical program -> unmapped\n\n")
BLIT_PROGRAM = 0x2004


UNCOMPARED = {"available": False,
              "why": "the snapshot and the screen differ in size, so no pixel was compared"}


def _gz(name: str) -> bytes:
    return gzip.decompress((FIX / f"{name}.gz").read_bytes())


def _edited(text: str, old: str, new: str) -> str:
    """`text` with `old` replaced by `new` exactly once: an edit that matched nothing would test
    the capture under the edit's name."""
    assert text.count(old) == 1, f"the edit {old!r} does not match exactly once"
    return text.replace(old, new)


def _session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _ChannelSession:
    """The channel double, answering `map` as m68k-dual's console does for the strobe."""
    ses = _channel(monkeypatch, tmp_path)
    plain = ses.monitor

    def monitor(command: str, timeout: float = 10.0) -> str:
        if command.startswith("map "):
            ses.commands.append(command)
            return MAP_BLIT
        return plain(command, timeout)

    monkeypatch.setattr(ses, "monitor", monitor)
    use_table(monkeypatch, table={"BLIT_PROGRAM": BLIT_PROGRAM})
    return ses


def _serve_arm(ses: _ChannelSession, board: str, snap: bytes | None = None) -> None:
    """The next chunk answers what the arming on `board` printed, and finds its two files where
    it would have written them; `snap` stands in for the captured snapshot."""
    seq = mstate.STATE.lua_seq + 1
    text = (FIX / f"arm-{board}.txt").read_bytes()
    ses.answers[seq] = re.sub(rb"MAME_MCP_LUA_END#\d+", b"MAME_MCP_LUA_END#%d" % seq, text)
    (ses.scratch / f"screen-{seq}.bin").write_bytes(_gz(f"arm-{board}-screen-bin"))
    (ses.scratch / f"screen-{seq}-snap.bin").write_bytes(
        _gz(f"arm-{board}-snap-bin") if snap is None else snap)


def _armed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kw: Any) -> dict[str, Any]:
    """The film armed as the capture was, its install answered, and its record."""
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual")
    out = s.gfx_film(**{"trigger": "0x70001e", "length": 2, "value": 0xFFFF, "keep": 3,
                        "frames": 12, **kw})
    assert out["status"] == "ok", out
    found = mf.held()
    assert found is not None
    rec = found[1]
    rec.update(installed=True, cpu=":maincpu")
    return rec


def _current(frame_txt: str) -> str:
    """A captured frame file in the notifier's current format. The captures predate the count
    of skipped frames a picture waited out; they were taken without frameskip, where it is 0,
    which is the one thing this adds to them."""
    head, sep, rest = frame_txt.partition("\n")
    assert re.fullmatch(r"MCP_FILM_FRAME k=\d+ frame=\d+ hits=\d+ read_at=\d+", head), head
    return head + " skipped=0" + sep + rest


def _header(name: str = "film.txt") -> str:
    """A captured film header in the dumper's current format. The captures predate the
    `changed` condition's baseline, which a film without it leaves at -1: that is the one
    thing this adds to them."""
    head, sep, rest = (FIX / name).read_text().partition("\n")
    assert head.startswith("MCP_FILM ") and "baseline_frame" not in head, head
    return head + " baseline_frame=-1 baseline_value=-1" + sep + rest


def _wrote(rec: dict[str, Any], frames: tuple[int, ...] = (1, 2), header: str | None = None,
           edits: dict[str, tuple[str, str]] | None = None) -> Path:
    """What the film's notifier wrote, as the capture has it, into the film's directory: the
    header (`taken` set to the frames placed) and each kept frame's four files; `edits` maps a
    file's name to one exact replacement in its text."""
    film: mf.Film = rec["film"]
    head = header or _edited(_header(), "taken=3", f"taken={len(frames)}")
    (film.dir / "film.txt").write_text(head)
    for k in frames:
        src = 1 + (k - 1) % 2
        txt = _current((FIX / f"frame-{src}.txt").read_text()).replace(f"k={src} ", f"k={k} ")
        if edits and f"frame-{k}.txt" in edits:
            txt = _edited(txt, *edits[f"frame-{k}.txt"])
        (film.dir / f"frame-{k}.txt").write_text(txt)
        (film.dir / f"frame-{k}.bin").write_bytes(_gz(f"frame-{src}-bin"))
        (film.dir / f"frame-{k}.snap").write_bytes(_gz(f"frame-{src}-snap"))
        (film.dir / f"frame-{k}.pens").write_bytes((FIX / f"frame-{src}.pens").read_bytes())
    return film.dir


def _png(path: Path) -> png_read.Png:
    return png_read.read(path.read_bytes())


# ------------------------------------------------------------------ the arguments

@pytest.mark.parametrize(("kw", "says"), [
    ({"clear": True, "first": 2}, "`clear` removes the film"),
    ({"clear": True, "trigger": "0x70001e"}, "`clear` removes the film"),
    ({"value": 1}, "go with `trigger`"),
    ({"keep": 4}, "go with `trigger`"),
    ({"trigger": "0x70001e", "first": 1}, "`first` pages a film being READ"),
    ({"trigger": "0x70001e", "length": 3}, "length is one of (1, 2, 4); got 3"),
    ({"trigger": "0x70001e", "length": True}, "length is one of (1, 2, 4); got True"),
    ({"trigger": "0x70001e", "value": 0x100}, "value=256"),
    ({"trigger": "0x70001e", "length": 2, "value": 0x10000}, "value=65536"),
    ({"trigger": "0x70001e", "frames": 0}, "frames=0"),
    ({"trigger": "0x70001e", "frames": mf.FRAMES_MAX + 1}, f"frames={mf.FRAMES_MAX + 1}"),
    ({"trigger": "0x70001e", "keep": mf.KEEP_MAX + 1}, f"keep={mf.KEEP_MAX + 1}"),
    ({"trigger": "0x70001e", "crop": [0, 0, 0, 4]}, "crop="),
    ({"trigger": "0x70001e", "film_dir": "relative/dir"}, "must be an absolute path"),
    ({"first": -1}, "first=-1"),
    ({"trigger": "0x70001e", "changed": True, "value": 1}, "`changed` and `value`"),
    ({"changed": True}, "go with `trigger`"),
    ({"clear": True, "changed": True}, "`clear` removes the film"),
    ({"trigger": "0x70001e", "changed": 1}, "changed"),
])
def test_an_argument_the_gesture_does_not_take_is_refused_before_the_machine(
    kw: dict[str, Any], says: str,
) -> None:
    with pytest.raises(mstate.Invalid, match=re.escape(says)):
        mf.check_gfx_film(**kw)


def test_the_largest_bounds_are_accepted() -> None:
    """The bounds' edges on the inside: a refusal one past them is only a refusal if the value
    at them is taken."""
    assert mf.check_gfx_film(trigger="0x70001e", length=4, value=0xFFFFFFFF,
                             frames=mf.FRAMES_MAX, keep=mf.KEEP_MAX) is None


# ------------------------------------------------------------------ arming

def test_arming_reads_the_screen_once_and_sends_the_install_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual")
    out = s.gfx_film(trigger="0x70001e", length=2, value=0xFFFF, keep=3, frames=12)
    assert out["status"] == "ok", out
    assert out["armed_now"] is True and (out["installed"], out["pending"]) == (False, True), out
    assert out["film"]["checked"] is True and "why" not in out["film"], (
        "m68k-dual's snapshot is its bare screen, so every kept frame is checked")
    assert "mismatch" not in out["film"], "a bare-screen snapshot has nothing to measure"
    assert (out["film"]["trigger_addr"], out["film"]["value"], out["trigger_maps_to"]) == (
        "0x0070001e", "0xffff", "m68k_dual_state::blit_w")
    assert "map 0x70001e::maincpu" in ses.commands, "the trigger's write side is asked"
    assert out["session"]["altered"] is False, "arming reads the screen and puts every pen back"
    folder = Path(out["film"]["film_dir"])
    assert folder.is_dir() and folder.parent == ses.scratch
    assert out["film"]["cpu"] == ":maincpu"
    assert not list(ses.scratch.glob("screen-*.bin")), "the arming chunk's files are gone"


def test_a_snapshot_that_is_not_the_bare_screen_leaves_every_frame_unchecked_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "circus")
    out = s.gfx_film(trigger="0x70001e")
    assert out["status"] == "ok", out
    assert out["film"]["checked"] is False
    mismatch = out["film"]["mismatch"]
    assert (mismatch["differing_pixels"], mismatch["screen_pixels"]) == (3079, 248 * 256), out
    assert mismatch["snapshot_colours_are_pens"] is False and mismatch["flip"] == "none"
    assert "overlay_or_artwork" in mismatch["candidates"], mismatch
    why = out["film"]["why"]
    assert "3079 of 63488 pixels" in why and "possible causes" in why, why
    assert "artwork drawn over it" not in why, "a cause is offered, never stated"


def test_the_install_marks_the_frame_and_reads_its_picture_at_the_next_notifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The Lua the install sends, held to the law it runs: its behaviour is proven live (the
    matrix's film section); this pins the parts a refactor could drop in silence."""
    rec = _armed(monkeypatch, tmp_path)
    script = rec["script"]
    assert "local trig, len, want, wpc = 0x70001e, 2, 0xffff, nil" in script
    assert 'install_write_tap(lo, lo + nb - 1, "mcp_film_"' in script
    assert "if want ~= nil and val ~= want then return end" in script
    assert "if wpc ~= nil and pc ~= wpc then return end" in script
    assert script.index("local print = function(s) said = s end") < script.index(
        "local function mcp_capture"), "the capture's print is kept for the frame's file"
    judge = script.index("if t.fresh then")
    assert script.index("if t.pend ~= nil then\n    if not drew then") < judge, (
        "the pending frame's picture is read BEFORE this frame is judged: after the double "
        "buffer turned it over")
    assert "return v:snapshot_pixels()" in script[judge:], (
        "the frame's own rendering is taken at its own notifier")
    assert "pens = pens()" in script[judge:], "the frame's own pens are saved at its notifier"
    assert mscreen.FRAME_PENS_LUA in script, "the pens are saved by the one shared function"
    assert 'add_machine_reset_notifier(guarded(t, function() lost("lost_reset") end))' in script
    assert 'add_machine_post_load_notifier(guarded(t, function() lost("lost_load") end))' in script
    assert "if t.judged >= frames_max and t.pend == nil then" in script
    assert f"if t.nhits <= {mf.HITS_KEPT} then" in script
    assert "MCP_TALLY installed tally_id=%s" in script, "the count watch's reader answers it"


def test_a_second_film_is_refused_naming_the_clear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _armed(monkeypatch, tmp_path)
    out = s.gfx_film(trigger="0x70001e")
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "gfx_film(clear=True)" in out["message"]


@pytest.mark.parametrize(("kw", "says"), [
    ({"trigger": "0x70001f", "length": 2}, "cross a bus word of 2 bytes"),
    ({"trigger": "0x70001e", "crop": [300, 0, 40, 10]}, "leaves the 336x252 screen"),
    ({"trigger": "NO_SUCH_SYMBOL"}, "'NO_SUCH_SYMBOL' is neither a symbol of this build's table"),
    ({"trigger": "0x70001e", "pc": "NOWHERE"}, "the pc 'NOWHERE'"),
])
def test_what_only_the_machine_can_judge_is_refused_and_nothing_is_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kw: dict[str, Any], says: str,
) -> None:
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual")
    out = s.gfx_film(**kw)
    assert out["status"] == "INVALID", out
    assert says in out["message"], out["message"]
    assert mf.held() is None, "a refused arming leaves no film"


# ------------------------------------------------------------------ what the film wrote

def test_the_header_and_a_frame_file_read_as_the_notifier_wrote_them() -> None:
    head = mf.parse_film_header(_header())
    assert head is not None
    assert (head["judged"], head["met"], head["taken"], head["dropped"]) == (12, 12, 3, 9)
    assert (head["first"], head["last"], head["finished"], head["total"]) == (900, 911, 1, 12)
    meta = mf.parse_frame(_current((FIX / "frame-1.txt").read_text()))
    assert meta is not None
    assert (meta.k, meta.frame, meta.hits, meta.read_at, meta.skipped) == (1, 900, 75, 901, 0)
    assert len(meta.listed) == mf.HITS_KEPT and meta.listed[0] == (0x21AC, 0xFFFF, 899)
    assert meta.said.startswith("MAME_MCP_SCREEN tag=:screen w=336 h=252 frame=901")
    assert mf.parse_film_header("MCP_FILM film seq=1\nend\n") is None
    assert mf.parse_frame("MCP_FILM_FRAME k=1 frame=2 hits=0 read_at=3 skipped=0\n") is None
    assert mf.parse_frame((FIX / "frame-1.txt").read_text()) is None, (
        "a frame file that does not say how many frames it waited is not a whole one")


def test_every_listed_hit_is_a_write_the_capture_recorded_on_the_same_frame() -> None:
    """Two taps on one strobe: each hit a kept frame names (pc, value, the counter the tap read)
    is a row of the blitter's capture with that pc, that data and that frame."""
    rows = {(int(pc, 16), int(data, 16), int(frame))
            for line in gzip.decompress((FIX / "capture-m68k-dual-rows.gz").read_bytes())
            .decode().splitlines()
            for _r, _n, frame, pc, data, *_rest in [line.split(" ")]}
    for k in (1, 2):
        meta = mf.parse_frame(_current((FIX / f"frame-{k}.txt").read_text()))
        assert meta is not None
        missing = [h for h in meta.listed if h not in rows]
        assert not missing, f"frame {meta.frame}'s hits the capture never saw: {missing}"


def test_a_read_converts_each_kept_frame_to_an_indexed_png_in_its_own_pens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    folder = _wrote(rec)
    # a pen no pixel shows moved between the frame's notifier and the next, as a palette upload
    # would: the PLTE is the frame's own pens, not the ones the capture found a frame later
    size = 336 * 252 * 4
    shown = {v & 0xFFFFFF for v in array("I", _gz("frame-1-bin")[size:2 * size])}
    unused = min(set(range(256)) - shown)
    pens = bytearray((folder / "frame-1.pens").read_bytes())
    pens[4 * unused:4 * unused + 4] = (0xFF123456).to_bytes(4, sys.byteorder)
    (folder / "frame-1.pens").write_bytes(bytes(pens))
    # A picture already listed (a sheet drawn of it first) is listed once: the film records
    # through the session's one image recorder.
    mstate.STATE.captures.append(("image", str(folder / "frame-1.png")))
    out = s.gfx_film()
    assert out["status"] == "ok", out
    assert (out["state"], out["judged"], out["met"], out["kept"], out["refused"]) == (
        "finished", 12, 12, 2, 0), out
    first = _png(folder / "frame-1.png")
    assert first.indexed and (first.width, first.height) == (336, 252)
    assert first.palette[unused] == (0x12, 0x34, 0x56), "the PLTE is the frame's own pens"
    assert (out["dropped_total"], out["dropped_frames"]) == (9, [903, 911]), out
    assert "dropped" not in out and out["lost"] == {}
    costs = [out["cost"]["judge_s_per_frame"], out["cost"]["picture_s_per_frame"]]
    assert all(isinstance(c, float) and round(c, 6) == c for c in costs), out["cost"]
    assert out["cells"][0] == {"k": 1, "frame": 900, "hits_in_frame": 75, "hit_counters": [899,
                                                                                           899],
                               "pc": "0x000021ac", "value": "0xffff",
                               "symbol": "BLIT_PROGRAM+0x1a8",
                               "path": str(Path(out["film"]["film_dir"], "frame-1.png"))}
    assert not list(folder.glob("frame-*.bin")), "the raw files are gone once converted"
    images = [p for kind, p in mstate.STATE.captures if kind == "image"]
    assert images.count(str(folder / "frame-1.png")) == 1, images


def test_a_frame_whose_picture_is_not_mames_rendering_of_it_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    folder = _wrote(rec)
    snap = bytearray((folder / "frame-2.snap").read_bytes())
    snap[0:4] = (0xFF010203).to_bytes(4, sys.byteorder)
    (folder / "frame-2.snap").write_bytes(bytes(snap))
    out = s.gfx_film()
    assert out["status"] == "ok", out
    assert (out["kept"], out["refused"]) == (1, 1), out
    (why,) = out["refused_frames"]
    assert why["k"] == 2 and why["code"] == "readback_refused"
    assert "on 1 pixel:" in why["why"], why
    # IT SAYS WHEN THE PICTURE WAS READ, and names first the cause a live run pointed to: a
    # driver that draws into the bitmap again before the next notifier.
    assert why["why"].startswith(
        "frame 901's picture, read at frame 902, differs from MAME's rendering of frame 901 on "
        "1 pixel:"), why
    assert "the driver drew into it again before it was read" in why["why"], why
    assert not (folder / "frame-2.png").exists(), "a refused frame has no picture"
    assert not list(folder.glob("frame-2.*")), "its raw files are gone all the same"


def test_a_picture_read_at_any_frame_but_the_next_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    _wrote(rec, edits={"frame-1.txt": ("read_at=901", "read_at=903")})
    out = s.gfx_film()
    assert out["refused_frames"][0]["k"] == 1, out
    assert "read at frame 903, not at the next one" in out["refused_frames"][0]["why"]


def test_a_capture_that_failed_its_own_check_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The indexed capture's own check still holds inside a film: the screen after the restore
    must be the screen before it."""
    rec = _armed(monkeypatch, tmp_path)
    folder = _wrote(rec)
    raw = bytearray((folder / "frame-1.bin").read_bytes())
    size = 336 * 252 * 4
    raw[2 * size] ^= 0xFF
    (folder / "frame-1.bin").write_bytes(bytes(raw))
    out = s.gfx_film()
    assert out["refused_frames"][0]["k"] == 1, out
    assert out["refused_frames"][0]["code"] == "readback_refused"
    assert "the screen after the restore differs" in out["refused_frames"][0]["why"]


def test_a_film_that_kept_nothing_says_so_with_what_it_judged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    head = _header()
    for old, new in (("met=12", "met=0"), ("taken=3", "taken=0"), ("dropped=9", "dropped=0")):
        head = _edited(head, old, new)
    _wrote(rec, frames=(), header=head)
    out = s.gfx_film()
    assert out["status"] == "ok" and out["kept"] == 0, out
    assert "image" not in out and "cells" not in out, "nothing kept is no picture"
    assert out["nothing_kept"] == ("no picture kept: 0 of the 12 frames judged (900..911) met "
                                   "the condition")


def test_every_callback_a_film_installs_runs_under_the_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The tap, the frame notifier, the reset and load notifiers, and the dumper."""
    assert_every_callback_guarded(_armed(monkeypatch, tmp_path)["script"], 1, 3)


def test_a_film_whose_callbacks_raised_says_so_and_never_reads_as_nothing_met(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A film whose tap raised at every write marked no frame, and read as a condition nothing
    met: the errors ride on the film's reply, the summary counts them, and `nothing_kept`
    says the zero is not a measurement."""
    rec = _armed(monkeypatch, tmp_path)
    # the captured film met one frame before its fault; with none met, nothing was kept
    head = (FIX.parent / "callbacks" / "film-raised.txt").read_text()
    for old, new in (("met=1", "met=0"), ("taken=1", "taken=0")):
        head = _edited(head, old, new)
    _wrote(rec, frames=(), header=head)
    out = s.gfx_film()
    first = "mcp:4: planted fault"
    assert out["callback_errors"] == {"count": 678, "first": first}, out
    assert out["nothing_kept"].endswith(
        f"; but the film's callbacks raised 678 times (the first: {first}), so frames that met "
        "it may not have been marked"), out["nothing_kept"]
    assert out["summary"].endswith(f"; its callbacks raised 678 times (the first: {first})")
    # A NOTIFIER THAT RAISES BEFORE IT JUDGES leaves no frame judged, and still says why
    for old, new in (("judged=5", "judged=0"), ("first=900", "first=-1"), ("last=904", "last=-1")):
        head = _edited(head, old, new)
    _wrote(rec, frames=(), header=head)
    assert s.gfx_film()["nothing_kept"] == (
        "no picture kept and no frame judged; but the film's callbacks raised 678 times (the "
        f"first: {first}), so frames that met it may not have been marked")
    # A FILM THAT KEPT A PICTURE carries the clause after the picture
    _wrote(rec, frames=(1,), header=(FIX.parent / "callbacks" / "film-raised.txt").read_text())
    kept = s.gfx_film()
    assert "image" in kept and kept["summary"].endswith(
        f"; its callbacks raised 678 times (the first: {first})"), kept["summary"]


def test_a_healthy_film_says_none_raised_and_its_prose_says_nothing_of_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    head = _header()
    for old, new in (("met=12", "met=0"), ("taken=3", "taken=0"), ("dropped=9", "dropped=0"),
                     ("baseline_value=-1\n", "baseline_value=-1 errors=0\n")):
        head = _edited(head, old, new)
    _wrote(rec, frames=(), header=head)
    out = s.gfx_film()
    assert out["callback_errors"] == {"count": 0, "first": {"available": False,
                                                            "why": mcallbacks.NONE_RAISED_WHY}}, out
    assert out["nothing_kept"] == ("no picture kept: 0 of the 12 frames judged (900..911) met "
                                   "the condition")
    assert "callbacks" not in out["summary"]


def test_the_film_install_fits_one_console_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    assert len(_armed(monkeypatch, tmp_path)["script"]) < transport.SCRIPT_MAX
    plain = mf.parse_film_header(_header())
    assert plain is not None and plain["errors"] is None, "a header from before the guard"


def test_a_film_that_has_written_nothing_yet_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _armed(monkeypatch, tmp_path)
    out = s.gfx_film()
    assert out["status"] == "ok", out
    assert out["state"] == "no_dump_yet" and "judged" not in out, out


def test_reading_or_clearing_with_no_film_is_answered_as_what_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _session(monkeypatch, tmp_path)
    out = s.gfx_film()
    assert out["status"] == "INVALID" and "gfx_film(trigger=...)" in out["message"], out
    gone = s.gfx_film(clear=True)
    assert gone["status"] == "ok" and gone["cleared"] is False, gone


def test_clear_sends_the_removal_and_keeps_the_films_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    folder = _wrote(rec)
    s.gfx_film()
    out = s.gfx_film(clear=True)
    assert out["status"] == "ok" and out["cleared"] is True and out["removal"] == "pending", out
    assert mf.held() is None
    assert (folder / "frame-1.png").is_file() and (folder / "film.json").is_file(), (
        "the pictures outlive the film")
    assert (folder / "film.txt").is_file(), "the header is one of the film's files, and they stay"


# ------------------------------------------------------------------ the sheet

def _read_label(sheet: png_read.Png, x: int, y: int, chars: int, enlarged: int) -> str:
    """The text at (`x`, `y`) of the page, on `sheet` enlarged `enlarged` times, read back glyph
    by glyph against the font: a glyph that matches none reads as `?`."""
    by_bits = {g: ch for ch, g in font.GLYPHS.items()}
    step, scale = font.advance(msheet.LABEL_SCALE), msheet.LABEL_SCALE
    out = []
    for i in range(chars):
        rows = []
        for gy in range(font.GLYPH_H):
            rows.append("".join(
                "#" if sheet.at((x + i * step + gx * scale) * enlarged,
                                (y + gy * scale) * enlarged) == msheet.INK
                else "." for gx in range(font.GLYPH_W)))
        out.append(by_bits.get(tuple(rows), "?"))
    return "".join(out).rstrip()


def test_the_glyphs_are_pairwise_distinct_so_a_label_reads_back_one_way() -> None:
    shapes = list(font.GLYPHS.values())
    assert len(set(shapes)) == len(shapes), "two characters draw the same"
    assert all(len(g) == font.GLYPH_H and all(len(r) == font.GLYPH_W for r in g) for g in shapes)


def test_the_sheets_labels_read_back_as_the_listing_names_each_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Read off the PNG's pixels, never off the strings the writer drew: each cell's two lines
    are its frame and hits, and the pc and value of its first hit, as `film.json` lists them."""
    rec = _armed(monkeypatch, tmp_path)
    _wrote(rec)
    out = s.gfx_film()
    sheet = _png(Path(out["image"]["path"]))
    enlarged = out["image"]["scale"]
    assert out["image"]["inline"] is True
    listing = json.loads(Path(out["listing_path"]).read_text())
    lay = mf.sheet_layout(rec["film"], sorted(rec["cells"].values(), key=lambda c: c.k))
    cols, _rows = msheet.page_shape(lay, len(listing["frames"]))
    for i, frame in enumerate(listing["frames"]):
        x, y = lay.label_origin(i % cols, i // cols)
        chars = (lay.cell[0] - 2 * msheet.LABEL_PAD) // font.advance(msheet.LABEL_SCALE)
        top = _read_label(sheet, x, y, chars, enlarged)
        low = _read_label(sheet, x, y + font.line_height(msheet.LABEL_SCALE), chars, enlarged)
        first = frame["listed_hits"][0]
        assert top == f"FRAME {frame['frame']}  HITS {frame['hits_in_frame']}", top
        assert low == f"PC {int(first['pc'], 16):X}  ={first['value'][2:].upper()}", low
    assert [c["frame"] for c in out["cells"]] == [900, 901]


def test_a_cells_picture_on_the_sheet_is_its_frames_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    folder = _wrote(rec)
    out = s.gfx_film()
    sheet = _png(Path(out["image"]["path"]))
    lay = mf.sheet_layout(rec["film"], list(rec["cells"].values()))
    frame = _png(folder / "frame-2.png")
    cols, _rows = msheet.page_shape(lay, 2)
    left, top = lay.picture_origin(1 % cols, 1 // cols)
    k = out["image"]["scale"]
    for x, y in ((0, 0), (100, 100), (335, 251)):
        assert sheet.at((left + x) * k, (top + y) * k) == frame.palette[frame.pixels[y * 336 + x]]


def test_a_crop_narrows_every_picture_and_its_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path, crop=[40, 30, 64, 48])
    folder = _wrote(rec)
    out = s.gfx_film()
    assert out["film"]["crop"] == [40, 30, 64, 48], out
    small = _png(folder / "frame-1.png")
    assert (small.width, small.height) == (64, 48)
    cap_pixels = array("I", _gz("frame-1-bin")[336 * 252 * 4:2 * 336 * 252 * 4])
    for x, y in ((0, 0), (63, 47), (10, 20)):
        assert small.pixels[y * 64 + x] == cap_pixels[(30 + y) * 336 + 40 + x] & 0xFFFFFF


def test_the_pages_fit_the_inline_ceiling_and_follow_on_from_next_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path, keep=mf.KEEP_MAX)
    _wrote(rec, frames=tuple(range(1, 25)))
    out = s.gfx_film()
    assert out["status"] == "ok" and out["kept"] == 24, out
    page = out["listed"]["count"]
    assert out["listed"] == {"first": 0, "count": page, "of": 24} and 1 <= page < 24
    assert out["next_first"] == page
    assert out["image"]["inline"] is True
    assert picture.within_ceiling(out["image"]["width"], out["image"]["height"])
    lay = mf.sheet_layout(rec["film"], list(rec["cells"].values()))
    cols, rows = msheet.page_shape(lay, 24)
    assert page == cols * rows, "a page is the grid page_shape chose"
    assert not picture.within_ceiling(*lay.size(cols, rows + 1)), "one more row does not fit"
    assert all(c * r <= page or not picture.within_ceiling(*lay.size(c, r))
               for c in range(1, 25) for r in range(1, 25)), (
        "no grid inside the ceiling holds more cells")
    second = s.gfx_film(first=page)
    assert second["listed"] == {"first": page, "count": min(page, 24 - page), "of": 24}
    past = s.gfx_film(first=24)
    assert past["status"] == "INVALID" and "past the 24 kept frames" in past["message"]


def test_the_reply_of_the_largest_film_stays_inside_the_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path, keep=mf.KEEP_MAX, crop=[0, 0, 8, 8])
    _wrote(rec, frames=tuple(range(1, mf.KEEP_MAX + 1)))
    out = s.gfx_film()
    assert out["kept"] == mf.KEEP_MAX, out
    assert len(json.dumps(out, indent=2)) < mstate.REPLY_BUDGET_CHARS


def test_the_animation_plays_every_kept_frame_at_the_screens_rate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    folder = _wrote(rec)
    out = s.gfx_film()
    anim = out["animation"]
    plays, delays, frames = png_read.read_animation(Path(anim["path"]).read_bytes())
    assert (plays, anim["frames"], len(frames)) == (0, 2, 2)
    assert delays == [(1000, 50080)] * 2, "one frame of the 50.08 Hz screen each"
    assert anim["frame_period_s"] == 0.019968, "the same frame, said in seconds"
    for k, shown in zip((1, 2), frames, strict=True):
        data = _png(folder / f"frame-{k}.png")
        assert shown.pixels == b"".join(bytes(data.palette[v]) for v in data.pixels)


def test_the_listing_names_every_kept_and_every_refused_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    folder = _wrote(rec, edits={"frame-2.txt": ("read_at=902", "read_at=905")})
    out = s.gfx_film()
    doc = json.loads(Path(out["listing_path"]).read_text())
    assert doc["film"]["trigger"] == "0x70001e" and (doc["judged"], doc["met"]) == (12, 12)
    (kept,) = doc["frames"]
    assert (kept["k"], kept["frame"], kept["file"], kept["checked"]) == (
        1, 900, "frame-1.png", True)
    assert kept["hits_in_frame"] == 75 and len(kept["listed_hits"]) == mf.HITS_KEPT
    assert kept["listed_hits"][0] == {"pc": "0x000021ac", "value": "0xffff", "counter": 899,
                                      "symbol": "BLIT_PROGRAM+0x1a8"}
    assert doc["refused"][0]["k"] == 2
    assert (folder / "frame-1.png").read_bytes() and kept["sha256"]


@pytest.mark.parametrize(("frame2_edit", "counters"), [
    (None, [[899, 899], [900, 900]]),
    (("h 1fd2 ffff 900\nsaid", "h 1fd2 ffff 901\nsaid"), [[899, 899], [900, 901]]),
])
def test_a_cell_names_the_counters_its_listed_hits_carry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, frame2_edit: tuple[str, str] | None,
    counters: list[list[int]],
) -> None:
    """A cell's `frame` is the picture's; the counters its hits carry are what joins it to
    `gfx_blits(frame=...)` and to a capture's rows, and a write made in vblank carries the one
    before. A cell whose hits straddle a counter says both ends."""
    rec = _armed(monkeypatch, tmp_path)
    _wrote(rec, edits={"frame-2.txt": frame2_edit} if frame2_edit else None)
    out = s.gfx_film()
    assert out["status"] == "ok", out
    assert [(c["frame"], c["hit_counters"]) for c in out["cells"]] == [
        (900, counters[0]), (901, counters[1])], out["cells"]
    doc = json.loads(Path(out["listing_path"]).read_text())
    assert [(f["frame"], f["hit_counters"]) for f in doc["frames"]] == [
        (900, counters[0]), (901, counters[1])], "film.json carries them beside `frame`"


def test_a_cell_with_no_listed_hit_names_no_counter_and_never_its_frame_instead(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    folder = _wrote(rec, frames=(1,), header=_edited(_header(), "taken=3", "taken=1"))
    text, n = re.subn(r"^h .*\n", "", (folder / "frame-1.txt").read_text(), flags=re.M)
    assert n == mf.HITS_KEPT, "every listed hit is taken out"
    (folder / "frame-1.txt").write_text(text)
    out = s.gfx_film()
    assert out["status"] == "ok", out
    (cell,) = out["cells"]
    nothing = {"available": False, "why": mf.NO_HIT_WHY}
    assert cell["hit_counters"] == nothing and cell["frame"] == 900, cell
    assert (cell["pc"], cell["value"]) == (nothing, nothing), "no hit, so no first hit's pc"


# ------------------------------------------------------------------ a snapshot that differs

def test_a_snapshot_whose_bytes_are_not_its_declared_size_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The arming chunk writes the snapshot whole or raises, so a file of another length is an
    instrument that failed, never a snapshot that differs."""
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual", b"")
    out = s.gfx_film(trigger="0x70001e")
    assert out["status"] == "INVALID" and out["code"] == "unexpected_answer", out
    assert "holds 0 bytes, and the 336x252 snapshot it declared is 338688" in out["message"]
    assert mf.held() is None, "a refused arming leaves no film"


def test_an_animation_refuses_no_frames_and_frames_that_differ() -> None:
    from scry_core import png
    one = png.Raster(2, 1, bytes(6))
    with pytest.raises(ValueError, match="at least one frame"):
        png.encode_animation([], (1, 60))
    with pytest.raises(ValueError, match="the first one's size"):
        png.encode_animation([one, png.Raster(1, 1, bytes(3))], (1, 60))


def test_the_font_refuses_a_character_outside_its_alphabet() -> None:
    with pytest.raises(ValueError, match="'x' is not in the label font"):
        font.draw(bytearray(3 * 64), 8, "x", 0, 0, 1, (255, 255, 255))


def test_a_film_on_no_named_cpu_taps_the_visible_one_as_every_tap_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """When the console marks no cpu visible the arming holds none, and the tap then sits where
    the count watch's, the capture's and the RAMDAC log's do: the visible cpu when the script
    runs, the first one only when there is none."""
    rec = _armed(monkeypatch, tmp_path)
    loose = mf.install_script(dataclasses.replace(rec["film"], cpu=None), Path("/s/film.txt"))
    assert ('local cpu = manager.machine.debugger.visible_cpu or '
            'manager.machine.devices[":maincpu"]') in loose
    assert 'local cpu = manager.machine.devices[":maincpu"]\n' in rec["script"]


def test_a_frame_file_with_a_negative_counter_is_not_a_frame_file() -> None:
    """A screen's counter never goes below zero, and the label font draws no minus sign: such a
    line is a torn or foreign file, refused as one rather than drawn."""
    text = _edited(_current((FIX / "frame-1.txt").read_text()), "frame=900", "frame=-1")
    assert mf.parse_frame(text) is None


def test_the_frames_lost_are_counted_by_their_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    head = _header()
    for old, new in (("taken=3", "taken=2"), ("lost_reset=0", "lost_reset=2"),
                     ("lost_skipped=0", "lost_skipped=1")):
        head = _edited(head, old, new)
    _wrote(rec, header=head)
    out = s.gfx_film()
    assert out["lost"] == {"reset": 2, "skipped": 1}, out


@pytest.mark.parametrize(("damage", "says"), [
    ("no pens", "No such file"),
    ("short pens", "255 pens were saved at frame 900 and the screen has 256"),
    ("capture raised", "the capture raised: mcp:9: disk full"),
    ("torn file", "frame-1.txt is not a whole frame file"),
])
def test_every_way_a_kept_frames_files_can_be_wrong_refuses_that_frame_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, damage: str, says: str,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    folder = _wrote(rec)
    if damage == "no pens":
        (folder / "frame-1.pens").unlink()
    elif damage == "short pens":
        (folder / "frame-1.pens").write_bytes((FIX / "frame-1.pens").read_bytes()[:-4])
    elif damage == "capture raised":
        meta = (folder / "frame-1.txt").read_text()
        said = next(ln for ln in meta.splitlines() if ln.startswith("said "))
        (folder / "frame-1.txt").write_text(
            meta.replace(said, "said MCP_FILM_ERROR mcp:9: disk full"))
    else:
        (folder / "frame-1.txt").write_text("MCP_FILM_FRAME k=1 frame=900\n")
    out = s.gfx_film()
    assert out["status"] == "ok" and out["kept"] == 1, out
    (refusal,) = out["refused_frames"]
    assert refusal["k"] == 1 and says in refusal["why"], refusal


def test_a_frame_of_another_size_than_the_armed_screen_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A game that changes its resolution mid-film: the sheet, the animation and the crop all
    rest on one size, so a frame of another is refused with both sizes named."""
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "circus")
    assert s.gfx_film(trigger="0x70001e")["status"] == "ok"
    found = mf.held()
    assert found is not None
    found[1].update(installed=True, cpu=":maincpu")
    _wrote(found[1], frames=(1,), header=_edited(_header(), "taken=3",
                                                 "taken=1"))
    out = s.gfx_film()
    assert out["kept"] == 0 and out["refused"] == 1, out
    assert "the screen is 336x252 at frame 900 and was 248x256" in out["refused_frames"][0]["why"]


def test_a_film_goes_to_dest_and_a_second_film_to_a_directory_of_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _session(monkeypatch, tmp_path)

    def arm(**kw: Any) -> dict[str, Any]:
        _serve_arm(ses, "m68k-dual")
        out: dict[str, Any] = s.gfx_film(trigger="0x70001e", **kw)
        # the install the arming sent is answered, as the console answers it at the next step
        ses.answers[mstate.STATE.lua_seq] = ses.sentinel(mstate.STATE.lua_seq)
        s.gfx_film(clear=True)
        ses.answers[mstate.STATE.lua_seq] = ses.sentinel(mstate.STATE.lua_seq)
        return out

    first = arm(film_dir=str(tmp_path / "kept"))
    assert first["film"]["film_dir"] == str(tmp_path / "kept") and (tmp_path / "kept").is_dir()
    one, two = arm(), arm()
    assert (Path(one["film"]["film_dir"]).name, Path(two["film"]["film_dir"]).name) == (
        "film-1", "film-2"), (one, two)


def test_an_arming_refused_at_the_install_leaves_its_dest_unmade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The install is the arming's last step that can refuse: a `dest` made before it would be
    left behind, and the next arming with the same `dest` refused as already there."""
    ses = _session(monkeypatch, tmp_path)
    dest = tmp_path / "kept"
    real = mtap.send_tap

    def refusing(*a: Any, **k: Any) -> dict[str, Any]:
        raise mstate.Invalid("bad_argument", "the console is too far behind to take it")

    monkeypatch.setattr(mtap, "send_tap", refusing)
    _serve_arm(ses, "m68k-dual")
    refused("too far behind", s.gfx_film(trigger="0x70001e", film_dir=str(dest)))
    assert not dest.exists(), "the refused arming left its directory"
    monkeypatch.setattr(mtap, "send_tap", real)
    _serve_arm(ses, "m68k-dual")
    assert s.gfx_film(trigger="0x70001e", film_dir=str(dest))["status"] == "ok"
    assert dest.is_dir()


def test_a_trigger_nothing_handles_is_armed_and_the_note_says_the_write_goes_nowhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A write tap on an address whose write side is unmapped still sees the cpu's
    writes there, so the film arms on it; on a ROM copy the note points at the live datum."""
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual")
    plain = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: MAP_ROM if c.startswith("map ")
                        else plain(c, timeout))
    out = s.gfx_film(trigger="0x400", length=2)
    assert out["status"] == "ok" and out["trigger_maps_to"] == "unmapped", out
    assert out["note"].startswith("the film judges from the first whole frame"), "kept"
    assert "; the trigger: nothing in the machine handles a write at 0x400" in out["note"], out
    assert "reads as memory, the ROM copy" in out["note"] and mf.held() is not None, out


def test_an_arming_answer_with_no_film_line_is_refused_in_the_consoles_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual")
    seq = mstate.STATE.lua_seq + 1
    ses.answers[seq] = re.sub(rb"MCP_FILM_ARM[^\n]*\n", b"", ses.answers[seq])
    out = s.gfx_film(trigger="0x70001e")
    assert out["status"] == "INVALID" and out["code"] == "unexpected_answer", out
    assert "printed no film line" in out["message"] and mf.held() is None


def test_a_snapshot_of_another_size_leaves_every_frame_unchecked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual", bytes(4 * 672 * 504))
    seq = mstate.STATE.lua_seq + 1
    ses.answers[seq] = ses.answers[seq].replace(b"snap_w=336 snap_h=252", b"snap_w=672 snap_h=504")
    out = s.gfx_film(trigger="0x70001e")
    assert out["film"]["checked"] is False, out
    assert "672x504 and the screen 336x252" in out["film"]["why"]
    assert out["film"]["mismatch"] == {
        "screen_size": [336, 252], "snapshot_size": [672, 504],
        "differing_pixels": UNCOMPARED, "screen_pixels": 336 * 252, "bbox": UNCOMPARED,
        "snapshot_colours_are_pens": UNCOMPARED,
        "flip": UNCOMPARED, "candidates": ["overlay_or_artwork"]}, out


def test_a_checked_frame_with_no_snapshot_is_refused_and_first_needs_a_kept_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    folder = _wrote(rec, frames=(1,), header=_edited(_header(), "taken=3",
                                                      "taken=1"))
    (folder / "frame-1.snap").write_bytes(b"")
    out = s.gfx_film()
    assert "has no snapshot of the screen's size" in out["refused_frames"][0]["why"], out
    empty = s.gfx_film(first=1)
    assert empty["status"] == "INVALID" and "the film has kept no frame" in empty["message"]


def test_a_direct_colour_screen_keeps_its_frames_in_colour_checked_against_mames_rendering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """starfire draws in direct colour: a kept frame has no pens, so its file is RGB, the
    colours the screen held, and the check compares those colours with MAME's rendering. The
    film record is m68k-dual's armed one with starfire's screen, the frame's files starfire's
    own capture (`starfire-*`, a film on `0x8014` at frame 276)."""
    rec = _armed(monkeypatch, tmp_path)
    rec["film"] = film = dataclasses.replace(rec["film"], width=256, height=224, length=1,
                                             value=None, screen=":screen")
    head = _edited(_header("starfire-film.txt"), "taken=2", "taken=1")
    (film.dir / "film.txt").write_text(head)
    (film.dir / "frame-1.txt").write_text(_current((FIX / "starfire-frame-1.txt").read_text()))
    (film.dir / "frame-1.bin").write_bytes(_gz("starfire-frame-1-bin"))
    (film.dir / "frame-1.snap").write_bytes(_gz("starfire-frame-1-snap"))
    (film.dir / "frame-1.pens").write_bytes(b"")
    out = s.gfx_film()
    assert out["kept"] == 1 and out["refused"] == 0, out
    shown = _png(film.dir / "frame-1.png")
    assert not shown.indexed and (shown.width, shown.height) == (256, 224)
    colours = array("I", _gz("starfire-frame-1-bin"))
    for x, y in ((0, 0), (128, 100), (255, 223)):
        c = colours[y * 256 + x]
        assert shown.at(x, y) == ((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)
    assert out["cells"][0]["value"] == "0xff" and out["cells"][0]["pc"] == "0x00000091"
    snap = bytearray(_gz("starfire-frame-1-snap"))
    snap[4 * (100 * 256 + 128)] ^= 0x01
    for suffix, data in ((".txt", _current((FIX / "starfire-frame-1.txt").read_text()).replace(
            "k=1 ", "k=2 ").encode()), (".bin", _gz("starfire-frame-1-bin")),
            (".snap", bytes(snap)), (".pens", b"")):
        (film.dir / f"frame-2{suffix}").write_bytes(data)
    (film.dir / "film.txt").write_text(_edited(head, "taken=1", "taken=2"))
    again = s.gfx_film()
    assert again["refused"] == 1 and "on 1 pixel:" in again["refused_frames"][0]["why"], again


def test_a_picture_that_waited_past_skipped_frames_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Under frameskip the double buffer turns only on a frame that drew: frame N's picture is
    read at the first drawn frame after it, and its file says how many were skipped between."""
    rec = _armed(monkeypatch, tmp_path)
    _wrote(rec, edits={"frame-1.txt": ("read_at=901 skipped=0", "read_at=902 skipped=1")})
    out = s.gfx_film()
    assert out["refused"] == 0 and out["kept"] == 2, out.get("refused_frames", out)


def test_the_notifier_reads_a_picture_only_on_a_frame_that_drew() -> None:
    """The law under frameskip, pinned where a refactor could drop it: a pending picture waits
    out a skipped frame instead of being lost, and a met frame that was itself skipped is lost at
    once, since it drew nothing to read."""
    film = mf.Film("70001e", 0x70001E, 2, 0xFFFF, "", None, ":maincpu", 12, 3, None,
                   Path("/nowhere"), ":screen", 336, 252, 60.0, True, None)
    script = mf.install_script(film, Path("/nowhere/film.txt"))
    wait = script.index("if not drew then")
    assert wait < script.index("develop(fr)", wait) < script.index("if t.fresh then"), (
        "a skipped frame turned no buffer, so the pending picture is not read at it")
    assert "t.pend.skipped = t.pend.skipped + 1" in script
    judge = script[script.index("if t.nhits > 0 then"):]
    assert judge.index("t.lost_skipped = t.lost_skipped + 1") < judge.index("t.pend = {"), (
        "a met frame that was skipped drew nothing, so it is lost before anything is kept")


# ------------------------------------------------------------------ changed=True

def test_a_changed_film_arms_with_its_condition_named(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    ses = _session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual")
    out = s.gfx_film(trigger="0x70001e", length=2, changed=True)
    assert out["status"] == "ok", out
    assert out["film"]["changed"] is True, out["film"]
    assert out["film"]["value"]["available"] is False, out["film"]
    found = mf.held()
    assert found is not None
    assert "local changed = true" in found[1]["script"]


def test_the_install_compares_each_write_with_the_one_before_it() -> None:
    """The tap's law for `changed`, pinned where a refactor could drop it: every write to the
    trigger moves the previous value, whatever wrote it; the film's first write is the baseline
    and meets nothing; a write equal to the one before meets nothing; only then the pc."""
    film = mf.Film("70001e", 0x70001E, 2, None, "", None, ":maincpu", 12, 3, None,
                   Path("/nowhere"), ":screen", 336, 252, 60.0, True, None, True)
    script = mf.install_script(film, Path("/nowhere/film.txt"))
    tap = script[script.index("install_write_tap("):script.index("local function untap()")]
    law = tap.index("if changed then")
    assert law < tap.index("if wpc ~= nil and pc ~= wpc then return end"), (
        "the previous write is every writer's, so it moves before the pc is judged")
    assert tap.index("local before = t.prev") < tap.index("t.prev = val") < tap.index(
        "if before == nil then") < tap.index("if val == before then return end")
    assert ("if before == nil then t.baseline_frame, t.baseline_value = frame(), val "
            "return end") in tap, "the baseline is recorded and meets nothing"
    assert "local changed = true" in script
    plain = mf.install_script(dataclasses.replace(film, changed=False), Path("/n/film.txt"))
    assert "local changed = false" in plain


def test_a_changed_films_reply_names_its_baseline(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    rec = _armed(monkeypatch, tmp_path)
    rec["film"] = dataclasses.replace(rec["film"], value=None, changed=True)
    _wrote(rec, header=_edited(_header(), "baseline_frame=-1 baseline_value=-1",
                               "baseline_frame=899 baseline_value=65535"))
    out = s.gfx_film()
    assert out["status"] == "ok", out
    assert (out["frame_baseline"], out["baseline_value"]) == (899, "0xffff"), out


@pytest.mark.parametrize(("baseline", "said"), [
    ("baseline_frame=-1 baseline_value=-1", (False, False)),
    ("baseline_frame=899 baseline_value=65535", (899, "0xffff")),
])
def test_a_changed_film_that_met_nothing_says_so_with_its_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, baseline: str,
    said: tuple[int | None, str | None],
) -> None:
    """The control, both ways it happens: a trigger never written has no baseline, and one
    written every frame with one value has its first write as the baseline; either keeps
    nothing and says so."""
    rec = _armed(monkeypatch, tmp_path)
    rec["film"] = dataclasses.replace(rec["film"], value=None, changed=True)
    head = _edited(_header(), "met=12 taken=3 dropped=9 dropped_first=903 dropped_last=911",
                   "met=0 taken=0 dropped=0 dropped_first=-1 dropped_last=-1")
    (rec["film"].dir / "film.txt").write_text(
        _edited(head, "baseline_frame=-1 baseline_value=-1", baseline))
    out = s.gfx_film()
    got = tuple(v["available"] if isinstance(v, dict) else v
                for v in (out["frame_baseline"], out["baseline_value"]))
    assert got == said and "nothing_kept" in out, out
    assert "0 of the 12 frames judged" in out["nothing_kept"]


def test_a_film_without_changed_carries_no_baseline(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    rec = _armed(monkeypatch, tmp_path)
    _wrote(rec)
    out = s.gfx_film()
    assert "frame_baseline" not in out and out["film"]["changed"] is False, out


def test_a_new_film_never_inherits_the_state_of_one_whose_removal_was_lost() -> None:
    """Every film installs under one id, and a rerun of its own install carries its state over.
    A different film (another directory, so another header) starts from nothing, so a removal the
    console never ran cannot hand it the old film's counts, header or previous value; and a reset
    or a state load leaves the previous write as it was, the film's own."""
    film = mf.Film("70001e", 0x70001E, 2, None, "", None, ":maincpu", 12, 3, None,
                   Path("/nowhere"), ":screen", 336, 252, 60.0, True, None, True)
    script = mf.install_script(film, Path("/nowhere/film.txt"))
    head = transport.lua_string(str(Path("/nowhere/film.txt")))
    assert f"local same = old ~= nil and old.head == {head}" in script
    assert "local t = same and old or {" in script
    lost = script[script.index("local function lost(field)"):script.index("local subs = {}")]
    assert "t.prev" not in lost and "baseline" not in lost


def test_the_label_font_measures_to_its_glyphs() -> None:
    """Known answers from the glyph size, 5x7 with a pixel of spacing, independent of any
    consumer that measures with the same functions it is checking."""
    assert (font.advance(1), font.advance(2), font.line_height(1), font.line_height(2)) == (
        6, 12, 8, 16)
    assert (font.width("A", 1), font.width("AB", 2), font.width("", 5)) == (5, 22, 0)


def test_a_glyph_at_scale_two_is_painted_on_its_own_rows_only() -> None:
    """L's bottom row is lit: at scale 2 both of its sub-rows are painted, and the row above the
    glyph's top is untouched."""
    stride, y = 20, 2
    px = bytearray(3 * stride * 24)
    font.draw(px, stride, "L", 1, y, 2, (255, 255, 255))

    def lit(row: int, col: int) -> bool:
        return px[(row * stride + col) * 3] == 255

    bottom = y + font.GLYPH_H * 2 - 1
    assert lit(bottom, 1) and lit(bottom - 1, 1), "the bottom row's two sub-rows"
    assert not any(lit(y - 1, c) for c in range(stride)), "nothing above the glyph"
    assert not any(lit(bottom + 1, c) for c in range(stride)), "nothing below it"


# ------------------------------------------------------------------ a film on a port

def _io_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                spaces: tuple[str, ...] = ("io", "program")) -> _ChannelSession:
    """The film's double, its cpu given an io space and its `mapi` answered (`io_board`)."""
    ses = _session(monkeypatch, tmp_path)
    io_board(monkeypatch, ses, spaces)
    return ses


def test_a_film_on_a_port_taps_the_io_space_and_asks_the_io_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _io_session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual")
    out = s.gfx_film(trigger="0x6", length=2, space="io", keep=12, frames=12)
    assert out["status"] == "ok", out
    assert out["film"]["space"] == "io", out["film"]
    assert out["trigger_maps_to"] == "twinsed1_state::twins_pal_w", out
    assert any(c.startswith("mapi 0x6") for c in ses.commands)
    assert not any(c.startswith("map ") for c in ses.commands), "the port is not a RAM address"
    found = mf.held()
    assert found is not None
    script = found[1]["script"]
    assert 'cpu.spaces["io"]' in script and 'cpu.spaces["program"]' not in script


def test_a_film_in_the_program_space_says_so_and_asks_the_program_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rec = _armed(monkeypatch, tmp_path)
    assert rec["film"].fields()["space"] == "program"
    assert 'cpu.spaces["program"]' in rec["script"]


@pytest.mark.parametrize(("kw", "said"), [
    ({"trigger": "PORT"}, "written `0x`"),
    ({"trigger": "0x6", "space": "data"}, "space"),
    ({"space": "io"}, "trigger"),
])
def test_what_a_film_on_a_port_cannot_take_is_refused_before_the_machine(
    kw: dict[str, Any], said: str,
) -> None:
    refused(said, s.gfx_film(**{"space": "io", **kw}))


def test_a_film_on_a_cpu_with_no_io_space_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    ses = _io_session(monkeypatch, tmp_path, spaces=("program",))
    _serve_arm(ses, "m68k-dual")
    refused("no io space", s.gfx_film(trigger="0x6", length=2, space="io"))
    assert mf.held() is None


def test_a_film_on_a_trigger_whose_write_side_the_console_does_not_name_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _io_session(monkeypatch, tmp_path)
    plain = ses.monitor
    monkeypatch.setattr(ses, "monitor", lambda c, timeout=10.0: "   Read: 0020 -> unmapped\n"
                        if c.startswith("mapi ") else plain(c, timeout))
    out = refused("the trigger: the console's `mapi 0x20` named no `Write:` side",
                  s.gfx_film(trigger="0x20", length=2, space="io"))
    assert out["code"] == "bad_argument" and mf.held() is None


def test_a_film_on_an_unmapped_port_is_armed_and_says_the_out_goes_nowhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _io_session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual")
    out = s.gfx_film(trigger="0x20", length=2, space="io")
    assert out["status"] == "ok" and out["trigger_maps_to"] == "unmapped", out
    assert "nothing in the machine handles an `out` at port 0x20" in out["note"], out
    assert mf.held() is not None


def test_a_film_on_an_odd_port_across_the_io_bus_word_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two bytes from port 7 of a 16-bit io bus straddle two bus words, which no single `out`
    writes: refused as a program trigger across a word is."""
    ses = _io_session(monkeypatch, tmp_path)
    _serve_arm(ses, "m68k-dual")
    refused("cross a bus word", s.gfx_film(trigger="0x7", length=2, space="io"))
    assert mf.held() is None


def test_reading_a_film_none_armed_asks_for_the_call_that_arms_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Nothing is wrong with the arguments: another call has to come first, and the code says so
    apart from a value to change."""
    _session(monkeypatch, tmp_path)
    out = refused(re.escape("no film is armed in this session: `gfx_film(trigger=...)` arms one"),
                  s.gfx_film())
    assert out["code"] == "needs_call", out


def test_the_film_directory_is_there_when_the_install_names_it_and_a_cancel_takes_it_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The install writes the film's header into its directory, so the directory is made
    first; a cancel met inside the install takes the scratch's `film-<n>` back as a refusal
    does."""
    ses = _session(monkeypatch, tmp_path)
    seen: list[bool] = []

    def cancelled(*a: Any, **k: Any) -> dict[str, Any]:
        seen.append(k["path"].parent.is_dir())
        raise KeyboardInterrupt
    monkeypatch.setattr(mtap, "send_tap", cancelled)
    _serve_arm(ses, "m68k-dual")
    with contextlib.suppress(KeyboardInterrupt):
        s.gfx_film(trigger="0x70001e")
    assert seen == [True], "the directory was not there when the install named it"
    assert not list(ses.scratch.glob("film-*")), "the cancelled arming left its directory"
