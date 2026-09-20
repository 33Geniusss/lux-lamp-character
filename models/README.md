# Face Landmarker model

`face_landmarker.task` is the official MediaPipe Face Landmarker float16 model:

- Source: https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
- Size: 3,758,596 bytes
- SHA-256: `64184E229B263107BC2B804C6625DB1341FF2BB731874B0BCC2FE6544E0BC9FF`

The model runs locally through MediaPipe Tasks. Camera frames are not uploaded
or written to disk by this project.

## Local speech models

The current application downloads and caches these models on first setup:

- Faster-Whisper Small under `models/faster-whisper/` for speech recognition.
- `hexgrad/Kokoro-82M` under `models/huggingface/` for speech synthesis.

Run `scripts/preload_models.py` through the project environment to download and
warm both models without opening the GUI. These generated cache directories are
ignored by Git. Microphone audio is processed locally and is neither uploaded
nor saved.
