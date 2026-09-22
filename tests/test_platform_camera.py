from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from src.lamp_character import platform_camera


class WslCameraBootstrapTests(unittest.TestCase):
    def test_wsl_attaches_configured_camera_and_waits_for_video_device(self):
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            tools = project_root / ".tools"
            scripts = project_root / "scripts"
            tools.mkdir()
            scripts.mkdir()
            (tools / "wsl-camera-hardware-id").write_text(
                "04f2:b828\n", encoding="utf-8"
            )
            attach_script = scripts / "attach_wsl_camera.ps1"
            attach_script.write_text("test", encoding="utf-8")

            with (
                mock.patch.object(platform_camera.sys, "platform", "linux"),
                mock.patch.dict(
                    os.environ,
                    {"WSL_DISTRO_NAME": "Ubuntu-24.04"},
                    clear=True,
                ),
                mock.patch.object(
                    platform_camera,
                    "_video_devices",
                    side_effect=[[], [], [Path("/dev/video0")]],
                ),
                mock.patch.object(
                    platform_camera.subprocess,
                    "run",
                    side_effect=[
                        SimpleNamespace(
                            returncode=0,
                            stdout="C:\\project\\scripts\\attach_wsl_camera.ps1\n",
                            stderr="",
                        ),
                        SimpleNamespace(returncode=0, stdout="", stderr=""),
                    ],
                ) as run,
                mock.patch.object(platform_camera.time, "sleep"),
            ):
                attached = platform_camera.ensure_wsl_camera(project_root)

        self.assertTrue(attached)
        attach_command = run.call_args_list[1].args[0]
        self.assertIn("04f2:b828", attach_command)
        self.assertIn("Ubuntu-24.04", attach_command)

    def test_missing_camera_configuration_is_a_noop(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(platform_camera.sys, "platform", "linux"),
            mock.patch.dict(
                os.environ,
                {"WSL_DISTRO_NAME": "Ubuntu-24.04"},
                clear=True,
            ),
            mock.patch.object(platform_camera, "_video_devices", return_value=[]),
        ):
            attached = platform_camera.ensure_wsl_camera(Path(directory))

        self.assertFalse(attached)


if __name__ == "__main__":
    unittest.main()
