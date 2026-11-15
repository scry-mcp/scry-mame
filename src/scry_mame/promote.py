"""`promote`: what this session learned, kept as a candidate and written on approval; where it
may be written is scry-core's to decide."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from scry_core import given, project_store
from scry_core import promote as core

from scry_mame import launch
from scry_mame.state import STATE

#: `start`'s arguments a recipe leaves to the run: this session's files, port and window.
RUN_OWN = frozenset({"state_dir", "stub_port", "display", "size", "background", "view",
                     "throttle_from_frame", "boot_lua", "env", "profile"})
#: What a recipe may hold as a path; `inipath` is one, though `start` judges it itself.
PROMOTE_PATHS = (*launch.START_PATHS, "inipath")
#: What a recipe cannot do without: the machine it boots.
NEEDS = ("system",)
SERVER = "mame"


@contextmanager
def launching(profile: str) -> Iterator[None]:
    """A start's launch, from the profile it read ("" for none)."""
    with STATE.drafts.starting(profile=profile, live=lambda: STATE.proc):
        yield


def keep_start(params: Mapping[str, Any], *, defaults: Mapping[str, Any]) -> bool:
    """This start's recipe as a candidate, named by the profile it read or the machine."""
    system = str(params.get("system") or "")
    if not system:
        return False
    if STATE.drafts.loaded_name("start") and core.only_the_run(given.names(), RUN_OWN):
        return False
    document: dict[str, Any] = {"format": project_store.FORMAT}
    document.update({name: value for name, value in params.items()
                     if name in defaults and name not in RUN_OWN
                     and value != defaults[name]})
    return STATE.drafts.keep("start", STATE.drafts.loaded_name("start") or system, document,
                             needs=NEEDS, path_keys=PROMOTE_PATHS, own=sorted(RUN_OWN))


def after_map(method: str, reply: dict[str, Any]) -> dict[str, Any]:
    """A map's `add` keeps what it learned, named by this session's entry or the machine."""
    application = STATE.maps.session_application or str(STATE.system or "")
    if method != "add" or not application:
        return reply
    if STATE.drafts.keep("maps", application, STATE.maps.document(application)):
        return {**reply, "kept": core.kept_line(STATE.drafts)}
    return reply


def promote(dry_run: bool = False, entries: list[str] | None = None,
            names: dict[str, str] | None = None, root: str = "") -> dict[str, Any]:
    """The `promote` tool's body."""
    return core.promote(STATE.drafts, dry_run=dry_run, entries=entries, names=names, root=root,
                        state=scratch(), server=SERVER)


def after_close(reply: dict[str, Any], state: str) -> dict[str, Any]:
    """`close`'s reply, naming what it left waiting."""
    return core.after_close(STATE.drafts, reply, state=state)


def scratch() -> str:
    """The session's scratch, which a recipe writes as `${state}`."""
    return str(STATE.scratch) if STATE.scratch is not None else ""
