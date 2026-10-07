param([switch]$Disable)
$ErrorActionPreference = 'Stop'
$dataFolder = Join-Path $env:LOCALAPPDATA 'HomeControl'
$location = Join-Path $PSScriptRoot 'data-location.txt'
if (Test-Path -LiteralPath $location) { $dataFolder = (Get-Content -LiteralPath $location -Raw).Trim() }
New-Item -ItemType Directory -Path $dataFolder -Force | Out-Null
$flag = Join-Path $dataFolder 'terminal-enabled.txt'
if ($Disable) {
    if (Test-Path -LiteralPath $flag) { Remove-Item -LiteralPath $flag }
    Write-Host 'Remote terminal disabled.'
} else {
    [IO.File]::WriteAllText($flag, 'enabled')
    Write-Host 'Remote PowerShell enabled for access-key holders. It uses the same privileges as HomeControl.'
}
Write-Host 'The dashboard picks up this change on its next refresh.'
