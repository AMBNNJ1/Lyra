$ErrorActionPreference = 'Stop'

# Resolve repo root from this script's location
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $repoRoot '.venv\Scripts\python.exe'

# Prefer active shell python, else venv python under repo
$py = $null
try {
  $cmd = Get-Command python -ErrorAction Stop
  $py = $cmd.Source
} catch {
  # ignore
}
if (-not $py -and $env:VIRTUAL_ENV) {
  $cand = Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
  if (Test-Path $cand) { $py = $cand }
}
if (-not $py -and (Test-Path $venvPy)) { $py = $venvPy }

if (-not $py) {
  Write-Host 'Python not found. Activate your venv or install Python.'
  Write-Host 'Examples:'
  Write-Host '  py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1'
  Write-Host '  powershell -File scripts\install_deps.ps1'
  exit 1
}

$initPy = Join-Path $repoRoot 'tools\init_memory_db.py'
& $py $initPy --index @args
if ($LASTEXITCODE -ne 0) {
  Write-Host "Initializer exited with code $LASTEXITCODE"
  exit $LASTEXITCODE
}

Write-Host "Done. Memory initialized (provider from .env or args)."
