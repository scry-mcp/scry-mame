"""`promote`: what this session learned, kept as a candidate and written on approval."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
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
after_export = core.after_export
after_close = core.after_close
kept_line = core.kept_line


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
    """The body of the `promote` tool, on this server's draft."""
    return core.promote(STATE.drafts, dry_run=dry_run, entries=entries, names=names, root=root,
                        starting=core.starting(STATE.drafts, recipe_paths), state=scratch())


def starting() -> list[str]:
    """Where the store is looked for, as core orders it from this server's recipe paths."""
    return core.starting(STATE.drafts, recipe_paths)


def recipe_paths(recipe: Mapping[str, Any]) -> list[str]:
    """A recipe's roms and its binary's folder."""
    parts = str(recipe.get("rompath") or "").split(core.LISTS["rompath"])
    binary = str(recipe.get("binary") or "")
    return [*parts, *([str(Path(binary).parent)] if binary else [])]


def scratch() -> str:
    """The session's scratch, which a recipe writes as `${state}`."""
    return str(STATE.scratch) if STATE.scratch is not None else ""
