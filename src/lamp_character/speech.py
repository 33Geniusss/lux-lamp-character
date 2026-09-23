"""Fully local speech I/O with an operating-system voice fallback."""

from __future__ import annotations

from collections import deque
from io import BytesIO
import math
import os
from pathlib import Path
from threading import Lock
import wave

PROJECT_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(PROJECT_ROOT / "models" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from faster_whisper import WhisperModel
import numpy as np
import pyttsx3
from PySide6.QtCore import QThread, Signal
import sounddevice as sd


DEFAULT_TRANSCRIPTION_MODEL = "small"
DEFAULT_TRANSCRIPTION_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
DEFAULT_TRANSCRIPTION_DEVICE = "cpu"
DEFAULT_TRANSCRIPTION_COMPUTE_TYPE = "int8"
DEFAULT_TRANSCRIPTION_CACHE = PROJECT_ROOT / "models" / "faster-whisper"
DEFAULT_TTS_MODEL = "hexgrad/Kokoro-82M"
DEFAULT_TTS_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
DEFAULT_TTS_VOICE = "af_heart"
DEFAULT_TTS_LANGUAGE = "a"
DEFAULT_TTS_DEVICE = "cpu"
DEFAULT_TTS_SPEED = 1.0
KOKORO_SAMPLE_RATE = 24000
MIC_CALIBRATION_SECONDS = 0.6
UTTERANCE_END_SILENCE_SECONDS = 2.0

_TRANSCRIPTION_MODELS: dict[tuple[str, str, str, str], WhisperModel] = {}
_TRANSCRIPTION_MODEL_LOCK = Lock()
_TTS_PIPELINES: dict[tuple[str, str, str], object] = {}
_TTS_PIPELINE_LOCK = Lock()


class NoSpeechDetected(RuntimeError):
    """The capture contained no usable spoken utterance; retry is safe."""


class _EnergyEndpointDetector:
    """Detect one utterance using a calibrated noise profile and hysteresis."""

    def __init__(self, block_seconds: float, calibration_rms: list[float]) -> None:
        if block_seconds <= 0:
            raise ValueError("Block duration must be positive")
        if not calibration_rms:
            raise ValueError("Microphone calibration must contain audio")

        profile = np.asarray(calibration_rms, dtype=np.float32)
        self.noise_floor = float(np.median(profile))
        self.noise_spread = max(
            1.0,
            float(np.percentile(profile, 90) - np.percentile(profile, 10)),
        )
        self.start_confirm_blocks = max(2, math.ceil(0.15 / block_seconds))
        self.minimum_voiced_blocks = max(2, math.ceil(0.2 / block_seconds))
        self.trailing_silence_blocks = math.ceil(
            UTTERANCE_END_SILENCE_SECONDS / block_seconds
        )
        self.speech_started = False
        self.voiced_blocks = 0
        self._start_candidate_blocks = 0
        self._silence_score = 0.0

    @property
    def start_threshold(self) -> float:
        """Higher threshold used to avoid starting on steady room noise."""

        margin = max(
            120.0,
            self.noise_spread * 1.5,
            self.noise_floor * 0.25,
        )
        return self.noise_floor + margin

    @property
    def silence_threshold(self) -> float:
        """Lower threshold used after speech starts to detect its endpoint."""

        margin = max(
            80.0,
            self.noise_spread,
            self.noise_floor * 0.15,
        )
        return self.noise_floor + margin

    def observe(self, rms: float) -> bool:
        """Consume one energy value; return true once trailing silence wins."""

        if not self.speech_started:
            if rms >= self.start_threshold:
                self._start_candidate_blocks += 1
                if self._start_candidate_blocks >= self.start_confirm_blocks:
                    self.speech_started = True
                    self.voiced_blocks = self._start_candidate_blocks
            else:
                self._start_candidate_blocks = 0
            return False

        if rms >= self.start_threshold:
            self.voiced_blocks += 1
            self._silence_score = 0.0
        elif rms <= self.silence_threshold:
            self._silence_score += 1.0
        else:
            # Borderline background spikes should not erase an otherwise clear
            # run of silence, but they also should not advance it.
            self._silence_score = max(0.0, self._silence_score - 0.25)

        return (
            self.voiced_blocks >= self.minimum_voiced_blocks
            and self._silence_score >= self.trailing_silence_blocks
        )


def pcm16_to_wav(pcm_data: bytes, sample_rate: int) -> bytes:
    """Wrap mono signed 16-bit PCM in an in-memory WAV container."""

    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive")
    if not pcm_data or len(pcm_data) % 2:
        raise ValueError("Expected non-empty 16-bit PCM audio")
    buffer = BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(pcm_data)
    return buffer.getvalue()


def load_transcription_model(
    model_name: str = DEFAULT_TRANSCRIPTION_MODEL,
    device: str = DEFAULT_TRANSCRIPTION_DEVICE,
    compute_type: str = DEFAULT_TRANSCRIPTION_COMPUTE_TYPE,
    download_root: Path = DEFAULT_TRANSCRIPTION_CACHE,
) -> WhisperModel:
    """Load one faster-whisper model per configuration and reuse it."""

    cache_path = Path(download_root).resolve()
    cache_path.mkdir(parents=True, exist_ok=True)
    cache_key = (model_name, device, compute_type, str(cache_path))
    with _TRANSCRIPTION_MODEL_LOCK:
        model = _TRANSCRIPTION_MODELS.get(cache_key)
        if model is None:
            model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                download_root=str(cache_path),
                revision=(
                    DEFAULT_TRANSCRIPTION_REVISION
                    if model_name == DEFAULT_TRANSCRIPTION_MODEL
                    else None
                ),
            )
            _TRANSCRIPTION_MODELS[cache_key] = model
    return model


def transcribe_speech_wav(model, audio_data: bytes) -> str:
    """Transcribe an in-memory WAV utterance with local faster-whisper."""

    segments, _info = model.transcribe(
        BytesIO(audio_data),
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
    )
    text = "".join(str(segment.text) for segment in segments).strip()
    if not text:
        raise NoSpeechDetected("Local Whisper returned no speech")
    return text


def load_tts_pipeline(
    model_name: str = DEFAULT_TTS_MODEL,
    language: str = DEFAULT_TTS_LANGUAGE,
    device: str = DEFAULT_TTS_DEVICE,
):
    """Load one Kokoro pipeline per configuration and reuse it."""

    cache_key = (model_name, language, device)
    with _TTS_PIPELINE_LOCK:
        pipeline = _TTS_PIPELINES.get(cache_key)
        if pipeline is None:
            from kokoro import KModel, KPipeline

            if model_name != DEFAULT_TTS_MODEL:
                pipeline = KPipeline(
                    lang_code=language,
                    repo_id=model_name,
                    device=device,
                )
                _TTS_PIPELINES[cache_key] = pipeline
                return pipeline

            from huggingface_hub import snapshot_download

            pinned_directory = (
                PROJECT_ROOT
                / "models"
                / "huggingface"
                / "pinned-kokoro"
                / DEFAULT_TTS_REVISION
            )
            snapshot_path = Path(
                snapshot_download(
                    repo_id=model_name,
                    revision=DEFAULT_TTS_REVISION,
                    allow_patterns=["config.json", "*.pth"],
                    local_dir=str(pinned_directory),
                )
            )
            model_path = snapshot_path / "kokoro-v1_0.pth"
            config_path = snapshot_path / "config.json"
            model = KModel(
                repo_id=model_name,
                config=str(config_path),
                model=str(model_path),
            ).to(device).eval()

            pipeline = KPipeline(
                lang_code=language,
                repo_id=model_name,
                model=model,
                device=device,
            )
            pipeline._lux_voice_directory = snapshot_path / "voices"
            pipeline._lux_model_name = model_name
            pipeline._lux_model_revision = DEFAULT_TTS_REVISION
            _TTS_PIPELINES[cache_key] = pipeline
    return pipeline


def iter_kokoro_audio(
    pipeline,
    text: str,
    voice: str = DEFAULT_TTS_VOICE,
    speed: float = DEFAULT_TTS_SPEED,
):
    """Yield mono float32 speech chunks generated locally by Kokoro."""

    normalized = " ".join(text.split())
    if not normalized:
        raise ValueError("Cannot speak an empty reply")

    produced_audio = False
    voice_argument = voice
    voice_directory = getattr(pipeline, "_lux_voice_directory", None)
    if voice_directory is not None:
        from huggingface_hub import hf_hub_download

        local_voices: list[str] = []
        for name in voice.split(","):
            normalized_name = name.strip()
            local_path = Path(voice_directory) / f"{normalized_name}.pt"
            if not local_path.is_file():
                local_path = Path(
                    hf_hub_download(
                        repo_id=pipeline._lux_model_name,
                        filename=f"voices/{normalized_name}.pt",
                        revision=pipeline._lux_model_revision,
                        local_dir=str(Path(voice_directory).parent),
                    )
                )
            local_voices.append(str(local_path))
        voice_argument = ",".join(local_voices)

    for result in pipeline(normalized, voice=voice_argument, speed=speed):
        audio = getattr(result, "audio", None)
        if audio is None:
            continue
        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size:
            produced_audio = True
            yield samples
    if not produced_audio:
        raise ValueError("Kokoro returned empty audio")


class SpeechModelWarmupWorker(QThread):
    """Load local speech models and run one silent Kokoro inference."""

    status_changed = Signal(str)
    ready = Signal()
    failure = Signal(str)

    def __init__(
        self,
        transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL,
        neural_voice_enabled: bool = True,
        tts_model: str = DEFAULT_TTS_MODEL,
        tts_voice: str = DEFAULT_TTS_VOICE,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.transcription_model = transcription_model
        self.neural_voice_enabled = neural_voice_enabled
        self.tts_model = tts_model
        self.tts_voice = tts_voice

    def run(self) -> None:
        try:
            self.status_changed.emit(
                f"LOADING · WHISPER {self.transcription_model}"
            )
            load_transcription_model(self.transcription_model)
            if self.isInterruptionRequested():
                return

            if self.neural_voice_enabled:
                self.status_changed.emit("LOADING · LOCAL KOKORO")
                pipeline = load_tts_pipeline(self.tts_model)
                if self.isInterruptionRequested():
                    return
                self.status_changed.emit("WARMING · LOCAL KOKORO VOICE")
                # The voice and part of the inference stack are lazy-loaded.
                # Generate but do not play a tiny phrase during startup.
                for _samples in iter_kokoro_audio(
                    pipeline,
                    "Ready.",
                    self.tts_voice,
                ):
                    if self.isInterruptionRequested():
                        return

            if not self.isInterruptionRequested():
                self.ready.emit()
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failure.emit(str(error))


def _play_wav_bytes(audio_data: bytes, should_stop) -> None:
    """Play an in-memory PCM WAV while allowing thread interruption."""

    with wave.open(BytesIO(audio_data), "rb") as audio:
        channels = audio.getnchannels()
        sample_width = audio.getsampwidth()
        sample_rate = audio.getframerate()
        frames = audio.readframes(audio.getnframes())

    dtype_by_width = {1: np.uint8, 2: np.int16, 4: np.int32}
    dtype = dtype_by_width.get(sample_width)
    if dtype is None:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")
    samples = np.frombuffer(frames, dtype=dtype)
    if channels > 1:
        samples = samples.reshape(-1, channels)

    with sd.OutputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype=dtype,
        blocksize=2048,
        latency="low",
    ) as stream:
        for start in range(0, len(samples), 2048):
            if should_stop():
                return
            stream.write(samples[start : start + 2048])


def _play_float_audio(samples: np.ndarray, sample_rate: int, should_stop) -> None:
    """Play mono float32 samples while allowing thread interruption."""

    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    if not audio.size:
        return
    with sd.OutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype=np.float32,
        blocksize=2048,
        latency="low",
    ) as stream:
        for start in range(0, len(audio), 2048):
            if should_stop():
                return
            stream.write(audio[start : start + 2048])


class SpeechWorker(QThread):
    """Capture one utterance and transcribe it with local faster-whisper."""

    calibrating = Signal(int)
    listening = Signal(int)
    transcribing = Signal(str)
    recognized_text = Signal(str)
    no_speech = Signal(str)
    failure = Signal(str)

    def __init__(
        self,
        transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL,
        input_device: int | None = None,
        max_seconds: float = 20.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.transcription_model = transcription_model
        self.input_device = input_device
        self.max_seconds = max_seconds

    def run(self) -> None:
        try:
            captured = self._capture_utterance()
            if captured is None:
                return
            pcm_data, sample_rate = captured
            self.transcribing.emit(self.transcription_model)
            model = load_transcription_model(self.transcription_model)
            text = transcribe_speech_wav(
                model,
                pcm16_to_wav(pcm_data, sample_rate),
            )
            if not self.isInterruptionRequested():
                self.recognized_text.emit(text)
        except NoSpeechDetected as error:
            self.no_speech.emit(str(error))
        except Exception as error:
            self.failure.emit(str(error))

    def _capture_utterance(self) -> tuple[bytes, int] | None:
        """Record through a small local energy gate; return PCM after silence."""

        device_info = sd.query_devices(self.input_device, "input")
        sample_rate = int(device_info["default_samplerate"])
        if sample_rate <= 0:
            raise RuntimeError("The selected microphone has no valid sample rate")

        block_seconds = 0.10
        block_size = max(800, int(sample_rate * block_seconds))
        max_blocks = max(1, math.ceil(self.max_seconds / block_seconds))
        calibration_blocks = math.ceil(MIC_CALIBRATION_SECONDS / block_seconds)
        pre_roll: deque[bytes] = deque(maxlen=6)
        utterance: list[bytes] = []
        calibration_rms: list[float] = []
        detector: _EnergyEndpointDetector | None = None
        self.calibrating.emit(sample_rate)

        with sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=block_size,
            device=self.input_device,
            dtype="int16",
            channels=1,
        ) as stream:
            for block_index in range(max_blocks + calibration_blocks):
                if self.isInterruptionRequested():
                    return None
                data, _overflowed = stream.read(block_size)
                block = bytes(data)
                samples = np.frombuffer(block, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0

                if block_index < calibration_blocks:
                    calibration_rms.append(rms)
                    pre_roll.append(block)
                    if block_index + 1 == calibration_blocks:
                        detector = _EnergyEndpointDetector(
                            block_seconds,
                            calibration_rms,
                        )
                        pre_roll.clear()
                        self.listening.emit(sample_rate)
                    continue

                if detector is None:
                    raise RuntimeError("Microphone endpoint detector was not initialized")

                if not detector.speech_started:
                    pre_roll.append(block)
                    detector.observe(rms)
                    if detector.speech_started:
                        utterance.extend(pre_roll)
                    continue

                utterance.append(block)
                if detector.observe(rms):
                    break

        if (
            detector is None
            or not detector.speech_started
            or detector.voiced_blocks < detector.minimum_voiced_blocks
        ):
            raise NoSpeechDetected("No speech detected before timeout")
        return b"".join(utterance), sample_rate


class VoiceReplyWorker(QThread):
    """Speak through local Kokoro, falling back to the system voice."""

    reply_started = Signal()
    reply_finished = Signal()
    voice_status = Signal(str)
    failure = Signal(str)

    def __init__(
        self,
        text: str,
        parent=None,
        neural_enabled: bool = True,
        tts_model: str = DEFAULT_TTS_MODEL,
        tts_voice: str = DEFAULT_TTS_VOICE,
    ) -> None:
        super().__init__(parent)
        self.text = text
        self.neural_enabled = neural_enabled
        self.tts_model = tts_model
        self.tts_voice = tts_voice
        self.playback_completed = False

    def run(self) -> None:
        self.playback_completed = False
        try:
            if self.neural_enabled:
                completed = self._speak_neural()
            else:
                completed = self._speak_local()
            if not completed or self.isInterruptionRequested():
                return
            self.playback_completed = True
            self.reply_finished.emit()
        except Exception as neural_error:
            if self.isInterruptionRequested():
                return
            if not self.neural_enabled:
                self.failure.emit(str(neural_error))
                return
            try:
                self.voice_status.emit("SPEAKING · SYSTEM VOICE FALLBACK")
                self.reply_started.emit()
                completed = self._speak_local()
                if not completed or self.isInterruptionRequested():
                    return
                self.playback_completed = True
                self.reply_finished.emit()
            except Exception as local_error:
                self.failure.emit(
                    f"Kokoro voice failed: {neural_error}; "
                    f"system voice failed: {local_error}"
                )

    def _speak_neural(self) -> bool:
        if self.isInterruptionRequested():
            return False
        self.voice_status.emit("LOADING · LOCAL KOKORO")
        pipeline = load_tts_pipeline(self.tts_model)
        self.voice_status.emit("GENERATING · LOCAL KOKORO")
        started = False
        for samples in iter_kokoro_audio(
            pipeline,
            self.text,
            self.tts_voice,
        ):
            if self.isInterruptionRequested():
                return False
            if not started:
                started = True
                self.voice_status.emit("SPEAKING · LOCAL KOKORO")
                self.reply_started.emit()
            _play_float_audio(
                samples,
                KOKORO_SAMPLE_RATE,
                self.isInterruptionRequested,
            )
            if self.isInterruptionRequested():
                return False
        return True

    def _speak_local(self) -> bool:
        if self.isInterruptionRequested():
            return False
        engine = pyttsx3.init()
        engine.setProperty("rate", 165)
        engine.setProperty("volume", 0.95)
        if not self.neural_enabled:
            self.voice_status.emit("SPEAKING · SYSTEM VOICE")
            self.reply_started.emit()
        engine.say(self.text)
        engine.runAndWait()
        engine.stop()
        return not self.isInterruptionRequested()


def speech_input_smoke_test(
    input_device: int | None = None,
    seconds: float = 1.0,
) -> int:
    """Verify microphone access without saving or uploading audio."""

    device_info = sd.query_devices(input_device, "input")
    sample_rate = int(device_info["default_samplerate"])
    block_size = max(1600, int(sample_rate * seconds))
    with sd.RawInputStream(
        samplerate=sample_rate,
        blocksize=block_size,
        device=input_device,
        dtype="int16",
        channels=1,
    ) as stream:
        data, overflowed = stream.read(block_size)
    if not data:
        raise RuntimeError("Microphone returned no audio samples")
    print(
        f"Speech input smoke test passed: device={device_info['name']}, "
        f"sample_rate={sample_rate}, bytes={len(data)}, overflowed={overflowed}"
    )
    return 0
