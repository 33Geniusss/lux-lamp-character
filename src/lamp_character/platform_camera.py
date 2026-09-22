"""WSL camera attachment bootstrap."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import time


_HARDWARE_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$")


def _video_devices() -> list[Path]:
    return sorted(Path("/dev").glob("video*"))


def ensure_wsl_camera(project_root: Path, wait_seconds: float = 8.0) -> bool:
    """Attach the configured Windows USB camera when a WSL session starts."""

    if not sys.platform.startswith("linux") or "WSL_DISTRO_NAME" not in os.environ:
        return False
    if _video_devices():
        return True

    config_path = project_root / ".tools" / "wsl-camera-hardware-id"
    attach_script = project_root / "scripts" / "attach_wsl_camera.ps1"
    if not config_path.is_file() or not attach_script.is_file():
        return False

    hardware_id = config_path.read_text(encoding="utf-8").strip()
    if not _HARDWARE_ID_PATTERN.fullmatch(hardware_id):
        raise RuntimeError(f"Invalid WSL camera hardware ID in {config_path}")

    converted = subprocess.run(
        ["wslpath", "-w", str(attach_script)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if converted.returncode:
        raise RuntimeError("Could not convert the WSL camera helper path for Windows")
    windows_script = converted.stdout.strip()
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        windows_script,
        "-HardwareId",
        hardware_id,
        "-Distro",
        os.environ["WSL_DISTRO_NAME"],
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Automatic WSL camera attachment failed: {message}")

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _video_devices():
            return True
        time.sleep(0.2)
    raise RuntimeError("The USB camera attached, but no /dev/video device appeared")
