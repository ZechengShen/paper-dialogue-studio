param(
    [Parameter(Mandatory = $true)]
    [string]$Script,
    [Parameter(Mandatory = $true)]
    [string]$OutDir,
    [switch]$Pilot
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Config = Join-Path $ProjectRoot 'config\podcast.yaml'
$Synthesizer = Join-Path $ProjectRoot '.agents\skills\paper-dialogue-podcast\scripts\synthesize_podcast.py'

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & (Join-Path $ProjectRoot 'setup.ps1')
}

$ResolvedScript = (Resolve-Path -LiteralPath $Script).Path
$ResolvedOut = if ([System.IO.Path]::IsPathRooted($OutDir)) { [System.IO.Path]::GetFullPath($OutDir) } else { [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutDir)) }
$SynthArgs = @('-B', $Synthesizer, '--script', $ResolvedScript, '--config', $Config, '--out', $ResolvedOut)
if ($Pilot) { $SynthArgs += '--pilot' }
& $VenvPython @SynthArgs
exit $LASTEXITCODE

