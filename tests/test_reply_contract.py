"""The reply contract of a refusal, fixed for every tool: `status`, `code`, `message`."""

from __future__ import annotations

import ast
import asyncio
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest
from scry_core import media_tools, png, reply_schema, series
from scry_core import reply_contract as contract  # noqa: E402
from scry_core.host_program import absolute as _abs
from scry_core.knowledge import KINDS  # noqa: E402
from scry_core.reply_contract import unavailable  # noqa: E402
from session_doubles import SessionFields, use_table  # noqa: E402

import scry_mame
from scry_mame import envelope as menvelope  # noqa: E402
from scry_mame import naming as mnaming  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as mstate  # noqa: E402

PACKAGE = Path(scry_mame.__file__).resolve().parent
SOURCES = sorted(PACKAGE.glob("*.py"))


def _tools() -> list[str]:
    """Every tool the server declares, read off its source, for the scans that match names."""
    tree = ast.parse((PACKAGE / "server.py").read_text())
    names = [
        node.name for node in tree.body
        if isinstance(node, ast.FunctionDef) and any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "tool"
            for d in node.decorator_list)
    ]
    assert len(names) > 20, "the walk found almost no tools, so it examined nothing"
    return names + list(media_tools.TOOLS)


def _served_tools() -> list[str]:
    """Every tool the MCP layer serves, which is the roster the calls below walk."""
    names = [t.name for t in asyncio.run(s.mcp.list_tools())]
    assert len(names) > 20, "the MCP layer served almost no tools, so it examined nothing"
    return names


_ARGS: dict[str, dict[str, Any]] = {
    "start": {"binary": _abs("nonexistent", "mame"), "system": "x", "rompath": _abs(),
              "reference_rom": _abs("nonexistent", "rom")},
    # exists, so the gate refuses it and not the path
    "rom_check": {"reference_rom": __file__},
    "run_to": {"ref": "0x4a0", "control": "0x4b0"},
    "run_for": {"milliseconds": 16},
    "screen_wait": {"screen": "menu"},
    "trace": {"frames": 2},
    "series_capture": {"at_frames": [10 ** 6]},
    "image_compare": {"method": "image", "a": _abs("nonexistent", "a.png"),
                      "b": _abs("nonexistent", "b.png")},
    "audio_compare": {"method": "diff", "a": _abs("nonexistent", "a.wav"),
                      "b": _abs("nonexistent", "b.wav")},
    "breakpoint_at": {"ref": "0x4a0"},
    "watch_add": {"ref": "0x4a0", "mode": "show", "length": 2},
    "regpoint_add": {"condition": "d1==7fff"},
    "declaration_clear": {"kind": "watch", "all": True},
    "comment_write": {"method": "add", "ref": "0x4a0", "text": "a note"},
    "symbols_find": {"name": "x"},
    "read_memory": {"ref": "0x4a0"},
    "read_block": {"tag": "blitram"},
    "disassemble": {"ref": "0x4a0"},
    "find": {"ref": "0x4a0", "length": 16, "data_hex": "00"},
    "scan": {"method": "start", "ref": "0x4a0", "length": 16},
    "write": {"ref": "0x4a0", "data_hex": "00"},
    "set_register": {"name": "D0", "value": 1},
    # a valid `dest`: a bad path is judged before the gate under test
    "memdump": {"ref": "0x4a0", "length": 16,
                "dest": str(Path(tempfile.gettempdir()) / "mame-reply-contract-never-written.bin")},
    "log": {"pattern": ".", "channel": "emulator"},
    "log_wait": {"pattern": ".", "channel": "emulator", "seconds": 0.01},
    "perform": {"steps": [{"op": "status"}]},
    "perform_export": {"dest": _abs("nonexistent", "session.json")},
    "drive": {"act": [{"op": "status"}], "pattern": "."},
    "debug": {"command": "bplist"},
    "lua": {"script": "print(1)"},
    "input": {"port": ":P1", "field": "Coin 1"},
    "record": {"frames": 2},
    "audio_record": {"frames": 2},
    "throttle": {"on": True},
    "state_write": {"method": "load", "name": "a"},
    "cpu_focus": {"cpu": "subcpu"},
    "gfx_view": {"layout": {"width": 8, "height": 8, "planes": 1, "planeoffset": [0],
                            "xoffset": "{ STEP8(0,1) }", "yoffset": "{ STEP8(0,8) }",
                            "charincrement": 64}, "palette": "none", "tag": "gfx1"},
    "gfx_locate": {"layouts": [{"width": 8, "height": 8, "planes": 1, "planeoffset": [0],
                                "xoffset": "{ STEP8(0,1) }", "yoffset": "{ STEP8(0,8) }",
                                "charincrement": 64}], "patch": [0, 0, 8, 8], "tag": "gfx1"},
    # a manifest that loads, since the file is read before the gate
    "gfx_load": {"path": str(Path(__file__).parent / "fixtures" / "gfx" / "manifest-blitter.yaml")},
    "gfx_blits": {"draw_command": "blit"},
    "gfx_blit_source": {"draw_command": "blit", "index": 0},
    "palette_log": {"palette_port": "ramdac"},
    "gfx_film": {},
    "gfx_sweep": {"tag": "gfx1"},
    "gfx_draft": {},
    # absolute on every host, so the empty map refuses, not the spelling
    "screen_map_write": {"method": "save",
                  "dest": str(Path(tempfile.gettempdir()) / "mame-reply-contract-screen-map.json")},
}


def _no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "proc", None)
    monkeypatch.setattr(mstate.STATE, "store", None)
    use_table(monkeypatch, table={})
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    monkeypatch.setattr(mstate.STATE, "found_stop_last", {})


@pytest.mark.parametrize("name", _served_tools())
def test_every_tool_answers_the_contract_with_no_machine(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no machine, every tool answers the one envelope: a refusal, or `ok` for status/close."""
    _no_session(monkeypatch)
    reply = getattr(s, name)(**_ARGS.get(name, {}))
    if name in ("status", "close"):
        assert reply["status"] == "ok" and "code" not in reply and "message" not in reply, reply
        return
    # start, the media tools and the export refuse their argument; a map save refuses the empty map
    expected = {"screen_map_write": "needs_call", "promote": "bad_argument",
                # asks nothing of a machine: with nothing to look up, its own judge refuses
                "knowledge_find": "bad_argument"}.get(name)
    contract.check_refusal(name, reply, expected or ("bad_argument" if name in (
        "start", "perform_export") or name in media_tools.TOOLS else "no_session"))


def test_a_kind_the_base_lacks_answers_the_reply_model(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `no_channel` refusal names the kinds the base holds, and the model declares them."""
    _no_session(monkeypatch)
    base = mnaming.base()
    absent = [k for k in KINDS if k not in base.kinds() and k not in mnaming.Live.kinds]
    assert absent, "the base holds every kind, so this case would examine nothing"
    for kind in absent:
        reply = s.knowledge_find(kind=kind)
        contract.check_refusal("knowledge_find", reply, "no_channel")
        assert reply["kinds"] == list(base.kinds()), reply
        reply_schema.check("knowledge_find", reply)


def _frame(lit: set[tuple[int, int]]) -> png.Raster:
    """A black 3x2 picture with the pixels in `lit` white."""
    width, height = 3, 2
    px = bytearray(bytes((0, 0, 0)) * (width * height))
    for x, y in lit:
        at = (y * width + x) * 3
        px[at:at + 3] = bytes((255, 255, 255))
    return png.Raster(width, height, bytes(px))


def _manifest(folder: Path, frames: dict[int, png.Raster]) -> str:
    """The `scry-series/1` manifest of `frames` in `folder`, as `image_compare` takes it."""
    folder.mkdir()
    for n, picture in frames.items():
        (folder / series.frame_name(n)).write_bytes(png.encode(picture))
    return str(series.write_manifest(folder, "test", "frame_number", None,
                                     sorted(frames))["manifest"])


def test_a_series_that_cannot_differ_answers_the_reply_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `control_silent` refusal names the series that never changed, as its model says."""
    _no_session(monkeypatch)
    a = _manifest(tmp_path / "a", {1: _frame(set()), 2: _frame(set())})
    b = _manifest(tmp_path / "b", {1: _frame(set()), 2: _frame({(0, 0)})})
    reply = s.image_compare(method="series", a=a, b=b)
    contract.check_refusal("image_compare", reply, "control_silent")
    assert reply["series"] == "a", reply
    reply_schema.check("image_compare", reply)


class _Running(SessionFields):
    """A machine that runs and nothing else."""

    running = True
    stop_count = 1
    last_stop_packet = "T05"
    writes = 0
    byte_order = "big"

    def poll_stop(self, timeout: float = 0.0) -> bool:
        return False

    def current_pc(self) -> int:
        return 0x4A0


class _Alive:
    pid = 4242

    def poll(self) -> int | None:
        return None


_READERS = ["registers", "read_memory", "read_block", "disassemble", "find", "history", "memdump",
            "debug", "comment_write",
            "step", "run_to", "run_for", "write", "set_register", "reset", "rom_check",
            "resume", "scan", "trace", "series_capture",
            "screen_signature"]


@pytest.mark.parametrize("name", _READERS)
def test_every_reader_refuses_a_running_machine_with_the_contract(
    name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A running machine refuses with `not_stopped` and the two context fields."""
    ses = _Running()
    monkeypatch.setattr(mstate.STATE, "alive", lambda: ses)
    monkeypatch.setattr(mstate.STATE, "ses", ses)
    monkeypatch.setattr(mstate.STATE, "proc", _Alive())
    monkeypatch.setattr(mstate.STATE, "scratch", tmp_path)
    use_table(monkeypatch, table={})
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    monkeypatch.setattr(mstate.STATE, "found_stop_last", {})
    reply = getattr(s, name)(**_ARGS.get(name, {}))
    contract.check_refusal(name, reply, "not_stopped")
    assert "last_stop" in reply and "answers_while_running" in reply, reply


def test_the_envelope_refuses_a_malformed_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "proc", None)
    monkeypatch.setattr(mstate.STATE, "found_stop_last", {})
    with pytest.raises(TypeError, match="code"):
        menvelope.envelope({"status": "INVALID", "message": "x"})
    with pytest.raises(TypeError, match="verdict"):
        menvelope.envelope({"status": "INVALID", "code": "bad_argument", "message": "x",
                            "verdict": "INVALID"})
    with pytest.raises(TypeError, match="ok"):
        menvelope.envelope({"code": "bad_argument"})
    with pytest.raises(TypeError, match="status"):
        menvelope.envelope({"status": "maybe"})
    for word in ("verdict", "why", "reason"):
        with pytest.raises(TypeError, match=word):
            menvelope.envelope({"status": "INVALID", "code": "bad_argument", "message": "x",
                                word: "x"})
    ok = menvelope.envelope({"verdict": "TARGET"})
    assert ok["status"] == "ok" and ok["verdict"] == "TARGET"
    # a row's or a field's `why` is an ok reply's own word
    rows = menvelope.envelope({"rows": [{"why": "a row's"}], "cycles": unavailable("n")})
    assert rows["status"] == "ok" and rows["cycles"] == {"available": False, "why": "n"}
    bad = menvelope.invalid("control_silent", "cold", control_hits=0)
    assert list(bad)[:3] == ["status", "code", "message"] and bad["control_hits"] == 0


def test_every_code_written_in_the_sources_is_in_the_table() -> None:
    """The scan reads the sources, so a wrong code in a branch no test reaches is caught."""
    seen = contract.codes_written_in(SOURCES)
    assert len(seen) > 40, "the scan found almost no refusals, so it examined nothing"
    wrong = [(f, n, c) for f, n, c in seen if c not in contract.CODES]
    assert not wrong, wrong


def _prose_matched_for_a_code(path: Path) -> list[int]:
    """Lines testing a string literal against `why`, `message` or `str(e)`."""
    tree = ast.parse(path.read_text())
    lines: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Compare) and len(node.ops) == 1
                and isinstance(node.ops[0], ast.In | ast.NotIn)
                and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)):
            continue
        right = node.comparators[0]
        prose = (isinstance(right, ast.Name) and right.id in ("why", "message")) or (
            isinstance(right, ast.Call) and isinstance(right.func, ast.Name)
            and right.func.id == "str" and len(right.args) == 1)
        if prose:
            lines.append(node.lineno)
    return sorted(lines)


def test_no_refusal_code_is_chosen_by_matching_its_own_prose(tmp_path: Path) -> None:
    """A code decided by `"already armed under" in why` changes silently when the sentence is
    reworded; the planted control proves an empty finding is not a scan that read nothing."""
    planted = tmp_path / "planted.py"
    planted.write_text('code = "ambiguous_ref" if "already" in why else "bad_argument"\n'
                       'if "armed" in str(e):\n    pass\nif "x" in message:\n    pass\n'
                       'if "unknown symbol" in refusal:\n    pass\n')
    assert _prose_matched_for_a_code(planted) == [1, 2, 4], "the control did not fire"
    found = [(src.name, line) for src in SOURCES for line in _prose_matched_for_a_code(src)]
    assert not found, f"a refusal's code is chosen by matching prose at {found}"


_FAMILY_MODULES = ["arming.py", "breakpoints.py", "watches.py", "rearm.py",
                   "regpoints.py", "declarations.py", "tally.py",
                   "lists.py", "conditions.py", "clear.py"]


def _literal_text(node: ast.expr) -> str | None:
    """A string literal, an f-string (placeholders as `{}`) or a concatenation of them."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "{}"
                       for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal_text(node.left), _literal_text(node.right)
        return None if left is None or right is None else left + right
    return None


def _refusal_literals(path: Path) -> list[tuple[int, str]]:
    """Literal refusal messages: arg 2 of `Invalid`/`invalid`, arg 1 of `DeclarationError`
    (which a caller reads as `bad_argument`)."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call):
            continue
        if (isinstance(node.func, ast.Attribute) and node.func.attr in ("Invalid", "invalid")
                and len(node.args) >= 2):
            message = node.args[1]
        elif (isinstance(node.func, ast.Name) and node.func.id == "DeclarationError"
              and len(node.args) >= 1):
            message = node.args[0]
        else:
            continue
        text = _literal_text(message)
        if text is not None:
            found.append((node.lineno, " ".join(text.split())))
    return found


def test_every_refusal_of_the_three_families_names_the_call_that_resolves_it(
    tmp_path: Path,
) -> None:
    """Every literal refusal of the declarations tier names a backticked tool that resolves it;
    a message built by a helper is not reached by this scan."""
    tools = _tools()
    names = re.compile(r"`(" + "|".join(tools) + r")(?:\(|`)")
    planted = tmp_path / "planted.py"
    planted.write_text('st.Invalid("bad_argument", "nothing here")\n'
                       'st.invalid("bad_argument", f"x {y}: `declaration_clear(ref=...)` does")\n'
                       'st.Invalid("bad_argument", "a " "joined `start`")\n'
                       'st.Invalid("bad_argument", helper(x))\n'
                       'raise DeclarationError(f"a watch needs {x}: `watch_add(mode=...)`")\n'
                       'raise DeclarationError(str(e))\n')
    scanned = _refusal_literals(planted)
    assert [line for line, _ in scanned] == [1, 2, 3, 5], "the control did not fire"
    assert [bool(names.search(text)) for _, text in scanned] == [False, True, True, True]
    nameless: list[str] = []
    total = 0
    for name in _FAMILY_MODULES:
        for line, text in _refusal_literals(PACKAGE / name):
            total += 1
            if not names.search(text):
                nameless.append(f"{name}:{line}: {text[:90]}")
    assert total > 20, "the scan found almost no refusals, so it examined nothing"
    assert not nameless, "a refusal that names no resolving call:\n" + "\n".join(nameless)
