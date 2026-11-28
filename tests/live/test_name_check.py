"""The name check bites in both directions: a name the base holds passes, one it does not fails.

The cases run on the server's own base, so they need no emulator.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import name_check
import pytest
from scry_core import abbreviation

from scry_mame import naming

#: A vector the base holds: the 68000's vector 2, `bus error`, at its slot 0x8.
VECTOR = "m68000:vector:2"


def transcript(directory: Path, reply: Mapping[str, object]) -> Path:
    """A directory holding one reply as a demo leaves it: a `json` block of `transcript.md`."""
    (directory / "transcript.md").write_text(
        "```json\n" + json.dumps(reply) + "\n```\n", encoding="utf-8")
    return directory


def named(name: str, ident: str | None = VECTOR) -> dict[str, object]:
    item: dict[str, object] = {"field": "given.ref", "number": "0x8", "kind": "vector",
                               "name": name}
    if ident is not None:
        item["id"] = ident
    return {"status": "ok", "names": [item]}


def test_a_name_the_base_holds_passes(tmp_path: Path) -> None:
    found = name_check.check(naming.base(), transcript(tmp_path, named("bus error")))
    assert found.findings == []
    assert (found.replies, found.names) == (1, 1)


def test_a_name_the_base_states_otherwise_fails(tmp_path: Path) -> None:
    found = name_check.check(naming.base(), transcript(tmp_path, named("bus fault")))
    assert [str(finding) for finding in found.findings] == [
        f"transcript.md block 1: `bus fault` ({VECTOR}): the base calls it `bus error`"]


def test_a_name_the_base_does_not_hold_fails(tmp_path: Path) -> None:
    reply = named("bus error", "m68000:vector:99")
    found = name_check.check(naming.base(), transcript(tmp_path, reply))
    assert [finding.why for finding in found.findings] == [
        "the base holds no entry with that id"]


def test_a_name_with_no_id_fails(tmp_path: Path) -> None:
    found = name_check.check(naming.base(), transcript(tmp_path, named("bus error", None)))
    assert [finding.why for finding in found.findings] == [
        "the reply names a base entry with no id"]


def test_a_name_that_is_not_a_string_is_not_held(tmp_path: Path) -> None:
    reply = {"status": "ok", "names": [
        {"field": "given.ref", "number": "0x8", "kind": "vector", "id": VECTOR, "name": None}]}
    assert name_check.check(naming.base(), transcript(tmp_path, reply)).findings == []


def test_a_reply_inside_a_list_is_walked(tmp_path: Path) -> None:
    found = name_check.check(naming.base(), transcript(tmp_path, {"status": "ok",
                                                                 "ran": [named("bus error")]}))
    assert (found.replies, found.names) == (2, 1)


def test_a_jsonl_transcript_is_read_line_by_line(tmp_path: Path) -> None:
    (tmp_path / "calls.jsonl").write_text(
        "\n".join(json.dumps(named("bus error")) for _ in range(2)) + "\n", encoding="utf-8")
    found = name_check.check(naming.base(), tmp_path)
    assert (found.replies, found.names) == (2, 2)


def test_a_block_that_is_no_reply_and_an_unclosed_fence_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "transcript.md").write_text(
        "```json\n[1, 2]\n```\n```json\nnot json\n```\n"
        "```json\n" + json.dumps(named("bus error")) + "\n```\n"
        '```json\n{"status": "ok"', encoding="utf-8")
    found = name_check.check(naming.base(), tmp_path)
    assert (found.replies, found.names) == (1, 1)


def test_the_program_s_own_names_are_not_the_base_s(tmp_path: Path) -> None:
    reply = {"status": "ok", "names": [
        {"field": "addr", "number": "0x0", "kind": "symbol", "name": "start"},
        {"field": "addr", "number": "0x0", "kind": "memory", "name": "spriteram"}]}
    found = name_check.check(naming.base(), transcript(tmp_path, reply))
    assert found.findings == []
    assert (found.names, found.symbols) == (0, 2)


def test_a_line_note_that_matches_its_entry_passes(tmp_path: Path) -> None:
    reply = {"status": "ok", "instruction": {"note": "bus error (0x08)"}}
    found = name_check.check(naming.base(), transcript(tmp_path, reply))
    assert found.findings == []
    assert found.names == 1


def test_a_line_note_of_another_name_fails(tmp_path: Path) -> None:
    reply = {"status": "ok", "instruction": {"note": "bus fault (0x08)"}}
    found = name_check.check(naming.base(), transcript(tmp_path, reply))
    assert [finding.why for finding in found.findings] == [
        "the base does not answer that name"]


def test_a_line_notes_list_is_held_to_the_base(tmp_path: Path) -> None:
    reply = {"status": "ok", "line_notes": [{"line": 0, "note": "bus error (0x08)"}]}
    found = name_check.check(naming.base(), transcript(tmp_path, reply))
    assert found.findings == []
    assert found.names == 1


def test_a_note_that_names_an_alias_fails(tmp_path: Path) -> None:
    reply = {"status": "ok", "instruction": {"note": "BERR (0x08)"}}
    found = name_check.check(naming.base(), transcript(tmp_path, reply))
    assert [finding.why for finding in found.findings] == ["the base calls it `bus error`"]


def test_a_note_without_its_number_fails(tmp_path: Path) -> None:
    reply = {"status": "ok", "instruction": {"note": "bus error"}}
    found = name_check.check(naming.base(), transcript(tmp_path, reply))
    assert [finding.why for finding in found.findings] == [
        "a note without a name and a number"]


def test_a_line_note_of_a_cut_name_passes_on_its_prefix(tmp_path: Path) -> None:
    entry = naming.base().by_id("m68000:vector:5")
    assert entry is not None
    cut = entry.name[:abbreviation.NAME_WIDTH - len(abbreviation.CUT)]
    reply = {"status": "ok", "instruction": {"note": f"{cut}.. (0x14)"}}
    found = name_check.check(naming.base(), transcript(tmp_path, reply))
    assert found.findings == []


def test_a_directory_with_no_reply_is_invalid(tmp_path: Path) -> None:
    assert name_check.main([str(tmp_path)]) == 3


def test_a_run_with_no_name_to_check_is_invalid(tmp_path: Path) -> None:
    transcript(tmp_path, {"status": "ok", "verdict": "TARGET"})
    assert name_check.main([str(tmp_path)]) == 3


def test_a_run_with_a_name_the_base_holds_passes_main(tmp_path: Path) -> None:
    assert name_check.main([str(transcript(tmp_path, named("bus error")))]) == 0


def test_main_reports_a_finding(tmp_path: Path) -> None:
    assert name_check.main([str(transcript(tmp_path, named("bus fault")))]) == 1


def test_main_refuses_a_directory_that_is_not_there(tmp_path: Path) -> None:
    assert name_check.main([str(tmp_path / "no-such-directory")]) == 3


def test_main_with_no_directory_and_no_default_is_invalid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(name_check, "DEFAULT", tmp_path / "no-such-directory")
    assert name_check.main([]) == 3
