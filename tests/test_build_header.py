"""`tests/live/build_header.py`: the sources a run's MAME came from, printed and never judged."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

LIVE = Path(__file__).parent / "live"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_header", LIVE / "build_header.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(tree: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t",
                           *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "mame"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "a.cpp").write_text("one\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "pin")
    return root


def test_a_clean_tree_hashes_as_its_head_and_a_patched_one_as_the_files_it_holds(
        tree: Path) -> None:
    mod = _module()
    head_tree = _git(tree, "show", "-s", "--format=%T", "HEAD")
    assert mod.patched_tree(tree) == head_tree
    (tree / "a.cpp").write_text("two\n")
    (tree / "new.cpp").write_text("added, untracked\n")        # a patch's new file counts
    patched = mod.patched_tree(tree)
    assert patched != head_tree
    assert _git(tree, "status", "--porcelain").count("\n") == 1     # the real index is untouched


def test_the_header_names_the_pin_and_the_hash_and_says_unknown_for_a_missing_tree(
        tree: Path, tmp_path: Path) -> None:
    mod = _module()
    pin = _git(tree, "rev-parse", "HEAD")
    shown = mod.tree_lines(str(tree))
    assert any(pin in ln for ln in shown) and any(mod.patched_tree(tree) in ln for ln in shown)
    for absent in ("", str(tmp_path / "nowhere")):
        lines = mod.tree_lines(absent)
        assert len(lines) == 1 and "unknown" in lines[0]


def test_the_binary_line_compares_the_live_bytes_with_the_pin(tmp_path: Path) -> None:
    mod = _module()
    bench = tmp_path / "bench"
    (bench / "m68k-dual" / "upstream").mkdir(parents=True)
    exe = bench / "m68k-dual" / "upstream" / "radendu"
    exe.write_bytes(b"binary")
    pin = {"path": "m68k-dual/upstream/radendu", "sha256": hashlib.sha256(b"binary").hexdigest(),
           "source_repo": "tch-blitter", "source_path": "upstream/radendu",
           "source_commit": "89bd7847f3e635607c0299d3dd0644367199ab03"}
    (bench / "bench.json").write_text(json.dumps([pin]))
    line = mod.binary_line(bench, str(exe))
    assert pin["sha256"] in line and "89bd7847f3e6" in line and "matches its pin" in line
    exe.write_bytes(b"other")
    assert "DIFFERS" in mod.binary_line(bench, str(exe))
    assert "unknown" in mod.binary_line(bench, str(tmp_path / "not-in-the-bench"))
