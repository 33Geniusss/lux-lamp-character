#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENVIRONMENT_PATH="${PROJECT_ROOT}/.conda-env"
TOOLS_PATH="${PROJECT_ROOT}/.tools"
PRIVATE_CONDA_PATH="${TOOLS_PATH}/miniforge3"
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
        ca-certificates curl build-essential \
        libegl1 libgl1 libportaudio2 espeak-ng \
        libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
        libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
        libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 \
        libxcb-xkb1 libxcb-randr0
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

if [[ "${SKIP_MODELS}" -eq 0 ]]; then
    echo "Preloading the local Whisper and Kokoro models..."
    "${PYTHON_EXECUTABLE}" "${PROJECT_ROOT}/scripts/preload_models.py"
fi

if [[ "${SKIP_CHECKS}" -eq 0 ]]; then
    echo "Running unit tests..."
    "${PYTHON_EXECUTABLE}" -m unittest discover -s "${PROJECT_ROOT}/tests" -v
    echo "Running the PyBullet smoke test..."
    "${PYTHON_EXECUTABLE}" "${PROJECT_ROOT}/run.py" --smoke-test
fi

cat <<'EOF'

Setup complete.
Before using GPT, set OPENAI_API_KEY in this terminal, then run:
  ./.conda-env/bin/python run.py
EOF
