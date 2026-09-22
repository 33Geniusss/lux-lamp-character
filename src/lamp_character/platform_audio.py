"""Platform-specific audio bootstrap helpers."""

from __future__ import annotations

import os
from pathlib import Path
import sys


_WSL_PORTAUDIO_READY = "LUX_WSL_PORTAUDIO_READY"


def configure_wsl_portaudio(project_root: Path) -> bool:
    """Restart with the project-local PulseAudio PortAudio build on WSL."""

    if not sys.platform.startswith("linux") or "WSL_DISTRO_NAME" not in os.environ:
        return False
    if os.environ.get(_WSL_PORTAUDIO_READY) == "1":
        return False

    library_dir = project_root / ".tools" / "portaudio-pulse" / "lib"
    if not (library_dir / "libportaudio.so.2").is_file():
        return False

    environment = os.environ.copy()
    previous_path = environment.get("LD_LIBRARY_PATH", "")
    environment["LD_LIBRARY_PATH"] = (
        f"{library_dir}:{previous_path}" if previous_path else str(library_dir)
    )
    environment[_WSL_PORTAUDIO_READY] = "1"
    launcher = str(Path(sys.argv[0]).resolve())
    os.execvpe(
        sys.executable,
        [sys.executable, launcher, *sys.argv[1:]],
        environment,
    )
    return True
