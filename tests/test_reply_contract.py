"""The reply contract of a refusal, fixed for every tool: `status`, `code`, `message`.

WHY A CONTRACT TEST AND NOT A GREP. One verdict spelled several ways (`verdict: INVALID` with
`why`, and sometimes `cause` beside it) leaves every reader of a refusal -- the summary line,
the stdio client, the agents, the live checks -- reading the spelling it happens to know. The
contract is now a CLASS (`scry_core.reply_contract.Invalid`) that refuses a code outside the
table and a reserved field, and an envelope that refuses a malformed refusal; this suite walks
every tool through the two gates every tool crosses (no machine, a running machine) and fixes
the envelope those gates produce.

Every case here was written to go RED against the server before the contract existed.
"""

from __future__ import annotations

import ast
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from scry_core import media_tools
from scry_core.reply_contract import unavailable  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scry_core import reply_contract as contract  # noqa: E402
from session_doubles import SessionFields, use_table  # noqa: E402

import mame_envelope as menvelope  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402

PACKAGE = Path(__file__).resolve().parent.parent
SOURCES = sorted(PACKAGE.glob("*.py"))


def _tools() -> list[str]:
    """Every tool the server registers, read off its source: a list kept by hand would be one
    short the day a tool is added, and the walk would report a contract it never checked."""
    tree = ast.parse((PACKAGE / "server.py").read_text())
    names = [
        node.name for node in tree.body
        if isinstance(node, ast.FunctionDef) and any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "tool"
            for d in node.decorator_list)
    ]
    assert len(names) > 20, "the walk found almost no tools, so it examined nothing"
    # And the media file tools, which the server registers by name through scry-core's
    # `register` rather than by a decorated function of its own.
    return names + list(media_tools.TOOLS)


# The arguments a tool needs to be CALLED at all; the gate refuses before any is judged.
_ARGS: dict[str, dict[str, Any]] = {
    "start": {"binary": "/nonexistent/mame", "system": "x", "rompath": "/",
              "reference_rom": "/nonexistent/rom"},
    # A file that EXISTS (this one), so the row is refused at the gate and not for the path: the
    # path is judged before the machine now, and a row refused for it never reaches the gate.
    "rom_check": {"reference_rom": __file__},
    "run_to": {"ref": "0x4a0", "control": "0x4b0"},
    "run_for": {"milliseconds": 16},
    "trace": {"frames": 2},
    "series_capture": {"frames": [10 ** 6]},
    # The media file tools: absolute paths of files that are not there, refused for the path.
    "image_diff": {"a": "/nonexistent/a.png", "b": "/nonexistent/b.png"},
    "series_diff": {"a": "/nonexistent/a.json", "b": "/nonexistent/b.json"},
    "region_track": {"manifest": "/nonexistent/m.json"},
    "golden_check": {"manifest": "/nonexistent/m.json", "checksums": "/nonexistent/g.sha256"},
    "audio_measure": {"path": "/nonexistent/s.wav"},
    "audio_diff": {"a": "/nonexistent/a.wav", "b": "/nonexistent/b.wav"},
    "breakpoint_at": {"ref": "0x4a0"},
    "watch_add": {"ref": "0x4a0", "mode": "show", "length": 2},
    "regpoint_add": {"condition": "d1==7fff"},
    "breakpoint_clear": {"all": True}, "watch_clear": {"all": True},
    "regpoint_clear": {"all": True},
    "comment_add": {"ref": "0x4a0", "text": "a note"},
    "comment_delete": {"ref": "0x4a0"},
    # paths judged before the gate, so each is one the server accepts: nothing is read or written
    "comment_save": {"dest": str(Path(tempfile.gettempdir()) / "mame-reply-contract.tsv")},
    "comment_load": {"path": str(Path(tempfile.gettempdir()) / "mame-reply-contract.tsv")},
    "symbols_find": {"name": "x"},
    "read_memory": {"ref": "0x4a0"},
    "read_block": {"tag": "blitram"},
    "disassemble": {"ref": "0x4a0"},
    "find": {"ref": "0x4a0", "length": 16, "data_hex": "00"},
    "scan_start": {"ref": "0x4a0", "length": 16},
    "write": {"ref": "0x4a0", "data_hex": "00"},
    "set_register": {"name": "D0", "value": 1},
    # THE `dest` HAS TO BE VALID: a path the server can judge without a machine is judged without
    # one, so a bad path never reaches the gate this suite is about. Nothing is written, because
    # every case here is refused AT THE GATE, before any console.
    "memdump": {"ref": "0x4a0", "length": 16,
                "dest": str(Path(tempfile.gettempdir()) / "mame-reply-contract-never-written.bin")},
    "log": {"pattern": ".", "channel": "emulator"},
    "log_wait": {"pattern": ".", "channel": "emulator", "seconds": 0.01},
    "perform": {"steps": [{"op": "status"}]},
    "perform_export": {"path": "/nonexistent/session.json"},
    "drive": {"act": [{"op": "status"}], "pattern": "."},
    "debug": {"command": "bplist"},
    "lua": {"script": "print(1)"},
    "input": {"port": ":P1", "field": "Coin 1"},
    "record": {"frames": 2},
    "audio_record": {"frames": 2},
    "throttle": {"on": True},
    "state_save": {"name": "a"},
    "state_load": {"name": "a"},
    "focus": {"cpu": "subcpu"},
    "gfx_view": {"layout": {"width": 8, "height": 8, "planes": 1, "planeoffset": [0],
                            "xoffset": "{ STEP8(0,1) }", "yoffset": "{ STEP8(0,8) }",
                            "charincrement": 64}, "palette": "none", "tag": "gfx1"},
    "gfx_locate": {"layouts": [{"width": 8, "height": 8, "planes": 1, "planeoffset": [0],
                                "xoffset": "{ STEP8(0,1) }", "yoffset": "{ STEP8(0,8) }",
                                "charincrement": 64}], "patch": [0, 0, 8, 8], "tag": "gfx1"},
    # a manifest that EXISTS and loads, so the row is refused at the gate and not for the file,
    # which is read before the gate
    "gfx_load": {"path": str(Path(__file__).parent / "fixtures" / "gfx" / "manifest-blitter.yaml")},
    "gfx_blits": {"draw_command": "blit"},
    "gfx_blit_source": {"draw_command": "blit", "index": 0},
    "palette_log": {"palette_port": "ramdac"},
    "gfx_film": {},
    "gfx_sweep": {"tag": "gfx1"},
    "gfx_draft": {},
    "map_load": {"path": "/nonexistent/x.scry-map.json"},
    # An absolute path on every host, so what refuses is the empty map, not the spelling.
    "map_save": {"path": str(Path(tempfile.gettempdir()) / "mame-reply-contract.scry-map.json")},
    "map_add": {"screen": "s", "match": [[0, 0, 1, 1]]},
}


def _no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mstate.STATE, "ses", None)
    monkeypatch.setattr(mstate.STATE, "proc", None)
    monkeypatch.setattr(mstate.STATE, "store", None)
    use_table(monkeypatch, table={})
    monkeypatch.setattr(mstate.STATE, "last_stop", {})
    monkeypatch.setattr(mstate.STATE, "found_stop_last", {})


@pytest.mark.parametrize("name", _tools())
def test_every_tool_answers_the_contract_with_no_machine(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE FIRST GATE. With no machine, every tool that needs one refuses `no_session`; `start`
    refuses its argument before spawning anything; `status` and `close` answer `ok` about the
    absence. Whichever it is, the reply is the one envelope."""
    _no_session(monkeypatch)
    reply = getattr(s, name)(**_ARGS.get(name, {}))
    if name in ("status", "close"):
        assert reply["status"] == "ok" and "code" not in reply and "message" not in reply, reply
        return
    # `start` refuses its argument; a media tool and the export need no machine and refuse the
    # path they were given.
    # A map's file tools need no machine either: a load refuses the missing file, a save the
    # empty map.
    expected = {"map_load": "bad_argument", "map_save": "needs_call"}.get(name)
    contract.check_refusal(name, reply, expected or ("bad_argument" if name in (
        "start", "perform_export") or name in media_tools.TOOLS else "no_session"))


class _Running(SessionFields):
    """A machine that RUNS and nothing else: what the readers' gate reads."""

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
            "debug", "comment_add", "comment_delete", "comment_load",
            "step", "run_to", "run_for", "write", "set_register", "reset", "rom_check",
            "resume", "scan_start", "scan_filter", "trace", "series_capture",
            "screen_signature"]


@pytest.mark.parametrize("name", _READERS)
def test_every_reader_refuses_a_running_machine_with_the_contract(
    name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE SECOND GATE: `not_stopped`, with the two context fields beside the envelope."""
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
    for word in ("verdict", "why", "reason", "cause"):
        with pytest.raises(TypeError, match=word):
            menvelope.envelope({"status": "INVALID", "code": "bad_argument", "message": "x",
                                word: "x"})
    ok = menvelope.envelope({"verdict": "TARGET"})
    assert ok["status"] == "ok" and ok["verdict"] == "TARGET"
    # A ROW'S OR A FIELD'S `why` IS AN OK REPLY'S OWN WORD, and an unread datum is its shape.
    rows = menvelope.envelope({"rows": [{"why": "a row's"}], "cycles": unavailable("n")})
    assert rows["status"] == "ok" and rows["cycles"] == {"available": False, "why": "n"}
    bad = menvelope.invalid("control_silent", "cold", control_hits=0)
    assert list(bad)[:3] == ["status", "code", "message"] and bad["control_hits"] == 0


def test_every_code_written_in_the_sources_is_in_the_table() -> None:
    """The class checks at RUNTIME; the contract's own scan reads the sources so a code typed
    wrong in a branch no test reaches is caught here, and a code cannot be computed from a
    string at runtime."""
    seen = contract.codes_written_in(SOURCES)
    assert len(seen) > 40, "the scan found almost no refusals, so it examined nothing"
    wrong = [(f, n, c) for f, n, c in seen if c not in contract.CODES]
    assert not wrong, wrong


def _prose_matched_for_a_code(path: Path) -> list[int]:
    """The lines of `path` that test a string literal against `why`, `message` or `str(e)`:
    the shape of a refusal's CODE chosen by reading its own prose."""
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
    """A code decided by `"already armed under" in why` changes in silence the day the
    sentence is reworded (it happened, and a test caught it after the fact). The helper that
    knows why a call is refused answers the code beside the text, and this scan holds every
    module of the package to it. The scan is checked against a planted case first, so an empty
    finding is a finding and not a scan that read nothing."""
    planted = tmp_path / "planted.py"
    planted.write_text('code = "ambiguous_ref" if "already" in why else "bad_argument"\n'
                       'if "armed" in str(e):\n    pass\nif "x" in message:\n    pass\n'
                       'if "unknown symbol" in refusal:\n    pass\n')
    assert _prose_matched_for_a_code(planted) == [1, 2, 4], "the control did not fire"
    found = [(src.name, line) for src in SOURCES for line in _prose_matched_for_a_code(src)]
    assert not found, f"a refusal's code is chosen by matching prose at {found}"


_FAMILY_MODULES = ["mame_arming.py", "mame_breakpoints.py", "mame_watches.py", "mame_rearm.py",
                   "mame_regpoints.py", "mame_declarations.py", "mame_tally.py",
                   "mame_lists.py", "mame_conditions.py", "mame_clear.py"]


def _literal_text(node: ast.expr) -> str | None:
    """A string literal, an f-string (its placeholders as `{}`) or a concatenation of them."""
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
    """Every literal message of a refusal in `path`: the second argument of an
    `st.Invalid(...)` / `st.invalid(...)` call, and the first of a `DeclarationError(...)`,
    the store's own refusal, which reaches a caller as `bad_argument` through `str(e)`."""
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
    """A refusal that ends without naming what resolves it leaves the agent retrying the
    same call. The literal message of every refusal in the four modules of the declarations
    tier names a tool of the server, backticked (`breakpoint_clear(ref=...)`, `start`,
    `debug("bpclear 0x3")`); the store's `DeclarationError`s are refusals too, since a caller
    reads them as `bad_argument`. The scan is checked against a planted file first, so an empty
    finding is a finding and not a scan that read nothing; a message built by a helper is
    read where the helper returns it, which this scan does not reach, and says so."""
    tools = _tools()
    names = re.compile(r"`(" + "|".join(tools) + r")(?:\(|`)")
    planted = tmp_path / "planted.py"
    planted.write_text('st.Invalid("bad_argument", "nothing here")\n'
                       'st.invalid("bad_argument", f"x {y}: `breakpoint_clear(ref=...)` does")\n'
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
