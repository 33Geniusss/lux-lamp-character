import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest import mock

from src.lamp_character.actions import MotionLabel
from src.lamp_character.app import LampWindow
from src.lamp_character.language import (
    FOLLOW_UP_OBSERVATION_INSTRUCTIONS,
    FollowUpObservationRequest,
    FollowUpObservationWorker,
    ObservationDecision,
    api_key_configured,
    clean_reply,
    generate_follow_up_observation_turn,
    generate_model_turn,
    LanguageModelWorker,
    SYSTEM_INSTRUCTIONS,
    validate_follow_up_observation_result,
    validate_initial_decision,
)
from src.lamp_character.memory import (
    FollowUpObservationTurn,
    MemoryStore,
    ModelTurn,
    SessionMemory,
)


class FakeResponses:
    def __init__(self, result):
        self.arguments = None
        self.result = result

    def parse(self, **kwargs):
        self.arguments = kwargs
        return SimpleNamespace(output_parsed=self.result)


class LanguageModelTests(unittest.TestCase):
    def setUp(self):
        self.memory = SessionMemory(
            session_id="test-session",
            conversation_summary="The user introduced themself as Sam.",
            updated_at="2026-09-14T00:00:00+00:00",
        )
        self.result = ModelTurn(
            reply='  "I hear you, and I am ready to help."  ',
            motion_labels=[MotionLabel.NOD_YES],
            updated_memory=self.memory.model_copy(
                update={"conversation_summary": "Sam said hello; Lux welcomed Sam."}
            ),
        )
        self.follow_up_observation_request = FollowUpObservationRequest(
            transcript="look at the bottle on my left",
            decision_history=(
                ObservationDecision(
                    observation_number=1,
                    planning_reply="I will look left, then check the new view.",
                    motion_labels=("inspect_left",),
                ),
            ),
            next_observation_number=2,
        )
        self.follow_up_observation_result = FollowUpObservationTurn(
            reply="Yes, I can see the bottle.",
            motion_labels=[MotionLabel.NOD_YES],
            updated_memory=self.memory.model_copy(
                update={"conversation_summary": "Lux found the bottle."}
            ),
        )
        self.image = "data:image/png;base64,abc"
        self.observation_id = "obs-1"
        self.captured_at = "2026-09-14T12:00:00+00:00"

    def test_turn_uses_structured_output_and_sends_complete_json(self):
        responses = FakeResponses(self.result)
        client = SimpleNamespace(responses=responses)

        turn = generate_model_turn(
            client,
            "hello",
            self.memory,
            "test-model",
            self.image,
            self.observation_id,
            self.captured_at,
        )

        self.assertEqual(turn.reply, "I hear you, and I am ready to help.")
        self.assertEqual(turn.motion_labels, [MotionLabel.NOD_YES])
        arguments = responses.arguments
        self.assertEqual(arguments["model"], "test-model")
        self.assertEqual(arguments["reasoning"], {"effort": "none"})
        self.assertIs(arguments["text_format"], ModelTurn)
        self.assertFalse(arguments["store"])
        content = arguments["input"][0]["content"]
        self.assertEqual(len(content), 2)
        payload = json.loads(content[0]["text"])
        self.assertEqual(payload["user_utterance"], "hello")
        self.assertEqual(payload["current_memory"], self.memory.model_dump(mode="json"))
        self.assertTrue(payload["visual_observation"]["image_attached"])
        self.assertEqual(
            payload["visual_observation"]["observation_id"],
            self.observation_id,
        )
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(content[1]["image_url"], self.image)
        self.assertEqual(content[1]["detail"], "low")

    def test_turn_without_camera_frame_is_rejected_before_api_call(self):
        responses = FakeResponses(self.result)
        client = SimpleNamespace(responses=responses)

        with self.assertRaisesRegex(ValueError, "requires a camera frame"):
            generate_model_turn(client, "hello", self.memory)
        self.assertIsNone(responses.arguments)

    def test_fixed_prompt_delegates_scene_memory_decision_to_model(self):
        prompt = " ".join(SYSTEM_INSTRUCTIONS.split())
        self.assertIn("decide whether the user has a new scene-memory need", prompt)
        self.assertIn("Do not create memory merely because an image", prompt)
        self.assertIn("return `scene_memories` unchanged", prompt)
        self.assertIn("Do not include emoji, emoticons, or kaomoji", prompt)
        self.assertIn("Treat these motion labels as tools", prompt)
        self.assertIn("request_another_observation", prompt)
        self.assertIn("does not require a particular target or motion label", prompt)
        self.assertIn("zero or exactly one motion label", prompt)
        self.assertIn("calls you again", prompt)
        self.assertIn("Honor an explicit directional observation goal", prompt)
        self.assertIn("Do not return no motion", prompt)
        self.assertIn("first response must contain only inspect_left", prompt)
        follow_up_prompt = " ".join(FOLLOW_UP_OBSERVATION_INSTRUCTIONS.split())
        self.assertIn("only the new image", follow_up_prompt)
        self.assertIn("zero or exactly one motion label", follow_up_prompt)
        self.assertIn("call you again for the next single motion", follow_up_prompt)
        self.assertIn("does not contain enough usable visual evidence", follow_up_prompt)
        self.assertIn("can_request_another_observation", follow_up_prompt)
        self.assertIn("Consult decision_history", follow_up_prompt)
        self.assertIn("choose nod_yes when the target is visible", follow_up_prompt)

    def test_follow_up_boolean_does_not_constrain_motion_semantics(self):
        planned = ModelTurn(
            reply="I will move, then reconsider the changed scene.",
            motion_labels=[MotionLabel.INSPECT_LEFT],
            request_another_observation=True,
            updated_memory=self.memory,
        )
        self.assertEqual(
            validate_initial_decision(planned),
            ("inspect_left",),
        )

        no_motion_plan = planned.model_copy(update={"motion_labels": []})
        self.assertEqual(validate_initial_decision(no_motion_plan), ())

    def test_structured_replies_allow_at_most_one_motion(self):
        with self.assertRaisesRegex(ValueError, "at most 1 item"):
            ModelTurn(
                reply="I will try two movements.",
                motion_labels=[MotionLabel.INSPECT_LEFT, MotionLabel.NOD_YES],
                request_another_observation=True,
                updated_memory=self.memory,
            )

        with self.assertRaisesRegex(ValueError, "at most 1 item"):
            FollowUpObservationTurn(
                reply="I will try two more movements.",
                motion_labels=[MotionLabel.INSPECT_RIGHT, MotionLabel.SHAKE_NO],
                request_another_observation=True,
                updated_memory=self.memory,
            )

    def test_follow_up_observation_uses_fresh_image_and_decision_history(self):
        responses = FakeResponses(self.follow_up_observation_result)
        client = SimpleNamespace(responses=responses)

        turn = generate_follow_up_observation_turn(
            client,
            self.follow_up_observation_request,
            self.memory,
            "test-model",
            self.image,
            "obs-2",
            "2026-09-14T12:00:03+00:00",
        )

        self.assertEqual(turn.motion_labels, [MotionLabel.NOD_YES])
        arguments = responses.arguments
        self.assertIs(arguments["text_format"], FollowUpObservationTurn)
        self.assertEqual(arguments["reasoning"], {"effort": "none"})
        payload = json.loads(arguments["input"][0]["content"][0]["text"])
        self.assertEqual(
            payload["decision_history"][0]["planning_reply"],
            "I will look left, then check the new view.",
        )
        self.assertEqual(
            payload["decision_history"][0]["motion_labels"],
            ["inspect_left"],
        )
        self.assertEqual(payload["visual_observation"]["observation_id"], "obs-2")
        self.assertEqual(payload["observation_policy"]["observation_number"], 2)
        self.assertEqual(payload["observation_policy"]["maximum_observations"], 3)
        self.assertTrue(
            payload["observation_policy"]["can_request_another_observation"]
        )
        self.assertEqual(arguments["input"][0]["content"][1]["image_url"], self.image)

    def test_waiting_for_follow_up_gpt_response_enters_think_state(self):
        worker = SimpleNamespace(
            reply_ready=mock.Mock(),
            follow_up_observation_required=mock.Mock(),
            failure=mock.Mock(),
            start=mock.Mock(),
        )
        host = SimpleNamespace(
            _pending_observation_request=self.follow_up_observation_request,
            _closing=False,
            _camera_frame_serial=2,
            _follow_up_observation_frame_floor=1,
            _latest_camera_image=object(),
            _camera_image_data_url=mock.Mock(return_value=self.image),
            memory_path=Path("memory.json"),
            language_model="test-model",
            speech_status_label=mock.Mock(),
            play_action=mock.Mock(),
            _on_language_reply=mock.Mock(),
            _on_follow_up_observation_required=mock.Mock(),
            _on_follow_up_observation_failure=mock.Mock(),
            follow_up_observation_worker=None,
        )

        with mock.patch(
            "src.lamp_character.app.FollowUpObservationWorker",
            return_value=worker,
        ):
            LampWindow._capture_follow_up_observation_frame(host, attempt=1)

        host.play_action.assert_called_once_with("think")
        worker.start.assert_called_once_with()

    def test_follow_up_observation_can_choose_any_whitelisted_motion(self):
        result = self.follow_up_observation_result.model_copy(
            update={"motion_labels": [MotionLabel.INSPECT_RIGHT]}
        )
        self.assertEqual(
            validate_follow_up_observation_result(result),
            ("inspect_right",),
        )

    def test_observation_limit_rejects_another_request(self):
        result = self.follow_up_observation_result.model_copy(
            update={"request_another_observation": True}
        )
        with self.assertRaisesRegex(ValueError, "beyond the limit"):
            validate_follow_up_observation_result(
                result,
                can_request_another_observation=False,
            )

    def test_worker_replaces_memory_only_after_valid_structured_reply(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            MemoryStore(path).replace(self.memory)
            client = SimpleNamespace(responses=FakeResponses(self.result))
            worker = LanguageModelWorker(
                "hello",
                path,
                "test-model",
                self.image,
                self.observation_id,
                self.captured_at,
            )

            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), mock.patch(
                "src.lamp_character.language.OpenAI", return_value=client
            ):
                worker.run()

            saved = MemoryStore(path).load()
            self.assertEqual(saved.turn_count, 1)
            self.assertEqual(saved.session_id, "test-session")
            self.assertEqual(saved.conversation_summary, "Sam said hello; Lux welcomed Sam.")

    def test_planning_worker_defers_memory_write_until_follow_up_observation(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            store = MemoryStore(path)
            store.replace(self.memory)
            original = path.read_bytes()
            planned = ModelTurn(
                reply="I will look left and then inspect the new scene.",
                motion_labels=[MotionLabel.INSPECT_LEFT],
                request_another_observation=True,
                updated_memory=self.memory.model_copy(
                    update={"conversation_summary": "This must not be saved yet."}
                ),
            )
            client = SimpleNamespace(responses=FakeResponses(planned))
            worker = LanguageModelWorker(
                self.follow_up_observation_request.transcript,
                path,
                "test-model",
                self.image,
                self.observation_id,
                self.captured_at,
            )
            requests = []
            worker.follow_up_observation_required.connect(
                lambda request, _latency: requests.append(request)
            )

            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), mock.patch(
                "src.lamp_character.language.OpenAI", return_value=client
            ):
                worker.run()

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(requests), 1)
            self.assertEqual(
                requests[0].pending_motion_labels,
                ("inspect_left",),
            )
            self.assertEqual(
                requests[0].decision_history[-1].planning_reply,
                "I will look left and then inspect the new scene.",
            )

    def test_follow_up_worker_can_request_third_image_without_writing_memory(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            store = MemoryStore(path)
            store.replace(self.memory)
            original = path.read_bytes()
            retry_result = self.follow_up_observation_result.model_copy(
                update={
                    "reply": "I still cannot see it, so I will try the other side.",
                    "motion_labels": [MotionLabel.INSPECT_RIGHT],
                    "request_another_observation": True,
                    "updated_memory": self.memory.model_copy(
                        update={"conversation_summary": "Do not save this plan."}
                    ),
                }
            )
            client = SimpleNamespace(responses=FakeResponses(retry_result))
            worker = FollowUpObservationWorker(
                self.follow_up_observation_request,
                path,
                "test-model",
                self.image,
                "obs-2",
                "2026-09-14T12:00:03+00:00",
            )
            requests = []
            worker.follow_up_observation_required.connect(
                lambda request, _latency: requests.append(request)
            )

            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), mock.patch(
                "src.lamp_character.language.OpenAI", return_value=client
            ):
                worker.run()

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(requests), 1)
            retry = requests[0]
            self.assertEqual(retry.next_observation_number, 3)
            self.assertEqual(retry.pending_motion_labels, ("inspect_right",))
            self.assertEqual(len(retry.decision_history), 2)
            self.assertEqual(retry.decision_history[-1].observation_number, 2)

    def test_worker_failure_preserves_existing_memory_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            MemoryStore(path).replace(self.memory)
            original = path.read_bytes()
            responses = mock.Mock()
            responses.parse.side_effect = RuntimeError("simulated API failure")
            client = SimpleNamespace(responses=responses)
            worker = LanguageModelWorker(
                "hello",
                path,
                "test-model",
                self.image,
                self.observation_id,
                self.captured_at,
            )

            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), mock.patch(
                "src.lamp_character.language.OpenAI", return_value=client
            ):
                worker.run()

            self.assertEqual(path.read_bytes(), original)

    def test_follow_up_observation_worker_commits_one_completed_turn(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            MemoryStore(path).replace(self.memory)
            client = SimpleNamespace(
                responses=FakeResponses(self.follow_up_observation_result)
            )
            worker = FollowUpObservationWorker(
                self.follow_up_observation_request,
                path,
                "test-model",
                self.image,
                "obs-2",
                "2026-09-14T12:00:03+00:00",
            )

            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), mock.patch(
                "src.lamp_character.language.OpenAI", return_value=client
            ):
                worker.run()

            saved = MemoryStore(path).load()
            self.assertEqual(saved.turn_count, 1)
            self.assertEqual(saved.session_id, "test-session")
            self.assertEqual(saved.conversation_summary, "Lux found the bottle.")

    def test_empty_reply_is_rejected(self):
        with self.assertRaises(ValueError):
            clean_reply("   ")

    def test_reply_is_not_truncated_to_the_old_240_character_limit(self):
        reply = "A" * 320
        self.assertEqual(clean_reply(reply), reply)

    def test_key_check_does_not_require_exposing_value(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}):
            self.assertTrue(api_key_configured())
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.assertFalse(api_key_configured())


if __name__ == "__main__":
    unittest.main()
