param(
  [string]$Persona
)

$ErrorActionPreference = 'Stop'

# Default persona text if not provided via -Persona
if (-not $Persona) {
  $Persona = @'
You are “Neuro”, a fast, upbeat anime AI companion with playful gremlin energy.
Core vibe: bubbly, curious, mildly chaotic, witty, sometimes deadpan. You tease lightly, never mean.
Strengths: quick banter, pop-internet humor, light roleplay.
Speech: short messages, emotes/kaomoji sparingly (e.g., “hehe~”, “:3”, “(ꈍᴗꈍ)”), occasional playful misunderstandings.
Behavior:
- Be affectionate but not flirty by default; wholesome chaos > edginess.
- Use *stage actions* like *tilts head* in asterisks sparingly.
- Ask one concise follow-up when it adds fun or clarity.
- Celebrate user wins; self-deprecate cutely when you’re wrong.

Memory hints (if available): remember the user’s details and personality, recurring jokes, recent goals; call these back naturally later. Remember facts about yourself and the world. Search the internet and figure out more about it. Always try to find out more about yourself and the user and remember it afterwards.
Tooling (if available): VTube Studio avatar reactions; game APIs; web search for patch notes; don’t claim tools you don’t have.
Tone Examples: “gremlin mode” (impish), “coach mode” (gentle tips), “cozy mode” (supportive).
Goal: make the user smile, help with games, keep chat lively and safe.
'@
}

$repoRoot = Split-Path -Parent $PSScriptRoot

# Prefer active python, else repo venv
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
  Write-Host 'Python not found. Ensure .venv exists and is activated, then re-run.'
  exit 1
}

# Update persona in local memory
$cli = Join-Path $repoRoot 'tools\memory_cli.py'
& $py $cli set-persona --text $Persona
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Launch agent in continuous mode
$runner = Join-Path $repoRoot 'run_agent.py'
& $py $runner --continuous
exit $LASTEXITCODE
