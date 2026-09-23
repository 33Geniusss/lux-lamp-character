[CmdletBinding()]
param(
    [switch]$SkipModels,
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvironmentPath = Join-Path $ProjectRoot ".conda-env"
$ToolsPath = Join-Path $ProjectRoot ".tools"
$PrivateCondaPath = Join-Path $ToolsPath "miniforge3"
$MiniforgeVersion = "26.7.2-0"
$MiniforgeSha256 = "71cf9519087be74fa53021219ff292beb2fc05fa49e0bb6eb0e0b6b14fccbaab"

function Find-CondaExecutable {
    $privateConda = Join-Path $PrivateCondaPath "Scripts\conda.exe"
    if (Test-Path -LiteralPath $privateConda) {
        return $privateConda
    }

    $command = Get-Command conda -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    return $null
}

function Install-PrivateMiniforge {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "This setup supports 64-bit Windows only."
    }

    New-Item -ItemType Directory -Force -Path $ToolsPath | Out-Null
    $installerName = "Miniforge3-$MiniforgeVersion-Windows-x86_64.exe"
    $installer = Join-Path $env:TEMP $installerName
    $url = "https://github.com/conda-forge/miniforge/releases/download/$MiniforgeVersion/$installerName"

    Write-Host "Conda was not found. Downloading a project-local Miniforge..."
    Invoke-WebRequest -Uri $url -OutFile $installer
    try {
        $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $MiniforgeSha256) {
            throw "Miniforge checksum mismatch. Expected $MiniforgeSha256 but received $actualHash."
        }
        $arguments = @(
            "/S",
            "/InstallationType=JustMe",
            "/AddToPath=0",
            "/RegisterPython=0",
            "/D=$PrivateCondaPath"
        )
        $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Miniforge installer exited with code $($process.ExitCode)."
        }
    }
    finally {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    }
}

Set-Location -LiteralPath $ProjectRoot
Write-Host "Setting up Lamp Character in $ProjectRoot"

$conda = Find-CondaExecutable
if ($null -eq $conda) {
    Install-PrivateMiniforge
    $conda = Find-CondaExecutable
}
if ($null -eq $conda) {
    throw "Conda could not be installed or located."
}

Write-Host "Creating or updating the Python 3.11 environment..."
$previousChannelPriority = $env:CONDA_CHANNEL_PRIORITY
try {
    $env:CONDA_CHANNEL_PRIORITY = "strict"
    & $conda env update `
        --prefix $EnvironmentPath `
        --file (Join-Path $ProjectRoot "environment.yml") `
        --prune
    if ($LASTEXITCODE -ne 0) {
        throw "Conda environment setup failed with code $LASTEXITCODE."
    }
}
finally {
    $env:CONDA_CHANNEL_PRIORITY = $previousChannelPriority
}

$python = Join-Path $EnvironmentPath "python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "The environment Python was not created at $python."
}

if (-not $SkipModels) {
    Write-Host "Preloading the local Whisper and Kokoro models..."
    & $python (Join-Path $ProjectRoot "scripts\preload_models.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Local model preload failed with code $LASTEXITCODE."
    }
}

if (-not $SkipChecks) {
    Write-Host "Running unit tests..."
    & $python -m unittest discover -s (Join-Path $ProjectRoot "tests") -v
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed with code $LASTEXITCODE."
    }

    Write-Host "Running the PyBullet smoke test..."
    & $python (Join-Path $ProjectRoot "run.py") --smoke-test
    if ($LASTEXITCODE -ne 0) {
        throw "PyBullet smoke test failed with code $LASTEXITCODE."
    }
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "Start Lux below. If OPENAI_API_KEY is not set, Lux prompts for it securely:"
Write-Host "  .\.conda-env\python.exe run.py"
