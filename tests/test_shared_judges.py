"""What MAME judges through scry-core's shared judges, as the DOSBox-X server does."""

from __future__ import annotations

from pathlib import Path

import pytest
from scry_core.reply_contract import Invalid

from scry_mame import (
    breakpoints,  # noqa: E402
    inputs,  # noqa: E402
    regpoints,  # noqa: E402
    savestates,  # noqa: E402
    symbols,  # noqa: E402
    watches,  # noqa: E402
)


def test_a_state_name_never_starts_with_a_dash() -> None:
    """It is one console parameter, and a leading dash reads as an option."""
    with pytest.raises(Invalid, match="never starting with `-`"):
        savestates.check_state_name("-x")
    savestates.check_state_name("_save")


def test_a_types_file_an_editor_marked_with_a_bom_reads_its_first_name(tmp_path: Path) -> None:
    path = tmp_path / "types.txt"
    path.write_bytes(b"\xef\xbb\xbf_start: u16\n")
    assert symbols.read_types(str(path)) == {"_START": "u16"}


def test_an_input_file_the_filesystem_will_not_look_at_is_refused_not_raised(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(self: Path) -> bool:
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(Path, "is_file", denied)
    with pytest.raises(Invalid, match="cannot be looked at") as e:
        inputs.input_file("cfg", str(tmp_path / "x.cfg"), "cfg")
    assert e.value.code == "bad_argument"


@pytest.mark.parametrize("check", [breakpoints.check_clear_breakpoints,
                                   regpoints.check_clear_regpoints,
                                   watches.check_clear_watches],
                         ids=["breakpoint", "regpoint", "watch"])
def test_a_blank_ref_beside_all_is_refused_never_read_as_all(check: object) -> None:
    with pytest.raises(Invalid, match="takes no `ref`"):
        check(ref=" ", all=True)  # type: ignore[operator]


def test_a_comment_row_from_no_session_names_the_comments_own_remedy() -> None:
    """A comment is adopted by commenting it again, never by declaring it."""
    from scry_mame import arming
    from scry_mame import declarations as dec

    row = arming.decl_row(dec.Declaration("comment", "symbol", "fade", cpu="maincpu",
                                          text="t"))
    assert "comment it again" in row["origin"]["why"], row
    breakpoint_row = arming.decl_row(dec.Declaration("breakpoint", "symbol", "fade"))
    assert "declare it again" in breakpoint_row["origin"]["why"], breakpoint_row


def test_close_and_status_with_no_session_say_so_in_the_words_both_servers_use() -> None:
    from scry_core import session_block

    from scry_mame import server as s

    closed = s.close()
    assert closed["summary"] == session_block.NO_SESSION_CLOSE, closed
    assert closed["note"] == session_block.NO_SESSION_CLOSE_NOTE, closed
    said = s.status()
    assert said["summary"] == session_block.NO_SESSION_STATUS
    assert "last_stop" in said and "presence" not in said, said
