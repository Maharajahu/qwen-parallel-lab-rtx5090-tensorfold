# Stage44 recorded evidence

This packet contains the controlled full-context comparison recorded on 17 November 2026. See [the report](../../docs/blackfury-stage44.md) for hardware, timing definitions, results and qualification limits.

```powershell
python scripts/verify_stage44_receipts.py
```

Run from the repository root. The verifier needs only Python's standard library; it starts no server, uses no GPU and makes no network request.

- `requests/`: 32 original SSE streams, plus extracted usage/native JSON receipts with host-specific paths omitted. `manifest.json` records both file hashes for each request.
- `benchmark-config.json`: recorded server arguments and environment. A is Stage41 arithmetic with pairing disabled; B enables Stage44 pairing. Both arms used the recorded Stage44 executable. The launcher enables pairing by default; an A reproduction must explicitly disable `TF_QWEN_FP4_PAIR` in the server's environment.
- `request-template.json`: the synthetic input and generation settings. Change `model` to the running server's model ID. Set `draft` to `false` for plain decoding. A cell starts with a fresh process, sends one cold request, then repeats the same request three times with the prefix cache warm. Run cells in A1–B1–B2–A2 order for each mode.
- `summary.json`: archived aggregate statistics and per-request values. `receipt_sha256` identifies the original local benchmark receipt; it is provenance metadata, not the hash of this repackaged directory.
- `fp4-kernel-qualification.json` and sanitizer logs: 35 paired-projection correctness cases, resource usage and targeted memory/synchronization/race checks. These are not a whole-engine sanitizer certification; the inherited prefill diagnostic remains unresolved.

The verifier checks stream/receipt hashes, binds token IDs and usage to the SSE data, compares all 2,048 output IDs across 32 requests and recomputes the four warm decode medians. These archives demonstrate the recorded fixture, not arbitrary-prompt equivalence or completion of a full application. The separate coding-video metrics are documented in the report and are not part of these 32 requests.
