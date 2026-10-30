"""Where a run's MAME came from, printed so two hosts' logs compare. It judges nothing."""

import os
import subprocess
import tempfile
from pathlib import Path

from scry_core import live_bench as bench
from scry_core.verdict import Invalid

#: The checkout the m68k-dual MAME was built from.
TREE_VAR = "MAME_DUAL_TREE"


def _git(tree: Path, *args: str, index: Path | None = None) -> str:
    env = {**os.environ, "GIT_INDEX_FILE": str(index)} if index else None
    done = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True,
                          check=False, env=env)
    if done.returncode != 0:
        raise OSError(f"git {args[0]} answered rc={done.returncode}: {done.stderr.strip()}")
    return done.stdout.strip()


def patched_tree(tree: Path) -> str:
    """What `tree` holds on disk, new files included, hashed through a temporary index."""
    with tempfile.TemporaryDirectory() as scratch:
        index = Path(scratch) / "index"
        _git(tree, "read-tree", "HEAD", index=index)
        _git(tree, "add", "-A", index=index)
        return _git(tree, "write-tree", index=index)


def tree_lines(tree: str) -> list[str]:
    if not tree:
        return [f"MAME sources: unknown: {TREE_VAR} names no build tree"]
    try:
        return [f"MAME sources: pin {_git(Path(tree), 'rev-parse', 'HEAD')}, "
                f"patched tree {patched_tree(Path(tree))}"]
    except OSError as e:
        return [f"MAME sources: unknown: {e}"]


def fork_line(binary: str) -> str:
    try:
        return f"MAME fork: {_git(Path(binary).parent, 'rev-parse', 'HEAD')}"
    except OSError as e:
        return f"MAME fork: unknown: {e}"


def binary_line(root: Path, binary: str) -> str:
    try:
        rel = Path(binary).relative_to(root).as_posix()
        pinned = next((e for e in bench.load(root / bench.MANIFEST) if e.path == rel), None)
        if pinned is None:
            return f"m68k-dual binary: unknown: {rel} is not pinned in the bench"
        live = bench.digest(Path(binary))
    except (OSError, ValueError, Invalid) as e:
        return f"m68k-dual binary: unknown: {e}"
    state = "matches its pin" if live == pinned.sha256 else f"DIFFERS from its pin {pinned.sha256}"
    return (f"m68k-dual binary: sha256 {live} {state}; "
            f"source {pinned.source_repo}@{pinned.source_commit[:12]}")


def lines(root: Path, dual_binary: str, free_binary: str) -> list[str]:
    return [fork_line(free_binary) if free_binary else "MAME fork: unknown: MAME_BINARY is unset",
            binary_line(root, dual_binary), *tree_lines(os.environ.get(TREE_VAR, ""))]
