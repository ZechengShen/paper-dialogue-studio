param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $VenvPython)) {
    $Candidates = @()
    if ($env:PODCAST_PYTHON) { $Candidates += $env:PODCAST_PYTHON }
    $Candidates += (Join-Path $env:USERPROFILE 'anaconda3\python.exe')
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand) { $Candidates += $PythonCommand.Source }
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        try {
            $LauncherPython = & $Launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $LauncherPython) { $Candidates += [string]$LauncherPython }
        } catch { }
    }
    $PythonPath = $null
    foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $Candidate)) { continue }
        try {
            & $Candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { $PythonPath = $Candidate; break }
        } catch { }
    }
    if (-not $PythonPath) { throw 'Python 3.9+ was not found. Install Python (3.12 recommended), or set PODCAST_PYTHON to its executable and retry.' }
    & $PythonPath -m venv (Join-Path $ProjectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment (exit $LASTEXITCODE)." }
}

& $VenvPython -c "import sys; print(sys.version)"
if ($LASTEXITCODE -ne 0) { throw 'The existing .venv is invalid. Remove it and rerun setup.ps1.' }

& $VenvPython -m pip install --isolated --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip (exit $LASTEXITCODE)." }

& $VenvPython -m pip install --isolated -r (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "Failed to install audio dependencies (exit $LASTEXITCODE)." }

& $VenvPython -c "import edge_tts, imageio_ffmpeg, yaml, flask, urllib3, certifi, pypdf, bs4; print('PROJECT_SETUP_OK')"
if ($LASTEXITCODE -ne 0) { throw "Audio dependency import check failed (exit $LASTEXITCODE)." }
