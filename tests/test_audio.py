from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from src.lamp_character.audio import (
    CHUNK_FRAMES,
    MUSIC_LOOP,
    SAMPLE_RATE,
    SOUND_EFFECTS,
    CharacterAudioWorker,
    audio_output_smoke_test,
    audio_contract,
)
from src.lamp_character.actions import action_duration
from src.lamp_character.app import GREETING_STAGE_SECONDS, LampWindow


class CharacterAudioTests(unittest.TestCase):
    def test_required_character_cues_are_procedural_pcm(self):
        self.assertEqual(
            set(SOUND_EFFECTS),
            {"engage", "greet", "success", "error", "disengage"},
        )
        for samples in SOUND_EFFECTS.values():
            self.assertEqual(samples.dtype, np.float32)
            self.assertGreater(len(samples), round(SAMPLE_RATE * 0.25))
            self.assertTrue(np.isfinite(samples).all())
            self.assertGreater(float(np.abs(samples).max()), 0.02)
            self.assertLessEqual(float(np.abs(samples).max()), 0.35)

    def test_music_loop_is_quiet_nonempty_and_four_seconds_long(self):
        self.assertEqual(MUSIC_LOOP.dtype, np.float32)
        self.assertEqual(len(MUSIC_LOOP), SAMPLE_RATE * 4)
        self.assertTrue(np.isfinite(MUSIC_LOOP).all())
        self.assertGreater(float(MUSIC_LOOP.std()), 0.01)
        self.assertLessEqual(float(np.abs(MUSIC_LOOP).max()), 0.28)
        self.assertEqual(audio_contract()["music_loop"], 4.0)

    def test_unknown_sound_effect_is_rejected_before_playback(self):
        worker = CharacterAudioWorker()
        with self.assertRaisesRegex(ValueError, "Unknown character sound effect"):
            worker.play_cue("not-a-cue")
        worker.shutdown()

    def test_greeting_stage_covers_motion_and_complete_cue(self):
        self.assertGreater(GREETING_STAGE_SECONDS, action_duration("greet"))
        self.assertGreater(GREETING_STAGE_SECONDS, audio_contract()["greet"])

    def test_listening_action_mutes_music_and_sound_effects(self):
        worker = mock.Mock()
        host = SimpleNamespace(character_audio_worker=worker)

        LampWindow._play_character_audio_for_action(host, "listen")

        worker.set_music_active.assert_called_once_with(False)
        worker.set_suspended.assert_called_once_with(True)
        worker.play_cue.assert_not_called()

    def test_output_smoke_test_uses_low_latency_chunks(self):
        stream = mock.Mock()
        stream_context = mock.MagicMock()
        stream_context.__enter__.return_value = stream

        with (
            mock.patch(
                "src.lamp_character.audio.sd.query_devices",
                return_value={"name": "test output"},
            ),
            mock.patch(
                "src.lamp_character.audio.sd.OutputStream",
                return_value=stream_context,
            ) as output_stream,
        ):
            self.assertEqual(audio_output_smoke_test(), 0)

        output_stream.assert_called_once_with(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=None,
            blocksize=CHUNK_FRAMES,
            latency="low",
        )
        self.assertGreater(stream.write.call_count, 0)


if __name__ == "__main__":
    unittest.main()
