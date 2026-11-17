"""`promote`: what this session learned, kept and written by scry-core's `promote`."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from scry_core import promote as core

from scry_mame import launch
from scry_mame.state import STATE

#: `start`'s arguments a recipe leaves to the run.
RUN_OWN = frozenset({"state_dir", "stub_port", "display", "size", "background", "view",
                     "throttle_from_frame", "boot_lua", "env", "profile"})
#: What a recipe may hold as a path.
PROMOTE_PATHS = launch.START_PATHS
#: What a recipe cannot do without.
NEEDS = ("system",)
SERVER = "mame"


@contextmanager
def launching(profile: str) -> Iterator[None]:
    """A start's launch, from the profile it read ("" for none)."""
    with STATE.drafts.starting(profile=profile, live=lambda: STATE.proc):
        yield


def after_start(reply: dict[str, Any], params: Mapping[str, Any], *,
                block: Mapping[str, Any] | None, defaults: Mapping[str, Any]) -> dict[str, Any]:
    """`start`'s reply with the recipe kept, named by the machine without a profile."""
    return core.after_start(STATE.drafts, reply, params, block=block,
                            guest=str(params.get("system") or ""), defaults=defaults,
                            run_own=RUN_OWN, needs=NEEDS, path_keys=PROMOTE_PATHS)


def after_map(method: str, reply: dict[str, Any]) -> dict[str, Any]:
    """A map's `add`, named by the machine without an entry read."""
    return core.after_map(STATE.drafts, STATE.maps, method, reply,
                          guest=str(STATE.system or ""))


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
