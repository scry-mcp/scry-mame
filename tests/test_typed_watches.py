"""Watches read as the SHAPE the value has: arrays, strings, structs, and a symbol's own type.

`width` bytes as N scalars render a sprite record as a row of numbers and a name as a row of
bytes, leaving a caller who knows the shape to decode it by hand. The format grammar
(`value_format`) names the shape, a sized format implies its
width, and a symbol the table types (`type:` beside it in the YAML, or a `types` file given
to `start`) reads as that type with no format named at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import add_symbol, refused, use_table  # noqa: E402
from test_server import _boot_args, _stub_boot  # noqa: E402
from test_watches import _watching  # noqa: E402

import gdb_session as g  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_symbols as syms  # noqa: E402
import server as s  # noqa: E402


def test_a_sized_format_needs_no_width_and_decodes_to_its_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("0001000200030004")
    out = s.watch_add(ref="0x2031fc", mode="show", fmt="u16[4]")
    assert out["status"] == "ok" and out["length"] == 8 and out["fmt"] == "u16[4]"
    assert out["reading"]["value"] == [1, 2, 3, 4]
    ses.memory[0x00203200] = b"RE\x00\x00\xff\xfe\x00\x10\x81"
    out = s.watch_add(ref="0x203200", mode="show", fmt="{name:char[4],x:i16,y:i16,flags:u8}")
    assert out["length"] == 9
    assert out["reading"]["value"] == {"name": "RE", "x": -2, "y": 16, "flags": 0x81}
    listed = {w["ref"]: w for w in s.watch_list()["watches"]}
    assert listed["0x203200"]["fmt"].startswith("{name:char[4]")
    assert listed["0x203200"]["length"] == 9
    refused("does not agree", s.watch_add(ref="0x2031f0", mode="show", fmt="u16[4]", length=6))
    refused("not a format", s.watch_add(ref="0x2031f0", mode="show", fmt="u64", length=8))
    refused("needs a length", s.watch_add(ref="0x2031f0", mode="show"))


def test_a_stop_renders_every_shape_and_a_change_watch_takes_the_sized_width(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _watching(monkeypatch, tmp_path)
    ses.memory[0x2031FC] = bytes.fromhex("0001000200030004")
    s.watch_add(ref="0x2031fc", mode="change", fmt="u16[4]")
    assert ses.watchpoints[-1][:2] == (0x2031FC, 8), "the watchpoint spans the array"
    out = s.step()
    (w,) = out["watches"]
    assert w["reading"]["value"] == [1, 2, 3, 4] and w["length"] == 8


def test_a_symbol_typed_in_the_yaml_reads_as_its_type_with_no_format_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    sym = tmp_path / "s.yaml"
    sym.write_text("images:\n  common:\n  - addr: 0x002031fc\n    name: frame_lo\n"
                   "    type: u16[2]\n    description: two words\n"
                   "  - addr: 0x00203200\n    name: pos\n    type: {x:i16,y:i16}\n"
                   "  - addr: 0x400\n    name: irq_vblank\n")
    table = g.symbols(str(sym))
    assert table.types == {"FRAME_LO": "u16[2]", "POS": "{x:i16,y:i16}"}
    assert table.table["IRQ_VBLANK"] == 0x400 and "IRQ_VBLANK" not in table.types
    bad = tmp_path / "bad.yaml"
    bad.write_text("- addr: 0x400\n  name: a\n  type: u64\n")
    with pytest.raises(ValueError, match="bad.yaml:3"):
        g.symbols(str(bad))
    ses = _watching(monkeypatch, tmp_path)
    use_table(monkeypatch, types={"FRAME_LO": "u16[2]",
                                  "POS": "{x:i16,y:i16}"})
    ses.memory[0x2031FC] = bytes.fromhex("00010002")
    out = s.watch_add(ref="frame_lo", mode="show")
    assert out["fmt"] == "u16[2]" and out["length"] == 4 and out["reading"]["value"] == [1, 2]
    add_symbol(monkeypatch, "POS", 0x203200)
    ses.memory[0x00203200] = bytes.fromhex("fffe0010")
    out = s.watch_add(ref="pos", mode="show")
    assert out["reading"]["value"] == {"x": -2, "y": 16}
    # A symbol typed as a BARE SCALAR needs no width either: one value of it.
    use_table(monkeypatch, types={**mstate.STATE.table().types, "SCORE": "u32"})
    add_symbol(monkeypatch, "SCORE", 0x203204)
    ses.memory[0x00203204] = bytes.fromhex("00000100")
    out = s.watch_add(ref="score", mode="show")
    assert out["fmt"] == "u32" and out["length"] == 4 and out["reading"]["value"] == 0x100, out
    out = s.watch_add(ref="0x203208", mode="show", fmt="i16")
    assert out["length"] == 2, "a named scalar with no length: one value"
    # A width given with a typed symbol and no fmt is the scalar default, as before.
    out = s.watch_add(ref="copy_in_rom", mode="show", length=2)
    assert out["fmt"] == "u16"


def test_a_types_file_types_symbols_at_start_and_is_refused_when_it_lies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    image = bytes(range(256))
    _stub_boot(monkeypatch, tmp_path, image, 0)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    sym = tmp_path / "s.yaml"
    sym.write_text("- addr: 0x10\n  name: hero\n- addr: 0x20\n  name: score\n  type: u32\n")
    types = tmp_path / "types.txt"
    types.write_text("# the shapes\nhero: {x:i16,y:i16,hp:u8}\n\nscore: u16\n")
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym), types=str(types))
    try:
        assert out["symbols_typed"] == 2
        assert mstate.STATE.table().types == {"HERO": "{x:i16,y:i16,hp:u8}", "SCORE": "u16"}, \
            "the types file wins over the YAML's own type"
    finally:
        s.close()
    types.write_text("villain: u8\n")
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym), types=str(types))
    assert out["status"] == "INVALID" and "lacks" in out["message"] and "VILLAIN" in out["message"]
    types.write_text("hero: u64\n")
    out = s.start(**_boot_args(tmp_path, image), symbols=str(sym), types=str(types))
    assert out["status"] == "INVALID" and "types.txt:1" in out["message"]
    out = s.start(**_boot_args(tmp_path, image), types=str(types))
    assert out["status"] == "INVALID" and "no `symbols`" in out["message"]
    types.write_text("# nothing\n")
    with pytest.raises(mstate.Invalid, match="names no type"):
        syms.read_types(str(types))


def test_a_watch_with_no_format_at_all_is_refused_by_the_model() -> None:
    import mame_declarations as dec
    with pytest.raises(dec.DeclarationError, match="needs a format"):
        dec.Declaration("watch", "symbol", "x", width=2, watch_mode="show")
