"""Own only this experiment's loopback TensorFold process."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

import psutil

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent.parent
EXE = REPOSITORY / ".runtime/fanout/tensorfold-native.exe"
STATE = ROOT / "runtime-state.json"
PORT = 18190
URL = f"http://127.0.0.1:{PORT}"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def owned():
    if not STATE.exists():
        return None
    state = json.loads(STATE.read_text())
    try:
        proc = psutil.Process(state["pid"])
        if abs(proc.create_time() - state["created"]) > .1:
            return None
        if Path(proc.exe()).resolve() != EXE.resolve() or proc.cmdline() != state["command"]:
            raise RuntimeError("PID is not this experiment's executable")
        return proc
    except psutil.NoSuchProcess:
        return None


def health():
    try:
        with OPENER.open(URL + "/health", timeout=3) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "status", "stop"))
    parser.add_argument("--context", type=int, default=4096)
    parser.add_argument("--parallel", type=int, default=8)
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--drafter-bits", type=int, choices=(0,4), default=4)
    parser.add_argument("--reserve-gib", type=float, default=0.5)
    parser.add_argument("--tuning", type=Path, default=ROOT / "speed/nodes7.json")
    args = parser.parse_args()
    proc = owned()
    if args.action == "stop":
        if proc:
            proc.terminate()
            proc.wait(timeout=30)
        print(json.dumps({"stopped": proc.pid if proc else None}))
        return
    if args.action == "status":
        print(json.dumps({"pid": proc.pid if proc else None, "health": health()}))
        return
    if proc:
        raise RuntimeError("Experiment is already running")
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError("Port is owned by another process")
    manifest = json.loads((REPOSITORY / ".runtime/models.json").read_text())["models"]
    if len(manifest) != 2 or not all(m.get("verified") is True and Path(m["path"]).is_dir() for m in manifest):
        raise RuntimeError("Model downloads have not passed hash verification")
    command = [str(EXE), "serve", manifest[0]["path"], "--name", "qwen27-fanout",
               "--host", "127.0.0.1", "--port", str(PORT), "--parallel", str(args.parallel),
               "--context", str(args.context), "--kv-cache", "fp8", "--prompt-cache-gib", "0",
               "--temperature", "0", "--no-thinking"]
    if args.plain:
        command += ["--no-drafts"]
    else:
        command += ["--drafter", manifest[1]["path"], "--drafter-bits", str(args.drafter_bits)]
    env = dict(os.environ)
    if env.get("CUDA_PATH"):
        env["PATH"] = str(Path(env["CUDA_PATH"]) / "bin") + os.pathsep + env.get("PATH", "")
    # No inherited tuning; each run uses only its explicit experiment settings.
    for name in list(env):
        if name.startswith(("TF_", "TENSORFOLD_")) or name == 'FZ_PRICE_BATCHED':
            env.pop(name)
    if args.reserve_gib is not None:
        if not .5 <= args.reserve_gib <= 8:
            raise ValueError("reserve-gib must be between 0.5 and 8 on this discrete GPU")
        env["TENSORFOLD_MEMORY_RESERVE_GIB"] = str(args.reserve_gib)
    tuning = json.loads(args.tuning.read_text()) if args.tuning else {}
    allowed = {"TF_CUDA_TEST_ATTN_MT2", "TF_NO_TREES", "TF_DRAFT_NODES", "TF_TIMING", "TF_QMMF_HALF_BELOW", "FZ_PRICE_BATCHED", "TENSORFOLD_PREFILL_POLICY", "TENSORFOLD_PREFILL_TOKENS", "TENSORFOLD_PREFILL_ORDER", "TENSORFOLD_PREFILL_SHARE"}
    if not isinstance(tuning, dict) or set(tuning) - allowed or any(not isinstance(v, str) for v in tuning.values()):
        raise ValueError("Tuning must be a string dictionary of supported performance settings")
    env.update(tuning)
    with (ROOT / "server.stdout.log").open("wb") as out, (ROOT / "server.stderr.log").open("wb") as err:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
    state = {"pid": child.pid, "created": psutil.Process(child.pid).create_time(), "reserve_gib": args.reserve_gib,
             "command": command, "tuning": tuning, "started_at": time.time()}
    STATE.write_text(json.dumps(state, indent=2))
    print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
