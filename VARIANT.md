# SW/CV Challenge Variant

- Speech-to-text: local `faster-whisper` with Whisper Small
- Language and vision reasoning: OpenAI GPT API
- Text-to-speech: local `hexgrad/Kokoro-82M` with voice `af_heart`

Only the GPT language and vision stage requires `OPENAI_API_KEY`. Microphone
audio and final reply text are processed locally for speech I/O.
