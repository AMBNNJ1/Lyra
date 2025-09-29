param(
  [ValidateSet('118','121')]
  [string]$CudaVersion = '121'
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path ..\.venv\Scripts\pip.exe)) { Write-Host 'No .venv found'; exit 1 }
$pip = Resolve-Path ..\.venv\Scripts\pip.exe

switch ($CudaVersion) {
  '118' { & $pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 }
  '121' { & $pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 }
}

Write-Host "Installed Torch for CUDA $CudaVersion."

