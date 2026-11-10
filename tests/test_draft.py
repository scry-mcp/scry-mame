"""The discovery of an unknown board: the correlation, the draft, its report, and the schema's
additions the draft needs.

THE KNOWN ANSWER IS CAPTURED from the blind run on `circus` in attract (a stock MAME): a capture of
RAM `0x00..0x3f` on every write to the port `0x2000` (`circus-clown-rows-txt.gz`, as the capture's
tap wrote it, in rows of six fields that `with_stamps` completes with a line and a time the
correlation never reads) and the `gfx_locate` answers over the whole screen for `gfx2`'s 16x16
candidates (`circus-clown-locates-json.gz`, as `evidence.record_locate` keeps them). On those
frames exactly one reading held: the clown's x is `240 - byte 10` and its y `239 - byte 11`, the
row of frame F-1 drawing the picture of frame F; no byte of the block holds its tile. The driver,
read only after the draft existed, draws it at `256 - clown_y - 16` and `256 - clown_x - 16 - 1`.
"""

from __future__ import annotations

import copy
import gzip
import json
import random
import re
from pathlib import Path
from typing import Any

import pytest
from lua_support import _channel, _ChannelSession  # noqa: E402
from scry_core.host_program import MODE_BITS  # noqa: E402
from session_doubles import refused, with_stamps  # noqa: E402

from scry_mame import blits as mblits  # noqa: E402
from scry_mame import capture  # noqa: E402
from scry_mame import correlate as corr  # noqa: E402
from scry_mame import draft as mdraft  # noqa: E402
from scry_mame import manifest as mm  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402
from scry_mame import yaml as mame_yaml  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "gfx"
DRAFT_FIX = Path(__file__).parent / "fixtures" / "draft"
HEADER = ("MCP_CAPTURE 0_64_t2000 seq=420 frame=1020 total=415 rows=415 overflow_rows=0 "
          "data_width=8 endianness=little cpu=:maincpu\nend\n")
WIDTH = 64


def _locates() -> list[dict[str, Any]]:
    """The run's answers as they were kept, before the evidence said which candidates searched
    their whole block: every one of that run's replies has `tiles_searched` equal to
    `[0, tiles_available]`, so each says so here."""
    locs = list(json.loads(gzip.decompress((FIX / "circus-clown-locates-json.gz").read_bytes())))
    for loc in _renamed(locs):
        loc["searched_whole"] = [True] * len(loc["candidates"])
    return locs


def _renamed(locs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Captured locates, the frame moved to the name a reply gives it now: the runs kept it under
    the name the reply had then, `screen_frame`."""
    for loc in locs:
        loc["frame_screen"] = loc.pop("screen_frame")
    return locs


def _rows_text() -> str:
    return with_stamps(gzip.decompress((FIX / "circus-clown-rows-txt.gz").read_bytes()).decode())


def _events() -> list[corr.Event]:
    return [corr.Event(loc["n"], loc["frame_screen"], loc["matches"][0]["window"][0],
                       loc["matches"][0]["window"][1], loc["matches"][0]["tile"])
            for loc in _locates() if loc["matches_total"] == 1]


def _rows(text: str) -> list[tuple[int, bytes]]:
    out = []
    for line in text.splitlines():
        _, _, frame, _, _, _, _, _, block = line.split(" ")
        out.append((int(frame), bytes.fromhex(block)))
    return out


def _captured(ses: _ChannelSession, rows: str, addr: int = 0,
              trigger: int = 0x2000) -> dict[str, Any]:
    """The record `watch_add` leaves for the capture once installed, and the files the periodic
    hook wrote where it says."""
    cid = capture.id_for(":maincpu", addr, WIDTH, trigger)
    head, rows_path = capture.paths(ses.scratch, cid)
    head.write_text(HEADER.replace("0_64_t2000", cid))
    rows_path.write_text(rows)
    rec = {"tally_id": cid, "installed": True, "lost": False, "cpu": ":maincpu", "resent": 0,
           "path": head, "rows_path": rows_path, "addr": addr, "width": WIDTH, "trigger": trigger,
           "source": capture.TapSource("share", "ram", addr), "last_total": 0, "last_seq": 0}
    mstate.STATE.tallies[(f"{addr:x}", ":maincpu")] = rec
    return rec


def _circus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _ChannelSession:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    mstate.STATE.evidence["locates"][:] = _locates()
    _captured(ses, _rows_text())
    return ses


# ------------------------------------------------------------------ the correlation

def test_the_clowns_coordinates_are_found_reversed_at_one_frames_lag() -> None:
    out = corr.correlate(corr.frames(_rows(_rows_text()), 1, "little"), _events(), 1, WIDTH)
    assert out["lag"] == 1, out.get("why")
    f = out["fields"]
    assert f["dest_x"] == {"status": "proved", "word": 10, "mask": "0xff", "role": "dest_x",
                           "sign": -1, "add": 240}
    assert f["dest_y"] == {"status": "proved", "word": 11, "mask": "0xff", "role": "dest_y",
                           "sign": -1, "add": 239}
    assert f["source_tile"]["status"] == "none", "no byte holds the tile at the group's lag"
    assert {(h["word"], h["lag"]) for h in f["source_tile"]["elsewhere"]} == {(32, 0)}, (
        "the pose's byte is written after the trigger, a frame off from x and y")
    assert out["lags"][1]["paired"] == 30, out["lags"]
    assert all(h["role"] == "source_tile" for k, lag in out["lags"].items() if k != 1
               for h in lag["holds"]), "x and y hold at one lag only"


def test_a_block_of_random_words_proves_nothing() -> None:
    """The control: the same events against rows whose bytes are noise."""
    rng = random.Random(482)
    rows = [(frame, bytes(rng.randrange(256) for _ in range(WIDTH))) for frame, _ in
            _rows(_rows_text())]
    out = corr.correlate(corr.frames(rows, 1, "little"), _events(), 1, WIDTH)
    assert out["lag"] is None and out["fields"] == {}, out
    assert all(not lag["holds"] for lag in out["lags"].values()), out["lags"]


def _synthetic(xs: list[int], ys: list[int], extra: int | None = None
               ) -> tuple[list[tuple[int, bytes]], list[corr.Event]]:
    """One row a frame from frame 100, byte 0 = x - 5, byte 1 = y, byte 2 = `extra` or x - 5
    again, and each event one frame after its row."""
    rows, events = [], []
    for i, (x, y) in enumerate(zip(xs, ys, strict=True)):
        third = x - 5 if extra is None else extra
        rows.append((100 + i, bytes([x - 5, y, third, 0])))
        events.append(corr.Event(i + 1, 101 + i, x, y, 0))
    return rows, events


def test_an_object_at_a_steady_speed_settles_no_lag() -> None:
    xs = [10 + 2 * i for i in range(8)]
    ys = [50 + 3 * i for i in range(8)]
    rows, events = _synthetic(xs, ys, extra=7)
    out = corr.correlate(corr.frames(rows, 1, "little"), events, 1, 4)
    assert out["lag"] is None and "lags [" in out["why"], out


def test_two_words_holding_one_role_leave_it_ambiguous() -> None:
    rng = random.Random(1)
    xs = [rng.randrange(20, 200) for _ in range(10)]
    ys = [rng.randrange(20, 200) for _ in range(10)]
    rows, events = _synthetic(xs, ys)          # byte 2 repeats byte 0
    out = corr.correlate(corr.frames(rows, 1, "little"), events, 1, 4)
    assert out["lag"] == 1
    assert out["fields"]["dest_x"]["status"] == "ambiguous"
    assert {h["word"] for h in out["fields"]["dest_x"]["holds"]} == {0, 2}
    assert out["fields"]["dest_y"]["status"] == "proved"


@pytest.mark.parametrize("high", [0, 1])
def test_a_byte_is_kept_over_the_word_that_says_the_same(high: int) -> None:
    """On a 16-bit bus a coordinate in a low byte, the high byte never moving: the word and the
    byte agree, and the byte is the claim the events exercised. A high byte that is a constant
    other than 0 gives the word an `add` the byte has not, and changes nothing of that."""
    rng = random.Random(2)
    rows, events = [], []
    for i in range(8):
        x, y = rng.randrange(0, 200), rng.randrange(0, 200)
        rows.append((100 + i, bytes([high, x, 0, y])))        # big-endian words 0xHHxx
        events.append(corr.Event(i + 1, 101 + i, x, y, 0))
    out = corr.correlate(corr.frames(rows, 2, "big"), events, 2, 2)
    assert out["fields"]["dest_x"] == {"status": "proved", "word": 0, "mask": "0x00ff",
                                       "role": "dest_x", "sign": 1, "add": 0}


def test_too_few_paired_events_prove_nothing() -> None:
    rows, events = _synthetic([10, 30, 20], [5, 90, 40], extra=1)
    out = corr.correlate(corr.frames(rows, 1, "little"), events, 1, 4)
    assert out["lag"] is None and out["fields"] == {}, out
    assert max(lag["paired"] for lag in out["lags"].values()) < corr.MIN_PAIRED


# ------------------------------------------------------------------ the draft

def test_the_draft_carries_the_clowns_command_and_loads(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    ses = _circus(monkeypatch, tmp_path)
    out = s.gfx_draft()
    assert out["status"] == "ok", out
    assert out["command_fields"] == {"write_2000": ["dest_x", "dest_y", "height", "width"]}
    assert "write_2000: source_tile holds only at lag [0], the lag of dest_x and dest_y being 1" \
        in " ".join(out["not_proved"])
    assert out["formats"] == {"tiles_16x16x1": "proved"} and out["asset_names"] == ["gfx2"]
    assert not {"draft", "assets", "commands"} & set(out), "the draft's file is `manifest`"
    assert ": 1 format (1 proved), 1 asset, 1 command" in out["summary"], out["summary"]
    text = Path(out["manifest"]["path"]).read_text()
    assert text.split("\n", 1)[0] == mm.DRAFT_MARKER
    assert b"\r" not in Path(out["manifest"]["path"]).read_bytes(), "the same bytes on every host"
    doc = mame_yaml.loads(text)
    cmd = doc["commands"]["write_2000"]
    assert cmd["fire"]["address"] == 0x2000 and "value" not in cmd["fire"]
    assert cmd["fields"]["dest_x"]["parts"] == [{"word": 10, "mask": 255}]
    assert cmd["fields"]["dest_x"]["sign"] == -1 and cmd["fields"]["dest_x"]["add"] == 240
    assert cmd["fields"]["width"]["const"] == 16 and cmd["asset"] == "gfx2"
    assert "fire: {address: 0x2000," in text and "mask: 0xff}" in text, "hex where hex reads"
    for entry in (doc["formats"]["tiles_16x16x1"], cmd["fields"]["dest_x"], cmd["block"]):
        prose = entry["source"].split("evidence in")[0]
        assert not re.search(r"\b\d+\b", prose), f"a figure in the draft's source: {prose}"
    loaded = s.gfx_load(path=out["manifest"]["path"])
    assert loaded["status"] == "ok" and loaded["draft"] is True, loaded
    crlf = tmp_path / "edited-gfx.yaml"            # saved again by an editor that writes CRLF
    crlf.write_bytes(Path(out["manifest"]["path"]).read_bytes().replace(b"\n", b"\r\n"))
    assert s.gfx_load(path=str(crlf))["draft"] is True, "a CRLF draft read as a finished manifest"
    loaded = s.gfx_load(path=out["manifest"]["path"])
    # THE COMMAND READS THE ROWS AS THE CORRELATION DID: the row of frame 606 places the clown
    # where the screen of frame 607 showed it.
    rows = mblits.read_rows(ses.scratch, mm.command("write_2000"), 606, 608)
    assert len(rows.blits) == 1
    assert (rows.blits[0].values["dest_x"], rows.blits[0].values["dest_y"]) == (168, 21)


def _byte_strobe(ses: _ChannelSession, width: int) -> None:
    """The circus capture as a 16-bit big-endian bus would have written it with the trigger
    struck by a BYTE write of 1 at its even address (a 68000's `move.b`): the tap keeps the row,
    its data `0x0100` and its mask the high lane only; `width` bytes of each block."""
    rows = []
    for line in _rows_text().splitlines():
        r, n, frame, beam, at, pc, _data, _mask, block = line.split(" ")
        rows.append(f"{r} {n} {frame} {beam} {at} {pc} 100 ff00 {block[:2 * width]}\n")
    rec = _captured(ses, "".join(rows))
    cid = capture.id_for(":maincpu", 0, width, 0x2000)
    del mstate.STATE.tallies[("0", ":maincpu")]
    head, rows_path = capture.paths(ses.scratch, cid)
    head.write_text(HEADER.replace("0_64_t2000", cid).replace(
        "data_width=8 endianness=little", "data_width=16 endianness=big"))
    rows_path.write_text("".join(rows))
    mstate.STATE.tallies[("0", ":maincpu")] = dict(rec, tally_id=cid, path=head,
                                                   rows_path=rows_path, width=width)


@pytest.mark.parametrize("width", [64, 63])
def test_a_command_struck_by_a_byte_write_reads_its_blits_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, width: int,
) -> None:
    """The draft states the fire value the reader compares: a write that covers only part of
    the fire word states none (every write to it fires), and a block of an odd length, read a
    byte at a time, states the trigger's own byte. Either way `gfx_blits` reads back the rows
    the correlation proved the command on."""
    ses = _circus(monkeypatch, tmp_path)
    _byte_strobe(ses, width)
    out = s.gfx_draft()
    assert out["status"] == "ok", out
    assert "write_2000" in out["command_fields"], out
    doc = mame_yaml.loads(Path(out["manifest"]["path"]).read_text())
    fire = doc["commands"]["write_2000"]["fire"]
    assert fire.get("value") == (None if width == 64 else 1), fire
    assert s.gfx_load(path=out["manifest"]["path"])["status"] == "ok"
    rows = mblits.read_rows(ses.scratch, mm.command("write_2000"), 606, 608)
    assert len(rows.blits) == 1, "the byte write is the command's blit"
    b = rows.blits[0]
    assert (b.values["dest_x"], b.values["dest_y"]) == (168, 21), "read in the bus's order"


def test_the_report_regenerates_byte_for_byte(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    _circus(monkeypatch, tmp_path)
    first = s.gfx_draft()
    again = s.gfx_draft()
    assert first["report"]["sha256"] == again["report"]["sha256"]
    assert first["manifest"]["sha256"] == again["manifest"]["sha256"]
    report = json.loads(Path(first["report"]["path"]).read_text())
    assert report["written_by"] == "gfx_draft" and report["draft"] == "gfx-draft.yaml"
    (corr_entry,) = report["correlations"]
    assert corr_entry["lag"] == 1 and corr_entry["command"] == "write_2000"


def test_a_random_block_writes_no_command(monkeypatch: pytest.MonkeyPatch,
                                          tmp_path: Path) -> None:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    mstate.STATE.evidence["locates"][:] = _locates()
    rng = random.Random(506)
    noise = "".join(f"r {n} {frame} 0 {frame}.{n:018d} 12ef 0 ff {rng.randbytes(WIDTH).hex()}\n"
                    for n, (frame, _) in enumerate(_rows(_rows_text()), 1))
    _captured(ses, noise, addr=0x40, trigger=0x2000)
    out = s.gfx_draft()
    assert out["status"] == "ok" and out["command_fields"] == {}, out
    assert any("no lag" in why for why in out["not_proved"]), out["not_proved"]


def test_a_manifest_is_never_overwritten(monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:
    _circus(monkeypatch, tmp_path)
    confirmed = tmp_path / "gfx.yaml"
    confirmed.write_text("schema: 1\nsystems: [circus]\n")
    out = refused("never overwrites", s.gfx_draft(dest=str(confirmed)))
    assert out["code"] == "bad_argument" and out["marker"] == mm.DRAFT_MARKER
    assert confirmed.read_text() == "schema: 1\nsystems: [circus]\n"
    other = tmp_path / "x-report.json"
    other.write_text('{"written_by": "somebody"}')
    refused("not a report gfx_draft wrote", s.gfx_draft(dest=str(tmp_path / "x.yaml")))


def test_a_draft_is_written_over_a_draft(monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:
    _circus(monkeypatch, tmp_path)
    dest = tmp_path / "circus-gfx.yaml"
    assert s.gfx_draft(dest=str(dest))["status"] == "ok"
    again = s.gfx_draft(dest=str(tmp_path / "Circus_GFX.YAML"))
    assert again["status"] == "ok" and again["manifest"]["path"] == str(dest), again
    assert sorted(p.name for p in tmp_path.glob("[Cc]ircus*")) == [
        "circus-gfx-report.json", "circus-gfx.yaml"]


def test_no_evidence_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _channel(monkeypatch, tmp_path)
    assert refused("no evidence to draft from", s.gfx_draft())["code"] == "needs_call"


def _one(frame: int, layouts: list[dict[str, Any]], matches: list[tuple[str, int, int]],
         tag: str = ":gfx2", shape: list[int] | None = None) -> dict[str, Any]:
    """A locate answer as the evidence keeps one: `matches` as (layout name, x, y)."""
    return {"n": 0, "frame_screen": frame, "palette": ":palette",
            "source": {"kind": "region", "tag": tag, "offset": 0}, "patch": [0, 0, 248, 256],
            "transparent": None, "flips": ["none"], "candidates": layouts,
            "searched_whole": [True] * len(layouts), "matches_total": len(matches),
            "matches": [{"layout": n, "window": [x, y], "tile": 1, "flip": "none", "base": 0,
                         "byte": 32, "shape": shape or [10, 10, 40]} for n, x, y in matches]}


def _evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
              locs: list[dict[str, Any]]) -> None:
    _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    for n, loc in enumerate(locs, 1):
        loc["n"] = n
    mstate.STATE.evidence["locates"][:] = locs


def _layouts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The clown's 16x16 layout, a rival of its size, and an 8x8 one."""
    clown = copy.deepcopy(next(c for loc in _locates() for c in loc["candidates"]
                               if c["name"] == "s4c3"))
    rival = dict(clown, name="rival", xoffset=list(range(16)), yoffset=list(range(0, 256, 16)))
    small = {"name": "small", "width": 8, "height": 8, "planes": 1, "planeoffset": [0],
             "xoffset": list(range(8)), "yoffset": list(range(0, 64, 8)), "charincrement": 64}
    return clown, rival, small


def test_a_rival_tried_beside_it_and_missing_a_window_leaves_the_layout_proved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    clown, rival, _ = _layouts()
    both = [clown, rival]
    _evidence(monkeypatch, tmp_path, [
        _one(700, both, [(clown["name"], 50, 60), (rival["name"], 50, 60)]),
        _one(707, both, [(clown["name"], 90, 60)])])
    out = s.gfx_draft()
    assert out["formats"] == {"tiles_16x16x1": "proved"}, out
    assert any("rival was never told apart" in why for why in out["not_proved"]), out


def test_rivals_never_tried_together_prove_neither(monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    clown, rival, _ = _layouts()
    _evidence(monkeypatch, tmp_path, [_one(700, [clown], [(clown["name"], 50, 60)]),
                                      _one(707, [rival], [(rival["name"], 90, 60)])])
    out = s.gfx_draft()
    assert out["formats"] == {} and len(out["not_proved"]) == 2, out
    report = json.loads(Path(out["report"]["path"]).read_text())
    assert sorted((a["layout"]["name"], a["not_told_apart_from"])
                  for a in report["ambiguous"]) == sorted([(clown["name"], ["rival"]),
                                                           ("rival", [clown["name"]])])


def test_layouts_of_two_sizes_are_both_proved_and_their_assets_say_which(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    clown, _, small = _layouts()
    _evidence(monkeypatch, tmp_path, [
        _one(700, [clown, small], [(clown["name"], 50, 60), (small["name"], 50, 60)])])
    out = s.gfx_draft()
    assert out["formats"] == {"tiles_8x8x1": "proved", "tiles_16x16x1": "proved"}, out
    assert out["asset_names"] == ["gfx2_16x16", "gfx2_8x8"]


@pytest.mark.parametrize(("shape", "failed"), [
    ([1, 16, 16], "rows"), ([16, 1, 16], "cols"), ([2, 2, 1], "rarest"), ([3, 3, 15], "rarest"),
    ([1, 1, 1], "cols, rarest, rows")])
def test_a_flat_or_sparse_window_proves_no_layout(shape: list[int], failed: str,
                                                  monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    clown, _, _ = _layouts()
    _evidence(monkeypatch, tmp_path, [_one(700, [clown], [(clown["name"], 50, 60)],
                                           shape=shape)])
    out = s.gfx_draft()
    assert out["formats"] == {}, out
    assert out["not_proved"] == [f":gfx2: {clown['name']} matched only windows that prove no "
                                 f"layout (failed: {failed})"], out


def test_a_window_another_block_explains_proves_nothing(monkeypatch: pytest.MonkeyPatch,
                                                        tmp_path: Path) -> None:
    """A pixel has one origin: a match overlapping another source's on the same frame is
    contested, while the same match on another frame is not."""
    clown, _, small = _layouts()
    _evidence(monkeypatch, tmp_path, [
        _one(700, [clown], [(clown["name"], 50, 60)]),
        _one(700, [small], [(small["name"], 58, 70)], tag=":gfx1")])
    out = s.gfx_draft()
    assert out["formats"] == {}, out
    report = json.loads(Path(out["report"]["path"]).read_text())
    assert {u["contested"] for u in report["unproving"]} == {1}
    later = _one(701, [small], [(small["name"], 58, 70)], tag=":gfx1")
    mstate.STATE.evidence["locates"][1] = dict(later, n=2)
    assert set(s.gfx_draft(dest=str(tmp_path / "b.yaml"))["formats"]) == {
        "tiles_8x8x1", "tiles_16x16x1"}


@pytest.mark.parametrize("choose", [
    {"candidate": "s1c1"}, {"candidate": "s1c1", "chosen_by": ""},
    {"candidate": "c1", "chosen_by": "me"}, {"candidate": "s1c1", "by": "me"},
    {"candidate": "s1c1", "chosen_by": 'say "x"'},
    {"candidate": "s1c1", "chosen_by": "me", "why": "x"},
    "s1c1", {"candidate": "s1c1", "chosen_by": "a\tb"},
    {"candidate": "s1c1", "chosen_by": "a\u2028b"},
    {"candidate": "s1c1", "chosen_by": "a\x85b"}, {"candidate": "s1c1", "chosen_by": "a\x0bb"},
])
def test_a_choice_is_judged_before_the_machine(choose: Any) -> None:
    refused("choose", s.gfx_draft(choose=choose))


@pytest.mark.parametrize(("dest", "said"), [("relative.yaml", "must be an absolute path"),
                                           ("{tmp}/draft.yml", "a `.yaml` file")])
def test_the_dest_is_judged_before_the_machine(dest: str, said: str, tmp_path: Path) -> None:
    refused(f"dest=.*{said}", s.gfx_draft(dest=dest.format(tmp=tmp_path)))


# ------------------------------------------------------------------ the schema's additions

def _manifest(command: str) -> dict[str, Any]:
    doc: dict[str, Any] = mame_yaml.loads("schema: 1\nsystems: [circus]\ncommands:\n" + command)
    return doc


_CLOWN = """  clown:
    block: {address: 8, words: 8, word_bytes: 1, status: proved, source: s}
    fire: {address: 0x2000, status: proved, source: s}
    fields:
      dest_x:
        parts: [{word: 2, mask: 0xff}]
        sign: -1
        add: 240
        status: proved
        source: s
      dest_y: {parts: [{word: 3, mask: 0xff}], sign: -1, add: 239, status: proved, source: s}
      width: {const: 16, status: proved, source: s}
      height: {const: 16, status: proved, source: s}
"""


def test_a_reversed_coordinate_a_fixed_size_and_an_outside_trigger_load() -> None:
    man = mm.parse(_manifest(_CLOWN), "m", "")
    cmd = man.commands["clown"]
    assert cmd.trigger == 0x2000 and cmd.fire_value is None
    words = [0xFF, 0x03, 0x47, 0xCB, 0, 0xF0, 0, 0xFC]
    assert cmd.fields["dest_x"].value(words) == 240 - 0x47
    assert cmd.fields["dest_y"].value(words) == 239 - 0xCB
    assert cmd.fields["width"].value(words) == 16
    assert man.summary()["commands"]["clown"]["fires_with"] == "any write"


@pytest.mark.parametrize("change,why", [
    (("width: {const: 16,", "width: {const: 16, add: 1,"), "a `const` size reads no bits"),
    (("dest_y: {parts: [{word: 3, mask: 0xff}], sign: -1,",
      "dest_y: {const: 3, sign: -1,"), "dest_y.const: an unknown key"),
    (("sign: -1\n        add: 240", "sign: 2\n        add: 240"), "sign=2: 1, or -1"),
    (("fire: {address: 0x2000,", "fire: {address: 0x2000, word: 1,"), "one of the two"),
    (("fire: {address: 0x2000,", "fire: {word: 1,"), "'value' is missing"),
    (("fire: {address: 0x2000,", "fire: {"), "one of the two"),
    (("      width: {const: 16, status: proved, source: s}\n",
      "      width: {status: proved, source: s}\n"),
     "'parts' is missing; a field reads bits of the block's words (a size the hardware fixes"),
])
def test_the_additions_are_refused_where_they_do_not_apply(change: tuple[str, str],
                                                           why: str) -> None:
    text = _CLOWN.replace(*change)
    assert text != _CLOWN, "the substitution matched nothing"
    with pytest.raises(mm.ManifestError, match=re.escape(why)):
        mm.parse(_manifest(text), "m", "")


def test_an_image_held_twice_still_places_the_object(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    """hardhat's `gfx1` holds each image twice, so every answer matched two tiles in ONE window:
    the object's place is known and its tile is not, and x and y are still proved."""
    ses = _circus(monkeypatch, tmp_path)
    for loc in mstate.STATE.evidence["locates"]:
        if loc["matches_total"] == 1:
            loc["matches"].append(dict(loc["matches"][0], tile=loc["matches"][0]["tile"] + 8))
            loc["matches_total"] = 2
    out = s.gfx_draft()
    assert out["command_fields"] == {"write_2000": ["dest_x", "dest_y", "height", "width"]}, out
    report = json.loads(Path(out["report"]["path"]).read_text())
    (entry,) = report["correlations"]
    assert entry["fields"]["source_tile"] == {"status": "none"}, "no answer knew its tile"
    assert ses.scratch.is_dir()


def test_two_blocks_of_one_tag_keep_an_asset_each(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    """One tag at two offsets, each with its format: two assets, each command naming its own."""
    clown, _, small = _layouts()
    far = _one(700, [small], [(small["name"], 120, 30)])
    far["source"] = dict(far["source"], offset=0x2000)
    _evidence(monkeypatch, tmp_path, [_one(700, [clown], [(clown["name"], 50, 60)]), far])
    out = s.gfx_draft()
    assert len(out["asset_names"]) == 2, out
    doc = mame_yaml.loads(Path(out["manifest"]["path"]).read_text())
    assert {n: a.get("offset", 0) for n, a in doc["assets"].items()} == {
        "gfx2": 0, "gfx2_at2000": 0x2000}, "the offset names the second one only"


def test_a_nested_device_tag_still_makes_a_draft_that_loads(monkeypatch: pytest.MonkeyPatch,
                                                            tmp_path: Path) -> None:
    clown, _, _ = _layouts()
    _evidence(monkeypatch, tmp_path, [_one(700, [clown], [(clown["name"], 50, 60)],
                                           tag=":sub:gfx1")])
    out = s.gfx_draft()
    assert out["status"] == "ok" and out["asset_names"] == ["sub_gfx1"], out


def test_an_answer_cut_at_the_kept_matches_tells_no_rival_apart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The rival's match at the second window may be among the ones not kept, so a cut answer
    cannot say the rival missed it."""
    clown, rival, _ = _layouts()
    both = [clown, rival]
    cut = _one(707, both, [(clown["name"], 90, 60)])
    cut["matches_total"] = 5000
    _evidence(monkeypatch, tmp_path, [
        _one(700, both, [(clown["name"], 50, 60), (rival["name"], 50, 60)]), cut])
    out = s.gfx_draft()
    assert out["formats"] == {}, out


def test_the_draft_does_not_move_with_the_line_and_time_a_row_carries(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The correlation reads a row's frame, data and block: the same rows under two other lines
    and times draft the same commands."""
    _circus(monkeypatch, tmp_path)
    first = s.gfx_draft()["command_fields"]
    (rec,) = [r for r in mstate.STATE.tallies.values() if r.get("trigger") is not None]
    Path(rec["rows_path"]).write_text(with_stamps(gzip.decompress(
        (FIX / "circus-clown-rows-txt.gz").read_bytes()).decode(), 7).replace(" -1 ", " 3 "))
    again = s.gfx_draft()["command_fields"]
    assert first and again == first


def test_every_command_a_capture_proves_is_written(monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    """One capture proving the same object against three groups of one tag: three commands."""
    ses = _circus(monkeypatch, tmp_path)
    locs = mstate.STATE.evidence["locates"]
    for offset in (0x100, 0x200):
        for loc in list(locs):
            if loc["source"]["offset"] == 0 and loc["matches_total"] == 1:
                locs.append(dict(loc, n=len(locs) + 1,
                                 source=dict(loc["source"], offset=offset)))
    out = s.gfx_draft()
    assert len(out["command_fields"]) == 3, out["command_fields"]
    assert ses.scratch.is_dir()


@pytest.mark.parametrize("reasons", [mdraft.NOT_PROVED_SHOWN, 12])
def test_the_summary_counts_every_reason_not_proved(reasons: int,
                                                    monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    """The reply shows the first reasons and counts the rest; as many as it shows leave none
    to count."""
    clown, _, _ = _layouts()
    locs = []
    for i in range(reasons):
        loc = _one(700 + i, [clown], [(clown["name"], 50, 60)], shape=[1, 16, 16])
        loc["source"] = dict(loc["source"], offset=0x100 * i)
        locs.append(loc)
    _evidence(monkeypatch, tmp_path, locs)
    out = s.gfx_draft()
    shown = min(reasons, mdraft.NOT_PROVED_SHOWN)
    assert len(out["not_proved"]) == shown and out.get("not_proved_more") == (
        reasons - shown or None), out
    assert out["summary"].endswith(f"{reasons} not proved"), out["summary"]


def test_a_role_ambiguous_at_the_lag_is_not_said_to_hold_only_elsewhere() -> None:
    held = {"status": "ambiguous", "elsewhere": [{"lag": 0, "word": 3}]}
    assert mdraft.elsewhere_reason("write_2000", "source_tile", held, 1) == (
        "write_2000: source_tile is ambiguous at lag 1 and also holds at lag [0], the lag of "
        "dest_x and dest_y being 1; see the report")
    assert "holds only at lag [0]" in mdraft.elsewhere_reason(
        "c", "source_tile", dict(held, status="none"), 1)


@pytest.mark.parametrize("which", ["draft", "report"])
def test_a_directory_where_a_file_goes_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path, which: str) -> None:
    _circus(monkeypatch, tmp_path)
    dest = tmp_path / "circus-gfx.yaml"
    (dest if which == "draft" else mdraft.report_path(dest)).mkdir()
    out = refused("is a directory", s.gfx_draft(dest=str(dest)))
    assert out["code"] == "bad_argument"


@MODE_BITS
@pytest.mark.parametrize("which", ["draft", "report"])
def test_a_file_that_cannot_be_read_where_a_file_goes_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, which: str,
) -> None:
    """Whether an unreadable file is a draft, or a report this wrote, cannot be told, so it is
    not overwritten."""
    _circus(monkeypatch, tmp_path)
    dest = tmp_path / "circus-gfx.yaml"
    target = dest if which == "draft" else mdraft.report_path(dest)
    target.write_text("x")
    target.chmod(0)
    try:
        out = refused("cannot be read" if which == "draft" else "not a report gfx_draft wrote",
                      s.gfx_draft(dest=str(dest)))
    finally:
        target.chmod(0o600)
    assert out["code"] == "bad_argument" and target.read_text() == "x"


def test_two_ranges_of_a_cpus_space_are_two_sources() -> None:
    """A block read through `ref` is named by its address and its cpu, not only by the space:
    two ranges, or one range on two cpus, are different blocks to the draft."""
    from scry_mame import evidence, gfx
    space = gfx.Block("space", "program", 0x100, 1, "big", b"")
    keys = {evidence.SourceKey.of(evidence.source_of(gfx.source_fields(space, 0, addr, cpu)))
            for addr, cpu in ((0x1000, ":maincpu"), (0x8000, ":maincpu"), (0x1000, ":sub"))}
    assert len(keys) == 3, keys
    region = evidence.source_of(gfx.source_fields(gfx.Block("region", ":gfx1", 8, 1, "big", b""),
                                                  0, None, ""))
    assert evidence.SourceKey.of(region).reply() == region, "a region says no addr"


@pytest.mark.parametrize(("kind", "tag", "addr"), [("share", "ram", None),
                                                  ("region", ":gfx1", None),
                                                  ("space", "program", 0x1000)])
def test_the_evidence_key_is_read_from_the_fields_a_graphics_reply_carries(
    kind: str, tag: str, addr: int | None,
) -> None:
    """The key is built from a reply's `source_fields`: a share or a region read by `tag` names
    its kind, tag and offset, a range read by `ref` its address and cpu as well. A field the key
    names and no reply carries would be the empty string on every key, telling no block apart."""
    from scry_mame import evidence, gfx
    assert evidence.SourceKey._fields == evidence.SOURCE_FIELDS
    fields = gfx.source_fields(gfx.Block(kind, tag, 0x100, 1, "big", b""), 0, addr, ":maincpu")
    carried = evidence.SOURCE_FIELDS if addr is not None else evidence.SOURCE_FIELDS[:3]
    missing = set(carried) - set(fields)
    assert not missing, sorted(missing)
    kept = evidence.source_of(fields)
    assert evidence.SourceKey.of(kept).reply() == kept, "the key says what the reply said"


def test_a_rival_searched_over_part_of_its_block_is_not_told_apart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The rival matched nothing at the second window, but that answer searched only some of its
    tiles (`first`, `count`, or the cap): the tile that would have matched may lie outside them,
    so nothing tells the two apart."""
    clown, rival, _ = _layouts()
    both = [clown, rival]
    part = _one(707, both, [(clown["name"], 90, 60)])
    part["searched_whole"] = [True, False]
    _evidence(monkeypatch, tmp_path, [
        _one(700, both, [(clown["name"], 50, 60), (rival["name"], 50, 60)]), part])
    out = s.gfx_draft()
    assert out["formats"] == {}, out
    assert any("never told apart" in why for why in out["not_proved"]), out


def test_a_dest_that_cannot_be_written_is_refused_by_name(monkeypatch: pytest.MonkeyPatch,
                                                          tmp_path: Path) -> None:
    _circus(monkeypatch, tmp_path)
    afile = tmp_path / "afile"
    afile.write_text("x")
    out = refused("is not a directory", s.gfx_draft(dest=str(afile / "circus-gfx.yaml")))
    assert out["code"] == "bad_argument" and str(afile) in out["message"]


def test_a_report_that_fails_to_write_leaves_no_new_draft_beside_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The draft and its report land together or not at all: a draft whose report is missing,
    or is an older one, would cite evidence that is not the draft's."""
    _circus(monkeypatch, tmp_path)
    dest = tmp_path / "circus-gfx.yaml"
    real = Path.write_text

    def failing(self: Path, *a: Any, **k: Any) -> int:
        if self.name.startswith(mdraft.report_path(dest).name):
            raise OSError(28, "No space left on device")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", failing)
    assert refused("cannot be written", s.gfx_draft(dest=str(dest)))["code"] == "host_failed"
    assert not dest.exists(), "a draft landed without its report"
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == [], "a half pair is left"


def test_a_format_proved_through_a_pen_map_is_proved_and_its_asset_is_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A pen map proves the format and the tile, never a pen base: the format is written proved,
    and the asset, which would need the base, is named as not proved with the reason."""
    clown, _, _ = _layouts()
    loc = _one(700, [clown], [(clown["name"], 50, 60)])
    loc["matches"][0].update(base=None, pen_map=[[0, 0], [5, 1]])
    _evidence(monkeypatch, tmp_path, [loc])
    out = s.gfx_draft()
    assert out["status"] == "ok", out
    assert out["formats"] == {"tiles_16x16x1": "proved"} and out["asset_names"] == [], out
    assert any("pen map" in why for why in out["not_proved"]), out["not_proved"]
    assert s.gfx_load(path=out["manifest"]["path"])["status"] == "ok"


def test_one_byte_holding_both_coordinates_assigns_neither() -> None:
    """A unit holding two roles is ambiguous for both: y = x + 5 on every event makes byte 0 hold
    `dest_x` and `dest_y` at once, and neither may be written as proved."""
    rng = random.Random(3)
    rows, events = [], []
    for i in range(8):
        x = rng.randrange(20, 200)
        rows.append((100 + i, bytes([x, 7, 0, 0])))
        events.append(corr.Event(i + 1, 101 + i, x, x + 5, 0))
    out = corr.correlate(corr.frames(rows, 1, "little"), events, 1, 4)
    assert out["lag"] == 1, out
    for role in ("dest_x", "dest_y"):
        assert out["fields"][role]["status"] == "ambiguous", out["fields"][role]
        assert "also holds" in out["fields"][role]["why"]


def test_the_events_left_unpaired_are_counted_by_reason() -> None:
    """At lag 1 an event whose frame before has no row, and one whose frame before has two, are
    each counted under their own reason, never paired."""
    rows, events = _synthetic([10, 30, 20, 50, 40, 60], [5, 90, 40, 15, 70, 25], extra=1)
    rows = [r for r in rows if r[0] != 102] + [(104, bytes([1, 2, 3, 4]))]
    out = corr.correlate(corr.frames(rows, 1, "little"), events, 1, 4)
    lag1 = out["lags"][1]
    assert (lag1["no_row"], lag1["several_rows"]) == (1, 1), lag1
    assert lag1["paired"] == len(events) - 2


# ------------------------------------------------------------------ the pieces, at their edges

def test_a_rectangle_is_indexed_by_every_square_it_covers_and_no_other() -> None:
    cell = mdraft.CELL
    assert mdraft._cells(0, 0, 0, cell, cell) == [(0, 0, 0)]
    assert mdraft._cells(0, 0, 0, cell + 1, 4) == [(0, 0, 0), (0, 1, 0)]
    assert mdraft._cells(0, 0, 0, 4, cell + 1) == [(0, 0, 0), (0, 0, 1)]
    assert mdraft._cells(7, 2 * cell, 3 * cell, 4, 4) == [(7, 2, 3)]
    assert mdraft._cells(0, cell - 1, 0, 2, 2) == [(0, 0, 0), (0, 1, 0)]


def test_a_name_is_suffixed_until_it_is_free() -> None:
    assert mdraft._unique({}, "foo") == "foo"
    assert mdraft._unique({"foo": 1}, "foo") == "foo_2"
    assert mdraft._unique({"foo": 1, "foo_2": 1}, "foo") == "foo_3"


def test_a_window_proves_its_layout_at_the_least_it_needs() -> None:
    """Proof by shape alone: one plane, where uniqueness is never asked."""
    need = mdraft.AXES_MIN
    assert _judged([need, need, 10], planes=1, side=10) == set()
    assert _judged([need - 1, need, 10], planes=1, side=10) == {"rows"}
    assert _judged([need, need - 1, 10], planes=1, side=10) == {"cols"}
    assert _judged([need, need, 9], planes=1, side=10) == {"rarest"}


# ------------------------------------------------------------------ proof by uniqueness

def _v30(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """The draft of the two v30 answers (`fixtures/draft/PROVENANCE.txt`): a digit matched
    once over its whole table, and the INSERT COINS strip matched in many windows."""
    locs = json.loads(gzip.decompress((DRAFT_FIX / "v30-locates-json.gz").read_bytes()))
    _evidence(monkeypatch, tmp_path, _renamed(locs))
    monkeypatch.setattr(mstate.STATE, "system", "v30")
    out: dict[str, Any] = s.gfx_draft()
    return out


def test_a_unique_match_over_a_whole_8bpp_search_proves_its_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The digit's window varies along both axes with its rarest pen short of the tile's side:
    its one match over every tile of the table proves the layout."""
    out = _v30(monkeypatch, tmp_path)
    assert out["formats"] == {"tiles_24x24x8": "proved"}, out
    entry = _report(out)["formats"]["tiles_24x24x8"]
    assert [(e["status"], e["proved_by"], e["tiles"]) for e in entry] == [("proved", [1], [1])]


def test_a_strip_matched_many_times_stays_unproved_naming_what_it_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    out = _v30(monkeypatch, tmp_path)
    rows = [u for u in _report(out)["unproving"] if u["layout"] == "coins8"]
    assert [(u["flat"], u["causes"], u["contested"]) for u in rows] == [
        (35, {"cols": 8, "rarest": 27}, 0)], rows
    assert ("program: coins8 matched only windows that prove no layout (failed: cols, "
            "rarest)") in out["not_proved"], out


def _deep(width: int) -> dict[str, Any]:
    """A layout of 8 planes, one byte a pixel, `width` pixels a side."""
    return {"name": f"deep{width}", "width": width, "height": width, "planes": 8,
            "planeoffset": list(range(8)), "xoffset": list(range(0, 8 * width, 8)),
            "yoffset": list(range(0, 8 * width * width, 8 * width)),
            "charincrement": 8 * width * width}


def test_two_layouts_each_matched_once_in_one_answer_are_each_unique(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Uniqueness is the layout's own over its search: a layout of another size matching once
    beside it in the same answer takes nothing from it."""
    small, big = _deep(8), _deep(16)
    loc = _one(700, [small, big], [(small["name"], 10, 10), (big["name"], 100, 60)])
    # each rarest pen short of its side, so neither proves by shape, and at half of it
    loc["matches"][0]["shape"], loc["matches"][1]["shape"] = [4, 4, 4], [4, 4, 8]
    _evidence(monkeypatch, tmp_path, [loc])
    assert s.gfx_draft()["formats"] == {"tiles_8x8x8": "proved", "tiles_16x16x8": "proved"}


def test_a_window_flat_along_an_axis_names_that_and_nothing_uniqueness_asks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """No search proves a window that does not vary along an axis, so its causes stop there."""
    deep = _deep(8)
    _evidence(monkeypatch, tmp_path, [_one(700, [deep], [
        (deep["name"], 10, 10), (deep["name"], 30, 10)], shape=[1, 4, 1])])
    out = s.gfx_draft()
    assert out["not_proved"] == [":gfx2: deep8 matched only windows that prove no layout "
                                 "(failed: rarest, rows)"], out
    assert [u["causes"] for u in _report(out)["unproving"]] == [{"rarest": 2, "rows": 2}]


def _judged(shape: list[int], planes: int = 8, total: int = 1, kept: int | None = None,
            whole: tuple[bool, ...] | None = (True,), at: int = 0, side: int = 24) -> set[str]:
    """What `_failed` names for a match of `shape` under candidate `at`, every candidate a
    `side`-pixel square of `planes`, in an answer of `total` matches of that layout (`kept` of
    them recorded) whose candidates searched their blocks as `whole` says (None: not said)."""
    cands = [{"name": f"c{k}", "width": side, "height": side, "planes": planes}
             for k in range(len(whole or (True,)))]
    loc: dict[str, Any] = {"candidates": cands, "matches_total": total,
                           "matches": [{"layout": f"c{at}"}] * (total if kept is None else kept)}
    if whole is not None:
        loc["searched_whole"] = list(whole)
    return mdraft._failed({"shape": shape, "layout": f"c{at}"}, loc)


@pytest.mark.parametrize(("case", "failed"), [
    ({"shape": [2, 2, 24], "planes": 1, "total": 9, "whole": (False,)}, set()),
    ({"shape": [2, 2, 24], "planes": 8, "total": 9, "whole": (False,)}, set()),
    ({"shape": [2, 2, 23], "planes": 2}, {"rarest"}),
    ({"shape": [2, 2, 12], "planes": 3}, set()),
    ({"shape": [2, 2, 11], "planes": 3}, {"rarest"}),
    ({"shape": [2, 2, 1], "planes": 8}, {"rarest"}),
    ({"shape": [2, 2, 12], "planes": 8, "total": 2}, {"rarest", "not_unique"}),
    ({"shape": [2, 2, 12], "planes": 8, "total": 5, "kept": 1}, {"rarest", "not_unique"}),
    ({"shape": [2, 2, 12], "planes": 8, "whole": (False,)}, {"rarest", "partial_search"}),
    ({"shape": [2, 2, 12], "planes": 8, "whole": None}, {"rarest", "partial_search"}),
    ({"shape": [2, 2, 12], "planes": 8, "total": 2, "whole": (False,)},
     {"rarest", "not_unique", "partial_search"}),
    ({"shape": [2, 2, 1], "planes": 8, "total": 2, "whole": (False,)}, {"rarest"}),
    ({"shape": [1, 2, 24], "planes": 8, "total": 2}, {"rows"}),
    ({"shape": [2, 1, 1], "planes": 8}, {"cols", "rarest"}),
    ({"shape": [2, 2, 12], "planes": 8, "whole": (False, True), "at": 1}, set()),
    ({"shape": [2, 2, 12], "planes": 8, "whole": (True, False), "at": 1},
     {"rarest", "partial_search"}),
])
def test_a_window_fails_the_conditions_it_misses_by_shape_and_by_uniqueness(
    case: dict[str, Any], failed: set[str],
) -> None:
    """Proof by shape at its least at any depth, proof by uniqueness from three planes for a window
    that varies along both axes with its rarest pen over half the tile's longer side, and each of
    its conditions read for the match's own layout. Below that half uniqueness is not asked."""
    assert _judged(**case) == failed


@pytest.mark.parametrize(("known", "shape", "side", "failed"), [
    ("the digit, 24x24x8", [13, 10, 14], 24, set()),
    ("INSERT COINS cut to its first window", [8, 2, 1], 8, {"rarest"}),
    ("INSERT COINS, its most varied window", [8, 7, 2], 8, {"rarest"}),
    ("INSERT COINS, its commonest rarest pen", [8, 4, 3], 8, {"rarest"}),
])
def test_the_measured_known_answers_fall_each_side_of_the_rarest_floor(
    known: str, shape: list[int], side: int, failed: set[str],
) -> None:
    """The shapes v30's known answers gave live: each matched once over a search of one
    window, and the digit's search held fewer tiles than the strip's, so neither the windows
    tried nor the tiles searched tell them apart. The rarest pen does (the strip's row gradient
    is in every tile of the font and tells nothing apart). Uniqueness stands in for the rarest
    pen only down to half the longer side, so the digit proves and no window of the strip does,
    whole or cut to one."""
    assert _judged(shape, planes=8, side=side) == failed, known


def test_a_strip_cut_to_one_window_proves_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """INSERT COINS's first window alone, as v30 answered it: one match over the strip's
    tiles, two distinct columns and a one-pixel rarest pen. It proves nothing, and says why."""
    coins = _deep(8)
    loc = _one(23, [coins], [(coins["name"], 84, 8)], tag="program", shape=[8, 2, 1])
    loc["matches"][0]["compared"] = 64
    _evidence(monkeypatch, tmp_path, [loc])
    out = s.gfx_draft()
    assert out["formats"] == {}, out
    assert [u["causes"] for u in _report(out)["unproving"]] == [{"rarest": 1}], out


def test_the_bus_words_are_read_in_their_order_and_a_partial_one_is_dropped() -> None:
    assert corr.split_words(bytes([0x01, 0x02]), 2, "little") == [0x0201]
    assert corr.split_words(bytes([0x01, 0x02]), 2, "big") == [0x0102]
    assert corr.split_words(bytes(range(8)), 3, "little") == [0x020100, 0x050403]


def test_a_role_holds_at_the_fewest_events_and_values_it_needs() -> None:
    """Exactly MIN_PAIRED events and MIN_VALUES distinct values of y: y holds, and a role that
    misses them (x never moving) does not stop the next role from being judged."""
    xs = [40] * corr.MIN_PAIRED
    ys = [10, 20, 10, 20][:corr.MIN_PAIRED]
    rows, events = [], []
    for i, (x, y) in enumerate(zip(xs, ys, strict=True)):
        rows.append((100 + i, bytes([x, y, 0, 0])))
        events.append(corr.Event(i + 1, 101 + i, x, y, 0))
    holding = corr._holding(corr._pair(events, corr.frames(rows, 1, "little"), 1)[0],
                            corr.units(4, 1))
    assert {h.role for h in holding} >= {"dest_y"}, holding
    assert "dest_x" not in {h.role for h in holding}, "x never moved"


def test_every_unpaired_event_is_counted() -> None:
    rows, events = _synthetic([10, 30, 20, 50, 40, 60, 70], [5, 90, 40, 15, 70, 25, 35], extra=1)
    rows = [r for r in rows if r[0] not in (102, 103)]
    rows += [(104, bytes([1, 2, 3, 4])), (105, bytes([1, 2, 3, 4]))]
    lag1 = corr.correlate(corr.frames(rows, 1, "little"), events, 1, 4)["lags"][1]
    assert (lag1["no_row"], lag1["several_rows"]) == (2, 2), lag1


def test_the_draft_cites_its_command_and_report_in_every_source(monkeypatch: pytest.MonkeyPatch,
                                                                tmp_path: Path) -> None:
    _circus(monkeypatch, tmp_path)
    out = s.gfx_draft()
    doc = mame_yaml.loads(Path(out["manifest"]["path"]).read_text())
    cmd = doc["commands"]["write_2000"]
    for entry in (cmd["fire"], cmd["block"], cmd["fields"]["dest_x"], cmd["fields"]["width"],
                  cmd["fields"]["height"]):
        assert "gfx-draft-report.json, commands.write_2000" in entry["source"], entry
    assert cmd["block"]["cpu"] == "maincpu"
    fmt = doc["formats"]["tiles_16x16x1"]
    assert "on gfx2" in fmt["source"] and "gfx-draft-report.json" in fmt["source"]
    report_text = Path(out["report"]["path"]).read_text()
    report = json.loads(report_text)
    assert report_text.startswith('{\n "') and list(report) == sorted(report), "sorted, indent 1"
    entry = report["formats"]["tiles_16x16x1"][0]
    assert {"proved_by", "tiles", "bases", "palette"} <= set(entry) and entry["bases"] == [0]
    assert entry["tiles"] and None not in entry["tiles"]
    assert entry["proved_by"] and entry["palette"] == ":palette", entry
    assert report["unproving"] == [], "every clown window proves its layout"
    assert report["assets"]["gfx2"]["format"] == "tiles_16x16x1"
    assert doc["assets"]["gfx2"]["source"].startswith(
        "the matches that prove its format were drawn through these pens; evidence in")
    assert cmd["fields"]["width"]["const"] == cmd["fields"]["height"]["const"] == 16
    cap = report["correlations"][0]["capture"]
    assert (cap["endianness"], cap["word_bytes"], cap["addr"]) == ("little", 1, "0x00000000"), cap
    assert cap["trigger_addr"].startswith("0x") and len(cap["trigger_addr"]) == 10, cap
    assert "trigger" not in cap, "one trigger key in the evidence, the resolved address"
    assert cap["rows_kept"] > 0 and "rows" not in cap, "the rows the file keeps, as palette_log's"
    assert report["correlations"][0]["group"]["format"] == "tiles_16x16x1"


def test_a_correlation_against_a_capture_whose_tap_raised_carries_its_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The rows a correlation reads are short of the writes by the count the capture names, and
    the report says so beside them; a header from before the guard says nothing either way."""
    _circus(monkeypatch, tmp_path)
    head = next(iter(mstate.STATE.tallies.values()))["path"]
    text = head.read_text()
    head.write_text(text.replace("cpu=:maincpu\n", "cpu=:maincpu errors=3\ne mcp:44: oops\n"))
    assert head.read_text() != text
    out = s.gfx_draft()
    report = json.loads(Path(out["report"]["path"]).read_text())
    assert report["correlations"][0]["capture"]["callback_errors"] == {
        "count": 3, "first": "mcp:44: oops"}
    # rows its tap never kept were never paired, so nothing is proved from them
    assert all(c["command"] is None for c in report["correlations"]), report["correlations"]
    assert any("its callbacks raised 3 times (the first: mcp:44: oops), so its rows are short"
               in why for why in report["not_proved"]), report["not_proved"]
    head.write_text(text)
    report = json.loads(Path(s.gfx_draft()["report"]["path"]).read_text())
    assert "callback_errors" not in report["correlations"][0]["capture"]


def test_a_draft_goes_where_its_dest_says_and_makes_no_directory(monkeypatch: pytest.MonkeyPatch,
                                                                  tmp_path: Path) -> None:
    _circus(monkeypatch, tmp_path)
    (tmp_path / "sub1").mkdir()
    dest = tmp_path / "sub1" / "circus-gfx.yaml"
    assert s.gfx_draft(dest=str(dest))["status"] == "ok" and dest.is_file()
    refused("is not a directory", s.gfx_draft(dest=str(tmp_path / "sub2" / "circus-gfx.yaml")))
    assert not (tmp_path / "sub2").exists()


@pytest.mark.parametrize(("by", "ok"), [("x" * mdraft.BY_MAX, True), ("X", True),
                                        ("x" * (mdraft.BY_MAX + 1), False),
                                        ("Max", True), ("María", True)])
def test_who_chose_is_one_printable_line_of_bounded_length(by: str, ok: bool) -> None:
    choose = {"candidate": "s1c1", "chosen_by": by}
    if ok:
        mdraft.check_gfx_draft(choose=choose)
    else:
        with pytest.raises(mstate.Invalid, match="choose.chosen_by"):
            mdraft.check_gfx_draft(choose=choose)


def _sweeps(counts: list[int]) -> None:
    """Sweeps as the evidence keeps them, each of `counts[i]` candidates of one 8x8 layout."""
    raw = {"width": 8, "height": 8, "planes": 1, "planeoffset": [0], "xoffset": list(range(8)),
           "yoffset": list(range(0, 64, 8)), "charincrement": 64}
    mstate.STATE.evidence["sweeps"][:] = [
        {"n": n, "candidates": [{"id": f"s{n}c{k}", "raw": dict(raw, name=f"x{n}_{k}"),
                                 "what": "1bpp"} for k in range(1, count + 1)]}
        for n, count in enumerate(counts, 1)]


def test_a_sweep_id_names_a_candidate_of_its_own_sweep(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    from scry_mame import evidence
    _channel(monkeypatch, tmp_path)
    _sweeps([2, 3])
    found = evidence.find_candidate("s1c2")
    assert found is not None and found[0]["n"] == 1 and found[1]["id"] == "s1c2"
    lay = evidence.candidate_layout("s2c3", "choose.candidate")
    assert lay.name == "s2c3"
    with pytest.raises(mstate.Invalid, match=r"^choose\.candidate='s9c9' names no candidate"):
        evidence.candidate_layout("s9c9", "choose.candidate")


@pytest.mark.parametrize(("held", "more"), [(16, False), (17, True)])
def test_a_refused_sweep_id_lists_what_is_held_and_says_when_it_is_more(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, held: int, more: bool,
) -> None:
    from scry_mame import evidence
    _channel(monkeypatch, tmp_path)
    _sweeps([held])
    with pytest.raises(mstate.Invalid) as err:
        evidence.candidate_layout("s1c99", "w")
    assert str(err.value).endswith(" and more") is more, str(err.value)


def test_the_evidence_keeps_which_candidates_searched_their_whole_block() -> None:
    from scry_mame import evidence
    fields = {"frame_screen": 1, "palette": ":palette", "kind": "region", "tag": ":gfx1",
              "offset": 0, "patch": [0, 0, 8, 8], "transparent": None, "flips": ["none"],
              "candidates": [{"layout": {"name": "a"}, "tiles_searched": [0, 256],
                              "tiles_available": 256},
                             {"layout": {"name": "b"}, "tiles_searched": [0, 16],
                              "tiles_available": 256}]}
    n = evidence.record_locate(fields, [])
    assert evidence.locates()[n - 1]["searched_whole"] == [True, False]


def test_the_evidence_keeps_the_pixels_each_match_compared() -> None:
    """A uniqueness proof is only as strong as what its match compared, so the record keeps it."""
    from scry_mame import evidence
    fields = {"frame_screen": 1, "palette": ":palette", "kind": "region", "tag": ":gfx1",
              "offset": 0, "patch": [0, 0, 8, 8], "transparent": 0, "flips": ["none"],
              "candidates": [{"layout": {"name": "a"}, "tiles_searched": [0, 16],
                              "tiles_available": 16}]}
    match = {"layout": "a", "window": [0, 0], "tile": 3, "flip": "none", "base": 0, "byte": 24,
             "compared": 41, "shape": [5, 6, 7], "ambiguous": False, "bit": 192}
    n = evidence.record_locate(fields, [match])
    kept = evidence.locates()[n - 1]["matches"][0]
    assert kept["compared"] == 41 and "ambiguous" not in kept and "bit" not in kept, kept


def test_a_source_names_no_address_and_no_offset_it_was_not_read_at() -> None:
    from scry_mame import evidence
    assert evidence.SourceKey.of({"kind": "space", "tag": "program"}) == ("space", "program", 0,
                                                                          "", "")


# ------------------------------------------------------------------ what a draft reads, in order

def _report(out: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = json.loads(Path(out["report"]["path"]).read_text())
    return report


def test_a_format_proved_under_no_palette_writes_no_asset_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    clown, _, _ = _layouts()
    loc = _one(700, [clown], [(clown["name"], 50, 60)])
    loc["palette"] = "none"
    _evidence(monkeypatch, tmp_path, [loc])
    out = s.gfx_draft()
    assert out["formats"] == {"tiles_16x16x1": "proved"} and out["asset_names"] == []
    assert ":gfx2: no asset for tiles_16x16x1, chosen under no palette" in out["not_proved"]


def test_a_format_drawn_through_two_banks_writes_an_asset_for_each(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    clown, _, _ = _layouts()
    loc = _one(700, [clown], [(clown["name"], 50, 60), (clown["name"], 90, 60)])
    loc["matches"][1]["base"] = 16
    _evidence(monkeypatch, tmp_path, [loc])
    out = s.gfx_draft()
    assert out["asset_names"] == ["gfx2_pen0", "gfx2_pen16"], out
    doc = mame_yaml.loads(Path(out["manifest"]["path"]).read_text())
    assert "pen_base" not in doc["assets"]["gfx2_pen0"]
    assert doc["assets"]["gfx2_pen16"]["pen_base"] == 16


def test_a_block_read_at_an_offset_alone_keeps_the_tags_name(monkeypatch: pytest.MonkeyPatch,
                                                              tmp_path: Path) -> None:
    clown, _, _ = _layouts()
    loc = _one(700, [clown], [(clown["name"], 50, 60)])
    loc["source"] = dict(loc["source"], offset=0x2000)
    _evidence(monkeypatch, tmp_path, [loc])
    doc = mame_yaml.loads(Path(s.gfx_draft()["manifest"]["path"]).read_text())
    assert {n: a["offset"] for n, a in doc["assets"].items()} == {"gfx2": 0x2000}


def _two_captures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _ChannelSession:
    """The clown's capture twice, at 0x1 and at 0x10: the owners sort 1 before 10, their ids
    `10_64_t2000` before `1_64_t2000`. A count watch with no trigger sorts before both."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    mstate.STATE.evidence["locates"][:] = _locates()
    mstate.STATE.tallies[("0", ":count")] = {"tally_id": "0_4", "trigger": None}
    for addr in (0x1, 0x10):
        _captured(ses, _rows_text(), addr=addr)
    return ses


def test_the_captures_are_read_in_the_order_of_their_ids(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    _two_captures(monkeypatch, tmp_path)
    out = s.gfx_draft()
    doc = mame_yaml.loads(Path(out["manifest"]["path"]).read_text())
    assert {n: c["block"]["address"] for n, c in doc["commands"].items()} == {
        "write_2000": 0x10, "write_2000_gfx2": 0x1}, "a tap with no trigger is passed over"


def test_a_capture_whose_header_cannot_be_read_is_read_a_byte_at_a_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _circus(monkeypatch, tmp_path)
    rec = mstate.STATE.tallies[("0", ":maincpu")]
    rec["path"] = ses.scratch / "no-such-header.txt"
    out = s.gfx_draft()
    assert "write_2000" in out["command_fields"], out
    assert _report(out)["correlations"][0]["capture"]["word_bytes"] == 1


def _offsets(locs: list[dict[str, Any]], moves: dict[int, int]) -> list[dict[str, Any]]:
    """Every single-match answer of the clown's run copied to each offset of `moves`, the key
    the number of answers to copy (0: all)."""
    out: list[dict[str, Any]] = []
    for offset, count in moves.items():
        ones = [loc for loc in locs if loc["matches_total"] == 1]
        for loc in ones[:count or None]:
            out.append(dict(loc, n=len(out) + 1, source=dict(loc["source"], offset=offset)))
    return out


def test_the_groups_are_correlated_in_the_order_of_their_sources_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Offsets 0x20 and 0x100: the text of the source 256 sorts before 32, the numbers after."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    mstate.STATE.evidence["locates"][:] = _offsets(_locates(), {0x20: 0, 0x100: 0})
    _captured(ses, _rows_text())
    out = s.gfx_draft()
    names = {e["group"]["source"]["offset"]: e["command"] for e in _report(out)["correlations"]}
    assert names == {0x100: "write_2000", 0x20: "write_2000_gfx2"}, names


def test_a_group_too_small_or_unproved_before_another_leaves_the_other_correlated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The group at 0x100 sorts first: three answers is too few to pair; then, with its windows
    moved off the clown, it proves nothing. The group at 0x20 is correlated either way, and every
    reason not proved is kept."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    few = _offsets(_locates(), {0x100: 3, 0x20: 0})
    mstate.STATE.evidence["locates"][:] = few
    _captured(ses, _rows_text())
    out = s.gfx_draft()
    assert "write_2000" in out["command_fields"], out
    rng = random.Random(7)
    moved = _offsets(_locates(), {0x100: 0, 0x20: 0})
    for loc in moved:
        if loc["source"]["offset"] == 0x100:
            loc["matches"] = [dict(loc["matches"][0], window=[rng.randrange(0, 200),
                                                              rng.randrange(0, 200)])]
    mstate.STATE.evidence["locates"][:] = moved
    out = s.gfx_draft(dest=str(tmp_path / "b.yaml"))
    assert list(out["command_fields"]) == ["write_2000"], out
    assert any(why.startswith("capture 0_64_t2000 against gfx2: ") for why in out["not_proved"])
    assert any("source_tile holds only at lag" in why for why in out["not_proved"])


def test_a_group_of_exactly_the_fewest_paired_events_is_correlated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    mstate.STATE.evidence["locates"][:] = _offsets(_locates(), {0: corr.MIN_PAIRED})
    _captured(ses, _rows_text())
    assert len(_report(s.gfx_draft())["correlations"]) == 1


def test_one_byte_holding_both_coordinates_writes_no_command_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    clown, _, _ = _layouts()
    rng = random.Random(3)
    locs, rows = [], []
    for i in range(8):
        x = rng.randrange(20, 200)
        locs.append(_one(101 + i, [clown], [(clown["name"], x, x + 5)]))
        rows.append(f"r {i + 1} {100 + i} 0 {100 + i}.{i:018d} 12ef 0 ff "
                    f"{bytes([x, 7] + [0] * (WIDTH - 2)).hex()}\n")
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    for n, loc in enumerate(locs, 1):
        loc["n"] = n
    mstate.STATE.evidence["locates"][:] = locs
    _captured(ses, "".join(rows))
    out = s.gfx_draft()
    assert out["command_fields"] == {}, out
    assert any(why.endswith("against gfx2: dest_x and dest_y are not both proved")
               for why in out["not_proved"]), out["not_proved"]


@pytest.mark.parametrize(("addr", "trigger", "word_bytes", "fire"), [
    (0x11, 0x15, 4, {"word": 1, "value": 7}),
    (0x10, 0x10, 2, {"word": 0, "value": 7}),
    (0x10, 0x18, 2, {"address": 0x18, "value": 7}),
    (0x10, 0x15, 2, {"address": 0x15, "value": 7}),
])
def test_a_trigger_inside_its_block_on_a_word_is_fired_by_that_word(
    addr: int, trigger: int, word_bytes: int, fire: dict[str, int],
) -> None:
    """The fire is the block's own word when the trigger is one of them, whole; outside the
    8 bytes, or off a word, it is the address."""
    rows: list[tuple[int, bytes, int | None]] = [(100, b"", 7), (101, b"", 7)]
    rec = {"trigger": trigger, "addr": addr, "width": 8}
    out = mdraft._command(mdraft._Draft("r.json"), "c", rec, ("0", ":maincpu"), word_bytes,
                          rows, {}, (8, 16, 1, (0,), (), (), 128), "")
    got = {k: v for k, v in out["fire"].items() if k not in ("status", "source")}
    assert got == fire and all(type(v) is int for v in got.values()), got
    assert (out["fields"]["width"]["const"], out["fields"]["height"]["const"]) == (8, 16)


@pytest.mark.parametrize(("values", "fire_value"), [([5], None), ([5, 5], 5), ([5, 6], None)])
def test_a_fire_value_is_stated_only_when_several_rows_agree(values: list[int],
                                                              fire_value: int | None) -> None:
    rows: list[tuple[int, bytes, int | None]] = [(100 + i, b"", v) for i, v in enumerate(values)]
    out = mdraft._command(mdraft._Draft("r.json"), "c", {"trigger": 0x2000, "addr": 0,
                                                          "width": 8},
                          ("0", ":maincpu"), 1, rows, {}, (8, 8, 1, (0,), (), (), 64), "")
    assert out["fire"].get("value") == fire_value, out["fire"]


def test_an_answer_cut_at_its_kept_matches_places_no_object(monkeypatch: pytest.MonkeyPatch,
                                                            tmp_path: Path) -> None:
    clown, _, _ = _layouts()
    cut = _one(707, [clown], [(clown["name"], 90, 60)])
    cut["matches_total"] = 5000
    _evidence(monkeypatch, tmp_path, [_one(700, [clown], [(clown["name"], 50, 60)]), cut])
    (events,) = mdraft._events().values()
    assert [e.frame for e in events] == [700]


def test_two_layouts_of_one_size_both_proved_are_named_in_the_order_they_matched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Each told apart where only it matched: the first to match takes the plain name, whatever
    their offsets would sort as."""
    from scry_mame import evidence
    clown, rival, _ = _layouts()
    both = [clown, rival]
    first, second = sorted(both, key=evidence.layout_key, reverse=True)
    _evidence(monkeypatch, tmp_path, [_one(700, both, [(first["name"], 50, 60)]),
                                      _one(707, both, [(second["name"], 90, 60)])])
    out = s.gfx_draft()
    assert out["formats"] == {"tiles_16x16x1": "proved", "tiles_16x16x1_2": "proved"}, out
    assert _report(out)["formats"]["tiles_16x16x1"][0]["layout"]["name"] == first["name"]


@pytest.mark.parametrize("other", [(42, 60), (66, 60), (50, 52), (50, 76)])
def test_a_window_only_touching_another_blocks_is_not_contested(
    other: tuple[int, int], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An 8x8 match of another block flush against the 16x16 at (50, 60), on each side."""
    clown, _, small = _layouts()
    _evidence(monkeypatch, tmp_path, [
        _one(700, [clown], [(clown["name"], 50, 60)]),
        _one(700, [small], [(small["name"], *other)], tag=":gfx1")])
    out = s.gfx_draft()
    assert out["formats"] == {"tiles_8x8x1": "proved", "tiles_16x16x1": "proved"}, out


def test_a_first_that_is_no_utf_8_is_no_draft_marker(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    _circus(monkeypatch, tmp_path)
    dest = tmp_path / "gfx.yaml"
    dest.write_bytes(b"\xff\xfe not a draft\n")
    refused("never overwrites", s.gfx_draft(dest=str(dest)))
    assert dest.read_bytes() == b"\xff\xfe not a draft\n"


def test_a_layout_that_proves_nothing_is_passed_over_for_the_next(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    clown, _, small = _layouts()
    loc = _one(700, [small, clown], [(small["name"], 10, 10), (clown["name"], 100, 60)])
    loc["matches"][0]["shape"] = [1, 16, 16]
    _evidence(monkeypatch, tmp_path, [loc])
    assert s.gfx_draft()["formats"] == {"tiles_16x16x1": "proved"}


def test_a_draft_that_does_not_load_back_is_refused_with_its_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    def broken(*_: Any) -> Any:
        raise mm.ManifestError("a defect")

    _circus(monkeypatch, tmp_path)
    monkeypatch.setattr(mm, "parse", broken)
    out = refused("the draft this derived does not load: a defect", s.gfx_draft())
    assert out["code"] == "unexpected_answer" and out["draft"].startswith(mm.DRAFT_MARKER)


def test_a_second_window_only_one_layout_matched_tells_the_two_apart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """One answer, both tried: the clown at x 50 and x 90 on one row, the rival at x 50 only."""
    clown, rival, _ = _layouts()
    both = [clown, rival]
    _evidence(monkeypatch, tmp_path, [_one(700, both, [(clown["name"], 50, 60),
                                                       (clown["name"], 90, 60),
                                                       (rival["name"], 50, 60)])])
    assert s.gfx_draft()["formats"] == {"tiles_16x16x1": "proved"}


def test_every_flat_and_every_contested_window_is_counted(monkeypatch: pytest.MonkeyPatch,
                                                          tmp_path: Path) -> None:
    clown, _, small = _layouts()
    flat = _one(700, [clown], [(clown["name"], 50, 60), (clown["name"], 90, 60)],
                shape=[1, 16, 16])
    _evidence(monkeypatch, tmp_path, [
        flat,
        _one(800, [small], [(small["name"], 50, 60)], tag=":gfx1"),
        _one(801, [small], [(small["name"], 50, 60)], tag=":gfx1"),
        _one(800, [clown], [(clown["name"], 50, 60)], tag=":gfx3"),
        _one(801, [clown], [(clown["name"], 50, 60)], tag=":gfx3")])
    out = s.gfx_draft()
    unproving = {(u["source"]["tag"], u["layout"]): (u["flat"], u["causes"], u["contested"])
                 for u in _report(out)["unproving"]}
    assert unproving[(":gfx2", clown["name"])] == (2, {"rows": 2}, 0), unproving
    assert unproving[(":gfx1", "small")] == (0, {}, 2), unproving
    assert (":gfx1: small matched only windows that prove no layout (matched from another block "
            "too)") in out["not_proved"], out


def test_the_draft_and_its_report_are_written_as_utf_8_whatever_the_locale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A person's name in a choice may be any printable text: the files are UTF-8 because the
    writer says so, never because the locale happens to be."""
    _circus(monkeypatch, tmp_path)
    written: list[tuple[str, Any]] = []
    real = Path.write_text

    def spy(self: Path, data: str, *args: Any, **kwargs: Any) -> int:
        if self.name.endswith(".tmp"):
            written.append((self.name, kwargs.get("encoding")))
        return real(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy)
    assert s.gfx_draft()["status"] == "ok"
    assert [enc for _, enc in written] == ["utf-8", "utf-8"], written


def test_a_capture_whose_install_is_pending_reads_nothing_another_tap_left(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Its files are the range's, so until its install answered they may be a removed tap's:
    the draft proves nothing from them, as a survey reads nothing from them."""
    ses = _channel(monkeypatch, tmp_path)
    monkeypatch.setattr(mstate.STATE, "system", "circus")
    mstate.STATE.evidence["locates"][:] = _locates()
    rec = _captured(ses, _rows_text())
    rec.update(installed=None, mark=0, line="never echoed", seq=99, script="")
    out = s.gfx_draft()
    assert not out.get("commands"), out


@pytest.mark.parametrize(("width", "height", "rarest", "failed"), [
    (8, 16, 8, set()), (8, 16, 7, {"rarest"}), (16, 8, 7, {"rarest"}), (15, 15, 8, set()),
    (15, 15, 7, {"rarest"})])
def test_the_rarest_floor_is_half_the_longer_side_of_any_tile(
        width: int, height: int, rarest: int, failed: set[str]) -> None:
    """The longer side, whichever it is, and an odd side rounded up: half of 15 is not met by 7."""
    cand = {"name": "c0", "width": width, "height": height, "planes": 8}
    loc = {"candidates": [cand], "matches_total": 1, "matches": [{"layout": "c0"}],
           "searched_whole": [True]}
    assert mdraft._failed({"shape": [2, 2, rarest], "layout": "c0"}, loc) == failed
