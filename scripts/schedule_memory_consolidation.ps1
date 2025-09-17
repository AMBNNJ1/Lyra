param(
  [object]$Time,
  [string]$TaskName,
  [string]$UserId,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'

# Backward-compatible defaults (avoid default assignments in param for older PS)
if (-not $Time -or "$Time".Trim() -eq '') { $Time = '02:30' }
if (-not $TaskName -or "$TaskName".Trim() -eq '') { $TaskName = 'NeuroMemoryConsolidate' }

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $repoRoot 'scripts\run_memory_consolidate.ps1'

if (-not (Test-Path $scriptPath)) {
  Write-Host "Script not found: $scriptPath"
  exit 1
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" $(if ($UserId) {"--user-id $UserId"} else {''})"
# Ensure -At is a [datetime] or a parseable string HH:mm
function Resolve-AtTime([object]$val) {
  if ($val -is [datetime]) { return $val }
  if ($val -is [timespan]) {
    $ts = [timespan]$val
    return (Get-Date -Hour $ts.Hours -Minute $ts.Minutes -Second 0)
  }
  $s = ($val | Out-String).Trim()
  # First try exact formats
  foreach ($fmt in @('H:mm','HH:mm')) {
    try { return [datetime]::ParseExact($s, $fmt, $null) } catch { }
  }
  # Try TimeSpan parsing (e.g., 2:30)
  try {
    $ts2 = [timespan]::Parse($s)
    return (Get-Date -Hour $ts2.Hours -Minute $ts2.Minutes -Second 0)
  } catch { }
  # Try general DateTime parse
  try { return [datetime]::Parse($s) } catch { }
  throw "Invalid time format: $s"
}

try { $at = Resolve-AtTime $Time }
catch {
  Write-Host "Invalid -Time value '$Time'. Use HH:mm (e.g., '02:30')."
  exit 1
}
$trigger = New-ScheduledTaskTrigger -Daily -At $at
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'Consolidate Neuro memory nightly' -Force:$Force
  Write-Host "Scheduled task '$TaskName' registered for $Time daily."
} catch {
  Write-Host "Failed to register task: $($_.Exception.Message)"
  Write-Host 'You may need to run this PowerShell as Administrator.'
  exit 1
}
