# Reproduce and verify the controlled 131K run

Engine source package: [`32f9226ba6c7829ffa456ab49d844edbaff092dd`](https://github.com/Maharajahu/qwen-parallel-lab-rtx5090-tensorfold/commit/32f9226ba6c7829ffa456ab49d844edbaff092dd). This evidence supplement changes no engine source. Its cumulative patch applies to TensorFold `6e9af930261a88bb28ac0bfb157ce8e57e9eea07`.

The workload is **129,024 input + 2,048 generated tokens**, including reasoning, in a 131,072-token window. One stream, thinking LOW, greedy, seed 42, DFlash2 with nine draft nodes, FP8 KV. The controlled benchmark used **`--thinking-budget 2048`**. The general BLACKFURY launcher defaults to 1024, so use the recorded command below for this comparison.

Pinned checkpoints (every file's size and SHA-256 is in [models-manifest.json](../../../models-manifest.json)):

- `nvidia/Qwen3.8-27B-NVFP4` revision `482ca0f3832238542f8f5295dde86b5f22711d80`.
- `z-lab/Qwen3.8-27B-DFlash2` revision `50307d4c4cde6860d4eee73e2547cd786fe8e8a4`, loaded with `--drafter-bits 4`.

Measured BLACKFURY executable SHA-256: `18c25d1c724ac8b1ab78e577ee31d349b1ec560428504dcb5f7d378ab2a0d582`.
Preserved original executable SHA-256: `0bea3824def9ccda1afa59985d1ea371059fe489be3efaf3d386e51351211d8b`.
The original is the retained local baseline, not an unmodified upstream build. Source reconstruction was verified; a fresh rebuild is not claimed to reproduce the executable hash.

## Verify without a GPU

From the repository root, with Python 3.11 or newer:

```powershell
python scripts/verify_blackfury_receipts.py
```

Expected: 30 archive files and 12 requests pass. The verifier independently reconstructs output from each original SSE response, compares it with its original JSON receipt, checks native token hashes and counts, and compares all token IDs, content UTF-8 bytes and reasoning UTF-8 bytes against `01-original/cold`. It does not infer equality from a saved Boolean.

All twelve have these hashes:

| Data | SHA-256 |
|---|---|
| 2,048 output token IDs | `ba76c71e48f84db09b3635e4118d28103407d9cd2f9ac4bee7d19aef404763c1` |
| Content UTF-8 | `d6df61d7f9e180a89d428a980a58c00e52b2fa5d4012c623c9cac0354724fcbe` |
| Reasoning UTF-8 | `2eca3f12edbb305885f2eb9b0b9adcbc01590601bdb6b772ad2ec203ad1d83af` |

Token hashing uses comma-separated decimal IDs, no spaces or trailing newline. Text hashing uses UTF-8 without normalization. The raw request, tokenized preflight, SSE responses and JSON receipts are copied byte for byte from the archived experiment. Identity files replace only the executable and two checkpoint paths with placeholders; their original file hashes are retained. No model weights are included.

## Build and launch the same settings

Follow the root [requirements](../../../README.md#requirements). Use the existing environment or create one and install `requirements.txt`. Then:

```powershell
python scripts/setup.py models
python scripts/setup.py prepare --variant blackfury-exact
python scripts/setup.py build --variant blackfury-exact --zig 'C:\tools\zig\zig.exe' --cuda-path 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3'
```

Adjust only compiler locations. To reuse downloaded checkpoints, add `--model-path` and `--drafter-path` to the `models` command as documented in the root README. The original environment was Windows, RTX 5090 32 GB, driver 617.42, CUDA 13.3, Zig 0.17.0, SM120; no clock changes or CPU inference offload. Use one GPU inference process, with no profiler, for comparable timings.

In a PowerShell terminal at the repository root, launch the recorded arguments and tuning:

```powershell
$record = Get-Content -Raw results/blackfury-exact/reproduction/02-exact/identity.json | ConvertFrom-Json
$models = (Get-Content -Raw .runtime/models.json | ConvertFrom-Json).models
if ($models.Count -ne 2 -or @($models | Where-Object { -not $_.verified }).Count) { throw 'Verify both pinned checkpoints first' }
$engine = (Resolve-Path .runtime/blackfury-exact/tensorfold-native.exe).Path
$env:CUDA_PATH = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3'
$env:PATH = "$env:CUDA_PATH\bin;$env:PATH"
Get-ChildItem Env: | Where-Object { $_.Name -match '^(TF_|TENSORFOLD_)' -or $_.Name -eq 'FZ_PRICE_BATCHED' } | Remove-Item
$record.tuning.PSObject.Properties | ForEach-Object { [Environment]::SetEnvironmentVariable($_.Name, [string]$_.Value, 'Process') }
$engineArgs = @($record.command | Select-Object -Skip 1 | ForEach-Object { $_.Replace('<MODEL_CHECKPOINT>', $models[0].path).Replace('<DRAFTER_CHECKPOINT>', $models[1].path) })
Get-FileHash -Algorithm SHA256 -LiteralPath $engine
& $engine @engineArgs
```

Wait for the server to listen on `127.0.0.1:18220`. This uses the actual recorded `--thinking-budget 2048`, not the general launcher's default. In a second PowerShell terminal at the repository root:

```powershell
Invoke-RestMethod http://127.0.0.1:18220/health
New-Item -ItemType Directory .runtime/131k-reproduction -ErrorAction Stop
foreach ($phase in 'cold','warm1','warm2') {
    curl.exe --noproxy '*' --fail-with-body --no-buffer --max-time 180 --header 'Content-Type: application/json' --data-binary '@results/blackfury-exact/reproduction/request.json' --output ".runtime/131k-reproduction/$phase.sse" http://127.0.0.1:18220/v1/chat/completions
    if ($LASTEXITCODE -ne 0) { throw "Request failed: $phase" }
}
python scripts/verify_blackfury_receipts.py --response .runtime/131k-reproduction/cold.sse --response .runtime/131k-reproduction/warm1.sse --response .runtime/131k-reproduction/warm2.sse
```

Stop the server with Ctrl+C after completion. Start a fresh process and use a new output directory for each repetition. Each process has one cold request and two warm requests. The archived experiment order was original → exact → rounded → rounded → exact → original; this packet contains the twelve original/exact equality comparisons. The six rounded-control requests are summarized separately in the [18-request CSV](../controlled-128k.csv), and produced different output.

## Timing and limits

The archived BLACKFURY warm decode median was **280.88 tok/s**, range **280.70–281.19**; the original median was **268.57 tok/s**. Cold prefill was **50.435 s / 2,558.2 tok/s**. These are full-request measurements, excluding process/model load. Warm requests reused 128,896 input tokens and processed 128 new ones. The native `tensorfold` fields in each SSE contain per-request decode, prefill and first-token timings.

These receipts cover the controlled synthetic reference-archive/SQLite-queue prompt, not the separate filmed castle coding loop or its 734 tok/s one-second peak. They establish equality for these twelve archived requests, not universal equivalence. Output reaches its 2,048-token budget; this is a fixed-length throughput test, not a claim that the requested queue implementation was completed.

The supplement was checked by replaying archived SSE and comparing file hashes. No new GPU benchmark or fresh build was performed while packaging it. The launch and capture commands reproduce the archived settings but were not rerun as part of packaging.
