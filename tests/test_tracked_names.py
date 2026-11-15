"""The data this repository tracks is named by scry-core's rule of file names (docs/file-names.md):
the rule, DOS's 8.3 for a file a DOS program uses by name, or a name a convention fixes."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

RULE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*\.[a-z0-9]+")
DOS = re.compile(r"[A-Z0-9_]{1,8}\.[A-Z0-9]{1,3}")
CONVENTIONAL = frozenset({"README.md", "CHANGELOG.md", "CONTRIBUTING.md", "REFERENCE.md",
                          "TRANSCRIPT.md", "LICENSE"})
DATA = ("tests/fixtures/", "demos/", ".scry/")


def outside(paths: list[str]) -> list[str]:
    def named(path: str) -> bool:
        leaf = path.rsplit("/", 1)[-1]
        return bool(leaf.startswith(".") or leaf in CONVENTIONAL or RULE.fullmatch(leaf)
                    or DOS.fullmatch(leaf))
    return [p for p in paths if p.startswith(DATA) and not p.endswith(".py") and not named(p)]


def tracked(root: Path) -> list[str]:
    """The paths git tracks, as written: a plain listing quotes a name with a byte past ASCII."""
    listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True,
                            encoding="utf-8", check=True).stdout
    return [p for p in listed.split("\0") if p]


def test_every_tracked_data_file_is_named_by_the_rule() -> None:
    listed = tracked(Path(__file__).resolve().parents[1])
    data = [p for p in listed if p.startswith(DATA)]
    assert data, "no tracked data file was judged"
    assert outside(listed) == []


def test_the_judge_tells_each_form_apart() -> None:
    assert outside(["tests/fixtures/a/provenance.txt", "demos/mines/MINES.COM",
                    "demos/x/README.md", "tests/fixtures/.gitattributes", "demos/x/demo.py"]) == []
    assert outside(["tests/fixtures/a/PROVENANCE.txt", "demos/x/Shot_1.png",
                    "demos/x/MINES.COMX"]) == ["tests/fixtures/a/PROVENANCE.txt",
                                               "demos/x/Shot_1.png", "demos/x/MINES.COMX"]


def test_a_tracked_name_past_ascii_is_judged(tmp_path: Path) -> None:
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "Caf\u00e9.txt").write_bytes(b"")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    assert outside(tracked(tmp_path)) == ["tests/fixtures/Caf\u00e9.txt"]


def test_the_listing_is_read_as_utf8_on_any_host(monkeypatch: pytest.MonkeyPatch) -> None:
    # git -z writes these bytes on every host; a pipe read as text takes the host's codec, cp1252
    # on Windows.
    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[Any]:
        listed = b"tests/fixtures/Caf\xc3\xa9.txt\x00"
        text = kw.get("text") or kw.get("encoding")
        out = listed.decode(kw.get("encoding") or "cp1252") if text else listed
        return subprocess.CompletedProcess(args, 0, out, "")
    monkeypatch.setattr(subprocess, "run", run)
    assert tracked(Path(".")) == ["tests/fixtures/Caf\u00e9.txt"]
