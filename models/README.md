# Face Landmarker model

`face_landmarker.task` is the official MediaPipe Face Landmarker float16 model:

- Source: https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
- Size: 3,758,596 bytes
- SHA-256: `64184E229B263107BC2B804C6625DB1341FF2BB731874B0BCC2FE6544E0BC9FF`

MediaPipe face inference runs locally and camera frames are not written to disk.
When GPT language/vision reasoning is enabled, however, each model request sends
one current low-detail camera frame to OpenAI together with the transcript and
validated session memory. Use `--no-llm` to prevent those remote requests.

## Local speech models

The current application downloads and caches these models on first setup:

- Faster-Whisper Small under `models/faster-whisper/` for speech recognition.
- `hexgrad/Kokoro-82M` under `models/huggingface/` for speech synthesis.

The application pins both model downloads to the revisions declared in
`src/lamp_character/speech.py` so a clean setup does not silently move to newer
weights.

Run `scripts/preload_models.py` through the project environment to download and
warm both models without opening the GUI. These generated cache directories are
ignored by Git. Microphone audio is processed locally and is neither uploaded
nor saved.
