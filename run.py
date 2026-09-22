"""Convenience launcher that works without installing the package."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from lamp_character.platform_audio import configure_wsl_portaudio  # noqa: E402

configure_wsl_portaudio(ROOT)

from lamp_character.platform_camera import ensure_wsl_camera  # noqa: E402

arguments = set(sys.argv[1:])
camera_free_modes = {
    "-h",
    "--help",
    "--smoke-test",
    "--speech-smoke-test",
    "--audio-output-smoke-test",
    "--screenshot",
    "--no-camera",
}
if "--camera-smoke-test" in arguments or not arguments.intersection(camera_free_modes):
    ensure_wsl_camera(ROOT)

from lamp_character.app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
