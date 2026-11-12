param(
    [string]$WorkingDirectory = (Join-Path $PSScriptRoot 'work'),
    [ValidateRange(1,16)][int]$Parallel = 12,
    [ValidateScript({ -not [double]::IsNaN($_) -and -not [double]::IsInfinity($_) -and $_ -ge 0.5 })]
    [double]$ReserveMemoryGiB = 0.5,
    [switch]$Continue
)
$ErrorActionPreference = 'Stop'
$lab = Split-Path $PSScriptRoot -Parent
$runtimeScript = Join-Path $lab 'runtime_control.py'
$repository = Split-Path (Split-Path $lab -Parent) -Parent
$omp = Join-Path $repository '.runtime\omp\omp.exe'
$python = Join-Path $repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
if (-not (Test-Path -LiteralPath $omp)) { throw "Portable OMP missing: $omp" }
if (-not (Test-Path -LiteralPath $runtimeScript)) { throw "Runtime helper missing: $runtimeScript" }
$oldProfile = $env:PI_CODING_AGENT_DIR
$oldPath = $env:PATH
if ($python -ne 'python') { $env:PATH = (Split-Path $python -Parent) + [IO.Path]::PathSeparator + $env:PATH }
$env:PI_CODING_AGENT_DIR = Join-Path $PSScriptRoot 'profile'
$startedHere = $false
try {
    $reserve = $ReserveMemoryGiB.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    $state = (& $python $runtimeScript start --context 65536 --parallel $Parallel --reserve-memory-gib $reserve --compact-kv 1 --compact-scratch 1 --compact-taps 1 --fine-prefix 1 --shared-costs 1 --classic-tail 1) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Shared-context runtime failed to start. Inspect the lab logs.' }
    $startedHere = -not $state.already_running
    $deadline = (Get-Date).AddSeconds(240)
    do {
        $state = (& $python $runtimeScript status) | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the shared-context runtime.' }
        if ($state.health.status -eq 'ok') { break }
        if (-not $state.pid -or (Get-Date) -gt $deadline) { throw 'Shared-context runtime did not become ready. Inspect the lab server logs.' }
        Start-Sleep -Seconds 1
    } while ($true)
    if ($state.health.model -ne 'qwen27-sync-speed') { throw 'Unexpected runtime model identity on port 18198.' }
    New-Item -ItemType Directory -Force -Path $WorkingDirectory | Out-Null
    $sessionArgs = @()
    if ($Continue) { $sessionArgs += '--continue' }
    & $omp --cwd $WorkingDirectory --model TensorFold-Shared/qwen27-sync-speed --system-prompt (Join-Path $PSScriptRoot 'system.txt') --tools workspace_file,workspace_terminal,parallel_tasks --extension (Join-Path $PSScriptRoot 'shared-extension.ts') --no-lsp --no-skills --no-rules --no-context-files --no-extensions --no-title --thinking low --max-fps 120 --spinner-interval 50 @sessionArgs
    if ($LASTEXITCODE -ne 0) { throw "OMP exited with code $LASTEXITCODE" }
} finally {
    try { if ($startedHere) { & $python $runtimeScript stop } }
    finally {
        $env:PI_CODING_AGENT_DIR = $oldProfile
        $env:PATH = $oldPath
    }
}
