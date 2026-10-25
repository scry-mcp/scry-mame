"""The palette write log (`mame_ramdac`, `palette_log`) and the pixel query it answers.

The m68k-dual fixtures are captured: the board's BT478 declared as `palette_ports.ramdac` (index
`0x720001`, data `0x720003`, r g b, 8 bits), armed inside the palette upload (frame 898) and read
away from it (frame 901). The `-after` files add a debugger write, a Lua write and a state load,
so the rows begin with the upload the arming cut into, before any index write: that is `unsynced`.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lua_support import _channel, _ChannelSession  # noqa: E402
from session_doubles import documented, published, refused, use_table  # noqa: E402
from test_callbacks import assert_every_callback_guarded  # noqa: E402
from test_gfx import _serve  # noqa: E402

import mame_callbacks as mcallbacks
import mame_manifest as mm  # noqa: E402
import mame_ramdac as mr  # noqa: E402
import mame_ramdac_lua as rlua  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_transport as transport  # noqa: E402
import server as s  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "gfx"
MANIFEST = FIX / "manifest-blitter.yaml"
LOG_ID = "ramdac_720001_1_720003"
PEN = 0x49
LIVE = "#9c734a"


def _text(name: str) -> str:
    path = FIX / name
    return (gzip.decompress(path.read_bytes()).decode() if path.suffix == ".gz"
            else path.read_text())


def _edited(name: str, old: str, new: str) -> str:
    """A captured fixture with `old` replaced by `new` exactly once."""
    text = _text(name)
    assert text.count(old) == 1, f"the edit {old!r} does not match {name} exactly once"
    return text.replace(old, new)


def _pen(pen: int) -> tuple[int, ...]:
    """A pen's components as the captured dump holds them, in r, g, b order."""
    dump = mr.parse_dump(_text("ramdac-m68k-dual.txt"))
    assert dump is not None
    return tuple(c for c in dump["pens"][pen].components if c is not None)


def _every_setter(reply: dict[str, Any]) -> list[dict[str, Any]]:
    """The whole setters list a read names, past the reply's cut."""
    listed: list[dict[str, Any]] = json.loads(Path(reply["setters_path"]).read_text())
    return listed


def _ramdac() -> mm.PalettePort:
    return mm.read(str(MANIFEST)).palette_ports["ramdac"]


def _loaded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
            manifest: Path = MANIFEST) -> _ChannelSession:
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(manifest))["status"] == "ok"
    return ses


def _armed(ses: _ChannelSession, name: str = "ramdac-m68k-dual") -> dict[str, Any]:
    """The log armed through the tool, its install answered, and the dump and rows its dumper
    wrote where the record says, as `name`'s capture has them."""
    out = s.palette_log(palette_port="ramdac", arm=True)
    assert out["armed_now"] is True, out
    # the console answers the install the way it did live, so the pipe drains behind it
    ses.answers[mstate.STATE.lua_seq] = (
        f"MCP_TALLY installed tally_id={LOG_ID} index=720001 data=720003 data_width=16 "
        "endianness=big cpu=:maincpu\n").encode() + ses.sentinel(mstate.STATE.lua_seq)
    rec = mstate.STATE.tallies[mr.owner_of(_ramdac())]
    rec.update(installed=True, cpu=":maincpu")
    rec["path"].write_text(_text(f"{name}.txt"))
    rec["rows_path"].write_text(_text(f"{name}.rows.gz"))
    return rec



def test_the_install_runs_the_devices_state_machine_on_both_ports() -> None:
    """Each port's tap sits on its bus word and keeps the writes whose lane covers the port's
    byte; the data tap composes on `order`, returns the slot to 0 at three and moves the index on
    only when the device auto-increments; a reset and a state load unsync it; a write at `stop`
    is decided against the parked time; past the cap a row is only counted."""
    r = _ramdac()
    script = rlua.install_script(LOG_ID, r, Path("/s/h.txt"), Path("/s/r.rows"), ":maincpu")
    assert f'local id = "{LOG_ID}"\nlocal ip, dp, base = 0x720001, 0x720003, 0\n' in script
    assert "local comp = {1, 2, 3}" in script and "local auto, pmask = true, 0xff" in script
    assert 'install_write_tap(ilo, ilo + nb - 1, "mcp_ramdac_i_"' in script
    assert 'install_write_tap(dlo, dlo + nb - 1, "mcp_ramdac_d_"' in script
    assert "if ((mask >> dshift) & 0xff) == 0 then return end" in script
    assert "if slot == 3 then" in script
    assert "if auto then t.idx = (t.idx + 1) & pmask end" in script
    assert "t.idx, t.slot, t.sync, t.dirty = v & pmask, 0, true, true" in script, (
        "an index write resets the component counter, as `index_w` does")
    assert 'add_machine_reset_notifier(guarded(t, function() desync("reset") end))' in script
    assert 'add_machine_post_load_notifier(guarded(t, function() desync("load") end))' in script
    assert "T.ps, T.pa = now.seconds, now.attoseconds" in script, "the park is stamped"
    assert f"if t.rows >= {mr.ROWS_MAX} then t.overflow_rows" in script
    assert 'devices[":maincpu"]' in script, "the cpu is bound when the chunk is composed"
    assert script.index("old.tap:remove()") < script.index("install_write_tap")
    assert "MCP_TALLY installed tally_id=%s" in script, "the count watch's reader answers it"
    assert len(script) < transport.SCRIPT_MAX
    bgr = mm.PalettePort("x", "palette", "", 1, 3, ("b", "g", "r"), 6, False, 256, "declared", "s")
    other = rlua.install_script(LOG_ID, bgr, Path("/s/h.txt"), Path("/s/r.rows"), None)
    assert "local comp = {3, 2, 1}" in other and "local auto, pmask = false, 0xff" in other
    assert ", 256\n" in other and 'cpu.spaces["program"]' in other
    assert "dbg.visible_cpu" in other


def test_a_captured_dump_parses_whole_and_a_cut_or_undecided_one_reads_as_none() -> None:
    text = _text("ramdac-m68k-dual.txt")
    dump = mr.parse_dump(text)
    assert dump is not None
    assert (dump["id"], dump["frame"], dump["total"], dump["index_writes"], dump["unsynced"],
            dump["desyncs"], dump["rows"], dump["overflow_rows"], dump["notifiers"]) == (
        LOG_ID, 901, 1330, 1, 562, 0, 1331, 0, 2)
    assert (dump["data_width"], dump["endianness"], dump["cpu"]) == (16, "big", ":maincpu")
    assert sorted(dump["pens"]) == list(range(256))
    pen = dump["pens"][PEN]
    assert (pen.writes, pen.n, pen.frame, pen.pc, pen.by, pen.components) == (
        3, 785, 900, 0xBF6, "guest", (0x9C, 0x73, 0x4A))
    assert mr.parse_dump(text.replace("end\n", "")) is None, "a dump with no end is not whole"
    assert mr.parse_dump(text.replace(" bf6 g ", " bf6 ? ", 1)) is None, (
        "a write not yet decided is never written as either")
    assert mr.parse_dump("MCP_RAMDAC x seq=1\nend\n") is None


def test_rows_parse_every_kind_and_a_cut_row_ends_the_read(tmp_path: Path) -> None:
    rows = list(mr.rows_of(_text("ramdac-m68k-dual-after.rows.gz").splitlines()))
    kinds = [r.kind for r in rows]
    assert (kinds.count("i"), kinds.count("d"), kinds.count("x")) == (3, 1336, 1)
    assert rows[0] == mr.Row("d", 1, 899, 0xBB0, "guest", value=0xC5), "unsynced: no pen"
    load = rows[-1]
    assert (load.kind, load.n, load.frame, load.reason) == ("x", 1340, 901, "load")
    debugger = [r for r in rows if r.by == "debugger"]
    assert [(r.kind, r.pen, r.slot, r.value) for r in debugger] == [
        ("i", None, None, PEN), ("d", PEN, 0, 0x12), ("d", PEN, 1, 0x34), ("d", PEN, 2, 0x56),
        ("i", None, None, PEN), ("d", PEN, 0, 0x21), ("d", PEN, 1, 0x43), ("d", PEN, 2, 0x65)]
    cut = tmp_path / "cut.rows"
    cut.write_text("i 1 5 400 g 10\nd 2 5 402 g 10\nd 3 5 404 g 10 1 20\n")
    assert [r.n for r in mr.rows(cut)] == [1], (
        "a line of another shape ends the read: what follows it is not known to be rows")
    for bad in ("i 1 5 400 g zz", "d 1 5 400 g 10 x 20", "r 1 5", "x 1 5 load extra"):
        cut.write_text(f"i 1 5 400 g 10\n{bad}\ni 3 5 400 g 10\n")
        assert [r.n for r in mr.rows(cut)] == [1], bad
    assert list(mr.rows(tmp_path / "none.rows")) == []


def _device(rows: list[mr.Row], auto: bool) -> list[tuple[int, int | None, int | None]]:
    """`ramdac_device` written again; the index is unknown until an index write."""
    out: list[tuple[int, int | None, int | None]] = []
    idx: int | None = None
    slot = 0
    for r in rows:
        if r.kind == "x":
            idx = None
        elif r.kind == "i":
            idx, slot = r.value, 0
        elif idx is None:
            out.append((r.n, None, None))
        else:
            out.append((r.n, idx, slot))
            slot += 1
            if slot == 3:
                slot = 0
                idx = (idx + 1) & 0xFF if auto else idx
    return out


def test_known_answer_the_taps_pens_are_the_devices_own() -> None:
    """Every data write the tap placed is on the pen and component the device would put it on;
    the same law without auto-increment disagrees, the control that this can fail."""
    rows = list(mr.rows_of(_text("ramdac-m68k-dual-after.rows.gz").splitlines()))
    tap = [(r.n, r.pen, r.slot) for r in rows if r.kind == "d"]
    assert len(tap) > 1000 and sum(1 for _n, p, _s in tap if p is None) == 562
    assert _device(rows, auto=True) == tap
    assert _device(rows, auto=False) != tap


@pytest.mark.parametrize("name", ["ramdac-m68k-dual", "ramdac-m68k-dual-after"])
def test_known_answer_the_replay_composes_what_the_dump_holds(name: str, tmp_path: Path) -> None:
    """Two paths to one colour: the dump's components, composed by the tap in MAME, and the rows
    replayed in order in Python. They agree on every pen, and on the newest write of each."""
    dump = mr.parse_dump(_text(f"{name}.txt"))
    assert dump is not None
    path = tmp_path / "log.rows"
    path.write_text(_text(f"{name}.rows.gz"))
    r = _ramdac()
    last: dict[int, tuple[int, str | None]] = {}
    for row, col in mr.replay(path, r):
        if row.pen is not None:
            last[row.pen] = (row.n, col)
    assert sorted(last) == sorted(dump["pens"])
    for pen, p in dump["pens"].items():
        assert last[pen] == (p.n, mr.colour(p.components, 8)), pen


def test_the_replay_places_each_slot_on_the_component_the_order_names(tmp_path: Path) -> None:
    """With `order` b, g, r the first write of a pen is its blue: the slot is where the write
    came in, the component is what the order says that slot carries."""
    bgr = mm.PalettePort("x", "palette", "", 1, 3, ("b", "g", "r"), 8, True, 0, "declared", "s")
    path = tmp_path / "bgr.rows"
    path.write_text("i 1 5 400 g 7\nd 2 5 402 g 7 0 11\nd 3 5 404 g 7 1 22\nd 4 5 406 g 7 2 33\n")
    got = [(r.kind, col) for r, col in mr.replay(path, bgr)]
    assert got == [("i", None), ("d", None), ("d", None), ("d", "#332211")]
    rgb = _ramdac()
    assert [col for _r, col in mr.replay(path, rgb)][-1] == "#112233"


def test_a_component_is_widened_the_way_mames_palnbit_does() -> None:
    assert [mr.widen(v, 6) for v in range(64)] == [(v << 2) | (v >> 4) for v in range(64)]
    assert [mr.widen(v, 5) for v in range(32)] == [(v << 3) | (v >> 2) for v in range(32)]
    assert [mr.widen(v, 4) for v in range(16)] == [v * 0x11 for v in range(16)]
    assert [mr.widen(v, 3) for v in range(8)] == [(v << 5) | (v << 2) | (v >> 1)
                                                   for v in range(8)]
    assert [mr.widen(v, 1) for v in range(2)] == [0, 0xFF]
    assert [mr.widen(v, 8) for v in (0, 0x7F, 0xFF)] == [0, 0x7F, 0xFF]
    assert mr.widen(0xFF, 6) == 0xFF and mr.widen(0x40, 6) == 0, "bits past the width are masked"
    assert mr.colour((0x3F, 0, 0x20), 6) == "#ff0082"
    assert mr.colour((1, None, 2), 8) is None, "a component not seen yet gives no colour"




def test_palette_logs_description_says_the_install_waits_for_the_consoles_read() -> None:
    """The description names the console's read of the install, never an execution."""
    text = published("palette_log")
    assert "installed when the console next reads a line" in documented("palette_log")
    assert "execut" not in text, text


def test_a_read_never_arms_an_arm_call_does_and_a_later_one_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _loaded(monkeypatch, tmp_path)
    unarmed = refused(re.escape('`palette_log(palette_port="ramdac", arm=True)` arms it'),
                      s.palette_log(palette_port="ramdac"))
    assert unarmed["code"] == "needs_call" and not mstate.STATE.tallies, unarmed
    rec = _armed(ses)
    sent = ses.stdin.getvalue().decode()
    assert "mcp_ramdac_d_" in sent and LOG_ID in sent, "the install went down the pipe"
    out = s.palette_log(palette_port="ramdac")
    assert out["status"] == "ok" and out["armed_now"] is False, out
    assert (out["writes_total"], out["index_writes"], out.get("unsynced_writes", 0), out["desyncs"],
            out["rows_kept"], out["overflow_rows"], out["rows_cut"]) == (
        1330, 1, 562, 0, 1331, 0, False)
    assert out["pens_written"] == ["0x0-0xff"] and out["sees_reset_and_load"] is True
    assert out["rows_path"] == str(rec["rows_path"])
    assert out["not_proved"] == ["palette_ports.ramdac"]
    every = _every_setter(out)
    assert sum(x["pens_set"] for x in every) == 256
    assert all(x["written_by"] == "guest" for x in every)
    assert "pen" not in out, "the whole table is asked for by pen"
    assert [r["n"] for r in out["rows"]] == list(range(1316, 1332)), "the newest 16 kept rows"
    last = out["rows"][-1]
    assert (last["n"], last["frame"], last["written_by"], last["pen"], last["component"]) == (
        1331, 900, "guest", 255, "b")
    assert last["color"] == f"#{''.join(f'{c:02x}' for c in _pen(255))}"
    assert out["summary"] == ("palette_log ramdac as of frame 901: 1330 data writes, pens "
                              "0x0-0xff written, 1331 rows kept, 0 past the cap")
    assert out["note"] == mr.UNSYNCED_NOTE
    assert "notes" not in out, "one `note`, as every tool's"
    assert (out["frame_as_of"], out["superseded"], out["installed"]) == (901, False, True)


def test_the_setters_listed_are_cut_and_the_whole_list_is_in_the_file_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """KNOWN ANSWER: the captured board uploads its palette through an unrolled loop, one writer
    pc per pen, so its 256 pens have 256 setters. The reply lists the first 32, ranked most pens
    first and then by pc, says how many there are, and names a file holding them all, whatever
    `limit` asks of the rows. The next read rewrites the file (an append would not parse), and a
    read by `pen` lists no setters."""
    assert mr.SETTERS_LISTED_MAX == 32, "the cut the decision names"
    ses = _loaded(monkeypatch, tmp_path)
    _armed(ses)
    out = s.palette_log(palette_port="ramdac", limit=0)
    every = _every_setter(out)
    assert len(every) == out["setters_total"] == 256, (len(every), out.get("setters_total"))
    assert len(out["setters"]) == 32 and out["setters"] == every[:32] and out["rows"] == []
    pcs = [int(x["pc"], 16) for x in every]
    assert len(set(pcs)) == 256 and pcs == sorted(pcs), "one writer per pen, ranked by pc"
    again = s.palette_log(palette_port="ramdac", limit=1)
    assert _every_setter(again) == every
    assert "setters" not in s.palette_log(palette_port="ramdac", pen=PEN), "a pen's read lists none"


def test_a_setters_file_the_scratch_refuses_costs_the_file_and_never_the_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The dump has been read by the time the file is written: a scratch that refuses it is said
    where `setters_path` would be, and the listing, the total and the rest of the reply still come
    back."""
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses)
    rec["setters_path"] = tmp_path / "gone" / "setters.json"
    out = s.palette_log(palette_port="ramdac", limit=0)
    assert out["status"] == "ok" and out["setters_path"]["available"] is False, out
    assert out["setters_path"]["why"], out
    assert len(out["setters"]) == mr.SETTERS_LISTED_MAX and out["setters_total"] == 256


def test_a_log_armed_and_not_yet_dumped_says_so_and_the_pixel_names_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Armed, and the machine has not executed since: nothing is on disk, which is a state the
    reply names, never an empty table."""
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses)
    rec["path"].unlink()
    out = s.palette_log(palette_port="ramdac")
    assert out["status"] == "ok" and out["state"] == "no_dump_yet" and "writes_total" not in out
    assert "no dump of this tap is on disk" in out["why"]
    px = _pixel(ses)
    assert px["set_by"]["available"] is False
    assert "no dump of this tap is on disk" in px["set_by"]["why"]


def test_writers_are_placed_in_the_symbol_table_and_a_clean_log_carries_no_notes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The game's writers get the symbol they sit in; a dump with no unsynced write and no
    debugger's write has nothing to warn about, so it carries no `notes`."""
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses)
    use_table(monkeypatch, table={"PAL_UPLOAD": 0xBE0})
    rec["path"].write_text(_edited("ramdac-m68k-dual.txt", "unsynced=562", "unsynced=0"))
    out = s.palette_log(palette_port="ramdac", pen=PEN, limit=1)
    assert out["pen_state"]["last"]["symbol"] == "PAL_UPLOAD+0x16" and "note" not in out
    whole = s.palette_log(palette_port="ramdac", limit=0)
    assert any(x.get("symbol") == "PAL_UPLOAD+0x16" for x in _every_setter(whole))


def test_a_debuggers_write_only_a_shown_row_holds_is_still_said(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A debugger's write a later guest write overwrote is no pen's newest, so only the rows shown
    carry it, and those rows alone have to bring the note. The clean log is the control."""
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses)
    rec["path"].write_text(_edited("ramdac-m68k-dual.txt", "unsynced=562", "unsynced=0"))
    assert "note" not in s.palette_log(palette_port="ramdac", limit=2), "the control"
    rows = _text("ramdac-m68k-dual.rows.gz").splitlines()
    n = int(rows[-1].split()[1])
    rows += [f"d {n + 1} 999 e2f2c d 10 0 21", f"d {n + 2} 999 bb0 g 10 0 c5"]
    rec["rows_path"].write_text("\n".join(rows) + "\n")
    out = s.palette_log(palette_port="ramdac", limit=2)
    assert [r.get("written_by") for r in out["rows"]] == ["debugger", "guest"], out["rows"]
    assert mr.DEBUGGER_NOTE in out["note"], out


def test_a_log_that_cannot_see_a_reset_or_whose_rows_were_cut_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A MAME binding one of the two notifiers, and a log past its rows cap: the reply says
    what it could not see, the edits being to the captured dump's header alone."""
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses)
    rec["path"].write_text(_edited("ramdac-m68k-dual.txt", "overflow_rows=0 notifiers=2",
                                   "overflow_rows=5 notifiers=1"))
    out = s.palette_log(palette_port="ramdac")
    assert out["sees_reset_and_load"] is False and out["rows_cut"] is True
    assert any("binds 1 of the 2 notifiers" in n for n in out["note"].split("; ")), out["note"]


def test_a_pen_is_read_whole_with_its_own_rows(monkeypatch: pytest.MonkeyPatch,
                                               tmp_path: Path) -> None:
    ses = _loaded(monkeypatch, tmp_path)
    _armed(ses)
    out = s.palette_log(palette_port="ramdac", pen=PEN, limit=2)
    assert "pen" not in out, "the pen's state is `pen_state`; `pen` is a number in every reply"
    assert out["pen_state"] == {"pen": PEN, "color": LIVE, "complete": True,
                          "components": {"r": 0x9C, "g": 0x73, "b": 0x4A}, "writes_total": 3,
                          "last": {"n": 785, "frame": 900, "pc": "0x00000bf6",
                                   "written_by": "guest"}}
    assert [(r["component"], r["color"]) for r in out["rows"]] == [
        ("g", {"available": False, "why": mr.INCOMPLETE_WHY}), ("b", LIVE)], (
        "the colour a row left needs all three components seen")
    assert "setters" not in out
    assert s.palette_log(palette_port="ramdac", pen=PEN, limit=0)["rows"] == []


def test_the_debuggers_writes_and_a_load_are_said(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    ses = _loaded(monkeypatch, tmp_path)
    _armed(ses, "ramdac-m68k-dual-after")
    out = s.palette_log(palette_port="ramdac", pen=PEN, limit=3)
    assert out["pen_state"]["last"] == {"n": 1339, "frame": 901, "pc": "0x000e2f2c",
                                        "written_by": "debugger"}
    assert out["pen_state"]["color"] == "#214365" and out["pen_state"]["writes_total"] == 9
    assert mr.DEBUGGER_NOTE in out["note"]
    whole = s.palette_log(palette_port="ramdac", limit=1)
    unstamped = {"available": False, "why": mr.UNSTAMPED_WHY}
    assert whole["rows"] == [{"n": 1340, "frame": 901, "line": unstamped, "time_s": unstamped,
                              "desync": True, "why": mr.DESYNC_WHY["load"]}]
    assert whole["desyncs"] == 1
    assert {"pc": "0x000e2f2c", "written_by": "debugger", "pens_set": 1, "which": ["0x49"]} in (
        _every_setter(whole))


def test_a_debuggers_write_is_never_placed_in_the_guests_symbol_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The debugger's pc is where the machine stood when it wrote, not code that wrote: a symbol
    beside it would name a routine of the game as the writer. The guest's rows are the control."""
    ses = _loaded(monkeypatch, tmp_path)
    _armed(ses, "ramdac-m68k-dual-after")
    use_table(monkeypatch, table={"PAL_UPLOAD": 0xBE0, "BELOW_THE_DEBUGGER": 0xE2F00})
    out = s.palette_log(palette_port="ramdac", pen=PEN, limit=3)
    last = out["pen_state"]["last"]
    assert last["written_by"] == "debugger" and "symbol" not in last, out
    whole = s.palette_log(palette_port="ramdac", limit=0)
    debugger = [x for x in _every_setter(whole) if x["written_by"] == "debugger"]
    placed = [x for x in _every_setter(whole)
              if x["written_by"] == "guest" and int(x["pc"], 16) >= 0xBE0]
    assert debugger and all("symbol" not in x for x in debugger), debugger
    assert placed and all(list(x)[-1] == "symbol" for x in placed), (
        "the control: a guest writer at or past the table's first symbol is placed, last")


def test_clear_removes_the_log_and_the_next_arm_arms_again(monkeypatch: pytest.MonkeyPatch,
                                                            tmp_path: Path) -> None:
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses)
    setters_file = Path(s.palette_log(palette_port="ramdac", limit=0)["setters_path"])
    out = s.palette_log(palette_port="ramdac", clear=True)
    assert out["cleared"] is True and out["removal"] == "pending", out
    assert 'T.items[id] = nil' in ses.stdin.getvalue().decode()
    assert not rec["path"].exists() and not rec["rows_path"].exists()
    assert not setters_file.exists(), "the setters file goes with the log"
    assert mr.owner_of(_ramdac()) not in mstate.STATE.tallies
    again = s.palette_log(palette_port="ramdac", clear=True)
    assert again["cleared"] is False and again["summary"] == "palette_log ramdac: no log was armed"
    assert s.palette_log(palette_port="ramdac")["code"] == "needs_call", "a read never arms"
    assert s.palette_log(palette_port="ramdac", arm=True)["armed_now"] is True


@pytest.mark.parametrize("kw, said", [
    ({"palette_port": ""}, r"palette_port='': the name of an entry"),
    ({"palette_port": "a b"}, r"palette_port='a b'"),
    ({"palette_port": "ramdac", "pen": -1}, r"pen=-1 is not a pen number"),
    ({"palette_port": "ramdac", "pen": True}, r"pen=True is not a pen number"),
    ({"palette_port": "ramdac", "limit": -1}, r"limit=-1 is outside 0\.\.256 rows"),
    ({"palette_port": "ramdac", "limit": 257}, r"limit=257 is outside 0\.\.256 rows"),
    ({"palette_port": "ramdac", "clear": True, "pen": 3}, r"`clear` removes the log"),
    ({"palette_port": "ramdac", "clear": True, "limit": 3}, r"`clear` removes the log"),
    ({"palette_port": "ramdac", "clear": 1}, r"clear is true or false; got 1"),
    ({"palette_port": "ramdac", "limit": True}, r"limit is a count; got True"),
])
def test_arguments_are_judged_before_the_machine(kw: dict[str, Any], said: str) -> None:
    with pytest.raises(mstate.Invalid, match=said):
        mr.check_palette_log(**kw)
    mr.check_palette_log(palette_port="ramdac", limit=256)
    mr.check_palette_log(palette_port="ramdac", limit=0, pen=0)


def test_a_log_needs_a_manifest_that_names_the_ramdac_and_the_pen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _channel(monkeypatch, tmp_path)
    refused("no manifest is loaded", s.palette_log(palette_port="ramdac"))
    assert s.gfx_load(path=str(MANIFEST))["status"] == "ok"
    out = s.palette_log(palette_port="dac")
    refused("palette_port='dac' is not in", out)
    assert out["palette_ports"] == ["ramdac"]
    refused(r"pen 256 is not one palette port 'ramdac' sets: it sets 0\.\.255",
            s.palette_log(palette_port="ramdac", pen=256))
    assert mstate.STATE.tallies == {}, "nothing was armed by a refused call"


def test_a_log_armed_from_another_entry_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    """The rows are read under the entry's law: a reloaded manifest that states the RAMDAC
    another way would read them wrongly, so it is refused, naming `clear`."""
    ses = _loaded(monkeypatch, tmp_path)
    _armed(ses)
    text, n = re.subn(r"order: \[r, g, b\]", "order: [b, g, r]", MANIFEST.read_text(), count=1)
    assert n == 1
    other = tmp_path / "bgr.yaml"
    other.write_text(text)
    assert s.gfx_load(path=str(other))["status"] == "ok"
    refused(re.escape('palette_log(palette_port="ramdac", clear=True)'),
            s.palette_log(palette_port="ramdac"))
    assert s.palette_log(palette_port="ramdac", clear=True)["cleared"] is True



def _pixel(ses: _ChannelSession) -> dict[str, Any]:
    _serve(ses, "screen-m68k-dual-pixel", screen="m68k-dual-pixel-screen")
    out: dict[str, Any] = s.screen_view(mode="pixel", point=[100, 100])
    return out


def test_the_pixel_names_the_write_that_set_its_pen(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    ses = _loaded(monkeypatch, tmp_path)
    _armed(ses)
    out = _pixel(ses)
    assert (out["pen"], out["color"]) == (PEN, LIVE), out
    assert out["set_by"] == {"palette_port": "ramdac", "pen": PEN, "color": LIVE, "complete": True,
                             "components": {"r": 0x9C, "g": 0x73, "b": 0x4A}, "writes_total": 3,
                             "last": {"n": 785, "frame": 900, "pc": "0x00000bf6",
                                      "written_by": "guest"},
                             "agrees": True}
    assert "note" not in out and out["set_by"].get("available") is not False
    assert out["summary"] == ("screen_view pixel :screen frame 901: (100, 100) is pen 0x49 "
                              "#9c734a; last set by a guest write at pc 0x00000bf6, frame 900; "
                              "388x388 PNG x8, inline")
    chunk = ses.stdin.getvalue().decode().splitlines()[-1]
    assert chunk.index("mcp_capture(") < chunk.index("R.dump_all()"), (
        "the log is dumped by the chunk that reads the screen, after it: one instant")


def test_a_pen_its_last_write_does_not_explain_is_said_with_the_write_that_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The after-case log against the before-case screen: the pen's newest write (the Lua
    chunk's) left another colour, so the reply says they disagree and finds the kept row that
    left the colour the pen has."""
    ses = _loaded(monkeypatch, tmp_path)
    _armed(ses, "ramdac-m68k-dual-after")
    out = _pixel(ses)
    assert out["set_by"]["agrees"] is False and out["set_by"]["color"] == "#214365"
    assert "something other than a write to the entry's ports" in out["note"]
    assert out["set_by"]["last"]["written_by"] == "debugger" and mr.DEBUGGER_NOTE in out["note"], (
        "the newest write was the debugger's, and saying the colour moved since does not unsay "
        "who wrote")
    unstamped = {"available": False, "why": mr.UNSTAMPED_WHY}
    assert out["same_color_write"] == {"n": 785, "frame": 900, "pc": "0x00000bf6",
                                       "written_by": "guest", "line": unstamped,
                                       "time_s": unstamped,
                                       "pen": PEN, "component": "b", "value": "0x4a",
                                       "color": LIVE}
    assert out["rows_cut"] is False
    assert out["summary"].endswith("frame 901, NOT the colour it has now; 388x388 PNG x8, inline")


def test_a_colour_no_kept_row_left_is_said_as_none(monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    """The pen's colour came from somewhere the kept rows never show (here, rows cut before
    it): `same_color_write` is null rather than the nearest row."""
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses, "ramdac-m68k-dual-after")
    rows = _text("ramdac-m68k-dual-after.rows.gz")
    kept = [ln for ln in rows.splitlines() if not re.match(r"^d \d+ \d+ \w+ \w 49 ", ln)]
    rec["rows_path"].write_text("\n".join(kept[:1300]) + "\n")
    out = _pixel(ses)
    assert out["set_by"]["agrees"] is False
    assert out["same_color_write"]["available"] is False, out


def test_a_log_armed_under_another_law_leaves_the_pixel_its_pen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A reloaded manifest that moved the RAMDAC to another cpu: the pixel still answers its pen
    and colour, `set_by`'s why names the clear, and the clear reaches the tap armed on the old
    cpu."""
    ses = _loaded(monkeypatch, tmp_path)
    _armed(ses)
    other = tmp_path / "moved.yaml"
    other.write_text(MANIFEST.read_text().replace("    index_port: 0x720001",
                                                  "    cpu: subcpu\n    index_port: 0x720001"))
    assert s.gfx_load(path=str(other))["status"] == "ok"
    out = _pixel(ses)
    assert (out["status"], out["pen"], out["set_by"]["available"]) == ("ok", PEN, False), out
    assert 'palette_log(palette_port="ramdac", clear=True)' in out["set_by"]["why"]
    # READ ALONE, the log asks for the clear first: another call, not another value.
    stale = refused("no longer states the same way", s.palette_log(palette_port="ramdac"))
    assert stale["code"] == "needs_call", stale
    cleared = s.palette_log(palette_port="ramdac", clear=True)
    assert cleared["cleared"] is True and cleared["tally_id"] == LOG_ID
    assert mstate.STATE.tallies == {}


def test_only_the_pixel_dumps_the_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ses = _loaded(monkeypatch, tmp_path)
    _serve(ses, "screen-m68k-dual-pixel", screen="m68k-dual-pixel-screen")
    assert s.screen_view(mode="histogram")["status"] == "ok"
    assert "dump_all" not in ses.stdin.getvalue().decode().splitlines()[-1]


def test_a_debugger_write_is_marked_at_the_pixel(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses, "ramdac-m68k-dual-after")
    rec["path"].write_text(_edited("ramdac-m68k-dual-after.txt", "p 49 9 1339 901 e2f2c d 21 43 65",
                                   "p 49 9 1339 901 e2f2c d 9c 73 4a"))
    out = _pixel(ses)
    assert out["set_by"]["agrees"] is True and out["set_by"]["last"]["written_by"] == "debugger"
    assert out["note"] == mr.DEBUGGER_NOTE


@pytest.mark.parametrize("case, said", [
    ("no_manifest", "no manifest is loaded"),
    ("no_ramdac", "names no `palette_ports` entry that sets pen 73 of palette :palette"),
    ("past_its_pens", "names no `palette_ports` entry that sets pen 73 of palette :palette"),
    ("not_armed", "no palette write log is armed on palette port 'ramdac': "
                  '`palette_log(palette_port="ramdac", arm=True)` arms it, and it records from '
                  "when the console next reads a line"),
    ("pen_unwritten", "no write to pen 73 since the log of palette port 'ramdac' was armed"),
    ("incomplete", None),
])
def test_what_the_pixel_cannot_say_it_names(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                            case: str, said: str | None) -> None:
    if case == "no_manifest":
        ses = _channel(monkeypatch, tmp_path)
    elif case in ("no_ramdac", "past_its_pens"):
        # another palette, or this one from pen 256 on: pen 73 is not one it sets
        other = tmp_path / "pal2.yaml"
        edit = ("    palette: pal2\n    index_port" if case == "no_ramdac" else
                "    palette: palette\n    pen_base: 256\n    index_port")
        other.write_text(MANIFEST.read_text().replace("    palette: palette\n    index_port", edit))
        ses = _loaded(monkeypatch, tmp_path, other)
    else:
        ses = _loaded(monkeypatch, tmp_path)
    if case in ("pen_unwritten", "incomplete"):
        rec = _armed(ses)
        dump = _text("ramdac-m68k-dual.txt")
        line = "p 49 3 785 900 bf6 g 9c 73 4a\n"
        assert line in dump
        rec["path"].write_text(dump.replace(line, "" if case == "pen_unwritten" else
                                            "p 49 1 785 900 bf6 g - - 4a\n"))
    out = _pixel(ses)
    assert out["status"] == "ok" and out["pen"] == PEN
    if said is None:
        assert out["set_by"]["complete"] is False
        assert out["set_by"]["agrees"]["available"] is False
        assert out["summary"].endswith(", incomplete; 388x388 PNG x8, inline")
        return
    assert out["set_by"]["available"] is False and said in out["set_by"]["why"], out.get("set_by")
    assert out["summary"].endswith(f"; no logged write to it: {out['set_by']['why']}; 388x388 PNG "
                                   "x8, inline"), out["summary"]


def test_only_the_rows_a_reply_shows_are_labelled(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    """Placing a writer in the symbol table costs a pass over the table, so it is spent on the
    rows the reply keeps, never on every row of the log only to drop them."""
    ses = _loaded(monkeypatch, tmp_path)
    _armed(ses, "ramdac-m68k-dual-after")
    labelled: list[int] = []
    real = mr.row_fields
    def counted(*a: Any) -> dict[str, Any]:
        labelled.append(1)
        return real(*a)

    monkeypatch.setattr(mr, "row_fields", counted)
    out = s.palette_log(palette_port="ramdac", limit=2)
    assert len(out["rows"]) == 2 and len(labelled) == 2
    labelled.clear()
    assert _pixel(ses)["same_color_write"] is not None
    assert len(labelled) == 1, "the pixel labels the one write it names"


def test_the_rows_shown_are_each_rendered_as_what_they_were(monkeypatch: pytest.MonkeyPatch,
                                                            tmp_path: Path) -> None:
    """The capture's own start, cut after its first data write that lands on a pen: the last
    data write the log could not place, the index write, and the first placed one, each in
    its own shape."""
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses)
    rows = _text("ramdac-m68k-dual.rows.gz").splitlines()
    first_index = next(i for i, ln in enumerate(rows) if ln.startswith("i "))
    rec["rows_path"].write_text("\n".join(rows[:first_index + 2]) + "\n")
    out = s.palette_log(palette_port="ramdac", limit=3)
    unplaced, index, placed = out["rows"]
    assert unplaced["unsynced"] is True and "pen" not in unplaced, unplaced
    assert index["index"] == "0x00" and "pen" not in index, index
    assert (placed["pen"], placed["value"]) == (0, "0x23") and "unsynced" not in placed, placed



PACKED_FIX = Path(__file__).parent / "fixtures" / "ramdac"


def _packed(board: str) -> mm.PalettePort:
    return mm.read(str(PACKED_FIX / f"{board}-palette.yaml")).palette_ports["pal"]


def _packed_dump(board: str) -> dict[str, Any]:
    text = gzip.decompress((PACKED_FIX / f"{board}-dump.txt.gz").read_bytes()).decode()
    dump = mr.parse_dump(text)
    assert dump is not None
    return dump


def _held(board: str) -> list[str]:
    """The colours MAME's palette device held for every pen at the dump's stop: `palette`'s
    reply, the ground truth the decoding is judged by."""
    colors: list[str] = json.loads((PACKED_FIX / f"{board}-palette.json").read_text())["colors"]
    return colors


def _composed(board: str, r: mm.PalettePort) -> dict[int, str | None]:
    return {pen: mr.colour(mr.components_of(p, r), r.component_bits)
            for pen, p in _packed_dump(board)["pens"].items()}


# the pens each capture's run wrote: v30-alt's game never set its last pen
@pytest.mark.parametrize("board, pens", [("v30-alt", 1023), ("v30", 256)])
def test_known_answer_a_packed_dump_decodes_to_the_colours_mame_held(board: str,
                                                                    pens: int) -> None:
    """CAPTURED: v30-alt's latch and v30's sequence (PROVENANCE.txt), every pen the log
    composed against what `palette` read at the same stop."""
    held = _held(board)
    composed = _composed(board, _packed(board))
    assert len(composed) == pens and None not in composed.values()
    assert {pen: col for pen, col in composed.items() if held[pen] != col} == {}


def test_the_controls_of_the_packed_known_answers_can_fail() -> None:
    """The same dumps read under a law each driver does not have disagree with the palette:
    v30 without the bit reversal of `twins_pal_w`, v30-alt with red and blue swapped."""
    for board, wrong in (("v30", {"components_bit_reversed": False}),
                         ("v30-alt", {"order": ("b", "g", "r")})):
        held, right = _held(board), _composed(board, _packed(board))
        misread = _composed(board, dataclasses.replace(_packed(board), **wrong))
        # the pens the wrong law reads otherwise (a grey reads the same either way)
        telling = [pen for pen, col in misread.items() if col != right[pen]]
        assert telling and all(held[pen] != misread[pen] for pen in telling), board


def test_a_packed_word_is_decoded_by_the_entrys_law() -> None:
    """`order`'s components from bit 0 up, `component_bits` each, bit-reversed when the entry
    says so, and nothing until every colour bit has been seen."""
    seq, latch = _packed("v30"), _packed("v30-alt")
    word = 0b10000_00011_00001                      # r 1, g 3, b 16 from bit 0 up
    assert mr.decode(latch, word, 0x7FFF) == (1, 3, 16)
    assert mr.decode(seq, word, 0xFFFF) == (16, 24, 1), "each 5-bit component bit-reversed"
    assert mr.decode(seq, word, 0x00FF) == (None, None, None), "bits 8-14 never seen written"
    assert mr.colour(mr.decode(latch, 0x7FFF, 0x7FFF), 5) == "#ffffff"


def test_a_packed_dump_parses_its_word_lines_and_an_older_header_reads_no_partial() -> None:
    dump = _packed_dump("v30-alt")
    assert (dump["id"], dump["partial_writes"], dump["unsynced"]) == ("ramdac_a_1@io_8", 0, 0)
    p = next(iter(dump["pens"].values()))
    assert p.word is not None and p.known == 0xFFFF and p.components == (None, None, None)
    m68k_dual = mr.parse_dump(_text("ramdac-m68k-dual.txt"))
    assert m68k_dual is not None and m68k_dual["partial_writes"] == 0, (
        "a byte RAMDAC's captured dump carries no field and reads as none")
    text = gzip.decompress((PACKED_FIX / "v30-alt-dump.txt.gz").read_bytes()).decode()
    bad = re.sub(r"(?m)^(w [0-9a-f]+ .*) ([0-9a-f]+)$", r"\1 zz", text, count=1)
    assert bad != text and mr.parse_dump(bad) is None, "a word line of another shape"


def test_the_packed_rows_are_replayed_merging_each_write_under_its_mask(tmp_path: Path) -> None:
    """A sequence pen written a byte at a time has no colour after the first half and the
    colour of the merged word after the second; a latch word is whole; an unsynced write lands
    on no pen."""
    path = tmp_path / "packed.rows"
    path.write_text("w 1 5 400 g - 7fff ffff\n"
                    "i 2 5 402 g 0\n"
                    "w 3 5 404 g 0 1 ff\n"
                    "w 4 5 404 g 0 7c00 ff00\n")
    got = [(r.kind, r.pen, col) for r, col in mr.replay(path, _packed("v30"))]
    assert got == [("w", None, None), ("i", None, None), ("w", 0, None),
                   ("w", 0, mr.colour(mr.decode(_packed("v30"), 0x7C01, 0x7FFF), 5))]
    rows = list(mr.rows(path))
    assert (rows[2].value, rows[2].mask) == (0x1, 0xFF)
    shown = mr.row_fields(rows[3], "#ffffff", _packed("v30"), None)
    assert (shown["pen"], shown["word"], shown["mask"], shown["color"]) == (
        0, "0x7c00", "0xff00", "#ffffff")
    lost = mr.row_fields(rows[0], None, _packed("v30"), None)
    assert (lost["unsynced"], lost["word"], lost["mask"]) == (True, "0x7fff", "0xffff"), (
        "an unsynced packed row shows what it carried, as a placed one does")
    over = tmp_path / "over.rows"
    over.write_text("w 1 5 404 g 0 7fff ffff\nw 2 5 404 g 0 0 ff\n")
    last = [col for _r, col in mr.replay(over, _packed("v30-alt"))][-1]
    assert last == mr.colour(mr.decode(_packed("v30-alt"), 0x7F00, 0x7FFF), 5), (
        "a write clears the bits of its mask it carries as 0")


def test_the_latch_and_sequence_taps_run_their_drivers_state_machines() -> None:
    latch = rlua.install_script("id", _packed("v30-alt"), Path("/s/h"), Path("/s/r"), ":maincpu")
    assert 'cpu.spaces["io"]' in latch and "local flag = 0x8000" in latch
    assert "local auto, pmask = true, 0x3ff" in latch and "local cmask = 0x7fff" in latch
    assert "if (v & flag) ~= 0 then" in latch, "a flagged word is an index"
    assert "store(base + t.idx, v, dword, fr, pc, w)" in latch, "a colour is written whole"
    assert "t.idx = ((t.idx & ~m) | (v & m)) & pmask" in latch, "the index port merges"
    assert 'error("a packed palette port is read little-endian' in latch
    assert latch.index("share a bus word") < latch.index("old.tap:remove()"), (
        "a refused install leaves the log it would replace in place")
    assert 'desync("index_partial")' in latch, "an index write that leaves it unknown desyncs"
    assert "sync = false" in latch
    alone = rlua.install_script("id", dataclasses.replace(_packed("v30-alt"), index_port=None),
                                Path("/s/h"), Path("/s/r"), None)
    assert "mcp_ramdac_i_" not in alone and "local ip, dp, base = nil, 0x8, 0" in alone
    seq = rlua.install_script("id", _packed("v30"), Path("/s/h"), Path("/s/r"), None, True)
    assert "t.idx, t.sync = 0, true" in seq and "sync = true" in seq
    assert "store(base + t.idx, v, m, fr, pc, w)" in seq, "a write merges under its mask"
    byte = rlua.install_script("id", _ramdac(), Path("/s/h"), Path("/s/r"), None, True)
    assert "share a bus word" not in byte and "sync = true" in byte
    for script in (latch, alone, seq):
        assert len(script) < transport.SCRIPT_MAX
        assert script.index("local cmask") < script.index("local function store"), (
            "the colour mask is a local the store reads, so it is declared first")


def test_every_callback_a_palette_log_installs_runs_under_the_guard() -> None:
    """Each protocol's taps, the reset and state-load notifiers, and the dumper; and the dump the
    pixel's chunk asks for, which runs every log's dumper outside the periodic."""
    for r, taps in ((_ramdac(), 2), (_packed("v30-alt"), 2),
                    (dataclasses.replace(_packed("v30-alt"), index_port=None), 1),
                    (_packed("v30"), 2)):
        script = rlua.install_script(LOG_ID, r, Path("/s/h.txt"), Path("/s/r.rows"), ":maincpu")
        assert_every_callback_guarded(script, taps, 2)
        assert "for _, it in pairs(T.items) do dump_guarded(it, T.dump, fr) end" in script


def test_a_logged_row_is_counted_only_once_it_is_kept() -> None:
    """As a capture's: a format that raises must not leave a counted row that was never stored,
    or every later dump trips over the hole."""
    script = rlua.install_script(LOG_ID, _ramdac(), Path("/s/h.txt"), Path("/s/r.rows"), None)
    log = script.split("local function log(fmt, ...)")[1].split("\nend\n")[0]
    assert log.index("t.pending[n] = string.format(fmt, ...)") < log.index(
        "t.npending, t.rows = n, t.rows + 1"), log
    assert "t.rows = t.rows + 1" not in log and "t.npending = t.npending + 1" not in log


# A log whose data tap raised at every synced write since a planted fault (`fixtures/callbacks`):
# no pen written, the errors beside the counts.
RAISED = (FIX.parent / "callbacks" / "ramdac-raised.txt").read_text()
RAISED_FIRST = "mcp:3: planted fault"


def _raised() -> str:
    """The captured dump that has pens, given the raised capture's count and first message: a log
    whose tap raised after it set its pens, the one shape a capture with no pen cannot show."""
    text = _edited("ramdac-m68k-dual.txt", "cpu=:maincpu\n", "cpu=:maincpu errors=3072\n")
    assert text.endswith("\nend\n")
    return text[:-len("end\n")] + f"e {RAISED_FIRST}\nend\n"


def test_a_log_whose_taps_raised_says_so_and_is_never_an_empty_census(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A log whose data tap raised at every write set no pen, and read as a palette nobody
    wrote: the errors ride on the log's reply, its summary counts them, and the pixel's
    `set_by` carries them beside the write it names."""
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses)
    rec["path"].write_text(RAISED)
    out = s.palette_log(palette_port="ramdac")
    assert out["callback_errors"] == {"count": 3072, "first": RAISED_FIRST}, out
    assert out["pens_written"] == [] and out["writes_total"] == 4608
    assert out["summary"].endswith(
        f"; its callbacks raised 3072 times (the first: {RAISED_FIRST})")
    rec["path"].write_text(_raised())
    pixel = _pixel(ses)
    assert pixel["set_by"]["callback_errors"] == {"count": 3072, "first": RAISED_FIRST}, pixel
    dump = mr.parse_dump(_text("ramdac-m68k-dual.txt"))
    assert dump is not None and dump["errors"] is None, "a dump from before the guard"


def test_a_pen_no_write_reached_because_the_tap_raised_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses)
    rec["path"].write_text(RAISED)
    pixel = _pixel(ses)
    assert pixel["set_by"]["available"] is False, pixel
    assert "raised 3072 times" in pixel["set_by"]["why"], pixel
    assert RAISED_FIRST in pixel["set_by"]["why"]


def test_a_healthy_log_says_none_raised_and_its_prose_says_nothing_of_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The count every dump of the guarded log carries is zero in the normal case: the reply says
    so, and no summary, `why` or `set_by` speaks of errors."""
    ses = _loaded(monkeypatch, tmp_path)
    rec = _armed(ses)
    rec["path"].write_text(_edited("ramdac-m68k-dual.txt", "cpu=:maincpu\n",
                                   "cpu=:maincpu errors=0\n"))
    out = s.palette_log(palette_port="ramdac")
    assert out["callback_errors"] == {"count": 0, "first": {"available": False,
                                                            "why": mcallbacks.NONE_RAISED_WHY}}, out
    assert "callbacks" not in out["summary"]
    pixel = _pixel(ses)
    none_raised = {"available": False, "why": mcallbacks.NONE_RAISED_WHY}
    assert pixel["set_by"]["callback_errors"] == {"count": 0, "first": none_raised}, pixel
    rec["path"].write_text(RAISED.replace("errors=3072", "errors=0").replace(
        f"e {RAISED_FIRST}\n", ""))
    pixel = _pixel(ses)
    assert pixel["set_by"]["available"] is False and "raised" not in pixel["set_by"]["why"], pixel


def test_every_protocol_the_manifest_takes_has_a_tap() -> None:
    assert set(rlua._TAPS) == set(mm.PROTOCOLS)


def _packed_manifest(tmp_path: Path, board: str) -> Path:
    """The fixture manifest with its RAMDAC replaced by `board`'s packed entry, so it loads on
    the double's system."""
    # v30's fixture keeps the section's old name, `ramdacs`, which the loader reads as an alias
    entry = re.split(r"^(?:palette_ports|ramdacs):\n",
                     (PACKED_FIX / f"{board}-palette.yaml").read_text(), maxsplit=1, flags=re.M)[1]
    head = MANIFEST.read_text().split("palette_ports:\n", 1)[0]
    path = tmp_path / f"{board}.yaml"
    path.write_text(head + "palette_ports:\n" + entry)
    return path


def test_a_sequence_log_armed_where_start_parked_knows_its_offset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The driver's `machine_start` zeroes the offset, so a log armed before the machine ever
    executed starts synced at 0; one stop later nothing says where the offset is."""
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(_packed_manifest(tmp_path, "v30")))["status"] == "ok"
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "last_stop", {"cause": "start", "stop_count": ses.stop_count})
    assert mr.fresh() is True
    out = s.palette_log(palette_port="pal", arm=True)
    assert out["armed_now"] is True and out["synced_at_start"] is True, out
    assert (out["protocol"], out["space"], out["index_port"], out["pen_range"]) == (
        "sequence", "io", "0x0000000e", [0, 255])
    assert out["data_port"].startswith("0x") and len(out["data_port"]) == 10, out
    assert "sync = true" in ses.stdin.getvalue().decode()
    assert s.palette_log(palette_port="pal", clear=True)["cleared"] is True
    ses.running = True
    assert mr.fresh() is False, "a machine released since the park"
    ses.running = False
    ses.stop_count += 1
    assert mr.fresh() is False
    again = s.palette_log(palette_port="pal")
    assert "synced_at_start" not in again
    monkeypatch.setattr(mstate.STATE, "last_stop",
                        {"cause": "run_for", "stop_count": ses.stop_count})
    assert mr.fresh() is False, "a stop the park is not"


def test_only_a_sequence_log_starts_synced_where_start_parked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A latch learns its index from a flagged word, which it cannot know before one: armed at
    the park it still starts unsynced."""
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(_packed_manifest(tmp_path, "v30-alt")))["status"] == "ok"
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "last_stop", {"cause": "start", "stop_count": ses.stop_count})
    out = s.palette_log(palette_port="pal", arm=True)
    assert mr.fresh() is True and out["armed_now"] is True and "synced_at_start" not in out
    assert "sync = false" in ses.stdin.getvalue().decode()


def test_a_log_in_the_io_space_needs_a_cpu_with_one(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(_packed_manifest(tmp_path, "v30-alt")))["status"] == "ok"
    monkeypatch.setattr(mstate.STATE, "machine_map",
                        {"cpus": [{"tag": ":maincpu", "spaces": ["program"]}]})
    refused(r":maincpu has no io space", s.palette_log(palette_port="pal", arm=True))
    assert mstate.STATE.tallies == {}


def test_a_packed_log_is_read_by_pen_with_its_word(monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    """v30-alt's captured dump through the tool: a pen's colour is the palette's, its word is
    shown, the reply counts `partial_writes`, and a dump that counted some says what they
    are."""
    ses = _channel(monkeypatch, tmp_path)
    assert s.gfx_load(path=str(_packed_manifest(tmp_path, "v30-alt")))["status"] == "ok"
    out = s.palette_log(palette_port="pal", arm=True)
    assert out["armed_now"] is True and out["tally_id"] == "ramdac_a_1@io_8", out
    ses.answers[mstate.STATE.lua_seq] = (
        b"MCP_TALLY installed tally_id=ramdac_a_1@io_8 index=a data=8 data_width=16 "
        b"endianness=little cpu=:maincpu\n") + ses.sentinel(mstate.STATE.lua_seq)
    rec = mstate.STATE.tallies[mr.owner_of(_packed("v30-alt"))]
    rec.update(installed=True, cpu=":maincpu")
    text = gzip.decompress((PACKED_FIX / "v30-alt-dump.txt.gz").read_bytes()).decode()
    rec["path"].write_text(text)
    rec["rows_path"].write_text("")
    held = _held("v30-alt")
    read = s.palette_log(palette_port="pal", pen=0x100, limit=0)
    assert read["partial_writes"] == 0 and read["pen_state"]["color"] == held[0x100], read
    assert read["pen_state"]["word"].startswith("0x") and read["pen_state"]["complete"] is True
    rec["path"].write_text(text.replace(" partial_writes=0\n", " partial_writes=3\n", 1))
    assert mr.PARTIAL_NOTE in s.palette_log(palette_port="pal", limit=0)["note"]
    refused(r"pen 1024 is not one palette port 'pal' sets: it sets 0\.\.1023",
            s.palette_log(palette_port="pal", pen=1024))


def test_a_log_armed_under_another_protocol_law_is_refused(monkeypatch: pytest.MonkeyPatch,
                                                            tmp_path: Path) -> None:
    """The law carries the protocol's keys: the same ports re-declared without the bit reversal
    would read the words wrongly."""
    _channel(monkeypatch, tmp_path)
    path = _packed_manifest(tmp_path, "v30")
    assert s.gfx_load(path=str(path))["status"] == "ok"
    assert s.palette_log(palette_port="pal", arm=True)["armed_now"] is True
    path.write_text(path.read_text().replace("components_bit_reversed: true",
                                             "components_bit_reversed: false"))
    assert s.gfx_load(path=str(path))["status"] == "ok"
    refused(re.escape('palette_log(palette_port="pal", clear=True)'),
            s.palette_log(palette_port="pal"))
