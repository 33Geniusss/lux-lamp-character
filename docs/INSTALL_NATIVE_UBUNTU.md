# Native Ubuntu 24.04 Installation Guide

This guide installs and runs Lux on a physical computer running Ubuntu 24.04
LTS. It is intended for a normal graphical Ubuntu desktop or laptop, not WSL2,
a headless server, a container, or a virtual machine without hardware
passthrough.

Native Ubuntu uses the camera through Video4Linux and uses the desktop's normal
PipeWire, PulseAudio, or ALSA audio devices. It does not need `usbipd-win`,
PowerShell, WSLg, or a project-local WSL audio bridge.

For Ubuntu 24.04 running under Windows 11 WSL2, use the separate
[WSL2 Installation Guide](INSTALL_UBUNTU.md).

## Requirements

- 64-bit Ubuntu 24.04 LTS on x86-64.
- A logged-in graphical Wayland or X11 desktop session.
- Four CPU cores and 8 GB RAM or more.
- Several gigabytes of free disk space for the environment and local models.
- An integrated or USB webcam supported by Video4Linux.
- A microphone and speaker visible in **Settings → Sound**.
- Internet access for installation, model downloads, and GPT requests.
- `sudo` access for installing Ubuntu system packages.
- An OpenAI API key for language and vision responses.

CUDA and a discrete GPU are not required. Lux runs PyBullet, MediaPipe,
Whisper Small, and Kokoro-82M on the CPU by default.

## 1. Install Git and clone the project

Open Terminal and run:

```bash
sudo apt update
sudo apt install -y git

mkdir -p ~/workspace
cd ~/workspace
git clone https://github.com/33Geniusss/lux-lamp-character.git
cd lux-lamp-character
```

If the repository has already been cloned, open a terminal in its root folder,
where `setup.sh` and `run.py` are located.

## 2. Run the one-command installer

```bash
bash setup.sh
```

Ubuntu asks for the `sudo` password while system packages are installed. No
Windows administrator prompt is involved. The installer then:

1. Installs camera utilities, desktop audio libraries, OpenGL/EGL, Qt/XCB,
   build tools, PortAudio, and eSpeak NG.
2. Finds Conda or installs a pinned project-private Miniforge under
   `.tools/miniforge3` after verifying its SHA-256 checksum.
3. Creates or updates the Python 3.11 environment under `.conda-env`.
4. Installs PyBullet, PySide6, MediaPipe, OpenCV, SoundDevice,
   Faster-Whisper, Kokoro, OpenAI, Pydantic, and supporting packages.
5. Downloads Whisper Small and Kokoro-82M into ignored local model caches and
   performs a silent Kokoro warm-up.
6. Runs the unit suite plus PyBullet, camera, microphone, and speaker smoke
   tests. The speaker check plays one short local cue.

The WSL-only camera sharing and PortAudio build steps are detected and skipped.
The first installation can take several minutes. It is safe to rerun the same
command after an interrupted installation or dependency update.

Optional setup switches:

```bash
# Do not download or warm the local speech models.
bash setup.sh --skip-models

# Install dependencies and models without running automated checks.
bash setup.sh --skip-checks
```

Do not use either switch for the first complete deployment unless installation
diagnostics require it.

## 3. Verify the native camera and audio devices

Check that Ubuntu created at least one camera node:

```bash
ls -l /dev/video*
```

Check the current desktop audio server and default devices:

```bash
pactl info
pactl list short sources
pactl list short sinks
```

The installer already runs the project hardware checks. Run them again when
diagnosing a device change or selecting a different camera/audio device:

```bash
# Camera capture and MediaPipe face inference for three seconds
./.conda-env/bin/python run.py --camera-smoke-test

# Record from the default microphone without uploading audio
./.conda-env/bin/python run.py --speech-smoke-test

# Play a short local cue through the default speaker
./.conda-env/bin/python run.py --audio-output-smoke-test
```

These checks use real devices and should be run from the same logged-in desktop
session that will run the GUI.

## 4. Start Lux and enter the API key

```bash
./.conda-env/bin/python run.py
```

If `OPENAI_API_KEY` is not already set, the terminal displays:

```text
OpenAI API key:
```

Paste the key and press Enter. Input is hidden, and the key exists only in the
running Lux process. It is not written to the repository or shell history.

To set it manually for the current terminal instead:

```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY && echo
export OPENAI_API_KEY
./.conda-env/bin/python run.py
```

The key is used only for GPT language and vision requests. Each request sends
the transcript, one current low-detail camera frame, and validated session
memory to OpenAI. Speech recognition uses local Whisper Small, speech synthesis
uses local Kokoro-82M, and raw microphone audio is not uploaded.

Wait until the GUI reports `READY · LOCAL MODELS`. Look toward the camera for
approximately 0.7 seconds to engage the character. Wait for `LISTENING` before
speaking.

## 5. Complete deployment checks

Run these commands from the project folder:

```bash
# URDF, actions, PyBullet control, and CPU rendering
./.conda-env/bin/python run.py --smoke-test

# Full unit and contract suite
./.conda-env/bin/python -m unittest discover -s tests -v

# Offscreen Qt composition and simulator rendering
QT_QPA_PLATFORM=offscreen \
  ./.conda-env/bin/python run.py --screenshot output/motion-studio.png
```

The offscreen screenshot checks Qt composition and simulation rendering. It
does not validate the physical camera, microphone, speaker, or visible desktop.

## Device selection

OpenCV normally opens camera index `0`. SoundDevice uses the system's default
input and output devices. List and override them when necessary:

```bash
./.conda-env/bin/python -c 'import sounddevice as sd; print(sd.query_devices())'

./.conda-env/bin/python run.py --camera-index 1
./.conda-env/bin/python run.py --audio-device 2
./.conda-env/bin/python run.py --audio-output-device 4
```

## Useful fallback modes

```bash
# Do not call GPT; use the fixed fallback response.
./.conda-env/bin/python run.py --no-llm

# Use the operating-system voice instead of Kokoro.
./.conda-env/bin/python run.py --local-voice

# Disable character music and sound effects.
./.conda-env/bin/python run.py --no-character-audio

# Open only the simulator and controls.
./.conda-env/bin/python run.py --no-camera --no-speech --no-llm
```

## Troubleshooting

### No `/dev/video*` device exists

Close applications that may own the camera, disconnect and reconnect an
external webcam, and inspect the kernel messages and available devices:

```bash
v4l2-ctl --list-devices
sudo dmesg | tail -n 50
```

If no camera appears, the device may require a Linux kernel driver or may be
disabled in firmware.

### Camera permission is denied

Ubuntu desktop sessions normally grant device access through logind ACLs. If
the camera exists but the current account cannot open it, add the account to
the `video` group:

```bash
sudo usermod -aG video "$USER"
```

Log out of the Ubuntu desktop completely and log back in before testing again.

### The wrong camera opens

List the devices and try another OpenCV index:

```bash
v4l2-ctl --list-devices
./.conda-env/bin/python run.py --camera-index 1
```

### Microphone or speaker is unavailable

First select and test the desired devices in **Settings → Sound**. Then inspect
the devices visible to PortAudio:

```bash
./.conda-env/bin/python -c 'import sounddevice as sd; print(sd.query_devices())'
```

Pass the appropriate input or output index with `--audio-device` or
`--audio-output-device`. Do not launch the GUI with `sudo`, because the root
process normally cannot access the logged-in user's audio session.

### Qt cannot connect to the display

Confirm that the command is running in a terminal opened inside the graphical
Ubuntu session:

```bash
printf 'DISPLAY=%s\nWAYLAND_DISPLAY=%s\n' "$DISPLAY" "$WAYLAND_DISPLAY"
```

Do not set `QT_QPA_PLATFORM=xcb` by default. Qt normally selects Wayland or X11
automatically. Use `QT_QPA_PLATFORM=xcb` only as an XWayland troubleshooting
fallback when the default Qt platform plugin fails.

### Dependency or model downloads fail

Confirm access to Ubuntu repositories, GitHub, Conda Forge, PyPI, and Hugging
Face. Then rerun `bash setup.sh`; completed environments and model downloads are
reused.

### The first launch is slow

Whisper Small and Kokoro-82M are CPU models with substantial weights. Setup
downloads and warms them, but each new process still loads the models into RAM.
Close memory-heavy applications on an 8 GB system.

## Updating the project

After pulling a newer revision, rerun the installer:

```bash
git pull
bash setup.sh
```

The environment is updated with `--prune`, model caches are reused, and the
automated validation suite runs again.
