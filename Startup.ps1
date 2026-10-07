param([switch]$Remove, [string]$PythonExecutable, [string]$DataFolder)
$ErrorActionPreference = 'Stop'
$taskName = 'HomeControl'
if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Get-NetFirewallRule -Name 'HomeControl-Private-8765' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Get-NetFirewallRule -Name 'HomeControl-Tailscale-8765' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Host 'Startup disabled. Usage and saved original settings are preserved.'
    Write-Host 'Pending device and Tweakout CPU recovery tasks are preserved. Keep this folder in place until recovery finishes.'
    exit
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$check = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $check.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Right-click Install-Startup.cmd and choose Run as administrator using your own account.'
}
$pythonPath = $null
if ($PythonExecutable) {
    if (-not (Test-Path -LiteralPath $PythonExecutable)) { throw 'Specified Python executable does not exist.' }
    $pythonPath = & $PythonExecutable -c 'import sys; print(sys.executable)'
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonPath = & py -3 -c 'import sys; print(sys.executable)'
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonPath = & python -c 'import sys; print(sys.executable)'
}
if (-not $pythonPath -or $LASTEXITCODE -ne 0) { throw 'Install Python 3 first.' }
$pythonPath = ($pythonPath | Select-Object -Last 1).Trim()
& $pythonPath -c 'import sys,struct,tkinter; assert sys.version_info >= (3,10) and struct.calcsize(chr(80))==8'
if ($LASTEXITCODE -ne 0) { throw 'Install regular 64-bit Python 3.10 or newer with Tcl/Tk.' }
$windowless = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $windowless)) { throw 'pythonw.exe missing. Repair Python installation.' }
$serverPath = Join-Path $PSScriptRoot 'server.py'
$locationFile = Join-Path $PSScriptRoot 'data-location.txt'
if (-not $DataFolder -and (Test-Path -LiteralPath $locationFile)) { $DataFolder = (Get-Content -LiteralPath $locationFile -Raw).Trim() }
if (-not $DataFolder) { $DataFolder = Join-Path $env:LOCALAPPDATA 'HomeControl' }
$DataFolder = [IO.Path]::GetFullPath($DataFolder)
[System.IO.File]::WriteAllText($locationFile, $DataFolder)
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 2
}
$action = New-ScheduledTaskAction -Execute $windowless -Argument ('"' + $serverPath + '" --background') -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'HomeControl phone dashboard and app tracking.' -Force | Out-Null
Get-NetFirewallRule -Name 'HomeControl-Private-8765' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name 'HomeControl-Private-8765' -DisplayName 'HomeControl (home network)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Program $windowless -Profile Private -RemoteAddress LocalSubnet | Out-Null
Get-NetFirewallRule -Name 'HomeControl-Tailscale-8765' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Start-ScheduledTask -TaskName $taskName
Write-Host 'Installed. Runs quietly now and at sign-in. Keep this folder in place.'
Write-Host 'Run Connection-Info.cmd for the phone address and key.'
