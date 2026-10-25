"""Input spellings and their refusals, judged with no emulator running."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import test_envelope_seam  # noqa: E402

import server as s  # noqa: E402

KINDS = ("breakpoint", "regpoint", "watch")


def _schema(tool: str) -> dict[str, Any]:
    tools = {t.name: t for t in asyncio.run(s.mcp.list_tools())}
    return dict(tools[tool].input_schema)


def _call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return test_envelope_seam._call(tool, args)[1]


def _clear(kind: str, **args: Any) -> dict[str, Any]:
    return _call("declaration_clear", {"kind": kind, **args})


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("ref", ["", "   "])
def test_an_empty_ref_is_refused_naming_all(kind: str, ref: str) -> None:
    reply = _clear(kind, ref=ref)
    assert reply["code"] == "bad_argument", reply
    assert "all=True" in reply["message"], reply


@pytest.mark.parametrize("kind", KINDS)
def test_no_ref_at_all_is_refused_naming_all(kind: str) -> None:
    reply = _clear(kind)
    assert reply["code"] == "bad_argument" and "all=True" in reply["message"], reply


@pytest.mark.parametrize("kind", KINDS)
def test_all_beside_a_ref_is_refused(kind: str) -> None:
    ref = "d0==1" if kind == "regpoint" else "0x4a0"
    reply = _clear(kind, ref=ref, all=True)
    assert reply["code"] == "bad_argument", reply
    assert "`all`" in reply["message"] and "`ref`" in reply["message"], reply


@pytest.mark.parametrize("kind", KINDS)
def test_all_alone_passes_the_judge_and_reaches_the_session_gate(kind: str) -> None:
    assert _clear(kind, all=True)["code"] == "no_session"


def test_the_clear_tool_publishes_all_as_a_boolean() -> None:
    props = _schema("declaration_clear")["properties"]
    assert props["all"]["type"] == "boolean" and props["all"].get("default") is False, props


@pytest.mark.parametrize("kind", ["breakpoint", "watch"])
@pytest.mark.parametrize("ref", ["1000:0010", "0xZZ", "0x"])
def test_a_clears_ref_meets_the_judge_every_other_ref_meets(kind: str, ref: str) -> None:
    reply = _clear(kind, ref=ref)
    assert reply["code"] == "bad_argument", reply


def test_watch_clear_publishes_space() -> None:
    props = _schema("declaration_clear")["properties"]
    assert props["space"]["enum"] == ["program", "io"], props


def test_a_suffixed_port_is_refused_naming_space() -> None:
    reply = _call("declaration_clear", {"kind": "watch", "ref": "0x6@io"})
    assert reply["code"] == "bad_argument" and 'space="io"' in reply["message"], reply


def test_space_beside_all_is_refused() -> None:
    reply = _call("declaration_clear", {"kind": "watch", "all": True, "space": "io"})
    assert reply["code"] == "bad_argument" and "`space`" in reply["message"], reply


def test_scan_start_takes_cell_bytes_and_not_width() -> None:
    props = _schema("scan")["properties"]
    cell = next(a for a in props["cell_bytes"]["anyOf"] if "enum" in a)
    assert "width" not in props and cell["enum"] == [1, 2, 4], props
    assert _call("scan", {"method": "start", "ref": "0x400", "length": 16,
                          "cell_bytes": 3})["code"] == (
        "bad_argument")
    assert _call("scan", {"method": "start", "ref": "0x400", "length": 16,
                          "cell_bytes": 2})["code"] == (
        "no_session")


def test_gfx_locate_transparent_takes_a_0x_value() -> None:
    args = {"layouts": ["8x8"], "patch": [0, 0, 8, 8], "tag": "gfx", "transparent": "0xf"}
    assert _call("gfx_locate", args)["code"] == "no_session"


@pytest.mark.parametrize("tool", ["perform", "drive"])
def test_the_settle_wait_is_settle_seconds(tool: str) -> None:
    props = _schema(tool)["properties"]
    assert "wait" not in props and "settle_seconds" in props, props


def test_gfx_view_and_gfx_sweep_default_palette_to_none_and_palette_to_the_only_device() -> None:
    assert _schema("gfx_view")["properties"]["palette"]["default"] == "none"
    assert "palette" not in _schema("gfx_view").get("required", [])
    assert _schema("gfx_sweep")["properties"]["palette"]["default"] == "none"
    assert _schema("palette")["properties"]["palette"]["default"] == ""


@pytest.mark.parametrize("tool", ["gfx_view", "gfx_sweep"])
def test_an_empty_palette_is_the_only_device_and_passes_the_judge(tool: str) -> None:
    args: dict[str, Any] = {"palette": "", "tag": "gfx"}
    if tool == "gfx_view":
        args["layout"] = "8x8"
    assert _call(tool, args)["code"] == "no_session", args


@pytest.mark.parametrize("tool", ["gfx_blits", "gfx_blit_source"])
def test_a_manifest_draw_command_is_draw_command(tool: str) -> None:
    props = _schema(tool)["properties"]
    assert "command" not in props and "draw_command" in props, props


def test_watch_add_by_does_not_offer_expr() -> None:
    assert "expr" not in _schema("watch_add")["properties"]["by"]["enum"]


def test_gfx_film_writes_into_film_dir() -> None:
    props = _schema("gfx_film")["properties"]
    assert "dest" not in props and "film_dir" in props, props


def test_drive_refuses_an_empty_pattern() -> None:
    reply = _call("drive", {"act": [{"op": "status"}], "pattern": ""})
    assert reply["code"] == "bad_argument" and "pattern" in reply["message"], reply


def test_palette_log_publishes_arm() -> None:
    props = _schema("palette_log")["properties"]
    assert props["arm"]["type"] == "boolean" and props["arm"].get("default") is False, props


def test_palette_log_refuses_arm_beside_clear() -> None:
    reply = _call("palette_log", {"palette_port": "ramdac", "arm": True, "clear": True})
    assert reply["code"] == "bad_argument" and "`clear`" in reply["message"], reply


def test_debug_refuses_a_hardreset_before_the_session_gate() -> None:
    reply = _call("debug", {"command": "hardreset"})
    assert reply["code"] == "bad_argument", reply


def test_a_line_too_long_for_a_packet_still_waits_for_the_session() -> None:
    """The packet size is the stub's, negotiated at `start`: with no session there is no size to
    judge a line by, so this refusal stays past the gate."""
    reply = _call("debug", {"command": "print " + "1+" * 4000 + "1"})
    assert reply["code"] == "no_session", reply


def test_an_empty_palette_over_several_devices_is_ambiguous_and_over_none_is_no_channel() -> None:
    import mame_palette as mpalette
    import mame_state as mstate
    with pytest.raises(mstate.Invalid) as several:
        mpalette.parse_pens("MAME_MCP_GFX_PENS_NONE name=- palettes=:pal1,:pal2", "", 0, 4, {})
    assert several.value.code == "ambiguous_ref" and "`palette`" in str(several.value)
    with pytest.raises(mstate.Invalid) as none:
        mpalette.parse_pens("MAME_MCP_GFX_PENS_NONE name=- palettes=", "", 0, 4, {})
    assert none.value.code == "no_channel"
    assert 'if name == "" then' in mpalette.PENS_LUA, "the chunk picks the only device itself"


@pytest.mark.parametrize("ref", ["[Irq_Ptr]+10", "0x1234:0x10"])
def test_watch_clear_judges_a_ref_as_watch_add_does(ref: str) -> None:
    """A pointer offset that reads two ways, and a segmented address in either spelling, are
    refused before anything is matched, as `watch_add` refuses them."""
    assert _call("declaration_clear", {"kind": "watch", "ref": ref})["code"] == "bad_argument", ref


@pytest.mark.parametrize("extra", [{"pen": 5}, {"limit": 4}])
def test_palette_log_refuses_a_read_argument_beside_arm(extra: dict[str, Any]) -> None:
    """Arming reads nothing, so what chooses a read would do nothing, as beside `clear`."""
    reply = _call("palette_log", {"palette_port": "ramdac", "arm": True, **extra})
    assert reply["code"] == "bad_argument" and "`arm`" in reply["message"], reply
