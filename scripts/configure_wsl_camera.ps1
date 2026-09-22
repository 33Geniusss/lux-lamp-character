[CmdletBinding()]
param(
    [string]$Distro = $env:WSL_DISTRO_NAME,
    [string]$BusId = ""
)

$ErrorActionPreference = "Stop"

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-Usbipd {
    $command = Get-Command usbipd -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $installed = "C:\Program Files\usbipd-win\usbipd.exe"
    if (Test-Path -LiteralPath $installed) {
        return $installed
    }
    return $null
}

function Invoke-ElevatedSelf {
    param([string]$SelectedBusId = "")

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $PSCommandPath),
        "-Distro", ('"{0}"' -f $Distro)
    )
    if ($SelectedBusId) {
        $arguments += @("-BusId", $SelectedBusId)
    }
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -Verb RunAs `
        -ArgumentList $arguments `
        -Wait `
        -PassThru
    if ($process.ExitCode -ne 0) {
        throw "The elevated camera setup exited with code $($process.ExitCode)."
    }
}

function Get-UsbipdState {
    param([string]$Usbipd)

    $json = & $Usbipd state | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "usbipd state failed."
    }
    return ($json | ConvertFrom-Json).Devices
}

function Select-CameraDevice {
    param(
        [object[]]$Devices,
        [string]$SelectedBusId = ""
    )

    if ($SelectedBusId) {
        return $Devices | Where-Object BusId -eq $SelectedBusId | Select-Object -First 1
    }

    $cameraHardwareIds = @(
        Get-PnpDevice -PresentOnly -Class Camera -ErrorAction SilentlyContinue |
            Where-Object { $_.Status -eq "OK" -and $_.InstanceId -match "^USB\\" } |
            ForEach-Object {
                if ($_.InstanceId -match "VID_([0-9A-F]{4})&PID_([0-9A-F]{4})") {
                    "{0}:{1}" -f $Matches[1].ToLowerInvariant(), $Matches[2].ToLowerInvariant()
                }
            } |
            Select-Object -Unique
    )

    $candidates = foreach ($device in $Devices) {
        if ($device.InstanceId -match "VID_([0-9A-F]{4})&PID_([0-9A-F]{4})") {
            $hardwareId = "{0}:{1}" -f `
                $Matches[1].ToLowerInvariant(), `
                $Matches[2].ToLowerInvariant()
            if ($hardwareId -in $cameraHardwareIds) {
                [PSCustomObject]@{
                    Device = $device
                    HardwareId = $hardwareId
                    Priority = if ($device.Description -match "(?i)\b(IR|Depth)\b") { 1 } else { 0 }
                }
            }
        }
    }
    if (-not $candidates) {
        $candidates = foreach ($device in $Devices) {
            if (
                $device.Description -match "(?i)camera" -and
                $device.InstanceId -match "VID_([0-9A-F]{4})&PID_([0-9A-F]{4})"
            ) {
                [PSCustomObject]@{
                    Device = $device
                    HardwareId = "{0}:{1}" -f `
                        $Matches[1].ToLowerInvariant(), `
                        $Matches[2].ToLowerInvariant()
                    Priority = if ($device.Description -match "(?i)\b(IR|Depth)\b") { 1 } else { 0 }
                }
            }
        }
    }
    return ($candidates | Sort-Object Priority, { $_.Device.BusId } | Select-Object -First 1)
}

if (-not $Distro) {
    throw "Could not determine the WSL distribution name. Pass -Distro explicitly."
}

$usbipd = Find-Usbipd
if (-not $usbipd) {
    if (-not (Test-Administrator)) {
        Write-Host "Windows administrator approval is required to install usbipd-win."
        Invoke-ElevatedSelf -SelectedBusId $BusId
        $usbipd = Find-Usbipd
    } else {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "winget is required to install usbipd-win automatically."
        }
        & $winget.Source install --interactive --exact dorssel.usbipd-win `
            --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "usbipd-win installation failed with code $LASTEXITCODE."
        }
        $usbipd = Find-Usbipd
    }
}
if (-not $usbipd) {
    throw "usbipd-win is not available after installation."
}

$devices = @(Get-UsbipdState -Usbipd $usbipd)
$selection = Select-CameraDevice -Devices $devices -SelectedBusId $BusId
if (-not $selection) {
    throw "No active USB camera was found. Check Windows Camera permissions and Device Manager."
}
if ($selection.PSObject.Properties.Name -contains "Device") {
    $camera = $selection.Device
    $hardwareId = $selection.HardwareId
} else {
    $camera = $selection
    if ($camera.InstanceId -notmatch "VID_([0-9A-F]{4})&PID_([0-9A-F]{4})") {
        throw "Could not determine the camera hardware ID for BUSID $($camera.BusId)."
    }
    $hardwareId = "{0}:{1}" -f `
        $Matches[1].ToLowerInvariant(), `
        $Matches[2].ToLowerInvariant()
}

if (-not $camera.PersistedGuid) {
    if (-not (Test-Administrator)) {
        Write-Host "Windows administrator approval is required to share $($camera.Description)."
        Invoke-ElevatedSelf -SelectedBusId $camera.BusId
    } else {
        & $usbipd bind --busid $camera.BusId
        if ($LASTEXITCODE -ne 0) {
            throw "Could not share camera BUSID $($camera.BusId)."
        }
    }
    $devices = @(Get-UsbipdState -Usbipd $usbipd)
    $camera = $devices | Where-Object BusId -eq $camera.BusId | Select-Object -First 1
}

if (-not $camera.ClientIPAddress) {
    & $usbipd attach --wsl $Distro --busid $camera.BusId
    if ($LASTEXITCODE -ne 0) {
        throw "Could not attach camera BUSID $($camera.BusId) to $Distro."
    }
}

Write-Output "LUX_CAMERA_BUSID=$($camera.BusId)"
Write-Output "LUX_CAMERA_HARDWARE_ID=$hardwareId"
Write-Output "LUX_CAMERA_DESCRIPTION=$($camera.Description)"
