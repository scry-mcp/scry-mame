"""`perform(path=)`: the document a session replays, and the two arguments that cannot come
together."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from server_support import _running  # noqa: E402

from scry_mame import server as s  # noqa: E402


def _doc(tmp_path: Path, **fields: Any) -> Path:
    path = tmp_path / "script.json"
    body: dict[str, Any] = {"version": 3, "server": "mame",
                            "steps": [{"op": "no_such_tool"}], **fields}
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_a_documents_steps_are_judged_as_the_whole_list(tmp_path: Path) -> None:
    out = s.perform(path=str(_doc(tmp_path)))
    assert out["status"] == "INVALID" and "no_such_tool" in out["message"], out
    assert "Nothing was run" in out["message"], out


def test_a_document_replays_on_the_parked_session(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _running(monkeypatch, tmp_path)
    path = tmp_path / "script.json"
    path.write_text(json.dumps({"version": 3, "steps": [{"op": "status"}, {"op": "status"}]}))
    out = s.perform(path=str(path))
    assert out["status"] == "ok" and out["steps_completed"] == 2, out


def test_a_step_and_a_path_are_refused_before_the_step_list_is_judged(
        tmp_path: Path) -> None:
    out = s.perform(steps=[{"op": "no_such_tool"}], path=str(_doc(tmp_path)))
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "steps and path" in out["message"], out


def test_the_whole_list_is_refused_before_the_first_step_runs(tmp_path: Path) -> None:
    path = tmp_path / "script.json"
    path.write_text(json.dumps({"version": 3,
                                "steps": [{"op": "status"}, {"op": "no_such_tool"}]}))
    out = s.perform(path=str(path))
    assert out["status"] == "INVALID" and "no_such_tool" in out["message"], out
    assert out["steps_completed"] == 0, out


def test_a_step_and_a_path_are_refused_together(tmp_path: Path) -> None:
    out = s.perform(steps=[{"op": "status"}], path=str(_doc(tmp_path)))
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "steps and path" in out["message"], out


def test_neither_a_step_nor_a_path_is_refused() -> None:
    out = s.perform()
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "give steps, or path" in out["message"], out


def test_a_document_version_this_server_does_not_read_is_refused_by_name(tmp_path: Path) -> None:
    out = s.perform(path=str(_doc(tmp_path, version=2)))
    assert out["status"] == "INVALID" and out["code"] == "bad_argument", out
    assert "version 2" in out["message"], out
