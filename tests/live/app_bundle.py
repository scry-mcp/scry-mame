"""A minimal `.app` around a build, its executable `launcher.c`."""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

SOURCE = Path(__file__).resolve().with_name("launcher.c")
LAUNCHER = "scry-launch"


def build(source: Path, dest: Path, *, name: str = "mame", app: str = "ScryMame",
          launcher: bool = True) -> Path:
    """The `.app` under `dest`; `launcher` fronts an emulator that writes beside its cwd."""
    contents = dest / f"{app}.app" / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        link = macos / entry.name
        if not link.is_symlink() and not link.exists():
            link.symlink_to(entry)
    if launcher:
        subprocess.run(["cc", "-O2", "-o", str(macos / LAUNCHER), str(SOURCE),
                        f'-DSCRY_APP_EXEC="{name}"'], check=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleExecutable": LAUNCHER if launcher else name,
        "CFBundleIdentifier": f"local.scry.{app.lower()}",
        "CFBundleName": app, "CFBundlePackageType": "APPL",
        "NSPrincipalClass": "NSApplication",
        "NSAppSleepDisabled": True}))
    return dest / f"{app}.app"


def executable_of(app: Path) -> str:
    """The executable its Info.plist names."""
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    return str(info["CFBundleExecutable"])
