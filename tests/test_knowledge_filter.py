"""What this server serves of its base: only entries a second check confirmed, which today are the
shared chips' and cpus'. Its own dictionaries have no second check, so every one is held back."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from scry_core import knowledge_tool
from scry_core.knowledge import KINDS, Base, shared

from scry_mame import naming
from scry_mame import server as s
from scry_mame.knowledge import support


def test_the_base_serves_the_shared_confirmed_entries_and_none_of_its_own() -> None:
    served = naming.base()
    own = {e.id for e in Base.load("scry_mame").entries()}
    assert own, "this server's dictionaries were not read"
    assert not own & {e.id for e in served.entries()}
    assert len(served) > 0
    assert served.held_back >= len(own)


def test_what_is_served_is_exactly_what_the_shared_confirmation_confirms() -> None:
    whole = support.load().unfiltered()
    sure = shared.confirmation()
    expected = {e.id for e in whole.entries() if sure.confirms(e)}
    assert {e.id for e in naming.base().entries()} == expected


def test_knowledge_find_on_a_held_back_key_says_it_exists_and_is_not_confirmed() -> None:
    reply = s.knowledge_find(kind="vector", key="2", scope="m68000")
    assert reply["entries"] == [] and reply["unconfirmed"] == ["m68000:vector:2"]
    assert "not confirmed" in reply["note"] and "no entry known" not in reply["summary"]
    assert (reply["served"], reply["held_back"]) == (len(naming.base()), naming.base().held_back)


def test_knowledge_find_on_a_confirmed_key_serves_it_and_counts_what_is_held_back() -> None:
    reply = s.knowledge_find(kind="vector", key="0x66", scope="z80")
    assert [e["id"] for e in reply["entries"]] == ["z80:vector:0x66"]
    assert "unconfirmed" not in reply and reply["held_back"] > 0


def test_status_with_no_session_carries_the_two_counts() -> None:
    assert s.status()["knowledge"] == knowledge_tool.counts(naming.base())


#: An entry's id as a document writes it: scope, kind, key.
ENTRY_ID = re.compile(rf"(?<![\w:])\w+:(?:{'|'.join(KINDS)}):[^\s`\"'<>),;]+")
ROOT = Path(__file__).resolve().parent.parent


def cited_ids() -> dict[str, set[str]]:
    """The entry ids the reference's examples, sentences and pages, the tour and the demos cite,
    by the file that cites them."""
    files = [p for pattern in ("docs/reference/**/*", "demos/**/*.md", "demos/**/*.py")
             for p in ROOT.glob(pattern)
             if p.is_file() and p.suffix in {".md", ".json", ".py"}]
    found = {p.relative_to(ROOT).as_posix(): set(ENTRY_ID.findall(p.read_text(encoding="utf-8")))
             for p in files}
    return {name: ids for name, ids in found.items() if ids}


def test_the_tour_and_the_reference_cite_confirmed_entries_only() -> None:
    cited = cited_ids()
    assert cited, "no document cites an entry: the scan examined nothing"
    held = {f"{name}: {i}" for name, ids in cited.items() for i in ids
            if naming.base().by_id(i) is None}
    assert not held, "\n".join(sorted(held))


def test_a_document_citing_a_held_back_entry_is_caught(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    page = tmp_path / "docs" / "reference" / "x.md"
    page.parent.mkdir(parents=True)
    page.write_text("`m68000:vector:2` and `z80:vector:0x66`", encoding="utf-8")
    assert cited_ids() == {"docs/reference/x.md": {"m68000:vector:2", "z80:vector:0x66"}}
    assert [i for i in cited_ids()["docs/reference/x.md"]
            if naming.base().by_id(i) is None] == ["m68000:vector:2"]
