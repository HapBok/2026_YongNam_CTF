param([string]$Distro = 'Ubuntu', [switch]$Mock)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$linuxRoot = (& wsl.exe -d $Distro -- wslpath -u $taskRoot).Trim()
if ($LASTEXITCODE -ne 0) { throw 'WSL path conversion failed' }
$ctl = "$linuxRoot/ctfctl.py"
$initArgs = @('-d', $Distro, '--', 'python3', $ctl, '--root', $linuxRoot, 'status', '--json')
& wsl.exe @initArgs
if ($LASTEXITCODE -ne 0) { throw 'Run init-run and preflight first' }
$logRoot = Join-Path $taskRoot '.runtime/logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$supervisorArgs = "-d $Distro -- python3 `"$ctl`" --root `"$linuxRoot`" start --workers 8 --external-workers"
if ($Mock) { $supervisorArgs += ' --mock' }
Start-Process -FilePath 'wsl.exe' -ArgumentList $supervisorArgs -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'supervisor.stdout.log') -RedirectStandardError (Join-Path $logRoot 'supervisor.stderr.log')
$deadline = [DateTime]::UtcNow.AddSeconds(20)
do {
    Start-Sleep -Milliseconds 500
    $check = (& wsl.exe -d $Distro -- python3 $ctl --root $linuxRoot status --json | ConvertFrom-Json)
} while (-not $check.supervisor_live -and [DateTime]::UtcNow -lt $deadline)
if (-not $check.supervisor_live) { throw 'Supervisor startup failed; see .runtime/logs' }
for ($n = 1; $n -le 8; $n++) {
    $workerId = 'w{0:d2}' -f $n
    $workerArgs = @('-w', '0', 'new-tab', '--title', "CTF $workerId", 'wsl.exe', '-d', $Distro, '--', 'bash', "$linuxRoot/scripts/worker-watch.sh", '--id', $workerId)
    if ($Mock) { $workerArgs += '--mock' }
    & wt.exe @workerArgs
}
Write-Host 'Eight dynamic workers launched. First Ctrl+C pauses the current problem; Ctrl+C while idle exits that worker.'

