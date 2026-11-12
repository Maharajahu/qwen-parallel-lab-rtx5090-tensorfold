param([string]$WorkingDirectory = (Join-Path $PSScriptRoot 'work'))
$ErrorActionPreference = 'Stop'
$lab = Split-Path $PSScriptRoot -Parent
$repository = Split-Path (Split-Path $lab -Parent) -Parent
$python = Join-Path $repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
$omp = Join-Path $repository '.runtime\omp\omp.exe'
if (-not (Test-Path -LiteralPath $omp)) { throw 'OMP missing. Run the repository setup first.' }
$oldProfile = $env:PI_CODING_AGENT_DIR
$oldPython = $env:FANOUT_PYTHON
$oldPath = $env:PATH
if ($python -ne 'python') { $env:PATH = (Split-Path $python -Parent) + [IO.Path]::PathSeparator + $env:PATH }
$env:PI_CODING_AGENT_DIR = Join-Path $PSScriptRoot 'profile'
$env:FANOUT_PYTHON = $python
$runtimeScript = Join-Path (Split-Path $PSScriptRoot -Parent) 'runtime_control.py'
$startedHere = $false
try {
    $runtimeState = (& $python $runtimeScript status) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the local runtime.' }
    $startedHere = -not $runtimeState.pid
    if ($startedHere) {
        & $python $runtimeScript start --context 4096 --parallel 8 --reserve-gib 0.5 --tuning (Join-Path (Split-Path $PSScriptRoot -Parent) 'speed\nodes7.json')
        if ($LASTEXITCODE -ne 0) { throw 'Cannot start the local model.' }
    }
    $deadline = (Get-Date).AddSeconds(180)
    do {
        $runtimeState = (& $python $runtimeScript status) | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the local runtime.' }
        if ($runtimeState.health.status -eq 'ok') { break }
        if (-not $runtimeState.pid -or (Get-Date) -gt $deadline) { throw 'Local model failed to become ready. Inspect server.stderr.log.' }
        Start-Sleep -Seconds 1
    } while ($true)
    if ($runtimeState.health.model -ne 'qwen27-fanout' -or $runtimeState.health.max_batch_size -ne 8) { throw 'Unexpected local model profile.' }
    New-Item -ItemType Directory -Force -Path $WorkingDirectory | Out-Null
    & $omp --cwd $WorkingDirectory --model TensorFold-Local/qwen27-fanout --system-prompt (Join-Path $PSScriptRoot 'system.txt') --tools workspace_file,build_scene,repair_scene --extension (Join-Path $PSScriptRoot 'fanout-extension.ts') --no-lsp --no-skills --no-rules --no-context-files --no-extensions --no-title --thinking off --max-fps 120 --spinner-interval 50
    if ($LASTEXITCODE -ne 0) { throw "OMP exited with code $LASTEXITCODE" }
} finally {
    try { if ($startedHere) { & $python $runtimeScript stop } }
    finally {
        $env:PI_CODING_AGENT_DIR = $oldProfile
        $env:FANOUT_PYTHON = $oldPython
        $env:PATH = $oldPath
    }
}
