from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
import wave

import numpy as np

from src.lamp_character.app import LampWindow
from src.lamp_character.speech import (
    DEFAULT_TRANSCRIPTION_MODEL,
    DEFAULT_TTS_VOICE,
    KOKORO_SAMPLE_RATE,
    NoSpeechDetected,
    SpeechModelWarmupWorker,
    SpeechWorker,
    VoiceReplyWorker,
    _EnergyEndpointDetector,
    _play_float_audio,
    _play_wav_bytes,
    iter_kokoro_audio,
    load_transcription_model,
    pcm16_to_wav,
    transcribe_speech_wav,
)


class FakeKokoroPipeline:
    def __init__(self):
        self.arguments = None

    def __call__(self, text, **kwargs):
        self.arguments = {"text": text, **kwargs}
        return iter(
            [
                SimpleNamespace(audio=np.array([0.1, -0.1], dtype=np.float32)),
                SimpleNamespace(audio=np.array([0.2], dtype=np.float32)),
            ]
        )


class FakeWhisperModel:
    def __init__(self, text="hello lamp"):
        self.arguments = None
        self.audio_data = b""
        self.text = text

    def transcribe(self, audio_file, **kwargs):
        self.arguments = kwargs
        self.audio_data = audio_file.read()
        segment = mock.Mock(text=self.text)
        return iter([segment] if self.text else []), mock.Mock(language="en")


class TranscriptionTests(unittest.TestCase):
    def test_endpoint_detector_finishes_after_speech_in_loud_room_noise(self):
        detector = _EnergyEndpointDetector(
            0.1,
            [1396.0, 1517.0, 1699.0, 1480.0, 1600.0, 1420.0],
        )

        for rms in [1500.0, 1650.0, 1450.0, 1750.0]:
            self.assertFalse(detector.observe(rms))
        self.assertFalse(detector.speech_started)

        for rms in [3600.0, 4100.0, 3300.0, 3900.0]:
            self.assertFalse(detector.observe(rms))
        self.assertTrue(detector.speech_started)

        self.assertEqual(detector.trailing_silence_blocks, 20)
        for _ in range(detector.trailing_silence_blocks - 1):
            self.assertFalse(detector.observe(detector.noise_floor))
        self.assertTrue(detector.observe(detector.noise_floor))

    def test_endpoint_detector_does_not_end_during_a_short_pause(self):
        detector = _EnergyEndpointDetector(
            0.1,
            [45.0, 50.0, 42.0, 48.0, 51.0, 46.0],
        )

        detector.observe(420.0)
        detector.observe(460.0)
        detector.observe(380.0)
        for _ in range(5):
            self.assertFalse(detector.observe(50.0))
        self.assertFalse(detector.observe(400.0))
        self.assertFalse(detector.observe(430.0))

    def test_resumed_speech_restarts_the_two_second_silence_window(self):
        detector = _EnergyEndpointDetector(
            0.1,
            [45.0, 50.0, 42.0, 48.0, 51.0, 46.0],
        )
        for rms in [420.0, 460.0, 380.0]:
            self.assertFalse(detector.observe(rms))

        for _ in range(detector.trailing_silence_blocks - 1):
            self.assertFalse(detector.observe(50.0))
        self.assertFalse(detector.observe(430.0))
        for _ in range(detector.trailing_silence_blocks - 1):
            self.assertFalse(detector.observe(50.0))
        self.assertTrue(detector.observe(50.0))

    def test_pcm_audio_is_wrapped_as_mono_16_bit_wav(self):
        wav_data = pcm16_to_wav(b"\x01\x00" * 1600, 16000)

        with wave.open(BytesIO(wav_data), "rb") as audio:
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getsampwidth(), 2)
            self.assertEqual(audio.getframerate(), 16000)
            self.assertEqual(audio.getnframes(), 1600)

    def test_transcription_uses_local_whisper_and_memory_file(self):
        model = FakeWhisperModel()
        wav_data = pcm16_to_wav(b"\x00\x00" * 800, 16000)

        result = transcribe_speech_wav(model, wav_data)

        self.assertEqual(result, "hello lamp")
        self.assertEqual(model.audio_data, wav_data)
        self.assertEqual(model.arguments["beam_size"], 5)
        self.assertTrue(model.arguments["vad_filter"])
        self.assertFalse(model.arguments["condition_on_previous_text"])

    def test_empty_transcription_is_rejected(self):
        model = FakeWhisperModel(text="")

        with self.assertRaisesRegex(NoSpeechDetected, "returned no speech"):
            transcribe_speech_wav(
                model,
                pcm16_to_wav(b"\x00\x00" * 100, 16000),
            )

    def test_local_model_is_cached_and_uses_project_download_root(self):
        fake_model = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with mock.patch(
                "src.lamp_character.speech.WhisperModel",
                return_value=fake_model,
            ) as constructor:
                with mock.patch.dict(
                    "src.lamp_character.speech._TRANSCRIPTION_MODELS",
                    {},
                    clear=True,
                ):
                    first = load_transcription_model(download_root=cache)
                    second = load_transcription_model(download_root=cache)

        self.assertIs(first, fake_model)
        self.assertIs(second, fake_model)
        constructor.assert_called_once_with(
            DEFAULT_TRANSCRIPTION_MODEL,
            device="cpu",
            compute_type="int8",
            download_root=str(cache.resolve()),
        )

    def test_worker_does_not_require_api_key_for_transcription(self):
        worker = SpeechWorker()
        worker._capture_utterance = mock.Mock(return_value=None)
        failures = []
        worker.failure.connect(failures.append)

        with mock.patch.dict(os.environ, {}, clear=True):
            worker.run()

        worker._capture_utterance.assert_called_once_with()
        self.assertEqual(failures, [])

    def test_worker_captures_then_transcribes_and_emits_text(self):
        model = FakeWhisperModel(text="look at the bottle")
        worker = SpeechWorker()
        worker._capture_utterance = mock.Mock(
            return_value=(b"\x00\x00" * 1600, 16000)
        )
        states = []
        transcripts = []
        worker.transcribing.connect(states.append)
        worker.recognized_text.connect(transcripts.append)

        with mock.patch(
            "src.lamp_character.speech.load_transcription_model",
            return_value=model,
        ):
            worker.run()

        self.assertEqual(states, [DEFAULT_TRANSCRIPTION_MODEL])
        self.assertEqual(transcripts, ["look at the bottle"])

    def test_empty_transcription_uses_no_speech_signal_not_failure(self):
        model = FakeWhisperModel(text="")
        worker = SpeechWorker()
        worker._capture_utterance = mock.Mock(
            return_value=(b"\x00\x00" * 1600, 16000)
        )
        no_speech = []
        failures = []
        worker.no_speech.connect(no_speech.append)
        worker.failure.connect(failures.append)

        with mock.patch(
            "src.lamp_character.speech.load_transcription_model",
            return_value=model,
        ):
            worker.run()

        self.assertEqual(no_speech, ["Local Whisper returned no speech"])
        self.assertEqual(failures, [])


class LocalVoiceTests(unittest.TestCase):
    def test_startup_warmup_loads_whisper_and_runs_silent_kokoro_inference(self):
        pipeline = FakeKokoroPipeline()
        worker = SpeechModelWarmupWorker()
        statuses = []
        ready = []
        failures = []
        worker.status_changed.connect(statuses.append)
        worker.ready.connect(lambda: ready.append(True))
        worker.failure.connect(failures.append)

        with (
            mock.patch(
                "src.lamp_character.speech.load_transcription_model"
            ) as load_whisper,
            mock.patch(
                "src.lamp_character.speech.load_tts_pipeline",
                return_value=pipeline,
            ) as load_kokoro,
        ):
            worker.run()

        load_whisper.assert_called_once_with(DEFAULT_TRANSCRIPTION_MODEL)
        load_kokoro.assert_called_once_with(worker.tts_model)
        self.assertEqual(pipeline.arguments["text"], "Ready.")
        self.assertEqual(pipeline.arguments["voice"], DEFAULT_TTS_VOICE)
        self.assertIn("WARMING · LOCAL KOKORO VOICE", statuses)
        self.assertEqual(ready, [True])
        self.assertEqual(failures, [])

    def test_startup_warmup_can_skip_kokoro_for_system_voice(self):
        worker = SpeechModelWarmupWorker(neural_voice_enabled=False)
        ready = []
        worker.ready.connect(lambda: ready.append(True))

        with (
            mock.patch(
                "src.lamp_character.speech.load_transcription_model"
            ) as load_whisper,
            mock.patch(
                "src.lamp_character.speech.load_tts_pipeline"
            ) as load_kokoro,
        ):
            worker.run()

        load_whisper.assert_called_once_with(DEFAULT_TRANSCRIPTION_MODEL)
        load_kokoro.assert_not_called()
        self.assertEqual(ready, [True])

    def test_kokoro_generation_uses_local_voice_and_returns_float_audio(self):
        pipeline = FakeKokoroPipeline()

        chunks = list(iter_kokoro_audio(pipeline, "  I understand you.  "))

        self.assertEqual(pipeline.arguments["text"], "I understand you.")
        self.assertEqual(pipeline.arguments["voice"], DEFAULT_TTS_VOICE)
        self.assertEqual(pipeline.arguments["speed"], 1.0)
        self.assertEqual([chunk.dtype for chunk in chunks], [np.float32, np.float32])
        np.testing.assert_allclose(chunks[0], [0.1, -0.1])

    def test_empty_kokoro_reply_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty reply"):
            list(iter_kokoro_audio(FakeKokoroPipeline(), "   "))

    def test_voice_worker_loads_kokoro_once_and_plays_all_chunks(self):
        pipeline = FakeKokoroPipeline()
        worker = VoiceReplyWorker("Hello")
        statuses = []
        started = []
        worker.voice_status.connect(statuses.append)
        worker.reply_started.connect(lambda: started.append(True))

        with (
            mock.patch(
                "src.lamp_character.speech.load_tts_pipeline",
                return_value=pipeline,
            ) as load_pipeline,
            mock.patch("src.lamp_character.speech._play_float_audio") as play,
        ):
            worker._speak_neural()

        load_pipeline.assert_called_once_with(worker.tts_model)
        self.assertEqual(play.call_count, 2)
        self.assertEqual(started, [True])
        self.assertEqual(statuses[-1], "SPEAKING · LOCAL KOKORO")

    def test_kokoro_failure_uses_system_voice_fallback(self):
        worker = VoiceReplyWorker("Hello")
        worker._speak_neural = mock.Mock(side_effect=RuntimeError("model unavailable"))
        worker._speak_local = mock.Mock()

        worker.run()

        worker._speak_local.assert_called_once_with()
        self.assertTrue(worker.playback_completed)

    def test_listening_gate_requires_signal_and_completed_worker(self):
        host = SimpleNamespace(
            _closing=False,
            _reply_audio_completed=False,
            reply_worker=SimpleNamespace(playback_completed=True),
            _on_reply_finished=mock.Mock(),
        )

        LampWindow._on_reply_worker_exited(host)
        host._on_reply_finished.assert_not_called()

        host._reply_audio_completed = True
        host.reply_worker.playback_completed = False
        LampWindow._on_reply_worker_exited(host)
        host._on_reply_finished.assert_not_called()

        host.reply_worker.playback_completed = True
        LampWindow._on_reply_worker_exited(host)
        host._on_reply_finished.assert_called_once_with()

    def test_no_speech_during_engagement_schedules_quiet_retry(self):
        auto_actions = mock.Mock()
        auto_actions.isChecked.return_value = True
        host = SimpleNamespace(
            _speech_handled=False,
            _engaged=True,
            auto_actions=auto_actions,
            speech_status_label=mock.Mock(),
            transcript_label=mock.Mock(),
            listen_button=mock.Mock(),
            _retry_listening_after_no_speech=mock.Mock(),
            _resume_character_audio=mock.Mock(),
            speech_enabled=True,
        )

        with mock.patch("src.lamp_character.app.QTimer.singleShot") as single_shot:
            LampWindow._on_speech_no_speech(host, "no speech")

        self.assertTrue(host._speech_handled)
        host.speech_status_label.setText.assert_called_once_with(
            "LISTENING · NO SPEECH, RETRYING"
        )
        host._resume_character_audio.assert_not_called()
        single_shot.assert_called_once_with(
            350, host._retry_listening_after_no_speech
        )

    def test_in_memory_wav_is_decoded_and_written_to_output_stream(self):
        buffer = BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(b"\x00\x00" * 100)
        stream = mock.Mock()
        stream_context = mock.MagicMock()
        stream_context.__enter__.return_value = stream

        with mock.patch(
            "src.lamp_character.speech.sd.OutputStream",
            return_value=stream_context,
        ):
            _play_wav_bytes(buffer.getvalue(), lambda: False)

        stream.write.assert_called_once()

    def test_kokoro_float_audio_is_written_to_output_stream(self):
        stream = mock.Mock()
        stream_context = mock.MagicMock()
        stream_context.__enter__.return_value = stream
        samples = np.array([0.1, -0.1, 0.2], dtype=np.float32)

        with mock.patch(
            "src.lamp_character.speech.sd.OutputStream",
            return_value=stream_context,
        ) as output_stream:
            _play_float_audio(samples, KOKORO_SAMPLE_RATE, lambda: False)

        output_stream.assert_called_once_with(
            samplerate=KOKORO_SAMPLE_RATE,
            channels=1,
            dtype=np.float32,
            blocksize=2048,
            latency="low",
        )
        stream.write.assert_called_once()


class TurnTimingTests(unittest.TestCase):
    def test_gpt_and_tts_wait_times_use_monotonic_stage_timers(self):
        host = SimpleNamespace(
            _gpt_started_at=10.0,
            _tts_started_at=20.0,
            _turn_stage_seconds={"stt": 1.25, "gpt": None, "tts": None},
            _update_turn_timing_display=mock.Mock(),
        )

        with mock.patch(
            "src.lamp_character.app.time.perf_counter",
            side_effect=[12.5, 20.75],
        ):
            LampWindow._finish_gpt_timing(host)
            LampWindow._on_reply_audio_started(host)

        self.assertEqual(host._turn_stage_seconds["gpt"], 2.5)
        self.assertEqual(host._turn_stage_seconds["tts"], 0.75)
        self.assertIsNone(host._gpt_started_at)
        self.assertIsNone(host._tts_started_at)
        self.assertEqual(host._update_turn_timing_display.call_count, 2)

    def test_timing_label_shows_all_three_stages_to_two_decimals(self):
        host = SimpleNamespace(
            _turn_stage_seconds={"stt": 1.234, "gpt": 4.567, "tts": 0.891},
            turn_timing_label=mock.Mock(),
        )

        LampWindow._update_turn_timing_display(host)

        host.turn_timing_label.setText.assert_called_once_with(
            "TIMING · STT 1.23s · GPT 4.57s · TTS 0.89s"
        )


if __name__ == "__main__":
    unittest.main()
