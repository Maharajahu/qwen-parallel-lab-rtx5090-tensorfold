"""Start, inspect or stop only this shared-context experiment's native runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import time
import urllib.request

import psutil

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent.parent
EXE = REPOSITORY / '.runtime/shared-context/tensorfold-native.exe'
STATE = ROOT / 'runtime-state.json'
PORT = 18192
URL = f'http://127.0.0.1:{PORT}'
MODEL = 'qwen27-shared-agent'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def health():
    try:
        with OPENER.open(URL + '/health', timeout=3) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def owned():
    if not STATE.exists():
        return None, None
    state = json.loads(STATE.read_text())
    try:
        process = psutil.Process(state['pid'])
        if abs(process.create_time() - state['created']) > .1:
            return None, state
        if Path(process.exe()).resolve() != EXE.resolve() or process.cmdline() != state['command']:
            raise RuntimeError('Saved PID is not the owned shared-context runtime')
        return process, state
    except psutil.NoSuchProcess:
        return None, state


def stop(process, state):
    if process is not None:
        process.terminate()
        process.wait(timeout=30)
        state['stopped_at'] = time.time()
        STATE.write_text(json.dumps(state, indent=2))
        archive = ROOT / 'runtime-history' / str(int(state['started_at'] * 1000))
        archive.mkdir(parents=True, exist_ok=True)
        for source in (STATE, ROOT / 'server.stdout.log', ROOT / 'server.stderr.log'):
            if source.exists():
                shutil.copy2(source, archive / source.name)
    return {'stopped': process.pid if process else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'status', 'stop'))
    parser.add_argument('--context', type=int, default=65536)
    parser.add_argument('--parallel', choices=('auto', *(str(n) for n in range(1, 9))), default='auto')
    parser.add_argument('--snapshots', type=int, default=1)
    parser.add_argument('--no-share', action='store_true')
    parser.add_argument('--plain', action='store_true')
    args = parser.parse_args()
    if not 2048 <= args.context <= 131072 or not 1 <= args.snapshots <= 32:
        parser.error('Context must be 2048..131072 and snapshots 1..32')
    process, state = owned()
    if args.action == 'stop':
        print(json.dumps(stop(process, state)))
        return
    if args.action == 'status':
        print(json.dumps({'pid': process.pid if process else None, 'health': health(), 'state': state}))
        return
    settings = {key: getattr(args, key) for key in ('context', 'parallel', 'snapshots', 'no_share', 'plain')}
    settings.update(thinking=True, reasoning_effort='low', thinking_budget=2048)
    if process:
        if state['settings'] != settings:
            raise RuntimeError('Existing runtime has different settings; stop it before changing configuration')
        current = health()
        if not current or current.get('status') != 'ok' or current.get('model') != MODEL:
            raise RuntimeError('Owned runtime is not healthy')
        print(json.dumps({'pid': process.pid, 'health': current, 'already_running': True}))
        return
    with socket.socket() as check:
        check.bind(('127.0.0.1', PORT))
    models = json.loads((REPOSITORY / '.runtime/models.json').read_text())['models']
    if not all(model.get('verified') for model in models):
        raise RuntimeError('Checkpoint manifest is not verified')
    command = [str(EXE), 'serve', models[0]['path'], '--backend', 'cuda', '--name', MODEL,
               '--host', '127.0.0.1', '--port', str(PORT), '--context', str(args.context),
               '--parallel', str(args.parallel), '--kv-cache', 'fp8', '--prompt-cache-gib', '0',
               '--temperature', '0', '--thinking', '--reasoning-effort', 'low', '--thinking-budget', '2048']
    command += ['--no-drafts'] if args.plain else ['--drafter', models[1]['path'], '--drafter-bits', '4']
    env = {k: v for k, v in os.environ.items() if not k.startswith(('TF_', 'TENSORFOLD_')) and k != 'FZ_PRICE_BATCHED'}
    tuning = json.loads((ROOT / 'speed/optimized-graphs.json').read_text())
    tuning['TENSORFOLD_MEMORY_RESERVE_GIB'] = '0.5'
    tuning['TF_QWEN_WINDOW_ROWS'] = '16'
    if not args.no_share:
        tuning.update(TF_QWEN_KV_PAGES='128', TF_QWEN_KV_PAGES_ALL='1', TF_QWEN_KV_SHARE=str(args.snapshots))
    env.update(tuning)
    if env.get('CUDA_PATH'):
        env['PATH'] = str(Path(env['CUDA_PATH']) / 'bin') + os.pathsep + env.get('PATH', '')
    with EXE.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    with (ROOT / 'server.stdout.log').open('wb') as out, (ROOT / 'server.stderr.log').open('wb') as err:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
    process = psutil.Process(child.pid)
    state = {'pid': child.pid, 'created': process.create_time(), 'command': command, 'settings': settings,
             'tuning': tuning, 'binary_sha256': sha, 'started_at': time.time()}
    STATE.write_text(json.dumps(state, indent=2))
    try:
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError(f'Runtime exited {child.returncode}; inspect server.stdout.log and server.stderr.log')
            current = health()
            if current and current.get('status') == 'ok' and current.get('model') == MODEL:
                state.update(ready_at=time.time(), health=current)
                STATE.write_text(json.dumps(state, indent=2))
                print(json.dumps({'pid': child.pid, 'health': current, 'already_running': False}))
                return
            time.sleep(.5)
        raise TimeoutError('Runtime did not become ready within 600 seconds')
    except BaseException:
        if child.poll() is None:
            stop(process, state)
        raise


if __name__ == '__main__':
    main()
