param([switch]$NoBrowser, [int]$Port = 7860)
$ErrorActionPreference = 'Stop'
$ProjectDir = $PSScriptRoot
$PythonPath = Join-Path $ProjectDir '.venv\Scripts\python.exe'
$AppPath = Join-Path $ProjectDir 'web\app.py'
$RuntimeDir = Join-Path $ProjectDir '.runtime'
$Address = "http://127.0.0.1:$Port/"
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Choose a port between 1024 and 65535.' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Run setup.ps1 once before starting the website.' }
$ExistingHealth = $null
try { $ExistingHealth = Invoke-RestMethod -Uri "${Address}api/health" -TimeoutSec 2 } catch { }
if ($ExistingHealth) {
    if ($ExistingHealth.workflow_version -ne 3) { throw 'An older service is using this port. Close its pages, wait for shutdown, then start again.' }
    Write-Output "Website is already ready: $Address"
    if (-not $NoBrowser) { Start-Process $Address }
    exit 0
}
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
$SavedPort = $env:PORT
$SavedRoot = $env:PAPER_DIALOGUE_AUDIO_PROJECT_DIR
try {
    $env:PORT = [string]$Port
    $env:PAPER_DIALOGUE_AUDIO_PROJECT_DIR = $ProjectDir
    $ServerProcess = Start-Process -FilePath $PythonPath -ArgumentList @('-B', "`"$AppPath`"") -WorkingDirectory $ProjectDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RuntimeDir 'web.stdout.log') -RedirectStandardError (Join-Path $RuntimeDir 'web.stderr.log') -PassThru
} finally {
    $env:PORT = $SavedPort
    $env:PAPER_DIALOGUE_AUDIO_PROJECT_DIR = $SavedRoot
}
$Ready = $false
for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
    try {
        $Health = Invoke-RestMethod -Uri "${Address}api/health" -TimeoutSec 1
        if ($Health.workflow_version -eq 3) { $Ready = $true; break }
    } catch { }
    if ($ServerProcess.HasExited) { break }
    Start-Sleep -Milliseconds 250
}
if (-not $Ready) { throw "Website did not start. Check $RuntimeDir\web.stderr.log" }
Write-Output "V3 website ready: $Address"
Write-Output 'All pages closed -> website and API tasks stop after about 40 seconds. Codex tasks run separately.'
if (-not $NoBrowser) { Start-Process $Address }
