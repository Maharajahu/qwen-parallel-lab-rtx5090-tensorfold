# BLACKFURY Exact

A TensorFold variant **optimized and qualified primarily for single-stream inference at 128K context** on one RTX 5090 32 GB. It keeps the original attention reduction order and rounding in the tested cases. This is an experimental Windows profile, not a universal GPU optimization.

## Build and start

Use the repository requirements and model verification steps, then:

```powershell
python scripts/setup.py prepare --variant blackfury-exact
python scripts/setup.py build --variant blackfury-exact --zig 'C:\tools\zig\zig.exe' --cuda-path 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3'
python variants/blackfury-exact/runtime_control.py start
```

Replace compiler paths with your installed locations. The existing setup verifies the pinned model checkpoints; `start` requires `.runtime/models.json` from that verification. If CUDA is portable, set `CUDA_PATH` as described in the root README before starting.

Defaults match the measured single-stream profile: 131,072-token context, one lane, thinking LOW, 1,024-token reasoning budget, temperature zero, nine DFlash nodes, FP8 KV, 128-token pages and compact GPU state. The server binds only to `127.0.0.1:18210`; model ID `blackfury-exact`. Connect an OpenAI-compatible client to `http://127.0.0.1:18210/v1`. No OMP extension is required to serve this engine.

```powershell
python variants/blackfury-exact/runtime_control.py status
python variants/blackfury-exact/runtime_control.py stop
```

The helper verifies process identity before stopping its own server. Use only one GPU runtime at a time. The earlier variants and their defaults remain available independently. Twelve-lane use is possible with `--context 65536 --parallel 12`; the separately reported twelve-branch demonstration uses different context and thinking settings and is not the single-stream optimization benchmark.

## Source and evidence

- [Measurements, peak versus aggregate rates, and limitations](../../docs/blackfury-exact.md)
- [Independent cumulative source patch](../../patches/blackfury-exact-native.patch)
- [Pinned source and measured binary identity](../../engine-manifest.json)
- [Controlled 128K results](../../results/blackfury-exact/controlled-128k.json)
- [Controlled-run reproduction and raw byte-match receipts](../../results/blackfury-exact/reproduction/README.md) — uses the recorded 2,048-token thinking budget rather than this launcher's 1,024 default.

The patch reconstructs the retained qualified source byte for byte against the pinned TensorFold revision. The measured executable was built and tested before packaging. Packaging verifies patch application and source identity; it does not claim bit-identical executable reproduction. Upstream licenses and notices are preserved.
