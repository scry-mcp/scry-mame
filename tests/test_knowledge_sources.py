"""`tools/knowledge_sources.py` writes the index the vector dictionaries are held to, and says
INVALID rather than write one it could not prove."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMMITTED = ROOT / "src" / "scry_mame" / "knowledge_index" / "sources.json"


def tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("knowledge_sources",
                                                  ROOT / "tools" / "knowledge_sources.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tree(base: Path) -> Path:
    """MAME's files as the rules read them: each holds the lines the committed index quotes, and
    `m68000.cpp` the seven autovector answers."""
    t = tool()
    rows = json.loads(COMMITTED.read_text(encoding="utf-8"))["rows"]
    held: dict[str, list[str]] = {}
    for rule in t.RULES:
        held.setdefault(rule.file(), []).append(rows[rule.ref]["line"])
    held[f"{t.M68K}m68000.cpp"] = [f"\t\tmap(a, b).lr8(NAME([] () -> u8 {{ return autovector({n}); "
                                   "}));" for n in range(1, 8)]
    for file, lines in held.items():
        (base / file).parent.mkdir(parents=True, exist_ok=True)
        (base / file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return base


CHIP_FILE = "src/devices/sound/x.cpp"
CHIP_SOURCE = """void x_device::write(uint8_t data)
{
\tswitch (data)
\t{
\tcase 0x01: a(); break;
\tcase 0x02: b(); break;
\t}
}
DEFINE_DEVICE_TYPE(X, x_device, "x", "X chip")
"""
CHIP_SPEC: dict[str, object] = {
    "rows": [
        {"ref": f"mame:{CHIP_FILE} x_device::write case 0x01", "find": "case 0x01",
         "inside": "x_device::write", "key": "0x01"},
        {"ref": f"mame:{CHIP_FILE} x_device::write case 0x02", "find": "case 0x02",
         "inside": "x_device::write", "key": "0x02"},
    ],
    "lists": [
        {"ref": f"mame:{CHIP_FILE} x_device::write", "keys": ["0x01", "0x02"],
         "cases": {"file": CHIP_FILE, "inside": "x_device::write"}},
        {"ref": f"mame:{CHIP_FILE} DEFINE_DEVICE_TYPE", "device_types": CHIP_FILE},
    ],
}


def chip_tree(mame: Path) -> Path:
    (mame / CHIP_FILE).parent.mkdir(parents=True, exist_ok=True)
    (mame / CHIP_FILE).write_text(CHIP_SOURCE, encoding="utf-8")
    return mame


def specs(base: Path, spec: dict[str, object] | None = None) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "x.json").write_text(json.dumps(CHIP_SPEC if spec is None else spec),
                                 encoding="utf-8")
    return base


def test_the_index_is_what_the_tool_writes_from_the_lines_it_quotes(tmp_path: Path) -> None:
    t = tool()
    made = t.build(tree(tmp_path), None)
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    vector_lists = (t.LIST_M68000, t.LIST_V30, t.LIST_M6809)
    assert made == {**committed, "rows": {r: committed["rows"][r] for r in made["rows"]},
                    "lists": {k: committed["lists"][k] for k in vector_lists}}
    assert len(made["rows"]) == len(t.RULES)
    assert [len(v) for v in made["lists"].values()] == [34, 5, 7]


def test_a_chip_spec_gives_its_rows_and_lists_and_nothing_else(tmp_path: Path) -> None:
    t = tool()
    mame = chip_tree(tree(tmp_path / "mame"))
    made = t.build(mame, specs(tmp_path / "specs"))
    ref = f"mame:{CHIP_FILE} x_device::write"
    assert made["rows"][f"{ref} case 0x02"] == {"line": "\tcase 0x02: b(); break;", "key": "0x02"}
    assert made["lists"][ref] == ["0x01", "0x02"]
    assert made["lists"][f"mame:{CHIP_FILE} DEFINE_DEVICE_TYPE"] == ["x"]
    assert len(made["rows"]) == len(t.RULES) + 2


def _no_row(spec: dict[str, object]) -> None:
    spec["rows"] = spec["rows"][:1]  # type: ignore[index]


def _case_uncovered(spec: dict[str, object]) -> None:
    spec["lists"][0]["keys"] = ["0x01"]  # type: ignore[index]


def _find_matches_none(spec: dict[str, object]) -> None:
    spec["rows"][0]["find"] = "case 0x09"  # type: ignore[index]


def _find_matches_two(spec: dict[str, object]) -> None:
    spec["rows"][0]["find"] = "case 0x0"  # type: ignore[index]


def _row_twice(spec: dict[str, object]) -> None:
    spec["rows"].append(spec["rows"][0])  # type: ignore[attr-defined, index]


def _no_keys(spec: dict[str, object]) -> None:
    spec["lists"][0]["keys"] = []  # type: ignore[index]


def _unknown_row(spec: dict[str, object]) -> None:
    spec["rows"][0]["insde"] = "x"  # type: ignore[index]


def _unknown_list(spec: dict[str, object]) -> None:
    spec["lists"][0]["case"] = {}  # type: ignore[index]


def _unknown_cases(spec: dict[str, object]) -> None:
    spec["lists"][0]["cases"]["symbols"] = {}  # type: ignore[index]


def _unknown_top(spec: dict[str, object]) -> None:
    spec["row"] = []


def _which_without_of(spec: dict[str, object]) -> None:
    spec["rows"][0].update(find="case 0x0", which=0)  # type: ignore[index]


def _which_of_wrong(spec: dict[str, object]) -> None:
    spec["rows"][0].update(find="case 0x0", which=0, of=3)  # type: ignore[index]


@pytest.mark.parametrize(("damage", "said"), [
    (_no_row, "is the key of no row"),
    (_case_uncovered, "lies inside no key"),
    (_find_matches_none, "matches 0 lines"),
    (_find_matches_two, "matches 2 lines"),
    (_row_twice, "is a row twice"),
    (_no_keys, "examined nothing"),
    (_unknown_row, "unknown key insde"),
    (_unknown_list, "unknown key case"),
    (_unknown_cases, "unknown key symbols"),
    (_unknown_top, "unknown key row"),
    (_which_without_of, "needs exactly `of` matches"),
    (_which_of_wrong, "needs exactly `of` matches"),
])
def test_a_chip_spec_that_proves_nothing_is_invalid(tmp_path: Path, damage: object,
                                                    said: str) -> None:
    t = tool()
    mame = chip_tree(tree(tmp_path / "mame"))
    spec = json.loads(json.dumps(CHIP_SPEC))
    damage(spec)  # type: ignore[operator]
    with pytest.raises(t.Invalid, match=said):
        t.build(mame, specs(tmp_path / "specs", spec))


NAMED_SOURCE = """enum
{
\tPORT_A = 0,
\tPORT_B,
\tCONTROL
};
void y_device::write(uint8_t offset)
{
\tswitch (offset)
\t{
\tcase PORT_A: a(); break;
\tcase PORT_B: case CONTROL: b();
\t\tswitch (mode)
\t\t{
\t\tcase MODE_1: break;
\t\t}
\t\tbreak;
\t}
}
"""


def _named_spec(keys: list[str], enums: bool = True) -> dict[str, object]:
    cases: dict[str, object] = {"file": CHIP_FILE, "inside": "y_device::write"}
    if enums:
        cases["enums"] = [{"file": CHIP_FILE, "after": r"^\tPORT_A = 0,$"}]
    return {
        "rows": [{"ref": f"mame:{CHIP_FILE} y {k}", "find": "case PORT_A", "key": k}
                 for k in keys[:1]]
        + [{"ref": f"mame:{CHIP_FILE} y {k}", "find": "case PORT_B", "key": k}
           for k in keys[1:]],
        "lists": [{"ref": f"mame:{CHIP_FILE} y_device::write", "keys": keys, "cases": cases}],
    }


def _built(t: ModuleType, tmp_path: Path, source: str, spec: dict[str, object]) -> object:
    mame = chip_tree(tree(tmp_path / "mame"))
    (mame / CHIP_FILE).write_text(source, encoding="utf-8")
    return t.build(mame, specs(tmp_path / "specs", spec))


def test_a_label_that_is_a_name_takes_its_number_from_the_enum_and_a_nested_switch_is_apart(
        tmp_path: Path) -> None:
    made = _built(tool(), tmp_path, NAMED_SOURCE, _named_spec(["0x00", "0x01..0x02"]))
    listed = made["lists"]  # type: ignore[index]
    assert listed[f"mame:{CHIP_FILE} y_device::write"] == ["0x00", "0x01..0x02"]


@pytest.mark.parametrize(("keys", "enums", "said"), [
    (["0x00", "0x01"], True, "`case CONTROL` of y_device::write lies inside no key"),
    (["0x00", "0x01..0x02"], False, "a name no enum"),
    (["0x00", "0x02..0x01"], True, "no upward range"),
])
def test_a_named_label_with_no_number_or_no_key_is_invalid(
        tmp_path: Path, keys: list[str], enums: bool, said: str) -> None:
    t = tool()
    with pytest.raises(t.Invalid, match=said):
        _built(t, tmp_path, NAMED_SOURCE, _named_spec(keys, enums))


def test_which_picks_one_of_exactly_of_the_matches(tmp_path: Path) -> None:
    spec = json.loads(json.dumps(CHIP_SPEC))
    spec["rows"][1].update(find="case 0x0", which=1, of=2)
    made = _built(tool(), tmp_path, CHIP_SOURCE, spec)
    rows = made["rows"]  # type: ignore[index]
    assert rows[f"mame:{CHIP_FILE} x_device::write case 0x02"]["line"] == "\tcase 0x02: b(); break;"


@pytest.mark.parametrize(("source", "region", "said"), [
    (CHIP_SOURCE + CHIP_SOURCE, {"inside": "x_device::write"}, "is defined 2 times"),
    ("void x_device::write(uint8_t data)\n{\n\tcase 0x01: a();\n", {"inside": "x_device::write"},
     "no closing"),
    (CHIP_SOURCE, {"inside": "x_device::write", "after": "case 0x0"}, "matches 2 lines"),
    (CHIP_SOURCE, {"inside": "x_device::write", "after": "case 0x01", "until": "nothing here"},
     "nothing matches"),
])
def test_a_region_that_is_not_one_function_is_invalid(
        tmp_path: Path, source: str, region: dict[str, str], said: str) -> None:
    t = tool()
    spec = json.loads(json.dumps(CHIP_SPEC))
    spec["rows"][0].update(region)
    mame = tree(tmp_path / "mame")
    (mame / CHIP_FILE).parent.mkdir(parents=True, exist_ok=True)
    (mame / CHIP_FILE).write_text(source, encoding="utf-8")
    with pytest.raises(t.Invalid, match=said):
        t.build(mame, specs(tmp_path / "specs", spec))


def test_a_file_with_no_device_type_line_is_invalid(tmp_path: Path) -> None:
    t = tool()
    spec: dict[str, object] = {
        "rows": [{"ref": f"mame:{CHIP_FILE} x", "find": "nothing", "key": "x"}],
            "lists": [{"ref": "mame:x device types", "device_types": CHIP_FILE}]}
    mame = tree(tmp_path / "mame")
    (mame / CHIP_FILE).parent.mkdir(parents=True, exist_ok=True)
    (mame / CHIP_FILE).write_text("nothing\n", encoding="utf-8")
    with pytest.raises(t.Invalid, match="holds no DEFINE_DEVICE_TYPE"):
        t.build(mame, specs(tmp_path / "specs", spec))


@pytest.mark.parametrize(("text", "said"), [
    ('{"rows": [{"ref": "mame:%s x"}]}', "KeyError"),
    ('{"rows": [{"ref": "mame:%s x", "find": "("}]}', "missing )"),
    ("not json", "JSONDecodeError"),
])
def test_a_malformed_spec_exits_three_and_writes_nothing(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, said: str) -> None:
    t = tool()
    mame, index = chip_tree(tree(tmp_path / "mame")), tmp_path / "sources.json"
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "x.json").write_text(text.replace("%s", CHIP_FILE), encoding="utf-8")
    given = ["--mame", str(mame), "--index", str(index), "--specs", str(tmp_path / "s")]
    assert t.main(given) == 3 and t.main([*given, "--check"]) == 3
    assert said in capsys.readouterr().err and not index.exists()


def test_a_row_may_carry_marks_and_no_key_and_a_list_may_have_no_cases(tmp_path: Path) -> None:
    spec: dict[str, object] = {
        "rows": [{"ref": f"mame:{CHIP_FILE} x a", "find": "case 0x01", "marks": "RW"},
                 {"ref": f"mame:{CHIP_FILE} x b", "find": "case 0x02", "key": "0x02"}],
        "lists": [{"ref": f"mame:{CHIP_FILE} x list", "keys": ["0x02"]}]}
    made = _built(tool(), tmp_path, CHIP_SOURCE, spec)
    rows = made["rows"]  # type: ignore[index]
    assert rows[f"mame:{CHIP_FILE} x a"] == {"line": "\tcase 0x01: a(); break;", "marks": "RW"}
    assert made["lists"][f"mame:{CHIP_FILE} x list"] == ["0x02"]  # type: ignore[index]


def test_an_enum_with_blank_and_comment_lines_still_numbers_its_names(tmp_path: Path) -> None:
    source = NAMED_SOURCE.replace("\tPORT_B,", "\n\t// the second\n\tPORT_B,")
    made = _built(tool(), tmp_path, source, _named_spec(["0x00", "0x01..0x02"]))
    assert made["lists"]  # type: ignore[index]


def _enum_after_twice(spec: dict[str, object]) -> None:
    spec["lists"][0]["cases"]["enums"][0]["after"] = "PORT"  # type: ignore[index]


def _enum_unreadable(spec: dict[str, object]) -> None:
    spec["lists"][0]["cases"]["enums"][0]["after"] = r"^\tPORT_A = 0,$"  # type: ignore[index]


def _cases_not_an_object(spec: dict[str, object]) -> None:
    spec["lists"][0]["cases"] = "x_device::write"  # type: ignore[index]


def _no_case_in_function(spec: dict[str, object]) -> None:
    spec["lists"][0]["cases"]["inside"] = "y_device::other"  # type: ignore[index]


def _list_twice(spec: dict[str, object]) -> None:
    spec["lists"].append(spec["lists"][0])  # type: ignore[attr-defined, index]


@pytest.mark.parametrize(("damage", "said"), [
    (_enum_after_twice, "matches 4 lines, not the one of an enum"),
    (_enum_unreadable, "an enumerator this tool cannot read"),
    (_cases_not_an_object, "is an object"),
    (_no_case_in_function, "no `case` label"),
    (_list_twice, "is a list twice"),
])
def test_a_spec_whose_enum_or_cases_cannot_be_read_is_invalid(
        tmp_path: Path, damage: object, said: str) -> None:
    t = tool()
    spec = _named_spec(["0x00", "0x01..0x02"])
    damage(spec)  # type: ignore[operator]
    port_b = "\tPORT_B = 1 + 0," if "enumerator" in said else "\tPORT_B,"
    source = NAMED_SOURCE.replace("\tPORT_B,", port_b)
    source += "void y_device::other()\n{\n\tfoo();\n}\n"
    with pytest.raises(t.Invalid, match=said):
        _built(t, tmp_path, source, spec)


def test_a_chip_spec_may_not_name_a_row_of_the_vector_rules(tmp_path: Path) -> None:
    t = tool()
    mame = chip_tree(tree(tmp_path / "mame"))
    rule = t.RULES[0]
    spec: dict[str, object] = {"rows": [*CHIP_SPEC["rows"],  # type: ignore[misc]
                                {"ref": rule.ref, "find": rule.find, "key": rule.key}],
                               "lists": CHIP_SPEC["lists"]}
    with pytest.raises(t.Invalid, match="names a row or a list of the vector rules"):
        t.build(mame, specs(tmp_path / "specs", spec))


def test_no_chip_spec_at_all_is_invalid(tmp_path: Path) -> None:
    t = tool()
    with pytest.raises(t.Invalid, match="would examine nothing"):
        t.build(tree(tmp_path / "mame"), tmp_path / "empty")


def test_a_state_the_source_names_and_no_rule_covers_is_invalid(tmp_path: Path) -> None:
    t = tool()
    mame = tree(tmp_path)
    gen = mame / t.M68K / "m68000gen.py"
    gen.write_text(gen.read_text() + '    [0x1c0, "extra", 12, False],\n', encoding="utf-8")
    with pytest.raises(t.Invalid, match="write a rule for each"):
        t.build(mame)


def test_main_writes_then_finds_its_own_index_equal_and_a_changed_one_different(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    t = tool()
    mame, index = chip_tree(tree(tmp_path / "mame")), tmp_path / "out" / "sources.json"
    given = ["--mame", str(mame), "--index", str(index), "--specs", str(specs(tmp_path / "s"))]
    assert t.main(given) == 0
    assert t.main([*given, "--check"]) == 0
    doc = json.loads(index.read_text(encoding="utf-8"))
    doc["rows"].popitem()
    index.write_text(json.dumps(doc), encoding="utf-8")
    assert t.main([*given, "--check"]) == 1
    assert "differs" in capsys.readouterr().out


@pytest.mark.parametrize(("damage", "said"), [
    (lambda m, t: (m / t.NEC / "necpriv.ipp").unlink(), "is not a file"),
    (lambda m, t: (m / t.M6809 / "m6809.h").write_text("nothing\n"), "matches 0 lines"),
    (lambda m, t: (m / t.NEC / "necpriv.ipp").write_text(
        (m / t.NEC / "necpriv.ipp").read_text() + "\tNEC_TRAP_VECTOR = 1,\n"), "matches 2 lines"),
    (lambda m, t: (m / t.M68K / "m68000.cpp").write_text("return autovector(1);\n"),
     "not 1 to 7"),
])
def test_a_source_that_cannot_be_read_or_matched_is_invalid_and_writes_nothing(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], damage: object, said: str) -> None:
    t = tool()
    mame, index = chip_tree(tree(tmp_path / "mame")), tmp_path / "sources.json"
    damage(mame, t)  # type: ignore[operator]
    given = ["--mame", str(mame), "--index", str(index), "--specs", str(specs(tmp_path / "s"))]
    assert t.main(given) == 3
    assert said in capsys.readouterr().err and not index.exists()


def test_an_unknown_option_exits_non_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert tool().main(["--no-such-option"]) == 2
    assert tool().main(["--help"]) == 0
    capsys.readouterr()
