import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.lamp_character.memory import (
    MemoryStore,
    SceneMemory,
    SessionMemory,
    normalize_memory_update,
)


class MemoryStoreTests(unittest.TestCase):
    def test_missing_file_is_created_and_loadable(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            memory = MemoryStore(path).load()
            self.assertTrue(path.exists())
            self.assertEqual(memory.turn_count, 0)
            self.assertEqual(MemoryStore(path).load(), memory)

    def test_replace_round_trip_leaves_no_temporary_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            store = MemoryStore(path)
            memory = SessionMemory.empty().model_copy(
                update={"conversation_summary": "The user likes blue lamps."}
            )
            store.replace(memory)
            self.assertEqual(store.load(), memory)
            self.assertFalse(path.with_name("memory.json.tmp").exists())

    def test_reset_discards_previous_session(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            store = MemoryStore(path)
            previous = SessionMemory.empty().model_copy(
                update={
                    "conversation_summary": "A conversation from an earlier run.",
                    "turn_count": 7,
                }
            )
            store.replace(previous)

            reset_memory = store.reset()

            self.assertEqual(reset_memory.conversation_summary, "No conversation yet.")
            self.assertEqual(reset_memory.scene_memories, [])
            self.assertEqual(reset_memory.turn_count, 0)
            self.assertNotEqual(reset_memory.session_id, previous.session_id)
            self.assertEqual(store.load(), reset_memory)

    def test_invalid_json_is_not_silently_overwritten(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                MemoryStore(path).load()
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


class MemoryNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.old_scene = SceneMemory(
            observation_id="obs-old",
            observed_at="2026-09-14T10:00:00+00:00",
            description="A red mug is on the desk.",
            objects=["red mug", "desk"],
        )
        self.previous = SessionMemory(
            session_id="stable-session",
            conversation_summary="Old summary.",
            scene_memories=[self.old_scene],
            turn_count=4,
            updated_at="2026-09-14T10:00:00+00:00",
        )

    def test_no_image_cannot_change_scene_memory_or_app_metadata(self):
        invented = SceneMemory(
            observation_id="invented",
            observed_at="tomorrow",
            description="Invented scene.",
        )
        proposed = SessionMemory(
            version=99,
            session_id="changed-by-model",
            conversation_summary="New summary.",
            scene_memories=[invented],
            turn_count=999,
            updated_at="changed",
        )
        normalized = normalize_memory_update(self.previous, proposed, False)
        self.assertEqual(normalized.scene_memories, [self.old_scene])
        self.assertEqual(normalized.session_id, "stable-session")
        self.assertEqual(normalized.version, 1)
        self.assertEqual(normalized.turn_count, 5)
        self.assertEqual(normalized.conversation_summary, "New summary.")

    def test_image_update_merges_new_scene_without_losing_old_scene(self):
        new_scene = SceneMemory(
            observation_id="obs-new",
            observed_at="2026-09-14T11:00:00+00:00",
            description="A blue book is visible.",
            objects=["blue book"],
        )
        proposed = self.previous.model_copy(
            update={
                "conversation_summary": "The user showed Lux a blue book.",
                "scene_memories": [new_scene],
            }
        )
        normalized = normalize_memory_update(
            self.previous,
            proposed,
            True,
            observation_id="obs-new",
            captured_at="2026-09-14T11:00:00+00:00",
        )
        self.assertEqual(
            [scene.observation_id for scene in normalized.scene_memories],
            ["obs-old", "obs-new"],
        )

    def test_image_update_rejects_unrelated_observation_ids(self):
        invented = SceneMemory(
            observation_id="not-the-current-frame",
            observed_at="tomorrow",
            description="Invented scene.",
        )
        proposed = self.previous.model_copy(
            update={"conversation_summary": "New summary.", "scene_memories": [invented]}
        )
        normalized = normalize_memory_update(
            self.previous,
            proposed,
            True,
            observation_id="obs-current",
            captured_at="2026-09-14T11:00:00+00:00",
        )
        self.assertEqual(normalized.scene_memories, [self.old_scene])


if __name__ == "__main__":
    unittest.main()
