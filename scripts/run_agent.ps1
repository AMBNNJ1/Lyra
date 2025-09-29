$ErrorActionPreference = 'Stop'
# Resolve paths relative to this script's directory
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$pyDefault = Join-Path $root '.venv/Scripts/python.exe'
$py311 = Join-Path $root '.venv311/Scripts/python.exe'
$py = $pyDefault
$use311 = $false
try {
  $cfg = Get-Content (Join-Path $root 'config.yaml') -Raw
} catch {
  $cfg = ''
}
# Prefer Python 3.11 venv when using Kokoro TTS (kokoro wheels require <3.13)
if ($env:TTS_ENGINE -and $env:TTS_ENGINE.ToLower() -eq 'kokoro') { $use311 = $true }
elseif ($cfg -match "(?m)^\s*engine:\s*kokoro\b") { $use311 = $true }
if ($use311 -and (Test-Path $py311)) { $py = $py311 }
$entry = Join-Path $root 'run_agent.py'
if (-not (Test-Path $py)) { Write-Host 'No suitable venv found'; exit 1 }

# Ensure console + Python use UTF-8 so emojis render correctly
try {
  # PowerShell 5/7: set output encoding to UTF-8
  [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
  $OutputEncoding = [Console]::OutputEncoding
} catch {}
try { $env:PYTHONIOENCODING = 'utf-8' } catch {}
try { $env:PYTHONUTF8 = '1' } catch {}

& $py $entry @Args
