# Ubuntu 24.04 on Windows 11 WSL2 Installation Guide

This guide installs and runs Lux in an Ubuntu 24.04 WSL2 distribution on
Windows 11. It covers the additional USB/IP camera and WSLg audio setup required
by WSL2.

For a physical Ubuntu desktop or laptop, use the separate
[Native Ubuntu 24.04 Installation Guide](INSTALL_NATIVE_UBUNTU.md). Native
Ubuntu does not require `usbipd-win`, PowerShell helpers, or the WSLg audio
bridge described here.

## Requirements

- Windows 11 with WSL2 and WSLg enabled.
- A 64-bit Ubuntu 24.04 WSL2 distribution on x86-64.
- Windows-to-WSL command interop enabled.
- An active WSLg graphical session.
- Four CPU cores and 8 GB RAM or more.
- Several gigabytes of free disk space for the environment and local models.
- An integrated or USB webcam exposed through Video4Linux.
- A microphone and speaker exposed through standard Linux audio facilities.
- Internet access for installation, local model downloads, and GPT requests.
- `sudo` access for installing system libraries.
- An OpenAI API key for language and vision responses.
- Permission to approve one Windows administrator prompt for camera sharing.

CUDA and a discrete GPU are not required.

## 1. Clone the project

In a new Ubuntu 24.04 WSL2 terminal:

```bash
mkdir -p ~/workspace
cd ~/workspace
git clone https://github.com/33Geniusss/lux-lamp-character.git
cd lux-lamp-character
```

## 2. Run the one-command installer

```bash
bash setup.sh
```

Ubuntu asks for the `sudo` password while installing system packages. On WSL2,
Windows also shows one UAC approval prompt if `usbipd-win` must be installed or
the selected camera has not been shared before. These operating-system prompts
cannot be bypassed safely. The script then performs the following steps:

1. Installs CA certificates, Curl, build tools, OpenGL/EGL, Qt/XCB runtime
   libraries, PortAudio build dependencies, camera utilities, and eSpeak NG.
2. On WSL, installs or locates `usbipd-win`, chooses the active non-IR USB
   camera, persistently shares it, attaches it to WSL, and grants the Ubuntu
   user access to `/dev/video*`.
3. Finds an existing Conda installation.
4. If Conda is unavailable, downloads the pinned Miniforge build matching the
   machine architecture into `.tools/miniforge3` and verifies its SHA-256
   checksum before execution.
5. Creates or updates `.conda-env` from `environment.yml` using Python 3.11.
6. Installs PyBullet, PySide6, MediaPipe, OpenCV, SoundDevice,
   Faster-Whisper, Kokoro, OpenAI, Pydantic, and supporting packages.
7. On WSL, builds a project-local PortAudio with PulseAudio support so
   SoundDevice can use WSLg's `RDPSource` and `RDPSink` devices.
8. Downloads Whisper Small and Kokoro-82M into ignored `models/` caches and
   runs a silent Kokoro warm-up inference.
9. Runs unit tests plus PyBullet, camera, microphone, and speaker smoke tests.

The first installation can take several minutes. It is safe to rerun the same
command after an interrupted installation or when dependencies change.

Optional setup switches:

```bash
# Install dependencies without downloading/warming the local speech models.
bash setup.sh --skip-models

# Install dependencies and models without running automated checks.
bash setup.sh --skip-checks
```

## 3. Start Lux and enter the API key

```bash
./.conda-env/bin/python run.py
```

If `OPENAI_API_KEY` is not already set, the terminal displays `OpenAI API key:`.
Paste the key and press Enter. Input is hidden, the key is kept only in the Lux
process, and it is not written to the repository or shell history. To configure
the variable yourself for the current shell instead, use:

```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY && echo
export OPENAI_API_KEY
./.conda-env/bin/python run.py
```

The key is required only for GPT language and vision requests. Each request
sends the transcript, one current low-detail camera frame, and validated session
memory to OpenAI. Microphone audio is transcribed locally, and replies are
synthesized locally.

Wait until the status reports `READY · LOCAL MODELS`. Look toward the camera for
approximately 0.7 seconds to engage the character. When microphone calibration
finishes and the interface changes to `LISTENING`, begin speaking.

## 4. Verify the deployment

Run each check from the project folder:

```bash
# URDF, actions, PyBullet control, and CPU rendering
./.conda-env/bin/python run.py --smoke-test

# Camera and MediaPipe face inference for three seconds
./.conda-env/bin/python run.py --camera-smoke-test

# Microphone capture without uploading audio
./.conda-env/bin/python run.py --speech-smoke-test

# Play a short local cue through the selected speaker
./.conda-env/bin/python run.py --audio-output-smoke-test

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

On WSL, `run.py` loads the project-local PulseAudio library automatically. For
an equivalent standalone Python inspection, include that library explicitly:

```bash
LD_LIBRARY_PATH="$PWD/.tools/portaudio-pulse/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
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

On WSL, rerun `bash setup.sh --skip-models`. The setup automatically installs
and configures `usbipd-win`. The selected camera hardware ID is stored under the
ignored `.tools/` directory, and later `run.py` launches automatically reattach
that camera after a WSL restart. Camera sharing survives Windows restarts, but
the active attachment does not; the launcher handles that non-persistent step.

### Microphone or speaker errors

Confirm that the device appears in the Windows and WSLg audio settings, then
list the PortAudio devices and pass the correct index.

Under WSL, rerun `bash setup.sh --skip-models`; the setup script builds the
PulseAudio-enabled PortAudio library used automatically by `run.py`. Confirm
that `PULSE_SERVER` is `unix:/mnt/wslg/PulseServer`, then run both audio smoke
tests above. If WSLg audio has stopped responding, run `wsl --shutdown` from
Windows PowerShell, reopen Ubuntu, reattach any USB camera, and test again.

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
  acl ca-certificates curl build-essential cmake git pkg-config \
  libegl1 libgl1 libportaudio2 libasound2-dev libpulse-dev \
  pulseaudio-utils usbutils v4l-utils espeak-ng \
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
