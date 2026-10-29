"""Structural checks that `args` routes every tool to the one judge its module also calls."""

from __future__ import annotations

import ast
import asyncio
import inspect
import pathlib
import re
import tempfile
from collections.abc import Callable
from typing import Any

import pytest
from scry_core import media_tools, roster
from scry_core import strict_arguments as strict  # noqa: E402
from scry_core.host_program import absolute as _abs

from scry_mame import (
    advance,  # noqa: E402
    args,  # noqa: E402
    block,  # noqa: E402
    breakpoints,  # noqa: E402
    comments,  # noqa: E402
    files,  # noqa: E402
    folds,  # noqa: E402
    launch,  # noqa: E402
    machine,  # noqa: E402
    manifest,  # noqa: E402
    read,  # noqa: E402
    regpoints,  # noqa: E402
    running,  # noqa: E402
    savestates,  # noqa: E402
    sequence,  # noqa: E402
    watches,  # noqa: E402
)
from scry_mame import audio as maudio  # noqa: E402
from scry_mame import blits as mblits  # noqa: E402
from scry_mame import docs as mdocs  # noqa: E402
from scry_mame import draft as mdraft  # noqa: E402
from scry_mame import film as mfilm  # noqa: E402
from scry_mame import focus as mfocus  # noqa: E402
from scry_mame import gfx as mgfx  # noqa: E402
from scry_mame import locate as mlocate  # noqa: E402
from scry_mame import lua as mlua  # noqa: E402
from scry_mame import maps as mmaps  # noqa: E402
from scry_mame import mcp as mame_mcp  # noqa: E402
from scry_mame import palette as mpalette  # noqa: E402
from scry_mame import ramdac as mramdac  # noqa: E402
from scry_mame import recording as mrec
from scry_mame import scan as mscan  # noqa: E402
from scry_mame import screen as mscreen  # noqa: E402
from scry_mame import series as mseries  # noqa: E402
from scry_mame import server as s  # noqa: E402
from scry_mame import state as st  # noqa: E402
from scry_mame import sweep as msweep  # noqa: E402
from scry_mame import trace as mtrace  # noqa: E402
from scry_mame import write as mwrite  # noqa: E402

SERVER = pathlib.Path(s.__file__)


def _registered() -> set[str]:
    return {t.name for t in asyncio.run(s.mcp.list_tools())}


#: Media file tools have scry-core's bodies, so no `args.check` call site exists here for them.
MEDIA = set(media_tools.TOOLS)
FOLDS: dict[str, Any] = {"comment_write": folds.COMMENT, "screen_map_write": folds.MAP,
                         "scan": folds.SCAN, "state_write": folds.STATE_METHODS}


def _call_sites() -> dict[str, set[str]]:
    """Each `args.check("<tool>", ...)` keyed by tool, with its keywords."""
    out: dict[str, set[str]] = {}
    for fn in ast.parse(SERVER.read_text(encoding="utf-8")).body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "check"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                tool = str(node.args[0].value)
                assert tool == fn.name, f"{fn.name} asks for {tool!r}'s check, not its own"
                assert tool not in out, f"{tool} asks for its check twice"
                out[tool] = ({p for p in inspect.signature(getattr(s, tool)).parameters
                              if p != "ctx"} if any(kw.arg is None for kw in node.keywords)
                             else {kw.arg for kw in node.keywords if kw.arg})
    return out


def test_every_registered_tool_is_either_checked_or_named_as_unchecked() -> None:
    """Red both ways: a tool with no entry, and an entry for a tool that is gone."""
    registered = _registered()
    assert not sorted(registered - args.KNOWN), (
        f"no entry in args, not even a deliberate none: {sorted(registered - args.KNOWN)}")
    assert not sorted(args.KNOWN - registered), (
        f"mame_args names tools this server does not register: {sorted(args.KNOWN - registered)}")


def test_every_checked_tool_actually_asks_its_check() -> None:
    """A tool in `BY_TOOL` must call `args.check(...)` in its body, or it is judged late."""
    missing = sorted(set(args.BY_TOOL) - set(_call_sites()) - MEDIA)
    assert not missing, f"in BY_TOOL but never asked by the tool body: {missing}"


def test_no_tool_in_machine_judges_asks_for_a_check_anyway() -> None:
    """A call site for a `MACHINE_JUDGES` tool would read as a guarantee while judging nothing."""
    pointless = sorted(set(_call_sites()) & args.MACHINE_JUDGES)
    assert not pointless, f"these ask for a check the table says they do not have: {pointless}"


@pytest.mark.parametrize("tool", sorted(set(args.BY_TOOL) - MEDIA))
def test_each_call_site_passes_what_its_check_takes(tool: str) -> None:
    """Checks end in `**_` for batch steps, so a misspelt keyword is swallowed and never judged."""
    passed = _call_sites()[tool]
    sig = inspect.signature(args.BY_TOOL[tool])
    named = {p.name for p in sig.parameters.values()
             if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    if tool in FOLDS:
        named = passed
    required = {p.name for p in sig.parameters.values()
                if p.default is p.empty and p.kind is p.POSITIONAL_OR_KEYWORD}
    assert not passed - named, (
        f"{tool} passes {sorted(passed - named)}, which {args.BY_TOOL[tool].__qualname__} does not "
        f"take: swallowed by `**_` and never judged")
    assert not required - passed, (
        f"{tool} does not pass {sorted(required - passed)}, which its check requires")
    # A defaulted parameter the tool also has is not optional: unpassed, the check judges its own
    # default instead of what the caller sent.
    tool_params = {p.name for p in inspect.signature(getattr(s, tool)).parameters.values()
                   if p.name != "ctx"}
    owed = (named & tool_params) - passed
    assert not owed, (
        f"{tool} has {sorted(owed)} and does not pass it to its check, which declares it: the "
        f"check would judge its own default instead of what the caller sent")


#: The same object, not an equal one, for every entry of the table.
OWNERS = {
    "read_memory": read.check_read_memory, "disassemble": read.check_disassemble,
    "registers": read.check_registers, "read_block": block.check_read_block,
    "find": read.check_find, "history": read.check_history,
    "symbols_find": read.check_symbols_find, "memdump": files.check_memdump,
    "snapshot": files.check_snapshot, "log": files.check_log,
    "log_wait": files.check_log_wait, "run_for": advance.check_run_for,
    "step": advance.check_step, "run_to": advance.check_run_to,
    "breakpoint_at": breakpoints.check_breakpoint_at, "watch_add": watches.check_watch_add,
    "regpoint_add": regpoints.check_regpoint_add,
    "write": mwrite.check_write, "set_register": mwrite.check_set_register,
    "perform": sequence.check_perform,
    "drive": sequence.check_drive,
}

OWNERS.update({
    "declaration_list": folds.check_list_declarations,
    "declaration_clear": folds.check_clear_declarations, "debug": mwrite.check_debug,
    "machine_map": machine.check_machine_map,
    "resume": running.check_resume, "throttle": mlua.check_throttle,
    "record": mrec.check_record, "input": mlua.check_input,
    "audio_record": maudio.check_audio_record,
    "screen_signature": mscreen.check_screen_signature, "lua": mlua.check_lua,
    "rom_check": launch.check_rom_check, "start": launch.check_start,
    "focus": mfocus.check_focus,
    "palette": mpalette.check_palette, "screen_view": mscreen.check_screen_view,
    "gfx_view": mgfx.check_gfx_view, "gfx_locate": mlocate.check_gfx_locate,
    "gfx_load": manifest.check_gfx_load, "gfx_blits": mblits.check_gfx_blits,
    "gfx_blit_source": mblits.check_gfx_blit_source,
    "palette_log": mramdac.check_palette_log, "gfx_film": mfilm.check_gfx_film,
    "gfx_sweep": msweep.check_gfx_sweep, "gfx_draft": mdraft.check_gfx_draft,
    "trace": mtrace.check_trace, "series_capture": mseries.check_series_capture,
    **{name: folds.CHECKS[name] for name in FOLDS},
    **{name: spec.check for name, spec in media_tools.TOOLS.items()},
})

METHOD_OWNERS: dict[tuple[str, str], Callable[..., Any]] = {
    ("comment_write", "add"): comments.check_add_comment,
    ("comment_write", "delete"): comments.check_delete_comment,
    ("comment_write", "save"): comments.check_save_comments,
    ("comment_write", "load"): comments.check_load_comments,
    ("screen_map_write", "add"): mmaps.check_add_map,
    ("screen_map_write", "load"): mmaps.check_load_map,
    ("screen_map_write", "save"): mmaps.check_save_map,
    ("scan", "start"): mscan.check_start_scan, ("scan", "filter"): mscan.check_filter_scan,
    ("state_write", "save"): savestates.check_state_name,
    ("state_write", "load"): savestates.check_state_name,
}


@pytest.mark.parametrize(("tool", "method"), sorted(METHOD_OWNERS))
def test_each_method_is_routed_to_its_modules_own_function(tool: str, method: str) -> None:
    assert FOLDS[tool][method].check is METHOD_OWNERS[(tool, method)]


def test_owners_names_every_entry_of_the_table() -> None:
    assert set(OWNERS) == set(args.BY_TOOL), sorted(set(OWNERS) ^ set(args.BY_TOOL))


@pytest.mark.parametrize("tool", sorted(OWNERS))
def test_the_table_routes_to_the_modules_own_function(tool: str) -> None:
    assert args.BY_TOOL[tool] is OWNERS[tool], (
        f"{tool} is routed somewhere other than the module function that owns the rule")


def test_the_surfaces_table_is_the_batchs_plus_the_tools_that_are_not_operations() -> None:
    """A batch op missing from the table is skipped by `preflight`; set equality, since an
    intersection stays green when an entry is deleted."""
    surface = set(sequence.BY_OP) | {"perform", "drive", "rom_check", "start"}
    assert set(args.BY_TOOL) == surface, sorted(set(args.BY_TOOL) ^ surface)
    differ = sorted(op for op in sequence.BY_OP if sequence.BY_OP[op] is not args.BY_TOOL[op])
    assert not differ, f"the batch and the surface route these elsewhere from each other: {differ}"


def test_every_step_operation_is_either_checked_or_named_as_unchecked() -> None:
    """An operation with no entry and no deliberate none is a step nobody judges."""
    ops = set(s._step_ops())
    covered = set(sequence.BY_OP) | sequence.MACHINE_JUDGES
    assert not sorted(ops - covered), (
        f"steps nobody judges before the list runs: {sorted(ops - covered)}")
    assert not sorted(covered - ops), f"named but not an operation: {sorted(covered - ops)}"


def test_every_module_body_asks_its_own_check() -> None:
    """The module function that does the work must ask the same check the server asks."""
    bodies: dict[str, Callable[..., Any]] = {
        "read_memory": read.read_memory, "disassemble": read.disassemble,
        "registers": read.registers_at_last_stop,
        "read_block": block.read_block,
        "find": read.find, "history": read.history,
        "symbols_find": read.symbols_find, "memdump": files.memdump,
        "snapshot": files.snapshot, "log": files.log, "log_wait": files.log_wait,
        "run_for": advance.run_for, "step": advance.step, "run_to": advance.run_to,
        "resume": running.resume, "throttle": mlua.throttle,
        "breakpoint_at": breakpoints.breakpoint_at, "watch_add": watches.watch_add,
        "regpoint_add": regpoints.regpoint_add,
        "write": mwrite.write, "set_register": mwrite.set_register,
        "record": mrec.record, "input": mlua.input_field,
        "audio_record": maudio.audio_record,
        "screen_signature": mscreen.screen_signature, "lua": mlua.lua,
        "focus": mfocus.focus,
        "palette": mpalette.palette, "screen_view": mscreen.screen_view,
        "gfx_view": mgfx.gfx_view, "gfx_locate": mlocate.gfx_locate,
        "gfx_load": manifest.gfx_load, "gfx_blits": mblits.gfx_blits,
        "gfx_blit_source": mblits.gfx_blit_source, "palette_log": mramdac.palette_log,
        "gfx_film": mfilm.gfx_film, "gfx_sweep": msweep.gfx_sweep, "gfx_draft": mdraft.gfx_draft,
        "trace": mtrace.trace,
        "declaration_list": folds.list_declarations,
        "declaration_clear": folds.clear_declarations, "debug": mwrite.debug,
        "machine_map": machine.machine_map, "series_capture": mseries.series_capture,
    }
    method_bodies: dict[tuple[str, str], Callable[..., Any]] = {
        ("comment_write", "add"): comments.add_comment,
        ("comment_write", "delete"): comments.delete_comment,
        ("comment_write", "save"): comments.save_comments,
        ("comment_write", "load"): comments.load_comments,
        ("screen_map_write", "add"): mmaps.add_map, ("screen_map_write", "load"): mmaps.load_map,
        ("screen_map_write", "save"): mmaps.save_map,
        ("scan", "start"): mscan.start_scan, ("scan", "filter"): mscan.filter_scan,
        ("state_write", "save"): savestates.save_state,
        ("state_write", "load"): savestates.load_state,
    }
    folded = set(FOLDS) | MEDIA
    assert set(bodies) | folded == set(sequence.BY_OP), sorted(
        (set(bodies) | folded) ^ set(sequence.BY_OP))
    assert set(method_bodies) == set(METHOD_OWNERS)
    checked: list[tuple[str, Callable[..., Any], Callable[..., Any]]] = [
        (op, body, sequence.BY_OP[op]) for op, body in bodies.items()]
    checked += [(f"{t} {m}", body, METHOD_OWNERS[(t, m)])
                for (t, m), body in method_bodies.items()]
    for op, body, check in checked:
        src = inspect.getsource(body)
        wanted = f"{check.__name__}("
        assert wanted in src, f"{op}'s body never asks {check.__name__}"


def test_an_unknown_tool_name_is_refused_rather_than_passed_through() -> None:
    """An unknown name is a programmer's error; passing it through would make the check a no-op."""
    with pytest.raises(AssertionError, match="no such tool"):
        args.check("warp_core", ref="0x0")


def test_a_tool_the_machine_judges_passes_through_without_a_verdict() -> None:
    """A `MACHINE_JUDGES` tool is asked nothing and answers nothing."""
    args.check("registers")
    args.check("declaration_list", kind="breakpoint")


def test_a_region_search_is_not_refused_for_the_length_it_is_not_given() -> None:
    """`find(region=...)` asks for a zero length: the class supplies its own range."""
    args.check("find", ref="", length=0, data_hex="00", symbol_class="DATA")


def test_the_one_hex_parser_accepts_what_it_always_accepted() -> None:
    """`bytes.fromhex` ignores ASCII whitespace, so a line pasted out of a dump is two bytes."""
    assert read.hex_bytes("data_hex", "de ad", verb="write") == b"\xde\xad"
    assert read.hex_bytes("data_hex", "dead", verb="write") == b"\xde\xad"
    args.check("write", ref="0x0", data_hex="de ad")
    args.check("find", ref="0x0", length=4, data_hex="de ad")


@pytest.mark.parametrize("value", ["", "abc", "zz", "de-ad"])
def test_the_one_hex_parser_refuses_what_is_not_hex(value: str) -> None:
    with pytest.raises(st.Invalid):
        read.hex_bytes("data_hex", value, verb="write")


@pytest.mark.parametrize(("dest", "expected"), [
    ("relative/x.png", "must be an absolute path or start with `~`"),
    (_abs("x\x00y.png"), "holds a NUL"),
])
def test_a_dest_is_judged_as_a_path_with_no_machine_in_sight(dest: str, expected: str) -> None:
    """The refusal comes from the table directly, with no session, and says why each fails."""
    with pytest.raises(st.Invalid) as caught:
        args.check("snapshot", dest=dest)
    assert expected in str(caught.value)


def test_a_dest_that_is_absolute_and_free_is_accepted() -> None:
    """Positive control: without it the rows above pass on a check that refuses every path."""
    fresh = pathlib.Path(tempfile.gettempdir()) / "mame-args-positive-control-never-written.png"
    assert not fresh.exists(), "the control needs a path that is not there yet"
    args.check("snapshot", dest=str(fresh))


def test_an_empty_dest_is_the_scratch_for_the_tools_that_allow_one() -> None:
    """`snapshot` and `record` name the file themselves; `memdump` has no such default."""
    args.check("snapshot", dest="")
    args.check("record", frames=2, dest="")
    with pytest.raises(st.Invalid):
        args.check("memdump", ref="0x4a0", length=16, dest="")


def test_no_refusal_sentence_is_written_at_more_than_one_site() -> None:
    """The same refusal sentence raised at two sites; it sees verbatim copies only."""
    import collections
    import re as _re
    seen: collections.defaultdict[str, set[str]] = collections.defaultdict(set)
    for path in sorted(pathlib.Path(args.__file__).parent.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", getattr(node.func, "id", ""))
                    in ("Invalid", "invalid")):
                continue
            parts = [sub.value for arg in node.args[1:] for sub in ast.walk(arg)
                     if isinstance(sub, ast.Constant) and isinstance(sub.value, str)]
            if not parts:
                continue
            key = " ".join(w for w in _re.sub(r"[^a-z ]+", " ", " ".join(parts).lower()).split()
                           if len(w) > 2)
            if len(key.split()) >= 3:
                seen[key].add(f"{path.name}:{node.lineno}")
    shared = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    assert not shared, (
        "these refusal sentences are written at more than one site:\n"
        + "\n".join(f"  {v}: {k[:70]}" for k, v in sorted(shared.items())))


def test_a_segmented_ref_is_refused_before_the_machine_and_stored_nowhere() -> None:
    """The map is flat, so `12345:0010` is refused cold; a name the machine may hold still waits."""
    st.STATE.ses = None
    calls: tuple[Callable[[], dict[str, Any]], ...] = (
                 lambda: s.breakpoint_at(ref="12345:0010"),
                 lambda: s.watch_add(ref="12345:0010", mode="show", length=2),
                 lambda: s.run_to(ref="12345:0010", control="0x25a4"),
                 lambda: s.read_memory(ref="12345:0010", length=4),
                 lambda: s.write(ref="12345:0010", data_hex="00"),
                 lambda: s.find(ref="12345:0010", length=4, data_hex="00"))
    for call in calls:
        got = call()
        assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
        assert "linear" in got["message"] and "12345:0010" in got["message"], got["message"]
    control = s.breakpoint_at(ref="no_such_symbol")
    assert control["code"] == "no_session", control


def test_the_instructions_say_a_wrong_type_is_the_schemas_refusal() -> None:
    """The SDK refuses a wrong type against the schema, and the instructions say so."""
    assert "wrong TYPE" in (s.mcp.instructions or ""), "the sentence is missing"


def test_the_instructions_close_with_the_in_development_notice() -> None:
    from scry_core.envelope import IN_DEVELOPMENT
    text = s.mcp.instructions or ""
    assert text.endswith("\n\n" + IN_DEVELOPMENT) and text.count(IN_DEVELOPMENT) == 1


# Case-insensitive: docstrings capitalise the word or not.
_CLAIMS_RUNNING = re.compile(r"(answers?|works|safe)[^.]{0,40}\brunning machine", re.IGNORECASE)


def test_every_tool_that_claims_it_answers_while_running_is_in_the_one_list() -> None:
    """A tool claiming to answer on a running machine must be in `RUNNING_OK_OPS`, or a sequence
    waits for a stop that never comes. The lifecycle tools are named, not filtered."""
    lifecycle = {"close", "start"}
    docs = {t.name: (getattr(s, t.name).__doc__ or "")
            for t in s.mcp._tool_manager.list_tools()}
    # A tool that also carries the needs-stopped sentence needs a stop by default
    # (`registers` answers running only with `from_last_stop=True`).
    claimed = {name for name, doc in docs.items()
               if _CLAIMS_RUNNING.search(doc) and mdocs.NEEDS_STOPPED not in doc} - lifecycle
    assert claimed, "no tool claims it at all, so this examined nothing and is not a verdict"
    missing = sorted(claimed - sequence.RUNNING_OK_OPS)
    assert not missing, (
        f"these tools tell a caller they answer on a running machine and are not in "
        f"RUNNING_OK_OPS, so a sequence refuses them: {missing}")
    unknown = sorted(sequence.RUNNING_OK_OPS - {t.name for t in s.mcp._tool_manager.list_tools()})
    assert not unknown, f"RUNNING_OK_OPS names tools this server does not register: {unknown}"


def test_the_instructions_families_are_the_registered_tools_and_the_running_ones_answer() -> None:
    """The roster names every registered tool once, and the instructions carry its running line."""
    registered = [t.name for t in strict.registered(s.mcp)]
    assert mame_mcp.ROSTER.unlisted(registered) == []
    assert mame_mcp.ROSTER.misfiled(roster.SHARED_FAMILIES) == []
    assert mame_mcp.ROSTER.running_sentence() in (s.mcp.instructions or "")
    named = mame_mcp.ROSTER.answering_named() - {"registers(from_last_stop=True)"}
    answering = (roster.by_method(sequence.RUNNING_OK_OPS, sequence.RUNNING_METHODS)
                 | (sequence.NOT_STEPS - {"start", "rom_check"}))
    assert set(media_tools.TOOLS) <= sequence.RUNNING_OK_OPS, "a file tool the gate refuses"
    assert named == answering, sorted(named ^ answering)


@pytest.mark.parametrize("addr", ["0xffff1", "0x10000000"])
def test_rom_check_refuses_an_address_outside_the_image_before_the_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, addr: str,
) -> None:
    """An address outside the image is refused in the envelope before the gate, like `start`."""
    monkeypatch.setattr(st.STATE, "ses", None)
    monkeypatch.setattr(st.STATE, "proc", None)
    image = tmp_path / "rom.bin"
    image.write_bytes(bytes(0x100000))
    got = s.rom_check(reference_rom=str(image), reference_addr=addr)
    assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
    assert "OUTSIDE" in got["message"], got["message"]
    # Control: the last sixteen bytes are inside the image, so the call reaches the gate.
    control = s.rom_check(reference_rom=str(image), reference_addr="0xffff0")
    assert control["code"] == "no_session", control


_START_OK = {"binary": _abs("b", "mame"), "rompath": _abs("r"),
             "reference_rom": _abs("r", "rom.bin")}


@pytest.mark.parametrize(("given", "name"), [
    ({"binary": "mame"}, "binary"),
    ({"reference_rom": "rom.bin"}, "reference_rom"),
    ({"rompath": "roms"}, "rompath"),
    ({"inipath": f"{_abs('a')};ini"}, r"inipath\[1\]"),
    ({"cfg": "x.cfg"}, "cfg"),
    ({"boot_lua": "print('x')"}, "boot_lua"),
    ({"symbols": {"maincpu": "a.map"}}, r"symbols\['maincpu'\]"),
    ({"types": "t.types"}, "types"),
    ({"state_dir": "states"}, "state_dir"),
    ({"boot_lua": _abs("x\0y")}, "boot_lua"),
])
def test_starts_machine_independent_half_judges_every_path_by_its_name(
        given: dict[str, Any], name: str) -> None:
    """Each path's shape is refused under its own name; whether a file exists is the host's."""
    with pytest.raises(st.Invalid, match=rf"^{name}="):
        launch.check_start(**{**_START_OK, **given})
    launch.check_start(**_START_OK, boot_lua=_abs("no", "such", "harness.lua"),
                       symbols={"a": _abs("no", "a.map")},
                       inipath=f"{_abs('no', 'ini')};{_abs('no', 'ini2')}",
                       cfg=_abs("no", "x.cfg"), state_dir=_abs("no", "states"),
                       types={"maincpu": _abs("no", "a.types"), "audiocpu": ""})
    launch.check_start(**_START_OK, types=_abs("no", "a.types"))


def test_starts_path_shapes_are_judged_in_the_order_judge_reads_them() -> None:
    """With two paths wrong, the one `judge` reads first is named."""
    with pytest.raises(st.Invalid, match=r"^binary="):
        launch.check_start(binary="mame", rompath=_abs("r"), reference_rom="rom.bin")
    with pytest.raises(st.Invalid, match=r"^reference_rom="):
        launch.check_start(binary=_abs("b", "mame"), rompath="roms", reference_rom="rom.bin")


def test_a_start_refused_for_the_shape_of_a_path_leaves_out_its_empty_start_retries() -> None:
    """A path-shape refusal happens before any launch, so `start_retries` is left out."""
    out = s.start(binary="mame", system="m68k", rompath=_abs("r"),
                  reference_rom=_abs("r", "rom.bin"))
    assert out["code"] == "bad_argument" and out["message"].startswith("binary="), out
    assert "start_retries" not in out, out


def test_the_instructions_tell_an_empty_diagnostic_from_a_field_not_sent() -> None:
    text = " ".join((s.mcp.instructions or "").split())
    assert "`omitted` names what was not sent" in text, text
