"""The data this repository tracks is named by scry-core's rule of file names (docs/file-names.md):
the rule, DOS's 8.3 for a file a DOS program uses by name, or a name a convention fixes."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

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


def test_every_tracked_data_file_is_named_by_the_rule() -> None:
    root = Path(__file__).resolve().parents[1]
    listed = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True,
                            check=True).stdout.split()
    data = [p for p in listed if p.startswith(DATA)]
    assert data, "no tracked data file was judged"
    assert outside(listed) == []


def test_the_judge_tells_each_form_apart() -> None:
    assert outside(["tests/fixtures/a/provenance.txt", "demos/mines/MINES.COM",
                    "demos/x/README.md", "tests/fixtures/.gitattributes", "demos/x/demo.py"]) == []
    assert outside(["tests/fixtures/a/PROVENANCE.txt", "demos/x/Shot_1.png",
                    "demos/x/MINES.COMX"]) == ["tests/fixtures/a/PROVENANCE.txt",
                                               "demos/x/Shot_1.png", "demos/x/MINES.COMX"]
