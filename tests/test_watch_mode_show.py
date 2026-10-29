"""The watch mode that reads at every stop and arms nothing is `show`; `read` names an access."""

import asyncio
import json
from pathlib import Path

import pytest
import test_envelope_seam  # noqa: E402

from scry_mame import declarations as dec  # noqa: E402
from scry_mame import (
    read,  # noqa: E402
    watches,  # noqa: E402
)
from scry_mame import server as s  # noqa: E402
from scry_mame import state as st  # noqa: E402

KEY = "x /nowhere/x.map"
# Modes the rename leaves alone sit beside the renamed ones, so a migration rewriting all shows.
LEGACY_ROWS: list[dict[str, object]] = [
    {"kind": "watch", "by": "address", "ref": "0x203200", "width": 8, "fmt": "f64",
     "watch_mode": "read", "cpu": ":maincpu", "created_at": "t", "origin": "s0",
     "fingerprint": "fp"},
    {"kind": "watch", "by": "address", "ref": "0x203208", "width": 2, "fmt": "u16",
     "watch_mode": "read", "cpu": ":maincpu", "created_at": "t", "origin": "s0",
     "fingerprint": "fp"},
    {"kind": "watch", "by": "pointer", "ref": "[base]+0x28", "width": 10,
     "fmt": "{seg:u16,off:u16,vidpos:u16,width:u16,height:u16}", "watch_mode": "read",
     "cpu": ":maincpu", "created_at": "t", "origin": "s0", "fingerprint": "fp"},
    {"kind": "watch", "by": "pointer", "ref": "[base2]+0x4", "width": 2, "fmt": "u16",
     "watch_mode": "read", "created_at": "t", "origin": "s0", "fingerprint": "fp"},
    {"kind": "watch", "by": "symbol", "ref": "frame", "width": 1, "fmt": "u8",
     "watch_mode": "read", "cpu": ":maincpu", "created_at": "t", "origin": "s0",
     "fingerprint": "fp"},
    {"kind": "watch", "by": "symbol", "ref": "lives", "width": 1, "fmt": "u8",
     "watch_mode": "change", "cpu": ":maincpu", "created_at": "t", "origin": "s0",
     "fingerprint": "fp"},
    {"kind": "watch", "by": "expr", "ref": "beamy", "width": None, "watch_mode": "expr",
     "created_at": "t", "origin": "s0", "fingerprint": "fp"},
]


def _schema_modes() -> list[str]:
    tools = {t.name: t for t in asyncio.run(s.mcp.list_tools())}
    return list(tools["watch_add"].input_schema["properties"]["mode"]["enum"])


def test_the_published_mode_enum_says_show_and_not_read() -> None:
    modes = _schema_modes()
    assert "show" in modes and "read" not in modes, modes


def test_mode_read_is_refused_in_the_servers_sentence_naming_show() -> None:
    reply = test_envelope_seam._call("watch_add", {"ref": "0x400", "mode": "read"})[1]
    assert reply["code"] == "bad_argument", reply
    assert reply["message"] == f"mode is one of {dec.WATCH_MODES}; got 'read'", reply
    assert "'show'" in reply["message"], reply


def test_a_store_written_with_read_rows_loads_them_as_show_and_persists_show(
        tmp_path: Path) -> None:
    path = tmp_path / "declarations.json"
    path.write_text(json.dumps({KEY: LEGACY_ROWS}))
    store = dec.DeclarationStore(KEY, path)
    modes = [d.watch_mode for d in store.declarations()]
    assert modes == ["show"] * 5 + ["change", "expr"], modes
    # Loading writes nothing: the file keeps the old word until the next write.
    assert json.loads(path.read_text())[KEY] == LEGACY_ROWS
    store.add(dec.Declaration("breakpoint", "address", "0x400", created_at="t", origin="s1",
                              cpu=":maincpu"))
    stored = [r.get("watch_mode") for r in json.loads(path.read_text())[KEY]]
    assert stored == ["show"] * 5 + ["change", "expr", None], stored


def test_a_show_watch_is_bounded_as_the_read_watch_was_and_a_change_watch_is_not() -> None:
    wide = watches.SHOW_WATCH_MAX + 1
    assert wide <= read.READ_MAX, "the case needs a width only the show ceiling refuses"
    with pytest.raises(st.Invalid, match=f"length={wide} is above"):
        watches.check_watch_width(wide, "show")
    watches.check_watch_width(wide, "change")


def test_a_resolved_show_watch_is_evaluated_and_a_resolved_change_watch_has_no_word() -> None:
    show = dec.Declaration("watch", "address", "0x400", width=2, fmt="u16", watch_mode="show",
                           cpu=":maincpu")
    change = dec.Declaration("watch", "address", "0x400", width=2, fmt="u16",
                             watch_mode="change", cpu=":maincpu")
    res = dec.Resolved(show, "address", 0x400)
    assert watches.resolved_state(show, res) == "evaluated"
    assert watches.resolved_state(change, dec.Resolved(change, "address", 0x400)) is None
