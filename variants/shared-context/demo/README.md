# Shared-context scene workload

This is the prepared input for the recorded eight-branch **Lantern Citadel** test. The model generates `part0.js` through `part7.js`, integrates them into a Three.js page, and checks the rendered scene and its controls. No generated component implementations are included in the template.

Complete the repository [installation](../../../README.md#install) first. Both scene examples use the host, geometry helpers, ESLint, and Three.js assets in `variants/fanout`. From the repository root, install the scene dependencies once:

```powershell
npm ci --prefix variants/fanout/lint
& .\.venv\Scripts\python.exe variants/fanout/prepare_assets.py
& .\.venv\Scripts\python.exe -m playwright install chromium
```

Copy the six input files to a fresh workspace **inside this repository**. The assembler finds `variants/fanout` by walking up from the workspace; no personal paths are required. These commands run from the repository root and refuse to overwrite an existing run:

```powershell
$workspace = Join-Path (Get-Location) '.runtime\work\shared-scene-01'
if (Test-Path -LiteralPath $workspace) { throw 'Choose a new workspace name for this run.' }
New-Item -ItemType Directory -Path $workspace -ErrorAction Stop | Out-Null
$template = '.\variants\shared-context\demo\lantern-citadel'
foreach ($name in @('TASK.md', 'plan.json', 'scene-contract.md', 'assemble_scene.py', 'validate_scene.py', 'PROMPT.txt')) {
    Copy-Item -LiteralPath (Join-Path $template $name) -Destination $workspace -ErrorAction Stop
}
.\variants\shared-context\Start-Agent.cmd -WorkingDirectory $workspace
```

Paste this prompt into OMP:

> Build the scene in TASK.md with eight synchronized branches. Integrate the files and verify the result in the browser. Use English throughout; finish with a two-line summary.

The task requests eight synchronized branches with low thinking and a 2,048-token thinking cap. Branches return proposals; the coordinator writes their code, runs `python assemble_scene.py`, and runs `python validate_scene.py`. Browser validation uses software rendering to avoid competing with inference for GPU memory. If a branch fails, preserve the receipts and report the failure; do not silently reduce the branch count.

A completed run contains eight `partN.js` files, `site/index.html`, `assembly-receipt.json`, `browser-receipt.json`, and `site/browser-preview.png` in the workspace. The browser receipt checks initialization, errors, orbit, zoom, pause, resume, Reset view, and Lumos. These checks do not grade artistic quality. Open `site/index.html` to inspect the generated scene.

For another run, repeat the copy commands with a new workspace name such as `shared-scene-02`. Keep the original template clean. The historical throughput is a recorded example; new output, token counts, timings, and validation results may differ.
