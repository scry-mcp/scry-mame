"""What this server serves of its base: the entries of its dictionaries of rows, and the shared
ones, that the locks seal in every part; the rest exists, is held back and stays a number."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from scry_core import demo, knowledge_tool, reference
from scry_core.knowledge import KINDS, sealed
from scry_core.knowledge.base import Base, dictionaries

from scry_mame import naming
from scry_mame import server as s
from scry_mame.knowledge import support

ROOT = Path(__file__).resolve().parent.parent


def _standing() -> dict[str, str]:
    lock = support.rows_lock()
    return {e.id: lock.standing(d, e) for source in support.SOURCES
            for _, d, _ in dictionaries(source) if d is not None for e in d.entries}


def test_the_base_serves_exactly_the_entries_the_locks_seal() -> None:
    standing = _standing()
    assert standing, "no dictionary of rows was read"
    served = {e.id for e in naming.base().entries()}
    assert served == {i for i, held in standing.items() if held == sealed.SERVED}
    assert naming.base().held_back == len(standing) - len(served)


def _part(seal: str) -> sealed.Part:
    return sealed.Part(seal, "a reader", "a writer", {})


def test_two_locks_merge_part_by_part() -> None:
    a = sealed.Lock({"x:device:x": {"doc": _part("1")}})
    b = sealed.Lock({"x:device:x": {"mame": _part("2")}, "y:device:y": {"doc": _part("3")}})
    got = support.merged(a, b)
    assert {i: sorted(p) for i, p in got.sealed.items()} == {"x:device:x": ["doc", "mame"],
                                                              "y:device:y": ["doc"]}


def test_a_part_two_locks_seal_is_refused_by_name() -> None:
    a = sealed.Lock({"x:device:x": {"doc": _part("1")}})
    with pytest.raises(ValueError, match="x:device:x: the part doc is sealed in two locks"):
        support.merged(a, sealed.Lock({"x:device:x": {"doc": _part("1")}}))


def test_knowledge_find_on_an_entry_held_back_says_it_exists_and_is_not_served() -> None:
    held = sorted(i for i, why in _standing().items() if why != sealed.SERVED)
    if not held:
        pytest.skip("every entry is sealed: none is held back to ask for")
    reply = s.knowledge_find(id=held[0])
    assert reply["entries"] == [] and reply["unconfirmed"] == [held[0]]
    assert "not confirmed" in reply["note"]
    assert (reply["served"], reply["held_back"]) == (len(naming.base()), naming.base().held_back)


def test_status_with_no_session_carries_the_two_counts() -> None:
    assert s.status()["knowledge"] == knowledge_tool.counts(naming.base())


#: An entry's id as a document writes it: scope, kind, key, and `#n` for one of its rows.
ENTRY_ID = re.compile(rf"(?<![\w:])\w+:(?:{'|'.join(KINDS)}):[^\s`\"'<>),;#]+")


def cited_ids() -> dict[str, set[str]]:
    """The entry ids the reference's examples, sentences and pages, the tour and the demos cite,
    by the file that cites them."""
    files = [p for pattern in ("docs/reference/**/*", "demos/**/*.md", "demos/**/*.py")
             for p in ROOT.glob(pattern)
             if p.is_file() and p.suffix in {".md", ".json", ".py"}]
    found = {p.relative_to(ROOT).as_posix(): set(ENTRY_ID.findall(p.read_text(encoding="utf-8")))
             for p in files}
    return {name: ids for name, ids in found.items() if ids}


def _unheld(ids: set[str]) -> set[str]:
    whole = Base(support.SOURCES, None)
    return {i for i in ids if whole.by_id(i) is None}


def test_the_tour_and_the_reference_cite_entries_the_dictionaries_hold() -> None:
    cited = cited_ids()
    assert cited, "no document cites an entry: the scan examined nothing"
    missing = {f"{name}: {i}" for name, ids in cited.items() for i in _unheld(ids)}
    assert not missing, "\n".join(sorted(missing))


def test_a_document_citing_an_entry_no_dictionary_holds_is_caught(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    page = tmp_path / "docs" / "reference" / "x.md"
    page.parent.mkdir(parents=True)
    page.write_text("`ay8910:register:0x07#1` and `ay8910:register:0x99`", encoding="utf-8")
    assert cited_ids() == {"docs/reference/x.md": {"ay8910:register:0x07",
                                                   "ay8910:register:0x99"}}
    assert _unheld(cited_ids()["docs/reference/x.md"]) == {"ay8910:register:0x99"}


def test_the_reference_example_is_the_server_s_reply_over_its_dictionaries() -> None:
    """`tests/knowledge_example.py` answers the ask in a process of its own; the committed
    example is that reply as `scry_core.reference` spells it."""
    run = subprocess.run([sys.executable, str(ROOT / "tests" / "knowledge_example.py")],
                         capture_output=True, text=True, check=False, cwd=ROOT)
    assert run.returncode == 0, run.stderr
    picked = reference.examples_from([json.loads(run.stdout)], {"knowledge_find"},
                                     demo.Normaliser(ROOT, Path.home().resolve(), {}, marks={
                                         str(ROOT): demo.placeholder(ROOT)}))
    committed = json.loads((ROOT / "docs/reference/examples.json").read_text(encoding="utf-8"))
    assert picked["knowledge_find"]["reply"]["entries"][0]["rows"], "the example has no rows"
    assert committed["knowledge_find"] == picked["knowledge_find"]
