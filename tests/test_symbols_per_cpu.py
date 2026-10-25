"""A symbol table per cpu: `start` takes one path, the first cpu's table as it always
was, or a mapping `{cpu: path}`; `bases` and `types` follow its shape; the store keeps its key
when another cpu's table is added; and the fingerprint names the cpu for any but the first.

The machine's cpus are `-listxml`'s, CAPTURED from m68k-dual (`fixtures/machine/`).
"""

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server_support import _boot_args, _never_spawns, _stub_boot  # noqa: E402
from session_doubles import prints_file, refused, rewrite_mame  # noqa: E402

import mame_declarations as dec  # noqa: E402
import mame_state as mstate  # noqa: E402
import mame_symbols as syms  # noqa: E402
import server as s  # noqa: E402

M68K_DUAL = [":maincpu", ":subcpu"]
LISTXML = Path(__file__).parent / "fixtures" / "machine" / "listxml-m68k-dual.xml"


def _yaml(path: Path, *rows: tuple[str, int]) -> str:
    path.write_text("".join(f"- addr: 0x{a:x}\n  name: {n}\n" for n, a in rows))
    return str(path)


def _two_tables(tmp_path: Path) -> tuple[str, str]:
    """The main cpu's and the sub cpu's tables, one name in both (`irq_vblank`) at two
    addresses, as two programs would have it."""
    return (_yaml(tmp_path / "main.yaml", ("irq_vblank", 0x400), ("main_only", 0x500)),
            _yaml(tmp_path / "sub.yaml", ("irq_vblank", 0x542), ("sub_only", 0x600)))


def test_one_path_is_the_first_cpus_table_and_a_mapping_is_one_per_cpu(tmp_path: Path) -> None:
    main, sub = _two_tables(tmp_path)
    one = syms.load(main, None, "", [])
    assert list(one.tables) == [None], "one path names no cpu until the machine does"
    assert one.keyed(":maincpu")[":maincpu"].table["IRQ_VBLANK"] == 0x400
    both = syms.load({"maincpu": main, ":subcpu": sub}, None, "", M68K_DUAL)
    assert sorted(str(cpu) for cpu in both.tables) == M68K_DUAL, "either spelling is its tag"
    assert both.tables[":subcpu"].table["IRQ_VBLANK"] == 0x542
    assert both.path_of(":subcpu", ":maincpu") == Path(sub)
    assert one.path_of(":maincpu", ":maincpu") == Path(main)


def test_a_mapping_naming_a_cpu_the_machine_lacks_is_refused_naming_its_cpus(
    tmp_path: Path,
) -> None:
    main, _sub = _two_tables(tmp_path)
    with pytest.raises(mstate.Invalid) as e:
        syms.load({"soundcpu": main}, None, "", M68K_DUAL)
    assert e.value.code == "unknown_ref" and ":subcpu" in str(e.value)


@pytest.mark.parametrize(("symbols", "bases", "types", "said"), [
    ("MAIN", {"maincpu": {"DATA": "400"}}, "", "only beside a `symbols` mapping"),
    ("MAIN", None, {"maincpu": "TYPES"}, "only beside a `symbols` mapping"),
    ({"maincpu": "MAIN"}, {"DATA": "400"}, "", "one entry per cpu"),
    ({"maincpu": "MAIN"}, None, "TYPES", "one entry per cpu"),
    ({"maincpu": "MAIN"}, None, {"subcpu": "TYPES"}, "gives no table"),
])
def test_bases_and_types_follow_the_shape_of_symbols(
    tmp_path: Path, symbols: Any, bases: Any, types: Any, said: str,
) -> None:
    """A value in the other shape does not say which cpu's program it describes, so it is
    refused rather than applied to a guess."""
    main, _sub = _two_tables(tmp_path)
    typed = tmp_path / "t.types"
    typed.write_text("irq_vblank: u16\n")

    def fill(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        return {"MAIN": main, "TYPES": str(typed)}.get(v, v)

    with pytest.raises(mstate.Invalid, match=said):
        syms.load(fill(symbols), fill(bases), fill(types), M68K_DUAL)


def test_types_per_cpu_type_that_cpus_table(tmp_path: Path) -> None:
    main, sub = _two_tables(tmp_path)
    typed = tmp_path / "sub.types"
    typed.write_text("sub_only: u16\n")
    loaded = syms.load({"maincpu": main, "subcpu": sub}, None, {"subcpu": str(typed)},
                       M68K_DUAL)
    assert loaded.tables[":subcpu"].types == {"SUB_ONLY": "u16"}
    assert loaded.tables[":maincpu"].types == {}


def test_the_store_keeps_its_key_when_a_table_for_another_cpu_is_added(tmp_path: Path) -> None:
    """What was declared under one path is still there once the sub cpu's table is added: the
    key is the first cpu's file. A mapping that gives the first cpu none keys by the one it
    gives, named, so it is never mistaken for the first cpu's store."""
    main, sub = _two_tables(tmp_path)
    one = syms.store_key("m68k-dual", syms.load(main, None, "", []), M68K_DUAL)
    both = syms.store_key("m68k-dual", syms.load({"maincpu": main, "subcpu": sub}, None, "",
                                                M68K_DUAL), M68K_DUAL)
    assert one == both == dec.store_key("m68k-dual", main)
    only_sub = syms.store_key("m68k-dual", syms.load({"subcpu": sub}, None, "", M68K_DUAL),
                              M68K_DUAL)
    assert only_sub == f"{dec.store_key('m68k-dual', sub)} :subcpu"
    assert syms.store_key("m68k-dual", syms.load("", None, "", []), M68K_DUAL) is None


def test_a_fingerprint_names_the_cpu_for_any_but_the_first(tmp_path: Path) -> None:
    rom = tmp_path / "rom.bin"
    rom.write_bytes(bytes(16))
    main, _sub = _two_tables(tmp_path)
    first = syms.fingerprint("m68k-dual", rom, Path(main))
    assert first == syms.fingerprint("m68k-dual", rom, Path(main), None)
    assert first != syms.fingerprint("m68k-dual", rom, Path(main), ":subcpu")


def _m68k_dual_boot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """A start that boots nothing and answers `-listxml` with m68k-dual's captured document."""
    image = bytes(range(64))
    _stub_boot(monkeypatch, tmp_path, image, at=0)
    args = _boot_args(tmp_path, image)
    rewrite_mame(args["binary"], prints_file(LISTXML))
    return {**args, "system": "m68k-dual"}


def test_start_loads_a_table_per_cpu_and_answers_each_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    args = _m68k_dual_boot(monkeypatch, tmp_path)
    main, sub = _two_tables(tmp_path)
    out = s.start(**args, symbols={"maincpu": main, "subcpu": sub})
    try:
        assert out["status"] == "ok", out
        assert mstate.STATE.first_cpu == ":maincpu"
        assert mstate.STATE.table(":subcpu").table["IRQ_VBLANK"] == 0x542
        assert mstate.STATE.table().table["IRQ_VBLANK"] == 0x400, "no cpu: the first's"
        assert out["symbols_total"] == 2 and out["symbols_by_cpu"] == {":maincpu": 2, ":subcpu": 2}
        assert out["declarations"]["key"] == dec.store_key("m68k-dual", main)
    finally:
        s.close()


def test_start_with_one_path_gives_it_to_the_first_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    args = _m68k_dual_boot(monkeypatch, tmp_path)
    main, _sub = _two_tables(tmp_path)
    out = s.start(**args, symbols=main)
    try:
        assert out["symbols_by_cpu"] == {":maincpu": 2}
        assert mstate.STATE.table(":subcpu").table == {}, "another cpu has no table"
    finally:
        s.close()


def test_a_mapping_naming_a_cpu_the_machine_lacks_spawns_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    args = _m68k_dual_boot(monkeypatch, tmp_path)
    main, _sub = _two_tables(tmp_path)
    _never_spawns_but_listxml(monkeypatch, tmp_path)
    refused("no cpu 'soundcpu'", s.start(**args, symbols={"soundcpu": main}))


def _never_spawns_but_listxml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`_never_spawns`, letting the one query a mapping waits for run."""
    import subprocess
    real = subprocess.Popen
    _never_spawns(monkeypatch, tmp_path)
    boom = subprocess.Popen

    def popen(*a: Any, **k: Any) -> Any:
        argv = a[0] if a else k["args"]
        return real(*a, **k) if "-listxml" in argv else boom(*a, **k)

    monkeypatch.setattr(subprocess, "Popen", popen)


def test_a_mapping_naming_one_cpu_twice_is_refused(tmp_path: Path) -> None:
    main, _sub = _two_tables(tmp_path)
    with pytest.raises(mstate.Invalid, match="names one cpu twice"):
        syms.load({"maincpu": main, ":maincpu": main}, None, "", M68K_DUAL)


def test_a_mapping_is_refused_when_the_machine_lists_no_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A mapping names cpus, and a `-listxml` that answers none leaves nothing to judge them
    against: refused, and nothing spawned."""
    image = bytes(range(64))
    args = _boot_args(tmp_path, image)            # a MAME that answers no XML at all
    main, _sub = _two_tables(tmp_path)
    _never_spawns_but_listxml(monkeypatch, tmp_path)
    refused("could not be read", s.start(**args, symbols={"maincpu": main}))
