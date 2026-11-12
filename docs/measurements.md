# Measurement boundaries

The values in `results/recorded-runs.json` describe the original recorded tests. They are not measurements from every machine that installs this package.

## Fanout

The OMP recording generated 13,336 completion tokens in eight scene components. Its 20.1830006-second parallel generation interval includes request handling, prefill, streaming, and static component validation. It excludes the planner, final assembly, browser checks, model loading, and compilation.

The complete OMP turn took 33.542 seconds. Within it, planning took 6.468 seconds and the artifact generation path took 26.903 seconds. These timers overlap; do not add them together. No component needed a repair in this run. The per-component token digests in the result file identify the historical outputs.

The native profile used context 4,096, eight streams, FP8 KV cache, temperature zero, thinking off, zero persistent prompt cache, a four-bit DFlash2 drafter, seven draft nodes, and 0.5 GiB memory reserve. The supplied source patch targets the historical reduced draft-head variant, not the later CUDA Graph optimization.

## Shared context

The shared-context run produced 27,974 completion tokens: 16,044 reasoning tokens and 11,930 other output tokens. The aggregate rate is the completed branch tokens divided by the measured 56.0611133-second parallel generation interval. Thinking tokens count toward throughput. The 101.389-second agent timer includes coordination, integration, and validation; model loading and compilation are excluded.

The runtime used context 65,536, automatic parallel capacity, FP8 KV cache, temperature zero, low thinking with a 2,048-token budget, and a four-bit DFlash2 drafter. The eight tasks shared the conversation and input files. A synchronized batch is refused if all its branches cannot be admitted together; eight branches are not guaranteed for every prompt and VRAM condition.

The original scene run passed initialization, orbit, zoom, pause/resume, reset, and Lumos-button checks. That verifies those interactions in that recorded run, not artistic quality or every possible task.

## Peak rates and comparisons

The 946.845 and 716.289 tokens/s values are the highest approximately one-second aggregate telemetry samples. Seven requests were active at the first peak and five at the second. Neither is an average over the complete test or a single-stream rate.

The workloads differ in context, generated tokens, thinking, scheduling, and verification. They do not demonstrate that disabling thinking causes a particular speedup, or that shared context is slower. Use identical prompts and settings, repeated interleaved runs, and both generation and complete-task timings for a controlled comparison.

Original executables are identified in `engine-manifest.json`. Source reconstruction and patch validation are distinct from bit-for-bit binary reproducibility. Compiler, SDK, line endings, and build paths can change binary hashes even when source is equivalent.

The fanout patch preserves the archived source after test-discovery additions documented after the recorded executable was built. Those additions do not change its runtime arithmetic. The harness files predate the recording and match its observed behavior, but there is no independent immutable hash inventory for the historical harness. Packaging changes make paths and setup portable; the historical throughput has not been reassigned to these changes.
