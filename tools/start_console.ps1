$ErrorActionPreference = 'Stop'
$repoPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $repoPath
function Test-ConsolePython([string]$Candidate) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate)) { return $false }
    try {
        & $Candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}
try {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8766/health' -TimeoutSec 2
        if ($health.app -eq 'passport-companion-console') {
            Start-Process 'http://127.0.0.1:8766/'
            exit 0
        }
    } catch { }
    $venvPath = Join-Path $repoPath '.venv-console'
    $consolePython = Join-Path $venvPath 'Scripts\python.exe'
    if (-not (Test-ConsolePython $consolePython)) {
        $candidates = @((Join-Path (Split-Path $repoPath -Parent) 'passport-venv\Scripts\python.exe'))
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $ErrorActionPreference = 'Continue'
            $installed = & py -0p 2>&1
            $ErrorActionPreference = 'Stop'
            foreach ($line in $installed) {
                if ("$line" -match '([A-Za-z]:\\.*?python(?:w)?\.exe)') { $candidates += $matches[1] }
            }
        }
        foreach ($command in @(Get-Command python,python3 -ErrorAction SilentlyContinue)) {
            # WindowsApps can contain a working Python install; validate by running it.
            $candidates += $command.Source
        }
        $selected = $candidates | Where-Object { Test-ConsolePython $_ } | Select-Object -First 1
        if (-not $selected) { throw 'Python 3.10+ is required. Install a current Python from python.org and retry.' }
        if (Test-Path -LiteralPath $venvPath) {
            $backupPath = Join-Path $repoPath ('.venv-console-backup-' + [guid]::NewGuid().ToString('N'))
            if ((Split-Path $venvPath -Parent) -ne $repoPath -or (Split-Path $backupPath -Parent) -ne $repoPath) { throw 'Invalid environment path' }
            Move-Item -LiteralPath $venvPath -Destination $backupPath
        }
        Write-Host "Creating console environment with $selected"
        & $selected -m venv $venvPath
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    }
    & $consolePython -c 'import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in sys.argv[1:]) else 1)' bleak cryptography psutil sounddevice numpy pynput
    if ($LASTEXITCODE -ne 0) {
        & $consolePython -m pip install -r (Join-Path $PSScriptRoot 'requirements-console.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and retry; details are shown above.' }
    }
    $windowlessPython = Join-Path $venvPath 'Scripts\pythonw.exe'
    $entryPoint = Join-Path $PSScriptRoot 'run_console_windowless.py'
    $background = Start-Process -FilePath $windowlessPython -ArgumentList @(('"' + $entryPoint + '"')) -WindowStyle Hidden -PassThru
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8766/health' -TimeoutSec 1
            if ($health.app -eq 'passport-companion-console') {
                Start-Process 'http://127.0.0.1:8766/'
                exit 0
            }
        } catch { }
        if ($background.HasExited) { throw 'Background startup failed. See ~/.codex/passport-console/console.log.' }
        Start-Sleep -Milliseconds 200
    }
    throw 'Console startup timed out. See ~/.codex/passport-console/console.log.'
} catch {
    Write-Host "Console startup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
