$ErrorActionPreference = 'Stop'

# Resolve repo root from this script's location
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $repoRoot '.venv\Scripts\python.exe'
$pip = Join-Path $repoRoot '.venv\Scripts\pip.exe'

if (-not (Test-Path $venvPy)) {
    Write-Host 'No .venv found in repo root. Create one first:'
    Write-Host '  py -3 -m venv .venv'
    Write-Host 'Then activate it and rerun this script.'
    exit 1
}

& $pip install --upgrade pip setuptools wheel

# Install Kokoro TTS (hexgrad/Kokoro-82M wrapper)
& $pip install "kokoro>=0.9.2"

# Torch is required by Kokoro. If not already installed, try CPU build by default.
try {
  $torchVer = & $venvPy -c "import torch,sys;print(torch.__version__)" 2>$null
  if (-not $torchVer) { throw 'no torch' }
  Write-Host "Torch already installed: $torchVer"
} catch {
  Write-Host 'Installing Torch (CPU build) ...'
  & $pip install --upgrade torch --index-url https://download.pytorch.org/whl/cpu
}

# Python 3.13+ needs audioop backport for WAV post-process
try { & $pip install audioop-lts } catch { Write-Host 'audioop-lts install failed; continuing.' }

Write-Host 'Kokoro setup completed.'

