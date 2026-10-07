param([string]$InstallFolder, [switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Update-Core.ps1')

function Get-HcTask { Get-ScheduledTask -TaskName HomeControl -ErrorAction SilentlyContinue }
function Lock-HcRecovery($data) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try { $suffix=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($data).ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,12) } finally { $hash.Dispose() }
    $mutex = [Threading.Mutex]::new($false,('Global\HomeControl-DeviceRecovery-'+$suffix))
    $owned = $false
    try {
        try { $owned=$mutex.WaitOne(30000) } catch [Threading.AbandonedMutexException] { $owned=$true }
        if (-not $owned) { throw 'Device recovery is busy; no app files were replaced. Retry shortly.' }
        return $mutex
    } catch { $mutex.Dispose(); throw }
}
function Unlock-HcRecovery($mutex) { $mutex.ReleaseMutex(); $mutex.Dispose() }
function Stop-HcApp($task, $target) {
    if ($task) { Disable-ScheduledTask -TaskName HomeControl | Out-Null; Stop-ScheduledTask -TaskName HomeControl }
    for ($attempt=0; $attempt -lt 10; $attempt++) {
        $listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
        if (-not $listeners.Count) { return }
        foreach ($processId in ($listeners.OwningProcess | Select-Object -Unique)) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId"
            $server = Join-Path $target 'server.py'
            if ($process.Name -notmatch '^python(w)?\.exe$' -or -not $process.CommandLine -or $process.CommandLine.IndexOf($server,[StringComparison]::OrdinalIgnoreCase) -lt 0) {
                throw 'Port 8765 is used by a different or unidentifiable app. Close it locally and retry.'
            }
            Stop-Process -Id $processId -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 300
    }
    throw 'The old app did not stop; no app files were replaced.'
}
function Suspend-HcControls($data) {
    if (-not @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue).Count) { return }
    $keyPath = Join-Path $data 'key.txt'
    if (-not (Test-Path -LiteralPath $keyPath)) { throw 'Cannot find the installed access key. Run Connection-Info.cmd in the old folder first.' }
    $headers = @{'X-Access-Key'=(Get-Content -LiteralPath $keyPath -Raw).Trim()}
    $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/status' -Headers $headers -TimeoutSec 20
    foreach ($route in @('/api/power/cancel','/api/tweakout/cancel','/api/lag/cancel','/api/network')) {
        $body = '{}'; if ($route -eq '/api/network') { $body = '{"mbps":null}' }
        try { $null = Invoke-RestMethod -Uri ('http://127.0.0.1:8765'+$route) -Method Post -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec 20 }
        catch { if (-not $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 404) { throw "Could not cancel $route. Cancel active controls on the dashboard, then retry." } }
    }
}
function Save-HcTask($task, $backup) {
    if ($task) { Export-ScheduledTask -TaskName HomeControl | Set-Content -LiteralPath (Join-Path $backup 'startup-task.xml') -Encoding Unicode }
}
function Set-HcStartup($target, $python, $data) {
    & (Join-Path $target 'Startup.ps1') -PythonExecutable $python -DataFolder $data
    $task = Get-HcTask
    if (-not $task -or -not $task.Settings.Enabled -or -not @($task.Triggers | Where-Object { $_.Enabled -and $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' }).Count) { throw 'The sign-in startup task was not enabled.' }
}
function Restore-HcTask($task, $backup) {
    $current = Get-HcTask
    if ($current) { Stop-ScheduledTask -TaskName HomeControl -ErrorAction SilentlyContinue }
    if ($task) {
        $xml = Get-Content -LiteralPath (Join-Path $backup 'startup-task.xml') -Raw
        Register-ScheduledTask -TaskName HomeControl -Xml $xml -Force | Out-Null
        if ($task.State -eq 'Running') { Start-ScheduledTask -TaskName HomeControl }
    } elseif ($current) {
        Unregister-ScheduledTask -TaskName HomeControl -Confirm:$false
        Get-NetFirewallRule -Name 'HomeControl-Private-8765' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    }
}
function Test-HcHealth($data, $version) {
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        try {
            $key = (Get-Content -LiteralPath (Join-Path $data 'key.txt') -Raw).Trim()
            $state = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/status' -Headers @{'X-Access-Key'=$key} -TimeoutSec 3
            if ($state.version -eq $version -and (Get-HcTask).State -eq 'Running') { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw 'The updated version did not pass its authenticated startup check.'
}
function Protect-HcBackup($path) {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($owner in @($sid,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    }
    Set-Acl -LiteralPath $path -AclObject $acl
}
function Get-HcPython($task) {
    $candidate = $null
    if ($task -and $task.Actions[0].Execute) { $candidate = Join-Path (Split-Path -Parent $task.Actions[0].Execute) 'python.exe' }
    if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { $candidate = & py -3 -c 'import sys; print(sys.executable)' }
        elseif (Get-Command python -ErrorAction SilentlyContinue) { $candidate = & python -c 'import sys; print(sys.executable)' }
    }
    if (-not $candidate) { throw 'Install 64-bit Python 3.10 or newer, including Tcl/Tk, then retry.' }
    $candidate = ($candidate | Select-Object -Last 1).Trim()
    & $candidate -c 'import sys,struct,tkinter; assert sys.version_info >= (3,10) and struct.calcsize(chr(80))==8'
    if ($LASTEXITCODE -ne 0) { throw 'HomeControl requires 64-bit Python 3.10+ with Tcl/Tk.' }
    return $candidate
}
function Start-HcUpdate {
    $source = [IO.Path]::GetFullPath($PSScriptRoot)
    $manifest = Test-HcPackage $source
    if ($ValidateOnly) { Write-Host "Verified $($manifest.files.Count) package files. No changes made."; return }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Right-click Update.cmd and choose Run as administrator using the account that installed HomeControl.' }
    $task = Get-HcTask
    if ($task) {
        $owner = [Security.Principal.NTAccount]::new($task.Principal.UserId).Translate([Security.Principal.SecurityIdentifier])
        if ($owner -ne $identity.User) { throw 'Run this updater using the Windows account that owns the HomeControl startup task.' }
    }
    $folder = $InstallFolder
    if (-not $folder -and $task) { $folder = $task.Actions[0].WorkingDirectory }
    if (-not $folder) { $folder = Read-Host 'Full path of your OLD HomeControl folder (containing server.py)' }
    $target = [IO.Path]::GetFullPath($folder.Trim('"'))
    if ($task -and [IO.Path]::GetFullPath($task.Actions[0].WorkingDirectory).TrimEnd('\') -ne $target.TrimEnd('\')) { throw 'The chosen folder differs from the startup task installation.' }
    $data = Join-Path $env:LOCALAPPDATA 'HomeControl'
    $location = Join-Path $target 'data-location.txt'
    if (Test-Path -LiteralPath $location) { $data = (Get-Content -LiteralPath $location -Raw).Trim() }
    if ($env:HOMECONTROL_DATA -and [IO.Path]::GetFullPath($env:HOMECONTROL_DATA) -ne [IO.Path]::GetFullPath($data)) { throw 'Remove the HOMECONTROL_DATA test override before updating your installed app.' }
    $python = Get-HcPython $task
    Invoke-HcUpdate $source $target $data $manifest $task $python
}
if ($MyInvocation.InvocationName -ne '.') {
    $mutex = [Threading.Mutex]::new($false,'Global\HomeControl-Update')
    $owned = $false
    try {
        try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
        if (-not $owned) { throw 'Another HomeControl update is already running.' }
        Start-HcUpdate
    } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
    finally { if ($owned) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
}
