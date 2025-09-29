# Lyra Web Server Startup Script
# Usage: .\start_lyra.ps1

Write-Host "🚀 Starting Lyra Web Server..." -ForegroundColor Cyan

# Activate virtual environment
if (Test-Path ".venv\Scripts\Activate.ps1") {
    Write-Host "📦 Activating virtual environment..." -ForegroundColor Yellow
    & .\.venv\Scripts\Activate.ps1
} else {
    Write-Host "❌ Virtual environment not found! Run: python -m venv .venv" -ForegroundColor Red
    exit 1
}

# Check if .env exists
if (!(Test-Path ".env")) {
    Write-Host "⚠️  Warning: .env file not found!" -ForegroundColor Yellow
}

# Start the web server
Write-Host "🌐 Starting Flask server on http://localhost:7860" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Gray
Write-Host ""

python web/server.py
