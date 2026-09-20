from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lamp_character.actions import (
    ACTIONS,
    JOINT_LIMITS,
    JOINT_ORDER,
    MODEL_ACTION_NAMES,
    action_duration,
    validate_model_motion_sequence,
)
from lamp_character.simulator import LampSimulator


class ActionContractTests(unittest.TestCase):
    def test_expected_action_vocabulary_is_present(self) -> None:
        self.assertEqual(
            set(ACTIONS),
            {
                "idle",
                "engage",
                "greet",
                "listen",
                "think",
                "answer",
                "disengage",
                "inspect_left",
                "inspect_right",
                "nod_yes",
                "shake_no",
            },
        )

    def test_model_motion_vocabulary_is_restricted(self) -> None:
        self.assertEqual(
            MODEL_ACTION_NAMES,
            {"inspect_left", "inspect_right", "nod_yes", "shake_no"},
        )
        self.assertEqual(
            validate_model_motion_sequence(["inspect_left"]),
            ("inspect_left",),
        )
        with self.assertRaises(ValueError):
            validate_model_motion_sequence(["greet"])
        with self.assertRaisesRegex(ValueError, "more than one motion"):
            validate_model_motion_sequence(["inspect_left", "inspect_right"])
        with self.assertRaisesRegex(ValueError, "more than one motion"):
            validate_model_motion_sequence(["nod_yes", "nod_yes"])

    def test_model_motion_labels_have_distinct_fixed_joint_behaviors(self) -> None:
        left_pose = ACTIONS["inspect_left"].keyframes[1].pose
        right_pose = ACTIONS["inspect_right"].keyframes[1].pose
        self.assertGreater(left_pose["base_yaw_joint"], 0.0)
        self.assertAlmostEqual(
            left_pose["base_yaw_joint"],
            -right_pose["base_yaw_joint"],
        )
        self.assertAlmostEqual(
            left_pose["neck_yaw_joint"],
            -right_pose["neck_yaw_joint"],
        )

        nod_positions = {
            frame.pose["head_pitch_joint"] for frame in ACTIONS["nod_yes"].keyframes
        }
        shake_positions = {
            frame.pose["neck_yaw_joint"] for frame in ACTIONS["shake_no"].keyframes
        }
        self.assertGreaterEqual(len(nod_positions), 4)
        self.assertGreaterEqual(len(shake_positions), 4)

    def test_every_keyframe_is_complete_and_safe(self) -> None:
        for action_name, action in ACTIONS.items():
            self.assertGreater(len(action.keyframes), 0)
            for frame in action.keyframes:
                self.assertGreater(frame.duration, 0.0)
                self.assertEqual(set(frame.pose), set(JOINT_ORDER))
                for name, value in frame.pose.items():
                    lower, upper = JOINT_LIMITS[name]
                    self.assertGreaterEqual(value, lower)
                    self.assertLessEqual(value, upper)
            self.assertGreater(action_duration(action_name), 0.0)

    def test_listening_pose_keeps_a_subtle_sway_after_entry_motion(self) -> None:
        urdf = ROOT / "robot" / "dummy_lamp_5dof.urdf"
        with LampSimulator(urdf) as simulator:
            simulator.play_action("listen")
            for _ in range(16):
                simulator.step(0.1)
            first = dict(simulator.commanded_pose)
            for _ in range(6):
                simulator.step(0.1)
            second = dict(simulator.commanded_pose)

        self.assertGreater(
            abs(second["base_yaw_joint"] - first["base_yaw_joint"]),
            0.001,
        )
        self.assertLessEqual(abs(second["base_yaw_joint"]), 0.0251)
        self.assertLessEqual(abs(second["neck_yaw_joint"]), 0.0451)


if __name__ == "__main__":
    unittest.main()
