# BLACKFURY Exact: single-stream optimization and measured results

BLACKFURY Exact is a local TensorFold variant **optimized and qualified primarily for single-stream, long-context inference** on an RTX 5090 32 GB. It preserves the original attention arithmetic in the tested cases. The earlier `fanout`, `shared-context` and `experimental12` variants remain independent.

The main controlled test uses **129,024 input + 2,048 output = 131,072 tokens**, one stream, thinking LOW, greedy decoding with seed 42. Qwen3.8-27B NVFP4, 4-bit DFlash2, nine draft nodes, FP8 KV, BF16 products and FP32 accumulation; active inference components stay in GPU VRAM. No clock changes were used. Measurements were taken on Windows with driver 617.42 on 15 November 2026.

## Controlled 128K single-stream test

| Engine | Cold prefill | Cold decode | Warm-prefix decode median | Warm native first token |
|---|---:|---:|---:|---:|
| Preserved original | 50.347 s | 266.44 tok/s | 268.57 tok/s | 0.237 s |
| Rounded fast control | 50.324 s | 274.08 tok/s | 278.92 tok/s | 0.237 s |
| **BLACKFURY Exact** | **50.435 s** | **278.63 tok/s** | **280.88 tok/s** | **0.235 s** |

The maximum complete warm request was **281.19 tok/s**; range **280.70–281.19 tok/s**. The warm median is **4.58% above the preserved original** in this test. Without DFlash, a separate full-context request measured **57.06 tok/s**.

Two fresh processes per engine, each with one cold request and two warm requests; order original → exact → rounded → rounded → exact → original. Warm requests reuse 128,896 prompt tokens and prefill the remaining 128. Rates exclude prefill. Process/model loading is separate from request time. These are local measurements, not a confidence interval or guaranteed speed. The rounded control produces different text, so its throughput difference does not isolate the kernel improvement.

An initial rounded-control attempt stopped when the analysis script decoded a UTF-8 artifact with Windows CP1252. The parser was corrected and that process was repeated; the two earlier valid processes were retained. The published CSV contains all 18 requests in the accepted comparison.

Peak device VRAM: **27.419 GiB**, including display/driver. Maximum warm model process resident memory: **0.745 GiB**; this is server/driver memory, not CPU inference offload. Maximum observed power **583.7 W**, temperature **76°C**.

[All controlled measurements](../results/blackfury-exact/controlled-128k.json) · [18-request CSV](../results/blackfury-exact/controlled-128k.csv)

[Exact request, recorded commands and independently verifiable byte-match receipts](../results/blackfury-exact/reproduction/README.md). The controlled run used `--thinking-budget 2048`; the general-purpose launcher's default is 1024.

## Real coding loop: peak and average are different

The separate filmed agent run starts from an empty project and conversation, generates twelve scene components sequentially, and then reviews and improves the application. Thinking LOW throughout; OMP 18.20.2; all history and reasoning preserved without compaction. The original geometry/water/display framework is reused, while scene components are generated anew.

| Metric | Measured value | Timing boundary |
|---|---:|---|
| Single-stream sampled peak | **734.17 tok/s** | 736 scheduler-decoded tokens over 1.002 s; short peak |
| Fastest nontruncated request, ≥64 tokens | **504.25 tok/s** | 99 output tokens at 89,020 input tokens; short request |
| Fastest nontruncated request, ≥128 tokens | **425.97 tok/s** | Native average for a complete request |
| Weighted decode rate over nontruncated requests | **330.37 tok/s** | Sum of output-minus-first-token counts / sum of native decode seconds; excludes prefill and tools |
| Complete recorded-loop output rate | **155.76 tok/s** | 77,610 output tokens / 498.267 s; includes prefill, tools, checks and the final truncated output |
| First token / first visible text | **0.887 / 1.128 s** | Already-loaded model; first prompt 3,059 tokens, zero cached prompt tokens |

Whole-file updates preserve a checked file revision and repeat existing source as well as emitting new code. This workload's throughput depends on DFlash acceptance and is **not a prediction for arbitrary new code generation**. Do not compare its 734 tok/s short peak directly with the controlled 281 tok/s complete-request maximum.

The continuous capture contains **10 completed iterations** and an eleventh attempt. It ends at **130,842 / 131,072 occupied tokens: 127,351 input + 3,491 output**, with 230 tokens reserved by the client. The last HTML update was truncated with `finish_reason=length` and **was not applied**. One automatic client retry was canceled before its first token. The planned 129,024-token input-only threshold was not reached; this is a documented capacity stop, not a normally completed final handover. The saved app is byte-identical to the version that passed assembly/browser checks after iteration ten. Zero tool execution errors were recorded in this attempt.

Three earlier attempts were stopped and excluded: two LF/CRLF infrastructure issues and one model-requested unmatched edit. The published attempt begins again from zero and uses one uninterrupted recording; no segments were joined to hide those failures.

## Separate twelve-branch demonstration

The same measured engine also completed a fresh, synchronized twelve-branch scene generation with **thinking OFF**:

- **1079.12 tok/s aggregate sampled peak**, 1,084 decoded tokens over 1.005 s.
- **790.23 tok/s aggregate across the branch group**, 25,949 output tokens over 32.837 s. Includes branch prefill, streaming and receipt completion; excludes group preflight and its warm seed.
- **0.928 s** first visible response, model already loaded; zero tool errors.
- 65,536 configured context, **12,594 maximum actual request input**, 9,303-token common branch prefix. This run did **not** fill the 64K window.

The 1,079 tok/s figure is a combined twelve-lane peak, not the speed of one response. This demonstration differs in context, concurrency and thinking from both single-stream tests and is not a controlled speedup comparison.

[Per-request agent data and timing definitions](../results/blackfury-exact/agent-runs.json)

## Implementation and validation

The long-context attention path separates a fixed prefix, a growing causal tail, and an ordered merge. The exact tail uses 40 blocks in the profiled shape instead of eight, distributing output dimensions across four warps while retaining original reduction and rounding order. The full-model tail kernel mean fell from 94.59 µs to 47.90 µs; prefix and merge means were 186.08 µs and 5.18 µs in the final capture. Native profiling recorded 1,616,553 kernels and 22,736 executions of the new tail.

Qualification of the retained executable included:

- 96 isolated cases with identical intermediate FP32 values and BF16 outputs, input preservation and guard checks.
- Compute Sanitizer memcheck/initcheck without errors and racecheck without errors or warnings.
- Original token IDs and rendered UTF-8 content/reasoning preserved in 37 recorded full-model comparisons: four mode checks, 17 functional requests, ten profiled requests and six final benchmark requests for the exact variant.
- 47/47 build steps and 255/255 focused host tests passed. The static audit found 389 inherited findings and zero new ones.
- One changed CUDA image relative to the preceding retained engine: `qwen35_kv8.fatbin`.

These checks do not prove equivalence for all possible inputs. Broader inherited GLM/modelopt/round-timing tests have known failures; structured output and required tool-call grammar were not qualified because this copy lacked `tfgrammar.dll`. Other GPUs, OSes and configurations are not qualified by these results.

An isolated hardware-counter capture measured 1.488 TB/s for the exact prefix, with replay and cache control. This is a diagnostic kernel measurement, not end-to-end model throughput. CPU attribution and some Windows profiler decoding had symbol/event-decoding limitations; no CPU PMU/IBS result is claimed.

The cumulative patch applies independently to pinned upstream TensorFold `6e9af930261a88bb28ac0bfb157ce8e57e9eea07`. Packaging applied it to a clean checkout and compared all 11,246 source files byte for byte with the retained qualified tree; original license notices remain unchanged. A fresh native rebuild or GPU benchmark was not repeated during packaging, and bit-identical binary reproduction is not claimed.

[Build and start BLACKFURY Exact](../variants/blackfury-exact/README.md) · [Identity and source manifest](../engine-manifest.json)

Packaging checks: the four existing offline setup tests passed; the new launcher started the retained executable with the documented defaults, served a real HTTP completion, and stopped its owned process. [Launcher receipt](../results/blackfury-exact/launcher-smoke.json). This smoke used the retained binary, not a freshly rebuilt executable.
