[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$")]
    [string]$HardwareId,
    [string]$Distro = $env:WSL_DISTRO_NAME
)

$ErrorActionPreference = "Stop"
$usbipdCommand = Get-Command usbipd -ErrorAction SilentlyContinue
$usbipd = if ($usbipdCommand) { $usbipdCommand.Source } else { $null }
if (-not $usbipd) {
    $installed = "C:\Program Files\usbipd-win\usbipd.exe"
    if (Test-Path -LiteralPath $installed) {
        $usbipd = $installed
    }
}
if (-not $usbipd) {
    throw "usbipd-win is not installed. Rerun bash setup.sh."
}
if (-not $Distro) {
    throw "Could not determine the WSL distribution name."
}

$json = & $usbipd state | Out-String
$devices = ($json | ConvertFrom-Json).Devices
$pattern = "VID_{0}&PID_{1}" -f ($HardwareId -split ":")[0], ($HardwareId -split ":")[1]
$camera = $devices |
    Where-Object { $_.InstanceId -match [regex]::Escape($pattern) } |
    Select-Object -First 1
if (-not $camera) {
    throw "The configured USB camera $HardwareId is not connected to Windows."
}
if ($camera.ClientIPAddress) {
    exit 0
}

& $usbipd attach --wsl $Distro --hardware-id $HardwareId
if ($LASTEXITCODE -ne 0) {
    throw "Could not attach USB camera $HardwareId to $Distro."
}
