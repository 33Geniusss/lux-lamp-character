import unittest
from types import SimpleNamespace
from unittest import mock

from src.lamp_character.app import LampWindow
from src.lamp_character.engagement import (
    EngagementDecision,
    EngagementStateMachine,
    FaceObservation,
    analyze_face_result,
    head_angles_from_matrix,
)


def synthetic_result(iris_shift: float = 0.0):
    points = [SimpleNamespace(x=0.5, y=0.5, z=0.0) for _ in range(478)]
    points[0] = SimpleNamespace(x=0.35, y=0.30, z=0.0)
    points[1] = SimpleNamespace(x=0.65, y=0.70, z=0.0)
    points[33] = SimpleNamespace(x=0.40, y=0.45, z=0.0)
    points[133] = SimpleNamespace(x=0.48, y=0.45, z=0.0)
    points[159] = SimpleNamespace(x=0.44, y=0.44, z=0.0)
    points[145] = SimpleNamespace(x=0.44, y=0.46, z=0.0)
    points[362] = SimpleNamespace(x=0.52, y=0.45, z=0.0)
    points[263] = SimpleNamespace(x=0.60, y=0.45, z=0.0)
    points[386] = SimpleNamespace(x=0.56, y=0.44, z=0.0)
    points[374] = SimpleNamespace(x=0.56, y=0.46, z=0.0)
    for index in range(468, 473):
        points[index] = SimpleNamespace(x=0.44 + iris_shift, y=0.45, z=0.0)
    for index in range(473, 478):
        points[index] = SimpleNamespace(x=0.56 + iris_shift, y=0.45, z=0.0)
    identity = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    return SimpleNamespace(
        face_landmarks=[points], facial_transformation_matrixes=[identity]
    )


class EngagementTests(unittest.TestCase):
    def test_head_angles_match_near_identity_reference(self):
        matrix = [
            [0.9995292, -0.01294756, 0.038823195, -0.3691378],
            [0.0072318, 0.9937692, -0.1101321, 22.75809],
            [-0.0371553, 0.1107059, 0.99315894, -65.765925],
            [0.0, 0.0, 0.0, 1.0],
        ]
        yaw, pitch = head_angles_from_matrix(matrix)
        self.assertAlmostEqual(yaw, 2.24, delta=0.2)
        self.assertAlmostEqual(pitch, 6.32, delta=0.2)

    def test_centered_open_eyes_are_attending(self):
        observation = analyze_face_result(synthetic_result())
        self.assertTrue(observation.raw_engaged)
        self.assertEqual(observation.reason, "Attending")
        self.assertAlmostEqual(observation.iris_offset, 0.0, delta=0.01)

    def test_shifted_irises_are_not_attending(self):
        observation = analyze_face_result(synthetic_result(iris_shift=0.025))
        self.assertFalse(observation.raw_engaged)
        self.assertEqual(observation.reason, "Look toward camera")

    def test_hysteresis_enters_and_exits(self):
        state = EngagementStateMachine(enter_delay=0.7, exit_delay=3.0)
        attending = FaceObservation(face_detected=True, raw_engaged=True, reason="Attending")
        away = FaceObservation(face_detected=True, raw_engaged=False, reason="Turn toward camera")
        transitions = []
        for step in range(5):
            transitions.append(state.update(attending, now=step * 0.2).transition)
        self.assertIn("engaged", transitions)
        self.assertTrue(state.engaged)
        for step in range(1, 12):
            decision = state.update(away, now=0.8 + step * 0.25)
        self.assertIsNone(decision.transition)
        self.assertTrue(state.engaged)
        decision = state.update(away, now=3.8)
        self.assertEqual(decision.transition, "disengaged")
        self.assertFalse(state.engaged)

    def test_default_exit_delay_is_three_seconds(self):
        self.assertEqual(EngagementStateMachine().exit_delay, 3.0)

    def test_turn_lock_defers_camera_state_without_changing_character(self):
        observation = FaceObservation(
            face_detected=True,
            raw_engaged=False,
            reason="Turn toward camera",
        )
        decision = EngagementDecision(
            observation=observation,
            engaged=False,
            phase="AWAY",
            candidate_seconds=0.0,
            away_seconds=3.0,
            transition="disengaged",
        )
        host = SimpleNamespace(
            _engagement_locked=True,
            _deferred_engagement_decision=None,
            metrics_label=mock.Mock(),
            engagement_label=mock.Mock(),
            _apply_engagement_decision=mock.Mock(),
        )

        LampWindow._on_engagement_decision(host, decision)

        self.assertIs(host._deferred_engagement_decision, decision)
        host._apply_engagement_decision.assert_not_called()
        self.assertIn(
            "TURN LOCK",
            host.engagement_label.setText.call_args.args[0],
        )

    def test_releasing_turn_lock_applies_latest_deferred_state(self):
        decision = mock.Mock()
        host = SimpleNamespace(
            _engagement_locked=True,
            _deferred_engagement_decision=decision,
            _apply_engagement_decision=mock.Mock(),
        )

        LampWindow._release_engagement_lock(host)

        self.assertFalse(host._engagement_locked)
        self.assertIsNone(host._deferred_engagement_decision)
        host._apply_engagement_decision.assert_called_once_with(decision)

    def test_completed_reply_does_not_reopen_mic_after_deferred_disengagement(self):
        auto_actions = mock.Mock()
        auto_actions.isChecked.return_value = True
        transcript_label = mock.Mock()
        transcript_label.text.return_value = 'You: "hello"'
        host = SimpleNamespace(
            transcript_label=transcript_label,
            _pending_reply="Hello there.",
            _release_engagement_lock=mock.Mock(),
            auto_actions=auto_actions,
            _engaged=False,
            speech_status_label=mock.Mock(),
            listen_button=mock.Mock(),
            speech_enabled=True,
            play_action=mock.Mock(),
            _resume_character_audio=mock.Mock(),
            _reply_cue="success",
        )

        LampWindow._on_reply_finished(host)

        host.play_action.assert_not_called()
        host._resume_character_audio.assert_not_called()
        host.speech_status_label.setText.assert_called_once_with(
            "READY · WAITING FOR ENGAGEMENT"
        )
        host.listen_button.setEnabled.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
