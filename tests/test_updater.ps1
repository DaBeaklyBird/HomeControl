$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'Update.ps1')
$script:fixture = Join-Path ([IO.Path]::GetTempPath()) ('HomeControl-updater-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $script:fixture | Out-Null
$script:checks = 0
function Assert($value,$message) { if (-not $value) { throw $message }; $script:checks++ }
function Throws($action,$pattern) { try { & $action; throw 'Expected failure did not occur' } catch { Assert ($_.Exception.Message -match $pattern) $_.Exception.Message } }
# System operations are substituted. Only temporary files are really copied.
function Suspend-HcControls($data) { $script:calls.Add('cancel') }
function Stop-HcApp($task,$target) { $script:calls.Add('stop') }
function Protect-HcBackup($path) { $script:calls.Add('private-backup'); $script:lastBackup=$path }
function Save-HcTask($task,$backup) { $script:calls.Add('save-task') }
function Get-HcTask { return $script:task }
function Set-HcStartup($target,$python,$data) {
    $script:calls.Add('startup')
    [IO.File]::WriteAllText((Join-Path $target 'data-location.txt'),$data)
    if ($script:fail -eq 'startup') { throw 'simulated startup failure' }
}
function Test-HcHealth($data,$version) { $script:calls.Add('health'); if ($script:fail -eq 'health') { throw 'simulated health failure' } }
function Restore-HcTask($task,$backup) { $script:calls.Add('rollback-task') }
function New-Fixture($name) {
    $root = Join-Path $script:fixture $name
    $source = Join-Path $root 'source'; $target = Join-Path $root 'installed'; $data = Join-Path $root 'data'
    foreach ($dir in @($source,$target,$data)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $entries = @()
    foreach ($name in @('server.py','Startup.ps1','version.py','Update.ps1','Update-Core.ps1','new-file.txt')) {
        $path = Join-Path $source $name
        [IO.File]::WriteAllText($path,'new '+$name)
        $entries += @{path=$name;mode='text-lf';sha256=(Get-HcChecksum $path 'text-lf')}
        if ($name -ne 'new-file.txt') { [IO.File]::WriteAllText((Join-Path $target $name),'old '+$name) }
    }
    [IO.File]::WriteAllText((Join-Path $target 'data-location.txt'),'original-location')
    [IO.File]::WriteAllText((Join-Path $data 'key.txt'),'private-test-key')
    [IO.File]::WriteAllText((Join-Path $data 'usage.sqlite'),'test-history')
    [IO.File]::WriteAllText((Join-Path $data 'device-selections.json'),'test-selections')
    $manifest = @{format=1;version='3.7';files=$entries}
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $source 'update-manifest.json') -Encoding UTF8
    $script:calls = [Collections.Generic.List[string]]::new(); $script:fail=''
    $script:task = [pscustomobject]@{State='Running'}
    $env:LOCALAPPDATA = $root
    return @{source=$source;target=$target;data=$data;manifest=(Test-HcPackage $source)}
}
try {
    $f = New-Fixture 'success'
    Invoke-HcUpdate $f.source $f.target $f.data $f.manifest $script:task 'test-python'
    Assert ((Get-Content -LiteralPath (Join-Path $f.target 'server.py') -Raw) -eq 'new server.py') 'App file was not updated'
    Assert ($script:calls.IndexOf('stop') -lt $script:calls.IndexOf('startup')) 'Startup order wrong'
    Assert ($script:calls.Contains('health') -and -not $script:calls.Contains('rollback-task')) 'Health check missing'
    Assert ((Get-Content -LiteralPath (Join-Path $f.data 'key.txt') -Raw) -eq 'private-test-key') 'Key changed'
    Assert ((Get-Content -LiteralPath (Join-Path $f.data 'usage.sqlite') -Raw) -eq 'test-history') 'History changed'
    $backup = $script:lastBackup
    Assert ((Get-Content -LiteralPath (Join-Path $backup 'runtime/key.txt') -Raw) -eq 'private-test-key') 'Runtime backup missing'
    Assert ((Get-Content -LiteralPath (Join-Path $backup 'app/server.py') -Raw) -eq 'old server.py') 'App backup missing'
    foreach ($failure in @('startup','health')) {
        $f = New-Fixture $failure; $script:fail=$failure
        Throws { Invoke-HcUpdate $f.source $f.target $f.data $f.manifest $script:task 'test-python' } 'rolled back'
        Assert ((Get-Content -LiteralPath (Join-Path $f.target 'server.py') -Raw) -eq 'old server.py') 'Old source not restored'
        Assert (-not (Test-Path -LiteralPath (Join-Path $f.target 'new-file.txt'))) 'New file not removed on rollback'
        Assert ((Get-Content -LiteralPath (Join-Path $f.target 'data-location.txt') -Raw) -eq 'original-location') 'Data location not restored'
        Assert ($script:calls.Contains('rollback-task')) 'Task not rolled back'
        Assert ((Get-Content -LiteralPath (Join-Path $f.data 'device-selections.json') -Raw) -eq 'test-selections') 'Preferences changed'
    }
    $f = New-Fixture 'missing-task'; $script:task=$null
    Invoke-HcUpdate $f.source $f.target $f.data $f.manifest $null 'test-python'
    Assert ($script:calls.Contains('startup')) 'Missing task was not created'
    $f = New-Fixture 'checksum'
    $textPath = Join-Path $f.source 'line-endings.txt'
    [IO.File]::WriteAllText($textPath,"line`r`n")
    $expectedHash = Get-HcChecksum $textPath 'text-lf'
    [IO.File]::WriteAllText($textPath,"line`n")
    Assert ((Get-HcChecksum $textPath 'text-lf') -eq $expectedHash) 'Line ending normalization differs'
    Add-Content -LiteralPath (Join-Path $f.source 'server.py') -Value 'tampered'
    Throws { Test-HcPackage $f.source } 'checksum failed'
    foreach ($relative in @('../escape','C:\escape','dir/../../escape','dir:stream','/root')) { Throws { Assert-HcPath $f.target $relative } 'Invalid package path' }
    $f = New-Fixture 'pending'
    [IO.File]::WriteAllText((Join-Path $f.data 'tweakout-cpu.json'),'{}')
    Throws { Invoke-HcUpdate $f.source $f.target $f.data $f.manifest $script:task 'test-python' } 'CPU recovery is pending'
    Assert (-not $script:calls.Contains('stop')) 'Stopped while CPU recovery pending'
    Remove-Item -LiteralPath (Join-Path $f.data 'tweakout-cpu.json')
    [IO.File]::WriteAllText((Join-Path $f.data 'device-recovery.json'),'{"device":{"deadline":1}}')
    $recoveryBefore = Get-Content -LiteralPath (Join-Path $f.data 'device-recovery.json') -Raw
    Invoke-HcUpdate $f.source $f.target $f.data $f.manifest $script:task 'test-python'
    Assert ((Get-Content -LiteralPath (Join-Path $f.data 'device-recovery.json') -Raw) -eq $recoveryBefore) 'Disconnected recovery records changed'
    [IO.File]::WriteAllText((Join-Path $f.data 'device-recovery.json'),'{}'); Assert-HcRecoveryReady $f.data
    Throws { Invoke-HcUpdate $f.target $f.target $f.data $f.manifest $script:task 'test-python' } 'separate folder'
    $f = New-Fixture 'partial-copy'
    $originalCopy = ${function:Copy-HcAppFile}
    function Copy-HcAppFile($sourceFile,$destination) {
        if ($sourceFile -eq (Join-Path $f.source 'new-file.txt')) { throw 'simulated copy failure' }
        & $originalCopy $sourceFile $destination
    }
    Throws { Invoke-HcUpdate $f.source $f.target $f.data $f.manifest $script:task 'test-python' } 'rolled back'
    Assert ((Get-Content -LiteralPath (Join-Path $f.target 'server.py') -Raw) -eq 'old server.py') 'Partial copy not rolled back'
    Assert ($script:calls.Contains('rollback-task')) 'Stopped task not restored after copy failure'
    ${function:Copy-HcAppFile} = $originalCopy
    $link = Join-Path $script:fixture 'junction'
    New-Item -ItemType Junction -Path $link -Target $f.source | Out-Null
    Throws { Assert-HcPath $link 'server.py' } 'Linked paths'
    # Remove only the junction, never its target, before recursive fixture cleanup.
    [IO.Directory]::Delete($link)
    Write-Host "Updater checks passed: $script:checks assertions; success, rollback, new task, preservation, corruption, paths and pending recovery."
} finally {
    # Resolve and verify the disposable workspace before recursive removal.
    $resolved = [IO.Path]::GetFullPath($script:fixture)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    if ($resolved.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolved) -like 'HomeControl-updater-test-*') { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
