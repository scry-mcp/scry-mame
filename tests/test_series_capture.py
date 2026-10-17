"""`series_capture`'s server half on doubles of the console and the run: what the notifier would
have dumped is written by the double, and the series the tool makes of it is read back with the
decoder. The notifier's own Lua runs on the live tier (section Y), against a real machine."""

from __future__ import annotations

import json
import sys
from array import array
from pathlib import Path
from typing import Any

import pytest
from scry_core import png

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import blank_session  # noqa: E402

import mame_advance as madvance  # noqa: E402
import mame_chunk as mchunk  # noqa: E402
import mame_read as mread  # noqa: E402
import mame_series as mseries  # noqa: E402
import mame_state as mstate  # noqa: E402

W, H = 4, 2


def _words(frame: int) -> array[int]:
    """Frame `frame`'s screen: every pixel ARGB with red = the frame number, green its x, blue
    its y, so a frame read under another frame's name, or a pixel moved, shows."""
    return array("I", (0xFF000000 | (frame << 16) | (x << 8) | y
                       for y in range(H) for x in range(W)))


def _direct(folder: Path, frame: int, read_at: int, size: tuple[int, int] = (W, H)) -> None:
    """What the notifier dumps for a direct-colour screen: the colours, no pens."""
    words = _words(frame) if size == (W, H) else array("I", [0xFF000000] * (size[0] * size[1]))
    (folder / f"raw-{frame}.bin").write_bytes(words.tobytes())
    (folder / f"raw-{frame}.pens").write_bytes(b"")
    (folder / f"raw-{frame}.txt").write_text(
        f"frame={frame} read_at={read_at} skipped=0\nMAME_MCP_SCREEN tag=:screen w={size[0]} "
        f"h={size[1]} frame={read_at} palette=- entries=0")


#: An indexed screen of two pens: what the screen holds when it is READ (the next frame's pens)
#: and what it held at the frame's own end. The series must show the second.
PENS_AT_READ = [0xFF0000FF, 0xFF00FF00]
PENS_AT_END = [0xFFFF0000, 0xFFFFFFFF]


def _indexed(folder: Path, frame: int, read_at: int) -> None:
    """What the notifier dumps for an indexed screen, in the capture chunk's layout (colours,
    the encoded pens, the colours after, the pens, the pens read back), and the pens saved at
    the frame's own end beside it. Pixel (0, 0) is pen 1, every other pen 0."""
    idx = [1] + [0] * (W * H - 1)
    colours = array("I", (PENS_AT_READ[i] for i in idx))
    encoded = array("I", (0xFF000000 | i for i in idx))
    pens = array("I", PENS_AT_READ)
    (folder / f"raw-{frame}.bin").write_bytes(colours.tobytes() + encoded.tobytes()
                                              + colours.tobytes() + pens.tobytes() * 2)
    (folder / f"raw-{frame}.pens").write_bytes(array("I", PENS_AT_END).tobytes())
    (folder / f"raw-{frame}.txt").write_text(
        f"frame={frame} read_at={read_at} skipped=0\nMAME_MCP_SCREEN tag=:screen w={W} h={H} "
        f"frame={read_at} palette=:palette entries=2")


class _Console:
    """The arm and finish chunks, answered as the Lua would answer them; the run, writing what
    the notifier would have dumped for each frame it was told to keep."""

    def __init__(self, folder_of: list[Path], kept: list[int], lost: str = "",
                 errors: int = 0, verdict: str = "ELAPSED", now: int = 100) -> None:
        self.folder_of, self.kept, self.lost, self.errors = folder_of, kept, lost, errors
        self.verdict, self.now, self.finished = verdict, now, 0
        self.ran_frames: int | None = None
        self.dump: Any = lambda folder, f: _direct(folder, f, f + 1)
        self.armed = f"MCP_SERIES_ARMED frame={now} w={W} h={H}\n"
        self.running_after = False
        self.scripts: list[str] = []

    def run(self, ses: Any, scratch: Path, script: str, seconds: float, progress: Any,
            what: str) -> tuple[str, dict[str, Any]]:
        self.scripts.append(script)
        if what == "series":
            folder = Path(script.split("local dir = ", 1)[1].split("\n", 1)[0].strip('"'))
            self.folder_of.append(folder)
            return self.armed, {"evaluated_by": "one step", "thread_errors": 0,
                                "console_reruns": 0, "resent": 0}
        self.finished += 1
        return (f"MCP_SERIES_DONE kept={len(self.kept)} lost={self.lost} errors={self.errors} "
                f"first_error={'boom' if self.errors else ''}\n"), {}

    def run_for(self, ses: Any, scratch: Path, milliseconds: int, seconds: float,
                progress: Any, frames: int = 0) -> dict[str, Any]:
        self.ran_frames = frames
        folder = self.folder_of[-1]
        for f in self.kept:
            self.dump(folder, f)
        if self.running_after:
            ses.running = True
        return {"summary": "x", "status": "ok", "verdict": self.verdict, "frame_before": 100,
                "frame_after": 100 + frames, "how": "the run", "session": {}}


class _Session:
    running = False


@pytest.fixture
def console(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Console:
    blank_session(monkeypatch)
    folders: list[Path] = []
    double = _Console(folders, kept=[101, 103, 105])
    monkeypatch.setattr(mchunk, "run", double.run)
    monkeypatch.setattr(madvance, "run_for", double.run_for)
    monkeypatch.setattr(mread, "frame", lambda ses: double.now)
    return double


def _capture(tmp_path: Path, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {"frames": None, "first": 101, "last": 105, "step": 2, "crop": None,
                            "dest": "", "seconds": 10.0}
    args.update(kw)
    return mseries.series_capture(_Session(), tmp_path, **args)  # type: ignore[arg-type]


def test_a_series_is_written_frame_by_frame_and_named_by_its_frame(console: _Console,
                                                                   tmp_path: Path) -> None:
    out = _capture(tmp_path)
    manifest = Path(out["manifest"])
    assert manifest.parent == tmp_path / "series" / "series-1" and out["kept_after_close"] is False
    assert (out["count"], out["first"], out["last"], out["distinct"]) == (3, 101, 105, 3)
    assert out["frames_asked"] == 3 and out["lost"] == [] and out["frame_source"] == "frame_number"
    assert out["verdict"] == "ELAPSED" and "summary" not in out and "session" not in out
    assert console.ran_frames == 105 - 100 + mseries.RUN_TAIL and console.finished == 1
    doc = json.loads(manifest.read_text())
    assert [r["frame"] for r in doc["frames"]] == [101, 103, 105] and doc["server"] == "mame"
    picture = png.decode((manifest.parent / "f000103.png").read_bytes())
    assert (picture.width, picture.height) == (W, H)
    assert picture.pixels[:6] == bytes([103, 0, 0, 103, 1, 0]), "frame 103's own pixels, in place"
    assert sorted(p.name for p in manifest.parent.iterdir()) == [
        "f000101.png", "f000103.png", "f000105.png", "manifest.json"], "no raw dump left"
    assert ("image", str(manifest.parent / "f000105.png")) in mstate.STATE.captures


def test_a_crop_and_a_dest_shape_the_series(console: _Console, tmp_path: Path) -> None:
    dest = tmp_path / "kept"
    out = _capture(tmp_path, frames=[101, 105], first=None, last=None, step=1,
                   crop=[1, 1, 2, 1], dest=str(dest))
    assert out["kept_after_close"] is True and Path(out["manifest"]).parent == dest
    picture = png.decode((dest / "f000105.png").read_bytes())
    assert (picture.width, picture.height, picture.pixels) == (2, 1, bytes([105, 1, 1, 105, 2, 1]))
    assert json.loads(Path(out["manifest"]).read_text())["crop"] == [1, 1, 2, 1]


def test_a_frame_lost_to_frameskip_is_listed_never_filled(console: _Console,
                                                          tmp_path: Path) -> None:
    console.kept, console.lost = [101, 105], "103"
    out = _capture(tmp_path)
    assert out["count"] == 2 and out["lost"] == [[103, 103]]


@pytest.mark.parametrize("change, said, code", [
    ({"now": 101}, "frame 101 is not ahead of the machine, which is at frame 101", "bad_argument"),
    ({"verdict": "OTHER_STOP"}, "stopped with verdict OTHER_STOP", "cut_by_other_stop"),
    ({"errors": 2}, "raised 2 time", "unexpected_answer"),
    ({"kept": [], "lost": "101,103,105"}, "every wanted frame was skipped", "no_progress"),
    ({"kept": [101, 105]}, r"1 wanted frame\(s\) came out of the run neither kept nor lost "
     r"\(first \[103\]\)", "unexpected_answer"),
])
def test_a_series_that_cannot_be_trusted_is_refused_and_leaves_nothing(
        console: _Console, tmp_path: Path, change: dict[str, Any], said: str, code: str) -> None:
    for k, v in change.items():
        setattr(console, k, v)
    dest = tmp_path / "kept"
    with pytest.raises(mstate.Invalid, match=said) as e:
        _capture(tmp_path, dest=str(dest))
    assert e.value.code == code
    assert not dest.exists(), "a refused series leaves no directory behind"
    if code != "bad_argument":
        assert console.finished == 1, "the notifier is removed whatever happened"


def test_a_crop_off_the_screen_is_refused_after_the_notifier_is_removed(
        console: _Console, tmp_path: Path) -> None:
    with pytest.raises(mstate.Invalid, match=r"crop \[3, 0\] \+ 2x1 leaves the screen"):
        _capture(tmp_path, crop=[3, 0, 2, 1])
    assert console.finished == 1 and console.ran_frames is None


@pytest.mark.parametrize("kw, said", [
    ({"crop": [0, 0, 0, 1]}, "crop="),
    ({"dest": "relative"}, "dest"),
    ({"seconds": 0}, "seconds"),
    ({"first": None, "last": None}, "one of the two"),
])
def test_what_needs_no_machine_is_refused_before_it(kw: dict[str, Any], said: str) -> None:
    args: dict[str, Any] = {"first": 101, "last": 105}
    args.update(kw)
    with pytest.raises(mstate.Invalid, match=said):
        mseries.check_series_capture(**args)


def test_a_dest_already_there_is_refused(console: _Console, tmp_path: Path) -> None:
    (tmp_path / "kept").mkdir()
    with pytest.raises(mstate.Invalid, match="already exists"):
        _capture(tmp_path, dest=str(tmp_path / "kept"))


def test_a_second_series_takes_the_next_name_and_a_run_refused_leaves_none(
        console: _Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = Path(_capture(tmp_path)["manifest"]).parent
    second = Path(_capture(tmp_path)["manifest"]).parent
    assert (first.name, second.name) == ("series-1", "series-2")

    def refused_run(*_: Any, **__: Any) -> dict[str, Any]:
        return {"summary": "x", "status": "INVALID", "code": "not_settled", "message": "m"}
    monkeypatch.setattr(madvance, "run_for", refused_run)
    out = _capture(tmp_path)
    assert out["code"] == "not_settled" and console.finished == 3
    assert sorted(p.name for p in (tmp_path / "series").iterdir()) == ["series-1", "series-2"]


@pytest.mark.parametrize("which", ["series", "series finish"])
def test_a_chunk_that_printed_no_line_is_refused(console: _Console, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch,
                                                 which: str) -> None:
    real = console.run

    def mute(ses: Any, scratch: Path, script: str, seconds: float, progress: Any,
             what: str) -> tuple[str, dict[str, Any]]:
        text, common = real(ses, scratch, script, seconds, progress, what)
        return ("nothing\n" if what == which else text), common
    monkeypatch.setattr(mchunk, "run", mute)
    with pytest.raises(mstate.Invalid, match="printed no series") as e:
        _capture(tmp_path)
    assert e.value.code == "unexpected_answer"


def test_a_dest_that_cannot_be_made_is_refused(console: _Console, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(self: Path, *_: Any, **__: Any) -> None:
        raise PermissionError("read-only")
    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(mstate.Invalid, match="cannot be created: read-only"):
        _capture(tmp_path, dest=str(tmp_path / "kept"))


def test_an_indexed_frame_is_shown_in_the_pens_of_its_own_end(console: _Console,
                                                              tmp_path: Path) -> None:
    """The bitmap is read a frame late, when the palette may have moved: pixel (0, 0) is pen 1,
    which was white at the frame's end and is green at the read. The series shows white."""
    console.dump = lambda folder, f: _indexed(folder, f, f + 1)
    out = _capture(tmp_path)
    picture = png.decode((Path(out["manifest"]).parent / "f000103.png").read_bytes())
    assert picture.pixels[:3] == bytes([255, 255, 255]), "pen 1 as it was at frame 103's end"
    assert picture.pixels[3:6] == bytes([255, 0, 0]), "pen 0 as it was at frame 103's end"


@pytest.mark.parametrize("dump, said, code", [
    (lambda folder, f: _direct(folder, f, f + 2), "read at frame 103, not at the next one",
     "readback_refused"),
    (lambda folder, f: _direct(folder, f, f + 1, (W + 1, H)), "the screen is 5x2 at frame 101",
     "readback_refused"),
])
def test_a_frame_read_at_the_wrong_time_or_size_is_refused(
        console: _Console, tmp_path: Path, dump: Any, said: str, code: str) -> None:
    console.kept = [101]
    console.dump = dump
    with pytest.raises(mstate.Invalid, match=said) as e:
        _capture(tmp_path, first=None, last=None, step=1, frames=[101])
    assert e.value.code == code


def test_a_capture_the_chunk_refused_is_refused_in_its_own_words(console: _Console,
                                                                tmp_path: Path) -> None:
    def two_screens(folder: Path, f: int) -> None:
        (folder / f"raw-{f}.pens").write_bytes(b"")
        (folder / f"raw-{f}.txt").write_text(
            f"frame={f} read_at={f + 1} skipped=0\nMAME_MCP_SCREEN_COUNT screens=:l,:r")
    console.dump = two_screens
    with pytest.raises(mstate.Invalid, match="2 screens") as e:
        _capture(tmp_path)
    assert e.value.code == "ambiguous_ref"


def test_a_run_that_may_still_be_moving_is_answered_without_the_console(
        console: _Console, tmp_path: Path) -> None:
    console.running_after = True
    session = _Session()
    out = mseries.series_capture(session, tmp_path, None, 101, 105, 2, None, "", 10.0)  # type: ignore[arg-type]
    assert console.finished == 0, "nothing is sent to a machine that may be running"
    assert "still armed" in out["note"]


def test_an_arming_that_failed_still_takes_the_notifier_down(console: _Console,
                                                            tmp_path: Path) -> None:
    console.armed = "MCP_SERIES_NO_SCREEN\n"
    with pytest.raises(mstate.Invalid, match="has no screen") as e:
        _capture(tmp_path)
    assert e.value.code == "no_channel" and console.finished == 1


def test_a_thousand_frames_fit_as_a_range_and_a_list_too_long_is_refused(tmp_path: Path) -> None:
    wanted = list(range(10 ** 6, 10 ** 6 + 1000))
    script = mseries.arm_script(tmp_path, None, wanted[0], wanted[-1], 1, wanted)
    assert len(script) <= mseries.CONSOLE_CHARS and "for f = 1000000, 1000999, 1 do" in script
    # A list of far frame numbers, each a dozen digits, is the one shape that cannot fit.
    far = list(range(10 ** 11, 10 ** 11 + 1000))
    with pytest.raises(mstate.Invalid, match="does not fit in one console line") as e:
        mseries.arm_script(tmp_path, far, None, None, 1, far)
    assert e.value.code == "bad_argument"


def test_the_reply_names_its_crop_and_the_consoles_account(console: _Console,
                                                          tmp_path: Path) -> None:
    out = _capture(tmp_path)
    assert out["crop"] == [0, 0, W, H] and out["thread_errors"] == 0
    assert out["resent"] == 0 and out["console_reruns"] == 0


@pytest.mark.parametrize("text, said", [
    ("half a line", "is not whole"),
    ("frame=101 read_at=102 skipped=0\nMCP_SERIES_ERROR no screen bitmap", "raised: no screen"),
])
def test_a_frame_file_that_is_not_whole_or_carries_an_error_is_refused(
        console: _Console, tmp_path: Path, text: str, said: str) -> None:
    def broken(folder: Path, f: int) -> None:
        (folder / f"raw-{f}.txt").write_text(text)
    console.kept, console.dump = [101], broken
    with pytest.raises(mstate.Invalid, match=said):
        _capture(tmp_path, first=None, last=None, step=1, frames=[101])


def test_pens_saved_short_of_the_screens_are_refused(console: _Console, tmp_path: Path) -> None:
    def short(folder: Path, f: int) -> None:
        _indexed(folder, f, f + 1)
        (folder / f"raw-{f}.pens").write_bytes(array("I", PENS_AT_END[:1]).tobytes())
    console.kept, console.dump = [101], short
    with pytest.raises(mstate.Invalid, match="1 pens were saved at frame 101"):
        _capture(tmp_path, first=None, last=None, step=1, frames=[101])


def test_a_run_that_raised_takes_the_notifier_down_and_a_failing_finish_is_not_the_answer(
        console: _Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any, **__: Any) -> dict[str, Any]:
        raise mstate.Invalid("session_broken", "the channel died")
    monkeypatch.setattr(madvance, "run_for", boom)
    real = console.run

    def finish_fails(ses: Any, scratch: Path, script: str, seconds: float, progress: Any,
                     what: str) -> tuple[str, dict[str, Any]]:
        if what == "series finish":
            console.finished += 1
            raise mstate.Invalid("unexpected_answer", "the finish failed too")
        return real(ses, scratch, script, seconds, progress, what)
    monkeypatch.setattr(mchunk, "run", finish_fails)
    with pytest.raises(mstate.Invalid, match="the channel died"):
        _capture(tmp_path)
    assert console.finished == 1


def test_a_machine_left_running_is_not_sent_the_finish_after_a_failed_arming(
        console: _Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    session.running = True
    console.armed = "nothing\n"
    with pytest.raises(mstate.Invalid, match="printed no series"):
        mseries.series_capture(session, tmp_path, None, 101, 105, 2, None, "", 10.0)  # type: ignore[arg-type]
    assert console.finished == 0
