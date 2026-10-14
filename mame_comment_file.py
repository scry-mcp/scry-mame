"""THE COMMENT FILE: one line per comment, the record a project versions beside its symbol file.

    # comments v1: ref<TAB>cpu<TAB>created_at<TAB>text
    0x500<TAB>:maincpu<TAB>2026-10-02T00:30:00+00:00<TAB>clears the sprite list
    irq_vblank<TAB>:maincpu<TAB>2026-10-02T00:31:12+00:00<TAB>vblank: blits, then the input

A TSV and not YAML, though the symbol files beside it are YAML: four fields split on a tab need no
YAML reader, so a server without one reads the same file with a reader of its own. The text goes
LAST, so it is the rest of the line and needs no quoting or escape; a comment cannot hold a tab or
a newline, which the text rule refuses with every other character that is not printable. The
writer sorts the rows by cpu, then ref, in code-point order, so a re-save moves nothing that did
not change and `git diff` shows exactly the comments that did. There is no column for the build:
a raw address read into another build is trusted for it, which is why a comment that should
survive a rebuild is made by symbol.

This module judges the FILE: its header, its columns, a text, a ref's and a cpu's shape in a file,
a stamp, one (ref, cpu) twice. What a ref names and whether a cpu exists are the server's, which
has the table and the machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import mame_prose as prose

#: Line 1, exactly: the version mark a reader checks before anything else.
HEADER = "# comments v1: ref\tcpu\tcreated_at\ttext"
# THE LONGEST TEXT, IN UTF-8 BYTES: what one line of MAME's `comlist` holds unbroken. `comlist`
# prints a comment after a 12-character prefix (` %08X - `, `comment_import`), and the console cuts
# a line that reaches `gdb_session.CONSOLE_WRAP_COLS`, so the column less one less the prefix is
# what comes back whole from the one MAME command that lists comments. Bytes and not characters,
# the cautious count of the two: a test holds the literal to that derivation.
TEXT_MAX_BYTES = 237
_BOM = "﻿"


@dataclass(frozen=True)
class Row:
    """One line of the file: the comment's `ref` as stored, its cpu's absolute tag (the format
    allows it empty, for a server with one cpu; this one refuses that at load), the stamp it was
    made at, and its text."""

    ref: str
    cpu: str
    created_at: str
    text: str
    #: The line it was read from, which a refusal of the row names; 0 for a row nobody read.
    line: int = field(default=0, compare=False)


class CommentFileError(ValueError):
    """A file this format does not read, or rows it cannot write, the message naming the line
    or the row and what was wrong."""


def text_fault(text: str) -> str | None:
    """What a comment's text breaks, or None: empty, a character that is not printable (a tab,
    a newline, any control), whitespace at either edge, or more than `TEXT_MAX_BYTES` UTF-8
    bytes. The one rule for a text typed into a call, held in the store, and read from a file."""
    if not text:
        return "is empty"
    if not text.isprintable():
        bad = next(c for c in text if not c.isprintable())
        return f"holds {bad!r}, which is not printable: one comment is one line of text"
    if text != text.strip():
        return "starts or ends with whitespace, which nobody reading the file can see"
    size = len(text.encode("utf-8"))
    if size > TEXT_MAX_BYTES:
        return (f"is {size} UTF-8 bytes, past the {TEXT_MAX_BYTES} one line of MAME's "
                "`comlist` holds")
    return None


def _word_fault(word: str) -> str | None:
    if not word.isprintable() or any(c.isspace() for c in word):
        return "holds whitespace or a character that is not printable"
    return None


def ref_fault(ref: str) -> str | None:
    """What a ref breaks as a FILE spells it, or None: empty, whitespace or a character that is
    not printable inside it, or a leading `#`, which a reader takes for a comment line."""
    if not ref:
        return "is empty"
    if ref.startswith("#"):
        return "starts with `#`, which a reader skips as a comment line"
    return _word_fault(ref)


def cpu_fault(cpu: str) -> str | None:
    """What a cpu column breaks, or None: whitespace or a character that is not printable. It may
    be empty, on a server with one cpu."""
    return _word_fault(cpu)


def stamp_fault(stamp: str) -> str | None:
    """What a `created_at` breaks, or None: it is a date AND a time with its offset from UTC, the
    store's own stamp, so a file read on another machine means the same instant."""
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None or "T" not in stamp:
        return (f"{stamp!r} is not a stamp with a date, a time and an offset from UTC, as "
                "`YYYY-MM-DDTHH:MM:SS+00:00`")
    return None


def row_fault(r: Row) -> str | None:
    """What one row breaks, or None, its column named first: the rules `parse` holds a line to
    and `render` holds a row to, so a file this module writes is one it reads."""
    for column, fault in (("ref", ref_fault(r.ref)), ("cpu", cpu_fault(r.cpu)),
                          ("created_at", stamp_fault(r.created_at)),
                          ("text", text_fault(r.text))):
        if fault is not None:
            return f"the {column} {fault}"
    return None


def parse(text: str, where: str = "the comment file") -> list[Row]:
    """Every row of a comment file's text, or the refusal naming the first line that breaks
    the format: no header (or another one, or a BOM before it), a row of fewer than four
    columns, a row breaking `row_fault`, one (ref, cpu) on two lines. CRLF reads as LF; lines of
    nothing but spaces and tabs, and lines starting with `#`, are skipped after the header.
    `where` names the file in a refusal."""
    lines = text.replace("\r\n", "\n").split("\n")
    if lines[0] != HEADER:
        why = ("starts with a byte order mark" if lines[0].startswith(_BOM)
               else f"is {lines[0][:80]!r}")
        raise CommentFileError(f"{where}:1: the first line {why}, and a comment file's is "
                               f"exactly {HEADER!r}")
    rows: list[Row] = []
    seen: dict[tuple[str, str], int] = {}
    for lineno, line in enumerate(lines[1:], 2):
        if not line.strip(" \t") or line.startswith("#"):
            continue
        cols = line.split("\t", 3)
        if len(cols) < 4:
            raise CommentFileError(f"{where}:{lineno}: a row is ref, cpu, created_at and text "
                                   "separated by tabs; this one has "
                                   f"{prose.counted(len(cols), 'column')}")
        row = Row(cols[0], cols[1], cols[2], cols[3], line=lineno)
        if (fault := row_fault(row)) is not None:
            raise CommentFileError(f"{where}:{lineno}: {fault}")
        if (row.ref, row.cpu) in seen:
            raise CommentFileError(f"{where}:{lineno}: {row.ref!r} on {row.cpu or 'no cpu'} "
                                   f"again, already on line {seen[row.ref, row.cpu]}: one "
                                   "comment per place")
        seen[row.ref, row.cpu] = lineno
        rows.append(row)
    return rows


def render(rows: list[Row]) -> str:
    """The file's text for `rows`: the header, then one line per row sorted by cpu and ref in
    code-point order, every line ended by LF. A row `parse` would refuse (`row_fault`, or one
    (ref, cpu) twice) is refused here instead, so nothing is written that cannot be read back."""
    seen: set[tuple[str, str]] = set()
    for r in rows:
        if (fault := row_fault(r)) is not None:
            raise CommentFileError(f"{r.ref!r} on {r.cpu or 'no cpu'}: {fault}")
        if (r.ref, r.cpu) in seen:
            raise CommentFileError(f"{r.ref!r} on {r.cpu or 'no cpu'} twice: a file holds one "
                                   "comment per (ref, cpu)")
        seen.add((r.ref, r.cpu))
    body = "".join(f"{r.ref}\t{r.cpu}\t{r.created_at}\t{r.text}\n"
                   for r in sorted(rows, key=lambda r: (r.cpu, r.ref)))
    return f"{HEADER}\n{body}"
