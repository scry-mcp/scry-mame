"""Cross-tool rules the published text states, each held where a caller reads it."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doubles import documented  # noqa: E402

import server as s  # noqa: E402


def _texts() -> dict[str, str]:
    return {t.name: " ".join((t.description or "").split())
            for t in asyncio.run(s.mcp.list_tools())}


def test_the_instructions_say_a_left_out_cpu_lists_every_cpu() -> None:
    text = " ".join((s.mcp.instructions or "").split())
    assert "no `cpu` is the VISIBLE one" not in text
    assert "no `cpu` acts on the VISIBLE one" in text and "lists or clears all" in text, text


@pytest.mark.parametrize("tool", ["run_to", "breakpoint_at", "regpoint_add"])
def test_a_condition_says_its_bare_numbers_are_hex(tool: str) -> None:
    assert "bare numbers hex" in _texts()[tool]


def test_no_condition_example_writes_a_bare_number() -> None:
    takers = ("run_to", "breakpoint_at", "watch_add", "regpoint_add")
    examples = re.findall(r"`[^`]*(?:==|!=)[^`]*`", " ".join(_texts()[t] for t in takers))
    bare = [e for e in examples if re.search(r"(?:==|!=)(?!0x)\d{2,}", e)]
    assert examples and not bare, (examples, bare)


def test_start_says_which_paths_are_directories() -> None:
    assert "`rompath`, `inipath`, `state_dir` directories, the rest files" in _texts()["start"]


def test_gfx_locate_names_its_source_arguments() -> None:
    text = documented("gfx_locate")
    assert all(f"`{a}`" in text for a in ("tag", "ref", "offset", "cpu")), text


def test_no_sentence_mixes_a_0x_number_with_a_decimal_one() -> None:
    mixed = []
    for name, text in _texts().items():
        for sent in re.split(r"(?<=[.;])\s", text):
            if (re.search(r"\b0x[0-9a-fA-F]{2,}\b", sent)
                    and re.search(r"(?<![\w.$#x])\d{5,}(?!\w)", sent)):
                mixed.append(f"{name}: {sent[:80]}")
    assert not mixed, mixed
