$ErrorActionPreference = 'Stop'
if (-not (Test-Path ..\.venv\python.exe)) { Write-Host 'No .venv found'; exit 1 }
..\.venv\python.exe -c "import torch;print('torch', torch.__version__);print('cuda_available', torch.cuda.is_available());print('device', (torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'))"

