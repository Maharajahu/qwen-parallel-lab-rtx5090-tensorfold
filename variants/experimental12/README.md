# Experimental synchronized 12-branch engine

Qwen3.8-27B NVFP4 with a 4-bit DFlash2 drafter, shared GPU prompt state and twelve synchronized branches on one RTX 5090 32 GB. Thinking is LOW with a 2,048-token reasoning cap. This is the newest experimental variant; the two earlier variants remain available.

## Install and run

Complete the repository [requirements and setup](../../README.md#install). To install only this native variant, use `--variant experimental12` instead of `--variant all`. Model and OMP installation are shared across variants.

From the repository root in PowerShell:

```powershell
.\variants\experimental12\Start-Agent.cmd -WorkingDirectory 'C:\work\experimental12'
```

Add `-Continue` to resume the latest conversation in that workspace. The default is twelve lanes and a 64K per-request context ceiling. `-Parallel 1..16` changes the reserved lane count; sixteen is an experimental API limit, not a guarantee that a complete group will fit. Native VRAM admission decides whether the full group can run. Long prompts or large output reservations may be refused. No CPU offload or serial fallback is enabled by this profile.

The coordinator uses `parallel_tasks` for independent proposals, integrates the files and runs checks. For large batches, `delivery="files"` saves complete proposals and returns their paths instead of injecting every proposal into the coordinator history. Each task can specify `max_tokens` up to the batch ceiling. Failed or truncated branches are reported as errors.

The [twelve-component scene workload](demo/README.md) contains the exact task contract and token budgets used in the successful recording.

## Runtime control

```powershell
& .\.venv\Scripts\python.exe variants/experimental12/runtime_control.py status
& .\.venv\Scripts\python.exe variants/experimental12/runtime_control.py stop
```

The runtime binds to `127.0.0.1:18198`. The launcher stops a process it started when OMP exits, with PID, executable and command-line ownership checks. Run one variant at a time.

## Native changes

The cumulative patch includes shared prompt state, synchronized admission, support for up to sixteen lanes, compact KV/recurrent state and scratch allocations, compact draft taps and finer prefix allocation. The final speed changes calibrate scheduling against measured multi-lane verification costs and use the existing classic projection tile for short NVFP4 prompt tails of 17–256 rows. Larger prefill chunks retain their previous dispatch.

The final speed changes preserve weights, tokenizer, activation arithmetic, FP8 KV precision, seven draft nodes and the sixteen-row per-lane window. Their two switches, `TF_QWEN_SHARED_COSTS` and `TF_QWEN_CLASSIC_TAIL`, are enabled by default. The calibration cache validates executable, model, device/driver and lane-layout identity, with drift spot checks.

See [measurements and limits](../../docs/experimental12.md) for the controlled comparison, the separate live result and the sampled peak.
