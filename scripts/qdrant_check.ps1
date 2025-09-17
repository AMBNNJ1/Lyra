$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { Write-Host 'No .venv found'; exit 1 }

$script = Join-Path $repoRoot 'tools\qdrant_check.py'
& $py $script @Args
exit $LASTEXITCODE

