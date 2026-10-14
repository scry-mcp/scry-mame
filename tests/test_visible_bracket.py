"""Make a cpu visible, act, put the visible one back: what a refused put-back leaves.

A put-back is refused when the cpu to put back is one the debugger ignores (the stub will not
show it, since a step on it would never end). The act has completed by then, so its outcome is
kept and the cpu left visible is named, never replaced by the put-back's refusal. The double
refuses the SECOND `make_visible`: the first shows the row's cpu, the second is the put-back.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resolution_per_cpu import MAIN, SUB, _two_programs  # noqa: E402
from test_server import _RunningSession  # noqa: E402

import gdb_session as g  # noqa: E402
import mame_arming as arming  # noqa: E402
import mame_conditions as conditions  # noqa: E402
import mame_cpus as cpus  # noqa: E402
import mame_declarations as dec  # noqa: E402
import mame_rearm as rearming  # noqa: E402
import mame_state as mstate  # noqa: E402
import server as s  # noqa: E402


def _refuses_the_put_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _RunningSession:
    """The two-cpu double, :maincpu visible, whose second `Hc` is refused."""
    ses = _two_programs(monkeypatch, tmp_path)
    plain = ses.make_visible
    calls: list[int] = []

    def make_visible(thread: int) -> None:
        calls.append(thread)
        if len(calls) == 2:
            raise g.Refused("E01")
        plain(thread)

    ses.make_visible = make_visible  # type: ignore[method-assign]
    ses.calls = calls  # type: ignore[attr-defined]
    return ses


def test_the_evaluation_is_kept_and_the_cpu_left_visible_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _refuses_the_put_back(monkeypatch, tmp_path)
    ses.exprs["{d0==1}"] = 1
    judged = conditions.judged_condition(ses, "bp 0x4a0::subcpu,d0==1", "d0==1", SUB)  # type: ignore[arg-type]
    assert judged.refusal is None, "the condition evaluated, and that is kept"
    assert judged.left_visible is not None and SUB in judged.left_visible, judged
    assert MAIN in judged.left_visible and "focus" in judged.left_visible, judged
    assert ses.visible_cpu == SUB and ses.calls == [2, 1]  # type: ignore[attr-defined]


def test_the_put_back_accepted_says_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The control: the same call on a double that takes both switches."""
    ses = _two_programs(monkeypatch, tmp_path)
    ses.exprs["{d0==1}"] = 1
    judged = conditions.judged_condition(ses, "bp 0x4a0::subcpu,d0==1", "d0==1", SUB)  # type: ignore[arg-type]
    assert judged.refusal is None and judged.left_visible is None, judged
    assert ses.visible_cpu == MAIN


@pytest.mark.parametrize("call", [
    lambda: s.breakpoint_at(ref="0x4a0", condition="d0==1", cpu="subcpu"),
    lambda: s.watch_add(ref="0x4a0", mode="change", length=2, condition="wpdata==1",
                        cpu="subcpu"),
])
def test_a_declaration_whose_put_back_was_refused_stores_nothing_and_says_both(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, call: object,
) -> None:
    """Judged before anything is stored, so the call refuses there: its message carries what
    the evaluation found and names the cpu left visible."""
    ses = _refuses_the_put_back(monkeypatch, tmp_path)
    ses.exprs["{d0==1}"] = 1
    ses.exprs["{wpdata==1}"] = 1
    out = call()  # type: ignore[operator]
    assert out["status"] == "INVALID", out
    assert "evaluates" in out["message"] and SUB in out["message"], out
    assert out["visible_cpu"] == SUB, out
    assert not any(c.startswith(("bp ", "wp ")) for c in ses.commands), ses.commands
    assert arming.store().declarations() == [], "nothing stored"


def test_start_keeps_a_rows_judgement_when_the_put_back_was_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """At `start` the row is armed by its cpu's name, which no visible cpu changes: the row
    comes back, and the pass names the cpu it left visible."""
    ses = _refuses_the_put_back(monkeypatch, tmp_path)
    ses.exprs["{d0==1}"] = 1
    arming.store().add(dec.Declaration("breakpoint", "address", "0x4a0", cpu=SUB,
                                       fingerprint="fp-test", origin="earlier",
                                       condition="d0==1"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert [r["ref"] for r in out["rearmed"]] == ["0x4a0"], out
    assert SUB in out["note"] and "focus" in out["note"], out


def test_a_refused_put_back_after_an_act_that_refused_says_both(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The act's own refusal goes out, and it names the cpu left visible: a refusal that hid it
    would leave the cpu moved with nothing saying so."""
    ses = _refuses_the_put_back(monkeypatch, tmp_path)

    def act(_item: None, _refusal: object) -> None:
        raise mstate.Invalid("bad_argument", "the act refused")

    with pytest.raises(mstate.Invalid) as raised:
        cpus.on_cpus(ses, MAIN, {SUB: [None]}, "a test", act)  # type: ignore[arg-type]
    assert "the act refused" in str(raised.value) and SUB in str(raised.value), raised.value
    assert raised.value.code == "bad_argument"


def test_the_bracket_puts_back_the_cpu_it_was_given_whatever_cpulist_says_later(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The caller read the visible cpu once; a second reading that came back empty would leave
    nothing to put back."""
    ses = _two_programs(monkeypatch, tmp_path)
    ses.exprs["{d0==1}"] = 1
    monkeypatch.setattr(cpus, "visible_cpu", lambda _ses: None)
    note = cpus.on_cpus(ses, MAIN, {SUB: [None]}, "a test", lambda *_: None)  # type: ignore[arg-type]
    assert note is None and ses.visible_cpu == MAIN, (note, ses.visible_cpu)


def test_start_keeps_a_change_watchs_judgement_when_the_put_back_was_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The watch branch of the re-arm, which collects its own note."""
    ses = _refuses_the_put_back(monkeypatch, tmp_path)
    ses.exprs["{wpdata==1}"] = 1
    arming.store().add(dec.Declaration("watch", "address", "0x4a0", cpu=SUB,
                                       fingerprint="fp-test", origin="earlier", width=2,
                                       fmt="u16", watch_mode="change", condition="wpdata==1"))
    out = rearming.rearm_breakpoints_and_watches(ses)  # type: ignore[arg-type]
    assert SUB in out.get("note", "") and "focus" in out["note"], out


def test_a_condition_that_does_not_evaluate_and_a_refused_put_back_say_both(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _refuses_the_put_back(monkeypatch, tmp_path)
    monkeypatch.setattr(conditions, "not_evaluated", lambda _ses, _cond: "unknown symbol d9")
    out = s.breakpoint_at(ref="0x4a0", condition="d0==1", cpu="subcpu")
    assert out["status"] == "INVALID" and "does not evaluate" in out["message"], out
    assert out["visible_cpu"] == SUB, out
    assert not any(c.startswith("bp ") for c in ses.commands)


def test_an_act_that_breaks_the_channel_still_puts_the_visible_cpu_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_programs(monkeypatch, tmp_path)

    def act(_item: None, _refusal: object) -> None:
        raise g.SessionError("no answer")

    with pytest.raises(g.SessionError):
        cpus.on_cpus(ses, MAIN, {SUB: [None]}, "a test", act)  # type: ignore[arg-type]
    assert ses.visible_cpu == MAIN


def test_a_stub_that_serves_no_cpu_reads_no_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ses = _two_programs(monkeypatch, tmp_path)
    ses.threads = {}
    monkeypatch.setattr(cpus, "stub_cpu", lambda _ses: None)
    assert cpus.register_blocks(ses) == {}  # type: ignore[arg-type]
