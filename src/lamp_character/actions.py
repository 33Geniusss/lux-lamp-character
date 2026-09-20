"""Motion vocabulary for the five-degree-of-freedom lamp character.

All values are joint positions in radians and stay inside the limits declared
by ``robot/dummy_lamp_5dof.urdf``.  The motions are intentionally small and
readable: the goal is character animation, not aggressive robot motion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

Color = tuple[float, float, float, float]
Pose = dict[str, float]

JOINT_ORDER = (
    "base_yaw_joint",
    "shoulder_pitch_joint",
    "elbow_pitch_joint",
    "neck_yaw_joint",
    "head_pitch_joint",
)

JOINT_LIMITS: dict[str, tuple[float, float]] = {
    "base_yaw_joint": (-2.600, 2.600),
    "shoulder_pitch_joint": (-0.750, 1.050),
    "elbow_pitch_joint": (-1.850, 0.400),
    "neck_yaw_joint": (-1.350, 1.350),
    "head_pitch_joint": (-0.900, 0.700),
}


class MotionLabel(StrEnum):
    """Only these high-level motions may be selected by the language model."""

    INSPECT_LEFT = "inspect_left"
    INSPECT_RIGHT = "inspect_right"
    NOD_YES = "nod_yes"
    SHAKE_NO = "shake_no"


MODEL_ACTION_NAMES = frozenset(label.value for label in MotionLabel)

HOME_POSE: Pose = {
    "base_yaw_joint": 0.00,
    "shoulder_pitch_joint": 0.38,
    "elbow_pitch_joint": -1.08,
    "neck_yaw_joint": 0.00,
    "head_pitch_joint": -0.18,
}

WARM_DIM: Color = (1.00, 0.72, 0.24, 0.45)
WARM: Color = (1.00, 0.84, 0.42, 1.00)
LISTEN_BLUE: Color = (0.30, 0.68, 1.00, 1.00)
THINK_VIOLET: Color = (0.72, 0.48, 1.00, 1.00)
ANSWER_GREEN: Color = (0.38, 1.00, 0.63, 1.00)


@dataclass(frozen=True)
class Keyframe:
    """A target pose and light state reached over ``duration`` seconds."""

    duration: float
    pose: Pose
    light: Color = WARM


@dataclass(frozen=True)
class Action:
    """A named sequence of expressive lamp keyframes."""

    label: str
    description: str
    keyframes: tuple[Keyframe, ...]
    idle_motion: bool = False


def pose(**updates: float) -> Pose:
    result = dict(HOME_POSE)
    result.update(updates)
    return result


ACTIONS: dict[str, Action] = {
    "idle": Action(
        "Idle",
        "Quiet breathing motion while waiting for engagement.",
        (Keyframe(0.8, pose(), WARM_DIM),),
        idle_motion=True,
    ),
    "engage": Action(
        "Engage",
        "Turns toward a person, rises slightly, and brings the light up.",
        (
            Keyframe(0.65, pose(shoulder_pitch_joint=0.48, elbow_pitch_joint=-0.96), WARM),
            Keyframe(0.35, pose(shoulder_pitch_joint=0.43, elbow_pitch_joint=-1.00, head_pitch_joint=-0.10), WARM),
        ),
    ),
    "greet": Action(
        "Greet",
        "A friendly side-to-side glance followed by a two-beat nod.",
        (
            Keyframe(0.35, pose(base_yaw_joint=-0.22, neck_yaw_joint=0.32, head_pitch_joint=-0.08), WARM),
            Keyframe(0.45, pose(base_yaw_joint=0.22, neck_yaw_joint=-0.30, head_pitch_joint=-0.08), WARM),
            Keyframe(0.28, pose(shoulder_pitch_joint=0.48, elbow_pitch_joint=-0.98, head_pitch_joint=-0.38), WARM),
            Keyframe(0.28, pose(shoulder_pitch_joint=0.40, elbow_pitch_joint=-1.06, head_pitch_joint=0.02), WARM),
            Keyframe(0.45, pose(shoulder_pitch_joint=0.43, elbow_pitch_joint=-1.00, head_pitch_joint=-0.10), WARM),
        ),
    ),
    "listen": Action(
        "Listen",
        "Leans in and aims the head toward the speaker.",
        (
            Keyframe(0.70, pose(shoulder_pitch_joint=0.62, elbow_pitch_joint=-1.24, head_pitch_joint=-0.34), LISTEN_BLUE),
            Keyframe(0.45, pose(shoulder_pitch_joint=0.59, elbow_pitch_joint=-1.20, head_pitch_joint=-0.28), LISTEN_BLUE),
        ),
    ),
    "think": Action(
        "Think",
        "Looks aside with a curious head tilt while considering a response.",
        (
            Keyframe(0.55, pose(base_yaw_joint=-0.18, neck_yaw_joint=0.62, head_pitch_joint=0.20), THINK_VIOLET),
            Keyframe(0.60, pose(base_yaw_joint=0.08, neck_yaw_joint=0.38, head_pitch_joint=0.30), THINK_VIOLET),
            Keyframe(0.45, pose(base_yaw_joint=-0.10, neck_yaw_joint=0.52, head_pitch_joint=0.22), THINK_VIOLET),
        ),
    ),
    "answer": Action(
        "Answer",
        "Returns eye-line to the person and punctuates speech with a nod.",
        (
            Keyframe(0.55, pose(shoulder_pitch_joint=0.46, elbow_pitch_joint=-1.00, head_pitch_joint=-0.08), ANSWER_GREEN),
            Keyframe(0.30, pose(shoulder_pitch_joint=0.51, elbow_pitch_joint=-0.94, head_pitch_joint=-0.32), ANSWER_GREEN),
            Keyframe(0.34, pose(shoulder_pitch_joint=0.43, elbow_pitch_joint=-1.02, head_pitch_joint=-0.06), ANSWER_GREEN),
            Keyframe(0.42, pose(shoulder_pitch_joint=0.46, elbow_pitch_joint=-1.00, head_pitch_joint=-0.14), ANSWER_GREEN),
        ),
    ),
    "disengage": Action(
        "Disengage",
        "Looks away gently, lowers the light, and returns to rest.",
        (
            Keyframe(0.55, pose(base_yaw_joint=0.38, neck_yaw_joint=-0.42, head_pitch_joint=-0.26), WARM_DIM),
            Keyframe(0.90, pose(), WARM_DIM),
        ),
    ),
    MotionLabel.INSPECT_LEFT.value: Action(
        "Inspect left",
        "Turns and leans toward something visible on the left, then returns.",
        (
            Keyframe(
                0.55,
                pose(
                    base_yaw_joint=0.58,
                    shoulder_pitch_joint=0.56,
                    elbow_pitch_joint=-1.18,
                    neck_yaw_joint=0.72,
                    head_pitch_joint=-0.24,
                ),
                LISTEN_BLUE,
            ),
            Keyframe(
                0.55,
                pose(
                    base_yaw_joint=0.72,
                    shoulder_pitch_joint=0.60,
                    elbow_pitch_joint=-1.22,
                    neck_yaw_joint=0.86,
                    head_pitch_joint=-0.34,
                ),
                LISTEN_BLUE,
            ),
            Keyframe(0.55, pose(), WARM),
        ),
    ),
    MotionLabel.INSPECT_RIGHT.value: Action(
        "Inspect right",
        "Turns and leans toward something visible on the right, then returns.",
        (
            Keyframe(
                0.55,
                pose(
                    base_yaw_joint=-0.58,
                    shoulder_pitch_joint=0.56,
                    elbow_pitch_joint=-1.18,
                    neck_yaw_joint=-0.72,
                    head_pitch_joint=-0.24,
                ),
                LISTEN_BLUE,
            ),
            Keyframe(
                0.55,
                pose(
                    base_yaw_joint=-0.72,
                    shoulder_pitch_joint=0.60,
                    elbow_pitch_joint=-1.22,
                    neck_yaw_joint=-0.86,
                    head_pitch_joint=-0.34,
                ),
                LISTEN_BLUE,
            ),
            Keyframe(0.55, pose(), WARM),
        ),
    ),
    MotionLabel.NOD_YES.value: Action(
        "Nod yes",
        "Confirms an affirmative result with two clear, friendly nods.",
        (
            Keyframe(0.28, pose(head_pitch_joint=-0.56), ANSWER_GREEN),
            Keyframe(0.28, pose(head_pitch_joint=0.22), ANSWER_GREEN),
            Keyframe(0.28, pose(head_pitch_joint=-0.52), ANSWER_GREEN),
            Keyframe(0.28, pose(head_pitch_joint=0.14), ANSWER_GREEN),
            Keyframe(0.38, pose(), WARM),
        ),
    ),
    MotionLabel.SHAKE_NO.value: Action(
        "Shake no",
        "Communicates a negative result with a gentle side-to-side shake.",
        (
            Keyframe(0.30, pose(neck_yaw_joint=0.82), WARM),
            Keyframe(0.36, pose(neck_yaw_joint=-0.82), WARM),
            Keyframe(0.36, pose(neck_yaw_joint=0.74), WARM),
            Keyframe(0.36, pose(neck_yaw_joint=-0.64), WARM),
            Keyframe(0.38, pose(), WARM_DIM),
        ),
    ),
}


def action_duration(action_name: str) -> float:
    """Return the fixed playback duration for one validated action."""

    return sum(frame.duration for frame in ACTIONS[action_name].keyframes)


def validate_model_motion_sequence(labels: list[str]) -> tuple[str, ...]:
    """Enforce the application-owned action boundary around model decisions."""

    unknown = set(labels) - MODEL_ACTION_NAMES
    if unknown:
        raise ValueError(f"Unknown model motion labels: {sorted(unknown)}")
    if len(labels) > 1:
        raise ValueError("The language model requested more than one motion")
    return tuple(labels)


def validate_actions() -> None:
    """Raise ``ValueError`` if an action violates the supplied URDF contract."""

    for action_name, action in ACTIONS.items():
        if not action.keyframes:
            raise ValueError(f"{action_name} has no keyframes")
        for frame in action.keyframes:
            if frame.duration <= 0:
                raise ValueError(f"{action_name} contains a non-positive duration")
            if set(frame.pose) != set(JOINT_ORDER):
                raise ValueError(f"{action_name} does not command exactly the five movable joints")
            for joint_name, value in frame.pose.items():
                lower, upper = JOINT_LIMITS[joint_name]
                if not lower <= value <= upper:
                    raise ValueError(
                        f"{action_name}: {joint_name}={value} is outside [{lower}, {upper}]"
                    )


validate_actions()
