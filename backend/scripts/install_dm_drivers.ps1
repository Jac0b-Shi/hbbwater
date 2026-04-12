param(
    [string]$DmHome = $env:DM_HOME
)

$ErrorActionPreference = "Stop"

if (-not $DmHome) {
    throw "DM_HOME is not set. Set DM_HOME to the DM8 installation directory first."
}

$packages = @(
    (Join-Path $DmHome "drivers\python\dmPython"),
    (Join-Path $DmHome "drivers\python\dmAsync"),
    (Join-Path $DmHome "drivers\python\dmSQLAlchemy\dmSQLAlchemy2.0")
)

foreach ($package in $packages) {
    if (-not (Test-Path $package)) {
        throw "Driver package not found: $package"
    }

    Write-Host "Installing $package"
    python -m pip install --user $package
}
