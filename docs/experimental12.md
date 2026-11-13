# Experimental twelve-branch measurements — 12 November 2026

All rates below are aggregate across concurrent branches on one Windows RTX 5090 32 GB. Thinking is LOW with a 2,048-token reasoning cap, and completion counts include reasoning and answer tokens. These are workload-specific measurements.

## Successful filmed run

[Watch the live agent (116 seconds)](https://github.com/Maharajahu/qwen-parallel-lab-rtx5090-tensorfold/releases/download/demos-2026-11/experimental12-live-low-791tps-1080p.mp4) · [Watch the generated scene (25 seconds)](https://github.com/Maharajahu/qwen-parallel-lab-rtx5090-tensorfold/releases/download/demos-2026-11/experimental12-scene-1080p.mp4). Original 1080p recordings; [provenance and checksums](videos.md).

Twelve distinct scene components completed in one native synchronized group:

| Metric | Observed result |
|---|---:|
| Completion tokens | 41,357 |
| Reasoning / other completion tokens | 23,786 / 17,571 |
| Group generation interval | 52.2686 s |
| **Aggregate group throughput** | **791.240 tokens/s** |
| **Highest sampled decode rate** | **1,080.963 tokens/s** |
| Complete coordinator turn | 105.066 s |
| Peak physical VRAM | 30,995 MiB |
| Maximum running branches | 12 |
| Shared cached prefix in every branch | 8,960 tokens |
| Browser checks after integration | 10/10 passed |

The terminal displayed the peak as **1,081.0 tokens/s**. It uses native scheduler decode counters over an approximately one-second moving window, polled every 250 ms. Decode counters exclude each request's first token produced by prefill. This short peak is not the sustained group average or single-stream speed. Its timestamp and native counter snapshot are preserved in [the live result](../results/experimental12-live.json).

The 791.240 rate divides all branch completion tokens by the interval from the first HTTP request start to the last completion. It includes group prefill, synchronization and streaming, but excludes runtime startup, prefix warmup, token preflight and coordinator integration. The full 105.066-second agent turn includes reasoning, reads, generation, file integration and browser validation.

All active model weights, KV, recurrent state, draft state and scratch remained on the GPU. The result is a functional stylized Three.js scene. The native barrier releases the group into a common decode round; delivery jitter is not zero. The first reasoning/text delivery spread was 6.364 ms in this filmed run.

## Controlled replay comparison

Three interleaved control/candidate pairs used identical requests. Each run generated exactly the same 42,816 native token IDs, text and reasoning. This replay distributes eight recorded coding tasks over twelve requests, repeating four tasks; it is separate from the twelve-distinct-task filmed run.

| Metric | Control median | Optimized median |
|---|---:|---:|
| **Aggregate throughput** | **570.783 tokens/s** | **766.073 tokens/s** |
| Group interval | 75.013 s | 55.890 s |
| Mean cached-tail prefill per branch | 154.853 ms | 137.946 ms |
| Mean first-token time per branch | 1.923036 s | 1.721444 s |
| Cold common-prefix prefill | 2.942617 s | 2.925081 s |

The throughput gain is **34.21%**. Candidate throughput ranged from 765.508 to 767.266 tokens/s. Cold prefill was essentially unchanged; the prefill improvement applies to short cached tails. Candidate startup took 59.39 s on a calibration miss and about 18.89 s on validated cache hits. Peak physical VRAM was 30,987 MiB.

This control is the preserved compact-VRAM twelve-lane profile immediately before the final scheduling/prompt-tail changes, not the old eight-branch `shared-context` recording. Source summaries: [six runs](../results/experimental12-final12-pairs.json), [median analysis](../results/experimental12-final12-analysis.json).

## Long context and qualification

One fresh eight-branch comparison reused 61,568 prefix tokens per branch and generated 18,540 tokens. Control: 598.283 tokens/s; optimized: 692.147 tokens/s, with exactly matching requests, native token IDs, text and reasoning. Peak optimized VRAM was 31,009 MiB. This is one pair, not a three-pair median.

Before packaging, the native regression checks passed 533 checks across 58 requests, covering cache adoption, prefix mutation invalidation, plain/draft equivalence, concurrency, cancellation, recovery and restart. The full native host gate passed 6,269 tests with 132 infrastructure skips; the final incremental host gate passed 1,006 newly run tests with 14 skips and other results cached. The final source's lean check reported no new issues in the thirteen changed/new files.

The optional structured-output grammar DLL was absent, so grammar-constrained decoding is not qualified. The 64K context ceiling does not mean twelve simultaneous full-64K continuations fit in VRAM. Actual full-group memory admission is authoritative.

Earlier filmed attempts were unsuccessful: inline handoff reduced the available completion budget, a 6,144-token-per-branch group was refused by memory admission, and uniform 4,096-token caps truncated one complex component. The successful run used file delivery and per-task caps totaling 48,896 completion tokens. These adapter changes did not change the native executable used for the engine benchmarks.

## Public package identity

The cumulative patch applies independently to TensorFold `6e9af930261a88bb28ac0bfb157ce8e57e9eea07`. Applying it to a separate clean checkout reconstructed all 11,233 qualified source files byte for byte. [engine-manifest.json](../engine-manifest.json) records the patch, 106 changed/new source files, complete source-tree digest and reference executable hash.

Reference executable SHA-256: `f2ad0e92a735d7dfd4ef8c61c517b9f9da2ac26301abd31f1e853cf9754d7e3d`.

The qualified binary was built and GPU-tested before packaging. Packaging revalidates source reconstruction, portable integration and offline tests; it does not repeat the GPU benchmarks or claim a bit-identical fresh binary. Build locally with the pinned toolchain using `scripts/setup.py build --variant experimental12`.
