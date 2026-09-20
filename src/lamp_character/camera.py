"""Local webcam capture and MediaPipe engagement inference worker."""

from __future__ import annotations

from pathlib import Path
import sys
import time

import cv2
import mediapipe as mp
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .engagement import EngagementDecision, EngagementStateMachine, analyze_face_result


STATUS_COLORS = {
    "ENGAGED": (66, 210, 135),
    "ATTENDING": (61, 188, 255),
    "AWAY": (70, 155, 255),
    "NO FACE": (135, 145, 158),
}


def _create_landmarker(model_path: Path):
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_facial_transformation_matrixes=True,
    )
    return mp.tasks.vision.FaceLandmarker.create_from_options(options)


def _open_camera(index: int):
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    capture = cv2.VideoCapture(index, backend)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def _draw_overlay(frame, result, decision: EngagementDecision) -> None:
    height, width = frame.shape[:2]
    observation = decision.observation
    color = STATUS_COLORS[decision.phase]
    cv2.rectangle(frame, (0, 0), (width - 1, height - 1), color, 5)

    if observation.face_detected and result.face_landmarks:
        landmarks = result.face_landmarks[0]
        xs = [point.x for point in landmarks]
        ys = [point.y for point in landmarks]
        left = max(0, int(min(xs) * width))
        top = max(0, int(min(ys) * height))
        right = min(width - 1, int(max(xs) * width))
        bottom = min(height - 1, int(max(ys) * height))
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        if len(landmarks) >= 478:
            for indices in (range(468, 473), range(473, 478)):
                center_x = int(sum(landmarks[i].x for i in indices) / 5 * width)
                center_y = int(sum(landmarks[i].y for i in indices) / 5 * height)
                cv2.circle(frame, (center_x, center_y), 4, color, -1)

    cv2.rectangle(frame, (12, 12), (236, 96), (18, 23, 30), -1)
    cv2.putText(frame, decision.phase, (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.78, color, 2)
    cv2.putText(
        frame,
        f"yaw {observation.head_yaw_deg:+.0f}  pitch {observation.head_pitch_deg:+.0f}",
        (24, 66),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (220, 225, 232),
        1,
    )
    cv2.putText(
        frame,
        observation.reason,
        (24, 87),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.46,
        (190, 199, 211),
        1,
    )


class CameraWorker(QThread):
    frame_ready = Signal(QImage)
    decision_ready = Signal(object)
    failure = Signal(str)

    def __init__(self, camera_index: int, model_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.camera_index = camera_index
        self.model_path = model_path

    def run(self) -> None:
        capture = None
        landmarker = None
        try:
            if not self.model_path.is_file():
                raise FileNotFoundError(f"Face model not found: {self.model_path}")
            capture = _open_camera(self.camera_index)
            if not capture.isOpened():
                raise RuntimeError(f"Could not open camera index {self.camera_index}")
            landmarker = _create_landmarker(self.model_path)
            state = EngagementStateMachine()
            started = time.monotonic()
            last_timestamp = -1

            while not self.isInterruptionRequested():
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError("Camera stopped returning frames")
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                timestamp = max(last_timestamp + 1, int((time.monotonic() - started) * 1000))
                last_timestamp = timestamp
                result = landmarker.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp
                )
                decision = state.update(analyze_face_result(result))
                _draw_overlay(frame, result, decision)
                shown = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                height, width, channels = shown.shape
                image = QImage(
                    shown.data,
                    width,
                    height,
                    channels * width,
                    QImage.Format.Format_RGB888,
                ).copy()
                self.frame_ready.emit(image)
                self.decision_ready.emit(decision)
        except Exception as error:  # keep the robot UI usable if a camera is unavailable
            self.failure.emit(str(error))
        finally:
            if capture is not None:
                capture.release()
            if landmarker is not None:
                landmarker.close()


def camera_smoke_test(camera_index: int, model_path: Path, seconds: float = 3.0) -> int:
    """Open a real camera and run local inference without saving any frames."""

    capture = _open_camera(camera_index)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open camera index {camera_index}")
    landmarker = _create_landmarker(model_path)
    started = time.monotonic()
    frames = 0
    faces = 0
    resolution = (0, 0)
    try:
        while time.monotonic() - started < seconds:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("Camera stopped returning frames")
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            timestamp = max(frames, int((time.monotonic() - started) * 1000))
            result = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp
            )
            frames += 1
            faces += int(bool(result.face_landmarks))
            resolution = (frame.shape[1], frame.shape[0])
    finally:
        capture.release()
        landmarker.close()
    print(
        f"Camera smoke test passed: index={camera_index}, frames={frames}, "
        f"resolution={resolution[0]}x{resolution[1]}, face_frames={faces}"
    )
    return 0
