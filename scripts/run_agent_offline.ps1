$ErrorActionPreference = 'Stop'

# Force offline for Hugging Face / Transformers
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'

# Optional: point to a local HF cache if you keep multiple repos
# $env:HF_HOME = 'D:\hf-cache'

# Activate venv and run
if (-not (Test-Path ..\.venv\Scripts\python.exe)) { Write-Host 'No .venv found'; exit 1 }
..\.venv\Scripts\python.exe ..\run_agent.py @Args

