"""The comment file's format, rule by rule: what a reader accepts, what it refuses and on which
line, and what a writer writes. Every expected text is written here from the format's own
definition, never read back from the writer."""


import pytest

from scry_mame import comment_file as cf  # noqa: E402
from scry_mame import gdb_session as gs  # noqa: E402

HEAD = "# comments v1: ref\tcpu\tcreated_at\ttext\n"
STAMP = "2026-10-02T00:30:00+00:00"


def refused(text: str, line: int, words: str) -> None:
    with pytest.raises(cf.CommentFileError) as e:
        cf.parse(text, "f.tsv")
    assert str(e.value).startswith(f"f.tsv:{line}: "), str(e.value)
    assert words in str(e.value), str(e.value)


def test_the_header_is_the_exact_version_line() -> None:
    assert cf.HEADER + "\n" == HEAD


def test_a_file_reads_back_its_rows_with_their_lines() -> None:
    rows = cf.parse(HEAD + f"irq_vblank\t:maincpu\t{STAMP}\tvblank, then input\n"
                    f"0x400\t:subcpu\t{STAMP}\tsee [1234h]; a ñ é\n", "f.tsv")
    assert rows == [cf.Row("irq_vblank", ":maincpu", STAMP, "vblank, then input"),
                    cf.Row("0x400", ":subcpu", STAMP, "see [1234h]; a ñ é")]
    assert [r.line for r in rows] == [2, 3]


def test_the_text_is_the_rest_of_the_line_after_three_tabs_and_a_cpu_may_be_empty() -> None:
    (only,) = cf.parse(HEAD + f"fade\t\t{STAMP}\ta b  c\n")
    assert (only.ref, only.cpu, only.text) == ("fade", "", "a b  c")


def test_blank_lines_hash_lines_and_crlf_are_read() -> None:
    rows = cf.parse(HEAD.replace("\n", "\r\n") + "\r\n# a note\r\n   \r\n"
                    f"x\t:maincpu\t{STAMP}\tt\r\n")
    assert [(r.ref, r.text, r.line) for r in rows] == [("x", "t", 5)]


def test_a_file_without_a_final_newline_reads_its_last_row() -> None:
    assert [r.ref for r in cf.parse(HEAD + f"x\t:m\t{STAMP}\tt")] == ["x"]


@pytest.mark.parametrize(("text", "words"), [
    ("", "the first line is ''"),
    ("x\t:m\tt\n", "the first line is"),
    ("﻿" + HEAD, "byte order mark"),
    ("# comments v2: ref\tcpu\tcreated_at\ttext\n", "the first line is"),
])
def test_anything_but_the_header_on_line_one_is_refused(text: str, words: str) -> None:
    refused(text, 1, words)


@pytest.mark.parametrize(("row", "words"), [
    (f"x\t:m\t{STAMP}", "3 columns"),
    ("x", "has 1 column"),
    (f"\t:m\t{STAMP}\tt", "the ref is empty"),
    (f"a b\t:m\t{STAMP}\tt", "the ref holds whitespace"),
    (f"#x\t:m\t{STAMP}\tt", None),            # a `#` line is skipped, never a row
    (f"x\t: m\t{STAMP}\tt", "the cpu holds whitespace"),
    (f"x\t:\x07m\t{STAMP}\tt", "the cpu holds whitespace or a character that is not printable"),
    (f"a\x07\t:m\t{STAMP}\tt", "the ref holds whitespace or a character that is not printable"),
    ("x\t:m\tyesterday\tt", "not a stamp with a date, a time and an offset"),
    ("x\t:m\t\tt", "not a stamp with a date, a time and an offset"),
    ("x\t:m\t2026-10-02\tt", "not a stamp with a date, a time and an offset"),
    ("x\t:m\t2026-10-02T00:30:00\tt", "not a stamp with a date, a time and an offset"),
    ("\x1f", "has 1 column"),                 # not blank: only spaces and tabs are
    (f"x\t:m\t{STAMP}\t", "the text is empty"),
    (f"x\t:m\t{STAMP}\ta\tb", "is not printable"),
    (f"x\t:m\t{STAMP}\t a", "whitespace"),
    (f"x\t:m\t{STAMP}\ta ", "whitespace"),
    (f"x\t:m\t{STAMP}\ta\x07", "is not printable"),
    (f"x\t:m\t{STAMP}\ta\rb", "a carriage return that does not end the line"),
    (f"x\t:m\t{STAMP}\t" + "y" * (cf.TEXT_MAX_BYTES + 1), f"past the {cf.TEXT_MAX_BYTES}"),
])
def test_a_row_breaking_a_rule_is_refused_on_its_line(row: str, words: str | None) -> None:
    text = HEAD + "# kept\n" + row + "\n"
    if words is None:
        assert cf.parse(text) == []
    else:
        refused(text, 3, words)


def test_one_ref_on_one_cpu_twice_is_refused_naming_both_lines() -> None:
    refused(HEAD + f"x\t:m\t{STAMP}\ta\ny\t:m\t{STAMP}\tb\nx\t:m\t{STAMP}\tc\n", 4,
            "already on line 2")
    assert len(cf.parse(HEAD + f"x\t:m\t{STAMP}\ta\nx\t:s\t{STAMP}\tb\n")) == 2


def test_the_bound_is_in_bytes_and_at_it_a_text_is_kept() -> None:
    at = "ñ" * (cf.TEXT_MAX_BYTES // 2) + "z" * (cf.TEXT_MAX_BYTES % 2)
    assert len(at.encode()) == cf.TEXT_MAX_BYTES
    assert cf.text_fault(at) is None and cf.text_fault("y" * cf.TEXT_MAX_BYTES) is None
    assert cf.text_fault(at + "z") is not None
    assert cf.text_fault("ñ" * (cf.TEXT_MAX_BYTES // 2 + 1)) is not None, \
        "fewer characters than the bound, more bytes: refused"


def test_the_bound_is_one_line_of_comlist() -> None:
    """MAME's `comlist` prints ` %08X - <text>` (`comment_import`), and its console wraps at
    `CONSOLE_WRAP_COLS`, a line of exactly that width being cut."""
    prefix = f" {0:08X} - "
    assert gs.CONSOLE_WRAP_COLS - 1 - len(prefix) == cf.TEXT_MAX_BYTES


def test_the_writer_sorts_by_cpu_then_ref_in_code_point_order() -> None:
    rows = [cf.Row("irq_vblank", ":maincpu", STAMP, "b"), cf.Row("0x400", ":subcpu", STAMP, "c"),
            cf.Row("0x500", ":maincpu", STAMP, "a"), cf.Row("Zeta", ":maincpu", STAMP, "d")]
    assert cf.render(rows) == (HEAD + f"0x500\t:maincpu\t{STAMP}\ta\n"
                               f"Zeta\t:maincpu\t{STAMP}\td\n"
                               f"irq_vblank\t:maincpu\t{STAMP}\tb\n"
                               f"0x400\t:subcpu\t{STAMP}\tc\n")


@pytest.mark.parametrize(("rows", "words"), [
    ([cf.Row("x", "a b", STAMP, "t")], "the cpu holds whitespace"),
    ([cf.Row("x", ":m", "", "t")], "the created_at"),
    ([cf.Row("#x", ":m", STAMP, "t")], "the ref starts with `#`"),
    ([cf.Row("x", ":m", STAMP, "a\nb")], "the text holds"),
    ([cf.Row("x", ":m", STAMP, "a"), cf.Row("x", ":m", STAMP, "b")], "twice"),
])
def test_the_writer_refuses_a_row_its_reader_would_refuse(rows: list[cf.Row],
                                                          words: str) -> None:
    with pytest.raises(cf.CommentFileError, match=words):
        cf.render(rows)


def test_an_empty_store_writes_the_header_alone_and_reads_back_empty() -> None:
    assert cf.render([]) == HEAD
    assert cf.parse(cf.render([])) == []


def test_what_the_writer_writes_the_reader_reads_back() -> None:
    rows = [cf.Row("0x400", ":subcpu", STAMP, 'a "quote" and \\'),
            cf.Row("fade", ":maincpu", STAMP, "x" * cf.TEXT_MAX_BYTES)]
    assert cf.parse(cf.render(rows)) == sorted(rows, key=lambda r: (r.cpu, r.ref))


@pytest.mark.parametrize(("ref", "fault"), [
    ("fade", None), ("0x400", None), ("", "is empty"), ("a b", "whitespace"),
    ("#x", "starts with `#`"), ("a b", "whitespace"),
])
def test_a_refs_shape_in_a_file(ref: str, fault: str | None) -> None:
    got = cf.ref_fault(ref)
    assert (got is None) if fault is None else (got is not None and fault in got), got
