# Lux: Live Lamp Character

![The supplied five-DOF lamp robot](robot/dummy-lamp.png)

Lux is a warm, expressive lamp character built for the Software/CV Character
Robot Challenge. It uses the laptop camera, microphone, and speaker together
with a simulated five-joint body to create one continuous interaction.

## What Lux can do

- Notice when someone looks toward it and disengage when attention moves away.
- Listen to speech and respond with a natural local voice.
- Observe objects, remember useful scene details, and answer later questions.
- Turn to inspect another view before completing a scene-based goal.
- Coordinate body motion, colored light, speech, sound effects, and music.
- Show live camera, engagement state, transcript, memory status, and per-turn timing.

The recorded demonstration is available in [DEMO.mp4](DEMO.mp4).

## Quick start

Choose the guide for your platform:

- [Windows installation](docs/INSTALL_WINDOWS.md)
- [Ubuntu 24.04 installation](docs/INSTALL_UBUNTU.md)

From the project directory, the complete setup is one command.

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Ubuntu 24.04:

```bash
bash setup.sh
```

Both scripts create an isolated Python environment, install dependencies,
download and warm the local speech models, and run automated checks.

## Run

Lux uses an OpenAI API key for language and visual reasoning. Speech recognition
and speech synthesis run locally.

Windows PowerShell:

```powershell
$lampKey = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [Net.NetworkCredential]::new("", $lampKey).Password
.\.conda-env\python.exe run.py
```

Ubuntu:

```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY && echo
export OPENAI_API_KEY
./.conda-env/bin/python run.py
```

The key exists only in the current terminal environment and is not saved by the
setup scripts.

## Try this interaction

Look toward the camera and say:

> Look toward the green cup on the left side of your camera view. If you can
> see it, nod, and remember its color and location.

After Lux responds, ask:

> What object did I ask you to remember, and where was it?

## Technical note

The architecture, interaction protocol, model-to-action boundary, deployment
decisions, measurements, data handling, tradeoffs, and limitations are in the
[two-page technical note](output/pdf/TECHNICAL_NOTE.pdf).

## Useful commands

Windows:

```powershell
.\.conda-env\python.exe -m unittest discover -s tests -q
.\.conda-env\python.exe run.py --smoke-test
.\.conda-env\python.exe run.py --camera-smoke-test
.\.conda-env\python.exe run.py --speech-smoke-test
```

Ubuntu:

```bash
./.conda-env/bin/python -m unittest discover -s tests -q
./.conda-env/bin/python run.py --smoke-test
./.conda-env/bin/python run.py --camera-smoke-test
./.conda-env/bin/python run.py --speech-smoke-test
```

Use `python run.py --help` to see optional camera, microphone, voice, model, and
debug settings.

## Project files

- `run.py` - application entry point
- `src/lamp_character/` - character application code
- `robot/` - supplied URDF, mesh, and reference image
- `scripts/` - model preload, benchmark, and document tools
- `tests/` - automated unit and contract tests
- `docs/` - platform installation guides
- `CHALLENGE.md` and `SUBMISSION.md` - challenge requirements

## Current scope

Lux has been exercised end to end on Windows. The Ubuntu setup path and package
list are included, but camera, microphone, speaker, and visible GUI operation
still need validation on a physical Ubuntu 24.04 laptop. The body is simulated;
there is no real-robot controller or emergency-stop system in this prototype.
