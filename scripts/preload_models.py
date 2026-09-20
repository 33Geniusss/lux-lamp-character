"""Download and validate the local speech models without opening the GUI."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from lamp_character.speech import (  # noqa: E402
    DEFAULT_TRANSCRIPTION_MODEL,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
    iter_kokoro_audio,
    load_transcription_model,
    load_tts_pipeline,
)


def main() -> int:
    print(
        f"Downloading/loading faster-whisper model: {DEFAULT_TRANSCRIPTION_MODEL}",
        flush=True,
    )
    load_transcription_model(DEFAULT_TRANSCRIPTION_MODEL)

    print(f"Downloading/loading Kokoro model: {DEFAULT_TTS_MODEL}", flush=True)
    pipeline = load_tts_pipeline(DEFAULT_TTS_MODEL)
    chunks = list(iter_kokoro_audio(pipeline, "Ready.", DEFAULT_TTS_VOICE))
    if not chunks:
        raise RuntimeError("Kokoro warm-up produced no audio")

    print("Local speech models are downloaded and ready.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
