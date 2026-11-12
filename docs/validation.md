# Validation

The historical performance results and validation of this portable package are separate. `results/recorded-runs.json` contains the former; this page describes the latter.

## Source and dependency checks

- Both native patches apply independently to the pinned clean TensorFold revision. Every changed source file is checked against its SHA-256 and size in `engine-manifest.json`.
- The reconstructed shared-context source matched the 11,222-file inherited source inventory before applying its final changes, and the final 46-file delta after those changes. The complete package patch includes inherited additions that were absent from the old partial patch.
- The fanout source patch matches its three archived modified sources. Its provenance limitation is described in [measurements](measurements.md).
- Both historical executable hashes were verified. They identify the original recordings; they are not required hashes for a new compiler build.
- All 21 checkpoint files were hashed when preparing the public manifest. Setup verifies those hashes again before recording local model paths.
- OMP is pinned by version, upstream commit, size, and SHA-256. Three.js 0.180.0 is downloaded with its package integrity checked.

## Checks without inference

From the repository root, after installing dependencies:

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s scripts -p 'test_setup.py'
& .\.venv\Scripts\python.exe -m unittest discover -s variants/fanout -p 'test_fanout.py'
node --test variants/fanout/omp-agent/test_live_status.mjs variants/fanout/omp-agent/test_scene_view.mjs variants/fanout/omp-agent/test_workspace.mjs variants/fanout/test_geometry.mjs
node --test variants/shared-context/omp-agent/test_shared_agent.mjs variants/shared-context/omp-agent/test_live_status.mjs variants/shared-context/omp-agent/test_branch_view.mjs
& .\.venv\Scripts\python.exe variants/shared-context/omp-agent/smoke_omp.py
```

The packaging checks passed 48 Node tests and eight fanout Python regressions, plus the setup-script tests. Both PowerShell launchers passed syntax parsing. The tests cover stream display, workspace boundaries, geometry helpers, branch coordination, setup source checks, and file-hash rejection. They do not establish GPU performance or general model quality.

The Python dependencies were installed in a fresh `.venv`, the documented Python test commands passed there, and both OMP extensions passed actual RPC startup without sending an inference request.

Both native binaries were rebuilt successfully from their public patches with Zig 0.17.0, CUDA 13.3, and SM120. Build hashes and package checks are recorded in [package-validation.json](../results/package-validation.json). The shared-context historical GPU test was not repeated during packaging. A run using the recorded plan generated all eight components with 13,336 tokens, no repairs, and all eight historical token SHA-256 values matching. The assembled page rendered successfully with eight initialized components and no page errors. Its screenshot was inspected. This is a functional reproduction check; the concurrent compiler workload makes its elapsed time unsuitable as a new benchmark.

## Real inference checks

Run one runtime at a time. The following shared-context check asks the actual model to implement a small parser and tests using two branches, integrates their proposals, verifies the resulting files independently, and optionally checks a second conversation turn:

```powershell
& .\.venv\Scripts\python.exe variants/shared-context/runtime_control.py start
try {
    & .\.venv\Scripts\python.exe variants/shared-context/omp-agent/smoke_model.py --continuation --timeout 300
    if ($LASTEXITCODE -ne 0) { throw 'Model qualification failed; inspect its receipt.' }
} finally {
    & .\.venv\Scripts\python.exe variants/shared-context/runtime_control.py stop
}
```

To regenerate the fanout components from the recorded plan without the OMP interface:

```powershell
& .\.venv\Scripts\python.exe variants/fanout/run_experiment.py --plan variants/fanout/examples/recorded-plan.json --contract compact --request-order 3,2,6,7,4,1,0,5 --output .runtime/work/fanout-recorded-plan-01
```

Choose a new output directory for every run. This command uses the existing plan and therefore excludes fresh planning; it is not a replay of the complete 33.542-second OMP turn. Omit `--plan` to include fresh planning. The wrapper stops the runtime if it started it.

The full eight-branch shared-context scene workload is documented [here](../variants/shared-context/demo/README.md). Inspect the generated page and its browser receipt as well as the token metrics. A passed compilation or static check alone does not establish scene quality.

## Limits

Windows RTX 5090 is the qualified hardware target. Other operating systems, GPUs, maximum contexts, and arbitrary coding projects have not been covered by these tests. These experimental patches do not represent a full upstream TensorFold test-suite certification.

The original native investigation reported an unrelated `launch/gemvSeg` invalidation-test failure on both original and modified source. The selected draft-head/config tests passed, but that result must not be described as the whole native suite passing.

## Experimental twelve-branch package

The new cumulative patch was applied to a separate clean pinned checkout, reconstructing all 11,233 qualified source files byte for byte. Native pre-publication qualification and its limits are documented in [experimental12](experimental12.md).

```powershell
node --test variants/experimental12/omp-agent/test_shared_agent.mjs variants/experimental12/omp-agent/test_live_status.mjs variants/experimental12/omp-agent/test_branch_view.mjs
& .\.venv\Scripts\python.exe variants/experimental12/omp-agent/smoke_omp.py
```

The smoke command starts the actual pinned OMP extension over RPC and requests state only, without starting inference. See [package checks](../results/experimental12-package-validation.json) for the checks performed on the portable files.
