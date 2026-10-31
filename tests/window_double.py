"""A window host whose emulator opens its window where its argv says."""

from __future__ import annotations

from scry_core.window import Display, Seen
from server_support import _StubProcess

from scry_mame.state import STATE

DISPLAYS = [Display(0, (0, 0, 1920, 1080)), Display(1, (1920, 0, 1920, 1080))]


class ObeyingHost:
    def displays(self) -> list[Display]:
        return list(DISPLAYS)

    def windows(self) -> list[Seen]:
        argv = _StubProcess.last_argv
        if STATE.proc is None or "-screen0" not in argv:
            return []
        index = int(argv[argv.index("-screen0") + 1].removeprefix("screen"))
        x, y, width, height = DISPLAYS[index].bounds
        bounds = (x, y, width, height) if "-nowindow" in argv else (x + 100, y + 100, 640, 480)
        return [Seen(pid=STATE.proc.pid, number=1, bounds=bounds, onscreen=True)]

    def above(self, window: Seen) -> list[Seen]:
        return []

    def activate(self, window: Seen) -> str:
        return ""


class Absent(ObeyingHost):
    """No window is ever listed."""

    def windows(self) -> list[Seen]:
        return []


class Covered(ObeyingHost):
    """Off screen until activated."""

    def __init__(self) -> None:
        self.activations = 0

    def windows(self) -> list[Seen]:
        return [Seen(w.pid, w.number, w.bounds, self.activations > 0) for w in super().windows()]

    def activate(self, window: Seen) -> str:
        self.activations += 1
        return ""


class Dragged(ObeyingHost):
    """The owner dragged the window to the other display after it opened."""

    def windows(self) -> list[Seen]:
        x, y, width, height = DISPLAYS[1].bounds
        return [Seen(w.pid, w.number, (x + 100, y + 100, 640, 480), True)
                for w in super().windows()]


class Stuck(ObeyingHost):
    """Listed but never shown, whatever is done to bring it forward."""

    def windows(self) -> list[Seen]:
        return [Seen(w.pid, w.number, w.bounds, False) for w in super().windows()]
