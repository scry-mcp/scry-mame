"""This server's half of `scry_core.comment_file`: how a ref and a cpu are spelled in the file."""

from __future__ import annotations

from scry_core import comment_file as core
from scry_core.comment_file import (
    HEADER,
    TEXT_MAX_BYTES,
    CommentFileError,
    Row,
    stamp_fault,
    text_fault,
)

__all__ = ["HEADER", "TEXT_MAX_BYTES", "CommentFileError", "Row", "cpu_fault", "parse",
           "ref_fault", "render", "stamp_fault", "text_fault"]


def ref_fault(ref: str) -> str | None:
    """What a ref breaks as a file spells it, or None."""
    if not ref:
        return "is empty"
    if ref.startswith("#"):
        return "starts with `#`, which a reader skips as a comment line"
    return core.word_fault(ref)


def cpu_fault(cpu: str) -> str | None:
    """What a cpu column breaks, or None; empty is allowed, for a one-cpu server."""
    return core.word_fault(cpu)


POLICY = core.Policy(ref_fault=ref_fault, cpu_fault=cpu_fault)


parse, render = POLICY.parse, POLICY.render
