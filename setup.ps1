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
    $PythonPath = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $PythonPath) { throw 'Python 3.9+ was not found. Set PODCAST_PYTHON and retry.' }
    & $PythonPath -c "import sys; assert sys.version_info >= (3, 9), sys.version"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.9 or later is required.' }
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
