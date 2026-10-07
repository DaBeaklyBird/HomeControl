$ErrorActionPreference = 'Stop'
try {
    $dataFolder = Join-Path $env:LOCALAPPDATA 'HomeControl'
    $location = Join-Path $PSScriptRoot 'data-location.txt'
    if (Test-Path -LiteralPath $location) { $dataFolder = (Get-Content -LiteralPath $location -Raw).Trim() }
    $keyPath = Join-Path $dataFolder 'key.txt'
    if (-not (Test-Path -LiteralPath $keyPath)) { throw 'No key found. Run Install-Startup.cmd as administrator first.' }
    $key = (Get-Content -LiteralPath $keyPath -Raw).Trim()
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/status' -Headers @{'X-Access-Key'=$key} -TimeoutSec 20
    } catch {
        throw 'The running server did not accept this key, or is offline. Close any Start.cmd window, then rerun Install-Startup.cmd as administrator from THIS folder. Run Connection-Info.cmd again.'
    }
    Write-Host 'Key verified against the running laptop program.' -ForegroundColor Green
    Write-Host 'Access key (case-sensitive):'
    Write-Host $key
    $addresses = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }
    foreach ($address in $addresses) {
        Write-Host ('iPhone: http://' + $address.IPAddress + ':8765')
        Write-Host ('Automatic sign-in link: http://' + $address.IPAddress + ':8765/#key=' + [uri]::EscapeDataString($key))
    }
    Write-Host 'Keep automatic sign-in links private: they contain your access key.'
} catch { Write-Host $_.Exception.Message -ForegroundColor Yellow; exit 1 }
