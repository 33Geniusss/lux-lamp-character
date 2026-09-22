#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENVIRONMENT_PATH="${PROJECT_ROOT}/.conda-env"
TOOLS_PATH="${PROJECT_ROOT}/.tools"
PRIVATE_CONDA_PATH="${TOOLS_PATH}/miniforge3"
PORTAUDIO_COMMIT="17967f32de95f2179e7f7caa9632a79c5d59a2ea"
SKIP_MODELS=0
SKIP_CHECKS=0

for argument in "$@"; do
    case "${argument}" in
        --skip-models) SKIP_MODELS=1 ;;
        --skip-checks) SKIP_CHECKS=1 ;;
        *) echo "Unknown option: ${argument}" >&2; exit 2 ;;
    esac
done

install_system_packages() {
    if ! command -v apt-get >/dev/null 2>&1; then
        echo "This automatic Linux setup currently supports Ubuntu/Debian (apt-get)." >&2
        exit 1
    fi

    local elevate=()
    if [[ "${EUID}" -ne 0 ]]; then
        if ! command -v sudo >/dev/null 2>&1; then
            echo "sudo is required to install Ubuntu system packages." >&2
            exit 1
        fi
        elevate=(sudo)
    fi

    echo "Installing Ubuntu system libraries for Qt, audio, and model setup..."
    "${elevate[@]}" apt-get update
    "${elevate[@]}" apt-get install -y \
        acl ca-certificates curl build-essential cmake git pkg-config \
        libegl1 libgl1 libportaudio2 libasound2-dev libpulse-dev \
        pulseaudio-utils usbutils v4l-utils espeak-ng \
        libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
        libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
        libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 \
        libxcb-xkb1 libxcb-randr0

    if is_wsl && [[ -n "${USER:-}" ]] && [[ "${USER}" != "root" ]]; then
        "${elevate[@]}" usermod -aG video "${USER}"
    fi
}

is_wsl() {
    [[ -n "${WSL_DISTRO_NAME:-}" ]] || grep -qi microsoft /proc/sys/kernel/osrelease
}

install_wsl_portaudio() {
    if ! is_wsl; then
        return
    fi

    local source_path="${TOOLS_PATH}/portaudio-src"
    local build_path="${TOOLS_PATH}/portaudio-build"
    local install_path="${TOOLS_PATH}/portaudio-pulse"
    if [[ -f "${install_path}/lib/libportaudio.so.2" ]]; then
        echo "Using the existing project-local PulseAudio PortAudio build."
        return
    fi

    echo "Building project-local PortAudio with PulseAudio support for WSL..."
    mkdir -p "${source_path}"
    if [[ ! -d "${source_path}/.git" ]]; then
        git -C "${source_path}" init
        git -C "${source_path}" remote add origin https://github.com/PortAudio/portaudio.git
    fi
    git -C "${source_path}" fetch --depth 1 origin "${PORTAUDIO_COMMIT}"
    git -C "${source_path}" checkout --detach FETCH_HEAD
    cmake -S "${source_path}" -B "${build_path}" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="${install_path}" \
        -DPA_BUILD_EXAMPLES=OFF \
        -DPA_BUILD_TESTS=OFF \
        -DPA_BUILD_SHARED_LIBS=ON \
        -DPA_USE_ALSA=ON \
        -DPA_USE_PULSEAUDIO=ON
    cmake --build "${build_path}" --parallel
    cmake --install "${build_path}"
}

configure_wsl_camera() {
    if ! is_wsl; then
        return
    fi

    local powershell_script windows_script output hardware_id device
    mkdir -p "${TOOLS_PATH}"
    powershell_script="${PROJECT_ROOT}/scripts/configure_wsl_camera.ps1"
    windows_script="$(wslpath -w "${powershell_script}")"
    echo "Configuring the Windows USB camera for WSL..."
    output="$(powershell.exe -NoProfile -ExecutionPolicy Bypass \
        -File "${windows_script}" -Distro "${WSL_DISTRO_NAME}")"
    printf '%s\n' "${output}"
    hardware_id="$(printf '%s\n' "${output}" | tr -d '\r' | \
        sed -n 's/^LUX_CAMERA_HARDWARE_ID=//p' | tail -n 1)"
    if [[ ! "${hardware_id}" =~ ^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$ ]]; then
        echo "The Windows camera setup did not return a valid hardware ID." >&2
        exit 1
    fi
    printf '%s\n' "${hardware_id,,}" > "${TOOLS_PATH}/wsl-camera-hardware-id"

    shopt -s nullglob
    for device in /dev/video*; do
        if [[ "${EUID}" -eq 0 ]]; then
            setfacl -m "u:${USER}:rw" "${device}"
        else
            sudo setfacl -m "u:${USER}:rw" "${device}"
        fi
    done
    shopt -u nullglob
}

find_conda() {
    if [[ -x "${PRIVATE_CONDA_PATH}/bin/conda" ]]; then
        printf '%s\n' "${PRIVATE_CONDA_PATH}/bin/conda"
    elif command -v conda >/dev/null 2>&1; then
        command -v conda
    fi
}

install_private_miniforge() {
    local architecture installer_name installer_path url
    architecture="$(uname -m)"
    case "${architecture}" in
        x86_64) installer_name="Miniforge3-Linux-x86_64.sh" ;;
        aarch64|arm64) installer_name="Miniforge3-Linux-aarch64.sh" ;;
        *) echo "Unsupported Linux architecture: ${architecture}" >&2; exit 1 ;;
    esac

    mkdir -p "${TOOLS_PATH}"
    installer_path="$(mktemp --suffix=.sh)"
    url="https://github.com/conda-forge/miniforge/releases/latest/download/${installer_name}"
    echo "Conda was not found. Downloading a project-local Miniforge..."
    curl -fL "${url}" -o "${installer_path}"
    bash "${installer_path}" -b -p "${PRIVATE_CONDA_PATH}"
    rm -f -- "${installer_path}"
}

cd -- "${PROJECT_ROOT}"
echo "Setting up Lamp Character in ${PROJECT_ROOT}"
install_system_packages
configure_wsl_camera

CONDA_EXECUTABLE="$(find_conda || true)"
if [[ -z "${CONDA_EXECUTABLE}" ]]; then
    install_private_miniforge
    CONDA_EXECUTABLE="$(find_conda || true)"
fi
if [[ -z "${CONDA_EXECUTABLE}" ]]; then
    echo "Conda could not be installed or located." >&2
    exit 1
fi

echo "Creating or updating the Python 3.11 environment..."
"${CONDA_EXECUTABLE}" env update \
    --prefix "${ENVIRONMENT_PATH}" \
    --file "${PROJECT_ROOT}/environment.yml" \
    --prune

PYTHON_EXECUTABLE="${ENVIRONMENT_PATH}/bin/python"
if [[ ! -x "${PYTHON_EXECUTABLE}" ]]; then
    echo "The environment Python was not created at ${PYTHON_EXECUTABLE}." >&2
    exit 1
fi

install_wsl_portaudio

if [[ "${SKIP_MODELS}" -eq 0 ]]; then
    echo "Preloading the local Whisper and Kokoro models..."
    "${PYTHON_EXECUTABLE}" "${PROJECT_ROOT}/scripts/preload_models.py"
fi

if [[ "${SKIP_CHECKS}" -eq 0 ]]; then
    echo "Running unit tests..."
    "${PYTHON_EXECUTABLE}" -m unittest discover -s "${PROJECT_ROOT}/tests" -v
    echo "Running the PyBullet smoke test..."
    "${PYTHON_EXECUTABLE}" "${PROJECT_ROOT}/run.py" --smoke-test
    if is_wsl; then
        echo "Running the WSL camera smoke test..."
        "${PYTHON_EXECUTABLE}" "${PROJECT_ROOT}/run.py" --camera-smoke-test
        echo "Running the WSL microphone smoke test..."
        "${PYTHON_EXECUTABLE}" "${PROJECT_ROOT}/run.py" --speech-smoke-test
        echo "Running the WSL speaker smoke test..."
        "${PYTHON_EXECUTABLE}" "${PROJECT_ROOT}/run.py" --audio-output-smoke-test
    fi
fi

cat <<'EOF'

Setup complete. Start Lux with the command below. If OPENAI_API_KEY is not set,
Lux securely prompts for it in the terminal without saving it:
  ./.conda-env/bin/python run.py
EOF
