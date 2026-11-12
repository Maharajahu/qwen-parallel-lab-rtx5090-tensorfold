"""Start, inspect or stop only this experimental twelve-lane profile's native runtime."""
import argparse
import hashlib
import json
import math
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
EXE = REPOSITORY / '.runtime/experimental12/tensorfold-native.exe'
STATE = ROOT / 'runtime-state.json'
PORT = 18198
URL = f'http://127.0.0.1:{PORT}'
MODEL = 'qwen27-sync-speed'
FLAGS = {'compact_kv': 'TF_QWEN_COMPACT_KV', 'compact_scratch': 'TF_QWEN_COMPACT_SCRATCH',
         'compact_taps': 'TF_QWEN_COMPACT_TAPS', 'fine_prefix': 'TF_QWEN_FINE_PREFIX'}
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
        executable = Path(state['executable']).resolve()
        if executable != EXE.resolve():
            raise RuntimeError('Saved executable is outside this experiment ownership boundary')
        if Path(process.exe()).resolve() != executable or process.cmdline() != state['command']:
            raise RuntimeError('Saved PID is not the owned VRAM experiment runtime')
        return process, state
    except psutil.NoSuchProcess:
        return None, state


def stop(process, state):
    if process is not None:
        current, _ = owned()
        if current is None or current.pid != process.pid or abs(current.create_time() - process.create_time()) > .1:
            raise RuntimeError('Refusing stop: runtime ownership changed')
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


def add_options(parser):
    for name in FLAGS:
        parser.add_argument('--' + name.replace('_', '-'), type=int, choices=(0, 1), default=1)
    parser.add_argument('--shared-costs', type=int, choices=(0,1), default=1)
    parser.add_argument('--classic-tail', type=int, choices=(0,1), default=1)
    parser.add_argument('--gpu-profile', action='store_true', help='Diagnostic GPU event timings; not a throughput run')
    parser.add_argument('--draft-nodes', type=int, choices=range(1,16), default=7)
    parser.add_argument('--reserve-memory-gib', type=float, default=.5,
                        help='Existing native TENSORFOLD_MEMORY_RESERVE_GIB setting; default 0.5 GiB')
    parser.add_argument('--memory-limit-gib', type=float, default=None,
                        help='Optional existing native TENSORFOLD_CUDA_MEMORY_LIMIT_GB arena/budget cap')


def tuning_for(args):
    tuning = json.loads((ROOT / 'speed/optimized-graphs.json').read_text())
    tuning.update({key: str(getattr(args, name)) for name, key in FLAGS.items()})
    tuning['TENSORFOLD_MEMORY_RESERVE_GIB'] = str(args.reserve_memory_gib)
    if args.memory_limit_gib is not None:
        tuning['TENSORFOLD_CUDA_MEMORY_LIMIT_GB'] = str(args.memory_limit_gib)
    tuning['TF_QWEN_WINDOW_ROWS'] = '16'
    tuning['TF_DRAFT_NODES'] = str(args.draft_nodes)
    tuning['TF_QWEN_SHARED_COSTS'] = str(args.shared_costs)
    tuning['TF_QWEN_CLASSIC_TAIL'] = str(args.classic_tail)
    if args.gpu_profile:
        tuning['TF_QWEN_GPU_PROFILE'] = '1'
    if not args.no_share:
        tuning.update(TF_QWEN_KV_PAGES='128', TF_QWEN_KV_PAGES_ALL='1', TF_QWEN_KV_SHARE=str(args.snapshots))
    return tuning


def environment_for(tuning, ambient=None):
    ambient = os.environ if ambient is None else ambient
    env = {k: v for k, v in ambient.items() if not k.upper().startswith(('TF_', 'TENSORFOLD_')) and k.upper() != 'FZ_PRICE_BATCHED'}
    env.update(tuning)
    if env.get('CUDA_PATH'):
        env['PATH'] = str(Path(env['CUDA_PATH']) / 'bin') + os.pathsep + env.get('PATH', '')
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'status', 'stop'))
    parser.add_argument('--context', type=int, default=65536)
    parser.add_argument('--parallel', choices=('auto', *(str(n) for n in range(1, 17))), default='12')
    parser.add_argument('--snapshots', type=int, default=1)
    parser.add_argument('--no-share', action='store_true')
    parser.add_argument('--plain', action='store_true')
    add_options(parser)
    args = parser.parse_args()
    if not 2048 <= args.context <= 131072 or not 1 <= args.snapshots <= 32:
        parser.error('Context must be 2048..131072 and snapshots 1..32')
    if not math.isfinite(args.reserve_memory_gib) or args.reserve_memory_gib < .5:
        parser.error('Reserve must be finite and at least 0.5 GiB')
    if args.memory_limit_gib is not None and (not math.isfinite(args.memory_limit_gib) or args.memory_limit_gib <= 0):
        parser.error('Memory limit must be finite and positive')
    process, state = owned()
    if args.action == 'stop':
        print(json.dumps(stop(process, state)))
        return
    if args.action == 'status':
        print(json.dumps({'pid': process.pid if process else None, 'health': health(), 'state': state}))
        return
    settings = {key: getattr(args, key) for key in ('context', 'parallel', 'snapshots', 'no_share', 'plain',
                'reserve_memory_gib', 'memory_limit_gib', 'gpu_profile', 'draft_nodes', 'shared_costs', 'classic_tail', *FLAGS)}
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
    executable = EXE
    command = [str(executable), 'serve', models[0]['path'], '--backend', 'cuda', '--name', MODEL,
               '--host', '127.0.0.1', '--port', str(PORT), '--context', str(args.context),
               '--parallel', str(args.parallel), '--kv-cache', 'fp8', '--prompt-cache-gib', '0',
               '--temperature', '0', '--thinking', '--reasoning-effort', 'low', '--thinking-budget', '2048']
    command += ['--no-drafts'] if args.plain else ['--drafter', models[1]['path'], '--drafter-bits', '4']
    tuning = tuning_for(args)
    env = environment_for(tuning)
    with executable.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    with (ROOT / 'server.stdout.log').open('wb') as out, (ROOT / 'server.stderr.log').open('wb') as err:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
    process = psutil.Process(child.pid)
    state = {'pid': child.pid, 'created': process.create_time(), 'command': command, 'settings': settings,
             'executable': str(executable.resolve()), 'tuning': tuning, 'effective_environment': {
                 k: v for k, v in env.items() if k.startswith(('TF_', 'TENSORFOLD_', 'CUDA_')) or k == 'PATH'},
             'binary_sha256': sha, 'started_at': time.time()}
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
