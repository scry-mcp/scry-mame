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


def test_the_index_is_what_the_tool_writes_from_the_lines_it_quotes(tmp_path: Path) -> None:
    t = tool()
    made = t.build(tree(tmp_path))
    assert made == json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert [len(v) for v in made["lists"].values()] == [34, 5, 7]


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
    mame, index = tree(tmp_path / "mame"), tmp_path / "out" / "sources.json"
    assert t.main(["--mame", str(mame), "--index", str(index)]) == 0
    assert t.main(["--mame", str(mame), "--index", str(index), "--check"]) == 0
    doc = json.loads(index.read_text(encoding="utf-8"))
    doc["rows"].popitem()
    index.write_text(json.dumps(doc), encoding="utf-8")
    assert t.main(["--mame", str(mame), "--index", str(index), "--check"]) == 1
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
    mame, index = tree(tmp_path / "mame"), tmp_path / "sources.json"
    damage(mame, t)  # type: ignore[operator]
    assert t.main(["--mame", str(mame), "--index", str(index)]) == 3
    assert said in capsys.readouterr().err and not index.exists()


def test_an_unknown_option_exits_non_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert tool().main(["--no-such-option"]) == 2
    assert tool().main(["--help"]) == 0
    capsys.readouterr()
