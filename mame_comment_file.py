"""THE COMMENT FILE: one line per comment, the record a project versions beside its symbol file.

    # comments v1: ref<TAB>cpu<TAB>created_at<TAB>text
    0x500<TAB>:maincpu<TAB>2026-10-02T00:30:00+00:00<TAB>clears the sprite list
    irq_vblank<TAB>:maincpu<TAB>2026-10-02T00:31:12+00:00<TAB>vblank: blits, then the input

The format is `scry_core.comment_file`'s, which both servers read and write; this module is this
server's half of it: a ref as a file spells it here (an address as `0x`, or a symbol) and a cpu
column that names a cpu by its tag. What a ref names and whether a cpu exists are the server's,
which has the table and the machine.

A TSV and not YAML, though the symbol files beside it are YAML: four fields split on a tab need no
YAML reader, so a server without one reads the same file with a reader of its own.
"""

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
    """What a ref breaks as a FILE spells it, or None: empty, whitespace or a character that is
    not printable inside it, or a leading `#`, which a reader takes for a comment line."""
    if not ref:
        return "is empty"
    if ref.startswith("#"):
        return "starts with `#`, which a reader skips as a comment line"
    return core.word_fault(ref)


def cpu_fault(cpu: str) -> str | None:
    """What a cpu column breaks, or None: whitespace or a character that is not printable. It may
    be empty, on a server with one cpu."""
    return core.word_fault(cpu)


POLICY = core.Policy(ref_fault=ref_fault, cpu_fault=cpu_fault)


def parse(text: str, where: str = "the comment file") -> list[Row]:
    """Every row of a comment file's text, or the refusal naming the first line that breaks the
    format (`scry_core.comment_file.parse`), held to this server's columns."""
    return core.parse(text, where, POLICY)


def render(rows: list[Row]) -> str:
    """The file's text for `rows` (`scry_core.comment_file.render`), held to this server's
    columns."""
    return core.render(rows, POLICY)
