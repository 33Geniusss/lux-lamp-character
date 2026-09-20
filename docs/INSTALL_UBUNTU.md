# Ubuntu 24.04 Installation Guide

This guide installs and runs Lux on the challenge target: a clean Ubuntu 24.04
LTS laptop with four CPU cores, 8 GB RAM, no discrete GPU, a camera, microphone,
speaker, and Wi-Fi.

Use a physical Ubuntu desktop or laptop for the final demonstration. WSL can be
useful for unit or headless checks, but it is not the supported environment for
validating Linux camera, microphone, speaker, and visible desktop behavior.

## Requirements

- 64-bit Ubuntu 24.04 LTS on x86-64. The setup script detects ARM64 and can
  install the matching Miniforge build, but the complete ARM64 dependency set
  has not been validated.
- An active graphical desktop session.
- Four CPU cores and 8 GB RAM or more.
- Several gigabytes of free disk space for the environment and local models.
- An integrated or USB webcam exposed through Video4Linux.
- A microphone and speaker exposed through standard Linux audio facilities.
- Internet access for installation, local model downloads, and GPT requests.
- `sudo` access for installing system libraries.
- An OpenAI API key for language and vision responses.

CUDA and a discrete GPU are not required.

## 1. Open a terminal in the project folder

After cloning or extracting the repository, navigate to the folder containing
`setup.sh` and `run.py`:

```bash
cd /path/to/SWCVChallenge
```

## 2. Run the one-command installer

```bash
bash setup.sh
```

Ubuntu asks for the `sudo` password while installing system packages. The
script then performs the following steps:

1. Installs CA certificates, Curl, build tools, OpenGL/EGL, Qt/XCB runtime
   libraries, PortAudio, and eSpeak NG with `apt-get`.
2. Finds an existing Conda installation.
3. If Conda is unavailable, downloads a private Miniforge build matching the
   machine architecture into `.tools/miniforge3`.
4. Creates or updates `.conda-env` from `environment.yml` using Python 3.11.
5. Installs PyBullet, PySide6, MediaPipe, OpenCV, SoundDevice,
   Faster-Whisper, Kokoro, OpenAI, Pydantic, and supporting packages.
6. Downloads Whisper Small and Kokoro-82M into ignored `models/` caches.
7. Runs a silent Kokoro warm-up inference.
8. Runs all unit tests and the CPU PyBullet render smoke test.

The first installation can take several minutes. It is safe to rerun the same
command after an interrupted installation or when dependencies change.

Optional setup switches:

```bash
# Install dependencies without downloading/warming the local speech models.
bash setup.sh --skip-models

# Install dependencies and models without running automated checks.
bash setup.sh --skip-checks
```

## 3. Set the OpenAI API key

Read the key without echoing it or placing it in shell history:

```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY && echo
export OPENAI_API_KEY
```

The key exists only in the current shell. Do not put it in source code,
screenshots, documentation, or committed `.env` files.

The key is required only for GPT language and vision requests. Microphone audio
is transcribed locally, and replies are synthesized locally.

## 4. Start Lux

```bash
./.conda-env/bin/python run.py
```

Wait until the status reports `READY · LOCAL MODELS`. Look toward the camera for
approximately 0.7 seconds to engage the character. When microphone calibration
finishes and the interface changes to `LISTENING`, begin speaking.

## 5. Verify the deployment

Run each check from the project folder:

```bash
# URDF, actions, PyBullet control, and CPU rendering
./.conda-env/bin/python run.py --smoke-test

# Camera and MediaPipe face inference for three seconds
./.conda-env/bin/python run.py --camera-smoke-test

# Microphone capture without uploading audio
./.conda-env/bin/python run.py --speech-smoke-test

# Full unit and contract suite
./.conda-env/bin/python -m unittest discover -s tests -v

# Offscreen full-window render
QT_QPA_PLATFORM=offscreen \
  ./.conda-env/bin/python run.py --screenshot output/motion-studio.png
```

The camera and speech smoke tests require real hardware and access permissions.
The offscreen check verifies Qt composition and simulation rendering, not the
visible desktop, webcam, microphone, or speaker.

## Device selection

OpenCV normally uses camera index `0`; SoundDevice uses the default PipeWire,
PulseAudio, or ALSA devices. Override them if needed:

```bash
./.conda-env/bin/python run.py --camera-index 1
./.conda-env/bin/python run.py --audio-device 2
./.conda-env/bin/python run.py --audio-output-device 4
```

List audio devices seen by PortAudio:

```bash
./.conda-env/bin/python -c 'import sounddevice as sd; print(sd.query_devices())'
```

List camera device nodes:

```bash
ls -l /dev/video*
```

## Useful fallback modes

```bash
# Do not use GPT; speak the fixed fallback response.
./.conda-env/bin/python run.py --no-llm

# Use the operating-system voice instead of Kokoro.
./.conda-env/bin/python run.py --local-voice

# Disable music and sound effects.
./.conda-env/bin/python run.py --no-character-audio

# Open only the simulator and controls.
./.conda-env/bin/python run.py --no-camera --no-speech --no-llm
```

## Troubleshooting

### Qt reports that the `xcb` platform plugin cannot be loaded

Rerun `bash setup.sh` so all XCB runtime packages are installed. Confirm that
the command is running inside a graphical Ubuntu desktop session and that
`DISPLAY` or `WAYLAND_DISPLAY` is set.

### The camera cannot be opened

Close other applications using it and verify that `/dev/video0` or another
`/dev/video*` node exists. Try `--camera-index 1`. If the user is not permitted
to access the device, add the account to the `video` group and log out and back
in before testing again:

```bash
sudo usermod -aG video "$USER"
```

### Microphone or speaker errors

Confirm that the device appears in Ubuntu **Settings → Sound**, then list the
PortAudio devices and pass the correct index. On desktop Ubuntu, PipeWire or
PulseAudio should expose the selected hardware to PortAudio.

### `OPENAI_API_KEY is not configured`

The key must be exported in the same terminal that launches Lux. Repeat the
secure `read` and `export` commands in the current shell.

### The setup cannot download dependencies or models

Confirm access to Ubuntu repositories, GitHub, Conda Forge, PyPI, and Hugging
Face. Rerun `bash setup.sh`; the environment and completed downloads are reused.

### The first model load is slow

Whisper Small and Kokoro-82M are CPU models with substantial weights. Setup
preloads both and runs a silent TTS inference. Later application launches reuse
the on-disk caches, although the models still need to be loaded into RAM.

### The app runs slowly on an 8 GB machine

Close memory-heavy applications before starting Lux. Keep the default CPU
`int8` Whisper configuration. Avoid running a second model preload or test suite
at the same time as the GUI.

## Manual installation reference

The one-command installer is preferred. For inspection, the equivalent system
package installation begins with:

```bash
sudo apt-get update
sudo apt-get install -y \
  ca-certificates curl build-essential \
  libegl1 libgl1 libportaudio2 espeak-ng \
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
  libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 \
  libxcb-xkb1 libxcb-randr0
```

With Conda already available:

```bash
conda env create --prefix ./.conda-env --file environment.yml
./.conda-env/bin/python scripts/preload_models.py
./.conda-env/bin/python run.py --smoke-test
```

## Updating the project

After pulling a newer revision, rerun:

```bash
bash setup.sh
```

The environment is updated with `--prune`, model caches are reused, and the
validation suite runs again.
