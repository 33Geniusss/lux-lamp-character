from __future__ import annotations

import unittest
from unittest import mock

from lamp_character import camera


class OpenCameraTests(unittest.TestCase):
    def test_linux_requests_mjpg_before_resolution(self):
        capture = mock.Mock()

        with (
            mock.patch.object(camera.sys, "platform", "linux"),
            mock.patch.object(camera.cv2, "VideoCapture", return_value=capture) as open_camera,
        ):
            result = camera._open_camera(2)

        self.assertIs(result, capture)
        open_camera.assert_called_once_with(2, camera.cv2.CAP_V4L2)
        self.assertEqual(
            capture.set.call_args_list,
            [
                mock.call(
                    camera.cv2.CAP_PROP_FOURCC,
                    camera.cv2.VideoWriter_fourcc(*"MJPG"),
                ),
                mock.call(camera.cv2.CAP_PROP_FRAME_WIDTH, 640),
                mock.call(camera.cv2.CAP_PROP_FRAME_HEIGHT, 480),
                mock.call(camera.cv2.CAP_PROP_FPS, 30),
                mock.call(camera.cv2.CAP_PROP_BUFFERSIZE, 1),
            ],
        )

    def test_smoke_test_releases_camera_when_open_fails(self):
        capture = mock.Mock()
        capture.isOpened.return_value = False

        with mock.patch.object(camera, "_open_camera", return_value=capture):
            with self.assertRaisesRegex(RuntimeError, "Could not open camera"):
                camera.camera_smoke_test(0, mock.Mock())

        capture.release.assert_called_once_with()

    def test_smoke_test_releases_camera_when_landmarker_creation_fails(self):
        capture = mock.Mock()
        capture.isOpened.return_value = True

        with (
            mock.patch.object(camera, "_open_camera", return_value=capture),
            mock.patch.object(
                camera,
                "_create_landmarker",
                side_effect=RuntimeError("bad model"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "bad model"):
                camera.camera_smoke_test(0, mock.Mock())

        capture.release.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
