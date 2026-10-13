# Exercise the real launcher while replacing only the visible Terminal UI.
# Every recorded tab still starts its real WSL worker hidden, in a separate mock workspace.
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$smokeRoot = Join-Path $taskRoot ('.runtime\launcher-smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null
foreach ($folder in @('src','config','prompts','schemas','scripts','tests')) {
    Copy-Item -LiteralPath (Join-Path $taskRoot $folder) -Destination $smokeRoot -Recurse
}
Copy-Item -LiteralPath (Join-Path $taskRoot 'ctfctl.py') -Destination $smokeRoot
$smokeLinux = (& wsl.exe -d Ubuntu -- wslpath -u $smokeRoot).Trim()
& wsl.exe -d Ubuntu -- python3 "$smokeLinux/ctfctl.py" --root $smokeLinux init-run --mock
if ($LASTEXITCODE -ne 0) { throw 'Mock initialization failed' }
$global:ctfSmokeTabRequests = [System.Collections.Generic.List[object]]::new()
function wt.exe {
    $tabArgs = @($args)
    $global:ctfSmokeTabRequests.Add($tabArgs)
    $start = [Array]::IndexOf($tabArgs, 'wsl.exe')
    if ($start -lt 0) { throw 'Launcher did not request WSL' }
    $nativeArgs = $tabArgs[($start + 1)..($tabArgs.Length - 1)]
    $quoted = ($nativeArgs | ForEach-Object {
        $item = [string]$_
        if ($item -match '[\s"]') { '"' + $item.Replace('"','\"') + '"' } else { $item }
    }) -join ' '
    $workerIndex = [Array]::IndexOf($nativeArgs, '--id')
    $workerId = $nativeArgs[$workerIndex + 1]
    Start-Process -FilePath 'wsl.exe' -ArgumentList $quoted -WindowStyle Hidden -RedirectStandardOutput (Join-Path $smokeRoot ".runtime/logs/$workerId.stdout.log") -RedirectStandardError (Join-Path $smokeRoot ".runtime/logs/$workerId.stderr.log") | Out-Null
}
try {
    & (Join-Path $smokeRoot 'scripts\launch-8.ps1') -Mock
    if ($global:ctfSmokeTabRequests.Count -ne 8) { throw 'Expected exactly eight Terminal tab requests' }
    Start-Sleep -Seconds 8
    $probe = 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute("SELECT COUNT(*) FROM workers").fetchone()[0])'
    $registered = & wsl.exe -d Ubuntu -- python3 -c $probe "$smokeLinux/.runtime/state.db"
    if ([int]$registered -ne 8) { throw "Expected eight registered WSL workers, got $registered" }
    Write-Host 'PASS: eight distinct Terminal requests and eight real WSL worker registrations'
    @{ passed = $true; requested_tabs = 8; registered_workers = 8; visible_ui_tested = $false; workspace = $smokeRoot } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRoot 'reports\launcher-smoke.json') -Encoding UTF8
}
finally {
    $global:ctfSmokeTabRequests | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskRoot 'reports\launcher-requests.json') -Encoding UTF8
    & wsl.exe -d Ubuntu -- python3 "$smokeLinux/ctfctl.py" --root $smokeLinux shutdown --graceful
    Remove-Item Function:\wt.exe -ErrorAction SilentlyContinue
    Remove-Variable -Name ctfSmokeTabRequests -Scope Global -ErrorAction SilentlyContinue
}
