"""The Lua the palette write log (`ramdac`) runs inside MAME, composed from `lua/ramdac-*.lua`
for each protocol a manifest states (a RAMDAC, a latch, a sequence); `ramdac` reads its files.
"""

from __future__ import annotations

from pathlib import Path

from scry_mame import callbacks, capture, lua_source
from scry_mame import manifest as mm
from scry_mame import tap as mtap

REGISTRY = "MCP_RAMDAC"
HEADER = "MCP_RAMDAC"
NOTIFIERS = 2             # the reset one and the state-load one the chunk subscribes


def install_script(log_id: str, r: mm.PalettePort, head: Path, rows: Path, cpu: str | None,
                   synced: bool = False) -> str:
    """The Lua that installs log `log_id`. `synced` starts the index known at 0, which a
    `sequence` log armed before the machine ever executed may (`ramdac.fresh`)."""
    code = lua_source.Code
    return mtap.tap_prelude(REGISTRY) + lua_source.render(
        "ramdac-install", id=log_id,
        ip=code("nil" if r.index_port is None else f"{r.index_port:#x}"),
        dp=code(f"{r.data_port:#x}"), base=r.pen_base, auto=r.auto_increment,
        pmask=code(f"{r.pen_count - 1:#x}"), bind_cpu=code(mtap.bound_cpu(cpu)), space=r.space,
        beam=code(capture.BEAM_LINE_LUA),
        guards=code(lua_source.render("ramdac-guards") if r.packed() else ""),
        remove_old=code(mtap.REMOVE_OLD_TAP), head=str(head), rows=str(rows),
        no_frame=callbacks.NO_FRAME, synced=synced, rows_max=capture.ROWS_MAX,
        taps=code(_TAPS[r.protocol](r)), header=HEADER,
        dumper=code(mtap.register_dumper_once(lua_source.render("ramdac-stamp-then-settle"))),
        answer=mtap.ANSWER_PREFIX).rstrip("\n")


def _ramdac_taps(r: mm.PalettePort) -> str:
    """MAME's `ramdac_device` (`lua/ramdac-taps-ramdac.lua`)."""
    slots = ", ".join(str(mm.COMPONENTS.index(c) + 1) for c in r.order)
    return lua_source.render("ramdac-taps-ramdac", comp=lua_source.Code(f"{{{slots}}}"))


def _packed(r: mm.PalettePort) -> str:
    """Both packed protocols' share (`lua/ramdac-packed.lua`)."""
    return lua_source.render("ramdac-packed", cmask=lua_source.Code(f"{r.colour_mask():#x}"))


def _latch_taps(r: mm.PalettePort) -> str:
    """v30-alt's `paldat_w` (`lua/ramdac-taps-latch.lua`)."""
    index = "" if r.index_port is None else lua_source.render("ramdac-latch-index")
    return (_packed(r) + lua_source.render(
        "ramdac-taps-latch", flag=lua_source.Code(f"{r.index_flag_mask or 0:#x}")) + index)


def _sequence_taps(r: mm.PalettePort) -> str:
    """v30's `twins_pal_w` (`lua/ramdac-taps-sequence.lua`)."""
    return _packed(r) + lua_source.render("ramdac-taps-sequence")


_TAPS = {"ramdac": _ramdac_taps, "latch": _latch_taps, "sequence": _sequence_taps}


def dump_lua() -> str:
    """A chunk's last line: every log dumped at the instant it read the screen."""
    return f"local R = _G.{REGISTRY} if R ~= nil and R.dump_all ~= nil then R.dump_all() end"
