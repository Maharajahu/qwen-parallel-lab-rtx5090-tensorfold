# BLACKFURY Exact V 1.0.1

Technical build identifier and package directory: `blackfury-stage44`.

Single-stream Qwen3.8-27B NVFP4 + DFlash2 for Windows / RTX 5090. This variant enables the paired FP4 gate/up kernel and the inherited approximate FP8 attention path. Read the [results and qualification limits](../../docs/blackfury-stage44.md), including the unresolved inherited-prefill race diagnostic, before use. The previous BLACKFURY Exact build remains available separately.

Use the repository's existing Python environment and model setup. Requirements: Zig 0.17.0, CUDA Toolkit 13.3 (SM120a target), Visual Studio C++ tools and installed NVTX3 headers (for example from Nsight Systems). No model or active inference state is offloaded to CPU RAM.

```powershell
python scripts/setup.py models
python scripts/setup.py prepare --variant blackfury-stage44
python scripts/setup.py build --variant blackfury-stage44 --zig 'C:\tools\zig\zig.exe' --cuda-path 'C:\tools\cuda-13.3' --nvtx-include 'C:\tools\Nsight Systems\target-windows-x64\nvtx\include'
python variants/blackfury-stage44/runtime_control.py start
```

Replace compiler/toolkit/header paths with their installed locations. The include directory must contain `nvtx3/nvToolsExt.h`. With portable CUDA, set `$env:CUDA_PATH` to the same toolkit before launching. Model reuse via `--model-path` and `--drafter-path` is supported by `scripts/setup.py models`, as for the other variants.

Endpoint: `http://127.0.0.1:18230/v1`; model ID: `blackfury-exact-v1.0.1`. Defaults: one stream, context 131,072, thinking LOW / budget 1,024, greedy, DFlash2 enabled, no persistent CPU prompt cache. Use only one engine variant at a time.

```powershell
python variants/blackfury-stage44/runtime_control.py status
python variants/blackfury-stage44/runtime_control.py stop
python scripts/verify_stage44_receipts.py
```

`stop` validates process identity before terminating the owned server. No Windows restart or driver/clock/power change is performed. The controlled benchmark used `--thinking-budget 2048 --shared-costs 1 --classic-tail 1`; the coding demonstration used the default 1,024-token budget and disabled those two options. `--plain` disables DFlash2. Reproduction requires the archived request and cache/order conditions, not just the same launch command.
