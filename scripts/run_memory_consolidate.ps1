param(
  [string]$UserId
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot

# Prefer active python, else venv under repo
$py = $null
try { $py = (Get-Command python -ErrorAction Stop).Source } catch { }
if (-not $py -and $env:VIRTUAL_ENV) {
  $cand = Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
  if (Test-Path $cand) { $py = $cand }
}
if (-not $py) {
  $venvPy = Join-Path $repoRoot '.venv\Scripts\python.exe'
  if (Test-Path $venvPy) { $py = $venvPy }
}
if (-not $py) {
  Write-Host 'Python not found. Ensure venv is created and dependencies installed.'
  exit 1
}

$cli = Join-Path $repoRoot 'tools\memory_cli.py'
$argsList = @('consolidate')
if ($UserId) { $argsList += @('--user-id', $UserId) }

& $py $cli @argsList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[memory] Consolidation task finished."
