# Original demonstration recordings

The recordings are hosted as public [GitHub release assets](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/tag/demos-2026-11). They are the existing final MP4 exports, uploaded without re-encoding. All eight are H.264, 1920 × 1080, with no audio.

| Experiment | Recording | Duration | Description |
|---|---|---:|---|
| BLACKFURY Exact | [Single-stream live agent](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/download/demos-2026-11/blackfury-exact-live-low-128k-1080p.mp4) | 498.267 s | One continuous thinking-LOW coding loop: ten completed iterations, ending at 130,842 / 131,072 occupied tokens. The final truncated edit was not applied. |
| BLACKFURY Exact | [Daylight scene walkthrough](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/download/demos-2026-11/blackfury-exact-scene-daylight-1080p.mp4) | 30.450 s | The preserved working scene after iteration ten of that same single-stream session. |
| Fanout | [Live agent](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/download/demos-2026-11/fanout-live-660tps-1080p.mp4) | 41.452 s | The actual 660.754 tokens/s OMP recording, with eight live component streams. |
| Fanout | [Scene walkthrough](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/download/demos-2026-11/fanout-scene-1080p.mp4) | 19.928 s | Separately recorded from an identical generated artifact: all eight components, assembled JavaScript and HTML match the live run. |
| Shared context | [Live agent](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/download/demos-2026-11/shared-context-live-low-499tps-1080p.mp4) | 112.883 s | The actual 498.991 tokens/s recording, with low thinking, eight synchronized branches, integration and validation. |
| Shared context | [Scene walkthrough](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/download/demos-2026-11/shared-context-scene-low-1080p.mp4) | 24.940 s | The generated Lantern Citadel scene from that thinking-low run. |
| Experimental twelve branches | [Live agent](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/download/demos-2026-11/experimental12-live-low-791tps-1080p.mp4) | 116.417 s | Twelve synchronized LOW-thinking branches; 41,357 completion tokens in a 52.27-second generation interval. |
| Experimental twelve branches | [Scene walkthrough](https://github.com/Maharajahu/qwen3.8-27b-nvfp4-blackfury-exact-tensorfold/releases/download/demos-2026-11/experimental12-scene-1080p.mp4) | 24.946 s | Separate recording of the scene produced by that run. |

Live recordings retain the captured timing. Their duration includes time around the task; the complete-agent and generation intervals are reported separately in [measurements](measurements.md). The BLACKFURY coding loop is distinct from the controlled 129,024-input + 2,048-output benchmark; its 734.17 tok/s sampled peak is not the full-context benchmark rate. The Three.js scenes are stylized demonstrations.

The README previews are original frames from these outputs. They are linked to their corresponding scene walkthroughs. MP4 links may download the file depending on the browser; open the downloaded file in a video player.

File sizes, SHA-256 hashes and the source capture names are recorded in [media.json](media.json). The same hashes are available in the release's `SHA256SUMS.txt`, `experimental12-SHA256SUMS.txt` and `blackfury-exact-SHA256SUMS.txt`. Model weights and private conversation logs are not part of this media release.
