"""Run one prompt with the installed local model, then release an owned GPU session."""
import argparse
from pathlib import Path
import subprocess
import sys
import time

from fanout import DEFAULT_PROMPT
from runtime_control import ROOT, health, owned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--output", type=Path, default=ROOT / "runs" / time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument('--contract', choices=('full','compact'), default='compact')
    parser.add_argument('--request-order', help='Permutation of component ids, comma separated')
    parser.add_argument('--plan', type=Path, help='Reuse a recorded plan and skip fresh planning')
    args = parser.parse_args()
    started_here = owned() is None
    try:
        if started_here:
            command=[sys.executable, str(ROOT / "runtime_control.py"), "start", "--context", "4096", "--reserve-gib", "0.5"]
            if args.contract == 'compact':
                command += ['--tuning', str(ROOT / 'speed/nodes7.json')]
            subprocess.run(command, check=True)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            status = health()
            if status and status.get("status") == "ok":
                if status.get("model") != "qwen27-fanout" or status.get("max_batch_size") != 8:
                    raise RuntimeError("The running server is not the eight-stream experiment")
                if status.get("live", {}).get("connections", 0):
                    raise RuntimeError("The local model is serving another request")
                break
            if owned() is None:
                raise RuntimeError("Model startup failed; read server.stderr.log")
            time.sleep(1)
        else:
            raise RuntimeError("Model did not become ready within 180 seconds")
        subprocess.run([sys.executable, str(ROOT / "fanout.py"), "--prompt", args.prompt,
                        "--output", str(args.output), '--contract', args.contract,
                        *(['--plan', str(args.plan)] if args.plan else []),
                        *(['--request-order', args.request_order] if args.request_order else [])], check=True)
        print(f"HTML: {args.output / 'index.html'}")
        print("Static checks passed. Inspect the generated page for visual and runtime quality.")
    finally:
        if started_here and owned() is not None:
            subprocess.run([sys.executable, str(ROOT / "runtime_control.py"), "stop"], check=True)


if __name__ == "__main__":
    main()
