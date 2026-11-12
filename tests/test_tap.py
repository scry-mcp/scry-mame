"""The fragments every tap's install script is composed of, pinned as the exact Lua they emit (a
fragment the four installs share is one place a change reaches all of them), the whole-dump reader
the four parsers share, and the refusal a port's watch gives when nothing sizes it.
"""

from __future__ import annotations

import re

import pytest
from lua_text import squash

from scry_mame import (
    callbacks,  # noqa: E402
    iotaps,  # noqa: E402
)
from scry_mame import state as mstate  # noqa: E402
from scry_mame import tap as mtap  # noqa: E402


def test_the_prelude_is_the_guard_then_the_registry_made_once() -> None:
    assert mtap.tap_prelude("MCP_X") == callbacks.LUA + (
        "local T = _G.MCP_X\n"
        "if T == nil then\n  T = { items = {}, periodic = false }\n  _G.MCP_X = T\nend\n")


def test_a_named_cpu_is_bound_by_name_and_no_name_is_the_visible_one() -> None:
    assert mtap.bound_cpu(":subcpu") == 'local cpu = manager.machine.devices[":subcpu"]'
    assert mtap.bound_cpu(None) == (
        "local cpu = manager.machine.debugger and manager.machine.debugger.visible_cpu "
        'or manager.machine.devices[":maincpu"]')


def test_the_old_tap_under_the_id_is_removed_and_kept_as_old() -> None:
    assert squash(mtap.REMOVE_OLD_TAP) == squash(
        "local old = T.items[id]\nif old ~= nil and old.tap ~= nil then old.tap:remove() end")


def test_the_dumper_is_registered_by_the_first_install_alone() -> None:
    assert mtap.register_dumper_once("  dump_at_stops(T, f)\n") == (
        "if not T.periodic then\n  T.periodic = true\n  dump_at_stops(T, f)\nend")
    with pytest.raises(AssertionError):
        mtap.register_dumper_once("  dump_at_stops(T, f)")


_HEAD = re.compile(r"^H (\S+)$")


def test_a_header_alone_with_a_stray_line_is_no_header() -> None:
    assert callbacks.read_whole("H one\nend\n", _HEAD, with_body=False) is not None
    assert callbacks.read_whole("H one\nv 1\nend\n", _HEAD, with_body=False) is None
    whole = callbacks.read_whole("H one\nv 1\nend\n", _HEAD, with_body=True)
    assert whole is not None and whole[1] == ["v 1"]
    assert callbacks.read_whole("H one\nv 1\n", _HEAD, with_body=True) is None, "no `end`"


@pytest.mark.parametrize(("mode", "said"), [
    ("count", "a count watch on a port needs a length in bytes or a sized fmt"),
    ("capture", "a capture watch on a port needs a length in bytes or a sized fmt, or a block "
                "the symbol table types"),
])
def test_a_port_watch_nothing_sizes_is_refused_saying_what_would(mode: str, said: str) -> None:
    with pytest.raises(mstate.Invalid) as e:
        iotaps._sized("0x6", mode, 0, "auto", "address", None)
    assert str(e.value) == said and e.value.code == "bad_argument"
