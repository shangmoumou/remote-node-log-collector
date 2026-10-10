param([switch]$Build, [switch]$CheckOnly, [string]$PythonExe)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$logDirectory = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logFile = Join-Path $logDirectory ('setup_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
Start-Transcript -Path $logFile | Out-Null

function Find-Python {
    # Probe real interpreters instead of trusting Windows application aliases.
    param([string]$ExplicitPath)
    $candidates = @()
    if ($ExplicitPath) {
        $candidates += $ExplicitPath
    } else {
        $candidates += @(Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
        $candidates += @(
            (Join-Path $env:ProgramData 'anaconda3\python.exe'),
            (Join-Path $env:USERPROFILE 'anaconda3\python.exe'),
            (Join-Path $env:USERPROFILE 'miniconda3\python.exe')
        )
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($launcher) {
            # Ask the Python launcher for its actual interpreter path.
            $previousPreference = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            $launcherOutput = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>&1
            $launcherExit = $LASTEXITCODE
            $ErrorActionPreference = $previousPreference
            if ($launcherExit -eq 0) { $candidates += [string]($launcherOutput | Select-Object -Last 1) }
        }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        Write-Host ('Checking interpreter: ' + $candidate)
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        # Verify the version and resolve sys.executable; capture diagnostics for the log.
        $probeOutput = & $candidate -c 'import sys; print(sys.executable); print(sys.version); sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>&1
        $probeExit = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
        foreach ($line in $probeOutput) { Write-Host ([string]$line) }
        if ($probeExit -eq 0 -and $probeOutput) {
            return [string]($probeOutput | Select-Object -First 1)
        }
        Write-Host ('Interpreter rejected. Exit code: ' + $probeExit)
    }
    throw 'No working Python 3.10+ found. Install Python or pass -PythonExe with its full path.'
}

try {
    Write-Host '[1/4] Checking Python runtime...'
    # Find-Python returns the executable that passed a real version check.
    $pythonPath = Find-Python -ExplicitPath $PythonExe
    Write-Host ('Selected Python: ' + $pythonPath)
    if ($CheckOnly) { return }
    $dependencyDirectory = Join-Path $PSScriptRoot '.dependencies'
    $env:PYTHONPATH = $dependencyDirectory + ';' + $env:PYTHONPATH
    Write-Host '[2/4] Checking required packages...'
    $check = if ($Build) { 'import tkinter, paramiko, PyInstaller' } else { 'import tkinter, paramiko' }
    & $pythonPath -c $check
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[3/4] Installing packages. Download sizes and detailed steps follow.'
        Write-Host 'Network timeout: 15 seconds per request; retries: 1.'
        $pipArguments = @('-m', 'pip', 'install', '--target', $dependencyDirectory,
            '--timeout', '15', '--retries', '1', '--disable-pip-version-check',
            '--progress-bar', 'on', '--verbose', '--log', ($logFile + '.pip.log'),
            '-r', (Join-Path $PSScriptRoot 'requirements.txt'))
        if ($Build) { $pipArguments += 'pyinstaller>=6,<7' }
        # Run pip in the foreground so its download progress remains visible.
        & $pythonPath @pipArguments
        if ($LASTEXITCODE -ne 0) { throw 'Package installation failed. See the log for network or package errors.' }
        & $pythonPath -c $check
        if ($LASTEXITCODE -ne 0) { throw 'Installed packages failed verification.' }
    } else {
        Write-Host '[3/4] Packages already available; installation skipped.'
    }
    if ($Build) {
        Write-Host '[4/4] Building standalone EXE...'
        # Bundle Python and dependencies into one executable for other Windows PCs.
        & $pythonPath -m PyInstaller --noconfirm --clean --onefile --windowed --name LogDownloader --collect-all paramiko (Join-Path $PSScriptRoot 'log_downloader.py')
        if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
        Write-Host ('EXE ready: ' + (Join-Path $PSScriptRoot 'dist\LogDownloader.exe'))
    } else {
        Write-Host '[4/4] Starting log downloader...'
        & $pythonPath (Join-Path $PSScriptRoot 'log_downloader.py')
        if ($LASTEXITCODE -ne 0) { throw 'Application exited with an error.' }
    }
    Write-Host ('Log: ' + $logFile)
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ('Detailed log: ' + $logFile)
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
