from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from src.lamp_character import platform_audio


class WslAudioBootstrapTests(unittest.TestCase):
    def test_wsl_restarts_with_project_local_portaudio(self):
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            library_dir = project_root / ".tools" / "portaudio-pulse" / "lib"
            library_dir.mkdir(parents=True)
            (library_dir / "libportaudio.so.2").write_bytes(b"test")

            with (
                mock.patch.object(platform_audio.sys, "platform", "linux"),
                mock.patch.dict(
                    os.environ,
                    {"WSL_DISTRO_NAME": "Ubuntu-24.04"},
                    clear=True,
                ),
                mock.patch.object(platform_audio.os, "execvpe") as execute,
            ):
                restarted = platform_audio.configure_wsl_portaudio(project_root)

        self.assertTrue(restarted)
        environment = execute.call_args.args[2]
        self.assertEqual(environment["LD_LIBRARY_PATH"], str(library_dir))
        self.assertEqual(environment["LUX_WSL_PORTAUDIO_READY"], "1")

    def test_missing_local_library_keeps_current_process(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(platform_audio.sys, "platform", "linux"),
            mock.patch.dict(
                os.environ,
                {"WSL_DISTRO_NAME": "Ubuntu-24.04"},
                clear=True,
            ),
            mock.patch.object(platform_audio.os, "execvpe") as execute,
        ):
            restarted = platform_audio.configure_wsl_portaudio(Path(directory))

        self.assertFalse(restarted)
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
