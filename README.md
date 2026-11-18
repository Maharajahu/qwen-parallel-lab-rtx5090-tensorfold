<h1 align="center">BLACKFURY Exact V 1.0.1</h1>
<p align="center"><strong>Qwen3.8-27B NVFP4 + DFlash2 on one RTX 5090 32 GB</strong><br>131,072-token context · Single-stream inference · All active inference state in GPU VRAM</p>
<p align="center"><strong>309.53 tok/s warm decode at 129,024 input + 2,048 output tokens</strong><br>Released 17 November 2026</p>

<p align="center">
  <a href="#install"><img src="https://img.shields.io/badge/Build-V_1.0.1-77e7f4?style=for-the-badge&amp;logo=windows&amp;logoColor=white" alt="Build and run BLACKFURY Exact V 1.0.1"></a>
  <a href="#watch"><img src="https://img.shields.io/badge/Watch-Live_coding-77e7f4?style=for-the-badge" alt="Watch the latest live coding session"></a>
  <a href="#performance"><img src="https://img.shields.io/badge/Compare-Performance-30363d?style=for-the-badge" alt="Compare V 1.0.1 with BLACKFURY Exact"></a>
  <a href="#documentation"><img src="https://img.shields.io/badge/Read-Documentation-30363d?style=for-the-badge" alt="Read the build guide, measurements and release notes"></a>
  <a href="https://x.com/ToolBraidComp"><img src="https://img.shields.io/badge/Follow-%40ToolBraidComp-111111?style=for-the-badge&amp;logo=x&amp;logoColor=white" alt="Follow ToolBraid on X"></a>
  <a href="https://buymeacoffee.com/dumitrescup"><img src="https://img.shields.io/badge/Buy_me_a_coffee-FFDD00?style=for-the-badge&amp;logo=buymeacoffee&amp;logoColor=000000" alt="Optional support via Buy Me a Coffee"></a>
</p>
<p align="center">Built on <a href="https://github.com/ashhart/TensorFold"><strong>TensorFold</strong></a>, created by <a href="https://github.com/ashhart">Ash (@ashhart)</a> and its contributors.</p>

Run Qwen3.8-27B locally with an OpenAI-compatible API for coding agents and other clients. V 1.0.1 improves long-context generation over the previous BLACKFURY Exact release while keeping the model, drafter and active inference state on one 32 GB GPU.

## Performance

### Compared with BLACKFURY Exact

| Measurement | BLACKFURY Exact | V 1.0.1 |
|---|---:|---:|
| Warm decode median, DFlash2 enabled | 280.88 tok/s | **309.53 tok/s (+10.20%)** |
| Cold prefill | 50.435 s | 50.368 s |
| Warm first-token latency, median | 0.235 s | 0.236 s |

Same prompt, **129,024 input + 2,048 output tokens**, one stream, thinking LOW and greedy decoding on Windows / RTX 5090 32 GB. The **+10.20%** is the difference between published medians from separate runs on 15 and 17 November; prefill and first-token latency are approximately unchanged. Decode rates exclude prefill and model loading. [Benchmark conditions and results](docs/blackfury-stage44.md#controlled-full-context-result) · [Previous release measurements](docs/blackfury-exact.md#controlled-128k-single-stream-test).

### Filmed coding sessions

| Measurement | BLACKFURY Exact | V 1.0.1 |
|---|---:|---:|
| Weighted decode rate | 330.37 tok/s | **376.54 tok/s** |
| Approximately one-second sampled peak | 734.17 tok/s | **753.29 tok/s** |

These are separate coding sessions with different context lengths and request histories. The peak is a short sample; neither row is a controlled speedup comparison. [Session details and timing definitions](docs/blackfury-stage44.md#real-coding-demonstration).

## Watch

- **[Live coding session — 6 min 03 s](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/download/demos-2026-11/blackfury-exact-v1.0.1-live-1080p60.mp4)**
- **[Generated scene — 20 s](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/download/demos-2026-11/blackfury-exact-v1.0.1-scene-1080p60.mp4)**

A real [Oh My Pi](https://github.com/can1357/oh-my-pi) coding-agent session producing a stylized Three.js castle. Both recordings are **1080p / 60 fps, normal speed**.

## Install

### Requirements

- **Windows x64, RTX 5090 and 32 GB VRAM.** Other platforms have not been qualified.
- Git, **Python 3.11+**, **Zig 0.17.0** and **CUDA Toolkit 13.3**.
- Visual Studio 2022 C++ Build Tools, a Windows SDK and **NVTX3 headers**.

Prepare the Python environment in PowerShell:

```powershell
git clone https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold.git
cd qwen3.8-27b-nvfp4-blackfury-exact-tensorfold
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Continue with the **[V 1.0.1 build and launch guide](variants/blackfury-stage44/README.md)** to download or reuse the pinned checkpoints, build the engine and start the server. Use `.\.venv\Scripts\python.exe` for the guide's Python commands. Run one engine variant at a time.

| Client setting | Value |
|---|---|
| OpenAI-compatible base URL | `http://127.0.0.1:18230/v1` |
| Model ID | `blackfury-exact-v1.0.1` |
| Defaults | One stream, 131,072-token context, thinking LOW, DFlash2 enabled |

Connect your client once the server reports healthy. The native server runs independently of OMP.

**Release status:** Experimental. V 1.0.1 uses approximate FP8 attention and has a known prefill validation issue under investigation. Read the [numerical behavior and known limitations](docs/blackfury-stage44.md#source-build-and-limitations) before use.

<a id="verify"></a>

## Documentation

- [Build, configure and run V 1.0.1](variants/blackfury-stage44/README.md)
- [Benchmarks, methodology and release notes](docs/blackfury-stage44.md)
- [Reproduce and verify the published measurements](results/blackfury-stage44/README.md)
- [Model revisions and download verification](models-manifest.json)

<a id="previous-versions"></a>

Previous releases: [BLACKFURY Exact](variants/blackfury-exact/README.md) · [Twelve-branch engine](variants/experimental12/README.md) · [Shared-context agent](variants/shared-context/demo/README.md) · [Earlier measurements](docs/measurements.md) · [Earlier recordings](docs/videos.md).

## Credits

Powered by TensorFold, with models from the Qwen team / Alibaba, NVIDIA and the DFlash contributors. The coding demo uses Oh My Pi and Three.js. [Full credits and source attribution](CREDITS.md).

## License and support

Local code and changes are provided under [Apache-2.0](LICENSE). Upstream notices are retained in [licenses/TensorFold](licenses/TensorFold); models and dependencies retain their own licenses. No model weights or prebuilt executables are included.

[Report an issue](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/issues/new) with your hardware, version and relevant error.
