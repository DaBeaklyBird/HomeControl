# File validation and transaction logic shared with the isolated updater tests.
if (-not ('HomeControlUpdate.Paths' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.ComponentModel;
namespace HomeControlUpdate {
    public static class Paths {
        [StructLayout(LayoutKind.Sequential, Pack=4, CharSet=CharSet.Unicode)]
        struct FindData {
            public uint attributes; public long creation, access, write;
            public uint sizeHigh, sizeLow, tag, reserved;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string name;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst=14)] public string alternate;
        }
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern IntPtr FindFirstFileW(string path, out FindData data);
        [DllImport("kernel32.dll")] static extern bool FindClose(IntPtr handle);
        public static bool UnsafeLink(string path) {
            FindData data; var handle=FindFirstFileW(path, out data);
            if (handle==new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
            try {
                // OneDrive cloud placeholders do not redirect the path to another entity.
                // Reject junctions, symlinks and unknown reparse tags.
                return (data.attributes & 0x400U)!=0 && (data.tag & 0xffff0fffU)!=0x9000001aU;
            } finally { FindClose(handle); }
        }
    }
}
'@
}
function Test-HcLinked($path) {
    return [HomeControlUpdate.Paths]::UnsafeLink($path)
}
function Assert-HcPath($root, $relative) {
    if (-not $relative -or $relative -notmatch '^[A-Za-z0-9_.-]+([/\\][A-Za-z0-9_.-]+)*$' -or @($relative -split '[/\\]' | Where-Object { $_ -eq '..' -or $_ -eq '.' }).Count) { throw 'Invalid package path.' }
    $fullRoot = [IO.Path]::GetFullPath($root).TrimEnd('\')
    $path = [IO.Path]::GetFullPath((Join-Path $fullRoot $relative))
    if (-not $path.StartsWith($fullRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Package path escapes installation.' }
    $check = $path
    while ($check) {
        if (Test-Path -LiteralPath $check) {
            if (((Get-Item -LiteralPath $check -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -and (Test-HcLinked $check)) { throw "Linked paths are unsupported: $check" }
        }
        $check = Split-Path -Parent $check
    }
    return $path
}
function Get-HcChecksum($file, $mode) {
    if ($mode -eq 'binary') { return (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() }
    if ($mode -ne 'text-lf') { throw 'Unknown checksum mode.' }
    $utf8 = [Text.UTF8Encoding]::new($false,$true)
    $text = $utf8.GetString([IO.File]::ReadAllBytes($file)).TrimStart([char]0xFEFF).Replace("`r`n","`n").TrimEnd([char]10)+"`n"
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash($utf8.GetBytes($text)))).Replace('-','').ToLowerInvariant() } finally { $hash.Dispose() }
}
function Test-HcPackage($source) {
    $manifestPath = Assert-HcPath $source 'update-manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.format -ne 1 -or $manifest.version -notmatch '^\d+\.\d+(\.\d+)?$' -or -not $manifest.files.Count) { throw 'Invalid update manifest.' }
    $seen = @{}
    foreach ($entry in $manifest.files) {
        $path = Assert-HcPath $source $entry.path
        if ($seen.ContainsKey($entry.path.ToLowerInvariant())) { throw 'Duplicate package path.' }
        $seen[$entry.path.ToLowerInvariant()] = $true
        if ($entry.sha256 -notmatch '^[a-f0-9]{64}$' -or (Get-HcChecksum $path $entry.mode) -ne $entry.sha256) { throw "Package checksum failed: $($entry.path). Extract the ZIP again." }
    }
    foreach ($required in @('server.py','Startup.ps1','version.py','Update.ps1','Update-Core.ps1')) { if (-not $seen.ContainsKey($required.ToLowerInvariant())) { throw "Package is missing $required." } }
    return $manifest
}
function Assert-HcRecoveryReady($data) {
    if (Test-Path -LiteralPath (Join-Path $data 'tweakout-cpu.json')) { throw 'CPU recovery is pending. Cancel the mode or wait for recovery, then retry.' }
    $devices = Join-Path $data 'device-recovery.json'
    if (Test-Path -LiteralPath $devices) {
        $records = Get-Content -LiteralPath $devices -Raw | ConvertFrom-Json
        if ($null -eq $records -or $records -isnot [Management.Automation.PSCustomObject]) { throw 'Invalid device recovery journal; leave it in place and repair recovery before updating.' }
    }
}
function Copy-HcAppFile($sourceFile, $destination) {
    $temporary = $destination+'.update-'+[Guid]::NewGuid().ToString('N')+'.tmp'
    try {
        Copy-Item -LiteralPath $sourceFile -Destination $temporary -Force
        for ($attempt=0; $attempt -lt 8; $attempt++) {
            try {
                if (Test-Path -LiteralPath $destination) { [IO.File]::Replace($temporary,$destination,[NullString]::Value) }
                else { [IO.File]::Move($temporary,$destination) }
                return
            } catch [IO.IOException] { if ($attempt -eq 7) { throw }; Start-Sleep -Milliseconds 25 }
        }
    } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
}
function Invoke-HcUpdate($source, $target, $data, $manifest, $task, $python, $backupRoot=(Join-Path $env:LOCALAPPDATA 'HomeControlBackups')) {
    $source = [IO.Path]::GetFullPath($source).TrimEnd('\')
    $target = [IO.Path]::GetFullPath($target).TrimEnd('\')
    if (-not (Test-Path -LiteralPath (Join-Path $target 'server.py'))) { throw 'The old installation folder must contain server.py.' }
    if ($source -eq $target -or $source.StartsWith($target+'\',[StringComparison]::OrdinalIgnoreCase) -or $target.StartsWith($source+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Extract the update to a separate folder outside the old installation.' }
    $entries = @($manifest.files.path) + @('update-manifest.json','data-location.txt') | Select-Object -Unique
    foreach ($relative in $entries) { $null = Assert-HcPath $target $relative }
    $null = Assert-HcPath $data 'key.txt'
    $null = Assert-HcPath $backupRoot 'path-check'
    Suspend-HcControls $data
    Assert-HcRecoveryReady $data
    $backup = Join-Path $backupRoot ((Split-Path -Leaf $target)+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[Guid]::NewGuid().ToString('N').Substring(0,6))
    New-Item -ItemType Directory -Path $backup | Out-Null
    Protect-HcBackup $backup
    Write-Host "Backup: $backup"
    Save-HcTask $task $backup
    $copied = @(); $stopped = $false; $taskChanged = $false; $deviceLock = $null
    try {
        $stopped = $true
        Stop-HcApp $task $target
        $deviceLock = Lock-HcRecovery $data
        Assert-HcRecoveryReady $data
        foreach ($relative in $entries) {
            $old = Join-Path $target $relative
            if (Test-Path -LiteralPath $old) {
                $saved = Join-Path (Join-Path $backup 'app') $relative
                New-Item -ItemType Directory -Path (Split-Path -Parent $saved) -Force | Out-Null
                Copy-Item -LiteralPath $old -Destination $saved -Force
            }
        }
        if (Test-Path -LiteralPath $data) {
            if (@(Get-ChildItem -LiteralPath $data -Recurse -Force | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -and (Test-HcLinked $_.FullName) }).Count) { throw 'Runtime data contains linked files; use a normal local data folder.' }
            Copy-Item -LiteralPath $data -Destination (Join-Path $backup 'runtime') -Recurse
        }
        foreach ($relative in @($manifest.files.path)+@('update-manifest.json')) {
            $destination = Assert-HcPath $target $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            $copied += $relative
            Copy-HcAppFile (Join-Path $source $relative) $destination
        }
        $copied += 'data-location.txt'
        Unlock-HcRecovery $deviceLock; $deviceLock = $null
        $taskChanged = $true
        Set-HcStartup $target $python $data
        Test-HcHealth $data $manifest.version
        Write-Host "HomeControl $($manifest.version) updated and running. Automatic startup at Windows sign-in is ON."
        Write-Host 'Your access key, history and settings were preserved. Refresh the phone dashboard.'
        Write-Host 'Run Connection-Info.cmd in the installed folder for the address and key. Keep the backup private.'
    } catch {
        $failure = $_.Exception.Message
        try {
            if ($taskChanged) { Stop-HcApp (Get-HcTask) $target }
            foreach ($relative in $copied) {
                $destination = Assert-HcPath $target $relative
                $old = Join-Path (Join-Path $backup 'app') $relative
                if (Test-Path -LiteralPath $old) { Copy-HcAppFile $old $destination }
                elseif (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination }
            }
            if ($stopped) { Restore-HcTask $task $backup }
        } catch { throw "Update failed: $failure. Automatic rollback also failed: $($_.Exception.Message). Backup: $backup" }
        throw "Update failed; app files and startup configuration were rolled back. $failure. Backup: $backup"
    } finally { if ($deviceLock) { Unlock-HcRecovery $deviceLock } }
}
