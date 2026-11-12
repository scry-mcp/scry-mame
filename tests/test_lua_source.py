"""The loader of the scripts under `src/scry_mame/lua/`: a slot is a Lua identifier, filled by
type."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from scry_mame import lua_source
from scry_mame import state as st


@pytest.fixture
def scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(lua_source, "HERE", tmp_path)
    lua_source.load.cache_clear()
    yield tmp_path
    lua_source.load.cache_clear()


def test_each_slot_takes_a_lua_literal_of_its_values_type(scripts: Path) -> None:
    (scripts / "t.lua").write_text(
        "local a, b, c, d, e = __SCRY_a__, __SCRY_b__, __SCRY_c__, __SCRY_d__, __SCRY_e__\n"
        "local f = __SCRY_f__\n", encoding="utf-8")
    got = lua_source.render("t", a='x "y"\n', b=7, c=True, d=None, e=0.5,
                            f=lua_source.Code("emu.time()"))
    assert got == ('local a, b, c, d, e = "x \\"y\\"\\n", 7, true, nil, 0.5\n'
                   "local f = emu.time()\n")


def test_a_statement_slot_is_a_comment_until_code_fills_it(scripts: Path) -> None:
    (scripts / "t.lua").write_text("local a = 1\nif a then\n  --- __SCRY_body__\nend\n",
                                   encoding="utf-8")
    got = lua_source.render("t", body=lua_source.Code("  a = a + 1\n"))
    assert got == "local a = 1\nif a then\n  a = a + 1\nend\n"
    with pytest.raises(st.Invalid, match="statement slot takes Code: body"):
        lua_source.render("t", body="a = 2")


def test_a_comment_line_is_not_sent_and_a_comment_after_code_is(scripts: Path) -> None:
    (scripts / "t.lua").write_text("-- why\n  -- more\nlocal a = 1 -- kept\n--- __SCRY_b__\n",
                                   encoding="utf-8")
    assert lua_source.render("t", b=lua_source.Code("-- from code\n")) == (
        "local a = 1 -- kept\n-- from code\n")


def test_a_slot_left_unfilled_or_a_value_for_none_is_refused(scripts: Path) -> None:
    (scripts / "t.lua").write_text("print(__SCRY_a__, __SCRY_a__)\n", encoding="utf-8")
    assert lua_source.render("t", a=1) == "print(1, 1)\n"
    with pytest.raises(st.Invalid, match="__SCRY_a__"):
        lua_source.render("t")
    with pytest.raises(st.Invalid, match="b"):
        lua_source.render("t", a=1, b=2)
    with pytest.raises(st.Invalid, match="list"):
        lua_source.render("t", a=[1])  # type: ignore[arg-type]
