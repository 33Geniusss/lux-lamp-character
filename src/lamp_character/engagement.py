"""Face-cue fusion and temporal filtering for local engagement detection."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Sequence


RIGHT_IRIS = range(468, 473)
LEFT_IRIS = range(473, 478)


@dataclass(frozen=True)
class FaceObservation:
    face_detected: bool
    head_yaw_deg: float = 0.0
    head_pitch_deg: float = 0.0
    iris_offset: float = 0.0
    eye_openness: float = 0.0
    face_area: float = 0.0
    raw_engaged: bool = False
    reason: str = "No face"


@dataclass(frozen=True)
class EngagementDecision:
    observation: FaceObservation
    engaged: bool
    phase: str
    candidate_seconds: float
    away_seconds: float
    transition: str | None = None


def head_angles_from_matrix(matrix: Sequence[Sequence[float]]) -> tuple[float, float]:
    """Return approximate yaw and pitch in degrees from a 4x4 pose matrix."""

    yaw = math.degrees(math.atan2(float(matrix[0][2]), float(matrix[2][2])))
    pitch = math.degrees(
        math.atan2(
            -float(matrix[1][2]),
            math.hypot(float(matrix[1][0]), float(matrix[1][1])),
        )
    )
    return yaw, pitch


def _point(landmarks: Sequence[Any], index: int) -> tuple[float, float]:
    item = landmarks[index]
    return float(item.x), float(item.y)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _eye_openness(
    landmarks: Sequence[Any],
    corner_indices: tuple[int, int],
    lid_indices: tuple[int, int],
) -> float:
    width = _distance(_point(landmarks, corner_indices[0]), _point(landmarks, corner_indices[1]))
    if width < 1e-6:
        return 0.0
    height = _distance(_point(landmarks, lid_indices[0]), _point(landmarks, lid_indices[1]))
    return height / width


def _iris_horizontal_offset(
    landmarks: Sequence[Any], iris_indices: range, corner_indices: tuple[int, int]
) -> float:
    iris_x = sum(_point(landmarks, index)[0] for index in iris_indices) / len(iris_indices)
    corner_x = [_point(landmarks, index)[0] for index in corner_indices]
    left_x, right_x = min(corner_x), max(corner_x)
    width = right_x - left_x
    if width < 1e-6:
        return 1.0
    return (iris_x - left_x) / width - 0.5


def analyze_face_result(
    result: Any,
    *,
    max_yaw: float = 23.0,
    max_pitch: float = 18.0,
    max_iris_offset: float = 0.20,
    min_eye_openness: float = 0.10,
    min_face_area: float = 0.018,
) -> FaceObservation:
    """Fuse face pose, iris position, eye openness, and apparent face size."""

    faces = getattr(result, "face_landmarks", None) or []
    if not faces:
        return FaceObservation(face_detected=False)

    landmarks = faces[0]
    xs = [float(point.x) for point in landmarks]
    ys = [float(point.y) for point in landmarks]
    face_area = max(0.0, (max(xs) - min(xs)) * (max(ys) - min(ys)))

    matrices = getattr(result, "facial_transformation_matrixes", None) or []
    yaw = pitch = 0.0
    if matrices:
        yaw, pitch = head_angles_from_matrix(matrices[0])

    # The refined face mesh has 478 points. If the iris refinement is missing,
    # pose remains useful but we conservatively avoid claiming engagement.
    if len(landmarks) < 478:
        return FaceObservation(
            face_detected=True,
            head_yaw_deg=yaw,
            head_pitch_deg=pitch,
            face_area=face_area,
            reason="Iris landmarks unavailable",
        )

    right_iris = _iris_horizontal_offset(landmarks, RIGHT_IRIS, (33, 133))
    left_iris = _iris_horizontal_offset(landmarks, LEFT_IRIS, (362, 263))
    iris_offset = (right_iris + left_iris) / 2.0
    openness = (
        _eye_openness(landmarks, (33, 133), (159, 145))
        + _eye_openness(landmarks, (362, 263), (386, 374))
    ) / 2.0

    if face_area < min_face_area:
        reason = "Move closer"
    elif openness < min_eye_openness:
        reason = "Eyes closed"
    elif abs(yaw) > max_yaw or abs(pitch) > max_pitch:
        reason = "Turn toward camera"
    elif abs(iris_offset) > max_iris_offset:
        reason = "Look toward camera"
    else:
        reason = "Attending"

    raw_engaged = reason == "Attending"
    return FaceObservation(
        face_detected=True,
        head_yaw_deg=yaw,
        head_pitch_deg=pitch,
        iris_offset=iris_offset,
        eye_openness=openness,
        face_area=face_area,
        raw_engaged=raw_engaged,
        reason=reason,
    )


class EngagementStateMachine:
    """Debounce noisy frame-level cues with asymmetric enter/exit delays."""

    def __init__(self, enter_delay: float = 0.7, exit_delay: float = 3.0) -> None:
        self.enter_delay = enter_delay
        self.exit_delay = exit_delay
        self.engaged = False
        self._candidate_seconds = 0.0
        self._away_seconds = 0.0
        self._last_time: float | None = None

    def update(self, observation: FaceObservation, now: float | None = None) -> EngagementDecision:
        current_time = time.monotonic() if now is None else now
        dt = 0.0 if self._last_time is None else max(0.0, min(current_time - self._last_time, 0.25))
        self._last_time = current_time
        transition: str | None = None

        if observation.raw_engaged:
            self._candidate_seconds += dt
            self._away_seconds = 0.0
            if not self.engaged and self._candidate_seconds >= self.enter_delay:
                self.engaged = True
                transition = "engaged"
        else:
            self._away_seconds += dt
            self._candidate_seconds = 0.0
            if self.engaged and self._away_seconds >= self.exit_delay:
                self.engaged = False
                transition = "disengaged"

        if self.engaged:
            phase = "ENGAGED"
        elif observation.raw_engaged:
            phase = "ATTENDING"
        elif observation.face_detected:
            phase = "AWAY"
        else:
            phase = "NO FACE"

        return EngagementDecision(
            observation=observation,
            engaged=self.engaged,
            phase=phase,
            candidate_seconds=self._candidate_seconds,
            away_seconds=self._away_seconds,
            transition=transition,
        )
