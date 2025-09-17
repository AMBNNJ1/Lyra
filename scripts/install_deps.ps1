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

# Core runtime deps
& $pip install python-dotenv pyyaml requests websockets

# TTS: Kokoro only
& $pip install "kokoro>=0.9.2"

# Sentiment (text)
& $pip install vaderSentiment

# Optional: Transformers if you plan to run local HF models
# (Will not download models; just installs the library.)
# & $pip install transformers

# Optional: qwen-vl-utils for VLM (vision) helpers
# & $pip install "qwen-vl-utils[decord]==0.0.8"

# Memory (local RAG) dependencies
# Light: numpy + rapidfuzz for scoring; sentence-transformers for local embeddings/rerankers.
& $pip install "numpy>=2.1.0" rapidfuzz
& $pip install sentence-transformers
& $pip install httpx trafilatura tenacity pydantic
& $pip install flask
# Vector DB: using local SQLite (default) or remote Qdrant
# Qdrant client (for remote vector DB)
& $pip install qdrant-client
# Python 3.13 removed audioop; install backport for WAV post-processing
try {
  & $pip install audioop-lts
} catch {
  Write-Host 'audioop-lts install failed; audio post-processing will be skipped.'
}
try {
  & $pip install faiss-cpu
} catch {
  Write-Host 'faiss-cpu install failed (often on Windows); continuing with lexical-only retrieval.'
}

Write-Host 'Dependencies installed.'

