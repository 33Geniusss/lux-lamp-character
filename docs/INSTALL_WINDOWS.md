# Windows Installation Guide

This guide installs and runs Lux on 64-bit Windows 10 or Windows 11. The setup
uses an isolated Python 3.11 environment inside the project and does not replace
the system Python installation.

## Requirements

- 64-bit Windows 10 or Windows 11.
- Four CPU cores and 8 GB RAM or more are recommended.
- Several gigabytes of free disk space for Python packages and local models.
- A webcam, microphone, and speaker for the complete interaction.
- Internet access for the first installation, model downloads, and GPT calls.
- An OpenAI API key for language and vision responses.

A discrete GPU and CUDA are not required. Git is needed only if the project is
being cloned from GitHub rather than downloaded as an archive.

## 1. Open PowerShell in the project folder

After cloning or extracting the repository, open the folder containing
`setup.ps1` and `run.py`. In File Explorer, right-click the empty area in that
folder and choose **Open in Terminal**, or navigate there manually:

```powershell
cd D:\path\to\SWCVChallenge
```

## 2. Run the one-command installer

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

The execution-policy override applies only to this new PowerShell process. The
script does not permanently change the machine's PowerShell policy.

The installer performs the following steps:

1. Finds an existing Conda installation.
2. If Conda is unavailable, downloads a private 64-bit Miniforge installation
   into `.tools/miniforge3` inside the project.
3. Creates or updates `.conda-env` from `environment.yml` using Python 3.11.
4. Installs PyBullet, PySide6, MediaPipe, OpenCV, SoundDevice,
   Faster-Whisper, Kokoro, OpenAI, Pydantic, and supporting packages.
5. Downloads Whisper Small and Kokoro-82M into the ignored `models/` caches.
6. Runs a silent Kokoro warm-up inference.
7. Runs all unit tests and the CPU PyBullet render smoke test.

The initial installation can take several minutes. Model and package caches are
reused on later runs. It is safe to run the same setup command again after an
interrupted installation or dependency update.

Optional setup switches:

```powershell
# Install dependencies but do not download/warm the local speech models.
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -SkipModels

# Install dependencies and models without running automated checks.
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -SkipChecks
```

## 3. Set the OpenAI API key

Use a secure prompt so the key is not shown in terminal history:

```powershell
$lampKey = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [Net.NetworkCredential]::new("", $lampKey).Password
```

This sets the key only for the current PowerShell window. Opening a new terminal
requires entering it again. Do not add the key to source files, `README` files,
screenshots, or committed `.env` files.

The key is required only for GPT language and vision reasoning. Whisper speech
recognition and Kokoro speech synthesis run locally.

## 4. Start Lux

```powershell
.\.conda-env\python.exe run.py
```

The first window initially shows that the local speech models are loading. Wait
until the status reports `READY · LOCAL MODELS` before starting a conversation.
Look toward the camera for approximately 0.7 seconds to engage the character.
During microphone calibration, wait until `LISTENING` appears before speaking.

## 5. Verify camera, microphone, and rendering

Run these commands individually from the project folder:

```powershell
# URDF, actions, PyBullet control, and CPU rendering
.\.conda-env\python.exe run.py --smoke-test

# Camera and MediaPipe face inference for three seconds
.\.conda-env\python.exe run.py --camera-smoke-test

# Microphone capture without uploading audio
.\.conda-env\python.exe run.py --speech-smoke-test

# Full unit and contract suite
.\.conda-env\python.exe -m unittest discover -s tests -v
```

To verify the GUI renderer without keeping the interactive window open:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.conda-env\python.exe run.py --screenshot output\motion-studio.png
Remove-Item Env:QT_QPA_PLATFORM
```

## Device selection

The default camera and audio devices normally use index `0` or the operating
system default. Override them when necessary:

```powershell
.\.conda-env\python.exe run.py --camera-index 1
.\.conda-env\python.exe run.py --audio-device 2
.\.conda-env\python.exe run.py --audio-output-device 4
```

List PortAudio devices:

```powershell
.\.conda-env\python.exe -c "import sounddevice as sd; print(sd.query_devices())"
```

## Useful fallback modes

```powershell
# Do not use GPT; speak the fixed fallback response.
.\.conda-env\python.exe run.py --no-llm

# Use the Windows system voice instead of Kokoro.
.\.conda-env\python.exe run.py --local-voice

# Disable music and sound effects.
.\.conda-env\python.exe run.py --no-character-audio

# Open the simulator without camera or microphone features.
.\.conda-env\python.exe run.py --no-camera --no-speech --no-llm
```

## Troubleshooting

### PowerShell says scripts are disabled

Use the complete command shown in this guide, including
`-ExecutionPolicy Bypass -File`. It affects only that process.

### The setup cannot download packages or models

Confirm that GitHub, Conda Forge, PyPI, and Hugging Face are reachable from the
network. Then rerun `setup.ps1`; completed downloads and the environment are
reused.

### `OPENAI_API_KEY is not configured`

The key was not set in the same PowerShell process that launched the app. Run
the secure key commands again in the current window, then start Lux from it.

### The camera cannot be opened

Close other applications using the camera. Check **Windows Settings → Privacy &
security → Camera** and permit desktop applications. Try another index with
`--camera-index 1` and run the camera smoke test.

### Microphone or speaker errors

Check **Windows Settings → System → Sound** and confirm the desired devices are
enabled. List the PortAudio indices with `sounddevice.query_devices()` and pass
the correct input/output index. The GUI continues operating if character audio
fails.

### The first model load is slow

The first setup downloads and initializes large CPU models. Later launches
reuse both disk caches, and the application performs model loading and a silent
Kokoro warm-up before enabling listening.

## Updating the project

After pulling a newer revision, rerun:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

The environment is updated with `--prune`, cached model files are reused, and
the validation suite is run again.
