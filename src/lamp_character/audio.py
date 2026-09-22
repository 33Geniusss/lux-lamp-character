"""Local procedural music and sound effects for the lamp character."""

from __future__ import annotations

from collections import deque
import threading

import numpy as np
from PySide6.QtCore import QThread, Signal
import sounddevice as sd


SAMPLE_RATE = 24_000
CHUNK_FRAMES = 1024
OUTPUT_LATENCY = "low"


def _tone(
    frequency: float,
    duration: float,
    amplitude: float = 0.18,
) -> np.ndarray:
    """Create one warm, softly enveloped tone."""

    frame_count = max(1, round(SAMPLE_RATE * duration))
    time_axis = np.arange(frame_count, dtype=np.float32) / SAMPLE_RATE
    fundamental = np.sin(2.0 * np.pi * frequency * time_axis)
    harmonic = 0.16 * np.sin(2.0 * np.pi * frequency * 2.0 * time_axis)
    attack_frames = max(1, round(SAMPLE_RATE * min(0.025, duration / 4.0)))
    release_frames = max(1, round(SAMPLE_RATE * min(0.10, duration / 3.0)))
    envelope = np.ones(frame_count, dtype=np.float32)
    envelope[:attack_frames] = np.linspace(
        0.0,
        1.0,
        attack_frames,
        endpoint=False,
        dtype=np.float32,
    )
    envelope[-release_frames:] *= np.linspace(
        1.0,
        0.0,
        release_frames,
        dtype=np.float32,
    )
    return (amplitude * envelope * (fundamental + harmonic)).astype(np.float32)


def _silence(duration: float) -> np.ndarray:
    return np.zeros(max(1, round(SAMPLE_RATE * duration)), dtype=np.float32)


def _sequence(notes: tuple[tuple[float, float], ...]) -> np.ndarray:
    parts: list[np.ndarray] = []
    for frequency, duration in notes:
        parts.append(_tone(frequency, duration))
        parts.append(_silence(0.025))
    return np.concatenate(parts).astype(np.float32)


def _build_music_loop() -> np.ndarray:
    """Build a quiet four-bar lamp theme without external media files."""

    bar_seconds = 1.0
    chord_progression = (
        (261.63, 329.63, 392.00),
        (220.00, 261.63, 329.63),
        (174.61, 220.00, 261.63),
        (196.00, 246.94, 293.66),
    )
    music = np.zeros(round(SAMPLE_RATE * bar_seconds * 4), dtype=np.float32)
    for bar_index, chord in enumerate(chord_progression):
        start = round(bar_index * bar_seconds * SAMPLE_RATE)
        pad = sum(_tone(note, bar_seconds, 0.040) for note in chord)
        music[start : start + len(pad)] += pad

    melody = (523.25, 659.25, 783.99, 659.25, 440.00, 523.25, 659.25, 587.33)
    note_seconds = 0.5
    for note_index, note in enumerate(melody):
        start = round(note_index * note_seconds * SAMPLE_RATE)
        voice = _tone(note, 0.44, 0.055)
        music[start : start + len(voice)] += voice

    fade_frames = round(SAMPLE_RATE * 0.16)
    music[:fade_frames] *= np.linspace(0.0, 1.0, fade_frames, dtype=np.float32)
    music[-fade_frames:] *= np.linspace(1.0, 0.0, fade_frames, dtype=np.float32)
    return np.clip(music, -0.28, 0.28).astype(np.float32)


SOUND_EFFECTS: dict[str, np.ndarray] = {
    "engage": _sequence(((523.25, 0.13), (659.25, 0.13), (783.99, 0.20))),
    "greet": _sequence(((659.25, 0.12), (783.99, 0.12), (1046.50, 0.20))),
    "success": _sequence(((783.99, 0.15), (1046.50, 0.24))),
    "error": _sequence(((392.00, 0.16), (329.63, 0.28))),
    "disengage": _sequence(((659.25, 0.14), (523.25, 0.26))),
}
MUSIC_LOOP = _build_music_loop()


class CharacterAudioWorker(QThread):
    """Play local SFX and looping music without blocking the Qt UI."""

    status_changed = Signal(str)
    failure = Signal(str)

    def __init__(self, output_device: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self.output_device = output_device
        self._condition = threading.Condition()
        self._cue_queue: deque[str] = deque()
        self._music_active = False
        self._suspended = False
        self._stopping = False

    def play_cue(self, cue_name: str) -> None:
        if cue_name not in SOUND_EFFECTS:
            raise ValueError(f"Unknown character sound effect: {cue_name}")
        with self._condition:
            if self._stopping or self._suspended:
                return
            self._cue_queue.append(cue_name)
            self._condition.notify_all()

    def set_music_active(self, active: bool) -> None:
        with self._condition:
            self._music_active = bool(active)
            self._condition.notify_all()

    def set_suspended(self, suspended: bool) -> None:
        with self._condition:
            self._suspended = bool(suspended)
            if self._suspended:
                self._cue_queue.clear()
            self._condition.notify_all()
        self.status_changed.emit(
            "AUDIO MUTED · LISTEN / VOICE"
            if suspended
            else "LOCAL AUDIO READY"
        )

    def shutdown(self) -> None:
        with self._condition:
            self._stopping = True
            self._music_active = False
            self._cue_queue.clear()
            self._condition.notify_all()

    def run(self) -> None:
        self.status_changed.emit("LOCAL AUDIO READY")
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._stopping
                    or (
                        not self._suspended
                        and (bool(self._cue_queue) or self._music_active)
                    )
                )
                if self._stopping:
                    return
                if self._cue_queue:
                    cue_name = self._cue_queue.popleft()
                    samples = SOUND_EFFECTS[cue_name]
                    is_music = False
                else:
                    cue_name = "music"
                    samples = MUSIC_LOOP
                    is_music = True

            self.status_changed.emit(
                "MUSIC · LAMP THEME" if is_music else f"SFX · {cue_name.upper()}"
            )
            try:
                self._play_samples(samples, is_music=is_music)
            except Exception as error:
                self.failure.emit(str(error))
                return
            with self._condition:
                idle = (
                    not self._stopping
                    and not self._suspended
                    and not self._cue_queue
                    and not self._music_active
                )
            if idle:
                self.status_changed.emit("LOCAL AUDIO READY")

    def _play_samples(self, samples: np.ndarray, *, is_music: bool) -> None:
        with sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=self.output_device,
            blocksize=CHUNK_FRAMES,
            latency=OUTPUT_LATENCY,
        ) as stream:
            for start in range(0, len(samples), CHUNK_FRAMES):
                with self._condition:
                    should_stop = self._stopping or self._suspended
                    if is_music:
                        should_stop = should_stop or not self._music_active
                        should_stop = should_stop or bool(self._cue_queue)
                if should_stop:
                    return
                chunk = samples[start : start + CHUNK_FRAMES]
                stream.write(chunk.reshape(-1, 1))


def audio_output_smoke_test(output_device: int | None = None) -> int:
    """Play one short local cue to verify speaker access."""

    device_info = sd.query_devices(output_device, "output")
    samples = SOUND_EFFECTS["success"]
    with sd.OutputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=output_device,
        blocksize=CHUNK_FRAMES,
        latency=OUTPUT_LATENCY,
    ) as stream:
        for start in range(0, len(samples), CHUNK_FRAMES):
            stream.write(samples[start : start + CHUNK_FRAMES].reshape(-1, 1))
    print(
        f"Audio output smoke test passed: device={device_info['name']}, "
        f"sample_rate={SAMPLE_RATE}, frames={len(samples)}"
    )
    return 0


def audio_contract() -> dict[str, float]:
    """Return deterministic cue durations for tests and documentation."""

    result = {
        name: len(samples) / SAMPLE_RATE
        for name, samples in SOUND_EFFECTS.items()
    }
    result["music_loop"] = len(MUSIC_LOOP) / SAMPLE_RATE
    return result
